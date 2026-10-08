"""Private workbench state must not enter source snapshots, with or without Git."""
import importlib.util
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
import source_identity


class PrivateStateTests(unittest.TestCase):
    def test_private_state_is_excluded_at_any_depth(self):
        for name in (".tinyenv/chat.state.json", "project/.tinyenv/job/request.json",
                     "project/.tinyenv/prompts.json"):
            with self.subTest(name=name):
                self.assertTrue(source_identity.ignored_source_path(name))
        self.assertFalse(source_identity.ignored_source_path("workbench/core/workspace.cpp"))

    def test_export_without_git_never_reads_private_state(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "main.cpp").write_text("int main() {}\n", encoding="utf-8")
            private = root / "nested" / ".tinyenv"
            private.mkdir(parents=True)
            (private / "chat.state.json").write_text("private draft\n", encoding="utf-8")
            (private / "request.json").write_text("private request\n", encoding="utf-8")
            self.assertEqual(set(source_identity.selected_files(root)), {"main.cpp"})


if __name__ == "__main__":
    unittest.main()
