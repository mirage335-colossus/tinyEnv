#!/usr/bin/env python3
"""Candidate records must expose stale/malformed transitions without modifying files."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / 'tools/check_agent_record.py'
spec = importlib.util.spec_from_file_location('agent_record', TOOL)
checker = importlib.util.module_from_spec(spec)
spec.loader.exec_module(checker)


def record(**changes):
    values = dict.fromkeys(checker.REQUIRED_FIELDS, 'none')
    values.update({
        'State': 'active', 'Updated (UTC)': '2000-01-01T10:00:00Z',
        'Last meaningful progress (UTC)': '2000-01-01T09:58:00Z',
        'Last inbox check (UTC)': '2000-01-01T09:59:00Z',
        'Next check (UTC) / action': '2000-01-01T10:05:00Z / check inbox and test result',
        'Liveness mode / cadence': 'checkpoint / five minutes',
        'Owner process': 'unavailable', 'Contact': 'messages/test-session/',
    })
    claims = changes.pop('claims', 'None.')
    values.update(changes)
    return ('# test-session\n## Current checkpoint\n' +
            ''.join(f'- {key}: {value}\n' for key, value in values.items()) +
            f'\n## Claims held\n{claims}\n\n## Blockers and handoff\n- Current request: none\n')


def scan_record(**changes):
    text = record(**changes)
    preamble = ''.join(f'- {key}: value\n' for key in checker.PREAMBLE_FIELDS)
    text = text.replace('# test-session\n', '# test-session\n' + preamble)
    return text.replace('## Blockers and handoff',
                        '## Baseline and dependencies\n- baseline\n\n'
                        '## Progress and checks\n- progress\n\n## Blockers and handoff')


class Transitions(unittest.TestCase):
    def test_claim_addition_requires_same_candidate_timestamp_refresh(self):
        before = record()
        after = record(claims='- directory: /tmp/session-output')
        with self.assertRaisesRegex(ValueError, 'Claims held changed without advancing'):
            checker.check_transition(before, after)
        after = after.replace('10:00:00Z', '10:01:00.001+00:00')
        checker.check_transition(before, after)
        # Actual inbox/progress events need not advance just because claims did.
        self.assertIn('Last inbox check (UTC): 2000-01-01T09:59:00Z', after)

    def test_table_and_bullet_claims_are_compared_completely(self):
        claims = '| Kind | Absolute path | Relative | Use |\n| --- | --- | --- | --- |\n'
        claims += '| file | /project/a | a | change |\n### Additional claims\n- file: /project/b'
        before = record(claims=claims)
        for changed in (claims.replace('/project/b', '/project/c'), claims + '\n- resource: git-index', 'None.'):
            with self.subTest(changed=changed), self.assertRaisesRegex(ValueError, 'Claims held changed'):
                checker.check_transition(before, record(claims=changed))

    def test_duplicate_missing_empty_or_misleveled_canonical_sections_fail(self):
        baseline = record()
        for heading in checker.SECTIONS:
            for candidate in (baseline + f'\n## {heading}\nNone.\n',
                              baseline.replace(f'## {heading}', '## Renamed'),
                              baseline.replace(f'## {heading}', f'### {heading}')):
                with self.subTest(heading=heading), self.assertRaisesRegex(ValueError, 'need exactly one'):
                    checker.check_transition(baseline, candidate)
        with self.assertRaisesRegex(ValueError, 'empty section'):
            checker.check_transition(baseline, record(claims=''))

    def test_missing_duplicate_and_empty_checkpoint_fields_fail(self):
        baseline = record()
        line = '- Last inbox check (UTC): 2000-01-01T09:59:00Z\n'
        for replacement in ('', line + line, '- Last inbox check (UTC): \n'):
            with self.subTest(replacement=replacement), self.assertRaises(ValueError):
                checker.check_transition(baseline, baseline.replace(line, replacement))

    def test_fenced_examples_cannot_supply_or_truncate_claims(self):
        baseline = record()
        for fence in ('```markdown', '~~~markdown'):
            with self.subTest(fence=fence), self.assertRaisesRegex(ValueError, 'fenced examples'):
                checker.check_transition(baseline, record(claims='- file: /project/a\n' + fence +
                    '\n## Claims held\nNone.\n' + fence[:3]))

    def test_next_check_can_move_earlier_when_the_plan_changes(self):
        checker.check_transition(record(), record(**{
            'Updated (UTC)': '2000-01-01T10:01:00Z',
            'Next check (UTC) / action': '2000-01-01T10:02:00Z / check new request'}))

    def test_elapsed_next_check_and_invalid_times_fail(self):
        baseline = record()
        for value in ('2000-01-01T09:59:00Z / check', '2000-01-01T10:00:00Z / check',
                      'none / wait', '2000-01-01T10:05:00Z',
                      '2000-01-01T10:05:00+01:00 / check', '2000-13-27T10:05:00Z / check'):
            with self.subTest(value=value), self.assertRaises(ValueError):
                checker.check_transition(baseline, record(**{'Next check (UTC) / action': value}))

    def test_future_events_and_backwards_event_times_fail(self):
        for field in ('Updated (UTC)', 'Last meaningful progress (UTC)', 'Last inbox check (UTC)'):
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, 'moved backwards'):
                checker.check_transition(record(), record(**{field: '2000-01-01T09:00:00Z'}))
        for field in ('Last meaningful progress (UTC)', 'Last inbox check (UTC)'):
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, 'later than Updated'):
                checker.check_transition(record(), record(**{field: '2000-01-01T10:01:00Z'}))

    def test_terminal_claims_never_disappear_due_to_stage(self):
        for state in checker.TERMINAL:
            for claims in ('- file: /project/held', 'None.\n- file: /project/still-held',
                           '| Kind | Absolute path |', 'None; see release note.'):
                candidate = record(claims=claims, State=state, **{'Updated (UTC)': '2000-01-01T10:01:00Z'})
                with self.subTest(state=state, claims=claims), self.assertRaisesRegex(ValueError, 'retains Claims held'):
                    checker.check_transition(record(), candidate)

    def test_closure_requires_job_and_time_disposition(self):
        values = {'State': 'done', 'Updated (UTC)': '2000-01-01T10:01:00Z',
                  'Next check (UTC) / action': 'none / complete',
                  'Closed (UTC), if terminal': '2000-01-01T10:01:00Z',
                  'Delete after (UTC)': '2000-01-31T10:01:00Z'}
        checker.check_transition(record(claims='- file: /project/a'), record(**values))
        for key, bad in (('Running jobs', 'PID 123, still running'),
                         ('Closed (UTC), if terminal', '2000-01-01T10:02:00Z'),
                         ('Delete after (UTC)', '2000-01-01T09:59:00Z')):
            with self.subTest(key=key), self.assertRaises(ValueError):
                checker.check_transition(record(), record(**{**values, key: bad}))

    def test_comparing_different_sessions_fails(self):
        with self.assertRaisesRegex(ValueError, 'session IDs differ'):
            checker.check_transition(record(), record().replace('# test-session', '# another-session'))

    def test_terminal_session_id_cannot_be_reopened(self):
        for old_state in checker.TERMINAL:
            for new_state in ('active', 'waiting', 'paused'):
                with self.subTest(old=old_state, new=new_state), self.assertRaisesRegex(
                        ValueError, 'fresh session ID and reacquire claims'):
                    checker.check_transition(record(State=old_state), record(State=new_state))

    def test_retention_extension_needs_explicit_exception(self):
        values = {'State': 'done', 'Updated (UTC)': '2000-01-01T10:01:00Z',
                  'Next check (UTC) / action': 'none / complete',
                  'Closed (UTC), if terminal': '2000-01-01T10:01:00Z',
                  'Delete after (UTC)': '2000-01-31T10:01:00.001Z'}
        for empty in ('none', 'None.'):
            with self.subTest(empty=empty), self.assertRaisesRegex(ValueError, 'explicit Retention exception'):
                checker.check_transition(record(), record(**{**values, 'Retention exception': empty}))
        values['Retention exception'] = 'artifacts/x / pending integration / owner B / evidence / review 2000-01-04'
        checker.check_transition(record(), record(**values))

    def test_terminal_completed_job_prose_gets_actionable_private_diagnostic(self):
        candidate = record(State='done', **{
            'Running jobs': 'none; secret completed job details',
            'Next check (UTC) / action': 'none / complete',
            'Closed (UTC), if terminal': '2000-01-01T10:00:00Z',
            'Delete after (UTC)': '2000-01-31T10:00:00Z'})
        with self.assertRaisesRegex(ValueError, 'literal none') as caught:
            checker.check_transition(record(), candidate)
        self.assertIn('Progress and checks', str(caught.exception))
        self.assertNotIn('secret', str(caught.exception))


class CommandLine(unittest.TestCase):
    def test_success_and_failure_leave_both_files_and_neighbor_records_untouched(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            before, after, neighbor = [root / name for name in ('before.md', 'after.md', 'neighbor.md')]
            before.write_text(record(), encoding='utf-8')
            neighbor.write_bytes(b'not even a valid record\xff')
            for candidate, status in ((record(**{'Updated (UTC)': '2000-01-01T10:01:00Z'}), 0),
                                      (record(claims='- file: /project/new'), 1)):
                after.write_text(candidate, encoding='utf-8')
                snapshot = {p.name: p.read_bytes() for p in root.iterdir()}
                result = subprocess.run([sys.executable, '-B', str(TOOL), '--before', str(before),
                                         '--after', str(after)], capture_output=True, text=True)
                self.assertEqual(result.returncode, status, result.stderr)
                self.assertEqual(snapshot, {p.name: p.read_bytes() for p in root.iterdir()})
                if status == 0:
                    self.assertIn('ownership, handoff and factual review still required', result.stdout)
            for bad_path in (before, root / 'missing.md'):
                result = subprocess.run([sys.executable, '-B', str(TOOL), '--before', str(before),
                                         '--after', str(bad_path)], capture_output=True, text=True)
                self.assertEqual(result.returncode, 1)
                self.assertNotIn('Traceback', result.stderr)


class SessionScan(unittest.TestCase):
    def test_known_missing_and_empty_fields_are_named_without_unknown_content(self):
        path = Path('/board/sessions/test-session.md')
        for key in ('Last heartbeat (UTC), if supervised', 'Retention exception'):
            for replacement in ('', f'- {key}: \n'):
                with self.subTest(key=key, replacement=replacement), self.assertRaises(ValueError) as caught:
                    checker.scan_record(scan_record().replace(f'- {key}: none\n', replacement), path)
                self.assertIn(key, str(caught.exception))
        missing = scan_record().replace('- Parent / read-only helpers: value\n', '')
        with self.assertRaisesRegex(ValueError, 'missing current-template preamble fields: Parent'):
            checker.scan_record(missing, path)
        for section in ('checkpoint', 'preamble'):
            candidate = scan_record().replace('- State: active' if section == 'checkpoint' else
                                               '- Task and approach: value',
                                               '- secret-label: secret-value')
            with self.assertRaises(ValueError) as caught:
                checker.scan_record(candidate, path)
            self.assertNotIn('secret', str(caught.exception))

    def test_terminal_nested_claims_remain_complete_and_opaque(self):
        claims = ('| Kind | Absolute path | Relative | Use |\n| --- | --- | --- | --- |\n'
                  '| file | /project/a | a | change |\n### Additional claims\n'
                  '- directory: /project/held\n#### Resource\n- resource: git-index\n' +
                  '\n'.join(f'- file: /project/{i}' for i in range(200)))
        path = Path('/board/sessions/test-session.md')
        for state in checker.TERMINAL:
            with self.subTest(state=state):
                output = checker.scan_record(scan_record(claims=claims, State=state), path)
                self.assertEqual(output['claims'], claims)
                self.assertEqual(output['metadata']['State'], state)
                self.assertEqual(output['id'], 'test-session')

    def test_unrelated_task_and_disposition_text_never_enters_scan_output(self):
        text = scan_record(**{'Next check (UTC) / action':
                             '2000-01-01T10:05:00Z / secret-next-action'})
        text = text.replace('Task and approach: value', 'Task and approach: secret-task')
        text = text.replace('work owned by others): value', 'work owned by others): secret-diff')
        text = text.replace('- baseline', '- secret-baseline')
        text = text.replace('- progress', '- secret-progress\n### More progress\nsecret-nested')
        text = text.replace('- Current request: none', '- secret-handoff')
        output = checker.scan_record(text, Path('/board/sessions/test-session.md'))
        self.assertNotIn('secret', json.dumps(output))
        self.assertEqual(output['metadata']['Next check (UTC)'], '2000-01-01T10:05:00Z')
        self.assertIn('Running jobs', output['metadata'])
        self.assertIn('Checkout / coordination root (absolute physical paths)', output['metadata'])

    def test_unknown_or_ambiguous_structures_need_manual_review(self):
        good = scan_record()
        bad_records = [
            record(), good.replace('## Claims held', '## Claims'),
            good + '\n## Private secret summary\nsecret-value\n',
            good.replace('## Progress and checks', '## Claims held'),
            good.replace('- State: active', '- State: active\n- Unknown: secret-value'),
            good.replace('- State: active', '- State: active\n- State: active'),
            good.replace('- Task and approach: value', 'Task and approach: value'),
            good.replace('- Task and approach: value', '- Task and approach: value\n- Extra: secret-value'),
            good.replace('## Claims held', '### Claims held'),
            good.replace('# test-session', '# wrong-session'),
            good.replace('## Claims held\nNone.', '## Claims held\n'),
            good.replace('## Claims held\nNone.', '## Claims held\n```\n## Claims held\n```'),
        ]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'test-session.md'
            for candidate in bad_records:
                with self.subTest(candidate=candidate):
                    path.write_text(candidate, encoding='utf-8')
                    output = checker.scan_sessions(Path(directory))
                    self.assertFalse(output['complete'])
                    self.assertEqual(output['records'], [])
                    self.assertEqual(len(output['errors']), 1)
                    self.assertNotIn('secret', json.dumps(output))

    def test_unreadable_and_invalid_utf8_records_make_partial_output_incomplete(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            good, broken = root / 'test-session.md', root / 'broken.md'
            good.write_text(scan_record(), encoding='utf-8')
            broken.write_bytes(b'\xff')
            output = checker.scan_sessions(root)
            self.assertFalse(output['complete'])
            self.assertEqual([r['id'] for r in output['records']], ['test-session'])
            original = checker.read_scan_record

            def read(path, *args, **kwargs):
                if path == broken:
                    raise PermissionError('cannot read record')
                return original(path, *args, **kwargs)

            with mock.patch.object(checker, 'read_scan_record', read):
                output = checker.scan_sessions(root)
            self.assertFalse(output['complete'])
            self.assertEqual([r['id'] for r in output['records']], ['test-session'])
            self.assertEqual(output['errors'], [{'path': str(broken), 'error': 'cannot read record'}])
            self.assertIn('omitted records may hold claims', output['advisory'])

    def test_direct_entries_only_and_symlinks_are_never_read(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            sessions = root / 'sessions'
            sessions.mkdir()
            (sessions / 'test-session.md').write_text(scan_record(), encoding='utf-8')
            (sessions / 'unexpected.tmp').write_text('secret-temp', encoding='utf-8')
            (sessions / 'nested.md').mkdir()
            (sessions / 'nested.md' / 'hidden.md').write_text('secret-nested', encoding='utf-8')
            outside = root / 'outside.md'
            outside.write_text('secret-external', encoding='utf-8')
            link = sessions / 'alias.md'
            try:
                link.symlink_to(outside)
            except (OSError, NotImplementedError):
                self.skipTest('symlinks unavailable')
            output = checker.scan_sessions(sessions)
            self.assertFalse(output['complete'])
            self.assertEqual([r['id'] for r in output['records']], ['test-session'])
            self.assertEqual({Path(e['path']).name for e in output['errors']},
                             {'unexpected.tmp', 'nested.md', 'alias.md'})
            self.assertNotIn('secret', json.dumps(output))
            alias = root / 'alias'
            alias.symlink_to(sessions, target_is_directory=True)
            self.assertFalse(checker.scan_sessions(alias)['complete'])

    def test_observed_concurrent_change_fails_instead_of_publishing_partial_claims(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'test-session.md'
            path.write_text(scan_record(), encoding='utf-8')
            original = checker.read_scan_record

            def change_during_read(p, *args, **kwargs):
                result = original(p, *args, **kwargs)
                p.write_text(result + '\nchanged', encoding='utf-8')
                return result

            with mock.patch.object(checker, 'read_scan_record', change_during_read):
                output = checker.scan_sessions(Path(directory))
            self.assertFalse(output['complete'])
            self.assertEqual(output['records'], [])
            self.assertIn('changed while being read', output['errors'][0]['error'])
            self.assertEqual(output['errors'][0]['code'], 'snapshot_changed')

    def test_read_access_time_change_does_not_invalidate_unchanged_record(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'test-session.md'
            path.write_text(scan_record(), encoding='utf-8')
            original = Path.lstat
            calls = 0

            def access_time_changes(p):
                nonlocal calls
                info = original(p)
                if p == path:
                    calls += 1
                    # Keep nanosecond content/identity fields; only atime differs.
                    info = mock.Mock(wraps=info, st_atime=info.st_atime + calls,
                                     **{key: getattr(info, key) for key in
                                        ('st_dev', 'st_ino', 'st_mode', 'st_size',
                                         'st_mtime_ns', 'st_ctime_ns')})
                return info

            with mock.patch.object(Path, 'lstat', access_time_changes):
                output = checker.scan_sessions(Path(directory))
            self.assertTrue(output['complete'], output)
            self.assertGreaterEqual(calls, 2)

    def test_prior_record_replacement_is_detected_before_scan_returns(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first, second = root / 'a.md', root / 'b.md'
            first.write_text(scan_record().replace('test-session', 'a'), encoding='utf-8')
            second.write_text(scan_record().replace('test-session', 'b'), encoding='utf-8')
            original = checker.read_scan_record

            def replace_prior(path, *args):
                text = original(path, *args)
                if path == second:
                    first.write_text(first.read_text() + '\nchanged', encoding='utf-8')
                return text

            with mock.patch.object(checker, 'read_scan_record', replace_prior):
                output = checker.scan_sessions(root)
            self.assertFalse(output['complete'])
            self.assertTrue(any(e['path'] == str(first) and 'changed after read' in e['error']
                                for e in output['errors']))

    def test_created_then_removed_temporary_entry_still_invalidates_snapshot(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'test-session.md').write_text(scan_record(), encoding='utf-8')
            original = checker.read_scan_record

            def transient(path, *args):
                text = original(path, *args)
                temp = root / 'candidate.tmp'
                temp.write_text('secret temporary candidate', encoding='utf-8')
                temp.unlink()
                # Some filesystems coalesce rapid timestamps. Model an observed
                # directory change; identical final metadata is undetectable by
                # this explicitly non-atomic reader.
                info = root.stat()
                os.utime(root, ns=(info.st_atime_ns, info.st_mtime_ns + 1_000_000_000))
                return text

            with mock.patch.object(checker, 'read_scan_record', transient):
                output = checker.scan_sessions(root)
            self.assertFalse(output['complete'])
            self.assertTrue(any('directory entries changed' in e['error'] for e in output['errors']))
            self.assertTrue(all(e.get('code') == 'snapshot_changed' for e in output['errors']))
            self.assertNotIn('secret', json.dumps(output))

    def test_snapshot_race_does_not_reclassify_malformed_entries(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'test-session.md').write_text(scan_record(), encoding='utf-8')
            (root / 'malformed.md').write_text('unknown owner format', encoding='utf-8')
            original = checker.read_scan_record

            def changed(path, *args):
                text = original(path, *args)
                info = root.stat()
                os.utime(root, ns=(info.st_atime_ns, info.st_mtime_ns + 1_000_000_000))
                return text

            with mock.patch.object(checker, 'read_scan_record', changed):
                result = checker.scan_sessions(root)
            self.assertFalse(result['complete'])
            self.assertTrue(any(e.get('code') == 'snapshot_changed' for e in result['errors']))
            malformed = [e for e in result['errors'] if e['path'] == str(root / 'malformed.md')]
            self.assertTrue(malformed)
            self.assertTrue(all('code' not in e for e in malformed))

    def test_replaced_record_descriptor_is_rejected_before_read(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'test-session.md'
            path.write_text(scan_record(), encoding='utf-8')
            before = path.lstat()
            replacement = Path(directory) / 'replacement'
            replacement.write_text('secret unrelated replacement', encoding='utf-8')
            replacement.replace(path)
            with self.assertRaisesRegex(ValueError, 'replaced before read'):
                checker.read_scan_record(path, before)

    def test_scan_cli_status_and_files_are_read_only(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / 'test-session.md'
            path.write_text(scan_record(), encoding='utf-8')
            for malformed in (False, True):
                if malformed:
                    (root / 'legacy.md').write_text('# legacy\nState: done\n', encoding='utf-8')
                snapshot = {p.name: p.read_bytes() for p in root.iterdir()}
                result = subprocess.run([sys.executable, '-B', str(TOOL), '--scan', str(root)],
                                        capture_output=True, text=True)
                self.assertEqual(result.returncode, int(malformed), result.stderr)
                self.assertEqual(json.loads(result.stdout)['complete'], not malformed)
                self.assertEqual(snapshot, {p.name: p.read_bytes() for p in root.iterdir()})
            for arguments in ([], ['--before', str(path)], ['--after', str(path)],
                              ['--scan', str(root), '--before', str(path)],
                              ['--scan', str(root), '--after', str(path)]):
                result = subprocess.run([sys.executable, '-B', str(TOOL)] + arguments,
                                        capture_output=True, text=True)
                self.assertEqual(result.returncode, 2)
                self.assertNotIn('Traceback', result.stderr)
            result = subprocess.run([sys.executable, '-B', str(TOOL), '--scan', str(root / 'missing')],
                                    capture_output=True, text=True)
            self.assertEqual(result.returncode, 1)
            self.assertFalse(json.loads(result.stdout)['complete'])


class TargetedInspection(unittest.TestCase):
    def test_current_metadata_claims_and_handoff_selections_are_disjoint(self):
        path = Path('/board/sessions/test-session.md')
        claims = '- file: /project/held\n### Child scope\n- directory: /project/subtree'
        text = scan_record(claims=claims).replace('Task and approach: value',
                                                'Task and approach: secret-task')
        text = text.replace('- progress', '- secret-progress').replace('- baseline', '- secret-baseline')
        text = text.replace('- Current request: none', '- selected-handoff\n### Details\nrelease reference A-1')
        selected = checker.inspect_record(text, path)
        self.assertTrue(selected['complete'], selected)
        self.assertEqual(selected['claims'], claims)
        self.assertNotIn('secret', json.dumps(selected))
        self.assertNotIn('selected-handoff', json.dumps(selected))
        selected = checker.inspect_record(text, path, 'handoff')
        self.assertTrue(selected['complete'], selected)
        self.assertEqual(selected['handoff'], '- selected-handoff\n### Details\nrelease reference A-1')
        for unwanted in ('secret', '/project/held', 'Owner process', 'metadata', 'claims'):
            self.assertNotIn(unwanted, json.dumps({k: v for k, v in selected.items() if k != 'advisory'}))

    def test_legacy_fallback_is_incomplete_with_whole_terminal_claims(self):
        claims = '- file: /project/a\n### Additional claims\n' + '\n'.join(
            f'- directory: /project/{i}' for i in range(200))
        text = ('# legacy\n- State: done\n- Closed (UTC): 2000-01-01T10:00:00Z\n'
                '- Liveness: checkpoint ended\n- Task and approach: secret-task\n'
                f'## Claims held\n{claims}\n## Progress\n- State: secret-progress\n'
                '## Blockers and handoff\n- secret-handoff\n')
        selected = checker.inspect_record(text, Path('/board/legacy.md'))
        self.assertFalse(selected['complete'])
        self.assertTrue(selected['errors'])
        self.assertEqual(selected['claims'], claims)
        self.assertIn({'field': 'State', 'value': 'done'}, selected['metadata'])
        self.assertNotIn('secret', json.dumps(selected))
        self.assertIn('unvalidated', selected['advisory'])

    def test_metadata_error_keeps_safe_complete_claims_but_never_succeeds(self):
        claims = '- file: /project/a\n### More\n- resource: git-state'
        text = scan_record(claims=claims).replace('- Retention exception: none\n', '')
        selected = checker.inspect_record(text, Path('/board/test-session.md'))
        self.assertFalse(selected['complete'])
        self.assertEqual(selected['claims'], claims)
        self.assertIn('Retention exception', selected['errors'][0]['error'])

    def test_ambiguous_claims_are_never_returned_as_complete(self):
        baseline = scan_record(claims='- file: /project/a')
        for text in (baseline + '\n## Claims held\n- file: /project/other\n',
                     baseline.replace('## Claims held', '### Claims held'),
                     baseline.replace('## Claims held', '```\n## Claims held') + '\n```',
                     baseline.replace('- file: /project/a', '')):
            with self.subTest(text=text):
                selected = checker.inspect_record(text, Path('/board/test-session.md'))
                self.assertFalse(selected['complete'])
                self.assertNotIn('claims', selected)
                self.assertTrue(selected['errors'])

    def test_fallback_handoff_does_not_expose_earlier_sections(self):
        text = ('# legacy\n- State: secret-state\n## Claims held\n- secret-claim\n'
                '## Blockers and handoff\nrelease A-2\n### Nested\nwriters stopped\n'
                '## Secret later heading\nsecret-history\n')
        selected = checker.inspect_record(text, Path('/board/legacy.md'), 'handoff')
        self.assertFalse(selected['complete'])
        self.assertEqual(selected['handoff'], 'release A-2\n### Nested\nwriters stopped')
        self.assertNotIn('secret', json.dumps(selected).lower())

    def test_fallback_ignores_unknown_metadata_and_malformed_next_action(self):
        text = scan_record().replace('- Retention exception: none', '- secret-key: secret-value')
        text = text.replace('2000-01-01T10:05:00Z / check inbox and test result', 'secret action without timestamp')
        selected = checker.inspect_record(text, Path('/board/test-session.md'))
        self.assertFalse(selected['complete'])
        self.assertNotIn('secret', json.dumps(selected))

    def test_inspection_rejects_symlink_invalid_utf8_and_changing_record(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / 'test-session.md'
            path.write_text(scan_record(), encoding='utf-8')
            link = root / 'link.md'
            try:
                link.symlink_to(path)
            except (OSError, NotImplementedError):
                self.skipTest('symlinks unavailable')
            self.assertFalse(checker.inspect_path(link)['complete'])
            original = checker.read_scan_record

            def mutate(p, *args):
                text = original(p, *args)
                p.write_text(text + '\nchanged', encoding='utf-8')
                return text

            with mock.patch.object(checker, 'read_scan_record', mutate):
                result = checker.inspect_path(path)
            self.assertFalse(result['complete'])
            self.assertNotIn('claims', result)
            path.write_bytes(b'\xff')
            self.assertFalse(checker.inspect_path(path)['complete'])

    def test_cli_compact_equivalence_and_inspection_exit_status(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / 'test-session.md'
            path.write_text(scan_record(), encoding='utf-8')
            (root / 'temporary.tmp').write_text('secret candidate', encoding='utf-8')
            for mode, expected in ((['--scan', str(root)], 1), (['--inspect', str(path)], 0),
                                   (['--inspect', str(path), '--section', 'handoff'], 0)):
                results = [subprocess.run([sys.executable, '-B', str(TOOL)] + mode + compact,
                                         cwd=ROOT, capture_output=True, text=True)
                           for compact in ([], ['--compact'])]
                self.assertEqual([r.returncode for r in results], [expected, expected])
                self.assertEqual(json.loads(results[0].stdout), json.loads(results[1].stdout))
                self.assertLess(len(results[1].stdout), len(results[0].stdout))
            path.write_text(path.read_text().replace('- Retention exception: none\n', ''), encoding='utf-8')
            result = subprocess.run([sys.executable, '-B', str(TOOL), '--inspect', str(path)],
                                    cwd=ROOT, capture_output=True, text=True)
            self.assertEqual(result.returncode, 1)
            self.assertEqual(json.loads(result.stdout)['claims'], 'None.')

    def test_field_discovery_and_invalid_mode_combinations(self):
        result = subprocess.run([sys.executable, '-B', str(TOOL), '--fields'],
                                cwd=ROOT, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)['checkpoint'], list(checker.REQUIRED_FIELDS))
        for args in (['--compact'], ['--section', 'handoff'], ['--fields', '--compact'],
                     ['--inspect', 'a.md', '--scan', 'sessions'],
                     ['--inspect', 'a.md', '--before', 'a.md', '--after', 'b.md']):
            with self.subTest(args=args):
                result = subprocess.run([sys.executable, '-B', str(TOOL)] + args,
                                        cwd=ROOT, capture_output=True, text=True)
                self.assertEqual(result.returncode, 2)
                self.assertNotIn('Traceback', result.stderr)


class ScopedDiscovery(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name).resolve()
        self.sessions = self.root / 'sessions'
        self.sessions.mkdir()
        self.target = self.root / 'project' / 'ledger.md'

    def tearDown(self):
        self.temporary.cleanup()

    def save(self, name, handoff='- Current request: none', claims='None.', state='done', *, complete=False):
        if complete:
            handoff = '- Scope inventory: complete\n' + handoff
        text = scan_record(claims=claims, State=state).replace('test-session', name)
        text = text.replace('- Current request: none', handoff)
        text = text.replace('Checkout / coordination root (absolute physical paths): value',
                            f'Checkout / coordination root (absolute physical paths): {self.root / "project"} / {self.root}')
        path = self.sessions / (name + '.md')
        path.write_text(text, encoding='utf-8')
        return path

    def lookup(self):
        return checker.scan_sessions(self.sessions, [checker.canonical_scope('file', str(self.target))])

    def test_closed_intervening_unchanged_owner_and_covering_scope_are_returned(self):
        for name, scope, acquired in (
                ('relay', self.target, 'initial'), ('quiet-owner', self.target, 'relay-release'),
                ('covering', self.target.parent, 'quiet-owner-release')):
            kind = 'directory' if name == 'covering' else 'file'
            self.save(name, f'- Scope: {kind}: {scope}\n- Release: {name}-release; acquired from {acquired}; unchanged bytes\n'
                            '### Evidence\nAll writers stopped; hash 0000; keep this whole section.', complete=True)
        self.save('sibling', f'- Scope: file: {self.target}2\n- Release: sibling-release', complete=True)
        result = self.lookup()
        self.assertTrue(result['complete'], result)
        self.assertEqual([entry['id'] for entry in result['records']], ['covering', 'quiet-owner', 'relay'])
        for entry in result['records']:
            self.assertIn('### Evidence', entry['handoff'])
            self.assertEqual(entry['state'], 'done')
        self.assertNotIn('owner', result)  # Discovery does not choose a lineage tip.

    def test_query_aliases_resolve_but_recorded_alias_claims_are_rejected(self):
        project = self.root / 'project'
        project.mkdir()
        alias = self.root / 'alias'
        alias.symlink_to(project, target_is_directory=True)
        self.assertEqual(checker.canonical_scope('file', str(alias / 'ledger.md'))['value'], str(self.target))
        self.save('owner', claims=f'- file: {alias / "ledger.md"}')
        result = self.lookup()
        self.assertFalse(result['complete'])
        self.assertIn('canonical physical paths', result['errors'][0]['error'])

    def test_exact_resource_and_quoted_path_with_spaces(self):
        scope = checker.canonical_scope('resource', 'device:host:shared-unit')
        self.save('resource', '- Scope: resource: device:host:shared-unit\n- Release: release-1; writers stopped', complete=True)
        self.save('other', '- Scope: resource: device:host:shared-unit-extra\n- Release: release-2', complete=True)
        result = checker.scan_sessions(self.sessions, [scope])
        self.assertEqual([entry['id'] for entry in result['records']], ['resource'])
        spaced = self.root / 'project' / 'file with spaces'
        text = self.save('spaced', f'- Scope: file: {spaced}\n- Released `{spaced}` unchanged', complete=True).read_text()
        self.assertTrue(checker.handoff_relevance(text, [checker.canonical_scope('file', str(spaced))]))

    def test_opaque_or_mixed_legacy_handoff_is_explicitly_uncertain(self):
        self.save('ambiguous', '- Released /unrelated/file; also released ledger unchanged.')
        self.save('legacy', '- Scope: ledger\n- Release: unknown')
        self.save('opaque', '- R1 previous work handed back; inspect owner note.')
        result = self.lookup()
        self.assertFalse(result['complete'])
        self.assertEqual(len(result['errors']), 3)
        self.assertEqual(len(result['records']), 3)
        self.assertTrue(all(entry['relevance_uncertain'] for entry in result['records']))
        self.assertIn('also released ledger unchanged', result['records'][0]['handoff'])

    def test_partial_explicit_inventory_never_hides_opaque_history(self):
        histories = {
            'partial': '- Scope: file: /unrelated/file\n- Release: R1; also released ledger unchanged.',
            'none': '- Scope: none\n- R1 previous work handed back; inspect owner note.',
            'named': f'- Scope: file: {self.target}\n- Release: R2; another unnamed file also released.',
        }
        for name, handoff in histories.items():
            self.save(name, handoff)
        result = self.lookup()
        self.assertFalse(result['complete'])
        self.assertEqual(len(result['errors']), len(histories))
        self.assertEqual({entry['id'] for entry in result['records']}, set(histories))
        for entry in result['records']:
            self.assertTrue(entry['relevance_uncertain'])
            self.assertEqual(entry['handoff'], histories[entry['id']])

    def test_complete_inventory_allows_prose_without_guessing_path_mentions(self):
        prose = ('\n### Evidence\nPrevious release R1 was unchanged; all writers stopped. '
                 f'Reference only: `{self.target}`; syntax /tmp/[example] is not another scope.')
        self.save('unrelated', '- Scope: file: /unrelated/file' + prose, complete=True)
        self.save('related', f'- Scope: file: {self.target}' + prose, complete=True)
        result = self.lookup()
        self.assertTrue(result['complete'], result)
        self.assertEqual([entry['id'] for entry in result['records']], ['related'])
        self.assertIn(prose.strip(), result['records'][0]['handoff'])

    def test_simple_unmarked_scope_rows_and_neutral_history_remain_supported(self):
        self.save('related', f'- Scope: file: {self.target}\n- Current request: none')
        self.save('unrelated', '- Scope: file: /unrelated/file')
        self.save('empty', '- Scope: none\n- No pending handoffs.')
        result = self.lookup()
        self.assertTrue(result['complete'], result)
        self.assertEqual([entry['id'] for entry in result['records']], ['related'])

    def test_incomplete_or_contradictory_inventory_assertions_are_uncertain(self):
        declarations = (
            '- Scope inventory: complete\n- Scope inventory: complete\n- Scope: none',
            '- Scope inventory: partial\n- Scope: none',
            '- Scope inventory: complete\n- Scope inventory: partial\n- Scope: none',
            '- Scope inventory: complete',
            f'- Scope inventory: complete\n- Scope: none\n- Scope: file: {self.target}',
            f'- Scope: none\n- Acquired scope: file: {self.target}',
            '- Scope inventory: complete\n- Scope: ledger',
            f'- Scope inventory: complete\n- Scope: file: {self.target}\n- Retained scope:',
            f'- Scope inventory: complete\n- Scope: file: {self.target}\n- Scope file: /omitted',
            f'- Scope inventory complete\n- Scope: file: {self.target}',
        )
        for number, declaration in enumerate(declarations):
            self.save(f'invalid-{number}', declaration)
        result = self.lookup()
        self.assertFalse(result['complete'])
        self.assertEqual(len(result['errors']), len(declarations))
        self.assertEqual(len(result['records']), len(declarations))
        self.assertTrue(all(entry['relevance_uncertain'] for entry in result['records']))

    def test_explicit_empty_complete_inventory_allows_explanatory_prose(self):
        self.save('empty', '- Scope: none\n- This session only read documents; no ownership history.', complete=True)
        result = self.lookup()
        self.assertTrue(result['complete'], result)
        self.assertEqual(result['records'], [])

    def test_actual_claim_kind_must_match_existing_filesystem_type(self):
        directory = self.root / 'owned-directory'
        directory.mkdir()
        child = directory / 'source.py'
        child.write_text('source')
        for kind, path in (('file', directory), ('directory', child)):
            with self.subTest(kind=kind, path=path), self.assertRaisesRegex(ValueError, 'claim kind'):
                checker.parse_claims(f'- {kind}: {path}')
        self.save('owner', claims=f'- file: {directory}')
        result = checker.scan_sessions(self.sessions, [checker.canonical_scope('file', str(child))])
        self.assertFalse(result['complete'])
        self.assertEqual([entry['path'] for entry in result['errors']], [str(self.sessions / 'owner.md')])
        self.assertIn('claim kind', result['errors'][0]['error'])

    def test_future_claim_types_are_revalidated_after_materialization_or_replacement(self):
        future = self.root / 'future'
        for kind in ('file', 'directory'):
            self.assertEqual(checker.parse_claims(f'- {kind}: {future}')[0]['kind'], kind)
        future.mkdir()
        with self.assertRaisesRegex(ValueError, 'claim kind'):
            checker.parse_claims(f'- file: {future}')
        self.assertEqual(checker.parse_claims(f'- directory: {future}')[0]['kind'], 'directory')
        future.rmdir()
        future.write_text('replacement')
        with self.assertRaisesRegex(ValueError, 'claim kind'):
            checker.parse_claims(f'- directory: {future}')
        self.assertEqual(checker.parse_claims(f'- file: {future}')[0]['kind'], 'file')

    def test_claim_validation_does_not_change_prior_scope_interpretation(self):
        self.target.parent.mkdir()
        self.target.mkdir()
        scope = checker.canonical_scope('file', str(self.target))
        self.assertEqual(scope['kind'], 'file')
        text = self.save('history', f'- Scope: file: {self.target}\n- Released before it became a directory.',
                         complete=True).read_text()
        self.assertTrue(checker.handoff_relevance(text, [scope]))
        with self.assertRaisesRegex(ValueError, 'claim kind'):
            checker.validate_claim_scope('file', str(self.target))

    def test_claim_type_permission_uncertainty_is_not_absence(self):
        with mock.patch.object(checker, 'canonical_scope', return_value={'kind': 'file', 'value': str(self.target)}), \
                mock.patch.object(checker.Path, 'stat', side_effect=PermissionError('denied')):
            with self.assertRaises(PermissionError):
                checker.validate_claim_scope('file', str(self.target))

    @unittest.skipUnless(hasattr(os, 'mkfifo'), 'FIFO fixture needs POSIX')
    def test_nonregular_file_claim_fails_without_opening_it(self):
        fifo = self.root / 'fifo'
        os.mkfifo(fifo)
        with self.assertRaisesRegex(ValueError, 'claim kind'):
            checker.parse_claims(f'- file: {fifo}')

    def test_unknown_claims_and_unreadable_or_legacy_records_never_disappear(self):
        self.save('malformed', claims='- claim a file somehow')
        legacy = self.save('legacy')
        legacy.write_text(legacy.read_text().replace('## Baseline and dependencies', '## Old baseline'))
        (self.sessions / 'unreadable.md').write_bytes(b'\xff')
        (self.sessions / 'candidate.tmp').write_text('not a record')
        result = self.lookup()
        self.assertFalse(result['complete'])
        self.assertEqual({Path(item['path']).name for item in result['errors']},
                         {'malformed.md', 'legacy.md', 'unreadable.md', 'candidate.tmp'})

    def test_terminal_retained_claim_remains_visible(self):
        self.save('terminal', claims=f'- directory: {self.target.parent}', state='done')
        result = self.lookup()
        self.assertTrue(result['complete'], result)
        self.assertEqual(result['records'][0]['claims'], f'- directory: {self.target.parent}')

    def test_component_boundaries_and_hard_link_aliases(self):
        directory = checker.canonical_scope('directory', str(self.root / 'a'))
        self.assertTrue(checker.scopes_overlap(directory, checker.canonical_scope('file', str(self.root / 'a/x'))))
        self.assertFalse(checker.scopes_overlap(directory, checker.canonical_scope('file', str(self.root / 'ab/x'))))
        a, b = self.root / 'one', self.root / 'two'
        a.write_text('same')
        os.link(a, b)
        self.assertTrue(checker.scopes_overlap(checker.canonical_scope('file', str(a)),
                                              checker.canonical_scope('file', str(b))))
        with self.assertRaisesRegex(ValueError, 'hard-linked'):
            checker.parse_claims(f'- file: {a}')

    def test_strict_claim_tables_keep_nested_and_all_rows(self):
        claims = (f'| Kind | Absolute path | Relative | Use |\n| --- | --- | --- | --- |\n'
                  f'| directory | {self.root / "a"} | a | outputs |\n'
                  f'### More\n- file: {self.root / "b"}\n- resource: git:common')
        self.assertEqual(len(checker.parse_claims(claims)), 3)
        for bad in ('None.\n- file: /x', '| Kind | Absolute path | Relative | Use |',
                    '- file: relative', '- file: /tmp/*', '- file: /tmp/x; extra',
                    '| file | /x | x | use |'):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                checker.parse_claims(bad)

    def test_permission_uncertainty_does_not_become_no_overlap(self):
        with mock.patch.object(checker.os.path, 'samefile', side_effect=PermissionError('denied')):
            with self.assertRaises(PermissionError):
                checker.scopes_overlap(checker.canonical_scope('file', str(self.root / 'x')),
                                        checker.canonical_scope('file', str(self.root / 'y')))

    def test_future_case_and_unicode_aliases_conflict_conservatively(self):
        pairs = [(self.root / 'Root/Foo', self.root / 'root/foo/child'),
                 (self.root / 'caf\u00e9', self.root / 'cafe\u0301/child')]
        for directory, child in pairs:
            with self.subTest(directory=directory):
                self.assertTrue(checker.scopes_overlap(checker.canonical_scope('directory', str(directory)),
                                                      checker.canonical_scope('file', str(child))))

    def test_portable_path_aliases_never_become_independent_claims(self):
        for leaf in ('file.', 'file ', 'file:stream', 'CON', 'nul.txt', 'LPT9', 'COM\u00b9.txt', 'a\\b'):
            with self.subTest(leaf=leaf), self.assertRaises(ValueError):
                checker.canonical_scope('file', str(self.root / leaf))
        self.assertEqual(checker.canonical_scope('resource', 'device:host:shared-unit'),
                         {'kind': 'resource', 'value': 'device:host:shared-unit'})

    @unittest.skipUnless(os.name == 'posix', 'undecodable byte filenames are POSIX-specific')
    def test_undecodable_names_remain_visible_errors_and_page_identity(self):
        bad = self.sessions / os.fsdecode(b'unknown-\xff.md')
        bad.write_text('not a valid session record', encoding='utf-8')
        first = self.lookup()
        self.assertFalse(first['complete'])
        self.assertEqual([item['path'] for item in first['errors']], [str(bad)])
        page = checker.page_result(first, 0, 1)
        self.assertEqual(page['errors'], first['errors'])
        renamed = self.sessions / os.fsdecode(b'unknown-\xfe.md')
        bad.rename(renamed)
        with self.assertRaisesRegex(ValueError, 'snapshot changed'):
            checker.page_result(self.lookup(), 0, 1, first['snapshot'])
        self.assertEqual(checker.read_document(renamed)['content'], 'not a valid session record')

    def test_large_scan_pages_all_records_and_all_errors_without_dropping_sections(self):
        for number in range(75):
            self.save(f'owner-{number:03}', f'- Scope: file: {self.target}\n- Release: R{number}\n' + 'detail ' * 40, complete=True)
        (self.sessions / 'unknown.tmp').write_text('unknown')
        result = self.lookup()
        snapshot = result['snapshot']
        records, errors, offset = [], [], 0
        while True:
            page = checker.page_result(self.lookup(), offset, 7, snapshot if offset else None)
            self.assertFalse(page['complete'])
            self.assertEqual(page['total_errors'], 1)
            self.assertLessEqual(len(page['records']) + len(page['errors']), 7)
            records.extend(page['records']); errors.extend(page['errors'])
            if page['next_offset'] is None:
                break
            offset = page['next_offset']
        self.assertEqual(len(records), 75)
        self.assertEqual(len(errors), 1)
        self.assertEqual(len({entry['id'] for entry in records}), 75)
        self.assertTrue(all('detail ' * 39 in entry['handoff'] for entry in records))

    def test_changed_snapshot_and_unbound_later_page_are_rejected(self):
        path = self.save('owner', f'- Scope: file: {self.target}\n- Release: R1', complete=True)
        first = self.lookup()
        with self.assertRaisesRegex(ValueError, 'require --snapshot'):
            checker.page_result(first, 1, 1)
        path.write_text(path.read_text().replace('Release: R1', 'Release: R2; unchanged bytes'))
        with self.assertRaisesRegex(ValueError, 'snapshot changed'):
            checker.page_result(self.lookup(), 1, 1, first['snapshot'])

    def test_unreadable_entry_change_also_invalidates_snapshot(self):
        path = self.sessions / 'broken.md'
        path.write_bytes(b'\xff')
        first = self.lookup()
        path.write_bytes(b'\xff\xff')
        with self.assertRaisesRegex(ValueError, 'snapshot changed'):
            checker.page_result(self.lookup(), 0, 1, first['snapshot'])
        # Even changing an unrelated record must not be silently mixed into pages.
        first = self.lookup()
        self.save('new-unrelated')
        with self.assertRaisesRegex(ValueError, 'snapshot changed'):
            checker.page_result(self.lookup(), 1, 1, first['snapshot'])

    def test_document_pages_round_trip_long_unicode_lines_and_reject_changes(self):
        document = self.root / 'guide.md'
        body = 'intro\r\n' + '\u03bb' * 12000 + '\r\nlast\n'
        document.write_bytes(body.encode())
        first = checker.read_document(document, limit=137)
        parts, current = [], first
        while True:
            parts.append(current['content'])
            self.assertLessEqual(len(current['content']), 137)
            if current['next_offset'] is None:
                break
            current = checker.read_document(document, current['next_offset'], 137, first['snapshot'])
        self.assertEqual(''.join(parts), body)
        document.write_text(body + 'changed')
        with self.assertRaisesRegex(ValueError, 'snapshot changed'):
            checker.read_document(document, 137, 137, first['snapshot'])
        alias = self.root / 'alias.md'
        alias.symlink_to(document)
        with self.assertRaisesRegex(ValueError, 'not a symlink'):
            checker.read_document(alias)

    def test_symlink_loop_and_bad_document_input_fail_explicitly(self):
        a, b = self.root / 'loop-a', self.root / 'loop-b'
        a.symlink_to(b); b.symlink_to(a)
        with self.assertRaises((OSError, ValueError)):
            checker.canonical_scope('file', str(a / 'future'))
        document = self.root / 'bad.txt'
        document.write_bytes(b'\xff')
        failed = subprocess.run([sys.executable, '-B', str(TOOL), '--read', str(document)],
                                cwd=ROOT, capture_output=True, text=True)
        self.assertEqual(failed.returncode, 1)
        self.assertFalse(json.loads(failed.stdout)['complete'])
        self.assertNotIn('Traceback', failed.stderr)

    def test_cli_modes_pages_and_errors(self):
        self.save('one', f'- Scope: file: {self.target}\n- Release: R1', complete=True)
        self.save('two', f'- Scope: file: {self.target}\n- Release: R2', complete=True)
        base = [sys.executable, '-B', str(TOOL), '--handoffs', str(self.sessions), '--scope', str(self.target),
                '--limit', '1', '--compact']
        first = subprocess.run(base, cwd=ROOT, capture_output=True, text=True)
        self.assertEqual(first.returncode, 0, first.stderr)
        page = json.loads(first.stdout)
        self.assertEqual(page['next_offset'], 1)
        self.assertFalse(page['all_returned'])
        second = subprocess.run(base + ['--offset', '1', '--snapshot', page['snapshot']],
                                cwd=ROOT, capture_output=True, text=True)
        self.assertEqual(second.returncode, 0, second.stderr)
        self.assertIsNone(json.loads(second.stdout)['next_offset'])
        for args in (['--handoffs', str(self.sessions)], ['--scope', str(self.target)],
                     ['--fields', '--limit', '1'], ['--read', 'x', '--inspect', 'y']):
            with self.subTest(args=args):
                bad = subprocess.run([sys.executable, '-B', str(TOOL)] + args,
                                     cwd=ROOT, capture_output=True, text=True)
                self.assertEqual(bad.returncode, 2)
        bad = subprocess.run(base + ['--offset', '1'], cwd=ROOT, capture_output=True, text=True)
        self.assertEqual(bad.returncode, 1)
        self.assertIn('require --snapshot', bad.stdout)


if __name__ == '__main__':
    unittest.main()
