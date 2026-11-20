#!/usr/bin/env python3
"""只读续用查询入口：复用原记录校验，并显式接收动作意图和当前工具能力。"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

try:
    from .agent_continuation import CAPABILITIES, HOSTS, INTENTS, OBSERVED_STATES, continuation
    from . import task_graph_cli as records
    from .task_graph_records import decode, read_record
except ImportError:
    from agent_continuation import CAPABILITIES, HOSTS, INTENTS, OBSERVED_STATES, continuation
    import task_graph_cli as records
    from task_graph_records import decode, read_record


def main() -> int:
    """只适配命令行，不复制任务 schema、pin 或安全读取规则，也不保存能力声明。

    原任务图入口为受保护文件，因此在此窄适配中调用其已有读取/完整校验函数；
    所有 graph 与 Light 单包、中央 pin 冲突和 4MiB 限制沿用同一权威实现。
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--task-id", required=True)
    parser.add_argument("--host", choices=HOSTS, required=True)
    parser.add_argument("--observed-state", choices=OBSERVED_STATES, required=True)
    parser.add_argument("--claude-event", type=Path, help="当前终止通知对应的同 ID 单条原生 JSON 事件")
    parser.add_argument("--intent", choices=INTENTS, default="observe")
    parser.add_argument("--capability", choices=CAPABILITIES, action="append", default=[])
    args = parser.parse_args()
    try:
        if args.claude_event and args.host != "claude":
            raise records.TaskGraphError("--claude-event applies only to Claude continuation")
        payload = decode(read_record(args.input))
        if not isinstance(payload, dict):
            raise records.TaskGraphError("task record must be a JSON object")
        records._execute("validate", payload)
        # 无执行节点的讨论范围可以与原请求一起恢复。空图确实没有可续用的实例。
        tasks = [payload["task"]] if "task" in payload else payload["tasks"]
        selected = next((task for task in tasks if task["id"] == args.task_id), None)
        if selected is None:
            raise records.TaskGraphError("unknown task ID")
        result = continuation(selected, args.host, args.observed_state,
                              intent=args.intent, capabilities=args.capability,
                              claude_event=records.read_claude_event(args.claude_event))
    except (records.TaskGraphError, records.WorktreePolicyError, OSError, UnicodeError, ValueError) as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2
    # 拒绝续用也是合法查询结果；exit 2 专用于无效输入，不把被阻止误报为执行失败。
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
