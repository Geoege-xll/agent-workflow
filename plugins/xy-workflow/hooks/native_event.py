"""Decode the official Codex PreToolUse event and its exact native rollout."""

from dataclasses import dataclass
import re
from pathlib import Path

from lib.agent_continuation import validate_reference
from lib.safe_text import open_file
from lib.task_graph_records import decode


MAX_ROW = 512 * 1024
TAIL_LIMIT = 4 * 1024 * 1024


@dataclass(frozen=True)
class Origin:
    thread: str
    cwd: Path
    transcript: Path
    turn: str
    parent: str | None = None
    agent_path: str | None = None


def thread(value):
    return validate_reference({"host": "codex", "agent_id": value}, "native Codex identity")["agent_id"]


def origin(event):
    session, turn = thread(event["session_id"]), thread(event["turn_id"])
    transcript = Path(event["transcript_path"])
    if (not transcript.is_absolute() or transcript.suffix != ".jsonl"
            or ".." in transcript.parts):
        raise ValueError("invalid Codex transcript path")
    with open_file(transcript) as stream:
        row = stream.readline(MAX_ROW + 1) if stream else b""
    if not row or len(row) > MAX_ROW or not row.endswith(b"\n"):
        raise ValueError("missing bounded native session metadata")
    entry = decode(row)
    metadata = entry["payload"]
    if entry["type"] != "session_meta":
        raise ValueError("unexpected first native transcript item")
    cwd = Path(metadata["cwd"])
    if not cwd.is_absolute() or ".." in cwd.parts:
        raise ValueError("invalid native session cwd")
    cwd = cwd.resolve(strict=True)
    source = metadata["source"]
    subagent = source.get("subagent") if isinstance(source, dict) else None
    agent = event.get("agent_id")
    if agent is None and subagent is None and metadata["id"] == session:
        return Origin(session, cwd, transcript, turn)
    # 子会话只接受宿主给出的本线程 ID 及首次元数据中真实的父线程。
    # 显示昵称和角色是描述字段，不能用于授权。不同发行版可绑定原生路径或 UUID。
    spawn = subagent["thread_spawn"] if isinstance(subagent, dict) else {}
    parent = thread(spawn.get("parent_thread_id"))
    agent = thread(agent)
    if (metadata["id"] != agent or session != parent or parent == agent
            or type(spawn.get("depth")) is not int or spawn["depth"] != 1):
        raise ValueError("native child evidence does not match the event")
    path = spawn.get("agent_path")
    if path is not None and (not re.fullmatch(r"/root(?:/[a-zA-Z0-9_.-]+)+", thread(path))
                             or metadata.get("agent_path") != path):
        raise ValueError("inconsistent native agent path")
    return Origin(agent, cwd, transcript, turn, parent, path)


def recent_events(owner):
    """只从本次宿主给出的单份记录读末段，保持原始事件类型和顺序。"""
    with open_file(owner.transcript) as stream:
        if stream is None:
            return
        size = stream.seek(0, 2)
        start = max(0, size - TAIL_LIMIT)
        stream.seek(start)
        if start:
            stream.readline(MAX_ROW + 1)
        remaining = size - stream.tell()
        while remaining > 0:
            row = stream.readline(min(MAX_ROW + 1, remaining))
            if not row or len(row) > MAX_ROW or not row.endswith(b"\n"):
                raise ValueError("incomplete bounded native transcript tail")
            remaining -= len(row)
            yield decode(row)


def user_item(entry, owner):
    if entry.get("type") != "event_msg":
        return None
    payload = entry["payload"]
    if (payload.get("type"), payload.get("thread_id")) != ("item_completed", owner.thread):
        return None
    item = payload["item"]
    if item.get("type") != "UserMessage":
        return None
    parts = item["content"]
    text = parts[0].get("text") if len(parts) == 1 and parts[0].get("type") == "text" else None
    return payload.get("turn_id"), text


def current_user_message(owner):
    """只认同一线程和轮次的宿主 UserMessage，忽略模型、工具和合成 HookPrompt。"""
    messages = [message for entry in recent_events(owner)
                if (user := user_item(entry, owner)) is not None
                for turn, message in (user,) if turn == owner.turn]
    return messages[0] if len(messages) == 1 else None


def previous_launcher_result(owner, argv, invocations):
    """将前一用户轮的固定启动器调用与原生工具输出按 call_id 配对。"""
    import shlex
    pending = None
    response = None
    invocation = False
    for entry in recent_events(owner):
        user = user_item(entry, owner)
        if user is not None:
            if user[0] == owner.turn:
                return response
            invocation = user[1] in invocations
            pending, response = None, None
        if not invocation or entry.get("type") != "response_item":
            continue
        item = entry["payload"]
        if item.get("type") == "function_call" and item.get("name") in {"exec_command", "shell_command", "Bash"}:
            arguments = decode(item["arguments"].encode())
            cmd = arguments.get("cmd", arguments.get("command"))
            if isinstance(cmd, str) and shlex.split(cmd) == argv:
                pending, response = item["call_id"], None
        if pending and item.get("type") == "function_call_output" and item.get("call_id") == pending:
            pending = None
            output = item.get("output")
            if isinstance(output, str):
                # 终端本身可能在结构化 stdout 前附加退出码/输出标题；仅接受一个独立 JSON 对象。
                lines = [line for line in output.splitlines() if line.startswith("{")]
                if len(lines) == 1:
                    response = decode(lines[0].encode())
    return None
