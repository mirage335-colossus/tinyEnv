#!/usr/bin/env python3
"""Checked coordination transactions against isolated, bounded board fixtures."""
import hashlib
from contextlib import contextmanager
import importlib.util
import json
import os
from pathlib import Path
import selectors
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('agent_session', ROOT / 'tools/agent_session.py')
SESSION = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(SESSION)


def record(name='worker', claims='None.', jobs='none', handoff='- None.', state='active'):
    terminal = state == 'done'
    return f'''# {name}
- Tool / host / local chat reference: test / local / fixture
- Parent / read-only helpers: none
- Task and approach: bounded transaction fixture
- Checkout / coordination root (absolute physical paths): /fixture / /fixture/board
- Branch / starting HEAD / current HEAD: main / abc / abc
- Starting worktree and index changes (including work owned by others): none
## Current checkpoint
- State: {state}
- Updated (UTC): 2000-01-01T12:00:00Z
- Last meaningful progress (UTC): 2000-01-01T12:00:00Z
- Last inbox check (UTC): 2000-01-01T12:00:00Z
- Next check (UTC) / action: {'none' if terminal else '2100-01-01T00:00:00Z'} / fixture action
- Liveness mode / cadence: checkpoint / five minutes
- Last heartbeat (UTC), if supervised: none
- Run token / heartbeat file and writer, if used: none
- Owner process: unavailable
- Running jobs: {jobs}
- Closed (UTC), if terminal: {'2000-01-01T12:00:00Z' if terminal else 'none'}
- Delete after (UTC): {'2000-01-31T12:00:00Z' if terminal else 'none'}
- Retention exception: none
- Contact: messages/{name}/
## Claims held
{claims}
## Baseline and dependencies
- Fixture only; no real shared source.
## Progress and checks
- Test pending.
## Blockers and handoff
{handoff}
'''


@unittest.skipUnless(os.name == 'posix', 'safe optional helper requires POSIX primitives')
class Transactions(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='agent_session-test-')
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name).resolve()
        self.board = self.base / 'board'
        (self.board / 'sessions').mkdir(parents=True)
        self.target = self.base / 'shared'
        self.scope = {'kind': 'file', 'value': str(self.target)}

    def save(self, name='worker', **kwargs):
        text = record(name, **kwargs)
        (self.board / 'sessions' / (name + '.md')).write_text(text)
        return text

    def review(self, **kwargs):
        return SESSION.review(self.board, scopes=[self.scope], **kwargs)

    def create(self, *, after=None, precondition=None, reviewed=None):
        return SESSION.commit(self.board, 'worker', record(claims=f'- file: {self.target}'),
                              reviewed or self.review(), create=True, after=after,
                              precondition=precondition)

    def test_complete_mutex_identity_and_bounded_contention(self):
        with SESSION.registry_mutex(self.board, 'worker'):
            text = (self.board / 'registry.lock/owner.md').read_text()
            for field in ('Session', 'Acquisition token', 'Host', 'UTC', 'Role', 'PID/start identity', 'Intent'):
                self.assertIn('- ' + field + ': ', text)
            with self.assertRaisesRegex(ValueError, 'busy'):
                with SESSION.registry_mutex(self.board, 'other', wait=.01):
                    self.fail('foreign lock acquired')
        self.assertFalse((self.board / 'registry.lock').exists())
        with self.assertRaises(ValueError):
            with SESSION.registry_mutex(self.board, 'worker', wait=31):
                self.fail('unbounded wait accepted')

    def test_same_session_cannot_reenter_or_reuse_a_previous_acquisition(self):
        source = self.base / 'candidate'
        source.write_text(record())
        with SESSION.registry_mutex(self.board, 'worker') as first:
            owner = (self.board / 'registry.lock/owner.md').read_bytes()
            with self.assertRaisesRegex(ValueError, 'busy'):
                with SESSION.registry_mutex(self.board, 'worker'):
                    self.fail('same-session reentry must not bypass exclusive acquisition')
            self.assertEqual((self.board / 'registry.lock/owner.md').read_bytes(), owner)
        with SESSION.registry_mutex(self.board, 'worker') as second:
            self.assertNotEqual(first.token, second.token)
            with self.assertRaisesRegex(ValueError, 'token'):
                SESSION.BOARD.publish_record(self.board, 'worker', str(source),
                                           create=True, lock_token=first.token)
            self.assertFalse((self.board / 'sessions/worker.md').exists())
            SESSION.BOARD.publish_record(self.board, 'worker', str(source),
                                       create=True, lock_token=second.token)
        self.assertFalse((self.board / 'registry.lock').exists())

    def process(self, code, *arguments):
        prefix = ('import sys\nfrom pathlib import Path\n'
                  f'sys.path.insert(0, {str(ROOT / "tests")!r})\n'
                  'from test_agent_session import SESSION, record\n')
        child = subprocess.Popen([sys.executable, '-B', '-c', prefix + code, *map(str, arguments)],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
            cwd=self.base)
        def cleanup():
            if child.poll() is None:
                child.kill()
            child.communicate(timeout=5)
        self.addCleanup(cleanup)
        return child

    def ready(self, children):
        # A bounded pipe barrier, not a timing sleep masquerading as concurrency.
        with selectors.DefaultSelector() as selector:
            for child in children:
                selector.register(child.stdout, selectors.EVENT_READ)
            deadline = time.monotonic() + 15
            while selector.get_map():
                events = selector.select(max(0, deadline - time.monotonic()))
                self.assertTrue(events, 'child did not reach fixture barrier')
                for key, _ in events:
                    self.assertEqual(key.fileobj.readline(), 'ready\n')
                    selector.unregister(key.fileobj)

    def test_independent_processes_have_one_claim_and_one_dependent_write(self):
        code = '''
board, target, output = map(Path, sys.argv[1:4])
name = sys.argv[4]
scope = {'kind': 'file', 'value': str(target)}
reviewed = SESSION.review(board, scopes=[scope])
print('ready', flush=True)
assert sys.stdin.readline() == 'go\\n'
try:
    SESSION.commit(board, name, record(name, claims=f'- file: {target}'), reviewed,
        create=True, wait=10, after=lambda receipt: output.write_text(name))
except SESSION.CoordinationError:
    raise SystemExit(2)
'''
        output = self.target
        children = [self.process(code, self.board, self.target, output, f'process-{i}')
                    for i in range(8)]
        self.ready(children)
        for child in children:
            child.stdin.write('go\n')
            child.stdin.flush()
        outcomes = [child.communicate(timeout=15) for child in children]
        codes = [child.returncode for child in children]
        self.assertEqual(codes.count(0), 1, (codes, outcomes))
        self.assertEqual(codes.count(2), 7, (codes, outcomes))
        winner = 'process-' + str(codes.index(0))
        self.assertEqual(output.read_text(), winner)
        self.assertEqual([p.stem for p in (self.board / 'sessions').iterdir()], [winner])
        self.assertFalse((self.board / 'registry.lock').exists())

    def test_killed_holder_leaves_lock_and_blocks_reentry_without_reclamation(self):
        child = self.process('''
with SESSION.registry_mutex(Path(sys.argv[1]), 'worker'):
    print('ready', flush=True)
    sys.stdin.readline()
''', self.board)
        self.ready([child])
        lock = self.board / 'registry.lock'
        owner = (lock / 'owner.md').read_bytes()
        child.kill()
        child.communicate(timeout=5)
        os.utime(lock, (1, 1))  # Neither age nor observed death permits stealing.
        for name in ('worker', 'other'):
            with self.assertRaisesRegex(ValueError, 'busy'):
                with SESSION.registry_mutex(self.board, name, wait=.01):
                    self.fail('abandoned lock was silently stolen')
        self.assertEqual((lock / 'owner.md').read_bytes(), owner)

    def test_cleanup_rejects_identically_replaced_owner_and_replaced_directory(self):
        for kind in ('owner', 'directory'):
            with self.subTest(kind=kind):
                real = SESSION.BOARD.publish_record
                def replace(*args, **kwargs):
                    result = real(*args, **kwargs)
                    lock = self.board / 'registry.lock'
                    if kind == 'owner':
                        sibling = lock / 'replacement'
                        sibling.write_bytes((lock / 'owner.md').read_bytes())
                        sibling.replace(lock / 'owner.md')
                    else:
                        lock.rename(self.board / 'original-lock')
                        lock.mkdir()
                        (lock / 'owner.md').write_text('foreign replacement')
                    return result
                actions = mock.Mock()
                with mock.patch.object(SESSION.BOARD, 'publish_record', side_effect=replace):
                    with self.assertRaisesRegex(ValueError, 'changed'):
                        self.create(after=actions)
                actions.assert_not_called()
                self.assertTrue((self.board / 'sessions/worker.md').exists())
                self.assertTrue((self.board / 'registry.lock/owner.md').exists())
                if kind == 'directory':
                    self.assertIn('- Session: worker',
                                  (self.board / 'original-lock/owner.md').read_text())
                    self.assertEqual((self.board / 'registry.lock/owner.md').read_text(),
                                     'foreign replacement')
                # Reset only the owned fixture between injected failures.
                shutil.rmtree(self.board)
                (self.board / 'sessions').mkdir(parents=True)

    def test_cleanup_unlink_or_rmdir_failure_suppresses_callback_and_preserves_lock(self):
        for operation in ('unlink', 'rmdir'):
            with self.subTest(operation=operation):
                original = getattr(SESSION.os, operation)
                def fail(name, *args, **kwargs):
                    if name == ('owner.md' if operation == 'unlink' else 'registry.lock'):
                        raise OSError('injected unlock failure')
                    return original(name, *args, **kwargs)
                actions = mock.Mock()
                # Patching an os function changes capability-set membership.
                with mock.patch.object(SESSION.BOARD, 'require_capabilities'), \
                        mock.patch.object(SESSION.os, operation, side_effect=fail):
                    with self.assertRaisesRegex(SESSION.CoordinationError, 'unlock failure'):
                        self.create(after=actions)
                actions.assert_not_called()
                self.assertTrue((self.board / 'sessions/worker.md').exists())
                self.assertTrue((self.board / 'registry.lock').is_dir())
                with self.assertRaisesRegex(ValueError, 'busy'):
                    with SESSION.registry_mutex(self.board, 'other'):
                        self.fail('partly cleaned mutex treated as available')
                shutil.rmtree(self.board)
                (self.board / 'sessions').mkdir(parents=True)

    def test_precondition_failure_stops_ack_output_and_job(self):
        for precondition in (lambda: False, lambda: 1,
                             mock.Mock(side_effect=AssertionError('unverified stopped writers'))):
            actions = mock.Mock()
            with self.assertRaises((ValueError, AssertionError)):
                self.create(precondition=precondition, after=actions)
            actions.assert_not_called()
            self.assertFalse((self.board / 'sessions/worker.md').exists())
            self.assertFalse((self.board / 'registry.lock').exists())

    def test_cleanup_uses_fresh_listing_when_old_directory_handle_is_stale(self):
        real = os.listdir
        held = []
        def listing(path):
            # Workspace mounts may expose the listing captured when the lock
            # descriptor was opened, before owner.md/staged files were created.
            return [] if held and path == held[0] else real(path)
        with mock.patch.object(SESSION.os, 'listdir', side_effect=listing):
            with SESSION.registry_mutex(self.board, 'worker') as lock:
                held.append(lock.fd)
                self.assertEqual(SESSION.os.listdir(lock.fd), [])
                self.assertTrue((self.board / 'registry.lock/owner.md').exists())
        self.assertFalse((self.board / 'registry.lock').exists())

    def test_success_receipt_and_callback_only_after_cleanup(self):
        events = []
        def action(receipt):
            self.assertFalse((self.board / 'registry.lock').exists())
            self.assertEqual(receipt['record_sha256'], hashlib.sha256(
                (self.board / 'sessions/worker.md').read_bytes()).hexdigest())
            self.target.write_text('one verified edit')
            events.append(receipt)
        result = self.create(precondition=lambda: True, after=action)
        self.assertEqual(events, [result])
        self.assertEqual(self.target.read_text(), 'one verified edit')
        self.assertEqual(result['claims'], [self.scope])

    def test_publisher_failure_suppresses_callback(self):
        actions = mock.Mock()
        with mock.patch.object(SESSION.BOARD, 'publish_record', side_effect=OSError('failed publish')):
            with self.assertRaisesRegex(SESSION.CoordinationError, 'failed publish'):
                self.create(after=actions)
        actions.assert_not_called()
        self.assertFalse((self.board / 'sessions/worker.md').exists())
        self.assertFalse((self.board / 'registry.lock').exists())

    def test_uncertain_cleanup_keeps_committed_record_but_stops_callback(self):
        real = SESSION.BOARD.publish_record
        def publish(*args, **kwargs):
            result = real(*args, **kwargs)
            (self.board / 'registry.lock/foreign').write_text('preserve')
            return result
        actions = mock.Mock()
        with mock.patch.object(SESSION.BOARD, 'publish_record', side_effect=publish):
            with self.assertRaisesRegex(ValueError, 'unexpected mutex contents'):
                self.create(after=actions)
        actions.assert_not_called()
        self.assertTrue((self.board / 'sessions/worker.md').exists())
        self.assertEqual((self.board / 'registry.lock/foreign').read_text(), 'preserve')
        self.assertIn('- Session: worker', (self.board / 'registry.lock/owner.md').read_text())

    def test_lock_metadata_failure_does_not_claim_success_or_delete_unknown_bytes(self):
        with mock.patch.object(SESSION.os, 'fsync', side_effect=OSError('sync failed')):
            with self.assertRaises(SESSION.CoordinationError):
                self.create()
        self.assertFalse((self.board / 'sessions/worker.md').exists())
        # Complete owned metadata may be cleaned; no claim has been published.
        self.assertFalse((self.board / 'registry.lock').exists())

    def test_stale_own_record_and_saved_byte_mismatch_fail_closed(self):
        before = self.save()
        reviewed = self.review()
        self.save(jobs='new job')
        with self.assertRaisesRegex(ValueError, 'stale baseline'):
            SESSION.commit(self.board, 'worker', before, reviewed,
                           expected_sha256=reviewed['record_hashes']['worker'])
        real = SESSION.BOARD.publish_record
        def mutate(*args, **kwargs):
            result = real(*args, **kwargs)
            (self.board / 'sessions/worker.md').write_text(record(jobs='unexpected replacement'))
            return result
        reviewed = self.review()
        actions = mock.Mock()
        with mock.patch.object(SESSION.BOARD, 'publish_record', side_effect=mutate):
            with self.assertRaisesRegex(ValueError, 'saved record differs'):
                SESSION.commit(self.board, 'worker', before, reviewed,
                               expected_sha256=reviewed['record_hashes']['worker'], after=actions)
        actions.assert_not_called()

    def test_terminal_record_cannot_replay_even_after_uncertain_output(self):
        self.save(state='done')
        reviewed = self.review()
        with self.assertRaisesRegex(ValueError, 'terminal session'):
            SESSION.commit(self.board, 'worker', record(state='done'), reviewed,
                           expected_sha256=reviewed['record_hashes']['worker'])

    def test_terminal_callback_rejected_before_releasing_scope(self):
        before = self.save(claims=f'- file: {self.target}')
        reviewed = self.review()
        actions = mock.Mock()
        with self.assertRaisesRegex(ValueError, 'terminal commit cannot run'):
            SESSION.commit(self.board, 'worker', record(state='done'), reviewed,
                           expected_sha256=reviewed['record_hashes']['worker'], after=actions)
        actions.assert_not_called()
        self.assertEqual((self.board / 'sessions/worker.md').read_text(), before)
        self.assertFalse((self.board / 'registry.lock').exists())

    def test_directory_terminal_and_resource_conflicts_not_prefix_siblings(self):
        self.save('other', claims=f'- directory: {self.base}', state='done')
        with self.assertRaisesRegex(ValueError, 'overlaps owner other'):
            self.create()
        self.save('other', claims=f'- directory: {self.base}-other')
        self.create()
        self.save('worker', claims='- resource: device:host:shared-unit')
        self.save('other', claims='- resource: device:host:shared-unit')
        reviewed = SESSION.review(self.board)
        with self.assertRaisesRegex(ValueError, 'overlaps owner other'):
            SESSION.commit(self.board, 'worker', record(claims='- resource: device:host:shared-unit'),
                           reviewed, expected_sha256=reviewed['record_hashes']['worker'])

    def test_unknown_record_requires_exact_explicit_legacy_interpretation(self):
        path = self.board / 'sessions/old.md'
        path.write_text('# old\n## Claims held\nNone, released after review.\n')
        with self.assertRaisesRegex(ValueError, 'incomplete registry'):
            self.review()
        assessment = {'old': {'sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
                              'claims': [], 'reason': 'Entire legacy record manually reviewed; no claims.'}}
        reviewed = self.review(legacy_reviews=assessment)
        self.assertEqual(reviewed['ownership'][0], {'id': 'old', 'claims': []})
        path.write_text(path.read_text() + 'changed\n')
        with self.assertRaisesRegex(ValueError, 'legacy record differs'):
            self.create(reviewed=reviewed)
        path.unlink()
        with self.assertRaisesRegex(ValueError, 'absent'):
            self.review(legacy_reviews=assessment)

    def test_crlf_record_and_legacy_review_hash_exact_publication_bytes(self):
        before = self.save()
        path = self.board / 'sessions/worker.md'
        path.write_bytes(before.replace('\n', '\r\n').encode())
        reviewed = self.review()
        self.assertEqual(reviewed['record_hashes']['worker'], hashlib.sha256(path.read_bytes()).hexdigest())
        SESSION.commit(self.board, 'worker', before, reviewed,
                       expected_sha256=reviewed['record_hashes']['worker'])
        legacy = self.board / 'sessions/old.md'
        legacy.write_bytes(b'# old\r\n## Claims held\r\nNone, manually released.\r\n')
        assessment = {'old': {'sha256': hashlib.sha256(legacy.read_bytes()).hexdigest(),
            'claims': [], 'reason': 'Manually reviewed the complete legacy record with CRLF bytes.'}}
        reviewed = SESSION.review(self.board, legacy_reviews=assessment)
        self.assertEqual(reviewed['record_hashes']['old'], assessment['old']['sha256'])
        SESSION.commit(self.board, 'worker', before, reviewed,
                       expected_sha256=reviewed['record_hashes']['worker'])

    def test_new_claim_requires_exact_scope_review(self):
        with self.assertRaisesRegex(ValueError, 'requires exact scope review'):
            self.create(reviewed=SESSION.review(self.board))

    def test_handoff_change_rejects_unchanged_byte_intervening_owner(self):
        self.save('quiet', handoff='- Prior release.')
        reviewed = self.review()
        self.save('quiet', handoff=f'- Acquired and released {self.target}; writers stopped; new reference.')
        with self.assertRaisesRegex(ValueError, 'handoff or input changed'):
            self.create(reviewed=reviewed)

    def test_scoped_discovery_requires_review_of_quiet_owner_not_only_relay(self):
        for name in ('relay', 'quiet'):
            self.save(name, handoff=f'- Scope: file: {self.target}\n- Release reference: {name}-1; writers stopped.')
        reviewed = self.review(handoffs=['relay'])
        self.assertEqual(set(reviewed['relevant_handoffs']), {'relay', 'quiet'})
        with self.assertRaisesRegex(ValueError, 'every returned candidate'):
            SESSION.commit(self.board, 'worker', record(claims=f'- file: {self.target}'),
                reviewed, create=True, handoffs_reviewed=['relay'])
        SESSION.commit(self.board, 'worker', record(claims=f'- file: {self.target}'),
            reviewed, create=True, handoffs_reviewed=['relay', 'quiet'])

    def test_unrelated_progress_change_does_not_invalidate_ownership_review(self):
        self.save('other')
        reviewed = self.review()
        text = (self.board / 'sessions/other.md').read_text().replace('Test pending.', 'Test passed.')
        text = text.replace('Updated (UTC): 2000-01-01T12:00:00Z',
                            'Updated (UTC): 2000-01-01T12:01:00Z')
        (self.board / 'sessions/other.md').write_text(text)
        self.create(reviewed=reviewed)

    def test_changed_missing_and_aliased_input_baselines(self):
        source = self.base / 'source'
        source.write_text('original')
        missing = self.base / 'future' / 'generated'
        reviewed = self.review(inputs=[source, missing])
        source.write_text('changed')
        with self.assertRaisesRegex(ValueError, 'input changed'):
            self.create(reviewed=reviewed)
        reviewed = self.review(inputs=[source, missing])
        missing.parent.mkdir()
        missing.write_text('created')
        with self.assertRaisesRegex(ValueError, 'input changed'):
            self.create(reviewed=reviewed)
        alias = self.base / 'alias'
        alias.symlink_to(source)
        reviewed = self.review(inputs=[alias])
        alias.unlink()
        alias.symlink_to(missing)
        with self.assertRaisesRegex(ValueError, 'input changed'):
            self.create(reviewed=reviewed)

    def test_board_replacement_invalidates_same_empty_ownership_snapshot(self):
        reviewed = self.review()
        self.board.rename(self.base / 'old-board')
        (self.board / 'sessions').mkdir(parents=True)
        with self.assertRaisesRegex(ValueError, 'changed'):
            self.create(reviewed=reviewed)
        self.assertFalse((self.board / 'sessions/worker.md').exists())

    def test_alias_retargeted_during_input_read_is_rejected(self):
        source, other, alias = (self.base / name for name in ('source', 'other', 'alias'))
        source.write_text('same bytes')
        other.write_text('same bytes')
        alias.symlink_to(source)
        real = SESSION.BOARD.read_regular
        def retarget(parent, name):
            result = real(parent, name)
            alias.unlink()
            alias.symlink_to(other)
            return result
        with mock.patch.object(SESSION.BOARD, 'read_regular', side_effect=retarget):
            with self.assertRaisesRegex(ValueError, 'alias changed'):
                SESSION.input_state(alias)

    def test_checkpoint_preserves_events_and_replaces_current_status_together(self):
        before = record(jobs='job-17 running', handoff='- Awaiting obsolete owner.')
        candidate = SESSION.checkpoint(before, state='waiting', running_jobs='none',
            progress='- Job-17 completed; 8/8 tests passed; 3 internal skips.',
            handoff='- Current owner identified; acquisition pending.',
            next_check='2100-01-01T00:00:00Z / request actual owner',
            updated_at='2000-01-01T12:03:00Z', progress_at='2000-01-01T12:02:00Z')
        fields = SESSION.CHECK.parse_record(candidate)[1]
        self.assertEqual(fields['Last inbox check (UTC)'], '2000-01-01T12:00:00Z')
        self.assertEqual(fields['Last meaningful progress (UTC)'], '2000-01-01T12:02:00Z')
        self.assertEqual(fields['Running jobs'], 'none')
        self.assertNotIn('obsolete owner', candidate)
        self.assertNotIn('Test pending', candidate)
        with self.assertRaises(TypeError):
            SESSION.checkpoint(before, state='active', running_jobs='none')
        with self.assertRaises(ValueError):
            SESSION.checkpoint(before, state='done', running_jobs='none', progress='- Done.',
                handoff='- Done.', next_check='none / done')

    def test_failed_acquisition_does_not_prevent_independent_completion_checkpoint(self):
        before = self.save(jobs='completed but not reconciled')
        reviewed = self.review()
        self.save('other', claims=f'- file: {self.target}')
        with self.assertRaises(ValueError):
            SESSION.commit(self.board, 'worker', record(claims=f'- file: {self.target}'),
                           reviewed, expected_sha256=reviewed['record_hashes']['worker'])
        current = SESSION.review(self.board)
        candidate = SESSION.checkpoint(before, state='waiting', running_jobs='none',
            progress='- Completed test: 8/8 passed.', handoff='- Waiting for other; no ownership.',
            next_check='2100-01-01T00:00:00Z / read inbox')
        SESSION.commit(self.board, 'worker', candidate, current,
                       expected_sha256=current['record_hashes']['worker'])
        self.assertEqual(SESSION.CHECK.parse_record(
            (self.board / 'sessions/worker.md').read_text())[1]['Running jobs'], 'none')

    def test_32_simultaneous_contenders_have_one_acquisition_and_one_callback(self):
        count = 32
        barrier = threading.Barrier(count)
        results, failures, unexpected = [], [], []
        def worker(index):
            name = f'worker-{index}'
            try:
                reviewed = self.review()
                barrier.wait(timeout=15)
                SESSION.commit(self.board, name, record(name, claims=f'- file: {self.target}'),
                    reviewed, create=True, wait=30,
                    after=lambda receipt: results.append(receipt))
            except SESSION.CoordinationError as exc:
                failures.append(str(exc))
            except Exception as exc:
                unexpected.append(repr(exc))
        workers = [threading.Thread(target=worker, args=(i,), daemon=True) for i in range(count)]
        for thread in workers:
            thread.start()
        for thread in workers:
            thread.join(35)
        self.assertTrue(all(not thread.is_alive() for thread in workers))
        self.assertEqual(unexpected, [])
        self.assertEqual(len(results), 1)
        self.assertEqual(len(failures), count - 1)
        self.assertEqual(len(list((self.board / 'sessions').iterdir())), 1)
        self.assertFalse((self.board / 'registry.lock').exists())

    def test_eight_disjoint_workers_make_useful_progress_then_close(self):
        count = 8
        barrier = threading.Barrier(count)
        local = threading.local()
        real_mutex = SESSION.registry_mutex
        completed, failures, attempts = [], [], []
        @contextmanager
        def tracked_mutex(*args, **kwargs):
            with real_mutex(*args, **kwargs) as lock:
                local.held = True
                yield lock
            local.held = False
        def worker(index):
            name = f'disjoint-{index}'
            target = self.base / name
            scope = {'kind': 'file', 'value': str(target)}
            deadline = time.monotonic() + 15
            def checked_retry(closing):
                tries = 0
                while time.monotonic() < deadline:
                    tries += 1
                    try:
                        reviewed = SESSION.review(self.board, scopes=[] if closing else [scope])
                        candidate = record(name, state='done') if closing else record(name, claims=f'- file: {target}')
                        def useful_work(receipt):
                            self.assertFalse(getattr(local, 'held', False))
                            target.write_text(name + ': useful result\n')
                            completed.append(name)
                        SESSION.commit(self.board, name, candidate, reviewed, create=not closing,
                            expected_sha256=reviewed['record_hashes'].get(name) if closing else None,
                            wait=2, after=None if closing else useful_work)
                        attempts.append(tries)
                        return
                    except SESSION.CoordinationError as exc:
                        if not any(word in str(exc) for word in
                                   ('changed', 'incomplete registry', 'busy')):
                            raise
                        time.sleep(.001)
                raise AssertionError('bounded fixture did not finish; not a fairness guarantee')
            try:
                barrier.wait(timeout=10)
                checked_retry(False)
                checked_retry(True)
            except Exception as exc:
                failures.append(repr(exc))
        with mock.patch.object(SESSION, 'registry_mutex', side_effect=tracked_mutex):
            workers = [threading.Thread(target=worker, args=(i,), daemon=True) for i in range(count)]
            for thread in workers:
                thread.start()
            for thread in workers:
                thread.join(20)
        self.assertTrue(all(not thread.is_alive() for thread in workers))
        self.assertEqual(failures, [])
        self.assertEqual(sorted(completed), [f'disjoint-{i}' for i in range(count)])
        self.assertEqual(len(attempts), count * 2)
        for index in range(count):
            name = f'disjoint-{index}'
            self.assertEqual((self.base / name).read_text(), name + ': useful result\n')
            _, fields, claims = SESSION.CHECK.parse_record((self.board / 'sessions' / (name + '.md')).read_text())
            self.assertEqual(fields['State'], 'done')
            self.assertEqual(claims, 'None.')

    def test_structured_clean_rejections_and_bounded_retry_advice(self):
        with SESSION.registry_mutex(self.board, 'holder'):
            with self.assertRaises(SESSION.CoordinationError) as caught:
                self.create()
        error = caught.exception
        self.assertEqual(error.code, 'registry_busy')
        self.assertFalse(error.uncertain)
        self.assertEqual(error.retry_action, 'bounded_backoff')
        self.assertTrue(.025 <= SESSION.retry_delay(error, 1) <= .05)
        for attempt, bounds in ((1, (.025, .05)), (7, (1.6, 3.2)), (12, (2.0, 4.0))):
            with mock.patch.object(SESSION.random, 'uniform', return_value=bounds[1]) as jitter:
                self.assertEqual(SESSION.retry_delay(error, attempt, max_attempts=32), bounds[1])
                jitter.assert_called_once_with(*bounds)
        self.assertIsNone(SESSION.retry_delay(error, 8))
        with self.assertRaises(ValueError):
            SESSION.retry_delay(error, 0)
        reviewed = self.review()
        self.save('other', claims=f'- file: {self.target}')
        with self.assertRaises(SESSION.CoordinationError) as caught:
            self.create(reviewed=reviewed)
        self.assertEqual(caught.exception.code, 'stale_review')
        self.assertEqual(caught.exception.retry_action, 'rereview_and_replan')
        with self.assertRaises(SESSION.CoordinationError) as caught:
            self.create()
        self.assertEqual(caught.exception.code, 'claim_conflict')
        with self.assertRaises(ValueError):
            SESSION.retry_delay(caught.exception, 1)

    def test_cleanup_overrides_clean_rejection_with_uncertainty(self):
        original = SESSION.os.rmdir
        def fail(name, *args, **kwargs):
            if name == 'registry.lock':
                raise OSError('cleanup after rejection failed')
            return original(name, *args, **kwargs)
        self.save('other', claims=f'- file: {self.target}')
        with mock.patch.object(SESSION.os, 'rmdir', side_effect=fail):
            with self.assertRaises(SESSION.CoordinationError) as caught:
                self.create()
        self.assertEqual(caught.exception.code, 'cleanup_uncertain')
        self.assertTrue(caught.exception.uncertain)
        with self.assertRaises(ValueError):
            SESSION.retry_delay(caught.exception, 1)
        self.assertFalse((self.board / 'sessions/worker.md').exists())

    def test_acknowledgment_renders_complete_correlated_fields(self):
        receipt = self.create()
        message = SESSION.acknowledgment(receipt, scope=self.scope, previous_owner='old-owner',
            release_reference='release-42', request_id='request-17',
            review_note='Reviewed complete release chain and saved source hash.')
        for expected in ('- New owner: worker\n', '- Previous owner / recipient: old-owner\n',
                         f'- Scope: file: {self.target}\n', '- Release reference: release-42\n',
                         '- Request ID: request-17\n', receipt['record_sha256'], receipt['updated']):
            self.assertIn(expected, message)
        self.assertFalse((self.board / 'messages').exists())
        self.assertEqual(self.review()['record_hashes']['worker'], receipt['record_sha256'])

    def test_acknowledgment_rejects_incomplete_or_mismatched_inputs(self):
        receipt = self.create()
        valid = dict(receipt=receipt, scope=self.scope, previous_owner='old-owner',
                     release_reference='release-42', request_id='none: no prior request',
                     review_note='Recorded release and current source inspected.')
        for change in ({'receipt': {}}, {'receipt': {**receipt, 'record_sha256': 'bad'}},
                       {'receipt': {**receipt, 'updated': 'yesterday'}},
                       {'scope': {'kind': 'file', 'value': str(self.base / 'unowned')}},
                       {'scope': {'kind': 'file', 'value': str(self.base / 'x/../shared')}},
                       {'scope': {'kind': 'file', 'value': str(self.target), 'extra': 'ignored'}},
                       {'previous_owner': ''}, {'release_reference': ''},
                       {'release_reference': 'r\n- forged: value'},
                       {'request_id': 'none'}, {'review_note': ''}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                SESSION.acknowledgment(**{**valid, **change})
        for field in ('scope', 'previous_owner', 'release_reference', 'request_id', 'review_note'):
            missing = dict(valid); missing.pop(field)
            with self.subTest(missing=field), self.assertRaises(TypeError):
                SESSION.acknowledgment(**missing)

    def test_acknowledgment_cli_formats_without_publishing(self):
        receipt = self.create()
        request = dict(receipt=receipt, scope=self.scope, previous_owner='old-owner',
                       release_reference='release-42', request_id='none: no prior request',
                       review_note='Inspected predecessor release and unchanged source.')
        command = [sys.executable, '-B', str(ROOT / 'tools/agent_session.py'),
                   'acknowledgment', '--json-errors']
        result = subprocess.run(command, input=json.dumps(request), text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('- Release reference: release-42\n', json.loads(result.stdout)['message'])
        request.pop('release_reference')
        result = subprocess.run(command, input=json.dumps(request), text=True, capture_output=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(json.loads(result.stderr)['error']['uncertain'])
        self.assertFalse((self.board / 'messages').exists())

    def test_invalid_closure_is_clean_before_candidate_staging(self):
        previous = self.save()
        reviewed = self.review()
        for changes in ({'Closed (UTC), if terminal': 'none'},
                        {'Running jobs': 'still running'},
                        {'Delete after (UTC)': '1999-12-31T12:00:00Z'}):
            candidate = SESSION.set_fields(record(state='done'), changes)
            with self.subTest(changes=changes), \
                    mock.patch.object(SESSION.BOARD, 'publish_record') as publish:
                with self.assertRaises(SESSION.CoordinationError) as caught:
                    SESSION.commit(self.board, 'worker', candidate, reviewed,
                                   expected_sha256=reviewed['record_hashes']['worker'])
                self.assertEqual(caught.exception.code, 'invalid_request')
                self.assertFalse(caught.exception.uncertain)
                publish.assert_not_called()
                self.assertEqual((self.board / 'sessions/worker.md').read_text(), previous)
                self.assertFalse((self.board / 'registry.lock').exists())

    def test_backwards_transition_and_terminal_replay_are_clean(self):
        self.save()
        reviewed = self.review()
        candidate = SESSION.set_fields(record(), {'Last inbox check (UTC)': '1999-12-31T12:00:00Z'})
        callback = mock.Mock()
        with mock.patch.object(SESSION.BOARD, 'publish_record') as publish:
            with self.assertRaises(SESSION.CoordinationError) as caught:
                SESSION.commit(self.board, 'worker', candidate, reviewed,
                               expected_sha256=reviewed['record_hashes']['worker'], after=callback)
            self.assertFalse(caught.exception.uncertain)
            publish.assert_not_called()
            callback.assert_not_called()
        self.save(state='done')
        reviewed = self.review()
        with mock.patch.object(SESSION.BOARD, 'publish_record') as publish:
            with self.assertRaises(SESSION.CoordinationError) as caught:
                SESSION.commit(self.board, 'worker', record(state='done'), reviewed,
                               expected_sha256=reviewed['record_hashes']['worker'])
            self.assertFalse(caught.exception.uncertain)
            publish.assert_not_called()
        self.assertFalse((self.board / 'registry.lock').exists())

    def test_failed_dependent_check_stops_success_release_until_reconciled(self):
        success_release = mock.Mock()
        def work(receipt):
            subprocess.run([sys.executable, '-c', 'raise SystemExit(7)'], check=True,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            success_release(receipt)
        with self.assertRaises(SESSION.CoordinationError) as caught:
            self.create(after=work)
        self.assertEqual(caught.exception.code, 'callback_uncertain')
        success_release.assert_not_called()
        # Reconcile the saved ownership and joined subprocess before an honest
        # failure release; completion of the acquisition was not a test pass.
        reviewed = self.review()
        self.assertEqual(reviewed['ownership'][0]['claims'], [self.scope])
        self.assertFalse((self.board / 'registry.lock').exists())
        candidate = record(state='done', handoff=(
            f'- Scope inventory: complete\n- Scope: file: {self.target}\n'
            '- Release: failed check exit7; writer joined; source not edited.'))
        result = SESSION.commit(self.board, 'worker', candidate, reviewed,
                                expected_sha256=reviewed['record_hashes']['worker'])
        self.assertEqual(result['claims'], [])
        self.assertIn('failed check exit7', (self.board / 'sessions/worker.md').read_text())

    def test_publication_and_callback_failures_never_offer_retry(self):
        real = SESSION.BOARD.publish_record
        def published_then_failed(*args, **kwargs):
            real(*args, **kwargs)
            raise OSError('transport lost after publication')
        callback = mock.Mock()
        with mock.patch.object(SESSION.BOARD, 'publish_record', side_effect=published_then_failed):
            with self.assertRaises(SESSION.CoordinationError) as caught:
                self.create(after=callback)
        self.assertEqual(caught.exception.code, 'publication_uncertain')
        self.assertTrue(caught.exception.uncertain)
        callback.assert_not_called()
        self.assertTrue((self.board / 'sessions/worker.md').exists())
        with self.assertRaises(ValueError):
            SESSION.retry_delay(caught.exception, 1)
        reviewed = self.review()
        candidate = (self.board / 'sessions/worker.md').read_text()
        def partial_callback(receipt):
            self.target.write_text('effect happened')
            raise RuntimeError('callback stopped after effect')
        with self.assertRaises(SESSION.CoordinationError) as caught:
            SESSION.commit(self.board, 'worker', candidate, reviewed,
                           expected_sha256=reviewed['record_hashes']['worker'], after=partial_callback)
        self.assertEqual(caught.exception.code, 'callback_uncertain')
        self.assertTrue(caught.exception.uncertain)
        self.assertEqual(self.target.read_text(), 'effect happened')
        self.assertFalse((self.board / 'registry.lock').exists())

    def test_scoped_review_allows_complete_disjoint_claims_and_handoffs(self):
        other = self.base / 'other'
        reviewed = self.review()
        self.save('other', claims=f'- file: {other}', handoff=(
            f'- Scope inventory: complete\n- Scope: file: {other}\n- Release: unrelated chain.'))
        self.create(reviewed=reviewed)
        self.assertTrue((self.board / 'sessions/worker.md').exists())

    def test_older_review_tokens_keep_conservative_fallback(self):
        reviewed = self.review()
        del reviewed['scope_fingerprint']
        other = self.base / 'other'
        self.save('other', claims=f'- file: {other}')
        with self.assertRaises(SESSION.CoordinationError) as caught:
            self.create(reviewed=reviewed)
        self.assertEqual(caught.exception.code, 'stale_review')

    def test_scoped_review_tracks_unchanged_input_ownership(self):
        dependency = self.base / 'dependency'
        dependency.write_text('unchanged bytes')
        reviewed = self.review(inputs=[dependency])
        self.save('reader-input-owner', claims=f'- file: {dependency}')
        with self.assertRaises(SESSION.CoordinationError) as caught:
            self.create(reviewed=reviewed)
        self.assertEqual(caught.exception.code, 'stale_review')

    def test_scoped_review_allows_changed_complete_unrelated_handoff(self):
        other = self.base / 'other'
        prefix = f'- Scope inventory: complete\n- Scope: file: {other}\n'
        self.save('other', handoff=prefix + '- Release: first.')
        reviewed = self.review()
        self.save('other', handoff=prefix + '- Release: second; unrelated ownership changed.')
        self.create(reviewed=reviewed)

    def test_scoped_review_keeps_opaque_and_new_quiet_owner_history(self):
        for handoff in ('- Scope: none\n- Opaque prior disposition.',
                        f'- Scope inventory: complete\n- Scope: file: {self.target}\n- Release: quiet owner; bytes unchanged.'):
            with self.subTest(handoff=handoff):
                reviewed = self.review()
                self.save('quiet', state='done', handoff=handoff)
                with self.assertRaises(SESSION.CoordinationError) as caught:
                    self.create(reviewed=reviewed)
                self.assertEqual(caught.exception.code, 'stale_review')
                (self.board / 'sessions/quiet.md').unlink()

    def test_scoped_review_still_fails_on_unknown_registry_entries(self):
        reviewed = self.review()
        (self.board / 'sessions/unknown.tmp').write_text('not an ignorable owner')
        with self.assertRaises(SESSION.CoordinationError) as caught:
            self.create(reviewed=reviewed)
        self.assertEqual(caught.exception.code, 'registry_invalid')
        self.assertFalse(caught.exception.uncertain)
        self.assertFalse((self.board / 'sessions/worker.md').exists())

    def test_release_review_cannot_omit_held_scope_dependencies(self):
        before = self.save(claims=f'- file: {self.target}')
        unrelated = {'kind': 'file', 'value': str(self.base / 'other')}
        reviewed = SESSION.review(self.board, scopes=[unrelated])
        self.save('quiet', state='done', handoff=(
            f'- Scope inventory: complete\n- Scope: file: {self.target}\n- Release: new relevant history.'))
        candidate = SESSION.replace_section(before, 'Claims held', 'None.')
        with self.assertRaises(SESSION.CoordinationError) as caught:
            SESSION.commit(self.board, 'worker', candidate, reviewed,
                           expected_sha256=reviewed['record_hashes']['worker'])
        self.assertEqual(caught.exception.code, 'stale_review')
        self.assertEqual(SESSION.CHECK.parse_record(
            (self.board / 'sessions/worker.md').read_text())[2], f'- file: {self.target}')

    def test_new_proposal_kind_is_rechecked_inside_mutex(self):
        reviewed = self.review()  # Deliberately no input hash: the claim itself must be valid.
        real = SESSION.registry_mutex
        @contextmanager
        def materialize(*args, **kwargs):
            with real(*args, **kwargs) as lock:
                self.target.mkdir()
                yield lock
        callback = mock.Mock()
        with mock.patch.object(SESSION, 'registry_mutex', side_effect=materialize):
            with self.assertRaises(SESSION.CoordinationError):
                self.create(reviewed=reviewed, after=callback)
        callback.assert_not_called()
        self.assertFalse((self.board / 'sessions/worker.md').exists())
        self.assertFalse((self.board / 'registry.lock').exists())
        self.assertTrue(self.target.is_dir())

    def test_only_pure_typed_scan_changes_offer_review_retry(self):
        changed = {'path': str(self.board / 'sessions'), 'error': 'changed',
                   'code': 'snapshot_changed'}
        malformed = {'path': str(self.board / 'sessions/unknown.md'), 'error': 'malformed'}
        untyped = {'path': str(self.board / 'sessions'),
                   'error': 'directory entries changed during scan; retry after publication settles'}
        for errors, code in (([changed], 'stale_review'),
                             ([changed, malformed], 'registry_invalid'),
                             ([untyped], 'registry_invalid')):
            with self.subTest(errors=errors), mock.patch.object(SESSION.CHECK, 'scan_sessions',
                    return_value={'complete': False, 'records': [], 'errors': errors}):
                with self.assertRaises(SESSION.CoordinationError) as caught:
                    self.review()
            self.assertEqual(caught.exception.code, code)
            self.assertFalse(caught.exception.uncertain)

    def test_supplemental_reread_race_is_typed_without_message_matching(self):
        self.save()
        real = SESSION.BOARD.read_regular
        def changed(parent, name):
            if name == 'worker.md':
                (self.board / 'sessions/worker.md').write_text(record(jobs='changed'))
                raise SESSION.BOARD.PublicationError('injected read validation failure')
            return real(parent, name)
        with mock.patch.object(SESSION.BOARD, 'read_regular', side_effect=changed):
            with self.assertRaises(SESSION.CoordinationError) as caught:
                self.review()
        self.assertEqual(caught.exception.code, 'stale_review')
        with mock.patch.object(SESSION.BOARD, 'read_regular', side_effect=
                SESSION.BOARD.PublicationError('source changed while reading')):
            with self.assertRaises(SESSION.CoordinationError) as caught:
                self.review()
        self.assertEqual(caught.exception.code, 'registry_invalid')

    def test_observed_input_read_change_is_typed_stale_review(self):
        self.target.write_text('before')
        real = SESSION.BOARD.read_regular
        def changed(parent, name):
            if name == self.target.name:
                self.target.write_text('after with different bytes')
                raise SESSION.BOARD.PublicationError('injected input validation failure')
            return real(parent, name)
        with mock.patch.object(SESSION.BOARD, 'read_regular', side_effect=changed):
            with self.assertRaises(SESSION.CoordinationError) as caught:
                self.review(inputs=[self.target])
        self.assertEqual(caught.exception.code, 'stale_review')
        self.assertFalse(caught.exception.uncertain)
        with mock.patch.object(SESSION.BOARD, 'read_regular', side_effect=PermissionError('denied')):
            with self.assertRaises(SESSION.CoordinationError) as caught:
                self.review(inputs=[self.target])
        self.assertEqual(caught.exception.code, 'registry_invalid')

    def test_direct_mutex_descriptor_close_failure_is_uncertain(self):
        real = SESSION.BOARD.open_directory
        calls = []
        @contextmanager
        def closing(path):
            calls.append(path)
            first = len(calls) == 1
            with real(path) as fd:
                yield fd
            if first:
                raise OSError('descriptor close failed after cleanup')
        with mock.patch.object(SESSION.BOARD, 'open_directory', side_effect=closing):
            with self.assertRaises(SESSION.CoordinationError) as caught:
                with SESSION.registry_mutex(self.board, 'worker'):
                    pass
        self.assertEqual(caught.exception.code, 'cleanup_uncertain')
        self.assertTrue(caught.exception.uncertain)
        self.assertFalse((self.board / 'registry.lock').exists())
        body_error = RuntimeError('caller body failed')
        with self.assertRaises(RuntimeError) as caught:
            with SESSION.registry_mutex(self.board, 'worker'):
                raise body_error
        self.assertIs(caught.exception, body_error)
        self.assertFalse((self.board / 'registry.lock').exists())

    def test_cli_json_error_reports_clean_contention_without_stdout(self):
        request = {'board': str(self.board), 'session': 'worker',
                   'candidate': record(claims=f'- file: {self.target}'),
                   'reviewed': self.review(), 'create': True}
        with SESSION.registry_mutex(self.board, 'holder'):
            result = subprocess.run([sys.executable, '-B', str(ROOT / 'tools/agent_session.py'),
                                     'commit', '--json-errors'], input=json.dumps(request),
                                    text=True, capture_output=True, timeout=15)
        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stdout, '')
        error = json.loads(result.stderr)['error']
        self.assertEqual(error['code'], 'registry_busy')
        self.assertFalse(error['uncertain'])
        self.assertFalse((self.board / 'sessions/worker.md').exists())

    def test_json_error_output_is_structured_and_output_failure_uncertain(self):
        request = {'board': str(self.board), 'session': 'worker',
                   'candidate': record(claims=f'- file: {self.target}'),
                   'reviewed': self.review(), 'create': True}
        source_bytes = SESSION.BOARD.source_bytes
        def request_bytes(source, *args):
            return json.dumps(request).encode() if source == '-' else source_bytes(source, *args)
        with mock.patch.object(SESSION.BOARD, 'source_bytes', side_effect=request_bytes):
            with mock.patch.object(SESSION, 'print', create=True) as printer:
                # First print is the successful result; output may be partially
                # delivered before transport failure. Error goes to stderr.
                printer.side_effect = [BrokenPipeError('output gone'), None]
                result = SESSION.main(['commit', '--json-errors'])
        self.assertEqual(result, 1)
        error = json.loads(printer.call_args.args[0])['error']
        self.assertEqual(error['code'], 'output_uncertain')
        self.assertTrue(error['uncertain'])
        self.assertEqual(error['retry_action'], 'reconcile_saved_state')
        self.assertTrue((self.board / 'sessions/worker.md').exists())

    def test_cli_json_review_checkpoint_and_failed_commit(self):
        tool = ROOT / 'tools/agent_session.py'
        def run(operation, request):
            return subprocess.run([sys.executable, '-B', str(tool), operation],
                input=json.dumps(request), text=True, capture_output=True, timeout=15)
        result = run('review', {'board': str(self.board), 'scopes': [self.scope]})
        self.assertEqual(result.returncode, 0, result.stderr)
        reviewed = json.loads(result.stdout)
        result = run('checkpoint', {'before': record(claims=f'- file: {self.target}'),
            'state': 'active', 'running_jobs': 'none', 'progress': '- CLI candidate prepared.',
            'handoff': '- None.', 'next_check': '2100-01-01T00:00:00Z / implementation next'})
        self.assertEqual(result.returncode, 0, result.stderr)
        candidate = json.loads(result.stdout)['candidate']
        fields = SESSION.CHECK.parse_record(candidate)[1]
        self.assertEqual(fields['Last inbox check (UTC)'], '2000-01-01T12:00:00Z')
        self.assertIn('CLI candidate prepared', candidate)
        result = run('commit', {'board': str(self.board), 'session': 'worker',
            'candidate': candidate, 'reviewed': reviewed, 'create': True})
        self.assertEqual(result.returncode, 0, result.stderr)
        result = run('commit', {'board': str(self.board), 'session': 'worker',
            'candidate': record(claims=f'- file: {self.target}'), 'reviewed': reviewed, 'create': True})
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('Stop dependent actions', result.stderr)


if __name__ == '__main__':
    unittest.main()
