"""从 AGY 主会话的本机原生记录核对本次领取对应的创建回执。"""

from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import re
import secrets

from lib import plugin_resources
from lib.hosts.dispatch_contract import (
    AGY_CONVERSATION_UUID, AGY_PARENT_ERROR, AGY_RELEASE_ERROR, DispatchPolicy, reject_unexpected_marker,
    validate_child_id,
)
from lib.safe_text import open_file, read_file
from lib.task_graph import TaskGraphError


# 1.5.13 的回执没有可跨并行工具定位的 call ID，只认单一调用、紧邻且连续的结果。
# Created/Completed 是宿主附加的时间行；命令输出和聊天的相同文字不能作为回执。
_MARKER = "XY-WORKFLOW-CLAIM "
_RECEIPT_HEADER = re.compile(r"(?:(?:Created|Completed) At: [0-9T:+.Z-]+\n)*Created the following subagent:\n")
_RECEIPT_FOOTER = ("\nThe subagent will send you a message when it has completed its task or requires guidance. "
                   "There is no need to poll for its response.")
_LOG = Path(".system_generated/logs/transcript.jsonl")
_FULL_LOG = _LOG.with_name("transcript_full.jsonl")


def parent_id(pm_id: str) -> str:
    host, _, parent = pm_id.partition(":")
    if host != "antigravity" or not AGY_CONVERSATION_UUID.fullmatch(parent):
        raise TaskGraphError(AGY_PARENT_ERROR)
    return parent


def new_claim(pm_id: str) -> dict:
    # 即使同一份输入被恢复，同一任务在确认未创建后重新领取也必须获得新的派发标记。
    return {"parent": parent_id(pm_id), "nonce": secrets.token_hex(32)}


def dispatch_marker(root: Path, target: dict, basis: str, claim: dict) -> str:
    # 原件路径独立参与指纹，防止复制已领取的图后用另一路径借用同一个创建事件。
    body = json.dumps([str(root), target, basis, claim], ensure_ascii=False, sort_keys=True,
                      separators=(",", ":")).encode("utf-8")
    return _MARKER + hashlib.sha256(body).hexdigest()


def _brain() -> Path:
    # shell 可以重设 HOME；用户可写项目及调用者提供的 HOME 不能取得宿主日志权威。
    # 当前核实的是使用系统账户目录的 POSIX AGY CLI；别的平台缺少证据时保留占用。
    if os.name != "posix":
        raise TaskGraphError("AGY native transcript location is unverified on this platform")
    import pwd
    return Path(pwd.getpwuid(os.getuid()).pw_dir) / ".gemini/antigravity-cli/brain"


def session_origin(event):
    """身份只读宿主指定会话的首条原生事件，首条工具输出或普通聊天均不能充当派发。"""
    current = event["conversationId"]
    parent_id("antigravity:" + current)
    directory = _brain() / current
    path = Path(event["transcriptPath"])
    if path not in (directory / _FULL_LOG, directory / _LOG):
        raise ValueError("缺少当前 AGY CLI 会话来源")
    with open_file(path) as stream:
        if stream is None:
            raise ValueError("宿主尚未写入会话来源")
        first = json.loads(stream.readline(8 * 1024 * 1024))
    if first.get("step_index") != 0 or first.get("status") != "DONE":
        raise ValueError("缺少原生首条消息")
    if (first.get("type"), first.get("source")) == ("USER_INPUT", "USER_EXPLICIT"):
        return current, None, None
    if (first.get("type"), first.get("source")) != ("SYSTEM_MESSAGE", "SYSTEM"):
        raise ValueError("无法识别原生派发身份")
    header = re.search(r"\n<SYSTEM_MESSAGE>\n\[Message\] timestamp=\S+ sender=(\S+) priority=\S+ content=", first["content"])
    if not header:
        raise ValueError("缺少原生派发来源")
    parent = parent_id("antigravity:" + header[1])
    validate_child_id(parent, current)
    lines = first["content"][header.end():].splitlines()
    markers = [line for line in lines if line.startswith(_MARKER)]
    return current, parent, markers[0] if len(markers) == 1 else None


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


def _field_complete(event: dict, required: str) -> bool:
    # 宿主会在短日志和完整日志中声明截断。缺省表示未声明；畸形列表或
    # 被核验字段及其子路径的截断均不能凭可见前缀补足原生证据。
    fields = event.get("truncated_fields", [])
    return isinstance(fields, list) and all(
        isinstance(field, str) and field and field.strip() == field and not field.startswith(required) for field in fields
    )


def _dispatch_step(event: dict, marker: str, role: str, *, full: bool) -> int | None:
    calls = event.get("tool_calls")
    if (event.get("type") != "PLANNER_RESPONSE" or not isinstance(calls, list)
            or len(calls) != 1 or not isinstance(calls[0], dict) or calls[0].get("name") != "invoke_subagent"):
        return None
    args = calls[0].get("args")
    if not isinstance(args, dict) or not all(isinstance(args.get(key), str) for key in ("Prompt", "TypeName")):
        return None
    # 短日志通常自报截断；即使完整日志也明示工具调用被裁切，一条可见标记
    # 仍不能证明原提示词只有这一条。两种来源都只能核验未被裁切的调用。
    if not _field_complete(event, "tool_calls"):
        return None
    prompt, selector = args["Prompt"], args["TypeName"]
    if not full:
        # 1.5.13 短日志给参数额外加了一层 JSON 字符串编码。
        try:
            prompt, selector = json.loads(prompt), json.loads(selector)
        except (ValueError, RecursionError):
            return None
    # 完整日志的参数是直接字符串。两个来源各按自己的格式读，禁止混用或猜测解码。
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


@contextmanager
def _parent_transcript(directory: Path):
    # 完整日志一旦存在就是本次证据的唯一来源。权限错误、坏节点、坏日志或未匹配
    # 仍应保留领取；只有安全读取器确认完整日志缺失才允许读历史短日志。
    with open_file(directory / _FULL_LOG) as stream:
        if stream is not None:
            yield stream, True
            return
    with open_file(directory / _LOG) as stream:
        yield stream, False


def verify_creation(parent: str, agent_id: str, workspace: Path, marker: str, role: str) -> None:
    from lib.skills.role_skills import ROLE_SKILLS
    if role not in ROLE_SKILLS:
        raise TaskGraphError("AGY dispatch requires a role defined by the current workflow package")
    validate_child_id(parent, agent_id)
    brain = _brain()
    # 即使父会话证据来自完整日志，宿主回执内的子会话 URI 仍指向短日志。
    child_log = brain / agent_id / _LOG
    try:
        with _parent_transcript(brain / parent) as (stream, full):
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
                        and isinstance(event.get("content"), str) and _field_complete(event, "content")
                        and _matches_receipt(event["content"], agent_id, child_log, workspace)):
                    return
                pending = _dispatch_step(event, marker, role, full=full)
    except TaskGraphError:
        raise
    except (OSError, ValueError) as exc:
        raise TaskGraphError("cannot verify the current AGY parent transcript; retain the claim") from exc
    raise TaskGraphError("no matching native invoke_subagent receipt for this AGY parent, task, role and workspace; retain the claim")


class AntigravityDispatch(DispatchPolicy):
    """从当前 PM 身份和 AGY 本机日志校验派发，只向调用方返回证据或明确拒绝。"""

    native_required = True

    def __init__(self, pm_id: str | None):
        self.pm_id = pm_id

    def check_pool_claim(self) -> None:
        if self.pm_id is None:
            raise TaskGraphError("AGY dispatch requires a claim through the current PM task pool")
        parent_id(self.pm_id)

    def claim_fields(self, root: Path, target: dict, basis: str) -> tuple[dict, dict]:
        self.check_pool_claim()
        claim = new_claim(self.pm_id)
        return {"antigravity_claim": claim}, {"dispatch_marker": dispatch_marker(root, target, basis, claim)}

    def check_release(self, root: Path, target: dict, task: dict, receipt: dict) -> bool:
        reject_unexpected_marker(task, receipt)
        claim = task.get("antigravity_claim")
        if claim is None:
            return False
        # 同一任务重新领取也会生成新 nonce。旧回执、其他 PM 和直接准入入口都不能释放名额。
        if (self.pm_id is None or parent_id(self.pm_id) != claim["parent"]
                or receipt.get("dispatch_marker") != dispatch_marker(root, target, task["claim_basis_sha256"], claim)):
            raise TaskGraphError(AGY_RELEASE_ERROR)
        return True

    def check_binding(self, root, target, task, receipt, reference, execution_root) -> None:
        parent = parent_id(self.pm_id or "")
        claim = task.get("antigravity_claim")
        if reference["host"] != "antigravity" or not claim or claim["parent"] != parent:
            raise TaskGraphError("AGY binding requires this parent's original AGY pool claim and host")
        marker = dispatch_marker(root, target, task["claim_basis_sha256"], claim)
        if receipt.get("dispatch_marker") != marker:
            raise TaskGraphError("AGY binding requires this task's original dispatch marker")
        if "agent_ref" not in task:
            # 首次绑定才读创建日志；同一轮已绑定 ID 的重试仍核对 PM、原件和标记，
            # 日志归档后也能幂等返回。最终原件 CAS 仍由外层任务池执行。
            verify_creation(parent, reference["agent_id"], execution_root(), marker, task["role"])
