#!/usr/bin/env python3
"""Compile and run the actual exported Reset event, without writing its inputs."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def snapshot(paths):
    return {str(path): sha256(path) for path in paths if path.is_file()}


def compiler_path(value):
    path = shutil.which(value)
    if not path:
        raise RuntimeError("Existing compiler not found: " + value)
    return str(Path(path).resolve())


def check_work_tree(output):
    for path in output.rglob("*"):
        if path.is_symlink() and not path.resolve().is_relative_to(output):
            raise RuntimeError("Generated-work symlink escapes the work directory: " + str(path))


def main():
    own = Path(__file__).resolve().parent
    tutorial = own.parents[2]
    repository = tutorial.parent
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", type=Path,
                        default=tutorial / ".work/projects/simple-c")
    parser.add_argument("--foundation", type=Path, default=repository)
    parser.add_argument("--gui-include", type=Path,
                        help="Existing prepared GUI headers; otherwise restore retained inputs")
    parser.add_argument("--gui-input-group", type=Path,
                        help="Retained group; defaults to the repository's third_party/gui-inputs")
    parser.add_argument("--work-dir", type=Path, default=tutorial / ".work/event-check")
    parser.add_argument("--cc", default=os.environ.get("CC", "cc"))
    parser.add_argument("--cxx", default=os.environ.get("CXX", "c++"))
    args = parser.parse_args()
    project = args.project.resolve()
    foundation = args.foundation.resolve()
    output = args.work_dir.resolve()
    if output.is_relative_to(repository) and not output.is_relative_to(tutorial / ".work"):
        parser.error("Inside this repository, generated work must be under tutorial-video/.work")
    if foundation != repository and output.is_relative_to(foundation):
        parser.error("Keep generated work outside the selected read-only foundation checkout")
    if output == project or output.is_relative_to(project):
        parser.error("Keep generated check outputs separate from the captured project")
    output.mkdir(parents=True, exist_ok=True)
    check_work_tree(output)
    records = []
    captured_files = sorted(p for p in project.rglob("*") if p.is_file())
    initial_hashes = snapshot(captured_files)
    gui_include = args.gui_include.resolve() if args.gui_include else None
    source_files = sorted(p for topic in (foundation / "visual/ui", foundation / "visual/flow")
                          for p in topic.rglob("*") if p.is_file())
    source_hashes = snapshot(source_files)
    gui_files = []
    gui_hashes = {}
    probe = own / "reset_event_check.cpp"
    proof = {"success": False,
             "scope": "Actual captured generated forms/events and Reset handler, native display-free MemoryAdapter",
             "platform": platform.platform(), "machine": platform.machine(),
             "commands": records, "project_root": str(project),
             "foundation_root": str(foundation),
             "captured_source_sha256_before": initial_hashes,
             "foundation_visual_sha256_before": source_hashes,
             "check_source_sha256": sha256(probe),
             "check_script_sha256": sha256(Path(__file__).resolve())}

    def run(command, label):
        argv = [str(item) for item in command]
        result = subprocess.run(argv, capture_output=True, text=True)
        records.append({"label": label, "command": argv,
                        "exit_code": result.returncode,
                        "stdout": result.stdout, "stderr": result.stderr})
        print(f"{label}: {'PASS' if result.returncode == 0 else 'FAIL'}", flush=True)
        if result.returncode:
            print(result.stdout, end="")
            print(result.stderr, end="", file=sys.stderr)
            raise RuntimeError(label + " failed")
        return result.stdout

    cxx_flags = ["-std=c++20", "-Wall", "-Wextra", "-Wpedantic", "-pthread"]
    try:
        if not (project / "src/ui/i_button1_activate.hpp").is_file():
            raise RuntimeError("Fresh captured Reset handler is missing; run capture first")
        cc, cxx = compiler_path(args.cc), compiler_path(args.cxx)
        proof["c_compiler"] = run([cc, "--version"], "C compiler identity")
        proof["cxx_compiler"] = run([cxx, "--version"], "C++ compiler identity")
        if gui_include is None:
            group = (args.gui_input_group or foundation / "third_party/gui-inputs").resolve()
            bootstrap = output / "gui-bootstrap"
            bootstrap.mkdir(exist_ok=True)
            (bootstrap / "CMakeLists.txt").write_text(
                'cmake_minimum_required(VERSION 3.24)\n'
                'project(TutorialEventHeaders LANGUAGES CXX)\n'
                'find_package(Python3 REQUIRED COMPONENTS Interpreter)\n'
                'include("${FOUNDATION_POLICY_SOURCE_ROOT}/cmake/GuiInputs.cmake")\n'
                'foundation_gui_inputs()\nfoundation_gui_headers()\n', encoding="utf-8")
            gui_build = output / "gui-build"
            run(["cmake", "-S", bootstrap, "-B", gui_build, "-G", "Ninja",
                 f"-DFOUNDATION_POLICY_SOURCE_ROOT={foundation}",
                 f"-DFOUNDATION_GUI_INPUT_GROUP={group}", f"-DCMAKE_CXX_COMPILER={cxx}",
                 f"-DPython3_EXECUTABLE={sys.executable}"],
                "Restore and patch retained GUI headers")
            gui_include = gui_build / "include"
            proof["gui_input_group"] = str(group)
            proof["gui_input_sha256"] = snapshot(sorted(p for p in group.rglob("*") if p.is_file()))
        check_work_tree(output)
        if not (gui_include / "gui/memory_adapter.hpp").is_file():
            raise RuntimeError("Prepared GUI headers are missing gui/memory_adapter.hpp")
        gui_files = sorted(p for p in gui_include.rglob("*") if p.is_file())
        gui_hashes = snapshot(gui_files)
        proof["prepared_gui_include"] = str(gui_include)
        proof["prepared_gui_sha256_before"] = gui_hashes
        includes = ["-I", str(project), "-I", str(foundation), "-isystem", str(gui_include)]
        run([cxx, *cxx_flags, *includes, "-fsyntax-only", probe],
            "Actual exported binding syntax")
        sources = [project / "signal.c", project / "events.c",
                   project / "event_adapter.cpp", project / "flow_adapter.cpp",
                   foundation / "visual/ui/ui.cpp", foundation / "visual/flow/flow.cpp",
                   probe]
        objects = []
        for number, source in enumerate(sources):
            obj = output / f"input{number}.o"
            dependency = output / f"input{number}.d"
            if source.suffix == ".c":
                command = [cc, "-std=c17", "-Wall", "-Wextra", "-Wpedantic"]
            else:
                command = [cxx, *cxx_flags]
            run([*command, *includes, "-MMD", "-MF", dependency,
                 "-c", source, "-o", obj], "Compile " + source.name)
            objects.append(obj)
        binary = output / "reset-event-check"
        run([cxx, "-pthread", *objects, "-o", binary],
            "Link actual event and C implementation")
        actual = run([binary], "Dispatch generated Reset event")
        expected = ("Exported GUI bindings: 3\nbutton1 Activate: handled\n"
                    "C state: gain 2, count 0, samples cleared\n"
                    "Output: State reset. Choose a gain and run again.\n"
                    "Actual generated Reset event: PASS\n")
        if actual != expected:
            raise RuntimeError("Unexpected generated Reset event output")
        print(actual, end="", flush=True)
        (output / "output.txt").write_text(actual, encoding="utf-8")
        proof["stdout"] = actual
        proof["binary_sha256"] = sha256(binary)
        if initial_hashes != snapshot(captured_files):
            raise RuntimeError("Captured inputs changed during verification")
        print("Captured source hashes unchanged: PASS", flush=True)
        proof["success"] = True
    except (OSError, RuntimeError) as error:
        proof["error"] = str(error)
        print(str(error), file=sys.stderr)
    finally:
        check_work_tree(output)
        final_hashes = snapshot(sorted(p for p in project.rglob("*") if p.is_file()))
        final_source_hashes = snapshot(source_files)
        final_gui_hashes = snapshot(gui_files)
        proof.update({"captured_source_sha256_after": final_hashes,
                      "captured_sources_unchanged": initial_hashes == final_hashes,
                      "foundation_visual_sha256_after": final_source_hashes,
                      "foundation_visual_unchanged": source_hashes == final_source_hashes,
                      "prepared_gui_sha256_after": final_gui_hashes,
                      "prepared_gui_unchanged": gui_hashes == final_gui_hashes})
        if not (proof["captured_sources_unchanged"] and proof["foundation_visual_unchanged"]
                and proof["prepared_gui_unchanged"]):
            proof["success"] = False
            proof["error"] = "Check inputs changed during verification"
        (output / "verification.json").write_text(json.dumps(proof, indent=2) + "\n", encoding="utf-8")
    return 0 if proof["success"] else 1


if __name__ == "__main__":
    sys.exit(main())
