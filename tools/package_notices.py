#!/usr/bin/env python3
"""Install complete, locally verified dependency notices beside application files."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile


# Existing retained SDK manifests authenticate these bytes but older license
# inventories list only the top-level tool and Node notices. Include the complete
# target runtime terms without changing or rebuilding the immutable SDK.
WASM_RUNTIME_NOTICES = (
    'upstream/emscripten/AUTHORS',
    'upstream/emscripten/system/lib/libc/musl/COPYRIGHT',
    'upstream/emscripten/system/lib/libcxx/LICENSE.TXT',
    'upstream/emscripten/system/lib/libcxxabi/LICENSE.TXT',
    'upstream/emscripten/system/lib/compiler-rt/LICENSE.TXT',
    'upstream/emscripten/system/lib/libunwind/LICENSE.TXT',
    # This source file contains its dedication; there is no separate license file.
    'upstream/emscripten/system/lib/dlmalloc.c',
)


def sha(path):
    result = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            result.update(block)
    return result.hexdigest()


def regular(path, root=None):
    path = Path(path)
    actual = path.resolve(strict=True)
    if not actual.is_file() or (root is not None and Path(root).resolve() not in actual.parents):
        raise ValueError('notice input is not a contained regular file: ' + str(path))
    return actual


def command(*args):
    return subprocess.check_output(args, text=True, encoding='utf-8', errors='strict').strip()


def distro_notice(library, share=Path('/usr/share'), query=command):
    library = regular(library)
    try:
        owner = query('dpkg-query', '-S', str(library))
    except subprocess.CalledProcessError:
        if not str(library).startswith('/usr/'):
            owner = query('dpkg-query', '-S', '/usr' + str(library))
        else:
            raise ValueError('dependency has no local notice provider; supply an explicit manifest')
    rows = owner.splitlines()
    if len(rows) != 1 or ': ' not in rows[0]:
        raise ValueError('dependency package ownership is ambiguous')
    package, owned = rows[0].rsplit(': ', 1)
    if not re.fullmatch(r'[a-z0-9][a-z0-9+.-]*(?::[a-z0-9]+)?', package):
        raise ValueError('unrecognized dependency package identity')
    if Path(owned).resolve(strict=True) != library:
        raise ValueError('package ownership names a different dependency')
    version = query('dpkg-query', '-W', '-f=${Version}', package)
    if not version or '\n' in version:
        raise ValueError('dependency package version is unavailable')
    name = package.split(':')[0]
    return {'provider': 'debian-package', 'package': package, 'version': version,
            'input': {'name': library.name, 'sha256': sha(library)}}, regular(Path(share) / 'doc' / name / 'copyright')


def notice_files(path):
    path = Path(path)
    if path.is_file():
        return [regular(path)]
    if not path.is_dir() or path.is_symlink():
        raise ValueError('dependency notice tree is unavailable')
    result = []
    for entry in sorted(path.rglob('*')):
        if entry.is_symlink():
            # SDK producers materialize links; a changed tree must not leak host files.
            raise ValueError('dependency notice tree contains a link')
        if entry.is_file(): result.append(regular(entry, path))
        elif not entry.is_dir(): raise ValueError('dependency notice tree contains a special entry')
    if not result: raise ValueError('dependency notice tree is empty')
    return result


def manual_components(path):
    if path is None: return {}
    data = json.loads(Path(path).read_text(encoding='utf-8'))
    if set(data) != {'schema_version', 'components'} or data['schema_version'] != 1:
        raise ValueError('invalid explicit dependency notice manifest')
    result = {}
    for item in data['components']:
        if set(item) != {'name', 'inputs', 'notices'} or not item['name'] or not item['inputs'] or not item['notices']:
            raise ValueError('incomplete explicit dependency notice component')
        files = []
        for relative, expected in item['notices'].items():
            source = Path(path).resolve().parent / relative
            if source.is_absolute() and Path(relative).is_absolute():
                raise ValueError('explicit notices use contained relative paths')
            source = regular(source, Path(path).resolve().parent)
            if sha(source) != expected: raise ValueError('explicit notice digest differs')
            files.append(source)
        for identity in item['inputs']:
            if not re.fullmatch('[0-9a-f]{64}', identity) or identity in result:
                raise ValueError('invalid or duplicate explicit dependency identity')
            result[identity] = (item['name'], files)
    return result


def collect(destination, *, sdk=None, windows_dependencies=None, libraries=(), files=(), manifest=None,
            share=Path('/usr/share'), query=command, runtime_inventory=None, runtime_roots=()):
    destination = Path(destination).absolute()
    if destination.is_symlink() or (destination.exists() and not destination.is_dir()):
        raise ValueError('dependency notice destination must be an ordinary directory')
    libraries = list(libraries)
    if runtime_inventory and not (sdk or windows_dependencies):
        runtime = json.loads(Path(runtime_inventory).read_text(encoding='utf-8'))
        for name, expected in runtime['files'].items():
            if Path(name).name != name: raise ValueError('invalid runtime notice inventory name')
            candidates = []
            for root in map(Path, runtime_roots):
                for path in root.rglob(name):
                    actual = regular(path, root)
                    if sha(actual) == expected: candidates.append(actual)
            if not candidates: raise ValueError('copied runtime notice input is unavailable: ' + name)
            libraries.append(sorted(set(candidates))[0])
    manual = manual_components(manifest)
    inputs, providers = [], []
    common_roots = [Path(share) / 'common-licenses']
    if sdk or windows_dependencies:
        from sdk_manifest import verify_sdk
        root = Path(sdk or windows_dependencies).resolve(strict=True)
        verify_sdk(root, release=True)
        data = json.loads((root / 'sdk.json').read_text(encoding='utf-8'))
        if windows_dependencies:
            inputs += sorted((root / 'prefix').glob('installed/*/share/*/copyright'))
            inputs += sorted((root / 'prefix').glob('share/*/copyright'))
            ports = data.get('provenance', {}).get('ports', [])
            triplet = data.get('provenance', {}).get('triplet', '')
            for port in ports:
                name = port.split('[', 1)[0]
                notice = root / 'prefix/installed' / triplet / 'share' / name / 'copyright'
                if not notice.is_file(): raise ValueError('prepared dependency lacks its exported port notice: ' + name)
            inputs = [regular(path, root) for path in inputs]
            common_roots = [root / 'prefix/share/common-licenses']
        else:
            for relative in data['licenses']:
                tree = root / relative
                if root not in tree.resolve(strict=True).parents:
                    raise ValueError('SDK notice tree escapes its retained root')
                inputs += notice_files(tree)
            if data['target'].get('system') == 'Emscripten':
                for relative in WASM_RUNTIME_NOTICES:
                    path = regular(root / relative, root)
                    if relative not in data['files'] or sha(path) != data['files'][relative]:
                        raise ValueError('Wasm runtime notice differs from retained inventory: ' + relative)
                    inputs.append(path)
            common_roots = [root / data['target']['sysroot'] / 'usr/share/common-licenses']
        providers.append({'provider': 'retained-sdk', 'recipe_id': data['recipe_id'],
                          'manifest_sha256': sha(root / 'sdk.json')})
    else:
        for library in sorted(set(map(str, libraries))):
            library = regular(library)
            identity = sha(library)
            if identity in manual:
                name, paths = manual[identity]
                providers.append({'provider': 'explicit', 'name': name, 'input': {'name': library.name, 'sha256': identity}})
                inputs += paths
            else:
                provider, path = distro_notice(library, share, query)
                providers.append(provider)
                inputs.append(path)
    for path, expected in files:
        path = regular(path)
        if sha(path) != expected: raise ValueError('configured dependency notice changed')
        inputs.append(path)
    # Distro notices reference shared complete texts; never leave such references dangling.
    queue, resolved = list(inputs), {}
    while queue:
        path = regular(queue.pop())
        data = path.read_bytes()
        identity = hashlib.sha256(data).hexdigest()
        key = identity + '-' + re.sub(r'[^A-Za-z0-9._+-]', '_', path.name)
        if key in resolved: continue
        resolved[key] = (path, data)
        for name in re.findall(rb'/usr/share/common-licenses/([A-Za-z0-9](?:[A-Za-z0-9.+-]*[A-Za-z0-9+])?)', data):
            candidates = [base / name.decode('ascii') for base in common_roots]
            found = [regular(candidate, base) for candidate, base in zip(candidates, common_roots) if candidate.exists()]
            if len(found) != 1: raise ValueError('referenced common license is unavailable: ' + name.decode('ascii'))
            queue += found
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.notices-', dir=destination.parent) as temporary:
        stage = Path(temporary) / 'notices'; stage.mkdir(); stage.chmod(0o755)
        inventory = {}
        for name, (path, data) in sorted(resolved.items()):
            if path.read_bytes() != data: raise ValueError('dependency notice changed while copying')
            target = stage / name
            target.write_bytes(data); target.chmod(0o644)
            inventory[name] = {'sha256': hashlib.sha256(data).hexdigest(), 'size': len(data)}
        report = {'schema_version': 1, 'providers': providers, 'files': inventory}
        (stage / 'index.json').write_text(json.dumps(report, sort_keys=True, indent=2) + '\n', encoding='utf-8')
        (stage / 'index.json').chmod(0o644)
        if destination.exists():
            current = {p.name: p.read_bytes() for p in destination.iterdir() if p.is_file() and not p.is_symlink()}
            intended = {p.name: p.read_bytes() for p in stage.iterdir()}
            permissions_match = os.name != 'posix' or (
                destination.stat().st_mode & 0o777 == 0o755 and
                all(path.stat().st_mode & 0o777 == 0o644 for path in destination.iterdir()))
            if not permissions_match or len(current) != len(list(destination.iterdir())) or current != intended:
                raise ValueError('existing dependency notices differ; use a fresh installation prefix')
        else:
            stage.rename(destination)
    return report


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output', required=True, type=Path)
    inputs = p.add_mutually_exclusive_group()
    inputs.add_argument('--sdk', type=Path)
    inputs.add_argument('--windows-dependencies', type=Path)
    p.add_argument('--library', action='append', default=[])
    p.add_argument('--file', nargs=2, action='append', default=[])
    p.add_argument('--manifest', type=Path)
    p.add_argument('--runtime-inventory', type=Path)
    p.add_argument('--runtime-root', type=Path, action='append', default=[])
    a = p.parse_args()
    print(json.dumps(collect(a.output, sdk=a.sdk, windows_dependencies=a.windows_dependencies,
                            libraries=a.library, files=a.file, manifest=a.manifest,
                            runtime_inventory=a.runtime_inventory, runtime_roots=a.runtime_root), sort_keys=True))


if __name__ == '__main__':
    try: main()
    except (OSError, ValueError, KeyError, subprocess.SubprocessError) as error: raise SystemExit(str(error))
