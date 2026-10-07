#!/usr/bin/env python3
"""Run source, archive or recovery qualification from an immutable candidate."""
import argparse
import ast
from contextlib import contextmanager
import importlib.util
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import tempfile
import shutil

TOOLS = Path(__file__).resolve().parent
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))
import artifact
import windows_compiler
import release
import sdk
from dependency_archive import digest, extract, write_json
from source_identity import source_tree, verify_source_archive
from verify_abi import audit
from build import host_programs

spec = importlib.util.spec_from_file_location("check_coverage", TOOLS / "coverage.py")
c = importlib.util.module_from_spec(spec)
spec.loader.exec_module(c)


def select(manifest, target, backend):
    matches = [a for a in manifest["artifacts"] if a["target"] == target and backend in (a["backends"] or ["core"])]
    if len(matches) != 1:
        raise ValueError("one exact delivered target/backend is required")
    return matches[0]


def native_target(target):
    if target.startswith("browser-"):
        raise ValueError("browser qualification requires the real-browser adapter and its retained receipts")
    machine = platform.machine().lower()
    machine = {"amd64": "x86_64", "arm64": "aarch64"}.get(machine, machine)
    if target != platform.system().lower() + "-" + machine:
        raise ValueError("execute the qualification inside the actual target environment")


def browser_prerequisite_snapshot(options, target, backend, scope, subject):
    """Bind a browser prerequisite receipt to this explicit frozen execution."""
    import ci_plan
    path = options.get("browser_prerequisite")
    plan_path = options.get("browser_prerequisite_plan")
    if not path and not plan_path:
        return None
    if not path or not plan_path or not ci_plan.needs_browser_prerequisite(backend, scope):
        raise ValueError("browser prerequisite requires its frozen plan and browser assertion scope")
    def snapshot(value):
        value = Path(value)
        if value.is_symlink() or not value.is_file() or value.stat().st_size > 8 * 1024 * 1024:
            raise ValueError("browser prerequisite needs bounded regular inputs")
        raw = value.read_bytes()
        data = json.loads(raw, object_pairs_hook=c.object_pairs,
                          parse_constant=lambda _: (_ for _ in ()).throw(ValueError("nonfinite JSON")))
        return value, raw, data
    path, raw, data = snapshot(path)
    plan_path, plan_raw, plan = snapshot(plan_path)
    c.validate(plan)
    c.fields(data, {"schema_version", "selection", "signing_key_fingerprint", "installed",
                    "browser_version", "plan", "check", "run_id", "attempt"})
    matches = [item for item in plan["checks"] if item["id"] == data["check"]]
    if (type(data["schema_version"]) is not int or data["schema_version"] != 1 or
            data["plan"] != plan["id"] or len(matches) != 1 or
            any(plan["subject"][key] != value for key, value in subject.items()) or
            data["plan"] != os.environ.get("FOUNDATION_PLAN_ID") or
            data["check"] != os.environ.get("FOUNDATION_CHECK_ID") or
            not isinstance(data["run_id"], str) or not c.NAME.fullmatch(data["run_id"]) or
            data["run_id"] != os.environ.get("FOUNDATION_RUN_ID") or
            type(data["attempt"]) is not int or data["attempt"] < 1 or
            str(data["attempt"]) != os.environ.get("FOUNDATION_RUN_ATTEMPT")):
        raise ValueError("browser prerequisite belongs to another frozen case or attempt")
    item = matches[0]
    if (item["target"], item["backend"], item["scope"]) != (target, backend, scope):
        raise ValueError("browser prerequisite names another target/backend/scope")
    expected = ci_plan.browser_prerequisite(target, item["environment"], backend)
    host = c.host_identity()
    machine = {"amd64": "x86_64", "arm64": "aarch64"}.get(host["machine"].lower(), host["machine"].lower())
    if (data["selection"] != expected or host["system"] != "Linux" or
            host["distribution"] != expected["distribution"] + "-" + expected["version"] or
            machine != {"amd64": "x86_64", "arm64": "aarch64"}[expected["architecture"]]):
        raise ValueError("browser prerequisite differs from the actual host or selected browser")
    engine = options.get("browser") or "firefox"
    executable = options.get("firefox") if engine == "firefox" else options.get("browser_executable")
    if engine != expected["engine"] or executable != expected["executable"]:
        raise ValueError("browser prerequisite differs from the executed browser command")
    fingerprint = None
    if data["signing_key_fingerprint"] != fingerprint:
        raise ValueError("browser prerequisite signing identity differs")
    installed = data["installed"]
    if not isinstance(installed, list) or len(installed) != len(expected["packages"]):
        raise ValueError("incomplete browser package prerequisite inventory")
    for package, record in zip(expected["packages"], installed):
        c.fields(record, {"package", "version", "architecture", "policy"}, {"executable", "files"})
        if (record["package"] != package or record["architecture"] != expected["architecture"] or
                not all(isinstance(record[key], str) and record[key].strip() for key in ("version", "policy"))):
            raise ValueError("browser prerequisite package identity differs")
    if expected['repository'] == 'host-preinstalled':
        observed = (ci_plan.inspect_host_chromium(expected) if engine == 'chromium'
                    else [ci_plan.inspect_host_firefox(expected)])
        if installed != observed or data['browser_version'] != observed[0]['version']:
            raise ValueError('installed host browser changed since prerequisite inspection')
        if engine == 'chromium':
            if options.get('driver') != expected['driver']:
                raise ValueError('browser prerequisite differs from the selected driver')
            options['browser_executable'], options['driver'] = (item['executable'] for item in observed)
        else:
            options['firefox'] = observed[0]['executable']
    if not isinstance(data["browser_version"], str) or not data["browser_version"].strip():
        raise ValueError("browser prerequisite version is absent")
    return {"path": path, "raw": raw, "data": data, "plan_path": plan_path, "plan_raw": plan_raw}


def bind_browser_prerequisite(state, details, evidence):
    if state is None:
        return
    import re
    actual = details.get("browser", {})
    expected = state["data"]
    def version(value):
        values = re.findall(r"(?<![0-9.])([0-9]+(?:\.[0-9]+){1,3})(?:esr)?(?![0-9.])", value)
        if len(values) != 1:
            raise ValueError("ambiguous browser prerequisite version")
        parts = tuple(map(int, values[0].split(".")))
        return parts + (0,) * (4 - len(parts))
    if (actual.get("status") != "passed" or actual.get("engine") != expected["selection"]["engine"] or
            version(actual.get("browser_version", "")) != version(expected["browser_version"])):
        raise ValueError("executed browser differs from its prerequisite receipt")
    if (state["path"].is_symlink() or state["path"].read_bytes() != state["raw"] or
            state["plan_path"].is_symlink() or state["plan_path"].read_bytes() != state["plan_raw"]):
        raise ValueError("browser prerequisite or frozen plan changed during qualification")
    if expected['selection']['repository'] == 'host-preinstalled':
        for record in expected['installed']:
            for name, value in record['files'].items():
                if digest(Path(name)) != value:
                    raise ValueError('host browser executable changed during qualification')
    destination = evidence / "browser/prerequisite.json"
    with destination.open("xb") as stream:
        stream.write(state["raw"])
    details["browser_prerequisite"] = {"sha256": digest(destination), "plan": expected["plan"],
                                       "check": expected["check"], "run_id": expected["run_id"],
                                       "attempt": expected["attempt"]}


BROWSER_SECURITY_CASES = {
    "authority", "sibling", "wrong-nonce", "extra-ports", "duplicate-ready", "duplicate-bound",
    "duplicate-request", "oversized-request", "stale-message-generation", "stale-key-generation",
    "queue-bounds", "forbidden-service", "forbidden-file", "forbidden-poll", "forbidden-resize",
    "forbidden-close", "forbidden-transport", "provider-replacement", "provider-dispose",
    "provider-pagehide", "file-read-replacement", "file-read-dispose", "file-read-pagehide",
    "file-import-replacement", "file-import-dispose", "download-revocation", "download-valid-cleanup",
    "own-navigation", "initial-navigation", "concurrent-frontends",
}
BROWSER_SECURITY_CHECKS = {
    "actual-browser", "production-assembly", "correct-hash-malicious-child", "malicious-top-level-ran",
    "malicious-payload-ran", "opaque-origin-parent-canaries", "transport-token-insulation",
    "parent-service-file-url-insulation", "canary-positive-controls", "browser-process-tree-joined",
    "canary-server-joined", "child-resource-network-denials", "storage-cookie-dom-denials",
    "popup-top-navigation-download-denials", "wrong-sibling-correct-nonce",
    "self-navigation-observed-and-channel-revoked", "initial-navigation-no-rebinding",
    "concurrent-frontends-isolated-lifetimes",
}
BROWSER_SECURITY_ASSETS = (
    "browser_embedding.mjs", "browser_client.mjs", "browser_services.mjs", "browser_lifecycle.mjs",
    "browser_limits.mjs", "browser_presenter.mjs", "renderer_channel.mjs", "renderer_dom.mjs",
    "renderer_frame.mjs", "renderer_child_bundle.mjs", "file_services.mjs", "style.css",
)
BROWSER_SECURITY_FIXTURE_FILES = set(BROWSER_SECURITY_ASSETS) | {"harness.mjs", "index.html"}
BROWSER_INTERACTION_CHECKS = {
    "editing", "accessible-names", "shared-geometry", "prompt-cancel", "bounded-task", "capture", "cleanup",
    "retained-record-dom", "bounded-file-import", "atomic-invalid-import", "export-offered",
    "pagehide-prompt-cancel", "navigation", "opaque-frame-policy", "parent-owned-services",
}


def browser_isolated_interactions(receipt, modes):
    cases = [{"transport": transport, "composition": composition}
             for transport in modes for composition in ("standalone", "isolated")]
    policies = receipt.get("frame_policies", {})
    if (receipt.get("composition") != "both" or receipt.get("executed_compositions") != ["standalone", "isolated"] or
            receipt.get("executed_cases") != cases or
            not BROWSER_INTERACTION_CHECKS <= set(receipt.get("checks", [])) or
            set(policies) != {transport + "-isolated" for transport in modes} or
            any(policy.get("sandbox") != "allow-scripts" or policy.get("srcdoc") is not True
                for policy in policies.values())):
        raise ValueError("real browser did not exercise both renderer compositions and their feature inventory")



def browser_receipt_inputs(receipt, paths):
    """A passed assertion inventory must describe the bytes actually delivered."""
    inputs = receipt.get("inputs")
    if not isinstance(inputs, dict):
        raise ValueError("browser receipt lacks its executed input inventory")
    for path in paths:
        path = Path(path)
        if path.is_symlink() or not path.is_file() or inputs.get(str(path.resolve())) != digest(path):
            raise ValueError("browser evidence is missing or stale for " + str(path))


def browser_wasm_manifest(directory, source_root):
    import package_wasm
    manifest = package_wasm.verify(directory)
    if (manifest.get("schema") != 3 or
            manifest.get("source_tree_sha256") != source_tree(source_root)["tree_sha256"]):
        raise ValueError("isolated browser release needs a source-bound schema-3 Wasm package")
    return manifest


def browser_evidence_paths(evidence, details):
    directories = ["browser"]
    if details.get("renderer_security"):
        directories.append("browser-isolation")
    paths = []
    for name in directories:
        for path in sorted((evidence / name).rglob("*")):
            if path.is_symlink():
                raise ValueError("browser evidence cannot contain linked inputs")
            if path.is_file():
                paths.append(path.relative_to(evidence).as_posix())
    return paths


def browser_child_metadata(assets):
    """Bind canonical inert bundle data to the actual reviewed child inputs."""
    import browser_bundle
    blobs = {}
    for name in (*browser_bundle.CHILD_MODULES, "style.css", browser_bundle.BUNDLE_NAME):
        path = Path(assets) / name
        if path.is_symlink() or not path.is_file() or path.stat().st_size > 64 * 1024 * 1024:
            raise ValueError("browser child needs ordinary bounded inputs: " + str(path))
        blobs[name] = path.read_bytes()
    metadata = browser_bundle.parse_module(blobs.pop(browser_bundle.BUNDLE_NAME))
    if metadata != browser_bundle.assemble(blobs):
        raise ValueError("browser child bundle is not canonical for its retained inputs")
    return metadata


def browser_security_fixtures(fixtures, evidence):
    """Verify the retained bytes that were served for every hostile case."""
    from html.parser import HTMLParser

    class Policies(HTMLParser):
        def __init__(self):
            super().__init__()
            self.values = []

        def handle_starttag(self, tag, attributes):
            attributes = dict(attributes)
            if tag == "meta" and attributes.get("http-equiv", "").lower() == "content-security-policy":
                self.values.append(attributes.get("content"))

    if evidence is None:
        raise ValueError("renderer security evidence requires its retained fixtures")
    evidence = Path(evidence)
    root = evidence / "fixtures"
    if (evidence.is_symlink() or root.is_symlink() or not root.is_dir() or
            {path.name for path in root.iterdir()} != BROWSER_SECURITY_CASES):
        raise ValueError("renderer security retained fixture inventory differs")
    fields = {"child_script_sha256", "child_csp", "sandbox", "protocol", "child_inputs", "parent_csp", "fixture_inputs"}
    for name in sorted(BROWSER_SECURITY_CASES):
        policy = fixtures[name]
        directory = root / name
        if not isinstance(policy, dict) or set(policy) != fields:
            raise ValueError("renderer security fixture policy fields are incomplete: " + name)
        if not isinstance(policy["parent_csp"], str):
            raise ValueError("renderer security fixture parent policy differs: " + name)
        if (directory.is_symlink() or not directory.is_dir() or
                {path.name for path in directory.iterdir()} != BROWSER_SECURITY_FIXTURE_FILES):
            raise ValueError("renderer security retained fixture inventory differs: " + name)
        actual = {}
        for filename in sorted(BROWSER_SECURITY_FIXTURE_FILES):
            path = directory / filename
            if path.is_symlink() or not path.is_file() or path.stat().st_size > 64 * 1024 * 1024:
                raise ValueError("renderer security fixture needs ordinary bounded files: " + str(path))
            actual[filename] = digest(path)
        if policy["fixture_inputs"] != actual:
            raise ValueError("renderer security fixture bytes are missing or stale: " + name)
        metadata = browser_child_metadata(directory)
        expected = {"child_script_sha256": metadata["CHILD_SCRIPT_SHA256"], "child_csp": metadata["CHILD_CSP"],
                    "sandbox": metadata["CHILD_SANDBOX"], "protocol": metadata["CHILD_PROTOCOL"],
                    "child_inputs": metadata["CHILD_INPUTS"]}
        if any(policy[field] != value for field, value in expected.items()):
            raise ValueError("renderer security fixture describes another bundle or policy: " + name)
        policies = Policies()
        policies.feed((directory / "index.html").read_text(encoding="utf-8"))
        policies.close()
        if policies.values != [policy["parent_csp"]] or "'sha256-" + metadata["CHILD_SCRIPT_SHA256"] + "'" not in policy["parent_csp"]:
            raise ValueError("renderer security fixture parent policy differs: " + name)


def browser_security_receipt(receipt, source_root, assets, engine, browser_version, *, fixture_evidence=None):
    if (receipt.get("schema_version") != 1 or receipt.get("status") != "passed" or
            receipt.get("engine") != engine or receipt.get("browser_version") != browser_version or
            receipt.get("complete_security_inventory") is not True or
            set(receipt.get("executed_cases", [])) != BROWSER_SECURITY_CASES or
            not BROWSER_SECURITY_CHECKS <= set(receipt.get("checks", []))):
        raise ValueError("real browser did not complete the renderer authority inventory")
    metadata = browser_child_metadata(assets)
    expected = {"script_sha256": metadata["CHILD_SCRIPT_SHA256"], "csp": metadata["CHILD_CSP"],
                "sandbox": metadata["CHILD_SANDBOX"], "protocol": metadata["CHILD_PROTOCOL"],
                "inputs": metadata["CHILD_INPUTS"]}
    if receipt.get("production_child") != expected:
        raise ValueError("renderer security evidence describes another bundle or policy")
    fixtures = receipt.get("fixture_policies")
    if not isinstance(fixtures, dict) or set(fixtures) != BROWSER_SECURITY_CASES:
        raise ValueError("renderer security evidence omitted its exact hostile fixtures")
    browser_security_fixtures(fixtures, fixture_evidence)
    browser_receipt_inputs(receipt, [source_root / "gui/tests/browser_isolation_test.py",
                                   source_root / "gui/tests/browser_isolation_attack.mjs",
                                   source_root / "gui/tests/browser_test.py",
                                   source_root / "tools/browser_bundle.py",
                                   source_root / "tools/package_wasm.py",
                                   source_root / "tools/process_tree.py",
                                   *(assets / name for name in BROWSER_SECURITY_ASSETS)])
    return receipt


def browser_check(source_root, server, evidence, options, executable=None, wasm=None):
    engine = options.get("browser") or "firefox"
    offline = bool(wasm and (source_root / "tools/package_wasm.py").is_file())
    mode = "wasm-offline" if offline else ("wasm" if wasm else "hosted")
    offline_html = None
    if offline:
        # Build and installed layouts are explicit; never silently fall back to
        # a multi-file check when the new source promises an offline package.
        candidates = [Path(wasm) / "wasm-package/software-foundation-wasm.html",
                      server.parent.parent / "wasm/software-foundation-wasm.html"]
        present = [path for path in candidates if path.is_file() and not path.is_symlink()]
        if len(present) != 1:
            raise ValueError("required offline Wasm HTML missing or ambiguous")
        offline_html = present[0]
    isolated = (source_root / "gui/host/browser_embedding.mjs").is_file()
    command = [sys.executable, "-B", str(source_root / "gui/tests/browser_test.py"), "--browser", engine,
               "--mode", mode, "--server", str(server),
               "--output", str(evidence / "browser")]
    if isolated:
        command += ["--composition", "both"]
    if wasm:
        command += ["--wasm-dir", str(wasm)]
        if offline:
            command += ["--offline-html", str(offline_html)]
    else:
        command += ["--executable", str(executable)]
    if engine == "firefox":
        browser_arguments = ["--firefox", options.get("firefox") or "firefox"]
    else:
        if not options.get("browser_executable"):
            raise ValueError("Chromium qualification needs its explicit executable and matching driver")
        browser_arguments = ["--browser-executable", options["browser_executable"], "--driver", options.get("driver") or "chromedriver"]
    command += browser_arguments
    subprocess.run(command, check=True)
    receipt = c.load(evidence / "browser/qualification.json")
    required = {"editing", "accessible-names", "shared-geometry", "prompt-cancel", "capture", "cleanup"}
    if (receipt.get("schema_version") != (2 if isolated else 1) or receipt.get("status") != "passed" or receipt.get("engine") != engine or
            not receipt.get("browser_version") or receipt.get("mode") != mode or
            not required <= set(receipt.get("checks", []))):
        raise ValueError("real browser did not complete the required interaction inventory")
    if offline and (receipt.get("executed_modes") != ["wasm", "offline"] or
                    "offline-no-network" not in receipt.get("checks", []) or
                    receipt.get("offline_network_resources") is not False):
        raise ValueError("real browser did not complete both Wasm modes without offline network resources")
    if isolated:
        modes = ["wasm", "offline"] if offline else [mode]
        browser_isolated_interactions(receipt, modes)
        delivered = [source_root / "gui/tests/browser_test.py", server, server.parent / "host.py",
                     server.parent / "boot.mjs", server.parent / "browser_composition.mjs",
                     server.parent / "renderer.mjs", server.parent / "index.html",
                     *(server.parent / name for name in BROWSER_SECURITY_ASSETS)]
        delivered += [Path(wasm) / "gui_web_wasm.js", Path(wasm) / "gui_web_wasm.wasm"] if wasm else [Path(executable)]
        if offline:
            delivered.append(offline_html)
        browser_receipt_inputs(receipt, delivered)
        if offline:
            browser_wasm_manifest(offline_html.parent, source_root)
        security = [sys.executable, "-B", str(source_root / "gui/tests/browser_isolation_test.py"),
                    "--browser", engine, "--assets", str(server.parent),
                    "--output", str(evidence / "browser-isolation"), *browser_arguments]
        subprocess.run(security, check=True)
        proof = c.load(evidence / "browser-isolation/qualification.json")
        browser_security_receipt(proof, source_root, server.parent, engine, receipt["browser_version"],
                                 fixture_evidence=evidence / "browser-isolation")
        receipt["renderer_security"] = {"path": "browser-isolation/qualification.json",
                                        "sha256": digest(evidence / "browser-isolation/qualification.json"),
                                        "production_child": proof["production_child"]}
    return receipt


def run_windows_source(command, archive, work, evidence, protected_roots, jobs):
    """Build once, then execute unchanged tests with a qualified host prerequisite."""
    import windows_graphics
    windows_graphics.verify_archive(Path(archive))
    prepare = list(command)
    if prepare[2:4] != ["test", "release"] or "--full" not in prepare:
        raise ValueError("Windows source qualification requires the complete release test command")
    prepare[2] = "build"
    prepare.remove("--full")
    index = prepare.index("--junit")
    del prepare[index:index + 2]
    windows_compiler.run(prepare, cwd=work)
    windows_compiler.run(["cmake", "--build", str(work / "build"), "--target", "foundation-gui-tests",
                          "--parallel", str(jobs)], cwd=work)
    directory = evidence / "windows-graphics"
    directory.mkdir()
    probe = work / "graphics-probe"
    probe.mkdir()
    staged = None
    failed_receipt = None
    try:
        with windows_graphics.qualified_stage(Path(archive), [work / "build/gui"],
                probe_directory=probe, compile_log=directory / "compile.log",
                protected_roots=protected_roots) as staged:
            c.write_new(directory / "probe.json", staged.probe_receipt)
            windows_graphics.run_owned(command, work, directory / "test.log",
                                       environment=staged.environment, timeout=3600)
    except BaseException as error:
        failed_receipt = getattr(error, "graphics_receipt", None)
        raise
    finally:
        c.write_new(directory / "graphics.json", staged.receipt if staged else failed_receipt or
                    {"status": "incomplete", "detail": "graphics setup did not reach the supervised tests"})
    return {"graphics_sha256": digest(directory / "graphics.json"),
            "probe_sha256": digest(directory / "probe.json"), "checks": "full-source"}


def retain_native_visuals(build, evidence):
    """Keep the actual captures after the disposable source/build tree is removed."""
    source = build / "gui/visual-evidence"
    paths = list(source.rglob("*")) if source.is_dir() and not source.is_symlink() else []
    files = [path for path in paths if path.is_file()]
    if (any(path.is_symlink() for path in paths) or not files or len(files) > 100 or
            sum(path.stat().st_size for path in files) > 64 * 1024 * 1024 or
            any(path.suffix not in (".json", ".png", ".ppm", ".log") for path in files) or
            not any(path.name == "qualification.json" for path in files) or
            not {".png", ".ppm"} <= {path.suffix for path in files}):
        raise ValueError("complete bounded native GUI capture evidence is required")
    destination = evidence / "native-visual"
    destination.mkdir()
    for path in files:
        output = destination / path.relative_to(source)
        output.parent.mkdir(parents=True, exist_ok=True)
        with output.open("xb") as stream:
            stream.write(path.read_bytes())
    return {path.relative_to(evidence).as_posix(): digest(path)
            for path in destination.rglob("*") if path.is_file()}


def source_provider_options(source, provider):
    """Select the delivered provider while retaining pre-provider C++ builders."""
    builder = source / "tools/build.py"
    if builder.is_symlink() or not builder.is_file() or builder.stat().st_size > 8 * 1024 * 1024:
        raise ValueError("invalid retained builder capability input")
    tree = ast.parse(builder.read_text(encoding="utf-8"))
    supported = any(isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and
                    node.func.attr == "add_argument" and any(isinstance(arg, ast.Constant) and
                    arg.value == "--core-provider" for arg in node.args) for node in ast.walk(tree))
    if supported:
        return ["--core-provider", provider]
    if provider != "cpp":
        raise ValueError("retained builder cannot select the delivered Rust provider")
    return []


def run_source(candidate, manifest, entry, work, evidence, jobs, recovery=False, browser_options=None):
    browser_target = entry["target"] == "browser-wasm32"
    if not browser_target:
        native_target(entry["target"])
    source = candidate / manifest["source"]["archive"]
    expected = verify_source_archive(source)
    extract(source, work / "source")
    if source_tree(work / "source") != expected:
        raise ValueError("extracted source differs from complete archived inventory")
    group = candidate / "dependencies" / entry["sdk_recipe"]
    group_files = next(x["files"] for x in manifest["dependencies"] if x["recipe_id"] == entry["sdk_recipe"])
    binary_only = not recovery and not any((group / name).exists() for name in group_files if name.endswith("-sources.tar.gz"))
    expected_files = group_files if binary_only else None
    provider = release.provider_identity(entry)
    command = [sys.executable, str(work / "source/tools/build.py"), "test", "release", "--full",
               "--portable", "--build-jobs", str(jobs), "--build-dir", str(work / "build"),
               "--junit", str(evidence / "source.junit.xml"),
               *source_provider_options(work / "source", provider["core_provider"])]
    if entry["target"].startswith("linux-") or browser_target:
        sdk.install(group, entry["sdk_recipe"], work / "sdk", production=True, **({"expected_files": expected_files} if expected_files is not None else {}))
        command += ["--sdk", str(work / "sdk")]
    else:
        import sdk_windows
        # Query the selected actual linker; environment setup must already have
        # used the repository's Windows selector. No compiler media is fetched.
        from windows_toolchain import inspect_selected_linker
        version = inspect_selected_linker()['version']
        sdk_windows.install(group, entry["sdk_recipe"], work / "windows-dependencies", version, **({"expected_files": expected_files} if expected_files is not None else {}))
        command += ["--binary-dependency-group" if binary_only else "--dependency-group", str(group), "--windows-dependencies", str(work / "windows-dependencies")]
    rust_recipe = provider.get("rust_sdk_recipe_id")
    if rust_recipe:
        import rust_sdk
        rust_group = candidate / "dependencies" / rust_recipe
        rust_sdk.install(rust_group, rust_recipe, work / "rust-sdk")
        cpp_sdk = work / "sdk" if (work / "sdk/sdk.json").is_file() else work / "windows-dependencies"
        rust_metadata = rust_sdk.verify_rust_sdk(work / "rust-sdk", cpp_sdk=cpp_sdk,
                                               target=provider["rust_target"], execute=True)
        if (digest(work / "rust-sdk/rust-sdk.json") != provider["rust_sdk_manifest_sha256"]
                or rust_metadata["compiler"]["version"] != provider["rust_compiler_version"]
                or digest(work / "rust-sdk" / rust_metadata["compiler"]["rustc"]) != provider["rust_compiler_sha256"]):
            raise ValueError("recovered Rust SDK differs from delivered compiler identity")
        command += ["--rust-sdk", str(work / "rust-sdk")]
    for recipe in release.dependency_recipes(entry):
        if recipe not in (entry["sdk_recipe"], rust_recipe):
            command += ["--binary-dependency-group" if binary_only else "--dependency-group", str(candidate / "dependencies" / recipe)]
    if entry["backends"] and entry["backends"] != ["core"]:
        gui = work / "source/third_party/retained/gui"
        if not gui.is_dir():
            raise ValueError("GUI source absent from the retained application snapshot")
        command += ["--gui-source", str(gui), "--gui-backends", ",".join(entry["backends"])]
        if not browser_target:
            command += ["--host-tests"]
    # The wrapper checks source identity around compilation and test execution.
    # No base path or fetch fallback is supplied, including during recovery.
    graphics = None
    if entry["target"] == "windows-x86_64" and "rev" in entry["backends"]:
        archive = (browser_options or {}).get("windows_graphics_archive")
        if not archive:
            raise ValueError("Windows Rev source tests require the retained host graphics archive")
        graphics = run_windows_source(command, archive, work, evidence,
            (candidate, work / "source", work / "windows-dependencies"), jobs)
    else:
        windows_compiler.run(command, cwd=work)
    ctest = host_programs(work / "sdk" if (work / "sdk/sdk.json").is_file() else None)["ctest"]
    definitions = json.loads(subprocess.check_output([ctest, "--test-dir", str(work / "build"),
                                                     "--show-only=json-v1"], text=True))["tests"]
    names = sorted(x["name"] for x in definitions)
    if not names or len(names) != len(set(names)):
        raise ValueError("empty or duplicate source test inventory")
    junit = evidence / "source.junit.xml"
    c.junit(junit, names)
    consumer = [sys.executable, str(work / "source/tests/check_install.py"), "--build", str(work / "build"),
                "--source", str(work / "source"), "--config", "Release"]
    if (work / "sdk/sdk.json").is_file():
        consumer += ["--sdk", str(work / "sdk")]
    windows_compiler.run(consumer, cwd=work)
    if not recovery:
        # Source checks also consume the exact delivered library/export. A good
        # rebuilt library cannot mask a broken SDK inside the shipped archive.
        artifact.verify(candidate / entry["archive"], candidate / entry["manifest"],
                        sdk=work / "sdk" if (work / "sdk/sdk.json").is_file() else None,
                        abi=entry["target"].startswith("linux-"), processor=entry["target"].split("-", 1)[1])
    reports = []
    excluded = {}
    for name in names:
        if not name.startswith("tools."):
            continue
        suite = name.removeprefix("tools.")
        original = work / "build/test-reports" / (suite + ".json")
        value = c.tool_report(c.load(original))
        destination = evidence / "tool-reports" / original.name
        destination.parent.mkdir(exist_ok=True)
        shutil.copyfile(original, destination)
        reports.append(destination.relative_to(evidence).as_posix())
        excluded.update(value["excluded"])
    if source_tree(work / "source") != expected:
        raise ValueError("source changed during qualification")
    result = {"executed_tests": names, "junit_sha256": digest(junit), "retained_inputs_only": recovery,
              "tool_reports": reports, "platform_exclusions": excluded, "installed_consumer": "passed"}
    result.update(provider)
    if graphics is not None:
        result["windows_graphics"] = graphics
    if {"framebuffer", "fltk", "rev"} <= set(entry["backends"]):
        result["native_visual"] = retain_native_visuals(work / "build", evidence)
    if not recovery:
        result["delivered_consumer"] = {"status": "passed", "archive_sha256": entry["sha256"]}
    if browser_target:
        result["browser"] = browser_check(work / "source", work / "build/gui/web/serve.py", evidence,
                                           browser_options or {}, wasm=work / "build/gui")
    return result


class AptCommandError(ValueError):
    def __init__(self, message, output, writers_stopped):
        super().__init__(message)
        self.output = output
        self.writers_stopped = writers_stopped


def apt_command(argv, cwd, timeout=180):
    """A timed-out package command must stop all writers before cleanup can begin."""
    import time
    from process_tree import launch
    limit = 16 * 1024 * 1024
    command = ["/usr/bin/env", "LC_ALL=C", "DEBIAN_FRONTEND=noninteractive", *map(str, argv)]
    with tempfile.TemporaryFile() as capture:
        owner = launch(command, cwd, capture)
        started = time.monotonic()
        failure = None
        stopped = False
        code = None
        try:
            while owner.process.poll() is None:
                if time.monotonic() - started > timeout or os.fstat(capture.fileno()).st_size > limit:
                    owner.terminate()
                    owner.wait()
                    raise ValueError("APT command exceeded its time/output bound")
                time.sleep(0.02)
            code = owner.wait()
            owner.finish()
            if os.fstat(capture.fileno()).st_size > limit:
                raise ValueError("APT command exceeded its output bound")
        except BaseException as error:
            failure = error
        finally:
            try:
                owner.close()
                stopped = True
            except BaseException as error:
                failure = error
        capture.seek(0)
        output = capture.read(limit + 1)
        if failure:
            raise AptCommandError(str(failure), output, stopped) from failure
        return subprocess.CompletedProcess(command, code, output)


def apt_preflight(target):
    """Require a disposable native container before any package-manager mutation."""
    native_target(target)
    if (not target.startswith("linux-") or os.environ.get("FOUNDATION_DISPOSABLE_CHECK") != "1"
            or not hasattr(os, "geteuid") or os.geteuid() != 0
            or not any(Path(p).is_file() for p in ("/.dockerenv", "/run/.containerenv"))):
        raise ValueError("APT qualification requires an explicitly selected disposable root container")
    for program in ("apt-get", "dpkg-query", "dpkg-deb", "gpg", "gpgconf", "gpgv", "openssl"):
        if not shutil.which(program):
            raise ValueError("APT qualification prerequisite missing: " + program)


def run_apt(candidate, entry, backend, work, evidence):
    """Exercise real signed HTTPS APT installation, upgrade, tamper refusal and purge."""
    import functools
    import http.server
    import ssl
    import threading
    import apt_repo
    apt_preflight(entry["target"])
    name = "software-foundation-" + backend
    existing = subprocess.run(["dpkg-query", "-W", "-f=${db:Status-Abbrev}", name], capture_output=True, text=True)
    if existing.returncode == 0:
        raise ValueError("disposable APT fixture must not adopt an existing package")
    work.mkdir(parents=True, exist_ok=True)
    evidence.mkdir(parents=True, exist_ok=True)
    log = evidence / "apt.log"
    writers_stopped = True
    def command(argv, *, succeeds=True, private_output=False):
        nonlocal writers_stopped
        with log.open("ab") as output:
            output.write(("+ " + subprocess.list2cmdline([str(x) for x in argv]) + "\n").encode())
            if argv[0] in ("gpg", "gpgconf"):
                # These calls share the explicitly owned private-home agent;
                # the enclosing transaction stops it before relinquishing scope.
                result = subprocess.run([str(x) for x in argv], stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                        env=dict(os.environ, DEBIAN_FRONTEND="noninteractive", LC_ALL="C"), timeout=180)
            else:
                try:
                    result = apt_command(argv, work)
                except AptCommandError as error:
                    writers_stopped = writers_stopped and error.writers_stopped
                    output.write(error.output)
                    raise
            output.write(b"[private fixture key omitted]\n" if private_output else result.stdout)
        if (result.returncode == 0) != succeeds:
            raise ValueError("APT qualification command had an unexpected outcome; inspect apt.log")
        return result.stdout
    arch = {"linux-x86_64": "amd64", "linux-aarch64": "arm64"}[entry["target"]]
    packages = []
    for sequence in (1, 2):
        # Only packaging versions change. Both projections must retain the exact
        # delivered application archive; this is an upgrade of packaging metadata.
        version = "0.0.0+qualification" + str(sequence)
        directory = work / ("package" + str(sequence))
        receipt = apt_repo.package(candidate / entry["archive"], candidate / entry["manifest"],
                                   version, arch, backend, directory)
        packages.append((directory, receipt))
    payload = packages[0][1]["payload"]
    if any((Path("/") / p).exists() or (Path("/") / p).is_symlink() for p in payload):
        raise ValueError("disposable APT fixture found an existing projected path")
    home = work / "keys"; home.mkdir(mode=0o700)
    secret = work / "signing.key"
    cert, key = work / "ca.pem", work / "tls.key"
    webroot = work / "public-repositories"; webroot.mkdir()
    server = None; thread = None; installed = False
    try:
        command(["gpg", "--batch", "--homedir", home, "--pinentry-mode", "loopback", "--passphrase", "",
                 "--quick-generate-key", "Disposable qualification <fixture@example.invalid>", "ed25519", "sign", "1d"])
        secret.write_bytes(command(["gpg", "--batch", "--homedir", home, "--pinentry-mode", "loopback",
                                    "--passphrase", "", "--export-secret-keys"], private_output=True))
        secret.chmod(0o600)
        public = work / "public.key"
        public.write_bytes(command(["gpg", "--batch", "--homedir", home, "--export"]))
        trusted = apt_repo.fingerprint(public)
        command(["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "1",
                 "-keyout", key, "-out", cert, "-subj", "/CN=127.0.0.1",
                 "-addext", "subjectAltName=IP:127.0.0.1", "-addext", "basicConstraints=critical,CA:TRUE"])
        class QuietHandler(http.server.SimpleHTTPRequestHandler):
            def log_message(self, *args):
                pass
        server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(QuietHandler, directory=str(webroot)))
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(cert, key)
        server.socket = context.wrap_socket(server.socket, server_side=True)
        base = "https://127.0.0.1:" + str(server.server_address[1])
        previous = None
        for sequence, (directory, receipt) in enumerate(packages, 1):
            repo = webroot / ("repo" + str(sequence))
            apt_repo.repository([directory / (receipt["package"] + ".json")], repo,
                                base + "/" + repo.name + "/", secret, trusted, sequence)
            previous = apt_repo.verify_repository(repo, trusted, previous=previous)
        keyring = work / "archive-keyring.gpg"
        shutil.copyfile(webroot / "repo1/archive-keyring.gpg", keyring)
        thread = threading.Thread(target=server.serve_forever, name="apt-fixture-server")
        thread.start()
        def options(repository, attempt):
            state = work / ("client-" + attempt); state.mkdir()
            (state / "lists/partial").mkdir(parents=True)
            (state / "cache/archives/partial").mkdir(parents=True)
            source = state / "source.list"
            source.write_text(f"deb [arch={arch} signed-by={keyring}] {base}/{repository}/ ./\n", encoding="utf-8")
            return ["apt-get", "-o", "Dir::Etc::sourcelist=" + str(source), "-o", "Dir::Etc::sourceparts=-",
                    "-o", "Dir::State::lists=" + str(state / "lists"), "-o", "Dir::Cache=" + str(state / "cache"),
                    "-o", "Acquire::https::CaInfo=" + str(cert), "-o", "Acquire::https::Verify-Peer=true",
                    "-o", "Acquire::https::Verify-Host=true", "-o", "Acquire::Retries=0",
                    "-o", "APT::Get::List-Cleanup=0", "-o", "APT::Sandbox::User=root"]
        def inspect(receipt):
            actual = command(["dpkg-query", "-W", "-f=${Version}", name]).decode().strip()
            if actual != receipt["version"]:
                raise ValueError("APT installed another package version")
            for relative, expected in receipt["payload"].items():
                path = Path("/") / relative
                if (path.is_symlink() or not path.is_file() or digest(path) != expected["sha256"]
                        or path.stat().st_size != expected["size"] or path.stat().st_mode & 0o777 != expected["mode"]):
                    raise ValueError("installed APT payload differs from exact archive projection")
            cli = "foundation-cli" + ("-" + backend if backend != "core" else "")
            command(["/usr/bin/" + cli, "--self-check"])
            if backend != "core":
                binary = "foundation-gui-" + ("web" if backend == "hosted-web" else backend)
                command(["/usr/bin/" + binary, "--self-check"])
        valid = None
        for sequence, (_, receipt) in enumerate(packages, 1):
            valid = options("repo" + str(sequence), "valid" + str(sequence))
            command(valid + ["update", "--error-on=any"])
            # Cleanup must purge even if apt exits after unpacking with an error.
            installed = True
            command(valid + ["install", "-y", "--no-install-recommends", name + "=" + receipt["version"]])
            inspect(receipt)
        shutil.copytree(webroot / "repo2", webroot / "tampered")
        signed = webroot / "tampered/InRelease"
        signed.write_bytes(signed.read_bytes().replace(b"Suite: stable", b"Suite: tampered", 1))
        refused = command(options("tampered", "tampered") + ["update", "--error-on=any"], succeeds=False)
        if b"BADSIG" not in refused and b"invalid signature" not in refused.lower():
            raise ValueError("negative APT test failed before signature rejection")
        # A failed refresh must not modify the already installed exact payload.
        inspect(packages[-1][1])
        command(valid + ["purge", "-y", name]); installed = False
        if any((Path("/") / p).exists() for p in packages[-1][1]["payload"]):
            raise ValueError("APT removal left owned application files")
        after = subprocess.run(["dpkg-query", "-W", "-f=${db:Status-Abbrev}", name], capture_output=True)
        if after.returncode == 0 and after.stdout.strip() != b"un":
            raise ValueError("APT removal left package state")
        return {"archive_sha256": entry["sha256"], "signing_fingerprint": trusted,
                "versions": [r["version"] for _, r in packages], "real_package_manager": "apt-get",
                "checks": ["signed-https-update", "install", "exact-installed-payload", "runtime",
                           "upgrade", "tamper-rejection", "purge"], "log": "apt.log"}
    finally:
        cleanup_error = (None if writers_stopped else
                         ValueError("writer termination uncertain; package cleanup requires container disposal"))
        try:
            if installed and writers_stopped:
                # Use the same isolated index that supplied the attempted install.
                # A failed download can leave no installed record; the default
                # host index may not even know this fixture package.
                command(valid + ["purge", "-y", name])
        except Exception as error:
            cleanup_error = error
        try:
            if server:
                if thread:
                    server.shutdown(); thread.join(timeout=10)
                    if thread.is_alive():
                        raise ValueError("APT fixture server did not stop")
                server.server_close()
        except Exception as error:
            cleanup_error = cleanup_error or error
        try:
            command(["gpgconf", "--homedir", home, "--kill", "gpg-agent"])
        except Exception as error:
            cleanup_error = cleanup_error or error
        if cleanup_error:
            raise ValueError("APT fixture cleanup failed; dispose of its container") from cleanup_error


@contextmanager
def qualification_work(evidence):
    """Do not erase outputs when driver cleanup or writer completion is uncertain."""
    import windows_graphics
    work = Path(tempfile.mkdtemp(prefix="foundation-exact-release-"))
    retain = False
    try:
        yield work
    except BaseException as error:
        retain = windows_graphics.retain_required(error)
        if retain:
            c.write_new(evidence / "retained-work.json", {
                "status": "incomplete", "workspace": str(work),
                "reason": "graphics cleanup or descendant completion requires reconciliation"})
        raise
    finally:
        if not retain:
            shutil.rmtree(work)


def check(candidate, target, backend, scope, evidence, jobs=2, browser_options=None, *, execution=None, receipt_name="qualification.json"):
    if scope not in ("source", "archive", "recovery", "abi", "apt") or jobs < 1:
        raise ValueError("unsupported qualification operation")
    candidate = candidate.resolve(strict=True)
    manifest = release.verify_selection(candidate, target, backend, scope)
    before = digest(candidate / "release.json")
    entry = select(manifest, target, backend)
    if execution is not None:
        c.fields(execution, {"schema_version", "plan", "subject", "execution", "checks", "backends", "target", "environment", "scope", "run_id", "attempt", "host"})
        if (scope not in ("source", "recovery", "abi") or target == "browser-wasm32" or
                execution["target"] != target or execution["scope"] != scope or
                execution["backends"] != sorted(entry["backends"] or ["core"]) or
                backend not in execution["backends"] or execution["host"] != c.host_identity() or
                execution["subject"]["source_sha256"] != manifest["source"]["sha256"] or
                execution["subject"]["inventory_sha256"] != before):
            raise ValueError("grouped execution must cover the exact complete native artifact")
    if target != "browser-wasm32":
        native_target(target)
    elif backend != "wasm" or scope in ("abi", "apt"):
        raise ValueError("browser target requires its Wasm backend and supported scope")
    graphics_archive = (browser_options or {}).get("windows_graphics_archive")
    graphics_needed = (target == "windows-x86_64" and
        ((scope in ("source", "recovery") and "rev" in entry["backends"]) or
         (scope == "archive" and backend == "rev")))
    if graphics_needed != (graphics_archive is not None):
        raise ValueError("provide one retained graphics archive only for Windows Rev runtime scopes")
    prerequisite = browser_prerequisite_snapshot(browser_options or {}, target, backend, scope,
        {"source_sha256": manifest["source"]["sha256"], "inventory_sha256": before})
    evidence.mkdir(parents=True, exist_ok=True)
    receipt = c.local(evidence, receipt_name)
    if receipt.exists():
        raise ValueError("qualification receipt must be a new attempt")
    with qualification_work(evidence) as work:
        if scope in ("source", "recovery"):
            inputs = candidate
            if scope == "recovery":
                # Recover only this target's complete source/dependency closure.
                recovered = work / 'recovered'; recovered.mkdir()
                shutil.copyfile(candidate / manifest['source']['archive'], recovered / manifest['source']['archive'])
                kinds = release.dependency_kinds(manifest['artifacts'])
                for recipe in release.dependency_recipes(entry):
                    release.copy_dependency_group(candidate / 'dependencies' / recipe,
                        recovered / 'dependencies' / recipe, recipe, kinds[recipe])
                # Recovery outputs deliberately omit application binaries. Rebuild
                # from only the retained source and groups, not from the base.
                inputs = work / "recovered"
            details = run_source(inputs, manifest, entry, work / "qualification", evidence, jobs, scope == "recovery", browser_options)
        elif scope == "apt":
            details = run_apt(candidate, entry, backend, work / "apt", evidence)
        elif scope == "archive":
            graphics_result = None
            if target != "browser-wasm32":
                extra = ({"windows_graphics_archive": graphics_archive,
                          "windows_graphics_evidence": evidence / "windows-graphics"} if graphics_needed else {})
                graphics_result = artifact.verify(candidate / entry["archive"], candidate / entry["manifest"], runtime_only=True,
                                abi=target.startswith("linux-"), processor=target.split("-", 1)[1], backend=backend, **extra)
            details = {"archive_sha256": entry["sha256"], "relocation": "passed"}
            if graphics_needed:
                if not isinstance(graphics_result, dict) or not graphics_result.get("windows_graphics"):
                    raise ValueError("packaged Windows Rev runtime omitted its graphics evidence")
                details["windows_graphics"] = graphics_result["windows_graphics"]
            if backend in ("wasm", "hosted-web"):
                extract(candidate / manifest["source"]["archive"], work / "source")
                prefix = work / "relocated archive"
                prefix.mkdir()
                artifact.inspect_archive(candidate / entry["archive"], prefix)
                servers = list(prefix.rglob("share/software-foundation/web/serve.py"))
                if len(servers) != 1:
                    raise ValueError("packaged browser assets missing or ambiguous")
                server = servers[0]
                if backend == "wasm":
                    details["browser"] = browser_check(work / "source", server, evidence, browser_options or {}, wasm=server.parent)
                else:
                    suffix = ".exe" if os.name == "nt" else ""
                    binaries = list(prefix.rglob("bin/foundation-gui-web" + suffix))
                    if len(binaries) != 1:
                        raise ValueError("packaged hosted browser executable missing or ambiguous")
                    details["browser"] = browser_check(work / "source", server, evidence, browser_options or {}, executable=binaries[0])
        else:
            root = work / "archive"
            root.mkdir()
            artifact.inspect_archive(candidate / entry["archive"], root)
            if not target.startswith("linux-"):
                raise ValueError("ELF audit is a Linux qualification scope")
            details = audit(root, target.split("-", 1)[1])
    bind_browser_prerequisite(prerequisite, details, evidence)
    release.verify_selection(candidate, target, backend, scope)
    if digest(candidate / "release.json") != before:
        raise ValueError("candidate changed during qualification")
    result = {"schema_version": 1, "source_sha256": manifest["source"]["sha256"],
              "inventory_sha256": before, "target": target, "backend": backend, "scope": scope,
              "host": c.host_identity(), "status": "passed", "details": details,
              "assertions": ["immutable-candidate", "exact-target-backend", scope + "-contract"],
              "evidence": {}}
    retained = (["source.junit.xml", *details.get("tool_reports", [])] if scope in ("source", "recovery") else [])
    if scope == "apt":
        retained += ["apt.log"]
    if "browser" in details:
        retained += browser_evidence_paths(evidence, details["browser"])
    if "windows_graphics" in details:
        retained += [p.relative_to(evidence).as_posix() for p in (evidence / "windows-graphics").rglob("*") if p.is_file()]
    retained += list(details.get("native_visual", {}))
    result["evidence"] = {name: digest(evidence / name) for name in retained}
    if execution is not None:
        c.write_new(evidence / "execution.json", execution)
        result["details"]["execution"] = execution
        result["evidence"]["execution.json"] = digest(evidence / "execution.json")
    c.write_new(receipt, result)
    return result


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("scope", choices=("source", "archive", "recovery", "abi", "apt"))
    p.add_argument("--release", type=Path, required=True)
    p.add_argument("--target", required=True)
    p.add_argument("--backend", required=True)
    p.add_argument("--evidence", type=Path, required=True)
    p.add_argument("--jobs", default="auto")
    p.add_argument("--execution-plan", type=Path)
    p.add_argument("--execution-id")
    p.add_argument("--run-id")
    p.add_argument("--attempt", type=int)
    p.add_argument("--receipt", default="qualification.json")
    p.add_argument("--browser", choices=("firefox", "chromium"), default="firefox")
    p.add_argument("--firefox", default="firefox")
    p.add_argument("--browser-executable")
    p.add_argument("--driver", default="chromedriver")
    p.add_argument("--browser-prerequisite", type=Path)
    p.add_argument("--browser-prerequisite-plan", type=Path)
    p.add_argument("--windows-graphics-archive", type=Path)
    a = p.parse_args()
    execution = None
    if any((a.execution_plan, a.execution_id, a.run_id, a.attempt)):
        if not all((a.execution_plan, a.execution_id, a.run_id, a.attempt)):
            raise ValueError("complete execution plan and run identity required")
        plan = c.validate(c.load(a.execution_plan))
        members = [x for x in c.executions(plan) if x["id"] == a.execution_id]
        if len(members) != 1 or "execution" not in members[0]:
            raise ValueError("unknown physical execution")
        leader = members[0]
        if (leader["target"], leader["backend"], leader["scope"], leader["qualification"]) != (a.target, a.backend, a.scope, a.receipt):
            raise ValueError("execution command differs from frozen leader")
        execution = c.execution_identity(plan, leader, a.run_id, a.attempt, c.host_identity())
    check(a.release, a.target, a.backend, a.scope, a.evidence, __import__("build_capacity").compile_jobs(a.jobs),
          {key: getattr(a, key) for key in ("browser", "firefox", "browser_executable", "driver", "browser_prerequisite", "browser_prerequisite_plan", "windows_graphics_archive")}, execution=execution, receipt_name=a.receipt)


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, KeyError, subprocess.CalledProcessError) as error:
        print("release check: " + str(error), file=sys.stderr)
        sys.exit(1)
