"""Protocol transition, truthful event metadata and no-dual-writer regressions."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import subprocess
import sys
import unittest
from datetime import datetime, timedelta, timezone
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('agent_migrate', ROOT / 'tools/agent_migrate.py')
MIGRATE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MIGRATE)
COMPAT, SESSION = MIGRATE.COMPAT, MIGRATE.SESSION


@unittest.skipUnless(os.name == 'posix', 'safe transition requires descriptor-relative operations')
class ProtocolTransition(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='coordination-transition-')
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()
        self.board = COMPAT.Board(self.root)
        self.board.apply('init', {})
        self.call('register', task='Change one generic file.', approach='Inspect, change, verify.',
                  baseline='No unrelated changes.', next_action='Inspect.', next_check=COMPAT.now())

    def call(self, operation, **request):
        return self.board.apply(operation, dict(id='worker', revision=self.board.read()['revision'], **request))

    def close(self):
        self.call('close', state='done', writers_stopped=True, result='Work complete.', disposition='Retained for integration.')

    def migrate(self, **changes):
        raw = self.board.state_path.read_bytes()
        values = dict(root=str(self.root), board=str(self.board.path), revision=self.board.read()['revision'],
                      expected_sha256=hashlib.sha256(raw).hexdigest(), operator='migration-owner',
                      review='All sessions closed, independent output and queued writers stopped.',
                      writers_stopped=True, exclusive_administration=True)
        values.update(changes)
        return MIGRATE.migrate(**values)

    def test_live_session_blocks_migration_without_side_effects(self):
        original = self.board.state_path.read_bytes()
        with self.assertRaisesRegex(MIGRATE.MigrationError, 'every source session'):
            self.migrate()
        self.assertEqual(original, self.board.state_path.read_bytes())
        self.assertFalse((self.board.path / 'sessions').exists())

    def test_missing_exclusion_and_stale_snapshot_are_clean_rejections(self):
        self.close()
        for change in ({'writers_stopped': False}, {'exclusive_administration': False},
                       {'expected_sha256': '0' * 64}, {'revision': -1}):
            with self.subTest(change=change), self.assertRaises(MIGRATE.MigrationError) as caught:
                self.migrate(**change)
            self.assertFalse(caught.exception.uncertain)
        self.assertFalse((self.board.path / 'sessions').exists())

    def test_full_protocol_refuses_a_live_json_board(self):
        with self.assertRaisesRegex(ValueError, 'compatibility JSON'):
            SESSION.review(self.board.path)
        with self.assertRaisesRegex(ValueError, 'compatibility JSON'):
            SESSION.initialize(self.board.path)
        self.assertFalse((self.board.path / 'sessions').exists())

    def test_closed_records_releases_messages_and_source_dates_survive(self):
        target = self.root / 'sample.txt'
        target.write_text('preserve')
        scope = {'kind': 'file', 'value': str(target)}
        self.call('claim', scopes=[scope])
        self.call('release', scopes=[scope], writers_stopped=True, disposition='Exact changes retained.')
        self.call('message', to='worker', message_id='retained', body='Useful unresolved note.')
        self.close()
        source = self.board.state_path.read_bytes()
        old = self.board.read()['sessions']['worker']
        receipt = self.migrate()
        self.assertEqual(Path(receipt['source_snapshot']).read_bytes(), source)
        self.assertFalse(self.board.state_path.exists())
        record = (self.board.path / 'sessions/worker.md').read_text()
        fields = SESSION.CHECK.parse_record(record)[1]
        self.assertEqual(fields['Closed (UTC), if terminal'], old['closed'])
        self.assertEqual(fields['Delete after (UTC)'], old['delete_after'])
        self.assertEqual(fields['Last inbox check (UTC)'], 'unavailable')
        reviewed = SESSION.review(self.board.path, scopes=[scope])
        self.assertIn('worker', reviewed['relevant_handoffs'])
        message = self.board.path / 'messages/worker/worker-retained.md'
        self.assertIn('Useful unresolved note.', message.read_text())
        self.assertEqual(target.read_text(), 'preserve')
        with self.assertRaisesRegex(COMPAT.Rejected, 'migrated'):
            self.board.read()
        with self.assertRaises(ValueError):
            self.board.apply('init', {})

    def test_failure_during_conversion_retains_source_and_blocks_both_protocols(self):
        self.close()
        before = self.board.state_path.read_bytes()
        real = MIGRATE.PUBLISH.exclusive_publish
        def fail_record(source, temporary, destination, name):
            if name.endswith('.md'):
                raise OSError('injected conversion publication failure')
            return real(source, temporary, destination, name)
        with mock.patch.object(MIGRATE.PUBLISH, 'exclusive_publish', side_effect=fail_record):
            with self.assertRaises(MIGRATE.MigrationError) as caught:
                self.migrate()
        self.assertTrue(caught.exception.uncertain)
        self.assertEqual(self.board.state_path.read_bytes(), before)
        with self.assertRaises(ValueError):
            self.board.read()
        with self.assertRaisesRegex(ValueError, 'compatibility JSON'):
            SESSION.review(self.board.path)

    def test_error_after_authority_switch_retains_new_state_and_reports_uncertainty(self):
        self.close()
        real = MIGRATE.os.unlink
        def unlink_then_fail(path, *args, **kwargs):
            result = real(path, *args, **kwargs)
            if path == 'state.json':
                raise OSError('injected post-switch failure')
            return result
        # Capability membership refers to the real builtin, not the injected wrapper.
        MIGRATE.PUBLISH.require_capabilities()
        with mock.patch.object(MIGRATE.PUBLISH, 'require_capabilities'), \
                mock.patch.object(MIGRATE.os, 'unlink', side_effect=unlink_then_fail):
            with self.assertRaises(MIGRATE.MigrationError) as caught:
                self.migrate()
        self.assertTrue(caught.exception.uncertain)
        self.assertFalse(self.board.state_path.exists())
        self.assertIn('worker', SESSION.review(self.board.path)['record_hashes'])
        with self.assertRaises(ValueError):
            self.board.read()

    def test_compatibility_paging_requires_bound_revision(self):
        with self.assertRaisesRegex(COMPAT.Rejected, 'first page revision'):
            self.board.apply('status', {'offset': 1})


class CompleteRecordInputs(unittest.TestCase):
    def test_capabilities_cli_needs_no_stdin_or_filesystem_mutation(self):
        result = subprocess.run([sys.executable, '-B', str(ROOT / 'tools/agent_session.py'), 'capabilities'],
                                stdin=subprocess.DEVNULL, capture_output=True, text=True, check=True)
        self.assertFalse(json.loads(result.stdout)['filesystem_qualified'])

    def test_capability_report_never_claims_filesystem_qualification(self):
        report = SESSION.capabilities()
        self.assertFalse(report['filesystem_qualified'])
        with mock.patch.object(MIGRATE.PUBLISH.os, 'supports_dir_fd', set()):
            report = SESSION.capabilities()
        self.assertFalse(report['record_publication_primitives'])
        self.assertFalse(report['guarded_edit_primitives'])
        self.assertTrue(report['missing'])

    def test_unknown_events_remain_explicit_and_cannot_erase_known_events(self):
        from test_agent_session import record
        text = SESSION.set_fields(record(), {'Last inbox check (UTC)': 'unavailable',
                                             'Last meaningful progress (UTC)': 'unavailable'})
        SESSION.CHECK.check_transition(text, text)
        known = SESSION.set_fields(text, {'Last inbox check (UTC)': '2000-01-01T11:00:00Z'})
        SESSION.CHECK.check_transition(text, known)
        with self.assertRaisesRegex(ValueError, 'moved backwards'):
            SESSION.CHECK.check_transition(known, text)

    def test_complete_template_renders_to_a_checked_candidate(self):
        request = json.loads((ROOT / 'docs/templates/session.json').read_text())
        at = datetime.now(timezone.utc)
        request['checkpoint']['Updated (UTC)'] = at.isoformat()
        request['checkpoint']['Next check (UTC) / action'] = (at + timedelta(minutes=5)).isoformat() + ' / inspect inbox'
        result = SESSION.render_record(**request)
        SESSION.CHECK.scan_record(result['candidate'], Path(request['session'] + '.md'))


@unittest.skipUnless(os.name == 'posix', 'safe initialization requires descriptor-relative operations')
class RecordBoardInitialization(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='coordination-initialization-')
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()
        self.board = self.root / 'board'

    def test_fresh_board_is_usable_and_repeat_initialization_preserves_contents(self):
        SESSION.initialize(self.board)
        note = self.board / 'notes/kept.txt'
        note.write_text('preserve')
        SESSION.initialize(self.board)
        self.assertEqual(note.read_text(), 'preserve')
        self.assertEqual(SESSION.review(self.board)['record_hashes'], {})

    def test_known_bad_namespace_is_rejected_before_creating_siblings(self):
        self.board.mkdir()
        target = self.root / 'outside'
        target.mkdir()
        for alias in (False, True):
            with self.subTest(alias=alias):
                bad = self.board / 'notes'
                bad.symlink_to(target, target_is_directory=True) if alias else bad.write_text('wrong type')
                with self.assertRaises((OSError, ValueError)):
                    SESSION.initialize(self.board)
                self.assertFalse((self.board / 'sessions').exists())
                self.assertFalse(list(target.iterdir()))
                bad.unlink()

    def test_partial_initialization_reports_uncertainty_and_is_inspectable(self):
        real = MIGRATE.PUBLISH.child_directory
        from contextlib import contextmanager
        @contextmanager
        def fail_messages(parent, name, create=False):
            if name == 'messages':
                raise OSError('injected directory creation failure')
            with real(parent, name, create=create) as opened:
                yield opened
        with mock.patch.object(MIGRATE.PUBLISH, 'child_directory', side_effect=fail_messages):
            with self.assertRaises(SESSION.CoordinationError) as caught:
                SESSION.initialize(self.board)
        self.assertTrue(caught.exception.uncertain)
        self.assertTrue((self.board / 'sessions').is_dir())
        SESSION.initialize(self.board)
        self.assertEqual(SESSION.review(self.board)['record_hashes'], {})

    def test_unknown_or_malformed_marker_refuses_review_and_initialization(self):
        self.board.mkdir()
        for content in ('not json', '{"protocol":"different","version":2}',
                        '{"protocol":"records","version":3}',
                        '{"protocol":"records","version":2,"unexpected":true}'):
            with self.subTest(content=content):
                (self.board / 'protocol.json').write_text(content)
                with self.assertRaises(ValueError):
                    SESSION.initialize(self.board)
                with self.assertRaises(ValueError):
                    SESSION.review(self.board)
                self.assertFalse((self.board / 'sessions').exists())


if __name__ == '__main__':
    unittest.main()
