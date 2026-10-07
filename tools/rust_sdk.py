#!/usr/bin/env python3
"""Explicit official Rust acquisition and retained, offline SDK extension replay."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess
import tarfile
import tempfile
import urllib.request

from dependency_archive import (archive_tree, checked_file, digest, encoded, extract,
                                file_inventory, inspect_manifest_archive, read_json,
                                object_pairs, relative, verify_inventory, write_json)
from sdk_environment import sanitized
from sdk_manifest import verify_sdk
from verify_abi import audit

TOOLS = ('rust_sdk.py', 'dependency_archive.py', 'sdk_environment.py', 'sdk_manifest.py', 'verify_abi.py')
SHA256 = re.compile(r'[0-9a-f]{64}')
RECOVERY_SCOPE = ('Offline restoration from the exact retained official compiler, Cargo, '
                  'target-library and source archives. Compiler/Cargo reconstruction '
                  'from source and a complete source-build bootstrap closure are not qualified.')
TARGETS = {
    'x86_64-unknown-linux-gnu': ('Linux', 'x86_64'),
    'aarch64-unknown-linux-gnu': ('Linux', 'aarch64'),
    'x86_64-pc-windows-msvc': ('Windows', 'x86_64'),
    'wasm32-unknown-emscripten': ('Emscripten', 'wasm32'),
}


def full_hash(value, description):
    if not isinstance(value, str) or not SHA256.fullmatch(value):
        raise ValueError('invalid complete SHA-256: ' + description)
    return value


def recipe_identity(recipe):
    inputs = {'recipe/rust.json': digest(recipe)}
    inputs.update({'tools/' + name: digest(Path(__file__).parent / name) for name in TOOLS})
    return hashlib.sha256(encoded(inputs)).hexdigest()


def checked_recipe(recipe):
    return check_recipe_data(read_json(recipe))


def check_recipe_data(data):
    if not isinstance(data, dict):
        raise ValueError('Rust recipe must be an object')
    if data.get('schema_version') != 1 or data.get('kind') != 'official-rust-components':
        raise ValueError('invalid Rust component recipe')
    host, target = data.get('host'), data.get('target')
    if host not in TARGETS or host == 'wasm32-unknown-emscripten' or target not in TARGETS:
        raise ValueError('unsupported Rust host or target')
    if target != 'wasm32-unknown-emscripten' and host != target:
        raise ValueError('native Rust extension requires matching host and target')
    if not re.fullmatch(r'\d+\.\d+\.\d+', data.get('version', '')):
        raise ValueError('Rust recipe requires an exact compiler version')
    if not re.fullmatch(r'\d{4}-\d{2}-\d{2}', data.get('release_date', '')):
        raise ValueError('Rust recipe requires an exact distribution date')
    if not re.fullmatch(r'[0-9a-f]{40}', data.get('compiler_commit', '')) or not re.fullmatch(r'[0-9a-f]{9,40}', data.get('cargo_commit', '')):
        raise ValueError('Rust recipe requires exact compiler/Cargo source revisions')
    for field in ('cargo_version', 'cargo_package_version'):
        if not re.fullmatch(r'\d+\.\d+\.\d+', data.get(field, '')):
            raise ValueError('Rust recipe requires an exact Cargo version: ' + field)
    bootstrap = data.get('bootstrap')
    if not isinstance(bootstrap, dict) or not re.fullmatch(r'\d+\.\d+\.\d+', bootstrap.get('version', '')) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}', bootstrap.get('date', '')):
        raise ValueError('Rust recipe requires exact source bootstrap inputs')
    if target == 'wasm32-unknown-emscripten':
        full_hash(data.get('cpp_sdk_recipe_id'), 'paired C++ recipe')
        if data.get('emscripten_version_file') not in (
                data.get('emscripten_version'), data.get('emscripten_version', '') + '-git'):
            raise ValueError('Rust recipe requires exact supplier Emscripten version text')
    if data.get('recovery_scope') != RECOVERY_SCOPE:
        raise ValueError('Rust recipe must state the bounded recovery contract')
    items = data.get('inputs')
    if not isinstance(items, list) or not items:
        raise ValueError('missing exact Rust binary/source inputs')
    names, filenames = set(), set()
    for item in items:
        if not isinstance(item, dict):
            raise ValueError('invalid Rust input')
        name = item.get('name')
        if not isinstance(name, str) or name in names:
            raise ValueError('duplicate Rust input name')
        names.add(name)
        filename = relative(item.get('file'))
        if len(filename.parts) != 1:
            raise ValueError('Rust input filename must be a basename')
        if str(filename) in filenames:
            raise ValueError('duplicate Rust supplier filename')
        filenames.add(str(filename))
        full_hash(item.get('sha256'), name)
        if not item.get('url', '').startswith('https://static.rust-lang.org/dist/'):
            raise ValueError('Rust recipe must pin an official HTTPS distribution URL')
    expected = {'rustc', 'cargo', 'host-std', 'rust-src', 'compiler-source', 'release-manifest',
                'stage0-rustc', 'stage0-cargo', 'stage0-std'}
    if target != host:
        expected.add('target-std')
    if names != expected:
        raise ValueError('Rust recipe omits or adds a binary/source/bootstrap input')
    components = {'rustc': ('rustc', host), 'cargo': ('cargo', host), 'host-std': ('rust-std', host),
                  'target-std': ('rust-std', target), 'rust-src': ('rust-src', None)}
    for item in items:
        name = item['name']
        if name in components:
            component, triple = components[name]
            basename = component + '-' + data['version'] + ('-' + triple if triple else '') + '.tar.xz'
            suffix = data['release_date'] + '/' + basename
        elif name.startswith('stage0-'):
            component = {'stage0-rustc': 'rustc', 'stage0-cargo': 'cargo', 'stage0-std': 'rust-std'}[name]
            basename = component + '-' + bootstrap['version'] + '-' + host + '.tar.xz'
            suffix = bootstrap['date'] + '/' + basename
        elif name == 'compiler-source':
            basename = 'rustc-' + data['version'] + '-src.tar.xz'
            suffix = data['release_date'] + '/' + basename
        else:
            basename = 'channel-rust-' + data['version'] + '.toml'
            suffix = basename
        if item['file'] != basename or item['url'] != 'https://static.rust-lang.org/dist/' + suffix:
            raise ValueError('Rust input filename/URL differs from declared component tuple: ' + name)
    return data


def fetch(recipe, inputs, network=False):
    """Only an explicit fetch action may acquire missing supplier bytes."""
    data = checked_recipe(recipe)
    inputs = Path(inputs)
    for item in data['inputs']:
        path = inputs / item['file']
        if path.is_symlink():
            raise ValueError('linked Rust supplier input')
        if path.exists():
            if not path.is_file() or digest(path) != item['sha256']:
                raise ValueError('changed pinned Rust input: ' + item['file'])
            continue
        if not network:
            raise ValueError('missing pinned Rust input; explicit fetch required: ' + item['file'])
        inputs.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=inputs, delete=False) as stream:
            temporary = Path(stream.name)
        try:
            with urllib.request.urlopen(item['url'], timeout=60) as source, temporary.open('wb') as output:
                shutil.copyfileobj(source, output)
            if digest(temporary) != item['sha256']:
                raise ValueError('pinned official Rust checksum mismatch: ' + item['file'])
            temporary.replace(path)
        finally:
            temporary.unlink(missing_ok=True)
    return data


def environment(root):
    result = sanitized()
    for name in list(result):
        if name.startswith(('CARGO_', 'RUSTUP_', 'RUSTC_', 'RUSTDOC_')) or name in (
                'RUSTFLAGS', 'RUSTDOCFLAGS', 'RUSTC', 'RUSTDOC'):
            result.pop(name, None)
    result['PATH'] = str(Path(root) / 'bin') + os.pathsep + os.defpath
    result['LC_ALL'] = 'C'
    result['PYTHONDONTWRITEBYTECODE'] = '1'
    return result


def verify_pair(data, cpp_data):
    """Pair native ABIs or the exact prepared Emscripten SDK recipe."""
    target, cpp = data['target'], cpp_data['target']
    if (target['system'], target['processor']) != (cpp['system'], cpp['processor']):
        raise ValueError('Rust extension target differs from selected C++ SDK')
    host = cpp_data.get('host')
    if host and (host.get('system'), host.get('processor')) != (
            data['host']['system'], data['host']['processor']):
        raise ValueError('Rust extension host differs from selected C++ SDK')
    if target['system'] == 'Linux' and not cpp.get('triple', '').endswith('-linux-gnu'):
        raise ValueError('Rust GNU target requires a GNU/Linux C++ SDK')
    if target['system'] == 'Windows':
        windows_dependencies = (cpp_data.get('kind') == 'windows-dependencies'
                                and cpp.get('triple') == 'x64-windows-static'
                                and cpp_data.get('external_toolchain', {}).get('toolset') == 'v143')
        if cpp.get('triple') != 'x86_64-pc-windows-msvc' and not windows_dependencies:
            raise ValueError('Rust MSVC target requires the Windows MSVC C++ SDK')
    bound = target.get('cpp_sdk_recipe_id')
    if bound and bound != cpp_data['recipe_id']:
        raise ValueError('Rust extension names a different paired C++ SDK recipe')
    if target['system'] == 'Emscripten' and not bound:
        raise ValueError('Rust Emscripten extension lacks an exact C++ SDK recipe binding')


def verify_rust_sdk(root, cpp_sdk=None, target=None, execute=False):
    root = Path(root).resolve(strict=True)
    data = read_json(root / 'rust-sdk.json')
    check_extension_data(data)
    if data.get('schema_version') != 1 or data.get('kind') != 'rust-extension':
        raise ValueError('invalid Rust SDK extension schema')
    full_hash(data.get('recipe_id'), 'Rust recipe')
    full_hash(data.get('sources_sha256'), 'Rust sources')
    if data.get('recovery_scope') != RECOVERY_SCOPE:
        raise ValueError('Rust SDK lacks the bounded source recovery statement')
    compiler = data.get('compiler', {})
    item = data.get('target', {})
    triple = item.get('triple')
    if triple not in TARGETS or (item.get('system'), item.get('processor')) != TARGETS[triple]:
        raise ValueError('unsupported or inconsistent Rust target identity')
    if target is not None and triple != target:
        raise ValueError('selected Rust target differs from retained target')
    host = compiler.get('host')
    if host not in TARGETS or host == 'wasm32-unknown-emscripten' or data.get('host') != dict(
            zip(('system', 'processor'), TARGETS[host])):
        raise ValueError('unsupported or inconsistent Rust compiler host identity')
    if triple != 'wasm32-unknown-emscripten' and host != triple:
        raise ValueError('native Rust SDK compiler host differs from target')
    if not re.fullmatch(r'\d+\.\d+\.\d+', compiler.get('version', '')):
        raise ValueError('missing exact Rust compiler version')
    if not re.fullmatch(r'\d+\.\d+\.\d+', compiler.get('cargo_version', '')):
        raise ValueError('missing exact Cargo executable version')
    verify_inventory(root, data.get('files'), exclude=('rust-sdk.json',))
    for field in ('rustc', 'cargo'):
        checked_file(root, compiler.get(field))
        if compiler[field] not in data['files']:
            raise ValueError('Rust host tool omitted from inventory')
    sysroot_name = compiler.get('sysroot')
    # The ordinary distribution sysroot is the extension root itself.
    if sysroot_name != '.':
        relative(sysroot_name)
        if not (root / sysroot_name).is_dir():
            raise ValueError('missing Rust compiler sysroot')
    library_name = str(relative(item.get('library_directory')))
    library = root / library_name
    if not library.is_dir():
        raise ValueError('missing retained Rust target libraries')
    for crate in ('core', 'std', 'compiler_builtins'):
        matches = [name for name in data['files']
                   if Path(name).parent.as_posix() == library_name
                   and re.fullmatch(r'lib' + crate + r'-[0-9a-f]+\.rlib', Path(name).name)]
        if len(matches) != 1:
            raise ValueError('missing or ambiguous matched Rust target crate: ' + crate)
    licenses = data.get('licenses')
    if not isinstance(licenses, list) or not licenses:
        raise ValueError('Rust extension lacks retained compiler/Cargo notices')
    for name in licenses:
        checked_file(root, name)
        if name not in data['files']:
            raise ValueError('Rust notice omitted from inventory')
    if item['system'] == 'Emscripten':
        full_hash(item.get('cpp_sdk_recipe_id'), 'paired C++ SDK recipe')
        if not re.fullmatch(r'\d+\.\d+\.\d+', item.get('emscripten_version', '')):
            raise ValueError('missing exact paired Emscripten version')
        if item.get('emscripten_version_file') not in (item['emscripten_version'], item['emscripten_version'] + '-git'):
            raise ValueError('missing exact paired Emscripten version file identity')
    if 'host_audit' in data:
        report = data['host_audit']
        if not isinstance(report, dict) or report.get('status') != 'passed' or report.get('scope') != 'host' or report.get('processor') != data['host']['processor']:
            raise ValueError('invalid retained Rust compiler host ABI audit')
        for name, value in report.get('files', {}).items():
            if not isinstance(value, dict) or value.get('sha256') != data['files'].get(name):
                raise ValueError('Rust compiler host audit differs from retained files')
    if cpp_sdk is not None:
        cpp_sdk = Path(cpp_sdk).resolve(strict=True)
        verify_sdk(cpp_sdk)
        cpp_data = read_json(cpp_sdk / 'sdk.json')
        verify_pair(data, cpp_data)
        if item['system'] == 'Emscripten':
            version_path = 'upstream/emscripten/emscripten-version.txt'
            if version_path not in cpp_data['files']:
                raise ValueError('paired Emscripten version omitted from C++ SDK inventory')
            version = checked_file(cpp_sdk, version_path).read_text().strip().strip('"')
            if version != item.get('emscripten_version_file', item['emscripten_version']):
                raise ValueError('retained Rust/Emscripten version tuple differs')
    if execute:
        if (platform.system(), normalized_processor(platform.machine())) != (
                data['host']['system'], data['host']['processor']):
            raise ValueError('Rust compiler execution requires its declared native host')
        env = environment(root)
        rustc = root / compiler['rustc']
        report = subprocess.check_output([str(rustc), '-vV'], cwd=root, env=env, text=True)
        fields = dict(line.split(': ', 1) for line in report.splitlines() if ': ' in line)
        if fields.get('release') != compiler['version'] or fields.get('host') != host:
            raise ValueError('Rust compiler version/host probe differs from retained metadata')
        cargo = subprocess.check_output([str(root / compiler['cargo']), '--version'], cwd=root,
                                        env=env, text=True).split()
        if len(cargo) < 2 or cargo[:2] != ['cargo', compiler['cargo_version']]:
            raise ValueError('Cargo executable version probe differs from retained metadata')
        actual = subprocess.check_output([str(rustc), '--print', 'sysroot'], cwd=root, env=env,
                                         text=True).strip()
        if Path(actual).resolve() != (root / sysroot_name).resolve():
            raise ValueError('Rust compiler resolves a different sysroot')
        actual = subprocess.check_output([str(rustc), '--print', 'target-libdir', '--target', triple],
                                         cwd=root, env=env, text=True).strip()
        if Path(actual).resolve() != library.resolve():
            raise ValueError('Rust compiler resolves different target libraries')
        verify_inventory(root, data['files'], exclude=('rust-sdk.json',))
    return data


def normalized_processor(value):
    return {'AMD64': 'x86_64', 'amd64': 'x86_64', 'ARM64': 'aarch64', 'arm64': 'aarch64'}.get(value, value)


def verify(root, cpp_sdk=None, target=None, execute=False):
    verify_rust_sdk(root, cpp_sdk, target, execute)
    return digest(Path(root) / 'rust-sdk.json')


def group_names(recipe):
    full_hash(recipe, 'Rust group recipe')
    stem = 'rust-sdk-' + recipe
    return stem + '-binary.tar.gz', stem + '-sources.tar.gz', stem + '-SHA256SUMS'


names = group_names


def check_extension_data(data):
    if not isinstance(data, dict) or data.get('schema_version') != 1 or data.get('kind') != 'rust-extension':
        raise ValueError('invalid Rust extension manifest')
    for field in ('compiler', 'host', 'target', 'files'):
        if not isinstance(data.get(field), dict):
            raise ValueError('invalid Rust extension object: ' + field)
    for field in ('recipe_id', 'sources_sha256'):
        full_hash(data.get(field), field)
    for field in ('rustc', 'cargo', 'sysroot', 'version', 'cargo_version', 'host'):
        if not isinstance(data['compiler'].get(field), str):
            raise ValueError('invalid Rust compiler metadata: ' + field)
    triple = data['target'].get('triple')
    if triple not in TARGETS:
        raise ValueError('unsupported Rust extension target')
    if (data['target'].get('system'), data['target'].get('processor')) != TARGETS[triple]:
        raise ValueError('inconsistent Rust extension target')
    relative(data['target'].get('library_directory'))
    for field in ('rustc', 'cargo'):
        relative(data['compiler'][field])
        if data['compiler'][field] not in data['files']:
            raise ValueError('Rust compiler tool omitted from inventory')
    for name, value in data['files'].items():
        relative(name)
        full_hash(value, 'Rust retained file')
    if data.get('recovery_scope') != RECOVERY_SCOPE:
        raise ValueError('Rust extension lacks the bounded source recovery statement')
    return data


def verify_stage0(recipe, stage0):
    if not isinstance(stage0, dict) or stage0.get('compiler') != recipe['bootstrap']:
        raise ValueError('source stage0 bootstrap tuple differs from pinned recipe')
    for item in recipe['inputs']:
        if item['name'].startswith('stage0-'):
            path = 'dist/' + recipe['bootstrap']['date'] + '/' + item['file']
            if stage0.get('checksums_sha256', {}).get(path) != item['sha256']:
                raise ValueError('retained stage0 binary differs from compiler source checksum')


def verify_source_binding(source_data, recipe_data):
    data = check_recipe_data(recipe_data)
    files = source_data.get('files', {})
    names = ['recipe/rust.json'] + ['tools/' + name for name in TOOLS]
    if any(name not in files for name in names):
        raise ValueError('retained Rust sources omit recipe or producer helpers')
    identity = hashlib.sha256(encoded({name: files[name] for name in names})).hexdigest()
    if source_data.get('recipe_id') != identity:
        raise ValueError('retained Rust source recipe/helper identity differs')
    if source_data.get('recovery_scope') != RECOVERY_SCOPE or source_data.get('bootstrap_reconstructed') is not False:
        raise ValueError('retained Rust sources lack the bounded bootstrap contract')
    for item in data['inputs']:
        if files.get('inputs/' + item['file']) != item['sha256']:
            raise ValueError('retained Rust sources omit or change pinned supplier input: ' + item['file'])
    if 'bootstrap/stage0.json' not in files:
        raise ValueError('retained Rust sources omit source bootstrap metadata')
    return data


def verify_sources(sources):
    sources = Path(sources)
    source_data = read_json(sources / 'sources.json')
    verify_inventory(sources, source_data['files'], exclude=('sources.json',))
    data = verify_source_binding(source_data, read_json(sources / 'recipe/rust.json'))
    verify_stage0(data, read_json(sources / 'bootstrap/stage0.json'))
    return source_data


def verify_group(group, recipe):
    group = Path(group)
    binary, sources, sums = group_names(recipe)
    if group.is_symlink() or not group.is_dir() or {p.name for p in group.iterdir()} != {binary, sources, sums}:
        raise ValueError('Rust SDK group must contain exactly the binary/source/checksum triplet')
    for name in (binary, sources, sums):
        checked_file(group, name)
    hashes = {}
    for line in (group / sums).read_text().splitlines():
        fields = line.split('  ')
        if len(fields) != 2 or fields[1] in hashes:
            raise ValueError('invalid or duplicate Rust group checksum entry')
        hashes[str(relative(fields[1]))] = full_hash(fields[0], 'Rust group checksum')
    if set(hashes) != {binary, sources}:
        raise ValueError('Rust checksums must cover exactly the matched binary/source pair')
    if any(digest(group / name) != value for name, value in hashes.items()):
        raise ValueError('Rust retained archive checksum mismatch')
    metadata, _ = inspect_manifest_archive(group / binary, 'rust-sdk.json')
    check_extension_data(metadata)
    source_data, source_hash = inspect_manifest_archive(group / sources, 'sources.json')
    with tarfile.open(group / sources) as archive:
        documents = []
        for name in ('recipe/rust.json', 'bootstrap/stage0.json'):
            try:
                member = archive.getmember(name)
            except KeyError as error:
                raise ValueError('retained Rust source group omits ' + name) from error
            if not member.isfile() or member.size > 1024 * 1024:
                raise ValueError('retained Rust metadata must be a bounded ordinary file')
            with archive.extractfile(member) as stream:
                documents.append(json.load(stream, object_pairs_hook=object_pairs))
    recipe_data = verify_source_binding(source_data, documents[0])
    verify_stage0(recipe_data, documents[1])
    if metadata.get('recipe_id') != recipe or source_data.get('recipe_id') != recipe:
        raise ValueError('Rust retained archive recipe identity mismatch')
    if metadata.get('sources_sha256') != source_hash:
        raise ValueError('Rust binary/source inventory binding differs')
    return {name: digest(group / name) for name in sorted((binary, sources, sums))}


def export_group(tree, sources, output, epoch=0):
    data = verify_rust_sdk(tree)
    source_data = verify_sources(sources)
    recipe = data['recipe_id']
    if source_data.get('schema_version') != 1 or source_data.get('recipe_id') != recipe:
        raise ValueError('Rust source inventory belongs to another recipe')
    verify_inventory(sources, source_data['files'], exclude=('sources.json',))
    if digest(Path(sources) / 'sources.json') != data['sources_sha256']:
        raise ValueError('Rust source inventory identity mismatch')
    output = Path(output).absolute()
    if output.exists() or output.is_symlink():
        raise ValueError('Rust group export destination must be new')
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=output.parent, prefix='.rust-export-') as temporary:
        group = Path(temporary) / 'group'
        group.mkdir()
        binary, source_name, sums = group_names(recipe)
        archive_tree(tree, group / binary, epoch)
        archive_tree(sources, group / source_name, epoch)
        (group / sums).write_text(''.join(digest(group / name) + '  ' + name + '\n'
                                        for name in (binary, source_name)))
        files = verify_group(group, recipe)
        group.rename(output)
    return {'recipe_id': recipe, 'files': files}


def restore(group, recipe, output, cpp_sdk=None, target=None, execute=False):
    verify_group(group, recipe)
    output = Path(output).absolute()
    if output.exists() or output.is_symlink():
        raise ValueError('Rust SDK restoration destination must be new')
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=output.parent, prefix='.rust-restore-') as temporary:
        tree = Path(temporary) / 'sdk'
        extract(Path(group) / group_names(recipe)[0], tree)
        data = verify_rust_sdk(tree, cpp_sdk, target, execute)
        if data['recipe_id'] != recipe:
            raise ValueError('restored Rust compiler recipe differs')
        tree.rename(output)
    return data


install = restore


def restore_sources(group, recipe, output):
    verify_group(group, recipe)
    output = Path(output).absolute()
    if output.exists() or output.is_symlink():
        raise ValueError('Rust source restoration destination must be new')
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=output.parent, prefix='.rust-sources-') as temporary:
        tree = Path(temporary) / 'sources'
        extract(Path(group) / group_names(recipe)[1], tree)
        data = verify_sources(tree)
        if data.get('recipe_id') != recipe:
            raise ValueError('restored Rust source recipe differs')
        tree.rename(output)
    return data


def install_component(archive, output, work, item, recipe):
    unpacked = work / ('unpack-' + item['name'])
    extract(archive, unpacked)
    roots = list(unpacked.iterdir())
    if len(roots) != 1 or not roots[0].is_dir():
        raise ValueError('official Rust package must have one top-level directory')
    supplier = roots[0]
    expected = recipe['cargo_package_version'] if item['name'] == 'cargo' else recipe['version']
    supplier_version = (supplier / 'version').read_text().strip().split()
    if not supplier_version or supplier_version[0] != expected:
        raise ValueError('official Rust package version differs from declared recipe: ' + item['name'])
    commit = recipe['cargo_commit'] if item['name'] == 'cargo' else recipe['compiler_commit']
    if len(supplier_version) < 2 or supplier_version[1].strip('()') != commit[:9]:
        raise ValueError('official Rust package source revision differs from recipe: ' + item['name'])
    component_names = (supplier / 'components').read_text().splitlines()
    if len(component_names) != 1 or len(relative(component_names[0]).parts) != 1:
        raise ValueError('official Rust package has an unexpected component list')
    component = supplier / component_names[0]
    if not component.is_dir():
        raise ValueError('missing official Rust package component')
    for path in sorted(component.rglob('*')):
        name = path.relative_to(component)
        if name.as_posix() == 'manifest.in':
            continue
        destination = output / name
        if path.is_dir():
            destination.mkdir(parents=True, exist_ok=True)
        elif path.is_file():
            if destination.exists():
                if not destination.is_file() or digest(path) != digest(destination):
                    raise ValueError('official Rust component payloads overlap with different bytes')
            else:
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(path, destination)
                destination.chmod(0o755 if path.stat().st_mode & 0o111 else 0o644)
    notices = output / 'notices' / item['name']
    notices.mkdir(parents=True)
    result = []
    for path in sorted(supplier.iterdir()):
        if path.is_file() and (path.name.startswith(('LICENSE', 'COPYRIGHT')) or path.name == 'README.md'):
            shutil.copyfile(path, notices / path.name)
            result.append((notices / path.name).relative_to(output).as_posix())
    return result


def prepare(recipe, inputs, output, cpp_sdk=None):
    data = fetch(recipe, inputs, network=False)
    identity = recipe_identity(recipe)
    output = Path(output).absolute()
    if output.exists() or output.is_symlink():
        raise ValueError('Rust prepared group output must be new')
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=output.parent, prefix='.rust-prepare-') as temporary:
        work = Path(temporary)
        tree, sources = work / 'sdk', work / 'sources'
        tree.mkdir()
        sources.mkdir()
        (sources / 'inputs').mkdir()
        licenses = []
        for item in data['inputs']:
            archive = Path(inputs) / item['file']
            shutil.copyfile(archive, sources / 'inputs' / item['file'])
            if item['name'] in ('rustc', 'cargo', 'host-std', 'target-std', 'rust-src'):
                licenses.extend(install_component(archive, tree, work, item, data))
        (sources / 'recipe').mkdir()
        shutil.copyfile(recipe, sources / 'recipe/rust.json')
        (sources / 'tools').mkdir()
        for name in TOOLS:
            shutil.copyfile(Path(__file__).parent / name, sources / 'tools' / name)
        source_archive = next(i for i in data['inputs'] if i['name'] == 'compiler-source')
        with tarfile.open(Path(inputs) / source_archive['file']) as archive:
            entries = [m for m in archive.getmembers() if m.name.endswith('/src/stage0.json')]
            if len(entries) != 1 or not entries[0].isfile() or entries[0].size > 1024 * 1024:
                raise ValueError('compiler source lacks bounded stage0 bootstrap metadata')
            (sources / 'bootstrap').mkdir()
            with archive.extractfile(entries[0]) as source:
                (sources / 'bootstrap/stage0.json').write_bytes(source.read())
        verify_stage0(data, read_json(sources / 'bootstrap/stage0.json'))
        write_json(sources / 'sources.json', {
            'schema_version': 1, 'recipe_id': identity, 'recovery_scope': RECOVERY_SCOPE,
            'files': file_inventory(sources), 'bootstrap_reconstructed': False,
            'compiler_source_sha256': source_archive['sha256'],
            'supplier_inputs': data['inputs'],
        })
        system, processor = TARGETS[data['target']]
        target = {'system': system, 'processor': processor, 'triple': data['target'],
                  'library_directory': 'lib/rustlib/' + data['target'] + '/lib'}
        if system == 'Emscripten':
            if cpp_sdk is None:
                raise ValueError('Emscripten Rust preparation requires the paired retained C++ SDK')
            verify_sdk(cpp_sdk)
            cpp_data = read_json(Path(cpp_sdk) / 'sdk.json')
            target['cpp_sdk_recipe_id'] = cpp_data['recipe_id']
            target['emscripten_version'] = data['emscripten_version']
            target['emscripten_version_file'] = data['emscripten_version_file']
            if target['cpp_sdk_recipe_id'] != data['cpp_sdk_recipe_id']:
                raise ValueError('paired Emscripten SDK recipe differs from pinned Rust recipe')
        extension = {'schema_version': 1, 'kind': 'rust-extension', 'recipe_id': identity,
                     'sources_sha256': digest(sources / 'sources.json'),
                     'host': dict(zip(('system', 'processor'), TARGETS[data['host']])),
                     'compiler': {'version': data['version'], 'cargo_version': data['cargo_version'],
                                  'host': data['host'], 'rustc': 'bin/rustc' + ('.exe' if data['host'].endswith('msvc') else ''),
                                  'cargo': 'bin/cargo' + ('.exe' if data['host'].endswith('msvc') else ''), 'sysroot': '.'},
                     'target': target, 'licenses': sorted(licenses), 'files': file_inventory(tree),
                     'recovery_scope': RECOVERY_SCOPE, 'compiler_reconstructed': False,
                     'supplier': 'official-rust-distribution', 'release_manifest_sha256': next(
                         i['sha256'] for i in data['inputs'] if i['name'] == 'release-manifest')}
        if extension['host']['system'] == 'Linux':
            extension['host_requirements'] = {'distribution': 'debian-12', 'glibc': '2.36',
                                             'os_runtime': ['glibc', 'libgcc-s1']}
            if platform.system() == 'Linux':
                extension['host_audit'] = audit(tree, extension['host']['processor'], host=True)
        else:
            extension['host_requirements'] = {'system': 'Windows', 'os_runtime': ['Windows system DLLs'],
                                             'final_link': 'Microsoft MSVC v143 and Windows SDK'}
        write_json(tree / 'rust-sdk.json', extension)
        verify_rust_sdk(tree, cpp_sdk)
        native_host = (platform.system(), normalized_processor(platform.machine())) == (
            extension['host']['system'], extension['host']['processor'])
        if native_host:
            verify_rust_sdk(tree, cpp_sdk, execute=True)
        return export_group(tree, sources, output)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='action', required=True)
    for action in ('recipe-id', 'fetch', 'prepare'):
        command = commands.add_parser(action)
        command.add_argument('--recipe', type=Path, default=Path(__file__).resolve().parents[1] / 'third_party/rust/linux-x86_64.json')
        if action != 'recipe-id':
            command.add_argument('--inputs', type=Path, required=True)
        if action == 'prepare':
            command.add_argument('--output', type=Path, required=True)
            command.add_argument('--cpp-sdk', '--cpp-sdk-root', type=Path)
    for action in ('install', 'restore', 'restore-sources', 'verify-group'):
        command = commands.add_parser(action)
        command.add_argument('--group', type=Path, required=True)
        command.add_argument('--recipe', required=True)
        if action != 'verify-group':
            command.add_argument('--output', type=Path, required=True)
        if action in ('install', 'restore'):
            command.add_argument('--cpp-sdk', '--cpp-sdk-root', type=Path)
            command.add_argument('--target')
            command.add_argument('--execute', action='store_true')
    check = commands.add_parser('verify')
    check.add_argument('positional_root', type=Path, nargs='?')
    check.add_argument('--root', type=Path)
    check.add_argument('--cpp-sdk', '--cpp-sdk-root', type=Path)
    check.add_argument('--target')
    check.add_argument('--execute', action='store_true')
    pack = commands.add_parser('export')
    pack.add_argument('--tree', type=Path, required=True)
    pack.add_argument('--sources', type=Path, required=True)
    pack.add_argument('--output', type=Path, required=True)
    pack.add_argument('--epoch', type=int, default=0)
    args = parser.parse_args()
    if args.action == 'recipe-id':
        checked_recipe(args.recipe)
        result = {'recipe_id': recipe_identity(args.recipe)}
    elif args.action == 'fetch':
        result = fetch(args.recipe, args.inputs, network=True)
    elif args.action == 'prepare':
        result = prepare(args.recipe, args.inputs, args.output, args.cpp_sdk)
    elif args.action in ('install', 'restore'):
        result = restore(args.group, args.recipe, args.output, args.cpp_sdk, args.target, args.execute)
    elif args.action == 'restore-sources':
        result = restore_sources(args.group, args.recipe, args.output)
    elif args.action == 'verify-group':
        result = {'recipe_id': args.recipe, 'files': verify_group(args.group, args.recipe)}
    elif args.action == 'export':
        result = export_group(args.tree, args.sources, args.output, args.epoch)
    else:
        root = args.root or args.positional_root
        if root is None or (args.root is not None and args.positional_root is not None):
            parser.error('verify requires exactly one --root or positional root')
        data = verify_rust_sdk(root, args.cpp_sdk, args.target, args.execute)
        result = {'sha256': digest(root / 'rust-sdk.json'), 'metadata': data,
                  'rustc': str((root / data['compiler']['rustc']).resolve()),
                  'cargo': str((root / data['compiler']['cargo']).resolve()), 'target': data['target']['triple']}
    print(encoded(result).decode(), end='')


if __name__ == '__main__':
    try:
        main()
    except (ValueError, OSError, KeyError, TypeError, subprocess.CalledProcessError) as error:
        raise SystemExit(str(error))
