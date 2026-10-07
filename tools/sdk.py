#!/usr/bin/env python3
"""Export, install and validate retained SDK groups; production is explicit."""
import argparse
import hashlib
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
from dependency_archive import (archive_tree, digest, encoded, extract, file_inventory, read_json, verify_inventory, write_json,
                                PORTABLE_PATHS, LINUX_SDK_PATHS, PathInventory, sdk_path_policy,
                                probe_case_sensitive, inspect_manifest_archive, require_linux_case_host, sdk_temporary_directory)
from dependency_store import create_sums, names, verify_group
from sdk_manifest import verify_sdk
from sdk_environment import sanitized
from verify_abi import audit, SDK_RUNTIME_NAMES


def recipe_identity(recipe_directory):
    return hashlib.sha256(encoded(file_inventory(recipe_directory))).hexdigest()


def materialize(source, output, *, path_policy=PORTABLE_PATHS):
    """Convert confined supplier links into ordinary archived files/directories."""
    source, output = Path(source).resolve(strict=True), Path(output)
    registry = PathInventory(path_policy)
    if path_policy == LINUX_SDK_PATHS:
        require_linux_case_host()
    def copy(path, destination, ancestors):
        real = path.resolve(strict=True)
        if real != source and source not in real.parents:
            raise ValueError('supplier link escapes SDK tree')
        if real in ancestors:
            raise ValueError('supplier directory link cycle')
        if destination != output:
            registry.add(destination.relative_to(output).as_posix(), real.is_dir())
        if real.is_dir():
            destination.mkdir()
            if path_policy == LINUX_SDK_PATHS:
                probe_case_sensitive(destination)
            for child in sorted(real.iterdir()):
                copy(child, destination / child.name, ancestors | {real})
        elif real.is_file():
            with real.open('rb') as source_file, destination.open('xb') as output_file:
                shutil.copyfileobj(source_file, output_file)
            destination.chmod(0o755 if real.stat().st_mode & 0o111 else 0o644)
        else:
            raise ValueError('supplier tree contains a special file')
    if output.exists() or output.is_symlink(): raise ValueError('materialization output must be new')
    copy(source, output, set())


def seal(root, recipe, target, sources_hash, kind='source-build', licenses=None, production=True, host_tools=None, runtime_source_sha256=None, *, path_policy=PORTABLE_PATHS):
    root = Path(root)
    if (root / 'sdk.json').exists(): raise ValueError('SDK is already sealed')
    metadata = {'schema_version': 1, 'recipe_id': recipe, 'kind': kind, 'target': target,
                'baseline': {'distribution': 'debian-12', 'glibc': '2.36'},
                'host': {'system': 'Linux', 'processor': target['processor'], 'glibc': '2.36'}, 'host_tools': host_tools or {},
                'sources_sha256': sources_hash, 'licenses': licenses or [],
                'relocation': 'relative-paths', 'audits': {}}
    if path_policy != PORTABLE_PATHS:
        metadata['path_policy'] = path_policy
    policy = sdk_path_policy(metadata)
    if policy == LINUX_SDK_PATHS:
        probe_case_sensitive(root)
    if production:
        if target['system'] == 'Linux':
            sysroot = root / target['sysroot']
            cohort = {name: value for name, value in file_inventory(sysroot, path_policy=policy).items()
                      if Path(name).name in SDK_RUNTIME_NAMES
                      and Path(name).parent.as_posix() in ('lib', 'lib64', 'usr/lib', 'usr/lib64')}
            runtime = {'recipe_id': recipe, 'processor': target['processor'], 'glibc': '2.36',
                       'source_sha256': runtime_source_sha256, 'files': cohort}
            metadata['audits']['target'] = audit(sysroot, target['processor'], host=True, sdk_sysroot=runtime)
            # Host compiler support is inspected separately from the target tree.
            host_files = {}
            for directory in ('bin', 'libexec', 'lib'):
                if (root / directory).exists():
                    try: host_files[directory] = audit(root / directory, target['processor'], host=True)
                    except ValueError as error:
                        if str(error) != 'no ELF files inspected': raise
            if not host_files: raise ValueError('SDK contains no auditable host executables')
            metadata['audits']['host'] = {'status': 'passed', 'directories': host_files}
    metadata['files'] = file_inventory(root, path_policy=policy)
    write_json(root / 'sdk.json', metadata)
    verify_sdk(root, release=production)
    return metadata


def export_group(tree, sources, output, epoch=0):
    tree, sources, output = Path(tree), Path(sources), Path(output).absolute()
    verify_sdk(tree)
    metadata = read_json(tree / 'sdk.json')
    recipe = metadata['recipe_id']
    source = read_json(sources / 'sources.json')
    if source.get('schema_version') != 1 or source.get('recipe_id') != recipe:
        raise ValueError('SDK source inventory belongs to another recipe')
    verify_inventory(sources, source['files'], exclude=('sources.json',))
    if digest(sources / 'sources.json') != metadata['sources_sha256']:
        raise ValueError('SDK source inventory identity mismatch')
    if output.exists() or output.is_symlink(): raise ValueError('SDK output group must be new')
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=output.parent, prefix='.sdk-export-') as temporary:
        group = Path(temporary) / 'group'
        group.mkdir()
        binary, source_name, _ = names(recipe)
        archive_tree(tree, group / binary, epoch, path_policy=sdk_path_policy(metadata))
        archive_tree(sources, group / source_name, epoch)
        create_sums(group, recipe)
        group.rename(output)
    return {'recipe_id': recipe, 'files': verify_group(output, recipe)}


def clean_environment(root=None):
    env = sanitized()
    env['LC_ALL'] = 'C'
    env['PYTHONDONTWRITEBYTECODE'] = '1'
    if root: env['PATH'] = str(Path(root) / 'bin') + os.pathsep + '/usr/bin:/bin'
    return env


def smoke(root, work):
    root, work = Path(root).resolve(strict=True), Path(work).absolute()
    verify_sdk(root)
    metadata = read_json(root / 'sdk.json')
    if metadata['target']['system'] == 'Emscripten':
        from sdk_wasm import smoke as browser_smoke
        return browser_smoke(root, work)
    if metadata['target']['system'] != 'Linux':
        raise ValueError('SDK smoke requires a declared platform-specific executor')
    if work.exists(): raise ValueError('SDK smoke work directory must be new')
    work.mkdir(parents=True)
    source = work / 'check.cpp'
    source.write_text('#include <string>\n#include <vector>\nint main(){std::vector<std::string> v{"entry"}; return v.at(0)=="entry" ? 0 : 1;}\n')
    compiler = root / metadata['target']['cxx_compiler']
    executable = work / 'check'
    command = [str(compiler), '-std=c++20', '--sysroot=' + str(root / metadata['target']['sysroot']),
               '-static-libstdc++', '-static-libgcc', str(source), '-o', str(executable)]
    subprocess.run(command, cwd=work, env=clean_environment(root), check=True)
    report = audit(executable, metadata['target']['processor'])
    subprocess.run([str(executable)], cwd=work, env=clean_environment(), check=True)
    write_json(work / 'result.json', report)
    return report


def install(group, recipe, output, production=True, *, expected_files=None):
    group, output = Path(group), Path(output).absolute()
    if expected_files is None: verify_group(group, recipe)
    else:
        from dependency_store import verify_binary_group
        verify_binary_group(group, recipe, expected_files)
    if output.exists() or output.is_symlink(): raise ValueError('SDK installation destination must be new')
    output.parent.mkdir(parents=True, exist_ok=True)
    with sdk_temporary_directory(dir=output.parent, prefix='.sdk-install-') as temporary:
        staged = Path(temporary) / 'sdk'
        archived, _ = inspect_manifest_archive(group / names(recipe)[0], 'sdk.json', sdk_archive=True)
        policy = sdk_path_policy(archived)
        extract(group / names(recipe)[0], staged, path_policy=policy)
        verify_sdk(staged, release=production)
        metadata = read_json(staged / 'sdk.json')
        if metadata['recipe_id'] != recipe: raise ValueError('SDK binary recipe identity mismatch')
        if metadata.get('relocation') not in ('relative-paths', 'buildroot'):
            raise ValueError('unsupported SDK relocation procedure')
        if metadata['relocation'] == 'buildroot':
            # Relocation must run at the final root. Rollback only this newly
            # created directory when the supplier script or verification fails.
            staged.rename(output)
            try:
                subprocess.run([str(output / 'relocate-sdk.sh')], cwd=output, env=clean_environment(output), check=True)
                metadata['installed_root'] = str(output.resolve())
                metadata['archive_sha256'] = digest(group / names(recipe)[0])
                metadata['files'] = file_inventory(output, exclude=('sdk.json',), path_policy=policy)
                write_json(output / 'sdk.json', metadata)
                verify_sdk(output, release=production)
                if production:
                    for tool in metadata.get('host_tools', {}).values():
                        subprocess.run([str(output / tool), '--version'], cwd=output, env=clean_environment(output), check=True, stdout=subprocess.DEVNULL)
                    smoke(output, Path(temporary) / 'compiler-check')
                    verify_sdk(output, release=True)
            except BaseException:
                shutil.rmtree(output)
                raise
        else:
            if production:
                smoke(staged, Path(temporary) / 'compiler-check')
                verify_sdk(staged, release=True)
            staged.rename(output)
    return metadata


def restore_sources(group, recipe, output):
    verify_group(group, recipe)
    extract(Path(group) / names(recipe)[1], output)
    source = read_json(Path(output) / 'sources.json')
    if source['recipe_id'] != recipe: raise ValueError('source recipe mismatch')
    verify_inventory(output, source['files'], exclude=('sources.json',))
    return source


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='action', required=True)
    for action in ('install', 'restore-sources'):
        command = commands.add_parser(action)
        command.add_argument('--group', type=Path, required=True)
        command.add_argument('--recipe', required=True)
        command.add_argument('--output', type=Path, required=True)
        if action == 'install': command.add_argument('--diagnostic', action='store_true', help='do not claim release compatibility')
    check = commands.add_parser('verify')
    check.add_argument('root', type=Path)
    check.add_argument('--release', action='store_true')
    probe = commands.add_parser('smoke')
    probe.add_argument('root', type=Path)
    probe.add_argument('--work', type=Path, required=True)
    pack = commands.add_parser('export')
    pack.add_argument('--tree', type=Path, required=True)
    pack.add_argument('--sources', type=Path, required=True)
    pack.add_argument('--output', type=Path, required=True)
    pack.add_argument('--epoch', type=int, default=0)
    args = parser.parse_args()
    if args.action == 'install': result = install(args.group, args.recipe, args.output, not args.diagnostic)
    elif args.action == 'restore-sources': result = restore_sources(args.group, args.recipe, args.output)
    elif args.action == 'verify': result = {'sha256': verify_sdk(args.root, args.release)}
    elif args.action == 'smoke': result = smoke(args.root, args.work)
    else: result = export_group(args.tree, args.sources, args.output, args.epoch)
    print(encoded(result).decode(), end='')


if __name__ == '__main__':
    try: main()
    except (ValueError, OSError, KeyError, subprocess.CalledProcessError) as error: raise SystemExit(str(error))
