"""Small Rev diagnostic preserves exact input, complete assertions and process ownership."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
spec = importlib.util.spec_from_file_location('rev_probe', ROOT / 'tools/rev_probe.py')
PROBE = importlib.util.module_from_spec(spec)
spec.loader.exec_module(PROBE)


class RevProbeTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='rev-probe-fixture-')
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.output = self.root / 'attempt'
        self.compiler = Path(sys.executable).resolve()
        self.verifier = mock.Mock()
        self.verifier.ordinary.side_effect = lambda path: path
        self.verifier.restore.return_value = {'source': str(self.root / 'retained/upstream'),
            'revision': 'a' * 40, 'group_sha256': 'b' * 64, 'redistributable': True, 'schema_version': 1}
        self.phases = []

    def compiler_info(self, build, **changes):
        info = {'CMAKE_CXX_COMPILER': str(self.compiler), 'CMAKE_CXX_COMPILER_ID': 'Clang',
                'CMAKE_CXX_COMPILER_VERSION': '19.1.7', 'CMAKE_CXX_COMPILER_CLANG_SCAN_DEPS': '',
                'CMAKE_LINKER': '', 'CMAKE_AR': '', 'CMAKE_MAKE_PROGRAM': str(self.compiler)}
        info.update(changes)
        build.mkdir(exist_ok=True)
        (build / 'compiler.json').write_text(json.dumps(info))

    def junit(self, *, skipped=False, names=PROBE.CASES):
        cases = ''.join('<testcase name="' + name + '">' + ('<skipped/>' if skipped else '') + '</testcase>'
                        for name in names)
        (self.output / 'tests.xml').write_text('<testsuite>' + cases + '</testsuite>')

    def command(self, command, cwd, log, environment, *, compiler):
        name = log.stem
        self.phases.append(name)
        log.write_text('completed ' + name)
        self.assertEqual(str(self.output / 'scratch'), environment['TMPDIR'])
        if name == 'configure':
            self.compiler_info(self.output / 'build')
            self.assertIn('-DFOUNDATION_REV_SOURCE=' + str(self.root / 'retained/upstream/third_party/rev'), command)
        if name == 'test':
            self.junit()
            self.assertFalse(compiler)
        else:
            self.assertTrue(compiler)
        return {'command': command, 'returncode': 0, 'status': 'passed', 'writers_stopped': True}

    def execute(self, command=None):
        with mock.patch.object(PROBE, 'source_group', return_value=self.verifier), \
             mock.patch.object(PROBE, 'executable', return_value=self.compiler), \
             mock.patch.object(PROBE, 'run_command', side_effect=command or self.command), \
             mock.patch.dict(os.environ, {'CMAKE_TOOLCHAIN_FILE': ''}):
            return PROBE.execute(self.root / 'group', self.output, str(self.compiler), jobs='2')

    def test_complete_inventory_and_exact_tools_are_retained_once(self):
        value = self.execute()
        self.assertEqual('passed', value['status'])
        self.assertEqual(['configure', 'build', 'test'], self.phases)
        self.assertEqual(2, value['jobs'])
        self.assertFalse(value['release_qualification'])
        self.assertTrue(value['writers_stopped'])
        self.assertEqual(list(PROBE.CASES), value['cases'])
        self.assertEqual(PROBE.evidence.sha(self.compiler), value['compiler']['programs']['CMAKE_CXX_COMPILER']['sha256'])
        self.assertEqual({'configure.log', 'build.log', 'test.log', 'tests.xml'}, set(value['evidence']))
        self.assertEqual(value, json.loads((self.output / 'result.json').read_text()))
        with self.assertRaises(FileExistsError):
            self.execute()
        self.assertEqual(value, json.loads((self.output / 'result.json').read_text()))

    def test_invalid_retained_group_cannot_launch_configuration(self):
        self.verifier.restore.side_effect = ValueError('input differs from reviewed tree')
        run = mock.Mock()
        value = self.execute(run)
        run.assert_not_called()
        self.assertEqual('failed', value['status'])
        self.assertIn('reviewed tree', value['error'])
        self.assertEqual([], value['phases'])

    def test_malformed_archive_retains_failure_receipt_without_launch(self):
        self.verifier.restore.side_effect = PROBE.tarfile.ReadError('truncated archive')
        run = mock.Mock()
        value = self.execute(run)
        run.assert_not_called()
        self.assertEqual('failed', value['status'])
        self.assertTrue(value['writers_stopped'])
        self.assertIn('truncated archive', value['error'])

    def test_failed_phase_blocks_every_dependent_phase(self):
        for failed in ('configure', 'build', 'test'):
            with self.subTest(failed=failed):
                self.output = self.root / failed
                self.phases = []
                def command(*args, **kwargs):
                    row = self.command(*args, **kwargs)
                    if args[2].stem == failed:
                        row.update(status='failed', returncode=1, error='actual compiler or assertion failure')
                    return row
                value = self.execute(command)
                self.assertEqual('failed', value['status'])
                self.assertEqual(failed, self.phases[-1])
                self.assertTrue(value['writers_stopped'])

    def test_zero_exit_with_missing_or_skipped_assertions_fails(self):
        for mode in ('missing', 'skipped', 'duplicate', 'empty'):
            with self.subTest(mode=mode):
                self.output = self.root / mode
                def command(*args, **kwargs):
                    row = self.command(*args, **kwargs)
                    if args[2].stem == 'test':
                        if mode == 'missing':
                            (self.output / 'tests.xml').unlink()
                        else:
                            self.junit(skipped=mode == 'skipped',
                                names=PROBE.CASES + PROBE.CASES[:1] if mode == 'duplicate' else () if mode == 'empty' else PROBE.CASES)
                    return row
                value = self.execute(command)
                self.assertEqual('failed', value['status'])

    def test_different_selected_compiler_blocks_build(self):
        def command(*args, **kwargs):
            row = self.command(*args, **kwargs)
            if args[2].stem == 'configure':
                self.compiler_info(self.output / 'build', CMAKE_CXX_COMPILER=str(ROOT / 'tools/rev_probe.py'))
            return row
        value = self.execute(command)
        self.assertEqual('failed', value['status'])
        self.assertEqual(['configure'], self.phases)
        self.assertIn('different compiler', value['error'])

    def test_retained_inputs_changed_after_tests_invalidate_success(self):
        self.verifier.restore.side_effect = [self.verifier.restore.return_value, ValueError('restored input changed')]
        value = self.execute()
        self.assertEqual('failed', value['status'])
        self.assertIn('restored input changed', value['error'])
        self.assertEqual(['configure', 'build', 'test'], self.phases)

    def test_cleanup_uncertainty_stops_build_and_does_not_read_logs(self):
        def command(*args, **kwargs):
            row = self.command(*args, **kwargs)
            row.update(status='failed', error='writer completion unknown', writers_stopped=False)
            return row
        value = self.execute(command)
        self.assertEqual('failed', value['status'])
        self.assertFalse(value['writers_stopped'])
        self.assertEqual({}, value['evidence'])
        self.assertEqual(['configure'], self.phases)

    def test_compiler_symlink_invocation_name_is_not_canonicalized(self):
        # clang++ and clang can share a binary but select different link drivers.
        alias = self.root / 'clang++'
        with mock.patch.object(PROBE.shutil, 'which', return_value=str(alias)):
            self.assertEqual(alias, PROBE.executable('clang++'))

    def test_transport_selects_only_joined_bounded_evidence(self):
        value = self.execute()
        paths = PROBE.retained_paths(self.output).splitlines()
        self.assertEqual(5, len(paths))
        self.assertNotIn(str(self.output / 'inputs'), paths)
        value['writers_stopped'] = False
        (self.output / 'result.json').write_text(json.dumps(value))
        self.assertEqual((self.output / 'result.json').as_posix(), PROBE.retained_paths(self.output))
        value['writers_stopped'] = True
        (self.output / 'result.json').write_text(json.dumps(value))
        with mock.patch.object(PROBE, 'MAX_LOG', 1):
            self.assertEqual((self.output / 'result.json').as_posix(), PROBE.retained_paths(self.output))

    def test_manual_workflow_uses_existing_inputs_and_owned_diagnostic_only(self):
        text = (ROOT / '.github/workflows/rev-probe.yml').read_text()
        for expected in ('workflow_dispatch:', 'lifecycle.py gui-input', 'tools/ci_windows.ps1',
                         'tools/rev_probe.py', "rev_probe.retained_paths('build/rev-probe')",
                         'lifecycle.py', "'bundle-store'", 'persist-credentials: false'):
            self.assertIn(expected, text)
        for forbidden in ('fetch-sdk', 'sdk-produce', 'publish-candidate', 'actions/upload-artifact@',
                          'apt-get', 'pip install', 'git clone'):
            self.assertNotIn(forbidden, text)
        self.assertLess(text.index('lifecycle.py gui-input'), text.index('tools/rev_probe.py'))

    def test_native_toolchain_override_is_rejected_without_launch(self):
        with mock.patch.object(PROBE, 'run_command') as run, \
             mock.patch.dict(os.environ, {'CMAKE_TOOLCHAIN_FILE': 'unreviewed-cross-toolchain.cmake'}):
            value = PROBE.execute(self.root / 'group', self.output, str(self.compiler))
        run.assert_not_called()
        self.assertEqual('failed', value['status'])
        self.assertIn('CMAKE_TOOLCHAIN_FILE', value['error'])

    def test_windows_compiler_regions_use_private_session_before_output_closure(self):
        owner = mock.Mock(); owner.poll.return_value = 0; owner.wait.return_value = 0
        session = mock.Mock(); session.environment = {'private': 'session'}
        session.finish.return_value = {'outcome': 'joined'}
        with mock.patch.object(PROBE.os, 'name', 'nt'), \
             mock.patch.object(PROBE.windows_compiler, 'BuildSession', return_value=session) as factory, \
             mock.patch.object(PROBE.process_tree, 'launch', return_value=owner) as launch:
            value = PROBE.run_command(['compiler'], self.root, self.root / 'compile.log', {'source': 'env'}, compiler=True)
        self.assertEqual('passed', value['status'])
        factory.assert_called_once_with({'source': 'env'})
        self.assertEqual(session.environment, launch.call_args.kwargs['env'])
        session.finish.assert_called_once_with(owner)
        owner.close.assert_called_once()
        self.assertEqual({'outcome': 'joined'}, value['compiler_completion'])

    def test_windows_cleanup_failure_never_publishes_stopped_writer(self):
        owner = mock.Mock(); owner.poll.return_value = 0; owner.wait.return_value = 0
        owner.close.side_effect = PROBE.process_tree.ProcessTreeError('cleanup unconfirmed')
        with mock.patch.object(PROBE.process_tree, 'launch', return_value=owner):
            value = PROBE.run_command(['test'], self.root, self.root / 'test.log', {}, compiler=False)
        self.assertEqual('failed', value['status'])
        self.assertFalse(value['writers_stopped'])

    @unittest.skipUnless(sys.platform.startswith('linux') or os.name == 'nt', 'qualified native supervisor required')
    def test_real_zero_exit_and_failure_retain_joined_logs(self):
        for code in (0, 3):
            value = PROBE.run_command([sys.executable, '-c', 'print("actual child"); raise SystemExit(' + str(code) + ')'],
                self.root, self.root / ('exit-' + str(code) + '.log'), dict(os.environ))
            self.assertEqual('passed' if code == 0 else 'failed', value['status'])
            self.assertTrue(value['writers_stopped'])
            self.assertEqual(code, value['returncode'])

    @unittest.skipUnless(sys.platform.startswith('linux') or os.name == 'nt', 'qualified native supervisor required')
    def test_real_timeout_joins_child_before_return(self):
        value = PROBE.run_command([sys.executable, '-c', 'import time; time.sleep(30)'], self.root,
            self.root / 'timeout.log', dict(os.environ), timeout=.05)
        self.assertEqual('failed', value['status'])
        self.assertTrue(value['writers_stopped'])
        self.assertIn('limit', value['error'])


if __name__ == '__main__':
    unittest.main()
