"""Replay the focus-only receipt sequence observed in Antigravity App 2.36.0."""

import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from lib.hosts import antigravity_dispatch
from lib.task_graph import TaskGraphError


class AntigravityDispatchReceiptTests(unittest.TestCase):
    def setUp(self):
        root = Path(self.enterContext(tempfile.TemporaryDirectory())).resolve()
        self.app, self.cli, self.workspace = (root / name for name in ("app", "cli", "workspace"))
        self.enterContext(mock.patch.object(antigravity_dispatch, "_brain_roots", return_value=(self.app, self.cli)))
        self.parent = "10000000-0000-4000-8000-000000000001"
        self.child = "20000000-0000-4000-8000-000000000002"
        self.marker = "XY-WORKFLOW-CLAIM " + "1" * 64
        self.role = "xy-backend"
        self.prompt = (
            f"{self.marker}\nXY-WORKFLOW-TASK-PACK-V1\n"
            "Use this complete current Task Pack as your assignment. Limit writes to its owned_paths.\n"
            '{"schema_version":2,"task":{"role":"xy-backend"}}'
        )
        self.focus = {"name": "update_focus", "args": {"focus": "派发实现任务"}}
        self.creation = {"name": "invoke_subagent", "args": {
            "Prompt": self.prompt, "Role": "Backend engineer", "TypeName": self.role,
        }}
        self.plan = {"step_index": 81, "source": "MODEL", "type": "PLANNER_RESPONSE", "status": "DONE",
                     "tool_calls": [self.focus, self.creation]}
        self.ack = self.event(82, self.timestamps("39") + "OK")

    @staticmethod
    def event(index, content):
        return {"step_index": index, "source": "MODEL", "type": "GENERIC", "status": "DONE", "content": content}

    @staticmethod
    def timestamps(second):
        return (f"Created At: 2026-11-28T16:29:{second}+08:00\n"
                "Completed At: 2026-11-28T16:29:46+08:00\n") * 2

    def receipt(self, brain):
        child_log = brain / self.child / ".system_generated/logs/transcript.jsonl"
        payload = {"conversationId": self.child, "logAbsoluteUri": child_log.as_uri(),
                   "workspaceUris": [self.workspace.as_uri()]}
        return self.event(83, self.timestamps("45") + "Created the following subagent:\n" + json.dumps(payload)
                          + "\nThe subagent will send you a message when it has completed its task or requires guidance. "
                            "There is no need to poll for its response.")

    def write(self, brain, *events):
        log = brain / self.parent / ".system_generated/logs/transcript_full.jsonl"
        log.parent.mkdir(parents=True, exist_ok=True)
        log.write_text("".join(json.dumps(event) + "\n" for event in events), encoding="utf-8")

    def verify(self, *, expected_prompt=True):
        antigravity_dispatch.verify_creation(
            self.parent, self.child, self.workspace, self.marker, self.role,
            expected_prompt=(lambda: self.prompt) if expected_prompt else None,
        )

    def test_app_focus_then_create_accepts_adjacent_ack_and_receipt(self):
        self.write(self.app, self.plan, self.ack, self.receipt(self.app))
        self.verify()
        self.verify(expected_prompt=False)  # 已绑定子会话的写保护重放原生回执。

    def test_app_focus_then_create_requires_the_native_ack_and_exact_prompt(self):
        receipt = self.receipt(self.app)
        altered_creation = {**self.creation, "args": {**self.creation["args"], "Prompt": self.prompt + "\n"}}
        altered_plan = {**self.plan, "tool_calls": [self.focus, altered_creation]}
        for case, events in {
            "wrong acknowledgement": [self.plan, {**self.ack, "content": "OK"}, receipt],
            "missing acknowledgement": [self.plan, {**receipt, "step_index": 82}],
            "different prompt": [altered_plan, self.ack, receipt],
        }.items():
            with self.subTest(case=case):
                self.write(self.app, *events)
                with self.assertRaisesRegex(TaskGraphError, "no matching native"):
                    self.verify()

    def test_cli_rejects_focus_then_create_even_when_the_ack_and_receipt_match(self):
        self.write(self.cli, self.plan, self.ack, self.receipt(self.cli))
        with self.assertRaisesRegex(TaskGraphError, "no matching native"):
            self.verify()
