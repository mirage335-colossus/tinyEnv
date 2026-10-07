"""Manual cleanup freezes complete inventories and refuses active workflows."""
import copy
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import ci_cleanup_repository as cleanup


class Transport:
    def __init__(self, rows=()):
        self.pages = [dict(total_count=len(rows), artifacts=list(rows[offset:offset + 100]))
                      for offset in range(0, max(1, len(rows)), 100)]
        self.runs = {}
        self.calls = []
        self.fail_delete = None

    def json(self, endpoint, *, method='GET'):
        self.calls.append((method, endpoint))
        if method == 'DELETE':
            if endpoint.endswith('/' + str(self.fail_delete)):
                raise ValueError('injected DELETE failure; outcome unconfirmed')
            return None
        if '/actions/runs?' in endpoint:
            status = endpoint.split('status=', 1)[1].split('&', 1)[0]
            value = self.runs.get(status, dict(total_count=0, workflow_runs=[]))
        else:
            value = self.pages[int(endpoint.rsplit('page=', 1)[1]) - 1]
        if isinstance(value, Exception): raise value
        return copy.deepcopy(value)


class RepositoryCleanupTests(unittest.TestCase):
    def setUp(self):
        self.environment = dict(GITHUB_ACTIONS='true', GITHUB_SERVER_URL='https://github.com',
            GITHUB_REPOSITORY='example/project', GITHUB_REPOSITORY_ID='9', GITHUB_RUN_ID='123',
            GITHUB_RUN_ATTEMPT='2', GITHUB_SHA='a' * 40, GITHUB_EVENT_NAME='workflow_dispatch',
            GITHUB_WORKFLOW_REF='example/project/.github/workflows/cleanup-artifacts.yml@refs/heads/main')
        self.sleeps = []

    def row(self, identity, size=10):
        # Duplicate names across different producing runs are expected.
        return dict(id=identity, name='same-name', size_in_bytes=size)

    def purge(self, remote, environment=None):
        return cleanup.purge(environment=self.environment if environment is None else environment,
                             transport=remote, sleep=self.sleeps.append)

    def test_complete_pages_frozen_then_idle_checked_before_any_delete(self):
        remote = Transport([self.row(identity) for identity in range(1, 204)])
        result = self.purge(remote)
        self.assertEqual(result['status'], 'complete')
        self.assertEqual((result['selected_count'], result['selected_bytes']), (203, 2030))
        self.assertEqual((result['deleted_count'], result['deleted_bytes']), (203, 2030))
        self.assertEqual((result['unconfirmed_count'], result['unconfirmed_bytes']), (0, 0))
        self.assertEqual([method for method, _ in remote.calls], ['GET'] * 8 + ['DELETE'] * 203)
        self.assertTrue(all('/actions/artifacts?' in endpoint for _, endpoint in remote.calls[:3]))
        self.assertTrue(all('/actions/runs?' in endpoint for _, endpoint in remote.calls[3:8]))
        self.assertEqual(self.sleeps, [1.0] * 202)

    def test_empty_inventory_needs_one_get_and_no_idle_or_delete_calls(self):
        remote = Transport()
        result = self.purge(remote)
        self.assertEqual(result['status'], 'complete')
        self.assertTrue(result['inventory_complete'])
        self.assertEqual(result['deleted_count'], 0)
        self.assertEqual(len(remote.calls), 1)
        self.assertFalse(self.sleeps)

    def test_every_noncompleted_status_refuses_other_run(self):
        for status in cleanup.ACTIVE_STATUSES:
            with self.subTest(status=status):
                remote = Transport([self.row(1)])
                remote.runs[status] = dict(total_count=1, workflow_runs=[dict(id=124, status=status)])
                result = self.purge(remote)
                self.assertEqual(result['status'], 'refused')
                self.assertIn('not idle', result['error'])
                self.assertEqual(result['unconfirmed_count'], 1)
                self.assertTrue(all(method == 'GET' for method, _ in remote.calls))

    def test_only_exact_current_run_is_excluded(self):
        remote = Transport([self.row(1, 0)])
        remote.runs['in_progress'] = dict(total_count=1, workflow_runs=[dict(id=123, status='in_progress')])
        self.assertEqual(self.purge(remote)['status'], 'complete')
        remote = Transport([self.row(1)])
        remote.runs['in_progress'] = dict(total_count=2, workflow_runs=[
            dict(id=123, status='in_progress'), dict(id=124, status='in_progress', path='cleanup-artifacts.yml')])
        self.assertEqual(self.purge(remote)['status'], 'refused')
        self.assertTrue(all(method == 'GET' for method, _ in remote.calls))

    def test_active_run_shape_count_and_duplicate_errors_stop_deletion(self):
        cases = [dict(total_count=True, workflow_runs=[]), dict(total_count=1, workflow_runs=[]),
                 dict(total_count=0, workflow_runs=None), dict(total_count=1, workflow_runs=[dict(id=True, status='queued')]),
                 dict(total_count=1, workflow_runs=[dict(id=123, status='completed')]),
                 dict(total_count=2, workflow_runs=[dict(id=123, status='queued')] * 2),
                 dict(total_count=100000, workflow_runs=[dict(id=123, status='queued'), dict(id=124, status='queued')])]
        for case in cases:
            with self.subTest(case=case):
                remote = Transport([self.row(1)]); remote.runs['queued'] = case
                result = self.purge(remote)
                self.assertEqual(result['status'], 'refused')
                self.assertTrue(all(method == 'GET' for method, _ in remote.calls))

    def test_changed_or_duplicate_later_artifact_page_prevents_all_deletion(self):
        for last in (dict(total_count=102, artifacts=[self.row(101), self.row(102)]),
                     dict(total_count=101, artifacts=[self.row(1)]), ValueError('page unavailable')):
            with self.subTest(last=last):
                remote = Transport([self.row(identity) for identity in range(1, 102)])
                remote.pages[-1] = last
                result = self.purge(remote)
                self.assertEqual(result['status'], 'refused')
                self.assertFalse(result['inventory_complete'])
                self.assertEqual(result['deleted_count'], 0)
                self.assertEqual([method for method, _ in remote.calls], ['GET', 'GET'])

    def test_malformed_or_oversized_artifact_inventory_refuses(self):
        cases = [dict(total_count=True, artifacts=[]), dict(total_count=1, artifacts=[]),
                 dict(total_count=10001, artifacts=[]), dict(total_count=0, artifacts=None),
                 dict(total_count=1, artifacts=[self.row(True)]),
                 dict(total_count=1, artifacts=[self.row(0)]),
                 dict(total_count=1, artifacts=[self.row(cleanup.cleanup.MAX_ARTIFACT_ID + 1)]),
                 dict(total_count=1, artifacts=[self.row(1, -1)]),
                 dict(total_count=1, artifacts=[self.row(1, True)])]
        for case in cases:
            with self.subTest(case=case):
                remote = Transport(); remote.pages = [case]
                result = self.purge(remote)
                self.assertEqual(result['status'], 'refused')
                self.assertFalse(result['inventory_complete'])
                self.assertEqual(len(remote.calls), 1)

    def test_manual_native_context_required_before_any_requests(self):
        changes = [(key, None) for key in self.environment] + [('GITHUB_EVENT_NAME', 'push'),
            ('GITHUB_EVENT_NAME', 'schedule'), ('GITHUB_SERVER_URL', 'https://other.example'),
            ('GITHUB_WORKFLOW_REF', 'other/project/.github/workflows/cleanup-artifacts.yml@main')]
        for key, value in changes:
            with self.subTest(key=key, value=value):
                environment = dict(self.environment)
                if value is None: del environment[key]
                else: environment[key] = value
                remote = Transport([self.row(1)])
                self.assertEqual(self.purge(remote, environment)['status'], 'refused')
                self.assertFalse(remote.calls)

    def test_delete_failure_reports_only_confirmed_count_and_bytes(self):
        remote = Transport([self.row(1, 13), self.row(2, 17), self.row(3, 19)])
        remote.fail_delete = 2
        result = self.purge(remote)
        self.assertEqual(result['status'], 'failed')
        self.assertEqual((result['deleted_count'], result['deleted_bytes']), (1, 13))
        self.assertEqual((result['unconfirmed_count'], result['unconfirmed_bytes']), (2, 36))
        self.assertEqual(result['unconfirmed_artifact_id'], 2)
        self.assertEqual([method for method, _ in remote.calls], ['GET'] * 6 + ['DELETE'] * 2)
        self.assertEqual(self.sleeps, [1.0])
        self.assertIn('not confirmed', cleanup.summary_text(result))

    def test_real_transport_404_is_not_counted_as_success_or_retried(self):
        remote = Transport([self.row(1)])
        wire = cleanup.delivery.GitHub('example/project'); wire.WRITE_HEADROOM = 0
        saved = remote.json
        def json_request(endpoint, *, method='GET'):
            if method == 'GET': return saved(endpoint, method=method)
            remote.calls.append((method, endpoint))
            return wire.json(endpoint, method=method)
        remote.json = json_request
        response = subprocess.CompletedProcess([], 1, b'HTTP/2.0 404 Not Found\r\n\r\n{"message":"Not Found"}', b'')
        with mock.patch.object(wire, '_run', return_value=response) as request:
            result = self.purge(remote)
        request.assert_called_once()
        self.assertEqual(result['status'], 'failed')
        self.assertEqual(result['deleted_count'], 0)
        self.assertEqual(result['unconfirmed_count'], 1)
        self.assertIn('404', result['error'])

    def test_native_transport_disables_waits_retries_and_quota_probes(self):
        remote = Transport([self.row(1)])
        with mock.patch.object(cleanup.delivery, 'GitHub', return_value=remote) as factory:
            result = cleanup.purge(environment=self.environment, sleep=self.sleeps.append)
        factory.assert_called_once_with('example/project')
        self.assertEqual(result['status'], 'complete')
        for name, expected in [('WRITE_HEADROOM', 0), ('REQUEST_DEADLINE', 30),
                ('COMMAND_TIMEOUT', 30), ('WAIT_BUDGET', 0), ('wait_remaining', 0.0), ('MAX_ATTEMPTS', 1)]:
            self.assertEqual(getattr(remote, name), expected)

    def test_new_artifact_after_freeze_is_not_selected(self):
        remote = Transport([self.row(1)])
        saved = remote.json
        def json_request(endpoint, *, method='GET'):
            if '/actions/runs?' in endpoint:
                remote.pages = [dict(total_count=2, artifacts=[self.row(1), self.row(2)])]
            return saved(endpoint, method=method)
        remote.json = json_request
        result = self.purge(remote)
        self.assertEqual(result['deleted_count'], 1)
        self.assertEqual([endpoint for method, endpoint in remote.calls if method == 'DELETE'],
                         ['repos/example/project/actions/artifacts/1'])

    def test_cli_reports_success_and_partial_failure_in_json_and_step_summary(self):
        for fail in (None, 2):
            with self.subTest(fail=fail), tempfile.TemporaryDirectory() as temporary:
                path = Path(temporary) / 'summary.md'; environment = dict(self.environment, GITHUB_STEP_SUMMARY=str(path))
                remote = Transport([self.row(1, 7), self.row(2, 11)]); remote.fail_delete = fail
                saved = cleanup.purge
                with mock.patch.dict(os.environ, environment, clear=True), \
                        mock.patch.object(cleanup, 'purge', side_effect=lambda **kwargs: saved(environment=environment, transport=remote, sleep=self.sleeps.append, **kwargs)), \
                        mock.patch('sys.stdout', new_callable=io.StringIO) as output:
                    code = cleanup.main([])
                events = [json.loads(line) for line in output.getvalue().splitlines()]
                self.assertEqual(events[0]['event'], 'inventory')
                result = events[-1]
                self.assertEqual(code, 0 if fail is None else 1)
                self.assertEqual(result['deleted_count'], 2 if fail is None else 1)
                self.assertIn('Confirmed deleted: ' + str(result['deleted_count']), path.read_text())
                self.assertIn('release assets are preserved', path.read_text())

    def test_progress_is_bounded_and_deadline_preserves_confirmed_counts(self):
        remote = Transport([self.row(identity, 2) for identity in range(1, 202)])
        events = []
        result = cleanup.purge(environment=self.environment, transport=remote,
                               sleep=self.sleeps.append, progress=events.append)
        self.assertEqual(result['deleted_count'], 201)
        self.assertEqual([event['event'] for event in events], ['inventory', 'progress', 'progress'])
        self.assertEqual([event['deleted_count'] for event in events[1:]], [100, 200])
        remote = Transport([self.row(1, 7), self.row(2, 11)])
        def clock():
            return cleanup.MAX_SECONDS if any(method == 'DELETE' for method, _ in remote.calls) else 0
        result = cleanup.purge(environment=self.environment, transport=remote,
                               sleep=self.sleeps.append, clock=clock)
        self.assertEqual(result['status'], 'failed')
        self.assertEqual(result['deleted_count'], 1)
        self.assertEqual(result['unconfirmed_bytes'], 11)
        self.assertIn('25-minute', result['error'])

    def test_cli_missing_summary_or_arbitrary_arguments_never_purge(self):
        with mock.patch.dict(os.environ, self.environment, clear=True), mock.patch.object(cleanup, 'purge') as purge:
            with self.assertRaises(ValueError): cleanup.main([])
            purge.assert_not_called()
        with mock.patch.object(cleanup, 'purge') as purge, mock.patch('sys.stderr'):
            with self.assertRaises(SystemExit): cleanup.main(['--repository', 'other/project'])
            purge.assert_not_called()


if __name__ == '__main__':
    unittest.main()
