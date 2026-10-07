#!/usr/bin/env python3
"""Prune the preceding successful full run of one explicitly marked workflow.

Runs, normal logs and published releases are preserved. An opt-in terminal step
is checked only after the entire producing run has completed successfully. The
first marked run establishes the baseline; unmarked historical runs are retained.
"""
import argparse
import json
import os
from pathlib import Path
import time

import ci_cleanup as cleanup
import ci_cleanup_drafts
import ci_cleanup_repository as repository_cleanup
import github_release as delivery

MARKER = 'Confirm complete workflow cleanup eligibility'
WORKFLOWS = {
    'candidate.yml': 'verdict',
    '_release-latest.yml': 'Verify all required results and the final remote Latest identity',
    'certify.yml': 'verdict',
    'sdk-application.yml': 'Verify complete candidate and publish directly after required regression',
}
PAGE_SIZE = 100
MAX_RUNS = 1000  # GitHub caps a filtered workflow-run search at 1000 results.
MAX_JOBS = 1000
MAX_CANDIDATES = 20
MAX_SECONDS = 9 * 60
MAX_EVENT_BYTES = 1024 * 1024


class BoundedTransport:
    """Apply the whole cleanup deadline before each read or exact mutation."""
    def __init__(self, transport, deadline, clock):
        self.transport, self.deadline, self.clock = transport, deadline, clock

    def check(self):
        if self.clock() >= self.deadline:
            raise cleanup.CleanupError('nine-minute cleanup budget reached; remaining evidence is preserved')

    def json(self, *args, **kwargs):
        self.check()
        return self.transport.json(*args, **kwargs)

    def pages(self, *args, **kwargs):
        self.check()
        # GitHub.pages is one gh invocation, already bounded to thirty seconds.
        return self.transport.pages(*args, **kwargs)


def inventory(transport, endpoint, field, maximum):
    """Freeze a complete bounded listing before any mutation can shift its pages."""
    rows, ids, expected = [], set(), None
    for page in range(1, (maximum + PAGE_SIZE - 1) // PAGE_SIZE + 1):
        separator = '' if endpoint.endswith('?') else '&'
        value = transport.json(endpoint + separator + f'per_page={PAGE_SIZE}&page={page}')
        if (not isinstance(value, dict) or type(value.get('total_count')) is not int or
                not 0 <= value['total_count'] <= maximum or
                expected not in (None, value['total_count']) or not isinstance(value.get(field), list)):
            raise cleanup.CleanupError(field + ' inventory is incomplete, changed or exceeds its finite limit')
        expected = value['total_count']
        if len(value[field]) != min(PAGE_SIZE, expected - len(rows)):
            raise cleanup.CleanupError(field + ' page does not match the complete inventory')
        for row in value[field]:
            if (not isinstance(row, dict) or not delivery.positive(row.get('id')) or
                    row['id'] > cleanup.MAX_ARTIFACT_ID or row['id'] in ids):
                raise cleanup.CleanupError(field + ' inventory contains invalid or duplicate identities')
            ids.add(row['id'])
            rows.append(row)
        if len(rows) == expected:
            return tuple(rows)
    raise cleanup.CleanupError(field + ' inventory exceeds supported pagination')


def run_context(value, context, *, workflow_id=None):
    """Bind an Actions run to the exact native repository and source workflow."""
    if not isinstance(value, dict):
        raise cleanup.CleanupError('completed workflow run identity is invalid')
    path = value.get('path')
    workflow = path[len('.github/workflows/'):] if isinstance(path, str) and path.startswith('.github/workflows/') else None
    if (workflow not in WORKFLOWS or not delivery.positive(value.get('id')) or
            not delivery.positive(value.get('workflow_id')) or
            workflow_id not in (None, value['workflow_id']) or
            not delivery.positive(value.get('run_attempt')) or not delivery.positive(value.get('run_number')) or
            not isinstance(value.get('head_sha'), str) or not delivery.OID.fullmatch(value['head_sha']) or
            value.get('event') != 'workflow_dispatch' or value.get('status') != 'completed' or
            value.get('conclusion') != 'success'):
        raise cleanup.CleanupError('run must be an exact completed successful allowlisted workflow')
    for field in ('repository', 'head_repository'):
        repository = value.get(field)
        if (not isinstance(repository, dict) or repository.get('id') != context['repository_id'] or
                repository.get('full_name') != context['repository']):
            raise cleanup.CleanupError('workflow producer must belong to the exact native repository')
    return dict(repository=context['repository'], repository_id=context['repository_id'],
                run_id=value['id'], attempt=value['run_attempt'], source_commit=value['head_sha'],
                workflow=workflow, workflow_id=value['workflow_id'], run_number=value['run_number'])


def read_run(transport, context, run_id, workflow_id=None):
    return run_context(transport.json(f"repos/{context['repository']}/actions/runs/{run_id}"),
                       context, workflow_id=workflow_id)


def full_run(transport, context):
    # An attempt may reuse earlier successful jobs. Until there is an independent
    # complete-attempt receipt, every rerun fails closed, including a partial one.
    if context['attempt'] != 1:
        return False
    endpoint = f"repos/{context['repository']}/actions/runs/{context['run_id']}/attempts/{context['attempt']}/jobs?"
    jobs = inventory(transport, endpoint, 'jobs', MAX_JOBS)
    selected = []
    for job in jobs:
        if (job.get('run_id') != context['run_id'] or job.get('head_sha') != context['source_commit'] or
                job.get('status') != 'completed' or job.get('conclusion') not in ('success', 'skipped')):
            raise cleanup.CleanupError('completed attempt jobs have inconsistent source, status or outcome')
        if job.get('name') == WORKFLOWS[context['workflow']]:
            selected.append(job)
    if len(selected) != 1 or selected[0]['conclusion'] != 'success':
        return False
    steps = selected[0].get('steps')
    if not isinstance(steps, list) or len(steps) > 200 or any(not isinstance(step, dict) for step in steps):
        raise cleanup.CleanupError('terminal full-run steps are incomplete or invalid')
    markers = [step for step in steps if step.get('name') == MARKER]
    return (len(markers) == 1 and markers[0].get('status') == 'completed' and
            markers[0].get('conclusion') == 'success')


def predecessor(transport, current):
    endpoint = f"repos/{current['repository']}/actions/workflows/{current['workflow_id']}/runs?status=success"
    rows = inventory(transport, endpoint, 'workflow_runs', MAX_RUNS)
    candidates, numbers = [], set()
    for row in rows:
        value = run_context(row, current, workflow_id=current['workflow_id'])
        if value['workflow'] != current['workflow'] or value['run_number'] in numbers:
            raise cleanup.CleanupError('workflow history has inconsistent paths or duplicate run numbers')
        if value['run_id'] == current['run_id'] and value != current:
            raise cleanup.CleanupError('current run changed in the workflow history snapshot')
        numbers.add(value['run_number'])
        if value['run_id'] != current['run_id'] and value['run_number'] < current['run_number']:
            candidates.append(value)
    candidates.sort(key=lambda value: value['run_number'], reverse=True)
    for index, value in enumerate(candidates):
        if index >= MAX_CANDIDATES:
            raise cleanup.CleanupError('full predecessor search exceeded 20 candidates; no deletion attempted')
        if full_run(transport, value):
            return value
    return None


def artifacts(transport, previous):
    endpoint = f"repos/{previous['repository']}/actions/runs/{previous['run_id']}/artifacts?"
    rows = inventory(transport, endpoint, 'artifacts', cleanup.MAX_DELETE)
    selected = []
    for row in rows:
        producer = row.get('workflow_run')
        if (not isinstance(producer, dict) or producer.get('id') != previous['run_id'] or
                producer.get('repository_id') != previous['repository_id'] or
                producer.get('head_repository_id') != previous['repository_id'] or
                producer.get('head_sha') != previous['source_commit'] or
                type(row.get('size_in_bytes')) is not int or row['size_in_bytes'] < 0):
            raise cleanup.CleanupError('artifact inventory does not belong to the exact predecessor')
        selected.append((row['id'], row['size_in_bytes']))
    return tuple(selected)


def prune(*, environment=None, event=None, transport=None, sleep=time.sleep,
          clock=time.monotonic, draft_cleanup=None):
    environment = os.environ if environment is None else environment
    started = clock()
    result = dict(status='refused', current_run_id=None, previous_run_id=None,
                  selected_count=0, selected_bytes=0, deleted_count=0, deleted_bytes=0,
                  unconfirmed_artifact_id=None)
    try:
        context = cleanup.current_context(environment)
        if (environment.get('GITHUB_EVENT_NAME') != 'workflow_run' or
                not environment['GITHUB_WORKFLOW_REF'].startswith(
                    context['repository'] + '/.github/workflows/cleanup-previous-run.yml@')):
            raise cleanup.CleanupError('previous-run cleanup requires its native workflow_run context')
        if not isinstance(event, dict) or event.get('action') != 'completed':
            raise cleanup.CleanupError('a completed workflow_run event is required')
        current = run_context(event.get('workflow_run'), context)
        if current['run_id'] == context['run_id']:
            raise cleanup.CleanupError('cleanup cannot target its own executing run')
        result['current_run_id'] = current['run_id']
        if transport is None:
            transport = delivery.GitHub(context['repository'])
            transport.WRITE_HEADROOM = 0
            transport.REQUEST_DEADLINE = 30
            transport.COMMAND_TIMEOUT = 30
            transport.WAIT_BUDGET = 0
            transport.wait_remaining = 0.0
            transport.MAX_ATTEMPTS = 1
        transport = BoundedTransport(transport, started + MAX_SECONDS, clock)
        if read_run(transport, context, current['run_id']) != current:
            raise cleanup.CleanupError('completed trigger run changed before cleanup')
        if not full_run(transport, current):
            result.update(status='skipped', reason='full completion marker absent, preserved or rerun attempt')
            return result
        previous = predecessor(transport, current)
        selected = ()
        if previous is not None:
            result['previous_run_id'] = previous['run_id']
            selected = artifacts(transport, previous)
        result.update(selected_count=len(selected), selected_bytes=sum(size for _, size in selected))
        repository_cleanup.require_idle(transport, context)
        for value in (current, previous):
            if value is not None and read_run(transport, context, value['run_id']) != value:
                raise cleanup.CleanupError('selected successful run changed before deletion')
        for identity, size in selected:
            transport.check()
            if result['deleted_count']:
                sleep(1.0)
            result.update(status='failed', unconfirmed_artifact_id=identity)
            transport.json(f"repos/{context['repository']}/actions/artifacts/{identity}", method='DELETE')
            result['deleted_count'] += 1
            result['deleted_bytes'] += size
            result['unconfirmed_artifact_id'] = None
        if draft_cleanup is not None:
            transport.check()
            for value in (current, previous):
                if value is not None and read_run(transport, context, value['run_id']) != value:
                    raise cleanup.CleanupError('selected successful run changed before draft deletion')
            result['status'] = 'failed'
            result['drafts'] = draft_cleanup(current, previous, transport=transport,
                                             cleanup_run_id=context['run_id'], sleep=sleep, clock=clock)
        result['status'] = 'complete'
    except (ValueError, OSError) as error:
        result['error'] = str(error)
    return result


def summary_text(result):
    lines = ['### Previous full workflow cleanup', '', 'Status: ' + result['status'] + '.', '',
             f"- Completed source run: {result['current_run_id']}.",
             f"- Selected preceding full run: {result['previous_run_id']}.",
             f"- Frozen artifacts: {result['selected_count']}, {result['selected_bytes']} bytes.",
             f"- Confirmed deleted: {result['deleted_count']}, {result['deleted_bytes']} bytes."]
    for field in ('reason', 'error'):
        if field in result:
            lines += ['', field.capitalize() + ': ' + result[field].replace('\r', ' ').replace('\n', ' ')]
    if result['unconfirmed_artifact_id'] is not None:
        lines += [f"Deletion of artifact {result['unconfirmed_artifact_id']} was not confirmed."]
    if 'drafts' in result:
        lines += ['', 'Transient draft cleanup: `' + json.dumps(result['drafts'], sort_keys=True) + '`.']
    lines += ['', 'Runs, normal workflow logs and published releases are preserved.', '']
    return '\n'.join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args(argv)
    event_path = os.environ.get('GITHUB_EVENT_PATH')
    summary_path = os.environ.get('GITHUB_STEP_SUMMARY')
    if not event_path or not summary_path:
        raise cleanup.CleanupError('native event path and step summary are required')
    with Path(event_path).open('rb') as stream:
        raw = stream.read(MAX_EVENT_BYTES + 1)
    if len(raw) > MAX_EVENT_BYTES:
        raise cleanup.CleanupError('workflow_run event exceeds one MiB')
    event = delivery.parse(raw.decode('utf-8'))
    # The summary must be writable before any remote deletion starts.
    with Path(summary_path).open('a', encoding='utf-8') as stream:
        result = prune(event=event, draft_cleanup=ci_cleanup_drafts.cleanup_drafts)
        stream.write(summary_text(result))
    print(json.dumps(result, sort_keys=True))
    return 0 if result['status'] in ('complete', 'skipped') else 1


if __name__ == '__main__':
    delivery.enable_metrics()
    try:
        raise SystemExit(main())
    except (ValueError, OSError) as error:
        print(json.dumps(dict(status='refused', error=str(error)), sort_keys=True))
        raise SystemExit(1)
