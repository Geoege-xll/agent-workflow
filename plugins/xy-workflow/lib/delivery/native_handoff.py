"""只读解包宿主最终结构化结果，不调用模型、不生成 QA 结论或写入工作流状态。

Codex 输入为 exec --output-last-message 保存的最终 QA JSON；Claude／AGY 输入为
单个终端 JSON。此边界不拼接事件流、不提取代码围栏，也不从自由文本修复结果。
内层 QA 的方法、固定范围和规范语义由 qa_handoff_cli 的既有校验器负责。
"""

from __future__ import annotations

# 直接脚本只信任自身物理位置确定的核心根，避免异 cwd 或 PYTHONPATH 中的
# 同名模块劫持内部依赖；正常包导入沿用调用方已选择的固定核心。
if not __package__:
    import sys as _sys
    from pathlib import Path as _Path
    _sys.path.insert(0, str(_Path(__file__).resolve().parents[2]))

import json
import math
from pathlib import Path
import sys
from typing import Any

try:
    from lib.safe_text import read_file
    from lib.task_graph_records import decode
except ImportError:
    from lib.safe_text import read_file
    from lib.task_graph_records import decode


HOSTS = ("codex", "claude", "antigravity")
MAX_HANDOFF_BYTES = 4 * 1024 * 1024


class NativeHandoffError(ValueError):
    """终端封装或安全读取失败；错误不回显可能含私密正文的原生载荷。"""


def decode_handoff_json(body: bytes) -> Any:
    """复用 UTF-8 记录解析器拒绝重复键，再核对整棵树，错误不回显正文或字段名。"""
    try:
        value = decode(body)
        # 默认解析可接受 NaN／Infinity，指数溢出也可产生 inf。键和值中转义后
        # 残留的孤立代理字符，同样须在解包或输出前拒绝，包括错误或未知元数据。
        pending = [value]
        while pending:
            current = pending.pop()
            if isinstance(current, float) and not math.isfinite(current):
                raise ValueError("non-finite JSON number")
            if isinstance(current, str):
                current.encode("utf-8", errors="strict")
            elif isinstance(current, dict):
                pending.extend(current.keys())
                pending.extend(current.values())
            elif isinstance(current, list):
                pending.extend(current)
        return value
    except (ValueError, RecursionError):
        raise NativeHandoffError("QA 输入必须是单个有效 UTF-8 JSON，且无重复键、非有限数或非法字符") from None


def _read(path: Path) -> bytes:
    """复用 4 MiB 安全 reader，不 resolve 用户路径，并核对读取期间的文件身份。

    reader 拒绝符号链接、硬链接、特殊节点和链接父目录；不先 resolve，以免把
    不安全输入转换成看似正常的目标路径。结束时复核节点，拒绝截断或替换后的结果。
    """
    try:
        if ".." in path.parts:
            raise ValueError("parent traversal")
        path = path.absolute()
        before = path.lstat()
        body = read_file(path)
        after = path.lstat()
        identity = lambda info: (info.st_dev, info.st_ino, info.st_mode, info.st_nlink,
                                 info.st_size, info.st_mtime_ns, info.st_ctime_ns)
        if body is None or identity(before) != identity(after) or len(body) != before.st_size:
            raise ValueError("input changed")
        return body
    except (OSError, ValueError, UnicodeError):
        raise NativeHandoffError("无法安全读取 QA 输入：须为稳定、无链接父目录的单链接普通 UTF-8 文件，且不超过 4 MiB") from None


def read_handoff_json(path: Path | None) -> Any:
    """文件与 stdin 使用同一 UTF-8 JSON 边界。stdin 是字节流，不能依当前终端编码转换。"""
    if path is not None:
        return decode_handoff_json(_read(path))
    try:
        body = sys.stdin.buffer.read(MAX_HANDOFF_BYTES + 1)
    except OSError:
        raise NativeHandoffError("无法从 stdin 读取 QA 输入") from None
    if len(body) > MAX_HANDOFF_BYTES:
        raise NativeHandoffError("QA stdin 输入不能超过 4 MiB")
    return decode_handoff_json(body)


def extract_native_handoff(host: str, path: Path) -> dict[str, Any]:
    """只证明传输终止成功，原样返回内层对象；FAIL 不改写为 PASS。

    不依赖可选用量判断 QA 成败；AGY response 若有非空正文，必须与结构化对象一致，
    防止两份相互冲突的结果由调用方任意选用。未知内层 findings／metadata 全部保留。
    """
    if host not in HOSTS:
        raise NativeHandoffError("不支持的原生宿主")
    terminal = read_handoff_json(path)
    if not isinstance(terminal, dict):
        raise NativeHandoffError("原生终端输入必须是 JSON 对象")
    if host == "codex":
        # Codex 最终文件直接包含 QA 对象，不是 review 的事件流或 result 封装。
        # 即使失败事件内夹带完整 QA 字段，也不能凭这些字段冒充成功的最终消息。
        status = terminal.get("status")
        if terminal.get("type") in (
            "thread.started", "turn.started", "turn.completed", "turn.failed",
            "turn.cancelled", "turn.canceled", "turn.incomplete",
            "item.started", "item.updated", "item.completed", "error",
        ) or (isinstance(status, str) and status.upper() in (
            "FAILED", "FAILURE", "ERROR", "CANCELLED", "CANCELED", "PARTIAL",
            "INCOMPLETE", "RUNNING", "PENDING",
        )):
            raise NativeHandoffError("Codex 输入必须是最终 QA 对象，不能是事件或失败／部分结果")
        payload = terminal
    elif host == "claude":
        # is_error 必须是 JSON false；0 与 False 在 Python 中相等，不能用宽松相等。
        if (terminal.get("type") != "result" or terminal.get("subtype") != "success"
                or terminal.get("is_error") is not False):
            raise NativeHandoffError("Claude 输入必须是成功且无错误的终端 result")
        payload = terminal.get("structured_output")
    else:
        conversation_id = terminal.get("conversation_id")
        if (terminal.get("status") != "SUCCESS" or not isinstance(conversation_id, str)
                or not conversation_id.strip()):
            raise NativeHandoffError("AGY 输入必须有 conversation_id 且为 SUCCESS 终端结果")
        payload = terminal.get("structured_output")
        if "usage" in terminal and not isinstance(terminal["usage"], dict):
            raise NativeHandoffError("AGY 可选 usage 必须是对象")
        if "response" in terminal:
            response = terminal["response"]
            if not isinstance(response, str):
                raise NativeHandoffError("AGY 可选 response 必须是字符串")
            if response:
                decoded_response = decode_handoff_json(response.encode("utf-8"))
                # 用规范 JSON 比较保持布尔／数值等原类型差异，不让 True == 1 掩盖冲突。
                canonical = lambda value: json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False)
                if canonical(decoded_response) != canonical(payload):
                    raise NativeHandoffError("AGY response 与 structured_output 不一致")
    if not isinstance(payload, dict):
        raise NativeHandoffError("原生结构化 QA 结果必须是对象")
    return payload
