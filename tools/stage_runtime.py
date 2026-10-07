#!/usr/bin/env python3
"""Copy an ELF runtime closure only from explicitly supplied target roots."""
import argparse
from pathlib import Path
import shutil
import subprocess
import tempfile
from dependency_archive import digest, write_json
from verify_abi import HOST_LIBRARIES, audit, elf, inspect, version


def normalize_empty_paths(path, readelf='readelf', elf_editor='patchelf'):
    """Remove wholly empty tags from a staged copy, preserving input provenance.

    An empty DT_RUNPATH supplies no directories but suppresses inherited RPATH.
    Do not erase nonempty paths (including empty colon-delimited components).
    The final installed-package audit must prove its inherited private closure.
    """
    before = inspect(path, readelf)
    if '' not in before['rpaths']:
        return None
    if any(before['rpaths']):
        raise ValueError('mixed empty and nonempty runtime paths: ' + str(path))
    editor = shutil.which(str(elf_editor))
    if editor is None:
        raise ValueError('empty runtime paths require the selected ELF editor: ' + str(elf_editor))
    editor_hash = digest(Path(editor))
    subprocess.run([editor, '--remove-rpath', str(path)], check=True)
    after = inspect(path, readelf)
    if after['rpaths'] or any(before[key] != after[key] for key in before
                             if key not in ('sha256', 'rpaths', 'rpath', 'runpath')):
        raise ValueError('ELF editor changed runtime contracts or left search-path tags: ' + str(path))
    if digest(Path(editor)) != editor_hash:
        raise ValueError('ELF editor changed during runtime normalization')
    return {'operation': 'remove-wholly-empty-rpath-tags', 'source_sha256': before['sha256'],
            'installed_sha256': after['sha256'], 'editor_sha256': editor_hash,
            'original_rpath': before['rpath'], 'original_runpath': before['runpath']}


def stage(executables, roots, destination, processor='x86_64', readelf='readelf', host_libraries=None,
          audit_baseline=True, elf_editor='patchelf'):
    """Collect target files; only an explicit native build may use observed floors."""
    if type(audit_baseline) is not bool:
        raise ValueError('runtime staging baseline policy must be explicit')
    destination = Path(destination).absolute()
    if destination.exists() or destination.is_symlink():
        raise ValueError('runtime staging destination must be new')
    host_libraries = HOST_LIBRARIES if host_libraries is None else set(host_libraries)
    if not host_libraries <= HOST_LIBRARIES:
        raise ValueError('undeclared host dependency exemption')
    providers = {}
    for root in map(lambda p: Path(p).resolve(strict=True), roots):
        for path in root.rglob('*'):
            if path.is_file() and '.so' in path.name:
                resolved = path.resolve(strict=True)
                if root not in resolved.parents:
                    raise ValueError('target library escapes selected root')
                providers.setdefault(path.name, []).append(resolved)
    queue = list(map(Path, executables))
    copied, host = {}, set()
    while queue:
        path = queue.pop(0)
        if not path.is_file() or not elf(path):
            raise ValueError('runtime input must be an ELF executable or library')
        for name in inspect(path, readelf)['needed']:
            if name in host_libraries:
                host.add(name)
                continue
            if name in copied:
                continue
            found = providers.get(name, [])
            if not found:
                raise ValueError('missing target runtime dependency: ' + name)
            identities = {digest(item) for item in found}
            if len(identities) != 1:
                raise ValueError('ambiguous target runtime provider: ' + name)
            copied[name] = found[0]
            queue.append(found[0])
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=destination.parent) as temporary:
        staged = Path(temporary) / 'lib'
        staged.mkdir()
        staged.chmod(0o755)
        transformations = {}
        for name, path in copied.items():
            shutil.copyfile(path, staged / name)
            (staged / name).chmod(0o755)
            changed = normalize_empty_paths(staged / name, readelf, elf_editor)
            if changed:
                transformations[name] = changed
        # files retains supplier identities used by dependency notice collection.
        report = {'schema_version': 2, 'files': {name: digest(path) for name, path in copied.items()},
                  'installed_files': {name: digest(staged / name) for name in copied},
                  'transformations': transformations,
                  'host_libraries': sorted(host), 'processor': processor}
        if copied:
            # Staging has no executable ancestor or final directory layout.
            # The complete installed package must pass the default audit next.
            ceilings = None
            if not audit_baseline:
                ceilings = {}
                for path in staged.iterdir():
                    for family, required in inspect(path, readelf)['requirements'].items():
                        if version(required) > version(ceilings.get(family, '0')):
                            ceilings[family] = required
            report['abi'] = audit(staged, processor, ceilings=ceilings, readelf=readelf, runtime_resolution=False)
        report['baseline_qualification'] = 'bookworm-abi-only' if audit_baseline else 'native-observed-requirements-only'
        report['runtime_resolution'] = 'requires_final_package_audit'
        inventory = staged / 'runtime-inventory.json'
        write_json(inventory, report)
        # Installed metadata is public even when the build uses a private umask.
        inventory.chmod(0o644)
        staged.rename(destination)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--executable', type=Path, action='append', required=True)
    parser.add_argument('--root', type=Path, action='append', required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--processor', default='x86_64')
    parser.add_argument('--elf-editor', default='patchelf')
    args = parser.parse_args()
    stage(args.executable, args.root, args.output, args.processor, elf_editor=args.elf_editor)


if __name__ == '__main__':
    try: main()
    except (ValueError, OSError, subprocess.CalledProcessError) as error: raise SystemExit(str(error))
