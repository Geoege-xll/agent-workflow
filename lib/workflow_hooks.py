#!/usr/bin/env python3
"""三宿主的辅助 Hook：有限提醒、入口只读检查，不作批准或执行决策。"""

from __future__ import annotations

# 直接脚本只信任自身物理位置确定的核心根，避免异 cwd 或 PYTHONPATH 中的
# 同名模块劫持内部依赖；正常包导入沿用调用方已选择的固定核心。
if not __package__:
    import sys as _sys
    from pathlib import Path as _Path
    _sys.path.insert(0, str(_Path(__file__).resolve().parents[1]))

import argparse
import json
import math
import time
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
    from lib.hosts.workflow_hook_settings import hook_mode
else:
    from lib.hosts.workflow_hook_settings import hook_mode

OWNER = "agent-workflow-assist-v1"
# 提醒先指向已有的独立只读审计分支，避免把查问题误当成实施任务；
# 仅实施适用 Light/Full 与默认委派，脚本仍不推导授权或替代验证与 QA。
ENTRY = (
    "Workflow assist reminder: reuse valid approvals and evidence for work already completed in this session. "
    "First apply xy-workflow's Standalone read-only audit branch for findings-only requests; keep explicit user opt-outs within existing boundaries. "
    "Light/Full implementation activates xy-workflow with delegation by default, except when the user explicitly asks PM to implement personally. "
    "Light requires minimum verification and QA/documentation assessment at handoff, without mandatory Full planning/DAG; Full gates remain. "
    "New tasks use new native IDs and only self-contained current task packs, without copied PM/sibling history. "
    "Read required standards completely as needed, preserve choices such as no prototype update, and add no extra stages or records."
)
# 恢复摘要只能帮助定位上下文，不能代替原始授权、改变等级或批准 PM 接管。
RECOVERY = (
    "Workflow recovery reminder: first apply xy-workflow's Standalone read-only audit branch for findings-only requests; "
    "for implementation, check task level and personal-implementation authority against trusted original instructions and existing plans; "
    "continue the current task with valid evidence without repeating completed related work. "
    "Light/Full implementation uses delegation by default and PM personal implementation only by explicit user instruction; Light requires minimum verification "
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


def hook_deadline() -> float:
    """监督者传来的绝对预算只读消费；未监督的 POSIX Hook 沿用原 3 秒上限。"""
    value = os.environ.get("AGENT_WORKFLOW_HOOK_DEADLINE")
    deadline = time.monotonic() + 3 if value is None else float(value)
    if not math.isfinite(deadline) or deadline <= time.monotonic():
        raise ValueError("expired or invalid Hook deadline")
    return deadline


def common_git(root: Path, deadline: float | None = None) -> str:
    """只为跨目录的 worktree 验证 Git 共同仓库；不扫描 diff 或业务文件。"""
    from lib.install.install_process import capture_process
    deadline = hook_deadline() if deadline is None else deadline

    def git(*arguments):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise subprocess.TimeoutExpired("git", 0)
        result = capture_process(["git", "-C", str(root), *arguments], timeout=min(0.7, remaining))
        # Windows 本地代码页不能决定 Git 路径字符；错误解码进入中性响应。
        return result.returncode, result.stdout.decode("utf-8", "strict").strip()

    code, common = git(
        "rev-parse", "--path-format=absolute", "--git-common-dir",
    )
    if code != 0:
        return ""
    code, top = git("rev-parse", "--show-toplevel")
    if code != 0 or Path(top).resolve() != root:
        return ""
    return common


def scoped_root(host: str, payload: dict, installed: Path, *, deadline: float | None = None) -> Path | None:
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
        deadline = hook_deadline() if deadline is None else deadline
        own = common_git(installed, deadline)
        if not own or own != common_git(root, deadline):
            return None
    return root


def response(host: str, event: str, payload: dict, project: Path) -> dict:
    """事件输出严格按宿主协议构造；没有 deny/allow、force_continue 或伪造用户消息。"""
    if os.environ.get("AGENT_WORKFLOW_HOOKS") == "off":
        return {}
    deadline = hook_deadline()
    root = scoped_root(host, payload, project, deadline=deadline)
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


def _command_parser() -> argparse.ArgumentParser:
    class HookParser(argparse.ArgumentParser):
        def error(self, message):
            # 参数可能含私有项目名；只报告稳定类别，不回显 argparse 原文。
            raise ValueError("Hook 参数无效")
    # 数据返回入口不能让--help先向stdout打印；独立main仍显式保留帮助入口。
    parser = HookParser(description=__doc__, add_help=False)
    parser.add_argument("--host", choices=("codex", "claude", "antigravity"), required=True)
    parser.add_argument("--event", required=True)
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--owner", choices=(OWNER,), required=True)
    parser.add_argument("--signature", required=True)
    return parser


def command_response(arguments, payload: bytes, *, project: Path | None = None) -> dict:
    """解析一次有限 Hook 请求并返回数据；打印由最外层安全读取边界负责。

    中央薄桥必须在核心会话结束重验之后才能发布提醒，因此这里不能打印、
    再启动helper或自行选择另一核心；既有worktree的有限只读Git检查仍保留。
    project 是桥已核验的物理根，只作一致性
    守卫，不能由事件 payload 或命令参数替换。普通独立脚本仍沿原 main 入口。
    """
    parser = _command_parser()
    args = parser.parse_args(arguments)
    if project is not None and args.project != project:
        raise ValueError("Hook 项目根与固定桥不一致")
    if not isinstance(payload, bytes) or len(payload) > 1024 * 1024:
        raise ValueError("oversized or invalid payload")
    decoded = json.loads(payload)
    if not isinstance(decoded, dict):
        raise ValueError("payload must be an object")
    return response(args.host, args.event, decoded, project if project is not None else args.project)


def main() -> int:
    if sys.argv[1:] in (["-h"], ["--help"]):
        _command_parser().print_help()
        return 0
    try:
        raw = sys.stdin.buffer.read(1024 * 1024 + 1)
        result = command_response(sys.argv[1:], raw)
    except (OSError, ValueError, UnicodeError, RecursionError, subprocess.SubprocessError):
        # 辅助层失败保持中性，不能让脚本/配置故障改变用户权限或冻结会话。
        # stderr 不输出原始 payload、路径或日志，避免泄露提示词和敏感内容。
        print("[workflow hooks] 辅助提醒暂不可用；原有工作流与宿主权限保持不变。", file=sys.stderr)
        result = {}
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
