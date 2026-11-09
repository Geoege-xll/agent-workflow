"""管理器共用的安全文件与锁所有者，不含登记或模型业务。

原有逐段拒绝链接、固定父目录描述符、排他发布及旧 inode 保留合同集中于此。
业务服务仍决定事务边界与锁序；这里不改用 Tree，也不把持锁误当成外部编辑
已被禁止，发布前后的精确字节/权限核对及异常保全继续由原实现负责。
"""

from __future__ import annotations

from contextlib import contextmanager
import hashlib
from lib.platform_fs import os, directory_lock
from pathlib import Path
import stat
import uuid

from lib import runtime_store
from lib.central.runtime_project import Node, read_at, move_at, publish_at, clone_file_permissions, delete_at, content_mode


def same_file_state(actual: tuple, expected: tuple) -> bool:
    """只比较计划正文与内容 mode 投影；不能替代真实 Node/ACL/身份的前像守卫。"""
    if actual[0] != expected[0]:
        return False
    if actual[1] is None or expected[1] is None:
        return actual[1] == expected[1]
    return content_mode(actual[1]) == content_mode(expected[1])


class PreservedEdit(ValueError):
    """隔离文件含其他编辑，必须显式进入冲突日志，不能宣告应用成功。"""
    def __init__(self,path: Path):
        self.retained_path=str(path)
        super().__init__("检测到旧文件版本的后续保存或权限变化，保留版本："+str(path))


class AnchoredFile:
    """固定父目录描述符发布文件，关闭检查路径后目录被换成链接的写出边界。

    所有目录逐段 O_NOFOLLOW 打开；后续读取、临时文件及 replace 都使用同一个
    dir_fd。即使路径在事务中被重命名，也不会沿新链接覆盖项目外的同名文件。
    事务期间保留描述符，回滚仍可定位本轮实际修改的原文件。
    """
    def __init__(self, root: Path, relative: str):
        secure_path(root,relative)
        absolute=root/relative
        self.path=absolute
        self.retainer=None
        descriptor=os.open(absolute.anchor,os.O_RDONLY|os.O_DIRECTORY|os.O_CLOEXEC)
        try:
            for part in absolute.parent.parts[1:]:
                following=os.open(part,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW|os.O_CLOEXEC,dir_fd=descriptor)
                os.close(descriptor);descriptor=following
        except BaseException:
            os.close(descriptor);raise
        self.directory=descriptor;self.name=absolute.name

    def __enter__(self):return self
    def __exit__(self,*_):os.close(self.directory)

    def read(self,name=None):
        if os.name == "nt":
            snapshot = read_at(self.directory, name or self.name)
            return ((None, None) if snapshot.kind == "missing" else (snapshot.payload, snapshot.mode))
        try:
            descriptor=os.open(name or self.name,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK|os.O_CLOEXEC,dir_fd=self.directory)
        except FileNotFoundError:return None,None
        try:
            info=os.fstat(descriptor)
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size>4*1024*1024:
                raise ValueError("管理目标不是有界独占普通文件")
            with os.fdopen(descriptor,"rb",closefd=False) as stream:data=stream.read(4*1024*1024+1)
            if len(data)>4*1024*1024:raise ValueError("管理目标超过读取范围")
            return data,stat.S_IMODE(info.st_mode)
        finally:os.close(descriptor)

    def write(self,data: bytes,mode: int,expected=None):
        if os.name == "nt":
            return self._write_windows(data, mode, expected)
        temporary=".workflow-models-"+uuid.uuid4().hex+".tmp"
        previous=None
        if expected is None:expected=self.read()
        descriptor=os.open(temporary,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW|os.O_CLOEXEC,0o600,dir_fd=self.directory)
        try:
            with os.fdopen(descriptor,"wb") as stream:
                stream.write(data);stream.flush();os.fchmod(stream.fileno(),mode);os.fsync(stream.fileno())
            # 临时文件完全就绪后再核对，避免磁盘写入期间的编辑被最后一次 replace 吞掉。
            if expected is not None and self.read() != expected:
                raise ValueError("文件在发布前发生其他修改，停止覆盖")
            if expected[0] is not None:
                # 隔离旧目标后重新核验：最后一次检查与移动之间保存的内容也会被发现。
                previous=".workflow-models-previous-"+uuid.uuid4().hex+".tmp"
                os.rename(self.name,previous,src_dir_fd=self.directory,dst_dir_fd=self.directory)
                if self.read(previous) != expected:
                    raise ValueError("文件在最终发布时发生其他修改，停止覆盖")
            # link 是排他创建：目标在隔离后被其他编辑器重新保存时，绝不替换新文件。
            os.link(temporary,self.name,src_dir_fd=self.directory,dst_dir_fd=self.directory,follow_symlinks=False)
        except BaseException:
            if previous is not None:
                try:
                    os.link(previous,self.name,src_dir_fd=self.directory,dst_dir_fd=self.directory,follow_symlinks=False)
                    # 恢复成功后立即去掉临时硬链接，保持目标 nlink=1 的受管读取合同。
                    os.unlink(previous,dir_fd=self.directory)
                    previous=None
                except FileExistsError:
                    # 对方已经新建目标，保留它；若隔离文件也有新增内容则保留供人工核对。
                    if self.read(previous) != expected:
                        raise PreservedEdit(self.path.parent/previous)
                except FileNotFoundError:
                    previous=None
            raise
        finally:
            try:os.unlink(temporary,dir_fd=self.directory)
            except FileNotFoundError:pass
            if previous is not None and self.retainer is not None:
                # 永久保留旧 inode；持有旧 fd 的编辑器即便稍后保存也仍有可找回路径。
                self.retainer(self,previous,expected)
                previous=None
            if previous is not None:
                # 出现双侧新内容时必须保留隔离文件，不能为清理临时文件而丢编辑。
                try:
                    prior=self.read(previous)
                    if prior == expected or self.read(self.name) == prior:
                        os.unlink(previous,dir_fd=self.directory)
                    else:
                        raise PreservedEdit(self.path.parent/previous)
                except PreservedEdit:raise
                except (OSError,ValueError) as exc:
                    raise PreservedEdit(self.path.parent/previous) from exc

    def _write_windows(self, data: bytes, mode: int, expected):
        """同父目录私有暂存，完整前像隔离与 no-replace 消费发布。

        外层历史 tuple API 保持不变；本次操作额外冻结真实 Node/ACL，临时文件
        完成后必须仍等于此完整前像。原 inode 保留器与异常资料归属不改变。
        """
        before = read_at(self.directory, self.name)
        pair = (None, None) if before.kind == "missing" else (before.payload, before.mode)
        if expected is not None and not same_file_state(pair, expected):
            raise ValueError("文件在发布前发生其他修改，停止覆盖")
        temporary = ".workflow-models-" + uuid.uuid4().hex + ".tmp"
        previous = None
        staged = None
        try:
            descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                                 0o600, dir_fd=self.directory)
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(data); stream.flush()
                os.fchmod(stream.fileno(), mode); os.fsync(stream.fileno())
            if before.kind == "file":
                clone_file_permissions(self.directory, self.name, temporary)
            staged = read_at(self.directory, temporary)
            if read_at(self.directory, self.name) != before:
                raise ValueError("文件在发布前发生其他修改，停止覆盖")
            if before.kind != "missing":
                previous = ".workflow-models-previous-" + uuid.uuid4().hex + ".tmp"
                move_at(self.name, previous, src_dir_fd=self.directory, dst_dir_fd=self.directory, expected=before)
                held = read_at(self.directory, previous)
                if (not held.same_content(before) or held.mode != before.mode or held.security != before.security
                        or held.identity[:2] != before.identity[:2] or held.identity[4:6] != before.identity[4:6]):
                    raise PreservedEdit(self.path.parent / previous)
                self.retained_snapshot = held
            publish_at(temporary, self.name, src_dir_fd=self.directory, dst_dir_fd=self.directory, expected=staged)
            os.fsync(self.directory)
        except BaseException:
            if previous is not None:
                held = read_at(self.directory, previous)
                # rename 改 ctime，但旧 inode、正文、mtime、mode 与独立 ACL 必须相同。
                if (held.same_content(before) and held.identity[:2] == before.identity[:2]
                        and held.identity[4:6] == before.identity[4:6] and held.security == before.security):
                    try:
                        publish_at(previous, self.name, src_dir_fd=self.directory,
                                   dst_dir_fd=self.directory, expected=held)
                    except FileExistsError:
                        pass
                    else:
                        previous = None
                else:
                    raise PreservedEdit(self.path.parent / previous)
            raise
        finally:
            # 已消费的 stage 不再 unlink；失败残留只在仍是本次完整快照时删除。
            if staged is not None and read_at(self.directory, temporary) == staged:
                delete_at(self.directory, temporary, expected=staged)
            if previous is not None:
                if self.retainer is not None:
                    # 原冻结的隔离 Node 交给归档消费者；它不能即时读取后重新认领
                    # 一个后来保存的同名文件。真实移动仍在同句柄复核这份 expected。
                    self.retainer(self, previous, pair)
                else:
                    held = read_at(self.directory, previous)
                    if (held.same_content(before) and held.identity[:2] == before.identity[:2]
                            and held.security == before.security):
                        delete_at(self.directory, previous, expected=held)
                    else:
                        raise PreservedEdit(self.path.parent / previous)



def write_state(root: Path,relative: str,data: bytes) -> None:
    with AnchoredFile(root,relative) as target:
        previous=target.read()  # 同样拒绝已有链接、硬链接或特殊文件。
        target.write(data,0o600,previous)


def secure_path(root: Path, relative: str) -> Path:
    """项目内所有读写逐段拒绝链接，避免借管理操作修改另一个项目。"""
    parts = Path(relative).parts
    if not parts or Path(relative).is_absolute() or ".." in parts:
        raise ValueError("管理路径必须是项目内相对路径")
    current = root
    for part in parts:
        current /= part
        if current.is_symlink():
            raise ValueError(f"管理路径不接受符号链接：{current}")
    return current


def project_path(raw: str | Path) -> Path:
    path = Path(raw).expanduser()
    if path.is_symlink() or not path.is_dir():
        raise ValueError("项目必须是已存在的普通目录")
    from lib.central.runtime_project import canonical_project
    return canonical_project(path)


def state_root(raw: str | Path | None = None) -> Path:
    """沿用中央库唯一状态目录解析；只解析，查询和预览不会创建状态。"""
    return runtime_store.state_root(raw)


def writable_directory(path: Path) -> None:
    """仅在实际保存时创建管理目录；列出项目和模型时不产生状态文件。"""
    for component in (path, *path.parents):
        if component.is_symlink():
            raise ValueError(f"状态目录不可经过符号链接：{component}")
    if os.name == "nt":
        with runtime_store._absolute_directory(path, create=True):
            pass
    else:
        path.mkdir(parents=True, exist_ok=True, mode=0o700)


@contextmanager
def lock(state: Path, identifier: str):
    directory = state/"locks"
    writable_directory(directory)
    path = secure_path(directory, hashlib.sha256(identifier.encode()).hexdigest()+".lock")
    # Windows 使用已验证 owner/DACL 的跨 session 目录互斥；不导入 POSIX fcntl。
    # identifier 单独建目录会改变历史状态结构，因此沿现有锁文件名字作为 purpose。
    if os.name == "nt":
        with directory_lock(directory, str(path.name)):
            yield
        return
    import fcntl
    descriptor = os.open(path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise ValueError("管理锁不是独占普通文件")
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise ValueError("该项目正在由另一管理操作更新，请稍后重试") from exc
        yield
    finally:
        os.close(descriptor)
