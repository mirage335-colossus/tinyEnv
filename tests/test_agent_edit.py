#!/usr/bin/env python3
"""Guarded source saves, including stale ownership and interrupted publication."""
import importlib.util
from contextlib import contextmanager
import json
import os
from pathlib import Path
import selectors
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('agent_edit', ROOT / 'tools/agent_edit.py')
EDIT = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(EDIT)
from test_agent_session import record


@unittest.skipUnless(os.name == 'posix' and hasattr(os, 'listxattr'), 'POSIX metadata checks required')
class Saves(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='agent_edit-test-')
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.board = self.root / 'board'
        (self.board / 'sessions').mkdir(parents=True)
        self.source = self.root / 'source.py'
        self.before = b'def value():\n    return 1\n'
        self.after = b'def value():\n    return 2\n'
        self.source.write_bytes(self.before)
        self.source.chmod(0o751)
        self.record_path = self.board / 'sessions/worker.md'
        self.save_record(f'- file: {self.source}')

    def save_record(self, claims, *, state='active'):
        self.record_path.write_text(record(claims=claims, state=state,
            handoff='- Scope inventory: complete\n- Scope: none'))
        self.record_hash = EDIT.digest(self.record_path.read_bytes())

    def edit(self, **options):
        defaults = dict(board=self.board, session='worker', path=self.source,
                        expected_sha256=EDIT.digest(self.before), content=self.after,
                        record_sha256=self.record_hash)
        defaults.update(options)
        return EDIT.edit(**defaults)

    def assert_original(self):
        self.assertEqual(self.source.read_bytes(), self.before)
        self.assertEqual(list(self.root.glob('.agent_edit-*')), [])

    def test_atomic_save_preserves_mode_and_reservation(self):
        inode = self.source.stat().st_ino
        saved_record = self.record_path.read_bytes()
        receipt = self.edit()
        self.assertEqual(self.source.read_bytes(), self.after)
        self.assertNotEqual(self.source.stat().st_ino, inode)
        self.assertEqual(self.source.stat().st_mode & 0o7777, 0o751)
        self.assertEqual(self.record_path.read_bytes(), saved_record)
        self.assertFalse(receipt['claims_released'])
        self.assertEqual(receipt['sha256'], EDIT.digest(self.after))

    def test_covering_directory_reservation(self):
        self.save_record(f'- directory: {self.root}')
        self.edit()
        self.assertEqual(self.source.read_bytes(), self.after)

    def test_conservative_alias_overlap_does_not_grant_file_authority(self):
        for name in ('SOURCE.py', 'caf\u00e9.py', 'cafe\u0301.py'):
            (self.root / name).write_bytes(self.before)
        for owned, other in [('source.py', 'SOURCE.py'), ('caf\u00e9.py', 'cafe\u0301.py')]:
            with self.subTest(owned=owned):
                owner_path, target = self.root / owned, self.root / other
                if os.path.samefile(owner_path, target):
                    continue  # This spelling is a real alias on this filesystem.
                self.save_record(f'- file: {owner_path}')
                with self.assertRaisesRegex(EDIT.EditError, 'reservation'):
                    self.edit(path=target)
                self.assertEqual(target.read_bytes(), self.before)
                self.assertEqual(owner_path.read_bytes(), self.before)

    def test_conservative_directory_overlap_does_not_grant_authority(self):
        owned, other = self.root / 'owned', self.root / 'OWNED'
        owned.mkdir()
        other.mkdir(exist_ok=True)
        if os.path.samefile(owned, other):
            self.skipTest('filesystem aliases case-varied directory names')
        target = other / 'source.py'
        target.write_bytes(self.before)
        self.save_record(f'- directory: {owned}')
        with self.assertRaisesRegex(EDIT.EditError, 'reservation'):
            self.edit(path=target)
        self.assertEqual(target.read_bytes(), self.before)

    def test_missing_released_stale_or_foreign_reservation_never_stages(self):
        for claims, state in [('None.', 'active'), ('None.', 'done')]:
            with self.subTest(claims=claims, state=state):
                self.save_record(claims, state=state)
                with mock.patch.object(EDIT, '_staged') as stage:
                    with self.assertRaises(EDIT.EditError):
                        self.edit()
                    stage.assert_not_called()
                self.assert_original()
        self.save_record(f'- file: {self.source}')
        with self.assertRaises(EDIT.EditError):
            self.edit(record_sha256='0' * 64)
        (self.board / 'sessions/other.md').write_text(record(name='other', claims=f'- file: {self.source}'))
        with self.assertRaises(EDIT.EditError):
            self.edit()
        self.assert_original()

    def test_failed_acquisition_does_not_authorize_edit(self):
        self.save_record('None.')
        (self.board / 'sessions/other.md').write_text(record(name='other', claims=f'- file: {self.source}'))
        scope = {'kind': 'file', 'value': str(self.source)}
        reviewed = EDIT.SESSION.review(self.board, scopes=[scope])
        with self.assertRaises(ValueError):
            EDIT.SESSION.commit(self.board, 'worker', record(claims=f'- file: {self.source}'),
                reviewed, expected_sha256=self.record_hash,
                handoffs_reviewed=list(reviewed['relevant_handoffs']))
        with self.assertRaises(EDIT.EditError):
            self.edit()
        self.assert_original()

    def test_stale_preimage_and_oversize_content_rejected(self):
        for options in [{'expected_sha256': '0' * 64}, {'content': b'x' * (EDIT.MAX_BYTES + 1)}]:
            with self.subTest(options=list(options)), self.assertRaises(EDIT.EditError):
                self.edit(**options)
            self.assert_original()

    def test_clean_mutex_contention_before_and_after_staging_is_distinct(self):
        original = EDIT.SESSION.registry_mutex
        for blocked_call in (1, 2):
            calls = 0
            def busy(*args, **kwargs):
                nonlocal calls
                calls += 1
                if calls == blocked_call:
                    raise EDIT.SESSION.CoordinationError('busy', code='registry_busy',
                                                        stage='acquisition', retry_action='bounded_backoff')
                return original(*args, **kwargs)
            with self.subTest(blocked_call=blocked_call), mock.patch.object(EDIT.SESSION, 'registry_mutex', busy):
                with self.assertRaises(EDIT.EditError) as raised:
                    self.edit()
                self.assertEqual(raised.exception.code, 'registry_busy')
                self.assertFalse(raised.exception.uncertain)
                self.assertEqual(raised.exception.as_dict()['retry_action'], 'bounded_backoff')
            self.assert_original()

    def test_mutex_cleanup_uncertainty_is_not_retryable_contention(self):
        failure = EDIT.SESSION.CoordinationError('failed cleanup', code='cleanup_uncertain',
                                                stage='cleanup', uncertain=True)
        with mock.patch.object(EDIT.SESSION, 'registry_mutex', side_effect=failure):
            with self.assertRaises(EDIT.EditError) as raised:
                self.edit()
        self.assertTrue(raised.exception.uncertain)
        self.assertEqual(raised.exception.as_dict()['retry_action'], 'reconcile_saved_state')
        self.assert_original()

    def test_alias_hardlink_directory_and_special_modes_rejected(self):
        alias = self.root / 'alias'
        alias.symlink_to(self.source)
        with self.assertRaises(EDIT.EditError):
            self.edit(path=alias)
        link = self.root / 'hardlink'
        os.link(self.source, link)
        with self.assertRaises(EDIT.EditError):
            self.edit()
        link.unlink()
        self.source.chmod(0o4751)
        with self.assertRaises(EDIT.EditError):
            self.edit()
        self.source.chmod(0o751)
        with self.assertRaises(EDIT.EditError):
            self.edit(path=self.root)
        self.assert_original()

    def test_extended_metadata_not_silently_lost(self):
        try:
            os.setxattr(self.source, 'user.agent_edit-test', b'kept')
        except OSError as error:
            self.skipTest('fixture filesystem does not support user xattrs: ' + str(error))
        with self.assertRaises(EDIT.EditError):
            self.edit()
        self.assertEqual(os.getxattr(self.source, 'user.agent_edit-test'), b'kept')
        self.assert_original()

    def test_staging_failure_and_prepublication_guard_failure_preserve_source(self):
        with mock.patch.object(EDIT.os, 'fchmod', side_effect=OSError('staging failed')):
            with self.assertRaises(EDIT.EditError) as raised:
                self.edit()
            self.assertFalse(raised.exception.uncertain)
        self.assert_original()
        real = EDIT._reservation
        calls = 0
        def changed(*args):
            nonlocal calls
            calls += 1
            if calls == 2:
                self.save_record('None.')
            return real(*args)
        with mock.patch.object(EDIT, '_reservation', side_effect=changed):
            with self.assertRaises(EDIT.EditError):
                self.edit()
        self.assert_original()

    def test_staging_cleanup_inspection_failure_is_uncertain(self):
        real_stat = EDIT.os.stat
        def denied(path, *args, **kwargs):
            if str(path).startswith('.agent_edit-'):
                raise PermissionError('cleanup inspection denied')
            return real_stat(path, *args, **kwargs)
        original = EDIT._staged
        @contextmanager
        def injected(*args):
            with mock.patch.object(EDIT.os, 'fchmod', side_effect=OSError('stage failed')), \
                    mock.patch.object(EDIT.os, 'stat', side_effect=denied):
                with original(*args) as staged:
                    yield staged
        with mock.patch.object(EDIT, '_staged', injected):
            with self.assertRaises(EDIT.EditError) as raised:
                self.edit()
        self.assertTrue(raised.exception.uncertain)
        self.assertEqual(raised.exception.code, 'edit_cleanup_uncertain')
        self.assertEqual(self.source.read_bytes(), self.before)
        self.assertEqual(len(list(self.root.glob('.agent_edit-*'))), 1)

    def test_staging_initial_identity_failure_closes_fd_and_retains_unknown_file(self):
        real_open, real_fstat = EDIT.os.open, EDIT.os.fstat
        owned = []
        def opened(path, *args, **kwargs):
            fd = real_open(path, *args, **kwargs)
            if str(path).startswith('.agent_edit-'):
                owned.append(fd)
            return fd
        def failed(fd):
            if fd in owned:
                raise OSError('initial stage identity unavailable')
            return real_fstat(fd)
        original = EDIT._staged
        @contextmanager
        def injected(*args):
            with mock.patch.object(EDIT.os, 'open', side_effect=opened), \
                    mock.patch.object(EDIT.os, 'fstat', side_effect=failed):
                with original(*args) as staged:
                    yield staged
        with mock.patch.object(EDIT, '_staged', injected):
            with self.assertRaises(EDIT.EditError) as raised:
                self.edit()
        self.assertTrue(raised.exception.uncertain)
        self.assertEqual(raised.exception.code, 'edit_cleanup_uncertain')
        with self.assertRaises(OSError):
            real_fstat(owned[0])
        self.assertEqual(self.source.read_bytes(), self.before)
        self.assertEqual(len(list(self.root.glob('.agent_edit-*'))), 1)

    def test_staging_close_failure_is_uncertain(self):
        real_fdopen = EDIT.os.fdopen
        def wrapped(fd, mode, *args, **kwargs):
            output = real_fdopen(fd, mode, *args, **kwargs)
            if mode != 'wb':
                return output
            wrapper = mock.Mock(wraps=output)
            def close():
                output.close()
                raise OSError('lost close result')
            wrapper.close.side_effect = close
            return wrapper
        original = EDIT._staged
        @contextmanager
        def injected(*args):
            with mock.patch.object(EDIT.os, 'fdopen', side_effect=wrapped):
                with original(*args) as staged:
                    yield staged
        with mock.patch.object(EDIT, '_staged', injected):
            with self.assertRaises(EDIT.EditError) as raised:
                self.edit()
        self.assertTrue(raised.exception.uncertain)
        self.assertEqual(raised.exception.code, 'edit_cleanup_uncertain')
        self.assert_original()

    def test_equal_bytes_new_inode_between_stage_and_save_is_rejected(self):
        real = EDIT._reservation
        calls = 0
        def changed(*args):
            nonlocal calls
            calls += 1
            if calls == 2:
                other = self.root / 'replacement'
                other.write_bytes(self.before)
                os.replace(other, self.source)
            return real(*args)
        with mock.patch.object(EDIT, '_reservation', side_effect=changed):
            with self.assertRaises(EDIT.EditError):
                self.edit()
        self.assert_original()

    def test_replace_then_error_is_uncertain_and_never_releases_claim(self):
        replace = EDIT.os.replace
        def uncertain(*args, **kwargs):
            replace(*args, **kwargs)
            raise OSError('lost completion')
        with mock.patch.object(EDIT.os, 'replace', side_effect=uncertain):
            with self.assertRaises(EDIT.EditError) as raised:
                self.edit()
        self.assertTrue(raised.exception.uncertain)
        self.assertEqual(raised.exception.code, 'edit_save_uncertain')
        self.assertEqual(self.source.read_bytes(), self.after)
        self.assertEqual(EDIT.digest(self.record_path.read_bytes()), self.record_hash)

    def test_directory_flush_failure_after_save_is_uncertain(self):
        fsync = EDIT.os.fsync
        def fail_directory(fd):
            import stat
            if stat.S_ISDIR(os.fstat(fd).st_mode):
                raise OSError('directory flush failed')
            return fsync(fd)
        with mock.patch.object(EDIT.os, 'fsync', side_effect=fail_directory):
            with self.assertRaises(EDIT.EditError) as raised:
                self.edit()
        self.assertTrue(raised.exception.uncertain)
        self.assertEqual(self.source.read_bytes(), self.after)
        self.assertEqual(EDIT.digest(self.record_path.read_bytes()), self.record_hash)

    def test_cleanup_never_deletes_replaced_staging_file(self):
        real = EDIT._reservation
        calls = 0
        def replaced(*args):
            nonlocal calls
            calls += 1
            if calls == 2:
                temporary = next(self.root.glob('.agent_edit-*'))
                foreign = self.root / 'foreign'
                foreign.write_bytes(b'foreign data')
                os.replace(foreign, temporary)
                raise EDIT.EditError('guard rejected')
            return real(*args)
        with mock.patch.object(EDIT, '_reservation', side_effect=replaced):
            with self.assertRaises(EDIT.EditError) as raised:
                self.edit()
        self.assertTrue(raised.exception.uncertain)
        self.assertEqual(self.source.read_bytes(), self.before)
        self.assertEqual(next(self.root.glob('.agent_edit-*')).read_bytes(), b'foreign data')

    def test_identical_foreign_staging_inode_is_not_published_or_deleted(self):
        real = EDIT._reservation
        calls = 0
        def replaced(*args):
            nonlocal calls
            calls += 1
            if calls == 2:
                temporary = next(self.root.glob('.agent_edit-*'))
                foreign = self.root / 'foreign'
                foreign.write_bytes(temporary.read_bytes())
                foreign.chmod(temporary.stat().st_mode & 0o777)
                os.replace(foreign, temporary)
            return real(*args)
        with mock.patch.object(EDIT, '_reservation', side_effect=replaced):
            with self.assertRaises(EDIT.EditError) as raised:
                self.edit()
        self.assertTrue(raised.exception.uncertain)
        self.assertEqual(self.source.read_bytes(), self.before)
        self.assertEqual(next(self.root.glob('.agent_edit-*')).read_bytes(), self.after)

    def test_claimed_board_files_cannot_bypass_publication_protocol(self):
        for relative in ['sessions/other.md', 'messages/message.md', 'registry.lock/owner.md',
                         'artifacts/file', 'notes/file']:
            with self.subTest(relative=relative):
                path = self.board / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(self.before)
                self.save_record(f'- file: {path}')
                with mock.patch.object(EDIT, '_reservation') as reservation:
                    with self.assertRaisesRegex(EDIT.EditError, 'dedicated publication'):
                        self.edit(path=path)
                    reservation.assert_not_called()
                self.assertEqual(path.read_bytes(), self.before)

    def test_staging_killed_before_publication_leaves_original_and_claim(self):
        script = '''import importlib.util,sys
from pathlib import Path
spec=importlib.util.spec_from_file_location('edit',sys.argv[1]);e=importlib.util.module_from_spec(spec);spec.loader.exec_module(e)
real=e.SESSION.registry_mutex
calls=0
def pause(*args,**kw):
 global calls
 calls+=1
 if calls==1:return real(*args,**kw)
 print('staged',flush=True);input()
e.SESSION.registry_mutex=pause
e.edit(sys.argv[2],'worker',sys.argv[3],sys.argv[4],b'new complete bytes',record_sha256=sys.argv[5])
'''
        child = subprocess.Popen([sys.executable, '-B', '-c', script, str(ROOT / 'tools/agent_edit.py'),
            str(self.board), str(self.source), EDIT.digest(self.before), self.record_hash],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        try:
            with selectors.DefaultSelector() as selector:
                selector.register(child.stdout, selectors.EVENT_READ)
                self.assertTrue(selector.select(15), 'child never reached staged barrier')
            self.assertEqual(child.stdout.readline().strip(), 'staged')
            child.kill()
            child.communicate(timeout=5)
            self.assertEqual(self.source.read_bytes(), self.before)
            self.assertEqual(EDIT.digest(self.record_path.read_bytes()), self.record_hash)
            stages = list(self.root.glob('.agent_edit-*'))
            self.assertEqual(len(stages), 1)
            self.assertEqual(stages[0].read_bytes(), b'new complete bytes')
        finally:
            if child.poll() is None:
                child.kill()
            child.communicate(timeout=5)

    def test_cli_success_and_structured_rejection(self):
        request = dict(board=str(self.board), session='worker', path=str(self.source),
                       expected_sha256='0' * 64, content=self.after.decode(), record_sha256=self.record_hash)
        command = [sys.executable, '-B', str(ROOT / 'tools/agent_edit.py')]
        result = subprocess.run(command, input=json.dumps(request), text=True, capture_output=True)
        self.assertEqual(result.returncode, 2)
        self.assertFalse(json.loads(result.stderr)['uncertain'])
        self.assert_original()
        request['expected_sha256'] = EDIT.digest(self.before)
        result = subprocess.run(command, input=json.dumps(request), text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)['sha256'], EDIT.digest(self.after))

    def test_cli_malformed_content_is_structured_and_does_not_save(self):
        command = [sys.executable, '-B', str(ROOT / 'tools/agent_edit.py')]
        for request in ([], {}, {'content': 1}, {'content': None}, {'content': []}):
            with self.subTest(request=request):
                result = subprocess.run(command, input=json.dumps(request), text=True, capture_output=True)
                self.assertEqual(result.returncode, 2)
                self.assertFalse(json.loads(result.stderr)['uncertain'])
                self.assert_original()


if __name__ == '__main__':
    unittest.main()
