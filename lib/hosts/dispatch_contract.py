"""派发准入使用的接口和已持久化的 AGY 历史格式。"""

from contextlib import nullcontext
import json
from pathlib import Path
import re
import sys
from typing import Callable

from lib.task_graph import TaskGraphError


# 旧记录在任何宿主都必须使用同一 UUID、nonce 和父子身份规则。这里不读取宿主日志。
AGY_CONVERSATION_UUID = re.compile(r"[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}")
AGY_PARENT_ERROR = "AGY dispatch requires --pm-id antigravity:<current parent conversation UUID>"
AGY_RELEASE_ERROR = "AGY release requires the current PM task pool and original dispatch marker"


def validate_claim(claim: dict) -> None:
    if (not isinstance(claim, dict) or set(claim) != {"parent", "nonce"}
            or not isinstance(claim["parent"], str) or not AGY_CONVERSATION_UUID.fullmatch(claim["parent"])
            or not isinstance(claim["nonce"], str) or not re.fullmatch(r"[0-9a-f]{64}", claim["nonce"])):
        raise TaskGraphError("invalid AGY parent or claim nonce")


def validate_child_id(parent: str, agent_id: str) -> None:
    if not isinstance(agent_id, str) or not AGY_CONVERSATION_UUID.fullmatch(agent_id) or parent == agent_id:
        raise TaskGraphError("AGY binding requires the child conversation UUID returned by invoke_subagent")


def reject_unexpected_marker(task: dict, receipt: dict) -> None:
    if "dispatch_marker" in receipt and "antigravity_claim" not in task:
        raise TaskGraphError("unexpected AGY dispatch marker on a non-AGY claim")


def bound_export_reference(task: dict) -> dict | None:
    """已绑定的历史 AGY 原件可用同一实例引用刷新旧交接副本。"""
    return task.get("agent_ref") if "antigravity_claim" in task else None


class DispatchPolicy:
    """共享准入的默认策略。各宿主只提供证据，原件更新及占用由任务池负责。"""

    native_required = False

    def delivery_input(self, project: Path, config: Path, path: Path | None, expected: str | None):
        """取得本次交付对象及其最终发布边界；默认宿主沿用文件或标准输入。"""
        if expected is not None:
            raise TaskGraphError("input fingerprint requires a PM-bound delivery")
        return json.loads(path.read_text() if path else sys.stdin.read()), nullcontext

    def guard_public_update(self, task: dict, operation: dict) -> None:
        """任务池独占 AGY 首绑；已有历史可读，同值写回沿用原更新协议。"""
        fields = operation.get("set")
        fields = fields if isinstance(fields, dict) else {}
        new_ref = fields.get("agent_ref")
        claim = operation.get("claim")
        agy_task = "antigravity_claim" in task or self.native_required
        if "antigravity_claim" in task and {"release_claim", "confirm_uncreated"} & operation.keys():
            # 两类释放都会归还名额，只有持原 PM 领取回执的池入口可在核对标记后发布。
            # 普通 withdraw 继续允许登记用户撤回；创建结果未确认时仍处于 STOP_REQUESTED。
            raise TaskGraphError(AGY_RELEASE_ERROR)
        if isinstance(claim, dict) and (agy_task or "antigravity_claim" in claim):
            raise TaskGraphError("AGY claim requires the current PM task pool")
        if isinstance(new_ref, dict) and "agent_ref" not in task and (agy_task or new_ref.get("host") == "antigravity"):
            raise TaskGraphError("AGY first binding requires the current PM task pool and native receipt")
        # 独立 QA 是 Reviewer 的交付；即使 Light 允许用户点名 PM 实施，
        # 未绑定的 Reviewer 或升级前人工登记的别名都不能据此新签发 QA 通过。
        accepting = (fields.get("state") == "QA_PASSED" and task.get("state") != "QA_PASSED"
                     or bool({"accept_request", "accept_foundation"} & operation.keys()))
        ref = task.get("agent_ref", {})
        if task.get("task_type") == "qa" and accepting and (agy_task or ref.get("host") == "antigravity"):
            if "antigravity_claim" not in task or ref.get("host") != "antigravity":
                raise TaskGraphError("AGY independent QA acceptance requires the native-bound Reviewer for this task")

    def check_pool_claim(self) -> None:
        """在创建登记项或领取前校验本端所需的 PM 身份。"""

    def check_claim_target(self, root: Path, payload: dict, task: dict) -> None:
        """在持准入锁的原件快照上核对宿主派发前置证据。"""

    def claim_fields(self, root: Path, target: dict, basis: str) -> tuple[dict, dict]:
        """分别返回要加入原件和本次回执的宿主字段。"""
        return {}, {}

    def check_release(self, root: Path, target: dict, task: dict, receipt: dict) -> bool:
        """校验本次回执；返回是否须使用持池锁的发布入口。"""
        reject_unexpected_marker(task, receipt)
        if "antigravity_claim" in task:
            # 其他宿主可以阅读并继续跟踪旧占用，释放须回到负责创建的 AGY 池。
            raise TaskGraphError(AGY_RELEASE_ERROR)
        return False

    def check_binding(self, root: Path, target: dict, task: dict, receipt: dict,
                      reference: dict, execution_root: Callable[[], Path]) -> None:
        if "antigravity_claim" in task or reference["host"] == "antigravity":
            raise TaskGraphError(AGY_PARENT_ERROR)


DEFAULT_DISPATCH = DispatchPolicy()
