"""Direct cleanup validates all trusted upload IDs before any mutation."""
import io
import json
from pathlib import Path
import sys
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import ci_cleanup as cleanup


class Transport:
    def __init__(self):
        self.calls = []
        self.fail_delete = None

    def json(self, endpoint, *, method='GET'):
        self.calls.append((method, endpoint))
        if method != 'DELETE':
            raise AssertionError('cleanup must never discover, probe or read back artifacts')
        if endpoint.endswith('/' + str(self.fail_delete)):
            raise ValueError('injected deletion failure')
        return None


class CleanupTests(unittest.TestCase):
    def setUp(self):
        self.environment = dict(GITHUB_ACTIONS='true', GITHUB_SERVER_URL='https://github.com',
            GITHUB_REPOSITORY='example/project', GITHUB_REPOSITORY_ID='9', GITHUB_RUN_ID='123',
            GITHUB_RUN_ATTEMPT='2', GITHUB_SHA='a' * 40,
            GITHUB_WORKFLOW_REF='example/project/.github/workflows/_release-latest.yml@refs/heads/main')
        self.environment[cleanup.IDS_ENV] = '[1, "5"]'
        self.sleeps = []

    def run_cleanup(self, remote, raw=None):
        environment = dict(self.environment)
        if raw is not None: environment[cleanup.IDS_ENV] = raw
        return cleanup.cleanup(environment=environment, transport=remote, sleep=self.sleeps.append)

    def test_deletes_only_supplied_ids_with_no_discovery_and_sequential_pacing(self):
        remote = Transport()
        result = self.run_cleanup(remote)
        self.assertEqual(result, dict(run_id=123, attempt=2, selected=2, deleted=2))
        self.assertEqual(remote.calls, [
            ('DELETE', 'repos/example/project/actions/artifacts/1'),
            ('DELETE', 'repos/example/project/actions/artifacts/5')])
        self.assertEqual(self.sleeps, [1.0])

    def test_string_and_number_duplicates_delete_once_in_original_order(self):
        remote = Transport()
        result = self.run_cleanup(remote, '["5", 1, 5, "1", "5"]')
        self.assertEqual(result['deleted'], 2)
        self.assertEqual([endpoint.rsplit('/', 1)[1] for _, endpoint in remote.calls], ['5', '1'])
        self.assertEqual(self.sleeps, [1.0])

    def test_empty_explicit_array_never_creates_transport_or_sleeps(self):
        environment = dict(self.environment); environment[cleanup.IDS_ENV] = ' [] '
        with mock.patch.object(cleanup.delivery, 'GitHub') as factory:
            result = cleanup.cleanup(environment=environment, sleep=self.sleeps.append)
        self.assertEqual(result, dict(run_id=123, attempt=2, selected=0, deleted=0))
        factory.assert_not_called()
        self.assertFalse(self.sleeps)

    def test_native_transport_has_no_quota_wait_or_retry(self):
        remote = Transport()
        with mock.patch.object(cleanup.delivery, 'GitHub', return_value=remote) as factory:
            result = cleanup.cleanup(environment=self.environment, sleep=self.sleeps.append)
        factory.assert_called_once_with('example/project')
        self.assertEqual(result['deleted'], 2)
        self.assertEqual(remote.WRITE_HEADROOM, 0)
        self.assertEqual(remote.REQUEST_DEADLINE, 30)
        self.assertEqual(remote.COMMAND_TIMEOUT, 30)
        self.assertEqual(remote.WAIT_BUDGET, 0)
        self.assertEqual(remote.wait_remaining, 0.0)
        self.assertEqual(remote.MAX_ATTEMPTS, 1)
        self.assertEqual([method for method, _ in remote.calls], ['DELETE', 'DELETE'])

    def test_missing_input_fails_before_transport(self):
        environment = dict(self.environment); del environment[cleanup.IDS_ENV]
        with mock.patch.object(cleanup.delivery, 'GitHub') as factory:
            with self.assertRaisesRegex(ValueError, 'explicit artifact-ids'):
                cleanup.cleanup(environment=environment, sleep=self.sleeps.append)
        factory.assert_not_called()
        self.assertFalse(self.sleeps)

    def test_missing_or_foreign_context_never_queries(self):
        changes = [(key, None) for key in self.environment if key != cleanup.IDS_ENV] + [
            ('GITHUB_ACTIONS', 'false'), ('GITHUB_SERVER_URL', 'https://other.example'),
            ('GITHUB_RUN_ID', '0'), ('GITHUB_RUN_ATTEMPT', '02'),
            ('GITHUB_REPOSITORY_ID', '-9'), ('GITHUB_SHA', 'not-a-commit'),
            ('GITHUB_WORKFLOW_REF', 'other/project/.github/workflows/cleanup.yml@main')]
        for key, value in changes:
            with self.subTest(key=key, value=value):
                environment = dict(self.environment)
                if value is None: del environment[key]
                else: environment[key] = value
                remote = Transport()
                with self.assertRaises(ValueError):
                    cleanup.cleanup(environment=environment, transport=remote, sleep=self.sleeps.append)
                self.assertFalse(remote.calls)

    def test_malformed_json_or_nonarray_never_deletes(self):
        for raw in ('', ' ', 'null', '{}', '1', '"1"', '[1,', '[1] trailing', '[NaN]', '[Infinity]'):
            with self.subTest(raw=raw):
                remote = Transport()
                with self.assertRaises(ValueError): self.run_cleanup(remote, raw)
                self.assertFalse(remote.calls)
        self.assertFalse(self.sleeps)

    def test_invalid_later_id_prevents_every_delete(self):
        for item in ('', '0', '01', '-1', ' 1', '+1', '1.0', '1e2', '1/2', '９',
                     0, -1, True, False, None, 1.0, [], {}, cleanup.MAX_ARTIFACT_ID + 1,
                     str(cleanup.MAX_ARTIFACT_ID + 1)):
            with self.subTest(item=item):
                remote = Transport()
                with self.assertRaisesRegex(ValueError, 'canonical positive integer'):
                    self.run_cleanup(remote, json.dumps([1, item]))
                self.assertFalse(remote.calls)
        self.assertFalse(self.sleeps)

    def test_bounded_ids_and_selection(self):
        remote = Transport()
        raw = json.dumps([cleanup.MAX_ARTIFACT_ID, str(cleanup.MAX_ARTIFACT_ID)])
        self.assertEqual(self.run_cleanup(remote, raw)['deleted'], 1)
        self.assertEqual(remote.calls[0][1], 'repos/example/project/actions/artifacts/' + str(cleanup.MAX_ARTIFACT_ID))
        for raw in (json.dumps([1] * (cleanup.MAX_DELETE + 1)), ' ' * cleanup.MAX_INPUT_BYTES + '[]'):
            with self.subTest(length=len(raw)):
                remote = Transport()
                with self.assertRaises(ValueError): self.run_cleanup(remote, raw)
                self.assertFalse(remote.calls)

    def test_deletion_failure_stops_without_retry_or_readback(self):
        remote = Transport(); remote.fail_delete = 2
        with self.assertRaisesRegex(ValueError, 'after 1 of 3 confirmed deletions'):
            self.run_cleanup(remote, '[1, 2, 3]')
        self.assertEqual(remote.calls, [('DELETE', 'repos/example/project/actions/artifacts/1'),
                                        ('DELETE', 'repos/example/project/actions/artifacts/2')])
        self.assertEqual(self.sleeps, [1.0])

    def test_cli_reads_exact_environment_input(self):
        remote = Transport()
        with mock.patch.dict(cleanup.os.environ, self.environment, clear=True), \
                mock.patch.object(cleanup.delivery, 'GitHub', return_value=remote), \
                mock.patch('sys.stdout', new_callable=io.StringIO) as output, \
                mock.patch.object(cleanup, 'cleanup', wraps=cleanup.cleanup) as run:
            # A single explicit ID avoids deliberate mutation pacing in this CLI check.
            cleanup.os.environ[cleanup.IDS_ENV] = '["91"]'
            cleanup.main([])
        run.assert_called_once_with()
        self.assertEqual(json.loads(output.getvalue())['deleted'], 1)
        self.assertEqual(remote.calls, [('DELETE', 'repos/example/project/actions/artifacts/91')])

    def test_cli_has_no_arbitrary_repository_or_run_override(self):
        with mock.patch.object(cleanup, 'cleanup') as run, mock.patch('sys.stderr'):
            with self.assertRaises(SystemExit): cleanup.main(['--run-id', '999'])
            run.assert_not_called()


if __name__ == '__main__':
    unittest.main()
