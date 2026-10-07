import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import windows_toolchain as toolchain
import unittest

spec = importlib.util.spec_from_file_location("builder", Path(__file__).resolve().parents[1] / "tools/build.py")
builder = importlib.util.module_from_spec(spec)
spec.loader.exec_module(builder)


class BuildTests(unittest.TestCase):
    def test_explicit_cpp_never_discovers_rust_and_rejects_unused_rust_sdk(self):
        from unittest.mock import patch
        import source_identity
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            with patch.object(builder, 'ROOT', root), patch.object(builder, 'run') as run, \
                    patch.object(builder, 'cache_identity', return_value={}), \
                    patch.object(builder, 'native_rust_identity') as native, \
                    patch.object(builder, 'rust_sdk_identity') as verify, \
                    patch.object(source_identity, 'source_tree', return_value={}):
                self.assertEqual(builder.main(['build', '--core-provider', 'cpp', '--configure-only']), 0)
                configure = run.call_args.args[0]
                self.assertIn('-DFOUNDATION_CORE_PROVIDER=cpp', configure)
                self.assertIn('-DFOUNDATION_RUST_SDK_ROOT=', configure)
                identity = json.loads((root / 'build/dev/wrapper-identity.json').read_text())
                self.assertEqual(identity['core_provider'], 'cpp')
                self.assertIsNone(identity['rust_sdk'])
                with self.assertRaises(SystemExit):
                    builder.main(['build', '--core-provider', 'cpp', '--rust-sdk', str(root / 'absent')])
                native.assert_not_called(); verify.assert_not_called()

    def test_default_native_rust_fails_with_actionable_missing_tools_without_configure(self):
        from unittest.mock import patch
        import rust_build
        with patch.object(builder.sys, 'platform', 'linux'), patch.object(builder, 'run') as run, \
                patch.object(rust_build, 'select_native_tools', side_effect=ValueError('missing rustc')):
            with self.assertRaisesRegex(ValueError, 'missing rustc.*--rust-sdk.*--core-provider cpp'):
                builder.main(['build', '--configure-only'])
            run.assert_not_called()

    def test_default_rust_is_selected_with_retained_tools_for_every_profile(self):
        from unittest.mock import patch
        import source_identity
        for arguments, preset, portable in (
                (['build'], 'dev', False), (['test', 'dev'], 'dev', False),
                (['build', 'release'], 'release', False), (['test', 'release'], 'release', False),
                (['build', 'asan'], 'asan', False), (['test', 'asan'], 'asan', False),
                (['package'], 'release', False), (['portable-package'], 'release', True)):
            with self.subTest(arguments=arguments), tempfile.TemporaryDirectory() as directory:
                root = Path(directory).resolve(); rust = root / 'rust'; rust.mkdir()
                def execute(command, **kwargs):
                    if command[0] == 'cpack':
                        packages = root / ('build/' + preset + '-rust-sdk' + ('-portable' if portable else '')) / 'packages'
                        packages.mkdir(parents=True)
                        (packages / 'example.tar.gz').write_bytes(b'archive fixture')
                with patch.object(builder, 'ROOT', root), patch.object(builder, 'run', side_effect=execute) as run, \
                        patch.object(builder, 'cache_identity', return_value={}), \
                        patch.object(builder, 'native_rust_identity') as native, \
                        patch.object(builder, 'rust_sdk_identity', return_value='a' * 64) as verify, \
                        patch.object(source_identity, 'source_tree', return_value={}):
                    self.assertEqual(builder.main([*arguments, '--rust-sdk', str(rust)]), 0)
                configure = run.call_args_list[0].args[0]
                self.assertIn('-DFOUNDATION_CORE_PROVIDER=rust', configure)
                self.assertIn('-DFOUNDATION_PORTABLE=' + ('ON' if portable else 'OFF'), configure)
                self.assertIn('-DFOUNDATION_SANITIZERS=' + ('ON' if preset == 'asan' else 'OFF'), configure)
                path = root / ('build/' + preset + '-rust-sdk' + ('-portable' if portable else ''))
                identity = json.loads((path / 'wrapper-identity.json').read_text())
                self.assertEqual(identity['core_provider'], 'rust')
                self.assertEqual(verify.call_count, 2)
                native.assert_not_called()

    def test_direct_cmake_and_presets_share_rust_default(self):
        import re
        root = Path(builder.__file__).resolve().parents[1]
        cmake = (root / 'CMakeLists.txt').read_text()
        provider = re.search(r'set\(FOUNDATION_CORE_PROVIDER "([^"]+)" CACHE STRING', cmake)
        self.assertIsNotNone(provider)
        self.assertEqual(provider[1], 'rust')
        presets = json.loads((root / 'CMakePresets.json').read_text())
        for preset in presets['configurePresets']:
            self.assertNotEqual(preset.get('cacheVariables', {}).get('FOUNDATION_CORE_PROVIDER'), 'cpp')

    def test_retained_rust_sdk_has_separate_target_argument_identity_and_rechecks(self):
        from unittest.mock import patch
        import source_identity
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve(); rust = root / 'rust'; rust.mkdir()
            sdk = root / 'cpp'; sdk.mkdir()
            (sdk / 'sdk.json').write_text(json.dumps({'target': {'system': 'Linux'}, 'recipe_id': 'a' * 64}))
            args = ['build', '--rust-sdk', str(rust), '--sdk', str(sdk)]
            with patch.object(builder, 'ROOT', root), patch.object(builder, 'run') as run, \
                    patch.object(builder, 'cache_identity', return_value={}), \
                    patch.object(builder, 'require_clean'), patch.object(builder, 'sdk_identity', return_value='c' * 64), \
                    patch.object(builder, 'rust_sdk_identity', return_value='b' * 64) as verify, \
                    patch.object(source_identity, 'source_tree', return_value={}):
                self.assertEqual(builder.main(args), 0)
                self.assertEqual(verify.call_count, 2)
                verify.assert_called_with(rust, sdk)
                configure = run.call_args_list[0].args[0]
                self.assertIn('-DFOUNDATION_CORE_PROVIDER=rust', configure)
                self.assertIn('-DFOUNDATION_RUST_SDK_ROOT=' + str(rust), configure)
                self.assertIn('-DFOUNDATION_SDK_ROOT=' + str(sdk), configure)
                build = root / 'build/dev-sdk-rust-sdk'
                identity = json.loads((build / 'wrapper-identity.json').read_text())
                self.assertEqual(identity['rust_sdk'], {'root': str(rust), 'sha256': 'b' * 64})
                verify.return_value = 'd' * 64
                with self.assertRaisesRegex(ValueError, 'configuration changed'):
                    builder.main(args)
                verify.side_effect = ['b' * 64, 'd' * 64]
                with self.assertRaisesRegex(ValueError, 'Rust SDK changed'):
                    builder.main(args)

    def test_native_rust_development_freezes_selected_tools_and_rejects_changed_tools(self):
        from unittest.mock import patch
        import source_identity
        selected = {'cargo': '/usr/bin/cargo', 'rustc': '/usr/bin/rustc'}
        before = {'cargo': {'sha256': 'a' * 64}, 'rustc': {'sha256': 'b' * 64}}
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            with patch.object(builder, 'ROOT', root), patch.object(builder, 'run') as run, \
                    patch.object(builder.sys, 'platform', 'linux'), \
                    patch.object(builder, 'cache_identity', return_value={}), \
                    patch.object(builder, 'native_rust_identity', return_value=(selected, before)) as verify, \
                    patch.object(source_identity, 'source_tree', return_value={}):
                self.assertEqual(builder.main(['build']), 0)
                self.assertEqual(verify.call_count, 2)
                configure = run.call_args_list[0].args[0]
                self.assertIn('-DFOUNDATION_RUST_CARGO=/usr/bin/cargo', configure)
                self.assertIn('-DFOUNDATION_RUST_RUSTC=/usr/bin/rustc', configure)
                identity = json.loads((root / 'build/dev-rust/wrapper-identity.json').read_text())
                self.assertEqual(identity['rust_tools'], before)
                verify.side_effect = [(selected, before), (selected, {'changed': True})]
                with self.assertRaisesRegex(ValueError, 'Rust tools changed'):
                    builder.main(['build'])

    def test_default_and_explicit_rust_reject_unprepared_profiles_and_unsupported_hosts(self):
        from contextlib import redirect_stderr
        from io import StringIO
        from unittest.mock import patch
        with patch.object(builder, 'run') as run, patch.object(builder, 'native_rust_identity') as discover:
            for selection in ([], ['--core-provider', 'rust']):
                for arguments in (['build', 'release'], ['build', 'asan'], ['package'], ['portable-package'],
                                  ['build', '--portable'], ['build', '--sdk', 'absent'],
                                  ['build', '--windows-dependencies', 'absent']):
                    with self.subTest(arguments=arguments, selection=selection), \
                            redirect_stderr(StringIO()) as error, self.assertRaises(SystemExit):
                        builder.main([*arguments, *selection])
                    self.assertIn('--rust-sdk', error.getvalue())
                    self.assertIn('--core-provider cpp', error.getvalue())
                for system in ('darwin', 'win32'):
                    with patch.object(builder.sys, 'platform', system), \
                            redirect_stderr(StringIO()), self.assertRaises(SystemExit):
                        builder.main(['build', *selection])
            run.assert_not_called(); discover.assert_not_called()

    def test_default_rust_does_not_adopt_an_existing_cpp_wrapper_tree(self):
        from unittest.mock import patch
        import source_identity
        selected = {'cargo': '/usr/bin/cargo', 'rustc': '/usr/bin/rustc'}
        tools = {'cargo': {'sha256': 'a' * 64}, 'rustc': {'sha256': 'b' * 64}}
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve(); tree = root / 'existing'
            with patch.object(builder, 'ROOT', root), patch.object(builder.sys, 'platform', 'linux'), \
                    patch.object(builder, 'run') as run, patch.object(builder, 'cache_identity', return_value={}), \
                    patch.object(builder, 'native_rust_identity', return_value=(selected, tools)), \
                    patch.object(source_identity, 'source_tree', return_value={}):
                self.assertEqual(builder.main(['build', '--core-provider', 'cpp', '--build-dir', str(tree)]), 0)
                before = (tree / 'wrapper-identity.json').read_bytes()
                run.reset_mock()
                with self.assertRaisesRegex(ValueError, 'configuration changed.*fresh build tree'):
                    builder.main(['build', '--build-dir', str(tree)])
                self.assertEqual((tree / 'wrapper-identity.json').read_bytes(), before)
                run.assert_not_called()

    def test_opt_in_timings_distinguish_probe_execution_and_failure(self):
        from unittest.mock import patch
        import source_identity
        import subprocess
        for fail in (False, True):
            with self.subTest(fail=fail), tempfile.TemporaryDirectory() as directory:
                root = Path(directory).resolve(); output = root / 'timings.json'; calls = []
                def execute(command, **kwargs):
                    calls.append(command)
                    if fail and command[0] == 'ctest' and '--show-only=json-v1' not in command:
                        raise subprocess.CalledProcessError(1, command)
                with patch.object(builder, 'ROOT', root), patch.object(builder, 'run', side_effect=execute), \
                        patch.object(builder, 'cache_identity', return_value={}), \
                        patch.object(builder.subprocess, 'check_output', side_effect=execute), \
                        patch.object(source_identity, 'source_tree', return_value={'tree_sha256':'a'*64}):
                    arguments = ['test', 'dev', '--core-provider', 'cpp', '--label', 'core', '--timings', str(output)]
                    if fail:
                        with self.assertRaises(subprocess.CalledProcessError): builder.main(arguments)
                    else:
                        self.assertEqual(builder.main(arguments), 0)
                report = json.loads(output.read_text())
                self.assertEqual(report['status'], 'failed' if fail else 'passed')
                self.assertFalse(report['context']['warm_tree_at_start'])
                self.assertEqual(set(report['phases']), {'configure', 'compile', 'source_verification',
                    'configuration_verification', 'test_startup_probe', 'test_execution'})
                self.assertEqual(report['phases']['source_verification']['calls'], 2 if fail else 3)
                self.assertTrue(all(row['seconds'] >= 0 for row in report['phases'].values()))
                tests = [c for c in calls if c[0] == 'ctest']
                self.assertEqual(len(tests), 2)
                self.assertIn('--show-only=json-v1', tests[0]); self.assertNotIn('--show-only=json-v1', tests[1])
                self.assertIn('^core$', tests[0]); self.assertIn('^core$', tests[1])
                self.assertIn('includes its own startup', report['interpretation'])

    def test_timing_receipt_separates_sdk_checks_and_binds_its_identity(self):
        from unittest.mock import patch
        import source_identity
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve(); sdk = root/'sdk'; sdk.mkdir(); output = root/'timings.json'
            (sdk/'sdk.json').write_text(json.dumps({'target':{'system':'Linux'}, 'recipe_id':'a'*64}))
            with patch.object(builder, 'ROOT', root), patch.object(builder, 'run'), \
                    patch.object(builder, 'cache_identity', return_value={}), \
                    patch.object(builder, 'sdk_identity', return_value='b'*64) as verify, \
                    patch.object(builder, 'require_clean'), \
                    patch.object(source_identity, 'source_tree', return_value={'tree_sha256':'c'*64}):
                self.assertEqual(builder.main(['build', '--core-provider', 'cpp', '--sdk', str(sdk), '--timings', str(output)]), 0)
            report = json.loads(output.read_text())
            self.assertEqual(report['phases']['sdk_verification']['calls'], 2)
            self.assertEqual(verify.call_count, 2)
            self.assertEqual(report['context']['sdk_sha256'], 'b'*64)
            self.assertEqual(report['context']['source_tree_sha256'], 'c'*64)
            self.assertNotIn('test_startup_probe', report['phases'])

    def test_prebuilt_wasm_input_is_pinned_reverified_and_part_of_tree_identity(self):
        from unittest.mock import patch
        import import_wasm, source_identity
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve(); package = root / 'wasm'; package.mkdir(); digest = 'a'*64
            args = ['build', '--core-provider', 'cpp', '--wasm-package', str(package), '--wasm-package-sha256', digest]
            with patch.object(builder, 'ROOT', root), patch.object(builder, 'run') as run, \
                    patch.object(builder, 'cache_identity', return_value={}), \
                    patch.object(source_identity, 'source_tree', return_value={}), \
                    patch.object(import_wasm, 'verify_input') as verify:
                self.assertEqual(builder.main(args), 0)
                self.assertEqual(verify.call_count, 2)
                verify.assert_called_with(package, digest, root)
                configure = run.call_args_list[0].args[0]
                self.assertIn('-DFOUNDATION_WASM_PACKAGE=' + str(package), configure)
                self.assertIn('-DFOUNDATION_WASM_PACKAGE_SHA256=' + digest, configure)
                identity = json.loads((root/'build/dev/wrapper-identity.json').read_text())
                self.assertEqual(identity['wasm_package'], {'root':str(package), 'sha256':digest})
                with self.assertRaisesRegex(ValueError, 'configuration changed'):
                    builder.main(['build', '--core-provider', 'cpp'])
            with patch.object(builder, 'run') as run:
                for invalid in (['build', '--wasm-package', str(package)],
                                ['build', '--wasm-package-sha256', digest],
                                [*args[:-1], 'bad']):
                    with self.subTest(invalid=invalid), self.assertRaises(SystemExit): builder.main(invalid)
                run.assert_not_called()

    def test_portable_package_is_explicit_release_and_verifies_both_archive_formats(self):
        from unittest.mock import patch
        import source_identity
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            calls = []
            def execute(command, **kwargs):
                calls.append(command)
                if command[0] == 'cpack':
                    packages = root / 'build/release-portable/packages'
                    packages.mkdir(parents=True)
                    for name in ('Foundation.tar.gz', 'Foundation.zip'):
                        (packages / name).write_bytes(b'fixture')
            with patch.object(builder, 'ROOT', root), patch.object(builder, 'run', side_effect=execute), \
                    patch.object(builder, 'cache_identity', return_value={}), \
                    patch.object(source_identity, 'source_tree', return_value={}):
                self.assertEqual(builder.main(['portable-package', '--core-provider', 'cpp']), 0)
            self.assertIn('release', calls[0])
            self.assertIn('-DFOUNDATION_PORTABLE=ON', calls[0])
            actions = [c[3] for c in calls if len(c) > 3 and str(c[2]).endswith('artifact.py')]
            self.assertEqual(actions, ['create', 'verify', 'create', 'verify'])
        with patch.object(builder, 'run') as execute, self.assertRaises(SystemExit):
            builder.main(['portable-package', 'dev'])
        execute.assert_not_called()

    def test_exact_test_selection_builds_only_registered_fixture_closure(self):
        import shutil, subprocess
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            module = Path(__file__).resolve().parents[1] / 'cmake/TestPrerequisites.cmake'
            shutil.copyfile(module, root / module.name)
            (root / 'ok.cpp').write_text('int main(){return 0;}\n')
            (root / 'bad.cpp').write_text('#error unrelated compilation must never run\n')
            (root / 'CMakeLists.txt').write_text("""cmake_minimum_required(VERSION 3.24)
project(ExactSelection LANGUAGES CXX)
enable_testing()
include(TestPrerequisites.cmake)
add_executable(selected EXCLUDE_FROM_ALL ok.cpp)
add_executable(setup EXCLUDE_FROM_ALL ok.cpp)
add_executable(unrelated bad.cpp)
add_test(NAME a.core COMMAND selected)
set_tests_properties(a.core PROPERTIES FIXTURES_REQUIRED prepare)
foundation_test_prerequisites(a.core selected)
add_test(NAME setup.fixture COMMAND setup)
set_tests_properties(setup.fixture PROPERTIES FIXTURES_SETUP prepare)
foundation_test_prerequisites(setup.fixture setup)
add_test(NAME cleanup.fixture COMMAND "${CMAKE_COMMAND}" -E true)
set_tests_properties(cleanup.fixture PROPERTIES FIXTURES_CLEANUP prepare)
foundation_test_prerequisites(cleanup.fixture)
add_test(NAME axcore COMMAND unrelated)
foundation_test_prerequisites(axcore unrelated)
add_test(NAME script.only COMMAND "${CMAKE_COMMAND}" -E true)
foundation_test_prerequisites(script.only)
cmake_language(DEFER CALL foundation_finalize_test_prerequisites)
""")
            (root / 'CMakePresets.json').write_text(json.dumps({'version':3,'configurePresets':[
                {'name':'dev','generator':'Ninja','binaryDir':'${sourceDir}/build/dev'}]}))
            with patch.object(builder, 'ROOT', root):
                self.assertEqual(builder.main(['test', 'dev', '--core-provider', 'cpp', '--test', 'script.only', '--jobs', '1']), 0)
                tree = root / 'build/dev'
                self.assertFalse((tree / 'selected').exists())
                self.assertFalse((tree / 'setup').exists())
                self.assertEqual(builder.main(['test', 'dev', '--core-provider', 'cpp', '--test', 'a.core', '--test', 'script.only', '--jobs', '1']), 0)
                suffix = '.exe' if sys.platform == 'win32' else ''
                self.assertTrue((tree / ('selected' + suffix)).is_file())
                self.assertTrue((tree / ('setup' + suffix)).is_file())
                self.assertFalse((tree / ('unrelated' + suffix)).exists())
                with self.assertRaisesRegex(ValueError, 'unknown exact test'):
                    builder.main(['test', 'dev', '--core-provider', 'cpp', '--test', 'a.cor'])
                with self.assertRaisesRegex(ValueError, 'unique'):
                    builder.main(['test', 'dev', '--core-provider', 'cpp', '--test', 'a.core', '--test', 'a.core'])
            for options in (['build', '--test', 'a.core'], ['test', '--test', 'a.core', '--full'],
                            ['test', '--test', 'a.core', '--label', 'core']):
                with self.subTest(options=options), self.assertRaises(SystemExit):
                    builder.main(options)

    def test_source_observations_keep_execution_boundaries_without_duplicate_build_scan(self):
        from unittest.mock import patch
        import source_identity
        for action in ('build', 'test', 'package'):
            with self.subTest(action=action), tempfile.TemporaryDirectory() as directory:
                root = Path(directory).resolve()
                phases = []
                def execute(command, **kwargs):
                    phases.append('configure' if '--preset' in command else
                                  'compile' if '--build' in command else command[0])
                def observe(*args):
                    phases.append('source')
                    return {}
                with patch.object(builder, 'ROOT', root), patch.object(builder, 'run', side_effect=execute), \
                        patch.object(builder, 'cache_identity', return_value={}), \
                        patch.object(source_identity, 'source_tree', side_effect=observe):
                    self.assertEqual(builder.main([action, 'release', '--core-provider', 'cpp']), 0)
                expected = ['source', 'configure', 'compile', 'source']
                if action != 'build': expected += ['ctest' if action == 'test' else 'cpack', 'source']
                self.assertEqual(phases, expected)

    def test_bundled_gui_is_explicit_and_retains_group_identity(self):
        from unittest.mock import patch
        import source_identity
        for selector in ([], ['--gui'], ['--gui-source', 'selected'],
                         ['--gui-input-group', 'selected-group']):
            with self.subTest(selector=selector), tempfile.TemporaryDirectory() as directory:
                root = Path(directory).resolve()
                source = root / 'selected'
                source.mkdir()
                bundled = root / 'third_party/gui-inputs'
                bundled.mkdir(parents=True)
                explicit = root / 'selected-group'
                explicit.mkdir()
                arguments = [str(root / arg) if arg in ('selected', 'selected-group') else arg
                             for arg in selector]
                receipt = json.dumps({'source': str(source), 'group_sha256': 'a' * 64})
                with patch.object(builder, 'ROOT', root), patch.object(builder, 'run') as run, \
                        patch.object(builder, 'cache_identity', return_value={}), \
                        patch.object(builder.subprocess, 'check_output', return_value=receipt) as restore, \
                        patch.object(source_identity, 'source_tree', return_value={}):
                    self.assertEqual(builder.main(['build', 'dev', '--core-provider', 'cpp', '--configure-only', *arguments]), 0)
                configure = run.call_args.args[0]
                enabled = bool(selector)
                self.assertIn('-DFOUNDATION_BUILD_GUI=' + ('ON' if enabled else 'OFF'), configure)
                tree = root / ('build/dev-gui' if enabled else 'build/dev')
                identity = json.loads((tree / 'wrapper-identity.json').read_text())
                if selector and selector[0] != '--gui-source':
                    group = bundled if selector == ['--gui'] else explicit
                    self.assertEqual(restore.call_count, 2)
                    self.assertEqual(restore.call_args_list[0].args[0][3:5], ['restore', str(group)])
                    self.assertEqual(identity['gui_input_group'], {'root': str(group), 'sha256': 'a' * 64})
                else:
                    restore.assert_not_called()
                    self.assertNotIn('gui_input_group', identity)

    def test_bundled_gui_missing_or_conflicting_input_fails_before_configure(self):
        from contextlib import redirect_stderr
        from io import StringIO
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            with patch.object(builder, 'ROOT', root), patch.object(builder, 'run') as run:
                with self.assertRaises(FileNotFoundError):
                    builder.main(['build', '--core-provider', 'cpp', '--gui'])
                run.assert_not_called()
                self.assertFalse((root / 'build').exists())
                for option in ('--gui-source', '--gui-input-group'):
                    with self.subTest(option=option), redirect_stderr(StringIO()), self.assertRaises(SystemExit):
                        builder.main(['build', '--gui', option, str(root)])
                run.assert_not_called()

    def test_configure_only_keeps_identity_guards_without_compiling(self):
        from unittest.mock import patch
        import source_identity
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            with patch.object(builder, 'ROOT', root), patch.object(builder, 'run') as run, \
                    patch.object(builder, 'cache_identity', return_value={}), \
                    patch.object(source_identity, 'source_tree', return_value={}):
                self.assertEqual(builder.main(['build', 'release', '--core-provider', 'cpp', '--configure-only']), 0)
            self.assertEqual(run.call_count, 1)
            self.assertIn('--preset', run.call_args.args[0])
            self.assertTrue((root / 'build/release/configured-identity.json').is_file())
        for action in ('test', 'package'):
            with self.subTest(action=action), self.assertRaises(SystemExit):
                builder.main([action, 'release', '--configure-only'])

    def test_stop_on_failure_requires_test_before_starting_work(self):
        from contextlib import redirect_stderr
        from io import StringIO
        from unittest.mock import patch
        for action in ('build', 'package'):
            with self.subTest(action=action), patch.object(builder, 'run') as run, \
                    redirect_stderr(StringIO()) as error, self.assertRaises(SystemExit) as rejected:
                builder.main([action, 'release', '--stop-on-failure'])
            self.assertEqual(rejected.exception.code, 2)
            self.assertIn('--stop-on-failure applies only to test', error.getvalue())
            run.assert_not_called()

    def test_stop_on_failure_preserves_failure_and_default_full_execution(self):
        import shutil
        import subprocess
        import source_identity
        from unittest.mock import patch
        ctest = shutil.which('ctest')
        self.assertIsNotNone(ctest, 'CTest is required for build wrapper tests')
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            tree = root / 'build/dev'
            tree.mkdir(parents=True)
            (tree / 'fail.py').write_text('raise SystemExit(1)\n')
            marker = tree / 'after-ran'
            (tree / 'after.py').write_text(
                'from pathlib import Path\nPath(__file__).with_name("after-ran").write_text("executed")\n')
            command = '[=[' + sys.executable.replace('\\', '/') + ']=]'
            (tree / 'CTestTestfile.cmake').write_text(
                'add_test(01_fail ' + command + ' "fail.py")\n'
                'add_test(02_after ' + command + ' "after.py")\n'
                'set_tests_properties(01_fail 02_after PROPERTIES LABELS core)\n'
                'set_tests_properties(02_after PROPERTIES DEPENDS 01_fail)\n')
            def run(command, **kwargs):
                if command[0] == 'ctest':
                    subprocess.run([ctest, *command[1:]], cwd=root,
                        env=kwargs['env'], capture_output=True, text=True, check=True)
            identity = None
            # The scheduling flag can change in the same configured tree. A
            # failing first case remains a failure with either execution policy.
            for stop in (False, True, False):
                marker.unlink(missing_ok=True)
                with self.subTest(stop=stop), patch.object(builder, 'ROOT', root), \
                        patch.object(builder, 'run', side_effect=run), \
                        patch.object(builder, 'cache_identity', return_value={}), \
                        patch.object(source_identity, 'source_tree', return_value={}):
                    with self.assertRaises(subprocess.CalledProcessError) as failed:
                        builder.main(['test', 'dev', '--core-provider', 'cpp', '--label', 'core', '--jobs', '1',
                                      *(['--stop-on-failure'] if stop else [])])
                self.assertNotEqual(failed.exception.returncode, 0)
                self.assertIn('01_fail', failed.exception.stdout)
                self.assertEqual(marker.exists(), not stop)
                current = (tree / 'wrapper-identity.json').read_bytes()
                if identity is not None:
                    self.assertEqual(current, identity)
                identity = current

    def test_supported_build_regions_use_explicit_compiler_owner(self):
        from unittest.mock import patch
        for command in (['cmake', '--preset', 'release'], ['cmake', '--build', 'tree'],
                        ['ctest', '--test-dir', 'tree'], ['cpack', '--config', 'tree/CPackConfig.cmake']):
            with self.subTest(command=command), patch.object(builder.windows_compiler, 'run') as run:
                builder.run(command, env={'PATH': 'selected-toolkit'})
            run.assert_called_once_with(command, cwd=builder.ROOT, env={'PATH': 'selected-toolkit'})

    def test_static_windows_export_disables_package_manager_hooks_only_for_its_children(self):
        from types import SimpleNamespace
        from unittest.mock import patch
        import dependency_archive
        import dependency_store
        import sdk_manifest
        import source_identity
        recipe = 'a' * 64
        hooks = {'-DVCPKG_MANIFEST_MODE=OFF', '-DVCPKG_APPLOCAL_DEPS=OFF',
                 '-DX_VCPKG_APPLOCAL_DEPS_INSTALL=OFF'}
        for action in ('build', 'test', 'package'):
            for retained in (False, "complete", "binary"):
                with self.subTest(action=action, retained=retained), tempfile.TemporaryDirectory() as temporary:
                    root = Path(temporary).resolve(strict=True)
                    dependencies = root / 'dependencies'
                    vcpkg = dependencies / 'prefix/scripts/buildsystems/vcpkg.cmake'
                    vcpkg.parent.mkdir(parents=True)
                    vcpkg.write_text('# inert retained integration fixture\n')
                    (dependencies / 'prefix/installed/x64-windows-static').mkdir(parents=True)
                    metadata = {'kind': 'windows-dependencies', 'recipe_id': recipe,
                                'target': {'system': 'Windows', 'processor': 'x86_64'},
                                'provenance': {'toolset': 'v143', 'crt_linkage': 'static',
                                               'library_linkage': 'static', 'lto': False},
                                'external_toolchain': {'minimum_linker': '14.44.35207'},
                                'files': {'prefix/scripts/buildsystems/vcpkg.cmake':
                                          hashlib.sha256(vcpkg.read_bytes()).hexdigest()}}
                    (dependencies / 'sdk.json').write_text(json.dumps(metadata))
                    group = root / 'group'; group.mkdir()
                    (group / ('sdk-' + recipe + '-SHA256SUMS')).write_text('fixture')
                    environment = {'PATH': 'selected-toolkit', 'VCPKG_DISABLE_METRICS': '0',
                                   'vcpkg_disable_metrics': 'inherited-alias', 'UNCHANGED': 'value'}
                    baseline = dict(environment)
                    args = [action, 'release', '--core-provider', 'cpp', '--jobs', '2', '--portable']
                    if retained:
                        args += ['--windows-dependencies', str(dependencies),
                                 '--binary-dependency-group' if retained == 'binary' else '--dependency-group', str(group)]
                    with patch.object(builder, 'ROOT', root), \
                            patch.object(builder, 'os', SimpleNamespace(name='nt', environ=environment)), \
                            patch.object(builder, 'run') as run, \
                            patch.object(builder, 'cache_identity', return_value={}), \
                            patch.object(builder, 'verify_windows_linker'), \
                            patch.object(dependency_store, 'verify_group', return_value={}), \
                            patch.object(dependency_store, 'verify_binary_group', return_value={}), \
                            patch.object(dependency_archive, 'inspect_manifest_archive', return_value=(metadata, None)), \
                            patch.object(sdk_manifest, 'verify_sdk'), \
                            patch.object(source_identity, 'source_tree', return_value={}):
                        self.assertEqual(builder.main(args), 0)
                    if retained:
                        receipt = json.loads((root / 'build/release-portable/wrapper-identity.json').read_text())
                        self.assertEqual(receipt['dependencies'][0].get('payload'), 'binary' if retained == 'binary' else None)
                    self.assertEqual(environment, baseline)
                    configure = run.call_args_list[0].args[0]
                    self.assertEqual(hooks.intersection(configure), hooks if retained else set())
                    self.assertFalse(any(arg.startswith('-DVCPKG_FEATURE_FLAGS=') for arg in configure))
                    for call in run.call_args_list:
                        child = call.kwargs['env']
                        self.assertIsNot(child, environment)
                        expected = dict(baseline)
                        if retained:
                            expected.pop('vcpkg_disable_metrics')
                            expected['VCPKG_DISABLE_METRICS'] = '1'
                        if call.args[0][0] == 'ctest':
                            # Two parent slots divide into one slot per child.
                            # Compiler ownership and retained-toolkit hooks stay
                            # identical across the test scheduling boundary.
                            expected.update(FOUNDATION_WORKER_BUDGET='1',
                                            CMAKE_BUILD_PARALLEL_LEVEL='1',
                                            CTEST_PARALLEL_LEVEL='1')
                        self.assertEqual(child, expected)
                    # Neither library/CRT relaxation nor altered export metadata
                    # may reach configuration under this consumer policy.
                    if retained:
                        for key, value in (('crt_linkage', 'dynamic'), ('library_linkage', 'dynamic'), ('lto', True)):
                            changed = json.loads(json.dumps(metadata))
                            changed['provenance'][key] = value
                            (dependencies / 'sdk.json').write_text(json.dumps(changed))
                            with patch.object(builder, 'ROOT', root), \
                                    patch.object(builder, 'os', SimpleNamespace(name='nt', environ=environment)), \
                                    patch.object(builder, 'run') as rejected, \
                                    patch.object(dependency_store, 'verify_group', return_value={}), \
                                    patch.object(dependency_store, 'verify_binary_group', return_value={}), \
                                    patch.object(dependency_archive, 'inspect_manifest_archive', return_value=(changed, None)), \
                                    patch.object(sdk_manifest, 'verify_sdk'):
                                with self.assertRaisesRegex(ValueError, 'incompatible Windows dependency ABI'):
                                    builder.main(args)
                            rejected.assert_not_called()

    def test_windows_linker_file_versions_use_same_order(self):
        from unittest.mock import patch
        for actual, minimum, success in (
                ('14.44.35207', '14.44.35207.0', True),
                ('14.44.35207.0', '14.44.35207', True),
                ('14.44.35207', '14.44.35207.1', False),
                ('14.44.35206.9', '14.44.35207.0', False),
                ('14.45.1', '14.44.35207.0', True)):
            with self.subTest(actual=actual, minimum=minimum), patch.object(
                    toolchain, 'inspect_selected_linker', return_value={'version':actual}):
                if success:
                    builder.verify_windows_linker(minimum)
                else:
                    with self.assertRaises(ValueError): builder.verify_windows_linker(minimum)
        with patch.object(toolchain, 'inspect_selected_linker', side_effect=ValueError('unrecognized tool')):
            with self.assertRaises(ValueError): builder.verify_windows_linker('14.44.35207.0')

    def test_native_windows_selected_linker_file_identity(self):
        import os
        value = toolchain.inspect_selected_linker()
        self.assertEqual(value['architecture'], 'x86_64')
        self.assertTrue(Path(value['path']).samefile(Path(os.environ['VCToolsInstallDir']) / 'bin/Hostx64/x64/link.exe'))
        self.assertEqual(value['sha256'], hashlib.sha256(Path(value['path']).read_bytes()).hexdigest())
        builder.verify_windows_linker(value['version'])

    def test_retained_host_tools_are_selected_and_cannot_escape(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            (root / "tools").mkdir()
            (root / "tools/cmake").write_text("fixture")
            (root / "sdk.json").write_text(json.dumps({"host_tools": {"cmake": "tools/cmake"}}))
            self.assertEqual(builder.host_programs(root)["cmake"], str((root / "tools/cmake").resolve()))
            self.assertEqual(builder.host_programs(root)["ctest"], "ctest")
            (root / "sdk.json").write_text(json.dumps({"host_tools": {"cmake": "../outside"}}))
            with self.assertRaises(ValueError):
                builder.host_programs(root)

    def test_sdk_inventory_is_complete(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            (root / "bin").mkdir()
            (root / "sysroot").mkdir()
            (root / "bin/cxx").write_bytes(b"compiler fixture")
            data = {"schema_version": 1, "recipe_id": "a" * 64, "target": {
                "system": "Linux", "processor": "x86_64", "triple": "x86_64-linux-gnu",
                "sysroot": "sysroot", "cxx_compiler": "bin/cxx"},
                "files": {"bin/cxx": hashlib.sha256(b"compiler fixture").hexdigest()}}
            (root / "sdk.json").write_text(json.dumps(data))
            self.assertEqual(len(builder.sdk_identity(root)), 64)
            (root / "sysroot/extra").write_text("unlisted")
            with self.assertRaises(ValueError):
                builder.sdk_identity(root)
            (root / "sysroot/extra").unlink()
            (root / "bin/cxx").write_bytes(b"modified")
            with self.assertRaises(ValueError):
                builder.sdk_identity(root)

    def test_path_and_job_validation(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(ValueError):
                builder.contained(Path(directory), "../elsewhere")
        self.assertGreaterEqual(builder.default_jobs(), 1)
        from unittest.mock import patch
        with patch("build_capacity.default_jobs", return_value=7):
            self.assertEqual(builder.default_jobs(), 7)
        with self.assertRaises(Exception):
            builder.positive("0")

    def test_runtime_install_script_selects_sdk_baseline_and_editor(self):
        import os
        import shutil
        import subprocess
        template = Path(builder.__file__).resolve().parents[1] / 'cmake/InstallRuntime.cmake.in'
        cmake = shutil.which('cmake')
        self.assertIsNotNone(cmake, 'CMake is required for build policy tests')
        with tempfile.TemporaryDirectory(prefix='runtime install ') as temporary:
            root = Path(temporary).resolve()
            (root / 'tools').mkdir()
            output = root / 'arguments.json'
            (root / 'tools/package_runtime.py').write_text(
                'import json,sys\nfrom pathlib import Path\nPath(' + repr(str(output)) +
                ').write_text(json.dumps(sys.argv[1:]))\n')
            script = root / 'configure.cmake'
            for sdk_root in ('', (root / 'retained SDK').as_posix()):
                with self.subTest(sdk=bool(sdk_root)):
                    script.write_text('cmake_minimum_required(VERSION 3.24)\n' +
                        'set(Python3_EXECUTABLE "' + Path(sys.executable).as_posix() + '")\n' +
                        'set(CMAKE_SOURCE_DIR "' + root.as_posix() + '")\n' +
                        'set(CMAKE_INSTALL_PREFIX "/opt/example")\n' +
                        'set(_portable_processor "x86_64")\n' +
                        'set(FOUNDATION_RUNTIME_ROOTS "' + (root/'target libraries').as_posix() + '")\n' +
                        'set(FOUNDATION_SDK_ROOT "' + sdk_root + '")\n' +
                        'configure_file("' + template.as_posix() + '" "' +
                        (root/'install.cmake').as_posix() + '" @ONLY)\n' +
                        'include("' + (root/'install.cmake').as_posix() + '")\n')
                    subprocess.run([cmake, '-P', str(script)], check=True,
                                   env=dict(os.environ, DESTDIR='/staging'))
                    args = json.loads(output.read_text())
                    expected = ['--prefix', '/staging/opt/example', '--processor', 'x86_64',
                                '--root', (root/'target libraries').as_posix()]
                    if sdk_root:
                        expected += ['--bookworm', '--elf-editor', sdk_root + '/bin/patchelf']
                    self.assertEqual(expected, args)

    def test_package_configuration_cannot_be_mislabelled(self):
        import shutil
        import subprocess
        cmake = shutil.which('cmake')
        self.assertIsNotNone(cmake, 'CMake is required for build policy tests')
        template = (Path(builder.__file__).resolve().parents[1] / 'cmake/PackagePolicy.cmake.in').read_text()
        with tempfile.TemporaryDirectory() as directory:
            policy = Path(directory) / 'policy.cmake'
            for build_type, configurations, requested, success in (
                ('Debug', '', 'Release', False),
                ('Release', '', 'Release', True),
                ('', 'Debug;Release', 'Release', True),
                ('', 'Debug;Release', 'Debug', False)):
                body = template.replace('@FOUNDATION_SANITIZERS@', 'OFF').replace('@FOUNDATION_BUILD_GUI@', 'OFF')
                body = body.replace('@CMAKE_BUILD_TYPE@', build_type).replace('@CMAKE_CONFIGURATION_TYPES@', configurations)
                policy.write_text(body)
                result = subprocess.run([cmake, '-DCPACK_BUILD_CONFIG=' + requested, '-P', str(policy)], capture_output=True)
                self.assertEqual(result.returncode == 0, success, result.stderr)

    def test_local_package_verification_relocates_every_produced_archive(self):
        import source_identity
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve(); build = root / 'output'
            calls = []
            def run(command, **kwargs):
                calls.append([str(value) for value in command])
                if command[0] == 'cpack':
                    (build / 'packages').mkdir()
                    for name in ('example.tar.gz', 'example.zip'):
                        (build / 'packages' / name).write_bytes(b'archive fixture')
            with patch.object(builder, 'ROOT', root), patch.object(builder, 'run', side_effect=run), \
                    patch.object(builder, 'cache_identity', return_value={}), \
                    patch.object(source_identity, 'source_tree', return_value={'revision': 1}):
                builder.main(['package', 'release', '--core-provider', 'cpp', '--build-dir', str(build), '--verify-package'])
            checks = [call for call in calls if str(root / 'tools/artifact.py') in call]
            self.assertEqual(['create', 'verify', 'create', 'verify'], [call[3] for call in checks])
            self.assertEqual(['example.tar.gz', 'example.tar.gz', 'example.zip', 'example.zip'],
                             [Path(call[4]).name for call in checks])
            for call in checks:
                self.assertEqual(call[4] + '.json', call[6])
                self.assertNotIn('--runtime-only', call)

    def test_local_package_verification_preserves_prepared_toolchain(self):
        import source_identity
        import sdk_manifest
        import sdk_wasm
        from unittest.mock import patch
        for system, processor in [('Linux', 'aarch64'), ('Emscripten', 'wasm32')]:
            with self.subTest(system=system), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary).resolve(); build = root / 'output'; sdk = root / 'sdk'; sdk.mkdir()
                (sdk / 'node/bin').mkdir(parents=True)
                (sdk / 'node/bin/node').write_text('executor')
                (sdk / 'sdk.json').write_text(json.dumps({'target': {'system': system, 'processor': processor},
                                                        'recipe_id': 'retained'}))
                calls = []
                def run(command, **kwargs):
                    calls.append([str(value) for value in command])
                    if command[0] == 'cpack':
                        (build / 'packages').mkdir()
                        (build / 'packages/example.tar.gz').write_bytes(b'archive fixture')
                with patch.object(builder, 'ROOT', root), patch.object(builder, 'run', side_effect=run), \
                        patch.object(builder, 'cache_identity', return_value={}), \
                        patch.object(builder, 'sdk_identity', return_value='verified'), \
                        patch.object(sdk_manifest, 'verify_sdk', return_value='verified'), \
                        patch.object(sdk_wasm, 'environment', return_value={}), \
                        patch.object(source_identity, 'source_tree', return_value={'revision': 1}), \
                        patch.dict(builder.os.environ, {}, clear=True):
                    builder.main(['package', '--core-provider', 'cpp', '--build-dir', str(build), '--sdk', str(sdk), '--verify-package',
                                  *(['--gui-backends', 'wasm'] if system == 'Emscripten' else [])])
                create, verify = [call for call in calls if str(root / 'tools/artifact.py') in call]
                self.assertNotIn('--sdk', create)
                self.assertEqual(str(sdk), verify[verify.index('--sdk') + 1])
                if system == 'Emscripten':
                    self.assertNotIn('--processor', verify)
                else:
                    self.assertEqual(processor, verify[verify.index('--processor') + 1])

    def test_local_package_verification_propagates_failure_and_requires_packages(self):
        import source_identity
        from unittest.mock import patch
        for missing in (True, False):
            with self.subTest(missing=missing), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary).resolve(); build = root / 'output'
                def run(command, **kwargs):
                    if command[0] == 'cpack' and not missing:
                        (build / 'packages').mkdir()
                        (build / 'packages/example.tar.gz').write_bytes(b'archive fixture')
                    if 'verify' in command:
                        raise ValueError('installed consumer rejected')
                with patch.object(builder, 'ROOT', root), patch.object(builder, 'run', side_effect=run), \
                        patch.object(builder, 'cache_identity', return_value={}), \
                        patch.object(source_identity, 'source_tree', return_value={'revision': 1}):
                    with self.assertRaisesRegex(ValueError, 'no application archives' if missing else 'consumer rejected'):
                        builder.main(['package', '--core-provider', 'cpp', '--build-dir', str(build), '--verify-package'])
        for action in ('build', 'test'):
            with self.assertRaises(SystemExit):
                builder.main([action, '--verify-package'])

    def test_mutation_during_packaging_invalidates_result(self):
        from unittest.mock import patch
        import sys
        sys.path.insert(0, str(Path(builder.__file__).parent))
        import source_identity
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            count = 0
            def run(command, **kwargs):
                nonlocal count
                if command[0] == 'cpack': count += 1
            def identity(*args): return {'revision': count}
            with patch.object(builder, 'ROOT', root), patch.object(builder, 'run', side_effect=run), \
                    patch.object(builder, 'cache_identity', return_value={}), \
                    patch.object(source_identity, 'source_tree', side_effect=identity):
                with self.assertRaisesRegex(ValueError, 'source changed during the operation'):
                    builder.main(['package', 'release', '--core-provider', 'cpp'])

    def test_mutation_during_compilation_or_validation_invalidates_result(self):
        import source_identity
        from unittest.mock import patch
        for phase, message in [('--build', 'source changed during compilation'),
                               ('ctest', 'source changed during the operation')]:
            with self.subTest(phase=phase), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary).resolve()
                revision = [0]
                def run(command, **kwargs):
                    if phase in command:
                        revision[0] += 1
                def identity(*args):
                    return {'revision': revision[0]}
                with patch.object(builder, 'ROOT', root), patch.object(builder, 'run', side_effect=run), \
                        patch.object(builder, 'cache_identity', return_value={}), \
                        patch.object(source_identity, 'source_tree', side_effect=identity):
                    with self.assertRaisesRegex(ValueError, message):
                        builder.main(['test', 'dev', '--core-provider', 'cpp', '--jobs', '2'])

    def test_normal_variable_compiler_is_read_from_active_cmake_record(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            compiler = root / 'compiler with spaces'
            compiler.write_text('fixture compiler')
            (root / 'CMakeCache.txt').write_text('CMAKE_CACHE_MAJOR_VERSION:INTERNAL=3\nCMAKE_CACHE_MINOR_VERSION:INTERNAL=31\nCMAKE_CACHE_PATCH_VERSION:INTERNAL=6\n')
            record = root / 'CMakeFiles/3.31.6/CMakeCXXCompiler.cmake'
            record.parent.mkdir(parents=True)
            record.write_text('set(CMAKE_CXX_COMPILER "' + str(compiler) + '")\n')
            self.assertEqual(builder.cache_identity(root)['compiler_resolved_path'], str(compiler.resolve()))
            record.unlink()
            with self.assertRaises(OSError):
                builder.cache_identity(root)

    def test_unstamped_tree_is_not_silently_adopted(self):
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            tree = root / 'build/dev'
            tree.mkdir(parents=True)
            (tree / 'CMakeCache.txt').write_text('CMAKE_BUILD_TYPE:STRING=Release\n')
            with patch.object(builder, 'ROOT', root), patch.object(builder, 'run') as run:
                with self.assertRaises(ValueError):
                    builder.main(['build', 'dev', '--core-provider', 'cpp'])
                run.assert_not_called()

    def test_link_runtime_launcher_and_dependency_cache_edits_change_identity(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            compiler = root / 'compiler'
            compiler.write_text('fixture compiler')
            cache = root / 'CMakeCache.txt'
            base = 'CMAKE_CXX_COMPILER:FILEPATH=' + str(compiler) + '\n'
            for name in ('CMAKE_EXE_LINKER_FLAGS', 'CMAKE_SHARED_LINKER_FLAGS_RELEASE',
                         'CMAKE_MODULE_LINKER_FLAGS', 'CMAKE_STATIC_LINKER_FLAGS',
                         'CMAKE_INSTALL_RPATH', 'CMAKE_LINKER', 'CMAKE_CXX_COMPILER_LAUNCHER',
                         'CMAKE_PREFIX_PATH', 'Toolkit_DIR'):
                cache.write_text(base + name + ':STRING=original\n')
                before = builder.cache_identity(root)
                cache.write_text(base + name + ':STRING=changed\n')
                self.assertNotEqual(before, builder.cache_identity(root), name)


class WindowsLinkerTests(unittest.TestCase):
    def executable(self, path, machine=0x8664):
        import struct
        path.parent.mkdir(parents=True, exist_ok=True)
        content = bytearray(90); content[:2] = b'MZ'; struct.pack_into('<I', content, 60, 64)
        content[64:68] = b'PE\0\0'; struct.pack_into('<H', content, 68, machine)
        struct.pack_into('<H', content, 86, 2); struct.pack_into('<H', content, 88, 0x20b)
        path.write_bytes(content)
        return path

    def test_selected_file_identity_and_mutation_are_checked_without_execution(self):
        from unittest.mock import patch
        import copy
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve(); expected = self.executable(root / 'toolset/bin/Hostx64/x64/link.exe')
            info = {'version':'14.44.35207.0','identities':[{'company':'Microsoft Corporation','original_filename':'LINK.EXE'}]}
            with patch.object(toolchain.platform, 'system', return_value='Windows'), \
                 patch.dict(toolchain.os.environ, {'VCToolsInstallDir':str(root/'toolset')}), \
                 patch.object(toolchain.shutil, 'which', return_value=str(expected)), \
                 patch.object(toolchain, 'file_version', return_value=info) as resource:
                value = toolchain.inspect_selected_linker()
                self.assertEqual(value['version'],info['version']);self.assertEqual(value['path'],str(expected.resolve()))
                self.assertEqual(value['sha256'],hashlib.sha256(expected.read_bytes()).hexdigest())
                other = self.executable(root/'other/link.exe')
                with patch.object(toolchain.shutil,'which',return_value=str(other)):
                    with self.assertRaisesRegex(ValueError,'PATH linker differs'):toolchain.inspect_selected_linker()
                for key,value in [('company','Other supplier'),('original_filename','other.exe')]:
                    changed = copy.deepcopy(info);changed['identities'][0][key]=value;resource.return_value=changed
                    with self.assertRaisesRegex(ValueError,'not the Microsoft linker'):toolchain.inspect_selected_linker()
                resource.return_value=dict(info,version='1.2.3.4')
                with self.assertRaisesRegex(ValueError,'not a supported'):toolchain.inspect_selected_linker()
                resource.return_value=info
                def mutate(path):
                    path.write_bytes(path.read_bytes()+b'changed');return info
                resource.side_effect=mutate
                with self.assertRaisesRegex(ValueError,'changed during'):toolchain.inspect_selected_linker()
                resource.side_effect=None;self.executable(expected,machine=0x14c)
                with self.assertRaisesRegex(ValueError,'native x64'):toolchain.inspect_selected_linker()
                expected.write_bytes(b'not a PE file')
                with self.assertRaisesRegex(ValueError,'not a PE'):toolchain.inspect_selected_linker()

    def test_win32_version_resource_reader_and_missing_or_outside_fields(self):
        import ctypes
        from ctypes import wintypes
        import struct
        from unittest.mock import Mock, patch
        fixed = [0xfeef04bd,0x10000,(14<<16)|44,(35207<<16),0,0,0,0,0,1,0,0,0]
        rows={'\\':struct.pack('<13I',*fixed),'\\VarFileInfo\\Translation':struct.pack('<HH',0x409,0x4b0),
              '\\StringFileInfo\\040904b0\\CompanyName':'Microsoft Corporation\0'.encode('utf-16-le'),
              '\\StringFileInfo\\040904b0\\OriginalFilename':'LINK.EXE\0'.encode('utf-16-le')}
        # Native ctypes pointer contracts are exercised using an inert buffer;
        # only DLL loading and the actual three API functions are substituted.
        offsets={};position=0
        for key,data in rows.items(): offsets[key]=position;position+=len(data)
        api=Mock();api.GetFileVersionInfoSizeW.return_value=512
        def fill(path,unused,size,block):
            for key,data in rows.items():ctypes.memmove(ctypes.addressof(block)+offsets[key],data,len(data))
            return 1
        def query(block,key,address,count):
            ctypes.cast(address,ctypes.POINTER(ctypes.c_void_p)).contents.value=ctypes.addressof(block)+offsets[key]
            ctypes.cast(count,ctypes.POINTER(wintypes.UINT)).contents.value=len(rows[key])//(2 if key.startswith('\\StringFileInfo') else 1)
            return 1
        api.GetFileVersionInfoW.side_effect=fill;api.VerQueryValueW.side_effect=query
        with patch.object(toolchain.platform,'system',return_value='Windows'), \
             patch.object(toolchain.ctypes,'WinDLL',return_value=api,create=True) as loader:
            value=toolchain.file_version(Path('selected-linker.exe'))
            self.assertEqual(value,{'version':'14.44.35207.0','identities':[{'company':'Microsoft Corporation','original_filename':'LINK.EXE'}]})
            loader.assert_called_with('version.dll',use_last_error=True,winmode=0x800)
            api.VerQueryValueW.side_effect=lambda *args:0
            with self.assertRaisesRegex(ValueError,'missing selected linker version field'):toolchain.file_version(Path('selected-linker.exe'))
            def outside(block,key,address,count):
                ctypes.cast(address,ctypes.POINTER(ctypes.c_void_p)).contents.value=ctypes.addressof(block)+1024
                ctypes.cast(count,ctypes.POINTER(wintypes.UINT)).contents.value=52
                return 1
            api.VerQueryValueW.side_effect=outside
            with self.assertRaisesRegex(ValueError,'exceeds its resource'):toolchain.file_version(Path('selected-linker.exe'))
            api.GetFileVersionInfoSizeW.return_value=0
            with self.assertRaisesRegex(ValueError,'missing or oversized'):toolchain.file_version(Path('selected-linker.exe'))
