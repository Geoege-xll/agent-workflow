"""任务图中 Writer 的正式准入、页面视觉批准与任务级例外确认。

图允许保存待决合同。就绪、导出与新交付登记消费同一份当前权威，
独立查询不会生成视觉批准，也不把领取后的自有锁误判为缺少业务批准。
"""
from __future__ import annotations

import copy
import re
from pathlib import Path

from lib.task_graph import TaskGraphError, delivery_complete
from lib.visual_authority import check_visual_page, prototype_owners


def business_confirmation(task: dict) -> None:
    """同一任务中的业务例外必须逐门对应。旧保护路径合同单独按原标准例外规则严格校验。"""
    gates = {gate for gate in task["gates"] if gate.startswith("exceptional:")}
    protected = set()
    if task.get("task_type") == "writer":
        # 仅 Writer 完整走过保护路径合同校验，其他角色不能凭借同名字段伪造例外。
        protected = {item["gate"] for item in task.get("standards_exceptions", [])}
    record = task.get("additional_business_confirmation")
    if "additional_business_confirmation" not in task:
        if gates - protected:
            raise TaskGraphError("exceptional gate requires its task's additional_business_confirmation")
        return
    fields = {"name", "reason", "decision_scope", "options", "evidence", "resume_condition"}
    if not isinstance(record, dict) or set(record) != fields:
        raise TaskGraphError("additional_business_confirmation requires name, reason, decision_scope, options, evidence and resume_condition")
    for field in ("name", "reason", "decision_scope", "resume_condition"):
        if not _concrete(record[field]):
            raise TaskGraphError(f"additional_business_confirmation.{field} must contain concrete text")
    for field in ("options", "evidence"):
        _entries(record[field], f"additional_business_confirmation.{field}")
    name = record["name"]
    gate = name if name.startswith("exceptional:") else f"exceptional:{name}"
    if gate not in gates or gates - protected - {gate}:
        raise TaskGraphError("additional_business_confirmation must match the task's exceptional gate")


def reviewed_business_confirmations(writers: list[dict]) -> list[dict]:
    """投影受审 Writer 的例外问项，非 UI 业务决定同样随其当前 QA 检查点交接。"""
    result = []
    for writer in writers:
        if writer.get("task_type") == "writer" and "additional_business_confirmation" in writer:
            record = writer["additional_business_confirmation"]
            gate = "exceptional:" + record["name"].removeprefix("exceptional:")
            result.append({"writer_id": writer["id"], "request_id": writer["request_id"], "gates": [gate],
                           "additional_business_confirmation": copy.deepcopy(record)})
    return sorted(result, key=lambda item: item["writer_id"])


def _concrete(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip()) and value.strip().lower() not in {
        "none", "tbd", "unknown", "n/a", "null", "[]", "{}", "待定"}


def _entries(value: object, label: str) -> None:
    if not isinstance(value, list) or not value or any(not _concrete(item) for item in value):
        raise TaskGraphError(f"{label} requires a non-empty list of concrete text")


def _prototype_refs(task: dict) -> list[dict]:
    return [ref for ref in task.get("ui_change", {}).get("design_authority_refs", [])
            if ref["kind"] == "prototype_contract"]


def _gate(page_id: str, fingerprint: str) -> str:
    return f"visual_approved:{page_id}@{fingerprint}"


def _page_source(task: dict, graph: dict, page: dict) -> dict:
    """精确绑定任务、需求、稳定页面及本轮视觉范围；不能把另一个请求的用户答复移入本包。"""
    if task.get("ui_change", {}).get("prototype_policy") != "required":
        raise TaskGraphError("visual approval requires a required-prototype production writer")
    if (page["request_id"] != task["request_id"] or page["task_id"] != task["id"]
            or not isinstance(page["requirements_fingerprint"], str)
            or not re.fullmatch(r"[a-f0-9]{64}", page["requirements_fingerprint"])
            or page["requirements_fingerprint"] != graph.get("requirements_fingerprint")):
        raise TaskGraphError("visual approval does not match the current request, task and requirements")
    matches = [ref for ref in _prototype_refs(task) if
               (ref["authority_id"], ref["path"]) == (page["authority_id"], page["path"])]
    if len(matches) != 1:
        raise TaskGraphError("visual approval does not match a current concrete page")
    if not isinstance(page["approval_ref"], str) or not re.fullmatch(r"user:[a-z0-9][a-z0-9._:/-]*", page["approval_ref"]):
        raise TaskGraphError("visual approval requires the explicit user approval_ref")
    _entries(page["changed_scope"], "visual approval changed_scope")
    _entries(page["interactions"], "visual approval interactions")
    if not isinstance(page["dependency_fingerprint"], str) or not re.fullmatch(r"[a-f0-9]{64}", page["dependency_fingerprint"]):
        raise TaskGraphError("visual approval requires a lowercase page dependency fingerprint")
    return matches[0]


PAGE_FIELDS = {"request_id", "task_id", "requirements_fingerprint", "authority_id", "path",
               "dependency_fingerprint", "approval_ref", "changed_scope", "interactions"}


def validate_visual_record(graph: dict, task: dict) -> None:
    if "visual_approval" not in task:
        return
    record = task["visual_approval"]
    if (not isinstance(record, dict) or set(record) != {"status", "pages"} or record["status"] != "approved"
            or not isinstance(record["pages"], list) or not record["pages"]):
        raise TaskGraphError("visual_approval requires approved concrete pages")
    seen = set()
    for page in record["pages"]:
        if not isinstance(page, dict) or set(page) != PAGE_FIELDS:
            raise TaskGraphError("visual_approval contains an incomplete page receipt")
        ref = _page_source(task, graph, page)
        if page["path"] in seen or ref["content_fingerprint"] != page["dependency_fingerprint"]:
            raise TaskGraphError("visual_approval contains a duplicate or stale page binding")
        seen.add(page["path"])


def recheck_visual_publication(before: bytes | None, after: bytes, root: Path | None) -> None:
    """在图的 CAS 锁内复核本次登记页面的真实字节，避免计算结束后、落盘前发生资源漂移。"""
    from lib.task_graph_records import decode
    if before is None:
        return
    try:
        previous, current = decode(before), decode(after)
    except (ValueError, UnicodeError):
        return
    # publish 也用于普通字节和单个包的导出；只检查现有权威图中发生更改的视觉回执。
    if not all(isinstance(value, dict) and value.get("schema_version") == 2
               and isinstance(value.get("tasks"), list) for value in (previous, current)):
        return
    old = {item["id"]: item for item in previous["tasks"] if isinstance(item, dict) and isinstance(item.get("id"), str)}
    from lib.solution_confirmation import EXECUTING_OR_DELIVERED
    for task in current["tasks"]:
        if (not isinstance(task, dict) or not isinstance(task.get("id"), str)
                or task.get("task_type") != "writer" or task.get("ui_change", {}).get("prototype_policy") != "required"):
            continue
        earlier = old.get(task["id"], {})
        receipt = task.get("visual_approval")
        if receipt and receipt != earlier.get("visual_approval"):
            validate_visual_record(current, task)
            previous_pages = earlier.get("visual_approval", {}).get("pages", [])
            for page in receipt["pages"]:
                if page not in previous_pages:
                    check_visual_page(current, task, page, root, stage="approval")
        if task["state"] != earlier.get("state") and task["state"] in EXECUTING_OR_DELIVERED:
            # 领取或登记交付也可能恰遇 worktree 被移动、重置或换掉 CSS。此处
            # 在 CAS 锁里按现有依赖及批准再查一次，包括只有旧视觉门的历史图。
            require_writer(current, task, root)


def writer_blockers(graph: dict, task: dict, root: Path | None, *, review_request: str | None = None) -> list[str]:
    """只查本 Writer 的门、传递交付与适用的 Foundation 回执；不引入可用槽位/他人排队顺序。"""
    if task["task_type"] != "writer":
        return []
    from lib.foundation_qa import closure, current_request_receipt, is_full_reviewer, valid_receipt
    missing = sorted(set(task["gates"]) - set(graph.get("approved_gates", [])))
    blockers = ["missing writer approvals: " + ", ".join(missing)] if missing else []
    needed = closure(graph, task["id"]) - {task["id"]} if task.get("depends_on") else set()
    waiting = sorted(item["id"] for item in graph["tasks"] if item["id"] in needed and (
        not delivery_complete(item["task_type"], item["state"]) or
        is_full_reviewer(item)
        and not current_request_receipt(graph, item, root=root)))
    if waiting:
        blockers.append("prerequisite delivery: " + ", ".join(waiting))
    if task.get("surface_kind") != "production_ui":
        return blockers
    for qa in graph["tasks"]:
        if (qa["request_id"] == task["request_id"] and qa.get("foundation_task_id") in needed
                and not valid_receipt(graph, qa, root=root)):
            blockers.append("missing current Foundation QA receipt")
    for ref in _prototype_refs(task):
        gate = _gate(ref["authority_id"], ref["content_fingerprint"])
        if gate not in task["gates"] or gate in missing:
            continue
        # 门的旧公开格式只有页面 ID 和摘要。不同请求/物理路径共用门值时，
        # 只有匹配当前请求及页面的来源可以解锁；单一语义的旧批准保持兼容。
        users = [item for item in graph["tasks"] if gate in item["gates"]]
        identities = {(item["request_id"], r["path"]) for item in users for r in _prototype_refs(item)
                      if _gate(r["authority_id"], r["content_fingerprint"]) == gate}
        pages = [page for item in users for page in item.get("visual_approval", {}).get("pages", [])
                 if (page["request_id"], page["path"], page["authority_id"], page["dependency_fingerprint"])
                 == (task["request_id"], ref["path"], ref["authority_id"], ref["content_fingerprint"])]
        if not pages and len(identities) > 1:
            blockers.append("ambiguous visual approval requires a request-bound page receipt")
        # 单一语义的旧图也有完整的页面权威和门值，沿用原批准并重算物理页。
        # 即使旧图还没有 approve_visuals 的来源记录，删除文件或篡改 CSS 也不能继续写。
        try:
            check_visual_page(graph, task, {"path": ref["path"], "dependency_fingerprint": ref["content_fingerprint"]},
                              root, stage="qa" if review_request else "writer", review_request=review_request)
        except (OSError, ValueError) as exc:
            blockers.append(f"stale visual approval: {exc}")
    return blockers


def require_writer(graph: dict, task: dict, root: Path | None) -> None:
    blockers = writer_blockers(graph, task, root)
    if blockers:
        raise TaskGraphError(f"writer {task['id']} requires current prerequisites: " + "; ".join(blockers))


def record_visuals(graph: dict, approvals: object, root: Path | None) -> None:
    """只在原子 CAS 补丁中记录用户确已确认的具体页，允许已交付原型变更后原位改绑。"""
    if not isinstance(approvals, list) or not approvals:
        raise TaskGraphError("approve_visuals requires a non-empty array")
    indexed = {task["id"]: task for task in graph["tasks"]}
    seen = set()
    obsolete = set()
    for item in approvals:
        if not isinstance(item, dict) or set(item) != PAGE_FIELDS | {"previous_fingerprint"}:
            raise TaskGraphError("approve_visuals requires the complete page approval and previous_fingerprint")
        task_id = item["task_id"]
        if not isinstance(task_id, str) or task_id not in indexed:
            raise TaskGraphError("approve_visuals requires a current Writer")
        task = indexed[task_id]
        page = {key: copy.deepcopy(value) for key, value in item.items() if key != "previous_fingerprint"}
        ref = _page_source(task, graph, page)
        key = (task_id, ref["path"])
        if key in seen or ref["content_fingerprint"] != item["previous_fingerprint"]:
            raise TaskGraphError("approve_visuals duplicate page or stale previous_fingerprint")
        seen.add(key)
        # 用户可按页确认，未完成的兄弟页面不阻塞本页。精确定位同请求拥有本页的
        # 原型 Writer，并检查它实际交付以及自己的需求、方案和其他前置。
        path = Path(ref["path"])
        owners = prototype_owners(graph, task, path)
        if not owners or any(not delivery_complete(owner["task_type"], owner["state"]) or
                             writer_blockers(graph, owner, root) for owner in owners):
            raise TaskGraphError("approve_visuals requires current delivered prototype evidence")
        check_visual_page(graph, task, page, root, stage="approval")
        pages = task.setdefault("visual_approval", {"status": "approved", "pages": []})["pages"]
        previous_page = next((stored for stored in pages if stored["path"] == page["path"]), None)
        if previous_page != page and task["state"] not in {"DECLARED", "BLOCKED", "READY", "FAILED"}:
            raise TaskGraphError("revised visual approval requires a pending production writer")
        old_gate = _gate(ref["authority_id"], ref["content_fingerprint"])
        new_gate = _gate(ref["authority_id"], page["dependency_fingerprint"])
        ref["content_fingerprint"] = page["dependency_fingerprint"]
        task["gates"][task["gates"].index(old_gate)] = new_gate
        if previous_page is None:
            pages.append(page)
        else:
            pages[pages.index(previous_page)] = page
        obsolete.add(old_gate)
        if new_gate not in graph.setdefault("approved_gates", []):
            graph["approved_gates"].append(new_gate)
    # 只清理所有消费者都已离开的旧门。未改绑的其他页面或任务保留其历史来源。
    used = {gate for task in graph["tasks"] for gate in task["gates"]}
    graph["approved_gates"] = [gate for gate in graph["approved_gates"] if gate not in obsolete - used]
