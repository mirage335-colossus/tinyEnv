#!/usr/bin/env python3
"""Run a complete registered unit suite and expose every case and exclusion."""
import argparse
import importlib.util
import json
import os
from pathlib import Path
import platform
import re
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


def flatten(suite):
    for item in suite:
        if isinstance(item, unittest.TestSuite):
            yield from flatten(item)
        else:
            yield item


def inapplicable(case, system):
    """Only platform facts exclude cases; missing tools/permissions are failures."""
    name = case.id()
    if system != 'Windows' and name == 'test_agent_board.CoordinationTests.test_windows_delete_pending_mutex_requires_new_exclusive_creation':
        return 'Native Windows delete-pending directory handle semantics belong to Windows runners.'
    if system != 'Windows' and name == 'test_build.BuildTests.test_native_windows_selected_linker_file_identity':
        return 'Native Win32 linker file identity inspection belongs to Windows runners.'
    if system != 'Linux' and name.startswith('test_sdk.NativeLinuxToolchainTests.'):
        return 'Native Linux retained C/C++ compiler fixture belongs to Linux runners.'
    if system != 'Linux' and name in {
            'test_rust_build.RustBuildTests.test_native_distro_links_bind_owners_versions_link_and_runtime_notices',
            'test_rust_build.RustBuildTests.test_retained_target_libraries_still_reject_native_distro_links',
            'test_rust_build.RustBuildTests.test_native_distro_bad_dangling_escaping_chained_and_special_link_targets',
            'test_rust_build.RustBuildTests.test_native_distro_directory_links_and_other_library_names_are_not_allowed',
            'test_rust_build.RustBuildTests.test_native_distro_package_ambiguity_unowned_wrong_owner_and_versions_fail',
            'test_rust_build.RustBuildTests.test_native_distro_changed_target_and_retargeted_link_block_all_operations',
            'test_rust_build.RustBuildTests.test_native_distro_ownership_changes_and_missing_harness_family_invalidate_inputs',
            'test_rust_build.RustBuildTests.test_native_distro_target_replacement_during_ownership_queries_is_rejected',
            'test_rust_build.RustBuildTests.test_native_distro_link_text_cannot_hide_intermediate_symlink_traversal'}:
        return 'Native Debian Rust symlink and package-ownership fixtures belong to Linux runners; retained SDK and Windows ownership checks remain required.'
    if system != 'Linux' and name == 'test_release_check.ReleaseCheckTests.test_apt_timeout_stops_descendant_before_cleanup':
        return 'Native Linux APT descendant fixture belongs to Linux runners.'
    if system != 'Linux' and name.startswith('test_process_tree.LinuxSubreaper.'):
        return 'Native Linux descendant supervision belongs to the Linux runner.'
    if system != 'Windows' and name == 'test_process_tree.NativeProcessTree.test_windows_child_cannot_break_out_of_its_job':
        return 'Native Windows Job Object check belongs to the Windows runner.'
    if system == 'Windows':
        if name in {
                'test_import_wasm.ImportWasmTests.test_pinned_same_source_staging_and_relocated_exact_document_launch',
                'test_import_wasm.ImportWasmTests.test_windows_gui_entry_preserves_arguments_and_console_target_kind'}:
            return 'Unix opener/compiler fixtures; portable import identity checks and native Windows GUI linking remain required.'
        if name == 'test_coverage.CoverageTests.test_parent_success_with_inherited_log_child_is_rejected':
            return 'POSIX process-group fixture; Windows Job Object cases remain required.'
        if name.startswith('test_portability.Portability.') or name.startswith('test_portability.PortabilityTests.'):
            return 'ELF runtime qualification belongs to Linux runners; PE checks remain required.'
        if name == 'test_source_identity.SourceIdentityTests.test_executable_mode_changes_identity':
            return 'POSIX executable metadata belongs to POSIX runners.'
        if name == 'test_source_identity.SourceIdentityTests.test_source_links_rejected_in_plain_and_restored_trees':
            return 'POSIX source symlink fixture; portable source inventory checks remain required.'
    return None


class Recorded(unittest.TextTestResult):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.outcomes = {}

    def addSuccess(self, test):
        super().addSuccess(test)
        self.outcomes[test.id()] = {'status': 'passed'}

    def addError(self, test, error):
        super().addError(test, error)
        self.outcomes[test.id()] = {'status': 'failed', 'reason': 'error'}

    def addFailure(self, test, error):
        super().addFailure(test, error)
        self.outcomes[test.id()] = {'status': 'failed', 'reason': 'assertion'}

    def addSkip(self, test, reason):
        super().addSkip(test, reason)
        self.outcomes[test.id()] = {'status': 'incomplete', 'reason': reason}

    def addExpectedFailure(self, test, error):
        super().addExpectedFailure(test, error)
        self.outcomes[test.id()] = {'status': 'incomplete', 'reason': 'expected failure'}

    def addUnexpectedSuccess(self, test):
        super().addUnexpectedSuccess(test)
        self.outcomes[test.id()] = {'status': 'failed', 'reason': 'unexpected success'}

    def addSubTest(self, test, subtest, error):
        super().addSubTest(test, subtest, error)
        if error is not None:
            self.outcomes[test.id()] = {'status': 'failed', 'reason': 'subtest'}


def execute(suite, system=None, stream=None):
    tests = list(flatten(suite))
    names = [test.id() for test in tests]
    if not names or len(set(names)) != len(names):
        raise ValueError('empty or duplicate test inventory')
    system = system or platform.system()
    excluded, selected = {}, []
    for test in tests:
        reason = inapplicable(test, system)
        if reason:
            excluded[test.id()] = reason
        else:
            selected.append(test)
    if not selected:
        raise ValueError('no applicable checks; do not schedule this suite on this host')
    result = unittest.TextTestRunner(stream=stream or sys.stderr, verbosity=2, resultclass=Recorded).run(unittest.TestSuite(selected))
    required = {test.id() for test in selected}
    complete = (result.wasSuccessful() and set(result.outcomes) == required and
                all(item['status'] == 'passed' for item in result.outcomes.values()))
    return {'schema_version': 1, 'system': system, 'status': 'passed' if complete else 'failed',
            'inventory': names, 'excluded': excluded, 'results': result.outcomes}


def publish(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=path.name + '-', dir=path.parent)
    try:
        with os.fdopen(descriptor, 'w') as stream:
            json.dump(value, stream, sort_keys=True, indent=2)
            stream.write('\n')
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


# Opt-in host diagnostics are deliberately outside normal test_*.py discovery.
DIAGNOSTICS = {'windows_hosts': ('tests/diagnostics/windows_hosts.py', 'Windows')}


def suite_source(suite, system=None):
    if not re.fullmatch(r'[a-z][a-z0-9_]*', suite):
        raise ValueError('invalid registered suite')
    if suite in DIAGNOSTICS:
        relative, required = DIAGNOSTICS[suite]
        if (system or platform.system()) != required:
            raise ValueError(suite + ' requires its native Windows host')
        name, path = 'diagnostic_' + suite, ROOT / relative
    else:
        name = 'test_' + suite
        path = ROOT / 'tests' / (name + '.py')
    if not path.is_file():
        raise ValueError('missing registered suite')
    return name, path


def load_suite(suite, system=None):
    name, path = suite_source(suite, system)
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    previous = sys.modules.get(name)
    # unittest resolves module fixtures through sys.modules. Register before
    # import, as a normal import does, so setUpModule/tearDownModule actually run.
    sys.modules[name] = module
    try:
        spec.loader.exec_module(module)
    except BaseException:
        if previous is None:
            sys.modules.pop(name, None)
        else:
            sys.modules[name] = previous
        raise
    return unittest.defaultTestLoader.loadTestsFromModule(module)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--suite', required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    suite_source(args.suite)
    args.output.unlink(missing_ok=True)
    # Test modules can import local fixtures and maintained tools explicitly.
    sys.path.insert(0, str(ROOT / 'tests'))
    result = execute(load_suite(args.suite))
    publish(args.output, result)
    return 0 if result['status'] == 'passed' else 1


if __name__ == '__main__':
    try:
        sys.exit(main())
    except (OSError, ValueError, ImportError) as error:
        print('unit runner: ' + str(error), file=sys.stderr)
        sys.exit(1)
