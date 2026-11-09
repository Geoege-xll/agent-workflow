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
JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000
JobObjectBasicAccountingInformation = 1
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

    def __init__(self, command, cwd=None, env=None, *, stdin=None, stdout=None, stderr=None):
        self.args = command
        self.returncode = None
        self._api = _Win32API()
        self._job = None
        self._process = PROCESS_INFORMATION()
        self._assigned = False
        self._quiescent = False
        self.stdin = self.stdout = self.stderr = None
        self._child_fds = []
        self._cancel_event = threading.Event()
        self._communicated = False
        try:
            with _defer_interrupts():
                self._start(command, cwd, env, (stdin, stdout, stderr))
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

    def _start(self, command, cwd, env, streams):
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
            allowed = (HANDLE * len(handles))(*handles)
            self._check(api.UpdateProcThreadAttribute(attributes, 0, PROC_THREAD_ATTRIBUTE_HANDLE_LIST,
                                                     allowed, ctypes.sizeof(allowed), None, None),
                        "Restrict inherited handles")
            startup = STARTUPINFOEXW()
            startup.StartupInfo.cb = ctypes.sizeof(startup)
            startup.StartupInfo.dwFlags = STARTF_USESTDHANDLES
            startup.StartupInfo.hStdInput, startup.StartupInfo.hStdOutput, startup.StartupInfo.hStdError = handles
            startup.lpAttributeList = ctypes.cast(attributes, LPVOID)
            flags = CREATE_SUSPENDED | CREATE_UNICODE_ENVIRONMENT | EXTENDED_STARTUPINFO_PRESENT
            self._check(api.CreateProcessW(None, command_line, None, None, True, flags, environment,
                                          directory, ctypes.byref(startup), ctypes.byref(self._process)), "Create suspended setup")
            self._check(api.AssignProcessToJobObject(self._job, self._process.hProcess), "Assign setup to Job Object")
            self._assigned = True
            if api.ResumeThread(self._process.hThread) == DWORD(-1).value:
                raise api.error("Resume contained setup")
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

    def _active_processes(self):
        accounting = JOBOBJECT_BASIC_ACCOUNTING_INFORMATION()
        self._check(self._api.QueryInformationJobObject(
            self._job, JobObjectBasicAccountingInformation, ctypes.byref(accounting),
            ctypes.sizeof(accounting), None), "Query setup Job active processes")
        return accounting.ActiveProcesses

    def _root_exitcode(self):
        result = self._api.WaitForSingleObject(self._process.hProcess, INFINITE)
        if result != WAIT_OBJECT_0:
            raise self._api.error("Wait for setup process")
        code = DWORD()
        self._check(self._api.GetExitCodeProcess(self._process.hProcess, ctypes.byref(code)), "Read setup exit code")
        self.returncode = code.value
        return self.returncode

    def wait(self, timeout=None):
        if self._quiescent:
            return self.returncode
        deadline = None if timeout is None else time.monotonic() + timeout
        while True:
            if self._active_processes() == 0:
                result = self._root_exitcode()
                self._quiescent = True
                return result
            remaining = None if deadline is None else deadline - time.monotonic()
            if remaining is not None and remaining <= 0:
                raise subprocess.TimeoutExpired(self.args, timeout)
            time.sleep(0.02 if remaining is None else min(0.02, remaining))

    def stop(self):
        if self._quiescent:
            return
        with _ignore_interrupts():
            try:
                self._check(self._api.TerminateJobObject(self._job, 1), "Terminate setup Job Object")
                # TerminateJobObject is asynchronous: a root-process wait alone
                # is insufficient. Do not give recovery an arbitrary grace timer.
                self.wait()
            except BaseException as exc:
                raise WindowsJobCleanupError(
                    "Cannot confirm the Windows setup Job is empty; filesystem recovery was not started"
                ) from exc

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
            self.stop()
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
            try:
                if not self._quiescent:
                    self.stop()
            finally:
                self._close_handles()


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
