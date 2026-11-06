"""角色偏好的字段解析与中央只读快照；不依赖 CLI/TUI 或不可变核心写入。"""

from __future__ import annotations

from contextlib import ExitStack, contextmanager
import hashlib
import os
from pathlib import Path
from threading import local

from . import role_models
from .platform_fs import directory_lock
from .runtime_project import Node, Tree, absolute_directory, json_bytes, unique_json

RELATIVE = "preferences/role-models.json"
FIELDS = ("model", "effort")
_COORDINATION = local()


def validate(value: dict) -> dict:
    """全局文件只接受版本化的模型白名单，不容纳凭据或任意额外配置。"""
    if not isinstance(value, dict) or set(value) != {"schema_version", "role_models"} or type(value["schema_version"]) is not int or value["schema_version"] != 1:
        raise ValueError("全局角色偏好格式无效；未显示配置原文")
    choices = value["role_models"]
    if not isinstance(choices, dict) or set(choices) - set(role_models.HOSTS):
        raise ValueError("全局角色偏好包含未知平台")
    checked = {}
    for host, roles in choices.items():
        if not isinstance(roles, dict) or set(roles) - role_models.ROLES:
            raise ValueError("全局角色偏好包含未知角色")
        checked[host] = {role: role_models.explicit(host, fields) for role, fields in roles.items()}
    return checked


def snapshot(state: Path) -> tuple[Node, dict]:
    """有界且不跟随链接读取；目录或文件不存在时返回空值而不创建状态。"""
    try:
        with Tree(state) as tree:
            node = tree.read(RELATIVE)
    except FileNotFoundError:
        node = Node()
    if node.kind == "missing":
        return node, {}
    try:
        return node, validate(unique_json(node.payload))
    except (ValueError, TypeError, RecursionError, UnicodeError) as exc:
        raise ValueError("全局角色偏好无效，请先显式修复；未显示配置原文") from exc


def payload(choices: dict) -> bytes:
    value = {"schema_version": 1, "role_models": choices}
    validate(value)
    return json_bytes(value)


def resolve(global_choices: dict, project_choices: dict, host: str, role: str) -> tuple[dict, dict]:
    """逐字段取项目、全局、宿主；显式 inherit 总是越过全局直达宿主。"""
    if host not in role_models.HOSTS or role not in role_models.ROLES:
        raise ValueError("未知平台或角色")
    project = project_choices.get(host, {}).get(role, {})
    defaults = global_choices.get(host, {}).get(role, {})
    values, sources = {}, {}
    for field in FIELDS:
        if field in project:
            values[field] = project[field]
            sources[field] = "host" if project[field] == "inherit" else "project"
        elif field in defaults:
            values[field] = defaults[field]
            sources[field] = "host" if defaults[field] == "inherit" else "global"
        else:
            values[field], sources[field] = "inherit", "host"
    return role_models.validate(host, values), sources


def revision(node: Node) -> dict:
    """公开身份只含摘要、权限与 inode，不把适配器或全局正文带入 UI。"""
    return {"kind": node.kind, "sha256": hashlib.sha256(node.payload).hexdigest(),
            "mode": node.mode, "identity": list(node.identity)}


@contextmanager
def coordination(state: Path):
    """所有偏好保存与启用物化共用此短锁；查询/预览不进入创建路径。

    目录通过既有逐段 no-follow 创建器建立为 0700。全局锁先于项目模型锁及
    原生收据锁，避免两个应用实例交错写全局，或 enable 物化已过期默认值。
    """
    key = str(Path(state).absolute())
    process = os.getpid()
    # fork 会复制当前线程的 Python 内存，但子进程没有父进程的重入授权。
    # PID 不同即重新走真实 flock；不能因继承 held 集合跳过跨进程互斥。
    held = getattr(_COORDINATION, "held", set()) if getattr(_COORDINATION, "process", None) == process else set()
    if key in held:
        # 全局事务内部复用既有 commit；只允许当前线程的同一持锁栈重入。
        # 线程集合不承担互斥，其他线程/进程仍必须获得下面真实目录 flock。
        yield
        return
    with ExitStack() as stack:
        stack.enter_context(absolute_directory(state, create=True))
        stack.enter_context(absolute_directory(state / "preferences", create=True))
        try:
            stack.enter_context(directory_lock(state / "preferences", "role-preferences"))
        except BlockingIOError as exc:
            raise ValueError("角色偏好正在由另一管理操作更新，请稍后重试") from exc
        _COORDINATION.held = held
        _COORDINATION.process = process
        held.add(key)
        try:
            yield
        finally:
            held.remove(key)
