#!/usr/bin/env python3
"""Verify and stage an already-built offline Wasm application for native installation."""
import argparse
import hashlib
from pathlib import Path
import re
import tempfile

from package_wasm import HTML_NAME, read_file, verify
from source_identity import source_tree

FILES = (HTML_NAME, 'web-manifest.json', 'manifest.sha256')
# Launch the document in the adjacent wasm directory; relocation never invokes a source tree,
# hosted server, network fetch, or a separately installed application revision.
POSIX_LAUNCHER = b'''#!/bin/sh
set -eu
here=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
document="$here/wasm/software-foundation-wasm.html"
[ -f "$document" ] || { echo "Installed offline document is missing: $document" >&2; exit 1; }
if command -v xdg-open >/dev/null 2>&1; then exec xdg-open "$document"; fi
if command -v gio >/dev/null 2>&1; then exec gio open "$document"; fi
echo "Open this installed document in a browser: $document" >&2
exit 1
'''
WINDOWS_LAUNCHER = (b'@echo off\r\n'
                    b'setlocal DisableDelayedExpansion\r\n'
                    b'if not exist "%~dp0wasm\\software-foundation-wasm.html" exit /b 1\r\n'
                    b'start "" "%~dp0wasm\\software-foundation-wasm.html"\r\n')


def verify_input(package_dir, expected_manifest_sha256, source_root):
    """The caller supplies an independently selected exact manifest identity."""
    root = Path(package_dir)
    if not re.fullmatch(r'[0-9a-f]{64}', expected_manifest_sha256 or ''):
        raise ValueError('Prebuilt Wasm requires an exact lowercase manifest SHA-256')
    if hashlib.sha256(read_file(root / 'web-manifest.json')).hexdigest() != expected_manifest_sha256:
        raise ValueError('Prebuilt Wasm manifest identity differs')
    manifest = verify(root)
    if manifest.get('schema') not in (2, 3) or manifest.get('source_tree_sha256') != source_tree(source_root)['tree_sha256']:
        raise ValueError('Prebuilt Wasm and native application source identities differ; rebuild from the same source snapshot')
    return manifest


def stage(package_dir, expected_manifest_sha256, source_root, output):
    package_dir, output = Path(package_dir), Path(output)
    manifest = verify_input(package_dir, expected_manifest_sha256, source_root)
    before = {name: read_file(package_dir / name, 256 * 1024 * 1024) for name in FILES}
    if output.is_symlink():
        raise ValueError('Wasm staging directory must be ordinary')
    output.parent.mkdir(parents=True, exist_ok=True)
    # Validate the exact copied snapshot before exposing it to installation.
    with tempfile.TemporaryDirectory(prefix='.wasm-import-', dir=output.parent) as temp:
        ready = Path(temp) / 'ready'
        package = ready / 'package'
        package.mkdir(parents=True)
        for name, data in before.items():
            (package / name).write_bytes(data)
            (package / name).chmod(0o644)
        verify_input(package, expected_manifest_sha256, source_root)
        (ready / 'open-offline.sh').write_bytes(POSIX_LAUNCHER)
        (ready / 'open-offline.sh').chmod(0o755)
        (ready / 'open-offline.cmd').write_bytes(WINDOWS_LAUNCHER)
        (ready / 'open-offline.cmd').chmod(0o644)
        if before != {name: read_file(package_dir / name, 256 * 1024 * 1024) for name in FILES}:
            raise ValueError('Prebuilt Wasm inputs changed during staging')
        if output.exists():
            expected = {p.relative_to(ready).as_posix(): (p.read_bytes(), p.stat().st_mode & 0o777)
                        for p in ready.rglob('*') if p.is_file()}
            if (output.is_symlink() or not output.is_dir() or
                    any(p.is_symlink() or not (p.is_dir() or p.is_file()) for p in output.rglob('*')) or
                    {p.relative_to(output).as_posix() for p in output.rglob('*') if p.is_dir()} != {'package'}):
                raise ValueError('Wasm staging contains an unexpected link or entry')
            actual = {p.relative_to(output).as_posix(): (p.read_bytes(), p.stat().st_mode & 0o777)
                      for p in output.rglob('*') if p.is_file()}
            # Windows does not preserve POSIX execute bits in copied data files.
            import os
            if os.name == 'nt':
                actual = {k: v[0] for k, v in actual.items()}
                expected = {k: v[0] for k, v in expected.items()}
            if actual != expected:
                raise ValueError('Existing Wasm staging differs; use a fresh native build directory')
        else:
            ready.rename(output)
    return manifest


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--package', required=True, type=Path)
    parser.add_argument('--sha256', required=True)
    parser.add_argument('--source-root', required=True, type=Path)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args(argv)
    if args.output:
        stage(args.package, args.sha256, args.source_root, args.output)
    else:
        verify_input(args.package, args.sha256, args.source_root)


if __name__ == '__main__':
    main()
