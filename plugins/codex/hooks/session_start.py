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
    # SessionStart 不能证明当前用户调用了哪个 Skill，故这里只载入主会话分支规则，
    # 不解析 stdin 中的历史或任意文本，更不会提前读取业务权威、启动维护或创建任务。
    # 主会话在实际任务进入时依据宿主当前用户的显式调用证据选择对应分支。
    context = (f"插件物理根：{root}。业务分支的工作流路径：{root / 'skills/xy-workflow/SKILL.md'}。\n\n"
               + (root / "main-session-context.md").read_text(encoding="utf-8"))
    print(json.dumps({"hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": context}}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
