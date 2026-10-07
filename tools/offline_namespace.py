#!/usr/bin/env python3
"""Qualified Linux user/mount/PID/network namespace adapter for offline acceptance.

Setup retains namespace capabilities only until all mounts are established. The
supervisor chroots too; compiler/application children have no capabilities. The
freshly restored SDK is made read-only before the execution phase.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
SETUP_PATH = '/usr/bin:/bin:/usr/sbin:/sbin'


def setup_program(name):
    value = shutil.which(name, path=SETUP_PATH)
    if not value:
        raise ValueError('missing declared namespace setup tool: ' + name)
    return str(Path(value).resolve(strict=True))


def setup_environment():
    return {'PATH': SETUP_PATH, 'LC_ALL': 'C', 'PYTHONUTF8': '1', 'PYTHONDONTWRITEBYTECODE': '1'}


def file_hash(path):
    value = hashlib.sha256()
    with path.open('rb') as source:
        for block in iter(lambda: source.read(1024 * 1024), b''):
            value.update(block)
    return value.hexdigest()


def rootfs_files(root):
    entries = {}
    for parent, directories, files in os.walk(root, followlinks=False):
        for name in directories + files:
            path = Path(parent) / name
            info = path.lstat()
            entry = {'mode': stat.S_IMODE(info.st_mode), 'uid': info.st_uid, 'gid': info.st_gid}
            if stat.S_ISLNK(info.st_mode):
                entry.update(type='symlink', target=os.readlink(path))
            elif stat.S_ISDIR(info.st_mode):
                entry['type'] = 'directory'
            elif stat.S_ISREG(info.st_mode):
                entry.update(type='file', size=info.st_size, sha256=file_hash(path))
            else:
                raise ValueError('prepared rootfs contains an unsupported special entry')
            entries[path.relative_to(root).as_posix()] = entry
    return dict(sorted(entries.items()))


def inventory_digest(files):
    return hashlib.sha256(json.dumps(files, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def mount_point(root, name):
    path = root / name
    parts = Path(name).parts
    if (path.is_symlink() or not path.is_dir() or root not in path.resolve().parents
            or any(root.joinpath(*parts[:index]).is_symlink() for index in range(1, len(parts)))):
        raise ValueError('prepared rootfs lacks an ordinary acceptance mount point: ' + name)
    return path


def verify_rootfs(boundary, *, rust_group=None):
    root, manifest_path = Path(boundary['rootfs']), Path(boundary['manifest'])
    if file_hash(manifest_path) != boundary['manifest_sha256']:
        raise ValueError('prepared rootfs manifest differs from its pinned identity')
    manifest = json.loads(manifest_path.read_text())
    from offline_acceptance import os_release, processor
    if (manifest.get('schema_version') != 1 or not manifest.get('packages')
            or manifest.get('rootfs') != str(root) or manifest.get('architecture') != processor()
            or manifest.get('os_release') != (root / 'etc/os-release').read_text()):
        raise ValueError('prepared rootfs requires complete Bookworm file/package provenance')
    os_release(root / 'etc/os-release')
    name = manifest.get('inventory')
    if not isinstance(name, str) or Path(name).name != name or name in ('.', '..'):
        raise ValueError('rootfs inventory must be an explicit contained manifest sibling')
    inventory_path = manifest_path.parent / name
    if inventory_path.is_symlink() or not inventory_path.is_file():
        raise ValueError('rootfs inventory must be an ordinary file')
    expected = json.loads(inventory_path.read_text())
    actual = rootfs_files(root)
    if actual != expected or inventory_digest(actual) != manifest.get('inventory_sha256'):
        raise ValueError('prepared rootfs file/link/mode inventory changed')
    required = ('work', 'output', 'inputs/group', 'proc', 'dev', 'sys', 'tmp')
    if rust_group is not None:
        required += ('inputs/rust-group',)
    for name in required:
        mount_point(root, name)
    if not (root / 'usr/bin/setpriv').is_file() or root not in (root / 'usr/bin/setpriv').resolve().parents:
        raise ValueError('prepared rootfs lacks the capability-dropping host tool')
    return manifest


def command(boundary, source, output, group, *, rust_group=None):
    if not hasattr(os, 'getuid') or os.getuid() == 0 or os.getgid() == 0:
        raise ValueError('namespace acceptance requires an ordinary Linux host user')
    for name in ('unshare', 'mount', 'chroot', 'ip'):
        setup_program(name)
    if rust_group is not None:
        rust_group = Path(rust_group)
        if rust_group.is_symlink() or not rust_group.is_dir() or rust_group.resolve(strict=True) != rust_group:
            raise ValueError('retained Rust group must be an ordinary canonical directory')
        mount_point(Path(boundary['rootfs']), 'inputs/rust-group')
    argv = [setup_program('unshare'), '--user', '--map-root-user', '--mount', '--net', '--pid', '--fork',
            str(Path(sys.executable).resolve(strict=True)), '-I', '-B', str(source / 'tools/offline_namespace.py'), '--inside', '--rootfs', boundary['rootfs'],
            '--source', str(source), '--output', str(output), '--group', str(group),
            '--uid', str(os.getuid()), '--gid', str(os.getgid())]
    if rust_group is not None:
        argv += ['--rust-group', str(rust_group)]
    return argv


def mount(*arguments):
    subprocess.run([setup_program('mount'), *map(str, arguments)], check=True, env=setup_environment())


def read_only_bind(source, destination):
    mount('--bind', source, destination)
    mount('-o', 'remount,bind,ro,nosuid,nodev', destination)


def restored_sdk(output, name, manifest):
    root = output / name
    receipt = root / manifest
    if (root.is_symlink() or not root.is_dir() or root.resolve(strict=True) != output.resolve(strict=True) / name
            or receipt.is_symlink() or not receipt.is_file()):
        raise ValueError('offline execution requires an ordinary completed SDK restoration: ' + name)
    return root


def inside(rootfs, source, output, group, uid, gid, *, rust_group=None):
    if os.getuid() != 0 or uid <= 0 or gid <= 0:
        raise ValueError('namespace setup requires a mapped ordinary host user')
    expected = f'0 {uid} 1'
    if ' '.join(Path('/proc/self/uid_map').read_text().split()) != expected:
        raise ValueError('namespace host user mapping differs from the launcher')
    # Namespace lifetime owns these mounts. No host mount or reusable rootfs is
    # changed; setup errors end the namespace before any application command.
    mount('--make-rprivate', '/')
    view = output.parent / ('.namespace-' + output.name)
    view.mkdir()
    read_only_bind(rootfs, view)
    read_only_bind(source, view / 'work')
    read_only_bind(group, view / 'inputs/group')
    if rust_group is not None:
        read_only_bind(rust_group, view / 'inputs/rust-group')
    mount('--bind', output, view / 'output')
    mount('-t', 'proc', '-o', 'nosuid,nodev,noexec', 'proc', view / 'proc')
    mount('-t', 'sysfs', '-o', 'ro,nosuid,nodev,noexec', 'sysfs', view / 'sys')
    mount('-t', 'tmpfs', '-o', 'mode=1777,nosuid,nodev', 'tmpfs', view / 'tmp')
    mount('-t', 'tmpfs', '-o', 'mode=755,nosuid', 'tmpfs', view / 'dev')
    for name in ('null', 'zero', 'random', 'urandom'):
        destination = view / 'dev' / name
        destination.touch()
        mount('--bind', Path('/dev') / name, destination)
    (view / 'dev/shm').mkdir()
    mount('-t', 'tmpfs', '-o', 'mode=1777,nosuid,nodev,noexec', 'tmpfs', view / 'dev/shm')
    (view / 'dev/fd').symlink_to('/proc/self/fd')
    subprocess.run([setup_program('ip'), 'link', 'set', 'lo', 'up'], check=True, env=setup_environment())
    # The supervisor's /proc/PID/root must also expose only the prepared root.
    os.chroot(view)
    os.chdir('/work')
    environment = {'PATH': '/usr/bin:/bin', 'HOME': '/output/home', 'USER': 'offline-builder', 'LOGNAME': 'offline-builder',
                   'TMPDIR': '/output/tmp', 'XDG_CACHE_HOME': '/output/cache', 'LC_ALL': 'C',
                   'PYTHONUTF8': '1', 'PYTHONDONTWRITEBYTECODE': '1', 'CCACHE_DISABLE': '1',
                   'CCACHE_DIR': '/output/cache/ccache', 'FOUNDATION_OUTER_UID': str(uid),
                   'LIBGL_ALWAYS_SOFTWARE': '1'}
    launcher = ['/usr/bin/setpriv', '--bounding-set=-all', '--inh-caps=-all', '--ambient-caps=-all', '--no-new-privs']
    inner = ['/usr/bin/python3', '-B', '/work/tools/offline_acceptance.py', '--request', '/output/request.json']
    stage_environment = {**environment, 'HOME': '/output/stage-home', 'TMPDIR': '/output/stage-tmp',
                         'XDG_CACHE_HOME': '/output/stage-cache', 'CCACHE_DIR': '/output/stage-cache/ccache'}
    subprocess.run([*launcher, *inner, '--inside', 'stage'], check=True, env=stage_environment)
    sdk = restored_sdk(Path('/output'), 'sdk', 'sdk.json')
    read_only_bind(sdk, sdk)
    if rust_group is not None:
        rust_sdk = restored_sdk(Path('/output'), 'rust-sdk', 'rust-sdk.json')
        read_only_bind(rust_sdk, rust_sdk)
    # Native GUI smoke requires a separately declared disposable display. This
    # does not enter the retained SDK or become an application prerequisite.
    target = json.loads(Path('/output/request.json').read_text())['case']['target']
    display = ['xvfb-run', '-a', '/usr/bin/env', 'TMPDIR=/output/tmp'] if target.startswith('linux-') else []
    execute_environment = {**environment, 'TMPDIR': '/tmp'} if display else environment
    subprocess.run([*launcher, *display, *inner, '--inside', 'execute'], check=True, env=execute_environment)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--inside', action='store_true')
    for name in ('rootfs', 'source', 'output', 'group'):
        parser.add_argument('--' + name, type=Path, required=True)
    parser.add_argument('--rust-group', type=Path)
    parser.add_argument('--uid', type=int, required=True)
    parser.add_argument('--gid', type=int, required=True)
    args = parser.parse_args(argv)
    if not args.inside:
        raise ValueError('namespace adapter must be invoked by the validated acceptance launcher')
    inside(args.rootfs, args.source, args.output, args.group, args.uid, args.gid, rust_group=args.rust_group)
    return 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except (OSError, ValueError, subprocess.CalledProcessError) as error:
        print('offline namespace: ' + str(error), file=sys.stderr)
        sys.exit(1)
