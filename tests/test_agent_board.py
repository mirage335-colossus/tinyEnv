"""Failure, lifecycle and real-process tests for the cooperative coordination example."""
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

sys.dont_write_bytecode = True
TOOL = Path(__file__).resolve().parents[1] / "tools" / "agent_board.py"
SPEC = importlib.util.spec_from_file_location("foundation_agent_board", TOOL)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)
Board, Rejected = MODULE.Board, MODULE.Rejected


class RegularReadTests(unittest.TestCase):
    def test_distinct_path_and_descriptor_ctime_still_reads_and_detects_changes(self):
        from types import SimpleNamespace
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'record'
            path.write_bytes(b'content')
            original = os.fstat
            def changed(fd, delta):
                info = original(fd)
                values = {key: getattr(info, key) for key in
                          ('st_dev', 'st_ino', 'st_mode', 'st_nlink', 'st_size', 'st_mtime_ns', 'st_ctime_ns')}
                values['st_ctime_ns'] += delta
                return SimpleNamespace(**values)
            with mock.patch.object(MODULE, 'cross_version', lambda info: MODULE.version(info)[:-1]):
                with mock.patch.object(MODULE.os, 'fstat', side_effect=lambda fd: changed(fd, 100)):
                    self.assertEqual(MODULE.read_regular(path), b'content')
                deltas = iter((100, 200))
                with mock.patch.object(MODULE.os, 'fstat', side_effect=lambda fd: changed(fd, next(deltas))):
                    with self.assertRaisesRegex(Rejected, 'changed while reading'):
                        MODULE.read_regular(path)


class CoordinationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.board = Board(self.root)
        self.board.apply("init", {})
        self.register("alpha")
        self.register("beta")

    def revision(self):
        return self.board.read()["revision"]

    def call(self, operation, session="alpha", **values):
        return self.board.apply(operation, dict(id=session, revision=self.revision(), **values))

    def register(self, name):
        return self.call("register", name, task="Maintain a generic component.", approach="Inspect, edit, verify.",
                         baseline="Initial checkout inspected; no other edits.", next_action="Inspect claims.", next_check=MODULE.now())

    @staticmethod
    def scope(name, kind="file"):
        return {"kind": kind, "value": name}

    def claim(self, name="src/example.cpp", session="alpha", kind="file"):
        return self.call("claim", session, scopes=[self.scope(name, kind)])

    def release(self, name="src/example.cpp", session="alpha", kind="file"):
        return self.call("release", session, scopes=[self.scope(name, kind)], writers_stopped=True,
                         disposition="Current changes remain available for review.")

    def checkpoint(self, **values):
        request = dict(state="active", progress="Focused check complete.", checks=["focused: passed"], blockers=[],
                       next_action="Review the next change.", next_check=MODULE.now(), dependencies=[],
                       disposition="Changes remain uncommitted.")
        request.update(values)
        return self.call("checkpoint", **request)

    def test_exact_claim_conflict_and_component_siblings(self):
        self.claim("src/item")
        self.claim("src/items", "beta")
        with self.assertRaisesRegex(Rejected, "scope held"):
            self.claim("src/item", "beta")

    def test_directory_claim_covers_future_children(self):
        self.claim("src", kind="directory")
        with self.assertRaises(Rejected):
            self.claim("src/new.cpp", "beta")
        self.claim("src2/new.cpp", "beta")

    def test_existing_claim_kind_mismatch(self):
        (self.root / "src").mkdir()
        with self.assertRaisesRegex(Rejected, "claim kind"):
            self.claim("src")
        (self.root / "text").write_text("value")
        with self.assertRaisesRegex(Rejected, "claim kind"):
            self.claim("text", kind="directory")

    def test_absent_claim_kind_rechecked_after_materialization(self):
        self.claim("future")
        (self.root / "future").mkdir()
        with self.assertRaisesRegex(Rejected, "claim kind"):
            self.board.apply("status", {})
        with self.assertRaises(Rejected):
            self.board.apply("claim", {"id": "beta", "revision": 3, "scopes": [self.scope("future/child")]})

    def test_case_and_unicode_conflicts_do_not_grant_authority(self):
        self.claim("Data.txt")
        with self.assertRaises(Rejected):
            self.claim("data.txt", "beta")
        with self.assertRaisesRegex(Rejected, "not exactly covered"):
            self.call("job", action="start", job_id="wrong-case", command="example", scopes=[self.scope("data.txt")])
        self.claim("caf\u00e9")
        with self.assertRaises(Rejected):
            self.claim("cafe\u0301", "beta")

    def test_traversal_and_registry_claims_rejected(self):
        for name in ("../outside", ".agent-work", ".agent-work/state.json", ".agent-work/notes", "."):
            with self.subTest(name=name), self.assertRaises(Rejected):
                self.claim(name, kind="directory")
        self.claim(".agent-work/notes/alpha", kind="directory")

    def test_symlink_and_hardlink_aliases_rejected(self):
        target = self.root / "target"
        target.write_text("value")
        try:
            (self.root / "alias").symlink_to(target)
            os.link(target, self.root / "hard")
        except OSError:
            self.skipTest("filesystem or user cannot create link fixtures")
        for name in ("alias", "target", "hard"):
            with self.subTest(name=name), self.assertRaises(Rejected):
                self.claim(name)

    def test_nonportable_path_aliases_and_device_names_rejected(self):
        for name in ("src/file.", "src/file ", "src/CON.txt", "src/file:stream", "src/LPT1", "src/a?b", "src/COM\u00b9.txt"):
            with self.subTest(name=name), self.assertRaisesRegex(Rejected, "not portable"):
                self.claim(name)

    def test_resource_lock_crosses_checkout_boundaries(self):
        self.claim("git:shared", kind="resource")
        other_root = self.root / "other-checkout"
        other_root.mkdir()
        other = Board(other_root, self.board.path)
        result = other.apply("register", dict(id="gamma", revision=self.revision(), task="Inspect.", approach="Review.",
            baseline="Independent checkout.", next_check=MODULE.now(), next_action="Claim resource."))
        with self.assertRaisesRegex(Rejected, "scope held"):
            other.apply("claim", dict(id="gamma", revision=result["revision"], scopes=[self.scope("git:shared", "resource")]))

    def test_stale_review_does_not_overwrite_current_record(self):
        revision = self.revision()
        self.claim()
        before = self.board.state_path.read_bytes()
        with self.assertRaises(Rejected) as raised:
            self.board.apply("claim", dict(id="beta", revision=revision, scopes=[self.scope("other")]))
        self.assertEqual(raised.exception.code, "stale")
        self.assertEqual(before, self.board.state_path.read_bytes())

    def test_unknown_board_entry_and_unknown_state_field_fail_closed(self):
        unknown = self.board.path / "unexpected.json"
        unknown.write_text("{}")
        with self.assertRaisesRegex(Rejected, "unknown board entries"):
            self.board.apply("status", {})
        unknown.unlink()
        state = self.board.read()
        state["unrecognized"] = True
        self.board.state_path.write_text(json.dumps(state))
        with self.assertRaisesRegex(Rejected, "unknown or incomplete"):
            self.board.apply("status", {})

    def test_duplicate_json_keys_and_truncated_records_fail_closed(self):
        for content in (b'{"schema":1,"schema":1}', b'{"schema":'):
            self.board.state_path.write_bytes(content)
            with self.assertRaises(Rejected):
                self.board.apply("status", {})

    def test_closed_record_with_retained_claim_is_never_filtered_out(self):
        self.claim()
        state = self.board.read()
        state["sessions"]["alpha"]["state"] = "done"
        self.board.state_path.write_text(json.dumps(state))
        with self.assertRaisesRegex(Rejected, "terminal session still owns"):
            self.board.apply("status", {})

    def test_status_pages_have_whole_claims_and_bound_revision(self):
        self.claim("a")
        self.claim("b")
        first = self.board.apply("status", {"limit": 1})
        self.assertEqual(len(first["entries"][0]["claims"]), 2)
        self.assertEqual(first["next_offset"], 1)
        second = self.board.apply("status", {"offset": 1, "limit": 1, "revision": first["revision"]})
        self.assertEqual(second["entries"][0]["id"], "beta")
        self.claim("c")
        with self.assertRaises(Rejected):
            self.board.apply("status", {"offset": 1, "revision": first["revision"]})

    def test_explicit_release_and_acquisition_ack_are_atomic(self):
        self.claim()
        transfer = self.call("handoff", scopes=[self.scope("src/example.cpp")], to="beta", writers_stopped=True,
                             disposition="Reviewed content remains uncommitted; no output writers remain.")
        self.assertEqual(transfer["claims"], [])
        with self.assertRaises(Rejected):
            self.claim()
        accepted = self.call("accept", "beta", release=transfer["release"], review="Read predecessor and current file.")
        self.assertEqual(len(accepted["claims"]), 1)
        state = self.board.read()
        self.assertIsNotNone(state["releases"][-1]["accepted"])
        self.assertIn(transfer["release"], state["messages"][-1]["body"])
        with self.assertRaises(Rejected):
            self.call("accept", "beta", release=transfer["release"], review="Duplicate attempt.")

    def test_closed_predecessor_release_is_discoverable_when_bytes_unchanged(self):
        self.claim()
        release = self.release()
        self.call("close", state="done", writers_stopped=True, result="Complete.", disposition="File unchanged.")
        entries = self.board.apply("status", {"limit": 50})["entries"]
        self.assertEqual(entries[-1]["release"]["id"], release["release"])
        self.claim(session="beta")
        self.assertEqual(len(self.board.read()["releases"]), 1)

    def test_parent_claim_cannot_be_released_as_child(self):
        self.claim("src", kind="directory")
        with self.assertRaisesRegex(Rejected, "exact held scopes"):
            self.release("src/example.cpp")

    def test_narrow_parent_atomically_then_handoff_one_child(self):
        self.claim("src", kind="directory")
        self.call("narrow", parent=self.scope("src", "directory"),
                  scopes=[self.scope("src/a.cpp"), self.scope("src/b.cpp")], writers_stopped=True,
                  disposition="Only two individual files still need changes.")
        self.call("handoff", scopes=[self.scope("src/a.cpp")], to="beta", writers_stopped=True,
                  disposition="First file is ready for independent review.")
        self.assertEqual(self.board.read()["sessions"]["alpha"]["claims"],
                         [self.scope(str(self.root / "src/b.cpp"))])

    def test_stale_and_materialized_input_prevents_claim_and_job(self):
        source = self.root / "input.txt"
        source.write_text("first")
        digest = MODULE.hashlib.sha256(source.read_bytes()).hexdigest()
        source.write_text("second")
        with self.assertRaisesRegex(Rejected, "reviewed input changed"):
            self.call("claim", scopes=[self.scope("out")], inputs=[{"path": "input.txt", "sha256": digest}])
        with self.assertRaises(Rejected):
            self.call("claim", scopes=[self.scope("out")], inputs=[{"path": "input.txt", "sha256": None}])
        self.assertFalse(self.board.read()["sessions"]["alpha"]["claims"])
        self.claim("out")
        with self.assertRaises(Rejected):
            self.call("job", action="start", job_id="stale", scopes=[self.scope("out")], command="example",
                      inputs=[{"path": "input.txt", "sha256": digest}])

    def test_release_requires_stopped_writers(self):
        self.claim()
        with self.assertRaises(Rejected):
            self.call("release", scopes=[self.scope("src/example.cpp")], disposition="Pending output.")
        self.assertEqual(len(self.board.read()["sessions"]["alpha"]["claims"]), 1)

    def test_message_no_replace_and_completed_inbox_time(self):
        self.call("message", "beta", to="alpha", body="Please review shared file.", message_id="request-1")
        with self.assertRaisesRegex(Rejected, "already exists"):
            self.call("message", "beta", to="alpha", body="Different content.", message_id="request-1")
        inbox = self.board.apply("inbox", {"id": "alpha"})
        self.assertIsNone(inbox["entries"][0]["processed"])
        processed = MODULE.now()
        self.checkpoint(processed_messages=["request-1"], inbox_at=processed)
        self.assertEqual(self.board.apply("inbox", {"id": "alpha"})["entries"][0]["processed"], processed)
        self.checkpoint()
        self.assertEqual(self.board.read()["sessions"]["alpha"]["inbox_at"], processed)

    def test_checkpoint_does_not_invent_progress_or_change_claims(self):
        self.claim()
        before = self.board.read()["sessions"]["alpha"]
        self.checkpoint()
        after = self.board.read()["sessions"]["alpha"]
        self.assertEqual(before["claims"], after["claims"])
        self.assertIsNone(after["progress_at"])
        with self.assertRaises(Rejected):
            self.checkpoint(progress_at="2999-01-01T00:00:00+00:00")

    def test_busy_empty_or_owned_lock_never_gets_stolen(self):
        self.board.lock.mkdir()
        with self.assertRaises(Rejected) as raised:
            self.claim()
        self.assertEqual(raised.exception.code, "busy")
        self.assertTrue(self.board.lock.is_dir())
        self.board.lock.rmdir()
        with self.board.mutex():
            with self.assertRaises(Rejected):
                with self.board.mutex():
                    self.fail("mutex reentered")

    def test_transient_windows_mkdir_denial_never_grants_ownership_before_creation(self):
        denied = PermissionError("injected Windows access denial")
        denied.winerror = 5
        original = Path.mkdir
        attempts = []
        before = self.board.state_path.read_bytes()
        def create(path, *args, **kwargs):
            if path == self.board.lock:
                self.assertIsNone(self.board.token)
                attempts.append(path)
                if len(attempts) == 1:
                    raise denied
            return original(path, *args, **kwargs)
        def wait(delay):
            self.assertIsNone(self.board.token)
            self.assertFalse(self.board.lock.exists())
            self.assertEqual(before, self.board.state_path.read_bytes())
        with mock.patch.object(Path, "mkdir", create), mock.patch.object(MODULE.time, "sleep", side_effect=wait) as sleep:
            with self.board.mutex():
                self.assertEqual(len(attempts), 2)
                self.assertIsNotNone(self.board.token)
                self.board.check_mutex()
        sleep.assert_called_once_with(.005)
        self.assertEqual(before, self.board.state_path.read_bytes())
        self.assertFalse(self.board.lock.exists())

    def test_persistent_windows_mkdir_denial_is_bounded_and_preserves_original_error(self):
        errors = [PermissionError("denied attempt " + str(i)) for i in range(7)]
        for error in errors:
            error.winerror = 5
        before = self.board.state_path.read_bytes()
        with mock.patch.object(Path, "mkdir", side_effect=errors) as create, \
                mock.patch.object(MODULE.time, "sleep") as sleep:
            with self.assertRaises(PermissionError) as caught:
                with self.board.mutex():
                    self.fail("denied acquisition entered the body")
        self.assertIs(caught.exception, errors[0])
        self.assertEqual(create.call_count, 7)
        self.assertTrue(all(call.args == () and call.kwargs == {"mode": 0o700} for call in create.call_args_list))
        self.assertEqual([call.args[0] for call in sleep.call_args_list], [.005, .01, .02, .04, .08, .16])
        self.assertIsNone(self.board.token)
        self.assertFalse(self.board.lock.exists())
        self.assertEqual(before, self.board.state_path.read_bytes())

    def test_other_mkdir_failures_are_immediate_and_never_reclassified(self):
        denied = PermissionError("ordinary access denial")
        other = PermissionError("different Windows failure"); other.winerror = 32
        for error in (denied, other, OSError("unknown filesystem failure")):
            with self.subTest(error=error), mock.patch.object(Path, "mkdir", side_effect=error) as create, \
                    mock.patch.object(MODULE.time, "sleep") as sleep:
                with self.assertRaises(type(error)) as caught:
                    with self.board.mutex():
                        self.fail("failed acquisition entered the body")
                self.assertIs(caught.exception, error)
                self.assertEqual(create.call_count, 1)
                sleep.assert_not_called()
                self.assertIsNone(self.board.token)
                self.assertFalse(self.board.lock.exists())

    def test_windows_mkdir_retry_cannot_steal_a_subsequently_occupied_lock(self):
        denied = PermissionError("injected Windows access denial"); denied.winerror = 5
        original = Path.mkdir
        attempts = []
        def create(path, *args, **kwargs):
            if path == self.board.lock:
                attempts.append(path)
                if len(attempts) == 1:
                    original(path, *args, **kwargs)
                    (path / "foreign").write_bytes(b"preserve")
                    raise denied
            return original(path, *args, **kwargs)
        with mock.patch.object(Path, "mkdir", create), mock.patch.object(MODULE.time, "sleep") as sleep:
            with self.assertRaises(Rejected) as caught:
                with self.board.mutex():
                    self.fail("occupied acquisition entered the body")
        self.assertEqual(caught.exception.code, "busy")
        self.assertFalse(caught.exception.uncertain)
        self.assertEqual(len(attempts), 2); sleep.assert_called_once_with(.005)
        self.assertIsNone(self.board.token)
        self.assertEqual((self.board.lock / "foreign").read_bytes(), b"preserve")
        self.assertEqual([p.name for p in self.board.lock.iterdir()], ["foreign"])

    @unittest.skipUnless(os.name == "nt", "Native Windows delete-pending directory semantics")
    def test_windows_delete_pending_mutex_requires_new_exclusive_creation(self):
        import ctypes
        from ctypes import wintypes
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                                      ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
        kernel.CreateFileW.restype = wintypes.HANDLE
        kernel.SetFileInformationByHandle.argtypes = [wintypes.HANDLE, ctypes.c_int,
                                                      ctypes.c_void_p, wintypes.DWORD]
        kernel.SetFileInformationByHandle.restype = wintypes.BOOL
        kernel.GetFileInformationByHandleEx.argtypes = [wintypes.HANDLE, ctypes.c_int,
                                                       ctypes.c_void_p, wintypes.DWORD]
        kernel.GetFileInformationByHandleEx.restype = wintypes.BOOL
        class FileDispositionInfo(ctypes.Structure):
            _fields_ = [("DeleteFile", ctypes.c_ubyte)]  # Win32 BOOLEAN, not BOOL.
        class FileStandardInfo(ctypes.Structure):
            _fields_ = [("AllocationSize", ctypes.c_longlong), ("EndOfFile", ctypes.c_longlong),
                        ("NumberOfLinks", wintypes.DWORD), ("DeletePending", ctypes.c_ubyte),
                        ("Directory", ctypes.c_ubyte)]
        self.assertEqual(ctypes.sizeof(FileDispositionInfo), 1)
        self.assertEqual(ctypes.sizeof(FileStandardInfo), 24)
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel.CloseHandle.restype = wintypes.BOOL
        before = self.board.state_path.read_bytes()
        self.board.lock.mkdir(mode=0o700)
        # DELETE access, read/write/delete sharing, OPEN_EXISTING and
        # BACKUP_SEMANTICS permit classic disposition on this owned directory.
        handle = kernel.CreateFileW(str(self.board.lock), 0x10000, 7, None, 3, 0x02000000, None)
        self.assertNotEqual(handle, ctypes.c_void_p(-1).value, ctypes.get_last_error())
        try:
            # RemoveDirectoryW can unlink the name while a handle remains open.
            # FileDispositionInfo (4) explicitly requests classic deletion on close.
            # https://learn.microsoft.com/windows/win32/api/fileapi/nf-fileapi-setfileinformationbyhandle
            disposition = FileDispositionInfo(1)
            self.assertTrue(kernel.SetFileInformationByHandle(
                handle, 4, ctypes.byref(disposition), ctypes.sizeof(disposition)), ctypes.get_last_error())
            standard = FileStandardInfo()
            self.assertTrue(kernel.GetFileInformationByHandleEx(
                handle, 1, ctypes.byref(standard), ctypes.sizeof(standard)), ctypes.get_last_error())
            self.assertTrue(standard.Directory)
            self.assertTrue(standard.DeletePending)
            with self.assertRaises(PermissionError) as caught:
                self.board.lock.mkdir(mode=0o700)
            self.assertEqual(caught.exception.winerror, 5)
            def release_handle(delay):
                nonlocal handle
                self.assertIsNone(self.board.token)
                self.assertEqual(before, self.board.state_path.read_bytes())
                self.assertTrue(kernel.CloseHandle(handle), ctypes.get_last_error())
                handle = None
            with mock.patch.object(MODULE.time, "sleep", side_effect=release_handle) as sleep:
                with self.board.mutex():
                    self.assertIsNone(handle)
                    self.assertIsNotNone(self.board.token)
                    self.board.check_mutex()
            sleep.assert_called_once_with(.005)
        finally:
            if handle is not None:
                self.assertTrue(kernel.CloseHandle(handle), ctypes.get_last_error())
        self.assertFalse(self.board.lock.exists())
        self.assertEqual(before, self.board.state_path.read_bytes())

    def test_cleanup_failure_is_uncertain_even_after_successful_publication(self):
        original_rmdir = Path.rmdir
        def deny_lock(path):
            if path == self.board.lock:
                raise OSError("injected cleanup failure")
            return original_rmdir(path)
        revision = self.revision()
        with mock.patch.object(Path, "rmdir", deny_lock), self.assertRaises(Rejected) as raised:
            self.board.apply('claim', dict(id='alpha', revision=revision, scopes=[self.scope('item')]))
        self.assertTrue(raised.exception.uncertain)
        self.assertTrue(self.board.lock.exists())
        with self.assertRaises(Rejected) as blocked:
            self.board.read()
        self.assertEqual(blocked.exception.code, 'busy')
        # Diagnostic inspection of saved bytes does not steal the retained mutex
        # or establish authority for another operation.
        saved = self.board.validate(MODULE.decode(MODULE.read_regular(self.board.state_path)))
        self.assertEqual(len(saved['sessions']['alpha']['claims']), 1)

    def test_owner_replacement_with_same_bytes_blocks_cleanup(self):
        with self.assertRaises(Rejected) as raised:
            with self.board.mutex():
                path = self.board.lock / "owner.json"
                data = path.read_bytes()
                replacement = self.board.lock / "replacement"
                replacement.write_bytes(data)
                os.replace(replacement, path)
        self.assertTrue(raised.exception.uncertain)
        self.assertTrue(self.board.lock.exists())

    def test_publication_failure_blocks_dependent_command(self):
        self.claim("build/alpha", kind="directory")
        marker = self.root / "should-not-exist"
        with mock.patch.object(MODULE.os, "replace", side_effect=OSError("injected publication failure")), self.assertRaises(Rejected):
            self.call("run", scopes=[self.scope("build/alpha", "directory")], job_id="blocked", argv=[sys.executable, "-c", "from pathlib import Path; Path('should-not-exist').write_text('bad')"])
        self.assertFalse(marker.exists())
        self.assertTrue(self.board.lock.exists())

    def test_unclaimed_command_never_launches(self):
        marker = self.root / "should-not-exist"
        with self.assertRaises(Rejected):
            self.call("run", scopes=[self.scope("build/alpha", "directory")], argv=[sys.executable, "-c", "from pathlib import Path; Path('should-not-exist').write_text('bad')"])
        self.assertFalse(marker.exists())

    def test_foreground_parent_exit_does_not_release_job(self):
        self.claim("build/alpha", kind="directory")
        result = self.call("run", scopes=[self.scope("build/alpha", "directory")], job_id="check", argv=[sys.executable, "-c", "pass"])
        self.assertEqual(result["exit_code"], 0)
        with self.assertRaisesRegex(Rejected, "registered jobs"):
            self.release("build/alpha", kind="directory")
        self.call("job", job_id="check", action="finish", writers_stopped=True, result="Parent, children and output writers checked; passed.")
        self.release("build/alpha", kind="directory")

    def test_command_failure_remains_registered_and_is_reported(self):
        self.claim("build/alpha", kind="directory")
        result = self.call("run", scopes=[self.scope("build/alpha", "directory")], job_id="failed-check", argv=[sys.executable, "-c", "raise SystemExit(7)"])
        self.assertFalse(result["ok"])
        self.assertEqual(result["exit_code"], 7)
        self.assertEqual(self.board.read()["sessions"]["alpha"]["jobs"][0]["id"], "failed-check")

    def test_terminal_ids_never_reopen_and_closure_has_retention(self):
        self.call("close", state="done", writers_stopped=True, result="Complete.", disposition="No changes.")
        state = self.board.read()["sessions"]["alpha"]
        self.assertEqual(MODULE.timestamp(state["delete_after"]) - MODULE.timestamp(state["closed"]), MODULE.timedelta(days=30))
        with self.assertRaises(Rejected):
            self.register("alpha")
        with self.assertRaises(Rejected):
            self.claim()

    def test_pending_handoff_prevents_sender_closure(self):
        self.claim()
        self.call("handoff", scopes=[self.scope("src/example.cpp")], to="beta", writers_stopped=True, disposition="Ready.")
        with self.assertRaisesRegex(Rejected, "pending handoff"):
            self.call("close", state="done", writers_stopped=True, result="Complete.", disposition="No changes.")
        with self.assertRaisesRegex(Rejected, "pending handoff"):
            self.call("close", "beta", state="done", writers_stopped=True, result="Complete.", disposition="No changes.")

    def test_invalid_pending_transfer_and_prior_scopes_fail_closed(self):
        self.claim()
        self.call("handoff", scopes=[self.scope("src/example.cpp")], to="beta", writers_stopped=True, disposition="Ready.")
        original = self.board.state_path.read_bytes()
        state = self.board.read()
        state["releases"][0]["scopes"][0]["value"] = "relative/path"
        self.board.state_path.write_bytes(MODULE.encoded(state))
        with self.assertRaisesRegex(Rejected, "canonical absolute"):
            self.board.read()
        self.board.state_path.write_bytes(original)
        state = self.board.read()
        state["sessions"]["alpha"]["claims"] = state["releases"][0]["scopes"]
        self.board.state_path.write_bytes(MODULE.encoded(state))
        with self.assertRaisesRegex(Rejected, "pending transfer overlaps"):
            self.board.read()
        self.board.state_path.write_bytes(original)
        state = self.board.read()
        duplicate = dict(state["releases"][0], id="duplicate-transfer")
        state["releases"].append(duplicate)
        self.board.state_path.write_bytes(MODULE.encoded(state))
        with self.assertRaisesRegex(Rejected, "pending transfers overlap"):
            self.board.read()

    def test_terminal_closure_cannot_precede_creation(self):
        self.call("close", state="done", writers_stopped=True, result="Complete.", disposition="No changes.")
        state = self.board.read()
        session = state["sessions"]["alpha"]
        early = MODULE.timestamp(session["created"]) - MODULE.timedelta(days=1)
        session["closed"] = early.isoformat()
        session["delete_after"] = (early + MODULE.timedelta(days=30)).isoformat()
        self.board.state_path.write_bytes(MODULE.encoded(state))
        with self.assertRaisesRegex(Rejected, "closure time outside"):
            self.board.read()

    def test_board_namespaces_must_be_ordinary_directories(self):
        notes = self.board.path / "notes"
        notes.write_text("wrong kind")
        with self.assertRaisesRegex(Rejected, "ordinary directory"):
            self.board.read()
        notes.unlink()
        target = self.root / "elsewhere"
        target.mkdir()
        try:
            notes.symlink_to(target, target_is_directory=True)
        except OSError:
            self.skipTest("filesystem or user cannot create link fixture")
        with self.assertRaises(Rejected):
            self.board.read()

    def test_initialization_rejects_invalid_namespace_before_saving_state(self):
        self.board.state_path.unlink()
        (self.board.path / "notes").write_text("not a directory")
        with self.assertRaisesRegex(Rejected, "ordinary directory"):
            self.board.apply("init", {})
        self.assertFalse(self.board.state_path.exists())
        self.assertFalse(self.board.lock.exists())

    def test_independent_cli_processes_cannot_both_claim_one_file(self):
        request_revision = self.revision()
        processes = []
        for session in ("alpha", "beta"):
            process = subprocess.Popen([sys.executable, "-B", str(TOOL), "claim", "--root", str(self.root)],
                                       stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            process.stdin.write(json.dumps(dict(id=session, revision=request_revision, scopes=[self.scope("shared.txt")])).encode())
            process.stdin.close()
            process.stdin = None
            processes.append(process)
        results = [process.communicate(timeout=15) for process in processes]
        self.assertEqual(sum(process.returncode == 0 for process in processes), 1, results)
        state = self.board.read()
        self.assertEqual(sum(bool(s["claims"]) for s in state["sessions"].values()), 1)

    def test_open_state_reader_excludes_writer_until_its_descriptor_is_closed(self):
        before = self.board.state_path.read_bytes()
        revision = self.revision()
        script = r'''
import importlib.util, sys
spec = importlib.util.spec_from_file_location('board', sys.argv[1])
module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
board = module.Board(sys.argv[2]); original = module.read_regular
def held_read(path):
    if path == board.state_path:
        # Keep a real descriptor open across the competing writer's attempt.
        with path.open('rb') as stream:
            print('state-open', flush=True)
            if sys.stdin.readline().strip() != 'continue': raise RuntimeError('gate lost')
            return original(path)
    return original(path)
module.read_regular = held_read
print(board.read()['revision'], flush=True)
'''
        process = subprocess.Popen([sys.executable, '-B', '-c', script, str(TOOL), str(self.root)],
                                   stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        try:
            self.assertEqual(process.stdout.readline().strip(), 'state-open')
            with self.assertRaises(Rejected) as raised:
                self.board.apply('claim', dict(id='alpha', revision=revision, scopes=[self.scope('item')]))
            self.assertEqual(raised.exception.code, 'busy')
            self.assertFalse(raised.exception.uncertain)
            self.assertEqual(self.board.state_path.read_bytes(), before)
            stdout, stderr = process.communicate('continue\n', timeout=15)
            self.assertEqual(process.returncode, 0, stderr)
            self.assertEqual(int(stdout.strip()), revision)
            self.assertFalse(self.board.lock.exists())
            self.claim('item')
            self.assertEqual(len(self.board.read()['sessions']['alpha']['claims']), 1)
        finally:
            if process.poll() is None:
                process.kill(); process.wait(timeout=5)

    def test_shared_instance_cannot_borrow_another_threads_mutex(self):
        from concurrent.futures import ThreadPoolExecutor
        before = self.board.state_path.read_bytes()
        with self.board.mutex(), ThreadPoolExecutor(max_workers=1) as executor:
            for operation in (self.board.read, self.board.check_mutex):
                with self.assertRaises(Rejected) as raised:
                    executor.submit(operation).result(timeout=5)
                self.assertEqual(raised.exception.code, 'busy')
                self.assertFalse(raised.exception.uncertain)
            self.assertIsInstance(self.board.read()['revision'], int)
        self.assertEqual(self.board.state_path.read_bytes(), before)
        self.assertFalse(self.board.lock.exists())

    def test_read_reuses_owned_mutex_and_does_not_change_revision(self):
        before = self.board.state_path.read_bytes()
        with self.board.mutex():
            owner = self.board.token
            self.assertIsInstance(self.board.read()['revision'], int)
            self.assertEqual(self.board.token, owner)
            with self.assertRaises(Rejected) as raised:
                Board(self.root).read()
            self.assertEqual(raised.exception.code, 'busy')
        self.assertEqual(self.board.state_path.read_bytes(), before)
        self.assertFalse(self.board.lock.exists())

    def test_eight_independent_writers_preserve_every_contribution(self):
        names = ["worker-" + str(index) for index in range(8)]
        for name in names:
            self.register(name)
        output = self.root / "shared-output"
        output.mkdir()
        (output / "result.txt").write_text("")
        script = r'''
import importlib.util, os, pathlib, random, sys, time
spec = importlib.util.spec_from_file_location('board', sys.argv[1])
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
root, name = pathlib.Path(sys.argv[2]), sys.argv[3]
board = module.Board(root)
scope = {'kind': 'directory', 'value': 'shared-output'}
def transact(operation, **request):
    for attempt in range(80):
        try:
            state = board.read()
            return board.apply(operation, dict(id=name, revision=state['revision'], **request))
        except module.Rejected as error:
            if error.uncertain or error.code not in {'busy', 'stale', 'conflict'}:
                raise
            time.sleep(random.uniform(.005, min(.1, .01 * (attempt + 1))))
    raise RuntimeError('bounded contention attempts exhausted')
transact('claim', scopes=[scope])
destination = root / 'shared-output/result.txt'
previous = destination.read_text()
temporary = destination.with_name(name + '.tmp')
temporary.write_text(previous + name + '\n')
os.replace(temporary, destination)
transact('release', scopes=[scope], writers_stopped=True, disposition='Contribution saved and verified.')
'''
        processes = [subprocess.Popen([sys.executable, "-B", "-c", script, str(TOOL), str(self.root), name],
                                      stdout=subprocess.PIPE, stderr=subprocess.PIPE) for name in names]
        try:
            results = [process.communicate(timeout=20) for process in processes]
            self.assertTrue(all(process.returncode == 0 for process in processes), results)
            self.assertEqual(sorted((output / "result.txt").read_text().splitlines()), names)
            state = self.board.read()
            self.assertTrue(all(not record["claims"] for record in state["sessions"].values()))
            self.assertEqual(len(state["releases"]), 8)
        finally:
            for process in processes:
                if process.poll() is None:
                    process.kill()
                    process.wait(timeout=5)

    def test_error_after_replace_preserves_committed_claim_and_reports_uncertainty(self):
        replace = MODULE.os.replace
        def replace_then_fail(source, destination):
            replace(source, destination)
            raise OSError("injected error after publication")
        with mock.patch.object(MODULE.os, "replace", replace_then_fail), self.assertRaises(Rejected) as raised:
            self.claim()
        self.assertTrue(raised.exception.uncertain)
        self.assertEqual(len(self.board.read()["sessions"]["alpha"]["claims"]), 1)
        self.assertFalse(self.board.lock.exists())

    def test_killed_mutex_holder_remains_blocking(self):
        script = ("import importlib.util,sys,time; "
                  "s=importlib.util.spec_from_file_location('board',sys.argv[1]); "
                  "m=importlib.util.module_from_spec(s); s.loader.exec_module(m); "
                  "b=m.Board(sys.argv[2]); c=b.mutex(); c.__enter__(); "
                  "print('locked',flush=True); time.sleep(30)")
        process = subprocess.Popen([sys.executable, "-B", "-c", script, str(TOOL), str(self.root)], stdout=subprocess.PIPE, text=True)
        try:
            self.assertEqual(process.stdout.readline().strip(), "locked")
            process.kill()
            process.wait(timeout=5)
            with self.assertRaises(Rejected) as raised:
                self.claim()
            self.assertEqual(raised.exception.code, "busy")
            self.assertTrue((self.board.lock / "owner.json").exists())
        finally:
            if process.poll() is None:
                process.kill()
                process.wait(timeout=5)
            process.stdout.close()

    def test_cli_malformed_input_has_structured_error(self):
        result = subprocess.run([sys.executable, "-B", str(TOOL), "claim", "--root", str(self.root)],
                                input=b"{broken", capture_output=True)
        self.assertEqual(result.returncode, 2)
        self.assertEqual(result.stdout, b"")
        self.assertFalse(json.loads(result.stderr)["ok"])

    def test_receipt_output_failure_does_not_undo_committed_claim(self):
        request = json.dumps(dict(id="alpha", revision=self.revision(), scopes=[self.scope("saved")])).encode()
        fake_input = mock.Mock(buffer=io.BytesIO(request))
        observed = []
        def output(*args, **kwargs):
            if not observed:
                observed.append("failed stdout")
                raise BrokenPipeError("receipt recipient disappeared")
            observed.append(args[0])
        with mock.patch.object(MODULE.sys, "stdin", fake_input), mock.patch("builtins.print", output):
            result = MODULE.main(["claim", "--root", str(self.root)])
        self.assertEqual(result, 2)
        self.assertEqual(json.loads(observed[-1])["code"], "output_uncertain")
        self.assertEqual(len(self.board.read()["sessions"]["alpha"]["claims"]), 1)

    def test_registration_template_is_usable_after_real_values_are_substituted(self):
        template = json.loads((TOOL.parents[1] / "docs/templates/session.json").read_text())
        # The primary template is now a complete record-protocol input; existing
        # JSON callers retain their explicit original registration contract.
        request = dict(id="from-template", revision=self.revision(), next_check=MODULE.now(),
                       task=template['identity']['Task and approach'], approach="Inspect and verify.",
                       baseline=template['baseline'], next_action="Review scope.")
        receipt = self.board.apply("register", request)
        self.assertEqual(receipt["id"], "from-template")


if __name__ == "__main__":
    unittest.main()
