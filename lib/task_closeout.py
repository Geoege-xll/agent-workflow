"""Project post-acceptance actions from existing authoritative task records."""

from pathlib import Path
import os
import re

from lib import task_graph_records as records
from lib.agent_continuation import HOSTS, validate_reference
from lib.foundation_qa import current_request_receipt
from lib.request_scope import request_scopes
from lib.task_graph import TaskGraphError, delivery_complete
from lib.task_settlement import _evidence


FIELD = "native_closeout"
LEGACY_PREFIX = "Native closeout receipt: "


def request_tasks(snapshots, request_id):
    return sorted(
        ((snap, task) for snap in snapshots for task in snap.tasks if task["request_id"] == request_id),
        key=lambda item: (item[0].descriptor["path"], item[1]["id"]),
    )


def accepted(root, rows):
    if not rows:
        return "request_not_registered"
    if any(snap.external_occupancy for snap, _ in rows):
        return "record_occupancy_unresolved"
    if any(not delivery_complete(task["task_type"], task["state"])
           and not (task["state"] == "WITHDRAWN" and not task.get("agent_ref")) for _, task in rows):
        return "request_contains_unaccepted_work"
    reviewers = [(snap, task) for snap, task in rows if task["task_type"] == "qa"]
    full = any(task["workflow_level"] == "Full" and task["task_type"] == "writer"
               and request_scopes(snap.source).get(task["request_id"]) != "prototype_only"
               for snap, task in rows)
    required = full or any(task.get("handoff_assessment", {}).get("independent_qa") == "required"
                           for _, task in rows)
    if required or reviewers:
        if len(reviewers) != 1:
            return "unique_request_qa_required"
        graph, qa = reviewers[0]
        if qa["state"] != "QA_PASSED" or not qa.get("agent_ref"):
            return "unique_request_qa_required"
        if full and not current_request_receipt(graph.source, qa, root=root):
            return "current_request_qa_receipt_required"
    return None


def closeout_host(pm_id, installed=None):
    host, sep, native = pm_id.partition(":")
    if not sep or host not in HOSTS or installed is not None and host != installed:
        raise TaskGraphError("closeout requires the PM identity of the current native host")
    validate_reference({"host": host, "agent_id": native})
    return host, native


def evidence_path(item):
    if (not isinstance(item, dict) or set(item) != {"path", "sha256"}
            or not isinstance(item["path"], str) or not isinstance(item["sha256"], str)
            or not re.fullmatch(r"[0-9a-f]{64}", item["sha256"])):
        raise TaskGraphError("evidence requires an exact path and lowercase byte SHA256")
    path = Path(item["path"])
    if not path.is_absolute() or str(path) != item["path"] or ".." in path.parts:
        raise TaskGraphError("evidence requires a canonical absolute path")
    return path


def verify_evidence(item):
    """交付物可为较大的二进制文件，复用原记录按物理路径流式计算的指纹。"""
    path = evidence_path(item)
    anchor = Path(path.anchor)
    if records.file_digest(anchor, path.relative_to(anchor).as_posix()) != item["sha256"]:
        raise TaskGraphError("evidence fingerprint changed")
    return path


def relative_under(path, directory):
    """按祖先目录的物理身份判定归属，返回相对拼写供后续快照逐项核对。"""
    if path.parts[:len(directory.parts)] == directory.parts:
        return path.relative_to(directory)
    try:
        scope = directory.stat()
    except FileNotFoundError:
        return None
    # /var 和 /private/var 的层数不同。仅比对祖先身份，保留槽内的原相对名称，
    # 让下游快照继续拒绝链接；不能 resolve 整个叶路径后跳过槽内的链接检查。
    for ancestor in (path, *path.parents):
        try:
            if os.path.samestat(scope, ancestor.stat()):
                return path.relative_to(ancestor)
        except (FileNotFoundError, NotADirectoryError):
            continue
    return None


def preservation(path, rows):
    """仅检查 PM 指定的原字节证据；预览不复制产物，也不查询宿主。"""
    body = records.read_record(path)
    value = records.decode(body)
    if not isinstance(value, list) or not value or len(value) > 128:
        raise TaskGraphError("preservation requires a non-empty array of exact evidence references")
    isolated = {Path(snap.descriptor["execution_roots"][task["id"]])
                for snap, task in rows if task.get("execution_workspace")}
    originals = {Path(snap.descriptor["path"]) for snap, _ in rows}
    for item in value:
        proof = verify_evidence(item)
        if any(relative_under(proof, root) is not None for root in isolated):
            raise TaskGraphError("preserved evidence must be outside disposable execution worktrees")
        if any(proof.samefile(original) for original in originals):
            raise TaskGraphError("preservation cannot use the mutable original task record as evidence")
    return {"path": str(path), "sha256": records.digest(body)}


def validate_metadata(payload, tasks):
    """终态记录属于原件运行元数据，不进入 Writer/Reviewer 的已审任务字段。"""
    receipts = payload.get(FIELD)
    if not isinstance(receipts, dict) or not receipts:
        raise TaskGraphError("native closeout metadata must contain original task receipts")
    indexed = {task.get("id"): task for task in tasks}
    for identifier, receipt in receipts.items():
        task = indexed.get(identifier)
        if task is None or task.get("agent_retired") is not True or not task.get("agent_ref"):
            raise TaskGraphError("native closeout metadata requires its exact retired original task")
        terminal_shape(receipt, task["agent_ref"])


def retired(snapshot, task):
    receipt = snapshot.source.get(FIELD, {}).get(task["id"])
    if receipt is None:
        return False
    terminal(receipt, task["agent_ref"], receipt["preservation"])
    _evidence(receipt["preservation"], records.read_record, "preservation receipt")
    return True


def plan(root, pm_id, snapshots, request_id, proof, *, installed=None):
    host, owner = closeout_host(pm_id, installed)
    rows = request_tasks(snapshots, request_id)
    blocked = accepted(root, rows)
    references = [task["agent_ref"] for _, task in rows if task.get("agent_ref")]
    keys = {(ref["host"], ref["agent_id"]) for ref in references}
    if len(keys) != len(references) or (host, owner) in keys:
        blocked = "ambiguous_native_identity"
    targets = []
    if not blocked:
        for snap, task in rows:
            ref = task.get("agent_ref")
            if not ref or retired(snap, task):
                continue
            if ref["host"] != host:
                blocked = "foreign_native_identity"
                break
            targets.append({
                "record": snap.descriptor["path"], "sha256": snap.descriptor["sha256"],
                "task_id": task["id"], "agent_ref": ref,
                "execution_root": snap.descriptor["execution_roots"][task["id"]],
            })
    if targets and proof is None:
        blocked = blocked or "preservation_required"
    saved = preservation(proof, rows) if not blocked and proof is not None else None
    return {"request_id": request_id, "status": "blocked" if blocked else "ready",
            "reason": blocked, "targets": [] if blocked else targets, "preservation": saved}


def terminal_shape(receipt, reference):
    if (not isinstance(receipt, dict)
            or set(receipt) != {"schema_version", "agent_ref", "outcome", "native_evidence", "preservation"}
            or type(receipt["schema_version"]) is not int or receipt["schema_version"] != 1
            or receipt["agent_ref"] != reference or receipt["outcome"] not in ("closed", "stopped", "retired")):
        raise TaskGraphError("terminal observation must bind the exact native ID and preservation receipt")
    validate_reference(receipt["agent_ref"])
    for key in ("native_evidence", "preservation"):
        evidence_path(receipt[key])


def terminal(receipt, reference, proof):
    """匹配 PM 已核对的原生回执定位。宿主操作、能力及结果本身仍由当前 PM 核对。"""
    terminal_shape(receipt, reference)
    if receipt["preservation"] != proof:
        raise TaskGraphError("terminal observation must bind the exact preservation receipt")
    verify_evidence(receipt["native_evidence"])


def _references(value):
    if isinstance(value, dict):
        for item in value.values():
            yield from _references(item)
    elif isinstance(value, list):
        for item in value:
            yield from _references(item)
    elif isinstance(value, str):
        yield value


def _preserved_references(source):
    receipts = list(source.get(FIELD, {}).values())
    # 早期候选若已写入历史证据，只保全其引用。它不作为本版的退役权威。
    texts = []
    for value in _references(source):
        if value.startswith(LEGACY_PREFIX):
            receipts.append(records.decode(value[len(LEGACY_PREFIX):].encode()))
        else:
            texts.append(value)
    for receipt in receipts:
        proof = receipt["preservation"]
        stored = _evidence(proof, records.read_record, "preservation receipt")
        texts.extend([receipt["native_evidence"]["path"], proof["path"]])
        texts.extend(str(verify_evidence(item)) for item in records.decode(stored))
    return texts


def _text_scratch_paths(text, slot, target):
    """枚举同一文本的各个定位。先识别槽名，再由实际目录确认该绝对路径的起点。"""
    locations = []
    previous = 0
    for marker in slot.finditer(text):
        # 一个未加引号的路径可以包含空格；先取最长真实目录，避免把另一目录
        # 的路径后缀当作本槽。相邻的命令参数、反引号或括号可以各自开始新定位。
        roots = re.finditer(r"(?<![\w./-])/", text[previous:marker.end()])
        for root in roots:
            start = previous + root.start()
            location = Path(text[start:marker.end() - 1])
            if location.is_dir():
                locations.append((start, marker.end(), location))
                break
        else:
            raise TaskGraphError("cannot prove a referenced scratch path is preserved")
        previous = marker.end()
    for index, (start, end, location) in enumerate(locations):
        if relative_under(location, target) != Path("."):
            continue
        limit = locations[index + 1][0] if index + 1 < len(locations) else len(text)
        suffix = text[end:limit]
        # 独立值和带引号的值可包含空格及标点。普通文字的终止符沿用已有合同；
        # 多个未加引号的定位之间可能夹有说明，按真实文件判断其结束位置。
        quote = text[start - 1] if start else ""
        quoted = quote in ('"', "'", "`")
        if quoted:
            suffix = suffix.partition(quote)[0]
        elif not (start == 0 and limit == len(text) and Path(text).is_file()):
            suffix = re.split(r'[\n\r"\x27\x60<>;)#]', suffix, maxsplit=1)[0].rstrip()
        candidate = Path(suffix)
        if not (target / candidate).is_file():
            if quoted or limit == len(text):
                raise TaskGraphError("cannot prove a referenced scratch path is preserved")
            matches = {Path(suffix[:separator.start()]) for separator in re.finditer(r"[\s,|，；、]+", suffix)
                       if (target / suffix[:separator.start()]).is_file()}
            if len(matches) != 1:
                raise TaskGraphError("cannot prove a referenced scratch path is preserved")
            candidate, = matches
        yield candidate.as_posix()


def keep_scratch(target, originals, keeps):
    """保留全部登记原件和能从原记录解析的显式证据定位；模糊路径拒绝清理。"""
    keep = set(keeps)
    slot = re.compile("/" + re.escape(target.name) + "/", re.IGNORECASE)
    for path, source in originals:
        relative = relative_under(path, target)
        if relative is not None:
            keep.add(relative.as_posix())
        for item in _preserved_references(source):
            keep.update(_text_scratch_paths(item, slot, target))
    return tuple(sorted(keep))
