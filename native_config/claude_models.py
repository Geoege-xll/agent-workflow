"""Claude 本机模型菜单和别名投影；配置不是账户能力证明。"""
from __future__ import annotations
from . import storage
from .contracts import CLAUDE_ALIASES, ConfigError, MODEL_ID, unique_json

# 仅读取明确的模型/非凭据路由变量，不输出完整 env 或 token。
ENV_KEYS = ("ANTHROPIC_MODEL", "ANTHROPIC_BASE_URL", "CLAUDE_CODE_SUBAGENT_MODEL",
            "CLAUDE_CODE_SUBAGENT_MODEL_FORCE", "CLAUDE_CODE_EFFORT_LEVEL",
            "CLAUDE_CODE_USE_BEDROCK", "CLAUDE_CODE_USE_MANTLE", "CLAUDE_CODE_USE_VERTEX",
            "CLAUDE_CODE_USE_FOUNDRY", "CLAUDE_CODE_USE_ANTHROPIC_AWS", "AWS_REGION", "AWS_DEFAULT_REGION",
            "AWS_PROFILE", "ANTHROPIC_BEDROCK_BASE_URL", "ANTHROPIC_BEDROCK_MANTLE_BASE_URL",
            "ANTHROPIC_VERTEX_BASE_URL", "ANTHROPIC_VERTEX_PROJECT_ID", "CLOUD_ML_REGION",
            "ANTHROPIC_FOUNDRY_BASE_URL", "ANTHROPIC_FOUNDRY_RESOURCE", "ANTHROPIC_AWS_BASE_URL",
            "ANTHROPIC_AWS_WORKSPACE_ID", "ANTHROPIC_SMALL_FAST_MODEL", "ANTHROPIC_SMALL_FAST_MODEL_AWS_REGION",
            "AWS_ENDPOINT_URL", "AWS_ENDPOINT_URL_BEDROCK", "AWS_ENDPOINT_URL_BEDROCK_RUNTIME",
            "AWS_IGNORE_CONFIGURED_ENDPOINT_URLS", *(f"ANTHROPIC_DEFAULT_{alias.upper()}_MODEL" for alias in CLAUDE_ALIASES))


def inputs(directory, project, environment):
    paths = [directory / "settings.json"]
    if project:
        paths.extend(project / ".claude" / name for name in ("settings.json", "settings.local.json"))
    layers, stamps = [], []
    effective = {key: value for key, value in environment.items() if key in ENV_KEYS or key.startswith("VERTEX_REGION_CLAUDE_")}
    current, current_source = None, None
    for path in paths:
        node = storage.read(path)
        value = unique_json(node.body) if node.body is not None else {}
        if not isinstance(value, dict) or not isinstance(value.get("env", {}), dict):
            raise ConfigError("Claude 模型来源格式无效")
        layers.append(value)
        stamps.append((str(path), node.revision()))
        effective.update({key: entry for key, entry in value.get("env", {}).items()
                          if key in ENV_KEYS or key.startswith("VERTEX_REGION_CLAUDE_")})
        if "model" in value:
            current, current_source = value["model"], str(path)
    if "ANTHROPIC_MODEL" in effective:
        current, current_source = effective["ANTHROPIC_MODEL"], "effective_environment"
    return layers, effective, current, current_source, stamps


def discover(directory, project, environment):
    layers, env, current, _, _ = inputs(directory, project, environment)
    models, seen = [], set()
    def append(identifier, label, source):
        if not isinstance(identifier, str) or not MODEL_ID.fullmatch(identifier) or identifier in seen:
            return
        seen.add(identifier)
        models.append({"id": identifier, "label": "".join(c for c in str(label or identifier) if c.isprintable())[:200],
                       "source": source, "efforts": [], "efforts_verified": False,
                       "usage": "dispatch_alias" if identifier in CLAUDE_ALIASES else "native_definition_only"})
    for alias in CLAUDE_ALIASES:
        mapped = env.get(f"ANTHROPIC_DEFAULT_{alias.upper()}_MODEL")
        # 无效映射不进入标签，避免任意配置载荷被投影到界面。
        mapped = mapped if isinstance(mapped, str) and MODEL_ID.fullmatch(mapped) else None
        append(alias, f"{alias} → {mapped}" if mapped else alias, "official_alias_local_mapping")
    # modelPicker 只有用户设置可生效；项目/local 的同名菜单不能冒充用户模型目录。
    menu = layers[0].get("modelPicker", {})
    options = menu.get("options", []) if isinstance(menu, dict) else []
    if isinstance(options, list):
        for row in options:
            if isinstance(row, str):
                append(row, row, "user_model_picker")
            elif isinstance(row, dict):
                append(row.get("value", row.get("model", row.get("id"))), row.get("label", row.get("name")), "user_model_picker")
    append(current, current, "current_local_configuration")
    return models
