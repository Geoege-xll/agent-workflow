"""只用request自有夹具验证原记录原子结算；原生模型观察由独立补验负责。"""

from __future__ import annotations

import copy
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from lib import task_graph_records as records
from lib.agent_continuation import active, continuation
from lib.task_graph import TaskGraphError, Task, validate_graph
from lib.task_graph_cli import _execute, export_task_pack, pack_snapshot, replace_pack_task
from tests.test_agent_continuation import PACK, PYTHON
from tests.test_dispatch_admission import plugin_fixture, plugin_helper
from tests.test_task_graph_records import graph


class TaskSettlementTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="settlement-", dir=os.environ.get("AWF_TEST_SCRATCH"))
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.source = self.root / "record.json"
        self.accepted = self.root / "accepted-pack.json"
        self.evidence = self.root / "result.log"
        # 此处是明确标记的测试输入，不能被作为真实原生完成或模型运行证据。
        self.evidence.write_bytes(b"fixture native completion and verification output\n")

    def fixture(self, *, kind="evidence", light=False, downstream=False):
        payload = graph()
        task = payload["tasks"][0]
        task.update(task_type=kind, state="RUNNING", agent_ref={"host": "codex", "agent_id": "fixture-native-a"})
        payload.update(active_paths=["src/one", "external/"], active_semantic_locks=["api", "external-lock"])
        if downstream:
            other = copy.deepcopy(task)
            other.update(id="next", agent_alias="fixture-next", task_type="read_only", state="DECLARED",
                         depends_on=["api"], blocks=[])
            other.pop("agent_ref")
            task["blocks"] = ["next"]
            payload["tasks"].append(other)
        if light:
            payload = export_task_pack(payload, "api")
            payload["task"]["workflow_level"] = "Light"
        self.source.write_text(json.dumps(payload), encoding="utf-8")
        pack = copy.deepcopy(payload) if light else export_task_pack(payload, "api")
        self.accepted.write_text(json.dumps(pack), encoding="utf-8")
        return payload, self.settlement_patch(task)

    def settlement_patch(self, task):
        """仅为当前已冻结接受包构造结果夹具；不声称执行了真实原生模型。"""
        evidence = {"path": str(self.evidence), "sha256": records.digest(self.evidence.read_bytes())}
        sha = records.digest(self.accepted.read_bytes())
        reference = task["agent_ref"]
        value = {"schema_version": 1, "agent_ref": reference,
                 "task_pack": {"path": str(self.accepted), "sha256": sha},
                 "completion": {"state": "completed", "agent_ref": reference, "task_pack_sha256": sha, "evidence": evidence},
                 "result": {"task_pack_sha256": sha, "evidence": [evidence]},
                 "verification": [{"command": task["verification_commands"][0], "exit_code": 0, "evidence": evidence}],
                 "retire": True}
        return {"tasks": {"api": {"settle": value}}}

    def first_dispatch(self, *, kind="evidence", light=False):
        """真实走claim、导出未绑定包和单独bind；原生create返回值只用明确夹具表示。

        这与从已绑定记录反造接受包不同：传给新实例的原字节在create之前已固定，
        后续绑定和交接评估不得改写它，也不能为补入创建后才有的ID要求重新接受。
        """
        from lib.dispatch_admission_cli import admission
        payload = graph()
        task = payload["tasks"][0]
        task["task_type"] = kind
        if light:
            payload = export_task_pack(payload, "api")
            payload["task"]["workflow_level"] = "Light"
        self.source.write_text(json.dumps(payload), encoding="utf-8")
        manifest = {"schema_version": 1, "project_root": str(self.root),
                    "records": [{"path": str(self.source), "sha256": records.digest(self.source.read_bytes()),
                                 "execution_roots": {"api": str(self.root)}}],
                    "capacity": {"configured_subagents": 2, "configured_writers": 1,
                                 "host_available_subagents": 2}}
        claim = admission("claim", manifest, {"record": str(self.source), "request_id": task["request_id"], "task_id": "api"})
        self.assertEqual("claimed", claim["status"])
        command = [*PYTHON, str(PACK / "lib/task_graph_cli.py"), "task", "--input", str(self.source),
                   "--output", str(self.accepted), "--expect-sha256", "missing"]
        if not light:
            command.extend(["--task-id", "api"])
        exported = subprocess.run(command, text=True, capture_output=True, timeout=60)
        self.assertEqual(0, exported.returncode, exported.stdout + exported.stderr)
        accepted = records.decode(self.accepted.read_bytes())
        self.assertEqual("RUNNING", accepted["task"]["state"])
        self.assertNotIn("agent_ref", accepted["task"])
        # 本夹具没有调用宿主工具；该ID只模拟create成功之后可观察到的返回值。
        reference = {"host": "codex", "agent_id": "fixture-native-first-create"}
        current = records.decode(self.source.read_bytes())
        bound, _ = self.invoke(current, {"tasks": {"api": {"set": {"agent_ref": reference}}}})
        self.assertEqual(0, bound.returncode, bound.stderr)
        current = records.decode(self.source.read_bytes())
        task = current.get("task") or current["tasks"][0]
        return current, self.settlement_patch(task)

    def update(self, payload, patch):
        if "task" not in payload:
            return records.update(payload, patch, None, _execute)
        def validate(command, candidate):
            return _execute(command, replace_pack_task(payload, candidate["tasks"][0]))
        result = records.update(pack_snapshot(payload), patch, None, validate)
        return replace_pack_task(payload, result["tasks"][0])

    def invoke(self, payload, patch, *, command=None, environment=None, cwd=PACK, expected=None):
        """真正通过保护CLI的已有update传输新操作，失败必须留下完整原记录。"""
        self.source.write_text(json.dumps(payload), encoding="utf-8")
        before = self.source.read_bytes()
        result = subprocess.run([*(command or [*PYTHON, str(PACK / "lib/task_graph_cli.py")]),
                                 "update", "--input", str(self.source), "--expect-sha256", expected or records.digest(before),
                                 "--patch", "-"], input=json.dumps(patch), cwd=cwd, env=environment,
                                text=True, capture_output=True, check=False, timeout=60)
        return result, before

    def test_both_result_types_settle_full_and_light_release_only_owned_activity(self):
        for kind in ("read_only", "evidence"):
            for light in (False, True):
                payload, patch = self.fixture(kind=kind, light=light)
                before = copy.deepcopy(payload)
                result, _ = self.invoke(payload, patch)
                self.assertEqual(0, result.returncode, result.stderr)
                updated = records.decode(self.source.read_bytes())
                task = updated.get("task") or updated["tasks"][0]
                self.assertEqual("RESULT_VERIFIED", task["state"])
                self.assertTrue(task["agent_retired"])
                self.assertEqual(before.get("task", before.get("tasks", [None])[0])["agent_ref"], task["agent_ref"])
                self.assertFalse(active(task))
                self.assertEqual("blocked", continuation(task, "codex", "idle")["action"])
                self.assertIn("RESULT_VERIFIED settlement:", task["acceptance_evidence"][-1])
                if not light:
                    self.assertEqual(["external/"], updated["active_paths"])
                    self.assertEqual(["external-lock"], updated["active_semantic_locks"])
                self.assertEqual(before, payload)

    def test_first_native_creation_accepts_pre_binding_pack_and_legitimate_closeout_metadata(self):
        for kind in ("read_only", "evidence"):
            for light in (False, True):
                with self.subTest(kind=kind, light=light):
                    self.accepted.unlink(missing_ok=True)
                    payload, change = self.first_dispatch(kind=kind, light=light)
                    accepted_bytes = self.accepted.read_bytes()
                    metadata = {"handoff_assessment": {"independent_qa": "not_required" if light else "required",
                                "documentation": "not_required", "reason": "当前只读结果的实际交接评估"},
                                "acceptance_evidence": ["已核实当前结果，完整证据保留在结果日志"]}
                    recorded, _ = self.invoke(payload, {"tasks": {"api": {"set": metadata}}})
                    self.assertEqual(0, recorded.returncode, recorded.stderr)
                    current = records.decode(self.source.read_bytes())
                    settled, _ = self.invoke(current, change)
                    self.assertEqual(0, settled.returncode, settled.stderr)
                    task = records.decode(self.source.read_bytes())
                    task = task.get("task") or task["tasks"][0]
                    self.assertEqual("RESULT_VERIFIED", task["state"])
                    self.assertEqual(metadata["acceptance_evidence"], task["acceptance_evidence"][:-1])
                    self.assertEqual(accepted_bytes, self.accepted.read_bytes())

    def test_pre_binding_acceptance_keeps_scope_approvals_and_completion_identity_strict(self):
        payload, change = self.first_dispatch()
        mutations = (
            lambda p, s: p["tasks"][0]["input_contracts"].append("未被原实例接受的新范围"),
            lambda p, s: p.update(approved_gates=[]),
            lambda p, s: s["completion"].update(agent_ref={"host": "codex", "agent_id": "other-native-instance"}),
        )
        for index, mutate in enumerate(mutations):
            current, patch_value = copy.deepcopy(payload), copy.deepcopy(change)
            mutate(current, patch_value["tasks"]["api"]["settle"])
            with self.subTest(index=index):
                rejected, before = self.invoke(current, patch_value)
                self.assertEqual(2, rejected.returncode, rejected.stdout + rejected.stderr)
                self.assertEqual(before, self.source.read_bytes())

    def test_bound_accepted_pack_cannot_claim_another_native_identity_or_drop_contract(self):
        for mutation in ("wrong-reference", "empty-task"):
            payload, change = self.fixture()
            pack = records.decode(self.accepted.read_bytes())
            if mutation == "wrong-reference":
                pack["task"]["agent_ref"] = {"host": "codex", "agent_id": "other-native-instance"}
            else:
                pack["task"] = {}
            self.accepted.write_text(json.dumps(pack), encoding="utf-8")
            sha = records.digest(self.accepted.read_bytes())
            value = change["tasks"]["api"]["settle"]
            value["task_pack"]["sha256"] = sha
            value["completion"]["task_pack_sha256"] = sha
            value["result"]["task_pack_sha256"] = sha
            with self.subTest(mutation=mutation):
                rejected, before = self.invoke(payload, change)
                self.assertEqual(2, rejected.returncode, rejected.stdout + rejected.stderr)
                self.assertEqual(before, self.source.read_bytes())

    def test_refuses_unknown_running_old_scope_unbound_and_failed_or_changed_evidence(self):
        mutations = (
            lambda p, s: s["completion"].update(state="running"),
            lambda p, s: s["completion"].update(state="unknown"),
            lambda p, s: s["completion"].update(agent_ref={"host": "codex", "agent_id": "other"}),
            lambda p, s: s.update(agent_ref={"host": "claude", "agent_id": "fixture-native-a"}),
            lambda p, s: s["completion"].update(task_pack_sha256="0" * 64),
            lambda p, s: s["result"].update(task_pack_sha256="0" * 64),
            lambda p, s: p["tasks"][0].pop("agent_ref"),
            lambda p, s: p["tasks"][0]["input_contracts"].append("new accepted scope"),
            lambda p, s: s["verification"][0].update(exit_code=1),
            lambda p, s: s.update(verification=[]),
            lambda p, s: s["task_pack"].update(sha256="0" * 64),
            lambda p, s: s["completion"]["evidence"].update(sha256="0" * 64),
            lambda p, s: s["result"].update(evidence=[]),
            lambda p, s: s.update(retire="true"),
            lambda p, s: p.update(approved_gates=[]),
            lambda p, s: p["standards_contract"].update(index_fingerprint="f" * 64),
        )
        for index, mutate in enumerate(mutations):
            payload, patch = self.fixture()
            mutate(payload, patch["tasks"]["api"]["settle"])
            with self.subTest(index=index), self.assertRaises((TaskGraphError, ValueError)):
                self.update(payload, patch)
        payload, patch = self.fixture()
        self.evidence.unlink()
        with self.assertRaises(ValueError):
            self.update(payload, patch)

    def test_safe_pack_read_rejects_links_duplicate_json_and_oversized_inputs(self):
        payload, patch = self.fixture()
        target = self.root / "pack-target.json"
        target.write_bytes(self.accepted.read_bytes())
        self.accepted.unlink()
        self.accepted.symlink_to(target)
        with self.assertRaises(ValueError):
            self.update(payload, patch)
        self.accepted.unlink()
        for body in (b'{"schema_version":2,"schema_version":2}', b"x" * (4 * 1024 * 1024 + 1), b"[]"):
            self.accepted.write_bytes(body)
            patch["tasks"]["api"]["settle"]["task_pack"]["sha256"] = records.digest(body)
            with self.subTest(body_size=len(body)), self.assertRaises(ValueError):
                self.update(payload, patch)

    def test_only_settle_can_enter_result_state_and_no_writer_or_qa_gate_is_bypassed(self):
        payload, patch = self.fixture()
        invalid = (
            {"tasks": {"api": {"set": {"state": "RESULT_VERIFIED"}}}},
            {"tasks": {"api": {**patch["tasks"]["api"], "set": {"state": "RUNNING"}}}},
            {**patch, "capacity": 20},
        )
        for change in invalid:
            with self.subTest(change=change), self.assertRaises(TaskGraphError):
                self.update(payload, change)
        for kind in ("writer", "qa"):
            payload, patch = self.fixture(kind=kind)
            with self.subTest(kind=kind), self.assertRaisesRegex(TaskGraphError, "read_only or evidence"):
                self.update(payload, patch)
            with self.assertRaisesRegex(TaskGraphError, "RESULT_VERIFIED"):
                validate_graph([Task("invalid", "request", task_type=kind, state="RESULT_VERIFIED")])

    def test_current_result_records_reject_legacy_writer_success_states_and_manual_completion(self):
        """3.0结果态通过身份/证据闭环产生，历史原文件仍保留为普通只读资料。"""
        for kind in ("read_only", "evidence"):
            for light in (False, True):
                for destination in ("BUILD_VERIFIED", "QA_SCOPE_READY", "QA", "RESULT_VERIFIED"):
                    payload, _ = self.fixture(kind=kind, light=light)
                    change = {"tasks": {"api": {"set": {"state": destination}}}}
                    rejected, before = self.invoke(payload, change)
                    self.assertEqual(2, rejected.returncode, rejected.stdout + rejected.stderr)
                    self.assertEqual(before, self.source.read_bytes())
                    if destination != "RESULT_VERIFIED":
                        task = payload.get("task") or payload["tasks"][0]
                        task["state"] = destination
                        with self.assertRaisesRegex(TaskGraphError, "RESULT_VERIFIED"):
                            _execute("validate", payload)


    def _assert_record_evidence_alias_rejected(self, alias: Path):
        """真实原CLI分别验证所有证据位置，拒绝发生在发布前且原文件字节不变。"""
        for field in ("task_pack", "completion", "result", "verification"):
            payload, patch = self.fixture(light=True)
            settle = patch["tasks"]["api"]["settle"]
            source = {"path": str(alias), "sha256": records.digest(self.source.read_bytes())}
            if field == "task_pack":
                settle["task_pack"] = source
                settle["completion"]["task_pack_sha256"] = source["sha256"]
                settle["result"]["task_pack_sha256"] = source["sha256"]
            elif field == "result":
                settle["result"]["evidence"] = [source]
            elif field == "verification":
                settle["verification"][0]["evidence"] = source
            else:
                settle["completion"]["evidence"] = source
            with self.subTest(field=field):
                rejected, before = self.invoke(payload, patch)
                self.assertEqual(2, rejected.returncode, rejected.stdout + rejected.stderr)
                self.assertIn("physically independent", rejected.stderr)
                self.assertEqual(before, self.source.read_bytes())
                self.assertFalse(list(self.root.glob(".*.workflow-*")))

    def test_publish_rejects_original_record_as_any_new_settlement_evidence(self):
        self._assert_record_evidence_alias_rejected(self.source)



    def test_evidence_changed_after_settlement_calculation_is_rejected_inside_publish_lock(self):
        """模拟计算成功到CAS之间的真实证据漂移，原记录和临时发布文件都须保留原状。"""
        payload, change = self.fixture(light=True)
        before = self.source.read_bytes()
        settled = self.update(payload, change)
        self.evidence.write_bytes(b"changed evidence after acceptance calculation\n")
        with self.assertRaisesRegex(TaskGraphError, "fingerprint changed"):
            records.publish(self.source, json.dumps(settled).encode("utf-8"), records.digest(before))
        self.assertEqual(before, self.source.read_bytes())
        self.assertFalse(list(self.root.glob(".*.workflow-*")))

    def test_independent_snapshots_survive_and_ordinary_publication_contract_is_unchanged(self):
        payload, patch = self.fixture(light=True)
        pack_bytes, log_bytes = self.accepted.read_bytes(), self.evidence.read_bytes()
        result, _ = self.invoke(payload, patch)
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        self.assertEqual(pack_bytes, self.accepted.read_bytes())
        self.assertEqual(log_bytes, self.evidence.read_bytes())
        self.assertEqual(patch["tasks"]["api"]["settle"]["task_pack"]["sha256"], records.digest(self.accepted.read_bytes()))
        # 普通bytes/JSON和新文件不是结算协议；不以字节魔法更改publish API。
        ordinary = self.root / "ordinary.json"
        for body in (b"ordinary bytes\n", b'{"ordinary":true}', b'{"ordinary":false}',
                     b'{"schema_version":2,"task":{"id":"ordinary","state":"RUNNING","task_type":[]}}',
                     b'{"schema_version":2,"task":{"id":"ordinary","state":"RESULT_VERIFIED","task_type":[]}}'):
            expected = records.digest(ordinary.read_bytes()) if ordinary.exists() else "missing"
            self.assertTrue(records.publish(ordinary, body, expected))
            self.assertEqual(body, ordinary.read_bytes())
            self.assertFalse(records.publish(ordinary, body, records.digest(body)))
        exported = self.root / "completed-export.json"
        self.assertTrue(records.publish(exported, self.source.read_bytes(), "missing"))
        # 后续非结算更新不重查所有历史来源；本测试只删除自有日志模拟过期来源。
        completed = records.decode(self.source.read_bytes())
        completed["task"]["acceptance_evidence"].append("ordinary later evidence reference")
        self.evidence.unlink()
        self.assertTrue(records.publish(self.source, json.dumps(completed).encode("utf-8"),
                                        records.digest(self.source.read_bytes())))

    def test_completed_scope_change_requires_pending_and_retirement_does_not_complete_running(self):
        payload, patch = self.fixture()
        retired = self.update(payload, {"tasks": {"api": {"set": {"agent_retired": True}}}})
        self.assertTrue(active(retired["tasks"][0]))
        self.assertEqual(set(payload["active_paths"]), set(retired["active_paths"]))
        completed = self.update(retired, patch)
        with self.assertRaisesRegex(TaskGraphError, "pending state"):
            self.update(completed, {"tasks": {"api": {"append": {"input_contracts": ["new scope"]}}}})
        with self.assertRaisesRegex(TaskGraphError, "retired"):
            self.update(completed, {"tasks": {"api": {"set": {"state": "RUNNING"}}}})
        self.assertFalse(_execute("qa-ready", completed)["qa_ready"])

    def test_declared_expected_negative_control_and_observation_only_need_no_fake_shell_check(self):
        for commands in ([], [{"run": "fixture-negative", "expected": "demonstrate declared failure"}]):
            payload, patch = self.fixture()
            payload["tasks"][0]["verification_commands"] = commands
            self.accepted.write_text(json.dumps(export_task_pack(payload, "api")), encoding="utf-8")
            settle = patch["tasks"]["api"]["settle"]
            sha = records.digest(self.accepted.read_bytes())
            settle["task_pack"]["sha256"] = sha
            settle["completion"]["task_pack_sha256"] = sha
            settle["result"]["task_pack_sha256"] = sha
            settle["verification"] = [] if not commands else [{"command": "fixture-negative", "exit_code": 1,
                "expected": commands[0]["expected"], "evidence": settle["completion"]["evidence"]}]
            self.assertEqual("RESULT_VERIFIED", self.update(payload, patch)["tasks"][0]["state"])

    def test_source_cli_stale_cas_keeps_original_and_success_unblocks_downstream(self):
        payload, patch = self.fixture(downstream=True)
        failed, before = self.invoke(payload, patch, expected="0" * 64)
        self.assertEqual(2, failed.returncode)
        self.assertEqual(before, self.source.read_bytes())
        passed, _ = self.invoke(payload, patch)
        self.assertEqual(0, passed.returncode, passed.stderr)
        updated = records.decode(self.source.read_bytes())
        self.assertEqual(["next"], _execute("ready", updated)["ready"])

    def test_real_plugin_settlement_releases_record_slot_and_rejects_old_pack_binding(self):
        """真实当前插件helper结算原记录；不运行旧中央安装器，不生成pin。"""
        project = self.root / "project"
        project.mkdir()
        # 本例要证明任务释放自有资源后，仍保留的外部锁不会阻塞独立现有资源。
        # 必须提供真实资源节点：Linux无法从空目录只读确认未来名称规则，不存在
        # 的src/one和external/会正确地共同保守锁住项目父树，不能把它误作未释放。
        (project / "src/one").mkdir(parents=True)
        (project / "external").mkdir()
        installed = plugin_fixture(self.root)
        environment = {key: value for key, value in os.environ.items()
                       if not key.startswith("AGENT_WORKFLOW_") and key != "PYTHONPATH"}
        payload, change = self.fixture(downstream=True)
        command = plugin_helper(installed, project, "lib/task_graph_cli.py")
        admission = plugin_helper(installed, project, "lib/dispatch_admission_cli.py")
        manifest = self.root / "manifest.json"
        data = {"schema_version": 1, "project_root": str(project), "records": [],
                "capacity": {"configured_subagents": 1, "configured_writers": 1, "host_available_subagents": 1}}
        def view():
            data["records"] = [{"path": str(self.source), "sha256": records.digest(self.source.read_bytes()),
                                "execution_roots": {"api": str(project), "next": str(project)}}]
            manifest.write_text(json.dumps(data), encoding="utf-8")
            observed = subprocess.run([*admission, "view", "--input", str(manifest)], cwd=project,
                                      env=environment, text=True, capture_output=True, timeout=60)
            self.assertEqual(0, observed.returncode, observed.stdout + observed.stderr)
            return json.loads(observed.stdout)
        self.assertEqual(1, view()["active_subagents"])
        accepted_bytes = self.accepted.read_bytes()
        accepted = json.loads(accepted_bytes)
        accepted["runtime_binding"] = {"unexpected": "old central record"}
        self.accepted.write_text(json.dumps(accepted), encoding="utf-8")
        rejected_change = copy.deepcopy(change)
        settle = rejected_change["tasks"]["api"]["settle"]
        wrong_sha = records.digest(self.accepted.read_bytes())
        settle["task_pack"]["sha256"] = wrong_sha
        settle["completion"]["task_pack_sha256"] = wrong_sha
        settle["result"]["task_pack_sha256"] = wrong_sha
        rejected, before = self.invoke(payload, rejected_change, command=command, environment=environment, cwd=project)
        self.assertEqual(2, rejected.returncode, rejected.stdout + rejected.stderr)
        self.assertIn("runtime_binding", rejected.stderr)
        self.assertEqual(before, self.source.read_bytes())
        self.accepted.write_bytes(accepted_bytes)
        result, _ = self.invoke(payload, change, command=command, environment=environment, cwd=project)
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        after = view()
        self.assertEqual(0, after["active_subagents"])
        self.assertEqual(0, after["active_writers"])
        self.assertEqual(["next"], [candidate["task_id"] for candidate in after["candidates"]],
                         json.dumps(after, ensure_ascii=False, sort_keys=True))
        # 独立包的真实CLI已覆盖当前卷；额外固定“名称规则未知”的文件边界，
        # 防止此夹具仅因Darwin的pathconf可用而通过，遗漏Linux空目录的保守投影。
        from lib import dispatch_admission_cli as admission_cli
        with patch.object(admission_cli, "_directory_case_sensitive", return_value=None):
            unknown_names = admission_cli.admission("view", data)
        self.assertEqual(["next"], [candidate["task_id"] for candidate in unknown_names["candidates"]],
                         json.dumps(unknown_names, ensure_ascii=False, sort_keys=True))
        print("PLUGIN_SETTLEMENT: actual packaged update/admission; RESULT_VERIFIED; record slots 1->0; native close unverified", flush=True)

    def test_settlement_keeps_external_subtree_when_future_directory_names_are_unknown(self):
        """槽位释放不能解除保留的外部父树锁，空目录继续按未知名称规则保守等待。"""
        from lib import dispatch_admission_cli as admission_cli
        project = self.root / "empty-project"
        project.mkdir()
        payload, change = self.fixture(downstream=True)
        settled, _ = self.invoke(payload, change)
        self.assertEqual(0, settled.returncode, settled.stdout + settled.stderr)
        manifest = {"schema_version": 1, "project_root": str(project),
                    "records": [{"path": str(self.source), "sha256": records.digest(self.source.read_bytes()),
                                 "execution_roots": {"api": str(project), "next": str(project)}}],
                    "capacity": {"configured_subagents": 1, "configured_writers": 1,
                                 "host_available_subagents": 1}}
        # 明确执行非Darwin的只读探测分支；这不是宣称在本机运行了真实Linux。
        # 空目录没有可观察名称，因此结果应为未知，不能为让候选通过假定其敏感。
        with patch.object(admission_cli.sys, "platform", "linux"):
            self.assertIsNone(admission_cli._directory_case_sensitive(project))
            projected = admission_cli.admission("view", manifest)
        diagnostic = json.dumps(projected, ensure_ascii=False, sort_keys=True)
        self.assertEqual(0, projected["active_subagents"], diagnostic)
        self.assertEqual(1, projected["remaining_subagent_slots"], diagnostic)
        self.assertEqual([], projected["candidates"], diagnostic)
        pending = next(item for item in projected["waiting"] if item["task_id"] == "next")
        self.assertEqual(["path_conflict"], pending["reasons"], diagnostic)
        self.assertEqual([], list(project.iterdir()))



class SettlementWorktreeConsumerTest(unittest.TestCase):
    def test_native_registered_worktree_roots_use_physical_identity(self):
        """实际Git登记解析覆盖Unicode/空格、独立HEAD/index与登记物理身份。"""
        from lib.delivery.worktree_cli import DeliveryError, common_dir, create, git, head, linked, private_dir
        with tempfile.TemporaryDirectory(prefix="registered-worktree-", dir=os.environ.get("AWF_TEST_SCRATCH")) as raw:
            root = Path(raw).resolve()
            repo, worker = root / "主 仓库", root / "独立 工作树"
            repo.mkdir()
            git(repo, "init", "-b", "main")
            git(repo, "-c", "user.name=Workflow Fixture", "-c", "user.email=fixture@example.invalid",
                "commit", "--allow-empty", "-m", "task-owned registration fixture")
            base = head(repo)
            self.assertEqual(str(worker), create(repo, worker, base)["root"])
            self.assertTrue(linked(repo, str(worker)).samefile(worker))
            self.assertTrue(common_dir(repo).samefile(common_dir(worker)))
            self.assertFalse(private_dir(repo).samefile(private_dir(worker)))
            output = git(repo, "worktree", "list", "--porcelain", "-z")
            roots = [os.fsdecode(item[len(b"worktree "):]) for item in output.split(b"\0") if item.startswith(b"worktree ")]
            print(f"NATIVE_REGISTERED_WORKTREE: native={str(worker)!r} git_roots={roots!r}; physical identity verified", flush=True)
            # 以下全部为当前request自有Git资源；不靠伪造登记输出使正向通过。
            child = worker / "子目录"
            child.mkdir()
            other = root / "其他 仓库"
            other.mkdir()
            git(other, "init", "-b", "other")
            git(repo, "branch", "ordinary-branch")
            fake = root / "复制gitfile但未登记"
            fake.mkdir()
            (fake / ".git").write_bytes((worker / ".git").read_bytes())
            for invalid in (str(repo), str(child), "ordinary-branch", str(other), str(fake), str(worker) + os.sep + "."):
                with self.subTest(invalid=invalid), self.assertRaises(DeliveryError):
                    linked(repo, invalid)
            # 即使目录仍有真实旧登记，也不能共享主checkout的私有HEAD/index。
            gitfile = worker / ".git"
            original = gitfile.read_bytes()
            before = gitfile.stat()
            with gitfile.open("r+b") as stream:
                try:
                    stream.seek(0)
                    stream.write(f"gitdir: {private_dir(repo)}\n".encode("utf-8"))
                    stream.truncate()
                    stream.flush()
                    with self.assertRaisesRegex(DeliveryError, "distinct canonical root"):
                        linked(repo, str(worker))
                finally:
                    stream.seek(0)
                    stream.write(original)
                    stream.truncate()
                    stream.flush()
            after = gitfile.stat()
            self.assertEqual(original, gitfile.read_bytes())
            self.assertEqual((before.st_dev, before.st_ino, before.st_mode), (after.st_dev, after.st_ino, after.st_mode))
            self.assertTrue(linked(repo, str(worker)).samefile(worker))

    def test_actual_merge_check_accepts_result_dependency_but_keeps_writer_qa_gates(self):
        """复用已有真实Git/验证QA夹具，只增加本变更缺失的结果依赖消费者场景。"""
        from tests.test_worktree_delivery import GitDeliveryTest
        from tests.test_scheduler_boundaries import v2_task
        from lib.delivery.worktree_cli import merge_check
        fixture = GitDeliveryTest()
        try:
            # 子Python也明确禁止pyc；既有真实Git夹具不得被验证本身制造脏文件。
            with patch.dict(os.environ, {"PYTHONDONTWRITEBYTECODE": "1"}):
                fixture.setUp()
            dependency = v2_task({"id": "result", "request_id": "req", "task_type": "read_only",
                                  "state": "RESULT_VERIFIED", "depends_on": [], "blocks": ["a"],
                                  "gates": [], "owned_paths": [], "semantic_locks": []})
            fixture.tasks[0]["depends_on"] = ["result"]
            fixture.tasks.append(dependency)
            self.assertEqual("merge_ready", merge_check(fixture.repo, fixture.config, fixture.payload)["status"])
        finally:
            fixture.doCleanups()


if __name__ == "__main__":
    unittest.main()
