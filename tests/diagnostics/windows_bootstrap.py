"""Opt-in native Windows extraction diagnostics; fixture tools are never executed.

Run: python -B tests/diagnostics/windows_bootstrap.py -v
Actual Python/CMake/Ninja execution remains a separate retained-input host check.
"""
import hashlib
import json
import os
from pathlib import Path
import stat
import subprocess
import tempfile
import unittest
import zipfile

ROOT = Path(__file__).resolve().parents[2]


class WindowsBootstrap(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if os.name != 'nt':
            raise RuntimeError('This diagnostic requires native Windows; it is not Linux qualification.')
        cls.shell = Path(os.environ['SystemRoot']) / 'System32/WindowsPowerShell/v1.0/powershell.exe'
        if not cls.shell.is_file():
            raise RuntimeError('Windows PowerShell 5.1 is a required bootstrap prerequisite.')

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='offline bootstrap ')
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.output = self.root / 'installed tools'
        self.python = [('python.exe', b'not executable'), ('python314.dll', b'fixture DLL'),
                       ('python314.zip', b'fixture stdlib'), ('python314._pth', b'python314.zip\r\n.\r\n\r\n#import site\r\n')]
        self.write_zip('Python', self.python)
        self.write_zip('Cmake', [('cmake-4.4.0-windows-x86_64/bin/' + name + '.exe', b'fixture')
                                 for name in ('cmake', 'ctest', 'cpack')])
        self.write_zip('Ninja', [('ninja.exe', b'fixture')])

    def write_zip(self, kind, entries):
        path = self.root / (kind + ' input.zip')
        with zipfile.ZipFile(path, 'w') as archive:
            for name, data in entries:
                archive.writestr(name, data)
        return path

    def invoke(self, overrides=None):
        arguments = {}
        for kind in ('Python', 'Cmake', 'Ninja'):
            path = self.root / (kind + ' input.zip')
            arguments[kind + 'Archive'] = str(path)
            arguments[kind + 'Sha256'] = hashlib.sha256(path.read_bytes()).hexdigest()
        arguments['Output'] = str(self.output)
        arguments.update(overrides or {})
        command = [str(self.shell), '-NoLogo', '-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass',
                   '-File', str(ROOT / 'tools/restore-windows-host-tools.ps1')]
        for key, value in arguments.items():
            command.extend(['-' + key, value])
        return subprocess.run(command, cwd=self.root, capture_output=True, text=True, timeout=30)

    def assert_rejected(self, overrides=None):
        result = self.invoke(overrides)
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertFalse(self.output.exists())
        self.assertEqual(list(self.root.glob('.windows-tools-*')), [])
        return result

    def test_preserves_tools_and_original_policy_without_executing_them(self):
        result = self.invoke()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        receipt = json.loads((self.output / 'bootstrap.json').read_text(encoding='utf-8'))
        self.assertEqual(receipt['qualification'], 'not-executed')
        self.assertEqual(receipt['python'], 'python/python.exe')
        self.assertEqual((self.output / 'python/python.exe').read_bytes(), b'not executable')
        self.assertEqual((self.output / 'python/python314.zip').read_bytes(), b'fixture stdlib')
        self.assertEqual((self.output / 'python/python314._pth.retained-disabled').read_bytes(), self.python[-1][1])
        self.assertFalse((self.output / 'python/python314._pth').exists())
        self.assertTrue((self.output / receipt['cmake_bin'] / 'ctest.exe').is_file())
        self.assertTrue((self.output / receipt['ninja_bin'] / 'ninja.exe').is_file())
        self.assertIn('Git for checkout and Git-dependent tests', receipt['separate_prerequisites'])
        self.assertEqual(list(self.root.glob('.windows-tools-*')), [])

    def test_every_archive_requires_matching_well_formed_hash(self):
        for kind in ('Python', 'Cmake', 'Ninja'):
            for digest in ('0' * 64, 'not-a-hash'):
                with self.subTest(kind=kind, digest=digest):
                    self.assert_rejected({kind + 'Sha256': digest})

    def test_relative_and_drive_relative_paths_are_rejected(self):
        for key in ('PythonArchive', 'CmakeArchive', 'NinjaArchive', 'Output'):
            for value in ('relative', r'C:relative', r'\relative'):
                with self.subTest(key=key, value=value):
                    result = self.assert_rejected({key: value})
                    self.assertIn('absolute local Windows paths', result.stderr)

    def test_existing_output_is_preserved(self):
        self.output.mkdir()
        sentinel = self.output / 'keep.txt'
        sentinel.write_text('foreign output')
        result = self.invoke()
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(sentinel.read_text(), 'foreign output')
        self.assertEqual(list(self.root.glob('.windows-tools-*')), [])

    def test_unsafe_windows_paths_and_links_are_rejected(self):
        names = ('../escape.txt', '/absolute.txt', 'C:/drive.txt', 'back\\slash', 'x/../parent',
                 'file:stream', 'NUL', 'COM1.txt', 'trailing.', 'space ', 'double//slash',
                 'line\nfeed', 'root//')
        for name in names:
            with self.subTest(name=name):
                self.write_zip('Ninja', [('ninja.exe', b'fixture'), (name, b'bad')])
                self.assert_rejected()
        symlink = zipfile.ZipInfo('linked')
        symlink.create_system = 3
        symlink.external_attr = (stat.S_IFLNK | 0o777) << 16
        self.write_zip('Ninja', [('ninja.exe', b'fixture'), (symlink, b'../outside')])
        self.assert_rejected()
        self.assertFalse((self.root / 'escape.txt').exists())

    def test_duplicate_case_collisions_and_file_ancestors_are_rejected(self):
        for extra in ([('NINJA.exe', b'other')], [('ancestor', b'file'), ('ancestor/child', b'child')],
                      [('folder/child', b'child'), ('FOLDER', b'file')],
                      [('folder/first', b'first'), ('FOLDER/second', b'second')]):
            with self.subTest(extra=extra):
                self.write_zip('Ninja', [('ninja.exe', b'fixture'), *extra])
                self.assert_rejected()

    def test_unexpected_python_policy_and_tool_layout_are_rejected(self):
        for policy in (b'python314.zip\n.\nimport site\n', b'python314.zip\n../outside\n', b'other.zip\n.\n'):
            with self.subTest(policy=policy):
                self.write_zip('Python', self.python[:-1] + [('python314._pth', policy)])
                self.assert_rejected()
        self.write_zip('Python', self.python)
        self.write_zip('Cmake', [('unexpected/bin/cmake.exe', b'fixture')])
        self.assert_rejected()

    def test_invalid_zip_or_missing_tool_never_publishes_partial_output(self):
        (self.root / 'Cmake input.zip').write_bytes(b'not a zip')
        self.assert_rejected()
        self.write_zip('Cmake', [('cmake-4.4.0-windows-x86_64/bin/cmake.exe', b'fixture')])
        self.assert_rejected()


if __name__ == '__main__':
    unittest.main()
