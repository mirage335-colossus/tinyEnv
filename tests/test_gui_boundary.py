"""Source-level boundary tripwires supplement executable GUI conformance."""

from pathlib import Path
import importlib.util
import ctypes
import json
import os
import re
import sys
import subprocess
import unittest
import tempfile
import time
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]


_spec = importlib.util.spec_from_file_location("gui_guard", ROOT / "gui/check_boundary.py")
_guard = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_guard)
shared_violations = _guard.shared_violations


class GuiBoundaryTests(unittest.TestCase):
    def test_shared_application_is_backend_independent(self):
        for path in _guard.sources(ROOT / "gui/shared"):
            self.assertEqual([], shared_violations(path.read_text()), str(path))

    def test_tripwire_rejects_concrete_backends(self):
        for source in ('#include <FL/Fl.H>', '#include <gui/framebuffer.hpp>',
                       'import Rev.Widget;', 'gui::WebAdapter adapter;'):
            self.assertTrue(shared_violations(source), source)
        self.assertFalse(shared_violations('#include <gui/contract.hpp>\ngui::Adapter& adapter;'))

    def test_rust_tripwire_rejects_backend_imports_calls_and_linkage(self):
        for source in ('use sdl2::video::Window;', 'use fltk::{app, window};',
                       'extern crate rev as renderer;', 'use gui::framebuffer::Adapter;',
                       'fn draw() { sdl2::event::poll(); }',
                       'extern "C" { fn SDL_PollEvent(event: *mut u8) -> u32; }',
                       'extern "C" { fn foundation_gui_render(); }',
                       'extern "C" { fn rev_create_window(); }',
                       '#[link(name = "SDL2")] extern "C" {}',
                       '#[link(name = "SDL2main")] extern "C" {}',
                       '#[link(name = r#"fltk"#)] extern "C" {}',
                       '#[link(name = "\\x53DL2")] extern "C" {}',
                       '#[link_name = "SDL_PollEvent"] extern "C" { fn poll(); }',
                       '#[link(name = concat!("SDL", "2"))] extern "C" {}',
                       '#[path = "../../gui/host/renderer.rs"] mod renderer;'):
            self.assertTrue(_guard.rust_violations(source), source)

    def test_rust_tripwire_permits_core_and_private_callback_without_data_false_positives(self):
        source = '''use core::slice;
use std::{ffi::c_void, ptr};
extern "C" { fn foundation_rust_panic() -> !; }
#[link(name = "c")] extern "C" { fn memcpy(); }
#[link_name = "foundation_rust_panic"] extern "C" { fn fault() -> !; }
fn borrow<'a>(value: &'a [u8]) -> &'a [u8] { value }
const TEXT: &str = r###"use sdl2::video::Window; #[link(name="SDL2")]"###;
const CHAR: char = 'x';
// extern "C" { fn SDL_PollEvent(); }
/* outer /* use fltk::app; */ #[link(name="Rev")] */
'''
        self.assertEqual([], _guard.rust_violations(source))
        for path in _guard.sources(ROOT / 'rust'):
            if path.suffix == '.rs':
                self.assertEqual([], _guard.rust_violations(path.read_text()), str(path))

    def test_rust_application_modules_are_checked_by_real_entry_point(self):
        with tempfile.TemporaryDirectory(prefix='Rust GUI boundary ') as temporary:
            project = Path(temporary).resolve(); root = project / 'gui'; root.mkdir()
            guard = root / 'check_boundary.py'
            guard.write_bytes((ROOT / 'gui/check_boundary.py').read_bytes())
            path = project / 'rust/component/src/nested/codec.rs'
            path.parent.mkdir(parents=True)
            path.write_text('extern "C" { fn SDL_PollEvent(); }\n')
            result = subprocess.run([sys.executable, '-B', str(guard)],
                capture_output=True, text=True, timeout=15)
            self.assertNotEqual(0, result.returncode)
            self.assertIn(str(path), result.stderr)
            path.write_text('use core::slice;\nextern "C" { fn foundation_rust_panic() -> !; }\n')
            result = subprocess.run([sys.executable, '-B', str(guard), '--dependencies'],
                capture_output=True, text=True, timeout=15)
            self.assertEqual(0, result.returncode, result.stderr)
            self.assertIn(str(path), result.stdout)

    def test_rust_hosts_keep_backend_ownership_and_reject_application_dependencies(self):
        with tempfile.TemporaryDirectory(prefix='Rust host boundary ') as temporary:
            root = Path(temporary) / 'gui'
            (root / 'host').mkdir(parents=True); (root / 'shared').mkdir()
            (root / 'shared/view.rs').write_text('const ID: &str = "records.add";\n')
            host = root / 'host/adapter.rs'
            host.write_text('extern "C" { fn SDL_PollEvent(); }\n')
            self.assertEqual([], _guard.tree_violations(root))
            for source in ('const ID: &str = "records.add";\n', 'use foundation::Store;\n',
                           'use foundation::{Record, Store};\n', 'use foundation::ui::Application;\n'):
                host.write_text(source)
                self.assertTrue(_guard.tree_violations(root), source)

    def test_incremental_build_rechecks_new_and_modified_rust_module(self):
        cmake = (ROOT / 'gui/CMakeLists.txt').read_text()
        block = 'file(GLOB_RECURSE' + cmake.split('file(GLOB_RECURSE', 1)[1].split(
            'add_library(foundation_gui_application STATIC', 1)[0]
        with tempfile.TemporaryDirectory(prefix='incremental Rust boundary ') as temporary:
            project = Path(temporary) / 'source'; root = project / 'gui'; root.mkdir(parents=True)
            (root / 'check_boundary.py').write_bytes((ROOT / 'gui/check_boundary.py').read_bytes())
            (root / 'CMakeLists.txt').write_text(
                'cmake_minimum_required(VERSION 3.24)\nproject(BoundaryGuard LANGUAGES NONE)\n' +
                'find_package(Python3 REQUIRED COMPONENTS Interpreter)\n' + block)
            build = Path(temporary) / 'build'
            subprocess.run(['cmake', '-G', 'Ninja', '-S', str(root), '-B', str(build)],
                check=True, capture_output=True, text=True, timeout=30)
            def check():
                return subprocess.run(['cmake', '--build', str(build), '--target', 'foundation_gui_contract'],
                    capture_output=True, text=True, timeout=30)
            result = check(); self.assertEqual(0, result.returncode, result.stdout + result.stderr)
            path = project / 'rust/component/src/nested/codec.rs'
            path.parent.mkdir(parents=True)
            for contents, accepted in [('use sdl2::event;\n', False), ('use core::slice;\n', True),
                                       ('#[link(name="SDL2")] extern "C" {}\n', False)]:
                path.write_text(contents)
                tick = max(time.time_ns(), path.stat().st_mtime_ns + 10_000_000,
                           (build / 'boundary-checked').stat().st_mtime_ns + 10_000_000)
                os.utime(path, ns=(tick, tick))
                result = check()
                self.assertEqual(accepted, result.returncode == 0, result.stdout + result.stderr)
                if not accepted:
                    self.assertIn('codec.rs', result.stdout + result.stderr)

    def test_composition_hosts_do_not_name_feature_ids(self):
        for path in _guard.sources(ROOT / "gui/hosts"):
            self.assertNotIn('"entries.', path.read_text(), str(path))

    def test_nested_shared_and_host_sources_are_checked_by_real_entry_point(self):
        with tempfile.TemporaryDirectory(prefix="nested GUI boundary ") as directory:
            root = Path(directory).resolve()
            guard = root / "check_boundary.py"
            guard.write_bytes((ROOT / "gui/check_boundary.py").read_bytes())
            paths = [root / "shared/feature/detail/control.hh",
                     root / "host/native/detail/dispatch.ipp",
                     root / "hosts/browser/detail/transport.cpp"]
            for path in paths: path.parent.mkdir(parents=True, exist_ok=True)
            paths[0].write_text('#include <FL/Fl.H>\n')
            for path in paths[1:]: path.write_text('const char* key = "entries.editor";\n')
            result = subprocess.run([sys.executable, "-B", str(guard)],
                capture_output=True, text=True, timeout=15)
            self.assertNotEqual(0, result.returncode)
            for path in paths: self.assertIn(str(path), result.stderr)
            paths[0].write_text('#include <gui/contract.hpp>\n')
            for path in paths[1:]: path.write_text('void generic_dispatch();\n')
            result = subprocess.run([sys.executable, "-B", str(guard)],
                capture_output=True, text=True, timeout=15)
            self.assertEqual(0, result.returncode, result.stderr)

    def test_incremental_build_rechecks_added_and_modified_nested_header(self):
        cmake = (ROOT / "gui/CMakeLists.txt").read_text()
        block = "file(GLOB_RECURSE" + cmake.split("file(GLOB_RECURSE", 1)[1].split(
            "add_library(foundation_gui_application STATIC", 1)[0]
        with tempfile.TemporaryDirectory(prefix="incremental GUI boundary ") as directory:
            root = Path(directory); source = root / "source"; source.mkdir()
            (source / "check_boundary.py").write_bytes((ROOT / "gui/check_boundary.py").read_bytes())
            (source / "CMakeLists.txt").write_text(
                'cmake_minimum_required(VERSION 3.24)\nproject(BoundaryGuard LANGUAGES NONE)\n' +
                'find_package(Python3 REQUIRED COMPONENTS Interpreter)\n' + block)
            build = root / "build"
            subprocess.run(["cmake", "-G", "Ninja", "-S", str(source), "-B", str(build)],
                check=True, capture_output=True, text=True, timeout=30)
            def check():
                return subprocess.run(["cmake", "--build", str(build), "--target", "foundation_gui_contract"],
                    capture_output=True, text=True, timeout=30)
            result = check(); self.assertEqual(0, result.returncode, result.stdout + result.stderr)
            path = source / "shared/new/detail/control.hh"; path.parent.mkdir(parents=True)
            def change(content):
                path.write_text(content)
                # Exercise dependency invalidation, independently of filesystem
                # timestamp granularity when edits follow a build immediately.
                tick = max(time.time_ns(), path.stat().st_mtime_ns + 10_000_000,
                           (build / "boundary-checked").stat().st_mtime_ns + 10_000_000)
                os.utime(path, ns=(tick, tick))
            change('#include <FL/Fl.H>\n')
            result = check(); self.assertNotEqual(0, result.returncode, result.stdout + result.stderr)
            self.assertIn("control.hh", result.stdout + result.stderr)
            change('#include <gui/contract.hpp>\n')
            result = check(); self.assertEqual(0, result.returncode, result.stdout + result.stderr)
            change('#include <gui/framebuffer.hpp>\n')
            result = check(); self.assertNotEqual(0, result.returncode, result.stdout + result.stderr)
            self.assertIn("control.hh", result.stdout + result.stderr)
            helper = source / 'helpers/bridge.hpp'; helper.parent.mkdir()
            helper.write_text('void generic_helper();\n')
            change('#include "../../../helpers/bridge.hpp"\n')
            result = check(); self.assertEqual(0,result.returncode,result.stdout+result.stderr)
            nested = helper.parent / 'nested.hpp'; nested.write_text('void another_helper();\n')
            helper.write_text('#include "nested.hpp"\n')
            tick = max(time.time_ns(), helper.stat().st_mtime_ns + 10_000_000,
                       (build / 'boundary-checked').stat().st_mtime_ns + 10_000_000)
            os.utime(helper,ns=(tick,tick))
            result = check(); self.assertEqual(0,result.returncode,result.stdout+result.stderr)
            nested.write_text('#include <FL/Fl.H>\n')
            tick = max(time.time_ns(), nested.stat().st_mtime_ns + 10_000_000,
                       (build / 'boundary-checked').stat().st_mtime_ns + 10_000_000)
            os.utime(nested,ns=(tick,tick))
            result = check(); self.assertNotEqual(0,result.returncode,result.stdout+result.stderr)
            self.assertIn('nested.hpp',result.stdout+result.stderr)

    def test_direct_group_configure_dependencies_have_no_path_aliases(self):
        inputs = (ROOT/'cmake/GuiInputs.cmake').read_text()
        selection = inputs.split('macro(foundation_gui_inputs)', 1)[1].split('if(NOT IS_DIRECTORY', 1)[0]
        # The fixture relocates the reviewed helper's explicit GUI module root.
        selection = 'set(foundation_gui_module_root "${CMAKE_CURRENT_SOURCE_DIR}")\n' + selection
        with tempfile.TemporaryDirectory(prefix='direct retained inputs ') as temporary:
            source=Path(temporary)/'source';(source/'gui').mkdir(parents=True)
            group=source/'third_party/gui-inputs';group.mkdir(parents=True)
            tool=source/'tools/dependency_archive.py';tool.parent.mkdir();tool.write_text('# fixture\n')
            for name in ('manifest.json','SHA256SUMS','gui-inputs.tar.gz'):
                (group/name).write_text('fixture\n')
            # Isolate CMake dependency spelling; archive validity is covered by
            # the real source-group suite and combined direct native build.
            (source/'gui/source_group.py').write_text('print('+repr(json.dumps({'source':str(source/'upstream')}))+')\n')
            (source/'gui/CMakeLists.txt').write_text(selection)
            (source/'CMakeLists.txt').write_text(
                'cmake_minimum_required(VERSION 3.24)\nproject(DirectInputs NONE)\n'
                'find_package(Python3 REQUIRED COMPONENTS Interpreter)\n'
                'function(foundation_register_build_directory)\nendfunction()\n'
                'set_property(DIRECTORY APPEND PROPERTY CMAKE_CONFIGURE_DEPENDS\n'
                ' "${CMAKE_SOURCE_DIR}/tools/dependency_archive.py"\n'
                ' "${CMAKE_SOURCE_DIR}/third_party/gui-inputs/manifest.json"\n'
                ' "${CMAKE_SOURCE_DIR}/third_party/gui-inputs/SHA256SUMS"\n'
                ' "${CMAKE_SOURCE_DIR}/third_party/gui-inputs/gui-inputs.tar.gz")\n'
                'add_subdirectory(gui)\n')
            for label,arguments in [('default',[]),('explicit-alias',[
                    '-DFOUNDATION_GUI_INPUT_GROUP='+str(source/'gui/../third_party/gui-inputs')])]:
                build=Path(temporary)/label
                for command in (['cmake','-G','Ninja','-S',str(source),'-B',str(build),*arguments],
                                ['cmake','--build',str(build)]):
                    result=subprocess.run(command,capture_output=True,text=True,timeout=30)
                    self.assertEqual(0,result.returncode,result.stdout+result.stderr)

    def test_literal_include_closure_and_aliases_cannot_hide_native_dependencies(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / 'gui'
            for directory in ('shared', 'helpers', 'host', 'hosts'):
                (root / directory).mkdir(parents=True)
            (root / 'shared/app.cpp').write_text('#include "../helpers/bridge.hpp"\n')
            bridge = root / 'helpers/bridge.hpp'
            for contents in ('#include<gui/detail/framebuffer.hpp>\n',
                             '#include "../host/adapter.hpp"\n',
                             'using Native = SDL_Window;\n', '#define BACKEND <FL/Fl.H>\n#include BACKEND\n'):
                bridge.write_text(contents)
                (root / 'host/adapter.hpp').write_text('struct NativeAdapter {};\n')
                failures = _guard.tree_violations(root)
                self.assertTrue(failures, contents)
                self.assertTrue(any('bridge.hpp' in failure for failure in failures))
            bridge.write_text('#include <gui/contract.hpp>\n// SDL_Window is forbidden here.\n')
            self.assertEqual([], _guard.tree_violations(root))
            dependencies = _guard.analyze(root)[1]
            self.assertIn(bridge.resolve(), dependencies)
            bridge.write_text('#include "cycle.hpp"\n')
            (root / 'helpers/cycle.hpp').write_text('#include "bridge.hpp"\n')
            self.assertEqual([], _guard.tree_violations(root))

    def test_include_resolution_preserves_angle_and_quoted_search_order(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / 'gui'
            for directory in ('shared', 'helpers'):
                (root / directory).mkdir(parents=True)
            (root / 'shared/app.cpp').write_text('#include "../helpers/bridge.hpp"\n')
            bridge = root / 'helpers/bridge.hpp'
            (root / 'common.hpp').write_text('void public_helper();\n')
            (root / 'helpers/common.hpp').write_text('using Hidden = SDL_Window;\n')
            bridge.write_text('#include <common.hpp>\n')
            self.assertEqual([], _guard.tree_violations(root))
            bridge.write_text('#include "common.hpp"\n')
            self.assertTrue(_guard.tree_violations(root))
            (root / 'common.hpp').write_text('using Hidden = SDL_Window;\n')
            (root / 'helpers/common.hpp').write_text('void sibling_helper();\n')
            bridge.write_text('#include <common.hpp>\n')
            self.assertTrue(_guard.tree_violations(root))
            self.assertTrue(shared_violations('#include_next <hidden.hpp>\n'))

    def test_host_domain_guards_follow_helpers_and_allow_only_composition_type(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / 'gui'
            for directory in ('shared', 'helpers', 'host', 'hosts'):
                (root / directory).mkdir(parents=True)
            (root / 'shared/task.hpp').write_text('class TextTask {};\n')
            (root / 'shared/application.hpp').write_text('#include "task.hpp"\nclass Application {};\n')
            (root / 'shared/view_definition.hpp').write_text('const char* id="records.add";\n')
            main = root / 'hosts/example_main.cpp'
            main.write_text('#include "shared/application.hpp"\nfoundation::ui::Application* app;\n')
            (root / 'host/task.hpp').write_text('void generic_task();\n')
            (root / 'host/service.hpp').write_text('#include "task.hpp"\n')
            self.assertEqual([], _guard.tree_violations(root))
            for source in ('const char* id="records.add";\n', 'foundation::Store entries;\n',
                           'foundation::ui::TextTask task;\n', 'foundation::ui::Application* concrete;\n',
                           '#include "shared/view_definition.hpp"\n'):
                (root / 'host/service.hpp').write_text(source)
                self.assertTrue(_guard.tree_violations(root), source)
            (root / 'host/service.hpp').write_text('#include "../helpers/bridge.hpp"\n')
            (root / 'helpers/bridge.hpp').write_text('#include "../shared/application.hpp"\n')
            self.assertTrue(any('bridge.hpp' in failure for failure in _guard.tree_violations(root)))

    def test_header_mirror_uses_final_patch_bytes_and_preserves_incremental_outputs(self):
        inputs = (ROOT / 'cmake/GuiInputs.cmake').read_text()
        patcher = 'function(foundation_gui_patch' + inputs.split('function(foundation_gui_patch',1)[1].split('endfunction()',1)[0] + 'endfunction()\n'
        mirror = inputs.split('macro(foundation_gui_headers)', 1)[1].split('endmacro()', 1)[0]
        with tempfile.TemporaryDirectory(prefix='patched header mirror ') as temporary:
            root = Path(temporary); source = root / 'source'; source.mkdir()
            upstream = source / 'upstream/include/gui'; upstream.mkdir(parents=True)
            patches = source / 'patches'; patches.mkdir()
            (patches / 'apply.py').write_bytes((ROOT / 'gui/patches/apply.py').read_bytes())
            names = [('contract','touch-contract'),('memory_adapter','touch-memory'),
                     ('interaction','touch-interaction'),('runtime','file-services'),
                     ('terminal','terminal-caret'),('web','web-tick')]
            for name, patch in names:
                old = 'inline constexpr int ' + name + '_value=1;\n'
                new = old.replace('=1;', '=2;')
                (upstream / (name+'.hpp')).write_text(old)
                (patches / (patch+'.patch')).write_text('--- old\n+++ new\n@@ -1 +1 @@\n-'+old+'+'+new)
            (upstream / 'removed.hpp').write_text('inline constexpr int obsolete=1;\n')
            (upstream / 'other.hpp').write_text(''.join('#include "'+name+'.hpp"\n' for name,_ in names))
            (source / 'main.cpp').write_text('#include <gui/other.hpp>\n' +
                ''.join('static_assert('+name+'_value==2);\n' for name,_ in names)+'int main(){return 0;}\n')
            project = 'cmake_minimum_required(VERSION 3.24)\nproject(HeaderMirror LANGUAGES CXX)\nfind_package(Python3 REQUIRED COMPONENTS Interpreter)\n'
            project += 'set(FOUNDATION_GUI_SOURCE "${CMAKE_CURRENT_SOURCE_DIR}/upstream")\n'
            project += 'set(foundation_gui_module_root "${CMAKE_CURRENT_SOURCE_DIR}")\n'
            project += 'file(GLOB verified_files "${FOUNDATION_GUI_SOURCE}/include/gui/*")\n'
            project += patcher + mirror + 'foundation_gui_patch(include/gui/web.hpp web-tick.patch include/gui/web.hpp)\n'
            project += 'add_executable(mirror main.cpp)\ntarget_compile_features(mirror PRIVATE cxx_std_20)\n'
            project += 'target_include_directories(mirror PRIVATE "${CMAKE_CURRENT_BINARY_DIR}/include" "${FOUNDATION_GUI_SOURCE}/include")\n'
            (source / 'CMakeLists.txt').write_text(project)
            build = root / 'build'
            configure = ['cmake','-G','Ninja','-S',str(source),'-B',str(build)]
            compile = ['cmake','--build',str(build)]
            for command in (configure,compile):
                subprocess.run(command,check=True,capture_output=True,text=True,timeout=45)
            outputs = list((build/'include/gui').glob('*.hpp')) + list((build/'CMakeFiles/mirror.dir').rglob('*.o')) + list((build/'CMakeFiles/mirror.dir').rglob('*.obj'))
            self.assertGreater(len(outputs),5)
            before = {path: (path.read_bytes(),path.stat().st_mtime_ns) for path in outputs}
            for command in (configure,compile):
                subprocess.run(command,check=True,capture_output=True,text=True,timeout=45)
            self.assertEqual(before,{path:(path.read_bytes(),path.stat().st_mtime_ns) for path in outputs})
            # A reviewed supplier inventory upgrade cannot leave stale generated
            # headers visible only to incremental consumers.
            (upstream/'removed.hpp').unlink()
            remaining={path:value for path,value in before.items() if path.name!='removed.hpp'}
            for command in (configure,compile):
                subprocess.run(command,check=True,capture_output=True,text=True,timeout=45)
            self.assertFalse((build/'include/gui/removed.hpp').exists())
            self.assertEqual(remaining,{path:(path.read_bytes(),path.stat().st_mtime_ns) for path in remaining})
            self.assertIn('contract_value=1', (upstream/'contract.hpp').read_text())

    def test_shared_declaration_has_one_construction_and_layout_source(self):
        source = (ROOT / "gui/shared/application.cpp").read_text()
        definition = (ROOT / "gui/shared/view_definition.hpp").read_text()
        self.assertIn("definition : view_definition", source)
        self.assertIn("definition.height", source)
        for identity in ("entries.heading", "entries.editor", "entries.add", "entries.remove"):
            self.assertEqual(1, definition.count('"' + identity + '"'))
        for path in (ROOT / "gui/patches").glob("*.patch"):
            self.assertNotIn('"entries.', path.read_text(), str(path))
        visual = (ROOT / "gui/tests/visual_test.py").read_text()
        self.assertIn("negative_checks(images['framebuffer'], baseline)", visual)

    def test_dependency_lock_is_complete_for_consumed_inputs(self):
        lock = json.loads((ROOT / "third_party/gui-boundary.lock.json").read_text())
        self.assertRegex(lock["revision"], r"^[0-9a-f]{40}$")
        self.assertRegex(lock["source_tree"], r"^[0-9a-f]{40}$")
        for path in ("include/gui/contract.hpp", "include/gui/layout.hpp",
                     "include/gui/terminal.hpp", "include/gui/framebuffer.hpp",
                     "backends/terminal/main.cpp", "backends/fltk/adapter.hpp",
                     "backends/rev/adapter.cpp", "backends/framebuffer/main_sdl.cpp",
                     "backends/web/renderer.mjs", "backends/web/host.py",
                     "cmake/PrepareRev.cmake", "third_party/rev/SHA256SUMS"):
            self.assertIn(path, lock["files"])
        for path, digest in lock["files"].items():
            self.assertFalse(Path(path).is_absolute())
            self.assertNotIn("..", Path(path).parts)
            self.assertRegex(digest, r"^[0-9a-f]{64}$")
        self.assertEqual("CC0-1.0", lock["license"])
        self.assertIn("LICENSE", lock["redistribution"]["license_files"])
        for notice in lock["redistribution"]["license_files"]:
            self.assertIn(notice, lock["files"])


    def test_typed_host_contract_has_no_feature_dispatch(self):
        for path in (ROOT / "gui/host").glob("*.hpp"):
            self.assertNotIn('"entries.', path.read_text())
            self.assertNotIn("foundation::Store", path.read_text())
        cmake = (ROOT / "gui/CMakeLists.txt").read_text()
        self.assertNotIn("using Example", cmake)
        self.assertNotIn("string(REPLACE", cmake)
        for name in ("FLTK", "SDL", "REV", "WEB"):
            self.assertIn("FOUNDATION_GUI_" + name, cmake)

    def windows_macro_fixture(self, *, windows, remove_guard=False):
        # Execute the real shared interface, application linkage and host factory.
        # Windows uses its actual platform header; other hosts reproduce only
        # that header's conditional min/max definitions for the same compile test.
        cmake = (ROOT / "gui/CMakeLists.txt").read_text()
        inputs = (ROOT / "cmake/GuiInputs.cmake").read_text()
        boundary = "add_library(foundation_gui_boundary INTERFACE)" + inputs.split(
            "add_library(foundation_gui_boundary INTERFACE)", 1)[1].split("endmacro()", 1)[0]
        application = "add_library(foundation_gui_application STATIC" + cmake.split(
            "add_library(foundation_gui_application STATIC", 1)[1].split("function(gui_warnings", 1)[0]
        host = "function(foundation_gui_executable" + cmake.split(
            "function(foundation_gui_executable", 1)[1].split("endfunction()", 1)[0] + "endfunction()\n"
        with tempfile.TemporaryDirectory(prefix="gui Windows macros ") as directory:
            source = Path(directory) / "source"; source.mkdir()
            (source / "shared").mkdir(); (source / "include").mkdir()
            header = """#pragma once
#include <algorithm>
#ifdef FIXTURE_WINDOWS_HEADERS
#ifdef _WIN32
#include <windows.h>
#elif !defined(NOMINMAX)
#define min(a,b) (((a)<(b))?(a):(b))
#define max(a,b) (((a)>(b))?(a):(b))
#endif
#else
#ifdef NOMINMAX
#error Non-Windows consumers must not inherit NOMINMAX
#endif
#endif
inline int generic_extent() { return std::min(4, std::max(1, 2)); }
"""
            (source / "collision.hpp").write_text(header, encoding="utf-8")
            (source / "shared/application.cpp").write_text(
                '#include "collision.hpp"\nint shared_extent() { return generic_extent(); }\n', encoding="utf-8")
            (source / "host.cpp").write_text(
                '#include "collision.hpp"\nint shared_extent();\nint main() { return shared_extent() != generic_extent(); }\n', encoding="utf-8")
            (source / "direct.cpp").write_text(
                '#include "collision.hpp"\nint main() { return generic_extent() != 2; }\n', encoding="utf-8")
            project = """cmake_minimum_required(VERSION 3.24)
project(WindowsGuiHeaderContract LANGUAGES CXX)
set(FOUNDATION_GUI_SOURCE "${CMAKE_CURRENT_SOURCE_DIR}")
set(EMSCRIPTEN OFF)
add_library(Threads::Threads INTERFACE IMPORTED)
add_library(fixture_core INTERFACE)
add_library(foundation::core ALIAS fixture_core)
add_custom_target(foundation_gui_contract)
add_custom_target(foundation-gui-hosts)
function(foundation_options target)
endfunction()
"""
            project += "set(WIN32 " + ("ON" if windows else "OFF") + ")\n"
            if windows:
                project += "add_compile_definitions(FIXTURE_WINDOWS_HEADERS)\n"
            project += boundary
            if remove_guard:
                project += "set_property(TARGET foundation_gui_boundary PROPERTY INTERFACE_COMPILE_DEFINITIONS \"\")\n"
            project += application + host + """
foundation_gui_executable(foundation-gui-fixture host.cpp)
add_executable(direct_boundary_consumer direct.cpp)
target_link_libraries(direct_boundary_consumer PRIVATE gui_boundary)
"""
            (source / "CMakeLists.txt").write_text(project, encoding="utf-8")
            build = Path(directory) / "build"
            configured = subprocess.run(["cmake", "-G", "Ninja", "-S", str(source), "-B", str(build)],
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, timeout=30)
            self.assertEqual(0, configured.returncode, configured.stdout)
            return subprocess.run(["cmake", "--build", str(build), "--config", "Debug", "--parallel", "2"],
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, timeout=60)

    def test_windows_shared_interface_prevents_native_min_max_macro_collision(self):
        guarded = self.windows_macro_fixture(windows=True)
        self.assertEqual(0, guarded.returncode, guarded.stdout)
        unguarded = self.windows_macro_fixture(windows=True, remove_guard=True)
        self.assertNotEqual(0, unguarded.returncode, "The negative control must expose the platform macro collision")
        self.assertIn("collision.hpp", unguarded.stdout)

    def test_non_windows_shared_interface_does_not_add_windows_macro_policy(self):
        result = self.windows_macro_fixture(windows=False)
        self.assertEqual(0, result.returncode, result.stdout)

    def test_sdl_host_and_deliverable_checks_select_declared_native_display(self):
        self.sdl_display_fixture()

    def test_sdl_display_discovery_selects_multiconfig_configuration(self):
        self.sdl_display_fixture("Ninja Multi-Config")

    def sdl_display_fixture(self, generator=None):
        cmake = (ROOT / "gui/CMakeLists.txt").read_text()
        setup = "function(foundation_gui_sdl_display_test " + cmake.split(
            "function(foundation_gui_sdl_display_test ", 1)[1].split("endfunction()", 1)[0] + "endfunction()\n"
        installed = "foreach(backend IN LISTS smoke_backends)" + cmake.split(
            "foreach(backend IN LISTS smoke_backends)", 1)[1].split("endforeach()", 1)[0] + "endforeach()\n"
        native = "foundation_gui_executable(foundation_gui_sdl_test" + cmake.split(
            "foundation_gui_executable(foundation_gui_sdl_test", 1)[1].split("endif()", 1)[0]
        project = """cmake_minimum_required(VERSION 3.24)
project(NativeSdlDisplay LANGUAGES NONE)
enable_testing()
set(smoke_backends sdl)
set(Python3_EXECUTABLE "${CMAKE_COMMAND}")
add_executable(foundation-gui-sdl IMPORTED)
set_target_properties(foundation-gui-sdl PROPERTIES IMPORTED_LOCATION "${CMAKE_COMMAND}")
function(foundation_gui_executable)
endfunction()
function(target_link_libraries)
endfunction()
function(foundation_gui_check name target labels)
    add_test(NAME foundation.gui.${name} COMMAND "${CMAKE_COMMAND}" --version)
endfunction()
"""
        project += 'include("' + (ROOT / 'cmake/TestPrerequisites.cmake').as_posix() + '")\n'
        with tempfile.TemporaryDirectory(prefix="SDL native display ") as directory:
            root = Path(directory)
            for system, driver in (("Linux", "x11"), ("Windows", "windows"), ("Other", None)):
                with self.subTest(system=system):
                    source = root / system; source.mkdir()
                    (source / "CMakeLists.txt").write_text(project + 'set(CMAKE_SYSTEM_NAME "' + system + '")\n' +
                                                          setup + installed + native)
                    build = source / "build"
                    command = ["cmake", "-S", str(source), "-B", str(build)]
                    if generator is not None: command += ["-G", generator]
                    result = subprocess.run(command, capture_output=True, text=True, timeout=30)
                    if driver is None:
                        self.assertNotEqual(0, result.returncode)
                        self.assertIn("Declare the native SDL video driver", result.stderr)
                        continue
                    self.assertEqual(0, result.returncode, result.stdout + result.stderr)
                    # Multi-configuration generators guard test definitions by
                    # configuration even when this fixture builds no executable.
                    result = subprocess.run(["ctest", "--test-dir", str(build), "-C", "Debug", "--show-only=json-v1"],
                        capture_output=True, text=True, check=True, timeout=15)
                    tests = json.loads(result.stdout)["tests"]
                    self.assertEqual({"foundation.gui.installed-sdl", "foundation.gui.sdl-host"},
                                     {test["name"] for test in tests})
                    for test in tests:
                        properties = {item["name"]: item["value"] for item in test["properties"]}
                        self.assertEqual(["SDL_VIDEODRIVER=" + driver], properties["ENVIRONMENT"])
                        self.assertEqual(["foundation_native_display"], properties["RESOURCE_LOCK"])

    def sdl_link_fixture(self, *, portable, static_available=True, remove_selection=False):
        cmake = (ROOT / "gui/CMakeLists.txt").read_text()
        block = (ROOT / "cmake/GuiNativeBackends.cmake").read_text() + "\nif(FOUNDATION_GUI_SDL)\n" + cmake.split("if(FOUNDATION_GUI_SDL)\n", 1)[1].split(
            "\nif(FOUNDATION_GUI_REV)", 1)[0]
        native_test = "foundation_gui_executable(foundation_gui_sdl_test" + cmake.split(
            "foundation_gui_executable(foundation_gui_sdl_test", 1)[1].split(
            "foundation_gui_check(sdl-host", 1)[0]
        if remove_selection:
            block = block.replace("INTERFACE SDL2::SDL2-static)", "INTERFACE SDL2::SDL2)")
        with tempfile.TemporaryDirectory(prefix="SDL linkage ") as temporary:
            root = Path(temporary); source = root / "source"; source.mkdir()
            (source / "static.c").write_text("int fixture_value(void) { return 3; }\n")
            (source / "shared.c").write_text("int fixture_value(void) { return 7; }\n")
            (source / "entry.c").write_text("int fixture_value(void); int fixture_entry(void) { return fixture_value(); }\n")
            (source / "main.c").write_text("int fixture_entry(void); int main(void) { return fixture_entry() != " +
                                           ("3" if portable else "7") + "; }\n")
            config = """add_library(fixture_shared SHARED "${CMAKE_CURRENT_SOURCE_DIR}/shared.c")
set_target_properties(fixture_shared PROPERTIES WINDOWS_EXPORT_ALL_SYMBOLS ON)
add_library(SDL2::SDL2 ALIAS fixture_shared)
add_library(fixture_entry STATIC "${CMAKE_CURRENT_SOURCE_DIR}/entry.c")
add_library(SDL2::SDL2main ALIAS fixture_entry)
"""
            if static_available:
                config += """add_library(fixture_static STATIC "${CMAKE_CURRENT_SOURCE_DIR}/static.c")
add_library(SDL2::SDL2-static ALIAS fixture_static)
"""
            (source / "SDL2Config.cmake").write_text(config)
            project = """cmake_minimum_required(VERSION 3.24)
project(PortableSdlSelection LANGUAGES C)
set(SDL2_DIR "${CMAKE_CURRENT_SOURCE_DIR}")
set(FOUNDATION_GUI_SDL ON)
function(foundation_gui_patch)
endfunction()
function(foundation_gui_executable name source)
    add_executable(${name} "${CMAKE_CURRENT_SOURCE_DIR}/main.c")
endfunction()
"""
            project += "set(FOUNDATION_PORTABLE " + ("ON" if portable else "OFF") + ")\n" + block + "\n" + native_test
            (source / "CMakeLists.txt").write_text(project)
            build = root / "build"
            configured = subprocess.run(["cmake", "-G", "Ninja", "-S", str(source), "-B", str(build)],
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, timeout=30)
            if portable and not static_available:
                self.assertNotEqual(0, configured.returncode)
                self.assertIn("Portable SDL requires the retained SDL2::SDL2-static target", configured.stdout)
                return []
            self.assertEqual(0, configured.returncode, configured.stdout)
            built = subprocess.run(["cmake", "--build", str(build), "--config", "Debug", "--parallel", "2"],
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, timeout=60)
            self.assertEqual(0, built.returncode, built.stdout)
            return [subprocess.run([str(next(p for p in build.glob(name + "*") if p.is_file() and
                p.suffix in ("", ".exe")))], cwd=build, capture_output=True, timeout=10).returncode
                for name in ("foundation-gui-sdl", "foundation_gui_sdl_test")]

    def test_portable_sdl_host_and_test_use_static_supplier_target(self):
        self.assertEqual([0, 0], self.sdl_link_fixture(portable=True))
        self.assertEqual([1, 1], self.sdl_link_fixture(portable=True, remove_selection=True),
                         "Both consumers must expose the incorrect shared linkage")

    def test_ordinary_sdl_preserves_shared_target_and_portable_requires_static(self):
        self.assertEqual([0, 0], self.sdl_link_fixture(portable=False))
        self.assertEqual([], self.sdl_link_fixture(portable=True, static_available=False))

    def rev_dependency_configuration(self, *, sdk=False, bundled=None, windows=False):
        # Execute the real composition block in CMake. The fixture replaces only
        # the toolkit build, so this stays independent of native SDK availability.
        cmake = (ROOT / "gui/CMakeLists.txt").read_text()
        block = cmake.split("if(FOUNDATION_GUI_REV)\n", 1)[1].split("\nif(BUILD_TESTING)", 1)[0]
        block = (ROOT / "cmake/GuiNativeBackends.cmake").read_text() + "\nif(FOUNDATION_GUI_REV)\n" + block
        with tempfile.TemporaryDirectory(prefix="rev dependency ") as directory:
            root = Path(directory)
            source = root / "source"; source.mkdir()
            project = """cmake_minimum_required(VERSION 3.24)
project(RevDependencySelection LANGUAGES NONE)
set(FOUNDATION_GUI_REV ON)
function(foundation_gui_patch source patch output)
    if(output STREQUAL "Rev.cmake")
        file(WRITE "${CMAKE_CURRENT_BINARY_DIR}/Rev.cmake" [=[
option(GUI_REV_BUNDLED_DEPS "Retained dependencies" ${WIN32})
if(GUI_REV_BUNDLED_DEPS)
    file(WRITE "${CMAKE_CURRENT_BINARY_DIR}/selection.txt" "retained")
else()
    file(WRITE "${CMAKE_CURRENT_BINARY_DIR}/selection.txt" "system")
endif()
]=])
    endif()
endfunction()
function(foundation_gui_executable)
endfunction()
function(target_link_libraries)
endfunction()
"""
            project += "set(WIN32 " + ("ON" if windows else "OFF") + ")\n"
            if sdk:
                project += 'set(FOUNDATION_SDK_ROOT "retained SDK")\n'
            (source / "CMakeLists.txt").write_text(project + block, encoding="utf-8")
            command = ["cmake", "-G", "Ninja", "-S", str(source), "-B", str(root / "build")]
            if bundled is not None:
                command.append("-DGUI_REV_BUNDLED_DEPS=" + bundled)
            result = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                    text=True, timeout=30)
            selected = root / "build/selection.txt"
            return result, selected.read_text() if selected.exists() else None

    def test_prepared_sdk_rev_selects_retained_dependencies(self):
        for setting in (None, "ON"):
            with self.subTest(setting=setting):
                result, selected = self.rev_dependency_configuration(sdk=True, bundled=setting)
                self.assertEqual(0, result.returncode, result.stdout)
                self.assertEqual("retained", selected)

    def test_prepared_sdk_rev_rejects_system_dependency_override(self):
        result, selected = self.rev_dependency_configuration(sdk=True, bundled="OFF")
        self.assertNotEqual(0, result.returncode)
        self.assertIn("Prepared SDK Rev requires GUI_REV_BUNDLED_DEPS=ON", result.stdout)
        self.assertIsNone(selected, "Reject the conflict before entering the toolkit build")

    def test_local_rev_dependency_defaults_and_overrides_remain_available(self):
        for windows, setting, expected in ((False, None, "system"), (False, "ON", "retained"),
                                            (True, None, "retained"), (True, "OFF", "system")):
            with self.subTest(windows=windows, setting=setting):
                result, selected = self.rev_dependency_configuration(windows=windows, bundled=setting)
                self.assertEqual(0, result.returncode, result.stdout)
                self.assertEqual(expected, selected)

    def fltk_static_link_fixture(self, *, sdk):
        # Model the SDK's autotools FindFLTK result: the static archive itself
        # omits its Xft closure. Every imported edge must reach the final link.
        cmake = (ROOT / "gui/CMakeLists.txt").read_text()
        block = (ROOT / "cmake/GuiNativeBackends.cmake").read_text() + "\nif(FOUNDATION_GUI_FLTK)\n" + cmake.split("if(FOUNDATION_GUI_FLTK)\n", 1)[1].split(
            "\nif(FOUNDATION_GUI_SDL)", 1)[0]
        with tempfile.TemporaryDirectory(prefix="fltk dependency ") as directory:
            root = Path(directory); source = root / "source"; source.mkdir()
            units = {
                "main": "int fltk_entry(void); int main(void) { return fltk_entry(); }",
                "fltk": "int xft_entry(void); int fltk_entry(void) { return xft_entry(); }",
                "xft": "int render_entry(void); int font_entry(void); int type_entry(void); "
                       "int xft_entry(void) { return render_entry()+font_entry()+type_entry(); }",
                "render": "int render_entry(void) { return 0; }",
                "font": "int font_entry(void) { return 0; }",
                "type": "int type_entry(void) { return 0; }"}
            for name, content in units.items():
                (source / (name + ".c")).write_text(content, encoding="utf-8")
            (source / "FindFLTK.cmake").write_text(
                "set(FLTK_LIBRARIES fixture_fltk)\nset(FLTK_FOUND TRUE)\n", encoding="utf-8")
            (source / "FindX11.cmake").write_text("""
if(NOT "Xft" IN_LIST X11_FIND_COMPONENTS OR NOT "Xrender" IN_LIST X11_FIND_COMPONENTS)
    message(FATAL_ERROR "The SDK must require the static toolkit dependencies")
endif()
foreach(name xft render font type)
    add_library(fixture_${name} STATIC "${CMAKE_CURRENT_SOURCE_DIR}/${name}.c")
endforeach()
add_library(X11::Xft ALIAS fixture_xft)
add_library(X11::Xrender ALIAS fixture_render)
add_library(Fontconfig::Fontconfig ALIAS fixture_font)
add_library(Freetype::Freetype ALIAS fixture_type)
target_link_libraries(fixture_xft PUBLIC X11::Xrender Fontconfig::Fontconfig Freetype::Freetype)
""", encoding="utf-8")
            project = """cmake_minimum_required(VERSION 3.24)
project(StaticToolkitClosure LANGUAGES C)
list(PREPEND CMAKE_MODULE_PATH "${CMAKE_CURRENT_SOURCE_DIR}")
set(FOUNDATION_GUI_FLTK ON)
set(CMAKE_SYSTEM_NAME Linux)
add_library(fixture_fltk STATIC fltk.c)
function(foundation_gui_patch)
endfunction()
function(foundation_gui_repatch)
endfunction()
function(foundation_gui_executable name source)
    add_executable(${name} "${CMAKE_CURRENT_SOURCE_DIR}/main.c")
endfunction()
"""
            if sdk:
                project += 'set(FOUNDATION_SDK_ROOT "retained SDK")\n'
            (source / "CMakeLists.txt").write_text(project + block, encoding="utf-8")
            result = subprocess.run(["cmake", "-G", "Ninja", "-S", str(source), "-B", str(root / "build")],
                                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, timeout=30)
            self.assertEqual(0, result.returncode, result.stdout)
            return subprocess.run(["cmake", "--build", str(root / "build"), "--config", "Debug",
                                   "--parallel", "2", "--target", "foundation-gui-fltk"],
                                  stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, timeout=60)

    def test_prepared_sdk_fltk_carries_complete_static_link_dependencies(self):
        with_sdk = self.fltk_static_link_fixture(sdk=True)
        self.assertEqual(0, with_sdk.returncode, with_sdk.stdout)
        # Negative control proves the fixture actually needs the new closure.
        without_sdk_closure = self.fltk_static_link_fixture(sdk=False)
        self.assertNotEqual(0, without_sdk_closure.returncode)
        self.assertIn("xft_entry", without_sdk_closure.stdout)

    def test_patch_application_is_exact_and_fail_closed(self):
        spec = importlib.util.spec_from_file_location("gui_patch", ROOT / "gui/patches/apply.py")
        module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
        patch = "--- old\n+++ new\n@@ -1,2 +1,2 @@\n first\n-old\n+new\n"
        self.assertEqual("first\nnew\n", module.apply("first\nold\n", patch))
        for source in ("different\nold\n", "first\nchanged\n", "prefix\nfirst\nold\n"):
            with self.assertRaises(ValueError): module.apply(source, patch)
        with self.assertRaises(ValueError): module.apply("first\nold\n", patch.replace("-1,2", "-1,3"))

    def test_portability_patches_select_exact_generated_tests_and_preserve_inputs(self):
        # Execute the actual patch function and upstream target-selection block.
        # Full behavior stays in the upstream executable tests; this fixture
        # detects compiling the unchanged supplier file or losing patch inputs.
        cmake = (ROOT / "gui/CMakeLists.txt").read_text()
        inputs = (ROOT / "cmake/GuiInputs.cmake").read_text()
        patch_function = "function(foundation_gui_patch" + inputs.split(
            "function(foundation_gui_patch", 1)[1].split("endfunction()", 1)[0] + "endfunction()\n"
        tests = "foreach(test_name contract " + cmake.split(
            "foreach(test_name contract ", 1)[1].split("endforeach()", 1)[0] + "endforeach()\n"
        lock = json.loads((ROOT / "third_party/gui-boundary.lock.json").read_text())
        declared = {entry.split(": ", 1)[0] for entry in lock["patches"]}
        with tempfile.TemporaryDirectory(prefix="GUI test patches ") as temporary:
            source = Path(temporary) / "source"; source.mkdir()
            upstream = source / "upstream"; (upstream / "tests").mkdir(parents=True)
            (source / "patches").mkdir()
            (source / "patches/apply.py").write_bytes((ROOT / "gui/patches/apply.py").read_bytes())
            originals = {}
            for name in ("contract", "adapter"):
                patch_name = "gui/patches/" + name + "-portability.patch"
                self.assertIn(patch_name, declared)
                patch = (ROOT / patch_name).read_text(encoding="utf-8")
                (source / "patches" / Path(patch_name).name).write_text(patch, encoding="utf-8")
                lines = patch.splitlines(keepends=True)
                start = int(re.match(r"@@ -(\d+)", lines[2]).group(1))
                original = "\n" * (start - 1) + "".join(line[1:] for line in lines[3:] if line.startswith((" ", "-")))
                path = upstream / "tests" / (name + "_test.cpp")
                path.write_text(original, encoding="utf-8"); originals[name] = path.read_bytes()
            for name in ("bitmap", "layout", "runtime", "presentation", "extension", "interaction", "framebuffer", "terminal", "web"):
                (upstream / "tests" / (name + "_test.cpp")).write_text("int main() { return 0; }\n")
            project = """cmake_minimum_required(VERSION 3.24)
project(PatchedSupplierTests LANGUAGES CXX)
set(FOUNDATION_GUI_SOURCE "${CMAKE_CURRENT_SOURCE_DIR}/upstream")
add_library(foundation_gui_boundary INTERFACE)
function(foundation_options target)
    target_compile_features(${target} PRIVATE cxx_std_20)
endfunction()
function(foundation_gui_check)
endfunction()
"""
            project += 'set(Python3_EXECUTABLE "' + Path(sys.executable).as_posix() + '")\n'
            project += 'set(foundation_gui_module_root "${CMAKE_CURRENT_SOURCE_DIR}")\n'
            project += patch_function + tests
            for name in ("contract", "adapter", "bitmap"):
                project += 'get_target_property(selected foundation_gui_upstream_' + name + ' SOURCES)\n'
                project += 'file(WRITE "${CMAKE_CURRENT_BINARY_DIR}/' + name + '.source" "${selected}")\n'
            (source / "CMakeLists.txt").write_text(project, encoding="utf-8")
            build = Path(temporary) / "build"
            result = subprocess.run(["cmake", "-G", "Ninja", "-S", str(source), "-B", str(build)],
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, timeout=30)
            self.assertEqual(0, result.returncode, result.stdout)
            for name in ("contract", "adapter"):
                generated = build / "tests" / (name + "_test.cpp")
                self.assertEqual(generated.resolve(strict=True), Path((build / (name + ".source")).read_text()).resolve(strict=True))
                self.assertIn("MemoryAdapter* active=nullptr;", generated.read_text())
                self.assertEqual(originals[name], (upstream / "tests" / (name + "_test.cpp")).read_bytes())
            self.assertEqual((upstream / "tests/bitmap_test.cpp").resolve(strict=True), Path((build / "bitmap.source").read_text()).resolve(strict=True))
            changed = upstream / "tests/contract_test.cpp"
            changed.write_text(changed.read_text().replace("const Event& event", "const Event& changed", 1))
            rejected = subprocess.run(["cmake", "-G", "Ninja", "-S", str(source), "-B", str(Path(temporary) / "rejected")],
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, timeout=30)
            self.assertNotEqual(0, rejected.returncode)
            self.assertIn("Patch context differs", rejected.stdout)

    def test_browser_startup_diagnostics_survive_cleanup(self):
        spec = importlib.util.spec_from_file_location("gui_browser", ROOT / "gui/tests/browser_test.py")
        browser = importlib.util.module_from_spec(spec); spec.loader.exec_module(browser)
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            with self.assertRaisesRegex(RuntimeError, "startup failed"):
                with browser.browser_workspace(output) as work:
                    (work / "chromedriver.log").write_text("startup evidence")
                    raise RuntimeError("startup failed")
            self.assertEqual("startup evidence", (output / "chromedriver.log").read_text())
            self.assertFalse(any(path.name.startswith("browser-") for path in output.iterdir()))

    def test_browser_transport_has_bounded_worker_and_cleanup(self):
        source = (ROOT / "gui/hosts/web_host.py").read_text()
        self.assertIn("queue.Queue(1)", source)
        self.assertIn("self.worker.join(timeout=2)", source)
        self.assertNotIn("select.select", source)


class BrowserOwnerTests(unittest.TestCase):
    def setUp(self):
        spec = importlib.util.spec_from_file_location("owned_browser", ROOT / "gui/tests/browser_test.py")
        self.browser = importlib.util.module_from_spec(spec); spec.loader.exec_module(self.browser)

    def instance(self, cls, log, owner):
        instance = cls.__new__(cls)
        instance.owner = owner; instance.log = log
        instance.closed = False; instance.cleanup_error = None
        instance.socket = None; instance.session = None
        return instance

    def test_firefox_accepts_delayed_startup_without_extending_protocol_timeout(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary); elapsed = [0.0]; attempts = []; connection = mock.Mock()
            owner = mock.Mock(); owner.process.poll.return_value = None
            def connect(address, *, timeout):
                self.assertEqual(('127.0.0.1', 32100), address)
                self.assertEqual(1, timeout)
                attempts.append(elapsed[0])
                if elapsed[0] >= 21.5: return connection
                elapsed[0] += timeout
                raise OSError('Firefox has not started listening')
            def sleep(seconds): elapsed[0] += seconds
            def command(name, arguments):
                return {'capabilities': {'browserVersion': '156.0'}} if name == 'WebDriver:NewSession' else {}
            with mock.patch.object(self.browser.process_tree, 'launch', return_value=owner), \
                 mock.patch.object(self.browser.socket, 'socket') as reserve_socket, \
                 mock.patch.object(self.browser.socket, 'create_connection', side_effect=connect), \
                 mock.patch.object(self.browser.time, 'monotonic', side_effect=lambda: elapsed[0]), \
                 mock.patch.object(self.browser.time, 'sleep', side_effect=sleep), \
                 mock.patch.object(self.browser.Browser, 'receive', return_value={}), \
                 mock.patch.object(self.browser.Browser, 'command', side_effect=command):
                reserve_socket.return_value.__enter__.return_value.getsockname.return_value = ('127.0.0.1', 32100)
                with self.browser.browser_workspace(output) as work:
                    browser = self.browser.Browser('firefox', work)
                    try:
                        self.assertGreater(attempts[-1], 20)
                        self.assertLess(attempts[-1], 120)
                        self.assertEqual('156.0', browser.capabilities['browserVersion'])
                        connection.settimeout.assert_called_once_with(15)
                        owner.terminate.assert_not_called(); owner.close.assert_not_called()
                    finally: browser.close()
            owner.terminate.assert_called_once(); owner.close.assert_called_once()
            connection.close.assert_called_once()
            self.assertFalse(work.exists())

    def test_firefox_startup_expires_at_120_seconds_and_joins_before_diagnostics(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary); elapsed = [0.0]; attempts = []; events = []; streams = []
            owner = mock.Mock(); owner.process.poll.return_value = None
            owner.terminate.side_effect = lambda: events.append('terminate')
            owner.close.side_effect = lambda: events.append('join')
            def launch(argv, cwd, stream, *, env):
                streams.append(stream); stream.write('Firefox startup remained pending'); stream.flush()
                return owner
            def connect(address, *, timeout):
                self.assertEqual(1, timeout)
                attempts.append(elapsed[0]); elapsed[0] += timeout
                raise OSError('Firefox has not started listening')
            def sleep(seconds): elapsed[0] += seconds
            real_copy = self.browser.shutil.copyfile
            def copy(source, destination):
                self.assertEqual(['terminate', 'join'], events)
                self.assertTrue(streams[0].closed)
                return real_copy(source, destination)
            with mock.patch.object(self.browser.process_tree, 'launch', side_effect=launch), \
                 mock.patch.object(self.browser.socket, 'socket') as reserve_socket, \
                 mock.patch.object(self.browser.socket, 'create_connection', side_effect=connect), \
                 mock.patch.object(self.browser.time, 'monotonic', side_effect=lambda: elapsed[0]), \
                 mock.patch.object(self.browser.time, 'sleep', side_effect=sleep), \
                 mock.patch.object(self.browser.shutil, 'copyfile', side_effect=copy):
                reserve_socket.return_value.__enter__.return_value.getsockname.return_value = ('127.0.0.1', 32100)
                with self.assertRaisesRegex(TimeoutError, 'Firefox automation startup timeout'):
                    with self.browser.browser_workspace(output) as work:
                        self.browser.Browser('firefox', work)
            self.assertLess(attempts[-1], 120)
            self.assertGreaterEqual(elapsed[0], 120)
            self.assertLess(elapsed[0], 121.1)  # At most the last bounded connection attempt plus its pause.
            owner.terminate.assert_called_once(); owner.close.assert_called_once()
            self.assertEqual('Firefox startup remained pending', (output / 'firefox.log').read_text())
            self.assertFalse(work.exists())

    def test_both_launchers_own_startup_and_join_before_log_copy(self):
        for chromium in (False, True):
            with self.subTest(chromium=chromium), tempfile.TemporaryDirectory() as temporary:
                output = Path(temporary); events = []; streams = []
                owner = mock.Mock(); owner.process.poll.return_value = 1
                owner.terminate.side_effect = lambda: events.append('terminate')
                owner.close.side_effect = lambda: events.append('join')
                def launch(argv, cwd, stream, *, env):
                    self.assertEqual(Path.cwd(), cwd)
                    streams.append(stream); stream.write('startup evidence'); stream.flush()
                    self.assertEqual('driver' if chromium else 'firefox', argv[0])
                    self.assertEqual(None if chromium else '1', None if env is None else env['MOZ_HEADLESS'])
                    return owner
                real_copy = self.browser.shutil.copyfile
                def copy(source, destination):
                    self.assertEqual(['terminate', 'join'], events)
                    self.assertTrue(streams[0].closed)
                    return real_copy(source, destination)
                with mock.patch.object(self.browser.process_tree, 'launch', side_effect=launch), \
                     mock.patch.object(self.browser.socket, 'socket') as reserve_socket, \
                     mock.patch.object(self.browser.socket, 'create_connection', side_effect=OSError('offline')), \
                     mock.patch.object(self.browser.ChromiumBrowser, 'request', side_effect=OSError('offline')), \
                     mock.patch.object(self.browser.shutil, 'copyfile', side_effect=copy):
                    reserve_socket.return_value.__enter__.return_value.getsockname.return_value = ('127.0.0.1', 32100)
                    with self.assertRaisesRegex(RuntimeError, 'exited during startup'):
                        with self.browser.browser_workspace(output) as work:
                            if chromium: self.browser.ChromiumBrowser('chrome', 'driver', work, [])
                            else: self.browser.Browser('firefox', work)
                self.assertEqual('startup evidence', (output / ('chromedriver.log' if chromium else 'firefox.log')).read_text())
                self.assertFalse(list(output.glob('browser-*')))

    def test_failed_launch_closes_log_and_uncertain_launch_preserves_workspace(self):
        for uncertain in (False, True):
            with self.subTest(uncertain=uncertain), tempfile.TemporaryDirectory() as temporary:
                output = Path(temporary); streams = []
                error = (self.browser.process_tree.ProcessTreeError('writer cleanup is uncertain') if uncertain
                         else OSError('executable missing'))
                def launch(argv, cwd, stream, *, env):
                    streams.append(stream); stream.write('launch evidence'); raise error
                expected = self.browser.BrowserCleanupError if uncertain else OSError
                with mock.patch.object(self.browser.process_tree, 'launch', side_effect=launch):
                    with self.assertRaises(expected):
                        with self.browser.browser_workspace(output) as work:
                            instance = self.browser.Browser.__new__(self.browser.Browser)
                            instance._launch(['missing'], work, 'firefox.log')
                self.assertTrue(streams[0].closed)
                self.assertEqual(uncertain, work.exists())
                self.assertEqual(not uncertain, (output / 'firefox.log').exists())
                if uncertain:
                    self.assertEqual('launch evidence', (work / 'firefox.log').read_text())
                    with self.assertRaises(self.browser.BrowserCleanupError): instance.close()
                else: instance.close()  # Failed launch has no process or socket to close.

    def test_failure_after_owner_creation_still_joins_before_cleanup(self):
        with tempfile.TemporaryDirectory() as temporary:
            owner=mock.Mock(spec=['terminate','close'])
            with mock.patch.object(self.browser.process_tree,'launch',return_value=owner):
                with self.assertRaises(AttributeError):
                    with self.browser.browser_workspace(Path(temporary)) as work:
                        instance=self.browser.Browser.__new__(self.browser.Browser)
                        instance._launch(['unused'],work,'firefox.log')
            owner.terminate.assert_called_once();owner.close.assert_called_once()
            self.assertTrue(instance.log.closed);self.assertFalse(work.exists())

    def test_failed_launch_with_unclosed_log_preserves_uncertain_workspace(self):
        with tempfile.TemporaryDirectory() as temporary:
            output=Path(temporary); stream=mock.Mock(); stream.close.side_effect=OSError('flush failed')
            with mock.patch.object(self.browser.process_tree,'launch',side_effect=OSError('launch failed')), \
                 mock.patch.object(Path,'open',return_value=stream):
                with self.assertRaisesRegex(self.browser.BrowserCleanupError,'flush failed'):
                    with self.browser.browser_workspace(output) as work:
                        instance=self.browser.Browser.__new__(self.browser.Browser)
                        instance._launch(['missing'],work,'firefox.log')
            self.assertTrue(work.exists())
            with self.assertRaises(self.browser.BrowserCleanupError):instance.close()
            stream.close.assert_called_once()

    def test_disconnect_failure_still_joins_and_successful_close_is_idempotent(self):
        for cls in (self.browser.Browser, self.browser.ChromiumBrowser):
            with self.subTest(cls=cls.__name__):
                events = []; owner = mock.Mock(); log = mock.Mock()
                owner.terminate.side_effect = lambda: events.append('terminate')
                owner.close.side_effect = lambda: events.append('join')
                log.close.side_effect = lambda: events.append('log')
                instance = self.instance(cls, log, owner)
                if cls is self.browser.Browser:
                    instance.socket = mock.Mock(); instance.socket.close.side_effect = RuntimeError('disconnect failed')
                else:
                    instance.session = 'active'; instance.request = mock.Mock(side_effect=RuntimeError('disconnect failed'))
                with self.assertRaisesRegex(RuntimeError, 'disconnect failed'): instance.close()
                self.assertEqual(['terminate', 'join', 'log'], events)
                instance.close()
                self.assertEqual(['terminate', 'join', 'log'], events)

    def test_uncertain_join_is_sticky_and_never_copies_or_deletes_logs(self):
        for failing_action in ('terminate', 'close'):
            with self.subTest(action=failing_action), tempfile.TemporaryDirectory() as temporary:
                output = Path(temporary); owner = mock.Mock()
                getattr(owner, failing_action).side_effect = RuntimeError('unconfirmed writer')
                with self.assertRaisesRegex(self.browser.BrowserCleanupError, 'unconfirmed writer'):
                    with self.browser.browser_workspace(output) as work:
                        log = (work / 'firefox.log').open('w'); log.write('not final')
                        (work / 'profile.sqlite').write_text('owned')
                        instance = self.instance(self.browser.Browser, log, owner)
                        instance.close()
                self.assertTrue(log.closed)
                owner.terminate.assert_called_once(); owner.close.assert_called_once()
                self.assertTrue((work / 'profile.sqlite').is_file())
                self.assertEqual('not final', (work / 'firefox.log').read_text())
                self.assertFalse((output / 'firefox.log').exists())
                with self.assertRaises(self.browser.BrowserCleanupError): instance.close()
                owner.terminate.assert_called_once(); owner.close.assert_called_once()

    def test_close_joins_actual_descendant_profile_writer_before_workspace_cleanup(self):
        # The browser/driver owns a child that keeps both its profile and inherited
        # log open. A parent-only wait cannot satisfy the pinned Windows handle or
        # Linux supervisor completion checks, even when its initial process exits.
        for cls in (self.browser.Browser, self.browser.ChromiumBrowser):
            with self.subTest(cls=cls.__name__), tempfile.TemporaryDirectory() as temporary:
                output = Path(temporary)
                with self.browser.browser_workspace(output) as work:
                    profile = work / 'profile.sqlite'
                    child = ('import os,time;f=open(' + repr(str(profile)) + ',"wb");'
                             'print("child-ready:"+str(os.getpid()),flush=True);time.sleep(60)')
                    parent = ('import subprocess,sys,time;subprocess.Popen([sys.executable,"-B","-c",' +
                              repr(child) + ']);print("parent-ready",flush=True);time.sleep(60)')
                    instance = cls.__new__(cls); instance.socket = None; instance.session = None
                    instance._launch([sys.executable, '-B', '-c', parent], work, 'firefox.log')
                    owner = instance.owner; handle = None
                    try:
                        deadline = time.monotonic() + 10
                        while True:
                            lines = (work / 'firefox.log').read_bytes().splitlines()
                            children = [line[len(b'child-ready:'):] for line in lines if line.startswith(b'child-ready:')]
                            if b'parent-ready' in lines and len(children) == 1 and children[0].isdigit(): break
                            if time.monotonic() >= deadline: self.fail('profile writer did not become ready')
                            time.sleep(.01)
                        if owner.job is not None:
                            job = owner.job; handle = job.api.OpenProcess(0x101000, False, int(children[0]))
                            self.assertTrue(handle, 'cannot pin descendant writer')
                            member = job.w.BOOL()
                            self.assertTrue(job.api.IsProcessInJob(handle, job.handle, ctypes.byref(member)))
                            self.assertTrue(member.value)
                        instance.close()
                        if handle is not None:
                            self.assertEqual(0, job.api.WaitForSingleObject(handle, 0), 'descendant writer is still running')
                        else:
                            self.assertFalse(owner._live(), 'descendant writer is still running')
                        self.assertTrue(owner.closed); self.assertTrue(instance.log.closed)
                        profile.rename(work / 'renamed.sqlite'); (work / 'renamed.sqlite').unlink()
                        completed = (work / 'firefox.log').read_bytes()
                        instance.close()
                    finally:
                        try: owner.terminate()
                        finally:
                            try: owner.close()
                            finally:
                                instance.log.close()
                                if handle is not None: self.assertTrue(job.api.CloseHandle(handle))
                self.assertEqual(completed, (output / 'firefox.log').read_bytes())
                self.assertFalse(work.exists())


if __name__ == "__main__":
    unittest.main()
