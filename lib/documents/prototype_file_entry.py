"""受管 file 入口的唯一发布边界；公开目录不包含浏览器或管理凭据。"""
from __future__ import annotations

from contextlib import contextmanager
from html.parser import HTMLParser
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import uuid

from lib.documents import prototype_review as review
from lib.documents import validate_prototype_workspace as workspace
from lib.documents.safe_documents import snapshot
from lib.documents.prototype_targets import _object, json_bytes

MOUNT = ".xy-prototype-entry"
ENTRY = '<script src=".xy-prototype-entry/entry.js" data-xy-delivery-entry="1" charset="utf-8"></script>'
ENTRY_START = ENTRY.removesuffix("</script>")
IGNORE = b"/.xy-prototype-entry/"
CATALOG_PREFIX = b"window.XYFileDeliveryEntry.receiveCatalog("
# 仅用于识别已经发布的受管 file 挂载，不是当前工具白名单的可选子集。
# 3.0.4/3.0.5 的 format5 工具闭包在发布时固定为这17项；3.0.3没有受管
# file入口，3.0.6起共享主题/许可属于完整新闭包。未来新增当前资产不能反向
# 改变此历史身份，也不能因“恰好缺主题”而把不完整的新缓存降级成旧版本。
_HISTORICAL_FILE_TOOL_VERSIONS = frozenset({"3.0.4", "3.0.5"})
_HISTORICAL_FILE_TOOL_ASSETS = (
    "delivery.html", "review.html", "live-workspace.js", "live-connection.js",
    "canvas-host.js", "live.css", "workspace.css", "review-state.js", "review-camera.js",
    "feedback.js", "feedback.css", "page-shell.js", "THIRD_PARTY_NOTICES.txt",
    "file-entry.js", "file-delivery.js", "file-page.js", "canvas-presentation.js",
)
# 项目交付目录与单次评审是两个不同权限范围：目录可覆盖256页，单次live评审
# 仍由prototype_targets.MAX_PAGES限制16页；不能因复用常量而截断整个项目目录。
MAX_DELIVERY_PAGES = 256


def directory_sha256(root, prototype):
    """与浏览器new URL('.', originalFileURL).href同口径；发布中只存摘要。

    调用者先按no-follow验证实际root/prototype，不能resolve用户传入的链接别名。
    file URI使用UTF-8百分号编码并保留目录末尾斜线，复制旧挂载不会继承原目录信任。
    """
    uri = (Path(root) / prototype).as_uri().rstrip("/") + "/"
    return hashlib.sha256(uri.encode("utf-8")).hexdigest()


class PreparationError(ValueError):
    code = "preparation_required"


class _Presentation(HTMLParser):
    """仅投影已存在的声明；动态CSS尺寸由子页测量，不猜平台或统一视口。"""
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.platform = self.display = ""
        self.frames = []
        self.plan_source = ""

    def handle_starttag(self, tag, attributes):
        attrs = dict(attributes)
        if tag == "body":
            self.platform = attrs.get("data-prototype-platform", "")
            self.display = attrs.get("data-prototype-display", "")
            self.plan_source = attrs.get("data-prototype-plan-source", "")
        if "prototype-frame" in attrs.get("class", "").split():
            sizes = {}
            for axis in ("width", "height"):
                matches = re.findall(r"(?:^|;)\s*--prototype-frame-" + axis + r"\s*:\s*([0-9]+(?:\.[0-9]+)?)px\s*(?=;|$)", attrs.get("style", ""))
                if len(matches) == 1 and 1 <= float(matches[0]) <= 16384:
                    number = float(matches[0])
                    sizes[axis] = int(number) if number.is_integer() else number
            self.frames.append(sizes if set(sizes) == {"width", "height"} else None)


def presentation(body):
    parser = _Presentation()
    parser.feed(body.decode("utf-8")); parser.close()
    for value in (parser.platform, parser.display):
        if len(value) > 128 or any(ord(char) < 32 for char in value): raise ValueError("原稿展示声明无效")
    return {"platform": parser.platform, "display": parser.display,
        "viewport": parser.frames[0] if len(parser.frames) == 1 else None, "plan_source": parser.plan_source}


def _entry_span(body):
    """只承认冻结的逐字标签，而且必须先于一切业务脚本；近似标签一律拒绝。"""
    text = body.decode("utf-8")
    offsets = [0]
    # HTMLParser行号只按LF递增；CRLF的CR仍属于该行原字节，不能用splitlines
    # 把单独CR也当换行，否则受管标签移除位置会偏移。
    for line in text.split("\n")[:-1]: offsets.append(offsets[-1] + len(line) + 1)
    # HTML注释中的模板示例不算入口；用原始位置记录真实script，避免移除注释示例
    # 或脚本文字后让匿名节点偏移与浏览器真正执行的标签不一致。
    class Scripts(HTMLParser):
        def __init__(self): super().__init__(); self.scripts = []; self.entries = []
        def handle_starttag(self, tag, attributes):
            if tag != "script": return
            attrs = dict(attributes); self.scripts.append(self.get_starttag_text())
            if MOUNT in attrs.get("src", "") or "data-xy-delivery-entry" in attrs:
                line, column = self.getpos()
                position = offsets[line - 1] + column
                self.entries.append((position, self.get_starttag_text()))
                if len(self.entries) > 1: raise PreparationError("受管入口不能重复")
    parser = Scripts(); parser.feed(text); parser.close()
    if not parser.entries: return None
    if len(parser.entries) != 1 or parser.scripts[0] != ENTRY_START or parser.entries[0][1] != ENTRY_START:
        raise PreparationError("受管入口必须是首个逐字匹配的经典脚本")
    position = parser.entries[0][0]
    if text[position:position + len(ENTRY)] != ENTRY: raise PreparationError("受管入口标签已改变")
    return position, position + len(ENTRY)


def entry_present(body):
    return _entry_span(body) is not None


def strip_entry(body):
    """只能在原字节定位注入完成后调用，避免匿名节点的来源偏移发生漂移。"""
    span = _entry_span(body)
    text = body.decode("utf-8")
    return (text[:span[0]] + text[span[1]:]).encode("utf-8") if span else body


def _read_optional(fd, name, limit=workspace.MAX_TEXT_FILE_SIZE):
    try: os.stat(name, dir_fd=fd, follow_symlinks=False)
    except FileNotFoundError: return None
    return review._read_at(fd, name, limit)


def _cas(fd, name, expected, body, *, mode=0o600):
    """在项目锁中按完整旧字节条件发布；失败补偿也不能覆盖用户的新内容。

    项目锁串行化本工具的不同请求；普通编辑器不协作持锁，因此换名前再次核对
    inode及字节。原稿只暂存本次待写内容，绝不在用户级目录保存业务HTML副本。
    """
    current = _read_optional(fd, name)
    if current != expected: raise ValueError("文件在准备期间改变，用户修改已保留：" + name)
    info = os.stat(name, dir_fd=fd, follow_symlinks=False) if current is not None else None
    if current == body: return
    temporary = ".entry-writing-" + uuid.uuid4().hex
    review._write_at(fd, temporary, body, mode=stat.S_IMODE(info.st_mode) if info else mode)
    try:
        if _read_optional(fd, name) != expected or (info is not None and workspace._file_identity(os.stat(name, dir_fd=fd, follow_symlinks=False)) != workspace._file_identity(info)):
            raise ValueError("文件在发布前改变，用户修改已保留：" + name)
        os.replace(temporary, name, src_dir_fd=fd, dst_dir_fd=fd); os.fsync(fd)
    finally:
        try: os.unlink(temporary, dir_fd=fd)
        except FileNotFoundError: pass


def _shell(tools):
    html = tools["tool/delivery.html"].decode("utf-8").replace('"/assets/', '"assets/')
    # JSON按JS字符串字面值编码，额外转义HTML敏感字符，模板只有唯一可信来源。
    encoded = json.dumps(html, ensure_ascii=True).replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")
    return ("window.XYFileDeliveryEntry.receiveShell(" + encoded + ");\n").encode()


def _cache_files(tools):
    return {**{name.removeprefix("tool/"): body for name, body in tools.items()}, "shell.js": _shell(tools)}


def _publish_cache(data_dir, tool, tools):
    """工具按payload只缓存一份；先写完整不可变目录，再原子发布可见名字。"""
    path, root_fd = review._data_root(data_dir, create=True)
    tools_fd = -1
    try:
        tools_fd = review._child(root_fd, "tools")
        # 多项目共享同payload缓存，复用目录锁避免跨项目同时首次发布。
        with review._lock(tools_fd):
            expected = _cache_files(tools)
            try: final = review._child(tools_fd, tool["payload_sha256"], create=False)
            except ValueError:
                # _child把缺失目录映射为安全校验错误，先确认确实不存在，不能覆盖篡改目录。
                try: os.stat(tool["payload_sha256"], dir_fd=tools_fd, follow_symlinks=False)
                except FileNotFoundError: final = -1
                else: raise
            if final >= 0:
                try:
                    if set(os.listdir(final)) != set(expected): raise ValueError("不可变工具缓存清单改变")
                    for name, body in expected.items():
                        if review._read_at(final, name) != body: raise ValueError("不可变工具缓存摘要改变")
                finally: os.close(final)
            else:
                temporary = ".entry-cache-" + uuid.uuid4().hex
                cache_fd = review._child(tools_fd, temporary)
                try:
                    for name, body in expected.items(): review._write_at(cache_fd, name, body)
                    os.rename(temporary, tool["payload_sha256"], src_dir_fd=tools_fd, dst_dir_fd=tools_fd)
                    os.fsync(tools_fd)
                finally: os.close(cache_fd)
        return path / "tools" / tool["payload_sha256"]
    finally:
        if tools_fd >= 0: os.close(tools_fd)
        os.close(root_fd)


@contextmanager
def _delivery(root, data_dir, *, create=False):
    identity = review.project_id(Path(root))
    path, root_fd = review._data_root(data_dir, create=create)
    project_fd = delivery_fd = -1
    try:
        project_fd = review._child(root_fd, identity, create=create)
        delivery_fd = review._child(project_fd, "delivery", create=create)
        yield path / identity / "delivery", delivery_fd
    finally:
        if delivery_fd >= 0: os.close(delivery_fd)
        if project_fd >= 0: os.close(project_fd)
        os.close(root_fd)


def _catalog(fd):
    raw = review._read_at(fd, "catalog.js", review.MAX_MANIFEST_BYTES)
    if not raw.startswith(CATALOG_PREFIX) or not raw.endswith(b");\n"): raise ValueError("公开目录回调无效")
    value = review._closed_json(raw[len(CATALOG_PREFIX):-3])
    return _validate_catalog(value)


def _validate_catalog(value):
    """生产者与消费者共用同一封闭字段校验，禁止发布本模块自己无法再读取的目录。"""
    _object(value, {"schema_version", "project_id", "directory_sha256", "tool", "pages"}, "公开交付目录")
    if type(value["schema_version"]) is not int or value["schema_version"] != 1: raise ValueError("公开目录版本无效")
    _object(value["tool"], {"version", "payload_sha256"}, "公开工具身份")
    if any(not isinstance(field, str) or not re.fullmatch(r"[a-f0-9]{64}", field) for field in (value["project_id"], value["directory_sha256"], value["tool"]["payload_sha256"])): raise ValueError("公开身份无效")
    if not isinstance(value["tool"]["version"], str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9.+_-]{0,127}", value["tool"]["version"]): raise ValueError("公开工具版本无效")
    if not isinstance(value["pages"], list) or not 1 <= len(value["pages"]) <= MAX_DELIVERY_PAGES: raise ValueError("公开页面数量无效")
    names = set()
    for page in value["pages"]:
        _object(page, {"name", "path", "label", "groups", "platform", "display", "viewport", "plan_source", "binding"}, "公开页面")
        name = page["name"]
        if not isinstance(name, str) or not re.fullmatch(r"[a-z0-9][a-z0-9-]*\.html", name) or name == "index.html" or name in names: raise ValueError("公开页面名称无效")
        names.add(name)
        relative = review._relative(page["path"], "公开页面路径")
        if Path(relative).name != name: raise ValueError("公开页面路径不匹配")
        for key, limit in (("label", 1024), ("platform", 128), ("display", 128), ("plan_source", 1024)):
            text = page[key]
            if not isinstance(text, str) or len(text) > limit or (key != "label" and any(ord(char) < 32 for char in text)): raise ValueError("公开页面文字无效")
        if not page["label"]: raise ValueError("公开页面标签不能为空")
        if page["plan_source"]: review._relative(page["plan_source"], "页面需求路径")
        if not isinstance(page["groups"], list) or len(page["groups"]) > 32: raise ValueError("公开分组无效")
        for group in page["groups"]:
            _object(group, {"label", "open"}, "公开分组")
            if not isinstance(group["label"], str) or not 1 <= len(group["label"]) <= 1024 or type(group["open"]) is not bool: raise ValueError("公开分组字段无效")
        if page["viewport"] is not None:
            size = _object(page["viewport"], {"width", "height"}, "公开尺寸")
            if any(type(number) not in (int, float) or not 1 <= number <= 16384 for number in size.values()): raise ValueError("公开尺寸范围无效")
        if page["binding"] is not None:
            binding = _object(page["binding"], {"request_id", "review_id", "instance", "origin"}, "公开绑定")
            review._identifier(binding["request_id"], "绑定请求")
            if (not isinstance(binding["review_id"], str) or not re.fullmatch(r"[a-f0-9]{64}", binding["review_id"])
                or not isinstance(binding["instance"], str) or not re.fullmatch(r"[a-f0-9]{48}", binding["instance"])): raise ValueError("公开修订或实例无效")
            if not isinstance(binding["origin"], str): raise ValueError("公开评审来源无效")
            match = re.fullmatch(r"http://127\.0\.0\.1:([1-9][0-9]{0,4})", binding["origin"])
            if not match or int(match[1]) > 65535: raise ValueError("公开评审来源无效")
    if len({str(Path(page["path"]).parent) for page in value["pages"]}) != 1: raise ValueError("公开目录页面必须同目录")
    return value


def _catalog_bytes(value):
    _validate_catalog(value)
    body = CATALOG_PREFIX + json_bytes(value) + b");\n"
    if len(body) > review.MAX_MANIFEST_BYTES: raise ValueError("公开交付目录超过字节限额；现有目录未改变")
    return body


def _write_catalog(fd, value):
    # callback载荷是封闭JSON；不允许额外语句、JSONP参数或隐藏的权限字段。
    _cas(fd, "catalog.js", _read_optional(fd, "catalog.js"), _catalog_bytes(value))


def _restore(fd, name, before, written):
    """仅补偿本次仍未被修改的输出；并发用户内容和其他请求结果始终保留。"""
    if _read_optional(fd, name) != written: return
    if before is None:
        os.unlink(name, dir_fd=fd); os.fsync(fd)
    else: _cas(fd, name, written, before)


def _link_value(fd, name):
    try: return os.readlink(name, dir_fd=fd)
    except FileNotFoundError: return None


def _link_cas(fd, name, expected, target):
    """受管工具链接与正文采用同一条件发布原则；清理只碰本次拥有的临时链接。"""
    if _link_value(fd, name) != expected: raise ValueError("受管链接在发布期间改变")
    temporary = ".entry-link-" + uuid.uuid4().hex
    try:
        os.symlink(str(target), temporary, dir_fd=fd)
        if _link_value(fd, name) != expected: raise ValueError("受管链接在换名前改变")
        os.replace(temporary, name, src_dir_fd=fd, dst_dir_fd=fd); os.fsync(fd)
    finally:
        try: os.unlink(temporary, dir_fd=fd)
        except FileNotFoundError: pass


def verify_mount(prototype_fd, root, prototype, *, expected_data_dir=None):
    """受管链接的窄例外：只信任本项目私有发布目录和摘要完全一致的工具闭包。"""
    info = os.stat(MOUNT, dir_fd=prototype_fd, follow_symlinks=False)
    if not stat.S_ISLNK(info.st_mode) or info.st_uid != os.getuid(): raise PreparationError("受管入口链接类型或属主无效")
    target = Path(os.readlink(MOUNT, dir_fd=prototype_fd))
    identity = review.project_id(Path(root))
    if not target.is_absolute() or ".." in target.parts or target.name != "delivery" or target.parent.name != identity:
        raise PreparationError("受管入口不属于当前项目")
    data_dir = target.parent.parent
    review.require_external_data_dir(root, data_dir)
    if expected_data_dir is not None and data_dir != Path(expected_data_dir): raise PreparationError("受管入口属于另一数据目录")
    with _delivery(root, data_dir) as (published, fd):
        if target != published: raise PreparationError("受管入口发布目录不匹配")
        value = _catalog(fd)
        if value["project_id"] != identity or any(str(Path(page["path"]).parent) != str(prototype) for page in value["pages"]): raise PreparationError("受管目录页面不属于当前原型目录")
        if value["directory_sha256"] != directory_sha256(root, prototype): raise PreparationError("交付目录已移动或复制；请在当前项目重新准备入口")
        cache = data_dir / "tools" / value["tool"]["payload_sha256"]
        expected_links = {"entry.js": cache / "file-entry.js", "shell.js": cache / "shell.js", "assets": cache}
        for name, expected in expected_links.items():
            linked = os.stat(name, dir_fd=fd, follow_symlinks=False)
            if not stat.S_ISLNK(linked.st_mode) or linked.st_uid != os.getuid() or os.readlink(name, dir_fd=fd) != str(expected): raise PreparationError("受管工具引用已改变")
        if set(os.listdir(fd)) != {"entry.js", "shell.js", "assets", "catalog.js"}: raise PreparationError("受管发布目录出现未知文件")
        cache_fd = workspace._open_root(cache, "不可变工具缓存")
        try:
            review._private(os.fstat(cache_fd), "不可变工具缓存")
            version = review._read_at(cache_fd, "version.txt")
            actual_version = version.decode().strip()
            if actual_version != value["tool"]["version"]: raise PreparationError("不可变工具版本或摘要不匹配")
            names = set(os.listdir(cache_fd))
            if names == set(review.LIVE_TOOL_ASSETS) | {"version.txt", "shell.js"}:
                asset_names = review.LIVE_TOOL_ASSETS
            elif (actual_version in _HISTORICAL_FILE_TOOL_VERSIONS
                  and names == set(_HISTORICAL_FILE_TOOL_ASSETS) | {"version.txt", "shell.js"}):
                asset_names = _HISTORICAL_FILE_TOOL_ASSETS
            else:
                raise PreparationError("不可变工具清单改变")
            # schema 只决定本次必须完整验证的封闭名单，不授予旧字节当前版本身份。
            # 全载荷仍使用原format5长度前缀摘要；shell必须由同一份delivery原字节派生。
            tools = {"tool/" + name: review._read_at(cache_fd, name) for name in asset_names}
            if review._payload(version, {name.removeprefix("tool/"): body for name, body in tools.items()}, format_version=5) != value["tool"]["payload_sha256"]: raise PreparationError("不可变工具版本或摘要不匹配")
            if review._read_at(cache_fd, "shell.js") != _shell(tools): raise PreparationError("唯一交付外壳已改变")
        finally: os.close(cache_fd)
    if os.readlink(MOUNT, dir_fd=prototype_fd) != str(target): raise PreparationError("受管链接在验证期间改变")
    return value


def _configuration(root, adapter, pages):
    project = Path(root)
    if not project.is_absolute() or ".." in project.parts or "\\" in str(project): raise ValueError("项目根必须为实际绝对目录")
    adapter = review._relative(adapter, "适配器路径")
    # 与评审一致，先确认项目来源，再直接读取同一个显式适配器。
    review.validate_task_source({}, root=project)
    body, _ = snapshot(project / adapter)
    errors = []
    docs = review.validate_docs(body.decode("utf-8").splitlines(), project, errors)
    if errors: raise ValueError("适配器文档配置无效：" + "; ".join(errors))
    prototype = PurePosixPath(review._relative(docs["standards_root"].rstrip("/") + "/prototype", "原型目录"))
    if not isinstance(pages, list) or not 1 <= len(pages) <= MAX_DELIVERY_PAGES or len(pages) != len(set(pages)): raise ValueError("须显式选择1至256个不重复具体页面")
    for page in pages:
        relative = PurePosixPath(review._relative(page, "原稿页面"))
        if relative.parent != prototype or relative.name == "index.html" or not re.fullmatch(r"[a-z0-9][a-z0-9-]*\.html", relative.name): raise ValueError("交付准备页面必须位于配置原型根")
    return prototype


def prepare_delivery(root, adapter, pages, *, data_dir=None):
    """显式准备只挂载可信工具和元数据，不创建请求、不启动服务、幂等保留既有绑定。"""
    review.require_external_data_dir(root, data_dir)
    prototype = _configuration(root, adapter, pages)
    tool, tools = review.capture_tool(format_version=5)
    identity = {"project_id": review.project_id(Path(root))}
    with review._project_lock(identity, data_dir):
        cache = _publish_cache(data_dir, tool, tools)
        project_fd = workspace._open_root(root, "交付准备项目")
        fd = -1
        changed = []
        try:
            fd = workspace._walk_directory(project_fd, prototype, "交付原型目录")
            try: os.stat(MOUNT, dir_fd=fd, follow_symlinks=False)
            except FileNotFoundError: old = None
            else: old = verify_mount(fd, root, prototype, expected_data_dir=data_dir or review.default_data_dir())
            # 一次读取全部原稿并先验证全部待写内容；任一页失败都不进入部分写入。
            originals = {Path(page).name: review._read_at(fd, Path(page).name, workspace.MAX_TEXT_FILE_SIZE) for page in pages}
            # prepare不绕过现有结构和依赖安全校验；裸原稿无挂载也走原no-follow闭包，
            # 已准备页则必须通过上面的可信挂载验证后才得到唯一工具依赖例外。
            workspace.capture_selected_pages(root, str(prototype), pages=[Path(page).name for page in pages], adapter=adapter)
            replacements = {}
            entries = {page["name"]: page for page in old["pages"]} if old else {}
            for page in pages:
                name = Path(page).name; body = originals[name]
                if entry_present(body): replacements[name] = body
                else:
                    matches = list(re.finditer(br"<head(?:\s[^>]*)?>", body, re.I))
                    if len(matches) != 1: raise ValueError("原稿必须有唯一head标签")
                    end = matches[0].end()
                    replacements[name] = body[:end] + ENTRY.encode() + body[end:]
                # 原稿若在head前已有业务script，不能先落盘再让open才发现顺序错误。
                # 在所有写入前对候选字节执行同一精确入口校验，保证“prepared”含义真实。
                if not entry_present(replacements[name]): raise PreparationError("无法安全插入首个受管入口")
                parsed = review.navigation_data(None, [{"path": page}], {page: body})[0]
                entries[name] = {key: parsed[key] for key in ("name", "path", "label", "groups")} | presentation(body) | {"binding": entries.get(name, {}).get("binding")}
            if len(entries) > MAX_DELIVERY_PAGES: raise ValueError("项目登记页面总数超过256")
            ignore = _read_optional(fd, ".gitignore")
            ignored = ignore or b""
            if IGNORE not in ignored.splitlines(): ignored += (b"\n" if ignored and not ignored.endswith(b"\n") else b"") + IGNORE + b"\n"
            with _delivery(root, data_dir, create=True) as (target, published):
                # 发布目录从不放业务原稿。工具链接只允许本项目的显式受管路径。
                links = {"entry.js": cache / "file-entry.js", "shell.js": cache / "shell.js", "assets": cache}
                previous_catalog = _read_optional(published, "catalog.js")
                next_catalog = {"schema_version": 1, "project_id": identity["project_id"], "directory_sha256": directory_sha256(root, prototype),
                    "tool": tool, "pages": sorted(entries.values(), key=lambda page: page["name"])}
                next_body = _catalog_bytes(next_catalog)
                link_changes = []
                mounted = False
                try:
                    for name, destination in links.items():
                        previous = _link_value(published, name)
                        if previous != str(destination):
                            _link_cas(published, name, previous, destination)
                            link_changes.append((name, previous, str(destination)))
                    _write_catalog(published, next_catalog)
                    if old is None:
                        _link_cas(fd, MOUNT, None, target); mounted = True
                    for name, body in replacements.items():
                        _cas(fd, name, originals[name], body); changed.append((name, originals[name], body))
                    _cas(fd, ".gitignore", ignore, ignored)
                    verify_mount(fd, root, prototype, expected_data_dir=data_dir or review.default_data_dir())
                except BaseException:
                    # 跨原稿/公开目录/工具链接没有文件系统多文件事务。逐项补偿只恢复
                    # 与本次输出仍相等的对象；用户新内容和其他请求的旧草稿从不删除。
                    for name, before, written in reversed(changed):
                        _restore(fd, name, before, written)
                    _restore(fd, ".gitignore", ignore, ignored)
                    _restore(published, "catalog.js", previous_catalog, next_body)
                    for name, previous, written in reversed(link_changes):
                        if _link_value(published, name) != written: continue
                        if previous is None: os.unlink(name, dir_fd=published)
                        else: _link_cas(published, name, written, previous)
                    if mounted and _link_value(fd, MOUNT) == str(target): os.unlink(MOUNT, dir_fd=fd)
                    raise
        finally:
            if fd >= 0: os.close(fd)
            os.close(project_fd)
    return {"status": "prepared", "project_id": identity["project_id"], "pages": sorted(pages), "tool": tool}


def require_prepared(root, adapter, pages, *, data_dir=None):
    prototype = _configuration(root, adapter, pages)
    project_fd = workspace._open_root(root, "交付项目")
    fd = -1
    try:
        fd = workspace._walk_directory(project_fd, prototype, "交付原型目录")
        try: value = verify_mount(fd, root, prototype, expected_data_dir=data_dir or review.default_data_dir())
        except (OSError, ValueError) as exc: raise PreparationError("交付入口未准备或已失效；请显式执行 prepare-delivery --root --adapter --pages") from exc
        tool, _ = review.capture_tool(format_version=5)
        if value["tool"] != tool: raise PreparationError("交付工具版本已更新；请重新执行 prepare-delivery")
        registered = {page["path"] for page in value["pages"]}
        for page in pages:
            if page not in registered or not entry_present(review._read_at(fd, Path(page).name)):
                raise PreparationError("具体原稿未准备；请显式执行 prepare-delivery")
        return value
    finally:
        if fd >= 0: os.close(fd)
        os.close(project_fd)


def publish_binding(root, adapter, pages, context, connection, *, data_dir=None):
    """不同请求合并同一项目公开目录；只能更新本次显式页，绝无active_request指针。"""
    with review._project_lock(context, data_dir):
        value = require_prepared(root, adapter, pages, data_dir=data_dir)
        binding = {"request_id": context["request_id"], "review_id": context["review_id"],
            "instance": connection["instance"], "origin": "http://127.0.0.1:" + str(connection["port"])}
        for page in value["pages"]:
            if page["path"] in pages: page["binding"] = binding.copy()
        with _delivery(root, data_dir) as (_, fd): _write_catalog(fd, value)
