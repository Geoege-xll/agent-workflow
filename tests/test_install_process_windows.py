from __future__ import annotations

import ctypes
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import Mock, patch

from lib import install_process, windows_process as win
from lib.install_process import CANCEL_FILE_ENV, SetupRunError, SetupRunner


ROOT = Path(__file__).resolve().parents[1]


class FakeWin32:
    """Exercise the real ctypes setup/Job owner without loading kernel32."""

    def __init__(self, fail=None, active=(0,), exitcode=37, missing_stdin=False):
        self.fail = fail
        self.events = []
        self.closed = []
        self.active = list(active)
        self.after_stop = [2, 1, 0]
        self.terminated = False
        self.exitcode = exitcode
        self.missing_stdin = missing_stdin
        self.interrupt_on_create = False
        self.allowed = None
        self.startup = None
        self.creation = None

    def error(self, operation):
        return OSError(5, operation)

    def record(self, name):
        self.events.append(name)
        return self.fail != name

    def CreateJobObjectW(self, security, name):
        return 200 if self.record("create_job") else None

    def SetInformationJobObject(self, job, kind, data, size):
        self.limits = ctypes.cast(data, ctypes.POINTER(win.JOBOBJECT_EXTENDED_LIMIT_INFORMATION)).contents
        return self.record("set_limits")

    def GetCurrentProcess(self):
        return -1

    def GetStdHandle(self, number):
        number = ctypes.c_int32(number).value
        return None if self.missing_stdin and number == -10 else -number

    def CreateFileW(self, name, access, share, security, disposition, flags, template):
        self.nul = (name, access, share, security, disposition)
        self.record("open_nul")
        return 50

    def DuplicateHandle(self, source_process, source, target_process, output, access, inherit, options):
        self.events.append(("duplicate", source, inherit, options))
        if self.fail == "duplicate":
            return False
        ctypes.cast(output, ctypes.POINTER(win.HANDLE))[0] = source + 1000
        return True

    def InitializeProcThreadAttributeList(self, attributes, count, flags, size):
        ctypes.cast(size, ctypes.POINTER(win.SIZE_T))[0] = 64
        if attributes is None:
            self.record("size_attributes")
            return False
        return self.record("initialize_attributes")

    def UpdateProcThreadAttribute(self, attributes, flags, kind, values, size, previous, returned):
        self.attribute_kind = kind
        self.allowed = list(ctypes.cast(values, ctypes.POINTER(win.HANDLE))[:size // ctypes.sizeof(win.HANDLE)])
        return self.record("restrict_handles")

    def DeleteProcThreadAttributeList(self, attributes):
        self.record("delete_attributes")

    def CreateProcessW(self, executable, command, process_security, thread_security, inherit, flags,
                       environment, cwd, startup, information):
        self.creation = {
            "executable": executable, "command": command.value,
            "inherit": inherit, "flags": flags, "cwd": cwd,
            "environment": None if environment is None else "".join(environment),
        }
        incoming = ctypes.cast(startup, ctypes.POINTER(win.STARTUPINFOEXW)).contents
        self.startup = {
            "cb": incoming.StartupInfo.cb,
            "flags": incoming.StartupInfo.dwFlags,
            "handles": [incoming.StartupInfo.hStdInput, incoming.StartupInfo.hStdOutput,
                        incoming.StartupInfo.hStdError],
            "attributes": incoming.lpAttributeList,
        }
        if not self.record("create_suspended"):
            return False
        result = ctypes.cast(information, ctypes.POINTER(win.PROCESS_INFORMATION)).contents
        result.hProcess, result.hThread, result.dwProcessId = 100, 101, 9001
        if self.interrupt_on_create:
            signal.getsignal(signal.SIGINT)(signal.SIGINT, None)
        return True

    def AssignProcessToJobObject(self, job, process):
        return self.record("assign_job")

    def ResumeThread(self, thread):
        return 1 if self.record("resume") else win.DWORD(-1).value

    def TerminateJobObject(self, job, exitcode):
        if not self.record("terminate_job"):
            return False
        self.terminated = True
        return True

    def QueryInformationJobObject(self, job, kind, data, size, returned):
        if not self.record("query_active"):
            return False
        values = self.after_stop if self.terminated else self.active
        count = values[0]
        if len(values) > 1:
            values.pop(0)
        output = ctypes.cast(data, ctypes.POINTER(win.JOBOBJECT_BASIC_ACCOUNTING_INFORMATION)).contents
        output.ActiveProcesses = count
        return True

    def TerminateProcess(self, process, exitcode):
        return self.record("discard_suspended")

    def WaitForSingleObject(self, process, timeout):
        self.record("wait_root")
        return win.WAIT_OBJECT_0

    def GetExitCodeProcess(self, process, output):
        ctypes.cast(output, ctypes.POINTER(win.DWORD))[0] = self.exitcode
        return self.record("exitcode")

    def CloseHandle(self, handle):
        self.closed.append(handle)
        self.events.append(("close", handle))
        return True


class WindowsCtypesBackendTest(unittest.TestCase):
    def launch(self, api, command=None, cwd="C:\\项目 space", env=None):
        with patch.object(win, "_Win32API", return_value=api):
            return win.WindowsJobProcess(command or ["C:\\Git\\bin\\bash.exe", "--noprofile"], cwd, env)

    def test_windows_abi_sizes_on_64_bit_test_hosts(self):
        self.assertEqual(4, ctypes.sizeof(win.DWORD))
        self.assertEqual(2, ctypes.sizeof(win.WORD))
        self.assertEqual(48, ctypes.sizeof(win.IO_COUNTERS))
        self.assertEqual(48, ctypes.sizeof(win.JOBOBJECT_BASIC_ACCOUNTING_INFORMATION))
        if ctypes.sizeof(ctypes.c_void_p) == 8:
            self.assertEqual(64, ctypes.sizeof(win.JOBOBJECT_BASIC_LIMIT_INFORMATION))
            self.assertEqual(144, ctypes.sizeof(win.JOBOBJECT_EXTENDED_LIMIT_INFORMATION))
            self.assertEqual(104, ctypes.sizeof(win.STARTUPINFOW))
            self.assertEqual(112, ctypes.sizeof(win.STARTUPINFOEXW))
            self.assertEqual(24, ctypes.sizeof(win.PROCESS_INFORMATION))
            self.assertEqual(80, win.STARTUPINFOW.hStdInput.offset)
            self.assertEqual(104, win.STARTUPINFOEXW.lpAttributeList.offset)

    def test_suspended_assign_resume_and_explicit_handle_allowlist(self):
        api = FakeWin32(exitcode=0)
        process = self.launch(api)
        self.assertLess(api.events.index("create_suspended"), api.events.index("assign_job"))
        self.assertLess(api.events.index("assign_job"), api.events.index("resume"))
        self.assertEqual(win.CREATE_SUSPENDED | win.CREATE_UNICODE_ENVIRONMENT |
                         win.EXTENDED_STARTUPINFO_PRESENT, api.creation["flags"])
        self.assertTrue(api.creation["inherit"])
        self.assertEqual(win.JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE, api.limits.BasicLimitInformation.LimitFlags)
        self.assertEqual(win.PROC_THREAD_ATTRIBUTE_HANDLE_LIST, api.attribute_kind)
        self.assertEqual([1010, 1011, 1012], api.allowed)
        self.assertEqual(api.allowed, api.startup["handles"])
        self.assertEqual(win.STARTF_USESTDHANDLES, api.startup["flags"])
        self.assertEqual(ctypes.sizeof(win.STARTUPINFOEXW), api.startup["cb"])
        self.assertTrue(api.startup["attributes"])
        self.assertNotIn(10, api.closed)  # stdin pipe/console belongs to the caller
        self.assertNotIn(11, api.closed)
        self.assertNotIn(12, api.closed)
        self.assertNotIn(200, api.allowed)  # Job handle cannot escape to children
        self.assertEqual(0, process.wait())
        process.close()
        self.assertEqual(1, api.closed.count(100))
        self.assertEqual(1, api.closed.count(101))
        self.assertEqual(1, api.closed.count(200))

    def test_unicode_command_cwd_env_and_exitcode_are_preserved(self):
        api = FakeWin32(exitcode=3010)
        command = ["C:\\程序 space\\python.exe", "", '引号 " 与 \\', "尾巴\\"]
        env = {"z": "中文值", "PATH": "C:\\工具 space", "=C:": "C:\\项目"}
        process = self.launch(api, command, "C:\\项目 & 工作", env)
        self.assertEqual(subprocess.list2cmdline(command), api.creation["command"])
        self.assertEqual("C:\\项目 & 工作", api.creation["cwd"])
        self.assertEqual("=C:=C:\\项目\0PATH=C:\\工具 space\0z=中文值\0\0", api.creation["environment"])
        self.assertEqual(3010, process.wait())
        process.close()

    def test_environment_inheritance_and_empty_block(self):
        self.assertIsNone(win._environment_block(None))
        self.assertEqual("\0\0", "".join(win._environment_block({})))
        for env in ({"A=B": "v"}, {"": "v"}, {"A": "a\0b"}, {"Path": "a", "PATH": "b"}):
            with self.subTest(env=env), self.assertRaises(ValueError):
                win._environment_block(env)

    def test_missing_stdin_uses_nul_but_valid_stdin_is_never_closed(self):
        api = FakeWin32(missing_stdin=True)
        process = self.launch(api)
        self.assertEqual(("NUL", 0x80000000, 3, None, 3), api.nul)
        self.assertEqual(1050, api.startup["handles"][0])
        self.assertIn(50, api.closed)
        process.wait()
        process.close()

    def test_unavailable_job_never_creates_or_resumes_a_process(self):
        for failure in ("create_job", "set_limits", "duplicate", "initialize_attributes", "restrict_handles"):
            api = FakeWin32(fail=failure)
            with self.subTest(failure=failure), self.assertRaises(OSError):
                self.launch(api)
            self.assertNotIn("create_suspended", api.events)
            self.assertNotIn("resume", api.events)

    def test_assignment_failure_discards_only_a_still_suspended_process(self):
        api = FakeWin32(fail="assign_job")
        with self.assertRaises(OSError):
            self.launch(api)
        self.assertNotIn("resume", api.events)
        self.assertIn("discard_suspended", api.events)
        self.assertIn("wait_root", api.events)
        self.assertIn(100, api.closed)
        self.assertIn(200, api.closed)

    def test_failed_resume_terminates_and_drains_job(self):
        api = FakeWin32(fail="resume", active=(2,))
        with patch.object(win.time, "sleep"), self.assertRaises(OSError):
            self.launch(api)
        self.assertIn("terminate_job", api.events)
        self.assertNotIn("discard_suspended", api.events)
        self.assertEqual(3, api.events.count("query_active"))
        self.assertLess(api.events.index("exitcode"), api.events.index(("close", 200)))

    def test_wait_observes_grandchildren_not_just_root_exit(self):
        api = FakeWin32(active=(2, 1, 0), exitcode=17)
        process = self.launch(api)
        with patch.object(win.time, "sleep") as pause:
            self.assertEqual(17, process.wait())
        self.assertEqual(2, pause.call_count)
        self.assertEqual(3, api.events.count("query_active"))
        self.assertGreater(api.events.index("wait_root"), api.events.index("query_active"))
        process.close()
        self.assertNotIn("terminate_job", api.events)

    def test_timeout_then_stop_waits_for_active_count_zero(self):
        api = FakeWin32(active=(2,))
        process = self.launch(api)
        with self.assertRaises(subprocess.TimeoutExpired):
            process.wait(timeout=0)
        with patch.object(win.time, "sleep") as pause:
            process.stop()
        self.assertEqual(2, pause.call_count)
        self.assertEqual(4, api.events.count("query_active"))
        self.assertEqual(37, process.returncode)
        process.close()
        self.assertEqual(1, api.events.count("terminate_job"))

    def test_cleanup_failure_is_outside_transaction_recovery_exception_types(self):
        for failure in ("terminate_job", "query_active"):
            api = FakeWin32(active=(2,), fail=failure)
            process = self.launch(api)
            before = signal.getsignal(signal.SIGINT)
            try:
                with self.subTest(failure=failure), self.assertRaises(win.WindowsJobCleanupError) as raised:
                    process.stop()
                self.assertNotIsInstance(raised.exception, (Exception, OSError, ValueError, KeyboardInterrupt))
                self.assertEqual(signal.SIG_IGN, signal.getsignal(signal.SIGINT))
            finally:
                # This is a deliberately fatal production path; reset the test
                # interpreter and release fake handles, not real processes.
                signal.signal(signal.SIGINT, before)
                process._close_handles()

    def test_embedded_nul_never_truncates_command_or_cwd_into_another_command(self):
        api = FakeWin32()
        with self.assertRaises(ValueError):
            self.launch(api, command=["program.exe", "argument\0truncated"])
        with self.assertRaises(ValueError):
            self.launch(api, command="program.exe\0truncated")
        with self.assertRaises(ValueError):
            self.launch(api, cwd="C:\\project\0other")
        self.assertNotIn("create_suspended", api.events)

    def test_sigint_during_create_cannot_orphan_started_job(self):
        api = FakeWin32(active=(1,))
        api.interrupt_on_create = True
        before = signal.getsignal(signal.SIGINT)
        with patch.object(win.time, "sleep"), self.assertRaises(KeyboardInterrupt):
            self.launch(api)
        self.assertIn("assign_job", api.events)
        self.assertIn("terminate_job", api.events)
        self.assertEqual(3, api.events.count("query_active"))
        self.assertIn(200, api.closed)
        self.assertEqual(before, signal.getsignal(signal.SIGINT))

    def test_recovery_sigint_ignore_is_not_overridden_during_create(self):
        before = signal.getsignal(signal.SIGINT)
        signal.signal(signal.SIGINT, signal.SIG_IGN)
        try:
            with win._defer_interrupts():
                self.assertEqual(signal.SIG_IGN, signal.getsignal(signal.SIGINT))
        finally:
            signal.signal(signal.SIGINT, before)


class SetupRunnerWindowsTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="workflow-process-unit-")
        self.root = Path(self.temp.name)
        self.cancel = self.root / "cancel"
        self.command = ["fixture.exe", "中文 argument"]
        self.backend = Mock()
        self.backend.args = self.command
        self.backend.wait.return_value = 0
        self.environment = patch.dict(os.environ)
        self.environment.start()
        os.environ.pop(CANCEL_FILE_ENV, None)

    def tearDown(self):
        self.environment.stop()
        self.temp.cleanup()

    def run_windows(self, runner, env=None):
        with patch.object(install_process.os, "name", "nt"), \
                patch.object(install_process, "WindowsJobProcess", return_value=self.backend) as constructor:
            runner.run(self.command, str(self.root), env=env)
        return constructor

    def test_optional_env_and_legacy_two_argument_call(self):
        env = {"PATH": "fixture", "WORKFLOW_TEST": "中文"}
        constructor = self.run_windows(SetupRunner(), env)
        constructor.assert_called_once_with(self.command, cwd=str(self.root), env=env)
        constructor = self.run_windows(SetupRunner())
        constructor.assert_called_once_with(self.command, cwd=str(self.root))
        self.assertEqual(2, self.backend.close.call_count)

    def test_original_posix_spawn_contract_and_optional_env(self):
        process = Mock()
        process.wait.return_value = 0
        with patch.object(install_process.os, "name", "posix"), \
                patch.object(install_process.subprocess, "Popen", return_value=process) as spawn:
            SetupRunner().run(self.command, str(self.root))
            spawn.assert_called_once_with(self.command, cwd=str(self.root), start_new_session=True)
            spawn.reset_mock()
            env = {"WORKFLOW_TEST": "中文"}
            SetupRunner().run(self.command, str(self.root), env=env)
            spawn.assert_called_once_with(self.command, cwd=str(self.root), start_new_session=True, env=env)

    def test_preserves_nonzero_root_exitcode(self):
        self.backend.wait.return_value = 3010
        with self.assertRaises(subprocess.CalledProcessError) as raised:
            self.run_windows(SetupRunner())
        self.assertEqual(3010, raised.exception.returncode)
        self.assertEqual(self.command, raised.exception.cmd)
        self.backend.close.assert_called_once()
        self.backend.stop.assert_not_called()

    def test_cancellation_before_spawn_starts_no_writer(self):
        os.environ[CANCEL_FILE_ENV] = str(self.cancel)
        self.cancel.touch()
        with patch.object(install_process, "WindowsJobProcess") as constructor, \
                patch.object(install_process.subprocess, "Popen") as spawn, \
                self.assertRaisesRegex(SetupRunError, "取消"):
            SetupRunner().run(self.command, str(self.root))
        constructor.assert_not_called()
        spawn.assert_not_called()

    def test_cancel_file_stops_and_closes_entire_job_before_returning(self):
        os.environ[CANCEL_FILE_ENV] = str(self.cancel)
        cancel = str(self.cancel)

        def wait(timeout):
            with open(cancel, "x"):
                pass
            raise subprocess.TimeoutExpired(self.command, timeout)

        self.backend.wait.side_effect = wait
        with self.assertRaisesRegex(SetupRunError, "取消"):
            self.run_windows(SetupRunner())
        self.assertEqual(["wait", "stop", "close"], [call[0] for call in self.backend.mock_calls])

    def test_keyboard_interrupt_stops_job_before_returning(self):
        self.backend.wait.side_effect = KeyboardInterrupt()
        with self.assertRaisesRegex(SetupRunError, "取消"):
            self.run_windows(SetupRunner())
        self.backend.stop.assert_called_once()
        self.backend.close.assert_called_once()

    def test_sigint_between_constructor_return_and_wait_is_cleaned_up(self):
        def create(*args, **kwargs):
            signal.getsignal(signal.SIGINT)(signal.SIGINT, None)
            return self.backend

        with patch.object(install_process.os, "name", "nt"), \
                patch.object(install_process, "WindowsJobProcess", side_effect=create), \
                self.assertRaisesRegex(SetupRunError, "取消"):
            SetupRunner().run(self.command, str(self.root))
        self.backend.wait.assert_not_called()
        self.backend.stop.assert_called_once()
        self.backend.close.assert_called_once()

    def test_timeout_stops_and_closes_entire_job(self):
        self.backend.wait.side_effect = subprocess.TimeoutExpired(self.command, 1)
        with self.assertRaisesRegex(SetupRunError, "超时"):
            self.run_windows(SetupRunner(timeout=1))
        self.backend.stop.assert_called_once()
        self.backend.close.assert_called_once()

    def test_unavailable_job_has_no_popen_or_parent_kill_fallback(self):
        with patch.object(install_process.os, "name", "nt"), \
                patch.object(install_process, "WindowsJobProcess", side_effect=OSError("job unavailable")), \
                patch.object(install_process.subprocess, "Popen") as spawn, \
                self.assertRaisesRegex(SetupRunError, "不会降级"):
            SetupRunner().run(self.command, str(self.root))
        spawn.assert_not_called()

    def test_query_error_stops_job_before_recovery_can_catch_error(self):
        self.backend.wait.side_effect = OSError("job query failed")
        with self.assertRaises(OSError):
            self.run_windows(SetupRunner())
        self.backend.stop.assert_called_once()
        self.backend.close.assert_called_once()

    def test_unconfirmed_cleanup_does_not_become_recoverable_setup_error(self):
        self.backend.wait.side_effect = subprocess.TimeoutExpired(self.command, 1)
        self.backend.stop.side_effect = win.WindowsJobCleanupError("not empty")
        with self.assertRaises(win.WindowsJobCleanupError):
            self.run_windows(SetupRunner(timeout=1))
        self.backend.close.assert_called_once()

    def test_fatal_constructor_cleanup_keeps_sigint_ignored_through_outer_guard(self):
        api = FakeWin32(fail="terminate_job", active=(1,))
        api.interrupt_on_create = True
        before = signal.getsignal(signal.SIGINT)
        try:
            with patch.object(install_process.os, "name", "nt"), \
                    patch.object(win, "_Win32API", return_value=api), \
                    self.assertRaises(win.WindowsJobCleanupError):
                SetupRunner().run(self.command, str(self.root))
            self.assertIn("assign_job", api.events)
            self.assertIn("resume", api.events)
            self.assertIn("terminate_job", api.events)
            self.assertEqual(signal.SIG_IGN, signal.getsignal(signal.SIGINT))
        finally:
            signal.signal(signal.SIGINT, before)

    def test_recovery_ignores_cancel_file_and_has_independent_600_second_budget(self):
        os.environ[CANCEL_FILE_ENV] = str(self.cancel)
        self.cancel.touch()
        before = signal.getsignal(signal.SIGINT)
        with patch.object(install_process.time, "monotonic", return_value=100):
            runner = SetupRunner(timeout=1)
        try:
            with patch.object(install_process.time, "monotonic", return_value=1000):
                runner.begin_recovery()
            self.assertEqual(1600, runner.deadline)
            self.assertEqual(signal.SIG_IGN, signal.getsignal(signal.SIGINT))
            with patch.object(install_process.time, "monotonic", return_value=1001):
                self.run_windows(runner)
            self.backend.wait.assert_called_once_with(timeout=599)
            self.backend.stop.assert_not_called()
        finally:
            runner.close()
        self.assertEqual(before, signal.getsignal(signal.SIGINT))

    def test_expired_budget_rejects_next_phase_before_spawn(self):
        with patch.object(install_process.time, "monotonic", return_value=100):
            runner = SetupRunner(timeout=1)
        with patch.object(install_process.time, "monotonic", return_value=102), \
                patch.object(install_process, "WindowsJobProcess") as constructor, \
                patch.object(install_process.subprocess, "Popen") as spawn, \
                self.assertRaisesRegex(SetupRunError, "尚未启动"):
            runner.run(self.command, str(self.root))
        constructor.assert_not_called()
        spawn.assert_not_called()


@unittest.skipUnless(os.name == "posix", "POSIX regression for the real optional cancellation-file channel")
class PosixCancelFileRegressionTest(unittest.TestCase):
    def test_real_cancel_file_stops_descendant_and_recovery_ignores_it(self):
        with tempfile.TemporaryDirectory(prefix="workflow-posix-cancel-file-") as raw:
            root = Path(raw)
            ready, late, cancel = (root / name for name in ("ready", "late", "cancel"))
            child = (
                "import time;from pathlib import Path;"
                f"Path({str(ready)!r}).write_text('ready');"
                f"time.sleep(.8);Path({str(late)!r}).write_text('late')"
            )
            parent = (
                "import subprocess,sys,time;"
                f"subprocess.Popen([sys.executable,'-B','-c',{child!r}]);"
                "time.sleep(30)"
            )
            observed = []

            def request_cancel():
                deadline = time.monotonic() + 5
                while not ready.exists() and time.monotonic() < deadline:
                    time.sleep(0.01)
                observed.append(ready.exists())
                cancel.touch()

            with patch.dict(os.environ, {CANCEL_FILE_ENV: str(cancel)}):
                runner = SetupRunner(timeout=10)
                thread = threading.Thread(target=request_cancel)
                thread.start()
                try:
                    with self.assertRaisesRegex(SetupRunError, "取消"):
                        runner.run([sys.executable, "-B", "-c", parent], root)
                    runner.begin_recovery()
                    runner.run([sys.executable, "-B", "-c", "pass"], root)
                finally:
                    runner.close()
                    thread.join(timeout=6)
            self.assertEqual([True], observed)
            time.sleep(.9)
            self.assertFalse(late.exists())


@unittest.skipUnless(os.name == "nt", "requires native Windows Job Objects; not native-tested on macOS")
class NativeWindowsJobTest(unittest.TestCase):
    def tree(self, root):
        late = root / "late-write"
        ready = root / "grandchild-ready"
        grandchild = (
            "import time;from pathlib import Path;"
            f"Path({str(ready)!r}).write_text('ready');"
            f"time.sleep(3);Path({str(late)!r}).write_text('late')"
        )
        child = (
            "import subprocess,sys,time;"
            f"subprocess.Popen([sys.executable,'-B','-c',{grandchild!r}]);"
            "time.sleep(30)"
        )
        # The initial process exits while its child and grandchild keep running.
        # Waiting only for this root would incorrectly report setup success.
        parent = "import subprocess,sys;" + f"subprocess.Popen([sys.executable,'-B','-c',{child!r}])"
        return [sys.executable, "-B", "-c", parent], ready, late

    def test_timeout_drains_child_and_grandchild_before_recovery(self):
        with tempfile.TemporaryDirectory(prefix="workflow-native-timeout-") as raw:
            root = Path(raw)
            command, ready, late = self.tree(root)
            with patch.dict(os.environ):
                os.environ.pop(CANCEL_FILE_ENV, None)
                runner = SetupRunner(timeout=1.5)
                try:
                    with self.assertRaisesRegex(SetupRunError, "超时"):
                        runner.run(command, root)
                    self.assertTrue(ready.exists(), "fixture grandchild never started before the timeout")
                    runner.begin_recovery()
                    runner.run([sys.executable, "-B", "-c", "pass"], root)
                finally:
                    runner.close()
            time.sleep(3.1)
            self.assertFalse(late.exists(), "grandchild wrote after setup cleanup/recovery returned")

    def test_cancel_file_drains_tree_and_does_not_cancel_recovery(self):
        with tempfile.TemporaryDirectory(prefix="workflow-native-cancel-") as raw:
            root = Path(raw)
            command, ready, late = self.tree(root)
            cancel = root / "cancel"
            observed = []

            def cancel_when_ready():
                deadline = time.monotonic() + 8
                while not ready.exists() and time.monotonic() < deadline:
                    time.sleep(0.02)
                observed.append(ready.exists())
                cancel.touch()

            with patch.dict(os.environ, {CANCEL_FILE_ENV: str(cancel)}):
                runner = SetupRunner(timeout=10)
                thread = threading.Thread(target=cancel_when_ready)
                thread.start()
                try:
                    with self.assertRaisesRegex(SetupRunError, "取消"):
                        runner.run(command, root)
                    runner.begin_recovery()
                    runner.run([sys.executable, "-B", "-c", "pass"], root)
                finally:
                    runner.close()
                    thread.join(timeout=10)
            self.assertEqual([True], observed)
            time.sleep(3.1)
            self.assertFalse(late.exists(), "grandchild survived Job cancellation")

    def test_unicode_arguments_cwd_environment_and_redirected_stdin_stdout_stderr(self):
        with tempfile.TemporaryDirectory(prefix="workflow-native-stdio-") as raw:
            root = Path(raw) / "中文 space & 项目"
            root.mkdir()
            arguments = ["", "中文值", 'with "quotes"', "trailing\\"]
            child = (
                "import json,os,sys;"
                "print(json.dumps([sys.argv[1:],os.getcwd(),os.environ['AW_TEST'],sys.stdin.read()]));"
                "print('stderr-marker',file=sys.stderr)"
            )
            outer = (
                "import os,sys;"
                f"sys.path.insert(0,{str(ROOT)!r});"
                "from lib.install_process import SetupRunner;"
                "env=dict(os.environ,AW_TEST='环境值');"
                f"SetupRunner(timeout=15).run([sys.executable,'-B','-X','utf8','-c',{child!r},*{arguments!r}],{str(root)!r},env=env)"
            )
            result = subprocess.run(
                [sys.executable, "-B", "-X", "utf8", "-c", outer], cwd=root,
                input="stdin survives\n中文\n", text=True, encoding="utf-8",
                capture_output=True, timeout=25,
            )
            self.assertEqual(0, result.returncode, result.stderr)
            self.assertEqual([arguments, str(root), "环境值", "stdin survives\n中文\n"], json.loads(result.stdout))
            self.assertIn("stderr-marker", result.stderr)

    def test_native_exitcode_is_preserved(self):
        with tempfile.TemporaryDirectory(prefix="workflow-native-exitcode-") as raw:
            with self.assertRaises(subprocess.CalledProcessError) as raised:
                SetupRunner(timeout=10).run([sys.executable, "-B", "-c", "raise SystemExit(37)"], raw)
            self.assertEqual(37, raised.exception.returncode)


if __name__ == "__main__":
    unittest.main()
