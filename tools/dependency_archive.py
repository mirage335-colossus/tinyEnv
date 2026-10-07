#!/usr/bin/env python3
"""Deterministic archives and strict inventories shared by local supply tools."""
from contextlib import contextmanager
import gzip
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import tarfile
import tempfile


def digest(path):
    value = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            value.update(block)
    return value.hexdigest()


def object_pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('duplicate JSON key: ' + key)
        result[key] = value
    return result


def read_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8'), object_pairs_hook=object_pairs)


def encoded(value):
    return (json.dumps(value, indent=2, sort_keys=True, ensure_ascii=True) + '\n').encode()


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as stream:
        temporary = Path(stream.name)
        stream.write(encoded(value))
        stream.flush()
        os.fsync(stream.fileno())
    try:
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def relative(name):
    if not isinstance(name, str) or not name or '\\' in name or ':' in name:
        raise ValueError('invalid portable relative path')
    path = PurePosixPath(name)
    if path.is_absolute() or any(p in ('', '.', '..') for p in name.split('/')):
        raise ValueError('invalid portable relative path: ' + name)
    for part in path.parts:
        if part.endswith(('.', ' ')) or any(ord(c) < 32 for c in part):
            raise ValueError('invalid portable path component')
    return path


PORTABLE_PATHS = 'portable'
LINUX_SDK_PATHS = 'linux-case-sensitive-v1'


def checked_path_policy(value):
    if value not in (PORTABLE_PATHS, LINUX_SDK_PATHS):
        raise ValueError('unknown retained path policy')
    return value


def sdk_path_policy(metadata):
    policy = checked_path_policy(metadata.get('path_policy', PORTABLE_PATHS))
    host, target = metadata.get('host'), metadata.get('target')
    if policy == LINUX_SDK_PATHS and (
            not isinstance(host, dict) or host.get('system') != 'Linux'
            or not isinstance(target, dict) or target.get('system') != 'Linux'
            or metadata.get('kind') == 'windows-dependencies'):
        raise ValueError('case-sensitive SDK path policy requires a Linux host and target')
    return policy


class PathInventory:
    """Register every component, including implicit directories and exclusions."""
    def __init__(self, path_policy=PORTABLE_PATHS):
        self.policy = checked_path_policy(path_policy)
        self.entries = {}
        self.explicit = set()

    def add(self, name, directory):
        name = str(relative(name))
        parts = name.split('/')
        for length in range(1, len(parts) + 1):
            component = '/'.join(parts[:length])
            is_directory = directory if length == len(parts) else True
            key = component if self.policy == LINUX_SDK_PATHS else component.casefold()
            previous = self.entries.get(key)
            if previous is not None:
                if previous[0] != component:
                    raise ValueError('ambiguous case-insensitive path: ' + component)
                if previous[1] != is_directory:
                    raise ValueError('retained archive file is also an entry parent: ' + component)
            self.entries[key] = (component, is_directory)
        if key in self.explicit:
            raise ValueError('duplicate retained path: ' + name)
        self.explicit.add(key)


def require_linux_case_host():
    import sys
    if not sys.platform.startswith('linux'):
        raise ValueError('Linux case-sensitive SDK paths require a Linux filesystem host')


class CaseProbeError(ValueError):
    preserve_tree = True


@contextmanager
def sdk_temporary_directory(*, dir, prefix):
    """Preserve owned work if a case probe can no longer prove safe cleanup."""
    temporary = Path(tempfile.mkdtemp(dir=dir, prefix=prefix))
    preserve = False
    try:
        yield str(temporary)
    except CaseProbeError:
        preserve = True
        raise
    finally:
        if not preserve:
            shutil.rmtree(temporary)


def probe_case_sensitive(directory):
    """Qualify an owned destination with exclusive, byte-distinct sibling files."""
    import uuid
    require_linux_case_host()
    directory = Path(directory)
    token = '.sdk-case-' + uuid.uuid4().hex
    owned = []
    try:
        for suffix, content in (('A', b'upper\n'), ('a', b'lower\n')):
            path = directory / (token + suffix)
            try:
                with path.open('xb') as stream:
                    state = os.fstat(stream.fileno())
                    owned.append((path, state.st_dev, state.st_ino, content))
                    stream.write(content)
                    stream.flush()
            except FileExistsError as error:
                raise ValueError('SDK destination does not preserve case-distinct paths: ' + str(directory)) from error
        if (owned[0][1:3] == owned[1][1:3]
                or any(path.read_bytes() != content for path, _, _, content in owned)):
            raise ValueError('SDK destination does not preserve case-distinct files: ' + str(directory))
    finally:
        # A changed entry is no longer known to be ours. Preserve it and fail.
        for path, device, inode, content in owned:
            try:
                state = path.lstat()
                if path.is_symlink() or (state.st_dev, state.st_ino) != (device, inode) or path.read_bytes() != content:
                    raise CaseProbeError('SDK filesystem probe changed; preserve destination for inspection: ' + str(path))
            except OSError as error:
                raise CaseProbeError('SDK filesystem probe cleanup uncertain; preserve destination for inspection: ' + str(path)) from error
        for path, _, _, _ in owned:
            try:
                path.unlink()
            except OSError as error:
                raise CaseProbeError('SDK filesystem probe cleanup failed; preserve destination for inspection: ' + str(path)) from error


def verify_case_sensitive(directory):
    """Read-only check of current lookups; repeat in each populated directory."""
    require_linux_case_host()
    directory = Path(directory)
    children = list(directory.iterdir())
    names = {child.name for child in children}
    for child in children:
        alternate = child.name.swapcase()
        if alternate != child.name and alternate not in names:
            alias = directory / alternate
            if alias.exists() or alias.is_symlink():
                raise ValueError('SDK filesystem has a case-insensitive lookup: ' + str(child))


def checked_file(root, name):
    path = Path(root).joinpath(*relative(name).parts)
    for parent in (path, *path.parents):
        if parent == Path(root).parent:
            break
        if parent.is_symlink():
            raise ValueError('links are not allowed in retained groups')
    if not path.is_file():
        raise ValueError('missing ordinary file: ' + name)
    return path


def file_inventory(root, exclude=(), *, path_policy=PORTABLE_PATHS):
    root = Path(root)
    result = {}
    registry = PathInventory(path_policy)
    if path_policy == LINUX_SDK_PATHS:
        verify_case_sensitive(root)
    for path in sorted(root.rglob('*')):
        name = path.relative_to(root).as_posix()
        if path.is_symlink() or (not path.is_file() and not path.is_dir()):
            raise ValueError('unsupported retained entry: ' + name)
        registry.add(name, path.is_dir())
        if path.is_dir() and path_policy == LINUX_SDK_PATHS:
            verify_case_sensitive(path)
        if path.is_file() and name not in exclude:
            result[name] = digest(path)
    return result


def verify_inventory(root, files, exclude=(), *, path_policy=PORTABLE_PATHS):
    if not isinstance(files, dict) or not files:
        raise ValueError('empty inventory')
    if any(not isinstance(value, str) or not re.fullmatch(r'[0-9a-f]{64}', value) for value in files.values()):
        raise ValueError('invalid checksum')
    registry = PathInventory(path_policy)
    for name in files:
        registry.add(name, False)
    for name in exclude:
        registry.add(name, False)
    actual = file_inventory(root, exclude, path_policy=path_policy)
    if actual != files:
        raise ValueError('retained file inventory or checksum mismatch')
    return actual


def archive_tree(root, output, epoch=0, *, path_policy=PORTABLE_PATHS):
    """Ordinary files only. Stable order, metadata and gzip header."""
    root, output = Path(root).resolve(), Path(output).absolute()
    if root == output or root in output.parents or output.exists():
        raise ValueError('archive output must be new and outside input tree')
    files = file_inventory(root, path_policy=path_policy)
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=output.parent, delete=False) as stream:
        temporary = Path(stream.name)
    try:
        with temporary.open('wb') as raw, gzip.GzipFile(filename='', mode='wb', fileobj=raw, mtime=epoch, compresslevel=1) as zipped:
            with tarfile.open(fileobj=zipped, mode='w', format=tarfile.PAX_FORMAT) as archive:
                for name in files:
                    path = root / name
                    info = tarfile.TarInfo(name)
                    info.size = path.stat().st_size
                    info.mode = 0o755 if path.stat().st_mode & 0o111 else 0o644
                    info.mtime = epoch
                    with path.open('rb') as source:
                        archive.addfile(info, source)
        temporary.replace(output)
    finally:
        temporary.unlink(missing_ok=True)
    return digest(output)


def archive_entries(source, max_bytes, path_policy):
    entries, total = [], 0
    registry = PathInventory(path_policy)
    for member in source:
        name = relative(member.name[:-1] if member.isdir() and member.name.endswith('/') else member.name)
        if not (member.isfile() or member.isdir()) or member.mode & 0o7000:
            raise ValueError('linked, privileged or special archive entry')
        registry.add(str(name), member.isdir())
        total += member.size
        if member.size < 0 or total > max_bytes:
            raise ValueError('archive exceeds extraction limit')
        entries.append((member, name))
    return entries


def extract(archive, destination, max_bytes=32 * 1024**3, *, path_policy=PORTABLE_PATHS):
    """Validate the complete archive before creating any destination entry."""
    checked_path_policy(path_policy)
    destination = Path(destination).absolute()
    if destination.exists() or destination.is_symlink():
        raise ValueError('extraction destination must not exist')
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tarfile.open(archive, 'r:*') as source:
        entries = archive_entries(source, max_bytes, path_policy)
        with sdk_temporary_directory(dir=destination.parent, prefix='.extract-') as temporary:
            root = Path(temporary) / 'tree'
            root.mkdir()
            if path_policy == LINUX_SDK_PATHS:
                probe_case_sensitive(root)
            directories = {'.'}
            def ensure_directory(name):
                parent = root
                for component in name.parts:
                    parent = parent / component
                    key = parent.relative_to(root).as_posix()
                    if key not in directories:
                        parent.mkdir()
                        if path_policy == LINUX_SDK_PATHS:
                            probe_case_sensitive(parent)
                        directories.add(key)
            for member, name in entries:
                path = root.joinpath(*name.parts)
                if member.isdir():
                    ensure_directory(name)
                else:
                    ensure_directory(name.parent)
                    with source.extractfile(member) as data, path.open('xb') as output:
                        shutil.copyfileobj(data, output)
                    path.chmod(0o755 if member.mode & 0o111 else 0o644)
            root.rename(destination)
    return destination


def inspect_manifest_archive(path, manifest_name, *, sdk_archive=False):
    """Verify complete hashes; SDK policy selection bounds manifest bytes only."""
    if sdk_archive and manifest_name != 'sdk.json':
        raise ValueError('SDK path policy is limited to the binary SDK manifest')
    with tarfile.open(path, 'r:*') as archive:
        # The bounded exact root manifest can occur after the case-distinct files.
        # Read it first without using case-insensitive tar member lookup.
        matches = [member for member in archive if member.name == manifest_name]
        if len(matches) != 1 or not matches[0].isfile() or matches[0].size > 32 * 1024**2 or matches[0].size < 0:
            raise ValueError('retained archive has a missing, duplicate or oversized manifest')
        with archive.extractfile(matches[0]) as stream:
            data = stream.read(32 * 1024**2 + 1)
        if len(data) > 32 * 1024**2:
            raise ValueError('retained manifest exceeds size limit')
        document = json.loads(data, object_pairs_hook=object_pairs)
        if not isinstance(document, dict):
            raise ValueError('retained manifest must be an object')
        policy = sdk_path_policy(document) if sdk_archive else PORTABLE_PATHS
        entries = archive_entries(archive, 32 * 1024**3, policy)
        files = {}
        for member, name in entries:
            if member.isdir() or str(name) == manifest_name:
                continue
            with archive.extractfile(member) as stream:
                value = hashlib.sha256()
                for block in iter(lambda: stream.read(1024 * 1024), b''):
                    value.update(block)
            files[str(name)] = value.hexdigest()
    if document.get('schema_version') != 1 or document.get('files') != files:
        raise ValueError('retained archive has a missing or incorrect complete manifest')
    return document, hashlib.sha256(data).hexdigest()
