"""调用偏好的唯一只读合同，可原样投影到插件；仅依赖 Python 标准库。

本模块不导入配置服务、安装器或宿主运行器。读取结果只是派发前的逻辑偏好，
由调用方按实际原生工具能力映射；任何结果都不证明运行中的 Agent 已采用参数。
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import stat
import sys

HOSTS = ("codex", "claude", "antigravity")
MAX_BYTES = 1024 * 1024
MAX_RECORDS = 512
FIELDS = ("model", "effort")
_MODEL = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/+@\[\]-]{0,199}\Z")
# 由本脚本物理位置定位固定产品根，支持源码、独立包及插件投影；不搜索 cwd。
PACKAGE_ROOT = Path(__file__).resolve(strict=True).parents[1]
sys.path.insert(0, str(PACKAGE_ROOT))
from product.command_identity import load_identity


_EFFORT = re.compile(r"[a-z][a-z0-9_]{0,31}\Z")


class PreferenceError(ValueError):
    """合同拒绝；诊断不包含配置正文或凭据。"""
    code = "invalid_request"


def _absolute(raw):
    if not isinstance(raw, (str, Path)) or not str(raw) or len(str(raw)) > 4096:
        raise PreferenceError("偏好路径必须是有界绝对路径")
    path = Path(raw)
    if not path.is_absolute() or ".." in path.parts or any(ord(c) < 32 for c in str(path)):
        raise PreferenceError("偏好路径必须是无跳转绝对路径")
    return path


def host_root(host, home=None, environment=None):
    """显式 home 优先作为隔离边界；生产读取尊重宿主用户配置根。"""
    if host not in HOSTS:
        raise PreferenceError("未知平台")
    env = os.environ if environment is None else environment
    base = _absolute(home if home is not None else Path.home())
    suffix = {"codex": ".codex", "claude": ".claude", "antigravity": ".gemini/config"}[host]
    variable = {"codex": "CODEX_HOME", "claude": "CLAUDE_CONFIG_DIR"}.get(host)
    if home is None and variable and env.get(variable):
        return _absolute(Path(env[variable]).expanduser())
    return base / suffix


def preference_path(host, home=None, environment=None):
    return host_root(host, home, environment) / "native-agent-config" / "dispatch-preferences.json"


def _open_directory(path):
    """逐级 no-follow 并持有所有祖先，防止链接与父路径替换逃逸。"""
    path = _absolute(path)
    descriptors, links = [], []
    try:
        descriptors.append(os.open(path.anchor, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW))
        for name in path.parts[1:]:
            parent = descriptors[-1]
            try:
                before = os.stat(name, dir_fd=parent, follow_symlinks=False)
            except FileNotFoundError:
                _check_links(links)
                raise
            if not stat.S_ISDIR(before.st_mode):
                raise PreferenceError("偏好父路径不能是链接或特殊节点")
            child = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent)
            descriptors.append(child)
            after = os.fstat(child)
            if (before.st_dev, before.st_ino) != (after.st_dev, after.st_ino):
                raise PreferenceError("偏好父路径在读取时变化")
            links.append((parent, name, (after.st_dev, after.st_ino)))
        return descriptors, links
    except BaseException:
        for fd in reversed(descriptors):
            os.close(fd)
        raise


def _check_links(links):
    for parent, name, identity in links:
        info = os.stat(name, dir_fd=parent, follow_symlinks=False)
        if not stat.S_ISDIR(info.st_mode) or (info.st_dev, info.st_ino) != identity:
            raise PreferenceError("偏好父路径在读取时变化")


def project_key(project):
    path = _absolute(project)
    descriptors = []
    try:
        descriptors, links = _open_directory(path)
        _check_links(links)
        return str(path)
    except OSError as exc:
        raise PreferenceError("项目必须是已存在且无链接的物理绝对目录") from exc
    finally:
        for fd in reversed(descriptors):
            os.close(fd)


def read_bytes(path):
    """缺失返回 None；损坏、硬链接、特殊文件、变化或危险目录均明确失败。"""
    path = _absolute(path)
    descriptors = []
    try:
        try:
            descriptors, links = _open_directory(path.parent)
        except FileNotFoundError:
            return None
        parent = descriptors[-1]
        try:
            info = os.stat(path.name, dir_fd=parent, follow_symlinks=False)
        except FileNotFoundError:
            _check_links(links)
            return None
        identity = lambda value: (value.st_dev, value.st_ino, value.st_mode, value.st_nlink,
                                  value.st_size, value.st_mtime_ns, value.st_ctime_ns)
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size > MAX_BYTES:
            raise PreferenceError("偏好必须是有界单链接普通文件")
        fd = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
        with os.fdopen(fd, "rb") as stream:
            if identity(os.fstat(stream.fileno())) != identity(info):
                raise PreferenceError("偏好在打开时变化")
            body = stream.read(MAX_BYTES + 1)
            if len(body) > MAX_BYTES or identity(os.fstat(stream.fileno())) != identity(info):
                raise PreferenceError("偏好在读取时变化")
        if identity(os.stat(path.name, dir_fd=parent, follow_symlinks=False)) != identity(info):
            raise PreferenceError("偏好在读取时变化")
        _check_links(links)
        return body
    except OSError as exc:
        raise PreferenceError("偏好无法安全读取") from exc
    finally:
        for fd in reversed(descriptors):
            os.close(fd)


def target_name(value):
    # 调用身份允许插件命名空间（冒号），不把 opaque 清单 ID 或显示名称当主键。
    if not isinstance(value, str) or not 1 <= len(value) <= 200 or value == "*" or any(
            not c.isprintable() or c.isspace() for c in value):
        raise PreferenceError("Agent 必须使用有界原生调用身份")
    return value


def validate_values(host, values, *, edits=False):
    if host not in HOSTS or not isinstance(values, dict) or set(values) - set(FIELDS):
        raise PreferenceError("偏好只接受 model / effort")
    checked = {}
    for field, value in values.items():
        if value is None and edits:
            checked[field] = None
            continue
        if not isinstance(value, str) or not (_MODEL if field == "model" else _EFFORT).fullmatch(value):
            raise PreferenceError("偏好字段必须是安全单行标识或编辑 null")
        if field == "model" and host == "claude" and value not in {"sonnet", "opus", "haiku", "fable", "inherit"}:
            raise PreferenceError("Claude 调用模型仅接受官方别名；完整 ID 请编辑原生定义")
        if field == "effort" and host == "claude" and value not in {"low", "medium", "high", "xhigh", "max"}:
            raise PreferenceError("Claude 推理档位无效")
        if host == "antigravity" and (field == "effort" or value not in {"inherit", "flash", "pro"}):
            raise PreferenceError("Antigravity 子代理仅证实 inherit / flash / pro，无独立 effort")
        checked[field] = value
    return checked


def empty_document(host):
    if host not in HOSTS:
        raise PreferenceError("未知平台")
    return {"schema_version": 1, "host": host, "defaults": {}, "agents": {}, "projects": {}}


def parse_document(body, host):
    if body is None:
        return empty_document(host)
    if not isinstance(body, bytes) or len(body) > MAX_BYTES:
        raise PreferenceError("偏好文件超过容量限制")
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise PreferenceError("偏好包含重复字段")
            result[key] = value
        return result
    def invalid(_):
        raise PreferenceError("偏好包含非有限数字")
    try:
        data = json.loads(body.decode("utf-8"), object_pairs_hook=unique, parse_constant=invalid)
        if (not isinstance(data, dict) or set(data) != {"schema_version", "host", "defaults", "agents", "projects"}
                or type(data["schema_version"]) is not int or data["schema_version"] != 1 or data["host"] != host):
            raise PreferenceError("偏好版本、宿主或字段无效")
        data["defaults"] = validate_values(host, data["defaults"])
        count = 0
        def agents(value):
            nonlocal count
            if not isinstance(value, dict):
                raise PreferenceError("Agent 偏好必须为对象")
            count += len(value)
            if count > MAX_RECORDS:
                raise PreferenceError("偏好记录超过容量限制")
            return {target_name(key): validate_values(host, row) for key, row in value.items()}
        data["agents"] = agents(data["agents"])
        if not isinstance(data["projects"], dict) or len(data["projects"]) > MAX_RECORDS:
            raise PreferenceError("项目偏好超过容量限制")
        for key, row in data["projects"].items():
            # 已存项目可以暂时离线，但键本身必须已是规范的物理绝对路径形状。
            if str(_absolute(key)) != key or not isinstance(row, dict) or set(row) != {"defaults", "agents"}:
                raise PreferenceError("项目偏好格式无效")
            row["defaults"] = validate_values(host, row["defaults"])
            row["agents"] = agents(row["agents"])
        return data
    except (UnicodeError, RecursionError, json.JSONDecodeError) as exc:
        raise PreferenceError("偏好 JSON 格式无效") from exc


def legacy_target(host, agent):
    """只读兼容精确七个 Claude 受管角色，不改文件也不重写 opaque 清单 ID。"""
    identity = load_identity(PACKAGE_ROOT)
    prefix = identity["plugin_name"] + ":"
    if host == "claude" and agent.startswith(prefix) and agent[len(prefix):] in identity["managed_roles"]:
        return identity["legacy_plugin_name"] + ":" + agent[len(prefix):]
    return None


def role_values(document, agents, agent):
    """同一层先用旧键补缺，再由新键逐字段覆盖；不改变跨层优先级。"""
    old = legacy_target(document["host"], agent)
    return {**agents.get(old, {}), **agents.get(agent, {})}


def project_preferences(document, agent, project=None):
    """逐字段继承，未配置字段保持缺失；sources 始终说明最终逻辑来源。"""
    if agent != "*":
        target_name(agent)
    preferences, sources = {}, {field: "host_default" for field in FIELDS}
    layers = [("user_default", document["defaults"]), ("user_agent", role_values(document, document["agents"], agent))]
    if project is not None:
        selected = document["projects"].get(str(project), {"defaults": {}, "agents": {}})
        layers.extend((("project_default", selected["defaults"]), ("project_agent", role_values(document, selected["agents"], agent))))
    for source, values in layers:
        for field, value in values.items():
            preferences[field], sources[field] = value, source
    return {"schema_version": 1, "host": document["host"], "agent": agent,
            "status": "configured" if preferences else "unconfigured", "configured": bool(preferences),
            "preferences": preferences, "sources": sources, "runtime_verified": False}


def resolve_preferences(host, agent, project=None, home=None, environment=None):
    if agent != "*":
        target_name(agent)
    key = project_key(project) if project is not None else None
    body = read_bytes(preference_path(host, home, environment))
    return project_preferences(parse_document(body, host), agent, key)


def main(argv=None):
    parser = argparse.ArgumentParser(description="只读解析派发偏好；不启动服务、不安装组件、不调用模型")
    parser.add_argument("--host", required=True, choices=HOSTS)
    parser.add_argument("--agent", required=True)
    parser.add_argument("--project")
    parser.add_argument("--home", type=Path)
    args = parser.parse_args(argv)
    try:
        result = resolve_preferences(args.host, args.agent, args.project, args.home)
    except (ValueError, OSError):
        print(json.dumps({"error": {"code": "invalid_preferences", "message": "派发偏好损坏或无法安全读取，请修复后重试"}}, ensure_ascii=False))
        return 1
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
