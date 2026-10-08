"""Observable headless workbench CLI checks against the built executable."""

import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest


class WorkbenchCliTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        selected = os.environ.get("TINYENV_WORKBENCH_TOOL")
        if selected is None:
            raise unittest.SkipTest("TINYENV_WORKBENCH_TOOL is not set; CLI requires a built executable")
        if not selected:
            raise AssertionError("TINYENV_WORKBENCH_TOOL must name the built executable")
        try:
            cls.tool = Path(selected).resolve(strict=True)
        except OSError as error:
            raise AssertionError(f"TINYENV_WORKBENCH_TOOL does not name an existing executable: {selected}") from error
        if not cls.tool.is_file():
            raise AssertionError("TINYENV_WORKBENCH_TOOL is not a regular executable file")

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="tinyenv workbench CLI ")
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name)
        self.root = self.base / "project with spaces café"
        self.root.mkdir()

    def invoke(self, *args, success=True, cwd=None):
        result = subprocess.run(
            [str(self.tool), *map(str, args)], cwd=cwd or self.base,
            capture_output=True, text=True, encoding="utf-8", timeout=10,
        )
        self.assertEqual(result.returncode, 0 if success else 1,
                         f"unexpected status for {args!r}:\n{result.stdout}{result.stderr}")
        return result

    @staticmethod
    def snapshot(root):
        result = {}
        for path in root.rglob("*"):
            relative = path.relative_to(root).as_posix()
            if path.is_symlink():
                result[relative] = ("symlink", os.readlink(path))
            elif path.is_dir():
                result[relative] = ("directory",)
            else:
                result[relative] = ("file", path.read_bytes(), path.stat().st_mtime_ns)
        return result

    def test_help_and_strict_arguments(self):
        for args in [("--help",), ("-h",), ("inspect", "--help"), ("parse", "--help")]:
            with self.subTest(args=args):
                result = self.invoke(*args)
                self.assertIn("tinyenv-workbench-tool inspect --root PATH", result.stdout)
                self.assertIn("only read files", result.stdout)
                self.assertEqual(result.stderr, "")
        invalid = [
            (), ("bogus",), ("bogus", "--help"), ("inspect",), ("parse",),
            ("inspect", "--root"), ("inspect", "--root", ""),
            ("parse", "--file", "--help"), ("inspect", "--unknown"),
            ("inspect", "--root", self.root, "--root", self.root),
            ("parse", "--file", "flow.txt", "--file", "other.txt"),
            ("inspect", "--root", self.root, "--file", "flow.txt"),
            ("inspect", "--root", self.root, "extra"),
            ("--root", self.root, "inspect"), ("--help", "-h"),
        ]
        before = self.snapshot(self.root)
        for args in invalid:
            with self.subTest(args=args):
                result = self.invoke(*args, success=False)
                self.assertEqual(result.stdout, "")
                self.assertIn("tinyenv-workbench-tool:", result.stderr)
        self.assertEqual(self.snapshot(self.root), before)

    def test_inspect_lists_chats_and_root_entries_without_writing(self):
        (self.root / "notes").mkdir()
        (self.root / "notes/nested.chat.md").write_text("# Nested\n", encoding="utf-8")
        (self.root / "notes/reference.markdown").write_text("# Reference\n", encoding="utf-8")
        (self.root / "z.MD").write_text("# Last\n", encoding="utf-8")
        (self.root / "a café.CHAT.MD").write_text("# First\n", encoding="utf-8")
        (self.root / "README.md").write_text("# Documentation\n", encoding="utf-8")
        (self.root / "source.cpp").write_text("int answer = 42;\n", encoding="utf-8")
        (self.root / ".tinyenv").mkdir()
        (self.root / ".tinyenv/private.chat.md").write_text("private\n", encoding="utf-8")
        before = self.snapshot(self.root)
        first = self.invoke("inspect", "--root", self.root)
        second = self.invoke("inspect", "--root", self.root)
        self.assertEqual(first.stdout, second.stdout)
        self.assertEqual(first.stderr, "")
        document = json.loads(first.stdout)
        self.assertEqual(document["schema_version"], 1)
        self.assertEqual(document["root"], self.root.resolve().as_posix())
        self.assertEqual(document["chats"], ["a café.CHAT.MD", "notes/nested.chat.md"])
        entries = {entry["path"]: entry for entry in document["files"]}
        self.assertEqual(set(entries), {"notes", "z.MD", "a café.CHAT.MD", "README.md", "source.cpp"})
        self.assertNotIn(".tinyenv", entries)
        self.assertEqual(entries["a café.CHAT.MD"]["name"], "a café.CHAT.MD")
        self.assertEqual(entries["source.cpp"]["bytes"], len(b"int answer = 42;\n"))
        self.assertTrue(entries["notes"]["directory"])
        self.assertFalse(entries["source.cpp"]["directory"])
        self.assertFalse(entries["source.cpp"]["symlink"])
        self.assertEqual(self.snapshot(self.root), before)

    def test_parse_nested_program_and_graph_round_trip(self):
        source = (
            'repeat 2\nagent writer: Draft "café" response\nif supported\n'
            'critique reviewer: Check evidence\nelse\nagent researcher: Find evidence\n'
            'end\nuntil approved\nconclude: Done\n'
        )
        canonical = (
            'repeat 2\n  agent writer: Draft "café" response\n  if supported\n'
            '    critique reviewer: Check evidence\n  else\n    agent researcher: Find evidence\n'
            '  end\nuntil approved\nconclude: Done\n'
        )
        flow = self.root / "flow café.txt"
        flow.write_text(source, encoding="utf-8")
        before = self.snapshot(self.root)
        result = self.invoke("parse", "--root", self.root, "--file", flow.name)
        self.assertEqual(result.stderr, "")
        document = json.loads(result.stdout)
        self.assertEqual(document["file"], flow.name)
        self.assertEqual(document["canonical"], canonical)
        nodes = document["program"]["nodes"]
        self.assertEqual([node["kind"] for node in nodes], ["repeat", "conclude"])
        self.assertEqual(nodes[0]["iterations"], 2)
        self.assertEqual(nodes[0]["condition"], "approved")
        self.assertEqual(nodes[0]["children"][0]["text"], 'Draft "café" response')
        branch = nodes[0]["children"][1]
        self.assertEqual(branch["kind"], "if")
        self.assertEqual(branch["condition"], "supported")
        self.assertEqual(branch["children"][0]["role"], "reviewer")
        self.assertEqual(branch["otherwise"][0]["role"], "researcher")
        graph = document["graph"]
        ids = {node["id"] for node in graph["nodes"]}
        self.assertEqual(ids, set(range(1, 7)))
        self.assertTrue(any(edge["loop"] for edge in graph["edges"]))
        self.assertTrue(all(edge["from"] in ids and edge["to"] in ids for edge in graph["edges"]))
        self.assertGreater(graph["width"], 0)
        self.assertGreater(graph["height"], 0)
        self.assertEqual(self.snapshot(self.root), before)

        roundtrip = self.root / "canonical.txt"
        roundtrip.write_text(document["canonical"], encoding="utf-8")
        repeated = json.loads(self.invoke("parse", "--file", roundtrip).stdout)
        self.assertEqual(repeated["canonical"], canonical)
        self.assertEqual(repeated["program"], document["program"])
        self.assertEqual(repeated["graph"], document["graph"])

    def test_relative_file_and_absolute_file_inside_explicit_root(self):
        (self.root / "flows").mkdir()
        flow = self.root / "flows/one.txt"
        flow.write_text("agent writer: Answer\n", encoding="utf-8")
        results = [
            self.invoke("parse", "--root", self.root, "--file", "./flows/one.txt"),
            self.invoke("parse", "--root", self.root, "--file", flow),
        ]
        self.assertEqual(results[0].stdout, results[1].stdout)
        inferred = json.loads(self.invoke("parse", "--file", "flows/one.txt", cwd=self.root).stdout)
        self.assertEqual(inferred["root"], flow.parent.resolve().as_posix())
        self.assertEqual(inferred["file"], "one.txt")

    def test_empty_program(self):
        flow = self.root / "empty.txt"
        flow.write_text("# No steps yet\n\n", encoding="utf-8")
        document = json.loads(self.invoke("parse", "--file", flow).stdout)
        self.assertEqual(document["canonical"], "")
        self.assertEqual(document["program"], {"nodes": []})
        self.assertEqual(document["graph"], {"width": 0, "height": 0, "nodes": [], "edges": []})

    def test_crlf_and_role_whitespace_canonicalize(self):
        flow = self.root / "windows-lines.txt"
        flow.write_bytes(b"agent \twriter  : Answer\r\ncritique  reviewer\t: Check evidence\r\n")
        before = self.snapshot(self.root)
        document = json.loads(self.invoke("parse", "--file", flow).stdout)
        self.assertEqual(document["canonical"], "agent writer: Answer\ncritique reviewer: Check evidence\n")
        self.assertEqual([node["role"] for node in document["program"]["nodes"]], ["writer", "reviewer"])
        self.assertEqual(self.snapshot(self.root), before)

    def test_syntax_diagnostics_and_source_preservation(self):
        flow = self.root / "invalid.txt"
        flow.write_text("agent writer: Good first step\nnot a command\n", encoding="utf-8")
        before = self.snapshot(self.root)
        result = self.invoke("parse", "--file", flow, success=False)
        self.assertEqual(result.stdout, "")
        self.assertIn(f"{flow.as_posix()}:2:1: error:", result.stderr)
        self.assertEqual(self.snapshot(self.root), before)

    def test_file_failures_and_root_boundaries_preserve_files(self):
        (self.root / "invalid-encoding.txt").write_bytes(b"agent writer: \xff\n")
        outside = self.base / "outside.txt"
        outside.write_text("agent writer: Outside\n", encoding="utf-8")
        before = self.snapshot(self.base)
        invalid = [
            ("parse", "--root", self.root, "--file", "missing.txt"),
            ("parse", "--root", self.root, "--file", "invalid-encoding.txt"),
            ("parse", "--root", self.root, "--file", self.root),
            ("parse", "--root", self.root, "--file", "../outside.txt"),
            ("parse", "--root", self.root, "--file", outside),
            ("inspect", "--root", self.base / "missing-root"),
            ("parse", "--file", self.base / "missing-root/flow.txt"),
        ]
        for args in invalid:
            with self.subTest(args=args):
                result = self.invoke(*args, success=False)
                self.assertEqual(result.stdout, "")
                self.assertTrue(result.stderr)
        self.assertEqual(self.snapshot(self.base), before)
        self.assertFalse((self.base / "missing-root").exists())

    def test_symlink_files_and_parent_directories_are_rejected(self):
        outside = self.base / "outside"
        outside.mkdir()
        flow = outside / "flow.txt"
        flow.write_text("agent writer: Outside\n", encoding="utf-8")
        try:
            (self.root / "linked.txt").symlink_to(flow)
            (self.root / "linked-directory").symlink_to(outside, target_is_directory=True)
        except OSError as error:
            self.skipTest(f"symlinks are unavailable: {error}")
        before = self.snapshot(self.base)
        for selected in ["linked.txt", "linked-directory/flow.txt"]:
            with self.subTest(file=selected):
                result = self.invoke("parse", "--root", self.root, "--file", selected, success=False)
                self.assertEqual(result.stdout, "")
        inspected = json.loads(self.invoke("inspect", "--root", self.root).stdout)
        entries = {entry["path"]: entry for entry in inspected["files"]}
        self.assertTrue(entries["linked.txt"]["symlink"])
        self.assertTrue(entries["linked-directory"]["symlink"])
        self.assertEqual(inspected["chats"], [])
        self.assertEqual(self.snapshot(self.base), before)

    @unittest.skipIf(os.name == "nt", "Windows argv does not accept arbitrary byte arguments")
    def test_invalid_utf8_argv_is_rejected_even_with_help(self):
        for args in [(b"--help", b"\xff"), (b"parse", b"--file", b"\xff")]:
            with self.subTest(args=args):
                result = subprocess.run([os.fsencode(self.tool), *args], cwd=self.base,
                                        capture_output=True, timeout=10)
                self.assertEqual(result.returncode, 1)
                self.assertEqual(result.stdout, b"")
                self.assertIn(b"Arguments must be valid UTF-8", result.stderr)

    @unittest.skipIf(os.name == "nt", "Windows forbids these filename characters")
    def test_json_escapes_path_control_characters(self):
        name = 'quote"line\n\t.chat.md'
        (self.root / name).write_text("# Chat\n", encoding="utf-8")
        result = self.invoke("inspect", "--root", self.root)
        document = json.loads(result.stdout)
        self.assertEqual(document["chats"], [name])
        self.assertEqual(document["files"][0]["name"], name)
        self.assertEqual(result.stdout.count("\n"), 1)

    @unittest.skipUnless(Path("/dev/full").exists(), "requires the /dev/full failing output device")
    def test_failed_output_returns_failure(self):
        with Path("/dev/full").open("wb") as output:
            result = subprocess.run([str(self.tool), "inspect", "--root", str(self.root)],
                                    cwd=self.base, stdout=output, stderr=subprocess.PIPE,
                                    text=True, encoding="utf-8", timeout=10)
        self.assertEqual(result.returncode, 1)
        self.assertIn("Cannot write standard output", result.stderr)


if __name__ == "__main__":
    unittest.main()
