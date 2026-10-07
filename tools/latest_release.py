#!/usr/bin/env python3
"""Validate one complete Latest workflow, promoted inventory and retained evidence."""
import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile

import ci_plan as ci
import github_release as delivery

ROOT = Path(__file__).resolve().parents[1]
STAGES = ('prepare', 'regression', 'application', 'certification', 'promotion')


def preflight(request, *, transport=None, remote=True):
    required = {'repository', 'source_commit', 'run_id', 'attempt', 'tag', 'profile',
                'recipes', 'gui_group', 'graphics_archive_url', 'execute', 'jobs'}
    if (not isinstance(request, dict) or not required <= set(request) or
            set(request) - required - {'core_provider', 'package_release', 'previous_packages'}):
        raise ValueError('complete Latest request required')
    core_provider = request.get('core_provider', 'rust')
    if core_provider not in ('rust', 'cpp'):
        raise ValueError('Latest core provider must be rust or cpp')
    delivery.location(request['repository']); ci.exact_commit(request['source_commit'])
    if (not re.fullmatch(r'[1-9][0-9]*', str(request['run_id'])) or
            type(request['attempt']) is not int or request['attempt'] < 1 or
            type(request['execute']) is not bool or request['jobs'] not in ('auto', '2', '4', '8')):
        raise ValueError('invalid run, attempt, execution or concurrency selection')
    tag = request['tag'] or f'release-{request["run_id"]}-attempt-{request["attempt"]}'
    delivery.valid_name(tag)
    if 'previous_packages' in request and 'package_release' not in request:
        raise ValueError('previous package selectors require a package revision')
    if 'package_release' in request:
        if (not isinstance(request['package_release'], str) or
                not re.fullmatch(r'[1-9][0-9]{0,5}', request['package_release']) or request['attempt'] >= 1000 or
                tag.lower() == 'latest'):
            raise ValueError('package revision must be 1 through 999999 and attempt below 1000')
        previous = request.get('previous_packages', {})
        if not isinstance(previous, dict) or set(previous) - {'linux-x86_64', 'linux-aarch64'}:
            raise ValueError('previous packages must be an exact Linux target map')
        if request['execute'] and set(previous) != {'linux-x86_64', 'linux-aarch64'}:
            raise ValueError('both exact previous Linux package channels are required for native upgrade qualification')
        import distro_check
        for target, selected in previous.items():
            checked = distro_check.selection(json.dumps(selected))
            if checked['target'] != target or checked['tag'] == tag:
                raise ValueError('previous package selector differs from target or names the new candidate')
    if tag == 'base' or tag.startswith(('ci-', 'screenshots-', 'experiment')):
        raise ValueError('ordinary release needs a distinct application tag')
    matrix = ci.release_matrix(request['recipes'], request['profile'], core_provider=core_provider)
    rust_recipes = ({row['target']: row['rust_recipe'] for row in matrix['include']}
                    if core_provider == 'rust' else {})
    if request['profile'] == 'all-gui':
        if not delivery.SHA.fullmatch(request['gui_group']):
            raise ValueError('all-GUI release requires an exact retained GUI input identity')
        ci.module('windows_graphics')._https(request['graphics_archive_url'])
    elif request['gui_group'] or request['graphics_archive_url']:
        raise ValueError('core release must omit GUI-only inputs')
    if remote:
        api = delivery.Remote(request['repository'], transport); api.visible()
        if api.find(tag, False) is not None or api.reference(tag, True) is not None:
            raise ValueError('release tag already exists; use a fresh identity or reconcile it')
        base = api.find('base'); assets = api.assets(base); reference = api.reference('base')
        if base['draft'] or not base['prerelease'] or base['name'] != 'base':
            raise ValueError('complete published dependency base required')
        expected = {name for recipe in request['recipes'].values() for name in delivery.store.names(recipe)}
        if not expected <= assets.keys():
            raise ValueError('exact base recipe missing; run explicit SDK maintenance first')
        rust_expected = {name for recipe in rust_recipes.values() for name in ci.rust_base_names(recipe)}
        if not rust_expected <= assets.keys():
            raise ValueError('exact complete Rust base recipe missing; run explicit Rust SDK maintenance first')
        api.unchanged('base', base, assets, reference)
    return dict(request, core_provider=core_provider, rust_recipes=rust_recipes, tag=tag, matrix=matrix,
                intent='publish and certify ordinary candidate before Latest' if request['execute'] else
                       'prepare only; no public candidate, certification or Latest change')


def require_stages(results, request):
    """Skipped/cancelled mandatory jobs cannot turn the orchestration green."""
    if not isinstance(results, dict) or set(results) != set(STAGES):
        raise ValueError('complete workflow result inventory required')
    required = STAGES if request['execute'] else STAGES[:3]
    if any(results[name].get('result') != 'success' for name in required):
        raise ValueError('mandatory release stage failed, was cancelled or did not execute')
    if not request['execute'] and any(results[name].get('result') != 'skipped' for name in STAGES[3:]):
        raise ValueError('plan-only workflow unexpectedly entered publication-dependent stages')
    app = results['application'].get('outputs', {})
    if (app.get('source_commit') != request['source_commit'] or app.get('tag') != request['tag'] or
            not delivery.SHA.fullmatch(app.get('inventory_sha256', '')) or
            not delivery.SHA.fullmatch(app.get('delivery_sha256', '')) or
            app.get('published') != ('true' if request['execute'] else 'false')):
        raise ValueError('application outputs do not identify the exact prepared delivery')
    if request['execute']:
        cert = results['certification'].get('outputs', {})
        if (cert.get('inventory_sha256') != app['inventory_sha256'] or
                not delivery.SHA.fullmatch(cert.get('certificate_sha256', '')) or
                cert.get('certification_run') != str(request['run_id']) or
                cert.get('certification_attempt') != str(request['attempt']) or
                cert.get('eligible_for_promotion') != 'true' or cert.get('attached') != 'true' or
                results['promotion'].get('outputs', {}).get('promoted') != 'true'):
            raise ValueError('exact ordinary certificate attachment and promotion are required')
    return app


def verify_latest(request, results, *, transport=None):
    app = require_stages(results, request)
    if not request['execute']:
        return {'schema_version': 1, 'status': 'prepared', 'published': False,
                'qualified': False, 'source_commit': request['source_commit'], 'tag': request['tag'],
                'inventory_sha256': app['inventory_sha256']}
    cert = results['certification']['outputs']
    api = delivery.Remote(request['repository'], transport); api.visible()
    with tempfile.TemporaryDirectory(prefix='latest-review-') as temporary:
        output = Path(temporary) / 'fetched'
        identity = ci.fetch_candidate(request['repository'], request['tag'], app['inventory_sha256'],
                                      output, transport=transport, metadata_only=True)
        if (identity['source_commit'] != request['source_commit'] or
                identity['packager_commit'] != request['source_commit'] or identity['experiment'] is not False or
                delivery.sha(delivery.archive.encoded(identity)) != app['delivery_sha256']):
            raise ValueError('published source, packager or delivery differs from this workflow')
        info, assets = delivery.verified_remote(api, identity, output / 'candidate', prerelease=False, readback=False, metadata_only=True)
        if 'package_release' in request and delivery.release.verify_metadata(output / 'candidate').get('packages') is None:
            raise ValueError('Latest candidate omits its required package repositories')
        checked = delivery.verify_certificate(api, assets, identity, output / 'candidate',
            ROOT / 'docs/release-policy.json', request['profile'], cert['certification_run'],
            int(cert['certification_attempt']), cert['certificate_sha256'], metadata_only=True)
        latest = api.transport.json(api.base + '/releases/latest')
        delivery.Remote.info(latest, request['tag'])
        if latest['id'] != info['id'] or latest['draft'] or latest['prerelease']:
            raise ValueError('Latest does not identify this exact ordinary certified release')
        api.unchanged(request['tag'], info, assets, identity['tag_commit'])
        if api.transport.json(api.base + '/releases/latest') != latest:
            raise ValueError('Latest changed during final verification')
    return {'schema_version': 1, 'status': 'passed', 'published': True, 'qualified': True,
            'source_commit': request['source_commit'], 'tag': request['tag'], 'release_id': info['id'],
            'inventory_sha256': app['inventory_sha256'], 'delivery_sha256': app['delivery_sha256'],
            'certificate': checked, 'assets': assets}


def environment_request():
    return {'repository': os.environ['GITHUB_REPOSITORY'], 'source_commit': os.environ['GITHUB_SHA'],
            'run_id': os.environ['GITHUB_RUN_ID'], 'attempt': int(os.environ['GITHUB_RUN_ATTEMPT']),
            'tag': os.environ.get('TAG', ''), 'profile': os.environ['PROFILE'],
            'core_provider': os.environ.get('CORE_PROVIDER', 'rust'),
            'recipes': delivery.parse(os.environ['RECIPES']), 'gui_group': os.environ.get('GUI_GROUP', ''),
            'graphics_archive_url': os.environ.get('GRAPHICS_ARCHIVE_URL', ''),
            **({'package_release': os.environ.get('PACKAGE_RELEASE', ''),
                'previous_packages': delivery.parse(os.environ.get('PREVIOUS_PACKAGES', '{}'))}
               if 'PACKAGE_RELEASE' in os.environ or 'PREVIOUS_PACKAGES' in os.environ else {}),
            'execute': {'true': True, 'false': False}[os.environ['EXECUTE']], 'jobs': os.environ['JOBS']}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation', choices=('preflight', 'verify'))
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args(argv)
    request = environment_request()
    head = subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=ROOT, check=True,
                          capture_output=True, text=True).stdout.strip()
    if head != request['source_commit']:
        raise ValueError('checked-out source does not match workflow commit')
    if args.operation == 'preflight':
        result = preflight(request)
        if os.environ.get('GITHUB_OUTPUT'):
            with open(os.environ['GITHUB_OUTPUT'], 'a', encoding='utf-8') as out:
                out.write('tag=' + result['tag'] + '\n')
    else:
        request['tag'] = request['tag'] or f'release-{request["run_id"]}-attempt-{request["attempt"]}'
        result = verify_latest(request, delivery.parse(os.environ['STAGE_RESULTS']))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    delivery.coverage.write_new(args.output, result)
    # Operator-retained input URLs can have transient query values; never echo
    # the complete request or environment into ordinary Actions logs.
    print(json.dumps({key: result[key] for key in ('status', 'intent', 'tag', 'source_commit',
                                                  'inventory_sha256', 'published', 'qualified') if key in result}, sort_keys=True))


if __name__ == '__main__':
    try:
        main()
    except (KeyError, OSError, ValueError, subprocess.SubprocessError) as error:
        raise SystemExit('Latest verification: ' + str(error))
