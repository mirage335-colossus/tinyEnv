#!/usr/bin/env python3
"""Delete explicit upload IDs supplied by their final workflow consumers.

The caller must obtain IDs from this workflow's trusted upload outputs and own
its final-consumer barrier and preservation option. No inventory is discovered.
One-day artifact expiry remains the fallback if cleanup cannot finish.
"""
import argparse
import json
import os
import re
import time

import github_release as delivery

IDS_ENV = 'FOUNDATION_CI_CLEANUP_ARTIFACT_IDS'
MAX_INPUT_BYTES = 32 * 1024
MAX_ARTIFACT_ID = 10 ** 20 - 1
MAX_DELETE = 512


class CleanupError(ValueError):
    pass


def current_context(environment=None):
    environment = os.environ if environment is None else environment
    if (environment.get('GITHUB_ACTIONS') != 'true' or
            environment.get('GITHUB_SERVER_URL') != 'https://github.com'):
        raise CleanupError('cleanup requires a native GitHub.com Actions context')
    repository = delivery.location(environment.get('GITHUB_REPOSITORY', ''))
    reference = environment.get('GITHUB_WORKFLOW_REF', '')
    prefix = repository + '/.github/workflows/'
    if (not reference.startswith(prefix) or
            not re.fullmatch(r'[A-Za-z0-9_-]+\.ya?ml@[^\r\n]+', reference[len(prefix):])):
        raise CleanupError('cleanup workflow must belong to the current repository')
    values = {}
    for field, variable in (('run_id', 'GITHUB_RUN_ID'), ('attempt', 'GITHUB_RUN_ATTEMPT'),
                            ('repository_id', 'GITHUB_REPOSITORY_ID')):
        value = environment.get(variable, '')
        if not isinstance(value, str) or not re.fullmatch(r'[1-9][0-9]{0,19}', value):
            raise CleanupError('cleanup requires a positive exact ' + field)
        values[field] = int(value)
    commit = environment.get('GITHUB_SHA', '')
    if not isinstance(commit, str) or not delivery.OID.fullmatch(commit):
        raise CleanupError('cleanup requires the exact current source commit')
    return dict(repository=repository, source_commit=commit, **values)


def selected_artifacts(raw):
    """Validate every explicit ID before returning a deduplicated immutable set."""
    if not isinstance(raw, str) or not raw.strip() or len(raw.encode('utf-8')) > MAX_INPUT_BYTES:
        raise CleanupError('cleanup requires a bounded explicit artifact-ids JSON array')
    try:
        values = delivery.parse(raw)
    except (ValueError, RecursionError):
        raise CleanupError('artifact-ids must be a complete JSON array') from None
    if not isinstance(values, list) or len(values) > MAX_DELETE:
        raise CleanupError('artifact-ids must be an array within the cleanup budget')
    selected, seen = [], set()
    for value in values:
        if isinstance(value, str) and re.fullmatch(r'[1-9][0-9]{0,19}', value):
            value = int(value)
        if type(value) is not int or not 0 < value <= MAX_ARTIFACT_ID:
            raise CleanupError('every artifact ID must be a canonical positive integer')
        if value not in seen:
            seen.add(value)
            selected.append(value)
    return tuple(selected)


def cleanup(*, environment=None, transport=None, sleep=time.sleep):
    environment = os.environ if environment is None else environment
    context = current_context(environment)
    selected = selected_artifacts(environment.get(IDS_ENV))
    if not selected:
        return dict(run_id=context['run_id'], attempt=context['attempt'], selected=0, deleted=0)
    if transport is None:
        transport = delivery.GitHub(context['repository'])
        # Cleanup is optional: never wait for quota or retry a partial mutation.
        transport.WRITE_HEADROOM = 0
        transport.REQUEST_DEADLINE = 30
        transport.COMMAND_TIMEOUT = 30
        transport.WAIT_BUDGET = 0
        transport.wait_remaining = 0.0
        transport.MAX_ATTEMPTS = 1
    deleted = 0
    for artifact_id in selected:
        if deleted:
            sleep(1.0)
        try:
            transport.json(f"repos/{context['repository']}/actions/artifacts/{artifact_id}", method='DELETE')
        except (ValueError, OSError) as error:
            raise CleanupError(f'cleanup stopped after {deleted} of {len(selected)} confirmed deletions; '
                               'remaining artifacts retain their expiry: ' + str(error)) from error
        deleted += 1
    return dict(run_id=context['run_id'], attempt=context['attempt'], selected=len(selected), deleted=deleted)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args(argv)
    print(json.dumps(cleanup(), sort_keys=True))


if __name__ == '__main__':
    delivery.enable_metrics()
    try:
        main()
    except (ValueError, OSError) as error:
        raise SystemExit('ci-cleanup: ' + str(error))
