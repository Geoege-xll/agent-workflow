"""反馈4的封闭输入合同和纯交接投影；不读写文件，也不负责来源信任。

调用者必须先按真实项目定位不可变包并重读全部来源，才能使用本模块生成
交接。浏览器只提交用户输入；REQ、交互和接口关联始终从重读的目标还原。
"""
from __future__ import annotations

import copy

from lib.documents.prototype_targets import (
    FeedbackError, MAX_ITEMS, MAX_TEXT_LENGTH, MAX_ID_LENGTH, MAX_INTERFACE_REFS,
    MAX_INTERFACE_LENGTH, SHA_PATTERN, canonical_target, validate_source_target,
    json_bytes, _object, _identifier, _strings, _text,
)

NOTICE = "本结果仅为用户修订输入，不代表批准，也不会自动修改文件。"


def check_review_reference(value: object) -> dict:
    """短引用只有稳定请求ID与64位内容身份，不接受路径或完整上下文。"""
    reference = _object(value, {"request_id", "review_id"}, "评审短引用")
    _identifier(reference["request_id"], "请求 ID")
    if not isinstance(reference["review_id"], str) or not SHA_PATTERN.fullmatch(reference["review_id"]):
        raise FeedbackError("评审短引用摘要无效")
    return reference


def check_feedback(value: object, pages: list[str]) -> dict:
    """校验独立序列的稳定ID/编号、三类目标及仅用户可编辑字段。"""
    envelope = _object(value, {"schema_version", "review", "anchors", "items"}, "反馈")
    if type(envelope["schema_version"]) is not int or envelope["schema_version"] != 4:
        raise FeedbackError("反馈版本须为4")
    check_review_reference(envelope["review"])
    anchor_ids = set()
    for field in ("anchors", "items"):
        entries = envelope[field]
        if not isinstance(entries, list) or len(entries) > MAX_ITEMS:
            raise FeedbackError(field + "须为最多256项的数组")
        ids, numbers = set(), set()
        for entry in entries:
            anchor = field == "anchors"
            _object(entry, {"id", "number", "target"} if anchor else
                    {"id", "number", "operation", "target", "message"}, field,
                    set() if anchor else {"reference_ids", "after_text"})
            identifier = _identifier(entry["id"], field + "ID")
            number = entry["number"]
            if identifier in ids or type(number) is not int or not 1 <= number <= 9007199254740991 or number in numbers:
                raise FeedbackError(field + "ID/正整数编号必须在本序列唯一")
            ids.add(identifier); numbers.add(number)
            canonical_target(entry["target"], pages)
            scope = entry["target"]["scope"]
            if anchor:
                if scope != "node": raise FeedbackError("定位标记只允许节点目标")
                anchor_ids.add(identifier)
                continue
            operation = entry["operation"]
            allowed = {"node": {"modify", "add", "delete"}, "page": {"modify", "add"}, "global": {"modify"}}
            if not isinstance(operation, str) or operation not in allowed[scope]:
                raise FeedbackError("目标范围不支持此整改类型")
            _text(entry["message"], "整改正文", MAX_TEXT_LENGTH, empty=operation == "delete")
            if "reference_ids" in entry and not _strings(entry["reference_ids"], "引用定位标记", MAX_ITEMS, MAX_ID_LENGTH):
                raise FeedbackError("没有引用时必须省略reference_ids")
            if "after_text" in entry:
                if scope != "node" or operation != "modify": raise FeedbackError("建议文字仅允许节点修改")
                _text(entry["after_text"], "建议文字", MAX_TEXT_LENGTH)
    if len({json_bytes(entry["target"]) for entry in envelope["anchors"]}) != len(envelope["anchors"]):
        raise FeedbackError("同一来源目标不得重复建立定位标记")
    for item in envelope["items"]:
        if set(item.get("reference_ids", [])) - anchor_ids:
            raise FeedbackError("引用了不存在的定位标记")
    return envelope


def compact_handoff(envelope: dict, context: dict, metadata: dict) -> dict:
    """按目标只交还一次来源关联；同目标多意见保留原ID、编号与用户文字。

    有整改时只交还真正被引用的A，且跨页引用不按当前页面裁切。仅有A时
    原样交还全部明确标记，不从定位推断整改。两者都不修改输入/草稿状态。
    """
    for entry in envelope["anchors"] + envelope["items"]:
        validate_source_target(entry["target"], metadata)
    changes = {}
    requirements = set(context["requirements"])
    referenced = set()
    for item in envelope["items"]:
        target = item["target"]
        key = json_bytes(target)
        if key not in changes:
            group = {"target": copy.deepcopy(target), "items": []}
            if target["scope"] == "node":
                page, locator = metadata[target["page"]], target["locator"]
                identifier = locator.get("id")
                mapped = page["req_ids"].get((locator["type"], identifier or locator["key"]), [])
                if set(mapped) - requirements:
                    raise FeedbackError("来源节点的需求关联不在当前Markdown中")
                if mapped: group["req_ids"] = list(mapped)
                contract = page["contracts"].get(identifier) if identifier else None
                if contract is not None:
                    if contract["id"] is not None:
                        group["interaction_id"] = _identifier(contract["id"], "交互契约ID", dom=True)
                    references = sorted(contract["interface_refs"])
                    if references:
                        group["interface_refs"] = _strings(references, "接口引用", MAX_INTERFACE_REFS, MAX_INTERFACE_LENGTH)
            changes[key] = group
        changes[key]["items"].append(copy.deepcopy({field: value for field, value in item.items() if field != "target"}))
        referenced.update(item.get("reference_ids", []))
    anchors = [entry for entry in envelope["anchors"] if not envelope["items"] or entry["id"] in referenced]
    return {"status": "current", "review": copy.deepcopy(envelope["review"]), "anchors": copy.deepcopy(anchors),
            "changes": [changes[key] for key in sorted(changes)], "notice": NOTICE}
