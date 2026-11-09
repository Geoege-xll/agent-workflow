"""Windows setup children, contained in a Job before their first instruction.

No shell is introduced here. The caller chooses the executable (and is responsible
for disabling shell profiles). Only duplicated standard handles are inherited.
"""

from __future__ import annotations

from contextlib import contextmanager
import ctypes
import math
import os
import signal
import subprocess
import sys
import threading
import time


# Use Windows-sized fields even when importing this module on a non-Windows test
# host: ctypes.wintypes.DWORD is an unsigned *long*, which is 64 bits on macOS.
DWORD = ctypes.c_uint32
WORD = ctypes.c_uint16
BOOL = ctypes.c_int32
HANDLE = ctypes.c_void_p
SIZE_T = ctypes.c_size_t
LPVOID = ctypes.c_void_p
LPWSTR = ctypes.c_wchar_p

CREATE_SUSPENDED = 0x00000004
CREATE_UNICODE_ENVIRONMENT = 0x00000400
EXTENDED_STARTUPINFO_PRESENT = 0x00080000
STARTF_USESTDHANDLES = 0x00000100
PROC_THREAD_ATTRIBUTE_HANDLE_LIST = 0x00020002
PROC_THREAD_ATTRIBUTE_PSEUDOCONSOLE = 0x00020016
JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000
JobObjectBasicAccountingInformation = 1
JobObjectBasicProcessIdList = 3
JobObjectExtendedLimitInformation = 9
DUPLICATE_SAME_ACCESS = 0x00000002
INFINITE = 0xFFFFFFFF
WAIT_OBJECT_0 = 0
WAIT_TIMEOUT = 258
INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value


class JOBOBJECT_BASIC_LIMIT_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("PerProcessUserTimeLimit", ctypes.c_int64),
        ("PerJobUserTimeLimit", ctypes.c_int64),
        ("LimitFlags", DWORD),
        ("MinimumWorkingSetSize", SIZE_T),
        ("MaximumWorkingSetSize", SIZE_T),
        ("ActiveProcessLimit", DWORD),
        ("Affinity", SIZE_T),
        ("PriorityClass", DWORD),
        ("SchedulingClass", DWORD),
    ]


class IO_COUNTERS(ctypes.Structure):
    _fields_ = [(name, ctypes.c_uint64) for name in (
        "ReadOperationCount", "WriteOperationCount", "OtherOperationCount",
        "ReadTransferCount", "WriteTransferCount", "OtherTransferCount",
    )]


class JOBOBJECT_EXTENDED_LIMIT_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("BasicLimitInformation", JOBOBJECT_BASIC_LIMIT_INFORMATION),
        ("IoInfo", IO_COUNTERS),
        ("ProcessMemoryLimit", SIZE_T),
        ("JobMemoryLimit", SIZE_T),
        ("PeakProcessMemoryUsed", SIZE_T),
        ("PeakJobMemoryUsed", SIZE_T),
    ]


class JOBOBJECT_BASIC_ACCOUNTING_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("TotalUserTime", ctypes.c_int64),
        ("TotalKernelTime", ctypes.c_int64),
        ("ThisPeriodTotalUserTime", ctypes.c_int64),
        ("ThisPeriodTotalKernelTime", ctypes.c_int64),
        ("TotalPageFaultCount", DWORD),
        ("TotalProcesses", DWORD),
        ("ActiveProcesses", DWORD),
        ("TotalTerminatedProcesses", DWORD),
    ]


class STARTUPINFOW(ctypes.Structure):
    _fields_ = [
        ("cb", DWORD),
        ("lpReserved", LPWSTR),
        ("lpDesktop", LPWSTR),
        ("lpTitle", LPWSTR),
        ("dwX", DWORD), ("dwY", DWORD),
        ("dwXSize", DWORD), ("dwYSize", DWORD),
        ("dwXCountChars", DWORD), ("dwYCountChars", DWORD),
        ("dwFillAttribute", DWORD), ("dwFlags", DWORD),
        ("wShowWindow", WORD), ("cbReserved2", WORD),
        ("lpReserved2", ctypes.POINTER(ctypes.c_ubyte)),
        ("hStdInput", HANDLE), ("hStdOutput", HANDLE), ("hStdError", HANDLE),
    ]


class STARTUPINFOEXW(ctypes.Structure):
    _fields_ = [("StartupInfo", STARTUPINFOW), ("lpAttributeList", LPVOID)]


class PROCESS_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("hProcess", HANDLE), ("hThread", HANDLE),
        ("dwProcessId", DWORD), ("dwThreadId", DWORD),
    ]


class PROCESSENTRY32W(ctypes.Structure):
    _fields_ = [("dwSize", DWORD), ("cntUsage", DWORD), ("th32ProcessID", DWORD),
                ("th32DefaultHeapID", SIZE_T), ("th32ModuleID", DWORD), ("cntThreads", DWORD),
                ("th32ParentProcessID", DWORD), ("pcPriClassBase", ctypes.c_int32),
                ("dwFlags", DWORD), ("szExeFile", ctypes.c_uint16 * 260)]


class WindowsJobCleanupError(BaseException):
    """Quiescence could not be proved; do NOT enter transaction recovery.

    Deliberately not an Exception/OSError: the install transaction catches those
    to begin filesystem recovery, which would be unsafe with unconfirmed writers.
    """


class WindowsProcessCancelled(Exception):
    """调用方取消或监督父进程已退出；抛出前必须先确认自有 Job 归零。"""


class _Win32API:
    def __init__(self):
        if os.name != "nt":
            raise OSError("Windows Job Objects require Windows")
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        signatures = {
            "CreateJobObjectW": ([LPVOID, LPWSTR], HANDLE),
            "SetInformationJobObject": ([HANDLE, ctypes.c_int, LPVOID, DWORD], BOOL),
            "QueryInformationJobObject": ([HANDLE, ctypes.c_int, LPVOID, DWORD, LPVOID], BOOL),
            "AssignProcessToJobObject": ([HANDLE, HANDLE], BOOL),
            "TerminateJobObject": ([HANDLE, DWORD], BOOL),
            "GetCurrentProcess": ([], HANDLE),
            "GetStdHandle": ([DWORD], HANDLE),
            "OpenProcess": ([DWORD, BOOL, DWORD], HANDLE),
            "IsProcessInJob": ([HANDLE, HANDLE, ctypes.POINTER(BOOL)], BOOL),
            "GetProcessTimes": ([HANDLE, LPVOID, LPVOID, LPVOID, LPVOID], BOOL),
            "CreateToolhelp32Snapshot": ([DWORD, DWORD], HANDLE),
            "Process32FirstW": ([HANDLE, ctypes.POINTER(PROCESSENTRY32W)], BOOL),
            "Process32NextW": ([HANDLE, ctypes.POINTER(PROCESSENTRY32W)], BOOL),
            "DuplicateHandle": ([HANDLE, HANDLE, HANDLE, ctypes.POINTER(HANDLE), DWORD, BOOL, DWORD], BOOL),
            "CreateFileW": ([LPWSTR, DWORD, DWORD, LPVOID, DWORD, DWORD, HANDLE], HANDLE),
            "InitializeProcThreadAttributeList": ([LPVOID, DWORD, DWORD, ctypes.POINTER(SIZE_T)], BOOL),
            "UpdateProcThreadAttribute": ([LPVOID, DWORD, SIZE_T, LPVOID, SIZE_T, LPVOID, LPVOID], BOOL),
            "DeleteProcThreadAttributeList": ([LPVOID], None),
            "CreateProcessW": ([LPWSTR, LPWSTR, LPVOID, LPVOID, BOOL, DWORD, LPVOID, LPWSTR,
                                ctypes.POINTER(STARTUPINFOEXW), ctypes.POINTER(PROCESS_INFORMATION)], BOOL),
            "ResumeThread": ([HANDLE], DWORD),
            "TerminateProcess": ([HANDLE, DWORD], BOOL),
            "WaitForSingleObject": ([HANDLE, DWORD], DWORD),
            "GetExitCodeProcess": ([HANDLE, ctypes.POINTER(DWORD)], BOOL),
            "CloseHandle": ([HANDLE], BOOL),
        }
        for name, (arguments, result) in signatures.items():
            function = getattr(kernel, name)
            function.argtypes = arguments
            function.restype = result
            setattr(self, name, function)

    @staticmethod
    def error(operation):
        code = ctypes.get_last_error()
        return ctypes.WinError(code, f"{operation}: {ctypes.FormatError(code)}")


@contextmanager
def _defer_interrupts():
    """Do not lose a newly created suspended process to a Python SIGINT race."""
    interrupted = []
    main = threading.current_thread() is threading.main_thread()
    previous = signal.getsignal(signal.SIGINT) if main else None
    # Recovery already ignores SIGINT. Do not turn it back into cancellation.
    defer = main and previous != signal.SIG_IGN
    if defer:
        signal.signal(signal.SIGINT, lambda *_: interrupted.append(True))
    try:
        yield
    finally:
        if defer:
            # A nested constructor cleanup can fail fatally. Do not undo its
            # SIGINT suppression while unwinding the outer assignment guard.
            fatal = isinstance(sys.exc_info()[1], WindowsJobCleanupError)
            signal.signal(signal.SIGINT, signal.SIG_IGN if fatal else previous)
        if interrupted and sys.exc_info()[0] is None:
            raise KeyboardInterrupt()


@contextmanager
def _ignore_interrupts():
    # Once stopping, repeated Ctrl+C must not release the transaction to recovery
    # before all descendants have exited. Node cancellation uses a file, not a
    # console control event, and does not interrupt this wait.
    main = threading.current_thread() is threading.main_thread()
    if main:
        previous = signal.getsignal(signal.SIGINT)
        signal.signal(signal.SIGINT, signal.SIG_IGN)
    try:
        yield
    finally:
        # A second Ctrl+C must not replace the fatal cleanup exception with a
        # recoverable KeyboardInterrupt while it unwinds through the installer.
        fatal = isinstance(sys.exc_info()[1], WindowsJobCleanupError)
        if main and not fatal:
            signal.signal(signal.SIGINT, previous)


def _command_line(command):
    if isinstance(command, str):
        result = command
    else:
        if isinstance(command, (bytes, os.PathLike)):
            command = [command]
        result = subprocess.list2cmdline([os.fsdecode(argument) for argument in command])
    if "\0" in result:
        raise ValueError("Embedded NUL in Windows command")
    return result


def _environment_block(env):
    if env is None:
        return None
    entries = []
    seen = set()
    for key, value in env.items():
        key, value = os.fsdecode(key), os.fsdecode(value)
        # Leading '=' is allowed for Windows' per-drive working directories.
        if not key or "=" in key[1:] or "\0" in key or "\0" in value:
            raise ValueError("Invalid Windows environment entry")
        if key.casefold() in seen:
            raise ValueError(f"Duplicate Windows environment name: {key}")
        seen.add(key.casefold())
        entries.append((key, value))
    entries.sort(key=lambda item: item[0].upper())
    # create_unicode_buffer adds its own NUL; empty environments still need two.
    return ctypes.create_unicode_buffer("\0".join(f"{key}={value}" for key, value in entries) + "\0")


class WindowsJobProcess:
    """Small Popen-like owner. wait() means the *whole Job* is empty."""

    def __init__(self, command, cwd=None, env=None, *, stdin=None, stdout=None, stderr=None,
                 pseudoconsole=None):
        # HPCON 是调用者拥有的指针宽度不透明值；本 owner 只把它绑定到启动属性，
        # 不关闭伪控制台。调用者必须保持其存活，直至 wait/close 已确认 Job 归零。
        # ConPTY 自行提供控制台标准句柄，显式 PIPE/DEVNULL 必须拒绝，不能悄悄丢弃。
        if pseudoconsole is not None:
            if type(pseudoconsole) is not int or not 0 < pseudoconsole < INVALID_HANDLE_VALUE:
                raise ValueError("Windows 伪控制台句柄必须是有效的指针宽度整数")
            if any(stream is not None for stream in (stdin, stdout, stderr)):
                raise ValueError("Windows 伪控制台不能同时指定标准流重定向")
        self.args = command
        self.returncode = None
        self._api = _Win32API()
        self._job = None
        self._process = PROCESS_INFORMATION()
        self._assigned = False
        self._resumed = False
        self._quiescent = False
        # 句柄释放与“所有成员均已结束”是两个独立事实。证明失败必须永久归本
        # owner 所有；close 后不能因句柄已清空再查询 Win32，更不能把失败改成成功。
        self._closed = False
        self._cleanup_error = None
        self._stop_attempted = False
        # 只在本 owner 生命周期内持有成员真实句柄。累计成员数用于证明捕获完整性，
        # 不能把当前 PID 清单/ActiveProcesses=0 当作历史成员均已 signaled 的屏障。
        self._members = {}
        self._total_processes = 0
        self.stdin = self.stdout = self.stderr = None
        self._child_fds = []
        self._cancel_event = threading.Event()
        self._communicated = False
        try:
            with _defer_interrupts():
                self._start(command, cwd, env, (stdin, stdout, stderr), pseudoconsole)
        except BaseException:
            with _ignore_interrupts():
                try:
                    self._abort_start()
                finally:
                    self._close_handles()
            raise

    def _check(self, result, operation):
        if not result:
            raise self._api.error(operation)
        return result

    @staticmethod
    def _file_handle(descriptor):
        import msvcrt
        return msvcrt.get_osfhandle(descriptor)

    def _standard_handles(self, handles, streams):
        """Duplicate, never mutate/close the parent's stdin (including pipes)."""
        api = self._api
        current = api.GetCurrentProcess()
        for number, name, stream in zip((-10, -11, -12), ("stdin", "stdout", "stderr"), streams):
            if stream not in (None, subprocess.PIPE, subprocess.DEVNULL):
                raise ValueError("Windows Job streams require inherited handles, PIPE or DEVNULL")
            if stream == subprocess.PIPE:
                # CRT 管道两端默认不可继承；只把 child 端另行复制进白名单。
                # parent 端由本 owner 持有，启动失败时也必须关闭，避免 EOF 永远不到达。
                read_fd, write_fd = os.pipe()
                child_fd, parent_fd = (read_fd, write_fd) if name == "stdin" else (write_fd, read_fd)
                self._child_fds.append(child_fd)
                setattr(self, name, os.fdopen(parent_fd, "wb" if name == "stdin" else "rb", buffering=0))
                source = self._file_handle(child_fd)
            else:
                source = None if stream == subprocess.DEVNULL else api.GetStdHandle(DWORD(number).value)
            temporary = None
            if source in (None, 0, INVALID_HANDLE_VALUE):
                access = 0x80000000 if number == -10 else 0x40000000
                source = api.CreateFileW("NUL", access, 3, None, 3, 0x80, None)
                if source in (None, 0, INVALID_HANDLE_VALUE):
                    raise api.error("Open missing standard handle as NUL")
                temporary = source
            try:
                duplicate = HANDLE()
                self._check(api.DuplicateHandle(current, source, current, ctypes.byref(duplicate),
                                                0, True, DUPLICATE_SAME_ACCESS), "Duplicate standard handle")
                handles.append(duplicate.value)
            finally:
                if temporary is not None:
                    api.CloseHandle(temporary)

    def _start(self, command, cwd, env, streams, pseudoconsole=None):
        api = self._api
        command_line = ctypes.create_unicode_buffer(_command_line(command))
        environment = _environment_block(env)
        directory = os.fsdecode(cwd) if cwd is not None else None
        if directory is not None and "\0" in directory:
            raise ValueError("Embedded NUL in Windows working directory")
        self._job = self._check(api.CreateJobObjectW(None, None), "Create setup Job Object")
        limits = JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
        limits.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        self._check(api.SetInformationJobObject(self._job, JobObjectExtendedLimitInformation,
                                               ctypes.byref(limits), ctypes.sizeof(limits)), "Set setup Job limits")
        handles = []
        attributes = None
        initialized = False
        try:
            if pseudoconsole is None:
                self._standard_handles(handles, streams)
            size = SIZE_T()
            # The first call reports the required buffer size, normally returning
            # ERROR_INSUFFICIENT_BUFFER. No fixed size or private CPython ABI.
            api.InitializeProcThreadAttributeList(None, 1, 0, ctypes.byref(size))
            if not size.value:
                raise api.error("Size process handle-inheritance attributes")
            attributes = ctypes.create_string_buffer(size.value)
            self._check(api.InitializeProcThreadAttributeList(attributes, 1, 0, ctypes.byref(size)),
                        "Initialize process handle-inheritance attributes")
            initialized = True
            startup = STARTUPINFOEXW()
            startup.StartupInfo.cb = ctypes.sizeof(startup)
            if pseudoconsole is None:
                allowed = (HANDLE * len(handles))(*handles)
                self._check(api.UpdateProcThreadAttribute(attributes, 0, PROC_THREAD_ATTRIBUTE_HANDLE_LIST,
                                                         allowed, ctypes.sizeof(allowed), None, None),
                            "Restrict inherited handles")
                startup.StartupInfo.dwFlags = STARTF_USESTDHANDLES
                startup.StartupInfo.hStdInput, startup.StartupInfo.hStdOutput, startup.StartupInfo.hStdError = handles
            else:
                # 官方 ConPTY 属性要求 lpValue=HPCON 本值，并非 &HPCON；cbSize
                # 仍为 sizeof(HANDLE)。此分支不继承宿主标准句柄，也不设 USESTDHANDLES。
                self._check(api.UpdateProcThreadAttribute(
                    attributes, 0, PROC_THREAD_ATTRIBUTE_PSEUDOCONSOLE,
                    HANDLE(pseudoconsole), ctypes.sizeof(HANDLE), None, None), "Bind pseudoconsole")
            startup.lpAttributeList = ctypes.cast(attributes, LPVOID)
            flags = CREATE_SUSPENDED | CREATE_UNICODE_ENVIRONMENT | EXTENDED_STARTUPINFO_PRESENT
            self._check(api.CreateProcessW(None, command_line, None, None, pseudoconsole is None, flags, environment,
                                          directory, ctypes.byref(startup), ctypes.byref(self._process)), "Create suspended setup")
            self._check(api.AssignProcessToJobObject(self._job, self._process.hProcess), "Assign setup to Job Object")
            self._assigned = True
            key = self._member_identity(self.pid, self._process.hProcess)
            if key is None:
                raise OSError("Suspended setup process is not associated with its Job")
            self._members[key] = self._process.hProcess
            if api.ResumeThread(self._process.hThread) == DWORD(-1).value:
                raise api.error("Resume contained setup")
            self._resumed = True
        finally:
            if initialized:
                api.DeleteProcThreadAttributeList(attributes)
            for handle in handles:
                api.CloseHandle(handle)
            for descriptor in self._child_fds:
                os.close(descriptor)
            self._child_fds.clear()
            if self._process.hThread:
                api.CloseHandle(self._process.hThread)
                self._process.hThread = None

    @property
    def pid(self):
        return self._process.dwProcessId

    @property
    def closed(self):
        """本 owner 的句柄已释放；不等同于 Job 归零证明成功。"""
        return self._closed

    def _member_identity(self, pid, handle):
        associated = BOOL()
        self._check(self._api.IsProcessInJob(handle, self._job, ctypes.byref(associated)),
                    "Verify setup Job member")
        if not associated.value:
            return None
        created, exited, kernel, user = (ctypes.c_uint64() for _ in range(4))
        self._check(self._api.GetProcessTimes(handle, ctypes.byref(created), ctypes.byref(exited),
                                             ctypes.byref(kernel), ctypes.byref(user)), "Read setup member identity")
        return pid, created.value

    def _capture_members(self):
        capacity = 16
        while True:
            # 官方结构为两个 DWORD 加 ULONG_PTR 可变长数组；Win32/Win64 按
            # 当前指针宽度分配，完整缓冲区读取前不消费截断的 PID 清单。
            buffer = ctypes.create_string_buffer(8 + ctypes.sizeof(SIZE_T) * capacity)
            complete = self._api.QueryInformationJobObject(
                self._job, JobObjectBasicProcessIdList, buffer, len(buffer), None)
            counts = ctypes.cast(buffer, ctypes.POINTER(DWORD))
            assigned, listed = counts[0], counts[1]
            if listed > capacity or listed > assigned:
                raise OSError("Invalid setup Job process list bounds")
            if not complete:
                error = self._api.error("Query setup Job process list")
                if getattr(error, "winerror", None) != 234:  # ERROR_MORE_DATA
                    raise error
            if complete and listed == assigned:
                pids = ctypes.cast(ctypes.addressof(buffer) + 8, ctypes.POINTER(SIZE_T))
                break
            capacity = max(capacity * 2, assigned)
        for pid in pids[:listed]:
            if not 0 < pid <= 0xFFFFFFFF:
                raise OSError("Invalid setup Job member process identifier")
            handle = self._api.OpenProcess(0x00101000, False, pid)  # SYNCHRONIZE | QUERY_LIMITED_INFORMATION
            if not handle:
                # PID 可能在枚举后退出或被回收；这里绝不据此宣称它已安全结束。
                # 最终 TotalProcesses 必须与已持有的唯一真实成员句柄数相等，
                # 捕获前已消失的瞬时成员因此会留下缺口并触发致命失败关闭。
                continue
            try:
                key = self._member_identity(pid, handle)
                if key is not None and key not in self._members:
                    self._members[key] = handle
                    handle = None
            finally:
                if handle is not None:
                    self._api.CloseHandle(handle)

    def _accounting(self):
        accounting = JOBOBJECT_BASIC_ACCOUNTING_INFORMATION()
        self._check(self._api.QueryInformationJobObject(
            self._job, JobObjectBasicAccountingInformation, ctypes.byref(accounting),
            ctypes.sizeof(accounting), None), "Query setup Job active processes")
        if accounting.TotalProcesses < self._total_processes:
            raise WindowsJobCleanupError("Cannot confirm setup Job cumulative member count after counter regression")
        self._total_processes = accounting.TotalProcesses
        return accounting

    def _root_exitcode(self):
        result = self._api.WaitForSingleObject(self._process.hProcess, INFINITE)
        if result != WAIT_OBJECT_0:
            raise self._api.error("Wait for setup process")
        code = DWORD()
        self._check(self._api.GetExitCodeProcess(self._process.hProcess, ctypes.byref(code)), "Read setup exit code")
        self.returncode = code.value
        return self.returncode

    def wait(self, timeout=None):
        if self._cleanup_error is not None:
            raise self._cleanup_error
        try:
            return self._wait_for_job(timeout)
        except WindowsJobCleanupError as error:
            self._cleanup_error = error
            raise

    def _wait_for_job(self, timeout=None):
        # 仅 stop 首次收尾可以在已有失败后继续尝试终止；公开 wait 始终保留
        # 最初的证明失败。内部等待仍执行原累计计数与逐真实句柄 signaled 屏障。
        if self._quiescent:
            return self.returncode
        deadline = None if timeout is None else time.monotonic() + timeout
        while True:
            self._capture_members()
            accounting = self._accounting()
            if accounting.ActiveProcesses == 0:
                if accounting.TotalProcesses != len(self._members):
                    raise WindowsJobCleanupError(
                        "Cannot confirm every setup Job member: "
                        f"cumulative={accounting.TotalProcesses}, retained={len(self._members)}; "
                        "a transient member may have exited before its handle could be retained"
                    )
                # 计数完整只证明每个成员都有句柄。终止是异步的，必须再逐句柄
                # 等到 signaled；所有等待共用原 deadline，取消/强停后的无预算
                # 清理仍延用既有“未确认结束不得交给恢复”的策略，不设假定宽限期。
                for handle in self._members.values():
                    remaining = None if deadline is None else max(0, deadline - time.monotonic())
                    milliseconds = INFINITE if remaining is None else min(INFINITE - 1, math.ceil(remaining * 1000))
                    result = self._api.WaitForSingleObject(handle, milliseconds)
                    if result == WAIT_TIMEOUT:
                        raise subprocess.TimeoutExpired(self.args, timeout)
                    if result != WAIT_OBJECT_0:
                        raise self._api.error("Wait for setup Job member termination")
                # 等待期间仍可能发生新的合法成员关联；再次核对累计数。只有完整
                # 历史成员都已退出且当前 Job 为空时，才没有本 Job 内的后续创建者。
                confirmed = self._accounting()
                if confirmed.ActiveProcesses == 0 and confirmed.TotalProcesses == len(self._members):
                    result = self._root_exitcode()
                    if self._cleanup_error is None:
                        self._quiescent = True
                    return result
            remaining = None if deadline is None else deadline - time.monotonic()
            if remaining is not None and remaining <= 0:
                raise subprocess.TimeoutExpired(self.args, timeout)
            time.sleep(0.02 if remaining is None else min(0.02, remaining))

    def stop(self):
        if self._cleanup_error is not None and (self._closed or self._stop_attempted):
            raise self._cleanup_error
        if self._quiescent:
            return
        with _ignore_interrupts():
            self._stop_attempted = True
            try:
                try:
                    self._capture_members()
                finally:
                    # 捕获失败也必须请求停止 Job；失败随后进入致命清理错误，
                    # 不能因查询错误让仍可写入的成员被当作普通异常交给事务恢复。
                    self._check(self._api.TerminateJobObject(self._job, 1), "Terminate setup Job Object")
                # TerminateJobObject is asynchronous: a root-process wait alone
                # is insufficient. Do not give recovery an arbitrary grace timer.
                self._wait_for_job()
            except BaseException as exc:
                # 第一次失败才决定终态；后续清理异常只属于这一失败的收尾，不能
                # 用 InvalidHandle 或另一个包装错误替换最初累计成员缺口的证据。
                if self._cleanup_error is None:
                    self._cleanup_error = WindowsJobCleanupError(
                        "Cannot confirm the Windows setup Job is empty; filesystem recovery was not started"
                    )
                    self._cleanup_error.__cause__ = exc
            if self._cleanup_error is not None:
                raise self._cleanup_error

    def communicate(self, body=None, timeout=None, cancel_file=None):
        """并行排空原字节管道；所有等待共用一次 deadline，不能因轮询重置预算。"""
        if body is not None and (not isinstance(body, bytes) or self.stdin is None):
            raise ValueError("Windows Job input requires bytes and stdin=PIPE")
        if self._communicated:
            raise ValueError("Windows Job communicate can only be consumed once")
        self._communicated = True
        deadline = None if timeout is None else time.monotonic() + timeout
        values, errors, workers = {}, [], []

        def transfer(name, stream):
            try:
                if name == "stdin":
                    # write() 可以短写；分片推进，不能把大输入尾部静默丢失。
                    view = memoryview(body or b"")
                    while view:
                        count = stream.write(view)
                        if not count:
                            raise OSError("Windows Job stdin write made no progress")
                        view = view[count:]
                else:
                    chunks = []
                    while chunk := stream.read(65536):
                        chunks.append(chunk)
                    values[name] = b"".join(chunks)
            except BrokenPipeError:
                if name != "stdin":
                    errors.append(OSError("Windows Job output pipe broke"))
            except BaseException as exc:
                errors.append(exc)
            finally:
                stream.close()

        for name in ("stdin", "stdout", "stderr"):
            stream = getattr(self, name)
            if stream is not None:
                worker = threading.Thread(target=transfer, args=(name, stream), daemon=True)
                workers.append(worker)
                worker.start()
        try:
            while True:
                if self._cancel_event.is_set() or (cancel_file is not None and os.path.lexists(cancel_file)):
                    raise WindowsProcessCancelled()
                if errors:
                    raise errors[0]
                remaining = None if deadline is None else deadline - time.monotonic()
                if remaining is not None and remaining <= 0:
                    raise subprocess.TimeoutExpired(self.args, timeout)
                try:
                    self.wait(timeout=0.05 if remaining is None else min(0.05, remaining))
                    break
                except subprocess.TimeoutExpired:
                    continue
        except BaseException:
            self.stop()
            raise
        finally:
            # 只有 Job 全部退出后才 join：此时仅 child 持有的写端均关闭，读者
            # 能见 EOF；不能先等阻塞的 stdin writer，造成输入/输出互相死锁。
            if self._quiescent:
                for worker in workers:
                    worker.join()
        if errors:
            raise errors[0]
        return values.get("stdout"), values.get("stderr")

    def _abort_start(self):
        if not self._process.hProcess:
            return
        if self._assigned:
            if self._resumed:
                self.stop()
            else:
                # 根线程从未恢复，不可能生成后代；此时保有的 CreateProcess
                # 真实句柄足以证明唯一成员退出，不依赖尚未完成的成员身份读取。
                try:
                    self._check(self._api.TerminateJobObject(self._job, 1), "Discard suspended setup Job")
                    self._root_exitcode()
                    self._quiescent = True
                except BaseException as exc:
                    raise WindowsJobCleanupError("Cannot discard suspended setup Job") from exc
            return
        # Assignment failed while still suspended: no user instruction or child
        # can have run. Terminate this never-started process, NOT a running parent
        # as a fallback to Job containment.
        try:
            self._check(self._api.TerminateProcess(self._process.hProcess, 1), "Discard suspended setup")
            if self._api.WaitForSingleObject(self._process.hProcess, INFINITE) != WAIT_OBJECT_0:
                raise self._api.error("Wait for discarded suspended setup")
        except BaseException as exc:
            raise WindowsJobCleanupError("Cannot discard suspended setup; filesystem recovery was not started") from exc

    def _close_handles(self):
        for handle in self._members.values():
            if handle != self._process.hProcess:
                self._api.CloseHandle(handle)
        self._members.clear()
        for descriptor in self._child_fds:
            os.close(descriptor)
        self._child_fds.clear()
        for name in ("stdin", "stdout", "stderr"):
            stream = getattr(self, name)
            if stream is not None:
                stream.close()
        if self._process.hThread:
            self._api.CloseHandle(self._process.hThread)
            self._process.hThread = None
        if self._process.hProcess:
            self._api.CloseHandle(self._process.hProcess)
            self._process.hProcess = None
        if self._job:
            self._api.CloseHandle(self._job)
            self._job = None

    def close(self):
        with _ignore_interrupts():
            if self._closed:
                if self._cleanup_error is not None:
                    raise self._cleanup_error
                return
            try:
                if not self._quiescent:
                    self.stop()
            finally:
                self._close_handles()
                self._closed = True


def supervise_hook(command, parent_pid, parent_created, deadline):
    """受管 bootstrap 的唯一监督入口；不导入项目、manager 或未验核心模块。"""
    if (type(parent_pid) is not int or not 0 < parent_pid <= 0xFFFFFFFF
            or type(parent_created) is not int or parent_created <= 0
            or not math.isfinite(deadline)):
        raise ValueError("Invalid Windows Hook supervision identity or budget")
    if deadline <= time.monotonic():
        sys.stdout.buffer.write(b"{}\n")
        return 0
    api = _Win32API()
    parent = api.OpenProcess(0x00100000 | 0x1000, False, parent_pid)
    if not parent:
        raise api.error("Open Hook parent process")
    process = None
    watcher = None
    host = None
    finished = threading.Event()
    monitor_errors = []
    try:
        created, exited, kernel, user = (ctypes.c_uint64() for _ in range(4))
        if not api.GetProcessTimes(parent, ctypes.byref(created), ctypes.byref(exited), ctypes.byref(kernel), ctypes.byref(user)):
            raise api.error("Read Hook parent process identity")
        if created.value != parent_created:
            raise ValueError("Windows Hook parent identity changed")
        if api.WaitForSingleObject(parent, 0) != WAIT_TIMEOUT:
            raise WindowsProcessCancelled()
        # 宿主可能以 pwsh -Command 再启动 payload pwsh。只核对这一层真实
        # parent 关系，不猜 shell 名称、不展开任意祖先监控链，也不终止祖先。
        snapshot = api.CreateToolhelp32Snapshot(2, 0)
        if snapshot in (None, 0, INVALID_HANDLE_VALUE):
            raise api.error("Read Hook host parent relationship")
        try:
            entry = PROCESSENTRY32W()
            entry.dwSize = ctypes.sizeof(entry)
            found = api.Process32FirstW(snapshot, ctypes.byref(entry))
            host_pid = None
            while found:
                if entry.th32ProcessID == parent_pid:
                    host_pid = entry.th32ParentProcessID
                    break
                found = api.Process32NextW(snapshot, ctypes.byref(entry))
            if not host_pid or api.WaitForSingleObject(parent, 0) != WAIT_TIMEOUT:
                raise WindowsProcessCancelled()
        finally:
            api.CloseHandle(snapshot)
        host = api.OpenProcess(0x00100000 | 0x1000, False, host_pid)
        if not host:
            raise api.error("Open Hook host parent process")
        if not api.GetProcessTimes(host, ctypes.byref(created), ctypes.byref(exited), ctypes.byref(kernel), ctypes.byref(user)):
            raise api.error("Read Hook host parent identity")
        # host PID 只能属于先于 payload 存在的进程；之后复用同一 PID 的新
        # 进程不能延长 Hook 寿命。持有两个真实 handle 后不再按 PID 轮询。
        if not 0 < created.value <= parent_created or api.WaitForSingleObject(host, 0) != WAIT_TIMEOUT:
            raise WindowsProcessCancelled()
        env = dict(os.environ)
        # 忽略用户继承的同名值；真实监督者发布同一台机器上的绝对单调截止时间。
        # 薄桥检查、helper 和 Git 消费剩余量，监督 Job 再覆盖 stdin 和导入等待。
        env["AGENT_WORKFLOW_HOOK_DEADLINE"] = repr(deadline)
        with _defer_interrupts():
            process = WindowsJobProcess(command, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

        def watch_parent():
            while not finished.is_set():
                for handle in (parent, host):
                    result = api.WaitForSingleObject(handle, 25)
                    if result != WAIT_TIMEOUT:
                        if result != WAIT_OBJECT_0:
                            monitor_errors.append(api.error("Watch Hook parent process"))
                        process._cancel_event.set()
                        return

        watcher = threading.Thread(target=watch_parent, daemon=True)
        watcher.start()
        output, error = process.communicate(timeout=max(0, deadline - time.monotonic()))
        if monitor_errors:
            raise monitor_errors[0]
        sys.stdout.buffer.write(output)
        sys.stderr.buffer.write(error)
        return process.returncode
    except (subprocess.TimeoutExpired, WindowsProcessCancelled):
        if process is not None:
            process.stop()
        # 未完成输出一直留在监督者内存，避免半份 JSON 后再追加中性响应。
        sys.stdout.buffer.write(b"{}\n")
        return 0
    finally:
        finished.set()
        if watcher is not None:
            watcher.join()
        if process is not None:
            process.close()
        if host:
            api.CloseHandle(host)
        api.CloseHandle(parent)
