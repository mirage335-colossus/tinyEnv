"""Installed runtime selection and fail-closed repeated diagnostic evidence."""
import importlib.util
import json
from pathlib import Path, PureWindowsPath
import platform
import re
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
spec = importlib.util.spec_from_file_location('host_contracts', ROOT / 'tools/host_contracts.py')
HOST = importlib.util.module_from_spec(spec)
spec.loader.exec_module(HOST)


class HostContracts(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='host-contract-fixture-')
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.target = 'windows-x86_64' if platform.system() == 'Windows' else (
            'linux-aarch64' if HOST.architecture(platform.machine()) == 'arm64' else 'linux-x86_64')

    def cache(self, version, arch='x64', system='Windows', complete=True):
        folder = self.root / 'Python' / version / arch
        executable = folder / ('python.exe' if system == 'Windows' else 'bin/python')
        executable.parent.mkdir(parents=True, exist_ok=True)
        executable.write_bytes(b'fixture Python executable')
        if complete:
            (folder.parent / (arch + '.complete')).touch()
        return executable.resolve()

    def metadata(self, executable):
        return dict(executable=str(executable), version='3.12.10 fixture', version_info=[3, 12, 10],
                    implementation='cpython', system='Windows', machine='AMD64', bits=64, optimize=0)

    def receipt(self, status='passed'):
        return {'schema_version': 1, 'system': platform.system(), 'status': status,
                'inventory': ['fixture.one', 'fixture.other_platform'],
                'excluded': {'fixture.other_platform': 'different host'},
                'results': {'fixture.one': {'status': status}}}

    def test_cache_selects_highest_complete_stable_patch_of_requested_architecture(self):
        expected = self.cache('3.12.10')
        self.cache('3.12.9'); self.cache('3.12.99', complete=False)
        self.cache('3.12.20', arch='arm64'); self.cache('3.12.11rc1'); self.cache('3.14.7')
        with mock.patch.object(HOST.platform, 'system', return_value='Windows'), \
             mock.patch.object(HOST.platform, 'machine', return_value='AMD64'):
            self.assertEqual(HOST.interpreter('3.12', 'windows-x86_64', {'RUNNER_TOOL_CACHE': str(self.root)}), expected)
            self.assertEqual(HOST.interpreter('3.14', 'windows-x86_64', {'RUNNER_TOOL_CACHE': str(self.root)}),
                             (self.root / 'Python/3.14.7/x64/python.exe').resolve())

    def test_linux_arm_cache_uses_native_bin_python(self):
        expected = self.cache('3.14.7', 'arm64', 'Linux')
        self.cache('3.14.8', 'x64', 'Linux')
        with mock.patch.object(HOST.platform, 'system', return_value='Linux'), \
             mock.patch.object(HOST.platform, 'machine', return_value='aarch64'):
            self.assertEqual(HOST.interpreter('3.14', 'linux-aarch64', {'RUNNER_TOOL_CACHE': str(self.root)}), expected)

    def test_missing_explicit_version_never_falls_back_to_default_or_download(self):
        self.cache('3.12.10')
        with mock.patch.object(HOST.platform, 'system', return_value='Windows'), \
             mock.patch.object(HOST.platform, 'machine', return_value='AMD64'), \
             mock.patch.object(HOST.subprocess, 'run') as run:
            for environment in ({}, {'RUNNER_TOOL_CACHE': str(self.root)}):
                with self.subTest(environment=environment), self.assertRaises(ValueError):
                    HOST.interpreter('3.14', 'windows-x86_64', environment)
            run.assert_not_called()

    def test_default_and_mismatched_host_are_explicit(self):
        self.assertEqual(HOST.interpreter('runner-default', self.target, {}), Path(sys.executable).resolve())
        with mock.patch.object(HOST.platform, 'system', return_value='Linux'), \
             mock.patch.object(HOST.platform, 'machine', return_value='aarch64'):
            with self.assertRaisesRegex(ValueError, 'native host'):
                HOST.interpreter('3.12', 'windows-x86_64', {})

    def test_runtime_probe_binds_actual_executable_architecture_version_and_hash(self):
        executable = self.cache('3.12.10')
        value = self.metadata(executable)
        with mock.patch.object(HOST.subprocess, 'run', return_value=mock.Mock(stdout=json.dumps(value))) as run:
            actual = HOST.inspect_runtime(executable, '3.12', 'windows-x86_64')
            self.assertEqual(actual['sha256'], HOST.digest(executable))
            self.assertEqual(actual['version_info'], [3, 12, 10])
            self.assertEqual(run.call_args.kwargs['timeout'], 15)
        for changes in ({'version_info': [3, 14, 7]}, {'bits': 32}, {'machine': 'ARM64'},
                        {'system': 'Linux'}, {'optimize': 1}, {'implementation': 'pypy'},
                        {'executable': str(self.root)}):
            with self.subTest(changes=changes), mock.patch.object(HOST.subprocess, 'run',
                    return_value=mock.Mock(stdout=json.dumps(dict(value, **changes)))), self.assertRaises(ValueError):
                HOST.inspect_runtime(executable, '3.12', 'windows-x86_64')

    def execute(self, launch, count=5):
        executable = Path(sys.executable).resolve()
        metadata = {'sha256': HOST.digest(executable), 'version': sys.version}
        with mock.patch.object(HOST, 'interpreter', return_value=executable), \
             mock.patch.object(HOST, 'inspect_runtime', return_value=metadata), \
             mock.patch.object(HOST.process_tree, 'launch', side_effect=launch):
            return HOST.execute(self.target, 'process_tree', 'runner-default', count, self.root / 'evidence', {})

    def test_failure_remains_failed_after_later_passes_and_every_inventory_is_retained(self):
        owners = []
        def launch(command, cwd, stream, env):
            status = 'failed' if not owners else 'passed'
            report = Path(command[-1]); HOST.run_tests.publish(report, self.receipt(status))
            self.assertEqual(Path(env['TMP']), report.parent / 'scratch')
            stream.write(status.encode())
            owner = mock.Mock(); owner.wait.return_value = 1 if status == 'failed' else 0
            owners.append(owner)
            return owner
        result = self.execute(launch)
        self.assertEqual(result['status'], 'failed')
        self.assertEqual([row['status'] for row in result['repetitions']], ['failed'] + ['passed'] * 4)
        self.assertEqual(len(list((self.root / 'evidence/repetitions').glob('*/cases.json'))), 5)
        self.assertTrue(result['writers_stopped'])
        self.assertIn('*/console.log', HOST.retained_paths(self.root / 'evidence'))
        self.assertFalse(result['release_qualification'])
        self.assertEqual(result['kind'], 'host-contract-diagnostic')
        for owner in owners:
            owner.wait.assert_called_once_with(timeout=HOST.CASE_SECONDS)
            owner.finish.assert_called_once_with(); owner.close.assert_called_once_with()

    def test_timeout_stops_and_joins_before_next_repetition_and_remains_failed(self):
        owners = []
        def launch(command, cwd, stream, env):
            if owners:
                owners[-1].close.assert_called_once_with()
            owner = mock.Mock()
            if not owners:
                owner.wait.side_effect = subprocess.TimeoutExpired(command, 120)
            else:
                owner.wait.return_value = 0
                HOST.run_tests.publish(Path(command[-1]), self.receipt())
            owners.append(owner)
            return owner
        result = self.execute(launch)
        self.assertEqual(result['status'], 'failed')
        self.assertEqual(len(result['repetitions']), 5)
        owners[0].terminate.assert_called_once_with(); owners[0].close.assert_called_once_with()
        self.assertIn('bounded execution', result['repetitions'][0]['error'])

    def test_uncertain_cleanup_stops_later_repetitions_and_records_failure(self):
        owner = mock.Mock(); owner.wait.return_value = 0
        owner.close.side_effect = HOST.process_tree.ProcessTreeError('writer exit unconfirmed')
        launch = mock.Mock(return_value=owner)
        result = self.execute(launch)
        self.assertEqual(result['status'], 'failed')
        self.assertIn('writer exit unconfirmed', result['error'])
        launch.assert_called_once()
        self.assertEqual(result['repetitions'], [])
        self.assertFalse(result['writers_stopped'])
        self.assertEqual(HOST.retained_paths(self.root / 'evidence'), (self.root / 'evidence/result.json').as_posix())

    def test_windows_retention_uses_portable_slashes_for_lifecycle_transport(self):
        class WindowsPath(PureWindowsPath):
            def read_text(self, **kwargs):
                return '{"writers_stopped":true}'
        with mock.patch.object(HOST, 'Path', WindowsPath):
            self.assertEqual(HOST.retained_paths('build/host-contracts'),
                'build/host-contracts/result.json\n'
                'build/host-contracts/repetitions/*/cases.json\n'
                'build/host-contracts/repetitions/*/console.log')

    def test_zero_exit_missing_inventory_or_internal_skip_cannot_pass(self):
        for receipt in (None, self.receipt('incomplete'), dict(self.receipt(), results={}),
                        dict(self.receipt(), inventory=['fixture.one', 'fixture.one'])):
            with self.subTest(receipt=receipt):
                folder = self.root / str(len(list(self.root.iterdir())))
                def launch(command, cwd, stream, env):
                    if receipt is not None:
                        HOST.run_tests.publish(Path(command[-1]), receipt)
                    owner = mock.Mock(); owner.wait.return_value = 0
                    return owner
                with mock.patch.object(HOST.process_tree, 'launch', side_effect=launch):
                    row = HOST.repetition(Path(sys.executable), 'process_tree', folder, 1, {})
                self.assertEqual(row['status'], 'failed')

    def test_setup_failure_is_retained_without_executing_any_cases(self):
        with mock.patch.object(HOST, 'interpreter', side_effect=ValueError('unavailable version')), \
             mock.patch.object(HOST, 'repetition') as run:
            result = HOST.execute(self.target, 'process_tree', '3.14', 20, self.root / 'evidence', {})
        self.assertEqual(result['status'], 'failed'); self.assertEqual(result['repetitions'], [])
        self.assertIn('unavailable version', result['error']); run.assert_not_called()
        self.assertEqual(json.loads((self.root / 'evidence/result.json').read_text()), result)

    def test_runner_metadata_preserves_native_environment_case_rules(self):
        cases = (
            ('Windows', {'IMAGEOS': 'win22', 'IMAGEVERSION': '20261001.1'}, 'win22', '20261001.1'),
            ('Windows', {'ImageOS': 'win22', 'ImageVersion': '20261001.2'}, 'win22', '20261001.2'),
            ('Linux', {'ImageOS': 'ubuntu24', 'IMAGEOS': 'different',
                       'ImageVersion': '20261001.3'}, 'ubuntu24', '20261001.3'),
            ('Linux', {'IMAGEOS': 'different', 'IMAGEVERSION': 'different'}, '', ''),
            ('Windows', {}, '', ''),
        )
        for index, (system, environment, image_os, version) in enumerate(cases):
            with self.subTest(system=system, environment=environment), \
                 mock.patch.object(HOST.platform, 'system', return_value=system), \
                 mock.patch.object(HOST, 'interpreter', side_effect=ValueError('setup unavailable')), \
                 mock.patch.object(HOST, 'repetition') as run:
                environment = dict(environment, GITHUB_SHA='source', GITHUB_RUN_ID='123')
                result = HOST.execute(self.target, 'process_tree', '3.14', 1,
                                      self.root / ('metadata-' + str(index)), environment)
                self.assertEqual(result['workflow']['ImageOS'], image_os)
                self.assertEqual(result['workflow']['ImageVersion'], version)
                self.assertEqual(result['workflow']['GITHUB_SHA'], 'source')
                self.assertEqual(result['workflow']['GITHUB_RUN_ID'], '123')
                self.assertEqual(result['workflow']['GITHUB_RUN_ATTEMPT'], '')
                self.assertEqual(result['status'], 'failed')
                run.assert_not_called()

    def test_overall_deadline_preserves_completed_rows_but_fails_incomplete_run(self):
        clock = [0]
        def run(*args):
            clock[0] = 11
            return {'status': 'passed'}
        executable = Path(sys.executable).resolve()
        with mock.patch.object(HOST, 'interpreter', return_value=executable), \
             mock.patch.object(HOST, 'inspect_runtime', return_value={'sha256': HOST.digest(executable)}), \
             mock.patch.object(HOST, 'repetition', side_effect=run), \
             mock.patch.object(HOST, 'TOTAL_SECONDS', 10), \
             mock.patch.object(HOST.time, 'monotonic', side_effect=lambda: clock[0]):
            result = HOST.execute(self.target, 'process_tree', 'runner-default', 5, self.root / 'evidence', {})
        self.assertEqual(result['status'], 'failed'); self.assertEqual(len(result['repetitions']), 1)
        self.assertIn('remaining repetitions incomplete', result['error'])

    def test_windows_hosts_mapping_is_explicit_and_never_root_test_discovery(self):
        name, path = HOST.run_tests.suite_source('windows_hosts', 'Windows')
        self.assertEqual(name, 'diagnostic_windows_hosts')
        self.assertEqual(path, ROOT / 'tests/diagnostics/windows_hosts.py')
        self.assertNotIn(path, list((ROOT / 'tests').glob('test_*.py')))
        for system in ('Linux', 'Darwin'):
            with self.subTest(system=system), self.assertRaisesRegex(ValueError, 'native Windows'):
                HOST.run_tests.suite_source('windows_hosts', system)
        for target in ('linux-x86_64', 'linux-aarch64'):
            with self.subTest(target=target), self.assertRaisesRegex(ValueError, 'native Windows'):
                HOST.execute(target, 'windows_hosts', 'runner-default', 1, self.root / 'absent', {})
        self.assertFalse((self.root / 'absent').exists())

    def test_native_probe_binds_same_directory_linker_and_rejects_ambient_substitution(self):
        spec = importlib.util.spec_from_file_location('diagnostic_fixture', ROOT / 'tests/diagnostics/windows_hosts.py')
        probe = importlib.util.module_from_spec(spec); spec.loader.exec_module(probe)
        compiler = self.root / 'cl.exe'; compiler.write_bytes(b'compiler')
        linker = self.root / 'link.exe'; linker.write_bytes(b'linker')
        foreign = self.root / 'other-link.exe'; foreign.write_bytes(b'foreign')
        with mock.patch.object(probe.shutil, 'which', return_value=str(linker)):
            identity = probe.compiler_identity(compiler)
        self.assertEqual(identity['compiler'], {'path': str(compiler.resolve()), 'sha256': HOST.digest(compiler)})
        self.assertEqual(identity['linker'], {'path': str(linker.resolve()), 'sha256': HOST.digest(linker)})
        for path in (None, str(foreign)):
            with self.subTest(path=path), mock.patch.object(probe.shutil, 'which', return_value=path):
                with self.assertRaisesRegex(ValueError, 'ambiguous'):
                    probe.compiler_identity(compiler)
        linker.unlink()
        with self.assertRaises(FileNotFoundError):
            probe.compiler_identity(compiler)

    def test_native_probe_output_requires_actual_x64_pe_headers(self):
        spec = importlib.util.spec_from_file_location('diagnostic_fixture', ROOT / 'tests/diagnostics/windows_hosts.py')
        probe = importlib.util.module_from_spec(spec); spec.loader.exec_module(probe)
        path = self.root / 'probe.exe'
        raw = bytearray(90); raw[:2] = b'MZ'; raw[60:64] = (64).to_bytes(4, 'little')
        raw[64:68] = b'PE\0\0'; raw[68:70] = (0x8664).to_bytes(2, 'little')
        raw[86:88] = (2).to_bytes(2, 'little'); raw[88:90] = (0x20b).to_bytes(2, 'little')
        path.write_bytes(raw)
        self.assertEqual(probe.probe_identity(path), {'path': str(path.resolve()), 'sha256': HOST.digest(path),
                         'format': 'PE32+', 'machine': 'x86_64'})
        for offset, replacement in ((64, b'wrong'), (68, b'\x4c\x01'), (88, b'\x0b\x01')):
            changed = bytearray(raw); changed[offset:offset+len(replacement)] = replacement
            path.write_bytes(changed)
            with self.subTest(offset=offset), self.assertRaises(ValueError):
                probe.probe_identity(path)

    def test_native_probe_workspace_preserves_uncertain_writers_without_cleanup_retry(self):
        spec = importlib.util.spec_from_file_location('diagnostic_fixture', ROOT / 'tests/diagnostics/windows_hosts.py')
        probe = importlib.util.module_from_spec(spec); spec.loader.exec_module(probe)
        uncertain = self.root / 'uncertain'; uncertain.mkdir()
        with mock.patch.object(probe.tempfile, 'mkdtemp', return_value=str(uncertain)), \
                mock.patch.object(probe.shutil, 'rmtree') as remove:
            with self.assertRaisesRegex(probe.process_tree.ProcessTreeError, 'unconfirmed'):
                with probe.workspace(probe.process_tree.ProcessTreeError):
                    raise probe.process_tree.ProcessTreeError('unconfirmed')
            remove.assert_not_called()
        safe = self.root / 'safe'; safe.mkdir()
        with mock.patch.object(probe.tempfile, 'mkdtemp', return_value=str(safe)):
            with probe.workspace(probe.process_tree.ProcessTreeError):
                (safe / 'profile').mkdir()
        self.assertFalse(safe.exists())

    def test_native_probe_retains_bounded_logs_only_after_confirmed_cleanup(self):
        spec = importlib.util.spec_from_file_location('diagnostic_fixture', ROOT / 'tests/diagnostics/windows_hosts.py')
        probe = importlib.util.module_from_spec(spec); spec.loader.exec_module(probe)
        folder = self.root / 'probe'; folder.mkdir()
        (folder / 'compile.log').write_bytes(b'x' * 20000)
        with mock.patch.object(probe.tempfile, 'mkdtemp', return_value=str(folder)), \
                mock.patch('builtins.print') as output:
            with self.assertRaisesRegex(ValueError, 'compiler failed'):
                with probe.workspace(probe.process_tree.ProcessTreeError):
                    raise ValueError('compiler failed')
        record = json.loads(output.call_args.args[0])
        self.assertEqual(record['diagnostic_log'], 'compile.log')
        self.assertEqual(record['text'], 'x' * 16384)
        self.assertTrue(record['truncated']); self.assertFalse(folder.exists())
        folder.mkdir(); (folder / 'firefox.log').write_bytes(b'potentially live log')
        with mock.patch.object(probe.tempfile, 'mkdtemp', return_value=str(folder)), \
                mock.patch('builtins.print') as output:
            with self.assertRaises(probe.process_tree.ProcessTreeError):
                with probe.workspace(probe.process_tree.ProcessTreeError):
                    raise probe.process_tree.ProcessTreeError('unconfirmed')
        self.assertEqual(len(output.call_args_list), 1)
        self.assertFalse(json.loads(output.call_args.args[0])['writers_stopped'])
        self.assertNotIn('potentially live log', str(output.call_args_list))
        self.assertTrue(folder.exists())

    def test_windows_hosts_input_inventory_binds_helpers_probe_browser_and_selection(self):
        paths = HOST.source_files('windows_hosts', 'windows-x86_64')
        self.assertEqual(len(paths), len(set(paths)))
        self.assertEqual(set(paths), {'tools/host_contracts.py', 'tools/run_tests.py', 'tools/process_tree.py',
            'tests/diagnostics/windows_hosts.py', 'tools/windows_graphics.py', 'tools/windows_gl_probe.cpp', 'tools/windows_toolchain.py', 'tools/windows_compiler.py',
            'gui/tests/browser_test.py', 'tools/ci_windows.ps1', 'tools/select-windows-toolchain.ps1',
            'third_party/sdk/windows-toolchain.json', '.github/workflows/host-contracts.yml'})
        self.assertTrue(all((ROOT / path).is_file() for path in paths))

    def test_compiler_capable_windows_suite_owns_private_services_and_receipt(self):
        owner = mock.Mock(); owner.wait.return_value = 0
        session = mock.Mock(environment={'_MSPDBSRV_ENDPOINT_': 'private-fixture'})
        session.finish.return_value = {'policy': 'private-msvc-build-session', 'helpers': []}
        with mock.patch.object(HOST.platform, 'system', return_value='Windows'), \
             mock.patch.object(HOST.windows_compiler, 'BuildSession', return_value=session) as select, \
             mock.patch.object(HOST.process_tree, 'launch', return_value=owner) as launch, \
             mock.patch.object(HOST, 'complete_report', return_value=True):
            row = HOST.repetition(Path(sys.executable), 'import_wasm', self.root / 'owned', 120, {'PATH': 'toolkit'})
        self.assertEqual(row['status'], 'passed')
        self.assertEqual(row['compiler_completion'], session.finish.return_value)
        self.assertEqual(select.call_args.args[0]['PATH'], 'toolkit')
        self.assertEqual(launch.call_args.kwargs['env'], session.environment)
        session.finish.assert_called_once_with(owner)
        owner.finish.assert_not_called(); owner.close.assert_called_once_with()

    def test_compiler_owner_rejects_unknown_helper_and_cannot_turn_failure_into_pass(self):
        for code, error in ((0, HOST.process_tree.ProcessTreeError('unknown helper')), (1, None)):
            owner = mock.Mock(); owner.wait.return_value = code
            session = mock.Mock(environment={}); session.finish.side_effect = error
            with mock.patch.object(HOST.platform, 'system', return_value='Windows'), \
                 mock.patch.object(HOST.windows_compiler, 'BuildSession', return_value=session), \
                 mock.patch.object(HOST.process_tree, 'launch', return_value=owner), \
                 mock.patch.object(HOST, 'complete_report') as report:
                row = HOST.repetition(Path(sys.executable), 'test_plan', self.root / str(code), 120, {})
            self.assertEqual(row['status'], 'failed'); report.assert_not_called()
            owner.close.assert_called_once_with()
            if code:
                session.finish.assert_not_called(); owner.finish.assert_called_once_with()
            else:
                self.assertIn('unknown helper', row['error']); owner.terminate.assert_called_once_with()

    def test_other_diagnostics_keep_generic_process_completion(self):
        for system, suite in (('Windows', 'process_tree'), ('Windows', 'latest_release'), ('Linux', 'test_plan')):
            owner = mock.Mock(); owner.wait.return_value = 0
            with mock.patch.object(HOST.platform, 'system', return_value=system), \
                 mock.patch.object(HOST.windows_compiler, 'BuildSession') as select, \
                 mock.patch.object(HOST.process_tree, 'launch', return_value=owner), \
                 mock.patch.object(HOST, 'complete_report', return_value=True):
                row = HOST.repetition(Path(sys.executable), suite, self.root / (system + '-' + suite), 120, {})
            self.assertEqual(row['status'], 'passed'); self.assertNotIn('compiler_completion', row)
            select.assert_not_called(); owner.finish.assert_called_once_with(); owner.close.assert_called_once_with()

    def test_new_source_input_during_diagnostic_invalidates_inventory(self):
        executable = Path(sys.executable).resolve()
        with mock.patch.object(HOST, 'interpreter', return_value=executable), \
             mock.patch.object(HOST, 'inspect_runtime', return_value={'sha256': HOST.digest(executable)}), \
             mock.patch.object(HOST, 'repetition', return_value={'status': 'passed'}), \
             mock.patch.object(HOST, 'source_files', side_effect=[['tools/host_contracts.py'],
                 ['tools/host_contracts.py', 'tools/source_identity.py']]):
            result = HOST.execute(self.target, 'test_plan', 'runner-default', 1, self.root / 'evidence', {})
        self.assertEqual(result['status'], 'failed')
        self.assertIn('source changed', result['error'])
        self.assertTrue(result['writers_stopped'])

    def test_build_diagnostics_select_complete_suites_and_bind_source_inputs(self):
        maintained = set(HOST.source_identity.snapshot_paths(ROOT))
        for suite in ('test_plan', 'ci_retry', 'package_wasm', 'import_wasm'):
            with self.subTest(suite=suite):
                self.assertIn(suite, HOST.SUITES)
                _, case = HOST.run_tests.suite_source(suite, 'Windows')
                self.assertEqual(case, ROOT / ('tests/test_' + suite + '.py'))
                paths = HOST.source_files(suite, 'windows-x86_64')
                self.assertEqual(len(paths), len(set(paths)))
                self.assertEqual(set(paths), maintained)
                self.assertIn('tools/' + suite + '.py', paths)
                self.assertIn('CMakeLists.txt', paths)
                self.assertIn('.github/workflows/host-contracts.yml', paths)

    def test_coordination_diagnostic_binds_real_helper_without_compiler_setup(self):
        self.assertIn('agent_board', HOST.SUITES)
        self.assertNotIn('agent_board', HOST.BUILD_SUITES)
        _, case = HOST.run_tests.suite_source('agent_board', 'Windows')
        self.assertEqual(case, ROOT / 'tests/test_agent_board.py')
        for target in HOST.TARGETS:
            with self.subTest(target=target):
                paths = HOST.source_files('agent_board', target)
                self.assertEqual(len(paths), len(set(paths)))
                self.assertEqual(set(paths), {'tools/host_contracts.py', 'tools/run_tests.py',
                    'tools/process_tree.py', 'tests/test_agent_board.py', 'tools/agent_board.py',
                    '.github/workflows/host-contracts.yml'})

    def test_latest_release_diagnostic_binds_complete_source_without_compiler_setup(self):
        self.assertIn('latest_release', HOST.SUITES)
        self.assertNotIn('latest_release', HOST.BUILD_SUITES)
        workflow = (ROOT / '.github/workflows/host-contracts.yml').read_text()
        choices = workflow.split('      suite:\n', 1)[1].split('      interpreter:\n', 1)[0]
        options = re.search(r'^        options: \[([^\]\n]+)\]$', choices, re.M).group(1)
        self.assertIn('latest_release', [value.strip() for value in options.split(',')])
        compiler_options = re.search(r"contains\(fromJSON\('(\[[^\n]+\])'\), inputs.suite\)", workflow).group(1)
        self.assertNotIn('latest_release', json.loads(compiler_options))
        maintained = set(HOST.source_identity.snapshot_paths(ROOT))
        for target, (system, _) in HOST.TARGETS.items():
            with self.subTest(target=target):
                name, case = HOST.run_tests.suite_source('latest_release', system)
                self.assertEqual(name, 'test_latest_release')
                self.assertEqual(case, ROOT / 'tests/test_latest_release.py')
                paths = HOST.source_files('latest_release', target)
                self.assertEqual(len(paths), len(set(paths)))
                self.assertEqual(set(paths), maintained)
                for required in ('tests/test_latest_release.py', 'tools/latest_release.py',
                                 'tools/github_release.py', '.github/workflows/_release-latest.yml',
                                 '.github/workflows/host-contracts.yml'):
                    self.assertIn(required, paths)

    def test_arbitrary_commands_counts_and_reused_output_are_rejected(self):
        for target, suite, interpreter, count in ((self.target, '../run', '3.12', 1),
                (self.target, 'process_tree', '/tmp/python', 1), ('other', 'process_tree', '3.12', 1),
                (self.target, 'process_tree', '3.12', 2)):
            with self.subTest(suite=suite, count=count), self.assertRaises(ValueError):
                HOST.execute(target, suite, interpreter, count, self.root / 'new', {})
        with self.assertRaises(FileExistsError):
            HOST.execute(self.target, 'process_tree', 'runner-default', 1, self.root, {})


if __name__ == '__main__':
    unittest.main()
