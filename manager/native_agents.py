"""三宿主全局原生角色事务；归属独立于项目 binding，恢复仅接管精确产物。"""

from __future__ import annotations

from contextlib import ExitStack
from dataclasses import dataclass, field
import hashlib
import json
from pathlib import Path
import uuid

from lib import role_models, runtime_store
from lib.central import role_preferences
from lib.central.runtime_project import Node, Resources, Tree, absolute_directory, json_bytes, unique_json, read_at
from lib.hosts import native_agents as native
from lib.hosts.native_context import HostPaths, NativeContext
from lib.platform_fs import directory_lock, os
from . import state_files


@dataclass(frozen=True)
class _Observation:
    host: str
    root: Path
    identity: tuple | None
    owner: Node
    record: Node
    discovery: tuple


@dataclass(frozen=True)
class GlobalNativePlan:
    state: Path
    context: NativeContext
    binding_json: bytes = field(repr=False)
    transaction_id: str
    preferences_before: Node
    observations: tuple[_Observation, ...]
    desired: tuple[tuple[str, str, bytes], ...] = field(repr=False)
    summary_json: bytes = field(repr=False)

    @property
    def summary(self) -> dict:
        return json.loads(self.summary_json)

    @property
    def conflicts(self) -> list:
        return self.summary["conflicts"]

    @property
    def can_apply(self) -> bool:
        return self.summary["can_apply"]

    @property
    def hosts(self) -> tuple[str, ...]:
        return tuple(row.host for row in self.observations)

    @property
    def recovery_ref(self) -> dict:
        value = {"schema_version": 1, "state": str(self.state), "transaction_id": self.transaction_id,
                 "targets": [{"host": row.host, "native_root": str(row.root)} for row in self.observations]}
        if not self.summary["changes"]:
            # no-op不创建native journal；中央事务会持久保存此不可变见证，恢复时
            # 必须逐个比较精确文件身份，不能把“没有journal”泛化成已验证成功。
            value["witness"] = [{"host": row.host, "root_identity": list(row.identity or ()),
                                  "owner": _revision(row.owner), "record": _revision(row.record),
                                  "files": {path: _revision(node) for path, node, _ in row.discovery
                                            if path in {native.role_relative(row.host, role) for role in role_models.ROLES}}}
                                 for row in self.observations]
        return value


def _revision(node: Node) -> dict:
    return {"kind": node.kind, "sha256": hashlib.sha256(node.payload).hexdigest(),
            "mode": node.mode, "identity": list(node.identity)}


def _context(state, context) -> tuple[Path, NativeContext]:
    state = state_files.state_root(state)
    if not isinstance(context, NativeContext) or context.state != state:
        raise ValueError("全局原生操作必须提供属于该状态目录的 NativeContext")
    return state, context


def _observe(state: Path, paths: HostPaths, host: str) -> _Observation:
    root = paths.root(host)
    return _Observation(host, root, native.root_identity(root), native.read_node(root, native.OWNER),
                        native.read_node(state, native.record_relative(root)), native.discover(root, host))


def _ownership(state: Path, before: _Observation) -> tuple[dict | None, list]:
    conflicts = []
    record = native.parse_record(before.record, state=state, root=before.root,
                                 host=before.host, identity=before.identity)
    if record is None:
        if before.owner.kind != "missing":
            conflicts.append({"path": str(before.root / native.OWNER), "reason": "宿主根已有未知归属；marker 不能授权接管"})
    elif before.owner.kind != "file" or before.owner.payload != before.record.payload or before.owner.mode != 0o600:
        conflicts.append({"path": str(before.root / native.OWNER), "reason": "宿主根归属锚与私有原像记录不一致"})
    current = {path: node for path, node, _ in before.discovery}
    for role in sorted(role_models.ROLES):
        path = native.role_relative(before.host, role)
        actual = current.get(path, Node())
        if record is None:
            if actual.kind != "missing":
                conflicts.append({"path": str(before.root / path), "reason": "存在未归属同名角色，保留原文件"})
        elif actual != Node.from_value(record["files"][path]["expected"]):
            conflicts.append({"path": str(before.root / path), "reason": "已归属角色被修改、替换或手动删除"})
    for path, _, declared in before.discovery:
        if declared and path != native.role_relative(before.host, declared):
            conflicts.append({"path": str(before.root / path), "reason": "另一原生文件声明相同受管角色名"})
    return record, conflicts


def preview_global(state, binding, *, context: NativeContext, hosts=None, preferences=None) -> GlobalNativePlan:
    """纯读固定核心、偏好、宿主根身份与前像；取消预览不会创建锁或目录。"""
    state, context = _context(state, context)
    selected = tuple(role_models.HOSTS if hosts is None else hosts)
    if not selected or len(set(selected)) != len(selected) or set(selected) - set(role_models.HOSTS):
        raise ValueError("hosts 必须是非空、无重复的宿主子集")
    selected = tuple(host for host in role_models.HOSTS if host in selected)
    core = runtime_store.load_core(binding, state)
    resources = Resources(core.root, json_bytes(core.binding()), core.label, core)
    preference_node, defaults = role_preferences.snapshot(state)
    if preferences is not None:
        defaults = role_preferences.validate({"schema_version": 1, "role_models": preferences})
    observations, desired, changes, conflicts = [], [], [], []
    for host in selected:
        before = _observe(state, context.host_paths, host)
        _, found = _ownership(state, before)
        observations.append(before)
        conflicts.extend(found)
        current = {path: node for path, node, _ in before.discovery}
        for role in sorted(role_models.ROLES):
            path = native.role_relative(host, role)
            body = native.compile_role(resources, host, role, defaults)
            native.validate_descriptor(body, host, role)
            desired.append((host, path, body))
            if not current.get(path, Node()).same_content(Node("file", body, 0o644)):
                changes.append({"host": host, "path": str(before.root / path), "operation": "write"})
    summary = {"scope": "global_native", "changes": changes, "conflicts": conflicts,
               "can_apply": not conflicts, "runtime_verified": False,
               "verification_boundary": "Generated descriptors and ownership do not prove native discovery priority or model execution."}
    return GlobalNativePlan(state, context, json_bytes(core.binding()), uuid.uuid4().hex,
                            preference_node, tuple(observations), tuple(desired), json_bytes(summary))


def _guard(plan: GlobalNativePlan, *, created_roots=()) -> None:
    runtime_store.load_core(unique_json(plan.binding_json), plan.state)
    if role_preferences.snapshot(plan.state)[0] != plan.preferences_before:
        raise ValueError("全局偏好在原生角色预览后变化")
    for before in plan.observations:
        actual = _observe(plan.state, plan.context.host_paths, before.host)
        if before.root in created_roots and before.identity is None:
            actual = _Observation(actual.host, actual.root, None, actual.owner, actual.record, actual.discovery)
        if actual != before:
            raise ValueError("宿主归属、角色或根目录在预览后变化，请重新预览")


def _journal_relative(identifier: str) -> str:
    if not isinstance(identifier, str) or len(identifier) != 32 or any(char not in "0123456789abcdef" for char in identifier):
        raise ValueError("原生事务 ID 无效")
    return "native-agents/transactions/" + identifier + ".json"


def _save(state: Path, journal: dict) -> None:
    relative = _journal_relative(journal["transaction_id"])
    with absolute_directory(state / "native-agents/transactions", create=True):
        pass
    state_files.write_state(state, relative, json_bytes(journal))


def _moved_matches(actual: Node, expected: Node) -> bool:
    # rename/link会改变ctime；inode、正文、mode、size、mtime必须仍是授权前像。
    return (actual.same_content(expected) and actual.identity[:2] == expected.identity[:2]
            and actual.identity[4:6] == expected.identity[4:6])


def _publish(state: Path, journal: dict, root: Path, relative: str, after: Node, *, expected: Node) -> None:
    """从固定plan前像排他发布，绝不重新认领窗口中新出现的同内容inode。

    stage身份及旧inode保留路径先写持久journal，再隔离/发布；即使进程在最后
    产物身份记录前退出，恢复也能凭stage inode区分本轮产物与未知同内容文件。
    所有文件操作沿同一Tree父fd进行；目录换链不会把发布带到授权根之外。
    """
    before = native.read_node(root, relative)
    if before != expected:
        raise ValueError("原生文件在固定预览后被替换或修改")
    if expected.same_content(after):
        return
    token = journal["transaction_id"] + "-" + uuid.uuid4().hex
    stage_name, held_name = ".awf-native-stage-" + token, ".workflow-models-previous-" + token + ".tmp"
    parent_path = Path(relative).parent
    stage_path = str(parent_path / stage_name)
    row = {"root": str(root), "path": relative, "before": expected.value(), "after": after.value(),
           "published": None, "retained": [], "stage": stage_path, "staged": None}
    journal["writes"].append(row)
    _save(state, journal)
    with Tree(root) as tree:
        parent, name = tree.parent(relative, create=True)
        if read_at(parent, name) != expected:
            raise ValueError("原生文件在打开父目录后发生变化")
        descriptor = os.open(stage_name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=parent)
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(after.payload)
            stream.flush()
            os.fchmod(stream.fileno(), after.mode)
            os.fsync(stream.fileno())
        row["staged"] = read_at(parent, stage_name).value()
        _save(state, journal)
        # stage磁盘写入期间的同内容替换也必须拒绝，完整Node比较包含inode/ctime。
        if read_at(parent, name) != expected:
            raise ValueError("原生文件在最终隔离前发生变化")
        if expected.kind == "file":
            row["retained"].append({"path": str(parent_path / held_name), "expected": expected.value()})
            _save(state, journal)
            os.rename(name, held_name, src_dir_fd=parent, dst_dir_fd=parent)
            if not _moved_matches(read_at(parent, held_name), expected):
                raise ValueError("原生旧inode在隔离窗口发生变化，已保全原像")
        # exclusive link不覆盖隔离后被编辑器重建的目标；stage链接移除后恢复nlink=1。
        os.link(stage_name, name, src_dir_fd=parent, dst_dir_fd=parent, follow_symlinks=False)
        os.unlink(stage_name, dir_fd=parent)
        os.fsync(parent)
        published = read_at(parent, name)
        if not _moved_matches(published, Node.from_value(row["staged"])):
            raise ValueError("原生产物在发布窗口被替换，已保全原像")
        row["published"] = published.value()
        _save(state, journal)


def _receipt(journal: dict) -> dict:
    return {"schema_version": 1, "transaction_id": journal["transaction_id"],
            "recovery_ref": journal["recovery_ref"], "status": journal["status"],
            "applied": journal["status"] == "applied", "conflicts": journal.get("conflicts", []),
            "artifacts": [{"root": row["root"], "path": row["path"], "node": row["published"]}
                          for row in journal["writes"] if row.get("published") is not None]}


def apply_global(plan: GlobalNativePlan) -> dict:
    if not isinstance(plan, GlobalNativePlan) or not plan.can_apply:
        raise ValueError("全局原生预览存在冲突，不能应用")
    # 真正 no-op 在任何创建型协调锁前返回，不制造事务/备份/目录。
    if not plan.summary["changes"]:
        _guard(plan)
        return {"schema_version": 1, "transaction_id": plan.transaction_id, "recovery_ref": plan.recovery_ref,
                "status": "noop", "applied": False, "artifacts": [], "conflicts": []}
    with role_preferences.coordination(plan.state), ExitStack() as stack:
        _guard(plan)
        journal = {"schema_version": 1, "transaction_id": plan.transaction_id, "recovery_ref": plan.recovery_ref,
                   "status": "prepared", "writes": [], "conflicts": [], "applied_evidence": None, "root_identities": {},
                   "desired": [{"host": host, "path": path, "after": Node("file", body, 0o644).value()}
                               for host, path, body in plan.desired]}
        _save(plan.state, journal)
        created = []
        try:
            for before in sorted(plan.observations, key=lambda row: str(row.root)):
                stack.enter_context(absolute_directory(before.root, create=True))
                if before.identity is None:
                    created.append(before.root)
                # 锁键是宿主物理根 inode，与 state 无关；两个 state 不能同时接管同一根。
                stack.enter_context(directory_lock(before.root, "native-roles"))
            _guard(plan, created_roots=created)
            journal["root_identities"] = {str(row.root): list(native.root_identity(row.root)) for row in plan.observations}
            _save(plan.state, journal)
            for before in plan.observations:
                record, conflicts = _ownership(plan.state, _observe(plan.state, plan.context.host_paths, before.host))
                if conflicts:
                    raise ValueError("全局原生归属在提交前变化")
                entries = {}
                for host, relative, body in plan.desired:
                    if host != before.host:
                        continue
                    baseline = (record["files"][relative]["baseline"] if record else Node().value())
                    _publish(plan.state, journal, before.root, relative, Node("file", body, 0o644),
                             expected=next((node for path, node, _ in before.discovery if path == relative), Node()))
                    entries[relative] = {"baseline": baseline,
                                         "expected": native.read_node(before.root, relative).value()}
                payload = json_bytes({"schema_version": 1, "host": before.host, "native_root": str(before.root),
                                      "root_identity": list(native.root_identity(before.root)), "state": str(plan.state),
                                      "files": entries})
                _publish(plan.state, journal, before.root, native.OWNER, Node("file", payload, 0o600), expected=before.owner)
                _publish(plan.state, journal, plan.state, native.record_relative(before.root), Node("file", payload, 0o600), expected=before.record)
            journal["status"] = "applied"
            journal["applied_evidence"] = _receipt(journal)
            _save(plan.state, journal)
            return _receipt(journal)
        except BaseException:
            # 异常不能伪装无副作用。保留 prepared 日志；中央父事务已有 recovery_ref，
            # 可在自身短锁范围内显式条件补偿，避免这里递归获取相同原生根锁。
            journal["status"] = "prepared"
            _save(plan.state, journal)
            raise


def _load_ref(recovery_ref, context: NativeContext) -> tuple[Path, dict | None]:
    if not isinstance(recovery_ref, dict) or set(recovery_ref) not in ({"schema_version", "state", "transaction_id", "targets"}, {"schema_version", "state", "transaction_id", "targets", "witness"}):
        raise ValueError("原生恢复引用无效")
    state, _ = _context(Path(recovery_ref["state"]), context)
    if recovery_ref["schema_version"] != 1 or not isinstance(recovery_ref["targets"], list):
        raise ValueError("原生恢复引用版本无效")
    for target in recovery_ref["targets"]:
        if (not isinstance(target, dict) or set(target) != {"host", "native_root"}
                or target["host"] not in role_models.HOSTS
                or target["native_root"] != str(context.host_paths.root(target["host"]))):
            raise ValueError("原生恢复引用跨越已授权宿主根")
    node = native.read_node(state, _journal_relative(recovery_ref["transaction_id"]))
    if node.kind == "missing":
        return state, None
    journal = unique_json(node.payload)
    if (not isinstance(journal, dict) or set(journal) != {"schema_version", "transaction_id", "recovery_ref", "status", "writes", "conflicts", "applied_evidence", "root_identities", "desired"}
            or journal["schema_version"] != 1 or journal["recovery_ref"] != recovery_ref
            or journal["transaction_id"] != recovery_ref["transaction_id"]
            or journal["status"] not in {"prepared", "applied", "compensated", "conflict"}
            or not isinstance(journal["writes"], list) or not isinstance(journal["conflicts"], list)):
        raise ValueError("原生恢复日志版本或引用无效")
    allowed = {(str(context.host_paths.root(target["host"])), native.OWNER) for target in recovery_ref["targets"]}
    for target in recovery_ref["targets"]:
        root = context.host_paths.root(target["host"])
        allowed.add((str(state), native.record_relative(root)))
        allowed.update((str(root), native.role_relative(target["host"], role)) for role in role_models.ROLES)
    seen = set()
    for row in journal["writes"]:
        if (not isinstance(row, dict) or set(row) - {"root", "path", "before", "after", "published", "retained", "restored", "stage", "staged"}
                or (row.get("root"), row.get("path")) not in allowed
                or (row["root"], row["path"]) in seen):
            raise ValueError("原生恢复日志包含未授权或重复目标")
        seen.add((row["root"], row["path"]))
        before = Node.from_value(row["before"])
        after = Node.from_value(row["after"])
        if before.kind not in {"missing", "file"} or after.kind != "file" or not isinstance(row.get("retained"), list):
            raise ValueError("原生恢复快照类型无效")
        for held in row["retained"]:
            if (not isinstance(held, dict) or set(held) != {"path", "expected"}
                    or not isinstance(held["path"], str) or Path(held["path"]).parent != Path(row["path"]).parent
                    or not Path(held["path"]).name.startswith(".workflow-models-previous-")
                    or not Path(held["path"]).name.endswith(".tmp") or held["expected"] != row["before"]):
                raise ValueError("原生恢复旧 inode 路径无效")
        if row.get("stage") is not None and (not isinstance(row["stage"], str)
                or Path(row["stage"]).parent != Path(row["path"]).parent
                or not Path(row["stage"]).name.startswith(".awf-native-stage-" + journal["transaction_id"] + "-")):
            raise ValueError("原生恢复stage路径无效")
        if row.get("staged") is not None:
            Node.from_value(row["staged"])
        if row.get("published") is not None:
            Node.from_value(row["published"])
    return state, journal


def _check_retained(row: dict, *, allow_missing: bool = False) -> None:
    for held in row["retained"]:
        node = native.read_node(Path(row["root"]), held["path"])
        before = Node.from_value(held["expected"])
        if allow_missing and node.kind == "missing":
            continue
        # rename 改变 ctime，但不改变 inode、mtime 和正文；保留旧 fd 后的保存
        # 或权限修改必须停止恢复，不能把后续用户编辑藏在一次成功补偿后面。
        if (not node.same_content(before) or node.identity[:2] != before.identity[:2]
                or node.identity[5:6] != before.identity[5:6]):
            raise ValueError("保留的原生旧 inode 已有后续编辑")


def compensate_global(recovery_ref, *, context: NativeContext) -> dict:
    """补偿是有条件且可重入的逆操作；不将相同正文的未知替换文件当成本轮产物。"""
    state, journal = _load_ref(recovery_ref, context)
    if journal is None:
        issues = _verify_witness(recovery_ref, context) if "witness" in recovery_ref else []
        return {"status": "conflict" if issues else "noop" if "witness" in recovery_ref else "not_started",
                "applied": False, "conflicts": issues, "recovery_ref": recovery_ref}
    with role_preferences.coordination(state), ExitStack() as stack:
        for target in sorted(recovery_ref["targets"], key=lambda row: row["native_root"]):
            root = Path(target["native_root"])
            if native.root_identity(root) is not None:
                stack.enter_context(directory_lock(root, "native-roles"))
        # 等锁后重新读日志，避免同一 ref 的两个恢复者用旧中间态覆盖彼此。
        _, journal = _load_ref(recovery_ref, context)
        conflicts = _root_issues(journal)
        if conflicts:
            journal["conflicts"], journal["status"] = conflicts, "conflict"
            _save(state, journal)
            return _receipt(journal)
        for row in reversed(journal["writes"]):
            try:
                root, path = Path(row["root"]), row["path"]
                current = native.read_node(root, path)
                if row.get("restored") is not None:
                    if current != Node.from_value(row["restored"]):
                        raise ValueError("补偿后的节点已有后续编辑")
                    continue
                published = Node.from_value(row["published"]) if row.get("published") is not None else None
                before = Node.from_value(row["before"])
                if current == before:
                    _check_retained(row, allow_missing=True)
                    _clean_stage(row)
                    row["restored"] = current.value()
                    _save(state, journal)
                    continue
                _check_retained(row)
                if published is None and row.get("staged") is not None and _moved_matches(current, Node.from_value(row["staged"])):
                    published = current
                if published is None and current.kind == "missing" and before.kind == "file" and row["retained"]:
                    # 进程可能在隔离旧inode后、排他发布前退出；日志已登记旧inode，
                    # 当前目标仍缺失时可恢复原内容。新出现目标一律保留并报冲突。
                    with state_files.AnchoredFile(root, path) as target:
                        target.write(before.payload, before.mode, (None, None))
                    _clean_stage(row)
                    row["restored"] = native.read_node(root, path).value()
                    _save(state, journal)
                    continue
                if published is None or current != published:
                    raise ValueError("原生产物身份不再属于本次事务")
                with state_files.AnchoredFile(root, path) as target:
                    if before.kind == "file":
                        target.write(before.payload, before.mode, (published.payload, published.mode))
                    else:
                        held = ".native-rollback-" + journal["transaction_id"] + "-" + uuid.uuid4().hex
                        os.rename(target.name, held, src_dir_fd=target.directory, dst_dir_fd=target.directory)
                        moved = target.read(held)
                        if moved != (published.payload, published.mode):
                            raise state_files.PreservedEdit(target.path.parent / held)
                        os.unlink(held, dir_fd=target.directory)
                _clean_stage(row)
                row["restored"] = native.read_node(root, path).value()
                _save(state, journal)
            except (OSError, ValueError):
                conflicts.append({"root": row["root"], "path": row["path"], "reason": "恢复身份或旧 inode 冲突，已保留文件和日志"})
        if not conflicts:
            # 内容恢复会生成新 inode，原归属记录中的 expected 不能仍指旧 inode。
            # 只在所有逆操作成功、正文仍等于原授权快照时重建这两个私有身份投影；
            # 这不是重新编译或补装角色，模型/权限及最初 baseline 均保持原值。
            for target in recovery_ref["targets"]:
                root = Path(target["native_root"])
                record_path = native.record_relative(root)
                current_record = native.read_node(state, record_path)
                if current_record.kind == "missing":
                    continue
                record = native.parse_record(current_record, state=state, root=root, host=target["host"],
                                             identity=native.root_identity(root))
                for path, entry in record["files"].items():
                    current = native.read_node(root, path)
                    if not current.same_content(Node.from_value(entry["expected"])):
                        conflicts.append({"root": str(root), "path": path, "reason": "恢复后正文与原归属不一致"})
                        break
                    entry["expected"] = current.value()
                if conflicts:
                    break
                payload = json_bytes(record)
                for owner_root, owner_path in ((root, native.OWNER), (state, record_path)):
                    node = native.read_node(owner_root, owner_path)
                    if node.payload != payload:
                        with state_files.AnchoredFile(owner_root, owner_path) as target_file:
                            target_file.write(payload, 0o600, (node.payload, node.mode))
                        restored = native.read_node(owner_root, owner_path)
                        for row in journal["writes"]:
                            if row["root"] == str(owner_root) and row["path"] == owner_path:
                                row["restored"] = restored.value()
                        _save(state, journal)
        journal["conflicts"] = conflicts
        journal["status"] = "conflict" if conflicts else "compensated"
        _save(state, journal)
        return _receipt(journal)


def recover_global(recovery_ref, *, context: NativeContext) -> dict:
    """中央父事务失败后的恢复入口，沿同一引用幂等补偿，不重新生成全局角色。"""
    return compensate_global(recovery_ref, context=context)


def status(state, host: str, *, context: NativeContext) -> dict:
    state, context = _context(state, context)
    before = _observe(state, context.host_paths, host)
    record, conflicts = _ownership(state, before)
    return {"host": host, "managed": record is not None, "conflicts": conflicts,
            "roles": sorted(role_models.ROLES) if record is not None and not conflicts else [],
            "native_root": str(before.root), "runtime_verified": False}


def status_global(state, *, context: NativeContext) -> dict:
    """只读完整七角色归属投影；损坏归属作为事实冲突，不冒充已安装。"""
    state, context = _context(state, context)
    hosts = {}
    for host in role_models.HOSTS:
        try:
            hosts[host] = status(state, host, context=context)
        except (OSError, ValueError):
            hosts[host] = {"host": host, "managed": False, "roles": [], "native_root": str(context.host_paths.root(host)),
                           "conflicts": [{"path": str(context.host_paths.root(host)), "reason": "原生归属记录无效或不可读"}],
                           "runtime_verified": False}
    return {"hosts": hosts, "verified_hosts": [host for host, value in hosts.items() if value["roles"]],
            "runtime_verified": False}


def verified_hosts(state, *, context: NativeContext) -> tuple[str, ...]:
    return tuple(status_global(state, context=context)["verified_hosts"])


def _root_issues(journal: dict) -> list[dict]:
    identities = journal.get("root_identities")
    if not isinstance(identities, dict):
        raise ValueError("原生恢复根身份无效")
    allowed = {target["native_root"] for target in journal["recovery_ref"]["targets"]}
    if set(identities) - allowed:
        raise ValueError("原生恢复根身份越界")
    return [{"type": "native_root_conflict", "path": root, "reason": "宿主物理根已替换或删除"}
            for root, identity in identities.items() if list(native.root_identity(Path(root)) or ()) != identity]


def _clean_stage(row: dict) -> None:
    if row.get("stage") is None:
        return
    root = Path(row["root"])
    actual = native.read_node(root, row["stage"])
    if actual.kind == "missing":
        return
    if row.get("staged") is None or actual != Node.from_value(row["staged"]):
        raise ValueError("原生stage含未知后续编辑，已保留")
    with Tree(root) as tree:
        parent, name = tree.parent(row["stage"])
        if read_at(parent, name) != actual:
            raise ValueError("原生stage在清理前变化")
        os.unlink(name, dir_fd=parent)
        os.fsync(parent)


def _verify_witness(reference: dict, context: NativeContext) -> list[dict]:
    expected = reference.get("witness")
    targets = {row["host"]: row["native_root"] for row in reference["targets"]}
    if not isinstance(expected, list) or len(expected) != len(targets):
        raise ValueError("no-op原生见证无效")
    issues, seen = [], set()
    for witness in expected:
        if (not isinstance(witness, dict) or set(witness) != {"host", "root_identity", "owner", "record", "files"}
                or witness["host"] not in targets or witness["host"] in seen
                or not isinstance(witness["files"], dict)
                or set(witness["files"]) != {native.role_relative(witness["host"], role) for role in role_models.ROLES}):
            raise ValueError("no-op原生见证范围无效")
        host = witness["host"]
        seen.add(host)
        before = _observe(context.state, context.host_paths, host)
        record, conflicts = _ownership(context.state, before)
        current = {path: _revision(node) for path, node, _ in before.discovery if path in witness["files"]}
        if (record is None or conflicts or list(before.identity or ()) != witness["root_identity"]
                or _revision(before.owner) != witness["owner"] or _revision(before.record) != witness["record"]
                or current != witness["files"]):
            issues.append({"type": "native_noop_witness_conflict", "path": targets[host],
                           "reason": "no-op见证中的原生归属、根或精确产物身份已变化"})
    return issues


def verify_global(recovery_ref, *, context: NativeContext) -> list[dict]:
    """已发布current的结算纯查固定产物；no-op仅凭持久ref中的精确见证验真。"""
    state, journal = _load_ref(recovery_ref, context)
    if journal is None:
        if "witness" in recovery_ref:
            return _verify_witness(recovery_ref, context)
        return [{"type": "native_journal_missing", "path": _journal_relative(recovery_ref["transaction_id"]),
                 "reason": "预期原生事务尚无持久日志"}]
    issues = _root_issues(journal)
    if journal["status"] in {"compensated", "conflict"}:
        issues.append({"type": "native_transaction_not_applied", "path": _journal_relative(journal["transaction_id"]),
                       "reason": "原生事务已补偿或存在冲突"})
    for row in journal["writes"]:
        try:
            _check_retained(row)
            if row.get("published") is None or native.read_node(Path(row["root"]), row["path"]) != Node.from_value(row["published"]):
                raise ValueError("精确产物身份不符")
        except (OSError, ValueError):
            issues.append({"type": "native_artifact_conflict", "path": str(Path(row["root"]) / row["path"]),
                           "reason": "原生产物缺失、替换、手改或保留旧inode已变化"})
    if not isinstance(journal.get("desired"), list):
        raise ValueError("原生事务缺少完整目标清单")
    for desired in journal["desired"]:
        root = context.host_paths.root(desired["host"])
        if (desired["path"] not in {native.role_relative(desired["host"], role) for role in role_models.ROLES}
                or not native.read_node(root, desired["path"]).same_content(Node.from_value(desired["after"]))):
            issues.append({"type": "native_desired_incomplete", "path": str(root / desired["path"]),
                           "reason": "原生完整目标尚未发布"})
    for target in recovery_ref["targets"]:
        try:
            current = status(state, target["host"], context=context)
            if not current["roles"]:
                raise ValueError("全局角色归属不完整")
        except (OSError, ValueError):
            issues.append({"type": "native_ownership_conflict", "path": target["native_root"],
                           "reason": "全局七角色归属无效"})
    return issues


def has_records(state: Path) -> bool:
    """只看本 state 的明确归属索引；不能据此反推/授权任何 HOME 宿主路径。"""
    try:
        with absolute_directory(state / "native-agents/roots") as descriptor:
            names = os.listdir(descriptor)
            if len(names) > 512:
                raise ValueError("原生归属索引超过有界条目限制")
            return bool(names)
    except FileNotFoundError:
        return False


def current_binding(state: Path) -> dict:
    node = native.read_node(state, "central/current.json")
    if node.kind != "file":
        raise ValueError("已安装全局原生角色缺少中央当前版本记录")
    value = unique_json(node.payload)
    if (not isinstance(value, dict) or set(value) != {"schema_version", "runtime_binding", "previous_binding", "generation"}
            or type(value["schema_version"]) is not int or value["schema_version"] != 1
            or not isinstance(value["generation"], str) or len(value["generation"]) != 32
            or any(char not in "0123456789abcdef" for char in value["generation"])):
        raise ValueError("中央当前版本记录无效")
    if value["previous_binding"] is not None:
        runtime_store.validate_binding(value["previous_binding"])
    return runtime_store.validate_binding(value["runtime_binding"])


def referenced_bindings(state: Path) -> tuple:
    """原生正文/恢复快照不引用 core；未知持久 schema 仍使 GC 保守失败关闭。

    这里只在本 state 的两个明确目录读取有界 JSON，不扫描宿主 HOME。全局
    bootstrap 读取 Task Pack pin，既无核心路径也无全局 Skill 软链，因此无需
    额外保活旧 core；活动任务与项目 used_bindings 由中央 owner 单独处理。
    """
    for directory in ("native-agents/roots", "native-agents/transactions"):
        try:
            with absolute_directory(state / directory) as descriptor:
                names = os.listdir(descriptor)
                if len(names) > 512:
                    raise ValueError("原生记录超过有界条目限制")
                for name in names:
                    if not name.endswith(".json") or "/" in name:
                        raise ValueError("原生记录含未知条目")
                    node = native.read_node(state, directory + "/" + name)
                    value = unique_json(node.payload)
                    if not isinstance(value, dict) or type(value.get("schema_version")) is not int or value["schema_version"] != 1:
                        raise ValueError("原生记录 schema 未知，不能判定 GC 引用")
        except FileNotFoundError:
            pass
    return ()
