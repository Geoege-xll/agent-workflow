"""从 AGY 主会话的本机原生记录核对本次领取对应的创建回执。"""

import hashlib
import json
import os
from pathlib import Path
import re
import secrets

from lib import plugin_resources
from lib.safe_text import open_file, read_file
from lib.task_graph import TaskGraphError


# 1.5.13 的回执没有可跨并行工具定位的 call ID，只认单一调用、紧邻且连续的结果。
# Created/Completed 是宿主附加的时间行；命令输出和聊天的相同文字不能作为回执。
_UUID = re.compile(r"[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}")
_MARKER = "XY-WORKFLOW-CLAIM "
_RECEIPT_HEADER = re.compile(r"(?:(?:Created|Completed) At: [0-9T:+.Z-]+\n)*Created the following subagent:\n")
_RECEIPT_FOOTER = ("\nThe subagent will send you a message when it has completed its task or requires guidance. "
                   "There is no need to poll for its response.")
_LOG = Path(".system_generated/logs/transcript.jsonl")


def packaged_host() -> bool:
    # 正常插件入口已经核过来源清单，再从 helper 自己所属的安装取宿主；
    # 用户命令的 --host/--pm-id 和环境变量不能把 AGY 包切换到另一个宿主的绑定分支。
    return (Path(__file__).resolve().parents[2] / ".antigravity-plugin/plugin.json").is_file()


def parent_id(pm_id: str) -> str:
    host, _, parent = pm_id.partition(":")
    if host != "antigravity" or not _UUID.fullmatch(parent):
        raise TaskGraphError("AGY dispatch requires --pm-id antigravity:<current parent conversation UUID>")
    return parent


def new_claim(pm_id: str) -> dict:
    # 即使同一份输入被恢复，同一任务在确认未创建后重新领取也必须获得新的派发标记。
    return {"parent": parent_id(pm_id), "nonce": secrets.token_hex(32)}


def validate_claim(claim: dict) -> None:
    if (not isinstance(claim, dict) or set(claim) != {"parent", "nonce"}
            or not isinstance(claim["parent"], str) or not _UUID.fullmatch(claim["parent"])
            or not isinstance(claim["nonce"], str) or not re.fullmatch(r"[0-9a-f]{64}", claim["nonce"])):
        raise TaskGraphError("invalid AGY parent or claim nonce")


def validate_child_id(parent: str, agent_id: str) -> None:
    if not isinstance(agent_id, str) or not _UUID.fullmatch(agent_id) or parent == agent_id:
        raise TaskGraphError("AGY binding requires the child conversation UUID returned by invoke_subagent")


def dispatch_marker(root: Path, target: dict, basis: str, claim: dict) -> str:
    # 原件路径独立参与指纹，防止复制已领取的图后用另一路径借用同一个创建事件。
    body = json.dumps([str(root), target, basis, claim], ensure_ascii=False, sort_keys=True,
                      separators=(",", ":")).encode("utf-8")
    return _MARKER + hashlib.sha256(body).hexdigest()


def guard_public_update(task: dict, operation: dict) -> None:
    """任务池独占 AGY 首绑；已有历史可读，同值写回沿用原更新协议。"""
    fields = operation.get("set")
    fields = fields if isinstance(fields, dict) else {}
    new_ref = fields.get("agent_ref")
    claim = operation.get("claim")
    agy_task = "antigravity_claim" in task or packaged_host()
    if "antigravity_claim" in task and {"release_claim", "confirm_uncreated"} & operation.keys():
        # 两类释放都会归还名额，只有持原 PM 领取回执的池入口可在核对标记后发布。
        # 普通 withdraw 继续允许登记用户撤回；创建结果未确认时仍处于 STOP_REQUESTED。
        raise TaskGraphError("AGY release requires the current PM task pool and original dispatch marker")
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


def _brain() -> Path:
    # shell 可以重设 HOME；用户可写项目及调用者提供的 HOME 不能取得宿主日志权威。
    # 当前核实的是使用系统账户目录的 POSIX AGY CLI；别的平台缺少证据时保留占用。
    if os.name != "posix":
        raise TaskGraphError("AGY native transcript location is unverified on this platform")
    import pwd
    return Path(pwd.getpwuid(os.getuid()).pw_dir) / ".gemini/antigravity-cli/brain"


def _matches_role(selector: str, role: str, prompt: str) -> bool:
    # TypeName 是宿主真正选择的原生类型，Role 仅是调用者填写的描述。
    # 错派到另一个命名角色时，即使 Prompt 里出现正确角色名或角色正文也不能视为选中该角色。
    if selector == role:
        return True
    if selector != "research":
        return False
    # 仅对已经核实的内建通用入口允许正文交接。定位当前包自身的原始角色文件，
    # 保持正文段落、顺序和内容不变；用户项目中的同名文件、缩写或自由标签不能代替它。
    relative = f"roles/{role}.md"
    if plugin_resources.plugin_root() is not None:
        source = plugin_resources.read_source(relative)
    else:
        source = read_file(Path(__file__).resolve().parents[2] / relative)
    if not source:
        return False
    text = source.decode("utf-8").replace("\r\n", "\n")
    header, separator, body = text.partition("\n---\n")
    body = body.strip("\n")
    return (header.startswith("---\n") and bool(separator and body)
            and "\n" + body + "\n" in "\n" + prompt.replace("\r\n", "\n") + "\n")


def _dispatch_step(event: dict, marker: str, role: str) -> int | None:
    calls = event.get("tool_calls")
    if (event.get("type") != "PLANNER_RESPONSE" or not isinstance(calls, list)
            or len(calls) != 1 or not isinstance(calls[0], dict) or calls[0].get("name") != "invoke_subagent"):
        return None
    args = calls[0].get("args")
    if not isinstance(args, dict) or not all(isinstance(args.get(key), str) for key in ("Prompt", "TypeName")):
        return None
    try:
        # AGY 的参数值保留了一层 JSON 字符串编码。只接受一个独立标记行；
        # 防止同一 Prompt 同时夹带多个任务的标记，让一个结果冒充其中任一任务。
        prompt = json.loads(args["Prompt"])
        selector = json.loads(args["TypeName"])
    except (ValueError, RecursionError):
        return None
    if (isinstance(prompt, str) and [line for line in prompt.splitlines() if line.startswith(_MARKER)] == [marker]
            and _matches_role(selector, role, prompt)):
        return event["step_index"]
    return None


def _matches_receipt(content: str, agent_id: str, log: Path, workspace: Path) -> bool:
    header = _RECEIPT_HEADER.match(content)
    if not header:
        return False
    try:
        payload, end = json.JSONDecoder().raw_decode(content, header.end())
    except (ValueError, RecursionError):
        return False
    if not isinstance(payload, dict) or content[end:] != _RECEIPT_FOOTER:
        return False
    roots = payload.get("workspaceUris")
    return (payload.get("conversationId") == agent_id and payload.get("logAbsoluteUri") == log.as_uri()
            and isinstance(roots, list) and workspace.as_uri() in roots)


def verify_creation(parent: str, agent_id: str, workspace: Path, marker: str, role: str) -> None:
    from lib.skills.role_skills import ROLE_SKILLS
    if role not in ROLE_SKILLS:
        raise TaskGraphError("AGY dispatch requires a role defined by the current workflow package")
    validate_child_id(parent, agent_id)
    brain = _brain()
    parent_log = brain / parent / _LOG
    child_log = brain / agent_id / _LOG
    try:
        with open_file(parent_log) as stream:
            if stream is None:
                raise TaskGraphError("AGY parent transcript is unavailable; retain the claim")
            # 读取打开瞬间的有界尾部快照，避开持续追加和巨大历史。截断处不是完整事件；
            # 只在相邻的已完成、同源事件上配对，解析异常或未知格式绝不能沿用前一步。
            size = os.fstat(stream.fileno()).st_size
            start = max(0, size - 32 * 1024 * 1024)
            stream.seek(start)
            if start:
                stream.readline(size - start)
            pending = None
            while stream.tell() < size:
                line = stream.readline(size - stream.tell())
                if not line:
                    break
                try:
                    event = json.loads(line)
                except (ValueError, RecursionError):
                    pending = None
                    continue
                if (not isinstance(event, dict) or event.get("source") != "MODEL"
                        or event.get("status") != "DONE" or type(event.get("step_index")) is not int):
                    pending = None
                    continue
                if (pending is not None and event["step_index"] == pending + 1 and event.get("type") == "GENERIC"
                        and isinstance(event.get("content"), str)
                        and _matches_receipt(event["content"], agent_id, child_log, workspace)):
                    return
                pending = _dispatch_step(event, marker, role)
    except TaskGraphError:
        raise
    except (OSError, ValueError) as exc:
        raise TaskGraphError("cannot verify the current AGY parent transcript; retain the claim") from exc
    raise TaskGraphError("no matching native invoke_subagent receipt for this AGY parent, task, role and workspace; retain the claim")
