"""Offline lifecycle scenarios: no live GitHub authentication or remote writes."""
import copy
import importlib.util
import io
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest import mock

ROOT=Path(__file__).resolve().parents[1]
SPEC=importlib.util.spec_from_file_location('github_delivery',ROOT/'tools/github_release.py')
G=importlib.util.module_from_spec(SPEC);SPEC.loader.exec_module(G)
import test_release as release_fixtures
import test_rust_sdk as rust_fixtures


class FakeGitHub:
    _lock=threading.RLock()
    def __init__(self, *, first_normal_latest=False):
        self.first_normal_latest=first_normal_latest
        self.releases=[];self.refs={};self.data={};self.next_id=1;self.next_asset=100
        self.latest=None;self.calls=[];self.fail_upload=None;self.change_download=None;self.private=True

    @property
    def mutations(self):
        return [x for x in self.calls if x[0] in ('POST','PATCH','DELETE','upload')]

    def json(self,endpoint,method='GET',body=None,missing=False):
        self.calls.append((method,endpoint,copy.deepcopy(body)))
        prefix='repos/example/project'
        if endpoint==prefix:return {'full_name':'example/project','private':self.private}
        path=endpoint[len(prefix):]
        if path.startswith('/git/ref/tags/'):
            value=self.refs.get(path.removeprefix('/git/ref/tags/'))
            if value is None:
                if missing:return None
                raise G.DeliveryError('missing tag')
            return {'object':{'type':'commit','sha':value}}
        if path=='/git/refs' and method=='POST':
            tag=body['ref'].removeprefix('refs/tags/')
            if tag in self.refs:raise G.DeliveryError('tag exists')
            self.refs[tag]=body['sha'];return {'object':{'type':'commit','sha':body['sha']}}
        if path.startswith('/releases/tags/') and method=='GET':
            tag=path.removeprefix('/releases/tags/')
            found=next((r for r in self.releases if G.quote(r['tag_name'],safe='')==tag and not r['draft']),None)
            if found is None and missing:return None
            if found is None:raise G.DeliveryError('published release missing')
            return copy.deepcopy(found)
        if path.startswith('/releases/') and path.removeprefix('/releases/').isdecimal() and method=='GET':
            found=next((r for r in self.releases if r['id']==int(path.rsplit('/',1)[1])),None)
            if found is None and missing:return None
            if found is None:raise G.DeliveryError('release ID missing')
            return copy.deepcopy(found)
        if path=='/releases/latest':
            found=next((r for r in self.releases if r['id']==self.latest),None)
            if found is None and self.latest is None and self.first_normal_latest:
                # GitHub can return its first published ordinary release even
                # when that release was created with make_latest=false.
                found=next((r for r in self.releases if not r['draft'] and not r['prerelease']),None)
            if found:return copy.deepcopy(found)
            if missing:return None
            raise G.DeliveryError('Latest missing')
        if path=='/releases' and method=='POST':
            row=dict(body,id=self.next_id,assets=[]);self.next_id+=1;self.releases.append(row)
            return copy.deepcopy(row)
        if path.startswith('/releases/assets/') and method=='DELETE':
            aid=int(path.rsplit('/',1)[1])
            row=next(r for r in self.releases if any(a['id']==aid for a in r['assets']))
            row['assets']=[a for a in row['assets'] if a['id']!=aid];self.data.pop(aid)
            return None
        if path.startswith('/releases/') and method=='PATCH':
            rid=int(path.rsplit('/',1)[1]);row=next(r for r in self.releases if r['id']==rid)
            row.update(body)
            if body.get('make_latest')=='true':self.latest=rid
            return copy.deepcopy(row)
        raise AssertionError((method,endpoint,body))

    def pages(self,endpoint):
        self.calls.append(('pages',endpoint))
        if endpoint.endswith('/releases?per_page=100'):return copy.deepcopy(self.releases)
        rid=int(endpoint.split('/releases/')[1].split('/')[0])
        return copy.deepcopy(next(r for r in self.releases if r['id']==rid)['assets'])

    def upload(self,tag,path):
        with self._lock:
            self.calls.append(('upload',tag,Path(path).name))
            row=next(r for r in self.releases if r['tag_name']==tag)
            if any(a['name']==Path(path).name for a in row['assets']):raise G.DeliveryError('asset exists')
            value=Path(path).read_bytes();asset={'id':self.next_asset,'name':Path(path).name,'state':'uploaded',
                                            'size':len(value),'digest':'sha256:'+G.sha(value)}
            self.next_asset+=1;self.data[asset['id']]=value;row['assets'].append(asset)
            if self.fail_upload==asset['name']:raise G.DeliveryError('injected response loss after upload')

    def download(self,asset_id,path):
        with self._lock:
            self.calls.append(('download',asset_id))
            data=self.data[asset_id]
            callback=self.change_download;self.change_download=None
        Path(path).write_bytes(data)
        if callback:callback()

    def replace_asset(self,name,value=None):
        row=next(r for r in self.releases if any(a['name']==name for a in r['assets']))
        asset=next(a for a in row['assets'] if a['name']==name)
        value=self.data[asset['id']] if value is None else value
        asset.update(id=self.next_asset,size=len(value),digest='sha256:'+G.sha(value));self.next_asset+=1
        self.data[asset['id']]=value


class RustBaseTests(unittest.TestCase):
    def setUp(self):
        self.fixture = rust_fixtures.RustSdkTests()
        self.fixture.setUp(); self.addCleanup(self.fixture.doCleanups)
        self.root = self.fixture.work
        self.remote = FakeGitHub()
        self.recipe, self.group = self.group_fixture()

    def group_fixture(self, suffix=''):
        original_work = self.fixture.work
        if suffix:
            self.fixture.work = self.root / suffix; self.fixture.work.mkdir()
        try:
            tree, sources, data = self.fixture.sdk()
            if suffix:
                helper = sources / 'tools' / G.rust_sdk.TOOLS[0]
                helper.write_text(helper.read_text() + suffix)
                source_data = G.archive.read_json(sources / 'sources.json')
                files = G.archive.file_inventory(sources, exclude=('sources.json',))
                names = ['recipe/rust.json'] + ['tools/' + name for name in G.rust_sdk.TOOLS]
                identity = G.sha(G.archive.encoded({name: files[name] for name in names}))
                source_data.update(recipe_id=identity, files=files)
                G.archive.write_json(sources / 'sources.json', source_data)
                data.update(recipe_id=identity, sources_sha256=G.archive.digest(sources / 'sources.json'))
                G.archive.write_json(tree / 'rust-sdk.json', data)
            group = self.fixture.work / 'group'
            G.rust_sdk.export_group(tree, sources, group)
            return data['recipe_id'], group
        finally:
            self.fixture.work = original_work

    def publish(self, **changes):
        return G.publish_rust_base('example/project', self.recipe, self.group, 'a' * 40,
                                   transport=self.remote, **changes)

    def test_rust_plan_validates_complete_sources_without_remote_reads(self):
        result = self.publish()
        self.assertFalse(result['execute'])
        self.assertEqual(result['operation'], 'publish-rust-base')
        self.assertEqual(result['files'], G.rust_sdk.verify_group(self.group, self.recipe))
        self.assertFalse(self.remote.calls)

    def test_rust_publish_fetch_and_reuse_preserve_complete_group(self):
        self.assertFalse(self.publish(execute=True)['reused'])
        names = G.rust_sdk.group_names(self.recipe)
        uploads = [call[2] for call in self.remote.calls if call[0] == 'upload']
        self.assertCountEqual(uploads, names); self.assertEqual(uploads[-1], names[-1])
        finalization = max(index for index, call in enumerate(self.remote.calls) if call[0] == 'PATCH')
        self.assertEqual(sum(call[0] == 'download' for call in self.remote.calls[:finalization]), 3)
        self.assertFalse(self.remote.releases[0]['draft'])
        self.assertTrue(self.remote.releases[0]['prerelease']); self.assertIsNone(self.remote.latest)
        self.remote.calls.clear()
        output = self.root / 'fetched'
        result = G.fetch_rust_base('example/project', self.recipe, output, transport=self.remote)
        expected = G.rust_sdk.verify_group(self.group, self.recipe)
        self.assertEqual(result, dict(fetched=True, recipe=self.recipe, files=expected, payload='complete'))
        self.assertEqual(G.rust_sdk.verify_group(output, self.recipe), expected)
        self.assertEqual(sum(call[0] == 'download' for call in self.remote.calls), 3)
        self.remote.calls.clear()
        self.assertTrue(self.publish(execute=True)['reused'])
        self.assertFalse(self.remote.mutations)
        self.assertFalse(any(call[0] == 'download' for call in self.remote.calls))

    def test_rust_append_preserves_existing_cpp_group_and_base_tag(self):
        recipe = 'b' * 64
        _, _, _, group = release_fixtures.fixture(self.root / 'cpp', recipe=recipe)
        G.publish_base('example/project', recipe, group, 'b' * 40, execute=True, transport=self.remote)
        before = copy.deepcopy(self.remote.releases[0]['assets'])
        self.publish(execute=True)
        self.assertEqual(self.remote.refs['base'], 'b' * 40)
        self.assertEqual(self.remote.releases[0]['assets'][:3], before)
        self.assertEqual(len(self.remote.releases[0]['assets']), 6)
        G.fetch_base('example/project', recipe, self.root / 'cpp-fetched', transport=self.remote)
        self.assertEqual(G.store.verify_group(self.root / 'cpp-fetched', recipe),
                         G.store.verify_group(group, recipe))

    def test_rust_batch_fetch_uses_one_inventory_for_distinct_complete_groups(self):
        recipe, group = self.group_fixture('second')
        self.publish(execute=True)
        # Historical inventories may contain several recipes for the same slot.
        for name in G.rust_sdk.group_names(recipe): self.remote.upload('base', group / name)
        self.remote.calls.clear()
        output = self.root / 'batch'
        result = G.fetch_rust_bases('example/project', [self.recipe, recipe], output,
                                   transport=self.remote)
        for identity, source in ((self.recipe, self.group), (recipe, group)):
            expected = G.rust_sdk.verify_group(source, identity)
            self.assertEqual(result[identity]['files'], expected)
            self.assertEqual(G.rust_sdk.verify_group(output / identity, identity), expected)
            self.assertEqual(result[identity]['payload'], 'complete')
        self.assertEqual(sum(call[0] in ('GET', 'pages') for call in self.remote.calls), 7)
        self.assertEqual(sum(call[0] == 'download' for call in self.remote.calls), 6)

    def test_new_rust_publication_retires_the_previous_complete_slot(self):
        self.publish(execute=True)
        before = copy.deepcopy(self.remote.releases[0]['assets'])
        recipe, group = self.group_fixture('replacement')
        result = G.publish_rust_base('example/project', recipe, group, 'b' * 40,
                                    execute=True, transport=self.remote)
        self.assertEqual({row['id'] for row in result['removed_assets'].values()}, {row['id'] for row in before})
        self.assertEqual({row['name'] for row in self.remote.releases[0]['assets']}, set(G.rust_sdk.names(recipe)))
        self.assertEqual(self.remote.refs['base'], 'a' * 40)
        G.fetch_rust_base('example/project', recipe, self.root / 'replacement-fetched', transport=self.remote)

    def test_rust_has_no_binary_only_fetch_shortcut(self):
        with self.assertRaises(TypeError):
            G.fetch_rust_base('example/project', self.recipe, self.root / 'binary',
                              transport=self.remote, binary_only=True)
        with self.assertRaises(TypeError):
            G.fetch_rust_bases('example/project', [self.recipe], self.root / 'binaries',
                               transport=self.remote, binary_only=True)
        self.assertFalse(self.remote.calls)

    def test_invalid_rust_selection_and_existing_output_fail_before_remote_reads(self):
        output = self.root / 'existing'; output.mkdir(); (output / 'keep').write_text('retained')
        for recipes in ([], self.recipe, [None], ['../bad'], [self.recipe, self.recipe]):
            with self.subTest(recipes=recipes), self.assertRaises(ValueError):
                G.fetch_rust_bases('example/project', recipes, self.root / 'invalid', transport=self.remote)
        with self.assertRaises(ValueError):
            G.fetch_rust_base('example/project', self.recipe, output, transport=self.remote)
        self.assertEqual((output / 'keep').read_text(), 'retained'); self.assertFalse(self.remote.calls)

    def test_incomplete_or_altered_local_rust_group_prevents_remote_reads(self):
        source = self.group / G.rust_sdk.group_names(self.recipe)[1]
        original = source.read_bytes(); source.unlink()
        with self.assertRaisesRegex(ValueError, 'exactly'):
            self.publish(execute=True)
        source.write_bytes(original + b'altered')
        with self.assertRaisesRegex(ValueError, 'checksum mismatch'):
            self.publish(execute=True)
        self.assertFalse(self.remote.calls)

    def test_wrong_matched_archive_identity_is_rejected_despite_valid_checksums(self):
        recipe, group = self.group_fixture('different-recipe')
        binary, source, sums = G.rust_sdk.group_names(self.recipe)
        for destination, name in zip((binary, source), G.rust_sdk.group_names(recipe)[:2]):
            (self.group / destination).write_bytes((group / name).read_bytes())
        (self.group / sums).write_text(''.join(G.archive.digest(self.group / name) + '  ' + name + '\n'
                                             for name in (binary, source)))
        with self.assertRaisesRegex(ValueError, 'recipe identity mismatch'):
            self.publish(execute=True)
        self.assertFalse(self.remote.calls)

    def test_partial_remote_rust_group_never_overwrites_or_downloads(self):
        self.publish(execute=True)
        self.remote.releases[0]['assets'].pop(); self.remote.calls.clear()
        with self.assertRaisesRegex(ValueError, 'partial existing'):
            self.publish(execute=True)
        output = self.root / 'incomplete'
        with self.assertRaisesRegex(ValueError, 'exact complete'):
            G.fetch_rust_base('example/project', self.recipe, output, transport=self.remote)
        self.assertFalse(output.exists()); self.assertFalse(self.remote.mutations)
        self.assertFalse(any(call[0] == 'download' for call in self.remote.calls))

    def test_altered_remote_rust_source_rejects_fetch_and_immutable_reuse(self):
        self.publish(execute=True)
        self.remote.replace_asset(G.rust_sdk.group_names(self.recipe)[1], b'changed compiler sources')
        self.remote.calls.clear(); output = self.root / 'changed'
        with self.assertRaisesRegex(ValueError, 'checksum mismatch'):
            G.fetch_rust_base('example/project', self.recipe, output, transport=self.remote)
        with self.assertRaisesRegex(ValueError, 'immutable group conflicts'):
            self.publish(execute=True)
        self.assertFalse(output.exists()); self.assertFalse(list(self.root.glob('.base-fetch-*')))
        self.assertFalse(self.remote.mutations)

    def test_rust_snapshot_identity_drift_never_exposes_output(self):
        self.publish(execute=True)
        original = copy.deepcopy(self.remote.releases[0]); references = dict(self.remote.refs)
        changes = (lambda: self.remote.refs.update(base='b' * 40),
                   lambda: self.remote.replace_asset(G.rust_sdk.group_names(self.recipe)[1]),
                   lambda: self.remote.releases[0].update(prerelease=False))
        for index, change in enumerate(changes):
            with self.subTest(change=index):
                self.remote.releases[0] = copy.deepcopy(original); self.remote.refs = dict(references)
                self.remote.change_download = change; output = self.root / ('drift-' + str(index))
                with self.assertRaises(ValueError):
                    G.fetch_rust_base('example/project', self.recipe, output, transport=self.remote)
                self.assertFalse(output.exists()); self.assertFalse(list(self.root.glob('.base-fetch-*')))

    def test_rust_payload_failure_prevents_checksum_marker_and_publication(self):
        binary, _, checksum = G.rust_sdk.group_names(self.recipe)
        self.remote.fail_upload = binary
        with self.assertRaises(G.DeliveryError) as caught:
            self.publish(execute=True)
        self.assertTrue(caught.exception.uncertain); self.assertTrue(self.remote.releases[0]['draft'])
        self.assertNotIn(checksum, [call[2] for call in self.remote.calls if call[0] == 'upload'])
        self.assertFalse(any(call[0] == 'PATCH' for call in self.remote.mutations))

    def test_rust_cli_plan_and_fetch_use_the_explicit_rust_api(self):
        request = self.root / 'request.json'
        G.archive.write_json(request, dict(repository='example/project', recipe=self.recipe,
                                           group=str(self.group), source_commit='a' * 40))
        result = subprocess.run([sys.executable, '-B', str(ROOT / 'tools/github_release.py'),
                                 'publish-rust-base', '--input', str(request)], cwd=ROOT,
                                check=True, capture_output=True, text=True)
        self.assertEqual(json.loads(result.stdout)['operation'], 'publish-rust-base')
        G.archive.write_json(request, dict(repository='example/project', recipe=self.recipe,
                                           output=str(self.root / 'cli-fetch')))
        with mock.patch.object(G, 'fetch_rust_base', return_value={'fetched': True}) as fetch, \
                mock.patch('sys.stdout', new_callable=io.StringIO):
            self.assertEqual(G.main(['fetch-rust-base', '--input', str(request)]), 0)
        fetch.assert_called_once_with(repository='example/project', recipe=self.recipe,
                                      output=str(self.root / 'cli-fetch'))


class PublicFakeGitHub(FakeGitHub):
    def __init__(self, **kwargs):
        super().__init__(**kwargs); self.private=False

    def download_public(self,url,path,size,digest):
        expected='https://github.com/example/project/releases/download/'
        assert url.startswith(expected)
        from urllib.parse import unquote
        tag,name=map(unquote,url[len(expected):].split('/'))
        row=next(r for r in self.releases if r['tag_name']==tag and not r['draft'])
        asset=next(a for a in row['assets'] if a['name']==name)
        self.calls.append(('public-download',asset['id']))
        Path(path).write_bytes(self.data[asset['id']])
        callback=self.change_download;self.change_download=None
        if callback:callback()


class BaseRetirementTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(); self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name); self.remote = FakeGitHub()
        self.old = self.group('a'); self.new = self.group('b')

    def group(self, digit, *, capabilities=None, processor='x86_64', kind='source-build'):
        recipe, tree, _, group = release_fixtures.fixture(self.root / digit, recipe=digit * 64)
        metadata = G.archive.read_json(tree / 'sdk.json')
        metadata.update(kind=kind, capabilities=capabilities or ['core', 'terminal', 'framebuffer', 'hosted-web'])
        metadata['host']['processor'] = metadata['target']['processor'] = processor
        metadata['target']['triple'] = processor + '-linux-gnu'
        G.archive.write_json(tree / 'sdk.json', metadata)
        binary, _, checksum = G.store.names(recipe)
        (group / binary).unlink()
        G.archive.archive_tree(tree, group / binary)
        (group / checksum).unlink(); G.store.create_sums(group, recipe)
        return recipe, group

    def publish(self, item, *, execute=True):
        recipe, group = item
        return G.publish_base('example/project', recipe, group, 'a' * 40,
                              execute=execute, transport=self.remote)

    def deletions(self):
        return [call for call in self.remote.calls if call[0] == 'DELETE']

    def test_retires_only_verified_matching_slot_and_preserves_application_copies(self):
        self.publish(self.old)
        old = {row['name']: copy.deepcopy(row) for row in self.remote.releases[0]['assets']}
        self.publish(self.group('c', capabilities=['core', 'fltk', 'sdl', 'rev']))
        self.publish(self.group('d', processor='aarch64'))
        self.publish(self.group('e', kind='diagnostic'))
        # Other namespaces and incomplete historical groups stay untouched.
        for name in ('README.txt', 'rust-sdk-' + 'f' * 64 + '-SHA256SUMS', G.store.names('f' * 64)[0]):
            path = self.root / name; path.write_bytes(b'retained'); self.remote.upload('base', path)
        self.remote.json('repos/example/project/releases', method='POST',
                         body=dict(tag_name='v1', name='v1', draft=False, prerelease=False))
        for name in G.store.names(self.old[0]): self.remote.upload('v1', self.old[1] / name)
        self.remote.latest = 2
        application = copy.deepcopy(self.remote.releases[1]); preserved = {
            row['name']: copy.deepcopy(row) for row in self.remote.releases[0]['assets'] if row['name'] not in old}
        result = self.publish(self.new)
        self.assertEqual(result['removed_assets'], old)
        self.assertEqual(self.remote.releases[1], application)
        self.assertEqual(self.remote.latest, 2); self.assertEqual(self.remote.refs['base'], 'a' * 40)
        remaining = {row['name']: row for row in self.remote.releases[0]['assets']}
        self.assertTrue(all(remaining[name] == row for name, row in preserved.items()))
        self.assertTrue(set(G.store.names(self.new[0])) <= remaining.keys())
        checksum = G.store.names(self.old[0])[-1]
        self.assertEqual(self.deletions()[0][1].rsplit('/', 1)[-1], str(old[checksum]['id']))
        ids = {row['id']: row['name'] for row in old.values()}
        downloaded = {ids[call[1]] for call in self.remote.calls if call[0] == 'download' and call[1] in ids}
        self.assertEqual(downloaded, set(old))

    def test_plans_and_exact_reuse_do_not_delete_historical_groups(self):
        self.assertFalse(self.publish(self.new, execute=False)['execute']); self.assertFalse(self.remote.calls)
        self.publish(self.new)
        for name in G.store.names(self.old[0]): self.remote.upload('base', self.old[1] / name)
        before = copy.deepcopy(self.remote.releases[0]); self.remote.calls.clear()
        self.assertTrue(self.publish(self.new)['reused'])
        self.assertEqual(self.remote.releases[0], before); self.assertFalse(self.remote.mutations)
        self.assertFalse(any(call[0] == 'download' for call in self.remote.calls))

    def test_malformed_binary_source_and_checksums_are_preserved(self):
        for name in G.store.names(self.old[0]):
            with self.subTest(member=name):
                self.remote = FakeGitHub(); self.publish(self.old)
                self.remote.replace_asset(name, b'invalid retained bytes')
                old = copy.deepcopy(self.remote.releases[0]['assets'])
                result = self.publish(self.new)
                self.assertEqual(result['removed_assets'], {}); self.assertFalse(self.deletions())
                self.assertEqual(self.remote.releases[0]['assets'][:3], old)

    def test_failed_new_upload_preserves_all_old_groups(self):
        self.publish(self.old); old = copy.deepcopy(self.remote.releases[0]['assets'])
        self.remote.fail_upload = G.store.names(self.new[0])[0]
        with self.assertRaises(G.DeliveryError): self.publish(self.new)
        self.assertEqual(self.remote.releases[0]['assets'][:3], old); self.assertFalse(self.deletions())

    def test_cleanup_reconciles_the_complete_inventory_before_any_deletion(self):
        self.publish(self.old); old_binary = G.store.names(self.old[0])[0]
        old_id = next(row['id'] for row in self.remote.releases[0]['assets'] if row['name'] == old_binary)
        original = self.remote.download
        def drift(identity, path):
            original(identity, path)
            if identity == old_id: self.remote.replace_asset(G.store.names(self.old[0])[1])
        self.remote.download = drift
        with self.assertRaisesRegex(G.DeliveryError, 'identities changed') as caught: self.publish(self.new)
        self.assertTrue(caught.exception.uncertain); self.assertFalse(self.deletions())

    def test_uncertain_delete_stops_after_the_checksum_without_replay(self):
        self.publish(self.old); original = self.remote.json
        def lose_response(endpoint, method='GET', body=None, missing=False):
            result = original(endpoint, method, body, missing)
            if method == 'DELETE': raise G.DeliveryError('injected deletion response loss')
            return result
        self.remote.json = lose_response
        with self.assertRaises(G.DeliveryError) as caught: self.publish(self.new)
        self.assertTrue(caught.exception.uncertain); self.assertEqual(len(self.deletions()), 1)
        remaining = {row['name'] for row in self.remote.releases[0]['assets']}
        binary, source, checksum = G.store.names(self.old[0])
        self.assertTrue({binary, source} <= remaining); self.assertNotIn(checksum, remaining)
        self.assertTrue(set(G.store.names(self.new[0])) <= remaining)

    def test_cleanup_inventory_limit_fails_before_deleting_old_groups(self):
        self.publish(self.old)
        with mock.patch.object(G, 'BASE_CLEANUP_GROUP_LIMIT', 0), self.assertRaisesRegex(G.DeliveryError, 'bounded group'):
            self.publish(self.new)
        self.assertFalse(self.deletions())


class DeliveryTests(unittest.TestCase):
    def setUp(self):
        self.fixture=release_fixtures.ReleaseTests();self.fixture.setUp();self.addCleanup(self.fixture.tearDown)
        self.root=self.fixture.root;self.remote=FakeGitHub()
        self.target=platform.system().lower()+'-'+{'amd64':'x86_64','arm64':'aarch64'}.get(platform.machine().lower(),platform.machine().lower())
        info=self.root/'application/build-info.txt';info.write_text(info.read_text().replace('linux-x86_64',self.target))
        package=self.root/'application.tar.gz';package.unlink();G.archive.archive_tree(self.root/'application',package)
        G.archive.write_json(self.root/'application.tar.gz.json',G.release.artifact.describe(package))
        self.fixture.spec['artifacts'][0].update(sha256=G.archive.digest(package),target=self.target)
        self.fixture.spec['required_scopes']=['source','archive','recovery']
        G.archive.write_json(self.fixture.spec_path,self.fixture.spec)
        self.directory=self.root/'release';G.release.assemble(self.fixture.spec_path,self.fixture.base,self.directory)
        self.args=dict(repository='example/project',tag='v1',directory=str(self.directory),source_commit='a'*40,
                       packager_commit='a'*40,publication_id='publish-1')
        self.delivery=G.publish_candidate(**self.args)['delivery']

    def publish(self,**changes):
        return G.publish_candidate(**dict(self.args,**changes),execute=True,transport=self.remote)

    def base(self,**changes):
        return G.publish_base('example/project',self.fixture.recipe,self.root/'group','a'*40,
                              transport=self.remote,**changes)

    def cert(self,attempt=1,failed=False,experiment=False):
        c=G.coverage;dest=self.root/('cert-'+str(attempt));dest.mkdir()
        rows=[dict(target=self.target,backend='core',environment='fixture',scope=scope)
              for scope in ('source','archive','recovery')]
        policy={'schema_version':1,'profiles':{'fixture':{'description':'offline lifecycle fixture',
                'targets':{self.target:['core']},'checks':rows}}}
        subject={'source_sha256':self.delivery['source_sha256'],'inventory_sha256':self.delivery['inventory_sha256'],
                 'configuration_sha256':c.digest({'policy':policy,'profile':'fixture'})}
        runner=dest/'fixture.py'
        runner.write_text("import json,sys,hashlib\nfrom pathlib import Path\np=Path(sys.argv[1]);r=json.loads(sys.argv[2])\nif r['scope'] in ('source','recovery'):\n q=p/'source.junit.xml';q.write_text('<testsuite><testcase name=\"fixture\"/></testsuite>');r['evidence']={'source.junit.xml':hashlib.sha256(q.read_bytes()).hexdigest()};r['details']={'executed_tests':['fixture']}\n(p/'qualification.json').write_text(json.dumps(r))\n")
        checks=[]
        for row in rows:
            receipt=dict(schema_version=1,source_sha256=subject['source_sha256'],inventory_sha256=subject['inventory_sha256'],
                host=c.host_identity(),status='passed',details={},assertions=['offline-fixture'],evidence={},
                **{key:row[key] for key in ('target','backend','scope')})
            argv=['{python}','{root}/fixture.py','{evidence}',json.dumps(receipt)]
            if failed and row['scope']=='archive':argv=['{python}','-c','raise SystemExit(7)']
            checks.append(dict(row,id=row['scope'],required=True,argv=argv,qualification='qualification.json',
                               timeout_seconds=5,warning_seconds=4,expected_tests=[]))
        plan=c.freeze({'schema_version':1,'mode':'release','subject':subject,'inputs':{'fixture.py':c.sha(runner)},'checks':checks})
        reports=[]
        for check in checks:
            c.run_case(plan,check['id'],dest,dest/check['id'],'qualification-run',attempt)
            reports.append(dest/check['id']/'result.json')
        # Non-plan ordering must survive deterministic packaging and revalidation.
        reports.reverse()
        certificate=G.certification.certify(self.directory,G.release.verify_release(self.directory),plan,reports,policy,'fixture',experiment)
        paths={}
        for key,value in [('certificate',certificate),('check_plan',plan),('policy',policy)]:
            paths[key]=dest/(key+'.json');c.write_new(paths[key],value)
        return dict(repository='example/project',tag='v1',directory=str(self.directory),delivery=self.delivery,
                    profile='fixture',reports=reports,attempt=attempt,**paths)

    def promotion(self,cert,**changes):
        values={key:cert[key] for key in ('repository','tag','directory','delivery','policy','profile','attempt')}
        values.update(run_id='qualification-run',certificate_sha256=G.archive.digest(cert['certificate']))
        values.update(changes)
        return G.promote(**values,transport=self.remote)

    def test_metadata_only_certificate_and_promotion_reproduce_complete_evidence_without_payload_transfers(self):
        self.publish(); cert = self.cert()
        metadata = self.root / 'metadata'; metadata.mkdir()
        import shutil
        shutil.copyfile(self.directory / 'release.json', metadata / 'release.json')
        cert['directory'] = str(metadata)
        self.remote.calls.clear()
        G.attach_certificate(**cert, execute=True, transport=self.remote, metadata_only=True)
        promoted = self.promotion(cert, execute=True, metadata_only=True)
        self.assertTrue(promoted['latest'])
        names = {row['id']: row['name'] for row in self.remote.releases[0]['assets']}
        transferred = {names[call[1]] for call in self.remote.calls if call[0] == 'download'}
        self.assertTrue(all(name == 'delivery.json' or name.startswith('certification-') for name in transferred))
        self.assertTrue(any(name.endswith('.tar.gz') for name in transferred))
        altered = copy.deepcopy(self.delivery); altered['files']['application.tar.gz']['size'] += 1
        with self.assertRaisesRegex(ValueError, 'remote asset differs'):
            G.verified_remote(G.Remote('example/project', self.remote), altered, metadata,
                readback=False, metadata_only=True)

    def test_mutations_are_offline_plans_by_default(self):
        self.assertFalse(G.publish_candidate(**self.args,transport=self.remote)['execute'])
        self.assertFalse(self.base()['execute'])
        cert=self.cert()
        self.assertFalse(G.attach_certificate(**cert,transport=self.remote)['execute'])
        self.assertFalse(self.promotion(cert)['execute'])
        self.assertEqual(self.remote.calls,[])

    def test_candidate_publishes_only_after_complete_byte_verification(self):
        result=self.publish()
        self.assertTrue(result['execute']);self.assertFalse(self.remote.releases[0]['draft'])
        self.assertTrue(self.remote.releases[0]['prerelease']);self.assertFalse(result['delivery']['experiment'])
        self.assertIsNone(self.remote.latest)
        uploads=[x for x in self.remote.calls if x[0]=='upload']
        self.assertEqual(len(uploads),len(self.delivery['files'])+1)
        last_patch=max(i for i,x in enumerate(self.remote.calls) if x[0]=='PATCH')
        self.assertTrue(any(x[0]=='download' for x in self.remote.calls[:last_patch]))

    def test_first_ordinary_candidate_does_not_enter_latest_fallback(self):
        self.remote.first_normal_latest=True
        result=self.publish()
        self.assertFalse(result['delivery']['experiment'])
        self.assertTrue(self.remote.releases[0]['prerelease'])
        self.assertIsNone(self.remote.json('repos/example/project/releases/latest',missing=True))
        # Demonstrate that the fake reproduces the failed first-normal-release
        # behavior despite the explicit make_latest=false publication field.
        self.remote.releases[0]['prerelease']=False
        self.assertEqual(self.remote.releases[0]['make_latest'],'false')
        self.assertEqual(self.remote.json('repos/example/project/releases/latest')['id'],result['release_id'])

    def test_candidate_latest_pointer_is_still_rejected(self):
        original=self.remote.json
        def select_candidate(endpoint,**kwargs):
            result=original(endpoint,**kwargs)
            if kwargs.get('method')=='PATCH' and kwargs.get('body',{}).get('draft') is False:
                self.remote.latest=result['id']
            return result
        self.remote.json=select_candidate
        with self.assertRaisesRegex(G.DeliveryError,'unexpectedly selected as Latest') as caught:
            self.publish()
        self.assertTrue(caught.exception.uncertain)
        self.assertTrue(self.remote.releases[0]['prerelease'])

    def test_remote_lifecycle_pin_distinguishes_pending_and_promoted_ordinary_release(self):
        self.publish();remote=G.Remote('example/project',self.remote)
        for pin in (1,0,'false'):
            with self.subTest(pin=pin),self.assertRaisesRegex(ValueError,'prerelease pin'):
                G.verified_remote(remote,self.delivery,self.directory,prerelease=pin)
        G.verified_remote(remote,self.delivery,self.directory,prerelease=True)
        with self.assertRaisesRegex(ValueError,'lifecycle'):
            G.verified_remote(remote,self.delivery,self.directory,prerelease=False)
        self.remote.releases[0]['prerelease']=False
        G.verified_remote(remote,self.delivery,self.directory)
        G.verified_remote(remote,self.delivery,self.directory,prerelease=False)
        with self.assertRaisesRegex(ValueError,'lifecycle'):
            G.verified_remote(remote,self.delivery,self.directory,prerelease=True)

    def test_existing_tag_draft_and_duplicate_tags_never_overwrite(self):
        self.publish();before=copy.deepcopy(self.remote.releases);count=len(self.remote.mutations)
        with self.assertRaisesRegex(ValueError,'already exists'):self.publish()
        self.assertEqual(self.remote.releases,before);self.assertEqual(len(self.remote.mutations),count)
        duplicate=copy.deepcopy(before[0]);duplicate['id']=999;self.remote.releases.append(duplicate)
        with self.assertRaisesRegex(ValueError,'duplicate release tags'):self.publish()

    def test_existing_orphan_tag_is_not_silently_adopted(self):
        self.remote.refs['v1']='a'*40
        with self.assertRaisesRegex(ValueError,'already exists'):self.publish()
        self.assertFalse(self.remote.mutations)

    def test_unknown_upload_outcome_preserves_draft_and_blocks_retry(self):
        self.remote.fail_upload='application.tar.gz'
        with self.assertRaises(G.DeliveryError) as caught:self.publish()
        self.assertTrue(caught.exception.uncertain);self.assertTrue(self.remote.releases[0]['draft'])
        self.assertFalse(any(x[0]=='PATCH' for x in self.remote.mutations))
        with self.assertRaisesRegex(ValueError,'already exists'):self.publish()

    def test_replaced_same_byte_asset_invalidates_observation(self):
        self.publish();self.remote.change_download=lambda:self.remote.replace_asset('application.tar.gz')
        with self.assertRaisesRegex(ValueError,'identities changed'):
            G.verified_remote(G.Remote('example/project',self.remote),self.delivery,self.directory)

    def test_tag_change_during_download_invalidates_observation(self):
        self.publish();self.remote.change_download=lambda:self.remote.refs.update(v1='b'*40)
        with self.assertRaisesRegex(ValueError,'tag identity changed'):
            G.verified_remote(G.Remote('example/project',self.remote),self.delivery,self.directory)

    def test_incomplete_or_duplicate_remote_assets_never_finalize(self):
        original=self.remote.upload
        def incomplete(tag,path):
            original(tag,path)
            if Path(path).name=='delivery.json':self.remote.releases[0]['assets'][0]['state']='starter'
        self.remote.upload=incomplete
        with self.assertRaises(G.DeliveryError) as caught:self.publish()
        self.assertTrue(caught.exception.uncertain);self.assertTrue(self.remote.releases[0]['draft'])
        self.assertFalse(any(x[0]=='PATCH' for x in self.remote.mutations))
        self.remote.releases[0]['assets'][0]['state']='uploaded'
        duplicate=copy.deepcopy(self.remote.releases[0]['assets'][0]);duplicate['id']=999
        self.remote.releases[0]['assets'].append(duplicate)
        with self.assertRaisesRegex(ValueError,'duplicate'):
            G.Remote('example/project',self.remote).assets(self.remote.releases[0])

    def test_missing_local_dependency_member_prevents_any_mutation(self):
        member=next(name for name in self.delivery['files'] if name.startswith('dependencies/'))
        (self.directory/member).unlink()
        with self.assertRaises(ValueError):self.publish()
        self.assertFalse(self.remote.calls)

    def test_base_fetch_missing_is_failure_without_fallback(self):
        with self.assertRaisesRegex(ValueError,'absent'):
            G.fetch_base('example/project',self.fixture.recipe,self.root/'fetched',transport=self.remote)
        self.assertFalse((self.root/'fetched').exists());self.assertFalse(self.remote.mutations)

    def base_groups(self, count=4):
        recipes = [digit * 64 for digit in 'abcdef'[:count]]
        groups = {}
        for recipe in recipes:
            if recipe == self.fixture.recipe:
                group = self.root / 'group'
            else:
                _, _, _, group = release_fixtures.fixture(self.root / ('sdk-' + recipe[0]), recipe=recipe)
            G.publish_base('example/project', recipe, group, 'a' * 40, execute=True, transport=self.remote)
            groups[recipe] = G.store.verify_group(group, recipe)
        self.remote.calls.clear()
        return recipes, groups

    def test_batch_base_fetch_uses_one_inventory_and_one_reconciliation_for_four_groups(self):
        recipes, expected = self.base_groups()
        destination = self.root / 'fetched-batch'
        result = G.fetch_bases('example/project', recipes, destination, transport=self.remote)
        self.assertEqual(set(result), set(recipes))
        for recipe in recipes:
            self.assertEqual(result[recipe], dict(fetched=True, recipe=recipe, files=expected[recipe], payload='complete'))
            self.assertEqual(G.store.verify_group(destination / recipe, recipe), expected[recipe])
        metadata = [call for call in self.remote.calls if call[0] in ('GET', 'pages')]
        self.assertEqual(len(metadata), 7)
        self.assertEqual(sum(call[0] == 'download' for call in self.remote.calls), 12)
        self.assertFalse(self.remote.mutations)

    def test_batch_base_fetch_keeps_one_global_four_transfer_bound(self):
        recipes, _ = self.base_groups()
        barrier = threading.Barrier(4); guard = threading.Lock()
        active = 0; peak = 0; completed = []
        original = self.remote.download
        def download(asset_id, path):
            nonlocal active, peak
            with guard:
                active += 1; peak = max(peak, active)
            try:
                barrier.wait(timeout=5)
                original(asset_id, path)
                with guard: completed.append(asset_id)
            finally:
                with guard: active -= 1
        with mock.patch.object(self.remote, 'download', side_effect=download):
            G.fetch_bases('example/project', recipes, self.root / 'parallel-batch', transport=self.remote)
        self.assertEqual(peak, 4); self.assertEqual(active, 0); self.assertEqual(len(completed), 12)

    def test_batch_base_fetch_verifies_complete_recipes_while_other_downloads_continue(self):
        recipes, expected = self.base_groups(2)
        later_assets = {row['id'] for row in self.remote.releases[0]['assets']
                        if row['name'] in G.store.names(recipes[-1])}
        original_download = self.remote.download
        for binary_only in (False, True):
            with self.subTest(binary_only=binary_only):
                verifying = threading.Event(); completed = []
                destination = self.root / ('overlap-' + str(binary_only))
                name = 'verify_binary_group' if binary_only else 'verify_group'
                original_verify = getattr(G.store, name)
                def download(asset_id, path):
                    if asset_id in later_assets:
                        self.assertTrue(verifying.wait(timeout=5), 'early verification waited for later downloads')
                    original_download(asset_id, path); completed.append(asset_id)
                def verify(group, recipe):
                    self.assertFalse(destination.exists())
                    if recipe == recipes[0]:
                        self.assertFalse(later_assets.intersection(completed))
                        verifying.set()
                    return original_verify(group, recipe)
                self.remote.calls.clear()
                with mock.patch.object(self.remote, 'download', side_effect=download), \
                        mock.patch.object(G.store, name, side_effect=verify):
                    result = G.fetch_bases('example/project', recipes, destination,
                                           transport=self.remote, binary_only=binary_only)
                self.assertTrue(verifying.is_set())
                self.assertEqual({recipe: row['files'] for recipe, row in result.items()}, expected)
                self.assertEqual(sum(call[0] in ('GET', 'pages') for call in self.remote.calls), 7)
                self.assertEqual(len(completed), 4 if binary_only else 6)

    def test_batch_base_fetch_bounds_verification_workers_independently(self):
        recipes, _ = self.base_groups(6)
        barrier = threading.Barrier(4); guard = threading.Lock()
        active = 0; peak = 0; completed = []
        original = G.store.verify_group
        def verify(group, recipe):
            nonlocal active, peak
            with guard:
                active += 1; peak = max(peak, active)
            try:
                if recipe in recipes[:4]: barrier.wait(timeout=5)
                result = original(group, recipe)
                with guard: completed.append(recipe)
                return result
            finally:
                with guard: active -= 1
        with mock.patch.object(G.store, 'verify_group', side_effect=verify):
            G.fetch_bases('example/project', recipes, self.root / 'bounded-verification', transport=self.remote)
        self.assertEqual(peak, 4); self.assertEqual(active, 0); self.assertCountEqual(completed, recipes)

    def test_batch_transfer_failure_joins_running_verifier_before_staging_cleanup(self):
        recipes, _ = self.base_groups(2)
        verifying = threading.Event(); failed = threading.Event(); verified = threading.Event()
        fail_name = G.store.names(recipes[-1])[0]
        fail_id = next(row['id'] for row in self.remote.releases[0]['assets'] if row['name'] == fail_name)
        original_download = self.remote.download; original_verify = G.store.verify_group
        destination = self.root / 'transfer-failed-pipeline'; completed = []
        def download(asset_id, path):
            if asset_id == fail_id:
                self.assertTrue(verifying.wait(timeout=5))
                failed.set()
                raise G.DeliveryError('injected pipelined transfer failure')
            original_download(asset_id, path); completed.append(asset_id)
        def verify(group, recipe):
            if recipe == recipes[0]:
                verifying.set()
                self.assertTrue(failed.wait(timeout=5))
                result = original_verify(group, recipe)
                self.assertTrue(Path(group).is_dir()); verified.set()
                return result
            return original_verify(group, recipe)
        with mock.patch.object(self.remote, 'download', side_effect=download), \
                mock.patch.object(G.store, 'verify_group', side_effect=verify):
            with self.assertRaisesRegex(ValueError, 'injected pipelined transfer failure'):
                G.fetch_bases('example/project', recipes, destination, transport=self.remote)
        self.assertTrue(verified.is_set())
        self.assertEqual(set(completed), {row['id'] for row in self.remote.releases[0]['assets']} - {fail_id})
        self.assertFalse(destination.exists()); self.assertFalse(list(self.root.glob('.base-fetch-*')))

    def test_batch_verification_failure_joins_later_transfers_before_staging_cleanup(self):
        recipes, _ = self.base_groups(2)
        verifying = threading.Event(); downloading = threading.Event(); failed = threading.Event()
        late_name = G.store.names(recipes[-1])[0]
        late_id = next(row['id'] for row in self.remote.releases[0]['assets'] if row['name'] == late_name)
        original_download = self.remote.download; original_verify = G.store.verify_group
        destination = self.root / 'verify-failed-pipeline'; completed = []
        def download(asset_id, path):
            if asset_id == late_id:
                self.assertTrue(verifying.wait(timeout=5)); downloading.set()
                self.assertTrue(failed.wait(timeout=5))
            original_download(asset_id, path); completed.append(asset_id)
        def verify(group, recipe):
            if recipe == recipes[0]:
                verifying.set(); self.assertTrue(downloading.wait(timeout=5)); failed.set()
                raise G.DeliveryError('injected pipelined verification failure')
            return original_verify(group, recipe)
        with mock.patch.object(self.remote, 'download', side_effect=download), \
                mock.patch.object(G.store, 'verify_group', side_effect=verify):
            with self.assertRaisesRegex(ValueError, 'injected pipelined verification failure'):
                G.fetch_bases('example/project', recipes, destination, transport=self.remote)
        self.assertEqual(set(completed), {row['id'] for row in self.remote.releases[0]['assets']})
        self.assertFalse(destination.exists()); self.assertFalse(list(self.root.glob('.base-fetch-*')))

    def test_batch_binary_fetch_verifies_complete_inventory_without_source_transfers(self):
        recipes, expected = self.base_groups(2)
        destination = self.root / 'binary-batch'
        result = G.fetch_bases('example/project', recipes, destination, transport=self.remote, binary_only=True)
        transferred = {call[1] for call in self.remote.calls if call[0] == 'download'}
        for recipe in recipes:
            binary, source, sums = G.store.names(recipe)
            self.assertEqual({p.name for p in (destination / recipe).iterdir()}, {binary, sums})
            self.assertEqual(result[recipe]['files'], expected[recipe])
            self.assertEqual(result[recipe]['payload'], 'binary')
            source_id = next(row['id'] for row in self.remote.releases[0]['assets'] if row['name'] == source)
            self.assertNotIn(source_id, transferred)
        self.assertEqual(len(transferred), 4)
        self.remote.replace_asset(G.store.names(recipes[-1])[1], b'changed retained source')
        invalid = self.root / 'invalid-binary-batch'
        with self.assertRaisesRegex(ValueError, 'complete checksum inventory'):
            G.fetch_bases('example/project', recipes, invalid, transport=self.remote, binary_only=True)
        self.assertFalse(invalid.exists())

    def test_batch_base_fetch_rejects_metadata_drift_before_exposing_any_group(self):
        recipes, _ = self.base_groups(2)
        original_row = copy.deepcopy(self.remote.releases[0]); original_refs = dict(self.remote.refs)
        mutations = (lambda: self.remote.refs.update(base='b' * 40),
                     lambda: self.remote.replace_asset(G.store.names(recipes[-1])[1]),
                     lambda: self.remote.releases[0].update(prerelease=False))
        for index, change in enumerate(mutations):
            with self.subTest(change=index):
                self.remote.releases[0] = copy.deepcopy(original_row); self.remote.refs = dict(original_refs)
                self.remote.change_download = change
                destination = self.root / ('drifting-batch-' + str(index))
                with self.assertRaises(ValueError):
                    G.fetch_bases('example/project', recipes, destination, transport=self.remote)
                self.assertFalse(destination.exists())
                self.assertFalse(list(self.root.glob('.base-fetch-*')))

    def test_batch_base_fetch_corruption_leaves_no_complete_or_partial_output(self):
        recipes, _ = self.base_groups(2)
        binary = G.store.names(recipes[-1])[0]
        asset = next(row for row in self.remote.releases[0]['assets'] if row['name'] == binary)
        self.remote.data[asset['id']] = b'corrupt download'
        destination = self.root / 'corrupt-batch'
        with self.assertRaises(ValueError):
            G.fetch_bases('example/project', recipes, destination, transport=self.remote)
        self.assertFalse(destination.exists()); self.assertFalse(list(self.root.glob('.base-fetch-*')))

    def test_batch_base_fetch_joins_workers_before_removing_failed_staging(self):
        recipes, _ = self.base_groups(2)
        fail_id = self.remote.releases[0]['assets'][0]['id']
        started = threading.Barrier(4); completed = []; original = self.remote.download
        first_wave = set(row['id'] for row in self.remote.releases[0]['assets'][:4])
        def download(asset_id, path):
            if asset_id in first_wave: started.wait(timeout=5)
            if asset_id == fail_id: raise G.DeliveryError('injected failed transfer')
            original(asset_id, path); completed.append(asset_id)
        with mock.patch.object(self.remote, 'download', side_effect=download):
            with self.assertRaisesRegex(ValueError, 'injected failed transfer'):
                G.fetch_bases('example/project', recipes, self.root / 'failed-batch', transport=self.remote)
        self.assertEqual(set(completed), {row['id'] for row in self.remote.releases[0]['assets']} - {fail_id})
        self.assertFalse((self.root / 'failed-batch').exists()); self.assertFalse(list(self.root.glob('.base-fetch-*')))

    def test_batch_base_fetch_invalid_selection_and_existing_output_fail_before_remote_reads(self):
        destination = self.root / 'existing-batch'; destination.mkdir(); (destination / 'keep').write_text('retained')
        for recipes in ([], 'a' * 64, [None], ['../bad'], ['a' * 64, 'a' * 64]):
            with self.subTest(recipes=recipes), self.assertRaises(ValueError):
                G.fetch_bases('example/project', recipes, self.root / 'invalid-batch', transport=self.remote)
        with self.assertRaises(ValueError):
            G.fetch_bases('example/project', ['a' * 64], destination, transport=self.remote)
        self.assertEqual((destination / 'keep').read_text(), 'retained')
        self.assertFalse(self.remote.calls); self.assertFalse((self.root / 'invalid-batch').exists())

    def test_base_publish_fetch_and_exact_reuse(self):
        self.base(execute=True)
        self.assertTrue(self.remote.releases[0]['prerelease']);self.assertIsNone(self.remote.latest)
        uploads=[x[2] for x in self.remote.calls if x[0]=='upload']
        self.assertCountEqual(uploads,list(G.store.names(self.fixture.recipe)))
        self.assertEqual(uploads[-1],G.store.names(self.fixture.recipe)[2])
        result=G.fetch_base('example/project',self.fixture.recipe,self.root/'fetched',transport=self.remote)
        self.assertEqual(result['files'],G.store.verify_group(self.root/'group',self.fixture.recipe))
        count=len(self.remote.mutations);self.assertTrue(self.base(execute=True)['reused'])
        self.assertEqual(len(self.remote.mutations),count)

    def test_base_payload_failure_prevents_checksum_commit_marker(self):
        binary, source, checksum = G.store.names(self.fixture.recipe)
        self.remote.fail_upload = binary
        with self.assertRaises(G.DeliveryError): self.base(execute=True)
        self.assertNotIn(checksum, [call[2] for call in self.remote.calls if call[0] == 'upload'])
        self.assertTrue(self.remote.releases[0]['draft'])

    def test_base_reuse_checks_all_remote_identities_without_downloading(self):
        self.base(execute=True); self.remote.calls.clear()
        self.assertTrue(self.base(execute=True)['reused'])
        self.assertFalse(any(call[0] in ('download', 'upload') for call in self.remote.calls))
        source = G.store.names(self.fixture.recipe)[1]
        self.remote.replace_asset(source, b'changed source')
        with self.assertRaisesRegex(ValueError, 'immutable group conflicts'):
            self.base(execute=True)

    def test_base_reuse_rejects_changed_size_or_identity_during_reconciliation(self):
        self.base(execute=True)
        row = self.remote.releases[0]['assets'][0]; original = row['size']; row['size'] += 1
        with self.assertRaisesRegex(ValueError, 'immutable group conflicts'):
            self.base(execute=True)
        row['size'] = original
        original_pages = self.remote.pages; reads = 0
        def pages(endpoint):
            nonlocal reads
            if '/assets?' in endpoint:
                reads += 1
                if reads == 2: self.remote.releases[0]['assets'][0]['id'] += 1000
            return original_pages(endpoint)
        with mock.patch.object(self.remote, 'pages', side_effect=pages), self.assertRaises(ValueError):
            self.base(execute=True)

    def test_binary_base_fetch_reconciles_complete_triplet_without_source_download(self):
        self.base(execute=True); self.remote.calls.clear()
        destination = self.root / 'binary-fetch'
        result = G.fetch_base('example/project', self.fixture.recipe, destination, transport=self.remote, binary_only=True)
        binary, source, sums = G.store.names(self.fixture.recipe)
        self.assertEqual(set(p.name for p in destination.iterdir()), {binary, sums})
        self.assertEqual(result['files'], G.store.verify_group(self.root/'group', self.fixture.recipe))
        self.assertEqual(result['payload'], 'binary')
        source_id = next(row['id'] for row in self.remote.releases[0]['assets'] if row['name'] == source)
        self.assertNotIn(('download', source_id), self.remote.calls)
        self.assertEqual(sum(call[0] == 'download' for call in self.remote.calls), 2)

    def test_binary_base_fetch_rejects_changed_untransferred_source_digest(self):
        self.base(execute=True); source = G.store.names(self.fixture.recipe)[1]
        self.remote.replace_asset(source, b'changed supplier source')
        destination = self.root/'invalid-binary-fetch'
        with self.assertRaisesRegex(ValueError, 'complete checksum inventory'):
            G.fetch_base('example/project', self.fixture.recipe, destination, transport=self.remote, binary_only=True)
        self.assertFalse(destination.exists())

    def test_binary_base_fetch_rejects_tag_or_asset_replacement_before_activation(self):
        self.base(execute=True)
        self.remote.change_download = lambda: self.remote.refs.update(base='b'*40)
        destination = self.root/'replaced-binary-fetch'
        with self.assertRaises(ValueError):
            G.fetch_base('example/project', self.fixture.recipe, destination, transport=self.remote, binary_only=True)
        self.assertFalse(destination.exists())

    def test_parallel_downloads_join_all_writers_after_failure_and_reject_collisions(self):
        import threading
        started = threading.Barrier(4); completed = []; guard = threading.Lock()
        class Remote:
            def download(self, asset, path, digest):
                started.wait(timeout=5)
                if asset == 0: raise ValueError('transfer failed')
                with guard: completed.append(asset)
        selections = [(str(i), self.root/str(i), 'a'*64) for i in range(4)]
        with self.assertRaisesRegex(ValueError, 'transfer failed'):
            G.download_files(Remote(), {str(i):i for i in range(4)}, selections)
        self.assertEqual(set(completed), {1, 2, 3})
        with self.assertRaisesRegex(ValueError, 'distinct'):
            G.download_files(Remote(), {'0':0}, [selections[0], selections[0]])

    def test_candidate_upload_response_loss_joins_payload_batch_and_omits_control_and_publish(self):
        self.remote.fail_upload = 'application.tar.gz'
        with self.assertRaises(G.DeliveryError) as caught: self.publish()
        self.assertTrue(caught.exception.uncertain)
        self.assertTrue(self.remote.releases[0]['draft'])
        self.assertFalse(any(row[0] == 'PATCH' for row in self.remote.calls))
        self.assertFalse(any(row[0] == 'upload' and row[2] == 'delivery.json' for row in self.remote.calls))

    def test_parallel_uploads_join_failed_batch_before_later_batch_or_controls(self):
        barrier=threading.Barrier(4); completed=[]; lock=threading.Lock()
        class Remote:
            def upload(self, tag, path):
                barrier.wait(timeout=5)
                if path.name == '0': raise G.DeliveryError('upload response lost', uncertain=True)
                with lock: completed.append(path.name)
        with self.assertRaisesRegex(G.DeliveryError, 'upload response lost'):
            G.upload_files(Remote(), 'fixture', [self.root/str(i) for i in range(8)])
        self.assertEqual(set(completed), {'1','2','3'})
        with self.assertRaisesRegex(G.DeliveryError,'distinct'):
            G.upload_files(Remote(), 'fixture', [self.root/'one', self.root/'ONE'])

    def test_shared_physical_evidence_keeps_all_logical_reports_and_original_bytes(self):
        parent=self.root/'shared-execution'; parent.mkdir(); console=parent/'console.log'; console.write_bytes(b'shared execution log')
        reports=[]
        for check in ('backend-a','backend-b','backend-c'):
            path=parent/(check+'.result.json')
            path.write_bytes(G.archive.encoded({'check':check,'evidence':{'console.log':G.archive.digest(console)}}))
            reports.append(path)
        target=self.root/'shared-retention'; target.mkdir(); copies={}; seen=[]
        def retain(source,name):
            seen.append(name); source=Path(source); data=source.read_bytes()
            if name in copies:
                self.assertEqual(copies[name],(source.resolve(),data)); return
            copies[name]=(source.resolve(),data)
            path=target/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(data)
        mapping=G.retain_reports(reports,retain)
        self.assertEqual(set(mapping),{'backend-a','backend-b','backend-c'})
        self.assertEqual(len(copies),4)
        self.assertEqual(len(set(Path(name).parent for name in mapping.values())),1)
        for path in reports:
            retained=target/mapping[G.coverage.load(path)['check']]
            self.assertEqual(path.read_bytes(),retained.read_bytes())
            self.assertEqual(G.coverage.load(retained)['evidence']['console.log'],G.archive.digest(retained.parent/'console.log'))
        other=self.root/'another-execution';other.mkdir();(other/'console.log').write_bytes(console.read_bytes())
        path=other/'other.result.json';path.write_bytes(G.archive.encoded({'check':'other','evidence':{'console.log':G.archive.digest(console)}}))
        mapping=G.retain_reports(reports+[path],retain)
        self.assertNotEqual(Path(mapping['other']).parent,Path(mapping['backend-a']).parent)
        with self.assertRaisesRegex(G.DeliveryError,'duplicate'):
            G.retain_reports([reports[0],reports[0]],retain)

    def test_base_release_replacement_during_upload_is_uncertain(self):
        original=self.remote.upload
        def changed_release(tag,path):
            original(tag,path)
            if Path(path).name==G.store.names(self.fixture.recipe)[-1]:
                self.remote.releases[0]['id']=999
        self.remote.upload=changed_release
        with self.assertRaisesRegex(G.DeliveryError,'base release identity changed') as caught:
            self.base(execute=True)
        self.assertTrue(caught.exception.uncertain)
        self.assertFalse(any(x[0]=='PATCH' for x in self.remote.mutations))

    def test_partial_or_conflicting_base_is_not_replaced(self):
        self.base(execute=True);row=self.remote.releases[0];row['assets'].pop();count=len(self.remote.mutations)
        with self.assertRaisesRegex(ValueError,'partial existing'):self.base(execute=True)
        self.assertEqual(len(self.remote.mutations),count)

    def test_changed_base_asset_is_rejected_even_with_valid_server_digest(self):
        self.base(execute=True);name=G.store.names(self.fixture.recipe)[0];self.remote.replace_asset(name,b'changed')
        count=len(self.remote.mutations)
        with self.assertRaisesRegex(ValueError,'differs'):self.base(execute=True)
        self.assertEqual(len(self.remote.mutations),count)

    def test_complete_certificate_attachment_and_exact_promotion(self):
        self.remote.first_normal_latest=True
        self.publish();cert=self.cert();before=copy.deepcopy(self.remote.releases[0]['assets'])
        attached=G.attach_certificate(**cert,execute=True,transport=self.remote)
        self.assertIsNone(self.remote.latest)
        self.assertEqual(self.remote.releases[0]['assets'][:len(before)],before)
        self.assertTrue(self.remote.releases[0]['prerelease'])
        self.assertIsNone(self.remote.json('repos/example/project/releases/latest',missing=True))
        self.assertEqual(self.remote.releases[0]['body'],'Certification pending. Immutable application assets.')
        note='\n\nOperator note: "Certification pending." is the original placeholder.'
        verify=G.verify_certificate
        def add_note(*args,**kwargs):
            result=verify(*args,**kwargs)
            self.remote.releases[0]['body']+=note
            return result
        with mock.patch.object(G,'verify_certificate',side_effect=add_note):
            result=self.promotion(cert,execute=True)
        self.assertEqual(self.remote.releases[0]['body'],'Certification complete. Immutable application assets.'+note)
        self.assertTrue(result['latest']);self.assertEqual(self.remote.latest,result['release_id'])
        self.assertFalse(self.remote.releases[0]['prerelease']);self.assertFalse(self.delivery['experiment'])
        G.verified_remote(G.Remote('example/project',self.remote),self.delivery,self.directory,prerelease=False)
        self.assertEqual(set(attached['files']),{'certification-qualification-run-attempt-1.json','certification-qualification-run-attempt-1.tar.gz'})

    def test_attachment_preserves_initial_lifecycle_for_pending_and_promoted_release(self):
        self.publish();cert=self.cert();G.attach_certificate(**cert,execute=True,transport=self.remote)
        self.promotion(cert,execute=True)
        later=self.cert(2)
        G.attach_certificate(**later,execute=True,transport=self.remote)
        self.assertFalse(self.remote.releases[0]['prerelease'])
        self.assertEqual(self.remote.latest,self.remote.releases[0]['id'])
        count=len(self.remote.mutations)
        self.remote.releases[0]['body']='Operator note: Certification pending. is quoted, not the generated status.'
        self.promotion(later,execute=True)
        self.assertEqual(len(self.remote.mutations),count+1)
        self.assertFalse(self.remote.releases[0]['prerelease'])
        self.assertEqual(self.remote.releases[0]['body'],'Operator note: Certification pending. is quoted, not the generated status.')

    def test_lifecycle_change_during_attachment_is_uncertain(self):
        self.publish();cert=self.cert();original=self.remote.upload
        def changed_lifecycle(tag,path):
            original(tag,path)
            if Path(path).name.startswith('certification-'):
                self.remote.releases[0]['prerelease']=False
        self.remote.upload=changed_lifecycle
        with self.assertRaisesRegex(G.DeliveryError,'lifecycle') as caught:
            G.attach_certificate(**cert,execute=True,transport=self.remote)
        self.assertTrue(caught.exception.uncertain)

    def test_lifecycle_change_after_certificate_review_blocks_promotion(self):
        self.publish();cert=self.cert();G.attach_certificate(**cert,execute=True,transport=self.remote)
        original=G.verify_certificate;count=len(self.remote.mutations)
        def changed_lifecycle(*args,**kwargs):
            result=original(*args,**kwargs)
            self.remote.releases[0]['prerelease']=False
            return result
        with mock.patch.object(G,'verify_certificate',side_effect=changed_lifecycle):
            with self.assertRaisesRegex(G.DeliveryError,'lifecycle') as caught:
                self.promotion(cert,execute=True)
        self.assertFalse(caught.exception.uncertain)
        self.assertEqual(len(self.remote.mutations),count);self.assertIsNone(self.remote.latest)


    def adopted_cert(self):
        original = self.cert()
        c = G.coverage; frozen = c.load(original['check_plan'])
        root = original['check_plan'].parent
        current = root / 'rerun-source'
        c.run_case(frozen, 'source', root, current, 'qualification-run', 2)
        prior = [path for path in original['reports'] if c.load(path)['check'] != 'source']
        adoption = c.adopt(frozen, prior, root, 'qualification-run', 2)
        reports = [*prior, current/'result.json']
        document = G.certification.certify(self.directory,G.release.verify_release(self.directory),frozen,
                    reports,c.load(original['policy']),'fixture',adoption=adoption)
        certificate = root/'adopted-certificate.json'; c.write_new(certificate,document)
        return original, dict(original, certificate=certificate, reports=reports, attempt=2)

    def test_adopted_certificate_survives_complete_bundle_remote_verification_and_promotion(self):
        self.publish(); original, adopted = self.adopted_cert()
        G.attach_certificate(**original, execute=True, transport=self.remote)
        old_assets = copy.deepcopy(self.remote.releases[0]['assets'])
        old_bytes = {path:path.read_bytes() for path in original['reports']}
        G.attach_certificate(**adopted, execute=True, transport=self.remote)
        self.assertEqual(self.remote.releases[0]['assets'][:len(old_assets)],old_assets)
        result = self.promotion(adopted,execute=True)
        self.assertTrue(result['execute']); self.assertIsNotNone(self.remote.latest)
        self.assertEqual({path:path.read_bytes() for path in original['reports']},old_bytes)
        certificate = G.coverage.load(adopted['certificate'])
        self.assertEqual(certificate['coverage']['source']['attempt'],2)
        self.assertEqual(certificate['coverage']['archive']['attempt'],1)
        self.assertEqual(certificate['adoption']['attempt'],2)

    def test_adopted_certificate_cannot_be_attached_under_another_attempt_or_changed_evidence(self):
        self.publish(); _, adopted = self.adopted_cert()
        count = len(self.remote.mutations)
        with self.assertRaisesRegex(ValueError,'adoption belongs to another'):
            G.attach_certificate(**dict(adopted,attempt=3),execute=True,transport=self.remote)
        self.assertEqual(len(self.remote.mutations),count)
        adopted['reports'][0].parent.joinpath('console.log').write_text('changed old log')
        with self.assertRaisesRegex(ValueError,'evidence changed'):
            G.attach_certificate(**adopted,execute=True,transport=self.remote)
        self.assertEqual(len(self.remote.mutations),count)

    def test_failed_later_attempt_keeps_older_reports_and_binary_bytes(self):
        self.publish();cert=self.cert();G.attach_certificate(**cert,execute=True,transport=self.remote)
        old=copy.deepcopy(self.remote.releases[0]['assets']);later=self.cert(2,failed=True)
        G.attach_certificate(**later,execute=True,transport=self.remote)
        self.assertEqual(self.remote.releases[0]['assets'][:len(old)],old)
        with self.assertRaisesRegex(ValueError,'does not qualify'):self.promotion(later,execute=True)
        self.assertIsNone(self.remote.latest)
        self.assertEqual(self.remote.releases[0]['body'],'Certification pending. Immutable application assets.')

    def test_duplicate_attempt_and_stale_certificate_are_rejected(self):
        self.publish();cert=self.cert();G.attach_certificate(**cert,execute=True,transport=self.remote)
        count=len(self.remote.mutations)
        with self.assertRaisesRegex(ValueError,'already exists'):G.attach_certificate(**cert,execute=True,transport=self.remote)
        with self.assertRaisesRegex(ValueError,'stale'):self.promotion(cert,certificate_sha256='0'*64,execute=True)
        self.assertEqual(len(self.remote.mutations),count)

    def test_partial_certificate_attempt_blocks_promotion_and_later_attachment(self):
        self.publish();cert=self.cert();stem='certification-qualification-run-attempt-1.tar.gz'
        self.remote.fail_upload=stem
        with self.assertRaises(G.DeliveryError) as caught:
            G.attach_certificate(**cert,execute=True,transport=self.remote)
        self.assertTrue(caught.exception.uncertain);count=len(self.remote.mutations)
        with self.assertRaisesRegex(ValueError,'partial certificate'):
            self.promotion(cert,execute=True)
        later=self.cert(2)
        with self.assertRaisesRegex(ValueError,'partial certificate'):
            G.attach_certificate(**later,execute=True,transport=self.remote)
        self.assertEqual(len(self.remote.mutations),count);self.assertIsNone(self.remote.latest)

    def test_changed_policy_or_local_evidence_cannot_reuse_certificate(self):
        self.publish();cert=self.cert();G.attach_certificate(**cert,execute=True,transport=self.remote)
        rules=G.coverage.load(cert['policy']);rules['profiles']['fixture']['description']='Changed support contract'
        Path(cert['policy']).write_bytes(G.archive.encoded(rules));count=len(self.remote.mutations)
        with self.assertRaisesRegex(ValueError,'current promotion policy differs'):
            self.promotion(cert,execute=True)
        self.assertEqual(len(self.remote.mutations),count)
        later=self.cert(2)
        (later['reports'][0].parent/'console.log').write_text('different execution output')
        with self.assertRaises(ValueError):G.attach_certificate(**later,execute=True,transport=self.remote)
        self.assertEqual(len(self.remote.mutations),count)

    def test_changed_binary_or_tag_cannot_be_promoted(self):
        self.publish();cert=self.cert();G.attach_certificate(**cert,execute=True,transport=self.remote)
        self.remote.replace_asset('application.tar.gz',b'different');count=len(self.remote.mutations)
        with self.assertRaises(ValueError):self.promotion(cert,execute=True)
        self.assertEqual(len(self.remote.mutations),count);self.assertIsNone(self.remote.latest)

    def test_experiment_never_becomes_latest_or_relabels_packager(self):
        with self.assertRaisesRegex(ValueError,'requires an experiment'):
            G.publish_candidate(**dict(self.args,packager_commit='b'*40))
        result=self.publish(packager_commit='b'*40,experiment=True)
        self.assertEqual(self.remote.releases[0]['name'],'experiment');self.assertTrue(self.remote.releases[0]['prerelease'])
        self.delivery=result['delivery'];cert=self.cert(experiment=True)
        remote=G.Remote('example/project',self.remote)
        with self.assertRaisesRegex(ValueError,'lifecycle'):
            G.verified_remote(remote,self.delivery,self.directory,prerelease=False)
        self.remote.releases[0]['prerelease']=False
        for pin in (None,False):
            with self.subTest(pin=pin),self.assertRaisesRegex(ValueError,'lifecycle'):
                G.verified_remote(remote,self.delivery,self.directory,prerelease=pin)
        self.remote.releases[0]['prerelease']=True
        with self.assertRaisesRegex(ValueError,'ordinary'):self.promotion(cert,execute=True)
        self.assertIsNone(self.remote.latest)

    def test_final_pointer_failure_is_uncertain_and_never_rolls_back(self):
        self.publish();cert=self.cert();G.attach_certificate(**cert,execute=True,transport=self.remote)
        original=self.remote.json
        def change_pointer(endpoint,**kwargs):
            result=original(endpoint,**kwargs)
            if kwargs.get('body',{}).get('make_latest')=='true':self.remote.latest=None
            return result
        self.remote.json=change_pointer
        with self.assertRaises(G.DeliveryError) as caught:self.promotion(cert,execute=True)
        self.assertTrue(caught.exception.uncertain)
        self.assertEqual(len(self.remote.releases),1)

    def test_promotion_must_finish_as_an_ordinary_release(self):
        self.publish();cert=self.cert();G.attach_certificate(**cert,execute=True,transport=self.remote)
        original=self.remote.json
        def keep_prerelease(endpoint,**kwargs):
            result=original(endpoint,**kwargs)
            if kwargs.get('body',{}).get('make_latest')=='true':self.remote.releases[0]['prerelease']=True
            return result
        self.remote.json=keep_prerelease
        with self.assertRaisesRegex(G.DeliveryError,'lifecycle') as caught:self.promotion(cert,execute=True)
        self.assertTrue(caught.exception.uncertain)

    def test_changed_asset_after_promotion_reports_uncertainty(self):
        self.publish();cert=self.cert();G.attach_certificate(**cert,execute=True,transport=self.remote)
        original=self.remote.json
        def change_asset(endpoint,**kwargs):
            result=original(endpoint,**kwargs)
            if kwargs.get('body',{}).get('make_latest')=='true':self.remote.replace_asset('application.tar.gz')
            return result
        self.remote.json=change_asset
        with self.assertRaises(G.DeliveryError) as caught:self.promotion(cert,execute=True)
        self.assertTrue(caught.exception.uncertain)

    def test_cli_plans_without_transport_and_requires_separate_execution_option(self):
        request=self.root/'request.json';request.write_text(json.dumps(self.args))
        with mock.patch.object(G,'GitHub',side_effect=AssertionError('unexpected transport')):
            with mock.patch('sys.stdout',new_callable=io.StringIO) as output:
                self.assertEqual(G.main(['publish-candidate','--input',str(request)]),0)
            self.assertFalse(json.loads(output.getvalue())['execute'])
        request.write_text(json.dumps(dict(self.args,execute=True)))
        with self.assertRaisesRegex(ValueError,'separate explicit CLI option'):
            G.main(['publish-candidate','--input',str(request)])

    def test_lost_execution_receipt_is_uncertain(self):
        request=self.root/'request.json';request.write_text(json.dumps(self.args))
        with mock.patch.object(G,'GitHub',return_value=self.remote),mock.patch('builtins.print',side_effect=BrokenPipeError):
            with self.assertRaises(G.DeliveryError) as caught:
                G.main(['publish-candidate','--input',str(request),'--execute'])
        self.assertTrue(caught.exception.uncertain)
        self.assertFalse(self.remote.releases[0]['draft']);self.assertIsNone(self.remote.latest)


class TransportTests(unittest.TestCase):
    def setUp(self):
        self.elapsed=0.;self.sleeps=[];self.diagnostics=io.StringIO()
        for patcher in (mock.patch.object(G.time,'time',side_effect=lambda:1000+self.elapsed),
                        mock.patch.object(G.time,'monotonic',side_effect=lambda:self.elapsed),
                        mock.patch.object(G.time,'sleep',side_effect=self.sleep),
                        mock.patch.object(G.random,'uniform',return_value=1.),
                        mock.patch.object(G.sys,'stderr',self.diagnostics)):
            patcher.start();self.addCleanup(patcher.stop)

    def sleep(self,seconds):
        self.assertGreater(seconds,0);self.assertLessEqual(seconds,60)
        self.sleeps.append(seconds);self.elapsed+=seconds

    @staticmethod
    def response(status=200,payload=b'{}',headers=None,code=0):
        head=('HTTP/2 '+str(status)+'\n').encode()
        for key,value in (headers or {}).items():head+=(key+': '+str(value)+'\r\n').encode()
        return subprocess.CompletedProcess([],code,head+b'\r\n'+payload,b'private credential diagnostics')

    def quota(self,remaining=1000,limit=1000,reset=4600):
        return self.response(payload=json.dumps({'resources':{'core':dict(limit=limit,remaining=remaining,reset=reset)}}).encode())

    def test_accounting_reuses_paginated_quota_headers_without_extra_requests(self):
        metrics = G.RequestMetrics(); transport = G.GitHub('example/project', metrics=metrics)
        headers = self.core_headers()
        first = self.response(payload=b'[{"id":1}]', headers=headers).stdout
        second = self.response(payload=b'[{"id":2}]', headers=dict(headers, **{'X-RateLimit-Remaining':'799'})).stdout
        with mock.patch.object(transport, '_run', return_value=subprocess.CompletedProcess([], 0, first+b'\n'+second, b'')) as run:
            self.assertEqual(transport.pages('private-endpoint'), [{'id':1}, {'id':2}])
            transport._headroom()
        self.assertEqual(run.call_count, 1)
        value = metrics.snapshot()
        self.assertEqual(value['api_responses'], 2); self.assertEqual(value['quota_probes'], 0)
        self.assertEqual(value['observed_quota'], {'limit':1000, 'remaining':799, 'reset':4600})
        self.assertNotIn('private', json.dumps(value))
        metrics.observe(dict(headers, **{'X-RateLimit-Remaining':'900'}))
        self.assertEqual(metrics.snapshot()['observed_quota']['remaining'], 799)
        metrics.observe({'x-ratelimit-limit':'secret', 'authorization':'secret'})
        self.assertNotIn('secret', json.dumps(metrics.snapshot()))

    def test_accounting_separates_actual_retry_wait_from_requests(self):
        metrics = G.RequestMetrics(); transport = G.GitHub('example/project', metrics=metrics)
        with mock.patch.object(transport, '_run', side_effect=[self.response(503, code=1), self.response()]):
            transport.json('private-endpoint')
        value = metrics.snapshot()
        self.assertEqual(value['api_responses'], 2)
        self.assertEqual(value['retry_wait_seconds'], 3.)
        self.assertEqual(value['cli_seconds'], 0.)

    def test_primary_rate_limit_waits_for_reset_and_retries_only_get(self):
        transport=G.GitHub('example/project')
        blocked=self.response(403,b'{"message":"private response"}',
            {'X-RateLimit-Remaining':'0','X-RateLimit-Reset':'4600','X-Private':'private header'},1)
        with mock.patch.object(transport,'_run',side_effect=[blocked,self.response(payload=b'{"ok":true}')]) as call:
            self.assertEqual(transport.json('endpoint'),{'ok':True})
        self.assertEqual(call.call_count,2);self.assertEqual(self.elapsed,3601)
        self.assertTrue(all(args.args[0][args.args[0].index('--method')+1]=='GET' for args in call.call_args_list))
        self.assertIn('HTTP 403; remaining=0; reset=4600',self.diagnostics.getvalue())
        self.assertNotIn('private',self.diagnostics.getvalue())

    def test_multiple_quota_windows_use_one_cumulative_transport_wait_budget(self):
        transport=G.GitHub('example/project')
        responses=[self.response(403,headers={'X-RateLimit-Remaining':0,'X-RateLimit-Reset':reset},code=1)
                   for reset in (4600,8200)]
        with mock.patch.object(transport,'_run',side_effect=responses+[self.response()]) as call:
            self.assertEqual(transport.json('first'),{})
        self.assertEqual(call.call_count,3);self.assertEqual(self.elapsed,7201)
        self.assertEqual(transport.wait_remaining,3599)
        with mock.patch.object(transport,'_run',return_value=self.response(403,
                headers={'X-RateLimit-Remaining':0,'X-RateLimit-Reset':11800},code=1)) as call:
            with self.assertRaisesRegex(G.DeliveryError,'wait budget exhausted'):transport.json('second')
        self.assertEqual(call.call_count,1);self.assertEqual(self.elapsed,7201)

    def test_retry_after_honors_both_numeric_and_http_date_minimums(self):
        for headers,delay in (({'Retry-After':30,'X-RateLimit-Remaining':0,'X-RateLimit-Reset':1020},31),
                              ({'Retry-After':'Thu, 01 Jan 1970 00:17:00 GMT'},21)):
            with self.subTest(headers=headers):
                self.elapsed=0;transport=G.GitHub('example/project')
                with mock.patch.object(transport,'_run',side_effect=[self.response(429,headers=headers,code=1),self.response()]):
                    self.assertEqual(transport.json('endpoint'),{})
                self.assertEqual(self.elapsed,delay)

    def test_explicit_primary_and_secondary_messages_allow_403_backoff(self):
        for message in ('API rate limit exceeded for 192.0.2.1.', 'API rate limit exceeded.',
                        'You have exceeded a secondary rate limit. Please wait a few minutes before you try again.',
                        'You have triggered an abuse detection mechanism. Please wait a few minutes before you try again.'):
            with self.subTest(message=message):
                transport=G.GitHub('example/project');start=self.elapsed
                blocked=self.response(403,json.dumps({'message':message}).encode(),code=1)
                with mock.patch.object(transport,'_run',side_effect=[blocked,blocked,self.response()]) as call:
                    self.assertEqual(transport.json('endpoint'),{})
                self.assertEqual(call.call_count,3);self.assertEqual(self.elapsed-start,182)
                self.assertNotIn(message,self.diagnostics.getvalue())

    def test_secondary_backoff_is_capped_and_attempt_limit_stops_reads(self):
        transport=G.GitHub('example/project')
        with mock.patch.object(transport,'_run',return_value=self.response(429,code=1)) as call:
            with self.assertRaisesRegex(G.DeliveryError,'attempt limit exhausted'):transport.json('endpoint')
        self.assertEqual(call.call_count,8);self.assertEqual(self.elapsed,3607)
        self.assertEqual(self.diagnostics.getvalue().count('waiting'),7)

    def test_confirmed_transient_json_reads_retry_with_short_backoff(self):
        transport=G.GitHub('example/project')
        failed=[self.response(status,b'private HTML error body',
                             {'X-RateLimit-Limit':5000,'X-RateLimit-Remaining':4615},1)
                for status in (500,502,503,504)]
        with mock.patch.object(transport,'_run',side_effect=failed+[self.response(payload=b'{"ok":true}')]) as call:
            self.assertEqual(transport.json('endpoint'),{'ok':True})
        self.assertEqual(call.call_count,5);self.assertEqual(self.sleeps,[3,5,9,17])
        self.assertEqual(transport.wait_remaining,transport.WAIT_BUDGET-34)
        self.assertTrue(all(c.args[0][c.args[0].index('--method')+1]=='GET' for c in call.call_args_list))
        self.assertIn('GitHub read retry (HTTP 500; limit=5000; remaining=4615)',self.diagnostics.getvalue())
        self.assertNotIn('private',self.diagnostics.getvalue());self.assertNotIn('rate limit',self.diagnostics.getvalue())

    def test_transient_retry_after_honors_numeric_and_date_minimums(self):
        for value,delay in ((30,31),('Thu, 01 Jan 1970 00:17:00 GMT',21)):
            with self.subTest(value=value):
                self.elapsed=0;transport=G.GitHub('example/project')
                with mock.patch.object(transport,'_run',side_effect=[self.response(503,headers={'Retry-After':value},code=1),self.response()]):
                    self.assertEqual(transport.json('endpoint'),{})
                self.assertEqual(self.elapsed,delay)

    def test_transient_attempt_deadline_and_shared_wait_limits(self):
        transport=G.GitHub('example/project')
        with mock.patch.object(transport,'_run',return_value=self.response(502,code=1)) as call:
            with self.assertRaisesRegex(G.DeliveryError,'attempt limit exhausted'):transport.json('endpoint')
        self.assertEqual(call.call_count,8);self.assertEqual(self.elapsed,189)
        transport=G.GitHub('example/project');transport.wait_remaining=4
        with mock.patch.object(transport,'_run',return_value=self.response(500,code=1)) as call:
            with self.assertRaisesRegex(G.DeliveryError,'wait budget exhausted'):transport.json('endpoint')
        self.assertEqual(call.call_count,2);self.assertEqual(transport.wait_remaining,1)
        transport=G.GitHub('example/project');transport.REQUEST_DEADLINE=2
        with mock.patch.object(transport,'_run',return_value=self.response(504,code=1)) as call:
            with self.assertRaisesRegex(G.DeliveryError,'request deadline exhausted'):transport.json('endpoint')
        self.assertEqual(call.call_count,1)

    def test_transient_read_retry_stops_at_permission_or_invalid_complete_response(self):
        for final in (self.response(403,b'{"message":"Resource not accessible by integration"}',code=1),
                      self.response(200,b'{'),self.response(200,b'{"duplicate":1,"duplicate":2}'),
                      self.response(200,b'partial',code=1)):
            with self.subTest(payload=final.stdout):
                transport=G.GitHub('example/project');start=self.elapsed
                with mock.patch.object(transport,'_run',side_effect=[self.response(500,code=1),final]) as call:
                    with self.assertRaises(G.DeliveryError):transport.json('endpoint')
                self.assertEqual(call.call_count,2);self.assertEqual(self.elapsed-start,3)

    def test_transient_pagination_discards_prefix_and_opaque_error_body(self):
        transport=G.GitHub('example/project')
        partial=self.response(payload=b'[{"id":1}]').stdout+b'\n'+self.response(502,b'private partial body\xff',code=1).stdout
        complete=self.response(payload=b'[{"id":2}]').stdout+b'\n'+self.response(payload=b'[{"id":3}]').stdout
        with mock.patch.object(transport,'_run',side_effect=[subprocess.CompletedProcess([],1,partial,b'private'),
                subprocess.CompletedProcess([],0,complete,b'')]) as call:
            self.assertEqual(transport.pages('endpoint'),[{'id':2},{'id':3}])
        self.assertEqual(call.call_count,2);self.assertEqual(self.elapsed,3)
        self.assertEqual(call.call_args_list[0].args,call.call_args_list[1].args)
        self.assertNotIn('private',self.diagnostics.getvalue())

    def test_transient_preflight_read_retries_before_one_write(self):
        transport=G.GitHub('example/project')
        with mock.patch.object(transport,'_run',side_effect=[self.response(503,code=1),self.quota(),self.response(201)]) as call:
            self.assertEqual(transport.json('endpoint',method='POST'),{})
        self.assertEqual([c.args[0][c.args[0].index('--method')+1] for c in call.call_args_list],['GET','GET','POST'])
        self.assertEqual(self.elapsed,3)

    def test_permission_and_other_failures_never_become_read_retries(self):
        responses=[self.response(403,b'{"message":"Resource not accessible by integration"}',
                                {'X-RateLimit-Remaining':50,'X-RateLimit-Reset':4600},1),
                   self.response(403,b'{"message":"unrelated API rate limit exceeded for someone"}',code=1),
                   self.response(403,b'{"other":"You have exceeded a secondary rate limit."}',code=1),
                   self.response(403,b'{"message":"You have exceeded a secondary rate limit.","message":"ambiguous"}',code=1),
                   self.response(403,b'x'*4097,{'Retry-After':'private invalid','X-RateLimit-Remaining':0,'X-RateLimit-Reset':'invalid'},1),
                   self.response(401,headers={'Retry-After':60},code=1),
                   self.response(501,headers={'Retry-After':60},code=1),self.response(505,headers={'Retry-After':60},code=1)]
        for response in responses:
            with self.subTest(response=response.returncode):
                transport=G.GitHub('example/project')
                with mock.patch.object(transport,'_run',return_value=response) as call:
                    with self.assertRaises(G.DeliveryError) as caught:transport.json('endpoint',missing=True)
                self.assertEqual(call.call_count,1);self.assertNotIn('private',str(caught.exception))
        self.assertFalse(self.sleeps)

    def test_deadline_and_cancellation_prevent_another_read(self):
        transport=G.GitHub('example/project');transport.REQUEST_DEADLINE=60
        with mock.patch.object(transport,'_run',return_value=self.response(429,code=1)) as call:
            with self.assertRaisesRegex(G.DeliveryError,'request deadline exhausted'):transport.json('endpoint')
        self.assertEqual(call.call_count,1);self.assertFalse(self.sleeps)
        transport=G.GitHub('example/project')
        with mock.patch.object(transport,'_run',return_value=self.response(429,code=1)) as call, \
                mock.patch.object(G.time,'sleep',side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):transport.json('endpoint')
        self.assertEqual(call.call_count,1)

    def test_direct_release_id_upload_uses_canonical_binary_endpoint_once(self):
        transport=G.GitHub('example/project')
        with tempfile.TemporaryDirectory() as temporary:
            path=Path(temporary)/'payload+1.tar.gz';path.write_bytes(b'\x00exact payload\xff')
            row={'id':3,'name':path.name,'state':'uploaded','size':path.stat().st_size,'digest':'sha256:'+G.archive.digest(path)}
            response=self.response(201,G.archive.encoded(row))
            with mock.patch.object(transport,'_headroom') as headroom, mock.patch.object(transport,'_run',return_value=response) as run:
                transport.upload_to(7,path)
            headroom.assert_called_once();run.assert_called_once()
            argv=run.call_args.args[0]
            self.assertIn('https://uploads.github.com/repos/example/project/releases/7/assets?name=payload%2B1.tar.gz',argv)
            self.assertIn('Content-Type: application/octet-stream',argv)
            self.assertIn('Content-Length: '+str(path.stat().st_size),argv)
            self.assertEqual(argv[argv.index('--input')+1],str(path));self.assertNotIn('release',argv)
            for status in (403,429,502):
                with mock.patch.object(transport,'_headroom'), mock.patch.object(transport,'_run',return_value=self.response(status,code=1)) as run:
                    with self.assertRaises(G.DeliveryError) as caught:transport.upload_to(7,path)
                    self.assertTrue(caught.exception.uncertain);run.assert_called_once()
            with mock.patch.object(transport,'_headroom'), mock.patch.object(transport,'_run',return_value=self.response(201,G.archive.encoded(dict(row,name='renamed')))):
                with self.assertRaisesRegex(G.DeliveryError,'could not be confirmed') as caught:transport.upload_to(7,path)
                self.assertTrue(caught.exception.uncertain)
            with mock.patch.object(transport,'_run') as run:
                for invalid in (0,True,-1,'7'):
                    with self.assertRaises(G.DeliveryError):transport.upload_to(invalid,path)
                run.assert_not_called()

    def test_nested_transport_clients_share_four_process_request_slots(self):
        from concurrent.futures import ThreadPoolExecutor
        entered=threading.Event();release=threading.Event();lock=threading.Lock();counts={'active':0,'peak':0}
        def run(argv, **options):
            with lock:
                counts['active']+=1;counts['peak']=max(counts['peak'],counts['active'])
                if counts['active']==4:entered.set()
            try:
                self.assertTrue(release.wait(timeout=5))
                return subprocess.CompletedProcess(argv,0,b'',b'')
            finally:
                with lock:counts['active']-=1
        spec=importlib.util.spec_from_file_location('independent_github_adapter',ROOT/'tools/github_release.py')
        alias=importlib.util.module_from_spec(spec);spec.loader.exec_module(alias)
        self.assertIs(alias.REQUEST_SLOTS,G.REQUEST_SLOTS)
        with mock.patch.object(G.subprocess,'run',side_effect=run), ThreadPoolExecutor(max_workers=8) as pool:
            futures=[pool.submit((G if index%2 else alias).GitHub('example/project')._run,['api','fixture'],timeout=5) for index in range(8)]
            try:
                self.assertTrue(entered.wait(timeout=5));self.assertEqual(counts['peak'],4)
            finally:release.set()
            for future in futures:future.result()
        self.assertEqual(counts,{'active':0,'peak':4})

    def test_cli_timeout_is_bounded_sanitized_and_never_retried(self):
        transport=G.GitHub('example/project')
        failure=subprocess.TimeoutExpired(['private command'],600,output=b'private output',stderr=b'private stderr')
        with mock.patch.object(G.subprocess,'run',side_effect=failure) as call:
            with self.assertRaisesRegex(G.DeliveryError,'bounded deadline') as caught:transport.json('endpoint')
        self.assertEqual(call.call_count,1);self.assertEqual(call.call_args.kwargs['timeout'],600)
        self.assertNotIn('private',str(caught.exception))

    def test_paginated_retry_discards_complete_prefix_and_restarts_inventory(self):
        transport=G.GitHub('example/project')
        failed=self.response(payload=b'[{"id":1}]').stdout+b'\n'+self.response(403,
            headers={'X-RateLimit-Remaining':0,'X-RateLimit-Reset':1010},code=1).stdout
        complete=self.response(payload='[{"id":2,"name":"caf\u00e9"}]'.encode()).stdout+b'\n'+self.response(payload=b'[{"id":3}]').stdout
        with mock.patch.object(transport,'_run',side_effect=[subprocess.CompletedProcess([],1,failed,b'private'),
                subprocess.CompletedProcess([],0,complete,b'')]) as call:
            self.assertEqual(transport.pages('endpoint'),[{'id':2,'name':'caf\u00e9'},{'id':3}])
        self.assertEqual(call.call_count,2);self.assertEqual(self.elapsed,11)
        self.assertEqual(call.call_args_list[0].args,call.call_args_list[1].args)
        self.assertIn('--include',call.call_args.args[0]);self.assertNotIn('--slurp',call.call_args.args[0])

    def test_download_retry_discards_partial_file_and_preserves_binary_bytes(self):
        for status in (429,500,502,503,504):
            with self.subTest(status=status):self.check_download_retry(status)

    def check_download_retry(self,status):
        transport=G.GitHub('example/project');attempts=[];start=self.elapsed
        payload=b'\x00\r\nHTTP/2 403\n\nunaltered binary\xff'
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);path=root/'asset'
            def run(arguments,*,output,**kwargs):
                self.assertFalse(path.exists())
                if attempts:self.assertFalse(Path(attempts[-1]).exists())
                attempts.append(output.name)
                response=self.response(status,b'partial failed body\xff',{'Retry-After':1},1) if len(attempts)==1 else self.response(payload=payload)
                output.write(response.stdout)
                return subprocess.CompletedProcess([],response.returncode,None,b'private')
            with mock.patch.object(transport,'_run',side_effect=run):transport.download(123,path)
            self.assertEqual(path.read_bytes(),payload);self.assertEqual(list(root.iterdir()),[path])
        self.assertEqual(len(set(attempts)),2);self.assertEqual(self.elapsed-start,2)

    def test_download_failures_leave_no_destination_and_never_reuse_partial_bytes(self):
        for response in (self.response(200,b'partial body',code=1),self.response(206,b'partial content'),
                         subprocess.CompletedProcess([],0,b'HTTP/2 200\nX-Large: '+b'x'*G.HTTP_HEADER_LIMIT+b'\n\nbody',b'')):
            with self.subTest(code=response.returncode),tempfile.TemporaryDirectory() as temporary:
                transport=G.GitHub('example/project');path=Path(temporary)/'asset'
                def run(arguments,*,output,**kwargs):
                    output.write(response.stdout);return subprocess.CompletedProcess([],response.returncode,None,b'private')
                with mock.patch.object(transport,'_run',side_effect=run) as call:
                    with self.assertRaises(G.DeliveryError):transport.download(123,path)
                self.assertEqual(call.call_count,1);self.assertEqual(list(Path(temporary).iterdir()),[])
                path.write_bytes(b'existing')
                with mock.patch.object(transport,'_run') as call:
                    with self.assertRaisesRegex(G.DeliveryError,'destination must be new'):transport.download(123,path)
                call.assert_not_called();self.assertEqual(path.read_bytes(),b'existing')

    @staticmethod
    def core_headers(remaining=800, reset=4600):
        return {'X-RateLimit-Limit': '1000', 'X-RateLimit-Remaining': str(remaining),
                'X-RateLimit-Reset': str(reset), 'X-RateLimit-Resource': 'core'}

    def test_recent_core_response_headers_admit_multiple_writes_without_quota_probes(self):
        transport = G.GitHub('example/project')
        responses = [self.response(headers=self.core_headers()), self.response(201), self.response()]
        with mock.patch.object(transport, '_run', side_effect=responses) as run:
            transport.json('metadata')
            transport.json('first', method='POST')
            transport.json('second', method='PATCH')
        self.assertEqual(run.call_count, 3)
        self.assertFalse(any(call.args[0][-1] == 'rate_limit' for call in run.call_args_list))
        self.assertFalse(self.sleeps)

    def test_missing_invalid_or_noncore_quota_headers_use_one_fallback_probe(self):
        valid = self.core_headers()
        for headers in ({}, dict(valid, **{'X-RateLimit-Remaining': '1001'}),
                        dict(valid, **{'X-RateLimit-Remaining': '-1'}),
                        dict(valid, **{'X-RateLimit-Resource': 'search'}),
                        {key: value for key, value in valid.items() if key != 'X-RateLimit-Resource'}):
            with self.subTest(headers=headers):
                transport = G.GitHub('example/project')
                with mock.patch.object(transport, '_run', side_effect=[self.response(headers=headers), self.quota(), self.response(201)]) as run:
                    transport.json('metadata'); transport.json('write', method='POST')
                self.assertEqual(run.call_count, 3)
                self.assertEqual(run.call_args_list[1].args[0][-1], 'rate_limit')
        self.assertFalse(self.sleeps)

    def test_stale_or_expired_quota_observation_is_reprobed_before_mutation(self):
        for expired in (False, True):
            with self.subTest(expired=expired):
                transport = G.GitHub('example/project')
                reset = int(1000 + self.elapsed + (1 if expired else 3600))
                with mock.patch.object(transport, '_run', side_effect=[self.response(headers=self.core_headers(reset=reset)), self.quota(reset=reset+3600), self.response(201)]) as run:
                    transport.json('metadata')
                    self.elapsed += 2 if expired else transport.QUOTA_MAX_AGE + 1
                    transport.json('write', method='POST')
                self.assertEqual(run.call_count, 3)
                self.assertEqual(run.call_args_list[1].args[0][-1], 'rate_limit')
        self.assertFalse(self.sleeps)

    def test_write_admission_decrements_observed_headroom_before_the_next_write(self):
        transport = G.GitHub('example/project')
        responses = [self.response(headers=self.core_headers(128)), self.response(201), self.quota(reset=8200), self.response(201)]
        with mock.patch.object(transport, '_run', side_effect=responses) as run:
            transport.json('metadata'); transport.json('first', method='POST'); transport.json('second', method='POST')
        self.assertEqual([call.args[0][-1] for call in run.call_args_list], ['metadata', 'first', 'rate_limit', 'second'])
        self.assertFalse(self.sleeps)

    def test_out_of_order_same_window_quota_headers_never_restore_spent_headroom(self):
        transport = G.GitHub('example/project')
        responses = [self.response(headers=self.core_headers(128)), self.response(headers=self.core_headers(900)),
                     self.response(201), self.quota(reset=8200), self.response(201)]
        with mock.patch.object(transport, '_run', side_effect=responses) as run:
            transport.json('first-observation'); transport.json('late-old-observation')
            transport.json('first-write', method='POST'); transport.json('second-write', method='POST')
        self.assertEqual(run.call_count, 5)
        self.assertEqual(run.call_args_list[3].args[0][-1], 'rate_limit')

    def test_fresh_quota_probe_admits_write_even_when_local_estimate_is_lower(self):
        transport = G.GitHub('example/project')
        responses = [self.response(headers=self.core_headers(128)), self.response(201),
                     self.quota(remaining=128), self.response(201)]
        with mock.patch.object(transport, '_run', side_effect=responses) as run:
            transport.json('metadata'); transport.json('first', method='POST'); transport.json('second', method='POST')
        self.assertEqual([call.args[0][-1] for call in run.call_args_list], ['metadata', 'first', 'rate_limit', 'second'])
        self.assertFalse(self.sleeps)

    def test_concurrent_writes_share_one_missing_cache_probe_and_keep_parallelism(self):
        from concurrent.futures import ThreadPoolExecutor
        transport = G.GitHub('example/project'); writes = threading.Barrier(4)
        def run(arguments, **kwargs):
            if arguments[-1] == 'rate_limit': return self.quota()
            writes.wait(timeout=5)
            return self.response(201)
        with mock.patch.object(transport, '_run', side_effect=run) as observed:
            with ThreadPoolExecutor(max_workers=4) as pool:
                futures = [pool.submit(transport.json, 'write-' + str(index), method='POST') for index in range(4)]
                self.assertEqual([future.result() for future in futures], [{}, {}, {}, {}])
        self.assertEqual(observed.call_count, 5)
        self.assertEqual(sum(call.args[0][-1] == 'rate_limit' for call in observed.call_args_list), 1)
        self.assertFalse(self.sleeps)

    def test_waiting_for_another_quota_probe_has_a_bounded_deadline(self):
        transport = G.GitHub('example/project'); transport.REQUEST_DEADLINE = 0.01
        transport._quota_probe_lock.acquire()
        try:
            with mock.patch.object(transport, '_run') as run:
                with self.assertRaises(G.DeliveryError): transport.json('write', method='POST')
            run.assert_not_called()
        finally:
            transport._quota_probe_lock.release()

    def test_cached_headroom_never_retries_an_uncertain_mutation(self):
        transport = G.GitHub('example/project')
        responses = [self.response(headers=self.core_headers()), self.response(429, headers={'Retry-After': '60'}, code=1)]
        with mock.patch.object(transport, '_run', side_effect=responses) as run:
            transport.json('metadata')
            with self.assertRaises(G.DeliveryError) as caught: transport.json('write', method='POST')
        self.assertTrue(caught.exception.uncertain); self.assertEqual(run.call_count, 2); self.assertFalse(self.sleeps)

    def test_direct_upload_reuses_metadata_headers_and_updates_quota_for_following_write(self):
        transport = G.GitHub('example/project')
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / 'payload.tar.gz'; path.write_bytes(b'verified payload')
            row = {'id': 3, 'name': path.name, 'state': 'uploaded', 'size': path.stat().st_size,
                   'digest': 'sha256:' + G.archive.digest(path)}
            responses = [self.response(headers=self.core_headers()),
                         self.response(201, G.archive.encoded(row), headers=self.core_headers(127)),
                         self.quota(reset=8200), self.response(201)]
            with mock.patch.object(transport, '_run', side_effect=responses) as run:
                transport.json('metadata'); transport.upload_to(7, path); transport.json('write', method='POST')
        self.assertEqual(run.call_count, 4)
        self.assertEqual(run.call_args_list[2].args[0][-1], 'rate_limit')
        self.assertFalse(self.sleeps)

    def test_low_headroom_waits_before_one_mutation_and_caps_at_token_limit(self):
        transport=G.GitHub('example/project')
        with mock.patch.object(transport,'_run',side_effect=[self.quota(127,reset=1010),self.quota(),self.response(201)]) as call:
            self.assertEqual(transport.json('endpoint',method='POST',body={'name':'v1'}),{})
        self.assertEqual(self.elapsed,11)
        self.assertEqual([c.args[0][c.args[0].index('--method')+1] for c in call.call_args_list],['GET','GET','POST'])
        self.assertTrue(all(c.args[0][-1]=='rate_limit' for c in call.call_args_list[:2]))
        transport=G.GitHub('example/project');start=self.elapsed
        with mock.patch.object(transport,'_run',side_effect=[self.quota(60,60),self.response(201)]) as call:
            self.assertEqual(transport.json('endpoint',method='POST'),{})
        self.assertEqual(call.call_count,2);self.assertEqual(self.elapsed,start)

    def test_mutation_rate_or_partial_response_is_uncertain_and_never_replayed(self):
        for method in ('POST','PATCH','PUT','DELETE'):
            for response in (self.response(403,headers={'Retry-After':60},code=1),self.response(429,code=1),
                             self.response(200,b'partial',code=1),self.response(200,b'{'),
                             *(self.response(status,headers={'Retry-After':1},code=1) for status in (500,502,503,504))):
                with self.subTest(method=method,code=response.returncode):
                    transport=G.GitHub('example/project')
                    with mock.patch.object(transport,'_run',side_effect=[self.quota(),response]) as call:
                        with self.assertRaises(G.DeliveryError) as caught:transport.json('endpoint',method=method,body={})
                    self.assertTrue(caught.exception.uncertain);self.assertEqual(call.call_count,2)
        self.assertFalse(self.sleeps)

    def test_upload_preflight_does_not_authorize_retry_after_rate_failure_or_timeout(self):
        for failure in (self.response(429,headers={'Retry-After':60},code=1),
                        *(self.response(status,headers={'Retry-After':1},code=1) for status in (500,502,503,504)),
                        subprocess.TimeoutExpired(['private'],600,stderr=b'private')):
            with self.subTest(failure=type(failure).__name__):
                transport=G.GitHub('example/project')
                with mock.patch.object(G.subprocess,'run',side_effect=[self.quota(),failure]) as call:
                    with self.assertRaises(G.DeliveryError) as caught:transport.upload('v1',Path('/owned/file.zip'))
                self.assertTrue(caught.exception.uncertain);self.assertEqual(call.call_count,2)
                self.assertEqual(call.call_args.args[0][1:3],['release','upload'])
                self.assertNotIn('private',str(caught.exception))
        self.assertFalse(self.sleeps)

    def test_preflight_rate_retries_and_low_headroom_share_eight_attempts(self):
        transport=G.GitHub('example/project')
        responses=[self.response(429,headers={'Retry-After':0},code=1),self.quota(127,reset=1000)]*4
        with mock.patch.object(transport,'_run',side_effect=responses) as call:
            with self.assertRaisesRegex(G.DeliveryError,'quota preflight attempt limit exhausted'):
                transport.json('endpoint',method='POST')
        self.assertEqual(call.call_count,8);self.assertEqual(self.elapsed,10)
        self.assertTrue(all(c.args[0][-1]=='rate_limit' for c in call.call_args_list))

    def test_invalid_or_exhausted_preflight_never_sends_a_write(self):
        for response in (self.response(),self.quota(-1),self.quota(1001),self.quota(0,reset=999999)):
            with self.subTest(response=response.stdout[:20]):
                transport=G.GitHub('example/project')
                with mock.patch.object(transport,'_run',return_value=response) as call:
                    with self.assertRaises(G.DeliveryError) as caught:transport.json('endpoint',method='POST')
                self.assertFalse(caught.exception.uncertain);self.assertEqual(call.call_count,1)
                self.assertEqual(call.call_args.args[0][-1],'rate_limit')
        self.assertFalse(self.sleeps)

    def test_ambiguous_or_oversized_headers_fail_without_using_body_as_rate_evidence(self):
        for raw in (b'HTTP/2 403\nRetry-After: 1\nretry-after: 2\n\n{}',
                    b'HTTP/2 403\nPrivate-No-Colon\n\n{}',
                    b'HTTP/2 403\nX-Large: '+b'x'*G.HTTP_HEADER_LIMIT+b'\n\n{}'):
            transport=G.GitHub('example/project')
            with mock.patch.object(transport,'_run',return_value=subprocess.CompletedProcess([],1,raw,b'private')) as call:
                with self.assertRaises(G.DeliveryError) as caught:transport.json('endpoint')
            self.assertEqual(call.call_count,1);self.assertNotIn('Private',str(caught.exception))
        self.assertFalse(self.sleeps)

    def test_invalid_location_and_untrusted_duplicate_fields_fail(self):
        for repository in ('--help','owner/repo/extra','../repo','owner/repo\n'):
            with self.assertRaises(ValueError):G.location(repository)
        for tag in ('../v1','--target=x','v 1','a/b'):
            with self.assertRaises(ValueError):G.location('example/project',tag)
        with self.assertRaises(ValueError):G.parse('{"id":1,"id":2}')

    def test_paginated_inventory_is_complete_and_never_uses_embedded_assets(self):
        transport=G.GitHub('example/project')
        raw=b'\n'.join(self.response(payload=page).stdout for page in (b'[{"id":1}]',b'[]',b'[{"id":2}]'))
        with mock.patch.object(transport,'_run',return_value=subprocess.CompletedProcess([],0,raw,b'')) as call:
            self.assertEqual(transport.pages('repos/example/project/releases?per_page=100'),[{'id':1},{'id':2}])
            self.assertIn('--paginate',call.call_args.args[0]);self.assertNotIn('--slurp',call.call_args.args[0])
        with mock.patch.object(transport,'_run',return_value=self.response(payload=b'{"assets":[]}')):
            with self.assertRaises(ValueError):transport.pages('endpoint')

    @staticmethod
    def release_row(identity, tag='other'):
        return dict(id=identity, tag_name=tag, name=tag, draft=True, prerelease=True)

    def release_page(self, rows, next_page=None, **headers):
        if next_page is not None:
            headers['Link'] = ('<https://api.github.com/repos/example/project/releases?per_page=100&page='
                               + str(next_page) + '>; rel="next"')
        return self.response(payload=json.dumps(rows).encode(), headers=headers)

    def test_initial_release_discovery_preserves_successful_request_count_and_never_waits(self):
        for responses in ([self.release_page([self.release_row(7, 'new')])],
                          [self.release_page([self.release_row(1)], 2),
                           self.release_page([self.release_row(7, 'new')])]):
            with self.subTest(pages=len(responses)):
                metrics = G.RequestMetrics(); transport = G.GitHub('example/project', metrics=metrics)
                remote = G.Remote('example/project', transport)
                with mock.patch.object(transport, '_run', side_effect=responses) as call:
                    self.assertEqual(remote.find('new'), self.release_row(7, 'new'))
                self.assertEqual(call.call_count, len(responses))
                self.assertEqual(metrics.snapshot()['api_responses'], len(responses))
                self.assertEqual(call.call_args_list[0].args[0][-1],
                                 'repos/example/project/releases?per_page=100')
                if len(responses) > 1:
                    self.assertEqual(call.call_args_list[1].args[0][-1],
                                     'repos/example/project/releases?per_page=100&page=2')
                self.assertTrue(all('--paginate' not in item.args[0] and
                                    item.args[0][item.args[0].index('--method') + 1] == 'GET'
                                    for item in call.call_args_list))
        self.assertFalse(self.sleeps)

    def test_repeated_release_id_restarts_complete_discovery_and_discards_all_prior_pages(self):
        transport = G.GitHub('example/project'); remote = G.Remote('example/project', transport)
        responses = [self.release_page([self.release_row(1), self.release_row(7, 'new')], 2),
                     self.release_page([self.release_row(1)]),
                     self.release_page([self.release_row(2)], 2),
                     self.release_page([self.release_row(9, 'new')])]
        with mock.patch.object(transport, '_run', side_effect=responses) as call:
            self.assertEqual(remote.find('new'), self.release_row(9, 'new'))
        self.assertEqual(call.call_count, 4); self.assertEqual(self.sleeps, [3])
        self.assertEqual(call.call_args_list[0].args, call.call_args_list[2].args)
        self.assertEqual(call.call_args_list[1].args, call.call_args_list[3].args)
        self.assertIn('repeated release ID across response pages', self.diagnostics.getvalue())

    def test_release_repetition_is_bounded_and_never_establishes_absence(self):
        transport = G.GitHub('example/project'); remote = G.Remote('example/project', transport)
        responses = [self.release_page([self.release_row(1)], 2),
                     self.release_page([self.release_row(1)])] * 3
        with mock.patch.object(transport, '_run', side_effect=responses) as call:
            with self.assertRaisesRegex(G.DeliveryError, 'inventory retry limit exhausted'):
                remote.find('new', required=False)
        self.assertEqual(call.call_count, 6); self.assertEqual(self.sleeps, [3, 5])
        self.assertEqual(transport.wait_remaining, transport.WAIT_BUDGET - 8)

    def test_discarded_release_match_cannot_survive_a_successful_absence_read(self):
        transport = G.GitHub('example/project'); remote = G.Remote('example/project', transport)
        responses = [self.release_page([self.release_row(7, 'new')], 2),
                     self.release_page([self.release_row(7, 'new')]), self.release_page([])]
        with mock.patch.object(transport, '_run', side_effect=responses) as call:
            self.assertIsNone(remote.find('new', required=False))
        self.assertEqual(call.call_count, 3); self.assertEqual(self.sleeps, [3])

    def test_same_page_release_duplicates_remain_nonretryable(self):
        transport = G.GitHub('example/project')
        response = self.release_page([self.release_row(1), self.release_row(1)])
        with mock.patch.object(transport, '_run', return_value=response) as call:
            with self.assertRaisesRegex(G.DeliveryError, 'duplicate release inventory'):
                G.Remote('example/project', transport).find('new', required=False)
        self.assertEqual(call.call_count, 1); self.assertFalse(self.sleeps)

    def test_malformed_release_records_never_gain_inventory_retries(self):
        invalid = [None, dict(self.release_row(1), id=True), dict(self.release_row(1), tag_name=None),
                   dict(self.release_row(1), name=None), dict(self.release_row(1), draft=1),
                   dict(self.release_row(1), prerelease=None)]
        for row in invalid:
            for late in (False, True):
                with self.subTest(row=row, late=late):
                    transport = G.GitHub('example/project')
                    responses = ([self.release_page([self.release_row(1)], 2),
                                  self.release_page([self.release_row(1), row])] if late
                                 else [self.release_page([row], 2)])
                    with mock.patch.object(transport, '_run', side_effect=responses) as call:
                        with self.assertRaises(G.DeliveryError):
                            G.Remote('example/project', transport).find('new', required=False)
                    self.assertEqual(call.call_count, len(responses))
        self.assertFalse(self.sleeps)

    def test_ambiguous_release_tags_remain_errors_despite_an_unrelated_page_shift(self):
        transport = G.GitHub('example/project')
        responses = [self.release_page([self.release_row(1), self.release_row(7, 'new')], 2),
                     self.release_page([self.release_row(1), self.release_row(9, 'new')])]
        with mock.patch.object(transport, '_run', side_effect=responses) as call:
            with self.assertRaisesRegex(G.DeliveryError, 'duplicate release tags require inspection'):
                G.Remote('example/project', transport).find('new')
        self.assertEqual(call.call_count, 2); self.assertFalse(self.sleeps)

    def test_release_access_and_malformed_stream_failures_do_not_retry_a_seen_page_shift(self):
        for final in (self.response(401, code=1), self.response(403, code=1),
                      self.response(payload=b'{'), self.response(payload=b'[{"id":1,"id":2}]')):
            with self.subTest(final=final.stdout):
                transport = G.GitHub('example/project')
                responses = [self.release_page([self.release_row(1)], 2),
                             self.release_page([self.release_row(1)], 3), final]
                with mock.patch.object(transport, '_run', side_effect=responses) as call:
                    with self.assertRaises(G.DeliveryError):
                        G.Remote('example/project', transport).find('new', required=False)
                self.assertEqual(call.call_count, 3)
        self.assertFalse(self.sleeps)

    def test_release_transport_and_inventory_retries_share_one_attempt_limit(self):
        transport = G.GitHub('example/project'); transport.MAX_ATTEMPTS = 4
        responses = [self.response(503, code=1), self.release_page([self.release_row(1)], 2),
                     self.release_page([self.release_row(1)]), self.response(503, code=1),
                     self.release_page([self.release_row(2)], 2), self.release_page([self.release_row(2)])]
        with mock.patch.object(transport, '_run', side_effect=responses) as call:
            with self.assertRaisesRegex(G.DeliveryError, 'attempt limit exhausted'):
                G.Remote('example/project', transport).find('new', required=False)
        self.assertEqual(call.call_count, 6); self.assertEqual(self.sleeps, [3, 5, 9])

    def test_release_transport_and_inventory_retries_share_one_request_budget(self):
        for final in ('http', 'inventory'):
            with self.subTest(final=final):
                self.elapsed = 0; self.sleeps.clear()
                transport = G.GitHub('example/project')
                responses = [self.release_page([self.release_row(1)], 2),
                             self.release_page([self.release_row(1)])]
                if final == 'http':responses.append(self.response(503, code=1))
                else:responses += [self.release_page([self.release_row(2)], 2),
                                   self.release_page([self.release_row(2)])]
                transport.RELEASE_REQUEST_LIMIT = len(responses)
                with mock.patch.object(transport, '_run', side_effect=responses) as call:
                    with self.assertRaisesRegex(G.DeliveryError, 'API-request budget exhausted'):
                        G.Remote('example/project', transport).find('new', required=False)
                self.assertEqual(call.call_count, len(responses)); self.assertEqual(self.sleeps, [3])

    def test_release_inventory_deadline_and_shared_wait_budget_stop_recovery(self):
        for limit in ('deadline', 'wait'):
            with self.subTest(limit=limit):
                transport = G.GitHub('example/project')
                if limit == 'deadline':transport.REQUEST_DEADLINE = 2
                else:transport.wait_remaining = 2
                responses = [self.release_page([self.release_row(1)], 2),
                             self.release_page([self.release_row(1)])]
                with mock.patch.object(transport, '_run', side_effect=responses) as call:
                    with self.assertRaisesRegex(G.DeliveryError, 'deadline exhausted' if limit == 'deadline'
                                                else 'wait budget exhausted'):
                        G.Remote('example/project', transport).find('new', required=False)
                self.assertEqual(call.call_count, 2)
        self.assertFalse(self.sleeps)

    def test_inventory_wait_and_transport_wait_charge_the_same_remaining_budget(self):
        transport = G.GitHub('example/project'); transport.wait_remaining = 4
        responses = [self.release_page([self.release_row(1)], 2),
                     self.release_page([self.release_row(1)]), self.response(503, code=1)]
        with mock.patch.object(transport, '_run', side_effect=responses) as call:
            with self.assertRaisesRegex(G.DeliveryError, 'wait budget exhausted'):
                G.Remote('example/project', transport).find('new', required=False)
        self.assertEqual(call.call_count, 3); self.assertEqual(self.sleeps, [3])
        self.assertEqual(transport.wait_remaining, 1)

    def test_release_inventory_page_and_complete_response_size_limits_are_not_retried(self):
        transport = G.GitHub('example/project'); transport.RELEASE_PAGE_LIMIT = 2
        responses = [self.release_page([self.release_row(1)], 2),
                     self.release_page([self.release_row(2)], 3)]
        with mock.patch.object(transport, '_run', side_effect=responses) as call:
            with self.assertRaisesRegex(G.DeliveryError, 'page limit exhausted'):
                G.Remote('example/project', transport).find('new', required=False)
        self.assertEqual(call.call_count, 2)
        transport = G.GitHub('example/project')
        responses = [self.release_page([self.release_row(1)], 2), self.release_page([self.release_row(2)])]
        with mock.patch.object(transport, '_run', side_effect=responses) as call, \
                mock.patch.object(G, 'HTTP_JSON_LIMIT', max(len(row.stdout) for row in responses)):
            with self.assertRaisesRegex(G.DeliveryError, 'pagination exceeds supported inventory limit'):
                G.Remote('example/project', transport).find('new', required=False)
        self.assertEqual(call.call_count, 2); self.assertFalse(self.sleeps)

    def test_release_pagination_links_cannot_escape_or_skip_the_bounded_inventory(self):
        links = ['<https://api.github.com/repos/example/project/releases?per_page=100&page=3>; rel="next"',
                 '<https://untrusted.invalid/releases?per_page=100&page=2>; rel="next"',
                 '<https://api.github.com/repos/other/project/releases?per_page=100&page=2>; rel="next"',
                 '<https://api.github.com/repos/example/project/releases?per_page=99&page=2>; rel="next"',
                 '<https://api.github.com/repos/example/project/releases?per_page=100&page=2&page=3>; rel="next"',
                 '<https://api.github.com/repos/example/project/releases?per_page=100&page>; rel="next"',
                 '<https://api.github.com/repos/example/project/releases?per_page=100&page=9>; rel="last"',
                 '<https://api.github.com/repos/example/project/releases?per_page=100&page=2>; rel="next", '
                 '<https://api.github.com/repos/example/project/releases?per_page=100&page=1>; rel="last"',
                 '<https://api.github.com/repos/example/project/releases?per_page=100&page=2>; rel="first"',
                 '<https://api.github.com/repos/example/project/releases?per_page=100&page=1>; rel="prev"',
                 'opaque private header']
        links.append(links[0] + ', ' + links[0])
        for link in links:
            with self.subTest(link=link):
                transport = G.GitHub('example/project')
                with mock.patch.object(transport, '_run', return_value=self.release_page([], Link=link)) as call:
                    with self.assertRaises(G.DeliveryError) as caught:
                        G.Remote('example/project', transport).find('new', required=False)
                self.assertEqual(call.call_count, 1); self.assertNotIn('private', str(caught.exception))
        self.assertFalse(self.sleeps)

    def test_release_pagination_repository_id_links_preserve_safe_endpoint_and_no_trailing_call(self):
        transport = G.GitHub('example/project')
        link = ('<https://api.github.com/repositories/123/releases?page=2&per_page=100>; rel="next", '
                '<https://api.github.com/repositories/123/releases?page=2&per_page=100>; rel="last"')
        final = '<https://api.github.com/repositories/123/releases?page=1&per_page=100>; rel="prev"'
        responses = [self.release_page([self.release_row(1)], Link=link),
                     self.release_page([self.release_row(7, 'new')], Link=final)]
        with mock.patch.object(transport, '_run', side_effect=responses) as call:
            self.assertEqual(G.Remote('example/project', transport).find('new'), self.release_row(7, 'new'))
        self.assertEqual(call.call_count, 2)
        self.assertEqual(call.call_args_list[1].args[0][-1],
                         'repos/example/project/releases?per_page=100&page=2')
        self.assertFalse(self.sleeps)

    def test_release_pagination_canonical_repository_case_preserves_safe_endpoint(self):
        transport = G.GitHub('Example/Project')
        responses = [self.release_page([self.release_row(1)], 2),
                     self.release_page([self.release_row(7, 'new')])]
        with mock.patch.object(transport, '_run', side_effect=responses) as call:
            self.assertEqual(G.Remote('Example/Project', transport).find('new'), self.release_row(7, 'new'))
        self.assertEqual(call.call_count, 2)
        self.assertEqual(call.call_args_list[1].args[0][-1],
                         'repos/Example/Project/releases?per_page=100&page=2')
        self.assertFalse(self.sleeps)

    def test_pagination_rejects_partial_or_ambiguous_complete_output(self):
        transport=G.GitHub('example/project')
        for raw in (b'["\xff"]', b'', b'[] trailing', b'[] {"id":1}', b'[{"id":1}] [{"id":2,"id":3}]',
                    b'[{"id":1}] [NaN]', b'[] [', b'[]\xff'):
            with self.subTest(raw=raw), mock.patch.object(transport,'_run',
                    return_value=self.response(payload=raw)):
                with self.assertRaises(ValueError):transport.pages('endpoint')
        with mock.patch.object(transport,'_run',
                return_value=self.response(payload=b'[{"id":1}]',code=1)):
            with self.assertRaisesRegex(G.DeliveryError,'complete remote pagination failed'):
                transport.pages('endpoint')
        with mock.patch.object(transport,'_run',
                return_value=self.response(payload=b'[]\n')):
            self.assertEqual([],transport.pages('endpoint'))

    def test_transport_never_uses_shell_or_clobber_and_never_prints_credentials(self):
        transport=G.GitHub('example/project')
        with mock.patch.object(G.subprocess,'run',side_effect=[self.quota(),subprocess.CompletedProcess([],1,b'',b'private token value')]) as call:
            with self.assertRaises(G.DeliveryError) as caught:transport.upload('v1',Path('/owned/file.zip'))
        argv=call.call_args.args[0]
        self.assertEqual(argv,['gh','release','upload','v1','--repo','github.com/example/project',str(Path('/owned/file.zip'))])
        self.assertNotIn('clobber',' '.join(argv));self.assertNotIn('private token',str(caught.exception))
        self.assertNotIn('shell',call.call_args.kwargs)

    def test_fake_release_by_id_only_treats_missing_as_optional_when_requested(self):
        transport=FakeGitHub();endpoint='repos/example/project/releases/7'
        self.assertIsNone(transport.json(endpoint,missing=True))
        with self.assertRaisesRegex(G.DeliveryError,'release ID missing'):transport.json(endpoint)
        row=dict(id=7,tag_name='new',name='new',draft=True,prerelease=True)
        transport.releases.append(row)
        for missing in (False,True):
            self.assertEqual(row,transport.json(endpoint,missing=missing))
        self.assertFalse(transport.mutations)

    def test_created_release_visibility_waits_by_read_only_and_exact_id(self):
        remote=G.Remote('example/project',FakeGitHub())
        row=dict(id=7,tag_name='new',name='new',draft=True,prerelease=True)
        with mock.patch.object(remote.transport,'json',side_effect=[None,None,row]) as read, \
                mock.patch.object(remote.transport,'pages',side_effect=AssertionError('unrelated inventory')), \
                mock.patch.object(G.time,'sleep') as sleep:
            self.assertEqual(row,remote.wait_find('new',release_id=7))
        self.assertEqual(read.call_args_list,[mock.call('repos/example/project/releases/7',missing=True)]*3)
        self.assertEqual(sleep.call_args_list,[mock.call(.25),mock.call(.5)])
        self.assertFalse(remote.transport.mutations)

    def test_created_release_observation_rejects_wrong_identity_and_lifecycle(self):
        remote=G.Remote('example/project',FakeGitHub())
        row=dict(id=7,tag_name='new',name='new',draft=True,prerelease=True)
        for change in ({'id':8},{'tag_name':'other'},{'draft':1},{'prerelease':None},{'name':None}):
            with self.subTest(change=change), mock.patch.object(remote.transport,'json',return_value=dict(row,**change)) as read, \
                    mock.patch.object(remote.transport,'pages',side_effect=AssertionError('inventory fallback')), \
                    self.assertRaises(G.DeliveryError):
                remote.wait_find('new',release_id=7)
            self.assertEqual(read.call_count,1)
        for identity in (True,0,-1,'7'):
            with self.subTest(identity=identity), mock.patch.object(remote.transport,'json') as read, \
                    self.assertRaisesRegex(G.DeliveryError,'positive release identity'):
                remote.wait_find('new',release_id=identity)
            read.assert_not_called()
        self.assertFalse(remote.transport.mutations)

    def test_created_release_missing_visibility_is_bounded_without_discovery_fallback(self):
        remote=G.Remote('example/project',FakeGitHub())
        with mock.patch.object(remote.transport,'json',return_value=None) as read, \
                mock.patch.object(remote.transport,'pages',side_effect=AssertionError('inventory fallback')), \
                mock.patch.object(G.time,'sleep') as sleep, self.assertRaisesRegex(G.DeliveryError,'not visible'):
            remote.wait_find('new',release_id=7)
        self.assertEqual(read.call_count,7)
        self.assertEqual([call.args[0] for call in sleep.call_args_list],[.25,.5,1,2,4,8])
        self.assertFalse(remote.transport.mutations)

    def test_created_release_access_error_is_not_missing_visibility(self):
        remote=G.Remote('example/project',FakeGitHub())
        with mock.patch.object(remote.transport,'json',side_effect=G.DeliveryError('access denied')) as read, \
                mock.patch.object(G.time,'sleep') as sleep, self.assertRaisesRegex(G.DeliveryError,'access denied'):
            remote.wait_find('new',release_id=7)
        self.assertEqual(read.call_count,1);sleep.assert_not_called();self.assertFalse(remote.transport.mutations)

    def test_unknown_release_observation_keeps_strict_complete_inventory(self):
        remote=G.Remote('example/project',FakeGitHub())
        row=dict(id=7,tag_name='new',name='new',draft=True,prerelease=True)
        with mock.patch.object(remote.transport,'pages',side_effect=[[],[row]]) as read, \
                mock.patch.object(G.time,'sleep'):
            self.assertEqual(row,remote.wait_find('new'))
        self.assertEqual(read.call_count,2)
        with mock.patch.object(remote.transport,'pages',return_value=[row,row]), \
                self.assertRaisesRegex(G.DeliveryError,'duplicate release inventory'):
            remote.wait_find('new')
        self.assertFalse(remote.transport.mutations)

    def test_access_failure_is_never_a_cache_miss(self):
        transport=G.GitHub('example/project')
        for raw in (b'HTTP/2 403 Forbidden\n\n{}',b'HTTP/2 500 Server Error\n\n{}',b'unknown'):
            with mock.patch.object(transport,'_run',return_value=subprocess.CompletedProcess([],1,raw,b'secret')):
                with self.assertRaises(ValueError):transport.json('endpoint',missing=True)


class PublicPayloadTests(unittest.TestCase):
    def setUp(self):
        self.temporary=tempfile.TemporaryDirectory();self.addCleanup(self.temporary.cleanup)
        self.root=Path(self.temporary.name)
        self.url='https://github.com/example/project/releases/download/v1/file.tar.gz'
        self.payload=b'complete public bytes'

    def response(self,payload=None,url=None,status=200):
        response=io.BytesIO(self.payload if payload is None else payload)
        response.url=url or 'https://release-assets.githubusercontent.com/asset?sig=hidden'
        response.status=status
        return response

    def test_public_bytes_use_no_cli_or_authorization_and_have_separate_metrics(self):
        metrics=G.RequestMetrics();transport=G.GitHub('example/project',metrics=metrics)
        with mock.patch.object(G,'build_opener') as opener,mock.patch.object(transport,'_run') as cli:
            opener.return_value.open.return_value=self.response()
            transport.download_public(self.url,self.root/'output',len(self.payload),G.sha(self.payload))
            request=opener.return_value.open.call_args.args[0]
            self.assertNotIn('Authorization',request.headers);self.assertEqual(self.url,request.full_url)
            cli.assert_not_called()
        self.assertEqual(self.payload,(self.root/'output').read_bytes())
        self.assertEqual(1,metrics.snapshot()['public_downloads']);self.assertEqual(0,metrics.snapshot()['api_responses'])

    def test_public_redirect_rejects_other_repositories_hosts_protocols_and_credentials(self):
        redirects=G.PublicReleaseRedirects(self.url)
        request=G.Request(self.url,headers={'Authorization':'private-token'})
        redirected=redirects.redirect_request(request,None,302,'',{},'https://release-assets.githubusercontent.com/asset?sig=hidden')
        self.assertNotIn('Authorization',redirected.headers)
        for url in ('http://github.com/example/project/releases/download/v1/file.tar.gz',
                    'https://github.com/other/project/releases/download/v1/file.tar.gz',
                    'https://attacker.invalid/asset','https://token@release-assets.githubusercontent.com/asset',
                    'https://release-assets.githubusercontent.com:443/asset','https://release-assets.githubusercontent.com/asset#fragment'):
            with self.subTest(url=url),self.assertRaisesRegex(ValueError,'redirect escaped'):
                redirects.redirect_request(request,None,302,'',{},url)

    def test_public_corrupt_short_oversized_and_untrusted_final_response_publish_nothing(self):
        for payload,url,status in ((b'corrupt',None,200),(b'x'*(len(self.payload)+1),None,200),
                                   (self.payload,'https://attacker.invalid/asset',200),(self.payload,None,206)):
            with self.subTest(payload=payload,url=url,status=status),mock.patch.object(G,'build_opener') as opener:
                opener.return_value.open.return_value=self.response(payload,url,status)
                with self.assertRaises(ValueError):
                    G.GitHub('example/project').download_public(self.url,self.root/'output',len(self.payload),G.sha(self.payload))
                self.assertFalse((self.root/'output').exists());self.assertEqual([],list(self.root.iterdir()))

    def test_public_transient_retry_discards_partial_bytes_without_auth_fallback(self):
        from email.message import Message
        headers=Message();headers['Retry-After']='0'
        failed=G.HTTPError(self.url,503,'temporary',headers,io.BytesIO(b'private error body'))
        transport=G.GitHub('example/project')
        with mock.patch.object(G,'build_opener') as opener,mock.patch.object(transport,'_wait') as wait:
            opener.return_value.open.side_effect=[failed,self.response()]
            transport.download_public(self.url,self.root/'output',len(self.payload),G.sha(self.payload))
            self.assertEqual(2,opener.return_value.open.call_count);wait.assert_called_once()
        self.assertEqual(self.payload,(self.root/'output').read_bytes())

    def test_visibility_is_explicit_and_private_downloads_keep_authenticated_transport(self):
        asset=dict(id=3,name='file.tar.gz',state='uploaded',size=len(self.payload),digest='sha256:'+G.sha(self.payload))
        info=dict(id=2,tag_name='v1',name='v1',draft=False,prerelease=True)
        for private in (True,False):
            with self.subTest(private=private):
                adapter=mock.Mock();adapter.json.return_value={'full_name':'example/project','private':private}
                adapter.download.side_effect=lambda identity,path:Path(path).write_bytes(self.payload)
                adapter.download_public.side_effect=lambda url,path,size,digest:Path(path).write_bytes(self.payload)
                remote=G.Remote('example/project',adapter);remote.visible();remote.pin_published(info,{'file.tar.gz':asset},private)
                remote.download(asset,self.root/str(private))
                self.assertEqual(1 if private else 0,adapter.download.call_count)
                self.assertEqual(0 if private else 1,adapter.download_public.call_count)
        adapter=mock.Mock();adapter.json.return_value={'full_name':'example/project'}
        with self.assertRaisesRegex(ValueError,'visibility'):G.Remote('example/project',adapter).visible()

    def test_exact_published_lookup_does_not_enumerate_release_history(self):
        adapter=mock.Mock();row=dict(id=2,tag_name='v1',name='v1',draft=False,prerelease=True)
        adapter.json.return_value=row
        remote=G.Remote('example/project',adapter)
        self.assertEqual(row,remote.published('v1'));self.assertEqual(row,remote.by_id(2,'v1'))
        self.assertEqual(2,adapter.json.call_count);adapter.pages.assert_not_called()
        adapter.json.return_value=dict(row,id=99)
        with self.assertRaisesRegex(ValueError,'identity changed'):remote.by_id(2,'v1')

    def test_bounded_cleanup_can_disable_reserve_probe_without_retrying_mutations(self):
        transport=G.GitHub('example/project');transport.WRITE_HEADROOM=0
        success=subprocess.CompletedProcess([],0,b'HTTP/2 204\r\n\r\n',b'')
        with mock.patch.object(transport,'_run',return_value=success) as run,mock.patch.object(transport,'_headroom') as probe:
            self.assertIsNone(transport.json('endpoint',method='DELETE'))
            run.assert_called_once();probe.assert_not_called()
        failure=subprocess.CompletedProcess([],1,b'HTTP/2 403\r\nRetry-After: 3600\r\n\r\n{}',b'')
        with mock.patch.object(transport,'_run',return_value=failure) as run,mock.patch.object(transport,'_wait') as wait:
            with self.assertRaises(G.DeliveryError):transport.json('endpoint',method='DELETE')
            run.assert_called_once();wait.assert_not_called()

    def test_empty_204_json_response_is_valid_but_other_empty_or_204_body_is_not(self):
        transport=G.GitHub('example/project')
        def result(status,body):return subprocess.CompletedProcess([],0,b'HTTP/2 '+str(status).encode()+b' Status\r\n\r\n'+body,b'')
        with mock.patch.object(transport,'_run',return_value=result(204,b'')),mock.patch.object(transport,'_headroom'):
            self.assertIsNone(transport.json('repos/example/project/actions/artifacts/1',method='DELETE'))
        for status,body in ((204,b'{}'),(200,b'')):
            with self.subTest(status=status),mock.patch.object(transport,'_run',return_value=result(status,body)):
                with self.assertRaises(ValueError):transport.json('endpoint')


if __name__=='__main__':unittest.main()
