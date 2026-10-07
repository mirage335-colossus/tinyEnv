#!/usr/bin/env python3
"""Compatibility support for existing JSON coordination boards.

New projects use agent_session.py and the complete record protocol. This interface
exists so a running JSON board can close safely before explicit agent_migrate.py.
It is not a sandbox, a distributed lock, or a process supervisor.
"""
import argparse
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import socket
import stat
import subprocess
import sys
import threading
import time
import unicodedata
import uuid

sys.dont_write_bytecode = True
MAX_BYTES = 4 * 1024 * 1024
MAX_RECORDS = 512
TERMINAL = {"done", "failed", "cancelled"}


class Rejected(ValueError):
    def __init__(self, message, code="invalid_request", uncertain=False):
        super().__init__(message)
        self.code, self.uncertain = code, uncertain

    def result(self):
        action = ("reconcile_saved_state" if self.uncertain else
                  "bounded_backoff" if self.code == "busy" else
                  "reread_and_replan" if self.code == "stale" else "inspect_and_correct")
        return {"ok": False, "code": self.code, "uncertain": self.uncertain,
                "action": action, "message": str(self)}


def now():
    return datetime.now(timezone.utc).isoformat()


def timestamp(value):
    if not isinstance(value, str):
        raise Rejected("timestamp must be an ISO UTC string")
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise Rejected("invalid timestamp") from error
    if result.utcoffset() != timedelta(0):
        raise Rejected("timestamp must be UTC")
    return result


def identifier(value):
    if (not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,79}", value)
            or value.rstrip(". ") != value):
        raise Rejected("ID must contain 1–80 safe ASCII characters and start with a letter or digit")
    return value


def text_field(value, label, limit=8192):
    if not isinstance(value, str) or not value.strip() or len(value) > limit or "\x00" in value:
        raise Rejected(label + " requires bounded nonempty text")
    return value


def encoded(value):
    return (json.dumps(value, sort_keys=True, ensure_ascii=True, separators=(",", ":")) + "\n").encode()


def no_duplicates(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise Rejected("duplicate JSON key: " + key, "corrupt")
        result[key] = value
    return result


def decode(data):
    if len(data) > MAX_BYTES:
        raise Rejected("input exceeds size limit; no partial registry is accepted", "capacity")
    try:
        return json.loads(data, object_pairs_hook=no_duplicates)
    except (UnicodeError, ValueError) as error:
        if isinstance(error, Rejected):
            raise
        raise Rejected("invalid JSON; inspect without replacing it", "corrupt") from error


def identity(info):
    return info.st_dev, info.st_ino


def version(info):
    return identity(info) + (info.st_mode, info.st_nlink, info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def cross_version(info):
    # Windows path stat can expose creation time as ctime while fstat exposes
    # change time (CPython issue 157671). Compare each API's full version with
    # itself, and use their common fields only across APIs. Never discard the
    # descriptor ctime check that detects write-and-restore during the read.
    return version(info)[:-1] if os.name == "nt" else version(info)


def safe_path(path):
    """Reject links/reparse points in existing components, including ancestors."""
    path = Path(os.path.abspath(path))
    for parent in reversed((path,) + tuple(path.parents)):
        try:
            info = parent.lstat()
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
            raise Rejected("links/reparse points require a separate verified physical location: " + str(parent))
    return path


def portable_components(path):
    """Reject spellings that alias ordinary paths or devices on another host."""
    for component in path.parts[1:] if path.is_absolute() else path.parts:
        stem = component.split(".", 1)[0].upper()
        if (component.rstrip(". ") != component or any(ord(c) < 32 for c in component)
                or any(c in component for c in '<>:"|?*\\')
                or stem in {"CON", "PRN", "AUX", "NUL"}
                or re.fullmatch(r"(?:COM|LPT)[1-9\u00b9\u00b2\u00b3]", stem)):
            raise Rejected("path component is not portable: " + repr(component))


def read_regular(path):
    safe_path(path)
    before = path.lstat()
    if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1 or before.st_size > MAX_BYTES:
        raise Rejected("expected a bounded singly linked regular file: " + str(path), "corrupt")
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
    fd = os.open(path, flags)
    with os.fdopen(fd, "rb") as stream:
        opened = os.fstat(stream.fileno())
        if cross_version(opened) != cross_version(before):
            raise Rejected("file changed before reading", "stale")
        data = stream.read(MAX_BYTES + 1)
        after = os.fstat(stream.fileno())
    current = path.lstat()
    if (version(opened) != version(after) or version(before) != version(current)
            or cross_version(after) != cross_version(current)):
        raise Rejected("file changed while reading", "stale")
    return data


def fold(path):
    # Conservative for conflicts only; never use folded names to grant authority.
    return unicodedata.normalize("NFC", str(path)).casefold()


def overlap(a, b):
    if a["kind"] == "resource" or b["kind"] == "resource":
        return a["kind"] == b["kind"] and a["value"] == b["value"]
    left, right = fold(a["value"]), fold(b["value"])
    if left == right:
        return True
    separator = os.sep
    return ((a["kind"] == "directory" and right.startswith(left.rstrip(separator) + separator)) or
            (b["kind"] == "directory" and left.startswith(right.rstrip(separator) + separator)))


def covered(held, needed):
    # Exact spelling matters on case-sensitive filesystems.
    return (held == needed or (held["kind"] == "directory" and needed["kind"] != "resource"
            and Path(held["value"]) in Path(needed["value"]).parents))


class Board:
    def __init__(self, root, board=None):
        self.root = safe_path(root)
        if not self.root.is_dir():
            raise Rejected("checkout root must already exist")
        if board is not None and not Path(board).is_absolute():
            raise Rejected("an alternate board must be an explicitly agreed absolute path")
        self.path = safe_path(board if board is not None else self.root / ".agent-work")
        self.state_path = self.path / "state.json"
        self.lock = self.path / "registry.lock"
        self.token = None
        self._lock_guard = None
        self._owner_thread = None

    def scope(self, value):
        if not isinstance(value, dict) or set(value) != {"kind", "value"}:
            raise Rejected("scope requires exactly kind and value")
        kind, name = value["kind"], value["value"]
        if kind == "resource":
            text_field(name, "resource", 240)
            if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9:._/-]*", name):
                raise Rejected("resource name must be an exact portable identifier")
            return {"kind": kind, "value": name}
        if kind not in {"file", "directory"}:
            raise Rejected("scope kind must be file, directory or resource")
        if not isinstance(name, str) or not name or ".." in Path(name).parts:
            raise Rejected("path must be explicit and contain no parent traversal")
        portable_components(Path(name))
        path = safe_path(Path(name) if Path(name).is_absolute() else self.root / name)
        if path in self.path.parents:
            raise Rejected("do not reserve a directory containing the coordination board")
        if path == self.root or path == self.path or self.path in path.parents:
            if not any(parent.name in {"notes", "artifacts"} and parent.parent == self.path
                       for parent in (path,) + tuple(path.parents)):
                raise Rejected("claim exact source paths or per-session notes/artifacts; not the registry")
            if path in {self.path / "notes", self.path / "artifacts"}:
                raise Rejected("do not reserve the shared notes/artifacts namespace")
        try:
            info = path.lstat()
        except FileNotFoundError:
            info = None
        if info is not None:
            correct = stat.S_ISDIR(info.st_mode) if kind == "directory" else stat.S_ISREG(info.st_mode)
            if not correct or (kind == "file" and info.st_nlink != 1):
                raise Rejected("claim kind differs from actual path or file has multiple links")
        return {"kind": kind, "value": str(path)}

    def scopes(self, values):
        if not isinstance(values, list) or not values or len(values) > 128:
            raise Rejected("provide 1–128 explicit scopes")
        result = [self.scope(value) for value in values]
        if len({tuple(v.items()) for v in result}) != len(result):
            raise Rejected("duplicate scopes")
        return result

    @contextmanager
    def mutex(self):
        safe_path(self.path)
        root_identity = identity(self.path.stat())
        denied = None
        # Windows can deny creation while the previous directory is still
        # delete-pending. Retry only exclusive creation, for at most 315 ms of
        # backoff. Nothing owns the mutex until mkdir succeeds; persistent ACL
        # denial remains the original PermissionError, never clean contention.
        for delay in (0, .005, .01, .02, .04, .08, .16):
            if delay:
                time.sleep(delay)
            try:
                self.lock.mkdir(mode=0o700)
            except FileExistsError as error:
                raise Rejected("registry mutex is occupied; never steal it", "busy") from error
            except PermissionError as error:
                if getattr(error, "winerror", None) != 5:
                    raise
                if denied is None:
                    denied = error
            else:
                break
        else:
            raise denied
        lock_identity = identity(self.lock.stat())
        token = uuid.uuid4().hex
        owner = {"token": token, "host": socket.gethostname(), "pid": os.getpid(),
                 "role": "registry transaction", "created": now()}
        owner_path = self.lock / "owner.json"
        owner_bytes = encoded(owner)
        try:
            with owner_path.open("xb") as stream:
                stream.write(owner_bytes)
                stream.flush()
                os.fsync(stream.fileno())
            owner_version = version(owner_path.stat())
        except BaseException as error:
            raise Rejected("mutex initialization uncertain; preserve it for recovery", "mutex_uncertain", True) from error
        self._owner_thread = threading.get_ident()
        self.token = token
        self._lock_guard = (root_identity, lock_identity, owner_version, owner_bytes)
        try:
            yield
        finally:
            self.token = None
            self._lock_guard = None
            self._owner_thread = None
            try:
                safe_path(self.path)
                if (identity(self.path.stat()) != root_identity or identity(self.lock.stat()) != lock_identity
                        or version(owner_path.stat()) != owner_version or read_regular(owner_path) != owner_bytes
                        or sorted(p.name for p in self.lock.iterdir()) != ["owner.json"]):
                    raise OSError("mutex identity or contents changed")
                owner_path.unlink()
                self.lock.rmdir()
            except BaseException as error:
                raise Rejected("mutex cleanup uncertain; inspect saved state and retained lock", "cleanup_uncertain", True) from error

    def check_mutex(self):
        if self.token is not None and self._owner_thread != threading.get_ident():
            raise Rejected("registry mutex belongs to another thread of this invocation", "busy")
        if self.token is None or self._lock_guard is None:
            raise Rejected("publication requires this invocation's mutex")
        root_identity, lock_identity, owner_version, owner_bytes = self._lock_guard
        owner_path = self.lock / "owner.json"
        safe_path(self.path)
        if (identity(self.path.stat()) != root_identity or identity(self.lock.stat()) != lock_identity
                or version(owner_path.stat()) != owner_version or read_regular(owner_path) != owner_bytes):
            raise Rejected("mutex changed before publication", "mutex_uncertain", True)

    def validate(self, state):
        if not isinstance(state, dict) or set(state) != {"schema", "revision", "sessions", "releases", "messages"}:
            raise Rejected("unknown or incomplete board format", "corrupt")
        if state["schema"] != 1 or type(state["revision"]) is not int or state["revision"] < 0:
            raise Rejected("unsupported schema or revision", "corrupt")
        if not isinstance(state["sessions"], dict) or len(state["sessions"]) > MAX_RECORDS:
            raise Rejected("session inventory exceeds supported capacity", "capacity")
        held = []
        required = {"id", "checkout", "host", "state", "task", "approach", "baseline", "dependencies", "claims",
                    "created", "updated", "progress_at", "inbox_at", "next_check", "next_action", "progress",
                    "checks", "blockers", "jobs", "closed", "delete_after", "disposition"}
        for key, session in state["sessions"].items():
            if not isinstance(session, dict) or set(session) != required or session["id"] != identifier(key):
                raise Rejected("unknown or incomplete session: " + key, "corrupt")
            if session["state"] not in TERMINAL | {"active", "waiting", "paused"}:
                raise Rejected("unknown session state", "corrupt")
            for field in ("task", "approach", "baseline", "next_action", "progress", "disposition", "checkout", "host"):
                text_field(session[field], field)
            for field in ("dependencies", "checks", "blockers", "jobs", "claims"):
                if not isinstance(session[field], list) or len(session[field]) > 128:
                    raise Rejected("invalid bounded list: " + field, "corrupt")
            for field in ("dependencies", "checks", "blockers"):
                for value in session[field]:
                    text_field(value, field)
            created, updated = timestamp(session["created"]), timestamp(session["updated"])
            if updated < created:
                raise Rejected("publication precedes creation", "corrupt")
            for field in ("progress_at", "inbox_at"):
                if session[field] is not None and not created <= timestamp(session[field]) <= updated:
                    raise Rejected("event time outside session lifetime", "corrupt")
            timestamp(session["next_check"])
            for claim in session["claims"]:
                if self.scope(claim) != claim:
                    raise Rejected("noncanonical recorded claim", "corrupt")
                if any(other != key and overlap(claim, scope) for other, scope in held):
                    raise Rejected("conflicting published claims", "corrupt")
                held.append((key, claim))
            job_ids = set()
            for job in session["jobs"]:
                if (not isinstance(job, dict) or set(job) != {"id", "scopes", "launched", "identity", "command"}
                        or identifier(job["id"]) in job_ids):
                    raise Rejected("unknown or duplicate job metadata", "corrupt")
                job_ids.add(job["id"])
                timestamp(job["launched"])
                text_field(job["identity"], "job identity")
                text_field(job["command"], "job command")
                for scope in self.scopes(job["scopes"]):
                    if not any(covered(claim, scope) for claim in session["claims"]):
                        raise Rejected("registered job lacks owned scope", "corrupt")
            if session["state"] in TERMINAL:
                if session["claims"] or session["jobs"] or session["closed"] is None:
                    raise Rejected("terminal session still owns scope or jobs", "corrupt")
                if timestamp(session["delete_after"]) != timestamp(session["closed"]) + timedelta(days=30):
                    raise Rejected("invalid retention deadline", "corrupt")
                if not created <= timestamp(session["closed"]) <= updated:
                    raise Rejected("closure time outside session lifetime", "corrupt")
            elif session["closed"] is not None or session["delete_after"] is not None:
                raise Rejected("live session has closure metadata", "corrupt")
        for collection in ("releases", "messages"):
            if not isinstance(state[collection], list) or len(state[collection]) > 4096:
                raise Rejected(collection + " exceeds supported capacity", "capacity")
        seen, pending_scopes = set(), []
        for release in state["releases"]:
            if (not isinstance(release, dict) or set(release) != {"id", "from", "to", "scopes", "disposition", "released", "accepted"}
                    or release["id"] in seen or release["from"] not in state["sessions"]
                    or (release["to"] is not None and release["to"] not in state["sessions"])):
                raise Rejected("invalid release inventory", "corrupt")
            identifier(release["id"])
            seen.add(release["id"])
            text_field(release["disposition"], "release disposition")
            released_at = timestamp(release["released"])
            if not isinstance(release["scopes"], list) or not 1 <= len(release["scopes"]) <= 128:
                raise Rejected("missing complete release scope inventory", "corrupt")
            released_scopes = set()
            # Prior scopes preserve identity even when a later change removes a path.
            for scope in release["scopes"]:
                if not isinstance(scope, dict) or set(scope) != {"kind", "value"} or scope["kind"] not in {"file", "directory", "resource"}:
                    raise Rejected("incomplete prior scope inventory", "corrupt")
                text_field(scope["value"], "released scope")
                key = scope["kind"], scope["value"]
                if key in released_scopes:
                    raise Rejected("duplicate released scope", "corrupt")
                released_scopes.add(key)
                if scope["kind"] == "resource":
                    self.scope(scope)
                else:
                    path = Path(scope["value"])
                    portable_components(path)
                    if not path.is_absolute() or str(Path(os.path.abspath(path))) != scope["value"] or ".." in path.parts:
                        raise Rejected("prior path must retain its canonical absolute spelling", "corrupt")
            if release["accepted"] is not None:
                if release["to"] is None or timestamp(release["accepted"]) < released_at:
                    raise Rejected("invalid acceptance time or recipient", "corrupt")
            elif release["to"] is not None:
                if (release["from"] == release["to"]
                        or state["sessions"][release["from"]]["state"] in TERMINAL
                        or state["sessions"][release["to"]]["state"] in TERMINAL):
                    raise Rejected("pending transfer needs two distinct live participants", "corrupt")
                if any(overlap(scope, claim) for scope in release["scopes"] for _, claim in held):
                    raise Rejected("pending transfer overlaps a published claim", "corrupt")
                if any(overlap(scope, prior) for scope in release["scopes"] for prior in pending_scopes):
                    raise Rejected("pending transfers overlap each other", "corrupt")
                pending_scopes.extend(release["scopes"])
        seen = set()
        for message in state["messages"]:
            if (not isinstance(message, dict) or set(message) != {"id", "from", "to", "body", "sent", "processed"}
                    or message["id"] in seen or message["from"] not in state["sessions"]
                    or message["to"] not in state["sessions"]):
                raise Rejected("invalid message inventory", "corrupt")
            identifier(message["id"])
            seen.add(message["id"])
            text_field(message["body"], "message")
            timestamp(message["sent"])
            if message["processed"] is not None:
                timestamp(message["processed"])
        return state

    def check_namespaces(self):
        for name in ("notes", "artifacts"):
            path = safe_path(self.path / name)
            if path.exists() and not path.is_dir():
                raise Rejected("board namespace must be an ordinary directory: " + name, "corrupt")

    def read(self):
        if not self.path.is_dir():
            raise Rejected("board is absent; use init only after agreeing its location")
        if (self.path / "protocol.json").exists():
            raise Rejected("board migrated to the record protocol; use agent_session.py", "migrated")
        # Windows MoveFileEx cannot replace an open destination, even when the
        # reader shares delete access. Serialize complete reads with publication;
        # close every state descriptor before releasing this brief mutex.
        if self.token is None:
            with self.mutex():
                return self.read()
        self.check_mutex()
        allowed = {"state.json", "registry.lock", "notes", "artifacts"}
        unknown = [p.name for p in self.path.iterdir() if p.name not in allowed]
        if unknown:
            raise Rejected("unknown board entries need review: " + repr(unknown), "corrupt")
        self.check_namespaces()
        return self.validate(decode(read_regular(self.state_path)))

    def save(self, state):
        self.check_mutex()
        self.validate(state)
        data = encoded(state)
        if len(data) > MAX_BYTES:
            raise Rejected("board capacity reached; perform reviewed retention maintenance", "capacity")
        temporary = self.lock / ("state-" + uuid.uuid4().hex + ".tmp")
        try:
            with temporary.open("xb") as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            self.check_mutex()
            os.replace(temporary, self.state_path)
            if read_regular(self.state_path) != data:
                raise OSError("saved bytes differ")
        except BaseException as error:
            # Keep an interrupted candidate for investigation; a leftover blocks cleanup.
            raise Rejected("state publication uncertain; inspect saved bytes", "publication_uncertain", True) from error

    def active(self, state, session_id):
        session = state["sessions"].get(identifier(session_id))
        if session is None or session["state"] in TERMINAL:
            raise Rejected("session absent or terminal; use a new ID")
        return session

    def revision(self, state, request):
        if type(request.get("revision")) is not int or request["revision"] != state["revision"]:
            raise Rejected("reviewed board revision differs; reread and replan", "stale")

    def check_free(self, state, session_id, scopes, accepted=None):
        for owner, session in state["sessions"].items():
            if owner != session_id and any(overlap(a, b) for a in scopes for b in session["claims"]):
                raise Rejected("scope held by " + owner, "conflict")
        for release in state["releases"]:
            if release["to"] is not None and release["accepted"] is None and release["id"] != accepted:
                if any(overlap(a, b) for a in scopes for b in release["scopes"]):
                    raise Rejected("pending handoff " + release["id"] + " requires accept or coordinated recovery", "conflict")

    def check_inputs(self, inputs):
        """Check exact reviewed regular-file bytes or explicit absence, without a lease."""
        if not isinstance(inputs, list) or len(inputs) > 128:
            raise Rejected("inputs must be a bounded list")
        for entry in inputs:
            if not isinstance(entry, dict) or set(entry) != {"path", "sha256"}:
                raise Rejected("input needs path and sha256, or null for reviewed absence")
            scope = self.scope({"kind": "file", "value": entry["path"]})
            path = Path(scope["value"])
            expected = entry["sha256"]
            if expected is not None and (not isinstance(expected, str) or not re.fullmatch("[0-9a-f]{64}", expected)):
                raise Rejected("input digest must be a lowercase SHA-256 or null")
            try:
                actual = hashlib.sha256(read_regular(path)).hexdigest()
            except FileNotFoundError:
                actual = None
            if actual != expected:
                raise Rejected("reviewed input changed; reread and replan: " + str(path), "stale")

    def apply(self, operation, request):
        if not isinstance(request, dict):
            raise Rejected("request must be a JSON object")
        if operation == "init":
            self.path.mkdir(mode=0o700, exist_ok=True)
            with self.mutex():
                self.check_namespaces()
                if self.state_path.exists():
                    state = self.read()
                else:
                    unknown = [p.name for p in self.path.iterdir() if p.name not in {"registry.lock", "notes", "artifacts"}]
                    if unknown:
                        raise Rejected("initialization would hide unknown registry data", "corrupt")
                    state = {"schema": 1, "revision": 0, "sessions": {}, "releases": [], "messages": []}
                    self.save(state)
            return {"ok": True, "revision": state["revision"], "board": str(self.path)}
        if operation in {"status", "show", "inbox"}:
            state = self.read()
            if "revision" in request:
                self.revision(state, request)
            if operation == "show":
                return {"revision": state["revision"], "session": state["sessions"][identifier(request["id"])]}
            offset, limit = request.get("offset", 0), request.get("limit", 20)
            if type(offset) is not int or type(limit) is not int or offset < 0 or not 1 <= limit <= 50:
                raise Rejected("offset must be nonnegative and limit 1–50")
            if offset and "revision" not in request:
                raise Rejected("later pages require the first page revision", "stale")
            if operation == "inbox":
                identifier(request["id"])
                entries = [m for m in state["messages"] if m["to"] == request["id"]]
            else:
                entries = [{k: record[k] for k in ("id", "state", "updated", "next_check", "claims", "closed", "delete_after")}
                           for _, record in sorted(state["sessions"].items())]
                # Releases include closed predecessors and are paged as first-class entries.
                entries += [{"release": r} for r in state["releases"]]
            return {"revision": state["revision"], "total": len(entries), "offset": offset,
                    "next_offset": offset + limit if offset + limit < len(entries) else None,
                    "entries": entries[offset:offset + limit]}
        if operation == "run":
            return self.run(request)
        with self.mutex():
            state = self.read()
            self.revision(state, request)
            session_id = identifier(request["id"])
            at = now()
            if operation == "register":
                if session_id in state["sessions"]:
                    raise Rejected("session IDs are never reused")
                session = {"id": session_id, "checkout": str(self.root), "host": socket.gethostname(),
                           "state": "active", "task": request["task"], "approach": request["approach"],
                           "baseline": request["baseline"], "dependencies": request.get("dependencies", []),
                           "claims": [], "created": at, "updated": at, "progress_at": None, "inbox_at": None,
                           "next_check": request["next_check"], "next_action": request["next_action"],
                           "progress": "Registered; work has not started.", "checks": [], "blockers": [], "jobs": [],
                           "closed": None, "delete_after": None, "disposition": "No changes yet."}
                state["sessions"][session_id] = session
            else:
                session = self.active(state, session_id)
                if session["checkout"] != str(self.root):
                    raise Rejected("session belongs to a different checkout")
                if operation == "claim":
                    scopes = self.scopes(request["scopes"])
                    self.check_free(state, session_id, scopes)
                    self.check_inputs(request.get("inputs", []))
                    for value in scopes:
                        if value not in session["claims"]:
                            session["claims"].append(value)
                elif operation == "narrow":
                    parent = self.scope(request["parent"])
                    children = self.scopes(request["scopes"])
                    if (parent["kind"] != "directory" or parent not in session["claims"]
                            or any(not covered(parent, child) or child == parent for child in children)
                            or request.get("writers_stopped") is not True or session["jobs"]):
                        raise Rejected("narrow requires one held parent, contained scopes and stopped writers")
                    self.check_free(state, session_id, children)
                    session["claims"] = [scope for scope in session["claims"] if scope != parent]
                    session["claims"].extend(scope for scope in children if scope not in session["claims"])
                    state["releases"].append({"id": uuid.uuid4().hex, "from": session_id, "to": None,
                        "scopes": [parent], "disposition": text_field(request["disposition"], "disposition"),
                        "released": at, "accepted": None})
                elif operation in {"release", "handoff"}:
                    scopes = self.scopes(request["scopes"])
                    if request.get("writers_stopped") is not True or session["jobs"]:
                        raise Rejected("confirm every writer stopped; registered jobs still prevent release")
                    if any(scope not in session["claims"] for scope in scopes):
                        raise Rejected("release must name exact held scopes; narrow a parent before transfer")
                    recipient = identifier(request["to"]) if operation == "handoff" else None
                    if recipient is not None:
                        self.active(state, recipient)
                        if recipient == session_id:
                            raise Rejected("handoff must name another participant")
                    release = {"id": uuid.uuid4().hex, "from": session_id, "to": recipient, "scopes": scopes,
                               "disposition": text_field(request["disposition"], "disposition"), "released": at, "accepted": None}
                    state["releases"].append(release)
                    session["claims"] = [s for s in session["claims"] if s not in scopes]
                    session["disposition"] = release["disposition"]
                elif operation == "accept":
                    release = next((r for r in state["releases"] if r["id"] == request["release"]), None)
                    if release is None or release["to"] != session_id or release["accepted"] is not None:
                        raise Rejected("handoff is absent, consumed or addressed to another participant")
                    text_field(request["review"], "predecessor and input review")
                    scopes = self.scopes(release["scopes"])
                    self.check_free(state, session_id, scopes, accepted=release["id"])
                    self.check_inputs(request.get("inputs", []))
                    session["claims"].extend(s for s in scopes if s not in session["claims"])
                    release["accepted"] = at
                    state["messages"].append({"id": uuid.uuid4().hex, "from": session_id, "to": release["from"],
                        "body": "Acquired release " + release["id"] + "; review: " + request["review"], "sent": at, "processed": None})
                elif operation == "checkpoint":
                    allowed = {"state", "progress", "checks", "blockers", "next_action", "next_check", "dependencies", "disposition"}
                    for field in allowed:
                        if field not in request:
                            raise Rejected("checkpoint needs the complete current field: " + field)
                        session[field] = request[field]
                    if session["state"] in TERMINAL:
                        raise Rejected("use close for terminal state")
                    for field in ("progress_at", "inbox_at"):
                        if field in request:
                            if session[field] is not None and timestamp(request[field]) < timestamp(session[field]):
                                raise Rejected("event time cannot move backward")
                            session[field] = request[field]
                    for message_id in request.get("processed_messages", []):
                        message = next((m for m in state["messages"] if m["id"] == message_id and m["to"] == session_id), None)
                        if message is None:
                            raise Rejected("processed message is not in this inbox")
                        if request.get("inbox_at") is None:
                            raise Rejected("supply actual completed inbox processing time")
                        if message["processed"] is None:
                            message["processed"] = request["inbox_at"]
                elif operation == "message":
                    recipient = identifier(request["to"])
                    if recipient not in state["sessions"]:
                        raise Rejected("recipient is unknown")
                    message_id = identifier(request.get("message_id", uuid.uuid4().hex))
                    if any(m["id"] == message_id for m in state["messages"]):
                        raise Rejected("message ID already exists; immutable publication refuses replacement")
                    state["messages"].append({"id": message_id, "from": session_id, "to": recipient,
                        "body": text_field(request["body"], "body"), "sent": at, "processed": None})
                elif operation == "job":
                    job_id = identifier(request["job_id"])
                    action = request["action"]
                    if action == "start":
                        scopes = self.scopes(request["scopes"])
                        self.check_inputs(request.get("inputs", []))
                        if any(not any(covered(c, s) for c in session["claims"]) for s in scopes):
                            raise Rejected("job scope is not exactly covered by own claims")
                        if any(j["id"] == job_id for j in session["jobs"]):
                            raise Rejected("job already registered")
                        session["jobs"].append({"id": job_id, "scopes": scopes, "launched": at,
                                               "identity": request.get("identity", "launch pending; identity unavailable"),
                                               "command": text_field(request["command"], "command")})
                    elif action == "finish":
                        if request.get("writers_stopped") is not True or not any(j["id"] == job_id for j in session["jobs"]):
                            raise Rejected("finish requires a known job and verified stopped output/child writers")
                        session["jobs"] = [j for j in session["jobs"] if j["id"] != job_id]
                        session["checks"].append(text_field(request["result"], "job result"))
                    else:
                        raise Rejected("job action must be start or finish")
                elif operation == "close":
                    if session["claims"] or session["jobs"] or request.get("writers_stopped") is not True:
                        raise Rejected("release claims and reconcile all writers before closing")
                    if any(session_id in {r["from"], r["to"]} and r["to"] is not None and r["accepted"] is None for r in state["releases"]):
                        raise Rejected("pending handoff must be resolved before closure")
                    if request["state"] not in TERMINAL:
                        raise Rejected("close state must be done, failed or cancelled")
                    session.update(state=request["state"], closed=at,
                        delete_after=(timestamp(at) + timedelta(days=30)).isoformat(),
                        progress=text_field(request["result"], "result"), blockers=[],
                        next_action="Review retention eligibility after the recorded deadline.",
                        disposition=text_field(request["disposition"], "disposition"))
                else:
                    raise Rejected("unknown operation")
            session["updated"] = at
            state["revision"] += 1
            self.save(state)
            result = {"ok": True, "revision": state["revision"], "id": session_id, "claims": session["claims"]}
            if operation in {"release", "handoff"}:
                result["release"] = release["id"]
        # Returning a receipt only after cleanup prevents dependent actions after failed unlock.
        return result

    def run(self, request):
        """Run a synchronous foreground command; retain a job until explicit reconciliation.

        It intentionally does not infer descendant/output completion from parent exit.
        Never detach children. The participant must call job finish after inspecting them.
        """
        argv = request.get("argv")
        if not isinstance(argv, list) or not argv or any(not isinstance(x, str) for x in argv):
            raise Rejected("argv must be a nonempty string list; shell interpretation is not used")
        job_id = identifier(request.get("job_id", uuid.uuid4().hex))
        start = dict(request, job_id=job_id, action="start", command=repr(argv))
        receipt = self.apply("job", start)
        # No child starts if job publication or mutex cleanup fails.
        try:
            completed = subprocess.run(argv, cwd=self.root, check=False)
        except BaseException as error:
            raise Rejected("job launch/completion uncertain; reconcile recorded job " + job_id, "job_uncertain", True) from error
        return {"ok": completed.returncode == 0, "job_id": job_id, "exit_code": completed.returncode,
                "revision": receipt["revision"], "reconcile": "job remains registered until job finish confirms all writers stopped"}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=("init", "status", "show", "register", "claim", "narrow", "release", "checkpoint", "handoff", "accept", "message", "inbox", "job", "run", "close"))
    parser.add_argument("--root", default=str(Path(__file__).resolve().parents[1]))
    parser.add_argument("--board", help="explicit absolute shared board; initialize separately")
    parser.add_argument("--input", default="-", help="JSON object on stdin or a claimed request file")
    args = parser.parse_args(argv)
    completed = False
    try:
        raw = sys.stdin.buffer.read(MAX_BYTES + 1) if args.input == "-" else read_regular(Path(args.input).absolute())
        request = decode(raw or b"{}")
        result = Board(args.root, args.board).apply(args.operation, request)
        completed = True
        print(json.dumps(result, ensure_ascii=True), flush=True)
        return 0 if result.get("ok", True) else 1
    except (OSError, ValueError, KeyError, TypeError) as error:
        failure = (Rejected("receipt output failed; operation may already be committed", "output_uncertain", True)
                   if completed else error if isinstance(error, Rejected) else Rejected(str(error)))
        print(json.dumps(failure.result()), file=sys.stderr, flush=True)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
