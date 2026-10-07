#!/usr/bin/env python3
"""Wrap verified archives and assemble a local signed flat APT repository."""
import argparse
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime, parsedate_to_datetime
import gzip
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import zipfile
from urllib.parse import urlsplit

TOOLS = str(Path(__file__).resolve().parent)
if TOOLS not in sys.path:
    sys.path.insert(0, TOOLS)
from verify_abi import audit as audit_abi


def sibling(name):
    spec = importlib.util.spec_from_file_location("apt_" + name, Path(__file__).with_name(name + ".py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


c = sibling("coverage")
artifact = sibling("artifact")
BACKENDS = {"core", "terminal", "framebuffer", "fltk", "rev", "sdl", "hosted-web"}
GUI_EXECUTABLES = {"foundation-gui-" + name for name in ("terminal", "framebuffer", "fltk", "rev", "sdl", "web")}
SELECTION_PATH = "share/doc/Foundation/debian-selection.json"


def runtime_dependencies(backend):
    if backend not in BACKENDS: raise ValueError('unsupported backend runtime policy')
    dependencies = ['libc6 (>= 2.36)']
    if backend == 'hosted-web': dependencies.append('python3')
    if backend == 'fltk': dependencies.extend(['fontconfig-config', 'fonts-dejavu-core'])
    if backend in ('rev', 'sdl'): dependencies.append('libglx-mesa0')
    return ', '.join(dependencies)


def encoded(value):
    return (json.dumps(value, sort_keys=True, indent=2, allow_nan=False) + "\n").encode()


def byte_record(data, mode):
    return {"sha256": hashlib.sha256(data).hexdigest(), "size": len(data), "mode": mode}


def source_modes(archive):
    if zipfile.is_zipfile(archive):
        with zipfile.ZipFile(archive) as bundle:
            return {str(artifact.member_path(item.filename)): (item.external_attr >> 16) & 0o777 for item in bundle.infolist() if not item.is_dir()}
    with tarfile.open(archive, "r:*") as bundle:
        return {str(artifact.member_path(item.name)): item.mode & 0o777 for item in bundle if item.isfile()}


def selection(archive_root, files, backend, archive_sha256):
    if backend not in BACKENDS or not re.fullmatch(r"[0-9a-f]{64}", archive_sha256):
        raise ValueError("invalid backend selection identity")
    if len(artifact.member_path(archive_root).parts) != 1:
        raise ValueError("selection needs one archive root")
    if not isinstance(files, dict) or not files or len(files) > artifact.MAX_FILES:
        raise ValueError("invalid source file inventory")
    seen = set()
    for name, record in files.items():
        artifact.member_path(name)
        if name.casefold() in seen or not isinstance(record, dict) or set(record) != {"size", "mode", "sha256"}:
            raise ValueError("invalid source file inventory entry")
        seen.add(name.casefold())
        if (type(record["size"]) is not int or not 0 <= record["size"] <= artifact.MAX_BYTES or
                type(record["mode"]) is not int or record["mode"] not in (0o644, 0o755) or
                not re.fullmatch(r"[0-9a-f]{64}", record["sha256"])):
            raise ValueError("invalid source file inventory identity")
    public = {name: record for name, record in files.items() if name.startswith("bin/")}
    known = {"bin/" + name for name in {"foundation-cli", *GUI_EXECUTABLES}}
    selected = {"bin/foundation-cli"}
    if backend != "core":
        selected.add("bin/foundation-gui-" + ("web" if backend == "hosted-web" else backend))
    if not selected <= public.keys() or not public.keys() <= known or any(x["mode"] != 0o755 for x in public.values()):
        raise ValueError("unexpected, nonexecutable or missing public executable")
    if SELECTION_PATH in files:
        raise ValueError("generated selection receipt collides with archive content")
    generated = artifact.member_path(SELECTION_PATH)
    expected_paths = {str(part).casefold(): str(part) for part in (generated, *generated.parents) if str(part) != "."}
    for name in files:
        existing = artifact.member_path(name)
        if name.casefold() in expected_paths:
            raise ValueError("generated selection receipt or ancestor collides with archive content")
        for part in existing.parents:
            text = str(part)
            if text.casefold() in expected_paths and text != expected_paths[text.casefold()]:
                raise ValueError("generated selection receipt has a case-aliased ancestor")
    excluded = {name: record for name, record in public.items() if name not in selected}
    kept = {name: record for name, record in files.items() if name not in excluded}
    return {"schema_version": 1, "backend": backend, "archive_sha256": archive_sha256,
            "archive_root": archive_root, "source_file_inventory_sha256": hashlib.sha256(encoded(files)).hexdigest(),
            "selected_executables": {name: public[name] for name in sorted(selected)},
            "excluded_executables": excluded, "retained_files": kept}


def launchers(backend, selected):
    result = {}
    for name in sorted(selected):
        binary = Path(name).name
        public = binary + ("-" + backend if binary == "foundation-cli" and backend != "core" else "")
        result["usr/bin/" + public] = f'#!/bin/sh\nexec /opt/software-foundation/{backend}/bin/{binary} "$@"\n'.encode()
    return result


def desktop_files(backend, retained):
    """Generated consumer entries; image-output framebuffer has no desktop window.

    The browser launcher keeps a visible terminal as its lifetime owner: Ctrl+C
    closes the loopback server and child sessions. It never detaches a hidden host.
    """
    if backend not in ('terminal', 'fltk', 'rev', 'sdl', 'hosted-web'):
        return {}
    public = 'foundation-gui-' + ('web' if backend == 'hosted-web' else backend)
    if 'bin/' + public not in retained:
        return {}
    result = {}
    if backend == 'hosted-web':
        web = 'share/software-foundation/web/'
        if not {web + name for name in ('serve.py', 'host.py', 'index.html', 'boot.mjs', 'renderer.mjs', 'style.css',
                                       'browser_lifecycle.mjs', 'wasm_transport.mjs', 'browser_presenter.mjs',
                                       'file_services.mjs', 'wasm_worker.mjs')} <= set(retained):
            return {}  # Older/minimal archives may only contain the wire protocol executable.
        public = 'foundation-gui-browser'
        script = ("#!/usr/bin/python3\n"
                  "\"\"\"Open the installed loopback UI; Ctrl+C stops the host and its sessions.\"\"\"\n"
                  "import runpy\nimport webbrowser\n"
                  "host = runpy.run_path('/opt/software-foundation/hosted-web/share/software-foundation/web/serve.py')['boundary']\n"
                  "server = host.Host(('127.0.0.1', 0), '/opt/software-foundation/hosted-web/bin/foundation-gui-web')\n"
                  "url = 'http://' + server.authority + '/'\n"
                  "print('Browser UI: ' + url + '\\nPress Ctrl+C in this terminal to stop.', flush=True)\n"
                  "try:\n"
                  "    if not webbrowser.open(url):\n        print('Open the URL above in your browser.', flush=True)\n"
                  "    server.serve_forever()\n"
                  "except KeyboardInterrupt:\n    pass\n"
                  "finally:\n    server.server_close()\n")
        result['usr/bin/' + public] = (script.encode(), 0o755)
    terminal = 'true' if backend in ('terminal', 'hosted-web') else 'false'
    entry = (f'[Desktop Entry]\nType=Application\nName=Software Foundation ({backend})\n'
             f'Comment=Generic application example\nExec={public}\nTryExec={public}\n'
             f'Terminal={terminal}\nCategories=Utility;\nStartupNotify=false\n')
    result['usr/share/applications/software-foundation-' + backend + '.desktop'] = (entry.encode(), 0o644)
    return result



def offline_desktop_files(backend, retained):
    """Schema 4 addition; older projections never gain files retroactively."""
    base = 'share/software-foundation/'
    prefix = base + 'wasm/'
    required = {prefix + name for name in ('software-foundation-wasm.html', 'web-manifest.json', 'manifest.sha256')}
    required.update(base + name for name in ('open-offline.sh', 'open-offline.cmd'))
    present = {name for name in retained if name.startswith(prefix) or name in required}
    if not present:
        return {}
    if present != required:
        raise ValueError('Incomplete installed offline Wasm package')
    public = 'foundation-gui-offline-' + backend
    script = ('#!/bin/sh\nexec /opt/software-foundation/' + backend + '/' + base + 'open-offline.sh "$@"\n').encode()
    entry = (f'[Desktop Entry]\nType=Application\nName=Software Foundation (offline browser, {backend})\n'
             f'Comment=Run the installed application document without a server\nExec={public}\nTryExec={public}\n'
             'Terminal=false\nCategories=Utility;\nStartupNotify=false\n').encode()
    return {'usr/bin/' + public: (script, 0o755),
            'usr/share/applications/software-foundation-offline-' + backend + '.desktop': (entry, 0o644)}


def installed_entries(backend, retained, schema):
    result = desktop_files(backend, retained) if schema >= 3 else {}
    if schema >= 4:
        result.update(offline_desktop_files(backend, retained))
    return result


def manual_paths(backend, files):
    suffix = "-" + backend if backend != "core" else ""
    mapping = {"share/man/man1/foundation-cli.1": "usr/share/man/man1/foundation-cli" + suffix + ".1",
               "share/man/man7/software-foundation.7": "usr/share/man/man7/software-foundation-" + backend + ".7"}
    if any(files[source]["mode"] != 0o644 for source in mapping if source in files):
        raise ValueError("manual pages must have ordinary data-file permissions")
    return {source: destination for source, destination in mapping.items() if source in files}


def projected_payload(chosen, schema=4):
    backend = chosen["backend"]
    private = "opt/software-foundation/" + backend + "/"
    result = {private + name: value for name, value in chosen["retained_files"].items()}
    result[private + SELECTION_PATH] = byte_record(encoded(chosen), 0o644)
    result.update({name: byte_record(data, 0o755) for name, data in launchers(backend, chosen["selected_executables"]).items()})
    result.update({destination: chosen["retained_files"][source]
                   for source, destination in manual_paths(backend, chosen["retained_files"]).items()})
    if schema >= 3:
        result.update({name: byte_record(data, mode) for name, (data, mode) in installed_entries(backend, chosen["retained_files"], schema).items()})
    return result


def run(*argv):
    return subprocess.run([str(a) for a in argv], check=True, capture_output=True).stdout


def full_fingerprint(value):
    if not isinstance(value, str) or not re.fullmatch(r"(?:[0-9a-fA-F]{40}|[0-9a-fA-F]{64})", value):
        raise ValueError("a complete trusted fingerprint is required")
    return value.upper()


def fingerprint(path):
    with tempfile.TemporaryDirectory(prefix="foundation public key ") as temp:
        output = run("gpg", "--batch", "--homedir", temp, "--with-colons", "--show-keys", path).decode()
    values, pending = [], False
    for line in output.splitlines():
        row = line.split(":")
        if row[0] == "pub":
            pending = True
        elif row[0] == "fpr" and pending:
            values.append(row[9])
            pending = False
    if len(values) != 1:
        raise ValueError("expected one public primary key")
    return full_fingerprint(values[0])


def control_fields(raw):
    fields = {}
    last = None
    for line in raw.splitlines():
        if line.startswith(" ") and last:
            fields[last] += "\n" + line
        else:
            if ": " not in line:
                raise ValueError("malformed control field")
            key, value = line.split(": ", 1)
            if key in fields:
                raise ValueError("duplicate control field")
            fields[key], last = value, key
    return fields


def deb_contents(path, control=False):
    raw = run("dpkg-deb", "--ctrl-tarfile" if control else "--fsys-tarfile", path)
    if len(raw) > artifact.MAX_BYTES:
        raise ValueError("package exceeds inspection limit")
    result, seen = {}, set()
    with tarfile.open(fileobj=io.BytesIO(raw)) as archive:
        for member in archive:
            name = member.name.removeprefix("./").rstrip("/")
            if member.isdir() and name in ("", "."):
                continue
            c.relative(name)
            if name.casefold() in seen or member.mode & 0o7000 or member.uid != 0 or member.gid != 0:
                raise ValueError("duplicate or unsafe package entry")
            seen.add(name.casefold())
            if member.isdir():
                continue
            if not member.isfile():
                raise ValueError("package may contain only directories and regular files")
            data = archive.extractfile(member).read()
            result[name] = {"sha256": __import__("hashlib").sha256(data).hexdigest(),
                            "size": len(data), "mode": member.mode & 0o777}
    return result


def package(archive, manifest, version, arch, backend, output):
    if arch not in ("amd64", "arm64") or backend not in BACKENDS:
        raise ValueError("unsupported Debian architecture/backend")
    if not re.fullmatch(r"[0-9][0-9A-Za-z.+~]{0,80}", version):
        raise ValueError("use an explicit monotonic Debian version")
    expected = c.load(manifest)
    if artifact.describe(archive) != expected:
        raise ValueError("portable archive differs from recorded bytes")
    output = Path(output).absolute()
    if output.exists() or output.is_symlink():
        raise ValueError("Debian package destination must be new")
    output.parent.mkdir(parents=True, exist_ok=True)
    name = "software-foundation-" + backend
    with tempfile.TemporaryDirectory(prefix=".foundation-debian-", dir=output.parent) as temp:
        temp = Path(temp)
        group = temp / "group"
        group.mkdir()
        deb = group / f"{name}_{version}_{arch}.deb"
        extracted = temp / "archive"
        extracted.mkdir()
        artifact.inspect_archive(archive, extracted)
        roots = list(extracted.iterdir())
        if len(roots) != 1 or not roots[0].is_dir() or not (roots[0] / "bin/foundation-cli").is_file():
            raise ValueError("archive must have one installation root and a CLI")
        source = roots[0]
        if any(not path.is_file() for path in (source / "bin").iterdir()):
            raise ValueError("unexpected nested public executable directory")
        modes = source_modes(archive)
        files = {path.relative_to(source).as_posix(): {"sha256": c.sha(path), "size": path.stat().st_size,
                 "mode": modes[path.relative_to(extracted).as_posix()]} for path in source.rglob("*") if path.is_file()}
        chosen = selection(source.name, files, backend, expected["sha256"])
        has_gui = any(Path(path).name in GUI_EXECUTABLES for path in files if path.startswith("bin/"))
        if has_gui:
            lock = c.load(Path(__file__).resolve().parents[1] / "third_party/gui-boundary.lock.json")
            if (lock.get("redistribution", {}).get("approved") is not True or
                    lock.get("license") in (None, "NOASSERTION") or
                    not lock["redistribution"].get("license_files")):
                raise ValueError("GUI redistribution requires recorded verified dependency terms")
        # The dependency floor printed in the control file must describe bytes,
        # not merely the build host or a caller-provided architecture label.
        audit_abi(source, {"amd64": "x86_64", "arm64": "aarch64"}[arch])
        if has_gui:
            notices = source / "share/doc/Foundation/gui-boundary"
            for license_name in lock["redistribution"]["license_files"]:
                expected_license = lock["files"].get(license_name)
                if not expected_license or c.sha(c.local(notices, license_name)) != expected_license:
                    raise ValueError("required GUI license evidence is absent from the package")
        stage = temp / "stage"
        private = stage / "opt/software-foundation" / backend
        private.parent.mkdir(parents=True)
        shutil.copytree(source, private)
        for omitted in chosen["excluded_executables"]:
            (private / omitted).unlink()
        record = private / SELECTION_PATH
        record.parent.mkdir(parents=True, exist_ok=True)
        c.write_new(record, chosen)
        record.chmod(0o644)
        # A regular tiny launcher avoids package links and preserves the private tree.
        binaries = stage / "usr/bin"
        binaries.mkdir(parents=True)
        for relative, data in launchers(backend, chosen["selected_executables"]).items():
            launcher = stage / relative
            launcher.write_bytes(data)
            launcher.chmod(0o755)
        for source_name, destination in manual_paths(backend, chosen["retained_files"]).items():
            manual = stage / destination
            manual.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source / source_name, manual)
            manual.chmod(chosen["retained_files"][source_name]["mode"])
        for relative, (data, mode) in installed_entries(backend, chosen["retained_files"], 4).items():
            entry = stage / relative
            entry.parent.mkdir(parents=True, exist_ok=True)
            entry.write_bytes(data)
            entry.chmod(mode)
        ctl = stage / "DEBIAN"
        ctl.mkdir(mode=0o755)
        text = (f"Package: {name}\nVersion: {version}\nArchitecture: {arch}\n"
                "Maintainer: Software Foundation contributors <maintainers@example.invalid>\n"
                f"Section: utils\nPriority: optional\nDepends: {runtime_dependencies(backend)}\n"
                f"Description: Generic development reference ({backend})\n")
        (ctl / "control").write_text(text)
        (ctl / "control").chmod(0o644)
        expected_payload = {p.relative_to(stage).as_posix(): {"sha256": c.sha(p), "size": p.stat().st_size,
                            "mode": p.stat().st_mode & 0o777} for p in stage.rglob("*")
                            if p.is_file() and ctl not in p.parents}
        if expected_payload != projected_payload(chosen):
            raise ValueError("staged payload differs from exact backend projection")
        run("dpkg-deb", "--build", "--root-owner-group", stage, deb)
        receipt = {"schema_version": 4, "archive": archive.name, "archive_sha256": expected["sha256"],
                   "archive_manifest": expected, "selection": chosen,
                   "package": deb.name, "sha256": c.sha(deb), "architecture": arch, "backend": backend,
                   "version": version, "control": text, "payload": expected_payload}
        verify_package(deb, receipt)
        if artifact.describe(archive) != expected or c.load(manifest) != expected:
            raise ValueError("original archive or manifest changed during packaging")
        c.write_new(group / (deb.name + ".json"), receipt)
        group.rename(output)
    return receipt


def verify_package(path, receipt):
    fields_required = {"schema_version", "archive", "archive_sha256", "archive_manifest", "selection", "package",
                       "sha256", "architecture", "backend", "version", "control", "payload"}
    if (set(receipt) != fields_required or type(receipt["schema_version"]) is not int or receipt["schema_version"] not in (2, 3, 4) or receipt["package"] != path.name or c.sha(path) != receipt["sha256"] or
            deb_contents(path) != receipt["payload"] or set(deb_contents(path, True)) != {"control"} or
            run("dpkg-deb", "--field", path).decode() != receipt["control"]):
        raise ValueError("Debian package differs from its verified source payload")
    fields = control_fields(receipt["control"])
    if (fields["Architecture"] != receipt["architecture"] or fields["Version"] != receipt["version"] or
            fields["Package"] != "software-foundation-" + receipt["backend"]):
        raise ValueError("package identity differs")
    if fields.get('Depends') != runtime_dependencies(receipt['backend']):
        raise ValueError('Debian runtime dependencies differ from backend policy')
    chosen = receipt["selection"]
    if set(chosen["retained_files"]) & set(chosen["excluded_executables"]):
        raise ValueError("overlapping backend selection inventory")
    original = dict(chosen["retained_files"], **chosen["excluded_executables"])
    if chosen != selection(chosen["archive_root"], original, receipt["backend"], receipt["archive_sha256"]):
        raise ValueError("backend selection differs from complete original inventory")
    expected_manifest = {"schema_version": 1, "archive": receipt["archive"], "sha256": receipt["archive_sha256"],
                         "files": {chosen["archive_root"] + "/" + name: {"sha256": record["sha256"], "size": record["size"]}
                                   for name, record in original.items()}}
    if receipt["archive_manifest"] != expected_manifest or receipt["payload"] != projected_payload(chosen, receipt["schema_version"]):
        raise ValueError("Debian payload no longer binds the original archive projection")
    return fields


@contextmanager
def signing_home():
    with tempfile.TemporaryDirectory(prefix="foundation-signing-") as home:
        os.chmod(home, 0o700)
        try:
            yield home
        finally:
            # Stop the agent before deleting its socket/configuration directory.
            run("gpgconf", "--homedir", home, "--kill", "gpg-agent")


def repository(receipts, output, base_url, key, trusted, sequence, valid_days=30):
    trusted = full_fingerprint(trusted)
    url = urlsplit(base_url)
    if (url.scheme != "https" or not url.netloc or url.query or url.fragment or url.username or
            any(ch in base_url for ch in "\r\n ") or not base_url.endswith("/")):
        raise ValueError("repository needs a fixed HTTPS release directory URL ending in slash")
    if type(sequence) is not int or sequence < 1 or not 1 <= valid_days <= 365:
        raise ValueError("invalid repository sequence or validity")
    if not receipts:
        raise ValueError("empty package repository")
    output.mkdir(parents=True, exist_ok=False)
    records, stanzas, names, arches = [], [], set(), set()
    for receipt_path in receipts:
        receipt = c.load(receipt_path)
        src = c.local(receipt_path.parent, receipt["package"])
        fields = verify_package(src, receipt)
        identity = (fields["Package"], fields["Architecture"])
        if identity in names:
            raise ValueError("duplicate package/architecture")
        names.add(identity)
        arches.add(fields["Architecture"])
        dst = output / src.name
        if dst.exists():
            raise ValueError("package filename collision")
        shutil.copyfile(src, dst)
        record_name = src.name + ".json"
        c.write_new(output / record_name, receipt)
        records.append({"package": dst.name, "receipt": record_name, "sha256": c.sha(dst),
                        "receipt_sha256": c.sha(output / record_name)})
        # APT resolves Filename relative to the configured repository directory.
        # Clients pin that directory to an immutable release tag.
        stanzas.append(receipt["control"] + f"Filename: {src.name}\nSize: {dst.stat().st_size}\nSHA256: {c.sha(dst)}\n")
    (output / "Packages").write_text("\n".join(stanzas) + "\n")
    (output / "Packages.gz").write_bytes(gzip.compress((output / "Packages").read_bytes(), mtime=0))
    now = datetime.now(timezone.utc).replace(microsecond=0)
    metadata = {"schema_version": 1, "sequence": sequence, "base_url": base_url, "signing_fingerprint": trusted,
                "packages": records, "created_at": now.isoformat(), "valid_until": (now + timedelta(days=valid_days)).isoformat()}
    c.write_new(output / "repository.json", metadata)
    release = ("Origin: Software Foundation\nLabel: Software Foundation\nSuite: stable\nCodename: foundation\n"
               f"Date: {format_datetime(now, usegmt=True)}\nValid-Until: {format_datetime(now + timedelta(days=valid_days), usegmt=True)}\n"
               f"Architectures: {' '.join(sorted(arches))}\nDescription: Verified portable application packages\nSHA256:\n")
    for filename in ("Packages", "Packages.gz", "repository.json"):
        p = output / filename
        release += f" {c.sha(p)} {p.stat().st_size} {filename}\n"
    (output / "Release").write_text(release)
    with signing_home() as temp:
        args = ["gpg", "--batch", "--homedir", temp]
        run(*args, "--import", key)
        (output / "archive-keyring.gpg").write_bytes(run(*args, "--export", trusted))
        if fingerprint(output / "archive-keyring.gpg") != trusted:
            raise ValueError("signing key differs from trusted primary")
        for filename, operation in (("InRelease", "--clearsign"), ("Release.gpg", "--detach-sign")):
            run(*args, "--pinentry-mode", "loopback", "--passphrase", "", "--local-user", trusted,
                "--digest-algo", "SHA256", "--output", output / filename, operation, output / "Release")
    verify_repository(output, trusted)
    return metadata


def verify_repository(directory, trusted, previous=None, now=None):
    trusted = full_fingerprint(trusted)
    directory = directory.resolve(strict=True)
    now = now or datetime.now(timezone.utc)
    for p in directory.iterdir():
        if p.is_symlink() or not p.is_file():
            raise ValueError("repository assets must be regular files")
    if fingerprint(directory / "archive-keyring.gpg") != trusted:
        raise ValueError("untrusted repository key")
    with tempfile.TemporaryDirectory(prefix="foundation verify ") as temp:
        args = ["gpgv", "--homedir", temp, "--keyring", directory / "archive-keyring.gpg"]
        # Capture only a successful verifier's stdout: newer gpgv versions may
        # leave named output in an unfinalized .part file.
        decoded = run(*args, "--output", "-", directory / "InRelease")
        run(*args, directory / "Release.gpg", directory / "Release")
        release = (directory / "Release").read_bytes()
        if not release.endswith(b"\n") or release.endswith(b"\n\n") or b"\r" in release:
            raise ValueError("Release must use canonical LF with one terminal newline")
        # CSF excludes its separator newline from signed text. Stock and Arch
        # GnuPG differ by exactly that LF when signing/decoding across providers.
        # The detached signature still authenticates every original Release byte;
        # do not trim other whitespace, line endings, content or extra blank lines.
        if decoded not in (release, release[:-1], release + b"\n"):
            raise ValueError("signed metadata disagree")
    head, hashes = release.decode("utf-8").split("SHA256:\n")
    fields = control_fields(head)
    if parsedate_to_datetime(fields["Valid-Until"]) <= now or parsedate_to_datetime(fields["Date"]) > now + timedelta(minutes=5):
        raise ValueError("repository metadata expired or from the future")
    expected = {}
    for line in hashes.splitlines():
        digest, size, name = line.split()
        c.relative(name)
        if name in expected:
            raise ValueError("duplicate repository digest")
        expected[name] = (digest, int(size))
    if set(expected) != {"Packages", "Packages.gz", "repository.json"}:
        raise ValueError("incomplete signed metadata inventory")
    for name, (digest, size) in expected.items():
        p = directory / name
        if c.sha(p) != digest or p.stat().st_size != size:
            raise ValueError("signed metadata digest differs")
    metadata = c.load(directory / "repository.json")
    if (metadata["schema_version"] != 1 or metadata["signing_fingerprint"] != trusted or
            type(metadata["sequence"]) is not int or metadata["sequence"] < 1):
        raise ValueError("invalid repository identity")
    if previous:
        if (metadata["sequence"] < previous["sequence"] or
                (metadata["sequence"] == previous["sequence"] and c.digest(metadata) != previous["metadata_sha256"])):
            raise ValueError("rollback or same-sequence replacement")
    if gzip.decompress((directory / "Packages.gz").read_bytes()) != (directory / "Packages").read_bytes():
        raise ValueError("compressed index differs")
    assets = {"Packages", "Packages.gz", "repository.json", "Release", "Release.gpg", "InRelease", "archive-keyring.gpg"}
    stanzas, identities, versions, package_hashes = [], set(), {}, {}
    for record in metadata["packages"]:
        p = c.local(directory, record["package"])
        r = c.local(directory, record["receipt"])
        if p.name in assets or r.name in assets or c.sha(p) != record["sha256"] or c.sha(r) != record["receipt_sha256"]:
            raise ValueError("package inventory differs")
        assets.update((p.name, r.name))
        receipt = c.load(r)
        ctl = verify_package(p, receipt)
        identity = (ctl["Package"], ctl["Architecture"])
        if identity in identities:
            raise ValueError("duplicate package identity")
        identities.add(identity)
        identity_text = ctl["Package"] + ":" + ctl["Architecture"]
        versions[identity_text] = ctl["Version"]
        package_hashes[identity_text] = record["sha256"]
        if previous and identity_text in previous.get("versions", {}):
            older = previous["versions"][identity_text]
            comparison = subprocess.run(["dpkg", "--compare-versions", ctl["Version"], "ge", older])
            if comparison.returncode != 0:
                raise ValueError("package version rollback")
            equal = subprocess.run(["dpkg", "--compare-versions", ctl["Version"], "eq", older])
            if equal.returncode == 0 and previous.get("package_sha256", {}).get(identity_text) != record["sha256"]:
                raise ValueError("same-version package replacement or missing previous payload identity")
        stanzas.append(receipt["control"] + f"Filename: {p.name}\nSize: {p.stat().st_size}\nSHA256: {c.sha(p)}\n")
    if not identities or {p.name for p in directory.iterdir()} != assets:
        raise ValueError("missing or extra repository assets")
    if (directory / "Packages").read_text() != "\n".join(stanzas) + "\n":
        raise ValueError("package index does not bind exact verified payloads")
    if previous and previous.get("signing_fingerprint") != trusted:
        raise ValueError("trust rotation requires an explicit separately reviewed transition")
    return {"sequence": metadata["sequence"], "metadata_sha256": c.digest(metadata),
            "signing_fingerprint": trusted, "versions": versions, "package_sha256": package_hashes}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("package")
    p.add_argument("--archive", type=Path, required=True)
    p.add_argument("--manifest", type=Path, required=True)
    p.add_argument("--version", required=True)
    p.add_argument("--architecture", choices=("amd64", "arm64"), required=True)
    p.add_argument("--backend", choices=sorted(BACKENDS), default="core")
    p.add_argument("--output", type=Path, required=True)
    p = sub.add_parser("assemble")
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--base-url", required=True)
    p.add_argument("--signing-key", type=Path, required=True)
    p.add_argument("--trusted-fingerprint", required=True)
    p.add_argument("--sequence", type=int, required=True)
    p.add_argument("receipts", type=Path, nargs="+")
    p = sub.add_parser("verify")
    p.add_argument("directory", type=Path)
    p.add_argument("--trusted-fingerprint", required=True)
    p.add_argument("--previous", type=Path)
    p.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "package":
        package(args.archive, args.manifest, args.version, args.architecture, args.backend, args.output)
    elif args.command == "assemble":
        repository(args.receipts, args.output, args.base_url, args.signing_key, args.trusted_fingerprint, args.sequence)
    else:
        state = verify_repository(args.directory, args.trusted_fingerprint,
                                  c.load(args.previous) if args.previous else None)
        c.write_new(args.output, state)


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, KeyError, TypeError, subprocess.CalledProcessError, tarfile.TarError) as error:
        print("APT: " + str(error), file=sys.stderr)
        sys.exit(1)
