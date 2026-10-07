#!/usr/bin/env python3
"""Checked orchestration for the cooperative board; no service or second registry.

This helper fails closed on unsupported records/claims. It cannot establish the
truth of a handoff, stop another writer, or constrain uncooperative processes.
Review scope-relevant handoffs before committing; a receipt is not a permission
token. Qualified wrappers or isolated writes handle unsupported environments.
"""
import argparse
from collections import namedtuple
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import random
import re
import socket
import sys
import time
import uuid

sys.dont_write_bytecode = True


def load_neighbor(name):
    spec = importlib.util.spec_from_file_location(name.replace('-', '_'),
                                                Path(__file__).with_name(name + '.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


BOARD = load_neighbor('agent_publish')
CHECK = BOARD.record_checker()
RegistryLock = namedtuple('RegistryLock', 'fd token')


class CoordinationError(ValueError):
    """Machine-readable failure; messages are explanatory, never retry selectors."""
    def __init__(self, message, *, code='invalid_request', stage='validation',
                 uncertain=False, retry_action='correct_request'):
        super().__init__(message)
        self.code = code
        self.stage = stage
        self.uncertain = uncertain
        self.retry_action = 'reconcile_saved_state' if uncertain else retry_action

    def as_dict(self):
        return {'code': self.code, 'stage': self.stage, 'uncertain': self.uncertain,
                'retry_action': self.retry_action, 'message': str(self)}


def retry_delay(error, attempt, *, max_attempts=8):
    """Bounded jitter advice, not a retry loop or permission to replay a request.

    Only a clean busy/stale rejection qualifies. For stale_review, reread and
    resolve changed ownership, inputs and handoffs, then rebuild the candidate.
    Do not refresh a hash on a stale prepared edit. Exhaustion returns None;
    uncertain/other errors require their explicit action, never generic retry.
    """
    if (not isinstance(error, CoordinationError) or error.uncertain or
            error.code not in {'registry_busy', 'stale_review'}):
        raise ValueError('only clean registry_busy or stale_review permits retry advice')
    if type(attempt) is not int or type(max_attempts) is not int or not 1 <= attempt or not 1 <= max_attempts <= 32:
        raise ValueError('attempt must be positive and max_attempts must be 1–32')
    if attempt >= max_attempts:
        return None
    # Equal jitter keeps a saturated client from repeatedly drawing very short
    # delays and flooding full-board readers. No worker-count oracle is needed.
    window = min(4.0, .05 * 2 ** min(attempt - 1, 7))
    return random.uniform(window / 2, window)


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def digest(value):
    return hashlib.sha256(value).hexdigest()


def fingerprint(value):
    return digest(json.dumps(value, sort_keys=True, separators=(',', ':')).encode())


def process_start():
    try:
        start = Path('/proc/self/stat').read_text().rsplit(') ', 1)[1].split()[19]
        boot = Path('/proc/sys/kernel/random/boot_id').read_text().strip()
        return f'linux boot={boot}; start_ticks={start}'
    except (OSError, IndexError):
        return 'unavailable on this platform'


@contextmanager
def _registry_mutex(board, session, *, intent='checked record transaction', wait=0):
    """Yield an acquisition-specific handle; never steal or do work under the lock."""
    BOARD.require_capabilities()
    board = BOARD.absolute_path(board)
    BOARD.safe_id(session)
    if not intent or '\n' in intent or '\r' in intent:
        raise CoordinationError('mutex intent must be one nonempty line')
    if not 0 <= wait <= 30:
        raise CoordinationError('mutex wait must be between 0 and 30 seconds')
    with BOARD.open_directory(board) as root:
        BOARD.require_record_board(board, opened=root)
        deadline = time.monotonic() + wait
        while True:
            try:
                os.mkdir('registry.lock', mode=0o700, dir_fd=root)
                break
            except FileExistsError as exc:
                if time.monotonic() >= deadline:
                    raise CoordinationError('registry busy; inspect or retry; never steal the lock',
                                            code='registry_busy', stage='acquisition',
                                            retry_action='bounded_backoff') from exc
                time.sleep(min(random.uniform(.02, .08), max(0, deadline - time.monotonic())))
        with BOARD.child_directory(root, 'registry.lock') as lock:
            token = uuid.uuid4().hex
            owner = (f'- Session: {session}\n- Acquisition token: {token}\n'
                     f'- Host: {socket.gethostname()}\n'
                     f'- UTC: {utc_now()}\n- Role: registry lock holder, not session worker\n'
                     f'- PID/start identity: {os.getpid()} / {process_start()}\n'
                     f'- Intent: {intent}\n').encode()
            created = False
            version = None
            try:
                fd = os.open('owner.md', os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW,
                             0o600, dir_fd=lock)
                created = True
                with os.fdopen(fd, 'wb') as stream:
                    stream.write(owner)
                    stream.flush()
                    os.fsync(stream.fileno())
                _, version = BOARD.read_regular(lock, 'owner.md')
                yield RegistryLock(lock, token)
            finally:
                try:
                    BOARD.verify_board(board, root)
                    BOARD.verify_directory(root, 'registry.lock', lock)
                    if created:
                        current, current_version = BOARD.read_regular(lock, 'owner.md')
                        if current != owner or (version is not None and current_version != version):
                            raise CoordinationError('lock owner changed; cleanup refused; inspect state')
                        # Some mounted filesystems retain the directory listing as
                        # of open(). Reopen relative to the verified lock, keeping
                        # descriptor-relative identity and unknown-entry protection.
                        with BOARD.child_directory(lock, '.') as fresh:
                            if BOARD.identity(os.fstat(fresh)) != BOARD.identity(os.fstat(lock)):
                                raise CoordinationError('mutex identity changed; cleanup refused')
                            entries = sorted(os.listdir(fresh))
                        if entries != ['owner.md']:
                            raise CoordinationError(f'unexpected mutex contents {entries!r}; '
                                                    'preserve owner and inspect state')
                        BOARD.verify_directory(root, 'registry.lock', lock)
                        os.unlink('owner.md', dir_fd=lock)
                    os.rmdir('registry.lock', dir_fd=root)
                except BaseException as exc:
                    raise CoordinationError(str(exc), code='cleanup_uncertain',
                                            stage='cleanup', uncertain=True) from exc


@contextmanager
def registry_mutex(board, session, *, intent='checked record transaction', wait=0):
    """Owned mutex with explicit clean-contention versus uncertain-cleanup errors."""
    entered = False
    body_error = None
    try:
        with _registry_mutex(board, session, intent=intent, wait=wait) as lock:
            entered = True
            try:
                yield lock
            except BaseException as exc:
                body_error = exc
                raise
    except CoordinationError:
        raise
    except BaseException as exc:
        if entered and exc is body_error:
            raise  # The caller body failed after acquisition; cleanup succeeded.
        if entered:
            raise CoordinationError(str(exc), code='cleanup_uncertain',
                                    stage='cleanup', uncertain=True) from exc
        raise CoordinationError(str(exc), code='mutex_uncertain',
                                stage='acquisition', uncertain=True) from exc


def replace_section(text, name, value):
    if not value.strip():
        raise CoordinationError(f'{name}: explicit current text required')
    headings = CHECK.headings_in(text)
    CHECK.section_text(text, headings, name)
    heading = next(h for h in headings if h[2].strip() == name)
    end = next((h.start() for h in headings if h.start() > heading.start()
                and len(h[1]) <= 2), len(text))
    return text[:heading.end()] + '\n' + value.strip() + '\n' + text[end:]


def set_fields(text, changes):
    section = CHECK.section_text(text, CHECK.headings_in(text), 'Current checkpoint')
    for key, value in changes.items():
        if key not in CHECK.REQUIRED_FIELDS or not isinstance(value, str) or '\n' in value or '\r' in value:
            raise CoordinationError('checkpoint fields need known labels and single-line strings')
        section, count = re.subn(r'^- ' + re.escape(key) + r':[^\n]*$',
                                lambda _: f'- {key}: {value}', section, flags=re.M)
        if count != 1:
            raise CoordinationError(f'{key}: need exactly one existing field')
    return replace_section(text, 'Current checkpoint', section)


def checkpoint(before, *, state, running_jobs, progress, handoff, next_check,
               progress_at=None, inbox_at=None, updated_at=None):
    """Replace current status together, retaining event times unless explicit.

    Times describe completed observations, never wrapper invocation. This builder
    cannot change claims or close a session. Commit stamps publication time again.
    """
    if state not in {'active', 'waiting', 'paused'}:
        raise CoordinationError('checkpoint cannot close/reopen a session')
    changes = {'State': state, 'Running jobs': running_jobs,
               'Next check (UTC) / action': next_check,
               'Updated (UTC)': updated_at or utc_now()}
    if progress_at is not None:
        changes['Last meaningful progress (UTC)'] = progress_at
    if inbox_at is not None:
        changes['Last inbox check (UTC)'] = inbox_at
    result = set_fields(before, changes)
    result = replace_section(result, 'Progress and checks', progress)
    result = replace_section(result, 'Blockers and handoff', handoff)
    CHECK.check_transition(before, result)
    if CHECK.parse_record(before)[2] != CHECK.parse_record(result)[2]:
        raise CoordinationError('checkpoint unexpectedly changed claims')
    return result


def _read_observed_regular(parent, name):
    """Keep publisher read guarantees and type only an observed identity change."""
    before = os.stat(name, dir_fd=parent, follow_symlinks=False)
    try:
        return BOARD.read_regular(parent, name)
    except (BOARD.PublicationError, FileNotFoundError) as exc:
        try:
            current = os.stat(name, dir_fd=parent, follow_symlinks=False)
        except FileNotFoundError:
            raise CHECK.SnapshotChanged('observed file disappeared during read') from exc
        if BOARD.file_version(before) != BOARD.file_version(current):
            raise CHECK.SnapshotChanged('observed file changed during read') from exc
        raise


def input_state(value):
    """Exact observed baseline, including absence/identity; not an input lease.

    Pair this check with stable inputs or an isolated snapshot. It cannot prove
    no edit/revert happened between observations or freeze a later read/write.
    """
    original = BOARD.absolute_path(value)
    physical = original.resolve(strict=False)
    try:
        with BOARD.open_directory(physical.parent) as parent:
            data, version = _read_observed_regular(parent, physical.name)
        if original.resolve(strict=False) != physical:
            raise CoordinationError(f'{original}: alias changed during input observation',
                                    code='stale_review', stage='review',
                                    retry_action='rereview_and_replan')
        return {'path': str(original), 'physical': str(physical), 'kind': 'file',
                'sha256': digest(data), 'version': list(version)}
    except FileNotFoundError:
        # Resolve again to catch an ancestor/link changing while checking absence.
        if original.resolve(strict=False) != physical or original.exists():
            raise CoordinationError(f'{original}: changed during missing-input observation',
                                    code='stale_review', stage='review',
                                    retry_action='rereview_and_replan')
        return {'path': str(original), 'physical': str(physical), 'kind': 'missing'}


def normalized_scopes(scopes):
    return [CHECK.canonical_scope(s['kind'], s['value']) for s in scopes]


def read_record_bytes(path):
    """Keep exact publication bytes while matching the reader's newline semantics."""
    with BOARD.open_directory(path.parent) as parent:
        try:
            data, _ = _read_observed_regular(parent, path.name)
        except FileNotFoundError as exc:
            raise CHECK.SnapshotChanged('observed record disappeared before supplemental read') from exc
    text = data.decode('utf-8').replace('\r\n', '\n').replace('\r', '\n')
    return data, text


def _review(board, *, scopes=(), handoffs=(), inputs=(), legacy_reviews=None):
    """Return a review token; no lock or ownership decision is made here.

    All current ownership is scanned. Selected handoffs are exact snapshots;
    Every handoff is fingerprinted for the conservative fallback. A second scoped
    fingerprint includes overlapping owners and every relevant/uncertain handoff,
    including legacy records. Commit uses it only when the reviewed scopes cover
    all prior and proposed claims; ordinary progress timestamps are excluded.
    """
    board = BOARD.absolute_path(board)
    BOARD.require_record_board(board)
    scopes = normalized_scopes(scopes)
    inputs = tuple(inputs)
    watched_scopes = scopes + normalized_scopes(
        [{'kind': 'file', 'value': str(path)} for path in inputs])
    with BOARD.open_directory(board) as opened:
        board_identity = list(BOARD.identity(os.fstat(opened)))
    legacy_reviews = legacy_reviews or {}
    scan = CHECK.scan_sessions(board / 'sessions')
    ownership, hashes, relevant, all_handoffs = [], {}, {}, {}
    interpreted = set()
    transient_errors = []
    for error in scan['errors']:
        if error.get('code') == 'snapshot_changed':
            transient_errors.append(error)
            continue
        path = Path(error['path'])
        session = path.stem
        assessment = legacy_reviews.get(session)
        if (path.parent != board / 'sessions' or path.name != session + '.md' or
                assessment is None or not isinstance(assessment.get('reason'), str) or
                not assessment['reason'].strip() or session in interpreted or
                any(r['id'] == session for r in scan['records'])):
            raise CoordinationError('incomplete registry; inspect every reported entry: ' +
                                    json.dumps(scan['errors'], separators=(',', ':')),
                                    code='registry_invalid', stage='review',
                                    retry_action='inspect_registry')
        BOARD.safe_id(session)
        raw, text = read_record_bytes(path)
        hashed = digest(raw)
        if hashed != assessment.get('sha256'):
            raise CoordinationError('legacy record differs from exact manually reviewed bytes')
        claims = [CHECK.validate_claim_scope(entry['kind'], entry['value'])
                  for entry in assessment['claims']]
        ownership.append({'id': session, 'claims': claims})
        hashes[session] = hashed
        all_handoffs[session] = {'manual_record_sha256': hashed}
        relevant[session] = {'manual_review': assessment['reason'], 'sha256': hashed}
        interpreted.add(session)
    if interpreted != set(legacy_reviews):
        raise CoordinationError('legacy review is absent, duplicate, or no longer needed; review again')
    if transient_errors:
        raise CoordinationError('registry snapshot changed; reread after publication settles',
                                code='stale_review', stage='review',
                                retry_action='rereview_and_replan')
    for record in scan['records']:
        claims = CHECK.parse_claims(record['claims'])
        ownership.append({'id': record['id'], 'claims': claims})
        path = Path(record['path'])
        raw, text = read_record_bytes(path)
        # Reject changing ownership between the scan and this selective reread.
        if CHECK.parse_record(text)[2] != record['claims']:
            raise CoordinationError('claims changed during review; retry', code='stale_review',
                                    stage='review', retry_action='rereview_and_replan')
        hashes[record['id']] = digest(raw)
        handoff = CHECK.section_text(text, CHECK.headings_in(text), 'Blockers and handoff')
        all_handoffs[record['id']] = handoff
        selected = record['id'] in handoffs
        error = None
        if watched_scopes:
            try:
                selected = CHECK.handoff_relevance(text, watched_scopes) or selected
            except ValueError as exc:
                selected, error = True, str(exc)
        if selected:
            relevant[record['id']] = {'handoff': handoff, 'uncertainty': error}
    if set(handoffs) - set(hashes):
        raise CoordinationError('requested handoff record is absent; resolve provenance')
    with BOARD.open_directory(board) as opened:
        if list(BOARD.identity(os.fstat(opened))) != board_identity:
            raise CoordinationError('board replaced during review; inspect agreed root')
    token = {'board': str(board), 'board_identity': board_identity,
             'scopes': scopes, 'handoffs': list(handoffs),
             'ownership': ownership, 'relevant_handoffs': relevant,
             'legacy_reviews': legacy_reviews,
             'handoff_fingerprint': fingerprint(all_handoffs),
             'record_hashes': hashes, 'inputs': [input_state(p) for p in inputs]}
    token['fingerprint'] = fingerprint({key: token[key] for key in
                                      ('board', 'board_identity', 'scopes', 'ownership',
                                       'handoff_fingerprint', 'inputs')})
    # Discovery uncertainty is never filtered out. In particular a partial or
    # opaque handoff remains relevant even when a typed row names another file.
    # Recompute from the full under-mutex scan, not an index or cached subset.
    scoped_owners = [owner for owner in ownership
                     if any(CHECK.scopes_overlap(claim, scope)
                            for claim in owner['claims'] for scope in watched_scopes)]
    token['scope_fingerprint'] = fingerprint({
        'board': token['board'], 'board_identity': board_identity, 'scopes': scopes,
        'ownership': scoped_owners, 'handoffs': relevant, 'inputs': token['inputs']})
    return token


def review(board, *, scopes=(), handoffs=(), inputs=(), legacy_reviews=None):
    """Read a complete snapshot; only typed observed races permit bounded retry."""
    try:
        return _review(board, scopes=scopes, handoffs=handoffs, inputs=inputs,
                       legacy_reviews=legacy_reviews)
    except CoordinationError:
        raise
    except CHECK.SnapshotChanged as exc:
        raise CoordinationError(str(exc), code='stale_review', stage='review',
                                retry_action='rereview_and_replan') from exc
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise CoordinationError(str(exc), code='registry_invalid', stage='review',
                                retry_action='inspect_registry') from exc


def _commit(board, session, candidate, reviewed, *, create=False, expected_sha256=None,
            precondition=None, after=None, wait=0, handoffs_reviewed=(), _state):
    """Publish/verify/clean up, then run dependent work outside the mutex.

    precondition performs read-only semantic review *before* locking and must
    return True. handoffs_reviewed explicitly acknowledges reading/resolving all
    returned discovery candidates; it does not choose or verify the last owner.
    Any failure prevents after(), including uncertain publication/cleanup. The
    exact saved record remains authoritative even when this function raises.
    """
    BOARD.safe_id(session)
    board = BOARD.absolute_path(board)
    if reviewed['board'] != str(board):
        raise CoordinationError('review belongs to another board')
    if create == (expected_sha256 is not None):
        raise CoordinationError('choose create or exact reviewed own-record SHA-256')
    if not create and reviewed['record_hashes'].get(session) != expected_sha256:
        raise CoordinationError('own record hash does not match the reviewed snapshot')
    _state['stage'] = 'precondition'
    if precondition is not None and precondition() is not True:
        raise CoordinationError('precondition failed; no acquisition or dependent action',
                                code='precondition_failed', stage='precondition')
    _state['stage'] = 'validation'
    CHECK.scan_record(candidate, board / 'sessions' / (session + '.md'))
    _, candidate_fields, candidate_claims = CHECK.parse_record(candidate)
    if candidate_fields['State'] in CHECK.TERMINAL and after is not None:
        raise CoordinationError('terminal commit cannot run an after callback into released scope')
    proposed = CHECK.parse_claims(candidate_claims)
    prior = next((r['claims'] for r in reviewed['ownership'] if r['id'] == session), [])
    additions = [scope for scope in proposed if scope not in prior]
    for scope in proposed:
        if scope not in prior and scope not in reviewed['scopes']:
            raise CoordinationError('every added claim requires exact scope review')
    _state['stage'] = 'acquisition'
    with registry_mutex(board, session, wait=wait) as lock:
        _state['stage'] = 'review'
        current = review(board, scopes=reviewed['scopes'], handoffs=reviewed['handoffs'],
                         inputs=[entry['path'] for entry in reviewed['inputs']],
                         legacy_reviews=reviewed['legacy_reviews'])
        # The candidate may introduce an absent path not present in any current
        # record. Revalidate its filesystem kind/aliases inside the mutex too.
        # A changed normalization never authorizes a newly redirected proposal.
        if CHECK.parse_claims(candidate_claims) != proposed:
            raise CoordinationError('proposed claim identity changed; reread and replan',
                                    code='stale_review', stage='review',
                                    retry_action='rereview_and_replan')
        # Empty/narrow scope reviews retain the conservative global baseline.
        # This is especially important when releasing previously held scope:
        # proposed claims alone cannot describe its remaining dependencies.
        complete_scope = bool(reviewed['scopes']) and all(
            scope in reviewed['scopes'] for scope in prior + proposed)
        fingerprint_key = ('scope_fingerprint' if complete_scope and
                           'scope_fingerprint' in reviewed else 'fingerprint')
        if current[fingerprint_key] != reviewed[fingerprint_key]:
            raise CoordinationError('reviewed ownership, handoff or input changed; review again',
                                    code='stale_review', stage='review',
                                    retry_action='rereview_and_replan')
        if not create and current['record_hashes'].get(session) != expected_sha256:
            raise CoordinationError('stale baseline: own record changed; review again',
                                    code='stale_review', stage='review',
                                    retry_action='rereview_and_replan')
        if additions and set(handoffs_reviewed) != set(reviewed['relevant_handoffs']):
            raise CoordinationError('read and resolve every returned candidate/uncertain handoff; '
                                    'pass their exact IDs as handoffs_reviewed; no last owner is inferred')
        for owner in current['ownership']:
            if owner['id'] != session:
                for theirs in owner['claims']:
                    if any(CHECK.scopes_overlap(ours, theirs) for ours in proposed):
                        raise CoordinationError(f'claim overlaps owner {owner["id"]}; request handoff',
                                                code='claim_conflict', stage='review',
                                                retry_action='request_handoff')
        candidate = set_fields(candidate, {'Updated (UTC)': utc_now()})
        # Validate lifecycle semantics before any candidate staging/publication.
        # A malformed close or backwards event time is a clean caller error,
        # while publisher revalidation still guards the actual save boundary.
        _state['stage'] = 'validation'
        CHECK.check_transition(candidate, candidate)
        if create:
            if session in current['record_hashes']:
                raise CoordinationError('session already exists; choose a fresh session ID')
        else:
            with BOARD.open_directory(board / 'sessions') as records:
                previous, _ = BOARD.read_regular(records, session + '.md')
            if digest(previous) != expected_sha256:
                raise CoordinationError('own record changed during transition validation',
                                        code='stale_review', stage='review',
                                        retry_action='rereview_and_replan')
            previous = previous.decode('utf-8')
            if CHECK.parse_record(previous)[1]['State'] in CHECK.TERMINAL:
                raise CoordinationError('terminal session cannot publish again; register a fresh session ID')
            CHECK.check_transition(previous, candidate)
        data = candidate.encode()
        _state['stage'] = 'publication'
        with BOARD.staged_bytes(lock.fd, data) as temporary:
            BOARD.publish_record(board, session, str(board / 'registry.lock' / temporary),
                                 create=create, expected_sha256=expected_sha256,
                                 lock_token=lock.token)
        with BOARD.open_directory(board / 'sessions') as records:
            saved, _ = BOARD.read_regular(records, session + '.md')
        if saved != data:
            raise CoordinationError('saved record differs; publication unconfirmed')
        receipt = {'board': str(board), 'session': session, 'record_sha256': digest(saved),
                   'claims': proposed, 'updated': CHECK.parse_record(candidate)[1]['Updated (UTC)']}
        _state['stage'] = 'cleanup'
    # No user callback or command executes while holding the registry mutex.
    if after is not None:
        _state['stage'] = 'callback'
        after(receipt)
    return receipt


def commit(board, session, candidate, reviewed, *, create=False, expected_sha256=None,
           precondition=None, after=None, wait=0, handoffs_reviewed=()):
    """Checked transaction; uncertain failures must be reconciled, never replayed.

    A clean registry_busy can use bounded backoff. stale_review requires rereading
    and replanning, claim_conflict requires a handoff. Publication, cleanup and
    callback failures may follow durable changes and never permit automatic retry.
    Success receipts retain the existing API and authorize only their saved claims.
    """
    state = {'stage': 'validation'}
    try:
        return _commit(board, session, candidate, reviewed, create=create,
                       expected_sha256=expected_sha256, precondition=precondition,
                       after=after, wait=wait, handoffs_reviewed=handoffs_reviewed,
                       _state=state)
    except BaseException as exc:
        stage = state['stage']
        if isinstance(exc, CoordinationError) and exc.uncertain:
            raise
        if stage in {'publication', 'cleanup', 'callback'}:
            raise CoordinationError(str(exc), code=stage + '_uncertain',
                                    stage=stage, uncertain=True) from exc
        if isinstance(exc, CoordinationError):
            raise
        code = 'precondition_failed' if stage == 'precondition' else 'invalid_request'
        raise CoordinationError(str(exc), code=code, stage=stage) from exc


def acknowledgment(receipt, *, scope, previous_owner, release_reference,
                   request_id, review_note):
    """Format a complete acquisition acknowledgment; do not publish or acquire.

    The caller must resolve the real predecessor, keep its claim held, publish
    this message atomically, and stop dependent edits if publication fails.
    A supplied receipt is prior evidence, not a continuing ownership lease.
    Free-text references/review notes are not machine-verified release lineage.
    """
    def line(value, field):
        if (not isinstance(value, str) or not value.strip() or value != value.strip()
                or len(value) > 2048 or any(ord(c) < 32 or ord(c) == 127 for c in value)
                or len(value.splitlines()) != 1):
            raise CoordinationError(field + ' must be a nonempty bounded single line')
        return value

    if not isinstance(receipt, dict):
        raise CoordinationError('provide the successful acquisition receipt')
    owner = BOARD.safe_id(line(receipt.get('session'), 'receipt session'))
    previous_owner = BOARD.safe_id(line(previous_owner, 'previous owner'))
    board = str(BOARD.absolute_path(line(receipt.get('board'), 'receipt board')))
    record_hash = line(receipt.get('record_sha256'), 'receipt record SHA256')
    if not re.fullmatch('[0-9a-f]{64}', record_hash):
        raise CoordinationError('receipt record SHA256 must be exact lowercase SHA256')
    updated = line(receipt.get('updated'), 'receipt timestamp')
    CHECK.timestamp(updated, 'receipt timestamp')
    if not isinstance(scope, dict) or set(scope) != {'kind', 'value'}:
        raise CoordinationError('provide one exact typed granted scope')
    canonical = CHECK.canonical_scope(line(scope['kind'], 'scope kind'),
                                      line(scope['value'], 'scope value'))
    if scope != canonical or not isinstance(receipt.get('claims'), list) or scope not in receipt['claims']:
        raise CoordinationError('scope must exactly match a canonical claim in the acquisition receipt')
    release_reference = line(release_reference, 'release reference')
    request_id = line(request_id, 'request ID or explicit no-request explanation')
    if request_id.lower() in {'none', 'none.', 'n/a'}:
        raise CoordinationError('explain why no request exists; do not invent an ID')
    review_note = line(review_note, 'review note')
    return (f'Acquisition acknowledgment\n- New owner: {owner}\n'
            f'- Previous owner / recipient: {previous_owner}\n'
            f'- Coordination root: {board}\n'
            f'- Scope: {scope["kind"]}: {scope["value"]}\n'
            f'- Release reference: {release_reference}\n- Request ID: {request_id}\n'
            f'- Acquisition record SHA256: {record_hash}\n- Acquired at (UTC): {updated}\n'
            f'- Reviewed predecessor and saved state: {review_note}\n')


def capabilities():
    """Report API prerequisites only; actual filesystem qualification is separate."""
    missing = []
    try:
        BOARD.require_capabilities()
    except BOARD.PublicationError as error:
        missing.append(str(error))
    metadata = all(hasattr(os, name) for name in ('listxattr', 'geteuid', 'getegid'))
    return {'record_publication_primitives': not missing,
            'guarded_edit_primitives': not missing and metadata,
            'missing': missing + ([] if metadata else ['guarded saves require descriptor metadata inspection']),
            'filesystem_qualified': False,
            'qualification': 'Run focused operation and failure tests on the actual board filesystem; '
                             'API availability, skipped tests and isolated-output use do not qualify shared writes.'}


def initialize(board):
    """Initialize one explicitly agreed fresh record board; never migrate implicitly."""
    BOARD.require_capabilities()
    board = BOARD.absolute_path(board)
    started = False
    try:
        with BOARD.open_directory(board.parent) as parent:
            try:
                os.stat(board.name, dir_fd=parent, follow_symlinks=False)
            except FileNotFoundError:
                started = True
                os.mkdir(board.name, mode=0o700, dir_fd=parent)
            with BOARD.child_directory(parent, board.name) as root:
                BOARD.require_record_board(board, opened=root)
                names = ('sessions', 'messages', 'notes', 'artifacts', 'heartbeats')
                # Reject known bad namespaces before creating anything inside
                # an existing board. Never repair an alias/type mismatch here.
                for name in names:
                    try:
                        os.stat(name, dir_fd=root, follow_symlinks=False)
                    except FileNotFoundError:
                        continue
                    with BOARD.child_directory(root, name):
                        pass
                started = True
                for name in names:
                    with BOARD.child_directory(root, name, create=True):
                        pass
                BOARD.verify_board(board, root)
    except (OSError, ValueError) as error:
        if started:
            raise CoordinationError(str(error), code='initialization_uncertain',
                                    stage='initialization', uncertain=True) from error
        raise
    return {'board': str(board), 'protocol': 'records', 'initialized': True}


def render_record(session, identity, checkpoint, claims, baseline, progress, handoff):
    """Render and validate a complete candidate, without publishing or inventing events."""
    BOARD.safe_id(session)
    if set(identity) != set(CHECK.PREAMBLE_FIELDS) or set(checkpoint) != set(CHECK.REQUIRED_FIELDS):
        raise CoordinationError('provide every exact identity and checkpoint field')
    for value in list(identity.values()) + list(checkpoint.values()):
        if not isinstance(value, str) or not value.strip() or '\n' in value or '\r' in value:
            raise CoordinationError('identity and checkpoint values must be nonempty single lines')
    if not isinstance(claims, list):
        raise CoordinationError('claims must be a list of exact typed scopes')
    normalized = normalized_scopes(claims)
    sections = {'Claims held': '\n'.join(f'- {c["kind"]}: {c["value"]}' for c in normalized) or 'None.',
                'Baseline and dependencies': baseline, 'Progress and checks': progress,
                'Blockers and handoff': handoff}
    for name, value in sections.items():
        if not isinstance(value, str) or not value.strip():
            raise CoordinationError(name + ' requires explicit current text')
    text = '# ' + session + '\n' + ''.join(f'- {k}: {identity[k]}\n' for k in CHECK.PREAMBLE_FIELDS)
    text += '## Current checkpoint\n' + ''.join(f'- {k}: {checkpoint[k]}\n' for k in CHECK.REQUIRED_FIELDS)
    text += ''.join(f'## {name}\n{value.strip()}\n' for name, value in sections.items())
    CHECK.scan_record(text, Path(session + '.md'))
    CHECK.check_transition(text, text)
    return {'candidate': text}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation', choices=('capabilities', 'init', 'render', 'review', 'checkpoint', 'commit', 'acknowledgment'))
    parser.add_argument('--input', default='-', help='JSON request on stdin or claimed absolute file')
    parser.add_argument('--json-errors', action='store_true',
                        help='emit structured failure JSON to stderr; success JSON is unchanged')
    args = parser.parse_args(argv)
    operation_complete = False
    try:
        request = ({} if args.operation == 'capabilities' and args.input == '-'
                   else json.loads(BOARD.source_bytes(args.input)))
        if args.operation == 'capabilities':
            result = capabilities(**request)
        elif args.operation == 'init':
            result = initialize(**request)
        elif args.operation == 'render':
            result = render_record(**request)
        elif args.operation == 'review':
            result = review(**request)
        elif args.operation == 'checkpoint':
            result = {'candidate': checkpoint(**request)}
        elif args.operation == 'acknowledgment':
            result = {'message': acknowledgment(**request)}
        else:
            result = commit(**request)
        operation_complete = True
        print(json.dumps(result, separators=(',', ':')), flush=True)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        if operation_complete:
            error = CoordinationError(str(exc), code='output_uncertain',
                                      stage='output', uncertain=True)
        elif isinstance(exc, CoordinationError):
            error = exc
        else:
            error = CoordinationError(str(exc))
        if args.json_errors:
            print(json.dumps({'ok': False, 'error': error.as_dict()}, separators=(',', ':')),
                  file=sys.stderr, flush=True)
        else:
            print(f'agent_session: {error}\n{error.code}: {error.retry_action}. '
                  'Stop dependent actions; inspect saved state before retrying.', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
