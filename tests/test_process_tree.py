"""Real process-lifetime scenarios plus native launch ordering checks."""
import ctypes
import importlib.util
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from types import SimpleNamespace
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('process_tree', ROOT / 'tools/process_tree.py')
TREE = importlib.util.module_from_spec(spec)
spec.loader.exec_module(TREE)


@unittest.skipUnless(os.name in ('posix', 'nt'), 'requires a supplied native process supervisor')
class NativeProcessTree(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='process-owner-')
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.stream = (self.root / 'console.log').open('wb')
        self.addCleanup(self.stream.close)

    def launch(self, body, *, env=None):
        owner = TREE.launch([sys.executable, '-B', '-c', body], self.root, self.stream, env=env)
        self.addCleanup(owner.close)
        return owner

    def test_default_environment_is_inherited(self):
        with mock.patch.dict(os.environ, {'FOUNDATION_PROCESS_ENV_FIXTURE':'inherited'}):
            owner=self.launch("import os;print(os.environ['FOUNDATION_PROCESS_ENV_FIXTURE'])")
            self.assertEqual(owner.wait(timeout=10),0);self.assertEqual(owner.finish(),0);owner.close()
            self.assertEqual(os.environ['FOUNDATION_PROCESS_ENV_FIXTURE'],'inherited')
        self.assertEqual((self.root/'console.log').read_text().strip(),'inherited')

    def test_environment_override_is_child_only_and_reaches_descendants(self):
        variable='FOUNDATION_PROCESS_ENV_FIXTURE'
        with mock.patch.dict(os.environ,{variable:'parent'}):
            environment=dict(os.environ,FOUNDATION_PROCESS_ENV_FIXTURE='child-only',GALLIUM_DRIVER='llvmpipe')
            body=("import os,subprocess,sys;print(os.environ['FOUNDATION_PROCESS_ENV_FIXTURE'],flush=True);"
                  "subprocess.run([sys.executable,'-B','-c',\"import os;print(os.environ['FOUNDATION_PROCESS_ENV_FIXTURE'])\"],check=True)")
            owner=self.launch(body,env=environment)
            self.assertEqual(owner.wait(timeout=10),0);self.assertEqual(owner.finish(),0);owner.close()
            self.assertEqual(os.environ[variable],'parent')
            self.assertEqual(environment[variable],'child-only')
        self.assertEqual((self.root/'console.log').read_text().splitlines(),['child-only','child-only'])

    def test_complete_parent_and_joined_child_leave_stable_output(self):
        for _ in range(8):
            owner = self.launch("import subprocess,sys; subprocess.run([sys.executable,'-c','print(42)'],check=True);print('done')")
            self.assertEqual(owner.wait(timeout=10), 0)
            self.assertEqual(owner.finish(), 0)
            owner.close()
        self.assertEqual((self.root / 'console.log').read_text().splitlines(), ['42', 'done'] * 8)

    def test_successful_parent_with_inherited_output_child_is_rejected_and_stopped(self):
        body = ("import subprocess,sys; subprocess.Popen([sys.executable,'-c',"
                "\"import time;time.sleep(0.5);print('late',flush=True);time.sleep(30)\"]);print('parent done')")
        owner = self.launch(body)
        self.assertEqual(owner.wait(timeout=10), 0)
        with self.assertRaisesRegex(TREE.ProcessTreeError, 'descendants outlived'):
            owner.finish()
        saved = (self.root / 'console.log').read_bytes()
        time.sleep(0.6)
        self.assertEqual((self.root / 'console.log').read_bytes(), saved)
        self.assertNotIn(b'late', saved)

    def test_termination_stops_parent_and_child_without_releasing_early(self):
        child = "import os,time;print('child-ready:'+str(os.getpid()),flush=True);time.sleep(30)"
        owner = self.launch("import subprocess,sys,time;subprocess.Popen([sys.executable,'-c'," +
                            repr(child) + "]);print('parent-ready',flush=True);time.sleep(30)")
        log = self.root / 'console.log'
        deadline = time.monotonic() + 10
        while True:
            lines = log.read_bytes().splitlines()
            children = [line.removeprefix(b'child-ready:') for line in lines if line.startswith(b'child-ready:')]
            if b'parent-ready' in lines and len(children) == 1 and children[0].isdigit():
                child_pid = int(children[0]); break
            if time.monotonic() >= deadline:
                self.fail('parent and output-owning child did not reach ready state')
            time.sleep(0.01)
        handle = None
        if owner.job is not None:
            # Pin this child before termination; a post-exit PID lookup could
            # observe a retired or reused identity instead of our output writer.
            job = owner.job
            handle = job.api.OpenProcess(0x101000, False, child_pid)
            self.assertTrue(handle, 'cannot pin the ready child process')
        try:
            if handle is not None:
                member = job.w.BOOL()
                self.assertTrue(job.api.IsProcessInJob(handle, job.handle, ctypes.byref(member)))
                self.assertTrue(member.value, 'ready child is not contained in the exact Job')
            owner.terminate()
            self.assertIsNotNone(owner.poll())
            if handle is not None:
                self.assertEqual(job.api.WaitForSingleObject(handle, 0), 0,
                                 'terminate returned before the exact child process completed')
            self.assertFalse(owner._live())
        finally:
            if handle is not None:
                self.assertTrue(job.api.CloseHandle(handle), 'cannot close child observation handle')
        owner.close()
        self.assertTrue(owner.closed)
        self.stream.close()
        # A completed tree and closed caller stream must release its output now.
        # Never hide an actual surviving writer behind cleanup retries or sleeps.
        released = self.root / 'released.log'
        try:
            log.rename(released)
            released.unlink()
        except OSError as error:
            self.fail('output remains locked after parent/child completion, empty Job and closed caller stream: ' + str(error))

    def test_finish_before_exit_is_not_completion(self):
        owner = self.launch('import time;time.sleep(30)')
        with self.assertRaisesRegex(TREE.ProcessTreeError, 'has not exited'):
            owner.finish()
        owner.terminate()

    @unittest.skipUnless(os.name == 'nt', 'native Job Object breakaway rejection is Windows-specific')
    def test_windows_child_cannot_break_out_of_its_job(self):
        owner = self.launch("import subprocess,sys\ntry:\n subprocess.Popen([sys.executable,'-c','pass'],creationflags=0x01000000)\nexcept OSError:\n print('breakaway denied')\nelse:\n raise SystemExit('breakaway incorrectly allowed')")
        self.assertEqual(owner.wait(timeout=10), 0)
        self.assertEqual(owner.finish(), 0)
        self.assertIn(b'breakaway denied', (self.root / 'console.log').read_bytes())


class WindowsCompletionObservation(unittest.TestCase):
    """Native API fixtures distinguish terminated objects from surviving writers."""
    def job(self, pids=(101,), state=0, member=True):
        job = TREE._WindowsJob.__new__(TREE._WindowsJob)
        job.handle = 700
        job.completion_observation = None
        job.accounting = mock.Mock(return_value=SimpleNamespace(active=len(pids), total=len(pids), terminated=0))
        job.w = SimpleNamespace(BOOL=ctypes.c_int32, DWORD=ctypes.c_uint32)
        job.api = mock.Mock()
        job.process_ids = mock.Mock(return_value=list(pids))
        job.api.OpenProcess.side_effect = lambda rights, inherit, pid: pid + 1000
        def membership(handle, exact_job, output):
            self.assertEqual(exact_job, 700)
            output._obj.value = member
            return True
        job.api.IsProcessInJob.side_effect = membership
        job.api.WaitForSingleObject.return_value = state
        job.api.CloseHandle.return_value = True
        def image_name(handle, flags, output, size):
            output.value = r'C:\Tools\compiler-child.exe'
            size._obj.value = len(output.value)
            return True
        job.api.QueryFullProcessImageNameW.side_effect = image_name
        job.fail = mock.Mock(side_effect=lambda operation: (_ for _ in ()).throw(TREE.ProcessTreeError(operation)))
        return job

    def owner(self, job):
        process = mock.Mock(returncode=0)
        process.poll.return_value = 0
        return TREE.ProcessTree(process, job)

    def test_signaled_members_wait_for_accounting_retirement_without_termination(self):
        job = self.job(pids=(101, 102))
        job.active = mock.Mock(side_effect=[2, 1, 0])
        job.terminate = mock.Mock()
        owner = self.owner(job)
        with mock.patch.object(TREE.time, 'sleep') as sleep:
            self.assertEqual(owner.finish(), 0)
        self.assertEqual(sleep.call_count, 2)
        self.assertEqual(job.api.WaitForSingleObject.call_args_list,
                         [mock.call(1101, 0), mock.call(1102, 0)] * 2)
        self.assertEqual(job.api.OpenProcess.call_args_list,
                         [mock.call(0x101000, False, 101), mock.call(0x101000, False, 102)] * 2)
        self.assertEqual(job.api.CloseHandle.call_count, 4)
        job.terminate.assert_not_called()

    def test_a_live_member_is_rejected_immediately_even_if_it_would_exit_next(self):
        job = self.job(state=0x102)
        job.active = mock.Mock(side_effect=[1, 0])
        owner = self.owner(job)
        with mock.patch.object(owner, 'terminate') as terminate, mock.patch.object(TREE.time, 'sleep') as sleep:
            with self.assertRaisesRegex(TREE.ProcessTreeError, 'descendants outlived'):
                owner.finish()
        terminate.assert_called_once_with()
        sleep.assert_not_called()
        self.assertEqual(job.active.call_count, 1)
        job.api.CloseHandle.assert_called_once_with(1101)

    def test_live_member_diagnostic_uses_exact_handle_and_keeps_first_observation(self):
        job = self.job(state=0x102)
        job.active = mock.Mock(return_value=1)
        owner = self.owner(job)
        def image_name(handle, flags, output, size):
            self.assertEqual((handle, flags), (1101, 0))
            job.api.CloseHandle.assert_not_called()
            job.api.WaitForSingleObject.return_value = 0  # Exits while diagnostics run.
            output.value = r'C:\Tools\compiler-child.exe'
            size._obj.value = len(output.value)
            return True
        job.api.QueryFullProcessImageNameW.side_effect = image_name
        with mock.patch.object(owner, 'terminate') as terminate, mock.patch.object(TREE.time, 'sleep') as sleep:
            with self.assertRaisesRegex(TREE.ProcessTreeError, 'windows_completion=') as caught:
                owner.finish()
        value = job.completion_observation
        self.assertEqual(value['pid'], 101)
        self.assertEqual(value['wait_state'], 258)
        self.assertTrue(value['member_verified'])
        self.assertEqual(value['image'], r'C:\Tools\compiler-child.exe')
        self.assertEqual(value['accounting_after_observation'], {'active': 1, 'total': 1, 'terminated': 0})
        self.assertIn('compiler-child.exe', str(caught.exception))
        job.api.WaitForSingleObject.assert_called_once_with(1101, 0)
        job.api.CloseHandle.assert_called_once_with(1101)
        terminate.assert_called_once_with(); sleep.assert_not_called()
        job.observe_running_process(999, 1999, [999], 258)
        self.assertEqual(job.completion_observation, value)

    def test_diagnostic_query_failures_keep_numeric_errors_and_still_reject(self):
        job = self.job(state=0x102)
        job.active = mock.Mock(return_value=1)
        job.api.QueryFullProcessImageNameW.side_effect = None
        job.api.QueryFullProcessImageNameW.return_value = False
        job.accounting.side_effect = TREE.ProcessTreeError('private diagnostic text')
        owner = self.owner(job)
        with mock.patch.object(TREE.ctypes, 'get_last_error', return_value=5, create=True), \
                mock.patch.object(owner, 'terminate') as terminate:
            with self.assertRaises(TREE.ProcessTreeError) as caught:
                owner.finish()
        self.assertEqual(job.completion_observation['image_query_error'], 5)
        self.assertEqual(job.completion_observation['accounting_query_error'], 5)
        self.assertNotIn('private diagnostic text', str(caught.exception))
        terminate.assert_called_once_with()
        job.api.CloseHandle.assert_called_once_with(1101)

    def test_diagnostic_output_is_bounded_and_preserved_when_cleanup_fails(self):
        job = self.job(pids=tuple(range(100, 200)), state=0x102)
        job.active = mock.Mock(return_value=100)
        def image_name(handle, flags, output, size):
            output.value = 'x' * 8000
            return True
        job.api.QueryFullProcessImageNameW.side_effect = image_name
        owner = self.owner(job)
        failure = TREE.ProcessTreeError('join remains uncertain')
        with mock.patch.object(owner, 'terminate', side_effect=failure):
            with self.assertRaises(TREE.ProcessTreeError) as caught:
                owner.finish()
        self.assertIs(caught.exception.__cause__, failure)
        self.assertIn('windows_completion=', str(caught.exception))
        self.assertIn('join remains uncertain', str(caught.exception))
        self.assertEqual(len(job.completion_observation['image']), 4096)
        self.assertTrue(job.completion_observation['image_truncated'])
        self.assertEqual(job.completion_observation['snapshot_count'], 100)
        self.assertEqual(len(job.completion_observation['snapshot_pids']), 32)
        self.assertTrue(job.completion_observation['snapshot_truncated'])
        job.api.CloseHandle.assert_called_once_with(1100)

    def test_nonretiring_accounting_is_bounded_and_keeps_owner_unclosed(self):
        job = self.job(pids=())
        job.active = mock.Mock(return_value=1)
        owner = self.owner(job)
        with mock.patch.object(TREE.time, 'monotonic', side_effect=[10, 16]):
            with self.assertRaisesRegex(TREE.ProcessTreeError, 'retirement remains unconfirmed'):
                owner.finish()
        self.assertFalse(owner.closed)
        job.api.CloseHandle.assert_not_called()

    def test_new_member_created_before_observed_exit_is_inspected_before_sleep(self):
        job = self.job()
        job.active = mock.Mock(return_value=1)
        job.process_ids.side_effect = [[101], [102]]
        job.api.WaitForSingleObject.side_effect = [0, 0x102]
        def open_process(rights, inherit, pid):
            job.api.CloseHandle.assert_not_called()  # Keep prior identity pinned.
            return pid + 1000
        job.api.OpenProcess.side_effect = open_process
        owner = self.owner(job)
        with mock.patch.object(owner, 'terminate') as terminate, mock.patch.object(TREE.time, 'sleep') as sleep:
            with self.assertRaisesRegex(TREE.ProcessTreeError, 'descendants outlived'):
                owner.finish()
        sleep.assert_not_called()
        terminate.assert_called_once_with()
        self.assertEqual(job.api.WaitForSingleObject.call_args_list, [mock.call(1101, 0), mock.call(1102, 0)])
        self.assertEqual(job.api.CloseHandle.call_args_list, [mock.call(1101), mock.call(1102)])

    def test_membership_churn_is_bounded_without_waiting_for_running_processes(self):
        job = self.job()
        job.process_ids.side_effect = [[101 + i] for i in range(9)]
        with self.assertRaisesRegex(TREE.ProcessTreeError, 'membership did not settle'):
            job.has_running_process()
        self.assertEqual(job.api.CloseHandle.call_count, 8)

    def test_reused_foreign_process_identity_is_ambiguous_even_if_signaled(self):
        job = self.job(member=False)
        with self.assertRaisesRegex(TREE.ProcessTreeError, 'identity changed'):
            job.has_running_process()
        job.api.WaitForSingleObject.assert_not_called()
        job.api.CloseHandle.assert_called_once_with(1101)

    def test_inaccessible_member_cannot_be_treated_as_completed(self):
        job = self.job()
        job.api.OpenProcess.return_value = None
        job.api.OpenProcess.side_effect = None
        with mock.patch.object(TREE.ctypes, 'get_last_error', return_value=5, create=True):
            with self.assertRaisesRegex(TREE.ProcessTreeError, 'open job member failed: 5'):
                job.has_running_process()
        job.api.CloseHandle.assert_not_called()

    def test_missing_member_requires_a_new_complete_snapshot_without_that_pid(self):
        for second, success in (([], True), ([101], False)):
            with self.subTest(second=second):
                job = self.job()
                job.process_ids.side_effect = [[101], second]
                job.api.OpenProcess.side_effect = None
                job.api.OpenProcess.return_value = None
                with mock.patch.object(TREE.ctypes, 'get_last_error', return_value=87, create=True):
                    if success:
                        self.assertFalse(job.has_running_process())
                    else:
                        with self.assertRaisesRegex(TREE.ProcessTreeError, 'lookup remains ambiguous'):
                            job.has_running_process()
                self.assertEqual(job.process_ids.call_count, 2)

    def test_membership_wait_and_close_failures_remain_failures(self):
        for failure in ('membership', 'wait', 'close'):
            with self.subTest(failure=failure):
                job = self.job()
                if failure == 'membership':
                    job.api.IsProcessInJob.side_effect = None
                    job.api.IsProcessInJob.return_value = False
                elif failure == 'wait':
                    job.api.WaitForSingleObject.return_value = 0xffffffff
                else:
                    job.api.CloseHandle.return_value = False
                with self.assertRaises(TREE.ProcessTreeError):
                    job.has_running_process()
                job.api.CloseHandle.assert_called_once_with(1101)

    def test_process_list_grows_to_return_every_member(self):
        job = self.job()
        del job.process_ids
        observed = []
        def query(handle, kind, pointer, size, returned):
            self.assertEqual((handle, kind, returned), (700, 3, None))
            value = pointer._obj; observed.append(len(value.ids))
            self.assertEqual(size, ctypes.sizeof(value))
            value.assigned = 40; value.count = min(40, len(value.ids))
            for i in range(value.count): value.ids[i] = 100 + i
            return len(value.ids) >= 40
        job.api.QueryInformationJobObject.side_effect = query
        with mock.patch.object(TREE.ctypes, 'get_last_error', return_value=234, create=True):
            self.assertEqual(job.process_ids(), list(range(100, 140)))
        self.assertEqual(observed, [32, 64])

    def test_invalid_or_unbounded_process_list_never_becomes_empty_success(self):
        for assigned, count, pids, ok, error in [(1, 2, [], True, 0),
                (2, 2, [101, 101], True, 0), (1, 1, [0], True, 0),
                (65537, 0, [], False, 234), (0, 0, [], False, 5)]:
            with self.subTest(assigned=assigned, count=count, pids=pids, error=error):
                job = self.job(); del job.process_ids
                def query(handle, kind, pointer, size, returned):
                    value = pointer._obj; value.assigned = assigned; value.count = count
                    for i, pid in enumerate(pids): value.ids[i] = pid
                    return ok
                job.api.QueryInformationJobObject.side_effect = query
                with mock.patch.object(TREE.ctypes, 'get_last_error', return_value=error, create=True):
                    with self.assertRaises(TREE.ProcessTreeError): job.process_ids()


class WindowsTerminationJoining(unittest.TestCase):
    def job(self, pids=(101, 102)):
        job = WindowsCompletionObservation().job(pids=pids)
        job.active = mock.Mock(return_value=0)
        job.total = mock.Mock(return_value=len(pids))
        job.api.TerminateJobObject.return_value = True
        return job

    def owner(self, job):
        return WindowsCompletionObservation().owner(job)

    def test_helper_policy_checks_every_live_pinned_member_before_stop_and_join(self):
        job = self.job(); owner = self.owner(job); accepted = []
        def wait(handle, milliseconds):
            if milliseconds == 0:
                job.api.TerminateJobObject.assert_not_called()
                return 0 if handle == 1101 else 258
            job.api.TerminateJobObject.assert_called_once_with(700, 1)
            return 0
        job.api.WaitForSingleObject.side_effect = wait
        def validate(pid, image):
            self.assertEqual(job.api.OpenProcess.call_count, 2)
            job.api.CloseHandle.assert_not_called()
            job.api.TerminateJobObject.assert_not_called()
            accepted.append((pid, image))
            return True
        owner.terminate(validate_live=validate)
        self.assertEqual(accepted, [(102, r'C:\Tools\compiler-child.exe')])
        self.assertTrue(owner.termination_joined)
        self.assertEqual(owner.finish(), 0)
        self.assertEqual(job.api.CloseHandle.call_args_list, [mock.call(1101), mock.call(1102)])

    def test_mixed_helper_and_unknown_member_cannot_be_accepted_from_first_match(self):
        job = self.job(); owner = self.owner(job); inspected = []
        job.api.WaitForSingleObject.return_value = 258
        def validate(pid, image):
            inspected.append(pid)
            return pid == 101
        with self.assertRaisesRegex(TREE.ProcessTreeError, 'not an accepted'):
            owner.terminate(validate_live=validate)
        self.assertEqual(inspected, [101, 102])
        self.assertFalse(owner.termination_joined)
        job.api.TerminateJobObject.assert_called_once_with(700, 1)
        self.assertEqual(job.api.CloseHandle.call_count, 2)
        with self.assertRaisesRegex(TREE.ProcessTreeError, 'termination remains unconfirmed'):
            owner.finish()

    def test_all_live_observations_survive_natural_exit_during_earlier_policy_work(self):
        job = self.job(); owner = self.owner(job); inspected = []
        job.api.WaitForSingleObject.return_value = 258
        def validate(pid, image):
            self.assertEqual(job.api.WaitForSingleObject.call_args_list,
                             [mock.call(1101, 0), mock.call(1102, 0)])
            job.api.WaitForSingleObject.return_value = 0  # The later child exits now.
            inspected.append(pid)
            return pid == 101
        with self.assertRaisesRegex(TREE.ProcessTreeError, 'not an accepted'):
            owner.terminate(validate_live=validate)
        self.assertEqual(inspected, [101, 102])
        self.assertFalse(owner.termination_joined)
        self.assertEqual(job.api.CloseHandle.call_count, 2)

    def test_helper_policy_does_not_hide_new_assignments_or_overrun_its_deadline(self):
        for late in (True, False):
            with self.subTest(late=late):
                job = self.job(pids=(101,)); owner = self.owner(job); clock = [10.]
                job.api.WaitForSingleObject.return_value = 258
                if late: job.process_ids.side_effect = [[101], [101, 102]]
                def validate(pid, image):
                    if not late: clock[0] = 16.
                    return True
                with mock.patch.object(TREE.time, 'monotonic', side_effect=lambda: clock[0]):
                    with self.assertRaisesRegex(TREE.ProcessTreeError, 'assignments changed|deadline exhausted'):
                        owner.terminate(validate_live=validate)
                self.assertFalse(owner.termination_joined)
                job.api.TerminateJobObject.assert_called_once_with(700, 1)
                job.api.CloseHandle.assert_called_once_with(1101)

    def test_helper_image_query_failure_and_callback_failure_are_fail_closed(self):
        for failed_image in (True, False):
            with self.subTest(failed_image=failed_image):
                job = self.job(); owner = self.owner(job)
                job.api.WaitForSingleObject.return_value = 258
                if failed_image:
                    job.api.QueryFullProcessImageNameW.side_effect = None
                    job.api.QueryFullProcessImageNameW.return_value = False
                validate = mock.Mock(side_effect=ValueError('identity changed'))
                with self.assertRaises((TREE.ProcessTreeError, ValueError)):
                    owner.terminate(validate_live=validate)
                self.assertFalse(owner.termination_joined)
                self.assertEqual(job.api.CloseHandle.call_count, 2)
                job.api.TerminateJobObject.assert_called_once_with(700, 1)
                if failed_image: validate.assert_not_called()

    def test_helper_policy_requires_successful_unjoined_windows_parent(self):
        for status in (None, 1):
            with self.subTest(status=status):
                job = self.job(); owner = self.owner(job); owner.process.poll.return_value = status
                with self.assertRaisesRegex(TREE.ProcessTreeError, 'successful unjoined Windows'):
                    owner.terminate(validate_live=lambda pid, image: True)
                job.api.OpenProcess.assert_not_called(); job.api.TerminateJobObject.assert_not_called()
        job = self.job(); owner = self.owner(job); owner.termination_joined = True
        with self.assertRaisesRegex(TREE.ProcessTreeError, 'successful unjoined Windows'):
            owner.terminate(validate_live=lambda pid, image: True)

    def test_zero_accounting_still_joins_pinned_child_before_return(self):
        job = self.job(); owner = self.owner(job); clock = [10.]
        def wait(handle, milliseconds):
            job.api.TerminateJobObject.assert_called_once_with(700, 1)
            self.assertEqual(job.api.OpenProcess.call_count, 2)
            job.api.CloseHandle.assert_not_called()
            self.assertEqual(milliseconds, 5000 if handle == 1101 else 4000)
            clock[0] += 1 if handle == 1101 else 2  # Child signaling is delayed.
            return 0
        job.api.WaitForSingleObject.side_effect = wait
        with mock.patch.object(TREE.time, 'monotonic', side_effect=lambda: clock[0]):
            owner.terminate(timeout=5)
        owner.process.wait.assert_called_once_with(timeout=2)
        self.assertTrue(owner.termination_joined)
        self.assertEqual(job.api.CloseHandle.call_args_list, [mock.call(1101), mock.call(1102)])
        self.assertEqual(job.total.call_count, 4)

    def test_vanished_observed_pid_fails_even_when_final_inventory_is_empty(self):
        job = self.job(); job.api.OpenProcess.side_effect = [1101, None]
        owner = self.owner(job)
        with self.assertRaisesRegex(TREE.ProcessTreeError, 'cannot pin observed'):
            owner.terminate()
        job.api.TerminateJobObject.assert_called_once_with(700, 1)
        job.api.WaitForSingleObject.assert_not_called()
        job.api.CloseHandle.assert_called_once_with(1101)
        self.assertFalse(owner.termination_joined)
        self.assertIn('cannot pin observed', owner.termination_failure)

    def test_late_or_hidden_assignments_never_pass_as_empty_accounting(self):
        scenarios = [([[101], [101, 102]], [1, 1]),
                     ([[101], [101]], [1, 2]),
                     ([[101], [101], []], [1, 1, 2]),
                     ([[101], [101], [102]], [1, 1]),
                     ([[101], [101], []], [1, 1, 1, 2])]
        for snapshots, totals in scenarios:
            with self.subTest(snapshots=snapshots, totals=totals):
                job = self.job(pids=(101,)); job.process_ids.side_effect = snapshots; job.total.side_effect = totals
                owner = self.owner(job)
                with self.assertRaisesRegex(TREE.ProcessTreeError, 'assignments changed'):
                    owner.terminate()
                job.api.CloseHandle.assert_called_once_with(1101)
                job.api.TerminateJobObject.assert_called_once_with(700, 1)
                self.assertFalse(owner.termination_joined)

    def test_membership_identity_failure_stops_job_and_closes_every_pinned_handle(self):
        for failed_query in (False, True):
            with self.subTest(failed_query=failed_query):
                job = self.job(); owner = self.owner(job)
                def membership(handle, exact_job, output):
                    output._obj.value = handle != 1102
                    return not failed_query or handle != 1102
                job.api.IsProcessInJob.side_effect = membership
                with self.assertRaises(TREE.ProcessTreeError):owner.terminate()
                self.assertEqual(job.api.CloseHandle.call_args_list, [mock.call(1101), mock.call(1102)])
                job.api.TerminateJobObject.assert_called_once_with(700, 1)
                job.api.WaitForSingleObject.assert_not_called()

    def test_timeout_or_failed_wait_preserves_uncertainty_and_closes_all_handles(self):
        for state, message in ((0x102, 'deadline exhausted'), (0xffffffff, 'join terminated')):
            with self.subTest(state=state):
                job = self.job(); owner = self.owner(job)
                job.api.WaitForSingleObject.side_effect = [0, state]
                with self.assertRaisesRegex(TREE.ProcessTreeError, message):owner.terminate()
                self.assertEqual(job.api.CloseHandle.call_args_list, [mock.call(1101), mock.call(1102)])
                owner.process.wait.assert_not_called()
                for operation in (owner.terminate, owner.finish, owner.close):
                    with self.assertRaisesRegex(TREE.ProcessTreeError, 'termination remains unconfirmed'):operation()
                self.assertFalse(owner.closed); self.assertFalse(owner.termination_joined)

    def test_close_failure_does_not_hide_original_wait_error_or_skip_other_handles(self):
        job = self.job(); owner = self.owner(job)
        job.api.WaitForSingleObject.return_value = 0x102
        job.api.CloseHandle.side_effect = [False, True]
        with self.assertRaisesRegex(TREE.ProcessTreeError, 'deadline exhausted.*close termination observation') as caught:
            owner.terminate()
        self.assertIsInstance(caught.exception.__cause__, TREE.ProcessTreeError)
        self.assertIn('deadline exhausted', str(caught.exception.__cause__))
        self.assertEqual(job.api.CloseHandle.call_args_list, [mock.call(1101), mock.call(1102)])
        self.assertFalse(owner.termination_joined)

    def test_observation_close_failure_alone_keeps_join_unconfirmed(self):
        job = self.job(); owner = self.owner(job)
        job.api.CloseHandle.side_effect = [False, True]
        with self.assertRaisesRegex(TREE.ProcessTreeError, 'close termination observation'):owner.terminate()
        self.assertFalse(owner.termination_joined)
        self.assertIn('close termination observation', owner.termination_failure)
        self.assertEqual(job.api.CloseHandle.call_count, 2)

    def test_termination_request_failure_closes_handles_and_never_claims_join(self):
        job = self.job(); owner = self.owner(job)
        job.api.TerminateJobObject.return_value = False
        with self.assertRaisesRegex(TREE.ProcessTreeError, 'terminate job'):owner.terminate()
        job.api.WaitForSingleObject.assert_not_called()
        self.assertEqual(job.api.CloseHandle.call_count, 2)
        self.assertFalse(owner.termination_joined)

    def test_parent_wait_and_accounting_share_the_original_deadline(self):
        job = self.job(pids=()); owner = self.owner(job); clock = [10.]
        def wait(timeout):
            self.assertEqual(timeout, 5)
            clock[0] = 16
        owner.process.wait.side_effect = wait; job.active.return_value = 1
        with mock.patch.object(TREE.time, 'monotonic', side_effect=lambda: clock[0]), \
                mock.patch.object(TREE.time, 'sleep') as sleep:
            with self.assertRaisesRegex(TREE.ProcessTreeError, 'deadline exhausted'):owner.terminate(timeout=5)
        sleep.assert_not_called(); self.assertFalse(owner.termination_joined)

    def test_close_cannot_bypass_join_when_parent_and_accounting_look_complete(self):
        job = self.job(); owner = self.owner(job)
        owner.close()
        self.assertTrue(owner.closed); self.assertTrue(owner.termination_joined)
        self.assertEqual(job.api.WaitForSingleObject.call_count, 2)
        self.assertEqual(job.api.CloseHandle.call_args_list, [mock.call(1101), mock.call(1102), mock.call(700)])
        owner.close()
        self.assertEqual(job.api.WaitForSingleObject.call_count, 2)


class WindowsLaunchOrdering(unittest.TestCase):
    def check_order(self, failure=None, environment=None):
        events = []
        class Job:
            def __init__(self):events.append('job')
            def assign(self, process):
                events.append('assign')
                if failure == 'assign':raise TREE.ProcessTreeError('assignment rejected')
            def resume(self, process):
                events.append('resume')
                if failure in ('resume', 'cleanup', 'join'):raise TREE.ProcessTreeError('resume rejected')
            def terminate(self):
                events.append('terminate job')
                if failure == 'cleanup':raise TREE.ProcessTreeError('job termination rejected')
            def terminate_and_wait(self, deadline):
                self.terminate()
                events.append('join job')
                if failure == 'join':raise TREE.ProcessTreeError('descendant join rejected')
            def close(self):events.append('close job')
        process = mock.Mock()
        process.poll.return_value = None
        process.kill.side_effect = lambda: events.append('kill suspended child')
        process.wait.side_effect = lambda **kw: events.append('wait child')
        def create(*args, **kwargs):
            self.assertEqual(kwargs['creationflags'], 0x4)
            self.assertFalse(kwargs['start_new_session'])
            self.assertIs(kwargs['env'],environment)
            events.append('create suspended')
            return process
        with mock.patch.object(TREE.os, 'name', 'nt'), mock.patch.object(TREE, '_WindowsJob', Job), \
                mock.patch.object(TREE.subprocess, 'Popen', side_effect=create):
            if failure:
                with self.assertRaises(TREE.ProcessTreeError):
                    TREE.launch(['program'], '.', None, env=environment)
            else:
                owner = TREE.launch(['program'], '.', None, env=environment)
                self.assertIs(owner.process, process)
        return events

    def test_windows_launch_passes_child_environment_without_changing_order(self):
        self.assertEqual(self.check_order(environment={'GALLIUM_DRIVER':'llvmpipe'}),
                         ['job','create suspended','assign','resume'])

    def test_child_cannot_execute_before_job_assignment(self):
        self.assertEqual(self.check_order(), ['job', 'create suspended', 'assign', 'resume'])

    def test_assignment_failure_never_resumes_and_joins_suspended_process(self):
        events = self.check_order('assign')
        self.assertNotIn('resume', events)
        self.assertEqual(events[-3:], ['kill suspended child', 'wait child', 'close job'])

    def test_resume_failure_still_closes_job_and_joins_child(self):
        events = self.check_order('resume')
        self.assertEqual(events[-5:], ['terminate job', 'join job', 'kill suspended child', 'wait child', 'close job'])

    def test_failed_descendant_join_still_attempts_primary_stop_wait_and_job_close(self):
        events = self.check_order('join')
        self.assertEqual(events[-5:], ['terminate job', 'join job', 'kill suspended child', 'wait child', 'close job'])

    def test_failed_cleanup_still_attempts_child_stop_join_and_job_close(self):
        events = self.check_order('cleanup')
        self.assertEqual(events[-3:], ['kill suspended child', 'wait child', 'close job'])


@unittest.skipUnless(sys.platform.startswith('linux'), 'requires private Linux child-subreaper')
class LinuxSubreaper(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='nested-owner-')
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.log = self.root / 'console.log'
        self.stream = self.log.open('wb')
        self.addCleanup(self.stream.close)

    def launch(self, body):
        owner = TREE.launch([sys.executable, '-B', '-c', body], self.root, self.stream)
        self.addCleanup(owner.close)
        return owner

    def wait_file(self, name):
        path = self.root / name
        until = time.monotonic() + 10
        while not path.exists() or not path.read_text():
            if time.monotonic() > until:
                self.fail('nested command did not become ready')
            time.sleep(0.01)
        return int(path.read_text())

    def assert_gone(self, *pids):
        for pid in pids:
            self.assertFalse(Path('/proc', str(pid)).exists(), 'descendant was not reaped: ' + str(pid))

    def test_parent_success_with_new_session_writer_is_rejected_and_reaped(self):
        writer = "import os,time;from pathlib import Path;Path('writer.pid').write_text(str(os.getpid()));time.sleep(1);print('late');time.sleep(30)"
        body = ("import subprocess,sys,time;from pathlib import Path;"
                "subprocess.Popen([sys.executable,'-B','-c'," + repr(writer) + "],start_new_session=True)\n"
                "while not Path('writer.pid').exists():time.sleep(0.01)\n")
        owner = self.launch(body)
        pid = self.wait_file('writer.pid')
        self.assertEqual(owner.wait(timeout=10), 0)
        with self.assertRaisesRegex(TREE.ProcessTreeError, 'descendants outlived'):
            owner.finish()
        self.assert_gone(pid)
        self.assertNotIn(b'late', self.log.read_bytes())

    def test_timeout_reaps_nested_supervisor_and_new_session_descendants(self):
        writer = "import os,time;from pathlib import Path;Path('writer.pid').write_text(str(os.getpid()));time.sleep(30)"
        inner = ("import os,subprocess,sys,time;from pathlib import Path;Path('inner.pid').write_text(str(os.getpid()));"
                 "subprocess.Popen([sys.executable,'-B','-c'," + repr(writer) + "],start_new_session=True);time.sleep(30)")
        body = ("import sys,time;from pathlib import Path;sys.path.insert(0," + repr(str(ROOT/'tools')) + ");"
                "import process_tree;owner=process_tree.launch([sys.executable,'-B','-c'," + repr(inner) + "],'.',sys.stdout);"
                "Path('supervisor.pid').write_text(str(owner.process.pid));time.sleep(30)")
        owner = self.launch(body)
        pids = [self.wait_file(name) for name in ('writer.pid', 'inner.pid', 'supervisor.pid')]
        owner.terminate(timeout=10)
        self.assertIsNotNone(owner.finish())
        self.assert_gone(*pids)

    def test_actual_coverage_timeout_stops_detached_session_writer(self):
        spec = importlib.util.spec_from_file_location('supervisor_coverage', ROOT/'tools/coverage.py')
        coverage = importlib.util.module_from_spec(spec);spec.loader.exec_module(coverage)
        writer = "import os,time;from pathlib import Path;Path('writer.pid').write_text(str(os.getpid()));time.sleep(2);print('late');time.sleep(30)"
        body = ("import subprocess,sys,time;subprocess.Popen([sys.executable,'-B','-c'," + repr(writer) +
                "],start_new_session=True);time.sleep(30)")
        plan = coverage.freeze({'schema_version':1,'mode':'diagnostic',
            'subject':{key:'a'*64 for key in ('source_sha256','inventory_sha256','configuration_sha256')},
            'inputs':{},'checks':[{'id':'nested','scope':'fixture','target':'linux-x86_64','environment':'fixture',
                'backend':'core','required':True,'argv':['{python}','-B','-c',body],
                'timeout_seconds':0.6,'warning_seconds':0.3,'expected_tests':[]}]})
        result = coverage.run_case(plan,'nested',self.root,self.root/'evidence','nested-run',1)
        self.assertEqual(result['status'],'incomplete')
        self.assert_gone(self.wait_file('writer.pid'))
        saved = (self.root/'evidence/console.log').read_bytes()
        time.sleep(0.1)
        self.assertEqual((self.root/'evidence/console.log').read_bytes(),saved)
        self.assertNotIn(b'late',saved)

    def test_subreaper_setting_is_private_to_supervisor(self):
        import ctypes
        api = ctypes.CDLL(None)
        before, after = ctypes.c_int(), ctypes.c_int()
        self.assertEqual(api.prctl(37, ctypes.byref(before), 0, 0, 0), 0)
        owner = self.launch('pass');owner.wait(timeout=10);owner.finish()
        self.assertEqual(api.prctl(37, ctypes.byref(after), 0, 0, 0), 0)
        self.assertEqual(before.value, after.value)

    def test_caller_exit_requests_private_supervisor_cleanup(self):
        writer = "import os,time;from pathlib import Path;Path('writer.pid').write_text(str(os.getpid()));time.sleep(30)"
        caller = ("import os,sys,time;from pathlib import Path;sys.path.insert(0," + repr(str(ROOT/'tools')) + ");"
                  "import process_tree;owner=process_tree.launch([sys.executable,'-B','-c'," + repr(writer) + "],'.',sys.stdout)\n"
                  "while not Path('writer.pid').exists():time.sleep(0.01)\n"
                  "Path('supervisor.pid').write_text(str(owner.process.pid));os._exit(0)")
        body = ("import subprocess,sys,time;from pathlib import Path;subprocess.run([sys.executable,'-B','-c'," + repr(caller) + "],check=True)\n"
                "deadline=time.monotonic()+5\n"
                "while any(Path('/proc',Path(name).read_text()).exists() for name in ('writer.pid','supervisor.pid')):\n"
                " if time.monotonic()>deadline:raise RuntimeError('caller exit left writer alive')\n"
                " time.sleep(0.01)\n")
        owner=self.launch(body)
        self.assertEqual(owner.wait(timeout=10),0)
        # The outer owner also reaps any already-exited adopted supervisor.
        owner.finish()
        self.assert_gone(self.wait_file('writer.pid'),self.wait_file('supervisor.pid'))

    def test_missing_command_is_a_failed_launch_with_confirmed_cleanup(self):
        owner = TREE.launch([str(self.root/'absent-program')], self.root, self.stream)
        self.addCleanup(owner.close)
        self.assertEqual(owner.wait(timeout=10),125)
        with self.assertRaisesRegex(TREE.ProcessTreeError,'supervisor launch failed'):
            owner.finish()
        self.assertFalse(owner._live())

    def test_large_launch_diagnostic_cannot_block_completion_pipe(self):
        owner = TREE.launch([str(self.root/('é'*2000))],self.root,self.stream)
        self.addCleanup(owner.close)
        self.assertEqual(owner.wait(timeout=10),125)
        with self.assertRaisesRegex(TREE.ProcessTreeError,'bounded diagnostic'):
            owner.finish()
        self.assertFalse(owner._live())


class SupervisorBoundary(unittest.TestCase):
    def test_other_posix_platforms_do_not_fall_back_to_escaping_groups(self):
        with mock.patch.object(TREE.os,'name','posix'), mock.patch.object(TREE.sys,'platform','darwin'), \
                mock.patch.object(TREE.subprocess,'Popen') as child:
            with self.assertRaisesRegex(TREE.ProcessTreeError,'no qualified process supervisor'):
                TREE.launch(['program'],'.',None)
            child.assert_not_called()

    def test_missing_completion_receipt_remains_uncertain_on_repeated_observation(self):
        incoming,outgoing=os.pipe();os.close(outgoing)
        process=mock.Mock(returncode=0);process.poll.return_value=0
        proxy=TREE._LinuxProcess(process,incoming,['program'])
        for _ in range(2):
            with self.assertRaisesRegex(TREE.ProcessTreeError,'completion uncertain'):
                proxy.poll()


if __name__ == '__main__':
    unittest.main()
