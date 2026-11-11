"""独立原生配置合同；不依赖工作流角色、安装记录或中央状态。"""

from __future__ import annotations

import json
from pathlib import Path
import re

HOSTS = ("codex", "claude", "antigravity")
FIELDS = ("model", "effort")
MAX_FILE_BYTES = 1024 * 1024
MAX_REQUEST_BYTES = 64 * 1024
MAX_INVENTORY_BYTES = 16 * 1024 * 1024
MAX_AGENTS = 512
MAX_BATCH = 64
MODEL_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/+@\[\]-]{0,199}\Z")
EFFORT_ID = re.compile(r"[a-z][a-z0-9_]{0,31}\Z")
CLAUDE_EFFORTS = ("low", "medium", "high", "xhigh", "max")
CLAUDE_ALIASES = ("sonnet", "opus", "haiku", "fable")
AGY_TIERS = ("inherit", "flash_lite", "flash", "pro")
DOCUMENTATION = {
    "codex": "https://learn.chatgpt.com/docs/agent-configuration/subagents",
    "claude": "https://code.claude.com/docs/en/sub-agents",
    "antigravity": "https://antigravity.google/docs/subagents?tab=cli",
}


class ConfigError(ValueError):
    """有界合同拒绝；错误中不携带 Agent 正文或原始设置。"""
    code = "invalid_request"


class ConflictError(ConfigError):
    """同一预览的原生来源已经变化，必须重新读取、预览。"""
    code = "conflict"


class UnsupportedFormat(ConfigError):
    """格式合法性或精确编辑边界无法证明，保守拒绝写入。"""
    code = "unsupported_format"


def host_name(host: str) -> str:
    if not isinstance(host, str) or host not in HOSTS:
        raise ConfigError("未知平台")
    return host


def absolute_path(raw: Path | str) -> Path:
    if not isinstance(raw, (Path, str)) or not str(raw) or len(str(raw)) > 4096:
        raise ConfigError("路径必须是有界绝对路径")
    value = Path(raw)
    if not value.is_absolute() or ".." in value.parts or any(ord(char) < 32 for char in str(value)):
        raise ConfigError("路径必须是无跳转的绝对路径")
    return value


def json_bytes(value, *, limit=MAX_REQUEST_BYTES) -> bytes:
    try:
        body = (json.dumps(value, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":")) + "\n").encode()
    except (TypeError, ValueError, UnicodeError, RecursionError) as exc:
        raise ConfigError("输入必须是有界 JSON") from exc
    if len(body) > limit:
        raise ConfigError("输入超过容量限制")
    return body


def unique_json(body: bytes, *, limit=MAX_FILE_BYTES):
    if len(body) > limit:
        raise ConfigError("JSON 超过容量限制")
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ConfigError("JSON 包含重复字段")
            result[key] = value
        return result
    def invalid(_value):
        raise ConfigError("JSON 包含非有限数")
    try:
        return json.loads(body.decode("utf-8"), object_pairs_hook=unique, parse_constant=invalid)
    except (ValueError, UnicodeError, RecursionError) as exc:
        raise ConfigError("JSON 格式无效") from exc


def validate_fields(host: str, fields: dict, *, edits=False) -> dict:
    """只允许原生模型字段；Codex 档位是官方 string 合同，不沿用 AWF 的 ultra 禁令。"""
    host_name(host)
    if not isinstance(fields, dict) or set(fields) - set(FIELDS):
        raise ConfigError("只接受 model / effort 字段")
    result = {}
    for field, value in fields.items():
        if value is None and edits:
            result[field] = None
            continue
        if not isinstance(value, str):
            raise ConfigError("原生字段必须是单行字符串或编辑 null")
        # Codex 没有 model: inherit 这一特殊 TOML 值；界面选择继承以删除字段实现。
        if edits and value == "inherit" and (field == "effort" or host == "codex"):
            result[field] = None
            continue
        if not edits and host == "codex" and value == "inherit":
            raise ConfigError("Codex 原生字段没有 inherit 字面量，请删除字段恢复宿主解析")
        if field == "model" and not MODEL_ID.fullmatch(value):
            raise ConfigError("模型标识无效")
        if field == "effort" and (not EFFORT_ID.fullmatch(value) or
                                  (host == "claude" and value not in CLAUDE_EFFORTS)):
            raise ConfigError("推理档位无效")
        if host == "antigravity" and (field == "effort" or value not in AGY_TIERS):
            raise ConfigError("Antigravity 仅支持官方 model tier，没有独立 effort")
        result[field] = value
    return result
