#!/usr/bin/env python3
"""三宿主的辅助 Hook：有限提醒、入口只读检查，不作批准或执行决策。"""

from __future__ import annotations

import argparse
import json
if __package__:
    from .platform_fs import os
else:
    from platform_fs import os
from pathlib import Path
import stat
import subprocess
import sys

sys.dont_write_bytecode = True
if __package__:
    from .workflow_hook_settings import hook_mode
else:
    from workflow_hook_settings import hook_mode

OWNER = "agent-workflow-assist-v1"
# 提醒只陈述分级和授权边界；脚本不能推导用户授权，也不能代替原等级的验证与 QA。
ENTRY = (
    "Workflow assist reminder: reuse valid approvals and evidence for work already completed in this session. "
    "Keep read-only discussion and explicit user opt-outs within existing boundaries. "
    "Only Light/Full; activate xy-workflow with delegation by default, except when the user explicitly asks PM to implement personally. "
    "Light requires minimum verification and QA/documentation assessment at handoff, without mandatory Full planning/DAG; Full gates remain. "
    "New tasks use new native IDs and only self-contained current task packs, without copied PM/sibling history. "
    "Read required standards completely as needed, preserve choices such as no prototype update, and add no extra stages or records."
)
# 恢复摘要只能帮助定位上下文，不能代替原始授权、改变等级或批准 PM 接管。
RECOVERY = (
    "Workflow recovery reminder: check task level and personal-implementation authority against trusted original instructions and existing plans; "
    "continue the current task with valid evidence without repeating completed related work. "
    "Only Light/Full, with delegation by default and PM personal implementation only by explicit user instruction; Light requires minimum verification "
    "and QA/documentation assessment at handoff, while Full gates remain. Reuse original IDs only for continuous same-task work or short rework; retirement prohibits reuse. "
    "New independent tasks never inherit complete PM/sibling history; resume/compact does not reset context. Summaries/old state create no exceptions. "
    "Restore only missing or changed relevant rules/plans, while still reading selected Skills' mandatory content completely."
)
DISPATCH = (
    "Dispatch assist reminder: ask the original working Agent for ordinary progress questions and wait for a brief report; do not create another Explore/supervisory Agent "
    "or inspect private history for progress. Specific checks explicitly requested by the user may be inspected within the authorized scope."
)


def read_small(path: Path, limit: int = 65536) -> str:
    """读取小型受管入口而非会话日志；拒绝链接、特殊节点和异常大文件。"""
    for parent in path.parents:
        if parent.is_symlink():
            raise ValueError("linked parent")
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
                         | getattr(os, "O_NONBLOCK", 0))
    with os.fdopen(descriptor, "rb") as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise ValueError("not a single-link regular file")
        body = stream.read(limit + 1)
    if len(body) > limit:
        raise ValueError("oversized hook input file")
    return body.decode("utf-8")


def common_git(root: Path) -> str:
    """只为跨目录的 worktree 验证 Git 共同仓库；不扫描 diff 或业务文件。"""
    result = subprocess.run(
        ["git", "-C", str(root), "rev-parse", "--path-format=absolute", "--git-common-dir"],
        capture_output=True, text=True, timeout=0.7, check=False,
    )
    if result.returncode != 0:
        return ""
    top = subprocess.run(["git", "-C", str(root), "rev-parse", "--show-toplevel"],
                         capture_output=True, text=True, timeout=0.7, check=False)
    if top.returncode != 0 or Path(top.stdout.strip()).resolve() != root:
        return ""
    return result.stdout.strip()


def scoped_root(host: str, payload: dict, installed: Path) -> Path | None:
    """绑定实际工作区；不把其他项目或多工作区的会话当成本项目任务。"""
    if host == "antigravity":
        paths = payload.get("workspacePaths")
        if not isinstance(paths, list) or len(paths) != 1:
            return None
        raw = paths[0]
    else:
        raw = payload.get("cwd")
    if not isinstance(raw, str) or not Path(raw).is_absolute():
        return None
    current = Path(raw).resolve(strict=True)
    installed = installed.resolve(strict=True)
    # 从子目录启动也只使用最近的项目入口，遇到嵌套项目不向外借用审批或规则。
    root = next((node for node in (current, *current.parents)
                 if (node / "AGENTS.md").is_file()), None)
    if root is None:
        return None
    if root != installed:
        own = common_git(installed)
        if not own or own != common_git(root):
            return None
    return root


def response(host: str, event: str, payload: dict, project: Path) -> dict:
    """事件输出严格按宿主协议构造；没有 deny/allow、force_continue 或伪造用户消息。"""
    if os.environ.get("AGENT_WORKFLOW_HOOKS") == "off":
        return {}
    root = scoped_root(host, payload, project)
    if root is None:
        return {}
    # 实际已安装的项目配置优先；worktree 未复制运行时时沿用原安装点的同仓库配置。
    # 不读取另外一个项目的适配器。脚本自身所在包兼容各安装器的临时 staging 路径。
    config = root / ".agent-workflow/project.yaml"
    if not config.exists():
        config = Path(__file__).resolve().parent.parent / "project.yaml"
    if hook_mode(read_small(config)) == "off":
        return {}
    if host == "antigravity":
        # 由宿主的 SessionStart 保证新会话只调用一次；不再猜调用序号或写临时去重文件。
        # 用户消息、转录路径等输入不进入输出，也不把会话启动解释成需求确认或压缩恢复。
        session = payload.get("conversationId")
        if event != "SessionStart" or not isinstance(session, str) or not session or len(session) > 256:
            return {}
        return {"injectSteps": [{"ephemeralMessage": ENTRY}]}
    if payload.get("hook_event_name") != event:
        return {}
    message = ""
    if event == "UserPromptSubmit":
        message = ENTRY
    elif event == "SessionStart":
        source = payload.get("source")
        if source in {"resume", "compact", "clear"} or (host == "codex" and source == "fork"):
            message = RECOVERY
        # 入口检查只证明导航资源就绪，不把它误报为任务遵循证明或 QA PASS。
        skill_root = ".claude" if host == "claude" else ".agents"
        skill = root / skill_root / "skills/xy-workflow/SKILL.md"
        if not skill.is_file() or skill.is_symlink():
            message += " Workflow entry resources are missing or linked; check installation without manufacturing approval or QA PASS from this result."
    elif host == "claude" and event == "PreToolUse" and payload.get("tool_name") == "Agent":
        tool_input = payload.get("tool_input")
        # 仅已发生的 Explore 派发获得条件提醒，不分析/保存用户提示词，也不阻塞原生探索。
        if isinstance(tool_input, dict) and tool_input.get("subagent_type") == "Explore":
            message = DISPATCH
    if not message:
        return {}
    return {"hookSpecificOutput": {"hookEventName": event, "additionalContext": message}}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", choices=("codex", "claude", "antigravity"), required=True)
    parser.add_argument("--event", required=True)
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--owner", choices=(OWNER,), required=True)
    parser.add_argument("--signature", required=True)
    args = parser.parse_args()
    try:
        raw = sys.stdin.buffer.read(1024 * 1024 + 1)
        if len(raw) > 1024 * 1024:
            raise ValueError("oversized payload")
        payload = json.loads(raw)
        if not isinstance(payload, dict):
            raise ValueError("payload must be an object")
        result = response(args.host, args.event, payload, args.project)
    except (OSError, ValueError, UnicodeError, subprocess.SubprocessError):
        # 辅助层失败保持中性，不能让脚本/配置故障改变用户权限或冻结会话。
        # stderr 不输出原始 payload、路径或日志，避免泄露提示词和敏感内容。
        print("[workflow hooks] 辅助提醒暂不可用；原有工作流与宿主权限保持不变。", file=sys.stderr)
        result = {}
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
