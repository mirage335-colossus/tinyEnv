#!/usr/bin/env python3
"""Stage and audit each retained Linux SDK executable's development closure.

The shared CMake dependency guard verifies the complete SDK once per build.
This post-link step binds its configured manifest and every copied provider,
without hashing the complete compiler/sysroot again for every executable.
"""
import argparse
from pathlib import Path
import re
import shutil
import tempfile

from dependency_archive import digest, file_inventory, read_json, write_json
from sdk_environment import require_clean
from stage_runtime import stage
from verify_abi import HOST_LIBRARIES, audit, inspect


def stage_build_runtime(sdk, executable, target, processor, manifest_sha256):
    require_clean()
    sdk, executable = Path(sdk).resolve(strict=True), Path(executable).resolve(strict=True)
    if not re.fullmatch(r'[A-Za-z0-9_][A-Za-z0-9_.+-]*', target):
        raise ValueError('unsafe SDK runtime target name')
    manifest = sdk / 'sdk.json'
    if digest(manifest) != manifest_sha256:
        raise ValueError('SDK manifest changed since configuration')
    metadata = read_json(manifest)
    if metadata['target']['system'] != 'Linux' or metadata['target']['processor'] != processor:
        raise ValueError('SDK development runtime target mismatch')
    relative = Path(metadata['target']['sysroot'])
    if relative.is_absolute() or '..' in relative.parts or not relative.parts:
        raise ValueError('SDK sysroot must be a contained relative path')
    sysroot = (sdk / relative).resolve(strict=True)
    if sdk not in sysroot.parents:
        raise ValueError('SDK sysroot escapes its root')
    private = Path('.sdk-runtime') / target
    destination = executable.parent / private
    owner = {'executable': str(executable), 'target': target}
    if destination.parent.is_symlink():
        raise ValueError('SDK runtime parent must not be a symlink')
    previous_inventory = None
    if destination.exists() or destination.is_symlink():
        if destination.is_symlink() or not destination.is_dir():
            raise ValueError('SDK runtime destination is not an owned directory')
        previous = read_json(destination / 'build-runtime.json')
        if (previous.get('owner') != owner or
                file_inventory(destination, exclude=('build-runtime.json',)) != previous.get('owned_files')):
            raise ValueError('SDK runtime destination changed outside its owning build')
        previous_inventory = file_inventory(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.parent.is_symlink():
        raise ValueError('SDK runtime parent must not be a symlink')
    editor = sdk / 'bin/patchelf'
    if editor.exists() and (editor.is_symlink() or digest(editor) != metadata['files'].get('bin/patchelf')):
        raise ValueError('SDK ELF editor differs from the configured inventory')
    executable_hash = digest(executable)
    # Most CLI/core targets have only host libc after static GNU runtime linking.
    # Avoid walking a large sysroot when no private dependency is needed.
    needs_private = set(inspect(executable)['needed']) - HOST_LIBRARIES
    with tempfile.TemporaryDirectory(prefix='.sdk-runtime-', dir=destination.parent) as temporary:
        work = Path(temporary)
        layout = work / 'layout'
        layout.mkdir()
        shutil.copy2(executable, layout / executable.name)
        staged = layout / private
        # Read library-bearing directories from the already verified manifest;
        # do not walk target headers again for each executable.
        directories = {Path(name).parent for name in metadata['files']
                       if name.startswith(relative.as_posix() + '/') and '.so' in Path(name).name}
        roots = [sdk / name for name in sorted(directories)
                 if not any(parent in directories for parent in name.parents)] if needs_private else []
        if any(path.resolve(strict=True) != sysroot and sysroot not in path.resolve(strict=True).parents for path in roots):
            raise ValueError('runtime library directory escapes the SDK sysroot')
        report = stage([executable], roots, staged, processor, elf_editor=editor)
        sources = {(Path(name).name, sha) for name, sha in metadata['files'].items()
                   if name.startswith(relative.as_posix() + '/')}
        if any((name, sha) not in sources for name, sha in report['files'].items()):
            raise ValueError('staged runtime provider differs from the configured SDK inventory')
        for name, installed in report['installed_files'].items():
            transformed = report['transformations'].get(name)
            if ((transformed and (transformed['source_sha256'] != report['files'][name] or
                                  transformed['installed_sha256'] != installed)) or
                    (not transformed and installed != report['files'][name])):
                raise ValueError('runtime provider changed while copying')
        result = audit(layout, processor)
        if digest(executable) != executable_hash or digest(manifest) != manifest_sha256:
            raise ValueError('executable or SDK changed during runtime staging')
        receipt = {'schema_version': 1, 'owner': owner, 'sdk_manifest_sha256': manifest_sha256,
                   'executable_sha256': executable_hash, 'audit': result,
                   'owned_files': file_inventory(staged)}
        write_json(staged / 'build-runtime.json', receipt)
        # All verification precedes replacement. A failed build keeps its earlier
        # closure; unrecognized/modified trees are never silently removed.
        current = file_inventory(destination) if destination.is_dir() and not destination.is_symlink() else None
        if current != previous_inventory or (previous_inventory is None and (destination.exists() or destination.is_symlink())):
            raise ValueError('SDK runtime destination changed during staging')
        # Keep the previous closure outside automatic staging cleanup: an OS
        # error during rollback must preserve it for explicit recovery.
        backup = None
        if destination.exists():
            backup = Path(tempfile.mkdtemp(prefix='.sdk-runtime-previous-', dir=destination.parent))
            destination.rename(backup / 'runtime')
        try:
            staged.rename(destination)
        except BaseException:
            if backup is not None:
                try:
                    (backup / 'runtime').rename(destination)
                except OSError as error:
                    raise ValueError('runtime rollback failed; previous closure retained at ' + str(backup)) from error
                backup.rmdir()
            raise
        if backup is not None:
            shutil.rmtree(backup)
    return receipt


def guard_build_runtime(sdk, executable, target, processor, manifest_sha256):
    """Verify selected output on no-relink builds without walking the SDK again.

    A wholly missing private tree is recreated; partial/modified/unowned output
    fails instead of being adopted. The shared guard verifies the complete SDK.
    """
    require_clean()
    executable = Path(executable)
    if executable.is_symlink():
        raise ValueError('SDK build executable must not be a symlink')
    executable = executable.resolve()
    if not re.fullmatch(r'[A-Za-z0-9_][A-Za-z0-9_.+-]*', target):
        raise ValueError('unsafe SDK runtime target name')
    if digest(Path(sdk) / 'sdk.json') != manifest_sha256:
        raise ValueError('SDK manifest changed since configuration')
    destination = executable.parent / '.sdk-runtime' / target
    if destination.parent.is_symlink() or destination.is_symlink():
        raise ValueError('SDK runtime destination must not be a symlink')
    if not destination.exists():
        if executable.exists():
            return stage_build_runtime(sdk, executable, target, processor, manifest_sha256)
        return {'status':'awaiting-first-link'}
    if not destination.is_dir():
        raise ValueError('SDK runtime destination is not an owned directory')
    receipt = read_json(destination / 'build-runtime.json')
    if (receipt.get('owner') != {'executable':str(executable), 'target':target} or
            receipt.get('sdk_manifest_sha256') != manifest_sha256 or
            file_inventory(destination, exclude=('build-runtime.json',)) != receipt.get('owned_files')):
        raise ValueError('SDK runtime destination changed outside its owning build')
    if executable.exists() and digest(executable) != receipt.get('executable_sha256'):
        raise ValueError('SDK executable differs from its audited runtime; inspect and remove the failed executable before rebuilding')
    return {'status':'verified-existing' if executable.exists() else 'awaiting-relink'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--guard', action='store_true', help='verify no-relink output; repair a wholly missing private tree')
    parser.add_argument('--sdk', type=Path, required=True)
    parser.add_argument('--manifest-sha256', required=True)
    parser.add_argument('--executable', type=Path, required=True)
    parser.add_argument('--target', required=True)
    parser.add_argument('--processor', choices=('x86_64', 'aarch64'), required=True)
    args = parser.parse_args()
    operation = guard_build_runtime if args.guard else stage_build_runtime
    operation(args.sdk, args.executable, args.target, args.processor, args.manifest_sha256)


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError, KeyError) as error:
        raise SystemExit('SDK build runtime: ' + str(error))
