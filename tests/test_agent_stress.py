#!/usr/bin/env python3
"""Independent reservation/edit loops; no winner selection or turn scheduler.

The processes are deterministic fixture clients, not reasoning agents. Set
FOUNDATION_AGENT_STRESS_WORKERS=64 for the larger local qualification run.
"""
import ast
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import random
import re
import selectors
import subprocess
import sys
import tempfile
import time
import unittest

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
from test_agent_session import SESSION, record

SPEC = importlib.util.spec_from_file_location('agent_edit', ROOT / 'tools/agent_edit.py')
EDIT = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(EDIT)


def digest(data):
    return hashlib.sha256(data).hexdigest()


def backoff(attempt):
    # Keep the total deadline and avoid a short-delay tail under saturation.
    # This mirrors retry_delay's advice without retrying uncertain failures.
    window = min(4.0, .05 * 2 ** min(attempt - 1, 7))
    time.sleep(random.uniform(window / 2, window))


def mapping(data):
    tree = ast.parse(data)
    if (len(tree.body) != 1 or not isinstance(tree.body[0], ast.Assign)
            or len(tree.body[0].targets) != 1
            or not isinstance(tree.body[0].targets[0], ast.Name)
            or tree.body[0].targets[0].id != 'VALUES'):
        raise AssertionError('unexpected fixture source')
    values = ast.literal_eval(tree.body[0].value)
    if not isinstance(values, dict):
        raise AssertionError('fixture mapping missing')
    return values


def released_history(reviewed):
    """Resolve the complete release chain of these known fixture participants.

    No timestamp or equal-byte choice of last owner: every release names its
    predecessor, and the whole chain must have one initial root and one tip.
    Real callers must interpret their actual records, not blindly copy IDs.
    """
    releases = {}
    for name, item in reviewed['relevant_handoffs'].items():
        if item.get('uncertainty') or item.get('manual_review'):
            raise AssertionError('uncertain fixture provenance')
        text = item['handoff']
        if text == '- Scope inventory: complete\n- Scope: none':
            continue
        if (not name.startswith('worker-') or '- Scope inventory: complete' not in text
                or f'- Release reference: {name}-done' not in text
                or '- Writers: synchronous edit completed; no child writers.' not in text):
            raise AssertionError('unrecognized release')
        predecessor = re.search(r'^- Acquired from: (initial|worker-\d+-done)$', text, re.M)
        source = re.search(r'^- Source SHA256: ([0-9a-f]{64})$', text, re.M)
        if not predecessor or not source:
            raise AssertionError('incomplete fixture lineage')
        releases[name + '-done'] = (predecessor[1], source[1])
    if not releases:
        return 'initial', None
    predecessors = {p for p, _ in releases.values()}
    tips = set(releases) - predecessors
    if len(tips) != 1:
        raise AssertionError('ambiguous release tip')
    tip = current = tips.pop()
    visited = set()
    while current != 'initial':
        if current in visited or current not in releases:
            raise AssertionError('cyclic or missing release lineage')
        visited.add(current)
        current = releases[current][0]
    if visited != set(releases):
        raise AssertionError('disconnected release history')
    return tip, releases[tip][1]


def worker(board, target, name, number):
    scope = {'kind': 'file', 'value': str(target)}
    # Every participant has reached the registry before the one-time start
    # barrier; the parent makes no ownership decisions after it opens.
    SESSION.review(board, scopes=[scope], inputs=[target])
    print('ready', flush=True)
    if sys.stdin.readline() != 'start\n':
        raise AssertionError('missing start barrier')
    deadline = time.monotonic() + 180
    attempts = blocked = 0
    retries = {}
    while True:
        if time.monotonic() >= deadline:
            raise AssertionError('bounded acquisition deadline exhausted')
        attempts += 1
        try:
            reviewed = SESSION.review(board, scopes=[scope], inputs=[target])
        except SESSION.CoordinationError as error:
            if error.uncertain or error.code != 'stale_review':
                raise
            retries[error.code] = retries.get(error.code, 0) + 1
            backoff(attempts)
            continue
        if any(SESSION.CHECK.scopes_overlap(scope, claim)
               for owner in reviewed['ownership'] for claim in owner['claims']):
            blocked += 1
            backoff(attempts)
            continue
        predecessor, released_hash = released_history(reviewed)
        before = target.read_bytes()
        if released_hash is not None and digest(before) != released_hash:
            # An intervening completed worker may have advanced both source and
            # board after this observation; take a wholly new review.
            backoff(attempts)
            continue
        values = mapping(before)
        if name in values:
            raise AssertionError('duplicate participant contribution')
        prepared = dict(values, **{name: number * number + 7})
        content = ('VALUES = ' + repr(prepared) + '\n').encode()
        candidate = record(name, claims=f'- file: {target}',
                           handoff=f'- Scope inventory: complete\n- Scope: file: {target}\n'
                                   f'- Acquired from: {predecessor}')
        try:
            receipt = SESSION.commit(board, name, candidate, reviewed, create=True,
                                     handoffs_reviewed=list(reviewed['relevant_handoffs']))
            acquired = time.monotonic_ns()
            break
        except SESSION.CoordinationError as error:
            # A clean conflict is a new ownership observation, not permission
            # to replay the prepared candidate. Start a fresh fixture review.
            if error.uncertain or error.code not in {'registry_busy', 'stale_review', 'claim_conflict'}:
                raise
            retries[error.code] = retries.get(error.code, 0) + 1
            backoff(attempts)
    if predecessor != 'initial':
        previous_owner = predecessor.removesuffix('-done')
        acknowledgment = SESSION.acknowledgment(receipt, scope=scope,
            previous_owner=previous_owner, release_reference=predecessor,
            request_id='none: independent acquisition after recorded release',
            review_note=f'Resolved full release chain; saved source SHA256 {digest(before)}.').encode()
        original_stdin = sys.stdin
        try:
            sys.stdin = io.TextIOWrapper(io.BytesIO(acknowledgment))
            SESSION.BOARD.publish_message(board, name, previous_owner, 'acquired', '-')
        finally:
            sys.stdin = original_stdin
    edit_attempts = 0
    while True:
        if time.monotonic() >= deadline:
            raise AssertionError('bounded save deadline exhausted; claim retained')
        edit_attempts += 1
        try:
            result = EDIT.edit(board, name, target, digest(before), content,
                               record_sha256=receipt['record_sha256'], wait=.5)
            break
        except EDIT.EditError as error:
            if error.uncertain or error.code not in {'registry_busy', 'stale_review'}:
                raise
            # These fixture clients own their reservation throughout the loop.
            # No automatic retry if either saved ownership or source changed.
            if (digest((board / 'sessions' / (name + '.md')).read_bytes()) != receipt['record_sha256']
                    or target.read_bytes() != before):
                raise AssertionError('save inputs changed; fixture requires replanning') from error
            retries[error.code] = retries.get(error.code, 0) + 1
            backoff(edit_attempts)
    finished = time.monotonic_ns()
    actual = target.read_bytes()
    if actual != content or mapping(actual) != prepared:
        raise AssertionError('saved contribution or earlier work lost')
    if result['sha256'] != digest(actual) or result['claims_released']:
        raise AssertionError('invalid edit receipt')
    handoff = (f'- Scope inventory: complete\n- Scope: file: {target}\n'
               f'- Release reference: {name}-done\n'
               f'- Acquired from: {predecessor}\n'
               '- Writers: synchronous edit completed; no child writers.\n'
               f'- Source SHA256: {digest(actual)}')
    closing = record(name, state='done', handoff=handoff)
    release_attempts = 0
    while True:
        if time.monotonic() >= deadline:
            raise AssertionError('bounded release deadline exhausted; claim retained')
        release_attempts += 1
        try:
            reviewed = SESSION.review(board, scopes=[scope], inputs=[target])
            SESSION.commit(board, name, closing, reviewed,
                           expected_sha256=receipt['record_sha256'])
            break
        except SESSION.CoordinationError as error:
            if error.uncertain or error.code not in {'registry_busy', 'stale_review'}:
                raise
            retries[error.code] = retries.get(error.code, 0) + 1
            backoff(release_attempts)
    print(json.dumps({'name': name, 'pid': os.getpid(), 'attempts': attempts,
                      'blocked': blocked, 'retries': retries,
                      'release_attempts': release_attempts,
                      'edit_attempts': edit_attempts, 'acquired_from': predecessor,
                      'preimage': digest(before), 'postimage': digest(content),
                      'acquired_ns': acquired, 'finished_ns': finished}), flush=True)


@unittest.skipUnless(os.name == 'posix' and hasattr(os, 'listxattr'),
                     'guarded-save process qualification requires POSIX metadata primitives')
class IndependentWriters(unittest.TestCase):
    def scenario(self, shared):
        count = int(os.environ.get('FOUNDATION_AGENT_STRESS_WORKERS', '16'))
        self.assertTrue(2 <= count <= 128, 'worker count must be 2..128')
        with tempfile.TemporaryDirectory(prefix='agent-stress-') as temporary:
            base = Path(temporary).resolve()
            board = base / 'board'
            (board / 'sessions').mkdir(parents=True)
            targets = [base / ('shared.py' if shared else f'source-{i}.py') for i in range(count)]
            initial = b'VALUES = {}\n'
            for path in set(targets):
                path.write_bytes(initial)
            children = []
            started = time.monotonic()
            try:
                for i, target in enumerate(targets):
                    children.append(subprocess.Popen(
                        [sys.executable, '-B', str(Path(__file__).resolve()), '--worker',
                         str(board), str(target), f'worker-{i}', str(i)],
                        cwd=base, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE, text=True))
                with selectors.DefaultSelector() as selector:
                    for child in children:
                        selector.register(child.stdout, selectors.EVENT_READ)
                    deadline = time.monotonic() + 45
                    while selector.get_map():
                        events = selector.select(max(0, deadline - time.monotonic()))
                        self.assertTrue(events, 'not all independent clients reached barrier')
                        for key, _ in events:
                            self.assertEqual(key.fileobj.readline(), 'ready\n')
                            selector.unregister(key.fileobj)
                for child in children:
                    child.stdin.write('start\n')
                    child.stdin.flush()
                results = []
                for child in children:
                    out, err = child.communicate(timeout=210)
                    self.assertEqual(child.returncode, 0, err)
                    results.append(json.loads(out))
                self.assertEqual(len({r['pid'] for r in results}), count)
                expected = {f'worker-{i}': i * i + 7 for i in range(count)}
                if shared:
                    self.assertEqual(mapping(targets[0].read_bytes()), expected)
                    ordered = sorted(results, key=lambda r: r['acquired_ns'])
                    previous = digest(initial)
                    for i, result in enumerate(ordered):
                        self.assertEqual(result['preimage'], previous)
                        previous = result['postimage']
                        if i:
                            self.assertLessEqual(ordered[i - 1]['finished_ns'], result['acquired_ns'])
                    self.assertEqual(previous, digest(targets[0].read_bytes()))
                else:
                    for i, target in enumerate(targets):
                        self.assertEqual(mapping(target.read_bytes()), {f'worker-{i}': expected[f'worker-{i}']})
                scan = SESSION.CHECK.scan_sessions(board / 'sessions')
                self.assertTrue(scan['complete'], scan['errors'])
                self.assertEqual(len(scan['records']), count)
                self.assertEqual({r['id'] for r in scan['records']}, set(expected))
                self.assertTrue(all(r['claims'] == 'None.' and r['metadata']['State'] == 'done'
                                    for r in scan['records']))
                self.assertFalse((board / 'registry.lock').exists())
                acknowledgments = list((board / 'messages').glob('*/*.md'))
                self.assertEqual(len(acknowledgments), count - 1 if shared else 0)
                for result in results:
                    previous = result['acquired_from']
                    if previous != 'initial':
                        message = board / 'messages' / previous.removesuffix('-done') / (result['name'] + '-acquired.md')
                        body = message.read_text()
                        for field in (f'- New owner: {result["name"]}\n',
                                      f'- Previous owner / recipient: {previous.removesuffix("-done")}\n',
                                      f'- Release reference: {previous}\n',
                                      f'- Scope: file: {targets[0]}\n',
                                      '- Request ID: none: independent acquisition after recorded release\n',
                                      '- Acquisition record SHA256: '):
                            self.assertIn(field, body)
                print(json.dumps({'workload': 'shared' if shared else 'disjoint',
                                  'processes': count, 'seconds': round(time.monotonic() - started, 3),
                                  'exact_mapping_preserved': True, 'complete_empty_claims': True,
                                  'results': results}), flush=True)
            finally:
                for child in children:
                    if child.poll() is None:
                        child.kill()
                    child.communicate(timeout=10)

    def test_shared_source_preserves_every_contribution(self):
        self.scenario(True)

    def test_disjoint_sources_complete_independently(self):
        self.scenario(False)


if __name__ == '__main__':
    if len(sys.argv) > 1 and sys.argv[1] == '--worker':
        worker(Path(sys.argv[2]), Path(sys.argv[3]), sys.argv[4], int(sys.argv[5]))
    else:
        unittest.main()
