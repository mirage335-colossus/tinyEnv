import importlib.util
import os
from pathlib import Path
import tempfile
import unittest

spec = importlib.util.spec_from_file_location("test_plan", Path(__file__).resolve().parents[1] / "tools/test_plan.py")
plan = importlib.util.module_from_spec(spec)
spec.loader.exec_module(plan)


class CoverageTests(unittest.TestCase):
    def test_declared_commands_include_subdirectories_but_not_fixture_builds(self):
        with tempfile.TemporaryDirectory() as directory:
            build = Path(directory)
            child = build / 'gui'; child.mkdir()
            (build / 'CTestTestfile.cmake').write_text('subdirs("gui")\n')
            declarations = child / 'CTestTestfile.cmake'
            declarations.write_text('add_test(example "old-command")\n')
            unrelated = build / 'consumer'; unrelated.mkdir()
            (unrelated / 'CTestTestfile.cmake').write_text('add_test(unrelated "ignored")\n')
            actual = plan.ctest_declarations(build)
            self.assertEqual(set(actual), {'CTestTestfile.cmake', 'gui/CTestTestfile.cmake'})
            from unittest.mock import patch
            for name in ('build-info.txt', 'test-platform.json'):
                (build / name).write_text('fixture')
            with patch.object(plan, 'source_id', return_value='source'), \
                    patch.object(plan, 'build_inputs', return_value={}):
                _, _, inputs = plan.candidate_prerequisite_inputs(build)
            self.assertEqual(set(inputs), {'CTestTestfile.cmake', 'gui/CTestTestfile.cmake',
                                           'build-info.txt', 'test-platform.json'})
            first = plan.digest(plan.normalize_locations(actual, build))
            declarations.write_text('add_test(example "changed-command")\n')
            self.assertNotEqual(first, plan.digest(plan.normalize_locations(plan.ctest_declarations(build), build)))
            declarations.write_text('subdirs("..")\n')
            with self.assertRaisesRegex(ValueError, 'duplicated'):
                plan.ctest_declarations(build)

    def test_partition_and_complete_merge(self):
        recipe = plan.make_plan(["c", "a", "b"], 2, "source")
        reports = [{"plan": recipe["id"], "shard": index, "exit_code": 0,
                    "results": {name: "passed" for name in shard}}
                   for index, shard in enumerate(recipe["shards"])]
        self.assertEqual(plan.merge(recipe, reports)["tests"], 3)
        for broken in (reports[:1], reports + reports[:1]):
            with self.assertRaises(ValueError):
                plan.merge(recipe, broken)
        reports[0]["results"]["a"] = "skipped"
        with self.assertRaises(ValueError):
            plan.merge(recipe, reports)

    def test_junit_requires_every_case(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "results.xml"
            path.write_text('<testsuite><testcase name="a" status="run"/><testcase name="b"><skipped/></testcase></testsuite>')
            self.assertEqual(plan.junit_results(path, ["a", "b"])["b"], "failed_or_incomplete")
            with self.assertRaises(ValueError):
                plan.junit_results(path, ["a", "b", "c"])

    def test_junit_timing_rejects_invalid_data_and_warns_only_for_passes(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "results.xml"
            path.write_text('<testsuite><testcase name="slow" time="8"/><testcase name="failed" time="9"><failure/></testcase><testcase name="unknown"/></testsuite>')
            limits = {"slow": 10, "failed": 10, "unknown": None}
            rows = plan.junit_timings(path, list(limits), limits)
            by_name = {row["name"]: row for row in rows}
            self.assertTrue(by_name["slow"]["near_timeout"])
            self.assertFalse(by_name["failed"]["near_timeout"])
            self.assertEqual(by_name["failed"]["status"], "failed_or_incomplete")
            self.assertIsNone(by_name["unknown"]["seconds"])
            summary = Path(tmp) / "summary.md"
            text = plan.timing_summary({"tests": rows, "phase_seconds": {"build": 1, "test": 9, "total": 11}}, "fixture", summary)
            self.assertIn("failed_or_incomplete", text)
            self.assertIn("Timeout margin warning: slow.", text)
            self.assertEqual(summary.read_text(), text + "\n")
            self.assertEqual(plan.test_timeouts([{ "name": "unlimited", "properties": [{"name": "TIMEOUT", "value": 0}]}]), {"unlimited": None})
            for value in ("nan", "inf", "-1"):
                path.write_text('<testsuite><testcase name="slow" time="' + value + '"/></testsuite>')
                with self.assertRaisesRegex(ValueError, "duration"):
                    plan.junit_timings(path, ["slow"], limits)
            with self.assertRaisesRegex(ValueError, "timeout"):
                plan.test_timeouts([{"name": "a", "properties": [{"name": "TIMEOUT", "value": float("inf")}]}])

    def test_local_plan_auto_compilation_and_explicit_legacy_overrides(self):
        import sys
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as tmp:
            build = Path(tmp); (build/'CMakeCache.txt').write_text('')
            for flags, expected in (([], 16), (['--jobs', '3'], 3), (['--jobs', '3', '--build-jobs', '7'], 7)):
                output=build/'plan.json'
                with patch.object(sys, 'argv', ['test_plan.py','plan','--build',str(build),'--shards','1','--output',str(output),*flags]), \
                     patch.object(plan, 'source_id', return_value='source'), patch.object(plan, 'build_inputs', return_value={}), \
                     patch.object(plan, 'configuration_id', return_value='configuration'), patch.object(plan, 'inventory', return_value=['test']), \
                     patch.object(plan, 'execution_context', return_value=({'cmake':'cmake'}, {})), \
                     patch.object(plan.builder, 'cache_identity', return_value={}), \
                     patch.object(plan.build_capacity, 'compile_jobs', return_value=16), \
                     patch.object(plan.windows_compiler, 'run') as run:
                    self.assertEqual(plan.main(),0)
                    self.assertEqual(run.call_args.args[0][-2:], ['--parallel',str(expected)])

    def test_candidate_workers_share_capacity_and_preserve_explicit_overrides(self):
        import subprocess, sys
        from unittest.mock import patch
        names = ['core.a', 'core.b', 'core.c', 'core.d']
        frozen = {'scopes': {'core': names}, 'timeouts': dict.fromkeys(names), 'id': 'fixture'}
        cases = [([], {}, 12, 12, 12, 3),
                 ([], {'CTEST_PARALLEL_LEVEL': '8'}, 12, 12, 8, 3),
                 (['--jobs', '3'], {'CTEST_PARALLEL_LEVEL': '8'}, 12, 12, 3, 4),
                 (['--build-jobs', '2'], {}, 12, 2, 12, 3),
                 (['--jobs', '3', '--build-jobs', '2'], {}, 12, 2, 3, 1),
                 ([], {'FOUNDATION_WORKER_BUDGET': '4'}, 4, 4, 4, 1)]
        with tempfile.TemporaryDirectory() as directory:
            build = Path(directory)
            for index, (flags, inherited, capacity, compile_jobs, test_jobs, budget) in enumerate(cases):
                output = build / (str(index) + '.json')
                environment = {'PATH': 'selected-toolkit', **inherited}
                calls = []
                def owned(argv, **options):
                    calls.append((argv, options['env']))
                    if '--output-junit' in argv:
                        Path(argv[argv.index('--output-junit') + 1]).write_text(
                            '<testsuite>' + ''.join('<testcase name="' + name + '"/>' for name in names) + '</testsuite>')
                    return subprocess.CompletedProcess(argv, 0)
                with self.subTest(flags=flags, inherited=inherited), \
                        patch.dict(os.environ, inherited, clear=True), \
                        patch.object(plan.build_capacity, 'default_jobs', return_value=capacity), \
                        patch.object(plan, 'candidate_prerequisite_inputs', return_value=()), \
                        patch.object(plan, '_candidate_observation', return_value=(frozen, None)), \
                        patch.object(plan, 'candidate_plan', return_value=frozen), \
                        patch.object(plan, 'execution_context', return_value=({'cmake': 'cmake', 'ctest': 'ctest'}, environment)), \
                        patch.object(plan.windows_compiler, 'run', side_effect=owned), \
                        patch.object(sys, 'argv', ['test_plan.py', 'candidate-run', '--build', str(build),
                                                  '--scope', 'core', '--output', str(output), *flags]):
                    self.assertEqual(plan.main(), 0)
                self.assertEqual(calls[0][0][-2:], ['--parallel', str(compile_jobs)])
                self.assertEqual(calls[0][1], environment)
                test_command, child = calls[1]
                self.assertEqual(test_command[test_command.index('--parallel') + 1], str(test_jobs))
                self.assertEqual(child['FOUNDATION_WORKER_BUDGET'], str(budget))
                self.assertEqual(child['CMAKE_BUILD_PARALLEL_LEVEL'], str(budget))
                self.assertEqual(child['CTEST_PARALLEL_LEVEL'], str(budget))
                self.assertEqual(environment, {'PATH': 'selected-toolkit', **inherited})

    def test_location_normalization_precedes_windows_json_escaping(self):
        from unittest.mock import patch
        value={'path':r'C:\work\source\main.cpp','command':['C:/work/source/test.py',r'C:\external\compiler.exe']}
        with patch.object(plan,'ROOT',r'C:\work\source'):
            normalized=plan.normalize_locations(value,Path.cwd()/'build')
        self.assertEqual(normalized,{'path':r'<SOURCE>\main.cpp','command':['<SOURCE>/test.py',r'C:\external\compiler.exe']})

    def test_windows_drive_case_normalizes_only_known_roots(self):
        from pathlib import PureWindowsPath
        from unittest.mock import patch
        class LexicalWindowsPath(PureWindowsPath):
            def absolute(self):return self
            def resolve(self):return self
        source=LexicalWindowsPath('D:/work/Source')
        build=LexicalWindowsPath('D:/work/Build')
        values={'cache': 'd:/work/Build', 'command': r'd:\work\Build\probe.exe',
                'source': 'd:/work/Source/file.cpp',
                'external': ['d:/external/compiler.exe', 'd:/work/Build-tools/compiler.exe',
                             'd:/work/build/probe.exe', 'd:work/Build']}
        with patch.object(plan,'Path',LexicalWindowsPath),patch.object(plan,'ROOT',source):
            normalized=plan.normalize_locations(values,build)
        self.assertEqual(normalized['cache'],'<BUILD>')
        self.assertEqual(normalized['command'],r'<BUILD>\probe.exe')
        self.assertEqual(normalized['source'],'<SOURCE>/file.cpp')
        self.assertEqual(normalized['external'],values['external'])

    def test_configuration_identity_normalizes_drive_case_without_hiding_external_changes(self):
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as temporary:
            build=Path(temporary).resolve();(build/'build-info.txt').write_text('fixture')
            inputs={'cache': {'CMAKE_HOME_DIRECTORY': 'd:/work/Source',
                              'EXTERNAL_TOOL': 'd:/external/Compiler.exe'}}
            commands={'CTestTestfile.cmake': 'add_test(probe "d:/work/Source/probe")'}
            with patch.object(plan,'ROOT',r'D:\work\Source'), \
                    patch.object(plan,'test_definitions',return_value=[{'name':'probe'}]), \
                    patch.object(plan,'_prerequisites',return_value=None), \
                    patch.object(plan,'build_inputs',return_value=inputs), \
                    patch.object(plan,'ctest_declarations',return_value=commands):
                first=plan.configuration_id(build,declared_commands=True)
                inputs['cache']['CMAKE_HOME_DIRECTORY']='D:/work/Source'
                self.assertEqual(first,plan.configuration_id(build,declared_commands=True))
                inputs['cache']['EXTERNAL_TOOL']='d:/external/compiler.exe'
                self.assertNotEqual(first,plan.configuration_id(build,declared_commands=True))
                inputs['cache']['EXTERNAL_TOOL']='d:/external/Compiler.exe'
                inputs['cache']['CMAKE_HOME_DIRECTORY']='d:/work/source'
                self.assertNotEqual(first,plan.configuration_id(build,declared_commands=True))

    def test_location_normalization_includes_supplied_and_resolved_roots(self):
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as temporary:
            physical = Path(temporary).resolve()
            source = physical / 'source'; source.mkdir()
            build = physical / 'build'; build.mkdir()
            declared_source = source / '..' / 'source'
            declared_build = build / '..' / 'build'
            value = [str(declared_source / 'main.cpp'), str(source / 'main.cpp'),
                     str(declared_build / 'probe'), str(build / 'probe'),
                     str(physical / 'external/compiler')]
            with patch.object(plan, 'ROOT', declared_source):
                normalized = plan.normalize_locations(value, declared_build)
            self.assertEqual(normalized[:2], ['<SOURCE>' + os.sep + 'main.cpp'] * 2)
            self.assertEqual(normalized[2:4], ['<BUILD>' + os.sep + 'probe'] * 2)
            self.assertEqual(normalized[4], value[4])

    def test_relative_build_name_is_not_replaced_in_ordinary_text(self):
        from unittest.mock import patch
        with patch.object(plan, 'ROOT', Path.cwd() / 'source'):
            value = {'command': ['build', 'rebuild', str(Path.cwd() / 'build/probe')]}
            actual = plan.normalize_locations(value, Path('build'))
        self.assertEqual(actual['command'][:2], ['build', 'rebuild'])
        self.assertEqual(actual['command'][2], '<BUILD>' + os.sep + 'probe')

    def test_location_prefix_siblings_stay_external_in_commands_and_paths(self):
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve(); source = root / 'source'; build = root / 'build'
            external = [str(root / name / 'compiler') for name in
                        ('source-cache', 'source cache', 'build-tools', 'build tools')]
            command = 'add_test(example "' + build.as_posix() + '/probe" "' + source.as_posix() + '")'
            command += '\n# Source directory: ' + source.as_posix() + '\n# Build directory: ' + build.as_posix() + '\n'
            with patch.object(plan, 'ROOT', source):
                result = plan.normalize_locations({'external': external, 'command': command}, build)
            self.assertEqual(result['external'], external)
            self.assertEqual(result['command'], 'add_test(example "<BUILD>/probe" "<SOURCE>")\n'
                             '# Source directory: <SOURCE>\n# Build directory: <BUILD>\n')

    def test_configuration_identity_preserves_declared_build_root_for_normalization(self):
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve(); source = root / 'source'; source.mkdir()
            build = root / 'build'; build.mkdir(); (build / 'build-info.txt').write_text('fixture')
            declared = build / '..' / 'build'
            commands = {'CTestTestfile.cmake': 'add_test(probe "' + declared.as_posix() + '/probe")'}
            inputs = {'cache': {'CMAKE_CACHEFILE_DIR': str(declared),
                                'EXTERNAL_TOOL': str(root / 'build-tools/compiler')}}
            with patch.object(plan, 'ROOT', source), \
                    patch.object(plan, 'test_definitions', return_value=[{'name':'probe'}]), \
                    patch.object(plan, '_prerequisites', return_value=None), \
                    patch.object(plan, 'build_inputs', return_value=inputs) as observed, \
                    patch.object(plan, 'ctest_declarations', return_value=commands), \
                    patch.object(plan, 'digest', side_effect=lambda value:value):
                identity = plan.configuration_id(declared, declared_commands=True)
            observed.assert_called_once_with(build)
            self.assertEqual(identity['inputs']['cache']['CMAKE_CACHEFILE_DIR'], '<BUILD>')
            self.assertEqual(identity['inputs']['cache']['EXTERNAL_TOOL'], inputs['cache']['EXTERNAL_TOOL'])
            self.assertEqual(identity['declarations']['CTestTestfile.cmake'], 'add_test(probe "<BUILD>/probe")')

    def test_tampered_and_empty_inventory_rejected(self):
        with self.assertRaises(ValueError):
            plan.make_plan([], 1, "source")
        recipe = plan.make_plan(["a", "b"], 2, "source")
        recipe["tests"].append("c")
        with self.assertRaises(ValueError):
            plan.validate_plan(recipe)

class ReceiptTests(unittest.TestCase):
    def test_failed_attempt_removes_stale_receipt(self):
        import json
        import subprocess
        import sys
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            invalid = root / "plan.json"
            invalid.write_text(json.dumps({"schema_version": 0}))
            for operation in ("run", "merge"):
                output = root / "previous.json"
                output.write_text('{"status":"passed"}')
                command = [sys.executable, str(Path(plan.__file__)), operation,
                           "--plan", str(invalid), "--output", str(output)]
                if operation == "run":
                    command += ["--build", str(root / "missing-build"), "--shard", "0"]
                else:
                    command += [str(root / "missing-report")]
                result = subprocess.run(command, capture_output=True)
                self.assertNotEqual(result.returncode, 0)
                self.assertFalse(output.exists())

class InputIdentityTests(unittest.TestCase):
    def setUp(self):
        import json
        from unittest.mock import patch
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.source = self.root / 'application'; self.source.mkdir()
        (self.source / 'main.cpp').write_text('int main() { return 0; }\n')
        self.build = self.root / 'build'; self.build.mkdir()
        self.compiler = self.root / 'compiler'; self.compiler.write_bytes(b'first compiler')
        self.cache = {'CMAKE_CXX_COMPILER': str(self.compiler), 'FOUNDATION_BUILD_GUI': 'OFF',
                      'FOUNDATION_DEPENDENCY_RECIPES': ''}
        (self.build / 'build-info.txt').write_text('fixture build\n')
        self.root_patch = patch.object(plan, 'ROOT', self.source); self.root_patch.start()
        self.definitions_patch = patch.object(plan, 'test_definitions', return_value=[{'name': 'core.store', 'command': ['inert']}])
        self.definitions_patch.start(); self.write_cache()

    def tearDown(self):
        self.definitions_patch.stop(); self.root_patch.stop(); self.temporary.cleanup()

    def write_cache(self):
        (self.build / 'CMakeCache.txt').write_text(''.join(name + ':STRING=' + value + '\n' for name, value in self.cache.items()))

    def freeze(self):
        return plan.make_plan(['core.store'], 1, plan.source_id(self.build), plan.configuration_id(self.build))

    def wrapper(self, **extra):
        import json
        value = {'sdk': None, 'gui': None, 'dependencies': [], 'windows_dependencies': None}
        value.update(extra)
        (self.build / 'wrapper-identity.json').write_text(json.dumps(value))
        (self.build / 'configured-identity.json').write_text(json.dumps(plan.builder.cache_identity(self.build)))
        return value

    def test_unchanged_native_tree_retains_valid_plan(self):
        frozen = self.freeze()
        plan.require_current(self.build, frozen)
        self.assertEqual(self.freeze(), frozen)

    def test_legacy_cache_and_wrapper_keep_cpp_provider_without_rust_tools(self):
        from unittest.mock import patch
        self.wrapper()
        with patch.object(plan, 'native_rust_inputs', side_effect=AssertionError('Rust tools must not be inspected')):
            inputs = plan.build_inputs(self.build)
        self.assertEqual(inputs['core_provider'], 'cpp')
        self.assertIsNone(inputs['rust_sdk'])
        self.assertNotIn('rust_tools', inputs)

    def test_compiler_bytes_change_with_unchanged_path_size_and_time(self):
        import os
        frozen = self.freeze(); stat = self.compiler.stat()
        self.compiler.write_bytes(b'other compiler')
        os.utime(self.compiler, ns=(stat.st_atime_ns, stat.st_mtime_ns))
        with self.assertRaisesRegex(ValueError, 'compiler'):
            plan.require_current(self.build, frozen)

    def test_wrapper_configured_compiler_receipt_is_reverified(self):
        self.wrapper(); self.freeze()
        self.compiler.write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError, 'configured compiler'):
            plan.build_inputs(self.build)

    def test_prepared_sdk_target_header_mutation_rejected_before_compile(self):
        import json, sys
        from unittest.mock import patch
        from test_sdk import fixture
        recipe, sdk, _, _ = fixture(self.root / 'dependency')
        self.cache.update(FOUNDATION_SDK_ROOT=str(sdk), CMAKE_CXX_COMPILER=str(sdk / 'bin/c++'))
        self.write_cache()
        # Direct CMake appends its SDK recipe outside the cache; verify that
        # ordinary SDK configurations remain supported without a wrapper stamp.
        frozen = self.freeze()
        (self.root / 'plan.json').write_text(json.dumps(frozen))
        (sdk / 'sysroot/usr/include/example.h').write_bytes(b'changed target input')
        with patch.object(sys, 'argv', ['test_plan.py', 'run', '--build', str(self.build), '--plan', str(self.root / 'plan.json'), '--shard', '0', '--output', str(self.root / 'report.json')]), patch.object(plan.windows_compiler, 'run') as run:
            with self.assertRaises(ValueError): plan.main()
            run.assert_not_called()
        self.assertFalse((self.root / 'report.json').exists())

    def test_rust_sdk_is_reverified_and_cannot_change_provider_receipt(self):
        from unittest.mock import patch
        from dependency_archive import digest
        import rust_sdk
        rust = (self.root / 'rust-sdk').resolve(); rust.mkdir()
        (rust / 'rust-sdk.json').write_text('{"fixture":1}')
        metadata = {'recipe_id': 'a' * 64}
        self.cache.update(FOUNDATION_CORE_PROVIDER='rust', FOUNDATION_RUST_SDK_ROOT=str(rust),
                          FOUNDATION_RUST_TARGET='x86_64-unknown-linux-gnu')
        self.write_cache()
        self.wrapper(core_provider='rust', rust_sdk={'root': str(rust), 'sha256': digest(rust / 'rust-sdk.json')})
        with patch.object(rust_sdk, 'verify_rust_sdk', return_value=metadata) as verify:
            first = plan.build_inputs(self.build)
            self.assertEqual(first['core_provider'], 'rust')
            verify.assert_called_once_with(rust, cpp_sdk=None, target='x86_64-unknown-linux-gnu', execute=True)
            (rust / 'rust-sdk.json').write_text('{"fixture":2}')
            with self.assertRaisesRegex(ValueError, 'Rust SDK differs'):
                plan.build_inputs(self.build)
        self.cache['FOUNDATION_CORE_PROVIDER'] = 'cpp'; self.write_cache()
        with self.assertRaisesRegex(ValueError, r'configured compiler|C\+\+ provider'):
            plan.build_inputs(self.build)

    def test_cpp_configuration_does_not_discover_rust(self):
        from unittest.mock import patch
        import rust_build, rust_sdk
        with patch.object(rust_sdk, 'verify_rust_sdk', side_effect=AssertionError('unexpected Rust SDK discovery')), \
                patch.object(rust_build, 'native_tool_identity', side_effect=AssertionError('unexpected Rust tool discovery')):
            self.assertIsNone(plan.build_inputs(self.build)['rust_sdk'])

    def native_rust(self):
        from unittest.mock import patch
        from test_rust_build import RustBuildTests
        import hashlib
        platform = patch.object(plan.sys, 'platform', 'linux'); platform.start()
        self.addCleanup(platform.stop)
        fixture = RustBuildTests('runTest'); fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        fixture.build = self.build / 'rust/Debug'
        fixture.config_path = fixture.build / 'config.json'
        description = fixture.configured()
        self.source = fixture.source
        self.root_patch.stop()
        self.root_patch = patch.object(plan, 'ROOT', self.source); self.root_patch.start()
        tools = {name: {key: row[key] for key in ('path', 'sha256', 'identity')}
                 for name, row in description['tools'].items()}
        identity = hashlib.sha256(';'.join((fixture.target, fixture.tools['rustc'], fixture.tools['cargo'],
                                            tools['rustc']['sha256'], tools['cargo']['sha256'], 'none')).encode()).hexdigest()
        self.cache.update(FOUNDATION_CORE_PROVIDER='rust', FOUNDATION_RUST_CARGO=fixture.tools['cargo'],
                          FOUNDATION_RUST_RUSTC=fixture.tools['rustc'], CMAKE_BUILD_TYPE='Debug',
                          FOUNDATION_CONFIGURED_RUST_IDENTITY=identity)
        self.write_cache()
        return fixture, tools

    def test_native_rust_direct_and_wrapper_trees_verify_declared_inputs_without_discovery(self):
        from unittest.mock import patch
        import rust_build, rust_sdk
        fixture, tools = self.native_rust()
        with patch.object(rust_build, 'select_native_tools', side_effect=AssertionError('unexpected discovery')), \
                patch.object(rust_build, '_run', side_effect=AssertionError('unexpected tool execution')), \
                patch.object(rust_sdk, 'verify_rust_sdk', side_effect=AssertionError('unexpected retained SDK')):
            direct = self.freeze(); plan.require_current(self.build, direct)
            actual = plan.build_inputs(self.build)
            self.assertIsNone(actual['rust_sdk']); self.assertEqual(actual['rust_tools'], tools)
            self.assertEqual(actual['dependencies'], [])
            self.assertEqual(set(actual['rust_configurations']), {'Debug'})
            self.wrapper(core_provider='rust', rust_sdk=None, rust_tools=tools)
            wrapped = self.freeze(); plan.require_current(self.build, wrapped)

    def test_native_rust_tool_mutation_invalidates_plans_even_with_same_size_and_mtime(self):
        import os
        fixture, _ = self.native_rust()
        frozen = self.freeze(); path = Path(fixture.tools['cargo']); before = path.stat()
        path.write_bytes(b'other'); os.utime(path, ns=(before.st_atime_ns, before.st_mtime_ns))
        with self.assertRaisesRegex(ValueError, 'selected Rust tool changed'):
            plan.require_current(self.build, frozen)

    def test_native_rust_wrapper_tool_snapshots_are_not_trusted(self):
        fixture, tools = self.native_rust()
        self.wrapper(core_provider='rust', rust_sdk=None, rust_tools=tools)
        self.freeze()
        tools['rustc']['sha256'] = '0' * 64
        self.wrapper(core_provider='rust', rust_sdk=None, rust_tools=tools)
        with self.assertRaisesRegex(ValueError, 'native Rust tools differ'):
            plan.build_inputs(self.build)

    def test_native_rust_declared_tool_paths_and_configured_identity_must_match(self):
        import shutil
        fixture, _ = self.native_rust()
        self.cache['FOUNDATION_CONFIGURED_RUST_IDENTITY'] = '0' * 64; self.write_cache()
        with self.assertRaisesRegex(ValueError, 'configured identity'):
            plan.build_inputs(self.build)
        cargo = fixture.root / 'other-cargo'; shutil.copyfile(fixture.tools['cargo'], cargo); cargo.chmod(0o755)
        self.cache['FOUNDATION_RUST_CARGO'] = str(cargo); self.write_cache()
        with self.assertRaisesRegex(ValueError, 'configured CMake selection'):
            plan.build_inputs(self.build)

    def test_native_rust_library_mutation_invalidates_plans(self):
        fixture, _ = self.native_rust()
        frozen = self.freeze()
        (fixture.libdir / 'libcore-identified.rlib').write_bytes(b'changed target input')
        with self.assertRaisesRegex(ValueError, 'target library inputs changed'):
            plan.require_current(self.build, frozen)

    def test_native_rust_notice_mutation_invalidates_plans(self):
        fixture, _ = self.native_rust()
        frozen = self.freeze(); fixture.notice.write_text('changed notice')
        with self.assertRaisesRegex(ValueError, 'notice inputs changed'):
            plan.require_current(self.build, frozen)

    def test_native_rust_config_changes_invalidate_plans_before_compilation(self):
        import json
        fixture, _ = self.native_rust()
        frozen = self.freeze()
        description = json.loads(fixture.config_path.read_text())
        description['metadata']['package_id'] = 'changed configured metadata'
        fixture.config_path.write_text(json.dumps(description))
        with self.assertRaisesRegex(ValueError, 'configuration changed'):
            plan.require_current(self.build, frozen)

    def test_native_rust_requires_complete_configurations_and_selected_tools(self):
        fixture, _ = self.native_rust()
        del self.cache['FOUNDATION_RUST_CARGO']; self.write_cache()
        with self.assertRaisesRegex(ValueError, 'missing its selected tools'):
            plan.build_inputs(self.build)
        self.cache['FOUNDATION_RUST_CARGO'] = fixture.tools['cargo']
        self.cache['CMAKE_CONFIGURATION_TYPES'] = 'Debug;Release'; self.write_cache()
        with self.assertRaises(FileNotFoundError):
            plan.build_inputs(self.build)
        self.cache['CMAKE_CONFIGURATION_TYPES'] = '../outside'; self.write_cache()
        with self.assertRaisesRegex(ValueError, 'configuration names'):
            plan.build_inputs(self.build)

    def test_native_rust_foreign_targets_and_prepared_graphs_need_retained_sdk(self):
        from unittest.mock import patch
        fixture, _ = self.native_rust()
        self.cache['FOUNDATION_RUST_TARGET'] = 'wasm32-unknown-emscripten'; self.write_cache()
        with self.assertRaisesRegex(ValueError, 'configured identity'):
            plan.build_inputs(self.build)
        self.cache.pop('FOUNDATION_RUST_TARGET')
        self.cache['FOUNDATION_WINDOWS_DEPENDENCIES'] = str(fixture.root); self.write_cache()
        with self.assertRaisesRegex(ValueError, 'retained SDK'):
            plan.build_inputs(self.build)
        self.cache.pop('FOUNDATION_WINDOWS_DEPENDENCIES'); self.write_cache()
        with patch.object(plan.sys, 'platform', 'win32'):
            with self.assertRaisesRegex(ValueError, 'retained SDK'):
                plan.build_inputs(self.build)

    def test_native_rust_multiconfig_and_no_config_match_direct_cmake_profiles(self):
        import os
        from unittest.mock import patch
        import rust_build
        fixture, _ = self.native_rust()
        for name in ('Release', 'NoConfig'):
            directory = self.build / 'rust' / name
            with patch.dict(os.environ, {}, clear=True), \
                    patch.object(rust_build, '_run', side_effect=fixture.fake_run), \
                    patch.object(rust_build.package_notices, 'distro_notice', return_value=({}, fixture.notice)):
                description = rust_build.describe(str(fixture.source), str(directory), fixture.target,
                                                  fixture.tools['cargo'], fixture.tools['rustc'], profile='release')
            rust_build.save_config(directory / 'config.json', description)
        self.cache['CMAKE_CONFIGURATION_TYPES'] = 'Debug;Release'; self.write_cache()
        self.assertEqual(set(plan.build_inputs(self.build)['rust_configurations']), {'Debug', 'Release'})
        del self.cache['CMAKE_CONFIGURATION_TYPES']; del self.cache['CMAKE_BUILD_TYPE']; self.write_cache()
        frozen = self.freeze(); plan.require_current(self.build, frozen)
        self.assertEqual(set(plan.build_inputs(self.build)['rust_configurations']), {'NoConfig'})

    def test_native_rust_configuration_cannot_switch_source_or_host(self):
        import json
        fixture, _ = self.native_rust()
        description = json.loads(fixture.config_path.read_text())
        description['tools']['rustc']['host'] = 'aarch64-unknown-linux-gnu'
        fixture.config_path.write_text(json.dumps(description))
        with self.assertRaisesRegex(ValueError, 'configured CMake selection'):
            plan.build_inputs(self.build)
        description['tools']['rustc']['host'] = fixture.target
        fixture.config_path.write_text(json.dumps(description))
        from unittest.mock import patch
        with patch.object(plan, 'ROOT', self.root):
            with self.assertRaisesRegex(ValueError, 'configured CMake selection'):
                plan.build_inputs(self.build)

    def test_native_rust_configuration_identity_normalizes_independent_build_directories(self):
        import os
        from unittest.mock import patch
        import rust_build
        fixture, _ = self.native_rust()
        first = plan.configuration_id(self.build)
        other = self.root / 'other-build'; directory = other / 'rust/Debug'
        with patch.dict(os.environ, {}, clear=True), \
                patch.object(rust_build, '_run', side_effect=fixture.fake_run), \
                patch.object(rust_build.package_notices, 'distro_notice', return_value=({}, fixture.notice)):
            description = rust_build.describe(str(fixture.source), str(directory), fixture.target,
                                              fixture.tools['cargo'], fixture.tools['rustc'])
        rust_build.save_config(directory / 'config.json', description)
        (other / 'CMakeCache.txt').write_text((self.build / 'CMakeCache.txt').read_text())
        (other / 'build-info.txt').write_text((self.build / 'build-info.txt').read_text())
        self.assertEqual(first, plan.configuration_id(other))

    def test_external_gui_bytes_change_source_identity(self):
        gui = self.root / 'gui-source'; gui.mkdir(); (gui / 'view.hpp').write_text('first input')
        self.cache.update(FOUNDATION_BUILD_GUI='ON', FOUNDATION_GUI_SOURCE=str(gui)); self.write_cache()
        frozen = self.freeze()
        (gui / 'view.hpp').write_text('other input')
        with self.assertRaisesRegex(ValueError, 'source'):
            plan.require_current(self.build, frozen)

    def test_retained_dependency_archive_mutation_is_reverified(self):
        from test_sdk import fixture
        from dependency_store import names, verify_group
        recipe, _, _, group = fixture(self.root / 'dependency')
        self.cache['FOUNDATION_DEPENDENCY_RECIPES'] = recipe; self.write_cache()
        # Match the wrapper's canonical location, including Windows short-name aliases.
        self.wrapper(dependencies=[{'root': str(group.resolve(strict=True)), 'recipe': recipe, 'files': verify_group(group, recipe)}])
        self.freeze()
        (group / names(recipe)[1]).write_bytes(b'changed source archive')
        with self.assertRaisesRegex(ValueError, 'checksum'):
            plan.build_inputs(self.build)

    def test_binary_group_scope_is_explicit_and_reverified(self):
        from test_sdk import fixture
        from dependency_store import names, verify_binary_group
        recipe, _, _, group = fixture(self.root / 'binary-dependency')
        (group / names(recipe)[1]).unlink()
        self.cache['FOUNDATION_DEPENDENCY_RECIPES'] = recipe; self.write_cache()
        entry = {'root': str(group.resolve(strict=True)), 'recipe': recipe,
                 'payload': 'binary', 'files': verify_binary_group(group, recipe)}
        self.wrapper(dependencies=[entry]); self.freeze()
        without_scope = {key:value for key,value in entry.items() if key != 'payload'}
        self.wrapper(dependencies=[without_scope])
        with self.assertRaises(ValueError): self.freeze()
        self.wrapper(dependencies=[entry])
        (group / names(recipe)[0]).write_bytes(b'changed binary payload')
        with self.assertRaisesRegex(ValueError, 'checksum'): self.freeze()

    def test_native_search_environment_change_invalidates_plan(self):
        import os
        from unittest.mock import patch
        frozen = self.freeze()
        with patch.dict(os.environ, {'CPATH': str(self.root / 'other-headers')}):
            with self.assertRaisesRegex(ValueError, 'configuration'):
                plan.require_current(self.build, frozen)

    def test_native_dependency_prefix_is_reverified_in_direct_and_wrapper_trees(self):
        from unittest.mock import patch
        root = self.root / 'inputs'; root.mkdir(); prefix = root / 'usr'; prefix.mkdir()
        self.cache['FOUNDATION_DEPENDENCY_PREFIX'] = str(root); self.write_cache()
        first = {'sha256':'a'*64, 'prefix':str(prefix.resolve())}
        with patch('prepare_dependencies.verify', return_value=first) as verify:
            frozen = self.freeze(); verify.assert_called()
            self.wrapper(dependency_prefix={'root':str(root.resolve()), **first})
            wrapped = self.freeze()
            with patch('prepare_dependencies.verify', return_value={**first, 'sha256':'b'*64}):
                with self.assertRaisesRegex(ValueError,'dependency prefix'): self.freeze()
            self.assertNotEqual(frozen['configuration'], wrapped['configuration'])
        (self.build / 'wrapper-identity.json').unlink(); (self.build / 'configured-identity.json').unlink()
        self.cache['FOUNDATION_SDK_ROOT'] = str(root); self.write_cache()
        with self.assertRaisesRegex(ValueError,'cannot mix'): self.freeze()

    def test_primary_recipe_without_retained_inputs_is_rejected(self):
        self.cache['FOUNDATION_DEPENDENCY_RECIPE'] = 'b' * 64; self.write_cache()
        with self.assertRaisesRegex(ValueError, 'complete verified'):
            self.freeze()

    def test_prepared_recipe_without_group_location_is_rejected(self):
        self.cache['FOUNDATION_DEPENDENCY_RECIPES'] = 'a' * 64; self.write_cache()
        with self.assertRaisesRegex(ValueError, 'complete verified'):
            self.freeze()

    def test_gui_group_is_verified_on_every_configuration_capture(self):
        from unittest.mock import patch
        group = self.root / 'gui-group'; group.mkdir()
        self.wrapper(gui_input_group={'root': str(group.resolve(strict=True)), 'sha256': 'a' * 64})
        with patch.object(plan, 'verify_gui_group', side_effect=['a' * 64, 'b' * 64]) as verify:
            self.freeze()
            verify.assert_called_once_with(str(group.resolve(strict=True)))
            with self.assertRaisesRegex(ValueError, 'GUI input group'):
                self.freeze()
            self.assertEqual(verify.call_count, 2)

    def test_compiler_mutation_during_prerequisite_build_leaves_no_plan(self):
        import sys
        from unittest.mock import patch
        output = self.root / 'plan.json'
        def changed(*args, **kwargs): self.compiler.write_bytes(b'changed during build')
        with patch.object(sys, 'argv', ['test_plan.py', 'plan', '--build', str(self.build), '--shards', '1', '--output', str(output)]), patch.object(plan.windows_compiler, 'run', side_effect=changed):
            with self.assertRaisesRegex(ValueError, 'compiling test prerequisites'):
                plan.main()
        self.assertFalse(output.exists())

    def test_mutation_during_test_execution_leaves_no_receipt(self):
        import json,sys,subprocess
        from unittest.mock import patch
        frozen = self.freeze(); path=self.root / 'plan.json';path.write_text(json.dumps(frozen))
        output=self.root / 'report.json';output.write_text('previous receipt')
        def runner(argv, **kwargs):
            if '--output-junit' in argv:
                Path(argv[argv.index('--output-junit')+1]).write_text('<testsuite><testcase name="core.store" status="run"/></testsuite>')
                self.compiler.write_bytes(b'changed during test')
            return subprocess.CompletedProcess(argv,0)
        with patch.object(sys, 'argv', ['test_plan.py','run','--build',str(self.build),'--plan',str(path),'--shard','0','--output',str(output)]), patch.object(plan.windows_compiler,'run',side_effect=runner):
            with self.assertRaisesRegex(ValueError,'compiler'):
                plan.main()
        self.assertFalse(output.exists())

    def test_shard_uses_automatic_capacity_and_explicit_jobs_without_repartitioning(self):
        import json, subprocess, sys
        from unittest.mock import patch
        frozen = self.freeze()
        recipe = self.root / 'frozen-plan.json'; recipe.write_text(json.dumps(frozen))
        for index, (flags, inherited, compile_jobs, test_jobs, budget) in enumerate([
                ([], {}, 12, 12, 12),
                ([], {'CTEST_PARALLEL_LEVEL': '6'}, 12, 6, 12),
                (['--jobs', '3'], {'CTEST_PARALLEL_LEVEL': '1'}, 3, 3, 3),
                (['--jobs', '3', '--build-jobs', '7'], {}, 7, 3, 7)]):
            output = self.root / (str(index) + '.json')
            environment = {'PATH': 'selected-toolkit', **inherited}
            calls = []
            def owned(argv, **options):
                calls.append((argv, options['env']))
                if '--output-junit' in argv:
                    Path(argv[argv.index('--output-junit') + 1]).write_text(
                        '<testsuite><testcase name="core.store"/></testsuite>')
                return subprocess.CompletedProcess(argv, 0)
            with self.subTest(flags=flags, inherited=inherited), \
                    patch.dict(os.environ, inherited, clear=True), \
                    patch.object(plan.build_capacity, 'default_jobs', return_value=12), \
                    patch.object(plan, 'execution_context', return_value=({'cmake': 'cmake', 'ctest': 'ctest'}, environment)), \
                    patch.object(plan.windows_compiler, 'run', side_effect=owned), \
                    patch.object(sys, 'argv', ['test_plan.py', 'run', '--build', str(self.build), '--plan', str(recipe),
                                              '--shard', '0', '--output', str(output), *flags]):
                self.assertEqual(plan.main(), 0)
            self.assertEqual(calls[0][0][-2:], ['--parallel', str(compile_jobs)])
            test_command, child = calls[1]
            self.assertEqual(test_command[test_command.index('--parallel') + 1], str(test_jobs))
            self.assertEqual(child['FOUNDATION_WORKER_BUDGET'], str(budget))
            self.assertEqual(child['CMAKE_BUILD_PARALLEL_LEVEL'], str(budget))
            self.assertEqual(child['CTEST_PARALLEL_LEVEL'], str(budget))
            self.assertEqual(json.loads(recipe.read_text()), frozen)
            self.assertEqual(json.loads(output.read_text())['results'], {'core.store': 'passed'})
            self.assertEqual(environment, {'PATH': 'selected-toolkit', **inherited})

    def owned_route(self, route, output):
        import json, sys
        from unittest.mock import patch
        if route == 'candidate':
            (self.build / 'CTestTestfile.cmake').write_text('# declaration fixture\n')
            (self.build / 'test-platform.json').write_text(json.dumps({'schema_version': 1, 'excluded_suites': {}}))
            definitions = [{'name': 'core.store', 'command': ['inert']},
                {'name': 'tools.fixture', 'properties': [{'name': 'LABELS', 'value': ['tools']}]},
                {'name': 'integration.fixture', 'properties': [{'name': 'LABELS', 'value': ['integration']}]}]
            with patch.object(plan, 'test_definitions', return_value=definitions):
                return plan.candidate_run(self.build, 'core', output, jobs=3, build_jobs=2)
        argv = ['test_plan.py', route, '--build', str(self.build), '--output', str(output), '--jobs', '2']
        if route == 'run':
            recipe = self.root / 'frozen-plan.json'; recipe.write_text(json.dumps(self.freeze()))
            argv += ['--plan', str(recipe), '--shard', '0']
        else:
            argv += ['--shards', '1']
        with patch.object(sys, 'argv', argv):
            return plan.main()

    def test_owned_ctest_nonzero_preserves_failed_receipts_and_junit(self):
        import json, subprocess
        from unittest.mock import patch
        programs = {'cmake': 'owned-cmake', 'ctest': 'owned-ctest'}
        environment = {'PATH': 'selected-toolkit'}
        for route in ('candidate', 'run'):
            with self.subTest(route=route):
                output = self.root / (route + '-failed.json')
                calls = []
                def owned(argv, **options):
                    calls.append(argv)
                    if argv[0] == programs['ctest']:
                        self.assertEqual(options['env']['PATH'], environment['PATH'])
                        self.assertGreaterEqual(int(options['env']['FOUNDATION_WORKER_BUDGET']), 1)
                        self.assertEqual(options['env']['CMAKE_BUILD_PARALLEL_LEVEL'], options['env']['FOUNDATION_WORKER_BUDGET'])
                        self.assertEqual(options['env']['CTEST_PARALLEL_LEVEL'], options['env']['FOUNDATION_WORKER_BUDGET'])
                        junit = Path(argv[argv.index('--output-junit') + 1])
                        junit.write_text('<testsuite><testcase name="core.store"><failure/></testcase></testsuite>')
                        raise subprocess.CalledProcessError(8, argv)
                    self.assertEqual(argv[0], programs['cmake'])
                    self.assertEqual(options, {'env': environment})
                    self.assertIn('foundation-tests-core' if route == 'candidate' else 'foundation-tests', argv)
                    return subprocess.CompletedProcess(argv, 0)
                with patch.object(plan, 'execution_context', return_value=(programs, environment)), \
                        patch.object(plan.windows_compiler, 'run', side_effect=owned), \
                        patch.object(plan.subprocess, 'run', side_effect=AssertionError('unowned test launch')):
                    if route == 'candidate':
                        with self.assertRaisesRegex(ValueError, 'candidate scope failed'):
                            self.owned_route(route, output)
                    else:
                        self.assertEqual(self.owned_route(route, output), 1)
                receipt = json.loads(output.read_text())
                self.assertEqual(receipt['exit_code'], 8)
                self.assertEqual(receipt['results'], {'core.store': 'failed_or_incomplete'})
                self.assertEqual([argv[0] for argv in calls], ['owned-cmake', 'owned-ctest'])
                self.assertTrue(Path(calls[-1][calls[-1].index('--output-junit') + 1]).is_file())
                self.assertEqual(environment, {'PATH': 'selected-toolkit'})

    def test_owner_and_timeout_failures_never_read_junit_or_emit_receipts(self):
        import subprocess
        from unittest.mock import patch
        import process_tree
        programs = {'cmake': 'owned-cmake', 'ctest': 'owned-ctest'}
        for route in ('candidate', 'run', 'plan'):
            for phase in ('compile', 'test') if route != 'plan' else ('compile',):
                for failure in (process_tree.ProcessTreeError('descendant join unknown'),
                                subprocess.TimeoutExpired('owned-command', 1)):
                    with self.subTest(route=route, phase=phase, failure=type(failure).__name__):
                        output = self.root / (route + '-' + phase + '-' + type(failure).__name__ + '.json')
                        def owned(argv, **options):
                            if (argv[0] == programs['cmake']) == (phase == 'compile'):
                                raise failure
                            return subprocess.CompletedProcess(argv, 0)
                        with patch.object(plan, 'execution_context', return_value=(programs, {})), \
                                patch.object(plan.windows_compiler, 'run', side_effect=owned) as run, \
                                patch.object(plan.subprocess, 'run', side_effect=AssertionError('unowned test launch')), \
                                patch.object(plan, 'junit_results', side_effect=AssertionError('unsafe JUnit read')) as read:
                            with self.assertRaises(type(failure)) as caught:
                                self.owned_route(route, output)
                        self.assertIs(caught.exception, failure)
                        self.assertEqual(run.call_count, 1 if phase == 'compile' else 2)
                        read.assert_not_called()
                        self.assertFalse(output.exists())

class NativeExecutionTests(unittest.TestCase):
    def test_actual_cmake_plan_run_and_merge(self):
        import json, subprocess, sys
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve(); source = root / 'source'; source.mkdir(); build = root / 'build'
            (source / 'CMakeLists.txt').write_text('cmake_minimum_required(VERSION 3.24)\nproject(PlanProbe LANGUAGES CXX)\nenable_testing()\nadd_executable(probe main.cpp)\nadd_custom_target(foundation-tests DEPENDS probe)\nadd_test(NAME core.probe COMMAND probe)\nfile(WRITE "${CMAKE_BINARY_DIR}/build-info.txt" "fixture\\n")\n')
            (source / 'main.cpp').write_text('int main() { return 0; }\n')
            subprocess.run(['cmake','-S',str(source),'-B',str(build),'-G','Ninja','-DCMAKE_BUILD_TYPE=Release'],check=True,capture_output=True)
            recipe = root / 'plan.json'; result = root / 'shard.json'; merged = root / 'merged.json'
            with patch.object(plan, 'ROOT', source):
                for argv in (['plan','--build',str(build),'--shards','1','--output',str(recipe)],
                             ['run','--build',str(build),'--plan',str(recipe),'--shard','0','--output',str(result)],
                             ['merge','--plan',str(recipe),'--output',str(merged),str(result)]):
                    with patch.object(sys,'argv',['test_plan.py',*argv]): self.assertEqual(plan.main(),0)
            self.assertEqual(json.loads(merged.read_text())['status'],'passed')
            self.assertEqual(json.loads(merged.read_text())['tests'],1)


class CandidateInventoryTests(unittest.TestCase):
    def test_actual_unlabelled_test_runs_and_every_scope_is_required(self):
        import json,subprocess,sys,copy
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary).resolve();source=root/'source';source.mkdir();build=root/'build'
            script=source/'fixture.py'
            script.write_text("import json,sys\nfrom pathlib import Path\np=Path(sys.argv[1]);p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps({'schema_version':1,'system':'fixture','status':'passed','inventory':['one'],'excluded':{},'results':{'one':{'status':'passed'}}}))\n")
            (source/'main.cpp').write_text('#include <fstream>\nint main(int argc, char** argv) { if (argc != 2) return 1; std::ofstream out(argv[1]); out << \"ran\"; return out ? 0 : 1; }\n')
            cmake='cmake_minimum_required(VERSION 3.24)\nproject(CandidateProbe LANGUAGES CXX)\nenable_testing()\nadd_executable(probe EXCLUDE_FROM_ALL main.cpp)\nadd_custom_target(foundation-tests DEPENDS probe)\nadd_custom_target(foundation-tests-core DEPENDS probe)\nadd_custom_target(foundation-tests-tools)\nadd_custom_target(foundation-tests-integration)\n'
            cmake+='add_test(NAME newly_unlabelled COMMAND probe "${CMAKE_BINARY_DIR}/unlabelled-ran")\n'
            cmake+='add_test(NAME tools.fixture COMMAND "'+sys.executable.replace('\\','/')+'" "${CMAKE_SOURCE_DIR}/fixture.py" "${CMAKE_BINARY_DIR}/test-reports/fixture.json")\nset_tests_properties(tools.fixture PROPERTIES LABELS tools)\n'
            cmake+='add_test(NAME integration.fixture COMMAND "${CMAKE_COMMAND}" -E true)\nset_tests_properties(integration.fixture PROPERTIES LABELS integration)\n'
            cmake+='file(WRITE "${CMAKE_BINARY_DIR}/build-info.txt" "fixture")\n'
            (source/'CMakeLists.txt').write_text(cmake)
            subprocess.run(['cmake','-S',str(source),'-B',str(build),'-G','Ninja','-DCMAKE_BUILD_TYPE=Release'],check=True,capture_output=True)
            (build/'test-platform.json').write_text(json.dumps({'schema_version':1,'excluded_suites':{'tools.unavailable':'explicit fixture platform exclusion'}}))
            paths=[]
            with patch.object(plan,'ROOT',source):
                unresolved=next(row for row in plan.test_definitions(build) if row['name']=='newly_unlabelled')
                self.assertNotIn('command',unresolved)
                frozen=plan.candidate_plan(build)
                self.assertEqual(frozen['scopes']['core'],['newly_unlabelled'])
                # Compile no unrelated executables in the tools scope, but keep
                # its complete frozen inventory identical to the eventual core.
                tools_first=root/'tools-first.json'
                plan.candidate_run(build,'tools',tools_first)
                self.assertFalse((build/'probe').exists() or (build/'probe.exe').exists())
                self.assertEqual(plan.candidate_plan(build),frozen)
                consumer=build/'unrelated-consumer';consumer.mkdir()
                (consumer/'CTestTestfile.cmake').write_text('add_test(unrelated ignored)\n')
                self.assertEqual(plan.candidate_plan(build),frozen)
                for scope in plan.CANDIDATE_SCOPES:
                    output=root/(scope+'.json');plan.candidate_run(build,scope,output,summary=root/'summary.md');paths.append(output)
                self.assertTrue((build/'unlabelled-ran').is_file())
                merged=plan.candidate_merge(paths)
                self.assertIn("Test timing: core", (root/'summary.md').read_text())
                receipt=json.loads(paths[0].read_text())
                self.assertEqual(receipt['timing']['tests'][0]['name'],'newly_unlabelled')
                self.assertIsNotNone(receipt['timing']['tests'][0]['seconds'])
                tampered=copy.deepcopy(receipt);tampered['timing']['tests'][0]['seconds']+=1
                paths[0].write_text(json.dumps(tampered))
                with self.assertRaisesRegex(ValueError,'timing'):plan.candidate_merge(paths)
                paths[0].write_text(json.dumps(receipt))
                # Separate runners compile disjoint prerequisites in distinct
                # trees. Both trees must bind exactly the same complete plan.
                twin=root/'independent-build'
                subprocess.run(['cmake','-S',str(source),'-B',str(twin),'-G','Ninja','-DCMAKE_BUILD_TYPE=Release'],check=True,capture_output=True)
                (twin/'test-platform.json').write_bytes((build/'test-platform.json').read_bytes())
                twin_tools=root/'independent-tools.json'
                plan.candidate_run(twin,'tools',twin_tools)
                self.assertFalse((twin/'probe').exists() or (twin/'probe.exe').exists())
                # Capture the complete identity at its actual digest boundary.
                # Host failures must explain the differing input without dropping
                # cache fields or weakening the independently built scope merge.
                identities=[]; real_digest=plan.digest
                def observe_identity(value):
                    if isinstance(value,dict) and {'inputs','build_info','tests','declarations'} <= value.keys():
                        identities.append(copy.deepcopy(value))
                    return real_digest(value)
                with patch.object(plan,'digest',side_effect=observe_identity):
                    plan.candidate_plan(build);plan.candidate_plan(twin)
                self.assertEqual(len(identities),2)
                differences=[]
                def compare(left,right,path='configuration'):
                    if left==right or len(differences)>=12:return
                    if isinstance(left,dict) and isinstance(right,dict) and left.keys()==right.keys():
                        for key in sorted(left):compare(left[key],right[key],path+'.'+str(key))
                    elif isinstance(left,list) and isinstance(right,list) and len(left)==len(right):
                        for index,(a,b) in enumerate(zip(left,right)):compare(a,b,path+'['+str(index)+']')
                    else:
                        a,b=repr(left),repr(right)
                        first=next((i for i,(x,y) in enumerate(zip(a,b)) if x!=y),min(len(a),len(b)))
                        begin=max(0,first-120);end=first+240
                        differences.append(path+' at offset '+str(first)+':\nfirst: '+a[begin:end]+'\ntwin: '+b[begin:end])
                compare(*identities)
                if differences:self.fail('Independent build configuration differs:\n'+'\n'.join(differences))
                self.assertEqual(plan.candidate_merge([paths[0],twin_tools,paths[2]])['plan'],merged['plan'])
                self.assertEqual(merged['mode'],'candidate');self.assertEqual(merged['plan']['platform_exclusions'],frozen['platform_exclusions'])
                for changed in (paths[:2],paths+paths[:1]):
                    with self.assertRaises(ValueError):plan.candidate_merge(changed)
                self.assertEqual(plan.candidate_merge(paths[:1],diagnostic=True)['omitted_scopes'],['integration','tools'])
                # Exercise the actual CLI with the relative receipt path used in CI.
                command=[sys.executable,'-B',str(Path(__file__).resolve().parents[1]/'tools/test_plan.py'),
                         'candidate-run','--build',str(build),'--scope','core','--output','relative.json']
                result=subprocess.run(command,cwd=root,capture_output=True,text=True)
                self.assertEqual(0,result.returncode,result.stdout+result.stderr)
                self.assertTrue((root/'relative.junit.xml').is_file())
                self.assertFalse((build/'relative.junit.xml').exists())
                row=json.loads(paths[1].read_text());row['tool_reports']['tools.fixture']['results']['one']['status']='incomplete';paths[1].write_text(json.dumps(row))
                with self.assertRaisesRegex(ValueError,'inner'):plan.candidate_merge(paths)
                original_run=plan.windows_compiler.run
                def mutate_declaration(argv, **kwargs):
                    result=original_run(argv,**kwargs)
                    if '--build' in argv:
                        declaration=build/'CTestTestfile.cmake'
                        declaration.write_text(declaration.read_text()+'# changed during prerequisite build\n')
                    return result
                with patch.object(plan.windows_compiler,'run',side_effect=mutate_declaration):
                    with self.assertRaisesRegex(ValueError,'prerequisite compilation'):
                        plan.candidate_run(build,'core',root/'changed.json')
                self.assertFalse((root/'changed.json').exists())


class PrerequisiteInventoryTests(unittest.TestCase):
    def test_exact_selection_requires_registry_and_rejects_unregistered_expansion(self):
        from unittest.mock import patch
        import json
        with tempfile.TemporaryDirectory() as directory:
            build = Path(directory)
            complete = json.dumps({'tests':[{'name':'selected'}]})
            with patch.object(plan.subprocess, 'check_output', return_value=complete), \
                    patch.object(plan.builder, 'cache_identity', return_value={}):
                with self.assertRaisesRegex(ValueError, 'complete registered'):
                    plan.named_selection(build, ['selected'], {'ctest':'ctest'}, {})
                (build / 'test-prerequisites.json').write_text(json.dumps({
                    'schema_version':1, 'tests':{'selected':[]}}))
                selected = json.dumps({'tests':[{'name':'selected'}, {'name':'unexpected'}]})
                with patch.object(plan.subprocess, 'check_output', side_effect=[complete, selected]):
                    with self.assertRaisesRegex(ValueError, 'differs from.*inventory'):
                        plan.named_selection(build, ['selected'], {'ctest':'ctest'}, {})

    def fixture(self, root, *, omitted=False, unknown=False):
        import shutil, subprocess
        source = root / 'source'; source.mkdir()
        build = root / 'build'
        module = Path(__file__).resolve().parents[1] / 'cmake/TestPrerequisites.cmake'
        shutil.copyfile(module, source / module.name)
        (source / 'main.cpp').write_text('int main() { return 0; }\n')
        script = """cmake_minimum_required(VERSION 3.24)
project(PrerequisiteProbe LANGUAGES CXX)
enable_testing()
include(TestPrerequisites.cmake)
add_executable(core EXCLUDE_FROM_ALL main.cpp)
add_executable(gui EXCLUDE_FROM_ALL main.cpp)
add_test(NAME a.core COMMAND core)
set_tests_properties(a.core PROPERTIES LABELS core)
foundation_test_prerequisites(a.core core)
add_test(NAME c.tools COMMAND "${CMAKE_COMMAND}" -E true)
set_tests_properties(c.tools PROPERTIES LABELS tools)
foundation_test_prerequisites(c.tools)
add_test(NAME d.install COMMAND "${CMAKE_COMMAND}" -E true)
set_tests_properties(d.install PROPERTIES LABELS integration)
foundation_test_prerequisites(d.install)
add_subdirectory(gui-tests)
file(WRITE "${CMAKE_BINARY_DIR}/build-info.txt" "fixture\\n")
file(WRITE "${CMAKE_BINARY_DIR}/test-platform.json" [=[{"schema_version":1,"excluded_suites":{}}]=])
cmake_language(DEFER CALL foundation_finalize_test_prerequisites)
"""
        (source / 'CMakeLists.txt').write_text(script)
        (source / 'gui-tests').mkdir()
        child = 'add_test(NAME b.gui COMMAND gui)\n'
        if not omitted:
            child += 'foundation_test_prerequisites(b.gui ' + ('missing' if unknown else 'gui') + ')\n'
        child += 'set_tests_properties(b.gui PROPERTIES LABELS gui)\n'
        (source / 'gui-tests/CMakeLists.txt').write_text(child)
        result = subprocess.run(['cmake', '-S', str(source), '-B', str(build), '-G', 'Ninja',
                                 '-DCMAKE_BUILD_TYPE=Release'], capture_output=True, text=True)
        return source, build, result

    def test_missing_or_unknown_prerequisites_fail_configuration(self):
        for option in ('omitted', 'unknown'):
            with self.subTest(option=option), tempfile.TemporaryDirectory() as directory:
                source, build, result = self.fixture(Path(directory), **{option: True})
                self.assertNotEqual(result.returncode, 0)
                self.assertIn('prerequisite', result.stdout + result.stderr)

    def test_disjoint_shards_compile_only_selected_targets_and_keep_one_plan(self):
        import json, sys, subprocess
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); source, build, result = self.fixture(root)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            recipe = root / 'plan.json'
            def invoke(*args):
                with patch.object(sys, 'argv', ['test_plan.py', *map(str, args)]):
                    self.assertEqual(plan.main(), 0)
            def exists(target):
                return (build / target).is_file() or (build / (target + '.exe')).is_file()
            with patch.object(plan, 'ROOT', source):
                invoke('plan', '--build', build, '--shards', 4, '--output', recipe)
                frozen = json.loads(recipe.read_text())
                self.assertEqual(frozen['prerequisites'], {'a.core':['core'], 'b.gui':['gui'], 'c.tools':[], 'd.install':[]})
                self.assertFalse(exists('core')); self.assertFalse(exists('gui'))
                # Script-only scope invokes no build; it must never fall back to all.
                invoke('run', '--build', build, '--plan', recipe, '--shard', 2, '--output', root/'part-2.json')
                self.assertFalse(exists('core')); self.assertFalse(exists('gui'))
                subprocess.run(['cmake', '--build', str(build), '--target', 'foundation-tests-core'], check=True, capture_output=True)
                self.assertTrue(exists('core')); self.assertFalse(exists('gui'))
                invoke('run', '--build', build, '--plan', recipe, '--shard', 0, '--output', root/'part-0.json')
                self.assertFalse(exists('gui'))
                for shard in (1, 3):
                    invoke('run', '--build', build, '--plan', recipe, '--shard', shard, '--output', root/f'part-{shard}.json')
                self.assertTrue(exists('gui'))
                (build / ('gui.exe' if (build / 'gui.exe').exists() else 'gui')).unlink()
                subprocess.run(['cmake', '--build', str(build), '--target', 'foundation-tests-gui'], check=True, capture_output=True)
                self.assertTrue(exists('gui'), 'late child-directory labels must supply their prerequisites')
                invoke('merge', '--plan', recipe, '--output', root/'merged.json', *(root/f'part-{i}.json' for i in range(4)))
                self.assertEqual(json.loads((root/'merged.json').read_text())['tests'], 4)
                # Complete identities survive the transition from unbuilt to built.
                plan.require_current(build, frozen)
                metadata = build / 'test-prerequisites.json'; original = metadata.read_text()
                changed = json.loads(original); changed['tests']['a.core'] = ['gui']
                metadata.write_text(json.dumps(changed))
                with self.assertRaisesRegex(ValueError, 'prerequisites changed'):
                    plan.require_current(build, frozen)
                metadata.write_text(original); metadata.unlink()
                with self.assertRaisesRegex(ValueError, 'inventory is missing'):
                    plan.require_current(build, frozen)

    def test_candidate_default_core_still_builds_gui_prerequisites(self):
        import json
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); source, build, result = self.fixture(root)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            with patch.object(plan, 'ROOT', source):
                frozen = plan.candidate_plan(build)
                self.assertEqual(frozen['scopes']['core'], ['a.core', 'b.gui'])
                with patch.object(plan, 'test_definitions', wraps=plan.test_definitions) as observe:
                    receipt = plan.candidate_run(build, 'core', root/'candidate.json')
                # Fresh inventory before compilation, after compilation, and after
                # execution; no duplicate CTest subprocesses inside a phase.
                self.assertEqual(observe.call_count, 3)
                self.assertEqual(receipt['results'], {'a.core':'passed', 'b.gui':'passed'})
                self.assertEqual(plan.candidate_plan(build), frozen)

    def test_malformed_incomplete_and_unsafe_target_maps_are_rejected(self):
        import json
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as directory:
            build = Path(directory); path = build/'test-prerequisites.json'
            for mapping in ({}, {'other':[]}, {'one':['--target']}, {'one':['a','a']}, {'one':'a'}):
                path.write_text(json.dumps({'schema_version':1,'tests':mapping}))
                with self.subTest(mapping=mapping), patch.object(plan, 'inventory', return_value=['one']):
                    with self.assertRaises(ValueError): plan.prerequisites(build)
