"""宿主能力只读诊断：区分文档合同、已生成配置、版本探测与真实会话验收。"""

from __future__ import annotations

import os
from pathlib import Path
import re
import shutil
import subprocess

from lib.claude_instructions import read_file
from lib.workflow_hook_install import EVENTS
from lib.workflow_hook_settings import hook_mode
from lib.claude_options import parse as parse_claude_options
from .catalog import discover


COMMANDS = {"codex": "codex", "claude": "claude", "antigravity": "agy"}
DOCS = {
    "codex": "https://learn.chatgpt.com/docs/hooks",
    "claude": "https://code.claude.com/docs/en/sub-agents",
    "antigravity": "https://antigravity.google/docs/hooks",
}
FEATURE_DOCS = {
    "block_writes_outside_working_directories": "https://code.claude.com/docs/en/changelog#21314",
    "suffixed_window_env": "https://code.claude.com/docs/en/env-vars",
}
FEATURES = {
    "codex": (("session_start_fork", None), ("session_start_compact", None)),
    "claude": (("background_subagents", None), ("send_message_resume", None),
               ("model_definition_precedence", (2, 1, 251)), ("model_force", (2, 1, 257)),
               ("role_auto_compact_window", (2, 1, 296)), ("suffixed_window_env", (2, 1, 304)),
               ("block_writes_outside_working_directories", (2, 1, 314)),
               ("per_invocation_effort", (2, 1, 292)), ("subagent_default_effort", (2, 1, 316))),
    "antigravity": (("session_start", None),),
}
VERSION = re.compile(r"(?:codex-cli\s+|Claude Code\s+|Antigravity CLI\s+|agy\s+)?"
                     r"(\d+\.\d+\.\d+(?:[-+][A-Za-z0-9.-]+)?)(?:\s+\(Claude Code\))?", re.I)


def client_version(host: str, *, probe: bool, environment: dict) -> dict:
    """默认不启动任何宿主；显式探测只执行固定参数，不返回宿主 stdout/stderr 原文。"""
    command = COMMANDS[host]
    result = {"command": command, "status": "not_probed", "version": None}
    if not probe:
        return result
    executable = shutil.which(command, path=environment.get("PATH", os.defpath))
    if executable is None:
        return result | {"status": "not_found"}
    try:
        # 固定 argv 和短超时；不运行 doctor/login/更新命令，错误文本也不混进诊断输出。
        completed = subprocess.run([executable, "--version"], stdin=subprocess.DEVNULL,
                                   capture_output=True, text=True, timeout=3, check=False, env=environment)
    except subprocess.TimeoutExpired:
        return result | {"status": "timeout"}
    except (OSError, UnicodeError):
        return result | {"status": "probe_failed"}
    if completed.returncode != 0:
        return result | {"status": "probe_failed"}
    # 只接受整行已知版本格式。预发行版本保留标记，不能按稳定版本推定最低版本条件。
    for line in completed.stdout.splitlines():
        match = VERSION.fullmatch(line.strip())
        if match:
            return result | {"status": "version_observed", "version": match[1]}
    return result | {"status": "unrecognized_version"}


def diagnose(host: str, *, project: Path | None = None, probe: bool = False,
             home: Path | None = None, environment: dict | None = None) -> dict:
    """输出有界白名单元数据，不把版本满足条件误报为事件、权限或角色已运行成功。"""
    if host not in COMMANDS:
        raise ValueError("未知宿主")
    environment = dict(os.environ) if environment is None else environment
    client = client_version(host, probe=probe, environment=environment)
    version = client["version"]
    stable = tuple(map(int, version.split("."))) if version and re.fullmatch(r"\d+\.\d+\.\d+", version) else None
    capabilities = []
    for name, minimum in FEATURES[host]:
        eligible = None if minimum is None or stable is None else stable >= minimum
        capabilities.append({"name": name, "documentation": FEATURE_DOCS.get(name, DOCS[host]),
                             "minimum_version": ".".join(map(str, minimum)) if minimum else None,
                             "version_meets_minimum": eligible, "runtime_verified": False})
    mode = "not_inspected"
    options = None
    if project is not None:
        try:
            body = read_file(project / ".agent-workflow/project.yaml")
            mode = hook_mode(body.decode("utf-8")) if body is not None else "not_installed"
            if host == "claude" and body is not None:
                options = parse_claude_options(body.decode("utf-8"))
        except (OSError, ValueError, UnicodeError):
            mode = "invalid_or_unreadable"
    catalog = discover(host, home=home, project=project, env=environment)
    lifecycle = {"recovery_event": "SessionStart(compact)", "runtime_verified": False,
                 "pre_post_compact_registered": False,
                 "reason": "恢复指令通过 SessionStart 注入；不为无恢复上下文作用的事件增加命令或压缩门禁"} if host in {"codex", "claude"} else None
    return {"platform": host, "documentation_snapshot": "2026-10-31", "client": client,
            "documented_capabilities": capabilities,
            "workflow": {"mode": mode, "target_hook_events": [event for event, _ in EVENTS[host]],
                         "generated_configuration_verified": False},
            "configured_claude_options": options, "compaction_lifecycle": lifecycle,
            "execution": catalog.execution, "notes": catalog.notes,
            "runtime_verified": False,
            "verification_boundary": "配置投影和版本信息不证明原生信任、事件触发、模型可用或实际角色完成；应在目标宿主会话验收"}
