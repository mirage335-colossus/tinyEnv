#!/usr/bin/env python3
"""Sign and publish separate immutable package channels from certified archives.

No application compilation, Actions artifact storage, remote overwrites or Latest
changes. Planning is the default; publication requires a separate explicit flag.
"""
import argparse
import base64
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import tarfile

import apt_repo as apt
import ci_plan as ci
import dependency_archive as archive
import distro_channel as distro
import github_release as delivery
import release
import source_identity

ROOT = Path(__file__).resolve().parents[1]
CONTROL = {'distribution.json', 'distribution.json.sig'}
MAX_ASSET = 2 * 1024**3 - 1
MAX_WORKFLOW_REQUEST_BYTES = 32 * 1024
TARGETS = {'linux-x86_64': ('x86_64', 'amd64'), 'linux-aarch64': ('aarch64', 'arm64')}


def workflow_request(raw):
    # Leave room for the other dispatch inputs while retaining complete notices.
    if not isinstance(raw, str) or len(raw.encode('utf-8')) > MAX_WORKFLOW_REQUEST_BYTES:
        raise ValueError('request exceeds input bound')
    return request(delivery.parse(raw))


def request(value):
    fields = {'schema_version', 'repository', 'application_tag', 'inventory_sha256', 'profile',
              'certificate_run', 'certificate_attempt', 'certificate_sha256', 'target', 'version',
              'package_release', 'sequence', 'valid_days', 'trusted_fingerprint', 'license_files',
              'runtime_dependencies', 'packager_commit'}
    if not isinstance(value, dict) or set(value) != fields or type(value['schema_version']) is not int or value['schema_version'] != 1:
        raise ValueError('complete distribution request required')
    delivery.location(value['repository'], value['application_tag'])
    if (value['target'] not in TARGETS or not delivery.OID.fullmatch(value['packager_commit']) or
            not delivery.SHA.fullmatch(value['inventory_sha256']) or not delivery.SHA.fullmatch(value['certificate_sha256']) or
            not delivery.coverage.NAME.fullmatch(value['certificate_run']) or not delivery.positive(value['certificate_attempt']) or
            not isinstance(value['profile'], str) or not value['profile']):
        raise ValueError('exact Linux target, source and certificate identity required')
    distro.version_key(value)
    if type(value['sequence']) is not int or not 1 <= value['sequence'] < 2**63 or type(value['valid_days']) is not int or not 1 <= value['valid_days'] <= 90:
        raise ValueError('positive sequence and bounded signed validity required')
    apt.full_fingerprint(value['trusted_fingerprint'])
    # Validate caller-controlled recipe lists using the existing complete contract.
    placeholder = {'url': 'https://example.invalid/' + '0' * 64, 'sha256': '0' * 64}
    distro.validate_spec(dict(schema_version=distro.CURRENT_SCHEMA, version=value['version'], package_release=value['package_release'],
        architecture=TARGETS[value['target']][0], backend='core', archive_url=placeholder['url'], archive_sha256='0' * 64,
        license_files=value['license_files'], redistribution_approved=True, application_source=placeholder,
        packaging_tool=placeholder, sdk=placeholder, dependencies=[], runtime_dependencies=value['runtime_dependencies']))
    return value


def tag_for(value):
    request(value)
    return 'distro-' + value['version'] + '-' + TARGETS[value['target']][0] + '-r' + str(value['package_release']) + '-s' + str(value['sequence'])


def base_url(value):
    return 'https://github.com/' + value['repository'] + '/releases/download/' + tag_for(value) + '/'


def plan(value):
    request(value)
    return delivery.plan('publish-distribution', value['repository'], tag=tag_for(value), request=value,
        lifecycle='verify exact certificate, sign separate channels, upload immutably, verify downloaded channels, publish non-Latest')


def asset_info(path):
    return {'size': path.stat().st_size, 'sha256': archive.digest(path)}


def alias(path):
    return 'sha256-' + archive.digest(path) + '-' + delivery.valid_name(path.name)


def copy_new(source, target):
    with Path(source).open('rb') as incoming, Path(target).open('xb') as outgoing:
        shutil.copyfileobj(incoming, outgoing)
    Path(target).chmod(0o644)
    if asset_info(Path(source)) != asset_info(Path(target)):
        raise ValueError('retained input changed while copying')


def selected(manifest, value):
    matches = [item for item in manifest['artifacts'] if item['target'] == value['target']]
    if len(matches) != 1: raise ValueError('certified inventory needs exactly one selected target')
    item = matches[0]
    backends = ['core', *item['backends']]
    if len(set(backends)) != len(backends) or not set(backends) <= distro.BACKENDS:
        raise ValueError('certified target has unsupported or repeated native backends')
    return item, backends


def certified(remote, candidate, identity, policy, value, *, certificate_paths=None, certificate_directory=None):
    request(value)
    if (identity['repository'] != value['repository'] or identity['tag'] != value['application_tag'] or
            identity['inventory_sha256'] != value['inventory_sha256'] or identity['experiment']):
        raise ValueError('application differs from exact ordinary certified input')
    if certificate_paths is not None and certificate_directory is not None:
        raise ValueError('one exact certificate evidence source required')
    info, assets = delivery.verified_remote(remote, identity, candidate, prerelease=False,
                                           readback=False, metadata_only=True)
    reader = (LocalEvidence(certificate_paths) if certificate_paths is not None else
              CertificateCache(remote, certificate_directory, value) if certificate_directory is not None else remote)
    result = delivery.verify_certificate(reader, assets, identity, candidate, policy, value['profile'],
        value['certificate_run'], value['certificate_attempt'], value['certificate_sha256'], metadata_only=True)
    remote.unchanged(identity['tag'], info, assets, identity['tag_commit'])
    return info, assets, result


def instructions(value, backends, *, native_only=False):
    url = base_url(value); trusted = value['trusted_fingerprint']; arch, debarch = TARGETS[value['target']]
    version = value['version'] + '+r' + str(value['package_release'])
    rendered = (f'# Immutable package channel {tag_for(value)}\n\n'
        f'Application: {value["application_tag"]}; inventory SHA256: {value["inventory_sha256"]}.\n'
        f'Trust the full signing fingerprint independently: `{trusted}`.\n'
        'Downloaded adjacent keys alone do not establish trust. Verify distribution.json.sig and the complete '
        'distribution with tools/distribution_release.py verify before configuration.\n\n'
        'APT: place the verified archive-keyring.gpg at /etc/apt/keyrings/software-foundation.gpg, then use:\n\n'
        f'```text\nTypes: deb\nURIs: {url}\nSuites: ./\nArchitectures: {debarch}\n'
        'Signed-By: /etc/apt/keyrings/software-foundation.gpg\n```\n\n'
        f'Run `sudo apt-get update`, then `sudo apt-get install software-foundation-core={version}`. '
        'For another declared variant select its software-foundation-BACKEND package.\n\n'
        'Arch: import and locally trust only the independently verified public key using pacman-key; '
        'append this exact configuration to pacman.conf:\n\n'
        f'```text\n[software-foundation]\nSigLevel = Required DatabaseRequired\nServer = {url.rstrip("/")}\n```\n\n'
        'Run `sudo pacman -Syu software-foundation-core-bin`; all database, package and signature names '
        f'resolve at the same immutable release root for {arch}.\n\n'
        'Gentoo: use `tools/distribution_release.py fetch` with the exact manifest digest, current policy and '
        'independently trusted fingerprint. After verification, extract channels.tar.gz into a new private '
        'directory and activate its native/gentoo overlay using `tools/distro_channel.py sync` on the complete '
        'native channel. Configure repos.conf location as ACTIVATION_ROOT/current/gentoo with auto-sync disabled. Use the generated binary-archive '
        'ebuild; it retrieves the retained content-addressed application archive without compiling it. '
        'Supply prerequisites from the configured binary package repository; do not silently build missing '
        'host prerequisites from source.\n\n'
        'Available variants: ' + ', '.join(backends) + '. All original sources, SDK triplets and selected '
        'certificate evidence remain content-addressed assets. Native package-manager installation qualification '
        'is separate from archive qualification. Move clients only after the required native install/update checks.\n').encode()
    if native_only:
        rendered = rendered.replace(b'complete distribution with tools/distribution_release.py verify',
                                    b'signed native channel with tools/distribution_release.py verify --native-only')
        rendered = rendered.replace(b'`tools/distribution_release.py fetch`',
                                    b'`tools/distribution_release.py fetch --native-only`')
    return rendered


def _key_outside(key, *roots):
    key = Path(key).resolve(strict=True)
    if any(key == Path(root).resolve() or Path(root).resolve() in key.parents for root in roots):
        raise ValueError('private signing key must stay outside checkout and retained outputs')
    distro.ordinary(key, 1024 * 1024)
    return key


def _git_object(kind, data, algorithm):
    return hashlib.new(algorithm, kind.encode() + b' ' + str(len(data)).encode() + b'\0' + data).digest()


def _source_git_tree(source, algorithm):
    """Reconstruct Git's byte-and-mode identity, excluding generated source.json."""
    manifest = source_identity.verify_source_archive(source)
    root = {}
    with tarfile.open(source, 'r:*') as bundle:
        for member in bundle:
            if not member.isfile() or member.name == 'source.json': continue
            node = root; parts = archive.relative(member.name).parts
            for component in parts[:-1]: node = node.setdefault(component, {})
            digest = hashlib.new(algorithm)
            digest.update(b'blob ' + str(member.size).encode() + b'\0')
            with bundle.extractfile(member) as stream:
                while True:
                    block = stream.read(1024 * 1024)
                    if not block: break
                    digest.update(block)
            node[parts[-1]] = (b'100755' if member.name in manifest['executables'] else b'100644', digest.digest())
    def tree(node):
        entries = []
        for name, value in node.items():
            encoded = name.encode('utf-8')
            directory = isinstance(value, dict)
            mode, oid = (b'40000', tree(value)) if directory else value
            entries.append((encoded + (b'/' if directory else b''), mode + b' ' + encoded + b'\0' + oid))
        return _git_object('tree', b''.join(value for _, value in sorted(entries)), algorithm)
    return tree(root).hex()


def verify_source_commit(source, proof, expected_commit):
    if (not isinstance(proof, dict) or set(proof) != {'schema_version', 'commit', 'commit_object', 'tree'} or
            type(proof['schema_version']) is not int or proof['schema_version'] != 1 or proof['commit'] != expected_commit or
            not isinstance(expected_commit, str) or not delivery.OID.fullmatch(expected_commit) or
            not isinstance(proof['commit_object'], str) or len(proof['commit_object']) > 1400000):
        raise ValueError('complete bounded packaging commit proof required')
    raw = base64.b64decode(proof['commit_object'], validate=True)
    algorithm = 'sha1' if len(expected_commit) == 40 else 'sha256'
    header, separator, _ = raw.partition(b'\n\n')
    first = header.split(b'\n', 1)[0]
    if (not separator or sum(line.startswith(b'tree ') for line in header.split(b'\n')) != 1 or len(raw) > 1024 * 1024 or _git_object('commit', raw, algorithm).hex() != expected_commit or
            first != ('tree ' + str(proof['tree'])).encode() or
            proof['tree'] != _source_git_tree(source, algorithm)):
        raise ValueError('packaging source bytes or modes differ from exact Git commit')
    return proof


def source_commit_proof(checkout, source, expected_commit):
    checkout = Path(checkout).resolve(strict=True)
    def git(*args):
        return subprocess.run(['git', '-C', str(checkout), *args], check=True, capture_output=True).stdout
    if git('rev-parse', 'HEAD').decode().strip() != expected_commit or git('status', '--porcelain', '--untracked-files=normal'):
        raise ValueError('packaging checkout must be clean at its exact recorded commit')
    raw = git('cat-file', 'commit', expected_commit)
    proof = dict(schema_version=1, commit=expected_commit, commit_object=base64.b64encode(raw).decode(),
                 tree=git('rev-parse', expected_commit + '^{tree}').decode().strip())
    return verify_source_commit(source, proof, expected_commit)


def prepare(value, candidate, identity, policy, packaging_source, output, key, *, transport=None, packaging_checkout=ROOT):
    """Verify the existing application/certificate and produce signed local assets."""
    request(value); candidate = Path(candidate).resolve(); output = Path(output).absolute(); policy = Path(policy)
    if output.exists() or output.is_symlink(): raise ValueError('new distribution output required')
    key = _key_outside(key, ROOT, output)
    manifest = release.verify_release(candidate); item, backends = selected(manifest, value)
    if any(entry['backends'] for entry in manifest['artifacts']): distro.require_gui_terms()
    packaging_proof = source_commit_proof(packaging_checkout, packaging_source, value['packager_commit'])
    remote = delivery.Remote(value['repository'], transport)
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.distribution-', dir=output.parent) as temporary:
        work = Path(temporary); stage = work / 'assets'; stage.mkdir(); channels = work / 'channels'; channels.mkdir()
        info, assets, evidence = certified(remote, candidate, identity, policy, value, certificate_directory=work)
        retained = {}
        def retain(logical, source):
            name = alias(source)
            if not (stage / name).exists(): copy_new(source, stage / name)
            retained[logical] = name
            return {'url': base_url(value) + name, 'sha256': archive.digest(source)}
        for name in identity['files']: retain('application/' + name, candidate / name)
        identity_path = work / 'delivery.json'; archive.write_json(identity_path, identity)
        retain('delivery.json', identity_path); retain('policy.json', policy)
        packaging = retain('packaging-source.tar.gz', Path(packaging_source))
        stem = f'certification-{value["certificate_run"]}-attempt-{value["certificate_attempt"]}'
        for suffix in ('.json', '.tar.gz'):
            path = work / (stem + suffix); retain(path.name, path)
        apt_receipts = []; native_groups = []; specifications = {}
        for backend in backends:
            out = work / ('apt-' + backend)
            receipt = apt.package(candidate / item['archive'], candidate / item['manifest'],
                value['version'] + '+r' + str(value['package_release']), TARGETS[value['target']][1], backend, out)
            apt_receipts.append(out / (receipt['package'] + '.json'))
            ref = lambda logical: {'url': base_url(value) + retained[logical],
                                   'sha256': archive.digest(stage / retained[logical])}
            dependencies = ['application/' + path for path in identity['files'] if path.startswith('dependencies/')]
            primary = next(path for path in dependencies if path.startswith('application/dependencies/' + item['sdk_recipe'] + '/') and path.endswith('-binary.tar.gz'))
            spec = dict(schema_version=distro.CURRENT_SCHEMA, version=value['version'], package_release=value['package_release'],
                architecture=TARGETS[value['target']][0], backend=backend,
                archive_url=ref('application/' + item['archive'])['url'], archive_sha256=item['sha256'],
                license_files=value['license_files'], redistribution_approved=True,
                application_source=ref('application/' + manifest['source']['archive']), packaging_tool=packaging,
                sdk=ref(primary), dependencies=[ref(path) for path in dependencies if path != primary],
                runtime_dependencies=value['runtime_dependencies'])
            spec_path = work / (backend + '.json'); archive.write_json(spec_path, spec)
            group = work / ('native-' + backend); distro.package(candidate / item['archive'], candidate / item['manifest'], spec_path, group)
            native_groups.append(group); specifications[backend] = spec
        apt.repository(apt_receipts, channels / 'apt', base_url(value), key, value['trusted_fingerprint'], value['sequence'], value['valid_days'])
        distro.assemble(native_groups, channels / 'native', key, value['trusted_fingerprint'], value['sequence'], value['valid_days'])
        apt_names = sorted(path.name for path in (channels / 'apt').iterdir())
        arch_names = sorted(path.name for path in (channels / 'native/arch').iterdir())
        for path in [*(channels / 'apt').iterdir(), *(channels / 'native/arch').iterdir()]:
            copy_new(path, stage / path.name)
        archive.archive_tree(channels, stage / 'channels.tar.gz')
        (stage / 'INSTALL.md').write_bytes(instructions(value, backends, native_only=True))
        frozen = dict(schema_version=1, request=value, tag=tag_for(value), application_release_id=info['id'],
            delivery_sha256=delivery.sha(archive.encoded(identity)), certificate=evidence,
            policy_sha256=archive.digest(policy), packaging_source_proof=packaging_proof, backends=backends, retained=retained,
            apt_files=apt_names, arch_files=arch_names, specifications=specifications,
            files={path.name: asset_info(path) for path in sorted(stage.iterdir())})
        if len(frozen['files']) + 2 > 1000 or any(row['size'] > MAX_ASSET for row in frozen['files'].values()):
            raise ValueError('distribution exceeds per-release or per-asset limits; do not partially publish')
        archive.write_json(stage / 'distribution.json', frozen)
        with distro.signing(key, value['trusted_fingerprint']) as (public, sign):
            if public != (stage / 'archive-keyring.gpg').read_bytes(): raise ValueError('channel signing keys differ')
            (stage / 'distribution.json.sig').write_bytes(sign((stage / 'distribution.json').read_bytes()))
        verify(stage, policy, value['trusted_fingerprint'])
        # Reconcile frozen remote identities and digests without downloading again.
        remote.unchanged(identity['tag'], info, assets, identity['tag_commit'])
        stage.rename(output)
    return frozen


class LocalEvidence:
    """Replay the existing certificate verifier from retained exact bytes."""
    def __init__(self, paths): self.paths = paths
    def download(self, row, path, expected=None):
        source = self.paths[row['name']]
        if asset_info(source) != {'size': row['size'], 'sha256': row['digest'][7:]} or expected not in (None, row['digest'][7:]):
            raise ValueError('retained certificate changed')
        copy_new(source, path)


class CertificateCache:
    """Download each exact certificate asset once, then verify/copy those bytes."""
    def __init__(self, remote, directory, value):
        self.remote, self.directory = remote, Path(directory)
        stem = f'certification-{value["certificate_run"]}-attempt-{value["certificate_attempt"]}'
        self.names = {stem + suffix for suffix in ('.json', '.tar.gz')}

    def download(self, row, path, expected=None):
        if row['name'] not in self.names:
            raise ValueError('unexpected certificate cache asset')
        cached = self.directory / row['name']
        if not cached.exists():
            self.remote.download(row, cached, expected)
        LocalEvidence({row['name']: cached}).download(row, path, expected)


def verify(directory, policy, trusted):
    directory = Path(directory).resolve(strict=True); policy = Path(policy)
    raw, _ = distro.ordinary(directory / 'distribution.json', 8 * 1024 * 1024)
    value = delivery.parse(raw)
    fields = {'schema_version', 'request', 'tag', 'application_release_id', 'delivery_sha256', 'certificate',
              'policy_sha256', 'packaging_source_proof', 'backends', 'retained', 'apt_files', 'arch_files', 'specifications', 'files'}
    if (not isinstance(value, dict) or set(value) != fields or type(value['schema_version']) is not int or value['schema_version'] != 1 or
            not delivery.positive(value['application_release_id'])):
        raise ValueError('complete signed distribution manifest required')
    req = request(value['request'])
    if req['trusted_fingerprint'] != apt.full_fingerprint(trusted) or value['tag'] != tag_for(req) or value['policy_sha256'] != archive.digest(policy):
        raise ValueError('trusted policy or channel identity differs')
    distro.verify_signature(raw, distro.ordinary(directory / 'distribution.json.sig')[0],
                           distro.ordinary(directory / 'archive-keyring.gpg')[0], trusted)
    files = value['files']
    if not isinstance(files, dict) or len(files) > 998 or {p.name for p in directory.iterdir()} != set(files) | CONTROL:
        raise ValueError('complete flat distribution asset inventory differs')
    for name, item in files.items():
        delivery.valid_name(name); path = archive.checked_file(directory, name)
        if not isinstance(item, dict) or set(item) != {'size', 'sha256'} or type(item['size']) is not int or not 0 <= item['size'] <= MAX_ASSET or asset_info(path) != item:
            raise ValueError('distribution asset bytes differ')
    retained = value['retained']
    if not isinstance(retained, dict): raise ValueError('retained application inventory missing')
    for logical, name in retained.items():
        archive.relative(logical)
        if (name not in files or not name.startswith('sha256-' + files[name]['sha256'] + '-') or
                not name[len('sha256-' + files[name]['sha256'] + '-'):]):
            raise ValueError('content-addressed retained alias differs')
    load = lambda name: archive.read_json(directory / retained[name])
    identity = load('delivery.json')
    if value['delivery_sha256'] != delivery.sha(archive.encoded(identity)) or identity['inventory_sha256'] != req['inventory_sha256'] or identity['repository'] != req['repository'] or identity['tag'] != req['application_tag']:
        raise ValueError('retained application provenance differs')
    stem = f'certification-{req["certificate_run"]}-attempt-{req["certificate_attempt"]}'
    required = {'delivery.json', 'policy.json', 'packaging-source.tar.gz', stem + '.json', stem + '.tar.gz'} | {'application/' + path for path in identity['files']}
    if set(retained) != required or archive.digest(directory / retained['policy.json']) != value['policy_sha256']:
        raise ValueError('retained complete application, certificate and policy closure differs')
    verify_source_commit(directory / retained['packaging-source.tar.gz'], value['packaging_source_proof'], req['packager_commit'])
    with tempfile.TemporaryDirectory(prefix='distribution-verify-') as temporary:
        temporary = Path(temporary); candidate = temporary / 'application'; candidate.mkdir()
        for name, row in identity['files'].items():
            path = candidate / archive.relative(name); path.parent.mkdir(parents=True, exist_ok=True)
            copy_new(directory / retained['application/' + name], path)
            if asset_info(path) != {'size': row['size'], 'sha256': row['sha256']}: raise ValueError('retained delivery asset differs')
        delivery.validate_delivery(identity, candidate); manifest = release.verify_release(candidate); item, backends = selected(manifest, req)
        if any(entry['backends'] for entry in manifest['artifacts']): distro.require_gui_terms()
        if value['backends'] != backends or set(value['specifications']) != set(backends): raise ValueError('channel variants differ from certified inventory')
        certpaths = {stem + suffix: directory / retained[stem + suffix] for suffix in ('.json', '.tar.gz')}
        certassets = {name: dict(name=name, size=path.stat().st_size, digest='sha256:' + archive.digest(path)) for name, path in certpaths.items()}
        observed = delivery.verify_certificate(LocalEvidence(certpaths), certassets, identity, candidate, policy,
            req['profile'], req['certificate_run'], req['certificate_attempt'], req['certificate_sha256'])
        if observed != value['certificate']: raise ValueError('retained certificate does not reproduce')
        channels = archive.extract(directory / 'channels.tar.gz', temporary / 'channels', max_bytes=distro.MAX_BYTES * 2)
        # Tar transport contains files only; normalize our freshly created implicit directories.
        for path in channels.rglob('*'):
            if path.is_dir(): path.chmod(0o755)
        if {p.name for p in channels.iterdir()} != {'apt', 'native'}: raise ValueError('unexpected channel archive contents')
        apt_state = apt.verify_repository(channels / 'apt', trusted); native = distro.verify(channels / 'native', trusted)
        if apt_state['sequence'] != req['sequence'] or native['sequence'] != req['sequence'] or native['architecture'] != TARGETS[req['target']][0]: raise ValueError('channel target or sequence differs')
        apt_meta = archive.read_json(channels / 'apt/repository.json')
        if apt_meta['base_url'] != base_url(req): raise ValueError('APT immutable base URL differs')
        seen = set()
        for row in apt_meta['packages']:
            receipt = archive.read_json(channels / 'apt' / row['receipt'])
            if (receipt['backend'] in seen or receipt['backend'] not in backends or receipt['archive_sha256'] != item['sha256'] or
                    receipt['archive_manifest'] != archive.read_json(candidate / item['manifest']) or
                    receipt['architecture'] != TARGETS[req['target']][1] or receipt['version'] != req['version'] + '+r' + str(req['package_release'])):
                raise ValueError('APT package differs from certified archive or selected version')
            seen.add(receipt['backend'])
        if seen != set(backends): raise ValueError('APT variants omit certified native backends')
        for names, root in ((value['apt_files'], channels / 'apt'), (value['arch_files'], channels / 'native/arch')):
            if not isinstance(names, list) or len(names) != len(set(names)) or set(names) != {p.name for p in root.iterdir()}: raise ValueError('flat package channel inventory differs')
            for name in names:
                if asset_info(root / name) != files.get(name): raise ValueError('flat channel payload differs')
        if {spec['backend']: spec for spec in native['packages'].values()} != value['specifications']:
            raise ValueError('signed recipe provenance differs')
        ref = lambda logical: {'url': base_url(req) + retained[logical], 'sha256': files[retained[logical]]['sha256']}
        dependency_names = ['application/' + path for path in identity['files'] if path.startswith('dependencies/')]
        primary = next(path for path in dependency_names if path.startswith('application/dependencies/' + item['sdk_recipe'] + '/') and path.endswith('-binary.tar.gz'))
        for backend, spec in value['specifications'].items():
            if (spec['application_source'] != ref('application/' + manifest['source']['archive']) or
                    spec['packaging_tool'] != ref('packaging-source.tar.gz') or spec['sdk'] != ref(primary) or
                    spec['dependencies'] != [ref(path) for path in dependency_names if path != primary] or
                    spec['archive_url'] != ref('application/' + item['archive'])['url'] or
                    spec['license_files'] != req['license_files'] or spec['runtime_dependencies'] != req['runtime_dependencies']):
                raise ValueError('recipe retained source, SDK or dependency roles differ')
            if (spec['backend'] != backend or spec['archive_sha256'] != item['sha256'] or spec['version'] != req['version'] or
                    spec['package_release'] != req['package_release'] or spec['architecture'] != TARGETS[req['target']][0]):
                raise ValueError('signed package differs from selected certified archive')
            for reference in [dict(url=spec['archive_url'], sha256=spec['archive_sha256']), spec['application_source'], spec['packaging_tool'], spec['sdk'], *spec['dependencies']]:
                name = reference['url'].removeprefix(base_url(req))
                if reference['url'] != base_url(req) + name or name not in retained.values() or files[name]['sha256'] != reference['sha256']:
                    raise ValueError('recipe does not resolve to retained content-addressed bytes')
        if (directory / 'INSTALL.md').read_bytes() not in (instructions(req, backends), instructions(req, backends, native_only=True)):
            raise ValueError('installation instructions differ')
    expected_files = set(retained.values()) | set(value['apt_files']) | set(value['arch_files']) | {'channels.tar.gz', 'INSTALL.md'}
    if set(files) != expected_files: raise ValueError('unreferenced distribution asset')
    return value


def native_marker(value, target=None):
    """Validate the exact public lifecycle marker; signed payload verification is separate."""
    fields = {'schema_version', 'target', 'source_commit', 'run_id', 'attempt', 'checks'}
    if (not isinstance(value, dict) or set(value) != fields or type(value['schema_version']) is not int or value['schema_version'] != 1 or
            value['target'] not in TARGETS or target not in (None, value['target']) or
            not isinstance(value['source_commit'], str) or not delivery.OID.fullmatch(value['source_commit']) or
            not delivery.positive(value['run_id']) or not delivery.positive(value['attempt'])):
        raise ValueError('complete native qualification marker required')
    expected = {'apt-bookworm', 'apt-trixie', 'apt-ubuntu'}
    if value['target'] == 'linux-x86_64': expected |= {'arch', 'gentoo'}
    if (not isinstance(value['checks'], dict) or set(value['checks']) != expected or
            any(not isinstance(item, str) or not delivery.SHA.fullmatch(item) for item in value['checks'].values())):
        raise ValueError('native qualification marker omits a required frontend')
    return value


NATIVE_ASSETS = CONTROL | {'archive-keyring.gpg', 'channels.tar.gz'}


def native_descriptor(directory, policy, trusted):
    """Authenticate the complete signed descriptor without replaying SDK recovery.

    A native installation consumes channel packages, while publication separately
    verifies every retained source/SDK/certificate byte through ``verify``.
    """
    directory = Path(directory)
    raw, _ = distro.ordinary(directory / 'distribution.json', 8 * 1024 * 1024)
    value = delivery.parse(raw)
    fields = {'schema_version', 'request', 'tag', 'application_release_id', 'delivery_sha256', 'certificate',
              'policy_sha256', 'packaging_source_proof', 'backends', 'retained', 'apt_files', 'arch_files', 'specifications', 'files'}
    if (not isinstance(value, dict) or set(value) != fields or type(value['schema_version']) is not int or
            value['schema_version'] != 1 or not delivery.positive(value['application_release_id'])):
        raise ValueError('complete signed distribution manifest required')
    req = request(value['request'])
    if req['trusted_fingerprint'] != apt.full_fingerprint(trusted) or value['tag'] != tag_for(req) or value['policy_sha256'] != archive.digest(policy):
        raise ValueError('trusted policy or channel identity differs')
    distro.verify_signature(raw, distro.ordinary(directory / 'distribution.json.sig')[0],
                           distro.ordinary(directory / 'archive-keyring.gpg')[0], trusted)
    files = value['files']
    if not isinstance(files, dict) or not NATIVE_ASSETS - CONTROL <= files.keys() or len(files) > 998:
        raise ValueError('complete signed asset inventory required')
    for name, item in files.items():
        delivery.valid_name(name)
        if (not isinstance(item, dict) or set(item) != {'size', 'sha256'} or type(item['size']) is not int or
                not 0 <= item['size'] <= MAX_ASSET or not delivery.SHA.fullmatch(str(item['sha256']))):
            raise ValueError('invalid signed asset identity')
    if asset_info(directory / 'archive-keyring.gpg') != files['archive-keyring.gpg']:
        raise ValueError('signed keyring bytes differ')
    if (not isinstance(value['backends'], list) or not value['backends'] or
            len(value['backends']) != len(set(value['backends'])) or set(value['backends']) - distro.BACKENDS or
            not isinstance(value['specifications'], dict) or set(value['specifications']) != set(value['backends'])):
        raise ValueError('complete signed backend inventory required')
    retained = value['retained']
    if not isinstance(retained, dict): raise ValueError('retained application inventory missing')
    for logical, name in retained.items():
        archive.relative(logical)
        if name not in files or not name.startswith('sha256-' + files[name]['sha256'] + '-'):
            raise ValueError('content-addressed retained alias differs')
    for names in (value['apt_files'], value['arch_files']):
        if not isinstance(names, list) or len(names) != len(set(names)):
            raise ValueError('complete signed package file inventory required')
        for name in names: delivery.valid_name(name)
    expected = set(retained.values()) | set(value['apt_files']) | set(value['arch_files']) | {'channels.tar.gz', 'INSTALL.md'}
    if set(files) != expected: raise ValueError('unreferenced distribution asset')
    for backend, spec in value['specifications'].items():
        distro.validate_spec(spec)
        if (spec['backend'] != backend or spec['architecture'] != TARGETS[req['target']][0] or
                spec['version'] != req['version'] or spec['package_release'] != req['package_release'] or
                spec['license_files'] != req['license_files'] or spec['runtime_dependencies'] != req['runtime_dependencies']):
            raise ValueError('signed package specification differs from request')
        for reference in [dict(url=spec['archive_url'], sha256=spec['archive_sha256']),
                          spec['application_source'], spec['packaging_tool'], spec['sdk'], *spec['dependencies']]:
            name = reference['url'].removeprefix(base_url(req))
            if reference['url'] != base_url(req) + name or name not in retained.values() or files[name]['sha256'] != reference['sha256']:
                raise ValueError('recipe does not resolve to signed retained assets')
    return value


def verify_native_channels(channels, value, trusted):
    """Verify every installed package/recipe, including independent native signatures."""
    channels = Path(channels); req = value['request']
    if {p.name for p in channels.iterdir()} != {'apt', 'native'}:
        raise ValueError('unexpected channel archive contents')
    state = apt.verify_repository(channels / 'apt', trusted)
    native = distro.verify(channels / 'native', trusted)
    if state['sequence'] != req['sequence'] or native['sequence'] != req['sequence'] or native['architecture'] != TARGETS[req['target']][0]:
        raise ValueError('channel target or sequence differs')
    if {spec['backend']: spec for spec in native['packages'].values()} != value['specifications']:
        raise ValueError('signed recipe provenance differs')
    metadata = archive.read_json(channels / 'apt/repository.json')
    if metadata['base_url'] != base_url(req): raise ValueError('APT immutable base URL differs')
    seen = set()
    for row in metadata['packages']:
        receipt = archive.read_json(channels / 'apt' / row['receipt']); backend = receipt['backend']
        if backend in seen or backend not in value['backends']:
            raise ValueError('APT package backend differs')
        spec = value['specifications'][backend]
        retained_manifest = archive.read_json(channels / 'native/packages' / (spec['architecture'] + '-' + backend) / 'portable-manifest.json')
        if (receipt['archive_sha256'] != spec['archive_sha256'] or receipt['archive_manifest'] != retained_manifest or
                receipt['architecture'] != TARGETS[req['target']][1] or
                receipt['version'] != req['version'] + '+r' + str(req['package_release'])):
            raise ValueError('APT package differs from signed archive or selected version')
        seen.add(backend)
    if seen != set(value['backends']): raise ValueError('APT variants omit signed native backends')
    for names, root in ((value['apt_files'], channels / 'apt'), (value['arch_files'], channels / 'native/arch')):
        if not isinstance(names, list) or len(names) != len(set(names)) or set(names) != {p.name for p in root.iterdir()}:
            raise ValueError('flat package channel inventory differs')
        for name in names:
            if asset_info(root / name) != value['files'].get(name): raise ValueError('flat channel payload differs')
    return value


def verify_native(directory, policy, trusted):
    """Verify a native-consumer projection; full inputs retain full verification."""
    directory = Path(directory).resolve(strict=True)
    names = {p.name for p in directory.iterdir()}
    if names != NATIVE_ASSETS:
        # Preserve legacy complete prepared generations and their recovery checks.
        return verify(directory, policy, trusted)
    value = native_descriptor(directory, policy, trusted)
    if asset_info(directory / 'channels.tar.gz') != value['files']['channels.tar.gz']:
        raise ValueError('signed channel archive bytes differ')
    with tempfile.TemporaryDirectory(prefix='native-channel-verify-') as temporary:
        channels = archive.extract(directory / 'channels.tar.gz', Path(temporary) / 'channels', max_bytes=distro.MAX_BYTES * 2)
        # Tar transports files only; normalize only fresh owned implicit directories.
        channels.chmod(0o755)
        for path in channels.rglob('*'):
            if path.is_dir(): path.chmod(0o755)
        verify_native_channels(channels, value, trusted)
    return value


def remote_native_descriptor(repository, tag, manifest_sha256, output, policy, trusted, transport=None):
    """Fetch three small controls and reconcile the complete immutable remote inventory."""
    delivery.location(repository, tag)
    if not delivery.SHA.fullmatch(manifest_sha256): raise ValueError('exact distribution manifest digest required')
    output = Path(output); output.mkdir()
    remote = delivery.Remote(repository, transport); info = remote.find(tag); rows = remote.assets(info)
    if info['draft']: raise ValueError('public non-Latest package channel required')
    if len(rows) > 1000 or any(row['size'] > MAX_ASSET for row in rows.values()):
        raise ValueError('remote distribution exceeds bounded asset limits')
    if 'distribution.json' not in rows or rows['distribution.json']['size'] > 8 * 1024 * 1024:
        raise ValueError('bounded distribution descriptor missing')
    remote.download(rows['distribution.json'], output / 'distribution.json', manifest_sha256)
    for name in ('distribution.json.sig', 'archive-keyring.gpg'):
        if name not in rows or rows[name]['size'] > 8 * 1024 * 1024: raise ValueError('bounded signed channel control missing')
        remote.download(rows[name], output / name)
    value = native_descriptor(output, policy, trusted)
    if value['request']['repository'] != repository or value['tag'] != tag: raise ValueError('remote distribution identity differs')
    if set(rows) != set(value['files']) | CONTROL:
        raise ValueError('remote channel inventory differs')
    for name, item in value['files'].items():
        if rows[name]['size'] != item['size'] or rows[name]['digest'] != 'sha256:' + item['sha256']:
            raise ValueError('remote asset identity differs from signed inventory')
    if not info['prerelease']:
        body = delivery.parse(info.get('body', ''))
        if body.get('kind') != 'signed-distribution' or body.get('manifest_sha256') != manifest_sha256:
            raise ValueError('accepted channel requires its native qualification marker')
        native_marker(body.get('native_qualification'), value['request']['target'])
    remote.unchanged(tag, info, rows, value['request']['packager_commit']); remote.not_latest(info)
    return value, remote, info, rows


def fetch(repository, tag, manifest_sha256, output, policy, trusted, *, transport=None, native_only=False, reuse=None):
    delivery.location(repository, tag)
    if not delivery.SHA.fullmatch(manifest_sha256): raise ValueError('exact distribution manifest digest required')
    output = Path(output).absolute()
    if output.exists() or output.is_symlink(): raise ValueError('new fetched distribution output required')
    output.parent.mkdir(parents=True, exist_ok=True)
    if native_only:
        with tempfile.TemporaryDirectory(prefix='.native-fetch-', dir=output.parent) as temporary:
            stage = Path(temporary) / 'assets'
            value, remote, info, rows = remote_native_descriptor(repository, tag, manifest_sha256, stage, policy, trusted, transport)
            item = value['files']['channels.tar.gz']; cached = Path(reuse) / 'channels.tar.gz' if reuse else None
            if cached is not None and cached.exists():
                # Reuse only exact authenticated bytes, copied without mutable hard links.
                if cached.is_symlink(): raise ValueError('linked reusable channel asset')
                if asset_info(cached) == item:
                    copy_new(cached, stage / 'channels.tar.gz')
                    if asset_info(stage / 'channels.tar.gz') != item: raise ValueError('reused channel bytes changed during copy')
                else:
                    remote.download(rows['channels.tar.gz'], stage / 'channels.tar.gz', item['sha256'])
            else:
                remote.download(rows['channels.tar.gz'], stage / 'channels.tar.gz', item['sha256'])
            value = verify_native(stage, policy, trusted)
            remote.unchanged(tag, info, rows, value['request']['packager_commit']); remote.not_latest(info)
            stage.rename(output)
        return value
    remote = delivery.Remote(repository, transport); info = remote.find(tag); rows = remote.assets(info)
    if info['draft']: raise ValueError('public non-Latest package channel required')
    if not info['prerelease']:
        body = delivery.parse(info.get('body', ''))
        if (body.get('kind') != 'signed-distribution' or body.get('manifest_sha256') != manifest_sha256 or
                not isinstance(body.get('native_qualification'), dict)):
            raise ValueError('accepted channel requires its native qualification marker')
        native_marker(body['native_qualification'])
    if len(rows) > 1000 or any(row['size'] > MAX_ASSET for row in rows.values()):
        raise ValueError('remote distribution exceeds bounded asset limits')
    with tempfile.TemporaryDirectory(prefix='.distribution-fetch-', dir=output.parent) as temporary:
        stage = Path(temporary) / 'assets'; stage.mkdir()
        if 'distribution.json' not in rows or rows['distribution.json']['size'] > 8 * 1024 * 1024: raise ValueError('bounded distribution descriptor missing')
        remote.download(rows['distribution.json'], stage / 'distribution.json', manifest_sha256)
        value = archive.read_json(stage / 'distribution.json')
        expected = set(value['files']) | CONTROL
        if set(rows) != expected: raise ValueError('remote channel inventory differs')
        selections = []
        for name in sorted(expected - {'distribution.json'}):
            delivery.valid_name(name)
            expected_hash = value['files'][name]['sha256'] if name in value['files'] else None
            selections.append((name, stage / name, expected_hash))
        delivery.download_files(remote, rows, selections)
        value = verify(stage, policy, trusted)
        if value['request']['repository'] != repository or value['tag'] != tag: raise ValueError('remote distribution identity differs')
        if not info['prerelease']: native_marker(body['native_qualification'], value['request']['target'])
        remote.unchanged(tag, info, rows, value['request']['packager_commit']); remote.not_latest(info)
        stage.rename(output)
    return value


def initialize_channel(remote, tag, commit, body):
    """Only a confirmed atomic tag-creation winner may create the draft once."""
    ref = remote.reference(tag, missing=True)
    if ref not in (None, commit): raise ValueError('distribution tag source differs')
    owns_initialization = False
    if ref is None:
        try:
            remote.change('/git/refs', body={'ref': 'refs/tags/' + tag, 'sha': commit})
            owns_initialization = True
        except delivery.DeliveryError:
            if remote.reference(tag, missing=True) != commit: raise
    response, creation_error = None, None
    if owns_initialization:
        try:
            response = remote.info(remote.change('/releases', body=dict(tag_name=tag,
                target_commitish=commit, name=tag, body=body, draft=True,
                prerelease=True, make_latest='false')), tag)
        except delivery.DeliveryError as error:
            creation_error = error
    try:
        existing = remote.wait_find(tag, release_id=response['id'] if response else None)
    except delivery.DeliveryError:
        if creation_error is not None: raise creation_error
        raise
    if (not existing['draft'] or not existing['prerelease'] or existing['name'] != tag or
            existing.get('body') != body or remote.reference(tag) != commit):
        raise ValueError('initialized distribution draft identity differs')
    return existing


def upload_files(remote, tag, directory, names, *, release_info=None):
    """Four independent writes at most; join a failed batch before returning."""
    names = list(names)
    if len(names) != len(set(names)):
        raise ValueError('upload asset names must be distinct')
    # Control records are a commit gate and follow every successfully joined payload.
    groups = ([name for name in names if name not in CONTROL],
              [name for name in names if name in CONTROL])
    with ThreadPoolExecutor(max_workers=4) as pool:
        for group in groups:
            for start in range(0, len(group), 4):
                futures = [pool.submit(remote.upload_to, release_info, Path(directory) / name)
                           if release_info is not None else
                           pool.submit(remote.upload, tag, Path(directory) / name)
                           for name in group[start:start + 4]]
                for future in futures:
                    future.result()


def publish(directory, policy, trusted, *, execute=False, transport=None):
    directory = Path(directory); frozen = verify(directory, policy, trusted); req = frozen['request']; result = plan(req)
    result['manifest_sha256'] = archive.digest(directory / 'distribution.json')
    if not execute: return result
    remote = delivery.Remote(req['repository'], transport)
    def act():
        remote.visible()
        with tempfile.TemporaryDirectory(prefix='distribution-authority-') as temporary:
            # Full local closure was verified above; reconcile exact remote metadata.
            candidate = Path(temporary) / 'candidate'; candidate.mkdir()
            identity = archive.read_json(directory / frozen['retained']['delivery.json'])
            copy_new(directory / frozen['retained']['application/release.json'], candidate / 'release.json')
            stem = f'certification-{req["certificate_run"]}-attempt-{req["certificate_attempt"]}'
            certpaths = {stem + suffix: directory / frozen['retained'][stem + suffix]
                         for suffix in ('.json', '.tar.gz')}
            info, app_assets, evidence = certified(remote, candidate, identity, policy, req, certificate_paths=certpaths)
            if evidence != frozen['certificate']: raise ValueError('certified application evidence changed')
            if info['id'] != frozen['application_release_id'] or delivery.sha(archive.encoded(identity)) != frozen['delivery_sha256']:
                raise ValueError('certified application remote identity changed')
            tag = frozen['tag']; existing = remote.find(tag, required=False)
            body = json.dumps({'kind': 'signed-distribution', 'manifest_sha256': result['manifest_sha256']}, sort_keys=True)
            if existing is None:
                existing = initialize_channel(remote, tag, req['packager_commit'], body)
            if not existing['draft'] and not existing['prerelease']:
                accepted = delivery.parse(existing.get('body', ''))
                native_marker(accepted.get('native_qualification'), req['target'])
                if set(accepted) != {'kind', 'manifest_sha256', 'native_qualification'} or accepted['kind'] != 'signed-distribution' or accepted['manifest_sha256'] != result['manifest_sha256']:
                    raise ValueError('accepted immutable channel identity differs')
                body = existing['body']
            if existing['name'] != tag or existing.get('body') != body or remote.reference(tag) != req['packager_commit']:
                raise ValueError('immutable distribution release identity differs')
            expected = {p.name: asset_info(p) for p in directory.iterdir()}; rows = remote.assets(existing)
            if set(rows) - set(expected): raise ValueError('unexpected distribution release assets; preserve state')
            if not existing['draft'] and set(rows) != set(expected): raise ValueError('published channel is incomplete; never repair in place')
            for name in rows:
                if rows[name]['digest'] != 'sha256:' + expected[name]['sha256'] or rows[name]['size'] != expected[name]['size']:
                    raise ValueError('existing immutable channel bytes differ; never overwrite')
            upload_files(remote, tag, directory, sorted(set(expected) - set(rows)), release_info=existing)
            rows = remote.assets(existing)
            if set(rows) != set(expected) or any(rows[name]['size'] != record['size'] or
                    rows[name]['digest'] != 'sha256:' + record['sha256'] for name, record in expected.items()):
                raise ValueError('uploaded complete asset identities differ')
            if existing['draft']:
                # First publication proves the full delivered closure. Identical
                # public retries reconcile every immutable asset ID and digest.
                with tempfile.TemporaryDirectory(prefix='distribution-readback-') as downloaded:
                    downloaded = Path(downloaded)
                    delivery.download_files(remote, rows, [(name, downloaded / name, record['sha256'])
                                                          for name, record in expected.items()])
                    if verify(downloaded, policy, trusted) != frozen: raise ValueError('downloaded signed channel differs')
            remote.unchanged(req['application_tag'], info, app_assets, identity['tag_commit'])
            if ({path.name: asset_info(path) for path in directory.iterdir()} != expected or
                    archive.digest(policy) != frozen['policy_sha256']):
                raise ValueError('local channel or policy changed before publication')
            remote.unchanged(tag, existing, rows, req['packager_commit'])
            if existing['draft']:
                remote.change('/releases/' + str(existing['id']), method='PATCH', body={'draft': False, 'prerelease': True, 'make_latest': 'false'})
            final = remote.by_id(existing['id'], tag)
            if (final['id'] != existing['id'] or final['draft'] or final['prerelease'] != existing['prerelease'] or remote.assets(final) != rows or
                    remote.reference(tag) != req['packager_commit'] or final.get('body') != body):
                raise ValueError('published channel state differs')
            remote.not_latest(final)
            return dict(result, execute=True, release_id=final['id'])
    return delivery.run_mutation(remote, act)


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__); p.add_argument('operation', choices=('plan', 'prepare', 'verify', 'publish', 'fetch'))
    p.add_argument('--request', type=Path); p.add_argument('--directory', type=Path); p.add_argument('--output', type=Path)
    p.add_argument('--policy', type=Path, default=ROOT / 'docs/release-policy.json'); p.add_argument('--trusted-fingerprint')
    p.add_argument('--signing-key', type=Path); p.add_argument('--execute', action='store_true')
    p.add_argument('--repository'); p.add_argument('--tag'); p.add_argument('--manifest-sha256')
    p.add_argument('--native-only', action='store_true', help='verify/fetch the signed native channel projection')
    args = p.parse_args(argv)
    if args.native_only and args.operation not in ('verify', 'fetch'):
        p.error('--native-only applies only to verify or fetch')
    if args.operation in ('plan', 'prepare'):
        if args.request is None: p.error('--request required')
        req = request(archive.read_json(args.request)); result = plan(req)
        if args.operation == 'prepare':
            if args.output is None or args.signing_key is None: p.error('--output and --signing-key required')
            # Freeze the actual packaging checkout, including its clean commit identity.
            head = subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=ROOT, check=True, capture_output=True, text=True).stdout.strip()
            clean = subprocess.run(['git', 'status', '--porcelain', '--untracked-files=normal'], cwd=ROOT, check=True, capture_output=True, text=True).stdout
            if head != req['packager_commit'] or clean: raise ValueError('packaging checkout must be clean at its exact recorded commit')
            with tempfile.TemporaryDirectory(prefix='distribution-inputs-') as temporary:
                work = Path(temporary); identity = ci.fetch_candidate(req['repository'], req['application_tag'], req['inventory_sha256'], work / 'input')
                source_identity.archive_source(ROOT, work / 'packaging-source.tar.gz')
                result = prepare(req, work / 'input/candidate', identity, args.policy, work / 'packaging-source.tar.gz', args.output, args.signing_key)
    elif args.operation == 'fetch':
        if not all((args.repository, args.tag, args.manifest_sha256, args.output, args.trusted_fingerprint)): p.error('fetch needs exact repository/tag/manifest, output and trusted fingerprint')
        result = fetch(args.repository, args.tag, args.manifest_sha256, args.output, args.policy, args.trusted_fingerprint, native_only=args.native_only)
    else:
        if not args.directory or not args.trusted_fingerprint: p.error('--directory and --trusted-fingerprint required')
        result = (publish(args.directory, args.policy, args.trusted_fingerprint, execute=args.execute) if args.operation == 'publish'
                  else (verify_native if args.native_only else verify)(args.directory, args.policy, args.trusted_fingerprint))
    print(json.dumps(result, sort_keys=True, indent=2))


if __name__ == '__main__':
    delivery.enable_metrics()
    try: main()
    except (ValueError, OSError, delivery.DeliveryError, subprocess.CalledProcessError) as error:
        raise SystemExit('distribution-release: ' + str(error) + '; retain outputs and remote state for reconciliation')
