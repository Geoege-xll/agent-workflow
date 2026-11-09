from __future__ import annotations

import ctypes
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import textwrap
import threading
import time
import unittest
from unittest.mock import Mock, patch

from lib.install import install_process
from lib.install import windows_process as win
from lib.install.install_process import CANCEL_FILE_ENV, SetupRunError, SetupRunner


ROOT = Path(__file__).resolve().parents[1]


class FakeWin32:
    """Exercise the real ctypes setup/Job owner without loading kernel32."""

    def __init__(self, fail=None, active=(0,), exitcode=37, missing_stdin=False,
                 members=(9001,), total=None):
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
        self.members = members
        self.total = len(members) if total is None else total
        self.process_handles = {100: 9001}
        self.next_process_handle = 300
        self.pending_members = set()
        self.notifications = []
        self.last_error = 5

    def error(self, operation):
        error = OSError(self.last_error, operation)
        error.winerror = self.last_error
        return error

    def record(self, name):
        self.events.append(name)
        return self.fail != name

    def CreateJobObjectW(self, security, name):
        return 200 if self.record("create_job") else None

    def SetInformationJobObject(self, job, kind, data, size):
        if kind == win.JobObjectAssociateCompletionPortInformation:
            port = win.JOBOBJECT_ASSOCIATE_COMPLETION_PORT.from_buffer_copy(ctypes.string_at(data, size))
            self.completion_key, self.completion_port = port.CompletionKey, port.CompletionPort
            return self.record("associate_port")
        # Win32 在调用时同步消费结构体；fake 也必须复制值，不能把 .contents
        # 的借用视图保存到 _start 返回之后。生产局部缓冲区释放后该视图会读到
        # 被复用的内存（本轮限值 8192 曾读成 103），造成与启动合同无关的随机失败。
        self.limits = win.JOBOBJECT_EXTENDED_LIMIT_INFORMATION.from_buffer_copy(
            ctypes.string_at(data, size))
        return self.record("set_limits")

    def CreateIoCompletionPort(self, file_handle, existing, key, concurrency):
        self.port_creation = (file_handle, existing, key, concurrency)
        return 201 if self.record("create_port") else None

    def GetQueuedCompletionStatus(self, port, code, key, value, milliseconds):
        self.events.append(("read_notification", port, milliseconds))
        if self.fail == "read_notification":
            self.last_error = 6
            ctypes.cast(value, ctypes.POINTER(win.LPVOID))[0] = None
            return False
        if not self.notifications:
            self.last_error = win.WAIT_TIMEOUT
            ctypes.cast(value, ctypes.POINTER(win.LPVOID))[0] = None
            return False
        incoming_key, incoming_code, incoming_value = self.notifications.pop(0)
        ctypes.cast(code, ctypes.POINTER(win.DWORD))[0] = incoming_code
        ctypes.cast(key, ctypes.POINTER(win.SIZE_T))[0] = incoming_key
        ctypes.cast(value, ctypes.POINTER(win.LPVOID))[0] = incoming_value
        return True

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
        if kind == 3:  # JobObjectBasicProcessIdList 的真实可变长 ABI。
            self.record("query_members")
            header = ctypes.cast(data, ctypes.POINTER(win.DWORD))
            capacity = (size - 8) // ctypes.sizeof(win.SIZE_T)
            header[0], header[1] = len(self.members), min(capacity, len(self.members))
            values = ctypes.cast(ctypes.cast(data, ctypes.c_void_p).value + 8, ctypes.POINTER(win.SIZE_T))
            for index, pid in enumerate(self.members[:capacity]):
                values[index] = pid
            return True
        if not self.record("query_active"):
            return False
        values = self.after_stop if self.terminated else self.active
        count = values[0]
        if len(values) > 1:
            values.pop(0)
        output = ctypes.cast(data, ctypes.POINTER(win.JOBOBJECT_BASIC_ACCOUNTING_INFORMATION)).contents
        output.ActiveProcesses = count
        output.TotalProcesses = self.total
        return True

    def OpenProcess(self, access, inherit, pid):
        self.next_process_handle += 1
        self.process_handles[self.next_process_handle] = pid
        return self.next_process_handle

    def GetProcessTimes(self, process, created, exited, kernel, user):
        ctypes.cast(created, ctypes.POINTER(ctypes.c_uint64))[0] = self.process_handles[process] * 10
        return True

    def IsProcessInJob(self, process, job, output):
        if not self.record("member_identity"):
            return False
        ctypes.cast(output, ctypes.POINTER(win.BOOL))[0] = self.process_handles[process] in self.members
        return True

    def TerminateProcess(self, process, exitcode):
        return self.record("discard_suspended")

    def WaitForSingleObject(self, process, timeout):
        self.record("wait_root")
        pid = self.process_handles.get(process)
        self.events.append(("wait_process", pid, timeout))
        if pid in self.pending_members:
            if timeout == 0:
                return win.WAIT_TIMEOUT
            self.pending_members.remove(pid)
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

    def test_supervisor_source_exec_needs_no_registered_module(self):
        # 对齐真实 windows_bootstrap 的已验证字节 exec 边界：它不注册模块，
        # 也不先 import 再重开源码。不可变证明类型必须在这一真实加载形态可用。
        source = ROOT / "lib/install/windows_process.py"
        namespace = {"__name__": "_workflow_windows_supervisor", "__file__": str(source)}
        exec(compile(source.read_bytes(), str(source), "exec"), namespace)
        proof = namespace["_JobExitProof"]("job-zero-notification", 2, 1)
        self.assertEqual(proof._asdict(), {"source": "job-zero-notification", "total_processes": 2,
                                           "retained_processes": 1})
        with self.assertRaises(AttributeError):
            proof.total_processes = 1

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
            self.assertEqual(568, ctypes.sizeof(win.PROCESSENTRY32W))
            self.assertEqual(80, win.STARTUPINFOW.hStdInput.offset)
            self.assertEqual(104, win.STARTUPINFOEXW.lpAttributeList.offset)
        self.assertEqual(2 * ctypes.sizeof(win.HANDLE), ctypes.sizeof(win.JOBOBJECT_ASSOCIATE_COMPLETION_PORT))
        self.assertEqual(ctypes.sizeof(win.HANDLE), win.JOBOBJECT_ASSOCIATE_COMPLETION_PORT.CompletionPort.offset)

    def test_suspended_assign_resume_and_explicit_handle_allowlist(self):
        api = FakeWin32(exitcode=0)
        process = self.launch(api)
        self.assertLess(api.events.index("create_suspended"), api.events.index("assign_job"))
        self.assertLess(api.events.index("assign_job"), api.events.index("resume"))
        self.assertLess(api.events.index("associate_port"), api.events.index("create_suspended"))
        self.assertEqual(api.port_creation, (win.INVALID_HANDLE_VALUE, None, 0, 1))
        self.assertEqual((api.completion_key, api.completion_port), (200, 201))
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
        self.assertNotIn(201, api.allowed)  # IOCP handle stays with the same owner
        self.assertEqual(0, process.wait())
        process.close()
        self.assertEqual(1, api.closed.count(100))
        self.assertEqual(1, api.closed.count(101))
        self.assertEqual(1, api.closed.count(200))
        self.assertEqual(1, api.closed.count(201))
        self.assertEqual("retained-handles", process._exit_proof.source)

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
        for failure in ("create_job", "set_limits", "create_port", "associate_port", "duplicate",
                        "initialize_attributes", "restrict_handles"):
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
        for failure in ("resume", "member_identity"):
            api = FakeWin32(fail=failure, active=(2,))
            with self.subTest(failure=failure), patch.object(win.time, "sleep"), self.assertRaises(OSError):
                self.launch(api)
            self.assertIn("terminate_job", api.events)
            self.assertNotIn("discard_suspended", api.events)
            self.assertLess(api.events.index("exitcode"), api.events.index(("close", 200)))
            if failure == "member_identity":
                self.assertNotIn("resume", api.events)

    def test_wait_observes_grandchildren_not_just_root_exit(self):
        api = FakeWin32(active=(2, 1, 0), exitcode=17)
        process = self.launch(api)
        with patch.object(win.time, "sleep") as pause:
            self.assertEqual(17, process.wait())
        self.assertEqual(2, pause.call_count)
        self.assertTrue(process._quiescent)
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
        self.assertTrue(process._quiescent)
        self.assertEqual(37, process.returncode)
        process.close()
        self.assertEqual(1, api.events.count("terminate_job"))

    def test_cumulative_member_gap_never_claims_quiescence(self):
        # 当前 PID 清单已不含一个瞬时成员，但生命周期累计数仍为 2；错误实现
        # 仅凭 ActiveProcesses=0 会把无法证明已退出的历史成员当成已安全收尾。
        api = FakeWin32(total=2)
        process = self.launch(api)
        try:
            with self.assertRaises(win.WindowsJobCleanupError):
                process.wait()  # 两类证据均缺失；无期限入口不能挂死等待 best-effort 消息。
            self.assertFalse(process._quiescent)
        finally:
            process._close_handles()  # 仅回收 fake；不让故意失败的清理改变测试解释器信号。

    def test_job_zero_proves_transient_member_only_after_retained_handles_signal(self):
        api = FakeWin32(total=2)
        api.notifications = [(200, win.JOB_OBJECT_MSG_ACTIVE_PROCESS_ZERO, None)]
        api.pending_members.add(9001)
        process = self.launch(api)
        try:
            with self.assertRaises(subprocess.TimeoutExpired):
                process.wait(timeout=0)
            self.assertFalse(process._quiescent)
            # 消费当场 owner 已空的证据可跨有限 wait 保留；真实已持有句柄仍须
            # signaled，不能收到一个 zero 就跳过根或已观察到的后代结束屏障。
            self.assertEqual(2, process._observed_zero_total)
            self.assertEqual(37, process.wait(timeout=1))
            self.assertEqual(("job-zero-notification", 2, 1),
                             (process._exit_proof.source, process._exit_proof.total_processes,
                              process._exit_proof.retained_processes))
        finally:
            process.close()

    def test_missing_zero_respects_finite_deadline_and_cleanup_remains_fatal(self):
        api = FakeWin32(total=2)
        api.after_stop = [0]
        process = self.launch(api)
        previous = signal.getsignal(signal.SIGINT)
        try:
            with self.assertRaises(subprocess.TimeoutExpired):
                process.wait(timeout=0)
            self.assertFalse(process._quiescent)
            with self.assertRaises(win.WindowsJobCleanupError) as caught:
                process.close()
            self.assertNotIsInstance(caught.exception, Exception)
            self.assertTrue(process.closed)
            with self.assertRaises(win.WindowsJobCleanupError) as repeated:
                process.close()
            self.assertIs(caught.exception, repeated.exception)
            self.assertEqual(api.closed.count(201), 1)
        finally:
            signal.signal(signal.SIGINT, previous)

    def test_invalid_notifications_never_replace_missing_history(self):
        for notifications, failure in (([(999, win.JOB_OBJECT_MSG_ACTIVE_PROCESS_ZERO, None)], None),
                                       ([(200, win.JOB_OBJECT_MSG_ACTIVE_PROCESS_ZERO, 9002)], None),
                                       ([], "read_notification")):
            with self.subTest(notifications=notifications, failure=failure):
                api = FakeWin32(total=2, fail=failure)
                api.notifications = notifications
                process = self.launch(api)
                try:
                    with self.assertRaises((win.WindowsJobCleanupError, OSError)):
                        process.wait()
                    self.assertFalse(process._quiescent)
                    self.assertIsNone(process._observed_zero_total)
                finally:
                    process._close_handles()

    def test_active_owner_and_changed_totals_invalidate_zero_observation(self):
        # 正确 key 的内层/早到 zero 在 owner 仍 active 时必须被消费并丢弃。
        api = FakeWin32(total=2, active=(2, 2, 0))
        api.notifications = [(200, win.JOB_OBJECT_MSG_ACTIVE_PROCESS_ZERO, None)]
        process = self.launch(api)
        try:
            with self.assertRaises(win.WindowsJobCleanupError):
                process.wait()
            self.assertIsNone(process._observed_zero_total)
            self.assertFalse(process._quiescent)
        finally:
            process._close_handles()
        for changed_total in (1, 3):
            with self.subTest(total=changed_total):
                api = FakeWin32(total=2)
                api.notifications = [(200, win.JOB_OBJECT_MSG_ACTIVE_PROCESS_ZERO, None)]
                api.pending_members.add(9001)
                process = self.launch(api)
                try:
                    with self.assertRaises(subprocess.TimeoutExpired):
                        process.wait(timeout=0)
                    api.total = changed_total
                    with self.assertRaises(win.WindowsJobCleanupError):
                        process.wait()
                    self.assertFalse(process._quiescent)
                finally:
                    process._close_handles()

    def test_active_zero_waits_for_every_retained_member_handle(self):
        # 20 成员同时覆盖可变长 Win32 缓冲区的扩容分支；不能默默只保留前 16 个。
        for members in ((9001, 9002), tuple(range(9001, 9021))):
            with self.subTest(member_count=len(members)):
                api = FakeWin32(members=members)
                api.pending_members.add(9002)
                process = self.launch(api)
                try:
                    with self.assertRaises(subprocess.TimeoutExpired):
                        process.wait(timeout=0)
                    self.assertFalse(process._quiescent)
                    self.assertEqual(37, process.wait(timeout=1))
                    self.assertTrue(process._quiescent)
                    self.assertEqual(len(members), len(process._members))
                    self.assertTrue(any(event[0] == "wait_process" and event[1] == 9002
                                        for event in api.events if isinstance(event, tuple)))
                finally:
                    process.close()

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
        self.assertIn("exitcode", api.events)
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

    def test_pipe_handles_are_allowlisted_without_inheriting_parent_ends(self):
        api = FakeWin32(exitcode=0)
        with patch.object(win, "_Win32API", return_value=api), \
                patch.object(win.WindowsJobProcess, "_file_handle", side_effect=lambda fd: fd + 5000):
            process = win.WindowsJobProcess(["fixture.exe"], stdin=subprocess.PIPE,
                                            stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        self.assertEqual(3, len(api.allowed))
        self.assertTrue(all(handle >= 6000 for handle in api.allowed))
        streams = (process.stdin, process.stdout, process.stderr)
        process.wait()
        process.close()
        self.assertTrue(all(stream.closed for stream in streams))

    def test_supervisor_rejects_reused_payload_pid_before_spawn(self):
        api = Mock()
        api.OpenProcess.return_value = 100

        def times(handle, created, *unused):
            ctypes.cast(created, ctypes.POINTER(ctypes.c_uint64))[0] = 999
            return True

        api.GetProcessTimes.side_effect = times
        with patch.object(win, "_Win32API", return_value=api), patch.object(win, "WindowsJobProcess") as spawn, \
                self.assertRaisesRegex(ValueError, "identity changed"):
            win.supervise_hook(["fixture.exe"], 1, 2, time.monotonic() + 1)
        spawn.assert_not_called()
        api.CloseHandle.assert_called_once_with(100)


class CaptureProcessTest(unittest.TestCase):
    def test_real_helper_preserves_selected_interpreter_exit(self):
        from lib import runtime_bridge
        env = dict(os.environ)
        env.pop("AGENT_WORKFLOW_HOOK_DEADLINE", None)
        invocation = runtime_bridge.HelperInvocation((sys.executable, "-B", "-X", "utf8", "-c", "raise SystemExit(37)"), env, ROOT, {})
        self.assertEqual(37, runtime_bridge.run_helper(invocation, timeout=5))

    def test_windows_capture_uses_job_and_preserves_bytes_and_exit(self):
        backend = Mock(returncode=37)
        backend.communicate.return_value = (b"\xff\x00out", b"\x80err")
        with patch.object(install_process.os, "name", "nt"), \
                patch.object(install_process.time, "monotonic", return_value=100), \
                patch.object(install_process, "WindowsJobProcess", return_value=backend), \
                patch.object(install_process.subprocess, "Popen") as ordinary:
            result = install_process.capture_process(["fixture.exe"], body=b"\x00\xff", timeout=2)
        self.assertEqual((37, b"\xff\x00out", b"\x80err"), (result.returncode, result.stdout, result.stderr))
        backend.communicate.assert_called_once_with(b"\x00\xff", timeout=2, cancel_file=None)
        backend.close.assert_called_once()
        ordinary.assert_not_called()

    def test_capture_startup_consumes_the_same_deadline(self):
        backend = Mock(returncode=0)
        backend.communicate.return_value = (b"out", b"")
        with patch.object(install_process.os, "name", "nt"), \
                patch.object(install_process.time, "monotonic", side_effect=(100, 100, 100.8)), \
                patch.object(install_process, "WindowsJobProcess", return_value=backend):
            install_process.capture_process(["fixture.exe"], timeout=2)
        self.assertAlmostEqual(1.2, backend.communicate.call_args.kwargs["timeout"])

    def test_real_capture_runs_selected_interpreter_with_binary_stdio(self):
        body = b"\x00\xff" + "中文".encode("utf-8") * 40000
        command = [sys.executable, "-B", "-X", "utf8", "-c",
                   "import sys; b=sys.stdin.buffer.read(); sys.stdout.buffer.write(b); sys.stderr.buffer.write(b'err\\xff'); raise SystemExit(37)"]
        result = install_process.capture_process(command, body=body, timeout=5)
        self.assertEqual((37, body, b"err\xff"), (result.returncode, result.stdout, result.stderr))

    def test_windows_helper_preserves_exit_and_stops_timeout_before_return(self):
        from lib import runtime_bridge
        backend = Mock()
        backend.wait.return_value = 37
        invocation = runtime_bridge.HelperInvocation((sys.executable, "-c", "pass"), dict(os.environ), ROOT, {})
        with patch.object(runtime_bridge.os, "name", "nt"), patch.object(win, "WindowsJobProcess", return_value=backend):
            self.assertEqual(37, runtime_bridge.run_helper(invocation, timeout=1))
            backend.wait.side_effect = subprocess.TimeoutExpired(invocation.command, 1)
            with self.assertRaisesRegex(ValueError, "超时并终止"):
                runtime_bridge.run_helper(invocation, timeout=1)
        backend.stop.assert_called_once()
        self.assertEqual(2, backend.close.call_count)

    def test_expired_hook_deadline_rejects_helper_without_spawn(self):
        from lib import runtime_bridge
        invocation = runtime_bridge.HelperInvocation((sys.executable,), {"AGENT_WORKFLOW_HOOK_DEADLINE": "1"}, ROOT, {})
        with patch.object(runtime_bridge.subprocess, "Popen") as spawn, \
                patch.object(win, "WindowsJobProcess") as job, self.assertRaisesRegex(ValueError, "未启动"):
            runtime_bridge.run_helper(invocation)
        spawn.assert_not_called()
        job.assert_not_called()


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
    def record_proof(self, process, **details):
        # 原始证据沿现有 CI process.log 保存，不打印环境、业务资料或继承凭据。
        proof = process._exit_proof
        entry = {"kind": "job-quiescence", "test": self.id(), "pid": process.pid,
                 "exit": process.returncode, "closed": process.closed,
                 "proof": None if proof is None else proof._asdict(), **details}
        line = json.dumps(entry, ensure_ascii=False)
        print("[job evidence] " + line, flush=True)
        target = os.environ.get("AWF_TEST_EVIDENCE_LOG")
        if target:
            with open(target, "a", encoding="utf-8") as stream:
                stream.write(line + "\n")

    def test_completed_transient_members_use_owned_job_zero_notification(self):
        # 固定原生入口为既有选定私有 venv；不换 base、不加 sleep 或 child 握手。
        # 先等真实根句柄结束，故意让所有瞬时 Python 成员在首次观察前都已退出，
        # 从而确定覆盖旧“累计 2 / 仅根句柄 1”的缺口，而非依靠调度碰巧复现。
        self.assertNotEqual(Path(sys.prefix).resolve(), Path(sys.base_prefix).resolve(),
                            "该原生节点需要现有测试入口选定的私有 venv")
        with tempfile.TemporaryDirectory(prefix="workflow-native-transient-",
                                         dir=os.environ.get("AGENT_WORKFLOW_TEST_SCRATCH")) as raw:
            command = [sys.executable, "-B", "-X", "utf8", "-c",
                       "import os;os.write(1,b'out\\x00');os.write(2,b'err\\xff');raise SystemExit(37)"]
            process = win.WindowsJobProcess(command, cwd=raw, stdin=subprocess.DEVNULL,
                                            stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            try:
                kernel = ctypes.WinDLL("kernel32", use_last_error=True)
                kernel.GetHandleInformation.argtypes = [win.HANDLE, ctypes.POINTER(win.DWORD)]
                kernel.GetHandleInformation.restype = win.BOOL
                for handle in (process._job, process._completion_port):
                    flags = win.DWORD()
                    self.assertTrue(kernel.GetHandleInformation(handle, ctypes.byref(flags)))
                    self.assertEqual(flags.value & 1, 0, "Job/IOCP 必须保持不可继承")
                self.assertEqual(win.WAIT_OBJECT_0,
                                 process._api.WaitForSingleObject(process._process.hProcess, 5000))
                self.assertFalse(process._quiescent)  # root 结束本身不能发布 Job 终态。
                before = process._accounting()
                self.assertGreaterEqual(before.TotalProcesses, 2)
                self.assertEqual(len(process._members), 1)
                output, error = process.communicate(timeout=5)
                self.assertEqual((output, error, process.returncode), (b"out\x00", b"err\xff", 37))
                self.assertEqual("job-zero-notification", process._exit_proof.source)
                self.assertGreater(process._exit_proof.total_processes, process._exit_proof.retained_processes)
                self.assertTrue(process._quiescent)
                self.record_proof(process, argv=command, stdout_hex=output.hex(), stderr_hex=error.hex())
            finally:
                process.close()

    def test_nested_breakaway_remains_contained_until_owner_job_is_empty(self):
        # 真实 Win32 event 控制后代写入，不靠 sleep 延长寿命或等待“足够久”。
        # fixture 的内层 Job 允许显式/静默 breakaway；自有祖先 Job 禁止它，
        # 因此新进程可以离开内层，仍必须受唯一外层 owner 的终止证明覆盖。
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.CreateEventW.argtypes = [win.LPVOID, win.BOOL, win.BOOL, win.LPWSTR]
        kernel.CreateEventW.restype = win.HANDLE
        kernel.SetEvent.argtypes, kernel.SetEvent.restype = [win.HANDLE], win.BOOL
        kernel.CloseHandle.argtypes, kernel.CloseHandle.restype = [win.HANDLE], win.BOOL
        for outcome in ("normal", "cancel"):
            with self.subTest(outcome=outcome), tempfile.TemporaryDirectory(
                    prefix="workflow-native-nested-", dir=os.environ.get("AGENT_WORKFLOW_TEST_SCRATCH")) as raw:
                root = Path(raw)
                ready_name, release_name = ("Local\\awf-" + root.name + suffix for suffix in ("-ready", "-release"))
                ready = kernel.CreateEventW(None, True, False, ready_name)
                if not ready:
                    raise ctypes.WinError(ctypes.get_last_error())
                self.addCleanup(kernel.CloseHandle, ready)
                release = kernel.CreateEventW(None, True, False, release_name)
                if not release:
                    raise ctypes.WinError(ctypes.get_last_error())
                self.addCleanup(kernel.CloseHandle, release)
                report, late = root / "member.json", root / "after-release"
                child = textwrap.dedent(f"""
                    import ctypes, json, os
                    from pathlib import Path
                    K = ctypes.WinDLL('kernel32', use_last_error=True)
                    H, D = ctypes.c_void_p, ctypes.c_uint32
                    K.OpenEventW.argtypes, K.OpenEventW.restype = [D, ctypes.c_int32, ctypes.c_wchar_p], H
                    K.SetEvent.argtypes, K.SetEvent.restype = [H], ctypes.c_int32
                    K.WaitForSingleObject.argtypes, K.WaitForSingleObject.restype = [H, D], D
                    ready = K.OpenEventW(2, False, {ready_name!r})
                    release = K.OpenEventW(0x00100000, False, {release_name!r})
                    assert ready and release, ctypes.get_last_error()
                    Path({str(report)!r}).write_text(json.dumps({{'pid': os.getpid()}}), encoding='utf-8')
                    assert K.SetEvent(ready), ctypes.get_last_error()
                    assert K.WaitForSingleObject(release, 10000) == 0
                    Path({str(late)!r}).write_text('released', encoding='utf-8')
                """)
                parent = textwrap.dedent(f"""
                    import ctypes, subprocess, sys
                    sys.path.insert(0, {str(ROOT)!r})
                    from lib.install import windows_process as W
                    K = W._Win32API()
                    inner = K.CreateJobObjectW(None, None)
                    assert inner, ctypes.get_last_error()
                    limits = W.JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
                    limits.BasicLimitInformation.LimitFlags = 0x00000800 | 0x00001000
                    assert K.SetInformationJobObject(inner, W.JobObjectExtendedLimitInformation,
                                                    ctypes.byref(limits), ctypes.sizeof(limits))
                    assert K.AssignProcessToJobObject(inner, K.GetCurrentProcess()), ctypes.get_last_error()
                    subprocess.Popen([sys.executable, '-B', '-X', 'utf8', '-c', {child!r}],
                                     creationflags=0x01000000)
                    raise SystemExit(23)
                """)
                process = win.WindowsJobProcess([sys.executable, "-B", "-X", "utf8", "-c", parent], cwd=root,
                                                stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                zeros = []
                native_next = process._api.GetQueuedCompletionStatus

                def observe_native_packet(*arguments):
                    # 只投影实际内核返回的 packet，不制造/重发消息、不改变返回值。
                    received = native_next(*arguments)
                    if received and ctypes.cast(arguments[1], ctypes.POINTER(win.DWORD))[0] == win.JOB_OBJECT_MSG_ACTIVE_PROCESS_ZERO:
                        state = process._accounting()
                        zeros.append({"key": ctypes.cast(arguments[2], ctypes.POINTER(win.SIZE_T))[0],
                                      "active": state.ActiveProcesses})
                    return received

                process._api.GetQueuedCompletionStatus = observe_native_packet
                try:
                    self.assertEqual(win.WAIT_OBJECT_0, process._api.WaitForSingleObject(ready, 5000))
                    self.assertEqual(win.WAIT_OBJECT_0,
                                     process._api.WaitForSingleObject(process._process.hProcess, 5000))
                    with self.assertRaises(subprocess.TimeoutExpired):
                        process.wait(timeout=.1)
                    self.assertTrue(any(item["active"] > 0 for item in zeros),
                                    "尚未观察到内层归零向仍活跃 owner 上送的真实通知")
                    self.assertIsNone(process._observed_zero_total)
                    self.assertFalse(process._quiescent)
                    member_pid = json.loads(report.read_text(encoding="utf-8"))["pid"]
                    member = next(handle for (pid, _), handle in process._members.items() if pid == member_pid)
                    self.assertIsNotNone(process._member_identity(member_pid, member))
                    self.assertEqual(win.WAIT_TIMEOUT, process._api.WaitForSingleObject(member, 0))
                    if outcome == "cancel":
                        process.stop()
                        self.assertEqual(win.WAIT_OBJECT_0, process._api.WaitForSingleObject(member, 0))
                        self.assertTrue(kernel.SetEvent(release))
                        self.assertFalse(late.exists(), "已停止成员仍在 release 后写入")
                    else:
                        self.assertTrue(kernel.SetEvent(release))
                        self.assertEqual(23, process.wait(timeout=5))
                        self.assertEqual(late.read_text(encoding="utf-8"), "released")
                    self.assertTrue(process._quiescent)
                    self.record_proof(process, outcome=outcome, zero_packets=zeros, member_pid=member_pid,
                                      member_wait=process._api.WaitForSingleObject(member, 0))
                finally:
                    process.close()

    def test_wait_confirms_normal_descendant_handles(self):
        """根进程先正常退出，owner 仍须捕获完整成员并等待后代真实句柄。"""
        with tempfile.TemporaryDirectory(prefix="workflow-native-normal-members-") as raw:
            child = "import time;print('child-started',flush=True);time.sleep(.4)"
            parent = ("import subprocess,sys;"
                      f"subprocess.Popen([sys.executable,'-B','-X','utf8','-c',{child!r}]);"
                      "raise SystemExit(23)")
            command = [sys.executable, "-B", "-X", "utf8", "-c", parent]
            process = win.WindowsJobProcess(command, cwd=raw, stdin=subprocess.DEVNULL,
                                            stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            try:
                output, error = process.communicate(timeout=10)
                states = [{"pid": pid, "created": created,
                           "wait": process._api.WaitForSingleObject(handle, 0)}
                          for (pid, created), handle in process._members.items()]
                print(json.dumps({"argv": command, "exit": process.returncode,
                                  "members": states, "stdout": output.decode(), "stderr": error.decode()}))
                self.assertEqual(23, process.returncode)
                self.assertIn(b"child-started", output)
                self.assertGreaterEqual(len(states), 2)
                self.assertTrue(all(item["wait"] == win.WAIT_OBJECT_0 for item in states))
                self.assertTrue(process._quiescent)
            finally:
                process.close()

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
                "from lib.install.install_process import SetupRunner;"
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

    def test_capture_timeout_drains_descendants_and_binary_output(self):
        # 真正的管道读写、Job 孙进程与超时必须在 native 集合执行；portable
        # fake 仅证明选路，不能替代该节点对 Win32 管道/句柄继承的验证。
        CaptureProcessTest("test_real_capture_runs_selected_interpreter_with_binary_stdio").test_real_capture_runs_selected_interpreter_with_binary_stdio()
        with tempfile.TemporaryDirectory(prefix="workflow-native-capture-") as raw:
            command, ready, late = self.tree(Path(raw))
            with self.assertRaises(subprocess.TimeoutExpired):
                install_process.capture_process(command, body=b"raw\xff", timeout=1.5)
            self.assertTrue(ready.exists())
            time.sleep(3.1)
            self.assertFalse(late.exists(), "capture returned while its Job descendant could still write")

    def test_helper_timeout_drains_its_job(self):
        from lib import runtime_bridge
        with tempfile.TemporaryDirectory(prefix="workflow-native-helper-") as raw:
            root = Path(raw)
            command, ready, late = self.tree(root)
            invocation = runtime_bridge.HelperInvocation(tuple(command), dict(os.environ), root, {})
            with self.assertRaisesRegex(ValueError, "超时并终止"):
                runtime_bridge.run_helper(invocation, timeout=1.5)
            self.assertTrue(ready.exists())
            time.sleep(3.1)
            self.assertFalse(late.exists())

    def test_helper_native_exitcode_is_preserved(self):
        CaptureProcessTest("test_real_helper_preserves_selected_interpreter_exit").test_real_helper_preserves_selected_interpreter_exit()

    def test_capture_cancel_file_drains_its_job(self):
        with tempfile.TemporaryDirectory(prefix="workflow-native-capture-cancel-") as raw:
            root = Path(raw)
            command, ready, late = self.tree(root)
            cancel = root / "cancel"

            def cancel_when_ready():
                deadline = time.monotonic() + 8
                while not ready.exists() and time.monotonic() < deadline:
                    time.sleep(0.02)
                cancel.touch()

            with patch.dict(os.environ, {CANCEL_FILE_ENV: str(cancel)}):
                runner = SetupRunner(timeout=10)
                token = install_process.ACTIVE_RUNNER.set(runner)
                worker = threading.Thread(target=cancel_when_ready)
                worker.start()
                try:
                    with self.assertRaisesRegex(SetupRunError, "取消"):
                        install_process.capture_process(command, body=b"raw\xff", timeout=10)
                    self.assertTrue(ready.exists())
                finally:
                    install_process.ACTIVE_RUNNER.reset(token)
                    runner.close()
                    worker.join(timeout=10)
            time.sleep(3.1)
            self.assertFalse(late.exists())


if __name__ == "__main__":
    unittest.main()
