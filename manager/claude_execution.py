"""只读投影 Claude 子 Agent 的配置覆盖来源，不猜测运行中会话或提供方能力。"""

from __future__ import annotations

from lib.role_models import MODEL_ID
from lib.claude_options import validate_window
import re


EFFORT_LEVELS = {"low", "medium", "high", "xhigh", "max"}
CONTROL_KEYS = (
    "CLAUDE_CODE_SUBAGENT_MODEL", "CLAUDE_CODE_SUBAGENT_MODEL_FORCE",
    "CLAUDE_CODE_EFFORT_LEVEL", "CLAUDE_CODE_SUBAGENT_EFFORT",
    "CLAUDE_CODE_FORK_SUBAGENT", "CLAUDE_CODE_DISABLE_BACKGROUND_TASKS",
    "CLAUDE_CODE_AUTO_COMPACT_WINDOW",
)
BOOLEAN_KEYS = {CONTROL_KEYS[1], CONTROL_KEYS[4], CONTROL_KEYS[5]}


def project_controls(sources: list[tuple[str, dict]], environment: dict) -> dict:
    """白名单读取进程环境和三层设置；设置 env 通常覆盖启动 shell 的同名值。

    这里只计算普通本地会话的文件投影。组织策略、--settings、CLI/Agent 调用参数、
    运行中 /model 与 /effort、特殊会话对 env 的处理均不可从这些文件推断。
    非法值只输出状态，不回显可能误填的密钥或任意文本。
    """
    values = {key: (environment[key], "environment") for key in CONTROL_KEYS if key in environment}
    for source, settings in sources:
        entries = settings.get("env", {})
        if not isinstance(entries, dict):
            raise ValueError("Claude env 必须为对象")
        for key in CONTROL_KEYS:
            if key in entries:
                values[key] = (entries[key], source)
    result = {}
    for key, (raw, source) in values.items():
        value = None
        valid = False
        if isinstance(raw, str):
            if key in BOOLEAN_KEYS:
                lowered = raw.lower()
                if lowered in {"1", "true", "yes", "on", "0", "false", "no", "off", ""}:
                    value, valid = lowered in {"1", "true", "yes", "on"}, True
            elif key == "CLAUDE_CODE_SUBAGENT_MODEL":
                value, valid = raw, bool(MODEL_ID.fullmatch(raw))
            elif key == "CLAUDE_CODE_AUTO_COMPACT_WINDOW":
                # 环境变量允许 200k / 1m（>=2.1.304），角色 frontmatter 仍必须用完整整数。
                match = re.fullmatch(r"([0-9]{1,7})([kKmM]?)", raw)
                if match:
                    tokens = int(match[1]) * {"": 1, "k": 1000, "m": 1000000}[match[2].lower()]
                    try:
                        value, valid = validate_window(tokens), True
                    except ValueError:
                        pass
            else:
                # 全局 effort 的 auto/unset 表示交给 API 默认值，不是角色可写的 effort 档位。
                allowed = EFFORT_LEVELS | ({"auto", "unset"} if key == "CLAUDE_CODE_EFFORT_LEVEL" else set())
                value, valid = raw, raw in allowed
        result[key] = {"source": source, "status": "configured" if valid else "invalid",
                       "value": value if valid else None}
    return result


def project_write_scope_guard(sources: list[tuple[str, dict]]) -> dict:
    """只投影一个原生布尔值和来源；不输出 allow/deny 内容或其他权限中的敏感文本。"""
    result = {"value": None, "source": None, "status": "absent", "runtime_verified": False}
    key = "blockWritesOutsideWorkingDirectories"
    for source, settings in sources:
        permissions = settings.get("permissions", {})
        if not isinstance(permissions, dict):
            result.update(value=None, source=source, status="invalid")
        elif key in permissions:
            value = permissions[key]
            result.update(value=value if type(value) is bool else None, source=source,
                          status="configured" if type(value) is bool else "invalid")
    return result


def effective_role(configured: dict, controls: dict, auto_compact_window: int | None = None) -> dict:
    """解析具名非 fork 角色的已知优先级；未知会话默认值明确留空，而非伪造实际模型。"""
    def selection(value, source):
        return {"value": value, "source": source}

    def control(key):
        return controls.get(key, {"value": None, "source": None, "status": "absent"})

    force = control("CLAUDE_CODE_SUBAGENT_MODEL_FORCE")
    if force["status"] == "invalid":
        model = selection(None, "invalid_force_override")
    elif force["value"]:
        forced = control("CLAUDE_CODE_SUBAGENT_MODEL")
        if forced["status"] == "invalid":
            model = selection(None, "invalid_model_override")
        elif forced["value"] not in {None, "inherit"}:
            model = selection(forced["value"], "CLAUDE_CODE_SUBAGENT_MODEL_FORCE + CLAUDE_CODE_SUBAGENT_MODEL")
        else:
            model = selection(None, "main_session_unobserved (forced)")
    elif configured["model"] != "inherit":
        model = selection(configured["model"], "role.model")
    else:
        # 生成的具名角色始终显式带 model: inherit；它也高于 SUBAGENT_MODEL 的普通默认值。
        model = selection(None, "main_session_unobserved (role.model: inherit)")

    global_effort = control("CLAUDE_CODE_EFFORT_LEVEL")
    default_effort = control("CLAUDE_CODE_SUBAGENT_EFFORT")
    if global_effort["status"] != "absent":
        effort = selection(global_effort["value"], "CLAUDE_CODE_EFFORT_LEVEL")
    elif configured["effort"] != "inherit":
        effort = selection(configured["effort"], "role.effort")
    elif default_effort["status"] != "absent":
        effort = selection(default_effort["value"], "CLAUDE_CODE_SUBAGENT_EFFORT (requires >=2.1.316)")
    else:
        effort = selection(None, "session_effort_unobserved")
    window = control("CLAUDE_CODE_AUTO_COMPACT_WINDOW")
    if auto_compact_window is not None:
        validate_window(auto_compact_window)
    # 请求窗口并不等于实际窗口：角色字段只降低继承值，主会话窗口、禁用压缩和特殊会话未知。
    requested_window = window["value"] if window["status"] != "absent" else auto_compact_window
    window_source = ("CLAUDE_CODE_AUTO_COMPACT_WINDOW" if window["status"] != "absent"
                     else "role.autoCompactWindow" if auto_compact_window is not None else "inherited_window_unobserved")
    compaction = {"configured_role": auto_compact_window, "requested": requested_window,
                  "source": window_source, "source_layer": window["source"],
                  "status": window["status"] if window["status"] != "absent" else "configured" if auto_compact_window else "inherited",
                  "actual": None, "runtime_verified": False,
                  "limitation": "角色字段仅降低继承窗口；--agent 主会话不适用；环境变量在被宿主忽略的会话中不覆盖角色字段"}
    return {"configured": configured, "model": model, "effort": effort, "runtime_verified": False,
            "controls": controls,
            "auto_compact_window": compaction,
            "version_requirements": {"model_definition_precedence": ">=2.1.251", "model_force": ">=2.1.257",
                                     "role_auto_compact_window": ">=2.1.296", "suffixed_window_env": ">=2.1.304",
                                     "subagent_default_effort": ">=2.1.316"},
            "assumption": "具名非 fork 角色；未计调用时覆盖、组织策略、模型能力上限及运行中会话设置"}
