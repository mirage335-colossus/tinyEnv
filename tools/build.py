#!/usr/bin/env python3
"""One incremental build entry point; never installs or downloads dependencies."""
import argparse
import hashlib
import json
import os
import re
from pathlib import Path
import subprocess
import sys
import time

import windows_compiler
from sdk_environment import require_clean

ROOT = Path(__file__).resolve().parents[1]


def positive(value):
    value = int(value)
    if value < 1:
        raise argparse.ArgumentTypeError("jobs must be positive")
    return value


def default_jobs():
    from build_capacity import default_jobs as capacity
    return capacity()


def job_limits(args):
    from build_capacity import compile_jobs, test_jobs
    environment = os.environ.get("CMAKE_BUILD_PARALLEL_LEVEL")
    build = args.build_jobs or args.jobs or (compile_jobs(environment) if environment else default_jobs())
    test_environment = os.environ.get("CTEST_PARALLEL_LEVEL")
    tests = args.test_jobs or args.jobs or test_jobs(test_environment)
    return build, tests


def contained(root, relative):
    root = Path(root).resolve(strict=True)
    path = Path(relative)
    if path.is_absolute() or ".." in path.parts or not path.parts:
        raise ValueError("SDK paths must be nonempty relative paths")
    resolved = (root / path).resolve(strict=True)
    if root != resolved and root not in resolved.parents:
        raise ValueError("SDK path escapes its root")
    return resolved


def sdk_identity(root):
    # Share one SDK contract with direct CMake and release consumers.
    tools = str(Path(__file__).resolve().parent)
    if tools not in sys.path:
        sys.path.insert(0, tools)
    from sdk_manifest import verify_sdk
    return verify_sdk(root)


def rust_sdk_identity(root, cpp_sdk=None):
    import platform
    from rust_sdk import verify_rust_sdk
    metadata = verify_rust_sdk(root, cpp_sdk=cpp_sdk, execute=True)
    if cpp_sdk is None:
        machine = {'AMD64': 'x86_64', 'amd64': 'x86_64', 'arm64': 'aarch64', 'ARM64': 'aarch64'}.get(
            platform.machine(), platform.machine())
        if metadata['target']['system'] != platform.system() or metadata['target']['processor'] != machine:
            raise ValueError("Rust SDK target requires its matching prepared C++ SDK")
    return hashlib.sha256((root / "rust-sdk.json").read_bytes()).hexdigest()


def native_rust_identity():
    from rust_build import native_tool_identity, select_native_tools
    try:
        selected = select_native_tools()
        return selected, native_tool_identity(selected["cargo"], selected["rustc"])
    except (OSError, ValueError) as error:
        raise ValueError("Rust tools are unavailable or invalid: " + str(error)
                         + "; provide a retained --rust-sdk or Debian distribution Rust tools, "
                           "or explicitly select --core-provider cpp") from error


def host_programs(root=None):
    """Select retained build tools where the SDK declares them."""
    programs = {name: name for name in ("cmake", "ctest", "cpack", "ninja")}
    if root:
        metadata = json.loads((root / "sdk.json").read_text(encoding="utf-8"))
        for name, relative in metadata.get("host_tools", {}).items():
            if name in programs or name == "python":
                programs[name] = str(contained(root, relative))
    return programs


def verify_windows_linker(minimum):
    tools = str(Path(__file__).resolve().parent)
    if tools not in sys.path:
        sys.path.insert(0, tools)
    from sdk_windows import linker_version
    from windows_toolchain import inspect_selected_linker
    actual = inspect_selected_linker()['version']
    if linker_version(actual) < linker_version(minimum):
        raise ValueError("actual consuming linker is older than the dependency producer")


def cache_identity(build):
    selected = {}
    cache_version = {}
    for line in (build / "CMakeCache.txt").read_text(encoding="utf-8").splitlines():
        if "=" not in line or ":" not in line or line.startswith(("#", "//")):
            continue
        name_type, value = line.split("=", 1)
        name = name_type.split(":", 1)[0]
        if name in ("CMAKE_CACHE_MAJOR_VERSION", "CMAKE_CACHE_MINOR_VERSION", "CMAKE_CACHE_PATCH_VERSION"):
            cache_version[name] = value
        # Every cached input can affect generated rules, package discovery or
        # runtime behavior. A prefix allowlist misses linker/launcher/toolkit
        # overrides and lets an externally edited cache bypass the build stamp.
        selected[name] = value
    if "CMAKE_CXX_COMPILER" not in selected:
        version = ".".join(cache_version["CMAKE_CACHE_" + part + "_VERSION"] for part in ("MAJOR", "MINOR", "PATCH"))
        record = build / "CMakeFiles" / version / "CMakeCXXCompiler.cmake"
        match = re.search(r'^set\(CMAKE_CXX_COMPILER "([^"\n]+)"\)$', record.read_text(encoding="utf-8"), re.M)
        if not match:
            raise ValueError("configured compiler identity is absent")
        selected["CMAKE_CXX_COMPILER"] = match[1]
    compiler = Path(selected["CMAKE_CXX_COMPILER"]).resolve(strict=True)
    selected["compiler_file_sha256"] = hashlib.sha256(compiler.read_bytes()).hexdigest()
    selected["compiler_resolved_path"] = str(compiler)
    return selected


def run(command, **kwargs):
    print("+ " + subprocess.list2cmdline([str(x) for x in command]), flush=True)
    windows_compiler.run(command, cwd=ROOT, **kwargs)


class PhaseTimings:
    """Opt-in monotonic wall times; nested subprocess work remains inclusive."""
    def __init__(self, destination):
        self.destination = destination
        self.started = time.perf_counter()
        self.phases = {}
        self.context = {}

    def call(self, name, function, *args, **kwargs):
        if self.destination is None:
            return function(*args, **kwargs)
        started = time.perf_counter()
        try:
            return function(*args, **kwargs)
        finally:
            phase = self.phases.setdefault(name, {"seconds": 0.0, "calls": 0})
            phase["seconds"] += time.perf_counter() - started
            phase["calls"] += 1

    def finish(self, status):
        if self.destination is None:
            return
        document = {"schema_version": 1, "clock": "perf_counter", "status": status,
                    "total_seconds": time.perf_counter() - self.started,
                    "context": self.context, "phases": self.phases,
                    "interpretation": "Total starts after argument parsing. Inclusive subprocess wall times. "
                    "test_startup_probe is a separate "
                    "CTest discovery-only invocation; test_execution includes its own startup, scheduling "
                    "and child processes. Configure/build may repeat verification internally. "
                    "Do not subtract the probe or sum these as exclusive CPU costs."}
        destination = self.destination.resolve()
        destination.parent.mkdir(parents=True, exist_ok=True)
        # Unique staging file also prevents a failed write leaving a valid-looking receipt.
        import tempfile
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=destination.parent,
                                             prefix=".timings-", delete=False) as stream:
                temporary = Path(stream.name)
                json.dump(document, stream, indent=2)
                stream.write("\n")
            temporary.replace(destination)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)


def main(argv=None):
    arguments = list(sys.argv[1:] if argv is None else argv)
    if arguments and arguments[0] == "editor":
        # Dispatch before application provider, package and Rust-tool selection.
        import importlib.util
        spec = importlib.util.spec_from_file_location("foundation_editor_build", ROOT / "editor/build.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module.main(arguments[1:])
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", nargs="?", choices=("build", "test", "package", "portable-package"), default="build")
    parser.add_argument("preset", nargs="?", choices=("dev", "release", "asan"), default=None)
    parser.add_argument("--verify-package", action="store_true", help="relocate and verify produced archives, including the installed CMake consumer")
    parser.add_argument("--configure-only", action="store_true", help="configure without compiling; candidate scopes build their own prerequisites")
    parser.add_argument("--jobs", type=positive)
    parser.add_argument("--build-jobs", type=positive, help="independent compilation concurrency")
    parser.add_argument("--test-jobs", type=positive, help="independent test concurrency")
    parser.add_argument("--stop-on-failure", action="store_true",
                        help="stop testing after the first failed CTest case; remaining coverage is incomplete")
    parser.add_argument("--dependency-prefix", type=Path, help="verified native development prefix")
    selection = parser.add_mutually_exclusive_group()
    selection.add_argument("--label", choices=("fast", "core", "tools", "integration", "gui"))
    selection.add_argument("--test", action="append", dest="tests", metavar="NAME",
                           help="run an exact CTest name; repeat for several names (including fixture prerequisites)")
    selection.add_argument("--full", action="store_true", help="run all enabled tests (default)")
    parser.add_argument("--sdk", type=Path)
    parser.add_argument("--core-provider", choices=("rust", "cpp"), default="rust",
                        help="private core validation implementation (default: rust; cpp is explicit compatibility mode)")
    parser.add_argument("--rust-sdk", type=Path, help="verified Rust extension paired with the selected target SDK")
    parser.add_argument("--windows-dependencies", type=Path, help="verified restored Windows dependency export")
    parser.add_argument("--dependency-group", type=Path, action="append", default=[],
                        help="verified complete retained group; first group is primary for host-supplied toolchains")
    parser.add_argument("--binary-dependency-group", type=Path, action="append", default=[],
                        help="explicit binary/checksum consumer input; source payload qualification is separate")
    gui_input = parser.add_mutually_exclusive_group()
    gui_input.add_argument("--gui", action="store_true", help="use the verified GUI sources retained in this checkout")
    gui_input.add_argument("--gui-source", type=Path)
    gui_input.add_argument("--gui-input-group", type=Path, help="verified offline GUI source group")
    parser.add_argument("--gui-backends", default="terminal,framebuffer,hosted-web",
                        help="comma-separated backends; enable GUI with --gui, --gui-source or --gui-input-group")
    parser.add_argument("--host-tests", action="store_true")
    parser.add_argument("--portable", action="store_true", help="generic CPU and private static C++ runtime")
    parser.add_argument("--build-dir", type=Path, help="owned per-session output tree")
    parser.add_argument("--distribution-tests", action="store_true")
    parser.add_argument("--junit", type=Path, help="machine-readable outcomes for this test invocation")
    parser.add_argument("--timings", type=Path,
                        help="write opt-in phase wall times and a separate CTest startup/discovery probe")
    parser.add_argument("--wasm-package", type=Path, help="verified prebuilt offline Wasm package directory for native installation")
    parser.add_argument("--wasm-package-sha256", help="exact SHA256 of the prebuilt web-manifest.json")
    args = parser.parse_args(argv)
    timings = PhaseTimings(args.timings)
    status = "failed"
    try:
        result = execute(args, parser, timings)
        status = "passed"
        return result
    finally:
        timings.finish(status)


def execute(args, parser, timings):
    if args.rust_sdk and args.core_provider != "rust":
        parser.error("--rust-sdk requires --core-provider rust")
    if bool(args.wasm_package) != bool(args.wasm_package_sha256):
        parser.error("--wasm-package and --wasm-package-sha256 must be supplied together")
    if args.wasm_package_sha256 and not re.fullmatch(r"[0-9a-f]{64}", args.wasm_package_sha256):
        parser.error("--wasm-package-sha256 must be a lowercase SHA256")
    if args.action == "portable-package":
        args.action = "package"
        args.portable = True
        args.verify_package = True
    preset = args.preset or ("release" if args.action == "package" else "dev")
    if args.verify_package and args.action != "package":
        parser.error("--verify-package applies only to package")
    if args.configure_only and args.action != "build":
        parser.error("--configure-only applies only to build")
    if args.stop_on_failure and args.action != "test":
        parser.error("--stop-on-failure applies only to test")
    if (args.label or args.full or args.tests or args.junit) and args.action != "test":
        parser.error("test selection applies only to test")
    if args.action == "package" and preset != "release":
        parser.error("package requires release configuration")
    if (args.core_provider == "rust" and not args.rust_sdk
            and (sys.platform != "linux" or args.sdk or args.windows_dependencies
                 or args.portable or preset != "dev")):
        parser.error("this Rust target/configuration requires an explicit retained --rust-sdk; "
                     "prepare its matched extension or explicitly select --core-provider cpp")
    backends = args.gui_backends.split(",")
    allowed = {"terminal", "framebuffer", "fltk", "rev", "sdl", "hosted-web", "wasm"}
    if len(set(backends)) != len(backends) or not set(backends) <= allowed:
        parser.error("unknown or duplicate GUI backend")
    if args.gui:
        args.gui_input_group = ROOT / "third_party/gui-inputs"
    has_gui = bool(args.gui_source or args.gui_input_group)
    if args.host_tests and not has_gui:
        parser.error("host checks require GUI inputs")
    if "wasm" in backends and (backends != ["wasm"] or not args.sdk or args.host_tests):
        parser.error("Wasm requires one backend and a prepared SDK; native host tests are separate")
    jobs, test_jobs = job_limits(args)
    suffix = (("-sdk" if args.sdk else "")
              + ("-rust-sdk" if args.rust_sdk else "-rust" if args.core_provider == "rust" else "")
              + ("-gui" if has_gui else ""))
    build = args.build_dir.resolve() if args.build_dir else ROOT / "build" / (preset + suffix + ("-portable" if args.portable else ""))
    timings.context = {"action": args.action, "preset": preset, "build_directory": str(build),
                       "warm_tree_at_start": (build / "CMakeCache.txt").is_file(),
                       "build_jobs": jobs, "test_jobs": test_jobs, "core_provider": args.core_provider}
    gui_group_identity = None
    if args.gui_input_group:
        gui_group = args.gui_input_group.resolve(strict=True)
        helper = ROOT / "gui/source_group.py"
        restored = json.loads(timings.call("source_verification", subprocess.check_output,
            [sys.executable, "-B", str(helper), "restore", str(gui_group), "--output", str(build / "inputs/gui")],
            text=True, encoding="utf-8"))
        args.gui_source = Path(restored["source"]).resolve(strict=True)
        gui_group_identity = {"root": str(gui_group), "sha256": restored["group_sha256"]}
    configure = ["cmake", "--preset", preset, "-B", str(build),
                 "-DFOUNDATION_CORE_PROVIDER=" + args.core_provider,
                 "-DFOUNDATION_RUST_SDK_ROOT=",
                 "-DFOUNDATION_BUILD_GUI=" + ("ON" if args.gui_source else "OFF"),
                 "-DFOUNDATION_SANITIZERS=" + ("ON" if preset == "asan" else "OFF"),
                 "-DFOUNDATION_PORTABLE=" + ("ON" if args.portable else "OFF"),
                 "-DFOUNDATION_DISTRIBUTION_TESTS=" + ("ON" if args.distribution_tests else "OFF")]
    for name in ("fltk", "rev", "sdl"):
        configure.append("-DFOUNDATION_GUI_" + name.upper() + "=" + ("ON" if args.gui_source and name in backends else "OFF"))
    configure += ["-DFOUNDATION_GUI_WEB=" + ("ON" if "hosted-web" in backends else "OFF"),
                  "-DFOUNDATION_GUI_HOST_TESTS=" + ("ON" if args.host_tests else "OFF")]
    identity = {"preset": preset, "sdk": None, "gui": None,
                "core_provider": args.core_provider, "rust_sdk": None,
                "backends": sorted(backends) if args.gui_source else [], "host_tests": args.host_tests,
                "portable": args.portable, "distribution_tests": args.distribution_tests, "dependencies": [],
                "windows_dependencies": None,
                "environment": {key: os.environ.get(key) for key in
                 ("CC", "CXX", "CFLAGS", "CXXFLAGS", "LDFLAGS", "CMAKE_GENERATOR")}}
    if gui_group_identity:
        identity["gui_input_group"] = gui_group_identity
    if args.dependency_prefix:
        if args.sdk or args.windows_dependencies:
            parser.error("native development prefix cannot be combined with a prepared SDK")
        from prepare_dependencies import verify
        prefix_root = args.dependency_prefix.resolve(strict=True)
        identity["dependency_prefix"] = {"root": str(prefix_root), **timings.call("dependency_verification", verify, prefix_root)}
        configure += ["-DFOUNDATION_DEPENDENCY_PREFIX=" + str(prefix_root)]
    programs = host_programs()
    child_environment = os.environ.copy()
    if args.core_provider == "rust":
        if args.rust_sdk:
            rust_sdk = args.rust_sdk.resolve(strict=True)
            paired_sdk = (args.sdk or args.windows_dependencies)
            paired_sdk = paired_sdk.resolve(strict=True) if paired_sdk else None
            identity["rust_sdk"] = {"root": str(rust_sdk), "sha256": timings.call(
                "rust_sdk_verification", rust_sdk_identity, rust_sdk, paired_sdk)}
            configure += ["-DFOUNDATION_RUST_SDK_ROOT=" + str(rust_sdk)]
        else:
            native_rust_tools, native_rust_before = timings.call("rust_tool_verification", native_rust_identity)
            identity["rust_tools"] = native_rust_before
            configure += ["-DFOUNDATION_RUST_CARGO=" + native_rust_tools["cargo"],
                          "-DFOUNDATION_RUST_RUSTC=" + native_rust_tools["rustc"]]
    if args.sdk:
        sdk = args.sdk.resolve(strict=True)
        try:
            require_clean()
        except ValueError as error:
            parser.error(str(error))
        identity["sdk"] = {"root": str(sdk), "sha256": timings.call("sdk_verification", sdk_identity, sdk)}
        is_browser = json.loads((sdk / "sdk.json").read_text(encoding="utf-8"))["target"]["system"] == "Emscripten"
        if is_browser != (backends == ["wasm"]):
            raise ValueError("prepared SDK target and selected GUI backend disagree")
        if is_browser:
            from sdk_wasm import environment
            child_environment = environment(sdk)
            configure += ["-DFOUNDATION_NODE_EXECUTABLE=" + str(contained(sdk, "node/bin/node"))]
        programs = host_programs(sdk)
        configure[0] = programs["cmake"]
        child_environment["PYTHONDONTWRITEBYTECODE"] = "1"
        if programs["ninja"] != "ninja":
            configure += ["-DCMAKE_MAKE_PROGRAM=" + programs["ninja"]]
        if "python" in programs:
            configure += ["-DPython3_EXECUTABLE=" + programs["python"]]
        if args.action == "package":
            from sdk_manifest import verify_sdk
            timings.call("sdk_verification", verify_sdk, sdk, release=True)
        configure += ["-DCMAKE_TOOLCHAIN_FILE=" + str(ROOT / "cmake/toolchains/sdk.cmake"),
                      "-DFOUNDATION_SDK_ROOT=" + str(sdk)]
    dependency_ids = []
    if args.sdk:
        dependency_ids.append(json.loads((args.sdk.resolve() / "sdk.json").read_text(encoding="utf-8"))["recipe_id"])
    if args.dependency_group or args.binary_dependency_group:
        tools = str(Path(__file__).resolve().parent)
        if tools not in sys.path:
            sys.path.insert(0, tools)
        from dependency_store import verify_group
        for group_arg, binary in [(group, False) for group in args.dependency_group] + [(group, True) for group in args.binary_dependency_group]:
            group = group_arg.resolve(strict=True)
            checksums = list(group.glob("sdk-*-SHA256SUMS"))
            if len(checksums) != 1:
                raise ValueError("retained group needs exactly one recipe checksum inventory")
            match = re.fullmatch(r"sdk-([0-9a-f]{64})-SHA256SUMS", checksums[0].name)
            if not match:
                raise ValueError("invalid retained group identity")
            recipe = match[1]
            if binary:
                from dependency_store import verify_binary_group
                hashes = timings.call("dependency_verification", verify_binary_group, group, recipe)
            else:
                hashes = timings.call("dependency_verification", verify_group, group, recipe)
            if recipe in dependency_ids:
                raise ValueError("duplicate prepared group")
            dependency_ids.append(recipe)
            entry = {"root": str(group), "recipe": recipe, "files": hashes}
            if binary:
                entry["payload"] = "binary"
            identity["dependencies"].append(entry)
    if args.windows_dependencies:
        if os.name != "nt" or args.sdk or not args.portable:
            raise ValueError("Windows dependency exports require a native portable Windows build")
        from dependency_archive import read_json, verify_inventory, inspect_manifest_archive
        from dependency_store import names
        from sdk_manifest import verify_sdk
        dependencies = args.windows_dependencies.resolve(strict=True)
        metadata = read_json(dependencies / "sdk.json")
        if metadata.get("kind") != "windows-dependencies" or metadata.get("recipe_id") not in dependency_ids:
            raise ValueError("Windows dependency export needs its complete matching retained group")
        timings.call("sdk_verification", verify_sdk, dependencies, release=True)
        retained = next(item for item in identity["dependencies"] if item["recipe"] == metadata["recipe_id"])
        archived, _ = inspect_manifest_archive(Path(retained["root"]) / names(metadata["recipe_id"])[0], "sdk.json")
        if archived != metadata:
            raise ValueError("restored Windows metadata differs from retained producer metadata")
        provenance = metadata.get("provenance", {})
        if (metadata["target"]["system"] != "Windows" or metadata["target"]["processor"] != "x86_64" or
                provenance.get("toolset") != "v143" or provenance.get("crt_linkage") != "static" or
                provenance.get("library_linkage") != "static" or provenance.get("lto") is not False):
            raise ValueError("incompatible Windows dependency ABI contract")
        verify_windows_linker(metadata["external_toolchain"]["minimum_linker"])
        timings.call("sdk_verification", verify_inventory, dependencies, metadata["files"], exclude=("sdk.json",))
        identity["windows_dependencies"] = {"root": str(dependencies), "sha256": hashlib.sha256((dependencies / "sdk.json").read_bytes()).hexdigest()}
        installed = dependencies / "prefix/installed/x64-windows-static"
        prefix = installed if installed.is_dir() else dependencies / "prefix"
        configure += ["-DCMAKE_PREFIX_PATH=" + str(prefix), "-DFOUNDATION_WINDOWS_DEPENDENCIES=" + str(dependencies)]
        vcpkg = dependencies / "prefix/scripts/buildsystems/vcpkg.cmake"
        if vcpkg.is_file():
            # The verified export uses static libraries and CRT. Its package
            # manager is unnecessary for DLL copying or dependency installation.
            configure += ["-DCMAKE_TOOLCHAIN_FILE=" + str(vcpkg), "-DVCPKG_TARGET_TRIPLET=x64-windows-static",
                          "-DVCPKG_MANIFEST_MODE=OFF", "-DVCPKG_APPLOCAL_DEPS=OFF",
                          "-DX_VCPKG_APPLOCAL_DEPS_INSTALL=OFF"]
            for key in list(child_environment):
                if key.upper() == "VCPKG_DISABLE_METRICS":
                    del child_environment[key]
            child_environment["VCPKG_DISABLE_METRICS"] = "1"
    configure += ["-DFOUNDATION_DEPENDENCY_RECIPE=" + (dependency_ids[0] if dependency_ids else "native-unprepared"),
                  "-DFOUNDATION_DEPENDENCY_RECIPES=" + ";".join(sorted(dependency_ids))]
    if args.gui_source:
        gui = args.gui_source.resolve(strict=True)
        identity["gui"] = str(gui)
        configure += ["-DFOUNDATION_BUILD_GUI=ON", "-DFOUNDATION_GUI_SOURCE=" + str(gui)]
    if args.wasm_package:
        if backends == ["wasm"]:
            parser.error("a prebuilt Wasm package can only be imported into a native build")
        from import_wasm import verify_input
        package = args.wasm_package.resolve(strict=True)
        timings.call("source_verification", verify_input, package, args.wasm_package_sha256, ROOT)
        identity["wasm_package"] = {"root": str(package), "sha256": args.wasm_package_sha256}
        configure += ["-DFOUNDATION_WASM_PACKAGE=" + str(package),
                      "-DFOUNDATION_WASM_PACKAGE_SHA256=" + args.wasm_package_sha256]
    else:
        configure += ["-DFOUNDATION_WASM_PACKAGE=", "-DFOUNDATION_WASM_PACKAGE_SHA256="]
    build.mkdir(parents=True, exist_ok=True)
    stamp = build / "wrapper-identity.json"
    if (build / "CMakeCache.txt").exists() and not stamp.exists():
        raise ValueError("refusing to adopt a populated unstamped build tree; move it aside or use CMake directly")
    if stamp.exists() and json.loads(stamp.read_text(encoding="utf-8")) != identity:
        raise ValueError("toolchain/configuration changed; use a fresh build tree or move the old one aside")
    cache_stamp = build / "configured-identity.json"
    if cache_stamp.exists() and json.loads(cache_stamp.read_text(encoding="utf-8")) != timings.call("configuration_verification", cache_identity, build):
        raise ValueError("configured compiler/options changed outside this wrapper; use a fresh tree or CMake directly")
    # Failed configuration must not leave a tree silently reusable with another SDK.
    stamp.write_text(json.dumps(identity, indent=2) + "\n")
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from source_identity import source_tree
    source_before = timings.call("source_verification", source_tree, ROOT, args.gui_source)
    timings.context["source_tree_sha256"] = source_before.get("tree_sha256")
    timings.context["sdk_sha256"] = identity["sdk"]["sha256"] if identity["sdk"] else None
    timings.context["rust_sdk_sha256"] = identity["rust_sdk"]["sha256"] if identity["rust_sdk"] else None
    timings.call("configure", run, configure, env=child_environment)
    cache_stamp.write_text(json.dumps(timings.call("configuration_verification", cache_identity, build), indent=2) + "\n")
    targets = ["all"]
    exact_selection = None
    if args.action == "test":
        if args.tests:
            from test_plan import named_selection
            exact_selection = timings.call("test_selection", named_selection, build, args.tests, programs, child_environment)
            targets = exact_selection["targets"]
        else:
            targets = ["foundation-tests" + ("-" + args.label if args.label else "")]
    if not args.configure_only and targets:
        timings.call("compile", run, [programs["cmake"], "--build", str(build), "--parallel", str(jobs), "--target", *targets], env=child_environment)
    if exact_selection is not None and timings.call("test_selection", named_selection, build, args.tests, programs, child_environment) != exact_selection:
        raise ValueError("named test inventory or prerequisites changed during compilation")
    if timings.call("source_verification", source_tree, ROOT, args.gui_source) != source_before:
        raise ValueError("source changed during compilation; rebuild a stable candidate")
    if args.action == "test":
        from build_capacity import worker_environment
        test_environment = worker_environment(child_environment, test_jobs,
                                               capacity=max(jobs, test_jobs))
        command = [programs["ctest"], "--test-dir", str(build), "--output-on-failure",
                   "--no-tests=error", "--parallel", str(test_jobs)]
        if args.junit:
            junit = args.junit.resolve()
            junit.parent.mkdir(parents=True, exist_ok=True)
            junit.unlink(missing_ok=True)
            command += ["--output-junit", str(junit)]
        if args.label:
            command += ["-L", "^" + args.label + "$"]
        if exact_selection is not None:
            command += ["-R", exact_selection["pattern"]]
        if args.stop_on_failure:
            command.append("--stop-on-failure")
        if timings.destination is not None:
            probe = [programs["ctest"], "--test-dir", str(build), "--show-only=json-v1"]
            if args.label:
                probe += ["-L", "^" + args.label + "$"]
            if exact_selection is not None:
                probe += ["-R", exact_selection["pattern"]]
            # Discovery runs no tests and never substitutes for the real execution.
            timings.call("test_startup_probe", subprocess.check_output, probe, cwd=ROOT,
                         env=test_environment, timeout=60)
        timings.call("test_execution", run, command, env=test_environment)
    elif args.action == "package":
        timings.call("package", run, [programs["cpack"], "--config", str(build / "CPackConfig.cmake"), "-C", "Release"], env=child_environment)
        if args.verify_package:
            archives = sorted([*(build / "packages").glob("*.tar.gz"), *(build / "packages").glob("*.zip")])
            if not archives:
                raise ValueError("no application archives found for verification")
            for archive in archives:
                manifest = archive.with_name(archive.name + ".json")
                for operation in ("create", "verify"):
                    verification = []
                    if operation == "verify" and args.sdk:
                        target = json.loads((args.sdk.resolve() / "sdk.json").read_text())["target"]
                        verification = ["--sdk", str(args.sdk.resolve())]
                        if target["system"] != "Emscripten":
                            verification += ["--processor", target["processor"]]
                    timings.call("package_verification", run, [sys.executable, "-B", str(ROOT / "tools/artifact.py"), operation,
                         str(archive), "--manifest", str(manifest), *verification], env=child_environment)
    # A plain build already checked its terminal source above. Tests and
    # packaging execute additional writers and require a fresh final observation.
    if args.action != "build" and timings.call("source_verification", source_tree, ROOT, args.gui_source) != source_before:
        raise ValueError("source changed during the operation; outputs are not qualification")
    if gui_group_identity:
        verified = json.loads(timings.call("source_verification", subprocess.check_output,
            [sys.executable, "-B", str(helper), "verify", str(gui_group)], text=True, encoding="utf-8"))
        if verified["group_sha256"] != gui_group_identity["sha256"]:
            raise ValueError("GUI input group changed during execution; evidence is invalid")
    if args.sdk and timings.call("sdk_verification", sdk_identity, args.sdk.resolve()) != identity["sdk"]["sha256"]:
        raise ValueError("prepared SDK changed during execution; evidence is invalid")
    if identity["rust_sdk"]:
        if timings.call("rust_sdk_verification", rust_sdk_identity, rust_sdk, paired_sdk) != identity["rust_sdk"]["sha256"]:
            raise ValueError("prepared Rust SDK changed during execution; evidence is invalid")
    elif args.core_provider == "rust":
        if timings.call("rust_tool_verification", native_rust_identity) != (native_rust_tools, native_rust_before):
            raise ValueError("selected Rust tools changed during execution; evidence is invalid")
    if args.windows_dependencies:
        timings.call("sdk_verification", verify_inventory, dependencies, metadata["files"], exclude=("sdk.json",))
        if hashlib.sha256((dependencies / "sdk.json").read_bytes()).hexdigest() != identity["windows_dependencies"]["sha256"]:
            raise ValueError("Windows dependency identity changed during execution")
    if args.dependency_prefix and timings.call("dependency_verification", verify, prefix_root) != {key: value for key, value in identity["dependency_prefix"].items() if key != "root"}:
        raise ValueError("native development prefix changed during execution")
    if args.wasm_package:
        timings.call("source_verification", verify_input, package, args.wasm_package_sha256, ROOT)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (OSError, ValueError, KeyError, subprocess.CalledProcessError) as error:
        print("build: " + str(error), file=sys.stderr)
        sys.exit(1)
