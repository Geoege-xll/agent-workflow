"""新项目 UI Foundation 的两个固定 QA 检查点，不提供通用阶段引擎。

图仍保存一个 QA 节点与一个原生 Reviewer；阶段 PASS 只解除功能 Writer 的基础
设施前置条件。所有证据通过既有 records 读取与 CAS 发布，模块不派发、不批准。
"""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
from typing import Any

# 脚本入口与包入口统一使用仓库已有 lib 命名空间，避免依赖调用者 cwd。
if not __package__:
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from lib.task_graph import TaskGraphError

SHA_FIELDS = {"task_pack", "handoff"}


def closure(payload: dict, task_id: str) -> set[str]:
    """只沿真实依赖边取 Foundation 闭包；不把同请求的后续功能纳入阶段范围。"""
    indexed = {task["id"]: task for task in payload["tasks"]}
    found, pending = set(), [task_id]
    while pending:
        current = pending.pop()
        if current in found:
            continue
        found.add(current)
        pending.extend(indexed[current]["depends_on"])
    return found


def validate_contract(payload: dict, *, handoff: bool = False) -> None:
    """可选引用只能声明一次；功能依赖 Foundation，自身绝不能依赖 QA。"""
    indexed = {task["id"]: task for task in payload["tasks"]}
    for qa in indexed.values():
        if "request_receipt" in qa:
            if "foundation_task_id" not in qa or not isinstance(qa["request_receipt"], dict) or set(qa["request_receipt"]) != SHA_FIELDS:
                raise TaskGraphError("request_receipt belongs only to Foundation request acceptance")
            for value in qa["request_receipt"].values():
                _reference(value)
        if "foundation_receipt" in qa and "foundation_task_id" not in qa:
            raise TaskGraphError("foundation_receipt requires foundation_task_id")
        if "foundation_task_id" not in qa:
            continue
        reference = qa["foundation_task_id"]
        if (qa.get("task_type") != "qa" or qa.get("workflow_level") != "Full"
                or not isinstance(reference, str) or not reference.strip()):
            raise TaskGraphError("foundation_task_id belongs only to a Full QA task")
        if handoff:
            continue
        foundation = indexed.get(reference)
        if (foundation is None or foundation.get("task_type") != "writer"
                or foundation.get("workflow_level") != "Full"
                or foundation.get("surface_kind") != "production_ui"
                or foundation["request_id"] != qa["request_id"]):
            raise TaskGraphError("foundation_task_id must identify the same request's Full production_ui writer")
        foundation_ids = closure(payload, reference)
        if qa["id"] in foundation_ids:
            raise TaskGraphError("Foundation must not depend on its QA")
        # 阶段审查只有基础设施闭包；同一节点的最终全请求 barrier 由 qa-ready 计算。
        # 因此 QA 不可声明后续功能依赖，否则又会把 Foundation 审查锁死在功能后面。
        if not set(qa["depends_on"]) <= foundation_ids:
            raise TaskGraphError("Foundation QA dependencies must stay inside the Foundation closure")
        for task in indexed.values():
            if (task["request_id"] != qa["request_id"] or task["task_type"] != "writer"
                    or task.get("surface_kind") != "production_ui" or task["id"] in foundation_ids):
                continue
            dependencies = closure(payload, task["id"])
            if reference not in dependencies or qa["id"] in dependencies:
                raise TaskGraphError("production UI features must depend on Foundation, never on the QA node")
        receipt = qa.get("foundation_receipt")
        if receipt is not None:
            fields = {"checkpoint_fingerprint", "agent_ref", "task_pack", "handoff"}
            if not isinstance(receipt, dict) or set(receipt) != fields:
                raise TaskGraphError("foundation_receipt has missing or unsupported fields")
            if receipt["agent_ref"] != qa.get("agent_ref"):
                raise TaskGraphError("foundation_receipt must retain the original Reviewer")
            if not _sha(receipt["checkpoint_fingerprint"]):
                raise TaskGraphError("foundation_receipt requires a checkpoint SHA256")
            for field in SHA_FIELDS:
                _reference(receipt[field])


def _sha(value: Any) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(c in "0123456789abcdef" for c in value)


def _reference(value: Any) -> None:
    if (not isinstance(value, dict) or set(value) != {"path", "sha256"}
            or not isinstance(value["path"], str) or not Path(value["path"]).is_absolute()
            or str(Path(value["path"])) != value["path"] or ".." in Path(value["path"]).parts
            or not _sha(value["sha256"])):
        raise TaskGraphError("QA evidence requires a normalized absolute path and byte SHA256")


def fingerprint(payload: dict, qa: dict, *, root: Path | None = None) -> str:
    """冻结闭包自身合同、构建、内容与采用权威，不绑定整图或集成全局 HEAD。

    内容读取仅遍历闭包 owned_paths，拒绝链接与特殊文件；规则内容沿用既有安全
    读取器。无关 feature 合同、状态及集成 HEAD 均不进入摘要，正常开发不会撤销
    已通过的基础设施；Foundation 返工、证据、采用规范和批准变化会改变摘要。
    """
    from lib import task_graph_records as records
    from lib.runtime_pins import project_root
    selected_root = project_root(root)
    ids = closure(payload, qa["foundation_task_id"])
    tasks = [task for task in payload["tasks"] if task["id"] in ids]
    sources, content, contracts = {}, {}, []
    gates = {gate for task in tasks for gate in task["gates"]}
    for task in sorted(tasks, key=lambda item: item["id"]):
        # blocks 会随正常下游扩展变化；它不是 Foundation 自身实现合同。
        contracts.append({key: value for key, value in task.items()
                          if key not in {"blocks", "agent_retired", "handoff_assessment"}})
        execution_root = Path(task.get("execution_workspace", {}).get("root", selected_root))
        content_roots = {"writer": execution_root}
        integration = payload.get("worktree_integrations", {}).get(task["request_id"])
        if integration:
            # 集成 HEAD 会随正常 feature 变化；只绑定候选中 Foundation 自己的内容，
            # 既检测错误组合/阶段包后改动，又不把无关提交误当成 Foundation 返工。
            content_roots["integration"] = Path(integration["root"])
        for source, content_root in content_roots.items():
            if content_root.is_symlink() or not content_root.is_dir():
                raise TaskGraphError("Foundation content root must be an existing physical directory")
            for relative in task["owned_paths"]:
                target = content_root / relative
                if target.is_symlink() or any(parent.is_symlink() for parent in target.parents if parent != content_root and content_root in parent.parents):
                    raise TaskGraphError("Foundation content must not use symlinks")
                if target.is_dir():
                    paths = sorted(target.rglob("*"))
                else:
                    paths = [target]
                for path in paths:
                    if path.is_symlink():
                        raise TaskGraphError("Foundation content must not use symlinks")
                    if path.is_dir():
                        continue
                    name = path.relative_to(content_root).as_posix()
                    content[f"{source}:{task['id']}:{name}"] = records.file_digest(content_root, name)
        for doc in task.get("controlled_document_access", {}).get("documents", []):
            if doc.get("mode") == "skip":
                continue
            actual = records.document_digest(selected_root, doc["path"], binding=payload.get("runtime_binding"))
            if actual != doc["content_fingerprint"]:
                raise TaskGraphError("Foundation controlled document fingerprint is stale: " + doc["path"])
            sources[doc["path"]] = actual
        for ref in task.get("ui_change", {}).get("design_authority_refs", []):
            actual = records.document_digest(selected_root, ref["path"], binding=payload.get("runtime_binding"))
            if actual != ref["content_fingerprint"]:
                raise TaskGraphError("Foundation design authority fingerprint is stale: " + ref["path"])
            sources[ref["path"]] = actual
    standard = copy.deepcopy(payload["standards_contract"])
    selected_rules = {rule for task in tasks for document in task.get("controlled_document_access", {}).get("documents", [])
                      for rule in document.get("rule_ids", [])}
    standard["leaves"] = [leaf for leaf in standard["leaves"] if leaf["path"] in sources]
    for leaf in standard["leaves"]:
        # 同一内置源可供后续feature采用更多规则；仅新采用的规则不改变Foundation
        # 已审合同，Foundation自己的读取rule_ids变化则仍通过tasks投影使回执失效。
        leaf["rule_ids"] = [rule for rule in leaf["rule_ids"] if rule in selected_rules]
    from lib.task_graph_cli import _paths_overlap
    owned = [path for task in tasks for path in task["owned_paths"]]
    standard["protected_paths"] = [policy for policy in standard["protected_paths"]
                                   if any(_paths_overlap(path, policy["path"]) for path in owned)]
    rules = {rule for leaf in standard["leaves"] for rule in leaf["rule_ids"]}
    for domain in ("engineering", "design"):
        key = f"required_{domain}_rule_ids"
        standard[key] = [rule for rule in standard[key] if rule in rules]
    projection = {"tasks": contracts, "content": content, "sources": sources, "standards": standard,
                  "requirements_fingerprint": payload.get("requirements_fingerprint"),
                  "approved_gates": sorted(set(payload.get("approved_gates", [])) & gates),
                  "ui_contract": payload.get("ui_contract")}
    return hashlib.sha256(json.dumps(projection, ensure_ascii=False, sort_keys=True,
                                     separators=(",", ":")).encode()).hexdigest()


def valid_receipt(payload: dict, qa: dict, *, root: Path | None = None) -> bool:
    """旧或失效证据仅表示阶段未通过；不能因旧 PASS 而解除功能前置条件。"""
    from lib import task_graph_records as records
    receipt = qa.get("foundation_receipt")
    if not receipt:
        return False
    try:
        return (receipt["agent_ref"] == qa.get("agent_ref")
                and receipt["checkpoint_fingerprint"] == fingerprint(payload, qa, root=root)
                and all(records.digest(records.read_record(Path(receipt[key]["path"]))) == receipt[key]["sha256"]
                        for key in SHA_FIELDS))
    except (OSError, ValueError, KeyError):
        return False


def checkpoint(payload: dict, qa: dict) -> dict:
    """只从当前权威图推导两种固定审查范围，调用者不能自报或缩小 writer IDs。"""
    from lib.task_graph import request_closure
    from lib.task_graph_cli import _tasks
    foundation = qa.get("foundation_task_id")
    stage = bool(foundation and not valid_receipt(payload, qa))
    ids = closure(payload, foundation) if stage else request_closure(_tasks(payload), qa["request_id"])
    return {"kind": "foundation" if stage else "request", "writer_ids": sorted(
        task["id"] for task in payload["tasks"] if task["id"] in ids and task["task_type"] == "writer")}


def accept(payload: dict, qa: dict, operation: Any, *, kind: str, root: Path | None = None) -> dict:
    """读取当前原字节包/结论，验证唯一 Reviewer 和范围，再产生受保护记录字段。"""
    from lib import task_graph_records as records
    from lib.task_graph_cli import export_task_pack, _execute
    from lib.delivery.qa_handoff_cli import validate_qa_handoff
    if (qa.get("task_type") != "qa" or "foundation_task_id" not in qa
            or qa.get("state") not in {"QA", "RUNNING"} or qa.get("agent_retired")):
        raise TaskGraphError("checkpoint acceptance requires the active original Foundation Reviewer")
    if not isinstance(operation, dict) or set(operation) != SHA_FIELDS:
        raise TaskGraphError("checkpoint acceptance requires task_pack and handoff byte references")
    bodies = {}
    for field in SHA_FIELDS:
        _reference(operation[field])
        bodies[field] = records.read_record(Path(operation[field]["path"]))
        if records.digest(bodies[field]) != operation[field]["sha256"]:
            raise TaskGraphError("QA checkpoint evidence fingerprint changed")
    pack = records.decode(bodies["task_pack"])
    current = export_task_pack(payload, qa["id"])
    if pack != current or pack.get("qa_checkpoint", {}).get("kind") != kind:
        raise TaskGraphError("QA task pack differs from the current checkpoint")
    candidate = copy.deepcopy(payload)
    candidate["request_id"] = qa["request_id"]
    if not _execute("qa-ready", candidate)["qa_ready"]:
        raise TaskGraphError("QA checkpoint is not ready")
    handoff = records.decode(bodies["handoff"])
    if not isinstance(handoff, dict):
        raise TaskGraphError("QA checkpoint handoff must be an object")
    validate_qa_handoff(handoff, bodies["task_pack"])
    if handoff["audit_result"] != "PASS":
        raise TaskGraphError("QA checkpoint acceptance requires PASS")
    if kind == "foundation":
        return {"state": "DECLARED", "foundation_receipt": {
            "checkpoint_fingerprint": fingerprint(payload, qa, root=root),
            "agent_ref": copy.deepcopy(qa["agent_ref"]), **copy.deepcopy(operation)}}
    return {"state": "QA_PASSED", "request_receipt": copy.deepcopy(operation)}


def validate_publication(target: Path, before: bytes | None, after: bytes) -> None:
    """发布锁内重读新阶段回执，拒绝同一记录自毁证据和计算后的证据替换。"""
    from lib import task_graph_records as records
    if before is None:
        return
    try:
        previous, current = records.decode(before), records.decode(after)
    except (ValueError, UnicodeError):
        return
    # publish同时服务任意普通bytes/JSON；仅schema2图的新QA收据进入本守卫。
    # 非图数据必须沿用原发布语义，不能因碰巧含tasks键而被新机制误判。
    def graph_tasks(value: Any) -> list[dict] | None:
        if (not isinstance(value, dict) or value.get("schema_version") != 2
                or not isinstance(value.get("tasks"), list)
                or any(not isinstance(task, dict) or not isinstance(task.get("id"), str)
                       for task in value["tasks"])):
            return None
        return value["tasks"]
    previous_tasks, current_tasks = graph_tasks(previous), graph_tasks(current)
    if previous_tasks is None or current_tasks is None:
        return
    old = {task["id"]: task for task in previous_tasks}
    for task in current_tasks:
        request = task.get("request_receipt")
        if request and request != old.get(task["id"], {}).get("request_receipt"):
            for reference in request.values():
                path = Path(reference["path"])
                if path.samefile(target) or records.digest(records.read_record(path)) != reference["sha256"]:
                    raise TaskGraphError("new request QA receipt requires unchanged independent evidence")
        receipt = task.get("foundation_receipt")
        if not receipt or receipt == old.get(task["id"], {}).get("foundation_receipt"):
            continue
        for field in SHA_FIELDS:
            reference = receipt[field]
            path = Path(reference["path"])
            if path.samefile(target) or records.digest(records.read_record(path)) != reference["sha256"]:
                raise TaskGraphError("new Foundation receipt requires unchanged independent evidence")
        if not valid_receipt(current, task):
            raise TaskGraphError("Foundation changed before receipt publication")
