"""Expired auxiliary drafts retire without touching SDK recovery or Actions evidence."""
import copy
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
sys.path.insert(0, str(Path(__file__).parent))
import ci_cleanup_expired as cleanup
from test_ci_cleanup_drafts import Transport as DraftTransport, context as draft_context

NOW = int(datetime(2026, 10, 5, tzinfo=timezone.utc).timestamp())
OLD = '2026-10-03T00:00:00Z'
RECENT = '2026-10-04T23:59:00Z'
PUBLICATION = ('screenshots.yml', 'gui-inputs.yml', 'distribution.yml')


def context(identity=42, workflow='host-contracts.yml', attempt=1):
    return dict(draft_context(identity, workflow), attempt=attempt)


def bundle_name(selected):
    attempt = selected['attempt']
    return {
        'host-contracts.yml': f'host-contracts-{attempt}',
        'native-gui.yml': f'native-gui-evidence-linux-aarch64-{attempt}',
        'rev-probe.yml': f'rev-probe-linux-aarch64-{attempt}-diagnostics',
        'distro-check.yml': f'distro-apt-ubuntu-{attempt}',
        'screenshots.yml': 'screenshots',
        'gui-inputs.yml': f'gui-inputs-{attempt}',
        'distribution.yml': f'distribution-{attempt}',
    }.get(selected['workflow'], f'sdk-group-linux-x86_64-{attempt}')


class Transport(DraftTransport):
    """Reuse exact draft transport fixtures and add attempt-specific Actions reads."""
    def __init__(self, contexts):
        super().__init__(contexts)
        self.runs, self.jobs = {}, {}
        self.after_run_read = None
        for identity, selected in enumerate(contexts, 100):
            self.releases[identity - 100].update(created_at=OLD, updated_at=OLD)
            self.assets[identity] = self.bundle_assets(bundle_name(selected), identity)
            repository = dict(id=selected['repository_id'], full_name=selected['repository'])
            key = (selected['run_id'], selected['attempt'])
            self.runs[key] = dict(id=selected['run_id'], workflow_id=selected['workflow_id'],
                run_number=selected['run_number'], run_attempt=selected['attempt'],
                path='.github/workflows/' + selected['workflow'], event='workflow_dispatch',
                status='completed', conclusion='success', head_sha=selected['source_commit'],
                repository=repository, head_repository=copy.deepcopy(repository), updated_at=OLD)
            names = ['prepare', 'publish'] if selected['workflow'] in PUBLICATION else ['diagnostic']
            self.jobs[key] = [dict(id=selected['run_id'] * 10 + index,
                run_id=selected['run_id'], run_attempt=selected['attempt'],
                head_sha=selected['source_commit'], name=name, status='completed', conclusion='success')
                for index, name in enumerate(names, 1)]

    def json(self, endpoint, *, method='GET', missing=False):
        match = re.search(r'/actions/runs/([0-9]+)/attempts/([0-9]+)(/jobs\?.*)?$', endpoint)
        if method == 'GET' and match:
            self.calls.append((method, endpoint))
            key = (int(match[1]), int(match[2]))
            if key not in self.runs:
                raise ValueError('unknown exact attempt fixture')
            if match[3]:
                rows = copy.deepcopy(self.jobs[key])
                page = int(re.search(r'(?:[?&])page=([0-9]+)', endpoint)[1])
                return dict(total_count=len(rows), jobs=rows[(page - 1) * 100:page * 100])
            value = copy.deepcopy(self.runs[key])
            if self.after_run_read:
                self.after_run_read(self, key)
            return value
        return super().json(endpoint, method=method, missing=missing)


class ExpiredCleanupTests(unittest.TestCase):
    def setUp(self):
        self.environment = dict(GITHUB_ACTIONS='true', GITHUB_SERVER_URL='https://github.com',
            GITHUB_REPOSITORY='example/project', GITHUB_REPOSITORY_ID='7', GITHUB_RUN_ID='900',
            GITHUB_RUN_ATTEMPT='1', GITHUB_SHA='b' * 40, GITHUB_EVENT_NAME='schedule',
            GITHUB_WORKFLOW_REF='example/project/.github/workflows/cleanup-previous-run.yml@refs/heads/main')
        self.sleeps = []

    def sweep(self, remote, **kwargs):
        return cleanup.sweep(environment=self.environment, transport=remote,
            sleep=self.sleeps.append, now=NOW, **kwargs)

    def deletions(self, remote):
        return [endpoint for method, endpoint in remote.calls if method == 'DELETE']

    def assert_no_deletions(self, remote):
        self.assertFalse(self.deletions(remote))

    def test_old_diagnostic_stores_retire_after_every_terminal_outcome(self):
        for workflow in ('host-contracts.yml', 'native-gui.yml', 'rev-probe.yml', 'distro-check.yml'):
            for outcome in ('success', 'failure', 'cancelled', 'timed_out'):
                with self.subTest(workflow=workflow, outcome=outcome):
                    remote = Transport([context(workflow=workflow)])
                    remote.runs[(42, 1)]['conclusion'] = outcome
                    remote.jobs[(42, 1)][0]['conclusion'] = outcome
                    result = self.sweep(remote)
                    self.assertEqual(result['status'], 'complete')
                    self.assertEqual((result['selected_drafts'], result['deleted_drafts'], result['deleted_tags']), (1, 1, 1))
                    self.assertEqual(self.deletions(remote), ['repos/example/project/releases/100',
                        'repos/example/project/git/refs/tags/ci-42-attempt-1'])

    def test_published_auxiliary_inputs_retire_only_after_successful_publisher(self):
        for workflow in PUBLICATION:
            with self.subTest(workflow=workflow):
                remote = Transport([context(workflow=workflow)])
                result = self.sweep(remote)
                self.assertEqual(result['status'], 'complete')
                self.assertEqual((result['deleted_drafts'], result['deleted_tags']), (1, 1))
                self.assertFalse(remote.releases)

    def test_unpublished_inputs_survive_missing_skipped_failed_or_duplicate_publisher(self):
        for workflow in PUBLICATION:
            for outcome in ('missing', 'skipped', 'failure', 'duplicate'):
                with self.subTest(workflow=workflow, outcome=outcome):
                    remote = Transport([context(workflow=workflow)])
                    if outcome == 'missing': remote.jobs[(42, 1)].pop()
                    elif outcome == 'duplicate':
                        remote.jobs[(42, 1)].append(dict(remote.jobs[(42, 1)][1], id=429))
                    else: remote.jobs[(42, 1)][1]['conclusion'] = outcome
                    self.sweep(remote)
                    self.assert_no_deletions(remote)
                    self.assertEqual(len(remote.releases), 1)
                    self.assertIn('ci-42-attempt-1', remote.refs)

    def test_recent_draft_or_attempt_is_preserved(self):
        for field in ('draft', 'run'):
            with self.subTest(field=field):
                remote = Transport([context()])
                row = remote.releases[0] if field == 'draft' else remote.runs[(42, 1)]
                row['updated_at'] = RECENT
                self.sweep(remote)
                self.assert_no_deletions(remote)
                self.assertEqual(len(remote.releases), 1)

    def test_old_attempt_selection_never_borrows_the_latest_attempt(self):
        remote = Transport([context(attempt=2)])
        remote.runs[(42, 3)] = dict(remote.runs[(42, 2)], run_attempt=3, status='in_progress', conclusion=None)
        remote.jobs[(42, 3)] = []
        result = self.sweep(remote)
        self.assertEqual(result['deleted_drafts'], 1)
        reads = [endpoint for method, endpoint in remote.calls if method == 'GET' and '/actions/runs/42/' in endpoint]
        self.assertTrue(any(endpoint.endswith('/attempts/2') for endpoint in reads))
        self.assertTrue(any('/attempts/2/jobs?' in endpoint for endpoint in reads))
        self.assertFalse(any('/attempts/3' in endpoint for endpoint in reads))
        self.assertNotIn(('GET', 'repos/example/project/actions/runs/42'), remote.calls)

    def test_run_identity_mismatches_fail_closed(self):
        changes = [('id', 43), ('run_attempt', 2), ('head_sha', 'c' * 40),
                   ('path', '.github/workflows/sdk-maintenance.yml'), ('event', 'pull_request')]
        for field, value in changes:
            with self.subTest(field=field):
                remote = Transport([context()]); remote.runs[(42, 1)][field] = value
                self.assertEqual(self.sweep(remote)['status'], 'refused')
                self.assert_no_deletions(remote)
        for field in ('repository', 'head_repository'):
            for key, value in (('id', 8), ('full_name', 'foreign/project')):
                with self.subTest(field=field, key=key):
                    remote = Transport([context()]); remote.runs[(42, 1)][field][key] = value
                    self.assertEqual(self.sweep(remote)['status'], 'refused')
                    self.assert_no_deletions(remote)

    def test_release_body_identity_mismatches_fail_closed(self):
        for field, value in (('repository', 'foreign/project'), ('repository_id', 8),
                ('run_id', 43), ('attempt', 2), ('source_commit', 'c' * 40),
                ('workflow', 'native-gui.yml')):
            with self.subTest(field=field):
                remote = Transport([context()])
                body = json.loads(remote.releases[0]['body']); body[field] = value
                remote.releases[0]['body'] = json.dumps(body)
                self.sweep(remote)
                self.assert_no_deletions(remote)
                self.assertEqual(len(remote.releases), 1)

    def test_incomplete_active_or_mismatched_jobs_preserve_drafts(self):
        for case in ('empty', 'active', 'wrong-run', 'wrong-source', 'duplicate'):
            with self.subTest(case=case):
                remote = Transport([context()]); jobs = remote.jobs[(42, 1)]
                if case == 'empty': jobs.clear()
                elif case == 'active': jobs[0].update(status='in_progress', conclusion=None)
                elif case == 'wrong-run': jobs[0]['run_id'] = 43
                elif case == 'wrong-source': jobs[0]['head_sha'] = 'c' * 40
                else: jobs.append(copy.deepcopy(jobs[0]))
                self.sweep(remote)
                self.assert_no_deletions(remote)

    def test_nonterminal_attempt_is_preserved(self):
        remote = Transport([context()]); remote.runs[(42, 1)].update(status='in_progress', conclusion=None)
        self.sweep(remote)
        self.assert_no_deletions(remote)

    def test_invalid_schedule_context_refuses_before_requests(self):
        for field, value in (('GITHUB_EVENT_NAME', 'workflow_run'),
                ('GITHUB_WORKFLOW_REF', 'example/project/.github/workflows/sdk-maintenance.yml@refs/heads/main'),
                ('GITHUB_SERVER_URL', 'https://foreign.example'), ('GITHUB_ACTIONS', 'false')):
            with self.subTest(field=field):
                self.setUp(); self.environment[field] = value
                remote = Transport([context()])
                self.assertEqual(self.sweep(remote)['status'], 'refused')
                self.assertFalse(remote.calls)

    def test_manual_default_or_false_preserves_recent_drafts_and_attempts(self):
        for immediate in (None, 'false'):
            with self.subTest(immediate=immediate):
                self.setUp(); self.environment['GITHUB_EVENT_NAME'] = 'workflow_dispatch'
                if immediate is not None: self.environment['CLEANUP_EXPIRE_NOW'] = immediate
                remote = Transport([context()])
                remote.releases[0]['updated_at'] = remote.runs[(42, 1)]['updated_at'] = RECENT
                self.assertEqual(self.sweep(remote)['status'], 'skipped')
                self.assert_no_deletions(remote)
                self.assertEqual(len(remote.releases), 1)

    def test_explicit_manual_true_retires_recent_terminal_diagnostics(self):
        self.environment.update(GITHUB_EVENT_NAME='workflow_dispatch', CLEANUP_EXPIRE_NOW='true')
        remote = Transport([context()])
        remote.releases[0]['updated_at'] = remote.runs[(42, 1)]['updated_at'] = RECENT
        result = self.sweep(remote)
        self.assertEqual(result['status'], 'complete')
        self.assertEqual((result['selected_drafts'], result['deleted_drafts'], result['deleted_tags']), (1, 1, 1))
        self.assertEqual(self.deletions(remote), ['repos/example/project/releases/100',
            'repos/example/project/git/refs/tags/ci-42-attempt-1'])

    def test_manual_true_preserves_unpublished_inputs_sdk_and_unknown_payloads(self):
        self.environment.update(GITHUB_EVENT_NAME='workflow_dispatch', CLEANUP_EXPIRE_NOW='true')
        for workflow in (*PUBLICATION, 'sdk-maintenance.yml', 'sdk-import.yml', 'host-contracts.yml'):
            with self.subTest(workflow=workflow):
                remote = Transport([context(workflow=workflow)])
                remote.releases[0]['updated_at'] = remote.runs[(42, 1)]['updated_at'] = RECENT
                if workflow in PUBLICATION:
                    remote.jobs[(42, 1)][1]['conclusion'] = 'failure'
                elif workflow == 'host-contracts.yml':
                    remote.assets[100] += remote.bundle_assets('unrecognized', 999)
                self.sweep(remote)
                self.assert_no_deletions(remote)
                self.assertEqual(len(remote.releases), 1)
                self.assertIn('ci-42-attempt-1', remote.refs)

    def test_manual_true_still_blocks_active_consumers_and_producers(self):
        self.environment.update(GITHUB_EVENT_NAME='workflow_dispatch', CLEANUP_EXPIRE_NOW='true')
        for status in cleanup.repository_cleanup.ACTIVE_STATUSES:
            with self.subTest(status=status):
                remote = Transport([context()])
                remote.releases[0]['updated_at'] = remote.runs[(42, 1)]['updated_at'] = RECENT
                remote.active[status] = [dict(id=77, status=status)]
                self.assertEqual(self.sweep(remote)['status'], 'skipped')
                self.assert_no_deletions(remote)
        remote = Transport([context()]); remote.runs[(42, 1)].update(status='in_progress', conclusion=None)
        self.assertEqual(self.sweep(remote)['status'], 'skipped')
        self.assert_no_deletions(remote)

    def test_immediate_override_requires_manual_event_and_literal_boolean_input(self):
        for event, immediate in [('schedule', 'true')] + [
                (event, value) for event in ('schedule', 'workflow_dispatch')
                for value in ('', 'True', 'FALSE', '1', True, None)]:
            with self.subTest(event=event, immediate=immediate):
                self.environment.update(GITHUB_EVENT_NAME=event, CLEANUP_EXPIRE_NOW=immediate)
                remote = Transport([context()])
                self.assertEqual(self.sweep(remote)['status'], 'refused')
                self.assertFalse(remote.calls)

    def test_every_active_consumer_blocks_mutation_and_cleanup_itself_is_allowed(self):
        for status in cleanup.repository_cleanup.ACTIVE_STATUSES:
            with self.subTest(status=status):
                remote = Transport([context()]); remote.active[status] = [dict(id=77, status=status)]
                self.sweep(remote)
                self.assert_no_deletions(remote)
        remote = Transport([context()]); remote.active['in_progress'] = [dict(id=900, status='in_progress')]
        self.assertEqual(self.sweep(remote)['deleted_drafts'], 1)

    def test_consumer_starting_after_selection_prevents_release_deletion(self):
        remote = Transport([context()])
        remote.after_assets = lambda wire: wire.active.update(queued=[dict(id=77, status='queued')])
        self.sweep(remote)
        self.assert_no_deletions(remote)
        self.assertEqual(len(remote.releases), 1)

    def test_changed_attempt_after_selection_prevents_release_deletion(self):
        remote = Transport([context()])
        remote.after_assets = lambda wire: wire.runs[(42, 1)].update(head_sha='c' * 40)
        self.sweep(remote)
        self.assert_no_deletions(remote)

    def test_draft_update_or_active_producer_after_selection_prevents_deletion(self):
        for change in ('draft-time', 'producer-state', 'producer-time'):
            with self.subTest(change=change):
                remote = Transport([context()])
                def changed(wire):
                    if change == 'draft-time': wire.releases[0]['updated_at'] = RECENT
                    elif change == 'producer-time': wire.runs[(42, 1)]['updated_at'] = RECENT
                    else: wire.runs[(42, 1)].update(status='in_progress', conclusion=None)
                remote.after_assets = changed
                self.assertEqual(self.sweep(remote)['status'], 'failed')
                self.assert_no_deletions(remote)
                self.assertEqual(len(remote.releases), 1)

    def test_sdk_recovery_and_unknown_workflows_are_preserved_despite_numeric_tags(self):
        for workflow in ('sdk-maintenance.yml', 'sdk-import.yml', 'rust-qualification.yml',
                'legacy-artifacts.yml', 'verify-retention.yml', 'unrecognized.yml'):
            with self.subTest(workflow=workflow):
                remote = Transport([context(workflow=workflow)])
                self.sweep(remote)
                self.assert_no_deletions(remote)
                self.assertEqual(len(remote.releases), 1)

    def test_mixed_retained_unknown_or_incomplete_assets_preserve_entire_store(self):
        for name in ('sdk-group-linux-x86_64-1', 'rust-sdk-group-linux-x86_64-1',
                     'legacy-preservation', 'unrecognized'):
            with self.subTest(name=name):
                remote = Transport([context()]); remote.assets[100] += remote.bundle_assets(name, 999)
                self.sweep(remote)
                self.assert_no_deletions(remote)
                self.assertEqual(len(remote.releases), 1)
        remote = Transport([context()]); remote.assets[100].pop()
        self.sweep(remote)
        self.assert_no_deletions(remote)

    def test_public_latest_base_and_nonnumeric_ci_tools_are_never_selected(self):
        remote = Transport([context(42), context(43), context(44), context(45), context(46)])
        remote.releases[1].update(draft=False, prerelease=False)
        remote.releases[2].update(tag_name='base', name='base')
        remote.releases[3].update(tag_name='release-current', name='Latest', draft=False, prerelease=False)
        remote.releases[4].update(tag_name='ci-tools-46-attempt-1', name='ci-tools-46-attempt-1')
        self.assertEqual(self.sweep(remote)['deleted_drafts'], 1)
        self.assertEqual([row['id'] for row in remote.releases], [101, 102, 103, 104])
        self.assertEqual(self.deletions(remote), ['repos/example/project/releases/100',
            'repos/example/project/git/refs/tags/ci-42-attempt-1'])

    def test_uncertain_deletion_is_never_replayed_or_followed_by_later_store_deletion(self):
        for endpoint in ('repos/example/project/releases/100',
                         'repos/example/project/git/refs/tags/ci-42-attempt-1'):
            with self.subTest(endpoint=endpoint):
                remote = Transport([context(42), context(43)]); remote.fail_delete = endpoint
                result = self.sweep(remote)
                self.assertEqual(result['status'], 'failed')
                self.assertEqual(self.deletions(remote).count(endpoint), 1)
                self.assertTrue(any(row['id'] == 101 for row in remote.releases))
                self.assertNotIn('repos/example/project/git/refs/tags/ci-43-attempt-1', self.deletions(remote))
                if '/releases/' in endpoint: self.assertIn('ci-42-attempt-1', remote.refs)

    def test_mismatched_second_store_prevents_first_store_deletion(self):
        remote = Transport([context(42), context(43)])
        remote.runs[(43, 1)]['head_sha'] = 'c' * 40
        self.assertEqual(self.sweep(remote)['status'], 'refused')
        self.assert_no_deletions(remote)

    def test_store_limit_retires_twenty_and_preserves_remaining_backlog(self):
        remote = Transport([context(42 + index) for index in reversed(range(cleanup.MAX_STORES + 1))])
        result = self.sweep(remote)
        self.assertEqual(result['status'], 'complete')
        self.assertEqual((result['selected_drafts'], result['deleted_drafts'], result['deleted_tags']), (20, 20, 20))
        self.assertEqual([row['tag_name'] for row in remote.releases], ['ci-62-attempt-1'])
        self.assertIn('ci-62-attempt-1', remote.refs)

    def test_retained_stores_do_not_starve_a_later_expired_diagnostic(self):
        remote = Transport([context(42 + index) for index in range(cleanup.MAX_STORES + 1)])
        for index in range(cleanup.MAX_STORES):
            name = 'sdk-group-linux-x86_64-1' if index % 2 else 'unrecognized'
            remote.assets[100 + index] += remote.bundle_assets(name, 1000 + index)
        result = self.sweep(remote)
        self.assertEqual(result['status'], 'complete')
        self.assertEqual((result['selected_drafts'], result['deleted_drafts'], result['deleted_tags']), (1, 1, 1))
        self.assertEqual([row['id'] for row in remote.releases], list(range(100, 120)))
        self.assertEqual(self.deletions(remote), ['repos/example/project/releases/120',
            'repos/example/project/git/refs/tags/ci-62-attempt-1'])
        self.assertEqual(set(remote.refs), {f'ci-{identity}-attempt-1' for identity in range(42, 62)})

    def test_null_nonstring_or_malformed_release_bodies_are_preserved(self):
        for body in (None, {}, [], True, 42, 'not-json'):
            with self.subTest(body=body):
                remote = Transport([context()]); remote.releases[0]['body'] = body
                self.assertEqual(self.sweep(remote)['status'], 'skipped')
                self.assert_no_deletions(remote)
                self.assertEqual(len(remote.releases), 1)
                self.assertIn('ci-42-attempt-1', remote.refs)

    def test_auxiliary_cleanup_never_deletes_actions_artifacts_or_workflow_runs(self):
        remote = Transport([context()])
        self.assertEqual(self.sweep(remote)['deleted_drafts'], 1)
        self.assertFalse(any('/actions/' in endpoint for endpoint in self.deletions(remote)))
        self.assertTrue(all('/releases/' in endpoint or '/git/refs/tags/' in endpoint
                            for endpoint in self.deletions(remote)))

    def test_daily_and_manual_workflow_keep_auxiliary_expiry_separate_from_full_run_pruning(self):
        workflow = (Path(__file__).resolve().parents[1] /
                    '.github/workflows/cleanup-previous-run.yml').read_text()
        trigger = re.search(r"(?ms)^'on':\n(.*?)(?=^\S|\Z)", workflow).group(1)
        self.assertEqual(trigger.count('  schedule:\n'), 1)
        crons = re.findall(r"^  - cron: '([^']+)'$", trigger, re.M)
        self.assertEqual(len(crons), 1)
        self.assertRegex(crons[0], r'^[0-9]+ [0-9]+ \* \* \*$')
        self.assertEqual(re.findall(r'^    - (.+)$', trigger, re.M), [
            'Candidate checks', '_Publish new Latest release',
            'Certify exact published candidate', 'Prepared SDK application and candidate'])
        dispatch = re.search(r'(?ms)^  workflow_dispatch:\n(.*?)(?=^  \S|\Z)', trigger).group(1)
        self.assertEqual(dispatch.count('    inputs:\n'), 1)
        self.assertEqual(dispatch.count('      expire_now:\n'), 1)
        immediate = re.search(r'(?ms)^      expire_now:\n(.*?)(?=^      \S|\Z)', dispatch).group(1)
        self.assertEqual(re.findall(r'^        type: (.+)$', immediate, re.M), ['boolean'])
        self.assertEqual(re.findall(r'^        default: (.+)$', immediate, re.M), ['false'])
        steps = workflow.split('    steps:\n', 1)[1].split('\n    - ')
        commands = {}
        for step in steps:
            command = re.search(r'^      run: (.+)$', step, re.M)
            if command:
                self.assertNotIn(command[1], commands)
                commands[command[1]] = re.findall(r'^      if: (.+)$', step, re.M)
        self.assertEqual(commands, {
            'python3 -B tools/ci_cleanup_previous.py': ["github.event_name == 'workflow_run'"],
            'python3 -B tools/ci_cleanup_expired.py': ["github.event_name != 'workflow_run'"],
        })
        self.assertEqual(re.findall(r'^        CLEANUP_EXPIRE_NOW: (.+)$', workflow, re.M),
            ["${{ github.event_name == 'workflow_dispatch' && inputs.expire_now || false }}"])


if __name__ == '__main__':
    unittest.main()
