"""三宿主全局原生角色事务；归属独立于项目 binding，恢复仅接管精确产物。"""

from __future__ import annotations

from contextlib import ExitStack, contextmanager
from contextvars import ContextVar
import base64
import re
import stat
from dataclasses import dataclass, field
import hashlib
import json
from pathlib import Path
import uuid

from lib import role_models, runtime_store
from lib.central import role_preferences
from lib.central.runtime_project import Node, Resources, Tree, absolute_directory, json_bytes, unique_json, read_at, identity, LIMIT, READ_FLAGS
from lib.hosts import native_agents as native
from lib.hosts.native_context import HostPaths, NativeContext
from lib.platform_fs import directory_lock, os
from . import state_files


_PREFERENCE_PROJECTION: ContextVar[tuple | None] = ContextVar("native_preference_projection", default=None)


@contextmanager
def preference_projection(state: Path, transaction_id: str, payload: bytes):
    """仅真实prepared偏好事务在本调用栈校验将要发布的全局模型投影。

    全局事务先更新native/project、最后发布prefs；中间的自身健康检查必须看到
    已授权的future值。入口验证实际持久prepared记录、精确前像及after，不使用
    环境变量；其他线程/进程仍读取持久prefs，中间态不能据此获得新任务许可。
    """
    state = state_files.state_root(state)
    if not isinstance(transaction_id, str) or not re.fullmatch(r"[0-9]{8}T[0-9]{6}Z-[0-9a-f]{8}", transaction_id):
        raise ValueError("偏好活动投影缺少有效事务ID")
    role_preferences.validate(unique_json(payload))
    node = native.read_node(state, "preferences/transactions/" + transaction_id + ".json")
    record = unique_json(node.payload)
    if (node.kind != "file" or node.mode != 0o600 or not isinstance(record, dict)
            or record.get("schema_version") != 1 or record.get("id") != transaction_id
            or record.get("status") != "prepared"
            or base64.b64decode(record.get("global_after", ""), validate=True) != payload
            or Node.from_value(record.get("global_before")) != role_preferences.snapshot(state)[0]):
        raise ValueError("偏好活动投影不属于当前真实prepared事务")
    token = _PREFERENCE_PROJECTION.set((str(state), transaction_id, bytes(payload), os.getpid()))
    try:
        yield
    finally:
        _PREFERENCE_PROJECTION.reset(token)


def _projected_preferences(state: Path) -> tuple[Node, dict]:
    before, defaults = role_preferences.snapshot(state)
    active = _PREFERENCE_PROJECTION.get()
    if active is not None and active[0] == str(state) and active[3] == os.getpid():
        defaults = role_preferences.validate(unique_json(active[2]))
    return before, defaults


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
        root_info = os.fstat(tree.directories[""])
        root_identity = journal["root_identities"].get(str(root))
        if root_identity is not None and [root_info.st_dev, root_info.st_ino] != root_identity:
            raise ValueError("原生宿主物理根在固定预览后被替换")
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
        from . import runtime_policy
        runtime_policy.ensure_management_settled(plan.state)
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
    journal_keys = {"schema_version", "transaction_id", "recovery_ref", "status", "writes", "conflicts", "applied_evidence", "root_identities", "desired"}
    if (not isinstance(journal, dict) or set(journal) not in (journal_keys, journal_keys | {"compensations"})
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
    if not isinstance(journal.get("compensations", []), list):
        raise ValueError("原生补偿节点记录无效")
    for step in journal.get("compensations", []):
        if (not isinstance(step, dict) or set(step) != {"root", "path", "expected", "after", "stage", "staged", "held", "isolated", "result", "returned"}
                or not isinstance(step["root"], str) or not isinstance(step["path"], str)
                or (step["root"], step["path"]) not in allowed or type(step["returned"]) is not bool):
            raise ValueError("原生补偿节点范围或字段无效")
        expected, after = Node.from_value(step["expected"]), Node.from_value(step["after"])
        if (expected.kind not in {"file", "missing"} or after.kind not in {"file", "missing"}
                or expected.kind == "file" and len(expected.identity) != 7):
            raise ValueError("原生补偿仅允许普通文件及缺失节点")
        for key, prefix in (("stage", ".awf-native-restore-"), ("held", ".native-rollback-")):
            path = step[key]
            if path is not None and (not isinstance(path, str) or str(Path(path)) != path or Path(path).parent != Path(step["path"]).parent
                    or not re.fullmatch(re.escape(prefix + journal["transaction_id"] + "-") + r"[0-9a-f]{32}", Path(path).name)):
                raise ValueError("原生补偿临时节点路径无效")
        if (step["stage"] is None) != (after.kind == "missing") or (step["held"] is None) != (expected.kind == "missing"):
            raise ValueError("原生补偿临时节点类型不符")
        for key in ("staged", "isolated", "result"):
            if step[key] is not None:
                Node.from_value(step[key])
        if step["staged"] is not None and not Node.from_value(step["staged"]).same_content(after):
            raise ValueError("原生补偿stage内容不符")
        if step["result"] is not None:
            result = Node.from_value(step["result"])
            if (step["returned"] or not result.same_content(after)
                    or after.kind == "file" and (step["staged"] is None or not _moved_matches(result, Node.from_value(step["staged"])))):
                raise ValueError("原生补偿结果不属于已登记stage")
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


def _compensation_result(journal: dict, root: Path, path: str) -> Node | None:
    for step in reversed(journal.get("compensations", [])):
        if step["root"] == str(root) and step["path"] == path and step["result"] is not None:
            return Node.from_value(step["result"])
    return None


def _check_compensation_history(journal: dict, root: Path, path: str) -> None:
    for step in journal.get("compensations", []):
        if step["root"] != str(root) or step["path"] != path:
            continue
        if step["returned"]:
            raise ValueError("该补偿已保全未知inode，不能自动认领或清理")
        for name, snapshot in (("stage", "staged"), ("held", "isolated")):
            if step[name] is None:
                continue
            actual = native.read_node(root, step[name])
            if actual.kind != "missing" and (step[snapshot] is None or actual != Node.from_value(step[snapshot])):
                raise ValueError("补偿保留节点已有后续编辑，已停止恢复")


def _read_compensation_pair(parent: int, stage: str, name: str, expected: Node) -> Node:
    """只识别本journal登记的stage和目标形成的精确双链接中间态。

    普通reader仍只接受nlink1。这里同时固定两个名字、同一个inode及完整读取
    前后像，并要求nlink恰为2；第三个硬链接、替换stage、未知同内容inode都拒绝。
    link/unlink会改变ctime与nlink，因此只在此封闭中间态用已登记inode、正文、
    mode、size、mtime证明来源；这不是给任意原生文件放宽身份核验。
    """
    before = os.stat(stage, dir_fd=parent, follow_symlinks=False)
    if (not stat.S_ISREG(before.st_mode) or before.st_nlink != 2 or before.st_size > LIMIT
            or identity(os.stat(name, dir_fd=parent, follow_symlinks=False)) != identity(before)):
        raise ValueError("补偿发布双链接不属于唯一登记节点对")
    descriptor = os.open(stage, READ_FLAGS, dir_fd=parent)
    with os.fdopen(descriptor, "rb") as stream:
        if identity(os.fstat(stream.fileno())) != identity(before):
            raise ValueError("补偿双链接在打开期间变化")
        body = stream.read(LIMIT + 1)
        if len(body) > LIMIT or identity(os.fstat(stream.fileno())) != identity(before):
            raise ValueError("补偿双链接在读取期间变化")
    actual = Node("file", body, stat.S_IMODE(before.st_mode), identity(before))
    if (not _moved_matches(actual, expected)
            or any(identity(os.stat(path, dir_fd=parent, follow_symlinks=False)) != identity(before)
                   for path in (stage, name))):
        raise ValueError("补偿双链接身份或内容与登记stage不一致")
    return actual


def _advance_compensation(state: Path, journal: dict, step: dict) -> Node:
    """首次执行和恢复共用的有界推进器；只沿本步骤已有身份向前推进。

    所有临时名字先写journal，文件stage完整Node在隔离前落盘。隔离后未记
    isolated时仍可由expected的原inode证明；发布后未记result时由staged证明。
    已有证据的中断继续原步骤，不追加新补偿；没有身份证据的残留只能保全报错。
    """
    root, path = Path(step["root"]), step["path"]
    expected, after = Node.from_value(step["expected"]), Node.from_value(step["after"])
    stage = Path(step["stage"]).name if step["stage"] else None
    held = Path(step["held"]).name if step["held"] else None
    if step["returned"]:
        raise ValueError("该补偿已保全未知inode，不能自动认领或清理")
    with Tree(root) as tree:
        root_info = os.fstat(tree.directories[""])
        root_identity = journal["root_identities"].get(str(root))
        if root_identity is not None and [root_info.st_dev, root_info.st_ino] != root_identity:
            raise ValueError("补偿宿主物理根已变化")
        parent, name = tree.parent(path)
        if step["result"] is None:
            if stage is not None and step["staged"] is None:
                # 随机路径本身不证明归属：create成功却未持久Node的中断残留
                # 不可认领。也不允许已经隔离后再临时创造另一份stage。
                if (read_at(parent, stage).kind != "missing" or read_at(parent, name) != expected
                        or held is not None and read_at(parent, held).kind != "missing"):
                    raise ValueError("补偿stage缺少持久身份或前像已变化")
                descriptor = os.open(stage, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=parent)
                with os.fdopen(descriptor, "wb") as stream:
                    stream.write(after.payload)
                    stream.flush()
                    os.fchmod(stream.fileno(), after.mode)
                    os.fsync(stream.fileno())
                step["staged"] = read_at(parent, stage).value()
                _save(state, journal)
            if held is not None:
                isolated = read_at(parent, held)
                if isolated.kind == "missing":
                    if step["isolated"] is not None or read_at(parent, name) != expected:
                        raise ValueError("补偿隔离节点缺失或最终前像已变化")
                    os.rename(name, held, src_dir_fd=parent, dst_dir_fd=parent)
                    isolated = read_at(parent, held)
                if step["isolated"] is None:
                    # rename之后、保存isolated之前崩溃仍有expected的完整inode
                    # 授权；仅允许rename应改变的ctime，不认领同正文的新inode。
                    step["isolated"] = isolated.value()
                    _save(state, journal)
                elif isolated != Node.from_value(step["isolated"]):
                    raise state_files.PreservedEdit(root / step["held"])
                if not _moved_matches(isolated, expected):
                    step["returned"] = True
                    _save(state, journal)
                    try:
                        os.link(held, name, src_dir_fd=parent, dst_dir_fd=parent, follow_symlinks=False)
                        os.fsync(parent)
                    except FileExistsError:
                        pass
                    raise state_files.PreservedEdit(root / step["held"])
            if stage is not None:
                staged = Node.from_value(step["staged"])
                try:
                    stage_info = os.stat(stage, dir_fd=parent, follow_symlinks=False)
                except FileNotFoundError:
                    stage_info = None
                if stage_info is not None and stage_info.st_nlink == 2:
                    # exclusive link已成功、stage尚未移除：普通read_at应继续拒绝，
                    # 仅此两个明确登记的路径可核实同inode后完成stage清理。
                    _read_compensation_pair(parent, stage, name, staged)
                    os.unlink(stage, dir_fd=parent)
                elif stage_info is not None:
                    if read_at(parent, stage) != staged or read_at(parent, name).kind != "missing":
                        raise ValueError("补偿stage或排他发布目标已变化")
                    os.link(stage, name, src_dir_fd=parent, dst_dir_fd=parent, follow_symlinks=False)
                    _read_compensation_pair(parent, stage, name, staged)
                    os.unlink(stage, dir_fd=parent)
                # stage已经移除、result未持久：仍必须证明目标就是staged inode。
                result = read_at(parent, name)
                if not _moved_matches(result, staged):
                    raise ValueError("补偿产物在发布窗口被替换")
            else:
                result = read_at(parent, name)
                if result.kind != "missing":
                    raise ValueError("补偿删除期间目标被外部重建")
            os.fsync(parent)
            step["result"] = result.value()
            _save(state, journal)
        result = Node.from_value(step["result"])
        if read_at(parent, name) != result:
            raise ValueError("补偿已发布结果出现未知替换或编辑")
        if stage is not None and read_at(parent, stage).kind != "missing":
            raise ValueError("已结算补偿出现未知stage残留")
        if held is not None:
            isolated = read_at(parent, held)
            if isolated.kind != "missing":
                if step["isolated"] is None or isolated != Node.from_value(step["isolated"]):
                    raise state_files.PreservedEdit(root / step["held"])
                os.unlink(held, dir_fd=parent)
                os.fsync(parent)
        return result


def _resume_compensation(state: Path, journal: dict, root: Path, path: str) -> None:
    # 同一路径可能先恢复原metadata再重建身份投影；较早已结算步骤不再拥有
    # 当前目标，只有最新步骤能继续推进。旧保留节点仍由history逐个精确检查。
    latest = next((step for step in reversed(journal.get("compensations", []))
                   if step["root"] == str(root) and step["path"] == path), None)
    if latest is not None:
        _advance_compensation(state, journal, latest)


def _compensate_node(state: Path, journal: dict, root: Path, path: str, *, expected: Node, after: Node) -> Node:
    """先持久登记完整授权，再由与recover相同的推进器执行文件逆操作。"""
    token = journal["transaction_id"] + "-" + uuid.uuid4().hex
    parent_path = Path(path).parent
    stage = ".awf-native-restore-" + token if after.kind == "file" else None
    held = ".native-rollback-" + token if expected.kind == "file" else None
    step = {"root": str(root), "path": path, "expected": expected.value(), "after": after.value(),
            "stage": str(parent_path / stage) if stage else None, "staged": None,
            "held": str(parent_path / held) if held else None, "isolated": None,
            "result": None, "returned": False}
    journal.setdefault("compensations", []).append(step)
    _save(state, journal)
    return _advance_compensation(state, journal, step)


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
                _check_retained(row, allow_missing=row.get("restored") is not None)
                _resume_compensation(state, journal, root, path)
                _check_compensation_history(journal, root, path)
                current = native.read_node(root, path)
                before = Node.from_value(row["before"])
                recovered = _compensation_result(journal, root, path)
                if recovered is not None:
                    if current != recovered:
                        raise ValueError("补偿产物已有未知替换或编辑")
                    row["restored"] = recovered.value()
                if row.get("restored") is not None:
                    _check_retained(row, allow_missing=current == before)
                    if current != Node.from_value(row["restored"]):
                        raise ValueError("补偿后的节点已有后续编辑")
                    continue
                published = Node.from_value(row["published"]) if row.get("published") is not None else None
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
                    restored = _compensate_node(state, journal, root, path, expected=current, after=before)
                else:
                    if published is None or current != published:
                        raise ValueError("原生产物身份不再属于本次事务")
                    restored = _compensate_node(state, journal, root, path, expected=published, after=before)
                _clean_stage(row)
                if native.read_node(root, path) != restored:
                    raise ValueError("补偿完成后的节点又被替换")
                row["restored"] = restored.value()
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
                active_root, active_path = state, record_path
                try:
                    _resume_compensation(state, journal, state, record_path)
                    _check_compensation_history(journal, state, record_path)
                    current_record = native.read_node(state, record_path)
                    authorized = _compensation_result(journal, state, record_path)
                    if authorized is not None and current_record != authorized:
                        raise ValueError("归属索引在重建投影前被替换")
                    if current_record.kind == "missing":
                        continue
                    record = native.parse_record(current_record, state=state, root=root, host=target["host"],
                                                 identity=native.root_identity(root))
                    for path, entry in record["files"].items():
                        current = native.read_node(root, path)
                        authorized = _compensation_result(journal, root, path)
                        if authorized is None:
                            restored_row = next((row for row in journal["writes"] if row["root"] == str(root) and row["path"] == path), None)
                            authorized = Node.from_value(restored_row["restored"]) if restored_row and restored_row.get("restored") is not None else Node.from_value(entry["expected"])
                        if current != authorized:
                            conflicts.append({"root": str(root), "path": path, "reason": "恢复后精确节点与已授权归属不一致"})
                            break
                        entry["expected"] = current.value()
                    if conflicts:
                        break
                    payload = json_bytes(record)
                    for owner_root, owner_path in ((root, native.OWNER), (state, record_path)):
                        active_root, active_path = owner_root, owner_path
                        _resume_compensation(state, journal, owner_root, owner_path)
                        _check_compensation_history(journal, owner_root, owner_path)
                        node = native.read_node(owner_root, owner_path)
                        authorized = _compensation_result(journal, owner_root, owner_path)
                        if authorized is not None and node != authorized:
                            raise ValueError("归属投影在重写前被未知替换")
                        if node.payload != payload:
                            restored = _compensate_node(state, journal, owner_root, owner_path,
                                                        expected=node, after=Node("file", payload, 0o600))
                            for row in journal["writes"]:
                                if row["root"] == str(owner_root) and row["path"] == owner_path:
                                    row["restored"] = restored.value()
                            _save(state, journal)
                except (OSError, ValueError):
                    conflicts.append({"root": str(active_root), "path": active_path,
                                      "reason": "归属投影的精确Node或补偿保留资料冲突，已保全现状"})
                    break
        if not conflicts:
            # metadata可能是在原发布中断后首次补偿产生，也必须核验它的精确
            # 结果；不能只遍历原writes，漏掉没有forward行的owner/索引恢复。
            results = {(row["root"], row["path"]): Node.from_value(row["restored"]) for row in journal["writes"]}
            for step in journal.get("compensations", []):
                if step["result"] is not None:
                    results[(step["root"], step["path"])] = Node.from_value(step["result"])
            for (root_raw, path), expected in results.items():
                try:
                    root = Path(root_raw)
                    _check_compensation_history(journal, root, path)
                    if native.read_node(root, path) != expected:
                        raise ValueError("补偿结算前节点变化")
                except (OSError, ValueError):
                    conflicts.append({"root": root_raw, "path": path, "reason": "补偿结算前精确节点或保留资料变化"})
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
    issues = []
    for root, identity in identities.items():
        if not isinstance(identity, list) or len(identity) != 2 or any(type(item) is not int for item in identity):
            raise ValueError("原生恢复根身份格式无效")
        try:
            actual = list(native.root_identity(Path(root)) or ())
        except (OSError, ValueError):
            actual = []
        if actual != identity:
            issues.append({"type": "native_root_conflict", "path": root, "reason": "宿主物理根已替换、链接化或删除"})
    return issues


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
        try:
            before = _observe(context.state, context.host_paths, host)
            record, conflicts = _ownership(context.state, before)
        except (OSError, ValueError):
            issues.append({"type": "native_noop_witness_conflict", "path": targets[host],
                           "reason": "no-op见证中的归属或宿主路径已损坏、替换或链接化"})
            continue
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
        try:
            complete = (desired["path"] in {native.role_relative(desired["host"], role) for role in role_models.ROLES}
                        and native.read_node(root, desired["path"]).same_content(Node.from_value(desired["after"])))
        except (OSError, ValueError):
            complete = False
        if not complete:
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
    # current是中央owner维护的封闭记录，偏好入口必须复用同一严格codec，
    # 同时核验私有文件权限及显式native_roots；不能复制旧字段集合后漂移，
    # 也不能忽略新增授权字段、从native归属或HOME推定一个当前版本。
    from .runtime_policy import current_snapshot
    _, current = current_snapshot(state)
    if current is None:
        raise ValueError("已安装全局原生角色缺少中央当前版本记录")
    return runtime_store.validate_binding(current["runtime_binding"])


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


def admission_issues(state: Path, *, hosts: tuple) -> list[dict]:
    """只读从当前有效中央激活定位原生根，再核验最新归属与合法模型投影。

    native_ref仅证明本generation授权的根，后续合法模型保存会改变同根产物；
    不拿旧事务的产物快照作长期expected，不扫描旧root索引或猜测HOME。
    当前真实activation_scope可验证本批已准备的native根；外部pending请求仍
    由中央gate拒绝，环境变量不能制造该调用栈授权。
    """
    state = state_files.state_root(state)
    if not isinstance(hosts, tuple) or len(set(hosts)) != len(hosts) or set(hosts) - set(role_models.HOSTS):
        raise ValueError("原生准入宿主必须是无重复的已知tuple")
    if not hosts:
        return []
    from . import runtime_policy as policy
    from .central_runtime import _validate_journal
    authority_node = None
    authority_path = policy.CURRENT
    try:
        current_node, current = policy.current_snapshot(state)
        active = policy.active_activation(state)
        if active is not None:
            # 只在真实ContextVar激活栈内读取本批过程日志。ref/receipt仍须互相
            # 精确匹配；不能通过构造current或外部环境模拟尚未发布的原生授权。
            authority_path = policy.ACTIVATION
            authority_node = native.read_node(state, policy.ACTIVATION)
            if authority_node.kind != "file" or authority_node.mode != 0o600:
                raise ValueError("当前活动激活日志缺失或权限无效")
            authority = _validate_journal(unique_json(authority_node.payload))
            if active != authority or active.get("native_receipt") is None:
                raise ValueError("当前活动激活尚未完成原生发布")
            reference = authority["native_ref"]
            keys = {"schema_version", "state", "transaction_id", "targets"}
            if (not isinstance(reference, dict) or set(reference) not in (keys, keys | {"witness"})
                    or type(reference["schema_version"]) is not int or reference["schema_version"] != 1
                    or reference["state"] != str(state) or not isinstance(reference["targets"], list)):
                raise ValueError("当前原生根引用无效")
            _journal_relative(reference["transaction_id"])
            receipt = authority["native_receipt"]
            if (not isinstance(receipt, dict) or receipt.get("recovery_ref") != reference
                    or receipt.get("transaction_id") != reference["transaction_id"]
                    or receipt.get("status") not in {"applied", "noop"}):
                raise ValueError("当前激活缺少对应原生结算收据")
            targets = policy.validate_native_roots(reference["targets"])
        else:
            # 已结算准入只消费current同一次条件发布固定的roots。失败激活会
            # 替换最后一份过程日志，不能因此丢掉旧current的有效授权；显式空
            # roots也绝不回退历史日志、root索引、HOME或任何环境变量猜测。
            if current is None:
                raise ValueError("缺少已发布的当前原生根授权")
            targets = policy.validate_native_roots(current["native_roots"])
        roots = {target["host"]: Path(target["native_root"]) for target in targets}
    except (OSError, ValueError, TypeError, KeyError, RecursionError):
        return [{"code": "native_authority_invalid", "path": authority_path,
                 "reason": "不能确认唯一当前有效的原生宿主根，已拒绝稀疏准入"}]
    try:
        preference_before, defaults = _projected_preferences(state)
    except (OSError, ValueError, TypeError):
        return [{"code": "native_preferences_invalid", "path": role_preferences.RELATIVE,
                 "reason": "全局角色偏好无效，不能核验原生模型投影"}]
    issues, observations = [], []
    for host in hosts:
        root = roots.get(host)
        if root is None:
            issues.append({"code": "native_authority_missing", "path": authority_path,
                           "reason": host + "缺少当前有效的唯一原生根授权"})
            continue
        try:
            before = _Observation(host, root, native.root_identity(root), native.read_node(root, native.OWNER),
                                  native.read_node(state, native.record_relative(root)), native.discover(root, host))
            record, conflicts = _ownership(state, before)
            observations.append(before)
            if record is None:
                conflicts.append({"path": str(root), "reason": "缺少完整七角色原生归属"})
            issues.extend({"code": "native_ownership_conflict", "path": row["path"], "reason": row["reason"]}
                          for row in conflicts)
            if not conflicts:
                for path, node, role in before.discovery:
                    if path not in record["files"]:
                        continue
                    role = Path(path).stem
                    expected = role_preferences.resolve(defaults, {}, host, role)[0]
                    if native.native_settings(node.payload, host) != expected:
                        issues.append({"code": "native_model_projection_conflict", "path": str(root / path),
                                       "reason": "原生模型字段偏离当前合法全局偏好投影"})
        except (OSError, ValueError, TypeError, KeyError):
            issues.append({"code": "native_ownership_conflict", "path": str(root),
                           "reason": "原生归属、七角色文件或物理根无效"})
    # 查询不持创建型锁；在同一组逻辑来源与精确节点前后稳定时才发布健康结论。
    try:
        if (policy.current_snapshot(state)[0] != current_node
                or authority_node is not None and native.read_node(state, policy.ACTIVATION) != authority_node
                or role_preferences.snapshot(state)[0] != preference_before):
            raise ValueError("准入来源读取期间变化")
        for before in observations:
            after = _Observation(before.host, before.root, native.root_identity(before.root),
                                 native.read_node(before.root, native.OWNER),
                                 native.read_node(state, native.record_relative(before.root)), native.discover(before.root, before.host))
            if after != before:
                raise ValueError("原生准入资源读取期间变化")
    except (OSError, ValueError):
        issues.append({"code": "native_admission_changed", "path": "native-agents",
                       "reason": "原生准入来源或精确产物在读取期间变化"})
    return issues
