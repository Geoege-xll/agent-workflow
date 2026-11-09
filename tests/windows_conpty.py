"""真实 Windows ConPTY 测试通道；进程树生命周期只委托已有 Job owner。"""

from __future__ import annotations

from dataclasses import dataclass, field
import ctypes
import math
import os
import queue
import subprocess
import threading
import time

from lib.install.windows_process import (
    WindowsJobCleanupError, WindowsJobProcess, WindowsProcessCancelled, _defer_interrupts, _ignore_interrupts,
)


# 不使用 ctypes.wintypes 的宿主 long：Mac 导入检查同样必须保留 Win32 ABI 宽度。
DWORD = ctypes.c_uint32
BOOL = ctypes.c_int32
HANDLE = ctypes.c_void_p
HRESULT = ctypes.c_int32
OUTPUT_LIMIT = 4 * 1024 * 1024


class COORD(ctypes.Structure):
    _fields_ = [("X", ctypes.c_int16), ("Y", ctypes.c_int16)]


class ConPTYCleanupError(BaseException):
    """本通道未确认完成收尾，不能以普通测试失败掩盖仍被占用的资源。"""


def _size(columns, rows):
    if any(type(value) is not int or not 1 <= value <= 32767 for value in (columns, rows)):
        raise ValueError("伪控制台尺寸必须是 1..32767 的整数")
    return COORD(columns, rows)


def _timeout(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
        raise ValueError("伪控制台超时必须是有限正数")
    return time.monotonic() + value


def _validate_launch(argv, cwd, env, output_limit):
    # 明确 argv 边界，拒绝 shell 字符串；命令中的空格/Unicode 由 Job owner 原样引用。
    if (not isinstance(argv, (list, tuple)) or not argv
            or any(not isinstance(value, str) or "\0" in value for value in argv)
            or not os.path.isabs(argv[0])):
        raise ValueError("伪控制台需要显式绝对可执行文件和字符串 argv")
    if cwd is not None:
        directory = os.fspath(cwd) if isinstance(cwd, (str, os.PathLike)) else None
        if not isinstance(directory, str) or not os.path.isabs(directory) or "\0" in directory:
            raise ValueError("伪控制台 cwd 必须是绝对目录")
    if env is not None:
        if not isinstance(env, dict):
            raise ValueError("伪控制台环境必须是字符串字典")
        names = set()
        for key, value in env.items():
            if (not isinstance(key, str) or not isinstance(value, str) or not key
                    or "=" in key[1:] or "\0" in key or "\0" in value or key.casefold() in names):
                raise ValueError("伪控制台环境含无效条目或大小写重复名称")
            names.add(key.casefold())
    if type(output_limit) is not int or not 1 <= output_limit <= OUTPUT_LIMIT:
        raise ValueError("伪控制台输出预算必须是 1..4MiB 的整数")


class _ConsoleAPI:
    def __init__(self):
        if os.name != "nt":
            raise OSError("真实 ConPTY 测试通道只可在 Windows 使用")
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        signatures = {
            "CreatePipe": ([ctypes.POINTER(HANDLE), ctypes.POINTER(HANDLE), ctypes.c_void_p, DWORD], BOOL),
            "CreatePseudoConsole": ([COORD, HANDLE, HANDLE, DWORD, ctypes.POINTER(HANDLE)], HRESULT),
            "ResizePseudoConsole": ([HANDLE, COORD], HRESULT),
            "ClosePseudoConsole": ([HANDLE], None),
            "ReadFile": ([HANDLE, ctypes.c_void_p, DWORD, ctypes.POINTER(DWORD), ctypes.c_void_p], BOOL),
            "WriteFile": ([HANDLE, ctypes.c_void_p, DWORD, ctypes.POINTER(DWORD), ctypes.c_void_p], BOOL),
            "OpenThread": ([DWORD, BOOL, DWORD], HANDLE),
            "CancelSynchronousIo": ([HANDLE], BOOL),
            "CloseHandle": ([HANDLE], BOOL),
        }
        for name, (arguments, result) in signatures.items():
            method = getattr(kernel, name)
            method.argtypes, method.restype = arguments, result
            setattr(self, name, method)

    @staticmethod
    def error(operation):
        code = ctypes.get_last_error()
        return ctypes.WinError(code, f"{operation}: {ctypes.FormatError(code)}")

    @staticmethod
    def hresult(result, operation):
        # HRESULT 不能用 GetLastError 解释；失败必须保留原始 32 位状态。
        if result < 0:
            raise OSError(f"{operation} 失败，HRESULT=0x{result & 0xffffffff:08x}")


@dataclass
class _WriteRequest:
    data: bytes
    done: threading.Event = field(default_factory=threading.Event)
    error: BaseException | None = None


class ConPTYProcess:
    """自有伪控制台的测试消费者，raw_output 是合并 stdout/stderr 的原始 VT 字节。

    生命周期控制由调用线程串行调用；输出线程一直排空，输入线程独立阻塞写入。
    wait/expect/write 的预算耗尽会先收尾自有 Job，再抛 TimeoutExpired；Job 的
    fail-closed 归零屏障沿用 WindowsJobProcess，绝不以任意宽限期替代成员结束证明。
    """

    def __init__(self, argv, *, cwd=None, env=None, columns=80, rows=24, output_limit=OUTPUT_LIMIT):
        size = _size(columns, rows)
        _validate_launch(argv, cwd, env, output_limit)
        self.args = tuple(argv)
        self._api = _ConsoleAPI()
        self._output_limit = output_limit
        self._output = bytearray()
        self._condition = threading.Condition()
        self._output_error = None
        self._eof = False
        self._closing = False
        self._closed = False
        self._cancelled = False
        self._input = HANDLE()
        self._output_handle = HANDLE()
        self._console = HANDLE()
        self._process = None
        self._reader = self._writer = self._closer = None
        self._requests = queue.Queue()
        child_input, child_output = HANDLE(), HANDLE()
        try:
            # 复用原 owner 的 SIGINT 延后边界，覆盖 Win32 返回与 Python 属性赋值之间
            # 的窗口；只有引用已归本实例所有后才允许 KeyboardInterrupt 开始收尾。
            with _defer_interrupts():
                if not self._api.CreatePipe(ctypes.byref(child_input), ctypes.byref(self._input), None, 0):
                    raise self._api.error("创建 ConPTY 输入管道")
                if not self._api.CreatePipe(ctypes.byref(self._output_handle), ctypes.byref(child_output), None, 0):
                    raise self._api.error("创建 ConPTY 输出管道")
                self._api.hresult(self._api.CreatePseudoConsole(
                    size, child_input, child_output, 0, ctypes.byref(self._console)), "CreatePseudoConsole")
                # drain 先于 Resume 开始，避免 child 启动输出填满管道后与父线程互等。
                self._reader = threading.Thread(target=self._drain, name="awf-conpty-output", daemon=True)
                self._reader.start()
                self._process = WindowsJobProcess(self.args, cwd=cwd, env=env,
                                                   pseudoconsole=self._console.value)
                self._writer = threading.Thread(target=self._feed, name="awf-conpty-input", daemon=True)
                self._writer.start()
        except BaseException:
            # 失败发生在 Job 构造中时，Job owner 已自行处置 suspended process；这里只
            # 释放自己的 HPCON/管道，不重复启动另一套进程监督或按 PID 猜测终止目标。
            for handle in (child_input, child_output):
                if handle.value:
                    self._api.CloseHandle(handle)
                    handle.value = None
            self.close()
            raise
        finally:
            # CreateProcess 完成后必须释放父进程保留的 ConPTY 端点，否则 EOF 无法到达。
            for handle in (child_input, child_output):
                if handle.value:
                    self._api.CloseHandle(handle)

    @property
    def pid(self):
        return None if self._process is None else self._process.pid

    @property
    def returncode(self):
        return None if self._process is None else self._process.returncode

    @property
    def closed(self):
        return self._closed

    @property
    def raw_output(self):
        with self._condition:
            return bytes(self._output)

    def _drain(self):
        buffer, count = ctypes.create_string_buffer(65536), DWORD()
        try:
            while True:
                if not self._api.ReadFile(self._output_handle, buffer, len(buffer), ctypes.byref(count), None):
                    code = ctypes.get_last_error()
                    if code == 109 or (self._closing and code == 995):  # BROKEN_PIPE / OPERATION_ABORTED
                        break
                    raise self._api.error("读取 ConPTY 原始输出")
                if count.value == 0:
                    break
                with self._condition:
                    available = self._output_limit - len(self._output)
                    self._output.extend(buffer.raw[:min(count.value, available)])
                    if count.value > available and self._output_error is None:
                        self._output_error = BufferError("ConPTY 原始输出超过 4MiB 内的声明预算")
                    # 达到上限仍继续排空以保证 ClosePseudoConsole 不死锁；调用者随后
                    # 收到显式失败，保留预算内证据，绝不把截断输出当作完整成功。
                    self._condition.notify_all()
        except BaseException as error:
            with self._condition:
                self._output_error = error
        finally:
            with self._condition:
                self._eof = True
                self._condition.notify_all()

    def _feed(self):
        while True:
            request = self._requests.get()
            if request is None:
                return
            try:
                offset = 0
                while offset < len(request.data):
                    if self._closing:
                        raise WindowsProcessCancelled()
                    part = request.data[offset:offset + 65536]
                    buffer, count = ctypes.create_string_buffer(part), DWORD()
                    if not self._api.WriteFile(self._input, buffer, len(part), ctypes.byref(count), None):
                        raise self._api.error("写入 ConPTY 键盘字节")
                    if not count.value:
                        raise OSError("ConPTY 输入写入没有进展")
                    offset += count.value
            except BaseException as error:
                request.error = error
            finally:
                request.done.set()

    def _check_output(self):
        with self._condition:
            error = self._output_error
        if error is not None:
            self.close()
            raise error

    def _expired(self, timeout):
        self.close()
        raise subprocess.TimeoutExpired(self.args, timeout, output=self.raw_output)

    def write(self, data, *, timeout=5):
        deadline = _timeout(timeout)
        if isinstance(data, str):
            data = data.encode("utf-8")
        if not isinstance(data, bytes) or len(data) > OUTPUT_LIMIT:
            raise ValueError("ConPTY 输入必须是至多 4MiB 的 bytes 或 UTF-8 字符串")
        if self._closing or self._closed:
            raise ValueError("ConPTY 通道已关闭")
        request = _WriteRequest(data)
        self._requests.put(request)
        while not request.done.wait(min(0.05, max(0, deadline - time.monotonic()))):
            self._check_output()
            if time.monotonic() >= deadline:
                self._expired(timeout)
        if request.error is not None:
            self.close()
            raise request.error
        return len(data)

    def send_ctrl_c(self, *, timeout=5):
        # 仅写入本实例 ConPTY 的 ETX。禁止 GenerateConsoleCtrlEvent(0) 或附着到
        # 宿主控制台，否则会把测试取消传播给 runner、其他应用或用户终端。
        return self.write(b"\x03", timeout=timeout)

    def resize(self, columns, rows):
        size = _size(columns, rows)
        if self._closing or self._closed:
            raise ValueError("ConPTY 通道已关闭")
        self._api.hresult(self._api.ResizePseudoConsole(self._console, size), "ResizePseudoConsole")

    def expect(self, marker, *, timeout=10):
        deadline = _timeout(timeout)
        if not isinstance(marker, bytes) or not marker:
            raise ValueError("ConPTY 输出标记必须是非空 bytes")
        while True:
            self._check_output()
            with self._condition:
                if marker in self._output:
                    return bytes(self._output)
                if self._eof:
                    raise EOFError(f"ConPTY 已结束，未观察到标记 {marker!r}")
                remaining = deadline - time.monotonic()
                if remaining > 0:
                    self._condition.wait(min(0.05, remaining))
                    continue
            self._expired(timeout)

    def wait(self, *, timeout=10):
        deadline = _timeout(timeout)
        if self._cancelled:
            self.close()  # 取消不能盖过唯一 Job owner 已记录的致命终止证明失败。
            raise WindowsProcessCancelled()
        if self._closed:
            return self._process.wait()
        while True:
            self._check_output()
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                self._expired(timeout)
            try:
                self._process.wait(timeout=min(0.05, remaining))
                break
            except subprocess.TimeoutExpired:
                continue
            except BaseException:
                self.close()
                raise
        self.close()
        self._check_output()
        return self.returncode

    def cancel(self):
        self._cancelled = True
        self.close()

    def _join_io(self, worker, deadline):
        if worker is None:
            return
        while worker.is_alive():
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise ConPTYCleanupError("ConPTY I/O 线程未确认结束，保留句柄避免 use-after-close")
            # 专用线程不会执行其他业务 IO；重复取消覆盖检查 closing 与进入 Win32
            # 同步调用之间的窄竞态。不关闭仍被 ReadFile/WriteFile 使用的 HANDLE。
            handle = self._api.OpenThread(0x0001, False, worker.native_id)  # THREAD_TERMINATE
            if handle:
                try:
                    if not self._api.CancelSynchronousIo(handle) and ctypes.get_last_error() != 1168:
                        raise self._api.error("取消 ConPTY 同步 I/O")
                finally:
                    self._api.CloseHandle(handle)
            worker.join(min(0.02, remaining))

    def close(self):
        # 与 Job owner 一样，重复 Ctrl+C 不能在句柄归属转移中途打断收尾。
        with _ignore_interrupts():
            self._close()

    def _close(self):
        if self._closed:
            if self._process is not None:
                self._process.close()
            return
        self._closing = True
        # 先让唯一 Job owner 证明所有 child 结束，保持输出 drain 存活；否则旧版
        # Windows 的 ClosePseudoConsole 会因输出管道已满而阻塞当前线程。
        job_error = None
        if self._process is not None:
            try:
                self._process.close()
            except WindowsJobCleanupError as error:
                # Job 已执行一次终止并释放自身句柄，致命终态仍由它保存。通道
                # 必须继续释放自己的 HPCON/I/O，最后原样传播该失败；不自行
                # 操作 Job 私有字段，也不把 HPCON 关闭当成后代结束的替代证明。
                job_error = error
        try:
            self._close_io()
        finally:
            if job_error is not None:
                raise job_error

    def _close_io(self):
        """只释放通道拥有的 HPCON、I/O 线程与管道，不判断 Job 生命周期。"""
        self._requests.put(None)
        deadline = time.monotonic() + 5
        self._join_io(self._writer, deadline)
        if self._console.value:
            if self._closer is None:
                self._closer = threading.Thread(target=self._api.ClosePseudoConsole,
                                                args=(self._console.value,),
                                                name="awf-conpty-close", daemon=True)
                try:
                    self._closer.start()
                except BaseException:
                    self._closer = None
                    raise
            # 前一次收尾未完成时继续等待同一调用，不能向相同 HPCON 再发第二次 close。
            self._closer.join(max(0, deadline - time.monotonic()))
            if self._closer.is_alive():
                raise ConPTYCleanupError("ClosePseudoConsole 未确认完成；输出 drain 仍保留")
            self._console.value = None
        # Thread.start 本身失败时没有挂起 IO；不可 join 从未启动的线程，掩盖原错。
        if self._reader is not None and self._reader.ident is not None:
            self._reader.join(max(0, deadline - time.monotonic()))
            if self._reader.is_alive():
                # EOF 未到达属于清理失败；取消只用于释放自己的读线程，不把证据截断
                # 变成成功。正常路径始终等待 ClosePseudoConsole 后的真实 EOF。
                self._join_io(self._reader, time.monotonic() + 1)
                raise ConPTYCleanupError("ConPTY 输出未观察到真实 EOF")
        for handle in (self._input, self._output_handle):
            if handle.value:
                if not self._api.CloseHandle(handle):
                    raise self._api.error("关闭 ConPTY 自有管道")
                handle.value = None
        self._closed = True

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()
