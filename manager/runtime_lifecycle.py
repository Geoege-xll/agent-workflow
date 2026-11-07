"""备份与不可变核心的统一、保守、可恢复生命周期服务。

preview 只读；原 binding/journal 是历史事实，清理不删改它们。删除授权来自
已验证归属记录及精确前像，最新完整 applied 批次与 pending 依赖始终保留。
GC 的未知引用会保活全部候选，不把“没有发现”当成“确认无人使用”。
"""

from __future__ import annotations

from contextlib import ExitStack
from dataclasses import dataclass
import hashlib
from pathlib import Path
import re
import stat
import uuid

from lib import runtime_store as store
from lib.central.runtime_project import Node, Tree, absolute_directory, identity, json_bytes, node_id, read_at, relative_path, unique_json
from lib.platform_fs import directory_lock, os
from . import runtime_policy as policy
from .runtime_state import ActivationError, read_binding_record, read_journal, read_state, retained_conflicts, write_control

RELATIVE = "central/lifecycle.json"
_DIGEST = re.compile(r"[0-9a-f]{64}\Z")


def _revision(node: Node) -> dict:
    return {"kind": node.kind, "sha256": hashlib.sha256(node.payload).hexdigest(),
            "mode": node.mode, "identity": list(node.identity)}


def _read_lifecycle(state: Path) -> tuple[Node, dict | None]:
    node = read_state(state, RELATIVE)
    if node.kind == "missing":
        return node, None
    if node.kind != "file" or node.mode != 0o600:
        raise ActivationError("生命周期记录必须是私有普通文件")
    value = unique_json(node.payload)
    if (not isinstance(value, dict) or set(value) != {"schema_version", "id", "phase", "observed", "backups", "archives", "cores", "released", "conflicts"}
            or type(value["schema_version"]) is not int or value["schema_version"] != 1
            or not isinstance(value["phase"], str) or value["phase"] not in {"prepared", "applied", "conflict"}
            or not isinstance(value["id"], str) or not re.fullmatch(r"[0-9a-f]{32}", value["id"])
            or any(not isinstance(value[key], list) for key in ("observed", "backups", "archives", "cores", "released", "conflicts"))):
        raise ActivationError("生命周期记录结构无效")
    _validate_entries(value)
    return node, value


def status(state: Path) -> dict:
    """只读公开清理结算状态；不创建目录，也不返回恢复前像或删除快照。

    pending表示管理写入仍需等待结算，can_recover只表示原恢复入口适用，
    不承诺未知手改已能安全覆盖。计数以计划项为单位；部分删除的目录仍未
    算作完成，避免把中断时已删若干叶文件误报为整个批次成功。
    """
    state = store.state_root(state)
    _, record = _read_lifecycle(state)
    phase = record["phase"] if record else "none"
    pending = phase in {"prepared", "conflict"}
    conflicts = []
    for row in record["conflicts"] if record else []:
        if (not isinstance(row, dict) or not isinstance(row.get("path"), str)
                or not isinstance(row.get("reason"), str)
                or not isinstance(row.get("code", "lifecycle_conflict"), str)):
            raise ActivationError("生命周期冲突诊断结构无效")
        # 兼容早期只有path/reason的诊断；明确投影三个公开字段，即使私有
        # 旧日志另带恢复内容，也不能通过CLI/TUI状态查询泄露其raw前像。
        conflicts.append({"code": row.get("code", "lifecycle_conflict"),
                          "path": row["path"], "reason": row["reason"]})
    counts = {}
    for kind in ("backups", "archives", "cores"):
        rows = record[kind] if record else []
        counts[kind + "_total"] = len(rows)
        counts[kind + "_done"] = sum(row["phase"] == "done" for row in rows)
    return {"schema_version": 1, "state_dir": str(state),
            "transaction_id": record["id"] if record else None, "phase": phase,
            "pending": pending, "can_recover": pending, "conflicts": conflicts, "counts": counts}


def _validate_snapshot(snapshot: dict) -> None:
    if (not isinstance(snapshot, dict) or "" not in snapshot or not isinstance(snapshot[""], dict)
            or not snapshot[""].get("directory")):
        raise ActivationError("生命周期目录快照无效")
    for path, row in snapshot.items():
        if not isinstance(path, str) or path and relative_path(path) != path or not isinstance(row, dict):
            raise ActivationError("生命周期快照路径无效")
        directory = row.get("directory") is True
        if set(row) != ({"inode", "mode", "directory"} if directory else {"inode", "mode", "sha256", "size"}):
            raise ActivationError("生命周期快照节点结构无效")
        if (not isinstance(row["inode"], list) or len(row["inode"]) != 2
                or any(type(item) is not int or item < 0 for item in row["inode"])
                or type(row["mode"]) is not int or not 0 <= row["mode"] <= 0o7777):
            raise ActivationError("生命周期快照身份无效")
        if not directory and (not isinstance(row["sha256"], str) or not _DIGEST.fullmatch(row["sha256"])
                              or type(row["size"]) is not int or not 0 <= row["size"] <= 128 * 1024 * 1024):
            raise ActivationError("生命周期文件快照无效")
        parent = path.rpartition("/")[0]
        if path and (parent not in snapshot or not snapshot[parent].get("directory")):
            raise ActivationError("生命周期快照缺少父目录")


def _validate_entries(value: dict) -> None:
    from .runtime_state import validate_retained
    for row in value["backups"]:
        if (not isinstance(row, dict) or set(row) != {"project", "record", "phase"}
                or not isinstance(row["project"], str) or not Path(row["project"]).is_absolute()
                or row["phase"] not in ("pending", "done")):
            raise ActivationError("生命周期备份恢复项无效")
        validate_retained([row["record"]])
    for row in value["archives"]:
        if (not isinstance(row, dict) or set(row) != {"root", "snapshot", "phase"}
                or not isinstance(row["root"], str) or row["phase"] not in ("pending", "deleting", "done")):
            raise ActivationError("生命周期显式归档项无效")
        _approved_archive(Path(row["root"]))
        _validate_snapshot(row["snapshot"])
    for row in value["cores"]:
        if (not isinstance(row, dict) or set(row) != {"content_id", "snapshot", "phase"}
                or not isinstance(row["content_id"], str) or not _DIGEST.fullmatch(row["content_id"])
                or row["phase"] not in ("pending", "deleting", "done")):
            raise ActivationError("生命周期核心恢复项无效")
        _validate_snapshot(row["snapshot"])
    for row in value["released"]:
        if not isinstance(row, dict) or set(row) != {"project", "record"} or not isinstance(row["project"], str):
            raise ActivationError("生命周期完成删除收据无效")
        validate_retained([row["record"]])
    for row in value["observed"]:
        if (not isinstance(row, dict) or set(row) not in ({"root", "path", "revision"}, {"root", "path", "directory"})
                or not isinstance(row["root"], str) or not Path(row["root"]).is_absolute()):
            raise ActivationError("生命周期引用前像无效")
        relative_path(row["path"])
        if "directory" in row:
            names = row["directory"]
            if names is not None and (not isinstance(names, list) or any(not isinstance(name, str) or "/" in name for name in names)):
                raise ActivationError("生命周期引用目录清单无效")
        else:
            revision = row["revision"]
            if (not isinstance(revision, dict) or set(revision) != {"kind", "sha256", "mode", "identity"}
                    or revision["kind"] not in ("file", "missing") or not isinstance(revision["sha256"], str)
                    or not _DIGEST.fullmatch(revision["sha256"]) or type(revision["mode"]) is not int
                    or not isinstance(revision["identity"], list) or any(type(item) is not int for item in revision["identity"])):
                raise ActivationError("生命周期引用记录身份无效")


def retired_history(state: Path, project: Path) -> dict[str, dict]:
    """仅缺失且已有完成删除收据的路径免报损坏；同名新节点仍照常核验。"""
    _, value = _read_lifecycle(state)
    if value is None:
        return {}
    result = {}
    for row in value["released"]:
        if not isinstance(row, dict) or set(row) != {"project", "record"}:
            raise ActivationError("生命周期删除收据无效")
        if row["project"] == str(project):
            from .runtime_state import validate_retained
            validate_retained([row["record"]])
            result[row["record"]["path"]] = row["record"]
    return result


def _walk_references(value, result: set[str]) -> None:
    if isinstance(value, list):
        for item in value:
            _walk_references(item, result)
    elif isinstance(value, dict):
        if set(value) == {"protocol_version", "content_id", "manifest_sha256"}:
            result.add(store.validate_binding(value)["content_id"])
            return
        for key, item in value.items():
            if key in {"runtime_binding", "previous_binding"} and item is not None:
                result.add(store.validate_binding(item)["content_id"])
            elif key == "used_bindings":
                if not isinstance(item, list):
                    raise ActivationError("核心引用历史无效")
                for binding in item:
                    result.add(store.validate_binding(binding)["content_id"])
            elif key in {"binding_before", "current_before", "policy_before", "journal_before"}:
                embedded = Node.from_value(item)
                if embedded.kind == "file":
                    _walk_references(unique_json(embedded.payload), result)
            else:
                _walk_references(item, result)


def _references(state: Path, task_records: tuple[Path, ...] = ()) -> tuple[set[str], list[dict], list[dict]]:
    """读取明确的私有记录根与显式 task records，不扫描业务代码/会话目录。"""
    referenced, observed, issues = set(), [], []
    try:
        with Tree(state) as tree:
            for directory in ("bindings", "transactions", "policies", "central"):
                try:
                    descriptor = tree.directory(directory)
                except FileNotFoundError:
                    observed.append({"root": str(state), "path": directory, "directory": None})
                    continue
                names = sorted(os.listdir(descriptor))
                relevant = [name for name in names if not (directory == "central" and name == "lifecycle.json")]
                observed.append({"root": str(state), "path": directory, "directory": relevant})
                for name in relevant:
                    relative = directory + "/" + name
                    if not name.endswith(".json"):
                        issues.append({"path": relative, "code": "unknown_reference", "reason": "未知私有记录或发布见证，保留全部核心"})
                        continue
                    node = read_state(state, relative)
                    observed.append({"root": str(state), "path": relative, "revision": _revision(node)})
                    if node.kind != "file" or node.mode != 0o600:
                        raise ActivationError("核心引用记录不是私有普通文件")
                    value = unique_json(node.payload)
                    if not isinstance(value, dict) or type(value.get("schema_version")) is not int or value["schema_version"] != 1:
                        raise ActivationError("未知核心引用schema")
                    if directory == "bindings":
                        if read_binding_record(state, Path(value["project_root"]))[0] != node:
                            raise ActivationError("binding引用前像变化")
                    elif directory == "transactions":
                        if read_journal(state, Path(value["project_root"]))[0] != node:
                            raise ActivationError("journal引用前像变化")
                    elif directory == "policies":
                        policy.validate_policy(value, Path(value["project_root"]))
                    elif relative == policy.CURRENT:
                        policy.validate_current(value)
                    elif relative == policy.ACTIVATION:
                        from .central_runtime import _validate_journal
                        _validate_journal(value)
                    else:
                        raise ActivationError("未知中央引用记录")
                    _walk_references(value, referenced)
    except FileNotFoundError:
        pass
    except (OSError, ValueError, TypeError, KeyError) as exc:
        issues.append({"path": "state", "code": "unknown_reference", "reason": "私有核心引用无法完整验证，保留全部核心"})
    for path in task_records:
        try:
            absolute = Path(path).absolute()
            with Tree(absolute.parent) as tree:
                node = tree.read(absolute.name)
            if node.kind != "file":
                raise ActivationError("显式任务记录缺失")
            _walk_references(unique_json(node.payload), referenced)
            observed.append({"root": str(absolute.parent), "path": absolute.name, "revision": _revision(node)})
        except (OSError, ValueError, TypeError, KeyError):
            issues.append({"path": str(path), "code": "unknown_reference", "reason": "显式任务 pin 无法验证，保留全部核心"})
    try:
        from . import native_agents
        for binding in native_agents.referenced_bindings(state):
            referenced.add(store.validate_binding(binding)["content_id"])
    except ImportError:
        # 尚未存在任何 native 记录的内部开发基线可独立验证生命周期；若有真实
        # native 根而消费者缺失，必须保守保活，不能把导入失败当成没有引用。
        if (state / "native-agents").exists():
            issues.append({"path": "native-agents", "code": "unknown_reference", "reason": "原生引用消费者不可用"})
    except (OSError, ValueError):
        issues.append({"path": "native-agents", "code": "unknown_reference", "reason": "原生引用记录无法验证"})
    return referenced, observed, issues


def _check_observed(observed: list[dict]) -> None:
    for row in observed:
        with Tree(Path(row["root"])) as tree:
            if "revision" in row:
                if _revision(tree.read(row["path"])) != row["revision"]:
                    raise ActivationError("生命周期预览后的引用记录发生变化：" + row["path"])
            else:
                try:
                    names = sorted(os.listdir(tree.directory(row["path"])))
                    if row["path"] == "central":
                        names = [name for name in names if name != "lifecycle.json"]
                except FileNotFoundError:
                    names = None
                if names != row["directory"] and not (row["path"] == "central" and row["directory"] is None and names == []):
                    raise ActivationError("生命周期预览后的引用集合发生变化：" + row["path"])


def _file_metadata(parent: int, name: str) -> dict:
    descriptor = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1 or before.st_size > 128 * 1024 * 1024:
            raise ActivationError("核心回收遇到未知非独占普通文件")
        digest = hashlib.sha256()
        while chunk := os.read(descriptor, 1024 * 1024):
            digest.update(chunk)
        if identity(os.fstat(descriptor)) != identity(before):
            raise ActivationError("核心回收快照读取期间变化")
        return {"inode": list(node_id(before)), "mode": stat.S_IMODE(before.st_mode),
                "sha256": digest.hexdigest(), "size": before.st_size}
    finally:
        os.close(descriptor)


def _core_snapshot(root: Path) -> dict:
    result = {}
    with absolute_directory(root) as descriptor:
        def walk(parent: int, prefix: str):
            info = os.fstat(parent)
            result[prefix] = {"inode": list(node_id(info)), "mode": stat.S_IMODE(info.st_mode), "directory": True}
            for name in sorted(os.listdir(parent)):
                relative = prefix + "/" + name if prefix else name
                info = os.stat(name, dir_fd=parent, follow_symlinks=False)
                if stat.S_ISDIR(info.st_mode):
                    child = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent)
                    try:
                        walk(child, relative)
                    finally:
                        os.close(child)
                else:
                    result[relative] = _file_metadata(parent, name)
        walk(descriptor, "")
    return result


@dataclass(frozen=True)
class LifecyclePlan:
    state: Path
    before: Node
    observed: tuple[dict, ...]
    backups: tuple[dict, ...]
    archives: tuple[dict, ...]
    cores: tuple[dict, ...]
    retained: tuple[dict, ...]
    released: tuple[dict, ...]

    @property
    def summary(self) -> dict:
        return {"schema_version": 1, "action": "prune", "backups": [{"project": row["project"], "path": row["record"]["path"]} for row in self.backups],
                "cores": [row["content_id"] for row in self.cores], "retained": list(self.retained),
                "approved_archives": [row["root"] for row in self.archives],
                "can_apply": True, "changes": len(self.backups) + len(self.archives) + len(self.cores)}


def preview(state: Path, *, task_records: tuple[Path, ...] = (), backup_roots: tuple[Path, ...] = (),
            approved_backup_roots: tuple[Path, ...] = (), include_cores: bool = True) -> LifecyclePlan:
    """生成统一清理计划；未知旧归档只 inventory，不把同名路径当归属证据。"""
    state = store.state_root(state)
    policy.ensure_settled(state)
    before, lifecycle = _read_lifecycle(state)
    if lifecycle and lifecycle["phase"] in {"prepared", "conflict"}:
        raise ActivationError("生命周期事务尚未结算，请先恢复")
    referenced, observed, retained = _references(state, tuple(task_records))
    backups, archives, cores = [], [], []
    try:
        with Tree(state) as machine:
            try:
                names = sorted(os.listdir(machine.directory("bindings")))
            except FileNotFoundError:
                names = []
            for name in names:
                if not re.fullmatch(r"[0-9a-f]{64}\.json", name):
                    continue
                raw = unique_json(machine.read("bindings/" + name).payload)
                project = Path(raw["project_root"])
                _, record = read_binding_record(state, project)
                _, journal = read_journal(state, project)
                protected = set()
                # 一次失败事务会把当前journal结算为rolled_back，不能因此丢掉
                # 上一个完整applied批次。binding.retained由成功事务按生成顺序
                # 追加；补偿产物只用.rollback，因此最后一个.previous批次是
                # 仍需保留的最近成功物理备份。nonce只用于分组，不用于推断时间。
                latest_batch = next((match[1] for row in reversed(record["retained_nodes"])
                                     if (match := re.search(r"\.agent-workflow-central-([0-9a-f]{32})-[0-9]+\.previous\Z", row["path"]))), None)
                if latest_batch:
                    protected.update(row["path"] for row in record["retained_nodes"]
                                     if f".agent-workflow-central-{latest_batch}-" in row["path"])
                # 旧中央核心的新任务入口仍可能检查全部历史 retained。按当前
                # 实际版及有效策略版保留其物理依赖，不能仅因为新reader会忽略
                # 已回收历史就破坏合法锁版旧核心的新任务能力。普通旧pin读取不
                # 依赖这些备份，used_bindings另在核心GC中全部保活。
                legacy_history = False
                from lib.runtime_bridge import _admission_protocol
                relevant_bindings = [record["runtime_binding"], policy.effective_binding(state, project, fallback=record["runtime_binding"])]
                for binding in relevant_bindings:
                    try:
                        if binding is not None and _admission_protocol(store.load_core(binding, state)) == 0:
                            legacy_history = True
                    except (OSError, ValueError):
                        legacy_history = True
                if legacy_history:
                    protected.update(row["path"] for row in record["retained_nodes"] + (journal.get("retained_nodes", []) if journal else []))
                if journal:
                    # 最新完整 applied 批次保留原 backup inode；未结算事务额外保留
                    # stage/rollback及全部retained，避免删掉条件补偿唯一恢复材料。
                    for row in journal["changes"]:
                        protected.add(row["backup"])
                        if journal["phase"] in {"prepared", "conflict"}:
                            protected.update((row["stage"], row["rollback"]))
                    if journal["phase"] in {"prepared", "conflict"}:
                        protected.update(row["path"] for row in journal.get("retained_nodes", []))
                with Tree(project) as tree:
                    records = {row["path"]: row for row in record["retained_nodes"] + (journal.get("retained_nodes", []) if journal else [])}
                    for relative, row in records.items():
                        if relative in protected:
                            retained.append({"path": str(project / relative), "code": "latest_or_pending", "reason": "最新完整批次或未结算恢复依赖"})
                            continue
                        conflicts = retained_conflicts(tree, [row], typed=True)
                        if conflicts:
                            retained.extend(conflicts)
                            continue
                        backups.append({"project": str(project), "record": row, "phase": "pending"})
    except FileNotFoundError:
        pass
    except (OSError, ValueError, TypeError, KeyError):
        # 归属信息不完整时清理不能继续使用已经收集的部分候选。
        backups = []
        retained.append({"path": "bindings", "code": "unknown_ownership", "reason": "备份归属无法完整验证"})
    for root in backup_roots:
        absolute = Path(root).absolute()
        try:
            snapshot = _core_snapshot(absolute)
            retained.append({"path": str(absolute), "code": "unknown_ownership", "reason": "精确旧归档已盘点，但缺少可验证受管清单，保留原字节",
                             "entries": len(snapshot) - 1})
        except (OSError, ValueError):
            retained.append({"path": str(absolute), "code": "unknown_ownership", "reason": "旧归档无法安全盘点，保留"})
    for root in approved_backup_roots:
        absolute = _approved_archive(Path(root))
        archives.append({"root": str(absolute), "snapshot": _core_snapshot(absolute), "phase": "pending"})
    if include_cores:
        try:
            with absolute_directory(state / "runtimes") as directory:
                for name in sorted(os.listdir(directory)):
                    if not _DIGEST.fullmatch(name):
                        retained.append({"path": "runtimes/" + name, "code": "unknown_core", "reason": "未知或导入暂存条目保留"})
                        continue
                    if name in referenced or any(row["code"] == "unknown_reference" for row in retained):
                        retained.append({"path": "runtimes/" + name, "code": "referenced_core", "reason": "有效或未知引用保活"})
                        continue
                    try:
                        binding = {"protocol_version": 1, "content_id": name, "manifest_sha256": name}
                        store.load_core(binding, state)
                        cores.append({"content_id": name, "snapshot": _core_snapshot(state / "runtimes" / name), "phase": "pending"})
                    except (OSError, ValueError):
                        retained.append({"path": "runtimes/" + name, "code": "unknown_core", "reason": "无法验证完整不可变核心，保留"})
        except FileNotFoundError:
            pass
    return LifecyclePlan(state, before, tuple(observed), tuple(backups), tuple(archives), tuple(cores), tuple(retained),
                         tuple(lifecycle["released"] if lifecycle else []))


def _save(state: Path, journal: dict, before: Node) -> Node:
    _validate_entries(journal)
    with Tree(state) as tree:
        write_control(tree, RELATIVE, json_bytes(journal), expected=before)
    return read_state(state, RELATIVE)


def _approved_archive(root: Path) -> Path:
    """只接收本次明确选择的既有工作流备份批次，不扩展为任意目录清理器。"""
    root = root.absolute()
    valid = root.parent.name == ".sync-backups" or (root.parent.name == "workflow-backups" and root.parent.parent.name == ".claude")
    if not valid or not root.name or root.name.startswith(".") or root.is_symlink():
        raise ActivationError("显式旧归档必须是精确工作流备份批次目录")
    return root


def _delete_core(state: Path, row: dict) -> None:
    """仅删除快照中仍为原inode/内容的节点；缺失节点允许中断后幂等继续。

    文件删除前后只放宽本任务原目录的owner-write位。目录本身按inode识别，
    任何新增/换链/未知文件都会阻断。无递归rm，无跟随链接，无事后广域清扫。
    """
    snapshot = row["snapshot"]
    content_id = row["content_id"]
    if not isinstance(content_id, str) or not _DIGEST.fullmatch(content_id) or not isinstance(snapshot, dict) or "" not in snapshot:
        raise ActivationError("核心回收恢复清单无效")
    _delete_snapshot(state / "runtimes" / content_id, snapshot)


def _delete_snapshot(root_path: Path, snapshot: dict) -> None:
    """备份显式删除和核心GC共用精确快照删除，授权来源由上层分别验证。"""
    content_id = root_path.name
    with absolute_directory(root_path.parent) as parent:
        try:
            actual_root = os.stat(content_id, dir_fd=parent, follow_symlinks=False)
        except FileNotFoundError:
            return
        if not stat.S_ISDIR(actual_root.st_mode) or list(node_id(actual_root)) != snapshot[""]["inode"]:
            raise ActivationError("核心目录身份已变化，拒绝回收")
        root = os.open(content_id, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent)
        def remove(directory: int, prefix: str):
            expected = snapshot[prefix]
            info = os.fstat(directory)
            if list(node_id(info)) != expected["inode"] or stat.S_IMODE(info.st_mode) not in {expected["mode"], expected["mode"] | 0o200}:
                raise ActivationError("核心目录身份或权限变化，拒绝回收")
            os.fchmod(directory, expected["mode"] | 0o200)
            for name in sorted(os.listdir(directory)):
                relative = prefix + "/" + name if prefix else name
                expected_child = snapshot.get(relative)
                if expected_child is None:
                    raise ActivationError("核心目录出现未知新条目，保留")
                info = os.stat(name, dir_fd=directory, follow_symlinks=False)
                if expected_child.get("directory"):
                    if not stat.S_ISDIR(info.st_mode) or list(node_id(info)) != expected_child["inode"]:
                        raise ActivationError("核心子目录发生替换，保留")
                    child = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=directory)
                    try:
                        remove(child, relative)
                    finally:
                        os.close(child)
                    os.rmdir(name, dir_fd=directory)
                else:
                    if _file_metadata(directory, name) != expected_child:
                        raise ActivationError("核心文件已有变化，保留")
                    os.unlink(name, dir_fd=directory)
                os.fsync(directory)
        try:
            remove(root, "")
        finally:
            os.close(root)
        if list(node_id(os.stat(content_id, dir_fd=parent, follow_symlinks=False))) != snapshot[""]["inode"]:
            raise ActivationError("核心最终目录发生替换，保留")
        os.rmdir(content_id, dir_fd=parent)
        os.fsync(parent)


def _execute(state: Path, journal: dict, before: Node) -> dict:
    conflicts = []
    for row in journal["backups"]:
        if row["phase"] == "done":
            continue
        _check_observed(journal["observed"])
        project, record = Path(row["project"]), row["record"]
        try:
            with Tree(project) as tree:
                issues = retained_conflicts(tree, [record], typed=True)
                if any(issue["code"] != "history_missing" for issue in issues):
                    raise ActivationError("待清理旧inode已被修改，保留")
                if not issues:
                    parent, name = tree.parent(record["path"])
                    os.unlink(name, dir_fd=parent)
                    os.fsync(parent)
            row["phase"] = "done"
            receipt = {"project": str(project), "record": record}
            if receipt not in journal["released"]:
                journal["released"].append(receipt)
            before = _save(state, journal, before)
        except (OSError, ValueError) as exc:
            conflicts.append({"path": str(project / record["path"]), "reason": str(exc), "code": "backup_changed"})
    for row in journal["cores"]:
        if row["phase"] == "done":
            continue
        _check_observed(journal["observed"])
        try:
            if row["phase"] == "pending":
                if _core_snapshot(state / "runtimes" / row["content_id"]) != row["snapshot"]:
                    raise ActivationError("核心在清理预览后变化")
                row["phase"] = "deleting"
                before = _save(state, journal, before)
            _delete_core(state, row)
            row["phase"] = "done"
            before = _save(state, journal, before)
        except (OSError, ValueError) as exc:
            conflicts.append({"path": "runtimes/" + row["content_id"], "reason": str(exc), "code": "core_changed"})
    for row in journal["archives"]:
        if row["phase"] == "done":
            continue
        _check_observed(journal["observed"])
        root = _approved_archive(Path(row["root"]))
        try:
            if row["phase"] == "pending":
                if _core_snapshot(root) != row["snapshot"]:
                    raise ActivationError("显式归档在预览后变化，保留")
                row["phase"] = "deleting"
                before = _save(state, journal, before)
            _delete_snapshot(root, row["snapshot"])
            row["phase"] = "done"
            before = _save(state, journal, before)
        except (OSError, ValueError) as exc:
            conflicts.append({"path": str(root), "reason": str(exc), "code": "archive_changed"})
    journal.update(phase="conflict" if conflicts else "applied", conflicts=conflicts)
    _save(state, journal, before)
    if conflicts:
        raise ActivationError("生命周期清理含冲突，已保留未知节点及恢复记录", conflicts)
    return {"schema_version": 1, "transaction_id": journal["id"], "phase": "applied",
            "backups_removed": len(journal["backups"]), "archives_removed": len(journal["archives"]), "cores_removed": len(journal["cores"])}


def apply(plan: LifecyclePlan, *, cancel=None) -> dict:
    if not isinstance(plan, LifecyclePlan):
        raise ActivationError("需要同一进程生成的生命周期预览")
    if cancel is not None and cancel.is_set():
        raise ActivationError("已取消，生命周期计划未写入")
    if not plan.backups and not plan.archives and not plan.cores:
        return {"schema_version": 1, "changed": False, "backups_removed": 0, "cores_removed": 0}
    with ExitStack() as stack:
        stack.enter_context(policy.coordination(plan.state))
        policy.ensure_settled(plan.state)
        if _read_lifecycle(plan.state)[0] != plan.before:
            raise ActivationError("生命周期记录在预览后变化")
        _check_observed(list(plan.observed))
        if plan.cores:
            stack.enter_context(directory_lock(plan.state / "runtimes", "runtime-core-publication", blocking=True))
        journal = {"schema_version": 1, "id": uuid.uuid4().hex, "phase": "prepared", "observed": list(plan.observed),
                   "backups": list(plan.backups), "archives": list(plan.archives), "cores": list(plan.cores), "released": list(plan.released), "conflicts": []}
        before = _save(plan.state, journal, plan.before)
        return _execute(plan.state, journal, before)


def recover(state: Path) -> dict:
    """继续已确认清理，仅认原计划快照；中断不会扩大到后来新增的备份/核心。"""
    state = store.state_root(state)
    with ExitStack() as stack:
        stack.enter_context(policy.coordination(state))
        policy.ensure_settled(state)
        before, journal = _read_lifecycle(state)
        if journal is None or journal["phase"] not in {"prepared", "conflict"}:
            raise ActivationError("没有待恢复的生命周期事务")
        if journal["cores"]:
            stack.enter_context(directory_lock(state / "runtimes", "runtime-core-publication", blocking=True))
        _check_observed(journal["observed"])
        return _execute(state, journal, before)
