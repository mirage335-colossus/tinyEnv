import importlib.util
import io
import os
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile
import unittest
import zipfile

spec = importlib.util.spec_from_file_location("artifact", Path(__file__).resolve().parents[1] / "tools/artifact.py")
artifact = importlib.util.module_from_spec(spec)
spec.loader.exec_module(artifact)


class InstalledProviderConsumerTests(unittest.TestCase):
    """A relocated static export must match its executing provider, not its label."""

    def setUp(self):
        tools = str(Path(artifact.__file__).resolve().parent)
        if tools not in sys.path:
            sys.path.insert(0, tools)

    def fixture(self, root, actual_provider):
        source = Path(artifact.__file__).resolve().parents[1]
        import windows_compiler
        producer = root / "producer"
        producer.mkdir()
        provider = '#include "text_validation.h"\n'
        provider += 'namespace foundation::detail { uint32_t validate_text(const uint8_t*, size_t) noexcept { return 0; } }\n'
        if actual_provider is not None:
            provider += 'extern "C" uint32_t foundation_text_provider_v1() noexcept { return ' + str(actual_provider) + '; }\n'
        (producer / "provider.cpp").write_text(provider)
        (producer / "version.hpp").write_text('#pragma once\n#define FOUNDATION_VERSION "0.1.0"\n')
        (producer / "FoundationConfig.cmake.in").write_text('''
add_library(foundation::core STATIC IMPORTED)
set_target_properties(foundation::core PROPERTIES
  IMPORTED_LOCATION "${CMAKE_CURRENT_LIST_DIR}/../../../lib/@CMAKE_STATIC_LIBRARY_PREFIX@foundation_fixture@CMAKE_STATIC_LIBRARY_SUFFIX@"
  INTERFACE_INCLUDE_DIRECTORIES "${CMAKE_CURRENT_LIST_DIR}/../../../include"
  INTERFACE_COMPILE_FEATURES cxx_std_20)
function(foundation_apply_runtime target)
endfunction()
''')
        (producer / "FoundationConfigVersion.cmake").write_text(
            'set(PACKAGE_VERSION "0.1.0")\nset(PACKAGE_VERSION_COMPATIBLE TRUE)\n')
        (producer / "CMakeLists.txt").write_text('''
cmake_minimum_required(VERSION 3.24)
project(FoundationProviderFixture LANGUAGES CXX)
add_library(foundation_fixture STATIC "''' + (source / 'src/store.cpp').as_posix() + '''" provider.cpp)
target_compile_features(foundation_fixture PRIVATE cxx_std_20)
target_include_directories(foundation_fixture PRIVATE "''' + (source / 'include').as_posix() + '''" "''' + (source / 'src').as_posix() + '''")
configure_file(FoundationConfig.cmake.in FoundationConfig.cmake @ONLY)
install(TARGETS foundation_fixture ARCHIVE DESTINATION lib)
install(DIRECTORY "''' + (source / 'include/foundation').as_posix() + '''" DESTINATION include)
install(FILES version.hpp DESTINATION include/foundation)
install(FILES "${CMAKE_CURRENT_BINARY_DIR}/FoundationConfig.cmake" FoundationConfigVersion.cmake DESTINATION lib/cmake/Foundation)
''')
        original = root / "original prefix"
        build = root / "producer build"
        windows_compiler.run(['cmake', '-S', str(producer), '-B', str(build), '-G', 'Ninja',
                              '-DCMAKE_BUILD_TYPE=Release', '-DCMAKE_INSTALL_PREFIX=' + str(original)], cwd=root)
        windows_compiler.run(['cmake', '--build', str(build), '--target', 'install', '--parallel', '2'], cwd=root)
        relocated = root / "relocated prefix"
        original.rename(relocated)
        return relocated

    def configure(self, root, prefix, declared_provider, label):
        import windows_compiler
        config = prefix / "lib/cmake/Foundation/FoundationConfig.cmake"
        text = config.read_text()
        text = '\n'.join(line for line in text.splitlines() if not line.startswith('set(Foundation_CORE_PROVIDER ')) + '\n'
        if declared_provider is not None:
            text += 'set(Foundation_CORE_PROVIDER "' + declared_provider + '")\n'
        config.write_text(text)
        build = root / ("consumer " + label)
        source = Path(artifact.__file__).resolve().parents[1] / "examples/consumer"
        windows_compiler.run(['cmake', '-S', str(source), '-B', str(build), '-G', 'Ninja',
                              '-DCMAKE_BUILD_TYPE=Release', '-DFoundation_DIR=' + str(config.parent)], cwd=root)
        return build

    def execute(self, root, build):
        import windows_compiler
        windows_compiler.run(['cmake', '--build', str(build), '--parallel', '2'], cwd=root)
        executable = build / ('consumer.exe' if os.name == 'nt' else 'consumer')
        return subprocess.run([str(executable)], cwd=root, capture_output=True, text=True).returncode

    def test_relocated_export_executes_actual_provider_and_rejects_mislabelling(self):
        import windows_compiler
        for actual in (0, 1):
            with self.subTest(actual=actual), windows_compiler.workspace(prefix="foundation provider fixture ") as directory:
                root = Path(directory)
                prefix = self.fixture(root, actual)
                for declared, expected in (("cpp", 0), ("rust", 1)):
                    with self.subTest(declared=declared):
                        build = self.configure(root, prefix, declared, declared)
                        self.assertEqual(self.execute(root, build), 0 if actual == expected else 1)

    def test_historical_export_does_not_require_missing_provider_symbol(self):
        import windows_compiler
        with windows_compiler.workspace(prefix="foundation historical provider fixture ") as directory:
            root = Path(directory)
            prefix = self.fixture(root, None)
            build = self.configure(root, prefix, None, "historical")
            self.assertEqual(self.execute(root, build), 0)
            # A modern declaration cannot silently use an unidentified library.
            build = self.configure(root, prefix, "rust", "unidentified")
            with self.assertRaises(subprocess.CalledProcessError):
                self.execute(root, build)

    def test_new_export_rejects_unsupported_or_empty_provider(self):
        import windows_compiler
        with windows_compiler.workspace(prefix="foundation unsupported provider fixture ") as directory:
            root = Path(directory)
            prefix = self.fixture(root, 0)
            for provider in ("automatic", ""):
                with self.subTest(provider=provider), self.assertRaises(subprocess.CalledProcessError):
                    self.configure(root, prefix, provider, "unsupported" + (provider or "empty"))


class ArtifactTests(unittest.TestCase):
    def test_describe_extracts_and_collects_exact_members_in_one_pass(self):
        from unittest.mock import patch
        for kind in ("tar", "zip"):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary); path = root / ("package." + kind)
                members = {"prefix/build-info.txt": b"target=linux-x86_64\n", "prefix/bin/payload": b"payload"}
                if kind == "zip":
                    with zipfile.ZipFile(path, "w") as bundle:
                        for name, data in members.items(): bundle.writestr(name, data)
                else:
                    with tarfile.open(path, "w") as bundle:
                        for name, data in members.items():
                            item = tarfile.TarInfo(name); item.size = len(data)
                            bundle.addfile(item, io.BytesIO(data))
                expected = artifact.describe(path)
                output = root / "unpacked"; output.mkdir()
                contents = {"prefix/build-info.txt": None}
                with patch.object(artifact, "inspect_archive", wraps=artifact.inspect_archive) as inspect:
                    self.assertEqual(artifact.describe(path, output, contents=contents), expected)
                    self.assertEqual(inspect.call_count, 1)
                self.assertEqual(contents, {"prefix/build-info.txt": members["prefix/build-info.txt"]})
                for name, data in members.items(): self.assertEqual((output / name).read_bytes(), data)

    def test_describe_rejects_archive_changed_during_combined_inspection(self):
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "package.zip"
            with zipfile.ZipFile(path, "w") as bundle: bundle.writestr("payload", "original")
            original = artifact.inspect_archive
            def changed(*args, **kwargs):
                value = original(*args, **kwargs)
                with zipfile.ZipFile(path, "w") as bundle: bundle.writestr("payload", "changed")
                return value
            with patch.object(artifact, "inspect_archive", side_effect=changed):
                with self.assertRaisesRegex(ValueError, "changed during inspection"):
                    artifact.describe(path)

    def test_rejects_escaping_paths_and_duplicates(self):
        for name in ("../outside", "/absolute", "C:/drive", "back\\slash"):
            with self.assertRaises(ValueError):
                artifact.member_path(name)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "bad.zip"
            with zipfile.ZipFile(path, "w") as bundle:
                bundle.writestr("file", "first")
                bundle.writestr("./file", "second")
            with self.assertRaises(ValueError):
                artifact.inspect_archive(path)

    def test_rejects_links_and_detects_changed_bytes(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "bad.tar"
            with tarfile.open(path, "w") as bundle:
                link = tarfile.TarInfo("link")
                link.type = tarfile.SYMTYPE
                link.linkname = "../../other"
                bundle.addfile(link)
            with self.assertRaises(ValueError):
                artifact.inspect_archive(path)
            path = Path(directory) / "good.tar"
            with tarfile.open(path, "w") as bundle:
                item = tarfile.TarInfo("prefix/file")
                item.size = 5
                bundle.addfile(item, io.BytesIO(b"hello"))
            self.assertEqual(artifact.describe(path)["files"]["prefix/file"]["size"], 5)

    def test_rejects_privileged_mode_and_modified_archive(self):
        import json
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "package.tar"
            def make(data, mode=0o644):
                with tarfile.open(path, "w") as bundle:
                    item = tarfile.TarInfo("prefix/file")
                    item.size = len(data)
                    item.mode = mode
                    bundle.addfile(item, io.BytesIO(data))
            make(b"first", 0o4755)
            with self.assertRaises(ValueError):
                artifact.describe(path)
            make(b"first")
            manifest = root / "manifest.json"
            manifest.write_text(json.dumps(artifact.describe(path)))
            make(b"other")
            with self.assertRaises(ValueError):
                artifact.verify(path, manifest)


class GraphicsArtifactTests(unittest.TestCase):
    def setUp(self):
        import types,sys
        tools = str(Path(artifact.__file__).parent)
        if tools not in sys.path:
            sys.path.insert(0, tools)
        import windows_graphics
        self.retain_required = windows_graphics.retain_required
        from unittest import mock
        self.mock = mock
        self.types = types
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.events = []
        self.clean = {'PATH': 'runtime-only', 'SystemRoot': 'system'}
        self.developer = {'PATH': 'selected-compiler', 'SystemRoot': 'system'}
        self.archive = self.root / 'retained.7z'
        self.archive.write_bytes(b'operator input')
        self.evidence = self.root / 'evidence'
        self.workspace = self.root / 'workspace'
        self.workspace.mkdir()
        self.prefix = self.workspace / 'prefix'
        self.binary = self.prefix / 'bin' / 'foundation-gui-rev.exe'
        self.binary.parent.mkdir(parents=True)
        self.binary.write_bytes(b'fixture')
        self.disposition = {'retain': False}

    def graphics(self, failure=None, marker='software-foundation gui smoke: ok\n', before_yield=False):
        from contextlib import contextmanager
        state = self.types.SimpleNamespace(environment={'PATH': 'selected-compiler', 'Path': 'duplicate',
                                                        'GALLIUM_DRIVER': 'llvmpipe'},
                                          receipt={'cleanup': 'pending', 'native_probe': {'status': 'passed'}})
        @contextmanager
        def stage(archive, directories, **kwargs):
            self.assertEqual(archive, self.archive)
            self.assertEqual(kwargs['environment']['PATH'], 'selected-compiler')
            self.assertNotEqual(kwargs['probe_directory'].parent, self.evidence)
            self.assertEqual(kwargs['compile_log'].parent, self.evidence)
            self.events.append('probe')
            if before_yield:
                error = ValueError('probe failure')
                error.graphics_receipt = {'cleanup': 'retained-uncertain'}
                raise error
            dll = directories[0] / 'opengl32.dll'
            dll.write_bytes(b'host-only')
            try:
                yield state
            finally:
                self.events.append('cleanup')
                state.receipt['cleanup'] = 'retained-uncertain' if failure == 'uncertain' else 'removed'
                if state.receipt['cleanup'] == 'removed':
                    dll.unlink()
        def run(argv, cwd, log, **kwargs):
            self.assertEqual(kwargs['environment']['PATH'], 'runtime-only')
            self.assertNotIn('Path', kwargs['environment'])
            self.assertEqual(kwargs['environment']['GALLIUM_DRIVER'], 'llvmpipe')
            self.assertEqual(kwargs['timeout'], 60)
            self.assertEqual(kwargs['max_bytes'], 64 * 1024)
            self.assertTrue((Path(argv[0]).parent / 'opengl32.dll').is_file())
            self.events.append('smoke-complete')
            if failure:
                raise ValueError('smoke ' + failure)
            log.write_text(marker)
            return {'returncode': 0, 'log_path': str(log)}
        return self.types.SimpleNamespace(qualified_stage=stage, run_owned=run, retain_required=self.retain_required)

    def invoke(self, graphics):
        import sys
        with self.mock.patch.dict(sys.modules, windows_graphics=graphics), \
                self.mock.patch.dict(artifact.os.environ, self.developer, clear=True):
            return artifact._windows_rev_smoke(self.binary, self.prefix, self.clean, self.archive,
                                              self.evidence, self.workspace, self.disposition, None)

    def test_qualified_smoke_keeps_receipts_external_and_cleans_before_return(self):
        import json
        result = self.invoke(self.graphics())
        self.assertEqual(self.events, ['probe', 'smoke-complete', 'cleanup'])
        self.assertEqual(result['stage']['cleanup'], 'removed')
        self.assertEqual(json.loads((self.evidence / 'graphics.json').read_text()), result)
        self.assertEqual(json.loads((self.evidence / 'probe.json').read_text()), {'status': 'passed'})
        self.assertFalse((self.binary.parent / 'opengl32.dll').exists())
        self.assertFalse(self.disposition['retain'])
        self.assertEqual(self.archive.read_bytes(), b'operator input')

    def test_wrong_marker_fails_after_known_cleanup_and_preserves_failure_receipt(self):
        import json
        with self.assertRaisesRegex(ValueError, 'smoke contract'):
            self.invoke(self.graphics(marker='unrelated\n'))
        self.assertFalse(self.disposition['retain'])
        self.assertEqual(json.loads((self.evidence / 'graphics.json').read_text())['status'], 'failed')
        self.assertEqual(self.events[-1], 'cleanup')

    def test_uncertain_smoke_preserves_staging_and_extraction_workspace(self):
        import json
        with self.assertRaisesRegex(ValueError, 'uncertain'):
            self.invoke(self.graphics(failure='uncertain'))
        report = json.loads((self.evidence / 'graphics.json').read_text())
        self.assertEqual(report['stage']['cleanup'], 'retained-uncertain')
        self.assertTrue(self.disposition['retain'])
        self.assertTrue((self.binary.parent / 'opengl32.dll').is_file())
        self.assertEqual(report['retained_workspace'], str(self.workspace))

    def test_pre_yield_probe_failure_retains_attached_receipt_and_skips_smoke(self):
        import json
        with self.assertRaisesRegex(ValueError, 'probe failure'):
            self.invoke(self.graphics(before_yield=True))
        self.assertTrue(self.disposition['retain'])
        self.assertEqual(self.events, ['probe'])
        self.assertEqual(json.loads((self.evidence / 'graphics.json').read_text())['stage'],
                         {'cleanup': 'retained-uncertain'})

    def test_evidence_cannot_be_inside_extracted_prefix_or_sdk(self):
        import sys
        for evidence, sdk in ((self.prefix / 'evidence', None), (self.root / 'sdk' / 'evidence', self.root / 'sdk')):
            if sdk:
                sdk.mkdir()
            with self.subTest(evidence=evidence), self.mock.patch.dict(sys.modules, windows_graphics=self.graphics()), \
                    self.assertRaisesRegex(ValueError, 'evidence must be outside'):
                artifact._windows_rev_smoke(self.binary, self.prefix, self.clean, self.archive, evidence,
                                            self.workspace, self.disposition, sdk)
            self.assertFalse(evidence.exists())

    def test_workspace_retention_does_not_delete_possible_live_writer_files(self):
        import shutil
        with artifact._workspace() as (directory, disposition):
            self.addCleanup(shutil.rmtree, directory, True)
            (directory / 'fixture').write_text('keep')
            disposition['retain'] = True
        self.assertEqual((directory / 'fixture').read_text(), 'keep')
        with artifact._workspace() as (removed, disposition):
            (removed / 'fixture').write_text('remove')
        self.assertFalse(removed.exists())

    def test_verify_requires_explicit_retained_host_inputs_only_for_windows_rev(self):
        with self.mock.patch.object(artifact, 'os', self.types.SimpleNamespace(name='nt')):
            with self.assertRaisesRegex(ValueError, 'requires retained graphics'):
                artifact.verify(self.archive, self.root / 'manifest', backend='rev')
            with self.assertRaisesRegex(ValueError, 'only to Windows Rev'):
                artifact.verify(self.archive, self.root / 'manifest', backend='core',
                                windows_graphics_archive=self.archive)

    def test_verify_dispatch_preserves_installed_consumer_after_graphics_scope(self):
        import json,sys
        import windows_compiler
        archive = self.root / 'application.zip'
        with zipfile.ZipFile(archive, 'w') as bundle:
            for name in ('bin/foundation-cli.exe', 'bin/foundation-gui-rev.exe',
                         'lib/cmake/Foundation/FoundationConfig.cmake'):
                bundle.writestr('application/' + name, 'fixture')
        manifest = self.root / 'application.json'
        manifest.write_text(json.dumps(artifact.describe(archive)))
        events = []
        def run(argv, **kwargs):
            events.append(argv)
            if '--version' in argv:
                self.assertNotIn('LD_PRELOAD', kwargs['env'])
                return self.types.SimpleNamespace(stdout='software-foundation 0.1.0\n')
            return self.types.SimpleNamespace(stdout='')
        def smoke(executable, prefix, clean, retained, evidence, workspace, disposition, sdk):
            self.assertEqual(retained, self.archive)
            self.assertEqual(evidence, self.evidence)
            self.assertNotIn('selected-compiler', clean['PATH'])
            events.append(['qualified-smoke'])
            return {'stage': {'cleanup': 'removed'}}
        fake_os = self.types.SimpleNamespace(name='nt', pathsep=';',
            environ={'SystemRoot': str(self.root / 'Windows'), 'PATH': 'selected-compiler', 'LD_PRELOAD': 'remove'})
        with self.mock.patch.object(artifact, 'os', fake_os), \
                self.mock.patch.dict(sys.modules, verify_pe=self.types.SimpleNamespace(audit=self.mock.Mock())), \
                self.mock.patch.object(artifact.subprocess, 'run', side_effect=run), \
                self.mock.patch.object(windows_compiler, 'run', side_effect=run) as build, \
                self.mock.patch.object(artifact, '_windows_rev_smoke', side_effect=smoke):
            result = artifact.verify(archive, manifest, backend='rev', windows_graphics_archive=self.archive,
                                     windows_graphics_evidence=self.evidence)
        self.assertEqual(build.call_count, 2)
        self.assertTrue(all(call.kwargs['env']['PATH'] == 'selected-compiler' for call in build.call_args_list))
        index = events.index(['qualified-smoke'])
        self.assertEqual(len(events[index+1:]), 3)
        self.assertEqual(events[index+1][0], 'cmake')
        self.assertEqual(result, {'windows_graphics': {'stage': {'cleanup': 'removed'}}})

    def test_uncertain_cmake_consumer_preserves_extracted_workspace(self):
        import json, sys, shutil
        import process_tree, windows_compiler
        archive = self.root / 'consumer.zip'
        with zipfile.ZipFile(archive, 'w') as bundle:
            for name in ('bin/foundation-cli.exe', 'lib/cmake/Foundation/FoundationConfig.cmake'):
                bundle.writestr('application/' + name, 'fixture')
        manifest = self.root / 'consumer.json'
        manifest.write_text(json.dumps(artifact.describe(archive)))
        workspace = self.root / 'uncertain-consumer'; workspace.mkdir()
        self.addCleanup(shutil.rmtree, workspace)
        def command(argv, **kwargs):
            return self.types.SimpleNamespace(stdout='software-foundation 0.1.0\n')
        def failed_build(*args, **kwargs):
            try:
                raise process_tree.ProcessTreeError('compiler writer remains uncertain')
            except process_tree.ProcessTreeError as error:
                raise RuntimeError('consumer configure failed') from error
        fake_os = self.types.SimpleNamespace(name='nt', pathsep=';',
            environ={'SystemRoot': str(self.root / 'Windows'), 'PATH': 'selected-compiler'})
        with self.mock.patch.object(artifact, 'os', fake_os), \
             self.mock.patch.dict(sys.modules, verify_pe=self.types.SimpleNamespace(audit=self.mock.Mock())), \
             self.mock.patch.object(artifact.tempfile, 'mkdtemp', return_value=str(workspace)), \
             self.mock.patch.object(artifact.subprocess, 'run', side_effect=command), \
             self.mock.patch.object(windows_compiler, 'run', side_effect=failed_build) as build, \
             self.mock.patch.object(artifact.shutil, 'rmtree') as remove:
            with self.assertRaisesRegex(RuntimeError, 'consumer configure'):
                artifact.verify(archive, manifest)
            build.assert_called_once()
            self.assertIn('-S', build.call_args.args[0])
            remove.assert_not_called()
        self.assertTrue((workspace / 'relocated prefix').is_dir())

    def test_application_archives_reject_host_dll_names_in_every_directory(self):
        for name in ('prefix/bin/OpenGL32.DLL', 'prefix/lib/runtime/libgallium_wgl.dll'):
            for extension in ('zip', 'tar'):
                with self.subTest(name=name, extension=extension):
                    archive = self.root / ('bad.' + extension)
                    if extension == 'zip':
                        with zipfile.ZipFile(archive, 'w') as bundle:
                            bundle.writestr(name, b'host input')
                    else:
                        with tarfile.open(archive, 'w') as bundle:
                            item = tarfile.TarInfo(name);item.size = 10
                            bundle.addfile(item, io.BytesIO(b'host input'))
                    with self.assertRaisesRegex(ValueError, 'host graphics DLLs'):
                        artifact.describe(archive)

    def test_supervisor_error_preserves_workspace_even_if_cleanup_receipt_is_inconsistent(self):
        import process_tree
        graphics = self.graphics()
        graphics.run_owned = self.mock.Mock(side_effect=process_tree.ProcessTreeError('unconfirmed writer state'))
        with self.assertRaisesRegex(process_tree.ProcessTreeError, 'unconfirmed'):
            self.invoke(graphics)
        self.assertTrue(self.disposition['retain'])

    def test_actual_owned_process_finishes_joined_child_before_staging_cleanup(self):
        from contextlib import contextmanager
        import sys,os
        sys.path.insert(0, str(Path(artifact.__file__).parent))
        import windows_graphics as actual
        self.binary.write_text("import subprocess,sys\nsubprocess.run([sys.executable,'-B','-c','pass'],check=True)\nprint('software-foundation gui smoke: ok')\n")
        state = self.types.SimpleNamespace(environment=dict(os.environ, GALLIUM_DRIVER='llvmpipe'),
                                          receipt={'cleanup':'pending','native_probe':{'status':'fixture-only'}})
        self.clean['PATH'] = os.environ.get('PATH', '')
        @contextmanager
        def stage(*args, **kwargs):
            self.events.append('probe-fixture')
            try:
                yield state
            finally:
                self.events.append('cleanup')
                state.receipt['cleanup'] = 'removed'
        def run(argv, cwd, log, **kwargs):
            self.assertEqual(kwargs['environment']['GALLIUM_DRIVER'], 'llvmpipe')
            result = actual.run_owned([sys.executable, '-B', argv[0]], cwd, log, **kwargs)
            self.events.append('all-writers-complete')
            return result
        result = self.invoke(self.types.SimpleNamespace(qualified_stage=stage, run_owned=run, retain_required=self.retain_required))
        self.assertEqual(result['status'], 'passed')
        self.assertEqual(self.events, ['probe-fixture','all-writers-complete','cleanup'])

    def test_wrapped_supervisor_error_preserves_workspace_through_cause(self):
        import process_tree
        graphics = self.graphics()
        def fail(*args, **kwargs):
            try:
                raise process_tree.ProcessTreeError('unconfirmed descendant')
            except process_tree.ProcessTreeError as cause:
                raise ValueError('qualification wrapper failed') from cause
        graphics.run_owned = fail
        with self.assertRaisesRegex(ValueError, 'wrapper failed'):
            self.invoke(graphics)
        self.assertTrue(self.disposition['retain'])
