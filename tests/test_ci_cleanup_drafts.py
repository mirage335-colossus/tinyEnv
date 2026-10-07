"""Only exact qualified temporary draft stores are retired; no network is used."""
import copy
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import ci_cleanup_drafts as cleanup


def context(run_id=42, workflow='candidate.yml'):
    return dict(repository='example/project', repository_id=7, run_id=run_id,
                attempt=1, source_commit='a' * 40, workflow=workflow,
                workflow_id=9, run_number=run_id)


class Transport:
    def __init__(self, contexts):
        self.calls = []
        self.releases, self.assets, self.refs = [], {}, {}
        self.active = {}
        self.fail_delete = None
        self.after_release_delete = None
        self.after_assets = None
        for identity, selected in enumerate(contexts, 100):
            tag = cleanup.bundles._tag(selected)
            body = {key: selected[key] for key in
                    ('repository', 'run_id', 'attempt', 'source_commit', 'workflow')}
            body.update(schema_version=1, kind='private-ci-transport', repository_id=7)
            self.releases.append(dict(id=identity, tag_name=tag, name=tag, draft=True,
                prerelease=True, target_commitish=selected['source_commit'],
                body=cleanup.bundles.archive.encoded(body).decode()))
            self.refs[tag] = selected['source_commit']
            self.assets[identity] = self.bundle_assets('candidate-1', identity)

    @staticmethod
    def bundle_assets(name, identity):
        return [dict(id=identity * 10, name=cleanup.bundles._manifest_name(name),
                     size=100, state='uploaded', digest='sha256:' + 'b' * 64),
                dict(id=identity * 10 + 1, name=cleanup.bundles._prefix(name) + '0000-' + 'c' * 64,
                     size=200, state='uploaded', digest='sha256:' + 'c' * 64)]

    def pages(self, endpoint):
        self.calls.append(('GET', endpoint))
        if endpoint.endswith('/releases?per_page=100'):
            return copy.deepcopy(self.releases)
        identity = int(endpoint.split('/releases/')[1].split('/')[0])
        value = copy.deepcopy(self.assets[identity])
        if self.after_assets:
            callback, self.after_assets = self.after_assets, None
            callback(self)
        return value

    def json(self, endpoint, *, method='GET', missing=False):
        self.calls.append((method, endpoint))
        if method == 'DELETE':
            if endpoint == self.fail_delete:
                raise ValueError('unconfirmed remote deletion')
            if '/releases/' in endpoint:
                identity = int(endpoint.rsplit('/', 1)[1])
                self.releases = [row for row in self.releases if row['id'] != identity]
                if self.after_release_delete: self.after_release_delete(self)
            else:
                del self.refs[endpoint.split('/tags/', 1)[1]]
            return None
        if '/actions/runs?' in endpoint:
            status = endpoint.split('status=', 1)[1].split('&', 1)[0]
            rows = self.active.get(status, [])
            return dict(total_count=len(rows), workflow_runs=copy.deepcopy(rows[:2]))
        if '/git/ref/tags/' in endpoint:
            tag = endpoint.split('/tags/', 1)[1]
            return dict(object=dict(type='commit', sha=self.refs[tag]))
        identity = int(endpoint.rsplit('/', 1)[1])
        return copy.deepcopy(next(row for row in self.releases if row['id'] == identity))


class DraftCleanupTests(unittest.TestCase):
    def invoke(self, remote, current=None, predecessor=None, **kwargs):
        return cleanup.cleanup_drafts(context() if current is None else current, predecessor,
            transport=remote, cleanup_run_id=99, sleep=lambda _: None, **kwargs)

    def deletions(self, remote):
        return [endpoint for method, endpoint in remote.calls if method == 'DELETE']

    def test_exact_two_stores_deleted_once_and_other_releases_preserved(self):
        remote = Transport([context(), context(37)])
        remote.releases += [dict(id=200, tag_name='base'), dict(id=201, tag_name='product-v1'),
                            dict(id=202, tag_name='ci-25-attempt-1')]
        result = self.invoke(remote, predecessor=context(37))
        self.assertEqual((result['selected_drafts'], result['deleted_drafts'], result['deleted_tags']), (2, 2, 2))
        self.assertEqual(self.deletions(remote), ['repos/example/project/releases/100',
            'repos/example/project/git/refs/tags/ci-42-attempt-1',
            'repos/example/project/releases/101', 'repos/example/project/git/refs/tags/ci-37-attempt-1'])
        self.assertEqual([row['id'] for row in remote.releases], [200, 201, 202])
        self.assertEqual(sum(endpoint.endswith('/releases?per_page=100') for _, endpoint in remote.calls), 1)

    def test_missing_release_preserves_orphaned_tag(self):
        remote = Transport([context()]); remote.releases = []
        self.assertEqual(self.invoke(remote)['selected_drafts'], 0)
        self.assertEqual(remote.refs, {'ci-42-attempt-1': 'a' * 40})
        self.assertFalse(self.deletions(remote))

    def test_retained_unknown_or_incomplete_bundle_preserves_entire_store(self):
        for name in ('sdk-group-linux-x86_64-1', 'rust-sdk-group-linux-x86_64-1',
                     'legacy-preservation', 'retention-check-old', 'unrecognized'):
            with self.subTest(name=name):
                remote = Transport([context()]); remote.assets[100] += remote.bundle_assets(name, 900)
                result = self.invoke(remote)
                self.assertEqual(result['preserved_drafts'], 1)
                self.assertEqual(result['preserved_tags'], ['ci-42-attempt-1'])
                self.assertFalse(self.deletions(remote))
        for mutate in (lambda rows: rows.pop(0), lambda rows: rows.pop(),
                       lambda rows: rows[1].update(digest='sha256:' + 'd' * 64),
                       lambda rows: rows[1].update(name=rows[1]['name'].replace('0000-', '0001-'))):
            remote = Transport([context()]); mutate(remote.assets[100])
            self.assertEqual(self.invoke(remote)['preserved_drafts'], 1)
            self.assertFalse(self.deletions(remote))

    def test_retained_workflows_and_invalid_contexts_refused_before_requests(self):
        changes = [dict(workflow=name) for name in ('sdk-maintenance.yml', 'sdk-import.yml',
            'legacy-artifacts.yml', 'verify-retention.yml', 'rust-qualification.yml')]
        changes += [dict(repository_id=True), dict(attempt=0), dict(source_commit='changed')]
        for change in changes:
            with self.subTest(change=change):
                selected = dict(context(), **change); remote = Transport([])
                with self.assertRaises(ValueError): self.invoke(remote, current=selected)
                self.assertFalse(remote.calls)
        remote = Transport([])
        with self.assertRaises(ValueError): self.invoke(remote, predecessor=context())
        self.assertFalse(remote.calls)

    def test_ambiguous_or_changed_provenance_refuses_all_deletion(self):
        changes = [lambda remote: remote.releases.append(dict(remote.releases[0], id=900)),
                   lambda remote: remote.releases[0].update(draft=False),
                   lambda remote: remote.releases[0].update(name='product'),
                   lambda remote: remote.releases[0].update(body='{}'),
                   lambda remote: remote.refs.update({'ci-42-attempt-1': 'd' * 40})]
        for change in changes:
            remote = Transport([context()]); change(remote)
            with self.assertRaises(ValueError): self.invoke(remote)
            self.assertFalse(self.deletions(remote))
        remote = Transport([context()])
        remote.after_assets = lambda wire: wire.assets[100][0].update(size=101)
        with self.assertRaisesRegex(ValueError, 'assets changed'): self.invoke(remote)
        self.assertFalse(self.deletions(remote))

    def test_every_other_active_consumer_blocks_release_deletion(self):
        for status in cleanup.repository_cleanup.ACTIVE_STATUSES:
            remote = Transport([context()])
            remote.active[status] = [dict(id=77, status=status)]
            with self.assertRaisesRegex(ValueError, 'not idle'): self.invoke(remote)
            self.assertFalse(self.deletions(remote))
        remote = Transport([context()]); remote.active['in_progress'] = [dict(id=99, status='in_progress')]
        self.assertEqual(self.invoke(remote)['deleted_tags'], 1)

    def test_uncertain_release_or_tag_delete_stops_without_retry(self):
        for endpoint, expected_releases in (('repos/example/project/releases/100', 0),
                ('repos/example/project/git/refs/tags/ci-42-attempt-1', 1)):
            remote = Transport([context(), context(37)]); remote.fail_delete = endpoint
            with self.assertRaisesRegex(ValueError, f'{expected_releases} confirmed release and 0 confirmed tag'):
                self.invoke(remote, predecessor=context(37))
            self.assertEqual(self.deletions(remote).count(endpoint), 1)
            self.assertTrue(any(row['id'] == 101 for row in remote.releases))

    def test_changed_tag_after_release_delete_is_preserved(self):
        remote = Transport([context()])
        remote.after_release_delete = lambda wire: wire.refs.update({'ci-42-attempt-1': 'd' * 40})
        with self.assertRaisesRegex(ValueError, '1 confirmed release and 0 confirmed tag'):
            self.invoke(remote)
        self.assertEqual(self.deletions(remote), ['repos/example/project/releases/100'])
        self.assertEqual(remote.refs['ci-42-attempt-1'], 'd' * 40)

    def test_expired_cleanup_budget_attempts_no_mutation(self):
        remote = Transport([context()]); ticks = iter((0, cleanup.MAX_SECONDS))
        with self.assertRaisesRegex(ValueError, 'two-minute'): self.invoke(remote, clock=lambda: next(ticks))
        self.assertFalse(self.deletions(remote))


if __name__ == '__main__':
    unittest.main()
