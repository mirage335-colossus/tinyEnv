"""Host input mechanics with tiny fixtures; native WGL requires Windows evidence."""
import copy
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
import windows_graphics as graphics


def digest(data):
    return hashlib.sha256(data).hexdigest()


class WindowsGraphicsTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.cache = self.root / 'retained.7z'
        self.cache.write_bytes(b'fixture archive')
        self.payloads = {'opengl32.dll': b'fixture loader', 'libgallium_wgl.dll': b'fixture renderer'}
        self.metadata = copy.deepcopy(graphics.lock())
        self.metadata['archive'].update(size=self.cache.stat().st_size, sha256=digest(self.cache.read_bytes()))
        for name, data in self.payloads.items():
            self.metadata['files'][name].update(size=len(data), sha256=digest(data))
        self.lock = self.root / 'lock.json'
        self.save_lock()
        self.addCleanup(patch.stopall)
        patch.object(graphics, 'LOCK_PATH', self.lock).start()
        patch.object(graphics, '_msvc_telemetry', return_value=None).start()
        self.app = self.root / 'application'
        self.app.mkdir()

    def save_lock(self):
        self.lock.write_text(json.dumps(self.metadata))

    def listing(self):
        return ('\n\n'.join('Path = ' + entry['member'] + '\nSize = ' + str(entry['size']) +
                           '\nAttributes = A\nFolder = -' for entry in self.metadata['files'].values()) + '\n').encode()

    def command(self, argv, **kwargs):
        if 'l' == argv[1]:
            return self.listing()
        self.assertEqual(['x', '-so', '-spd', '-y', '-bso0', '-bsp0', '-bse2'], argv[1:8])
        return self.payloads[Path(argv[-1]).name]

    def stage(self, **kwargs):
        return graphics.stage(self.cache, [self.app], environment={}, **kwargs)

    def install(self):
        for name, data in self.payloads.items():
            (self.app / name).write_bytes(data)

    def probe(self):
        return {'schema_version': 1, 'status': 'passed', 'opengl32_path': str(self.app / 'opengl32.dll'),
                'libgallium_wgl_path': str(self.app / 'libgallium_wgl.dll'), 'version': '4.5 Mesa fixture',
                'vendor': 'Mesa', 'renderer': 'llvmpipe fixture', 'major': 4, 'minor': 5,
                'wgl_create_context_attribs_arb': True, 'wgl_choose_pixel_format_arb': True,
                'arb_buffer_storage': True, 'gl_buffer_storage': True, 'error': ''}

    def test_lock_identity_and_exact_selected_members(self):
        self.assertEqual('host-qualification-only', graphics.verify_archive(self.cache)['scope'])
        self.assertEqual(set(graphics.SELECTED), set(graphics.lock()['files']))
        self.cache.write_bytes(b'x' * self.metadata['archive']['size'])
        with self.assertRaisesRegex(graphics.GraphicsError, 'bytes differ'):
            graphics.verify_archive(self.cache)

    def test_missing_archive_never_implicitly_downloads(self):
        with patch.object(graphics.urllib.request, 'build_opener') as opener:
            with self.assertRaisesRegex(graphics.GraphicsError, 'explicit maintenance'):
                graphics.fetch(self.root / 'absent.7z')
            opener.assert_not_called()

    def test_verified_cache_reused_without_network(self):
        with patch.object(graphics.urllib.request, 'build_opener') as opener:
            self.assertEqual('verified-cache', graphics.fetch(self.cache, network=True)['acquisition'])
            opener.assert_not_called()

    def test_https_and_redirect_policy_rejects_credentials_and_downgrade(self):
        for url in ('http://example.invalid/a', 'https://name:secret@example.invalid/a',
                    'https://example.invalid/a#fragment', 'https://example.invalid/\n'):
            with self.subTest(url=url), self.assertRaises(graphics.GraphicsError):
                graphics.fetch_retained(url, self.root / 'absent.7z')
        request = graphics.urllib.request.Request('https://example.invalid/a')
        with self.assertRaises(graphics.GraphicsError):
            graphics._HTTPSRedirect().redirect_request(request, None, 302, 'redirect', {}, 'http://example.invalid/b')

    def response(self, data):
        result = io.BytesIO(data)
        result.geturl = lambda: 'https://example.invalid/retained?private=value'
        result.headers = {}
        return result

    def test_explicit_transfer_verifies_before_atomic_publication(self):
        target = self.root / 'new.7z'
        with patch.object(graphics.urllib.request, 'build_opener') as factory:
            factory.return_value.open.return_value = self.response(self.cache.read_bytes())
            receipt = graphics.fetch_retained('https://example.invalid/input?private=value', target)
        self.assertEqual(self.cache.read_bytes(), target.read_bytes())
        self.assertNotIn('private', json.dumps(receipt))
        self.assertFalse(list(self.root.glob('.graphics-fetch-*')))

    def test_bad_transfer_does_not_publish_or_leak_access_query(self):
        target = self.root / 'new.7z'
        with patch.object(graphics.urllib.request, 'build_opener') as factory:
            factory.return_value.open.return_value = self.response(b'x' * self.cache.stat().st_size)
            with self.assertRaises(graphics.GraphicsError):
                graphics.fetch_retained('https://example.invalid/input?private=value', target)
        self.assertFalse(target.exists())
        self.assertFalse(list(self.root.glob('.graphics-fetch-*')))

    def test_selective_stage_multiple_destinations_and_cleanup(self):
        second = self.root / 'probe'
        second.mkdir()
        (self.app / 'foreign.txt').write_text('keep')
        with patch.object(graphics, '_command', side_effect=self.command) as commands:
            with graphics.stage(self.cache, [self.app, second], environment={'SAFE': 'value'}) as staged:
                self.assertEqual('llvmpipe', staged.environment['GALLIUM_DRIVER'])
                self.assertEqual(4, len(staged.receipt['files']))
                for directory in (self.app, second):
                    for name, data in self.payloads.items():
                        self.assertEqual(data, (directory / name).read_bytes())
            self.assertEqual(3, commands.call_count)
        self.assertEqual('removed', staged.receipt['cleanup'])
        self.assertEqual(['foreign.txt'], [path.name for path in self.app.iterdir()])
        self.assertEqual([], list(second.iterdir()))

    def test_no_clobber_including_case_alias(self):
        foreign = self.app / 'OpenGL32.DLL'
        foreign.write_bytes(b'foreign')
        with patch.object(graphics, '_command') as command:
            with self.assertRaisesRegex(graphics.GraphicsError, 'already exists'), self.stage():
                self.fail('must not enter')
            command.assert_not_called()
        self.assertEqual(b'foreign', foreign.read_bytes())

    def test_rejects_protected_roots_and_duplicate_directories(self):
        for directories, protected in (([self.app], [self.root]), ([self.app, self.app], [])):
            with self.subTest(directories=directories), self.assertRaises(graphics.GraphicsError):
                with graphics.stage(self.cache, directories, protected_roots=protected):
                    self.fail('must not enter')

    def test_absent_protected_scope_is_retained_without_creation(self):
        protected = self.root / 'future-sdk' / 'sysroot'
        with patch.object(graphics, '_command', side_effect=self.command):
            with self.stage(protected_roots=[protected]):
                self.assertFalse(protected.exists())
        with self.assertRaises(graphics.GraphicsError):
            with self.stage(protected_roots=[self.app / 'future-sdk']):
                self.fail('must reject an ancestor of protected inputs')

    def test_reparse_or_link_metadata_is_rejected(self):
        with patch.object(graphics, '_plain', return_value=False):
            with self.assertRaises(graphics.GraphicsError):
                graphics.verify_archive(self.cache)

    def test_override_rejection_is_case_insensitive_and_environment_private(self):
        for key in graphics.FORBIDDEN_ENV:
            with self.assertRaises(graphics.GraphicsError):
                graphics.child_environment({key.lower(): ''})
        environment = {'gallium_driver': 'other', 'secret': 'hidden'}
        copied = graphics.child_environment(environment)
        self.assertEqual('other', environment['gallium_driver'])
        self.assertEqual('llvmpipe', copied['GALLIUM_DRIVER'])
        self.assertNotIn('gallium_driver', copied)

    def test_unsafe_duplicate_and_missing_archive_entries_rejected(self):
        for value in (self.listing() + self.listing(), self.listing().replace(b'x64/opengl32.dll', b'../opengl32.dll'),
                      self.listing().replace(b'Folder = -', b'Folder = +'),
                      self.listing() + b'\nPath = x64/other\nSize = 0\nSymbolic Link = /tmp\n'):
            # Unselected links are harmless because no archive path is extracted;
            # selected links and unsafe/duplicate paths must still fail closed.
            if b'Symbolic Link' in value:
                value = self.listing().replace(b'Folder = -', b'Symbolic Link = /tmp')
            with self.subTest(listing=value), self.assertRaises(graphics.GraphicsError):
                graphics._listing(value, self.metadata)

    def test_actual_windows_7zip_listing_matches_locked_members(self):
        # Selected records from Windows 7-Zip 26.03, -slt -ba -sccUTF-8, reading
        # the locked archive. This is console-output evidence, not WGL evidence.
        raw = (b'Path = x64\\libgallium_wgl.dll\r\nSize = 61868544\r\nPacked Size = \r\n'
               b'Modified = 2026-09-26 20:58:33.3376780\r\nAttributes = A\r\nCRC = 0BA88BAC\r\n'
               b'Encrypted = -\r\nMethod = BCJ2 LZMA2:28 LZMA:20:lc0:lp2 LZMA:20:lc0:lp2\r\nBlock = 1\r\n\r\n'
               b'Path = x64\\opengl32.dll\r\nSize = 139264\r\nPacked Size = \r\n'
               b'Modified = 2026-09-26 21:04:22.6457865\r\nAttributes = A\r\nCRC = 118B73A7\r\n'
               b'Encrypted = -\r\nMethod = BCJ2 LZMA2:28 LZMA:20:lc0:lp2 LZMA:20:lc0:lp2\r\nBlock = 1\r\n\r\n')
        metadata = json.loads((ROOT/'third_party/host-graphics/mesa-windows.json').read_bytes())
        graphics._listing(raw,metadata)
        graphics._listing(raw.replace(b'\\',b'/').replace(b'\r\n',b'\n'),metadata)

    def test_native_separator_listing_stages_only_canonical_locked_members(self):
        raw = self.listing().replace(b'/',b'\\').replace(b'\n',b'\r\n')
        def command(argv, **kwargs):
            if argv[1] == 'l': return raw
            self.assertIn(argv[-1],['x64/'+name for name in graphics.SELECTED])
            return self.command(argv,**kwargs)
        with patch.object(graphics,'_command',side_effect=command) as commands:
            with self.stage() as staged:
                self.assertEqual(set(graphics.SELECTED),{p.name for p in self.app.iterdir()})
                for name, data in self.payloads.items(): self.assertEqual(data,(self.app/name).read_bytes())
            self.assertEqual(3,commands.call_count)
        self.assertEqual('removed',staged.receipt['cleanup'])
        self.assertEqual([],list(self.app.iterdir()))

    def test_native_listing_separators_do_not_enable_path_aliases_or_links(self):
        raw = self.listing().replace(b'/',b'\\')
        invalid = (b'..\\opengl32.dll', b'x64\\..\\opengl32.dll', b'\\opengl32.dll',
                   b'C:\\x64\\opengl32.dll', b'\\\\server\\share\\opengl32.dll',
                   b'x64\\.\\opengl32.dll', b'x64\\\\opengl32.dll',
                   b'x64/child\\opengl32.dll', b'x64/opengl32.dll')
        for name in invalid:
            value = raw.replace(b'x64\\opengl32.dll',name)
            with self.subTest(name=name),self.assertRaisesRegex(graphics.GraphicsError,'archive.*path') as caught:
                graphics._listing(value,self.metadata)
            displayed = [line[7:].decode() for line in value.splitlines() if line.startswith(b'Path = ')]
            self.assertTrue(any(repr(path) in str(caught.exception) for path in displayed))
        for value in (raw + raw.replace(b'x64',b'X64'),
                      raw.replace(b'Folder = -',b'Symbolic Link = target'),
                      raw.replace(b'Folder = -',b'Hard Link = target'),
                      raw.replace(b'Folder = -',b'Folder = +'),
                      raw.replace(b'Size = ',b'Size = 9'),
                      raw.replace(b'x64\\opengl32.dll',b'x64\\OpenGL32.dll')):
            with self.subTest(value=value),self.assertRaises(graphics.GraphicsError):
                graphics._listing(value,self.metadata)

    def test_partial_extraction_failure_removes_only_owned_files(self):
        def command(argv, **kwargs):
            return b'bad' if argv[-1].endswith('libgallium_wgl.dll') else self.command(argv, **kwargs)
        with patch.object(graphics, '_command', side_effect=command):
            with self.assertRaisesRegex(graphics.GraphicsError, 'driver bytes'), self.stage():
                self.fail('must not enter')
        self.assertEqual([], list(self.app.iterdir()))

    def test_cleanup_preserves_replaced_or_modified_files(self):
        with patch.object(graphics, '_command', side_effect=self.command):
            with self.assertRaisesRegex(graphics.GraphicsError, 'cleanup preserved'):
                with self.stage() as staged:
                    (self.app / 'opengl32.dll').write_bytes(b'changed')
        self.assertEqual('preserved-changed-files', staged.receipt['cleanup'])
        self.assertEqual(b'changed', (self.app / 'opengl32.dll').read_bytes())
        self.assertFalse((self.app / 'libgallium_wgl.dll').exists())

    def test_uncertain_writers_preserve_driver_files(self):
        with patch.object(graphics, '_command', side_effect=self.command):
            with self.assertRaisesRegex(graphics.GraphicsError, 'cleanup preserved') as caught:
                with self.stage() as staged:
                    staged.mark_writers_uncertain()
        self.assertEqual('retained-uncertain', staged.receipt['cleanup'])
        self.assertIs(staged.receipt, caught.exception.graphics_receipt)
        self.assertEqual(2, len(list(self.app.iterdir())))

    def test_process_error_before_stage_yield_retains_failure_receipt(self):
        def command(argv, **kwargs):
            if argv[-1].endswith('libgallium_wgl.dll'):
                raise graphics.process_tree.ProcessTreeError('fixture uncertain cleanup')
            return self.command(argv, **kwargs)
        with patch.object(graphics, '_command', side_effect=command):
            with self.assertRaises(graphics.GraphicsError) as caught, self.stage():
                self.fail('must not enter')
        self.assertEqual('retained-uncertain', caught.exception.graphics_receipt['cleanup'])
        self.assertEqual(['opengl32.dll'], [item.name for item in self.app.iterdir()])

    def test_precompile_failure_attaches_safe_cleanup_receipt(self):
        directory = self.root / 'probe'
        directory.mkdir()
        with patch.object(graphics.shutil, 'which', return_value=None):
            with self.assertRaises(graphics.GraphicsError) as caught:
                with graphics.qualified_stage(self.cache, [self.app], probe_directory=directory,
                                              compile_log=self.root / 'compile.log', environment={}):
                    self.fail('must not enter')
        self.assertEqual('removed', caught.exception.graphics_receipt['cleanup'])
        self.assertEqual([], list(directory.iterdir()))

    def test_retention_follows_chained_errors_and_nonremoved_receipts(self):
        failure = graphics.process_tree.ProcessTreeError('uncertain')
        hidden = OSError('log publication failed')
        hidden.__cause__ = failure
        hidden.graphics_receipt = {'cleanup': 'removed'}
        self.assertTrue(graphics.retain_required(hidden))
        changed = graphics.GraphicsError('changed file')
        changed.graphics_receipt = {'cleanup': 'preserved-changed-files'}
        self.assertTrue(graphics.retain_required(changed))
        self.assertFalse(graphics.retain_required(graphics.GraphicsError('known stopped command failure')))
        with patch.object(graphics, '_command', side_effect=self.command):
            with self.assertRaises(graphics.GraphicsError) as caught:
                with self.stage():
                    raise hidden
        self.assertEqual('retained-uncertain', caught.exception.graphics_receipt['cleanup'])
        self.assertEqual(2, len(list(self.app.iterdir())))

    def test_native_probe_receipt_requires_actual_loaded_files(self):
        self.install()
        executable = self.app / 'probe.exe'
        executable.write_bytes(b'fixture executable')
        with patch.object(graphics, '_command', return_value=json.dumps(self.probe()).encode()):
            result = graphics.run_probe(executable, environment={}, expected_directory=self.app)
        self.assertEqual(self.metadata['archive']['sha256'], result['archive_sha256'])
        for field, value in (('opengl32_path', str(self.root / 'opengl32.dll')),
                             ('libgallium_wgl_path', str(self.root / 'libgallium_wgl.dll')),
                             ('renderer', 'another driver'), ('major', 3), ('wgl_choose_pixel_format_arb', False),
                             ('status', 'failed'), ('major', True), ('gl_buffer_storage', False)):
            receipt = self.probe()
            receipt[field] = value
            with self.subTest(field=field), patch.object(graphics, '_command', return_value=json.dumps(receipt).encode()):
                with self.assertRaises(graphics.GraphicsError):
                    graphics.run_probe(executable, environment={}, expected_directory=self.app)

    def test_opengl_43_requires_buffer_storage_and_44_does_not(self):
        self.install()
        executable = self.app / 'probe.exe'
        executable.write_bytes(b'exe')
        for minor, storage, succeeds in ((3, False, False), (3, True, True), (4, False, True)):
            receipt = self.probe()
            receipt.update(minor=minor, arb_buffer_storage=storage)
            with self.subTest(minor=minor, storage=storage), patch.object(graphics, '_command', return_value=json.dumps(receipt).encode()):
                if succeeds:
                    graphics.run_probe(executable, environment={}, expected_directory=self.app)
                else:
                    with self.assertRaises(graphics.GraphicsError):
                        graphics.run_probe(executable, environment={}, expected_directory=self.app)

    def test_bounded_command_runs_with_explicit_child_environment(self):
        environment = dict(os.environ, GRAPHICS_FIXTURE='expected')
        output = graphics._command([sys.executable, '-c', 'import os; print(os.environ["GRAPHICS_FIXTURE"])'],
                                   directory=self.app, environment=environment, limit=100, timeout=10)
        self.assertEqual(b'expected', output.strip())
        self.assertNotIn('GRAPHICS_FIXTURE', os.environ)

    def test_command_timeout_output_limit_and_failure_close_writers(self):
        for source, limit, timeout in (('import time; time.sleep(5)', 100, 0.05),
                                       ('print("x"*1000)', 10, 10), ('raise SystemExit(2)', 100, 10)):
            with self.subTest(source=source), self.assertRaises(graphics.GraphicsError):
                graphics._command([sys.executable, '-c', source], directory=self.app,
                                  environment=dict(os.environ), limit=limit, timeout=timeout)
        self.assertEqual([], list(self.app.iterdir()))

    def test_run_owned_retains_bounded_log_on_success_and_failure(self):
        log = self.app / 'success.log'
        receipt = graphics.run_owned([sys.executable, '-c', 'print("passed")'], self.app, log,
                                     environment=dict(os.environ), timeout=10, max_bytes=100)
        self.assertEqual(digest(log.read_bytes()), receipt['log_sha256'])
        with self.assertRaisesRegex(graphics.GraphicsError, 'already exists'):
            graphics.run_owned([sys.executable, '-c', 'print("changed")'], self.app, log)
        failure = self.app / 'failure.log'
        with self.assertRaises(graphics.GraphicsError):
            graphics.run_owned([sys.executable, '-c', 'print("failed"); raise SystemExit(2)'],
                               self.app, failure, environment=dict(os.environ), timeout=10, max_bytes=100)
        self.assertEqual(b'failed', failure.read_bytes().strip())

    def test_compile_probe_without_driver_preserves_exact_command_and_receipt(self):
        directory = self.root / 'probe'; directory.mkdir()
        log = self.root / 'compile.log'
        def command(argv, **kwargs):
            self.assertEqual(argv, ['fixture-cl.exe', '/nologo', '/std:c++20', '/EHsc',
                str(ROOT / 'tools/windows_gl_probe.cpp'), '/Fo:' + str(directory / 'windows-gl-probe.obj'),
                '/Fe:' + str(directory / 'windows-gl-probe.exe'), '/link', '/INCREMENTAL:NO',
                'opengl32.lib', 'gdi32.lib', 'user32.lib'])
            self.assertEqual(kwargs['limit'], 1024 * 1024)
            self.assertEqual(kwargs['timeout'], 300)
            (directory / 'windows-gl-probe.exe').write_bytes(b'compiled fixture')
            (directory / 'windows-gl-probe.obj').write_bytes(b'object')
            Path(kwargs['record']).write_bytes(b'compile success')
        with patch.object(graphics.shutil, 'which', return_value='fixture-cl.exe'), \
             patch.object(graphics, '_command', side_effect=command) as run, \
             patch.object(graphics, 'stage') as stage, patch.object(graphics, 'fetch') as fetch:
            executable, receipt = graphics.compile_probe(directory, log, environment={'PATH': 'selected'})
            self.assertEqual(executable, directory / 'windows-gl-probe.exe')
            self.assertEqual(receipt['source_sha256'], digest((ROOT / 'tools/windows_gl_probe.cpp').read_bytes()))
            self.assertEqual(receipt['executable_sha256'], digest(b'compiled fixture'))
            self.assertEqual(receipt['log_sha256'], digest(b'compile success'))
            self.assertEqual(receipt['compiler'], str(Path('fixture-cl.exe').absolute()))
            stage.assert_not_called(); fetch.assert_not_called()
            with self.assertRaisesRegex(graphics.GraphicsError, 'already exists'):
                graphics.compile_probe(directory, log, environment={})
            run.assert_called_once()

    def test_explicit_strict_compile_does_not_enable_helper_policy(self):
        directory = self.root / 'probe'; directory.mkdir()
        def command(argv, **kwargs):
            self.assertIsNone(kwargs['compiler_helper'])
            (directory / 'windows-gl-probe.exe').write_bytes(b'compiled fixture')
            Path(kwargs['record']).write_bytes(b'log')
        with patch.object(graphics.shutil, 'which', return_value='fixture-cl.exe'), \
                patch.object(graphics, '_command', side_effect=command), \
                patch.object(graphics, '_msvc_telemetry') as policy:
            _, receipt = graphics.compile_probe(directory, self.root / 'compile.log', strict_completion=True)
        policy.assert_not_called()
        self.assertEqual(receipt['completion'], {'policy': 'strict', 'outcome': 'no-surviving-descendants', 'stopped_pids': []})

    def test_command_helper_hook_is_only_used_after_successful_parent(self):
        class Helper:
            def __init__(self): self.calls = 0
            def finish(self, owner):
                self.calls += 1
                owner.finish()
        helper = Helper()
        graphics._command([sys.executable, '-c', 'print("complete")'], directory=self.app,
                          environment=dict(os.environ), limit=100, timeout=10, compiler_helper=helper)
        self.assertEqual(helper.calls, 1)
        with self.assertRaises(graphics.GraphicsError):
            graphics._command([sys.executable, '-c', 'raise SystemExit(2)'], directory=self.app,
                              environment=dict(os.environ), limit=100, timeout=10, compiler_helper=helper)
        self.assertEqual(helper.calls, 1)

    def test_compile_probe_missing_compiler_and_protected_outputs_fail_before_launch(self):
        directory = self.root / 'probe'; directory.mkdir()
        with patch.object(graphics.shutil, 'which', return_value=None), patch.object(graphics, '_command') as run:
            with self.assertRaisesRegex(graphics.GraphicsError, 'MSVC cl.exe is unavailable'):
                graphics.compile_probe(directory, self.root / 'compile.log', environment={})
            with self.assertRaisesRegex(graphics.GraphicsError, 'protected'):
                graphics.compile_probe(directory, self.root / 'compile.log', protected_roots=[self.root])
            run.assert_not_called()

    def test_qualified_stage_compiles_selected_probe_and_checks_before_yield(self):
        directory = self.root / 'probe'
        directory.mkdir()
        log = self.root / 'compile.log'
        def command(argv, **kwargs):
            if argv[0] == 'fixture-cl.exe':
                self.assertIn('/std:c++20', argv)
                self.assertIn('/INCREMENTAL:NO', argv)
                for argument in argv:
                    if argument.startswith(('/Fo:', '/Fe:')):
                        Path(argument[4:]).write_bytes(b'compiled fixture')
                Path(kwargs['record']).write_bytes(b'compile success')
                return b'compile success'
            if len(argv) == 1:
                result = self.probe()
                result.update(opengl32_path=str(directory / 'opengl32.dll'),
                              libgallium_wgl_path=str(directory / 'libgallium_wgl.dll'))
                return json.dumps(result).encode()
            return self.command(argv, **kwargs)
        with patch.object(graphics.shutil, 'which', return_value='fixture-cl.exe'), patch.object(graphics, '_command', side_effect=command):
            with graphics.qualified_stage(self.cache, [self.app], probe_directory=directory,
                                          compile_log=log, environment={'PATH': 'selected'},
                                          protected_roots=[self.root / 'future-sdk']) as staged:
                self.assertEqual('passed', staged.probe_receipt['probe']['status'])
                self.assertEqual(digest(b'compile success'), staged.receipt['compile']['log_sha256'])
                self.assertEqual(4, len(staged.receipt['files']))
            self.assertEqual('removed', staged.receipt['cleanup'])
            self.assertEqual([], list(self.app.iterdir()))
            with self.assertRaisesRegex(graphics.GraphicsError, 'already exists'):
                with graphics.qualified_stage(self.cache, [self.app], probe_directory=directory,
                                              compile_log=log, environment={}):
                    self.fail('must not overwrite previous evidence')


class MsvcTelemetryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()
        self.compiler = self.root / 'cl.exe'; self.compiler.write_bytes(b'compiler')
        self.helper = self.root / 'vctip.exe'; self.helper.write_bytes(b'telemetry')

    def policy(self):
        return graphics._MsvcTelemetry(self.compiler, self.helper)

    def test_exact_helper_receipt_requires_completed_join_and_reports_empty_inventory(self):
        for pids in ([], [10, 20]):
            with self.subTest(pids=pids):
                policy = self.policy()
                with self.assertRaisesRegex(graphics.GraphicsError, 'not been established'):
                    policy.receipt()
                from unittest.mock import Mock
                owner = Mock()
                def terminate(*, validate_live):
                    owner.finish.assert_not_called()
                    for pid in pids: self.assertTrue(validate_live(pid, str(self.helper)))
                owner.terminate.side_effect = terminate
                policy.finish(owner)
                owner.finish.assert_called_once_with()
                receipt = policy.receipt()
                self.assertEqual(receipt['stopped_pids'], pids)
                self.assertEqual(receipt['outcome'], 'verified-helper-terminated-and-joined' if pids else 'no-surviving-helper')
                self.assertEqual(receipt['helper'], {'path': str(self.helper), 'sha256': digest(b'telemetry')})
                self.assertEqual(receipt['compiler'], {'path': str(self.compiler), 'sha256': digest(b'compiler')})

    def test_same_basename_and_same_bytes_in_another_directory_are_rejected(self):
        other = self.root / 'foreign'; other.mkdir(); foreign = other / 'vctip.exe'
        foreign.write_bytes(self.helper.read_bytes())
        with self.assertRaisesRegex(graphics.GraphicsError, 'exact selected toolkit'):
            graphics._MsvcTelemetry(self.compiler, foreign)
        policy = self.policy()
        with self.assertRaisesRegex(graphics.process_tree.ProcessTreeError, 'exact selected VCTIP'):
            policy.validate(123, str(foreign))
        self.assertEqual(policy.stopped_pids, [])

    def test_changed_compiler_or_helper_never_grants_completion(self):
        for filename in ('cl.exe', 'vctip.exe'):
            with self.subTest(filename=filename):
                policy = self.policy(); path = self.root / filename; original = path.read_bytes()
                path.write_bytes(original + b'changed')
                with self.assertRaisesRegex(graphics.GraphicsError, 'changed during compilation'):
                    policy.validate(10, str(self.helper))
                self.assertEqual(policy.stopped_pids, [])
                path.write_bytes(original)

    def test_unconfirmed_owner_join_cannot_produce_helper_receipt(self):
        from unittest.mock import Mock
        policy = self.policy(); owner = Mock()
        owner.terminate.side_effect = graphics.process_tree.ProcessTreeError('join unconfirmed')
        with self.assertRaisesRegex(graphics.process_tree.ProcessTreeError, 'join unconfirmed'):
            policy.finish(owner)
        owner.finish.assert_not_called()
        with self.assertRaisesRegex(graphics.GraphicsError, 'not been established'):
            policy.receipt()


if __name__ == '__main__':
    unittest.main()
