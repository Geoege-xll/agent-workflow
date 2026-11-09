"""中央私有记录的唯一 codec、条件发布与中断识别边界。

这里不执行启停、项目恢复或模型事务，不改变这些业务各自的补偿终结语义。
正式记录仍是原协议 JSON；确定性旁路标记只表示一次私有发布尚未可靠结束。
读取遇到标记一律安全拒绝，绝不通过随机临时文件猜测版本或自动删除资料。
"""

from __future__ import annotations

import hashlib
from pathlib import Path
import re
import stat
import uuid

from lib import runtime_store as store
from lib.platform_fs import os
from lib.central.runtime_project import (
    CAPACITY_IDENTITY, HOSTS, LIMIT, Node, ProjectRuntimeError, Tree, json_bytes, managed_path, node_id,
    project_key, identity, read_at, relative_path, skill_parts, unique_json, publish_at, move_at, delete_at,
)


_NONCE = re.compile(r"[0-9a-f]{32}\Z")
_DIGEST = re.compile(r"[0-9a-f]{64}\Z")
_RETAINED = re.compile(r"(?:.*/)?\.agent-workflow-central-[0-9a-f]{32}-[0-9]+\.(?:previous|rollback)\Z")
_ACTIONS = frozenset({"enable", "disable", "use", "rollback", "repair"})
# 发布见证含一个完整before，其base64长度为4*ceil(record_bytes/3)。封闭头的
# 最长私有路径是transactions/<64hex>.json，名字/摘要固定长度，stat整数的
# 十进制上界与生产者容量占位共用。这里只扩见证，不扩普通record/资源的4MiB。
_MARKER_METADATA_LIMIT = len(json_bytes({
    "schema_version": 1, "record": "transactions/" + "f" * 64 + ".json",
    "before": Node("missing", b"", 0o7777, CAPACITY_IDENTITY, "f" * 64 if os.name == "nt" else "").value(),
    "temporary": ".central-state-" + "f" * 32,
    "previous": ".central-state-previous-" + "f" * 32, "after_sha256": "f" * 64,
}))
PRIVATE_MARKER_LIMIT = _MARKER_METADATA_LIMIT + 4 * ((LIMIT + 2) // 3)
CONFLICT_REASON_LIMIT = 4096


class ActivationError(ProjectRuntimeError):
    """业务与记录边界共用的领域错误；诊断不包含任何私有记录正文。"""

    def __init__(self, message: str, conflicts=()):
        self.conflicts = tuple(conflicts)
        super().__init__(message)


def publication_capacity(record_bytes: int) -> int:
    """证明普通记录及其完整before见证均在各自预算内；不读取或创建状态。"""
    if type(record_bytes) is not int or not 0 <= record_bytes <= LIMIT:
        raise ActivationError("中央事务记录容量超过4MiB，未开始写入")
    return _MARKER_METADATA_LIMIT + 4 * ((record_bytes + 2) // 3)


def bounded_conflicts(rows: list[dict]) -> list[dict]:
    """只限制新生成诊断文本，历史Node正文/路径/归属原像完全保留。

    容量证明必须覆盖失败阶段；异常文本没有天然长度上界，因此生产者实际
    执行同一UTF-8字节约束。JSON最坏控制字符膨胀由预算里的\\u0000占位覆盖。
    """
    result = []
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get("reason"), str):
            raise ActivationError("冲突诊断容量结构无效")
        encoded = row["reason"].encode("utf-8", errors="replace")
        # 异常文字可能含操作系统surrogateescape；只规范新诊断，不让一个
        # 无法UTF-8编码的reason在目标写入后破坏本已证明有界的结算日志。
        reason = encoded.decode("utf-8") if len(encoded) <= CONFLICT_REASON_LIMIT else encoded[:CONFLICT_REASON_LIMIT - 3].decode("utf-8", errors="ignore") + "..."
        result.append({**row, "reason": reason})
    return result


def _record_size(body: bytes) -> None:
    if not isinstance(body, bytes):
        raise ActivationError("中央私有记录正文必须为bytes")
    publication_capacity(len(body))


def _marker_bytes(relative: str, before: Node, temporary: str, previous: str, after: bytes) -> bytes:
    value = {"schema_version": 1, "record": relative, "before": before.value(),
             "temporary": temporary, "previous": previous, "after_sha256": hashlib.sha256(after).hexdigest()}
    metadata = {**value, "before": {**value["before"], "body": ""}}
    if len(json_bytes(metadata)) > _MARKER_METADATA_LIMIT:
        raise ActivationError("私有发布见证元数据超出封闭预算")
    publication_capacity(len(before.payload))
    return json_bytes(value, max_bytes=PRIVATE_MARKER_LIMIT)


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
    _require(isinstance(raw, dict) and set(raw) == ({"kind", "body", "mode", "identity", "security"} if os.name == "nt" else {"kind", "body", "mode", "identity"}))
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
        keys = {"path", "kind", "mode", "sha256", "inode"}
        if os.name == "nt":
            keys.add("security")
            if isinstance(item, dict) and item.get("kind") == "link":
                keys.add("skill")
        _require(isinstance(item, dict) and set(item) == keys)
        if os.name == "nt":
            _require(isinstance(item["security"], str) and bool(_DIGEST.fullmatch(item["security"])))
            if item.get("kind") == "link":
                from lib.central.runtime_project import SKILL_NAME
                _require(isinstance(item["skill"], str) and bool(SKILL_NAME.fullmatch(item["skill"])))
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
                 and not (set(row) - keys - ({"stage_inode", "stage_security", "published_inode", "installed"} if os.name == "nt" else {"stage_inode", "published_inode", "installed"})))
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
        if os.name == "nt" and "stage_security" in row:
            _require(isinstance(row["stage_security"], str) and bool(_DIGEST.fullmatch(row["stage_security"]))
                     and "stage_inode" in row and _node(row["after"]).kind == "link")
        after = _node(row["after"])
        if os.name == "nt":
            if after.kind == "missing":
                _require(not {"stage_inode", "stage_security", "published_inode"}.intersection(row))
            elif after.kind == "link" and "stage_inode" in row:
                _require("stage_security" in row)
        if os.name == "nt" and "published_inode" in row:
            # published_inode 已表示完整 stage 准备就绪；planned 空身份/ACL
            # 此时不再足够。普通文件 stage 就是产物，Skill stage 则仍是带
            # 独立安全见证的目录，二者不可互换或待 installed 后才补事实。
            _require(after.kind in {"file", "link"} and len(after.identity) == 7
                     and row["published_inode"] == list(after.identity[:2]) and "stage_inode" in row)
            if after.kind == "file":
                _require(row["stage_inode"] == row["published_inode"] and "stage_security" not in row)
            else:
                _require("stage_security" in row)
        if "installed" in row:
            installed = _node(row["installed"])
            _require(installed.same_content(after))
            if os.name == "nt" and installed.kind != "missing":
                _require("published_inode" in row and same_published_node(installed, after))
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
        if snapshot.mode != 0o600:
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


def retained_conflicts(tree: Tree, records: list[dict], *, typed: bool = False) -> list[dict]:
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
            node = read_at(parent, name, allow_link=True, skill_name=item.get("skill"))
        # 同一节点可能同时改变多项；按缺失、内容/类型、权限、inode 身份的
        # 优先级报告最直接的事实，不能把缺失推断成后续保存。这里只细分诊断，
        # 任一差异仍保留原有冲突阻断，不认领、修复或删除恢复资料。
        if node.kind == "missing":
            reason = "保留的旧 inode 路径已缺失"
        elif node.kind != item["kind"] or hashlib.sha256(node.payload).hexdigest() != item["sha256"]:
            reason = "保留的旧 inode 内容或类型已变化"
        elif node.mode != item["mode"] or os.name == "nt" and node.security != item["security"]:
            reason = "保留的旧 inode 权限已变化"
        elif list(node.identity[:2]) != item["inode"]:
            reason = "保留的旧 inode 身份已变化"
        else:
            continue
        # 消费者必须根据稳定类型判断影响层级；中文诊断只供展示，不能作为
        # 新任务许可或管理写许可的分支条件。历史缺失不会破坏当前有效资源。
        issue = {"path": item["path"], "reason": reason}
        if typed:
            issue.update(code="history_missing" if node.kind == "missing" else "history_modified", layer="history")
        conflicts.append(issue)
    return conflicts


def retained_record(path: str, node: Node, *, skill_name: str | None = None) -> dict:
    record = {"path": path, "kind": node.kind, "mode": node.mode,
              "sha256": hashlib.sha256(node.payload).hexdigest(), "inode": list(node.identity[:2])}
    if os.name == "nt":
        record["security"] = node.security
        if node.kind == "link":
            if skill_name is None or Path(os.fsdecode(node.payload)).name != skill_name:
                raise ActivationError("保留链接缺少原始受管 Skill 名称或目标同名校验失败")
            record["skill"] = skill_name
    validate_retained([record])
    return record


def _same_inode(actual: Node, expected: Node) -> bool:
    return actual.same_content(expected) and actual.mode == expected.mode and actual.identity[:2] == expected.identity[:2] and actual.identity[4:6] == expected.identity[4:6] and actual.security == expected.security


def same_published_node(actual: Node, expected: Node) -> bool:
    """Windows 发布/codec/恢复共用完整实际见证，仅排除 rename 自身的 ChangeTime。

    planned 空身份不构成发布授权；内容模式的宽投影也不能替代实际 mode、
    节点身份、链接数、大小、mtime 或独立 ACL/owner 指纹。没有历史写承诺。
    """
    return (actual.kind in {"file", "link"} and actual.kind == expected.kind
            and len(actual.identity) == len(expected.identity) == 7
            and isinstance(actual.security, str) and bool(_DIGEST.fullmatch(actual.security))
            and actual.security == expected.security and actual.same_content(expected)
            and actual.mode == expected.mode and actual.identity[:6] == expected.identity[:6])


def write_private(tree: Tree, relative: str, body: bytes, *, expected: Node | None = None) -> None:
    """在调用方既有中央锁内条件发布，任何直接退出都留下确定性见证。

    保留 rename 旧 inode + no-replace link 的并发守卫，拒绝发布前像变化、
    隔离期间保存及正式名称碰撞。标记存在时只有本函数持有的精确父目录、
    临时名和节点身份可用于内部核对；业务 reader 没有绕过中断标记的入口。
    这里只保障单机状态的可识别结算，不承诺项目/机器跨文件系统原子提交。
    """
    _record_size(body)
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
    _publish_private(tree, relative, body, expected=expected)


def write_control(tree: Tree, relative: str, body: bytes, *, expected: Node) -> None:
    """发布中央旁路记录；业务 codec 在调用前校验，基础边界限定私有命名空间。

    current、策略、全局事务及生命周期记录不能进入封闭 binding 或任务 pin。
    路径白名单阻止业务层把这个安全发布原语用作任意项目文件写入器；全部
    调用都必须显式给出前像，不能把发布时重新读取的外部保存自动认作授权。
    """
    _record_size(body)
    relative_path(relative)
    allowed = relative in {"central/current.json", "central/activation.json", "central/lifecycle.json"}
    allowed = allowed or bool(re.fullmatch(r"policies/[0-9a-f]{64}\.json", relative))
    if not allowed or not isinstance(expected, Node):
        raise ActivationError("中央旁路记录路径或前像无效")
    raw = unique_json(body)
    if not isinstance(raw, dict) or type(raw.get("schema_version")) is not int or raw["schema_version"] != 1:
        raise ActivationError("中央旁路记录结构无效")
    namespace = relative.split("/", 1)[0]
    root_descriptor = tree.directories[""]
    try:
        os.mkdir(namespace, 0o700, dir_fd=root_descriptor)
        os.fsync(root_descriptor)
    except FileExistsError:
        pass
    descriptor = tree.directory(namespace)
    if stat.S_IMODE(os.fstat(descriptor).st_mode) != 0o700:
        raise ActivationError("中央旁路记录目录必须保持私有 0700 权限")
    _publish_private(tree, relative, body, expected=expected)


def _publish_private(tree: Tree, relative: str, body: bytes, *, expected: Node | None) -> None:
    """在固定父目录上执行同一套见证、前像比较和 inode 保全发布。"""
    parent, name = tree.parent(relative, create=True)
    _check_marker(parent, name, relative)
    before = read_at(parent, name)
    # 调用方可绑定最终核对的完整前像，防止其 capture 与这里重新读取 before
    # 之间发生的外部保存被认领为本次可覆盖版本。必须比较完整 Node（包含字节、
    # 权限及时间/inode 身份），并在生成临时名、创建见证或发布任何记录前拒绝；
    # 未显式传 expected 的既有调用仍沿用原内部条件发布与异常保全语义。
    if expected is not None and before != expected:
        raise ActivationError("机器记录与调用方预期前像不符，拒绝发布")
    temporary = ".central-state-" + uuid.uuid4().hex
    held_name = ".central-state-previous-" + uuid.uuid4().hex
    marker_name = _marker_name(name)
    marker_body = _marker_bytes(relative, before, temporary, held_name, body)
    # O_EXCL 使两个 writer 即使误缺中央锁也不能共享一次发布见证；旧/未知标记
    # 永不认领。先落盘标记和父目录，再触碰正式名称，覆盖首次发布无记录窗口。
    held = None
    temporary_inode = None
    temporary_snapshot = None
    temporary_clean = True
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
            temporary_info = os.fstat(descriptor)
            temporary_inode = node_id(temporary_info)
            if os.name == "nt":
                from lib.windows_fs import security_fingerprint
                # fdopen 尚未成功时正文必为空；先记下真实完整 empty Node，取消
                # 也只能条件删除这一版本，不能把后续部分写入或他人保存当作空文件。
                temporary_snapshot = Node("file", b"", stat.S_IMODE(temporary_info.st_mode),
                                          identity(temporary_info), security_fingerprint(descriptor))
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
        temporary_snapshot = read_at(parent, temporary)
        if (temporary_snapshot.identity[:2] != temporary_inode
                or temporary_snapshot.mode != 0o600
                or not temporary_snapshot.same_content(Node("file", body, 0o600))):
            raise ActivationError("机器临时记录在发布前被修改")
        if read_at(parent, name) != before:
            raise ActivationError("机器记录在发布前被修改")
        if before.kind != "missing":
            held = held_name
            move_at(name, held, src_dir_fd=parent, dst_dir_fd=parent, expected=before)
            if not _same_inode(read_at(parent, held), before):
                raise ActivationError("机器记录在隔离时被修改，保留旧记录")
        publish_at(temporary, name, src_dir_fd=parent, dst_dir_fd=parent,
                   expected=temporary_snapshot)
        os.fsync(parent)
        if held is not None:
            held_snapshot = read_at(parent, held)
            if not _same_inode(held_snapshot, before):
                raise ActivationError("机器旧记录发生后续保存，已保留")
            delete_at(parent, held, expected=held_snapshot)
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
            held_snapshot = read_at(parent, held)
            if _same_inode(held_snapshot, before):
                try:
                    publish_at(held, name, src_dir_fd=parent, dst_dir_fd=parent, expected=held_snapshot)
                except FileExistsError:
                    pass
                else:
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
                if temporary_snapshot is not None and read_at(parent, temporary) == temporary_snapshot:
                    delete_at(parent, temporary, expected=temporary_snapshot)
                elif os.name != "nt" and node_id(actual) == temporary_inode:
                    # POSIX 原有已知 own inode 清理语义保持，旧 fdopen 中断不会
                    # 因 Windows 新增完整 ACL 见证而留下新的阻断 marker。
                    os.unlink(temporary, dir_fd=parent)
                else:
                    # 尚无完整 stage 身份或含后来保存时，保留 marker 指向该资料。
                    temporary_clean = False
        # 正常完成或精确回到原前像才能撤见证；失败中的未知状态永久失败关闭。
        current = read_at(parent, name)
        restored = (temporary_clean and held is None and (not temporary_opened or temporary_inode is not None)
                    and (current == before if before.kind == "missing" else _same_inode(current, before)))
        # 最后一次 fsync 也可能与外部保存交错；完成标志只说明步骤走过，不能
        # 代替此刻的新 inode/字节/权限/时间身份。变化时留标记并拒绝假报成功。
        finished = completed and current == published
        if completed and not finished:
            raise ActivationError("机器新记录在结算前已有后续保存，已保留核对资料：" + relative + ".publish")
        if finished or restored:
            marker = read_at(parent, marker_name, max_bytes=PRIVATE_MARKER_LIMIT)
            if marker.identity[:2] != marker_inode or marker.payload != marker_body:
                raise ActivationError("私有发布见证已有外部修改，已保留核对资料：" + relative + ".publish")
            delete_at(parent, marker_name, expected=marker, max_bytes=PRIVATE_MARKER_LIMIT)
            os.fsync(parent)
