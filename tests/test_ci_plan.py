import importlib.util
from contextlib import nullcontext
from pathlib import Path, PurePosixPath, PureWindowsPath
import tempfile
import json
import subprocess
import sys
import copy
import unittest
from unittest.mock import Mock, patch

spec = importlib.util.spec_from_file_location("ci_plan", Path(__file__).resolve().parents[1] / "tools/ci_plan.py")
ci = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ci)


class CiPlanTests(unittest.TestCase):
    def test_default_prepared_operations_reject_missing_rust_before_building(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with patch.object(ci, 'assert_host'), patch.object(ci.subprocess, 'run') as launch:
                with self.assertRaisesRegex(ValueError, 'exact retained SDK group'):
                    ci.prepared_check('linux-x86_64', 'a' * 64, root / 'group', root / 'check')
                with self.assertRaisesRegex(ValueError, 'exact retained SDK group'):
                    ci.prepared_package('linux-x86_64', 'a' * 64, root / 'group', root / 'source', root / 'package')
                launch.assert_not_called()
            self.assertFalse((root / 'check').exists()); self.assertFalse((root / 'package').exists())

    def test_release_matrix_freezes_rust_inputs_and_cpp_opt_out(self):
        recipes = {target: 'a' * 64 for target in ci.STANDARD}
        rows = ci.release_matrix(recipes)['include']
        self.assertEqual({row['target']: row['rust_recipe'] for row in rows},
                         {target: ci.rust_recipe(target) for target in ci.STANDARD})
        self.assertEqual({row['core_provider'] for row in rows}, {'rust'})
        with patch.object(ci, 'rust_recipe', side_effect=AssertionError('C++ recipe discovery')):
            rows = ci.release_matrix(recipes, core_provider='cpp')['include']
        self.assertEqual({row['core_provider'] for row in rows}, {'cpp'})
        self.assertEqual({row['rust_recipe'] for row in rows}, {''})

    def test_browser_matrix_requires_exact_matched_rust_cpp_tuple(self):
        recipes = {target: 'a' * 64 for target in ci.RUST_RECIPES}
        with self.assertRaisesRegex(ValueError, r'exact matched C\+\+ SDK'):
            ci.release_matrix(recipes, 'all-gui')
        paired = ci.module('rust_sdk').checked_recipe(ci.ROOT / ci.RUST_RECIPES['browser-wasm32'])
        recipes['browser-wasm32'] = paired['cpp_sdk_recipe_id']
        self.assertEqual(len(ci.release_matrix(recipes, 'all-gui')['include']), 4)

    def test_retained_rust_requires_one_exact_owned_producer(self):
        request = dict(schema_version=1, repository='owner/project', target='linux-x86_64',
            recipe_id='a' * 64, run_id=7, source_commit='b' * 40, attempt=2, job_id=9,
            workflow='sdk-maintenance.yml', group=dict(manifest_id=11, manifest_sha256='c' * 64))
        self.assertEqual(ci.retained_rust_request(request, 'owner/project', 'linux-x86_64', 'a' * 64), request)
        for changes in ({'repository': 'other/project'}, {'target': 'linux-aarch64'},
                        {'recipe_id': 'd' * 64}, {'workflow': 'untrusted.yml'}, {'job_id': True},
                        {'group': {'manifest_id': 11, 'manifest_sha256': 'latest'}}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                ci.retained_rust_request(dict(request, **changes), 'owner/project', 'linux-x86_64', 'a' * 64)

    def test_cpp_lane_has_no_rust_discovery_or_inputs(self):
        with patch.object(ci, 'module') as module:
            self.assertIsNone(ci.rust_selection('cpp', None, None))
            self.assertEqual(ci.install_rust_input('cpp', None, None, Path('out'), None),
                             (['--core-provider', 'cpp'], {'core_provider': 'cpp'}))
            module.assert_not_called()
        for provider, group, recipe in [('cpp', Path('group'), None), ('rust', None, 'a' * 64),
                                        ('rust', Path('group'), 'latest'), ('automatic', None, None)]:
            with self.subTest(provider=provider), self.assertRaises(ValueError):
                ci.rust_selection(provider, group, recipe)

    def test_rust_lane_binds_installed_compiler_bytes_and_complete_group(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); output = root / 'rust-sdk'; output.mkdir()
            (output / 'rust-sdk.json').write_text('manifest fixture')
            (output / 'rustc').write_text('compiler fixture')
            rust = Mock()
            rust.verify_group.return_value = {'retained-input': 'b' * 64}
            rust.verify_rust_sdk.return_value = {'compiler': {'version': '1.63.0', 'rustc': 'rustc'},
                                                 'target': {'triple': 'x86_64-unknown-linux-gnu'}}
            original = ci.module
            with patch.object(ci, 'module', side_effect=lambda name: rust if name == 'rust_sdk' else original(name)):
                self.assertEqual(ci.rust_selection('rust', root / 'group', 'a' * 64), rust.verify_group.return_value)
                flags, identity = ci.install_rust_input('rust', root / 'group', 'a' * 64, output, root / 'cpp-sdk')
            self.assertEqual(flags, ['--core-provider', 'rust', '--rust-sdk', str(output)])
            self.assertEqual(identity['rust_sdk_recipe_id'], 'a' * 64)
            self.assertEqual(identity['rust_compiler_sha256'], original('coverage').sha(output / 'rustc'))
            rust.verify_rust_sdk.assert_called_once_with(output, cpp_sdk=root / 'cpp-sdk', execute=True)

    def test_binary_source_batches_keep_complete_rust_producer_inputs(self):
        original = ci.module
        execution = {'id': 'source', 'target': 'linux-x86_64', 'backend': 'core', 'scope': 'source', 'sdk_payload': 'binary'}
        coverage = Mock(); coverage.executions.return_value = [execution]
        entry = {'target': 'linux-x86_64', 'sdk_recipe': 'a' * 64, 'dependency_recipes': ['a' * 64, 'b' * 64],
                 'core_provider': 'rust', 'rust_sdk_recipe_id': 'b' * 64, 'rust_compiler_version': '1.63.0',
                 'rust_target': 'x86_64-unknown-linux-gnu', 'rust_sdk_manifest_sha256': 'c' * 64,
                 'rust_compiler_sha256': 'd' * 64}
        manifest = {'artifacts': [entry], 'dependencies': [{'recipe_id': 'a' * 64}, {'recipe_id': 'b' * 64, 'kind': 'rust'}]}
        with patch.object(ci, 'module', side_effect=lambda name: coverage if name == 'coverage' else original(name)):
            names = ci.qualification_payload_names({}, {'checks': ['source']}, manifest, '1')
        self.assertIn('qualification-sdk-source-1-1', names)
        self.assertNotIn('qualification-sdk-source-0-1', names)

    def test_default_disjoint_source_scopes_and_independent_producers(self):
        plan = ci.plan()
        checks = plan["checks"]["include"]
        self.assertEqual(len(checks), 9)
        self.assertEqual(len({(x["target"], x["scope"]) for x in checks}), 9)
        self.assertEqual(len(plan["packages"]["include"]), 3)

    def test_focused_selection_does_not_masquerade_as_full(self):
        checks = ci.plan(True, False)["checks"]["include"]
        self.assertEqual({x["scope"] for x in checks}, {"core"})
        self.assertEqual(len(checks), 2)

    def test_optional_runner_requires_explicit_configuration_and_does_not_move_arm(self):
        with self.assertRaises(ValueError):
            ci.plan(pool="faster")
        with self.assertRaises(ValueError):
            ci.plan(pool="faster", configured="self-hosted")
        result = ci.plan(pool="faster", configured="foundation-linux-large")["packages"]["include"]
        self.assertEqual({x["target"]: x["runner"] for x in result}["linux-aarch64"], "ubuntu-24.04-arm")

    def test_actual_architecture_is_checked(self):
        with patch.object(ci.platform, "machine", return_value="ARM64"), patch.object(ci.platform, "system", return_value="Linux"):
            ci.assert_host("linux-aarch64")
            with self.assertRaises(ValueError):
                ci.assert_host("linux-x86_64")

    def test_empty_or_duplicate_archive_inputs_fail(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with self.assertRaises(ValueError):
                ci.archives(root)
            for name in ("a", "b"):
                (root / name).mkdir()
                (root / name / "same.zip").touch()
            with self.assertRaises(ValueError):
                ci.archives(root)

    def test_cpack_private_duplicates_are_not_deliverables(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / 'app.zip').write_bytes(b'archive')
            (root / '_CPack_Packages').mkdir()
            (root / '_CPack_Packages/app.zip').write_bytes(b'archive')
            self.assertEqual(ci.archives(root, recursive=False), [root / 'app.zip'])
            with self.assertRaisesRegex(ValueError, 'duplicate'):
                ci.archives(root)

    def test_release_matrix_requires_every_exact_target_recipe(self):
        recipes = {key: 'a' * 64 for key in ci.STANDARD}
        self.assertEqual({x['target'] for x in ci.release_matrix(recipes)['include']}, set(ci.STANDARD))
        for malformed in ({}, {'linux-x86_64': 'a' * 64}, dict(recipes, unknown='b' * 64), dict(recipes, **{'linux-x86_64': 'latest'})):
            with self.assertRaises(ValueError): ci.release_matrix(malformed)

    def test_gui_publication_preflight_preserves_unresolved_supplier_terms(self):
        recipes = {key: 'a' * 64 for key in (*ci.STANDARD, 'browser-wasm32')}
        policy=ci.module('coverage').load(ci.ROOT/'docs/release-policy.json')
        modules={name:ci.module(name) for name in ('coverage','certify_release')}
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);(root/'third_party').mkdir()
            (root/'third_party/gui-boundary.lock.json').write_text('{"redistribution":{"approved":false}}')
            with patch.object(ci,'ROOT',root),patch.object(ci,'module',side_effect=modules.__getitem__),self.assertRaisesRegex(ValueError,'licensing'):
                ci.release_matrix(recipes,'all-gui',policy)

    def test_complete_commit_required(self):
        self.assertEqual(ci.exact_commit('b' * 40), 'b' * 40)
        for text in ('main', 'HEAD', 'abc123', 'a' * 41, 'B' * 40):
            with self.assertRaises(ValueError): ci.exact_commit(text)


    def test_authorized_faster_arm_and_windows_are_independent(self):
        selected=ci.plan(pool='faster',configured_arm='foundation-arm-large',configured_windows='foundation-windows-large')
        values={row['target']:row['runner'] for row in selected['packages']['include']}
        self.assertEqual(values['linux-x86_64'],'ubuntu-24.04')
        self.assertEqual(values['linux-aarch64'],'foundation-arm-large')
        self.assertEqual(values['windows-x86_64'],'foundation-windows-large')
        for invalid in ('self-hosted','foundation-linux-large','unsafe label'):
            with self.assertRaises(ValueError):ci.plan(pool='faster',configured_windows=invalid)

    def test_validator_never_downloads_an_implicit_supplier(self):
        with tempfile.TemporaryDirectory() as temporary, patch('shutil.which',return_value=None), patch('urllib.request.build_opener') as request:
            with self.assertRaisesRegex(ValueError,'HTTPS'):
                ci.workflow_lint(Path(temporary)/'lint')
            request.assert_not_called()
        from subprocess import CompletedProcess
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);tool=root/'actionlint';tool.write_bytes(b'fixture')
            with patch.object(ci.subprocess,'run',return_value=CompletedProcess([],0,'1.7.12\n')) as run, patch('urllib.request.build_opener') as request:
                result=ci.workflow_lint(root/'lint',executable=str(tool))
                self.assertEqual(result['origin'],'installed');self.assertTrue(result['workflows']);request.assert_not_called()
                self.assertIn('-shellcheck=',run.call_args.args[0])


    def test_retained_validator_rejects_bad_identity_and_insecure_redirect(self):
        import io,urllib.request
        with tempfile.TemporaryDirectory() as temporary, patch('shutil.which',return_value=None):
            output=Path(temporary)/'lint'
            with patch('urllib.request.build_opener') as opener:
                opener.return_value.open.return_value.__enter__.return_value=io.BytesIO(b'wrong archive')
                with self.assertRaisesRegex(ValueError,'pinned identity'):
                    ci.workflow_lint(output,retained_url='https://example.invalid/retained.tar.gz')
                self.assertFalse(output.exists())
            def redirect(handler):
                request=urllib.request.Request('https://example.invalid/archive')
                handler.redirect_request(request,None,302,'moved',{},'http://example.invalid/archive')
            with patch('urllib.request.build_opener',side_effect=redirect):
                with self.assertRaisesRegex(ValueError,'transfer failed'):
                    ci.workflow_lint(output,retained_url='https://example.invalid/archive')
                self.assertFalse(output.exists())

    def test_validator_changed_inputs_cannot_emit_success(self):
        from subprocess import CompletedProcess
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);tool=root/'actionlint';tool.write_bytes(b'fixture')
            def run(argv,**unused):
                if '-version' not in argv: tool.write_bytes(b'changed')
                return CompletedProcess(argv,0,'1.7.12\n')
            with patch.object(ci.subprocess,'run',side_effect=run):
                with self.assertRaisesRegex(ValueError,'changed during'):
                    ci.workflow_lint(root/'lint',executable=str(tool))
            self.assertFalse((root/'lint/qualification.json').exists())


class PortableProducerAssemblyTests(unittest.TestCase):
    def setUp(self):
        import shutil,zipfile
        from test_release import ReleaseTests
        from unittest.mock import Mock
        self.fixture=ReleaseTests();self.fixture.setUp();self.addCleanup(self.fixture.tearDown)
        f=self.fixture;self.root=f.root;self.source=Path(f.spec['source']['path'])
        # Inert archive contents exercise transfer/assembly, not target execution.
        produced=self.root/'producer output';produced.mkdir()
        archive=produced/'windows-x86_64.zip'
        with zipfile.ZipFile(archive,'w') as bundle:
            bundle.writestr('application/bin/foundation-cli.exe',b'inert Windows archive fixture')
            info=(self.root/'application/build-info.txt').read_text().replace('target=linux-x86_64','target=windows-x86_64')
            bundle.writestr('application/build-info.txt',info)
        descriptor=archive.with_name(archive.name+'.json')
        descriptor.write_text(json.dumps(ci.module('artifact').describe(archive)))
        self.entry=dict(path=archive.name,manifest_path=descriptor.name,sha256=ci.module('coverage').sha(archive),
                        target='windows-x86_64',backends=[],sdk_recipe=f.recipe,dependency_recipes=[f.recipe])
        (produced/'artifact.json').write_text(json.dumps(self.entry))
        self.packages=self.root/'receiver packages';self.packages.mkdir()
        self.received=self.packages/'windows-x86_64';shutil.move(str(produced),self.received)
        self.original=ci.module;policy=Mock()
        policy.requirements.return_value=({'targets':{'windows-x86_64':['core']},'checks':[{'scope':'archive'}]},None)
        self.modules=patch.object(ci,'module',side_effect=lambda name:policy if name=='certify_release' else self.original(name))
        self.modules.start();self.addCleanup(self.modules.stop)

    def test_moved_windows_bundle_assembles_with_portable_names(self):
        output=self.root/'released'
        result=ci.assemble_release(self.source,self.packages,self.fixture.base,output,'fixture')
        self.assertEqual(result['artifacts'][0]['archive'],'windows-x86_64.zip')
        self.assertEqual(result['artifacts'][0]['manifest'],'windows-x86_64.zip.json')
        self.assertEqual((output/'windows-x86_64.zip').read_bytes(),(self.received/'windows-x86_64.zip').read_bytes())
        self.assertEqual(result,ci.module('release').verify_release(output))
        for path_type in (PurePosixPath,PureWindowsPath):
            for field in ('path','manifest_path'):
                self.assertEqual(path_type(self.entry[field]).parts,(self.entry[field],))

    def test_foreign_absolute_and_nested_paths_fail_before_assembly(self):
        bad_names=('/work/output/windows-x86_64.zip',r'D:\a\output\windows-x86_64.zip',
                   r'\\server\share\windows-x86_64.zip',r'folder\windows-x86_64.zip',
                   '../windows-x86_64.zip','nested/windows-x86_64.zip','NUL.zip')
        output=self.root/'rejected'
        for field in ('path','manifest_path'):
            for name in bad_names:
                altered=dict(self.entry);altered[field]=name
                (self.received/'artifact.json').write_text(json.dumps(altered))
                with self.subTest(field=field,name=name),self.assertRaises(ValueError):
                    ci.assemble_release(self.source,self.packages,self.fixture.base,output,'fixture')
                self.assertFalse((self.root/'assembly.json').exists());self.assertFalse(output.exists())


class BrowserPrerequisiteTests(unittest.TestCase):
    def selection(self, target='linux-x86_64', environment='ubuntu-24.04'):
        return ci.browser_prerequisite(target, environment, 'hosted-web')

    def test_only_scopes_executing_browser_assertions_install_prerequisites(self):
        for backend in ('core', 'hosted-web', 'wasm', 'fltk'):
            for scope in ('source', 'recovery', 'archive', 'abi', 'apt'):
                self.assertEqual(ci.needs_browser_prerequisite(backend, scope),
                                 backend == 'hosted-web' and scope == 'archive' or
                                 backend == 'wasm' and scope in ('source', 'recovery', 'archive'))

    def test_distribution_and_engine_selection_is_explicit(self):
        for target, arch in (('linux-x86_64', 'amd64'), ('linux-aarch64', 'arm64')):
            selected = self.selection(target)
            self.assertEqual((selected['image'], selected['architecture'], selected['packages']), ('ubuntu:24.04', arch, ['firefox']))
            self.assertEqual(selected['executable'], '/usr/bin/firefox')
            self.assertEqual(selected['repository'], 'host-preinstalled')
        self.assertEqual(self.selection(environment='debian-12')['packages'], ['firefox-esr'])
        chromium = ci.browser_prerequisite('browser-wasm32', 'chromium', 'wasm')
        self.assertEqual((chromium['image'], chromium['packages']), ('', ['google-chrome', 'chromedriver']))
        self.assertEqual(chromium['repository'], 'host-preinstalled')
        self.assertEqual(chromium['executable'], '/usr/bin/google-chrome')
        for target, environment, backend in (('windows-x86_64', 'ubuntu-24.04', 'hosted-web'),
                ('browser-wasm32', 'ubuntu-24.04', 'wasm'), ('linux-x86_64', 'ubuntu-24.04', 'core')):
            with self.assertRaises(ValueError): ci.browser_prerequisite(target, environment, backend)

    def test_setup_requires_disposable_root_and_actual_distribution_and_architecture(self):
        from contextlib import ExitStack
        from subprocess import CompletedProcess
        with ExitStack() as stack:
            stack.enter_context(patch.object(ci.platform, 'system', return_value='Linux'))
            machine = stack.enter_context(patch.object(ci.platform, 'machine', return_value='x86_64'))
            release = stack.enter_context(patch.object(ci.platform, 'freedesktop_os_release', create=True,
                                                       return_value={'ID': 'ubuntu', 'VERSION_ID': '24.04'}))
            uid = stack.enter_context(patch.object(ci.os, 'geteuid', create=True, return_value=0))
            marker = stack.enter_context(patch.object(Path, 'is_file', return_value=True))
            launch = stack.enter_context(patch.object(ci.subprocess, 'run', return_value=CompletedProcess([], 0, 'amd64\n')))
            stack.enter_context(patch.dict(ci.os.environ, {'FOUNDATION_DISPOSABLE_CHECK': '1', 'CHECK_IMAGE': 'ubuntu:24.04'}))
            ci.browser_setup_preflight(self.selection())
            for obj, bad, good in ((uid, 1000, 0), (marker, False, True),
                    (release, {'ID': 'debian', 'VERSION_ID': '12'}, {'ID': 'ubuntu', 'VERSION_ID': '24.04'}),
                    (machine, 'aarch64', 'x86_64')):
                launch.reset_mock(); obj.return_value = bad
                with self.assertRaises(ValueError): ci.browser_setup_preflight(self.selection())
                launch.assert_not_called(); obj.return_value = good
            for variable in ('FOUNDATION_DISPOSABLE_CHECK', 'CHECK_IMAGE'):
                with patch.dict(ci.os.environ, {variable: ''}):
                    launch.reset_mock()
                    with self.assertRaises(ValueError): ci.browser_setup_preflight(self.selection())
                    launch.assert_not_called()
            launch.return_value.stdout = 'arm64\n'
            with self.assertRaisesRegex(ValueError, 'package architecture'): ci.browser_setup_preflight(self.selection())

    def test_host_browser_never_installs_or_rewrites_sources(self):
        record = dict(package='firefox', version='Mozilla Firefox 153.4.0', architecture='amd64',
                      policy='native host', executable='/usr/lib/firefox/firefox', files={'/usr/lib/firefox/firefox':'a'*64})
        with tempfile.TemporaryDirectory() as temporary, patch.object(ci, 'inspect_host_firefox', return_value=record) as inspect, \
                patch.object(ci, 'browser_setup_preflight', side_effect=AssertionError('container mutation')), \
                patch.object(ci.subprocess, 'run', side_effect=AssertionError('unexpected installation')):
            output=Path(temporary)/'receipt'
            receipt=ci.install_browser_prerequisite('linux-x86_64','ubuntu-24.04','hosted-web',output)
            self.assertEqual(receipt['installed'],[record]); self.assertIsNone(receipt['signing_key_fingerprint'])
            inspect.assert_called_once_with(self.selection()); self.assertTrue(output.is_dir())
            inspect.side_effect=ValueError('missing browser')
            with self.assertRaisesRegex(ValueError,'missing browser'):
                ci.install_browser_prerequisite('linux-x86_64','ubuntu-24.04','hosted-web',Path(temporary)/'missing')
            self.assertFalse((Path(temporary)/'missing').exists())

    def test_host_browser_requires_real_native_bytes_version_and_architecture(self):
        from subprocess import CompletedProcess
        with tempfile.TemporaryDirectory() as temporary:
            binary=Path(temporary)/'firefox'; raw=bytearray(64); raw[:6]=b'\x7fELF\x02\x01';raw[18:20]=(62).to_bytes(2,'little');binary.write_bytes(raw)
            selection=dict(self.selection(),executable=str(binary))
            with patch.object(ci.platform,'system',return_value='Linux'), \
                    patch.object(ci.platform,'freedesktop_os_release',create=True,return_value={'ID':'ubuntu','VERSION_ID':'24.04'}), \
                    patch.object(ci,'assert_host'), patch.object(ci.subprocess,'run',return_value=CompletedProcess([],0,'Mozilla Firefox 153.4.0\n')) as run:
                result=ci.inspect_host_firefox(selection)
                self.assertEqual(result['executable'],str(binary.resolve()))
                self.assertEqual(result['files'],{str(binary.resolve()):ci.module('coverage').sha(binary)})
                raw[18:20]=(183).to_bytes(2,'little');binary.write_bytes(raw);run.reset_mock()
                with self.assertRaisesRegex(ValueError,'architecture'):ci.inspect_host_firefox(selection)
                run.assert_not_called()
                binary.write_bytes(b'#!/bin/sh\nunknown wrapper\n')
                with self.assertRaisesRegex(ValueError,'wrapper'):ci.inspect_host_firefox(selection)

    def test_host_chromium_binds_browser_driver_and_rejects_incompatible_inputs(self):
        from subprocess import CompletedProcess
        selected = ci.browser_prerequisite('browser-wasm32', 'chromium', 'wasm')
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve(); browser = root/'chrome'; driver = root/'chromedriver'
            raw = bytearray(64); raw[:6] = b'\x7fELF\x02\x01'; raw[18:20] = (62).to_bytes(2,'little')
            browser.write_bytes(raw); driver.write_bytes(raw)
            selection = dict(selected, executable=str(browser), driver=str(driver))
            versions = {str(browser): 'Google Chrome 154.0.8037.57', str(driver): 'ChromeDriver 154.0.8037.57 (fixture)'}
            def launch(argv, **kwargs): return CompletedProcess(argv,0,versions[argv[0]])
            with patch.object(ci.platform,'system',return_value='Linux'), \
                    patch.object(ci.platform,'freedesktop_os_release',create=True,return_value={'ID':'ubuntu','VERSION_ID':'24.04'}), \
                    patch.object(ci.os,'geteuid',create=True,return_value=1000) as uid, \
                    patch.object(ci,'assert_host'), patch.object(ci.subprocess,'run',side_effect=launch):
                records = ci.inspect_host_chromium(selection)
                self.assertEqual([r['executable'] for r in records], [str(browser),str(driver)])
                self.assertEqual(records[1]['files'], {str(driver): ci.module('coverage').sha(driver)})
                versions[str(driver)] = 'ChromeDriver 153.0.8037.57 (fixture)'
                with self.assertRaisesRegex(ValueError,'major versions differ'): ci.inspect_host_chromium(selection)
                versions[str(driver)] = 'ChromeDriver 154.0.8037.57 (fixture)'
                raw[18:20] = (183).to_bytes(2,'little'); driver.write_bytes(raw)
                with self.assertRaisesRegex(ValueError,'architecture'): ci.inspect_host_chromium(selection)
                driver.write_bytes(b'#!/bin/sh\nunknown wrapper\n')
                with self.assertRaisesRegex(ValueError,'architecture'): ci.inspect_host_chromium(selection)
                raw[18:20] = (62).to_bytes(2,'little'); driver.write_bytes(raw)
                wrapper=root/'google-chrome';wrapper.write_bytes(b'#!/bin/sh\nexec \"$HERE/chrome\" \"$@\"\n')
                selection['executable']=str(wrapper);versions[str(wrapper)]=versions[str(browser)]
                records=ci.inspect_host_chromium(selection)
                self.assertEqual(set(records[0]['files']),{str(wrapper),str(browser)})
                versions[str(wrapper)]='Google Chrome 154.0.8037.58'
                with self.assertRaisesRegex(ValueError,'wrapper and native'):ci.inspect_host_chromium(selection)
                versions[str(wrapper)]=versions[str(browser)];uid.return_value=0
                with self.assertRaisesRegex(ValueError,'unprivileged'):ci.inspect_host_chromium(selection)

    def test_host_chromium_setup_only_inspects_existing_inputs(self):
        records = [dict(package=p,version='Google Chrome 154.0.1.2' if p=='google-chrome' else 'ChromeDriver 154.0.1.2',
                        architecture='amd64',policy='host',executable='/fixture/'+p,files={'/fixture/'+p:'a'*64})
                   for p in ('google-chrome','chromedriver')]
        with tempfile.TemporaryDirectory() as temporary, patch.object(ci,'inspect_host_chromium',return_value=records), \
                patch.object(ci,'browser_setup_preflight',side_effect=AssertionError('no package mutation')), \
                patch.object(ci.subprocess,'run',side_effect=AssertionError('no installation')):
            receipt=ci.install_browser_prerequisite('browser-wasm32','chromium','wasm',Path(temporary)/'receipt')
            self.assertEqual(receipt['installed'],records)
            self.assertEqual(receipt['browser_version'],records[0]['version'])

    def test_lifecycle_receipt_preserves_new_evidence_directory(self):
        helper_spec = importlib.util.spec_from_file_location('ci_lifecycle_fixture', ci.ROOT / '.github/scripts/lifecycle.py')
        helper = importlib.util.module_from_spec(helper_spec); helper_spec.loader.exec_module(helper)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); (root / 'build').mkdir()
            item = dict(id='ubuntu-check', target='linux-x86_64', environment='ubuntu-24.04', backend='hosted-web', scope='archive')
            frozen = dict(id='plan-id', checks=[item])
            events = []
            def install(*args):
                events.append('setup'); args[-1].mkdir(parents=True)
                return {'schema_version': 1, 'installed': []}
            def run_case(*args):
                events.append('check')
                output = args[3]
                self.assertFalse(output.exists())
                self.assertTrue((root / 'build/prerequisites/ubuntu-check/browser.json').is_file())
                return {'status': 'passed'}
            with patch.object(helper, 'ROOT', root), patch.object(helper.os, 'chdir'), \
                 patch.object(helper.evidence, 'load', return_value=frozen), patch.object(helper.evidence, 'validate'), \
                 patch.object(helper.evidence, 'check_inputs'), patch.object(helper.evidence, 'run_execution', side_effect=run_case), \
                 patch.object(helper.ci.platform, 'system', return_value='Linux'), \
                 patch.object(helper.ci, 'install_browser_prerequisite', side_effect=install), \
                 patch.dict(helper.os.environ, {'CHECK': 'ubuntu-check', 'GITHUB_RUN_ID': '123', 'GITHUB_RUN_ATTEMPT': '2'}):
                with self.assertRaisesRegex(ValueError, 'browser prerequisite'):
                    helper.main('check')
                self.assertEqual(events, [])
                helper.main('check-prerequisites')
                self.assertEqual(events, ['setup'])
                helper.main('check')
                self.assertEqual(events, ['setup', 'check'])
            receipt = json.loads((root / 'build/prerequisites/ubuntu-check/browser.json').read_text())
            self.assertEqual((receipt['plan'], receipt['check'], receipt['run_id'], receipt['attempt']), ('plan-id', 'ubuntu-check', '123', 2))


class CandidateFetchTests(unittest.TestCase):
    def setUp(self):
        sys.path.insert(0, str(Path(__file__).parent))
        import test_github_release
        self.fixture = test_github_release.DeliveryTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.fixture.publish()
        self.remote = self.fixture.remote
        self.root = self.fixture.root
        self.inventory = self.fixture.delivery['inventory_sha256']

    def fetch(self, **changes):
        args = dict(repository='example/project', tag='v1', inventory=self.inventory,
                    output=self.root / 'fetched', transport=self.remote)
        args.update(changes)
        return ci.fetch_candidate(**args)

    def direct_plan(self, *, scopes=('archive', 'source', 'recovery'), workflow_context=None):
        c = ci.module('coverage')
        self.fetch(metadata_only=True, planning=True, workflow_context=workflow_context)
        root = self.root / 'fetched'
        policy = {'schema_version': 1, 'profiles': {'fixture': {'description': 'direct asset qualification',
            'targets': {self.fixture.target: ['core']}, 'checks': [dict(target=self.fixture.target,
                backend='core', environment='debian-12', scope=scope) for scope in scopes]}}}
        ci.qualification_plan(root / 'candidate', 'fixture', root / 'check-plan.json', policy, metadata_only=True)
        return c.load(root / 'check-plan.json'), c.load(root / 'candidate-remote.json')

    def direct_fetch(self, plan, frozen, scope, *, directory=None, trusted_context=None):
        import shutil
        candidate = directory or self.root / ('direct-' + scope)
        candidate.mkdir()
        shutil.copyfile(self.fixture.directory / 'release.json', candidate / 'release.json')
        item = next(row for row in ci.module('coverage').executions(plan) if row['scope'] == scope)
        result = ci.fetch_candidate_payloads('example/project', 'v1', self.inventory, candidate,
            self.fixture.delivery, frozen, plan, [item['id']], transport=self.remote, trusted_context=trusted_context)
        return candidate, result

    def workflow_context(self):
        return dict(repository='example/project',run_id=123,attempt=2,source_commit='a'*40,workflow='certify.yml')

    def workflow_environment(self):
        return dict(GITHUB_ACTIONS='true',GITHUB_REPOSITORY='example/project',GITHUB_RUN_ID='123',
                    GITHUB_RUN_ATTEMPT='2',GITHUB_SHA='a'*40,
                    GITHUB_WORKFLOW_REF='example/project/.github/workflows/certify.yml@refs/heads/main')

    def make_public(self):
        from test_github_release import PublicFakeGitHub
        remote=PublicFakeGitHub();remote.__dict__.update(self.remote.__dict__);remote.private=False;self.remote=remote

    def test_authenticated_same_run_public_inputs_need_no_metadata_or_payload_api_calls(self):
        self.make_public();context=self.workflow_context();self.remote.calls.clear()
        with patch.dict(ci.os.environ,self.workflow_environment(),clear=True):
            plan,frozen=self.direct_plan(workflow_context=context)
            self.assertEqual(2,frozen['schema_version']);self.assertFalse(frozen['repository_private'])
            self.assertEqual(7,sum(call[0] not in ('public-download','download') for call in self.remote.calls if call[0] not in ('POST','PATCH','upload')))
            for scope in ('source','recovery','archive'):
                self.remote.calls.clear()
                candidate,receipt=self.direct_fetch(plan,frozen,scope,trusted_context=context)
                self.assertTrue(self.remote.calls)
                self.assertTrue(all(call[0]=='public-download' for call in self.remote.calls))
                self.assertEqual(len(receipt['files']),len(self.remote.calls))
                ci.module('release').verify_selection(candidate,self.fixture.target,'core',scope)

    def test_authenticated_same_run_private_inputs_keep_exact_asset_api_downloads(self):
        context=self.workflow_context()
        with patch.dict(ci.os.environ,self.workflow_environment(),clear=True):
            plan,frozen=self.direct_plan(workflow_context=context);self.remote.calls.clear()
            _,receipt=self.direct_fetch(plan,frozen,'archive',trusted_context=context)
        self.assertTrue(frozen['repository_private'])
        self.assertTrue(all(call[0]=='download' for call in self.remote.calls))
        self.assertEqual(len(receipt['files']),len(self.remote.calls))

    def test_frozen_snapshot_requires_exact_run_attempt_and_plan_pins(self):
        self.make_public();context=self.workflow_context()
        with patch.dict(ci.os.environ,self.workflow_environment(),clear=True):
            plan,frozen=self.direct_plan(workflow_context=context)
            for label,changed,requested in (
                    ('snapshot',dict(frozen,repository_private=True),context),
                    ('attempt',frozen,dict(context,attempt=3)),
                    ('commit',frozen,dict(context,source_commit='b'*40))):
                self.remote.calls.clear()
                with self.subTest(label=label),self.assertRaisesRegex(ValueError,'trusted candidate snapshot'):
                    self.direct_fetch(plan,changed,'archive',directory=self.root/label,trusted_context=requested)
                self.assertFalse(self.remote.calls)
        with patch.dict(ci.os.environ,{},clear=True),self.assertRaisesRegex(ValueError,'trusted candidate snapshot'):
            self.direct_fetch(plan,frozen,'archive',directory=self.root/'outside-run',trusted_context=context)

    def test_retained_schema_two_without_explicit_trust_keeps_remote_boundary_checks(self):
        context=self.workflow_context()
        with patch.dict(ci.os.environ,self.workflow_environment(),clear=True):
            plan,frozen=self.direct_plan(workflow_context=context)
        self.remote.calls.clear()
        self.direct_fetch(plan,frozen,'archive')
        self.assertEqual(7,sum(call[0]!='download' for call in self.remote.calls))

    def test_trusted_public_payload_tampering_is_quarantined_and_final_identity_check_remains(self):
        self.make_public();context=self.workflow_context()
        with patch.dict(ci.os.environ,self.workflow_environment(),clear=True):
            plan,frozen=self.direct_plan(workflow_context=context)
            entry=ci.module('release').verify_metadata(self.fixture.directory)['artifacts'][0]
            row=frozen['assets'][entry['archive']];original=self.remote.data[row['id']]
            self.remote.data[row['id']]=b'corrupt'
            with self.assertRaisesRegex(ValueError,'downloaded asset bytes differ'):
                self.direct_fetch(plan,frozen,'archive',trusted_context=context)
            self.assertEqual(['release.json'],[p.name for p in (self.root/'direct-archive').iterdir()])
            self.remote.data[row['id']]=original
            self.remote.replace_asset(entry['archive'])
            self.direct_fetch(plan,frozen,'archive',directory=self.root/'same-bytes',trusted_context=context)
            remote=ci.module('github_release').Remote('example/project',self.remote)
            with self.assertRaisesRegex(ValueError,'asset identities changed'):
                remote.unchanged('v1',frozen['release'],frozen['assets'],self.fixture.delivery['tag_commit'])

    def test_direct_plan_downloads_only_source_and_controls_and_freezes_every_payload_digest(self):
        self.remote.calls.clear(); plan, frozen = self.direct_plan()
        ids = {row['id']: row['name'] for row in self.remote.releases[0]['assets']}
        transferred = [ids[call[1]] for call in self.remote.calls if call[0] == 'download']
        metadata = ci.module('release').verify_metadata(self.fixture.directory)
        self.assertEqual(set(transferred), {'delivery.json', 'release.json', metadata['source']['archive']})
        self.assertEqual(sum(name == metadata['source']['archive'] for name in transferred), 1)
        self.assertEqual(set(frozen['assets']), set(ids.values()))
        self.assertIn('build/delivery.json', plan['inputs'])
        self.assertIn('build/candidate-remote.json', plan['inputs'])
        self.assertEqual({name.removeprefix('build/candidate/'): digest for name, digest in plan['inputs'].items()
            if name.startswith('build/candidate/') and name != 'build/candidate/release.json'}, metadata['files'])
        self.assertFalse(self.remote.mutations)

    def test_direct_scope_downloads_only_consumed_original_assets_with_bounded_shared_reads(self):
        plan, frozen = self.direct_plan(); release = ci.module('release')
        metadata = release.verify_metadata(self.fixture.directory)
        for scope in ('archive', 'source', 'recovery'):
            self.remote.calls.clear()
            candidate, receipt = self.direct_fetch(plan, frozen, scope)
            check = next(row for row in ci.module('coverage').executions(plan) if row['scope'] == scope)
            binary_source = check.get('sdk_payload') == 'binary'
            names = release.required_files(metadata, self.fixture.target, 'core', scope, binary_source=binary_source)
            self.assertEqual(set(receipt['files']), set(names))
            self.assertEqual(release.verify_selection(candidate, self.fixture.target, 'core', scope), metadata)
            self.assertEqual(sum(call[0] == 'download' for call in self.remote.calls), len(names))
            self.assertEqual(sum(call[0] != 'download' for call in self.remote.calls), 7)
        self.assertFalse(self.remote.mutations)

    def test_direct_snapshot_rejects_unselected_asset_replacement_before_transferring(self):
        plan, frozen = self.direct_plan()
        source_sdk = next(row['name'] for row in self.remote.releases[0]['assets'] if row['name'].endswith('-sources.tar.gz'))
        self.remote.replace_asset(source_sdk); self.remote.calls.clear()
        with self.assertRaisesRegex(ValueError, 'identities changed'):
            self.direct_fetch(plan, frozen, 'archive')
        self.assertFalse(any(call[0] == 'download' for call in self.remote.calls))
        self.assertEqual([p.name for p in (self.root / 'direct-archive').iterdir()], ['release.json'])

    def test_direct_download_mutation_and_corruption_publish_no_payload(self):
        plan, frozen = self.direct_plan()
        self.remote.change_download = lambda: self.remote.replace_asset('delivery.json')
        with self.assertRaisesRegex(ValueError, 'identities changed'):
            self.direct_fetch(plan, frozen, 'archive')
        self.assertEqual([p.name for p in (self.root / 'direct-archive').iterdir()], ['release.json'])
        # Restore the remote snapshot, then change bytes without changing its advertised digest.
        self.remote.releases[0]['assets'] = list(copy.deepcopy(frozen['assets']).values())
        entry = ci.module('release').verify_metadata(self.fixture.directory)['artifacts'][0]
        row = frozen['assets'][entry['archive']]; self.remote.data[row['id']] = b'corrupt'
        with self.assertRaisesRegex(ValueError, 'downloaded asset bytes differ'):
            self.direct_fetch(plan, frozen, 'archive', directory=self.root / 'corrupt-archive')
        self.assertEqual([p.name for p in (self.root / 'corrupt-archive').iterdir()], ['release.json'])

    def test_direct_download_collision_and_parent_link_never_replace_foreign_outputs(self):
        plan, frozen = self.direct_plan(); metadata = ci.module('release').verify_metadata(self.fixture.directory)
        candidate = self.root / 'direct-archive'; archive = metadata['artifacts'][0]['archive']
        self.remote.change_download = lambda: (candidate / archive).write_bytes(b'foreign writer')
        with self.assertRaisesRegex(ValueError, 'existing file'):
            self.direct_fetch(plan, frozen, 'archive')
        self.assertEqual((candidate / archive).read_bytes(), b'foreign writer')
        self.assertEqual({p.name for p in candidate.iterdir()}, {'release.json',archive})
        outside = self.root / 'foreign-output'; outside.mkdir(); linked = self.root / 'direct-source'
        def link_parent():
            (linked / 'dependencies').symlink_to(outside, target_is_directory=True)
        self.remote.change_download = link_parent
        with self.assertRaisesRegex(ValueError, 'ordinary directories'):
            self.direct_fetch(plan, frozen, 'source')
        self.assertEqual(list(outside.iterdir()), [])
        self.assertEqual({p.name for p in linked.iterdir()}, {'release.json','dependencies'})

    def test_direct_inputs_reject_omitted_scope_inventory_and_foreign_snapshot(self):
        plan, frozen = self.direct_plan()
        broken = copy.deepcopy(plan); broken.pop('id')
        broken['inputs'].pop(next(name for name in broken['inputs'] if name.endswith('-sources.tar.gz')))
        with self.assertRaisesRegex(ValueError, 'inventory is incomplete'):
            self.direct_fetch(ci.module('coverage').freeze(broken), frozen, 'archive')
        frozen = dict(frozen, repository='other/project')
        with self.assertRaisesRegex(ValueError, 'differ from frozen candidate'):
            self.direct_fetch(plan, frozen, 'source')

    def test_fetch_reconstructs_complete_tree_and_never_mutates_remote(self):
        count = len(self.remote.mutations)
        result = self.fetch()
        self.assertEqual(result, self.fixture.delivery)
        self.assertEqual(ci.module('release').verify_release(self.root / 'fetched/candidate'),
                         ci.module('release').verify_release(self.fixture.directory))
        self.assertEqual(len(self.remote.mutations), count)

    def test_metadata_fetch_transfers_no_sdk_or_application_payload_but_checks_every_digest(self):
        self.remote.calls.clear()
        result = self.fetch(metadata_only=True)
        self.assertEqual(result, self.fixture.delivery)
        files = list((self.root / 'fetched/candidate').iterdir())
        self.assertEqual([path.name for path in files], ['release.json'])
        ids = {row['id']: row['name'] for row in self.remote.releases[0]['assets']}
        transferred = [ids[call[1]] for call in self.remote.calls if call[0] == 'download']
        self.assertEqual(set(transferred), {'delivery.json', 'release.json'})
        self.assertFalse(self.remote.mutations)
        sdk = next(row for row in self.remote.releases[0]['assets'] if row['name'].endswith('-binary.tar.gz'))
        sdk['digest'] = 'sha256:' + '0'*64
        with self.assertRaisesRegex(ValueError, 'remote asset differs'):
            self.fetch(metadata_only=True, output=self.root / 'tampered')
        self.assertFalse((self.root / 'tampered').exists())

    def test_complete_fetch_downloads_each_payload_once(self):
        self.remote.calls.clear(); self.fetch()
        counts = {}
        for call in self.remote.calls:
            if call[0] == 'download': counts[call[1]] = counts.get(call[1], 0) + 1
        for row in self.remote.releases[0]['assets']:
            if row['name'] != 'delivery.json': self.assertEqual(counts[row['id']], 1, row['name'])

    def test_retained_builder_capability_is_explicit_and_legacy_groups_remain_complete(self):
        import ast
        import source_identity
        root = self.root / 'builder-source'; (root / 'tools').mkdir(parents=True)
        builder = root / 'tools/build.py'
        builder.write_text("parser.add_argument('--dependency-group')\n")
        legacy = self.root / 'legacy-builder.tar.gz'; source_identity.archive_source(root, legacy)
        self.assertFalse(ci.archived_binary_group_support(self.root, {'source': {'archive': legacy.name}}))
        builder.write_text("parser.add_argument('--binary-dependency-group', action='append')\n")
        modern = self.root / 'modern-builder.tar.gz'; source_identity.archive_source(root, modern)
        self.assertTrue(ci.archived_binary_group_support(self.root, {'source': {'archive': modern.name}}))
        builder.write_text("# --binary-dependency-group\nparser.add_argument('--dependency-group')\n")
        comment = self.root / 'comment-builder.tar.gz'; source_identity.archive_source(root, comment)
        self.assertFalse(ci.archived_binary_group_support(self.root, {'source': {'archive': comment.name}}))
        release = ci.module('release'); metadata = release.verify_release(self.fixture.directory)
        names = release.required_files(metadata, self.fixture.target, 'core', 'source', binary_source=False)
        self.assertTrue(any(name.endswith('-sources.tar.gz') for name in names))

    def test_scope_payload_selection_omits_sdk_sources_except_recovery(self):
        import shutil
        release = ci.module('release'); archive = ci.module('dependency_archive')
        manifest = release.verify_release(self.fixture.directory)
        scope_files = {scope: release.required_files(manifest, self.fixture.target, 'core', scope)
                       for scope in ('archive', 'source', 'recovery')}
        self.assertEqual(set(scope_files['archive']), {manifest['artifacts'][0]['archive'], manifest['artifacts'][0]['manifest']})
        self.assertFalse(any(name.endswith('-sources.tar.gz') for name in scope_files['source']))
        self.assertTrue(any(name.endswith('-sources.tar.gz') for name in scope_files['recovery']))
        for scope, names in scope_files.items():
            destination = self.root / ('sparse-' + scope); destination.mkdir()
            for name in ['release.json', *names]:
                target = destination / name; target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(self.fixture.directory / name, target)
            self.assertEqual(release.verify_selection(destination, self.fixture.target, 'core', scope), manifest)
            required = destination / manifest['artifacts'][0]['archive']; required.unlink()
            with self.assertRaisesRegex(ValueError, 'missing'):
                release.verify_selection(destination, self.fixture.target, 'core', scope)

    def test_transport_projects_each_scope_without_repeating_sources_into_binary_bundle(self):
        import shutil, ci_transport
        c = ci.module('coverage'); release = ci.module('release')
        policy = {'schema_version': 1, 'profiles': {'fixture': {'description': 'transport fixture',
            'targets': {self.fixture.target: ['core']}, 'checks': [dict(target=self.fixture.target,
                backend='core', environment='debian-12', scope=scope) for scope in ('source', 'archive', 'recovery')]}}}
        plan_path = self.root / 'projection-plan.json'
        ci.qualification_plan(self.fixture.directory, 'fixture', plan_path, policy)
        plan = c.load(plan_path); destination = self.root / 'transport-checkout'
        for name in plan['inputs']:
            if name.startswith('build/candidate/'): continue
            target = destination / name; target.parent.mkdir(parents=True, exist_ok=True); shutil.copyfile(ci.ROOT / name, target)
        shutil.copytree(self.fixture.directory, destination / 'build/candidate')
        (destination / 'build/check-plan.json').write_text(json.dumps(plan))
        (destination / 'build/delivery.json').write_text(json.dumps(self.fixture.delivery))
        spec = importlib.util.spec_from_file_location('projected_lifecycle', ci.ROOT / '.github/scripts/lifecycle.py')
        helper = importlib.util.module_from_spec(spec); spec.loader.exec_module(helper)
        payloads = {}
        def publish(**options):
            payloads[options['name']] = {name: (options['root'] / name).read_bytes() for name in options['paths']}
        with patch.object(helper, 'ROOT', destination), patch.object(helper, 'storage_context', return_value={}), \
                patch.dict(helper.os.environ, GITHUB_RUN_ATTEMPT='1', RUNNER_NAME='fixture-runner'), \
                patch.object(ci_transport, 'publish_bundles', side_effect=lambda **options: [publish(**request) for request in options['requests']]):
            helper.qualification_payloads()
        self.assertEqual(len(payloads), 5)  # source, target, SDK pair/sources, complete metadata
        self.assertEqual(set(payloads['qualification-inputs-1']), {'candidate/release.json','delivery.json','check-plan.json'})
        binary = payloads['qualification-sdk-0-1']; sources = payloads['qualification-sdk-source-0-1']
        self.assertEqual(len(binary), 2); self.assertEqual(len(sources), 1)
        self.assertFalse(any(name.endswith('-sources.tar.gz') for name in binary))
        self.assertTrue(all(name.endswith('-sources.tar.gz') for name in sources))
        manifest = release.verify_release(destination / 'build/candidate')
        for scope in ('archive', 'source', 'recovery'):
            for name in manifest['files']: (destination / 'build/candidate' / name).unlink(missing_ok=True)
            for directory in sorted((destination / 'build/candidate').rglob('*'), reverse=True):
                if directory.is_dir(): directory.rmdir()
            batch = next(row for row in ci.qualification_batches(plan)['include'] if
                         next(item for item in c.executions(plan) if item['id'] in row['checks'])['scope'] == scope)
            fetched = []
            def restore(name, output, **options):
                fetched.append(name)
                for relative, content in payloads[name].items():
                    path = Path(output) / relative; path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(content)
            with patch.object(helper, 'ROOT', destination), \
                    patch.dict(helper.os.environ, GITHUB_ACTIONS='true', GITHUB_REPOSITORY='example/project',
                        GITHUB_WORKFLOW_REF='example/project/.github/workflows/certify.yml@refs/heads/main',
                        GITHUB_RUN_ID='12', GITHUB_SHA='a'*40, GITHUB_RUN_ATTEMPT='1',
                        CONTROL_ATTEMPT='1', BATCH=batch['id']), \
                    patch.object(helper, 'fetch_bundles', side_effect=lambda requests: [restore(request['name'], request['output']) for request in requests]):
                helper.fetch_check_payloads()
            actual = {path.relative_to(destination / 'build/candidate').as_posix() for path in (destination / 'build/candidate').rglob('*') if path.is_file()}
            check = next(row for row in c.executions(plan) if row['id'] in batch['checks'])
            binary_source = check.get('sdk_payload') == 'binary'
            expected = {'release.json', *release.required_files(manifest, self.fixture.target, 'core', scope, binary_source=binary_source)}
            self.assertEqual(actual, expected)
            self.assertEqual('qualification-sdk-source-0-1' in fetched,
                             scope == 'recovery' or scope == 'source' and not binary_source)
            self.assertEqual('qualification-sdk-0-1' in fetched, scope != 'archive')

    def test_frozen_batch_payload_list_includes_inputs_and_exact_recovery_closure(self):
        c=ci.module('coverage'); release=ci.module('release')
        policy={'schema_version':1,'profiles':{'fixture':{'description':'frozen input selector',
            'targets':{self.fixture.target:['core']},'checks':[dict(target=self.fixture.target,backend='core',environment='debian-12',scope=scope) for scope in ('source','archive','recovery')]}}}
        path=self.root/'named-plan.json';ci.qualification_plan(self.fixture.directory,'fixture',path,policy)
        plan=c.load(path);manifest=release.verify_metadata(self.fixture.directory)
        plain=ci.qualification_batches(plan)['include']
        frozen=ci.qualification_batches(plan,manifest=manifest,attempt='2')['include']
        self.assertEqual([row['id'] for row in plain],[row['id'] for row in frozen])
        for batch in frozen:
            check=next(row for row in c.executions(plan) if row['id']==batch['checks'][0])
            scope=check['scope']
            self.assertEqual(batch['payloads'][0],'qualification-inputs-2')
            self.assertEqual(any(name.startswith('qualification-sdk-source-') for name in batch['payloads']),
                             scope=='recovery' or scope=='source' and check.get('sdk_payload')!='binary')
            self.assertEqual(any(name.startswith('qualification-sdk-0-') for name in batch['payloads']),scope!='archive')
        altered=copy.deepcopy(manifest);altered['dependencies']=[]
        recovery=next(batch for batch in plain if next(row['scope'] for row in c.executions(plan) if row['id']==batch['checks'][0])=='recovery')
        with self.assertRaisesRegex(ValueError,'closure is incomplete'):
            ci.qualification_payload_names(plan,recovery,altered,'2')

    def test_sparse_execution_inputs_reject_omitted_inventory_and_changed_selected_bytes(self):
        import shutil
        c = ci.module('coverage'); release = ci.module('release')
        policy = {'schema_version': 1, 'profiles': {'fixture': {'description': 'scope fixture',
            'targets': {self.fixture.target: ['core']},
            'checks': [dict(target=self.fixture.target, backend='core', environment='debian-12', scope=scope) for scope in ('source', 'archive', 'recovery')]}}}
        frozen_path = self.root / 'scope-plan.json'
        ci.qualification_plan(self.fixture.directory, 'fixture', frozen_path, policy)
        plan = c.load(frozen_path); item = next(row for row in c.executions(plan) if row['scope'] == 'archive')
        destination = self.root / 'scoped-checkout'
        for name in plan['inputs']:
            if name.startswith('build/candidate/'): continue
            target = destination / name; target.parent.mkdir(parents=True, exist_ok=True); shutil.copyfile(ci.ROOT / name, target)
        manifest = release.verify_release(self.fixture.directory)
        for name in ['release.json', *release.required_files(manifest, item['target'], item['backend'], item['scope'])]:
            target = destination / 'build/candidate' / name; target.parent.mkdir(parents=True, exist_ok=True); shutil.copyfile(self.fixture.directory / name, target)
        c.check_inputs(plan, destination, check_ids=[item['id']])
        c.check_inputs(plan, destination, metadata_only=True)
        broken = copy.deepcopy(plan); broken.pop('id'); omitted = next(name for name in broken['inputs'] if name.endswith('-sources.tar.gz')); broken['inputs'].pop(omitted)
        with self.assertRaisesRegex(ValueError, 'inventory differs'):
            c.check_inputs(c.freeze(broken), destination, check_ids=[item['id']])
        with self.assertRaisesRegex(ValueError, 'unknown'):
            c.check_inputs(plan, destination, check_ids=['absent'])
        (destination / 'build/candidate' / manifest['artifacts'][0]['archive']).write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError, 'check input changed'):
            c.check_inputs(plan, destination, check_ids=[item['id']])

    def test_wrong_inventory_does_not_publish_local_destination(self):
        with self.assertRaisesRegex(ValueError, 'identity'): self.fetch(inventory='b' * 64)
        self.assertFalse((self.root / 'fetched').exists())

    def test_changed_asset_during_fetch_is_rejected(self):
        self.remote.change_download = lambda: self.remote.replace_asset('delivery.json')
        with self.assertRaisesRegex(ValueError, 'identities changed'): self.fetch()
        self.assertFalse((self.root / 'fetched').exists())

    def test_untrusted_descriptor_cannot_write_outside_destination(self):
        altered = copy.deepcopy(self.fixture.delivery)
        altered['files']['../escape'] = altered['files'].pop('release.json')
        self.remote.replace_asset('delivery.json', ci.module('github_release').archive.encoded(altered))
        with self.assertRaises(ValueError): self.fetch()
        self.assertFalse((self.root / 'escape').exists())


    def test_prepared_producer_uses_one_build_and_retains_matching_inventory(self):
        import shutil
        from unittest.mock import Mock
        original = ci.module
        sdk = Mock()
        artifacts = original('artifact')
        fake_artifact = Mock(describe=artifacts.describe)
        def selected(name):
            if name == 'sdk': return sdk
            if name == 'artifact': return fake_artifact
            return original(name)
        produced = self.root / 'produced'
        archive = self.fixture.directory / ci.module('release').verify_release(self.fixture.directory)['artifacts'][0]['archive']
        commands = []
        def launch(argv, **kwargs):
            commands.append(argv)
            if argv[2] == 'package':
                destination = produced / 'work/build/packages'
                destination.mkdir(parents=True)
                shutil.copyfile(archive, destination / 'application.tar.gz')
        with patch.object(ci, 'module', side_effect=selected), patch.object(ci, 'assert_host'), patch.object(ci.subprocess, 'run', side_effect=launch):
            entry = ci.prepared_package('linux-x86_64', self.fixture.fixture.recipe, self.fixture.root / 'group',
                    self.fixture.directory / ci.module('release').verify_release(self.fixture.directory)['source']['archive'], produced, 2, core_provider='cpp')
        self.assertEqual([x[2] for x in commands], ['test', 'package'])
        self.assertIn('--full', commands[0]); self.assertNotIn('--full', commands[1])
        self.assertNotIn('--junit', commands[1])
        self.assertEqual(entry['path'], 'linux-x86_64.tar.gz')
        self.assertEqual(entry['manifest_path'], 'linux-x86_64.tar.gz.json')
        self.assertEqual(entry['sdk_recipe'], self.fixture.fixture.recipe)
        self.assertEqual(entry['dependency_recipes'], [self.fixture.fixture.recipe])
        self.assertTrue((produced / 'artifact.json').is_file())
        sdk.install.assert_called_once()
        fake_artifact.verify.assert_called_once()

    def test_binary_only_prepared_producer_binds_complete_triplet_without_supplier_sources(self):
        import shutil
        from unittest.mock import Mock
        original = ci.module
        sdk = Mock()
        artifacts = original('artifact')
        fake_artifact = Mock(describe=artifacts.describe)
        def selected(name):
            if name == 'sdk': return sdk
            if name == 'artifact': return fake_artifact
            return original(name)
        produced = self.root / 'produced'
        store=ci.module('dependency_store'); recipe=self.fixture.fixture.recipe
        complete=store.verify_group(self.fixture.root/'group',recipe)
        binary_group=self.root/'binary-group';binary_group.mkdir()
        for name in store.names(recipe):
            if not name.endswith('-sources.tar.gz'):shutil.copyfile(self.fixture.root/'group'/name,binary_group/name)
        archive = self.fixture.directory / ci.module('release').verify_release(self.fixture.directory)['artifacts'][0]['archive']
        commands = []
        def launch(argv, **kwargs):
            commands.append(argv)
            if argv[2] == 'package':
                destination = produced / 'work/build/packages'
                destination.mkdir(parents=True)
                shutil.copyfile(archive, destination / 'application.tar.gz')
        with patch.object(ci, 'module', side_effect=selected), patch.object(ci, 'assert_host'), patch.object(ci.subprocess, 'run', side_effect=launch):
            entry = ci.prepared_package('linux-x86_64', self.fixture.fixture.recipe, binary_group,
                    self.fixture.directory / ci.module('release').verify_release(self.fixture.directory)['source']['archive'], produced, 2, expected_files=complete, core_provider='cpp')
        self.assertEqual([x[2] for x in commands], ['test', 'package'])
        self.assertIn('--full', commands[0]); self.assertNotIn('--full', commands[1])
        self.assertNotIn('--junit', commands[1])
        self.assertEqual(entry['path'], 'linux-x86_64.tar.gz')
        self.assertEqual(entry['manifest_path'], 'linux-x86_64.tar.gz.json')
        self.assertEqual(entry['sdk_recipe'], self.fixture.fixture.recipe)
        self.assertEqual(entry['dependency_recipes'], [self.fixture.fixture.recipe])
        self.assertTrue((produced / 'artifact.json').is_file())
        sdk.install.assert_called_once_with(binary_group,recipe,produced/'work/sdk',production=True,expected_files=complete)
        fake_artifact.verify.assert_called_once()

    def test_policy_derived_plan_binds_inputs_and_every_required_scope(self):
        target = self.fixture.target
        rows = [dict(target=target, backend='core', environment='fixture', scope=scope) for scope in ('source', 'archive', 'recovery')]
        policy = {'schema_version': 1, 'profiles': {'fixture': {'description': 'fixture inventory', 'targets': {target: ['core']}, 'checks': rows}}}
        output = self.root / 'check-plan.json'
        matrix = ci.qualification_plan(self.fixture.directory, 'fixture', output, policy)
        plan = json.loads(output.read_text())
        self.assertEqual(len(matrix['include']), 3)
        self.assertEqual({x['scope'] for x in plan['checks']}, {'source', 'archive', 'recovery'})
        self.assertTrue(all(x['required'] and x['qualification'] == 'qualification.json' for x in plan['checks']))
        self.assertEqual(plan['subject']['inventory_sha256'], self.inventory)
        self.assertIn('tools/release_check.py', plan['inputs'])
        self.assertIn('build/candidate/release.json', plan['inputs'])

    def test_ubuntu_check_uses_explicit_real_firefox_and_binds_setup_inputs(self):
        from unittest.mock import Mock
        target = 'linux-x86_64'
        policy = {'schema_version': 1, 'profiles': {'fixture': {'description': 'fixture browser',
                  'targets': {target: ['hosted-web']}, 'checks': [dict(target=target, backend='hosted-web',
                  environment='ubuntu-24.04', scope=scope) for scope in ('source', 'archive', 'recovery')]}}}
        original = ci.module
        release = Mock(verify_release=Mock(return_value=dict(original('release').verify_release(self.fixture.directory))))
        release.dependency_recipes = original('release').dependency_recipes
        release.verify_release.return_value['artifacts'][0]['target'] = target
        release.verify_release.return_value['artifacts'][0]['backends'] = ['hosted-web']
        with patch.object(ci, 'module', side_effect=lambda name: release if name == 'release' else original(name)):
            output = self.root / 'browser-plan.json'
            matrix = ci.qualification_plan(self.fixture.directory, 'fixture', output, policy)
        frozen = json.loads(output.read_text())
        self.assertEqual(matrix['include'][0]['image'], 'ubuntu:24.04')
        self.assertEqual(next(x for x in matrix['include'] if x['scope']=='archive')['image'], '')
        archive = next(item for item in frozen['checks'] if item['scope'] == 'archive')
        self.assertIn('/usr/bin/firefox', archive['argv'])
        self.assertIn('--browser-prerequisite-plan', archive['argv'])
        self.assertIn('{root}/build/check-plan.json', archive['argv'])
        self.assertIn('.github/scripts/lifecycle.py', frozen['inputs'])
        self.assertIn('.github/workflows/certify.yml', frozen['inputs'])
        for case in frozen['checks']:
            self.assertEqual('--browser-prerequisite' in case['argv'], case['scope'] == 'archive')


    def test_all_gui_groups_preserve_106_requirements_with_66_executions(self):
        from unittest.mock import Mock
        original=ci.module;manifest=original('release').verify_release(self.fixture.directory)
        policy=json.loads((ci.ROOT/'docs/release-policy.json').read_text())
        manifest['artifacts']=[dict(manifest['artifacts'][0],target=target,backends=backends) for target,backends in policy['profiles']['all-gui']['targets'].items()]
        release=Mock(verify_release=Mock(return_value=manifest))
        release.dependency_recipes = original('release').dependency_recipes
        with patch.object(ci,'module',side_effect=lambda name:release if name=='release' else original(name)):
            output=self.root/'all-gui-plan.json';matrix=ci.qualification_plan(self.fixture.directory,'all-gui',output,policy)
        frozen=json.loads(output.read_text());self.assertEqual(len(frozen['checks']),106);self.assertEqual(len(matrix['include']),66)
        batches = ci.qualification_batches(frozen)['include']
        self.assertEqual(len(batches), 23)
        self.assertEqual(sorted(check for batch in batches for check in batch['checks']),
                         sorted(row['id'] for row in matrix['include']))
        self.assertTrue(all(len({by['scope'] for by in original('coverage').executions(frozen) if by['id'] in batch['checks']}) == 1 for batch in batches))
        self.assertTrue(all(len(batch['checks']) <= 16 for batch in batches))
        self.assertEqual(sum(batch['browser'] for batch in batches), 10)
        self.assertEqual(sum(batch['graphics'] for batch in batches), 3)
        by_id = {row['id']: row for row in matrix['include']}
        for batch in batches:
            for check in batch['checks']:
                self.assertEqual(tuple(batch[key] for key in ('runner', 'image', 'target', 'environment')),
                                 tuple(by_id[check][key] for key in ('runner', 'image', 'target', 'environment')))
        for target in ('linux-x86_64', 'linux-aarch64'):
            ubuntu = [batch for batch in batches if batch['target'] == target and batch['environment'] == 'ubuntu-24.04']
            self.assertEqual({batch['image'] for batch in ubuntu}, {'', 'ubuntu:24.04'})
            self.assertEqual(next(batch for batch in ubuntu if not batch['image'])['checks'],
                             [target + '-hosted-web-ubuntu-24.04-archive'])
        windows = [batch for batch in batches if batch['target'] == 'windows-x86_64']
        self.assertEqual(len(windows), 3)
        self.assertTrue(all(batch['graphics'] and not batch['browser'] for batch in windows))
        changed = copy.deepcopy(frozen); changed['checks'][0]['environment'] = 'debian-13'
        with self.assertRaises(ValueError): ci.qualification_batches(changed)
        chromium = next(row for row in matrix['include'] if row['id']=='browser-wasm32-wasm-chromium-archive')
        self.assertEqual(chromium['image'], '')
        command = next(row['argv'] for row in frozen['checks'] if row['id']==chromium['id'])
        self.assertIn('/usr/bin/google-chrome', command); self.assertIn('/usr/bin/chromedriver', command)
        grouped=[x for x in frozen['checks'] if 'execution' in x]
        self.assertEqual(len(grouped),48)
        self.assertTrue(all(x['scope'] in ('source','recovery','abi') for x in grouped))
        self.assertEqual(len({x['execution'] for x in grouped}),8)
        for leader in original('coverage').executions(frozen):
            if 'execution' in leader:
                rows=original('coverage').execution_members(frozen,leader)
                self.assertEqual({x['backend'] for x in rows},set(policy['profiles']['all-gui']['targets'][leader['target']]))

    def test_every_supported_profile_batch_name_passes_real_transport_context(self):
        from unittest.mock import Mock
        original = ci.module; policy = json.loads((ci.ROOT / 'docs/release-policy.json').read_text())
        source = original('release').verify_release(self.fixture.directory)
        transport = original('ci_transport')
        for profile in ('core', 'all-gui'):
            with self.subTest(profile=profile):
                manifest = copy.deepcopy(source)
                manifest['artifacts'] = [dict(source['artifacts'][0], target=target, backends=backends)
                    for target, backends in policy['profiles'][profile]['targets'].items()]
                release = Mock(verify_release=Mock(return_value=manifest))
                release.dependency_recipes = original('release').dependency_recipes
                output = self.root / (profile + '-bundle-names.json')
                with patch.object(ci, 'module', side_effect=lambda name: release if name == 'release' else original(name)):
                    matrix = ci.qualification_plan(self.fixture.directory, profile, output, policy)
                frozen = json.loads(output.read_text()); before = copy.deepcopy(frozen)
                batches = ci.qualification_batches(frozen)['include']
                self.assertEqual(frozen, before)
                self.assertEqual(sorted(check for batch in batches for check in batch['checks']),
                                 sorted(row['id'] for row in matrix['include']))
                self.assertEqual(len({batch['id'] for batch in batches}), len(batches))
                for batch in batches:
                    for prefix in ('evidence-', 'browser-prerequisite-'):
                        for attempt in (1, 2**63 - 1):
                            name = prefix + batch['id'] + '-' + str(attempt)
                            context = transport._context('example/project', 123, attempt, 'a'*40, 'certify.yml', name)
                            self.assertEqual(context['name'], name)

    def test_windows_gui_plan_freezes_graphics_inputs_and_passes_explicit_archive(self):
        from unittest.mock import Mock
        target = 'windows-x86_64'
        policy = {'schema_version': 1, 'profiles': {'fixture': {'description': 'fixture graphics',
                  'targets': {target: ['rev']}, 'checks': [dict(target=target, backend='rev',
                  environment='windows-2022', scope=scope) for scope in ('source', 'archive', 'recovery')]}}}
        original = ci.module
        release = Mock(verify_release=Mock(return_value=dict(original('release').verify_release(self.fixture.directory))))
        release.dependency_recipes = original('release').dependency_recipes
        release.verify_release.return_value['artifacts'][0].update(target=target, backends=['rev'])
        with patch.object(ci, 'module', side_effect=lambda name: release if name == 'release' else original(name)):
            output = self.root / 'graphics-plan.json'
            matrix = ci.qualification_plan(self.fixture.directory, 'fixture', output, policy)
        frozen = json.loads(output.read_text())
        self.assertTrue(all(item['graphics'] for item in matrix['include']))
        for item in frozen['checks']:
            self.assertIn('--windows-graphics-archive', item['argv'])
            self.assertNotIn('--browser-prerequisite', item['argv'])
        self.assertIn('tools/windows_gl_probe.cpp', frozen['inputs'])
        self.assertIn('third_party/host-graphics/mesa-windows.json', frozen['inputs'])
        self.assertTrue(all(item.get('sdk_payload') == 'complete' for item in frozen['checks'] if item['scope'] == 'source'))
        with patch.object(ci, 'module', side_effect=lambda name: release if name == 'release' else original(name)), \
                patch.object(ci, 'archived_binary_group_support', return_value=True):
            ci.qualification_plan(self.fixture.directory, 'fixture', self.root / 'modern-graphics-plan.json', policy)
        modern = json.loads((self.root / 'modern-graphics-plan.json').read_text())
        self.assertTrue(all(item.get('sdk_payload') == 'binary' for item in modern['checks'] if item['scope'] == 'source'))



class PortableQualificationPlanTests(unittest.TestCase):
    def setUp(self):
        import shutil
        sys.path.insert(0, str(Path(__file__).parent))
        import test_github_release
        self.fixture = test_github_release.DeliveryTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.root = self.fixture.root / 'portable-workspace'
        shutil.copytree(ci.ROOT / 'tools', self.root / 'tools',
                        ignore=shutil.ignore_patterns('__pycache__'))
        (self.root / 'docs').mkdir()
        shutil.copyfile(ci.ROOT / 'docs/release-policy.json', self.root / 'docs/release-policy.json')
        shutil.copytree(self.fixture.directory, self.root / 'build/candidate')
        self.candidate = self.root / 'build/candidate'
        self.output = self.root / 'build/check-plan.json'
        self.planner = ci.module('qualification_plan')
        self.coverage = ci.module('coverage')
        self.policy = {'schema_version': 1, 'profiles': {'fixture': {
            'description': 'portable local qualification', 'targets': {self.fixture.target: ['core']},
            'checks': [dict(target=self.fixture.target, backend='core', environment='fixture', scope=scope)
                       for scope in ('source', 'archive', 'recovery')]}}}

    def create(self, **changes):
        options = dict(root=self.root, candidate=self.candidate, profile='fixture',
                       output=self.output, policy=self.policy)
        options.update(changes)
        return self.planner.create_plan(**options)

    def test_local_plan_needs_no_provider_tree_environment_or_requests(self):
        import os
        with patch.dict(os.environ, {}, clear=True), patch('subprocess.run') as run, \
                patch('urllib.request.build_opener') as request:
            plan = self.create()
        run.assert_not_called(); request.assert_not_called()
        self.assertFalse((self.root / '.github').exists())
        self.assertEqual(plan, self.coverage.load(self.output))
        self.assertFalse(any(name.startswith('.github/') for name in plan['inputs']))
        self.assertNotIn('build/delivery.json', plan['inputs'])
        self.assertNotIn('build/candidate-remote.json', plan['inputs'])
        self.assertTrue(all('runner' not in item and 'image' not in item for item in plan['checks']))
        self.coverage.check_inputs(plan, self.root)
        hosted_output = self.fixture.root / 'hosted-plan.json'
        matrix = ci.qualification_plan(self.fixture.directory, 'fixture', hosted_output, self.policy)
        hosted = self.coverage.load(hosted_output)
        self.assertEqual(plan['checks'], hosted['checks'])
        self.assertEqual(plan['subject'], hosted['subject'])
        self.assertEqual({item['id'] for item in self.coverage.executions(plan)},
                         {item['id'] for item in matrix['include']})
        self.assertEqual(set(hosted['inputs']) - set(plan['inputs']),
                         {'.github/scripts/lifecycle.py', '.github/scripts/container_job.py',
                          '.github/workflows/certify.yml'})

    def test_metadata_only_plan_needs_retained_source_but_no_delivery_descriptors(self):
        manifest = ci.module('release').verify_release(self.candidate)
        source_name = manifest['source']['archive']
        for name in manifest['files']:
            if name != source_name:
                (self.candidate / name).unlink()
        plan = self.create(metadata_only=True)
        self.coverage.check_inputs(plan, self.root, metadata_only=True)
        self.assertEqual(plan['inputs']['build/candidate/' + source_name], manifest['source']['sha256'])
        self.assertNotIn('build/candidate-remote.json', plan['inputs'])
        self.output.unlink()
        (self.candidate / source_name).write_bytes(b'changed retained source')
        with self.assertRaisesRegex(ValueError, 'retained source'):
            self.create(metadata_only=True)
        self.assertFalse(self.output.exists())

    def test_optional_provider_inputs_are_frozen_and_tampering_is_rejected(self):
        name = 'provider/receipt.json'; receipt = self.root / name
        receipt.parent.mkdir(); receipt.write_text('{"provider":"fixture","attempt":1}')
        plan = self.create(additional_inputs={name: receipt})
        self.coverage.check_inputs(plan, self.root)
        receipt.write_text('{"provider":"fixture","attempt":2}')
        with self.assertRaisesRegex(ValueError, 'check input changed: provider/receipt.json'):
            self.coverage.check_inputs(plan, self.root)

    def test_provider_inputs_cannot_replace_core_inputs_or_escape_workspace(self):
        receipt = self.root / 'external.json'; receipt.write_text('{}')
        for extra in ({'tools/release_check.py': receipt}, {'build/candidate/extra.json': receipt},
                      {'../receipt.json': receipt}, [('provider.json', receipt), ('provider.json', receipt)]):
            with self.subTest(extra=extra), self.assertRaises(ValueError):
                self.create(additional_inputs=extra)
            self.assertFalse(self.output.exists())

    def test_hosted_invalid_runner_selection_does_not_publish_plan(self):
        with self.assertRaisesRegex(ValueError, 'runner selection'):
            ci.qualification_plan(self.fixture.directory, 'fixture', self.output, self.policy, runners={})
        self.assertFalse(self.output.exists())

    def test_new_plan_cannot_overwrite_an_existing_attempt(self):
        expected = self.create(); before = self.output.read_bytes()
        with self.assertRaises(FileExistsError):
            self.create()
        self.assertEqual(self.output.read_bytes(), before)
        self.assertEqual(self.coverage.load(self.output), expected)


class QualificationBatchTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        spec = importlib.util.spec_from_file_location('batch_lifecycle', ci.ROOT / '.github/scripts/lifecycle.py')
        self.helper = importlib.util.module_from_spec(spec); spec.loader.exec_module(self.helper)

    def plan(self, backends=('terminal', 'fltk', 'sdl'), target='linux-x86_64', environment='debian-12'):
        c = ci.module('coverage')
        checks = [dict(id='case-' + str(index), target=target, environment=environment, backend=backend,
                       scope='archive', required=True, argv=['python', 'check'], timeout_seconds=5400,
                       warning_seconds=4500, expected_tests=[]) for index, backend in enumerate(backends)]
        plan = c.freeze(dict(schema_version=1, mode='release', subject=dict(source_sha256='a'*64,
                            inventory_sha256='b'*64, configuration_sha256='c'*64), inputs={}, checks=checks))
        (self.root / 'build').mkdir(exist_ok=True)
        (self.root / 'build/check-plan.json').write_text(json.dumps(plan))
        return plan

    def test_failed_case_continues_later_fresh_container_and_fails_batch(self):
        import subprocess
        plan = self.plan(); batch = ci.qualification_batches(plan)['include'][0]; seen = []
        def run(command, **options):
            seen.append((command, options))
            if options['env']['CHECK'] == 'case-1': raise subprocess.CalledProcessError(1, command)
        with patch.object(self.helper, 'ROOT', self.root), patch.object(self.helper.ci.platform, 'system', return_value='Linux'), \
                patch.dict(self.helper.os.environ, BATCH=batch['id'], CHECK_IMAGE=batch['image']), \
                patch.object(self.helper.build_capacity, 'test_jobs', return_value=1), \
                patch.object(self.helper.subprocess, 'run', side_effect=run), \
                patch.object(self.helper, 'container_bootstrap', return_value=nullcontext('sha256:' + 'd'*64)) as bootstrap:
            with self.assertRaisesRegex(ValueError, 'required batch executions failed: case-1'):
                self.helper.check_batch()
        self.assertEqual([options['env']['CHECK'] for command, options in seen], ['case-0', 'case-1', 'case-2'])
        self.assertTrue(all(command[-4:] == [str(self.root / '.github/scripts/container_job.py'), 'check', '--prepared-image', 'sha256:' + 'd'*64] for command, options in seen))
        bootstrap.assert_called_once()
        self.assertTrue(all(options['cwd'] == self.root and options['check'] for command, options in seen))
        self.assertFalse((self.root / 'build/evidence').exists())  # No fabricated success or empty output root.

    def test_container_cases_overlap_keep_complete_failures_and_join_before_image_cleanup(self):
        import threading
        from contextlib import contextmanager
        plan = self.plan(); batch = ci.qualification_batches(plan)['include'][0]
        barrier = threading.Barrier(3); completed = []; cleanup = []; environments = []
        lock = threading.Lock()
        def run(command, **options):
            identity = options['env']['CHECK']
            with lock: environments.append(options['env'])
            barrier.wait(timeout=5)
            with lock: completed.append(identity)
            if identity != 'case-0': raise subprocess.CalledProcessError(1, command)
        @contextmanager
        def bootstrap(*args):
            try: yield 'sha256:' + 'd'*64
            finally: cleanup.append(set(completed))
        with patch.object(self.helper, 'ROOT', self.root), \
                patch.object(self.helper.ci.platform, 'system', return_value='Linux'), \
                patch.dict(self.helper.os.environ, BATCH=batch['id'], CHECK_IMAGE=batch['image'],
                           FOUNDATION_CHECK_JOBS='3', FOUNDATION_WORKER_BUDGET='6',
                           CMAKE_BUILD_PARALLEL_LEVEL='6', CTEST_PARALLEL_LEVEL='6'), \
                patch.object(self.helper.build_capacity, 'default_jobs', return_value=6), \
                patch.object(self.helper.subprocess, 'run', side_effect=run), \
                patch.object(self.helper, 'container_bootstrap', side_effect=bootstrap):
            with self.assertRaisesRegex(ValueError, 'required batch executions failed: case-1, case-2'):
                self.helper.check_batch()
            self.assertEqual(self.helper.os.environ['FOUNDATION_WORKER_BUDGET'], '6')
        self.assertEqual(cleanup, [{'case-0', 'case-1', 'case-2'}])
        self.assertEqual({row['CHECK'] for row in environments}, {'case-0', 'case-1', 'case-2'})
        self.assertTrue(all(row['FOUNDATION_WORKER_BUDGET'] == '2' and
                            row['CMAKE_BUILD_PARALLEL_LEVEL'] == '2' and
                            row['CTEST_PARALLEL_LEVEL'] == '2' for row in environments))

    def test_private_case_pool_respects_worker_limit_and_rechecks_frozen_inputs(self):
        import threading
        plan = self.plan(tuple('backend-' + str(index) for index in range(5)))
        batch = ci.qualification_batches(plan)['include'][0]
        barrier = threading.Barrier(2); lock = threading.Lock(); running = [0]; peak = [0]; completed = []
        def run(command, **options):
            identity = options['env']['CHECK']
            with lock:
                running[0] += 1; peak[0] = max(peak[0], running[0])
            if identity in ('case-0', 'case-1'): barrier.wait(timeout=5)
            with lock:
                completed.append(identity); running[0] -= 1
        with patch.object(self.helper, 'ROOT', self.root), \
                patch.object(self.helper.ci.platform, 'system', return_value='Linux'), \
                patch.dict(self.helper.os.environ, BATCH=batch['id'], CHECK_IMAGE=batch['image'], FOUNDATION_CHECK_JOBS='2'), \
                patch.object(self.helper.subprocess, 'run', side_effect=run), \
                patch.object(self.helper.evidence, 'check_inputs') as check_inputs, \
                patch.object(self.helper, 'container_bootstrap', return_value=nullcontext('sha256:' + 'd'*64)):
            self.helper.check_batch()
        self.assertEqual(peak[0], 2)
        self.assertEqual(set(completed), set(batch['checks']))
        self.assertEqual(check_inputs.call_count, 2)
        self.assertTrue(all(call.kwargs == {'check_ids': batch['checks']} for call in check_inputs.call_args_list))

    def test_package_manager_and_windows_shared_resource_cases_remain_ordered(self):
        import threading
        caller = threading.get_ident()
        for platform, target, environment, scope in (
                ('Linux', 'linux-x86_64', 'debian-12', 'apt'),
                ('Windows', 'windows-x86_64', 'windows-2022', 'archive')):
            with self.subTest(platform=platform):
                plan = self.plan(('terminal', 'rev'), target, environment)
                plan.pop('id')
                for item in plan['checks']: item['scope'] = scope
                plan = ci.module('coverage').freeze(plan)
                (self.root / 'build/check-plan.json').write_text(json.dumps(plan))
                batch = ci.qualification_batches(plan)['include'][0]; seen = []; threads = []
                def run(command, **options):
                    seen.append(options['env']['CHECK']); threads.append(threading.get_ident())
                with patch.object(self.helper, 'ROOT', self.root), \
                        patch.object(self.helper.ci.platform, 'system', return_value=platform), \
                        patch.dict(self.helper.os.environ, BATCH=batch['id'], CHECK_IMAGE=batch['image'], FOUNDATION_CHECK_JOBS='999'), \
                        patch.object(self.helper, 'ThreadPoolExecutor', side_effect=AssertionError('shared resource pool')) as pool, \
                        patch.object(self.helper.subprocess, 'run', side_effect=run), \
                        patch.object(self.helper, 'container_bootstrap', return_value=nullcontext('sha256:' + 'd'*64)):
                    self.helper.check_batch()
                    pool.assert_not_called()
                self.assertEqual(seen, batch['checks'])
                self.assertEqual(threads, [caller] * len(batch['checks']))

    def test_invalid_private_case_budget_fails_before_bootstrap_or_launch(self):
        plan = self.plan(); batch = ci.qualification_batches(plan)['include'][0]
        with patch.object(self.helper, 'ROOT', self.root), \
                patch.object(self.helper.ci.platform, 'system', return_value='Linux'), \
                patch.dict(self.helper.os.environ, BATCH=batch['id'], CHECK_IMAGE=batch['image'], FOUNDATION_CHECK_JOBS='0'), \
                patch.object(self.helper.subprocess, 'run') as run, \
                patch.object(self.helper, 'container_bootstrap') as bootstrap:
            with self.assertRaisesRegex(ValueError, 'positive integer'):
                self.helper.check_batch()
        run.assert_not_called(); bootstrap.assert_not_called()

    def test_parallel_operations_join_remaining_writers_after_earlier_failure(self):
        import threading
        barrier=threading.Barrier(4); completed=[]; lock=threading.Lock()
        def task(index):
            barrier.wait(timeout=5)
            if index == 0: raise ValueError('first transfer failed')
            with lock: completed.append(index)
        with self.assertRaisesRegex(ValueError,'first transfer failed'):
            self.helper.parallel_operations([lambda index=index: task(index) for index in range(4)])
        self.assertEqual(set(completed),{1,2,3})

    def test_development_runner_plan_rejects_non_linux_before_selection(self):
        with patch.dict(self.helper.os.environ, TARGET='windows-x86_64', SDK_DEVELOPMENT='true'), \
                patch.object(self.helper, 'selected_runners') as select:
            with self.assertRaisesRegex(ValueError, 'requires a Linux target'):
                self.helper.main('runner-plan')
            select.assert_not_called()

    def test_runner_plan_uses_complete_allowlisted_selection(self):
        with patch.object(self.helper, 'ROOT', self.root), patch.object(self.helper.os, 'chdir'), \
                patch.dict(self.helper.os.environ, TARGET='linux-aarch64', LINUX_POOL='faster', FOUNDATION_FASTER_ARM_RUNNER='foundation-arm-fast'), \
                patch.object(self.helper, 'scalar_output') as output:
            self.helper.main('runner-plan')
        output.assert_called_once_with('runner','foundation-arm-fast')
        with patch.dict(self.helper.os.environ, TARGET='linux-aarch64', LINUX_POOL='faster', FOUNDATION_FASTER_ARM_RUNNER='unapproved-runner'):
            with self.assertRaisesRegex(ValueError,'authorized'): self.helper.selected_runners()

    def test_direct_metadata_fetch_authenticates_and_rederives_before_any_public_payload(self):
        names = ['qualification-inputs-2', 'qualification-linux-x86_64-2']
        plan = {'id':'a'*64}; batch = {'checks':['one']}; events = []
        context = dict(repository='example/project',run_id=12,attempt=2,source_commit='a'*40,workflow='certify.yml')
        with patch.object(self.helper, 'ROOT', self.root), \
                patch.object(self.helper, 'storage_context', return_value=context), \
                patch.object(self.helper, 'fetch_bundle', side_effect=lambda *args: events.append('authenticated-controls')), \
                patch.object(self.helper.evidence, 'load', return_value=plan), \
                patch.object(self.helper.evidence, 'validate', return_value=plan), \
                patch.object(self.helper.evidence, 'check_inputs', side_effect=lambda *args, **kw: events.append(kw)), \
                patch.object(self.helper, 'check_payload_selection', return_value=(batch,names)), \
                patch.object(self.helper.ci, 'fetch_candidate_payloads', return_value={'files':{}}) as payloads, \
                patch.dict(self.helper.os.environ, GITHUB_RUN_ATTEMPT='2', CHECK_PAYLOADS=json.dumps(names),
                    GITHUB_REPOSITORY='example/project', TAG='v1', INVENTORY='b'*64):
            self.helper.fetch_published_check_inputs()
            self.assertEqual(events, ['authenticated-controls', {'metadata_only':True}, {'check_ids':['one']}])
            payloads.assert_called_once()
            self.assertEqual(context,payloads.call_args.kwargs['trusted_context'])
            payloads.reset_mock()
            with patch.dict(self.helper.os.environ, CHECK_PAYLOADS=json.dumps(names+['qualification-source-2'])), \
                    self.assertRaisesRegex(ValueError, 'differs from complete frozen'):
                self.helper.fetch_published_check_inputs()
            payloads.assert_not_called()

    def test_metadata_publication_never_includes_source_or_sdk_payloads(self):
        import ci_transport
        with patch.object(self.helper, 'ROOT', self.root), \
                patch.object(self.helper, 'storage_context', return_value={}), \
                patch.object(self.helper.evidence, 'load', return_value={}), \
                patch.object(self.helper.evidence, 'validate', return_value={}), \
                patch.object(self.helper.evidence, 'check_inputs') as check, \
                patch.object(ci_transport, 'publish_bundle') as publish, \
                patch.dict(self.helper.os.environ, GITHUB_RUN_ATTEMPT='2', RUNNER_NAME='fixture-runner'):
            self.helper.qualification_metadata()
        self.assertEqual(publish.call_args.kwargs['paths'],
            ['candidate/release.json','delivery.json','candidate-remote.json','check-plan.json'])
        self.assertEqual([call.kwargs for call in check.call_args_list], [{'metadata_only':True}]*2)

    def test_evidence_controls_and_every_failed_outcome_restore_together_then_reconcile(self):
        plan = self.plan(); matrix = ci.qualification_batches(plan); events = []
        context = dict(repository='example/project', run_id=12, attempt=2,
                       source_commit='a'*40, workflow='certify.yml')
        with patch.object(self.helper, 'ROOT', self.root), \
                patch.object(self.helper, 'fetch_bundle', side_effect=lambda *args: events.append('controls')) as controls, \
                patch.object(self.helper, 'fetch_bundles', side_effect=lambda *args: events.append('evidence')) as fetch, \
                patch.object(self.helper.evidence, 'check_inputs', side_effect=lambda *args, **kwargs: events.append('validated-controls')), \
                patch.object(self.helper.ci_retry, 'local_present', return_value=True) as present, \
                patch.object(self.helper.ci_retry.EarlierAttempts, 'select_batch') as select_prior, \
                patch.object(self.helper.ci_retry.EarlierAttempts, 'restore') as restore_prior, \
                patch.object(self.helper.ci, 'module', return_value=Mock(verify_metadata=Mock(return_value={}))), \
                patch.object(self.helper.ci, 'qualification_batches', return_value=matrix), \
                patch.dict(self.helper.os.environ, GITHUB_ACTIONS='true', GITHUB_REPOSITORY='example/project',
                    GITHUB_WORKFLOW_REF='example/project/.github/workflows/certify.yml@refs/heads/main',
                    GITHUB_RUN_ID='12', GITHUB_SHA='a'*40, GITHUB_RUN_ATTEMPT='2',
                    CONTROL_ATTEMPT='2', CHECK_BATCHES=json.dumps(matrix)):
            self.helper.fetch_certification_evidence()
            self.assertEqual(events, ['controls', 'validated-controls', 'evidence'])
            controls.assert_called_once_with('qualification-inputs-2', self.root / 'build')
            fetch.assert_called_once()
            requests = fetch.call_args.args[0]
            self.assertEqual([row['name'] for row in requests], ['evidence-'+row['id']+'-2' for row in matrix['include']])
            self.assertTrue(all(row['allow_failed'] for row in requests))
            self.assertEqual([call.args for call in present.call_args_list],
                [(context, 'evidence-'+row['id']+'-2', 'evidence-'+str(index).zfill(2))
                 for index, row in enumerate(matrix['include'])])
            select_prior.assert_not_called(); restore_prior.assert_not_called()
            altered = {'include':[dict(row, runner='foreign-runner') for row in matrix['include']]}
            with patch.dict(self.helper.os.environ, CHECK_BATCHES=json.dumps(altered)), \
                    self.assertRaisesRegex(ValueError, 'differ from complete frozen'):
                self.helper.fetch_certification_evidence()
            fetch.assert_called_once()  # Rejected selectors must not fetch any outcome.

    def test_evidence_collection_requires_exact_workflow_context_before_fetch(self):
        matrix = ci.qualification_batches(self.plan())
        environment = dict(GITHUB_ACTIONS='true', GITHUB_REPOSITORY='example/project',
            GITHUB_WORKFLOW_REF='example/project/.github/workflows/certify.yml@refs/heads/main',
            GITHUB_RUN_ID='12', GITHUB_SHA='a'*40, GITHUB_RUN_ATTEMPT='2',
            CONTROL_ATTEMPT='2', CHECK_BATCHES=json.dumps(matrix))
        for changed in ({'GITHUB_WORKFLOW_REF':''}, {'GITHUB_SHA':''},
                        {'GITHUB_WORKFLOW_REF':'foreign/project/.github/workflows/certify.yml@refs/heads/main'}):
            with self.subTest(changed=changed), \
                    patch.dict(self.helper.os.environ, dict(environment, **changed), clear=True), \
                    patch.object(self.helper, 'fetch_bundle') as controls, \
                    patch.object(self.helper, 'fetch_bundles') as fetch, \
                    patch.object(self.helper.ci_retry, 'EarlierAttempts') as earlier:
                with self.assertRaises(ValueError): self.helper.fetch_certification_evidence()
                controls.assert_not_called(); fetch.assert_not_called(); earlier.assert_not_called()

    def test_check_input_fetch_rederives_exact_scope_before_executing_any_case(self):
        names=['qualification-inputs-2','qualification-linux-x86_64-2']
        plan={'id':'a'*64};batch={'checks':['one']}
        with patch.object(self.helper,'fetch_bundles') as fetch, \
                patch.object(self.helper.evidence,'load',return_value=plan), \
                patch.object(self.helper.evidence,'validate',return_value=plan), \
                patch.object(self.helper.evidence,'check_inputs') as check_inputs, \
                patch.object(self.helper,'check_payload_selection',return_value=(batch,names)), \
                patch.dict(self.helper.os.environ,GITHUB_RUN_ATTEMPT='2',CHECK_PAYLOADS=json.dumps(names)):
            self.helper.fetch_check_inputs()
            self.assertEqual(fetch.call_count,1)
            self.assertEqual([row['name'] for row in fetch.call_args.args[0]],names)
            self.assertEqual(check_inputs.call_args.kwargs,{'check_ids':['one']})
            wrong=names+['qualification-source-2']
            with patch.dict(self.helper.os.environ,CHECK_PAYLOADS=json.dumps(wrong)), self.assertRaisesRegex(ValueError,'differs from complete frozen'):
                self.helper.fetch_check_inputs()
            self.assertEqual(check_inputs.call_args.kwargs,{'metadata_only':True})
        with patch.object(self.helper,'fetch_bundles') as fetch:
            for invalid in ([],names+names,[names[0],'unrelated-2'],[names[0],'qualification-linux-x86_64-1']):
                with patch.dict(self.helper.os.environ,GITHUB_RUN_ATTEMPT='2',CHECK_PAYLOADS=json.dumps(invalid)), self.assertRaises(ValueError):
                    self.helper.fetch_check_inputs()
            fetch.assert_not_called()

    def test_group_restore_preflights_all_collisions_before_final_file_writes(self):
        from unittest.mock import Mock
        original=ci.module;transport=Mock(); output=self.root/'restored'
        requests=[{'name':'one','output':output},{'name':'two','output':output}]
        collision=[False]
        def fetch(repository,run_id,attempt,source_commit,workflow,selected):
            result=[]
            for index,request in enumerate(selected):
                staged=Path(request['output']);staged.mkdir(parents=True)
                name='shared.log' if collision[0] else 'case-'+str(index)+'/result.json'
                path=staged/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(b'proof'+str(index).encode())
                result.append({'manifest':{'name':request['name'],'files':{name:{'mode':0o600}}}})
            return result
        transport.fetch_bundles.side_effect=fetch
        with patch.object(ci,'module',side_effect=lambda name:transport if name=='ci_transport' else original(name)):
            results=ci.restore_run_bundles('example/project',1,2,'a'*40,'certify.yml',requests)
            self.assertEqual(len(results),2);self.assertEqual((output/'case-0/result.json').read_bytes(),b'proof0')
            mode=(output/'case-1/result.json').stat().st_mode
            self.assertTrue(mode & 0o200)
            if sys.platform != 'win32':
                self.assertEqual(mode & 0o777,0o600)
            collision[0]=True;other=self.root/'collision';requests=[dict(request,output=other) for request in requests]
            with self.assertRaisesRegex(ValueError,'colliding'):
                ci.restore_run_bundles('example/project',1,2,'a'*40,'certify.yml',requests)
            self.assertFalse(other.exists())

    def test_host_browser_keeps_per_case_prerequisite_before_check(self):
        plan = self.plan(('wasm',), 'browser-wasm32', 'chromium'); batch = ci.qualification_batches(plan)['include'][0]
        with patch.object(self.helper, 'ROOT', self.root), patch.object(self.helper.ci.platform, 'system', return_value='Linux'), \
                patch.dict(self.helper.os.environ, BATCH=batch['id'], CHECK_IMAGE=''), \
                patch.object(self.helper.subprocess, 'run') as run:
            self.helper.check_batch()
        self.assertEqual([call.args[0][-1] for call in run.call_args_list], ['check-prerequisites', 'check'])
        self.assertTrue(all(call.kwargs['env']['CHECK'] == 'case-0' and call.kwargs['env']['CHECK_BROWSER'] == 'yes'
                            for call in run.call_args_list))

    def test_windows_batch_runs_independent_cases_without_container_or_browser_setup(self):
        plan = self.plan(('terminal', 'rev'), 'windows-x86_64', 'windows-2022'); batch = ci.qualification_batches(plan)['include'][0]
        with patch.object(self.helper, 'ROOT', self.root), patch.object(self.helper.ci.platform, 'system', return_value='Windows'), \
                patch.dict(self.helper.os.environ, BATCH=batch['id'], CHECK_IMAGE=''), \
                patch.object(self.helper.subprocess, 'run') as run:
            self.helper.check_batch()
        self.assertEqual([call.args[0][-1] for call in run.call_args_list], ['check', 'check'])
        self.assertEqual([call.kwargs['env']['CHECK'] for call in run.call_args_list], ['case-0', 'case-1'])

    def test_windows_source_checks_exclude_transport_attempt_without_changing_parent(self):
        for scope in ('source', 'recovery'):
            with self.subTest(scope=scope):
                plan = self.plan(('terminal',), 'windows-x86_64', 'windows-2022')
                plan.pop('id'); plan['checks'][0]['scope'] = scope
                plan = ci.module('coverage').freeze(plan)
                (self.root / 'build/check-plan.json').write_text(json.dumps(plan))
                batch = ci.qualification_batches(plan)['include'][0]
                with patch.object(self.helper, 'ROOT', self.root), \
                        patch.object(self.helper.ci.platform, 'system', return_value='Windows'), \
                        patch.dict(self.helper.os.environ, BATCH=batch['id'], CHECK_IMAGE='',
                                   CONTROL_ATTEMPT='1', GITHUB_RUN_ATTEMPT='2'), \
                        patch.object(self.helper.subprocess, 'run') as run:
                    self.helper.check_batch()
                    self.assertEqual(self.helper.os.environ['CONTROL_ATTEMPT'], '1')
                    self.assertEqual(self.helper.os.environ['GITHUB_RUN_ATTEMPT'], '2')
                run.assert_called_once()
                environment = run.call_args.kwargs['env']
                self.assertNotIn('CONTROL_ATTEMPT', set(environment))
                self.assertEqual(environment['GITHUB_RUN_ATTEMPT'], '2')
                self.assertEqual(environment['CHECK'], 'case-0')

    def test_batch_selection_rejects_unknown_id_image_and_changed_frozen_input_before_launch(self):
        plan = self.plan(); batch = ci.qualification_batches(plan)['include'][0]
        with patch.object(self.helper, 'ROOT', self.root), patch.object(self.helper.ci.platform, 'system', return_value='Linux'), \
                patch.object(self.helper.subprocess, 'run') as run:
            for identity, image in (('absent', batch['image']), (batch['id'], 'ubuntu:24.04')):
                with patch.dict(self.helper.os.environ, BATCH=identity, CHECK_IMAGE=image), self.assertRaises(ValueError):
                    self.helper.check_batch()
            (self.root / 'mapping.py').write_text('before')
            plan.pop('id'); plan['inputs'] = {'mapping.py': ci.module('coverage').sha(self.root / 'mapping.py')}
            plan = ci.module('coverage').freeze(plan)
            (self.root / 'build/check-plan.json').write_text(json.dumps(plan))
            (self.root / 'mapping.py').write_text('after')
            with patch.dict(self.helper.os.environ, BATCH=batch['id'], CHECK_IMAGE=batch['image']), \
                    self.assertRaisesRegex(ValueError, 'check input changed'):
                self.helper.check_batch()
            run.assert_not_called()

    def test_future_batch_growth_splits_without_changing_execution_inventory(self):
        plan = self.plan(tuple('backend-' + str(index) for index in range(33)))
        batches = ci.qualification_batches(plan)['include']
        self.assertEqual([len(batch['checks']) for batch in batches], [16, 16, 1])
        self.assertEqual([check for batch in batches for check in batch['checks']], [item['id'] for item in plan['checks']])
        self.assertEqual(len({batch['id'] for batch in batches}), 3)

    def test_normalized_truncated_batch_ids_preserve_checks_and_reject_digest_collision(self):
        c = ci.module('coverage'); plan = self.plan(tuple('backend-' + str(index) for index in range(33)))
        plan.pop('id')
        for index, item in enumerate(plan['checks']):
            item['id'] = ('Case.Shared.' if index % 2 == 0 else 'case-shared-') + 'x'*100 + '-' + str(index)
        plan = c.freeze(plan); before = copy.deepcopy(plan)
        batches = ci.qualification_batches(plan)['include']
        self.assertEqual(plan, before)
        self.assertEqual([check for batch in batches for check in batch['checks']], [item['id'] for item in plan['checks']])
        self.assertEqual(len({batch['id'] for batch in batches}), 3)
        self.assertTrue(all(len(batch['id']) <= 39 and batch['id'].startswith('batch-case-shared-') for batch in batches))
        self.assertEqual(ci.qualification_batches(plan)['include'], batches)
        original, loader = c.digest, ci.module
        with patch.object(ci, 'module', side_effect=lambda name: c if name == 'coverage' else loader(name)), \
                patch.object(c, 'digest', side_effect=lambda value: '0'*64 if 'runner' in value else original(value)):
            with self.assertRaisesRegex(ValueError, 'colliding batch transport identity'):
                ci.qualification_batches(plan)

    def test_evidence_aggregation_fetches_each_batch_once_into_shared_case_root(self):
        plan = self.plan(); batch = ci.qualification_batches(plan)['include'][0]
        with patch.object(self.helper, 'ROOT', self.root), patch.object(self.helper.os, 'chdir'), \
                patch.object(self.helper.evidence, 'load', return_value=plan), \
                patch.dict(self.helper.os.environ, GITHUB_RUN_ATTEMPT='2'), \
                patch.object(self.helper, 'fetch_bundle') as fetch:
            self.helper.main('fetch-evidence-bundles')
        fetch.assert_called_once_with('evidence-' + batch['id'] + '-2', 'build', allow_failed=True)

    def test_batch_bundle_preserves_case_children_and_disjoint_restore_rejects_collision(self):
        from unittest.mock import Mock
        for name in ('case-a', 'case-b'):
            path = self.root / 'build/evidence' / name; path.mkdir(parents=True)
            (path / 'result.json').write_text(name)
        with patch.object(self.helper, 'ROOT', self.root):
            base, paths = self.helper.bundle_inputs('build/evidence/')
        self.assertEqual(base, self.root / 'build/evidence')
        self.assertEqual(paths, ['case-a', 'case-b'])
        original = ci.module
        def fetched(repository, run, attempt, source, workflow, name, output, **options):
            path = output / name / 'result.json'; path.parent.mkdir(parents=True); path.write_text(name)
            return {'manifest': {'files': {name + '/result.json': {'mode': 0o600}}}}
        transport = Mock(fetch_bundle=Mock(side_effect=fetched)); destination = self.root / 'restored'
        with patch.object(ci, 'module', side_effect=lambda name: transport if name == 'ci_transport' else original(name)):
            for name in ('case-a', 'case-b'):
                ci.restore_run_bundle('example/project', 1, 1, 'a'*40, 'certify.yml', name, destination, allow_failed=True)
            with self.assertRaisesRegex(ValueError, 'existing file'):
                ci.restore_run_bundle('example/project', 1, 1, 'a'*40, 'certify.yml', 'case-a', destination, allow_failed=True)
        self.assertEqual({path.relative_to(destination).as_posix(): path.read_text() for path in destination.rglob('*.json')},
                         {'case-a/result.json': 'case-a', 'case-b/result.json': 'case-b'})


class SdkMaintenanceTests(unittest.TestCase):
    def setUp(self):
        sys.path.insert(0, str(Path(__file__).parent))
        import test_github_release
        self.fixture = test_github_release.DeliveryTests(); self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.remote = self.fixture.remote; self.root = self.fixture.root
        self.recipe = self.fixture.fixture.recipe

    def choose(self, **changes):
        args = dict(repository='example/project', recipe=self.recipe, output=self.root / 'selected', transport=self.remote)
        args.update(changes); return ci.maintenance_base(**args)

    def test_absence_is_explicit_and_base_only_never_rebuilds(self):
        self.assertEqual(self.choose()['origin'], 'absent-base')
        with self.assertRaisesRegex(ValueError, 'absent'): self.choose(source='base')
        self.assertFalse((self.root / 'selected').exists())
        self.remote.refs['base'] = 'a' * 40
        with self.assertRaisesRegex(ValueError, 'orphan'): self.choose()
        self.assertEqual(self.remote.mutations, [])

    def test_complete_base_is_verified_and_reused(self):
        self.fixture.base(execute=True); before = len(self.remote.mutations)
        result = self.choose()
        self.assertEqual(result['origin'], 'base')
        self.assertTrue((self.root / 'selected').is_dir())
        self.assertEqual(len(self.remote.mutations), before)

    def test_partial_corrupt_and_network_errors_never_fall_back(self):
        self.fixture.base(execute=True)
        complete = copy.deepcopy(self.remote.releases[0]['assets'])
        self.remote.releases[0]['assets'].pop()
        with self.assertRaisesRegex(ValueError, 'partial'): self.choose()
        self.remote.releases[0]['assets'] = complete
        first = complete[0]; self.remote.data[first['id']] = b'corrupt'
        with self.assertRaisesRegex(ValueError, 'bytes'): self.choose()
        with patch.object(self.remote, 'pages', side_effect=OSError('network unavailable')):
            with self.assertRaisesRegex(OSError, 'network'): self.choose()
        self.assertFalse((self.root / 'selected').exists())

    def test_only_explicit_rebuild_skips_remote_and_other_recipe_absence_is_checked(self):
        with patch.object(self.remote, 'pages', side_effect=AssertionError('unexpected network')):
            self.assertEqual(self.choose(source='rebuild')['origin'], 'rebuild')
        self.fixture.base(execute=True)
        self.assertEqual(self.choose(recipe='b' * 64)['origin'], 'absent-recipe')
        with self.assertRaises(ValueError): self.choose(source='latest')

    def test_core_sdk_probe_requires_copied_installed_consumer_success(self):
        import shutil
        from unittest.mock import Mock
        original = ci.module; sdk = Mock(); artifacts = original('artifact')
        verifier = Mock(describe=artifacts.describe)
        def selected(name):
            return sdk if name == 'sdk' else verifier if name == 'artifact' else original(name)
        manifest = original('release').verify_release(self.fixture.directory)
        archive = self.fixture.directory / manifest['artifacts'][0]['archive']
        output = self.root / 'probe'; commands = []
        def run(argv, **kwargs):
            commands.append(argv)
            if argv[2] == 'package':
                packages = Path(argv[argv.index('--build-dir') + 1]) / 'packages'; packages.mkdir(parents=True)
                shutil.copyfile(archive, packages / 'application.tar.gz')
        with patch.object(ci, 'module', side_effect=selected), patch.object(ci, 'assert_host'), patch.object(ci.subprocess, 'run', side_effect=run):
            result = ci.prepared_check('linux-x86_64', self.recipe, self.root / 'group', output, core_provider='cpp')
            self.assertIn('installed-consumer', result['checks'])
            self.assertEqual([x[2] for x in commands], ['test', 'package'])
            self.assertIn('--label', commands[0]); self.assertNotIn('--label', commands[1])
            self.assertNotIn('--junit', commands[1]); verifier.verify.assert_called_once()
            verifier.verify.side_effect = ValueError('installed consumer failed')
            with self.assertRaisesRegex(ValueError, 'consumer failed'):
                ci.prepared_check('linux-x86_64', self.recipe, self.root / 'group', self.root / 'failed-probe', core_provider='cpp')
            self.assertFalse((self.root / 'failed-probe/qualification.json').exists())

    def test_browser_core_probe_selects_wasm_for_test_and_package_without_gui(self):
        import shutil
        from unittest.mock import Mock
        original = ci.module; sdk = Mock(); artifacts = original('artifact')
        verifier = Mock(describe=artifacts.describe)
        def selected(name):
            return sdk if name == 'sdk' else verifier if name == 'artifact' else original(name)
        manifest = original('release').verify_release(self.fixture.directory)
        archive = self.fixture.directory / manifest['artifacts'][0]['archive']
        output = self.root / 'browser-probe'; commands = []
        def run(argv, **kwargs):
            commands.append(argv)
            if argv[2] == 'package':
                packages = output / 'build/packages'; packages.mkdir(parents=True)
                shutil.copyfile(archive, packages / 'application.tar.gz')
        with patch.object(ci, 'module', side_effect=selected), patch.object(ci.platform, 'system', return_value='Linux'), patch.object(ci.platform, 'machine', return_value='x86_64'), patch.object(ci.subprocess, 'run', side_effect=run):
            result = ci.prepared_check('browser-wasm32', self.recipe, self.root / 'group', output, core_provider='cpp')
        self.assertEqual([argv[2] for argv in commands], ['test', 'package'])
        for argv in commands:
            self.assertEqual(argv[argv.index('--gui-backends') + 1], 'wasm')
            self.assertNotIn('--gui-input-group', argv); self.assertNotIn('--gui-source', argv)
        self.assertIn('--label', commands[0]); self.assertNotIn('--label', commands[1])
        self.assertEqual(result['target'], 'browser-wasm32')
        self.assertEqual(verifier.verify.call_args.kwargs['sdk'], output / 'sdk')

    def test_development_sdk_checks_both_ordinary_commands_without_portable(self):
        from unittest.mock import Mock
        original = ci.module; sdk = Mock()
        sdk.install.return_value = {'capabilities': ['terminal', 'framebuffer', 'fltk', 'rev', 'sdl', 'hosted-web']}
        def selected(name): return sdk if name == 'sdk' else original(name)
        group = self.root / 'group'; output = self.root / 'development-check'
        with patch.object(ci, 'module', side_effect=selected), patch.object(ci, 'assert_host'), patch.object(ci.subprocess, 'run') as run:
            result = ci.prepared_check('linux-x86_64', self.recipe, group, output, gui_group=group, development=True, core_provider='cpp')
        commands = [call.args[0] for call in run.call_args_list]
        self.assertEqual([row[2:4] for row in commands], [['build', 'dev'], ['test', 'dev']])
        for command in commands:
            self.assertIn('--sdk', command); self.assertIn('--host-tests', command)
            self.assertNotIn('--portable', command); self.assertNotIn('--label', command)
        self.assertNotIn('--full', commands[0]); self.assertNotIn('--junit', commands[0])
        self.assertIn('--full', commands[1]); self.assertIn('--junit', commands[1])
        self.assertEqual(result['configuration'], 'dev'); self.assertFalse(result['redistribution'])
        self.assertIn('without-portable-mode', result['checks'])
        with patch.object(ci, 'module', side_effect=selected), patch.object(ci, 'assert_host'), \
                patch.object(ci.subprocess, 'run', side_effect=subprocess.CalledProcessError(1, ['build'])):
            failed = self.root / 'development-failed'
            with self.assertRaises(subprocess.CalledProcessError):
                ci.prepared_check('linux-x86_64', self.recipe, group, failed, gui_group=group, development=True, core_provider='cpp')
            self.assertFalse((failed / 'qualification.json').exists())

    def test_development_sdk_scope_rejects_unsupported_targets_before_install(self):
        group = self.root / 'group'
        with patch.object(ci, 'assert_host') as host:
            for target, gui, mode in [('windows-x86_64', group, True), ('browser-wasm32', group, True),
                                      ('linux-x86_64', None, True), ('linux-x86_64', group, 'true')]:
                output = self.root / 'not-created'
                with self.assertRaisesRegex(ValueError, 'development qualification'):
                    ci.prepared_check(target, self.recipe, group, output, gui_group=gui, development=mode, core_provider='cpp')
                self.assertFalse(output.exists())
            host.assert_not_called()

    def test_gui_qualification_never_packages_or_uploads_inputs(self):
        from unittest.mock import Mock
        original = ci.module; sdk = Mock()
        sdk.install.return_value = {'capabilities': ['core', 'terminal', 'framebuffer', 'fltk', 'rev', 'sdl', 'hosted-web']}
        def selected(name): return sdk if name == 'sdk' else original(name)
        group = self.root / 'group'; output = self.root / 'gui-check'
        with patch.object(ci, 'module', side_effect=selected), patch.object(ci, 'assert_host'), patch.object(ci.subprocess, 'run') as run:
            result = ci.prepared_check('linux-x86_64', self.recipe, group, output, gui_group=group, core_provider='cpp')
        self.assertEqual(run.call_count, 1)
        argv = run.call_args.args[0]
        self.assertEqual(argv[2], 'test'); self.assertIn('--full', argv); self.assertIn('--host-tests', argv)
        self.assertFalse(result['redistribution'])
        self.assertEqual(self.remote.mutations, [])
        with patch.object(ci, 'module', side_effect=selected), patch.object(ci, 'assert_host'), patch.object(ci.subprocess, 'run') as run:
            sdk.install.return_value = {'capabilities': ['core']}
            with self.assertRaisesRegex(ValueError, 'capabilities'):
                ci.prepared_check('linux-x86_64', self.recipe, group, self.root / 'insufficient', gui_group=group, core_provider='cpp')
            run.assert_not_called()


class WindowsGraphicsCiTests(unittest.TestCase):
    def test_graphics_selection_covers_combined_source_and_specific_archive_only(self):
        for backend in ('terminal', 'fltk', 'rev', 'hosted-web'):
            for scope in ('source', 'recovery', 'archive', 'abi', 'apt'):
                self.assertEqual(ci.needs_windows_graphics('windows-x86_64', ['fltk', 'rev'], backend, scope),
                                 scope in ('source', 'recovery') or backend == 'rev' and scope == 'archive')
                self.assertFalse(ci.needs_windows_graphics('windows-x86_64', ['core'], backend, scope))
                self.assertFalse(ci.needs_windows_graphics('linux-x86_64', ['rev'], backend, scope))

    def test_graphics_input_cannot_enter_core_or_non_windows_probe(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for target, gui, archive in (('windows-x86_64', root, None),
                    ('windows-x86_64', None, root / 'graphics.7z'), ('linux-x86_64', root, root / 'graphics.7z')):
                with self.assertRaisesRegex(ValueError, 'explicit retained'):
                    ci.prepared_check(target, 'a' * 64, root, root / 'output', gui_group=gui, graphics_archive=archive, core_provider='cpp')
            self.assertFalse((root / 'output').exists())

    def test_gui_runner_uses_bounded_shared_owner_and_propagates_failures(self):
        from types import SimpleNamespace
        from unittest.mock import Mock
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); runtime = Mock(); staged = SimpleNamespace(environment={'PATH': 'controlled'})
            with patch.object(ci, 'module', return_value=runtime):
                ci.graphics_test(['test-command'], root, staged)
                runtime.run_owned.assert_called_once_with(['test-command'], root, root / 'graphics-test.log',
                    environment=staged.environment, timeout=3600, max_bytes=16 * 1024 * 1024)
                runtime.run_owned.side_effect = RuntimeError('writer cleanup unknown')
                with self.assertRaisesRegex(RuntimeError, 'cleanup unknown'):
                    ci.graphics_test(['test-command'], root, staged)

    def test_windows_gui_uses_shared_build_then_probe_and_test_before_cleanup(self):
        from types import SimpleNamespace
        from contextlib import contextmanager
        from unittest.mock import Mock
        sys.path.insert(0, str(Path(__file__).parent)); import test_github_release
        fixture = test_github_release.DeliveryTests(); fixture.setUp(); self.addCleanup(fixture.doCleanups)
        root = fixture.root; output = root / 'graphics-check'; events = []; commands = []
        original = ci.module; sdk = Mock(); graphics = Mock(); compiler = Mock()
        sdk.install.return_value = {'capabilities': ['terminal', 'framebuffer', 'fltk', 'rev', 'sdl', 'hosted-web']}
        @contextmanager
        def stage(archive, directories, **options):
            self.assertEqual(events, ['build', 'prerequisites'])
            self.assertEqual(directories, [output / 'build/gui'])
            self.assertIn(output / 'dependencies', options['protected_roots'])
            current = SimpleNamespace(environment={'TEST_GRAPHICS': 'owned'}, receipt={'cleanup': 'active'},
                                      probe_receipt={'status': 'passed'})
            events.append('probe')
            try: yield current
            finally: events.append('cleanup'); current.receipt['cleanup'] = 'removed'
        graphics.qualified_stage.side_effect = stage
        def selected(name):
            if name == 'windows_toolchain':
                import windows_toolchain
                return windows_toolchain
            return {'sdk_windows': sdk, 'windows_graphics': graphics, 'windows_compiler': compiler}.get(name) or original(name)
        def command(argv, **kwargs):
            self.assertEqual(kwargs, {'cwd': ci.ROOT})
            commands.append(argv)
            if argv[0] == 'cmake': events.append('prerequisites')
            else:
                self.assertEqual(argv[2], 'build'); self.assertNotIn('--junit', argv); self.assertNotIn('--full', argv)
                (output / 'build/gui').mkdir(parents=True); events.append('build')
        compiler.run.side_effect = command
        def tested(argv, destination, staged):
            self.assertEqual(argv[2], 'test'); self.assertIn('--full', argv); self.assertIn('--host-tests', argv)
            self.assertEqual(staged.environment, {'TEST_GRAPHICS': 'owned'}); events.append('test')
            captures = output / 'build/gui/visual-evidence/run-one'; captures.mkdir(parents=True)
            for name in ('qualification.json', 'capture.png', 'capture.ppm'): (captures / name).write_bytes(b'fixture')
        with patch.object(ci, 'module', side_effect=selected), patch.object(ci, 'assert_host'), \
             patch('windows_toolchain.inspect_selected_linker', return_value={'version':'14.44.35207.0'}), \
             patch.object(ci.subprocess, 'run', side_effect=AssertionError('unowned compiler launch')), patch.object(ci, 'graphics_test', side_effect=tested):
            result = ci.prepared_check('windows-x86_64', fixture.fixture.recipe, root / 'group', output,
                                      gui_group=root / 'group', graphics_archive=root / 'graphics.7z', core_provider='cpp')
        sdk.install.assert_called_once_with((root / 'group').resolve(strict=True), fixture.fixture.recipe, output / 'dependencies', '14.44.35207.0')
        self.assertEqual(events, ['build', 'prerequisites', 'probe', 'test', 'cleanup'])
        self.assertEqual(compiler.run.call_count, 2)
        self.assertEqual(compiler.run.call_args_list[1].args[0],
                         ['cmake', '--build', str(output / 'build'), '--target', 'foundation-gui-tests', '--parallel', '2'])
        self.assertEqual(json.loads((output / 'graphics.json').read_text())['cleanup'], 'removed')
        self.assertIn('graphics.json', result['graphics_evidence'])
        self.assertIn('build/gui/visual-evidence/run-one/capture.png', result['graphics_evidence'])
        self.assertFalse(result['redistribution'])
        self.assertNotIn('package', [item[2] for item in commands])
        graphics.fetch.assert_not_called(); graphics.fetch_retained.assert_not_called()
        events.clear(); commands.clear(); output = root / 'failed-graphics-check'
        with patch.object(ci, 'module', side_effect=selected), patch.object(ci, 'assert_host'), \
             patch('windows_toolchain.inspect_selected_linker', return_value={'version':'14.44.35207.0'}), \
             patch.object(ci.subprocess, 'run', side_effect=AssertionError('unowned compiler launch')), \
             patch.object(ci, 'graphics_test', side_effect=RuntimeError('GUI assertion failed')):
            with self.assertRaisesRegex(RuntimeError, 'GUI assertion failed'):
                ci.prepared_check('windows-x86_64', fixture.fixture.recipe, root / 'group', output,
                                  gui_group=root / 'group', graphics_archive=root / 'graphics.7z', core_provider='cpp')
        self.assertEqual(events, ['build', 'prerequisites', 'probe', 'cleanup'])
        self.assertFalse((output / 'qualification.json').exists())
        self.assertEqual(json.loads((output / 'graphics.json').read_text())['cleanup'], 'removed')
        events.clear(); output = root / 'failed-setup'
        failure = RuntimeError('probe setup failed'); failure.graphics_receipt = {'cleanup': 'retained-uncertain'}
        graphics.qualified_stage.side_effect = failure
        with patch.object(ci, 'module', side_effect=selected), patch.object(ci, 'assert_host'), \
             patch('windows_toolchain.inspect_selected_linker', return_value={'version':'14.44.35207.0'}), \
             patch.object(ci.subprocess, 'run', side_effect=AssertionError('unowned compiler launch')):
            with self.assertRaisesRegex(RuntimeError, 'probe setup failed'):
                ci.prepared_check('windows-x86_64', fixture.fixture.recipe, root / 'group', output,
                                  gui_group=root / 'group', graphics_archive=root / 'graphics.7z', core_provider='cpp')
        self.assertFalse((output / 'qualification.json').exists())
        self.assertEqual(json.loads((output / 'graphics.json').read_text()), failure.graphics_receipt)

    def test_only_explicit_maintenance_uses_supplier_fetch(self):
        from unittest.mock import Mock
        helper_spec = importlib.util.spec_from_file_location('graphics_ci_lifecycle', ci.ROOT / '.github/scripts/lifecycle.py')
        helper = importlib.util.module_from_spec(helper_spec); helper_spec.loader.exec_module(helper)
        for command in ('graphics-input', 'graphics-maintain'):
            with self.subTest(command=command), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                archive = root / 'build/host-graphics/mesa-windows.7z'
                graphics = Mock()
                def acquired(*args, **kwargs):
                    self.assertTrue(archive.parent.is_dir())
                    self.assertFalse(archive.exists())
                    return {'acquisition': command}
                graphics.fetch.side_effect = acquired; graphics.fetch_retained.side_effect = acquired
                with patch.dict(sys.modules, {'windows_graphics': graphics}), patch.object(helper, 'ROOT', root), \
                     patch.object(helper.os, 'chdir'), patch.object(helper.ci, 'assert_host'), \
                     patch.object(helper, 'write') as published, \
                     patch.dict(helper.os.environ, {'GRAPHICS_ARCHIVE_URL': 'https://storage.example/retained.7z'}):
                    helper.main(command)
                    if command == 'graphics-input':
                        graphics.fetch.assert_not_called()
                        graphics.fetch_retained.assert_called_once_with('https://storage.example/retained.7z', archive)
                    else:
                        graphics.fetch.assert_called_once_with(archive, network=True)
                        graphics.fetch_retained.assert_not_called()
                    published.assert_called_once_with('build/host-graphics/acquisition.json', {'acquisition': command})
                    graphics.reset_mock(); published.reset_mock()
                    archive.parent.rmdir(); archive.parent.write_bytes(b'not a directory')
                    with self.assertRaises(FileExistsError): helper.main(command)
                    graphics.fetch.assert_not_called(); graphics.fetch_retained.assert_not_called()
                    published.assert_not_called()
        for workflow in ('sdk-maintenance.yml', 'native-gui.yml', 'certify.yml'):
            text = (ci.ROOT / '.github/workflows' / workflow).read_text()
            self.assertNotIn('path: build/host-graphics/', text)
            self.assertNotIn('mesa-windows.7z\n', text)


class WindowsGraphicsPackageTests(unittest.TestCase):
    """Real source/group/archive inventories with isolated host-operation fixtures."""
    def setUp(self):
        from unittest.mock import Mock
        from test_sdk import fixture
        self.temporary = tempfile.TemporaryDirectory(); self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.recipe, _, _, self.group = fixture(self.root)
        source = self.root / 'source'; source.mkdir()
        (source / 'LICENSE').write_text('Inert source fixture\n')
        self.core_source = self.root / 'core-source.tar.gz'
        ci.module('source_identity').archive_source(source, self.core_source)
        gui = source / 'third_party/retained/gui'; gui.mkdir(parents=True)
        (gui / 'interface.hpp').write_text('/* retained GUI source fixture */\n')
        self.gui_source = self.root / 'gui-source.tar.gz'
        ci.module('source_identity').archive_source(source, self.gui_source)
        self.output = self.root / 'produced'; self.archive = self.root / 'retained.7z'
        self.archive.write_bytes(b'inert retained archive fixture')
        self.graphics = Mock(); self.sdk = Mock(); self.compiler = Mock(); self.events = []; self.commands = []
        self.compiler_failure = None
        self.sdk.install.return_value = {'capabilities': ['terminal', 'framebuffer', 'fltk', 'rev', 'sdl', 'hosted-web']}
        self.real_module = ci.module
        self.artifacts = Mock(describe=self.real_module('artifact').describe)
        self.cleanup = 'removed'; self.test_error = None; self.write_captures = True; self.setup_error = None

    def produce(self, *, source=None, target='windows-x86_64', graphics=True):
        from contextlib import contextmanager
        from types import SimpleNamespace
        import zipfile
        build = self.output / 'work/build'
        drivers = []
        @contextmanager
        def stage(archive, directories, **options):
            self.assertEqual(archive, self.archive)
            self.assertEqual(self.events, ['build', 'prerequisites'])
            self.assertEqual(directories, [build / 'gui'])
            self.assertEqual(options['compile_log'], self.output / 'graphics-compile.log')
            self.assertIn(self.group.resolve(), options['protected_roots'])
            self.assertIn(self.output / 'work/source', options['protected_roots'])
            self.assertIn(self.output / 'work/dependencies', options['protected_roots'])
            if self.setup_error: raise self.setup_error
            for directory in [*directories, options['probe_directory']]:
                for name in ('opengl32.dll', 'libgallium_wgl.dll'):
                    path = directory / name; path.write_bytes(b'host-only fixture'); drivers.append(path)
            current = SimpleNamespace(environment={'GRAPHICS_FIXTURE': 'owned'},
                receipt={'cleanup': 'active'}, probe_receipt={'status': 'passed'})
            self.events.append('probe')
            try: yield current
            finally:
                self.events.append('cleanup'); current.receipt['cleanup'] = self.cleanup
                if self.cleanup == 'removed':
                    for path in drivers: path.unlink()
        def run_test(argv, cwd, log, **options):
            self.assertEqual(argv[2:4], ['test', 'release'])
            self.assertIn('--full', argv); self.assertIn('--host-tests', argv)
            self.assertEqual(Path(argv[argv.index('--build-dir') + 1]), build)
            self.assertEqual(options['environment'], {'GRAPHICS_FIXTURE': 'owned'})
            self.assertEqual((options['timeout'], options['max_bytes']), (3600, 16 * 1024 * 1024))
            self.assertEqual(cwd, self.output); self.assertEqual(log, self.output / 'graphics-test.log')
            self.assertTrue(all(path.is_file() for path in drivers)); self.events.append('test')
            log.write_text('fixture command output\n')
            if self.test_error: raise self.test_error
            if self.write_captures:
                capture = build / 'gui/visual-evidence/fixture'; capture.mkdir(parents=True)
                for name in ('qualification.json', 'capture.png', 'capture.ppm'): (capture / name).write_bytes(b'fixture')
        def selected(name):
            if name == 'windows_toolchain':
                import windows_toolchain
                return windows_toolchain
            return {'sdk_windows': self.sdk, 'windows_graphics': self.graphics, 'artifact': self.artifacts,
                    'windows_compiler': self.compiler}.get(name) or self.real_module(name)
        def launched(argv, **options):
            self.commands.append(argv)
            if argv[0] == 'cmake':
                self.assertEqual(argv[2], str(build)); self.events.append('prerequisites'); return
            self.assertEqual(options['cwd'], self.output / 'work/source')
            self.assertEqual(Path(argv[argv.index('--build-dir') + 1]), build)
            if argv[2] == 'build':
                self.assertNotIn('--full', argv); self.assertNotIn('--junit', argv)
                (build / 'gui').mkdir(parents=True); self.events.append('build')
            elif argv[2] == 'package':
                self.assertEqual(self.events, ['build', 'prerequisites', 'probe', 'test', 'cleanup'])
                self.assertFalse(any(path.exists() for path in drivers))
                self.assertNotIn('--full', argv); self.assertNotIn('--junit', argv)
                self.events.append('package'); destination = build / 'packages'; destination.mkdir()
                with zipfile.ZipFile(destination / 'application.zip', 'x') as archive:
                    archive.writestr('Foundation/bin/foundation-cli.exe', 'inert program fixture')
            else: raise AssertionError(argv)
        def owned(argv, **options):
            phase = 'prerequisites' if argv[0] == 'cmake' else 'build'
            self.assertEqual(options, {'cwd': self.output / 'work/source'})
            if self.compiler_failure == phase:
                import process_tree
                raise process_tree.ProcessTreeError('compiler cleanup unknown: ' + phase)
            return launched(argv, **options)
        def unmanaged(argv, **options):
            self.assertEqual(argv[2], 'package', 'compiler launch bypassed its private owner')
            return launched(argv, **options)
        self.compiler.run.side_effect = owned
        self.graphics.qualified_stage.side_effect = stage
        self.graphics.run_owned.side_effect = run_test
        with patch.object(ci, 'module', side_effect=selected), patch.object(ci, 'assert_host'), \
             patch('windows_toolchain.inspect_selected_linker', return_value={'version':'14.44.35207.0'},
                   side_effect=getattr(self, 'probe_error', None)), \
             patch.object(ci.subprocess, 'run', side_effect=unmanaged):
            return ci.prepared_package(target, self.recipe, self.group, source or self.gui_source,
                self.output, 2, graphics_archive=self.archive if graphics else None, core_provider='cpp')

    def test_unverified_windows_linker_stops_before_dependency_install_or_build(self):
        self.probe_error = ValueError('selected linker identity invalid')
        with self.assertRaisesRegex(ValueError, 'linker identity invalid'): self.produce()
        self.sdk.install.assert_not_called()
        self.assertEqual(self.commands, [])
        self.graphics.qualified_stage.assert_not_called()

    def test_package_follows_complete_test_and_host_cleanup_and_binds_evidence(self):
        result = self.produce()
        self.assertEqual(result['path'], 'windows-x86_64.zip')
        self.assertEqual(result['manifest_path'], 'windows-x86_64.zip.json')
        self.sdk.install.assert_called_once_with(self.group, self.recipe, self.output / 'work/dependencies', '14.44.35207.0')
        self.assertEqual(self.events, ['build', 'prerequisites', 'probe', 'test', 'cleanup', 'package'])
        self.graphics.verify_archive.assert_called_once_with(self.archive)
        self.graphics.fetch.assert_not_called(); self.graphics.fetch_retained.assert_not_called()
        self.artifacts.verify.assert_called_once()
        receipt = json.loads((self.output / 'graphics-qualification.json').read_text())
        self.assertEqual(receipt['archive_sha256'], result['sha256'])
        self.assertEqual(receipt['backends'], result['backends'])
        self.assertEqual(json.loads((self.output / 'graphics.json').read_text())['cleanup'], 'removed')
        self.assertIn('work/build/gui/visual-evidence/fixture/capture.png', receipt['evidence'])
        for name, digest in receipt['evidence'].items():
            self.assertEqual(self.real_module('coverage').sha(self.output / name), digest)
        self.assertFalse(list(self.output.rglob('*.dll')))

    def test_compiler_owner_failure_stops_graphics_and_packaging(self):
        import process_tree
        for phase in ('build', 'prerequisites'):
            with self.subTest(phase=phase):
                self.output = self.root / ('failed-' + phase)
                self.compiler_failure = phase
                self.events.clear(); self.commands.clear(); self.compiler.reset_mock()
                with self.assertRaisesRegex(process_tree.ProcessTreeError, 'compiler cleanup unknown: ' + phase):
                    self.produce()
                self.assertEqual(self.compiler.run.call_count, 1 if phase == 'build' else 2)
                self.assertEqual(self.events, [] if phase == 'build' else ['build'])
                self.graphics.qualified_stage.assert_not_called()
                self.graphics.run_owned.assert_not_called()
                self.artifacts.verify.assert_not_called()
                self.assertFalse((self.output / 'graphics-qualification.json').exists())
                self.assertFalse((self.output / 'artifact.json').exists())
                self.assertNotIn('package', self.events)

    def test_absent_gui_input_and_unexpected_core_or_linux_input_never_build(self):
        for label, options in [('missing', {'graphics': False}), ('core', {'source': self.core_source}),
                               ('linux', {'target': 'linux-x86_64'})]:
            with self.subTest(case=label):
                self.output = self.root / label
                with self.assertRaisesRegex(ValueError, 'retained host graphics'): self.produce(**options)
                self.assertEqual(self.commands, [])
                self.graphics.qualified_stage.assert_not_called()
                self.assertFalse((self.output / 'artifact.json').exists())
        self.graphics.fetch.assert_not_called(); self.graphics.fetch_retained.assert_not_called()

    def test_failed_gui_assertion_never_packages_and_keeps_cleanup_receipt(self):
        self.test_error = RuntimeError('GUI assertion failed')
        with self.assertRaisesRegex(RuntimeError, 'GUI assertion failed'): self.produce()
        self.assertEqual(self.events[-1], 'cleanup')
        self.assertNotIn('package', self.events); self.artifacts.verify.assert_not_called()
        self.assertFalse((self.output / 'artifact.json').exists())
        self.assertFalse((self.output / 'graphics-qualification.json').exists())
        self.assertEqual(json.loads((self.output / 'graphics.json').read_text())['cleanup'], 'removed')

    def test_retained_or_uncertain_host_files_block_packaging_and_survive(self):
        self.cleanup = 'retained-changed'
        with self.assertRaisesRegex(ValueError, 'cleanup did not complete') as caught: self.produce()
        self.assertEqual(caught.exception.graphics_receipt['cleanup'], 'retained-changed')
        self.assertEqual(len(list(self.output.rglob('*.dll'))), 4)
        self.assertNotIn('package', self.events); self.assertFalse((self.output / 'artifact.json').exists())

    def test_pre_yield_failure_preserves_evidence_and_output(self):
        self.setup_error = RuntimeError('probe completion uncertain')
        self.setup_error.graphics_receipt = {'cleanup': 'retained-uncertain'}
        with self.assertRaisesRegex(RuntimeError, 'completion uncertain'): self.produce()
        self.assertEqual(json.loads((self.output / 'graphics.json').read_text()), self.setup_error.graphics_receipt)
        self.assertTrue((self.output / 'work/source').is_dir())
        self.assertNotIn('package', self.events); self.assertFalse((self.output / 'artifact.json').exists())

    def test_missing_rendered_capture_inventory_prevents_package(self):
        self.write_captures = False
        with self.assertRaisesRegex(ValueError, 'capture evidence'): self.produce()
        self.assertNotIn('package', self.events); self.assertFalse((self.output / 'artifact.json').exists())


class AptMechanismLifecycleTests(unittest.TestCase):
    def test_early_package_failure_retains_started_receipt_without_success(self):
        from subprocess import CalledProcessError
        helper_spec = importlib.util.spec_from_file_location('apt_ci_lifecycle', ci.ROOT / '.github/scripts/lifecycle.py')
        helper = importlib.util.module_from_spec(helper_spec); helper_spec.loader.exec_module(helper)
        import release_check
        original_write = helper.write
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with patch.object(helper, 'ROOT', root), patch.object(helper.os, 'chdir'), \
                 patch.object(release_check, 'apt_preflight'), patch.object(release_check, 'run_apt') as execute, \
                 patch.object(helper.subprocess, 'run', side_effect=CalledProcessError(1, ['build'])), \
                 patch.object(helper, 'write', side_effect=lambda path, item: original_write(root / path, item)), \
                 patch.dict(helper.os.environ, {'GITHUB_SHA': 'a' * 40}):
                with self.assertRaises(CalledProcessError): helper.main('apt-native-smoke')
                execute.assert_not_called()
            record = json.loads((root / 'build/apt-evidence/started.json').read_text())
            self.assertEqual(record, dict(operation='apt-native-smoke', target='linux-x86_64', backend='core',
                                         status='started', source_commit='a' * 40))
            self.assertFalse((root / 'build/apt-evidence/result.json').exists())


class GuiInputDeliveryTests(unittest.TestCase):
    def setUp(self):
        from types import SimpleNamespace
        import test_github_release
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name); self.group = self.root / 'group'; self.group.mkdir()
        self.files = {'gui-inputs.tar.gz': b'retained inputs', 'manifest.json': b'{"redistributable":true}', 'SHA256SUMS': b'complete group'}
        for name, data in self.files.items(): (self.group / name).write_bytes(data)
        self.remote = test_github_release.FakeGitHub()
        def verify(group, redistribution=False):
            if {p.name: p.read_bytes() for p in Path(group).iterdir()} != self.files:
                raise ValueError('fixture group differs')
            return {'redistributable': True}
        self.patch = patch.object(ci, 'gui_group_module', return_value=SimpleNamespace(verify=verify))
        self.patch.start(); self.addCleanup(self.patch.stop)
        self.identity = ci.module('coverage').sha(self.group / 'manifest.json')

    def publish(self, execute=False):
        return ci.publish_gui_group('example/project', self.group, 'a' * 40, execute=execute, transport=self.remote)

    def test_plan_never_contacts_remote_and_complete_group_roundtrips(self):
        self.assertFalse(self.publish()['execute']); self.assertEqual(self.remote.calls, [])
        self.assertFalse(self.publish(True)['reused']); self.assertIsNone(self.remote.latest)
        self.assertTrue(self.publish(True)['reused'])
        ci.fetch_gui_group('example/project', self.identity, self.root / 'fetched', self.remote)
        self.assertEqual({p.name: p.read_bytes() for p in (self.root / 'fetched').iterdir()}, self.files)

    def test_missing_partial_and_conflicting_groups_fail_without_replacement(self):
        with self.assertRaises(ValueError): ci.fetch_gui_group('example/project', self.identity, self.root / 'missing', self.remote)
        self.publish(True)
        self.remote.releases[0]['assets'].pop()
        count = len(self.remote.mutations)
        with self.assertRaisesRegex(ValueError, 'partial'): self.publish(True)
        self.assertEqual(len(self.remote.mutations), count)

    def test_replaced_asset_identity_blocks_fetch_even_with_same_bytes(self):
        self.publish(True)
        asset = ci.gui_group_names(self.identity)['manifest.json']
        self.remote.change_download = lambda: self.remote.replace_asset(asset)
        with self.assertRaisesRegex(ValueError, 'identities changed'):
            ci.fetch_gui_group('example/project', self.identity, self.root / 'fetched', self.remote)
        self.assertFalse((self.root / 'fetched').exists())

    def test_unresolved_redistribution_prevents_all_remote_mutations(self):
        from types import SimpleNamespace
        with patch.object(ci, 'gui_group_module', return_value=SimpleNamespace(verify=lambda *a, **k: (_ for _ in ()).throw(ValueError('unresolved terms')))):
            with self.assertRaisesRegex(ValueError, 'unresolved'): self.publish(True)
        self.assertEqual(self.remote.mutations, [])


class GuiInputRetirementTests(unittest.TestCase):
    def setUp(self):
        from types import SimpleNamespace
        import test_gui_source_group as fixtures
        import test_github_release
        fixture = fixtures.SourceGroupTests(); fixture.setUp(); self.addCleanup(fixture.doCleanups)
        self.fixture = fixture; self.verifier = fixtures.subject
        fixture.lock.update(license='CC0-1.0', redistribution={'approved': True, 'license_files': ['api.hpp']})
        self.verifier.archive.write_json(fixture.foundation / 'third_party/gui-boundary.lock.json', fixture.lock)
        self.old = fixture.root / 'old'; self.verifier.export(fixture.source, self.old, fixture.foundation)
        def verify(group, redistribution=False, foundation_root=None):
            return self.verifier.verify(group, redistribution, foundation_root or fixture.foundation)
        adapter = SimpleNamespace(verify=verify, MAX_TOTAL=self.verifier.MAX_TOTAL)
        mocked = patch.object(ci, 'gui_group_module', return_value=adapter); mocked.start(); self.addCleanup(mocked.stop)
        self.remote = test_github_release.FakeGitHub()
        self.publish(self.old)
        (fixture.foundation / 'gui/patches/host.patch').write_bytes(b'updated reviewed patch\n')
        self.new = fixture.root / 'new'; self.verifier.export(fixture.source, self.new, fixture.foundation)

    def publish(self, group):
        return ci.publish_gui_group('example/project', group, 'a' * 40, execute=True, transport=self.remote)

    def test_new_gui_group_verifies_old_frozen_inputs_before_retiring_exact_ids(self):
        old = {row['name']: copy.deepcopy(row) for row in self.remote.releases[0]['assets']}
        old_manifest = self.verifier.archive.read_json(self.old / 'manifest.json')
        old_manifest['upstream'] = 'https://example.invalid/other-gui'
        raw = self.verifier.archive.encoded(old_manifest); other = ci.module('github_release').sha(raw)
        path = self.fixture.root / ci.gui_group_names(other)['manifest.json']; path.write_bytes(raw)
        self.remote.upload('base', path)
        for local, name in ci.gui_group_names(other).items():
            if local == 'manifest.json': continue
            path = self.fixture.root / name; path.write_bytes((self.old / local).read_bytes()); self.remote.upload('base', path)
        partial = self.fixture.root / ci.gui_group_names('c' * 64)['SHA256SUMS']; partial.write_bytes(b'partial')
        self.remote.upload('base', partial)
        preserved = {row['name']: copy.deepcopy(row) for row in self.remote.releases[0]['assets'] if row['name'] not in old}
        result = self.publish(self.new)
        self.assertEqual(result['removed_assets'], old)
        remaining = {row['name']: row for row in self.remote.releases[0]['assets']}
        self.assertTrue(all(remaining[name] == row for name, row in preserved.items()))
        identity = self.verifier.archive.digest(self.new / 'manifest.json')
        self.assertTrue(set(ci.gui_group_names(identity).values()) <= remaining.keys())
        self.assertFalse(set(old) & remaining.keys()); self.assertEqual(self.remote.refs['base'], 'a' * 40)
        self.assertIsNone(self.remote.latest)
        first = next(call for call in self.remote.calls if call[0] == 'DELETE')
        checksum = next(row for name, row in old.items() if name.endswith('-SHA256SUMS'))
        self.assertEqual(first[1].rsplit('/', 1)[-1], str(checksum['id']))

    def test_failed_gui_publication_preserves_the_previous_complete_group(self):
        old = copy.deepcopy(self.remote.releases[0]['assets'])
        identity = self.verifier.archive.digest(self.new / 'manifest.json')
        self.remote.fail_upload = ci.gui_group_names(identity)['gui-inputs.tar.gz']
        with self.assertRaises(ValueError): self.publish(self.new)
        self.assertEqual(self.remote.releases[0]['assets'][:3], old)
        self.assertFalse(any(call[0] == 'DELETE' for call in self.remote.calls))



if __name__ == "__main__":
    unittest.main()
