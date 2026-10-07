#!/usr/bin/env python3
"""Checked, explicit transition from a closed JSON board to the record protocol.

Every participant must be stopped and closed before this exclusive administrative
operation. It never migrates live claims, guesses stopped writers, steals a mutex,
or overwrites an existing destination. An interrupted transition requires review.
"""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys
import uuid

sys.dont_write_bytecode = True


def load(name):
    spec = importlib.util.spec_from_file_location(name, Path(__file__).with_name(name + '.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


COMPAT = load('agent_board')
SESSION = load('agent_session')
PUBLISH = SESSION.BOARD
CHECK = SESSION.CHECK


class MigrationError(ValueError):
    def __init__(self, message, uncertain=False):
        super().__init__(message)
        self.uncertain = uncertain


def compact(value):
    return json.dumps(value, ensure_ascii=True, separators=(',', ':'))


def convert_record(record, state, snapshot):
    """Preserve exact source facts separately and expose complete release provenance."""
    session = record['id']
    related = [r for r in state['releases'] if session in (r['from'], r['to'])]
    scopes = {tuple(sorted(scope.items())) for release in related for scope in release['scopes']}
    handoff = '- Scope inventory: complete\n'
    handoff += '\n'.join('- Scope: ' + dict(scope)['kind'] + ': ' + dict(scope)['value']
                         for scope in sorted(scopes)) if scopes else '- Scope: none'
    handoff += '\n- Exact source snapshot: ' + str(snapshot)
    handoff += '\n- Retained disposition: ' + compact(record['disposition'])
    handoff += ''.join('\n- Retained release: ' + compact(release) for release in related)
    identity = {
        'Tool / host / local chat reference': 'converted JSON record / ' + compact(record['host']) + ' / ' + session,
        'Parent / read-only helpers': 'unavailable in source record',
        'Task and approach': compact({'task': record['task'], 'approach': record['approach']}),
        'Checkout / coordination root (absolute physical paths)': record['checkout'] + ' / ' + str(snapshot.parents[2]),
        'Branch / starting HEAD / current HEAD': 'unavailable; preserve the original baseline below',
        'Starting worktree and index changes (including work owned by others)': compact(record['baseline']),
    }
    checkpoint = {
        'State': record['state'], 'Updated (UTC)': record['updated'],
        'Last meaningful progress (UTC)': record['progress_at'] or 'unavailable',
        'Last inbox check (UTC)': record['inbox_at'] or 'unavailable',
        'Next check (UTC) / action': 'none / review original retention eligibility',
        'Liveness mode / cadence': 'checkpoint / closed',
        'Last heartbeat (UTC), if supervised': 'none',
        'Run token / heartbeat file and writer, if used': 'none',
        'Owner process': 'unavailable in source record; exclusive migration requires stopped writers',
        'Running jobs': 'none', 'Closed (UTC), if terminal': record['closed'],
        'Delete after (UTC)': record['delete_after'], 'Retention exception': 'none',
        'Contact': 'messages/' + session + '/',
    }
    return SESSION.render_record(session=session, identity=identity, checkpoint=checkpoint, claims=[],
        baseline='- Retained baseline and dependencies: ' + compact({k: record[k] for k in ('baseline', 'dependencies')}),
        progress='- Retained progress and checks: ' + compact({k: record[k] for k in ('progress', 'checks', 'blockers')}),
        handoff=handoff)['candidate'].encode()


def migrate(root, board, revision, expected_sha256, operator, review,
            writers_stopped=False, exclusive_administration=False):
    PUBLISH.require_capabilities()
    PUBLISH.safe_id(operator)
    if writers_stopped is not True or exclusive_administration is not True or not isinstance(review, str) or not review.strip():
        raise MigrationError('positive stopped-writer evidence and exclusive administration are required')
    board = PUBLISH.absolute_path(board)
    compatibility = COMPAT.Board(root, board)
    changed = False
    try:
        with compatibility.mutex():
            state = compatibility.read()
            compatibility.revision(state, {'revision': revision})
            with PUBLISH.open_directory(board) as opened:
                before, before_version = PUBLISH.read_regular(opened, 'state.json')
                if hashlib.sha256(before).hexdigest() != expected_sha256:
                    raise MigrationError('source snapshot differs from reviewed bytes')
                for record in state['sessions'].values():
                    if record['state'] not in COMPAT.TERMINAL or record['claims'] or record['jobs']:
                        raise MigrationError('every source session must be terminal with no claims or jobs')
                if any(r['to'] is not None and r['accepted'] is None for r in state['releases']):
                    raise MigrationError('pending handoffs must be resolved before migration')
                # No implicit merge, overwrite or second registry is permitted.
                for name in ('sessions', 'messages', 'heartbeats', 'protocol.json'):
                    try:
                        os.stat(name, dir_fd=opened, follow_symlinks=False)
                    except FileNotFoundError:
                        pass
                    else:
                        raise MigrationError('destination already exists: ' + name)
                migration_id = 'migration-' + uuid.uuid4().hex
                snapshot = board / 'artifacts' / migration_id / 'source.json'
                candidates = {name: convert_record(record, state, snapshot)
                              for name, record in state['sessions'].items()}
                messages = []
                for message in state['messages']:
                    metadata = {k: v for k, v in message.items() if k != 'body'}
                    body = ('Retained message metadata: ' + compact(metadata) + '\n\n' + message['body']).encode()
                    messages.append((message['to'], message['from'] + '-' + message['id'] + '.md', body))
                changed = True
                with PUBLISH.child_directory(opened, 'registry.lock') as lock:
                    with PUBLISH.child_directory(opened, 'artifacts', create=True) as artifacts:
                        os.mkdir(migration_id, mode=0o700, dir_fd=artifacts)
                        with PUBLISH.child_directory(artifacts, migration_id) as evidence:
                            with PUBLISH.staged_bytes(lock, before) as staged:
                                PUBLISH.exclusive_publish(lock, staged, evidence, 'source.json')
                            receipt = {'operator': operator, 'review': review, 'source_sha256': expected_sha256,
                                       'migrated_at': SESSION.utc_now(), 'source_closures': {
                                           name: {'closed': r['closed'], 'delete_after': r['delete_after']}
                                           for name, r in state['sessions'].items()},
                                       'retention': 'Source dates are preserved; review dependencies before removing this snapshot.'}
                            with PUBLISH.staged_bytes(lock, (compact(receipt) + '\n').encode()) as staged:
                                PUBLISH.exclusive_publish(lock, staged, evidence, 'receipt.json')
                    for name in ('sessions', 'messages', 'heartbeats'):
                        os.mkdir(name, mode=0o700, dir_fd=opened)
                    with PUBLISH.child_directory(opened, 'sessions') as sessions:
                        for name, candidate in candidates.items():
                            with PUBLISH.staged_bytes(lock, candidate) as staged:
                                PUBLISH.exclusive_publish(lock, staged, sessions, name + '.md')
                    with PUBLISH.child_directory(opened, 'messages') as inboxes:
                        for recipient, name, body in messages:
                            with PUBLISH.child_directory(inboxes, recipient, create=True) as inbox:
                                with PUBLISH.staged_bytes(lock, body) as staged:
                                    PUBLISH.exclusive_publish(lock, staged, inbox, name)
                    scanned = CHECK.scan_sessions(board / 'sessions')
                    if not scanned['complete'] or len(scanned['records']) != len(candidates):
                        raise MigrationError('converted record inventory did not validate')
                    for name, expected in candidates.items():
                        with PUBLISH.child_directory(opened, 'sessions') as sessions:
                            saved, _ = PUBLISH.read_regular(sessions, name + '.md')
                        if saved != expected:
                            raise MigrationError('saved converted record differs')
                    marker = {'protocol': 'records', 'version': 2, 'source_sha256': expected_sha256,
                              'evidence': str(snapshot.parent)}
                    with PUBLISH.staged_bytes(lock, (compact(marker) + '\n').encode()) as staged:
                        PUBLISH.exclusive_publish(lock, staged, opened, 'protocol.json')
                    current, current_version = PUBLISH.read_regular(opened, 'state.json')
                    if current != before or current_version != before_version:
                        raise MigrationError('source changed during migration')
                    compatibility.check_mutex()
                    PUBLISH.verify_board(board, opened)
                    # This is the authority switch: full-protocol writers refuse state.json.
                    os.unlink('state.json', dir_fd=opened)
                    os.fsync(opened)
            result = {'ok': True, 'protocol': 'records', 'board': str(board), 'sessions': len(candidates),
                      'messages': len(messages), 'source_snapshot': str(snapshot), 'source_sha256': expected_sha256}
        return result
    except BaseException as error:
        if isinstance(error, MigrationError) and not changed:
            raise
        raise MigrationError(str(error), uncertain=changed or getattr(error, 'uncertain', False)) from error


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', default='-', help='JSON request on stdin or a claimed regular file')
    args = parser.parse_args(argv)
    completed = False
    try:
        request = json.loads(PUBLISH.source_bytes(args.input))
        result = migrate(**request)
        completed = True
        print(json.dumps(result), flush=True)
        return 0
    except (OSError, ValueError, TypeError, KeyError) as error:
        uncertain = completed or getattr(error, 'uncertain', False)
        print(json.dumps({'ok': False, 'uncertain': uncertain,
                          'action': 'reconcile_saved_state' if uncertain else 'correct_preconditions',
                          'message': str(error)}), file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
