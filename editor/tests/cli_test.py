#!/usr/bin/env python3
"""Focused local CLI behavior checks; never part of application CI discovery."""

import json
from pathlib import Path
import subprocess
import sys
import tempfile


def main():
    if len(sys.argv) != 2:
        raise SystemExit("usage: cli_test.py /absolute/path/to/foundation-editor-tool")
    tool = Path(sys.argv[1]).resolve(strict=True)

    def invoke(*args, success=True):
        result = subprocess.run([str(tool), *map(str, args)], capture_output=True,
                                text=True, encoding="utf-8", timeout=10)
        if (result.returncode == 0) != success:
            raise AssertionError(f"unexpected status {result.returncode}: {args!r}\n"
                                 f"{result.stdout}{result.stderr}")
        return result

    def snapshot(root):
        return {str(path.relative_to(root)): (path.read_bytes(), path.stat().st_mtime_ns)
                for path in root.rglob("*") if path.is_file() and not path.is_symlink()}

    invoke("--help")
    invoke("bogus", success=False)
    with tempfile.TemporaryDirectory(prefix="foundation editor CLI ") as temporary:
        base = Path(temporary)
        project = base / "project with spaces café"
        project.mkdir()
        invoke("new", "--project", project)
        design = project / "design/project.json"
        document = json.loads(design.read_text(encoding="utf-8"))
        assert len(document["forms"]) == 1 and len(document["flows"]) == 1
        retained = snapshot(project)
        invoke("new", "--project", project, success=False)
        assert snapshot(project) == retained, "new changed an existing project"
        invoke("validate", "--root", project, "--project", "design/project.json")
        invoke("check-generated", "--project", design)
        invoke("generate", "--project", project)
        assert snapshot(project) == retained, "unchanged generation rewrote files"

        # Semantic edits made by an ordinary text editor are noticed without
        # modifying either the source design or retained output during a check.
        document["forms"][0]["label"] = "Edited outside the editor"
        design.write_text(json.dumps(document, ensure_ascii=False), encoding="utf-8")
        edited = snapshot(project)
        stale = invoke("check-generated", "--project", project, success=False)
        assert "differs" in stale.stderr
        assert snapshot(project) == edited, "freshness check wrote project files"
        invoke("generate", "--project", project)
        invoke("check-generated", "--project", project)

        # Changes to output location/namespace become retained project settings;
        # later operations need no repeated flags or editor executable at build.
        invoke("generate", "--project", project, "--output", "custom output",
               "--namespace", "demo::generated")
        configured = json.loads(design.read_text(encoding="utf-8"))
        assert configured["generated_directory"] == "custom output"
        assert configured["cpp_namespace"] == "demo::generated"
        invoke("check-generated", "--project", project)
        retained = snapshot(project)
        invoke("generate", "--project", project, "--output", "../escape", success=False)
        invoke("validate", "--root", project, "--project", "../outside.json", success=False)
        invoke("validate", "--project", project, "--project", design, success=False)
        assert snapshot(project) == retained, "invalid paths/options changed files"
        invoke("recover", "--project", project)
        assert snapshot(project) == retained, "empty recovery changed files"

        # An output directory containing handwritten files has no ownership
        # guard. Preflight refuses before publishing any generated output.
        foreign = base / "foreign"
        (foreign / "design").mkdir(parents=True)
        (foreign / "generated/visual").mkdir(parents=True)
        clean = dict(configured)
        clean["generated_directory"] = "generated/visual"
        (foreign / "design/project.json").write_text(json.dumps(clean), encoding="utf-8")
        (foreign / "generated/visual/forms.hpp").write_text("// Handwritten source\n", encoding="utf-8")
        untouched = snapshot(foreign)
        refused = invoke("generate", "--project", foreign, success=False)
        assert "ownership" in refused.stderr
        assert snapshot(foreign) == untouched, "generation replaced handwritten source"

        # Rooted path operations reject a symlink to another directory rather
        # than allowing generated output to escape the explicit project root.
        outside = base / "outside"
        outside.mkdir()
        sentinel = outside / "forms.hpp"
        sentinel.write_text("preserve me\n", encoding="utf-8")
        (project / "linked-output").symlink_to(outside, target_is_directory=True)
        invoke("generate", "--project", project, "--output", "linked-output", success=False)
        assert sentinel.read_text(encoding="utf-8") == "preserve me\n"
        assert not (outside / ".foundation-editor-owned.json").exists()

        original = design.read_bytes()
        design.write_text('{"schema_version":1,"schema_version":1}', encoding="utf-8")
        failed = invoke("validate", "--project", project, success=False)
        assert "error" in failed.stderr
        assert design.read_text(encoding="utf-8") == '{"schema_version":1,"schema_version":1}'
        design.write_bytes(original)
        invoke("new", "--project", base / "missing-root/design/project.json", success=False)
        assert not (base / "missing-root").exists()
    print("Editor CLI preservation, freshness and rooted-path checks passed")


if __name__ == "__main__":
    main()
