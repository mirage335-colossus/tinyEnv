#!/usr/bin/env python3
"""Freeze test coverage, run disjoint shards, reject incomplete aggregation."""
import argparse
import hashlib
import json
import math
import os
import tempfile
import time
from pathlib import Path
import re
import subprocess
import sys
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))
import build as builder
import windows_compiler
import build_capacity
from sdk_environment import HOST_OVERRIDES, require_clean
from dependency_archive import read_json
from dependency_store import verify_group
from source_identity import source_tree


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def gui_source(cache):
    enabled = cache.get("FOUNDATION_BUILD_GUI", "OFF").upper() not in ("OFF", "NO", "FALSE", "0", "")
    value = cache.get("FOUNDATION_GUI_SOURCE")
    if enabled and not value:
        raise ValueError("enabled GUI has no configured source input")
    return Path(value).resolve(strict=True) if enabled else None


def source_id(build=None):
    supplement = gui_source(builder.cache_identity(build)) if build is not None else None
    return source_tree(ROOT, supplement)["tree_sha256"]


def execution_context(build):
    cache = builder.cache_identity(build)
    sdk = Path(cache["FOUNDATION_SDK_ROOT"]).resolve(strict=True) if cache.get("FOUNDATION_SDK_ROOT") else None
    if sdk:
        require_clean()
    programs = builder.host_programs(sdk)
    if not sdk:
        programs["cmake"] = cache.get("CMAKE_COMMAND", programs["cmake"])
        programs["ctest"] = cache.get("CMAKE_CTEST_COMMAND", programs["ctest"])
    environment = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    if sdk and read_json(sdk / "sdk.json")["target"]["system"] == "Emscripten":
        from sdk_wasm import environment as sdk_environment
        environment = sdk_environment(sdk)
    return programs, environment


def verify_gui_group(root):
    value = subprocess.check_output([sys.executable, "-B", str(ROOT / "gui/source_group.py"),
                                     "verify", str(root)], text=True, encoding="utf-8")
    return json.loads(value)["group_sha256"]


def native_rust_inputs(build, cache):
    """Verify CMake's selected native tools without discovery or execution."""
    if (not sys.platform.startswith("linux") or cache.get("FOUNDATION_SDK_ROOT")
            or cache.get("FOUNDATION_WINDOWS_DEPENDENCIES")):
        raise ValueError("this Rust target requires its configured retained SDK")
    from rust_build import _load_config, native_tool_identity
    cargo, rustc = cache.get("FOUNDATION_RUST_CARGO"), cache.get("FOUNDATION_RUST_RUSTC")
    if not cargo or not rustc:
        raise ValueError("native Rust configuration is missing its selected tools")
    tools = native_tool_identity(cargo, rustc)
    configurations = (cache["CMAKE_CONFIGURATION_TYPES"].split(";") if cache.get("CMAKE_CONFIGURATION_TYPES")
                      else [cache.get("CMAKE_BUILD_TYPE") or "NoConfig"])
    if (len(set(configurations)) != len(configurations)
            or any(not re.fullmatch(r"[A-Za-z0-9_][A-Za-z0-9_.+-]*", name) for name in configurations)):
        raise ValueError("invalid native Rust configuration names")
    descriptions = {}
    target = None
    for name in configurations:
        path = build / "rust" / name / "config.json"
        path.resolve(strict=True).relative_to(build.resolve(strict=True))
        description, _ = _load_config(str(path.absolute()))
        described_tools = {tool: {key: row[key] for key in ("path", "sha256", "identity")}
                           for tool, row in description["tools"].items()}
        if (description["source_root"] != str(ROOT.resolve(strict=True))
                or description["build_dir"] != str(path.parent.resolve(strict=True))
                or description["system"] != "Linux" or description["sdk_root"]
                or description["cpp_sdk_root"] or description["cpp_sdk_manifest"] or described_tools != tools
                or description["tools"]["rustc"]["host"] != description["target"]
                or description["profile"] != ("debug" if name.lower() == "debug" else "release")
                or (target is not None and target != description["target"])):
            raise ValueError("native Rust inputs differ from the configured CMake selection")
        target = description["target"]
        descriptions[name] = digest(normalize_locations(description, build))
    expected = hashlib.sha256(";".join((target, rustc, cargo, tools["rustc"]["sha256"],
                                      tools["cargo"]["sha256"], "none")).encode()).hexdigest()
    if (cache.get("FOUNDATION_CONFIGURED_RUST_IDENTITY") != expected
            or (cache.get("FOUNDATION_RUST_TARGET") and cache["FOUNDATION_RUST_TARGET"] != target)):
        raise ValueError("native Rust toolchain differs from its configured identity")
    return tools, descriptions


def build_inputs(build):
    """Recompute bytes, never trust a saved wrapper receipt as verification."""
    cache = builder.cache_identity(build)
    stamp = build / "wrapper-identity.json"
    configured = build / "configured-identity.json"
    wrapper = read_json(stamp) if stamp.exists() else None
    if wrapper is not None:
        if not configured.is_file() or read_json(configured) != cache:
            raise ValueError("configured compiler/options changed outside the build wrapper")
    elif configured.exists():
        raise ValueError("configured build receipt is missing its wrapper identity")
    # Pre-provider build trees remain C++; the current configure default is irrelevant.
    provider = cache.get("FOUNDATION_CORE_PROVIDER", "cpp")
    if provider not in ("cpp", "rust"):
        raise ValueError("unknown configured core provider")
    result = {"cache": cache, "wrapper": wrapper, "sdk": None, "dependencies": [], "windows_dependencies": None, "dependency_prefix": None,
              "core_provider": provider, "rust_sdk": None,
              "environment": {key: os.environ.get(key) for key in (*HOST_OVERRIDES, "CMAKE_GENERATOR")}}
    sdk_root = cache.get("FOUNDATION_SDK_ROOT")
    prefix_root = cache.get("FOUNDATION_DEPENDENCY_PREFIX")
    if prefix_root:
        if sdk_root or cache.get("FOUNDATION_WINDOWS_DEPENDENCIES"):
            raise ValueError("native dependency prefix cannot mix with prepared exports")
        from prepare_dependencies import verify
        prefix = Path(prefix_root).resolve(strict=True)
        verified = verify(prefix)
        result["dependency_prefix"] = {"root": str(prefix), "sha256": verified["sha256"], "prefix": str(verified["prefix"])}
    recipe_ids = []
    if sdk_root:
        sdk = Path(sdk_root).resolve(strict=True)
        require_clean()
        result["sdk"] = {"root": str(sdk), "sha256": builder.sdk_identity(sdk)}
        recipe_ids.append(read_json(sdk / "sdk.json")["recipe_id"])
    rust_root = cache.get("FOUNDATION_RUST_SDK_ROOT")
    if provider == "rust":
        if rust_root:
            from rust_sdk import verify_rust_sdk
            from dependency_archive import digest as file_digest
            rust = Path(rust_root).resolve(strict=True)
            metadata = verify_rust_sdk(rust, cpp_sdk=Path(sdk_root) if sdk_root else
                                       Path(cache["FOUNDATION_WINDOWS_DEPENDENCIES"]) if cache.get("FOUNDATION_WINDOWS_DEPENDENCIES") else None,
                                       target=cache.get("FOUNDATION_RUST_TARGET") or None, execute=True)
            result["rust_sdk"] = {"root": str(rust), "sha256": file_digest(rust / "rust-sdk.json")}
            recipe_ids.append(metadata["recipe_id"])
        else:
            result["rust_tools"], result["rust_configurations"] = native_rust_inputs(build, cache)
    elif rust_root:
        raise ValueError("C++ provider cannot retain a configured Rust SDK")
    if wrapper is not None:
        if wrapper.get("core_provider", "cpp") != provider or wrapper.get("rust_sdk") != result["rust_sdk"]:
            raise ValueError("core provider or Rust SDK differs from configured wrapper identity")
        if wrapper.get("rust_tools") != result.get("rust_tools"):
            raise ValueError("native Rust tools differ from configured wrapper identity")
        if wrapper.get("dependency_prefix") != result["dependency_prefix"]:
            raise ValueError("native dependency prefix differs from configured wrapper identity")
        if prefix_root and wrapper.get("windows_dependencies"):
            raise ValueError("native dependency prefix cannot mix with Windows exports")
        if wrapper.get("sdk") != result["sdk"]:
            raise ValueError("prepared SDK differs from configured wrapper identity")
        if any(os.environ.get(key) != value for key, value in wrapper.get("environment", {}).items()):
            raise ValueError("build environment differs from configured wrapper identity")
        expected_gui = str(gui_source(cache)) if gui_source(cache) else None
        if wrapper.get("gui") != expected_gui:
            raise ValueError("GUI source differs from configured wrapper identity")
        for item in wrapper.get("dependencies", []):
            payload = item.get("payload", "complete")
            if payload == "binary":
                from dependency_store import verify_binary_group
                files = verify_binary_group(item["root"], item["recipe"])
            elif payload == "complete":
                files = verify_group(item["root"], item["recipe"])
            else:
                raise ValueError("unknown retained dependency payload scope")
            actual = {"root": str(Path(item["root"]).resolve(strict=True)), "recipe": item["recipe"], "files": files}
            if payload == "binary":
                actual["payload"] = "binary"
            if actual != item or item["recipe"] in recipe_ids:
                raise ValueError("retained dependency group changed or is duplicated")
            recipe_ids.append(item["recipe"])
            result["dependencies"].append(actual)
        windows = wrapper.get("windows_dependencies")
        if windows:
            from sdk_manifest import verify_sdk
            path = Path(windows["root"]).resolve(strict=True)
            actual = {"root": str(path), "sha256": verify_sdk(path, release=True)}
            if actual != windows or read_json(path / "sdk.json")["recipe_id"] not in recipe_ids:
                raise ValueError("Windows dependency export differs from its retained identity")
            result["windows_dependencies"] = actual
        group = wrapper.get("gui_input_group")
        if group:
            actual = {"root": str(Path(group["root"]).resolve(strict=True)),
                      "sha256": verify_gui_group(group["root"])}
            if actual != group:
                raise ValueError("GUI input group differs from its retained identity")
            result["gui_input_group"] = actual
    declared = set(filter(None, cache.get("FOUNDATION_DEPENDENCY_RECIPES", "").split(";")))
    if sdk_root:
        declared.add(read_json(Path(sdk_root) / "sdk.json")["recipe_id"])
    if result["rust_sdk"]:
        declared.add(metadata["recipe_id"])
    primary = cache.get("FOUNDATION_DEPENDENCY_RECIPE", "native-unprepared")
    if (sorted(declared) != sorted(recipe_ids)
            or (primary != "native-unprepared" and primary not in recipe_ids)):
        raise ValueError("configured dependencies need complete verified retained input identities")
    return result


def normalize_locations(value, build):
    """Normalize declared and physical roots before JSON escaping.

    Windows tools may retain an 8.3 spelling while Path.resolve expands it.
    Both supplied and resolved root spellings represent the same input; leave
    unrelated compiler/dependency paths intact rather than resolving every value.
    """
    replacements = [(str(ROOT), "<SOURCE>")]
    for root, marker in ((build, "<BUILD>"), (ROOT, "<SOURCE>")):
        path = Path(root)
        spellings = {str(path.absolute()), str(path.resolve())}
        if path.is_absolute():
            spellings.add(str(path))
        replacements.extend((spelling, marker) for spelling in spellings)
    # CMake lowercases the Windows drive in CMAKE_CACHEFILE_DIR even when
    # other generated roots preserve it. Only that drive letter is equivalent;
    # preserve case-sensitive directory components and unrelated input values.
    replacements += [(path[0].swapcase() + path[1:], marker)
                     for path, marker in replacements if re.match(r"^[A-Za-z]:[/\\]", path)]
    replacements = sorted(set((spelling, marker) for path, marker in replacements
                             for spelling in (path, path.replace("\\", "/"))), key=lambda item:len(item[0]), reverse=True)
    # A root must end at a path component or a generated CMake delimiter.
    # Prefix siblings such as source-cache or "source cache" are external inputs.
    replacements = [(re.compile(re.escape(path) + r"""(?=$|[/\\;"')\]\r\n])"""), marker)
                    for path, marker in replacements]
    def visit(item):
        if isinstance(item, str):
            for pattern, marker in replacements: item = pattern.sub(marker, item)
            return item
        if isinstance(item, list): return [visit(row) for row in item]
        if isinstance(item, dict): return {visit(key):visit(row) for key,row in item.items()}
        return item
    return visit(value)


def test_definitions(build):
    programs, environment = execution_context(build)
    raw = subprocess.check_output([programs["ctest"], "--test-dir", str(build), "--show-only=json-v1"],
                                  text=True, env=environment)
    tests = json.loads(raw)["tests"]
    return normalize_locations(tests, build)


def inventory(build):
    return test_names(test_definitions(build))


def test_names(definitions):
    tests = sorted(item["name"] for item in definitions)
    if not tests or len(set(tests)) != len(tests):
        raise ValueError("test inventory is empty or duplicated")
    return tests


def ctest_declarations(build):
    """Read only CTest's declared tree, excluding tests' nested consumer builds."""
    root = Path(build).resolve(strict=True)
    pending, result = [root / "CTestTestfile.cmake"], {}
    while pending:
        path = pending.pop().resolve(strict=True)
        path.relative_to(root)
        relative = path.relative_to(root).as_posix()
        if relative in result:
            raise ValueError("recursive or duplicated CTest declaration directory")
        text = path.read_text(encoding="utf-8")
        result[relative] = text
        for line in text.splitlines():
            if line.strip().startswith("subdirs("):
                match = re.fullmatch(r'\s*subdirs\("([^"\\]+)"\)\s*', line)
                if not match:
                    raise ValueError("unsupported generated CTest subdirectory declaration")
                pending.append(path.parent / match[1] / "CTestTestfile.cmake")
    return result


def prerequisites(build):
    """Return the complete configured mapping; old external trees keep full builds."""
    return _prerequisites(build)


def _prerequisites(build, tests=None):
    path = Path(build) / "test-prerequisites.json"
    if not path.exists():
        if builder.cache_identity(build).get("FOUNDATION_HAS_TEST_PREREQUISITES") == "ON":
            raise ValueError("configured test prerequisite inventory is missing")
        return None
    value = read_json(path)
    if (set(value) != {"schema_version", "tests"} or value["schema_version"] != 1 or
            not isinstance(value["tests"], dict)):
        raise ValueError("invalid test prerequisite inventory")
    mapping = value["tests"]
    if sorted(mapping) != (inventory(build) if tests is None else tests):
        raise ValueError("test prerequisite inventory differs from complete CTest inventory")
    validate_prerequisites(mapping)
    return mapping


def validate_prerequisites(mapping):
    if not isinstance(mapping, dict) or not mapping:
        raise ValueError("empty or invalid test prerequisite inventory")
    for name, targets in mapping.items():
        if (not isinstance(name, str) or not name or not isinstance(targets, list) or
                any(not isinstance(x, str) or not re.fullmatch(r"[A-Za-z0-9_][A-Za-z0-9_.+-]*", x) for x in targets) or
                targets != sorted(set(targets))):
            raise ValueError("invalid or duplicate test prerequisites")


def selected_targets(mapping, names):
    validate_prerequisites(mapping)
    if not names or not set(names) <= set(mapping):
        raise ValueError("selected tests have missing prerequisites")
    return sorted({target for name in names for target in mapping[name]})


def named_selection(build, names, programs, environment):
    """Select literal names and ask CTest to expand its actual fixture graph.

    The complete registered mapping is authoritative. Never infer build targets
    from names, silently accept a typo, or fall back to the expensive all target.
    """
    if (not names or len(names) != len(set(names)) or
            any(not isinstance(name, str) or not name for name in names)):
        raise ValueError("named tests must be nonempty and unique")
    command = [programs["ctest"], "--test-dir", str(build), "--show-only=json-v1"]
    complete = json.loads(subprocess.check_output(command, text=True, env=environment))["tests"]
    available = test_names(complete)
    if not set(names) <= set(available):
        raise ValueError("unknown exact test name: " + ", ".join(sorted(set(names) - set(available))))
    mapping = _prerequisites(build, available)
    if mapping is None:
        raise ValueError("exact test selection requires the complete registered prerequisite inventory")
    pattern = "^(" + "|".join(re.escape(name) for name in sorted(names)) + ")$"
    selected = json.loads(subprocess.check_output(command + ["-R", pattern], text=True, env=environment))["tests"]
    executed = test_names(selected)
    if not set(names) <= set(executed) or not set(executed) <= set(available):
        raise ValueError("CTest exact selection differs from the complete inventory")
    return {"names": executed, "targets": selected_targets(mapping, executed), "pattern": pattern,
            "prerequisites": mapping}


def compile_targets(programs, environment, build, targets, jobs):
    # An empty script-only selection must not invoke CMake's default all target.
    if targets:
        windows_compiler.run([programs["cmake"], "--build", str(build), "--target", *targets,
                              "--parallel", str(jobs)], env=environment)


def configuration_id(build, *, declared_commands=False):
    definitions = test_definitions(build)
    mapping = _prerequisites(build, test_names(definitions))
    return _configuration_id(build, definitions, mapping, declared_commands=declared_commands)


def _configuration_id(build, tests, mapping, *, declared_commands=False):
    # Reuse one complete CTest observation only inside this verification phase.
    # Callers take a fresh observation after compilation and after execution.
    declared_build = build
    build = build.resolve()
    inputs = build_inputs(build)
    # Normalize checkout/build locations while preserving actual compiler and
    # retained-input digests, complete cache values and external locations.
    normalized = normalize_locations(inputs, declared_build)
    info = (build / "build-info.txt").read_text()
    identity = {"inputs": normalized, "build_info": info, "tests": tests}
    if mapping is not None:
        identity["prerequisites"] = mapping
    if declared_commands:
        # CTest omits command arrays for not-yet-built executables. Bind the exact
        # generated commands instead, so independent scope builds have the same
        # inventory identity without compiling unrelated executables.
        declarations = ctest_declarations(build)
        if not declarations:
            raise ValueError("candidate needs complete generated CTest declarations")
        identity["tests"] = [{key:value for key,value in item.items() if key != "command"} for item in tests]
        identity["declarations"] = normalize_locations(declarations, declared_build)
    return digest(identity)


def require_current(build, plan):
    declared = "prerequisites" in plan
    if declared and prerequisites(build) != plan["prerequisites"]:
        raise ValueError("test prerequisites changed since planning")
    if (configuration_id(build, declared_commands=declared) != plan["configuration"] or source_id(build) != plan["source"]
            or inventory(build) != plan["tests"]):
        raise ValueError("source, compiler, prepared inputs or test configuration changed since planning")


def make_plan(tests, shards, identity, configuration="unit-fixture", *, prerequisites=None):
    if shards < 1 or shards > len(tests):
        raise ValueError("shards must be between 1 and the test count")
    plan = {"schema_version": 1, "source": identity, "configuration": configuration, "tests": sorted(tests),
            "shards": [sorted(tests)[index::shards] for index in range(shards)]}
    if prerequisites is not None:
        validate_prerequisites(prerequisites)
        if sorted(prerequisites) != plan["tests"]:
            raise ValueError("test prerequisites do not cover the complete inventory")
        plan["prerequisites"] = prerequisites
    plan["id"] = digest(plan)
    return plan


def validate_plan(plan):
    body = {key: value for key, value in plan.items() if key != "id"}
    if plan.get("schema_version") != 1 or digest(body) != plan.get("id"):
        raise ValueError("plan identity mismatch")
    if "prerequisites" in plan:
        validate_prerequisites(plan["prerequisites"])
        if sorted(plan["prerequisites"]) != plan["tests"]:
            raise ValueError("test prerequisites do not cover the complete inventory")
    flat = [name for shard in plan["shards"] for name in shard]
    if not flat or any(not shard for shard in plan["shards"]) or sorted(flat) != plan["tests"] or len(set(flat)) != len(flat):
        raise ValueError("invalid shard inventory")


def junit_results(path, expected):
    cases = list(ET.parse(path).getroot().iter("testcase"))
    names = [case.attrib.get("name") for case in cases]
    if sorted(names) != sorted(expected) or len(set(names)) != len(names):
        raise ValueError("missing, unexpected or duplicate test results")
    statuses = {}
    for case in cases:
        passed = case.attrib.get("status", "run") in ("run", "passed")
        passed = passed and all(case.find(tag) is None for tag in ("failure", "error", "skipped"))
        statuses[case.attrib["name"]] = "passed" if passed else "failed_or_incomplete"
    return statuses



def test_timeouts(definitions):
    limits = {}
    for item in definitions:
        values = [prop["value"] for prop in item.get("properties", []) if prop["name"] == "TIMEOUT"]
        if len(values) > 1:
            raise ValueError("duplicate test timeout")
        limit = float(values[0]) if values else None
        if limit is not None and (not math.isfinite(limit) or limit < 0):
            raise ValueError("test timeout must be finite and nonnegative")
        limits[item["name"]] = limit or None
    return limits


def junit_timings(path, expected, timeouts):
    """Retain measured JUnit times; absent durations remain explicitly unknown."""
    statuses = junit_results(path, expected)
    if not set(expected) <= set(timeouts):
        raise ValueError("timing timeout inventory is incomplete")
    rows = []
    for case in ET.parse(path).getroot().iter("testcase"):
        name = case.attrib["name"]
        seconds = float(case.attrib["time"]) if "time" in case.attrib else None
        limit = timeouts[name]
        if seconds is not None and (not math.isfinite(seconds) or seconds < 0):
            raise ValueError("JUnit duration must be finite and nonnegative")
        if limit is not None and (not math.isfinite(limit) or limit <= 0):
            raise ValueError("test timeout must be finite and positive")
        rows.append(dict(name=name, status=statuses[name], seconds=seconds, timeout_seconds=limit,
                         near_timeout=statuses[name] == "passed" and seconds is not None and
                         limit is not None and seconds >= .8 * limit))
    return sorted(rows, key=lambda row: row["name"])


def timing_summary(timing, scope, summary=None):
    rows = timing["tests"]
    known = [row for row in rows if row["seconds"] is not None]
    phases = timing["phase_seconds"]
    lines = ["### Test timing: " + scope, "",
             "Build: %.2fs; test wall time: %.2fs; complete scope: %.2fs." %
             (phases["build"], phases["test"], phases["total"]), "",
             "Measured test durations total %.2fs across %d cases (concurrent tests may overlap)." %
             (sum(row["seconds"] for row in known), len(known)), ""]
    for row in sorted(known, key=lambda row: row["seconds"], reverse=True)[:5]:
        name = row["name"].replace("`", "'").replace("\n", " ").replace("\r", " ")
        warning = " — passed at 80% or more of its declared timeout" if row["near_timeout"] else ""
        lines.append("- `%s`: %.2fs (%s)%s" % (name, row["seconds"], row["status"], warning))
    if len(known) != len(rows):
        lines += ["", "%d cases have no reported JUnit duration." % (len(rows) - len(known))]
    warnings = [row["name"] for row in rows if row["near_timeout"]]
    if warnings:
        lines += ["", "Timeout margin warning: " + ", ".join(name.replace("\n", " ").replace("\r", " ") for name in warnings) + "."]
    text = "\n".join(lines) + "\n"
    print(text)
    if summary is not None:
        with Path(summary).open("a", encoding="utf-8") as stream:
            stream.write(text + "\n")
    return text


def merge(plan, reports):
    validate_plan(plan)
    seen = set()
    results = {}
    for report in reports:
        index = report["shard"]
        if report["plan"] != plan["id"] or index in seen or type(index) is not int or not 0 <= index < len(plan["shards"]):
            raise ValueError("duplicate, stale or invalid shard")
        if set(report["results"]) != set(plan["shards"][index]):
            raise ValueError("incomplete shard results")
        if report["exit_code"] != 0 or any(value != "passed" for value in report["results"].values()):
            raise ValueError("failed or incomplete coverage")
        seen.add(index)
        results.update(report["results"])
    if seen != set(range(len(plan["shards"]))) or set(results) != set(plan["tests"]):
        raise ValueError("missing shard coverage")
    return {"schema_version": 1, "plan": plan["id"], "source": plan["source"], "status": "passed", "tests": len(results)}


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                     prefix=path.name + ".", delete=False) as output:
        staging = Path(output.name)
        output.write(json.dumps(value, indent=2) + "\n")
        output.flush()
        os.fsync(output.fileno())
    try:
        os.replace(staging, path)
    finally:
        staging.unlink(missing_ok=True)



CANDIDATE_SCOPES = ("core", "tools", "integration")


def candidate_plan(build):
    return _candidate_observation(build)[0]


def _candidate_observation(build):
    definitions = test_definitions(build)
    assignments = {scope: [] for scope in CANDIDATE_SCOPES}
    for item in definitions:
        labels = next((p["value"] for p in item.get("properties", []) if p["name"] == "LABELS"), [])
        selected = [scope for scope in ("tools", "integration") if scope in labels]
        if len(selected) > 1:
            raise ValueError("test has competing candidate owners")
        assignments[selected[0] if selected else "core"].append(item["name"])
    tests = sorted(x["name"] for x in definitions)
    if not tests or len(tests) != len(set(tests)) or any(not names for names in assignments.values()):
        raise ValueError("candidate inventory is empty, duplicated or has an empty required scope")
    platform_path = build / "test-platform.json"
    platform = read_json(platform_path)
    if (set(platform) != {"schema_version", "excluded_suites"} or platform["schema_version"] != 1 or
            not isinstance(platform["excluded_suites"], dict) or
            any(not name.startswith("tools.") or name in tests or not isinstance(reason, str) or not reason
                for name, reason in platform["excluded_suites"].items())):
        raise ValueError("invalid explicit platform exclusions")
    mapping = _prerequisites(build, tests)
    value = dict(schema_version=1, source=source_id(build),
                 configuration=_configuration_id(build, definitions, mapping, declared_commands=True),
                 tests=tests, scopes={key: sorted(value) for key, value in assignments.items()},
                 platform_exclusions=platform["excluded_suites"], timeouts=test_timeouts(definitions))
    value["id"] = digest(value)
    return value, mapping


def candidate_prerequisite_inputs(build):
    """Freeze declarations before CTest can resolve freshly compiled executables."""
    build = Path(build)
    paths = {build/name for name in ctest_declarations(build)}
    paths.update(build/name for name in ('build-info.txt', 'test-platform.json'))
    if (build / "test-prerequisites.json").exists():
        paths.add(build / "test-prerequisites.json")
    declarations = {path.relative_to(build).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
                    for path in sorted(paths)}
    return source_id(build), build_inputs(build), declarations


def candidate_run(build, scope, output, jobs=None, *, build_jobs=None, summary=None):
    """Freeze all tests; unlabelled new tests automatically belong to core."""
    if scope not in CANDIDATE_SCOPES or (build_jobs is not None and build_jobs < 1):
        raise ValueError("invalid candidate scope or concurrency")
    jobs = build_capacity.test_jobs(jobs if jobs is not None else os.environ.get("CTEST_PARALLEL_LEVEL"))
    output = Path(output)
    if output.exists():
        raise ValueError("candidate receipt must name a new attempt")
    output.parent.mkdir(parents=True, exist_ok=True)
    from build_capacity import compile_jobs as selected_compile_jobs
    compile_jobs = build_jobs or selected_compile_jobs(os.environ.get("CMAKE_BUILD_PARALLEL_LEVEL"))
    started = time.monotonic()
    before = candidate_prerequisite_inputs(build)
    frozen, mapping = _candidate_observation(build)
    programs, environment = execution_context(build)
    targets = selected_targets(mapping, frozen["scopes"][scope]) if mapping is not None else ["foundation-tests-" + scope]
    compile_targets(programs, environment, build, targets, compile_jobs)
    compiled_at = time.monotonic()
    if candidate_prerequisite_inputs(build) != before:
        raise ValueError("candidate inputs changed during prerequisite compilation")
    if candidate_plan(build) != frozen:
        raise ValueError("candidate inventory changed during prerequisite compilation")
    names = frozen["scopes"][scope]
    test_environment = build_capacity.worker_environment(environment, min(jobs, len(names)),
                                                        capacity=max(compile_jobs, jobs))
    junit = output.with_suffix(".junit.xml").resolve()
    if junit.exists():
        raise ValueError("candidate JUnit must name a new attempt")
    testing_at = time.monotonic()
    try:
        exit_code = windows_compiler.run([programs["ctest"], "--test-dir", str(build), "--no-tests=error", "--output-on-failure",
            "--parallel", str(jobs), "-R", "^(" + "|".join(re.escape(name) for name in names) + ")$",
            "--output-junit", str(junit)], env=test_environment).returncode
    except subprocess.CalledProcessError as error:
        # The owner raises this only after a nonzero command and its children
        # have joined. Ownership and timeout failures must bypass report creation.
        exit_code = error.returncode
    tested_at = time.monotonic()
    outcomes = junit_results(junit, names)
    timed_tests = junit_timings(junit, names, frozen["timeouts"])
    if candidate_plan(build) != frozen:
        raise ValueError("candidate inputs changed during execution")
    import importlib.util
    spec = importlib.util.spec_from_file_location("candidate_coverage", Path(__file__).with_name("coverage.py"))
    checked = importlib.util.module_from_spec(spec); spec.loader.exec_module(checked)
    inner = {name: checked.tool_report(read_json(build / "test-reports" / (name.removeprefix("tools.") + ".json")))
             for name in names if name.startswith("tools.")}
    result = dict(schema_version=1, plan=frozen, scope=scope, results=outcomes, tool_reports=inner,
                  exit_code=exit_code, junit_sha256=hashlib.sha256(junit.read_bytes()).hexdigest(),
                  timing=dict(tests=timed_tests, phase_seconds=dict(build=compiled_at-started,
                              test=tested_at-testing_at, total=time.monotonic()-started)))
    save(output, result)
    timing_summary(result["timing"], scope, summary)
    if exit_code or any(value != "passed" for value in outcomes.values()):
        raise ValueError("candidate scope failed")
    return result


def candidate_merge(paths, *, diagnostic=False):
    expected = {"core"} if diagnostic else set(CANDIDATE_SCOPES)
    reports = [read_json(Path(path)) for path in paths]
    if not reports or {x.get("scope") for x in reports} != expected or len(reports) != len(expected):
        raise ValueError("missing, duplicate or unexpected candidate scope")
    frozen = reports[0]["plan"]
    if frozen.get("id") != digest({key:value for key,value in frozen.items() if key != "id"}):
        raise ValueError("candidate plan digest differs")
    assigned = [name for names in frozen["scopes"].values() for name in names]
    if sorted(assigned) != frozen["tests"] or len(assigned) != len(set(assigned)) or set(frozen["scopes"]) != set(CANDIDATE_SCOPES):
        raise ValueError("candidate assignment is incomplete or duplicated")
    import importlib.util
    spec = importlib.util.spec_from_file_location("candidate_coverage", Path(__file__).with_name("coverage.py"))
    checked = importlib.util.module_from_spec(spec); spec.loader.exec_module(checked)
    excluded = {}
    for path, report in zip(paths, reports):
        names = frozen["scopes"][report["scope"]]
        if (report["plan"] != frozen or report["exit_code"] or sorted(report["results"]) != names or
                any(value != "passed" for value in report["results"].values())):
            raise ValueError("changed candidate identity or incomplete scope results")
        junit = Path(path).with_suffix(".junit.xml")
        if hashlib.sha256(junit.read_bytes()).hexdigest() != report["junit_sha256"] or junit_results(junit,names) != report["results"]:
            raise ValueError("candidate JUnit changed")
        if report["timing"]["tests"] != junit_timings(junit, names, frozen["timeouts"]):
            raise ValueError("candidate timing differs from retained JUnit")
        phases = report["timing"]["phase_seconds"]
        if (set(phases) != {"build", "test", "total"} or
                any(type(value) not in (int, float) or not math.isfinite(value) or value < 0 for value in phases.values()) or
                phases["total"] < phases["build"] + phases["test"]):
            raise ValueError("invalid candidate phase timings")
        if set(report["tool_reports"]) != {name for name in names if name.startswith("tools.")}:
            raise ValueError("candidate inner-case inventory missing")
        for name, inner in report["tool_reports"].items():
            checked.tool_report(inner)
            excluded[name] = inner["excluded"]
    return dict(schema_version=1, status="passed", mode="diagnostic" if diagnostic else "candidate",
                plan=frozen, executed_scopes=sorted(expected), inner_exclusions=excluded,
                omitted_scopes=sorted(set(CANDIDATE_SCOPES)-expected))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    plan_cmd = sub.add_parser("plan")
    plan_cmd.add_argument("--build", type=Path, required=True)
    plan_cmd.add_argument("--shards", type=int, default=2)
    plan_cmd.add_argument("--jobs", type=builder.positive, help="legacy explicit compile concurrency")
    plan_cmd.add_argument("--build-jobs", type=builder.positive)
    plan_cmd.add_argument("--output", type=Path, required=True)
    run_cmd = sub.add_parser("run")
    run_cmd.add_argument("--build", type=Path, required=True)
    run_cmd.add_argument("--plan", type=Path, required=True)
    run_cmd.add_argument("--shard", type=int, required=True)
    run_cmd.add_argument("--jobs", type=builder.positive, help="legacy explicit compile/test concurrency")
    run_cmd.add_argument("--build-jobs", type=builder.positive)
    run_cmd.add_argument("--summary", type=Path)
    run_cmd.add_argument("--output", type=Path, required=True)
    merge_cmd = sub.add_parser("merge")
    merge_cmd.add_argument("--plan", type=Path, required=True)
    merge_cmd.add_argument("--output", type=Path, required=True)
    merge_cmd.add_argument("reports", type=Path, nargs="+")
    candidate_cmd = sub.add_parser("candidate-run")
    candidate_cmd.add_argument("--build", type=Path, required=True)
    candidate_cmd.add_argument("--scope", choices=CANDIDATE_SCOPES, required=True)
    candidate_cmd.add_argument("--jobs", type=builder.positive, help="explicit test concurrency; default is resource-aware")
    candidate_cmd.add_argument("--build-jobs", type=builder.positive)
    candidate_cmd.add_argument("--output", type=Path, required=True)
    candidate_cmd.add_argument("--summary", type=Path, help="append timing to the hosted job summary")
    candidate_merge_cmd = sub.add_parser("candidate-merge")
    candidate_merge_cmd.add_argument("--output", type=Path, required=True)
    candidate_merge_cmd.add_argument("--diagnostic", action="store_true")
    candidate_merge_cmd.add_argument("reports", type=Path, nargs="+")
    args = parser.parse_args()
    if args.action == "candidate-run":
        candidate_run(args.build, args.scope, args.output, args.jobs, build_jobs=args.build_jobs, summary=args.summary)
        return 0
    if args.action == "candidate-merge":
        if args.output.exists():
            raise ValueError("candidate merge must name a new attempt")
        save(args.output, candidate_merge(args.reports, diagnostic=args.diagnostic))
        return 0
    inputs = ([args.plan] if args.action != "plan" else []) + (args.reports if args.action == "merge" else [])
    if args.output.resolve() in [path.resolve() for path in inputs]:
        raise ValueError("output must not replace an input")
    # A failed attempt must never leave a previous successful receipt behind.
    args.output.unlink(missing_ok=True)
    started = time.monotonic()
    if args.action in ("plan", "run"):
        compile_concurrency = args.build_jobs or args.jobs or build_capacity.compile_jobs(os.environ.get("CMAKE_BUILD_PARALLEL_LEVEL"))
        cache = (args.build / "CMakeCache.txt").read_text()
        if re.search(r"^CMAKE_CONFIGURATION_TYPES:.*=.+", cache, flags=re.M):
            raise ValueError("test-plan example requires a single-configuration build tree")
        before, inputs_before = source_id(args.build), build_inputs(args.build)
        if args.action == "run":
            planned = json.loads(args.plan.read_text())
            validate_plan(planned)
            require_current(args.build, planned)
        programs, environment = execution_context(args.build)
        mapping = prerequisites(args.build)
        declarations_before = ctest_declarations(args.build) if mapping is not None else None
        if args.action == "run" and "prerequisites" in planned:
            if not 0 <= args.shard < len(planned["shards"]):
                raise ValueError("invalid shard or concurrency")
            targets = selected_targets(mapping, planned["shards"][args.shard])
        else:
            targets = [] if mapping is not None and args.action == "plan" else ["foundation-tests"]
        compile_targets(programs, environment, args.build, targets, compile_concurrency)
        compiled_at = time.monotonic()
        if (before != source_id(args.build) or inputs_before != build_inputs(args.build) or
                prerequisites(args.build) != mapping or
                (mapping is not None and ctest_declarations(args.build) != declarations_before)):
            raise ValueError("source, compiler or prepared inputs changed while compiling test prerequisites")
    if args.action == "plan":
        save(args.output, make_plan(inventory(args.build), args.shards, source_id(args.build),
            configuration_id(args.build, declared_commands=mapping is not None), prerequisites=mapping))
    else:
        plan = json.loads(args.plan.read_text())
        validate_plan(plan)
        if args.action == "merge":
            save(args.output, merge(plan, [json.loads(path.read_text()) for path in args.reports]))
        else:
            if not 0 <= args.shard < len(plan["shards"]):
                raise ValueError("invalid shard or concurrency")
            require_current(args.build, plan)
            expected = plan["shards"][args.shard]
            test_concurrency = build_capacity.test_jobs(args.jobs if args.jobs is not None
                                                       else os.environ.get("CTEST_PARALLEL_LEVEL"))
            test_environment = build_capacity.worker_environment(environment, min(test_concurrency, len(expected)),
                                                                capacity=max(compile_concurrency, test_concurrency))
            args.output.parent.mkdir(parents=True, exist_ok=True)
            junit = args.output.with_name(args.output.name + ".junit.xml").resolve()
            # Prevent stale JUnit data from surviving a failed test launch.
            junit.unlink(missing_ok=True)
            testing_at = time.monotonic()
            try:
                exit_code = windows_compiler.run([programs["ctest"], "--test-dir", str(args.build), "--no-tests=error", "--output-on-failure",
                    "--parallel", str(test_concurrency), "-R", "^(" + "|".join(re.escape(x) for x in expected) + ")$",
                    "--output-junit", str(junit)], env=test_environment).returncode
            except subprocess.CalledProcessError as error:
                exit_code = error.returncode
            tested_at = time.monotonic()
            results = junit_results(junit, expected)
            timed_tests = junit_timings(junit, expected, test_timeouts(test_definitions(args.build)))
            require_current(args.build, plan)
            timing = dict(tests=timed_tests, phase_seconds=dict(build=compiled_at-started,
                          test=tested_at-testing_at, total=time.monotonic()-started))
            save(args.output, {"schema_version": 1, "plan": plan["id"], "shard": args.shard,
                               "exit_code": exit_code, "results": results, "timing": timing})
            timing_summary(timing, "shard " + str(args.shard), args.summary)
            if exit_code or any(value != "passed" for value in results.values()):
                return 1
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (OSError, ValueError, KeyError, ET.ParseError, subprocess.CalledProcessError) as error:
        print("test plan: " + str(error), file=sys.stderr)
        sys.exit(1)
