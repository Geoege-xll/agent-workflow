"""宿主能力只读诊断：区分文档合同、已生成配置、版本探测与真实会话验收。"""

from __future__ import annotations

import hashlib
import json
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
# 这些条目来自官方文档，不代表当前宿主已加载、已授权或已完成模型运行。
# 审阅界面明确标为人工审阅入口；不能由 /diff 或 /artifact 推出专用 AI review。
AGY_REFERENCE = "https://antigravity.google/docs/cli/reference/"
AGY_HEADLESS = "https://antigravity.google/docs/cli/headless/"
AGY_DISCOVERY = "https://antigravity.google/docs/customization-discovery"
AGY_SUBAGENTS = "https://antigravity.google/docs/subagents?tab=cli"
AGY_CAPABILITIES = {
    "diff_review_ui": {"documentation": AGY_REFERENCE, "interface": "/diff", "kind": "human_review_ui"},
    "artifact_review_ui": {"documentation": AGY_REFERENCE, "interface": "/artifact", "kind": "human_review_ui"},
    "independent_subagents": {"documentation": AGY_SUBAGENTS, "interface": "custom subagents"},
    "send_message_resume": {"documentation": AGY_SUBAGENTS, "interface": "message idle agent",
                            "boundary": "文档描述空闲 Agent 收消息后保留上下文续用；已终止 Agent 不可唤醒"},
    "conversation_resume": {"documentation": AGY_REFERENCE, "interface": "--continue / --conversation / /resume"},
    "context_usage": {"documentation": AGY_REFERENCE, "interface": "/context"},
    "quota_usage": {"documentation": AGY_REFERENCE, "interface": "/usage",
                    "boundary": "模型配额显示不等于本任务已采集 token 用量"},
    "headless_json": {"documentation": AGY_HEADLESS, "interface": "--output-format json / stream-json"},
    "structured_output_schema": {"documentation": AGY_HEADLESS, "interface": "--json-schema"},
    "cumulative_session_usage": {"documentation": AGY_HEADLESS, "interface": "result.usage",
                                 "counter_scope": "cumulative_session",
                                 "boundary": "流式会话 usage 为累计值；读取方须按会话区分，不能逐事件相加"},
    "skill_source_inspection": {"documentation": AGY_DISCOVERY, "interface": "/skills"},
    "skill_reload": {"documentation": AGY_DISCOVERY, "interface": "/skills reload"},
    "native_grill_me": {"documentation": "https://antigravity.google/docs/commands/grill-me/",
                        "interface": "/grill-me", "kind": "native_interview"},
    "native_plan": {"documentation": AGY_REFERENCE, "interface": "/plan", "kind": "native_planning"},
}
FEATURES = {
    "codex": (("session_start_fork", None), ("session_start_compact", None)),
    "claude": (("background_subagents", None), ("send_message_resume", None),
               ("model_definition_precedence", (2, 1, 251)), ("model_force", (2, 1, 257)),
               ("role_auto_compact_window", (2, 1, 296)), ("suffixed_window_env", (2, 1, 304)),
               ("block_writes_outside_working_directories", (2, 1, 314)),
               ("per_invocation_effort", (2, 1, 292)), ("subagent_default_effort", (2, 1, 316))),
    "antigravity": (("session_start", None),) + tuple((name, None) for name in AGY_CAPABILITIES),
}
VERSION = re.compile(r"(?:codex-cli\s+|Claude Code\s+|Antigravity CLI\s+|agy\s+)?"
                     r"(\d+\.\d+\.\d+(?:[-+][A-Za-z0-9.-]+)?)(?:\s+\(Claude Code\))?", re.I)


def client_version(host: str, *, probe: bool, environment: dict) -> dict:
    """默认不启动任何宿主；显式探测只执行固定参数，不返回宿主 stdout/stderr 原文。"""
    command = COMMANDS[host]
    result = {"command": command, "status": "not_probed", "version": None,
              "evidence_level": "runtime_unverified", "runtime_verified": False}
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
            return result | {"status": "version_observed", "version": match[1], "evidence_level": "source_observed"}
    return result | {"status": "unrecognized_version"}


def declared_skill_name(body: bytes) -> str | None:
    """保守识别有界单行 frontmatter；不解析完整 YAML，也不回显任意正文或异常原值。"""
    lines = body.decode("utf-8").splitlines()
    if not lines or lines[0] != "---" or "---" not in lines[1:]:
        return None
    values = {}
    for line in lines[1:lines.index("---", 1)]:
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        match = re.fullmatch(r"([a-z][a-z0-9_-]*):[ \t]*(.+)", line)
        if not match or match[1] in values or not all(char.isprintable() for char in line):
            return None
        value = match[2].strip()
        if not value:
            return None
        # 只接受确定的字符串标量。复杂 YAML 合法性无法确认时保留 unknown，
        # 不把文件名、重复字段、转义控制字符或截断后的字符串当成真实声明。
        if value.startswith('"'):
            try:
                value = json.loads(value)
            except ValueError:
                return None
            if not isinstance(value, str) or not all(char.isprintable() for char in value):
                return None
        elif value.startswith("'"):
            if not re.fullmatch(r"'(?:[^']|'')*'", value):
                return None
            value = value[1:-1].replace("''", "'")
        elif value[0] in "-?:,[]{}#&*!|>%@`" or re.search(r":\s|\s#", value):
            return None
        values[match[1]] = value
    name = values.get("name", "")
    return name if len(name) <= 64 and re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", name) else None


def antigravity_customization_sources(project: Path | None) -> dict:
    """只查明确项目路径，不枚举个人技能、manifest 指向目录或其他自定义来源。"""
    relative = ".agents/skills/grill-me/SKILL.md"
    definition = {"relative_path": relative, "status": "not_inspected", "sha256": None,
                  "declared_name": None, "declaration_status": "unknown",
                  "evidence_level": "runtime_unverified", "runtime_verified": False}
    if project is not None:
        try:
            # 复用安全 reader 的单链接普通文件、父目录、UTF-8 与大小限制；
            # 拒绝来源只返回固定状态，避免错误信息把正文或项目外路径带进输出。
            body = read_file(project / relative)
            definition.update(status="not_found" if body is None else "source_observed",
                              evidence_level="source_observed")
            if body is not None:
                name = declared_skill_name(body)
                definition.update(sha256=hashlib.sha256(body).hexdigest(), declared_name=name,
                                  declaration_status="recognized" if name is not None else "unrecognized")
        except (OSError, ValueError, UnicodeError):
            definition.update(status="invalid_or_unreadable")
    # 同名声明只构成潜在冲突。文档中的优先级还受个人来源、manifest 和当前加载状态影响，
    # 因而绝不根据文件存在或 --version 成功推断当前 /grill-me 已被自定义技能覆盖。
    return {"inspection_scope": "explicit_project_paths_only", "personal_directories_scanned": False,
            "grill_me": {"project_definition": definition,
                         "same_name_risk": "possible" if definition["declared_name"] == "grill-me" else "unknown",
                         "actual_source": {"status": "unknown", "source": None,
                                           "evidence_level": "runtime_unverified", "runtime_verified": False},
                         "documentation": AGY_DISCOVERY + "#which-customization-wins",
                         "verification_hint": "请在当前目标宿主用 /skills 查看实际路径与指令；必要时 /skills reload 后再次核对。doctor 不执行这些命令"}}


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
                             "version_meets_minimum": eligible, "runtime_verified": False,
                             "evidence_level": "documented", "runtime_status": "runtime_unverified",
                             **(AGY_CAPABILITIES.get(name, {}) if host == "antigravity" else {})})
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
    return {"platform": host, "documentation_snapshot": "2026-11-02", "client": client,
            "documented_capabilities": capabilities,
            "customization_sources": antigravity_customization_sources(project) if host == "antigravity" else None,
            "review_boundary": {"dedicated_ai_review": {"status": "not_confirmed_in_reference",
                                 "documentation": AGY_REFERENCE, "evidence_level": "runtime_unverified",
                                 "runtime_verified": False},
                                "reason": "文档列有 diff／Artifact 人工审阅入口；未确认专用 /review AI 审查命令，面板不证明独立 AI 审查已完成"}
                               if host == "antigravity" else None,
            "workflow": {"mode": mode, "target_hook_events": [event for event, _ in EVENTS[host]],
                         "generated_configuration_verified": False},
            "configured_claude_options": options, "compaction_lifecycle": lifecycle,
            "execution": catalog.execution, "notes": catalog.notes,
            "runtime_verified": False, "runtime_status": "runtime_unverified",
            "verification_boundary": "配置投影和版本信息不证明原生信任、事件触发、模型可用或实际角色完成；应在目标宿主会话验收"}
