#!/usr/bin/env python3
"""Wrap qualified binary archives and authenticate complete local distribution channels.

No source compilation, dependency installation, network retrieval or remote publication.
Mutable destinations must be private to this tool and cooperating locked writers.
"""
import argparse
import base64
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import gzip
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
from urllib.parse import urlsplit
import zipfile


def sibling(name):
    spec = importlib.util.spec_from_file_location('distro_' + name, Path(__file__).with_name(name + '.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


apt = sibling('apt_repo')
artifact = sibling('artifact')
archive_tools = sibling('dependency_archive')
MAX_BYTES = 320 * 1024 * 1024
MAX_FILES = 10000
BACKENDS = {'core', 'terminal', 'framebuffer', 'fltk', 'rev', 'sdl', 'hosted-web'}
GUI_EXECUTABLES = {'foundation-gui-' + ('web' if backend == 'hosted-web' else backend)
                   for backend in BACKENDS - {'core'}}
SELECTION_PATH = 'share/doc/Foundation/distro-selection.json'
ARCHES = {'x86_64': 'amd64', 'aarch64': 'arm64'}
CONTROL = {'channel.json', 'channel.json.sig'}


class CommitUncertain(RuntimeError):
    """Activation happened, but its final durability acknowledgment failed."""


def encoded(value):
    return (json.dumps(value, sort_keys=True, indent=2, allow_nan=False) + '\n').encode()


def digest(data):
    return hashlib.sha256(data).hexdigest()


def document(data):
    if len(data) > 8 * 1024 * 1024:
        raise ValueError('metadata exceeds limit')
    return json.loads(data, object_pairs_hook=archive_tools.object_pairs,
                      parse_constant=lambda _: (_ for _ in ()).throw(ValueError('nonfinite JSON')))


def safe_name(value):
    path = archive_tools.relative(value)
    if not re.fullmatch(r'[A-Za-z0-9_+./-]+', value):
        raise ValueError('unsafe channel path spelling')
    artifact.member_path(value)
    return path


def ordinary(path, limit=MAX_BYTES):
    path = Path(path).absolute()
    if any(parent.is_symlink() for parent in (path, *path.parents)):
        raise ValueError('linked input or ancestor')
    before = path.stat()
    if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1 or before.st_size > limit:
        raise ValueError('expected bounded singly linked regular file')
    flags = os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0)
    with os.fdopen(os.open(path, flags), 'rb') as stream:
        opened = os.fstat(stream.fileno())
        data = stream.read(limit + 1)
        after = os.fstat(stream.fileno())
    identity = lambda st: (st.st_dev, st.st_ino, st.st_size, st.st_mtime_ns, st.st_ctime_ns)
    if len(data) > limit or identity(before) != identity(opened) or identity(opened) != identity(after) or identity(after) != identity(path.stat()):
        raise ValueError('input changed while reading')
    return data, stat.S_IMODE(before.st_mode)


def tree(root):
    root = Path(root).absolute()
    if root.is_symlink() or not root.is_dir() or root.resolve() != root:
        raise ValueError('expected physical tree')
    result, seen, directories, total = {}, set(), set(), 0
    for path in sorted(root.rglob('*')):
        name = path.relative_to(root).as_posix()
        safe_name(name)
        if name.casefold() in seen or len(seen) >= MAX_FILES:
            raise ValueError('duplicate path or excessive inventory')
        seen.add(name.casefold())
        if path.is_symlink():
            raise ValueError('linked channel entry')
        if path.is_dir():
            if stat.S_IMODE(path.stat().st_mode) != 0o755:
                raise ValueError('unexpected channel directory mode')
            directories.add(name)
            continue
        data, mode = ordinary(path)
        if mode not in (0o644, 0o755):
            raise ValueError('unexpected channel file mode')
        total += len(data)
        if total > MAX_BYTES:
            raise ValueError('channel exceeds bounded example size')
        result[name] = (data, mode)
    if directories != parent_directories(result):
        raise ValueError('unexpected empty or incomplete directory inventory')
    return result


def parent_directories(files):
    return {str(parent) for name in files for parent in safe_name(name).parents if str(parent) != '.'}


def inventory(files):
    return {name: {'sha256': digest(data), 'size': len(data), 'mode': mode}
            for name, (data, mode) in sorted(files.items())}


def write_files(root, files):
    for name in sorted(parent_directories(files), key=lambda value: (value.count('/'), value)):
        directory = root.joinpath(*safe_name(name).parts)
        directory.mkdir(exist_ok=True)
        directory.chmod(0o755)
    for name, (data, mode) in files.items():
        target = root.joinpath(*safe_name(name).parts)
        with target.open('xb') as stream:
            stream.write(data)
            stream.flush()
            os.fchmod(stream.fileno(), mode)
            os.fsync(stream.fileno())
    for name in sorted(parent_directories(files), key=lambda value: (-value.count('/'), value)):
        sync_directory(root / name)
    sync_directory(root)


def sync_directory(path):
    if os.name != 'posix' or not hasattr(os, 'O_DIRECTORY'):
        raise ValueError('durable publication needs the qualified POSIX filesystem profile')
    descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def gzip_bytes(data):
    output = io.BytesIO()
    with gzip.GzipFile(filename='', mode='wb', fileobj=output, mtime=0) as zipped:
        zipped.write(data)
    return output.getvalue()


def immutable_url(value, expected):
    if not isinstance(value, str) or not re.fullmatch(r'[0-9a-f]{64}', expected):
        raise ValueError('invalid URL digest')
    url = urlsplit(value)
    if (url.scheme != 'https' or not url.netloc or url.username or url.password or url.query or url.fragment
            or expected not in url.path or re.search(r'[\s\x00-\x1f\'"$`\\]', value)):
        raise ValueError('require an HTTPS content-addressed immutable URL')
    return value


def release_tag_url(value, expected):
    """Require one exact GitHub tag asset, authenticated by its separate digest."""
    if not isinstance(expected, str) or not re.fullmatch(r'[0-9a-f]{64}', expected):
        raise ValueError('invalid URL digest')
    component = r'[A-Za-z0-9][A-Za-z0-9_.+-]{0,180}'
    repository = r'[A-Za-z0-9][A-Za-z0-9_.-]{0,180}'
    match = re.fullmatch(r'https://github\.com/(' + repository + ')/(' + repository +
                         r')/releases/download/(' + component + ')/(' + component + ')', value) if isinstance(value, str) else None
    if not match or match[3].lower() == 'latest':
        raise ValueError('require an exact HTTPS GitHub release-tag asset URL')
    for part in match.groups():
        safe_name(part)
        stem = part.split('.', 1)[0].upper()
        if (part.endswith('.') or '..' in part or stem in {'CON', 'PRN', 'AUX', 'NUL'} or
                re.fullmatch(r'(?:COM|LPT)[1-9]', stem)):
            raise ValueError('unsafe release-tag URL spelling')
    return value


def version_key(spec):
    value = spec['version']
    if not isinstance(value, str) or not re.fullmatch(r'(?:0|[1-9][0-9]{0,5})(?:\.(?:0|[1-9][0-9]{0,5})){2}', value):
        raise ValueError('version must have three bounded canonical numeric components')
    release = spec['package_release']
    if type(release) is not int or not 1 <= release <= 999999:
        raise ValueError('invalid package release')
    return tuple(map(int, value.split('.'))) + (release,)


def require_gui_terms():
    lock = document(ordinary(Path(__file__).resolve().parents[1] / 'third_party/gui-boundary.lock.json')[0])
    if not (lock.get('redistribution', {}).get('approved') is True and lock.get('license') != 'NOASSERTION'
            and lock.get('redistribution', {}).get('license_files')):
        raise ValueError('GUI dependency redistribution terms remain unresolved')


def runtime_policy(backend):
    result = {'arch': ['glibc>=2.36'], 'gentoo': ['>=sys-libs/glibc-2.36']}
    if backend == 'hosted-web':
        result['arch'].append('python'); result['gentoo'].append('dev-lang/python')
    if backend == 'fltk':
        result['arch'].extend(['fontconfig', 'ttf-dejavu'])
        result['gentoo'].extend(['media-libs/fontconfig', 'media-fonts/dejavu'])
    if backend in ('rev', 'sdl'):
        result['arch'].append('mesa'); result['gentoo'].append('media-libs/mesa[X,opengl]')
    return result


CURRENT_SCHEMA = 6
RELEASE_TAG_SCHEMA = 7


def validate_spec(spec):
    fields = {'schema_version', 'version', 'package_release', 'architecture', 'backend',
              'archive_url', 'archive_sha256', 'license_files', 'redistribution_approved',
              'application_source', 'packaging_tool', 'sdk', 'dependencies', 'runtime_dependencies'}
    if not isinstance(spec, dict) or set(spec) != fields or type(spec['schema_version']) is not int or spec['schema_version'] not in (1, 2, 3, 4, 5, 6, RELEASE_TAG_SCHEMA):
        raise ValueError('invalid complete package specification')
    version_key(spec)
    if spec['architecture'] not in ARCHES or spec['backend'] not in BACKENDS or spec['redistribution_approved'] is not True:
        raise ValueError('unsupported target or unreviewed redistribution terms')
    check_url = release_tag_url if spec['schema_version'] == RELEASE_TAG_SCHEMA else immutable_url
    check_url(spec['archive_url'], spec['archive_sha256'])
    if not isinstance(spec['license_files'], list) or not spec['license_files'] or len(set(spec['license_files'])) != len(spec['license_files']):
        raise ValueError('complete retained license file list required')
    for name in spec['license_files']:
        safe_name(name)
    if not isinstance(spec['dependencies'], list) or len(spec['dependencies']) > 100:
        raise ValueError('invalid dependency provenance')
    for record in [spec['application_source'], spec['packaging_tool'], spec['sdk'], *spec['dependencies']]:
        if not isinstance(record, dict) or set(record) != {'url', 'sha256'}:
            raise ValueError('source, SDK and dependency groups require exact URLs and digests')
        check_url(record['url'], record['sha256'])
        if (spec['schema_version'] == RELEASE_TAG_SCHEMA and
                record['url'].rsplit('/', 1)[0] != spec['archive_url'].rsplit('/', 1)[0]):
            raise ValueError('release-tag references must name the same exact repository and tag')
    dependencies = spec['runtime_dependencies']
    if not isinstance(dependencies, dict) or set(dependencies) != {'arch', 'gentoo'}:
        raise ValueError('explicit runtime dependency lists required')
    for kind, values in dependencies.items():
        if not isinstance(values, list) or not values or len(values) > 100 or len(set(values)) != len(values):
            raise ValueError('invalid runtime dependency list')
        atom = r'[A-Za-z0-9+_.<>=:/-]{1,150}'
        if kind == 'gentoo': atom += r'(?:\[[A-Za-z0-9_+!?=-]+(?:,[A-Za-z0-9_+!?=-]+)*\])?'
        if any(not isinstance(v, str) or len(v) > 200 or not re.fullmatch(atom, v) for v in values):
            raise ValueError('unsafe runtime dependency atom')
        if spec['schema_version'] >= 3 and not set(runtime_policy(spec['backend'])[kind]) <= set(values):
            raise ValueError('required backend runtime dependencies are absent')
    if spec['backend'] != 'core':
        require_gui_terms()
    return spec


def tar_bytes(files):
    output = io.BytesIO()
    directories = parent_directories(files)
    if directories & files.keys():
        raise ValueError('file is also a directory')
    with gzip.GzipFile(filename='', mode='wb', fileobj=output, mtime=0) as zipped:
        with tarfile.open(fileobj=zipped, mode='w', format=tarfile.PAX_FORMAT) as bundle:
            for name in sorted(set(files) | directories):
                member = tarfile.TarInfo(name)
                member.uid = member.gid = member.mtime = 0
                if name in directories:
                    member.type, member.mode = tarfile.DIRTYPE, 0o755
                    bundle.addfile(member)
                else:
                    data, member.mode = files[name]
                    member.size = len(data)
                    bundle.addfile(member, io.BytesIO(data))
    return output.getvalue()


def archive_payload(path, expected):
    if zipfile.is_zipfile(path):
        with zipfile.ZipFile(path) as bundle:
            for entry in bundle.infolist():
                safe_name(entry.filename[:-1] if entry.is_dir() and entry.filename.endswith('/') else entry.filename)
    else:
        with tarfile.open(path, 'r:*') as bundle:
            for entry in bundle:
                safe_name(entry.name[:-1] if entry.isdir() and entry.name.endswith('/') else entry.name)
    if artifact.describe(path) != expected:
        raise ValueError('portable archive bytes or inventory differ')
    with tempfile.TemporaryDirectory(prefix='foundation portable ') as temporary:
        root = Path(temporary)
        artifact.inspect_archive(path, root)
        for directory in root.rglob('*'):
            if directory.is_dir():
                directory.chmod(0o755)
        roots = list(root.iterdir())
        if len(roots) != 1 or not roots[0].is_dir():
            raise ValueError('portable archive needs exactly one installation root')
        files = tree(roots[0])
        if 'bin/foundation-cli' not in files or files['bin/foundation-cli'][1] != 0o755:
            raise ValueError('portable archive needs executable CLI')
        safe_name(roots[0].name)
        return roots[0].name, files


def select_payload(spec, root_name, payload):
    """Project a complete known executable inventory; retain every shared file."""
    public = {path: value for path, value in payload.items() if path.startswith('bin/')}
    known = {'bin/' + name for name in {'foundation-cli', *GUI_EXECUTABLES}}
    selected = {'bin/foundation-cli'}
    if spec['backend'] != 'core':
        selected.add('bin/foundation-gui-' + ('web' if spec['backend'] == 'hosted-web' else spec['backend']))
    if not selected <= public.keys() or not public.keys() <= known or any(mode != 0o755 for _, mode in public.values()):
        raise ValueError('unexpected, nonexecutable or missing public executable')
    if SELECTION_PATH in payload:
        raise ValueError('generated selection receipt collides with archive content')
    existing = {path.casefold(): path for path in set(payload) | parent_directories(payload)}
    for path in {SELECTION_PATH} | parent_directories({SELECTION_PATH: None}):
        if path in payload or (path.casefold() in existing and existing[path.casefold()] != path):
            raise ValueError('generated selection receipt has an aliased or blocked ancestor')
    excluded = {path: value for path, value in public.items() if path not in selected}
    kept = {path: value for path, value in payload.items() if path not in excluded}
    receipt = {'schema_version': 1, 'backend': spec['backend'], 'archive_sha256': spec['archive_sha256'],
               'archive_root': root_name, 'source_file_inventory_sha256': digest(encoded(inventory(payload))),
               'selected_executables': inventory({path: public[path] for path in selected}),
               'excluded_executables': inventory(excluded), 'retained_files': inventory(kept)}
    kept[SELECTION_PATH] = (encoded(receipt), 0o644)
    return kept, receipt


def required_license_files(payload):
    """Derive complete terms from the authenticated archive, not caller preference."""
    required = {'share/doc/Foundation/LICENSE'}
    gui = 'share/doc/Foundation/gui-boundary/'
    deps = 'share/doc/Foundation/dependency-notices/'
    lock_path, index_path = gui+'gui-boundary.lock.json', deps+'index.json'
    has_gui = any(path.startswith(gui) or path.startswith('bin/foundation-gui-') for path in payload)
    def data(path):
        if path not in payload or payload[path][1] != 0o644:
            raise ValueError('missing or non-data retained license file: '+path)
        return payload[path][0]
    if has_gui:
        lock = document(data(lock_path)); permission = lock.get('redistribution', {})
        names = permission.get('license_files')
        if (permission.get('approved') is not True or not isinstance(names, list) or not names or
                len(set(names)) != len(names) or not isinstance(lock.get('files'), dict)):
            raise ValueError('incomplete bundled GUI redistribution terms')
        required.add(lock_path)
        for name in names:
            safe_name(name); path = gui+name
            if digest(data(path)) != lock['files'].get(name):
                raise ValueError('bundled GUI license digest differs')
            required.add(path)
    if has_gui or any(path.startswith(deps) for path in payload):
        index = document(data(index_path))
        if (not isinstance(index, dict) or set(index) != {'schema_version','providers','files'} or
                type(index['schema_version']) is not int or index['schema_version'] != 1 or
                not isinstance(index['providers'], list) or not isinstance(index['files'], dict)):
            raise ValueError('invalid bundled dependency notice index')
        required.add(index_path)
        for name, record in index['files'].items():
            safe_name(name); path = deps+name
            if (name == 'index.json' or not isinstance(record, dict) or set(record) != {'sha256','size'} or
                    type(record['size']) is not int or record['size'] < 0 or
                    record['size'] != len(data(path)) or record['sha256'] != digest(data(path))):
                raise ValueError('bundled dependency notice identity differs')
            required.add(path)
        if {path for path in payload if path.startswith(deps)} != {deps+name for name in index['files']} | {index_path}:
            raise ValueError('dependency notice inventory omits installed files')
    for path in required: data(path)
    return sorted(required)


def recipe_files(spec, root_name, payload, archive_name):
    """Templates are also the verifier: unexpected hooks cannot be signed in silently."""
    if spec['schema_version'] >= 3 and not set(required_license_files(payload)) <= set(spec['license_files']):
        raise ValueError('license list omits required retained terms')
    backend, architecture = spec['backend'], spec['architecture']
    name = 'software-foundation-' + backend + '-bin'
    private = 'opt/software-foundation/' + backend
    selection = None
    if spec['schema_version'] >= 2:
        payload, selection = select_payload(spec, root_name, payload)
    allowed = {'foundation-cli'}
    if backend != 'core':
        allowed.add('foundation-gui-' + ('web' if backend == 'hosted-web' else backend))
    binaries = {Path(path).name for path in payload if path.startswith('bin/')}
    if binaries != allowed or any('/' in path[4:] for path in payload if path.startswith('bin/')):
        raise ValueError('unexpected or missing public executable')
    launchers = {}
    for binary in sorted(binaries):
        public = binary + ('-' + backend if binary == 'foundation-cli' and backend != 'core' else '')
        launchers[public] = (f'#!/bin/sh\nexec /{private}/bin/{binary} "$@"\n'.encode(), 0o755)
    desktop = apt.desktop_files(backend, payload) if spec['schema_version'] >= 5 else {}
    if spec['schema_version'] >= 6:
        desktop.update(apt.offline_desktop_files(backend, payload))
    for path, value in desktop.items():
        if path.startswith('usr/bin/'):
            launchers[Path(path).name] = value
    entries = {Path(path).name: value for path, value in desktop.items() if path.startswith('usr/share/applications/')}
    notices = []
    for path in spec['license_files']:
        if path not in payload:
            raise ValueError('missing retained license file')
        notices.append(path.encode() + b'\n' + payload[path][0] + b'\n')
    terms = b'\n'.join(notices)
    suffix = '-' + backend if backend != 'core' else ''
    manuals = {source: destination for source, destination in {
        'share/man/man1/foundation-cli.1': 'usr/share/man/man1/foundation-cli' + suffix + '.1',
        'share/man/man7/software-foundation.7': 'usr/share/man/man7/software-foundation-' + backend + '.7'
    }.items() if source in payload}
    if any(payload[source][1] != 0o644 for source in manuals):
        raise ValueError('manual pages must have ordinary data-file permissions')
    native = {private + '/' + path: value for path, value in payload.items()}
    native.update({destination: payload[source] for source, destination in manuals.items()})
    native.update({'usr/bin/' + path: value for path, value in launchers.items()})
    native.update({'usr/share/applications/' + path: value for path, value in entries.items()})
    native[f'usr/share/licenses/{name}/LICENSE'] = (terms, 0o644)
    version = spec['version'] + '-' + str(spec['package_release'])
    pkginfo = (f'pkgname = {name}\npkgbase = {name}\npkgver = {version}\n'
               f'pkgdesc = Generic prebuilt application ({backend})\narch = {architecture}\n'
               'license = LicenseRef-Foundation-Bundled\n'
               'builddate = 0\npackager = Software Foundation contributors\n'
               f'size = {sum(len(v[0]) for v in native.values())}\nxdata = pkgtype=pkg\n')
    pkginfo += ''.join('depend = ' + value + '\n' for value in spec['runtime_dependencies']['arch'])
    native['.PKGINFO'] = (pkginfo.encode(), 0o644)
    mtree = '#mtree\n' + ''.join(f'./{path} type=dir uid=0 gid=0 mode=755 time=0\n' for path in sorted(parent_directories(native)))
    mtree += ''.join(f'./{path} type=file uid=0 gid=0 mode={mode:o} size={len(data)} time=0 sha256digest={digest(data)}\n'
                     for path, (data, mode) in sorted(native.items()))
    native['.MTREE'] = (gzip_bytes(mtree.encode()), 0o644)
    package_name = f'{name}-{version}-{architecture}.pkg.tar.gz'
    output = {'arch/' + package_name: (tar_bytes(native), 0o644)}
    source_values = [spec['archive_url'], 'LICENSE', *launchers]
    sums = [spec['archive_sha256'], digest(terms), *(digest(value[0]) for value in launchers.values())]
    install = f'  install -d "$pkgdir/{private}"\n  cp -a "$srcdir/{root_name}/." "$pkgdir/{private}/"\n'
    if selection is not None:
        source_values.append('selection.json')
        sums.append(digest(encoded(selection)))
        install += ''.join(f'  rm -- "$pkgdir/{private}/{path}"\n' for path in sorted(selection['excluded_executables']))
        install += f'  install -Dm644 "$srcdir/selection.json" "$pkgdir/{private}/{SELECTION_PATH}"\n'
    install += f'  install -Dm644 "$srcdir/LICENSE" "$pkgdir/usr/share/licenses/{name}/LICENSE"\n'
    install += ''.join(f'  install -Dm755 "$srcdir/{launcher}" "$pkgdir/usr/bin/{launcher}"\n' for launcher in launchers)
    install += ''.join(f'  install -Dm644 "$srcdir/{root_name}/{source}" "$pkgdir/{destination}"\n'
                       for source, destination in manuals.items())
    source_values.extend(entries)
    sums.extend(digest(value[0]) for value in entries.values())
    install += ''.join(f'  install -Dm644 \"$srcdir/{entry}\" \"$pkgdir/usr/share/applications/{entry}\"\n' for entry in entries)
    source_values[0] = archive_name + '::' + source_values[0]
    quotes = lambda values: ' '.join("'" + value + "'" for value in values)
    pkgbuild = (f'pkgname={name}\npkgver={spec["version"]}\npkgrel={spec["package_release"]}\n'
                f'pkgdesc="Generic prebuilt application ({backend})"\narch=({quotes([architecture])})\n'
                "license=('LicenseRef-Foundation-Bundled')\noptions=('!strip' '!debug' '!zipman')\n"
                f'depends=({quotes(spec["runtime_dependencies"]["arch"])})\nsource=({quotes(source_values)})\n'
                f'sha256sums=({quotes(sums)})\npackage() {{\n{install}}}\n')
    srcinfo = (f'pkgbase = {name}\n\tpkgdesc = Generic prebuilt application ({backend})\n'
               f'\tpkgver = {spec["version"]}\n\tpkgrel = {spec["package_release"]}\n'
               f'\tarch = {architecture}\n\tlicense = LicenseRef-Foundation-Bundled\n'
               '\toptions = !strip\n\toptions = !debug\n\toptions = !zipman\n')
    srcinfo += ''.join('\tdepends = ' + item + '\n' for item in spec['runtime_dependencies']['arch'])
    srcinfo += ''.join('\tsource = ' + item + '\n' for item in source_values)
    srcinfo += ''.join('\tsha256sums = ' + item + '\n' for item in sums) + f'pkgname = {name}\n'
    arch_prefix = 'recipes/arch/' + name + '/'
    output.update({arch_prefix + 'PKGBUILD': (pkgbuild.encode(), 0o644), arch_prefix + '.SRCINFO': (srcinfo.encode(), 0o644),
                   arch_prefix + 'LICENSE': (terms, 0o644)})
    output.update({arch_prefix + path: value for path, value in launchers.items()})
    output.update({arch_prefix + path: value for path, value in entries.items()})
    if selection is not None:
        output['backend-selection.json'] = (encoded(selection), 0o644)
        output[arch_prefix + 'selection.json'] = (encoded(selection), 0o644)
    gentoo_prefix = 'gentoo/app-misc/' + name + '/'
    revision = '' if spec['package_release'] == 1 else '-r' + str(spec['package_release'] - 1)
    ebuild_name = name + '-' + spec['version'] + revision + '.ebuild'
    license_name = 'Foundation-Bundled-' + backend
    # Historical recipes stay byte-identical; EAPI phase compliance is versioned.
    prepare_command = 'eapply_user' if spec['schema_version'] >= 4 else ':'
    ebuild = (f'EAPI=8\nDESCRIPTION="Generic prebuilt application ({backend})"\n'
              f'SRC_URI="{spec["archive_url"]} -> {archive_name}"\nS="${{WORKDIR}}/{root_name}"\n'
              f'LICENSE="{license_name}"\nSLOT="0"\nKEYWORDS="~{ARCHES[architecture]}"\n'
              f'RDEPEND="{" ".join(spec["runtime_dependencies"]["gentoo"])}"\n'
              'RESTRICT="strip"\nQA_PREBUILT="*"\n'
              f'src_prepare() {{ {prepare_command}; }}\n'
              'src_configure() { :; }\nsrc_compile() { :; }\n'
              f'src_install() {{\n  insinto /{private}\n  doins -r "${{S}}/."\n')
    if selection is not None:
        ebuild += ''.join(f'  rm -- "${{D}}/{private}/{path}" || die\n' for path in sorted(selection['excluded_executables']))
        ebuild += f'  insinto /{private}/{str(Path(SELECTION_PATH).parent)}\n  newins "${{FILESDIR}}/selection.json" distro-selection.json\n'
    ebuild += ''.join(f'  fperms 0755 /{private}/{path}\n' for path, (_, mode) in sorted(payload.items()) if mode == 0o755)
    ebuild += ''.join(f'  dobin "${{FILESDIR}}/{path}"\n' for path in launchers)
    ebuild += ''.join(f'  insinto /{Path(destination).parent.as_posix()}\n  newins "${{S}}/{source}" {Path(destination).name}\n'
                      for source, destination in manuals.items())
    ebuild += ''.join(f'  insinto /usr/share/applications\n  newins \"${{FILESDIR}}/{path}\" {path}\n' for path in entries)
    if spec['schema_version'] >= 3:
        ebuild += '  docompress -x /opt/software-foundation /usr/share/man\n'
    ebuild += '}\n'
    output[gentoo_prefix + ebuild_name] = (ebuild.encode(), 0o644)
    gentoo_aux = dict(launchers, **entries)
    if selection is not None:
        gentoo_aux['selection.json'] = (encoded(selection), 0o644)
    output.update({gentoo_prefix + 'files/' + path: value for path, value in gentoo_aux.items()})
    # Full manifests bind recipes/helpers as well as the downloaded archive.
    manifest = f'DIST {archive_name} {spec["archive_size"]} SHA512 {spec["archive_sha512"]}\n'
    manifest += f'EBUILD {ebuild_name} {len(ebuild.encode())} SHA512 {hashlib.sha512(ebuild.encode()).hexdigest()}\n'
    manifest += ''.join(f'AUX {path} {len(data)} SHA512 {hashlib.sha512(data).hexdigest()}\n' for path, (data, _) in gentoo_aux.items())
    output[gentoo_prefix + 'Manifest'] = (manifest.encode(), 0o644)
    output['gentoo/licenses/' + license_name] = (terms, 0o644)
    return output


def expected_package(files):
    for key in ('spec.json', 'portable-manifest.json'):
        if key not in files:
            raise ValueError('incomplete retained package metadata')
    spec = validate_spec(document(files['spec.json'][0]))
    manifest = document(files['portable-manifest.json'][0])
    name = manifest['archive']
    safe_name(name)
    if not name.endswith(('.tar.gz', '.tar.xz', '.tar', '.zip')):
        raise ValueError('unsupported portable archive extension')
    if '/' in name or 'retained/' + name not in files:
        raise ValueError('missing retained portable archive')
    data = files['retained/' + name][0]
    if digest(data) != spec['archive_sha256']:
        raise ValueError('archive differs from recipe digest')
    with tempfile.TemporaryDirectory(prefix='foundation recipe ') as temporary:
        path = Path(temporary) / name
        path.write_bytes(data)
        root_name, payload = archive_payload(path, manifest)
    if spec['schema_version'] >= 2 and any('bin/' + name in payload for name in GUI_EXECUTABLES):
        # Retained archives and shared files still contain GUI material for core projections.
        require_gui_terms()
    augmented = dict(spec, archive_size=len(data), archive_sha512=hashlib.sha512(data).hexdigest())
    generated = recipe_files(augmented, root_name, payload, name)
    generated.update({'spec.json': (encoded(spec), 0o644), 'portable-manifest.json': (encoded(manifest), 0o644), 'retained/' + name: (data, 0o644)})
    return generated, spec


def package(archive, manifest, spec_path, output):
    archive, output = Path(archive), Path(output).absolute()
    files = {'retained/' + archive.name: (ordinary(archive)[0], 0o644),
             'spec.json': (encoded(document(ordinary(spec_path)[0])), 0o644),
             'portable-manifest.json': (encoded(document(ordinary(manifest)[0])), 0o644)}
    expected, _ = expected_package(files)
    publish_new(output, expected)
    return {'files': inventory(expected)}


def publish_new(output, files):
    if output.exists() or output.is_symlink() or output.parent.resolve() != output.parent:
        raise ValueError('output must be new under a physical existing parent')
    published = False
    try:
        with tempfile.TemporaryDirectory(prefix='.channel-stage-', dir=output.parent) as temporary:
            stage = Path(temporary) / 'tree'
            stage.mkdir()
            write_files(stage, files)
            if tree(stage) != files:
                raise ValueError('staged publication differs')
            stage.rename(output)
            published = True
            sync_directory(output.parent)
    except OSError as error:
        if published:
            raise CommitUncertain('new output exists; inspect it before retrying publication') from error
        raise


def run(*args):
    return subprocess.run([str(v) for v in args], check=True, capture_output=True, timeout=60).stdout


@contextmanager
def signing(key, trusted):
    trusted = apt.full_fingerprint(trusted)
    ordinary(key, 1024 * 1024)
    with tempfile.TemporaryDirectory(prefix='foundation channel signing ') as temporary:
        home = Path(temporary)
        home.chmod(0o700)
        try:
            run('gpg', '--batch', '--homedir', home, '--import', key)
            public = run('gpg', '--batch', '--homedir', home, '--export', trusted)
            public_path = home / 'public.gpg'
            public_path.write_bytes(public)
            if apt.fingerprint(public_path) != trusted:
                raise ValueError('signing key does not match independently trusted identity')
            def sign(data):
                source, signature = home / 'input', home / 'signature'
                source.write_bytes(data)
                signature.unlink(missing_ok=True)
                run('gpg', '--batch', '--homedir', home, '--pinentry-mode', 'loopback', '--passphrase', '',
                    '--local-user', trusted, '--digest-algo', 'SHA256', '--output', signature, '--detach-sign', source)
                return signature.read_bytes()
            yield public, sign
        finally:
            run('gpgconf', '--homedir', home, '--kill', 'all')


def verify_signature(data, signature, public, trusted):
    trusted = apt.full_fingerprint(trusted)
    with tempfile.TemporaryDirectory(prefix='foundation channel verify ') as temporary:
        home = Path(temporary)
        for name, value in (('data', data), ('signature', signature), ('public.gpg', public)):
            (home / name).write_bytes(value)
        if apt.fingerprint(home / 'public.gpg') != trusted:
            raise ValueError('untrusted channel key')
        status = run('gpgv', '--homedir', home, '--status-fd=1', '--keyring', home / 'public.gpg', home / 'signature', home / 'data').decode()
        valid = [line.split() for line in status.splitlines() if line.startswith('[GNUPG:] VALIDSIG ')]
        if len(valid) != 1 or trusted not in (valid[0][2], valid[0][-1]):
            raise ValueError('signature does not match the trusted primary identity')


def database(files, specs, include_files=False):
    rows = {}
    for name, spec in specs.items():
        package_path = next(path for path in files if path.startswith('packages/' + name + '/arch/') and path.endswith('.pkg.tar.gz'))
        data = files[package_path][0]
        signature = files[package_path + '.sig'][0]
        package_name = 'software-foundation-' + spec['backend'] + '-bin'
        version = spec['version'] + '-' + str(spec['package_release'])
        with tarfile.open(fileobj=io.BytesIO(data), mode='r:gz') as archive:
            members = [entry for entry in archive.getmembers() if not entry.name.startswith('.')]
        fields = {'FILENAME': Path(package_path).name, 'NAME': package_name, 'BASE': package_name,
                  'VERSION': version, 'ARCH': spec['architecture'], 'CSIZE': str(len(data)),
                  'ISIZE': str(sum(entry.size for entry in members)), 'BUILDDATE': '0',
                  'PACKAGER': 'Software Foundation contributors',
                  'SHA256SUM': digest(data), 'PGPSIG': base64.b64encode(signature).decode(),
                  'DESC': 'Generic prebuilt application', 'LICENSE': 'LicenseRef-Foundation-Bundled',
                  'DEPENDS': '\n'.join(spec['runtime_dependencies']['arch'])}
        rows[package_name + '-' + version + '/desc'] = (''.join('%' + key + '%\n' + value + '\n\n' for key, value in fields.items()).encode(), 0o644)
        if include_files:
            listing = '%FILES%\n' + ''.join(entry.name.rstrip('/') + ('/' if entry.isdir() else '') + '\n'
                                           for entry in sorted(members, key=lambda entry: entry.name)) + '\n'
            rows[package_name + '-' + version + '/files'] = (listing.encode(), 0o644)
    return tar_bytes(rows)


def assemble(groups, output, key, trusted, sequence, valid_days=30):
    if type(sequence) is not int or not 1 <= sequence < 2**63 or type(valid_days) is not int or not 1 <= valid_days <= 90:
        raise ValueError('positive sequence and bounded validity required')
    files, specs, architectures = {}, {}, set()
    for group in groups:
        actual = tree(group)
        expected, spec = expected_package(actual)
        if actual != expected:
            raise ValueError('package contains changed bytes or unexpected hooks/files')
        identity = spec['architecture'] + '-' + spec['backend']
        if identity in specs:
            raise ValueError('duplicate target identity')
        specs[identity] = spec
        architectures.add(spec['architecture'])
        files.update({'packages/' + identity + '/' + path: value for path, value in actual.items()})
        for path, value in actual.items():
            if path.startswith('gentoo/'):
                if path in files and files[path] != value:
                    raise ValueError('conflicting overlay recipe')
                files[path] = value
    if len(architectures) != 1:
        raise ValueError('use one complete channel per target architecture')
    files['gentoo/profiles/repo_name'] = (b'software-foundation-bin\n', 0o644)
    files['gentoo/metadata/layout.conf'] = (b'masters = gentoo\nrepo-name = software-foundation-bin\nthin-manifests = false\n', 0o644)
    now = datetime.now(timezone.utc).replace(microsecond=0)
    with signing(key, trusted) as (public, sign):
        files['public.gpg'] = (public, 0o644)
        for path in list(files):
            if path.endswith('.pkg.tar.gz'):
                data = files[path][0]
                signature = sign(data)
                files[path + '.sig'] = (signature, 0o644)
                files['arch/' + Path(path).name] = files[path]
                files['arch/' + Path(path).name + '.sig'] = (signature, 0o644)
        for suffix in ('db', 'files'):
            db = database(files, specs, include_files=suffix == 'files')
            files['arch/software-foundation.' + suffix] = (db, 0o644)
            files['arch/software-foundation.' + suffix + '.sig'] = (sign(db), 0o644)
        metadata = {'schema_version': 1, 'sequence': sequence, 'architecture': architectures.pop(),
                    'created': now.isoformat(), 'expires': (now + timedelta(days=valid_days)).isoformat(),
                    'signing_fingerprint': apt.full_fingerprint(trusted), 'packages': specs, 'files': inventory(files)}
        files['channel.json'] = (encoded(metadata), 0o644)
        files['channel.json.sig'] = (sign(files['channel.json'][0]), 0o644)
    verify_files(files, trusted)
    publish_new(Path(output).absolute(), files)
    return metadata


def verify_files(files, trusted, check_dates=True):
    if not CONTROL | {'public.gpg'} <= files.keys():
        raise ValueError('incomplete signed channel')
    verify_signature(files['channel.json'][0], files['channel.json.sig'][0], files['public.gpg'][0], trusted)
    metadata = document(files['channel.json'][0])
    if (set(metadata) != {'schema_version', 'sequence', 'architecture', 'created', 'expires', 'signing_fingerprint', 'packages', 'files'}
            or type(metadata['schema_version']) is not int or metadata['schema_version'] != 1 or type(metadata['sequence']) is not int or not 1 <= metadata['sequence'] < 2**63
            or metadata['architecture'] not in ARCHES or metadata['signing_fingerprint'] != apt.full_fingerprint(trusted)):
        raise ValueError('invalid channel identity')
    created, expires = (datetime.fromisoformat(metadata[name]) for name in ('created', 'expires'))
    if created.utcoffset() != timedelta(0) or expires.utcoffset() != timedelta(0) or not created < expires <= created + timedelta(days=90):
        raise ValueError('invalid channel validity interval')
    if check_dates and (expires <= datetime.now(timezone.utc) or created > datetime.now(timezone.utc) + timedelta(minutes=5)):
        raise ValueError('expired or future channel')
    if inventory({name: row for name, row in files.items() if name not in CONTROL}) != metadata['files']:
        raise ValueError('signed complete inventory differs')
    if not isinstance(metadata['packages'], dict) or not metadata['packages']:
        raise ValueError('empty package inventory')
    allowed = set(CONTROL) | {'public.gpg', 'arch/software-foundation.db', 'arch/software-foundation.db.sig',
                            'arch/software-foundation.files', 'arch/software-foundation.files.sig',
                            'gentoo/profiles/repo_name', 'gentoo/metadata/layout.conf'}
    overlay = {'gentoo/profiles/repo_name': (b'software-foundation-bin\n', 0o644),
               'gentoo/metadata/layout.conf': (b'masters = gentoo\nrepo-name = software-foundation-bin\nthin-manifests = false\n', 0o644)}
    for identity, spec in metadata['packages'].items():
        validate_spec(spec)
        if identity != spec['architecture'] + '-' + spec['backend'] or spec['architecture'] != metadata['architecture']:
            raise ValueError('package/channel target mismatch')
        prefix = 'packages/' + identity + '/'
        group = {name[len(prefix):]: value for name, value in files.items() if name.startswith(prefix) and not name.endswith('.pkg.tar.gz.sig')}
        expected, _ = expected_package(group)
        if group != expected or document(group['spec.json'][0]) != spec:
            raise ValueError('recipe/payload differs from retained package')
        allowed.update(prefix + name for name in group)
        for name, value in group.items():
            if name.startswith('gentoo/'):
                if name in overlay and overlay[name] != value:
                    raise ValueError('conflicting overlay')
                overlay[name] = value
            if name.endswith('.pkg.tar.gz'):
                copied = 'arch/' + Path(name).name
                sig = prefix + name + '.sig'
                if files.get(copied) != value or files.get(copied + '.sig') != files.get(sig):
                    raise ValueError('Arch package mirror differs')
                verify_signature(value[0], files[sig][0], files['public.gpg'][0], trusted)
                allowed.update((copied, copied + '.sig', sig))
    if any(files.get(name) != value for name, value in overlay.items()):
        raise ValueError('overlay import incomplete or changed')
    allowed.update(overlay)
    if set(files) != allowed:
        raise ValueError('unexpected hooks or incomplete native repository inventory')
    for suffix in ('db', 'files'):
        path = 'arch/software-foundation.' + suffix
        if files[path][0] != database(files, metadata['packages'], include_files=suffix == 'files'):
            raise ValueError('native repository metadata differs')
        verify_signature(files[path][0], files[path + '.sig'][0], files['public.gpg'][0], trusted)
    return metadata


def verify(directory, trusted):
    return verify_files(tree(directory), trusted)


def advance(previous, candidate):
    if candidate['architecture'] != previous['architecture'] or candidate['signing_fingerprint'] != previous['signing_fingerprint']:
        raise ValueError('channel target or trusted identity changed')
    if candidate['sequence'] < previous['sequence'] or (candidate['sequence'] == previous['sequence'] and candidate != previous):
        raise ValueError('rollback or same-sequence replacement')
    for name, spec in previous['packages'].items():
        after = candidate['packages'].get(name)
        if after is None or version_key(after) < version_key(spec) or (version_key(after) == version_key(spec) and after != spec):
            raise ValueError('package removal, downgrade or same-version replacement')


def sync(source, location, trusted):
    """Atomically activate a fully authenticated retained generation on POSIX.

    Old generations are retained, never deleted. Failure before replacement
    preserves current; uncertainty after replacement requires reading current.
    """
    if os.name != 'posix':
        raise ValueError('atomic symlink activation needs the qualified POSIX profile')
    import fcntl
    location = Path(location).absolute()
    if location == location.parent or location.resolve() != location or location.is_symlink():
        raise ValueError('activation destination must be physical and dedicated')
    files = tree(source)
    candidate = verify_files(files, trusted)
    location.mkdir(exist_ok=True)
    sync_directory(location.parent)
    lock_path = location / '.sync.lock'
    with os.fdopen(os.open(lock_path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600), 'r+b') as locked:
        if os.fstat(locked.fileno()).st_nlink != 1:
            raise ValueError('lock has foreign aliases')
        fcntl.flock(locked, fcntl.LOCK_EX)
        if (not stat.S_ISREG(os.fstat(locked.fileno()).st_mode)
                or os.fstat(locked.fileno()).st_ino != lock_path.stat().st_ino):
            raise ValueError('activation lock identity changed')
        unknown = {p.name for p in location.iterdir()} - {'.sync.lock', 'current', 'generations'}
        if unknown:
            raise ValueError('foreign files in activation root')
        generations = location / 'generations'
        if generations.is_symlink():
            raise ValueError('linked generation store')
        generations.mkdir(exist_ok=True)
        current = location / 'current'
        previous = None
        if current.is_symlink():
            target = os.readlink(current)
            if not re.fullmatch(r'generations/[1-9][0-9]*-[0-9a-f]{64}', target):
                raise ValueError('unmanaged activation pointer')
            previous = verify_files(tree(location / target), trusted, check_dates=False)
            if target != 'generations/' + str(previous['sequence']) + '-' + digest(encoded(previous)):
                raise ValueError('generation identity differs from signed metadata')
            advance(previous, candidate)
            if candidate == previous:
                return {'changed': False, 'sequence': previous['sequence'], 'current': target}
        elif current.exists():
            raise ValueError('activation pointer is not managed')
        identity = str(candidate['sequence']) + '-' + digest(encoded(candidate))
        destination = generations / identity
        if destination.exists():
            if tree(destination) != files:
                raise ValueError('retained generation differs; refusing overwrite')
        else:
            publish_new(destination, files)
        # Revalidate the complete staged generation immediately before activation.
        verify_files(tree(destination), trusted)
        activated = False
        try:
            with tempfile.TemporaryDirectory(prefix='.activate-', dir=location) as temporary:
                pointer = Path(temporary) / 'current'
                pointer.symlink_to('generations/' + identity)
                sync_directory(pointer.parent)
                if previous is not None:
                    if verify_files(tree(location / os.readlink(current)), trusted, check_dates=False) != previous:
                        raise ValueError('active generation changed before commit')
                os.replace(pointer, current)
                activated = True
                sync_directory(location)
            sync_directory(location)
        except OSError as error:
            if activated:
                raise CommitUncertain('current was replaced; inspect it before retrying; older generations remain retained') from error
            raise
        return {'changed': True, 'sequence': candidate['sequence'], 'current': 'generations/' + identity}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    command = sub.add_parser('package')
    for name in ('archive', 'manifest', 'spec', 'output'):
        command.add_argument('--' + name, type=Path, required=True)
    command = sub.add_parser('assemble')
    command.add_argument('groups', type=Path, nargs='+')
    command.add_argument('--output', type=Path, required=True)
    command.add_argument('--signing-key', type=Path, required=True)
    command.add_argument('--trusted-fingerprint', required=True)
    command.add_argument('--sequence', type=int, required=True)
    for action in ('verify', 'sync'):
        command = sub.add_parser(action)
        command.add_argument('source', type=Path)
        command.add_argument('--trusted-fingerprint', required=True)
        if action == 'sync':
            command.add_argument('--location', type=Path, required=True)
    args = parser.parse_args()
    if args.command == 'package':
        result = package(args.archive, args.manifest, args.spec, args.output)
    elif args.command == 'assemble':
        result = assemble(args.groups, args.output, args.signing_key, args.trusted_fingerprint, args.sequence)
    elif args.command == 'verify':
        result = verify(args.source, args.trusted_fingerprint)
    else:
        result = sync(args.source, args.location, args.trusted_fingerprint)
    print(json.dumps(result, sort_keys=True))


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError, tarfile.TarError, CommitUncertain) as error:
        print('Distribution channel: ' + str(error), file=sys.stderr)
        sys.exit(1)
