"""只读访问当前 Codex 宿主目录；协议、容量和子进程生命周期统一在此收口。"""

from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import selectors
import shutil
import signal
import subprocess
import time

from lib.role_models import EFFORTS, MODEL_ID

TIMEOUT_SECONDS = 6.0
MAX_OUTPUT_BYTES = 4 * 1024 * 1024
MAX_PAGES = 20
PAGE_LIMIT = 100


@dataclass(frozen=True)
class NativeModel:
    model: str
    label: str
    efforts: tuple[str, ...]
    default_effort: str | None


@dataclass(frozen=True)
class NativeModels:
    models: tuple[NativeModel, ...] = ()
    failure: str | None = None


class ProtocolError(ValueError):
    """只携带本地定义的诊断，禁止把宿主 stderr 或 JSON-RPC 错误正文传给界面。"""


def _io_failure(stage: str, exc: OSError) -> str:
    """只投影异常类别与 errno，既保留排障依据，也不暴露异常中可能包含的路径/载荷。"""
    return f"原生目录进程无法启动或通信（阶段：{stage}，异常：{type(exc).__name__}，errno：{exc.errno}）"


def executable(env: dict) -> str | None:
    """尊重当前 PATH；测试注入的环境也不会意外借用用户的 Codex 或账户。"""
    command = shutil.which("codex", path=env.get("PATH", os.defpath))
    # 随后会切到所选项目；提前固定可执行文件，不能让相对 PATH 在另一个 cwd 指向别处。
    return str(Path(command).absolute()) if command else None


class _Session:
    def __init__(self, command: str, cwd: Path, env: dict):
        self.deadline = time.monotonic() + TIMEOUT_SECONDS
        self.output_bytes = 0
        self.buffer = bytearray()
        self.stdout_closed = False
        self.messages = 0
        self.selector = selectors.DefaultSelector()
        self.process = None
        self.stage = "spawn"
        try:
            # 独立进程组仅用于回收本次查询及其后代；不传配置覆盖，不启动推理会话。
            self.process = subprocess.Popen([command, "app-server", "--stdio"], cwd=cwd, env=env,
                                            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                            start_new_session=True)
            self.stage = "configure-pipes"
            for stream in (self.process.stdin, self.process.stdout, self.process.stderr):
                os.set_blocking(stream.fileno(), False)
            self.selector.register(self.process.stdout, selectors.EVENT_READ, "stdout")
            self.selector.register(self.process.stderr, selectors.EVENT_READ, "stderr")
        except BaseException as exc:
            stage = self.stage
            try:
                self.close()
            except OSError as cleanup:
                detail = _io_failure(stage, exc) + "；" if isinstance(exc, OSError) else ""
                raise ProtocolError(detail + _io_failure("cleanup", cleanup)) from exc
            if isinstance(exc, OSError):
                raise ProtocolError(_io_failure(stage, exc)) from exc
            raise

    def remaining(self) -> float:
        remaining = self.deadline - time.monotonic()
        if remaining <= 0:
            raise ProtocolError("原生 model/list 查询超时")
        return remaining

    def receive(self) -> None:
        self.stage = "poll"
        for key, _ in self.selector.select(self.remaining()):
            self.stage = "read"
            try:
                chunk = os.read(key.fd, 65536)
            except BlockingIOError:
                continue
            if not chunk:
                self.selector.unregister(key.fileobj)
                if key.data == "stdout":
                    self.stdout_closed = True
                continue
            # stderr 也计入总预算但立即丢弃，避免噪声阻塞及私密启动载荷进入日志。
            self.output_bytes += len(chunk)
            if self.output_bytes > MAX_OUTPUT_BYTES:
                raise ProtocolError("原生 model/list 输出超过安全上限")
            if key.data == "stdout":
                self.buffer.extend(chunk)

    def send(self, value: dict) -> None:
        pending = memoryview(json.dumps(value, separators=(",", ":")).encode() + b"\n")
        while pending:
            self.remaining()
            try:
                self.stage = "stdin"
                count = os.write(self.process.stdin.fileno(), pending)
                pending = pending[count:]
            except BlockingIOError:
                # 非阻塞写入与读取共享同一总时限；宿主不读 stdin 也不能挂住界面。
                self.receive()

    def request(self, identifier: str, method: str, params: dict) -> dict:
        self.send({"id": identifier, "method": method, "params": params})
        while True:
            self.remaining()
            if b"\n" not in self.buffer:
                if self.stdout_closed:
                    raise ProtocolError("原生目录进程在返回完整响应前退出（启动环境或协议不可用）")
                self.receive()
                continue
            line, _, tail = self.buffer.partition(b"\n")
            self.buffer = bytearray(tail)
            self.messages += 1
            if self.messages > 2048:
                raise ProtocolError("原生 model/list 消息数量超过安全上限")
            try:
                reply = json.loads(line)
            except (ValueError, UnicodeError, RecursionError) as exc:
                raise ProtocolError("原生 model/list 返回无效 JSON 协议") from exc
            if not isinstance(reply, dict):
                raise ProtocolError("原生 model/list 响应必须为对象")
            if "id" not in reply and isinstance(reply.get("method"), str):
                continue
            if reply.get("id") != identifier:
                raise ProtocolError("原生 model/list 响应 ID 不匹配")
            if "error" in reply:
                raise ProtocolError("原生宿主拒绝目录请求（错误正文已隐藏）")
            if not isinstance(reply.get("result"), dict):
                raise ProtocolError("原生 model/list 缺少有效 result")
            return reply["result"]

    def close(self) -> None:
        """成功、异常及用户取消均回收进程组，不依赖宿主收到 EOF 后自行退出。"""
        process = self.process
        self.stage = "cleanup"
        try:
            if process is not None:
                failure = None
                for sig, timeout in ((signal.SIGTERM, 0.2), (signal.SIGKILL, 0.5)):
                    try:
                        os.killpg(process.pid, sig)
                    except ProcessLookupError:
                        pass
                    except PermissionError as exc:
                        # Darwin 沙箱可能把已消失进程组报作 EPERM；先回收确认父进程已退出。
                        # 活进程若真的无法组清理，仍终止直属进程并如实报告，不能漏掉 wait。
                        if process.poll() is None:
                            failure = exc
                            try:
                                process.send_signal(sig)
                            except ProcessLookupError:
                                pass
                    try:
                        process.wait(timeout=timeout)
                    except subprocess.TimeoutExpired as exc:
                        if sig == signal.SIGKILL:
                            raise ProtocolError("原生目录进程未能在回收时限内结束") from exc
                # 父进程先退出也继续清理该组，避免只等待父进程而留下后代。
                if failure is not None:
                    raise failure
        finally:
            self.selector.close()
            if process is not None:
                for stream in (process.stdin, process.stdout, process.stderr):
                    if stream is not None:
                        stream.close()


def _models(result: dict) -> tuple[list[NativeModel], str | None]:
    rows, cursor = result.get("data"), result.get("nextCursor")
    if not isinstance(rows, list) or (cursor is not None and (not isinstance(cursor, str) or not cursor or len(cursor) > 4096)):
        raise ProtocolError("原生 model/list 的分页结构无效")
    models = []
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get("hidden", False), bool):
            raise ProtocolError("原生 model/list 的模型结构无效")
        if row.get("hidden", False):
            continue
        model, label = row.get("model"), row.get("displayName")
        levels, default = row.get("supportedReasoningEfforts", []), row.get("defaultReasoningEffort")
        if (not isinstance(row.get("id"), str) or not isinstance(model, str) or not MODEL_ID.fullmatch(model)
                or not isinstance(label, str) or not isinstance(levels, list)
                or any(not isinstance(item, dict) or not isinstance(item.get("reasoningEffort"), str) for item in levels)
                or (default is not None and not isinstance(default, str))):
            raise ProtocolError("原生 model/list 的模型字段无效")
        # 配置使用 model 而非不透明的目录 id；未知新档位与 ultra 均不成为可写能力。
        efforts = tuple(dict.fromkeys(item["reasoningEffort"] for item in levels if item["reasoningEffort"] in EFFORTS))
        models.append(NativeModel(model, label, efforts, default if default in EFFORTS else None))
    return models, cursor


def query(command: str | None, cwd: Path, env: dict) -> NativeModels:
    """一次初始化加有界分页，只返回白名单模型字段；失败由目录所有者决定回退。"""
    if os.name != "posix":
        # Windows 的 setup Job 封装不提供此 stdio 会话合同；能力不足时先拒绝，不能启动后漏清理。
        return NativeModels(failure="当前平台缺少可安全回收的原生 stdio 目录接口；请使用显式目录")
    if command is None:
        return NativeModels(failure="当前 PATH 中未找到 codex 可执行文件")
    session = None
    try:
        session = _Session(command, cwd, env)
        try:
            session.request("initialize", "initialize", {"clientInfo": {"name": "agent_workflow_manager", "version": "1"}})
            session.send({"method": "initialized", "params": {}})
            models, seen, cursor = [], set(), None
            for page in range(MAX_PAGES):
                result = session.request(f"models-{page}", "model/list",
                                         {"limit": PAGE_LIMIT, "cursor": cursor, "includeHidden": False})
                rows, cursor = _models(result)
                models.extend(rows)
                if cursor is None:
                    return NativeModels(tuple(models))
                if cursor in seen:
                    raise ProtocolError("原生 model/list 分页游标重复")
                seen.add(cursor)
            raise ProtocolError("原生 model/list 分页超过安全上限")
        finally:
            session.close()
    except ProtocolError as exc:
        return NativeModels(failure=str(exc))
    except OSError as exc:
        return NativeModels(failure=_io_failure(session.stage if session else "spawn", exc))
