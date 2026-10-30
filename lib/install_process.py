"""安装事务内的 setup 进程管理；超时和取消必须先停止写入，再交回事务恢复。"""

from __future__ import annotations

from contextvars import ContextVar
import math
import os
import signal
import subprocess
import time
import threading


class SetupRunError(ValueError):
    """可被安装事务捕获并恢复的超时或取消，而非外层强杀安装器。"""


class SetupRunner:
    def __init__(self, timeout: float | None = None):
        if timeout is not None and (not math.isfinite(timeout) or timeout <= 0):
            raise SetupRunError("安装超时必须为有限正数")
        self.deadline = time.monotonic() + timeout if timeout is not None else None
        self.previous_interrupt = None

    def begin_recovery(self):
        # 应用预算耗尽后仍要允许旧版本恢复，恢复不能继承已经过期的 deadline。
        self.deadline = time.monotonic() + 600
        if threading.current_thread() is threading.main_thread():
            self.previous_interrupt = signal.getsignal(signal.SIGINT)
            signal.signal(signal.SIGINT, signal.SIG_IGN)

    def close(self):
        if self.previous_interrupt is not None:
            signal.signal(signal.SIGINT, self.previous_interrupt)

    @staticmethod
    def stop(process):
        """setup 自成进程组；先终止，再清理仍存活的后代，父进程收割后才返回。"""
        try:os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:pass
        try:process.wait(timeout=2)
        except subprocess.TimeoutExpired:pass
        finally:
            # 即便 shell 已退出，也必须停止忽略 TERM 的孙进程，不能提前释放项目锁。
            try:os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:pass
            process.wait()

    def run(self, command, cwd):
        remaining = self.deadline - time.monotonic() if self.deadline is not None else None
        if remaining is not None and remaining <= 0:
            raise SetupRunError("安装已超时，尚未启动下一阶段")
        process = subprocess.Popen(command, cwd=cwd, start_new_session=True)
        try:
            result = process.wait(timeout=remaining)
        except subprocess.TimeoutExpired as exc:
            self.stop(process)
            raise SetupRunError("安装已超时，setup 进程组已停止") from exc
        except KeyboardInterrupt as exc:
            self.stop(process)
            raise SetupRunError("安装已取消，setup 进程组已停止") from exc
        if result:
            raise subprocess.CalledProcessError(result, command)


ACTIVE_RUNNER: ContextVar[SetupRunner | None] = ContextVar("workflow_install_runner", default=None)
