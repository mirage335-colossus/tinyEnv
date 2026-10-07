"""Explicit build ownership never grants arbitrary surviving children success."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import windows_compiler as compiler


class BuildSessionTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        # Native temporary roots may use a Windows 8.3 alias; selection returns
        # canonical toolkit paths, so compare the same physical fixture paths.
        self.root = Path(self.temporary.name).resolve(strict=True)
        self.directory = self.root / 'toolkit/bin/Hostx64/x64'
        self.directory.mkdir(parents=True)
        self.paths = {}
        for name in ('cl.exe', 'link.exe', *compiler.HELPERS):
            path = self.directory / name; path.write_bytes(name.encode()); self.paths[name] = path
        self.environment = {'PATH': str(self.directory), 'VCToolsInstallDir': str(self.root / 'toolkit')}

    def session(self, environment=None):
        with patch.object(compiler, '_select_toolkit', return_value=self.paths):
            return compiler.BuildSession(self.environment if environment is None else environment)

    def test_every_nested_owner_gets_a_fresh_endpoint_and_preserves_parent_environment(self):
        environment = dict(self.environment, _mspdbsrv_endpoint_='foreign', _MSPDBSRV_ENDPOINT_='another')
        before = dict(environment)
        first = self.session(environment); nested = self.session(first.environment)
        self.assertNotEqual(first.endpoint, nested.endpoint)
        self.assertNotIn(first.endpoint, ('foreign', 'another'))
        self.assertEqual(environment, before)
        for value in (first, nested):
            self.assertEqual([key for key in value.environment if key.upper() == compiler.ENDPOINT], [compiler.ENDPOINT])
            self.assertEqual(value.environment[compiler.ENDPOINT], value.endpoint)

    def test_selection_binds_compiler_and_linker_to_exact_toolkit(self):
        with patch.object(compiler.windows_toolchain, 'pe_identity') as pe, \
             patch.object(compiler.shutil, 'which', side_effect=lambda name, **kw: str(self.paths[name])):
            self.assertEqual(compiler._select_toolkit(self.environment), self.paths)
            self.assertEqual(pe.call_count, 4)
        foreign = self.root / 'cl.exe'; foreign.write_bytes(b'cl.exe')
        for found in (None, str(foreign)):
            with self.subTest(found=found), patch.object(compiler.shutil, 'which', return_value=found):
                with self.assertRaisesRegex(ValueError, 'differs from its toolkit'):
                    compiler._select_toolkit(self.environment)
        for environment in ({}, dict(self.environment, Path='ambiguous')):
            with self.subTest(environment=environment), self.assertRaisesRegex(ValueError, 'one selected'):
                compiler._select_toolkit(environment)

    def test_missing_pdb_server_or_bad_pe_is_not_a_qualified_toolkit(self):
        with patch.object(compiler.shutil, 'which', side_effect=lambda name, **kw: str(self.paths[name])), \
             patch.object(compiler.windows_toolchain, 'pe_identity', side_effect=ValueError('not PE')):
            with self.assertRaisesRegex(ValueError, 'not PE'):
                compiler._select_toolkit(self.environment)
        self.paths['mspdbsrv.exe'].unlink()
        with patch.object(compiler.shutil, 'which', side_effect=lambda name, **kw: str(self.paths[name])), \
             patch.object(compiler.windows_toolchain, 'pe_identity'):
            with self.assertRaises(FileNotFoundError):
                compiler._select_toolkit(self.environment)

    def test_exact_mixed_helpers_are_all_validated_then_joined_and_reported(self):
        session = self.session(); owner = Mock()
        def terminate(**kwargs):
            for pid, name in ((42, 'mspdbsrv.exe'), (43, 'vctip.exe')):
                self.assertIs(kwargs['validate_live'](pid, str(self.paths[name])), True)
        owner.terminate.side_effect = terminate
        receipt = session.finish(owner)
        owner.finish.assert_called_once_with()
        self.assertEqual([row['pid'] for row in receipt['helpers']], [42, 43])
        self.assertEqual(receipt['outcome'], 'verified-helpers-terminated-and-joined')
        self.assertEqual(receipt['toolkit']['mspdbsrv.exe']['sha256'], hashlib.sha256(b'mspdbsrv.exe').hexdigest())
        with self.assertRaisesRegex(ValueError, 'already completed'):
            session.finish(owner)

    def test_no_survivor_is_distinct_from_terminated_helpers(self):
        receipt = self.session().finish(Mock())
        self.assertEqual(receipt['outcome'], 'no-surviving-helper')
        self.assertEqual(receipt['helpers'], [])

    def test_unknown_mixed_member_cannot_be_accepted_after_one_known_helper(self):
        session = self.session(); owner = Mock()
        unknown = self.root / 'mspdbsrv.exe'; unknown.write_bytes(b'mspdbsrv.exe')
        def terminate(**kwargs):
            kwargs['validate_live'](11, str(self.paths['vctip.exe']))
            kwargs['validate_live'](12, str(unknown))
        owner.terminate.side_effect = terminate
        with self.assertRaisesRegex(compiler.process_tree.ProcessTreeError, 'unknown live'):
            session.finish(owner)
        owner.finish.assert_not_called()
        with self.assertRaisesRegex(ValueError, 'unconfirmed'):
            session.receipt()

    def test_compiler_itself_is_not_an_optional_surviving_helper(self):
        session = self.session()
        with self.assertRaisesRegex(compiler.process_tree.ProcessTreeError, 'unknown live'):
            session.validate(11, str(self.paths['cl.exe']))

    def test_changed_toolkit_and_uncertain_join_never_produce_receipt(self):
        for name in self.paths:
            with self.subTest(name=name):
                session = self.session(); original = self.paths[name].read_bytes()
                self.paths[name].write_bytes(original + b'changed')
                owner = Mock()
                with self.assertRaisesRegex(ValueError, 'toolkit changed'):
                    session.finish(owner)
                owner.terminate.assert_not_called()
                self.paths[name].write_bytes(original)
        session = self.session(); owner = Mock()
        owner.terminate.side_effect = compiler.process_tree.ProcessTreeError('join uncertain')
        with self.assertRaisesRegex(compiler.process_tree.ProcessTreeError, 'join uncertain'):
            session.finish(owner)
        with self.assertRaisesRegex(ValueError, 'unconfirmed'):
            session.receipt()

    def test_file_alias_must_identify_exact_file_not_equal_content(self):
        session = self.session()
        # A path with redundant components exercises identity rather than basename.
        alias = str(self.directory / '.' / 'mspdbsrv.exe')
        self.assertIs(session.validate(8, alias), True)
        self.assertEqual(session.observed[0]['path'], str(self.paths['mspdbsrv.exe']))

    def native_run(self, owner, session):
        return (patch.object(compiler, 'os', SimpleNamespace(name='nt', environ=self.environment)),
                patch.object(compiler, 'BuildSession', return_value=session),
                patch.object(compiler.process_tree, 'launch', return_value=owner))

    def test_run_joins_before_publishing_and_launches_with_private_environment(self):
        owner = Mock(); owner.wait.return_value = 0
        session = Mock(environment={'private': 'endpoint'}); session.finish.return_value = {'joined': True}
        a, b, c = self.native_run(owner, session)
        events = []
        session.finish.side_effect = lambda target: events.append('join') or {'joined': True}
        owner.close.side_effect = lambda: events.append('close')
        with a, b, c as launch, patch('builtins.print', side_effect=lambda *a, **kw: events.append('receipt')):
            result = compiler.run(['cmake', '--build', 'tree'], cwd=self.root)
        self.assertEqual(events, ['join', 'close', 'receipt'])
        self.assertEqual(result.returncode, 0)
        self.assertEqual(launch.call_args.kwargs['env'], session.environment)
        session.finish.assert_called_once_with(owner)

    def test_failure_and_timeout_close_owner_without_success_policy(self):
        for error in (subprocess.TimeoutExpired('cmake', 1), None):
            owner = Mock(); owner.wait.return_value = 9; owner.wait.side_effect = error
            session = Mock(environment={})
            a, b, c = self.native_run(owner, session)
            with self.subTest(timeout=bool(error)), a, b, c, patch('builtins.print') as output:
                with self.assertRaises(subprocess.SubprocessError):
                    compiler.run(['cmake'], cwd=self.root)
            owner.close.assert_called_once_with(); session.finish.assert_not_called(); output.assert_not_called()
            if error is None:
                owner.terminate.assert_called_once_with()

    def test_uncertain_close_or_validation_never_prints_a_passing_receipt(self):
        for phase in ('finish', 'close'):
            owner = Mock(); owner.wait.return_value = 0
            session = Mock(environment={})
            getattr(session if phase == 'finish' else owner, phase).side_effect = compiler.process_tree.ProcessTreeError('uncertain')
            a, b, c = self.native_run(owner, session)
            with self.subTest(phase=phase), a, b, c, patch('builtins.print') as output:
                with self.assertRaisesRegex(compiler.process_tree.ProcessTreeError, 'uncertain'):
                    compiler.run(['cmake'], cwd=self.root)
            owner.close.assert_called_once_with(); output.assert_not_called()

    def test_consumer_workspace_removes_only_after_confirmed_completion(self):
        with compiler.workspace('msvc-consumer-fixture-') as directory:
            (directory / 'output').write_text('finished')
        self.assertFalse(directory.exists())
        with self.assertRaisesRegex(ValueError, 'ordinary failure'):
            with compiler.workspace('msvc-consumer-fixture-') as directory:
                raise ValueError('ordinary failure')
        self.assertFalse(directory.exists())
        with self.assertRaisesRegex(RuntimeError, 'wrapped'):
            with compiler.workspace('msvc-consumer-fixture-') as directory:
                self.addCleanup(compiler.shutil.rmtree, directory)
                try:
                    raise compiler.process_tree.ProcessTreeError('live writer uncertain')
                except compiler.process_tree.ProcessTreeError as error:
                    raise RuntimeError('wrapped') from error
        self.assertTrue(directory.is_dir())

    def test_other_platforms_keep_normal_checked_subprocess_without_toolkit_lookup(self):
        with patch.object(compiler, 'os', SimpleNamespace(name='posix')), \
             patch.object(compiler, 'BuildSession') as session, patch.object(compiler.subprocess, 'run') as run:
            compiler.run(['cmake'], cwd=self.root, env={'PATH': 'target'})
        session.assert_not_called(); run.assert_called_once_with(['cmake'], cwd=self.root, env={'PATH': 'target'}, check=True)


if __name__ == '__main__':
    unittest.main()
