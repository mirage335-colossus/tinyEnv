"""Consumer checks for pinned, same-source offline browser installation."""
import hashlib
import os
from pathlib import Path
import shutil
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
sys.path.insert(0, str(ROOT / 'tests'))
import import_wasm
import test_package_wasm as fixtures


class ImportWasmTests(unittest.TestCase):
    setUp = fixtures.PackageWasmTests.setUp
    make = fixtures.PackageWasmTests.make
    make_legacy = fixtures.PackageWasmTests.make_legacy
    rewrite_checksums = fixtures.PackageWasmTests.rewrite_checksums
    def fixture(self):
        source = self.root / 'source'
        source.mkdir()
        (source / 'application.cpp').write_text('int main() { return 0; }\n')
        import_wasm_package = __import__('package_wasm')
        import_wasm_package.package(self.assets, self.output, [self.notice], source_root=source)
        identity = hashlib.sha256((self.output / 'web-manifest.json').read_bytes()).hexdigest()
        return source, identity

    def test_explicit_source_bound_schema2_and_schema3_import_compatibility(self):
        source, identity = self.fixture()
        self.assertEqual(import_wasm.verify_input(self.output, identity, source)['schema'], 3)
        self.make_legacy(schema=2, source_root=source)
        identity = hashlib.sha256((self.output / 'web-manifest.json').read_bytes()).hexdigest()
        self.assertEqual(import_wasm.verify_input(self.output, identity, source)['schema'], 2)
        self.make_legacy(schema=1)
        identity = hashlib.sha256((self.output / 'web-manifest.json').read_bytes()).hexdigest()
        with self.assertRaisesRegex(ValueError, 'source identities differ'):
            import_wasm.verify_input(self.output, identity, source)

    @unittest.skipIf(os.name == "nt", "POSIX desktop-opener fixture; Windows launcher uses native file association")
    def test_pinned_same_source_staging_and_relocated_exact_document_launch(self):
        source, identity = self.fixture()
        stage = self.root / 'stage'
        import_wasm.stage(self.output, identity, source, stage)
        import_wasm.stage(self.output, identity, source, stage)
        installed = self.root / 'relocated prefix with spaces' / 'share/software-foundation/wasm'
        shutil.copytree(stage / 'package', installed)
        shutil.copy2(stage / 'open-offline.sh', installed.parent / 'open-offline.sh')
        fake = self.root / 'fake-browser'; fake.mkdir()
        receipt = self.root / 'opened-path'
        browser = fake / 'xdg-open'
        browser.write_text('#!/bin/sh\nprintf "%s" "$1" > "$FOUNDATION_BROWSER_RECEIPT"\n')
        browser.chmod(0o755)
        subprocess.run(['sh', str(installed.parent / 'open-offline.sh')], check=True,
                       env=dict(os.environ, PATH=str(fake) + os.pathsep + os.environ['PATH'], FOUNDATION_BROWSER_RECEIPT=str(receipt)))
        self.assertEqual(receipt.read_text(), str(installed / import_wasm.HTML_NAME))
        self.assertEqual((installed / import_wasm.HTML_NAME).read_bytes(), (self.output / import_wasm.HTML_NAME).read_bytes())

    def test_cmake_selected_build_and_direct_install_revalidate_identity(self):
        source = self.root / 'source'; source.mkdir()
        shutil.copytree(ROOT / 'tools', source / 'tools', ignore=shutil.ignore_patterns('__pycache__'))
        (source / 'cmake').mkdir()
        for name in ('ImportWasm.cmake', 'InstallWasm.cmake.in'):
            shutil.copy2(ROOT / 'cmake' / name, source / 'cmake' / name)
        (source / 'application.cpp').write_text('int example() { return 7; }\n')
        (source / 'CMakeLists.txt').write_text(
            'cmake_minimum_required(VERSION 3.24)\nproject(ImportFixture LANGUAGES CXX)\n'
            'include(GNUInstallDirs)\nfind_package(Python3 REQUIRED COMPONENTS Interpreter)\n'
            'add_library(foundation_core STATIC application.cpp)\ninclude(cmake/ImportWasm.cmake)\n')
        __import__('package_wasm').package(self.assets, self.output, [self.notice], source_root=source)
        identity = hashlib.sha256((self.output / 'web-manifest.json').read_bytes()).hexdigest()
        build = source / 'build'
        def run(*args):
            return subprocess.run(list(args), capture_output=True, text=True, timeout=60)
        # Match the supported single-config preset, rather than an ambient host generator.
        configured = run('cmake', '-S', str(source), '-B', str(build), '-G', 'Ninja',
                         '-DCMAKE_BUILD_TYPE=Release',
                         '-DFOUNDATION_WASM_PACKAGE=' + str(self.output), '-DFOUNDATION_WASM_PACKAGE_SHA256=' + identity)
        self.assertEqual(configured.returncode, 0, configured.stdout + configured.stderr)
        built = run('cmake', '--build', str(build), '--target', 'foundation_core', '--parallel', '2')
        self.assertEqual(built.returncode, 0, built.stdout + built.stderr)
        installed = run('cmake', '--install', str(build), '--prefix', str(self.root/'installed'))
        self.assertEqual(installed.returncode, 0, installed.stdout + installed.stderr)
        self.assertEqual((self.root/'installed/share/software-foundation/wasm'/import_wasm.HTML_NAME).read_bytes(),
                         (self.output/import_wasm.HTML_NAME).read_bytes())
        (source/'application.cpp').write_text('int example() { return 8; }\n')
        for command in (('cmake', '--build', str(build), '--target', 'foundation_core'),
                        ('cmake', '--install', str(build), '--prefix', str(self.root/'rejected'))):
            rejected = run(*command)
            self.assertNotEqual(rejected.returncode, 0)
            self.assertIn('source identities differ', rejected.stdout + rejected.stderr)
        self.assertFalse((self.root/'rejected').exists())

    @unittest.skipIf(os.name == "nt", "Unix compiler Win32 declaration fixture; actual Windows GUI link covered by native build")
    def test_windows_gui_entry_preserves_arguments_and_console_target_kind(self):
        # Compile the actual entry shim against a tiny Win32/CRT declaration
        # fixture; native Windows linking is separately qualified on that host.
        include = self.root/'windows-headers'; include.mkdir()
        (include/'windows.h').write_text('#define WINAPI\nusing HINSTANCE = void*; using LPSTR = char*;\nextern int __argc; extern char** __argv;\n')
        (include/'SDL.h').write_text('void SDL_SetMainReady();\n')
        driver = self.root/'driver.cpp'
        driver.write_text('#include <windows.h>\nint __argc=2; char arg0[]="example"; char arg1[]="value"; char* args[]={arg0,arg1,nullptr}; char** __argv=args;\n'
                          'bool ready=false; void SDL_SetMainReady() { ready=true; }\n'
                          'int foundation_gui_main(int argc,char** argv) { return ready && argc==2 && argv==args ? 19 : 1; }\n'
                          'int WinMain(HINSTANCE,HINSTANCE,LPSTR,int); int main() { return WinMain(nullptr,nullptr,nullptr,0)==19 ? 0 : 1; }\n')
        binary = self.root/'entry-check'
        result = subprocess.run(['c++','-D_WIN32','-DFOUNDATION_GUI_SDL_ENTRY','-I'+str(include),str(ROOT/'gui/hosts/windows_gui_entry.cpp'),str(driver),'-o',str(binary)],capture_output=True,text=True,timeout=30)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        subprocess.run([str(binary)],check=True,timeout=10)
        helper = (ROOT/'gui/CMakeLists.txt').read_text().split('function(foundation_gui_executable ',1)[1].split('endfunction()',1)[0]
        fixture = self.root/'cmake-windows'; fixture.mkdir()
        (fixture/'host.cpp').write_text('int main() { return 0; }\n')
        (fixture/'hosts').mkdir();shutil.copy2(ROOT/'gui/hosts/windows_gui_entry.cpp',fixture/'hosts/windows_gui_entry.cpp')
        (fixture/'CMakeLists.txt').write_text('cmake_minimum_required(VERSION 3.24)\nproject(WindowsProperties LANGUAGES CXX)\n'
            'set(WIN32 TRUE)\nset(MSVC TRUE)\nfunction(foundation_options target)\nendfunction()\n'
            'add_library(foundation_gui_application INTERFACE)\nadd_custom_target(foundation-gui-hosts)\n'
            'function(foundation_gui_executable '+helper+'endfunction()\n'
            'foreach(kind fltk rev sdl terminal framebuffer web)\n'
            'foundation_gui_executable(foundation-gui-${kind} host.cpp)\n'
            'get_target_property(is_gui foundation-gui-${kind} WIN32_EXECUTABLE)\n'
            'get_target_property(options foundation-gui-${kind} LINK_OPTIONS)\n'
            'if(kind MATCHES "^(fltk|rev|sdl)$")\n'
            'if(NOT is_gui OR NOT "${options}" MATCHES "MANIFESTINPUT")\nmessage(FATAL_ERROR "Missing GUI launch integration")\nendif()\n'
            'elseif(is_gui)\nmessage(FATAL_ERROR "CLI host changed subsystem")\nendif()\nendforeach()\n')
        configured = subprocess.run(['cmake','-S',str(fixture),'-B',str(self.root/'cmake-windows-build')],capture_output=True,text=True,timeout=30)
        self.assertEqual(configured.returncode,0,configured.stdout+configured.stderr)

    def test_wrong_pin_changed_source_legacy_group_and_tampered_stage_fail(self):
        source, identity = self.fixture()
        with self.assertRaisesRegex(ValueError, 'manifest identity'):
            import_wasm.verify_input(self.output, 'a' * 64, source)
        (source / 'application.cpp').write_text('changed source')
        with self.assertRaisesRegex(ValueError, 'source identities differ'):
            import_wasm.verify_input(self.output, identity, source)
        (source / 'application.cpp').write_text('int main() { return 0; }\n')
        stage = self.root / 'stage'
        import_wasm.stage(self.output, identity, source, stage)
        (stage / 'open-offline.sh').write_text('wrong launcher')
        with self.assertRaisesRegex(ValueError, 'staging differs'):
            import_wasm.stage(self.output, identity, source, stage)
        self.make()
        identity = hashlib.sha256((self.output / 'web-manifest.json').read_bytes()).hexdigest()
        with self.assertRaisesRegex(ValueError, 'source identities differ'):
            import_wasm.verify_input(self.output, identity, source)


if __name__ == '__main__':
    unittest.main()
