"""中央内容库：导入通用核心、固定内容版本，并在读取时验证完整快照。

库只拥有机器状态目录下的 ``runtimes``，不登记项目、不执行安装脚本，也不
改变宿主权限或模型设置。内容摘要证明字节完整性，并不证明来源可信；POSIX
只读位仅用于防止误写，同一用户仍能主动修改它们。所有版本默认保留。
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re
import stat
import sys
import uuid

if __package__:
    from .platform_fs import directory_lock, os, publish_exclusive
else:
    from platform_fs import directory_lock, os, publish_exclusive


PROTOCOL_VERSION = 1
# 与既有项目安装入口对应；中央管理器本身也需要冻结，故另外纳入 manager。
# project.yaml 属于项目所有者，不能借中央快照复制其中的模型、权限或个人配置。
CORE_DIRECTORIES = ("product", "roles", "platforms", "lib", "scripts", "templates", "manager")
SETUP_FILES = ("setup_all.sh", "setup_claude.sh", "setup_codex.sh", "setup_antigravity.sh")
_DIGEST = re.compile(r"[0-9a-f]{64}", re.ASCII)
_VERSION = re.compile(r"(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)", re.ASCII)
_STAGE = re.compile(r"\.import-[0-9a-f]{32}", re.ASCII)
_MANIFEST_LIMIT = 4 * 1024 * 1024
# 沿用既有 Windows 安全文件边界的上限；流式逐文件处理，不在内存聚合整个包。
_FILE_LIMIT = 128 * 1024 * 1024
_DIRECTORY_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0)
_READ_FLAGS = os.O_RDONLY | os.O_NOFOLLOW | getattr(os, "O_NONBLOCK", 0) | getattr(os, "O_CLOEXEC", 0)


class RuntimeStoreError(ValueError):
    """固定版本不存在、损坏，或输入跨越了内容库的安全边界。"""


@dataclass(frozen=True)
class FrozenCore:
    """已验证核心的不可变定位值；root 是实际的 core 目录，而非下载源。"""

    content_id: str
    manifest_sha256: str
    root: Path
    label: str

    def binding(self) -> dict:
        """返回可写入项目或任务 pin 的最小 JSON 合同，不暴露机器绝对路径。"""
        return validate_binding({
            "protocol_version": PROTOCOL_VERSION,
            "content_id": self.content_id,
            "manifest_sha256": self.manifest_sha256,
        })


def state_root(raw: str | Path | None = None) -> Path:
    """只解析状态路径，绝不创建目录；不 resolve 掉待检查的危险链接。"""
    value = raw if raw is not None else os.environ.get(
        "AGENT_WORKFLOW_STATE_DIR", Path.home() / ".config" / "agent-workflow"
    )
    if not isinstance(value, (str, Path)) or not str(value):
        raise RuntimeStoreError("中央状态目录必须是非空路径")
    return Path(value).expanduser().absolute()


def validate_binding(binding: dict) -> dict:
    """严格校验协议 1 的 pin，并返回独立副本；额外路径字段不能进入加载合同。"""
    keys = {"protocol_version", "content_id", "manifest_sha256"}
    if (not isinstance(binding, dict) or set(binding) != keys
            or type(binding["protocol_version"]) is not int
            or binding["protocol_version"] != PROTOCOL_VERSION):
        raise RuntimeStoreError("核心绑定只接受协议 1 的三个固定字段")
    for key in ("content_id", "manifest_sha256"):
        if not isinstance(binding[key], str) or not _DIGEST.fullmatch(binding[key]):
            raise RuntimeStoreError(f"核心绑定的 {key} 必须是小写 SHA256")
    if binding["content_id"] != binding["manifest_sha256"]:
        raise RuntimeStoreError("核心内容 ID 与原始清单摘要不一致")
    return dict(binding)


def _identity(info) -> tuple:
    # atime 会因正常读取改变；其余字段共同识别替换、权限变更、原地写入及硬链变化。
    return (info.st_dev, info.st_ino, info.st_mode, info.st_nlink, info.st_size,
            info.st_mtime_ns, info.st_ctime_ns)


def _node_identity(info) -> tuple:
    return info.st_dev, info.st_ino


def _component(name: str) -> None:
    # 使用跨平台一致的规范拼写，避免 POSIX 接受的路径在 Windows 被截断或解释为 ADS。
    stem = name.partition(".")[0].upper()
    if (not name or name in {".", ".."} or name.rstrip(" .") != name
            or any(ord(char) < 32 or char in '/\\:<>"|?*' for char in name)
            or stem in {"CON", "PRN", "AUX", "NUL"}
            or (len(stem) == 4 and stem[:3] in {"COM", "LPT"} and stem[3] in "123456789¹²³")):
        raise RuntimeStoreError(f"核心路径含有不规范分量：{name!r}")


def _logical_path(raw: str, *, alias: bool = False) -> str:
    if not isinstance(raw, str):
        raise RuntimeStoreError("核心逻辑路径必须是字符串")
    # 只剥离一次精确前缀，不能把 .agent-workflow-other 或重复前缀当作别名。
    if alias and raw.startswith(".agent-workflow/"):
        raw = raw[len(".agent-workflow/"):]
    for name in raw.split("/"):
        _component(name)
    return raw


def _included(relative: str) -> bool:
    parts = relative.split("/")
    if any(part.startswith(".") or part in {"__pycache__", "tests"} for part in parts):
        return False
    name = parts[-1]
    if name.endswith((".pyc", ".pyo")) or name in {"project.yaml", "windows-runtime.paths"}:
        return False
    # scripts 下的宿主回归入口不是运行时依赖；模板和受管规则正文仍是通用载荷。
    if parts[0] == "scripts" and name.startswith("test_"):
        return False
    return parts[0] in CORE_DIRECTORIES or relative in SETUP_FILES


def _check_directory(info, display: str, *, frozen: bool = False) -> None:
    if not stat.S_ISDIR(info.st_mode):
        raise RuntimeStoreError(f"核心目录不能是链接或特殊节点：{display}")
    if frozen and os.name != "nt" and stat.S_IMODE(info.st_mode) != 0o555:
        raise RuntimeStoreError(f"核心目录只读模式已改变：{display}")


@contextmanager
def _child_directory(parent: int, name: str, *, frozen: bool = False):
    _component(name)
    before = os.stat(name, dir_fd=parent, follow_symlinks=False)
    _check_directory(before, name, frozen=frozen)
    descriptor = os.open(name, _DIRECTORY_FLAGS, dir_fd=parent)
    try:
        if _node_identity(os.fstat(descriptor)) != _node_identity(before):
            raise RuntimeStoreError(f"核心目录在打开时被替换：{name}")
        yield descriptor
        current = os.stat(name, dir_fd=parent, follow_symlinks=False)
        if _node_identity(current) != _node_identity(before):
            raise RuntimeStoreError(f"核心目录在操作期间被替换：{name}")
    finally:
        os.close(descriptor)


@contextmanager
def _absolute_directory(path: Path, *, create: bool = False):
    """逐段锚定绝对路径；先拒绝祖先链接，再允许在已锚定父目录内创建。"""
    path = Path(path).expanduser().absolute()
    if ".." in path.parts:
        raise RuntimeStoreError("核心物理路径不能含有上级目录跳转")
    descriptors = []
    links = []
    try:
        descriptor = os.open(path.anchor, _DIRECTORY_FLAGS)
        descriptors.append(descriptor)
        for name in path.parts[1:]:
            _component(name)
            if create:
                try:
                    os.mkdir(name, 0o700, dir_fd=descriptor)
                except FileExistsError:
                    pass  # mkdir 的排他结果仍必须通过下面的节点及身份检查。
                else:
                    # 发布目录自身 fsync 不能替代新祖先目录项的持久化。
                    os.fsync(descriptor)
            before = os.stat(name, dir_fd=descriptor, follow_symlinks=False)
            _check_directory(before, str(path))
            child = os.open(name, _DIRECTORY_FLAGS, dir_fd=descriptor)
            descriptors.append(child)
            if _node_identity(os.fstat(child)) != _node_identity(before):
                raise RuntimeStoreError("核心路径在打开期间被替换")
            links.append((descriptor, name, _node_identity(before)))
            descriptor = child
        yield descriptor
        for parent, name, expected in links:
            if _node_identity(os.stat(name, dir_fd=parent, follow_symlinks=False)) != expected:
                raise RuntimeStoreError("核心路径祖先在操作期间被替换")
    finally:
        for descriptor in reversed(descriptors):
            os.close(descriptor)


def _read_regular(parent: int, name: str, *, limit: int = _FILE_LIMIT, expected=None) -> tuple[bytes, object]:
    _component(name)
    before = os.stat(name, dir_fd=parent, follow_symlinks=False)
    if (not stat.S_ISREG(before.st_mode) or before.st_nlink != 1
            or before.st_mode & 0o7000):
        raise RuntimeStoreError(f"核心文件必须是无特殊权限的单链接普通文件：{name}")
    if expected is not None and _identity(before) != expected:
        raise RuntimeStoreError(f"核心源文件在快照期间变化：{name}")
    if before.st_size > limit:
        raise RuntimeStoreError(f"核心文件超过安全读取上限：{name}")
    descriptor = os.open(name, _READ_FLAGS, dir_fd=parent)
    with os.fdopen(descriptor, "rb") as stream:
        if _identity(os.fstat(stream.fileno())) != _identity(before):
            raise RuntimeStoreError(f"核心文件在打开时变化：{name}")
        body = stream.read(before.st_size + 1)
        after = os.fstat(stream.fileno())
    if (len(body) != before.st_size or _identity(after) != _identity(before)
            or _identity(os.stat(name, dir_fd=parent, follow_symlinks=False)) != _identity(before)):
        raise RuntimeStoreError(f"核心文件在读取期间变化：{name}")
    return body, before


@contextmanager
def _relative_parent(root: int, relative: str):
    parts = _logical_path(relative).split("/")
    opened = []
    descriptor = root
    try:
        for name in parts[:-1]:
            before = os.stat(name, dir_fd=descriptor, follow_symlinks=False)
            _check_directory(before, relative)
            child = os.open(name, _DIRECTORY_FLAGS, dir_fd=descriptor)
            if _node_identity(os.fstat(child)) != _node_identity(before):
                os.close(child)
                raise RuntimeStoreError("核心相对目录在打开时变化")
            opened.append((child, descriptor, name, _node_identity(before)))
            descriptor = child
        yield descriptor, parts[-1]
        for child, parent, name, expected in opened:
            if _node_identity(os.stat(name, dir_fd=parent, follow_symlinks=False)) != expected:
                raise RuntimeStoreError("核心相对目录在操作期间变化")
    finally:
        for child, _, _, _ in reversed(opened):
            os.close(child)


def _scan(root: int, *, source: bool) -> tuple[list[str], list[dict], dict]:
    """源扫描只选择受管边界，库扫描验证全部节点，不能用忽略规则掩盖损坏。"""
    root_info = os.fstat(root)
    _check_directory(root_info, ".", frozen=not source)
    directories, files, identities = [], [], {"": _identity(root_info)}
    seen = set()

    def visit(parent: int, name: str, relative: str) -> None:
        _logical_path(relative)
        info = os.stat(name, dir_fd=parent, follow_symlinks=False)
        # 忽略缓存也先检查节点类型；不会跟随名为 __pycache__ 的链接读取外部内容。
        if not (stat.S_ISDIR(info.st_mode) or stat.S_ISREG(info.st_mode)) or (
                stat.S_ISREG(info.st_mode) and info.st_nlink != 1):
            raise RuntimeStoreError(f"核心载荷包含链接、硬链或特殊节点：{relative}")
        if source and not _included(relative):
            return
        folded = relative.casefold()
        if folded in seen:
            raise RuntimeStoreError(f"核心载荷路径存在跨平台重名：{relative}")
        seen.add(folded)
        identities[relative] = _identity(info)
        if stat.S_ISDIR(info.st_mode):
            _check_directory(info, relative, frozen=not source)
            directories.append(relative)
            with _child_directory(parent, name, frozen=not source) as child:
                for child_name in sorted(os.listdir(child)):
                    visit(child, child_name, f"{relative}/{child_name}")
                if _identity(os.fstat(child)) != _identity(info):
                    raise RuntimeStoreError(f"核心目录在扫描期间变化：{relative}")
        else:
            body, opened = _read_regular(parent, name, expected=identities[relative])
            executable = bool(opened.st_mode & 0o111)
            if not source and os.name != "nt":
                mode = 0o555 if executable else 0o444
                if stat.S_IMODE(opened.st_mode) != mode:
                    raise RuntimeStoreError(f"核心文件只读模式已改变：{relative}")
            files.append({"path": relative, "size": len(body),
                          "sha256": hashlib.sha256(body).hexdigest(), "executable": executable})

    names = (*CORE_DIRECTORIES, *SETUP_FILES) if source else sorted(os.listdir(root))
    for name in names:
        visit(root, name, name)
    if _identity(os.fstat(root)) != identities[""]:
        raise RuntimeStoreError("核心根目录在扫描期间变化")
    return sorted(directories), sorted(files, key=lambda row: row["path"]), identities


def _json(raw: bytes):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise RuntimeStoreError(f"核心 JSON 字段重复：{key}")
            result[key] = value
        return result

    try:
        return json.loads(raw.decode("utf-8", errors="strict"), object_pairs_hook=unique)
    except (UnicodeError, ValueError, RecursionError) as exc:
        raise RuntimeStoreError("核心 JSON 不是有效的 UTF-8 唯一字段对象") from exc


def _label(root: int, files: list[dict]) -> str:
    if not any(row["path"] == "manager/release.json" for row in files):
        return "source"
    with _relative_parent(root, "manager/release.json") as (parent, name):
        raw, _ = _read_regular(parent, name, limit=4096)
    data = _json(raw)
    if (not isinstance(data, dict) or set(data) != {"schema_version", "version"}
            or type(data["schema_version"]) is not int or data["schema_version"] != 1
            or not isinstance(data["version"], str) or not _VERSION.fullmatch(data["version"])):
        raise RuntimeStoreError("manager/release.json 的正式发行标签无效")
    return data["version"]


def _manifest_bytes(manifest: dict) -> bytes:
    return (json.dumps(manifest, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def _validate_manifest(raw: bytes) -> dict:
    manifest = _json(raw)
    if (not isinstance(manifest, dict)
            or set(manifest) != {"protocol_version", "label", "directories", "files"}
            or type(manifest["protocol_version"]) is not int
            or manifest["protocol_version"] != PROTOCOL_VERSION
            or not isinstance(manifest["label"], str)
            or not (manifest["label"] == "source" or _VERSION.fullmatch(manifest["label"]))
            or not isinstance(manifest["directories"], list) or not isinstance(manifest["files"], list)):
        raise RuntimeStoreError("核心清单协议或字段无效")
    directories = manifest["directories"]
    for path in directories:
        if not isinstance(path, str) or not _included(_logical_path(path)):
            raise RuntimeStoreError("核心清单包含边界外目录")
    paths = []
    for row in manifest["files"]:
        if (not isinstance(row, dict) or set(row) != {"path", "size", "sha256", "executable"}
                or not isinstance(row["path"], str) or not _included(_logical_path(row["path"]))
                or type(row["size"]) is not int or not 0 <= row["size"] <= _FILE_LIMIT
                or not isinstance(row["sha256"], str) or not _DIGEST.fullmatch(row["sha256"])
                or type(row["executable"]) is not bool):
            raise RuntimeStoreError("核心清单文件记录无效")
        paths.append(row["path"])
    all_paths = directories + paths
    if (directories != sorted(set(directories)) or paths != sorted(set(paths))
            or len({path.casefold() for path in all_paths}) != len(all_paths)
            or not set(CORE_DIRECTORIES) <= set(directories)
            or not set(SETUP_FILES) <= set(paths)
            or any(path.split("/")[0] not in CORE_DIRECTORIES for path in directories)):
        raise RuntimeStoreError("核心清单路径集合、顺序或必要入口无效")
    for path in all_paths:
        parent = path.rpartition("/")[0]
        if parent and parent not in directories:
            raise RuntimeStoreError("核心清单缺少父目录")
    if _manifest_bytes(manifest) != raw:
        raise RuntimeStoreError("核心清单不是协议规定的规范排序 JSON 字节")
    return manifest


def _source_manifest(source: int) -> tuple[dict, bytes, dict]:
    """预览与导入共用唯一清单算法，避免 UI 预览的 ID 与实际导入发生语义漂移。"""
    directories, files, identities = _scan(source, source=True)
    manifest = {"protocol_version": PROTOCOL_VERSION, "label": _label(source, files),
                "directories": directories, "files": files}
    raw = _manifest_bytes(manifest)
    if len(raw) > _MANIFEST_LIMIT:
        raise RuntimeStoreError("核心清单超过安全读取上限")
    _validate_manifest(raw)
    _verify_snapshot(source, identities)
    return manifest, raw, identities


def inspect_core(source_root: Path) -> dict:
    """纯只读预览来源，返回绑定三字段与 label，不创建 state、暂存或落地 root。"""
    with _absolute_directory(Path(source_root).expanduser().absolute()) as source:
        manifest, raw, _ = _source_manifest(source)
        return {**_binding(hashlib.sha256(raw).hexdigest()), "label": manifest["label"]}


@contextmanager
def _validated_entry(version: Path, binding: dict):
    """保持祖先及核心目录锚定，完整验证后才把描述符交给读取操作。"""
    with _absolute_directory(version) as root:
        version_info = os.fstat(root)
        _check_directory(version_info, str(version), frozen=True)
        if set(os.listdir(root)) != {"core", "manifest.json"}:
            raise RuntimeStoreError("核心版本目录的节点集合已改变")
        raw, info = _read_regular(root, "manifest.json", limit=_MANIFEST_LIMIT)
        if os.name != "nt" and stat.S_IMODE(info.st_mode) != 0o444:
            raise RuntimeStoreError("核心清单只读模式已改变")
        if hashlib.sha256(raw).hexdigest() != binding["manifest_sha256"]:
            raise RuntimeStoreError("核心原始清单摘要不匹配，版本已损坏")
        manifest = _validate_manifest(raw)
        with _child_directory(root, "core", frozen=True) as core:
            directories, files, identities = _scan(core, source=False)
            # Windows 没有 POSIX 可执行位，保留源清单里的执行需求供桥接器使用。
            if os.name == "nt":
                expected = {row["path"]: row["executable"] for row in manifest["files"]}
                for row in files:
                    row["executable"] = expected.get(row["path"], row["executable"])
            if directories != manifest["directories"] or files != manifest["files"]:
                raise RuntimeStoreError("核心完整文件集合或内容与清单不符")
            if _label(core, files) != manifest["label"]:
                raise RuntimeStoreError("核心来源标签与冻结发行元数据不符")
            _verify_snapshot(core, identities)
            yield core, manifest
            # 清单先于内容读取；结束时再次核对其身份及整个快照，避免一次读取中
            # 前后看到两种版本仍返回成功。操作结束后的主动同用户篡改不在防护承诺内。
            if _identity(os.stat("manifest.json", dir_fd=root, follow_symlinks=False)) != _identity(info):
                raise RuntimeStoreError("核心清单在验证期间变化")
            if _identity(os.fstat(root)) != _identity(version_info):
                raise RuntimeStoreError("核心版本目录在验证期间变化")
            _verify_snapshot(core, identities)


def _binding(content_id: str) -> dict:
    return validate_binding({"protocol_version": PROTOCOL_VERSION, "content_id": content_id,
                             "manifest_sha256": content_id})


def load_core(binding: dict, state: Path | None = None) -> FrozenCore:
    """只从固定机器内容库加载 pin；未知或损坏版本立即失败，不寻找最新版。"""
    binding = validate_binding(binding)
    version = state_root(state) / "runtimes" / binding["content_id"]
    try:
        with _validated_entry(version, binding) as (_, manifest):
            return FrozenCore(binding["content_id"], binding["manifest_sha256"],
                              version / "core", manifest["label"])
    except FileNotFoundError as exc:
        raise RuntimeStoreError(f"固定核心版本缺失：{binding['content_id']}") from exc


def list_cores(state: Path | None = None) -> list[dict]:
    """返回按内容 ID 排序的已验证版本；只读查询不会创建状态目录。"""
    runtimes = state_root(state) / "runtimes"
    try:
        with _absolute_directory(runtimes) as root:
            names = sorted(os.listdir(root))
            result = []
            for name in names:
                # 导入暂存目录不是已发布版本；崩溃遗留也不自动删除，更不作为回退源。
                if _STAGE.fullmatch(name):
                    try:
                        info = os.stat(name, dir_fd=root, follow_symlinks=False)
                    except FileNotFoundError:
                        # 另一轮发布或失败回收可在 listdir 之后移除暂存目录；只忽略
                        # 此正常瞬态，不把它扩散成整份版本列表为空。
                        continue
                    _check_directory(info, name)
                    continue
                if not _DIGEST.fullmatch(name):
                    raise RuntimeStoreError("中央版本库存在未知条目")
                core = load_core(_binding(name), state)
                result.append({**core.binding(), "root": str(core.root), "label": core.label})
            return result
    except FileNotFoundError:
        return []


def read_core_source(core: FrozenCore, logical_path: str) -> bytes:
    """仅读取完整验证清单中的规范路径，支持一次精确 .agent-workflow/ 别名。"""
    if not isinstance(core, FrozenCore) or not isinstance(core.root, Path):
        raise RuntimeStoreError("核心读取需要已加载的 FrozenCore")
    binding = core.binding()
    if (not core.root.is_absolute() or core.root.name != "core"
            or core.root.parent.name != core.content_id or core.root.parent.parent.name != "runtimes"):
        raise RuntimeStoreError("核心定位值不是固定内容库目录")
    relative = _logical_path(logical_path, alias=True)
    try:
        with _validated_entry(core.root.parent, binding) as (root, manifest):
            if core.label != manifest["label"]:
                raise RuntimeStoreError("核心定位值的来源标签不匹配")
            record = next((row for row in manifest["files"] if row["path"] == relative), None)
            if record is None:
                raise RuntimeStoreError("逻辑路径不在冻结核心文件清单中")
            with _relative_parent(root, relative) as (parent, name):
                body, info = _read_regular(parent, name)
            if len(body) != record["size"] or hashlib.sha256(body).hexdigest() != record["sha256"]:
                raise RuntimeStoreError("核心文件在验证后发生变化")
            if os.name != "nt" and stat.S_IMODE(info.st_mode) != (0o555 if record["executable"] else 0o444):
                raise RuntimeStoreError("核心文件模式在验证后发生变化")
            return body
    except FileNotFoundError as exc:
        raise RuntimeStoreError("固定核心或其清单文件缺失") from exc


def _write_new(parent: int, name: str, body: bytes, mode: int = 0o600) -> None:
    descriptor = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                         mode, dir_fd=parent)
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(body)
        stream.flush()
        os.fchmod(stream.fileno(), mode)
        os.fsync(stream.fileno())


def _verify_snapshot(root: int, expected: dict) -> None:
    # 比较整个两遍快照的节点身份；仅比较摘要会漏掉改写后恢复同字节的并发输入。
    for relative, identity in expected.items():
        if not relative:
            actual = os.fstat(root)
        else:
            with _relative_parent(root, relative) as (parent, name):
                actual = os.stat(name, dir_fd=parent, follow_symlinks=False)
        if _identity(actual) != identity:
            raise RuntimeStoreError(f"核心快照在操作期间变化：{relative or '.'}")


def _copy_snapshot(source: int, stage: int, manifest: dict, identities: dict) -> None:
    os.mkdir("core", 0o700, dir_fd=stage)
    with _child_directory(stage, "core") as root:
        # 字典序使父目录先于子目录创建；所有目标由本轮排他创建，没有覆盖已有内容。
        for relative in manifest["directories"]:
            with _relative_parent(root, relative) as (parent, name):
                os.mkdir(name, 0o700, dir_fd=parent)
        for row in manifest["files"]:
            relative = row["path"]
            with _relative_parent(source, relative) as (parent, name):
                body, _ = _read_regular(parent, name, expected=identities[relative])
            if len(body) != row["size"] or hashlib.sha256(body).hexdigest() != row["sha256"]:
                raise RuntimeStoreError(f"核心源在复制期间变化：{relative}")
            with _relative_parent(root, relative) as (parent, name):
                mode = (0o555 if row["executable"] else 0o444) if os.name != "nt" else 0o600
                _write_new(parent, name, body, mode)


def _freeze_directories(root: int, paths: list[str]) -> None:
    for relative in sorted(paths, reverse=True):
        with _relative_parent(root, relative) as (parent, name):
            with _child_directory(parent, name) as descriptor:
                if os.name != "nt":
                    os.fchmod(descriptor, 0o555)
                os.fsync(descriptor)
    if os.name != "nt":
        os.fchmod(root, 0o555)
    os.fsync(root)


def _remove_stage(parent: int, name: str, expected: tuple) -> None:
    """只回收本轮 UUID 暂存树；逐段拒绝链接，绝不清理已发布版本。"""
    info = os.stat(name, dir_fd=parent, follow_symlinks=False)
    if _node_identity(info) != expected:
        raise RuntimeStoreError("导入暂存目录身份已改变，保留现场")
    with _child_directory(parent, name) as root:
        if os.name != "nt":
            os.fchmod(root, 0o700)
        for child in os.listdir(root):
            info = os.stat(child, dir_fd=root, follow_symlinks=False)
            if stat.S_ISDIR(info.st_mode):
                _remove_stage(root, child, _node_identity(info))
            elif stat.S_ISREG(info.st_mode) and info.st_nlink == 1:
                os.unlink(child, dir_fd=root)
            else:
                raise RuntimeStoreError("暂存树出现未知链接或特殊节点，保留现场")
    os.rmdir(name, dir_fd=parent)


def import_core(source_root: Path, state: Path | None = None, *, expected_binding: dict | None = None) -> FrozenCore:
    """导入受管源码；可按预览绑定拒绝漂移，同 ID 幂等且不修复既有损坏。

    expected_binding 使用 validate_binding 的三个固定字段；inspect_core 附带的
    label 只用于展示，由消费者投影出这三个字段，不能混入机器路径或其他状态。
    """
    expected = validate_binding(expected_binding) if expected_binding is not None else None
    source_root = Path(source_root).expanduser().absolute()
    runtimes = state_root(state) / "runtimes"
    if source_root == runtimes or source_root.is_relative_to(runtimes) or runtimes.is_relative_to(source_root):
        raise RuntimeStoreError("核心源与中央版本库不能互相包含")
    with _absolute_directory(source_root) as source:
        manifest, raw, identities = _source_manifest(source)
        directories, files = manifest["directories"], manifest["files"]
        content_id = hashlib.sha256(raw).hexdigest()
        binding = _binding(content_id)
        # 对前像的检查早于创建状态及暂存树。后续双遍快照仍会拒绝检查通过后
        # 发生的源变更，不能把预览外的新版本发布成用户刚确认的版本。
        if expected is not None and binding != expected:
            raise RuntimeStoreError("当前核心来源与预览绑定不符，请重新预览后应用")
        with _absolute_directory(runtimes, create=True) as destination:
            stage_name = ".import-" + uuid.uuid4().hex
            os.mkdir(stage_name, 0o700, dir_fd=destination)
            stage_identity = _node_identity(os.stat(stage_name, dir_fd=destination, follow_symlinks=False))
            try:
                with _child_directory(destination, stage_name) as stage:
                    _copy_snapshot(source, stage, manifest, identities)
                    # 清单先在不可见暂存树内排他发布，复用既有跨平台发布语义。
                    _write_new(stage, ".manifest", raw, 0o444 if os.name != "nt" else 0o600)
                    publish_exclusive(runtimes / stage_name / ".manifest", runtimes / stage_name / "manifest.json")
                    _freeze_directories(stage, ["core", *("core/" + path for path in directories)])
                second_directories, second_files, second_identities = _scan(source, source=True)
                if (directories != second_directories or files != second_files or identities != second_identities):
                    raise RuntimeStoreError("核心源在两遍导入快照之间变化")
                with _validated_entry(runtimes / stage_name, binding):
                    pass
                # 仅发布阶段持跨进程目录锁；耗时源读取不占锁。所有写入者共享此锁，
                # 先校验同名目标再整目录 rename，不会覆盖另一轮已经发布的非空快照。
                # 此互斥与 POSIX 只读位都不宣称能抵抗主动绕锁的同用户进程。
                with directory_lock(runtimes, "runtime-core-publication", blocking=True):
                    _verify_snapshot(source, identities)
                    try:
                        os.stat(content_id, dir_fd=destination, follow_symlinks=False)
                    except FileNotFoundError:
                        os.rename(stage_name, content_id, src_dir_fd=destination, dst_dir_fd=destination)
                        stage_name = ""
                        os.fsync(destination)
                    else:
                        # 已有同 ID 即使仅仅空目录也必须完整验证，不能自动重建或修复。
                        return load_core(binding, state)
                return load_core(binding, state)
            finally:
                if stage_name:
                    active_error = sys.exc_info()[1]
                    try:
                        _remove_stage(destination, stage_name, stage_identity)
                    except (OSError, RuntimeStoreError) as cleanup_error:
                        if active_error is None:
                            raise
                        active_error.add_note(f"暂存树未能安全回收：{cleanup_error}")
