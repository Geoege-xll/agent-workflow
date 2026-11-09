"""只读解析同任务结果结算证据，返回由原 records CAS 一次发布的字段。

该模块不派发、不查询原生宿主、不修改文件。PM负责核实实际原生观察与结果；
这里绑定其当前任务、完整接受包原字节、证据来源与验证约定，防止误用旧范围。
"""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
from typing import Any, Callable

try:
    from .agent_continuation import validate_reference
    from .task_graph import TaskGraphError
    from .runtime_pins import record_binding
    from .standard_paths import builtin_source_path
except ImportError:
    from agent_continuation import validate_reference
    from task_graph import TaskGraphError
    from runtime_pins import record_binding
    from standard_paths import builtin_source_path


SHA = re.compile(r"[0-9a-f]{64}\Z")
SETTLEMENT_PREFIX = "RESULT_VERIFIED settlement: "


def _object(value: Any, fields: set[str], label: str, *, optional: set[str] = frozenset()) -> dict:
    if not isinstance(value, dict) or set(value) - (fields | optional) or fields - set(value):
        raise TaskGraphError(f"{label} has missing or unsupported fields")
    return value


def _evidence(value: Any, read: Callable, label: str) -> bytes:
    """只读明确单文件，沿用4MiB、UTF-8包解析及链接/变化拒绝边界，不扫描目录。"""
    value = _object(value, {"path", "sha256"}, label)
    raw, sha = value["path"], value["sha256"]
    if (not isinstance(raw, str) or not raw or "\x00" in raw or not Path(raw).is_absolute()
            or str(Path(raw)) != raw or ".." in Path(raw).parts
            or not isinstance(sha, str) or not SHA.fullmatch(sha)):
        raise TaskGraphError(f"{label} requires an absolute path and lowercase byte SHA256")
    body = read(Path(raw))
    if hashlib.sha256(body).hexdigest() != sha:
        raise TaskGraphError(f"{label} fingerprint changed")
    if not body:
        raise TaskGraphError(f"{label} must reference non-empty evidence")
    return body


def _scope(task: dict) -> dict:
    """只忽略运行元数据；验收约定、验证命令、标准和路径均属于接受范围。

    Light归一化会补空调度字段；这些语义等价的省略不应误报旧scope。退休可以
    发生在交接后，但不能掩盖真实范围变化。原生身份在外层逐字段独立核对。
    """
    result = {key: value for key, value in task.items() if key not in {"state", "agent_retired", "agent_ref"}}
    for field in ("depends_on", "blocks", "gates", "semantic_locks"):
        result.setdefault(field, [])
    return result


def _record_tasks(value: Any) -> dict[str, dict]:
    """只识别schema 2记录；普通publish仍可写任意bytes/JSON，不引入新传输协议。"""
    if not isinstance(value, dict) or type(value.get("schema_version")) is not int or value["schema_version"] != 2:
        return {}
    tasks = [value["task"]] if "task" in value else value.get("tasks")
    if not isinstance(tasks, list) or any(not isinstance(task, dict) or not isinstance(task.get("id"), str)
                                         or not isinstance(task.get("task_type"), str) for task in tasks):
        return {}
    return {task["id"]: task for task in tasks}


def validate_new_settlement_sources(target: Path, before: bytes | None, after: bytes, *,
                                    read: Callable, decode: Callable) -> None:
    """在原CAS锁内拒绝本轮结算自毁证据，不回查所有历史收据。

    新文件、普通字节/JSON和未发生新结算的更新沿原publish语义。已生成收据是
    owner显式的不可变证据描述；只解析RUNNING→RESULT_VERIFIED新追加的一条。
    samefile核实际文件身份，可覆盖Windows大小写别名；不能用同内容或字符串
    casefold判身份。最后一瞬的不合作外部替换仍受原发布边界限制，不宣称跨文件事务。
    """
    if before is None:
        return
    try:
        old_tasks, new_tasks = _record_tasks(decode(before)), _record_tasks(decode(after))
    except (ValueError, UnicodeError):
        return
    for task_id, current in new_tasks.items():
        previous = old_tasks.get(task_id)
        if (previous is None or previous.get("state") != "RUNNING" or current.get("state") != "RESULT_VERIFIED"
                or previous.get("task_type") not in {"read_only", "evidence"}):
            continue
        old_evidence, evidence = previous.get("acceptance_evidence"), current.get("acceptance_evidence")
        if (not isinstance(old_evidence, list) or not isinstance(evidence, list)
                or len(evidence) != len(old_evidence) + 1 or evidence[:-1] != old_evidence
                or not isinstance(evidence[-1], str) or not evidence[-1].startswith(SETTLEMENT_PREFIX)):
            raise TaskGraphError("new result publication requires its exclusive settlement receipt")
        receipt = _object(decode(evidence[-1][len(SETTLEMENT_PREFIX):].encode("utf-8")),
                          {"schema_version", "agent_ref", "task_pack", "completion", "result", "verification"},
                          "settlement receipt", optional={"retire"})
        completion = _object(receipt["completion"], {"state", "agent_ref", "task_pack_sha256", "evidence"}, "receipt.completion")
        result = _object(receipt["result"], {"task_pack_sha256", "evidence"}, "receipt.result")
        if not isinstance(result["evidence"], list) or not isinstance(receipt["verification"], list):
            raise TaskGraphError("new settlement receipt must contain result and verification evidence arrays")
        references = [receipt["task_pack"], completion["evidence"], *result["evidence"]]
        for entry in receipt["verification"]:
            _object(entry, {"command", "exit_code", "evidence"}, "receipt.verification", optional={"expected"})
            references.append(entry["evidence"])
        checked = set()
        for reference in references:
            # 复用安全reader及SHA核验，避免路径在结算计算与发布之间已变化。
            # 同一独立日志可以被多个证据字段引用，但任何字段都不得别名目标。
            _object(reference, {"path", "sha256"}, "settlement source")
            if not isinstance(reference["path"], str) or not isinstance(reference["sha256"], str):
                raise TaskGraphError("settlement source requires a path and SHA string")
            key = (reference["path"], reference["sha256"])
            if key in checked:
                continue
            _evidence(reference, read, "settlement source")
            if Path(reference["path"]).samefile(target):
                raise TaskGraphError("settlement evidence must be physically independent from the record being published")
            checked.add(key)


def _overlap(first: str, second: str) -> bool:
    a, b = PurePosixPath(first).parts, PurePosixPath(second).parts
    return a[:min(len(a), len(b))] == b[:min(len(a), len(b))]


def _authority(payload: dict, task: dict) -> dict:
    """比较当前任务实际采用的权威，不要求Full接受包携带兄弟任务的标准。

    原导出器按任务读取来源、领域、owned范围投影标准；这里仅比较同一责任范围，
    不另行导出包、不读取兄弟会话，也不允许包自报标准覆盖覆写原记录的权威。
    """
    contract = copy.deepcopy(payload["standards_contract"])
    domains = {"design"} if task.get("surface_kind") == "design_ui" else {"engineering", "design"} if task.get("surface_kind") == "production_ui" else {"engineering"}
    sources = {doc["path"] for doc in task.get("controlled_document_access", {}).get("documents", [])}
    sources.update(ref["path"] for ref in task.get("ui_change", {}).get("design_authority_refs", []))
    selected = [leaf for leaf in contract["leaves"] if leaf["path"] in sources or (
        not sources and leaf["domain"] in domains and builtin_source_path(leaf["path"]) is not None)]
    contract["leaves"] = selected or [leaf for leaf in contract["leaves"] if leaf["domain"] in domains]
    for domain in ("engineering", "design"):
        available = {rule for leaf in contract["leaves"] if leaf["domain"] == domain for rule in leaf["rule_ids"]}
        key = f"required_{domain}_rule_ids"
        contract[key] = [rule for rule in contract[key] if domain in domains and rule in available]
    contract["protected_paths"] = [policy for policy in contract["protected_paths"]
                                   if any(_overlap(path, policy["path"]) for path in task["owned_paths"])]
    return contract


def settle_task(payload: dict, task: dict, value: Any, *, read: Callable, decode: Callable) -> dict:
    """返回结果态/证据/可选退休，发布仍由原update校验及CAS负责。

    completed是PM从实际原生工具核实后提供的观察；本地结构和哈希校验不能证明
    宿主确实运行、关闭或释放打开线程额度。未知或仍运行绝不按退休推定完成。
    """
    value = _object(value, {"schema_version", "agent_ref", "task_pack", "completion", "result", "verification"},
                    "settle", optional={"retire"})
    if type(value["schema_version"]) is not int or value["schema_version"] != 1:
        raise TaskGraphError("settle requires schema_version 1")
    if task["task_type"] not in {"read_only", "evidence"} or task["state"] != "RUNNING":
        raise TaskGraphError("settle requires a RUNNING read_only or evidence task")
    reference = validate_reference(value["agent_ref"])
    if reference != task.get("agent_ref"):
        raise TaskGraphError("settle requires the original bound native agent_ref")
    if "retire" in value and not isinstance(value["retire"], bool):
        raise TaskGraphError("settle.retire must be a boolean")
    body = _evidence(value["task_pack"], read, "settle.task_pack")
    pack = decode(body)
    if (not isinstance(pack, dict) or type(pack.get("schema_version")) is not int
            or pack["schema_version"] != 2 or not isinstance(pack.get("task"), dict)
            or set(pack) - {"schema_version", "task", "standards_contract", "approved_gates", "requirements_fingerprint", "runtime_binding", "ui_contract"}):
        raise TaskGraphError("settle requires a complete schema 2 Task Pack")
    # 不从当前locator补pin；接受包与原记录必须各自通过原内容库，并属于同一固定版。
    if record_binding(pack) != record_binding(payload):
        raise TaskGraphError("accepted Task Pack runtime_binding differs from original record")
    if (pack["task"].get("state") != "RUNNING" or pack["task"].get("agent_ref") != reference
            or _scope(pack["task"]) != _scope(task)):
        raise TaskGraphError("accepted Task Pack does not match the current task scope or identity")
    if pack.get("requirements_fingerprint") != payload.get("requirements_fingerprint"):
        raise TaskGraphError("accepted Task Pack requirements fingerprint changed")
    # Light本身就是完整包；Full采用原导出器的任务相关权威投影。两种来源均只读。
    authority = payload["standards_contract"] if task["workflow_level"] == "Light" else _authority(payload, task)
    if pack.get("standards_contract") != authority:
        raise TaskGraphError("accepted Task Pack standards authority changed")
    gates = set(task.get("gates", []))
    if (not gates <= set(payload.get("approved_gates", []))
            or pack.get("approved_gates") != [gate for gate in payload.get("approved_gates", []) if gate in gates]):
        raise TaskGraphError("accepted Task Pack approvals do not match current required gates")
    expected_ui = payload.get("ui_contract") if task.get("surface_kind") in {"production_ui", "design_ui"} else None
    if pack.get("ui_contract") != expected_ui:
        raise TaskGraphError("accepted Task Pack UI authority changed")

    completion = _object(value["completion"], {"state", "agent_ref", "task_pack_sha256", "evidence"}, "settle.completion")
    sha = value["task_pack"]["sha256"]
    if completion["state"] != "completed" or completion["agent_ref"] != reference or completion["task_pack_sha256"] != sha:
        raise TaskGraphError("native completion must match the original identity and accepted Task Pack SHA")
    _evidence(completion["evidence"], read, "settle.completion.evidence")
    result = _object(value["result"], {"task_pack_sha256", "evidence"}, "settle.result")
    if result["task_pack_sha256"] != sha or not isinstance(result["evidence"], list) or not result["evidence"]:
        raise TaskGraphError("result must bind the accepted Task Pack and non-empty evidence")
    for evidence in result["evidence"]:
        _evidence(evidence, read, "settle.result.evidence")
    verification = value["verification"]
    commands = task.get("verification_commands")
    if (not isinstance(commands, list) or not isinstance(verification, list)
            or len(verification) != len(commands)):
        raise TaskGraphError("settle verification must cover each current command exactly once")
    for command, observed in zip(commands, verification):
        if (not isinstance(command, str) and not (isinstance(command, dict) and set(command) == {"run", "expected"}
                and all(isinstance(command[key], str) and command[key].strip() for key in command))):
            raise TaskGraphError("current verification command must be a string or frozen run/expected object")
        entry = _object(observed, {"command", "exit_code", "evidence"}, "settle.verification", optional={"expected"})
        expected_command = command["run"] if isinstance(command, dict) else command
        if entry["command"] != expected_command or type(entry["exit_code"]) is not int:
            raise TaskGraphError("verification command or exit code is invalid")
        if isinstance(command, dict):
            # 预期负控/缺陷复现可以非零，但必须绑定原任务明确的expected约定；
            # 语义是否相符仍由PM核实实际证据，不能自动把任意非零解释成成功。
            if entry.get("expected") != command["expected"]:
                raise TaskGraphError("verification must bind the frozen expected outcome")
        elif entry["exit_code"] != 0 or "expected" in entry:
            raise TaskGraphError("verification failed; string commands require exit 0")
        _evidence(entry["evidence"], read, "settle.verification.evidence")
    # 已有acceptance_evidence承载最小来源绑定，不保存另一份状态或强制额外报告。
    summary = SETTLEMENT_PREFIX + json.dumps(value, ensure_ascii=False, sort_keys=True)
    fields = {"state": "RESULT_VERIFIED", "acceptance_evidence": [*task["acceptance_evidence"], summary]}
    if value.get("retire"):
        fields["agent_retired"] = True
    return fields
