from __future__ import annotations

import copy
import json
import hashlib
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from tests.test_scheduler_boundaries import v2_task


def qa_task_pack(host: str = "codex") -> dict:
    """创建自包含当前Reviewer包；身份是测试数据，不声称真实原生执行。"""
    return {"schema_version": 2, "standards_contract": {
                "index_path": "docs/STANDARDS.md", "root": "docs/standards", "index_fingerprint": "e" * 64,
                "required_engineering_rule_ids": ["eng-source-boundary"], "required_design_rule_ids": [],
                "leaves": [{"path": "docs/standards/GENERAL.md", "domain": "engineering",
                            "content_fingerprint": "f" * 64, "rule_ids": ["eng-source-boundary"]}], "protected_paths": [],
            },
            "approved_gates": [], "task": v2_task({
                "id": "qa", "request_id": "qa-request", "task_type": "qa", "state": "QA",
                "depends_on": [], "blocks": [], "gates": [], "owned_paths": [], "semantic_locks": [],
                "agent_ref": {"host": host, "agent_id": "fixture-reviewer"},
            })}


def handoff_ref(pack: dict, body: bytes) -> dict:
    task = pack["task"]
    return {"request_id": task["request_id"], "task_id": task["id"], "agent_alias": task["agent_alias"],
            "agent_ref": task["agent_ref"], "task_pack_sha256": hashlib.sha256(body).hexdigest()}


class QAHandoffValidationTest(unittest.TestCase):
    """验证 QA PASS 必须覆盖固定 diff 与独立识别出的适用规范。"""

    def setUp(self) -> None:
        self.cli = Path(__file__).resolve().parents[1] / "lib/delivery/qa_handoff_cli.py"
        self.payload = {
            "schema_version": 2,
            "skill_evidence": {"skills_used": ["xy-qa-review"], "unavailable_required_skills": [],
                               "uncovered_audit_surfaces": []},
            "audit_result": "PASS",
            "review_method": {
                "selected": "internal-xy-qa-procedure",
                "external_skill": None,
                "capability_evidence": [
                    "capability:native-review-unavailable",
                    "capability:installed-review-skill-unavailable",
                ],
                "fallback_reason": "missing",
                "scope_ref": {
                    "repositories": [
                        {
                            "path": ".",
                            "base_revision": "base-revision",
                            "head_revision": "head-revision",
                            "diff_fingerprint": "d" * 64,
                            "changed_paths": ["services/api.py"],
                        }
                    ]
                },
            },
            "standards_policy_coverage": {
                "index_path": "docs/STANDARDS.md",
                "root": "docs/standards",
                "index_fingerprint": "e" * 64,
                "task_pack_rule_ids": ["eng-source-boundary"],
                "required_engineering_rule_ids": ["eng-source-boundary"],
                "required_design_rule_ids": [],
                "path_checks": [
                    {
                        "path": "services/api.py",
                        "applicable_rule_ids": ["eng-source-boundary"],
                        "reason": "该文件属于生产源码",
                    }
                ],
                "rule_checks": [
                    {
                        "rule_id": "eng-source-boundary",
                        "source_path": "docs/standards/GENERAL.md",
                        "source_fingerprint": "f" * 64,
                        "source_anchor": "project-specific-hard-rules",
                        "domain": "engineering",
                        "severity": "hard",
                        "disposition": "pass",
                        "affected_paths": ["services/api.py"],
                        "evidence_refs": ["diff:services/api.py"],
                        "not_applicable_reason": "",
                        "exception_ref": "",
                    }
                ],
            },
        }
        self.task_pack = qa_task_pack()
        self.task_pack_body = json.dumps(self.task_pack, ensure_ascii=False).encode("utf-8")
        self.payload["handoff_ref"] = handoff_ref(self.task_pack, self.task_pack_body)

    def invoke(self, payload: dict[str, object] | bytes, *, task_pack_body: bytes | None = None,
               env: dict[str, str] | None = None, stdin: bool = False,
               command: str = "validate", host: str | None = None) -> subprocess.CompletedProcess[str]:
        with tempfile.TemporaryDirectory(prefix="qa-handoff-") as raw:
            root = Path(raw).resolve()
            current_pack = root / "qa-task-pack.json"
            current_pack.write_bytes(self.task_pack_body if task_pack_body is None else task_pack_body)
            body = payload if isinstance(payload, bytes) else json.dumps(payload, ensure_ascii=False).encode("utf-8")
            args = [sys.executable, str(self.cli), command, "--task-pack", str(current_pack)]
            if host is not None:
                args.extend(("--host", host))
            if not stdin:
                source = root / "handoff.json"
                source.write_bytes(body)
                args.extend(("--input", str(source)))
            result = subprocess.run(args, input=body if stdin else None, capture_output=True, check=False, env=env)
            return subprocess.CompletedProcess(args, result.returncode, result.stdout.decode(), result.stderr.decode())


    def test_complete_standards_coverage_can_pass(self) -> None:
        for stdin in (False, True):
            with self.subTest(stdin=stdin):
                result = self.invoke(self.payload, stdin=stdin)
                self.assertEqual(0, result.returncode, result.stdout + result.stderr)
                self.assertEqual({"status": "valid"}, json.loads(result.stdout))

    def test_light_solution_review_checks_authoritative_writer_and_legacy_gate(self):
        """Light 单包直接核对已批准正文；旧记录无来源时只展示真实的批准门。"""
        from lib.solution_confirmation import bind_decisions
        from lib.task_graph_cli import _verify_solution_scope, reviewed_solutions, export_task_pack
        from tests.test_task_graph_records import graph
        source = export_task_pack(graph(), "api")
        writer = source["task"]
        writer.update(workflow_level="Light", blocks=[], depends_on=[],
                      solution_decisions=[{"id": "retry", "content": "失败时由用户重试"}])
        bind_decisions(writer)
        gate = next(gate for gate in writer["gates"] if gate.startswith("solution_approved:"))
        source["approved_gates"].append(gate)
        pack = qa_task_pack()
        pack["task"].update(workflow_level="Light", request_id=writer["request_id"])
        pack["approved_gates"] = [gate]
        pack["reviewed_solution_decisions"] = reviewed_solutions([writer], source)
        with tempfile.TemporaryDirectory() as fixture:
            directory = Path(fixture).resolve()
            writer_file, qa_file = directory / "writer.json", directory / "reviewer.json"
            writer_file.write_text(json.dumps(source))
            qa_file.write_text(json.dumps({key: value for key, value in pack.items() if key != "reviewed_solution_decisions"}))
            result = subprocess.run([sys.executable, str(self.cli.parents[1] / "task_graph_cli.py"), "task",
                "--input", str(qa_file), "--source", str(writer_file)], capture_output=True, text=True)
            self.assertEqual(0, result.returncode, result.stderr)
            self.assertEqual(pack["reviewed_solution_decisions"], json.loads(result.stdout)["reviewed_solution_decisions"])
        self.assertNotIn("source_ref", pack["reviewed_solution_decisions"][0])
        _verify_solution_scope(pack, source)
        stamped = copy.deepcopy(pack)
        stamped["solution_approval_sources"] = {gate: "fixture:wrong-reply"}
        stamped["reviewed_solution_decisions"][0]["source_ref"] = "fixture:wrong-reply"
        with self.assertRaisesRegex(ValueError, "authoritative"):
            _verify_solution_scope(stamped, source)
        del pack["reviewed_solution_decisions"]
        with self.assertRaisesRegex(ValueError, "authoritative"):
            _verify_solution_scope(pack, source)

    def test_current_pack_requires_exact_skill_ids_and_preserves_optional_coverage_gap(self) -> None:
        pack = self.task_pack
        pack["task"].update(required_skills=["xy-mobile-ui"], audit_surfaces=["standards-conformance", "concurrency"])
        body = json.dumps(pack).encode("utf-8")
        self.payload["handoff_ref"] = handoff_ref(pack, body)
        evidence = self.payload["skill_evidence"]
        for substitute in ([], ["xy-mobile-ui-extra"], [" xy-mobile-ui "], ["xy-workflow:xy-mobile-ui"]):
            with self.subTest(substitute=substitute):
                evidence["skills_used"] = ["xy-qa-review", *substitute]
                result = self.invoke(self.payload, task_pack_body=body)
                self.assertEqual(2, result.returncode)
                self.assertIn("required Skill(s): xy-mobile-ui", result.stderr)

        evidence["skills_used"] = ["xy-qa-review", "xy-mobile-ui"]
        evidence["uncovered_audit_surfaces"] = ["concurrency"]
        result = self.invoke(self.payload, task_pack_body=body)
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        evidence["uncovered_audit_surfaces"].append("standards-conformance")
        result = self.invoke(self.payload, task_pack_body=body)
        self.assertEqual(2, result.returncode)
        self.assertIn("mandatory audit surface(s) uncovered: standards-conformance", result.stderr)

    def test_production_ui_pack_excludes_pass_with_uncovered_ui_or_accessibility(self) -> None:
        """使用正式 Writer 投影和完整规则覆盖，排除 QA 任务自身 non_ui 标签造成的绕过。"""
        from lib.task_graph_cli import export_task_pack
        from tests import test_foundation_qa as fixtures

        with tempfile.TemporaryDirectory(prefix="qa-ui-surfaces-") as raw:
            root = Path(raw).resolve()
            with fixtures.working_root(root):
                graph = fixtures.graph(root)
                graph["tasks"][2].update(state="QA", agent_ref={"host": "codex", "agent_id": "fixture-reviewer"})
                pack = export_task_pack(graph, "qa")
                body = json.dumps(pack).encode("utf-8")
                payload = fixtures.handoff(pack, body)
                result = self.invoke(payload, task_pack_body=body)
                self.assertEqual(0, result.returncode, result.stdout + result.stderr)
                for surface in ("ui", "accessibility"):
                    with self.subTest(surface=surface):
                        payload["skill_evidence"]["uncovered_audit_surfaces"] = [surface]
                        result = self.invoke(payload, task_pack_body=body)
                        self.assertEqual(2, result.returncode)
                        self.assertIn(f"mandatory audit surface(s) uncovered: {surface}", result.stderr)

    def test_v2_result_cannot_reuse_old_pass_identity_or_reencoded_pack(self):
        """每个身份维度和真正交接包的字节都必须匹配，FAIL也不能换Reviewer。"""
        for outcome in ("PASS", "FAIL"):
            for field, value in (("request_id", "old-request"), ("task_id", "other-task"),
                                 ("agent_alias", "other-alias"), ("task_pack_sha256", "0" * 64),
                                 ("agent_ref", {"host": "codex", "agent_id": "replacement-reviewer"})):
                candidate = json.loads(json.dumps(self.payload))
                candidate["audit_result"] = outcome
                candidate["handoff_ref"][field] = value
                with self.subTest(outcome=outcome, field=field):
                    result = self.invoke(candidate)
                    self.assertEqual(2, result.returncode)
                    self.assertIn("handoff_ref", result.stderr)
        reencoded = json.dumps(self.task_pack, indent=2).encode("utf-8")
        self.assertEqual(2, self.invoke(self.payload, task_pack_body=reencoded).returncode)
        for version in (None, 1, True, "2"):
            candidate = {**self.payload, "schema_version": version}
            self.assertEqual(2, self.invoke(candidate).returncode)

    def builtin_payload(self):
        payload = json.loads(json.dumps(self.payload))
        path = "platforms/shared/skills/xy-code-standards/references/rules.md"
        digest = hashlib.sha256((self.cli.parents[2] / path).read_bytes()).hexdigest()
        coverage = payload["standards_policy_coverage"]
        coverage.update(index_fingerprint=None, task_pack_rule_ids=["eng-common-005"], required_engineering_rule_ids=["eng-common-005"])
        coverage["path_checks"][0]["applicable_rule_ids"] = ["eng-common-005"]
        coverage["rule_checks"][0].update(rule_id="eng-common-005", source_path=path, source_fingerprint=digest, source_anchor="配置、错误和维护")
        self.task_pack["standards_contract"].update(index_fingerprint=None, required_engineering_rule_ids=["eng-common-005"],
            leaves=[{"path": path, "domain": "engineering", "content_fingerprint": digest, "rule_ids": ["eng-common-005"]}])
        self.task_pack_body = json.dumps(self.task_pack, ensure_ascii=False).encode("utf-8")
        payload["handoff_ref"] = handoff_ref(self.task_pack, self.task_pack_body)
        return payload

    def test_current_pack_prevents_stale_standards_or_inactive_reviewer(self):
        candidate = json.loads(json.dumps(self.payload))
        candidate["standards_policy_coverage"]["rule_checks"][0]["source_fingerprint"] = "0" * 64
        result = self.invoke(candidate)
        self.assertEqual(2, result.returncode)
        self.assertIn("current task pack", result.stderr)
        for state, retired in (("DECLARED", False), ("QA_PASSED", False), ("QA", True)):
            pack = json.loads(self.task_pack_body)
            pack["task"].update(state=state, agent_retired=retired)
            body = json.dumps(pack).encode("utf-8")
            candidate = {**self.payload, "handoff_ref": handoff_ref(pack, body)}
            with self.subTest(state=state, retired=retired):
                self.assertEqual(2, self.invoke(candidate, task_pack_body=body).returncode)

    def test_builtin_coverage_accepts_missing_project_index_and_exact_installed_source(self):
        payload = self.builtin_payload()
        for prefix in ("", ".agent-workflow/"):
            candidate = json.loads(json.dumps(payload))
            candidate["standards_policy_coverage"]["rule_checks"][0]["source_path"] = prefix + payload["standards_policy_coverage"]["rule_checks"][0]["source_path"]
            result = self.invoke(candidate)
            self.assertEqual(0, result.returncode, result.stdout + result.stderr)

    def test_builtin_rule_identity_severity_and_fingerprint_cannot_be_forged(self):
        for field, value, message in (("severity", "advisory", "ID/severity"),
                                      ("source_fingerprint", "a" * 64, "fingerprint is stale"),
                                      ("rule_id", "eng-does-not-exist", "ID/severity"),
                                      ("domain", "design", "direct design"),
                                      ("source_path", ".claude/skills/xy-code-standards/references/rules.md", "direct engineering")):
            payload = self.builtin_payload()
            payload["standards_policy_coverage"]["rule_checks"][0][field] = value
            with self.subTest(field=field):
                result = self.invoke(payload)
                self.assertNotEqual(0, result.returncode)
                self.assertIn(message, result.stderr)

    def test_missing_project_index_cannot_hide_project_rule_sources(self):
        payload = json.loads(json.dumps(self.payload))
        payload["standards_policy_coverage"]["index_fingerprint"] = None
        result = self.invoke(payload)
        self.assertNotEqual(0, result.returncode)
        self.assertIn("no project standards rule sources", result.stderr)

    def test_native_skill_copy_cannot_become_project_authority_with_forged_root(self):
        payload = self.builtin_payload()
        coverage = payload["standards_policy_coverage"]
        path = ".claude/skills/xy-code-standards/references/rules.md"
        coverage.update(root=path.rsplit("/", 1)[0], index_fingerprint="a" * 64)
        coverage["rule_checks"][0]["source_path"] = path
        result = self.invoke(payload)
        self.assertNotEqual(0, result.returncode)
        self.assertIn("direct engineering", result.stderr)

    def test_legal_review_methods_preserve_pass_and_fail_handoffs(self) -> None:
        """三种方法都可交接；FAIL 表示真实发现，不需要为了换方法而伪造技术故障。"""

        methods = (
            {
                "selected": "host-native-review",
                "external_skill": None,
                "capability_evidence": ["capability:read-only-native-review"],
                "fallback_reason": None,
            },
            {
                "selected": "installed-code-review-skill",
                "external_skill": "requesting-code-review/code-reviewer.md",
                "capability_evidence": [
                    "capability:native-review-unavailable",
                    "capability:installed-read-only-review-prompt",
                ],
                "fallback_reason": "missing",
            },
            {key: value for key, value in self.payload["review_method"].items() if key != "scope_ref"},
        )
        for method in methods:
            for outcome in ("PASS", "FAIL"):
                with self.subTest(method=method["selected"], outcome=outcome):
                    payload = json.loads(json.dumps(self.payload))
                    payload["audit_result"] = outcome
                    payload["review_method"].update(method)
                    if outcome == "FAIL":
                        payload["standards_policy_coverage"]["rule_checks"][0]["disposition"] = "fail"
                    result = self.invoke(payload)
                    self.assertEqual(0, result.returncode, result.stdout + result.stderr)

    def test_missing_review_method_fields_are_rejected(self) -> None:
        """显式 null 与字段缺失不同：不能用未记录的方法证据接受历史不完整 PASS。"""

        for field in ("selected", "external_skill", "capability_evidence", "fallback_reason", "scope_ref"):
            with self.subTest(field=field):
                payload = json.loads(json.dumps(self.payload))
                del payload["review_method"][field]
                result = self.invoke(payload)
                self.assertEqual(2, result.returncode, result.stdout + result.stderr)
                self.assertIn("review_method", result.stderr)
                self.assertIn(field, result.stderr)

    def test_invalid_review_method_values_are_rejected(self) -> None:
        """从真实 CLI 检查非法 JSON 类型、空证据及去空白后的重复引用，避免只测私有函数。"""

        invalid_values = {
            "selected": ("unsupported-review-method", "", None, [], True),
            "capability_evidence": (None, {}, "capability:one", [], [""], [7], ["capability:one", " capability:one "]),
            "fallback_reason": (None, "", "findings", "FAIL", [], True),
            "external_skill": ("unexpected-skill", [], False),
        }
        for field, values in invalid_values.items():
            for value in values:
                with self.subTest(field=field, value=value):
                    payload = json.loads(json.dumps(self.payload))
                    payload["review_method"][field] = value
                    result = self.invoke(payload)
                    self.assertEqual(2, result.returncode, result.stdout + result.stderr)
                    self.assertNotIn("Traceback", result.stderr)
                    self.assertIn("review_method." + field, result.stderr)

    def test_method_skill_and_fallback_reason_must_agree(self) -> None:
        """原生无回退、外部方法有技能、内部无外部技能，三者不能互相冒用身份。"""

        cases = (
            ("host-native-review", None, "missing"),
            ("host-native-review", "requesting-code-review", None),
            ("installed-code-review-skill", None, "missing"),
            ("installed-code-review-skill", "", "missing"),
            ("installed-code-review-skill", [], "missing"),
            ("installed-code-review-skill", "requesting-code-review", None),
            ("internal-xy-qa-procedure", "requesting-code-review", "missing"),
        )
        for selected, external_skill, fallback_reason in cases:
            for outcome in ("PASS", "FAIL"):
                with self.subTest(selected=selected, skill=external_skill, reason=fallback_reason, outcome=outcome):
                    payload = json.loads(json.dumps(self.payload))
                    payload["audit_result"] = outcome
                    payload["review_method"].update(
                        selected=selected, external_skill=external_skill, fallback_reason=fallback_reason
                    )
                    result = self.invoke(payload)
                    self.assertEqual(2, result.returncode, result.stdout + result.stderr)
                    self.assertNotIn("Traceback", result.stderr)
                    self.assertIn("review_method.", result.stderr)

    def test_missing_required_rule_blocks_pass(self) -> None:
        payload = json.loads(json.dumps(self.payload))
        payload["standards_policy_coverage"]["rule_checks"] = []
        result = self.invoke(payload)
        self.assertEqual(2, result.returncode)
        self.assertIn("missing required standards rule", result.stderr)

    def test_unclassified_changed_path_blocks_pass(self) -> None:
        payload = json.loads(json.dumps(self.payload))
        payload["review_method"]["scope_ref"]["repositories"][0][
            "changed_paths"
        ].append("services/model.py")
        result = self.invoke(payload)
        self.assertEqual(2, result.returncode)
        self.assertIn("path_checks must classify every changed path", result.stderr)

    def test_hard_rule_failure_cannot_be_reported_as_pass(self) -> None:
        payload = json.loads(json.dumps(self.payload))
        payload["standards_policy_coverage"]["rule_checks"][0][
            "disposition"
        ] = "fail"
        result = self.invoke(payload)
        self.assertEqual(2, result.returncode)
        self.assertIn("hard standards rule failure", result.stderr)

    def test_pass_without_rule_evidence_is_rejected(self) -> None:
        payload = json.loads(json.dumps(self.payload))
        payload["standards_policy_coverage"]["rule_checks"][0][
            "evidence_refs"
        ] = []
        result = self.invoke(payload)
        self.assertEqual(2, result.returncode)
        self.assertIn("requires evidence_refs", result.stderr)

    def test_not_applicable_requires_a_reason_and_no_path_mapping(self) -> None:
        payload = json.loads(json.dumps(self.payload))
        check = payload["standards_policy_coverage"]["rule_checks"][0]
        check["disposition"] = "not_applicable"
        check["affected_paths"] = []
        check["evidence_refs"] = []
        payload["standards_policy_coverage"]["path_checks"][0][
            "applicable_rule_ids"
        ] = []
        result = self.invoke(payload)
        self.assertEqual(2, result.returncode)
        self.assertIn("not_applicable_reason", result.stderr)

    def test_nested_repository_scope_must_cover_policy_paths(self) -> None:
        payload = json.loads(json.dumps(self.payload))
        payload["review_method"]["scope_ref"]["repositories"] = [
            {
                "path": "ragflow",
                "base_revision": "e35860ad7",
                "head_revision": "8a36e88b9",
                "diff_fingerprint": "a" * 64,
                "changed_paths": ["ragflow/api/apps/provider_api.py"],
            }
        ]
        coverage = payload["standards_policy_coverage"]
        coverage["path_checks"][0]["path"] = "ragflow/api/apps/provider_api.py"
        coverage["rule_checks"][0]["affected_paths"] = [
            "ragflow/api/apps/provider_api.py"
        ]
        result = self.invoke(payload)
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)

        payload["review_method"]["scope_ref"]["repositories"][0][
            "changed_paths"
        ] = ["ragflow/api/apps/other.py"]
        result = self.invoke(payload)
        self.assertEqual(2, result.returncode)
        self.assertIn("affected_paths contains paths outside fixed scope", result.stderr)

    def test_qa_discovered_rule_omitted_by_pm_cannot_pass(self) -> None:
        """QA 可以补读规则证明 PM 漏选，但不能把错误任务包静默修成 PASS。"""

        payload = json.loads(json.dumps(self.payload))
        coverage = payload["standards_policy_coverage"]
        # 冻结包确实漏派了第二条规则，而非让回执自行删去已有规则假冒缺漏。
        coverage["required_engineering_rule_ids"].append("eng-service-contract")
        coverage["path_checks"][0]["applicable_rule_ids"].append("eng-service-contract")
        coverage["rule_checks"].append({**coverage["rule_checks"][0], "rule_id": "eng-service-contract"})
        result = self.invoke(payload)
        self.assertEqual(2, result.returncode)
        self.assertIn("omitted from the PM Task Pack", result.stderr)

        # 相同证据作为 FAIL 交回 PM 是合法的，因为它准确暴露了编排缺口。
        payload["audit_result"] = "FAIL"
        result = self.invoke(payload)
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)

    def test_legacy_fail_requires_actionable_mandatory_evidence(self) -> None:
        self.payload["audit_result"] = "FAIL"
        self.payload["standards_policy_coverage"]["task_pack_rule_ids"] = []
        result = self.invoke(self.payload)
        self.assertEqual(2, result.returncode)
        self.assertIn("FAIL requires actionable", result.stderr)

        # 已有的强制规则、适用路径及直接证据足以定位问题，无需补造结构化发现。
        self.payload["standards_policy_coverage"]["rule_checks"][0]["disposition"] = "fail"
        result = self.invoke(self.payload)
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)


class QAComposeTest(unittest.TestCase):
    """直接运行命令行，将 Reviewer 判定回填为可再次 validate 的多仓回执。"""

    def setUp(self):
        self.fixture = QAHandoffValidationTest()
        self.fixture.setUp()
        self.pack = self.fixture.task_pack
        self.scope = copy.deepcopy(self.fixture.payload["review_method"]["scope_ref"])
        self.scope["repositories"].append({"path": "web", "base_revision": "web-base", "head_revision": "web-head",
                                           "diff_fingerprint": "a" * 64, "changed_paths": ["web/a.ts", "web/b.ts"]})
        self.pack["task"]["qa_scope_ref"] = self.scope
        contract = self.pack["standards_contract"]
        self.project_rules = ["eng-source-boundary", "eng-error-boundary"]
        contract["leaves"][0]["rule_ids"] = [*self.project_rules, "eng-not-used"]
        self.builtin_path = "platforms/shared/skills/xy-code-standards/references/rules.md"
        fingerprint = hashlib.sha256((self.fixture.cli.parents[2] / self.builtin_path).read_bytes()).hexdigest()
        contract["leaves"].append({"domain": "engineering", "path": self.builtin_path,
                                   "content_fingerprint": fingerprint, "rule_ids": ["eng-common-005"]})
        contract["required_engineering_rule_ids"] = [*self.project_rules, "eng-not-used", "eng-common-005"]
        self.body = json.dumps(self.pack, ensure_ascii=False, indent=2).encode()
        self.decisions = {
            "task_pack_sha256": hashlib.sha256(self.body).hexdigest(), "audit_result": "PASS",
            "review_method": {"selected": "host-native-review", "capability_evidence": ["logs:host-review"]},
            "skill_evidence": self.fixture.payload["skill_evidence"],
            "review_details": {"findings": [], "verification": [
                {"command": "fixture-check", "exit_code": 0, "log_ref": "logs:complete-fixture"}]},
            "path_groups": [
                {"paths": ["web/a.ts", "web/b.ts"], "rule_ids": self.project_rules, "reason": "两个页面处理相同错误"},
                {"paths": ["services/api.py"], "rule_ids": ["eng-common-005"], "reason": "API 的配置处理"},
            ],
            "rule_groups": [
                {"rule_ids": self.project_rules, "severity": "hard", "disposition": "pass",
                 "evidence_refs": ["diff:web/a.ts", "diff:web/b.ts"]},
                {"rule_ids": ["eng-common-005"], "disposition": "pass", "evidence_refs": ["diff:services/api.py"]},
                {"rule_ids": ["eng-not-used"], "severity": "advisory", "disposition": "not_applicable",
                 "not_applicable_reason": "固定范围未调用该接口", "evidence_refs": []},
            ],
        }

    def compose(self, decisions, *, body=None, stdin=False):
        return self.fixture.invoke(decisions, task_pack_body=self.body if body is None else body,
                                   command="compose", stdin=stdin)

    def assert_rejected(self, result, error):
        self.assertEqual(2, result.returncode, result.stdout + result.stderr)
        self.assertEqual("", result.stdout)
        self.assertIn(error, json.loads(result.stderr)["error"])

    def test_compose_validates_complete_grouped_multirepo_receipt_and_binds_original_bytes(self):
        for stdin in (False, True):
            with self.subTest(stdin=stdin):
                result = self.compose(self.decisions, stdin=stdin)
                self.assertEqual(0, result.returncode, result.stderr)
                receipt = json.loads(result.stdout)
                self.assertEqual(handoff_ref(self.pack, self.body), receipt["handoff_ref"])
                self.assertEqual(self.scope, receipt["review_method"]["scope_ref"])
                self.assertEqual(self.decisions["review_details"], receipt["review_details"])
                self.assertEqual(self.decisions["skill_evidence"], receipt["skill_evidence"])
                coverage = receipt["standards_policy_coverage"]
                checks = {check["rule_id"]: check for check in coverage["rule_checks"]}
                self.assertEqual(sorted(checks), sorted(coverage["task_pack_rule_ids"]))
                for rule in self.project_rules:
                    self.assertEqual(["web/a.ts", "web/b.ts"], checks[rule]["affected_paths"])
                    self.assertEqual(rule, checks[rule]["source_anchor"])
                    self.assertEqual("f" * 64, checks[rule]["source_fingerprint"])
                self.assertEqual(self.builtin_path, checks["eng-common-005"]["source_path"])
                self.assertEqual("hard", checks["eng-common-005"]["severity"])
                self.assertEqual([], checks["eng-not-used"]["affected_paths"])
                self.assertEqual(3, len(coverage["path_checks"]))
                checked = self.fixture.invoke(result.stdout.encode(), task_pack_body=self.body)
                self.assertEqual({"status": "valid"}, json.loads(checked.stdout), checked.stderr)

    def test_missing_frozen_scope_requires_reviewer_scope_and_frozen_scope_cannot_be_replaced(self):
        changed_scope = copy.deepcopy(self.scope)
        changed_scope["repositories"][1]["head_revision"] = "different-head"
        self.decisions["review_method"]["scope_ref"] = changed_scope
        self.assert_rejected(self.compose(self.decisions), "qa_scope_ref")
        del self.pack["task"]["qa_scope_ref"]
        self.body = json.dumps(self.pack).encode()
        self.decisions["task_pack_sha256"] = hashlib.sha256(self.body).hexdigest()
        del self.decisions["review_method"]["scope_ref"]
        self.assert_rejected(self.compose(self.decisions), "scope_ref")
        self.decisions["review_method"]["scope_ref"] = self.scope
        result = self.compose(self.decisions)
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual(self.scope, json.loads(result.stdout)["review_method"]["scope_ref"])

    def test_all_receipt_commands_bind_the_complete_frozen_scope_including_array_order(self):
        baseline = self.compose(self.decisions)
        self.assertEqual(0, baseline.returncode, baseline.stderr)
        for mutate in (lambda repos: repos[1].update(head_revision="changed"),
                       lambda repos: repos[1].update(diff_fingerprint="b" * 64),
                       lambda repos: repos.reverse(),
                       lambda repos: repos[1]["changed_paths"].reverse()):
            # 使用同一合法结果，仅改一个冻结维度，覆盖完整回执直接校验、原生终端解包
            # 和 Reviewer 显式传入范围三种路径。所有命令均须在输出回执前拒绝。
            scope = copy.deepcopy(self.scope)
            mutate(scope["repositories"])
            decisions = copy.deepcopy(self.decisions)
            decisions["review_method"]["scope_ref"] = scope
            self.assert_rejected(self.compose(decisions), "qa_scope_ref")
            receipt = json.loads(baseline.stdout)
            receipt["review_method"]["scope_ref"] = scope
            for command, host in (("validate", None), ("extract", "codex")):
                with self.subTest(command=command, scope=scope):
                    self.assert_rejected(self.fixture.invoke(receipt, task_pack_body=self.body,
                                                             command=command, host=host), "qa_scope_ref")

    def test_compose_rejects_stale_decisions_missing_judgments_and_conflicting_evidence(self):
        # 仅重新编码就已是另一份包。同请求换 Reviewer 也不能把旧结论直接重绑为 PASS。
        self.assert_rejected(self.compose(self.decisions, body=json.dumps(self.pack).encode()), "task_pack_sha256")
        self.pack["task"]["agent_ref"]["agent_id"] = "replacement"
        self.assert_rejected(self.compose(self.decisions, body=json.dumps(self.pack).encode()), "task_pack_sha256")
        mutations = [
            (lambda d: d.pop("task_pack_sha256"), "task_pack_sha256"),
            (lambda d: d.pop("audit_result"), "audit_result"),
            (lambda d: d.pop("skill_evidence"), "skill_evidence"),
            (lambda d: d["review_method"].pop("capability_evidence"), "capability_evidence"),
            (lambda d: d["review_method"].update(selected="internal-xy-qa-procedure"), "fallback_reason"),
            (lambda d: d["rule_groups"].pop(), "missing required standards rule"),
            (lambda d: d["rule_groups"][0].pop("disposition"), "disposition"),
            (lambda d: d["rule_groups"][0].pop("severity"), "severity"),
            (lambda d: d["rule_groups"][0].update(evidence_refs=[]), "evidence_refs"),
            (lambda d: d["rule_groups"][1].update(severity="advisory"), "ID/severity"),
            (lambda d: d["rule_groups"][0].update(disposition="fail"), "hard standards rule failure"),
            (lambda d: d["rule_groups"][-1].pop("not_applicable_reason"), "not_applicable_reason"),
            (lambda d: d["rule_groups"].append(d["rule_groups"][0]), "duplicate rule IDs"),
            (lambda d: d["path_groups"][0]["paths"].pop(), "classify every changed path"),
            (lambda d: d["path_groups"][0]["paths"].append("other/a.ts"), "outside fixed scope"),
            (lambda d: d["path_groups"].append(d["path_groups"][0]), "duplicates"),
            (lambda d: d["path_groups"][0].update(rule_ids=["*"]), "invalid stable rule ID"),
            (lambda d: d.update(handoff_ref={}), "compose must contain exactly"),
        ]
        for mutate, error in mutations:
            with self.subTest(error=error):
                decisions = copy.deepcopy(self.decisions)
                mutate(decisions)
                self.assert_rejected(self.compose(decisions), error)

    def test_undispatched_applicable_rule_allows_actionable_fail_only(self):
        omitted = "eng-omitted"
        self.decisions["path_groups"][1]["rule_ids"].append(omitted)
        self.decisions["rule_groups"].append({
            "rule_ids": [omitted], "source_path": "docs/standards/GENERAL.md", "source_fingerprint": "f" * 64,
            "severity": "hard", "disposition": "pass", "evidence_refs": ["diff:services/api.py"],
        })
        self.assert_rejected(self.compose(self.decisions), "omitted from the PM Task Pack")
        self.decisions["audit_result"] = "FAIL"
        self.assert_rejected(self.compose(self.decisions), "actionable blocking")
        self.decisions["review_details"]["findings"] = [
            {"severity": "P1", "blocking": True, "detail": "PM 漏派接口规则", "evidence_refs": ["spec:eng-omitted"],
             "owner_role": "pm", "next_step": "修正接口规则并刷新任务包"}]
        result = self.compose(self.decisions)
        self.assertEqual(0, result.returncode, result.stderr)
        receipt = json.loads(result.stdout)
        self.assertEqual("FAIL", receipt["audit_result"])
        self.assertNotIn(omitted, receipt["standards_policy_coverage"]["task_pack_rule_ids"])
        self.assertIn(omitted, receipt["standards_policy_coverage"]["required_engineering_rule_ids"])
        self.assertEqual({"status": "valid"}, json.loads(self.fixture.invoke(receipt, task_pack_body=self.body).stdout))
        # 对已展开结果只删汇总 ID，保留逐路径和逐规则的实审记录；手填结果和宿主
        # 解包都不能利用这份不完整汇总偷渡 PASS。合法 FAIL 仍保留真实漏派与返工依据。
        receipt["standards_policy_coverage"]["required_engineering_rule_ids"].remove(omitted)
        for command, host in (("validate", None), ("extract", "codex")):
            with self.subTest(command=command):
                failed = self.fixture.invoke(receipt, task_pack_body=self.body, command=command, host=host)
                self.assertEqual(0, failed.returncode, failed.stderr)
                forged = copy.deepcopy(receipt)
                forged["audit_result"] = "PASS"
                forged["review_details"]["findings"] = []
                result = self.fixture.invoke(forged, task_pack_body=self.body, command=command, host=host)
                self.assert_rejected(result, "omitted from the PM Task Pack")

    def test_group_expansion_cannot_emit_a_receipt_larger_than_the_input_limit(self):
        # 一份很短的规则列表会多次展开同一条长证据，失败时不输出任何局部回执。
        self.decisions["rule_groups"][0]["evidence_refs"] = ["x" * (2 * 1024 * 1024)]
        self.assert_rejected(self.compose(self.decisions), "4 MiB")

    def test_pack_cannot_supply_ambiguous_rule_metadata(self):
        # JSON 图的规则登记按领域索引，完整回执则按全局规则 ID 索引。重名时不能依
        # 叶子顺序取最后一项，否则同一份明确判定会意外通过另一个规则来源。
        self.pack["standards_contract"]["leaves"].insert(0, {
            "path": "docs/standards/DESIGN_TEST.md", "domain": "design", "content_fingerprint": "c" * 64,
            "rule_ids": ["eng-source-boundary"],
        })
        self.body = json.dumps(self.pack).encode()
        self.decisions["task_pack_sha256"] = hashlib.sha256(self.body).hexdigest()
        self.assert_rejected(self.compose(self.decisions), "多个来源")


class NativeQAHandoffTest(unittest.TestCase):
    """从真实 CLI 验证原生终端合同；封装夹具不冒充真实模型执行证据。"""

    def setUp(self) -> None:
        fixture = QAHandoffValidationTest()
        fixture.setUp()
        self.cli = fixture.cli
        self.payload = fixture.payload
        temporary = tempfile.TemporaryDirectory(prefix="qa-current-pack-")
        self.addCleanup(temporary.cleanup)
        self.pack_file = Path(temporary.name).resolve() / "qa-pack.json"
        self.pack_file.write_bytes(fixture.task_pack_body)
        self.payload["skill_evidence"] = {
            "skills_used": ["xy-qa-review"],
            "unavailable_required_skills": [],
            "uncovered_audit_surfaces": [],
        }

    def envelope(self, host: str, payload: dict[str, object]) -> dict[str, object]:
        """各宿主只使用已确定的最终 JSON 形态，不给事件流猜测完成状态。"""
        pack = qa_task_pack(host)
        body = json.dumps(pack, ensure_ascii=False).encode("utf-8")
        self.pack_file.write_bytes(body)
        payload["handoff_ref"] = handoff_ref(pack, body)
        if host == "codex":
            return payload
        if host == "claude":
            return {"type": "result", "subtype": "success", "is_error": False,
                    "structured_output": payload}
        return {"conversation_id": "conversation-qa", "status": "SUCCESS",
                "structured_output": payload, "response": json.dumps(payload),
                "usage": {"total_tokens": 57}}

    def invoke_path(self, host: str | None, source: Path) -> subprocess.CompletedProcess[str]:
        command = ["validate"] if host is None else ["extract", "--host", host]
        return subprocess.run(
            [sys.executable, str(self.cli), *command, "--input", str(source), "--task-pack", str(self.pack_file)],
            text=True, capture_output=True, check=False, timeout=15,
        )

    def invoke(self, host: str | None, value: object) -> subprocess.CompletedProcess[str]:
        body = value if isinstance(value, bytes) else json.dumps(value).encode("utf-8")
        with tempfile.TemporaryDirectory(prefix="qa-native-") as raw:
            # macOS 的系统临时路径可能有 /var 别名；正常夹具使用其实际普通父目录。
            root = Path(raw).resolve()
            source = root / "terminal.json"
            source.write_bytes(body)
            before = source.stat()
            result = self.invoke_path(host, source)
            self.assertEqual(body, source.read_bytes())
            self.assertEqual(before.st_mtime_ns, source.stat().st_mtime_ns)
            self.assertEqual([source], list(root.iterdir()))
            return result

    def assert_rejected(self, result: subprocess.CompletedProcess[str]) -> None:
        self.assertEqual(2, result.returncode, result.stdout + result.stderr)
        self.assertEqual("", result.stdout)
        self.assertNotIn("Traceback", result.stderr)
        self.assertIsInstance(json.loads(result.stderr)["error"], str)

    def test_schema_is_strict_and_supports_findings_verification_and_rework(self) -> None:
        result = subprocess.run([sys.executable, str(self.cli), "schema"],
                                text=True, capture_output=True, check=False)
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        schema = json.loads(result.stdout)
        self.assertEqual("object", schema["type"])
        self.assertEqual({"schema_version", "handoff_ref", "audit_result", "review_method",
                          "standards_policy_coverage", "skill_evidence", "review_details"},
                         set(schema["properties"]))
        self.assertEqual(["PASS", "FAIL"], schema["properties"]["audit_result"]["enum"])
        method = schema["properties"]["review_method"]["properties"]
        self.assertEqual({"host-native-review", "installed-code-review-skill", "internal-xy-qa-procedure"},
                         set(method["selected"]["enum"]))
        self.assertIn("null", method["external_skill"]["type"])
        self.assertIn(None, method["fallback_reason"]["enum"])
        self.assertEqual({"skills_used", "unavailable_required_skills", "uncovered_audit_surfaces"},
                         set(schema["properties"]["skill_evidence"]["properties"]))
        self.assertIn("repositories", method["scope_ref"]["properties"])
        coverage = schema["properties"]["standards_policy_coverage"]["properties"]
        self.assertIn("rule_checks", coverage)
        self.assertIn("null", coverage["index_fingerprint"]["type"])
        self.assertIn("path_checks", coverage)
        details = schema["properties"]["review_details"]["properties"]
        finding = details["findings"]["items"]["properties"]
        self.assertEqual({"severity", "blocking", "detail", "evidence_refs", "owner_role", "next_step"},
                         set(finding))
        self.assertIn("xy-backend", finding["owner_role"]["enum"])
        self.assertEqual({"command", "exit_code", "log_ref"},
                         set(details["verification"]["items"]["properties"]))

        def check_objects(value: object) -> None:
            # OpenAI strict 要求每层对象字段全部 required，不能只约束最外层。
            if isinstance(value, dict):
                if value.get("type") == "object":
                    self.assertIs(False, value["additionalProperties"])
                    self.assertEqual(set(value["properties"]), set(value["required"]))
                for child in value.values():
                    check_objects(child)
            elif isinstance(value, list):
                for child in value:
                    check_objects(child)
        check_objects(schema)

    def test_success_envelopes_preserve_pass_fail_and_all_inner_metadata(self) -> None:
        for host in ("codex", "claude", "antigravity"):
            for outcome in ("PASS", "FAIL"):
                with self.subTest(host=host, outcome=outcome):
                    payload = json.loads(json.dumps(self.payload))
                    payload.update(audit_result=outcome, findings=[{"severity": "P2", "detail": "原始发现"}],
                                   metadata={"source": "fixture", "count": 0})
                    payload["review_details"] = self.review_details(blocking=outcome == "FAIL")
                    result = self.invoke(host, self.envelope(host, payload))
                    self.assertEqual(0, result.returncode, result.stdout + result.stderr)
                    self.assertEqual(payload, json.loads(result.stdout))

    def review_details(self, *, blocking: bool) -> dict:
        return {
            "findings": [{
                "severity": "P1" if blocking else "P3",
                "blocking": blocking,
                "detail": "回执重复键掩盖冲突结论" if blocking else "维护性建议",
                "evidence_refs": ["diff:services/api.py", "logs:validation-full"],
                "owner_role": "xy-backend" if blocking else None,
                "next_step": "拒绝冲突键并补充回归验证" if blocking else None,
            }],
            "verification": [{"command": "python -m unittest", "exit_code": 1 if blocking else 0,
                              "log_ref": "logs:validation-full"}],
        }

    def test_findings_require_evidence_and_actionable_blockers(self) -> None:
        for outcome, section, mutation, error in (
            ("FAIL", "findings", {}, "actionable blocking"),
            ("PASS", "findings", {}, "PASS cannot contain blocking"),
            ("FAIL", "findings", {"severity": ["P1"]}, "severity"),
            ("FAIL", "findings", {"evidence_refs": []}, "evidence_refs"),
            ("FAIL", "findings", {"owner_role": None}, "owner_role"),
            ("FAIL", "findings", {"owner_role": "fixture-worker"}, "owner_role"),
            ("FAIL", "findings", {"next_step": " "}, "next_step"),
            ("FAIL", "verification", {"exit_code": False}, "exit_code"),
            ("FAIL", "verification", {"log_ref": ""}, "log_ref"),
        ):
            with self.subTest(outcome=outcome, mutation=mutation):
                payload = json.loads(json.dumps(self.payload))
                payload["audit_result"] = outcome
                details = self.review_details(blocking=True)
                if mutation:
                    details[section][0].update(mutation)
                elif outcome == "FAIL":
                    details["findings"] = []
                payload["review_details"] = details
                result = self.invoke("codex", payload)
                self.assert_rejected(result)
                self.assertIn(error, result.stderr)

    def test_failed_cancelled_partial_and_nonterminal_envelopes_are_rejected(self) -> None:
        cases = [
            ("codex", {"type": "turn.failed", "structured_output": self.payload}),
            ("codex", {"type": "item.completed", "item": {"type": "agent_message", "text": json.dumps(self.payload)}}),
            # 即使错误事件带有可解析的 PASS 对象，也不能作为 Claude 成功终端回执。
            ("claude", {"type": "assistant", "isApiErrorMessage": True, "error": "invalid_request",
                        "message": {"model": "<synthetic>", "content": [{"type": "text", "text":
                            "Prompt is too long · automatic compaction failed: summarization produced empty response"}]},
                        "structured_output": self.envelope("claude", self.payload)["structured_output"]}),
        ]
        for field, values in {"type": ["assistant", None], "subtype": ["error", "cancelled", "partial", None],
                              "is_error": [True, 0, None]}.items():
            for value in values:
                envelope = self.envelope("claude", self.payload)
                envelope[field] = value
                cases.append(("claude", envelope))
        for status in ("ERROR", "CANCELLED", "PARTIAL", "RUNNING", "success", None):
            envelope = self.envelope("antigravity", self.payload)
            envelope["status"] = status
            cases.append(("antigravity", envelope))
        cases.append(("antigravity", {"event": "result", "result": self.envelope("antigravity", self.payload)}))
        for host, value in cases:
            with self.subTest(host=host, value=value):
                self.assert_rejected(self.invoke(host, value))

    def test_native_contract_rejects_missing_or_malformed_fields(self) -> None:
        for host in ("codex", "claude", "antigravity"):
            for field in ("skills_used", "unavailable_required_skills", "uncovered_audit_surfaces"):
                payload = json.loads(json.dumps(self.payload))
                del payload["skill_evidence"][field]
                with self.subTest(host=host, field=field, value="missing"):
                    self.assert_rejected(self.invoke(host, self.envelope(host, payload)))
                for bad_value in (None, "skill", [7], [""], ["same", " same "]):
                    with self.subTest(host=host, field=field, value=bad_value):
                        payload = json.loads(json.dumps(self.payload))
                        payload["skill_evidence"][field] = bad_value
                        self.assert_rejected(self.invoke(host, self.envelope(host, payload)))
            for defect in ("missing", "required-unavailable"):
                payload = json.loads(json.dumps(self.payload))
                if defect == "missing":
                    del payload["skill_evidence"]
                else:
                    payload["skill_evidence"]["unavailable_required_skills"] = ["missing-skill"]
                with self.subTest(host=host, defect=defect):
                    self.assert_rejected(self.invoke(host, self.envelope(host, payload)))
        for field, value in (("conversation_id", ""), ("response", "plain text"),
                             ("response", json.dumps({"audit_result": "PASS"})), ("usage", [])):
            envelope = self.envelope("antigravity", self.payload)
            envelope[field] = value
            with self.subTest(field=field):
                self.assert_rejected(self.invoke("antigravity", envelope))

    def test_optional_agy_response_and_usage_do_not_create_new_qa_gates(self) -> None:
        """AGY 的结构化终端结果不依赖可见用量；附加 response 为空时也无需再生成正文。"""
        for response in (None, ""):
            envelope = self.envelope("antigravity", self.payload)
            del envelope["usage"]
            if response is None:
                del envelope["response"]
            else:
                envelope["response"] = response
            with self.subTest(response=response):
                result = self.invoke("antigravity", envelope)
                self.assertEqual(0, result.returncode, result.stdout + result.stderr)
                self.assertEqual(self.payload, json.loads(result.stdout))

    def test_structured_output_must_be_an_object_and_not_a_string_or_partial_result(self) -> None:
        for host in ("claude", "antigravity"):
            for value in (None, [], json.dumps(self.payload)):
                envelope = self.envelope(host, self.payload)
                envelope["structured_output"] = value
                with self.subTest(host=host, value=value):
                    self.assert_rejected(self.invoke(host, envelope))
        # QA 字段齐全也不能让 Codex 的失败事件取得最终消息身份。
        payload = json.loads(json.dumps(self.payload))
        payload["type"] = "turn.failed"
        self.assert_rejected(self.invoke("codex", payload))
        # 宿主明确带取消／部分状态时，大小写或两种取消拼写都不能被 QA 字段掩盖。
        for status in ("FAILED", "error", "CANCELLED", "canceled", "PARTIAL", "incomplete", "running"):
            payload = json.loads(json.dumps(self.payload))
            payload["status"] = status
            with self.subTest(status=status):
                self.assert_rejected(self.invoke("codex", payload))

    def test_native_generation_never_weakens_existing_semantic_gates(self) -> None:
        for host in ("codex", "claude", "antigravity"):
            for defect in ("fallback-findings", "native-fallback", "hard-fail", "pm-omission", "scope", "evidence",
                           "audit-type", "domain-type", "severity-type", "disposition-type"):
                payload = json.loads(json.dumps(self.payload))
                method, coverage = payload["review_method"], payload["standards_policy_coverage"]
                if defect == "fallback-findings":
                    method["fallback_reason"] = "findings"
                elif defect == "native-fallback":
                    method["selected"] = "host-native-review"
                elif defect == "hard-fail":
                    coverage["rule_checks"][0]["disposition"] = "fail"
                elif defect == "pm-omission":
                    coverage["task_pack_rule_ids"] = []
                elif defect == "scope":
                    method["scope_ref"]["repositories"][0]["changed_paths"].append("services/other.py")
                elif defect == "evidence":
                    coverage["rule_checks"][0]["evidence_refs"] = []
                elif defect == "audit-type":
                    payload["audit_result"] = []
                else:
                    coverage["rule_checks"][0][defect.removesuffix("-type")] = []
                with self.subTest(host=host, defect=defect):
                    self.assert_rejected(self.invoke(host, self.envelope(host, payload)))

    def test_text_stream_duplicates_nonfinite_and_unsafe_encoding_are_rejected(self) -> None:
        good = json.dumps(self.payload).encode("utf-8")
        invalid = [b"not JSON", b"```json\n" + good + b"\n```", good + b"\n" + good,
                   b"[" + good + b"]", b'{"audit_result":"FAIL",' + good[1:],
                   good[:-1] + b',"metadata":{"key":1,"key":2}}',
                   good[:-1] + b',"metadata":NaN}', good[:-1] + b',"metadata":Infinity}',
                   good[:-1] + b',"metadata":1e400}', good[:-1] + b',"metadata":"\\ud800"}',
                   b"\xff", b" " * (4 * 1024 * 1024 + 1)]
        for host in (None, "codex"):
            for index, body in enumerate(invalid):
                with self.subTest(host=host, case=index):
                    self.assert_rejected(self.invoke(host, body))

    def test_validate_stdin_rejects_conflicting_keys_and_non_utf8_bytes(self) -> None:
        fixture = QAHandoffValidationTest()
        fixture.setUp()
        good = json.dumps(self.payload).encode("utf-8")
        for body in (b'{"audit_result":"FAIL",' + good[1:], b"\xff", b" " * (4 * 1024 * 1024 + 1)):
            result = fixture.invoke(body, stdin=True)
            self.assert_rejected(result)

    def test_unsafe_file_nodes_and_parent_paths_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory(prefix="qa-native-files-") as raw:
            root = Path(raw).resolve()
            source = root / "terminal.json"
            source.write_text(json.dumps(self.payload), encoding="utf-8")
            linked = root / "symlink.json"
            linked.symlink_to(source)
            parent = root / "parent-link"
            parent.symlink_to(root, target_is_directory=True)
            fifo = root / "fifo"
            if os.name != "nt":
                os.mkfifo(fifo)
            candidates = [linked, parent / source.name, root, root / "missing", root / "child/../terminal.json"]
            if os.name != "nt":
                candidates.append(fifo)
            for host in (None, "codex"):
                for candidate in candidates:
                    with self.subTest(host=host, path=candidate):
                        self.assert_rejected(self.invoke_path(host, candidate))
            hardlink = root / "hardlink.json"
            os.link(source, hardlink)
            for host in (None, "codex"):
                self.assert_rejected(self.invoke_path(host, source))
                self.assert_rejected(self.invoke_path(host, hardlink))


if __name__ == "__main__":
    unittest.main()
