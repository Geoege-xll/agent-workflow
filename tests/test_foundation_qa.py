"""在真实原字节交接与临时目录上验证 Foundation 两检查点，身份均为测试夹具。"""
from __future__ import annotations

import copy
from contextlib import contextmanager
import json
import os
import subprocess
import sys
from pathlib import Path
import tempfile
import unittest

from lib import foundation_qa, task_graph_records as records
from lib.task_graph_cli import _execute, _verify_ui_scope, export_task_pack
from tests.test_scheduler_boundaries import v2_task, with_builtin_standards
from tests.test_task_graph import _builtin_standards_payload
from lib.validate_project_docs import builtin_standard_rule_catalog

REPO = Path(__file__).resolve().parents[1]


@contextmanager
def working_root(root):
    """生产入口按真实cwd确定项目，夹具也沿用相同路径，不注入中央桥环境。"""
    previous = Path.cwd()
    os.chdir(root)
    try:
        yield
    finally:
        os.chdir(previous)


def graph(root):
    result = _builtin_standards_payload()
    result["request_id"] = "req-boundaries"
    writer = result["tasks"][0]
    writer.update(id="foundation", state="BUILD_VERIFIED", role="xy-web", surface_kind="production_ui",
                  owned_paths=["src/foundation.py"], blocks=["feature"],
                  goal="建立已批准UI基础", input_contracts=["冻结设计"], output_contracts=["可复用组件"],
                  acceptance_evidence=["build:foundation-log"], verification_commands=["build-and-smoke"],
                  audit_surfaces=["ui", "accessibility", "standards-conformance"],
                  ui_change={"route": "UI-Conformance", "design_delta": "none", "prototype_policy": "not_applicable",
                             "prototype_decision": None, "design_authority_refs": [{"kind": "controlled_document",
                             "authority_id": "accepted", "path": "docs/ui.md", "anchor": "ui",
                             "content_fingerprint": records.digest(b"approved ui"), "resolution_state": "resolved"}],
                             "affected_surfaces": ["shared"], "justification": "依照已批准权威建立基础"})
    for doc in writer["controlled_document_access"]["documents"]:
        doc["applies_to"] = writer["owned_paths"]
    with_builtin_standards(result)
    result["standards_contract"]["required_design_rule_ids"] = ["des-baseline-001"]
    result["ui_contract"] = {"prototype_paths": ["docs/standards/prototype"]}
    feature = copy.deepcopy(writer)
    feature.update(id="feature", agent_alias="fixture-feature", state="DECLARED", depends_on=["foundation"],
                   blocks=[], owned_paths=["src/feature.py"])
    feature["ui_change"]["affected_surfaces"] = ["page"]
    for doc in feature["controlled_document_access"]["documents"]:
        doc["applies_to"] = feature["owned_paths"]
    qa = v2_task({"id": "qa", "request_id": result["request_id"], "task_type": "qa", "state": "DECLARED",
                  "foundation_task_id": "foundation", "depends_on": [], "blocks": [], "gates": [],
                  "owned_paths": [], "semantic_locks": [], "audit_surfaces": ["ui", "accessibility"]})
    result["tasks"].extend([feature, qa])
    for relative, body in (("src/foundation.py", b"foundation-v1"), ("src/feature.py", b"feature-v1"),
                           ("docs/ui.md", b"approved ui")):
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(body)
    for leaf in result["standards_contract"]["leaves"]:
        path = root / leaf["path"]
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes((REPO / leaf["path"]).read_bytes())
    _execute("validate", result)
    return result


def handoff(pack, body, *, scope_ref=None):
    """构造完整规则覆盖结果，复用生产校验器验证，而非mock掉QA语义检查。"""
    task = pack["task"]
    coverage = {key: copy.deepcopy(pack["standards_contract"][key]) for key in
                ("index_path", "root", "index_fingerprint", "required_engineering_rule_ids", "required_design_rule_ids")}
    rules = [rule for leaf in pack["standards_contract"]["leaves"] for rule in leaf["rule_ids"]]
    scope_ref = scope_ref or task.get("qa_scope_ref")
    if scope_ref:
        paths = [path for repo in scope_ref["repositories"] for path in repo["changed_paths"]]
    else:
        paths = [path for writer in pack["reviewed_ui_changes"] for path in writer["owned_paths"]]
        scope_ref = {"repositories": [{"path": ".", "base_revision": "base", "head_revision": "head",
                                       "diff_fingerprint": "d" * 64, "changed_paths": paths}]}
    catalog = builtin_standard_rule_catalog(REPO)
    coverage.update(task_pack_rule_ids=rules,
                    path_checks=[{"path": path, "applicable_rule_ids": rules, "reason": "审查当前生产实现"} for path in paths],
                    rule_checks=[])
    for leaf in pack["standards_contract"]["leaves"]:
        for rule in leaf["rule_ids"]:
            definition = catalog[leaf["path"]]["rules"][rule]
            coverage["rule_checks"].append({"rule_id": rule, "source_path": leaf["path"],
                 "source_fingerprint": leaf["content_fingerprint"], "source_anchor": rule,
                 "domain": leaf["domain"], "severity": definition, "disposition": "pass",
                 "affected_paths": paths, "evidence_refs": ["diff:current"], "not_applicable_reason": "", "exception_ref": ""})
    return {"schema_version": 2, "audit_result": "PASS", "handoff_ref": {
        "request_id": task["request_id"], "task_id": task["id"], "agent_alias": task["agent_alias"],
        "agent_ref": task["agent_ref"], "task_pack_sha256": records.digest(body)},
        "skill_evidence": {"skills_used": ["xy-qa-review"], "unavailable_required_skills": [], "uncovered_audit_surfaces": []},
        "review_method": {"selected": "internal-xy-qa-procedure", "external_skill": None,
                          "capability_evidence": ["capability:native-unavailable", "capability:skill-unavailable"],
                          "fallback_reason": "missing", "scope_ref": copy.deepcopy(scope_ref)},
        "standards_policy_coverage": coverage}


class FoundationQATest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="foundation-qa-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.cwd = working_root(self.root)
        self.cwd.__enter__()
        self.addCleanup(self.cwd.__exit__, None, None, None)
        self.source = graph(self.root)

    def update(self, source, task_id, operation):
        return records.update(source, {"tasks": {task_id: operation}}, self.root, _execute)

    def start(self, source):
        started = self.update(source, "qa", {"set": {"state": "QA"}})
        if "agent_ref" not in started["tasks"][2]:
            started = self.update(started, "qa", {"set": {"agent_ref": {"host": "codex", "agent_id": "original-reviewer"}}})
        return started

    def evidence(self, source, label="stage"):
        pack = export_task_pack(source, "qa", root=self.root)
        body = json.dumps(pack, ensure_ascii=False).encode()
        result = handoff(pack, body)
        references = {}
        for field, content in (("task_pack", body), ("handoff", json.dumps(result).encode())):
            path = self.root / f"{label}-{field}.json"
            path.write_bytes(content)
            references[field] = {"path": str(path), "sha256": records.digest(content)}
        return pack, result, references

    def passed_foundation(self):
        started = self.start(self.source)
        _, _, references = self.evidence(started)
        return self.update(started, "qa", {"accept_foundation": references})

    def ordinary_source(self):
        """沿用同一真实规范和两个 Writer，移除可选阶段以覆盖普通 Full 入口。"""
        source = copy.deepcopy(self.source)
        source["tasks"][2].pop("foundation_task_id")
        source["tasks"][1]["state"] = "BUILD_VERIFIED"
        return source

    def freeze(self, source, paths=None, *, commit=False):
        """在临时真实 Git 仓库预先冻结候选差异，回执仅复用已冻结范围。"""
        from lib.delivery.worktree_cli import git, head, scope
        if not (self.root / ".git").exists():
            git(self.root, "init", "-b", "main")
            git(self.root, "config", "user.name", "Ordinary QA Fixture")
            git(self.root, "config", "user.email", "workflow-fixture@example.invalid")
            git(self.root, "commit", "--allow-empty", "-m", "fixture baseline")
            self.base_revision = head(self.root)
            commit = True
        if commit:
            git(self.root, "add", "--", *(paths or ["src/foundation.py", "src/feature.py"]))
            git(self.root, "commit", "-m", "fixture Writer candidate")
        fixed_scope = {"repositories": [scope(self.root, self.base_revision, head(self.root))]}
        return self.update(source, "qa", {"freeze_qa_scope": fixed_scope})

    def test_ordinary_final_acceptance_requires_current_bytes_and_reopens_only_affected_review(self):
        source = self.start(self.freeze(self.ordinary_source()))
        old_pack, _, old_refs = self.evidence(source, "ordinary-original")
        self.assertEqual({"kind": "request", "writer_ids": ["feature", "foundation"]}, old_pack["qa_checkpoint"])
        with self.assertRaisesRegex(ValueError, "accept_request"):
            self.update(source, "qa", {"set": {"state": "QA_PASSED"}})
        with self.assertRaisesRegex(ValueError, "only operation"):
            self.update(source, "qa", {"accept_request": old_refs, "set": {"state": "FAILED"}})
        wrong = copy.deepcopy(old_refs)
        wrong["handoff"]["sha256"] = "0" * 64
        with self.assertRaisesRegex(ValueError, "fingerprint changed"):
            self.update(source, "qa", {"accept_request": wrong})
        failed = self.update(source, "qa", {"set": {"state": "FAILED"}})
        with self.assertRaisesRegex(ValueError, "current checkpoint"):
            self.update(self.start(failed), "qa", {"accept_request": old_refs})
        result = self.update(source, "qa", {"accept_request": old_refs})
        reviewer = result["tasks"][2]
        self.assertEqual("QA_PASSED", reviewer["state"])
        self.assertTrue(foundation_qa.current_request_receipt(result, reviewer))
        outside = copy.deepcopy(result["tasks"][1])
        outside.update(id="outside", agent_alias="outside-writer", request_id="other-request",
                       semantic_locks=[], owned_paths=["src/outside.py"], depends_on=["feature"])
        for document in outside["controlled_document_access"]["documents"]:
            document["applies_to"] = outside["owned_paths"]
        unrelated = copy.deepcopy(result)
        unrelated["tasks"][1]["blocks"] += ["outside"]
        unrelated["tasks"].append(outside)
        unrelated = self.update(unrelated, "outside", {"set": {"state": "DECLARED"},
            "append": {"verification_commands": ["check-other-request"]}})
        self.assertEqual(reviewer, unrelated["tasks"][2])
        self.assertTrue(foundation_qa.current_request_receipt(unrelated, unrelated["tasks"][2]))

        # 即使返工还原为相同构建态，本轮已作废的包也不得在同一 Reviewer 上重放。
        rework = self.update(unrelated, "feature", {"set": {"state": "DECLARED"},
            "append": {"verification_commands": ["check-updated-contract"]}})
        self.assertEqual("DECLARED", rework["tasks"][2]["state"])
        self.assertNotIn("request_receipt", rework["tasks"][2])
        self.assertEqual(reviewer["agent_ref"], rework["tasks"][2]["agent_ref"])
        complete = self.update(rework, "feature", {"set": {"state": "BUILD_VERIFIED"}})
        reopened = self.start(self.freeze(complete))
        new_pack, _, new_refs = self.evidence(reopened, "ordinary-reopened")
        self.assertNotEqual(old_pack["qa_checkpoint_fingerprint"], new_pack["qa_checkpoint_fingerprint"])
        with self.assertRaisesRegex(ValueError, "current checkpoint"):
            self.update(reopened, "qa", {"accept_request": old_refs})
        self.assertEqual("QA_PASSED", self.update(reopened, "qa", {"accept_request": new_refs})["tasks"][2]["state"])

    def test_ordinary_cli_cas_rejects_changed_sources_and_excludes_legacy_pass_from_ready(self):
        source = self.start(self.ordinary_source())
        scoped = self.freeze(source)
        source_body = json.dumps(source).encode()
        graph_path = self.root / "graph.json"
        graph_path.write_bytes(source_body)
        cli = [sys.executable, str(REPO / "lib/task_graph_cli.py"), "update", "--input", str(graph_path)]
        freeze_patch = {"tasks": {"qa": {"freeze_qa_scope": scoped["tasks"][2]["qa_scope_ref"]}}}
        frozen = subprocess.run([*cli, "--expect-sha256", records.digest(source_body), "--patch", "-"],
                                input=json.dumps(freeze_patch), capture_output=True, text=True, check=False)
        self.assertEqual(0, frozen.returncode, frozen.stderr)
        source_body = graph_path.read_bytes()
        source = records.decode(source_body)
        self.assertEqual(scoped, source)
        _, _, refs = self.evidence(source, "ordinary-cli")
        patch = {"tasks": {"qa": {"accept_request": refs}}}
        pending = self.update(source, "qa", patch["tasks"]["qa"])
        changed = self.root / "src/feature.py"
        changed.write_bytes(b"post-review mutation")
        with self.assertRaisesRegex(ValueError, "PM-frozen QA scope is stale"):
            records.publish(graph_path, json.dumps(pending).encode(), records.digest(source_body))
        self.assertEqual(source_body, graph_path.read_bytes())
        changed.write_bytes(b"feature-v1")
        command = [*cli, "--expect-sha256", records.digest(source_body), "--patch", "-"]
        accepted = subprocess.run(command, input=json.dumps(patch), capture_output=True, text=True, check=False)
        self.assertEqual(0, accepted.returncode, accepted.stderr)
        saved = records.decode(graph_path.read_bytes())
        self.assertEqual("QA_PASSED", saved["tasks"][2]["state"])
        saved["tasks"][2]["blocks"] = ["after-qa"]
        saved["tasks"].append(v2_task({"id": "after-qa", "request_id": "other", "task_type": "read_only",
            "state": "DECLARED", "depends_on": ["qa"], "blocks": [], "gates": [], "owned_paths": [],
            "semantic_locks": []}))
        self.assertIn("after-qa", _execute("ready", saved)["ready"])
        saved["tasks"][2].pop("request_receipt")
        self.assertEqual({"status": "valid"}, _execute("validate", saved))
        self.assertNotIn("after-qa", _execute("ready", saved)["ready"])

    def test_ordinary_scope_must_be_frozen_before_pass_and_cover_exact_diff(self):
        source = self.ordinary_source()
        # 故意使用目录所有权，验证采样依据是已冻结的具体文件而非整个目录。
        for writer in source["tasks"][:2]:
            writer["owned_paths"] = ["src"]
            for document in writer["controlled_document_access"]["documents"]:
                document["applies_to"] = ["src"]
        unfrozen = self.start(source)
        _, _, refs = self.evidence(unfrozen, "ordinary-missing-scope")
        with self.assertRaisesRegex(ValueError, "PM-frozen qa_scope_ref"):
            self.update(unfrozen, "qa", {"accept_request": refs})
        started = self.freeze(unfrozen)
        pack, _, refs = self.evidence(started, "ordinary-scope")
        fixed_scope = pack["task"]["qa_scope_ref"]
        with self.assertRaisesRegex(ValueError, "only operation"):
            self.update(started, "qa", {"accept_request": refs, "freeze_qa_scope": fixed_scope})
        with self.assertRaisesRegex(ValueError, "protected"):
            self.update(started, "qa", {"set": {"qa_scope_ref": fixed_scope}})
        for key, value in (("changed_paths", ["src/feature.py"]), ("diff_fingerprint", "1" * 64),
                           ("base_revision", "wrong-base"), ("head_revision", "wrong-head")):
            with self.subTest(field=key):
                draft_scope = copy.deepcopy(fixed_scope)
                draft_scope["repositories"][0][key] = value
                body = Path(refs["task_pack"]["path"]).read_bytes()
                wrong = json.dumps(handoff(pack, body, scope_ref=draft_scope)).encode()
                target = self.root / "ordinary-wrong-handoff.json"
                target.write_bytes(wrong)
                wrong_refs = {**refs, "handoff": {"path": str(target), "sha256": records.digest(wrong)}}
                with self.assertRaisesRegex(ValueError, "complete PM-frozen scope_ref"):
                    self.update(started, "qa", {"accept_request": wrong_refs})
        (self.root / "src/.DS_Store").write_bytes(b"cache")
        (self.root / "src/cache-link").symlink_to(self.root / "irrelevant")
        self.assertEqual(pack, export_task_pack(started, "qa", root=self.root))
        accepted = self.update(started, "qa", {"accept_request": refs})
        self.assertEqual("QA_PASSED", accepted["tasks"][2]["state"])
        changed = self.root / "src/feature.py"
        changed.write_bytes(b"new candidate")
        refrozen = self.freeze(accepted, ["src/feature.py"], commit=True)
        self.assertEqual("DECLARED", refrozen["tasks"][2]["state"])
        self.assertEqual(started["tasks"][2]["agent_ref"], refrozen["tasks"][2]["agent_ref"])
        resumed = self.start(refrozen)
        with self.assertRaisesRegex(ValueError, "current checkpoint"):
            self.update(resumed, "qa", {"accept_request": refs})
        updated_pack, _, new_refs = self.evidence(resumed, "ordinary-scope-update")
        self.assertNotEqual(fixed_scope, updated_pack["task"]["qa_scope_ref"])
        self.assertEqual("QA_PASSED", self.update(resumed, "qa", {"accept_request": new_refs})["tasks"][2]["state"])

    def test_ordinary_required_prototype_uses_page_dependency_fingerprint(self):
        from lib.documents.validate_prototype_workspace import capture_selected_pages
        from tests.test_prototype_workspace import PROTOTYPE_RELATIVE, write_valid_project

        self.root = write_valid_project(self.root).resolve()
        source = graph(self.root)
        source["tasks"][2].pop("foundation_task_id")
        feature = source["tasks"][1]
        prototype = PROTOTYPE_RELATIVE.as_posix()
        page = capture_selected_pages(self.root, prototype, pages=["settings.html"], adapter="project.yaml")["pages"][0]
        fingerprint = page["dependency_fingerprint"]
        gate = f"visual_approved:settings@{fingerprint}"
        source["requirements_fingerprint"] = "c" * 64
        source["approved_gates"].append(gate)
        feature.update(state="BUILD_VERIFIED", depends_on=["foundation", "prototype"], gates=["requirements_approved", gate])
        feature["ui_change"].update(route="UI-Page", design_delta="changed", prototype_policy="required",
            prototype_decision={"source": "requirements_confirmation_user_choice", "choice_ref": "user:settings/prototype",
                "requirement_fingerprint": source["requirements_fingerprint"], "affected_surfaces": ["page"],
                "selected_policy": "required", "recommended_policy": "required", "recommendation_reason": "核对界面交互"},
            design_authority_refs=[{"kind": "prototype_contract", "authority_id": "settings", "path": page["path"],
                "anchor": "page-design-and-interaction-contract", "content_fingerprint": fingerprint, "resolution_state": "resolved"}])
        designer = copy.deepcopy(source["tasks"][0])
        designer.update(id="prototype", role="xy-uiux", surface_kind="design_ui", agent_alias="fixture-prototype",
                        blocks=["feature"], owned_paths=[page["path"]])
        designer.pop("ui_change")
        for doc in designer["controlled_document_access"]["documents"]:
            doc["applies_to"] = designer["owned_paths"]
        source["tasks"].append(designer)
        started = self.start(self.freeze(source, ["src/foundation.py", "src/feature.py", page["path"]]))
        _, _, refs = self.evidence(started, "ordinary-required-prototype")
        self.assertNotEqual(fingerprint, records.file_digest(self.root, page["path"]))
        self.assertEqual("QA_PASSED", self.update(started, "qa", {"accept_request": refs})["tasks"][2]["state"])
        css = self.root / prototype / "prototype.css"
        css.write_bytes(css.read_bytes() + b"\n")
        with self.assertRaisesRegex(ValueError, "prototype dependency fingerprint is stale"):
            self.update(started, "qa", {"accept_request": refs})

    def test_foundation_unblocks_original_deadlock_without_releasing_feature_early(self):
        from lib.task_graph import qa_ready
        from lib.task_graph_cli import _tasks
        self.assertFalse(qa_ready(_tasks(self.source), self.source["request_id"]))
        self.assertTrue(qa_ready(_tasks(self.source), self.source["request_id"], writer_ids={"foundation"}))
        self.assertTrue(_execute("qa-ready", self.source)["qa_ready"])
        self.assertNotIn("feature", _execute("ready", self.source)["ready"])
        started = self.start(self.source)
        self.assertNotIn("feature", _execute("ready", started)["ready"])
        failed = self.update(started, "qa", {"set": {"state": "FAILED"}})
        self.assertNotIn("feature", _execute("ready", failed)["ready"])
        with self.assertRaisesRegex(ValueError, "accept_request"):
            self.update(started, "qa", {"set": {"state": "QA_PASSED"}})
        with self.assertRaisesRegex(ValueError, "protected"):
            self.update(started, "qa", {"set": {"foundation_receipt": {}}})

    def test_two_checkpoints_keep_one_node_and_original_reviewer(self):
        passed = self.passed_foundation()
        qa = passed["tasks"][2]
        self.assertEqual("DECLARED", qa["state"])
        self.assertEqual("original-reviewer", qa["agent_ref"]["agent_id"])
        self.assertNotIn("agent_retired", qa)
        self.assertIn("feature", _execute("ready", passed)["ready"])
        self.assertFalse(_execute("qa-ready", passed)["qa_ready"])
        with self.assertRaisesRegex(ValueError, "QA barrier"):
            self.start(passed)
        completed = self.update(passed, "feature", {"set": {"state": "BUILD_VERIFIED"}})
        final = self.start(completed)
        with self.assertRaisesRegex(ValueError, "current checkpoint"):
            self.update(final, "qa", {"accept_request": {field: qa["foundation_receipt"][field] for field in ("task_pack", "handoff")}})
        pack, _, refs = self.evidence(final, "final")
        self.assertEqual({"kind": "request", "writer_ids": ["feature", "foundation"]}, pack["qa_checkpoint"])
        self.assertEqual(2, len(pack["reviewed_ui_changes"]))
        accepted = self.update(final, "qa", {"accept_request": refs})
        self.assertEqual("QA_PASSED", accepted["tasks"][2]["state"])
        self.assertEqual(3, len(accepted["tasks"]))
        self.assertEqual(qa["agent_ref"], accepted["tasks"][2]["agent_ref"])
        reopened = self.update(accepted, "foundation", {"append": {"acceptance_evidence": ["build:foundation-recheck"]}})
        self.assertEqual("DECLARED", reopened["tasks"][2]["state"])
        self.assertNotIn("foundation_receipt", reopened["tasks"][2])
        self.assertNotIn("request_receipt", reopened["tasks"][2])

    def test_old_wrong_and_failed_handoff_cannot_release_features(self):
        started = self.start(self.source)
        pack, result, refs = self.evidence(started)
        for change in ("fail", "identity", "scope", "byte"):
            payload, references = copy.deepcopy(result), copy.deepcopy(refs)
            if change == "fail":
                payload["audit_result"] = "FAIL"
            elif change == "identity":
                payload["handoff_ref"]["agent_ref"]["agent_id"] = "other"
            elif change == "scope":
                references["task_pack"]["sha256"] = "a" * 64
            else:
                payload["handoff_ref"]["task_pack_sha256"] = "b" * 64
            body = json.dumps(payload).encode()
            path = self.root / f"wrong-{change}.json"
            path.write_bytes(body)
            references["handoff"] = {"path": str(path), "sha256": records.digest(body)}
            with self.subTest(change=change), self.assertRaises(ValueError):
                self.update(started, "qa", {"accept_foundation": references})
        (self.root / "src/foundation.py").write_text("edited-after-pack")
        with self.assertRaisesRegex(ValueError, "current checkpoint"):
            self.update(started, "qa", {"accept_foundation": refs})

    def test_checkpoint_scope_rejects_omitted_ui_mixed_phase_and_wrong_id(self):
        started = self.start(self.source)
        pack = export_task_pack(started, "qa")
        self.assertEqual(["foundation"], pack["qa_checkpoint"]["writer_ids"])
        _verify_ui_scope(pack, started)
        for kind in ("missing-ui", "mixed", "wrong-id"):
            invalid = copy.deepcopy(pack)
            if kind == "missing-ui":
                invalid["reviewed_ui_changes"] = []
            elif kind == "mixed":
                invalid["qa_checkpoint"]["kind"] = "request"
            else:
                invalid["qa_checkpoint"]["writer_ids"] = ["feature"]
            with self.subTest(kind=kind), self.assertRaises(ValueError):
                _verify_ui_scope(invalid, started)
        for reference in ("feature-does-not-exist", "qa"):
            invalid = copy.deepcopy(self.source)
            invalid["tasks"][2]["foundation_task_id"] = reference
            with self.assertRaises(ValueError):
                _execute("validate", invalid)

    def test_foundation_rework_and_evidence_change_invalidate_but_feature_does_not(self):
        passed = self.passed_foundation()
        original = passed["tasks"][2]["foundation_receipt"]["checkpoint_fingerprint"]
        changed = self.update(passed, "feature", {"append": {"acceptance_evidence": ["build:new-feature"]}})
        (self.root / "src/feature.py").write_text("unrelated feature edit")
        self.assertEqual(original, foundation_qa.fingerprint(changed, changed["tasks"][2]))
        self.assertIn("feature", _execute("ready", changed)["ready"])
        for operation in ({"set": {"state": "RUNNING"}}, {"append": {"acceptance_evidence": ["build:changed-foundation"]}}):
            rework = self.update(passed, "foundation", operation)
            self.assertNotIn("foundation_receipt", rework["tasks"][2])
            self.assertNotIn("feature", _execute("ready", rework)["ready"])
        (self.root / "src/foundation.py").write_text("foundation-v2")
        self.assertNotIn("feature", _execute("ready", passed)["ready"])

    def test_receipt_file_and_authority_replacement_invalidate(self):
        passed = self.passed_foundation()
        receipt = passed["tasks"][2]["foundation_receipt"]
        evidence = Path(receipt["handoff"]["path"])
        old = evidence.read_bytes()
        evidence.write_bytes(old + b" ")
        self.assertNotIn("feature", _execute("ready", passed)["ready"])
        evidence.write_bytes(old)
        (self.root / "docs/ui.md").write_text("new authority")
        self.assertNotIn("feature", _execute("ready", passed)["ready"])

    def test_worktree_stage_and_final_require_current_integration_evidence(self):
        source = copy.deepcopy(self.source)
        for task in source["tasks"][:2]:
            task["execution_workspace"] = {"root": str(self.root / task["id"]), "base_revision": "a" * 40,
                                            "head_revision": "b" * 40 if task["state"] == "BUILD_VERIFIED" else None}
        record = {"root": str(self.root / "integration"), "target_branch": "main", "target_base": "a" * 40,
                  "head_revision": "c" * 40, "verification": []}
        source["worktree_integrations"] = {source["request_id"]: record}
        self.assertFalse(_execute("qa-ready", source)["qa_ready"])
        record["verification"] = [{"command": "integration-smoke", "exit_code": 0, "log_ref": "logs/integration",
                                    "head_revision": "c" * 40}]
        self.assertTrue(_execute("qa-ready", source)["qa_ready"])
        record["head_revision"] = "d" * 40
        self.assertFalse(_execute("qa-ready", source)["qa_ready"])
        record["verification"][0]["head_revision"] = "d" * 40
        for directory in (self.root / "foundation", self.root / "integration"):
            (directory / "src").mkdir(parents=True)
            (directory / "src/foundation.py").write_text("foundation-v1")
        started = self.start(source)
        _, _, refs = self.evidence(started, "worktree-stage")
        passed = self.update(started, "qa", {"accept_foundation": refs})
        stage_fingerprint = passed["tasks"][2]["foundation_receipt"]["checkpoint_fingerprint"]
        # 正常feature集成推进只改全局HEAD，不应废弃基础设施内容相同的阶段回执。
        passed["worktree_integrations"][source["request_id"]]["head_revision"] = "e" * 40
        self.assertEqual(stage_fingerprint, foundation_qa.fingerprint(passed, passed["tasks"][2]))
        passed["tasks"][1]["state"] = "BUILD_VERIFIED"
        passed["tasks"][1]["execution_workspace"]["head_revision"] = "f" * 40
        self.assertFalse(_execute("qa-ready", passed)["qa_ready"])
        passed["worktree_integrations"][source["request_id"]]["verification"][0]["head_revision"] = "e" * 40
        self.assertTrue(_execute("qa-ready", passed)["qa_ready"])
        # 组合候选错误改动Foundation本身则必须撤回阶段放行，不受全局HEAD豁免。
        (self.root / "integration/src/foundation.py").write_text("wrong combined foundation")
        self.assertFalse(foundation_qa.valid_receipt(passed, passed["tasks"][2]))


    def test_receipt_publication_rechecks_independent_bytes(self):
        started = self.start(self.source)
        _, _, refs = self.evidence(started)
        passed = self.update(started, "qa", {"accept_foundation": refs})
        target = self.root / "graph.json"
        before = json.dumps(started).encode()
        target.write_bytes(before)
        after = json.dumps(passed).encode()
        records.publish(target, after, records.digest(before))
        self.assertEqual(passed, records.decode(target.read_bytes()))
        target.write_bytes(before)
        Path(refs["handoff"]["path"]).write_bytes(b"changed")
        with self.assertRaisesRegex(ValueError, "unchanged independent"):
            records.publish(target, after, records.digest(before))

    def test_actual_cli_export_update_and_admission_preserve_stage_boundary(self):
        """跨真实进程跑现有入口，证明派发聚合不会在临时read_only投影中丢失阶段门禁。"""
        from lib import dispatch_admission_cli as admission
        path = self.root / "graph.json"
        path.write_text(json.dumps(self.source))
        command = [sys.executable, "-B", str(REPO / "lib/task_graph_cli.py")]
        viewed = subprocess.run([*command, "qa-ready", "--input", str(path)], capture_output=True, text=True)
        self.assertEqual(0, viewed.returncode, viewed.stderr)
        self.assertTrue(json.loads(viewed.stdout)["qa_ready"])
        manifest = {"schema_version": 1, "project_root": str(self.root),
                    "records": [{"path": str(path), "sha256": records.digest(path.read_bytes()),
                    "execution_roots": {task["id"]: str(self.root) for task in self.source["tasks"]}}],
                    "capacity": {"configured_subagents": 4, "configured_writers": 3, "host_available_subagents": 4}}
        result = admission.admission("view", manifest)
        self.assertEqual(["qa"], [item["task_id"] for item in result["candidates"]])
        claimed = admission.admission("claim", manifest, result["candidates"][0])
        self.assertEqual("claimed", claimed["status"])
        current = records.decode(path.read_bytes())
        bound = self.update(current, "qa", {"set": {"agent_ref": {"host": "codex", "agent_id": "original-reviewer"}}})
        path.write_text(json.dumps(bound))
        exported = subprocess.run([*command, "task", "--input", str(path), "--task-id", "qa"],
                                  capture_output=True, text=True)
        self.assertEqual(0, exported.returncode, exported.stderr)
        self.assertEqual("foundation", json.loads(exported.stdout)["qa_checkpoint"]["kind"])
        _, _, refs = self.evidence(bound)
        patch = self.root / "patch.json"
        patch.write_text(json.dumps({"tasks": {"qa": {"accept_foundation": refs}}}))
        updated = subprocess.run([*command, "update", "--input", str(path), "--patch", str(patch),
                                   "--expect-sha256", records.digest(path.read_bytes()), "--root", str(self.root)],
                                  capture_output=True, text=True)
        self.assertEqual(0, updated.returncode, updated.stderr)
        manifest["records"][0]["sha256"] = records.digest(path.read_bytes())
        result = admission.admission("view", manifest)
        self.assertEqual(["feature"], [item["task_id"] for item in result["candidates"]])
