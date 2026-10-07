"""Contract/preflight tests; these do not claim an actual offline application run."""
import copy
import json
import os
from pathlib import Path
import shutil
import sys
import subprocess
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import offline_acceptance as acceptance
from dependency_archive import read_json, write_json
from dependency_store import names
import sdk
from test_sdk import fixture


@unittest.skipUnless(sys.platform.startswith('linux'), 'Bookworm acceptance contract requires Linux')
class OfflineAcceptance(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        host = patch.object(acceptance.platform, 'machine', return_value='x86_64')
        host.start(); self.addCleanup(host.stop)
        self.group = self.root / 'group with spaces'; self.group.mkdir()
        self.plan = {'schema_version': 2, 'isolation': {'kind': 'docker', 'image': 'sha256:' + 'f' * 64},
                     'cases': [{'target': 'linux-x86_64', 'group': str(self.group), 'recipe': 'a' * 64,
                                'core_provider': 'cpp'},
                               {'target': 'browser-wasm32', 'group': str(self.group), 'recipe': 'b' * 64,
                                'core_provider': 'cpp'}]}

    def test_inventory_preserves_supported_hosts_backends_and_distro_route(self):
        contract = acceptance.inventory()
        self.assertEqual(contract['core_providers'],
                         {'default': 'rust', 'optional': ['cpp'], 'automatic_fallback': False})
        self.assertEqual(contract['plan_schema'], {'current': 2, 'schema_1_requires_explicit_provider': True})
        self.assertEqual(acceptance.validate_plan(self.plan, system='Linux', machine='x86_64'),
                         ['linux-x86_64', 'browser-wasm32'])
        native = contract['native_backends']
        self.assertEqual(len(native), 6)
        for target in contract['targets']:
            self.assertEqual(target['backends'], ['wasm'] if target['target'] == 'browser-wasm32' else native)
            self.assertTrue(target['core_cli'])
        self.assertFalse(contract['ordinary_distribution_route']['retained_sdk_required'])
        self.assertIn('readelf', contract['distribution_host_tools']['native_sdk'])
        self.assertIn('complete Microsoft offline compiler/Windows SDK installer layout and component configuration',
                      next(item for item in contract['targets'] if item['target'] == 'windows-x86_64')['separate_prerequisites'])
        arm = copy.deepcopy(self.plan)
        arm['cases'] = [{'target': 'linux-aarch64', 'group': str(self.group), 'recipe': 'c' * 64,
                         'core_provider': 'cpp'}]
        self.assertEqual(acceptance.validate_plan(arm, system='Linux', machine='aarch64'), ['linux-aarch64'])

    def test_historical_plan_omissions_require_migration_before_any_launch_or_input_verification(self):
        historical = copy.deepcopy(self.plan); historical['schema_version'] = 1
        for case in historical['cases']:
            case.pop('core_provider')
        path = self.root / 'historical-plan.json'; write_json(path, historical)
        output = self.root / 'new output'
        with patch.object(acceptance, 'verify_case') as verify, \
                patch.object(acceptance.subprocess, 'run') as launch, \
                self.assertRaisesRegex(ValueError, 'schema-1.*explicit core_provider.*schema 2'):
            acceptance.run(path, output)
        verify.assert_not_called(); launch.assert_not_called(); self.assertFalse(output.exists())
        for case in historical['cases']:
            case['core_provider'] = 'cpp'
        self.assertEqual(acceptance.validate_plan(historical, system='Linux', machine='x86_64'),
                         ['linux-x86_64', 'browser-wasm32'])

    def test_new_plan_defaults_to_rust_and_requires_frozen_paired_inputs(self):
        plan = copy.deepcopy(self.plan)
        case = plan['cases'][0]; case.pop('core_provider')
        for fields in ({}, {'rust_group': str(self.group)}, {'rust_recipe': 'c' * 64}):
            with self.subTest(fields=fields), self.assertRaisesRegex(ValueError, 'retained Rust group and recipe'):
                acceptance.validate_plan({**plan, 'cases': [{**case, **fields}]},
                                         system='Linux', machine='x86_64')
        case.update(rust_group=str(self.group), rust_recipe='c' * 64)
        self.assertEqual(acceptance.validate_plan(plan, system='Linux', machine='x86_64'),
                         ['linux-x86_64', 'browser-wasm32'])
        historical = copy.deepcopy(plan); historical['schema_version'] = 1
        with self.assertRaisesRegex(ValueError, 'schema-1.*explicit core_provider'):
            acceptance.validate_plan(historical, system='Linux', machine='x86_64')
        historical['cases'][0]['core_provider'] = 'rust'
        self.assertEqual(acceptance.validate_plan(historical, system='Linux', machine='x86_64'),
                         ['linux-x86_64', 'browser-wasm32'])

    def test_plans_reject_tags_shell_fields_duplicates_and_foreign_hosts(self):
        invalid = []
        value = copy.deepcopy(self.plan); value['isolation']['image'] = 'debian:bookworm'; invalid.append(value)
        value = copy.deepcopy(self.plan); value['isolation']['command'] = 'curl supplier'; invalid.append(value)
        value = copy.deepcopy(self.plan); value['cases'][0]['arguments'] = '--online'; invalid.append(value)
        value = copy.deepcopy(self.plan); value['cases'].append(value['cases'][0].copy()); invalid.append(value)
        value = copy.deepcopy(self.plan); value['cases'][0]['recipe'] = 'short'; invalid.append(value)
        value = copy.deepcopy(self.plan); value['cases'][0]['target'] = 'linux-aarch64'; invalid.append(value)
        value = copy.deepcopy(self.plan); value['isolation'] = {'kind': 'none'}; invalid.append(value)
        value = copy.deepcopy(self.plan); value['cases'][0]['group'] = 'relative'; invalid.append(value)
        for value in invalid:
            with self.subTest(value=value), self.assertRaises(ValueError):
                acceptance.validate_plan(value, system='Linux', machine='x86_64')

    def test_rust_plans_require_a_complete_paired_group_and_preserve_explicit_cpp_plans(self):
        plan = copy.deepcopy(self.plan)
        rust_group = self.root / 'rust group'; rust_group.mkdir()
        case = plan['cases'][0]
        case.update(core_provider='rust', rust_group=str(rust_group), rust_recipe='c' * 64)
        self.assertEqual(acceptance.validate_plan(plan, system='Linux', machine='x86_64'),
                         ['linux-x86_64', 'browser-wasm32'])
        invalid = []
        for field in ('rust_group', 'rust_recipe'):
            value = copy.deepcopy(plan); value['cases'][0].pop(field); invalid.append(value)
        value = copy.deepcopy(plan); value['cases'][0]['rust_recipe'] = 'bad'; invalid.append(value)
        value = copy.deepcopy(plan); value['cases'][0]['core_provider'] = 'auto'; invalid.append(value)
        value = copy.deepcopy(plan); value['cases'][0]['core_provider'] = 'cpp'; invalid.append(value)
        for value in invalid:
            with self.subTest(case=value['cases'][0]), self.assertRaises(ValueError):
                acceptance.validate_plan(value, system='Linux', machine='x86_64')
        explicit_cpp = copy.deepcopy(self.plan); explicit_cpp['cases'][0]['core_provider'] = 'cpp'
        self.assertEqual(acceptance.validate_plan(explicit_cpp, system='Linux', machine='x86_64'),
                         acceptance.validate_plan(self.plan, system='Linux', machine='x86_64'))

    def test_cpp_group_verification_never_imports_rust_sdk(self):
        with patch.dict(sys.modules, {'rust_sdk': None}):
            result = acceptance.verify_case(self.prepared_fixture())
        self.assertEqual(result['core_provider'], 'cpp')
        self.assertNotIn('rust', result)

    def test_rust_group_preflight_pairs_metadata_and_binds_complete_archive_hashes(self):
        import rust_sdk
        case = self.prepared_fixture()
        group = self.root / 'rust group'; group.mkdir()
        case.update(core_provider='rust', rust_group=str(group), rust_recipe='c' * 64)
        metadata = {'host': {'system': 'Linux', 'processor': 'x86_64'},
                    'target': {'system': 'Linux', 'processor': 'x86_64'}}
        files = {name: 'd' * 64 for name in rust_sdk.names(case['rust_recipe'])}
        inspect = acceptance.inspect_manifest_archive
        def archive(path, member, **kwargs):
            return (metadata, None) if member == 'rust-sdk.json' else inspect(path, member, **kwargs)
        with patch.object(rust_sdk, 'verify_group', return_value=files) as verify, \
                patch.object(rust_sdk, 'verify_pair') as pair, \
                patch.object(acceptance, 'inspect_manifest_archive', side_effect=archive):
            result = acceptance.verify_case(case)
            verify.assert_called_with(group, case['rust_recipe'])
            pair.assert_called_once_with(metadata, result['metadata'])
            self.assertEqual(result['rust'], {'files': files, 'recipe': case['rust_recipe'], 'metadata': metadata})
            case.pop('core_provider')
            self.assertEqual(acceptance.verify_case(case)['core_provider'], 'rust')
            pair.side_effect = ValueError('Rust/C++ target mismatch')
            with self.assertRaisesRegex(ValueError, 'target mismatch'):
                acceptance.verify_case(case)

    def test_default_case_preflight_never_treats_missing_rust_inputs_as_cpp(self):
        case = self.prepared_fixture(); case.pop('core_provider')
        with patch.object(acceptance, 'verify_group') as verify, \
                self.assertRaisesRegex(ValueError, 'retained Rust group and recipe'):
            acceptance.verify_case(case)
        verify.assert_not_called()

    def test_rust_commands_and_environment_select_retained_tools_without_ambient_cargo_state(self):
        output = self.root / 'output'; cpp = self.root / 'cpp sdk'; rust = self.root / 'rust sdk'
        for action in ('build', 'test', 'package'):
            command = acceptance.build_arguments('linux-x86_64', cpp, output, 2, action,
                                                 rust_sdk=rust)
            self.assertEqual(command[command.index('--core-provider') + 1], 'rust')
            self.assertEqual(command[command.index('--rust-sdk') + 1], str(rust))
            self.assertEqual(command[command.index('--sdk') + 1], str(cpp))
            legacy = acceptance.build_arguments('linux-x86_64', cpp, output, 2, action, core_provider='cpp')
            self.assertEqual(legacy[legacy.index('--core-provider') + 1], 'cpp')
            self.assertNotIn('--rust-sdk', legacy)
        with self.assertRaisesRegex(ValueError, 'exact retained SDK'):
            acceptance.build_arguments('linux-x86_64', cpp, output, 2, 'build')
        for provider, extension in (('cpp', rust), ('rust', None), ('auto', None)):
            with self.subTest(provider=provider), self.assertRaises(ValueError):
                acceptance.build_arguments('linux-x86_64', cpp, output, 2, 'build',
                                           core_provider=provider, rust_sdk=extension)
        environment = acceptance.rust_environment(output, {'PATH': '/usr/bin', 'CARGO_HOME': '/ambient',
            'CARGO_TARGET_DIR': '/ambient-target', 'CARGO_BUILD_RUSTC_WRAPPER': 'wrapper',
            'RUSTFLAGS': '-C target-cpu=native', 'RUSTC_WRAPPER': 'wrapper', 'RUSTUP_HOME': '/ambient-rustup'})
        self.assertEqual(environment, {'PATH': '/usr/bin', 'CARGO_HOME': str(output / 'cargo-home'),
            'RUSTUP_HOME': str(output / 'rustup-home'), 'CARGO_NET_OFFLINE': 'true'})

    def test_rust_requests_project_the_verified_group_and_recheck_outer_inputs(self):
        from dependency_archive import digest
        for implicit, mutate in ((False, False), (False, True), (True, False), (True, True)):
            with self.subTest(implicit=implicit, mutate=mutate), tempfile.TemporaryDirectory() as directory:
                root = Path(directory).resolve(); source = root / 'source'; source.mkdir()
                (source / 'app.py').write_text('frozen source\n')
                cpp = root / 'cpp group'; cpp.mkdir(); (cpp / 'archive').write_bytes(b'cpp')
                rust = root / 'rust group'; rust.mkdir(); (rust / 'archive').write_bytes(b'rust')
                case = {'target': 'linux-x86_64', 'group': str(cpp), 'recipe': 'a' * 64,
                        'core_provider': 'rust', 'rust_group': str(rust), 'rust_recipe': 'b' * 64}
                if implicit:
                    case.pop('core_provider')
                value = copy.deepcopy(self.plan); value['cases'] = [case]
                plan = root / 'plan.json'; write_json(plan, value); output = root / 'output'
                verified = {'files': {'archive': digest(cpp / 'archive')},
                            'rust': {'files': {'archive': digest(rust / 'archive')}}}
                def command(boundary, frozen, case_output, group, uid, gid, phase, **kwargs):
                    self.assertEqual(group, cpp); self.assertEqual(kwargs, {'rust_group': rust})
                    request = read_json(case_output / 'request.json')
                    self.assertEqual(request['rust_group_files'], verified['rust']['files'])
                    self.assertEqual(request['case']['core_provider'], 'rust')
                    if phase == 'execute':
                        write_json(case_output / 'execute.json', {'status': 'passed'})
                        if mutate:
                            (rust / 'archive').write_bytes(b'changed after launch')
                    return ['boundary', phase]
                with patch.object(acceptance, 'verify_case', return_value=verified), \
                        patch.object(acceptance, 'docker_phase', side_effect=command) as phases, \
                        patch.object(acceptance.subprocess, 'run', return_value=subprocess.CompletedProcess(
                            [], 0, value['isolation']['image'] + '\n', '')):
                    if mutate:
                        with self.assertRaisesRegex(ValueError, 'retained group changed outside'):
                            acceptance.run(plan, output, ['linux-x86_64'], root=source)
                    else:
                        report = acceptance.run(plan, output, ['linux-x86_64'], root=source)
                        self.assertEqual(report['requested_providers'], {'linux-x86_64': 'rust'})
                        self.assertEqual(report['cases'][0]['core_provider'], 'rust')
                        self.assertEqual(report['input_recheck'], 'passed')
                    self.assertEqual(phases.call_count, 2)
                self.assertEqual(read_json(output / 'acceptance.json')['status'], 'failed' if mutate else 'passed')

    def test_old_projected_request_without_provider_is_rejected_without_reinterpretation(self):
        request = {'case': {'target': 'linux-x86_64', 'group': str(self.group), 'recipe': 'a' * 64}}
        with patch.object(acceptance, 'read_json', return_value=request), \
                patch.object(acceptance, 'verify_case') as verify, \
                patch.object(acceptance, 'checked_command') as launch, \
                self.assertRaisesRegex(ValueError, 'projected offline requests require an explicit core_provider'):
            acceptance.inside('stage', Path('/output/request.json'))
        verify.assert_not_called(); launch.assert_not_called()

    def test_rust_sdk_readonly_receipt_requires_the_mount_and_a_filesystem_write_rejection(self):
        import errno
        from types import SimpleNamespace
        with patch.object(acceptance.os, 'statvfs', return_value=SimpleNamespace(f_flag=os.ST_RDONLY)), \
                patch.object(acceptance.os, 'open', side_effect=OSError(errno.EROFS, 'read-only')) as write:
            self.assertEqual(acceptance.readonly_sdk(self.root),
                             {'mount_readonly': True, 'write_rejection_errno': errno.EROFS})
            self.assertEqual(write.call_count, 1)
            write.side_effect = OSError(errno.EACCES, 'permissions')
            with self.assertRaisesRegex(ValueError, 'read-only filesystem'):
                acceptance.readonly_sdk(self.root)
        with patch.object(acceptance.os, 'statvfs', return_value=SimpleNamespace(f_flag=0)), \
                patch.object(acceptance.os, 'open') as write, self.assertRaisesRegex(ValueError, 'read-only mount'):
            acceptance.readonly_sdk(self.root)
        write.assert_not_called()

    def test_default_requires_wasm_inputs_and_narrow_selection_never_implies_full_inventory(self):
        plan = copy.deepcopy(self.plan); plan['cases'].pop()
        path = self.root / 'plan.json'; write_json(path, plan)
        output = self.root / 'new output'
        with self.assertRaisesRegex(ValueError, 'missing retained inputs'), patch.object(acceptance.subprocess, 'run') as launch:
            acceptance.run(path, output)
        launch.assert_not_called()
        self.assertFalse(output.exists())

    def prepared_fixture(self, *, capabilities=None, processor='x86_64', host_processor='x86_64'):
        recipe, tree, sources, group = fixture(self.root / 'sdk fixture')
        metadata = read_json(tree / 'sdk.json')
        metadata['target']['processor'] = processor
        metadata['capabilities'] = capabilities or acceptance.inventory()['native_backends']
        if host_processor is None:
            metadata['host'].pop('processor')
        else:
            metadata['host']['processor'] = host_processor
        write_json(tree / 'sdk.json', metadata)
        shutil.rmtree(group)
        sdk.export_group(tree, sources, group)
        return {'target': 'linux-x86_64', 'group': str(group), 'recipe': recipe, 'core_provider': 'cpp'}

    def test_complete_group_integrity_and_capabilities_are_verified_without_repair(self):
        case = self.prepared_fixture()
        result = acceptance.verify_case(case)
        self.assertEqual(set(result['files']), set(names(case['recipe'])))
        (Path(case['group']) / names(case['recipe'])[1]).write_bytes(b'corrupt retained sources')
        with self.assertRaisesRegex(ValueError, 'checksum'):
            acceptance.verify_case(case)
        with self.assertRaisesRegex(ValueError, 'missing|directory'):
            acceptance.verify_case({**case, 'group': str(self.root / 'absent')})

    def test_wrong_native_architecture_and_incomplete_gui_sdk_fail(self):
        for capabilities, machine, message in ((['core', 'terminal'], 'x86_64', 'capabilities'),
                                                (None, 'aarch64', 'architecture')):
            with self.subTest(machine=machine, capabilities=capabilities), tempfile.TemporaryDirectory() as name:
                original = self.root
                self.root = Path(name).resolve()
                try:
                    with self.assertRaisesRegex(ValueError, message):
                        acceptance.verify_case(self.prepared_fixture(capabilities=capabilities, processor=machine))
                finally:
                    self.root = original

    def test_one_tree_per_target_and_existing_build_entrypoint(self):
        output = self.root / 'output'; retained = self.root / 'installed sdk'
        for target in ('linux-x86_64', 'linux-aarch64', 'browser-wasm32'):
            commands = [acceptance.build_arguments(target, retained, output, 3, action, core_provider='cpp')
                        for action in ('build', 'test', 'package')]
            for command in commands:
                self.assertEqual(command[2], str(acceptance.ROOT / 'tools/build.py'))
                self.assertEqual(command[command.index('--build-dir') + 1], str(output / 'build'))
                self.assertEqual(command[command.index('--sdk') + 1], str(retained))
                self.assertIn('--gui', command)
                backends = command[command.index('--gui-backends') + 1].split(',')
                self.assertEqual(backends, ['wasm'] if target == 'browser-wasm32' else acceptance.inventory()['native_backends'])
                self.assertNotIn('--full', command)
            self.assertIn('--label', commands[1])

    def test_missing_sdk_host_architecture_never_defaults_to_the_current_host(self):
        with self.assertRaisesRegex(ValueError, 'different native host'):
            acceptance.verify_case(self.prepared_fixture(host_processor=None))

    def test_output_overlap_is_rejected_before_input_verification_or_writes(self):
        rootfs = self.root / 'prepared rootfs'; rootfs.mkdir()
        manifest = self.root / 'rootfs.json'; manifest.write_text('{}')
        value = copy.deepcopy(self.plan)
        value['isolation'] = {'kind': 'namespace', 'rootfs': str(rootfs), 'manifest': str(manifest), 'manifest_sha256': 'a' * 64}
        path = self.root / 'overlap-plan.json'; write_json(path, value)
        output = rootfs / 'new output'
        with patch.object(acceptance, 'verify_case') as verify, self.assertRaisesRegex(ValueError, 'rootfs must be disjoint'):
            acceptance.run(path, output)
        verify.assert_not_called(); self.assertFalse(output.exists())
        source = self.root / 'application source'; source.mkdir()
        write_json(path, self.plan)
        with patch.object(acceptance, 'verify_case') as verify, self.assertRaisesRegex(ValueError, 'nonignored application source'):
            acceptance.run(path, source / 'new output', root=source)
        verify.assert_not_called(); self.assertFalse((source / 'new output').exists())

    def test_junit_requires_both_core_tests_with_no_skips_failures_or_disabled_cases(self):
        path = self.root / 'core.junit.xml'
        valid = '<testsuite tests="2" failures="0" skipped="0"><testcase name="core.store" status="run"/><testcase name="core.cli" status="run"/></testsuite>'
        path.write_text(valid)
        result = acceptance.verify_core_junit(path)
        self.assertEqual(result['count'], 2)
        self.assertEqual(result['tests'], ['core.cli', 'core.store'])
        invalid = [valid.replace('name="core.cli"', 'name="typo"'),
                   valid.replace('name="core.cli" status="run"/>', 'name="core.cli" status="run"><skipped/></testcase>'),
                   valid.replace('name="core.cli" status="run"/>', 'name="core.cli" status="run"><failure/></testcase>'),
                   valid.replace('status="run"', 'status="notrun"'), valid.replace('skipped="0"', 'skipped="1"')]
        for document in invalid:
            with self.subTest(document=document):
                path.write_text(document)
                with self.assertRaises(ValueError): acceptance.verify_core_junit(path)

    def test_current_core_inventory_requires_component_and_fail_closed_tests(self):
        required = ('core.store', 'core.cli', 'core.text_validation', 'core.text_status')
        path = self.root / 'current-core.junit.xml'
        cases = ''.join('<testcase name="' + name + '" status="run"/>' for name in required)
        path.write_text('<testsuite tests="4" failures="0">' + cases + '</testsuite>')
        result = acceptance.verify_core_junit(path, required)
        self.assertEqual(result['count'], 4)
        self.assertEqual(result['tests'], sorted(required))
        path.write_text('<testsuite>' + cases.replace('<testcase name="core.text_status" status="run"/>', '') + '</testsuite>')
        with self.assertRaisesRegex(ValueError, 'complete required core inventory'):
            acceptance.verify_core_junit(path, required)

    def test_snapshot_contains_only_application_inputs_and_complete_source_identity(self):
        source = self.root / 'checkout'; source.mkdir()
        (source / 'app.py').write_text('retained application\n')
        for name in ('build', '.agent-work', '__pycache__'):
            (source / name).mkdir(); (source / name / 'ambient').write_text('must not mount\n')
        frozen = self.root / 'frozen source'
        identity = acceptance.snapshot(source, frozen)
        self.assertEqual(set(identity['files']), {'app.py'})
        self.assertEqual(set(path.name for path in frozen.iterdir()), {'app.py', 'source.json'})
        (source / 'linked').symlink_to(self.root / 'outside')
        with self.assertRaisesRegex(ValueError, 'linked|escaping'):
            acceptance.snapshot(source, self.root / 'rejected source')

    def test_missing_declared_tool_fails_with_an_actionable_error(self):
        with self.assertRaisesRegex(ValueError, 'required-builder'):
            acceptance.tool_identity('required-builder', str(self.root / 'absent-tool'))

    def test_usrmerge_package_lookup_uses_only_verified_same_file_aliases(self):
        physical = Path('/usr/bin/sh').resolve(strict=True)
        lexical = Path('/bin/sh')
        calls = []
        def lookup(command, **kwargs):
            calls.append(command)
            return subprocess.CompletedProcess(command, 0 if command[-1] == str(lexical) else 1,
                                               'dash: /bin/sh\n' if command[-1] == str(lexical) else '', '')
        with patch.object(acceptance.subprocess, 'run', side_effect=lookup):
            completed = acceptance.distribution_owner(physical, lexical)
        self.assertEqual(completed.args[-1], str(lexical))
        self.assertTrue(all(Path(command[-1]).samefile(physical) for command in calls))
        unrelated = self.root / 'different tool'; unrelated.write_text('unrelated')
        with patch.object(acceptance.subprocess, 'run', return_value=subprocess.CompletedProcess([], 1, '', '')) as run:
            with self.assertRaisesRegex(ValueError, 'lacks distribution package ownership'):
                acceptance.distribution_owner(physical, unrelated)
        self.assertNotIn(str(unrelated), [call.args[0][-1] for call in run.call_args_list])


if __name__ == '__main__':
    unittest.main()
