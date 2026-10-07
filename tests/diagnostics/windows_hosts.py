"""Opt-in installed Windows host probes; never ordinary unit-test discovery."""
from contextlib import contextmanager, ExitStack
import ctypes
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import platform
import shutil
import sys
import tempfile
import time
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tools'))
import process_tree
import windows_graphics
import windows_toolchain
import windows_compiler


def digest(path):
    value = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            value.update(chunk)
    return value.hexdigest()


def executable_identity(path):
    path = Path(path).resolve(strict=True)
    if not path.is_file():
        raise ValueError('installed host executable is not a file')
    return {'path': str(path), 'sha256': digest(path)}


def probe_identity(path):
    windows_toolchain.pe_identity(path)
    return dict(executable_identity(path), format='PE32+', machine='x86_64')


def compiler_identity(compiler):
    compiler = Path(compiler).resolve(strict=True)
    linker = compiler.with_name('link.exe').resolve(strict=True)
    selected = shutil.which('link.exe')
    if selected is None or Path(selected).resolve(strict=True) != linker:
        raise ValueError('selected linker differs from the compiler directory; host input is ambiguous')
    return {'compiler': executable_identity(compiler), 'linker': executable_identity(linker)}


@contextmanager
def workspace(cleanup_error):
    # A cleanup error must not let TemporaryDirectory erase an uncertain writer.
    directory = Path(tempfile.mkdtemp(prefix='windows-host-probe-')).resolve()
    safe = True
    try:
        yield directory
    except cleanup_error:
        safe = False
        print(json.dumps({'retained_workspace': str(directory), 'writers_stopped': False}), flush=True)
        raise
    except BaseException:
        # Ordinary command/startup failures have already joined their owner. Keep
        # only bounded named excerpts in the outer, retained diagnostic console.
        for name in ('compile.log', 'firefox.log', 'first/compile.log', 'control/compile.log'):
            path = directory / name
            if not path.exists():
                continue
            try:
                with path.open('rb') as stream:
                    raw = stream.read(16385)
                print(json.dumps({'diagnostic_log': name, 'text': raw[:16384].decode('utf-8', errors='replace'),
                                  'truncated': len(raw) > 16384}), flush=True)
            except OSError as error:
                print(json.dumps({'diagnostic_log': name, 'read_error': error.errno}), flush=True)
        raise
    finally:
        if safe:
            shutil.rmtree(directory)


# Each child makes real synchronous PDB requests, then remains an owned client
# until released. The second compile proves another owner's cleanup did not kill
# or substitute the server used by this already-running isolated session.
PDB_CLIENT = r"""
import json,subprocess,sys,time
from pathlib import Path
root=Path(sys.argv[1]); compiler=sys.argv[2]
(root/'unit.cpp').write_text('int main() { return 0; }\n')
command=[compiler,'/nologo','/EHsc','/Zi','/FS',str(root/'unit.cpp'),
 '/Fo:'+str(root/'unit.obj'),'/Fd:'+str(root/'compiler.pdb'),'/Fe:'+str(root/'unit.exe'),
 '/link','/DEBUG','/PDB:'+str(root/'linked.pdb')]
subprocess.run(command,cwd=root,check=True)
(root/'ready').write_text('compiled')
deadline=time.monotonic()+90
again=False
while not (root/'stop').exists():
 if time.monotonic()>deadline: raise RuntimeError('private PDB probe control deadline')
 if not again and (root/'again').exists():
  subprocess.run(command,cwd=root,check=True)
  (root/'recompiled').write_text('compiled again');again=True
 time.sleep(0.01)
"""


def wait_marker(path, owner, deadline):
    while not path.is_file():
        if owner.poll() is not None:
            raise AssertionError('private compiler client exited before ' + path.name)
        if time.monotonic() >= deadline:
            raise AssertionError('private compiler client did not publish ' + path.name)
        time.sleep(0.01)


def pin_server(owner, expected, stack):
    """Retain exact native process identity; never reopen a PID after cleanup."""
    job = owner.job
    matches = []
    for pid in job.process_ids():
        handle = job.api.OpenProcess(0x100000 | 0x1000, False, pid)
        if not handle:
            job.fail('pin native diagnostic member')
        def close(handle=handle):
            if not job.api.CloseHandle(handle):
                job.fail('close native diagnostic member')
        stack.callback(close)
        member = job.w.BOOL()
        if not job.api.IsProcessInJob(handle, job.handle, ctypes.byref(member)) or not member.value:
            raise process_tree.ProcessTreeError('diagnostic process is not in its exact owned Job')
        state = job.api.WaitForSingleObject(handle, 0)
        if state == 0:
            continue
        if state != 0x102:
            job.fail('observe native diagnostic member')
        image = ctypes.create_unicode_buffer(32768); size = job.w.DWORD(len(image))
        if not job.api.QueryFullProcessImageNameW(handle, 0, image, ctypes.byref(size)):
            job.fail('identify native diagnostic member')
        if not 0 < size.value < len(image) or size.value != len(image.value):
            raise process_tree.ProcessTreeError('invalid native diagnostic member image')
        if Path(image.value).samefile(expected):
            matches.append((pid, handle, image.value))
    if len(matches) != 1:
        raise AssertionError('one live private MSPDBSRV is required; observed ' + str(len(matches)))
    return matches[0]


class WindowsHosts(unittest.TestCase):
    def setUp(self):
        if platform.system() != 'Windows':
            raise RuntimeError('windows_hosts requires its native Windows host')

    def test_compiler_probe_completes_with_all_descendants_joined(self):
        compiler = shutil.which('cl.exe')
        self.assertIsNotNone(compiler, 'selected installed MSVC cl.exe is required')
        identity = compiler_identity(compiler)
        strict = os.environ.get('FOUNDATION_MSVC_STRICT_COMPLETION', '0')
        if strict not in ('0', '1'):
            raise ValueError('FOUNDATION_MSVC_STRICT_COMPLETION must be 0 or 1')
        print(json.dumps(dict(identity, source_sha256=digest(ROOT / 'tools/windows_gl_probe.cpp'),
                              strict_completion=strict == '1')), flush=True)
        with workspace(process_tree.ProcessTreeError) as directory:
            executable, receipt = windows_graphics.compile_probe(directory, directory / 'compile.log',
                                                                 environment=dict(os.environ), strict_completion=strict == '1')
            output_identity = probe_identity(executable)
            self.assertEqual(receipt['source_sha256'], digest(ROOT / 'tools/windows_gl_probe.cpp'))
            self.assertEqual(identity, compiler_identity(compiler), 'compiler/linker changed during the native probe')
            print(json.dumps({'compile': receipt, 'output': output_identity}), flush=True)
            # No driver download or WGL execution is needed to reproduce the compiler lifetime.

    def test_private_pdb_sessions_join_without_stopping_other_builds(self):
        compiler = shutil.which('cl.exe')
        self.assertIsNotNone(compiler, 'selected installed MSVC cl.exe is required')
        identity = compiler_identity(compiler)
        with workspace(process_tree.ProcessTreeError) as directory:
            sessions, owners, folders = [], [], []
            with ExitStack() as stack:
                for name in ('first', 'control'):
                    folder = directory / name; folder.mkdir(); folders.append(folder)
                    session = windows_compiler.BuildSession(dict(os.environ)); sessions.append(session)
                    stream = stack.enter_context((folder / 'compile.log').open('xb'))
                    owner = process_tree.launch([sys.executable, '-B', '-c', PDB_CLIENT, str(folder), compiler],
                                                folder, stream, env=session.environment)
                    stack.callback(owner.close); owners.append(owner)
                self.assertNotEqual(sessions[0].endpoint, sessions[1].endpoint)
                deadline = time.monotonic() + 60
                for folder, owner in zip(folders, owners):
                    wait_marker(folder / 'ready', owner, deadline)
                pinned = [pin_server(owner, session.paths['mspdbsrv.exe'], stack)
                          for owner, session in zip(owners, sessions)]
                self.assertNotEqual(pinned[0][0], pinned[1][0], 'private endpoints reused one server')
                outputs = []
                for folder in folders:
                    row = {'executable': probe_identity(folder / 'unit.exe'), 'pdb': {}}
                    for name in ('compiler.pdb', 'linked.pdb'):
                        self.assertGreater((folder / name).stat().st_size, 0)
                        row['pdb'][name] = executable_identity(folder / name)
                    outputs.append(row)
                (folders[0] / 'stop').write_text('stop')
                self.assertEqual(owners[0].wait(timeout=10), 0)
                first = sessions[0].finish(owners[0])
                self.assertEqual(owners[0].job.api.WaitForSingleObject(pinned[0][1], 0), 0)
                self.assertEqual(owners[1].job.api.WaitForSingleObject(pinned[1][1], 0), 0x102,
                                 'finishing the first build stopped the other private PDB server')
                (folders[1] / 'again').write_text('compile again')
                wait_marker(folders[1] / 'recompiled', owners[1], time.monotonic() + 30)
                self.assertEqual(owners[1].job.api.WaitForSingleObject(pinned[1][1], 0), 0x102,
                                 'control build silently replaced its original PDB server')
                same_server = pin_server(owners[1], sessions[1].paths['mspdbsrv.exe'], stack)
                self.assertEqual(same_server[0], pinned[1][0], 'control build created a replacement server')
                (folders[1] / 'stop').write_text('stop')
                self.assertEqual(owners[1].wait(timeout=10), 0)
                control = sessions[1].finish(owners[1])
                self.assertEqual(owners[1].job.api.WaitForSingleObject(pinned[1][1], 0), 0)
                for receipt, member in zip((first, control), pinned):
                    self.assertTrue(any(row['name'] == 'mspdbsrv.exe' and row['pid'] == member[0]
                                        for row in receipt['helpers']))
                print(json.dumps({'private_pdb_sessions': [first, control],
                                  'control_server_survived_other_cleanup': True, 'outputs': outputs}), flush=True)
            self.assertEqual(identity, compiler_identity(compiler))
            for folder in folders:
                moved = folder.with_name(folder.name + '-released')
                folder.rename(moved); shutil.rmtree(moved)
            self.assertFalse(any(directory.iterdir()))

    def test_firefox_session_close_releases_profile_immediately(self):
        executable = Path('C:/Program Files/Mozilla Firefox/firefox.exe')
        identity = executable_identity(executable)  # Same installed path as native certification.
        print(json.dumps({'firefox': identity}), flush=True)
        spec = importlib.util.spec_from_file_location('diagnostic_browser', ROOT / 'gui/tests/browser_test.py')
        browser_module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(browser_module)
        with workspace(browser_module.BrowserCleanupError) as directory:
            browser = browser_module.Browser(str(executable), directory)
            try:
                self.assertEqual(browser.capabilities['browserName'].lower(), 'firefox')
                self.assertTrue(browser.capabilities['browserVersion'])
                print(json.dumps({'browser_name': browser.capabilities['browserName'],
                                  'browser_version': browser.capabilities['browserVersion']}), flush=True)
                browser.command('WebDriver:Navigate', {'url': 'about:blank'})
                self.assertEqual(browser.script('return document.location.href;'), 'about:blank')
                self.assertEqual(browser.script('document.body.textContent="native host probe"; return document.body.textContent;'),
                                 'native host probe')
            finally:
                browser.close()
            self.assertEqual(identity, executable_identity(executable), 'Firefox changed during the native probe')
            released = directory / 'released-profile'
            browser.profile.rename(released)
            shutil.rmtree(released)
            self.assertFalse(browser.profile.exists())
            self.assertFalse(released.exists())
            # Whole workspace removal additionally exercises the now-closed browser log.
