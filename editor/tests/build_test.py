#!/usr/bin/env python3
"""Local editor build isolation checks; intentionally absent from application tests."""
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("editor_build_test_subject", ROOT / "editor/build.py")
build = importlib.util.module_from_spec(spec)
spec.loader.exec_module(build)


class EditorBuildTests(unittest.TestCase):
    def test_dispatch_precedes_application_provider_selection(self):
        result = subprocess.run([sys.executable, "-B", str(ROOT / "tools/build.py"), "editor", "--help"],
                                cwd=ROOT, capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("--backend {fltk,rev,framebuffer}", result.stdout)
        self.assertNotIn("--core-provider", result.stdout)
        self.assertNotIn("--rust-sdk", result.stdout)
        self.assertNotIn("portable-package", result.stdout)

    def test_populated_application_or_unstamped_tree_rejected_without_writes(self):
        for stamped in (False, True):
            with self.subTest(stamped=stamped), tempfile.TemporaryDirectory() as temporary:
                tree = Path(temporary)
                (tree / "CMakeCache.txt").write_text("application cache fixture")
                if stamped:
                    (tree / "wrapper-identity.json").write_text(json.dumps({"component": "application"}))
                before = {p.name: p.read_bytes() for p in tree.iterdir()}
                with self.assertRaises(ValueError):
                    build.preflight(tree, {"component": "editor"})
                self.assertEqual({p.name: p.read_bytes() for p in tree.iterdir()}, before)

    def test_backend_operation_and_sdk_identity_changes_require_fresh_tree(self):
        identity = {"component": "editor", "backend": "fltk", "operation": "build", "sdk": None}
        with tempfile.TemporaryDirectory() as temporary:
            tree = Path(temporary)
            (tree / "wrapper-identity.json").write_text(json.dumps(identity))
            build.preflight(tree, identity)
            for key, changed in (("backend", "rev"), ("operation", "test"), ("sdk", "other")):
                with self.subTest(key=key), self.assertRaises(ValueError):
                    build.preflight(tree, {**identity, key: changed})

    def test_external_cmake_cache_modification_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            tree = Path(temporary)
            identity = {"component": "editor"}
            (tree / "wrapper-identity.json").write_text(json.dumps(identity))
            (tree / "CMakeCache.txt").write_text("fixture")
            cache = {"CMAKE_HOME_DIRECTORY": str(ROOT / "editor"), "compiler_file_sha256": "original"}
            (tree / "configured-identity.json").write_text(json.dumps(cache))
            with patch.object(build.application_build, "cache_identity", return_value=cache):
                build.preflight(tree, identity)
            with patch.object(build.application_build, "cache_identity", return_value={**cache, "compiler_file_sha256": "changed"}):
                with self.assertRaises(ValueError):
                    build.preflight(tree, identity)

    def test_default_application_graph_has_no_editor_target(self):
        root = (ROOT / "CMakeLists.txt").read_text()
        self.assertNotIn("add_subdirectory(editor", root)
        self.assertNotIn("foundation-editor", root)
        editor = (ROOT / "editor/CMakeLists.txt").read_text()
        self.assertNotIn("foundation::core", editor)
        self.assertNotIn("RustComponent", editor)
        self.assertNotIn("install(", editor)
        self.assertIn("foundation_finalize_build_policy NO_INSTALL", editor)
        self.assertIn('"Build explicit local editor tests" OFF', editor)


if __name__ == "__main__":
    unittest.main()
