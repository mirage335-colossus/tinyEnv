#!/usr/bin/env python3
"""Supervise one command and finish its inherited output writers before evidence.

Linux uses a private child-subreaper process, including nested sessions and groups.
Commands must not transfer writable handles or ask another service to keep writing;
such workloads require a qualified container/service supervisor. This is lifetime
supervision of cooperating programs, not hostile-process confinement. Other POSIX
systems fail closed until an equivalent descendant owner is supplied.
Windows starts suspended and assigns a no-breakaway, kill-on-close Job Object
before resuming the initial thread; assignment failure never runs child code.
Windows termination pins verified Job member handles before requesting exit and
joins them under one deadline; changed cumulative assignments fail closed.
Normal completion checks signaled member handles and a fresh complete Job list
before waiting for accounting retirement; a running descendant fails immediately.
Native qualification is required for each supported platform and environment.
"""
import ctypes
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time


class ProcessTreeError(RuntimeError):
    pass


def _remaining(deadline):
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise ProcessTreeError('descendant exit deadline exhausted; retain output ownership')
    return remaining


def _direct_children():
    """The private supervisor has one thread and is its children's only reaper."""
    text = Path('/proc/self/task/' + str(os.getpid()) + '/children').read_text()
    values = text.split()
    if any(not value.isdecimal() or int(value) <= 0 for value in values):
        raise ProcessTreeError('invalid private supervisor child inventory')
    return [int(value) for value in values]


def _linux_supervise(parent, report_fd, control_fd, argv):
    """Run only in a dedicated process, never inside the calling Python harness.

    Reaping all children to ECHILD proves no descendant can still create writers.
    During cleanup, killing direct children makes their descendants direct adopted
    children of this subreaper. Repeat until the kernel reports no children. PID
    identity cannot be reused between inventory and kill: this single-threaded
    process performs no wait/reap between those operations.
    """
    stopping = False
    primary = None
    code = None
    outlived = False
    error = None
    reaped = 0
    def stop(_signum, _frame):
        nonlocal stopping
        stopping = True
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGCHLD, signal.SIG_DFL)
    os.set_blocking(control_fd, False)
    def requested():
        try:
            # Data requests termination; EOF means the caller disappeared.
            os.read(control_fd, 1)
            return True
        except BlockingIOError:
            return False
    try:
        api = ctypes.CDLL(None, use_errno=True)
        api.prctl.argtypes = [ctypes.c_int, ctypes.c_ulong, ctypes.c_ulong, ctypes.c_ulong, ctypes.c_ulong]
        api.prctl.restype = ctypes.c_int
        if api.prctl(36, 1, 0, 0, 0) != 0:  # PR_SET_CHILD_SUBREAPER
            raise ProcessTreeError('private Linux child-subreaper setup failed')
        if api.prctl(1, signal.SIGTERM, 0, 0, 0) != 0:  # PR_SET_PDEATHSIG
            raise ProcessTreeError('private Linux parent-death notification failed')
        if os.getppid() != parent:
            raise ProcessTreeError('command owner exited before launch')
        _direct_children()  # Require the cleanup primitive before any command code.
        if stopping or requested():
            stopping = True
            code = -signal.SIGTERM
        else:
            child = subprocess.Popen(argv, stdin=subprocess.DEVNULL, close_fds=True)
            primary = child.pid
    except BaseException as failure:
        error = 'supervisor launch failed: ' + str(failure)[:1024]
        stopping = True
    # Even a failed inspection keeps this owner alive while children remain. The
    # caller times out and retains ownership instead of claiming uncertain cleanup.
    while True:
        empty = False
        try:
            stopping = stopping or requested()
            while True:
                try:
                    pid, status = os.waitpid(-1, os.WNOHANG)
                except ChildProcessError:
                    empty = True
                    break
                if not pid:
                    break
                reaped += 1
                if pid == primary:
                    code = os.waitstatus_to_exitcode(status)
                    child.returncode = code
            if empty:
                break
            if code is not None and not stopping:
                outlived = True
            if stopping or outlived:
                for pid in _direct_children():
                    try:
                        os.kill(pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
        except BaseException as failure:
            error = 'descendant cleanup inspection failed: ' + str(failure)[:1024]
            stopping = True
        time.sleep(0.01)
    report = {'schema_version': 1, 'primary_returncode': code, 'descendants_outlived': outlived,
              'terminated': stopping, 'error': error, 'reaped': reaped}
    data = (json.dumps(report, sort_keys=True) + '\n').encode()
    if len(data) > 4096:
        report['error'] = 'supervisor failure exceeded the bounded diagnostic size'
        data = (json.dumps(report, sort_keys=True) + '\n').encode()
    # The pipe is private, has one small final record, and is not inherited by the
    # command. A lost receipt remains uncertain to the caller, even after cleanup.
    try:
        os.write(report_fd, data)
    finally:
        os.close(report_fd)
        os.close(control_fd)


class _LinuxProcess:
    """Popen-compatible observation of a privately supervised primary command."""
    def __init__(self, supervisor, report_fd, argv, control_fd=None):
        self.supervisor, self.report_fd, self.args = supervisor, report_fd, argv
        self.control_fd = control_fd
        self.pid = supervisor.pid
        self.returncode = None
        self.report = None
        self.failure = None

    def _collect(self):
        if self.failure is not None:
            raise ProcessTreeError(self.failure)
        if self.report is not None:
            return self.returncode
        try:
            raw = os.read(self.report_fd, 8193)
            if len(raw) > 8192 or self.supervisor.returncode != 0:
                raise ValueError('private supervisor failed or excessive receipt')
            report = json.loads(raw)
            required = {'schema_version', 'primary_returncode', 'descendants_outlived', 'terminated', 'error', 'reaped'}
            if (not isinstance(report, dict) or set(report) != required or report['schema_version'] != 1
                    or type(report['descendants_outlived']) is not bool or type(report['terminated']) is not bool
                    or type(report['reaped']) is not int or report['reaped'] < 0
                    or (report['error'] is not None and not isinstance(report['error'], str))
                    or (report['primary_returncode'] is not None and type(report['primary_returncode']) is not int)):
                raise ValueError('invalid private supervisor receipt')
            if report['primary_returncode'] is None and not report['error']:
                raise ValueError('primary completion missing from supervisor receipt')
            self.report = report
            self.returncode = report['primary_returncode'] if report['primary_returncode'] is not None else 125
        except (OSError, ValueError) as failure:
            self.failure = 'private supervisor completion uncertain; retain output ownership'
            raise ProcessTreeError(self.failure) from failure
        finally:
            if self.report_fd is not None:
                os.close(self.report_fd)
                self.report_fd = None
            if self.control_fd is not None:
                os.close(self.control_fd)
                self.control_fd = None
        return self.returncode

    def poll(self):
        return None if self.supervisor.poll() is None else self._collect()

    def wait(self, timeout=None):
        self.supervisor.wait(timeout=timeout)
        return self._collect()

    def terminate(self):
        if self.supervisor.poll() is None:
            # A pipe request is safe before the private interpreter has installed
            # handlers; an immediate signal could otherwise kill it at startup.
            try:
                os.write(self.control_fd, b'T')
            except BrokenPipeError:
                pass


def _linux_launch(argv, cwd, stream, *, env=None):
    incoming, outgoing = os.pipe()
    try:
        control_incoming, control_outgoing = os.pipe()
    except BaseException:
        os.close(incoming)
        os.close(outgoing)
        raise
    try:
        process = subprocess.Popen([sys.executable, '-B', str(Path(__file__).resolve()),
                                    '--supervise-linux', str(os.getpid()), str(outgoing), str(control_incoming), *argv],
                                   cwd=cwd, stdin=subprocess.DEVNULL, stdout=stream,
                                   stderr=subprocess.STDOUT, start_new_session=True, pass_fds=(outgoing,control_incoming), env=env)
    except BaseException:
        os.close(incoming)
        os.close(control_outgoing)
        raise
    finally:
        os.close(outgoing)
        os.close(control_incoming)
    return ProcessTree(_LinuxProcess(process, incoming, argv,control_outgoing))


class _WindowsJob:
    """Native handle owner; constructed only on Windows."""
    def __init__(self):
        from ctypes import wintypes as w
        self.api = ctypes.WinDLL('kernel32', use_last_error=True)
        self.handle = None
        self.completion_observation = None
        self.w = w
        class BasicLimits(ctypes.Structure):
            _fields_ = [('process_time', ctypes.c_longlong), ('job_time', ctypes.c_longlong),
                        ('flags', w.DWORD), ('min_working_set', ctypes.c_size_t),
                        ('max_working_set', ctypes.c_size_t), ('active_limit', w.DWORD),
                        ('affinity', ctypes.c_size_t), ('priority', w.DWORD), ('scheduling', w.DWORD)]
        class IoCounters(ctypes.Structure):
            _fields_ = [(name, ctypes.c_ulonglong) for name in
                        ('read_ops', 'write_ops', 'other_ops', 'read_bytes', 'write_bytes', 'other_bytes')]
        class ExtendedLimits(ctypes.Structure):
            _fields_ = [('basic', BasicLimits), ('io', IoCounters),
                        ('process_memory', ctypes.c_size_t), ('job_memory', ctypes.c_size_t),
                        ('peak_process_memory', ctypes.c_size_t), ('peak_job_memory', ctypes.c_size_t)]
        class Accounting(ctypes.Structure):
            _fields_ = [('user_time', ctypes.c_longlong), ('kernel_time', ctypes.c_longlong),
                        ('period_user', ctypes.c_longlong), ('period_kernel', ctypes.c_longlong),
                        ('page_faults', w.DWORD), ('total', w.DWORD), ('active', w.DWORD),
                        ('terminated', w.DWORD)]
        class ThreadEntry(ctypes.Structure):
            _fields_ = [('size', w.DWORD), ('usage', w.DWORD), ('thread', w.DWORD),
                        ('owner', w.DWORD), ('base_priority', w.LONG), ('delta_priority', w.LONG),
                        ('flags', w.DWORD)]
        self.Accounting, self.ThreadEntry = Accounting, ThreadEntry
        signatures = {
            'CreateJobObjectW': ([ctypes.c_void_p, w.LPCWSTR], w.HANDLE),
            'SetInformationJobObject': ([w.HANDLE, ctypes.c_int, ctypes.c_void_p, w.DWORD], w.BOOL),
            'QueryInformationJobObject': ([w.HANDLE, ctypes.c_int, ctypes.c_void_p, w.DWORD, ctypes.c_void_p], w.BOOL),
            'AssignProcessToJobObject': ([w.HANDLE, w.HANDLE], w.BOOL),
            'TerminateJobObject': ([w.HANDLE, w.UINT], w.BOOL),
            'CloseHandle': ([w.HANDLE], w.BOOL),
            'CreateToolhelp32Snapshot': ([w.DWORD, w.DWORD], w.HANDLE),
            'Thread32First': ([w.HANDLE, ctypes.POINTER(ThreadEntry)], w.BOOL),
            'Thread32Next': ([w.HANDLE, ctypes.POINTER(ThreadEntry)], w.BOOL),
            'OpenThread': ([w.DWORD, w.BOOL, w.DWORD], w.HANDLE),
            'ResumeThread': ([w.HANDLE], w.DWORD),
            'OpenProcess': ([w.DWORD, w.BOOL, w.DWORD], w.HANDLE),
            'IsProcessInJob': ([w.HANDLE, w.HANDLE, ctypes.POINTER(w.BOOL)], w.BOOL),
            'WaitForSingleObject': ([w.HANDLE, w.DWORD], w.DWORD),
            'QueryFullProcessImageNameW': ([w.HANDLE, w.DWORD, w.LPWSTR, ctypes.POINTER(w.DWORD)], w.BOOL),
        }
        for name, (arguments, result) in signatures.items():
            function = getattr(self.api, name)
            function.argtypes, function.restype = arguments, result
        self.handle = self.api.CreateJobObjectW(None, None)
        if not self.handle:
            self.fail('create job')
        try:
            limits = ExtendedLimits()
            limits.basic.flags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE; no breakaway flags.
            if not self.api.SetInformationJobObject(self.handle, 9, ctypes.byref(limits), ctypes.sizeof(limits)):
                self.fail('configure non-breakaway job')
        except BaseException:
            self.close()
            raise

    def fail(self, operation):
        raise ProcessTreeError(operation + ' failed: ' + str(ctypes.WinError(ctypes.get_last_error())))

    def assign(self, process):
        if not self.api.AssignProcessToJobObject(self.handle, self.w.HANDLE(int(process._handle))):
            self.fail('assign suspended process to job')

    def resume(self, process):
        snapshot = self.api.CreateToolhelp32Snapshot(0x4, 0)  # TH32CS_SNAPTHREAD
        if snapshot == ctypes.c_void_p(-1).value:
            self.fail('inspect suspended process thread')
        matches = []
        try:
            entry = self.ThreadEntry()
            entry.size = ctypes.sizeof(entry)
            found = self.api.Thread32First(snapshot, ctypes.byref(entry))
            while found:
                if entry.owner == process.pid:
                    matches.append(entry.thread)
                entry.size = ctypes.sizeof(entry)
                found = self.api.Thread32Next(snapshot, ctypes.byref(entry))
            if ctypes.get_last_error() != 18:  # ERROR_NO_MORE_FILES
                self.fail('enumerate suspended process thread')
        finally:
            if not self.api.CloseHandle(snapshot):
                self.fail('close thread snapshot')
        if len(matches) != 1:
            raise ProcessTreeError('expected exactly one suspended initial thread')
        thread = self.api.OpenThread(0x2, False, matches[0])  # THREAD_SUSPEND_RESUME
        if not thread:
            self.fail('open suspended initial thread')
        try:
            count = self.api.ResumeThread(thread)
            if count == 0xffffffff:
                self.fail('resume initial thread')
            if count != 1:
                raise ProcessTreeError('unexpected initial thread suspension count')
        finally:
            if not self.api.CloseHandle(thread):
                self.fail('close initial thread handle')

    def accounting(self):
        accounting = self.Accounting()
        if not self.api.QueryInformationJobObject(self.handle, 1, ctypes.byref(accounting),
                                                  ctypes.sizeof(accounting), None):
            self.fail('inspect job membership')
        return accounting

    def active(self):
        return self.accounting().active

    def total(self):
        return self.accounting().total

    def process_ids(self):
        """Take a complete, bounded Job snapshot, including nested members."""
        capacity = 32
        for _ in range(8):
            class ProcessIds(ctypes.Structure):
                _fields_ = [('assigned', self.w.DWORD), ('count', self.w.DWORD),
                            ('ids', ctypes.c_size_t * capacity)]
            members = ProcessIds()
            ok = self.api.QueryInformationJobObject(self.handle, 3, ctypes.byref(members),
                                                    ctypes.sizeof(members), None)
            if not ok and ctypes.get_last_error() != 234:  # ERROR_MORE_DATA
                self.fail('inspect job process list')
            if members.count > capacity or members.count > members.assigned:
                raise ProcessTreeError('invalid job process list counts')
            if ok and members.count == members.assigned:
                result = list(members.ids[:members.count])
                if len(set(result)) != len(result) or any(not 0 < pid <= 0xffffffff for pid in result):
                    raise ProcessTreeError('invalid job process identifiers')
                return result
            capacity = max(capacity * 2, members.assigned)
            if capacity > 65536:
                break
        raise ProcessTreeError('job process inventory remains incomplete; retain output ownership')

    def observe_running_process(self, pid, handle, members, state):
        """Retain the first rejected handle observation, never a later substitute.

        These bounded diagnostics cannot grant completion. Query the image through
        the already pinned, verified member handle; do not log argv or environment.
        Accounting is explicitly a later observation, not an atomic snapshot.
        """
        if getattr(self, 'completion_observation', None) is not None:
            return
        observation = {'pid': pid, 'member_verified': True, 'wait_state': state,
                       'snapshot_count': len(members), 'snapshot_pids': members[:32],
                       'snapshot_truncated': len(members) > 32}
        self.completion_observation = observation
        image = ctypes.create_unicode_buffer(32768)
        size = self.w.DWORD(len(image))
        if self.api.QueryFullProcessImageNameW(handle, 0, image, ctypes.byref(size)):
            observation['image'] = image.value[:4096]
            observation['image_truncated'] = len(image.value) > 4096
        else:
            observation['image_query_error'] = ctypes.get_last_error()
        try:
            accounting = self.accounting()
            observation['accounting_after_observation'] = {
                key: int(getattr(accounting, key)) for key in ('active', 'total', 'terminated')}
        except (OSError, ProcessTreeError):
            observation['accounting_query_error'] = ctypes.get_last_error()

    def has_running_process(self):
        """Separate executable members from already-signaled process objects.

        Job accounting and process-handle completion are separate observations.
        Never give a running descendant a grace period to finish successfully.
        Open handles pin identity; membership rejects a reused foreign PID.
        """
        observed = {}
        try:
            pending = self.process_ids()
            for _ in range(8):
                disappeared = set()
                for pid in pending:
                    if pid in observed:
                        continue  # The retained signaled handle pins this identity.
                    # SYNCHRONIZE | PROCESS_QUERY_LIMITED_INFORMATION; no inheritance.
                    handle = self.api.OpenProcess(0x101000, False, pid)
                    if not handle:
                        error = ctypes.get_last_error()
                        if error == 87:  # Possibly retired since the snapshot.
                            disappeared.add(pid)
                            continue
                        raise ProcessTreeError('open job member failed: ' + str(error) +
                                               '; retain output ownership')
                    observed[pid] = handle
                    member = self.w.BOOL()
                    if not self.api.IsProcessInJob(handle, self.handle, ctypes.byref(member)):
                        self.fail('confirm job process identity')
                    if not member.value:
                        raise ProcessTreeError('job process identity changed; retain output ownership')
                    state = self.api.WaitForSingleObject(handle, 0)
                    if state == 0x102:  # WAIT_TIMEOUT: still executable now.
                        self.observe_running_process(pid, handle, pending, state)
                        return True
                    if state != 0:  # Only WAIT_OBJECT_0 establishes termination.
                        self.fail('inspect job process completion')
                # A member could have created another member before terminating.
                # Inspect every newly found process before permitting any sleep.
                pending = self.process_ids()
                if disappeared.intersection(pending):
                    raise ProcessTreeError('job member lookup remains ambiguous; retain output ownership')
                if all(pid in observed for pid in pending):
                    return False
            raise ProcessTreeError('job membership did not settle; retain output ownership')
        finally:
            failed = False
            for handle in observed.values():
                if not self.api.CloseHandle(handle):
                    failed = True
            if failed:
                self.fail('close job process observation')

    def terminate(self):
        if not self.api.TerminateJobObject(self.handle, 1):
            self.fail('terminate job')

    def terminate_and_wait(self, deadline, *, validate_live=None):
        """Pin identities before termination; accounting alone is not a join.

        A cumulative assignment change can hide a new child that disappeared from
        the active list before it was pinned. Reject that uncertainty, even when
        the final list and active count are empty. This is not a creation freeze.
        """
        observed, requested, failure = {}, False, None
        try:
            _remaining(deadline)
            total = self.total()
            for pid in self.process_ids():
                _remaining(deadline)
                handle = self.api.OpenProcess(0x101000, False, pid)
                if not handle:
                    # Even ERROR_INVALID_PARAMETER cannot prove completion of an
                    # observed identity that we never managed to pin.
                    raise ProcessTreeError('cannot pin observed job member; retain output ownership')
                observed[pid] = handle
                member = self.w.BOOL()
                if not self.api.IsProcessInJob(handle, self.handle, ctypes.byref(member)):
                    self.fail('confirm termination member identity')
                if not member.value:
                    raise ProcessTreeError('termination member identity changed; retain output ownership')
            if validate_live is not None:
                # Pin the entire snapshot before classifying any live member.
                # A caller-specific helper policy never uses the first-member
                # diagnostic as proof about the remainder of the Job.
                live = []
                for pid, handle in observed.items():
                    _remaining(deadline)
                    state = self.api.WaitForSingleObject(handle, 0)
                    if state == 0x102:
                        live.append((pid, handle))
                    elif state != 0:
                        self.fail('inspect helper process completion')
                # Preserve every live observation before any caller policy work;
                # a later natural exit cannot exempt an already observed member.
                for pid, handle in live:
                    _remaining(deadline)
                    image = ctypes.create_unicode_buffer(32768)
                    size = self.w.DWORD(len(image))
                    if not self.api.QueryFullProcessImageNameW(handle, 0, image, ctypes.byref(size)):
                        self.fail('identify live helper image')
                    if not 0 < size.value < len(image) or size.value != len(image.value):
                        raise ProcessTreeError('invalid live helper image identity; retain output ownership')
                    if validate_live(pid, image.value) is not True:
                        raise ProcessTreeError('live member is not an accepted command helper; retain output ownership')
                    _remaining(deadline)
            def reconcile():
                _remaining(deadline)
                members = self.process_ids()
                if any(pid not in observed for pid in members) or self.total() != total:
                    raise ProcessTreeError('job assignments changed during termination; retain output ownership')
            reconcile()
            requested = True
            self.terminate()
            for handle in observed.values():
                milliseconds = max(1, min(int(_remaining(deadline) * 1000), 0xfffffffe))
                state = self.api.WaitForSingleObject(handle, milliseconds)
                if state == 0x102:
                    raise ProcessTreeError('descendant exit deadline exhausted; retain output ownership')
                if state != 0:
                    self.fail('join terminated job member')
            reconcile()
        except BaseException as error:
            failure = error
            raise
        finally:
            cleanup_errors = []
            if not requested:
                # Capture failed, but still stop executable members. This is a
                # best-effort stop, never a substitute for the failed join proof.
                try:
                    self.terminate()
                except BaseException as error:
                    cleanup_errors.append('stop after failed capture: ' + str(error))
            for handle in observed.values():
                if not self.api.CloseHandle(handle):
                    cleanup_errors.append('close termination observation failed')
            if cleanup_errors:
                message = '; '.join(cleanup_errors) + '; retain output ownership'
                if failure is not None:
                    raise ProcessTreeError(str(failure) + '; ' + message) from failure
                raise ProcessTreeError(message)
        return total

    def close(self):
        if self.handle is not None:
            if not self.api.CloseHandle(self.handle):
                self.fail('close job')
            self.handle = None


class ProcessTree:
    def __init__(self, process, job=None):
        self.process, self.job = process, job
        self.closed = False
        self.termination_joined = False
        self.termination_failure = None

    def poll(self):
        return self.process.poll()

    def wait(self, timeout=None):
        return self.process.wait(timeout=timeout)

    def _live(self):
        if isinstance(self.process, _LinuxProcess):
            return self.process.poll() is None
        return bool(self.job.active())

    def terminate(self, timeout=5, *, validate_live=None):
        """Stop and join every member; optional helper validation precedes stopping.

        A caller-specific helper policy requires an already successful Windows
        parent and validates every live pinned identity. It does not alter finish.
        """
        if self.closed:
            return
        if self.termination_failure is not None:
            raise ProcessTreeError(self.termination_failure)
        if validate_live is not None:
            if (not callable(validate_live) or self.job is None or self.process.poll() != 0
                    or self.termination_joined):
                raise ProcessTreeError('helper completion requires a successful unjoined Windows command')
        if self.termination_joined:
            return
        deadline = time.monotonic() + timeout
        try:
            if isinstance(self.process, _LinuxProcess):
                self.process.terminate()
            elif self.job is not None:
                total = (self.job.terminate_and_wait(deadline) if validate_live is None else
                         self.job.terminate_and_wait(deadline, validate_live=validate_live))
            self.process.wait(timeout=_remaining(deadline))
            while self._live():
                time.sleep(min(0.01, _remaining(deadline)))
            _remaining(deadline)
            if self.job is not None and self.job.total() != total:
                raise ProcessTreeError('job assignments changed during termination; retain output ownership')
            self.termination_joined = True
        except BaseException as error:
            if self.job is not None:
                self.termination_failure = 'Windows termination remains unconfirmed: ' + str(error)
            raise

    def finish(self):
        """A successful parent with surviving writers is an incomplete command."""
        if self.closed:
            raise ProcessTreeError('process owner already closed')
        if self.termination_failure is not None:
            raise ProcessTreeError(self.termination_failure)
        if self.process.poll() is None:
            raise ProcessTreeError('parent has not exited')
        if isinstance(self.process, _LinuxProcess):
            report = self.process.report
            if report['error']:
                raise ProcessTreeError(report['error'])
            if report['descendants_outlived']:
                raise ProcessTreeError('descendants outlived the command; output completion was not valid')
        deadline = time.monotonic() + 5
        while self._live():
            if self.job is None or self.job.has_running_process():
                message = 'descendants outlived the command; output completion was not valid'
                observation = getattr(self.job, 'completion_observation', None)
                if isinstance(observation, dict):
                    message += '; windows_completion=' + json.dumps(observation, sort_keys=True)
                try:
                    self.terminate()
                except BaseException as error:
                    raise ProcessTreeError(message + '; descendant cleanup failed: ' + str(error)) from error
                raise ProcessTreeError(message)
            # All observed members have terminated. Wait only for accounting to
            # retire them, rechecking for any actual live member on every turn.
            if time.monotonic() >= deadline:
                raise ProcessTreeError('job retirement remains unconfirmed; retain output ownership')
            time.sleep(0.01)
        return self.process.returncode

    def close(self):
        if not self.closed:
            try:
                if self.termination_failure is not None:
                    raise ProcessTreeError(self.termination_failure)
                if self.job is not None or self.process.poll() is None or self._live():
                    # Windows must not skip a required join merely because its
                    # primary and aggregate counters already look completed.
                    self.terminate()
            finally:
                if self.job is not None:
                    self.job.close()
            self.closed = True


def launch(argv, cwd, stream, *, env=None):
    """Own descendants before execution; env affects only the supervised tree."""
    if os.name == 'posix' and sys.platform.startswith('linux'):
        return _linux_launch(argv, cwd, stream, env=env)
    if os.name != 'nt':
        raise ProcessTreeError('no qualified process supervisor for this operating system')
    job = _WindowsJob() if os.name == 'nt' else None
    process = None
    try:
        process = subprocess.Popen(argv, cwd=cwd, stdin=subprocess.DEVNULL,
                                   stdout=stream, stderr=subprocess.STDOUT,
                                   start_new_session=os.name == 'posix',
                                   creationflags=0x4 if job is not None else 0, env=env)
        if job is not None:
            job.assign(process)
            job.resume(process)
        return ProcessTree(process, job)
    except BaseException as original:
        # Assignment failure leaves the child suspended; no child code ran.
        cleanup_errors = []
        actions = []
        deadline = time.monotonic() + 5
        if process is not None:
            if job is not None:
                # Resume can fail after the initial thread already ran (for
                # example while closing its handle), so descendants need joining.
                actions.append(lambda: job.terminate_and_wait(deadline))
            actions.extend((lambda: process.kill() if process.poll() is None else None,
                            lambda: process.wait(timeout=_remaining(deadline))))
        if job is not None:
            actions.append(job.close)
        for action in actions:
            try:
                action()
            except BaseException as error:
                cleanup_errors.append(str(error))
        if cleanup_errors:
            raise ProcessTreeError('launch failed and writer cleanup is uncertain: '
                                   + '; '.join(cleanup_errors)) from original
        raise


if __name__ == '__main__':
    if len(sys.argv) < 6 or sys.argv[1] != '--supervise-linux' or not sys.platform.startswith('linux'):
        raise SystemExit('private supervisor requires its complete internal invocation')
    _linux_supervise(int(sys.argv[2]), int(sys.argv[3]), int(sys.argv[4]), sys.argv[5:])
