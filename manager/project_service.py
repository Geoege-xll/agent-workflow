"""项目登记、解析、状态与启停组合计划的唯一业务入口。

登记锁、偏好协调锁及原生事务的取得顺序沿既有实现保持；原生操作完成后登记
发布失败仍报告真实跨资源部分完成，不伪装原子提交。本模块只依赖安全文件
边界、中央运行时服务与 lib，不反向导入模型事务 service。
"""

from __future__ import annotations

from contextlib import ExitStack
from dataclasses import dataclass
import json
from pathlib import Path

from lib.hosts.claude_instructions import read_file
from lib.central import role_preferences
from lib import runtime_store
from . import runtime_policy, runtime_service, state_files
from lib.central.runtime_project import Node, json_bytes

SOURCE = Path(__file__).resolve().parents[1]


def registry(state: Path) -> dict:
    path = state_files.secure_path(state, "projects.json")
    return parse_registry(read_file(path))


def parse_registry(raw: bytes | None) -> dict:
    """解析登记原始字节；缺失使用空表，坏 schema/字段形状抛 ValueError。

    只读返回登记合同，不解析或创建项目目录；计划、列表与偏好消费者使用
    同一校验入口，避免准备与条件发布对同一前像作出不同解释。
    """
    data=json.loads(raw) if raw else {"schema":1,"registered":[],"hidden":[]}
    if not isinstance(data,dict) or data.get("schema") != 1 or any(not isinstance(data.get(key),list) or not all(isinstance(value,str) for value in data[key]) for key in ("registered","hidden")):
        raise ValueError("项目列表格式无效")
    return data


def projects(state: Path, scan: Path | None = None) -> list[Path]:
    data=registry(state)
    rows=data["registered"]
    hidden=set(data["hidden"])
    result = set()
    for value in rows:
        path = Path(value)
        if path.is_dir() and not path.is_symlink():
            result.add(path.resolve())
    if scan and scan.is_dir():
        # 仅扫描指定目录的直接子目录，不递归业务代码、worktree 或历史会话。
        for child in scan.iterdir():
            if not child.name.startswith(".") and not child.is_symlink() and (child/".agent-workflow/project.yaml").is_file():
                result.add(child.resolve())
    return sorted((row for row in result if str(row) not in hidden), key=lambda row: (row.name.casefold(), str(row)))


def register(state: Path, project: Path, remove: bool = False) -> None:
    # 旧公开签名保留；登记/删除与新入口消费相同计划和条件发布规则。
    apply_project(preview_project(state, project, "del" if remove else "add"))


class ProjectResolutionError(ValueError):
    """短名称拒绝携带明确路径候选，JSON 出口不必展示其他底层错误原文。"""
    def __init__(self, message: str, candidates):
        self.candidates = tuple(str(value) for value in candidates)
        super().__init__(message)


def resolve_project(state: Path, raw: str | Path) -> Path:
    """接受已存在路径或唯一登记短名称；重名和未知名称都明确拒绝。

    短名称只来自显式登记表，不把扫描到的同名目录自动视为用户目标。
    路径存在时仍沿原 state_files.project_path 解析，保留调用目录和物理根身份语义。
    """
    candidate = Path(raw).expanduser()
    # 单段裸名称可能同时是 cwd 中的目录和登记名称；先解决登记歧义，不能因为
    # 当前目录偶然存在同名项就绕过重名拒绝。./name 等显式路径仍沿旧路径语义。
    named = not candidate.is_absolute() and "/" not in str(raw) and str(raw) not in {".", ".."}
    if not named:
        return state_files.project_path(candidate)
    registered = registry(state)["registered"]
    matches = sorted({state_files.project_path(value) for value in registered
                      if Path(value).name == str(raw) and Path(value).is_dir()})
    if len(matches) == 1:
        return matches[0]
    if not matches and (candidate.exists() or candidate.is_symlink()):
        return state_files.project_path(candidate)
    candidates = matches or sorted({Path(value) for value in registered})
    # 保持原名称解析诊断的逐路径控制符过滤和 1000 字符界限；此处仅处理
    # 路径候选，不依赖模型目录模块，JSON/终端出口仍继续应用各自展示保护。
    detail = "、".join("".join(char for char in str(value) if char.isprintable())[:1000] for value in candidates) or "无登记项目"
    raise ProjectResolutionError(("项目名称重名，请使用完整路径。候选：" if matches else "未知项目名称。已登记候选：") + detail,
                                 candidates)


def project_status(state: Path, project: Path) -> dict:
    """CLI 与 TUI 共用只读状态；state 字段沿原生合同表示业务状态。"""
    return runtime_service.status(state_files.state_root(state), state_files.project_path(project))


def project_summaries(state: Path, scan: Path | None = None) -> list[dict]:
    """每行展示本机实际版本、前次版、宿主和冲突；单个坏项目不隐藏其余项目。"""
    registered = set(registry(state)["registered"])
    result = []
    for project in projects(state, scan):
        try:
            row = project_status(state, project)
        except (OSError, ValueError):
            # 坏配置可能包含秘密；列表只给固定诊断，单项目操作仍从原生边界拒绝。
            row = {"schema_version": 1, "project": str(project), "state": "conflict", "enabled": False,
                   "runtime_binding": None, "previous_binding": None, "hosts": [], "managed_paths": [],
                   "conflicts": [{"path": ".", "reason": "状态读取失败，请单独检查项目绑定和受管资源"}],
                   "pending_transaction": None}
        result.append({**row, "registered": str(project) in registered})
    return result


def runtime_binding(state: Path, content_id: str) -> dict:
    """内容 ID 必须完整匹配已验证核心；不接受前缀、版本标签或 latest 回退。"""
    binding = runtime_store.validate_binding({"protocol_version": runtime_store.PROTOCOL_VERSION,
                                              "content_id": content_id, "manifest_sha256": content_id})
    return runtime_store.load_core(binding, state_files.state_root(state)).binding()


@dataclass(frozen=True)
class ProjectPlan:
    """项目登记组合计划；原生启停/换版仍只有 runtime_service 一份实现。

    registry_before 仅在当前进程用于条件发布，不进入 summary。apply 持登记锁
    并核对原始字节，避免手改或并发登记被覆盖；原生计划自行重查项目和核心。
    """
    state: Path
    project: Path
    action: str
    registry_before: bytes | None
    registered_before: bool
    registered_after: bool
    runtime_plan: runtime_service.ActivationPlan | None
    status_before: dict
    policy_before: Node | None = None
    policy_after: bytes | None = None

    @property
    def summary(self) -> dict:
        native = self.runtime_plan.summary if self.runtime_plan else None
        return {"schema_version": 1, "action": self.action, "project": str(self.project),
                "state_dir": str(self.state), "registered_before": self.registered_before,
                "registered_after": self.registered_after, "runtime_action": native["action"] if native else None,
                "runtime": native, "status_before": self.status_before,
                "policy_after": json.loads(self.policy_after) if self.policy_after else None,
                "can_apply": native["can_apply"] if native else True,
                "conflicts": native["conflicts"] if native else [],
                "changes": native["changes"] if native else []}


# 项目组合预览把status、固定版本选择和native准备置于同一纯读调用栈；
# 嵌套readonly借父scope，各实际根/pin独立验证，最外层尾验后才交付纯Plan。
# apply仍自行fresh校验；显式source双inspect/零导入及原registry CAS不变。
@runtime_store.read_operation
def preview_project(state: Path, project: Path, action: str, *, enable: bool = False,
                    source_root: Path | None = None, content_id: str | None = None,
                    hosts=None, native_context=None) -> ProjectPlan:
    """只读生成 add/del/启停/版本计划；首次启用默认跟随已激活 current。

    重开项目按有效 follow/pinned 策略选版；显式 source_root 才导入指定来源，
    content_id 只选择已存在且验证成功的中央版本。所有原生业务限制交给所有者。
    """
    state, project = state_files.state_root(state), state_files.project_path(project)
    runtime_policy.ensure_management_settled(state)
    if action not in {"add", "del", "enable", "disable", "use", "follow", "rollback", "repair"}:
        raise ValueError("未知项目管理动作")
    if (type(enable) is not bool or (enable and action != "add")
            or (source_root is not None and content_id is not None)
            or (action == "use" and content_id is None)
            or (content_id is not None and action not in {"add", "enable", "use"})
            or (source_root is not None and action not in {"add", "enable"})
            or (action == "add" and not enable and (source_root is not None or content_id is not None))):
        raise ValueError("项目管理动作与启用/来源/固定版本参数不匹配")
    snapshot = read_file(state_files.secure_path(state, "projects.json"))
    data = parse_registry(snapshot)
    registered = str(project) in data["registered"]
    before = project_status(state, project)
    policy_node, previous_policy = runtime_policy.snapshot(state, project)
    next_policy = None
    if action == "use" or (content_id is not None and action in {"enable", "add"}):
        next_policy = runtime_policy.policy_value(project, "pinned", runtime_binding(state, content_id))
    elif action == "follow":
        next_policy = runtime_policy.policy_value(project, "follow")
    native_action = "enable" if action == "add" and enable else "disable" if action == "del" else action
    native = None
    if action == "follow":
        # 清锁是独立策略变化；停用项目保持停用，下一次 enable 才物化 current。
        if before["declared_enabled"]:
            _, current = runtime_policy.current_snapshot(state)
            if current is None:
                raise ValueError("尚未选择中央 current，请先导入并激活版本")
            native = runtime_service.preview(state, project, "use", binding=current["runtime_binding"],
                                             hosts=hosts, native_context=native_context)
    elif native_action != "add":
        selected = runtime_binding(state, content_id) if content_id is not None else None
        source = source_root
        if native_action == "enable" and source is None and selected is None:
            selected = runtime_policy.effective_binding(state, project, fallback=before["runtime_binding"])
        if native_action == "enable" and source is None and selected is None:
            # 公共服务不能借调用者所在源码目录隐式导入核心，否则CLI与TUI会
            # 得到不同的首次启用语义，也会制造没有current权威的“已安装”状态。
            # 明确给出的source/content仍沿既有显式合同；普通启用只消费有效策略。
            raise ValueError("尚无可用中央版本；请先运行 runtime install，再运行 runtime activate，然后启用项目")
        native = runtime_service.preview(state, project, native_action, source_root=source,
                                         binding=selected, hosts=hosts, native_context=native_context)
    if action == "rollback" and native and native.binding_json:
        # 项目回退是显式版本选择，与中央 rollback 不同；锁定实际回退的版本，
        # 后续全局激活不会把用户刚回退的项目再次推走。
        next_policy = runtime_policy.policy_value(project, "pinned", json.loads(native.binding_json))
    return ProjectPlan(state, project, action, snapshot, registered,
                       True if action == "add" else False if action == "del" else registered, native, before,
                       policy_node, json_bytes(next_policy) if next_policy is not None else None)


def apply_project(plan: ProjectPlan, *, cancel=None) -> dict:
    """应用同一条件计划；删除先停用成功才解除登记，任何失败都正常抛出。

    登记与项目是跨资源操作，不能宣称原子提交：原生操作已成功而登记写失败时
    保留真实状态并报错，status 仍可查看。取消在开始前无副作用；同步原生事务
    开始后等待结算，并用 cancel_requested 报告迟到请求，不把成功伪报取消。
    """
    if not isinstance(plan, ProjectPlan):
        raise ValueError("需要同一进程生成的项目管理计划")
    if not plan.summary["can_apply"]:
        raise runtime_service.ActivationError("项目预览含冲突，不能应用", plan.summary["conflicts"])
    if cancel is not None and cancel.is_set():
        raise ValueError("操作已取消，尚未应用项目计划")
    registration = plan.action in {"add", "del"}
    with ExitStack() as stack:
        # 组合登记入口也先取偏好协调锁，再取 registry / install / central-state。
        # 仅登记项目同样会改变全局计划的影响集合，不能绕过全局来源守卫。
        stack.enter_context(role_preferences.coordination(plan.state))
        runtime_policy.ensure_management_settled(plan.state)
        if plan.policy_before is not None and runtime_policy.snapshot(plan.state, plan.project)[0] != plan.policy_before:
            raise ValueError("项目版本策略在预览后变化，请刷新后重试")
        if registration:
            stack.enter_context(state_files.lock(plan.state, "registry"))
            if read_file(state_files.secure_path(plan.state, "projects.json")) != plan.registry_before:
                raise ValueError("项目登记表在预览后发生变化，请刷新后重试")
        result = runtime_service.apply(plan.runtime_plan) if plan.runtime_plan else project_status(plan.state, plan.project)
        if plan.policy_after is not None:
            runtime_policy.write_policy(plan.state, plan.project, json.loads(plan.policy_after), plan.policy_before)
            result = project_status(plan.state, plan.project)
        if registration:
            # 持锁不等于可覆盖外部编辑器的保存；发布前仍比较精确前像。
            if read_file(state_files.secure_path(plan.state, "projects.json")) != plan.registry_before:
                raise ValueError("原生项目操作已结算，但登记表已有其他修改；未覆盖登记，请查看 status")
            data = parse_registry(plan.registry_before)
            rows, hidden = set(data["registered"]), set(data["hidden"])
            if plan.action == "add":
                rows.add(str(plan.project)); hidden.discard(str(plan.project))
            else:
                rows.discard(str(plan.project)); hidden.add(str(plan.project))
            data.update(registered=sorted(rows), hidden=sorted(hidden))
            payload = (json.dumps(data, ensure_ascii=False, indent=2)+"\n").encode()
            with state_files.AnchoredFile(plan.state, "projects.json") as target:
                previous = target.read()
                if previous[0] != plan.registry_before:
                    raise ValueError("原生项目操作已结算，但登记表在发布前变化；已停止覆盖，请查看 status")
                target.write(payload, 0o600, previous)
        return {**result, "action": plan.action, "registered": plan.registered_after,
                "cancel_requested": bool(cancel is not None and cancel.is_set())}
