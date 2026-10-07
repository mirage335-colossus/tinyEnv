#!/usr/bin/env python3
"""Immutable local base storage for complete dependency binary/source groups."""
import argparse
from pathlib import Path
import re
import shutil
import tempfile
from dependency_archive import digest, encoded, extract, inspect_manifest_archive, read_json, relative


def names(recipe):
    if not re.fullmatch(r'[0-9a-f]{64}', recipe):
        raise ValueError('recipe identity must be a complete SHA-256')
    stem = 'sdk-' + recipe
    return (stem + '-binary.tar.gz', stem + '-sources.tar.gz', stem + '-SHA256SUMS')


def verify_group(directory, recipe):
    directory = Path(directory)
    binary, source, checksum = names(recipe)
    if directory.is_symlink() or not directory.is_dir():
        raise ValueError('missing ordinary dependency group directory')
    expected = set((binary, source, checksum))
    if {p.name for p in directory.iterdir()} != expected:
        raise ValueError('dependency group must contain exactly binary, source and checksum files')
    for name in expected:
        path = directory / name
        if path.is_symlink() or not path.is_file():
            raise ValueError('dependency group must contain ordinary files')
    values = {}
    for line in (directory / checksum).read_text().splitlines():
        fields = line.split('  ')
        if len(fields) != 2 or fields[1] in values or not re.fullmatch(r'[0-9a-f]{64}', fields[0]):
            raise ValueError('invalid or duplicate dependency checksum entry')
        relative(fields[1])
        values[fields[1]] = fields[0]
    if set(values) != {binary, source}:
        raise ValueError('dependency checksum must cover exactly the matched pair')
    for name, expected_hash in values.items():
        if digest(directory / name) != expected_hash:
            raise ValueError('dependency archive checksum mismatch')
    binary_info, _ = inspect_manifest_archive(directory / binary, 'sdk.json', sdk_archive=True)
    source_info, source_hash = inspect_manifest_archive(directory / source, 'sources.json')
    if binary_info.get('recipe_id') != recipe or source_info.get('recipe_id') != recipe:
        raise ValueError('retained archive recipe identity mismatch')
    if binary_info.get('sources_sha256') != source_hash:
        raise ValueError('binary archive names a different complete source inventory')
    return {name: digest(directory / name) for name in sorted(expected)}


def verify_binary_group(directory, recipe, expected_files=None):
    """Verify a compiler input without replaying its retained supplier sources.

    Release qualification supplies the complete map from its frozen manifest.
    The default is useful for a local installed SDK consumer; it still verifies
    the complete pair checksum and the binary's recipe/source-manifest binding.
    """
    directory = Path(directory); binary, source, checksum = names(recipe)
    if directory.is_symlink() or not directory.is_dir() or {p.name for p in directory.iterdir()} != {binary, checksum}:
        raise ValueError('binary dependency group must contain exactly binary and checksum files')
    for name in (binary, checksum):
        if (directory / name).is_symlink() or not (directory / name).is_file():
            raise ValueError('dependency group must contain ordinary files')
    values = {}
    for line in (directory / checksum).read_text().splitlines():
        fields = line.split('  ')
        if len(fields) != 2 or fields[1] in values or not re.fullmatch(r'[0-9a-f]{64}', fields[0]):
            raise ValueError('invalid or duplicate dependency checksum entry')
        relative(fields[1]); values[fields[1]] = fields[0]
    if set(values) != {binary, source} or digest(directory / binary) != values[binary]:
        raise ValueError('binary dependency checksum differs from complete pair')
    if expected_files is not None:
        if (not isinstance(expected_files, dict) or set(expected_files) != {binary, source, checksum} or
                any(not isinstance(v, str) or not re.fullmatch(r'[0-9a-f]{64}', v) for v in expected_files.values()) or
                expected_files[binary] != values[binary] or expected_files[source] != values[source] or
                expected_files[checksum] != digest(directory / checksum)):
            raise ValueError('binary dependency group differs from frozen complete inventory')
    metadata, _ = inspect_manifest_archive(directory / binary, 'sdk.json', sdk_archive=True)
    if metadata.get('recipe_id') != recipe or not re.fullmatch(r'[0-9a-f]{64}', metadata.get('sources_sha256', '')):
        raise ValueError('binary archive lacks exact recipe and source manifest identity')
    return {binary: values[binary], source: values[source], checksum: digest(directory / checksum)}


def create_sums(directory, recipe):
    binary, source, checksum = names(recipe)
    path = Path(directory) / checksum
    with path.open('x') as output:
        output.write(''.join(digest(Path(directory) / name) + '  ' + name + '\n' for name in (binary, source)))
    return verify_group(directory, recipe)


def copy_group(source, destination, recipe):
    source, destination = Path(source), Path(destination).absolute()
    files = verify_group(source, recipe)
    if destination.exists() or destination.is_symlink():
        raise ValueError('refusing to overwrite retained dependency destination')
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=destination.parent, prefix='.group-') as temporary:
        staged = Path(temporary) / 'group'
        staged.mkdir()
        for name in files:
            shutil.copyfile(source / name, staged / name)
        if verify_group(staged, recipe) != files:
            raise ValueError('dependency group changed while copying')
        staged.rename(destination)
    return files


def put(base, group, recipe):
    base = Path(base)
    expected = verify_group(group, recipe)
    destination = base / recipe
    if destination.exists():
        if verify_group(destination, recipe) != expected:
            raise ValueError('immutable recipe already exists with different bytes')
        return {'recipe_id': recipe, 'reused': True, 'files': expected}
    copy_group(group, destination, recipe)
    return {'recipe_id': recipe, 'reused': False, 'files': expected}


def fetch(base, recipe, output):
    # A missing recipe is a maintenance error, never an implicit build/download.
    return copy_group(Path(base) / recipe, output, recipe)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('put', 'fetch', 'verify'))
    parser.add_argument('--recipe', required=True)
    parser.add_argument('--base', type=Path)
    parser.add_argument('--group', type=Path)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    if args.action == 'put':
        if not args.base or not args.group: parser.error('put requires --base and --group')
        result = put(args.base, args.group, args.recipe)
    elif args.action == 'fetch':
        if not args.base or not args.output: parser.error('fetch requires --base and --output')
        result = fetch(args.base, args.recipe, args.output)
    else:
        if not args.group: parser.error('verify requires --group')
        result = verify_group(args.group, args.recipe)
    print(encoded(result).decode(), end='')


if __name__ == '__main__':
    try:
        main()
    except (ValueError, OSError) as error:
        raise SystemExit(str(error))
