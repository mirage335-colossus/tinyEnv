from pathlib import Path
import os
import shutil
import subprocess
import sys
import tempfile
import tarfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from dependency_archive import extract
from source_identity import archive_source, source_tree, verify_source_archive
import source_identity as source_module
import json
from unittest.mock import patch


class SourceIdentityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.source = self.root / 'source'
        self.source.mkdir()
        (self.source / 'main.cpp').write_text('int main(){return 0;}\n')
        (self.source / 'build.sh').write_text('#!/bin/sh\nexit 0\n')
        (self.source / 'build.sh').chmod(0o755)

    def tearDown(self): self.temp.cleanup()

    def test_archive_matches_tree_and_restored_tree(self):
        data = archive_source(self.source, self.root / 'source.tar.gz')
        self.assertEqual(data, source_tree(self.source))
        self.assertEqual(data, verify_source_archive(self.root / 'source.tar.gz'))
        extract(self.root / 'source.tar.gz', self.root / 'restored')
        self.assertEqual(data, source_tree(self.root / 'restored'))

    def test_source_bytes_change_identity(self):
        before = source_tree(self.source)
        (self.source / 'main.cpp').write_text('int main(){return 1;}\n')
        self.assertNotEqual(before['tree_sha256'], source_tree(self.source)['tree_sha256'])

    @unittest.skipIf(os.name == 'nt', 'POSIX executable bit')
    def test_executable_mode_changes_identity(self):
        before = source_tree(self.source)
        (self.source / 'build.sh').chmod(0o644)
        self.assertNotEqual(before['tree_sha256'], source_tree(self.source)['tree_sha256'])

    def test_generated_outputs_excluded(self):
        before = source_tree(self.source)
        (self.source / 'build').mkdir()
        (self.source / 'build/output').write_text('generated')
        self.assertEqual(before, source_tree(self.source))

    def test_local_environment_secrets_are_excluded_from_plain_and_restored_archives(self):
        templates = ['.env.example', '.env.openrouter.example', 'module/.env.service.example']
        retained = [*templates, '..env.openrouter.source', '..env.openrouter.szz', '#ordinary#']
        for name in retained:
            path = self.source / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text('API_KEY=\n')
        before = source_tree(self.source)
        self.assertTrue(set(retained) <= set(before['files']))
        secrets = ['.env', '.env.openrouter', '.env.openrouter.bak', '.env.openrouter~',
                   'module/.env.service', 'module/.env.service.example~', '.env~', '.#.env',
                   '.#.env.openrouter', '#.env#', '#.env.openrouter#', '..env.swp',
                   'module/..env.openrouter.swp', 'module/..env.openrouter.swo',
                   '#.env.openrouter.example#', '.#.env.openrouter.example']
        for name in secrets:
            path = self.source / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text('inert local credential fixture')
        private_directory = self.source / 'module/.env.private-directory'
        private_directory.mkdir()
        (private_directory / 'credential').write_text('inert local credential fixture')
        scan = os.scandir
        def checked_scan(path):
            self.assertNotEqual(Path(path), private_directory, 'private subtree was traversed')
            return scan(path)
        for manifest in (False, True):
            with self.subTest(restored=manifest):
                if manifest:
                    (self.source / 'source.json').write_text(json.dumps(before))
                with patch.object(source_module.os, 'scandir', side_effect=checked_scan):
                    self.assertEqual(before, source_tree(self.source))
                archive = self.root / ('restored.tar.gz' if manifest else 'plain.tar.gz')
                self.assertEqual(before, archive_source(self.source, archive))
                with tarfile.open(archive) as contents:
                    self.assertEqual(set(contents.getnames()), {*before['files'], 'source.json'})
                    self.assertTrue(set(retained) <= set(contents.getnames()))
                    self.assertTrue(set(secrets).isdisjoint(contents.getnames()))
        (self.source / '.env.openrouter').write_text('changed inert local credential fixture')
        self.assertEqual(before, source_tree(self.source))

    @unittest.skipUnless(shutil.which('git'), 'Git required for force-index fixture')
    def test_local_environment_secrets_are_excluded_even_when_git_tracks_them(self):
        secrets = ['.env.openrouter', '.env~', '.#.env.openrouter', '#.env.openrouter#',
                   '..env.openrouter.swp']
        for name in secrets:
            (self.source / name).write_text('inert forced-index credential fixture')
        (self.source / '.env.openrouter.example').write_text('OPENROUTER_API_KEY=\n')
        shutil.copyfile(Path(__file__).resolve().parents[1] / '.gitignore', self.source / '.gitignore')
        before = source_tree(self.source)
        environment = {name: value for name, value in os.environ.items() if not name.startswith('GIT_')}
        environment.update(GIT_CONFIG_NOSYSTEM='1', GIT_CONFIG_GLOBAL=os.devnull,
                           GIT_CONFIG_SYSTEM=os.devnull)
        command = ['git', '-C', str(self.source), '-c', 'core.hooksPath=' + os.devnull,
                   '-c', 'user.name=Source fixture', '-c', 'user.email=source@example.invalid']
        for arguments in (['init', '--quiet', '--template='], ['add', '--all', '--force'],
                          ['commit', '--quiet', '-m', 'Source fixture']):
            subprocess.run([*command, *arguments], env=environment, check=True,
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        ignored = subprocess.run([*command, 'check-ignore', '--no-index', '--stdin'],
                                 input='\n'.join([*secrets, '.env.openrouter.example']) + '\n',
                                 env=environment, text=True, check=True, stdout=subprocess.PIPE,
                                 stderr=subprocess.PIPE).stdout.splitlines()
        self.assertEqual(set(secrets), set(ignored))
        self.assertEqual(before, source_tree(self.source))
        archive = self.root / 'git.tar.gz'
        self.assertEqual(before, archive_source(self.source, archive))
        with tarfile.open(archive) as contents:
            self.assertTrue(set(secrets).isdisjoint(contents.getnames()))
            self.assertIn('.env.openrouter.example', contents.getnames())

    def test_generated_subtrees_are_not_traversed_with_or_without_manifest(self):
        (self.source / 'module/build').mkdir(parents=True)
        (self.source / 'module/build/retained.cpp').write_text('nested build is source')
        (self.source / 'cache.pyc').mkdir()
        (self.source / 'cache.pyc/retained.cpp').write_text('only pyc files are excluded')
        before = source_tree(self.source)
        excluded = [self.source / 'build', self.source / '.agent-work',
                    self.source / 'module/__pycache__']
        for directory in excluded:
            directory.mkdir()
            (directory / 'large-output').write_text('generated')
        (self.source / 'module/generated.pyc').write_text('generated')
        scan = os.scandir
        def checked_scan(path):
            self.assertNotIn(Path(path), excluded, 'excluded subtree was traversed')
            return scan(path)
        for manifest in (False, True):
            with self.subTest(restored=manifest):
                if manifest:
                    (self.source / 'source.json').write_text(json.dumps(before))
                with patch.object(source_module.os, 'scandir', side_effect=checked_scan):
                    self.assertEqual(before, source_tree(self.source))

    @unittest.skipIf(os.name == 'nt', 'source symlink fixture needs POSIX')
    def test_source_links_rejected_in_plain_and_restored_trees(self):
        before = source_tree(self.source)
        for manifest in (False, True):
            with self.subTest(restored=manifest):
                if manifest:
                    (self.source / 'source.json').write_text(json.dumps(before))
                for name, target in [('extra.cpp', self.source / 'main.cpp'),
                                     ('linked-directory', self.root),
                                     ('broken.cpp', self.root / 'absent')]:
                    link = self.source / name
                    link.symlink_to(target, target_is_directory=target.is_dir())
                    try:
                        with self.assertRaises(ValueError):
                            source_tree(self.source)
                    finally:
                        link.unlink()

    def test_source_scan_errors_do_not_hide_inputs(self):
        (self.source / 'include').mkdir()
        (self.source / 'include/api.hpp').write_text('retained')
        scan = os.scandir
        def failed_scan(path):
            if Path(path).name == 'include':
                raise PermissionError('injected inaccessible source')
            return scan(path)
        with patch.object(source_module.os, 'scandir', side_effect=failed_scan):
            with self.assertRaisesRegex(PermissionError, 'inaccessible source'):
                source_tree(self.source)

    def test_supplement_retained_and_not_double_counted(self):
        extra = self.root / 'gui'
        extra.mkdir()
        (extra / 'generic.hpp').write_text('// supplier source\n')
        (extra / 'setup.sh').write_text('#!/bin/sh\nexit 0\n')
        (extra / 'setup.sh').chmod(0o755)
        data = archive_source(self.source, self.root / 'source.tar.gz', extra)
        extract(self.root / 'source.tar.gz', self.root / 'restored')
        self.assertEqual(data, source_tree(self.root / 'restored'))
        self.assertEqual(data, source_tree(self.root / 'restored', self.root / 'restored/third_party/retained/gui'))
        self.assertIn('third_party/retained/gui/generic.hpp', data['files'])
        with patch.object(source_module, 'WINDOWS', True):
            self.assertEqual(data, source_tree(self.root / 'restored', self.root / 'restored/third_party/retained/gui'))

    def test_archive_cannot_become_its_own_source_input(self):
        with self.assertRaisesRegex(ValueError, 'outside source inputs'):
            archive_source(self.source, self.source / 'source.tar.gz')

    def test_failed_archive_staging_does_not_publish_partial_output(self):
        destination = self.root / 'source.tar.gz'
        with patch.object(source_module.tarfile.TarFile, 'addfile', side_effect=OSError('injected archive failure')):
            with self.assertRaises(OSError): archive_source(self.source, destination)
        self.assertFalse(destination.exists())

    def test_windows_retained_modes_survive_non_executable_storage(self):
        data = source_tree(self.source)
        data['executables'] = ['build.sh']
        # Produce authoritative metadata with the same logical modes on every host.
        paths = source_module.snapshot_paths(self.source)
        data = source_module.describe_paths(paths, {'build.sh'})
        (self.source / 'source.json').write_text(json.dumps(data), encoding='utf-8')
        (self.source / 'build.sh').chmod(0o644)
        with patch.object(source_module, 'WINDOWS', True):
            self.assertEqual(data, source_tree(self.source))
            archive_source(self.source, self.root / 'portable.tar.gz')
            self.assertEqual(data, verify_source_archive(self.root / 'portable.tar.gz'))
            (self.source / 'main.cpp').write_text('changed')
            self.assertNotEqual(data, source_tree(self.source))

    def test_windows_index_modes_are_preserved_and_conflicts_rejected(self):
        (self.source / '.git').mkdir()
        paths = {'build.sh': self.source / 'build.sh'}
        with patch.object(source_module, 'WINDOWS', True), patch.object(source_module.subprocess, 'check_output', return_value=b'100755 abc 0\tbuild.sh\0'):
            self.assertEqual({'build.sh'}, source_module.portable_executables(self.source, paths))
        with patch.object(source_module, 'WINDOWS', True), patch.object(source_module.subprocess, 'check_output', return_value=b'100755 abc 2\tbuild.sh\0'):
            with self.assertRaisesRegex(ValueError, 'unmerged'):
                source_module.portable_executables(self.source, paths)

    def test_nested_git_checkout_uses_own_index_before_parent_archive(self):
        (self.source / '.git').mkdir()
        (self.root / 'source.json').write_text(json.dumps({'files': {}, 'executables': []}))
        paths = {'build.sh': self.source / 'build.sh'}
        with patch.object(source_module, 'WINDOWS', True), patch.object(source_module.subprocess, 'check_output', return_value=b'100755 abc 0\tbuild.sh\0'):
            self.assertEqual({'build.sh'}, source_module.portable_executables(self.source, paths))
        for row in (b'120000 abc 0\tbuild.sh\0', b'100755 abc 0\tbuild.sh\0' * 2):
            with patch.object(source_module, 'WINDOWS', True), patch.object(source_module.subprocess, 'check_output', return_value=row):
                with self.assertRaisesRegex(ValueError, 'unsupported or duplicate'):
                    source_module.portable_executables(self.source, paths)

    def test_unlisted_restored_source_rejected(self):
        archive_source(self.source, self.root / 'source.tar.gz')
        extract(self.root / 'source.tar.gz', self.root / 'restored')
        (self.root / 'restored/unlisted.cpp').write_text('unlisted')
        with self.assertRaisesRegex(ValueError, 'inventory changed'):
            source_tree(self.root / 'restored')


if __name__ == '__main__': unittest.main()
