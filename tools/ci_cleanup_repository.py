#!/usr/bin/env python3
"""Manually purge this repository's Actions artifacts after checking idle runs.

The idle observations are not a lock against newly starting workflows.
Only IDs in the complete frozen artifact inventory are deleted; later uploads,
workflow runs and release assets are untouched.
"""
import argparse
import json
import os
from pathlib import Path
import time

import ci_cleanup as cleanup
import github_release as delivery

ACTIVE_STATUSES = ('requested', 'pending', 'waiting', 'queued', 'in_progress')
PAGE_SIZE = 100
MAX_ARTIFACTS = 10000
MAX_SECONDS = 25 * 60


def require_idle(transport, context):
    """Two rows suffice: the current run is the only permitted active result."""
    for status in ACTIVE_STATUSES:
        endpoint = f"repos/{context['repository']}/actions/runs?status={status}&per_page=2"
        value = transport.json(endpoint)
        if (not isinstance(value, dict) or type(value.get('total_count')) is not int or
                value['total_count'] < 0 or not isinstance(value.get('workflow_runs'), list) or
                len(value['workflow_runs']) != min(2, value['total_count'])):
            raise cleanup.CleanupError('active workflow inventory is incomplete or invalid')
        ids = set()
        for row in value['workflow_runs']:
            if (not isinstance(row, dict) or not delivery.positive(row.get('id')) or
                    row['id'] in ids or row.get('status') != status):
                raise cleanup.CleanupError('active workflow inventory has invalid identities or status')
            ids.add(row['id'])
        if value['total_count'] > 1 or any(run != context['run_id'] for run in ids):
            raise cleanup.CleanupError('repository is not idle: another workflow is ' + status)


def artifact_inventory(transport, context):
    """Freeze every ID and listed byte size before deletion can shift any page."""
    selected, ids, expected_total = [], set(), None
    for page in range(1, MAX_ARTIFACTS // PAGE_SIZE + 1):
        endpoint = f"repos/{context['repository']}/actions/artifacts?per_page={PAGE_SIZE}&page={page}"
        value = transport.json(endpoint)
        if (not isinstance(value, dict) or type(value.get('total_count')) is not int or
                not 0 <= value['total_count'] <= MAX_ARTIFACTS or
                not isinstance(value.get('artifacts'), list) or
                expected_total not in (None, value['total_count'])):
            raise cleanup.CleanupError('artifact inventory is incomplete, changed or exceeds 10000 entries')
        expected_total = value['total_count']
        if len(value['artifacts']) != min(PAGE_SIZE, expected_total - len(selected)):
            raise cleanup.CleanupError('artifact page does not match the complete inventory')
        for row in value['artifacts']:
            if (not isinstance(row, dict) or not delivery.positive(row.get('id')) or
                    row['id'] > cleanup.MAX_ARTIFACT_ID or row['id'] in ids or
                    type(row.get('size_in_bytes')) is not int or row['size_in_bytes'] < 0):
                raise cleanup.CleanupError('artifact inventory has duplicate IDs or invalid byte sizes')
            ids.add(row['id'])
            selected.append((row['id'], row['size_in_bytes']))
        if len(selected) == expected_total:
            return tuple(selected)
    raise cleanup.CleanupError('artifact inventory exceeds supported pagination')


def purge(*, environment=None, transport=None, sleep=time.sleep, clock=time.monotonic, progress=None):
    environment = os.environ if environment is None else environment
    started = clock()
    result = dict(status='refused', repository=None, run_id=None, attempt=None,
                  inventory_complete=False, selected_count=0, selected_bytes=0,
                  deleted_count=0, deleted_bytes=0, unconfirmed_count=0,
                  unconfirmed_bytes=0, unconfirmed_artifact_id=None)
    try:
        context = cleanup.current_context(environment)
        result.update({key: context[key] for key in ('repository', 'run_id', 'attempt')})
        if environment.get('GITHUB_EVENT_NAME') != 'workflow_dispatch':
            raise cleanup.CleanupError('repository purge requires a manual workflow_dispatch run')
        if transport is None:
            transport = delivery.GitHub(context['repository'])
            transport.WRITE_HEADROOM = 0
            transport.REQUEST_DEADLINE = 30
            transport.COMMAND_TIMEOUT = 30
            transport.WAIT_BUDGET = 0
            transport.wait_remaining = 0.0
            transport.MAX_ATTEMPTS = 1
        selected = artifact_inventory(transport, context)
        result.update(inventory_complete=True, selected_count=len(selected),
                      selected_bytes=sum(size for _, size in selected))
        result.update(unconfirmed_count=result['selected_count'], unconfirmed_bytes=result['selected_bytes'])
        if progress is not None:
            progress(dict(event='inventory', selected_count=result['selected_count'], selected_bytes=result['selected_bytes']))
        if selected:
            require_idle(transport, context)
        for identity, size in selected:
            if clock() - started >= MAX_SECONDS:
                raise cleanup.CleanupError('25-minute cleanup budget reached; rerun manually for remaining artifacts')
            if result['deleted_count']:
                sleep(1.0)
            result.update(status='failed', unconfirmed_artifact_id=identity)
            # missing=False is deliberate: 404 must not be counted as a confirmed
            # DELETE204. Stop on all errors without probing or replaying mutations.
            transport.json(f"repos/{context['repository']}/actions/artifacts/{identity}", method='DELETE')
            result['deleted_count'] += 1
            result['deleted_bytes'] += size
            result['unconfirmed_count'] -= 1
            result['unconfirmed_bytes'] -= size
            result['unconfirmed_artifact_id'] = None
            if progress is not None and result['deleted_count'] % 100 == 0:
                progress(dict(event='progress', deleted_count=result['deleted_count'],
                              deleted_bytes=result['deleted_bytes'], unconfirmed_count=result['unconfirmed_count']))
        result['status'] = 'complete'
    except (ValueError, OSError) as error:
        result['error'] = str(error)
    return result


def summary_text(result):
    lines = ['### Manual Actions artifact cleanup', '', 'Status: ' + result['status'] + '.', '']
    if result['inventory_complete']:
        lines += [f"- Frozen inventory: {result['selected_count']} artifacts, {result['selected_bytes']} bytes.",
                  f"- Confirmed deleted: {result['deleted_count']} artifacts, {result['deleted_bytes']} bytes at listing.",
                  f"- Not confirmed deleted: {result['unconfirmed_count']} artifacts, {result['unconfirmed_bytes']} bytes at listing."]
    else:
        lines += ['No complete inventory was frozen; no deletion was attempted.']
    if result['unconfirmed_artifact_id'] is not None:
        lines += [f"- Stopped at artifact {result['unconfirmed_artifact_id']}; its deletion was not confirmed."]
    if 'error' in result:
        lines += ['', 'Error: ' + result['error'].replace('\r', ' ').replace('\n', ' ')]
    lines += ['', 'The idle checks are observations, not a lock. Uploads after the inventory snapshot are not selected.',
              'Workflow runs and release assets are preserved. Listed bytes are not a billing adjustment measurement.', '']
    return '\n'.join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args(argv)
    destination = os.environ.get('GITHUB_STEP_SUMMARY')
    if not destination:
        raise cleanup.CleanupError('GITHUB_STEP_SUMMARY is required before repository cleanup')
    # Open the summary before any deletion so an unavailable report path fails early.
    with Path(destination).open('a', encoding='utf-8') as stream:
        result = purge(progress=lambda value: print(json.dumps(value, sort_keys=True), flush=True))
        stream.write(summary_text(result))
    print(json.dumps(result, sort_keys=True))
    return 0 if result['status'] == 'complete' else 1


if __name__ == '__main__':
    delivery.enable_metrics()
    try:
        raise SystemExit(main())
    except (ValueError, OSError) as error:
        print(json.dumps(dict(status='refused', error=str(error)), sort_keys=True))
        raise SystemExit(1)
