#!/usr/bin/env python3
"""Freeze, execute and replay native checks for packages in an app candidate."""
import argparse
import json
import os
from pathlib import Path
import shutil

import ci_plan as ci
import dependency_archive as archive
import distro_check as native
import github_release as delivery
import release
import release_packages as packages

ROOT = Path(__file__).resolve().parents[1]
PLAN = ROOT / 'build/package-plan.json'
CONTROLS = ROOT / 'build/package-control'
CHECK = 'native-packages'
TARGETS = tuple(packages.TARGETS)


def previous_packages(raw):
    value = delivery.parse(raw)
    if not isinstance(value, dict) or set(value) != set(TARGETS):
        raise ValueError('exact native upgrade selections required for both Linux targets')
    result = {target: native.selection(json.dumps(item)) for target, item in value.items()}
    if any(item['target'] != target for target, item in result.items()):
        raise ValueError('native upgrade selection target differs')
    return result


def matrix():
    return {'include': [dict(row, native_id=row['id'], id=target + '-' + row['id'])
                        for target in TARGETS for row in native.matrix(target)['include']]}


def workflow():
    reference = os.environ['GITHUB_WORKFLOW_REF']
    prefix = os.environ['GITHUB_REPOSITORY'] + '/.github/workflows/'
    if not reference.startswith(prefix) or '@' not in reference[len(prefix):]:
        raise ValueError('exact repository workflow reference required')
    return reference[len(prefix):].split('@', 1)[0]


def control_name(selected):
    return 'packages.json' if selected.get('format') == 'release-packages' else 'distribution.json'


def download_controls(remote, selected, output):
    info = remote.published(selected['tag']); assets = remote.assets(info)
    name = control_name(selected)
    output.mkdir(parents=True, exist_ok=False)
    for filename in (name, name + '.sig', 'archive-keyring.gpg'):
        if filename not in assets:
            raise ValueError('published signed package control absent: ' + filename)
        if not 0 < assets[filename]['size'] <= packages.MAX_CONTROL:
            raise ValueError('published signed package control exceeds its byte bound')
        remote.download(assets[filename], output / filename,
                        selected['manifest_sha256'] if filename == name else None)
    remote.unchanged(selected['tag'], info, assets)


def identities(manifest, plan, controls):
    """Metadata-only replay authenticates the complete signed payload anchors."""
    current = controls / 'current'
    value = packages.binding(current, manifest)
    if value['policy_sha256'] != archive.digest(ROOT / 'docs/release-policy.json'):
        raise ValueError('signed package policy differs from certification policy')
    req = value['request']
    if (req['repository'], req['application_tag'], req['source_commit']) != (
            plan['repository'], plan['tag'], plan['application_source_commit']):
        raise ValueError('native package application provenance differs')
    result = {}
    for target in TARGETS:
        selected = native.selection(json.dumps(plan['selected'][target]))
        expected = dict(format='release-packages', target=target, tag=plan['tag'],
                        manifest_sha256=manifest['files']['packages.json'])
        if selected != expected:
            raise ValueError('native package selection differs from ordinary inventory')
        view = packages.native_identity(current, plan['trusted_fingerprint'], target=target)
        prior = native.selection(json.dumps(plan['previous'][target]))
        if prior['target'] != target or prior['tag'] == selected['tag']:
            raise ValueError('an older exact native upgrade predecessor is required')
        directory = controls / 'previous' / target
        if archive.digest(directory / control_name(prior)) != prior['manifest_sha256']:
            raise ValueError('native upgrade predecessor manifest differs')
        old = (packages.native_identity(directory, plan['trusted_fingerprint'], target=target)
               if prior.get('format') == 'release-packages' else
               native.release.native_descriptor(directory, ROOT / 'docs/release-policy.json', plan['trusted_fingerprint']))
        if old['request']['target'] != target or old['tag'] != prior['tag']:
            raise ValueError('authenticated native upgrade predecessor differs')
        native.require_version_upgrade(old, view)
        result[target] = view
    return result


def plan():
    identity = ci.fetch_candidate(os.environ['GITHUB_REPOSITORY'], os.environ['TAG'],
        os.environ['INVENTORY'], CONTROLS / 'application', metadata_only=True)
    manifest = release.verify_metadata(CONTROLS / 'application/candidate')
    value = dict(schema_version=1, enabled='packages' in manifest)
    if value['enabled']:
        previous = previous_packages(os.environ['PREVIOUS_PACKAGES'])
        trusted = native.release.apt.full_fingerprint(os.environ['TRUSTED_FINGERPRINT'])
        selected = {target: dict(format='release-packages', tag=os.environ['TAG'], target=target,
                    manifest_sha256=manifest['files']['packages.json']) for target in TARGETS}
        value.update(repository=os.environ['GITHUB_REPOSITORY'], tag=os.environ['TAG'],
            inventory_sha256=os.environ['INVENTORY'], application_source_commit=identity['source_commit'],
            trusted_fingerprint=trusted, selected=selected, previous=previous,
            source_commit=os.environ['GITHUB_SHA'], run_id=os.environ['GITHUB_RUN_ID'],
            attempt=int(os.environ['GITHUB_RUN_ATTEMPT']), workflow=workflow())
        remote = delivery.Remote(value['repository']); remote.visible()
        download_controls(remote, selected[TARGETS[0]], CONTROLS / 'current')
        for target in TARGETS:
            download_controls(remote, previous[target], CONTROLS / 'previous' / target)
        identities(manifest, value, CONTROLS)
    archive.write_json(PLAN, value)
    with Path(os.environ['GITHUB_OUTPUT']).open('a', encoding='utf-8') as stream:
        stream.write('enabled=' + str(value['enabled']).lower() + '\n')
        stream.write('matrix=' + json.dumps(matrix() if value['enabled'] else {'include': []}) + '\n')
    return value


def check():
    ci.restore_run_bundle(os.environ['GITHUB_REPOSITORY'], int(os.environ['GITHUB_RUN_ID']),
        int(os.environ['CONTROL_ATTEMPT']), os.environ['GITHUB_SHA'], workflow(),
        'qualification-inputs-' + os.environ['CONTROL_ATTEMPT'], ROOT / 'build')
    coverage = ci.module('coverage')
    coverage.check_inputs(coverage.load(ROOT / 'build/check-plan.json'), ROOT, metadata_only=True)
    value = archive.read_json(PLAN)
    if not value['enabled'] or value['attempt'] != int(os.environ['GITHUB_RUN_ATTEMPT']):
        raise ValueError('native execution requires its exact current frozen attempt')
    rows = [row for row in matrix()['include'] if row['id'] == os.environ['PACKAGE_CHECK']]
    if len(rows) != 1:
        raise ValueError('unknown required native frontend')
    row = rows[0]; target = row['target']; environment = dict(os.environ)
    environment.update(CHANNEL=json.dumps(value['selected'][target]), PREVIOUS=json.dumps(value['previous'][target]),
        TRUSTED_FINGERPRINT=value['trusted_fingerprint'], CHECK_ID=row['native_id'],
        CHECK_KIND=row['kind'], CHECK_IMAGE=row['image'])
    for name, selected in [('current', value['selected'][target]), ('previous', value['previous'][target])]:
        native.fetch_selected(selected, ROOT / 'build/channels' / name, ROOT / 'docs/release-policy.json',
            value['trusted_fingerprint'], value['repository'],
            reuse=ROOT / 'build/channels/current' if name == 'previous' else None)
    return native.container(ROOT, row['native_id'], environment)


def validate_report(path, manifest, frozen, application):
    path = Path(path); report = archive.read_json(path)
    fields = {'schema_version', 'check', 'status', 'run_id', 'attempt', 'evidence', 'records'}
    if (set(report) != fields or report['schema_version'] != 1 or report['check'] != CHECK or
            report['status'] != 'passed' or report['run_id'] != application['run_id']):
        raise ValueError('complete current native package qualification report required')
    archive.verify_inventory(path.parent, report['evidence'], exclude=(path.name,))
    value = archive.read_json(path.parent / 'package-plan.json')
    if (not value.get('enabled') or value.get('schema_version') != 1 or
            report['evidence']['package-plan.json'] != frozen['inputs'].get('build/package-plan.json') or
            value['inventory_sha256'] != frozen['subject']['inventory_sha256'] or
            value['run_id'] != report['run_id'] or value['attempt'] != report['attempt']):
        raise ValueError('native package controls differ from frozen certification inputs')
    if archive.digest(ROOT / 'docs/release-policy.json') != frozen['inputs'].get('docs/release-policy.json'):
        raise ValueError('native package replay policy differs from frozen policy')
    attempt = application.get('adoption', {}).get('attempt')
    if attempt is None:
        attempts = {item['attempt'] for item in application['checks'].values()}
        if attempts != {report['attempt']}:
            raise ValueError('native checks cannot adopt another certification attempt')
    elif attempt != report['attempt']:
        raise ValueError('native checks require this adoption attempt')
    views = identities(manifest, value, path.parent / 'controls')
    rows = matrix()['include']; records = report['records']
    if (not isinstance(records, dict) or set(records) != {row['id'] for row in rows} or
            len(set(records.values())) != len(rows) or not set(records.values()) <= report['evidence'].keys()):
        raise ValueError('every required native frontend needs one retained receipt')
    markers = {}
    for target in TARGETS:
        selected = [archive.read_json(archive.checked_file(path.parent, records[row['id']]))
                    for row in rows if row['target'] == target]
        environment = dict(GITHUB_SHA=value['source_commit'], GITHUB_RUN_ID=value['run_id'],
            GITHUB_RUN_ATTEMPT=str(value['attempt']), PREVIOUS=json.dumps(value['previous'][target]))
        markers[target] = native.qualification(value['selected'][target], selected, environment)
        for record in selected:
            expected = [dict(backend=backend, **views[target]['payloads'][record['kind']][backend])
                        for backend in views[target]['backends']]
            if sorted(record['backends'], key=lambda item: item['backend']) != sorted(expected, key=lambda item: item['backend']):
                raise ValueError('native installed payload differs from signed application package anchors')
    return dict(manifest_sha256=manifest['files']['packages.json'], tag=value['tag'],
                previous=value['previous'], qualification=markers)


def collect():
    value = archive.read_json(PLAN)
    if not value['enabled']:
        return
    if value['attempt'] != int(os.environ['GITHUB_RUN_ATTEMPT']):
        raise ValueError('native collection cannot reuse an earlier attempt')
    output = ROOT / 'build/package-evidence'; output.mkdir(parents=True, exist_ok=False)
    shutil.copyfile(PLAN, output / 'package-plan.json')
    for name in ('current', 'previous'):
        shutil.copytree(CONTROLS / name, output / 'controls' / name)
    records = {}
    for row in matrix()['include']:
        destination = output / 'native' / row['id']
        receipt = ci.restore_run_bundle(value['repository'], int(value['run_id']), value['attempt'],
            value['source_commit'], value['workflow'],
            'evidence-batch-package-' + row['id'] + '-' + str(value['attempt']), destination)
        transport = output / 'transport' / (row['id'] + '.json'); transport.parent.mkdir(exist_ok=True)
        archive.write_json(transport, receipt)
        records[row['id']] = (destination / 'native/result.json').relative_to(output).as_posix()
    archive.write_json(output / (CHECK + '.result.json'), dict(schema_version=1, check=CHECK,
        status='passed', run_id=value['run_id'], attempt=value['attempt'],
        evidence=archive.file_inventory(output), records=records))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation', choices=('plan', 'check', 'collect'))
    args = parser.parse_args()
    {'plan': plan, 'check': check, 'collect': collect}[args.operation]()


if __name__ == '__main__':
    main()
