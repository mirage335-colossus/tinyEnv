"""Optional hosted lane policy and fail-closed execution contracts."""
import ast
import importlib.util
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import Mock, call, patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('rust_qualification', ROOT / '.github/scripts/rust_qualification.py')
qualification = importlib.util.module_from_spec(spec); spec.loader.exec_module(qualification)
host_spec = importlib.util.spec_from_file_location('rust_host_prepare', ROOT / '.github/scripts/rust_host_prepare.py')
host_preparation = importlib.util.module_from_spec(host_spec); host_spec.loader.exec_module(host_preparation)


class RustWorkflowTests(unittest.TestCase):
    def test_native_candidate_preparation_retains_exact_official_inputs_before_install(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for target in qualification.ci_plan.STANDARD:
                output = root / target / 'sdk'; output.parent.mkdir()
                recipe = ROOT / qualification.ci_plan.RUST_RECIPES[target]
                with self.subTest(target=target), \
                     patch.object(host_preparation.ci_plan, 'assert_host') as host, \
                     patch.object(host_preparation.rust_sdk, 'recipe_identity', return_value='a' * 64), \
                     patch.object(host_preparation.rust_sdk, 'fetch') as fetch, \
                     patch.object(host_preparation.rust_sdk, 'prepare') as prepare, \
                     patch.object(host_preparation.rust_sdk, 'install') as install, \
                     patch.object(host_preparation.rust_sdk, 'verify_group', return_value={'retained': 'b' * 64}):
                    result = host_preparation.prepare(target, output)
                host.assert_called_once_with(target)
                fetch.assert_called_once_with(recipe, output.parent / 'native-rust-inputs', network=True)
                prepare.assert_called_once_with(recipe, output.parent / 'native-rust-inputs', output.parent / 'native-rust-group')
                install.assert_called_once_with(output.parent / 'native-rust-group', 'a' * 64, output, execute=True)
                self.assertEqual(result['recipe'], 'a' * 64)
                self.assertEqual(result['files'], {'retained': 'b' * 64})

    def test_native_candidate_preparation_refuses_foreign_hosts_and_occupied_output_before_acquisition(self):
        with tempfile.TemporaryDirectory() as temporary, \
             patch.object(host_preparation.rust_sdk, 'fetch') as fetch:
            root = Path(temporary)
            with patch.object(host_preparation.ci_plan, 'assert_host', side_effect=ValueError('wrong host')):
                with self.assertRaisesRegex(ValueError, 'wrong host'):
                    host_preparation.prepare('windows-x86_64', root / 'sdk')
            with patch.object(host_preparation.ci_plan, 'assert_host'):
                with self.assertRaisesRegex(ValueError, 'must be new'):
                    host_preparation.prepare('linux-x86_64', root)
            fetch.assert_not_called()

    def test_new_workflow_entrypoints_select_rust_and_forward_legacy_provider_explicitly(self):
        for name in ('candidate', 'candidate-package', 'sdk-application', 'sdk-maintenance', 'native-gui', '_release-latest', 'screenshots'):
            with self.subTest(workflow=name):
                text = (ROOT / '.github/workflows' / (name + '.yml')).read_text()
                self.assertIn('      core_provider:', text)
                self.assertIn('        default: rust', text)
                self.assertIn('CORE_PROVIDER: ${{ inputs.core_provider }}', text)
        feedback = (ROOT / '.github/workflows/ci.yml').read_text()
        self.assertEqual(feedback.count('sudo sh tools/ci-apt.sh install rustc cargo'), 2)
        self.assertEqual(feedback.count('PATH=/usr/bin:/bin:$PATH python3'), 2)
        self.assertIn('--core-provider cpp --build-dir build/cpp-compat', feedback)
        self.assertLess(feedback.index('Prepare distribution Rust host tools'), feedback.index('Build and test inexpensive contracts'))
        self.assertLess(feedback.rindex('Prepare distribution Rust host tools'), feedback.index('Compile shared application once'))

    def test_ordinary_prepared_workflows_require_retained_rust_and_sdk_maintenance_retains_full_group(self):
        for name in ('sdk-application', 'native-gui'):
            with self.subTest(workflow=name):
                text = (ROOT / '.github/workflows' / (name + '.yml')).read_text()
                self.assertIn('lifecycle.py fetch-rust-sdk', text)
                self.assertNotIn('rust_host_prepare.py', text)
        application = (ROOT / '.github/workflows/sdk-application.yml').read_text()
        self.assertIn('build/rust-recipes.json', application)
        self.assertIn('FOUNDATION_PROVIDER_RECIPE: ${{ matrix.rust_recipe }}', application)
        maintenance = (ROOT / '.github/workflows/sdk-maintenance.yml').read_text()
        self.assertIn('BUNDLE_PATHS: build/rust-sdk-group/', maintenance)
        self.assertIn('build/rust-sdk-isolation.json', maintenance)

    def test_phase_markers_flush_and_preserve_failures(self):
        with patch('builtins.print') as output:
            with qualification.phase('fixture-success'):
                pass
            with self.assertRaisesRegex(ValueError, 'fixture failure'):
                with qualification.phase('fixture-failure'):
                    raise ValueError('fixture failure')
        self.assertEqual(output.call_args_list, [
            call('Rust qualification phase start: fixture-success', flush=True),
            call('Rust qualification phase end: fixture-success', flush=True),
            call('Rust qualification phase start: fixture-failure', flush=True),
            call('Rust qualification phase failed: fixture-failure', flush=True)])

    def test_linux_tracebacks_repeat_and_cancel_after_success_or_failure(self):
        for action in ('linux', 'qualify', 'linux-replay'):
            for error in (None, ValueError('fixture failure')):
                with self.subTest(action=action, error=error), \
                        patch.object(qualification.sys, 'argv', ['qualification', action]), \
                        patch.object(qualification.platform, 'system', return_value='Linux'), \
                        patch.object(qualification, action.replace('-', '_'), side_effect=error) as selected, \
                        patch.object(qualification.faulthandler, 'dump_traceback_later') as start, \
                        patch.object(qualification.faulthandler, 'cancel_dump_traceback_later') as cancel:
                    if error:
                        with self.assertRaisesRegex(ValueError, 'fixture failure'): qualification.main()
                    else:
                        qualification.main()
                    selected.assert_called_once_with()
                    start.assert_called_once_with(300, repeat=True)
                    cancel.assert_called_once_with()

    def test_windows_qualification_does_not_enable_linux_tracebacks(self):
        with patch.object(qualification.sys, 'argv', ['qualification', 'qualify']), \
                patch.object(qualification.platform, 'system', return_value='Windows'), \
                patch.object(qualification, 'qualify') as selected, \
                patch.object(qualification.faulthandler, 'dump_traceback_later') as start, \
                patch.object(qualification.faulthandler, 'cancel_dump_traceback_later') as cancel:
            qualification.main()
        selected.assert_called_once_with()
        start.assert_not_called()
        cancel.assert_not_called()

    def test_linux_phase_markers_keep_isolation_and_unbuffered_child_logs(self):
        names = ('linux.docker-create', 'linux.docker-start-attach', 'linux.docker-commit',
                 'linux.docker-qualify', 'linux.docker-replay', 'linux.offline')
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); (root / 'build').mkdir()
            with patch.object(qualification, 'ROOT', root), \
                    patch.object(qualification.platform, 'system', return_value='Linux'), \
                    patch.object(qualification.os, 'getuid', return_value=1000, create=True), \
                    patch.object(qualification.os, 'getgid', return_value=1000, create=True), \
                    patch.object(qualification, 'selection', return_value=('linux-x86_64',)), \
                    patch.object(qualification, 'offline') as offline, \
                    patch.object(qualification.subprocess, 'run') as run, \
                    patch.object(qualification.subprocess, 'check_output', return_value='sha256:' + 'a' * 64), \
                    patch('builtins.print') as output:
                module_spec = importlib.util.spec_from_file_location('rust_container_fixture', ROOT / '.github/scripts/container_job.py')
                with patch.object(qualification.importlib.util, 'spec_from_file_location', return_value=module_spec):
                    qualification.linux()
                offline.assert_called_once_with('sha256:' + 'a' * 64)
                messages = [item.args[0] for item in output.call_args_list]
                self.assertEqual(messages, [message for name in names for message in
                    ('Rust qualification phase start: ' + name, 'Rust qualification phase end: ' + name)])
                commands = [item.args[0] for item in run.call_args_list]
                self.assertIn('iproute2', commands[0][-1])
                qualify, replay = commands[2:4]
                self.assertIn('--init', qualify[:qualify.index('sha256:' + 'a' * 64)])
                self.assertEqual(qualify[qualify.index('--user') + 1], '1000:1000')
                self.assertNotIn('--privileged', qualify)
                self.assertEqual(qualify[qualify.index('--tmpfs') + 1], '/tmp:rw,exec,nosuid,nodev,mode=1777')
                self.assertNotIn('--init', replay)
                self.assertIn('--network=none', replay)
                self.assertIn('--read-only', replay)
                self.assertIn('--cap-drop=ALL', replay)
                self.assertIn('--security-opt=no-new-privileges', replay)
                self.assertEqual(replay[replay.index('--user') + 1], '1000:1000')
                self.assertEqual(replay[replay.index('--tmpfs') + 1], '/tmp:rw,mode=1777')
                mounts = [replay[index + 1] for index, argument in enumerate(replay) if argument == '-v']
                self.assertEqual(mounts, [str(root) + ':/work:ro', str(root / 'build/rust-replay') + ':/output'])
                for command in (qualify, replay):
                    index = command.index('python3')
                    self.assertEqual(command[index:index + 3], ['python3', '-u', '-B'])

    def test_explicit_lane_uses_four_native_hosts_and_exact_paired_recipes(self):
        ci = qualification.ci_plan
        recipes = {target: 'a' * 64 for target in ci.RUST_RECIPES}
        recipes['browser-wasm32'] = qualification.rust_sdk.checked_recipe(
            ROOT / ci.RUST_RECIPES['browser-wasm32'])['cpp_sdk_recipe_id']
        result = ci.rust_qualification_matrix(recipes)['include']
        self.assertEqual({row['target'] for row in result}, set(ci.RUST_RECIPES))
        self.assertEqual(next(row['runner'] for row in result if row['target'] == 'linux-aarch64'), 'ubuntu-24.04-arm')
        self.assertTrue(all(row['core_provider'] == 'rust' and len(row['rust_recipe']) == 64 for row in result))
        for broken in ({}, {'linux-x86_64': 'a' * 64}, dict(recipes, unknown='b' * 64)):
            with self.subTest(selection=broken), self.assertRaises(ValueError): ci.rust_qualification_matrix(broken)

    def test_network_acquisition_occurs_only_in_explicit_preparation(self):
        source = ast.parse(Path(qualification.__file__).read_text())
        callers = []
        for function in (item for item in source.body if isinstance(item, ast.FunctionDef)):
            for node in ast.walk(function):
                if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                        and isinstance(node.func.value, ast.Name) and node.func.value.id == 'rust_sdk'
                        and node.func.attr == 'fetch'):
                    callers.append(function.name)
                    self.assertTrue(any(item.arg == 'network' and isinstance(item.value, ast.Constant)
                                        and item.value.value is True for item in node.keywords))
        self.assertEqual(callers, ['prepare'])

    def test_workflow_recipe_does_not_enter_controlled_rust_environment_namespace(self):
        import rust_build
        workflow = (ROOT / '.github/workflows/rust-qualification.yml').read_text()
        self.assertIn('FOUNDATION_OPTIONAL_PROVIDER_RECIPE: ${{ matrix.rust_recipe }}', workflow)
        self.assertNotIn('      RUST_RECIPE:', workflow)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            environment = rust_build.child_environment(root, root / 'cargo', root / 'rustc', [],
                environment={'FOUNDATION_OPTIONAL_PROVIDER_RECIPE': 'a' * 64})
            self.assertEqual(environment['FOUNDATION_OPTIONAL_PROVIDER_RECIPE'], 'a' * 64)

    def test_debug_windows_selects_only_registered_native_tests(self):
        source = ast.parse(Path(qualification.__file__).read_text())
        function = next(item for item in source.body if isinstance(item, ast.FunctionDef) and item.name == 'windows_debug')
        names = next(ast.literal_eval(item.value) for item in function.body if isinstance(item, ast.Assign)
                     and any(isinstance(target, ast.Name) and target.id == 'tests' for target in item.targets))
        self.assertNotIn('integration.cxx_runtime', names)
        self.assertEqual(set(names), {'core.store', 'core.cli', 'core.text_validation', 'core.text_status',
                                     'core.windows_arguments', 'rust.unit', 'integration.install'})

    def test_debug_pe_audit_excludes_compiler_probes_and_checks_exact_consumer(self):
        import verify_pe
        names = ('foundation-cli', 'foundation_core_test', 'foundation_windows_arguments_test',
                 'foundation_rust_component_test', 'foundation_text_status_test')
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve(); build = root / 'build'; build.mkdir()
            probe = build / 'CMakeFiles/CompilerIdCXX/probe.exe'; probe.parent.mkdir(parents=True)
            probe.write_bytes(b'compiler fixture')
            paths = [*(build / (name + '.exe') for name in names), root / 'consumer.exe']
            for path in paths: path.write_bytes(b'produced fixture')
            def inspect(path):
                return {'sha256': 'a' * 64, 'machine': 0x8664, 'minimum_os': [6, 0],
                        'minimum_subsystem': [6, 0], 'imports': ['vcruntimed.dll'] if path == probe else ['kernel32.dll']}
            with patch.object(verify_pe, 'inspect', side_effect=inspect) as examined:
                with self.assertRaisesRegex(ValueError, 'shared compiler runtime'): verify_pe.audit(build)
                examined.reset_mock()
                result = qualification.windows_debug_pe(build, paths[-1])
                self.assertEqual(set(result), {path.name for path in paths})
                self.assertEqual({call.args[0] for call in examined.call_args_list}, set(paths))
                def shared_consumer(path):
                    result = inspect(path)
                    if path == paths[-1]: result['imports'] = ['vcruntimed.dll']
                    return result
                examined.side_effect = shared_consumer
                with self.assertRaisesRegex(ValueError, 'shared compiler runtime'):
                    qualification.windows_debug_pe(build, paths[-1])
                examined.side_effect = inspect
                paths[-1].unlink()
                with self.assertRaises(FileNotFoundError): qualification.windows_debug_pe(build, paths[-1])

    def test_boundary_probe_rejects_any_successful_external_connection(self):
        connection = Mock(); connection.__enter__ = Mock(return_value=connection); connection.__exit__ = Mock(return_value=False)
        with patch.object(qualification.socket, 'create_connection', return_value=connection):
            with self.assertRaisesRegex(ValueError, 'allowed an external TCP'): qualification.denial_probe()

    def test_boundary_probe_requires_external_denials_and_working_loopback(self):
        listener = Mock(); listener.__enter__ = Mock(return_value=listener); listener.__exit__ = Mock(return_value=False)
        listener.getsockname.return_value = ('127.0.0.1', 12345)
        accepted = Mock(); listener.accept.return_value = (accepted, ('127.0.0.1', 12346))
        local = Mock(); local.__enter__ = Mock(return_value=local); local.__exit__ = Mock(return_value=False)
        def connect(address, **options):
            if address[0] in ('1.1.1.1', '8.8.8.8'): raise OSError('fixture outbound denial')
            self.assertEqual(address, ('127.0.0.1', 12345))
            return local
        with patch.object(qualification.socket, 'create_connection', side_effect=connect), \
                patch.object(qualification.socket, 'socket', return_value=listener):
            result = qualification.denial_probe()
        self.assertEqual(result['loopback'], 'passed')
        self.assertEqual(len(result['external_tcp_denied']), 2)
        accepted.close.assert_called_once()

    def test_native_windows_boundary_refuses_ordinary_hosts_before_work(self):
        with patch.dict(os.environ, {}, clear=True), patch.object(qualification.platform, 'system', return_value='Windows'), \
                patch.object(qualification, 'selection') as selection:
            with self.assertRaisesRegex(ValueError, 'active disposable hosted firewall'): qualification.windows_offline()
            selection.assert_not_called()

    def test_bounded_windows_owner_joins_all_descendants_after_timeout(self):
        import process_tree
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); (root / 'build').mkdir()
            owner = Mock(); owner.wait.side_effect = subprocess.TimeoutExpired('fixture', 600)
            with patch.object(qualification, 'ROOT', root), patch.object(process_tree, 'launch', return_value=owner):
                with self.assertRaises(subprocess.TimeoutExpired): qualification.supervise_windows_offline()
            owner.wait.assert_called_once_with(timeout=600)
            owner.close.assert_called_once()
            owner.finish.assert_not_called()

    def test_workflow_retains_authenticated_groups_and_has_no_application_publication(self):
        workflow = (ROOT / '.github/workflows/rust-qualification.yml').read_text()
        self.assertIn("branches: ['codex/rust-*']", workflow)
        self.assertIn('fail-fast: false', workflow)
        self.assertIn('.github/scripts/lifecycle.py bundle-store', workflow)
        self.assertIn('build/rust-recovery/', workflow)
        self.assertNotIn('publish-candidate', workflow)
        self.assertNotIn('promote', workflow)
        self.assertNotIn('ci-evidence-publish', workflow)
        self.assertIn('if: always()', workflow)

    def test_windows_firewall_cleanup_restores_original_profiles(self):
        script = (ROOT / 'tools/rust_windows_offline.ps1').read_text()
        self.assertIn("$env:RUNNER_ENVIRONMENT -ne 'github-hosted'", script)
        self.assertIn('finally {', script)
        cleanup = script.split('} finally {', 1)[1]
        self.assertIn('Remove-NetFirewallRule -Name $taskRuleName', cleanup)
        self.assertIn('Set-NetFirewallProfile -Profile $taskProfile.Name -Enabled $taskProfile.Enabled', cleanup)
        self.assertIn('Compare-Object $taskProfiles $taskAfter -Property Name, Enabled', cleanup)
        self.assertNotIn('Set-NetFirewallProfile -Profile Domain, Private, Public -Enabled False', script)


if __name__ == '__main__': unittest.main()
