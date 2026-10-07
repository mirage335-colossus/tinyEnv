#!/usr/bin/env python3
"""Bind a build to a complete portable source snapshot, including retained inputs."""
import argparse
import gzip
import hashlib
import os
from pathlib import Path
import shutil
import subprocess
import tarfile
import tempfile
from dependency_archive import archive_tree, digest, encoded, file_inventory, inspect_manifest_archive, read_json, relative, write_json

WINDOWS = os.name == 'nt'

SUPPLEMENT_PREFIX = 'third_party/retained/gui/'


def ignored_source_path(name):
    parts = Path(name).parts
    return (name == 'source.json' or parts[0] in ('build', '.agent-work', '.git') or
            '__pycache__' in parts or name.endswith('.pyc'))


def source_files_without_git(root):
    """Prune generated trees before enumeration; never follow source links."""
    def failed(error):
        raise error

    for directory, directories, filenames in os.walk(root, topdown=True, onerror=failed, followlinks=False):
        parent = Path(directory).relative_to(root)
        # File-only exclusions do not exclude directories named source.json or
        # *.pyc: their descendants remain ordinary source inputs.
        directories[:] = [name for name in directories
                          if '__pycache__' not in (parent / name).parts and
                          (parent / name).parts[0] not in ('build', '.agent-work', '.git')]
        for name in [*directories, *filenames]:
            relative_name = (parent / name).as_posix()
            if ignored_source_path(relative_name):
                continue
            path = Path(directory) / name
            if path.is_file() or path.is_symlink():
                yield relative_name


def selected_files(root):
    root = Path(root).resolve(strict=True)
    if (root / '.git').exists():
        result = subprocess.check_output(['git', '-C', str(root), 'ls-files', '--cached', '--others', '--exclude-standard', '-z'])
        names = set(item.decode('utf-8') for item in result.split(b'\0') if item)
    elif (root / 'source.json').is_file():
        names = set(read_json(root / 'source.json')['files'])
        # Extra source files cannot silently disappear from a restored snapshot.
        actual = set(source_files_without_git(root))
        if names != actual:
            raise ValueError('restored source inventory changed')
    else:
        names = set(source_files_without_git(root))
    result = {}
    for name in sorted(names):
        if ignored_source_path(name):
            continue
        path = root.joinpath(*relative(name).parts)
        if path.is_symlink() or root not in path.resolve().parents:
            raise ValueError('source snapshot contains an escaping or linked file')
        if not path.exists(): continue  # An intentional tracked deletion changes the identity.
        if not path.is_file(): raise ValueError('source snapshot needs an explicitly retained submodule tree')
        result[name] = path
    if not result: raise ValueError('source snapshot is empty')
    return result


def snapshot_paths(root, supplement=None):
    files = selected_files(root)
    if supplement:
        extra = selected_files(supplement)
        retained = {name: path for name, path in files.items() if name.startswith(SUPPLEMENT_PREFIX)}
        expected = {SUPPLEMENT_PREFIX + name: path for name, path in extra.items()}
        if retained and ({name: digest(path) for name, path in retained.items()} != {name: digest(path) for name, path in expected.items()}):
            raise ValueError('retained GUI source differs from explicit supplement')
        files.update(expected)
    return files


def portable_executables(root, paths):
    """Windows cannot represent POSIX mode bits; retain reviewed source metadata.

    Bytes and complete path inventory are still recomputed. POSIX always inspects
    actual file modes so a local chmod remains a source change.
    """
    root = Path(root).resolve(strict=True)
    if not WINDOWS:
        return {name for name, path in paths.items() if path.stat().st_mode & 0o111}
    if (root / '.git').exists():
        raw = subprocess.check_output(['git', '-C', str(root), 'ls-files', '--stage', '-z'])
        names = set(); seen = set()
        for row in raw.split(b'\0'):
            if not row: continue
            metadata, name = row.split(b'\t', 1)
            mode, _, stage = metadata.split()
            if stage != b'0': raise ValueError('unmerged source index cannot define portable modes')
            decoded = name.decode('utf-8')
            if mode not in (b'100644', b'100755') or decoded in seen:
                raise ValueError('unsupported or duplicate source index mode')
            seen.add(decoded)
            if mode == b'100755': names.add(decoded)
        return names & set(paths)
    authority = next((parent for parent in [root, *root.parents] if (parent / 'source.json').is_file()), None)
    if authority is not None:
        data = read_json(authority / 'source.json')
        names = data.get('executables')
        if (not isinstance(names, list) or len(names) != len(set(names)) or
                any(not isinstance(n, str) or n not in data.get('files', {}) for n in names)):
            raise ValueError('invalid retained executable inventory')
        prefix = '' if authority == root else root.relative_to(authority).as_posix() + '/'
        return {name[len(prefix):] for name in names if name.startswith(prefix)} & set(paths)
    return {name for name, path in paths.items() if path.stat().st_mode & 0o111}


def describe_paths(paths, executables=None):
    files = {name: digest(path) for name, path in sorted(paths.items())}
    executables = sorted(executables if executables is not None else
                         (name for name, path in paths.items() if path.stat().st_mode & 0o111))
    identity = hashlib.sha256(encoded({'files': files, 'executables': executables})).hexdigest()
    return {'schema_version': 1, 'tree_sha256': identity, 'files': files, 'executables': executables}


def source_tree(root, supplement=None):
    paths = snapshot_paths(root, supplement)
    executable = portable_executables(root, paths)
    if supplement:
        extra = selected_files(supplement)
        executable.difference_update({name for name in executable if name.startswith(SUPPLEMENT_PREFIX)})
        executable.update(SUPPLEMENT_PREFIX + name for name in portable_executables(supplement, extra))
    return describe_paths(paths, executable)


def archive_source(root, output, supplement=None, epoch=0):
    output = Path(output).resolve()
    source_root = Path(root).resolve(strict=True)
    if source_root in output.parents and source_root / 'build' not in output.parents:
        raise ValueError('source archive output must be outside source inputs or under ignored build/')
    if output.exists(): raise ValueError('source archive destination must be new')
    paths = snapshot_paths(root, supplement)
    before = source_tree(root, supplement)
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=output.parent, prefix='.source-') as temporary:
        staged = Path(temporary) / 'source'
        staged.mkdir()
        for name, path in paths.items():
            destination = staged / name
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(path, destination)
            destination.chmod(0o755 if name in before['executables'] else 0o644)
        write_json(staged / 'source.json', before)
        copied = source_tree(staged)
        if copied != before or source_tree(root, supplement) != before:
            raise ValueError('source inputs changed while snapshotting')
        # Set archive modes from the verified logical inventory, including on
        # Windows where chmod cannot represent POSIX executable permission.
        ready = Path(temporary) / 'source.tar.gz'
        with ready.open('xb') as raw, gzip.GzipFile(filename='', mode='wb', fileobj=raw, mtime=epoch, compresslevel=1) as zipped:
            with tarfile.open(fileobj=zipped, mode='w', format=tarfile.PAX_FORMAT) as archive:
                for name in sorted([*before['files'], 'source.json']):
                    path = staged / name
                    info = tarfile.TarInfo(name)
                    info.size = path.stat().st_size
                    info.mode = 0o755 if name in before['executables'] else 0o644
                    info.mtime = epoch
                    with path.open('rb') as stream: archive.addfile(info, stream)
        verify_source_archive(ready)
        # Same-filesystem link publishes complete bytes without replacing an
        # output another writer may have created after the initial inspection.
        os.link(ready, output)
    verify_source_archive(output)
    return before


def verify_source_archive(archive):
    data, _ = inspect_manifest_archive(archive, 'source.json')
    executables = []
    with tarfile.open(archive) as source:
        for member in source:
            if member.isfile() and member.name != 'source.json' and member.mode & 0o111:
                executables.append(member.name)
    if sorted(executables) != data.get('executables'):
        raise ValueError('source executable mode inventory mismatch')
    actual = hashlib.sha256(encoded({'files': data['files'], 'executables': sorted(executables)})).hexdigest()
    if actual != data.get('tree_sha256'):
        raise ValueError('source tree identity mismatch')
    return data


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('digest', 'archive', 'verify'))
    parser.add_argument('--root', type=Path)
    parser.add_argument('--supplement', type=Path)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--archive', type=Path)
    parser.add_argument('--epoch', type=int, default=0)
    args = parser.parse_args()
    if args.action == 'verify':
        if not args.archive: parser.error('verify requires --archive')
        result = verify_source_archive(args.archive)
    else:
        if not args.root: parser.error('--root is required')
        if args.action == 'digest':
            print(source_tree(args.root, args.supplement)['tree_sha256'])
            return
        if not args.output: parser.error('archive requires --output')
        result = archive_source(args.root, args.output, args.supplement, args.epoch)
    print(encoded(result).decode(), end='')


if __name__ == '__main__':
    try: main()
    except (ValueError, OSError, KeyError, subprocess.CalledProcessError) as error: raise SystemExit(str(error))
