from __future__ import annotations

import json
import hashlib
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from tests.test_scheduler_boundaries import v2_graph, with_builtin_standards

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


def _builtin_standards_payload(prefix: str = "") -> dict:
    """沿用已有Writer夹具，只切换真实内置源；不依赖被删除的项目通用模板。"""
    from tests.test_scheduler_boundaries import _writer_payload
    payload = _writer_payload()
    path = "platforms/shared/skills/xy-code-standards/references/rules.md"
    digest = hashlib.sha256((Path(__file__).resolve().parents[1] / path).read_bytes()).hexdigest()
    leaf = {"path": prefix + path, "domain": "engineering", "content_fingerprint": digest, "rule_ids": ["eng-common-005"]}
    payload["standards_contract"].update(index_fingerprint=None, required_engineering_rule_ids=["eng-common-005"], leaves=[leaf], protected_paths=[])
    payload["tasks"][0]["controlled_document_access"]["documents"] = [{
        "path": leaf["path"], "content_fingerprint": digest, "rule_ids": ["eng-common-005"],
        "mode": "full", "reason": "读取真实内置工程底线", "sections_or_queries": [],
        "applies_to": payload["tasks"][0]["owned_paths"],
    }]
    return payload


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
    return with_builtin_standards(v2_graph(upgraded))


class RequestUiQaContractTest(unittest.TestCase):
    def test_export_preserves_each_writer_contract_and_rejects_forgery(self):
        """QA 审查多个界面时保留各自权威；不能靠伪造投影或角色绕过写入边界。"""
        import copy
        from lib.task_graph_cli import _execute, _verify_ui_scope, export_task_pack, REVIEWED_UI_FIELDS

        graph = _builtin_standards_payload()
        writer = graph["tasks"][0]
        writer.update(role="xy-web", surface_kind="production_ui",
                      audit_surfaces=["ui", "accessibility", "standards-conformance"],
                      ui_change={"route": "UI-Conformance", "design_delta": "none",
                                 "prototype_policy": "not_applicable", "prototype_decision": None,
                                 "design_authority_refs": [{"kind": "controlled_document",
                                     "authority_id": "accepted", "path": "docs/accepted.md",
                                     "anchor": "ui", "content_fingerprint": "a" * 64,
                                     "resolution_state": "resolved"}],
                                 "affected_surfaces": ["settings"], "justification": "恢复已批准界面"})
        graph["ui_contract"] = {"prototype_paths": ["docs/standards/prototype"]}
        with_builtin_standards(graph)
        graph["standards_contract"]["required_design_rule_ids"] = ["des-baseline-001"]
        second = copy.deepcopy(writer)
        second["id"] = "second"
        second["owned_paths"] = ["web/other.py"]
        second["ui_change"]["affected_surfaces"] = ["other"]
        for document in second["controlled_document_access"]["documents"]:
            document["applies_to"] = second["owned_paths"]
        qa = {"id": "qa", "request_id": writer["request_id"], "task_type": "qa",
              "depends_on": [writer["id"], second["id"]], "blocks": [], "gates": [],
              "owned_paths": [], "semantic_locks": [], "state": "DECLARED",
              "audit_surfaces": ["ui", "accessibility"]}
        writer["blocks"] = ["qa"]
        second["blocks"] = ["qa"]
        graph["tasks"].extend([second, qa])
        v2_graph(graph)
        pack = export_task_pack(graph, "qa")
        # 使用源码 CLI 的真实入口导出，验证交接消费者收到的字节与内存校验一致。
        cli = Path(__file__).resolve().parents[1] / "lib/task_graph_cli.py"
        with tempfile.TemporaryDirectory(prefix="ui-qa-graph-") as directory:
            source = Path(directory).resolve() / "graph.json"
            source.write_text(json.dumps(graph), encoding="utf-8")
            command = subprocess.run([sys.executable, str(cli), "task", "--input", str(source),
                                      "--task-id", "qa"], text=True, capture_output=True, check=False)
            qa_file = source.with_name("qa.json")
            qa_file.write_text(json.dumps(pack), encoding="utf-8")
            comparison = subprocess.run([sys.executable, str(cli), "verify-ui-scope", "--input",
                                         str(qa_file), "--source", str(source)],
                                        text=True, capture_output=True, check=False)
            self.assertEqual(0, comparison.returncode, comparison.stderr)
            self.assertEqual(hashlib.sha256(qa_file.read_bytes()).hexdigest(),
                             json.loads(comparison.stdout)["task_pack_sha256"])
        self.assertEqual(0, command.returncode, command.stderr)
        self.assertEqual(pack, json.loads(command.stdout))
        self.assertEqual(["settings", "other"], [entry["ui_change"]["affected_surfaces"][0]
                                                   for entry in pack["reviewed_ui_changes"]])
        self.assertEqual({"status": "valid"}, _execute("validate", pack))
        _verify_ui_scope(pack, graph)
        for projection in ([], pack["reviewed_ui_changes"][:1], None):
            invalid = copy.deepcopy(pack)
            if projection is None:
                invalid.pop("reviewed_ui_changes")
            else:
                invalid["reviewed_ui_changes"] = projection
            with self.subTest(projection=projection), self.assertRaises(TaskGraphError):
                _verify_ui_scope(invalid, graph)

        # Light 不生成图：使用同请求的现有 Writer 单包校验 UI 投影和冻结版本。
        light_writer = copy.deepcopy(writer)
        light_writer.update(workflow_level="Light", depends_on=[], blocks=[], gates=[],
                            goal="恢复界面文案", input_contracts=["既有界面依据"],
                            output_contracts=["保留界面行为"], acceptance_evidence=["界面可运行"],
                            verification_commands=[{"run": "test", "expected": "成功"}])
        light_writer.pop("qa_scope", None)
        light_source = {"schema_version": 2, "task": light_writer,
                        "standards_contract": copy.deepcopy(graph["standards_contract"]),
                        "ui_contract": copy.deepcopy(graph["ui_contract"]), "approved_gates": []}
        light_qa = copy.deepcopy(pack)
        light_qa["task"].update(workflow_level="Light", depends_on=[], blocks=[])
        light_qa["reviewed_ui_changes"] = [{key: copy.deepcopy(light_writer[key])
                                            for key in REVIEWED_UI_FIELDS if key in light_writer}]
        _verify_ui_scope(light_qa, light_source)
        with tempfile.TemporaryDirectory(prefix="light-ui-qa-") as directory:
            folder = Path(directory).resolve()
            source = folder / "writer.json"
            target = folder / "qa.json"
            source.write_text(json.dumps(light_source), encoding="utf-8")
            target.write_text(json.dumps(light_qa), encoding="utf-8")
            result = subprocess.run([sys.executable, str(cli), "verify-ui-scope", "--input",
                                     str(target), "--source", str(source)],
                                    text=True, capture_output=True, check=False)
            self.assertEqual(0, result.returncode, result.stderr)
            self.assertEqual(hashlib.sha256(source.read_bytes()).hexdigest(),
                             json.loads(result.stdout)["source_sha256"])
        invalid = copy.deepcopy(light_qa)
        invalid["reviewed_ui_changes"] = []
        with self.assertRaises(TaskGraphError):
            _verify_ui_scope(invalid, light_source)
        invalid = copy.deepcopy(light_source)
        invalid["task"]["request_id"] = "other-request"
        with self.assertRaises(TaskGraphError):
            _verify_ui_scope(light_qa, invalid)
        for mutation in ("missing", "unresolved", "spoofed_role", "scope", "null_contract"):
            invalid = copy.deepcopy(pack)
            entry = invalid["reviewed_ui_changes"][0]
            if mutation == "missing":
                entry["ui_change"]["design_authority_refs"] = []
            elif mutation == "unresolved":
                entry["ui_change"]["design_authority_refs"][0]["resolution_state"] = "unresolved"
            elif mutation == "spoofed_role":
                entry["role"] = "xy-qa"
            elif mutation == "null_contract":
                entry["ui_change"] = None
            else:
                invalid["task"]["audit_surfaces"] = ["ui"]
            with self.subTest(mutation=mutation), self.assertRaises(TaskGraphError):
                _execute("validate", invalid)
        invalid = copy.deepcopy(graph)
        invalid["tasks"][-1]["audit_surfaces"] = ["ui"]
        with self.assertRaises(TaskGraphError):
            export_task_pack(invalid, "qa")

    def test_non_ui_request_exports_empty_ui_scope(self):
        """无生产界面的请求不凭空制造设计依据或界面审计。"""
        from lib.task_graph_cli import export_task_pack
        graph = _builtin_standards_payload()
        writer = graph["tasks"][0]
        writer["blocks"] = ["qa"]
        graph["tasks"].append({"id": "qa", "request_id": writer["request_id"],
            "task_type": "qa", "depends_on": [writer["id"]], "blocks": [], "gates": [],
            "owned_paths": [], "semantic_locks": [], "state": "DECLARED"})
        v2_graph(graph)
        self.assertEqual([], export_task_pack(graph, "qa")["reviewed_ui_changes"])
        # 非生产审计可包含无障碍审计面，不能由表面名称推断出生产 UI 合同。
        pack = export_task_pack(graph, "qa")
        pack["task"]["audit_surfaces"] = ["accessibility"]
        pack.pop("reviewed_ui_changes")
        from lib.task_graph_cli import _execute
        self.assertEqual({"status": "valid"}, _execute("validate", pack))


class BuiltinSourceContractTest(unittest.TestCase):
    def invoke(self, payload):
        cli = Path(__file__).resolve().parents[1] / "lib/task_graph_cli.py"
        return subprocess.run([sys.executable, str(cli), "validate"], input=json.dumps(v2_graph(payload)),
                              text=True, capture_output=True, check=False)

    def test_builtin_and_project_supplements_validate_in_current_v2_graph(self):
        from tests.test_scheduler_boundaries import _writer_payload
        for payload in (_builtin_standards_payload(), _builtin_standards_payload(".agent-workflow/"), _writer_payload()):
            result = self.invoke(payload)
            self.assertEqual(0, result.returncode, result.stdout + result.stderr)

    def test_project_specialist_cannot_replace_general_or_builtin_engineering_floor(self):
        payload = _builtin_standards_payload()
        standards = payload["standards_contract"]
        project = {"path": "docs/standards/BACKEND.md", "domain": "engineering", "content_fingerprint": "b" * 64, "rule_ids": ["eng-specific"]}
        standards.update(index_fingerprint="a" * 64, required_engineering_rule_ids=["eng-specific"])
        original = payload["tasks"][0]["controlled_document_access"]["documents"][0]
        index = {**original, "path": standards["index_path"], "content_fingerprint": "a" * 64, "rule_ids": []}
        payload["tasks"][0]["controlled_document_access"]["documents"] = [index, {**original, **{key: value for key, value in project.items() if key != "domain"}}]
        standards["leaves"].append(project)
        result = self.invoke(payload)
        self.assertNotEqual(0, result.returncode)
        self.assertIn("selected builtin engineering baseline", result.stderr)
        # 2.0项目叶只能补充，删除内置来源后即使项目规则完整也不能替代底线。
        standards["leaves"] = [project]
        result = self.invoke(payload)
        self.assertNotEqual(0, result.returncode)
        self.assertIn("builtin engineering baseline", result.stderr)

    def test_builtin_sources_reject_stale_ids_wrong_domains_and_missing_path_coverage(self):
        for mutation, message in (("stale", "fingerprint is stale"), ("unknown-id", "unknown rule"),
                                  ("wrong-domain", "direct design"), ("path-coverage", "do not cover"),
                                  ("skip", "must not skip"), ("native-copy", "exact builtin source"),
                                  ("native-root", "exact builtin source")):
            payload = _builtin_standards_payload()
            leaf = payload["standards_contract"]["leaves"][0]
            document = payload["tasks"][0]["controlled_document_access"]["documents"][0]
            if mutation == "stale":
                leaf["content_fingerprint"] = document["content_fingerprint"] = "a" * 64
            elif mutation == "unknown-id":
                leaf["rule_ids"] = ["eng-does-not-exist"]
            elif mutation == "wrong-domain":
                leaf["domain"] = "design"
            elif mutation == "path-coverage":
                document["applies_to"] = ["other"]
            elif mutation == "skip":
                document["mode"] = "skip"
            else:
                leaf["path"] = document["path"] = ".agents/skills/xy-code-standards/references/rules.md"
                if mutation == "native-root":
                    payload["standards_contract"]["root"] = leaf["path"].rsplit("/", 1)[0]
                    payload["standards_contract"]["index_fingerprint"] = "b" * 64
            with self.subTest(mutation=mutation):
                result = self.invoke(payload)
                self.assertNotEqual(0, result.returncode)
                self.assertIn(message, result.stderr)


class TaskGraphTest(unittest.TestCase):
    def test_one_qa_declaration_per_request_includes_pending_active_and_historical_reviewers(self) -> None:
        """唯一Reviewer属于请求合同，空路径/锁与旧实例失效都不能授权另一个QA声明。"""
        for state in ("DECLARED", "RUNNING", "QA", "QA_PASSED", "FAILED"):
            tasks = [Task("original-qa", "request-a", task_type="qa", state=state),
                     Task("second-qa", "request-a", task_type="qa")]
            with self.subTest(state=state), self.assertRaisesRegex(TaskGraphError, "one QA task per request"):
                validate_graph(tasks)
        # 同一个Reviewer的后续状态仍只有一个QA节点；不同请求独立选择其Reviewer。
        validate_graph([Task("original-qa", "request-a", task_type="qa", state="QA"),
                        Task("independent-qa", "request-b", task_type="qa")])

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
            source.write_text(json.dumps(with_builtin_standards(v2_graph(payload))), encoding="utf-8")
            result = subprocess.run(
                [sys.executable, str(cli), "validate", "--input", str(source)],
                text=True,
                capture_output=True,
                check=False,
            )
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)

        # 2.0内置规则是唯一通用底线。项目规则可在GENERAL或专项叶补充，不能强制
        # 一个空GENERAL作为兼容门禁；移到专项叶后仍保留当前真实内置读取来源。
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
        self.assertEqual(0, rejected.returncode, rejected.stderr)

        # 真实拒绝的是删除内置来源，即使项目补充叶完整也不能替代。
        missing_baseline_contract = json.loads(json.dumps(omitted_baseline))
        missing_baseline_contract["standards_contract"]["leaves"] = [
            leaf
            for leaf in missing_baseline_contract["standards_contract"]["leaves"]
            if not leaf["path"].startswith("platforms/")
        ]
        missing_baseline_contract["tasks"][0]["controlled_document_access"]["documents"] = [
            document for document in missing_baseline_contract["tasks"][0]["controlled_document_access"]["documents"]
            if not document["path"].startswith("platforms/")]
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
        self.assertIn("builtin engineering baseline", rejected.stderr)

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
        # 非注册文档携带规则编号会在来源检查处提前失败，不能再作为普通文档绕过规范。
        self.assertIn("standards rule source is absent from contract", wrong_path.stderr)

        stale_task = json.loads(json.dumps(task))
        stale_task["controlled_document_access"]["documents"][0][
            "content_fingerprint"
        ] = "f" * 64
        stale = invoke(stale_task)
        self.assertEqual(2, stale.returncode)
        self.assertIn("engineering standards leaf fingerprint is stale", stale.stderr)

        incomplete_scope_task = json.loads(json.dumps(task))
        incomplete_scope_task["owned_paths"].append("services/model.py")
        # 显式冻结原范围的内置引用，再扩大写范围；基础fixture补源助手不能把这条
        # 故意留下的实际读取缺口补成覆盖完整，从而掩盖运行时边界。
        builtin_document = _builtin_standards_payload()["tasks"][0]["controlled_document_access"]["documents"][0]
        incomplete_scope_task["controlled_document_access"]["documents"].append({
            **builtin_document, "applies_to": list(task["owned_paths"]),
        })
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
