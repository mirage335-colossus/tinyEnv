#!/usr/bin/env python3
"""Native package-manager acceptance of exact, signed, already-built release bytes."""
import argparse
import ctypes
import io
import json
import os
from pathlib import Path
import platform
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
import time
import uuid
from urllib.parse import quote

import process_tree
from release_check import qualification_work

import distribution_release as release
import distro_client as client

IMAGES = {'apt-bookworm': ('apt', 'debian:bookworm'), 'apt-trixie': ('apt', 'debian:trixie'),
          'apt-ubuntu': ('apt', 'ubuntu:24.04'), 'arch': ('arch', 'archlinux:base'),
          'gentoo': ('gentoo', 'gentoo/stage3:latest')}


def matrix(target, distro="all", *, accept=False):
    if target not in release.TARGETS: raise ValueError('unsupported distribution target')
    if distro not in ('all', 'apt', 'arch', 'gentoo'): raise ValueError('unknown native distro selection')
    if accept and distro != 'all': raise ValueError('focused native diagnosis cannot accept a channel')
    # Official Arch Linux and the example Portage image are qualified on x86-64.
    names = list(IMAGES) if target == 'linux-x86_64' else ['apt-bookworm', 'apt-trixie', 'apt-ubuntu']
    if distro != 'all': names = [name for name in names if IMAGES[name][0] == distro]
    if not names: raise ValueError('native distro selection is unsupported for target')
    return {'include': [dict(id=name, kind=IMAGES[name][0], image=IMAGES[name][1], target=target,
        runner='ubuntu-24.04' if target == 'linux-x86_64' else 'ubuntu-24.04-arm') for name in names]}


def extract_channels(assets, output, manifest=None):
    channels = (client.extract_channels(assets, output, manifest) if manifest is not None else
                release.archive.extract(Path(assets)/'channels.tar.gz', output, max_bytes=release.distro.MAX_BYTES*2))
    # Only the fresh owned extraction is normalized. Payload file modes remain
    # authenticated by the signed channel and its native package inventories.
    channels.chmod(0o755)
    for path in channels.rglob('*'):
        if path.is_dir(): path.chmod(0o755)
    return channels


def expected_payload(channels, manifest, backend, kind):
    if kind == 'apt':
        metadata = release.archive.read_json(channels/'apt/repository.json')
        rows = [release.archive.read_json(channels/'apt'/row['receipt']) for row in metadata['packages']]
        architecture = release.TARGETS[manifest['request']['target']][1] if manifest.get('format') == client.PACKAGE_FORMAT else None
        matches = [row for row in rows if row['backend'] == backend and
                   (architecture is None or row['architecture'] == architecture)]
        if len(matches) != 1: raise ValueError('one exact APT backend receipt required')
        return matches[0]['payload']
    spec = manifest['specifications'][backend]
    group = channels/'native/packages'/(spec['architecture']+'-'+backend)
    generated, _ = release.distro.expected_package(release.distro.tree(group))
    packages = [value[0] for name, value in generated.items() if name.startswith('arch/') and name.endswith('.pkg.tar.gz')]
    if len(packages) != 1: raise ValueError('one exact native package required')
    expected = {}
    with tarfile.open(fileobj=io.BytesIO(packages[0]), mode='r:gz') as bundle:
        for entry in bundle:
            if not entry.isfile() or entry.name.startswith('.'): continue
            # Gentoo supplies license acceptance through the authenticated overlay;
            # private notices and every public launcher/manual remain mandatory.
            if kind == 'gentoo' and entry.name.startswith('usr/share/licenses/'): continue
            with bundle.extractfile(entry) as stream: data = stream.read()
            expected[entry.name] = {'sha256': release.distro.digest(data), 'size': len(data), 'mode': entry.mode}
    return expected


def verify_installed(root, expected, backend):
    root = Path(root)
    for name, row in expected.items():
        release.archive.relative(name); path = root/name
        data, mode = release.distro.ordinary(path)
        if {'sha256': release.distro.digest(data), 'size': len(data), 'mode': mode} != row:
            raise ValueError('installed payload differs: '+name)
    private = root/'opt/software-foundation'/backend
    actual = {path.relative_to(root).as_posix() for path in private.rglob('*') if path.is_file() or path.is_symlink()}
    declared = {name for name in expected if name.startswith('opt/software-foundation/'+backend+'/')}
    if actual != declared: raise ValueError('installed private tree contains missing or foreign files')
    return len(expected)


def install_arch(names, version, run, query_path):
    """Prove the package database advanced even when payload bytes are unchanged."""
    run('pacman', '-Syu', '--noconfirm', *names)
    run('pacman', '-Syu', '--noconfirm')
    raw = run('pacman', '-Q', *names, capture=query_path)
    rows = [line.split() for line in raw.decode('utf-8').splitlines()]
    if (len(rows) != len(names) or any(len(row) != 2 for row in rows)
            or len({row[0] for row in rows}) != len(names)
            or dict(rows) != dict.fromkeys(names, version)):
        raise ValueError('installed Arch package versions differ from signed channel')
    for name in names: run('pacman', '-Qkk', name)
    return dict(rows)


def supervised(argv, stream, *, timeout, env=None):
    """Do not release an evidence stream while command descendants can write."""
    owner = process_tree.launch(argv, Path.cwd(), stream, env=env)
    try:
        status = owner.wait(timeout=timeout)
        owner.finish()
        if status: raise subprocess.CalledProcessError(status, argv)
    finally:
        owner.close()


def recorded_command(argv, evidence, timings, *, capture=None, env=None):
    """Persist elapsed time even for a failed native prerequisite or package step."""
    argv = [str(arg) for arg in argv]
    row = dict(command=argv, started_utc=time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()), status='failed')
    start = time.monotonic()
    try:
        with (evidence/'native.log').open('ab') as stream:
            stream.write(('COMMAND '+json.dumps(argv)+'\n').encode()); stream.flush()
            if capture is None:
                supervised(argv, stream, timeout=900, env=env)
                raw = None
            else:
                with capture.open('xb') as captured:
                    supervised(argv, captured, timeout=900, env=env)
                raw = capture.read_bytes(); stream.write(raw)
        row['status'] = 'passed'
        return raw
    finally:
        row['seconds'] = round(time.monotonic()-start, 6)
        timings.append(row)
        release.archive.write_json(evidence/'command-timings.json', timings)


def require_disposable():
    if (not hasattr(os, 'geteuid') or os.geteuid() != 0 or not Path('/.dockerenv').is_file() or
            os.environ.get('FOUNDATION_DISPOSABLE_CHECK') != '1'):
        raise ValueError('native package installation requires an explicitly disposable root container')


def keyring_subreaper():
    """Only call in a dedicated single-threaded keyring worker, before spawning."""
    if not sys.platform.startswith('linux') or process_tree._direct_children():
        raise process_tree.ProcessTreeError('keyring worker requires a fresh Linux child process')
    api = ctypes.CDLL(None, use_errno=True)
    api.prctl.argtypes = [ctypes.c_int, ctypes.c_ulong, ctypes.c_ulong, ctypes.c_ulong, ctypes.c_ulong]
    api.prctl.restype = ctypes.c_int
    if api.prctl(36, 1, 0, 0, 0) != 0:  # PR_SET_CHILD_SUBREAPER
        raise process_tree.ProcessTreeError('keyring child-subreaper setup failed')


def reap_keyring_children(timeout):
    """Join adopted services after scoped shutdown; never signal arbitrary PIDs."""
    deadline = time.monotonic() + timeout
    reaped = []
    while True:
        try:
            pid, status = os.waitpid(-1, os.WNOHANG)
        except ChildProcessError:
            return reaped  # ECHILD proves that no owned daemon can create writers.
        if pid:
            reaped.append({'pid': pid, 'returncode': os.waitstatus_to_exitcode(status)})
            if len(reaped) > 64:
                raise process_tree.ProcessTreeError('unexpected keyring child count; retain output ownership')
            continue
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise process_tree.ProcessTreeError('keyring descendants did not exit after scoped shutdown; retain output ownership')
        time.sleep(min(.01, remaining))


def keyring_session(home, commands, *, timeout=840, cleanup_timeout=30):
    """Keep this dedicated worker alive through commands, service stop and join.

    The existing strict outer ProcessTree owns the worker and catches any failed
    cleanup. An established pacman home is private to the disposable container;
    keeping it preserves the official distribution keys needed by pacman -Syu.
    """
    home = Path(home).resolve(strict=True)
    if not home.is_dir(): raise ValueError('keyring home must be a directory')
    keyring_subreaper()
    deadline = time.monotonic() + timeout
    failure = None
    try:
        for argv in commands:
            print('COMMAND ' + json.dumps([str(arg) for arg in argv]), flush=True)
            remaining = deadline - time.monotonic()
            if remaining <= 0: raise subprocess.TimeoutExpired(argv, timeout)
            subprocess.run([str(arg) for arg in argv], check=True, timeout=remaining)
    except BaseException as error:
        failure = error
    cleanup = ['gpgconf', '--homedir', str(home), '--kill', 'all']
    errors = []
    cleanup_deadline = time.monotonic() + cleanup_timeout
    try:
        print('COMMAND ' + json.dumps(cleanup), flush=True)
        subprocess.run(cleanup, check=True, timeout=cleanup_timeout)
    except BaseException as error:
        errors.append(error)
    try:
        reaped = reap_keyring_children(max(0, cleanup_deadline - time.monotonic()))
        if any(row['returncode'] for row in reaped):
            raise process_tree.ProcessTreeError('keyring service exited unsuccessfully: ' + json.dumps(reaped))
    except BaseException as error:
        errors.append(error)
    if errors:
        message = '; '.join(str(error) for error in errors)
        if failure is not None: message = str(failure) + '; ' + message
        raise process_tree.ProcessTreeError('keyring cleanup failed: ' + message) from (failure or errors[0])
    if failure is not None: raise failure
    return dict(kind='arch-keyring', status='passed', home=str(home), cleanup=cleanup, joined=reaped)


def prepare_arch_keyring(key, trusted):
    require_disposable()
    home = Path('/etc/pacman.d/gnupg')
    home.mkdir(mode=0o700, parents=True, exist_ok=True)
    trusted = release.distro.apt.full_fingerprint(trusted)
    return keyring_session(home, [
        ['pacman-key', '--gpgdir', home, '--init'],
        ['pacman-key', '--gpgdir', home, '--add', Path(key).resolve(strict=True)],
        ['pacman-key', '--gpgdir', home, '--lsign-key', trusted]])


def image_identity(raw):
    values = release.delivery.parse(raw)
    if not isinstance(values, list) or len(values) != 1 or not isinstance(values[0], dict):
        raise ValueError('one exact inspected container image required')
    value = values[0].get('Id', '')
    if not value.startswith('sha256:') or not release.delivery.SHA.fullmatch(value[7:]):
        raise ValueError('invalid inspected container image identity')
    return value


def remove_owned_container(name, token):
    """Stop only the uniquely named, labeled container created by this invocation."""
    ids = subprocess.check_output(['docker', 'ps', '-aq', '--filter', 'name=^/'+name+'$'], text=True).split()
    if not ids: return
    if len(ids) != 1: raise ValueError('ambiguous owned container; preserve evidence')
    info = release.delivery.parse(subprocess.check_output(['docker', 'inspect', ids[0]], text=True))
    if (len(info) != 1 or info[0].get('Name') != '/'+name or
            info[0].get('Config', {}).get('Labels', {}).get('foundation.native-check') != token):
        raise ValueError('container ownership changed; preserve it')
    subprocess.run(['docker', 'rm', '--force', '--volumes', ids[0]], check=True, timeout=60)


def require_version_upgrade(previous, candidate):
    client.advance(previous, candidate)
    if previous['request']['sequence'] >= candidate['request']['sequence']:
        raise ValueError('upgrade requires an older exact published channel')
    if any(release.distro.version_key(candidate['specifications'][backend]) <=
           release.distro.version_key(spec)
           for backend, spec in previous['specifications'].items()):
        raise ValueError('upgrade requires a newer package version or package release for every existing backend')


def gentoo_license_config(backends):
    """Portage accepts exact license names, not shell patterns in license tokens."""
    return ''.join('app-misc/software-foundation-'+backend+'-bin Foundation-Bundled-'+backend+'\n'
                   for backend in backends)


def gentoo_install_options():
    """Parallel native package merges only in an explicitly disposable check host."""
    require_disposable()
    from build_capacity import default_jobs
    jobs = default_jobs()
    if type(jobs) is not int or jobs < 1: raise ValueError('positive native package job budget required')
    return ['--jobs=' + str(jobs)]


def prepare_gentoo_runtime(value, root, run):
    """Configure only required host capabilities, then resolve binaries before refresh."""
    dependencies = sorted({atom for spec in value['specifications'].values()
                           for atom in spec['runtime_dependencies']['gentoo']})
    directory = Path(root)/'etc/portage/package.use'
    directory.mkdir(parents=True, exist_ok=True)
    # Mesa's X dependency is conditional on the host's libglvnd USE selection.
    # Keep it per-package; a global X flag changes unrelated binary choices.
    flags = 'media-libs/libglvnd X\n' if 'media-libs/mesa[X,opengl]' in dependencies else ''
    (directory/'software-foundation').write_text(flags)
    run('emerge', '--pretend', '--getbinpkgonly', '--usepkgonly',
        '--binpkg-respect-use=y', '--oneshot', '--with-bdeps=n', *dependencies)


def native(directory, policy, trusted, kind, evidence, *, previous=None, target=None,
           format=None, previous_format=None):
    require_disposable()
    if kind not in ('apt', 'arch', 'gentoo'): raise ValueError('unknown package frontend')
    manifest = client.verify_channel(directory, policy, trusted, target=target, format=format)
    target = manifest['request']['target']
    machine = {'amd64': 'x86_64', 'arm64': 'aarch64'}.get(platform.machine().lower(), platform.machine().lower())
    if target != 'linux-'+machine: raise ValueError('native package target differs from execution processor')
    if kind != 'apt' and target != 'linux-x86_64': raise ValueError('this native frontend image is qualified only on x86-64')
    evidence = Path(evidence); evidence.mkdir(parents=True, exist_ok=False)
    commands, timings = [], []
    def run(*argv, capture=None):
        commands.append([str(arg) for arg in argv])
        environment = dict(os.environ, DEBIAN_FRONTEND='noninteractive', LC_ALL='C.UTF-8')
        return recorded_command(commands[-1], evidence, timings, capture=capture, env=environment)
    with qualification_work(evidence) as work:
        rounds = []
        if previous:
            old = client.verify_channel(previous, policy, trusted, target=target, format=previous_format)
            require_version_upgrade(old, manifest)
            rounds.append((Path(previous), old))
        rounds.append((Path(directory), manifest)); installed = []; package_versions = []
        for index, (assets, value) in enumerate(rounds):
            channels = extract_channels(assets, work/('channels-'+str(index)), value)
            url = ('https://github.com/' + value['request']['repository'] + '/releases/download/' +
                   quote(value['tag'], safe='') + '/' if value.get('format') == client.PACKAGE_FORMAT
                   else release.base_url(value['request']))
            backends = value['backends']
            if kind == 'apt':
                # Minimal images may exclude manuals; qualification must inspect
                # the complete installed package, including its public man pages.
                Path('/etc/dpkg/dpkg.cfg.d/zz-foundation-manuals').write_text('path-include=/usr/share/man/*\n')
                key = Path('/etc/apt/keyrings/software-foundation.gpg'); key.parent.mkdir(exist_ok=True)
                shutil.copyfile(assets/'archive-keyring.gpg', key); key.chmod(0o644)
                Path('/etc/apt/sources.list.d/software-foundation.sources').write_text(
                    f'Types: deb\nURIs: {url}\nSuites: ./\nArchitectures: {release.TARGETS[target][1]}\nSigned-By: {key}\n')
                names = ['software-foundation-'+backend+'='+value['request']['version']+'+r'+str(value['request']['package_release']) for backend in backends]
                run('sh', Path(__file__).with_name('ci-apt.sh'), 'install', *names)
                run('sh', Path(__file__).with_name('ci-apt.sh'), 'install', *names)
            elif kind == 'arch':
                if index == 0:
                    run(sys.executable, Path(__file__).resolve(), 'arch-keyring',
                        '--directory', assets, '--trusted-fingerprint', trusted)
                    with Path('/etc/pacman.conf').open('a') as out:
                        out.write('\n[options]\nNoExtract = !usr/share/man !usr/share/man/ !usr/share/man/man1 !usr/share/man/man1/ !usr/share/man/man7 !usr/share/man/man7/ !usr/share/man/man1/foundation-* !usr/share/man/man7/software-foundation-*\nInclude = /etc/pacman.d/software-foundation.conf\n')
                Path('/etc/pacman.d/software-foundation.conf').write_text(f'[software-foundation]\nSigLevel = Required DatabaseRequired\nServer = {url.rstrip("/")}\n')
                names = ['software-foundation-'+backend+'-bin' for backend in backends]
                version = value['request']['version']+'-'+str(value['request']['package_release'])
                observed = install_arch(names, version, run, evidence/('arch-versions-'+str(index)+'.txt'))
                package_versions.append(dict(tag=value['tag'], packages=observed))
            else:
                # The signed recipes only wrap the retained archive; missing host
                # prerequisites must come from binary repositories, never compilation.
                prepare_gentoo_runtime(value, '/', run)
                config = dict(schema_version=1, repository=value['request']['repository'], target=target,
                    trusted_fingerprint=trusted, policy_sha256=release.archive.digest(policy),
                    selection={'tag': value['tag'], 'manifest_sha256': client.manifest_digest(assets)},
                    location='/var/lib/software-foundation-channel')
                if value.get('format') == client.PACKAGE_FORMAT:
                    config['selection']['format'] = client.PACKAGE_FORMAT
                config_path = Path('/etc/software-foundation-channel.json')
                config_path.write_bytes(release.archive.encoded(config))
                client.refresh(config, policy, prepared=assets)
                client.install_portage(config_path, Path(client.__file__))
                run('emaint', 'sync', '-r', 'software-foundation-bin')
                overlay = Path(config['location'])/'current/channels/native/gentoo'
                for folder in ('package.accept_keywords', 'package.license'): (Path('/etc/portage')/folder).mkdir(exist_ok=True)
                Path('/etc/portage/package.accept_keywords/software-foundation').write_text('app-misc/software-foundation-* ~amd64\n')
                Path('/etc/portage/package.license/software-foundation').write_text(gentoo_license_config(backends))
                # Disable only package-byte transformations in this disposable host.
                os.environ['FEATURES'] = subprocess.check_output(['portageq', 'envvar', 'FEATURES'], text=True).strip()+' -compressdebug parallel-install -merge-sync'
                atoms = []
                for backend in backends:
                    files = list((overlay/'app-misc'/('software-foundation-'+backend+'-bin')).glob('*.ebuild'))
                    if len(files) != 1: raise ValueError('one exact binary ebuild required')
                    run('ebuild', files[0], 'package')
                    atoms.append('=app-misc/'+files[0].stem)
                # All binary wrappers exist before one dependency-resolution/merge
                # operation. Every backend/version is still checked individually.
                run('emerge', '--getbinpkgonly', '--usepkgonly', '--binpkg-respect-use=y',
                    '--oneshot', '--with-bdeps=n', *gentoo_install_options(), *atoms)
                for atom in atoms: run('portageq', 'has_version', '/', atom)
                run('emaint', 'sync', '-r', 'software-foundation-bin')
            installed = []
            for backend in backends:
                expected = expected_payload(channels, value, backend, kind)
                count = verify_installed('/', expected, backend)
                executable = 'foundation-cli'+('-'+backend if backend != 'core' else '')
                run(executable, '--self-check')
                if backend != 'core': run('foundation-gui-'+('web' if backend == 'hosted-web' else backend), '--self-check')
                if backend == 'hosted-web':
                    run('python3', Path(__file__).resolve().parents[1]/'gui/tests/web_host_test.py',
                        '/opt/software-foundation/hosted-web/share/software-foundation/web/serve.py',
                        '/usr/bin/foundation-gui-web')
                installed.append({'backend': backend, 'files': count, 'payload_sha256': release.distro.digest(release.distro.encoded(expected))})
        names = ['software-foundation-'+backend+('' if kind == 'apt' else '-bin') for backend in manifest['backends']]
        if kind == 'apt': run('apt-get', 'purge', '-y', *names)
        elif kind == 'arch': run('pacman', '-R', '--noconfirm', *names)
        else: run('emerge', '--unmerge', *('app-misc/'+name for name in names))
        for backend in manifest['backends']:
            private = Path('/opt/software-foundation')/backend
            if private.exists() and any(private.rglob('*')): raise ValueError('private files remain after removal')
    result = dict(schema_version=1, status='passed', kind=kind, target=target, tag=manifest['tag'],
        manifest_sha256=client.manifest_digest(directory),
        checks=['signature', 'published-download', 'install', 'repeated-update', 'exact-payload', 'self-check', 'remove'],
        upgrade_from=rounds[0][1]['tag'] if len(rounds) == 2 else None,
        upgrade_manifest_sha256=client.manifest_digest(rounds[0][0]) if len(rounds) == 2 else None,
        package_versions=package_versions, backends=installed,
        id=os.environ.get('CHECK_ID'), image=os.environ.get('CHECK_IMAGE'), image_id=os.environ.get('CHECK_IMAGE_ID'),
        os_release=Path('/etc/os-release').read_text(),
        source_commit=os.environ.get('GITHUB_SHA'), run_id=os.environ.get('GITHUB_RUN_ID'),
        attempt=os.environ.get('GITHUB_RUN_ATTEMPT'), commands=commands, command_timings=timings)
    if manifest.get('format') == client.PACKAGE_FORMAT:
        result['format'] = client.PACKAGE_FORMAT
        result['upgrade_format'] = rounds[0][1].get('format', 'distribution') if len(rounds) == 2 else None
    release.archive.write_json(evidence/'result.json', result)
    return result


def selection(raw):
    if not isinstance(raw, str) or len(raw.encode()) > 16384: raise ValueError('bounded exact channel selection required')
    value = release.delivery.parse(raw)
    if (not isinstance(value, dict) or
            set(value) not in ({'tag', 'manifest_sha256', 'target'}, {'tag', 'manifest_sha256', 'target', 'format'}) or
            'format' in value and value['format'] != client.PACKAGE_FORMAT):
        raise ValueError('exact channel tag, manifest digest and target required')
    release.delivery.valid_name(value['tag'])
    if value['target'] not in release.TARGETS or not release.delivery.SHA.fullmatch(str(value['manifest_sha256'])):
        raise ValueError('invalid channel target or digest')
    return value


def fetch_selected(selected, output, policy, trusted, repository, *, transport=None, reuse=None):
    """Fetch the exact native target without routing integrated bytes via legacy tags."""
    selected = selection(release.distro.encoded(selected).decode())
    return client.fetch_channel(selected, repository, output, policy, trusted,
                                transport=transport, reuse=reuse)


def private_display(directory):
    from screenshots import private_display as owned
    return owned(directory)


def container(root, check_id, environment):
    root = Path(root).resolve(strict=True)
    output = root/'build/distro-evidence'; output.mkdir(parents=True, exist_ok=False)
    # Display service is independently owned by this job, not installed from a
    # tested distribution's optional source-only display-wrapper packages.
    with private_display(output/'display') as display:
        return container_with_display(root, check_id, environment, display)


def container_with_display(root, check_id, environment, display):
    root = Path(root).resolve(strict=True); selected = selection(environment['CHANNEL'])
    rows = [row for row in matrix(selected['target'])['include'] if row['id'] == check_id]
    if len(rows) != 1: raise ValueError('native check is not in selected matrix')
    row = rows[0]
    if environment.get('CHECK_IMAGE') != row['image'] or environment.get('CHECK_KIND') != row['kind']:
        raise ValueError('native execution image or kind differs from plan')
    if ':' in str(root): raise ValueError('unsupported container source path')
    output = root/'build/distro-evidence'
    token = uuid.uuid4().hex
    name = 'foundation-native-'+token; snapshot_name = name+'-snapshot'
    number = display['DISPLAY'].removeprefix(':')
    if not number.isdecimal(): raise ValueError('private local display number required')
    socket = '/tmp/.X11-unix/X'+number
    args = ['docker', 'create', '--name', name, '--label', 'foundation.native-check='+token, '--init',
        '--hostname', platform.node(), '-e', 'DISPLAY='+display['DISPLAY'],
        '-e', 'XAUTHORITY=/run/foundation-Xauthority', '-e', 'LIBGL_ALWAYS_SOFTWARE=1',
        '-e', 'SDL_VIDEODRIVER=x11', '-e', 'REV_SCALE=1',
        '--mount', f'type=bind,source={socket},target={socket},readonly',
        '--mount', 'type=bind,source='+display['XAUTHORITY']+',target=/run/foundation-Xauthority,readonly',
        '-e', 'FOUNDATION_DISPOSABLE_CHECK=1',
        '-e', 'PYTHONDONTWRITEBYTECODE=1', '-e', 'PYTHONUTF8=1', '-e', 'TRUSTED_FINGERPRINT',
        '-e', 'GITHUB_SHA', '-e', 'GITHUB_RUN_ID', '-e', 'GITHUB_RUN_ATTEMPT', '-e', 'CHECK_ID', '-e', 'CHECK_IMAGE',
        '--mount', f'type=bind,source={root},target=/source,readonly',
        '--mount', f'type=bind,source={output},target=/evidence', '-w', '/source']
    commands = {
        'apt': 'sh tools/ci-apt.sh install ca-certificates python3 gnupg gpgv dpkg-dev binutils',
        'arch': 'pacman -Syu --noconfirm --needed python gnupg binutils dpkg',
        'gentoo': 'export FEATURES="$(portageq envvar FEATURES) parallel-install -merge-sync"\nemerge --getbinpkgonly --usepkgonly --binpkg-respect-use=y --oneshot --with-bdeps=n --jobs="$(python3 -B tools/build_capacity.py)" app-crypt/gnupg app-arch/dpkg'
    }
    snapshot = None
    try:
        subprocess.run(['docker', 'pull', row['image']], check=True)
        image = subprocess.check_output(['docker', 'image', 'inspect', row['image']], text=True)
        image_id = image_identity(image)
        (output/'image.json').write_text(image)
        args += ['-e', 'CHECK_IMAGE_ID='+image_id]
        if row['kind'] == 'gentoo':
            subprocess.run(['docker', 'pull', 'gentoo/portage:latest'], check=True)
            snapshot_image = subprocess.check_output(['docker', 'image', 'inspect', 'gentoo/portage:latest'], text=True)
            (output/'portage-image.json').write_text(snapshot_image)
            snapshot = subprocess.check_output(['docker', 'create', '--name', snapshot_name, '--label', 'foundation.native-check='+token, '-v', '/var/db/repos/gentoo', image_identity(snapshot_image), '/bin/true'], text=True).strip()
            if not snapshot or any(c not in '0123456789abcdef' for c in snapshot): raise ValueError('invalid disposable snapshot identity')
            args += ['--volumes-from', snapshot+':ro']
        script = commands[row['kind']] + '\nexec python3 -B tools/distro_check.py native --directory /source/build/channels/current --policy /source/docs/release-policy.json --trusted-fingerprint "$TRUSTED_FINGERPRINT" --kind '+row['kind']+' --evidence /evidence/native'
        if selected.get('format') == client.PACKAGE_FORMAT:
            script += ' --format '+client.PACKAGE_FORMAT+' --target '+selected['target']
        if environment.get('PREVIOUS'):
            prior = selection(environment['PREVIOUS'])
            if prior['target'] != selected['target']: raise ValueError('native upgrade predecessor differs')
            script += ' --previous /source/build/channels/previous'
            if prior.get('format') == client.PACKAGE_FORMAT: script += ' --previous-format '+client.PACKAGE_FORMAT
        with (output/'container.log').open('wb') as stream:
            supervised([*args, image_id, 'bash', '-euc', script], stream, timeout=120, env=environment)
            # A Gentoo upgrade executes two complete verified channel rounds.
            # Keep individual command limits and every other native scope unchanged.
            duration = 9000 if row['kind'] == 'gentoo' and environment.get('PREVIOUS') else 4500
            supervised(['docker', 'start', '--attach', name], stream, timeout=duration)
    finally:
        errors = []
        for owned in (name, snapshot_name):
            try: remove_owned_container(owned, token)
            except Exception as error: errors.append(str(error))
        if errors: raise RuntimeError('container cleanup is uncertain: '+'; '.join(errors))
        # Confirm server-side writers stopped before reassigning the evidence mount.
        if output.exists():
            subprocess.run(['sudo', 'chown', '-R', str(os.getuid())+':'+str(os.getgid()), str(output)], check=True)


def qualification(selected, records, environment):
    selected = selection(release.distro.encoded(selected).decode())
    prior = selection(environment['PREVIOUS']) if environment.get('PREVIOUS') else None
    if selected.get('format') == client.PACKAGE_FORMAT and prior is None:
        raise ValueError('integrated native qualification requires an exact upgrade predecessor')
    if prior and (prior['target'] != selected['target'] or prior['tag'] == selected['tag']):
        raise ValueError('native upgrade predecessor differs')
    expected = matrix(selected['target'])['include']; by_id = {}
    required = {'signature', 'published-download', 'install', 'repeated-update', 'exact-payload', 'self-check', 'remove'}
    for record in records:
        name = record.get('id')
        if name in by_id: raise ValueError('duplicate native result')
        by_id[name] = record
    if set(by_id) != {row['id'] for row in expected}: raise ValueError('missing or foreign native result')
    for row in expected:
        result = by_id[row['id']]
        if (result.get('status') != 'passed' or result.get('schema_version') != 1 or result.get('target') != selected['target'] or
                result.get('kind') != row['kind'] or result.get('image') != row['image'] or result.get('tag') != selected['tag'] or
                result.get('manifest_sha256') != selected['manifest_sha256'] or set(result.get('checks', [])) != required or
                result.get('source_commit') != environment['GITHUB_SHA'] or result.get('run_id') != environment['GITHUB_RUN_ID'] or
                result.get('attempt') != environment['GITHUB_RUN_ATTEMPT'] or
                result.get('upgrade_from') != (prior['tag'] if prior else None) or
                result.get('upgrade_manifest_sha256') != (prior['manifest_sha256'] if prior else None) or
                result.get('format') != selected.get('format') or
                (selected.get('format') == client.PACKAGE_FORMAT and
                    result.get('upgrade_format') != (prior.get('format', 'distribution') if prior else None)) or
                not result.get('backends') or not result.get('commands') or
                not isinstance(result.get('image_id'), str) or not result['image_id'].startswith('sha256:') or
                not release.delivery.SHA.fullmatch(result['image_id'][7:])):
            raise ValueError('native result scope or execution identity differs')
    return dict(schema_version=1, target=selected['target'], source_commit=environment['GITHUB_SHA'],
        run_id=int(environment['GITHUB_RUN_ID']), attempt=int(environment['GITHUB_RUN_ATTEMPT']),
        checks={name:release.distro.digest(release.distro.encoded(result)) for name,result in sorted(by_id.items())})


def validate_payload_evidence(channels, value, result):
    backends = result['backends']
    if ({item['backend'] for item in backends} != set(value['backends']) or len(backends) != len(value['backends'])):
        raise ValueError('native result does not cover every packaged backend')
    for item in backends:
        expected = expected_payload(channels, value, item['backend'], result['kind'])
        if item != dict(backend=item['backend'], files=len(expected), payload_sha256=release.distro.digest(release.distro.encoded(expected))):
            raise ValueError('native payload evidence differs from exact signed channel')


def accept(selected, records, environment, output):
    """Called after verified successful workflow bundles, under publication ownership."""
    if selected.get('format') == client.PACKAGE_FORMAT:
        raise ValueError('integrated packages are accepted through certified application release promotion')
    marker = qualification(selected, records, environment)
    value = release.fetch(environment['GITHUB_REPOSITORY'], selected['tag'], selected['manifest_sha256'],
        output, release.ROOT/'docs/release-policy.json', environment['TRUSTED_FINGERPRINT'], native_only=True)
    if value['request']['target'] != selected['target']: raise ValueError('qualified channel target differs')
    with tempfile.TemporaryDirectory(prefix='foundation-accept-') as temporary:
        channels = extract_channels(output, Path(temporary)/'channels')
        for result in records:
            validate_payload_evidence(channels, value, result)
    remote = release.delivery.Remote(environment['GITHUB_REPOSITORY'])
    def mutation():
        info = remote.find(selected['tag']); assets = remote.assets(info)
        body = release.delivery.parse(info.get('body', ''))
        base = {'kind': 'signed-distribution', 'manifest_sha256': selected['manifest_sha256']}
        desired = dict(base, native_qualification=marker)
        if info['draft'] or body not in (base, desired): raise ValueError('unexpected channel lifecycle; preserve it')
        expected = dict(value['files'])
        expected.update({name: release.asset_info(Path(output)/name) for name in release.CONTROL})
        if set(assets) != set(expected) or any(assets[name]['digest'] != 'sha256:'+item['sha256'] or assets[name]['size'] != item['size'] for name,item in expected.items()):
            raise ValueError('native checked remote assets changed')
        remote.unchanged(selected['tag'], info, assets, value['request']['packager_commit'])
        if body != desired or info['prerelease']:
            remote.change('/releases/'+str(info['id']), method='PATCH', body={
                'body': json.dumps(desired, sort_keys=True), 'prerelease': False, 'make_latest': 'false'})
        final = remote.by_id(info['id'], selected['tag'])
        if final['id'] != info['id'] or final['draft'] or final['prerelease'] or remote.assets(final) != assets or release.delivery.parse(final['body']) != desired:
            raise ValueError('native channel acceptance outcome differs; inspect remote state')
        remote.not_latest(final)
        return desired
    return release.delivery.run_mutation(remote, mutation)


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__); p.add_argument('operation', choices=('plan', 'native', 'arch-keyring'))
    p.add_argument('--distro', choices=('all', 'apt', 'arch', 'gentoo'), default='all'); p.add_argument('--accept', action='store_true')
    p.add_argument('--target'); p.add_argument('--directory', type=Path); p.add_argument('--previous', type=Path)
    p.add_argument('--format', choices=(client.PACKAGE_FORMAT,))
    p.add_argument('--previous-format', choices=(client.PACKAGE_FORMAT,))
    p.add_argument('--policy', type=Path); p.add_argument('--trusted-fingerprint'); p.add_argument('--kind'); p.add_argument('--evidence', type=Path)
    a = p.parse_args(argv)
    if a.operation == 'plan': result = matrix(a.target, a.distro, accept=a.accept)
    elif a.operation == 'arch-keyring':
        if not all((a.directory, a.trusted_fingerprint)): p.error('complete Arch keyring inputs required')
        result = prepare_arch_keyring(a.directory/'archive-keyring.gpg', a.trusted_fingerprint)
    else:
        if not all((a.directory, a.policy, a.trusted_fingerprint, a.kind, a.evidence)): p.error('complete native inputs required')
        if a.format and not a.target: p.error('integrated native inputs require --target')
        if a.previous_format and not a.previous: p.error('--previous-format requires --previous')
        result = native(a.directory, a.policy, a.trusted_fingerprint, a.kind, a.evidence,
                        previous=a.previous, target=a.target, format=a.format, previous_format=a.previous_format)
    print(json.dumps(result, sort_keys=True))

if __name__ == '__main__': main()
