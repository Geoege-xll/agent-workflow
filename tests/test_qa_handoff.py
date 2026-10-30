from __future__ import annotations

import json
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


if __name__ == "__main__":
    unittest.main()
