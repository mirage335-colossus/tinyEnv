"""Release and bounded artifact transport fixtures use no network."""
import copy
import hashlib
import io
import json
import os
import stat
from types import SimpleNamespace
from pathlib import Path
import sys
import tarfile
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
import ci_transport as t


class FakeGitHub:
    def __init__(self):
        self.repo = dict(id=7, full_name='example/project')
        self.run = dict(id=12, run_attempt=2, head_sha='a' * 40, event='workflow_dispatch',
                        path='.github/workflows/sdk-maintenance.yml',
                        repository=self.repo.copy(), head_repository=self.repo.copy())
        self.jobs = [dict(id=30, run_id=12, run_attempt=2, head_sha='a' * 40,
                         name='produce (linux-aarch64)', runner_id=90, runner_name='Runner 1',
                         status='in_progress', conclusion=None)]
        self.refs = {}; self.releases = []; self.data = {}; self.next_asset = 100
        self.calls = []; self.lose_upload = False; self.on_download = None

    def json(self, endpoint, *, method='GET', body=None, missing=False):
        self.calls.append((method, endpoint))
        base = 'repos/example/project'; assert endpoint.startswith(base)
        path = endpoint[len(base):]
        if not path: return copy.deepcopy(self.repo)
        if path == '/actions/runs/12/attempts/2': return copy.deepcopy(self.run)
        if path.startswith('/actions/runs/12/attempts/2/jobs?'):
            page = int(path.rsplit('page=', 1)[1]); rows = self.jobs[(page - 1) * 100:page * 100]
            return dict(total_count=len(self.jobs), jobs=copy.deepcopy(rows))
        if path == '/releases/9': return copy.deepcopy(next(row for row in self.releases if row['id'] == 9))
        if path.startswith('/actions/jobs/'):
            return copy.deepcopy(next(j for j in self.jobs if j['id'] == int(path.rsplit('/', 1)[1])))
        if path.startswith('/git/ref/tags/'):
            value = self.refs.get(path.split('/tags/', 1)[1])
            if value is None and missing: return None
            if value is None: raise t.delivery.DeliveryError('missing tag')
            return dict(object=dict(type='commit', sha=value))
        if path == '/git/refs' and method == 'POST':
            name = body['ref'].split('refs/tags/', 1)[1]
            if name in self.refs: raise t.delivery.DeliveryError('already exists')
            self.refs[name] = body['sha']; return {}
        if path == '/releases' and method == 'POST':
            # The real API permits duplicate draft tags; never fake uniqueness.
            self.releases.append(dict(body, id=9, assets=[])); return copy.deepcopy(self.releases[-1])
        raise AssertionError((endpoint, method, body))

    def pages(self, endpoint):
        self.calls.append(('pages', endpoint))
        if endpoint.endswith('/releases?per_page=100'): return copy.deepcopy(self.releases)
        assert '/releases/9/assets?' in endpoint
        return copy.deepcopy(self.releases[0]['assets'])

    def upload(self, tag, path):
        self.calls.append(('upload', path.name))
        row = self.releases[0]; assert row['tag_name'] == tag
        assert all(a['name'] != path.name for a in row['assets'])
        raw = path.read_bytes(); aid = self.next_asset; self.next_asset += 1
        row['assets'].append(dict(id=aid, name=path.name, size=len(raw), digest='sha256:' + t.delivery.sha(raw), state='uploaded'))
        self.data[aid] = raw
        if self.lose_upload:
            self.lose_upload = False
            raise t.delivery.DeliveryError('response lost after write', True)

    def download(self, aid, path):
        self.calls.append(('download', aid)); path.write_bytes(self.data[aid])
        if self.on_download:
            callback, self.on_download = self.on_download, None; callback()

    def complete(self, conclusion='success'):
        self.jobs[0].update(status='completed', conclusion=conclusion)

    def replace(self, name, content):
        row = next(a for a in self.releases[0]['assets'] if a['name'] == name)
        row.update(size=len(content), digest='sha256:' + t.delivery.sha(content))
        self.data[row['id']] = content


class TransportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='transport fixture '); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve(); self.source = self.root / 'source'; self.source.mkdir()
        (self.source / 'folder').mkdir(); (self.source / 'folder/file with spaces').write_bytes(b'abc' * 100)
        (self.source / 'empty').write_bytes(b''); (self.source / 'tool').write_bytes(b'#!/bin/sh\nexit 0\n')
        (self.source / 'tool').chmod(0o755)
        self.remote = FakeGitHub()
        self.context = dict(repository='example/project', run_id=12, attempt=2, source_commit='a' * 40,
                            workflow='sdk-maintenance.yml', name='sdk-group-linux-aarch64')

    def publish(self, **kwargs):
        options = dict(self.context, root=self.source, paths=['folder', 'empty', 'tool'],
                       job_id=30, transport=self.remote, chunk_bytes=4096)
        options.update(kwargs); return t.publish_bundle(**options)

    def fetch(self, **kwargs):
        options = dict(self.context, output=self.root / 'restored', transport=self.remote)
        options.update(kwargs); return t.fetch_bundle(**options)

    def manifest(self):
        row = next(a for a in self.remote.releases[0]['assets'] if a['name'].startswith('bundle-'))
        return row, json.loads(self.remote.data[row['id']])

    def mutate_manifest(self, action):
        row, value = self.manifest(); action(value)
        self.remote.replace(row['name'], t.archive.encoded(value))

    def test_roundtrip_binds_context_and_preserves_bytes_and_modes(self):
        pointer = self.publish(metadata={'recipe': 'b' * 64})
        self.remote.complete(); receipt = self.fetch(manifest_id=pointer['manifest']['id'],
                                                    manifest_sha256=pointer['manifest']['sha256'])
        self.assertEqual(receipt['pointer'], pointer)
        self.assertEqual(receipt['manifest']['metadata'], {'recipe': 'b' * 64})
        for name in ('folder/file with spaces', 'empty', 'tool'):
            self.assertEqual((self.source / name).read_bytes(), (self.root / 'restored' / name).read_bytes())
        if os.name != 'nt': self.assertEqual(0o755, (self.root / 'restored/tool').stat().st_mode & 0o777)
        self.assertTrue(self.remote.releases[0]['draft']); self.assertTrue(self.remote.releases[0]['prerelease'])
        self.assertEqual('false', self.remote.releases[0]['make_latest'])
        self.assertFalse(any('/actions/artifacts' in str(c) for c in self.remote.calls))

    def test_single_part_preserves_archive_hash_and_rejects_wrong_whole_identity(self):
        self.publish(chunk_bytes=t.CHUNK_BYTES); self.remote.complete()
        _, manifest = self.manifest(); self.assertEqual(len(manifest['archive']['parts']), 1)
        self.mutate_manifest(lambda value: value['archive'].update(sha256='0' * 64))
        with self.assertRaisesRegex(ValueError, 'reconstructed archive bytes differ'):
            self.fetch()
        self.assertFalse((self.root / 'restored').exists())

    def test_compressed_evidence_is_smaller_and_retry_identical(self):
        (self.source / 'log.txt').write_text('Repeated diagnostic text\n' * 10000)
        pointer = self.publish(paths=['log.txt'], compress=True)
        _, manifest = self.manifest()
        self.assertLess(manifest['archive']['size'], (self.source / 'log.txt').stat().st_size // 10)
        uploads = [c for c in self.remote.calls if c[0] == 'upload']
        self.assertEqual(pointer, self.publish(paths=['log.txt'], compress=True))
        self.assertEqual(uploads, [c for c in self.remote.calls if c[0] == 'upload'])
        self.remote.complete(); self.fetch()
        self.assertEqual((self.source / 'log.txt').read_bytes(), (self.root / 'restored/log.txt').read_bytes())

    def test_compressed_input_cannot_expand_past_declared_payload_bound(self):
        path = self.root / 'oversized.gz'
        with t.gzip.open(path, 'wb') as stream: stream.write(b'x' * 100000)
        output = self.root / 'expanded'; output.mkdir()
        files = {'file': dict(size=1, mode=0o644, sha256=t.delivery.sha(b'x'))}
        with patch.object(t, 'MAX_MANIFEST', 100), self.assertRaisesRegex(ValueError, 'expanded archive'):
            t._extract(path, output, files)
        self.assertFalse(list(output.iterdir()))
        self.assertFalse(list(self.root.glob('expanded-*')))

    def test_parallel_chunk_fetch_joins_failure_without_publishing_partial_output(self):
        self.publish(chunk_bytes=1024); self.remote.complete()
        original = self.remote.download
        import threading
        gate = threading.Barrier(2, timeout=3)
        active, maximum = 0, 0
        lock = threading.Lock()
        def download(aid, path):
            nonlocal active, maximum
            if path.name.startswith('blob-'):
                with lock:
                    active += 1; maximum = max(maximum, active)
                try:
                    if any(part in path.name for part in ('-0000-', '-0001-')): gate.wait()
                    if '-0000-' in path.name: raise OSError('network failure')
                    original(aid, path)
                finally:
                    with lock: active -= 1
            else: original(aid, path)
        with patch.object(self.remote, 'download', side_effect=download):
            with self.assertRaises(OSError): self.fetch()
        self.assertGreaterEqual(maximum, 2)
        self.assertEqual(active, 0)
        self.assertFalse((self.root / 'restored').exists())

    def test_manifest_uploaded_last_and_identical_retry_performs_no_upload(self):
        first = self.publish(); uploads = [c for c in self.remote.calls if c[0] == 'upload']
        self.assertTrue(uploads[-1][1].startswith('bundle-')); self.assertGreater(len(uploads), 2)
        self.assertEqual(first, self.publish())
        self.assertEqual(uploads, [c for c in self.remote.calls if c[0] == 'upload'])

    def test_partial_response_loss_retains_bytes_and_exact_retry_reconciles(self):
        self.remote.lose_upload = True
        with self.assertRaises(t.delivery.DeliveryError): self.publish()
        self.assertGreaterEqual(len(self.remote.releases[0]['assets']), 1)
        self.assertLessEqual(len(self.remote.releases[0]['assets']), 4)
        self.assertFalse(any(x['name'].startswith('bundle-') for x in self.remote.releases[0]['assets']))
        self.publish(); self.remote.complete(); self.fetch()

    def test_changed_bytes_cannot_overwrite_completed_or_partial_bundle(self):
        self.publish(); previous = copy.deepcopy(self.remote.data)
        (self.source / 'empty').write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError, 'prior bundle assets'): self.publish()
        self.assertEqual(previous, self.remote.data)

    def test_partial_bundle_is_never_fetchable(self):
        self.remote.lose_upload = True
        with self.assertRaises(t.delivery.DeliveryError): self.publish()
        self.remote.complete()
        with self.assertRaisesRegex(ValueError, 'manifest'): self.fetch()
        self.assertFalse((self.root / 'restored').exists())

    def test_failed_or_running_job_requires_explicit_completed_failure_policy(self):
        self.publish(metadata={'status': 'passed'})
        with self.assertRaisesRegex(ValueError, 'completion'): self.fetch(allow_failed=True)
        self.remote.complete('failure')
        with self.assertRaisesRegex(ValueError, 'completion'): self.fetch()
        result = self.fetch(allow_failed=True)
        self.assertEqual('failure', result['producer']['conclusion'])

    def test_cancelled_job_never_becomes_retained_pass(self):
        self.publish(); self.remote.complete('cancelled')
        with self.assertRaisesRegex(ValueError, 'completion'): self.fetch(allow_failed=True)

    def test_repository_source_attempt_workflow_and_fork_mismatch_fail_before_write(self):
        changes = [('head_sha', 'b' * 40), ('run_attempt', 1), ('path', '.github/workflows/other.yml'),
                   ('head_repository', dict(id=8, full_name='example/project')), ('event', 'pull_request')]
        for key, value in changes:
            with self.subTest(key=key):
                prior = self.remote.run[key]; self.remote.run[key] = value
                with self.assertRaisesRegex(ValueError, 'producer repository'): self.publish()
                self.remote.run[key] = prior
        self.assertFalse(self.remote.releases)

    def test_explicit_rust_feature_push_preserves_complete_transport_binding(self):
        self.remote.run.update(event='push', head_branch='codex/rust-hybrid-integration-20261004',
                               path='.github/workflows/rust-qualification.yml')
        self.context.update(workflow='rust-qualification.yml', name='rust-qualification-linux-aarch64-2')
        pointer = self.publish(); self.remote.complete()
        self.assertEqual(pointer, self.fetch()['pointer'])
        self.assertTrue(self.remote.releases[0]['draft'])
        self.assertEqual('false', self.remote.releases[0]['make_latest'])

    def test_push_exception_rejects_other_workflows_branches_and_foreign_inputs(self):
        self.remote.run.update(event='push', head_branch='codex/rust-hybrid',
                               path='.github/workflows/rust-qualification.yml')
        self.context.update(workflow='rust-qualification.yml')
        cases = [('head_branch', 'main'), ('head_branch', 'codex/other'),
                 ('head_branch', 'codex/rust-hybrid/nested'), ('head_branch', None),
                 ('event', 'pull_request'), ('head_sha', 'b' * 40), ('run_attempt', 1),
                 ('head_repository', dict(id=8, full_name='example/project')),
                 ('path', '.github/workflows/sdk-maintenance.yml')]
        for key, value in cases:
            with self.subTest(field=key, value=value):
                prior = self.remote.run[key]; self.remote.run[key] = value
                with self.assertRaisesRegex(ValueError, 'producer repository'): self.publish()
                self.remote.run[key] = prior
        self.remote.run['path'] = '.github/workflows/sdk-maintenance.yml'
        with self.assertRaisesRegex(ValueError, 'producer repository'):
            self.publish(workflow='sdk-maintenance.yml')
        self.assertFalse(self.remote.releases)

    def test_reusable_caller_workflow_and_unique_runner_resolution(self):
        self.remote.run['path'] = '.github/workflows/_release-latest.yml'
        self.remote.jobs[0]['name'] = 'SDK / produce (linux-aarch64)'
        self.publish(workflow='_release-latest.yml', job_id=None, runner_name='Runner 1')
        self.remote.complete()
        self.fetch(workflow='_release-latest.yml', job_name='SDK / produce (linux-aarch64)')

    def test_canonical_target_name_with_underscore_roundtrips(self):
        name = 'sdk-group-windows-x86_64-2'
        pointer = self.publish(name=name); self.remote.complete()
        self.assertEqual(pointer, self.fetch(name=name)['pointer'])

    def test_ambiguous_runner_and_wrong_explicit_job_fail(self):
        self.remote.jobs.append(dict(self.remote.jobs[0], id=31))
        with self.assertRaisesRegex(ValueError, 'ambiguous'): self.publish(job_id=None, runner_name='Runner 1')
        with self.assertRaisesRegex(ValueError, 'job identity'): self.publish(job_name='other')

    def test_job_inventory_paginates_completely(self):
        self.remote.jobs = [dict(self.remote.jobs[0], id=1000 + i, runner_name='Other ' + str(i)) for i in range(100)] + self.remote.jobs
        self.publish(job_id=None, runner_name='Runner 1')
        self.assertTrue(any('page=2' in str(c) for c in self.remote.calls))

    def test_existing_tag_or_public_release_conflict_is_not_repaired(self):
        self.remote.refs['ci-12-attempt-2'] = 'b' * 40
        with self.assertRaisesRegex(ValueError, 'tag source'): self.publish()
        self.remote.refs.clear(); self.publish(); self.remote.releases[0]['draft'] = False
        with self.assertRaisesRegex(ValueError, 'lifecycle'): self.publish()

    def test_pinned_manifest_and_exact_job_are_required_when_supplied(self):
        pointer = self.publish(); self.remote.complete()
        for options in ({'manifest_id': pointer['manifest']['id'], 'manifest_sha256': '0' * 64},
                        {'manifest_id': pointer['manifest']['id']}, {'job_id': 31}, {'job_name': 'other'}):
            with self.subTest(options=options), self.assertRaises(ValueError): self.fetch(**options)

    def test_asset_corruption_id_replacement_and_remote_changes_reject(self):
        self.publish(); self.remote.complete(); row = self.remote.releases[0]['assets'][0]
        old = self.remote.data[row['id']]; self.remote.data[row['id']] = b'corrupt'
        with self.assertRaisesRegex(ValueError, 'downloaded asset'): self.fetch()
        self.remote.data[row['id']] = old
        self.remote.on_download = lambda: self.remote.jobs[0].update(name='changed')
        with self.assertRaisesRegex(ValueError, 'producer identity'): self.fetch()
        self.assertFalse((self.root / 'restored').exists())

    def test_changed_chunk_identity_and_extra_owned_chunk_reject(self):
        self.publish(); self.remote.complete(); row = self.remote.releases[0]['assets'][0]
        row['id'] += 10000
        with self.assertRaisesRegex(ValueError, 'complete declared'): self.fetch()
        row['id'] -= 10000
        extra = dict(row, id=9999, name=t._prefix(self.context['name']) + 'unexpected')
        self.remote.releases[0]['assets'].append(extra)
        with self.assertRaisesRegex(ValueError, 'complete declared'): self.fetch()

    def test_parallel_other_bundle_does_not_invalidate_this_inventory(self):
        self.publish()
        self.remote.releases[0]['assets'].append(dict(id=9999, name=t._prefix('other') + 'uploading', state='starter'))
        self.remote.complete(); self.fetch()

    def test_two_jobs_reconcile_concurrent_store_creation_and_keep_separate_bundles(self):
        self.remote.jobs.append(dict(self.remote.jobs[0], id=31, runner_id=91,
                                     runner_name='Runner 2', name='proof'))
        original = self.remote.json; interleaved = []; entered = False
        def interleave(endpoint, **kwargs):
            nonlocal entered
            if endpoint.endswith('/git/refs') and kwargs.get('method') == 'POST' and not entered:
                entered = True
                # Both publishers observed no tag/release; job 31 wins both creates.
                interleaved.append(self.publish(name='proof', job_id=31, paths=['tool']))
            return original(endpoint, **kwargs)
        with patch.object(self.remote, 'json', side_effect=interleave):
            first = self.publish()
        self.assertEqual(1, len(self.remote.refs)); self.assertEqual(1, len(self.remote.releases))
        self.assertEqual(first['release_id'], interleaved[0]['release_id'])
        self.assertNotEqual(first['manifest']['id'], interleaved[0]['manifest']['id'])
        self.assertEqual(2, len([c for c in self.remote.calls if c == ('POST', 'repos/example/project/git/refs')]))
        self.assertEqual(1, len([c for c in self.remote.calls if c == ('POST', 'repos/example/project/releases')]))
        for job in self.remote.jobs: job.update(status='completed', conclusion='success')
        one = self.fetch(); two = self.fetch(name='proof', job_id=31, output=self.root / 'proof')
        self.assertEqual(30, one['producer']['id']); self.assertEqual(31, two['producer']['id'])
        self.assertEqual(['tool'], list(two['manifest']['files']))
        self.assertEqual((self.root / 'restored/tool').read_bytes(), (self.root / 'proof/tool').read_bytes())

    def test_confirmed_creation_uses_exact_id_despite_unstable_unrelated_inventory(self):
        remote=t.delivery.Remote('example/project',self.remote)
        original=self.remote.pages
        def unstable(endpoint):
            if endpoint.endswith('/releases?per_page=100') and self.remote.releases:
                # Insertion between paginated reads can repeat an unrelated row.
                other=dict(self.remote.releases[0],id=88,tag_name='unrelated')
                return [other,other,*self.remote.releases]
            return original(endpoint)
        with patch.object(self.remote,'pages',side_effect=unstable):
            found=t._store(remote,self.context,7,create=True)
        self.assertEqual(found['id'],9)
        self.assertEqual(1,self.remote.calls.count(('pages','repos/example/project/releases?per_page=100')))
        self.assertEqual(1,self.remote.calls.count(('GET','repos/example/project/releases/9')))
        self.assertEqual(1,self.remote.calls.count(('POST','repos/example/project/releases')))
        self.assertEqual(self.remote.refs['ci-12-attempt-2'],self.context['source_commit'])

    def test_creation_response_requires_complete_transport_identity_before_id_observation(self):
        changes=({'id':True},{'tag_name':'other'},{'draft':False},{'prerelease':False},
                 {'name':'other'},{'body':'{}'},{'target_commitish':'b'*40})
        for change in changes:
            with self.subTest(change=change):
                self.remote=FakeGitHub();remote=t.delivery.Remote('example/project',self.remote)
                original=self.remote.json
                def changed(endpoint,**kwargs):
                    value=original(endpoint,**kwargs)
                    return dict(value,**change) if endpoint.endswith('/releases') and kwargs.get('method')=='POST' else value
                with patch.object(self.remote,'json',side_effect=changed),self.assertRaises(t.delivery.DeliveryError) as caught:
                    t.delivery.run_mutation(remote,lambda:t._store(remote,self.context,7,create=True))
                self.assertTrue(caught.exception.uncertain)
                self.assertNotIn(('GET','repos/example/project/releases/9'),self.remote.calls)
                self.assertEqual(1,self.remote.calls.count(('POST','repos/example/project/releases')))

    def test_known_id_visibility_limit_and_observed_identity_fail_without_recreation(self):
        changes=(None,{'id':10},{'tag_name':'other'},{'draft':False},{'prerelease':False},
                 {'name':'other'},{'body':'{}'},{'source_ref':'b'*40})
        for change in changes:
            with self.subTest(change=change):
                self.remote=FakeGitHub();remote=t.delivery.Remote('example/project',self.remote);original=self.remote.json
                def observe(endpoint,**kwargs):
                    value=original(endpoint,**kwargs)
                    if endpoint.endswith('/releases/9'):
                        if change is None:return None
                        if 'source_ref' in change:self.remote.refs['ci-12-attempt-2']=change['source_ref'];return value
                        return dict(value,**change)
                    return value
                with patch.object(self.remote,'json',side_effect=observe),patch.object(t.time,'sleep'), \
                        self.assertRaises(t.delivery.DeliveryError) as caught:
                    t.delivery.run_mutation(remote,lambda:t._store(remote,self.context,7,create=True))
                self.assertTrue(caught.exception.uncertain)
                self.assertEqual(7 if change is None else 1,self.remote.calls.count(('GET','repos/example/project/releases/9')))
                self.assertEqual(1,self.remote.calls.count(('pages','repos/example/project/releases?per_page=100')))
                self.assertEqual(1,self.remote.calls.count(('POST','repos/example/project/releases')))

    def test_lost_creation_response_keeps_strict_discovery_and_never_repeats_write(self):
        for observed in ('visible','missing','duplicate'):
            with self.subTest(observed=observed):
                self.remote=FakeGitHub();remote=t.delivery.Remote('example/project',self.remote)
                original_json=self.remote.json;original_pages=self.remote.pages
                def lose(endpoint,**kwargs):
                    value=original_json(endpoint,**kwargs)
                    if endpoint.endswith('/releases') and kwargs.get('method')=='POST':
                        raise t.delivery.DeliveryError('response lost after creation',True)
                    return value
                def inventory(endpoint):
                    rows=original_pages(endpoint)
                    if endpoint.endswith('/releases?per_page=100') and rows:
                        return [] if observed=='missing' else rows*2 if observed=='duplicate' else rows
                    return rows
                with patch.object(self.remote,'json',side_effect=lose),patch.object(self.remote,'pages',side_effect=inventory),patch.object(t.time,'sleep'):
                    if observed=='visible':self.assertEqual(9,t._store(remote,self.context,7,create=True)['id'])
                    else:
                        with self.assertRaises(t.delivery.DeliveryError) as caught:
                            t.delivery.run_mutation(remote,lambda:t._store(remote,self.context,7,create=True))
                        self.assertTrue(caught.exception.uncertain)
                        self.assertIn('response lost' if observed=='missing' else 'duplicate release inventory',str(caught.exception))
                self.assertNotIn(('GET','repos/example/project/releases/9'),self.remote.calls)
                self.assertEqual(1,self.remote.calls.count(('POST','repos/example/project/releases')))

    def test_preexisting_uninitialized_tag_never_grants_draft_creation(self):
        self.remote.refs['ci-12-attempt-2'] = self.context['source_commit']
        with patch.object(t.time, 'sleep'), self.assertRaisesRegex(ValueError, 'not visible'):
            self.publish()
        self.assertFalse(self.remote.releases)
        self.assertFalse(any(c[0] == 'POST' for c in self.remote.calls))

    def test_uncertain_ref_creation_response_never_grants_draft_creation(self):
        original = self.remote.json
        def uncertain(endpoint, **kwargs):
            result = original(endpoint, **kwargs)
            if endpoint.endswith('/git/refs') and kwargs.get('method') == 'POST':
                raise t.delivery.DeliveryError('response lost after ref creation', True)
            return result
        with patch.object(self.remote, 'json', side_effect=uncertain), patch.object(t.time, 'sleep'), \
                self.assertRaisesRegex(ValueError, 'not visible'):
            self.publish()
        self.assertEqual(1, len(self.remote.refs)); self.assertFalse(self.remote.releases)
        self.assertFalse(any(c == ('POST', 'repos/example/project/releases') for c in self.remote.calls))

    def test_manifest_context_types_and_metadata_bounds_are_strict(self):
        self.publish(); self.remote.complete(); row, base = self.manifest()
        edits = [lambda v:v.update(attempt=True), lambda v:v.update(repository_id=True),
                 lambda v:v.update(release_id=True), lambda v:v['producer'].update(id=True),
                 lambda v:v['producer'].update(runner_id=True),
                 lambda v:v.update(metadata={'oversized': 'x' * 65536})]
        for edit in edits:
            with self.subTest(edit=edit):
                value = copy.deepcopy(base); edit(value)
                self.remote.replace(row['name'], t.archive.encoded(value))
                with self.assertRaisesRegex(ValueError, 'provenance'): self.fetch()

    def test_unsafe_input_paths_and_missing_files_fail_before_remote_write(self):
        for value in ('../tool', '/tool', 'folder/../tool', 'folder\\tool', 'C:tool', 'CON', 'folder//tool'):
            with self.subTest(value=value), self.assertRaises(ValueError): self.publish(paths=[value])
        with self.assertRaises(FileNotFoundError): self.publish(paths=['missing'])
        with self.assertRaisesRegex(ValueError, 'empty'): self.publish(paths=['missing'], allow_missing=True)
        self.assertFalse(self.remote.releases)

    def test_missing_diagnostic_path_and_overlapping_selection_are_explicit(self):
        self.publish(paths=['missing', 'folder', 'folder/file with spaces'], allow_missing=True)
        self.remote.complete(); result = self.fetch()
        self.assertEqual(['folder/file with spaces'], list(result['manifest']['files']))

    def test_links_and_nonregular_inputs_reject(self):
        original = Path.lstat
        for mode, attributes in ((stat.S_IFLNK | 0o777, 0), (stat.S_IFIFO | 0o644, 0),
                                 (stat.S_IFREG | 0o4755, 0), (stat.S_IFREG | 0o644, 0x400)):
            with self.subTest(mode=mode, attributes=attributes):
                def observed(path, *args, **kwargs):
                    if path == self.source / 'tool':
                        return SimpleNamespace(st_mode=mode, st_file_attributes=attributes)
                    return original(path, *args, **kwargs)
                with patch.object(Path, 'lstat', observed), self.assertRaisesRegex(ValueError, 'ordinary'):
                    self.publish()
        self.assertFalse(self.remote.releases)

    def test_manifest_rejects_path_aliases_traversal_mode_and_file_parent(self):
        self.publish(); self.remote.complete(); row, base = self.manifest()
        edits = [lambda v:v['files'].update({'../bad': next(iter(v['files'].values()))}),
                 lambda v:v['files'].update({'Folder/new': next(iter(v['files'].values()))}),
                 lambda v:v['files'].update({'folder': next(iter(v['files'].values()))}),
                 lambda v:v['files']['tool'].update(mode=0o4755),
                 lambda v:v.update(unknown=True)]
        for edit in edits:
            with self.subTest(edit=edit):
                value = copy.deepcopy(base); edit(value); self.remote.replace(row['name'], t.archive.encoded(value))
                with self.assertRaises(ValueError): self.fetch()

    def test_tar_links_duplicate_missing_and_unexpected_files_reject(self):
        files = {'file': dict(size=1, mode=0o644, sha256=hashlib.sha256(b'x').hexdigest())}
        for mode in ('link', 'duplicate', 'missing', 'extra', 'bad-bytes'):
            with self.subTest(mode=mode):
                path = self.root / (mode + '.tar')
                with tarfile.open(path, 'w') as stream:
                    if mode == 'link':
                        info = tarfile.TarInfo('file'); info.type = tarfile.SYMTYPE; info.linkname = '../elsewhere'; stream.addfile(info)
                    elif mode != 'missing':
                        for name in (['file', 'file'] if mode == 'duplicate' else ['file', 'extra'] if mode == 'extra' else ['file']):
                            info = tarfile.TarInfo(name); info.size = 1; info.mode = 0o644
                            stream.addfile(info, io.BytesIO(b'y' if mode == 'bad-bytes' else b'x'))
                output = self.root / mode; output.mkdir()
                with self.assertRaises(ValueError): t._extract(path, output, files)

    def test_input_mutation_prevents_commit_marker(self):
        original = self.remote.upload
        def upload(tag, path):
            original(tag, path); (self.source / 'empty').write_bytes(b'changed')
        with patch.object(self.remote, 'upload', side_effect=upload):
            with self.assertRaisesRegex(ValueError, 'input changed'): self.publish()
        self.assertFalse(any(a['name'].startswith('bundle-') for a in self.remote.releases[0]['assets']))

    def test_existing_destination_is_never_replaced(self):
        self.publish(); self.remote.complete(); output = self.root / 'restored'; output.mkdir(); (output / 'owned').write_text('keep')
        with self.assertRaisesRegex(ValueError, 'must be new'): self.fetch()
        self.assertEqual('keep', (output / 'owned').read_text())

    def test_large_payload_uses_release_chunks_and_reconstructs_exact_bytes(self):
        data = bytes(range(256)) * 8193
        (self.source / 'large.bin').write_bytes(data)
        self.publish(paths=['large.bin'], chunk_bytes=65536)
        self.remote.complete(); result = self.fetch()
        self.assertEqual(data, (self.root / 'restored/large.bin').read_bytes())
        self.assertGreater(len(result['manifest']['archive']['parts']), 30)
        self.assertTrue(all(p['size'] <= 65536 for p in result['manifest']['archive']['parts']))
        self.assertFalse(any('actions/artifacts' in str(c) or 'upload-artifact' in str(c) for c in self.remote.calls))

    def test_lost_manifest_response_reconciles_without_overwrite(self):
        original = self.remote.upload
        def upload(tag, path):
            if path.name.startswith('bundle-'): self.remote.lose_upload = True
            original(tag, path)
        with patch.object(self.remote, 'upload', side_effect=upload):
            with self.assertRaises(t.delivery.DeliveryError): self.publish()
        uploads = len([c for c in self.remote.calls if c[0] == 'upload'])
        self.publish()
        self.assertEqual(uploads, len([c for c in self.remote.calls if c[0] == 'upload']))
        self.remote.complete(); self.fetch()

    def test_created_draft_visibility_is_reconciled_with_reads_only(self):
        original = self.remote.json; hidden = 3
        def delayed(endpoint, **kwargs):
            nonlocal hidden
            value = original(endpoint, **kwargs)
            if endpoint.endswith('/releases/9') and hidden:
                self.assertTrue(kwargs.get('missing'))
                hidden -= 1
                return None
            return value
        with patch.object(self.remote, 'json', side_effect=delayed), patch.object(t.time, 'sleep') as sleep:
            self.publish()
        self.assertEqual(0, hidden); self.assertEqual(3, sleep.call_count)
        self.assertEqual(1, len([c for c in self.remote.calls if c == ('POST', 'repos/example/project/releases')]))
        self.remote.complete(); self.fetch()

    def test_unobserved_created_draft_fails_without_repeating_mutation(self):
        original = self.remote.json
        def hidden(endpoint, **kwargs):
            value = original(endpoint, **kwargs)
            if endpoint.endswith('/releases/9'):
                self.assertTrue(kwargs.get('missing'))
                return None
            return value
        with patch.object(self.remote, 'json', side_effect=hidden), patch.object(t.time, 'sleep'), \
                self.assertRaisesRegex(ValueError, 'not visible'):
            self.publish()
        self.assertEqual(1, len(self.remote.releases))
        self.assertEqual(1, len([c for c in self.remote.calls if c == ('POST', 'repos/example/project/releases')]))
        self.assertFalse(self.remote.releases[0]['assets'])

    def test_manifest_identity_replacement_after_upload_is_rejected(self):
        original = t._asset_inventory; changed = False
        def replaced(remote, info):
            nonlocal changed
            result = original(remote, info)
            if any(name.startswith('bundle-') for name in result) and not changed:
                changed = True
                marker = next(row for row in self.remote.releases[0]['assets'] if row['name'].startswith('bundle-'))
                marker['id'] += 10000
            return result
        with patch.object(t, '_asset_inventory', side_effect=replaced), self.assertRaisesRegex(ValueError, 'after commit marker'):
            self.publish()

    def test_transport_tag_change_after_manifest_upload_is_rejected(self):
        original = self.remote.upload
        def changed(tag, path):
            original(tag, path)
            if path.name.startswith('bundle-'): self.remote.refs[tag] = 'b' * 40
        with patch.object(self.remote, 'upload', side_effect=changed), self.assertRaisesRegex(ValueError, 'lifecycle'):
            self.publish()

    def test_chunk_count_limit_is_checked_before_any_remote_mutation(self):
        with self.assertRaisesRegex(ValueError, 'too many bounded chunks'): self.publish(chunk_bytes=1)
        self.assertFalse(self.remote.releases)
        self.assertFalse(self.remote.refs)

    def test_small_chunk_reconstruction_preserves_complete_archive_hash(self):
        self.publish(chunk_bytes=1024); self.remote.complete(); result = self.fetch()
        parts = result['manifest']['archive']['parts']; self.assertGreater(len(parts), 2)
        self.assertEqual(list(range(len(parts))), [int(p['name'][len(t._prefix(self.context['name'])):][:4]) for p in parts])




class BatchTransportTests(unittest.TestCase):
    setUp = TransportTests.setUp
    publish = TransportTests.publish
    fetch = TransportTests.fetch

    def common(self):
        return {key:value for key,value in self.context.items() if key != 'name'}

    def requests(self, count=8):
        return [dict(name='batch-'+str(i), root=self.source, paths=['folder', 'empty', 'tool'],
                     compress=bool(i % 2)) for i in range(count)]

    def publish_batch(self, requests=None):
        return t.publish_bundles(**self.common(), requests=requests or self.requests(),
                                 job_id=30, transport=self.remote)

    def fetch_batch(self, names=None, **options):
        names = names or [row['name'] for row in self.requests()]
        return t.fetch_bundles(**self.common(), requests=[dict(name=name, output=self.root/name, **options)
                              for name in names], transport=self.remote)

    def reads(self):
        return [call for call in self.remote.calls if call[0] in ('GET', 'pages')]

    def test_eight_fetches_share_exact_provenance_and_inventory_boundaries(self):
        pointers = self.publish_batch(); self.remote.complete(); self.remote.calls.clear()
        receipts = self.fetch_batch()
        self.assertEqual(pointers, [result['pointer'] for result in receipts])
        self.assertEqual(12, len(self.reads()))
        self.assertEqual(2, sum('/jobs?per_page=' in call[1] for call in self.reads()))
        self.assertFalse(any('/actions/jobs/' in call[1] for call in self.reads()))
        for result in receipts:
            self.assertEqual(b'abc'*100, (self.root/result['pointer']['name']/'folder/file with spaces').read_bytes())
        self.remote.calls.clear()
        for request in self.requests(): self.fetch(name=request['name'], output=self.root/('single-'+request['name']))
        self.assertEqual(96, len(self.reads()))

    def test_batch_publication_has_constant_metadata_reads_and_payloads_before_markers(self):
        pointers = self.publish_batch()
        self.assertEqual(18, len(self.reads()))
        uploads = [call[1] for call in self.remote.calls if call[0] == 'upload']
        first_marker = next(i for i,name in enumerate(uploads) if name.startswith('bundle-'))
        self.assertEqual(8, first_marker)
        self.assertTrue(all(name.startswith('bundle-') for name in uploads[first_marker:]))
        self.remote.calls.clear()
        self.assertEqual(pointers, self.publish_batch())
        self.assertEqual(16, len(self.reads()))
        self.assertFalse(any(call[0] == 'upload' for call in self.remote.calls))

    def test_every_output_is_quarantined_until_last_bundle_bytes_verify(self):
        self.publish_batch(); self.remote.complete()
        row = next(row for row in self.remote.releases[0]['assets'] if row['name'].startswith(t._prefix('batch-7')))
        self.remote.data[row['id']] = b'tampered'
        with self.assertRaisesRegex(ValueError, 'downloaded asset'): self.fetch_batch()
        self.assertFalse(any((self.root/request['name']).exists() for request in self.requests()))
        self.assertFalse(list(self.root.glob('.foundation-ci-fetch-*')))

    def test_selected_remote_boundary_changes_reject_all_outputs(self):
        changes = ('source', 'tag', 'release', 'producer', 'asset', 'extra')
        for change in changes:
            with self.subTest(change=change):
                remote = FakeGitHub(); self.remote = remote
                self.publish_batch(self.requests(2)); remote.complete(); original = remote.download; changed = False
                def download(identity, path):
                    nonlocal changed
                    original(identity, path)
                    if path.name.startswith('blob-') and not changed:
                        changed = True
                        if change == 'source': remote.run['head_sha'] = 'b'*40
                        elif change == 'tag': remote.refs['ci-12-attempt-2'] = 'b'*40
                        elif change == 'release': remote.releases[0]['draft'] = False
                        elif change == 'producer': remote.jobs[0]['conclusion'] = 'failure'
                        elif change == 'asset': remote.releases[0]['assets'][0]['id'] += 9999
                        else: remote.releases[0]['assets'].append(dict(remote.releases[0]['assets'][0],
                            id=9999, name=t._prefix('batch-0')+'extra'))
                with patch.object(remote, 'download', side_effect=download), self.assertRaises(ValueError):
                    self.fetch_batch(['batch-0','batch-1'], allow_failed=True)
                self.assertFalse((self.root/'batch-0').exists()); self.assertFalse((self.root/'batch-1').exists())

    def test_unrelated_job_progress_and_partial_asset_do_not_change_selected_scope(self):
        self.publish_batch(self.requests(2)); self.remote.complete()
        self.remote.jobs.append(dict(self.remote.jobs[0], id=31, name='unrelated', status='in_progress', conclusion=None))
        self.remote.on_download = lambda: (self.remote.jobs[1].update(status='completed', conclusion='failure'),
            self.remote.releases[0]['assets'].append(dict(id=9999,name=t._prefix('unrelated')+'uploading',state='starter')))
        self.assertEqual(2, len(self.fetch_batch(['batch-0','batch-1'])))

    def test_each_bundle_enforces_its_exact_producer_and_failure_policy(self):
        self.publish_batch(self.requests(2)); self.remote.complete('failure')
        requests = [dict(name='batch-0',output=self.root/'batch-0',allow_failed=True),
                    dict(name='batch-1',output=self.root/'batch-1',allow_failed=False)]
        with self.assertRaisesRegex(ValueError,'completion'):
            t.fetch_bundles(**self.common(),requests=requests,transport=self.remote)
        self.assertFalse((self.root/'batch-0').exists())
        self.remote.complete()
        requests[1]['job_id'] = 31
        with self.assertRaisesRegex(ValueError,'producer differs'):
            t.fetch_bundles(**self.common(),requests=requests,transport=self.remote)
        self.assertFalse((self.root/'batch-0').exists())

    def test_invalid_duplicate_and_overlapping_requests_fail_before_remote_io(self):
        for requests in ([], [dict(name='a',output=self.root/'a'),dict(name='a',output=self.root/'b')],
                         [dict(name='a',output=self.root/'a'),dict(name='b',output=self.root/'a'/'b')],
                         [dict(name='a',output=self.root/'a',unknown=True)],
                         [dict(name='a',output=self.root/'a',job_id=True)]):
            with self.subTest(requests=requests), self.assertRaises(ValueError):
                t.fetch_bundles(**self.common(),requests=requests,transport=self.remote)
        self.assertEqual([],self.remote.calls)

    def test_batch_uploads_use_only_the_validated_release_id(self):
        observed = []
        def upload_to(identity, path):
            observed.append(identity)
            self.remote.upload('ci-12-attempt-2', path)
        self.remote.upload_to = upload_to
        self.publish_batch()
        self.assertEqual([9]*16, observed)

    def test_uncertain_payload_upload_never_commits_any_manifest_and_retries_exactly(self):
        self.remote.lose_upload = True
        with self.assertRaises(t.delivery.DeliveryError) as failed: self.publish_batch()
        self.assertTrue(failed.exception.uncertain)
        self.assertFalse(any(row['name'].startswith('bundle-') for row in self.remote.releases[0]['assets']))
        self.publish_batch(); self.remote.complete(); self.assertEqual(8,len(self.fetch_batch()))


class FastTransportTests(unittest.TestCase):
    setUp = TransportTests.setUp
    publish = TransportTests.publish
    fetch = TransportTests.fetch
    common = BatchTransportTests.common
    requests = BatchTransportTests.requests
    publish_batch = BatchTransportTests.publish_batch
    fetch_batch = BatchTransportTests.fetch_batch
    reads = BatchTransportTests.reads

    def environment(self, *, artifacts=False):
        value = dict(GITHUB_ACTIONS='true', GITHUB_REPOSITORY='example/project', GITHUB_RUN_ID='12',
                     GITHUB_RUN_ATTEMPT='2', GITHUB_SHA='a'*40,
                     GITHUB_WORKFLOW_REF='example/project/.github/workflows/sdk-maintenance.yml@refs/heads/main')
        if artifacts: value['FOUNDATION_CI_ARTIFACTS_DIR'] = str(self.root/'downloaded')
        return value

    def local(self, context, request, output):
        output.mkdir(); (output/'file').write_text(request['name'])
        return dict(pointer=dict(name=request['name'], kind='actions-ci-evidence'),
                    manifest=dict(files={'file': {}}, metadata={}),
                    producer=dict(kind='workflow-needs', trust_basis='same-run-actions-context-and-workflow-needs',
                                  job_key='produce', runner_name='Runner 1', conclusion='success'))

    def test_same_run_gate_requires_every_exact_actions_context_field(self):
        environment = self.environment()
        with patch.dict(os.environ, environment, clear=True): self.assertTrue(t._same_run(self.context))
        for key in environment:
            with self.subTest(field=key), patch.dict(os.environ, dict(environment, **{key:'different'}), clear=True):
                self.assertFalse(t._same_run(self.context))
        with patch.dict(os.environ, {}, clear=True): self.assertFalse(t._same_run(self.context))

    def test_cross_run_ignores_current_workflow_artifacts_and_keeps_strict_checks(self):
        self.publish_batch(self.requests(2)); self.remote.complete(); self.remote.calls.clear()
        environment = dict(self.environment(artifacts=True), GITHUB_RUN_ID='99')
        with patch.dict(os.environ, environment, clear=True), \
                patch.dict(sys.modules, {'ci_artifacts':SimpleNamespace(fetch_local=lambda *args:self.fail('cross-run local read'))}):
            self.assertEqual(2, len(self.fetch_batch(['batch-0','batch-1'])))
        self.assertEqual(12, len(self.reads()))

    def test_native_provenance_does_not_invent_numeric_job_ids(self):
        self.remote.complete(); self.remote.jobs.append(dict(self.remote.jobs[0], id=31))
        with patch.dict(os.environ, self.environment(artifacts=True), clear=True), \
                patch.dict(sys.modules, {'ci_artifacts':SimpleNamespace(fetch_local=self.local)}):
            receipts = self.fetch_batch(['batch-0'])
        self.assertEqual('workflow-needs', receipts[0]['producer']['kind'])
        self.assertNotIn('id', receipts[0]['producer']); self.assertEqual([], self.remote.calls)

    def test_same_run_release_batches_reduce_reads_and_pin_selected_release(self):
        with patch.dict(os.environ, self.environment(), clear=True):
            pointers = self.publish_batch()
            self.assertEqual(12, len(self.reads()))  # Includes initial draft creation reads.
            self.remote.calls.clear(); self.assertEqual(pointers, self.publish_batch())
            self.assertEqual(10, len(self.reads()))
            self.remote.complete(); self.remote.calls.clear()
            self.assertEqual(pointers, [r['pointer'] for r in self.fetch_batch()])
            self.assertEqual(9, len(self.reads()))
            self.assertEqual(1, sum(call[1].endswith('/releases?per_page=100') for call in self.reads()))
            self.assertEqual(1, sum(call[1].endswith('/releases/9') for call in self.reads()))
            self.assertEqual(1, sum('/jobs?per_page=' in call[1] for call in self.reads()))

    def test_same_run_still_rejects_changed_release_tag_and_payload_identity(self):
        for change in ('tag', 'release', 'asset', 'extra', 'bytes'):
            with self.subTest(change=change), patch.dict(os.environ, self.environment(), clear=True):
                self.remote = FakeGitHub(); self.publish_batch(self.requests(2)); self.remote.complete()
                if change == 'bytes':
                    row = self.remote.releases[0]['assets'][0]; self.remote.data[row['id']] = b'tampered'
                else:
                    def mutate():
                        if change == 'tag': self.remote.refs['ci-12-attempt-2'] = 'b'*40
                        elif change == 'release': self.remote.releases[0]['draft'] = False
                        elif change == 'asset': self.remote.releases[0]['assets'][0]['id'] += 9999
                        else: self.remote.releases[0]['assets'].append(dict(self.remote.releases[0]['assets'][0],
                            id=9999, name=t._prefix('batch-0')+'extra'))
                    self.remote.on_download = mutate
                with self.assertRaises(ValueError): self.fetch_batch(['batch-0','batch-1'])
                self.assertFalse((self.root/'batch-0').exists()); self.assertFalse((self.root/'batch-1').exists())

    def test_eight_native_artifacts_need_zero_provenance_or_release_requests(self):
        with patch.dict(os.environ, self.environment(artifacts=True), clear=True), \
                patch.dict(sys.modules, {'ci_artifacts':SimpleNamespace(fetch_local=self.local)}), \
                patch.object(t, '_run', side_effect=AssertionError('unexpected REST run query')), \
                patch.object(t, '_jobs', side_effect=AssertionError('unexpected REST jobs query')):
            receipts = self.fetch_batch()
        self.assertEqual([], self.remote.calls)
        self.assertEqual(['workflow-needs']*8, [r['producer']['kind'] for r in receipts])
        for request in self.requests():
            self.assertEqual(request['name'], (self.root/request['name']/'file').read_text())

    def test_invalid_local_artifact_never_falls_back_or_publishes_other_outputs(self):
        def local(context, request, output):
            if request['name'] == 'batch-1': raise ValueError('invalid artifact digest')
            return self.local(context, request, output)
        with patch.dict(os.environ, self.environment(artifacts=True), clear=True), \
                patch.dict(sys.modules, {'ci_artifacts':SimpleNamespace(fetch_local=local)}), \
                self.assertRaisesRegex(ValueError, 'invalid artifact'):
            self.fetch_batch(['batch-0','batch-1'])
        self.assertFalse(self.remote.calls)
        self.assertFalse((self.root/'batch-0').exists()); self.assertFalse((self.root/'batch-1').exists())
        self.assertFalse(list(self.root.glob('.foundation-ci-input-*')))

    def test_native_producer_outcome_is_preserved_and_failed_consumption_is_explicit(self):
        import ci_artifacts
        for index, outcome in enumerate(('success', 'failure', 'cancelled')):
            with self.subTest(outcome=outcome):
                downloaded = self.root / ('downloaded-' + str(index)); downloaded.mkdir()
                name = 'certificate-2'; context = dict(self.context, name=name)
                ci_artifacts.prepare(**context, root=self.source, paths=['folder'],
                    output=downloaded/ci_artifacts.artifact_name(context, ci_artifacts.slot_for(name, 2)),
                    runner_name='Runner 1', job_key='produce', outcome=outcome)
                environment = dict(self.environment(artifacts=True), FOUNDATION_CI_ARTIFACTS_DIR=str(downloaded))
                with patch.dict(os.environ, environment, clear=True):
                    if outcome != 'success':
                        with self.assertRaisesRegex(ValueError, 'failed native producer'): self.fetch_batch([name])
                        self.assertFalse((self.root/name).exists())
                    receipt = self.fetch_batch([name], allow_failed=outcome != 'success')[0]
                self.assertEqual(outcome, receipt['producer']['conclusion'])
                self.assertEqual('same-run-actions-context-and-workflow-needs', receipt['producer']['trust_basis'])
                import shutil
                shutil.rmtree(self.root/name)
        self.assertEqual([], self.remote.calls)

    def test_absent_local_artifact_falls_back_and_mixed_failure_publishes_nothing(self):
        self.publish_batch(self.requests(2)); self.remote.complete(); self.remote.calls.clear()
        def local(context, request, output):
            return self.local(context, request, output) if request['name'] == 'batch-0' else None
        bad = next(row for row in self.remote.releases[0]['assets'] if row['name'].startswith(t._prefix('batch-1')))
        self.remote.data[bad['id']] = b'corrupt'
        with patch.dict(os.environ, dict(self.environment(artifacts=True), FOUNDATION_CI_ARTIFACT_RELEASE_FALLBACK='true'), clear=True), \
                patch.dict(sys.modules, {'ci_artifacts':SimpleNamespace(fetch_local=local)}), \
                self.assertRaisesRegex(ValueError, 'downloaded asset'):
            self.fetch_batch(['batch-0','batch-1'])
        self.assertFalse((self.root/'batch-0').exists()); self.assertFalse((self.root/'batch-1').exists())
        self.assertTrue(any(call[0] == 'download' for call in self.remote.calls))

    def test_real_native_roundtrip_validates_hashes_and_context_without_rest(self):
        import ci_artifacts
        downloaded = self.root/'downloaded'; downloaded.mkdir()
        names = ['qualification-inputs-2', 'certificate-2']
        for name in names:
            context = dict(self.context, name=name)
            slot = ci_artifacts.slot_for(name, 2)
            result = ci_artifacts.prepare(**context, root=self.source, paths=['folder','tool'],
                output=downloaded/ci_artifacts.artifact_name(context, slot), runner_name='Runner 1', job_key='produce')
            self.assertEqual('actions', result['transport'])
        with patch.dict(os.environ, self.environment(artifacts=True), clear=True):
            with self.assertRaisesRegex(ValueError, 'REST producer pins'):
                self.fetch_batch(names, job_name='produce (linux-aarch64)', job_id=30)
            receipts = self.fetch_batch(names)
        self.assertEqual([], self.remote.calls)
        self.assertEqual(['produce','produce'], [receipt['producer']['job_key'] for receipt in receipts])
        self.assertTrue(all(receipt['pointer']['transport'] == 'actions' for receipt in receipts))
        for name in names:
            self.assertEqual((self.source/'tool').read_bytes(), (self.root/name/'tool').read_bytes())

    def test_real_corrupt_artifact_cannot_use_an_available_release_fallback(self):
        import ci_artifacts
        name = 'qualification-inputs-2'; self.publish(name=name); self.remote.complete(); self.remote.calls.clear()
        context = dict(self.context, name=name); downloaded = self.root/'downloaded'; downloaded.mkdir()
        staged = downloaded/ci_artifacts.artifact_name(context, ci_artifacts.slot_for(name, 2))
        ci_artifacts.prepare(**context, root=self.source, paths=['folder'], output=staged, runner_name='Runner 1', job_key='produce')
        (staged/'payload.tar.gz').write_bytes(b'corrupt')
        with patch.dict(os.environ, self.environment(artifacts=True), clear=True), \
                self.assertRaisesRegex(ValueError, 'artifact archive bytes'):
            self.fetch_batch([name])
        self.assertEqual([], self.remote.calls)
        self.assertFalse((self.root/name).exists())

    def test_absent_native_artifact_requires_explicit_legacy_fallback(self):
        self.publish_batch(self.requests(2)); self.remote.complete(); self.remote.calls.clear()
        with patch.dict(os.environ, self.environment(artifacts=True), clear=True), \
                patch.dict(sys.modules, {'ci_artifacts':SimpleNamespace(fetch_local=lambda *args:None)}):
            with self.assertRaisesRegex(ValueError, 'release relay is not enabled'):
                self.fetch_batch(['batch-0','batch-1'])
            self.assertEqual([], self.remote.calls)
            with patch.dict(os.environ, {'FOUNDATION_CI_ARTIFACT_RELEASE_FALLBACK':'true'}):
                receipts = self.fetch_batch(['batch-0','batch-1'])
        self.assertEqual(2, len(receipts)); self.assertEqual(9, len(self.reads()))
        self.assertFalse(list(self.root.glob('.foundation-ci-input-*')))

    def test_required_native_mode_rejects_missing_download_setup(self):
        environment = dict(self.environment(), FOUNDATION_CI_ARTIFACTS_REQUIRED='true')
        with patch.dict(os.environ, environment, clear=True), self.assertRaisesRegex(ValueError, 'directory is missing'):
            self.fetch_batch(['batch-0'])
        self.assertEqual([], self.remote.calls)


if __name__ == '__main__': unittest.main()
