from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from lib.task_graph import (
    Task,
    TaskGraphError,
    downstream_tasks,
    effective_dispatch_capacity,
    qa_ready,
    ready_tasks,
    request_closure,
    validate_graph,
)


def _standards_payload(payload: dict[str, object]) -> dict[str, object]:
    """把本文件原有的单文件夹具投影为新的 STANDARDS 目录合同。

    这个辅助函数只服务于测试数据迁移，不存在于生产路径。它保留每个测试故意制造
    的缺失、跳过、错误路径或过期指纹，同时统一补上索引与 UI 设计叶文档，避免
    大量 UI 路由断言被无关的夹具字段淹没。
    """

    upgraded = json.loads(json.dumps(payload))
    old_contract = upgraded.pop("engineering_contract", None)
    tasks = upgraded.get("tasks", [])
    if old_contract is not None:
        engineering_fingerprint = old_contract["content_fingerprint"]
        has_ui_writer = any(
            task.get("surface_kind") in {"production_ui", "design_ui"}
            for task in tasks
        )
        upgraded["standards_contract"] = {
            "index_path": "docs/STANDARDS.md",
            "root": "docs/standards",
            "index_fingerprint": engineering_fingerprint,
            "required_engineering_rule_ids": old_contract["required_rule_ids"],
            "required_design_rule_ids": ["des-baseline"] if has_ui_writer else [],
            "leaves": [
                {
                    "path": "docs/standards/GENERAL.md",
                    "domain": "engineering",
                    "content_fingerprint": engineering_fingerprint,
                    "rule_ids": list(
                        dict.fromkeys(
                            list(old_contract["required_rule_ids"])
                            + [
                                policy["rule_id"]
                                for policy in old_contract["protected_paths"]
                            ]
                        )
                    ),
                }
            ]
            + (
                [
                    {
                        "path": "docs/standards/DESIGN_FOUNDATIONS.md",
                        "domain": "design",
                        "content_fingerprint": "d" * 64,
                        "rule_ids": ["des-baseline"],
                    }
                ]
                if has_ui_writer
                else []
            ),
            "protected_paths": old_contract["protected_paths"],
        }

    ui_contract = upgraded.get("ui_contract")
    if isinstance(ui_contract, dict):
        ui_contract.pop("design_system_paths", None)

    for task in tasks:
        task["audit_surfaces"] = [
            "standards-conformance" if item == "engineering-conformance" else item
            for item in task.get("audit_surfaces", [])
        ]
        if (
            task.get("surface_kind") == "design_ui"
            and "standards-conformance" not in task["audit_surfaces"]
        ):
            task["audit_surfaces"].append("standards-conformance")
        if "engineering_exceptions" in task:
            task["standards_exceptions"] = task.pop("engineering_exceptions")
        for ref in task.get("ui_change", {}).get("design_authority_refs", []):
            if not isinstance(ref, dict):
                continue
            if ref.get("kind") == "design_system":
                ref["kind"] = "design_standard"
                if ref.get("path") == "docs/DESIGN_SYSTEM.md":
                    ref["path"] = "docs/standards/DESIGN_FOUNDATIONS.md"
        task["owned_paths"] = [
            "docs/standards/DESIGN_FOUNDATIONS.md"
            if path == "docs/DESIGN_SYSTEM.md"
            else path
            for path in task.get("owned_paths", [])
        ]

        access = task.get("controlled_document_access")
        # 旧设计任务没有工程规范字段；新模型为它显式生成“索引 + 设计叶”最小集合。
        if access is None and task.get("surface_kind") == "design_ui" and old_contract is not None:
            access = {"adapter": "project.yaml", "documents": []}
            task["controlled_document_access"] = access
        if not isinstance(access, dict) or old_contract is None:
            continue
        documents = access["documents"]
        for document in documents:
            if document["path"] == "docs/ENGINEERING.md":
                document["path"] = "docs/standards/GENERAL.md"
        documents.insert(
            0,
            {
                "path": "docs/STANDARDS.md",
                "mode": "full",
                "reason": "解析当前任务适用的最小规范叶集合",
                "sections_or_queries": [],
                "content_fingerprint": old_contract["content_fingerprint"],
                "applies_to": task.get("owned_paths", []),
                "rule_ids": [],
            },
        )
        if task.get("surface_kind") in {"production_ui", "design_ui"}:
            documents.append(
                {
                    "path": "docs/standards/DESIGN_FOUNDATIONS.md",
                    "mode": "targeted",
                    "reason": "UI 任务必须遵守适用的设计规范",
                    "sections_or_queries": ["des-baseline"],
                    "content_fingerprint": "d" * 64,
                    "applies_to": task.get("owned_paths", []),
                    "rule_ids": ["des-baseline"],
                }
            )
    return upgraded


class TaskGraphTest(unittest.TestCase):
    def test_tasks_without_dependencies_are_ready_in_deterministic_order(self) -> None:
        tasks = [
            Task("ui", "req-1", owned_paths=("docs/design/",)),
            Task("backend", "req-1", owned_paths=("backend/",)),
            Task("web", "req-1", depends_on=("api",)),
            Task("api", "req-1", blocks=("web",), owned_paths=("api/",)),
        ]

        self.assertEqual(
            ["api", "backend", "ui"],
            ready_tasks(
                tasks,
                approved_gates=set(),
                active_paths=set(),
                active_semantic_locks=set(),
                capacity=3,
            ),
        )

    def test_dependencies_and_named_gates_are_required_before_readiness(self) -> None:
        tasks = [
            Task("api", "req-1", blocks=("web",), state="BUILD_VERIFIED"),
            Task(
                "web",
                "req-1",
                depends_on=("api",),
                gates=("requirements_approved",),
            ),
        ]

        self.assertEqual(
            [],
            ready_tasks(
                tasks,
                approved_gates=set(),
                active_paths=set(),
                active_semantic_locks=set(),
                capacity=1,
            ),
        )
        self.assertEqual(
            ["web"],
            ready_tasks(
                tasks,
                approved_gates={"requirements_approved"},
                active_paths=set(),
                active_semantic_locks=set(),
                capacity=1,
            ),
        )

    def test_capacity_limits_ready_dispatch_without_creating_a_dependency(self) -> None:
        tasks = [Task("a", "req-1"), Task("b", "req-1"), Task("c", "req-1")]

        self.assertEqual(
            ["a"],
            ready_tasks(
                tasks,
                approved_gates=set(),
                active_paths=set(),
                active_semantic_locks=set(),
                capacity=1,
            ),
        )
        self.assertEqual(
            ["a", "b", "c"],
            ready_tasks(
                tasks,
                approved_gates=set(),
                active_paths=set(),
                active_semantic_locks=set(),
                capacity=3,
            ),
        )

    def test_active_owned_paths_block_only_conflicting_tasks(self) -> None:
        tasks = [
            Task("web", "req-1", owned_paths=("web/",)),
            Task("api", "req-1", owned_paths=("api/",)),
        ]

        self.assertEqual(
            ["api"],
            ready_tasks(
                tasks,
                approved_gates=set(),
                active_paths={"web/"},
                active_semantic_locks=set(),
                capacity=2,
            ),
        )

    def test_downstream_tasks_are_sorted_and_failure_does_not_affect_independent_branch(self) -> None:
        tasks = [
            Task("api", "req-1", blocks=("mobile", "web"), state="FAILED"),
            Task("web", "req-1", depends_on=("api",)),
            Task("mobile", "req-1", depends_on=("api",)),
            Task("docs", "req-1"),
        ]

        self.assertEqual(["mobile", "web"], downstream_tasks(tasks, "api"))
        self.assertEqual(
            ["docs"],
            ready_tasks(
                tasks,
                approved_gates=set(),
                active_paths=set(),
                active_semantic_locks=set(),
                capacity=3,
            ),
        )

    def test_request_closure_includes_transitive_dependencies_but_not_unrelated_work(self) -> None:
        tasks = [
            Task("api", "shared", blocks=("web",)),
            Task("web", "req-1", depends_on=("api",), blocks=("qa",)),
            Task("qa", "req-1", depends_on=("web",), task_type="qa"),
            Task("unrelated", "req-2"),
        ]

        self.assertEqual({"api", "web", "qa"}, request_closure(tasks, "req-1"))

    def test_request_qa_waits_for_all_related_build_evidence_only(self) -> None:
        tasks = [
            Task("api", "shared", blocks=("web",), state="BUILD_VERIFIED"),
            Task("web", "req-1", depends_on=("api",), state="BUILD_VERIFIED"),
            Task("qa", "req-1", task_type="qa", state="QA"),
            Task("unrelated", "req-2", state="RUNNING"),
        ]

        self.assertTrue(qa_ready(tasks, "req-1"))
        tasks[1] = Task("web", "req-1", depends_on=("api",), state="RUNNING")
        self.assertFalse(qa_ready(tasks, "req-1"))

    def test_invalid_graphs_are_rejected(self) -> None:
        with self.assertRaises(TaskGraphError):
            validate_graph([Task("a", "req-1", depends_on=("missing",))])
        with self.assertRaises(TaskGraphError):
            validate_graph([Task("a", "req-1", depends_on=("a",))])
        with self.assertRaises(TaskGraphError):
            validate_graph([Task("a", "req-1"), Task("a", "req-1")])
        with self.assertRaises(TaskGraphError):
            validate_graph(
                [Task("a", "req-1", owned_paths=("same/",)), Task("b", "req-1", owned_paths=("same/",))]
            )
        # owned_paths 是调度锁前缀，不是 shell/gitignore 模式；glob 会制造错误的并行安全结论。
        with self.assertRaisesRegex(TaskGraphError, "glob metacharacters"):
            validate_graph([Task("a", "req-1", owned_paths=("services/**",))])

    def test_serial_tasks_may_reuse_the_same_owned_path(self) -> None:
        """同一路径可以串行交接，但不能被静态校验永久锁死。"""

        tasks = [
            Task(
                "contract",
                "req-1",
                blocks=("implementation",),
                owned_paths=("services/checkout/",),
            ),
            Task(
                "implementation",
                "req-1",
                depends_on=("contract",),
                owned_paths=("services/checkout/",),
            ),
        ]

        validate_graph(tasks)

    def test_unordered_ancestor_paths_and_semantic_locks_are_rejected(self) -> None:
        """并行候选即使路径字符串不同，也不能绕过父子路径或共享契约锁。"""

        with self.assertRaisesRegex(TaskGraphError, "overlapping owned paths"):
            validate_graph(
                [
                    Task("root", "req-1", owned_paths=("services/",)),
                    Task("leaf", "req-1", owned_paths=("services/checkout/api.py",)),
                ]
            )

        with self.assertRaisesRegex(TaskGraphError, "semantic lock"):
            validate_graph(
                [
                    Task(
                        "web",
                        "req-1",
                        semantic_locks=("checkout-api-contract",),
                    ),
                    Task(
                        "ios",
                        "req-1",
                        semantic_locks=("checkout-api-contract",),
                    ),
                ]
            )

    def test_blocks_and_depends_on_must_be_bidirectionally_consistent(self) -> None:
        """blocks 不是提示文本；错误反向边必须在派发前失败。"""

        with self.assertRaisesRegex(TaskGraphError, "blocks/depends_on mismatch"):
            validate_graph(
                [
                    Task("contract", "req-1", blocks=("web",)),
                    Task("web", "req-1"),
                ]
            )

    def test_state_driven_readiness_uses_runtime_locks_and_valid_gates(self) -> None:
        """READY 只从 Task.state 推导，并同时服从路径锁、语义锁和批准 Gate。"""

        tasks = [
            Task(
                "contract",
                "req-1",
                blocks=("web",),
                state="BUILD_VERIFIED",
            ),
            Task(
                "web",
                "req-1",
                depends_on=("contract",),
                gates=("requirements_approved",),
                owned_paths=("apps/web/",),
                semantic_locks=("checkout-ui-contract",),
            ),
        ]

        self.assertEqual(
            [],
            ready_tasks(
                tasks,
                approved_gates={"requirements_approved"},
                active_paths={"apps/web/src/"},
                active_semantic_locks=set(),
                capacity=1,
            ),
        )
        self.assertEqual(
            ["web"],
            ready_tasks(
                tasks,
                approved_gates={"requirements_approved"},
                active_paths=set(),
                active_semantic_locks=set(),
                capacity=1,
            ),
        )

        with self.assertRaisesRegex(TaskGraphError, "unsupported gate"):
            validate_graph([Task("bad", "req-1", gates=("Visual Proceed",))])

    def test_effective_capacity_uses_project_host_and_active_writer_limits(self) -> None:
        """配置值只是上限；宿主剩余槽位和正在运行的 Writer 共同收紧容量。"""

        self.assertEqual(
            2,
            effective_dispatch_capacity(
                configured_subagents=8,
                configured_writers=6,
                host_available_subagents=2,
                active_subagents=3,
                active_writers=2,
            ),
        )
        self.assertEqual(
            1,
            effective_dispatch_capacity(
                configured_subagents=4,
                configured_writers=3,
                host_available_subagents=9,
                active_subagents=3,
                active_writers=1,
            ),
        )

    def test_qa_ready_checks_only_writer_tasks_in_the_request_closure(self) -> None:
        """只读诊断和 QA 自身不能形成 BUILD_VERIFIED 的循环等待。"""

        tasks = [
            Task(
                "backend",
                "req-1",
                blocks=("web",),
                state="BUILD_VERIFIED",
            ),
            Task(
                "web",
                "req-1",
                depends_on=("backend",),
                state="BUILD_VERIFIED",
            ),
            Task("diagnostics", "req-1", task_type="read_only", state="RUNNING"),
            Task("qa", "req-1", task_type="qa", state="DECLARED"),
            Task("unrelated", "req-2", state="RUNNING"),
        ]

        self.assertTrue(qa_ready(tasks, "req-1"))

    def test_cli_validates_and_computes_ready_and_qa_state(self) -> None:
        """PM 使用同一份 JSON 快照完成 validate、ready 与 qa-ready 三个门禁。"""

        engineering_fingerprint = "e" * 64
        engineering_access = {
            "adapter": "project.yaml",
            "documents": [
                {
                    "path": "docs/ENGINEERING.md",
                    "mode": "targeted",
                    "reason": "实现任务必须服从当前工程规范",
                    "sections_or_queries": ["Project-specific hard rules"],
                    "content_fingerprint": engineering_fingerprint,
                    "applies_to": ["contracts/checkout.json"],
                    "rule_ids": ["eng-baseline"],
                }
            ],
        }
        payload = {
            "engineering_contract": {
                "path": "docs/ENGINEERING.md",
                "content_fingerprint": engineering_fingerprint,
                "required_rule_ids": ["eng-baseline"],
                "protected_paths": [],
            },
            "tasks": [
                {
                    "id": "contract",
                    "request_id": "req-1",
                    "task_type": "writer",
                    "role": "xy-backend",
                    "surface_kind": "non_ui",
                    "qa_scope": "request",
                    "depends_on": [],
                    "blocks": ["web"],
                    "gates": ["requirements_approved"],
                    "owned_paths": ["contracts/checkout.json"],
                    "semantic_locks": ["checkout-api-contract"],
                    "audit_surfaces": ["engineering-conformance"],
                    "controlled_document_access": engineering_access,
                    "state": "BUILD_VERIFIED",
                },
                {
                    "id": "web",
                    "request_id": "req-1",
                    "task_type": "writer",
                    "role": "xy-web",
                    "surface_kind": "non_ui",
                    "qa_scope": "request",
                    "depends_on": ["contract"],
                    "blocks": [],
                    "gates": ["requirements_approved"],
                    "owned_paths": ["apps/web/checkout/"],
                    "semantic_locks": [],
                    "audit_surfaces": ["engineering-conformance"],
                    "controlled_document_access": {
                        "adapter": "project.yaml",
                        "documents": [
                            {
                                **engineering_access["documents"][0],
                                "applies_to": ["apps/web/checkout/"],
                            }
                        ],
                    },
                    "state": "DECLARED",
                },
            ],
            "approved_gates": ["requirements_approved"],
            "active_paths": [],
            "active_semantic_locks": [],
            "capacity": 2,
            "request_id": "req-1",
        }
        with tempfile.TemporaryDirectory(prefix="task-graph-cli-") as raw:
            source = Path(raw) / "graph.json"
            source.write_text(json.dumps(_standards_payload(payload)), encoding="utf-8")
            cli = Path(__file__).resolve().parents[1] / "lib/task_graph_cli.py"

            validate = subprocess.run(
                [sys.executable, str(cli), "validate", "--input", str(source)],
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(validate.returncode, 0, validate.stdout + validate.stderr)
            self.assertEqual({"status": "valid"}, json.loads(validate.stdout))

            ready = subprocess.run(
                [sys.executable, str(cli), "ready", "--input", str(source)],
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(ready.returncode, 0, ready.stdout + ready.stderr)
            self.assertEqual({"ready": ["web"]}, json.loads(ready.stdout))

            qa = subprocess.run(
                [sys.executable, str(cli), "qa-ready", "--input", str(source)],
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(qa.returncode, 0, qa.stdout + qa.stderr)
            self.assertEqual(
                {"qa_ready": False, "request_id": "req-1"},
                json.loads(qa.stdout),
            )

    def test_backend_writer_reads_only_index_and_applicable_engineering_leaf(self) -> None:
        """后端任务无需设计规范，但索引、工程叶、指纹、规则和路径覆盖缺一不可。"""

        fingerprint = "a" * 64
        leaf_fingerprint = "b" * 64
        payload = {
            "standards_contract": {
                "index_path": "docs/STANDARDS.md",
                "root": "docs/standards",
                "index_fingerprint": fingerprint,
                "required_engineering_rule_ids": ["eng-backend-001"],
                "required_design_rule_ids": [],
                "leaves": [
                    {
                        "path": "docs/standards/GENERAL.md",
                        "domain": "engineering",
                        "content_fingerprint": leaf_fingerprint,
                        "rule_ids": ["eng-backend-001"],
                    }
                ],
                "protected_paths": [],
            },
            "tasks": [
                {
                    "id": "backend-api",
                    "request_id": "req-backend-standards",
                    "task_type": "writer",
                    "role": "xy-backend",
                    "surface_kind": "non_ui",
                    "qa_scope": "request",
                    "depends_on": [],
                    "blocks": [],
                    "gates": ["requirements_approved"],
                    "owned_paths": ["services/api.py"],
                    "semantic_locks": [],
                    "state": "DECLARED",
                    "audit_surfaces": ["standards-conformance"],
                    "controlled_document_access": {
                        "adapter": "project.yaml",
                        "documents": [
                            {
                                "path": "docs/STANDARDS.md",
                                "mode": "full",
                                "reason": "从统一索引解析后端适用规范",
                                "sections_or_queries": [],
                                "content_fingerprint": fingerprint,
                                "applies_to": ["services/api.py"],
                                "rule_ids": [],
                            },
                            {
                                "path": "docs/standards/GENERAL.md",
                                "mode": "targeted",
                                "reason": "该工程规则覆盖后端生产源码",
                                "sections_or_queries": ["eng-backend-001"],
                                "content_fingerprint": leaf_fingerprint,
                                "applies_to": ["services/api.py"],
                                "rule_ids": ["eng-backend-001"],
                            },
                        ],
                    },
                }
            ],
        }
        cli = Path(__file__).resolve().parents[1] / "lib/task_graph_cli.py"
        with tempfile.TemporaryDirectory(prefix="backend-standards-") as raw:
            source = Path(raw) / "graph.json"
            source.write_text(json.dumps(payload), encoding="utf-8")
            result = subprocess.run(
                [sys.executable, str(cli), "validate", "--input", str(source)],
                text=True,
                capture_output=True,
                check=False,
            )
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)

        # 即使专项后端叶能覆盖写路径和任务必需规则，生产 Writer 也不能绕过
        # GENERAL 中的跨项目基础规范；这个约束不影响原型设计任务。
        omitted_baseline = json.loads(json.dumps(payload))
        omitted_baseline["standards_contract"]["leaves"][0]["rule_ids"] = [
            "eng-common-001"
        ]
        omitted_baseline["standards_contract"]["leaves"].append(
            {
                "path": "docs/standards/BACKEND.md",
                "domain": "engineering",
                "content_fingerprint": leaf_fingerprint,
                "rule_ids": ["eng-backend-001"],
            }
        )
        omitted_baseline["tasks"][0]["controlled_document_access"]["documents"][1][
            "path"
        ] = "docs/standards/BACKEND.md"
        with tempfile.TemporaryDirectory(prefix="backend-standards-no-general-") as raw:
            source = Path(raw) / "graph.json"
            source.write_text(json.dumps(omitted_baseline), encoding="utf-8")
            rejected = subprocess.run(
                [sys.executable, str(cli), "validate", "--input", str(source)],
                text=True,
                capture_output=True,
                check=False,
            )
        self.assertEqual(2, rejected.returncode)
        self.assertIn("requires selected GENERAL.md baseline", rejected.stderr)

        # 不只检查任务包读取列表，还要拒绝从冻结规范合同里直接删掉基础叶。
        missing_baseline_contract = json.loads(json.dumps(omitted_baseline))
        missing_baseline_contract["standards_contract"]["leaves"] = [
            leaf
            for leaf in missing_baseline_contract["standards_contract"]["leaves"]
            if leaf["path"] != "docs/standards/GENERAL.md"
        ]
        with tempfile.TemporaryDirectory(prefix="backend-standards-no-contract-") as raw:
            source = Path(raw) / "graph.json"
            source.write_text(json.dumps(missing_baseline_contract), encoding="utf-8")
            rejected = subprocess.run(
                [sys.executable, str(cli), "validate", "--input", str(source)],
                text=True,
                capture_output=True,
                check=False,
            )
        self.assertEqual(2, rejected.returncode)
        self.assertIn("requires GENERAL.md baseline in standards_contract", rejected.stderr)

    def test_cli_requires_frozen_engineering_authority_for_implementation_writers(self) -> None:
        """实现 Writer 缺失、跳过或伪造工程规范时，必须在派发前失败。"""

        cli = Path(__file__).resolve().parents[1] / "lib/task_graph_cli.py"
        fingerprint = "e" * 64
        task = {
            "id": "backend",
            "request_id": "req-engineering",
            "task_type": "writer",
            "role": "xy-backend",
            "surface_kind": "non_ui",
            "qa_scope": "request",
            "depends_on": [],
            "blocks": [],
            "gates": ["requirements_approved"],
            "owned_paths": ["services/api.py"],
            "semantic_locks": [],
            "state": "DECLARED",
            "audit_surfaces": ["engineering-conformance"],
            "controlled_document_access": {
                "adapter": "project.yaml",
                "documents": [
                    {
                        "path": "docs/ENGINEERING.md",
                        "mode": "targeted",
                        "reason": "源码实现必须遵守工程规范",
                        "sections_or_queries": ["Project-specific hard rules"],
                        "content_fingerprint": fingerprint,
                        "applies_to": ["services/api.py"],
                        "rule_ids": ["eng-baseline"],
                    }
                ],
            },
        }
        contract = {
            "path": "docs/ENGINEERING.md",
            "content_fingerprint": fingerprint,
            "required_rule_ids": ["eng-baseline"],
            "protected_paths": [],
        }

        def invoke(
            candidate: dict[str, object],
            *,
            engineering_contract: dict[str, object] | None = contract,
        ) -> subprocess.CompletedProcess[str]:
            with tempfile.TemporaryDirectory(prefix="engineering-contract-") as raw:
                source = Path(raw) / "graph.json"
                payload: dict[str, object] = {"tasks": [candidate]}
                if engineering_contract is not None:
                    payload["engineering_contract"] = engineering_contract
                source.write_text(json.dumps(_standards_payload(payload)), encoding="utf-8")
                return subprocess.run(
                    [sys.executable, str(cli), "validate", "--input", str(source)],
                    text=True,
                    capture_output=True,
                    check=False,
                )

        accepted = invoke(task)
        self.assertEqual(0, accepted.returncode, accepted.stdout + accepted.stderr)

        missing_contract = invoke(task, engineering_contract=None)
        self.assertEqual(2, missing_contract.returncode)
        self.assertIn("requires standards_contract", missing_contract.stderr)

        missing_access_task = json.loads(json.dumps(task))
        del missing_access_task["controlled_document_access"]
        missing_access = invoke(missing_access_task)
        self.assertEqual(2, missing_access.returncode)
        self.assertIn("requires controlled_document_access", missing_access.stderr)

        skipped_task = json.loads(json.dumps(task))
        skipped_task["controlled_document_access"]["documents"][0]["mode"] = "skip"
        skipped = invoke(skipped_task)
        self.assertEqual(2, skipped.returncode)
        self.assertIn("must not skip a selected engineering standards leaf", skipped.stderr)

        wrong_path_task = json.loads(json.dumps(task))
        wrong_path_task["controlled_document_access"]["documents"][0]["path"] = (
            "docs/OTHER.md"
        )
        wrong_path = invoke(wrong_path_task)
        self.assertEqual(2, wrong_path.returncode)
        self.assertIn("requires at least one selected engineering standards leaf", wrong_path.stderr)

        stale_task = json.loads(json.dumps(task))
        stale_task["controlled_document_access"]["documents"][0][
            "content_fingerprint"
        ] = "f" * 64
        stale = invoke(stale_task)
        self.assertEqual(2, stale.returncode)
        self.assertIn("engineering standards leaf fingerprint is stale", stale.stderr)

        incomplete_scope_task = json.loads(json.dumps(task))
        incomplete_scope_task["owned_paths"].append("services/model.py")
        incomplete_scope = invoke(incomplete_scope_task)
        self.assertEqual(2, incomplete_scope.returncode)
        self.assertIn("standards do not cover owned path", incomplete_scope.stderr)

        missing_audit_task = json.loads(json.dumps(task))
        missing_audit_task["audit_surfaces"] = []
        missing_audit = invoke(missing_audit_task)
        self.assertEqual(2, missing_audit.returncode)
        self.assertIn("standards-conformance audit surface", missing_audit.stderr)

    def test_cli_blocks_protected_upstream_edits_without_an_approved_exception(self) -> None:
        """受保护上游路径只能通过显式异常 Gate、回滚和验证合同进入调度。"""

        cli = Path(__file__).resolve().parents[1] / "lib/task_graph_cli.py"
        fingerprint = "a" * 64
        task = {
            "id": "ragflow-core",
            "request_id": "req-upstream",
            "task_type": "writer",
            "role": "xy-backend",
            "surface_kind": "non_ui",
            "qa_scope": "request",
            "depends_on": [],
            "blocks": [],
            "gates": ["requirements_approved"],
            "owned_paths": ["ragflow/api/apps/provider_api.py"],
            "semantic_locks": [],
            "state": "DECLARED",
            "audit_surfaces": ["engineering-conformance"],
            "controlled_document_access": {
                "adapter": "project.yaml",
                "documents": [
                    {
                        "path": "docs/ENGINEERING.md",
                        "mode": "targeted",
                        "reason": "命中 RAGFlow 上游保护边界",
                        "sections_or_queries": ["RAGFlow upstream boundary"],
                        "content_fingerprint": fingerprint,
                        "applies_to": ["ragflow/api/apps/provider_api.py"],
                        "rule_ids": ["eng-baseline", "eng-ragflow-upstream"],
                    }
                ],
            },
        }
        contract = {
            "path": "docs/ENGINEERING.md",
            "content_fingerprint": fingerprint,
            "required_rule_ids": ["eng-baseline"],
            "protected_paths": [
                {
                    "path": "ragflow/",
                    "rule_id": "eng-ragflow-upstream",
                    "direct_edit": "forbidden_without_exception",
                    "allowed_paths": [],
                }
            ],
        }

        def invoke(candidate: dict[str, object]) -> subprocess.CompletedProcess[str]:
            with tempfile.TemporaryDirectory(prefix="protected-upstream-") as raw:
                source = Path(raw) / "graph.json"
                source.write_text(
                    json.dumps(
                        _standards_payload(
                            {"tasks": [candidate], "engineering_contract": contract}
                        )
                    ),
                    encoding="utf-8",
                )
                return subprocess.run(
                    [sys.executable, str(cli), "validate", "--input", str(source)],
                    text=True,
                    capture_output=True,
                    check=False,
                )

        rejected = invoke(task)
        self.assertEqual(2, rejected.returncode)
        self.assertIn("writes protected path", rejected.stderr)

        missing_gate = json.loads(json.dumps(task))
        missing_gate["engineering_exceptions"] = [
            {
                "rule_id": "eng-ragflow-upstream",
                "gate": "exceptional:ragflow-hotfix",
                "reason": "上游尚未发布安全修复，临时应用最小补丁",
                "patch_surface": ["ragflow/api/apps/provider_api.py"],
                "rollback_plan": "上游修复发布后删除该补丁并恢复原文件",
                "verification_commands": ["pytest -q api/tests/test_provider_api.py"],
            }
        ]
        rejected = invoke(missing_gate)
        self.assertEqual(2, rejected.returncode)
        self.assertIn("must declare its exceptional gate", rejected.stderr)

        approved_exception = json.loads(json.dumps(missing_gate))
        approved_exception["gates"].append("exceptional:ragflow-hotfix")
        accepted = invoke(approved_exception)
        self.assertEqual(0, accepted.returncode, accepted.stdout + accepted.stderr)

    def test_cli_validates_ui_conformance_plan_fields(self) -> None:
        """一致性路由必须在派发前证明冻结依据、审计面与设计目录边界。"""

        engineering_fingerprint = "e" * 64
        authority = {
            "kind": "controlled_document",
            "authority_id": "settings-accepted-behavior",
            "path": "docs/features/settings.md",
            "anchor": "accepted-behavior",
            "content_fingerprint": "a" * 64,
            "resolution_state": "resolved",
        }
        base_task = {
            "id": "web-conformance",
            "request_id": "req-ui",
            "task_type": "writer",
            "role": "xy-web",
            "surface_kind": "production_ui",
            "qa_scope": "request",
            "depends_on": [],
            "blocks": [],
            "gates": ["requirements_approved"],
            "owned_paths": ["apps/web/settings/"],
            "semantic_locks": [],
            "state": "DECLARED",
            "ui_change": {
                "route": "UI-Conformance",
                "design_delta": "none",
                "prototype_policy": "not_applicable",
                "prototype_decision": None,
                "design_authority_refs": [authority],
                "affected_surfaces": ["settings-save-button"],
                "justification": "恢复已经批准的保存行为，不产生新的设计选择",
            },
            "audit_surfaces": ["ui", "accessibility", "engineering-conformance"],
            "controlled_document_access": {
                "adapter": "project.yaml",
                "documents": [
                    {
                        "path": "docs/ENGINEERING.md",
                        "mode": "targeted",
                        "reason": "生产 UI 实现仍必须遵守工程规范",
                        "sections_or_queries": ["Project-specific hard rules"],
                        "content_fingerprint": engineering_fingerprint,
                        "applies_to": ["apps/web/settings/"],
                        "rule_ids": ["eng-baseline"],
                    }
                ],
            },
        }
        cli = Path(__file__).resolve().parents[1] / "lib/task_graph_cli.py"

        def invoke(
            task: dict[str, object],
            command: str = "validate",
            *,
            approved_gates: list[str] | None = None,
            tasks: list[dict[str, object]] | None = None,
            prototype_paths: list[str] | None = None,
            design_system_paths: list[str] | None = None,
        ) -> subprocess.CompletedProcess[str]:
            # 使用临时 JSON 文件复用真实 CLI 入口，验证的正是 PM 运行时会消费的结构。
            with tempfile.TemporaryDirectory(prefix="ui-conformance-graph-") as raw:
                source = Path(raw) / "graph.json"
                payload = {
                    "tasks": tasks or [task],
                    "engineering_contract": {
                        "path": "docs/ENGINEERING.md",
                        "content_fingerprint": engineering_fingerprint,
                        "required_rule_ids": ["eng-baseline"],
                        "protected_paths": [],
                    },
                    # 设计路径由 PM 从 project.yaml 解析后冻结到运行时快照；CLI 据此做路径交叠检查。
                    "ui_contract": {
                        "prototype_paths": prototype_paths
                        or ["docs/standards/prototype/"],
                        "design_system_paths": design_system_paths
                        or ["docs/DESIGN_SYSTEM.md"],
                    },
                }
                if command == "ready":
                    payload.update(
                        {
                            "approved_gates": approved_gates or [],
                            "active_paths": [],
                            "active_semantic_locks": [],
                            "capacity": 1,
                        }
                    )
                source.write_text(json.dumps(_standards_payload(payload)), encoding="utf-8")
                return subprocess.run(
                    [sys.executable, str(cli), command, "--input", str(source)],
                    text=True,
                    capture_output=True,
                    check=False,
                )

        accepted = invoke(base_task)
        self.assertEqual(0, accepted.returncode, accepted.stdout + accepted.stderr)

        missing_authority = json.loads(json.dumps(base_task))
        missing_authority["ui_change"]["design_authority_refs"] = []
        rejected = invoke(missing_authority)
        self.assertEqual(2, rejected.returncode)
        self.assertIn("requires non-empty design_authority_refs", rejected.stderr)

        visual_gate = json.loads(json.dumps(base_task))
        visual_gate["gates"].append("visual_approved:settings@deadbeef")
        rejected = invoke(visual_gate)
        self.assertEqual(2, rejected.returncode)
        self.assertIn("must not declare a visual gate", rejected.stderr)

        # 非法引用不能再靠“非空字符串”蒙混过关；必须有可定位来源和冻结的 SHA-256。
        invalid_authority = json.loads(json.dumps(base_task))
        invalid_authority["ui_change"]["design_authority_refs"] = [
            {
                **authority,
                "content_fingerprint": "deadbeef",
                "resolution_state": "unresolved",
            }
        ]
        rejected = invoke(invalid_authority)
        self.assertEqual(2, rejected.returncode)
        self.assertIn("content_fingerprint", rejected.stderr)

        unresolved_authority = json.loads(json.dumps(base_task))
        unresolved_authority["ui_change"]["design_authority_refs"][0][
            "resolution_state"
        ] = "unresolved"
        rejected = invoke(unresolved_authority)
        self.assertEqual(2, rejected.returncode)
        self.assertIn("resolution_state must be 'resolved'", rejected.stderr)

        free_form_authority = json.loads(json.dumps(base_task))
        free_form_authority["ui_change"]["design_authority_refs"] = [
            "not-a-resolvable-authority"
        ]
        rejected = invoke(free_form_authority)
        self.assertEqual(2, rejected.returncode)
        self.assertIn("must be an object", rejected.stderr)

        # Authority 的 kind 必须与适配器冻结的有类型路径相符，不能只伪造标签和指纹。
        valid_prototype_authority = json.loads(json.dumps(base_task))
        valid_prototype_authority["ui_change"]["design_authority_refs"] = [
            {
                **authority,
                "kind": "prototype_contract",
                "authority_id": "settings-prototype",
                "path": "docs/standards/prototype/settings.html",
            }
        ]
        accepted = invoke(valid_prototype_authority)
        self.assertEqual(0, accepted.returncode, accepted.stdout + accepted.stderr)

        # 旧 references 分支不再是权威入口；改成其他 kind 也不能恢复嵌套规范路径。
        valid_design_reference = json.loads(json.dumps(base_task))
        valid_design_reference["ui_change"]["design_authority_refs"] = [
            {
                **authority,
                "authority_id": "settings-design-reference",
                "path": "docs/standards/design/references/settings.md",
            }
        ]
        rejected = invoke(valid_design_reference)
        self.assertEqual(2, rejected.returncode)
        self.assertIn("standards authority must be a shallow", rejected.stderr)

        mislabeled_design_reference = json.loads(json.dumps(valid_design_reference))
        mislabeled_design_reference["ui_change"]["design_authority_refs"][0]["kind"] = (
            "production_baseline"
        )
        rejected = invoke(mislabeled_design_reference)
        self.assertEqual(2, rejected.returncode)
        self.assertIn("standards authority must be a shallow", rejected.stderr)

        valid_design_system_authority = json.loads(json.dumps(base_task))
        valid_design_system_authority["ui_change"]["design_authority_refs"] = [
            {
                **authority,
                "kind": "design_system",
                "authority_id": "current-design-system",
                "path": "docs/DESIGN_SYSTEM.md",
                # 迁移后的设计叶夹具使用 d 指纹；合法 authority 必须指向同一版本。
                "content_fingerprint": "d" * 64,
            }
        ]
        accepted = invoke(valid_design_system_authority)
        self.assertEqual(0, accepted.returncode, accepted.stdout + accepted.stderr)

        escaped_prototype_authority = json.loads(json.dumps(valid_prototype_authority))
        escaped_prototype_authority["ui_change"]["design_authority_refs"][0]["path"] = (
            "tmp/fake-prototype.html"
        )
        rejected = invoke(escaped_prototype_authority)
        self.assertEqual(2, rejected.returncode)
        self.assertIn("prototype_contract path must be inside", rejected.stderr)

        escaped_design_system_authority = json.loads(
            json.dumps(valid_design_system_authority)
        )
        escaped_design_system_authority["ui_change"]["design_authority_refs"][0]["path"] = (
            "tmp/fake-design-system.md"
        )
        rejected = invoke(escaped_design_system_authority)
        self.assertEqual(2, rejected.returncode)
        self.assertIn("design_standard path must match a frozen design leaf", rejected.stderr)

        mislabeled_prototype_authority = json.loads(json.dumps(base_task))
        mislabeled_prototype_authority["ui_change"]["design_authority_refs"][0]["path"] = (
            "docs/standards/prototype/settings.html"
        )
        rejected = invoke(mislabeled_prototype_authority)
        self.assertEqual(2, rejected.returncode)
        self.assertIn("must use kind prototype_contract", rejected.stderr)

        prototype_on_design_system = json.loads(json.dumps(valid_prototype_authority))
        prototype_on_design_system["ui_change"]["design_authority_refs"][0]["path"] = (
            "docs/DESIGN_SYSTEM.md"
        )
        rejected = invoke(prototype_on_design_system)
        self.assertEqual(2, rejected.returncode)
        self.assertIn("prototype_contract path must be inside", rejected.stderr)

        # UI-Conformance 不得直接或通过过宽父目录拥有任何已解析设计路径。
        design_write = json.loads(json.dumps(base_task))
        design_write["owned_paths"] = ["docs/standards/prototype/settings.html"]
        rejected = invoke(design_write)
        self.assertEqual(2, rejected.returncode)
        self.assertIn("must not overlap configured design path", rejected.stderr)

        custom_design_write = json.loads(json.dumps(base_task))
        custom_design_write["owned_paths"] = [
            "docs/standards/DESIGN_FOUNDATIONS.md"
        ]
        rejected = invoke(custom_design_write)
        self.assertEqual(2, rejected.returncode)
        self.assertIn("must not overlap configured design path", rejected.stderr)

        missing_audit = json.loads(json.dumps(base_task))
        missing_audit["audit_surfaces"] = ["ui"]
        rejected = invoke(missing_audit)
        self.assertEqual(2, rejected.returncode)
        self.assertIn("ui and accessibility audit surfaces", rejected.stderr)

        missing_ui_change = json.loads(json.dumps(base_task))
        del missing_ui_change["ui_change"]
        rejected = invoke(missing_ui_change)
        self.assertEqual(2, rejected.returncode)
        self.assertIn("production_ui requires ui_change", rejected.stderr)

        wrong_scope = json.loads(json.dumps(base_task))
        wrong_scope["qa_scope"] = "project"
        rejected = invoke(wrong_scope)
        self.assertEqual(2, rejected.returncode)
        self.assertIn("qa_scope must be 'request'", rejected.stderr)

        # 一致性任务即使不直接由 xy-uiux 执行，也不能依赖本请求中的设计写入任务。
        dependent = json.loads(json.dumps(base_task))
        dependent["depends_on"] = ["prototype"]
        design_task = {
            "id": "prototype",
            "request_id": "req-ui",
            "task_type": "writer",
            "role": "xy-uiux",
            "surface_kind": "design_ui",
            "qa_scope": "request",
            "depends_on": [],
            "blocks": ["web-conformance"],
            "gates": ["requirements_approved"],
            "owned_paths": ["docs/standards/prototype/settings.html"],
            "semantic_locks": [],
            "state": "DECLARED",
            "audit_surfaces": ["ui", "accessibility"],
        }
        rejected = invoke(dependent, tasks=[design_task, dependent])
        self.assertEqual(2, rejected.returncode)
        self.assertIn("must not depend on xy-uiux", rejected.stderr)

        # 不能通过更换角色标签来改写冻结原型：设计路径写权限是全图 Writer 不变量。
        dependent_on_disguised_writer = json.loads(json.dumps(base_task))
        dependent_on_disguised_writer["depends_on"] = ["shadow-prototype"]
        disguised_writer = {
            "id": "shadow-prototype",
            "request_id": "req-ui",
            "task_type": "writer",
            "role": "xy-web",
            "surface_kind": "non_ui",
            "qa_scope": "request",
            "depends_on": [],
            "blocks": ["web-conformance"],
            "gates": ["requirements_approved"],
            "owned_paths": ["docs/standards/prototype/settings.html"],
            "semantic_locks": [],
            "state": "BUILD_VERIFIED",
            "audit_surfaces": ["docs"],
        }
        rejected = invoke(
            dependent_on_disguised_writer,
            tasks=[disguised_writer, dependent_on_disguised_writer],
        )
        self.assertEqual(2, rejected.returncode)
        self.assertIn("writer overlapping a typed design path", rejected.stderr)

        smuggled_variants = (
            ("design-system-smuggle", ["docs/DESIGN_SYSTEM.md"], True),
            ("roleless-smuggle", ["docs/standards/prototype/other.html"], False),
            ("broad-smuggle", ["docs/"], True),
        )
        for task_id, owned_paths, include_role in smuggled_variants:
            with self.subTest(task_id=task_id):
                dependent_variant = json.loads(json.dumps(base_task))
                dependent_variant["depends_on"] = [task_id]
                variant = {
                    "id": task_id,
                    "request_id": "req-ui",
                    "task_type": "writer",
                    "depends_on": [],
                    "blocks": ["web-conformance"],
                    "gates": ["requirements_approved"],
                    "owned_paths": owned_paths,
                    "semantic_locks": [],
                    "state": "BUILD_VERIFIED",
                }
                if include_role:
                    variant.update(
                        {
                            "role": "xy-web",
                            "surface_kind": "non_ui",
                            "qa_scope": "request",
                            "audit_surfaces": ["docs"],
                        }
                    )
                rejected = invoke(
                    dependent_variant,
                    tasks=[variant, dependent_variant],
                )
                self.assertEqual(2, rejected.returncode)
                self.assertIn("writer overlapping a typed design path", rejected.stderr)

        # 传递依赖也必须服从同一全图不变量，不能隔一层 evidence 任务隐藏写入者。
        transitive_dependent = json.loads(json.dumps(base_task))
        transitive_dependent["depends_on"] = ["bridge"]
        transitive_smuggler = {
            **disguised_writer,
            "id": "transitive-smuggler",
            "blocks": ["bridge"],
        }
        bridge = {
            "id": "bridge",
            "request_id": "req-ui",
            "task_type": "evidence",
            "depends_on": ["transitive-smuggler"],
            "blocks": ["web-conformance"],
            "gates": [],
            "owned_paths": [],
            "semantic_locks": [],
            "state": "BUILD_VERIFIED",
        }
        rejected = invoke(
            transitive_dependent,
            tasks=[transitive_smuggler, bridge, transitive_dependent],
        )
        self.assertEqual(2, rejected.returncode)
        self.assertIn("writer overlapping a typed design path", rejected.stderr)

    def test_cli_binds_each_design_change_route_to_approved_page_fingerprints(self) -> None:
        """Patch/Page/Flow 都必须等待与已批准页面一一匹配的视觉 Gate。"""

        cli = Path(__file__).resolve().parents[1] / "lib/task_graph_cli.py"
        fingerprint = "b" * 64
        engineering_fingerprint = "e" * 64
        expected_gate = f"visual_approved:settings@{fingerprint}"

        def task_for(route: str) -> dict[str, object]:
            return {
                "id": f"web-{route.casefold()}",
                "request_id": "req-design",
                "task_type": "writer",
                "role": "xy-web",
                "surface_kind": "production_ui",
                "qa_scope": "request",
                "depends_on": ["prototype"],
                "blocks": [],
                "gates": ["requirements_approved", expected_gate],
                "owned_paths": ["apps/web/settings/"],
                "semantic_locks": [],
                "state": "DECLARED",
                "ui_change": {
                    "route": route,
                    "design_delta": "changed",
                    "prototype_policy": "required",
                    "prototype_decision": {
                        "source": "requirements_confirmation_user_choice",
                        "choice_ref": "user:req-design/use-prototype",
                        "requirement_fingerprint": "a" * 64,
                        "affected_surfaces": ["settings-page"],
                        "recommended_policy": "required",
                        "recommendation_reason": "页面结构和交互均发生变化，先确认原型可以降低返工风险",
                        "selected_policy": "required",
                    },
                    "design_authority_refs": [
                        {
                            "kind": "prototype_contract",
                            "authority_id": "settings",
                            "path": "docs/standards/prototype/settings.html",
                            "anchor": "page-design-and-interaction-contract",
                            "content_fingerprint": fingerprint,
                            "resolution_state": "resolved",
                        }
                    ],
                    "affected_surfaces": ["settings-page"],
                    "justification": "实现已经完成视觉确认的设置页设计变更",
                },
                "audit_surfaces": ["ui", "accessibility", "engineering-conformance"],
                "controlled_document_access": {
                    "adapter": "project.yaml",
                    "documents": [
                        {
                            "path": "docs/ENGINEERING.md",
                            "mode": "targeted",
                            "reason": "生产 UI 实现仍必须遵守工程规范",
                            "sections_or_queries": ["Project-specific hard rules"],
                            "content_fingerprint": engineering_fingerprint,
                            "applies_to": ["apps/web/settings/"],
                            "rule_ids": ["eng-baseline"],
                        }
                    ],
                },
            }

        def design_task_for(production_task_id: str) -> dict[str, object]:
            # 设计变更路由必须依赖本请求中已经构建验证的 xy-uiux 原型任务；
            # 单独批准视觉 Gate 不能代替这条有向依赖和真实设计证据。
            return {
                "id": "prototype",
                "request_id": "req-design",
                "task_type": "writer",
                "role": "xy-uiux",
                "surface_kind": "design_ui",
                "qa_scope": "request",
                "depends_on": [],
                "blocks": [production_task_id],
                "gates": ["requirements_approved"],
                "owned_paths": ["docs/standards/prototype/settings.html"],
                "semantic_locks": [],
                "state": "BUILD_VERIFIED",
                "audit_surfaces": ["ui", "accessibility"],
            }

        def invoke(
            task: dict[str, object],
            command: str,
            approved_gates: list[str],
            *,
            design_task: dict[str, object] | None = None,
        ) -> subprocess.CompletedProcess[str]:
            with tempfile.TemporaryDirectory(prefix="ui-design-graph-") as raw:
                source = Path(raw) / "graph.json"
                source.write_text(
                    json.dumps(
                        _standards_payload({
                            "tasks": [
                                design_task or design_task_for(str(task["id"])),
                                task,
                            ],
                            "ui_contract": {
                                "prototype_paths": ["docs/standards/prototype/"],
                                "design_system_paths": ["docs/DESIGN_SYSTEM.md"],
                            },
                            "engineering_contract": {
                                "path": "docs/ENGINEERING.md",
                                "content_fingerprint": engineering_fingerprint,
                                "required_rule_ids": ["eng-baseline"],
                                "protected_paths": [],
                            },
                            "requirements_fingerprint": "a" * 64,
                            "approved_gates": approved_gates,
                            "active_paths": [],
                            "active_semantic_locks": [],
                            "capacity": 1,
                        })
                    ),
                    encoding="utf-8",
                )
                return subprocess.run(
                    [sys.executable, str(cli), command, "--input", str(source)],
                    text=True,
                    capture_output=True,
                    check=False,
                )

        for route in ("UI-Patch", "UI-Page", "UI-Flow"):
            with self.subTest(route=route):
                task = task_for(route)
                valid = invoke(task, "validate", [])
                self.assertEqual(0, valid.returncode, valid.stdout + valid.stderr)

                waiting = invoke(task, "ready", ["requirements_approved"])
                self.assertEqual(0, waiting.returncode, waiting.stdout + waiting.stderr)
                self.assertEqual({"ready": []}, json.loads(waiting.stdout))

                ready = invoke(
                    task,
                    "ready",
                    ["requirements_approved", expected_gate],
                )
                self.assertEqual(0, ready.returncode, ready.stdout + ready.stderr)
                self.assertEqual({"ready": [task["id"]]}, json.loads(ready.stdout))

        # “制作原型”也必须是用户在需求确认中的选择，不能再由 PM 默认补成 required。
        missing_user_choice = task_for("UI-Page")
        missing_user_choice["ui_change"]["prototype_decision"] = None
        rejected = invoke(missing_user_choice, "validate", [])
        self.assertEqual(2, rejected.returncode)
        self.assertIn("requires prototype_decision", rejected.stderr)

        missing_visual = task_for("UI-Page")
        missing_visual["gates"] = ["requirements_approved"]
        rejected = invoke(missing_visual, "validate", [])
        self.assertEqual(2, rejected.returncode)
        self.assertIn("requires exact visual gate", rejected.stderr)

        mismatched_visual = task_for("UI-Page")
        mismatched_visual["gates"] = [
            "requirements_approved",
            f"visual_approved:other@{fingerprint}",
        ]
        rejected = invoke(mismatched_visual, "validate", [])
        self.assertEqual(2, rejected.returncode)
        self.assertIn("requires exact visual gate", rejected.stderr)

        mismatched_prototype = task_for("UI-Page")
        mismatched_prototype["ui_change"]["design_authority_refs"][0]["path"] = (
            "docs/standards/prototype/other.html"
        )
        rejected = invoke(mismatched_prototype, "validate", [])
        self.assertEqual(2, rejected.returncode)
        self.assertIn("prototype authority is not owned", rejected.stderr)

        non_writer_design = design_task_for(str(task_for("UI-Page")["id"]))
        non_writer_design["task_type"] = "read_only"
        rejected = invoke(
            task_for("UI-Page"),
            "validate",
            [],
            design_task=non_writer_design,
        )
        self.assertEqual(2, rejected.returncode)
        self.assertIn("design_ui must be a writer", rejected.stderr)

        disguised_design = design_task_for(str(task_for("UI-Page")["id"]))
        disguised_design.update(
            {
                "surface_kind": "non_ui",
                "task_type": "read_only",
                "gates": [],
                "audit_surfaces": ["docs"],
            }
        )
        rejected = invoke(
            task_for("UI-Page"),
            "validate",
            [],
            design_task=disguised_design,
        )
        self.assertEqual(2, rejected.returncode)
        self.assertIn("role xy-uiux requires surface_kind design_ui", rejected.stderr)

        unapproved_design = design_task_for(str(task_for("UI-Page")["id"]))
        unapproved_design["gates"] = []
        rejected = invoke(
            task_for("UI-Page"),
            "validate",
            [],
            design_task=unapproved_design,
        )
        self.assertEqual(2, rejected.returncode)
        self.assertIn("design_ui requires requirements_approved", rejected.stderr)

        escaped_task = task_for("UI-Page")
        escaped_task["ui_change"]["design_authority_refs"][0]["path"] = (
            "tmp/fake-prototype.html"
        )
        escaped_design = design_task_for(str(escaped_task["id"]))
        escaped_design["owned_paths"] = ["tmp/fake-prototype.html"]
        rejected = invoke(
            escaped_task,
            "validate",
            [],
            design_task=escaped_design,
        )
        self.assertEqual(2, rejected.returncode)
        self.assertIn("design_ui owned path must be inside", rejected.stderr)

        broad_design = design_task_for(str(task_for("UI-Page")["id"]))
        broad_design["owned_paths"] = ["docs/"]
        rejected = invoke(
            task_for("UI-Page"),
            "validate",
            [],
            design_task=broad_design,
        )
        self.assertEqual(2, rejected.returncode)
        self.assertIn("design_ui owned path must be inside", rejected.stderr)

        duplicate_id = task_for("UI-Flow")
        duplicate_id["ui_change"]["design_authority_refs"].append(
            {
                "kind": "prototype_contract",
                "authority_id": "settings",
                "path": "docs/standards/prototype/other.html",
                "anchor": "page-design-and-interaction-contract",
                "content_fingerprint": fingerprint,
                "resolution_state": "resolved",
            }
        )
        directory_design = design_task_for(str(duplicate_id["id"]))
        directory_design["owned_paths"] = ["docs/standards/prototype/"]
        rejected = invoke(
            duplicate_id,
            "validate",
            [],
            design_task=directory_design,
        )
        self.assertEqual(2, rejected.returncode)
        self.assertIn("prototype authority_id values must be unique", rejected.stderr)

        duplicate_path = task_for("UI-Flow")
        duplicate_path["ui_change"]["design_authority_refs"].append(
            {
                "kind": "prototype_contract",
                "authority_id": "settings-copy",
                "path": "docs/standards/prototype/settings.html",
                "anchor": "alternate-contract-anchor",
                "content_fingerprint": "c" * 64,
                "resolution_state": "resolved",
            }
        )
        duplicate_path["gates"].append(f"visual_approved:settings-copy@{'c' * 64}")
        rejected = invoke(duplicate_path, "validate", [])
        self.assertEqual(2, rejected.returncode)
        self.assertIn("prototype paths must be unique", rejected.stderr)

        # 多页面流程是合法场景，但每个页面必须拥有独立来源、指纹与视觉批准 Gate。
        multi_page = task_for("UI-Flow")
        second_fingerprint = "c" * 64
        multi_page["ui_change"]["design_authority_refs"].append(
            {
                "kind": "prototype_contract",
                "authority_id": "profile",
                "path": "docs/standards/prototype/profile.html",
                "anchor": "page-design-and-interaction-contract",
                "content_fingerprint": second_fingerprint,
                "resolution_state": "resolved",
            }
        )
        multi_page["gates"].append(
            f"visual_approved:profile@{second_fingerprint}"
        )
        multi_page_design = design_task_for(str(multi_page["id"]))
        multi_page_design["owned_paths"] = ["docs/standards/prototype/"]
        accepted = invoke(
            multi_page,
            "validate",
            [],
            design_task=multi_page_design,
        )
        self.assertEqual(0, accepted.returncode, accepted.stdout + accepted.stderr)

        generic_route = task_for("design_change")
        rejected = invoke(generic_route, "validate", [])
        self.assertEqual(2, rejected.returncode)
        self.assertIn("unsupported route", rejected.stderr)

    def test_cli_requires_a_scope_bound_prototype_choice_at_requirements_confirmation(self) -> None:
        """原型与直接开发两条路都必须来自需求确认中的用户选择。"""

        cli = Path(__file__).resolve().parents[1] / "lib/task_graph_cli.py"
        engineering_fingerprint = "e" * 64
        task = {
            "id": "web-direct-ui-page",
            "request_id": "req-direct-ui",
            "task_type": "writer",
            "role": "xy-web",
            "surface_kind": "production_ui",
            "qa_scope": "request",
            "depends_on": [],
            "blocks": [],
            "gates": ["requirements_approved"],
            "owned_paths": ["apps/web/settings/"],
            "semantic_locks": [],
            "state": "DECLARED",
            "ui_change": {
                "route": "UI-Page",
                "design_delta": "changed",
                "prototype_policy": "waived_by_user",
                "prototype_decision": {
                    "source": "requirements_confirmation_user_choice",
                    "choice_ref": "user:req-direct-ui/no-prototype",
                    "requirement_fingerprint": "a" * 64,
                    "affected_surfaces": ["settings-page"],
                    "recommended_policy": "required",
                    "recommendation_reason": "新增页面包含新的交互流程，原型有助于提前确认",
                    "selected_policy": "waived_by_user",
                },
                "design_authority_refs": [],
                "affected_surfaces": ["settings-page"],
                "justification": "在已确认需求范围内直接实现设置页设计变化",
            },
            "audit_surfaces": ["ui", "accessibility", "engineering-conformance"],
            "controlled_document_access": {
                "adapter": "project.yaml",
                "documents": [
                    {
                        "path": "docs/ENGINEERING.md",
                        "mode": "targeted",
                        "reason": "直接实现生产 UI 仍必须遵守工程规范",
                        "sections_or_queries": ["Project-specific hard rules"],
                        "content_fingerprint": engineering_fingerprint,
                        "applies_to": ["apps/web/settings/"],
                        "rule_ids": ["eng-baseline"],
                    }
                ],
            },
        }

        def invoke(
            candidate: dict[str, object],
            *,
            tasks: list[dict[str, object]] | None = None,
        ) -> subprocess.CompletedProcess[str]:
            with tempfile.TemporaryDirectory(prefix="ui-prototype-decision-") as raw:
                source = Path(raw) / "graph.json"
                source.write_text(
                    json.dumps(
                        _standards_payload({
                            "tasks": tasks or [candidate],
                            "ui_contract": {
                                "prototype_paths": ["docs/standards/prototype/"],
                                "design_system_paths": ["docs/DESIGN_SYSTEM.md"],
                            },
                            "engineering_contract": {
                                "path": "docs/ENGINEERING.md",
                                "content_fingerprint": engineering_fingerprint,
                                "required_rule_ids": ["eng-baseline"],
                                "protected_paths": [],
                            },
                            "requirements_fingerprint": "a" * 64,
                        })
                    ),
                    encoding="utf-8",
                )
                return subprocess.run(
                    [sys.executable, str(cli), "validate", "--input", str(source)],
                    text=True,
                    capture_output=True,
                    check=False,
                )

        accepted = invoke(task)
        self.assertEqual(0, accepted.returncode, accepted.stdout + accepted.stderr)

        missing_record = json.loads(json.dumps(task))
        missing_record["ui_change"]["prototype_decision"] = None
        rejected = invoke(missing_record)
        self.assertEqual(2, rejected.returncode)
        self.assertIn("requires prototype_decision", rejected.stderr)

        invented_by_pm = json.loads(json.dumps(task))
        invented_by_pm["ui_change"]["prototype_decision"]["source"] = "pm_decision"
        rejected = invoke(invented_by_pm)
        self.assertEqual(2, rejected.returncode)
        self.assertIn(
            "source must be 'requirements_confirmation_user_choice'",
            rejected.stderr,
        )

        expanded_scope = json.loads(json.dumps(task))
        expanded_scope["ui_change"]["prototype_decision"]["affected_surfaces"] = [
            "settings-page",
            "billing-page",
        ]
        rejected = invoke(expanded_scope)
        self.assertEqual(2, rejected.returncode)
        self.assertIn("must exactly match ui_change.affected_surfaces", rejected.stderr)

        stale_requirement = json.loads(json.dumps(task))
        stale_requirement["ui_change"]["prototype_decision"][
            "requirement_fingerprint"
        ] = "c" * 64
        rejected = invoke(stale_requirement)
        self.assertEqual(2, rejected.returncode)
        self.assertIn("must match task graph requirements_fingerprint", rejected.stderr)

        mismatched_selection = json.loads(json.dumps(task))
        mismatched_selection["ui_change"]["prototype_decision"][
            "selected_policy"
        ] = "required"
        rejected = invoke(mismatched_selection)
        self.assertEqual(2, rejected.returncode)
        self.assertIn(
            "selected_policy must match ui_change.prototype_policy",
            rejected.stderr,
        )

        visual_gate = json.loads(json.dumps(task))
        visual_gate["gates"].append("visual_approved:settings@" + "b" * 64)
        rejected = invoke(visual_gate)
        self.assertEqual(2, rejected.returncode)
        self.assertIn("waived_by_user must not declare a visual gate", rejected.stderr)

        stale_prototype_authority = json.loads(json.dumps(task))
        stale_prototype_authority["ui_change"]["design_authority_refs"] = [
            {
                "kind": "prototype_contract",
                "authority_id": "settings",
                "path": "docs/standards/prototype/settings.html",
                "anchor": "page-design-and-interaction-contract",
                "content_fingerprint": "b" * 64,
                "resolution_state": "resolved",
            }
        ]
        rejected = invoke(stale_prototype_authority)
        self.assertEqual(2, rejected.returncode)
        self.assertIn("must not use prototype_contract authority", rejected.stderr)

        dependent = json.loads(json.dumps(task))
        dependent["depends_on"] = ["prototype"]
        design_task = {
            "id": "prototype",
            "request_id": "req-direct-ui",
            "task_type": "writer",
            "role": "xy-uiux",
            "surface_kind": "design_ui",
            "qa_scope": "request",
            "depends_on": [],
            "blocks": ["web-direct-ui-page"],
            "gates": ["requirements_approved"],
            "owned_paths": ["docs/standards/prototype/settings.html"],
            "semantic_locks": [],
            "state": "BUILD_VERIFIED",
            "audit_surfaces": ["ui", "accessibility"],
        }
        rejected = invoke(dependent, tasks=[design_task, dependent])
        self.assertEqual(2, rejected.returncode)
        self.assertIn("waived_by_user must not depend on xy-uiux", rejected.stderr)


if __name__ == "__main__":
    unittest.main()
