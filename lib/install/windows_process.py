"""Windows setup children, contained in a Job before their first instruction.

No shell is introduced here. The caller chooses the executable (and is responsible
for disabling shell profiles). Only duplicated standard handles are inherited.
"""

from __future__ import annotations

from contextlib import contextmanager
import ctypes
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


class WindowsJobCleanupError(BaseException):
    """Quiescence could not be proved; do NOT enter transaction recovery.

    Deliberately not an Exception/OSError: the install transaction catches those
    to begin filesystem recovery, which would be unsafe with unconfirmed writers.
    """


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

    def __init__(self, command, cwd, env=None):
        self.args = command
        self.returncode = None
        self._api = _Win32API()
        self._job = None
        self._process = PROCESS_INFORMATION()
        self._assigned = False
        self._quiescent = False
        try:
            with _defer_interrupts():
                self._start(command, cwd, env)
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

    def _standard_handles(self, handles):
        """Duplicate, never mutate/close the parent's stdin (including pipes)."""
        api = self._api
        current = api.GetCurrentProcess()
        for number in (-10, -11, -12):
            source = api.GetStdHandle(DWORD(number).value)
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

    def _start(self, command, cwd, env):
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
            self._standard_handles(handles)
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
