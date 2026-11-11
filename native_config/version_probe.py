"""仅显式目录刷新可使用的固定只读版本观察，不启动模型。"""
from __future__ import annotations
import os
import re
import selectors
import shutil
import signal
import subprocess
import time


def observe_claude_version(environment: dict[str, str], *, timeout: float = 3.0) -> dict:
    """显式刷新时只运行官方固定 --version；有界读取并可靠回收进程。

    不执行 shell、不读取 stderr，也不启动模型会话。超过 4096 字节或短超时
    立即杀掉本次独立进程组，避免异常包装器遗留子进程或无限输出占用内存。
    """
    command = shutil.which("claude", path=environment.get("PATH", os.defpath))
    result = {"status": "not_found", "version": None, "runtime_verified": False}
    if command is None:
        return result
    process = None
    try:
        process = subprocess.Popen([command, "--version"], stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                   stderr=subprocess.DEVNULL, env=environment, start_new_session=True)
        deadline, output = time.monotonic() + timeout, bytearray()
        with selectors.DefaultSelector() as selector:
            selector.register(process.stdout, selectors.EVENT_READ)
            while selector.get_map():
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return result | {"status": "timeout"}
                for key, _ in selector.select(min(remaining, 0.1)):
                    chunk = os.read(key.fileobj.fileno(), 4097 - len(output))
                    if not chunk:
                        selector.unregister(key.fileobj)
                    else:
                        output.extend(chunk)
                        if len(output) > 4096:
                            return result | {"status": "output_limit"}
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return result | {"status": "timeout"}
        if process.wait(timeout=remaining) != 0:
            return result | {"status": "probe_failed"}
        text = output.decode("utf-8", errors="strict").strip()
        match = re.fullmatch(r"(?:Claude Code\s+)?(\d{1,6}\.\d{1,6}\.\d{1,6})(?:\s+\(Claude Code\))?", text)
        if match is None:
            return result | {"status": "unrecognized_version"}
        return result | {"status": "observed", "version": match[1]}
    except subprocess.TimeoutExpired:
        return result | {"status": "timeout"}
    except (OSError, UnicodeError):
        return result | {"status": "probe_failed"}
    finally:
        if process is not None:
            # 即使包装器父进程已退出，也回收仍持有 stdout 的本组后代。
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.wait()
            process.stdout.close()
