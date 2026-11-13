"""有界、不跟随链接的模型文件快照和条件原子写入。"""

from __future__ import annotations

from contextlib import ExitStack, contextmanager
from dataclasses import dataclass
import ctypes
import errno
import fcntl
import hashlib
import os
from pathlib import Path
import secrets
import stat
import sys
from typing import Callable

from .contracts import ConfigError, ConflictError, MAX_FILE_BYTES as MAX_BYTES, absolute_path


_DIR_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0)
_READ_FLAGS = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | getattr(os, "O_CLOEXEC", 0)


def _rename_directory_exclusive(parent, source, destination):
    """使用宿主的排他 rename 发布目录，禁止覆盖抢先出现的空目录。

    mkdir 后重新按名字 open 无法证明打开的是自己创建的目录；先持有随机
    私有目录 inode，再以内核 no-replace 语义发布固定名字，才能关闭这个
    首次创建窗口。macOS/Linux 均使用标准 libc；不支持时失败关闭，不退回
    可覆盖的 os.rename。Windows 本轮不在支持范围。
    """
    libc = ctypes.CDLL(None, use_errno=True)
    function = getattr(libc, "renameatx_np" if sys.platform == "darwin" else "renameat2", None)
    if function is None:
        raise OSError(errno.ENOTSUP, "exclusive directory publication unavailable")
    function.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
    function.restype = ctypes.c_int
    if function(parent, os.fsencode(source), parent, os.fsencode(destination), 4 if sys.platform == "darwin" else 1):
        code = ctypes.get_errno()
        raise OSError(code, "exclusive directory publication failed")


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
        # 只记录目录上下文正常退出时的观察，不能用发布前的 check 推断收尾位置。
        # 若某个目录退出抛错，ExitStack 仍会关闭其余描述符；未完成退出检查的
        # 目录保持 False，收据不得继续把旧绝对路径当作可定位的恢复资料。
        self.exit_verified = False

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
        handle.exit_verified = True
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


def directory_stamp(path: Path) -> tuple:
    """记录完整目录链（含缺失边界），不创建目录也不使用 mtime 充当身份。

    本服务 staging 会改变目录时间；稳定身份只含 dev/ino/权限/属主。
    缺失边界也进入前像；实际创建仅由服务端固定目标的写计划授权，逐级排他发布。
    """
    path = absolute_path(path)
    with directory(path.anchor) as handle:
        result = []
        descriptors, links = [], []
        parent = handle.fd
        def checked(value):
            for descriptor, name, expected in links:
                current = os.stat(name, dir_fd=descriptor, follow_symlinks=False)
                if not stat.S_ISDIR(current.st_mode) or (current.st_dev, current.st_ino) != expected:
                    raise ConflictError("配置父目录在观察期间变化")
            return value
        try:
            for index, name in enumerate(path.parts[1:]):
                try:
                    info = os.stat(name, dir_fd=parent, follow_symlinks=False)
                except FileNotFoundError:
                    result.append((name, None))
                    result.extend((part, None) for part in path.parts[index + 2:])
                    return checked(tuple(result))
                if not stat.S_ISDIR(info.st_mode):
                    raise ConfigError("配置父路径不能是链接或特殊节点")
                descriptor = os.open(name, _DIR_FLAGS, dir_fd=parent)
                descriptors.append(descriptor)
                actual = os.fstat(descriptor)
                if (actual.st_dev, actual.st_ino) != (info.st_dev, info.st_ino):
                    raise ConflictError("配置父目录在观察时变化")
                result.append((name, info.st_dev, info.st_ino, info.st_mode, info.st_uid))
                links.append((parent, name, (info.st_dev, info.st_ino)))
                parent = descriptor
            return checked(tuple(result))
        finally:
            for descriptor in reversed(descriptors):
                os.close(descriptor)



@dataclass(frozen=True)
class Write:
    """批量计划的一项精确前后像；路径只能来自服务端原生清单。"""
    role: str
    path: Path
    before: Snapshot
    after: bytes
    parent_stamp: tuple = ()



@dataclass
class _Staged:
    """私有隔离目录保存真实 inode；恢复副本与实际外部对象分别留存。"""
    name: str
    parent: int
    descriptor: int
    temporary: set
    captures: dict
    container_identity: tuple
    preview_identity: tuple = ()


@contextmanager
def _batch_directories(result):
    """让目录退出与 fd 清理也进入保存结算，保留已发生的发布事实。

    ExitStack 的 __exit__ 在批量主体及保留资料 finally 之后运行。它可能
    检出父目录移动，此时目标已经发布、原 inode 和前像也已留下，不能再
    只抛普通冲突使调用方丢失全部收据；也不能在描述符已关闭后假装回滚。
    尚未动过公共名字的冲突仍按原合同抛出，由调用方重新读取并预览。
    """
    try:
        with ExitStack() as stack:
            yield stack
    except (OSError, ValueError) as exc:
        if not result["namespace_touched"]:
            raise
        result.update(saved=False, partial_failure=result["published"],
                      finalization_failed=True, finalization_error_type=type(exc).__name__)


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
    prepared, published, retained_locations = {}, {}, {}
    statuses = {item.role: "not_written" for item in changes}
    failure = None
    with _batch_directories(result) as stack:
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
                return _identity(os.fstat(stream.fileno()))

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
                result["namespace_touched"] = True
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

        def verify_retained_names():
            # 该回调最后注册、最先退出，因此保留资料 finally 已完成，而父目录
            # 与隔离目录 fd 仍有效。仅父目录链未变不足以证明完整 backup 路径：
            # .hold 自身或其中的对象名称可能已被移动，甚至被同字节对象替换。
            # 每一条声明必须同时对应持有的容器和观察到的对象 dev/ino；只按
            # 原名称 no-follow 核对，不扫描新位置，也不修改/清理任何失联对象。
            for entry in result["recovery"]:
                slot = prepared[entry["role"]]
                identity = entry["observed_identity"]
                verified = False
                try:
                    container = os.stat(slot.name, dir_fd=slot.parent, follow_symlinks=False)
                    node = os.stat(Path(entry["backup"]).name, dir_fd=slot.descriptor, follow_symlinks=False)
                    verified = (stat.S_ISDIR(container.st_mode)
                                and (container.st_dev, container.st_ino) == slot.container_identity
                                and stat.S_ISREG(node.st_mode) and identity is not None
                                and (node.st_dev, node.st_ino) == tuple(identity[:2]))
                except OSError:
                    # 无法核实只是位置未知，不能抹掉已成功发布的目标或观察身份。
                    # 后续目录退出若另有异常，仍由外层结算保留其独立失败收据。
                    pass
                retained_locations[entry["backup"]] = verified

        try:
            # 新文件也复用同一事务。先验证预览目录链，再在既有父目录锁下
            # mkdir（不接受外部抢先创建），绝不覆盖外部新出现的配置文件。
            guard()
            for parent in sorted({item.path.parent for item in changes}, key=str):
                expected = next(item.parent_stamp for item in changes if item.path.parent == parent)
                if expected and directory_stamp(parent) != expected:
                    raise ConflictError("配置父目录在预览后变化")
                created_identity = None
                if expected and expected[-1][1] is None:
                    # 固定宿主偏好路径允许首次缺少多级目录，但每一级都在最近既有
                    # 祖先的排他锁下发布私有 inode。绝不 mkdir 后盲目接受抢先出现
                    # 的同名目录；每步保留 fd/祖先链，路径被换位就拒绝后续写入。
                    missing_index = next(index for index, entry in enumerate(expected) if entry[1] is None)
                    anchor_path = Path(parent.anchor).joinpath(*(entry[0] for entry in expected[:missing_index]))
                    anchor = stack.enter_context(directory(anchor_path))
                    fcntl.flock(anchor.fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    if directory_stamp(parent) != expected:
                        raise ConflictError("配置父目录在首次创建前变化")
                    for entry in expected[missing_index:]:
                        temporary = ".native-config-" + secrets.token_hex(16) + ".new"
                        os.mkdir(temporary, 0o700, dir_fd=anchor.fd)
                        created_fd = os.open(temporary, _DIR_FLAGS, dir_fd=anchor.fd)
                        stack.callback(os.close, created_fd)
                        created_identity = os.fstat(created_fd)
                        try:
                            _rename_directory_exclusive(anchor.fd, temporary, entry[0])
                            result["namespace_touched"] = True
                            anchor_path = anchor_path / entry[0]
                            result.setdefault("created_directories", []).append(str(anchor_path))
                            os.fsync(anchor.fd)
                        except FileExistsError as exc:
                            raise ConflictError("配置父目录已由外部创建") from exc
                        finally:
                            try:
                                info = os.stat(temporary, dir_fd=anchor.fd, follow_symlinks=False)
                                if (info.st_dev, info.st_ino) == (created_identity.st_dev, created_identity.st_ino):
                                    os.rmdir(temporary, dir_fd=anchor.fd)
                            except FileNotFoundError:
                                pass
                        anchor.check()
                        published_info = os.stat(entry[0], dir_fd=anchor.fd, follow_symlinks=False)
                        if (published_info.st_dev, published_info.st_ino) != (created_identity.st_dev, created_identity.st_ino):
                            raise ConflictError("首次创建的配置父目录已换位")
                        anchor = stack.enter_context(directory(anchor_path))
                        opened = os.fstat(anchor.fd)
                        if (opened.st_dev, opened.st_ino) != (created_identity.st_dev, created_identity.st_ino):
                            raise ConflictError("首次创建的配置父目录在打开前换位")
                handle = stack.enter_context(directory(parent))
                if created_identity is not None:
                    opened = os.fstat(handle.fd)
                    if (opened.st_dev, opened.st_ino) != (created_identity.st_dev, created_identity.st_ino):
                        raise ConflictError("首次创建的配置父目录在打开前换位")
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
                observed = os.fstat(descriptor)
                slot = _Staged(name, parent, descriptor, set(), {}, (observed.st_dev, observed.st_ino))
                prepared[item.role] = slot
                stage(slot, "candidate.new", item.after, stat.S_IMODE(item.before.identity[2]) if item.before.identity else 0o600)
                if item.before.body is not None:
                    slot.preview_identity = stage(slot, "before.backup", item.before.body)
            stack.callback(verify_retained_names)
            guard()
            for item in changes:
                slot = prepared[item.role]
                for check in changes:
                    expected = published.get(check.role, check.before)
                    if _read_at(handles[check.path.parent].fd, check.path.name) != expected:
                        raise ConflictError("原生 Agent 在批量提交期间变化")
                for handle in handles.values():
                    handle.check()
                if item.before.body is not None:
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
                if slot is not None and item.before.body is None and item.role in published:
                    # 首次创建没有前像可恢复。保留已发布对象和实际位置，避免
                    # 为“回滚到缺失”而删除并发编辑者已经打开/更新的唯一文件。
                    statuses[item.role] = "recovery_required"
                    continue
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
                            "observed_identity": list(slot.preview_identity),
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
    # 此时所有目录上下文及 fd 清理回调均已执行；合并父目录链与保留名称核验，
    # 不递归扫描用户目录、猜测 rename 后的位置，也不把旧绝对路径伪称当前位置。
    # dev/ino 是退出前持有的真实容器/对象观察身份；它们只供人工核对，不是定位器。
    by_role = {item.role: item for item in changes}
    for entry in result["recovery"]:
        item = by_role[entry["role"]]
        entry["declared_backup"] = entry["backup"]
        entry["container_identity"] = list(prepared[item.role].container_identity)
        verified = handles[item.path.parent].exit_verified and retained_locations.get(entry["backup"], False)
        entry["location_status"] = "verified_at_finalization" if verified else "unknown"
        if not verified:
            entry["backup"] = None
    for item in changes:
        handle = handles.get(item.path.parent)
        if handle is None or not handle.exit_verified:
            statuses[item.role] = {"saved": "published_location_unknown",
                                   "rolled_back": "rolled_back_location_unknown"}.get(statuses[item.role], statuses[item.role])
    if result.get("cleanup_pending"):
        result["cleanup_pending_location_status"] = ("verified_at_finalization" if all(
            handle.exit_verified for handle in handles.values()) else "unknown")
    if result.get("finalization_failed"):
        failure = failure or result["finalization_error_type"]
    result["results"] = [{"role": item.role, "status": statuses[item.role]} for item in changes]
    created = [item for item in changes if item.before.body is None]
    if created:
        result["created_files"] = []
        for item in created:
            node = published.get(item.role)
            verified = False
            if node is not None and handles.get(item.path.parent) and handles[item.path.parent].exit_verified:
                try:
                    actual = read(item.path)
                    verified = actual.identity[:2] == node.identity[:2]
                except (OSError, ValueError):
                    pass
            result["created_files"].append({"role": item.role, "target": str(item.path), "before_absent": True,
                                           "published": item.role in published,
                                           "observed_identity": list(node.identity) if node is not None else None,
                                           "location_status": "verified_at_finalization" if verified else "unknown",
                                           "recovery_action": "保留实际发布对象，核对内容后通过新预览修改；不会自动删除首次创建的文件。"})
    if failure:
        result["error"] = "Native file batch save failed; external objects were not overwritten. Inspect per-agent results and retained recovery files."
        result["error_type"] = failure
    return result
