#!/usr/bin/env python3
"""Assemble and recover complete local releases. Never publishes remotely."""
import argparse
from pathlib import Path
import re
import shutil
import tempfile
import artifact
from dependency_archive import digest, encoded, file_inventory, read_json, relative, verify_inventory, write_json
from dependency_store import copy_group, verify_group
from source_identity import verify_source_archive

RUST_IDENTITY_FIELDS = ('rust_sdk_recipe_id', 'rust_compiler_version', 'rust_target',
                        'rust_sdk_manifest_sha256', 'rust_compiler_sha256')


def provider_identity(entry):
    # An omitted field belongs to a historical C++ artifact, not a new build request.
    provider = entry.get('core_provider', 'cpp')
    if provider not in ('cpp', 'rust'):
        raise ValueError('unknown core provider')
    result = {'core_provider': provider}
    if provider == 'rust':
        for field in RUST_IDENTITY_FIELDS:
            value = entry.get(field)
            if not isinstance(value, str) or not value.strip() or value == 'none':
                raise ValueError('Rust artifact needs its complete compiler and SDK identity')
            if (field.endswith('sha256') or field == 'rust_sdk_recipe_id') and not re.fullmatch(r'[0-9a-f]{64}', value):
                raise ValueError('invalid Rust compiler or SDK identity')
            result[field] = value
    elif any(entry.get(field) not in (None, 'none') for field in RUST_IDENTITY_FIELDS):
        raise ValueError('C++ artifact cannot declare a Rust compiler or SDK')
    return result


def dependency_kinds(artifacts):
    kinds = {}
    for entry in artifacts:
        identity = provider_identity(entry)
        for recipe in dependency_recipes(entry):
            kind = 'rust' if recipe == identity.get('rust_sdk_recipe_id') else 'sdk'
            if recipe in kinds and kinds[recipe] != kind:
                raise ValueError('dependency recipe has conflicting SDK kinds')
            kinds[recipe] = kind
    return kinds


def dependency_names(recipe, kind='sdk'):
    if kind == 'sdk':
        from dependency_store import names
        return names(recipe)
    if kind == 'rust':
        from rust_sdk import group_names
        return group_names(recipe)
    raise ValueError('unknown dependency group kind')


def verify_dependency_group(directory, recipe, kind='sdk', expected_files=None, *, binary=False):
    if kind == 'rust':
        from rust_sdk import verify_group as verify_rust_group
        actual = verify_rust_group(directory, recipe)
    elif kind == 'sdk':
        if binary:
            from dependency_store import verify_binary_group
            return verify_binary_group(directory, recipe, expected_files)
        actual = verify_group(directory, recipe)
    else:
        raise ValueError('unknown dependency group kind')
    if expected_files is not None and actual != expected_files:
        raise ValueError('release dependency identity mismatch')
    return actual


def copy_dependency_group(source, destination, recipe, kind='sdk'):
    if kind == 'sdk':
        return copy_group(source, destination, recipe)
    files = verify_dependency_group(source, recipe, kind)
    source, destination = Path(source), Path(destination).absolute()
    if destination.exists() or destination.is_symlink():
        raise ValueError('refusing to overwrite retained dependency destination')
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=destination.parent, prefix='.group-') as temporary:
        staged = Path(temporary) / 'group'; staged.mkdir()
        for name in files:
            shutil.copyfile(source / name, staged / name)
        verify_dependency_group(staged, recipe, kind, files)
        staged.rename(destination)
    return files


def safe_name(name):
    if len(relative(name).parts) != 1:
        raise ValueError('release asset names must be simple filenames')
    return name


def dependency_recipes(entry):
    recipes = entry.get('dependency_recipes', [entry['sdk_recipe']])
    if not recipes or len(recipes) != len(set(recipes)) or entry['sdk_recipe'] not in recipes:
        raise ValueError('artifact dependency recipes must be complete, unique and include its primary SDK')
    if any(not re.fullmatch(r'[0-9a-f]{64}', value) for value in recipes):
        raise ValueError('invalid dependency recipe identity')
    identity = provider_identity(entry)
    if identity['core_provider'] == 'rust' and (identity['rust_sdk_recipe_id'] not in recipes
            or identity['rust_sdk_recipe_id'] == entry['sdk_recipe']):
        raise ValueError('Rust artifact must retain its distinct Rust SDK dependency group')
    return sorted(recipes)


def validate_package(archive, entry, source_identity, expected):
    # Read the small build record while validating every archive member. No full
    # temporary extraction is needed for this metadata-only package check.
    records = [name for name in expected["files"] if Path(name).name == "build-info.txt"]
    if len(records) != 1:
        raise ValueError('application archive requires one build information record')
    contents = {records[0]: None}
    if artifact.describe(archive, contents=contents) != expected:
        raise ValueError('release application archive inventory mismatch')
    info = {}
    for line in contents[records[0]].decode('utf-8').splitlines():
        if '=' in line:
            key, value = line.split('=', 1)
            if key in info: raise ValueError('duplicate packaged build information field')
            info[key] = value
    if info.get('sdk_recipe_id') != entry['sdk_recipe']:
        raise ValueError('packaged SDK recipe differs from release specification')
    if info.get('source_tree_sha256') != source_identity:
        raise ValueError('packaged source tree differs from retained source archive')
    if info.get('target') != entry['target']:
        raise ValueError('packaged target differs from release specification')
    identity = provider_identity(entry)
    if provider_identity(info) != identity:
        raise ValueError('packaged core provider or Rust toolchain differs from release specification')
    backends = [value for value in info.get('gui_backends', '').split(',') if value]
    if len(backends) != len(set(backends)) or sorted(backends) != sorted(entry.get('backends', [])):
        raise ValueError('packaged backends differ from release specification')
    declared = info.get('dependency_recipes', '').split(',')
    if sorted(declared) != dependency_recipes(entry):
        raise ValueError('packaged dependency list differs from release specification')


def package_files(metadata, referenced):
    """Declare package assets inside the ordinary immutable release inventory."""
    if 'packages' not in metadata:
        return set()
    packages = metadata['packages']
    if (not isinstance(packages, dict) or set(packages) != {'manifest', 'files'} or
            packages['manifest'] != 'packages.json' or not isinstance(packages['files'], list) or
            not packages['files'] or not all(isinstance(name, str) for name in packages['files'])):
        raise ValueError('complete package asset declaration required')
    names = packages['files']
    if (names != sorted(set(names)) or not {'packages.json', 'packages.json.sig', 'archive-keyring.gpg', 'INSTALL.md'} <= set(names) or
            set(names) & referenced or not set(names) <= set(metadata['files'])):
        raise ValueError('duplicate, missing or overlapping package assets')
    for name in names:
        if safe_name(name) != name or Path(name).name != name:
            raise ValueError('package repository assets must be flat release assets')
    return set(names)


def verify_metadata(directory):
    """Validate the complete frozen inventory without reading absent payloads.

    This is for evidence aggregation and authenticated remote reconciliation;
    producer publication and physical qualification still verify payload bytes.
    """
    directory = Path(directory).resolve(strict=True)
    data = read_json(directory / 'release.json')
    if data.get('schema_version') != 1 or data.get('qualification') != 'candidate':
        raise ValueError('unsupported local release manifest')
    files = data.get('files')
    if not isinstance(files, dict) or not files or any(not isinstance(v, str) or not re.fullmatch(r'[0-9a-f]{64}', v) for v in files.values()):
        raise ValueError('invalid complete release inventory')
    source = data['source']; safe_name(source['archive'])
    if files.get(source['archive']) != source['sha256'] or not re.fullmatch(r'[0-9a-f]{64}', source.get('tree_sha256', '')):
        raise ValueError('release source identity mismatch')
    referenced = {source['archive']}; wanted = set(); targets = set()
    if not data['artifacts']: raise ValueError('release needs application artifacts')
    for entry in data['artifacts']:
        if entry['target'] in targets: raise ValueError('duplicate release target')
        targets.add(entry['target'])
        for key, checksum in (('archive', 'sha256'), ('manifest', 'manifest_sha256')):
            safe_name(entry[key])
            if entry[key] in referenced or files.get(entry[key]) != entry[checksum]:
                raise ValueError('release application identity mismatch')
            referenced.add(entry[key])
        wanted.update(dependency_recipes(entry))
        backends = entry.get('backends', [])
        if not isinstance(backends, list) or len(backends) != len(set(backends)):
            raise ValueError('duplicate release backend')
    observed = set()
    kinds = dependency_kinds(data['artifacts'])
    for entry in data['dependencies']:
        recipe = entry['recipe_id']
        kind = entry.get('kind', 'sdk')
        if (kind != kinds.get(recipe) or recipe in observed
                or set(entry['files']) != set(dependency_names(recipe, kind))):
            raise ValueError('duplicate or incomplete dependency group')
        observed.add(recipe)
        for name, value in entry['files'].items():
            path = 'dependencies/' + recipe + '/' + name
            if files.get(path) != value: raise ValueError('release dependency identity mismatch')
            referenced.add(path)
    referenced.update(package_files(data, referenced))
    if not wanted or wanted != observed or set(files) != referenced:
        raise ValueError('unexpected or omitted release asset')
    scopes = data['required_scopes']
    if not scopes or len(scopes) != len(set(scopes)):
        raise ValueError('release scopes must be nonempty and unique')
    return data


def required_files(metadata, target, backend, scope, *, binary_source=True):
    """Derive physical-check inputs from the complete target/backend inventory."""
    if scope not in ('source', 'recovery', 'archive', 'abi', 'apt'):
        raise ValueError('unsupported qualification operation')
    choices = [item for item in metadata['artifacts'] if item['target'] == target and backend in (item['backends'] or ['core'])]
    if len(choices) != 1: raise ValueError('unknown or ambiguous target/backend')
    entry = choices[0]; selected = {entry['archive'], entry['manifest']}
    if scope in ('source', 'recovery') or scope == 'archive' and backend in ('wasm', 'hosted-web'):
        selected.add(metadata['source']['archive'])
    if scope in ('source', 'recovery'):
        recipes = dependency_recipes(entry)
        for group in metadata['dependencies']:
            if group['recipe_id'] in recipes:
                selected.update('dependencies/' + group['recipe_id'] + '/' + name for name in group['files']
                    if scope == 'recovery' or group.get('kind') == 'rust' or not binary_source or not name.endswith('-sources.tar.gz'))
    return sorted(selected)


def verify_selection(directory, target, backend, scope):
    """Verify every selected byte; reject additional or missing scope payloads."""
    directory = Path(directory).resolve(strict=True); data = verify_metadata(directory)
    names = required_files(data, target, backend, scope)
    actual = file_inventory(directory, exclude=('release.json',))
    if not set(names) <= set(actual) or not set(actual) <= set(data['files']):
        raise ValueError('missing or unexpected physical qualification input')
    if actual != {name: data['files'][name] for name in actual}:
        raise ValueError('retained file inventory or checksum mismatch')
    entry = next(item for item in data['artifacts'] if item['target'] == target)
    if data['source']['archive'] in names:
        source = verify_source_archive(directory / data['source']['archive'])
        if source['tree_sha256'] != data['source']['tree_sha256']:
            raise ValueError('release source tree binding mismatch')
    validate_package(directory / entry['archive'], entry, data['source']['tree_sha256'],
                     read_json(directory / entry['manifest']))
    if scope in ('source', 'recovery'):
        for group in data['dependencies']:
            if group['recipe_id'] in dependency_recipes(entry):
                binary = scope == 'source' and not any((directory / 'dependencies' / group['recipe_id'] / name).exists() for name in group['files'] if name.endswith('-sources.tar.gz'))
                verify_dependency_group(directory / 'dependencies' / group['recipe_id'], group['recipe_id'],
                                        group.get('kind', 'sdk'), group['files'], binary=binary)
    return data


def verify_release(directory):
    directory = Path(directory).resolve(strict=True)
    metadata = verify_metadata(directory)
    if metadata.get('schema_version') != 1 or metadata.get('qualification') != 'candidate':
        raise ValueError('unsupported local release manifest')
    verify_inventory(directory, metadata['files'], exclude=('release.json',))
    source = metadata['source']
    safe_name(source['archive'])
    if digest(directory / source['archive']) != source['sha256']:
        raise ValueError('release source identity mismatch')
    source_manifest = verify_source_archive(directory / source['archive'])
    if source.get('tree_sha256') != source_manifest['tree_sha256']:
        raise ValueError('release source tree binding mismatch')
    wanted = set()
    for entry in metadata['artifacts']:
        for name in ('archive', 'manifest'):
            safe_name(entry[name])
        if digest(directory / entry['archive']) != entry['sha256'] or digest(directory / entry['manifest']) != entry['manifest_sha256']:
            raise ValueError('release application identity mismatch')
        validate_package(directory / entry['archive'], entry, source_manifest['tree_sha256'],
                         read_json(directory / entry['manifest']))
        wanted.update(dependency_recipes(entry))
    observed = set()
    for entry in metadata['dependencies']:
        recipe = entry['recipe_id']
        if recipe in observed: raise ValueError('duplicate dependency recipe')
        observed.add(recipe)
        verify_dependency_group(directory / 'dependencies' / recipe, recipe, entry.get('kind', 'sdk'), entry['files'])
    if not wanted or wanted != observed:
        raise ValueError('release must retain exactly every required SDK group')
    if not metadata['required_scopes'] or len(metadata['required_scopes']) != len(set(metadata['required_scopes'])):
        raise ValueError('release scopes must be nonempty and unique')
    referenced = {source['archive']}
    for entry in metadata['artifacts']:
        referenced.update((entry['archive'], entry['manifest']))
    for entry in metadata['dependencies']:
        referenced.update('dependencies/' + entry['recipe_id'] + '/' + name for name in entry['files'])
    referenced.update(package_files(metadata, referenced))
    if set(metadata['files']) != referenced:
        raise ValueError('unexpected or omitted release asset')
    if 'packages' in metadata:
        import release_packages
        release_packages.binding(directory, metadata)
    return metadata


def assemble(spec_path, base, output):
    spec_path, output = Path(spec_path).resolve(), Path(output).absolute()
    spec = read_json(spec_path)
    if spec.get('schema_version') != 1 or not spec.get('artifacts'):
        raise ValueError('release spec must list application archives')
    if output.exists() or output.is_symlink():
        raise ValueError('release output must be new')
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=output.parent, prefix='.release-') as temporary:
        staged = Path(temporary) / 'release'
        staged.mkdir()
        seen = {'release.json', 'dependencies'}
        def retain(name):
            path = Path(name)
            if not path.is_absolute(): path = spec_path.parent / path
            path = path.resolve(strict=True)
            filename = safe_name(path.name)
            if filename in seen: raise ValueError('duplicate release asset filename')
            seen.add(filename)
            shutil.copyfile(path, staged / filename)
            if digest(path) != digest(staged / filename): raise ValueError('input changed during release assembly')
            return filename
        source = retain(spec['source']['path'])
        source_hash = digest(staged / source)
        if source_hash != spec['source']['sha256']:
            raise ValueError('source archive differs from frozen specification')
        source_manifest = verify_source_archive(staged / source)
        metadata = {'schema_version': 1, 'qualification': 'candidate',
                    'source': {'archive': source, 'sha256': source_hash, 'tree_sha256': source_manifest['tree_sha256']}, 'artifacts': [],
                    'dependencies': [], 'required_scopes': spec['required_scopes']}
        recipes = set()
        kinds = dependency_kinds(spec['artifacts'])
        for entry in spec['artifacts']:
            archive = retain(entry['path'])
            manifest = retain(entry['manifest_path'])
            if digest(staged / archive) != entry['sha256']:
                raise ValueError('application archive differs from frozen specification')
            recipe = entry['sdk_recipe']
            validate_package(staged / archive, entry, source_manifest['tree_sha256'], read_json(staged / manifest))
            recipes.update(dependency_recipes(entry))
            frozen = {'archive': archive, 'sha256': digest(staged / archive),
                'manifest': manifest, 'manifest_sha256': digest(staged / manifest),
                'target': entry['target'], 'backends': entry.get('backends', []), 'sdk_recipe': recipe,
                'dependency_recipes': dependency_recipes(entry)}
            if entry.get('core_provider') is not None:
                frozen.update(provider_identity(entry))
            metadata['artifacts'].append(frozen)
        for recipe in sorted(recipes):
            files = copy_dependency_group(Path(base) / recipe, staged / 'dependencies' / recipe, recipe, kinds[recipe])
            group = {'recipe_id': recipe, 'files': files}
            if kinds[recipe] == 'rust': group['kind'] = 'rust'
            metadata['dependencies'].append(group)
        metadata['files'] = file_inventory(staged)
        write_json(staged / 'release.json', metadata)
        verify_release(staged)
        staged.rename(output)
    return metadata


def verify_recovery(directory, expected_release_sha256=None):
    """Verify a standalone recovery kit without the original release or base.

    A caller-supplied release digest is the trust anchor. Without it, this checks
    local integrity and completeness, not publisher identity or qualification.
    """
    directory = Path(directory).absolute()
    if directory.is_symlink() or not directory.is_dir():
        raise ValueError('recovery kit must be an ordinary directory')
    directory = directory.resolve(strict=True)
    receipt_path = directory / 'recovery.json'
    if receipt_path.is_symlink() or not receipt_path.is_file():
        raise ValueError('recovery kit needs an ordinary recovery.json')
    receipt_hash = digest(receipt_path)
    receipt = read_json(receipt_path)
    if not isinstance(receipt, dict) or 'schema_version' not in receipt:
        raise ValueError('legacy recovery kit lacks retained release metadata; re-export from the verified release')
    if (type(receipt['schema_version']) is not int or receipt['schema_version'] != 1 or
            set(receipt) != {'schema_version', 'release_sha256', 'source', 'dependencies'}):
        raise ValueError('unsupported recovery manifest')
    release_hash = receipt['release_sha256']
    if not isinstance(release_hash, str) or not re.fullmatch(r'[0-9a-f]{64}', release_hash):
        raise ValueError('invalid recovery release identity')
    if expected_release_sha256 is not None:
        if (not isinstance(expected_release_sha256, str) or
                not re.fullmatch(r'[0-9a-f]{64}', expected_release_sha256)):
            raise ValueError('expected release identity must be a complete SHA-256')
        if release_hash != expected_release_sha256:
            raise ValueError('recovery release differs from trusted release identity')
    manifest_path = directory / 'release.json'
    if manifest_path.is_symlink() or not manifest_path.is_file() or digest(manifest_path) != release_hash:
        raise ValueError('retained release metadata is missing or changed')
    data = verify_metadata(directory)
    if receipt['source'] != data['source'] or receipt['dependencies'] != data['dependencies']:
        raise ValueError('recovery declarations differ from retained release metadata')
    source = data['source']
    if source['archive'] in ('release.json', 'recovery.json', 'dependencies'):
        raise ValueError('source archive collides with recovery metadata')
    expected = {'release.json': release_hash, 'recovery.json': receipt_hash,
                source['archive']: source['sha256']}
    for entry in data['dependencies']:
        recipe = entry['recipe_id']
        expected.update(('dependencies/' + recipe + '/' + name, value)
                        for name, value in entry['files'].items())
    # Check ordinary entries and frozen hashes before parsing any payload. Inner
    # inventories then bind the source tree and each compiled SDK to its sources.
    verify_inventory(directory, expected)
    if verify_source_archive(directory / source['archive'])['tree_sha256'] != source['tree_sha256']:
        raise ValueError('recovery source tree binding mismatch')
    for entry in data['dependencies']:
        verify_dependency_group(directory / 'dependencies' / entry['recipe_id'], entry['recipe_id'],
                                entry.get('kind', 'sdk'), entry['files'])
    expected_directories = {str(parent) for name in expected for parent in relative(name).parents if str(parent) != '.'}
    if {path.relative_to(directory).as_posix() for path in directory.rglob('*') if path.is_dir()} != expected_directories:
        raise ValueError('unexpected recovery directory')
    # Recheck after archive inspection: concurrent mutation cannot leave a success
    # receipt describing bytes that failed the frozen inventory at completion.
    verify_inventory(directory, expected)
    return {'schema_version': 1, 'status': 'passed', 'scope': 'retained-recovery-inputs',
            'release_sha256': release_hash, 'release_pin_verified': expected_release_sha256 is not None,
            'source': source, 'dependencies': data['dependencies'], 'artifacts': data['artifacts']}


def recover(directory, output):
    directory, output = Path(directory).resolve(strict=True), Path(output).absolute()
    if output == directory or directory in output.resolve().parents:
        raise ValueError('recovery output must be outside the release tree')
    if output.exists() or output.is_symlink(): raise ValueError('recovery output must be new')
    release_hash = digest(directory / 'release.json')
    data = verify_release(directory)
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=output.parent, prefix='.recover-') as temporary:
        staged = Path(temporary) / 'recovered'
        staged.mkdir()
        shutil.copyfile(directory / data['source']['archive'], staged / data['source']['archive'])
        for entry in data['dependencies']:
            recipe = entry['recipe_id']
            copy_dependency_group(directory / 'dependencies' / recipe, staged / 'dependencies' / recipe,
                                  recipe, entry.get('kind', 'sdk'))
        shutil.copyfile(directory / 'release.json', staged / 'release.json')
        write_json(staged / 'recovery.json', {'schema_version': 1, 'release_sha256': release_hash,
                   'source': data['source'], 'dependencies': data['dependencies']})
        verify_recovery(staged, release_hash)
        staged.rename(output)
    return data


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='action', required=True)
    create = sub.add_parser('assemble')
    create.add_argument('--spec', type=Path, required=True)
    create.add_argument('--base', type=Path, required=True)
    create.add_argument('--output', type=Path, required=True)
    for action in ('verify', 'recover', 'verify-recovery'):
        command = sub.add_parser(action)
        command.add_argument('directory', type=Path)
        if action == 'recover': command.add_argument('--output', type=Path, required=True)
        if action == 'verify-recovery':
            command.add_argument('--expected-release-sha256', help='independently trusted SHA-256 of the original release.json')
    args = parser.parse_args()
    if args.action == 'assemble': result = assemble(args.spec, args.base, args.output)
    elif args.action == 'verify': result = verify_release(args.directory)
    elif args.action == 'verify-recovery': result = verify_recovery(args.directory, args.expected_release_sha256)
    else: result = recover(args.directory, args.output)
    print(encoded(result).decode(), end='')


if __name__ == '__main__':
    try: main()
    except (ValueError, OSError, KeyError) as error: raise SystemExit(str(error))
