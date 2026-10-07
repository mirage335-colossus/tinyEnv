import copy
from html import escape
import importlib.util
import json
from pathlib import Path
import platform
import shutil
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('release_check', Path(__file__).resolve().parents[1] / 'tools/release_check.py')
check = importlib.util.module_from_spec(spec)
spec.loader.exec_module(check)


class ReleaseCheckTests(unittest.TestCase):
    def retained_builder(self, source, provider=True):
        path = source / 'tools/build.py'
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("parser.add_argument('--core-provider', default='rust')\n" if provider else
                        "# Before hybrid support, --core-provider was not an argument.\nparser.add_argument('--full')\n")
        return path

    def test_source_provider_selection_is_explicit_and_legacy_cpp_is_preserved(self):
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary)
            self.retained_builder(source)
            for provider in ('cpp', 'rust'):
                with self.subTest(provider=provider):
                    self.assertEqual(check.source_provider_options(source, provider), ['--core-provider', provider])
            builder = self.retained_builder(source, provider=False)
            self.assertEqual(check.source_provider_options(source, 'cpp'), [])
            with self.assertRaisesRegex(ValueError, 'cannot select.*Rust'):
                check.source_provider_options(source, 'rust')
            builder.unlink()
            with self.assertRaisesRegex(ValueError, 'capability input'):
                check.source_provider_options(source, 'cpp')

    def test_isolated_interaction_receipt_cannot_omit_an_existing_application_feature(self):
        receipt = dict(composition='both', executed_compositions=['standalone', 'isolated'],
                       executed_cases=[dict(transport='hosted', composition=name) for name in ('standalone', 'isolated')],
                       checks=sorted(check.BROWSER_INTERACTION_CHECKS),
                       frame_policies={'hosted-isolated': dict(sandbox='allow-scripts', srcdoc=True)})
        check.browser_isolated_interactions(receipt, ['hosted'])
        for name in check.BROWSER_INTERACTION_CHECKS:
            broken = copy.deepcopy(receipt); broken['checks'].remove(name)
            with self.subTest(check=name), self.assertRaisesRegex(ValueError, 'feature inventory'):
                check.browser_isolated_interactions(broken, ['hosted'])
        for field, value in [('executed_cases', receipt['executed_cases'][:1]),
                             ('executed_compositions', ['isolated']), ('frame_policies', {})]:
            with self.subTest(field=field), self.assertRaises(ValueError):
                check.browser_isolated_interactions(dict(receipt, **{field: value}), ['hosted'])

    def test_renderer_qualification_retains_complete_hostile_fixture_and_observation_evidence(self):
        with tempfile.TemporaryDirectory() as temporary:
            evidence = Path(temporary)
            for name in ('browser/qualification.json', 'browser/frame.png',
                         'browser-isolation/qualification.json', 'browser-isolation/authority.json',
                         'browser-isolation/fixtures/authority/renderer_child_bundle.mjs'):
                path = evidence / name; path.parent.mkdir(parents=True, exist_ok=True); path.write_text('observed\n')
            legacy = check.browser_evidence_paths(evidence, {})
            self.assertEqual(legacy, ['browser/frame.png', 'browser/qualification.json'])
            retained = check.browser_evidence_paths(evidence, {'renderer_security': {'path': 'browser-isolation/qualification.json'}})
            self.assertIn('browser-isolation/authority.json', retained)
            self.assertIn('browser-isolation/fixtures/authority/renderer_child_bundle.mjs', retained)
            (evidence / 'browser-isolation/linked').symlink_to(evidence / 'browser/qualification.json')
            with self.assertRaisesRegex(ValueError, 'linked'):
                check.browser_evidence_paths(evidence, {'renderer_security': True})

    def test_isolated_browser_wasm_qualification_requires_schema_three_and_exact_source(self):
        import package_wasm
        manifest = dict(schema=3, source_tree_sha256='a' * 64)
        with patch.object(package_wasm, 'verify', return_value=manifest), \
                patch.object(check, 'source_tree', return_value=dict(tree_sha256='a' * 64)):
            self.assertEqual(manifest, check.browser_wasm_manifest(Path('/package'), Path('/source')))
            for broken in (dict(schema=2, source_tree_sha256='a' * 64), dict(schema=3),
                           dict(schema=3, source_tree_sha256='b' * 64)):
                with patch.object(package_wasm, 'verify', return_value=broken), self.assertRaises(ValueError):
                    check.browser_wasm_manifest(Path('/package'), Path('/source'))

    def renderer_fixture(self, root):
        import browser_bundle
        source = root / 'source'; assets = root / 'web'
        assets.mkdir()
        for name in check.BROWSER_SECURITY_ASSETS:
            (assets / name).write_text('// fixture ' + name + '\n')
        for name in ('browser_isolation_test.py', 'browser_isolation_attack.mjs', 'browser_test.py'):
            path = source / 'gui/tests' / name; path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text('# fixture\n')
        for name in ('browser_bundle.py', 'package_wasm.py', 'process_tree.py'):
            path = source / 'tools' / name; path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text('# fixture\n')
        for name in browser_bundle.CHILD_MODULES:
            imports = ''.join("import {" + browser_bundle.CHILD_EXPORTS[dependency][0] + " as input" + str(index) + "} from './" + dependency + "';\n"
                              for index, dependency in enumerate(browser_bundle.CHILD_GRAPH[name]))
            exports = ''.join('export const ' + export + '=' + str(index) + ';\n'
                              for index, export in enumerate(browser_bundle.CHILD_EXPORTS[name]))
            (assets / name).write_text(imports + exports)
        metadata = browser_bundle.assemble({name: (assets / name).read_bytes()
                                           for name in browser_bundle.CHILD_MODULES + ('style.css',)})
        (assets / 'renderer_child_bundle.mjs').write_bytes(browser_bundle.module_bytes(metadata))
        evidence = root / 'browser-isolation'; fixtures = evidence / 'fixtures'
        fixture_policies = {}
        parent_csp = "default-src 'none'; script-src 'self' 'sha256-" + metadata['CHILD_SCRIPT_SHA256'] + "'"
        for case in check.BROWSER_SECURITY_CASES:
            directory = fixtures / case; directory.mkdir(parents=True)
            for name in check.BROWSER_SECURITY_ASSETS:
                shutil.copyfile(assets / name, directory / name)
            (directory / 'harness.mjs').write_text('// retained harness\n')
            (directory / 'index.html').write_text('<meta http-equiv="Content-Security-Policy" content="' + escape(parent_csp, quote=True) + '">')
            fixture_policies[case] = dict(child_script_sha256=metadata['CHILD_SCRIPT_SHA256'], child_csp=metadata['CHILD_CSP'],
                sandbox=metadata['CHILD_SANDBOX'], protocol=metadata['CHILD_PROTOCOL'], child_inputs=metadata['CHILD_INPUTS'],
                parent_csp=parent_csp, fixture_inputs={path.name: check.digest(path) for path in directory.iterdir()})
        paths = [*source.rglob('*'), *assets.iterdir()]
        receipt = dict(schema_version=1, status='passed', engine='firefox', browser_version='153.4.0',
                       complete_security_inventory=True, executed_cases=sorted(check.BROWSER_SECURITY_CASES),
                       checks=sorted(check.BROWSER_SECURITY_CHECKS),
                       fixture_policies=fixture_policies,
                       inputs={str(path.resolve()): check.digest(path) for path in paths if path.is_file()},
                       production_child=dict(script_sha256=metadata['CHILD_SCRIPT_SHA256'], csp=metadata['CHILD_CSP'],
                                             sandbox=metadata['CHILD_SANDBOX'], protocol=metadata['CHILD_PROTOCOL'],
                                             inputs=metadata['CHILD_INPUTS']))
        return source, assets, receipt, evidence

    def test_browser_authority_receipt_requires_complete_current_byte_bound_proof(self):
        with tempfile.TemporaryDirectory() as temporary:
            source, assets, receipt, evidence = self.renderer_fixture(Path(temporary))
            self.assertEqual(receipt, check.browser_security_receipt(receipt, source, assets, 'firefox', '153.4.0', fixture_evidence=evidence))
            for field, value in [('schema_version', 0), ('status', 'failed'), ('engine', 'chromium'),
                                 ('browser_version', 'other'), ('complete_security_inventory', False),
                                 ('executed_cases', ['authority']), ('checks', []), ('fixture_policies', {})]:
                with self.subTest(field=field), self.assertRaises(ValueError):
                    check.browser_security_receipt(dict(receipt, **{field: value}), source, assets, 'firefox', '153.4.0', fixture_evidence=evidence)
            for field in ('script_sha256', 'csp', 'sandbox', 'protocol', 'inputs'):
                broken = copy.deepcopy(receipt); broken['production_child'][field] = 'wrong'
                with self.subTest(policy=field), self.assertRaisesRegex(ValueError, 'another bundle'):
                    check.browser_security_receipt(broken, source, assets, 'firefox', '153.4.0', fixture_evidence=evidence)
            for name in check.BROWSER_SECURITY_ASSETS:
                broken = copy.deepcopy(receipt); broken['inputs'].pop(str((assets / name).resolve()))
                with self.subTest(asset=name), self.assertRaisesRegex(ValueError, 'missing or stale'):
                    check.browser_security_receipt(broken, source, assets, 'firefox', '153.4.0', fixture_evidence=evidence)
            (assets / 'browser_client.mjs').write_text('// changed after qualification\n')
            with self.assertRaisesRegex(ValueError, 'missing or stale'):
                check.browser_security_receipt(receipt, source, assets, 'firefox', '153.4.0', fixture_evidence=evidence)

    def test_browser_authority_receipt_requires_complete_retained_fixture_fields_and_policies(self):
        with tempfile.TemporaryDirectory() as temporary:
            source, assets, receipt, evidence = self.renderer_fixture(Path(temporary))
            qualify = lambda value: check.browser_security_receipt(value, source, assets, 'firefox', '153.4.0', fixture_evidence=evidence)
            with self.assertRaisesRegex(ValueError, 'retained fixtures'):
                check.browser_security_receipt(receipt, source, assets, 'firefox', '153.4.0')
            broken = copy.deepcopy(receipt); broken['fixture_policies']['authority'] = {}
            with self.assertRaisesRegex(ValueError, 'policy fields'):
                qualify(broken)
            for field in receipt['fixture_policies']['authority']:
                broken = copy.deepcopy(receipt); broken['fixture_policies']['authority'].pop(field)
                with self.subTest(missing=field), self.assertRaisesRegex(ValueError, 'policy fields'):
                    qualify(broken)
                broken = copy.deepcopy(receipt); broken['fixture_policies']['authority'][field] = 'wrong'
                with self.subTest(changed=field), self.assertRaises(ValueError):
                    qualify(broken)

    def test_browser_authority_receipt_rejects_changed_extra_missing_and_linked_fixture_bytes(self):
        with tempfile.TemporaryDirectory() as temporary:
            source, assets, receipt, evidence = self.renderer_fixture(Path(temporary))
            directory = evidence / 'fixtures/authority'
            qualify = lambda: check.browser_security_receipt(receipt, source, assets, 'firefox', '153.4.0', fixture_evidence=evidence)
            for name in check.BROWSER_SECURITY_FIXTURE_FILES:
                path = directory / name; original = path.read_bytes()
                path.write_bytes(original + b'\nchanged after browser execution\n')
                with self.subTest(changed=name), self.assertRaisesRegex(ValueError, 'missing or stale'):
                    qualify()
                path.write_bytes(original)
            path = directory / 'unexpected.mjs'; path.write_text('// not executed\n')
            with self.assertRaisesRegex(ValueError, 'inventory differs'):
                qualify()
            path.unlink()
            path = directory / 'harness.mjs'; original = path.read_bytes(); path.unlink()
            with self.assertRaisesRegex(ValueError, 'inventory differs'):
                qualify()
            path.symlink_to(assets / 'browser_client.mjs')
            with self.assertRaisesRegex(ValueError, 'ordinary bounded'):
                qualify()
            path.unlink(); path.write_bytes(original)
            self.assertEqual(receipt, qualify())

    def test_browser_authority_receipt_reassembles_child_and_reads_actual_parent_policy(self):
        with tempfile.TemporaryDirectory() as temporary:
            source, assets, receipt, evidence = self.renderer_fixture(Path(temporary))
            directory = evidence / 'fixtures/authority'
            qualify = lambda value: check.browser_security_receipt(value, source, assets, 'firefox', '153.4.0', fixture_evidence=evidence)
            path = directory / 'renderer_dom.mjs'; original = path.read_bytes()
            path.write_bytes(original + b'\nconst hiddenChange=true;\n')
            broken = copy.deepcopy(receipt); broken['fixture_policies']['authority']['fixture_inputs'][path.name] = check.digest(path)
            with self.assertRaisesRegex(ValueError, 'not canonical'):
                qualify(broken)
            path.write_bytes(original)
            path = directory / 'index.html'
            path.write_text('<meta http-equiv="Content-Security-Policy" content="default-src \'none\'">')
            broken = copy.deepcopy(receipt); broken['fixture_policies']['authority']['fixture_inputs'][path.name] = check.digest(path)
            with self.assertRaisesRegex(ValueError, 'parent policy differs'):
                qualify(broken)

    def test_new_browser_source_cannot_be_qualified_by_legacy_interaction_receipt(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); marker = root / 'source/gui/host/browser_embedding.mjs'
            marker.parent.mkdir(parents=True); marker.write_text('// isolated composition\n')
            receipt = dict(schema_version=1, status='passed', engine='firefox', browser_version='153.4.0',
                           mode='hosted', checks=['editing', 'accessible-names', 'shared-geometry', 'prompt-cancel', 'capture', 'cleanup'])
            with patch.object(check.subprocess, 'run') as run, patch.object(check.c, 'load', return_value=receipt), \
                    self.assertRaisesRegex(ValueError, 'interaction inventory'):
                check.browser_check(root / 'source', root / 'web/serve.py', root / 'evidence', {}, executable=root / 'app')
            self.assertIn('--composition', run.call_args.args[0])
            self.assertIn('both', run.call_args.args[0])

    def test_browser_requires_offline_build_and_installed_packages(self):
        for installed in (False, True):
            with self.subTest(installed=installed), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                (root / 'source/tools').mkdir(parents=True)
                (root / 'source/tools/package_wasm.py').write_text('# capability marker')
                server = root / ('installed/share/software-foundation/web/serve.py' if installed else 'build/gui/web/serve.py')
                wasm = server.parent if installed else server.parent.parent
                html = (server.parent.parent / 'wasm/software-foundation-wasm.html' if installed else
                        wasm / 'wasm-package/software-foundation-wasm.html')
                html.parent.mkdir(parents=True); html.write_text('offline fixture')
                receipt = dict(schema_version=1, status='passed', engine='firefox', browser_version='test',
                               mode='wasm-offline', executed_modes=['wasm', 'offline'], offline_network_resources=False,
                               checks=['editing', 'accessible-names', 'shared-geometry', 'prompt-cancel', 'capture', 'cleanup', 'offline-no-network'])
                with patch.object(check.subprocess, 'run') as run, patch.object(check.c, 'load', return_value=receipt):
                    check.browser_check(root / 'source', server, root / 'evidence', {}, wasm=wasm)
                    command = run.call_args.args[0]
                    self.assertEqual(command[command.index('--mode') + 1], 'wasm-offline')
                    self.assertEqual(command[command.index('--offline-html') + 1], str(html))
                    for field, value in [('mode', 'wasm'), ('executed_modes', ['wasm']), ('offline_network_resources', True)]:
                        broken = dict(receipt); broken[field] = value
                        with patch.object(check.c, 'load', return_value=broken), self.assertRaises(ValueError):
                            check.browser_check(root / 'source', server, root / 'evidence', {}, wasm=wasm)
                html.unlink()
                with patch.object(check.subprocess, 'run') as run, self.assertRaisesRegex(ValueError, 'offline Wasm HTML missing'):
                    check.browser_check(root / 'source', server, root / 'evidence', {}, wasm=wasm)
                run.assert_not_called()

    def test_legacy_browser_source_retains_multi_file_mode(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            receipt = dict(schema_version=1, status='passed', engine='firefox', browser_version='test', mode='wasm',
                           checks=['editing', 'accessible-names', 'shared-geometry', 'prompt-cancel', 'capture', 'cleanup'])
            with patch.object(check.subprocess, 'run') as run, patch.object(check.c, 'load', return_value=receipt):
                check.browser_check(root / 'source', root / 'web/serve.py', root / 'evidence', {}, wasm=root / 'web')
                command = run.call_args.args[0]
                self.assertEqual(command[command.index('--mode') + 1], 'wasm')
                self.assertNotIn('--offline-html', command)

    def test_source_test_capacity_is_independent_of_compile_override(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); recipe = 'a' * 64
            self.retained_builder(root / 'work/source')
            entry = {'target': 'linux-x86_64', 'sdk_recipe': recipe, 'backends': []}
            manifest = {'source': {'archive': 'source.tar.gz'},
                        'dependencies': [{'recipe_id': recipe, 'files': {'sources.tar.gz': 'b' * 64}}]}
            with patch.object(check, 'native_target'), patch.object(check, 'verify_source_archive', return_value='snapshot'), \
                    patch.object(check, 'extract'), patch.object(check, 'source_tree', return_value='snapshot'), \
                    patch.object(check.sdk, 'install'), \
                    patch.object(check.windows_compiler, 'run', side_effect=RuntimeError('inspect build command')) as run:
                with self.assertRaisesRegex(RuntimeError, 'inspect build command'):
                    check.run_source(root, manifest, entry, root / 'work', root / 'evidence', 16)
                command = run.call_args.args[0]
                self.assertEqual(command[command.index('--build-jobs') + 1], '16')
                self.assertNotIn('--test-jobs', command)
                self.assertIn('--full', command)
                self.assertEqual(command[command.index('--core-provider') + 1], 'cpp')

    def test_rust_source_recovery_uses_exact_retained_group_and_provider(self):
        import rust_sdk
        from dependency_archive import digest
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); work = root / 'work'; rust = work / 'rust-sdk'; rust.mkdir(parents=True)
            self.retained_builder(work / 'source')
            (rust / 'rust-sdk.json').write_text('manifest fixture')
            (rust / 'rustc').write_text('compiler fixture')
            entry = {'target': 'linux-x86_64', 'sdk_recipe': 'a' * 64, 'backends': [],
                     'core_provider': 'rust', 'rust_sdk_recipe_id': 'b' * 64,
                     'dependency_recipes': ['a' * 64, 'b' * 64],
                     'rust_compiler_version': '1.63.0', 'rust_target': 'x86_64-unknown-linux-gnu',
                     'rust_sdk_manifest_sha256': digest(rust / 'rust-sdk.json'),
                     'rust_compiler_sha256': digest(rust / 'rustc')}
            manifest = {'source': {'archive': 'source.tar.gz'},
                        'dependencies': [{'recipe_id': 'a' * 64, 'files': {'sources.tar.gz': 'c' * 64}}]}
            metadata = {'compiler': {'version': '1.63.0', 'rustc': 'rustc'}}
            with patch.object(check, 'native_target'), patch.object(check, 'verify_source_archive', return_value='snapshot'), \
                    patch.object(check, 'extract'), patch.object(check, 'source_tree', return_value='snapshot'), \
                    patch.object(check.sdk, 'install'), patch.object(rust_sdk, 'install') as install, \
                    patch.object(rust_sdk, 'verify_rust_sdk', return_value=metadata), \
                    patch.object(check.windows_compiler, 'run', side_effect=RuntimeError('inspect recovered command')) as run:
                with self.assertRaisesRegex(RuntimeError, 'inspect recovered command'):
                    check.run_source(root, manifest, entry, work, root / 'evidence', 2, recovery=True)
                command = run.call_args.args[0]
                self.assertIn('--core-provider', command)
                self.assertEqual(command[command.index('--core-provider') + 1], 'rust')
                self.assertEqual(command.count('--core-provider'), 1)
                self.assertEqual(command[command.index('--rust-sdk') + 1], str(rust))
                self.assertNotIn('--dependency-group', command)
                install.assert_called_once_with(root / 'dependencies' / ('b' * 64), 'b' * 64, rust)
                entry['rust_compiler_sha256'] = 'f' * 64
                with self.assertRaisesRegex(ValueError, 'delivered compiler identity'):
                    check.run_source(root, manifest, entry, work, root / 'evidence', 2, recovery=True)

    def test_windows_source_consumes_verified_file_version_and_rejects_bad_probe(self):
        import sdk_windows
        import windows_toolchain
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); entry = {'target':'windows-x86_64','sdk_recipe':'a'*64,'backends':[]}
            self.retained_builder(root / 'work/source')
            source_name = 'sdk-' + entry['sdk_recipe'] + '-sources.tar.gz'
            group = root / 'dependencies' / entry['sdk_recipe']; group.mkdir(parents=True)
            (group / source_name).write_text('full-group source fixture')
            manifest = {'source':{'archive':'source.tar.gz'}, 'dependencies':[{'recipe_id':entry['sdk_recipe'], 'files':{source_name:'b'*64}}]}
            with patch.object(check,'native_target'), patch.object(check,'verify_source_archive',return_value='snapshot'), \
                 patch.object(check,'extract'), patch.object(check,'source_tree',return_value='snapshot'), \
                 patch.object(windows_toolchain,'inspect_selected_linker',return_value={'version':'14.44.35207.0'}) as probe, \
                 patch.object(sdk_windows,'install',side_effect=RuntimeError('stop after verified version')) as install:
                with self.assertRaisesRegex(RuntimeError,'stop after verified version'):
                    check.run_source(root,manifest,entry,root/'work',root/'evidence',2)
                install.assert_called_once_with(root/'dependencies'/entry['sdk_recipe'],entry['sdk_recipe'],
                    root/'work/windows-dependencies','14.44.35207.0')
                install.reset_mock();probe.side_effect=ValueError('selected linker identity failed')
                with self.assertRaisesRegex(ValueError,'identity failed'):
                    check.run_source(root,manifest,entry,root/'work',root/'evidence',2)
                install.assert_not_called()

    def test_windows_source_stages_only_after_build_and_saves_final_cleanup(self):
        from contextlib import contextmanager
        from types import SimpleNamespace
        import json
        import windows_graphics
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); work = root / 'work'; work.mkdir()
            evidence = root / 'evidence'; evidence.mkdir()
            command = ['python', 'tools/build.py', 'test', 'release', '--full', '--junit', 'report.xml',
                       '--gui-backends', 'terminal,framebuffer,fltk,rev,sdl,hosted-web']
            events = []
            @contextmanager
            def staging(archive, directories, **options):
                self.assertEqual(events, ['build', 'gui-prerequisites'])
                self.assertEqual(directories, [work / 'build/gui'])
                self.assertEqual(options['protected_roots'], (root / 'sdk',))
                value = SimpleNamespace(environment={'GALLIUM_DRIVER': 'llvmpipe'},
                    receipt={'cleanup': 'pending'}, probe_receipt={'renderer': 'verified fixture'})
                try:
                    yield value
                finally:
                    events.append('cleanup'); value.receipt['cleanup'] = 'removed'
            def build(argv, **options):
                if argv[0] == 'python':
                    self.assertEqual(argv[2], 'build')
                    self.assertNotIn('--full', argv); self.assertNotIn('--junit', argv)
                    self.assertIn(command[-1], argv); events.append('build')
                else:
                    self.assertIn('foundation-gui-tests', argv); events.append('gui-prerequisites')
            def execute(argv, cwd, log, **options):
                self.assertEqual(argv, command)
                self.assertEqual(options['environment']['GALLIUM_DRIVER'], 'llvmpipe')
                self.assertFalse((evidence / 'windows-graphics/graphics.json').exists())
                log.write_bytes(b'unchanged full tests completed'); events.append('tests')
            with patch.object(windows_graphics, 'verify_archive'), \
                    patch.object(windows_graphics, 'qualified_stage', staging), \
                    patch.object(windows_graphics, 'run_owned', side_effect=execute), \
                    patch.object(check.windows_compiler, 'run', side_effect=build):
                result = check.run_windows_source(command, root / 'retained.7z', work, evidence, (root / 'sdk',), 2)
            self.assertEqual(events, ['build', 'gui-prerequisites', 'tests', 'cleanup'])
            self.assertEqual(json.loads((evidence / 'windows-graphics/graphics.json').read_text())['cleanup'], 'removed')
            self.assertEqual(result['graphics_sha256'], check.digest(evidence / 'windows-graphics/graphics.json'))

    def test_windows_graphics_is_required_only_for_actual_rev_runtime(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); manifest, unused = self.fixture(root)
            manifest['artifacts'][0].update(target='windows-x86_64', backends=['terminal', 'rev'])
            with patch.object(check.release, 'verify_selection', return_value=manifest), \
                    patch.object(check, 'native_target'), patch.object(check.artifact, 'verify') as verify:
                for scope, backend, options in [('source', 'terminal', {}), ('recovery', 'rev', {}),
                    ('archive', 'rev', {}), ('archive', 'terminal', {'windows_graphics_archive': root / 'retained.7z'})]:
                    with self.assertRaisesRegex(ValueError, 'retained graphics'):
                        check.check(root, 'windows-x86_64', backend, scope, root / 'absent', browser_options=options)
                verify.assert_not_called()
                def performed(*args, **options):
                    dest = options['windows_graphics_evidence']; dest.mkdir()
                    (dest / 'graphics.json').write_text('{"cleanup":"removed"}')
                    return {'windows_graphics': {'checks': 'probe-and-smoke'}}
                verify.side_effect = performed
                result = check.check(root, 'windows-x86_64', 'rev', 'archive', root / 'evidence',
                                     browser_options={'windows_graphics_archive': root / 'retained.7z'})
                self.assertIn('windows-graphics/graphics.json', result['evidence'])
                self.assertEqual(result['details']['windows_graphics']['checks'], 'probe-and-smoke')

    def test_visual_capture_retention_rejects_incomplete_or_unexpected_output(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); build = root / 'build'; source = build / 'gui/visual-evidence/run'
            source.mkdir(parents=True); evidence = root / 'evidence'; evidence.mkdir()
            for name in ['qualification.json', 'native.png', 'framebuffer.ppm']:
                (source / name).write_bytes(name.encode())
            bad = source / 'opengl32.dll'; bad.write_bytes(b'not a capture')
            with self.assertRaisesRegex(ValueError, 'capture evidence'):
                check.retain_native_visuals(build, evidence)
            bad.unlink(); (source / 'framebuffer.ppm').unlink()
            with self.assertRaisesRegex(ValueError, 'capture evidence'):
                check.retain_native_visuals(build, evidence)
            (source / 'framebuffer.ppm').write_bytes(b'pixels fixture')
            inventory = check.retain_native_visuals(build, evidence)
            self.assertEqual(len(inventory), 3)
            for name, digest in inventory.items():
                self.assertEqual(digest, check.digest(evidence / name))
                self.assertEqual((evidence / name).read_bytes(), (source / Path(name).name).read_bytes())

    def test_qualification_workspace_retains_uncertain_writers_and_cleans_safe_failure(self):
        import json
        from process_tree import ProcessTreeError
        import windows_graphics
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); evidence = root / 'evidence'; evidence.mkdir()
            safe = None
            with self.assertRaisesRegex(ValueError, 'ordinary failure'):
                with check.qualification_work(evidence) as safe:
                    (safe / 'output').write_bytes(b'complete')
                    raise ValueError('ordinary failure')
            self.assertFalse(safe.exists())
            for kind in ('uncertain', 'changed'):
                case = evidence / kind; case.mkdir()
                error = ProcessTreeError('writer completion unconfirmed') if kind == 'uncertain' else windows_graphics.GraphicsError('changed owned file')
                if kind == 'changed': error.graphics_receipt = {'cleanup': 'preserved-changed-files'}
                with self.assertRaises(type(error)):
                    with check.qualification_work(case) as retained:
                        (retained / 'output').write_bytes(b'preserve for reconciliation')
                        raise error
                self.assertEqual((retained / 'output').read_bytes(), b'preserve for reconciliation')
                self.assertEqual(json.loads((case / 'retained-work.json').read_text())['workspace'], str(retained))
                # This fixture has no child or other writer; its owned output is reconciled.
                check.shutil.rmtree(retained)

    def test_grouped_audit_binds_complete_artifact_and_rejects_subset(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);manifest,unused=self.fixture(root)
            entry=manifest['artifacts'][0];entry.update(target='linux-x86_64',backends=['fltk','sdl'])
            identity=dict(schema_version=1,plan='d'*64,subject=dict(source_sha256=manifest['source']['sha256'],
                inventory_sha256=check.digest(root/'release.json'),configuration_sha256='c'*64),
                execution='abi-fltk',checks=['abi-fltk','abi-sdl'],backends=['fltk','sdl'],target='linux-x86_64',
                environment='fixture',scope='abi',run_id='run',attempt=1,host=check.c.host_identity())
            with patch.object(check.release,'verify_selection',return_value=manifest),patch.object(check,'native_target'), \
                 patch.object(check.artifact,'inspect_archive'),patch.object(check,'audit',return_value={'audited':'all'}) as audit:
                wrong=copy.deepcopy(identity);wrong['backends']=['fltk']
                with self.assertRaisesRegex(ValueError,'complete native artifact'):
                    check.check(root,'linux-x86_64','fltk','abi',root/'rejected',execution=wrong)
                audit.assert_not_called();self.assertFalse((root/'rejected').exists())
                result=check.check(root,'linux-x86_64','fltk','abi',root/'evidence',execution=identity,receipt_name='abi-fltk.qualification.json')
                self.assertEqual(result['details']['execution'],identity)
                self.assertEqual(result['evidence']['execution.json'],check.digest(root/'evidence/execution.json'))
                audit.assert_called_once()

    def browser_fixture(self, root):
        import ci_plan
        import json
        subject = dict(source_sha256='a' * 64, inventory_sha256='b' * 64)
        plan = check.c.freeze(dict(schema_version=1, mode='release',
            subject=dict(subject, configuration_sha256='c' * 64), inputs={}, checks=[dict(
                id='browser-archive', target='linux-x86_64', backend='hosted-web', scope='archive',
                environment='debian-12', required=True, argv=['fixture'], timeout_seconds=5,
                warning_seconds=4, expected_tests=[])]))
        selection = ci_plan.browser_prerequisite('linux-x86_64', 'debian-12', 'hosted-web')
        receipt = dict(schema_version=1, selection=selection,
            signing_key_fingerprint=None,
            installed=[dict(package='firefox-esr', version='153.4.0+build1', architecture='amd64', policy='official origin fixture')],
            browser_version='Mozilla Firefox 153.4.0esr', plan=plan['id'], check='browser-archive', run_id='123', attempt=2)
        plan_path = root / 'plan.json'; plan_path.write_text(json.dumps(plan))
        receipt_path = root / 'browser.json'; receipt_path.write_text(json.dumps(receipt))
        options = dict(browser_prerequisite=receipt_path, browser_prerequisite_plan=plan_path,
                       browser='firefox', firefox='/usr/bin/firefox-esr')
        host = dict(system='Linux', machine='x86_64', distribution='debian-12')
        environment = dict(FOUNDATION_PLAN_ID=plan['id'], FOUNDATION_CHECK_ID='browser-archive',
                           FOUNDATION_RUN_ID='123', FOUNDATION_RUN_ATTEMPT='2')
        return subject, receipt, options, host, environment

    def test_browser_prerequisite_is_bound_to_actual_case_and_preserved(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            subject, receipt, options, host, environment = self.browser_fixture(root)
            with patch.object(check.c, 'host_identity', return_value=host), patch.dict(check.os.environ, environment):
                state = check.browser_prerequisite_snapshot(options, 'linux-x86_64', 'hosted-web', 'archive', subject)
            evidence = root / 'evidence'; (evidence / 'browser').mkdir(parents=True)
            details = dict(browser=dict(status='passed', engine='firefox', browser_version='153.4.0'))
            check.bind_browser_prerequisite(state, details, evidence)
            self.assertEqual((evidence / 'browser/prerequisite.json').read_bytes(), options['browser_prerequisite'].read_bytes())
            self.assertEqual(details['browser_prerequisite']['sha256'], check.digest(evidence / 'browser/prerequisite.json'))
            self.assertEqual(details['browser_prerequisite']['plan'], receipt['plan'])

    def test_browser_prerequisite_ignores_conflicting_provider_environment(self):
        with tempfile.TemporaryDirectory() as temporary:
            subject, receipt, options, host, environment = self.browser_fixture(Path(temporary))
            inherited = dict(environment, CHECK='wrong-check', GITHUB_RUN_ID='wrong-run', GITHUB_RUN_ATTEMPT='999')
            with patch.object(check.c, 'host_identity', return_value=host), patch.dict(check.os.environ, inherited, clear=True):
                before = dict(check.os.environ)
                state = check.browser_prerequisite_snapshot(options, 'linux-x86_64', 'hosted-web', 'archive', subject)
                self.assertEqual(state['data'], receipt)
                self.assertEqual(dict(check.os.environ), before)

    def test_browser_prerequisite_requires_complete_exact_neutral_execution_context(self):
        with tempfile.TemporaryDirectory() as temporary:
            subject, _, options, host, environment = self.browser_fixture(Path(temporary))
            legacy = dict(CHECK='browser-archive', GITHUB_RUN_ID='123', GITHUB_RUN_ATTEMPT='2')
            invalid = [legacy]
            for key in environment:
                missing = dict(environment); del missing[key]; invalid.append(dict(legacy, **missing))
                wrong = dict(environment); wrong[key] = 'other'; invalid.append(dict(legacy, **wrong))
            invalid.append(dict(environment, FOUNDATION_RUN_ATTEMPT='02'))
            with patch.object(check.c, 'host_identity', return_value=host):
                for values in invalid:
                    with self.subTest(values=values), patch.dict(check.os.environ, values, clear=True):
                        with self.assertRaisesRegex(ValueError, 'another frozen case or attempt'):
                            check.browser_prerequisite_snapshot(options, 'linux-x86_64', 'hosted-web', 'archive', subject)

    def test_host_browser_receipt_selects_exact_native_bytes_and_rechecks_after_assertions(self):
        import ci_plan,json
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);subject,receipt,options,host,environment=self.browser_fixture(root)
            spec=check.c.load(options['browser_prerequisite_plan']);del spec['id']
            spec['checks'][0]['environment']='ubuntu-24.04';frozen=check.c.freeze(spec)
            options['browser_prerequisite_plan'].write_text(json.dumps(frozen));receipt['plan']=frozen['id']
            environment['FOUNDATION_PLAN_ID']=frozen['id']
            receipt['selection']=ci_plan.browser_prerequisite('linux-x86_64','ubuntu-24.04','hosted-web')
            native=root/'firefox-native';native.write_bytes(b'inspected executable')
            observed=dict(package='firefox',version=receipt['browser_version'],architecture='amd64',policy='preinstalled host prerequisite',
                          executable=str(native),files={str(native):check.digest(native)})
            receipt['installed']=[observed];options['browser_prerequisite'].write_text(json.dumps(receipt))
            options['firefox']='/usr/bin/firefox';host['distribution']='ubuntu-24.04'
            with patch.object(check.c,'host_identity',return_value=host),patch.dict(check.os.environ,environment), \
                 patch.object(ci_plan,'inspect_host_firefox',return_value=observed):
                state=check.browser_prerequisite_snapshot(options,'linux-x86_64','hosted-web','archive',subject)
            self.assertEqual(options['firefox'],str(native))
            details=dict(browser=dict(status='passed',engine='firefox',browser_version='153.4.0'))
            evidence=root/'evidence';(evidence/'browser').mkdir(parents=True)
            native.write_bytes(b'changed after browser assertions')
            with self.assertRaisesRegex(ValueError,'executable changed'):
                check.bind_browser_prerequisite(state,details,evidence)
            self.assertFalse((evidence/'browser/prerequisite.json').exists())

    def test_host_chromium_receipt_rechecks_selected_driver_bytes(self):
        import ci_plan,json
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);subject,receipt,options,host,environment=self.browser_fixture(root)
            spec=check.c.load(options['browser_prerequisite_plan']);del spec['id']
            spec['checks'][0].update(target='browser-wasm32',backend='wasm',environment='chromium')
            frozen=check.c.freeze(spec);options['browser_prerequisite_plan'].write_text(json.dumps(frozen))
            environment['FOUNDATION_PLAN_ID']=frozen['id']
            receipt.update(plan=frozen['id'],selection=ci_plan.browser_prerequisite('browser-wasm32','chromium','wasm'),
                           browser_version='Google Chrome 154.0.1.2')
            observed=[]
            for package,version in (('google-chrome',receipt['browser_version']),('chromedriver','ChromeDriver 154.0.1.2')):
                binary=root/package;binary.write_bytes(package.encode())
                observed.append(dict(package=package,version=version,architecture='amd64',policy='host',
                    executable=str(binary),files={str(binary):check.digest(binary)}))
            receipt['installed']=observed;options['browser_prerequisite'].write_text(json.dumps(receipt))
            options.update(browser='chromium',browser_executable='/usr/bin/google-chrome',driver='/usr/bin/chromedriver')
            host['distribution']='ubuntu-24.04'
            with patch.object(check.c,'host_identity',return_value=host),patch.dict(check.os.environ,environment), \
                    patch.object(ci_plan,'inspect_host_chromium',return_value=observed):
                with self.assertRaisesRegex(ValueError,'selected driver'):
                    check.browser_prerequisite_snapshot(dict(options,driver='/unrelated/driver'),'browser-wasm32','wasm','archive',subject)
                state=check.browser_prerequisite_snapshot(options,'browser-wasm32','wasm','archive',subject)
            self.assertEqual(options['driver'],str(root/'chromedriver'))
            self.assertEqual(options['browser_executable'],str(root/'google-chrome'))
            evidence=root/'evidence';(evidence/'browser').mkdir(parents=True)
            (root/'chromedriver').write_bytes(b'changed driver')
            with self.assertRaisesRegex(ValueError,'executable changed'):
                check.bind_browser_prerequisite(state,dict(browser=dict(status='passed',engine='chromium',browser_version='154.0.1.2')),evidence)
            self.assertFalse((evidence/'browser/prerequisite.json').exists())

    def test_browser_prerequisite_rejects_wrong_scope_attempt_host_and_package(self):
        import json
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            subject, original, options, host, environment = self.browser_fixture(root)
            mutations = [lambda r: r.update(schema_version=True), lambda r: r.update(plan='d' * 64), lambda r: r.update(check='other'),
                         lambda r: r.update(run_id='124'), lambda r: r.update(attempt=1),
                         lambda r: r.update(attempt=True), lambda r: r['selection'].update(architecture='arm64'),
                         lambda r: r.update(signing_key_fingerprint='wrong'), lambda r: r.update(installed=[]),
                         lambda r: r['installed'][0].update(package='chromium'),
                         lambda r: r['installed'][0].update(architecture='arm64')]
            with patch.object(check.c, 'host_identity', return_value=host), patch.dict(check.os.environ, environment):
                for mutate in mutations:
                    receipt = copy.deepcopy(original); mutate(receipt)
                    options['browser_prerequisite'].write_text(json.dumps(receipt))
                    with self.assertRaises(ValueError):
                        check.browser_prerequisite_snapshot(options, 'linux-x86_64', 'hosted-web', 'archive', subject)
                options['browser_prerequisite'].write_text(json.dumps(original))
                for backend, scope in [('core', 'archive'), ('hosted-web', 'apt'), ('hosted-web', 'source')]:
                    with self.assertRaises(ValueError):
                        check.browser_prerequisite_snapshot(options, 'linux-x86_64', backend, scope, subject)
                with self.assertRaises(ValueError):
                    check.browser_prerequisite_snapshot(dict(options, firefox='unrelated'), 'linux-x86_64', 'hosted-web', 'archive', subject)
                host['distribution'] = 'ubuntu-24.04'
                with self.assertRaises(ValueError):
                    check.browser_prerequisite_snapshot(options, 'linux-x86_64', 'hosted-web', 'archive', subject)

    def test_browser_prerequisite_mutation_or_different_runtime_cannot_pass(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            subject, receipt, options, host, environment = self.browser_fixture(root)
            with patch.object(check.c, 'host_identity', return_value=host), patch.dict(check.os.environ, environment):
                state = check.browser_prerequisite_snapshot(options, 'linux-x86_64', 'hosted-web', 'archive', subject)
            evidence = root / 'evidence'; (evidence / 'browser').mkdir(parents=True)
            for browser in (dict(status='failed', engine='firefox', browser_version='153.4.0'),
                            dict(status='passed', engine='chromium', browser_version='153.4.0'),
                            dict(status='passed', engine='firefox', browser_version='153.5.0')):
                with self.assertRaises(ValueError): check.bind_browser_prerequisite(state, dict(browser=browser), evidence)
            details = dict(browser=dict(status='passed', engine='firefox', browser_version='153.4.0'))
            for path in (state['path'], state['plan_path']):
                before = path.read_bytes(); path.write_bytes(before + b'\n')
                with self.assertRaisesRegex(ValueError, 'changed during'):
                    check.bind_browser_prerequisite(state, details, evidence)
                path.write_bytes(before)
            self.assertFalse((evidence / 'browser/prerequisite.json').exists())

    def fixture(self, root):
        machine = {'amd64': 'x86_64', 'arm64': 'aarch64'}.get(platform.machine().lower(), platform.machine().lower())
        target = platform.system().lower() + '-' + machine
        (root / 'release.json').write_text('{}')
        entry = {'target': target, 'backends': [], 'archive': 'app.tar.gz', 'manifest': 'app.json', 'sha256': 'b' * 64}
        return {'source': {'sha256': 'a' * 64}, 'artifacts': [entry]}, target

    @unittest.skipUnless(platform.system() == 'Linux', 'native Linux descendant fixture')
    def test_apt_timeout_stops_descendant_before_cleanup(self):
        import sys
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); pid = root / 'child.pid'
            script = ("import os,subprocess,sys,time; "
                      "child=subprocess.Popen([sys.executable,'-c','import time;time.sleep(60)'],start_new_session=True); "
                      "open(sys.argv[1],'w').write(str(child.pid)); print('started',flush=True); time.sleep(60)")
            with self.assertRaises(check.AptCommandError) as caught:
                check.apt_command([sys.executable, '-c', script, str(pid)], root, timeout=1)
            self.assertTrue(caught.exception.writers_stopped)
            self.assertIn(b'started', caught.exception.output)
            self.assertFalse(Path('/proc/' + pid.read_text()).exists())

    def test_failed_apt_download_cleans_with_its_isolated_index_and_preserves_primary_error(self):
        from contextlib import ExitStack
        from subprocess import CompletedProcess
        from unittest.mock import Mock
        from types import ModuleType
        import sys
        import apt_repo
        import http.server
        import threading
        with tempfile.TemporaryDirectory() as temporary, ExitStack() as stack:
            root = Path(temporary); work = root / 'work'; evidence = root / 'evidence'
            commands = []
            receipt = dict(package='fixture.deb', version='1.0', payload={})
            def repository(receipts, output, *args):
                output.mkdir(); (output / 'archive-keyring.gpg').write_bytes(b'fixture public key')
            def executed(argv, cwd):
                commands.append(argv)
                if 'install' in argv:
                    return CompletedProcess(argv, 100, b'404 injected download failure')
                if 'purge' in argv:
                    self.assertIn('Dir::Etc::sourcelist=' + str(work / 'client-valid1/source.list'), argv)
                    return CompletedProcess(argv, 0, b'package is not installed, so not removed')
                return CompletedProcess(argv, 0, b'fixture command completed')
            def unmanaged(argv, **options):
                self.assertIn(argv[0], ('dpkg-query', 'gpg', 'gpgconf'))
                return CompletedProcess(argv, 1 if argv[0] == 'dpkg-query' else 0, b'fixture output')
            stack.enter_context(patch.object(check, 'apt_preflight'))
            stack.enter_context(patch.object(check, 'apt_command', side_effect=executed))
            stack.enter_context(patch.object(check.subprocess, 'run', side_effect=unmanaged))
            stack.enter_context(patch.object(apt_repo, 'package', return_value=receipt))
            stack.enter_context(patch.object(apt_repo, 'fingerprint', return_value='A' * 40))
            stack.enter_context(patch.object(apt_repo, 'repository', side_effect=repository))
            stack.enter_context(patch.object(apt_repo, 'verify_repository', return_value={}))
            server = Mock(); server.server_address = ('127.0.0.1', 12345)
            raw_socket = server.socket
            stack.enter_context(patch.object(http.server, 'ThreadingHTTPServer', return_value=server))
            # This case tests failed-download cleanup, with all transport mocked.
            # Slim offline SDK Python need not load its optional SSL extension.
            ssl = ModuleType('ssl')
            ssl.PROTOCOL_TLS_SERVER = object()
            context = Mock(spec=['load_cert_chain', 'wrap_socket'])
            ssl.SSLContext = Mock(return_value=context)
            stack.enter_context(patch.dict(sys.modules, {'ssl': ssl}))
            thread = Mock(); thread.is_alive.return_value = False
            stack.enter_context(patch.object(threading, 'Thread', return_value=thread))
            entry = dict(target='linux-x86_64', archive='app.tar.gz', manifest='app.json', sha256='b' * 64)
            with self.assertRaisesRegex(ValueError, 'unexpected outcome'):
                check.run_apt(root, entry, 'core', work, evidence)
            ssl.SSLContext.assert_called_once_with(ssl.PROTOCOL_TLS_SERVER)
            context.load_cert_chain.assert_called_once_with(work / 'ca.pem', work / 'tls.key')
            context.wrap_socket.assert_called_once_with(raw_socket, server_side=True)
            self.assertEqual(sum('install' in argv for argv in commands), 1)
            self.assertEqual(sum('purge' in argv for argv in commands), 1)
            self.assertIn(b'404 injected download failure', (evidence / 'apt.log').read_bytes())
            server.shutdown.assert_called_once(); server.server_close.assert_called_once()
            thread.join.assert_called_once()
            self.assertFalse((evidence / 'qualification.json').exists())

    def test_apt_cleanup_fixture_runs_without_optional_ssl_extension(self):
        import subprocess
        import sys
        script = (
            "import sys, unittest\n"
            "sys.modules.pop('ssl', None)\n"
            "sys.modules['_ssl'] = None\n"
            "try:\n import ssl\n"
            "except ImportError:\n pass\n"
            "else:\n raise SystemExit('SSL prerequisite unexpectedly available')\n"
            "sys.path.insert(0, sys.argv[1])\n"
            "from test_release_check import ReleaseCheckTests\n"
            "case = ReleaseCheckTests('test_failed_apt_download_cleans_with_its_isolated_index_and_preserves_primary_error')\n"
            "result = unittest.TestResult()\n"
            "case.run(result)\n"
            "if not result.wasSuccessful() or result.testsRun != 1 or result.skipped:\n"
            " raise SystemExit(str(result.errors + result.failures + result.skipped))\n"
            "print('mocked APT cleanup passed without optional SSL extension')\n")
        result = subprocess.run([sys.executable, '-I', '-B', '-c', script, str(Path(__file__).resolve().parent)],
                                capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(result.stdout.strip(), 'mocked APT cleanup passed without optional SSL extension')

    def test_apt_refuses_ordinary_host_before_any_package_command(self):
        with patch.object(check, 'native_target'), patch.dict(check.os.environ, {}, clear=True), \
                patch.object(check.subprocess, 'run') as run:
            with self.assertRaisesRegex(ValueError, 'disposable root container'):
                check.apt_preflight('linux-x86_64')
            run.assert_not_called()

    def test_apt_receipt_requires_complete_adapter_and_binds_log(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); manifest, target = self.fixture(root)
            def performed(candidate, entry, backend, work, evidence):
                (evidence / 'apt.log').write_bytes(b'actual adapter log fixture')
                return {'archive_sha256': entry['sha256'], 'checks': ['install', 'upgrade', 'purge']}
            with patch.object(check.release, 'verify_selection', return_value=manifest), \
                    patch.object(check, 'run_apt', side_effect=performed) as apt:
                result = check.check(root, target, 'core', 'apt', root / 'evidence')
                self.assertEqual(apt.call_args.args[2], 'core')
                self.assertEqual(result['evidence'], {'apt.log': check.digest(root / 'evidence/apt.log')})
            with patch.object(check.release, 'verify_selection', return_value=manifest), \
                    patch.object(check, 'run_apt', side_effect=ValueError('install failed')):
                with self.assertRaisesRegex(ValueError, 'install failed'):
                    check.check(root, target, 'core', 'apt', root / 'failed')
                self.assertFalse((root / 'failed/qualification.json').exists())

    def test_core_empty_gui_inventory_is_an_exact_scope(self):
        value = {'artifacts': [{'target': 'linux-x86_64', 'backends': []}]}
        self.assertIs(check.select(value, 'linux-x86_64', 'core'), value['artifacts'][0])
        for target, backend in [('linux-aarch64', 'core'), ('linux-x86_64', 'fltk')]:
            with self.assertRaises(ValueError):
                check.select(value, target, backend)
        value['artifacts'] *= 2
        with self.assertRaises(ValueError):
            check.select(value, 'linux-x86_64', 'core')

    def test_exact_archive_receipt_and_immutable_attempt(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            manifest, target = self.fixture(root)
            with patch.object(check.release, 'verify_selection', return_value=manifest) as verify, patch.object(check.artifact, 'verify') as runtime:
                result = check.check(root, target, 'core', 'archive', root / 'evidence')
                self.assertEqual(verify.call_count, 2)
                self.assertEqual(runtime.call_args.kwargs['backend'], 'core')
                self.assertTrue(runtime.call_args.kwargs['runtime_only'])
                self.assertEqual(result['source_sha256'], manifest['source']['sha256'])
                self.assertEqual(result['inventory_sha256'], check.digest(root / 'release.json'))
                self.assertEqual(result['host'], check.c.host_identity())
                with self.assertRaisesRegex(ValueError, 'new attempt'):
                    check.check(root, target, 'core', 'archive', root / 'evidence')

    def test_candidate_mutation_or_runtime_failure_never_leaves_pass_receipt(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            manifest, target = self.fixture(root)
            def mutate(*args, **kwargs):
                (root / 'release.json').write_text('{"changed":true}')
            with patch.object(check.release, 'verify_selection', return_value=manifest), patch.object(check.artifact, 'verify', side_effect=mutate):
                with self.assertRaisesRegex(ValueError, 'changed'):
                    check.check(root, target, 'core', 'archive', root / 'evidence')
                self.assertFalse((root / 'evidence/qualification.json').exists())
            with patch.object(check.release, 'verify_selection', return_value=manifest), patch.object(check.artifact, 'verify', side_effect=ValueError('runtime failed')):
                with self.assertRaisesRegex(ValueError, 'runtime failed'):
                    check.check(root, target, 'core', 'archive', root / 'failure')
                self.assertFalse((root / 'failure/qualification.json').exists())

    def test_native_scope_rejects_wrong_os_architecture_and_browser(self):
        with patch.object(check.platform, 'system', return_value='Linux'), patch.object(check.platform, 'machine', return_value='x86_64'):
            check.native_target('linux-x86_64')
            for target in ('linux-aarch64', 'windows-x86_64', 'browser-wasm32'):
                with self.assertRaises(ValueError):
                    check.native_target(target)


if __name__ == '__main__':
    unittest.main()
