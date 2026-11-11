#!/usr/bin/env python3
"""只向官方受信任SessionStart事件提供入口提醒，不读取任务或执行任何业务。"""

from __future__ import annotations

import json
from pathlib import Path


def main() -> int:
    """根目录来自已安装脚本物理位置，不从cwd或用户提供的路径猜测。

    Hook只输出短上下文；批准、分类、派发和QA仍由原工作流及主会话负责。
    不写trust、不访问账户/历史、不启动服务，未受宿主信任时由官方客户端跳过。
    """
    root = Path(__file__).resolve().parents[1]
    context = (
        "Apply the installed Agent Workflow xy-workflow Skill at main-session task intake. "
        f"Plugin root: {root}. Read {root / 'skills/xy-workflow/SKILL.md'} and its "
        "unchanged product authority before orchestration. The main session remains PM. "
        "This is an entry reminder only; it creates no approvals and dispatches no agents."
    )
    print(json.dumps({"hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": context}}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
