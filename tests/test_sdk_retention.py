"""Complete SDK byte retention does not grant consumer or publication approval."""
import importlib.util
import copy
import hashlib
import io
import zipfile
import json
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import tempfile
import traceback
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
import dependency_archive as archive
import dependency_store as store
import sdk_windows

spec = importlib.util.spec_from_file_location('retention_lifecycle', ROOT / '.github/scripts/lifecycle.py')
lifecycle = importlib.util.module_from_spec(spec); spec.loader.exec_module(lifecycle)


class SdkRetentionTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(); self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve() / 'owned checkout'; self.root.mkdir()
        shutil.copytree(ROOT / 'third_party/sdk', self.root / 'third_party/sdk')
        self.recipe_file = self.root / 'third_party/sdk/windows-base.json'
        self.recipe = sdk_windows.recipe_identity(self.recipe_file)
        self.group = self.root / 'build/sdk-group'
        provenance = json.loads(self.recipe_file.read_text())
        policy = json.loads((self.recipe_file.parent / 'windows-toolchain.json').read_text())
        provenance.update(linker_version='14.44.35207', windows_sdk=policy['windows_sdk'])
        provenance_path = self.root / 'provenance.json'; archive.write_json(provenance_path, provenance)
        sdk_windows.empty_base(self.recipe_file, provenance_path, self.group)
        self.files = store.verify_group(self.group, self.recipe)
        archive.write_json(self.root / 'build/sdk-origin.json', {'origin': 'base', 'recipe': self.recipe})
        self.environment = {'TARGET': 'windows-x86_64', 'SDK_PROFILE': 'core', 'JOBS': '2', 'CORE_PROVIDER': 'cpp',
            'GITHUB_SHA': 'a' * 40, 'GITHUB_REPOSITORY': 'example/foundation',
            'GITHUB_RUN_ID': '123', 'GITHUB_RUN_ATTEMPT': '2',
            'GITHUB_OUTPUT': str(self.root / 'step-output')}
        self.addCleanup(patch.stopall)
        patch.object(lifecycle, 'ROOT', self.root).start()
        previous = Path.cwd(); lifecycle.os.chdir(self.root)
        self.addCleanup(lifecycle.os.chdir, previous)
        patch.dict(lifecycle.os.environ, self.environment).start()
        self.publisher = patch.object(lifecycle.delivery, 'publish_base', side_effect=AssertionError('unexpected publication')).start()

    def test_private_graphics_input_is_repository_scoped_and_hash_bound(self):
        import windows_graphics
        from unittest.mock import Mock
        row=dict(id=77,name='retained.7z',state='uploaded',size=3,digest='sha256:'+'b'*64)
        remote=Mock();remote.transport.json.return_value=row
        expected=dict(name='retained.7z',size=3,sha256='b'*64)
        archive=self.root/'graphics.7z'
        with patch.object(lifecycle.delivery,'Remote',return_value=remote),patch.object(windows_graphics,'lock',return_value={'archive':expected}),patch.object(windows_graphics,'verify_archive',return_value={}),patch.object(windows_graphics,'fetch_retained',side_effect=AssertionError('unexpected fallback')):
            receipt=lifecycle.retained_graphics('https://api.github.com/repos/example/foundation/releases/assets/77',archive)
            self.assertEqual(receipt['asset_id'],77);remote.download.assert_called_once_with(row,archive,'b'*64)
            with self.assertRaisesRegex(ValueError,'this repository'):
                lifecycle.retained_graphics('https://api.github.com/repos/foreign/foundation/releases/assets/77',archive)
            row['digest']='sha256:'+'c'*64
            with self.assertRaisesRegex(ValueError,'locked archive'):
                lifecycle.retained_graphics('https://api.github.com/repos/example/foundation/releases/assets/77',archive)
            self.assertEqual(remote.download.call_count,1)

    def receipt(self): return json.loads((self.root / 'build/sdk-retention.json').read_text())

    def test_rust_maintenance_consumes_retained_extension_with_both_producers_isolated(self):
        rust_recipe = 'b' * 64; rust_files = {'retained-rust-input': 'c' * 64}
        rust_inputs = self.root / 'build/rust-sdk-inputs'; rust_inputs.mkdir()
        (rust_inputs / 'producer-only.txt').write_bytes(b'Rust supplier bytes')
        self.publisher.side_effect = None; self.publisher.return_value = {'operation': 'plan'}
        def consume(*args, **kwargs):
            self.assertFalse(rust_inputs.exists())
            self.assertFalse((self.root / 'build/sdk-inputs').exists())
            self.assertEqual(kwargs['core_provider'], 'rust')
            self.assertEqual(kwargs['rust_recipe'], rust_recipe)
            self.assertEqual(kwargs['rust_group'], self.root / 'build/rust-sdk-group')
            return {'status': 'passed'}
        with patch.dict(lifecycle.os.environ, CORE_PROVIDER='rust'), \
             patch.object(lifecycle.ci, 'assert_host'), \
             patch.object(lifecycle, 'prepare_rust_maintenance', return_value=(rust_recipe, rust_files)), \
             patch.object(lifecycle.ci, 'prepared_check', side_effect=consume) as check, \
             patch.object(lifecycle.ci, 'publish_rust_base', return_value={'operation': 'Rust plan'}) as rust_publish:
            lifecycle.main('sdk-produce')
        check.assert_called_once()
        rust_publish.assert_called_once_with('example/foundation', rust_recipe,
            self.root / 'build/rust-sdk-group', 'a' * 40)
        self.assertTrue(rust_inputs.is_dir())
        receipt = json.loads((self.root / 'build/sdk-consumer/qualification.json').read_text())
        self.assertEqual(receipt['rust_producer_isolation']['sha256'],
            lifecycle.evidence.sha(self.root / 'build/rust-sdk-isolation.json'))
        self.assertEqual(json.loads((self.root / 'build/rust-sdk-isolation.json').read_text())['status'], 'passed')

    def test_rust_maintenance_failure_keeps_inputs_and_cannot_plan_publication(self):
        rust_inputs = self.root / 'build/rust-sdk-inputs'; rust_inputs.mkdir()
        (rust_inputs / 'producer-only.txt').write_bytes(b'Rust supplier bytes')
        with patch.dict(lifecycle.os.environ, CORE_PROVIDER='rust'), \
             patch.object(lifecycle.ci, 'assert_host'), \
             patch.object(lifecycle, 'prepare_rust_maintenance', return_value=('b' * 64, {})), \
             patch.object(lifecycle.ci, 'prepared_check', side_effect=RuntimeError('Rust consumer failed')), \
             patch.object(lifecycle.ci, 'publish_rust_base') as rust_publish:
            with self.assertRaisesRegex(RuntimeError, 'Rust consumer failed'):
                lifecycle.main('sdk-produce')
        rust_publish.assert_not_called(); self.publisher.assert_not_called()
        receipt = json.loads((self.root / 'build/rust-sdk-isolation.json').read_text())
        self.assertEqual(receipt['status'], 'failed')
        self.assertEqual((Path(receipt['quarantine']) / 'producer-only.txt').read_bytes(), b'Rust supplier bytes')

    def test_failed_consumer_keeps_failure_and_complete_group_can_be_retained(self):
        with patch.object(lifecycle.ci, 'assert_host'), \
             patch.object(lifecycle.ci, 'prepared_check', side_effect=RuntimeError('consumer assertion failed')):
            with self.assertRaisesRegex(RuntimeError, 'consumer assertion failed'):
                lifecycle.main('sdk-produce')
        self.assertFalse((self.root / 'build/sdk-publication-plan.json').exists())
        lifecycle.main('sdk-retain')
        receipt = self.receipt()
        self.assertEqual(receipt['files'], self.files)
        self.assertEqual((receipt['status'], receipt['qualification'], receipt['publication_approved']),
                         ('verified', 'unqualified', False))
        self.assertEqual((receipt['target'], receipt['profile'], receipt['recipe_id']),
                         ('windows-x86_64', 'core', self.recipe))
        self.assertEqual((receipt['source_commit'], receipt['run_id'], receipt['attempt']), ('a' * 40, '123', 2))
        self.assertEqual((self.root / 'step-output').read_text(), 'retained=true\n')
        self.assertEqual(store.verify_group(self.group, self.recipe), self.files)
        self.publisher.assert_not_called()

    def test_retained_group_stays_compatible_with_existing_offline_install(self):
        lifecycle.main('sdk-retain')
        copied = self.root / 'relocated group'
        self.assertEqual(store.copy_group(self.group, copied, self.recipe), self.files)
        installed = sdk_windows.install(copied, self.recipe, self.root / 'relocated dependencies', '14.44.35207')
        self.assertEqual(installed['recipe_id'], self.recipe)
        self.assertEqual(installed['target']['system'], 'Windows')
        self.assertEqual(self.receipt()['qualification'], 'unqualified')
        self.publisher.assert_not_called()

    def test_current_recipe_profile_and_origin_are_revalidated(self):
        origin = self.root / 'build/sdk-origin.json'
        for target, profile in [('windows-x86_64', 'all-gui'), ('linux-x86_64', 'core'), ('browser-wasm32', 'core')]:
            with self.subTest(target=target, profile=profile), patch.dict(lifecycle.os.environ, {'TARGET': target, 'SDK_PROFILE': profile}):
                with self.assertRaisesRegex(ValueError, 'selected current recipe'): lifecycle.main('sdk-retain')
        archive.write_json(origin, {'origin': 'base', 'recipe': 'b' * 64})
        with self.assertRaisesRegex(ValueError, 'selected current recipe'): lifecycle.main('sdk-retain')
        archive.write_json(origin, {'origin': 'base', 'recipe': self.recipe})
        self.recipe_file.write_text(self.recipe_file.read_text() + '\n')
        with self.assertRaisesRegex(ValueError, 'selected current recipe'): lifecycle.main('sdk-retain')
        self.assertFalse((self.root / 'build/sdk-retention.json').exists())
        self.assertFalse((self.root / 'step-output').exists())

    def test_incomplete_or_unexpected_group_files_never_emit_retention_success(self):
        name = store.names(self.recipe)[1]; data = (self.group / name).read_bytes()
        (self.group / name).unlink()
        with self.assertRaisesRegex(ValueError, 'exactly'): lifecycle.main('sdk-retain')
        (self.group / name).write_bytes(data)
        (self.group / 'foreign.txt').write_text('must remain visible')
        with self.assertRaisesRegex(ValueError, 'exactly'): lifecycle.main('sdk-retain')
        self.assertEqual((self.group / 'foreign.txt').read_text(), 'must remain visible')
        self.assertFalse((self.root / 'build/sdk-retention.json').exists())
        self.assertFalse((self.root / 'step-output').exists())

    def test_changed_inner_content_is_rejected_even_with_rewritten_outer_checksums(self):
        binary, source, sums = store.names(self.recipe)
        extracted = self.root / 'changed binary'; archive.extract(self.group / binary, extracted)
        (extracted / 'prefix/README.txt').write_text('changed after sealing')
        (self.group / binary).unlink(); archive.archive_tree(extracted, self.group / binary)
        (self.group / sums).write_text(''.join(archive.digest(self.group / name) + '  ' + name + '\n'
                                             for name in (binary, source)))
        with self.assertRaisesRegex(ValueError, 'manifest'): lifecycle.main('sdk-retain')
        self.assertFalse((self.root / 'build/sdk-retention.json').exists())
        self.assertFalse((self.root / 'step-output').exists())

    def test_refuses_to_replace_existing_receipt(self):
        receipt = self.root / 'build/sdk-retention.json'; receipt.write_text('foreign receipt')
        with self.assertRaises(FileExistsError): lifecycle.main('sdk-retain')
        self.assertEqual(receipt.read_text(), 'foreign receipt')
        self.assertFalse((self.root / 'step-output').exists())

    def test_unknown_target_or_profile_cannot_select_a_fallback_recipe(self):
        for target, profile in [('unknown', 'core'), ('windows-x86_64', 'unknown')]:
            with self.subTest(target=target, profile=profile), self.assertRaisesRegex(ValueError, 'unknown SDK'):
                lifecycle.sdk_identity(target, profile)

    def test_workflow_retains_only_verified_group_without_masking_failure(self):
        text = (ROOT / '.github/workflows/sdk-maintenance.yml').read_text()
        retention = text.split('    - name: Verify complete SDK bytes', 1)[1].split('    - name:', 1)[0]
        self.assertIn('id: retain', retention); self.assertIn('if: always()', retention)
        self.assertIn('lifecycle.py sdk-retain', retention)
        group = text.split('      name: Retain verified sdk-group-', 1)[0].rsplit('    - ',1)[1]
        self.assertIn("if: always() && steps.retain.outcome == 'success' && steps.retain.outputs.retained == 'true'", group)
        self.assertNotIn('continue-on-error', text)
        publication = text.split('  publish:', 1)[1]
        self.assertIn('    if: inputs.execute\n    needs: produce\n', publication)
        self.assertNotIn('always()', publication.split('    steps:', 1)[0])
        self.assertIn('          build/sdk-retention.json\n', text)
        self.assertIn('          build/sdk-isolation.json\n', text)
        self.assertIn('sdk_retention', (ROOT / 'CMakeLists.txt').read_text())



class RetainedSdkRecoveryTests(unittest.TestCase):
    setUp = SdkRetentionTests.setUp

    def prepare(self):
        self.repository = 'example/foundation'
        self.request = dict(schema_version=1, repository=self.repository, target='windows-x86_64', profile='core',
            recipe_id=self.recipe, run_id=123, source_commit='a' * 40, attempt=2, job_id=456,
            group={'id': 789, 'sha256': '0' * 64}, proof={'id': 790, 'sha256': '0' * 64})
        self.repo = {'id': 42, 'full_name': self.repository, 'private': True}
        self.run = dict(id=123, run_attempt=2, head_sha='a' * 40, status='in_progress', conclusion=None,
            event='workflow_dispatch', path='.github/workflows/sdk-maintenance.yml',
            repository=self.repo.copy(), head_repository=self.repo.copy())
        self.job = dict(id=456, run_id=123, run_attempt=2, head_sha='a' * 40,
            name='produce (windows-x86_64, windows-2022)', status='completed', conclusion='failure',
            started_at='2026-01-01T12:00:00Z', completed_at='2026-01-01T13:00:00Z')
        self.base = 'repos/' + self.repository
        self.rows = {self.base: self.repo, self.base + '/actions/runs/123/attempts/2': self.run,
                     self.base + '/actions/jobs/456': self.job}
        self.receipt_value = dict(schema_version=1, status='verified', qualification='unqualified',
            publication_approved=False, target='windows-x86_64', profile='core', recipe_id=self.recipe,
            source_commit='a' * 40, run_id='123', attempt=2, files=self.files)
        self.proof = {'sdk-retention.json': archive.encoded(self.receipt_value),
                      'sdk-origin.json': archive.encoded({'origin':'rebuild', 'recipe':self.recipe}),
                      'other-report.txt': b'No extraction of unrelated proof files.\n'}
        self.payloads = {}; self.downloads = []
        self.pack('group', {p.name:p.read_bytes() for p in self.group.iterdir()})
        self.pack('proof', self.proof)
        from unittest.mock import Mock
        self.transport = Mock(); self.transport.json.side_effect = lambda endpoint: copy.deepcopy(self.rows[endpoint])

    def pack(self, kind, entries):
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, 'w') as stream:
            for name, data in (entries.items() if isinstance(entries, dict) else entries):
                if isinstance(name, str):
                    # Bypass ZipInfo's constructor cleanup so malformed test names
                    # are stored unchanged on every host, including Windows.
                    item = zipfile.ZipInfo()
                    item.filename = item.orig_filename = name
                else:
                    item = name
                stream.writestr(item, data)
        raw = buffer.getvalue(); artifact_id = self.request[kind]['id']; self.payloads[artifact_id] = raw
        digest = hashlib.sha256(raw).hexdigest(); self.request[kind]['sha256'] = digest
        self.rows[self.base + '/actions/artifacts/' + str(artifact_id)] = dict(id=artifact_id,
            name='sdk-' + kind + '-windows-x86_64-2', size_in_bytes=len(raw), expired=False, digest='sha256:' + digest,
            created_at='2026-01-01T12:59:00Z', workflow_run=dict(id=123, repository_id=42, head_repository_id=42, head_sha='a'*40))

    def bundle_request(self):
        return dict(self.request,schema_version=2,workflow='sdk-maintenance.yml',
            **{kind:dict(manifest_id=self.request[kind]['id'],manifest_sha256=self.request[kind]['sha256'])
               for kind in ('group','proof')})

    def download(self, repository, artifact_id, output):
        self.assertEqual(repository, self.repository); self.downloads.append(artifact_id)
        with output.open('xb') as stream: stream.write(self.payloads[artifact_id])

    def recover(self, destination=None):
        return lifecycle.ci.import_legacy_sdk(self.repository, self.request, 'windows-x86_64', 'core', self.recipe,
            self.root / 'restored group' if destination is None else destination,
            transport=self.transport, download=self.download)

    def test_completed_failed_job_with_active_siblings_reuses_exact_unqualified_triplet(self):
        self.prepare(); result = self.recover()
        self.assertEqual(store.verify_group(self.root / 'restored group', self.recipe), self.files)
        self.assertEqual(self.downloads, [789, 790]); self.assertEqual(result['origin'], 'retained')
        self.assertEqual(result['qualification'], 'unqualified'); self.assertIs(result['publication_approved'], False)
        self.assertEqual(result['request'], self.request); self.assertEqual(result['retention'], self.receipt_value)
        self.assertFalse((self.root / 'other-report.txt').exists()); self.publisher.assert_not_called()
        with self.assertRaisesRegex(ValueError, 'must be new'): self.recover()

    def test_exact_request_rejects_mismatch_unknown_fields_and_coerced_identifiers(self):
        self.prepare(); original = copy.deepcopy(self.request)
        mutations = [('repository','other/foundation'), ('target','linux-x86_64'), ('profile','all-gui'),
            ('recipe_id','b'*64), ('source_commit','main'), ('run_id', '123'), ('attempt', True),
            ('job_id', 0), ('unexpected',1), ('group',{'id':789,'sha256':'x'}), ('proof',original['group'])]
        for key, value in mutations:
            with self.subTest(key=key):
                self.request = copy.deepcopy(original); self.request[key] = value
                with self.assertRaises(ValueError): self.recover()
        self.assertFalse(self.downloads)

    def test_wrong_or_unfinished_producer_is_rejected_before_download(self):
        self.prepare()
        mutations = [(self.run,'id',124), (self.run,'run_attempt',1), (self.run,'head_sha','b'*40),
            (self.run,'path','.github/workflows/candidate.yml'), (self.run,'event','pull_request'),
            (self.run,'head_repository',{'id':43,'full_name':'fork/foundation'}),
            (self.run,'repository',{'id':42,'full_name':'other/foundation'}),
            (self.job,'id',457), (self.job,'run_id',125), (self.job,'run_attempt',1),
            (self.job,'head_sha','c'*40), (self.job,'name','produce (linux-x86_64, ubuntu-24.04)'),
            (self.job,'status','in_progress'), (self.job,'conclusion','cancelled'),
            (self.job,'completed_at','2026-01-01T11:00:00Z')]
        for row, key, value in mutations:
            original = row[key]
            with self.subTest(key=key, value=value):
                row[key] = value
                with self.assertRaises(ValueError): self.recover()
                row[key] = original
        self.assertFalse(self.downloads)

    def test_artifact_metadata_must_bind_bytes_repository_run_target_and_job_interval(self):
        self.prepare(); row = self.rows[self.base + '/actions/artifacts/789']
        for key, value in [('id',791), ('name','sdk-group-windows-x86_64-1'), ('expired',True),
                           ('digest','sha256:'+'b'*64), ('size_in_bytes',0),
                           ('created_at','2026-01-01T11:59:59Z'), ('created_at','2026-01-01T13:00:01Z')]:
            original = row[key]
            with self.subTest(key=key, value=value):
                row[key] = value
                with self.assertRaises(ValueError): self.recover()
                row[key] = original
        for key, value in [('id',124), ('repository_id',43), ('head_repository_id',43), ('head_sha','b'*40)]:
            original = row['workflow_run'][key]; row['workflow_run'][key] = value
            with self.subTest(key=key), self.assertRaises(ValueError): self.recover()
            row['workflow_run'][key] = original
        self.assertFalse(self.downloads)

    def test_corrupt_download_or_changed_remote_metadata_never_publishes_group(self):
        self.prepare(); self.payloads[789] += b'changed'
        with self.assertRaisesRegex(ValueError, 'pinned bytes'): self.recover()
        self.assertFalse((self.root/'restored group').exists())
        self.prepare()
        count = 0
        def changed(endpoint):
            nonlocal count
            value = copy.deepcopy(self.rows[endpoint])
            if endpoint.endswith('/artifacts/789'):
                count += 1
                if count > 1: value['expired'] = True
            return value
        self.transport.json.side_effect = changed
        with self.assertRaisesRegex(ValueError, 'changed during verification'): self.recover()
        self.assertFalse((self.root/'restored group').exists())

    def test_receipt_and_origin_are_read_bounded_and_revalidated(self):
        self.prepare()
        for key, value in [('schema_version',True), ('qualification','qualified'), ('status','passed'),
            ('publication_approved',True), ('recipe_id','b'*64), ('target','linux-x86_64'),
            ('profile','all-gui'), ('run_id','124'), ('attempt',1), ('source_commit','b'*40), ('files',{})]:
            with self.subTest(key=key):
                receipt = dict(self.receipt_value, **{key:value})
                self.pack('proof',dict(self.proof, **{'sdk-retention.json':archive.encoded(receipt)}))
                with self.assertRaises(ValueError): self.recover()
        for entry in ({'origin':'rebuild','recipe':'b'*64}, {'origin':'unknown','recipe':self.recipe}, []):
            self.pack('proof',dict(self.proof, **{'sdk-origin.json':archive.encoded(entry)}))
            with self.assertRaises(ValueError): self.recover()
        for entries in ({'sdk-origin.json':b'{}'}, dict(self.proof, **{'sdk-retention.json':b' '*131073}),
                        dict(self.proof, **{'sdk-origin.json':b'{"recipe":1,"recipe":2}'})):
            self.pack('proof',entries)
            with self.assertRaises(ValueError): self.recover()
        self.assertFalse((self.root/'restored group').exists())

    def test_group_and_proof_archives_reject_unsafe_members_and_inexact_triplets(self):
        self.prepare(); group = {p.name:p.read_bytes() for p in self.group.iterdir()}
        symlink = zipfile.ZipInfo('shortcut'); symlink.create_system = 3; symlink.external_attr = 0o120777 << 16
        privileged = zipfile.ZipInfo('privileged'); privileged.external_attr = 0o104755 << 16
        invalid = [('extra',b'x'), ('../escape',b'x'), ('C:/escape',b'x'), ('bad\\name',b'x'),
                   (symlink,b'target'), (privileged,b'x')]
        for kind, good in [('group',group), ('proof',self.proof)]:
            for name, data in invalid:
                with self.subTest(kind=kind, name=str(name)):
                    self.pack(kind,[*good.items(),(name,data)])
                    if kind == 'proof' and name == 'extra':
                        # Unrelated regular proof reports are inspected but never extracted.
                        continue
                    with self.assertRaises(ValueError): self.recover()
                    self.assertFalse((self.root/'restored group').exists())
                self.pack(kind,good)
            first = next(iter(good))
            self.pack(kind,[*good.items(),(first.upper(),b'alias')])
            with self.assertRaises(ValueError): self.recover()
            self.pack(kind,good)
        self.pack('group',dict(list(group.items())[1:]))
        with self.assertRaisesRegex(ValueError, 'exactly'): self.recover()
        self.assertFalse((self.root/'restored group').exists())

    def test_stored_raw_names_are_rejected_before_host_filename_cleanup(self):
        self.prepare()
        group = {p.name:p.read_bytes() for p in self.group.iterdir()}
        case = 0
        for separator in ('/', '\\'):
            for kind, good in [('group',group), ('proof',self.proof)]:
                for name in ('bad\\name', 'bad\x00name', 'folder\\', '\x00hidden'):
                    case += 1
                    destination = self.root / ('raw-name-case-' + str(case))
                    with self.subTest(separator=separator, kind=kind, name=repr(name)):
                        self.pack(kind,[*good.items(),(name,b'x')])
                        raw = self.payloads[self.request[kind]['id']]
                        # Both local and central records contain the actual unsafe
                        # spelling; writing the test must not repair it first.
                        self.assertEqual(raw.count(name.encode()),2)
                        with patch.object(zipfile.os,'sep',separator):
                            with zipfile.ZipFile(io.BytesIO(raw)) as source:
                                member = source.infolist()[-1]
                                self.assertEqual(member.orig_filename,name)
                                if '\x00' in name or separator == '\\':
                                    self.assertNotEqual(member.filename,name)
                            with self.assertRaisesRegex(ValueError,'portable|name changes'):
                                self.recover(destination)
                        self.assertFalse(destination.exists())
                self.pack(kind,good)
        # Canonical directories and unrelated reports remain valid proof input.
        self.pack('proof',dict(self.proof, **{'reports/':b'', 'reports/result.txt':b'ok'}))
        self.assertEqual(self.recover()['qualification'],'unqualified')
        self.assertFalse((self.root/'reports').exists())

    def test_retained_lifecycle_reruns_consumer_without_cold_production(self):
        archive.write_json(self.root/'build/sdk-origin.json',{'origin':'retained','recipe':self.recipe,
                            'qualification':'unqualified','publication_approved':False})
        self.publisher.side_effect = None; self.publisher.return_value = {'operation':'plan'}
        with patch.object(lifecycle.ci,'assert_host'), patch.object(lifecycle.ci,'prepared_check', return_value={'status':'passed'}) as check, \
             patch.object(lifecycle.subprocess,'run',side_effect=AssertionError('cold producer must not run')):
            lifecycle.main('sdk-produce')
        check.assert_called_once(); self.publisher.assert_called_once()
        self.assertNotIn('execute',self.publisher.call_args.kwargs)
        self.assertTrue((self.root/'build/sdk-publication-plan.json').is_file())

    def test_explicit_source_is_required_and_recovery_failure_has_no_cold_fallback(self):
        self.prepare(); self.request=self.bundle_request()
        with patch.dict(lifecycle.os.environ,{'SDK_SOURCE':'auto','SDK_RETAINED_INPUT':json.dumps(self.request),
                                             'GITHUB_REPOSITORY':self.repository}):
            with self.assertRaisesRegex(ValueError,'explicit source=retained'): lifecycle.main('sdk-inputs')
        with patch.dict(lifecycle.os.environ,{'SDK_SOURCE':'retained','SDK_RETAINED_INPUT':json.dumps(self.request),
                                             'GITHUB_REPOSITORY':self.repository}), \
             patch.object(lifecycle.ci,'retained_sdk',side_effect=ValueError('exact digest differs')), \
             patch.object(lifecycle.ci,'maintenance_base') as base:
            with self.assertRaisesRegex(ValueError,'exact digest differs'): lifecycle.main('sdk-inputs')
            base.assert_not_called()
        with patch.dict(lifecycle.os.environ,{'SDK_SOURCE':'retained','TARGET':'all'}):
            with self.assertRaisesRegex(ValueError,'one exact target'): lifecycle.main('sdk-plan')



    def test_retained_all_gui_reruns_both_consumers_and_preserves_failure(self):
        origin = {'origin':'retained','recipe':self.recipe,'qualification':'unqualified','publication_approved':False}
        archive.write_json(self.root/'build/sdk-origin.json',origin)
        self.publisher.side_effect = None; self.publisher.return_value = {'operation':'plan'}
        entry = lifecycle.main
        with patch.dict(lifecycle.os.environ,{'SDK_PROFILE':'all-gui'}), \
             patch.object(lifecycle.ci,'assert_host'), patch.object(lifecycle,'main') as gui_input, \
             patch.object(lifecycle.ci,'gui_group_module') as group_module, \
             patch.object(lifecycle.ci,'prepared_check', return_value={'status':'passed'}) as check, \
             patch.object(lifecycle.subprocess,'run',side_effect=AssertionError('cold producer must not run')):
            entry('sdk-produce')
        gui_input.assert_not_called(); group_module.return_value.verify.assert_called_once_with(self.root/'build/gui-group')
        self.assertEqual(check.call_count,2)
        self.assertEqual(check.call_args.args[5],self.root/'build/gui-group')
        self.assertEqual(check.call_args.kwargs['graphics_archive'],self.root/'build/host-graphics/mesa-windows.7z')
        self.publisher.assert_called_once(); (self.root/'build/sdk-publication-plan.json').unlink()
        (self.root/'build/sdk-isolation.json').unlink()
        shutil.rmtree(self.root/'build/sdk-consumer'); shutil.rmtree(self.root/'build/sdk-gui-consumer')
        self.publisher.reset_mock()
        with patch.dict(lifecycle.os.environ,{'SDK_PROFILE':'all-gui'}), \
             patch.object(lifecycle.ci,'assert_host'), patch.object(lifecycle,'main'), \
             patch.object(lifecycle.ci,'gui_group_module'), \
             patch.object(lifecycle.ci,'prepared_check',side_effect=[None,RuntimeError('GUI failed')]):
            with self.assertRaisesRegex(RuntimeError,'GUI failed'): entry('sdk-produce')
        self.publisher.assert_not_called(); self.assertFalse((self.root/'build/sdk-publication-plan.json').exists())

    def test_gui_replay_uses_complete_selected_group_and_never_falls_back_to_acquisition(self):
        import screenshots
        selector={'source':'base','manifest_sha256':'a'*64}
        with patch.dict(lifecycle.os.environ,{'GUI_INPUT':json.dumps(selector)}), \
             patch.object(screenshots,'fetch_gui_input',return_value={'selector':selector}) as fetch, \
             patch.object(lifecycle.subprocess,'run',side_effect=AssertionError('supplier acquisition forbidden')):
            lifecycle.main('gui-input')
        fetch.assert_called_once_with(self.environment['GITHUB_REPOSITORY'],selector,self.root/'build/gui-group')
        self.assertEqual(selector,json.loads((self.root/'build/gui-origin.json').read_text())['selector'])
        (self.root/'build/gui-origin.json').unlink()
        with patch.dict(lifecycle.os.environ,{'GUI_INPUT':json.dumps(selector)}), \
             patch.object(screenshots,'fetch_gui_input',side_effect=ValueError('retained input differs')), \
             patch.object(lifecycle.subprocess,'run',side_effect=AssertionError('supplier fallback forbidden')):
            with self.assertRaisesRegex(ValueError,'retained input differs'):lifecycle.main('gui-input')
        self.assertFalse((self.root/'build/gui-origin.json').exists())

    def test_linux_planning_does_not_substitute_for_native_recipe_check(self):
        self.prepare(); self.request=self.bundle_request()
        environment={'SDK_SOURCE':'retained','SDK_RETAINED_INPUT':json.dumps(self.request),
                     'GITHUB_REPOSITORY':self.repository,'SDK_PROFILE':'core','TARGET':'windows-x86_64'}
        with patch.dict(lifecycle.os.environ,environment), patch.object(lifecycle,'sdk_identity',return_value='b'*64) as identity:
            lifecycle.main('sdk-plan'); identity.assert_not_called()
            with self.assertRaisesRegex(ValueError,'current recipe differs'): lifecycle.main('sdk-inputs')
            identity.assert_called()
        for raw in ('[]', '{"schema_version":1,"schema_version":1}', ' '*16385):
            with patch.dict(lifecycle.os.environ,dict(environment,SDK_RETAINED_INPUT=raw)),self.assertRaises(ValueError):
                lifecycle.main('sdk-plan')

    def test_workflow_declares_exact_manual_recovery_inputs_for_plan_and_producer(self):
        text=(ROOT/'.github/workflows/sdk-maintenance.yml').read_text()
        self.assertIn('        - retained\n',text)
        self.assertEqual(text.count('SDK_RETAINED_INPUT: ${{ inputs.retained_input }}'),2)
        self.assertEqual(text.count('SDK_PROFILE: ${{ inputs.profile }}'),2)
        self.assertEqual(text.count('SDK_SOURCE: ${{ inputs.source }}'),2)
        self.assertIn('    if: inputs.execute\n    needs: produce\n',text)



class SdkProducerIsolationTests(unittest.TestCase):
    setUp = SdkRetentionTests.setUp

    def producer(self):
        original = self.root / 'build/sdk-inputs'; original.mkdir()
        (original / 'producer-only.txt').write_bytes(b'producer bytes')
        return original

    def isolate(self, origin='rebuild'):
        return lifecycle.isolated_sdk_producer('windows-x86_64', 'core', self.recipe, origin, self.files)

    def isolation(self):
        return json.loads((self.root / 'build/sdk-isolation.json').read_text())

    def test_real_subprocess_cannot_read_original_but_independent_consumer_succeeds(self):
        original = self.producer(); consumer = self.root / 'relocated'; consumer.mkdir()
        (consumer / 'copied.txt').write_bytes(b'independent bytes')
        script = 'from pathlib import Path; import sys; print(Path(sys.argv[1]).read_bytes().decode())'
        def read(path):
            return subprocess.run([sys.executable, '-B', '-c', script, str(path)], cwd=self.root,
                                  capture_output=True, text=True, timeout=20)
        self.assertEqual(read(original / 'producer-only.txt').returncode, 0)
        with self.isolate() as check:
            self.assertNotEqual(read(original / 'producer-only.txt').returncode, 0)
            good = read(consumer / 'copied.txt')
            self.assertEqual((good.returncode, good.stdout.strip()), (0, 'independent bytes'))
            check('independent-consumer')
        self.assertEqual(read(original / 'producer-only.txt').returncode, 0)
        receipt = self.isolation()
        self.assertEqual((receipt['status'], receipt['initial_state'], receipt['disposition']),
                         ('passed', 'present', 'restored'))
        self.assertEqual(receipt['group_files'], self.files)
        self.assertEqual(receipt['recipe_id'], self.recipe)
        self.assertFalse(Path(receipt['quarantine']).parent.exists())

    def test_base_and_retained_origins_record_initial_absence(self):
        for origin in ('base', 'retained'):
            with self.subTest(origin=origin):
                with self.isolate(origin): self.assertFalse((self.root/'build/sdk-inputs').exists())
                receipt = self.isolation()
                self.assertEqual((receipt['origin'], receipt['initial_state'], receipt['disposition']),
                                 (origin, 'absent', 'remained-absent'))
                self.assertIsNone(receipt['quarantine'])
                (self.root/'build/sdk-isolation.json').unlink()

    def test_existing_producer_is_quarantined_even_for_retained_input(self):
        original = self.producer()
        with self.isolate('retained'): self.assertFalse(original.exists())
        self.assertEqual(self.isolation()['disposition'], 'restored')

    def test_consumer_exception_preserves_quarantine_without_restoring(self):
        original = self.producer()
        with self.assertRaisesRegex(RuntimeError, 'consumer failure'):
            with self.isolate(): raise RuntimeError('consumer failure')
        receipt = self.isolation()
        self.assertEqual((receipt['status'],receipt['disposition'],receipt['consumers']),
                         ('failed','preserved','not-completed'))
        self.assertFalse(original.exists())
        self.assertEqual((Path(receipt['quarantine'])/'producer-only.txt').read_bytes(),b'producer bytes')

    def test_interrupt_preserves_tree_and_failure_receipt(self):
        self.producer()
        with self.assertRaises(KeyboardInterrupt):
            with self.isolate(): raise KeyboardInterrupt()
        self.assertEqual(self.isolation()['status'],'failed')
        self.assertTrue(Path(self.isolation()['quarantine']).is_dir())

    def test_recreated_original_preserves_both_trees(self):
        original = self.producer()
        with self.assertRaisesRegex(ValueError, 'recreated'):
            with self.isolate():
                original.mkdir(); (original/'foreign').write_bytes(b'foreign')
        receipt = self.isolation()
        self.assertEqual((original/'foreign').read_bytes(),b'foreign')
        self.assertEqual((Path(receipt['quarantine'])/'producer-only.txt').read_bytes(),b'producer bytes')
        self.assertEqual(receipt['status'],'failed')

    def test_absent_origin_recreated_by_consumer_is_not_removed(self):
        original = self.root/'build/sdk-inputs'
        with self.assertRaisesRegex(ValueError,'recreated'):
            with self.isolate('base'): original.mkdir()
        self.assertTrue(original.is_dir()); self.assertEqual(self.isolation()['status'],'failed')

    def test_replaced_quarantine_is_not_restored_or_deleted(self):
        original = self.producer(); saved = self.root/'saved original'
        with self.assertRaisesRegex(ValueError,'quarantine identity'):
            with self.isolate():
                holder, = (self.root/'build').glob('sdk-producer-quarantine-*')
                (holder/'sdk-inputs').rename(saved); (holder/'sdk-inputs').mkdir()
                (holder/'sdk-inputs/foreign').write_bytes(b'foreign')
        self.assertEqual((saved/'producer-only.txt').read_bytes(),b'producer bytes')
        self.assertEqual((holder/'sdk-inputs/foreign').read_bytes(),b'foreign')
        self.assertFalse(original.exists())

    def test_file_link_and_reparse_producer_roots_are_rejected(self):
        original = self.root/'build/sdk-inputs'; original.write_bytes(b'foreign')
        with self.assertRaisesRegex(ValueError,'ordinary directories'):
            with self.isolate(): self.fail('consumer must not run')
        self.assertEqual(original.read_bytes(),b'foreign'); original.unlink()
        (self.root/'build/sdk-isolation.json').unlink(); original.mkdir()
        actual = Path.lstat
        from types import SimpleNamespace
        for mode, attributes in [(stat.S_IFLNK|0o777, 0), (stat.S_IFDIR|0o755,0x400)]:
            def lstat(path):
                if path == original: return SimpleNamespace(st_mode=mode,st_file_attributes=attributes)
                return actual(path)
            with self.subTest(mode=mode), patch.object(Path,'lstat',lstat):
                with self.assertRaisesRegex(ValueError,'ordinary directories'):
                    with self.isolate(): self.fail('consumer must not run')
            self.assertTrue(original.is_dir()); (self.root/'build/sdk-isolation.json').unlink()

    def test_failed_rename_does_not_retry_or_cleanup(self):
        original = self.producer(); real = Path.rename
        for after in (False, True):
            def rename(path,destination):
                if path == original:
                    if after: real(path,destination)
                    raise OSError('uncertain move')
                return real(path,destination)
            with self.subTest(after=after), patch.object(Path,'rename',rename):
                with self.assertRaisesRegex(OSError,'uncertain move'):
                    with self.isolate(): self.fail('consumer must not run')
            receipt = self.isolation(); self.assertEqual(receipt['status'],'failed')
            self.assertTrue(Path(receipt['quarantine']).parent.exists())
            self.assertEqual(original.exists(),not after)
            self.assertEqual(Path(receipt['quarantine']).exists(),after)
            (self.root/'build/sdk-isolation.json').unlink()

    def test_restore_failure_preserves_tree_and_suppresses_passed_receipt(self):
        original = self.producer(); real = Path.rename
        def rename(path,destination):
            if Path(destination) == original: raise PermissionError('restoration denied')
            return real(path,destination)
        with patch.object(Path,'rename',rename), self.assertRaisesRegex(PermissionError,'restoration denied'):
            with self.isolate(): pass
        receipt = self.isolation()
        self.assertEqual((receipt['status'],receipt['consumers'],receipt['disposition']),
                         ('failed','completed','preserved'))
        self.assertTrue(Path(receipt['quarantine']).is_dir()); self.assertFalse(original.exists())

    def test_changed_parent_is_preserved_without_writing_foreign_receipt(self):
        self.producer(); parent=self.root/'build'; saved=self.root/'preserved-build'
        with self.assertRaisesRegex(ValueError,'parent changed'):
            with self.isolate():
                parent.rename(saved); parent.mkdir(); (parent/'foreign').write_bytes(b'foreign')
        self.assertEqual(list(parent.iterdir()),[parent/'foreign'])
        self.assertEqual((parent/'foreign').read_bytes(),b'foreign')
        self.assertTrue(any(saved.glob('sdk-producer-quarantine-*/sdk-inputs/producer-only.txt')))

    def test_conflicting_receipt_at_exit_blocks_success_without_overwrite(self):
        self.producer(); receipt=self.root/'build/sdk-isolation.json'
        with self.assertRaises(FileExistsError):
            with self.isolate(): receipt.write_bytes(b'foreign')
        self.assertEqual(receipt.read_bytes(),b'foreign')

    def test_receipt_failure_chains_original_consumer_error_and_preserves_tree(self):
        self.producer(); failure=RuntimeError('consumer failed')
        with patch.object(lifecycle,'write',side_effect=OSError('receipt write failed')):
            with self.assertRaisesRegex(OSError,'receipt write failed') as raised:
                with self.isolate(): raise failure
        self.assertIs(raised.exception.__cause__,failure)
        self.assertTrue(any((self.root/'build').glob('sdk-producer-quarantine-*/sdk-inputs/producer-only.txt')))
        self.assertFalse((self.root/'build/sdk-inputs').exists())

    def test_existing_isolation_receipt_is_never_replaced(self):
        self.producer(); path=self.root/'build/sdk-isolation.json'; path.write_bytes(b'foreign')
        with self.assertRaises(FileExistsError):
            with self.isolate(): self.fail('consumer must not run')
        self.assertEqual(path.read_bytes(),b'foreign'); self.assertTrue((self.root/'build/sdk-inputs').is_dir())

    def test_both_consumers_install_inside_guard_and_receipts_bind_final_isolation(self):
        original = self.producer(); entry=lifecycle.main; calls=[]
        def consumer(target,recipe,group,output,*args,**kwargs):
            self.assertFalse(original.exists()); self.assertTrue(kwargs['defer_qualification'])
            self.assertFalse((self.root/'build/sdk-consumer/qualification.json').exists())
            # Use a real installer before either qualification receipt can appear.
            sdk_windows.install(group,recipe,output/'dependencies','14.44.35207')
            calls.append(output.name)
            return {'status':'passed','group_files':self.files}
        self.publisher.side_effect=None; self.publisher.return_value={'operation':'plan'}
        with patch.dict(lifecycle.os.environ,{'SDK_PROFILE':'all-gui'}), patch.object(lifecycle.ci,'assert_host'), \
             patch.object(lifecycle,'main') as gui, patch.object(lifecycle.ci,'gui_group_module') as group, \
             patch.object(lifecycle.ci,'prepared_check',side_effect=consumer):
            entry('sdk-produce')
        self.assertEqual(calls,['sdk-consumer','sdk-gui-consumer']); gui.assert_not_called()
        group.return_value.verify.assert_called_once_with(self.root/'build/gui-group')
        self.assertTrue(original.is_dir())
        self.assertEqual(self.isolation()['checkpoints'],
            ['before-install-and-core','after-core','before-gui-install','after-all-consumers'])
        digest=archive.digest(self.root/'build/sdk-isolation.json')
        for name in calls:
            report=json.loads((self.root/'build'/name/'qualification.json').read_text())
            self.assertEqual(report['producer_isolation'],{'file':'../sdk-isolation.json','sha256':digest})
        self.assertTrue((self.root/'build/sdk-publication-plan.json').is_file())

    def test_guard_exit_failure_emits_neither_qualification_nor_publication(self):
        original = self.producer()
        def consumer(*args,**kwargs): original.mkdir(); return {'status':'passed'}
        with patch.object(lifecycle.ci,'assert_host'), patch.object(lifecycle.ci,'prepared_check',side_effect=consumer):
            with self.assertRaisesRegex(ValueError,'recreated'): lifecycle.main('sdk-produce')
        self.assertFalse((self.root/'build/sdk-consumer/qualification.json').exists())
        self.assertFalse((self.root/'build/sdk-publication-plan.json').exists()); self.publisher.assert_not_called()
        self.assertEqual(self.isolation()['status'],'failed')

    def test_deferred_prepared_check_runs_sdk_install_but_does_not_publish(self):
        from unittest.mock import Mock
        sdk=Mock(); sdk.install.return_value={'capabilities':['terminal','framebuffer','fltk','rev','sdl','hosted-web']}
        select=lifecycle.ci.module
        def module(name): return sdk if name=='sdk' else select(name)
        for defer in (False,True):
            output=self.root/('deferred' if defer else 'ordinary')
            with patch.object(lifecycle.ci,'module',side_effect=module),patch.object(lifecycle.ci,'assert_host'), \
                 patch.object(lifecycle.ci.subprocess,'run'):
                receipt=lifecycle.ci.prepared_check('linux-x86_64',self.recipe,self.group,output,
                    gui_group=self.group,defer_qualification=defer,core_provider='cpp')
            self.assertEqual(receipt['status'],'passed')
            self.assertEqual((output/'qualification.json').exists(),not defer)
        self.assertEqual(sdk.install.call_count,2)



class LifecycleFailureReceiptTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(); self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        previous = Path.cwd(); lifecycle.os.chdir(self.root)
        self.addCleanup(lifecycle.os.chdir, previous)
        self.receipt = self.root / 'build/receipts/failure.json'

    def failures(self):
        return (lifecycle.ProcessTreeError('owned helper remains live'),
                subprocess.TimeoutExpired(['owned-compiler'], 3))

    def test_owned_failure_receipt_preserves_original_exception_cause_and_traceback(self):
        for command in ('gui-qualify', 'publish-candidate'):
            for error in self.failures():
                with self.subTest(command=command, error=type(error).__name__):
                    cause = OSError('original owner diagnostic')
                    def fail(operation):
                        self.assertEqual(operation, command)
                        raise error from cause
                    with patch.object(lifecycle, 'main', side_effect=fail):
                        try:
                            lifecycle.cli(command)
                        except (lifecycle.ProcessTreeError, subprocess.TimeoutExpired) as caught:
                            self.assertIs(caught, error)
                            self.assertIs(caught.__cause__, cause)
                            self.assertIn('fail', [frame.name for frame in traceback.extract_tb(caught.__traceback__)])
                        else:
                            self.fail('owned failure was suppressed')
                    receipt = json.loads(self.receipt.read_text())
                    self.assertFalse(receipt['ok'])
                    self.assertEqual(receipt['operation'], command)
                    self.assertEqual(receipt['error'], str(error))
                    self.assertEqual(receipt['uncertain'], command == 'publish-candidate')
                    self.receipt.unlink()

    def test_receipt_write_failure_preserves_original_owned_error(self):
        for error in self.failures():
            with self.subTest(error=type(error).__name__), \
                 patch.object(lifecycle, 'main', side_effect=error), \
                 patch.object(lifecycle, 'write', side_effect=OSError('receipt unavailable')):
                with self.assertRaises(type(error)) as raised: lifecycle.cli('gui-qualify')
                self.assertIs(raised.exception, error)
        self.assertFalse(self.receipt.exists())

    def test_existing_failure_receipt_is_never_overwritten(self):
        self.receipt.parent.mkdir(parents=True); self.receipt.write_text('prior receipt')
        for error in self.failures():
            with self.subTest(error=type(error).__name__), patch.object(lifecycle, 'main', side_effect=error):
                with self.assertRaises(type(error)) as raised: lifecycle.cli('gui-qualify')
                self.assertIs(raised.exception, error)
                self.assertEqual(self.receipt.read_text(), 'prior receipt')

    def test_unrelated_runtime_error_does_not_enter_receipt_handling(self):
        error = RuntimeError('unrelated programming error')
        with patch.object(lifecycle, 'main', side_effect=error):
            with self.assertRaises(RuntimeError) as raised: lifecycle.cli('gui-qualify')
        self.assertIs(raised.exception, error)
        self.assertFalse(self.receipt.exists())

    def test_success_and_preexisting_error_exit_behavior_are_unchanged(self):
        with patch.object(lifecycle, 'main') as main:
            lifecycle.cli('gui-qualify')
        main.assert_called_once_with('gui-qualify')
        self.assertFalse(self.receipt.exists())
        with patch.object(lifecycle, 'main', side_effect=ValueError('invalid input')):
            with self.assertRaises(SystemExit) as raised: lifecycle.cli('gui-qualify')
        self.assertEqual(json.loads(raised.exception.code), json.loads(self.receipt.read_text()))
        self.assertFalse(json.loads(self.receipt.read_text())['ok'])


if __name__ == '__main__': unittest.main()
