"""CLI 与 TUI 共用的按字段偏好计划、目录快照及条件应用服务。"""

from __future__ import annotations

import base64
from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import uuid

from lib import role_models, role_preferences
from lib.runtime_project import CONFIG, Node, Tree, absolute_directory, json_bytes, skill_parts
from . import service, runtime_service
from .catalog import Catalog, discover


@dataclass(frozen=True)
class PreferenceCatalogs:
    """一次显式编辑/刷新获取的目录；私有来源范围防止串用另一个项目菜单。"""

    catalog: Catalog
    project_catalogs: dict[str, Catalog]
    _scope: tuple | None = field(default=None, repr=False)
    _registry: Node | None = field(default=None, repr=False)


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
        data = service._registry_data(node.payload if node.kind == "file" else None)
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


def roles(state: Path, project: Path | None, host: str) -> list[str]:
    if host not in role_models.HOSTS:
        raise ValueError("未知平台")
    return sorted(role_models.ROLES) if project is None else service.roles(service.project_path(project), host)


def view(state, project, host, role) -> dict:
    """纯读取有效值和字段来源；明确 inherit 的来源为 host，覆盖仍保留在 overrides。"""
    state = service.state_root(state)
    global_node, defaults = role_preferences.snapshot(state)
    config, native, machine = Node(), Node(), Node()
    choices = {}
    if project is not None:
        project = service.project_path(project)
        config = _read(project, CONFIG)
        choices = _config(config)
        native = _read(project, service.role_path(project, host, role).relative_to(project).as_posix())
        machine, _ = runtime_service.read_binding_record(state, project)
    values, sources = role_preferences.resolve(defaults, choices, host, role)
    explicit = (defaults if project is None else choices).get(host, {}).get(role, {})
    return {**values, "sources": sources, "overrides": dict(explicit),
            "revision": {"global": role_preferences.revision(global_node),
                         "project": role_preferences.revision(config),
                         "native": role_preferences.revision(native),
                         "binding": role_preferences.revision(machine)}}


def _active_projects(state: Path, host: str) -> tuple[Node, tuple[Path, ...]]:
    registry, projects = _registered(state)
    active = []
    for project in projects:
        # 这里只读取本机登记和宿主归属，不把停用/未管理项目装成活跃目标。损坏
        # 目标由 preview 投影为冲突；加载菜单也不能擅自跳过一个应更新的项目。
        service.project_path(project)
        _, record = runtime_service.read_binding_record(state, project)
        if record and record["enabled"] and host in record["hosts"] and service.roles(project, host):
            active.append(project)
    return registry, tuple(active)


def load_catalogs(state: Path, project: Path | None, host: str) -> PreferenceCatalogs:
    """仅显式编辑/刷新调用：每个真实来源单独读取，原生查询沿现有有界实现。"""
    state = service.state_root(state)
    project = service.project_path(project) if project is not None else None
    if host not in role_models.HOSTS:
        raise ValueError("未知平台")
    catalog = discover(host, project=project)
    registry, targets = _active_projects(state, host) if project is None else (None, ())
    snapshots = {str(target): discover(host, project=target) for target in targets}
    return PreferenceCatalogs(catalog, snapshots, (str(state), str(project) if project else None, host), registry)


def check_catalogs(state: Path, project: Path | None, host: str,
                   catalog: Catalog | PreferenceCatalogs) -> bool:
    """只读失效检查，不启动 native；False 要求用户重新进入编辑/刷新后重选。"""
    try:
        state = service.state_root(state)
        project = service.project_path(project) if project is not None else None
        bundle = catalog if isinstance(catalog, PreferenceCatalogs) else PreferenceCatalogs(catalog, {})
        if bundle._scope is not None and bundle._scope != (str(state), str(project) if project else None, host):
            return False
        snapshots = [(project, bundle.catalog)]
        if project is None:
            registry, active = _active_projects(state, host)
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
                current = discover(host, project=target, _snapshot=previous)
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


def _observe(state: Path, project: Path) -> tuple[_Observation, dict | None]:
    project = service.project_path(project)
    machine, record = runtime_service.read_binding_record(state, project)
    journal = runtime_service._read_state(state, runtime_service._state_relative(project, "transactions"))
    with Tree(project) as tree:
        config = tree.read(CONFIG)
        paths = {CONFIG}
        if record:
            paths.update(record["managed"])
        observed = tuple((path, tree.read(path, skill_link=bool(skill_parts(path)))) for path in sorted(paths))
        directories = tree.directory_facts(list(paths))
    return _Observation(project, config, machine, journal, observed, directories), record


def _check_observation(state: Path, before: _Observation) -> None:
    current, _ = _observe(state, before.project)
    if current != before:
        raise ValueError("项目配置、原生受管状态或目录在预览后变化：" + str(before.project))


@dataclass(frozen=True)
class _Target:
    observation: _Observation
    changes: tuple[service.Change, ...]
    catalog: Catalog | None


@dataclass(frozen=True)
class ModelPreferencePlan:
    state: Path
    project: Path | None
    host: str
    global_before: Node
    global_after: bytes
    registry_before: Node | None
    catalog: Catalog | PreferenceCatalogs
    targets: tuple[_Target, ...]
    summary_json: bytes

    @property
    def summary(self) -> dict:
        # 调用方获得独立 JSON 投影，修改弹层字典不会修改已授权计划。
        return json.loads(self.summary_json)


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


def preview(state, project, host, choices, catalog, expected=None) -> ModelPreferencePlan:
    """只读构建全部目标；普通保存不发现新目录，不创建锁、备份或配置文件。"""
    state = service.state_root(state)
    project = service.project_path(project) if project is not None else None
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
    if not check_catalogs(state, project, host, catalog):
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
            changes = ()
            active = bool(record and record["enabled"] and host in record["hosts"])
            selected = bundle.catalog if project is not None else bundle.project_catalogs.get(str(target))
            if active and effective:
                # 已启用但未安装该角色不应借全局默认补装。其余角色仍保持明确覆
                # 盖；只对当前已有宿主资源的跟随字段形成模型补丁。
                installed = service.roles(target, host)
                editable = {role: value for role, value in effective.items() if role in installed}
                if editable:
                    if selected is None:
                        raise ValueError("缺少该项目真实来源的模型目录快照，请刷新")
                    changes = tuple(service.prepare(target, host, editable, selected, state=state,
                                                     global_preferences=edited if project is None else defaults,
                                                     persist=project is not None))
            elif project is not None and effective:
                raise ValueError("项目该宿主尚未启用，不能保存原生角色偏好")
            if following:
                summary["affected_projects"].append({"project": str(target), "enabled": bool(record and record["enabled"]),
                                                      "host_active": active, "fields": following,
                                                      "changed_paths": [row.relative for row in changes],
                                                      "materialization": "update" if changes else "on_enable" if not active else "unchanged"})
            targets.append(_Target(observation, changes, selected))
        except (OSError, ValueError, TypeError) as exc:
            summary["conflicts"].append({"path": str(target), "reason": "项目状态、受管资源或模型能力冲突，请检查项目后重试"})
    summary["can_apply"] = not summary["conflicts"]
    if project is None:
        summary["notes"].append("停用或未管理项目只在后续启用时采用默认值；明确项目覆盖和已有任务 pin 保留。")
    return ModelPreferencePlan(state, project, host, global_node,
                               role_preferences.payload(edited if project is None else defaults), registry,
                               catalog, tuple(targets), json_bytes(summary))


def _guard(plan: ModelPreferencePlan) -> None:
    if role_preferences.snapshot(plan.state)[0] != plan.global_before:
        raise ValueError("全局角色偏好在预览后变化，请重新预览")
    if plan.registry_before is not None and _registered(plan.state)[0] != plan.registry_before:
        raise ValueError("登记项目列表在预览后变化，请重新预览")
    if not check_catalogs(plan.state, plan.project, plan.host, plan.catalog):
        raise ValueError("模型目录来源在预览后变化，请重新编辑")
    for target in plan.targets:
        _check_observation(plan.state, target.observation)


def _restore_global(state: Path, before: Node, published: Node) -> None:
    """只撤回仍等于本轮产物的私有配置；后续编辑与换目录必须保留为冲突。"""
    if _read(state, role_preferences.RELATIVE) != published:
        raise ValueError("全局偏好已有后续修改，保留现状")
    with service.AnchoredFile(state, role_preferences.RELATIVE) as target:
        if before.kind == "file":
            target.write(before.payload, before.mode, (published.payload, published.mode))
        else:
            held = ".role-preferences-rollback-" + uuid.uuid4().hex
            service.os.rename(target.name, held, src_dir_fd=target.directory, dst_dir_fd=target.directory)
            if target.read(held) != (published.payload, published.mode):
                raise service.PreservedEdit(target.path.parent / held)
            # 排他隔离后仅删除本轮精确产物；目标被第三方重建时保持新文件。
            service.os.unlink(held, dir_fd=target.directory)


def apply(plan) -> dict:
    """应用同一进程内计划；多项目补偿复用模型备份及原生收据，不盲目恢复。"""
    if not isinstance(plan, ModelPreferencePlan) or not plan.summary["can_apply"]:
        raise ValueError("偏好预览存在冲突，不能应用")
    summary = plan.summary
    result = {"applied": False, "scope": summary["scope"], "backup_id": None, "backups": [],
              "affected_projects": summary["affected_projects"], "diagnostic": "无偏好变更。"}
    if not summary["changes"]:
        _guard(plan)
        return result
    with role_preferences.coordination(plan.state):
        _guard(plan)
        if plan.project is not None:
            target = plan.targets[0]
            identifier = service.commit(plan.state, plan.project, target.changes,
                                        lambda: service.check(plan.project, plan.host, state=plan.state),
                                        before_write=lambda: _guard(plan))
            result.update(applied=True, backup_id=identifier,
                          backups=[{"project": str(plan.project), "backup_id": identifier}] if identifier else [],
                          diagnostic="项目角色偏好已保存。")
            return result
        identifier = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:8]
        relative = "preferences/transactions/" + identifier + ".json"
        previous_global = ([{"path": "preferences/transactions/" + identifier + "-previous-" + uuid.uuid4().hex + ".json",
                             "expected_sha": hashlib.sha256(plan.global_before.payload).hexdigest(),
                             "mode": plan.global_before.mode}] if plan.global_before.kind == "file" else [])
        record = {"schema_version": 1, "id": identifier, "status": "prepared",
                  "global_before": plan.global_before.value(),
                  "global_after": base64.b64encode(plan.global_after).decode(), "global_previous": previous_global,
                  "projects": [{"project": str(target.observation.project), "backup_id": None,
                                "files": [{"path": row.relative, "before_sha": hashlib.sha256(row.before).hexdigest(),
                                           "after_sha": hashlib.sha256(row.after).hexdigest(), "mode": row.mode}
                                          for row in target.changes]}
                               for target in plan.targets if target.changes], "conflicts": []}
        with absolute_directory(plan.state / "preferences" / "transactions", create=True):
            pass
        def save():
            service.write_state(plan.state, relative, service._record_payload(record))
        save()
        completed, observations = [], []
        published = None
        try:
            for target in plan.targets:
                _check_observation(plan.state, target.observation)
                if target.changes:
                    project = target.observation.project
                    backup = service.commit(plan.state, project, target.changes,
                                            lambda project=project: service.check(project, plan.host, state=plan.state),
                                            before_write=lambda target=target: _check_observation(plan.state, target.observation))
                    completed.append(target)
                    next(row for row in record["projects"] if row["project"] == str(project))["backup_id"] = backup
                    result["backups"].append({"project": str(project), "backup_id": backup})
                    save()
                observations.append(_observe(plan.state, target.observation.project)[0])
            # 所有项目先准备并成功后再发布全局权威。最后重查目录及目标，失败
            # 则按精确前后像补偿，不能把部分更新报告为全局成功。
            if role_preferences.snapshot(plan.state)[0] != plan.global_before or _registered(plan.state)[0] != plan.registry_before:
                raise ValueError("全局偏好或登记项目列表在应用期间变化")
            if not check_catalogs(plan.state, None, plan.host, plan.catalog):
                raise ValueError("模型目录来源在应用期间变化")
            for observation in observations:
                _check_observation(plan.state, observation)
            with service.AnchoredFile(plan.state, role_preferences.RELATIVE) as target:
                def retain_global(original, previous, expected):
                    # 私有全局文件也保留旧 inode。仅保存正文副本会遗漏仍持有旧
                    # fd 的编辑器随后写入；永久路径和摘要写入同一恢复明细。
                    archive_relative = record["global_previous"][0]["path"]
                    with service.AnchoredFile(plan.state, archive_relative) as archive:
                        service.os.rename(previous, archive.name, src_dir_fd=original.directory, dst_dir_fd=archive.directory)
                        if archive.read() != expected:
                            raise service.PreservedEdit(archive.path)
                target.retainer = retain_global
                expected = ((plan.global_before.payload, plan.global_before.mode)
                            if plan.global_before.kind == "file" else (None, None))
                target.write(plan.global_after, 0o600, expected)
            published = _read(plan.state, role_preferences.RELATIVE)
            service._check_versions(plan.state, record["global_previous"])
            record["status"] = "applied"
            save()
        except BaseException as failure:
            if isinstance(failure, service.PreservedEdit):
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
                if isinstance(restoration_failure, service.PreservedEdit):
                    detail["retained_path"] = restoration_failure.retained_path
                record["conflicts"].append(detail)
            for target in reversed(completed):
                project = target.observation.project
                try:
                    reverse = [service.Change(row.relative, row.after, row.before, row.mode) for row in target.changes]
                    backup = service.commit(plan.state, project, reverse,
                                            lambda project=project: service.check(project, plan.host, state=plan.state))
                    record["projects"].append({"project": str(project), "rollback_backup_id": backup})
                except (OSError, ValueError):
                    record["conflicts"].append({"path": str(project), "reason": "项目不能安全撤回，保留现状及原备份"})
            record["status"] = "conflict" if record["conflicts"] else "rolled_back"
            try:
                save()
            except BaseException as logging_failure:
                raise ValueError("全局偏好未完成；恢复日志保存失败，请核对事务 " + identifier + " 及项目模型备份") from logging_failure
            raise ValueError("全局偏好未完成；" + ("存在恢复冲突，已保留现状" if record["conflicts"] else "已条件撤回本轮变更") +
                             "；可恢复事务：" + identifier) from failure
        result.update(applied=True, backup_id=identifier, diagnostic="全局角色偏好及实际跟随项目已保存。")
        return result
