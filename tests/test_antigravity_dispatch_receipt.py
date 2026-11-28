"""Replay the focus-only receipt sequence observed in Antigravity App 2.36.0."""

import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from lib.hosts import antigravity_dispatch
from lib.task_graph import TaskGraphError
from tests.test_task_graph_records import graph


class AntigravityDispatchReceiptTests(unittest.TestCase):
    def setUp(self):
        root = Path(self.enterContext(tempfile.TemporaryDirectory())).resolve()
        self.app, self.cli, self.workspace = (root / name for name in ("app", "cli", "workspace"))
        self.enterContext(mock.patch.object(antigravity_dispatch, "_brain_roots", return_value=(self.app, self.cli)))
        self.parent = "10000000-0000-4000-8000-000000000001"
        self.child = "20000000-0000-4000-8000-000000000002"
        self.workspace.mkdir()
        self.pm_id = "antigravity:" + self.parent
        self.policy = antigravity_dispatch.AntigravityDispatch(self.pm_id)
        self.record = self.workspace / "graph.json"
        self.graph = graph()
        self.task = self.graph["tasks"][0]
        self.task["state"] = "RUNNING"
        self.role = self.task["role"]
        self.target = {"record": str(self.record), "request_id": self.task["request_id"], "task_id": self.task["id"]}
        basis = "1" * 64
        claim, self.claim_receipt = self.policy.claim_fields(self.workspace, self.target, basis)
        self.task.update(claim, claim_basis_sha256=basis, claim_prior_state="READY")
        self.record.write_text(json.dumps(self.graph), encoding="utf-8")
        self.marker = self.claim_receipt["dispatch_marker"]
        self.prompt = antigravity_dispatch.initial_prompt(self.workspace, self.target, self.marker)
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
            expected_prompt=(lambda: self.prompt) if expected_prompt else None, expected_task=self.target,
        )

    def check_binding(self, task, prompt):
        create = {**self.creation, "args": {**self.creation["args"], "Prompt": prompt}}
        self.write(self.app, {**self.plan, "tool_calls": [self.focus, create]}, self.ack, self.receipt(self.app))
        self.policy.check_binding(
            self.workspace, self.target, task, self.claim_receipt,
            {"host": "antigravity", "agent_id": self.child}, lambda: self.workspace,
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

    def test_binding_a_revised_withdrawal_requires_the_original_pack_identity(self):
        header, data = self.prompt.rsplit("\n", 1)
        original = json.loads(data)
        stopped = {**self.task, "state": "STOP_REQUESTED", "goal": "Revised scope",
                   "task_revision": 1, "revision_source": "user:revision"}
        self.graph["tasks"] = [stopped]
        self.record.write_text(json.dumps(self.graph), encoding="utf-8")
        self.check_binding(stopped, self.prompt)
        for field in ("id", "request_id", "role"):
            with self.subTest(field=field), self.assertRaisesRegex(TaskGraphError, "no matching native"):
                candidate = {**original, "task": {**original["task"], field: "different"}}
                body = json.dumps(candidate, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
                self.check_binding(stopped, f"{header}\n{body}")
        with self.assertRaisesRegex(TaskGraphError, "no matching native"):
            self.check_binding(stopped, header + "\n{")
