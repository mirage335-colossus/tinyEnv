"""Local shell compatibility checks with inert programs; no build or GUI.

FOUNDATION_TEST_SHELL selects one interpreter executable, defaulting to /bin/sh.
"""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
SHELL = os.environ.get('FOUNDATION_TEST_SHELL', '/bin/sh')


class ShellLauncherTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='foundation-launchers-')
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name)
        self.checkout = self.directory / "-checkout 'quoted' [literal]"
        self.checkout.mkdir()
        self.receipt = self.directory / 'receipt.jsonl'
        self.environment = dict(os.environ, LAUNCHER_RECEIPT=str(self.receipt),
                                LAUNCHER_EXIT='0', LAUNCHER_CREATE_EDITOR='',
                                CDPATH=str(self.directory / 'wrong'))
        for name in ('build.sh', 'editor.sh'):
            shutil.copy2(ROOT / name, self.checkout / name)
        self.probe = self.directory / 'python probe'
        self.probe.write_text(f'#!{sys.executable}\n' + '''import json, os, shutil, sys
from pathlib import Path
with Path(os.environ['LAUNCHER_RECEIPT']).open('a') as stream:
    stream.write(json.dumps({'arguments': sys.argv[1:], 'cwd': os.getcwd()}) + '\\n')
if os.environ['LAUNCHER_CREATE_EDITOR'] and '--build-dir' in sys.argv:
    target = Path(sys.argv[sys.argv.index('--build-dir') + 1]) / 'foundation-editor-fltk'
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(sys.argv[0], target)
sys.exit(int(os.environ['LAUNCHER_EXIT']))
''')
        self.probe.chmod(0o755)
        self.environment['PYTHON'] = str(self.probe)

    def invoke(self, script, arguments=(), relative=False):
        path = self.checkout / script
        if relative:
            path = Path('.') / self.checkout.name / script
            # Prefix the operand: the directory itself starts with a dash.
            path = './' + str(path)
        return subprocess.run([SHELL, str(path), *arguments], cwd=self.directory,
                              env=self.environment, text=True, capture_output=True, timeout=10)

    def records(self):
        return [json.loads(line) for line in self.receipt.read_text().splitlines()]

    def editor(self, sdk=False):
        if sdk:
            manifest = self.checkout / 'build/agents/rust-package-qualification/sdk/sdk.json'
            manifest.parent.mkdir(parents=True)
            manifest.write_text('{}\n')
        path = self.checkout / ('build/editor-fltk-sdk' if sdk else 'build/editor-fltk-dev')
        path.mkdir(parents=True)
        shutil.copy2(self.probe, path / 'foundation-editor-fltk')

    def test_build_preserves_no_arguments_and_literal_arguments(self):
        for arguments in ([], ['', 'two words', "quote'", '$literal', '*', '\\path']):
            with self.subTest(arguments=arguments):
                self.receipt.unlink(missing_ok=True)
                result = self.invoke('build.sh', arguments, relative=True)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(self.records(), [{
                    'arguments': [str(self.checkout / 'tools/build.py'), *arguments],
                    'cwd': str(self.directory)}])

    def test_build_preserves_child_failure(self):
        self.environment['LAUNCHER_EXIT'] = '19'
        self.assertEqual(self.invoke('build.sh').returncode, 19)

    def test_existing_editor_preserves_arguments_cwd_and_exit_status(self):
        self.editor()
        for arguments, status in (([], 0), (['', 'two words', '*', '$literal'], 23)):
            with self.subTest(arguments=arguments):
                self.receipt.unlink(missing_ok=True)
                self.environment['LAUNCHER_EXIT'] = str(status)
                result = self.invoke('editor.sh', arguments, relative=True)
                self.assertEqual(result.returncode, status, result.stderr)
                self.assertEqual(self.records(), [{'arguments': arguments,
                                                   'cwd': str(self.checkout)}])

    def test_existing_sdk_editor_is_selected_without_build(self):
        self.editor(sdk=True)
        result = self.invoke('editor.sh', ['--project', 'a project.json'])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.records(), [{'arguments': ['--project', 'a project.json'],
                                           'cwd': str(self.checkout)}])

    def test_missing_editor_build_failure_stops_launch(self):
        self.environment['LAUNCHER_EXIT'] = '17'
        result = self.invoke('editor.sh', ['--project', 'literal'])
        self.assertEqual(result.returncode, 17, result.stderr)
        self.assertEqual(self.records(), [{'arguments': [str(self.checkout / 'tools/build.py'),
            'editor', 'build', 'dev', '--backend', 'fltk', '--build-dir',
            str(self.checkout / 'build/editor-fltk-dev')], 'cwd': str(self.checkout)}])

    def test_missing_editor_builds_selected_variant_then_launches(self):
        self.environment['LAUNCHER_CREATE_EDITOR'] = '1'
        for sdk in (False, True):
            with self.subTest(sdk=sdk):
                self.receipt.unlink(missing_ok=True)
                arguments = ['--project', 'a project.json', '']
                expected = [str(self.checkout / 'tools/build.py'),
                            'editor', 'build', 'dev', '--backend', 'fltk']
                if sdk:
                    sdk_dir = self.checkout / 'build/agents/rust-package-qualification/sdk'
                    sdk_dir.mkdir(parents=True)
                    (sdk_dir / 'sdk.json').write_text('{}\n')
                    expected += ['--sdk', str(sdk_dir)]
                build_dir = self.checkout / ('build/editor-fltk-sdk' if sdk else 'build/editor-fltk-dev')
                expected += ['--build-dir', str(build_dir)]
                result = self.invoke('editor.sh', arguments)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(self.records(), [
                    {'arguments': expected, 'cwd': str(self.checkout)},
                    {'arguments': arguments, 'cwd': str(self.checkout)}])

if __name__ == '__main__':
    unittest.main()
