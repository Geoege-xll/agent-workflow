"""中央版本激活的持久协调者；项目事务仍由 runtime_service 独占。

登记表、策略和原始前像共同固定一次影响集合。prepared 先封闭新任务入口，
子事务按预分配 ID 结算，current 最后 CAS；恢复依靠原 inode 条件补偿，
不会借用“切换前次版”覆盖后续用户修改，也不宣称跨文件系统原子性。
"""

from __future__ import annotations

import copy
from dataclasses import dataclass
from pathlib import Path
import uuid

from lib import runtime_store as store
from lib.central.runtime_project import CAPACITY_IDENTITY, Node, Tree, canonical_project, json_bytes, unique_json
from lib.hosts.claude_instructions import read_file
from . import runtime_policy as policy, runtime_service as projects, state_files
from .runtime_state import ActivationError, CONFLICT_REASON_LIMIT, bounded_conflicts, publication_capacity, read_state, write_control


@dataclass(frozen=True)
class ProjectCapture:
    project: Path
    policy_before: Node
    binding_before: Node
    journal_before: Node
    runtime_plan: projects.ActivationPlan | None
    mode: str


@dataclass(frozen=True)
class CentralPlan:
    state: Path
    action: str
    binding: dict
    current_before: Node
    activation_before: Node
    registry_before: bytes | None
    captures: tuple[ProjectCapture, ...]
    native_plan: object
    native_context: object

    @property
    def summary(self) -> dict:
        native = self.native_plan.summary
        conflicts = list(native.get("conflicts", []))
        rows = []
        for capture in self.captures:
            item = capture.runtime_plan.summary if capture.runtime_plan else None
            conflicts.extend(item["conflicts"] if item else [])
            # 处置是本次提案的固定事实，不能为了绘制预览再调用status或读取
            # 可变policy/current。原始机器前像已经在preview中完成完整codec；
            # 这里只解码快照并返回独立pin，避免展示消费者改写计划内部目标。
            record = unique_json(capture.binding_before.payload) if capture.binding_before.kind == "file" else None
            captured_policy = unique_json(capture.policy_before.payload) if capture.policy_before.kind == "file" else None
            declared_enabled = bool(record and record["enabled"])
            effective = captured_policy["runtime_binding"] if capture.mode == "pinned" else self.binding
            if item is not None:
                disposition, reason = "apply", "已启用且跟随中央版本，本次应用目标版本"
            elif record is None:
                disposition, reason = "not_enabled", "项目尚无本机绑定，本次不启用；首次启用采用有效策略版本"
            elif capture.mode == "pinned":
                disposition, reason = "skipped_pinned", "项目已锁版，保留既定版本并跳过本次中央激活"
            else:
                disposition, reason = "on_enable", "项目已停用且跟随中央版本，保持停用，下次启用采用目标版本"
            rows.append({"project": str(capture.project), "policy": capture.mode,
                         "affected": item is not None, "runtime": item,
                         "declared_enabled": declared_enabled,
                         "applied_binding": record["runtime_binding"] if record else None,
                         "effective_after": store.validate_binding(effective),
                         "disposition": disposition, "reason": reason})
        return {"schema_version": 1, "action": self.action, "runtime_binding": store.validate_binding(self.binding),
                "previous_binding": unique_json(self.current_before.payload)["runtime_binding"] if self.current_before.kind == "file" else None,
                "projects": rows, "native": native, "conflicts": conflicts,
                "can_apply": not conflicts and native.get("can_apply", True)}


@dataclass(frozen=True)
class RecoveryPlan:
    state: Path
    before: Node
    record: dict
    native_context: object

    @property
    def summary(self) -> dict:
        _, current = policy.current_snapshot(self.state)
        published = bool(current and current["generation"] == self.record["id"])
        return {"schema_version": 1, "action": "recover", "transaction_id": self.record["id"],
                "phase": self.record["phase"], "current_published": published,
                "recovery": "complete" if published else "compensate", "can_apply": True}


def _native_context(state: Path, context):
    if context is not None:
        return context
    from lib.hosts.native_context import NativeContext
    return NativeContext.for_state(state)


def _registry_bytes(state: Path) -> bytes | None:
    return read_file(state_files.secure_path(state, "projects.json"))


def _registered(state: Path, raw: bytes | None) -> tuple[Path, ...]:
    from .project_service import parse_registry
    data = parse_registry(raw)
    # 使用 raw registry 的完整登记集合；隐藏、失效目录不能借 UI 列表过滤偷偷
    # 逃离激活前像检查。重复物理目录只执行一次，任何无效登记明确拒绝。
    return tuple(sorted({canonical_project(Path(value)) for value in data["registered"]}, key=str))


def status(state: Path) -> dict:
    from . import runtime_lifecycle
    state = store.state_root(state)
    _, current = policy.current_snapshot(state)
    pending = policy.pending(state)
    lifecycle = runtime_lifecycle.status(state)
    controller_issues = []
    if current:
        try:
            _require_controller(store.load_core(current["runtime_binding"], state))
        except (OSError, ValueError):
            controller_issues.append({"path": policy.CURRENT, "reason": "中央current或控制核心无效",
                                      "code": "current_control_invalid", "layer": "admission"})
    return {"schema_version": 1, "state_dir": str(state),
            "runtime_binding": current["runtime_binding"] if current else None,
            "previous_binding": current["previous_binding"] if current else None,
            "generation": current["generation"] if current else None,
            "pending_activation": {"id": pending["id"], "phase": pending["phase"]} if pending else None,
            "lifecycle": lifecycle,
            "issues": controller_issues,
            "new_task_allowed": pending is None and current is not None and not controller_issues,
            # 清理的固定引用前像必须先恢复再允许管理写；当前资源/任务读取
            # 不因cleanup一概禁用，仍沿既有activation及项目自身准入边界。
            "management_write_allowed": pending is None and not lifecycle["pending"]}


def _require_controller(core: store.FrozenCore) -> store.FrozenCore:
    """候选资格在任何原生预览/写入之前检查，旧current不阻碍激活合格新core修复。"""
    from lib.runtime_bridge import controller_protocol
    if controller_protocol(core) != 1:
        raise ActivationError("所选核心缺少 CENTRAL_CONTROL_PROTOCOL=1，不能作为中央current控制器")
    return core


def preview(state: Path, action: str = "activate", *, binding: dict | None = None,
            source_root: Path | None = None, native_context=None) -> CentralPlan:
    """预览只激活已导入核心；来源导入、中央激活和程序升级是三个独立动作。"""
    from . import native_agents
    state = store.state_root(state)
    policy.ensure_management_settled(state)
    if action not in {"activate", "rollback"} or (action == "rollback" and (binding is not None or source_root is not None)):
        raise ActivationError("中央动作或版本参数无效")
    current_node, current = policy.current_snapshot(state)
    if source_root is not None:
        if binding is not None:
            raise ActivationError("中央来源与固定版本不能同时指定")
        inspected = store.inspect_core(source_root)
        binding = {key: inspected[key] for key in ("protocol_version", "content_id", "manifest_sha256")}
    selected = (current["previous_binding"] if current else None) if action == "rollback" else binding
    if selected is None:
        raise ActivationError("中央激活需要已导入的固定版本，回退需要前次 current")
    selected = _require_controller(store.load_core(store.validate_binding(selected), state)).binding()
    context = _native_context(state, native_context)
    native = native_agents.preview_global(state, selected, context=context)
    # 在只读预览期即拒绝不能写入current的根形状；不等项目已修改后才发现
    # 明确授权路径不规范，也不从宿主环境或旧activation猜测替代根。
    policy.validate_native_roots(native.recovery_ref["targets"])
    raw = _registry_bytes(state)
    captures = []
    for project in _registered(state, raw):
        policy_node, project_policy = policy.snapshot(state, project)
        binding_node, record = projects.read_binding_record(state, project)
        journal_node, _ = projects._journal(state, project)
        affected = bool(record and record["enabled"] and project_policy["mode"] == "follow")
        runtime = projects.preview(state, project, "use", binding=selected, native_context=context,
                                   native_ready_hosts=tuple(native.hosts)) if affected else None
        captures.append(ProjectCapture(project, policy_node, binding_node, journal_node, runtime, project_policy["mode"]))
    plan = CentralPlan(state, action, selected, current_node, read_state(state, policy.ACTIVATION), raw,
                       tuple(captures), native, context)
    if plan.summary["can_apply"]:
        _publication_budget(plan)
    return plan


def _validate_journal(value: dict) -> dict:
    try:
        return _validate_journal_data(value)
    except ActivationError:
        raise
    except (TypeError, KeyError, RecursionError, OverflowError) as exc:
        raise ActivationError("中央激活恢复记录嵌套结构无效") from exc


def _validate_journal_data(value: dict) -> dict:
    keys = {"schema_version", "id", "phase", "action", "runtime_binding", "current_before", "registry_before",
            "native_ref", "native_receipt", "projects", "conflicts"}
    if (not isinstance(value, dict) or set(value) != keys or type(value["schema_version"]) is not int or value["schema_version"] != 1
            or not isinstance(value["phase"], str) or value["phase"] not in policy.PENDING_PHASES | {"applied", "compensated"}
            or not isinstance(value["action"], str) or value["action"] not in {"activate", "rollback"}):
        raise ActivationError("中央激活恢复记录结构无效")
    # 借current codec校验共享nonce与pin；这个临时对象不发布为生效权威，故
    # 明确给空roots。真正current只使用已核验native_ref.targets，不扩展binding。
    policy.validate_current({"schema_version": 1, "runtime_binding": value["runtime_binding"],
                             "previous_binding": None, "generation": value["id"], "native_roots": []})
    Node.from_value(value["current_before"])
    if value["registry_before"] is not None and not isinstance(value["registry_before"], str):
        raise ActivationError("中央激活登记前像无效")
    if not isinstance(value["projects"], list) or not isinstance(value["conflicts"], list):
        raise ActivationError("中央激活项目清单无效")
    seen = set()
    for row in value["projects"]:
        if not isinstance(row, dict) or set(row) != {"project", "policy_before", "binding_before", "journal_before", "binding_after", "journal_after", "transaction_id", "phase"}:
            raise ActivationError("中央项目恢复前像无效")
        project = Path(row["project"])
        # settled journal是历史事实，项目后来删除不能使无关新任务永久失效。
        # 这里校验路径语法，pending的实际补偿/产物读取仍由项目服务重验物理根。
        if (not project.is_absolute() or ".." in project.parts or str(project) != row["project"]
                or str(project) in seen or row["phase"] not in {"queued", "applying", "applied", "compensated"}):
            raise ActivationError("中央项目恢复身份无效")
        seen.add(str(project))
        for key in ("policy_before", "binding_before", "journal_before"):
            Node.from_value(row[key])
        for key in ("binding_after", "journal_after"):
            if row[key] is not None:
                Node.from_value(row[key])
        policy.validate_current({"schema_version": 1, "runtime_binding": value["runtime_binding"],
                                 "previous_binding": None, "generation": row["transaction_id"], "native_roots": []})
    return value


def _save(state: Path, journal: dict, expected: Node) -> Node:
    _validate_journal(journal)
    with Tree(state) as tree:
        write_control(tree, policy.ACTIVATION, json_bytes({**journal, "conflicts": bounded_conflicts(journal["conflicts"])}), expected=expected)
    return read_state(state, policy.ACTIVATION)


def _journal_value(plan: CentralPlan, identifier: str) -> dict:
    """发布与预算共享封闭格式；预算nonce只取相同固定长度，不产生授权见证。"""
    return {"schema_version": 1, "id": identifier, "phase": "prepared", "action": plan.action,
            "runtime_binding": plan.binding, "current_before": plan.current_before.value(),
            "registry_before": plan.registry_before.decode("utf-8") if plan.registry_before is not None else None,
            "native_ref": plan.native_plan.recovery_ref, "native_receipt": None,
            "projects": [{"project": str(capture.project), "policy_before": capture.policy_before.value(),
                          "binding_before": capture.binding_before.value(), "journal_before": capture.journal_before.value(),
                          "binding_after": None, "journal_after": None, "transaction_id": identifier, "phase": "queued"}
                         for capture in plan.captures if capture.runtime_plan], "conflicts": []}


def _settlement_budget(journal: dict, *, receipt_increment: int = 0) -> int:
    """封闭阶段的逐字段上界，同时涵盖失败/补偿诊断，不截断任何历史Node。

    每个项目及native最多产生一条中央补偿冲突；reason在真实_save中执行同一
    UTF-8字节上限，控制字符占位覆盖最坏JSON转义。phase采用各自最长合法值，
    这里只计算字节，不把这个非真实状态交给codec/恢复/准入。
    """
    bound = copy.deepcopy(journal)
    bound["phase"] = "compensating"
    for row in bound["projects"]:
        row["phase"] = "compensated"
    bound["conflicts"] = bounded_conflicts(bound["conflicts"]) + [
        {"path": row["project"], "reason": "\x00" * CONFLICT_REASON_LIMIT, "code": "project_compensation_conflict"}
        for row in bound["projects"]] + [
        {"path": "native", "reason": "\x00" * CONFLICT_REASON_LIMIT, "code": "native_compensation_conflict"}]
    size = len(json_bytes(bound)) + receipt_increment
    publication_capacity(size)
    return size


def _publication_budget(plan: CentralPlan) -> int:
    """在任何prepared/目标写之前汇总生产者预算；未知格式不猜测、不落盘。

    子记录进入中央Node时正文再次base64；它们的生产者只返回已证明的普通
    记录大小。原生receipt由其生产者计入嵌入缩进，中央不复制native wire。
    两种占位都仅用于本函数RAM长度计算，不能作为应用收据或文件归属。
    """
    from . import native_agents
    increment = native_agents.receipt_budget(plan.native_plan)
    if type(increment) is not int or increment < 0:
        raise ActivationError("原生生产者没有提供有效容量预算")
    journal = _journal_value(plan, "f" * 32)
    affected = [capture for capture in plan.captures if capture.runtime_plan]
    for capture, row in zip(affected, journal["projects"]):
        budget = projects.publication_budget(capture.runtime_plan)
        if not isinstance(budget, projects.PublicationBudget):
            raise ActivationError("项目生产者没有提供有效容量预算")
        for field, size in (("binding_after", budget.binding_after_bytes), ("journal_after", budget.journal_after_bytes)):
            publication_capacity(size)
            row[field] = Node("file", b"x" * size, 0o600, CAPACITY_IDENTITY).value()
    publication_capacity(len(plan.activation_before.payload))
    publication_capacity(len(json_bytes(_expected_current(journal))))
    return _settlement_budget(journal, receipt_increment=increment)


def _expected_current(journal: dict) -> dict:
    """发布与已发布恢复共用本批current值，避免只检查部分生效字段。

    本函数不读取可变current，也不把语法校验当作原生成功证据；调用方仍需
    完成真实项目/原生核验。根授权只复制本批精确targets，不复制witness或
    receipt；previous也由同一个固定前像推导，恢复不能认领后来的外部改动。
    """
    before_node = Node.from_value(journal["current_before"])
    if before_node.kind not in {"missing", "file"}:
        raise ActivationError("中央 current 前像不是私有记录或缺失状态")
    before = policy.validate_current(unique_json(before_node.payload)) if before_node.kind == "file" else None
    selected = store.validate_binding(journal["runtime_binding"])
    reference = journal["native_ref"]
    if not isinstance(reference, dict) or "targets" not in reference:
        raise ActivationError("中央 current 缺少本批原生根引用")
    current = {"schema_version": 1, "runtime_binding": selected,
               "previous_binding": before["runtime_binding"] if before and before["runtime_binding"] != selected else before["previous_binding"] if before else None,
               "generation": journal["id"],
               "native_roots": policy.validate_native_roots(reference["targets"])}
    return policy.validate_current(current)


def _check_plan(plan: CentralPlan) -> None:
    if _registry_bytes(plan.state) != plan.registry_before:
        raise ActivationError("项目登记表在中央预览后变化")
    if policy.current_snapshot(plan.state)[0] != plan.current_before or read_state(plan.state, policy.ACTIVATION) != plan.activation_before:
        raise ActivationError("中央 current 或激活记录在预览后变化")
    for capture in plan.captures:
        if (policy.snapshot(plan.state, capture.project)[0] != capture.policy_before
                or projects.read_binding_record(plan.state, capture.project)[0] != capture.binding_before
                or projects._journal(plan.state, capture.project)[0] != capture.journal_before):
            raise ActivationError("中央预览中的项目策略或前像已变化：" + str(capture.project))
        if capture.runtime_plan:
            with Tree(capture.project) as tree:
                projects._check_plan(capture.runtime_plan, tree)
    _require_controller(store.load_core(plan.binding, plan.state))


def apply(plan: CentralPlan, *, cancel=None) -> dict:
    """应用同一提案；取消在 prepared 前零写，之后必须完成结算再返回。"""
    from . import native_agents
    if not isinstance(plan, CentralPlan) or not plan.summary["can_apply"]:
        raise ActivationError("中央预览含冲突，不能应用")
    if cancel is not None and cancel.is_set():
        raise ActivationError("操作已取消，尚未应用中央计划")
    # 第一次校验在协调锁创建前；最终前像校验后再证明一次，不能由绕过CLI的
    # 直接服务调用把超容量计划推进到native prepare或第一个项目写入。
    _publication_budget(plan)
    with policy.coordination(plan.state):
        policy.ensure_management_settled(plan.state)
        _check_plan(plan)
        _publication_budget(plan)
        identifier = uuid.uuid4().hex
        journal = _journal_value(plan, identifier)
        for row in journal["projects"]:
            row["transaction_id"] = uuid.uuid4().hex
        snapshot = _save(plan.state, journal, plan.activation_before)
        with policy.activation_scope(plan.state, identifier):
            try:
                journal["native_receipt"] = native_agents.apply_global(plan.native_plan)
                journal["phase"] = "applying"
                snapshot = _save(plan.state, journal, snapshot)
                affected = [capture for capture in plan.captures if capture.runtime_plan]
                for capture, row in zip(affected, journal["projects"]):
                    row["phase"] = "applying"
                    snapshot = _save(plan.state, journal, snapshot)
                    native_issues = native_agents.verify_global(journal["native_ref"], context=plan.native_context)
                    if native_issues:
                        raise ActivationError("全局原生产物在项目应用前发生变化", native_issues)
                    projects.apply(capture.runtime_plan, transaction_id=row["transaction_id"])
                    row["binding_after"] = projects.read_binding_record(plan.state, capture.project)[0].value()
                    row["journal_after"] = projects._journal(plan.state, capture.project)[0].value()
                    row["phase"] = "applied"
                    snapshot = _save(plan.state, journal, snapshot)
                # current 发布前再次核对 raw registry 及全部策略，不能只信持锁。
                if _registry_bytes(plan.state) != plan.registry_before or any(
                        policy.snapshot(plan.state, capture.project)[0] != capture.policy_before for capture in plan.captures):
                    raise ActivationError("中央发布前登记表或策略发生变化")
                _verify_applied(plan.state, journal, plan.native_context)
                for capture in plan.captures:
                    if capture.runtime_plan is None and (projects.read_binding_record(plan.state, capture.project)[0] != capture.binding_before
                                                        or projects._journal(plan.state, capture.project)[0] != capture.journal_before):
                        raise ActivationError("未参与激活的固定项目前像发生变化")
                journal["phase"] = "publishing"
                snapshot = _save(plan.state, journal, snapshot)
                current = _expected_current(journal)
                with Tree(plan.state) as tree:
                    write_control(tree, policy.CURRENT, json_bytes(current), expected=plan.current_before)
                # 若在此后中断，不能恢复旧项目却留下新 current；recover 会验证
                # 已发布批次并补终态。此异常分支仅补偿 current 尚未发布的批次。
                journal["phase"] = "applied"
                snapshot = _save(plan.state, journal, snapshot)
            except BaseException:
                _, actual = policy.current_snapshot(plan.state)
                if actual and actual["generation"] == identifier:
                    raise ActivationError("中央 current 已发布，结算中断；请恢复全局事务以核验并完成")
                _compensate(plan.state, journal, snapshot, plan.native_context)
                raise
        return {**status(plan.state), "transaction_id": identifier, "projects_applied": len(journal["projects"]),
                "cancel_requested": bool(cancel is not None and cancel.is_set())}


def _compensate(state: Path, journal: dict, snapshot: Node, context) -> dict:
    from . import native_agents
    journal["phase"] = "compensating"
    snapshot = _save(state, journal, snapshot)
    conflicts = []
    for row in reversed(journal["projects"]):
        try:
            projects.compensate(state, Path(row["project"]), row["transaction_id"],
                                Node.from_value(row["binding_before"]), Node.from_value(row["journal_before"]))
            row["phase"] = "compensated"
            snapshot = _save(state, journal, snapshot)
        except (OSError, ValueError) as exc:
            conflicts.append({"path": row["project"], "reason": str(exc), "code": "project_compensation_conflict"})
    try:
        receipt = native_agents.compensate_global(journal["native_ref"], context=context)
        # noop是原生服务复核本批持久ref中的witness后确认“未写原生产物”的合法
        # 结算，不需要再撤回全局文件；不能把它误判为冲突，使项目已补偿的批次
        # 永久卡在pending。仅接纳明确成功状态，任何conflicts或未知状态仍关门。
        if not isinstance(receipt, dict) or receipt.get("status") not in {"compensated", "not_started", "noop"} or receipt.get("conflicts"):
            conflicts.append({"path": "native", "reason": "原生服务返回未完成的条件补偿结果",
                              "code": "native_compensation_conflict"})
    except (OSError, ValueError) as exc:
        conflicts.append({"path": "native", "reason": str(exc), "code": "native_compensation_conflict"})
    journal.update(phase="conflict" if conflicts else "compensated", conflicts=conflicts)
    _save(state, journal, snapshot)
    if conflicts:
        raise ActivationError("中央激活补偿遇到冲突，保留待结算门与全部恢复资料", conflicts)
    return {"compensated": True, "transaction_id": journal["id"]}


def _verify_applied(state: Path, journal: dict, context) -> None:
    """current发布前与发布后恢复复用完整收据核验，避免先应用项目被后改掩盖。"""
    from . import native_agents
    for row in journal["projects"]:
        project = Path(row["project"])
        binding_node, record = projects.read_binding_record(state, project)
        journal_node, project_journal = projects._journal(state, project)
        checked = projects.status(state, project)
        if (row["phase"] != "applied" or row["binding_after"] is None or row["journal_after"] is None
                or binding_node != Node.from_value(row["binding_after"]) or journal_node != Node.from_value(row["journal_after"])
                or not record or record["generation"] != row["transaction_id"] or record["runtime_binding"] != journal["runtime_binding"]
                or not record["enabled"] or not project_journal or project_journal["id"] != row["transaction_id"]
                or project_journal["phase"] != "applied" or not checked["resources_healthy"]):
            raise ActivationError("中央已应用项目前像或产物含后续变化，保留恢复资料")
    native_issues = native_agents.verify_global(journal["native_ref"], context=context)
    if native_issues:
        raise ActivationError("中央已应用全局原生产物含后续变化", native_issues)


def preview_recovery(state: Path, *, native_context=None) -> RecoveryPlan:
    state = store.state_root(state)
    node = read_state(state, policy.ACTIVATION)
    if node.kind != "file" or node.mode != 0o600:
        raise ActivationError("没有可恢复的中央激活记录")
    record = _validate_journal(unique_json(node.payload))
    if record["phase"] not in policy.PENDING_PHASES:
        raise ActivationError("中央激活已经结算")
    _settlement_budget(record)
    return RecoveryPlan(state, node, record, _native_context(state, native_context))


def recover(plan: RecoveryPlan) -> dict:
    from . import native_agents
    if not isinstance(plan, RecoveryPlan):
        raise ActivationError("需要同一进程预览的恢复计划")
    _settlement_budget(plan.record)
    with policy.coordination(plan.state), policy.activation_scope(plan.state, plan.record["id"]):
        if read_state(plan.state, policy.ACTIVATION) != plan.before:
            raise ActivationError("中央恢复记录在预览后变化")
        journal = unique_json(plan.before.payload)
        current_node, current = policy.current_snapshot(plan.state)
        if current and current["generation"] == journal["id"]:
            if current != _expected_current(journal):
                raise ActivationError("已发布 current 的版本或根授权与激活记录不一致")
            _verify_applied(plan.state, journal, plan.native_context)
            # 原生核验可能读多个文件；协调锁不能禁止外部编辑器保存current。
            # 终态保存前重验最初完整Node，连同字节相同的新inode也视为漂移；
            # 失败只保留外部current和待结算journal，不修正授权或误报恢复成功。
            if policy.current_snapshot(plan.state)[0] != current_node:
                raise ActivationError("已发布 current 在资源核验期间发生变化，保留待结算门")
            journal.update(phase="applied", conflicts=[])
            _save(plan.state, journal, plan.before)
            return {**status(plan.state), "recovered": True, "transaction_id": journal["id"]}
        before = Node.from_value(journal["current_before"])
        if policy.current_snapshot(plan.state)[0] != before:
            raise ActivationError("中央 current 已被其他修改，拒绝条件补偿")
        return _compensate(plan.state, journal, plan.before, plan.native_context)


def new_task_gate(state: Path, project: Path, binding: dict | None = None) -> dict:
    """只读新任务许可；旧任务 read/helper 不调用此门，也不读取 current。"""
    state, project = store.state_root(state), canonical_project(project)
    policy.ensure_settled(state)
    checked = projects.status(state, project)
    selected = checked["effective_binding"]
    if not checked["new_task_allowed"] or selected is None:
        raise ActivationError("项目未启用、当前资源冲突或有效策略未结算，不能创建新任务")
    if binding is not None and store.validate_binding(binding) != selected:
        raise ActivationError("新任务显式 pin 不是项目有效策略版本，不能创建新任务")
    return store.load_core(selected, state).binding()
