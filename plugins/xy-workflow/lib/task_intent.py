"""原任务上的撤回、停止观察和修订回执。所有操作仅由原记录的 update/CAS 发布。"""

from __future__ import annotations

import copy
import re

from lib.agent_continuation import active, validate_reference
from lib.hosts import antigravity_dispatch
from lib.task_graph import TaskGraphError, WITHDRAWAL_STATES, delivery_complete
from lib.verification_inputs import validate_command

PENDING = {"DECLARED", "READY", "BLOCKED"}
CONTROL_OPS = {"claim", "release_claim", "withdraw", "confirm_stop", "confirm_uncreated", "revise", "ack_revision"}
REVISION_FIELDS = {"goal", "input_contracts", "output_contracts", "acceptance_evidence", "verification_commands"}
CLAIM_FIELDS = {"claim_basis_sha256", "claim_prior_state", "antigravity_claim"}
RECORD_FIELDS = CLAIM_FIELDS | {"withdrawal", "task_revision", "revision_source", "revision_ack", "revision_result", "qa_result_scope", "qa_failed_pack_fingerprint"}


def _fields(value, names, label):
    if not isinstance(value, dict) or set(value) != names:
        raise TaskGraphError(f"{label} requires exactly {', '.join(sorted(names))}")
    return value


def _source(value, label):
    # 来源可以是宿主事件、对话定位或当前工作区证据。helper 只能验证绑定和输入，
    # 真实投递、停止、用户批准和回执内容必须由 PM 从实际宿主观察后登记。
    if not isinstance(value, str) or not value.strip():
        raise TaskGraphError(f"{label} requires a non-empty evidence reference")


def _same_agent(task, value):
    if validate_reference(value) != task.get("agent_ref"):
        raise TaskGraphError("operation requires the original bound agent_ref")


def _receipt(task, value, sources):
    _fields(value, {"revision", "agent_ref", *sources}, "revision receipt")
    if type(value["revision"]) is not int or value["revision"] != task.get("task_revision"):
        raise TaskGraphError("receipt must identify the current task revision")
    _same_agent(task, value["agent_ref"])
    for field in sources:
        _source(value[field], field)


def _confirmed_stop(task, value):
    _fields(value, {"agent_ref", "observed_state", "source"}, "confirm_stop")
    _same_agent(task, value["agent_ref"])
    if value["observed_state"] != "stopped":
        raise TaskGraphError("only confirmed native stopped releases a withdrawal")
    _source(value["source"], "confirm_stop.source")


def _confirmed_uncreated(task, value):
    field = "previous_sha256" if "claim_basis_sha256" in task else "claimed_sha256"
    basis = task.get("claim_basis_sha256") or task.get("withdrawal", {}).get("claimed_sha256")
    _fields(value, {field, "outcome"}, "confirm_uncreated")
    if (task.get("agent_ref") or value["outcome"] != "definitely_not_created"
            or not isinstance(basis, str) or value[field] != basis):
        raise TaskGraphError("uncreated confirmation must match the original unbound claim")


def validate_intent(task):
    """读取旧记录时不补写字段。出现新状态时，同时校验产生它的原始依据。"""
    if CLAIM_FIELDS.intersection(task):
        if (not isinstance(task.get("claim_basis_sha256"), str)
                or not re.fullmatch(r"[0-9a-f]{64}", task["claim_basis_sha256"])
                or not isinstance(task.get("claim_prior_state"), str) or task["claim_prior_state"] not in PENDING):
            raise TaskGraphError("claim basis requires the original CAS SHA256 and pending state")
        if "antigravity_claim" in task:
            antigravity_dispatch.validate_claim(task["antigravity_claim"])
            if "agent_ref" in task:
                # 新领取的状态即使是从磁盘恢复，也不得把主会话、角色别名、
                # 或其它宿主的引用报告成已绑定。旧记录没有此字段，仍按原协议读取。
                ref = validate_reference(task["agent_ref"])
                if ref["host"] != "antigravity":
                    raise TaskGraphError("AGY claim requires an AGY agent_ref")
                antigravity_dispatch.validate_child_id(task["antigravity_claim"]["parent"], ref["agent_id"])
    if "withdrawal" in task or task["state"] in WITHDRAWAL_STATES:
        withdrawal = task.get("withdrawal")
        if not isinstance(withdrawal, dict) or task["state"] not in WITHDRAWAL_STATES:
            raise TaskGraphError("withdrawal must belong to a STOP_REQUESTED or WITHDRAWN task")
        prior = withdrawal.get("prior_state")
        if not isinstance(prior, str) or prior not in PENDING | {"RUNNING", "QA", "FAILED"}:
            raise TaskGraphError("withdrawal requires the prior task state")
        allowed = {"prior_state", "reason", "claimed_sha256", "confirmation"}
        if set(withdrawal) - allowed:
            raise TaskGraphError("unsupported withdrawal evidence")
        _source(withdrawal.get("reason"), "withdrawal reason")
        if "claimed_sha256" in withdrawal and not (isinstance(withdrawal["claimed_sha256"], str)
                and re.fullmatch(r"[0-9a-f]{64}", withdrawal["claimed_sha256"])):
            raise TaskGraphError("unbound withdrawal requires original claim SHA256")
        confirmed = "confirmation" in withdrawal
        if confirmed:
            if task["state"] != "WITHDRAWN":
                raise TaskGraphError("stop confirmation must finish withdrawal")
            if "agent_ref" in task:
                _confirmed_stop(task, withdrawal["confirmation"])
            else:
                _confirmed_uncreated(task, withdrawal["confirmation"])
        elif task["state"] == "WITHDRAWN" and (prior not in PENDING | {"FAILED"} or "agent_ref" in task):
            raise TaskGraphError("running or previously bound withdrawal requires stop confirmation")
    if "qa_failed_pack_fingerprint" in task and (
            not isinstance(task["qa_failed_pack_fingerprint"], str)
            or not re.fullmatch(r"[0-9a-f]{64}", task["qa_failed_pack_fingerprint"])
            or "qa_result_scope" not in task or not task.get("agent_ref")):
        raise TaskGraphError("QA failure must bind its original task pack, scope and Reviewer")
    if "qa_result_scope" in task:
        if (task.get("task_type") != "qa" or task.get("workflow_level") != "Full"
                or not isinstance(task["qa_result_scope"], str) or not re.fullmatch(r"[0-9a-f]{64}", task["qa_result_scope"])
                or not ({"revision_result", "qa_failed_pack_fingerprint"} & task.keys())):
            raise TaskGraphError("qa_result_scope requires an evidence-bound revised Full QA result")
    if not ({"task_revision", "revision_source", "revision_ack", "revision_result"} & task.keys()):
        return
    if type(task.get("task_revision")) is not int or task["task_revision"] < 1:
        raise TaskGraphError("task_revision must be a positive integer")
    _source(task.get("revision_source"), "revision_source")
    # 当前任务声称交付时必有本轮结果和同实例确认。这样即使单独读取某个
    # 修订过的 Light 包，也不会把手填成功态解释成就绪依赖或可归档结果。
    if delivery_complete(task["task_type"], task["state"]) and "revision_result" not in task:
        raise TaskGraphError("revised completion requires the current revision result")
    if "revision_ack" in task:
        _receipt(task, task["revision_ack"], {"delivery_source", "ack_source"})
    if "revision_result" in task:
        _receipt(task, task["revision_result"], {"source"})
        if "revision_ack" not in task:
            raise TaskGraphError("revision_result requires original instance acknowledgment")


def check_delivery(graph, task):
    """阻断本项及其依赖已撤回后的所有交接，包括原本没有 Writer 门的只读任务。"""
    from lib.foundation_qa import closure
    if "task_revision" in task and set(task.get("gates", [])) - set(graph.get("approved_gates", [])):
        raise TaskGraphError("revised task requires its current approvals before delivery")
    if not any(item.get("state") in WITHDRAWAL_STATES for item in graph["tasks"]):
        return
    # Full 交接包不带兄弟任务；实际导出及准入始终从权威图调用。
    selected = closure(graph, task["id"]) if task.get("depends_on") else {task["id"]}
    if task["task_type"] == "qa" and task.get("workflow_level") == "Full":
        if task.get("foundation_task_id") and not task.get("foundation_receipt"):
            selected.update(closure(graph, task["foundation_task_id"]))
        else:
            # 最终 QA 涵盖该请求及其跨请求前置交付。一个已撤回的证据项即便
            # 没有写路径，也不能在 qa-ready 被拒后又从直接导包入口进入审查。
            for member in graph["tasks"]:
                if member["request_id"] == task["request_id"]:
                    selected.update(closure(graph, member["id"]))
    for item in graph["tasks"]:
        if item["id"] in selected and item["state"] in WITHDRAWAL_STATES:
            raise TaskGraphError(f"delivery blocked by withdrawal of {item['id']}")


def apply_control(task, name, value, *, record_sha):
    """仅返回原任务的增量事实，不发送宿主消息，不触碰代码和现有构建产物。"""
    state = task["state"]
    if name == "claim":
        agy = isinstance(value, dict) and "antigravity_claim" in value
        _fields(value, {"previous_sha256", "antigravity_claim"} if agy else {"previous_sha256"}, "claim")
        if (state not in PENDING or "agent_ref" in task or task.get("agent_retired")
                or not record_sha or value["previous_sha256"] != record_sha):
            raise TaskGraphError("claim requires the current pending task and original record CAS")
        # 回执上的 previous_sha256 属于这次领取。即使同图 B 有新进展仍能核对 A；
        # 释放后保留基线，使重新领取的原件不同，过期 release 不能核销新领取。
        task.update(state="RUNNING", claim_basis_sha256=record_sha, claim_prior_state=state)
        # 旧轮的标记与原领取一起失效。新准入若切到其它宿主，也不能误用前轮的 AGY 身份。
        task.pop("antigravity_claim", None)
        if agy:
            antigravity_dispatch.validate_claim(value["antigravity_claim"])
            task["antigravity_claim"] = value["antigravity_claim"].copy()
        return
    if name == "release_claim":
        _fields(value, {"previous_sha256", "outcome", "prior_state"}, "release_claim")
        if (state != "RUNNING" or value["prior_state"] != task.get("claim_prior_state")
                or task.get("agent_retired") or "claim_basis_sha256" not in task):
            raise TaskGraphError("release_claim requires the original unbound RUNNING claim")
        _confirmed_uncreated(task, {key: value[key] for key in ("previous_sha256", "outcome")})
        task["state"] = value["prior_state"]
        return
    if name in {"confirm_stop", "confirm_uncreated"}:
        if state != "STOP_REQUESTED":
            raise TaskGraphError("stop confirmation requires STOP_REQUESTED")
        if name == "confirm_stop":
            _confirmed_stop(task, value)
        else:
            _confirmed_uncreated(task, value)
        task["withdrawal"]["confirmation"] = copy.deepcopy(value)
        task["state"] = "WITHDRAWN"
        return
    if state in WITHDRAWAL_STATES or state not in PENDING | {"FAILED"} and not active(task):
        raise TaskGraphError("withdrawn or delivered task is closed; a changed request needs a new task")
    if name == "withdraw":
        _fields(value, {"reason"}, "withdraw")
        _source(value["reason"], "withdraw.reason")
        # 领取已经占槽，即便创建超时或绑定失败也不能直接撤销。保留此刻原记录
        # SHA 供已有 release 对照 claim 回执；绑定过的实例必须取得同一 ID 的停止观察。
        task["withdrawal"] = {"reason": value["reason"], "prior_state": state}
        if active(task) and "agent_ref" not in task and "claim_basis_sha256" not in task:
            task["withdrawal"]["claimed_sha256"] = record_sha
        task["state"] = "STOP_REQUESTED" if active(task) or "agent_ref" in task else "WITHDRAWN"
        return
    if task.get("agent_retired") or state == "FAILED":
        raise TaskGraphError("revision requires a pending task or its active original agent")
    if name == "revise":
        _fields(value, {"set", "source"}, "revise")
        _source(value["source"], "revise.source")
        fields = value["set"]
        if (not isinstance(fields, dict) or not fields or set(fields) - REVISION_FIELDS
                or all(task.get(key) == entry for key, entry in fields.items())):
            raise TaskGraphError("revise requires a changed implementation contract within the same ownership")
        for key, entry in fields.items():
            if key == "goal":
                _source(entry, "goal")
            elif not isinstance(entry, list) or not entry:
                raise TaskGraphError(f"revised {key} must be a non-empty array")
            else:
                for item in entry:
                    if key == "verification_commands":
                        validate_command(item, "verification command")
                    else:
                        _source(item, key)
        task.update(copy.deepcopy(fields))
        task["task_revision"] = task.get("task_revision", 0) + 1
        task["revision_source"] = value["source"]
        task.pop("revision_ack", None)
        task.pop("revision_result", None)
        task.pop("qa_result_scope", None)
        return
    _receipt(task, value, {"delivery_source", "ack_source"})
    if not active(task) or "revision_ack" in task:
        raise TaskGraphError("revision acknowledgment requires the active original instance and is single-use")
    task["revision_ack"] = copy.deepcopy(value)


def reopen_changed_review(task, previous, new_scope):
    """只在实际受审范围改变后续用原 Full Reviewer；显式冻结与原生检查点共用此迁移。"""
    # 旧普通 QA 记录可沿用此前已存在的 PM 冻结值。失败／失效前的实际范围
    # 独立于本次图 SHA 和 Reviewer 轮次，因此单纯领取、失败、重复请求不能制造差异。
    old_scope = previous.get("qa_result_scope") or previous.get("qa_scope_fingerprint")
    if (task["task_type"] != "qa" or task["workflow_level"] != "Full" or task["state"] not in {"FAILED", "DECLARED"}
            or not task.get("revision_result") or not task.get("agent_ref") or task.get("agent_retired")
            or not old_scope or old_scope == new_scope):
        return False
    # 新范围在现有 Writer barrier、受审文件与批准校验后才能成立。保留失败
    # 证据来源、同一实例和原批准；清掉旧轮回执，交付必须重新确认最新版。
    prior = task.pop("revision_result")
    task.setdefault("acceptance_evidence", []).append(
        f"QA 第 {prior['revision']} 版返工前回报：{prior['source']}")
    task.pop("qa_result_scope", None)
    task.pop("qa_failed_pack_fingerprint", None)
    task.pop("revision_ack")
    task["task_revision"] += 1
    task["state"] = "DECLARED"
    return True


def ordinary_operations(task, operations):
    """在旧操作解释之前识别修订结果，保留 settle、QA 等既有证据核验与独占语义。"""
    fields = operations.get("set", {})
    if not isinstance(fields, dict):
        raise TaskGraphError("task.set must be an object")
    state = fields.get("state")
    if "state" in fields and not isinstance(state, str):
        raise TaskGraphError("task state must be a string")
    if isinstance(state, str) and state in WITHDRAWAL_STATES:
        raise TaskGraphError("withdrawal state requires its explicit operation")
    if task["state"] in WITHDRAWAL_STATES:
        # 已领取但未绑定时，唯一有助于安全释放的补写是找回实际已创建实例。
        if (task["state"] == "STOP_REQUESTED" and set(operations) == {"set"}
                and set(fields) == {"agent_ref"} and "agent_ref" not in task):
            return operations
        raise TaskGraphError("withdrawal blocks delivery and ordinary task updates")
    if "claim_basis_sha256" in task and "agent_ref" not in task and state is not None:
        raise TaskGraphError("unbound claimed task requires claim, release_claim or withdrawal")
    if "task_revision" not in task:
        # 已确认发给实例的旧 3.x 合同，其后第一次行为修改也必须进入显式修订。
        # 追加实际验收证据保留原语义；同值更新不凭空制造一个新的修订号。
        behavior = REVISION_FIELDS - {"acceptance_evidence"}
        additions = operations.get("append", {})
        # 旧记录在创建实例与绑定 ID 之间也已占用；此时新行为同样不能冒用
        # 刚发出的旧包。是否有新版领取基线只影响恢复，不影响合同版本边界。
        if (active(task)
                and (any(key in fields and fields[key] != task.get(key) for key in behavior)
                     or isinstance(additions, dict) and any(
                         key in additions and isinstance(additions[key], list)
                         and any(item not in task.get(key, []) for item in additions[key]) for key in behavior))):
            raise TaskGraphError("changing a dispatched implementation contract requires revise")
        if "revision_result" in operations:
            raise TaskGraphError("revision_result requires an existing task revision")
        return operations
    if "append" in operations and not isinstance(operations["append"], dict):
        raise TaskGraphError("task.append must be an object")
    proof = operations.get("revision_result")
    changes = {key: value for key, value in operations.items() if key != "revision_result"}
    if (set(fields) - {"state", "agent_ref", "agent_retired", "handoff_assessment"}
            or "documents" in changes or set(changes.get("append", {})) - {"acceptance_evidence"}):
        raise TaskGraphError("changed contract requires a separate explicit revise operation")
    # 依据任务类型识别实际结果。附加证据不能把 RUNNING→READY 包装成结算，
    # 否则仍在运行的实例可在同一补丁里放掉写锁。
    outcome = (state == "FAILED" or delivery_complete(task["task_type"], state)
               or state == "QA" and task["task_type"] == "writer")
    returns_result = outcome or bool(changes.keys() & {"settle", "accept_foundation", "accept_request"})
    # 第一次领取及确定未创建的释放仍由既有协议完成；已经绑定的实例不得借
    # RUNNING→READY 或 FAILED→RUNNING 绕过新版结果回执再进入另一轮。
    initial_claim = task["state"] in PENDING and not task.get("revision_result")
    unbound_release = active(task) and "agent_ref" not in task and state in PENDING
    foundation_next = (task.get("foundation_receipt") and "qa_result_scope" not in task and task["state"] in PENDING
                       and state in {"RUNNING", "QA"} and task["task_type"] == "qa")
    if not returns_result:
        start = initial_claim and state in PENDING | ({"RUNNING", "QA"} if task["task_type"] == "qa" else {"RUNNING"})
        if ("revision_result" in operations or "append" in changes
                or state is not None and not (start or unbound_release or foundation_next)):
            raise TaskGraphError("ordinary state updates cannot reopen a revised task")
        return changes
    if (not active(task) or task.get("agent_retired") or "revision_ack" not in task
            or not isinstance(proof, dict) or not (state or changes.keys() & {"settle", "accept_foundation", "accept_request"})):
        raise TaskGraphError("revised result requires current original acknowledgment and active task")
    _receipt(task, proof, {"source"})
    if task.get("revision_result") == proof:
        raise TaskGraphError("duplicate revision result")
    task["revision_result"] = copy.deepcopy(proof)
    return changes


def handoff_task(task):
    """回执属于 PM 记录。交给同一实例的完整实现合同保留修订号/来源，确认前后内容一致。"""
    omitted = CLAIM_FIELDS | {"qa_result_scope", "qa_failed_pack_fingerprint"}
    if active(task) or task["state"] in PENDING:
        omitted = omitted | {"revision_ack", "revision_result"}
    return {key: value for key, value in task.items() if key not in omitted}
