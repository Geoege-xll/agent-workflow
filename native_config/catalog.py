"""显式、只读模型发现；来源守卫与能力证据独立，不调用推理。"""
from __future__ import annotations
import hashlib
import os
from pathlib import Path
import tomllib

from . import agy_models, claude_models, codex_models, storage
from .contracts import ConfigError, EFFORT_ID, MODEL_ID, json_bytes, unique_json


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


def _explicit(config, base, environment):
    value = config.get("model_catalog_json")
    if value is None or value == "":
        return None
    if not isinstance(value, str):
        raise ConfigError("模型目录路径无效")
    # 显式隔离 HOME 时，~ 也必须解析到同一测试根，不能借用进程真实用户目录。
    selected = Path(value)
    if value == "~" or value.startswith("~/"):
        selected = Path(environment.get("HOME", str(Path.home()))) / value[2:]
    else:
        selected = selected.expanduser()
    return selected if selected.is_absolute() else base / selected


def _metadata(path):
    """凭据只取身份元数据，不读正文；客户端替换同样使旧目录失效。"""
    try:
        return [(info.st_dev, info.st_ino, info.st_mode, info.st_size, info.st_mtime_ns, info.st_ctime_ns)
                for info in (path.lstat(), path.stat())]
    except OSError:
        return None


def source_stamp(directory, project, environment=None, *, host="codex", include_cache=True):
    env = os.environ if environment is None else environment
    if host == "claude":
        _, effective, current, source, paths = claude_models.inputs(directory, project, env)
        material = [host, str(directory), str(project), paths, effective, current, source]
    elif host == "antigravity":
        command = agy_models.executable(env)
        material = [host, str(directory), str(project), command, _metadata(Path(command)) if command else None]
    else:
        paths = [directory / "config.toml"]
        if project:
            paths.append(project / ".codex/config.toml")
        config, base = _merged(directory, project)
        explicit = _explicit(config, base, env)
        if explicit:
            paths.append(explicit)
        command = codex_models.executable(env)
        identity = None
        if include_cache and explicit is None:
            node = storage.read(directory / "models_cache.json")
            try:
                cache = unique_json(node.body) if node.body is not None else {}
                value = cache.get("identity") if isinstance(cache, dict) else None
                identity = hashlib.sha256(value.encode()).hexdigest() if isinstance(value, str) else None
            except (ValueError, TypeError):
                # 默认缓存只作身份失效信号；格式损坏不能让其提供模型或覆盖原生成功结果。
                identity = None
        material = [host, str(directory), str(project), [(str(path), storage.read(path).revision()) for path in paths],
                    command, _metadata(Path(command)) if command else None, _metadata(directory / "auth.json"),
                    {key: env.get(key) for key in ("OPENAI_BASE_URL", "CODEX_HOME")}, identity]
    return hashlib.sha256(json_bytes(material, limit=8 * 1024 * 1024)).hexdigest()


def discover(host, directory, project, environment):
    result = {"host": host, "status": "ready", "models": [], "notes": [], "runtime_verified": False}
    stable_before = source_stamp(directory, project, environment, host=host, include_cache=False)
    if host == "claude":
        result["models"] = claude_models.discover(directory, project, environment)
        result["notes"].append("本机用户菜单、当前配置与别名映射不证明账户可调用；modelSettings 偏好不证明推理档位。完整 ID 仅适用于原生定义，调用偏好使用别名。")
    elif host == "antigravity":
        native = agy_models.query(agy_models.executable(environment), project or Path(environment.get("HOME", str(directory.parent))), environment)
        result["models"] = native["models"]
        result["status"] = native["status"]
        result["notes"].extend(native["notes"])
        result["subagent_models"] = [{"id": name, "label": name, "source": "official_subagents_tier", "usage": "subagent_tier",
                                      "efforts": [], "efforts_verified": False} for name in ("inherit", "flash", "pro")]
        result["notes"].append("agy models 是会话目录；子代理仅证实 inherit / flash / pro，invoke_subagent 参数 schema 未证实，已配置偏好仍需阻断未支持派发。")
    else:
        config, base = _merged(directory, project)
        path = _explicit(config, base, environment)
        if path:
            node = storage.read(path)
            if node.body is None:
                raise ConfigError("明确模型目录缺失")
            data = unique_json(node.body)
            if not isinstance(data, dict) or not isinstance(data.get("models"), list):
                raise ConfigError("明确模型目录格式无效")
            seen = set()
            for row in data["models"]:
                if not isinstance(row, dict) or row.get("visibility", "list") not in {"list", "visible"} or row.get("hidden", False):
                    continue
                identifier = row.get("slug", row.get("id"))
                if not isinstance(identifier, str) or not MODEL_ID.fullmatch(identifier) or identifier in seen:
                    continue
                levels = row.get("supported_reasoning_levels")
                if levels is not None and not isinstance(levels, list):
                    raise ConfigError("模型推理目录格式无效")
                efforts = [item.get("effort") if isinstance(item, dict) else item for item in levels or []]
                if any(not isinstance(item, str) or not EFFORT_ID.fullmatch(item) for item in efforts):
                    raise ConfigError("模型推理档位无效")
                seen.add(identifier)
                label = row.get("display_name")
                label = label if isinstance(label, str) and label else identifier
                result["models"].append({"id": identifier, "label": "".join(c for c in str(label) if c.isprintable())[:200],
                                         "source": "explicit_official_catalog", "efforts": list(dict.fromkeys(efforts)),
                                         "efforts_verified": levels is not None})
        else:
            cwd = project or Path(environment.get("HOME", str(directory.parent)))
            native = codex_models.query(codex_models.executable(environment), cwd, environment)
            if native.failure:
                result["status"] = "failed"
                result["notes"].append(native.failure)
            else:
                seen = set()
                for row in native.models:
                    if row.model in seen:
                        continue
                    seen.add(row.model)
                    result["models"].append({"id": row.model, "label": "".join(c for c in row.label if c.isprintable())[:200], "source": "official_model_list",
                                             "efforts": list(row.efforts), "default_effort": row.default_effort, "efforts_verified": True})
        current = config.get("model")
        if isinstance(current, str) and MODEL_ID.fullmatch(current) and not any(row["id"] == current for row in result["models"]):
            result["models"].append({"id": current, "label": current, "source": "current_local_configuration", "efforts": [], "efforts_verified": False})
        result["notes"].append("推理选项逐模型来自真实目录；目录可见不证明实际模型执行。")
    if source_stamp(directory, project, environment, host=host, include_cache=False) != stable_before:
        raise ConfigError("模型目录查询期间来源或身份已变化；结果已丢弃，请刷新")
    stamp = source_stamp(directory, project, environment, host=host)
    # source_stamp 自身会重读配置；给返回值盖戳前再核对稳定部分，不能在
    # 第一次检查与最终盖戳之间切换提供方/账户后，把旧候选绑定到新身份。
    if source_stamp(directory, project, environment, host=host, include_cache=False) != stable_before:
        raise ConfigError("模型目录最终绑定时来源或身份已变化；结果已丢弃，请刷新")
    result["source_stamp"] = stamp
    return result
