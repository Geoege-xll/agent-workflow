"""只读执行官方 agy models；会话目录不等同子代理可接受的模型 tier。"""
from __future__ import annotations
import os
from pathlib import Path
import re
import selectors
import shutil
import signal
import subprocess
import time

TIMEOUT_SECONDS = 6.0
MAX_OUTPUT_BYTES = 1024 * 1024


def executable(environment):
    value = shutil.which("agy", path=environment.get("PATH", os.defpath))
    return str(Path(value).absolute()) if value else None


def parse_output(body):
    text = body.decode("utf-8", errors="strict")
    text = re.sub(r"\x1b\[[0-?]*[ -/]*[@-~]", "", text)
    rows, seen = [], set()
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        # 官方裸文本协议为 slug + 单空白分隔显示名；任何混杂诊断/表头均整批拒绝。
        columns = line.split(None, 1)
        if len(columns) != 2:
            raise ValueError("AGY 目录包含非模型行")
        identifier = columns[0]
        if not re.fullmatch(r"[a-z0-9][a-z0-9._-]{0,127}", identifier) or identifier in seen:
            raise ValueError("AGY 目录标识无效或重复")
        seen.add(identifier)
        label = columns[1] if len(columns) > 1 else identifier
        rows.append({"id": identifier, "label": "".join(c for c in label if c.isprintable())[:200],
                     "source": "official_agy_models", "usage": "session_only", "efforts": [], "efforts_verified": False})
    if not rows:
        raise ValueError("AGY 目录格式无法识别")
    return rows


def query(command, cwd, environment):
    failed = {"status": "failed", "models": [], "notes": ["AGY 本机会话目录读取失败；不会据此生成子代理模型能力。"]}
    if not command or os.name != "posix":
        return failed
    child = None
    try:
        deadline = time.monotonic() + TIMEOUT_SECONDS
        child = subprocess.Popen([command, "models"], cwd=cwd, env=environment, stdin=subprocess.DEVNULL,
                                 stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True)
        output, size = bytearray(), 0
        with selectors.DefaultSelector() as selector:
            for stream, name in ((child.stdout, "stdout"), (child.stderr, "stderr")):
                os.set_blocking(stream.fileno(), False)
                selector.register(stream, selectors.EVENT_READ, name)
            while selector.get_map():
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise ValueError("AGY 目录超时")
                for key, _ in selector.select(remaining):
                    try:
                        chunk = os.read(key.fd, 65536)
                    except BlockingIOError:
                        continue
                    if not chunk:
                        selector.unregister(key.fileobj)
                        continue
                    size += len(chunk)
                    if size > MAX_OUTPUT_BYTES:
                        raise ValueError("AGY 目录输出超限")
                    if key.data == "stdout":
                        output.extend(chunk)
        if child.wait(timeout=max(0.001, deadline - time.monotonic())) != 0:
            return failed
        return {"status": "ready", "models": parse_output(output), "notes": ["来自本机官方 agy models，只代表会话目录。"]}
    except (OSError, ValueError, UnicodeError, subprocess.TimeoutExpired):
        return failed
    finally:
        if child is not None:
            # 总是清理本次查询进程组；父进程退出也不能遗留持有输出管道的后代。
            for sig, timeout in ((signal.SIGTERM, 0.2), (signal.SIGKILL, 0.5)):
                try:
                    os.killpg(child.pid, sig)
                except ProcessLookupError:
                    pass
                except PermissionError:
                    if child.poll() is None:
                        child.send_signal(sig)
                try:
                    child.wait(timeout=timeout)
                except subprocess.TimeoutExpired as exc:
                    if sig == signal.SIGKILL:
                        raise ValueError("AGY 目录进程未能在回收预算内结束") from exc
            child.stdout.close()
            child.stderr.close()
