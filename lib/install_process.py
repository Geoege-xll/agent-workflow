"""安装事务内的 setup 进程管理；超时和取消必须先停止写入，再交回事务恢复。"""

from __future__ import annotations

from contextvars import ContextVar
import math
import os
import signal
import subprocess
import time
import threading

try:
    from .windows_process import WindowsJobProcess, _defer_interrupts
except ImportError:
    from windows_process import WindowsJobProcess, _defer_interrupts


CANCEL_FILE_ENV = "AGENT_WORKFLOW_CANCEL_FILE"


class _SetupCancelled(Exception):
    pass


class SetupRunError(ValueError):
    """可被安装事务捕获并恢复的超时或取消，而非外层强杀安装器。"""


class SetupRunner:
    def __init__(self, timeout: float | None = None):
        if timeout is not None and (not math.isfinite(timeout) or timeout <= 0):
            raise SetupRunError("安装超时必须为有限正数")
        self.deadline = time.monotonic() + timeout if timeout is not None else None
        self.previous_interrupt = None
        # Node owns a private directory and creates this initially absent file on
        # Ctrl+C/timeout, then waits for Python to finish recovery. Never depend
        # on Node forwarding console signals, or let Node kill this installer.
        self.cancel_file = os.environ.get(CANCEL_FILE_ENV) or None
        self.recovering = False

    def begin_recovery(self):
        # 应用预算耗尽后仍要允许旧版本恢复，恢复不能继承已经过期的 deadline。
        self.recovering = True
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
        if os.name == "nt":
            process.stop()
            return
        try:os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:pass
        try:process.wait(timeout=2)
        except subprocess.TimeoutExpired:pass
        finally:
            # 即便 shell 已退出，也必须停止忽略 TERM 的孙进程，不能提前释放项目锁。
            try:os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:pass
            process.wait()

    def _wait(self, process, remaining, cancel_file):
        if cancel_file is None:
            # Preserve the original POSIX wait (including existing mocks) when
            # the optional Node cancellation channel is not in use.
            return process.wait(timeout=remaining)
        while True:
            if os.path.lexists(cancel_file):
                raise _SetupCancelled()
            remaining = self.deadline - time.monotonic() if self.deadline is not None else None
            if remaining is not None and remaining <= 0:
                raise subprocess.TimeoutExpired(process.args, 0)
            try:
                return process.wait(timeout=0.1 if remaining is None else min(0.1, remaining))
            except subprocess.TimeoutExpired:
                # Check both cancellation and the transaction's absolute budget,
                # not a fresh timeout for each poll or setup phase.
                continue

    def run(self, command, cwd, env=None):
        remaining = self.deadline - time.monotonic() if self.deadline is not None else None
        if remaining is not None and remaining <= 0:
            raise SetupRunError("安装已超时，尚未启动下一阶段")
        cancel_file = None if self.recovering else self.cancel_file
        if cancel_file is not None and os.path.lexists(cancel_file):
            raise SetupRunError("安装已取消，尚未启动下一阶段")
        windows = os.name == "nt"
        options = {"cwd": cwd}
        # Keep the old Popen invocation exactly when env is not supplied.
        if env is not None:
            options["env"] = env
        if windows:
            result = self._run_windows(command, options, remaining, cancel_file)
        else:
            process = subprocess.Popen(command, start_new_session=True, **options)
            try:
                result = self._wait(process, remaining, cancel_file)
            except subprocess.TimeoutExpired as exc:
                self.stop(process)
                raise SetupRunError("安装已超时，setup 进程组已停止") from exc
            except (KeyboardInterrupt, _SetupCancelled) as exc:
                self.stop(process)
                raise SetupRunError("安装已取消，setup 进程组已停止") from exc
        if result:
            raise subprocess.CalledProcessError(result, command)

    def _run_windows(self, command, options, remaining, cancel_file):
        process = None
        try:
            try:
                # Cover the constructor-to-local-assignment gap as well as the
                # backend's native spawn. No Ctrl+C can orphan a running Job.
                with _defer_interrupts():
                    process = WindowsJobProcess(command, **options)
            except OSError as exc:
                raise SetupRunError(f"无法启动受控 Windows setup（不会降级为仅终止父进程）：{exc}") from exc
            remaining = self.deadline - time.monotonic() if self.deadline is not None else None
            return self._wait(process, remaining, cancel_file)
        except subprocess.TimeoutExpired as exc:
            if process is not None:
                process.stop()
            raise SetupRunError("安装已超时，setup Job 已停止") from exc
        except (KeyboardInterrupt, _SetupCancelled) as exc:
            if process is not None:
                process.stop()
            raise SetupRunError("安装已取消，setup Job 已停止") from exc
        except BaseException:
            # A Win32 query failure also must not hand a live writer to
            # filesystem recovery. Unconfirmed cleanup is a fatal backend
            # error, deliberately outside the transaction's recovery catch.
            if process is not None:
                process.stop()
            raise
        finally:
            if process is not None:
                process.close()


ACTIVE_RUNNER: ContextVar[SetupRunner | None] = ContextVar("workflow_install_runner", default=None)
