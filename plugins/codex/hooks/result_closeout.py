"""Remind the current Codex PM to reconcile its registered result tasks before stopping."""

from __future__ import annotations

import json
import os
from pathlib import Path
import shlex
import sys


# 与其他宿主 Hook 一样，从脚本自身的物理安装根加载共用代码。命令使用 -I，
# 避免宿主 cwd 或 PYTHONPATH 中的同名模块改变任务查询的来源。
PLUGIN = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PLUGIN))

from lib import task_graph_records as records, task_pool
from lib.agent_continuation import validate_reference
from lib.dispatch_admission_cli import _project_directory, _same_directory
from lib.plugin_resources import PLUGIN_ENV
from lib.task_graph import TaskGraphError


MAX_EVENT_BYTES = 4 * 1024 * 1024
POOL_UNAVAILABLE = ("xy-workflow could not verify this Codex session’s registered task pool. "
                    "Check the original pool and keep unresolved task occupancy.")


def continuation(root: Path, pm_id: str) -> dict:
    pool_view = shlex.join([
        "bash", str(PLUGIN / "lib/python_runtime.sh"), "-B", "-X", "utf8",
        str(PLUGIN / "plugins/source_pack.py"), "helper", "--project", str(root),
        "lib/task_pool_cli.py", "view", "--root", str(root), "--pm-id", pm_id,
    ])
    return {
        "decision": "block",
        "reason": (
            "xy-workflow Codex result closeout. Continue the current PM turn within existing user instructions. "
            f"Read the current registered tasks and record digests using `{pool_view}`. "
            "Use the available native wait/status tools or an actual native completion result for the original "
            "bound IDs of active read_only/evidence tasks. Keep coordinating with the native wait tool if the "
            "original worker is still running and waiting is authorized. Stop itself supplies no completion evidence. "
            "Check the latest complete Task Pack actually delivered and accepted, any required revision acknowledgement, "
            "the matching native completion, and the actual current-scope result and required verification evidence. "
            "Use the existing lib/task_graph_cli.py update with exclusive settle and the current record SHA only "
            "after those checks pass. Preserve occupancy for any unconfirmed result. "
            "After valid settlement refresh task-pool admission with actual capacity and use normal claim, export, "
            "spawn and bind for already approved READY work when eligible. Apply the existing Writer and independent "
            "QA gates. Respect any pause, withdrawal, or stop request. Report any remaining blocker with the "
            "original record intact."
        ),
    }


def reconcile(event: object) -> dict:
    if (not isinstance(event, dict) or event.get("hook_event_name") != "Stop"
            or event.get("stop_hook_active") is not False
            or any(event.get(field) is not None for field in ("agent_id", "agent_type", "agent_transcript_path"))):
        return {}

    session = event.get("session_id")
    for field in ("session_id", "turn_id"):
        validate_reference({"host": "codex", "agent_id": event.get(field)}, field)
    pm_id = "codex:" + session
    root = _project_directory(event.get("cwd"))
    if not _same_directory(root, Path.cwd()):
        raise TaskGraphError("Stop cwd is not the current physical workspace")

    os.environ.setdefault(PLUGIN_ENV, str(PLUGIN))
    for snapshot in task_pool.registered_tasks(root, pm_id):
        task = snapshot.task
        ref = task.get("agent_ref")
        # RUNNING 仍可能只是历史登记或尚未收尾。这里只决定是否提醒 PM 核对，
        # 不读取聊天历史、不推定最新修订已交付，也不消费任何子代理文本。
        if (task["task_type"] in {"read_only", "evidence"} and task["state"] == "RUNNING"
                and not task.get("withdrawal") and not task.get("agent_retired")
                and ref and ref["host"] == "codex" and ref["agent_id"] != session):
            return continuation(root, pm_id)
    return {}


def main() -> int:
    try:
        body = sys.stdin.buffer.read(MAX_EVENT_BYTES + 1)
        if len(body) > MAX_EVENT_BYTES:
            raise ValueError("Stop event exceeds the input limit")
        output = reconcile(records.decode(body))
    except (ValueError, OSError, RecursionError):
        # Codex 显示信号但允许该轮结束。底层报错可能含私有记录路径或模型文本。
        output = {"systemMessage": POOL_UNAVAILABLE}
    print(json.dumps(output, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
