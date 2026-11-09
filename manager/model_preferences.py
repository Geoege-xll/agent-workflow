"""CLI 与 TUI 共用的按字段偏好计划、目录快照及条件应用服务。"""

from __future__ import annotations

import base64
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import uuid

from lib import role_models, runtime_store
from lib.central import role_preferences
from lib.central.runtime_project import CAPACITY_IDENTITY, CONFIG, Node, Tree, absolute_directory, json_bytes, skill_parts, move_at, read_at, delete_at
from . import project_service, service, runtime_service, runtime_state, state_files, native_agents
from .catalog import Catalog, discover


@dataclass(frozen=True)
class PreferenceCatalogs:
    """一次显式编辑/刷新获取的目录；私有来源范围防止串用另一个项目菜单。"""

    catalog: Catalog
    project_catalogs: dict[str, Catalog]
    _scope: tuple | None = field(default=None, repr=False)
    _registry: Node | None = field(default=None, repr=False)


@dataclass(frozen=True)
class PreferenceContext:
    """一次只读的显示及编辑前像；JSON 属性隔离调用方的草稿修改。"""

    state: Path
    project: Path | None
    host: str
    catalogs: PreferenceCatalogs | None
    _values_json: bytes = field(repr=False)
    _following_json: bytes = field(repr=False)

    @property
    def role_values(self) -> dict:
        return json.loads(self._values_json)

    @property
    def following_values(self) -> dict:
        return json.loads(self._following_json)


def _read(root: Path, relative: str) -> Node:
    try:
        with Tree(root) as tree:
            return tree.read(relative)
    except FileNotFoundError:
        return Node()


def _config(node: Node) -> dict:
    if node.kind == "missing":
        return {}
    try:
        return role_models.parse(node.payload.decode("utf-8"))
    except (ValueError, UnicodeError, RecursionError) as exc:
        raise ValueError("项目角色偏好配置无效；未显示适配器原文") from exc


def _registered(state: Path) -> tuple[Node, tuple[Path, ...]]:
    node = _read(state, "projects.json")
    try:
        data = project_service.parse_registry(node.payload if node.kind == "file" else None)
    except (ValueError, TypeError, RecursionError) as exc:
        raise ValueError("项目登记信息无效；未显示记录原文") from exc
    paths = []
    for raw in data["registered"]:
        path = Path(raw)
        if not path.is_absolute() or ".." in path.parts:
            raise ValueError("登记项目路径必须是物理绝对路径")
        if path not in paths:
            paths.append(path)
    return node, tuple(sorted(paths, key=str))


@runtime_store.read_operation
def roles(state: Path, project: Path | None, host: str, *, native_context=None) -> list[str]:
    if host not in role_models.HOSTS:
        raise ValueError("未知平台")
    return sorted(role_models.ROLES) if project is None else service.roles(state_files.project_path(project), host, state=state, native_context=native_context)


@runtime_store.read_operation
def view(state, project, host, role) -> dict:
    """纯读取有效值和字段来源；明确 inherit 的来源为 host，覆盖仍保留在 overrides。"""
    state = state_files.state_root(state)
    global_node, defaults = role_preferences.snapshot(state)
    config, native, machine = Node(), Node(), Node()
    choices = {}
    if project is not None:
        project = state_files.project_path(project)
        config = _read(project, CONFIG)
        choices = _config(config)
        native = _read(project, service.role_path(project, host, role).relative_to(project).as_posix())
        machine, _ = runtime_service.read_binding_record(state, project)
    return _view(defaults, choices, host, role, project, global_node, config, native, machine)


def _view(defaults, choices, host, role, project, global_node, config, native, machine) -> dict:
    """以调用方已固定的同一组来源推导字段，避免上下文逐角色重读全局配置。"""
    values, sources = role_preferences.resolve(defaults, choices, host, role)
    explicit = (defaults if project is None else choices).get(host, {}).get(role, {})
    return {**values, "sources": sources, "overrides": dict(explicit),
            "revision": {"global": role_preferences.revision(global_node),
                         "project": role_preferences.revision(config),
                         "native": role_preferences.revision(native),
                         "binding": role_preferences.revision(machine)}}


@runtime_store.read_operation
def load_context(state: Path, project: Path | None, host: str, *,
                 catalogs: PreferenceCatalogs | None = None, native_context=None) -> PreferenceContext:
    """只读角色、来源和 reset 跟随值，绝不发现目录或启动原生宿主。

    新上下文仅供显示或新编辑使用；调用方必须保留已有草稿的旧 role_values，
    不能用刷新后的投影替换 expected。附带目录只检查其归属，不自动刷新或续期。
    """
    state = state_files.state_root(state)
    project = state_files.project_path(project) if project is not None else None
    if host not in role_models.HOSTS:
        raise ValueError("未知平台")
    scope = (str(state), str(project) if project else None, host)
    if catalogs is not None and (not isinstance(catalogs, PreferenceCatalogs) or
                                catalogs._scope is not None and catalogs._scope != scope):
        raise ValueError("编辑上下文与模型目录范围不一致")
    global_node, defaults = role_preferences.snapshot(state)
    config = _read(project, CONFIG) if project is not None else Node()
    choices = _config(config)
    machine = runtime_service.read_binding_record(state, project)[0] if project is not None else Node()
    selected_roles = roles(state, project, host, native_context=native_context)
    native = {role: _read(project, service.role_path(project, host, role).relative_to(project).as_posix())
              if project is not None else Node() for role in selected_roles}
    values = {role: _view(defaults, choices, host, role, project, global_node, config, native[role], machine)
              for role in selected_roles}
    following = {}
    for role in selected_roles:
        inherited, sources = role_preferences.resolve(defaults if project is not None else {}, {}, host, role)
        following[role] = {**inherited, "sources": sources}
    # 读取不持创建型锁；用完整节点及角色集合的前后核对拒绝撕裂快照。异常原样
    # 交服务边界处理，已有显示/草稿由 TUI 生命周期保留，不能伪装成空配置成功。
    if (role_preferences.snapshot(state)[0] != global_node or
            roles(state, project, host, native_context=native_context) != selected_roles or
            project is not None and (
                _read(project, CONFIG) != config or
                runtime_service.read_binding_record(state, project)[0] != machine or
                any(_read(project, service.role_path(project, host, role).relative_to(project).as_posix()) != native[role]
                    for role in selected_roles))):
        raise ValueError("角色偏好来源或配置在读取上下文期间变化，请重新读取")
    return PreferenceContext(state, project, host, catalogs, json_bytes(values), json_bytes(following))


def _discover(host, *, project=None, _snapshot=None, native_context=None):
    """模型来源仍按宿主实时权限读取，但配置根只取入口解析过的不可变路径。"""
    if native_context is None:
        return discover(host, project=project, _snapshot=_snapshot)
    import os
    paths = native_context.host_paths
    environment = {**os.environ, "HOME": str(paths.home), "CODEX_HOME": str(paths.codex),
                   "CLAUDE_CONFIG_DIR": str(paths.claude)}
    return discover(host, home=paths.home, project=project, env=environment, _snapshot=_snapshot)


@runtime_store.read_operation
def _active_projects(state: Path, host: str, *, native_context=None) -> tuple[Node, tuple[Path, ...]]:
    registry, projects = _registered(state)
    active = []
    for project in projects:
        # 这里只读取本机登记和宿主归属，不把停用/未管理项目装成活跃目标。损坏
        # 目标由 preview 投影为冲突；加载菜单也不能擅自跳过一个应更新的项目。
        state_files.project_path(project)
        _, record = runtime_service.read_binding_record(state, project)
        if record and record["enabled"] and host in record["hosts"] and service.roles(project, host, state=state, native_context=native_context):
            active.append(project)
    return registry, tuple(active)


@runtime_store.read_operation
def load_catalogs(state: Path, project: Path | None, host: str, *, native_context=None) -> PreferenceCatalogs:
    """仅显式编辑/刷新调用：固定整个批次后逐范围查询，最后发布一致快照。"""
    state = state_files.state_root(state)
    project = state_files.project_path(project) if project is not None else None
    if host not in role_models.HOSTS:
        raise ValueError("未知平台")
    registry, targets = _active_projects(state, host, native_context=native_context) if project is None else (None, ())
    scopes = (project, *targets)
    # 在任何 native 之前固定所有有效来源与登记/活跃集合。此处空快照强制只读，
    # 默认共享缓存只贡献不透明提示，不贡献候选或能力；不能边查边接受新提供方。
    before = [_discover(host, project=target, _snapshot=Catalog(host), native_context=native_context) for target in scopes]
    identities = {}
    for baseline in before:
        if baseline._native_scope is not None:
            key, identity = baseline._native_cache, baseline._native_scope[1]
            if key in identities and identities[key] != identity:
                raise ValueError("模型目录批次准备期间缓存来源已变化，请重新进入编辑")
            identities[key] = identity
    acquired = []
    for target, baseline in zip(scopes, before):
        current = _discover(host, project=target, native_context=native_context)
        if current._native_query is not None:
            start, end = current._native_query
            key = current._native_cache
            if (baseline._native_scope is None or start[0] != baseline._native_scope[0] or
                    key != baseline._native_cache or key not in identities or start[1] != identities[key]):
                raise ValueError("模型目录批次获取期间身份或有效来源已变化，本次结果已丢弃")
            identities[key] = end[1]
        elif current._native_scope is None and current.stamp != baseline.stamp:
            raise ValueError("模型目录批次获取期间有效来源或能力已变化，本次结果已丢弃")
        acquired.append(current)
    # 只有尚未交付、每次 before→after 连续且稳定来源仍等于基底的本轮结果可
    # 归一到最终共享提示。使用独立副本重新投影，不修改此前发布的目录/草稿；
    # 查询间外部刷新及最后查询之后的变化都无法通过这个精确 identity 守卫。
    sealed = []
    for target, baseline, current in zip(scopes, before, acquired):
        snapshot = current
        if current._native_query is not None:
            expected = (baseline._native_scope[0], identities[current._native_cache])
            snapshot = replace(current, _native_scope=expected)
        checked = _discover(host, project=target, _snapshot=snapshot, native_context=native_context)
        if current._native_query is not None:
            if checked._native_scope != expected or checked._status != current._status:
                raise ValueError("模型目录批次发布前身份或有效来源已变化，本次结果已丢弃")
        elif checked.stamp != current.stamp:
            raise ValueError("模型目录批次发布前有效来源或能力已变化，本次结果已丢弃")
        sealed.append(checked)
    if project is None and _active_projects(state, host, native_context=native_context) != (registry, targets):
        raise ValueError("登记项目或活跃范围在目录获取期间变化，请重新进入编辑")
    return PreferenceCatalogs(sealed[0], {str(target): value for target, value in zip(targets, sealed[1:])},
                              (str(state), str(project) if project else None, host), registry)


@runtime_store.read_operation
def check_catalogs(state: Path, project: Path | None, host: str,
                   catalog: Catalog | PreferenceCatalogs, *, native_context=None) -> bool:
    """只读失效检查，不启动 native；False 要求用户重新进入编辑/刷新后重选。"""
    try:
        state = state_files.state_root(state)
        project = state_files.project_path(project) if project is not None else None
        bundle = catalog if isinstance(catalog, PreferenceCatalogs) else PreferenceCatalogs(catalog, {})
        if bundle._scope is not None and bundle._scope != (str(state), str(project) if project else None, host):
            return False
        snapshots = [(project, bundle.catalog)]
        if project is None:
            registry, active = _active_projects(state, host, native_context=native_context)
            if bundle._registry is not None and bundle._registry != registry:
                return False
            if {str(target) for target in active} != set(bundle.project_catalogs):
                return False
            snapshots.extend((target, bundle.project_catalogs[str(target)]) for target in active)
        for target, previous in snapshots:
            if not isinstance(previous, Catalog) or previous.host != host or previous._status != "ready":
                return False
            # 无 stamp 的目录只允许现有测试/显式静态调用合同；生产 discover 总
            # 带摘要。带摘要时重读本地文件与身份，_snapshot 保证不会启动进程。
            if previous.stamp:
                current = _discover(host, project=target, _snapshot=previous, native_context=native_context)
                if current._status != "ready" or current.stamp != previous.stamp:
                    return False
        return True
    except (OSError, ValueError, TypeError, KeyError):
        return False


@dataclass(frozen=True)
class _Observation:
    project: Path
    config: Node
    machine: Node
    journal: Node
    observed: tuple
    directories: tuple
    ownership_sources: runtime_service.OwnershipSources


def _project_observation(project, sources) -> _Observation:
    """只投影既有调用字段；完整inventory唯一归项目ownership职责维护。"""
    config = dict(sources.observed)[CONFIG]
    return _Observation(project, config, sources.machine, sources.journal,
                        sources.observed, sources.directories, sources)


def _snapshot_observation(state: Path, project: Path) -> _Observation:
    """只读取得完整事实；真正封口后的recheck另沿Plan固定inventory比较。"""
    project = state_files.project_path(project)
    return _project_observation(project, runtime_service.capture_ownership_sources(state, project))


@runtime_store.read_operation
def _observe(state: Path, project: Path) -> tuple[_Observation, dict | None]:
    project = state_files.project_path(project)
    machine, record = runtime_service.read_binding_record(state, project)
    sources = runtime_service.capture_ownership_sources(state, project)
    if sources.machine != machine:
        raise ValueError("项目归属记录在观察前变化")
    with Tree(project) as tree:
        if record:
            conflicts, _ = runtime_service._ownership(tree, record, state, repair=False)
            if conflicts:
                raise ValueError("项目已归属资源含手改、手删或替换冲突")
        # journal-only历史也属于本次完整inventory。复用原历史producer/校验，
        # 稳定missing仍允许；存在但已编辑的历史不能由完整来源快照追认。
        if runtime_service._history_writes(tree, json.loads(sources.retained_json)):
            raise ValueError("项目保留历史含未知编辑")
    runtime_service.recheck_ownership_sources(state, project, sources)
    return _project_observation(project, sources), record


@runtime_store.read_operation
def _check_observation(state: Path, before: _Observation) -> None:
    current, _ = _observe(state, before.project)
    if current != before:
        raise ValueError("项目配置、原生受管状态或目录在预览后变化：" + str(before.project))


@dataclass(frozen=True)
class _Target:
    observation: _Observation
    changes: tuple[service.Change, ...]
    catalog: Catalog | None
    metadata_only: bool = False


class _UnavailableRoles(ValueError):
    """仅携带已校验角色标识的资格失败，可安全投影为具体预览冲突。"""


def _prepare_target(state, observation, record, host, effective, catalog, defaults, *,
                    project_scope, reset, native_context) -> _Target:
    """按真实角色资格形成一个项目的固定变更，不负责发布或汇总展示。

    项目显式请求是整批编辑，不能像全局默认传播一样丢掉不可用角色；恢复
    平台则只清理历史来源，允许角色已离开画像且不依赖模型目录。角色资格
    始终复用 service.roles 的绑定、归属与画像检查，稀疏角色不以文件判定。
    """
    project = observation.project
    active = bool(record and record["enabled"] and host in record["hosts"])
    changes = ()
    if active and effective:
        installed = set(service.roles(project, host, state=state, native_context=native_context))
        unavailable = set(effective) - installed
        if project_scope and not reset and unavailable:
            raise _UnavailableRoles("角色不在当前启用宿主的已验证画像中：" + "、".join(sorted(unavailable)))
        # 全局保存仅更新已经可用的跟随角色，绝不因为设置默认而安装新角色。
        # reset 的不可用角色仅进入 metadata_roles，不能生成其原生文件。
        editable = effective if project_scope and reset else {
            role: fields for role, fields in effective.items() if role in installed}
        if editable:
            if catalog is None:
                if not reset:
                    raise ValueError("缺少该项目真实来源的模型目录快照，请刷新")
                if set(editable) & installed:
                    catalog = _discover(host, project=project, native_context=native_context)
            changes = tuple(service.prepare(project, host, editable, catalog, state=state,
                                             global_preferences=defaults, persist=project_scope,
                                             native_context=native_context,
                                             metadata_roles=tuple(sorted(set(editable) - installed))))
    elif project_scope and effective:
        if not reset:
            raise _UnavailableRoles("项目该宿主尚未启用，不能保存原生角色偏好")
        # 停用项目没有可物化目标；只从原配置删除本次请求字段，其他宿主和
        # 未编辑字段由统一的 _edit 保留，不借平台恢复执行项目启用。
        edited = _edit(_config(observation.config), host, effective)
        updated = role_models.update(observation.config.payload.decode(), edited).encode()
        if updated != observation.config.payload:
            changes = (service.Change(CONFIG, observation.config.payload, updated, observation.config.mode),)
    return _Target(observation, changes, catalog, not active)


@dataclass(frozen=True)
class ModelPreferencePlan:
    state: Path
    project: Path | None
    host: str
    global_before: Node
    global_after: bytes
    registry_before: Node | None
    catalog: Catalog | PreferenceCatalogs | None
    targets: tuple[_Target, ...]
    summary_json: bytes
    native_context: object = None
    global_native: object = None

    @property
    def summary(self) -> dict:
        # 调用方获得独立 JSON 投影，修改弹层字典不会修改已授权计划。
        return json.loads(self.summary_json)

    @property
    def changed_paths(self) -> list[str]:
        """只读 CLI 投影，顺序与现有按目标展开一致，不泄漏事务内部目标结构。"""
        return [row.relative for target in self.targets for row in target.changes]


def _edit(choices: dict, host: str, edits: dict) -> dict:
    updated = json.loads(json.dumps(choices))
    if not isinstance(edits, dict) or set(edits) - role_models.ROLES:
        raise ValueError("角色编辑包含未知角色")
    for role, fields in edits.items():
        if not isinstance(fields, dict) or not fields or set(fields) - set(role_preferences.FIELDS):
            raise ValueError("每个角色必须指定本次实际编辑的 model / effort 字段")
        selected = dict(updated.get(host, {}).get(role, {}))
        for name, value in fields.items():
            if value is None:
                selected.pop(name, None)
            else:
                selected[name] = value
        selected = role_models.explicit(host, selected)
        if selected:
            updated.setdefault(host, {})[role] = selected
        else:
            updated.get(host, {}).pop(role, None)
        if not updated.get(host):
            updated.pop(host, None)
    return updated


@runtime_store.read_operation
def preview(state, project, host, choices, catalog, expected=None, *, native_context=None, _reset=False) -> ModelPreferencePlan:
    """只读构建全部目标；普通保存不发现新目录，不创建锁、备份或配置文件。"""
    state = state_files.state_root(state)
    project = state_files.project_path(project) if project is not None else None
    if host not in role_models.HOSTS:
        raise ValueError("未知平台")
    global_node, defaults = role_preferences.snapshot(state)
    config = _config(_read(project, CONFIG)) if project is not None else {}
    edited = _edit(config if project is not None else defaults, host, choices)
    if expected is not None:
        if not isinstance(expected, dict) or any(role not in expected or expected[role] != view(state, project, host, role) for role in choices):
            raise ValueError("角色偏好来源或配置在编辑后变化，请重新选择或丢弃草稿")
    bundle = catalog if isinstance(catalog, PreferenceCatalogs) else PreferenceCatalogs(catalog, {})
    summary = {"scope": "project" if project is not None else "global", "platform": host,
               "project": str(project) if project is not None else None, "changes": [],
               "affected_projects": [], "conflicts": [], "can_apply": True, "notes": [], "values": {}}
    if native_context is None and native_agents.has_records(state) and choices:
        raise ValueError("已有全局原生归属的偏好写入必须提供 NativeContext")
    if catalog is not None and not check_catalogs(state, project, host, catalog, native_context=native_context):
        summary["conflicts"].append({"path": "model-catalog", "reason": "模型来源失效、读取失败或影响项目快照不完整；请进入编辑或刷新重新获取"})
    for role, fields in choices.items():
        before_scope = (config if project is not None else defaults).get(host, {}).get(role, {})
        after_scope = edited.get(host, {}).get(role, {})
        for name in fields:
            if (name in before_scope, before_scope.get(name)) != (name in after_scope, after_scope.get(name)):
                summary["changes"].append({"role": role, "field": name, "before": before_scope.get(name),
                                           "after": after_scope.get(name), "operation": "reset" if name not in after_scope else "set"})
        values, _ = role_preferences.resolve(edited if project is None else defaults, edited if project is not None else {}, host, role)
        # 当前范围本身也需合法目录证据；绝不从其他项目的自定义提供方菜单补值。
        if catalog is not None:
            service.validate_selection(host, values, bundle.catalog)
        summary["values"][role] = values
    registry, projects = _registered(state) if project is None else (None, (project,))
    targets = []
    for target in projects:
        try:
            observation, record = _observe(state, target)
            target_choices = _config(observation.config)
            effective = {}
            following = []
            for role, fields in choices.items():
                if project is not None:
                    effective[role] = fields
                    following.extend({"role": role, "field": name} for name in fields)
                else:
                    override = target_choices.get(host, {}).get(role, {})
                    changed_fields = [row["field"] for row in summary["changes"] if row["role"] == role and row["field"] not in override]
                    if changed_fields:
                        effective[role] = role_preferences.resolve(edited, target_choices, host, role)[0]
                        following.extend({"role": role, "field": name} for name in changed_fields)
            active = bool(record and record["enabled"] and host in record["hosts"])
            selected = bundle.catalog if project is not None else bundle.project_catalogs.get(str(target))
            planned = _prepare_target(state, observation, record, host, effective, selected,
                                      edited if project is None else defaults, project_scope=project is not None,
                                      reset=_reset, native_context=native_context)
            if following:
                summary["affected_projects"].append({"project": str(target), "enabled": bool(record and record["enabled"]),
                                                      "host_active": active, "fields": following,
                                                      "changed_paths": [row.relative for row in planned.changes],
                                                      "materialization": "update" if planned.changes else "on_enable" if not active else "unchanged"})
            targets.append(planned)
        except _UnavailableRoles as exc:
            summary["conflicts"].append({"path": str(target), "reason": str(exc)})
        except (OSError, ValueError, TypeError) as exc:
            summary["conflicts"].append({"path": str(target), "reason": "项目状态、受管资源或模型能力冲突，请检查项目后重试"})
    global_native = None
    if project is None and native_context is not None and summary["changes"]:
        projection = native_agents.status_global(state, context=native_context)["hosts"][host]
        if projection["conflicts"]:
            summary["conflicts"].extend(projection["conflicts"])
        elif projection["managed"]:
            current = native_agents.current_binding(state)
            global_native = native_agents.preview_global(state, current, context=native_context, hosts=(host,), preferences=edited)
            summary["conflicts"].extend(global_native.conflicts)
    summary["can_apply"] = not summary["conflicts"]
    if project is None:
        summary["notes"].append("停用或未管理项目只在后续启用时采用默认值；明确项目覆盖和已有任务 pin 保留。")
    return ModelPreferencePlan(state, project, host, global_node,
                               role_preferences.payload(edited if project is None else defaults), registry,
                               catalog, tuple(targets), json_bytes(summary), native_context, global_native)


@runtime_store.read_operation
def _guard(plan: ModelPreferencePlan) -> None:
    if role_preferences.snapshot(plan.state)[0] != plan.global_before:
        raise ValueError("全局角色偏好在预览后变化，请重新预览")
    if plan.registry_before is not None and _registered(plan.state)[0] != plan.registry_before:
        raise ValueError("登记项目列表在预览后变化，请重新预览")
    if plan.catalog is not None and not check_catalogs(plan.state, plan.project, plan.host, plan.catalog, native_context=plan.native_context):
        raise ValueError("模型目录来源在预览后变化，请重新编辑")
    for target in plan.targets:
        _check_observation(plan.state, target.observation)
        if plan.catalog is None and target.catalog is not None:
            # 平台恢复可能在准备目标时惰性取得目录；它仍属于同一显式宿主
            # 上下文，不能回退到进程HOME/CODEX_HOME重读。复用普通目录守卫，
            # 同时保留ready/host/stamp检查和只读_snapshot，绝不隐式刷新授权。
            if not check_catalogs(plan.state, target.observation.project, plan.host, target.catalog,
                                  native_context=plan.native_context):
                raise ValueError("模型来源或能力已变化；草稿已保留，请刷新并重新选择后再应用")


@dataclass(frozen=True)
class _PreferenceGuardSnapshot:
    """只保存本轮额外mutable原生来源，既有Plan仍是其他来源的唯一expected。"""

    native_sources: tuple


def _native_guard_sources(plan):
    if plan.native_context is None:
        return ()
    return tuple(native_agents.observe_sources(plan.state, plan.native_context.host_paths, host)
                 for host in role_models.HOSTS)


def _capture_commit_guard(plan: ModelPreferencePlan) -> _PreferenceGuardSnapshot:
    """在显式纯准备phase内执行真实guard，前后绑定原生稀疏资格来源。"""
    sources = _native_guard_sources(plan)
    _guard(plan)
    if _native_guard_sources(plan) != sources:
        raise ValueError("模型准备期间原生角色来源已变化")
    return _PreferenceGuardSnapshot(sources)


def _check_catalog_sources(state, project, host, catalog, native_context):
    """只重读已固定目录来源，不再推导项目/core资格，不查询或续期目录。

    完整check_catalogs已经在同一纯准备phase内验证active集合；随后registry、
    全部项目binding/config/managed节点和原生完整来源都必须仍等于同一前像。
    因此这里只沿已固定各scope重查ready、来源stamp及缓存身份，不重新基准。
    """
    bundle = catalog if isinstance(catalog, PreferenceCatalogs) else PreferenceCatalogs(catalog, {})
    if bundle._scope is not None and bundle._scope != (str(state), str(project) if project else None, host):
        raise ValueError("模型目录范围在准备后变化")
    snapshots = [(project, bundle.catalog)]
    if project is None:
        snapshots.extend((Path(path), item) for path, item in bundle.project_catalogs.items())
    for target, previous in snapshots:
        if not isinstance(previous, Catalog) or previous.host != host or previous._status != "ready":
            raise ValueError("模型目录在准备后不可应用")
        if previous.stamp:
            current = _discover(host, project=target, _snapshot=previous, native_context=native_context)
            if current._status != "ready" or current.stamp != previous.stamp:
                raise ValueError("模型目录来源在准备后变化，请重新编辑")


def _recheck_commit_guard(plan: ModelPreferencePlan, snapshot: _PreferenceGuardSnapshot) -> None:
    """整树尾验结束后fresh比较原前像；此函数没有core读取或隐式宿主查询。"""
    if not isinstance(snapshot, _PreferenceGuardSnapshot):
        raise TypeError("模型准备来源快照无效")
    if role_preferences.snapshot(plan.state)[0] != plan.global_before:
        raise ValueError("全局角色偏好在准备后变化")
    if plan.registry_before is not None and _registered(plan.state)[0] != plan.registry_before:
        raise ValueError("登记项目列表在准备后变化")
    for target in plan.targets:
        runtime_service.recheck_ownership_sources(plan.state, target.observation.project,
                                                  target.observation.ownership_sources)
        if plan.catalog is None and target.catalog is not None:
            _check_catalog_sources(plan.state, target.observation.project, plan.host, target.catalog, plan.native_context)
    if plan.catalog is not None:
        _check_catalog_sources(plan.state, plan.project, plan.host, plan.catalog, plan.native_context)
    if _native_guard_sources(plan) != snapshot.native_sources:
        raise ValueError("原生角色来源在准备封口后变化")


def _restore_global(state: Path, before: Node, published: Node) -> None:
    """只撤回仍等于本轮产物的私有配置；后续编辑与换目录必须保留为冲突。"""
    if _read(state, role_preferences.RELATIVE) != published:
        raise ValueError("全局偏好已有后续修改，保留现状")
    with state_files.AnchoredFile(state, role_preferences.RELATIVE) as target:
        if before.kind == "file":
            target.write(before.payload, before.mode, (published.payload, published.mode))
        else:
            held = ".role-preferences-rollback-" + uuid.uuid4().hex
            move_at(target.name, held, src_dir_fd=target.directory, dst_dir_fd=target.directory, expected=published)
            if target.read(held) != (published.payload, published.mode):
                raise state_files.PreservedEdit(target.path.parent / held)
            # 排他隔离后仅删除本轮精确产物；目标被第三方重建时保持新文件。
            held_node = read_at(target.directory, held)
            if (held_node.identity[:2] != published.identity[:2] or held_node.security != published.security
                    or (held_node.payload, held_node.mode) != (published.payload, published.mode)):
                raise state_files.PreservedEdit(target.path.parent / held)
            delete_at(target.directory, held, expected=held_node)


def apply(plan) -> dict:
    """应用同一进程内计划；多项目补偿复用模型备份及原生收据，不盲目恢复。"""
    if not isinstance(plan, ModelPreferencePlan) or not plan.summary["can_apply"]:
        raise ValueError("偏好预览存在冲突，不能应用")
    # project及不经过commit的global尾phase都必须拥有自己的封口。入口先拒绝
    # 外层租约，不能在native已发布/创建journal后才发现借来的phase尚未结束。
    runtime_store.require_no_read_operation()
    summary = plan.summary
    result = {"applied": False, "scope": summary["scope"], "backup_id": None, "backups": [],
              "affected_projects": summary["affected_projects"], "diagnostic": "无偏好变更。"}
    if not summary["changes"]:
        _guard(plan)
        return result
    with role_preferences.coordination(plan.state):
        from . import runtime_policy
        runtime_policy.ensure_management_settled(plan.state)
        _guard(plan)
        if plan.project is not None:
            target = plan.targets[0]
            if not target.changes:
                # 展示出的请求差异不等于落盘结果。空计划不能创建备份，也不能
                # 把 commit 的 no-op 包装成保存成功；资格冲突已在 preview 拒绝。
                return result
            def verify_project():
                if target.metadata_only:
                    # 停用/尚未管理项目仅恢复持久来源；没有可启动的native目标，
                    # 因而不能通过service.check迫使一次metadata恢复变成启用动作。
                    with Tree(plan.project) as tree:
                        current = tree.read(CONFIG)
                    config_change = next((row for row in target.changes if row.relative == CONFIG), None)
                    if config_change is not None and current.payload != config_change.after:
                        raise ValueError("平台恢复后的项目配置与固定计划不一致")
                    _config(current)
                else:
                    service.check(plan.project, plan.host, state=plan.state)
            identifier = service.commit(plan.state, plan.project, target.changes,
                                        verify_project,
                                        read_preparation=service.CommitReadPreparation(
                                            lambda: _capture_commit_guard(plan),
                                            lambda captured: _recheck_commit_guard(plan, captured)),
                                        native_context=plan.native_context)
            result.update(applied=identifier is not None, backup_id=identifier,
                          backups=[{"project": str(plan.project), "backup_id": identifier}] if identifier else [],
                          diagnostic="项目角色偏好已保存。" if identifier else result["diagnostic"])
            return result
        identifier = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:8]
        relative = "preferences/transactions/" + identifier + ".json"
        previous_global = ([{"path": "preferences/transactions/" + identifier + "-previous-" + uuid.uuid4().hex + ".json",
                             "expected_sha": hashlib.sha256(plan.global_before.payload).hexdigest(),
                             "mode": plan.global_before.mode}] if plan.global_before.kind == "file" else [])
        if state_files.os.name == "nt" and previous_global:
            previous_global[0].update(identity=list(plan.global_before.identity), security=plan.global_before.security)
        record = {"schema_version": 1, "id": identifier, "status": "prepared",
                  "global_before": plan.global_before.value(),
                  "global_after": base64.b64encode(plan.global_after).decode(), "global_previous": previous_global,
                  "global_native_ref": plan.global_native.recovery_ref if plan.global_native is not None else None,
                  "projects": [{"project": str(target.observation.project), "backup_id": None,
                                "files": [{"path": row.relative, "before_sha": service._fingerprint(row.before),
                                           "after_sha": service._fingerprint(row.after), "mode": row.mode}
                                          for row in target.changes]}
                               for target in plan.targets if target.changes], "conflicts": []}
        if state_files.os.name == "nt":
            # 关闭后实际 metadata 的位宽使用固定上界证明；只增字段预算，不抬4MiB。
            capacity = {**record, "global_previous": [{**row, "identity": list(CAPACITY_IDENTITY),
                         "security": "f" * 64, "mode": 0o7777} for row in previous_global]}
            service.record_payload(capacity)
        with absolute_directory(plan.state / "preferences" / "transactions", create=True):
            pass
        def save():
            state_files.write_state(plan.state, relative, service.record_payload(record))
        save()
        completed, observations = [], []
        published = None
        native_receipt = None
        projection = (native_agents.preference_projection(plan.state, identifier, plan.global_after)
                      if plan.global_native is not None else None)
        if projection is not None:
            projection.__enter__()
        try:
            if plan.global_native is not None:
                native_receipt = native_agents.apply_global(plan.global_native)
            no_project_changes = all(not target.changes for target in plan.targets)
            for target in plan.targets:
                if no_project_changes:
                    # 没有项目发布时，末次guard继续比较预览原前像。不能在native
                    # 自有写之后重读_observe并把窗口中的第三方编辑追认为新基准。
                    observations.append(target.observation)
                    continue
                _check_observation(plan.state, target.observation)
                if target.changes:
                    project = target.observation.project
                    backup = service.commit(plan.state, project, target.changes,
                                            lambda project=project: service.check(project, plan.host, state=plan.state),
                                            before_write=lambda target=target: _check_observation(plan.state, target.observation),
                                            native_context=plan.native_context,
                                            global_preferences=role_preferences.validate(json.loads(plan.global_after)))
                    completed.append(target)
                    next(row for row in record["projects"] if row["project"] == str(project))["backup_id"] = backup
                    result["backups"].append({"project": str(project), "backup_id": backup})
                    save()
                observations.append(_observe(plan.state, target.observation.project)[0])
            # 所有项目先准备并成功后再发布全局权威。最后重查目录及目标，失败
            # 则按精确前后像补偿，不能把部分更新报告为全局成功。
            if no_project_changes:
                with runtime_store.core_read_operation():
                    publication_sources = _capture_commit_guard(plan)
                # scope尾验仍位于本父补偿try内；fresh来源检查紧邻下面的权威
                # 发布，不把昂贵核心尾检放在最终CAS之后，也不复用关闭reader。
                _recheck_commit_guard(plan, publication_sources)
            else:
                if role_preferences.snapshot(plan.state)[0] != plan.global_before or _registered(plan.state)[0] != plan.registry_before:
                    raise ValueError("全局偏好或登记项目列表在应用期间变化")
                if plan.catalog is not None and not check_catalogs(plan.state, None, plan.host, plan.catalog, native_context=plan.native_context):
                    raise ValueError("模型目录来源在应用期间变化")
                for observation in observations:
                    _check_observation(plan.state, observation)
            with state_files.AnchoredFile(plan.state, role_preferences.RELATIVE) as target:
                def retain_global(original, previous, expected):
                    # 私有全局文件也保留旧 inode。仅保存正文副本会遗漏仍持有旧
                    # fd 的编辑器随后写入；永久路径和摘要写入同一恢复明细。
                    archive_relative = record["global_previous"][0]["path"]
                    with state_files.AnchoredFile(plan.state, archive_relative) as archive:
                        frozen = getattr(original, "retained_snapshot", None) or read_at(original.directory, previous)
                        move_at(previous, archive.name, src_dir_fd=original.directory, dst_dir_fd=archive.directory, expected=frozen)
                        if state_files.os.name == "nt":
                            archived = read_at(archive.directory, archive.name)
                            if (archived.identity[:2] != frozen.identity[:2] or archived.security != frozen.security
                                    or archived.identity[4:6] != frozen.identity[4:6] or archived.payload != frozen.payload):
                                raise state_files.PreservedEdit(archive.path)
                            record["global_previous"][0].update(identity=list(archived.identity), security=archived.security, mode=archived.mode)
                        if not state_files.same_file_state(archive.read(), expected):
                            raise state_files.PreservedEdit(archive.path)
                target.retainer = retain_global
                expected = ((plan.global_before.payload, plan.global_before.mode)
                            if plan.global_before.kind == "file" else (None, None))
                target.write(plan.global_after, 0o600, expected)
            published = _read(plan.state, role_preferences.RELATIVE)
            service.check_versions(plan.state, record["global_previous"])
            record["status"] = "applied"
            save()
        except BaseException as failure:
            if isinstance(failure, state_files.PreservedEdit):
                record["conflicts"].append({"path": role_preferences.RELATIVE, "reason": "旧全局文件已有后续保存",
                                            "retained_path": failure.retained_path})
            # 发布函数可能完成文件发布后才失败，按实际可见字节判断是否需要撤回；
            # 不能假设抛异常就等于没有副作用，也不能覆盖第三方的新配置。
            try:
                current = _read(plan.state, role_preferences.RELATIVE)
                if published is not None or (current.payload == plan.global_after and current.mode == 0o600):
                    _restore_global(plan.state, plan.global_before, published or current)
                elif not current.same_content(plan.global_before):
                    record["conflicts"].append({"path": role_preferences.RELATIVE, "reason": "全局配置已有后续修改"})
            except (OSError, ValueError) as restoration_failure:
                detail = {"path": role_preferences.RELATIVE, "reason": "全局配置不能安全撤回，保留现状"}
                if isinstance(restoration_failure, state_files.PreservedEdit):
                    detail["retained_path"] = restoration_failure.retained_path
                record["conflicts"].append(detail)
            for target in reversed(completed):
                project = target.observation.project
                try:
                    reverse = [service.Change(row.relative, row.after, row.before, row.mode) for row in target.changes]
                    backup = service.commit(plan.state, project, reverse,
                                            lambda project=project: service.check(project, plan.host, state=plan.state),
                                            native_context=plan.native_context)
                    record["projects"].append({"project": str(project), "rollback_backup_id": backup})
                except (OSError, ValueError):
                    record["conflicts"].append({"path": str(project), "reason": "项目不能安全撤回，保留现状及原备份"})
            if plan.global_native is not None:
                recovery = native_agents.compensate_global(plan.global_native.recovery_ref, context=plan.native_context)
                record["conflicts"].extend(recovery.get("conflicts", []))
            record["status"] = "conflict" if record["conflicts"] else "rolled_back"
            try:
                save()
            except BaseException as logging_failure:
                raise ValueError("全局偏好未完成；恢复日志保存失败，请核对事务 " + identifier + " 及项目模型备份") from logging_failure
            raise ValueError("全局偏好未完成；" + ("存在恢复冲突，已保留现状" if record["conflicts"] else "已条件撤回本轮变更") +
                             "；可恢复事务：" + identifier) from failure
        finally:
            # scope只服务本次已prepared事务的自身健康校验；任何成功、补偿或
            # 异常退出都撤销future投影，不能泄漏到后续调用或让其他任务借用。
            if projection is not None:
                projection.__exit__(None, None, None)
        result.update(applied=True, backup_id=identifier, diagnostic="全局角色偏好及实际跟随项目已保存。")
        return result


def reset_platform(state, project, host, *, native_context=None, catalog=None) -> ModelPreferencePlan:
    """固定整个平台恢复计划；清理所有已知持久覆盖，包括停用宿主和未安装角色。

    不从当前菜单/已安装角色集合推导清理范围，避免合法但暂未启用的配置被漏掉。
    未知 schema 由既有来源解析拒绝；no-op 走同一纯读计划且不备份、不写入。
    """
    state = state_files.state_root(state)
    project = state_files.project_path(project) if project is not None else None
    if host not in role_models.HOSTS:
        raise ValueError("未知平台")
    source = _config(_read(project, CONFIG)) if project is not None else role_preferences.snapshot(state)[1]
    edits = {role: {field: None for field in fields} for role, fields in source.get(host, {}).items() if fields}
    return preview(state, project, host, edits, catalog, native_context=native_context, _reset=True)
