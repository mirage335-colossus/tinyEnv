#!/usr/bin/env python3
"""Build the native AI workbench in an isolated tree, using retained inputs."""
import argparse
import hashlib
import importlib.util
import json
import os
import shutil
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "tools") not in sys.path:
    sys.path.insert(0, str(ROOT / "tools"))
import build as application_build
from sdk_environment import require_clean


def read_stamp(path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise ValueError("Invalid workbench build identity; use a fresh build tree") from error


def preflight(build, identity):
    """Reject application/foreign trees before restoring inputs or configuring."""
    stamp = build / "wrapper-identity.json"
    cache = build / "CMakeCache.txt"
    if build.exists() and not stamp.exists() and any(build.iterdir()):
        raise ValueError("Refusing nonempty foreign tree; use a fresh workbench build directory")
    if cache.exists() and not stamp.exists():
        raise ValueError("Refusing populated unstamped tree; use a fresh workbench build directory")
    if stamp.exists() and read_stamp(stamp) != identity:
        raise ValueError("Workbench component/backend/toolchain/configuration changed; use a fresh workbench build tree")
    configured = build / "configured-identity.json"
    if configured.exists() and (not cache.exists() or read_stamp(configured) != application_build.cache_identity(build)):
        raise ValueError("Workbench compiler/options changed outside the wrapper; use a fresh tree")
    if cache.exists():
        entries = application_build.cache_identity(build)
        if entries.get("CMAKE_HOME_DIRECTORY") != str(ROOT / "workbench"):
            raise ValueError("Application and workbench build trees must remain separate")
    if build == ROOT or build == ROOT / "workbench":
        raise ValueError("Use an out-of-source workbench build directory")


def selected_programs(sdk=None):
    """Bind both build tools and runtime interpreter to exact existing bytes."""
    programs = application_build.host_programs(sdk)
    programs.pop("cpack", None)
    programs.setdefault("python", sys.executable)
    selected = {}
    for name, executable in programs.items():
        located = shutil.which(executable)
        if not located:
            raise ValueError("Required workbench tool is unavailable: " + name)
        path = Path(located).resolve(strict=True)
        if not path.is_file():
            raise ValueError("Required workbench tool is not a regular file: " + name)
        selected[name] = str(path)
    return selected


def input_group():
    spec = importlib.util.spec_from_file_location("foundation_workbench_gui_inputs", ROOT / "gui/source_group.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def identity_for(args, build, programs):
    identity = {
        "component": "workbench", "operation": args.action, "preset": args.preset,
        "backend": args.backend, "native_host": not args.headless,
        "sdk": None, "dependency_prefix": None, "gui_group": None, "gui_source": None,
        "programs": programs, "program_hashes": {name: hashlib.sha256(Path(path).read_bytes()).hexdigest() for name, path in programs.items()},
        "environment": {key: os.environ.get(key) for key in
            ("CC", "CXX", "CFLAGS", "CXXFLAGS", "LDFLAGS", "CMAKE_GENERATOR", "CMAKE_PREFIX_PATH", "PKG_CONFIG_PATH")},
    }
    if args.sdk:
        sdk = args.sdk.resolve(strict=True)
        require_clean()
        identity["sdk"] = {"root": str(sdk), "sha256": application_build.sdk_identity(sdk)}
        metadata = json.loads((sdk / "sdk.json").read_text(encoding="utf-8"))
        if metadata["target"]["system"] != "Linux":
            raise ValueError("The workbench requires a native SDK; browser/Wasm SDKs are not workbench inputs")
    if args.dependency_prefix:
        from prepare_dependencies import verify
        prefix = args.dependency_prefix.resolve(strict=True)
        identity["dependency_prefix"] = {"root": str(prefix), **verify(prefix)}
    if args.gui_source:
        source = args.gui_source.resolve(strict=True)
        # Every locked input is rechecked by shared CMake before compilation.
        lock_path = ROOT / "third_party/gui-boundary.lock.json"
        lock = json.loads(lock_path.read_text(encoding="utf-8"))
        for name, expected in lock["files"].items():
            actual = hashlib.sha256((source / name).read_bytes()).hexdigest()
            if actual != expected:
                raise ValueError("Pinned GUI input differs: " + name)
        identity["gui_source"] = {"root": str(source), "lock_sha256": hashlib.sha256(lock_path.read_bytes()).hexdigest()}
    else:
        group = (args.gui_input_group or ROOT / "third_party/gui-inputs").resolve(strict=True)
        module = input_group()
        verified = module.receipt(group, module.verify(group))
        identity["gui_group"] = {"root": str(group), "sha256": verified["group_sha256"]}
    return identity


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", nargs="?", choices=("build", "test"), default="build")
    parser.add_argument("preset", nargs="?", choices=("dev", "release", "asan"), default="dev")
    parser.add_argument("--backend", choices=("fltk", "rev", "framebuffer"), default="fltk")
    parser.add_argument("--build-dir", type=Path)
    parser.add_argument("--sdk", type=Path, help="existing verified native C++ SDK; no Rust extension needed")
    parser.add_argument("--dependency-prefix", type=Path, help="existing verified native development prefix")
    selection = parser.add_mutually_exclusive_group()
    selection.add_argument("--gui-source", type=Path)
    selection.add_argument("--gui-input-group", type=Path)
    parser.add_argument("--headless", action="store_true", help="build the shared UI, CLI and local tests without a native window")
    parser.add_argument("--configure-only", action="store_true")
    parser.add_argument("--jobs", type=application_build.positive)
    parser.add_argument("--build-jobs", type=application_build.positive)
    parser.add_argument("--test-jobs", type=application_build.positive)
    args = parser.parse_args(argv)
    if args.configure_only and args.action != "build":
        parser.error("--configure-only applies only to build")
    if args.sdk and args.dependency_prefix:
        parser.error("--sdk and --dependency-prefix are mutually exclusive")
    try:
        execute(args)
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        print("workbench build: " + str(error), file=sys.stderr)
        return 1
    return 0


def execute(args):
    suffix = "-sdk" if args.sdk else ""
    suffix += "-headless" if args.headless else ""
    suffix += "-tests" if args.action == "test" else ""
    build = (args.build_dir or ROOT / "build" / ("workbench-" + args.backend + "-" + args.preset + suffix)).resolve()
    programs = selected_programs(args.sdk.resolve(strict=True) if args.sdk else None)
    identity = identity_for(args, build, programs)
    preflight(build, identity)
    build.mkdir(parents=True, exist_ok=True)
    # Failed configurations remain bound to their exact selected inputs.
    (build / "wrapper-identity.json").write_text(json.dumps(identity, indent=2) + "\n", encoding="utf-8")
    command = [programs["cmake"], "-S", str(ROOT / "workbench"), "-B", str(build), "-G", "Ninja",
        "-DCMAKE_BUILD_TYPE=" + ("Release" if args.preset == "release" else "Debug"),
        "-DTINYENV_WORKBENCH_BACKEND=" + args.backend,
        "-DTINYENV_WORKBENCH_BUILD_HOST=" + ("OFF" if args.headless else "ON"),
        "-DTINYENV_WORKBENCH_TESTS=" + ("ON" if args.action == "test" else "OFF"),
        "-DFOUNDATION_SANITIZERS=" + ("ON" if args.preset == "asan" else "OFF"),
        "-DPython3_EXECUTABLE=" + programs["python"],
        "-DCMAKE_MAKE_PROGRAM=" + programs["ninja"]]
    if args.gui_source:
        command += ["-DFOUNDATION_GUI_SOURCE=" + str(args.gui_source.resolve()), "-DFOUNDATION_GUI_INPUT_GROUP="]
    else:
        group = (args.gui_input_group or ROOT / "third_party/gui-inputs").resolve()
        command += ["-DFOUNDATION_GUI_INPUT_GROUP=" + str(group), "-DFOUNDATION_GUI_SOURCE="]
    if args.sdk:
        command += ["-DCMAKE_TOOLCHAIN_FILE=" + str(ROOT / "cmake/toolchains/sdk.cmake"),
                    "-DFOUNDATION_SDK_ROOT=" + str(args.sdk.resolve())]
    if args.dependency_prefix:
        command += ["-DFOUNDATION_DEPENDENCY_PREFIX=" + str(args.dependency_prefix.resolve())]
    environment = os.environ.copy()
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    application_build.run(command, env=environment)
    cache = application_build.cache_identity(build)
    (build / "configured-identity.json").write_text(json.dumps(cache, indent=2) + "\n", encoding="utf-8")
    jobs, test_jobs = application_build.job_limits(args)
    if not args.configure_only:
        application_build.run([programs["cmake"], "--build", str(build), "--parallel", str(jobs)], env=environment)
        if args.action == "test":
            application_build.run([programs["ctest"], "--test-dir", str(build), "--output-on-failure",
                                   "--no-tests=error", "--parallel", str(test_jobs)], env=environment)
    if identity_for(args, build, programs) != identity:
        raise ValueError("Workbench selected input identity changed during operation")
    if application_build.cache_identity(build) != cache:
        raise ValueError("Workbench configured compiler/options changed during operation")


if __name__ == "__main__":
    raise SystemExit(main())
