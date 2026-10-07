#!/usr/bin/env python3
"""Build an external consumer after relocating the installed prefix."""
import argparse
from pathlib import Path
import os
import shutil
import subprocess
import tempfile
import sys
import json

parser = argparse.ArgumentParser()
parser.add_argument("--build", type=Path, required=True)
parser.add_argument("--source", type=Path, required=True)
parser.add_argument("--config", required=True)
parser.add_argument("--sdk", type=Path)
args = parser.parse_args()
sys.path.insert(0, str(args.source / "tools"))
from build import host_programs, sdk_identity
import windows_compiler
programs = host_programs(args.sdk)
sdk_before = sdk_identity(args.sdk) if args.sdk else None
environment = os.environ.copy()
browser_sdk = bool(args.sdk and json.loads((args.sdk / "sdk.json").read_text())["target"]["system"] == "Emscripten")
if args.sdk:
    environment["PYTHONDONTWRITEBYTECODE"] = "1"


def run(command, **kwargs):
    compiler = command[0] == "cmake"
    if compiler:
        command[0] = programs["cmake"]
    command = [str(part) for part in command]
    selected_environment = kwargs.pop("env", environment)
    if compiler:
        windows_compiler.run(command, env=selected_environment, **kwargs)
    else:
        subprocess.run(command, check=True, env=selected_environment, **kwargs)


with windows_compiler.workspace(prefix="foundation install ") as directory:
    root = Path(directory)
    original = root / "original prefix"
    moved = root / "relocated prefix"
    run(["cmake", "--install", args.build, "--config", args.config, "--prefix", original])
    original.rename(moved)
    for section, name in (("man1", "foundation-cli.1"), ("man7", "software-foundation.7")):
        copies = list(moved.rglob(section + "/" + name))
        if len(copies) != 1 or copies[0].read_bytes() != (args.source / "docs/man" / name).read_bytes():
            raise RuntimeError("installed manual missing, duplicated or changed: " + name)
    # Build only against the install, without access to its original location.
    consumer = root / "consumer source"
    shutil.copytree(args.source / "examples/consumer", consumer)
    configs = list(moved.rglob("FoundationConfig.cmake"))
    if len(configs) != 1:
        raise RuntimeError("installed package configuration missing or ambiguous")
    for configuration in configs[0].parent.glob("*.cmake"):
        text = configuration.read_text(encoding="utf-8")
        if str(args.build.resolve()) in text:
            raise RuntimeError("installed CMake package retains a build-tree path: " + configuration.name)
        if args.sdk and str(args.sdk.resolve()) in text:
            raise RuntimeError("installed CMake package retains an SDK path: " + configuration.name)
    extra = []
    if args.sdk:
        extra = ["-DCMAKE_TOOLCHAIN_FILE=" + str(args.source / "cmake/toolchains/sdk.cmake"),
                 "-DFOUNDATION_SDK_ROOT=" + str(args.sdk.resolve())]
        if programs["ninja"] != "ninja":
            extra += ["-DCMAKE_MAKE_PROGRAM=" + programs["ninja"]]
    poison = root / "unavailable rust tools"
    poison.mkdir()
    attempted = root / "rust tool invocation"
    for tool in ("cargo", "rustc", "rustup"):
        if os.name == "nt":
            launcher = poison / (tool + ".cmd")
            launcher.write_text('@echo off\necho attempted>>"%FOUNDATION_RUST_TOOL_ATTEMPT%"\nexit /b 89\n')
        else:
            launcher = poison / tool
            launcher.write_text('#!/bin/sh\nprintf "%s\\n" "$0" >> "$FOUNDATION_RUST_TOOL_ATTEMPT"\nexit 89\n')
            launcher.chmod(0o755)
    consumer_environment = dict(environment)
    consumer_environment["PATH"] = str(poison) + os.pathsep + consumer_environment.get("PATH", "")
    consumer_environment["FOUNDATION_RUST_TOOL_ATTEMPT"] = str(attempted)
    run(["cmake", "-S", consumer, "-B", root / "consumer build", "-G", "Ninja",
         "-DCMAKE_BUILD_TYPE=" + args.config, "-DFoundation_DIR=" + str(configs[0].parent),
         "-DCMAKE_FIND_USE_PACKAGE_REGISTRY=OFF", "-DCMAKE_FIND_USE_SYSTEM_PACKAGE_REGISTRY=OFF", *extra],
        env=consumer_environment)
    run(["cmake", "--build", root / "consumer build", "--parallel", "2"], env=consumer_environment)
    suffix = ".js" if browser_sdk else (".exe" if __import__("os").name == "nt" else "")
    executor = [args.sdk / "node/bin/node"] if browser_sdk else []
    run([*executor, root / "consumer build" / ("consumer" + suffix)], env=consumer_environment)
    if attempted.exists():
        raise RuntimeError("installed C++ consumer invoked a Rust tool")
    clean = {key: value for key, value in os.environ.items() if key not in
             ("LD_LIBRARY_PATH", "LD_PRELOAD", "DYLD_LIBRARY_PATH", "DYLD_INSERT_LIBRARIES")}
    run([*executor, moved / "bin" / ("foundation-cli" + suffix), "--self-check"], cwd=moved, env=clean)
    if args.sdk and sdk_identity(args.sdk) != sdk_before:
        raise ValueError("SDK changed while checking its installed consumer")
