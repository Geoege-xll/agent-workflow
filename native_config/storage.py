"""有界、不跟随链接的模型文件快照和条件原子写入。"""

from __future__ import annotations

from contextlib import ExitStack, contextmanager
from dataclasses import dataclass
import fcntl
import hashlib
import os
from pathlib import Path
import secrets
import stat
from typing import Callable

from .contracts import ConfigError, ConflictError, MAX_FILE_BYTES as MAX_BYTES, absolute_path


_DIR_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0)
_READ_FLAGS = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | getattr(os, "O_CLOEXEC", 0)


def _identity(info) -> tuple:
    return (info.st_dev, info.st_ino, info.st_mode, info.st_nlink,
            info.st_size, info.st_mtime_ns, info.st_ctime_ns)


@dataclass(frozen=True)
class Snapshot:
    """正文只留在服务内部；公开版本摘要同时包含内容及真实文件身份。"""

    body: bytes | None = None
    identity: tuple = ()

    def revision(self) -> str:
        material = repr(self.identity).encode("ascii") + b"\0" + (self.body or b"")
        return hashlib.sha256(material).hexdigest()


class _Directory:
    """保留每一级描述符，打开和最终发布均检查路径仍指向同一真实目录。"""

    def __init__(self):
        self.descriptors = []
        self.links = []

    @property
    def fd(self):
        return self.descriptors[-1]

    def check(self):
        for parent, name, expected in self.links:
            try:
                info = os.stat(name, dir_fd=parent, follow_symlinks=False)
            except FileNotFoundError as exc:
                raise ConflictError("配置父目录在操作期间变化") from exc
            if not stat.S_ISDIR(info.st_mode) or (info.st_dev, info.st_ino) != expected:
                raise ConflictError("配置父目录在操作期间变化")


@contextmanager
def directory(path: Path, *, create: bool = False):
    """从文件系统根逐段 no-follow；只在 apply 的明确写入路径创建目录。"""
    path = absolute_path(path)
    handle = _Directory()
    try:
        handle.descriptors.append(os.open(path.anchor, _DIR_FLAGS))
        for name in path.parts[1:]:
            parent = handle.fd
            if create:
                try:
                    os.mkdir(name, 0o700, dir_fd=parent)
                except FileExistsError:
                    pass
            info = os.stat(name, dir_fd=parent, follow_symlinks=False)
            if not stat.S_ISDIR(info.st_mode):
                raise ConfigError("配置父路径不能是链接或特殊节点")
            child = os.open(name, _DIR_FLAGS, dir_fd=parent)
            handle.descriptors.append(child)
            if (os.fstat(child).st_dev, os.fstat(child).st_ino) != (info.st_dev, info.st_ino):
                raise ConflictError("配置父目录在打开时变化")
            handle.links.append((parent, name, (info.st_dev, info.st_ino)))
        yield handle
        handle.check()
    finally:
        for descriptor in reversed(handle.descriptors):
            os.close(descriptor)


def project_identity(path: Path) -> tuple[int, int]:
    """项目必须已存在；不创建、不登记，也不接受指向其他目录的项目链接。"""
    try:
        with directory(path) as handle:
            info = os.fstat(handle.fd)
            return info.st_dev, info.st_ino
    except OSError as exc:
        raise ConfigError("项目必须是已存在且不含链接的真实目录") from exc


def _read_at(parent: int, name: str) -> Snapshot:
    try:
        before = os.stat(name, dir_fd=parent, follow_symlinks=False)
    except FileNotFoundError:
        return Snapshot()
    if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1 or before.st_size > MAX_BYTES:
        raise ConfigError("模型配置必须是有界的单链接普通文件")
    descriptor = os.open(name, _READ_FLAGS, dir_fd=parent)
    with os.fdopen(descriptor, "rb") as stream:
        if _identity(os.fstat(stream.fileno())) != _identity(before):
            raise ConflictError("模型配置在打开时变化")
        body = stream.read(MAX_BYTES + 1)
        if len(body) > MAX_BYTES or _identity(os.fstat(stream.fileno())) != _identity(before):
            raise ConflictError("模型配置在读取时变化")
    try:
        after = os.stat(name, dir_fd=parent, follow_symlinks=False)
    except FileNotFoundError as exc:
        raise ConflictError("模型配置在读取时变化") from exc
    if _identity(after) != _identity(before):
        raise ConflictError("模型配置在读取时变化")
    return Snapshot(body, _identity(before))


def read(path: Path) -> Snapshot:
    try:
        with directory(path.parent) as handle:
            return _read_at(handle.fd, path.name)
    except FileNotFoundError:
        return Snapshot()
    except OSError as exc:
        raise ConfigError("模型配置无法安全读取") from exc



@dataclass(frozen=True)
class Write:
    """批量计划的一项精确前后像；路径只能来自服务端原生清单。"""
    role: str
    path: Path
    before: Snapshot
    after: bytes



@dataclass
class _Staged:
    """私有隔离目录保存真实 inode；恢复副本与实际外部对象分别留存。"""
    name: str
    parent: int
    descriptor: int
    temporary: set
    captures: dict


def _same_after_move(actual: Snapshot, expected: Snapshot) -> bool:
    """rename/link 正常改变 ctime；其余身份、权限、大小、mtime 与正文必须一致。"""
    return (actual.body == expected.body and actual.body is not None
            and actual.identity[:6] == expected.identity[:6])


def write_batch(changes: tuple[Write, ...], guard: Callable[[], None]) -> dict:
    """隔离实际目标后核对前像，再排他发布；任何新出现的目标都不能被覆盖。

    标准库没有跨平台的 rename-CAS。这里使用同目录 0700 私有隔离目录和
    link 的 EEXIST 语义，而不是检查后无条件 replace。隔离到发布之间目标会
    短暂缺失，响应明确记录该可见性边界，也不承诺跨文件系统断电原子性。
    真实隔离 inode 可能仍被编辑器已打开的 fd 写入，所以无论成功或回滚都
    永久保留到另有明确的安全清理合同；不靠再次 stat 猜测不存在外部写者。
    """
    if len(changes) > 64 or len({item.path for item in changes}) != len(changes):
        raise ConfigError("批量保存计划无效")
    result = {"saved": False, "partial_failure": False, "published": False,
              "namespace_touched": False, "temporary_visibility_gap": False,
              "results": [], "recovery": [],
              "retention_policy": "until_explicit_safe_cleanup_contract"}
    if not changes:
        return result
    prepared, published = {}, {}
    statuses = {item.role: "not_written" for item in changes}
    failure = None
    with ExitStack() as stack:
        handles = {}

        def stage(slot, name, body, mode=0o600):
            if body is None or len(body) > MAX_BYTES:
                raise ConfigError("原生 Agent 前后像无效")
            descriptor = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                                 0o600, dir_fd=slot.descriptor)
            slot.temporary.add(name)
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(body)
                stream.flush()
                os.fchmod(stream.fileno(), mode)
                os.fsync(stream.fileno())

        def capture(slot, target, name):
            # 目的名字位于本次排他创建的私有目录中，不指向任何公共/既有对象。
            if name in slot.captures or name in slot.temporary:
                raise ConfigError("隔离目标名称重复")
            os.rename(target, name, src_dir_fd=slot.parent, dst_dir_fd=slot.descriptor)
            slot.captures[name] = None
            result["namespace_touched"] = result["temporary_visibility_gap"] = True
            actual = _read_at(slot.descriptor, name)
            slot.captures[name] = actual
            return actual

        def link_candidate(slot, candidate, target, *, item=None):
            staged = _read_at(slot.descriptor, candidate)
            # 真实发布线性化点：目标缺失时才创建；外部原子保存一旦重建名字，
            # link 必须以 EEXIST 拒绝，绝不以 replace/rename 再次覆盖它。
            os.link(candidate, target, src_dir_fd=slot.descriptor, dst_dir_fd=slot.parent,
                    follow_symlinks=False)
            if item is not None:
                result["published"] = True
                published[item.role] = staged
                statuses[item.role] = "saved"
            os.unlink(candidate, dir_fd=slot.descriptor)
            slot.temporary.remove(candidate)
            actual = _read_at(slot.parent, target)
            if not _same_after_move(actual, staged):
                raise ConflictError("排他发布后目标再次变化，未覆盖外部保存")
            if item is not None:
                published[item.role] = actual
            return actual

        def restore_copy(slot, target, node, candidate):
            # 从副本恢复，实际隔离的外部 inode 始终留在私有目录中。即使目标
            # 在 link 返回后又被外部替换，删除本服务的副本也不会删掉唯一外部对象。
            if node is None or node.body is None:
                raise ConfigError("隔离对象不支持有界副本恢复，已保留实际对象")
            stage(slot, candidate, node.body, stat.S_IMODE(node.identity[2]))
            return link_candidate(slot, candidate, target)

        try:
            for parent in sorted({item.path.parent for item in changes}, key=str):
                handle = stack.enter_context(directory(parent))
                try:
                    fcntl.flock(handle.fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError as exc:
                    raise ConflictError("原生 Agent 配置正在被另一保存修改") from exc
                handles[parent] = handle
            guard()
            for item in changes:
                if _read_at(handles[item.path.parent].fd, item.path.name) != item.before:
                    raise ConflictError("原生 Agent 在预览后变化")
            for item in changes:
                parent = handles[item.path.parent].fd
                name = ".native-config-" + secrets.token_hex(16) + ".hold"
                os.mkdir(name, 0o700, dir_fd=parent)
                descriptor = os.open(name, _DIR_FLAGS, dir_fd=parent)
                stack.callback(os.close, descriptor)
                slot = _Staged(name, parent, descriptor, set(), {})
                prepared[item.role] = slot
                stage(slot, "candidate.new", item.after, stat.S_IMODE(item.before.identity[2]))
                stage(slot, "before.backup", item.before.body)
            guard()
            for item in changes:
                slot = prepared[item.role]
                for check in changes:
                    expected = published.get(check.role, check.before)
                    if _read_at(handles[check.path.parent].fd, check.path.name) != expected:
                        raise ConflictError("原生 Agent 在批量提交期间变化")
                for handle in handles.values():
                    handle.check()
                actual = capture(slot, item.path.name, "before")
                if not _same_after_move(actual, item.before):
                    raise ConflictError("实际隔离的目标不是预览前像，已保留外部对象")
                os.fsync(slot.descriptor)
                os.fsync(slot.parent)
                link_candidate(slot, "candidate.new", item.path.name, item=item)
                os.fsync(slot.parent)
            for handle in handles.values():
                handle.check()
            result["saved"] = True
        except (OSError, ValueError) as exc:
            if isinstance(exc, ConflictError) and not result["namespace_touched"]:
                raise
            failure = type(exc).__name__
            result["partial_failure"] = bool(published)
            for item in reversed(changes):
                slot = prepared.get(item.role)
                if slot is None or "before" not in slot.captures:
                    continue
                try:
                    if item.role in published:
                        actual = capture(slot, item.path.name, "rollback")
                        if not _same_after_move(actual, published[item.role]):
                            # 回滚隔离也可能恰好捕获外部新保存；只排他恢复其副本，
                            # 保留实际 inode，不把它误当成本服务发布后可丢弃的内容。
                            statuses[item.role] = "rollback_conflict"
                            restore_copy(slot, item.path.name, actual, "external-return.new")
                            continue
                        restore_copy(slot, item.path.name, item.before, "restore.new")
                    else:
                        actual = slot.captures["before"]
                        if actual is None or not _same_after_move(actual, item.before):
                            statuses[item.role] = "rollback_conflict"
                            restore_copy(slot, item.path.name, actual, "external-return.new")
                            continue
                        # 首次发布被新目标阻止时，此 link 同样会拒绝覆盖；前像保留。
                        restore_copy(slot, item.path.name, item.before, "restore.new")
                    statuses[item.role] = "rolled_back"
                    os.fsync(slot.parent)
                except (OSError, ValueError) as restore_failure:
                    statuses[item.role] = ("rollback_conflict" if isinstance(restore_failure, (ConflictError, FileExistsError))
                                           or statuses[item.role] == "rollback_conflict" else "recovery_required")
        finally:
            for item in changes:
                slot = prepared.get(item.role)
                if slot is None:
                    continue
                # 是否保留仅取决于是否真正隔离过对象，不能以 saved/回滚结果
                # 判断旧 fd 已关闭。成功路径同样保留固定预览副本和实际原 inode。
                keep = bool(slot.captures)
                for name in tuple(slot.temporary):
                    if keep and name == "before.backup":
                        result["recovery"].append({"role": item.role, "target": str(item.path),
                            "backup": str(item.path.parent / slot.name / name),
                            "sha256": hashlib.sha256(item.before.body).hexdigest(), "kind": "preview_preimage",
                            "sha256_semantics": "immutable_preview_bytes", "content_may_change": False,
                            "retention": "until_explicit_safe_cleanup_contract"})
                        continue
                    try:
                        os.unlink(name, dir_fd=slot.descriptor)
                    except FileNotFoundError:
                        pass
                    except OSError:
                        result.setdefault("cleanup_pending", []).append(str(item.path.parent / slot.name / name))
                for name, node in slot.captures.items():
                    # 这些是真实对象，不能进入临时副本的 unlink 清理。chmod 不会
                    # 撤销已打开 fd 的写权限；保留路径才能接住返回后才发生的写入。
                    if node is not None:
                        try:
                            descriptor = os.open(name, _READ_FLAGS, dir_fd=slot.descriptor)
                            with os.fdopen(descriptor, "rb") as stream:
                                os.fchmod(stream.fileno(), 0o600)
                        except OSError:
                            pass
                    result["recovery"].append({"role": item.role, "target": str(item.path),
                        "backup": str(item.path.parent / slot.name / name),
                        "sha256": hashlib.sha256(node.body).hexdigest() if node is not None else None,
                        "sha256_semantics": "observed_at_isolation_not_current", "content_may_change": True,
                        "observed_identity": list(node.identity) if node is not None else None,
                        "object_role": "target_at_initial_isolation" if name == "before" else "target_at_rollback_isolation",
                        "kind": "isolated_object", "container_mode": 0o700,
                        "original_mode": stat.S_IMODE(node.identity[2]) if node is not None else None,
                        "retention": "until_explicit_safe_cleanup_contract"})
                if not keep:
                    try:
                        os.rmdir(slot.name, dir_fd=slot.parent)
                    except OSError:
                        result.setdefault("cleanup_pending", []).append(str(item.path.parent / slot.name))
    result["results"] = [{"role": item.role, "status": statuses[item.role]} for item in changes]
    if failure:
        result["error"] = "Native file batch save failed; external objects were not overwritten. Inspect per-agent results and retained recovery files."
        result["error_type"] = failure
    return result
