"""覆盖调度容量、需求门禁和受保护源码所有权的真实行为边界。"""

from __future__ import annotations

import unittest

from lib.task_graph import Task, TaskGraphError, effective_dispatch_capacity, ready_tasks
from lib.task_graph_cli import _execute


def _writer_payload(owned_path: str = "backend/service.py") -> dict:
    """构造最小的正式 Writer 合同，避免保护路径测试被无关规范缺失遮蔽。"""

    fingerprint = "a" * 64
    rule_ids = ["eng-baseline", "eng-upstream"]
    documents = []
    for path, rules in (
        ("docs/STANDARDS.md", []),
        ("docs/standards/GENERAL.md", rule_ids),
    ):
        documents.append(
            {
                "path": path,
                "mode": "full",
                "reason": "读取此任务适用的工程规范",
                "sections_or_queries": [],
                "content_fingerprint": fingerprint,
                "applies_to": [owned_path],
                "rule_ids": rules,
            }
        )
    return {
        "standards_contract": {
            "index_path": "docs/STANDARDS.md",
            "root": "docs/standards",
            "index_fingerprint": fingerprint,
            "required_engineering_rule_ids": ["eng-baseline"],
            "required_design_rule_ids": [],
            "leaves": [
                {
                    "path": "docs/standards/GENERAL.md",
                    "domain": "engineering",
                    "content_fingerprint": fingerprint,
                    "rule_ids": rule_ids,
                }
            ],
            "protected_paths": [
                {
                    "path": "vendor/core",
                    "rule_id": "eng-upstream",
                    "direct_edit": "forbidden_without_exception",
                    "allowed_paths": ["vendor/core/extensions"],
                }
            ],
        },
        "tasks": [
            {
                "id": "backend",
                "request_id": "req-boundaries",
                "task_type": "writer",
                "role": "xy-backend",
                "surface_kind": "non_ui",
                "qa_scope": "request",
                "depends_on": [],
                "blocks": [],
                "gates": ["requirements_approved"],
                "owned_paths": [owned_path],
                "semantic_locks": [],
                "state": "DECLARED",
                "audit_surfaces": ["standards-conformance"],
                "controlled_document_access": {
                    "adapter": "project.yaml",
                    "documents": documents,
                },
            }
        ],
        "approved_gates": ["requirements_approved"],
        "active_paths": [],
        "active_semantic_locks": [],
        "capacity": 1,
    }


def _add_exception(payload: dict, patch_path: str) -> None:
    """将已批准例外明确绑定到补丁范围，测试不能扩大这份授权。"""

    gate = "exceptional:upstream-hotfix"
    task = payload["tasks"][0]
    task["gates"].append(gate)
    payload["approved_gates"].append(gate)
    task["standards_exceptions"] = [
        {
            "rule_id": "eng-upstream",
            "gate": gate,
            "reason": "实施已批准的最小上游补丁",
            "patch_surface": [patch_path],
            "rollback_plan": "移除此补丁并恢复上游版本",
            "verification_commands": ["pytest tests/test_upstream.py"],
        }
    ]


class SchedulerCapacityBoundaryTest(unittest.TestCase):
    def test_zero_capacity_returns_no_tasks(self) -> None:
        self.assertEqual(
            [],
            ready_tasks(
                [Task("backend", "req-capacity")],
                approved_gates=set(),
                active_paths=set(),
                active_semantic_locks=set(),
                capacity=0,
            ),
        )

    def test_zero_capacity_still_validates_graph_paths_and_locks(self) -> None:
        # 容量耗尽不能让损坏的输入被静默接受；下一轮容量恢复前仍应暴露合同错误。
        cases = [
            ([Task("backend", "req-capacity", depends_on=("missing",))], set(), set()),
            ([Task("backend", "req-capacity")], {"../outside"}, set()),
            ([Task("backend", "req-capacity")], set(), {"invalid lock"}),
        ]
        for tasks, active_paths, active_locks in cases:
            with self.subTest(tasks=tasks, paths=active_paths, locks=active_locks):
                with self.assertRaises(TaskGraphError):
                    ready_tasks(
                        tasks,
                        approved_gates=set(),
                        active_paths=active_paths,
                        active_semantic_locks=active_locks,
                        capacity=0,
                    )

    def test_exhausted_host_or_writer_slots_stay_empty_through_cli(self) -> None:
        for host_slots, active_writers in ((0, 0), (3, 2)):
            with self.subTest(host_slots=host_slots, active_writers=active_writers):
                payload = _writer_payload()
                payload["capacity"] = effective_dispatch_capacity(
                    configured_subagents=3,
                    configured_writers=2,
                    host_available_subagents=host_slots,
                    active_subagents=0,
                    active_writers=active_writers,
                )
                self.assertEqual(0, payload["capacity"])
                self.assertEqual({"ready": []}, _execute("ready", payload))


class ProtectedOwnershipBoundaryTest(unittest.TestCase):
    def test_parent_ownership_cannot_bypass_protection(self) -> None:
        with self.assertRaisesRegex(TaskGraphError, "writes protected path"):
            _execute("validate", _writer_payload("vendor"))

    def test_parent_ownership_cannot_expand_a_small_exception(self) -> None:
        payload = _writer_payload("vendor")
        _add_exception(payload, "vendor/core/service.py")
        with self.assertRaisesRegex(TaskGraphError, "does not cover protected path"):
            _execute("validate", payload)

    def test_parent_ownership_accepts_full_protected_intersection_exception(self) -> None:
        payload = _writer_payload("vendor")
        _add_exception(payload, "vendor/core")
        self.assertEqual({"ready": ["backend"]}, _execute("ready", payload))

    def test_only_explicitly_allowed_subtree_is_exempt(self) -> None:
        for path in ("vendor/core/extensions", "vendor/core/extensions/plugin.py"):
            with self.subTest(path=path):
                self.assertEqual(
                    {"status": "valid"}, _execute("validate", _writer_payload(path))
                )
        for path in ("vendor/core", "vendor/core/extensions-private/plugin.py"):
            with self.subTest(path=path):
                with self.assertRaisesRegex(TaskGraphError, "writes protected path"):
                    _execute("validate", _writer_payload(path))

    def test_fully_allowed_protected_root_does_not_block_parent_ownership(self) -> None:
        payload = _writer_payload("vendor")
        payload["standards_contract"]["protected_paths"][0]["allowed_paths"] = [
            "vendor/core"
        ]
        self.assertEqual({"status": "valid"}, _execute("validate", payload))

    def test_similarly_named_sibling_is_not_protected(self) -> None:
        self.assertEqual(
            {"status": "valid"}, _execute("validate", _writer_payload("vendor/core-extra"))
        )

    def test_exact_patch_requires_its_approval_and_does_not_escape_ownership(self) -> None:
        payload = _writer_payload("vendor/core/service.py")
        _add_exception(payload, "vendor/core/service.py")
        self.assertEqual({"ready": ["backend"]}, _execute("ready", payload))
        payload["approved_gates"] = ["requirements_approved"]
        self.assertEqual({"ready": []}, _execute("ready", payload))
        payload["tasks"][0]["standards_exceptions"][0]["patch_surface"] = ["vendor"]
        with self.assertRaisesRegex(TaskGraphError, "must stay within task owned_paths"):
            _execute("validate", payload)


class ScheduledWriterRequirementsTest(unittest.TestCase):
    def test_non_ui_writer_must_declare_requirements_gate(self) -> None:
        payload = _writer_payload()
        payload["tasks"][0]["gates"] = []
        # 已存在全局批准也不能替代任务的依赖声明，否则门禁撤回后仍可继续派发。
        for approved in ([], ["requirements_approved"]):
            payload["approved_gates"] = approved
            with self.subTest(approved=approved):
                with self.assertRaisesRegex(TaskGraphError, "requires requirements_approved"):
                    _execute("ready", payload)

    def test_non_ui_writer_waits_until_requirements_are_approved(self) -> None:
        payload = _writer_payload()
        payload["approved_gates"] = []
        self.assertEqual({"ready": []}, _execute("ready", payload))
        payload["approved_gates"] = ["requirements_approved"]
        self.assertEqual({"ready": ["backend"]}, _execute("ready", payload))

    def test_read_only_and_qa_tasks_do_not_gain_a_requirements_gate(self) -> None:
        for task_type, role in (("read_only", "xy-backend"), ("qa", "xy-qa")):
            with self.subTest(task_type=task_type):
                payload = _writer_payload()
                payload.pop("standards_contract")
                task = payload["tasks"][0]
                task.update(task_type=task_type, role=role, gates=[], owned_paths=[])
                task.pop("controlled_document_access")
                payload["approved_gates"] = []
                self.assertEqual({"status": "valid"}, _execute("validate", payload))
                expected_ready = ["backend"] if task_type == "read_only" else []
                self.assertEqual({"ready": expected_ready}, _execute("ready", payload))


if __name__ == "__main__":
    unittest.main()
