#!/usr/bin/env python3
"""Optional complete, atomic publication for the cooperative agent board.

This does not acquire locks, inspect other claims, grant ownership, or recover
abandoned work. The caller must review complete claims while holding its own
registry mutex and pass its acquisition token before publishing a record. A token
guards accidental borrowing/replay, not malicious access to the same filesystem.
Inputs must be in claimed files or
stdin; unvalidated candidates must never be prepared in sessions/. POSIX
descriptor-relative filesystem operations and hard links are required. There is
no unsafe fallback. Atomic visibility is not a promise of crash durability or a
security boundary against participants that ignore the cooperative protocol.
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


class PublicationError(ValueError):
    pass


def safe_id(value):
    if not re.fullmatch(r'[A-Za-z0-9._-]+', value) or value in {'.', '..'}:
        raise PublicationError('IDs must use letters, digits, dots, underscores and hyphens; '
                               'dot and dot-dot are not IDs')
    return value


def require_capabilities():
    operations = (os.open, os.mkdir, os.stat, os.unlink, os.link, os.rename)
    if (not hasattr(os, 'O_NOFOLLOW') or not hasattr(os, 'O_DIRECTORY') or
            any(op not in os.supports_dir_fd for op in operations) or
            os.link not in os.supports_follow_symlinks):
        raise PublicationError('safe publication requires POSIX dir_fd, O_NOFOLLOW and '
                               'hard-link support; no direct-write fallback is available')


def require_record_board(board, opened=None):
    """Never run two authoritative protocols against one live board."""
    def inspect(root):
        try:
            os.stat('state.json', dir_fd=root, follow_symlinks=False)
        except FileNotFoundError:
            pass
        else:
            raise PublicationError('this board uses the compatibility JSON protocol; finish its '
                                   'sessions and run agent_migrate.py before record-protocol writes')
        try:
            raw, _ = read_regular(root, 'protocol.json')
        except FileNotFoundError:
            return  # Existing record boards remain usable without a migration marker.
        marker = json.loads(raw)
        if (not isinstance(marker, dict) or marker.get('protocol') != 'records' or marker.get('version') != 2
                or set(marker) - {'protocol', 'version', 'source_sha256', 'evidence'}):
            raise PublicationError('unknown coordination protocol marker; inspect before writing')
    if opened is not None:
        inspect(opened)
    else:
        with open_directory(board) as root:
            inspect(root)


def identity(info):
    return info.st_dev, info.st_ino


def file_version(info):
    return identity(info) + (info.st_mode, info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def absolute_path(value):
    path = Path(value)
    if not path.is_absolute() or '..' in path.parts:
        raise PublicationError('board and source paths must be absolute without dot-dot components')
    return path


@contextmanager
def open_directory(path):
    """Walk every component without following even an ancestor symlink."""
    path = absolute_path(path)
    fd = os.open(path.anchor, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        for part in path.parts[1:]:
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            os.close(fd)
            fd = child
        yield fd
    finally:
        os.close(fd)


@contextmanager
def child_directory(parent, name, create=False):
    if create:
        try:
            os.mkdir(name, mode=0o700, dir_fd=parent)
        except FileExistsError:
            pass
    fd = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent)
    try:
        yield fd
    finally:
        os.close(fd)


def read_regular(parent, name):
    fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
    with os.fdopen(fd, 'rb') as stream:
        before = os.fstat(stream.fileno())
        if not stat.S_ISREG(before.st_mode):
            raise PublicationError(f'{name}: expected a regular file, not a symlink or special file')
        data = stream.read()
        after = os.fstat(stream.fileno())
        current = os.stat(name, dir_fd=parent, follow_symlinks=False)
        if file_version(before) != file_version(after) or file_version(after) != file_version(current):
            raise PublicationError(f'{name}: source changed while reading; inspect and retry')
        return data, file_version(after)


def source_bytes(source, board=None):
    if source == '-':
        return sys.stdin.buffer.read()
    path = absolute_path(source)
    if board is not None and board / 'sessions' in path.parents:
        raise PublicationError('prepare record candidates in claimed artifacts or stdin, never sessions/')
    with open_directory(path.parent) as parent:
        return read_regular(parent, path.name)[0]


def verify_directory(parent, name, opened):
    current = os.stat(name, dir_fd=parent, follow_symlinks=False)
    if not stat.S_ISDIR(current.st_mode) or identity(current) != identity(os.fstat(opened)):
        raise PublicationError(f'{name}: board directory changed; inspect before retrying')


def verify_board(path, opened):
    with open_directory(path) as current:
        if identity(os.fstat(current)) != identity(os.fstat(opened)):
            raise PublicationError('board directory changed; inspect before retrying')


@contextmanager
def staged_bytes(directory, data):
    """Only this invocation's unguessable, exclusively created temp is removed."""
    name = '.agent_publish-' + uuid.uuid4().hex + '.tmp'
    fd = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                 0o600, dir_fd=directory)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        yield name
    finally:
        try:
            os.unlink(name, dir_fd=directory)
        except FileNotFoundError:
            pass  # Successful record replacement consumed this exact temp name.


def exclusive_publish(source_dir, temporary, target_dir, target):
    try:
        os.link(temporary, target, src_dir_fd=source_dir, dst_dir_fd=target_dir,
                follow_symlinks=False)
    except FileExistsError as exc:
        raise PublicationError(f'{target}: already exists; nothing replaced, use a fresh ID') from exc
    except OSError as exc:
        raise PublicationError(f'{target}: atomic no-replace hard-link publication failed ({exc}); '
                               'nothing replaced; no direct-write fallback') from exc


def publish_message(board, sender, recipient, message_id, body):
    require_capabilities()
    sender, recipient, message_id = map(safe_id, (sender, recipient, message_id))
    board = absolute_path(board)
    require_record_board(board)
    data = source_bytes(body)
    name = f'{sender}-{message_id}.md'
    with open_directory(board) as root, child_directory(root, 'messages', create=True) as messages:
        with child_directory(messages, recipient, create=True) as inbox:
            with staged_bytes(inbox, data) as temporary:
                verify_board(board, root)
                verify_directory(root, 'messages', messages)
                verify_directory(messages, recipient, inbox)
                exclusive_publish(inbox, temporary, inbox, name)
    return board / 'messages' / recipient / name


def record_checker():
    # Keep command and imported uses from generating an unclaimed tools/__pycache__.
    sys.dont_write_bytecode = True
    path = Path(__file__).resolve().with_name('check_agent_record.py')
    spec = importlib.util.spec_from_file_location('agent_record_checker', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def lock_owner(lock, session, lock_token):
    data, version = read_regular(lock, 'owner.md')
    owners = re.findall(r'^- Session:[ \t]*([^\r\n]*)$', data.decode('utf-8'), re.MULTILINE)
    if owners != [session]:
        raise PublicationError('registry.lock/owner.md needs exactly one plain "- Session: ID" '
                               'line matching --session; caller must already hold this mutex')
    tokens = re.findall(r'^- Acquisition token:[ \t]*([^\r\n]*)$', data.decode('utf-8'), re.MULTILINE)
    if tokens != [lock_token]:
        raise PublicationError('registry acquisition token differs or is missing; '
                               'session identity alone is not proof of this lock acquisition')
    return data, version


def publish_record(board, session, candidate, *, create=False, expected_sha256=None,
                   lock_token=None):
    require_capabilities()
    session = safe_id(session)
    if not isinstance(lock_token, str) or not re.fullmatch('[0-9a-f]{32}', lock_token):
        raise PublicationError('provide the acquisition token returned by your owned transaction; '
                               'do not borrow a token from an existing lock')
    if create == (expected_sha256 is not None):
        raise PublicationError('choose exactly one of --create and --expected-sha256')
    if expected_sha256 is not None and not re.fullmatch('[0-9a-fA-F]{64}', expected_sha256):
        raise PublicationError('--expected-sha256 must be the exact current record SHA-256')
    board = absolute_path(board)
    require_record_board(board)
    data = source_bytes(candidate, board)
    text = data.decode('utf-8')
    checker = record_checker()
    target = session + '.md'
    checker.scan_record(text, board / 'sessions' / target)
    checker.check_transition(text, text)
    with open_directory(board) as root, child_directory(root, 'registry.lock') as lock:
        owner = lock_owner(lock, session, lock_token)
        with child_directory(root, 'sessions') as sessions:
            old = None
            if not create:
                old, old_version = read_regular(sessions, target)
                if hashlib.sha256(old).hexdigest() != expected_sha256.lower():
                    raise PublicationError('stale baseline: current record SHA-256 differs; '
                                           'reread current claims and record before retrying')
                previous = old.decode('utf-8')
                checker.scan_record(previous, board / 'sessions' / target)
                if checker.parse_record(previous)[1]['State'] in checker.TERMINAL:
                    raise PublicationError('terminal session cannot publish again; register a fresh session ID')
                checker.check_transition(previous, text)
            # Staging in the already-owned mutex keeps proposals out of sessions/.
            with staged_bytes(lock, data) as temporary:
                verify_board(board, root)
                verify_directory(root, 'registry.lock', lock)
                verify_directory(root, 'sessions', sessions)
                if lock_owner(lock, session, lock_token) != owner:
                    raise PublicationError('registry lock owner changed during publication')
                if create:
                    exclusive_publish(lock, temporary, sessions, target)
                else:
                    current, version = read_regular(sessions, target)
                    if current != old or version != old_version:
                        raise PublicationError('record changed after baseline check; nothing replaced')
                    # Cooperative mutex is the compare/replace boundary. This is
                    # not an operating-system CAS against uncooperative writers.
                    os.replace(temporary, target, src_dir_fd=lock, dst_dir_fd=sessions)
    return board / 'sessions' / target


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    message = sub.add_parser('message', help='publish one immutable complete message; never replace')
    for option in ('board', 'sender', 'recipient', 'id', 'body'):
        message.add_argument('--' + option, required=True)
    message.epilog = '--body is a claimed absolute regular file, or - for stdin.'
    record = sub.add_parser('record', help='publish a checked record under your already-held registry mutex')
    for option in ('board', 'session', 'candidate', 'lock-token'):
        record.add_argument('--' + option, required=True)
    mode = record.add_mutually_exclusive_group(required=True)
    mode.add_argument('--create', action='store_true')
    mode.add_argument('--expected-sha256')
    record.epilog = ('--candidate is a claimed absolute regular file outside sessions/, or - for stdin. '
                     '--lock-token comes from this caller\'s owned acquisition, never an existing lock. '
                     'Review all complete claims yourself under registry.lock; this tool grants no ownership.')
    args = parser.parse_args(argv)
    try:
        if args.command == 'message':
            path = publish_message(args.board, args.sender, args.recipient, args.id, args.body)
        else:
            path = publish_record(args.board, args.session, args.candidate, create=args.create,
                                  expected_sha256=args.expected_sha256, lock_token=args.lock_token)
    except (OSError, ValueError) as exc:
        parser.exit(1, f'agent_publish: {exc}\nPublication not confirmed; inspect current state. '
                    'No claims are granted by this tool.\n')
    print(path)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
