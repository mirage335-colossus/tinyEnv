#!/usr/bin/env python3
"""Produce checked, real console output for the tutorial's small examples."""

import argparse
import datetime
import difflib
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess
import sys


EXAMPLES = Path(__file__).resolve().parent
TUTORIAL = EXAMPLES.parent
REPOSITORY = TUTORIAL.parent
SOURCE_PATH = Path("editor/examples/simple-c/signal.c")
ORIGINAL_RETURN = "    return sample * gain;"
CHANGED_RETURN = "    return sample * gain + 1.0f;"


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def command(args, records, label, expected_exit=0):
    result = subprocess.run([str(item) for item in args], capture_output=True,
                            text=True, check=False)
    records.append({"label": label, "command": [str(item) for item in args],
                    "exit_code": result.returncode, "expected_exit_code": expected_exit,
                    "stdout": result.stdout,
                    "stderr": result.stderr})
    if result.returncode != expected_exit:
        raise RuntimeError(f"{label} failed ({result.returncode})\n"
                           f"{result.stdout}{result.stderr}")
    return result.stdout


def compiler_path(value):
    resolved = shutil.which(str(value))
    if not resolved:
        raise RuntimeError(f"Existing compiler not found: {value}")
    return str(Path(resolved).resolve())


def environment():
    return {"platform": platform.platform(), "machine": platform.machine(),
            "python": platform.python_version(),
            "created_utc": datetime.datetime.now(datetime.timezone.utc).isoformat()}


def check_algorithm(args):
    work = args.work_dir / "algorithm"
    work.mkdir(parents=True, exist_ok=True)
    source = REPOSITORY / SOURCE_PATH
    header = source.with_suffix(".h")
    driver = EXAMPLES / "algorithm-walkthrough/driver.c"
    patch = EXAMPLES / "algorithm-walkthrough/add_offset.patch"
    original = source.read_text(encoding="utf-8")
    hashes_before = {str(path.relative_to(REPOSITORY)): sha256(path)
                     for path in (source, header)}
    proof = {"success": False, "scope": "Native copied-source C17 algorithm check",
             "environment": environment(), "commands": [],
             "repository_source_sha256_before": hashes_before,
             "production_resource_sha256": {
                 str(path.relative_to(TUTORIAL)): sha256(path)
                 for path in (driver, patch, Path(__file__).resolve())},
             "source_path": str(SOURCE_PATH), "function": "simple_c_apply_gain"}
    try:
        expected_function = ("float simple_c_apply_gain(float sample, float gain) {\n"
                             + ORIGINAL_RETURN + "\n}")
        if original.count(expected_function) != 1 or original.count(ORIGINAL_RETURN) != 1:
            raise RuntimeError("Source changed: review the retained one-line demonstration")
        changed = original.replace(ORIGINAL_RETURN, CHANGED_RETURN, 1)
        line = original.splitlines().index(ORIGINAL_RETURN) + 1
        proof["edit_line"] = line
        proof["before_line"] = ORIGINAL_RETURN
        proof["after_line"] = CHANGED_RETURN
        proof["unified_diff"] = "".join(difflib.unified_diff(
            original.splitlines(keepends=True), changed.splitlines(keepends=True),
            fromfile="a/signal.c", tofile="b/signal.c"))
        if proof["unified_diff"] != patch.read_text(encoding="utf-8"):
            raise RuntimeError("Retained patch differs from the actual one-line edit")
        cc = compiler_path(args.cc)
        proof["compiler"] = command([cc, "--version"], proof["commands"], "C compiler identity")
        proof["runs"] = {}
        for label, text, offset, expected in (
                ("before", original, "0", [2, 4, 6, 8]),
                ("after", changed, "1", [3, 5, 7, 9])):
            copied = work / label
            copied.mkdir(exist_ok=True)
            (copied / "signal.c").write_text(text, encoding="utf-8")
            shutil.copyfile(header, copied / "signal.h")
            shutil.copyfile(driver, copied / "driver.c")
            binary = copied / "algorithm-check"
            command([cc, "-std=c17", "-Wall", "-Wextra", "-Wpedantic", "-Werror",
                     "-O2", copied / "signal.c", copied / "driver.c", "-lm",
                     "-o", binary], proof["commands"], f"Compile {label} C algorithm")
            stdout = command([binary, offset], proof["commands"], f"Run {label} C algorithm")
            match = re.search(r"^Outputs: \[([0-9, ]+)\]$", stdout, flags=re.MULTILINE)
            actual = [int(item.strip()) for item in match.group(1).split(",")] if match else []
            expected_stdout = ("Inputs: [1, 2, 3, 4]\nGain: 2\nOutputs: ["
                               + ", ".join(str(item) for item in expected)
                               + "]\nAlgorithm check: PASS\n")
            if actual != expected or stdout != expected_stdout:
                raise RuntimeError(f"Unexpected {label} console output: {stdout!r}")
            command([binary, "1" if label == "before" else "0"], proof["commands"],
                    f"Reject incorrect {label} output expectation", expected_exit=1)
            proof["runs"][label] = {"inputs": [1, 2, 3, 4], "gain": 2,
                                     "actual_outputs": actual, "expected_outputs": expected,
                                     "stdout": stdout, "binary_sha256": sha256(binary),
                                     "source_sha256": {path.name: sha256(path) for path in
                                                       (copied / "signal.c", copied / "signal.h",
                                                        copied / "driver.c")}}
            (work / f"{label}-output.txt").write_text(stdout, encoding="utf-8")
            print(f"{label.capitalize()} algorithm:\n{stdout}", end="", flush=True)
        if proof["runs"]["before"]["actual_outputs"] == proof["runs"]["after"]["actual_outputs"]:
            raise RuntimeError("Algorithm edit did not change the result")
        proof["success"] = True
    finally:
        hashes_after = {str(path.relative_to(REPOSITORY)): sha256(path)
                        for path in (source, header)}
        proof["repository_source_sha256_after"] = hashes_after
        proof["repository_sources_unchanged"] = hashes_before == hashes_after
        if hashes_before != hashes_after:
            proof["success"] = False
        write_json(work / "verification.json", proof)
    if not proof["success"]:
        raise RuntimeError("Repository source changed during the algorithm check")
    return proof


def check_language(args):
    work = args.work_dir / "language-integration"
    work.mkdir(parents=True, exist_ok=True)
    source = EXAMPLES / "language-integration"
    source_paths = sorted(path for path in source.rglob("*") if path.is_file()
                          and "event-check" not in path.relative_to(source).parts
                          and (path.suffix in {".c", ".cpp", ".h", ".hpp", ".rs"}
                               or path.name == "CMakeLists.txt"))
    hashes_before = {str(path.relative_to(source)): sha256(path) for path in source_paths}
    proof = {"success": False, "scope": "Native C17/C++20/Rust console integration",
             "environment": environment(), "commands": [],
             "source_sha256_before": hashes_before}
    try:
        cc, cxx = compiler_path(args.cc), compiler_path(args.cxx)
        rustc = compiler_path(args.rustc or "rustc")
        for label, compiler in (("C", cc), ("C++", cxx), ("Rust", rustc)):
            proof[label.lower().replace("+", "x") + "_compiler"] = command(
                [compiler, "--version"], proof["commands"], f"{label} compiler identity")
        build = work / "build"
        command(["cmake", "-S", source, "-B", build, "-G", "Ninja",
                 "-DCMAKE_BUILD_TYPE=Release", f"-DCMAKE_C_COMPILER={cc}",
                 f"-DCMAKE_CXX_COMPILER={cxx}", f"-DTUTORIAL_RUSTC={rustc}"],
                proof["commands"], "Configure language integration")
        command(["cmake", "--build", build, "--parallel", "2"], proof["commands"],
                "Build language integration")
        binary = build / ("tutorial-integration.exe" if os.name == "nt" else "tutorial-integration")
        stdout = command([binary], proof["commands"], "Run language integration")
        expected = ("Run 1: 2.000\nRun 2: 3.000\n"
                    "C17 helper, C++20 handler, and Rust modules linked: PASS\n")
        if stdout != expected:
            raise RuntimeError(f"Unexpected integration console output: {stdout!r}")
        command(["ctest", "--test-dir", build, "--output-on-failure", "--no-tests=error"],
                proof["commands"], "CTest language integration")
        proof["stdout"] = stdout
        proof["binary_sha256"] = sha256(binary)
        (work / "output.txt").write_text(stdout, encoding="utf-8")
        print(f"Language integration:\n{stdout}", end="", flush=True)
        proof["success"] = True
    finally:
        hashes_after = {str(path.relative_to(source)): sha256(path) for path in source_paths}
        proof["source_sha256_after"] = hashes_after
        proof["sources_unchanged"] = hashes_before == hashes_after
        if hashes_before != hashes_after:
            proof["success"] = False
        write_json(work / "verification.json", proof)
    if not proof["success"]:
        raise RuntimeError("Language integration inputs changed during the check")
    return proof


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--only", choices=("all", "algorithm", "language"), default="all")
    parser.add_argument("--work-dir", type=Path, default=TUTORIAL / ".work/examples")
    parser.add_argument("--cc", default=os.environ.get("CC", "cc"))
    parser.add_argument("--cxx", default=os.environ.get("CXX", "c++"))
    parser.add_argument("--rustc", help="Path to an existing native Rust compiler; downloads nothing")
    args = parser.parse_args()
    args.work_dir = args.work_dir.resolve()
    if args.work_dir.is_relative_to(REPOSITORY) and not args.work_dir.is_relative_to(TUTORIAL / ".work"):
        parser.error("Inside this repository, generated work must be under tutorial-video/.work")
    summary = {"success": False, "checks": {}, "environment": environment()}
    try:
        if args.only in ("all", "algorithm"):
            check_algorithm(args)
            summary["checks"]["algorithm"] = "algorithm/verification.json"
        if args.only in ("all", "language"):
            check_language(args)
            summary["checks"]["language-integration"] = "language-integration/verification.json"
        summary["success"] = True
    except (OSError, RuntimeError) as error:
        summary["error"] = str(error)
        print(str(error), file=sys.stderr)
    finally:
        write_json(args.work_dir / "verification.json", summary)
    return 0 if summary["success"] else 1


if __name__ == "__main__":
    sys.exit(main())
