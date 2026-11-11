"""显式、只读模型发现；无旧管理器或中央安装器依赖。"""

from __future__ import annotations

import tomllib
import hashlib
from pathlib import Path

from . import codex_models, storage
from .contracts import (AGY_TIERS, CLAUDE_ALIASES, ConfigError, EFFORT_ID,
                        MODEL_ID, json_bytes, unique_json)


def _config(path):
    node = storage.read(path)
    if node.body is None:
        return {}
    try:
        return tomllib.loads(node.body.decode("utf-8"))
    except (ValueError, UnicodeError, RecursionError) as exc:
        raise ConfigError("官方模型来源配置无效") from exc


def _merged(directory, project):
    config, base = _config(directory / "config.toml"), directory
    if project is not None:
        local = _config(project / ".codex/config.toml")
        config.update(local)
        if "model_catalog_json" in local:
            base = project / ".codex"
    return config, base


def source_stamp(directory, project):
    """只重读目录来源指纹，不再次启动宿主；换源后旧能力证据降为未知。"""
    paths = [directory / "config.toml"]
    config, base = _merged(directory, project)
    if project is not None:
        paths.append(project / ".codex/config.toml")
    explicit = config.get("model_catalog_json")
    if explicit is not None:
        if not isinstance(explicit, str):
            raise ConfigError("模型目录路径无效")
        selected = Path(explicit)
        paths.append(selected if selected.is_absolute() else base / selected)
    return hashlib.sha256(json_bytes([(str(path), storage.read(path).revision()) for path in paths])).hexdigest()


def discover(host, directory, project, environment):
    result = {"host": host, "status": "ready", "models": [], "notes": [], "runtime_verified": False}
    if host == "claude":
        result["models"] = [{"id": name, "label": name, "source": "official_alias", "efforts": [], "efforts_verified": False}
                            for name in CLAUDE_ALIASES]
        result["notes"].append("Full model IDs can be stored in native agent definitions; available models and provider routing remain unverified.")
    elif host == "antigravity":
        result["models"] = [{"id": name, "label": name, "source": "official_build_plugins_schema", "efforts": [], "efforts_verified": True}
                            for name in AGY_TIERS]
        result["notes"].append("flash_lite is documented in build-plugins; the subagents table still lists inherit/flash/pro. Client acceptance remains unverified.")
    else:
        config, base = _merged(directory, project)
        explicit = config.get("model_catalog_json")
        if explicit is not None:
            if not isinstance(explicit, str):
                raise ConfigError("明确模型目录路径无效")
            path = Path(explicit)
            if not path.is_absolute():
                path = base / path
            node = storage.read(path)
            if node.body is None:
                raise ConfigError("明确模型目录缺失")
            data = unique_json(node.body)
            if not isinstance(data, dict) or not isinstance(data.get("models"), list):
                raise ConfigError("明确模型目录格式无效")
            for row in data["models"]:
                if not isinstance(row, dict):
                    raise ConfigError("模型目录条目无效")
                identifier = row.get("slug", row.get("id"))
                if not isinstance(identifier, str) or not MODEL_ID.fullmatch(identifier):
                    continue
                levels = row.get("supported_reasoning_levels")
                if levels is not None and not isinstance(levels, list):
                    raise ConfigError("模型推理目录格式无效")
                efforts = [item.get("effort") if isinstance(item, dict) else item for item in levels or []]
                if any(not isinstance(item, str) or not EFFORT_ID.fullmatch(item) for item in efforts):
                    raise ConfigError("模型推理档位无效")
                result["models"].append({"id": identifier, "label": identifier, "source": "explicit_official_catalog",
                                         "efforts": efforts, "efforts_verified": levels is not None})
        else:
            native = codex_models.query(codex_models.executable(environment), project or directory.parent, environment)
            if native.failure:
                result.update(status="failed")
                result["notes"].append(native.failure)
            else:
                result["models"] = [{"id": row.model, "label": row.label, "source": "official_model_list",
                                      "efforts": list(row.efforts), "default_effort": row.default_effort,
                                      "efforts_verified": True} for row in native.models]
        result["notes"].append("Effort options come from the returned model catalog; model availability and actual execution are not verified.")
    return result
