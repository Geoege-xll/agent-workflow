"""活动原稿与意见的唯一来源边界：只存元数据和草稿，不发布业务HTML副本。"""
from __future__ import annotations

from contextlib import contextmanager
import copy
import fcntl
import math
import os
from pathlib import Path
import uuid

from lib.documents import prototype_review as review
from lib.documents.prototype_handoff import check_feedback, check_review_reference, compact_handoff
from lib.documents.prototype_targets import (FeedbackError, MAX_FEEDBACK_BYTES, canonical_target,
    check_context, json_bytes, validate_source_target, _identifier, _object, _strings, _text)


class LiveError(FeedbackError):
    """可安全返回的业务错误；HTTP映射只消费稳定code，不暴露文件或认证信息。"""
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


@contextmanager
def draft_lock(directory_fd):
    """并发保存的锁争用也是CAS冲突，不能落入通用400或无限等待另一标签。"""
    fd = os.dup(directory_fd)
    try:
        try: fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise LiveError("draft_conflict", "另一窗口正在保存草稿；当前输入保留，请重新核对。") from exc
        yield
    finally: os.close(fd)


def capture_live(root, adapter, plan, request_id, pages=None, *, tool=None, context_version=4, registered_context=None):
    """新登记绑定活动来源与当前需求语义；重读按该修订保存的上下文版本捕获。"""
    if tool is None: tool, _ = review.capture_tool(format_version=5)
    # live目录只来自显式登记页；不可沿用历史离线包对可选index壳的身份绑定。
    return review.capture_review(root, adapter, plan, request_id, pages, tool=tool, format_version=4,
                                 navigation_source="registered_pages", context_version=context_version,
                                 registered_context=registered_context)


@contextmanager
def live_directory(context, data_dir, *, create=False):
    """live目录与历史不可变包平行，短引用永不通过活动指针寻找另一个修订。"""
    with review._request_directory(context, data_dir, create=create) as (path, request_fd):
        live_fd = version_fd = -1
        try:
            live_fd = review._child(request_fd, "live", create=create)
            version_fd = review._child(live_fd, context["review_id"], create=create)
            yield path / "live" / context["review_id"], version_fd
        finally:
            if version_fd >= 0: os.close(version_fd)
            if live_fd >= 0: os.close(live_fd)


def replace_json(fd: int, name: str, value: dict):
    """私有已验证目录内写完整临时文件再原子换名；失败保留旧数据和诊断文件。"""
    temporary = ".writing-" + uuid.uuid4().hex
    review._write_at(fd, temporary, json_bytes(value), mode=0o600)
    os.replace(temporary, name, src_dir_fd=fd, dst_dir_fd=fd)
    os.fsync(fd)


def read_json(fd, name, limit):
    # 旧安全读取器把ENOENT包装为ValidationError；新可选记录先在同一已打开目录
    # 区分“不存在”，已有文件仍必须经过no-follow/唯一普通文件/属主/大小复核。
    os.stat(name, dir_fd=fd, follow_symlinks=False)
    return review._closed_json(review._read_at(fd, name, limit))


def register_live(root, context, *, data_dir=None):
    review.require_external_data_dir(root, data_dir)
    check_context(context, compact_source="live")
    value = {"schema_version": 5, "kind": "live", "context": context}
    with live_directory(context, data_dir, create=True) as (_, fd), review._lock(fd):
        try:
            old = read_json(fd, "metadata.json", review.MAX_MANIFEST_BYTES)
        except FileNotFoundError:
            review._write_at(fd, "metadata.json", json_bytes(value))
        else:
            if old != value: raise FeedbackError("活动原稿元数据与修订不一致")


def resolve_live(root, reference, *, data_dir=None):
    reference = check_review_reference(reference)
    review.require_external_data_dir(root, data_dir)
    identity = {"project_id": review.project_id(Path(root)), **reference}
    with live_directory(identity, data_dir) as (_, fd):
        value = review._closed_json(review._read_at(fd, "metadata.json", review.MAX_MANIFEST_BYTES))
    _object(value, {"schema_version", "kind", "context"}, "活动原稿元数据")
    if type(value["schema_version"]) is not int or value["schema_version"] != 5 or value["kind"] != "live":
        raise FeedbackError("短引用不是活动原稿5")
    context = check_context(value["context"], compact_source="live")
    if any(context[key] != identity[key] for key in identity): raise FeedbackError("活动原稿不属于当前项目或修订")
    return context


def require_current(root, context):
    """来源身份固定在登记时；重读失败也按来源变化处理，旧草稿仍允许读取。"""
    try:
        current, metadata, files, navigation = capture_live(root, context["adapter"], context["plan_source"],
            context["request_id"], [page["path"] for page in context["pages"]], tool=context["tool"],
            context_version=context["schema_version"], registered_context=context)
        if current != context: raise FeedbackError("来源修订已改变")
        return metadata, files, navigation
    except (ValueError, OSError, UnicodeError) as exc:
        raise LiveError("source_changed", "原稿已变化或暂时无法安全确认；原意见保留，请重新核对原稿后打开新评审。") from exc


def check_feedback5(value, pages):
    """反馈5复用已冻结的纯紧凑条目合同，版本转投影不改变输入对象或旧4语义。"""
    _object(value, {"schema_version", "review", "anchors", "items"}, "反馈5")
    if type(value["schema_version"]) is not int or value["schema_version"] != 5: raise FeedbackError("反馈版本须为5")
    check_feedback({**value, "schema_version": 4}, pages)
    return value


def validate_live_feedback(root, adapter, value, *, data_dir=None):
    _object(value, {"schema_version", "review", "anchors", "items"}, "反馈5")
    context = resolve_live(root, value.get("review"), data_dir=data_dir)
    if adapter != context["adapter"]: raise FeedbackError("反馈适配器与显式选择不一致")
    check_feedback5(value, [page["path"] for page in context["pages"]])
    metadata, _, _ = require_current(root, context)
    return compact_handoff(value, context, metadata)


def check_draft(value, context, metadata):
    """服务器复核封闭state快照；未完成文字可恢复，但不能携带任意对象/伪造来源。"""
    if value is None: return None
    _object(value, {"schema_version", "review_id", "anchors", "items", "drafts", "withdrawn",
        "nextAnchor", "nextItem", "cameras"}, "草稿快照")
    if type(value["schema_version"]) is not int or value["schema_version"] != 5 or value["review_id"] != context["review_id"]:
        raise FeedbackError("草稿修订不一致")
    pages = [page["path"] for page in context["pages"]]
    def positive(number):
        if type(number) is not int or not 1 <= number <= 9007199254740991: raise FeedbackError("草稿编号无效")
    def target(entry, *, nullable=False):
        if nullable and entry is None: return
        canonical_target(entry, pages)
        validate_source_target(entry, metadata)
    def refs(values):
        for value in _strings(values, "草稿引用", 256, 128): _identifier(value, "草稿引用ID")
    def requirements(values):
        if set(_strings(values, "草稿需求", len(context["requirements"]), 128)) - set(context["requirements"]):
            raise FeedbackError("草稿需求不属于原稿")
    def extra(entry):
        if "interaction_id" in entry: _identifier(entry["interaction_id"], "草稿交互", dom=True)
        if "interface_refs" in entry: _strings(entry["interface_refs"], "草稿接口", 32, 512)
    def item(entry):
        _object(entry, {"id", "number", "operation", "target", "message", "req_ids", "reference_ids"},
            "草稿整改", {"comparison", "interaction_id", "interface_refs"})
        compact = {key: entry[key] for key in ("id", "number", "operation", "target", "message")}
        check_feedback({"schema_version": 4, "review": {key: context[key] for key in ("request_id", "review_id")},
            "anchors": [], "items": [compact]}, pages)
        target(entry["target"]); refs(entry["reference_ids"]); requirements(entry["req_ids"]); extra(entry)
        if "comparison" in entry:
            if entry["target"]["scope"] != "node" or entry["operation"] != "modify": raise FeedbackError("局部提案范围无效")
            comparison = _object(entry["comparison"], {"before_text", "after_text"}, "局部提案")
            for text in comparison.values(): _text(text, "局部提案文字", 4000, empty=True)
    def draft(entry):
        _object(entry, {"target", "operation", "message", "after_text", "reference_ids", "editing", "excerpt",
            "req_ids", "interaction_id", "interface_refs"}, "未完成草稿")
        target(entry["target"], nullable=True)
        if entry["operation"] not in ("modify", "add", "delete"): raise FeedbackError("草稿操作无效")
        for key in ("message", "after_text", "excerpt"): _text(entry[key], "草稿文字", 4000, empty=True)
        refs(entry["reference_ids"]); requirements(entry["req_ids"])
        if entry["editing"] is not None: _identifier(entry["editing"], "编辑ID")
        if entry["interaction_id"] != "": _identifier(entry["interaction_id"], "交互ID", dom=True)
        _strings(entry["interface_refs"], "接口引用", 32, 512)
    for field in ("anchors", "items"):
        entries = value[field]
        if not isinstance(entries, list) or len(entries) > 256: raise FeedbackError("草稿条目超限")
        ids, numbers = set(), set()
        for entry in entries:
            if field == "items": item(entry)
            else:
                _object(entry, {"id", "number", "target"}, "草稿标记")
                target(entry["target"])
                if entry["target"]["scope"] != "node": raise FeedbackError("标记只能定位节点")
            _identifier(entry["id"], "条目ID"); positive(entry["number"])
            if entry["id"] in ids or entry["number"] in numbers: raise FeedbackError("草稿ID或编号重复")
            ids.add(entry["id"]); numbers.add(entry["number"])
        next_number = value["nextAnchor" if field == "anchors" else "nextItem"]
        positive(next_number)
        if any(number >= next_number for number in numbers): raise FeedbackError("草稿后续编号无效")
    if len({json_bytes(entry["target"]) for entry in value["anchors"]}) != len(value["anchors"]):
        raise FeedbackError("草稿标记重复定位同一目标")
    drafts = value["drafts"]
    if not isinstance(drafts, dict) or len(drafts) > 256: raise FeedbackError("未完成草稿超限")
    item_ids = {entry["id"] for entry in value["items"]}
    for key, entry in drafts.items():
        _text(key, "草稿键", 2048); draft(entry)
        # JS JSON.stringify保留target字段顺序，语义比较后再核对编辑键；不以Python排序冒充同一字符串。
        if entry["editing"] is not None:
            if key != "edit:" + entry["editing"] or entry["editing"] not in item_ids: raise FeedbackError("草稿编辑关联无效")
        elif entry["target"] is None:
            if key != "unresolved": raise FeedbackError("未定位草稿键无效")
        elif review._closed_json(key.encode("utf-8")) != entry["target"]: raise FeedbackError("草稿目标键无效")
    withdrawn = value["withdrawn"]
    if withdrawn is not None:
        _object(withdrawn, {"item", "draft"}, "撤回记录"); item(withdrawn["item"])
        old = withdrawn["item"]
        if old["id"] in item_ids or any(entry["number"] == old["number"] for entry in value["items"]) or old["number"] >= value["nextItem"]:
            raise FeedbackError("撤回记录与当前序列冲突")
        if withdrawn["draft"] is not None:
            draft(withdrawn["draft"])
            if withdrawn["draft"]["editing"] != old["id"]: raise FeedbackError("撤回草稿绑定无效")
    cameras = value["cameras"]
    if not isinstance(cameras, dict) or set(cameras) - set(pages): raise FeedbackError("相机页面无效")
    for camera in cameras.values():
        _object(camera, {"k", "x", "y"}, "相机")
        if any(type(number) not in {int, float} or not math.isfinite(number) for number in camera.values()): raise FeedbackError("相机数字无效")
        if not .08 <= camera["k"] <= 3 or abs(camera["x"]) >= 1e7 or abs(camera["y"]) >= 1e7: raise FeedbackError("相机范围无效")
    if len(json_bytes(value)) > MAX_FEEDBACK_BYTES: raise FeedbackError("草稿超过1MiB")
    return value


class LiveSource:
    """单服务实例固定一个原稿修订；并发草稿由磁盘修订号与目录锁共同约束。"""
    def __init__(self, root, context, *, data_dir=None):
        self.root, self.context, self.data_dir = Path(root), copy.deepcopy(context), data_dir

    def current(self): return require_current(self.root, self.context)

    def read_draft(self):
        with live_directory(self.context, self.data_dir) as (_, fd):
            try: value = read_json(fd, "draft.json", MAX_FEEDBACK_BYTES)
            except FileNotFoundError: return {"revision": 0, "draft": None}
        _object(value, {"revision", "draft"}, "草稿记录")
        if type(value["revision"]) is not int or not 0 <= value["revision"] <= 9007199254740991:
            raise FeedbackError("草稿记录修订无效")
        # 原稿变化后仍允许取回旧正文；不尝试用新metadata验证或重绑旧定位。
        if value["draft"] is not None:
            saved = _object(value["draft"], {"schema_version", "review_id", "anchors", "items", "drafts", "withdrawn",
                "nextAnchor", "nextItem", "cameras"}, "已保存草稿")
            if type(saved["schema_version"]) is not int or saved["schema_version"] != 5 or saved["review_id"] != self.context["review_id"]:
                raise FeedbackError("草稿记录绑定无效")
        return value

    def save_draft(self, revision, draft):
        if type(revision) is not int or not 0 <= revision < 9007199254740991: raise FeedbackError("草稿修订须为非负安全整数")
        with live_directory(self.context, self.data_dir) as (_, fd), draft_lock(fd):
            metadata, _, _ = self.current()
            check_draft(draft, self.context, metadata)
            if self.read_draft()["revision"] != revision:
                raise LiveError("draft_conflict", "另一标签页已保存新草稿；当前输入保留，请重新核对后保存。")
            result = {"revision": revision + 1, "draft": copy.deepcopy(draft)}
            if len(json_bytes(result)) > MAX_FEEDBACK_BYTES: raise FeedbackError("草稿记录超过1MiB，旧意见保留")
            replace_json(fd, "draft.json", result)
            return result
