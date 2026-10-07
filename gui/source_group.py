#!/usr/bin/env python3
"""Retain and restore exact local GUI inputs; no downloads or toolkit execution."""
import argparse
import hashlib
import gzip
import importlib.util
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import subprocess
import tarfile
import tempfile

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location('dependency_archive', ROOT / 'tools/dependency_archive.py')
archive = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(archive)
MAX_FILES = 20000
MAX_FILE = 512 * 1024**2
MAX_TOTAL = 2 * 1024**3
MAX_JSON = 16 * 1024**2
GROUP_FILES = {'gui-inputs.tar.gz', 'manifest.json', 'SHA256SUMS'}
WINDOWS = os.name == 'nt'


class BoundedInfo(tarfile.TarInfo):
    def _proc_member(self, stream):
        if self.size < 0 or self.size > MAX_FILE or (not self.isfile() and self.size > MAX_JSON):
            raise ValueError('archive header exceeds size limit')
        return super()._proc_member(stream)


def portable(name):
    path = archive.relative(name)
    for part in path.parts:
        if any(c in part for c in '*?<>|"') or part.split('.')[0].upper() in {
            'CON', 'PRN', 'AUX', 'NUL', *(f'COM{i}' for i in range(1, 10)), *(f'LPT{i}' for i in range(1, 10))
        }:
            raise ValueError('nonportable retained path')
    return path


def ordinary(path):
    path = Path(path).absolute()
    for item in (path, *path.parents):
        if item.is_symlink():
            raise ValueError('linked input or output path')
    return path


def file_version(path):
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
        raise ValueError('input must be an ordinary singly linked file')
    if info.st_size > MAX_FILE:
        raise ValueError('retained file exceeds size limit')
    return (info.st_dev, info.st_ino, info.st_mode, info.st_nlink, info.st_size,
            info.st_mtime_ns, info.st_ctime_ns)


def observed_metadata(path, logical_mode=None):
    before = file_version(path)
    digest = archive.digest(path)
    if file_version(path) != before:
        raise ValueError('retained file changed while hashing')
    mode = logical_mode if WINDOWS and logical_mode is not None else (0o755 if before[2] & 0o111 else 0o644)
    return {'sha256': digest, 'size': before[4], 'mode': mode}, before


def metadata(path, logical_mode=None):
    return observed_metadata(path, logical_mode)[0]


def stream_identity(stream, size):
    """Hash one bounded member without retaining its payload or a second copy."""
    sha256 = hashlib.sha256()
    blob = hashlib.sha1(b'blob ' + str(size).encode() + b'\0')
    remaining = size
    while remaining:
        block = stream.read(min(1024 * 1024, remaining))
        if not block: raise ValueError('archive content differs from inventory')
        remaining -= len(block); sha256.update(block); blob.update(block)
    if stream.read(1): raise ValueError('archive content exceeds declared size')
    return sha256.hexdigest(), blob.digest()


def tree_identity(files):
    """Compatibility entry point for complete in-memory source byte inventories."""
    blobs = {}
    for name, (mode, data) in files.items():
        blob = hashlib.sha1(b'blob ' + str(len(data)).encode() + b'\0')
        blob.update(data); blobs[name] = (mode, blob.digest())
    return tree_from_blobs(blobs)


def tree_from_blobs(files):
    """Git tree identity from modes and already-hashed complete member bytes."""
    root = {}
    for name, (mode, blob) in files.items():
        parts = portable(name).parts
        node = root
        for part in parts[:-1]:
            node = node.setdefault(part, {})
            if not isinstance(node, dict):
                raise ValueError('file is also a directory')
        if parts[-1] in node:
            raise ValueError('duplicate source entry')
        node[parts[-1]] = (mode, blob)

    def encode(node):
        entries = []
        for name, item in sorted(node.items(), key=lambda pair: (pair[0] + ('/' if isinstance(pair[1], dict) else '')).encode()):
            if isinstance(item, dict):
                mode, digest = b'40000', encode(item)
            else:
                mode, digest = (b'100755' if item[0] == 0o755 else b'100644'), item[1]
            entries.append(mode + b' ' + name.encode() + b'\0' + digest)
        content = b''.join(entries)
        return hashlib.sha1(b'tree ' + str(len(content)).encode() + b'\0' + content).digest()
    return encode(root).hex()


def integration(root):
    lock_path = ordinary(root / 'third_party/gui-boundary.lock.json')
    lock = archive.read_json(lock_path)
    if not re.fullmatch('[0-9a-f]{40}', lock.get('source_tree', '')):
        raise ValueError('lock requires reviewed complete source tree identity')
    names = ['third_party/gui-boundary.lock.json', 'gui/patches/apply.py']
    for item in lock['patches']:
        name = item.split(': ', 1)[0]
        if not name.startswith('gui/patches/') or not name.endswith('.patch'):
            raise ValueError('invalid patch declaration')
        names.append(name)
    if len(set(names)) != len(names):
        raise ValueError('duplicate integration input')
    return lock, {name: ordinary(root / portable(name)) for name in names}


def distributable(lock):
    terms = lock.get('redistribution', {})
    licenses = terms.get('license_files', [])
    return terms.get('approved') is True and lock.get('license') != 'NOASSERTION' and bool(licenses) and all(name in lock['files'] for name in licenses)


def source_files(source, lock):
    source = ordinary(source)
    def git(*args):
        return subprocess.run(['git', '-C', str(source), *args], check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE).stdout
    if git('rev-parse', 'HEAD').decode().strip() != lock['revision'] or git('rev-parse', 'HEAD^{tree}').decode().strip() != lock['source_tree']:
        raise ValueError('source checkout is not the reviewed revision/tree')
    if git('status', '--porcelain', '--untracked-files=all').strip():
        raise ValueError('source checkout contains tracked or untracked changes')
    result = {}
    for record in git('ls-files', '-s', '-z').split(b'\0'):
        if not record:
            continue
        prefix, raw_name = record.split(b'\t', 1)
        mode, _, stage = prefix.split()
        if mode not in (b'100644', b'100755') or stage != b'0':
            raise ValueError('source contains unsupported link/submodule/conflict entry')
        name = raw_name.decode('utf-8')
        result[name] = (ordinary(source / portable(name)), 0o755 if mode == b'100755' else 0o644)
    return result


def validate_entries(entries):
    if not isinstance(entries, dict) or not 0 < len(entries) <= MAX_FILES:
        raise ValueError('invalid retained file count')
    folded, total = {}, 0
    for name, value in entries.items():
        parts = portable(name).parts
        for i in range(1, len(parts) + 1):
            spelling = '/'.join(parts[:i]); key = spelling.casefold()
            kind = 'file' if i == len(parts) else 'directory'
            if key in folded and folded[key] != (spelling, kind):
                raise ValueError('ambiguous file/directory spelling')
            folded[key] = (spelling, kind)
        if not isinstance(value, dict) or set(value) != {'sha256', 'size', 'mode'}:
            raise ValueError('invalid retained file metadata')
        if not isinstance(value['sha256'], str) or not re.fullmatch('[0-9a-f]{64}', value['sha256']):
            raise ValueError('invalid retained checksum')
        if type(value['size']) is not int or not 0 <= value['size'] <= MAX_FILE or type(value['mode']) is not int or value['mode'] not in (0o644, 0o755):
            raise ValueError('invalid retained size/mode')
        total += value['size']
    if total > MAX_TOTAL:
        raise ValueError('retained group exceeds total size limit')


def verify(group, redistribution=False, foundation_root=ROOT):
    group = ordinary(group)
    if not group.is_dir() or {p.name for p in group.iterdir()} != GROUP_FILES:
        raise ValueError('incomplete or unexpected group inputs')
    # Reuse only this complete observation. Physical versions are rechecked
    # after decoding; a later verify/restore operation always hashes afresh.
    observed = {name: observed_metadata(ordinary(group / name)) for name in GROUP_FILES}
    if (group / 'manifest.json').stat().st_size > MAX_JSON or (group / 'SHA256SUMS').stat().st_size > 1024:
        raise ValueError('oversize group metadata')
    manifest = archive.read_json(group / 'manifest.json')
    if set(manifest) != {'schema_version', 'kind', 'revision', 'source_tree', 'upstream', 'license', 'redistributable', 'archive_sha256', 'files'} or type(manifest['schema_version']) is not int or manifest['schema_version'] != 1 or manifest['kind'] != 'foundation-gui-inputs':
        raise ValueError('unsupported GUI input manifest')
    expected_sums = ''.join(f'{observed[name][0]["sha256"]}  {name}\n' for name in ['gui-inputs.tar.gz', 'manifest.json'])
    if (group / 'SHA256SUMS').read_text() != expected_sums or observed['gui-inputs.tar.gz'][0]['sha256'] != manifest['archive_sha256']:
        raise ValueError('group checksum mismatch')
    lock, inputs = integration(foundation_root)
    for key in ['revision', 'source_tree', 'upstream', 'license']:
        if manifest[key] != lock[key]:
            raise ValueError('group does not match current dependency lock')
    if manifest['redistributable'] is not distributable(lock):
        raise ValueError('group terms differ from reviewed lock')
    if redistribution and not distributable(lock):
        raise ValueError('GUI dependency redistribution terms are unresolved')
    expected = manifest['files']; validate_entries(expected)
    # Bound compressed expansion, including headers, before tarfile parses metadata.
    expanded = 0
    with gzip.open(group / 'gui-inputs.tar.gz', 'rb') as compressed:
        for block in iter(lambda: compressed.read(1024 * 1024), b''):
            expanded += len(block)
            if expanded > MAX_TOTAL + MAX_FILES * 4096:
                raise ValueError('archive expansion exceeds limit')
    upstream, upstream_hashes, seen, retained = {}, {}, set(), {}
    with tarfile.open(group / 'gui-inputs.tar.gz', 'r:gz', tarinfo=BoundedInfo) as stream:
        for member in stream:
            if len(seen) >= MAX_FILES or not member.isfile() or member.name in seen or member.name not in expected:
                raise ValueError('unexpected, duplicate or non-file archive entry')
            name = member.name; portable(name); seen.add(name)
            info = expected[name]
            if member.size != info['size'] or member.mode != info['mode'] or member.uid != 0 or member.gid != 0 or member.linkname:
                raise ValueError('archive metadata differs from inventory')
            with stream.extractfile(member) as data:
                digest, blob = stream_identity(data, info['size'])
            if digest != info['sha256']:
                raise ValueError('archive content differs from inventory')
            if name.startswith('upstream/'):
                relative = name[len('upstream/'):]
                upstream[relative] = (member.mode, blob)
                upstream_hashes[relative] = digest
            elif name.startswith('foundation/') and name[len('foundation/'):] in inputs:
                retained[name[len('foundation/'):]] = dict(sha256=digest, size=member.size, mode=member.mode)
            else:
                raise ValueError('unexpected retained namespace')
    if seen != set(expected) or set(retained) != set(inputs):
        raise ValueError('incomplete archive inventory')
    if tree_from_blobs(upstream) != lock['source_tree']:
        raise ValueError('complete source tree differs from reviewed commit')
    for name, path in inputs.items():
        if retained[name] != metadata(path, 0o644):
            raise ValueError('retained integration differs from current source: ' + name)
    for name, digest in lock['files'].items():
        if upstream_hashes.get(name) != digest:
            raise ValueError('consumed upstream input differs from lock')
    if {path.name for path in group.iterdir()} != GROUP_FILES or any(
            file_version(ordinary(group / name)) != version for name, (_, version) in observed.items()):
        raise ValueError('group inputs changed during verification')
    return manifest


def export(source, output, foundation_root=ROOT):
    output = ordinary(output)
    if output.exists():
        raise ValueError('export output must be new')
    lock, inputs = integration(foundation_root)
    sources = source_files(source, lock)
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=output.parent, prefix='.gui-export-') as temporary:
        stage = Path(temporary); tree = stage / 'tree'; tree.mkdir(); group = stage / 'group'; group.mkdir()
        entries = {}
        for base, files in [('upstream', sources), ('foundation', {name: (path, 0o644) for name, path in inputs.items()})]:
            for name, (path, mode) in files.items():
                info = metadata(path, mode)
                if info['mode'] != mode:
                    raise ValueError('physical mode differs from reviewed input')
                target = tree / base / name; target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(path, target); target.chmod(info['mode'])
                if metadata(target, mode) != info:
                    raise ValueError('source changed while retaining inputs')
                entries[base + '/' + name] = info
        validate_entries(entries)
        with (group / 'gui-inputs.tar.gz').open('xb') as raw, gzip.GzipFile(filename='', mode='wb', fileobj=raw, mtime=0, compresslevel=1) as zipped:
            with tarfile.open(fileobj=zipped, mode='w', format=tarfile.PAX_FORMAT) as bundle:
                for name, info in sorted(entries.items()):
                    item = tarfile.TarInfo(name); item.size = info['size']; item.mode = info['mode']; item.mtime = 0
                    with (tree / name).open('rb') as data:
                        bundle.addfile(item, data)
        digest = archive.digest(group / 'gui-inputs.tar.gz')
        manifest = {'schema_version': 1, 'kind': 'foundation-gui-inputs', **{key: lock[key] for key in ['revision', 'source_tree', 'upstream', 'license']}, 'redistributable': distributable(lock), 'archive_sha256': digest, 'files': entries}
        (group / 'manifest.json').write_bytes(archive.encoded(manifest))
        (group / 'SHA256SUMS').write_text(f'{digest}  gui-inputs.tar.gz\n' +
            f'{archive.digest(group / "manifest.json")}  manifest.json\n')
        verify(group, foundation_root=foundation_root)
        group.rename(output)
    return receipt(output, manifest)


def receipt(group, manifest, source=None):
    result = {'schema_version': 1, 'group_sha256': archive.digest(Path(group) / 'manifest.json'), 'revision': manifest['revision'], 'redistributable': manifest['redistributable']}
    if source is not None:
        result['source'] = str(source)
    return result


def restore(group, output, foundation_root=ROOT):
    manifest = verify(group, foundation_root=foundation_root)
    output = ordinary(output)
    if output.exists():
        actual, actual_dirs = {}, set()
        for path in output.rglob('*'):
            name = path.relative_to(output).as_posix()
            if path.is_dir() and not path.is_symlink():
                actual_dirs.add(name)
            else:
                actual[name] = metadata(ordinary(path), manifest['files'].get(name, {}).get('mode'))
        expected_dirs = {str(parent) for name in manifest['files'] for parent in PurePosixPath(name).parents if str(parent) != '.'}
        if actual != manifest['files'] or actual_dirs != expected_dirs:
            raise ValueError('existing restored output changed or contains foreign entries')
    else:
        output.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=output.parent, prefix='.gui-restore-') as temporary:
            staged = Path(temporary) / 'tree'
            archive.extract(Path(group) / 'gui-inputs.tar.gz', staged, max_bytes=MAX_TOTAL)
            actual = {p.relative_to(staged).as_posix(): metadata(ordinary(p), manifest['files'].get(p.relative_to(staged).as_posix(), {}).get('mode')) for p in staged.rglob('*') if not p.is_dir() or p.is_symlink()}
            if actual != manifest['files']:
                raise ValueError('input changed before restore activation')
            staged.rename(output)
    return receipt(group, manifest, output / 'upstream')


def main():
    parser = argparse.ArgumentParser(description=__doc__); commands = parser.add_subparsers(dest='command', required=True)
    create = commands.add_parser('export'); create.add_argument('--source', type=Path, required=True); create.add_argument('--output', type=Path, required=True)
    check = commands.add_parser('verify'); check.add_argument('group', type=Path); check.add_argument('--redistribution', action='store_true')
    recover = commands.add_parser('restore'); recover.add_argument('group', type=Path); recover.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    try:
        if args.command == 'export': result = export(args.source, args.output)
        elif args.command == 'verify': result = receipt(args.group, verify(args.group, args.redistribution))
        else: result = restore(args.group, args.output)
        print(json.dumps(result, sort_keys=True))
    except (ValueError, OSError, EOFError, KeyError, TypeError, subprocess.CalledProcessError, tarfile.TarError) as error:
        parser.exit(1, 'GUI input error: ' + str(error) + '\n')

if __name__ == '__main__':
    main()
