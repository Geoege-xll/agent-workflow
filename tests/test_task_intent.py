"""在临时原记录上通过正式 CLI 验证撤回与修订；宿主观察用夹具明确给出。"""

import copy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from lib import task_graph_records as records
from lib.agent_continuation import active
from lib.task_graph_cli import export_task_pack
from tests.test_scheduler_boundaries import v2_task
from tests.test_task_graph_records import graph


CLI = Path(__file__).resolve().parents[1] / "lib/task_graph_cli.py"
AGENT = {"host": "codex", "agent_id": "/fixture/original"}
OTHER = {"host": "codex", "agent_id": "/fixture/other"}


class TaskIntentTest(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory())).resolve()
        self.record = self.root / "authoritative.json"
        self.write(graph())

    def write(self, value):
        self.record.write_text(json.dumps(value), encoding="utf-8")

    def current(self):
        return json.loads(self.record.read_bytes())

    def sha(self):
        return hashlib.sha256(self.record.read_bytes()).hexdigest()

    def cli(self, command, *args, patch=None, ok=True):
        result = subprocess.run([sys.executable, "-B", str(CLI), command, "--input", str(self.record), *args],
                                input=json.dumps(patch), text=True, capture_output=True, cwd=self.root)
        self.assertEqual(0 if ok else 2, result.returncode, result.stderr + result.stdout)
        return json.loads(result.stdout if ok else result.stderr)

    def update(self, ops, *, target="api", ok=True, expected=None):
        before = self.record.read_bytes()
        result = self.cli("update", "--patch", "-", "--expect-sha256", expected or self.sha(),
                          patch={"tasks": {target: ops}}, ok=ok)
        if not ok:
            self.assertEqual(before, self.record.read_bytes())
        return result

    def claim(self):
        basis = self.sha()
        self.update({"claim": {"previous_sha256": basis}})
        return basis

    def bind(self):
        self.update({"set": {"agent_ref": AGENT}})

    def revise(self, goal):
        self.update({"revise": {"set": {"goal": goal}, "source": "user:fixture-confirmed-change"}})

    def ack(self, revision=1, agent=AGENT, *, ok=True):
        self.update({"ack_revision": {"revision": revision, "agent_ref": agent,
                                      "delivery_source": f"native:message/{revision}",
                                      "ack_source": f"native:response/{revision}"}}, ok=ok)

    def test_withdrawal_blocks_dependent_handoff_and_preserves_independent_candidate(self):
        value = graph()
        writer = value["tasks"][0]
        # 增加一个无关证据项及一个确实依赖 Writer 的阅读项；两者无文件所有权。
        for name, deps in (("independent", []), ("dependent", ["api"])):
            item = v2_task({"id": name, "request_id": writer["request_id"], "task_type": "read_only",
                            "depends_on": deps, "blocks": [], "gates": [], "owned_paths": [],
                            "semantic_locks": [], "state": "DECLARED"})
            value["tasks"].append(item)
        writer["blocks"] = ["dependent"]
        self.write(value)
        self.update({"withdraw": {"reason": "用户撤回实现"}})
        self.assertEqual(["independent"], self.cli("ready")["ready"])
        self.assertFalse(self.cli("qa-ready")["qa_ready"])
        for task_id in ("api", "dependent"):
            self.cli("task", "--task-id", task_id, ok=False)
        self.update({"set": {"state": "RUNNING"}}, ok=False)
        self.update({"set": {"state": "BUILD_VERIFIED"}}, ok=False)
        self.update({"set": {"state": "RUNNING"}}, target="independent")
        self.assertEqual("WITHDRAWN", self.current()["tasks"][0]["state"])

    def test_bound_stop_rejects_unknown_or_other_instance_and_keeps_workspace(self):
        output = self.root / "writer-change"
        output.write_text("已经产生的更改")
        self.claim()
        self.bind()
        self.update({"withdraw": {"reason": "停止当前实现"}})
        stopped = self.current()
        self.assertTrue(active(stopped["tasks"][0]))
        self.assertIn("src/one", stopped["active_paths"])
        self.assertIn("api", stopped["active_semantic_locks"])
        self.assertFalse(self.cli("continuation", "--task-id", "api", "--host", "codex",
                                  "--observed-state", "running")["reuse_allowed"])
        for observed, original in (("unknown", AGENT), ("stopped", OTHER)):
            self.update({"confirm_stop": {"agent_ref": original, "observed_state": observed, "source": "native:stop/1"}}, ok=False)
        self.update({"set": {"state": "FAILED", "agent_retired": True}}, ok=False)
        self.update({"settle": {}}, ok=False)
        self.update({"confirm_stop": {"agent_ref": AGENT, "observed_state": "stopped", "source": "native:stop/2"}})
        final = self.current()
        self.assertFalse(active(final["tasks"][0]))
        self.assertEqual(["external/"], final["active_paths"])
        self.assertEqual(["external-lock"], final["active_semantic_locks"])
        self.assertEqual("已经产生的更改", output.read_text())
        self.update({"set": {"state": "DECLARED"}}, ok=False)

    def test_unbound_claim_can_be_recovered_after_sibling_update_and_replay_is_rejected(self):
        original = graph()
        original["tasks"].append(v2_task({"id": "sibling", "request_id": "other", "task_type": "read_only",
                                          "depends_on": [], "blocks": [], "gates": [], "owned_paths": [],
                                          "semantic_locks": [], "state": "DECLARED"}))
        self.write(original)
        first = self.claim()
        release = {"outcome": "definitely_not_created", "previous_sha256": first, "prior_state": "DECLARED"}
        self.update({"release_claim": release})
        second = self.claim()
        self.assertNotEqual(first, second)
        self.update({"release_claim": release}, ok=False)
        self.update({"set": {"state": "READY"}}, target="sibling")
        self.update({"withdraw": {"reason": "用户撤销"}})
        for outcome, basis, ok in (("unknown", second, False), ("definitely_not_created", first, False),
                                   ("definitely_not_created", second, True)):
            self.update({"confirm_uncreated": {"outcome": outcome, "previous_sha256": basis}}, ok=ok)
        self.assertEqual("WITHDRAWN", self.current()["tasks"][0]["state"])
        # 老的无基线领取能够在撤回后补绑实际实例，不能拿“没创建”释放已绑定的宿主。
        self.write(graph())
        self.update({"set": {"state": "RUNNING"}})
        previous = self.sha()
        self.update({"withdraw": {"reason": "停止"}})
        self.bind()
        self.update({"confirm_uncreated": {"outcome": "definitely_not_created", "claimed_sha256": previous}}, ok=False)
        self.update({"confirm_stop": {"agent_ref": AGENT, "observed_state": "stopped", "source": "native:stop/3"}})

    def test_light_revision_survives_claim_ack_and_rejects_old_late_and_duplicate_results(self):
        value = export_task_pack(graph(), "api")
        value["task"]["workflow_level"] = "Light"
        self.write(value)
        self.revise("首派前选定的新目标")
        self.assertEqual(["api"], self.cli("ready")["ready"])
        self.claim()
        self.assertEqual(1, self.cli("task")["task"]["task_revision"])
        self.ack(ok=False)
        self.bind()
        self.ack()
        self.revise("运行中明确批准的第二版")
        self.ack(1, ok=False)
        self.ack(2, OTHER, ok=False)
        proof = {"revision": 2, "agent_ref": AGENT, "source": "native:result/2"}
        complete = {"set": {"state": "BUILD_VERIFIED"}, "revision_result": proof}
        self.update(complete, ok=False)
        self.ack(2)
        self.ack(2, ok=False)
        self.update({"set": {"state": "READY"}, "append": {"acceptance_evidence": ["旧结果"]},
                     "revision_result": proof}, ok=False)
        self.update({"set": {"state": "BUILD_VERIFIED"}}, ok=False)
        self.update({"append": {"output_contracts": ["未经确认的修改"]}}, ok=False)
        for stale in ({**proof, "revision": 1}, {**proof, "agent_ref": OTHER}):
            self.update({**complete, "revision_result": stale}, ok=False)
        self.update(complete)
        self.assertEqual("BUILD_VERIFIED", self.current()["task"]["state"])
        self.assertEqual(proof, self.current()["task"]["revision_result"])
        self.update(complete, ok=False)
        self.update({"set": {"state": "DECLARED"}}, ok=False)
        self.update({"revise": {"set": {"goal": "新任务"}, "source": "user:later"}}, ok=False)
        self.update({"set": {"input_contracts": ["替换已接受合同"]}}, ok=False)
        with self.assertRaisesRegex(ValueError, "authoritative update"):
            records.publish(self.record, json.dumps(value).encode(), self.sha())

    def test_revised_evidence_rejects_old_pack_even_with_current_result_envelope(self):
        # 使用原结算器真正读取的独立文件和摘要；把旧包外层改标为新版仍应失败。
        from tests.test_task_settlement import TaskSettlementTest
        fixture = TaskSettlementTest()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        self.record = fixture.source
        _, stale = fixture.fixture()
        self.revise("只读证据需要覆盖新版输入")
        current = self.current()["tasks"][0]
        agent = current["agent_ref"]
        self.ack(agent=agent)
        proof = {"revision": 1, "agent_ref": agent, "source": "native:verified-evidence"}
        self.update({**stale["tasks"]["api"], "revision_result": proof}, ok=False)
        pack = self.cli("task", "--task-id", "api")
        fixture.accepted.write_text(json.dumps(pack))
        settle = fixture.settlement_patch(current)["tasks"]["api"]
        self.update(settle, ok=False)
        self.update({**settle, "revision_result": proof})
        self.assertEqual("RESULT_VERIFIED", self.current()["tasks"][0]["state"])

    def test_pool_claim_preserves_frozen_qa_and_both_checkpoints_require_original_reviewer(self):
        from tests.test_foundation_qa import FoundationQATest
        from lib.foundation_qa import current_request_receipt

        for staged in (False, True):
            with self.subTest(staged=staged):
                fixture = FoundationQATest()
                fixture.setUp()
                self.addCleanup(fixture.doCleanups)
                self.root = fixture.root
                self.record = self.root / "qa-graph.json"
                source = fixture.source if staged else fixture.freeze(fixture.ordinary_source())
                self.write(source)
                qa = source["tasks"][2]
                args = ["--root", str(self.root), "--pm-id", "codex:qa-fixture", "--record", str(self.record),
                        "--expect-sha256", self.sha()]
                # 必须经过池的真实 register/claim。旧的 set.state 没有领取基线，
                # 无法复现“冻结后领取”误使 QA 范围过期。
                for command in (["register", *args], ["claim", *args, "--request-id", qa["request_id"],
                        "--task-id", qa["id"], "--configured-subagents", "2", "--configured-writers", "1",
                        "--host-available-subagents", "2"]):
                    result = subprocess.run([sys.executable, "-B", str(CLI.with_name("task_pool_cli.py")), *command],
                                            cwd=self.root, env={**os.environ, "TMPDIR": str(self.root)},
                                            text=True, capture_output=True)
                    self.assertEqual(0, result.returncode, result.stderr)
                self.update({"set": {"agent_ref": AGENT}}, target="qa")
                claimed = self.current()["tasks"][2]
                self.assertIn("claim_basis_sha256", claimed)
                self.assertEqual(qa.get("qa_review_revision"), claimed.get("qa_review_revision"))
                proof = {}
                if staged:
                    self.update({"revise": {"set": {"goal": "核查基础设施及完整请求"}, "source": "user:stage-review"}}, target="qa")
                    self.update({"ack_revision": {"revision": 1, "agent_ref": AGENT, "delivery_source": "native:stage",
                                                  "ack_source": "native:stage-ack"}}, target="qa")
                    proof = {"revision_result": {"revision": 1, "agent_ref": AGENT, "source": "native:stage-result"}}
                    _, _, evidence = fixture.evidence(self.current(), "foundation")
                    self.update({"accept_foundation": evidence, **proof}, target="qa")
                    proof = {"revision_result": {"revision": 1, "agent_ref": AGENT, "source": "native:final-result"}}
                    self.update({"set": {"state": "BUILD_VERIFIED"}}, target="feature")
                    # Foundation 之后恢复的是同一 Reviewer；用另一个 ID 领取或补绑
                    # 都不能取代阶段回执关联的实例。
                    self.update({"set": {"state": "QA"}}, target="qa")
                    self.update({"set": {"agent_ref": OTHER}}, target="qa", ok=False)
                _, _, evidence = fixture.evidence(self.current(), "final")
                changed = self.root / "src/foundation.py"
                original = changed.read_bytes()
                changed.write_bytes(original + b"\n# modified after QA handoff\n")
                self.update({"accept_request": evidence, **proof}, target="qa", ok=False)
                changed.write_bytes(original)
                self.update({"accept_request": evidence, **proof}, target="qa")
                accepted = self.current()
                reviewer = accepted["tasks"][2]
                self.assertEqual("QA_PASSED", reviewer["state"])
                self.assertEqual(AGENT, reviewer["request_receipt"]["agent_ref"])
                self.assertTrue(current_request_receipt(accepted, reviewer, root=self.root))
                if staged:
                    self.assertEqual(AGENT, reviewer["foundation_receipt"]["agent_ref"])

    def test_revised_qa_needs_real_current_pack_and_original_reviewer_handoff(self):
        from tests.test_foundation_qa import FoundationQATest
        fixture = FoundationQATest()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        self.root = fixture.root
        self.record = self.root / "qa-record.json"
        value = fixture.start(fixture.freeze(fixture.ordinary_source()))
        self.write(value)
        _, _, old = fixture.evidence(value, "original")
        self.update({"revise": {"set": {"goal": "在本次冻结范围核对新增验收项"}, "source": "user:qa-revision"}}, target="qa")
        # Reviewer 合同发生变化后，既有范围冻结门继续生效；先按原协议冻结新版。
        self.write(fixture.freeze(self.current()))
        qa = self.current()["tasks"][2]
        self.update({"ack_revision": {"revision": 1, "agent_ref": qa["agent_ref"],
                                      "delivery_source": "native:message/reviewer", "ack_source": "native:ack/reviewer"}}, target="qa")
        proof = {"revision": 1, "agent_ref": qa["agent_ref"], "source": "native:review/new"}
        self.update({"revision_result": proof, "accept_request": old}, target="qa", ok=False)
        _, _, fresh = fixture.evidence(self.current(), "revised")
        self.update({"accept_request": fresh}, target="qa", ok=False)
        self.update({"accept_request": fresh, "revision_result": proof}, target="qa")
        self.assertEqual("QA_PASSED", self.current()["tasks"][2]["state"])
        self.update({"accept_request": fresh, "revision_result": proof}, target="qa", ok=False)

    def test_failed_revised_qa_resumes_only_after_real_refreeze_with_new_receipts(self):
        from tests.test_foundation_qa import FoundationQATest
        fixture = FoundationQATest()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        self.root = fixture.root
        self.record = self.root / "failed-qa.json"
        value = fixture.start(fixture.freeze(fixture.ordinary_source()))
        self.write(value)
        qa = value["tasks"][2]
        freeze = {"freeze_qa_scope": qa["qa_scope_ref"]}
        agent = qa["agent_ref"]
        self.update({"revise": {"set": {"goal": "审查本次补丁"}, "source": "user:review"}}, target="qa")
        self.update(freeze, target="qa")
        ack = {"revision": 1, "agent_ref": agent, "delivery_source": "native:old-send", "ack_source": "native:old-ack"}
        self.update({"ack_revision": ack}, target="qa")
        _, _, old_pack = fixture.evidence(self.current(), "pre-failure")
        old_result = {"revision": 1, "agent_ref": agent, "source": "native:failure"}
        self.update({"set": {"state": "FAILED"}, "revision_result": old_result}, target="qa")
        self.update(freeze, target="qa")
        self.update({"set": {"state": "QA"}}, target="qa", ok=False)
        self.update({"set": {"state": "DECLARED"}, "append": {"verification_commands": ["verify repaired behavior"]}},
                    target="feature")
        self.update({"set": {"state": "BUILD_VERIFIED"}}, target="feature")
        self.update({"set": {"state": "QA"}}, target="qa", ok=False)
        self.update(freeze, target="qa")
        reopened = self.current()["tasks"][2]
        self.assertEqual((2, agent, "DECLARED"), (reopened["task_revision"], reopened["agent_ref"], reopened["state"]))
        self.assertNotIn("revision_ack", reopened)
        self.assertIn("native:failure", reopened["acceptance_evidence"][-1])
        self.update({"set": {"state": "QA"}}, target="qa")
        self.update({"ack_revision": ack}, target="qa", ok=False)
        next_ack = {**ack, "revision": 2, "delivery_source": "native:rework-send", "ack_source": "native:rework-ack"}
        self.update({"ack_revision": {**next_ack, "agent_ref": OTHER}}, target="qa", ok=False)
        self.update({"ack_revision": next_ack}, target="qa")
        _, _, current_pack = fixture.evidence(self.current(), "repaired")
        self.update({"accept_request": current_pack, "revision_result": old_result}, target="qa", ok=False)
        new_result = {**old_result, "revision": 2, "source": "native:rework-pass"}
        self.update({"accept_request": old_pack, "revision_result": new_result}, target="qa", ok=False)
        self.update({"accept_request": current_pack, "revision_result": new_result}, target="qa")
        self.assertEqual("QA_PASSED", self.current()["tasks"][2]["state"])

    def test_passed_revised_reviewer_continues_after_writer_invalidates_the_old_pass(self):
        from tests.test_foundation_qa import FoundationQATest
        fixture = FoundationQATest()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        self.root = fixture.root
        self.record = self.root / "qa-after-pass.json"
        source = fixture.start(fixture.freeze(fixture.ordinary_source()))
        self.write(source)
        qa = source["tasks"][2]
        agent = qa["agent_ref"]
        freeze = {"freeze_qa_scope": qa["qa_scope_ref"]}
        self.update({"revise": {"set": {"goal": "原 Reviewer 检查接口"}, "source": "user:contract"}}, target="qa")
        self.update(freeze, target="qa")
        ack = {"revision": 1, "agent_ref": agent, "delivery_source": "native:send/1", "ack_source": "native:ack/1"}
        self.update({"ack_revision": ack}, target="qa")
        _, _, first = fixture.evidence(self.current(), "pass-original")
        proof = {"revision": 1, "agent_ref": agent, "source": "native:pass/1"}
        self.update({"revision_result": proof, "accept_request": first}, target="qa")
        self.update({"set": {"state": "QA"}}, target="qa", ok=False)
        self.update({"set": {"state": "DECLARED"}, "append": {"verification_commands": ["check real amendment"]}},
                    target="feature")
        self.update({"set": {"state": "BUILD_VERIFIED"}}, target="feature")
        self.assertEqual("DECLARED", self.current()["tasks"][2]["state"])
        self.update({"set": {"state": "QA"}}, target="qa", ok=False)
        self.update(freeze, target="qa")
        self.update({"set": {"state": "QA"}}, target="qa")
        self.update({"ack_revision": {**ack, "revision": 2, "delivery_source": "native:send/2",
                                      "ack_source": "native:ack/2"}}, target="qa")
        _, _, second = fixture.evidence(self.current(), "pass-amended")
        self.update({"revision_result": proof, "accept_request": first}, target="qa", ok=False)
        self.update({"revision_result": {**proof, "revision": 2, "source": "native:pass/2"},
                     "accept_request": second}, target="qa")
        self.assertEqual(agent, self.current()["tasks"][2]["request_receipt"]["agent_ref"])

    def test_revised_review_without_freeze_uses_real_foundation_or_integration_checkpoint(self):
        from lib.delivery.worktree_cli import create, git, head, scope
        from tests.test_foundation_qa import FoundationQATest, handoff
        from lib.foundation_qa import current_request_receipt, valid_receipt

        for integrated in (False, True):
            with self.subTest(integrated=integrated):
                fixture = FoundationQATest()
                fixture.setUp()
                self.addCleanup(fixture.doCleanups)
                self.root = fixture.root
                self.record = self.root / "qa-graph.json"
                value = fixture.ordinary_source() if integrated else fixture.source
                request_id = value["request_id"]
                if integrated:
                    # 候选库、Writer 和集成目录都是真实链接的 Git worktree。只更新原
                    # Writer 的产物、对应提交和验证记录，避免虚构 head 或绕开集成门。
                    outside = Path(self.enterContext(tempfile.TemporaryDirectory())).resolve()
                    git(self.root, "init", "-b", "main")
                    git(self.root, "config", "user.name", "QA fixture")
                    git(self.root, "config", "user.email", "fixture@example.invalid")
                    git(self.root, "add", "docs", "src", "platforms")
                    git(self.root, "commit", "-m", "fixture baseline")
                    base = head(self.root)
                    for task in value["tasks"][:2]:
                        task["execution_workspace"] = create(self.root, outside / task["id"], base)
                    writer = outside / "feature"
                    (writer / "src/feature.py").write_text("first = True")
                    git(writer, "commit", "-am", "fixture original feature")
                    tip = head(writer)
                    value["tasks"][1]["execution_workspace"]["head_revision"] = tip
                    candidate = outside / "candidate"
                    create(self.root, candidate, tip)
                    verification = {"command": "fixture-smoke", "exit_code": 0, "log_ref": "fixture:first", "head_revision": tip}
                    value["worktree_integrations"] = {request_id: {"root": str(candidate), "target_base": base,
                        "target_branch": "main", "head_revision": tip, "verification": [verification]}}
                self.write(fixture.start(value))
                qa = self.current()["tasks"][2]
                agent = qa["agent_ref"]
                self.update({"revise": {"set": {"goal": "复核当前交付物"}, "source": "user:review"}}, target="qa")
                ack = {"revision": 1, "agent_ref": agent, "delivery_source": "native:send/1", "ack_source": "native:ack/1"}
                self.update({"ack_revision": ack}, target="qa")
                _, _, old = fixture.evidence(self.current(), "old-checkpoint")
                failure = {"revision": 1, "agent_ref": agent, "source": "native:fail/1"}
                self.update({"set": {"state": "FAILED"}, "revision_result": failure}, target="qa")
                self.update({"set": {"state": "QA"}}, target="qa", ok=False)
                self.update({"freeze_qa_scope": {"repositories": []}}, target="qa", ok=False)
                owner = "feature" if integrated else "foundation"
                self.update({"set": {"state": "DECLARED"}}, target=owner)
                if integrated:
                    (writer / "src/feature.py").write_text("repaired = True")
                    git(writer, "commit", "-am", "fixture corrected feature")
                    tip = head(writer)
                    self.update({"checkpoint": tip, "set": {"state": "BUILD_VERIFIED"}}, target=owner)
                    git(candidate, "merge", "--ff-only", tip)
                    self.update({"set": {"state": "QA"}}, target="qa", ok=False)
                    self.cli("update", "--patch", "-", "--expect-sha256", self.sha(),
                             patch={"integrations": {request_id: {"head_revision": tip, "verification": [
                                 {**verification, "head_revision": tip, "log_ref": "fixture:repaired"}]}}})
                else:
                    (self.root / "src/foundation.py").write_text("repaired = True")
                    self.update({"set": {"state": "BUILD_VERIFIED"}}, target=owner)
                self.update({"set": {"state": "QA"}}, target="qa")
                self.assertEqual(2, self.current()["tasks"][2]["task_revision"])
                self.update({"ack_revision": {**ack, "revision": 2, "agent_ref": OTHER}}, target="qa", ok=False)
                self.update({"ack_revision": {**ack, "revision": 2, "delivery_source": "native:send/2",
                                              "ack_source": "native:ack/2"}}, target="qa")
                kind = "accept_request" if integrated else "accept_foundation"
                passed = {"revision": 2, "agent_ref": agent, "source": "native:pass/2"}
                self.update({kind: old, "revision_result": passed}, target="qa", ok=False)
                pack, _, fresh = fixture.evidence(self.current(), "new-checkpoint")
                if integrated:
                    # 正式集成验收要求 handoff 中的范围与从 target_base 到实际新
                    # 集成 HEAD 计算的完整 diff 完全一致。用真实 Git 对象构造该回执。
                    body = Path(fresh["task_pack"]["path"]).read_bytes()
                    current = handoff(pack, body, scope_ref={"repositories": [scope(self.root, base, tip)]})
                    path = Path(fresh["handoff"]["path"])
                    path.write_bytes(json.dumps(current).encode())
                    fresh["handoff"]["sha256"] = records.digest(path.read_bytes())
                self.update({kind: fresh, "revision_result": failure}, target="qa", ok=False)
                self.update({kind: fresh, "revision_result": passed}, target="qa")
                result = self.current()
                validate = current_request_receipt if integrated else valid_receipt
                self.assertTrue(validate(result, result["tasks"][2], root=self.root))

    def test_only_original_writer_can_repair_a_current_failed_review_finding(self):
        from tests.test_foundation_qa import FoundationQATest
        fixture = FoundationQATest()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        self.root = fixture.root
        self.record = self.root / "writer-rework.json"
        source = fixture.ordinary_source()
        source["tasks"][1]["state"] = "DECLARED"
        self.write(source)
        def writer(ops, *, ok=True):
            return self.update(ops, target="feature", ok=ok)
        writer({"set": {"state": "RUNNING"}})
        writer({"set": {"agent_ref": AGENT}})
        writer({"revise": {"set": {"goal": "核查修订后的功能"}, "source": "user:amend"}})
        ack = {"revision": 1, "agent_ref": AGENT, "delivery_source": "native:initial", "ack_source": "native:ack"}
        writer({"ack_revision": ack})
        proof = {"revision": 1, "agent_ref": AGENT, "source": "native:original-result"}
        complete = {"set": {"state": "BUILD_VERIFIED"}, "revision_result": proof}
        writer(complete)
        self.write(fixture.start(fixture.freeze(self.current())))
        _, result, failed = fixture.evidence(self.current(), "failed-writer-review")
        good_handoff = copy.deepcopy(failed)
        path = self.root / "qa-fail.json"
        result.update(audit_result="FAIL", review_details={"findings": [{
            "severity": "P1", "blocking": True, "detail": "修订后的行为仍缺少返回值",
            "evidence_refs": ["diff:src/feature.py:21", "log:observed"], "owner_role": "xy-web",
            "next_step": "修正原功能的缺陷并使用现有证据验证"}], "verification": []})
        path.write_bytes(json.dumps(result).encode())
        failed["handoff"] = {"path": str(path), "sha256": records.digest(path.read_bytes())}
        request = {**failed, "reviewer_id": "qa", "finding_index": 0, "affected_path": "src/feature.py"}
        writer({"rework_from_qa": request}, ok=False)
        self.update({"set": {"state": "FAILED"}}, target="qa")
        writer({"set": {"state": "DECLARED"}}, ok=False)
        writer({"rework_from_qa": {**request, **good_handoff}}, ok=False)
        writer({"rework_from_qa": {**request, "affected_path": "src/foundation.py"}}, ok=False)
        writer({"rework_from_qa": {**request, "reviewer_id": "missing"}}, ok=False)
        writer({"rework_from_qa": {**request, "finding_index": 8}}, ok=False)
        self.update({"rework_from_qa": request}, target="foundation", ok=False)
        writer({"rework_from_qa": request})
        returned = self.current()["tasks"][1]
        self.assertEqual((2, AGENT, "DECLARED"), (returned["task_revision"], returned["agent_ref"], returned["state"]))
        self.assertIn(failed["handoff"]["sha256"], returned["acceptance_evidence"][-1])
        writer({"set": {"state": "RUNNING"}})
        writer({"ack_revision": ack}, ok=False)
        writer({"ack_revision": {**ack, "revision": 2, "agent_ref": OTHER}}, ok=False)
        writer({"ack_revision": {**ack, "revision": 2, "delivery_source": "native:fix", "ack_source": "native:fix-ack"}})
        writer(complete, ok=False)
        writer({**complete, "revision_result": {**proof, "revision": 2, "source": "native:repaired"}})
        # 同一失败回执只适用于当时受审的交付；修复后即使 Reviewer 仍是 FAILED，
        # 也不可重复使用该回执再次打开已更新的 Writer。
        writer({"rework_from_qa": request}, ok=False)
        self.write(fixture.start(fixture.freeze(self.current())))
        _, _, accepted = fixture.evidence(self.current(), "accepted-writer-repair")
        self.update({"accept_request": accepted}, target="qa")
        writer({"rework_from_qa": request}, ok=False)

    def test_legacy_unbound_running_contract_cannot_change_before_binding(self):
        # 已发起的旧创建没有 claim 基线，原包仍可能正在运行。合同不变时沿旧路
        # 完成；需求已变时，首次绑定和成功态都不能替代新版的原实例回执。
        for revised in (False, True):
            with self.subTest(revised=revised):
                self.write(graph())
                self.update({"set": {"state": "RUNNING"}})
                self.update({"set": {"input_contracts": ["新增日期"]}}, ok=False)
                self.update({"append": {"output_contracts": ["增加日期列"]}}, ok=False)
                if revised:
                    self.update({"revise": {"set": {"input_contracts": ["新增日期"]}, "source": "user:date"}})
                self.bind()
                self.update({"set": {"state": "BUILD_VERIFIED"}}, ok=not revised)
                if revised:
                    self.ack()
                    self.update({"set": {"state": "BUILD_VERIFIED"},
                                 "revision_result": {"revision": 1, "agent_ref": AGENT, "source": "native:with-date"}})
                self.assertEqual("BUILD_VERIFIED", self.current()["tasks"][0]["state"])

    def test_group_withdrawal_is_atomic_and_keeps_original_confirmation_gates(self):
        value = graph()
        sibling = copy.deepcopy(value["tasks"][0])
        sibling.update(id="sibling", owned_paths=["src/two"], semantic_locks=[])
        for doc in sibling["controlled_document_access"]["documents"]:
            doc["applies_to"] = ["src/two"]
        value["tasks"].append(sibling)
        self.write(value)
        self.claim()
        self.bind()
        self.update({"set": {"input_contracts": ["试图绕开修订回执"]}}, ok=False)
        self.revise("修订后仍受原批准和拥有的路径约束")
        before = self.sha()
        self.cli("update", "--patch", "-", "--expect-sha256", before, ok=False,
                 patch={"tasks": {"api": {"withdraw": {"reason": "用户撤回"}}, "missing": {"withdraw": {"reason": "用户撤回"}}}})
        self.assertEqual(before, self.sha())
        self.cli("update", "--patch", "-", "--expect-sha256", before, patch={"tasks": {
            key: {"withdraw": {"reason": "用户撤回整项请求"}} for key in ("api", "sibling")}})
        self.assertEqual(["STOP_REQUESTED", "WITHDRAWN"], [t["state"] for t in self.current()["tasks"]])
        value["approved_gates"] = []
        self.write(value)
        self.revise("等待原有批准门")
        self.assertEqual([], self.cli("ready")["ready"])
        self.cli("task", "--task-id", "api", ok=False)
        self.update({"claim": {"previous_sha256": self.sha()}}, ok=False)
