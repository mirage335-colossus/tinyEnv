#!/usr/bin/env python3
"""Inventory and verify a locally produced package, then test it after relocation."""
import argparse
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
import re
import unicodedata
import zipfile

MAX_BYTES = 256 * 1024 * 1024
MAX_FILES = 10000


def member_path(name):
    path = PurePosixPath(name)
    if path.is_absolute() or ".." in path.parts or "\\" in name or ":" in name or not path.parts:
        raise ValueError("unsafe archive path: " + name)
    for part in path.parts:
        if (part.endswith((".", " ")) or any(ord(c) < 32 for c in part)
                or re.fullmatch(r"(?i:CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\..*)?", part)):
            raise ValueError("unsafe portable archive component")
    return path


def inspect_archive(archive, destination=None, *, contents=None):
    """Validate all members, optionally extracting and collecting selected contents.

    ``contents`` maps exact member paths to bytes; only its existing keys are read
    back to the caller. The complete archive still receives every safety check.
    """
    inventory = {}
    seen = set()
    total = 0

    def consume(name, size, directory, mode, stream):
        nonlocal total
        if mode & 0o7000:
            raise ValueError("unexpected privileged archive permissions")
        path = member_path(name)
        if path.name.casefold() in ("opengl32.dll", "libgallium_wgl.dll"):
            raise ValueError("host graphics DLLs must not be embedded in an application archive")
        canonical = unicodedata.normalize("NFC", str(path)).casefold()
        if canonical in seen:
            raise ValueError("duplicate archive path")
        seen.add(canonical)
        total += size
        if total > MAX_BYTES or len(seen) > MAX_FILES:
            raise ValueError("archive exceeds example limits")
        target = destination.joinpath(*path.parts) if destination else None
        if directory:
            if target:
                target.mkdir(parents=True, exist_ok=True)
            return
        data = stream.read(MAX_BYTES + 1)
        if len(data) != size:
            raise ValueError("archive member size mismatch")
        inventory[str(path)] = {"size": size, "sha256": hashlib.sha256(data).hexdigest()}
        if contents is not None and str(path) in contents:
            contents[str(path)] = data
        if target:
            target.parent.mkdir(parents=True, exist_ok=True)
            with target.open("xb") as out:
                out.write(data)
            target.chmod(0o755 if mode & 0o111 else 0o644)

    if zipfile.is_zipfile(archive):
        with zipfile.ZipFile(archive) as bundle:
            for item in bundle.infolist():
                mode = item.external_attr >> 16
                if stat.S_ISLNK(mode) or (stat.S_IFMT(mode) not in (0, stat.S_IFREG, stat.S_IFDIR)):
                    raise ValueError("unsupported archive entry")
                with bundle.open(item) as stream:
                    consume(item.filename, item.file_size, item.is_dir(), mode, stream)
    else:
        with tarfile.open(archive, "r:*") as bundle:
            for item in bundle:
                if not (item.isfile() or item.isdir()):
                    raise ValueError("unsupported archive entry")
                stream = bundle.extractfile(item) if item.isfile() else None
                consume(item.name, item.size, item.isdir(), item.mode, stream)
                if stream:
                    stream.close()
    if not inventory:
        raise ValueError("empty archive")
    return inventory


def describe(archive, destination=None, *, contents=None):
    def checksum():
        with archive.open("rb") as stream:
            value = hashlib.sha256()
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                value.update(chunk)
            return value.hexdigest()
    before = checksum()
    files = inspect_archive(archive, destination, contents=contents)
    if checksum() != before:
        raise ValueError("archive changed during inspection")
    return {"schema_version": 1, "archive": archive.name, "sha256": before, "files": files}


@contextmanager
def _workspace():
    directory = Path(tempfile.mkdtemp(prefix="foundation package "))
    disposition = {"retain": False}
    try:
        yield directory, disposition
    except BaseException as error:
        tools = str(Path(__file__).resolve().parent)
        if tools not in sys.path:
            sys.path.insert(0, tools)
        from windows_graphics import retain_required
        disposition["retain"] = disposition["retain"] or retain_required(error)
        raise
    finally:
        # A failed supervisor must never trigger removal beneath possible writers.
        if not disposition["retain"]:
            shutil.rmtree(directory)


def _windows_rev_smoke(executable, prefix, clean, archive, evidence, workspace, disposition, sdk):
    tools = str(Path(__file__).resolve().parent)
    if tools not in sys.path:
        sys.path.insert(0, tools)
    import windows_graphics
    evidence = Path(evidence).absolute()
    resolved = evidence.resolve()
    protected = [prefix.resolve(), workspace.resolve()]
    if sdk:
        protected.append(sdk.resolve())
    if any(resolved == value or value in resolved.parents or resolved in value.parents for value in protected):
        raise ValueError("graphics evidence must be outside the extracted package, probe workspace and SDK")
    if evidence.is_symlink() or evidence.exists():
        raise ValueError("graphics evidence requires a fresh external directory")
    evidence.mkdir()
    probe = workspace / "graphics probe"
    probe.mkdir()
    # Keep selected compiler tools available only to compile/probe qualification.
    developer = {key: value for key, value in os.environ.items() if key not in
                 ("LD_LIBRARY_PATH", "LD_PRELOAD", "DYLD_LIBRARY_PATH", "DYLD_INSERT_LIBRARIES")}
    staged = None
    smoke = None
    failure = None
    receipt = None
    try:
        with windows_graphics.qualified_stage(
                archive, [executable.parent], probe_directory=probe,
                compile_log=evidence / "compile.log", environment=developer,
                protected_roots=([sdk] if sdk else [])) as staged:
            environment = {key: value for key, value in staged.environment.items() if key.upper() != "PATH"}
            environment["PATH"] = clean["PATH"]
            smoke = windows_graphics.run_owned(
                [str(executable), "--smoke-test"], prefix, evidence / "test.log",
                environment=environment, timeout=60, max_bytes=64 * 1024)
            if (evidence / "test.log").read_text(encoding="utf-8") != "software-foundation gui smoke: ok\n":
                raise ValueError("packaged GUI smoke contract did not complete")
        receipt = staged.receipt
        if receipt.get("cleanup") != "removed":
            raise ValueError("graphics qualification did not confirm staged file removal")
    except BaseException as error:
        failure = error
        raise
    finally:
        if staged is not None:
            receipt = staged.receipt
        elif failure is not None:
            receipt = getattr(failure, "graphics_receipt", None)
        if (windows_graphics.retain_required(failure) or not receipt
                or receipt.get("cleanup") != "removed"):
            disposition["retain"] = True
        report = {"schema_version": 1, "status": "failed" if failure else "passed",
                  "stage": receipt, "smoke": smoke,
                  "error": str(failure)[:1024] if failure else "",
                  "retained_workspace": str(workspace) if disposition["retain"] else None}
        with (evidence / "graphics.json").open("x", encoding="utf-8") as output:
            json.dump(report, output, indent=2); output.write("\n")
        if receipt and receipt.get("native_probe"):
            with (evidence / "probe.json").open("x", encoding="utf-8") as output:
                json.dump(receipt["native_probe"], output, indent=2); output.write("\n")
    return report


def verify(archive, manifest, runtime_only=False, abi=False, processor="x86_64", sdk=None, backend="core", *,
           windows_graphics_archive=None, windows_graphics_evidence=None):
    graphics_required = os.name == "nt" and backend == "rev"
    if graphics_required and (windows_graphics_archive is None or windows_graphics_evidence is None):
        raise ValueError("Windows Rev verification requires retained graphics archive and external evidence directory")
    if not graphics_required and (windows_graphics_archive is not None or windows_graphics_evidence is not None):
        raise ValueError("host graphics qualification inputs apply only to Windows Rev verification")
    graphics_result = None
    expected = json.loads(manifest.read_text())
    browser_sdk = bool(sdk and json.loads((sdk / "sdk.json").read_text())["target"]["system"] == "Emscripten")
    with _workspace() as (temp, disposition):
        prefix = Path(temp) / "relocated prefix"
        prefix.mkdir()
        if describe(archive, prefix) != expected:
            raise ValueError("archive identity or member inventory mismatch")
        if abi:
            tools = str(Path(__file__).resolve().parent)
            if tools not in sys.path:
                sys.path.insert(0, tools)
            from verify_abi import audit
            audit(prefix, processor)
        if os.name == "nt":
            tools = str(Path(__file__).resolve().parent)
            if tools not in sys.path:
                sys.path.insert(0, tools)
            from verify_pe import audit
            audit(prefix, processor)
        suffix = ".js" if browser_sdk else (".exe" if os.name == "nt" else "")
        name = "foundation-cli" + suffix
        candidates = list(prefix.rglob(name))
        if len(candidates) != 1 or candidates[0].parent.name != "bin":
            raise ValueError("expected exactly one packaged CLI")
        executable = candidates[0]
        clean = {key: value for key, value in os.environ.items() if key not in
                 ("LD_LIBRARY_PATH", "LD_PRELOAD", "DYLD_LIBRARY_PATH", "DYLD_INSERT_LIBRARIES")}
        if os.name == "nt":
            system_root = Path(os.environ["SystemRoot"])
            clean["PATH"] = os.pathsep.join([str(executable.parent), str(system_root / "System32"), str(system_root)])
        executor = [str(sdk / "node/bin/node")] if browser_sdk else []
        result = subprocess.run([*executor, str(executable), "--version"], cwd=prefix, env=clean,
                                check=True, text=True, capture_output=True)
        if result.stdout != "software-foundation 0.1.0\n":
            raise ValueError("unexpected packaged version")
        subprocess.run([*executor, str(executable), "--self-check"], cwd=prefix, env=clean, check=True)
        if backend != "core":
            hosts = {name: name for name in ("terminal", "framebuffer", "fltk", "rev", "sdl")}
            hosts["hosted-web"] = "web"
            if backend not in hosts:
                raise ValueError("this native artifact verifier needs a supported backend")
            name = "foundation-gui-" + hosts[backend] + (".exe" if os.name == "nt" else "")
            hosts_found = list(prefix.rglob(name))
            if len(hosts_found) != 1 or hosts_found[0].parent.name != "bin":
                raise ValueError("packaged backend absent or ambiguous")
            if graphics_required:
                graphics_result = _windows_rev_smoke(
                    hosts_found[0], prefix, clean, windows_graphics_archive,
                    windows_graphics_evidence, temp, disposition, sdk)
            else:
                smoke = subprocess.run([str(hosts_found[0]), "--smoke-test"], cwd=prefix,
                                       env=clean, check=True, timeout=60, text=True, capture_output=True)
                if smoke.stdout != "software-foundation gui smoke: ok\n":
                    raise ValueError("packaged GUI smoke contract did not complete")
        if runtime_only:
            return {"windows_graphics": graphics_result} if graphics_result else None
        # Use only the extracted SDK export to compile a separate consumer.
        source = Path(__file__).resolve().parents[1] / "examples/consumer"
        consumer = Path(temp) / "consumer source"
        shutil.copytree(source, consumer)
        build = Path(temp) / "consumer build"
        configs = list(prefix.rglob("FoundationConfig.cmake"))
        if len(configs) != 1:
            raise ValueError("packaged SDK export missing or ambiguous")
        extra = []
        cmake = "cmake"
        compiler_environment = os.environ.copy()
        if sdk:
            tools = str(Path(__file__).resolve().parent)
            if tools not in sys.path:
                sys.path.insert(0, tools)
            from build import host_programs, sdk_identity
            sdk = sdk.resolve(strict=True)
            sdk_before = sdk_identity(sdk)
            programs = host_programs(sdk)
            cmake = programs["cmake"]
            compiler_environment["PYTHONDONTWRITEBYTECODE"] = "1"
            extra = ["-DCMAKE_TOOLCHAIN_FILE=" + str(Path(__file__).resolve().parents[1] / "cmake/toolchains/sdk.cmake"),
                     "-DFOUNDATION_SDK_ROOT=" + str(sdk)]
            if programs["ninja"] != "ninja":
                extra += ["-DCMAKE_MAKE_PROGRAM=" + programs["ninja"]]
        tools = str(Path(__file__).resolve().parent)
        if tools not in sys.path:
            sys.path.insert(0, tools)
        import windows_compiler
        windows_compiler.run([cmake, "-S", str(consumer), "-B", str(build), "-G", "Ninja",
                        "-DCMAKE_BUILD_TYPE=Release", "-DFoundation_DIR=" + str(configs[0].parent),
                        "-DCMAKE_FIND_USE_PACKAGE_REGISTRY=OFF", "-DCMAKE_FIND_USE_SYSTEM_PACKAGE_REGISTRY=OFF", *extra],
                       env=compiler_environment)
        windows_compiler.run([cmake, "--build", str(build), "--parallel", "2"], env=compiler_environment)
        subprocess.run([*executor, str(build / ("consumer" + suffix))], check=True)
        if sdk and sdk_identity(sdk) != sdk_before:
            raise ValueError("SDK changed during installed-consumer validation")
        return {"windows_graphics": graphics_result} if graphics_result else None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("create", "verify"))
    parser.add_argument("archive", type=Path)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--runtime-only", action="store_true", help="copied-archive runtime check without a consumer compiler")
    parser.add_argument("--abi", action="store_true", help="audit every shipped ELF against Bookworm before execution")
    parser.add_argument("--processor", choices=("x86_64", "aarch64"), default="x86_64")
    parser.add_argument("--sdk", type=Path, help="matching prepared toolchain for installed-library consumer")
    parser.add_argument("--backend", default="core", choices=("core", "terminal", "framebuffer", "fltk", "rev", "sdl", "hosted-web"))
    parser.add_argument("--windows-graphics-archive", type=Path, help="retained host input for native Windows Rev validation")
    parser.add_argument("--windows-graphics-evidence", type=Path, help="fresh external directory for graphics qualification evidence")
    args = parser.parse_args()
    if args.archive.resolve() == args.manifest.resolve():
        raise ValueError("manifest must not overwrite its archive")
    if args.action == "create":
        if args.windows_graphics_archive is not None or args.windows_graphics_evidence is not None:
            raise ValueError("host graphics inputs are supported only by verify")
        args.manifest.write_text(json.dumps(describe(args.archive), indent=2) + "\n")
    else:
        verify(args.archive, args.manifest, args.runtime_only, args.abi, args.processor, args.sdk, args.backend,
               windows_graphics_archive=args.windows_graphics_archive,
               windows_graphics_evidence=args.windows_graphics_evidence)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (OSError, ValueError, subprocess.CalledProcessError, tarfile.TarError, zipfile.BadZipFile) as error:
        print("artifact: " + str(error), file=sys.stderr)
        sys.exit(1)
