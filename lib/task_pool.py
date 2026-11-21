"""PM 私有的原记录索引。登记只保存定位和身份；每次查询、准入、归档都读取原件。"""

from __future__ import annotations

from contextlib import ExitStack, contextmanager
from dataclasses import dataclass
import json
import os
from pathlib import Path
import tempfile
import unicodedata

from lib import dispatch_admission_cli as dispatch
from lib import shared_solution_records as solutions
from lib import task_graph_records as records
from lib.agent_continuation import active, validate_reference
from lib.hosts.dispatch_contract import DEFAULT_DISPATCH, DispatchPolicy, reject_unexpected_marker
from lib.hosts.handoff import project_scratch_base
from lib.platform_fs import directory_lock
from lib.safe_text import read_file
from lib.task_graph import TaskGraphError, delivery_complete
from lib.task_sources import validate_task_source


MAX_RECORDS = 128  # 与跨请求准入的单次显式记录清单上限一致。
MAX_INDEX_BYTES = 4 * 1024 * 1024  # 与安全读取器一致，写入前避免生成自己不能恢复的索引。


def _text(value, label: str, limit: int) -> str:
    if (not isinstance(value, str) or not value.strip() or len(value) > limit
            or any(unicodedata.category(ch).startswith("C") for ch in value)):
        raise TaskGraphError(f"{label} must contain 1..{limit} printable characters")
    return value


def _node(path: Path) -> list[int]:
    info = path.lstat()
    if not info.st_ino:
        raise TaskGraphError(f"directory identity is unavailable: {path}")
    return [info.st_dev, info.st_ino]


def _private(fd: int) -> None:
    info = os.fstat(fd)
    if info.st_uid != os.getuid() or info.st_mode & 0o077:
        raise TaskGraphError("task pool requires a private directory owned by the current user")


@contextmanager
def _index(root: Path, pm_id: str, *, create: bool):
    """按项目物理路径和显式 PM 身份定位，不从目录枚举会话或读取任何宿主历史。

    锁顺序固定为池目录、再到既有项目准入锁或单一原记录的发布锁；锁内只做
    本地读写和现有校验。进程退出即解除协作锁，磁盘不保存占位、容量或运行态。
    """
    validate_task_source({}, root=root)
    _text(pm_id, "pm-id", 256)
    if any(ch.isspace() for ch in pm_id):
        raise TaskGraphError("pm-id must be a stable identifier without whitespace")
    key = records.digest(pm_id.encode("utf-8"))
    base = project_scratch_base(root)
    file = base / "task-pools" / key / "index.json"
    scope = {"schema_version": 1, "project": str(root), "project_node": _node(root), "pm": key}
    with ExitStack() as stack:
        # 新项目的首次只读查询不能创建 scratch；仅在明确 register 时分配目录。
        try:
            parent = stack.enter_context(records._scratch_base_directory(base, create=create))
            _private(parent)
            container = stack.enter_context(records._scratch_directory(base.parent))
            _private(container)
            pools = stack.enter_context(records._scratch_directory("task-pools", parent=parent, create=create))
            _private(pools)
            new_slot = False
            if create:
                try:
                    os.mkdir(key, 0o700, dir_fd=pools)
                    new_slot = True
                except FileExistsError:
                    pass
            slot = stack.enter_context(records._scratch_directory(key, parent=pools))
            _private(slot)
        except FileNotFoundError:
            if create:
                raise
            yield file, {**scope, "records": {}}
            return
        # 新建槽的进程负责写入初始索引。若此刻另一进程只读探测，等待其短锁释放，
        # 避免登记因一次竞争退出并留下永久无索引的新槽；普通操作仍按既有忙错误返回。
        stack.enter_context(directory_lock(file.parent, "pm-task-pool", blocking=new_slot))
        body = read_file(file)
        if body is None:
            # 首次登记前可以是空池。已有 PM 槽突然丢失索引则无法证明旧占用已结束，
            # 拒绝悄悄建空表后只登记一个目标。完整 scratch 被系统回收仍需 PM 重新盘点。
            if not new_slot:
                raise TaskGraphError("missing task pool index in existing PM slot; restore the registered inventory")
            data = {**scope, "records": {}}
            _save(file, data)
            yield file, data
            return
        info = file.lstat()
        if info.st_uid != os.getuid() or info.st_mode & 0o077:
            raise TaskGraphError("task pool index must be private")
        data = records.decode(body)
        dispatch._object(data, set(scope) | {"records"}, "task pool index")
        if (type(data["schema_version"]) is not int or any(data[k] != v for k, v in scope.items())
                or not isinstance(data["records"], dict) or len(data["records"]) > MAX_RECORDS):
            raise TaskGraphError("task pool scope, project identity or index format changed")
        for path, entry in data["records"].items():
            if not Path(path).is_absolute() or str(Path(path)) != path or ".." in Path(path).parts:
                raise TaskGraphError("invalid task pool record locator")
            fields = {"parent_node", "kind", "request", "members", "title"}
            if isinstance(entry, dict) and "prototype_claim" in entry:
                fields.add("prototype_claim")
                dispatch._sha(entry["prototype_claim"])
            dispatch._object(entry, fields, "registered record")
            if not isinstance(entry["members"], dict) or not entry["members"]:
                raise TaskGraphError("invalid task pool member bindings")
            for member in entry["members"].values():
                dispatch._object(member, {"request", "role", "alias", "module", "type", "level", "root", "node"},
                                 "registered task identity")
                if not isinstance(member["request"], str):
                    raise TaskGraphError("invalid task pool request identity")
            if entry["title"] is not None:
                _text(entry["title"], "title", 120)
        yield file, data


def _save(file: Path, data: dict) -> None:
    """持池目录协作锁原子替换完整定位表。异常只移除本次创建的私有临时文件。"""
    body = json.dumps(data, sort_keys=True, ensure_ascii=False).encode("utf-8")
    if len(body) > MAX_INDEX_BYTES:
        raise TaskGraphError("task pool index exceeds its safe read limit; archive terminal records first")
    fd, name = tempfile.mkstemp(dir=file.parent, prefix=".index-")
    try:
        with os.fdopen(fd, "wb") as out:
            out.write(body)
            out.flush()
            os.fsync(out.fileno())
        os.replace(name, file)
    finally:
        Path(name).unlink(missing_ok=True)


@dataclass
class Snapshot:
    binding: dict
    descriptor: dict
    tasks: list[dict]
    approved_gates: set[str]
    external_occupancy: bool
    size: int


@dataclass(frozen=True)
class RegisteredTask:
    """一次只读查询从已核对原件提取的任务及其登记执行根。"""

    record: str
    execution_root: Path
    task: dict


def _snapshot(root: Path, path: str, expected: str | None = None) -> Snapshot:
    """从原件提取本次查询用快照。正规 CAS 会替换文件 inode，不能把它当稳定业务 ID。

    绑定原记录所在目录节点、图/包与请求、原任务成员身份及物理执行根。状态、合同正文、
    证据等只属于本次快照；即便有旧标题可显示，也不能用索引补齐缺失记录的执行事实。
    """
    file = dispatch._absolute(path)
    body = records.read_record(file)
    sha = records.digest(body)
    if expected is not None and sha != dispatch._sha(expected):
        raise TaskGraphError("record fingerprint changed; inspect the current task before issuing another command")
    payload = records.decode(body)
    tasks = dispatch.authoritative_tasks(payload)
    if not tasks:
        raise TaskGraphError("execution pool requires a record with executable tasks")
    # 原 ready 包含完整结构校验，并额外校验图容量和活动资源字段。不能以准入
    # 为跨记录分配临时替换的 capacity 掩盖损坏原图；当前候选仍只由原准入决定。
    dispatch._query(payload, root, "ready")
    members, roots = {}, {}
    for task in tasks:
        execution = dispatch.execution_root(payload, task, root)
        roots[task["id"]] = str(execution)
        members[task["id"]] = {
            "request": task["request_id"], "role": task["role"], "alias": task["agent_alias"],
            "module": task["module"], "type": task["task_type"], "level": task["workflow_level"],
            "root": str(execution), "node": _node(execution),
        }
    binding = {"parent_node": _node(file.parent), "kind": "light" if "task" in payload else "graph",
               "request": payload.get("request_id"), "members": members}
    return Snapshot(binding, {"path": path, "sha256": sha, "execution_roots": roots}, tasks,
                    set(payload.get("approved_gates", [])),
                    bool(payload.get("active_paths") or payload.get("active_semantic_locks")), len(body))


def _check_binding(entry: dict, snap: Snapshot, *, extend: bool = False) -> None:
    if any(entry[field] != snap.binding[field] for field in ("parent_node", "kind", "request")):
        raise TaskGraphError("registered record identity changed; restore the original record")
    old, current = entry["members"], snap.binding["members"]
    if any(current.get(key) != member for key, member in old.items()):
        raise TaskGraphError("registered task identity or execution root changed; restore the original binding")
    if not extend and old.keys() != current.keys():
        raise TaskGraphError("new task members require explicit register with the reviewed record SHA")


def _require_entry(entries: dict, path: str) -> dict:
    if path not in entries:
        raise TaskGraphError("record is not registered in this project and PM pool")
    return entries[path]


def register(root: Path, pm_id: str, path: str, expected: str, title: str | None, *,
             dispatch_target: dict | None = None, policy: DispatchPolicy = DEFAULT_DISPATCH) -> dict:
    if dispatch_target:
        policy.check_pool_claim()
    if title is not None:
        _text(title, "title", 120)
    path = str(dispatch._absolute(path))
    snap = _snapshot(root, path, expected)
    if dispatch_target is not None:
        # 快捷派发只为已取得所需批准的实际目标登记。登记已有记录以供恢复的
        # 入口仍允许待决状态；此处只验证任务归属及本记录批准，准入归完整池负责。
        task = next((item for item in snap.tasks if (item["id"], item["request_id"])
                     == (dispatch_target["task_id"], dispatch_target["request_id"])), None)
        if task is None:
            raise TaskGraphError("dispatch target is not in the selected record")
        # Light 单包可以只提供方案正文。其方案门由原校验器算出，原 JSON 中
        # 未手写门名时也必须核实对应批准，不能先把待决设计登记成可派发委托。
        required = set(task.get("gates", [])) | set(solutions.decision_keys(task).values())
        if required - snap.approved_gates:
            raise TaskGraphError("dispatch target requires current approvals before registration")
    with _index(root, pm_id, create=True) as (file, data):
        entries = data["records"]
        if path in entries:
            _check_binding(entries[path], snap, extend=True)
        else:
            if len(entries) >= MAX_RECORDS:
                raise TaskGraphError("task pool reached its record limit; archive terminal records first")
            for name in entries:
                try:
                    if Path(path).samefile(name):
                        raise TaskGraphError("this physical record is already registered under another name")
                except FileNotFoundError:
                    continue
        entry = {**entries.get(path, {}), **snap.binding,
                 "title": title if title is not None else entries.get(path, {}).get("title")}
        # 登记 CAS 与原件发布共用其父目录锁；旧观察在拿锁之前失效时，不发布登记。
        with records._publication_lock(Path(path)):
            if records.digest(records.read_record(Path(path))) != expected:
                raise TaskGraphError("record fingerprint changed during registration")
            if entries.get(path) != entry:
                entries[path] = entry
                _save(file, data)
        return {"status": "registered", "record": path, "sha256": expected, "task_count": len(snap.tasks)}


def _terminal(task: dict) -> bool:
    # FAILED 是失败事实；仍有活跃工作/待停请求时绝不能解除登记。旧 Writer 的 QA
    # 是已移交，显式 QA 的 QA 却仍在审查，二者沿用原图 active 判定。
    return (not active(task) and (task["state"] in {"FAILED", "WITHDRAWN"}
            or delivery_complete(task["task_type"], task["state"])
            or task["task_type"] == "writer" and task["state"] == "QA"))


def _archive_peers(root: Path, entries: dict, target: Snapshot) -> list[Snapshot]:
    """终态副本可能仍是别的待派 Writer 的方案依据。只检查同请求显式登记的原件。

    比对当前正文所属的决定，也检查已有成员关系：目标可能已合法移除自己的决定，
    但另一个任务仍需在领取时提供该原件。全部相关成员终结后，仍可逐份解除索引。
    """
    path = Path(target.descriptor["path"])
    requests = {task["request_id"] for task in target.tasks}
    keys = {key for task in target.tasks for key in solutions.decision_keys(task)}
    peers = []
    for name, entry in entries.items():
        if name == str(path) or not any(member["request"] in requests for member in entry["members"].values()):
            continue
        snap = _snapshot(root, name)
        _check_binding(entry, snap)
        peers.append(snap)
        for task in snap.tasks:
            if _terminal(task):
                continue
            for key in solutions.decision_keys(task):
                if key in keys or any(path.samefile(member) for member in solutions.members(Path(name), key)):
                    raise TaskGraphError("another unfinished task still requires this shared solution record")
    return peers


def archive(root: Path, pm_id: str, path: str, expected: str) -> dict:
    with _index(root, pm_id, create=False) as (file, data):
        entry = _require_entry(data["records"], path)
        snap = _snapshot(root, path, expected)
        _check_binding(entry, snap)
        if snap.external_occupancy or not all(_terminal(task) for task in snap.tasks):
            raise TaskGraphError("only a wholly terminal record without resource occupancy can be archived")
        # 归档只删除本条索引，不改原图、不删工作成果。紧贴发布时重核 SHA，
        # 避免在终态判断之后、有新修订写入时把仍需跟踪的记录丢掉。
        checked = [snap, *_archive_peers(root, data["records"], snap)]
        with solutions._locked_directories({Path(item.descriptor["path"]).parent for item in checked}):
            for item in checked:
                original = Path(item.descriptor["path"])
                if records.digest(records.read_record(original)) != item.descriptor["sha256"]:
                    raise TaskGraphError("record fingerprint changed during archive")
            del data["records"][path]
            _save(file, data)
        return {"status": "archived", "record": path, "sha256": expected, "task_count": len(snap.tasks)}


def _read_pool(root: Path, entries: dict, *, selected: str | None = None) -> tuple[list[Snapshot], list[dict]]:
    snapshots, errors = [], []
    total = 0
    for path, entry in entries.items():
        if selected is not None and selected != path:
            continue
        try:
            snap = _snapshot(root, path)
            _check_binding(entry, snap)
            total += snap.size
            if total > 16 * 1024 * 1024:
                raise TaskGraphError("aggregate record bodies exceed 16MiB")
            snapshots.append(snap)
        except (ValueError, OSError) as exc:
            # 查询保留其它可读项以及坏记录的原定位。未知资源占用不能算空闲，
            # 领取入口会检查完整 errors，绝不按仅成功读取的子集申请原生资源。
            errors.append({"record": path, "title": entry["title"], "error": str(exc)})
    return snapshots, errors


def registered_tasks(root: Path, pm_id: str) -> tuple[RegisteredTask, ...]:
    """按物理项目和 PM 身份读取可用于授权的原件快照，不分配任务池目录。

    尚无登记时返回空结果。已有 PM 槽缺索引或任一原件无效时直接失败，
    避免将未知占用视为空闲。返回对象只包含本次读取的任务数据，锁在返回前释放。
    """
    with _index(root, pm_id, create=False) as (_, data):
        snapshots, errors = _read_pool(root, data["records"])
        if errors:
            raise TaskGraphError("已登记任务原件需要核对")
        return tuple(
            RegisteredTask(snap.descriptor["path"], Path(snap.descriptor["execution_roots"][task["id"]]), task)
            for snap in snapshots for task in snap.tasks
        )


def _manifest(root, snapshots, capacity):
    return {"schema_version": 1, "project_root": str(root),
            "records": [snap.descriptor for snap in snapshots], "capacity": capacity}


def check_handoff(root: Path, pm_id: str, original: Path, expected: str) -> None:
    """将本次导出的真实原件与池内冻结的领取版本对应；同字节复制品也不能借用回执。"""
    path = str(dispatch._absolute(str(original.absolute())))
    root = dispatch._project_directory(str(root))
    with _index(root, pm_id, create=False) as (_, data):
        entry = _require_entry(data["records"], path)
        snap = _snapshot(root, path, expected)
        _check_binding(entry, snap)
        if not entry.get("prototype_claim") or entry["prototype_claim"] != snap.tasks[0].get("claim_basis_sha256"):
            raise TaskGraphError("prototype requires its recorded admission in this PM task pool")


def bind(root: Path, pm_id: str, receipt: dict, reference: dict, *,
         policy: DispatchPolicy = DEFAULT_DISPATCH) -> dict:
    """拿到真实宿主回执后把 ID 写回原件，允许同图无关更新及在途撤回。

    池锁串行化同一 PM 的两个绑定，先检索已登记原件中的历史身份，再走原 update
    的 CAS 和首次绑定校验。丢失回包时重试同一绑定保持幂等，不触发宿主创建。
    """
    target = dispatch.claim_target(receipt)
    validate_reference(reference)
    path = str(dispatch._absolute(target["record"]))
    with _index(root, pm_id, create=False) as (_, data):
        _require_entry(data["records"], path)
        snapshots, errors = _read_pool(root, data["records"])
        if errors:
            raise TaskGraphError(f"binding requires every registered original: {errors}")
        selected = None
        for snap in snapshots:
            for task in snap.tasks:
                if (snap.descriptor["path"] == path and task["request_id"] == target["request_id"]
                        and task["id"] == target["task_id"]):
                    selected = task, snap.descriptor["sha256"]
                elif task.get("agent_ref") == reference:
                    raise TaskGraphError("native ID is already bound to another registered task")
        if selected is None:
            raise TaskGraphError("claim target does not identify a registered task")
        task, sha = selected
        reject_unexpected_marker(task, receipt)
        if (task.get("claim_basis_sha256") != receipt["previous_sha256"]
                or task.get("claim_prior_state") != receipt["prior_state"]):
            raise TaskGraphError("binding requires the current task's original claim receipt")
        body = records.read_record(Path(path))
        if records.digest(body) != sha:
            raise TaskGraphError("record changed before binding; inspect the existing native result")
        payload = records.decode(body)
        from lib.task_graph_cli import is_standalone_prototype, publish_task_update
        # 重试已绑定结果也须确认本池的同一领取，禁止未经准入的外来副本借幂等
        # 返回一条成功绑定的假回执。查询池时仍可如实看到外来原件已有的状态。
        if is_standalone_prototype(payload) and data["records"][path].get("prototype_claim") != receipt["previous_sha256"]:
            raise TaskGraphError("binding requires the prototype claim recorded by this PM pool")
        policy.check_binding(root, target, task, receipt, reference,
                             lambda: dispatch.execution_root(payload, task, root))
        if task.get("agent_ref") != reference:
            patch = {"tasks": {task["id"]: {"set": {"agent_ref": reference}}}}
            updated = publish_task_update(Path(path), root, payload, body, sha, patch, pool_operation=True)
            sha = dispatch._sha(updated["sha256"])
        return {"status": "bound", "target": target, "agent_ref": reference, "sha256": sha}


def view(root: Path, pm_id: str, *, path: str | None, query: str | None, capacity: dict | None) -> dict:
    with _index(root, pm_id, create=False) as (_, data):
        entries = data["records"]
        if path:
            _require_entry(entries, path)
        # 带容量时即使筛了单条也对完整池计算。筛选只影响返回的任务行，不能从
        # 资源占用中漏掉另一个原图或同一请求的其他成员。
        snapshots, errors = _read_pool(root, entries, selected=path if capacity is None else None)
        words = query.casefold().split() if query else []
        rows = []
        for snap in snapshots:
            location = snap.descriptor["path"]
            if path and location != path:
                continue
            title = entries[location]["title"]
            for task in snap.tasks:
                fields = [title or "", task.get("goal", ""), task["request_id"], task["id"], task["agent_alias"]]
                if not all(word in " ".join(fields).casefold() for word in words):
                    continue
                row = {"record": location, "request_id": task["request_id"], "task_id": task["id"],
                       "title": title, "goal": task.get("goal"), "agent_alias": task["agent_alias"],
                       "sha256": snap.descriptor["sha256"], "state": task["state"], "active": active(task)}
                row.update({k: task[k] for k in ("agent_ref", "task_revision", "agent_retired") if k in task})
                if "task_revision" in task:
                    # 自然语言进度应区分“已登记修改”和“原实例已确认新版本”。
                    # 仅返回本次校验过的原件事实，索引不保存送达正文或回报副本。
                    row["revision_acknowledged"] = "revision_ack" in task
                    row["revision_result_recorded"] = "revision_result" in task
                rows.append(row)
        result = {"schema_version": 1, "tasks": rows, "errors": errors, "registered_records": len(entries)}
        if capacity is not None:
            if errors:
                result["admission"] = None
            elif snapshots:
                result["admission"] = dispatch.admission("view", _manifest(root, snapshots, capacity))
            else:
                result["admission"] = dispatch.select_candidates((), capacity)
        return result


def operate(root: Path, pm_id: str, command: str, capacity: dict, *, target: dict | None = None,
            expected: str | None = None, receipt: dict | None = None, outcome: str | None = None,
            policy: DispatchPolicy = DEFAULT_DISPATCH) -> dict:
    if command == "claim":
        policy.check_pool_claim()
    with _index(root, pm_id, create=False) as (file, data):
        entries = data["records"]
        if not entries:
            raise TaskGraphError("no registered records in this project and PM pool")
        if target:
            _require_entry(entries, target["record"])
        snapshots, errors = _read_pool(root, entries)
        if errors:
            raise TaskGraphError(f"pool admission requires every registered original: {errors}")
        if target:
            actual = next(snap.descriptor["sha256"] for snap in snapshots if snap.descriptor["path"] == target["record"])
            if dispatch._sha(expected) != actual:
                raise TaskGraphError("target fingerprint changed; review the new record before another claim")
        # 池锁阻止并发登记/归档改变清单，准入锁内再次加载每项刚读到的 SHA，
        # 并用原 update CAS 发布唯一目标。未知或冲突不自动刷新用户指令后重试。
        def freeze_prototype(path, previous_sha):
            # 在全池仲裁通过后、原件 CAS 之前冻结领取基线。先存定位依据，后发
            # RUNNING：中途失败的原件仍待派，单有这条摘要不能导出、绑定或释放名额。
            # 一旦原件已发布，恢复时则能同时核对同一 PM、同一路径与相同基线。
            entries[path]["prototype_claim"] = previous_sha
            _save(file, data)

        return dispatch.admission(command, _manifest(root, snapshots, capacity), target, receipt, outcome,
                                  freeze_prototype=freeze_prototype, policy=policy)
