"""原型反馈的只读准备、封闭协议与真实来源复核，不承担修订或批准。"""

from __future__ import annotations

import copy
import json
from pathlib import Path
import re
from urllib.parse import urlencode

from lib.documents import prototype_review as review
from lib.documents.prototype_targets import (canonical_target, validate_source_target,
    check_context as _check_context, FeedbackError, _json_bytes, _unique_object, _object,
    _text, _identifier, _relative, _strings, _version, MAX_FEEDBACK_BYTES, MAX_ITEMS,
    MAX_TEXT_LENGTH, MAX_ID_LENGTH, MAX_INTERFACE_REFS, MAX_INTERFACE_LENGTH,
    ITEM_FIELDS, OPTIONAL_ITEM_FIELDS)

from lib.documents import validate_prototype_workspace as workspace


MARKDOWN_PAYLOAD_HEADING = "## Agent Workflow Feedback Payload"
NOTICE = "本结果仅为用户修订输入；当前文字是浏览器摘录，建议文字是修改提案，没有可信已批准基线。不会自动修改文件或授予批准。"


def parse_feedback(raw: bytes) -> dict:
    """在执行任何文件来源核验前拒绝超限、重复键和非标准 JSON 数字。"""
    if not isinstance(raw, bytes) or len(raw) > MAX_FEEDBACK_BYTES:
        raise FeedbackError("反馈文件超过 1 MiB 限额")
    # Markdown 是同一封闭协议的运输包装。只接受固定标题和唯一 json 围栏，
    # 摘要既不能再携带第二份机器输入，也不能靠近似标题制造解释歧义。
    try:
        decoded = raw.decode("utf-8", errors="strict")
        if not decoded.lstrip().startswith("{"):
            lines = decoded.splitlines()
            if lines.count(MARKDOWN_PAYLOAD_HEADING) != 1:
                raise FeedbackError("Markdown 必须包含唯一固定机器载荷标题")
            index = lines.index(MARKDOWN_PAYLOAD_HEADING) + 1
            while index < len(lines) and not lines[index].strip(): index += 1
            fences = [i for i, line in enumerate(lines) if re.match(r"^\s*(`{3,}|~{3,})", line)]
            if index >= len(lines) or lines[index] != "```json" or len(fences) != 2 or fences[0] != index or lines[fences[1]] != "```":
                raise FeedbackError("Markdown 仅允许标题后单个 fenced JSON 机器载荷")
            decoded = "\n".join(lines[index + 1:fences[1]])
        value = json.loads(decoded, object_pairs_hook=_unique_object,
                           parse_constant=lambda _: (_ for _ in ()).throw(FeedbackError("反馈不得含非标准 JSON 数字")))
    except (UnicodeError, json.JSONDecodeError, RecursionError) as exc:
        raise FeedbackError("反馈不是有效的 UTF-8 JSON 对象") from exc
    _object(value, {"schema_version", "context", "anchors", "items"} if isinstance(value, dict) and value.get("schema_version") == 3 else {"schema_version", "context", "items"}, "反馈")
    return value


# 来源捕获归装配域所有；保留公开名称供既有Python调用者复用。
capture_review = review.capture_review


def prepare_review(root: str | Path, adapter: str, plan: str, request_id: str,
                   pages: list[str] | None = None, *, data_dir: str | Path | None = None) -> dict:
    """将固定工具与选定业务页面装配成用户级私有离线快照，不写项目。"""
    review.require_external_data_dir(root, data_dir)
    tool, tools = review.capture_tool()
    context, _, files, navigation = capture_review(root, adapter, plan, request_id, pages, tool=tool)
    published = review.publish_bundle(context, files, tools, navigation, data_dir=data_dir)
    review_url = (Path(published["bundle_path"]) / "index.html").as_uri() + "#" + urlencode({"page": navigation[0]["name"]})
    return {"status": "ready", "context": context, "review_url": review_url, **published}


def validate_feedback(root: str | Path, adapter: str, feedback: dict, *,
                      data_dir: str | Path | None = None) -> dict:
    """重算权威输入并按稳定节点交接；意见字样和哈希相等都不授予修订/批准权限。"""
    # 公开 Python API 与 CLI 使用同样的限额和封闭字段，不信任调用方已做前端校验。
    if len(_json_bytes(feedback)) > MAX_FEEDBACK_BYTES:
        raise FeedbackError("反馈文件超过 1 MiB 限额")
    if isinstance(feedback, dict) and type(feedback.get("schema_version")) is int and feedback["schema_version"] == 3:
        return _validate_feedback_v3(root, adapter, feedback, data_dir=data_dir)
    envelope = _object(feedback, {"schema_version", "context", "items"}, "反馈")
    _version(envelope["schema_version"], "反馈")
    context = _check_context(envelope["context"])
    review.require_external_data_dir(root, data_dir)
    if adapter != context["adapter"]:
        raise FeedbackError("反馈适配器与显式选择不一致")
    items = envelope["items"]
    if not isinstance(items, list) or len(items) > MAX_ITEMS:
        raise FeedbackError("反馈条目须为最多 256 项的数组")
    item_ids = set()
    req_ids = {req["id"] for req in context["requirements"]}
    pages = [page["path"] for page in context["pages"]]
    for item in items:
        _object(item, ITEM_FIELDS, "反馈条目", OPTIONAL_ITEM_FIELDS)
        item_id = _identifier(item["id"], "反馈 ID")
        if item_id in item_ids:
            raise FeedbackError("反馈 ID 不得重复")
        item_ids.add(item_id)
        if _relative(item["page"], "反馈页面") not in pages:
            raise FeedbackError("反馈页面不在本次评审范围")
        _identifier(item["target_id"], "目标 ID", dom=True)
        if not isinstance(item["kind"], str) or item["kind"] not in {"must_change", "suggestion", "question"}:
            raise FeedbackError("反馈等级无效")
        _text(item["message"], "反馈文字", MAX_TEXT_LENGTH)
        associated = _strings(item["req_ids"], "关联需求", len(req_ids), MAX_ID_LENGTH)
        if set(associated) - req_ids:
            raise FeedbackError("关联需求不在当前 Markdown 中")
        if "comparison" in item:
            comparison = _object(item["comparison"], {"before_text", "after_text"}, "局部提案")
            for key in ("before_text", "after_text"):
                _text(comparison[key], "局部提案文字", MAX_TEXT_LENGTH, empty=True)
        if "interaction_id" in item:
            _identifier(item["interaction_id"], "交互契约 ID", dom=True)
        if "interface_refs" in item:
            if not _strings(item["interface_refs"], "接口引用", MAX_INTERFACE_REFS, MAX_INTERFACE_LENGTH):
                raise FeedbackError("没有明确接口引用时必须省略 interface_refs")
    # 原离线包是当轮工具字节的权威；插件升级不要求旧缓存长期保留，
    # 也不允许把旧反馈静默绑定到新工具。项目源则必须每次真实重读。
    review.validate_bundle(context, data_dir=data_dir, format_version=2)
    current, metadata, current_files, navigation = capture_review(root, adapter, context["plan_source"], context["request_id"], pages, tool=context["tool"], format_version=2)
    review.validate_bundle(context, data_dir=data_dir, source_files=current_files, navigation=navigation, format_version=2)
    if current != context:
        raise FeedbackError("反馈绑定已过期或来源不匹配；请保留原意见并重新准备评审")
    changes = {}
    for item in items:
        page = metadata[item["page"]]
        if page["ids"][item["target_id"]] != 1:
            raise FeedbackError("反馈目标不存在或 DOM ID 重复：" + item["target_id"])
        contract = page["contracts"].get(item["target_id"])
        if "interaction_id" in item:
            interaction_id = item["interaction_id"]
            if contract is None or contract["id"] != interaction_id or page["ids"][interaction_id] != 1:
                raise FeedbackError("交互关联不属于当前目标的唯一契约")
        if "interface_refs" in item:
            if contract is None or set(item["interface_refs"]) - contract["interface_refs"]:
                raise FeedbackError("接口引用未在当前目标契约中明确声明")
        key = (item["page"], item["target_id"])
        changes.setdefault(key, {"page": key[0], "target_id": key[1], "items": []})["items"].append(copy.deepcopy(item))
    return {"status": "current", "context": current, "changes": [changes[key] for key in sorted(changes)], "notice": NOTICE}


def _validate_feedback_v3(root, adapter, envelope, *, data_dir=None):
    """独立重建来源后交接三类目标；A 与整改拥有独立稳定编号序列。"""
    _object(envelope, {"schema_version", "context", "anchors", "items"}, "反馈")
    context = _check_context(envelope["context"])
    review.require_external_data_dir(root, data_dir)
    if adapter != context["adapter"]: raise FeedbackError("反馈适配器与显式选择不一致")
    pages = [page["path"] for page in context["pages"]]
    requirements = {req["id"] for req in context["requirements"]}
    anchors, items = envelope["anchors"], envelope["items"]
    anchor_ids = set()
    for entries, label in ((anchors, "定位标记"), (items, "整改")):
        if not isinstance(entries, list) or len(entries) > MAX_ITEMS:
            raise FeedbackError(label + "须为最多256项的数组")
        ids, numbers = set(), set()
        for entry in entries:
            _object(entry, {"id", "number", "target"} if label == "定位标记" else
                    {"id", "number", "operation", "target", "message", "req_ids", "reference_ids"},
                    label, set() if label == "定位标记" else OPTIONAL_ITEM_FIELDS)
            identifier = _identifier(entry["id"], label + "ID")
            number = entry["number"]
            if identifier in ids or type(number) is not int or not 1 <= number <= 9007199254740991 or number in numbers:
                raise FeedbackError(label + "ID/正整数编号必须在本序列唯一")
            ids.add(identifier); numbers.add(number)
            canonical_target(entry["target"], pages)
            scope = entry["target"]["scope"]
            if label == "定位标记":
                if scope != "node": raise FeedbackError("定位标记只允许节点目标")
                anchor_ids.add(identifier)
                continue
            operation = entry["operation"]
            allowed = {"node": {"modify", "add", "delete"}, "page": {"modify", "add"}, "global": {"modify"}}
            if not isinstance(operation, str) or operation not in allowed[scope]: raise FeedbackError("目标范围不支持此整改类型")
            _text(entry["message"], "整改正文", MAX_TEXT_LENGTH, empty=operation == "delete")
            associated = _strings(entry["req_ids"], "关联需求", len(requirements), MAX_ID_LENGTH)
            if set(associated) - requirements: raise FeedbackError("关联需求不在当前Markdown中")
            _strings(entry["reference_ids"], "引用定位标记", MAX_ITEMS, MAX_ID_LENGTH)
            if "comparison" in entry:
                if scope != "node" or operation != "modify": raise FeedbackError("局部提案仅允许节点修改")
                comparison = _object(entry["comparison"], {"before_text", "after_text"}, "局部提案")
                for key in comparison: _text(comparison[key], "局部提案文字", MAX_TEXT_LENGTH, empty=True)
            if "interaction_id" in entry: _identifier(entry["interaction_id"], "交互契约ID", dom=True)
            if "interface_refs" in entry and not _strings(entry["interface_refs"], "接口引用", MAX_INTERFACE_REFS, MAX_INTERFACE_LENGTH):
                raise FeedbackError("没有明确接口引用时必须省略interface_refs")
    if len({review.json_bytes(entry["target"]) for entry in anchors}) != len(anchors):
        raise FeedbackError("同一来源目标不得重复建立定位标记")
    for item in items:
        if set(item["reference_ids"]) - anchor_ids: raise FeedbackError("引用了不存在的定位标记")
    # 先检查当前包身份，再重读项目输入。两个格式互不迁移，也不借新工具验证旧包。
    review.validate_bundle(context, data_dir=data_dir, format_version=3)
    current, metadata, files, navigation = capture_review(root, adapter, context["plan_source"], context["request_id"], pages, tool=context["tool"])
    review.validate_bundle(context, data_dir=data_dir, source_files=files, navigation=navigation, format_version=3)
    if current != context: raise FeedbackError("反馈绑定已过期或来源不匹配；请保留原意见并重新准备评审")
    for entry in anchors + items:
        validate_source_target(entry["target"], metadata)
    for item in items:
        target = item["target"]
        contract = None
        mapped = []
        if target["scope"] == "node":
            page, locator = metadata[target["page"]], target["locator"]
            identifier = locator.get("id")
            contract = page["contracts"].get(identifier) if identifier else None
            mapped = page["req_ids"].get((locator["type"], identifier or locator["key"]), [])
        if set(item["req_ids"]) - set(mapped): raise FeedbackError("需求引用没有明确业务源映射")
        if "interaction_id" in item and (contract is None or contract["id"] != item["interaction_id"]):
            raise FeedbackError("交互关联不属于当前目标的唯一契约")
        if "interface_refs" in item and (contract is None or set(item["interface_refs"]) - contract["interface_refs"]):
            raise FeedbackError("接口引用未在当前目标契约中明确声明")
    changes = {}
    for item in items:
        key = review.json_bytes(item["target"])
        changes.setdefault(key, {"target": copy.deepcopy(item["target"]), "items": []})["items"].append(copy.deepcopy(item))
    return {"status": "current", "context": current, "anchors": copy.deepcopy(anchors),
            "changes": [changes[key] for key in sorted(changes)], "notice": NOTICE}


_capture_review = capture_review
