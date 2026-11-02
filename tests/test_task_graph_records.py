"""只在临时夹具验证记录工具；不接触真实项目、运行中任务或用户环境。"""

from __future__ import annotations

import copy
import json
import os
from pathlib import Path
import stat
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from lib import task_graph_records as records
from lib.task_graph_cli import _execute


PACK = Path(__file__).resolve().parents[1]


def graph():
    """真实使用原有规范、Writer 和请求级 QA 合同，不为测试放宽校验。"""
    document = {
        "mode": "full", "reason": "实现当前功能时遵守适用规范", "sections_or_queries": [],
        "content_fingerprint": "e" * 64, "applies_to": ["src/one"], "rule_ids": [],
    }
    return {
        "request_id": "request-1", "approved_gates": ["requirements_approved"],
        "active_paths": ["external/"], "active_semantic_locks": ["external-lock"], "capacity": 2,
        "standards_contract": {
            "index_path": "docs/STANDARDS.md", "root": "docs/standards", "index_fingerprint": "e" * 64,
            "required_engineering_rule_ids": ["eng-common-001"], "required_design_rule_ids": [],
            "leaves": [{"path": "docs/standards/GENERAL.md", "domain": "engineering",
                        "content_fingerprint": "e" * 64, "rule_ids": ["eng-common-001"]}],
            "protected_paths": [],
        },
        "tasks": [{
            "id": "api", "request_id": "request-1", "task_type": "writer", "role": "xy-backend",
            "surface_kind": "non_ui", "qa_scope": "request", "depends_on": [], "blocks": [],
            "gates": ["requirements_approved"], "owned_paths": ["src/one"], "semantic_locks": ["api"],
            "state": "DECLARED", "audit_surfaces": ["standards-conformance"],
            "verification_commands": ["project-scoped-build-and-smoke"],
            "output_contracts": ["可编译、可运行，并交独立 QA"],
            "controlled_document_access": {"adapter": "project.yaml", "documents": [
                {**copy.deepcopy(document), "path": "docs/STANDARDS.md"},
                {**copy.deepcopy(document), "path": "docs/standards/GENERAL.md", "rule_ids": ["eng-common-001"]},
            ]},
        }],
    }


def isolated_graph(root: Path):
    """只构造原有隔离记录格式；对象 ID 是夹具数据，不冒充真实 Git／构建证据。"""
    source = graph()
    source["tasks"][0]["execution_workspace"] = {
        "root": str(root / "worker"), "base_revision": "a" * 40, "head_revision": None,
    }
    source["worktree_integrations"] = {"request-1": {
        "root": str(root / "integration"), "target_branch": "main", "target_base": "a" * 40,
        "head_revision": None, "verification": [],
    }}
    return source


class RecordUpdateTest(unittest.TestCase):
    def setUp(self):
        self.original = graph()
        self.assertEqual({"status": "valid"}, _execute("validate", self.original))

    def update(self, change, source=None, root=None):
        return records.update(source or self.original, change, root, _execute)

    def test_agent_binding_requires_observed_running_task_and_is_immutable(self):
        """原生身份只能补记到已运行任务；完成态引用可保留但不能换绑。"""
        reference = {"host": "codex", "agent_id": "/fixture/agent-a"}
        bind = {"tasks": {"api": {"set": {"agent_ref": reference}}}}
        self.assertNotIn("agent_ref", self.original["tasks"][0])
        with self.assertRaisesRegex(ValueError, "RUNNING|QA"):
            self.update(bind)
        with self.assertRaisesRegex(ValueError, "RUNNING|QA"):
            self.update({"tasks": {"api": {"set": {"state": "RUNNING", "agent_ref": reference}}}})
        running = self.update({"tasks": {"api": {"set": {"state": "RUNNING"}}}})
        bound = self.update(bind, running)
        self.assertEqual(reference, bound["tasks"][0]["agent_ref"])
        self.assertEqual(bound, self.update(bind, bound))
        completed = self.update({"tasks": {"api": {"set": {"state": "BUILD_VERIFIED"}}}}, bound)
        self.assertEqual(completed, self.update(bind, completed))
        for value in (None, {}, {"host": "codex", "agent_id": "/fixture/agent-b"},
                      {"host": "claude", "agent_id": reference["agent_id"]}):
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.update({"tasks": {"api": {"set": {"agent_ref": value}}}}, bound)
        with self.assertRaisesRegex(ValueError, "protected|unsupported"):
            self.update({"tasks": {"api": {"append": {"agent_ref": [reference]}}}}, running)

    def test_agent_reference_shape_and_active_identity_collision(self):
        """真实 ID 由 PM 核实；图只校验结构、边界与同宿主活动身份的独占。"""
        source = self.update({"tasks": {"api": {"set": {"state": "RUNNING"}}}})
        for reference in (None, [], {}, {"host": "other", "agent_id": "a"},
                          {"host": "codex", "agent_id": ""}, {"host": "codex", "agent_id": " a"},
                          {"host": "codex", "agent_id": "a\n"}, {"host": "codex", "agent_id": "a" * 257},
                          {"host": "codex", "agent_id": "a", "state": "idle"}):
            invalid = copy.deepcopy(source)
            invalid["tasks"][0]["agent_ref"] = reference
            with self.subTest(reference=reference), self.assertRaises(ValueError):
                _execute("validate", invalid)
        reference = {"host": "codex", "agent_id": "/fixture/agent-a"}
        source["tasks"][0]["agent_ref"] = reference
        source["tasks"].append({"id": "read", "request_id": "request-1", "task_type": "read_only",
                                "state": "RUNNING", "depends_on": [], "blocks": [], "gates": [],
                                "owned_paths": [], "semantic_locks": []})
        bind = {"tasks": {"read": {"set": {"agent_ref": reference}}}}
        with self.assertRaisesRegex(ValueError, "agent_ref.*active|active.*agent_ref"):
            self.update(bind, source)
        source["tasks"][0]["state"] = "BUILD_VERIFIED"
        self.assertEqual(reference, self.update(bind, source)["tasks"][1]["agent_ref"])
        # 历史任务引用不会自动授权一个尚未运行的新任务。
        source["tasks"][1]["state"] = "DECLARED"
        with self.assertRaisesRegex(ValueError, "RUNNING|QA"):
            self.update(bind, source)

    def test_explicit_qa_binding_preserves_existing_qa_barrier(self):
        source = copy.deepcopy(self.original)
        source["tasks"][0]["blocks"] = ["qa"]
        source["tasks"].append({"id": "qa", "request_id": "request-1", "task_type": "qa",
                                "state": "DECLARED", "depends_on": ["api"], "blocks": [],
                                "gates": [], "owned_paths": [], "semantic_locks": []})
        with self.assertRaisesRegex(ValueError, "QA barrier"):
            self.update({"tasks": {"qa": {"set": {"state": "QA"}}}}, source)
        source["tasks"][0]["state"] = "BUILD_VERIFIED"
        qa = self.update({"tasks": {"qa": {"set": {"state": "QA"}}}}, source)
        reference = {"host": "claude", "agent_id": "fixture-reviewer"}
        result = self.update({"tasks": {"qa": {"set": {"agent_ref": reference}}}}, qa)
        self.assertEqual(reference, result["tasks"][1]["agent_ref"])

    def test_state_updates_keep_external_locks_and_release_only_owned_locks(self):
        running = self.update({"tasks": {"api": {"set": {"state": "RUNNING"}}}, "capacity": 1})
        self.assertEqual(["external/", "src/one"], running["active_paths"])
        self.assertEqual(["api", "external-lock"], running["active_semantic_locks"])
        complete = self.update({"tasks": {"api": {"set": {"state": "BUILD_VERIFIED"}}}}, running)
        self.assertEqual(["external/"], complete["active_paths"])
        self.assertEqual(["external-lock"], complete["active_semantic_locks"])
        self.assertEqual("DECLARED", self.original["tasks"][0]["state"])
        self.assertEqual(self.original["tasks"][0]["verification_commands"], complete["tasks"][0]["verification_commands"])

    def test_scope_append_requires_explicit_complete_document_coverage(self):
        change = {"tasks": {"api": {"append": {"owned_paths": ["src/two"]}}}}
        with self.assertRaisesRegex(ValueError, "cover"):
            self.update(change)
        change["tasks"]["api"]["documents"] = {
            "docs/STANDARDS.md": ["src/two"], "docs/standards/GENERAL.md": ["src/two"],
        }
        updated = self.update(change)
        self.assertEqual(["src/one", "src/two"], updated["tasks"][0]["owned_paths"])
        self.assertEqual(updated, self.update(change, updated))

    def test_running_scope_and_lock_changes_cannot_claim_external_locks(self):
        running = self.update({"tasks": {"api": {"set": {"state": "RUNNING"}}}})
        for fields in ({"semantic_locks": ["external-lock"]}, {"owned_paths": ["external/new"]}):
            operation = {"append": fields}
            if "owned_paths" in fields:
                operation["documents"] = {
                    "docs/STANDARDS.md": fields["owned_paths"],
                    "docs/standards/GENERAL.md": fields["owned_paths"],
                }
            with self.subTest(fields=fields), self.assertRaisesRegex(ValueError, "blocked"):
                self.update({"tasks": {"api": operation}}, running)
        # 拒绝的补丁不修改原图；正常完成也只能释放原自有锁。
        completed = self.update({"tasks": {"api": {"set": {"state": "BUILD_VERIFIED"}}}}, running)
        self.assertEqual(["external-lock"], completed["active_semantic_locks"])
        allowed = self.update({"tasks": {"api": {"append": {"semantic_locks": ["new-own-lock"]}}}}, running)
        self.assertIn("new-own-lock", allowed["active_semantic_locks"])

    def test_qa_running_uses_existing_request_barrier_and_lock_checks(self):
        source = copy.deepcopy(self.original)
        source["tasks"][0]["blocks"] = ["qa"]
        source["tasks"].append({
            "id": "qa", "request_id": "request-1", "task_type": "qa", "state": "DECLARED",
            "depends_on": ["api"], "blocks": [], "gates": [], "owned_paths": [], "semantic_locks": [],
        })
        for state in ("RUNNING", "QA"):
            with self.subTest(state=state):
                source["tasks"][0]["state"] = "DECLARED"
                change = {"tasks": {"qa": {"set": {"state": state}}}}
                with self.assertRaisesRegex(ValueError, "QA barrier"):
                    self.update(change, source)
                source["tasks"][0]["state"] = "BUILD_VERIFIED"
                running = self.update(change, source)
                self.assertEqual("qa", running["tasks"][1]["task_type"])
                for field, value in (("semantic_locks", "external-lock"), ("owned_paths", "external/report")):
                    with self.subTest(field=field), self.assertRaisesRegex(ValueError, "blocked"):
                        self.update({"tasks": {"qa": {"append": {field: [value]}}}}, running)
                own = self.update({"tasks": {"qa": {"append": {
                    "semantic_locks": ["qa-review"], "owned_paths": ["qa-artifacts/"],
                }}}}, running)
                self.assertIn("qa-review", own["active_semantic_locks"])
                self.assertIn("qa-artifacts/", own["active_paths"])
                alternate = "QA" if state == "RUNNING" else "RUNNING"
                switched = self.update({"tasks": {"qa": {"set": {"state": alternate}}}}, own)
                self.assertEqual(own["active_paths"], switched["active_paths"])
                self.assertEqual(own["active_semantic_locks"], switched["active_semantic_locks"])
                # 记录已由原交接确立的 PASS，仅验证锁释放，不在这里伪造审查证据。
                done = self.update({"tasks": {"qa": {"set": {"state": "QA_PASSED"}}}}, switched)
                self.assertEqual(["external/"], done["active_paths"])
                self.assertEqual(["external-lock"], done["active_semantic_locks"])

    def test_qa_readiness_does_not_replace_newly_unlocked_ready_tasks(self):
        source = copy.deepcopy(self.original)
        source["tasks"][0]["blocks"] = ["evidence", "read", "writer-b"]
        for task_id, kind in (("evidence", "evidence"), ("read", "read_only")):
            source["tasks"].append({
                "id": task_id, "request_id": "request-1", "task_type": kind, "state": "DECLARED",
                "depends_on": ["api"], "blocks": [], "gates": [], "owned_paths": [], "semantic_locks": [],
            })
        other = copy.deepcopy(self.original["tasks"][0])
        other.update(id="writer-b", request_id="request-b", depends_on=["api"],
                     owned_paths=["src/two"], semantic_locks=["api-b"])
        for document in other["controlled_document_access"]["documents"]:
            document["applies_to"] = ["src/two"]
        source["tasks"].append(other)
        updated = self.update({"tasks": {"api": {"set": {"state": "BUILD_VERIFIED"}}}, "capacity": 4}, source)
        self.assertTrue(_execute("qa-ready", updated)["qa_ready"])
        self.assertEqual(["evidence", "read", "writer-b"], _execute("ready", updated)["ready"])

    def test_scope_updates_keep_design_and_parallel_ownership_boundaries(self):
        with self.assertRaisesRegex(ValueError, "design"):
            self.update({"tasks": {"api": {"append": {"owned_paths": ["docs/standards/DESIGN_FOUNDATIONS.md"]}}}})
        other = copy.deepcopy(self.original["tasks"][0])
        other["id"] = "other"
        other["semantic_locks"] = ["other-lock"]
        other["owned_paths"] = ["src/two"]
        for doc in other["controlled_document_access"]["documents"]:
            doc["applies_to"] = ["src/two"]
        source = copy.deepcopy(self.original)
        source["tasks"].append(other)
        change = {"tasks": {"api": {
            "append": {"owned_paths": ["src/two"]},
            "documents": {"docs/STANDARDS.md": ["src/two"], "docs/standards/GENERAL.md": ["src/two"]},
        }}}
        with self.assertRaisesRegex(ValueError, "overlapping"):
            self.update(change, source)

    def test_approval_changes_and_false_qa_state_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "supports only"):
            self.update({"approved_gates": ["requirements_approved"]})
        for field in ("role", "gates", "qa_scope", "depends_on", "id"):
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, "protected"):
                self.update({"tasks": {"api": {"set": {field: []}}}})
        with self.assertRaisesRegex(ValueError, "QA_PASSED"):
            self.update({"tasks": {"api": {"set": {"state": "QA_PASSED"}}}})
        without_approval = copy.deepcopy(self.original)
        without_approval["approved_gates"] = []
        with self.assertRaisesRegex(ValueError, "blocked"):
            self.update({"tasks": {"api": {"set": {"state": "RUNNING"}}}}, without_approval)

    def test_completed_scope_change_does_not_reuse_old_completion(self):
        complete = self.update({"tasks": {"api": {"set": {"state": "BUILD_VERIFIED"}}}})
        change = {"tasks": {"api": {"append": {"verification_commands": ["new-target-build"]}}}}
        with self.assertRaisesRegex(ValueError, "pending state"):
            self.update(change, complete)
        change["tasks"]["api"]["set"] = {"state": "DECLARED"}
        self.assertEqual("DECLARED", self.update(change, complete)["tasks"][0]["state"])

    def test_completed_input_output_and_document_contract_changes_need_pending_state(self):
        complete = self.update({"tasks": {"api": {"set": {"state": "BUILD_VERIFIED"}}}})
        document = copy.deepcopy(complete["tasks"][0]["controlled_document_access"])
        document["documents"][0].update(mode="targeted", sections_or_queries=["新增适用规范章节"])
        for field, value in (("input_contracts", ["新的输入行为"]),
                             ("output_contracts", ["离线模式必须可运行"]),
                             ("semantic_locks", ["new-contract"]),
                             ("controlled_document_access", document)):
            with self.subTest(field=field):
                change = {"tasks": {"api": {"set": {field: value}}}}
                with self.assertRaisesRegex(ValueError, "pending state"):
                    self.update(change, complete)
                change["tasks"]["api"]["set"]["state"] = "DECLARED"
                self.assertEqual("DECLARED", self.update(change, complete)["tasks"][0]["state"])
        # 添加真实结果的引用不是新增功能合同，不强制重编译，更不自动授权 QA PASS。
        evidenced = self.update({"tasks": {"api": {"set": {"acceptance_evidence": ["existing-build.log"]}}}}, complete)
        self.assertEqual("BUILD_VERIFIED", evidenced["tasks"][0]["state"])

    def test_completed_document_reason_only_update_preserves_evidence_and_completion(self):
        source = copy.deepcopy(self.original)
        source["tasks"][0].update(state="BUILD_VERIFIED", input_contracts=["existing-before-content-and-build.log"])
        document = copy.deepcopy(source["tasks"][0]["controlled_document_access"])
        document["documents"][0]["reason"] = "澄清读取用途；规则和功能要求均未改变"
        change = {"tasks": {"api": {"set": {"controlled_document_access": document}}}}
        updated = self.update(change, source)
        self.assertEqual("BUILD_VERIFIED", updated["tasks"][0]["state"])
        for field in ("input_contracts", "output_contracts", "verification_commands"):
            self.assertEqual(source["tasks"][0][field], updated["tasks"][0][field])
        self.assertEqual(source["standards_contract"], updated["standards_contract"])
        self.assertEqual(updated, self.update(change, updated))
        # 说明性例外不允许同时改变真实功能输入并继续使用旧完成态。
        change["tasks"]["api"]["set"]["output_contracts"] = ["新的业务行为"]
        with self.assertRaisesRegex(ValueError, "pending state"):
            self.update(change, source)

    def test_worktree_completion_and_integration_updates_keep_original_qa_barrier(self):
        with tempfile.TemporaryDirectory(prefix="workflow-record-head-") as raw:
            source = isolated_graph(Path(raw).resolve())
            running = self.update({"tasks": {"api": {"set": {"state": "RUNNING"}}}}, source)
            completed = self.update({"tasks": {"api": {
                "checkpoint": "b" * 40, "set": {"state": "BUILD_VERIFIED"},
            }}}, running)
            self.assertEqual("b" * 40, completed["tasks"][0]["execution_workspace"]["head_revision"])
            self.assertFalse(_execute("qa-ready", completed)["qa_ready"])
            check = {"command": "actual-selected-build-and-smoke", "exit_code": 0,
                     "log_ref": "fixture:existing-log", "head_revision": "c" * 40}
            integrated = self.update({"integrations": {"request-1": {
                "head_revision": "c" * 40, "verification": [check],
            }}}, completed)
            self.assertTrue(_execute("qa-ready", integrated)["qa_ready"])
            self.assertEqual("BUILD_VERIFIED", integrated["tasks"][0]["state"])
            self.assertEqual(source["approved_gates"], integrated["approved_gates"])
            # 新组合 head 不能自动改绑旧验证或变成新的 QA PASS。
            stale = self.update({"integrations": {"request-1": {"head_revision": "d" * 40}}}, integrated)
            self.assertEqual([check], stale["worktree_integrations"]["request-1"]["verification"])
            self.assertFalse(_execute("qa-ready", stale)["qa_ready"])
            failed = self.update({"integrations": {"request-1": {
                "verification": [{**check, "head_revision": "d" * 40, "exit_code": 1}],
            }}}, stale)
            self.assertFalse(_execute("qa-ready", failed)["qa_ready"])
            for name in ("root", "base_revision"):
                self.assertEqual(source["tasks"][0]["execution_workspace"][name],
                                 integrated["tasks"][0]["execution_workspace"][name])
            for name in ("root", "target_branch", "target_base"):
                self.assertEqual(source["worktree_integrations"]["request-1"][name],
                                 integrated["worktree_integrations"]["request-1"][name])

    def test_worktree_record_operations_reject_identity_changes_and_invalid_evidence(self):
        with tempfile.TemporaryDirectory(prefix="workflow-record-guard-") as raw:
            source = isolated_graph(Path(raw).resolve())
            before = copy.deepcopy(source)
            invalid = [
                {"tasks": {"api": {"checkpoint": "short-head"}}},
                {"tasks": {"api": {"checkpoint": {"root": "/other"}}}},
                {"tasks": {"api": {"set": {"execution_workspace": {}}}}},
                {"tasks": {"api": {"checkpoint": None, "set": {"state": "BUILD_VERIFIED"}}}},
                {"integrations": {"unknown": {"head_revision": "b" * 40}}},
                {"integrations": {"request-1": {"head_revision": "short-head"}}},
                {"integrations": {"request-1": {"verification": [{
                    "command": "build", "exit_code": True, "log_ref": "fixture:log", "head_revision": "c" * 40,
                }]}}},
            ]
            for field in ("root", "target_branch", "target_base"):
                invalid.append({"integrations": {"request-1": {field: "replacement"}}})
            for change in invalid:
                with self.subTest(change=change), self.assertRaises(ValueError):
                    self.update(change, source)
                self.assertEqual(before, source)
            with self.assertRaisesRegex(ValueError, "existing execution_workspace"):
                self.update({"tasks": {"api": {"checkpoint": "b" * 40}}})

    def test_refresh_selected_plan_reference_does_not_reset_build_or_adopt_standards(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw).resolve()
            (root / "plan.md").write_text("新的恢复检查点，不改变实现输入。", encoding="utf-8")
            source = copy.deepcopy(self.original)
            source["tasks"][0]["state"] = "BUILD_VERIFIED"
            source["tasks"][0]["controlled_document_access"]["documents"].append({
                **copy.deepcopy(source["tasks"][0]["controlled_document_access"]["documents"][0]), "path": "plan.md",
            })
            updated = self.update({"refresh_documents": ["plan.md"]}, source, root)
            self.assertEqual("BUILD_VERIFIED", updated["tasks"][0]["state"])
            self.assertEqual(source["standards_contract"], updated["standards_contract"])
            self.assertEqual(records.digest((root / "plan.md").read_bytes()), updated["tasks"][0]["controlled_document_access"]["documents"][-1]["content_fingerprint"])


class RecordPublicationTest(unittest.TestCase):
    def test_noop_stale_fingerprint_and_original_permissions(self):
        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw).resolve() / "graph.json"
            path.write_bytes(b"old\n")
            path.chmod(0o640)
            info = path.stat()
            self.assertFalse(records.publish(path, b"old\n", records.digest(b"old\n")))
            self.assertEqual((info.st_ino, info.st_mtime_ns), (path.stat().st_ino, path.stat().st_mtime_ns))
            with self.assertRaisesRegex(ValueError, "fingerprint changed"):
                records.publish(path, b"new\n", "0" * 64)
            self.assertTrue(records.publish(path, b"new\n", records.digest(b"old\n")))
            self.assertEqual(0o640, stat.S_IMODE(path.stat().st_mode))

    def test_detected_external_edit_is_preserved_without_backup_or_lock_files(self):
        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw).resolve() / "graph.json"
            path.write_bytes(b"old\n")
            fsync = os.fsync

            def edit_after_temporary_write(descriptor):
                fsync(descriptor)
                path.write_bytes(b"concurrent edit\n")

            with patch.object(records.os, "fsync", side_effect=edit_after_temporary_write):
                with self.assertRaisesRegex(ValueError, "changed before publication"):
                    records.publish(path, b"new\n", records.digest(b"old\n"))
            self.assertEqual(b"concurrent edit\n", path.read_bytes())
            self.assertEqual([path], list(path.parent.iterdir()))

    def test_atomic_replace_readers_and_failed_publication_keep_complete_graph(self):
        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw).resolve() / "graph.json"
            path.write_bytes(b"old\n")
            replace = os.replace

            def observe(source, destination):
                self.assertEqual(b"old\n", records.read_record(path))
                self.assertEqual(1, path.stat().st_nlink)
                replace(source, destination)
                self.assertEqual(b"new\n", records.read_record(path))
                self.assertEqual(1, path.stat().st_nlink)

            with patch.object(records.os, "replace", side_effect=observe):
                self.assertTrue(records.publish(path, b"new\n", records.digest(b"old\n")))
            with patch.object(records.os, "replace", side_effect=OSError("interrupted before replacement")):
                with self.assertRaisesRegex(OSError, "interrupted"):
                    records.publish(path, b"later\n", records.digest(b"new\n"))
            self.assertEqual(b"new\n", records.read_record(path))
            self.assertEqual([path], list(path.parent.iterdir()))

    def test_cooperative_writer_lock_fails_closed_without_changing_graph(self):
        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw).resolve() / "graph.json"
            path.write_bytes(b"old\n")
            with records._publication_lock(path):
                with self.assertRaisesRegex(ValueError, "busy or advisory locking"):
                    records.publish(path, b"new\n", records.digest(b"old\n"))
            self.assertEqual(b"old\n", path.read_bytes())
            self.assertEqual([path], list(path.parent.iterdir()))

    def test_link_targets_are_never_overwritten(self):
        for hard in (False, True):
            with self.subTest(hard=hard), tempfile.TemporaryDirectory() as raw:
                root = Path(raw).resolve()
                source = root / "source.json"
                source.write_bytes(b"private\n")
                target = root / "graph.json"
                os.link(source, target) if hard else target.symlink_to(source)
                with self.assertRaisesRegex(ValueError, "single-link"):
                    records.publish(target, b"new\n", records.digest(b"private\n"))
                self.assertEqual(b"private\n", source.read_bytes())


class RecordCliTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="workflow-records-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.source = self.root / "graph.json"
        self.source.write_text(json.dumps(graph(), ensure_ascii=False), encoding="utf-8")

    def invoke(self, *args, input=None):
        return subprocess.run(["bash", str(PACK / "lib/python_runtime.sh"), "-X", "utf8",
                               str(PACK / "lib/task_graph_cli.py"), *map(str, args)],
                              input=input, text=True, capture_output=True, check=False, timeout=15)

    def test_continuation_cli_is_read_only_and_requires_current_host_observation(self):
        """通过真实 CLI 验证旧图、绑定、CAS、活动观察及阻塞建议，查询不发布文件。"""
        query = ("continuation", "--input", self.source, "--task-id", "api", "--host", "codex")
        before = self.source.read_bytes()
        result = self.invoke(*query, "--observed-state", "idle")
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual("unbound", json.loads(result.stdout)["reason"])
        self.assertEqual(before, self.source.read_bytes())
        reference = {"host": "codex", "agent_id": "/fixture/agent-a"}
        for fields in ({"state": "RUNNING"}, {"agent_ref": reference}):
            result = self.invoke("update", "--input", self.source, "--expect-sha256",
                                 records.digest(self.source.read_bytes()), "--patch", "-",
                                 input=json.dumps({"tasks": {"api": {"set": fields}}}))
            self.assertEqual(0, result.returncode, result.stderr)
        before = self.source.read_bytes()
        for state in ("running", "idle", "cancelled", "missing", "unknown"):
            result = self.invoke(*query, "--observed-state", state)
            self.assertEqual(0, result.returncode, result.stderr)
            value = json.loads(result.stdout)
            self.assertEqual(state in {"running", "idle"}, value["reuse_allowed"])
            self.assertEqual(reference, value["agent_ref"])
            self.assertEqual("wait" if state == "running" else "followup" if state == "idle" else "blocked",
                             value["action"])
            self.assertEqual(before, self.source.read_bytes())
        result = self.invoke("continuation", "--input", self.source, "--task-id", "api", "--host", "claude",
                             "--observed-state", "idle")
        self.assertFalse(json.loads(result.stdout)["reuse_allowed"])
        self.assertEqual("host_mismatch", json.loads(result.stdout)["reason"])
        # 绑定走原 CAS：旧摘要与 append 绕过均拒写。
        for old_sha, operation in (("0" * 64, {"set": {"agent_ref": reference}}),
                                   (records.digest(before), {"append": {"agent_ref": [reference]}})):
            result = self.invoke("update", "--input", self.source, "--expect-sha256", old_sha,
                                 "--patch", "-", input=json.dumps({"tasks": {"api": operation}}))
            self.assertEqual(2, result.returncode)
            self.assertEqual(before, self.source.read_bytes())
        result = self.invoke(*query, "--observed-state", "idle", "--output", self.root / "forbidden.json")
        self.assertEqual(2, result.returncode)
        self.assertEqual({"graph.json"}, {p.name for p in self.root.iterdir()})
        completed = json.loads(before)
        completed["tasks"][0]["state"] = "BUILD_VERIFIED"
        self.source.write_text(json.dumps(completed), encoding="utf-8")
        result = self.invoke(*query, "--observed-state", "idle")
        self.assertEqual("task_not_active", json.loads(result.stdout)["reason"])

    def test_update_and_export_use_existing_validators_and_do_not_create_other_records(self):
        before = records.digest(self.source.read_bytes())
        result = self.invoke("update", "--input", self.source, "--expect-sha256", before, "--patch", "-",
                             input=json.dumps({"tasks": {"api": {"set": {"state": "RUNNING"}}}}))
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertTrue(json.loads(result.stdout)["updated"])
        target = self.root / "api-task.json"
        result = self.invoke("task", "--input", self.source, "--task-id", "api", "--output", target, "--expect-sha256", "missing")
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual(json.loads(self.source.read_text(encoding="utf-8"))["tasks"][0], json.loads(target.read_text(encoding="utf-8")))
        self.assertEqual({"graph.json", "api-task.json"}, {p.name for p in self.root.iterdir()})
        result = self.invoke("qa-ready", "--input", self.source)
        self.assertFalse(json.loads(result.stdout)["qa_ready"])

    def test_worktree_checkpoint_and_integration_update_run_through_installed_cli_contract(self):
        source = isolated_graph(self.root)
        self.source.write_text(json.dumps(source), encoding="utf-8")
        changes = [
            {"tasks": {"api": {"checkpoint": "b" * 40, "set": {"state": "BUILD_VERIFIED"}}}},
            {"integrations": {"request-1": {"head_revision": "c" * 40, "verification": [{
                "command": "existing-build-and-run", "exit_code": 0, "log_ref": "fixture:existing-log",
                "head_revision": "c" * 40,
            }]}}},
        ]
        for change in changes:
            with self.subTest(change=change):
                result = self.invoke("update", "--input", self.source,
                                     "--expect-sha256", records.digest(self.source.read_bytes()),
                                     "--patch", "-", input=json.dumps(change))
                self.assertEqual(0, result.returncode, result.stderr)
                self.assertTrue(json.loads(result.stdout)["updated"])
        result = self.invoke("qa-ready", "--input", self.source)
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertTrue(json.loads(result.stdout)["qa_ready"])
        self.assertEqual({"graph.json"}, {path.name for path in self.root.iterdir()})
        # 新接口仍走原 CAS 写入，不因是检查点记录而覆盖更新后的图。
        before = self.source.read_bytes()
        result = self.invoke("update", "--input", self.source, "--expect-sha256", "0" * 64,
                             "--patch", "-", input=json.dumps(changes[0]))
        self.assertEqual(2, result.returncode)
        self.assertEqual(before, self.source.read_bytes())

    def test_bad_update_changes_no_bytes_and_cannot_export_over_graph(self):
        before = self.source.read_bytes()
        result = self.invoke("update", "--input", self.source, "--expect-sha256", records.digest(before), "--patch", "-",
                             input='{"tasks":{"api":{"set":{"owned_paths":["../outside"]}}}}')
        self.assertEqual(2, result.returncode)
        self.assertEqual(before, self.source.read_bytes())
        result = self.invoke("task", "--input", self.source, "--task-id", "api", "--output", self.source, "--expect-sha256", records.digest(before))
        self.assertEqual(2, result.returncode)
        self.assertEqual(before, self.source.read_bytes())

    def test_malformed_record_options_and_duplicate_patch_keys_fail_cleanly(self):
        before = self.source.read_bytes()
        for content in ('{"capacity":1,"capacity":2}', '{"tasks":{"unknown":{"set":{"state":"RUNNING"}}}}'):
            with self.subTest(content=content):
                result = self.invoke("update", "--input", self.source, "--expect-sha256", records.digest(before), "--patch", "-", input=content)
                self.assertEqual(2, result.returncode)
                self.assertNotIn("Traceback", result.stderr)
                self.assertEqual(before, self.source.read_bytes())
        result = self.invoke("validate", "--input", self.source, "--output", self.root / "must-not-exist.json")
        self.assertEqual(2, result.returncode)
        self.assertFalse((self.root / "must-not-exist.json").exists())
        self.source.write_text("[]", encoding="utf-8")
        result = self.invoke("task", "--input", self.source, "--task-id", "api")
        self.assertEqual(2, result.returncode)
        self.assertNotIn("Traceback", result.stderr)

    def test_invalid_running_field_type_is_json_error_and_keeps_bytes(self):
        running = records.update(graph(), {"tasks": {"api": {"set": {"state": "RUNNING"}}}}, None, _execute)
        self.source.write_text(json.dumps(running), encoding="utf-8")
        before = self.source.read_bytes()
        for fields in ({"owned_paths": None}, {"state": []}, {"semantic_locks": 1}):
            with self.subTest(fields=fields):
                result = self.invoke("update", "--input", self.source, "--expect-sha256", records.digest(before),
                                     "--patch", "-", input=json.dumps({"tasks": {"api": {"set": fields}}}))
                self.assertEqual(2, result.returncode)
                self.assertIn("error", json.loads(result.stderr))
                self.assertEqual(before, self.source.read_bytes())

    def test_fingerprints_accept_existing_receipt_fields_and_detect_stale_evidence(self):
        binary = self.root / "app.bin"
        binary.write_bytes(b"\x00\xffbuild-output")
        receipt = json.dumps({"artifact_sha256": {"app.bin": records.digest(binary.read_bytes())}, "unrelated": "do not scan"})
        before = self.source.read_bytes()
        result = self.invoke("fingerprints", "--root", self.root, "--select", "artifact_sha256", input=receipt)
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertTrue(json.loads(result.stdout)["matched"])
        binary.write_bytes(b"changed build")
        result = self.invoke("fingerprints", "--root", self.root, "--select", "artifact_sha256", input=receipt)
        self.assertEqual(1, result.returncode)
        self.assertEqual(["app.bin"], json.loads(result.stdout)["changed"])
        self.assertEqual(before, self.source.read_bytes())

    def test_fingerprints_generate_only_selected_files_and_reject_traversal(self):
        result = self.invoke("fingerprints", "--root", self.root, input='["graph.json"]')
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual({"graph.json": records.digest(self.source.read_bytes())}, json.loads(result.stdout)["fingerprints"])
        result = self.invoke("fingerprints", "--root", self.root, input='["../private"]')
        self.assertEqual(2, result.returncode)

    def test_scratch_workspace_reuses_deterministic_slot_and_cleans_up_at_closeout(self):
        first = self.invoke("scratch", "--root", self.root, "--request-id", "req-audit-01")
        self.assertEqual(0, first.returncode, first.stderr)
        payload1 = json.loads(first.stdout)
        self.assertFalse(payload1["reused"])
        self.assertEqual("req-audit-01", payload1["request_id"])
        scratch_dir = Path(payload1["scratch_dir"])
        self.assertTrue(scratch_dir.is_dir())
        (scratch_dir / "evidence.log").write_text("round 1\n", encoding="utf-8")
        readonly_dir = scratch_dir / "readonly-build"
        readonly_dir.mkdir()
        readonly_file = readonly_dir / "artifact.bin"
        readonly_file.write_bytes(b"readonly-artifact")
        readonly_file.chmod(0o444)
        readonly_dir.chmod(0o500)

        second = self.invoke("scratch", "--root", self.root, "--request-id", "req-audit-01")
        self.assertEqual(0, second.returncode, second.stderr)
        payload2 = json.loads(second.stdout)
        self.assertEqual(payload1["scratch_dir"], payload2["scratch_dir"])
        self.assertTrue(payload2["reused"])
        self.assertEqual("round 1\n", (scratch_dir / "evidence.log").read_text(encoding="utf-8"))

        cleaned = self.invoke("cleanup-scratch", "--root", self.root, "--request-id", "req-audit-01")
        self.assertEqual(0, cleaned.returncode, cleaned.stderr)
        cleaned_payload = json.loads(cleaned.stdout)
        self.assertTrue(cleaned_payload["cleaned"])
        self.assertEqual(2, cleaned_payload["removed_files"])
        self.assertGreater(cleaned_payload["reclaimed_bytes"], 0)
        self.assertFalse(scratch_dir.exists())

        for bad_id in ("", " ", "\t"):
            with self.subTest(bad_id=bad_id):
                invalid = self.invoke("scratch", "--root", self.root, "--request-id", bad_id)
                self.assertEqual(2, invalid.returncode)
                self.assertIn("error", json.loads(invalid.stderr))


class ScratchWorkspaceTest(unittest.TestCase):
    """真实文件系统回归：任务身份映射、目录替换及目录外数据保护。"""

    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="workflow-scratch-safety-")
        self.addCleanup(temporary.cleanup)
        self.home = Path(temporary.name).resolve()
        self.project = self.home / "project"
        self.project.mkdir()
        temp_root_patch = patch.object(records.tempfile, "gettempdir", return_value=str(self.home))
        temp_root_patch.start()
        self.addCleanup(temp_root_patch.stop)

    def test_existing_graph_ids_map_to_safe_distinct_directories(self):
        ids = ("需求-文档复用", "issue:123", "feature/reuse", "../escape", "CON", "r" * 129,
               "Request-A", "request-a")
        paths = []
        for request_id in ids:
            with self.subTest(request_id=request_id):
                payload = graph()
                payload["request_id"] = payload["tasks"][0]["request_id"] = request_id
                self.assertEqual("valid", _execute("validate", payload)["status"])
                allocated = records.scratch_workspace(self.project, request_id)
                self.assertEqual(request_id, allocated["request_id"])
                path = Path(allocated["scratch_dir"])
                self.assertEqual(Path(allocated["project_scratch_root"]), path.parent)
                self.assertEqual(path, Path(records.scratch_workspace(self.project, request_id)["scratch_dir"]))
                paths.append(path)
        self.assertEqual(len(ids), len({path.name for path in paths}))
        # 即便底层文件系统忽略大小写，不同请求也必须保留各自的文件。
        evidence = paths[-2] / "active.log"
        evidence.write_text("keep active request", encoding="utf-8")
        self.assertFalse(paths[-2].samefile(paths[-1]))
        records.cleanup_scratch(self.project, ids[-1])
        self.assertEqual("keep active request", evidence.read_text(encoding="utf-8"))

    def test_directory_swapped_before_open_never_follows_external_link(self):
        target = Path(records.scratch_workspace(self.project, "race")["scratch_dir"])
        nested = target / "build"
        nested.mkdir()
        external = self.home / "external"
        external.mkdir()
        victim = external / "important.txt"
        victim.write_bytes(b"keep outside data")
        original_open = records.os.open
        swapped = False

        def replace_before_open(name, flags, *args, **kwargs):
            nonlocal swapped
            if name == "build" and not swapped:
                swapped = True
                nested.rename(self.home / "original-build")
                nested.symlink_to(external, target_is_directory=True)
            return original_open(name, flags, *args, **kwargs)

        with patch.object(records.os, "open", side_effect=replace_before_open):
            with self.assertRaises((OSError, ValueError)):
                records.cleanup_scratch(self.project, "race")
        self.assertTrue(swapped)
        self.assertEqual(b"keep outside data", victim.read_bytes())

    def test_opened_directory_swap_keeps_traversal_on_original_identity(self):
        target = Path(records.scratch_workspace(self.project, "opened-race")["scratch_dir"])
        nested = target / "build"
        nested.mkdir()
        (nested / "owned.bin").write_bytes(b"task artifact")
        nested_identity = nested.stat().st_ino
        external = self.home / "external"
        external.mkdir()
        victim = external / "important.txt"
        victim.write_bytes(b"keep outside data")
        original_listdir = records.os.listdir
        swapped = False

        def replace_before_listdir(descriptor):
            nonlocal swapped
            if records.os.fstat(descriptor).st_ino == nested_identity and not swapped:
                swapped = True
                nested.rename(self.home / "original-build")
                nested.symlink_to(external, target_is_directory=True)
            return original_listdir(descriptor)

        with patch.object(records.os, "listdir", side_effect=replace_before_listdir):
            with self.assertRaisesRegex(ValueError, "changed while cleaning"):
                records.cleanup_scratch(self.project, "opened-race")
        self.assertTrue(swapped)
        self.assertEqual(b"keep outside data", victim.read_bytes())

    def test_symlinks_and_hardlinks_never_change_external_contents_or_permissions(self):
        target = Path(records.scratch_workspace(self.project, "links")["scratch_dir"])
        external = self.home / "external"
        external.mkdir()
        victim = external / "important.txt"
        victim.write_bytes(b"keep outside data")
        victim.chmod(0o444)
        (target / "external-directory").symlink_to(external, target_is_directory=True)
        os.link(victim, target / "hardlink")
        records.cleanup_scratch(self.project, "links")
        self.assertEqual(b"keep outside data", victim.read_bytes())
        self.assertEqual(0o444, stat.S_IMODE(victim.stat().st_mode))
        self.assertFalse(target.exists())
        self.assertFalse(records.cleanup_scratch(self.project, "links")["cleaned"])

    def test_target_symlink_is_rejected_and_all_cleanup_preserves_other_projects(self):
        target = Path(records.scratch_workspace(self.project, "linked-target")["scratch_dir"])
        external = self.home / "external"
        external.mkdir()
        target.rmdir()
        target.symlink_to(external, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, "not a link"):
            records.cleanup_scratch(self.project, "linked-target")
        self.assertTrue(target.is_symlink())
        target.unlink()
        other_project = self.home / "other-project"
        other_project.mkdir()
        other = Path(records.scratch_workspace(other_project, "same-id")["scratch_dir"])
        (other / "keep.log").write_bytes(b"other project")
        own = Path(records.scratch_workspace(self.project, "own")["scratch_dir"])
        (own / "remove.log").write_bytes(b"own project")
        legacy = own.parent / "legacy-request"
        legacy.mkdir()
        (legacy / "keep.log").write_bytes(b"unadopted legacy data")
        self.assertTrue(records.cleanup_scratch(self.project, remove_all=True)["cleaned"])
        self.assertFalse(own.exists())
        self.assertEqual(b"unadopted legacy data", (legacy / "keep.log").read_bytes())
        self.assertEqual(b"other project", (other / "keep.log").read_bytes())

    def test_legacy_hash_shaped_id_is_never_adopted_or_cleaned(self):
        """旧 ID 可以恰好符合新哈希格式，迁移隔离必须依靠独立容器而非名称猜测。"""
        base = records._project_scratch_base(self.project)
        legacy = self.home / "agent-workflow-scratch" / base.name / records._validated_scratch_slot("current")
        legacy.mkdir(parents=True)
        evidence = legacy / "keep.log"
        evidence.write_bytes(b"unfinished legacy task")
        current = records.scratch_workspace(self.project, "current")
        self.assertFalse(current["reused"])
        self.assertFalse(legacy.samefile(current["scratch_dir"]))
        records.cleanup_scratch(self.project, remove_all=True)
        self.assertEqual(b"unfinished legacy task", evidence.read_bytes())

    @unittest.skipIf(os.name == "nt" or getattr(os, "geteuid", lambda: 0)() == 0,
                     "需要普通 POSIX 用户验证目录读取权限")
    def test_unreadable_directory_is_preserved_with_error(self):
        """无法安全打开时拒绝清理，不为绕过权限而恢复按路径 chmod 的竞态。"""
        target = Path(records.scratch_workspace(self.project, "unreadable")["scratch_dir"])
        nested = target / "restricted"
        nested.mkdir()
        evidence = nested / "keep.log"
        evidence.write_bytes(b"keep inaccessible artifacts")
        nested.chmod(0o100)
        try:
            with self.assertRaises(PermissionError):
                records.cleanup_scratch(self.project, "unreadable")
        finally:
            nested.chmod(0o700)
        self.assertEqual(b"keep inaccessible artifacts", evidence.read_bytes())


class RecordInstalledRuntimeTest(unittest.TestCase):
    def test_three_host_install_exports_helpers_and_runs_from_detached_runtime(self):
        """在临时后端夹具执行真实安装与自带三宿主验收，不运行任何业务构建。"""
        with tempfile.TemporaryDirectory(prefix="workflow-record-install-") as raw:
            root = Path(raw).resolve()
            project = root / "示例 Project"
            project.mkdir()
            business = project / "go.mod"
            business.write_bytes(b"module example.test/records\n")
            result = subprocess.run(["bash", str(PACK / "install.sh"), str(project)],
                                    cwd=root, text=True, capture_output=True, check=False, timeout=120)
            self.assertEqual(0, result.returncode, result.stdout + result.stderr)
            runtime = project / ".agent-workflow"
            self.assertEqual((PACK / "lib/task_graph_records.py").read_bytes(), (runtime / "lib/task_graph_records.py").read_bytes())
            self.assertEqual((PACK / "lib/agent_continuation.py").read_bytes(), (runtime / "lib/agent_continuation.py").read_bytes())
            reference = "xy-workflow/references/runtime-records.md"
            for directory in (".claude/skills", ".agents/skills"):
                self.assertEqual((PACK / "platforms/shared/skills" / reference).read_bytes(), (project / directory / reference).read_bytes())
            for host in ("Claude", "Codex", "Antigravity"):
                self.assertIn(f"{host} --check", result.stdout)
            source = root / "graph.json"
            source.write_text(json.dumps(graph()), encoding="utf-8")
            result = subprocess.run([
                "bash", str(runtime / "lib/python_runtime.sh"), "-X", "utf8", str(runtime / "lib/task_graph_cli.py"),
                "update", "--input", str(source), "--expect-sha256", records.digest(source.read_bytes()), "--patch", "-",
            ], input='{"tasks":{"api":{"set":{"state":"RUNNING"}}}}',
                cwd=project, text=True, capture_output=True, check=False, timeout=15)
            self.assertEqual(0, result.returncode, result.stderr)
            self.assertEqual("RUNNING", json.loads(source.read_text(encoding="utf-8"))["tasks"][0]["state"])
            # 安装态从业务根加载新 helper，并经原 CAS 绑定后实际运行只读查询。
            result = subprocess.run([
                "bash", str(runtime / "lib/python_runtime.sh"), "-X", "utf8", str(runtime / "lib/task_graph_cli.py"),
                "update", "--input", str(source), "--expect-sha256", records.digest(source.read_bytes()), "--patch", "-",
            ], input='{"tasks":{"api":{"set":{"agent_ref":{"host":"codex","agent_id":"fixture-installed-agent"}}}}}',
                cwd=project, text=True, capture_output=True, check=False, timeout=15)
            self.assertEqual(0, result.returncode, result.stderr)
            before = source.read_bytes()
            result = subprocess.run([
                "bash", str(runtime / "lib/python_runtime.sh"), "-X", "utf8", str(runtime / "lib/task_graph_cli.py"),
                "continuation", "--input", str(source), "--task-id", "api", "--host", "codex", "--observed-state", "idle",
            ], cwd=project, text=True, capture_output=True, check=False, timeout=15)
            self.assertEqual(0, result.returncode, result.stderr)
            self.assertEqual("followup", json.loads(result.stdout)["action"])
            self.assertEqual(before, source.read_bytes())
            self.assertEqual(b"module example.test/records\n", business.read_bytes())


if __name__ == "__main__":
    unittest.main()
