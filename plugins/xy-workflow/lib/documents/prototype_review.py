"""插件原型工具的私有离线装配、完整性复核与显式有界迁移。

项目始终拥有业务原型；这里的包仅是可重建派生物。所有发布和恢复操作
都以已打开的真实目录描述符为锚点，不沿用户提供的符号链接执行写入。
"""
from __future__ import annotations

from contextlib import contextmanager
import fcntl
import html
from html.parser import HTMLParser
import json
import os
from pathlib import Path, PurePosixPath
import posixpath
import re
import stat
import sys
import uuid
from urllib.parse import unquote, urlsplit

from lib.documents.safe_documents import digest, normalized_relative, snapshot
from lib.documents import validate_prototype_workspace as workspace

TOOL_ROOT = Path(__file__).resolve().parents[2]
TOOL_ASSETS = ("index.html", "workspace.css", "workspace.js", "feedback.css", "feedback.js", "page-shell.js")
MAX_BUNDLE_FILES = 300
MAX_MANIFEST_BYTES = 256 * 1024


def json_bytes(value: object) -> bytes:
    """规范 JSON 排序键，避免浏览器导出调整键顺序就改变内容身份。"""
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def review_id(context: dict) -> str:
    return digest(json_bytes({key: value for key, value in context.items() if key != "review_id"}))


def project_id(root: Path) -> str:
    fd = workspace._open_root(root, "评审项目根")
    try:
        info = os.fstat(fd)
        return digest(json_bytes([str(root), info.st_dev, info.st_ino]))
    finally:
        os.close(fd)


def _payload(version: bytes, files: dict[str, bytes]) -> str:
    # 长度前缀固定路径/字节边界，不能用简单字符串拼接产生歧义。
    import hashlib
    value = hashlib.sha256(b"agent-workflow/prototype-review-tool/v2\0")
    for name, body in [("version", version)] + sorted(files.items()):
        encoded = name.encode("utf-8")
        value.update(len(encoded).to_bytes(8, "big")); value.update(encoded)
        value.update(len(body).to_bytes(8, "big")); value.update(body)
    return value.hexdigest()


def capture_tool() -> tuple[dict, dict[str, bytes]]:
    """只读取当前物理代码根中的固定白名单，不接受项目或 CLI 指定工具根。"""
    version_path = TOOL_ROOT / "product/PLUGIN_VERSION"
    captures = {version_path: snapshot(version_path)}
    assets = {}
    for name in TOOL_ASSETS:
        path = TOOL_ROOT / "templates/prototype" / name
        captures[path] = snapshot(path)
        assets[name] = captures[path][0]
    version_raw = captures[version_path][0]
    version = version_raw.decode("utf-8").strip()
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9.+_-]{0,127}", version):
        raise ValueError("插件工具版本无效")
    for path, expected in captures.items():
        if snapshot(path) != expected:
            raise ValueError("工具载荷在读取期间变化")
    return {"version": version, "payload_sha256": _payload(version_raw, assets)}, {
        **{"tool/" + name: body for name, body in assets.items()}, "tool/version.txt": version_raw}


class _Navigation(HTMLParser):
    """只投影旧索引的文本与分组，不执行或信任其中的脚本/样式。"""
    def __init__(self, selected: set[str]):
        super().__init__(convert_charrefs=True)
        self.selected = selected
        self.groups = []
        self.result = {}
        self.summary = None
        self.anchor = None

    def handle_starttag(self, tag, attrs):
        values = dict(attrs)
        if tag == "details":
            self.groups.append({"label": "", "open": "open" in values})
        elif tag == "summary" and self.groups:
            self.summary = self.groups[-1]
        elif tag == "a":
            href = values.get("href", "")
            # 旧业务索引可能用 ./page.html 或 page.html#state。这里只将本地
            # 路径规范化后匹配已选叶页面，保留原标签/分组；外部、越界及未选
            # 链接不能因此获得加载权限，更不把旧href作为新viewer的地址。
            split = urlsplit(href)
            target = posixpath.normpath(unquote(split.path)) if not split.scheme and not split.netloc else ""
            if target in self.selected:
                if target in self.result:
                    raise ValueError("旧索引重复登记选定页面：" + target)
                self.anchor = {"label": "", "groups": [group.copy() for group in self.groups]}
                self.result[target] = self.anchor

    def handle_endtag(self, tag):
        if tag == "details" and self.groups:
            self.groups.pop()
        elif tag == "summary":
            self.summary = None
        elif tag == "a":
            self.anchor = None

    def handle_data(self, data):
        if self.summary is not None:
            self.summary["label"] += data
        if self.anchor is not None:
            self.anchor["label"] += data


def navigation_data(index: bytes | None, pages: list[dict], files: dict[str, bytes]) -> list[dict]:
    parser = _Navigation({Path(page["path"]).name for page in pages})
    if index is not None:
        parser.feed(index.decode("utf-8")); parser.close()
    result = []
    for page in pages:
        path = page["path"]
        name = Path(path).name
        found = parser.result.get(name)
        if found is None:
            match = re.search(r"<title(?:\s[^>]*)?>(.*?)</title\s*>", files[path].decode("utf-8"), re.I | re.S)
            label = html.unescape(match[1]) if match else name
            found = {"label": label, "groups": []}
        label = found["label"].strip()
        if not label or len(label) > 1024 or any(not group["label"].strip() or len(group["label"]) > 1024 for group in found["groups"]):
            raise ValueError("原型索引的页面或分组标签为空/超限")
        result.append({"name": name, "path": path, "url": "project/" + path,
                       "label": label, "groups": found["groups"]})
    return result


def default_data_dir() -> Path:
    if sys.platform == "darwin":
        return Path.home() / "Library/Application Support/agent-workflow/prototype-reviews"
    xdg = os.environ.get("XDG_DATA_HOME")
    base = Path(xdg) if xdg and Path(xdg).is_absolute() else Path.home() / ".local/share"
    return base / "agent-workflow/prototype-reviews"


def require_external_data_dir(root: str | Path, data_dir=None) -> None:
    """评审数据必须在项目外，显式测试目录也不能偷偷变成项目写入口。"""
    selected = default_data_dir() if data_dir is None else Path(data_dir)
    project = Path(root)
    if selected == project or selected.is_relative_to(project):
        raise ValueError("评审 data-dir 必须位于物理项目之外的用户级私有数据目录")


def _private(info, label):
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) & 0o077:
        raise ValueError(label + "必须是当前用户独占的私有目录")


def _child(parent: int, name: str, *, create: bool = True) -> int:
    if create:
        try:
            os.mkdir(name, 0o700, dir_fd=parent)
        except FileExistsError:
            pass
    fd = workspace._open_directory_at(parent, name, "评审数据目录")
    try:
        _private(os.fstat(fd), "评审数据目录")
    except BaseException:
        os.close(fd); raise
    return fd


def _data_root(data_dir: str | Path | None, *, create: bool) -> tuple[Path, int]:
    path = default_data_dir() if data_dir is None else Path(data_dir)
    if not path.is_absolute() or ".." in path.parts or "\\" in str(path):
        raise ValueError("data-dir 必须是无父跳转的实际绝对目录")
    # 允许建立缺失的用户数据祖先；每个组件均在已打开父目录下 mkdir/open，
    # 不通过 exists/resolve 把符号链接祖先洗成安全目录。
    fd = workspace._open_root(path.anchor, "用户数据锚点")
    try:
        for part in path.parts[1:]:
            if create:
                try:
                    os.mkdir(part, 0o700, dir_fd=fd)
                except FileExistsError:
                    pass
            next_fd = workspace._open_directory_at(fd, part, "用户数据目录")
            os.close(fd); fd = next_fd
        _private(os.fstat(fd), "data-dir")
        return path, fd
    except BaseException:
        os.close(fd); raise


@contextmanager
def _request_directory(context: dict, data_dir, *, create: bool):
    path, root_fd = _data_root(data_dir, create=create)
    project_fd = request_fd = -1
    try:
        project_fd = _child(root_fd, context["project_id"], create=create)
        request_fd = _child(project_fd, context["request_id"], create=create)
        yield path / context["project_id"] / context["request_id"], request_fd
    finally:
        if request_fd >= 0: os.close(request_fd)
        if project_fd >= 0: os.close(project_fd)
        os.close(root_fd)


@contextmanager
def _lock(directory_fd: int):
    # 直接锁已验证的目录 inode，不创建可被另一个首次发布进程抢建的锁文件。
    # macOS 并发 O_CREAT|O_NOFOLLOW 可返回瞬时 ENOENT；目录锁同时消除此
    # 创建竞态，并确保锁身份与实际写入目录完全一致。
    fd = os.dup(directory_fd)
    try:
        # 非阻塞锁明确报告忙碌；不无限等待另一个失控进程。
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise ValueError("同请求正在发布，请稍后重试；现有包未改变") from exc
        yield
    finally:
        os.close(fd)


@contextmanager
def _project_lock(context: dict, data_dir):
    # 迁移跨 request 共享同一项目锁，避免两个不同请求交错删除与补偿恢复。
    _, root_fd = _data_root(data_dir, create=True)
    project_fd = -1
    try:
        project_fd = _child(root_fd, context["project_id"])
        with _lock(project_fd): yield
    finally:
        if project_fd >= 0: os.close(project_fd)
        os.close(root_fd)


def _read_at(root_fd: int, relative: str, limit=workspace.MAX_DEPENDENCY_SIZE) -> bytes:
    path = PurePosixPath(normalized_relative(relative).as_posix())
    fd = workspace._open_dependency_at(root_fd, path, "评审包文件 " + relative)
    try:
        before = os.fstat(fd)
        body = workspace._read_descriptor(fd, relative, limit)
        if workspace._file_identity(before) != workspace._file_identity(os.fstat(fd)):
            raise ValueError("评审包文件读取期间变化")
        return body
    finally:
        os.close(fd)


def _write_at(root_fd: int, relative: str, body: bytes, *, mode=0o400, private=True):
    path = normalized_relative(relative)
    parent = os.dup(root_fd)
    try:
        for part in path.parts[:-1]:
            child = _child(parent, part) if private else workspace._open_directory_at(parent, part, "恢复项目父目录")
            os.close(parent); parent = child
        fd = os.open(path.name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, mode, dir_fd=parent)
        try:
            view = memoryview(body)
            while view:
                count = os.write(fd, view)
                if count <= 0: raise OSError("评审包写入未取得进展")
                view = view[count:]
            os.fchmod(fd, mode)
            os.fsync(fd)
        finally:
            os.close(fd)
        os.fsync(parent)
    finally:
        os.close(parent)


def _tree(root_fd: int, *, freeze=False, prefix="") -> set[str]:
    result = set()
    for name in os.listdir(root_fd):
        relative = prefix + name
        info = os.stat(name, dir_fd=root_fd, follow_symlinks=False)
        if stat.S_ISDIR(info.st_mode):
            fd = _child(root_fd, name, create=False)
            try:
                result.update(_tree(fd, freeze=freeze, prefix=relative + "/"))
                if freeze: os.fchmod(fd, 0o500)
            finally:
                os.close(fd)
        elif stat.S_ISREG(info.st_mode) and info.st_nlink == 1:
            result.add(relative)
        else:
            raise ValueError("评审包混入非普通节点：" + relative)
        if len(result) > MAX_BUNDLE_FILES:
            raise ValueError("评审包文件数量超限")
    return result


def _closed_json(body: bytes) -> dict:
    def unique(pairs):
        value = {}
        for key, entry in pairs:
            if key in value: raise ValueError("评审数据包含重复字段")
            value[key] = entry
        return value
    return json.loads(body.decode("utf-8"), object_pairs_hook=unique,
                      parse_constant=lambda _: (_ for _ in ()).throw(ValueError("非法JSON数字")))


def _check_bundle(request_fd: int, context: dict, *, expected: dict[str, bytes] | None = None,
                  source_files: dict[str, bytes] | None = None, navigation: list[dict] | None = None) -> dict:
    fd = _child(request_fd, context["review_id"], create=False)
    try:
        manifest = _closed_json(_read_at(fd, "manifest.json", MAX_MANIFEST_BYTES))
        if (not isinstance(manifest, dict) or set(manifest) != {"schema_version", "context", "files"}
                or type(manifest["schema_version"]) is not int or manifest["schema_version"] != 2
                or manifest["context"] != context or not isinstance(manifest["files"], list)
                or not 1 <= len(manifest["files"]) < MAX_BUNDLE_FILES):
            raise ValueError("评审包清单不匹配")
        files = {}
        for entry in manifest["files"]:
            if (not isinstance(entry, dict) or set(entry) != {"path", "size", "sha256"}
                    or not isinstance(entry["path"], str) or type(entry["size"]) is not int
                    or not 0 <= entry["size"] <= workspace.MAX_DEPENDENCY_SIZE
                    or not isinstance(entry["sha256"], str) or not re.fullmatch(r"[0-9a-f]{64}", entry["sha256"])):
                raise ValueError("评审包文件记录无效")
            path = normalized_relative(entry["path"]).as_posix()
            if path == "manifest.json" or path in files: raise ValueError("评审包重复文件")
            body = _read_at(fd, path)
            if len(body) != entry["size"] or digest(body) != entry["sha256"]:
                raise ValueError("评审包文件损坏：" + path)
            files[path] = body
        if _tree(fd) != set(files) | {"manifest.json"}:
            raise ValueError("评审包包含清单外文件或缺失文件")
        tool_paths = {"tool/" + name for name in TOOL_ASSETS} | {"tool/version.txt"}
        if not tool_paths.issubset(files): raise ValueError("评审包缺少工具载荷")
        if (files["tool/version.txt"].decode("utf-8").strip() != context["tool"]["version"]
                or _payload(files["tool/version.txt"], {name: files["tool/" + name] for name in TOOL_ASSETS})
                != context["tool"]["payload_sha256"]):
            raise ValueError("评审包工具版本或摘要不匹配")
        if source_files is not None:
            original_tools = {path: files[path] for path in tool_paths}
            expected = _assemble(context, source_files, original_tools, navigation)
        if expected is not None and files != {path: body for path, body in expected.items() if path != "manifest.json"}:
            raise ValueError("评审包派生文件不匹配真实来源与固定工具")
        return manifest
    finally:
        os.close(fd)


def validate_bundle(context: dict, *, data_dir=None, source_files=None, navigation=None) -> dict:
    if review_id(context) != context["review_id"]:
        raise ValueError("评审内容身份不匹配")
    with _request_directory(context, data_dir, create=False) as (_, fd):
        return _check_bundle(fd, context, source_files=source_files, navigation=navigation)


def _assemble(context: dict, files: dict[str, bytes], tools: dict[str, bytes], navigation: list[dict]) -> dict[str, bytes]:
    result = dict(tools)
    selected = {page["path"] for page in context["pages"]}
    for path, body in files.items():
        target = "project/" + normalized_relative(path).as_posix()
        if path in selected:
            source = body.decode("utf-8")
            bridge = posixpath.relpath("tool/page-shell.js", posixpath.dirname(target))
            addition = '<script src="' + html.escape(bridge, quote=True) + '" data-prototype-review-bridge></script>'
            matches = list(re.finditer(r"</body\s*>", source, re.I))
            if len(matches) != 1: raise ValueError("具体页面必须有唯一 body 结束标签")
            source = source[:matches[0].start()] + addition + source[matches[0].start():]
            body = source.encode("utf-8")
        result[target] = body
    boot = {"schema_version": 2, "context": context, "pages": navigation}
    # JSON 是非执行数据；转义 '<' 防止业务标签中的 </script> 结束数据元素。
    encoded = json_bytes(boot).decode("utf-8")
    for char, replacement in (("&", "\\u0026"), ("<", "\\u003c"), (">", "\\u003e"), ("\u2028", "\\u2028"), ("\u2029", "\\u2029")):
        encoded = encoded.replace(char, replacement)
    source = tools["tool/index.html"].decode("utf-8")
    for name in TOOL_ASSETS:
        if name != "index.html":
            source = source.replace('"' + name + '"', '"tool/' + name + '"')
    if 'id="prototype-review-data"' in source: raise ValueError("工具模板不能预带评审数据")
    source = source.replace("</head>", '<script type="application/json" id="prototype-review-data">' + encoded + '</script></head>', 1)
    result["index.html"] = source.encode("utf-8")
    return result


def publish_bundle(context: dict, files: dict[str, bytes], tools: dict[str, bytes], navigation: list[dict], *, data_dir=None) -> dict:
    assembled = _assemble(context, files, tools, navigation)
    manifest = {"schema_version": 2, "context": context, "files": [
        {"path": path, "size": len(body), "sha256": digest(body)} for path, body in sorted(assembled.items())]}
    assembled["manifest.json"] = json_bytes(manifest)
    with _request_directory(context, data_dir, create=True) as (path, fd), _lock(fd):
        try:
            os.stat(context["review_id"], dir_fd=fd, follow_symlinks=False)
        except FileNotFoundError:
            reused = False
        else:
            _check_bundle(fd, context, expected=assembled)
            return {"bundle_path": str(path / context["review_id"]), "reused": True}
        stage = ".building-" + uuid.uuid4().hex
        os.mkdir(stage, 0o700, dir_fd=fd)
        stage_fd = _child(fd, stage, create=False)
        try:
            for name, body in assembled.items(): _write_at(stage_fd, name, body)
            _tree(stage_fd, freeze=True)
            os.fchmod(stage_fd, 0o500)
            os.fsync(stage_fd)
            # 同请求的进程通过私有 no-follow 锁串行发布；只发布完整目录，
            # 失败的独立 .building 目录保留可诊断，不触碰任何旧包。
            os.rename(stage, context["review_id"], src_dir_fd=fd, dst_dir_fd=fd)
            os.fsync(fd)
        finally:
            os.close(stage_fd)
        _check_bundle(fd, context, expected=assembled)
        return {"bundle_path": str(path / context["review_id"]), "reused": reused}

# 这些名称只是候选范围；字节来源与实际引用检查共同成立才有删除资格。
# prototype.css/js 经常混有业务样式，index 还保存业务分组，因此永不自动删。
MIGRATION_TOOL_NAMES = {"workspace.css", "workspace.js", "feedback.css", "feedback.js", "page-shell.js"}


def _migration_inventory(root: Path, prototype: str) -> dict[str, bytes]:
    project_fd = workspace._open_root(root, "迁移项目根")
    prototype_fd = -1
    try:
        prototype_fd = workspace._walk_directory(project_fd, PurePosixPath(prototype), "迁移原型根")
        result = {}
        total = 0
        def walk(fd, prefix="", depth=0):
            nonlocal total
            if depth > workspace.MAX_DEPENDENCY_DEPTH: raise ValueError("迁移清点目录过深")
            for name in sorted(os.listdir(fd)):
                if name.startswith("."):
                    raise ValueError("迁移原型目录有隐藏节点，须先人工确认：" + name)
                relative = prefix + name
                info = os.stat(name, dir_fd=fd, follow_symlinks=False)
                if stat.S_ISDIR(info.st_mode):
                    nested = workspace._open_directory_at(fd, name, "迁移清点子目录")
                    try: walk(nested, relative + "/", depth + 1)
                    finally: os.close(nested)
                elif stat.S_ISREG(info.st_mode) and info.st_nlink == 1:
                    body = _read_at(prototype_fd, relative)
                    result[prototype + "/" + relative] = body
                    total += len(body)
                    if len(result) > workspace.MAX_DEPENDENCY_NODES or total > workspace.MAX_DEPENDENCY_TOTAL_SIZE:
                        raise ValueError("迁移清点超过有界读取限额")
                else:
                    raise ValueError("迁移清点拒绝链接或特殊节点：" + relative)
        walk(prototype_fd)
        return result
    finally:
        if prototype_fd >= 0: os.close(prototype_fd)
        os.close(project_fd)


def migration_preview(root: str | Path, adapter: str, plan: str, request_id: str,
                      pages: list[str] | None = None, *, confirm_no_active_use: bool = False) -> dict:
    """只读清点；活动使用未知时不推定删除许可，所有候选均保留报告。"""
    from lib.documents.prototype_feedback import _capture_review
    tool, tools = capture_tool()
    context, _, _, _ = _capture_review(root, adapter, plan, request_id, pages, tool=tool)
    inventory = _migration_inventory(Path(root), context["prototype_root"])
    candidates, preserved = [], []
    for path, body in sorted(inventory.items()):
        name = Path(path).name
        eligible = Path(path).parent.as_posix() == context["prototype_root"] and name in MIGRATION_TOOL_NAMES
        if not eligible:
            reason = "项目业务页面、索引或未确认资产"
        elif body != tools["tool/" + name]:
            reason = "来源未知、用户修改或混合业务内容"
        elif not confirm_no_active_use:
            reason = "活动使用尚未明确排除"
        else:
            # 在整个有界原型目录中寻找真实依赖。除解析出的静态引用外，再保守
            # 保留任何含候选文件名字面值的业务文本，避免动态拼装或自定义加载器
            # 被误判为未引用；宁可保留，不按文件名批量清除。
            used = False
            for source, source_body in inventory.items():
                if source == path: continue
                if Path(source).suffix.lower() in workspace.TEXT_DEPENDENCY_SUFFIXES:
                    if name.encode("utf-8") in source_body:
                        used = True; break
            if not used:
                candidates.append({"path": path, "sha256": digest(body), "mode": stat.S_IMODE((Path(root) / path).lstat().st_mode), "reason": "当前插件原字节纯工具且无实际引用"})
                continue
            reason = "项目页面或业务资产仍引用该工具"
        preserved.append({"path": path, "reason": reason})
    inventory_digest = [{"path": path, "sha256": digest(body)} for path, body in sorted(inventory.items())]
    result = {"schema_version": 2, "status": "preview", "context": context,
              "active_use_confirmed": confirm_no_active_use, "candidates": candidates, "preserved": preserved}
    result["source_digest"] = digest(json_bytes({"preview": result, "inventory": inventory_digest}))
    # 清点完成后再读取一次，拒绝 preview 内部读到两个不同的项目状态。
    if _migration_inventory(Path(root), context["prototype_root"]) != inventory:
        raise ValueError("迁移来源在清点期间变化")
    return result


def _state_write(fd: int, state: dict):
    name = ".state-" + uuid.uuid4().hex
    _write_at(fd, name, json_bytes(state), mode=0o600)
    os.rename(name, "state.json", src_dir_fd=fd, dst_dir_fd=fd)
    os.fsync(fd)


def _quarantine_name(preview: dict) -> str:
    return ".awf-prototype-migration-" + preview["source_digest"]


def _restore_quarantine(project_fd: int, preview: dict) -> list[str]:
    """通过排他硬链接恢复原节点，保留 inode/权限且不覆盖并发新文件。

    先 rename 再核验的节点即使被外部进程换成不同内容或符号链接，也仍在
    同文件系统隔离区中；恢复原节点本身，不打开链接目标或用旧前像覆盖它。
    """
    name = _quarantine_name(preview)
    try:
        os.stat(name, dir_fd=project_fd, follow_symlinks=False)
    except FileNotFoundError:
        return []
    fd = _child(project_fd, name, create=False)
    conflicts = []
    try:
        expected_names = {Path(entry["path"]).name for entry in preview["candidates"]}
        if set(os.listdir(fd)) - expected_names: raise ValueError("迁移隔离区有未知节点，拒绝清理")
        for entry in preview["candidates"]:
            relative = PurePosixPath(entry["path"])
            try: os.stat(relative.name, dir_fd=fd, follow_symlinks=False)
            except FileNotFoundError: continue
            parent = workspace._walk_directory(project_fd, relative.parent, "隔离恢复父目录")
            try:
                try:
                    os.link(relative.name, relative.name, src_dir_fd=fd, dst_dir_fd=parent, follow_symlinks=False)
                except FileExistsError:
                    conflicts.append(entry["path"])
                else:
                    os.unlink(relative.name, dir_fd=fd)
                    os.fsync(parent)
            finally: os.close(parent)
        if not os.listdir(fd): os.rmdir(name, dir_fd=project_fd)
        os.fsync(project_fd)
    finally: os.close(fd)
    return conflicts


def _recover_transaction(project_fd: int, transaction_fd: int, expected_project: str, preview: dict) -> dict:
    state = _closed_json(_read_at(transaction_fd, "state.json", MAX_MANIFEST_BYTES))
    if (not isinstance(state, dict) or set(state) != {"schema_version", "project_id", "source_digest", "status", "files"}
            or state["schema_version"] != 2 or state["project_id"] != expected_project
            or state["source_digest"] != preview["source_digest"]
            or state["status"] not in {"collecting", "prepared", "committed", "recovered", "recovery_conflict"}
            or state["files"] != [{"path": item["path"], "sha256": item["sha256"], "mode": item["mode"]} for item in preview["candidates"]]):
        raise ValueError("迁移恢复记录与来源不匹配")
    if state["status"] in {"committed", "recovered"}:
        return state
    if state["status"] == "collecting":
        # collecting 阶段协议不允许动项目。即使前像只保存一部分，也能明确
        # 恢复为无项目副作用状态；后续只补缺失前像，不删除已有恢复资料。
        state["status"] = "recovered"
        _state_write(transaction_fd, state)
        return state
    conflicts = _restore_quarantine(project_fd, preview)
    for entry in state["files"]:
        path = entry["path"]
        body = _read_at(transaction_fd, "preimages/" + path)
        if digest(body) != entry["sha256"]: raise ValueError("迁移前像损坏，拒绝不可信恢复")
        try:
            current = _read_at(project_fd, path)
        except (OSError, ValueError):
            # 本协议只 rename 到同盘隔离区；若原节点与隔离节点都不存在，说明
            # 已超出本事务能证明的改动范围。保留前像并报告冲突，不复活外部删除。
            conflicts.append(path)
        else:
            if current != body: conflicts.append(path)
    state["status"] = "recovery_conflict" if conflicts else "recovered"
    _state_write(transaction_fd, state)
    if conflicts: raise ValueError("迁移恢复遇到用户新内容，已保留前像且未覆盖：" + ", ".join(conflicts))
    return state


def migration_recover(root: str | Path, adapter: str, preview: dict, *, data_dir=None) -> dict:
    """恢复崩溃中断的精确候选；绝不覆盖期间产生的用户内容。"""
    _validate_preview(preview, adapter)
    require_external_data_dir(root, data_dir)
    context = preview["context"]
    if project_id(Path(root)) != context["project_id"]: raise ValueError("迁移恢复不是原物理项目")
    with _project_lock(context, data_dir), _request_directory(context, data_dir, create=False) as (_, request_fd), _lock(request_fd):
        migrations = _child(request_fd, "migrations", create=False)
        transaction_fd = project_fd = -1
        try:
            transaction_fd = _child(migrations, preview["source_digest"], create=False)
            project_fd = workspace._open_root(root, "迁移恢复项目根")
            state = _recover_transaction(project_fd, transaction_fd, context["project_id"], preview)
            return {"status": state["status"], "source_digest": preview["source_digest"]}
        finally:
            if project_fd >= 0: os.close(project_fd)
            if transaction_fd >= 0: os.close(transaction_fd)
            os.close(migrations)


def _validate_preview(preview: dict, adapter: str):
    from lib.documents.prototype_feedback import _check_context
    if (not isinstance(preview, dict) or set(preview) != {"schema_version", "status", "context", "active_use_confirmed", "candidates", "preserved", "source_digest"}
            or type(preview["schema_version"]) is not int or preview["schema_version"] != 2
            or preview["status"] != "preview" or type(preview["active_use_confirmed"]) is not bool
            or not isinstance(preview["source_digest"], str) or not re.fullmatch(r"[0-9a-f]{64}", preview["source_digest"])):
        raise ValueError("迁移 preview 字段不完整或包含未知字段")
    context = _check_context(preview["context"])
    if context["adapter"] != adapter: raise ValueError("迁移适配器不一致")
    for field, keys in (("candidates", {"path", "sha256", "mode", "reason"}), ("preserved", {"path", "reason"})):
        if not isinstance(preview[field], list) or len(preview[field]) > workspace.MAX_DEPENDENCY_NODES:
            raise ValueError("迁移清点记录超限")
        seen = set()
        for entry in preview[field]:
            if not isinstance(entry, dict) or set(entry) != keys or not isinstance(entry["path"], str):
                raise ValueError("迁移清点条目字段无效")
            path = normalized_relative(entry["path"])
            if not path.is_relative_to(context["prototype_root"]) or entry["path"] in seen:
                raise ValueError("迁移候选越界或重复")
            seen.add(entry["path"])
            if field == "candidates" and (path.parent.as_posix() != context["prototype_root"] or path.name not in MIGRATION_TOOL_NAMES
                    or not isinstance(entry["sha256"], str) or not re.fullmatch(r"[0-9a-f]{64}", entry["sha256"])
                    or type(entry["mode"]) is not int or not 0 <= entry["mode"] <= 0o777):
                raise ValueError("迁移候选没有纯工具边界")


def migration_apply(root: str | Path, adapter: str, preview: dict, *, data_dir=None) -> dict:
    """要求同一 preview 来源 CAS；先落盘精确前像/日志，再删除未引用纯工具。"""
    _validate_preview(preview, adapter)
    require_external_data_dir(root, data_dir)
    context = preview["context"]
    current = migration_preview(root, adapter, context["plan_source"], context["request_id"],
                                [page["path"] for page in context["pages"]],
                                confirm_no_active_use=preview["active_use_confirmed"])
    if current != preview: raise ValueError("迁移 preview 已过期；未修改项目，请重新预览")
    if not preview["candidates"]: return {"status": "no_changes", "source_digest": preview["source_digest"], "removed": []}
    with _project_lock(context, data_dir), _request_directory(context, data_dir, create=True) as (request_path, request_fd), _lock(request_fd):
        migrations = _child(request_fd, "migrations")
        project_fd = transaction_fd = -1
        try:
            project_fd = workspace._open_root(root, "迁移项目根")
            existing_recovered = False
            try: os.mkdir(preview["source_digest"], 0o700, dir_fd=migrations)
            except FileExistsError:
                transaction_fd = _child(migrations, preview["source_digest"], create=False)
                state = _recover_transaction(project_fd, transaction_fd, context["project_id"], preview)
                if state["status"] == "committed":
                    return {"status": "already_applied", "source_digest": preview["source_digest"], "removed": [item["path"] for item in preview["candidates"]]}
                existing_recovered = True
            if transaction_fd < 0:
                transaction_fd = _child(migrations, preview["source_digest"], create=False)
            state = {"schema_version": 2, "project_id": context["project_id"], "source_digest": preview["source_digest"],
                     "status": "collecting", "files": [{"path": item["path"], "sha256": item["sha256"], "mode": item["mode"]} for item in preview["candidates"]]}
            _state_write(transaction_fd, state)
            # 前像全部成功落盘之前不执行任何删除。只保存候选，绝不备份整项目。
            for entry in state["files"]:
                body = _read_at(project_fd, entry["path"])
                if digest(body) != entry["sha256"]: raise ValueError("迁移来源在保存前像时变化")
                preimage = "preimages/" + entry["path"]
                if existing_recovered:
                    try:
                        saved = _read_at(transaction_fd, preimage)
                    except workspace.ValidationError as exc:
                        if not isinstance(exc.__cause__, FileNotFoundError): raise
                        _write_at(transaction_fd, preimage, body)
                    else:
                        if saved != body: raise ValueError("先前恢复前像与重试来源不一致")
                else:
                    _write_at(transaction_fd, preimage, body)
            state["status"] = "prepared"
            _state_write(transaction_fd, state)
            try:
                # 再次核对完整 preview，避免准备前像期间另一进程修改业务引用。
                if migration_preview(root, adapter, context["plan_source"], context["request_id"],
                        [page["path"] for page in context["pages"]], confirm_no_active_use=preview["active_use_confirmed"]) != preview:
                    raise ValueError("迁移来源在 apply 提交前变化")
                quarantine_name = _quarantine_name(preview)
                os.mkdir(quarantine_name, 0o700, dir_fd=project_fd)
                quarantine_fd = _child(project_fd, quarantine_name, create=False)
                try:
                    for entry in state["files"]:
                        relative = PurePosixPath(entry["path"])
                        parent = workspace._walk_directory(project_fd, relative.parent, "迁移提交父目录")
                        try:
                            # 先原子移走实际叶节点，再读取核验；不能 stat/read 后直接
                            # unlink，从而误删二者之间被用户换入的新业务字节。
                            os.rename(relative.name, relative.name, src_dir_fd=parent, dst_dir_fd=quarantine_fd)
                            moved = _read_at(quarantine_fd, relative.name)
                            info = os.stat(relative.name, dir_fd=quarantine_fd, follow_symlinks=False)
                            if digest(moved) != entry["sha256"] or stat.S_IMODE(info.st_mode) != entry["mode"]:
                                raise ValueError("迁移候选在原子提交时变化，恢复原节点")
                            os.fsync(parent)
                        finally: os.close(parent)
                    os.fsync(quarantine_fd)
                    # 所有必要前像仍在用户数据中；隔离区里的原节点在 commit 日志
                    # 成功落盘前绝不删除，因此崩溃恢复不会丢失最后一份业务内容。
                finally: os.close(quarantine_fd)
                state["status"] = "committed"
                _state_write(transaction_fd, state)
            except BaseException:
                _recover_transaction(project_fd, transaction_fd, context["project_id"], preview)
                raise
            # 清理只涉及本事务移走且再次验证的纯工具。若清理受阻，保留隔离区
            # 与 committed 日志供人工检查；项目业务不被补偿成“未提交”。
            quarantine_fd = _child(project_fd, _quarantine_name(preview), create=False)
            try:
                for entry in state["files"]:
                    name = Path(entry["path"]).name
                    if digest(_read_at(quarantine_fd, name)) != entry["sha256"]:
                        raise ValueError("迁移已提交，但隔离区出现新内容，已保留且未删除")
                    os.unlink(name, dir_fd=quarantine_fd)
                os.fsync(quarantine_fd)
            finally: os.close(quarantine_fd)
            os.rmdir(_quarantine_name(preview), dir_fd=project_fd)
            os.fsync(project_fd)
            return {"status": "applied", "source_digest": preview["source_digest"], "removed": [item["path"] for item in preview["candidates"]],
                    "recovery_path": str(request_path / "migrations" / preview["source_digest"])}
        finally:
            if project_fd >= 0: os.close(project_fd)
            if transaction_fd >= 0: os.close(transaction_fd)
            os.close(migrations)
