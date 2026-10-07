"""Run-scoped storage keeps exact layouts, provenance and unqualified SDK lineage."""
import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import textwrap
import unittest
from unittest.mock import Mock, patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'));sys.path.insert(0,str(ROOT/'tests'))
import ci_plan as ci
import ci_transport
import dependency_archive as archive
import dependency_store as store
import test_sdk_retention as retention
lifecycle=retention.lifecycle


class StorageLayoutTests(unittest.TestCase):
    def setUp(self):
        temporary=tempfile.TemporaryDirectory();self.addCleanup(temporary.cleanup)
        self.root=Path(temporary.name).resolve();self.addCleanup(patch.stopall)
        patch.object(lifecycle,'ROOT',self.root).start()
        self.context=dict(repository='example/foundation',run_id=123,attempt=2,
                          source_commit='a'*40,workflow='_release-latest.yml')
        patch.dict(os.environ,dict(GITHUB_REPOSITORY=self.context['repository'],GITHUB_RUN_ID='123',
            GITHUB_RUN_ATTEMPT='2',GITHUB_SHA='a'*40,
            GITHUB_WORKFLOW_REF='example/foundation/.github/workflows/_release-latest.yml@refs/heads/main',
            RUNNER_NAME='runner-a',GITHUB_OUTPUT=str(self.root/'output'),GITHUB_STEP_SUMMARY=str(self.root/'summary'))).start()

    def test_certification_plan_defaults_to_all_batches_and_honors_lower_limit(self):
        matrix = {'include': [{'id': 'batch-' + str(index)} for index in range(23)]}
        for limit, expected in [('0', 23), ('4', 4), ('8', 8), ('16', 16), ('23', 23), ('256', 23)]:
            with self.subTest(limit=limit), patch.dict(os.environ, CERTIFICATION_JOBS=limit,
                    TAG='candidate', INVENTORY='a'*64, PROFILE='all-gui'), \
                    patch.object(lifecycle.os, 'chdir'), patch.object(lifecycle.shutil, 'move'), \
                    patch.object(ci, 'fetch_candidate') as fetch, \
                    patch.object(ci, 'qualification_plan'), patch.object(ci, 'module'), \
                    patch.object(ci, 'qualification_batches', return_value=matrix), \
                    patch.object(lifecycle.evidence, 'load'), patch.object(lifecycle, 'output') as output, \
                    patch.object(lifecycle, 'scalar_output') as scalar:
                lifecycle.main('certification-plan')
                fetch.assert_called_once()
                output.assert_called_once_with('matrix', matrix)
                scalar.assert_called_once_with('max_parallel', expected)
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(lifecycle.certification_job_limit(), 0)

    def test_invalid_certification_limit_stops_before_remote_work(self):
        for limit in ('', '-1', '1.5', '257', '08', '1e2', 'true', ' 8', '8\\n'):
            with self.subTest(limit=limit), patch.dict(os.environ, CERTIFICATION_JOBS=limit), \
                    patch.object(lifecycle.os, 'chdir'), patch.object(ci, 'fetch_candidate') as fetch, \
                    patch.object(lifecycle, 'output') as output, \
                    self.assertRaisesRegex(ValueError, 'FOUNDATION_CERTIFICATION_JOBS'):
                lifecycle.main('certification-plan')
            fetch.assert_not_called(); output.assert_not_called()

    def test_certification_cannot_schedule_an_empty_matrix(self):
        with patch.dict(os.environ, CERTIFICATION_JOBS='0', TAG='candidate', INVENTORY='a'*64, PROFILE='core'), \
                patch.object(lifecycle.os, 'chdir'), patch.object(lifecycle.shutil, 'move'), \
                patch.object(ci, 'fetch_candidate'), patch.object(ci, 'qualification_plan'), \
                patch.object(ci, 'module'), patch.object(ci, 'qualification_batches', return_value={'include': []}), \
                patch.object(lifecycle.evidence, 'load'), patch.object(lifecycle, 'output') as output, \
                patch.object(lifecycle, 'scalar_output') as scalar, \
                self.assertRaisesRegex(ValueError, '1 to 256 batches'):
            lifecycle.main('certification-plan')
        output.assert_not_called(); scalar.assert_not_called()

    def test_hosted_checks_translate_identity_at_provider_boundary(self):
        previous = Path.cwd()
        try:
            with patch.dict(os.environ, CHECK='linux-check'), \
                    patch.object(lifecycle.qualification_tasks, 'prepare', return_value={'status': 'prepared'}) as prepare, \
                    patch.object(lifecycle.qualification_tasks, 'run', return_value={'status': 'passed'}) as run:
                lifecycle.main('check-prerequisites')
                lifecycle.main('check')
                prepare.assert_called_once_with(self.root, 'linux-check', '123', 2)
                run.assert_called_once_with(self.root, 'linux-check', '123', 2)
                run.return_value = {'status': 'failed'}
                with self.assertRaisesRegex(ValueError, 'qualification did not pass'):
                    lifecycle.main('check')
        finally:
            os.chdir(previous)

    def file(self,name,data=b'checked bytes'):
        p=self.root/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(data);return p

    def diagnostic_paths(self, workflow, failed):
        name = 'application-evidence-' if workflow == 'sdk-application' else 'native-gui-evidence-'
        text = (ROOT / f'.github/workflows/{workflow}.yml').read_text()
        if workflow == 'sdk-application':
            block = text.split('        name: ' + name, 1)[1].split('        paths: |-\n', 1)[1]
        else:
            block = text.split('        BUNDLE_NAME: ' + name, 1)[1].split('        BUNDLE_PATHS: |-\n', 1)[1]
        lines = []
        for line in block.splitlines():
            if not line.startswith('          '):
                break
            lines.append(line.strip())
        conditional = "${{ job.status == 'failure' && 'build/receipts/failure.json' || '' }}"
        self.assertEqual(lines.count(conditional), 1)
        return '\n'.join(
            ('build/receipts/failure.json' if failed else '') if line == conditional else line
            for line in lines)

    def failure_receipt(self):
        path = self.root / 'build/receipts/failure.json'
        receipt = {'ok': False, 'operation': 'application-build', 'error': 'compiler failed'}
        lifecycle.write(path, receipt)
        with self.assertRaises(FileExistsError):
            lifecycle.write(path, {'ok': True})
        self.assertLess(path.stat().st_size, 4096)
        return path

    def test_early_failure_retains_only_existing_static_receipt(self):
        receipt = self.failure_receipt()
        for name in ('build/receipts/other.json', 'build/base/sdk.tar.gz',
                     'build/produced/application.zip', 'build/native-gui/build/program.exe'):
            self.file(name)
        for workflow in ('sdk-application', 'native-gui'):
            with self.subTest(workflow=workflow):
                root, paths = lifecycle.bundle_inputs(self.diagnostic_paths(workflow, failed=True))
                self.assertEqual(root, self.root / 'build')
                inventory = ci_transport._inventory(root, paths, False)
                self.assertEqual(set(inventory), {'receipts/failure.json'})
                self.assertEqual(inventory['receipts/failure.json']['size'], receipt.stat().st_size)
                self.assertEqual(inventory['receipts/failure.json']['sha256'],
                                 hashlib.sha256(receipt.read_bytes()).hexdigest())

    def test_failure_receipt_and_partial_diagnostics_preserve_declared_build_root(self):
        self.failure_receipt()
        for workflow, directory in (('sdk-application', 'produced'), ('native-gui', 'native-gui')):
            with self.subTest(workflow=workflow):
                self.file(f'build/{directory}/source.junit.xml', b'<testsuite failures="1"/>')
                self.file(f'build/{directory}/build/private.bin')
                root, paths = lifecycle.bundle_inputs(self.diagnostic_paths(workflow, failed=True))
                self.assertEqual(root, self.root / 'build')
                self.assertEqual(set(ci_transport._inventory(root, paths, False)),
                                 {'receipts/failure.json', f'{directory}/source.junit.xml'})

    def test_success_diagnostics_keep_existing_layout_without_failure_receipt(self):
        for workflow, directory, relative in (('sdk-application', 'produced', 'source.junit.xml'),
                                             ('native-gui', 'native-gui', 'native-gui/source.junit.xml')):
            with self.subTest(workflow=workflow):
                self.file(f'build/{directory}/source.junit.xml', b'<testsuite failures="0"/>')
                self.file(f'build/{directory}/build/private.bin')
                root, paths = lifecycle.bundle_inputs(self.diagnostic_paths(workflow, failed=False))
                self.assertEqual(root, self.root / ('build/produced' if workflow == 'sdk-application' else 'build'))
                self.assertEqual(set(ci_transport._inventory(root, paths, False)), {relative})
        self.assertFalse((self.root / 'build/receipts/failure.json').exists())

    def test_successful_application_and_evidence_share_one_publication(self):
        self.file('build/produced/application.tar.gz'); self.file('build/produced/artifact.json')
        self.file('build/produced/source.junit.xml', b'<testsuite/>')
        pointers = [{'manifest': {'id': 1}}, {'manifest': {'id': 2}}]
        with patch.dict(os.environ, APPLICATION_SUCCEEDED='true', TARGET='linux-x86_64',
                BUNDLE_NAME='application-evidence-linux-x86_64-2', BUNDLE_PATHS=self.diagnostic_paths('sdk-application', False)), \
                patch.object(ci_transport, 'publish_bundles', return_value=pointers) as publish:
            lifecycle.store_application_bundles()
        requests = publish.call_args.kwargs['requests']
        self.assertEqual([row['name'] for row in requests], ['application-linux-x86_64-2','application-evidence-linux-x86_64-2'])
        self.assertEqual(set(requests[0]['paths']), {'application.tar.gz','artifact.json'})
        self.assertEqual(requests[1]['paths'], ['source.junit.xml'])
        self.assertTrue(requests[1]['compress'])
        self.assertEqual(json.loads((self.root/'build/transport-pointers/application-linux-x86_64-2.json').read_text()), pointers[0])

    def test_failed_application_still_retains_diagnostics_without_publishing_partial_application(self):
        self.failure_receipt(); self.file('build/produced/partial.tar.gz')
        with patch.dict(os.environ, APPLICATION_SUCCEEDED='false', TARGET='linux-x86_64',
                BUNDLE_NAME='application-evidence-linux-x86_64-2', BUNDLE_PATHS=self.diagnostic_paths('sdk-application', True)), \
                patch.object(ci_transport, 'publish_bundle', return_value={}) as publish, \
                patch.object(ci_transport, 'publish_bundles') as batch:
            lifecycle.store_application_bundles()
        batch.assert_not_called()
        self.assertEqual(publish.call_args.kwargs['paths'], ['receipts/failure.json'])

    def test_candidate_aggregation_fetches_all_nine_receipts_in_one_complete_batch(self):
        import test_plan
        selected = {'include': [dict(target=target, runner=runner) for target,runner in ci.STANDARD.items()]}
        previous = Path.cwd()
        try:
            with patch.dict(os.environ, CANDIDATE_TARGETS=json.dumps(selected), DEVFAST='false'), \
                    patch.object(lifecycle,'fetch_bundles') as fetch, \
                    patch.object(test_plan,'candidate_merge',return_value={'status':'passed'}) as merge:
                lifecycle.main('candidate-aggregate')
        finally:
            os.chdir(previous)
        for target in ci.STANDARD:
            self.assertEqual(json.loads((self.root/'build/candidate-results'/target/'coverage.json').read_text()),
                             {'status':'passed'})
        fetch.assert_called_once(); self.assertEqual(len(fetch.call_args.args[0]), 9)
        self.assertEqual(merge.call_count, 3)
        self.assertTrue(all(len(call.args[0]) == 3 and call.kwargs == {'diagnostic':False} for call in merge.call_args_list))

    def test_rust_and_cpp_source_bundles_restore_flat_reports_for_real_candidate_merge(self):
        import ci_artifacts
        import test_plan
        workflow = (ROOT / '.github/workflows/candidate.yml').read_text()
        source = workflow.split('  source:\n', 1)[1].split('  package:\n', 1)[0]
        preparation = source.split('    - name: Explicit pinned native Rust host preparation\n', 1)[1].split('    - name:', 1)[0]
        self.assertIn("if: inputs.core_provider == 'rust'", preparation)
        preparation_script = textwrap.dedent(preparation.split('      run: |\n', 1)[1])
        declarations = source.split('        paths: |\n', 1)[1].split('    permissions:', 1)[0]
        scopes = {'core': ['core.fixture'], 'tools': ['tools.fixture'], 'integration': ['integration.fixture']}
        inner = dict(schema_version=1, system='fixture', status='passed', inventory=['one'],
                     excluded={}, results={'one': {'status': 'passed'}})
        target = 'linux-x86_64'
        selected = {'include': [dict(target=target, runner=ci.STANDARD[target])]}
        previous = Path.cwd()
        try:
            for provider in ('cpp', 'rust'):
                with self.subTest(provider=provider):
                    checkout = self.root / provider; checkout.mkdir()
                    release = checkout / 'build/release'; release.mkdir(parents=True)
                    artifacts = checkout / 'downloaded'; artifacts.mkdir()
                    plan = dict(schema_version=1, source='b' * 64, configuration=hashlib.sha256(provider.encode()).hexdigest(),
                                tests=sorted(name for names in scopes.values() for name in names), scopes=scopes,
                                platform_exclusions={}, timeouts={name: 30 for names in scopes.values() for name in names})
                    plan['id'] = test_plan.digest(plan)
                    original_receipt = archive.encoded(dict(schema_version=1, target=target, recipe='c' * 64,
                        scope='explicit-native-host-preparation', files={'rust-sdk.tar.gz': 'd' * 64}))
                    with patch.object(lifecycle, 'ROOT', checkout), patch.dict(os.environ, TARGET=target,
                            CORE_PROVIDER=provider, GITHUB_ACTIONS='true', CANDIDATE_TARGETS=json.dumps(selected),
                            DEVFAST='false', FOUNDATION_CI_ARTIFACTS_DIR=str(artifacts),
                            FOUNDATION_CI_ARTIFACTS_REQUIRED='true', FOUNDATION_CI_ARTIFACT_RELEASE_FALLBACK='false'):
                        os.chdir(checkout)
                        if provider == 'rust':
                            def prepare(command, **kwargs):
                                self.assertEqual(command, [sys.executable, '-B', '.github/scripts/rust_host_prepare.py',
                                                           '--target', target])
                                self.assertEqual(kwargs, {'check': True})
                                (checkout / 'build/native-rust-preparation.json').write_bytes(original_receipt)
                            with patch('subprocess.run', side_effect=prepare):
                                exec(compile(preparation_script, 'candidate-rust-preparation', 'exec'), {})
                            self.assertEqual((release / 'native-rust-preparation.json').read_bytes(), original_receipt)
                        else:
                            self.assertFalse((release / 'native-rust-preparation.json').exists())
                        (release / 'build-info.txt').write_text('provider=' + provider)
                        (release / 'test-reports').mkdir()
                        archive.write_json(release / 'test-reports/fixture.json', inner)
                        for scope, names in scopes.items():
                            report = release / ('candidate-' + scope + '.json')
                            junit = report.with_suffix('.junit.xml')
                            junit.write_text('<testsuite><testcase name="' + names[0] + '" status="run" time="0.1"/></testsuite>')
                            archive.write_json(report, dict(schema_version=1, plan=plan, scope=scope,
                                results={name: 'passed' for name in names}, tool_reports={'tools.fixture': inner} if scope == 'tools' else {},
                                exit_code=0, junit_sha256=archive.digest(junit), timing=dict(
                                    tests=test_plan.junit_timings(junit, names, plan['timeouts']),
                                    phase_seconds={'build': 0.1, 'test': 0.1, 'total': 0.2})))
                            base, paths = lifecycle.bundle_inputs(declarations.replace('${{ matrix.scope }}', scope))
                            self.assertEqual(base, release)
                            slot = 'source-' + target + '-' + scope
                            output = artifacts / ci_artifacts.artifact_name(self.context, slot)
                            ci_artifacts.prepare(**self.context, name=slot + '-2', root=base, paths=paths,
                                output=output, runner_name='runner-a', job_key='source', outcome='success')
                            manifest = json.loads((output / 'manifest.json').read_text())
                            self.assertIn(report.name, manifest['files'])
                            self.assertIn(junit.name, manifest['files'])
                            self.assertFalse(any(name.startswith('release/') for name in manifest['files']))
                            self.assertEqual('native-rust-preparation.json' in manifest['files'], provider == 'rust')
                            if provider == 'rust':
                                self.assertEqual(manifest['files']['native-rust-preparation.json']['sha256'],
                                                 hashlib.sha256(original_receipt).hexdigest())
                        # Exercise actual native archive verification, restored paths,
                        # JSON/JUnit identities and candidate_merge; only network is forbidden.
                        with patch.object(lifecycle.delivery, 'Remote', side_effect=AssertionError('unexpected network')):
                            lifecycle.main('candidate-aggregate')
                        coverage = json.loads((checkout / 'build/candidate-results' / target / 'coverage.json').read_text())
                        self.assertEqual(coverage['status'], 'passed')
                        self.assertEqual(coverage['executed_scopes'], ['core', 'integration', 'tools'])
                        self.assertEqual(coverage['omitted_scopes'], [])
                        if provider == 'rust':
                            for scope in scopes:
                                self.assertEqual((checkout / 'build/candidate-results' / target / scope /
                                    'native-rust-preparation.json').read_bytes(), original_receipt)
        finally:
            os.chdir(previous)

    def test_assembly_fetches_one_unique_sdk_batch_before_building_candidate(self):
        recipes = {'linux-x86_64': 'b' * 64, 'windows-x86_64': 'a' * 64, 'linux-aarch64': 'b' * 64}
        events = []
        previous = Path.cwd()
        try:
            with patch.dict(os.environ, PROFILE='core', EXPERIMENT='false', CORE_PROVIDER='cpp',
                            PACKAGE_REPOSITORY='false'), \
                    patch.object(lifecycle.evidence, 'load', side_effect=[recipes, {}]), \
                    patch.object(lifecycle.delivery, 'fetch_bases',
                                 side_effect=lambda *args: events.append('fetched')) as fetch, \
                    patch.object(ci, 'assemble_release', side_effect=lambda *args: events.append('assembled')), \
                    patch.object(lifecycle.delivery, 'publish_candidate',
                                 return_value={'delivery': {'inventory_sha256': 'c' * 64}}), \
                    patch.object(lifecycle, 'write'), patch.object(lifecycle, 'scalar_output'), \
                    patch.object(lifecycle.evidence, 'sha', return_value='d' * 64):
                lifecycle.main('assemble')
        finally:
            os.chdir(previous)
        fetch.assert_called_once_with('example/foundation', ['a' * 64, 'b' * 64], Path('build/base'))
        self.assertEqual(events, ['fetched', 'assembled'])

    def test_assembly_stops_before_candidate_or_publication_after_sdk_batch_failure(self):
        previous = Path.cwd()
        try:
            with patch.object(lifecycle.evidence, 'load', return_value={'linux': 'a' * 64}), \
                    patch.object(lifecycle.delivery, 'fetch_bases',
                                 side_effect=ValueError('remote inventory changed')), \
                    patch.object(ci, 'assemble_release') as assemble, \
                    patch.object(lifecycle.delivery, 'publish_candidate') as publish, \
                    patch.object(lifecycle, 'write') as write, \
                    self.assertRaisesRegex(ValueError, 'remote inventory changed'):
                lifecycle.main('assemble')
        finally:
            os.chdir(previous)
        assemble.assert_not_called()
        publish.assert_not_called()
        write.assert_not_called()

    def test_single_directory_selects_contents_without_invalid_dot_path(self):
        self.file('build/group/a.json');self.file('build/group/nested/b.txt')
        root,paths=lifecycle.bundle_inputs('build/group/')
        self.assertEqual(root,self.root/'build/group');self.assertEqual(paths,['a.json','nested'])
        self.assertEqual(set(ci_transport._inventory(root,paths,False)),{'a.json','nested/b.txt'})

    def test_explicit_multiple_paths_preserve_common_root(self):
        self.file('build/source/source.tar.gz');self.file('build/source/recipes.json');self.file('build/source/foreign')
        root,paths=lifecycle.bundle_inputs('build/source/source.tar.gz\nbuild/source/recipes.json')
        self.assertEqual(root,self.root/'build/source');self.assertEqual(paths,['recipes.json','source.tar.gz'])
        self.assertNotIn('foreign',ci_transport._inventory(root,paths,False))

    def test_wildcard_archive_selection_does_not_require_absent_platform_format(self):
        self.file('build/package/packages/app.zip');self.file('build/package/packages/app.json')
        root,paths=lifecycle.bundle_inputs('build/package/packages/*.tar.gz\nbuild/package/packages/*.zip\nbuild/package/packages/*.json')
        self.assertEqual(root,self.root/'build/package/packages');self.assertEqual(paths,['app.json','app.zip'])

    def test_paths_are_bounded_and_cannot_escape(self):
        for value in ('','/outside','build/../outside','build\\x','C:drive','x\n'*101):
            with self.subTest(value=value),self.assertRaises(ValueError): lifecycle.bundle_inputs(value)

    def test_called_workflow_identity_comes_from_exact_caller(self):
        self.assertEqual(lifecycle.storage_context(),self.context)
        for value in ('other/repo/.github/workflows/a.yml@main','example/foundation/.github/workflows/../a.yml@main'):
            with patch.dict(os.environ,{'GITHUB_WORKFLOW_REF':value}),self.assertRaises(ValueError): lifecycle.storage_context()

    def test_publish_pointer_uses_existing_api_and_preserves_layout(self):
        self.file('build/report/check.json')
        pointer=dict(self.context,name='report',manifest={'id':9,'sha256':'b'*64})
        with patch.dict(os.environ,{'BUNDLE_NAME':'report','BUNDLE_PATHS':'build/report/'}), \
             patch.object(ci_transport,'publish_bundle',return_value=pointer) as publish:
            lifecycle.store_bundle()
        self.assertEqual(publish.call_args.kwargs,dict(self.context,name='report',root=self.root/'build/report',
                                                      paths=['check.json'],runner_name='runner-a',compress=False))
        self.assertEqual(json.loads((self.root/'build/transport-pointers/report.json').read_text()),pointer)
        self.assertIn('"manifest"',(self.root/'summary').read_text())

    def restore(self,output,files):
        def fetch(*args,**kwargs):
            root=Path(args[6]);root.mkdir()
            inventory={}
            for name,data in files.items():
                path=root/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(data)
                inventory[name]=dict(size=len(data),mode=0o644,sha256=hashlib.sha256(data).hexdigest())
            return {'manifest':{'files':inventory}}
        original=ci.module
        with patch.object(ci,'module',side_effect=lambda name: Mock(fetch_bundle=fetch) if name=='ci_transport' else original(name)):
            return ci.restore_run_bundle(**self.context,name='report',output=output)

    def test_restore_merges_only_absent_selected_files(self):
        self.file('build/foreign.txt',b'foreign')
        self.restore(self.root/'build',{'candidate/a.txt':b'a','delivery.json':b'{}'})
        self.assertEqual((self.root/'build/foreign.txt').read_bytes(),b'foreign')
        self.assertEqual((self.root/'build/candidate/a.txt').read_bytes(),b'a')

    def test_restore_preflights_all_collisions_before_any_copy(self):
        self.file('build/z.txt',b'foreign')
        with self.assertRaisesRegex(ValueError,'existing file'):
            self.restore(self.root/'build',{'a.txt':b'a','z.txt':b'changed'})
        self.assertFalse((self.root/'build/a.txt').exists());self.assertEqual((self.root/'build/z.txt').read_bytes(),b'foreign')

    def test_restore_rejects_reparse_destination_before_fetch(self):
        root=self.root/'build';root.mkdir();original=Path.lstat
        from types import SimpleNamespace
        def lstat(path,*args,**kwargs):
            value=original(path,*args,**kwargs)
            return SimpleNamespace(st_mode=value.st_mode,st_file_attributes=0x400) if path==root else value
        with patch.object(Path,'lstat',lstat),self.assertRaisesRegex(ValueError,'reparse'):
            self.restore(root,{'new-file':b'must not escape'})
        self.assertEqual(list(root.iterdir()),[])

    def test_restore_rejects_file_as_parent(self):
        self.file('build/a',b'foreign')
        with self.assertRaisesRegex(ValueError,'ordinary directories'):
            self.restore(self.root/'build',{'a/child':b'changed'})
        self.assertEqual((self.root/'build/a').read_bytes(),b'foreign')


class RetainedBundleTests(unittest.TestCase):
    setUp=retention.SdkRetentionTests.setUp

    def prepare(self):
        self.request=dict(schema_version=2,repository='example/foundation',target='windows-x86_64',profile='core',
            recipe_id=self.recipe,run_id=123,source_commit='a'*40,attempt=2,job_id=456,workflow='sdk-import.yml',
            group={'manifest_id':789,'manifest_sha256':'b'*64},proof={'manifest_id':790,'manifest_sha256':'c'*64})
        self.receipt=dict(schema_version=1,status='verified',qualification='unqualified',publication_approved=False,
            target='windows-x86_64',profile='core',recipe_id=self.recipe,source_commit='a'*40,run_id='123',attempt=2,files=self.files)
        self.origin=dict(origin='retained',recipe=self.recipe,legacy_import={'source_commit':'d'*40})
        self.calls=[]

    def fetch(self,*args,**kwargs):
        self.calls.append((args,kwargs));name=args[5];path=Path(args[6])
        if name.startswith('sdk-group'): shutil.copytree(self.group,path)
        else:
            path.mkdir();archive.write_json(path/'sdk-retention.json',self.receipt);archive.write_json(path/'sdk-origin.json',self.origin)
        return {'pointer':{'name':name},'manifest':{'files':{}},'producer':{'id':456}}

    def recover(self):
        original=ci.module
        with patch.object(ci,'module',side_effect=lambda name: Mock(fetch_bundle=self.fetch) if name=='ci_transport' else original(name)):
            return ci.retained_sdk('example/foundation',self.request,'windows-x86_64','core',self.recipe,self.root/'restored')

    def test_exact_bundle_manifests_restore_identical_triplet_without_approval(self):
        self.prepare();result=self.recover()
        self.assertEqual(store.verify_group(self.root/'restored',self.recipe),self.files)
        self.assertEqual(result['qualification'],'unqualified');self.assertIs(result['publication_approved'],False)
        self.assertEqual(result['previous_origin'],self.origin)
        for args,kwargs in self.calls:
            kind='group' if args[5].startswith('sdk-group') else 'proof'
            self.assertEqual(args[:5],('example/foundation',123,2,'a'*40,'sdk-import.yml'))
            self.assertEqual(kwargs,dict(job_id=456,manifest_id=self.request[kind]['manifest_id'],
                manifest_sha256=self.request[kind]['manifest_sha256'],allow_failed=True,transport=None))

    def test_changed_retention_binding_or_triplet_is_rejected(self):
        for key,value in [('source_commit','b'*40),('qualification','passed'),('files',{})]:
            with self.subTest(key=key):
                self.prepare();self.receipt[key]=value
                with self.assertRaises(ValueError): self.recover()
                self.assertFalse((self.root/'restored').exists())

    def test_ordinary_reuse_rejects_legacy_and_unknown_workflow_without_fetch(self):
        self.prepare();self.request['schema_version']=1
        with patch.object(ci_transport,'fetch_bundle') as fetch,self.assertRaisesRegex(ValueError,'explicit import'):
            self.recover()
        self.assertEqual(self.calls,[])
        self.prepare();self.request['workflow']='other.yml'
        with self.assertRaisesRegex(ValueError,'explicit producer'): self.recover()
        self.assertEqual(self.calls,[])

    def test_import_request_uses_nested_transport_manifest_identity(self):
        self.prepare();context={key:self.request[key] for key in ('repository','run_id','attempt','source_commit','workflow')}
        for kind in ('group','proof'):
            reference=self.request[kind]
            archive.write_json(self.root/f'build/transport-pointers/sdk-{kind}-windows-x86_64-2.json',
                dict(context,job_id=456,name=f'sdk-{kind}-windows-x86_64-2',
                     manifest=dict(id=reference['manifest_id'],sha256=reference['manifest_sha256'])))
        with patch.object(lifecycle,'storage_context',return_value=context): lifecycle.main('sdk-import-request')
        self.assertEqual(json.loads((self.root/'build/import-retained-input.json').read_text()),self.request)
        self.assertIn('retained_input=',(self.root/'step-output').read_text())


class LegacyImportTests(unittest.TestCase):
    setUp=retention.SdkRetentionTests.setUp
    prepare=retention.RetainedSdkRecoveryTests.prepare
    pack=retention.RetainedSdkRecoveryTests.pack
    download=retention.RetainedSdkRecoveryTests.download

    def test_explicit_import_preserves_complete_original_proof_and_unqualified_lineage(self):
        self.prepare();proof=self.root/'original proof'
        result=ci.import_legacy_sdk(self.repository,self.request,'windows-x86_64','core',self.recipe,
            self.root/'restored',proof_output=proof,transport=self.transport,download=self.download)
        self.assertEqual(set(p.name for p in proof.iterdir()),set(self.proof))
        self.assertEqual(result['request'],self.request);self.assertEqual(result['producer'],self.job)
        self.assertEqual((proof/'other-report.txt').read_bytes(),self.proof['other-report.txt'])
        self.assertEqual(result['qualification'],'unqualified');self.assertFalse(result['publication_approved'])

    def test_lifecycle_import_rebinds_retention_without_faking_consumer_approval(self):
        self.prepare();retained=self.root/'original group';self.group.rename(retained)
        (self.root/'build/sdk-origin.json').unlink()
        result=dict(origin='retained',recipe=self.recipe,qualification='unqualified',publication_approved=False,
                    request=self.request,retention=self.receipt_value,producer=self.job)
        def import_group(repository,request,target,profile,recipe,output,*,proof_output):
            self.assertEqual((repository,request,target,profile,recipe),
                (self.repository,self.request,'windows-x86_64','core',self.recipe))
            shutil.copytree(retained,output);proof_output.mkdir()
            (proof_output/'original-report.json').write_bytes(b'{"status":"passed"}')
            return result
        with patch.dict(os.environ,{'LEGACY_INPUT':json.dumps(self.request),'GITHUB_SHA':'e'*40,'GITHUB_RUN_ID':'999'}), \
             patch.object(lifecycle.ci,'import_legacy_sdk',side_effect=import_group):
            lifecycle.main('sdk-import-legacy')
        receipt=json.loads((self.root/'build/sdk-retention.json').read_text())
        self.assertEqual((receipt['source_commit'],receipt['run_id']),('e'*40,'999'))
        self.assertEqual(receipt['files'],self.files);self.assertEqual(receipt['qualification'],'unqualified')
        self.assertFalse(receipt['publication_approved'])
        self.assertEqual(json.loads((self.root/'build/sdk-import.json').read_text()),result)
        self.assertEqual(json.loads((self.root/'build/sdk-origin.json').read_text())['legacy_import'],result)
        self.publisher.assert_not_called()

    def test_import_proof_collision_rejects_without_overwriting_either_tree(self):
        self.prepare();proof=self.root/'original proof';proof.mkdir();(proof/'foreign').write_bytes(b'foreign')
        with self.assertRaisesRegex(ValueError,'proof output must be new'):
            ci.import_legacy_sdk(self.repository,self.request,'windows-x86_64','core',self.recipe,
                self.root/'restored',proof_output=proof,transport=self.transport,download=self.download)
        self.assertFalse((self.root/'restored').exists());self.assertEqual((proof/'foreign').read_bytes(),b'foreign')


class WorkflowContractTests(unittest.TestCase):
    def test_workflows_route_actions_artifacts_through_bounded_adapter(self):
        for path in (ROOT/'.github/workflows').glob('*.yml'):
            with self.subTest(path=path.name):
                text=path.read_text()
                for forbidden in ('actions/upload-artifact@','actions/download-artifact@','gh run download'):
                    self.assertNotIn(forbidden,text)

    def test_small_evidence_has_downloads_before_consumers_and_keeps_all_failure_receipts(self):
        candidate = (ROOT/'.github/workflows/candidate.yml').read_text()
        certify = (ROOT/'.github/workflows/certify.yml').read_text()
        self.assertEqual(candidate.count('uses: ./.github/actions/ci-evidence-publish'), 3)
        # Preparation, checks, native package checks, certificate and attachment.
        self.assertEqual(certify.count('uses: ./.github/actions/ci-evidence-publish'), 5)
        self.assertLess(candidate.index('uses: ./.github/actions/ci-evidence-download'),
                        candidate.index('lifecycle.py candidate-aggregate'))
        self.assertIn('slot: ${{ strategy.job-index }}', certify)
        self.assertIn("if: always() && needs.prepare.result == 'success'", certify)
        self.assertIn('max_parallel: ${{ steps.plan.outputs.max_parallel }}', certify)
        self.assertIn('max-parallel: ${{ fromJSON(needs.prepare.outputs.max_parallel) }}', certify)
        self.assertIn("CERTIFICATION_JOBS: ${{ vars.FOUNDATION_CERTIFICATION_JOBS || '0' }}", certify)
        self.assertIn('build/prerequisites/', certify)
        self.assertIn('build/attachment-plan.json', certify)
        self.assertEqual(certify.count('uses: ./.github/actions/ci-evidence-download'), 4)
        for workflow in ('sdk-maintenance', 'sdk-import'):
            self.assertNotIn('uses: ./.github/actions/ci-evidence-publish',
                             (ROOT/f'.github/workflows/{workflow}.yml').read_text())

    def test_native_package_consumers_remain_independent_and_application_assembly_is_gated(self):
        package = (ROOT/'.github/workflows/candidate-package.yml').read_text()
        self.assertIn('needs: package', package)
        self.assertIn('pattern: package-${{ inputs.target }}', package)
        self.assertNotIn('bundle-store', package)
        self.assertLess(package.index('ci-evidence-download'), package.index("'bundle-fetch'"))
        application = (ROOT/'.github/workflows/sdk-application.yml').read_text()
        self.assertIn("needs.application.result == 'success'", application)
        self.assertIn("inputs.require_regression && needs.regression.result == 'success'", application)
        self.assertIn('pattern: source', application)
        self.assertIn("pattern: '{source,application-linux-*,application-windows-*,application-browser-*}'", application)
        self.assertNotIn('lifecycle.py application-bundles', application)
        self.assertIn("- if: always()\n      name: Retain application diagnostics including failures", application)
        # Preparation retains frozen controls; existing source/application handoffs and
        # public SDK assets supply the bytes without a duplicate full candidate relay.
        self.assertNotIn('lifecycle.py bundle-store', application)
        preview = application.split('Retain candidate preparation controls', 1)[1].split('    - if: inputs.execute', 1)[0]
        self.assertIn('name: candidate-${{ github.run_attempt }}', preview)
        self.assertIn('build/candidate/release.json', preview)
        self.assertNotIn('build/candidate/\n', preview)

    def test_cleanup_uses_ids_after_successful_final_consumers_and_keeps_small_receipts(self):
        publish = (ROOT/'.github/actions/ci-evidence-publish/action.yml').read_text()
        self.assertIn('value: ${{ steps.upload.outputs.artifact-id }}', publish)
        self.assertIn('retention-days: 1', publish)
        for filename in ('candidate.yml', '_release-latest.yml', 'promote.yml'):
            self.assertNotIn('uses: ./.github/actions/ci-artifact-cleanup',
                             (ROOT/'.github/workflows'/filename).read_text())
        for filename, barrier, identity in (
                ('candidate-package.yml', "'--runtime-only'", 'needs.package.outputs.artifact_id'),
                ('sdk-application.yml', 'id: publication', 'steps.cleanup_inputs.outputs.ids'),
                ('certify.yml', "'attach-certificate'", 'needs.record.outputs.certificate_artifact_id')):
            text = (ROOT/'.github/workflows'/filename).read_text()
            with self.subTest(workflow=filename):
                self.assertEqual(text.count('uses: ./.github/actions/ci-artifact-cleanup'), 1)
                self.assertLess(text.index(barrier), text.index('uses: ./.github/actions/ci-artifact-cleanup'))
                cleanup = text.split('uses: ./.github/actions/ci-artifact-cleanup', 1)[1]
                self.assertIn('artifact-ids:', cleanup)
                self.assertIn(identity, cleanup)
                self.assertIn('continue-on-error: true', cleanup)
                self.assertIn('timeout-minutes: 1', cleanup)
                gate = text[:text.index('uses: ./.github/actions/ci-artifact-cleanup')].rsplit('    - ', 1)[1]
                self.assertIn('success() &&', gate)
                self.assertIn('!inputs.preserve_artifacts', gate)
                self.assertIn('actions: write', text)
        application = (ROOT/'.github/workflows/sdk-application.yml').read_text()
        self.assertIn("inputs.execute && !inputs.preserve_artifacts && steps.publication.outputs.published == 'true'", application)
        self.assertIn("steps.cleanup_inputs.outcome == 'success'", application)
        certificate = (ROOT/'.github/workflows/certify.yml').read_text()
        self.assertIn("steps.result.outputs.attached == 'true'", certificate)
        for text, receipt in ((application, 'name: Retain candidate publication receipt'),
                              (certificate, 'name: Retain verified certification-delivery-')):
            self.assertLess(text.index(receipt), text.index('uses: ./.github/actions/ci-artifact-cleanup'))
        self.assertIn('source_artifact_id: ${{ steps.source_bundle.outputs.artifact-id }}', application)
        self.assertIn('artifact_id: ${{ steps.package_bundle.outputs.artifact-id }}',
                      (ROOT/'.github/workflows/candidate-package.yml').read_text())
        self.assertIn('certificate_artifact_id: ${{ steps.certificate_bundle.outputs.artifact-id }}',
                      (ROOT/'.github/workflows/certify.yml').read_text())

    def test_preservation_reaches_nested_last_consumers_and_permissions_allow_only_needed_cleanup(self):
        for filename, count in (('_release-latest.yml', 2), ('sdk-application.yml', 1), ('candidate.yml', 1)):
            text = (ROOT/'.github/workflows'/filename).read_text()
            self.assertEqual(text.count('preserve_artifacts: ${{ inputs.preserve_artifacts }}'), count)
        package = (ROOT/'.github/workflows/candidate-package.yml').read_text()
        self.assertIn('preserve_artifacts:\n        type: boolean\n        default: false', package)
        self.assertIn('contents: read\n      actions: write', package.split('  copied:\n')[1])
        candidate = (ROOT/'.github/workflows/candidate.yml').read_text().split('  package:\n')[1].split('  sanitizer:\n')[0]
        self.assertIn('actions: write', candidate)
        self.assertNotIn('  cleanup:\n', (ROOT/'.github/workflows/sdk-application.yml').read_text())
        self.assertNotIn('  cleanup:\n', (ROOT/'.github/workflows/promote.yml').read_text())

    def test_application_cleanup_collects_complete_unique_matrix_outputs_for_both_profiles(self):
        import textwrap
        application = (ROOT/'.github/workflows/sdk-application.yml').read_text()
        block = application.split('      id: cleanup_inputs\n', 1)[1].split('    - name: Remove source', 1)[0]
        code = compile(textwrap.dedent(block.split('      run: |\n', 1)[1]), 'cleanup-inputs', 'exec')
        targets = ('linux-x86_64', 'linux-aarch64', 'windows-x86_64', 'browser-wasm32')
        for target in targets:
            self.assertIn(target.replace('-', '_')+": ${{ matrix.target == '"+target+"' && steps.application_bundle.outputs.artifact-id || '' }}", application)
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)/'output'
            def run(selected, ids, source='100'):
                output.unlink(missing_ok=True)
                environment = dict(APPLICATION_MATRIX=json.dumps({'include': [{'target': t} for t in selected]}),
                                   APPLICATION_ARTIFACT_IDS=json.dumps(ids), SOURCE_ARTIFACT_ID=source,
                                   GITHUB_OUTPUT=str(output))
                with patch.dict(os.environ, environment): exec(code, {})
                return json.loads(output.read_text().removeprefix('ids='))
            for selected in (targets[:3], targets):
                ids = {target.replace('-', '_'): str(i+200) for i,target in enumerate(reversed(selected))}
                self.assertEqual(set(run(selected, ids)), {'100', *ids.values()})
            complete = {target.replace('-', '_'): str(i+200) for i,target in enumerate(targets)}
            for selected, ids, source in (
                    (targets, {k:v for k,v in complete.items() if k!='browser_wasm32'}, '100'),
                    (targets[:3], complete, '100'),
                    (targets, dict(complete, foreign='900'), '100'),
                    (targets, dict(complete, browser_wasm32=''), '100'),
                    (targets, dict(complete, browser_wasm32='200'), '100'),
                    (targets, complete, '200'), (targets, complete, ''),
                    (targets, complete, '100\n200'), (targets+targets[:1], complete, '100'),
                    (('foreign',), {'foreign':'200'}, '100')):
                with self.subTest(targets=selected, ids=ids, source=source):
                    with self.assertRaises(SystemExit): run(selected, ids, source)
                    self.assertFalse(output.exists())

    def test_repository_cleanup_is_manual_only_and_keeps_run_history_and_releases(self):
        text = (ROOT/'.github/workflows/cleanup-artifacts.yml').read_text()
        trigger = text.split("'on':\n", 1)[1].split('permissions:', 1)[0]
        self.assertEqual(trigger.strip(), 'workflow_dispatch:')
        self.assertIn('actions: write', text)
        self.assertIn('contents: read', text)
        self.assertNotIn('contents: write', text)
        self.assertIn('cancel-in-progress: false', text)
        self.assertIn('timeout-minutes: 30', text)
        self.assertIn('persist-credentials: false', text)
        self.assertIn('run: python3 -B tools/ci_cleanup_repository.py', text)
        self.assertIn('GH_TOKEN: ${{ github.token }}', text)
        for forbidden in ('upload-artifact', 'ci-evidence-publish', 'gh run delete', 'release delete'):
            self.assertNotIn(forbidden, text)
        for path in (ROOT/'.github/workflows').glob('*.yml'):
            if path.name != 'cleanup-artifacts.yml':
                self.assertNotIn('cleanup-artifacts.yml', path.read_text())

    def test_explicit_legacy_import_neither_builds_nor_publishes_a_base(self):
        text=(ROOT/'.github/workflows/sdk-import.yml').read_text()
        for required in ('sdk-import-legacy','sdk-import-request','sdk-group-','sdk-proof-','build/legacy-proof/'):
            self.assertIn(required,text)
        for forbidden in ('sdk-produce','publish-bases','execute:', 'delete'):
            self.assertNotIn(forbidden,text)

    def test_called_workflows_export_exact_result_outputs(self):
        for name,outputs in {'sdk-application':['tag','inventory_sha256','source_commit','delivery_sha256','published'],
            'certify':['certificate_sha256','certification_run','certification_attempt','inventory_sha256','eligible_for_promotion','attached'],
            'promote':['promoted']}.items():
            text=(ROOT/f'.github/workflows/{name}.yml').read_text()
            self.assertIn('workflow_call:',text)
            for output in outputs: self.assertIn('outputs.'+output,text)
            if name=='sdk-application':
                self.assertIn("jobs.assemble.outputs.published || 'false'",text)
                self.assertIn('published: ${{ steps.publication.outputs.published }}',text)
                self.assertIn('jobs.assemble.outputs.regression_result',text)


if __name__=='__main__': unittest.main()
