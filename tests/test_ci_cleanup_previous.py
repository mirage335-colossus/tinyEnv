"""Completed full workflows prune one exact predecessor with frozen inventories."""
import copy
import io
import json
import os
from pathlib import Path
import re
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import ci_cleanup_previous as cleanup


def run(identity, number, *, workflow='candidate.yml', attempt=1):
    repository = dict(id=9, full_name='example/project')
    return dict(id=identity, workflow_id=7, run_number=number, run_attempt=attempt,
                path='.github/workflows/' + workflow, event='workflow_dispatch',
                status='completed', conclusion='success', head_sha='a' * 40,
                repository=repository, head_repository=repository)


def job(identity, producer, *, marker='success'):
    steps = [] if marker is None else [dict(name=cleanup.MARKER, status='completed', conclusion=marker)]
    return dict(id=identity, run_id=producer['id'], head_sha=producer['head_sha'],
                name=cleanup.WORKFLOWS[producer['path'].rsplit('/', 1)[1]],
                status='completed', conclusion='success', steps=steps)


def artifact(identity, producer, size=10):
    return dict(id=identity, name='identical-name-across-runs', size_in_bytes=size,
                workflow_run=dict(id=producer['id'], repository_id=9, head_repository_id=9,
                                  head_sha=producer['head_sha']))


class Transport:
    def __init__(self):
        self.current = run(123, 10)
        self.previous = run(122, 9)
        self.runs = {123: self.current, 122: self.previous}
        self.history = [self.current, self.previous]
        self.jobs = {123: [job(1230, self.current)], 122: [job(1220, self.previous)]}
        self.artifacts = {122: [artifact(1, self.previous), artifact(2, self.previous, 20)]}
        self.active = {}
        self.overrides = {}
        self.calls = []
        self.fail_delete = None

    @staticmethod
    def page(rows, field, endpoint):
        page = int(endpoint.rsplit('page=', 1)[1])
        return dict(total_count=len(rows), **{field: rows[(page - 1) * 100:page * 100]})

    def json(self, endpoint, *, method='GET'):
        self.calls.append((method, endpoint))
        if method == 'DELETE':
            if endpoint.endswith('/' + str(self.fail_delete)):
                raise ValueError('DELETE outcome unconfirmed')
            return None
        if endpoint in self.overrides:
            value = self.overrides[endpoint]
            if isinstance(value, Exception): raise value
            return copy.deepcopy(value)
        if '/actions/workflows/' in endpoint:
            value = self.page(self.history, 'workflow_runs', endpoint)
        elif '/jobs?' in endpoint:
            identity = int(endpoint.split('/actions/runs/')[1].split('/')[0])
            value = self.page(self.jobs.get(identity, []), 'jobs', endpoint)
        elif '/artifacts?' in endpoint:
            identity = int(endpoint.split('/actions/runs/')[1].split('/')[0])
            value = self.page(self.artifacts.get(identity, []), 'artifacts', endpoint)
        elif '/actions/runs?' in endpoint:
            status = endpoint.split('status=')[1].split('&')[0]
            rows = self.active.get(status, [])
            value = dict(total_count=len(rows), workflow_runs=rows[:2])
        else:
            value = self.runs[int(endpoint.rsplit('/', 1)[1])]
        return copy.deepcopy(value)


class PreviousCleanupTests(unittest.TestCase):
    def setUp(self):
        self.environment = dict(GITHUB_ACTIONS='true', GITHUB_SERVER_URL='https://github.com',
            GITHUB_REPOSITORY='example/project', GITHUB_REPOSITORY_ID='9', GITHUB_RUN_ID='900',
            GITHUB_RUN_ATTEMPT='1', GITHUB_SHA='b' * 40, GITHUB_EVENT_NAME='workflow_run',
            GITHUB_WORKFLOW_REF='example/project/.github/workflows/cleanup-previous-run.yml@refs/heads/main')
        self.remote = Transport()
        self.event = dict(action='completed', workflow_run=copy.deepcopy(self.remote.current))
        self.sleeps = []

    def prune(self, **kwargs):
        return cleanup.prune(environment=self.environment, event=self.event, transport=self.remote,
                             sleep=self.sleeps.append, **kwargs)

    def assert_read_only(self):
        self.assertTrue(all(method == 'GET' for method, _ in self.remote.calls))

    def test_exact_predecessor_deleted_after_full_inventory_and_idle_barrier(self):
        result = self.prune()
        self.assertEqual(result['status'], 'complete')
        self.assertEqual(result['previous_run_id'], 122)
        self.assertEqual((result['selected_count'], result['selected_bytes']), (2, 30))
        self.assertEqual((result['deleted_count'], result['deleted_bytes']), (2, 30))
        deletes = [(method, endpoint) for method, endpoint in self.remote.calls if method == 'DELETE']
        self.assertEqual(deletes, [('DELETE', 'repos/example/project/actions/artifacts/1'),
                                  ('DELETE', 'repos/example/project/actions/artifacts/2')])
        first_delete = next(index for index, call in enumerate(self.remote.calls) if call[0] == 'DELETE')
        self.assertEqual(sum('/actions/runs?status=' in endpoint for _, endpoint in self.remote.calls[:first_delete]), 5)
        self.assertEqual(self.sleeps, [1.0])

    def test_current_failed_active_preparation_preserved_and_partial_rerun_never_prune(self):
        for field, value in (('conclusion', 'failure'), ('status', 'in_progress'), ('run_attempt', 2)):
            with self.subTest(field=field):
                self.setUp()
                self.event['workflow_run'][field] = value
                self.remote.current[field] = value
                result = self.prune()
                self.assertIn(result['status'], ('refused', 'skipped'))
                self.assert_read_only()
        for marker in (None, 'skipped', 'failure'):
            with self.subTest(marker=marker):
                self.setUp()
                self.remote.jobs[123] = [job(1230, self.remote.current, marker=marker)]
                self.assertEqual(self.prune()['status'], 'skipped')
                self.assert_read_only()

    def test_wrong_context_fork_workflow_and_source_are_refused_before_requests(self):
        for change in ('foreign-fork', 'wrong-workflow', 'wrong-event', 'wrong-server', 'own-run'):
            with self.subTest(change=change):
                self.setUp()
                if change == 'foreign-fork': self.event['workflow_run']['head_repository']['id'] = 99
                elif change == 'wrong-workflow': self.event['workflow_run']['path'] = '.github/workflows/sdk-maintenance.yml'
                elif change == 'wrong-event': self.environment['GITHUB_EVENT_NAME'] = 'workflow_dispatch'
                elif change == 'wrong-server': self.environment['GITHUB_SERVER_URL'] = 'https://other.example'
                else: self.event['workflow_run']['id'] = 900
                self.assertEqual(self.prune()['status'], 'refused')
                self.assertFalse(self.remote.calls)

    def test_first_marked_run_keeps_unmarked_history_and_current_artifacts(self):
        self.remote.jobs[122] = [job(1220, self.remote.previous, marker=None)]
        result = self.prune()
        self.assertEqual(result['status'], 'complete')
        self.assertIsNone(result['previous_run_id'])
        self.assertEqual(result['selected_count'], 0)
        self.assert_read_only()

    def test_nearest_eligible_predecessor_skips_preserved_and_newer_runs(self):
        newest = run(124, 11)
        preserved = run(121, 8)
        old = run(120, 7)
        self.remote.jobs[122] = [job(1220, self.remote.previous, marker='skipped')]
        self.remote.jobs[121] = [job(1210, preserved, marker='skipped')]
        self.remote.jobs[120] = [job(1200, old)]
        self.remote.history += [newest, preserved, old]
        self.remote.runs.update({124: newest, 121: preserved, 120: old})
        self.remote.artifacts[120] = [artifact(77, old)]
        result = self.prune()
        self.assertEqual(result['previous_run_id'], 120)
        self.assertEqual([endpoint for method, endpoint in self.remote.calls if method == 'DELETE'],
                         ['repos/example/project/actions/artifacts/77'])
        self.assertFalse(any('/runs/124/' in endpoint for _, endpoint in self.remote.calls))

    def test_complete_history_and_artifact_pagination_precede_deletion(self):
        self.remote.current['run_number'] = 1000
        self.remote.previous['run_number'] = 999
        self.event['workflow_run']['run_number'] = 1000
        self.remote.history += [run(identity, identity - 19) for identity in range(20, 119)]
        self.remote.artifacts[122] = [artifact(identity, self.remote.previous) for identity in range(1, 204)]
        result = self.prune()
        self.assertEqual((result['status'], result['deleted_count']), ('complete', 203))
        calls = self.remote.calls[:next(index for index, call in enumerate(self.remote.calls) if call[0] == 'DELETE')]
        self.assertEqual(sum('/actions/workflows/' in endpoint for _, endpoint in calls), 2)
        self.assertEqual(sum('/artifacts?' in endpoint for _, endpoint in calls), 3)

    def test_changed_duplicate_incomplete_or_oversized_later_pages_refuse_before_delete(self):
        for last in (dict(total_count=102, artifacts=[artifact(101, self.remote.previous)]),
                     dict(total_count=101, artifacts=[artifact(1, self.remote.previous)]),
                     dict(total_count=101, artifacts=[]), ValueError('missing page')):
            with self.subTest(last=last):
                self.setUp()
                self.remote.artifacts[122] = [artifact(identity, self.remote.previous) for identity in range(1, 102)]
                self.remote.overrides['repos/example/project/actions/runs/122/artifacts?per_page=100&page=2'] = last
                self.assertEqual(self.prune()['status'], 'refused')
                self.assert_read_only()
        for field in ('workflow_runs', 'artifacts'):
            with self.subTest(field=field):
                self.setUp()
                endpoint = ('repos/example/project/actions/workflows/7/runs?status=success&per_page=100&page=1'
                            if field == 'workflow_runs' else 'repos/example/project/actions/runs/122/artifacts?per_page=100&page=1')
                self.remote.overrides[endpoint] = dict(total_count=1001, **{field: []})
                self.assertEqual(self.prune()['status'], 'refused')
                self.assert_read_only()

    def test_unrelated_artifact_identity_and_invalid_size_are_refused(self):
        for field, value in (('id', 123), ('repository_id', 99), ('head_repository_id', 99), ('head_sha', 'c' * 40)):
            with self.subTest(field=field):
                self.setUp()
                self.remote.artifacts[122][0]['workflow_run'][field] = value
                self.assertEqual(self.prune()['status'], 'refused')
                self.assert_read_only()
        for size in (-1, True):
            with self.subTest(size=size):
                self.setUp()
                self.remote.artifacts[122][0]['size_in_bytes'] = size
                self.assertEqual(self.prune()['status'], 'refused')
                self.assert_read_only()

    def test_every_active_status_aborts_and_exact_cleanup_run_is_allowed(self):
        for status in cleanup.repository_cleanup.ACTIVE_STATUSES:
            with self.subTest(status=status):
                self.setUp()
                self.remote.active[status] = [dict(id=124, status=status)]
                self.assertEqual(self.prune()['status'], 'refused')
                self.assert_read_only()
        self.setUp()
        self.remote.active['in_progress'] = [dict(id=900, status='in_progress')]
        self.assertEqual(self.prune()['status'], 'complete')

    def test_restarted_or_changed_run_aborts_at_final_identity_barrier(self):
        saved = self.remote.json
        def changing(endpoint, **kwargs):
            if '/actions/runs?status=' in endpoint:
                self.remote.previous['run_attempt'] = 2
            return saved(endpoint, **kwargs)
        self.remote.json = changing
        self.assertEqual(self.prune()['status'], 'refused')
        self.assert_read_only()

    def test_foreign_workflow_history_duplicate_number_and_changed_current_are_refused(self):
        for field, value in (('workflow_id', 8), ('path', '.github/workflows/certify.yml'), ('run_number', 10)):
            with self.subTest(field=field):
                self.setUp()
                self.remote.previous[field] = value
                self.assertEqual(self.prune()['status'], 'refused')
                self.assert_read_only()
        self.setUp()
        self.remote.history[0] = dict(self.remote.current, head_sha='c' * 40)
        self.assertEqual(self.prune()['status'], 'refused')
        self.assert_read_only()

    def test_malformed_jobs_incomplete_terminal_and_nested_marker_do_not_qualify(self):
        for case in ('wrong-source', 'in-progress', 'duplicate-terminal', 'nested', 'bad-steps'):
            with self.subTest(case=case):
                self.setUp()
                rows = self.remote.jobs[123]
                if case == 'wrong-source': rows[0]['head_sha'] = 'c' * 40
                elif case == 'in-progress': rows[0]['status'] = 'in_progress'
                elif case == 'duplicate-terminal': rows.append(dict(rows[0], id=1231))
                elif case == 'nested': rows[0]['name'] = 'regression / verdict'
                else: rows[0]['steps'] = None
                self.assertIn(self.prune()['status'], ('refused', 'skipped'))
                self.assert_read_only()

    def test_candidate_search_is_finite_and_does_not_select_older_unknown_marker(self):
        self.remote.history = [self.remote.current] + [run(100 - index, 9 - index) for index in range(21)]
        # Positive run numbers are mandatory; use a larger source run number.
        self.remote.current['run_number'] = 100
        self.event['workflow_run']['run_number'] = 100
        for index, value in enumerate(self.remote.history[1:]):
            value['run_number'] = 99 - index
            self.remote.jobs[value['id']] = [job(2000 + index, value, marker=None)]
        result = self.prune()
        self.assertEqual(result['status'], 'refused')
        self.assertIn('20 candidates', result['error'])
        self.assert_read_only()

    def test_delete_error_is_never_replayed_or_counted_confirmed(self):
        self.remote.fail_delete = 2
        result = self.prune()
        self.assertEqual(result['status'], 'failed')
        self.assertEqual((result['deleted_count'], result['deleted_bytes']), (1, 10))
        self.assertEqual(result['unconfirmed_artifact_id'], 2)
        self.assertEqual(sum(method == 'DELETE' for method, _ in self.remote.calls), 2)

    def test_quota_exhaustion_on_inventory_or_delete_never_waits_or_retries(self):
        for phase in ('inventory', 'delete'):
            with self.subTest(phase=phase):
                self.setUp()
                saved = self.remote.json
                def limited(endpoint, *, method='GET'):
                    if ((phase == 'inventory' and '/artifacts?' in endpoint) or
                            (phase == 'delete' and method == 'DELETE')):
                        self.remote.calls.append((method, endpoint))
                        raise ValueError('GitHub HTTP 403: API rate limit exceeded')
                    return saved(endpoint, method=method)
                self.remote.json = limited
                result = self.prune()
                self.assertEqual(result['status'], 'refused' if phase == 'inventory' else 'failed')
                self.assertEqual(result['deleted_count'], 0)
                self.assertEqual(sum(method == 'DELETE' for method, _ in self.remote.calls), int(phase == 'delete'))
                self.assertIn('rate limit', result['error'])
                self.assertFalse(self.sleeps)

    def test_native_transport_has_finite_quota_timeout_and_retry_settings(self):
        with mock.patch.object(cleanup.delivery, 'GitHub', return_value=self.remote):
            result = cleanup.prune(environment=self.environment, event=self.event, sleep=self.sleeps.append)
        self.assertEqual(result['status'], 'complete')
        for name, expected in [('WRITE_HEADROOM', 0), ('REQUEST_DEADLINE', 30), ('COMMAND_TIMEOUT', 30),
                               ('WAIT_BUDGET', 0), ('wait_remaining', 0.0), ('MAX_ATTEMPTS', 1)]:
            self.assertEqual(getattr(self.remote, name), expected)

    def test_deadline_stops_starting_deletes_and_preserves_unconfirmed_ids(self):
        def clock():
            return cleanup.MAX_SECONDS if any(method == 'DELETE' for method, _ in self.remote.calls) else 0
        result = self.prune(clock=clock)
        self.assertEqual(result['status'], 'failed')
        self.assertEqual(result['deleted_count'], 1)
        self.assertIsNone(result['unconfirmed_artifact_id'])
        self.assertIn('budget', result['error'])

    def test_global_deadline_also_stops_inventory_reads(self):
        def clock():
            return cleanup.MAX_SECONDS if self.remote.calls else 0
        result = self.prune(clock=clock)
        self.assertEqual(result['status'], 'refused')
        self.assertEqual(len(self.remote.calls), 1)
        self.assertEqual(result['deleted_count'], 0)
        self.assertIn('budget', result['error'])
        self.assert_read_only()

    def test_drafts_receive_only_qualified_contexts_after_final_artifact_consumer(self):
        drafts = mock.Mock(return_value=dict(deleted_drafts=2))
        result = self.prune(draft_cleanup=drafts)
        self.assertEqual(result['drafts'], dict(deleted_drafts=2))
        current, previous = drafts.call_args.args
        self.assertEqual((current['run_id'], previous['run_id']), (123, 122))
        self.assertEqual(drafts.call_args.kwargs['cleanup_run_id'], 900)
        self.assertEqual(result['status'], 'complete')
        self.assertEqual(self.remote.calls[-2:], [('GET', 'repos/example/project/actions/runs/123'),
                                                ('GET', 'repos/example/project/actions/runs/122')])

    def test_cli_opens_summary_before_deletion_and_reports_json(self):
        with tempfile.TemporaryDirectory() as temporary:
            event_path = Path(temporary) / 'event.json'
            summary_path = Path(temporary) / 'summary.md'
            event_path.write_text(json.dumps(self.event))
            environment = dict(self.environment, GITHUB_EVENT_PATH=str(event_path), GITHUB_STEP_SUMMARY=str(summary_path))
            saved = cleanup.prune
            with mock.patch.dict(os.environ, environment, clear=True), mock.patch('sys.stdout', new_callable=io.StringIO) as output, \
                    mock.patch.object(cleanup.ci_cleanup_drafts, 'cleanup_drafts', return_value=dict(deleted_drafts=0)), \
                    mock.patch.object(cleanup, 'prune', side_effect=lambda **kwargs: saved(environment=environment,
                        transport=self.remote, sleep=self.sleeps.append, **kwargs)):
                self.assertEqual(cleanup.main([]), 0)
            self.assertEqual(json.loads(output.getvalue())['deleted_count'], 2)
            self.assertIn('Selected preceding full run: 122', summary_path.read_text())

    def test_workflow_wiring_marks_only_full_nonpreserved_terminal_paths(self):
        root = Path(__file__).resolve().parents[1]
        # These maintained workflows use fixed indentation. Bound each assertion
        # to its actual section/job/step; actionlint separately checks YAML syntax.
        # Portable unit suites require only the standard library, including on
        # retained SDKs and native Windows hosts without optional Python packages.
        def section(text, header):
            self.assertEqual(len(re.findall('(?m)^' + re.escape(header) + '$', text)), 1)
            return re.search('(?ms)^' + re.escape(header) + r'\n(.*?)(?=^\S|\Z)', text).group(1)

        def job_block(text, identity):
            jobs = section(text, 'jobs:')
            header = '  ' + identity + ':'
            self.assertEqual(len(re.findall('(?m)^' + re.escape(header) + '$', jobs)), 1)
            return re.search('(?ms)^' + re.escape(header) + r'\n(.*?)(?=^  \S|\Z)', jobs).group(1)

        workflow = (root / '.github/workflows/cleanup-previous-run.yml').read_text()
        trigger = section(workflow, "'on':")
        self.assertIn('  workflow_run:\n    workflows:\n', trigger)
        source_list = re.search(r'^    workflows:\n((?:    - [^\n]+\n)+)', trigger, re.M).group(1)
        sources = re.findall(r'^    - (.+)$', source_list, re.M)
        permissions = re.findall(r'^  (\w+): (.+)$', section(workflow, 'permissions:'), re.M)
        self.assertEqual(len(permissions), 2)
        self.assertEqual(dict(permissions), dict(contents='write', actions='write'))
        cleanup_job = job_block(workflow, 'cleanup')
        self.assertEqual(cleanup_job.count('    steps:\n'), 1)
        steps = cleanup_job.split('    steps:\n', 1)[1]
        first_step = steps.split('\n    - ', 1)[0]
        self.assertTrue(first_step.startswith('    - uses: actions/checkout@'))
        checkout_settings = re.findall(r'(?ms)^      with:\n(.*?)(?=^      \S|\Z)', first_step)
        self.assertEqual(len(checkout_settings), 1)
        self.assertEqual(re.findall(r'^        ref: (.+)$', checkout_settings[0], re.M),
                         ['${{ github.event.repository.default_branch }}'])
        terminal_jobs = {'candidate.yml': 'verdict', '_release-latest.yml': 'final',
                         'certify.yml': 'verdict', 'sdk-application.yml': 'assemble'}
        self.assertEqual(set(terminal_jobs), set(cleanup.WORKFLOWS))
        for source, identity in terminal_jobs.items():
            with self.subTest(workflow=source):
                text = (root / '.github/workflows' / source).read_text()
                self.assertEqual(len(re.findall(r'^name: (.+)$', text, re.M)), 1)
                self.assertIn(re.search(r'^name: (.+)$', text, re.M).group(1), sources)
                self.assertEqual(text.count('name: ' + cleanup.MARKER), 1)
                terminal = job_block(text, identity)
                job_names = re.findall(r'^    name: (.+)$', terminal, re.M)
                self.assertLessEqual(len(job_names), 1)
                self.assertEqual(job_names[0] if job_names else identity, cleanup.WORKFLOWS[source])
                marker = '    - name: ' + cleanup.MARKER + '\n'
                marker_matches = list(re.finditer('(?m)^' + re.escape(marker), terminal))
                self.assertEqual(len(marker_matches), 1)
                marker_step = terminal[marker_matches[0].end():].split('\n    - ', 1)[0]
                condition = 'success() && inputs.execute && !inputs.preserve_artifacts'
                if source == 'candidate.yml':
                    condition = 'success() && !inputs.devfast && inputs.include_arm && !inputs.preserve_artifacts'
                elif source == 'sdk-application.yml':
                    condition = 'success() && inputs.execute && inputs.require_regression && !inputs.preserve_artifacts'
                self.assertEqual(re.findall(r'^      if: (.+)$', marker_step, re.M), [condition])


if __name__ == '__main__':
    unittest.main()
