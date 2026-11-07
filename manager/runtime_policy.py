"""中央 current、项目 follow/pinned 策略及新任务结算门的旁路记录。

binding schema 1 与任务三字段 pin 是旧核心的公开合同；这里的机器策略只在
私有旁路中保存。查询不创建目录，写入复用既有条件发布和跨进程协调锁。
"""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path
import re

from lib import runtime_store as store
from lib.central import role_preferences
from lib.central.runtime_project import Node, Tree, canonical_project, json_bytes, node_id, project_key, unique_json
from .runtime_state import ActivationError, read_state, write_control

CURRENT = "central/current.json"
ACTIVATION = "central/activation.json"
PENDING_PHASES = frozenset({"prepared", "applying", "publishing", "compensating", "conflict"})
_SCOPE: ContextVar[tuple[str, str] | None] = ContextVar("central_activation_scope", default=None)
coordination = role_preferences.coordination


def _private(node: Node) -> dict | None:
    if node.kind == "missing":
        return None
    if node.kind != "file" or node.mode != 0o600:
        raise ActivationError("中央旁路记录必须是私有普通文件")
    value = unique_json(node.payload)
    if not isinstance(value, dict) or type(value.get("schema_version")) is not int or value["schema_version"] != 1:
        raise ActivationError("中央旁路记录版本无效")
    return value


def validate_current(value: dict) -> dict:
    if (not isinstance(value, dict) or set(value) != {"schema_version", "runtime_binding", "previous_binding", "generation"}
            or type(value["schema_version"]) is not int or value["schema_version"] != 1
            or not isinstance(value["generation"], str) or not re.fullmatch(r"[0-9a-f]{32}", value["generation"])):
        raise ActivationError("中央 current 记录结构无效")
    store.validate_binding(value["runtime_binding"])
    if value["previous_binding"] is not None:
        store.validate_binding(value["previous_binding"])
    return value


def current_snapshot(state: Path) -> tuple[Node, dict | None]:
    node = read_state(store.state_root(state), CURRENT)
    value = _private(node)
    return node, validate_current(value) if value is not None else None


def policy_relative(project: Path) -> str:
    return "policies/" + project_key(project) + ".json"


def validate_policy(value: dict, project: Path) -> dict:
    expected = {"schema_version", "project_root", "project_identity", "mode", "runtime_binding"}
    if (not isinstance(value, dict) or set(value) != expected or type(value["schema_version"]) is not int or value["schema_version"] != 1
            or value["project_root"] != str(project) or value["project_identity"] != list(node_id(project.stat()))
            or not isinstance(value["project_identity"], list) or any(type(item) is not int for item in value["project_identity"])
            or not isinstance(value["mode"], str) or value["mode"] not in {"follow", "pinned"}):
        raise ActivationError("项目中央策略或物理身份无效")
    if value["mode"] == "follow":
        if value["runtime_binding"] is not None:
            raise ActivationError("follow 策略不得持有锁定版本")
    else:
        store.validate_binding(value["runtime_binding"])
    return value


def snapshot(state: Path, project: Path) -> tuple[Node, dict]:
    state, project = store.state_root(state), canonical_project(project)
    node = read_state(state, policy_relative(project))
    value = _private(node)
    if value is None:
        # 升级前已有 binding 没有策略记录时采用 follow；只有在尚无中央 current
        # 的迁移阶段，effective_binding 才回退该项目自己的实际绑定。
        value = policy_value(project, "follow")
    return node, validate_policy(value, project)


def policy_value(project: Path, mode: str, binding: dict | None = None) -> dict:
    value = {"schema_version": 1, "project_root": str(project),
             "project_identity": list(node_id(project.stat())), "mode": mode,
             "runtime_binding": store.validate_binding(binding) if binding is not None else None}
    return validate_policy(value, project)


def effective_binding(state: Path, project: Path, *, fallback: dict | None = None) -> dict | None:
    _, policy = snapshot(state, project)
    if policy["mode"] == "pinned":
        return policy["runtime_binding"]
    _, current = current_snapshot(state)
    return current["runtime_binding"] if current else fallback


def pending(state: Path) -> dict | None:
    node = read_state(store.state_root(state), ACTIVATION)
    value = _private(node)
    if value is None:
        return None
    if (not isinstance(value.get("phase"), str) or value["phase"] not in PENDING_PHASES | {"applied", "compensated"}
            or not isinstance(value.get("id"), str) or not re.fullmatch(r"[0-9a-f]{32}", value["id"])):
        raise ActivationError("中央激活记录无效，拒绝猜测结算状态")
    from .central_runtime import _validate_journal
    _validate_journal(value)
    return value if value["phase"] in PENDING_PHASES else None


def ensure_settled(state: Path) -> None:
    value = pending(state)
    if value is not None and _SCOPE.get() != (str(store.state_root(state)), value["id"]):
        raise ActivationError("中央激活尚未结算；先恢复全局事务，暂不允许管理写入或新任务")


@contextmanager
def activation_scope(state: Path, identifier: str):
    """仅当前调用栈获准执行其 prepared 批次，环境变量不能伪造重入授权。"""
    token = _SCOPE.set((str(store.state_root(state)), identifier))
    try:
        yield
    finally:
        _SCOPE.reset(token)


def write_policy(state: Path, project: Path, value: dict, expected: Node) -> None:
    """调用者持协调锁并已完成项目事务后条件发布，不覆盖其他偏好保存。"""
    validate_policy(value, project)
    with Tree(state) as tree:
        write_control(tree, policy_relative(project), json_bytes(value), expected=expected)
