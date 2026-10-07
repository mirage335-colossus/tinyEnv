#!/usr/bin/env python3
"""Expire completed auxiliary transport drafts, preserving unpublished inputs.

Daily or explicitly dispatched default-branch cleanup may invoke this policy.
Application/full-run artifact pruning and retained SDKs keep their existing policy.
"""
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import time

import ci_cleanup as cleanup
import ci_cleanup_drafts as drafts
import ci_cleanup_previous as previous
import ci_cleanup_repository as repository_cleanup
import github_release as delivery

MIN_AGE = 24 * 60 * 60
MAX_STORES = drafts.MAX_STORES
TAG = re.compile(r'ci-([1-9][0-9]{0,19})-attempt-([1-9][0-9]{0,19})')
PUBLISHED = frozenset(('screenshots.yml', 'gui-inputs.yml', 'distribution.yml'))
TERMINAL = frozenset(('success', 'failure', 'cancelled', 'timed_out', 'skipped',
                      'neutral', 'action_required', 'stale'))


def timestamp(value):
    if not isinstance(value, str) or not re.fullmatch(r'\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ', value):
        raise cleanup.CleanupError('exact UTC update time required for draft expiry')
    return datetime.strptime(value, '%Y-%m-%dT%H:%M:%SZ').replace(tzinfo=timezone.utc).timestamp()


def eligible(transport, native, selected, cutoff):
    """Bind the exact old attempt; a later successful rerun grants no authority."""
    endpoint = (f"repos/{native['repository']}/actions/runs/{selected['run_id']}"
                f"/attempts/{selected['attempt']}")
    run = transport.json(endpoint)
    if (not isinstance(run, dict) or run.get('id') != selected['run_id'] or
            run.get('run_attempt') != selected['attempt'] or
            run.get('head_sha') != selected['source_commit'] or
            run.get('path') != '.github/workflows/' + selected['workflow'] or
            run.get('event') != 'workflow_dispatch'):
        raise cleanup.CleanupError('auxiliary draft run identity differs from its exact attempt')
    for field in ('repository', 'head_repository'):
        value = run.get(field)
        if (not isinstance(value, dict) or value.get('id') != native['repository_id'] or
                value.get('full_name') != native['repository']):
            raise cleanup.CleanupError('auxiliary producer must belong to the exact native repository')
    if (run.get('status') != 'completed' or run.get('conclusion') not in TERMINAL or
            timestamp(run.get('updated_at')) > cutoff):
        return False
    jobs = previous.inventory(transport, endpoint + '/jobs?', 'jobs', previous.MAX_JOBS)
    for job in jobs:
        if (job.get('run_id') != selected['run_id'] or
                job.get('head_sha') != selected['source_commit'] or
                job.get('status') != 'completed' or job.get('conclusion') not in TERMINAL):
            raise cleanup.CleanupError('auxiliary attempt jobs have inconsistent source or terminal status')
    if selected['workflow'] in PUBLISHED:
        publishers = [job for job in jobs if job.get('name') == 'publish']
        return len(publishers) == 1 and publishers[0]['conclusion'] == 'success'
    return bool(jobs)


def sweep(*, environment=None, transport=None, sleep=time.sleep, clock=time.monotonic, now=None):
    environment = os.environ if environment is None else environment
    result = dict(status='refused', selected_drafts=0, deleted_drafts=0, deleted_tags=0,
                  preserved_drafts=0)
    try:
        native = cleanup.current_context(environment)
        event = environment.get('GITHUB_EVENT_NAME')
        immediate = environment.get('CLEANUP_EXPIRE_NOW', 'false')
        if (event not in ('schedule', 'workflow_dispatch') or
                not environment['GITHUB_WORKFLOW_REF'].startswith(
                    native['repository'] + '/.github/workflows/cleanup-previous-run.yml@')):
            raise cleanup.CleanupError('draft expiry requires its native scheduled or manual cleanup context')
        if immediate not in ('false', 'true') or (immediate == 'true' and event != 'workflow_dispatch'):
            raise cleanup.CleanupError('immediate expiry requires an explicit manual cleanup request')
        if transport is None:
            transport = delivery.GitHub(native['repository'])
            transport.WRITE_HEADROOM = transport.WAIT_BUDGET = transport.wait_remaining = 0
            transport.REQUEST_DEADLINE = transport.COMMAND_TIMEOUT = 30
            transport.MAX_ATTEMPTS = 1
        transport = previous.BoundedTransport(transport, clock() + previous.MAX_SECONDS, clock)
        cutoff = (time.time() if now is None else now) - (0 if immediate == 'true' else MIN_AGE)
        remote = delivery.Remote(native['repository'], transport)
        selected, identities, seen = [], {}, set()
        for row in transport.pages(remote.base + '/releases?per_page=100'):
            if (not isinstance(row, dict) or not delivery.positive(row.get('id')) or
                    row['id'] in seen or not isinstance(row.get('tag_name'), str)):
                raise cleanup.CleanupError('draft expiry release inventory is incomplete or ambiguous')
            seen.add(row['id'])
            if (not TAG.fullmatch(row['tag_name']) or row.get('draft') is not True or
                    row.get('prerelease') is not True):
                continue
            if not isinstance(row.get('body'), str):
                continue
            try:
                body = delivery.parse(row['body'])
            except ValueError:
                continue  # Unknown storage is retained, never guessed from its tag.
            if (not isinstance(body, dict) or not isinstance(body.get('workflow'), str) or
                    body['workflow'] not in drafts.AUXILIARY_NAMES):
                continue
            context, repository_id = drafts._context(body, auxiliary=True)
            if (context['repository'] != native['repository'] or repository_id != native['repository_id'] or
                    context['run_id'] == native['run_id'] or drafts.bundles._tag(context) != row['tag_name']):
                raise cleanup.CleanupError('draft expiry provenance differs from its native repository or tag')
            if row['tag_name'] in identities:
                raise cleanup.CleanupError('duplicate auxiliary draft tags require inspection')
            identities[row['tag_name']] = row['id']
            if timestamp(row.get('updated_at')) <= cutoff and eligible(transport, native, context, cutoff):
                info = drafts.bundles._store(remote, context, repository_id, release_id=row['id'])
                if not drafts._temporary_assets(remote.assets(info), context['attempt'], context['workflow']):
                    result['preserved_drafts'] += 1
                    continue  # Retained stores must not consume the daily deletion budget.
                selected.append(dict(context, repository_id=repository_id))
        # The bounded batch is deterministic; later daily sweeps handle a backlog.
        selected.sort(key=lambda value: (value['run_id'], value['attempt']))
        selected = selected[:MAX_STORES]
        result['selected_drafts'] = len(selected)
        if not selected:
            result.update(status='skipped', reason='no expired eligible auxiliary drafts')
            return result
        try:
            repository_cleanup.require_idle(transport, native)
        except cleanup.CleanupError as error:
            if not str(error).startswith('repository is not idle:'):
                raise
            result.update(status='skipped', reason=str(error))
            return result  # A later daily sweep retries after the consumers finish.

        def recheck(context):
            tag = drafts.bundles._tag(context)
            info = remote.by_id(identities[tag], tag)
            return (timestamp(info.get('updated_at')) <= cutoff and
                    eligible(transport, native, context, cutoff))

        result['status'] = 'failed'
        outcome = drafts.cleanup_drafts(selected[0], additional=selected[1:],
            transport=transport, cleanup_run_id=native['run_id'], auxiliary=True,
            before_delete=recheck, sleep=sleep, clock=clock)
        outcome['preserved_drafts'] += result['preserved_drafts']
        result.update(outcome)
        result['status'] = 'complete'
    except (ValueError, OSError) as error:
        result['error'] = str(error)
    return result


def main():
    destination = os.environ.get('GITHUB_STEP_SUMMARY')
    if not destination:
        raise cleanup.CleanupError('GITHUB_STEP_SUMMARY is required before draft expiry')
    with Path(destination).open('a', encoding='utf-8') as stream:
        result = sweep()
        stream.write('### Expired auxiliary draft cleanup\n\n```json\n' +
                     json.dumps(result, sort_keys=True, indent=2) + '\n```\n')
    print(json.dumps(result, sort_keys=True))
    return 0 if result['status'] in ('complete', 'skipped') else 1


if __name__ == '__main__':
    delivery.enable_metrics()
    try:
        raise SystemExit(main())
    except (ValueError, OSError) as error:
        print(json.dumps(dict(status='refused', error=str(error)), sort_keys=True))
        raise SystemExit(1)
