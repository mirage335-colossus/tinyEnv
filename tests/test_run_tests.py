import importlib.util
import io
from pathlib import Path
import sys
import tempfile
from types import ModuleType
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('run_tests', Path(__file__).resolve().parents[1] / 'tools/run_tests.py')
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)


class RunnerTests(unittest.TestCase):
    def result(self, body):
        class Case(unittest.TestCase):
            def runTest(self):
                body(self)
        return runner.execute(unittest.TestSuite([Case()]), stream=io.StringIO())

    def test_actual_success_is_complete(self):
        result = self.result(lambda case: case.assertEqual(2 + 3, 5))
        self.assertEqual(result['status'], 'passed')
        self.assertEqual(set(result['inventory']), set(result['results']))

    def test_internal_skip_or_subtest_failure_cannot_hide(self):
        for body in (lambda case: case.skipTest('missing prerequisite'), lambda case: case.fail('incorrect')):
            self.assertEqual(self.result(body)['status'], 'failed')
        def subtest(case):
            with case.subTest('one'):
                case.assertEqual(1, 2)
        self.assertEqual(self.result(subtest)['status'], 'failed')

    def test_empty_duplicate_inventories_rejected(self):
        with self.assertRaises(ValueError):
            runner.execute(unittest.TestSuite(), stream=io.StringIO())
        case = unittest.FunctionTestCase(lambda: None)
        with self.assertRaises(ValueError):
            runner.execute(unittest.TestSuite([case, case]), stream=io.StringIO())

    def test_registered_module_and_class_fixtures_run_once_in_order(self):
        source = '''import sys
import unittest
assert sys.modules[__name__].__dict__ is globals()
events = []
def setUpModule():
    events.append('module setup')
def tearDownModule():
    events.append('module teardown')
class First(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        events.append('first setup')
    @classmethod
    def tearDownClass(cls):
        events.append('first teardown')
    def test_one(self):
        self.assertEqual(events, ['module setup', 'first setup'])
        events.append('one')
    def test_two(self):
        self.assertEqual(events[-1], 'one')
        events.append('two')
class Second(unittest.TestCase):
    def test_three(self):
        self.assertEqual(events[-1], 'first teardown')
        events.append('three')
'''
        with tempfile.TemporaryDirectory() as temporary, patch.dict(sys.modules):
            root = Path(temporary); (root / 'tests').mkdir()
            (root / 'tests/test_fixture.py').write_text(source)
            with patch.object(runner, 'ROOT', root):
                result = runner.execute(runner.load_suite('fixture'), stream=io.StringIO())
            self.assertEqual(result['status'], 'passed')
            self.assertEqual(len(result['results']), 3)
            self.assertEqual(sys.modules['test_fixture'].events,
                             ['module setup', 'first setup', 'one', 'two',
                              'first teardown', 'three', 'module teardown'])

    def test_failed_module_import_restores_previous_registration(self):
        with tempfile.TemporaryDirectory() as temporary, patch.dict(sys.modules):
            root = Path(temporary); (root / 'tests').mkdir()
            (root / 'tests/test_fixture.py').write_text("raise ImportError('fixture import failed')\n")
            for previous in (None, ModuleType('previous_fixture')):
                if previous is None:
                    sys.modules.pop('test_fixture', None)
                else:
                    sys.modules['test_fixture'] = previous
                with patch.object(runner, 'ROOT', root), self.assertRaisesRegex(ImportError, 'fixture import failed'):
                    runner.load_suite('fixture')
                if previous is None:
                    self.assertNotIn('test_fixture', sys.modules)
                else:
                    self.assertIs(sys.modules['test_fixture'], previous)

    def test_module_setup_failure_cannot_certify_unexecuted_cases(self):
        source = '''import unittest
def setUpModule():
    raise RuntimeError('fixture setup failed')
class Case(unittest.TestCase):
    def test_unexecuted(self):
        raise AssertionError('test must not execute after fixture failure')
'''
        with tempfile.TemporaryDirectory() as temporary, patch.dict(sys.modules):
            root = Path(temporary); (root / 'tests').mkdir()
            (root / 'tests/test_fixture.py').write_text(source)
            with patch.object(runner, 'ROOT', root):
                result = runner.execute(runner.load_suite('fixture'), stream=io.StringIO())
            self.assertEqual(result['status'], 'failed')
            self.assertEqual(result['inventory'], ['test_fixture.Case.test_unexecuted'])
            self.assertNotIn(result['inventory'][0], result['results'])
            self.assertTrue(all(item['status'] == 'failed' for item in result['results'].values()))

    def test_platform_exclusion_is_explicit_and_narrow(self):
        class Named:
            def __init__(self, name): self.name = name
            def id(self): return self.name
        name = Named('test_process_tree.NativeProcessTree.test_windows_child_cannot_break_out_of_its_job')
        self.assertIsNotNone(runner.inapplicable(name, 'Linux'))
        self.assertIsNone(runner.inapplicable(name, 'Windows'))
        self.assertIsNone(runner.inapplicable(Named('unknown.missing_tool'), 'Linux'))
        pending = Named('test_agent_board.CoordinationTests.test_windows_delete_pending_mutex_requires_new_exclusive_creation')
        self.assertIsNone(runner.inapplicable(pending, 'Windows'))
        self.assertIsNotNone(runner.inapplicable(pending, 'Linux'))
        self.assertIsNone(runner.inapplicable(Named('test_agent_board.CoordinationTests.test_eight_independent_writers_preserve_every_contribution'), 'Windows'))
        self.assertIsNone(runner.inapplicable(Named('test_agent_board.CoordinationTests.test_eight_independent_writers_preserve_every_contribution'), 'Linux'))
        native = Named('test_sdk.NativeLinuxToolchainTests.test_compiler_selection')
        self.assertIsNone(runner.inapplicable(native, 'Linux'))
        self.assertIsNotNone(runner.inapplicable(native, 'Windows'))
        self.assertIsNone(runner.inapplicable(Named('test_sdk.SdkTests.test_inventory'), 'Windows'))
        linker = Named('test_build.BuildTests.test_native_windows_selected_linker_file_identity')
        self.assertIsNone(runner.inapplicable(linker, 'Windows'))
        self.assertIsNotNone(runner.inapplicable(linker, 'Linux'))
        self.assertIsNone(runner.inapplicable(Named('test_build.WindowsLinkerTests.test_invalid_identity'), 'Linux'))
        apt = Named('test_release_check.ReleaseCheckTests.test_apt_timeout_stops_descendant_before_cleanup')
        self.assertIsNone(runner.inapplicable(apt, 'Linux'))
        self.assertIsNotNone(runner.inapplicable(apt, 'Windows'))
        self.assertIsNone(runner.inapplicable(Named('test_release_check.ReleaseCheckTests.test_apt_refuses_ordinary_host_before_any_package_command'), 'Windows'))
        for name in ('test_pinned_same_source_staging_and_relocated_exact_document_launch',
                     'test_windows_gui_entry_preserves_arguments_and_console_target_kind'):
            case = Named('test_import_wasm.ImportWasmTests.' + name)
            self.assertIsNotNone(runner.inapplicable(case, 'Windows'))
            self.assertIsNone(runner.inapplicable(case, 'Linux'))
        for name in ('test_cmake_selected_build_and_direct_install_revalidate_identity',
                     'test_wrong_pin_changed_source_legacy_group_and_tampered_stage_fail'):
            self.assertIsNone(runner.inapplicable(Named('test_import_wasm.ImportWasmTests.' + name), 'Windows'))

    def test_native_rust_distro_exclusions_partition_complete_inventory_without_skips(self):
        native = {'test_native_distro_links_bind_owners_versions_link_and_runtime_notices',
                  'test_retained_target_libraries_still_reject_native_distro_links',
                  'test_native_distro_bad_dangling_escaping_chained_and_special_link_targets',
                  'test_native_distro_directory_links_and_other_library_names_are_not_allowed',
                  'test_native_distro_package_ambiguity_unowned_wrong_owner_and_versions_fail',
                  'test_native_distro_changed_target_and_retargeted_link_block_all_operations',
                  'test_native_distro_ownership_changes_and_missing_harness_family_invalidate_inputs',
                  'test_native_distro_target_replacement_during_ownership_queries_is_rejected',
                  'test_native_distro_link_text_cannot_hide_intermediate_symlink_traversal'}
        module_spec = importlib.util.spec_from_file_location(
            'test_rust_build', Path(__file__).with_name('test_rust_build.py'))
        module = importlib.util.module_from_spec(module_spec)
        module_spec.loader.exec_module(module)
        cases = list(runner.flatten(unittest.defaultTestLoader.loadTestsFromModule(module)))
        expected = {'test_rust_build.RustBuildTests.' + name for name in native}
        self.assertTrue(expected.issubset({case.id() for case in cases}))
        for case in cases:
            self.assertFalse(getattr(case, '__unittest_skip__', False))
            self.assertFalse(getattr(getattr(case, case._testMethodName), '__unittest_skip__', False))
        class InventoryCase(unittest.TestCase):
            def __init__(self, name):
                super().__init__()
                self.name = name
            def id(self):
                return self.name
            def runTest(self):
                self.assertTrue(self.name.startswith('test_rust_build.'))
        for system in ('Linux', 'Windows', 'Darwin'):
            result = runner.execute(unittest.TestSuite(InventoryCase(case.id()) for case in cases),
                                    system=system, stream=io.StringIO())
            self.assertEqual(result['status'], 'passed')
            self.assertEqual(set(result['excluded']), set() if system == 'Linux' else expected)
            self.assertFalse(set(result['excluded']) & set(result['results']))
            self.assertEqual(set(result['inventory']), set(result['excluded']) | set(result['results']))
            self.assertTrue(all(row['status'] == 'passed' for row in result['results'].values()))


if __name__ == '__main__':
    unittest.main()
