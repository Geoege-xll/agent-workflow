from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


class QAHandoffValidationTest(unittest.TestCase):
    """验证 QA PASS 必须覆盖固定 diff 与独立识别出的适用规范。"""

    def setUp(self) -> None:
        self.cli = Path(__file__).resolve().parents[1] / "lib/qa_handoff_cli.py"
        self.payload = {
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

    def invoke(self, payload: dict[str, object]) -> subprocess.CompletedProcess[str]:
        with tempfile.TemporaryDirectory(prefix="qa-handoff-") as raw:
            source = Path(raw) / "handoff.json"
            source.write_text(json.dumps(payload), encoding="utf-8")
            return subprocess.run(
                [sys.executable, str(self.cli), "validate", "--input", str(source)],
                text=True,
                capture_output=True,
                check=False,
            )

    def test_complete_standards_coverage_can_pass(self) -> None:
        result = self.invoke(self.payload)
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        self.assertEqual({"status": "valid"}, json.loads(result.stdout))

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
        payload["standards_policy_coverage"]["task_pack_rule_ids"] = []
        result = self.invoke(payload)
        self.assertEqual(2, result.returncode)
        self.assertIn("omitted from the PM Task Pack", result.stderr)

        # 相同证据作为 FAIL 交回 PM 是合法的，因为它准确暴露了编排缺口。
        payload["audit_result"] = "FAIL"
        result = self.invoke(payload)
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)


class NativeQAHandoffTest(unittest.TestCase):
    """从真实 CLI 验证原生终端合同；封装夹具不冒充真实模型执行证据。"""

    def setUp(self) -> None:
        fixture = QAHandoffValidationTest()
        fixture.setUp()
        self.cli = fixture.cli
        self.payload = fixture.payload
        self.payload["skill_evidence"] = {
            "skills_used": ["xy-qa-review"],
            "unavailable_required_skills": [],
            "uncovered_audit_surfaces": [],
        }

    def envelope(self, host: str, payload: dict[str, object]) -> dict[str, object]:
        """各宿主只使用已确定的最终 JSON 形态，不给事件流猜测完成状态。"""
        if host == "codex":
            return payload
        if host == "claude":
            return {"type": "result", "subtype": "success", "is_error": False,
                    "structured_output": payload}
        return {"conversation_id": "conversation-qa", "status": "SUCCESS",
                "structured_output": payload, "response": json.dumps(payload),
                "usage": {"total_tokens": 57}}

    def invoke_path(self, host: str, source: Path) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(self.cli), "extract", "--host", host, "--input", str(source)],
            text=True, capture_output=True, check=False,
        )

    def invoke(self, host: str, value: object) -> subprocess.CompletedProcess[str]:
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

    def test_schema_is_complete_strict_minimal_contract(self) -> None:
        result = subprocess.run([sys.executable, str(self.cli), "schema"],
                                text=True, capture_output=True, check=False)
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        schema = json.loads(result.stdout)
        self.assertEqual("object", schema["type"])
        self.assertEqual({"audit_result", "review_method", "standards_policy_coverage", "skill_evidence"},
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
        self.assertIn("path_checks", coverage)

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
                    if outcome == "FAIL":
                        payload["standards_policy_coverage"]["rule_checks"][0]["disposition"] = "fail"
                        payload["skill_evidence"]["unavailable_required_skills"] = ["required-skill"]
                    result = self.invoke(host, self.envelope(host, payload))
                    self.assertEqual(0, result.returncode, result.stdout + result.stderr)
                    self.assertEqual(payload, json.loads(result.stdout))

    def test_failed_cancelled_partial_and_nonterminal_envelopes_are_rejected(self) -> None:
        cases = [
            ("codex", {"type": "turn.failed", "structured_output": self.payload}),
            ("codex", {"type": "item.completed", "item": {"type": "agent_message", "text": json.dumps(self.payload)}}),
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
        for index, body in enumerate(invalid):
            with self.subTest(case=index):
                self.assert_rejected(self.invoke("codex", body))

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
            for candidate in candidates:
                with self.subTest(path=candidate):
                    self.assert_rejected(self.invoke_path("codex", candidate))
            hardlink = root / "hardlink.json"
            os.link(source, hardlink)
            self.assert_rejected(self.invoke_path("codex", source))
            self.assert_rejected(self.invoke_path("codex", hardlink))


if __name__ == "__main__":
    unittest.main()
