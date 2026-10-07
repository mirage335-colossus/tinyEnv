#!/usr/bin/env python3
"""Bounded synchronous source saves for independently cooperating sessions.

This does not acquire/release claims, run commands, or supervise descendants.
Callers retain ownership through validation and reconcile every uncertain result.
An unrestricted writer can bypass these checks; enforce tool access separately.
Only existing regular files up to 8 MiB, owned by the invoking uid/gid with no
extended attributes or special permission bits, are supported. Atomic replacement
changes inode identity. No direct-write fallback is provided.
The owner must not concurrently release its claim while staging or invoking this
helper; it does not supervise sibling calls, arbitrary children or queued saves.
Coordination-board paths cannot be edited through this source adapter.
"""
import argparse
from contextlib import contextmanager
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import stat
import sys
import uuid

sys.dont_write_bytecode = True
SPEC = importlib.util.spec_from_file_location('agent_edit_session', Path(__file__).with_name('agent_session.py'))
SESSION = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(SESSION)
BOARD = SESSION.BOARD
MAX_BYTES = 8 * 1024 * 1024


class EditError(ValueError):
    def __init__(self, message, *, code='edit_rejected', uncertain=False):
        super().__init__(message)
        self.code = code
        self.uncertain = uncertain

    def as_dict(self):
        action = ('reconcile_saved_state' if self.uncertain else
                  'bounded_backoff' if self.code == 'registry_busy' else
                  'rereview_and_replan' if self.code == 'stale_review' else
                  'inspect_and_replan')
        return {'code': self.code, 'uncertain': self.uncertain,
                'retry_action': action,
                'message': str(self)}


def digest(data):
    return hashlib.sha256(data).hexdigest()


def _metadata(fd):
    info = os.fstat(fd)
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
        raise EditError('target must be a singly linked regular file')
    if info.st_size > MAX_BYTES or info.st_uid != os.geteuid() or info.st_gid != os.getegid():
        raise EditError('unsupported source size or ownership')
    if stat.S_IMODE(info.st_mode) & ~0o777:
        raise EditError('special permission bits are unsupported')
    if not hasattr(os, 'listxattr'):
        raise EditError('extended attribute inspection unavailable; no metadata-loss fallback')
    if os.listxattr(fd):
        raise EditError('extended attributes/ACLs require a metadata-preserving editor')
    return info


def _read(parent, name):
    fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
    with os.fdopen(fd, 'rb') as source:
        before = _metadata(source.fileno())
        data = source.read(MAX_BYTES + 1)
        after = _metadata(source.fileno())
        current = os.stat(name, dir_fd=parent, follow_symlinks=False)
        if (len(data) > MAX_BYTES or BOARD.file_version(before) != BOARD.file_version(after)
                or BOARD.file_version(after) != BOARD.file_version(current)):
            raise EditError('source changed during bounded read')
        return data, BOARD.file_version(after), stat.S_IMODE(after.st_mode)


def _reservation(board, session, path, record_sha256, legacy_reviews):
    reviewed = SESSION.review(board, legacy_reviews=legacy_reviews)
    if reviewed['record_hashes'].get(session) != record_sha256:
        raise EditError('own reservation changed or is absent; inspect current saved record')
    with BOARD.open_directory(Path(board) / 'sessions') as records:
        raw, _ = BOARD.read_regular(records, session + '.md')
    if digest(raw) != record_sha256:
        raise EditError('own reservation changed during inspection')
    if SESSION.CHECK.parse_record(raw.decode())[1]['State'] in SESSION.CHECK.TERMINAL:
        raise EditError('terminal sessions cannot edit')
    target = {'kind': 'file', 'value': str(path)}
    own = next((owner['claims'] for owner in reviewed['ownership'] if owner['id'] == session), [])
    # Conservative case/Unicode folding is appropriate for rejecting another
    # owner's possible conflict, never for granting authority to a distinct
    # source on a case-sensitive filesystem. Actual canonical containment only.
    if not any((claim['kind'] == 'file' and claim['value'] == str(path)) or
               (claim['kind'] == 'directory' and Path(claim['value']) in path.parents)
               for claim in own):
        raise EditError('source has no current own file or covering-directory reservation')
    for owner in reviewed['ownership']:
        if owner['id'] != session and any(SESSION.CHECK.scopes_overlap(claim, target)
                                         for claim in owner['claims']):
            raise EditError('source overlaps another reservation')


@contextmanager
def _staged(parent, content, mode):
    name = '.agent_edit-' + uuid.uuid4().hex + '.tmp'
    fd = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=parent)
    try:
        identity = BOARD.identity(os.fstat(fd))
        output = os.fdopen(fd, 'wb')
    except BaseException as error:
        try:
            os.close(fd)
        except OSError as close_error:
            raise EditError('staging initialization/descriptor cleanup failed; inspect retained artifact',
                            code='edit_cleanup_uncertain', uncertain=True) from close_error
        # Never unlink a staging path whose identity could not be established.
        raise EditError('staging initialization failed; inspect retained artifact',
                        code='edit_cleanup_uncertain', uncertain=True) from error
    try:
        try:
            output.write(content)
            output.flush()
            os.fchmod(output.fileno(), mode)
            os.fsync(output.fileno())
            _metadata(output.fileno())
        finally:
            try:
                output.close()
            except BaseException as error:
                raise EditError('staging descriptor close failed; inspect saved staging state',
                                code='edit_cleanup_uncertain', uncertain=True) from error
        yield name, identity
    finally:
        try:
            current = os.stat(name, dir_fd=parent, follow_symlinks=False)
        except FileNotFoundError:
            pass  # Successful replacement consumes this invocation's staging name.
        except OSError as error:
            raise EditError('staging cleanup inspection failed; preserve unverified artifact',
                            code='edit_cleanup_uncertain', uncertain=True) from error
        else:
            if BOARD.identity(current) != identity:
                raise EditError('staging identity changed; preserve unfamiliar file',
                                code='edit_cleanup_uncertain', uncertain=True)
            try:
                os.unlink(name, dir_fd=parent)
            except OSError as error:
                raise EditError('owned staging cleanup failed; inspect retained artifact',
                                code='edit_cleanup_uncertain', uncertain=True) from error


def edit(board, session, path, expected_sha256, content, *, record_sha256,
         legacy_reviews=None, wait=0):
    """Replace an owned existing file; return only after publication and cleanup.

    Hash/stage first, then perform bounded byte and reservation rechecks plus
    replacement under the registry mutex. This short source-publication section
    runs no caller callbacks or tests. Claims are never released here, on success
    or failure. A changed inode with equal bytes is rejected as an intervening save.
    """
    attempted = False
    try:
        BOARD.require_capabilities()
        BOARD.safe_id(session)
        path = BOARD.absolute_path(path)
        if str(path.resolve()) != str(path):
            raise EditError('source must use its canonical physical path')
        board_path = BOARD.absolute_path(board).resolve()
        if path == board_path or board_path in path.parents:
            raise EditError('coordination-board files require their dedicated publication protocol')
        if not isinstance(content, bytes) or len(content) > MAX_BYTES:
            raise EditError('content must be bytes of at most 8 MiB')
        if any(not isinstance(value, str) or not re.fullmatch('[0-9a-f]{64}', value)
               for value in (expected_sha256, record_sha256)):
            raise EditError('exact lowercase source and reservation SHA-256 values are required')
        # A busy board may legitimately change throughout an unlocked scan.
        # Take one short observation transaction before writing any staging
        # bytes; the later transaction still rechecks the entire reservation.
        with SESSION.registry_mutex(board, session, intent='source reservation preflight', wait=wait):
            _reservation(board, session, path, record_sha256, legacy_reviews)
        with BOARD.open_directory(path.parent) as parent:
            original, version, mode = _read(parent, path.name)
            if digest(original) != expected_sha256:
                raise EditError('stale source preimage; reread and replan')
            with _staged(parent, content, mode) as (temporary, stage_identity):
                with SESSION.registry_mutex(board, session, intent='bounded atomic source publication', wait=wait):
                    BOARD.verify_board(path.parent, parent)
                    _reservation(board, session, path, record_sha256, legacy_reviews)
                    current, current_version, _ = _read(parent, path.name)
                    if current_version != version or digest(current) != expected_sha256:
                        raise EditError('source changed after staging; reread and replan')
                    staged, stage_version, staged_mode = _read(parent, temporary)
                    if (stage_version[:2] != stage_identity or staged != content
                            or staged_mode != mode):
                        raise EditError('staged identity, bytes or mode changed; no save')
                    attempted = True
                    os.replace(temporary, path.name, src_dir_fd=parent, dst_dir_fd=parent)
                    os.fsync(parent)
                    saved, _, saved_mode = _read(parent, path.name)
                    if saved != content or saved_mode != mode:
                        raise EditError('saved source verification failed')
        return {'path': str(path), 'session': session, 'preimage_sha256': expected_sha256,
                'sha256': digest(content), 'record_sha256': record_sha256,
                'claims_released': False}
    except BaseException as error:
        if attempted:
            raise EditError('source replacement attempted; reconcile saved source and reservation: ' + str(error),
                            code='edit_save_uncertain', uncertain=True) from error
        if isinstance(error, EditError):
            raise
        if (isinstance(error, SESSION.CoordinationError) and not error.uncertain
                and error.code in {'registry_busy', 'stale_review'}):
            # No replacement was attempted and owned staging cleanup completed.
            # Preserve the actionable guard result; never convert uncertain
            # cleanup/publication into a generic contention retry.
            raise EditError(str(error), code=error.code) from error
        raise EditError(str(error), code='edit_guard_uncertain' if getattr(error, 'uncertain', False)
                        else 'edit_rejected', uncertain=getattr(error, 'uncertain', False)) from error


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', default='-', help='JSON request path or stdin; content is UTF-8 text')
    args = parser.parse_args(argv)
    try:
        if args.input == '-':
            raw = sys.stdin.buffer.read(MAX_BYTES * 8 + 1)
        else:
            with open(BOARD.absolute_path(args.input), 'rb') as stream:
                raw = stream.read(MAX_BYTES * 8 + 1)
        if len(raw) > MAX_BYTES * 8:
            raise EditError('JSON request exceeds bounded input size')
        request = json.loads(raw)
        if not isinstance(request, dict) or not isinstance(request.get('content'), str):
            raise EditError('JSON request must be an object with UTF-8 text content')
        request['content'] = request['content'].encode('utf-8')
        receipt = edit(**request)
        try:
            print(json.dumps(receipt), flush=True)
        except BaseException as error:
            raise EditError('receipt output failed; reconcile saved source',
                            code='edit_output_uncertain', uncertain=True) from error
        return 0
    except (EditError, ValueError, TypeError, KeyError, OSError) as error:
        failure = error if isinstance(error, EditError) else EditError(str(error))
        print(json.dumps(failure.as_dict()), file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main())
