#!/usr/bin/env python3
"""Workbench build isolation and local-only complete Python test discovery."""
from contextlib import ExitStack, contextmanager
import http.client
import importlib.util
import json
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import urllib.request

ROOT = Path(__file__).resolve().parents[2]
# CTest launches from the isolated build tree, not the source checkout.
sys.path.insert(0, str(ROOT))
spec = importlib.util.spec_from_file_location("workbench_build_test_subject", ROOT / "workbench/build.py")
build = importlib.util.module_from_spec(spec)
spec.loader.exec_module(build)


def denied_transport(*args, **kwargs):
    raise AssertionError("Workbench automated tests prohibit real network transports")


@contextmanager
def offline_transports():
    """Deny real transports; provider fixtures must inject an in-memory client."""
    with ExitStack() as stack:
        for owner, attribute in (
            (socket, "create_connection"), (socket, "getaddrinfo"),
            (socket, "gethostbyname"), (socket, "gethostbyname_ex"), (socket, "gethostbyaddr"),
            (socket.socket, "connect"), (socket.socket, "connect_ex"),
            (socket.socket, "sendto"),
            (urllib.request, "urlopen"), (http.client.HTTPConnection, "connect"),
            (http.client.HTTPSConnection, "connect"),
        ):
            stack.enter_context(patch.object(owner, attribute, denied_transport))
        yield


class WorkbenchBuildTests(unittest.TestCase):
    def test_dispatch_precedes_application_provider_selection(self):
        result = subprocess.run([sys.executable, "-B", str(ROOT / "tools/build.py"), "workbench", "--help"],
                                cwd=ROOT, capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("--backend {fltk,rev,framebuffer}", result.stdout)
        self.assertIn("--headless", result.stdout)
        for application_flag in ("--core-provider", "--rust-sdk", "portable-package"):
            self.assertNotIn(application_flag, result.stdout)

    def test_foreign_or_unstamped_tree_rejected_without_writes(self):
        for component in (None, "application", "editor"):
            with self.subTest(component=component), tempfile.TemporaryDirectory() as temporary:
                tree = Path(temporary)
                (tree / "CMakeCache.txt").write_text("foreign cache fixture")
                if component:
                    (tree / "wrapper-identity.json").write_text(json.dumps({"component": component}))
                before = {p.name: p.read_bytes() for p in tree.iterdir()}
                with self.assertRaises(ValueError):
                    build.preflight(tree, {"component": "workbench"})
                self.assertEqual({p.name: p.read_bytes() for p in tree.iterdir()}, before)

    def test_backend_configuration_and_interpreter_changes_require_fresh_tree(self):
        identity = {"component": "workbench", "backend": "fltk", "operation": "build",
                    "sdk": None, "native_host": False, "program_hashes": {"python": "original"}}
        changes = (("backend", "rev"), ("operation", "test"), ("sdk", "other"),
                   ("native_host", True), ("program_hashes", {"python": "changed"}))
        with tempfile.TemporaryDirectory() as temporary:
            tree = Path(temporary)
            (tree / "wrapper-identity.json").write_text(json.dumps(identity))
            build.preflight(tree, identity)
            for key, value in changes:
                with self.subTest(key=key), self.assertRaises(ValueError):
                    build.preflight(tree, {**identity, key: value})

    def test_external_cmake_cache_modification_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            tree = Path(temporary)
            identity = {"component": "workbench"}
            (tree / "wrapper-identity.json").write_text(json.dumps(identity))
            (tree / "CMakeCache.txt").write_text("fixture")
            cache = {"CMAKE_HOME_DIRECTORY": str(ROOT / "workbench"), "compiler_file_sha256": "original"}
            (tree / "configured-identity.json").write_text(json.dumps(cache))
            with patch.object(build.application_build, "cache_identity", return_value=cache):
                build.preflight(tree, identity)
            with patch.object(build.application_build, "cache_identity", return_value={**cache, "compiler_file_sha256": "changed"}):
                with self.assertRaises(ValueError):
                    build.preflight(tree, identity)

    def test_workbench_tree_cannot_reuse_editor_cmake_cache(self):
        with tempfile.TemporaryDirectory() as temporary:
            tree = Path(temporary)
            identity = {"component": "workbench"}
            (tree / "wrapper-identity.json").write_text(json.dumps(identity))
            (tree / "CMakeCache.txt").write_text("fixture")
            with patch.object(build.application_build, "cache_identity", return_value={"CMAKE_HOME_DIRECTORY": str(ROOT / "editor")}):
                with self.assertRaises(ValueError):
                    build.preflight(tree, identity)

    def test_programs_resolve_existing_tools_without_packaging(self):
        with patch.object(build.application_build, "host_programs", return_value={"cmake": sys.executable, "ctest": sys.executable, "ninja": sys.executable, "cpack": "missing-unused-cpack"}):
            selected = build.selected_programs()
        self.assertEqual(set(selected), {"cmake", "ctest", "ninja", "python"})
        self.assertTrue(all(Path(path).is_absolute() and Path(path).is_file() for path in selected.values()))
        with patch.object(build.application_build, "host_programs", return_value={"cmake": "tinyenv-definitely-absent-cmake"}):
            with self.assertRaisesRegex(ValueError, "unavailable: cmake"):
                build.selected_programs()

    def test_selected_program_bytes_are_part_of_identity(self):
        args = SimpleNamespace(action="build", preset="dev", backend="fltk", headless=True,
                               sdk=None, dependency_prefix=None, gui_source=None, gui_input_group=None)
        module = SimpleNamespace(verify=lambda group: {}, receipt=lambda group, verified: {"group_sha256": "gui-input-fixture"})
        with tempfile.TemporaryDirectory() as temporary, patch.object(build, "input_group", return_value=module):
            tool = Path(temporary) / "python-fixture"
            tool.write_bytes(b"original interpreter fixture")
            before = build.identity_for(args, Path(temporary), {"python": str(tool)})
            tool.write_bytes(b"changed interpreter fixture")
            after = build.identity_for(args, Path(temporary), {"python": str(tool)})
        self.assertEqual(before["programs"], after["programs"])
        self.assertNotEqual(before["program_hashes"], after["program_hashes"])

    def test_headless_configuration_uses_selected_python_and_local_graph(self):
        commands = []
        programs = {name: str(Path(sys.executable).resolve()) for name in ("cmake", "ctest", "ninja", "python")}
        cache = {"CMAKE_HOME_DIRECTORY": str(ROOT / "workbench")}
        with tempfile.TemporaryDirectory() as temporary:
            args = SimpleNamespace(action="test", preset="dev", backend="rev", headless=True,
                                   sdk=None, dependency_prefix=None, gui_source=None, gui_input_group=None,
                                   build_dir=Path(temporary) / "tree", configure_only=False, jobs=2,
                                   build_jobs=None, test_jobs=None)
            with patch.object(build, "selected_programs", return_value=programs), \
                 patch.object(build, "identity_for", return_value={"component": "workbench"}), \
                 patch.object(build.application_build, "cache_identity", return_value=cache), \
                 patch.object(build.application_build, "job_limits", return_value=(2, 1)), \
                 patch.object(build.application_build, "run", side_effect=lambda argv, **kwargs: commands.append(argv)):
                build.execute(args)
            configured = commands[0]
            self.assertIn("-DTINYENV_WORKBENCH_BUILD_HOST=OFF", configured)
            self.assertIn("-DTINYENV_WORKBENCH_TESTS=ON", configured)
            self.assertIn("-DPython3_EXECUTABLE=" + programs["python"], configured)
            self.assertIn(str(ROOT / "workbench"), configured)
            self.assertEqual(len(commands), 3)
            self.assertIn("--no-tests=error", commands[-1])

    def test_default_application_graph_stays_independent(self):
        root = (ROOT / "CMakeLists.txt").read_text()
        self.assertNotIn("add_subdirectory(workbench", root)
        self.assertNotIn("tinyenv-workbench", root)
        component = (ROOT / "workbench/CMakeLists.txt").read_text()
        for unwanted in ("foundation::core", "RustComponent", "editor/model/", "editor/generate/", "install("):
            self.assertNotIn(unwanted, component)
        self.assertIn("foundation_finalize_build_policy NO_INSTALL", component)
        self.assertIn('"Build explicit local workbench tests" OFF', component)
        self.assertIn("TINYENV_RUNTIME_PATH", component)

    def test_discovery_blocks_network_transport(self):
        with offline_transports():
            with self.assertRaisesRegex(AssertionError, "prohibit real network"):
                socket.getaddrinfo("127.0.0.1", 1)
            with self.assertRaisesRegex(AssertionError, "prohibit real network"):
                urllib.request.urlopen("https://example.invalid/")


def discover_local_tests():
    with offline_transports():
        suite = unittest.defaultTestLoader.discover(str(ROOT / "workbench/tests"), pattern="test_*.py")
        result = unittest.TextTestRunner(verbosity=2).run(suite)
    if result.skipped:
        print("Incomplete workbench coverage: skipped cases are not passes", file=sys.stderr)
        return 1
    return 0 if result.wasSuccessful() and result.testsRun else 1


if __name__ == "__main__":
    if sys.argv[1:] == ["--discover"]:
        raise SystemExit(discover_local_tests())
    unittest.main()
