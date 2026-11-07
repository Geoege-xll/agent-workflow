"""中央私有记录的唯一 codec、条件发布与中断识别边界。

这里不执行启停、项目恢复或模型事务，不改变这些业务各自的补偿终结语义。
正式记录仍是原协议 JSON；确定性旁路标记只表示一次私有发布尚未可靠结束。
读取遇到标记一律安全拒绝，绝不通过随机临时文件猜测版本或自动删除资料。
"""

from __future__ import annotations

import hashlib
from pathlib import Path
import re
import uuid

from lib import runtime_store as store
from lib.platform_fs import os
from lib.central.runtime_project import (
    HOSTS, Node, ProjectRuntimeError, Tree, json_bytes, managed_path, node_id,
    project_key, read_at, relative_path, skill_parts, unique_json,
)


_NONCE = re.compile(r"[0-9a-f]{32}\Z")
_DIGEST = re.compile(r"[0-9a-f]{64}\Z")
_RETAINED = re.compile(r"(?:.*/)?\.agent-workflow-central-[0-9a-f]{32}-[0-9]+\.(?:previous|rollback)\Z")
_ACTIONS = frozenset({"enable", "disable", "use", "rollback", "repair"})


class ActivationError(ProjectRuntimeError):
    """业务与记录边界共用的领域错误；诊断不包含任何私有记录正文。"""

    def __init__(self, message: str, conflicts=()):
        self.conflicts = tuple(conflicts)
        super().__init__(message)


def state_relative(project: Path, kind: str) -> str:
    if kind not in {"bindings", "transactions"}:
        raise ActivationError("未知的中央私有记录种类")
    return f"{kind}/{project_key(project)}.json"


def _marker_name(name: str) -> str:
    return name + ".publish"


def _check_marker(parent: int, name: str, relative: str) -> None:
    try:
        os.stat(_marker_name(name), dir_fd=parent, follow_symlinks=False)
    except FileNotFoundError:
        return
    # 标记只作失败关闭的见证，不是可执行恢复命令；截断文件、链接或未知内容
    # 同样表示不确定。只报告可找回的确定性位置，不打开或回显其私有前像。
    raise ActivationError("中央私有记录发布中断或尚未结算；已保留核对资料：" + relative + ".publish")


def read_state(state: Path, relative: str) -> Node:
    """在正式读取前后检查发布见证，缺正式文件也不能绕过中断识别。"""
    try:
        with Tree(state) as tree:
            try:
                parent, name = tree.parent(relative)
            except FileNotFoundError:
                return Node()
            _check_marker(parent, name, relative)
            try:
                snapshot = read_at(parent, name)
            except ProjectRuntimeError:
                # 覆盖 reader 先检查标记、writer 随后进入 link 双硬链窗口的交错。
                _check_marker(parent, name, relative)
                raise
            _check_marker(parent, name, relative)
            return snapshot
    except FileNotFoundError:
        return Node()


def _require(condition: bool) -> None:
    if not condition:
        raise ActivationError("中央私有记录嵌套结构无效")


def _node(raw: object) -> Node:
    # Node.from_value 是项目资源的基础 codec；私有边界先校验可哈希/正文类型，
    # 再补齐 missing 与身份的一致性，避免坏嵌套穿出 TypeError/KeyError。
    _require(isinstance(raw, dict) and set(raw) == {"kind", "body", "mode", "identity"})
    _require(isinstance(raw["kind"], str) and isinstance(raw["body"], str))
    value = Node.from_value(raw)
    _require(all(item >= 0 for item in value.identity[:5]))
    if value.kind == "missing":
        _require(value.payload == b"" and value.mode == 0 and not value.identity)
    return value


def _inode(raw: object) -> None:
    _require(isinstance(raw, list) and len(raw) == 2
             and all(type(item) is int and item >= 0 for item in raw))


def validate_retained(records: object) -> None:
    """完整验证旧 inode 清单，业务获得清单前即拒绝任何坏项。"""
    _require(isinstance(records, list))
    for item in records:
        _require(isinstance(item, dict) and set(item) == {"path", "kind", "mode", "sha256", "inode"})
        relative = relative_path(item["path"])
        _require(bool(_RETAINED.fullmatch(relative)))
        _require(isinstance(item["kind"], str) and item["kind"] in {"file", "link"}
                 and type(item["mode"]) is int and 0 <= item["mode"] <= 0o7777
                 and isinstance(item["sha256"], str) and bool(_DIGEST.fullmatch(item["sha256"])))
        _inode(item["inode"])


def _binding(record: object, project: Path) -> dict:
    required = {"schema_version", "project_root", "project_identity", "runtime_binding", "enabled",
                "hosts", "previous_binding", "used_bindings", "managed", "retained_nodes", "generation"}
    _require(isinstance(record, dict) and set(record) == required)
    _require(type(record["schema_version"]) is int and record["schema_version"] == 1
             and record["project_root"] == str(project)
             and record["project_identity"] == list(node_id(project.stat()))
             and isinstance(record["project_identity"], list)
             and all(type(item) is int for item in record["project_identity"])
             and type(record["enabled"]) is bool)
    hosts = record["hosts"]
    _require(isinstance(hosts, list) and bool(hosts)
             and all(isinstance(host, str) and host in HOSTS for host in hosts)
             and len(set(hosts)) == len(hosts))
    _require(isinstance(record["generation"], str) and bool(_NONCE.fullmatch(record["generation"])))
    binding = store.validate_binding(record["runtime_binding"])
    previous = record["previous_binding"]
    if previous is not None:
        store.validate_binding(previous)
    _require(isinstance(record["used_bindings"], list))
    used = [store.validate_binding(item) for item in record["used_bindings"]]
    if binding not in used or (previous is not None and previous not in used):
        raise ActivationError("本机当前或前次绑定不在项目已用版本历史中")
    _require(isinstance(record["managed"], dict))
    for relative, managed in record["managed"].items():
        relative_path(relative)
        _require(isinstance(managed, dict) and set(managed) == {"purpose", "baseline", "expected"}
                 and isinstance(managed["purpose"], str) and managed_path(relative, managed["purpose"]))
        for key in ("baseline", "expected"):
            value = _node(managed[key])
            _require(value.kind != "link" or bool(skill_parts(relative)))
    validate_retained(record["retained_nodes"])
    return record


def _journal(record: object, project: Path) -> dict:
    required = {"schema_version", "project_root", "id", "phase", "action", "binding_before", "changes", "conflicts"}
    _require(isinstance(record, dict) and required <= set(record)
             and not (set(record) - required - {"retained_nodes"}))
    _require(type(record["schema_version"]) is int and record["schema_version"] == 1
             and record["project_root"] == str(project)
             and isinstance(record["id"], str) and bool(_NONCE.fullmatch(record["id"]))
             and isinstance(record["phase"], str) and record["phase"] in {"prepared", "applied", "rolled_back", "conflict"}
             and isinstance(record["action"], str) and record["action"] in _ACTIONS)
    before = _node(record["binding_before"])
    _require(before.kind in {"missing", "file"})
    if before.kind == "file":
        _require(before.mode == 0o600 and len(before.identity) == 7)
        _binding(unique_json(before.payload), project)
    _require(isinstance(record["changes"], list))
    seen = set()
    for index, row in enumerate(record["changes"]):
        keys = {"path", "before", "after", "backup", "stage", "rollback"}
        _require(isinstance(row, dict) and keys <= set(row)
                 and not (set(row) - keys - {"stage_inode", "published_inode", "installed"}))
        relative = relative_path(row["path"])
        # journal 还包含共享 Hook guard 和配置指定的 persistent 文档，不等于
        # binding.managed 的独占清单；此处保持原规范根内路径合同，不缩窄业务授权。
        _require(relative not in seen)
        seen.add(relative)
        parent, _, _ = relative.rpartition("/")
        prefix = parent + "/" if parent else ""
        expected = prefix + f".agent-workflow-central-{record['id']}-{index}"
        _require(all(row[key] == expected + suffix for key, suffix in
                     (("backup", ".previous"), ("stage", ".stage"), ("rollback", ".rollback"))))
        for key in ("before", "after", "installed"):
            if key in row:
                value = _node(row[key])
                _require(value.kind != "link" or bool(skill_parts(relative)))
        for key in ("stage_inode", "published_inode"):
            if key in row:
                _inode(row[key])
        if "installed" in row:
            installed = _node(row["installed"])
            _require(installed.same_content(_node(row["after"])))
            if installed.kind != "missing":
                _require(list(installed.identity[:2]) == row.get("published_inode"))
    _require(isinstance(record["conflicts"], list))
    for conflict in record["conflicts"]:
        _require(isinstance(conflict, dict) and set(conflict) == {"path", "reason"}
                 and isinstance(conflict["reason"], str))
        if conflict["path"] != ".":
            relative_path(conflict["path"])
    validate_retained(record.get("retained_nodes", []))
    return record


def _decode(snapshot: Node, project: Path, kind: str) -> dict:
    message = "本机项目绑定结构或物理目录身份无效" if kind == "bindings" else "中央项目事务恢复记录无效"
    try:
        _require(snapshot.kind == "file")
        if os.name != "nt" and snapshot.mode != 0o600:
            raise ActivationError("本机项目绑定必须保持私有 0600 权限" if kind == "bindings"
                                  else "中央恢复记录必须保持私有 0600 权限")
        record = unique_json(snapshot.payload)
        return _binding(record, project) if kind == "bindings" else _journal(record, project)
    except ActivationError:
        raise
    except (ValueError, TypeError, KeyError, RecursionError, OverflowError) as exc:
        # 不把异常中的坏值拼到领域诊断中；因果链仅供程序诊断，CLI/TUI 显示外层。
        raise ActivationError(message) from exc


def read_binding_record(state: Path, project: Path) -> tuple[Node, dict | None]:
    snapshot = read_state(state, state_relative(project, "bindings"))
    return snapshot, None if snapshot.kind == "missing" else _decode(snapshot, project, "bindings")


def read_journal(state: Path, project: Path) -> tuple[Node, dict | None]:
    snapshot = read_state(state, state_relative(project, "transactions"))
    return snapshot, None if snapshot.kind == "missing" else _decode(snapshot, project, "transactions")


def retained_conflicts(tree: Tree, records: list[dict]) -> list[dict]:
    try:
        validate_retained(records)
    except (ValueError, TypeError, KeyError) as exc:
        raise ActivationError("保留 inode 记录结构无效") from exc
    conflicts = []
    for item in records:
        try:
            parent, name = tree.parent(item["path"])
        except FileNotFoundError:
            node = Node()
        else:
            node = read_at(parent, name, allow_link=True)
        # 同一节点可能同时改变多项；按缺失、内容/类型、权限、inode 身份的
        # 优先级报告最直接的事实，不能把缺失推断成后续保存。这里只细分诊断，
        # 任一差异仍保留原有冲突阻断，不认领、修复或删除恢复资料。
        if node.kind == "missing":
            reason = "保留的旧 inode 路径已缺失"
        elif node.kind != item["kind"] or hashlib.sha256(node.payload).hexdigest() != item["sha256"]:
            reason = "保留的旧 inode 内容或类型已变化"
        elif node.mode != item["mode"]:
            reason = "保留的旧 inode 权限已变化"
        elif list(node.identity[:2]) != item["inode"]:
            reason = "保留的旧 inode 身份已变化"
        else:
            continue
        conflicts.append({"path": item["path"], "reason": reason})
    return conflicts


def retained_record(path: str, node: Node) -> dict:
    record = {"path": path, "kind": node.kind, "mode": node.mode,
              "sha256": hashlib.sha256(node.payload).hexdigest(), "inode": list(node.identity[:2])}
    validate_retained([record])
    return record


def _same_inode(actual: Node, expected: Node) -> bool:
    return actual.same_content(expected) and actual.mode == expected.mode and actual.identity[:2] == expected.identity[:2]


def write_private(tree: Tree, relative: str, body: bytes) -> None:
    """在调用方既有中央锁内条件发布，任何直接退出都留下确定性见证。

    保留 rename 旧 inode + no-replace link 的并发守卫，拒绝发布前像变化、
    隔离期间保存及正式名称碰撞。标记存在时只有本函数持有的精确父目录、
    临时名和节点身份可用于内部核对；业务 reader 没有绕过中断标记的入口。
    这里只保障单机状态的可识别结算，不承诺项目/机器跨文件系统原子提交。
    """
    # 发布也使用同一完整 codec，避免业务在修改项目后写出 reader 无法接受的日志。
    try:
        raw = unique_json(body)
        _require(isinstance(raw, dict) and isinstance(raw.get("project_root"), str))
        project = Path(raw["project_root"])
        kind = relative.split("/", 1)[0]
        _require(project.is_absolute() and relative == state_relative(project, kind))
        _decode(Node("file", body, 0o600), project, kind)
    except (ValueError, TypeError, KeyError) as exc:
        raise ActivationError("待发布中央私有记录无效") from exc
    parent, name = tree.parent(relative, create=True)
    _check_marker(parent, name, relative)
    before = read_at(parent, name)
    temporary = ".central-state-" + uuid.uuid4().hex
    held_name = ".central-state-previous-" + uuid.uuid4().hex
    marker_name = _marker_name(name)
    marker_body = json_bytes({"schema_version": 1, "record": relative, "before": before.value(),
                              "temporary": temporary, "previous": held_name,
                              "after_sha256": hashlib.sha256(body).hexdigest()})
    # O_EXCL 使两个 writer 即使误缺中央锁也不能共享一次发布见证；旧/未知标记
    # 永不认领。先落盘标记和父目录，再触碰正式名称，覆盖首次发布无记录窗口。
    held = None
    temporary_inode = None
    temporary_opened = False
    completed = False
    published = None
    descriptor = None
    try:
        descriptor = os.open(marker_name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=parent)
        marker_inode = node_id(os.fstat(descriptor))
        marker_stream = os.fdopen(descriptor, "wb")
    except BaseException:
        # open 返回后裸 fd 由本调用独占；只有 fdopen 成功才移交给 stream。
        # fstat/移交前取消也必须关闭，尚未确证身份或完整内容的 marker 保留拒绝。
        if descriptor is not None:
            os.close(descriptor)
        raise
    try:
        with marker_stream as stream:
            stream.write(marker_body)
            stream.flush()
            os.fchmod(stream.fileno(), 0o600)
            os.fsync(stream.fileno())
        os.fsync(parent)
        descriptor = None
        try:
            descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=parent)
            temporary_opened = True
            temporary_inode = node_id(os.fstat(descriptor))
            temporary_stream = os.fdopen(descriptor, "wb")
        except BaseException:
            # 临时文件也只在成功移交后由 stream 关闭，元数据失败不能漏 fd。
            # 未取得 inode 时，路径名称本身不足以授权删除，由下方保留见证。
            if descriptor is not None:
                os.close(descriptor)
            raise
        with temporary_stream as stream:
            stream.write(body)
            stream.flush()
            os.fchmod(stream.fileno(), 0o600)
            os.fsync(stream.fileno())
        if read_at(parent, name) != before:
            raise ActivationError("机器记录在发布前被修改")
        if before.kind != "missing":
            held = held_name
            os.rename(name, held, src_dir_fd=parent, dst_dir_fd=parent)
            if not _same_inode(read_at(parent, held), before):
                raise ActivationError("机器记录在隔离时被修改，保留旧记录")
        os.link(temporary, name, src_dir_fd=parent, dst_dir_fd=parent, follow_symlinks=False)
        os.unlink(temporary, dir_fd=parent)
        os.fsync(parent)
        if held is not None:
            if not _same_inode(read_at(parent, held), before):
                raise ActivationError("机器旧记录发生后续保存，已保留")
            os.unlink(held, dir_fd=parent)
            held = None
        current = read_at(parent, name)
        if not (current.same_content(Node("file", body, 0o600)) and current.identity[:2] == temporary_inode):
            raise ActivationError("机器新记录已有后续保存，已保留")
        published = current
        os.fsync(parent)
        completed = True
    except BaseException:
        if held is not None:
            # 同步失败仅在正式名称仍为空、旧 inode 与原前像完全一致时回接。
            # 若已有第三方节点或旧 inode 后续保存，就保留两边与标记等待核对。
            if _same_inode(read_at(parent, held), before):
                try:
                    os.link(held, name, src_dir_fd=parent, dst_dir_fd=parent, follow_symlinks=False)
                except FileExistsError:
                    pass
                else:
                    os.unlink(held, dir_fd=parent)
                    held = None
                    os.fsync(parent)
        raise
    finally:
        # 清理只认本次创建的 inode；攻击者/外部保存替换的同名临时节点不删除。
        if temporary_inode is not None:
            try:
                actual = os.stat(temporary, dir_fd=parent, follow_symlinks=False)
            except FileNotFoundError:
                pass
            else:
                if node_id(actual) == temporary_inode:
                    os.unlink(temporary, dir_fd=parent)
        # 正常完成或精确回到原前像才能撤见证；失败中的未知状态永久失败关闭。
        current = read_at(parent, name)
        restored = (held is None and (not temporary_opened or temporary_inode is not None)
                    and (current == before if before.kind == "missing" else _same_inode(current, before)))
        # 最后一次 fsync 也可能与外部保存交错；完成标志只说明步骤走过，不能
        # 代替此刻的新 inode/字节/权限/时间身份。变化时留标记并拒绝假报成功。
        finished = completed and current == published
        if completed and not finished:
            raise ActivationError("机器新记录在结算前已有后续保存，已保留核对资料：" + relative + ".publish")
        if finished or restored:
            marker = read_at(parent, marker_name)
            if marker.identity[:2] != marker_inode or marker.payload != marker_body:
                raise ActivationError("私有发布见证已有外部修改，已保留核对资料：" + relative + ".publish")
            os.unlink(marker_name, dir_fd=parent)
            os.fsync(parent)
