#!/usr/bin/env python3
"""Produce and restore exact Windows dependency groups; never bundle MSVC."""
import argparse
import hashlib
import os
import zipfile
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
from dependency_archive import digest, encoded, extract, file_inventory, read_json, relative, verify_inventory, write_json
from dependency_store import names, verify_group
from sdk import export_group, materialize

TOOLS = ('sdk_windows.py', 'sdk.py', 'sdk_environment.py', 'sdk_manifest.py', 'dependency_store.py', 'dependency_archive.py', 'verify_abi.py', 'select-windows-toolchain.ps1')


def recipe_identity(recipe):
    recipe = Path(recipe)
    inputs = {'windows-base.json': digest(recipe), 'windows-toolchain.json': digest(recipe.parent / 'windows-toolchain.json')}
    inputs.update({'tools/' + name: digest(Path(__file__).parent / name) for name in TOOLS})
    return hashlib.sha256(encoded(inputs)).hexdigest()


def linker_version(value):
    """Compare banner and file versions without treating trailing zero as newer."""
    if not isinstance(value, str) or not re.fullmatch(r'[0-9]+(?:\.[0-9]+){2,3}', value):
        raise ValueError('invalid linker version: expected three or four numeric components')
    fields = tuple(map(int, value.split('.')))
    return fields + (0,) * (4 - len(fields))


def check_provenance(recipe, provenance):
    for key in ('vcpkg_ref', 'triplet', 'ports', 'toolset', 'configurations', 'crt_linkage', 'library_linkage', 'lto'):
        if provenance.get(key) != recipe[key]: raise ValueError('Windows producer provenance differs: ' + key)
    if recipe['toolset'] != 'v143' or recipe['crt_linkage'] != 'static' or recipe['library_linkage'] != 'static' or recipe['lto']:
        raise ValueError('unsupported Windows dependency ABI policy')
    linker_version(provenance.get('linker_version', ''))
    if not re.fullmatch(r'14\.[34]\d\.\d+(?:\.\d+)?', provenance.get('linker_version', '')):
        raise ValueError('record the exact producing v143 linker version')
    if not re.fullmatch(r'\d+\.\d+\.\d+\.\d+', provenance.get('windows_sdk', '')):
        raise ValueError('record the exact producing Windows SDK version')


def assemble(recipe_path, export_root, source_root, provenance_path, output):
    recipe_path, output = Path(recipe_path), Path(output).absolute()
    recipe = checked_recipe(recipe_path)
    provenance = read_json(provenance_path)
    check_provenance(recipe, provenance)
    policy = read_json(recipe_path.parent / 'windows-toolchain.json')
    if provenance['windows_sdk'] != policy['windows_sdk']:
        raise ValueError('producing Windows SDK differs from pinned host policy')
    identity = recipe_identity(recipe_path)
    if recipe['ports']:
        verify_inputs(recipe_path, Path(source_root) / 'cache')
        required = {'.vcpkg-root', 'scripts/buildsystems/vcpkg.cmake'}
        for port in recipe['ports']:
            name = port.split('[', 1)[0]
            required.add('installed/' + recipe['triplet'] + '/share/' + name + '/copyright')
            if not any(p.startswith('installed/vcpkg/info/' + name + '_') and p.endswith('_' + recipe['triplet'] + '.list') for p in provenance['files']):
                raise ValueError('export missing selected port inventory: ' + name)
        if not required <= set(provenance['files']):
            raise ValueError('export missing integration files or selected port notices')
    verify_inventory(export_root, provenance['files'])
    verify_inventory(source_root, provenance['source_files'])
    if output.exists(): raise ValueError('dependency group destination must be new')
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=output.parent) as temporary:
        work = Path(temporary)
        binary = work / 'binary'
        binary.mkdir()
        materialize(export_root, binary / 'prefix')
        sources = work / 'sources'
        materialize(source_root, sources)
        (sources / 'recipe').mkdir()
        shutil.copyfile(recipe_path, sources / 'recipe/windows-base.json')
        shutil.copyfile(recipe_path.parent / 'windows-toolchain.json', sources / 'recipe/windows-toolchain.json')
        (sources / 'tools').mkdir()
        for name in TOOLS: shutil.copyfile(Path(__file__).parent / name, sources / 'tools' / name)
        write_json(sources / 'provenance.json', provenance)
        write_json(sources / 'sources.json', {'schema_version': 1, 'recipe_id': identity, 'files': file_inventory(sources)})
        metadata = {'schema_version': 1, 'recipe_id': identity, 'kind': 'windows-dependencies',
                    'target': {'system': 'Windows', 'processor': 'x86_64', 'triple': 'x64-windows-static', 'sysroot': 'prefix'},
                    'external_toolchain': {'toolset': 'v143', 'minimum_linker': provenance['linker_version'], 'windows_sdk': provenance['windows_sdk']},
                    'sources_sha256': digest(sources / 'sources.json'), 'licenses': ['prefix'],
                    'relocation': 'relative-paths', 'provenance': provenance,
                    'capabilities': recipe.get('capabilities', ['core', 'terminal', 'framebuffer', 'hosted-web']),
                    'files': file_inventory(binary)}
        write_json(binary / 'sdk.json', metadata)
        return export_group(binary, sources, output)


def empty_base(recipe_path, provenance_path, output):
    """Prepare the complete no-external-library base used by the native example."""
    recipe = read_json(recipe_path)
    if recipe['ports']: raise ValueError('nonempty dependency recipe requires reviewed export and source trees')
    provenance = read_json(provenance_path)
    check_provenance(recipe, provenance)
    output = Path(output).absolute()
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=output.parent) as temporary:
        work = Path(temporary)
        export = work / 'export'
        source = work / 'source'
        export.mkdir(); source.mkdir()
        (export / 'README.txt').write_text('No third-party runtime libraries are required by this native core.\nMicrosoft compiler and Windows SDK are separate host prerequisites.\n')
        (source / 'README.txt').write_text('This dependency recipe selects no upstream ports.\n')
        cache = source / 'cache'; cache.mkdir()
        (cache / 'README.txt').write_text('The selected core requires no external dependency inputs.\n')
        write_json(cache / 'inputs.json', {'schema_version': 1, 'recipe_id': recipe_identity(recipe_path),
                   'files': file_inventory(cache)})
        provenance['files'] = file_inventory(export)
        provenance['source_files'] = file_inventory(source)
        write_json(work / 'provenance.json', provenance)
        return assemble(recipe_path, export, source, work / 'provenance.json', output)


def checked_recipe(path):
    recipe = read_json(path)
    if (recipe.get('schema_version') != 1 or recipe.get('kind') != 'windows-dependencies'
            or not re.fullmatch(r'[0-9a-f]{40}', recipe.get('vcpkg_ref', ''))
            or recipe.get('triplet') != 'x64-windows-static'
            or recipe.get('configurations') != ['Debug', 'Release']
            or not isinstance(recipe.get('ports'), list)
            or len(recipe['ports']) != len(set(recipe['ports']))
            or any(not re.fullmatch(r'[a-z0-9][a-z0-9-]*(?:\[(?:[a-z0-9-]+,)*[a-z0-9-]+\])?', p)
                   for p in recipe['ports'])):
        raise ValueError('invalid pinned Windows dependency recipe')
    return recipe


def host_provenance(recipe_path, provenance_path):
    recipe, provenance = checked_recipe(recipe_path), read_json(provenance_path)
    check_provenance(recipe, provenance)
    policy = read_json(Path(recipe_path).parent / 'windows-toolchain.json')
    if provenance['windows_sdk'] != policy['windows_sdk']:
        raise ValueError('producing Windows SDK differs from pinned host policy')
    if os.name != 'nt': raise ValueError('Windows dependency preparation requires a native Windows host')
    if recipe['ports']:
        if not re.fullmatch(r'14\.[34]\d\.\d+', provenance.get('tools_version', '')):
            raise ValueError('nonempty ports require the exact selected tools_version')
        install = Path(provenance.get('installation_path', ''))
        if not install.is_absolute() or not install.is_dir():
            raise ValueError('nonempty ports require the selected installation_path')
        linker = install / 'VC/Tools/MSVC' / provenance['tools_version'] / 'bin/Hostx64/x64/link.exe'
        found = shutil.which('link.exe')
        if not found or Path(found).resolve() != linker.resolve(strict=True):
            raise ValueError('initialize the exact selected Windows toolchain environment')
        result = subprocess.run([str(linker)], text=True, capture_output=True)
        actual = re.search(r'Version (\d+(?:\.\d+)+)', result.stdout + result.stderr)
        if not actual or linker_version(actual[1]) != linker_version(provenance['linker_version']):
            raise ValueError('actual selected linker differs from producer provenance')
    return recipe, provenance


def supplier_environment(checkout, downloads, jobs, network):
    env = dict(os.environ)
    # These locations and cache sources must never inherit a developer's mutable
    # package installation or remote binary cache.
    for key in ('VCPKG_OVERLAY_PORTS', 'VCPKG_OVERLAY_TRIPLETS', 'VCPKG_CHAINLOAD_TOOLCHAIN_FILE',
                'VCPKG_DEFAULT_TRIPLET', 'VCPKG_DEFAULT_HOST_TRIPLET', 'VCPKG_VISUAL_STUDIO_PATH'):
        env.pop(key, None)
    env.update(VCPKG_ROOT=str(checkout), VCPKG_DOWNLOADS=str(downloads),
               VCPKG_BINARY_SOURCES='clear', X_VCPKG_ASSET_SOURCES='clear' if network else 'clear;x-block-origin',
               VCPKG_DISABLE_METRICS='1', VCPKG_MAX_CONCURRENCY=str(jobs), PYTHONDONTWRITEBYTECODE='1')
    return env


def write_triplet(directory, provenance):
    directory.mkdir()
    text = ('set(VCPKG_TARGET_ARCHITECTURE x64)\nset(VCPKG_CRT_LINKAGE static)\n'
            'set(VCPKG_LIBRARY_LINKAGE static)\nset(VCPKG_PLATFORM_TOOLSET v143)\n'
            'set(VCPKG_C_FLAGS "/GL-")\nset(VCPKG_CXX_FLAGS "/GL-")\n'
            'set(VCPKG_CMAKE_CONFIGURE_OPTIONS "-DCMAKE_INTERPROCEDURAL_OPTIMIZATION=OFF")\n')
    for key, value in (('VCPKG_PLATFORM_TOOLSET_VERSION', provenance['tools_version']),
                       ('VCPKG_CMAKE_SYSTEM_VERSION', provenance['windows_sdk'])):
        text += 'set(' + key + ' "' + value + '")\n'
    # The local installation path is an execution input; it is not exported in
    # the reusable triplet. vcpkg receives it via its explicit environment.
    (directory / 'x64-windows-static.cmake').write_bytes(text.encode('utf-8'))


def supplier_command(checkout, triplets, recipe, action):
    base = [str(checkout / 'vcpkg.exe'), action, '--triplet=' + recipe['triplet'],
            '--host-triplet=' + recipe['triplet'], '--overlay-triplets=' + str(triplets), '--disable-metrics']
    ports = [port.split('[', 1)[0] for port in recipe['ports']] if action == 'export' else recipe['ports']
    return base + [port + ':' + recipe['triplet'] for port in ports]


def extract_supplier(archive, destination, revision):
    if destination.exists(): raise ValueError('supplier extraction destination must be new')
    with zipfile.ZipFile(archive) as source:
        if source.comment.decode('ascii') != revision:
            raise ValueError('retained package-manager archive differs from pinned Git revision')
        seen = set()
        for entry in source.infolist():
            name = str(relative(entry.filename.rstrip('/')))
            if entry.orig_filename != entry.filename or name.casefold() in seen:
                raise ValueError('duplicate or unsafe package-manager source path')
            seen.add(name.casefold())
            mode = entry.external_attr >> 16
            if entry.flag_bits & 1 or (mode & 0o170000) not in (0, 0o100000, 0o040000) or mode & 0o7000:
                raise ValueError('unsupported package-manager source entry')
        files = {entry.filename.rstrip('/').casefold() for entry in source.infolist() if not entry.is_dir()}
        if any(any(str(p).casefold() in files for p in relative(e.filename.rstrip('/')).parents)
               for e in source.infolist()):
            raise ValueError('package-manager source file is an ancestor')
        destination.mkdir()
        for entry in source.infolist():
            output = destination / entry.filename
            if entry.is_dir(): output.mkdir(parents=True, exist_ok=True)
            else:
                output.parent.mkdir(parents=True, exist_ok=True)
                with source.open(entry) as src, output.open('xb') as dst: shutil.copyfileobj(src, dst)


def verify_inputs(recipe_path, cache):
    cache = Path(cache).resolve(strict=True)
    state = read_json(cache / 'inputs.json')
    if state.get('schema_version') != 1 or state.get('recipe_id') != recipe_identity(recipe_path):
        raise ValueError('Windows retained inputs belong to another complete recipe')
    verify_inventory(cache, state['files'], exclude=('inputs.json',))
    recipe = checked_recipe(recipe_path)
    if recipe['ports']:
        for name in ('vcpkg-source.zip', 'vcpkg.exe'):
            if name not in state['files']: raise ValueError('Windows retained input is missing: ' + name)
        if not any(name.startswith('downloads/') for name in state['files']):
            raise ValueError('nonempty ports require retained dependency downloads')
        with zipfile.ZipFile(cache / 'vcpkg-source.zip') as source:
            if source.comment.decode('ascii') != recipe['vcpkg_ref']:
                raise ValueError('Windows retained source revision differs')
    return state


def fetch(recipe_path, provenance_path, cache, jobs=2):
    """Explicit online preparation; no application job calls this implicitly."""
    recipe, provenance = host_provenance(recipe_path, provenance_path)
    cache = Path(cache).absolute()
    if cache.exists(): raise ValueError('Windows input cache destination must be new')
    cache.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=cache.parent) as temporary:
        work = Path(temporary); retained = work / 'retained'; retained.mkdir()
        if recipe['ports']:
            checkout = work / 'vcpkg'
            subprocess.run(['git', 'init', str(checkout)], check=True)
            subprocess.run(['git', '-C', str(checkout), 'fetch', '--depth=1',
                            'https://github.com/microsoft/vcpkg.git', recipe['vcpkg_ref']], check=True)
            actual = subprocess.check_output(['git', '-C', str(checkout), 'rev-parse', 'FETCH_HEAD^{commit}'], text=True).strip()
            if actual != recipe['vcpkg_ref']: raise ValueError('package-manager revision did not resolve exactly')
            subprocess.run(['git', '-C', str(checkout), 'checkout', '--detach', actual], check=True)
            subprocess.run(['git', '-C', str(checkout), 'archive', '--format=zip',
                            '--output=' + str(retained / 'vcpkg-source.zip'), actual], check=True)
            downloads = retained / 'downloads'; downloads.mkdir()
            env = supplier_environment(checkout, downloads, jobs, True)
            env['VCPKG_VISUAL_STUDIO_PATH'] = provenance['installation_path']
            subprocess.run(['cmd.exe', '/d', '/c', str(checkout / 'bootstrap-vcpkg.bat'), '-disableMetrics'],
                           cwd=checkout, env=env, check=True)
            shutil.copyfile(checkout / 'vcpkg.exe', retained / 'vcpkg.exe')
            triplets = work / 'triplets'; write_triplet(triplets, provenance)
            # Traverse configure/build-time downloads as well as source URLs.
            # --only-downloads omits late tools (for example an MSYS build tool).
            # This explicit maintenance build is discarded: the separate cold
            # build below must recreate every library with downloads disabled.
            subprocess.run(supplier_command(checkout, triplets, recipe, 'install'),
                           cwd=checkout, env=env, check=True)
        else:
            (retained / 'README.txt').write_text('The selected core requires no external dependency inputs.\n')
        write_json(retained / 'inputs.json', {'schema_version': 1, 'recipe_id': recipe_identity(recipe_path),
                   'files': file_inventory(retained)})
        verify_inputs(recipe_path, retained)
        retained.rename(cache)
    return {'recipe_id': recipe_identity(recipe_path), 'files': read_json(cache / 'inputs.json')['files']}


def build(recipe_path, provenance_path, cache, output, jobs=2):
    """Restore a fresh build tree and export with all supplier downloads disabled."""
    recipe, provenance = host_provenance(recipe_path, provenance_path)
    verify_inputs(recipe_path, cache)
    cache, output = Path(cache).resolve(strict=True), Path(output).absolute()
    if output.exists(): raise ValueError('dependency group destination must be new')
    if not recipe['ports']: return empty_base(recipe_path, provenance_path, output)
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=output.parent) as temporary:
        work = Path(temporary); checkout = work / 'vcpkg'
        extract_supplier(cache / 'vcpkg-source.zip', checkout, recipe['vcpkg_ref'])
        shutil.copyfile(cache / 'vcpkg.exe', checkout / 'vcpkg.exe')
        downloads = work / 'downloads'; materialize(cache / 'downloads', downloads)
        triplets = work / 'triplets'; write_triplet(triplets, provenance)
        env = supplier_environment(checkout, downloads, jobs, False)
        env['VCPKG_VISUAL_STUDIO_PATH'] = provenance['installation_path']
        subprocess.run(supplier_command(checkout, triplets, recipe, 'install') + ['--no-downloads'],
                       cwd=checkout, env=env, check=True)
        subprocess.run(supplier_command(checkout, triplets, recipe, 'export') +
                       ['--raw', '--output=prepared', '--output-dir=' + str(work)], cwd=checkout, env=env, check=True)
        export = work / 'prepared'
        sources = work / 'sources'; sources.mkdir(); materialize(cache, sources / 'cache')
        verify_inputs(recipe_path, cache)
        provenance.update(files=file_inventory(export), source_files=file_inventory(sources))
        write_json(work / 'provenance.json', provenance)
        return assemble(recipe_path, export, sources, work / 'provenance.json', output)


def install(group, recipe, output, consumer_linker_version, *, expected_files=None):
    if expected_files is None: verify_group(group, recipe)
    else:
        from dependency_store import verify_binary_group
        verify_binary_group(group, recipe, expected_files)
    output = Path(output).absolute()
    if output.exists(): raise ValueError('dependency installation destination must be new')
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=output.parent) as temporary:
        tree = Path(temporary) / 'base'
        extract(Path(group) / names(recipe)[0], tree)
        metadata = read_json(tree / 'sdk.json')
        if metadata.get('kind') != 'windows-dependencies': raise ValueError('not a Windows dependency base')
        if linker_version(consumer_linker_version) < linker_version(metadata['external_toolchain']['minimum_linker']):
            raise ValueError('consuming linker is older than the producing linker')
        verify_inventory(tree, metadata['files'], exclude=('sdk.json',))
        tree.rename(output)
    return metadata


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('recipe-id', 'empty-base', 'assemble', 'install', 'fetch', 'build', 'verify-inputs'))
    parser.add_argument('--recipe-file', type=Path, default=Path(__file__).resolve().parents[1] / 'third_party/sdk/windows-base.json')
    parser.add_argument('--provenance', type=Path)
    parser.add_argument('--cache', type=Path)
    parser.add_argument('--jobs', type=int, default=2)
    parser.add_argument('--export-root', type=Path)
    parser.add_argument('--source-root', type=Path)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--group', type=Path)
    parser.add_argument('--recipe')
    parser.add_argument('--linker-version')
    args = parser.parse_args()
    if args.jobs < 1: parser.error('--jobs must be positive')
    if args.action in ('fetch', 'build', 'verify-inputs'):
        if not args.cache: parser.error('--cache is required')
        if args.action == 'verify-inputs': result = verify_inputs(args.recipe_file, args.cache)
        else:
            if not args.provenance: parser.error('--provenance is required')
            if args.action == 'fetch': result = fetch(args.recipe_file, args.provenance, args.cache, args.jobs)
            else:
                if not args.output: parser.error('--output is required')
                result = build(args.recipe_file, args.provenance, args.cache, args.output, args.jobs)
    elif args.action == 'recipe-id': result = {'recipe_id': recipe_identity(args.recipe_file)}
    elif args.action == 'empty-base':
        if not args.provenance or not args.output: parser.error('empty-base requires --provenance and --output')
        result = empty_base(args.recipe_file, args.provenance, args.output)
    elif args.action == 'assemble':
        if not all((args.export_root, args.source_root, args.provenance, args.output)): parser.error('assemble requires --export-root --source-root --provenance --output')
        result = assemble(args.recipe_file, args.export_root, args.source_root, args.provenance, args.output)
    else:
        if not all((args.group, args.recipe, args.output, args.linker_version)): parser.error('install requires --group --recipe --output --linker-version')
        result = install(args.group, args.recipe, args.output, args.linker_version)
    print(encoded(result).decode(), end='')


if __name__ == '__main__':
    try: main()
    except (ValueError, OSError, KeyError, subprocess.CalledProcessError, zipfile.BadZipFile) as error: raise SystemExit(str(error))
