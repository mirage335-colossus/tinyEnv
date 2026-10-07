#!/usr/bin/env python3
"""Assemble signed package repositories before an application inventory freezes.

The ordinary delivery owns these assets. This module neither publishes a release
nor rebuilds the application, and keeps the legacy separate-channel format intact.
"""
import io
from pathlib import Path
import re
import tarfile
import tempfile

import apt_repo as apt
import dependency_archive as archive
import distribution_release as channel
import distro_channel as distro
import github_release as delivery
import release

CONTROL = {'packages.json', 'packages.json.sig'}
TARGETS = channel.TARGETS
MAX_CONTROL = 8 * 1024 * 1024
TARGET_FIELDS = {'backends', 'specifications', 'native_archive', 'application_archive',
                 'application_manifest', 'payloads'}


def _info(path):
    return channel.asset_info(Path(path))


def _base(request, latest=False):
    suffix = 'latest/download/' if latest else 'download/' + request['application_tag'] + '/'
    return 'https://github.com/' + request['repository'] + '/releases/' + suffix


def _request(value):
    fields = {'repository', 'application_tag', 'source_commit', 'version', 'package_release',
              'sequence', 'valid_days', 'trusted_fingerprint'}
    if not isinstance(value, dict) or set(value) != fields:
        raise ValueError('complete integrated package request required')
    delivery.location(value['repository'], value['application_tag'])
    if value['application_tag'] in ('base', 'latest') or not delivery.OID.fullmatch(str(value['source_commit'])):
        raise ValueError('exact application source required')
    distro.version_key(value)
    if (type(value['sequence']) is not int or not 1 <= value['sequence'] < 2**63 or
            type(value['valid_days']) is not int or not 1 <= value['valid_days'] <= 90):
        raise ValueError('positive sequence and bounded signed validity required')
    apt.full_fingerprint(value['trusted_fingerprint'])
    return value


def _inventory(value):
    if not isinstance(value, dict) or not value or len(value) > 998:
        raise ValueError('bounded complete package inventory required')
    seen = set()
    for name, row in value.items():
        delivery.valid_name(name)
        if (name.casefold() in seen or not isinstance(row, dict) or set(row) != {'size', 'sha256'} or
                type(row['size']) is not int or not 0 <= row['size'] <= channel.MAX_ASSET or
                not delivery.SHA.fullmatch(str(row['sha256']))):
            raise ValueError('invalid package asset identity')
        seen.add(name.casefold())


def _names(names):
    if not isinstance(names, list) or not names or len(names) != len(set(names)):
        raise ValueError('complete package file list required')
    for name in names:
        delivery.valid_name(name)
    return set(names)


def _document(directory):
    raw = distro.ordinary(Path(directory) / 'packages.json', MAX_CONTROL)[0]
    value = delivery.parse(raw)
    fields = {'schema_version', 'request', 'policy_sha256', 'targets', 'apt_files',
              'arch_files', 'inputs', 'files'}
    if (not isinstance(value, dict) or set(value) != fields or
            type(value['schema_version']) is not int or value['schema_version'] != 1):
        raise ValueError('complete signed integrated package manifest required')
    req = _request(value['request'])
    if not delivery.SHA.fullmatch(str(value['policy_sha256'])):
        raise ValueError('exact integrated package policy required')
    _inventory(value['files']); _inventory(value['inputs'])
    if len(value['files']) + len(value['inputs']) + len(CONTROL) + 2 > 1000:
        raise ValueError('complete ordinary package release exceeds asset count limit')
    if set(value['files']) & (CONTROL | set(value['inputs'])):
        raise ValueError('package assets collide with application inputs or controls')
    apt_names, arch_names = _names(value['apt_files']), _names(value['arch_files'])
    if not {'archive-keyring.gpg', 'InRelease', 'Release', 'Release.gpg', 'Packages',
            'Packages.gz', 'repository.json'} <= apt_names:
        raise ValueError('incomplete combined APT controls')
    if apt_names & arch_names or set(value['targets']) != set(TARGETS):
        raise ValueError('package target inventory or flat names differ')
    expected = apt_names | arch_names | {'INSTALL.md'}
    for target, item in value['targets'].items():
        if not isinstance(item, dict) or set(item) != TARGET_FIELDS:
            raise ValueError('complete integrated package target required')
        backends = item['backends']
        if (not isinstance(backends, list) or not backends or backends[0] != 'core' or
                len(backends) != len(set(backends)) or set(backends) - distro.BACKENDS or
                not isinstance(item['specifications'], dict) or set(item['specifications']) != set(backends)):
            raise ValueError('complete packaged backend inventory required')
        if item['native_archive'] != 'native-' + target + '.tar.gz':
            raise ValueError('canonical target bundle name required')
        expected.add(item['native_archive'])
        for field in ('application_archive', 'application_manifest'):
            if item[field] not in value['inputs']:
                raise ValueError('target application input missing')
        for backend, spec in item['specifications'].items():
            distro.validate_spec(spec)
            if (spec['schema_version'] != distro.RELEASE_TAG_SCHEMA or spec['backend'] != backend or
                    spec['architecture'] != TARGETS[target][0] or spec['version'] != req['version'] or
                    spec['package_release'] != req['package_release'] or
                    spec['archive_sha256'] != value['inputs'][item['application_archive']]['sha256'] or
                    spec['archive_url'] != _base(req) + item['application_archive']):
                raise ValueError('target package specification differs')
            for ref in [dict(url=spec['archive_url'], sha256=spec['archive_sha256']),
                        spec['application_source'], spec['packaging_tool'], spec['sdk'], *spec['dependencies']]:
                name = ref['url'].removeprefix(_base(req))
                if (ref['url'] != _base(req) + name or name not in value['inputs'] or
                        value['inputs'][name]['sha256'] != ref['sha256']):
                    raise ValueError('recipe input differs from signed application assets')
        if not isinstance(item['payloads'], dict) or set(item['payloads']) != {'apt', 'arch', 'gentoo'}:
            raise ValueError('complete package payload anchors required')
        for rows in item['payloads'].values():
            if not isinstance(rows, dict) or set(rows) != set(backends):
                raise ValueError('payload anchors omit packaged backends')
            for row in rows.values():
                if (not isinstance(row, dict) or set(row) != {'files', 'payload_sha256'} or
                        type(row['files']) is not int or row['files'] < 1 or
                        not delivery.SHA.fullmatch(str(row['payload_sha256']))):
                    raise ValueError('invalid package payload anchor')
    if set(value['files']) != expected:
        raise ValueError('unexpected or omitted integrated package assets')
    return value


def _selected(value, target):
    if target not in TARGETS:
        raise ValueError('supported integrated package target required')
    return set(value['apt_files']) | {value['targets'][target]['native_archive']} | (
        set(value['arch_files']) if target == 'linux-x86_64' else set())


def _view(value, target, directory):
    item = value['targets'][target]
    return dict(format='release-packages', request=dict(value['request'], target=target),
                tag=value['request']['application_tag'], backends=item['backends'],
                specifications=item['specifications'], payloads=item['payloads'],
                apt_files=value['apt_files'], arch_files=value['arch_files'] if target == 'linux-x86_64' else [],
                files={name: value['files'][name] for name in sorted(_selected(value, target))},
                manifest_sha256=archive.digest(Path(directory) / 'packages.json'))


def native_identity(directory, trusted, *, target):
    """Authenticate a prior head without requiring its repository dates to be current."""
    value = _document(directory)
    if value['request']['trusted_fingerprint'] != apt.full_fingerprint(trusted):
        raise ValueError('integrated package trust differs')
    key = Path(directory) / 'archive-keyring.gpg'
    if _info(key) != value['files']['archive-keyring.gpg']:
        raise ValueError('integrated package keyring differs')
    distro.verify_signature(distro.ordinary(Path(directory) / 'packages.json', MAX_CONTROL)[0],
                           distro.ordinary(Path(directory) / 'packages.json.sig')[0],
                           distro.ordinary(key)[0], trusted)
    return _view(value, target, directory)


def binding(directory, manifest):
    """Check package roles against the ordinary inventory; no signature process is run."""
    value = _document(directory); role = manifest.get('packages')
    names = set(value['files']) | CONTROL
    if (not isinstance(role, dict) or set(role) != {'manifest', 'files'} or
            role['manifest'] != 'packages.json' or _names(role['files']) != names):
        raise ValueError('ordinary inventory package role differs')
    files = manifest['files']
    if not names <= files.keys():
        raise ValueError('ordinary inventory omits package assets')
    for name, row in value['files'].items():
        if files[name] != row['sha256']:
            raise ValueError('ordinary and signed package inventories differ')
    for name in CONTROL:
        if archive.digest(Path(directory) / name) != files[name]:
            raise ValueError('ordinary package control digest differs')
    original = {Path(name).name: digest for name, digest in files.items() if name not in names}
    if (len(original) != len(files) - len(names) or set(original) != set(value['inputs']) or
            any(original[name] != row['sha256'] for name, row in value['inputs'].items())):
        raise ValueError('package inputs differ from complete ordinary inventory')
    targets = {item['target']: item for item in manifest['artifacts'] if item['target'] in TARGETS}
    if set(targets) != set(value['targets']):
        raise ValueError('ordinary application package targets differ')
    for target, item in value['targets'].items():
        app = targets[target]
        primary = release.dependency_names(app['sdk_recipe'])[0]
        dependencies = sorted(Path(name).name for name in files if name.startswith('dependencies/'))
        ref = lambda name: dict(url=_base(value['request']) + name, sha256=value['inputs'][name]['sha256'])
        if (item['application_archive'] != app['archive'] or item['application_manifest'] != app['manifest'] or
                item['backends'] != ['core', *app['backends']] or
                any(spec['application_source'] != dict(url=_base(value['request']) + manifest['source']['archive'],
                        sha256=manifest['source']['sha256']) or spec['packaging_tool'] != spec['application_source']
                    for spec in item['specifications'].values())):
            raise ValueError('package application or source binding differs')
        if primary not in value['inputs'] or any(spec['sdk'] != ref(primary) or
                sorted(spec['dependencies'], key=lambda row: row['url']) != [ref(name) for name in dependencies if name != primary]
                for spec in item['specifications'].values()):
            raise ValueError('package SDK or complete dependency closure differs')
    return value


def extract_channels(directory, output, target):
    """Restore the already authenticated combined APT and selected native trees."""
    directory, output = Path(directory), Path(output).absolute()
    value = _document(directory)
    if target not in value['targets'] or output.exists() or output.is_symlink():
        raise ValueError('new selected package extraction output required')
    output.mkdir(parents=True)
    apt_root = output / 'apt'; apt_root.mkdir()
    for name in value['apt_files']:
        if _info(directory / name) != value['files'][name]:
            raise ValueError('APT input changed before extraction')
        channel.copy_new(directory / name, apt_root / name)
    name = value['targets'][target]['native_archive']
    if _info(directory / name) != value['files'][name]:
        raise ValueError('native input changed before extraction')
    archive.extract(directory / name, output / 'native', max_bytes=distro.MAX_BYTES)
    # Only fresh owned implicit directories are normalized; file modes stay exact.
    (output / 'native').chmod(0o755)
    for path in (output / 'native').rglob('*'):
        if path.is_dir(): path.chmod(0o755)
    return output


def _payloads(native, receipts, target):
    result = {'apt': {}, 'arch': {}, 'gentoo': {}}
    for receipt in receipts:
        if receipt['architecture'] == TARGETS[target][1]:
            payload = receipt['payload']
            result['apt'][receipt['backend']] = dict(files=len(payload), payload_sha256=distro.digest(distro.encoded(payload)))
    metadata = archive.read_json(native / 'channel.json')
    for spec in metadata['packages'].values():
        group = native / 'packages' / (spec['architecture'] + '-' + spec['backend'])
        files = {name: row for name, row in distro.tree(group).items()
                 if not name.endswith('.pkg.tar.gz.sig')}
        generated, _ = distro.expected_package(files)
        packages = [row[0] for name, row in generated.items() if name.startswith('arch/') and name.endswith('.pkg.tar.gz')]
        if len(packages) != 1:
            raise ValueError('one exact native package per backend required')
        payload = {}
        with tarfile.open(fileobj=io.BytesIO(packages[0]), mode='r:gz') as bundle:
            for member in bundle:
                if member.isfile() and not member.name.startswith('.'):
                    with bundle.extractfile(member) as stream:
                        payload[member.name] = dict(sha256=distro.digest(stream.read()), size=member.size, mode=member.mode)
        for kind in ('arch', 'gentoo'):
            chosen = {name: row for name, row in payload.items()
                      if kind != 'gentoo' or not name.startswith('usr/share/licenses/')}
            result[kind][spec['backend']] = dict(files=len(chosen), payload_sha256=distro.digest(distro.encoded(chosen)))
    return result


def verify(directory, policy, trusted, *, target=None):
    """Replay signatures and package projections from exact local published bytes."""
    directory = Path(directory); value = _document(directory)
    if value['policy_sha256'] != archive.digest(policy):
        raise ValueError('integrated package policy differs')
    native_identity(directory, trusted, target=target or 'linux-x86_64')
    selected = set(value['files']) if target is None else _selected(value, target)
    allowed = selected | CONTROL
    if (directory / 'release.json').exists():
        allowed.add('release.json')
        original = archive.read_json(directory / 'release.json')['files']
        allowed.update(name for name, digest in original.items()
                       if Path(name).name in value['inputs'] and
                       digest == value['inputs'][Path(name).name]['sha256'])
    if (directory / 'delivery.json').exists(): allowed.add('delivery.json')
    for path in directory.rglob('*'):
        name = path.relative_to(directory).as_posix(); archive.relative(name)
        if path.is_symlink() or (not path.is_dir() and (not path.is_file() or name not in allowed)):
            raise ValueError('unexpected or linked package input')
    for name in selected:
        if _info(directory / name) != value['files'][name]:
            raise ValueError('signed package asset bytes differ')
    targets = list(value['targets']) if target is None else [target]
    for current in targets:
        with tempfile.TemporaryDirectory(prefix='release-packages-verify-') as temporary:
            channels = extract_channels(directory, Path(temporary) / 'channels', current)
            state = apt.verify_repository(channels / 'apt', trusted)
            native = distro.verify(channels / 'native', trusted)
            req = value['request']; item = value['targets'][current]
            if (state['sequence'] != req['sequence'] or native['sequence'] != req['sequence'] or
                    native['architecture'] != TARGETS[current][0] or
                    {spec['backend']: spec for spec in native['packages'].values()} != item['specifications']):
                raise ValueError('native package target, sequence or specifications differ')
            apt_metadata = archive.read_json(channels / 'apt/repository.json')
            if apt_metadata['base_url'] != _base(req, latest=True):
                raise ValueError('combined APT Latest URI differs')
            receipts = [archive.read_json(channels / 'apt' / row['receipt']) for row in apt_metadata['packages']]
            expected = {(TARGETS[t][1], backend) for t, entry in value['targets'].items() for backend in entry['backends']}
            if {(row['architecture'], row['backend']) for row in receipts} != expected or len(receipts) != len(expected):
                raise ValueError('combined APT backend/architecture inventory differs')
            for receipt in receipts:
                t = next(t for t in TARGETS if TARGETS[t][1] == receipt['architecture'])
                entry = value['targets'][t]
                if (receipt['archive_sha256'] != value['inputs'][entry['application_archive']]['sha256'] or
                        receipt['archive'] != entry['application_archive'] or
                        distro.digest(distro.encoded(receipt['archive_manifest'])) != value['inputs'][entry['application_manifest']]['sha256'] or
                        receipt['version'] != req['version'] + '+r' + str(req['package_release'])):
                    raise ValueError('APT receipt differs from signed application inputs')
            if _payloads(channels / 'native', receipts, current) != item['payloads']:
                raise ValueError('signed payload anchors differ from verified package bytes')
            if current == 'linux-x86_64':
                if set(value['arch_files']) != {p.name for p in (channels / 'native/arch').iterdir()}:
                    raise ValueError('flat Arch asset inventory differs')
                for name in value['arch_files']:
                    if _info(channels / 'native/arch' / name) != value['files'][name]:
                        raise ValueError('flat Arch bytes differ from verified native channel')
    return value if target is None else _view(value, target, directory)


def _instructions(req):
    url = _base(req, latest=True); trusted = req['trusted_fingerprint']
    return ('# Signed application package repositories\n\n'
        'Independently verify signing fingerprint `' + trusted + '` before trusting archive-keyring.gpg. '
        'The adjacent key alone does not establish trust.\n\n'
        'APT: install the independently verified keyring and configure:\n\n```\nTypes: deb\nURIs: ' + url +
        '\nSuites: ./\nArchitectures: amd64 arm64\nSigned-By: /etc/apt/keyrings/software-foundation.gpg\n```\n\n'
        'Then run `apt-get update` and install the desired `software-foundation-<backend>` package.\n\n'
        'Arch x86_64: independently import and locally trust the same signing key, then configure:\n\n'
        '```\n[software-foundation]\nSigLevel = Required DatabaseRequired\nServer = ' + url +
        '\n```\n\nRun `pacman -Syu` for normal updates. Latest may move after an index refresh; '
        'a missing older package requires a fresh complete update. ARM64 Arch is not qualified.\n\n'
        'Gentoo x86_64: use the trusted retained `tools/distro_client.py` Portage adapter with '
        '`selection={"track":"latest"}`. Normal `emaint sync -r software-foundation-bin` verifies '
        'the signed Latest head and restores its exact-tag native overlay. ARM64 Gentoo is not qualified.\n').encode()


def build(candidate, repository, tag, source_commit, policy, key, trusted, *, sequence, package_release):
    """Write flat package assets; the caller freezes their ordinary inventory next."""
    candidate = Path(candidate).resolve(strict=True)
    manifest = release.verify_release(candidate)
    key = channel._key_outside(key, channel.ROOT, candidate)
    with tarfile.open(candidate / manifest['source']['archive'], 'r:*') as source:
        member = source.getmember('CMakeLists.txt')
        if not member.isfile() or member.size > 1024 * 1024:
            raise ValueError('bounded retained project version source required')
        text = source.extractfile(member).read().decode()
    versions = re.findall(r'project\(Foundation\s+VERSION\s+([0-9]+\.[0-9]+\.[0-9]+)\s', text)
    if len(versions) != 1:
        raise ValueError('one retained application version required')
    req = _request(dict(repository=repository, application_tag=tag, source_commit=source_commit,
        version=versions[0], package_release=package_release, sequence=sequence, valid_days=30,
        trusted_fingerprint=apt.full_fingerprint(trusted)))
    inputs, paths = {}, {}
    for logical, digest in manifest['files'].items():
        name = delivery.valid_name(Path(logical).name)
        if name.casefold() in {n.casefold() for n in inputs}:
            raise ValueError('flattened application asset names collide')
        paths[name] = archive.checked_file(candidate, logical); inputs[name] = _info(paths[name])
        if inputs[name]['sha256'] != digest:
            raise ValueError('application input changed before packaging')
    entries = {item['target']: item for item in manifest['artifacts'] if item['target'] in TARGETS}
    if set(entries) != set(TARGETS):
        raise ValueError('both Linux application targets required for combined repositories')
    if any(item['backends'] for item in entries.values()):
        distro.require_gui_terms()
    ref = lambda name: dict(url=_base(req) + name, sha256=inputs[name]['sha256'])
    with tempfile.TemporaryDirectory(prefix='.release-packages-', dir=candidate.parent) as temporary:
        work = Path(temporary); staged = work / 'assets'; staged.mkdir()
        targets, apt_receipts, native_roots = {}, [], {}
        for target, item in sorted(entries.items()):
            expected = archive.read_json(paths[item['manifest']])
            _, payload = distro.archive_payload(paths[item['archive']], expected)
            licenses = sorted(distro.required_license_files(payload))
            backends = ['core', *item['backends']]; groups, specs = [], {}
            dependencies = [Path(name).name for name in manifest['files'] if name.startswith('dependencies/')]
            primary = release.dependency_names(item['sdk_recipe'])[0]
            if primary not in dependencies:
                raise ValueError('primary application SDK archive missing')
            for backend in backends:
                apt_root = work / ('apt-' + target + '-' + backend)
                receipt = apt.package(paths[item['archive']], paths[item['manifest']],
                    req['version'] + '+r' + str(package_release), TARGETS[target][1], backend, apt_root)
                apt_receipts.append(apt_root / (receipt['package'] + '.json'))
                source = ref(manifest['source']['archive'])
                spec = dict(schema_version=distro.RELEASE_TAG_SCHEMA, version=req['version'], package_release=package_release,
                    architecture=TARGETS[target][0], backend=backend, archive_url=ref(item['archive'])['url'],
                    archive_sha256=item['sha256'], license_files=licenses, redistribution_approved=True,
                    application_source=source, packaging_tool=source, sdk=ref(primary),
                    dependencies=[ref(name) for name in dependencies if name != primary],
                    runtime_dependencies=distro.runtime_policy(backend))
                spec_path = work / ('spec-' + target + '-' + backend + '.json'); archive.write_json(spec_path, spec)
                group = work / ('native-' + target + '-' + backend)
                distro.package(paths[item['archive']], paths[item['manifest']], spec_path, group)
                groups.append(group); specs[backend] = spec
            native = work / ('native-' + target)
            distro.assemble(groups, native, key, trusted, sequence, req['valid_days'])
            name = 'native-' + target + '.tar.gz'; archive.archive_tree(native, staged / name)
            native_roots[target] = native
            targets[target] = dict(backends=backends, specifications=specs, native_archive=name,
                application_archive=item['archive'], application_manifest=item['manifest'])
        apt_root = work / 'apt'
        apt.repository(apt_receipts, apt_root, _base(req, latest=True), key, trusted, sequence, req['valid_days'])
        apt_files = sorted(p.name for p in apt_root.iterdir())
        arch_root = native_roots['linux-x86_64'] / 'arch'
        arch_files = sorted(p.name for p in arch_root.iterdir())
        for root in (apt_root, arch_root):
            for path in root.iterdir(): channel.copy_new(path, staged / path.name)
        receipts = [archive.read_json(path) for path in apt_receipts]
        for target, native in native_roots.items(): targets[target]['payloads'] = _payloads(native, receipts, target)
        (staged / 'INSTALL.md').write_bytes(_instructions(req))
        value = dict(schema_version=1, request=req, policy_sha256=archive.digest(policy), targets=targets,
            apt_files=apt_files, arch_files=arch_files, inputs=inputs,
            files={path.name: _info(path) for path in sorted(staged.iterdir())})
        archive.write_json(staged / 'packages.json', value)
        with distro.signing(key, trusted) as (public, sign):
            if public != (staged / 'archive-keyring.gpg').read_bytes():
                raise ValueError('package signing keys differ')
            (staged / 'packages.json.sig').write_bytes(sign((staged / 'packages.json').read_bytes()))
        verify(staged, policy, trusted)
        if any(_info(paths[name]) != row for name, row in inputs.items()):
            raise ValueError('application inputs changed during packaging')
        if {p.name.casefold() for p in staged.iterdir()} & {p.name.casefold() for p in candidate.iterdir()}:
            raise ValueError('package output collides with existing application assets')
        for path in staged.iterdir(): channel.copy_new(path, candidate / path.name)
    return value


def fetch(repository, tag, manifest_sha256, output, policy, trusted, *, target, transport=None):
    """Fetch selected repositories and authenticate their ordinary release binding."""
    delivery.location(repository, tag)
    if target not in TARGETS or not delivery.SHA.fullmatch(str(manifest_sha256)):
        raise ValueError('exact package manifest and supported target required')
    output = Path(output).absolute()
    if output.exists() or output.is_symlink():
        raise ValueError('new fetched package output required')
    output.parent.mkdir(parents=True, exist_ok=True)
    remote = delivery.Remote(repository, transport); remote.visible()
    info = remote.published(tag)
    if hasattr(remote.transport, 'observe_release'): remote.transport.observe_release(info)
    assets = remote.assets(info)
    if len(assets) > 1000 or any(row['size'] > channel.MAX_ASSET for row in assets.values()):
        raise ValueError('ordinary package release exceeds bounded asset limits')
    with tempfile.TemporaryDirectory(prefix='.release-package-fetch-', dir=output.parent) as temporary:
        stage = Path(temporary) / 'assets'; stage.mkdir()
        for name in ('packages.json', 'packages.json.sig', 'archive-keyring.gpg', 'release.json', 'delivery.json'):
            if name not in assets or assets[name]['size'] > MAX_CONTROL:
                raise ValueError('bounded integrated package control missing')
            remote.download(assets[name], stage / name, manifest_sha256 if name == 'packages.json' else None)
        value = _document(stage); req = value['request']
        if req['repository'] != repository or req['application_tag'] != tag:
            raise ValueError('integrated package repository or tag differs')
        native_identity(stage, trusted, target=target)
        manifest = release.verify_metadata(stage); identity = archive.read_json(stage / 'delivery.json')
        delivery.validate_delivery(identity, stage, metadata_only=True)
        delivery.validate_remote_inventory(identity, info, assets)
        binding(stage, manifest)
        if (identity['experiment'] or identity['source_commit'] != req['source_commit'] or
                identity['packager_commit'] != req['source_commit'] or identity['repository'] != repository or identity['tag'] != tag):
            raise ValueError('integrated package source or ordinary delivery differs')
        for name, row in value['inputs'].items():
            matches = [item for item in identity['files'].values() if item['asset'] == name]
            if len(matches) != 1 or {'size': matches[0]['size'], 'sha256': matches[0]['sha256']} != row:
                raise ValueError('retained package input differs from frozen delivery')
        selected = _selected(value, target)
        for name in selected:
            if name not in assets or assets[name]['size'] != value['files'][name]['size'] or assets[name]['digest'] != 'sha256:' + value['files'][name]['sha256']:
                raise ValueError('remote package bytes differ from signed inventory')
            if not (stage / name).exists(): remote.download(assets[name], stage / name, value['files'][name]['sha256'])
        result = verify(stage, policy, trusted, target=target)
        remote.unchanged(tag, info, assets, identity['tag_commit'])
        stage.rename(output)
    return result
