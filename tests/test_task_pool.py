"""通过真实独立 CLI 进程验证 PM 私有登记、原件恢复、容量和有界归档。"""

import concurrent.futures
import copy
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock
from uuid import uuid4

from lib import task_graph_records, task_pool
from lib.hosts import antigravity_dispatch
from lib.task_graph_cli import export_task_pack
from lib.task_graph_records import digest
from tests.test_task_graph_records import graph


PACK = Path(__file__).resolve().parents[1]


class TaskPoolTest(unittest.TestCase):
    def setUp(self):
        directory = self.enterContext(tempfile.TemporaryDirectory(dir=os.environ.get("AWF_TEST_SCRATCH")))
        self.work = Path(directory).resolve()
        self.root = self.work / "project"
        self.root.mkdir()
        (self.root / "src").mkdir()
        (self.root / "src/known").touch()
        self.pm = "codex:conversation-A"
        self.capacity = ["--configured-subagents", "2", "--configured-writers", "1",
                         "--host-available-subagents", "2"]
        # 子进程各自启动、退出，只共享当前测试所属的系统 scratch，绝不碰宿主 PM 的索引。
        self.env = {k: v for k, v in os.environ.items() if not k.startswith("AGENT_WORKFLOW_")}
        self.env.update(TMPDIR=str(self.work), PYTHONDONTWRITEBYTECODE="1")

    def call(self, args, *, expect=0, pm=None, project=None):
        raw = subprocess.run([sys.executable, "-B", str(PACK / "lib/task_pool_cli.py"), *args,
                              "--root", str(project or self.root), "--pm-id", pm or self.pm],
                             cwd=self.root, env=self.env, capture_output=True, check=False, text=True)
        if expect is None:
            return raw
        self.assertEqual(expect, raw.returncode, raw.stderr)
        return json.loads(raw.stdout if expect == 0 else raw.stderr)

    def record(self, name, *, request=None, state="READY", level="Light", path="src/one"):
        source = graph()
        source.update(request_id=request or name, active_paths=[], active_semantic_locks=[])
        task = source["tasks"][0]
        task.update(id=name, request_id=request or name, state=state, owned_paths=[path], semantic_locks=[])
        for doc in task["controlled_document_access"]["documents"]:
            doc["applies_to"] = [path]
        if level == "Light":
            source = export_task_pack(source, name)
            source["task"]["workflow_level"] = "Light"
            source.pop("qa_checkpoint", None)
            source.pop("qa_checkpoint_fingerprint", None)
        dest = self.work / (name + ".json")  # 原记录可在项目之外的明确位置。
        self.write(dest, source)
        return dest

    def child(self, task):
        # Full 图要求无依赖 Writer 具有独立写入面；子节点及其规范覆盖一起绑定。
        child = copy.deepcopy(task)
        child.update(id="part", owned_paths=["src/part"])
        for doc in child["controlled_document_access"]["documents"]:
            doc["applies_to"] = ["src/part"]
        return child

    def write(self, dest, value):
        dest.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")

    def sha(self, path):
        return digest(path.read_bytes())

    def reg(self, path, *extra, expect=0):
        return self.call(["register", "--record", str(path), "--expect-sha256", self.sha(path), *extra], expect=expect)

    def claim(self, path, *, request=None, task_id=None, sha=None, expect=0):
        return self.call(["claim", "--record", str(path), "--request-id", request or path.stem,
                          "--task-id", task_id or path.stem, "--expect-sha256", sha or self.sha(path), *self.capacity],
                         expect=expect)

    def graph_call(self, *args, code=0, patch=None):
        result = subprocess.run(
            [sys.executable, "-B", str(PACK / "lib/task_graph_cli.py"), *args, "--root", str(self.root)],
            cwd=self.root, env=self.env, capture_output=True, text=True, check=False,
            input=json.dumps(patch) if patch is not None else None,
        )
        self.assertEqual(code, result.returncode, result.stderr or result.stdout)
        return json.loads(result.stdout if code == 0 else result.stderr)

    def test_legacy_cleanup_blocks_registered_request_even_with_original_outside_scratch(self):
        request = "protected"
        self.reg(self.record("registered", request=request))
        folder = Path(self.graph_call("scratch", "--request-id", request)["scratch_dir"])
        evidence = folder / "only-deliverable.log"
        evidence.write_text("in-use evidence")
        for select in (("--request-id", request), ("--all",)):
            with self.subTest(select=select):
                error = self.graph_call("cleanup-scratch", *select, "--dry-run", code=2)
                self.assertIn("registered", error["error"])
                self.assertTrue(evidence.is_file())
        ordinary = Path(self.graph_call("scratch", "--request-id", "ordinary")["scratch_dir"])
        (ordinary / "disposable.txt").write_text("unreferenced file")
        scan = self.graph_call("cleanup-scratch", "--request-id", "ordinary", "--dry-run")
        self.graph_call("cleanup-scratch", "--request-id", "ordinary", "--expect-sha256", scan["snapshot_sha256"])
        self.assertFalse(ordinary.exists())
        self.assertTrue(evidence.is_file())

    def test_cleanup_barrier_excludes_cross_pm_registration_and_original_update(self):
        from lib.hosts.handoff import SYSTEM_HANDOFF

        request = "closing"
        selected = self.record("done", request=request, state="BUILD_VERIFIED")
        # 核对项目根中的原件可复用登记屏障，无需再次取得同一 inode 锁。
        in_root = self.root / selected.name
        selected.rename(in_root)
        self.reg(in_root)
        peer_dir = self.work / "peer"
        peer_dir.mkdir()
        peer_record = self.record("peer")
        peer = peer_dir / peer_record.name
        peer_record.rename(peer)
        self.call(["register", "--record", str(peer), "--expect-sha256", self.sha(peer)], pm="codex:other")
        untouched = peer.read_bytes()
        newcomer_dir = self.work / "newcomer"
        newcomer_dir.mkdir()
        new_record = self.record("new", request=request)
        newcomer = newcomer_dir / new_record.name
        new_record.rename(newcomer)
        folder = Path(self.graph_call("scratch", "--request-id", request)["scratch_dir"])
        artifact = folder / "temporary.log"
        artifact.write_text("temporary")
        cleanup = ("cleanup-scratch", "--pm-id", self.pm, "--request-id", request)
        preview = self.graph_call(*cleanup, "--dry-run")
        original_cleanup = task_graph_records.cleanup_scratch
        competing_registration = ["register", "--record", str(newcomer), "--expect-sha256", self.sha(newcomer)]

        def race(*args, **kwargs):
            # 真实独立进程在引用核对之后、第一次删除之前，分别尝试加入新请求原件和改旧原件。
            denied = self.call(competing_registration, pm="codex:newcomer", expect=2)
            self.assertIn("Resource temporarily unavailable", denied["error"])
            denied = self.graph_call("update", "--input", str(peer), "--expect-sha256", self.sha(peer), "--patch", "-",
                                     patch={"tasks": {"peer": {"append": {"acceptance_evidence": [str(artifact)]}}}},
                                     code=2)
            self.assertIn("record directory is busy", denied["error"])
            return original_cleanup(*args, **kwargs)

        with mock.patch.object(tempfile, "tempdir", str(self.work)):
            with mock.patch.object(task_graph_records, "cleanup_scratch", side_effect=race):
                outcome = task_pool.cleanup_request(self.root, self.pm, request, dry_run=False, keep=(),
                                                   expected=preview["snapshot_sha256"], handoff=SYSTEM_HANDOFF)
        self.assertEqual("applied", outcome["status"])
        self.assertEqual(untouched, peer.read_bytes())
        self.assertFalse(artifact.exists())
        self.assertEqual("registered", self.call(competing_registration, pm="codex:newcomer")["status"])

    def test_cleanup_recognizes_embedded_reference_only_in_its_physical_slot(self):
        folder = Path(self.graph_call("scratch", "--request-id", "referenced")["scratch_dir"])
        other = folder.with_name(folder.name.upper())
        same_slot = other.exists() and other.samefile(folder)
        if not same_slot:
            other.mkdir()
        evidence = other / "Evidence.log"
        evidence.write_bytes(b"recorded bytes")
        sibling = folder / "disposable.tmp"
        sibling.write_bytes(b"unused")
        record = self.record("elsewhere")
        source = json.loads(record.read_bytes())
        source["task"]["acceptance_evidence"] = [f"verification output `{evidence}`"]
        self.write(record, source)
        self.reg(record)
        command = ("cleanup-scratch", "--request-id", "referenced")
        if same_slot:
            self.assertIn("referenced", self.graph_call(*command, "--dry-run", code=2)["error"])
            self.assertTrue(sibling.exists())
        else:
            preview = self.graph_call(*command, "--dry-run")
            self.graph_call(*command, "--expect-sha256", preview["snapshot_sha256"])
            self.assertFalse(sibling.exists())
        self.assertEqual(b"recorded bytes", evidence.read_bytes())

    def test_cleanup_preserves_multiple_references_through_short_temp_paths(self):
        from lib.task_closeout import keep_scratch, relative_under, verify_evidence

        # macOS 对两种系统临时根均有真实的不同深度别名。其他环境用临时目录的
        # 父链接验证文本引用；结构化原件、回执的无链接读取合同保持不变。
        bases = (self.work, Path("/private/tmp")) if sys.platform == "darwin" else (self.work,)
        for number, base in enumerate(bases):
            with self.subTest(base=base), tempfile.TemporaryDirectory(dir=base) as directory:
                self.env["TMPDIR"] = directory
                request = f"short-path-{number}"
                folder = Path(self.graph_call("scratch", "--request-id", request)["scratch_dir"])
                if sys.platform == "darwin" and folder.is_relative_to("/private"):
                    alias = Path("/") / folder.relative_to("/private")
                else:
                    parent = self.work / "aliases" / f"root-{number}"
                    parent.parent.mkdir(exist_ok=True)
                    parent.symlink_to(directory, target_is_directory=True)
                    alias = parent / folder.relative_to(directory)
                self.assertTrue(alias.samefile(folder))
                if alias.with_name(alias.name.upper()).is_dir():
                    alias = alias.with_name(alias.name.upper())
                prefix = f"{alias.parent}/./{alias.name}/"
                files = {"First proof.log": b"first", "second.log": b"second", "third.log": b"third"}
                for name, body in files.items():
                    (folder / name).write_bytes(body)
                discard = folder / "discard.tmp"
                discard.write_bytes(b"unreferenced fixture")
                external = Path(directory) / "external" / folder.name
                external.mkdir(parents=True)
                outside = external / "unrelated.log"
                outside.write_bytes(b"separate slot")
                owner = self.record(f"source-{number}", state="BUILD_VERIFIED")
                source = json.loads(owner.read_bytes())
                source["task"]["acceptance_evidence"] = [
                    f"`{prefix}./First proof.log` and `{outside}`; logs {prefix}second.log {prefix}third.log"
                ]
                self.write(owner, source)
                self.reg(owner)
                command = ("cleanup-scratch", "--request-id", request)
                self.assertIn("referenced", self.graph_call(*command, "--dry-run", code=2)["error"])
                self.reg(self.record(request, state="BUILD_VERIFIED"))
                self.assertEqual(Path("second.log"), relative_under(alias / "second.log", folder))
                with self.assertRaisesRegex(ValueError, "registered task original"):
                    task_pool.require_registered_scratch_keeps(folder, (), (alias / "second.log",))
                with self.assertRaisesRegex(ValueError, "cannot prove"):
                    keep_scratch(folder, [(owner, {"text": f"`{prefix}second.log missing`"})], ())
                with self.assertRaisesRegex(ValueError, "symlink"):
                    verify_evidence({"path": str(alias / "second.log"), "sha256": self.sha(folder / "second.log")})
                preview = self.graph_call(*command, "--pm-id", self.pm, "--dry-run")
                self.assertEqual(sorted(files), preview["kept_files"])
                self.assertEqual(["discard.tmp"], preview["candidate_sample"])
                self.graph_call(*command, "--pm-id", self.pm, "--expect-sha256", preview["snapshot_sha256"])
                self.assertFalse(discard.exists())
                self.assertEqual(files, {path.name: path.read_bytes() for path in folder.iterdir()})
                self.assertEqual(b"separate slot", outside.read_bytes())

    def test_two_full_closeouts_preserve_current_qa_contract_and_allow_cleanup(self):
        from lib.foundation_qa import current_request_receipt
        from lib.solution_confirmation import bind_decisions, decision_gates
        from tests.test_foundation_qa import FoundationQATest

        fixture = FoundationQATest()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        self.root = fixture.root
        source = fixture.ordinary_source()
        writer = source["tasks"][0]
        writer["agent_ref"] = {"host": "codex", "agent_id": "writer-foundation"}
        writer["solution_decisions"] = [{"id": "route", "content": "使用现有分页入口"}]
        bind_decisions(writer)
        gate = decision_gates(writer)["route"]
        source["approved_gates"].append(gate)
        source["solution_approval_sources"] = {gate: "user:fixture-current-decision"}
        source = fixture.start(fixture.freeze(source))
        _, _, refs = fixture.evidence(source, "before-closeout")
        source = fixture.update(source, "qa", {"accept_request": refs})
        self.assertTrue(current_request_receipt(source, source["tasks"][2], root=self.root))
        request = source["tasks"][2]["request_id"]
        folder = Path(self.graph_call("scratch", "--request-id", request)["scratch_dir"])
        saved = folder / "Evidence"
        saved.mkdir()
        other = folder.with_name(folder.name.upper()) / "eVIDENCE"
        folded = other.is_dir() and other.samefile(saved)

        def reference(path):
            return other / path.name.swapcase() if folded else path

        original, delivered, manifest, native, explicit = (saved / name for name in (
            "Graph.json", "Result.log", "Proof.json", "Native.log", "Kept.bin"))
        unused, terminal = folder / "regenerable.txt", folder / "terminal.json"
        self.write(original, source)
        delivered.write_bytes(b"verified result")
        native.write_bytes(b"observed native closure")
        explicit.write_bytes(b"manually retained")
        unused.write_text("regenerable artifact")
        self.write(manifest, [{"path": str(reference(delivered)), "sha256": self.sha(delivered)}])
        self.reg(reference(original))
        if not folded:
            # 在敏感卷上，这两个仅拼写不同的普通文件必须保持独立。
            (saved / delivered.name.swapcase()).write_bytes(b"disposable case twin")
        for task_id in (source["tasks"][0]["id"], "qa"):
            plan = self.call(["closeout", "--request-id", request, "--preservation", str(reference(manifest))])
            self.assertEqual("ready", plan["status"], plan.get("reason"))
            selected = next(target for target in plan["targets"] if target["task_id"] == task_id)
            self.write(terminal, {"schema_version": 1, "agent_ref": selected["agent_ref"], "outcome": "closed",
                                  "native_evidence": {"path": str(reference(native)), "sha256": self.sha(native)},
                                  "preservation": plan["preservation"]})
            result = self.call(["finish-closeout", "--request-id", request, "--task-id", task_id,
                                "--record", str(reference(original)), "--expect-sha256", selected["sha256"],
                                "--evidence", str(terminal)])
            self.assertEqual("closed", result["status"])
            reached = json.loads(original.read_bytes())
            self.assertEqual({gate: "user:fixture-current-decision"}, reached["solution_approval_sources"])
            self.assertEqual(refs["handoff"], reached["tasks"][2]["request_receipt"]["handoff"])
            self.assertTrue(current_request_receipt(reached, reached["tasks"][2], root=self.root))
            self.assertEqual([task.get("acceptance_evidence") for task in source["tasks"]],
                             [task.get("acceptance_evidence") for task in reached["tasks"]])
        # CAS 原子发布可能采纳登记时的拼写，从磁盘枚举这份最终原件的实际名字。
        preserved = {file.relative_to(folder).as_posix(): file.read_bytes() for file in saved.iterdir()
                     if folded or file.name != delivered.name.swapcase()}
        keep_name = "eVIDENCE/" + explicit.name.swapcase() if folded else explicit.relative_to(folder).as_posix()
        if not folded:
            rejected = self.graph_call("cleanup-scratch", "--pm-id", self.pm, "--request-id", request,
                                       "--keep", "Evidence/" + explicit.name.swapcase(), "--dry-run", code=2)
            self.assertIn("scratch keep path", rejected["error"])
        cleanup = ("cleanup-scratch", "--pm-id", self.pm, "--request-id", request, "--keep", keep_name)
        scan = self.graph_call(*cleanup, "--dry-run")
        self.assertEqual(set(preserved), set(scan["kept_files"]))
        self.assertIn(unused.name, scan["candidate_sample"])
        self.graph_call(*cleanup, "--expect-sha256", scan["snapshot_sha256"])
        self.assertFalse(unused.exists())
        self.assertEqual(preserved, {file.relative_to(folder).as_posix(): file.read_bytes()
                                     for file in saved.iterdir()})
        after_cleanup = json.loads(original.read_bytes())
        self.assertTrue(current_request_receipt(after_cleanup, after_cleanup["tasks"][2], root=self.root))
        self.assertEqual("ready", self.call(["closeout", "--request-id", request])["status"])
        revised = fixture.update(reached, source["tasks"][0]["id"],
                                 {"append": {"acceptance_evidence": ["changed business evidence"]}})
        self.assertFalse(current_request_receipt(revised, revised["tasks"][2], root=self.root))

    def test_registered_plan_preserves_history_and_checks_current_evidence_before_archive(self):
        from tests.test_foundation_qa import FoundationQATest

        fixture = FoundationQATest()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        self.root = fixture.root
        (self.root / "project.yaml").write_bytes((PACK / "project.yaml").read_bytes())
        name = "docs/plans/payout.md"
        plan = self.root / name
        plan.parent.mkdir()
        sql = self.root / "docs/payout.sql"
        sql.write_bytes(b"first release")
        old_sha = self.sha(sql)
        proof = self.root / "docs/proof.md"
        proof.write_text("[SQL](payout.sql)\n")
        links = "[清单][ledger] [SQL](../payout.sql) SHA256="
        old_line = "- 验收证据: " + links + old_sha
        original = ((PACK / "templates/docs/PLAN.md").read_text().replace("已验收版本: `none`", "已验收版本: `v1`")
                    + "\n其它导航也会引用[清单][ledger]和[SQL](../payout.sql)。\n"
                    + "\n## 批准依据与必要证据\n\n- 批准依据: 上轮批准\n" + old_line + "\n\n[ledger]: ../proof.md\n")
        plan.write_text(original)
        saved = self.work / "reviewed.md"
        saved.write_bytes(plan.read_bytes())
        graph = fixture.freeze(fixture.ordinary_source())
        active = fixture.start(fixture.update(graph, "qa", {"freeze_qa_scope": {
            "scope_ref": graph["tasks"][2]["qa_scope_ref"], "projection_paths": [name]}}))
        _, _, refs = fixture.evidence(active, "current")
        accepted = fixture.update(active, "qa", {"accept_request": refs})
        record = self.work / "registered.json"
        self.write(record, accepted)
        self.reg(record)

        def archive(code=0):
            return self.call(["archive", "--record", str(record), "--expect-sha256", self.sha(record)], expect=code)

        original_sha = self.sha(record)
        self.assertEqual("required_plan_projection_pending", archive(2)["error"])
        self.assertEqual(1, self.call(["view"])["registered_records"])
        sql.write_bytes(b"second release")
        receipt = refs["handoff"]["sha256"]
        def project(evidence, *, history=False, code=0):
            after = original.replace("已验收版本: `v1`", "已验收版本: `v2`").replace(old_line, "- 验收证据: " + evidence)
            if history:
                after = after.replace("\n## 需求与验收", "\n" + old_line + "\n\n## 需求与验收")
            plan.write_text(after)
            entry = {"path": name, "reviewed": {"path": str(saved), "sha256": self.sha(saved)},
                     "projected_sha256": self.sha(plan)}
            return self.graph_call("update", "--input", str(record), "--expect-sha256", original_sha, "--patch", "-",
                                   patch={"tasks": {"qa": {"record_qa_projection": {
                                       "adapter": "project.yaml", "documents": [entry]}}}}, code=code)

        self.assertIn("SHA256 与链接文件的实际字节不符", project(links + old_sha + " " + receipt, code=2)["error"])
        self.assertIn("旧验收证据链接", project(old_sha + " " + receipt, code=2)["error"])
        proof.write_text("[SQL](missing.sql)\n")
        current = links + self.sha(sql) + " " + receipt
        self.assertIn("proof.md:1", project(current, history=True, code=2)["error"])
        self.assertEqual(original_sha, self.sha(record))
        proof.write_text("[SQL](payout.sql)\n")
        project(current, history=True)
        self.assertEqual(original, saved.read_text())
        self.assertIn(old_line, plan.read_text())
        sql.write_bytes(b"changed after projection")
        self.assertEqual("current_request_qa_receipt_required", archive(2)["error"])
        sql.write_bytes(b"second release")
        self.assertEqual("archived", archive()["status"])
        self.assertEqual(0, self.call(["view"])["registered_records"])

    def test_full_closeout_requires_the_current_unique_qa(self):
        completed = self.record("full", level="Full", state="BUILD_VERIFIED")
        self.reg(completed)
        result = self.call(["closeout", "--request-id", "full"])
        self.assertEqual(("blocked", "unique_request_qa_required", []),
                         (result["status"], result["reason"], result["targets"]))

    def test_recovery_query_isolation_and_wholly_terminal_archive(self):
        a = self.record("shipping", request="order", level="Full")
        b = self.record("returns", request="order", state="FAILED")
        self.assertEqual([], self.call(["view"])["tasks"])
        self.assertFalse((self.work / "agent-workflow-request-scratch").exists())
        self.reg(a, "--title", "订单 发货")
        self.reg(b, "--title", "售后退货")
        rows = self.call(["status", "--query", "order"])["tasks"]
        self.assertEqual({"shipping", "returns"}, {row["task_id"] for row in rows})
        self.assertEqual([str(a)], [row["record"] for row in self.call(["view", "--query", "订单 ShIP"])["tasks"]])
        self.assertEqual([], self.call(["view"], pm="codex:conversation-B")["tasks"])
        alias = self.root.with_name(self.root.name.upper())
        if sys.platform == "darwin" and alias.exists() and alias.samefile(self.root):
            self.assertEqual(2, self.call(["view"], project=alias)["registered_records"])
        other = self.work / "other"
        other.mkdir()
        self.assertEqual([], self.call(["view"], project=other)["tasks"])
        pool_file, = (self.work / "agent-workflow-request-scratch").glob("*/task-pools/*/index.json")
        index = json.loads(pool_file.read_bytes())
        self.assertEqual(0, pool_file.stat().st_mode & 0o077)
        self.assertNotIn("state", str(index))
        self.assertNotIn("input_contracts", str(index))
        self.assertNotIn(self.pm, str(index))
        self.assertIn("terminal", self.call(["archive", "--record", str(a), "--expect-sha256", self.sha(a)], expect=2)["error"])
        before = b.read_bytes()
        self.assertEqual("archived", self.call(["archive", "--record", str(b), "--expect-sha256", self.sha(b)])["status"])
        self.assertEqual(before, b.read_bytes())
        self.assertEqual([str(a)], [row["record"] for row in self.call(["view"])["tasks"]])

    def test_invalidated_full_reviewer_keeps_result_scope_without_blocking_other_work(self):
        from tests.test_foundation_qa import FoundationQATest
        fixture = FoundationQATest()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        self.root = fixture.root
        source = fixture.freeze(fixture.ordinary_source())
        qa = source["tasks"][2]
        # 模拟已通过一轮修订、随后 Writer 改动使该轮失效的持久态。原 Reviewer
        # 保有原身份和回报；预测其它任务时不应将其重新列为待新建的 Agent。
        agent = {"host": "codex", "agent_id": "original-reviewer"}
        receipt = {"revision": 1, "agent_ref": agent}
        qa.update(agent_ref=agent, task_revision=1, revision_source="user:review",
                  revision_ack={**receipt, "delivery_source": "native:send", "ack_source": "native:ack"},
                  revision_result={**receipt, "source": "native:finished"}, qa_result_scope=qa["qa_scope_fingerprint"])
        reviewed = self.work / "review.json"
        self.write(reviewed, source)
        original = reviewed.read_bytes()
        independent = self.record("independent")
        self.reg(reviewed)
        self.reg(independent)
        status = self.call(["status", *self.capacity])
        self.assertEqual([], status["errors"])
        self.assertEqual(["independent"], [row["task_id"] for row in status["admission"]["candidates"]])
        waiting = next(row for row in status["admission"]["waiting"] if row["task_id"] == "qa")
        self.assertIn("already_bound", waiting["reasons"])
        self.assertEqual("claimed", self.claim(independent)["status"])
        self.assertEqual(original, reviewed.read_bytes())

    def test_corrupt_missing_or_replaced_records_disable_claim_until_original_restored(self):
        good, bad = self.record("good"), self.record("bad", path="src/two")
        self.reg(good)
        self.reg(bad)
        previous = bad.read_bytes()
        for replacement, message in ((None, "No such file"), (b"broken", "Expecting value"),
                                     (previous.replace(b'"request_id": "bad"', b'"request_id": "other"'), "identity")):
            with self.subTest(message=message):
                if replacement is None:
                    bad.unlink()
                else:
                    bad.write_bytes(replacement)
                status = self.call(["view", *self.capacity])
                self.assertEqual(str(bad), status["errors"][0]["record"])
                self.assertIn(message, status["errors"][0]["error"])
                self.assertIsNone(status["admission"])
                self.assertEqual([str(good)], [row["record"] for row in status["tasks"]])
                self.assertIn("every registered", self.claim(good, expect=2)["error"])
                if message == "identity":
                    self.assertIn("identity", self.reg(bad, expect=2)["error"])
                bad.write_bytes(previous)
        self.assertEqual([], self.call(["view"])["errors"])

    def test_read_only_registered_tasks_distinguish_empty_pool_missing_index_and_invalid_original(self):
        # CLI 与进程内查询使用同一临时根。读取前后检查原件字节及记录范围，
        # 防止 Hook 查询创建新池、返回部分有效原件或修改任务的持久状态。
        with mock.patch.object(tempfile, "tempdir", str(self.work)):
            self.assertEqual((), task_pool.registered_tasks(self.root, self.pm))
            self.assertFalse((self.work / "agent-workflow-request-scratch").exists())
            record = self.record("writer")
            original = record.read_bytes()
            self.reg(record)
            snapshot, = task_pool.registered_tasks(self.root, self.pm)
            self.assertEqual((str(record), self.root, "writer"),
                             (snapshot.record, snapshot.execution_root, snapshot.task["id"]))
            snapshot.task["state"] = "CANCELLED"
            self.assertEqual(original, record.read_bytes())
            self.assertEqual("READY", task_pool.registered_tasks(self.root, self.pm)[0].task["state"])

            record.write_bytes(b"broken")
            with self.assertRaisesRegex(ValueError, "已登记任务原件需要核对"):
                task_pool.registered_tasks(self.root, self.pm)
            record.write_bytes(original)
            index, = (self.work / "agent-workflow-request-scratch").glob("*/task-pools/*/index.json")
            index.unlink()
            with self.assertRaisesRegex(ValueError, "missing task pool index"):
                task_pool.registered_tasks(self.root, self.pm)

    def test_new_pm_index_is_visible_only_after_initial_publication(self):
        with mock.patch.object(tempfile, "tempdir", str(self.work)):
            existing = self.record("existing")
            pending = self.record("pending")
            self.reg(existing)
            other_pm = "antigravity:another-conversation"

            def fail_during_initial_save(file, data):
                self.assertEqual(frozenset({existing}), task_pool.registered_record_paths(self.root))
                raise OSError("interrupted initial save")

            with mock.patch.object(task_pool, "_save", side_effect=fail_during_initial_save):
                with self.assertRaisesRegex(OSError, "interrupted initial save"):
                    task_pool.register(self.root, other_pm, str(pending), self.sha(pending), None)

            self.assertEqual(frozenset({existing}), task_pool.registered_record_paths(self.root))
            task_pool.register(self.root, other_pm, str(pending), self.sha(pending), None)
            self.assertEqual(frozenset({existing, pending}), task_pool.registered_record_paths(self.root))

    def test_child_expansion_requires_its_reviewed_version_and_preserves_previous_identity(self):
        path = self.record("parent", level="Full")
        self.reg(path)
        old = self.sha(path)
        value = json.loads(path.read_bytes())
        value["tasks"].append(self.child(value["tasks"][0]))
        self.write(path, value)
        self.assertIn("explicit register", self.call(["view"])["errors"][0]["error"])
        self.assertIn("fingerprint changed", self.call(["register", "--record", str(path), "--expect-sha256", old], expect=2)["error"])
        self.assertEqual(2, self.reg(path)["task_count"])
        self.assertEqual({"parent", "part"}, {row["task_id"] for row in self.call(["status", "--query", "parent"])["tasks"]})
        value["tasks"].pop(0)
        self.write(path, value)
        self.assertIn("identity", self.reg(path, expect=2)["error"])

    def test_concurrent_claim_original_sha_and_receipt_replay(self):
        first, second = self.record("a"), self.record("b", path="src/two")
        self.reg(first)
        self.reg(second)
        previous = self.sha(first)
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as exe:
            replies = list(exe.map(lambda _: self.claim(first, sha=previous, expect=None), range(2)))
        self.assertEqual([0, 2], sorted(reply.returncode for reply in replies), [reply.stderr for reply in replies])
        receipt = json.loads(next(reply.stdout for reply in replies if not reply.returncode))
        result = self.call(["view", *self.capacity])["admission"]
        self.assertEqual((1, 1), (result["active_writers"], result["unbound_claims"]))
        self.assertEqual([], result["candidates"])
        self.assertIn("writer_capacity", next(row["reasons"] for row in result["waiting"] if row["record"] == str(second)))
        self.assertIn("not an admitted", self.claim(second, expect=2)["error"])
        self.assertIn("fingerprint changed", self.claim(first, sha=previous, expect=2)["error"])
        file = self.work / "receipt.json"
        self.write(file, receipt)
        cmd = ["release", "--receipt", str(file), *self.capacity, "--outcome"]
        self.assertEqual("retained", self.call([*cmd, "unknown"])["status"])
        self.assertEqual("released", self.call([*cmd, "definitely_not_created"])["status"])
        current = self.claim(first)
        self.assertNotEqual(receipt["previous_sha256"], current["previous_sha256"])
        self.assertIn("release requires", self.call([*cmd, "definitely_not_created"], expect=2)["error"])

    def withdraw(self, path, ident):
        patch = json.dumps({"tasks": {ident: {"withdraw": {"reason": "用户撤回该项"}}}})
        result = subprocess.run([sys.executable, "-B", str(PACK / "lib/task_graph_cli.py"), "update",
                                 "--input", str(path), "--root", str(self.root), "--patch", "-",
                                 "--expect-sha256", self.sha(path)], input=patch, capture_output=True,
                                cwd=self.root, env=self.env, text=True, check=False)
        self.assertEqual(0, result.returncode, result.stderr)

    def rejected_update(self, path, operation):
        # 特意直接走公开 CLI，以当前真实摘要提交完整补丁，排除参数错误或过期 CAS 造成的假阴性。
        before = path.read_bytes()
        result = subprocess.run([sys.executable, "-B", str(PACK / "lib/task_graph_cli.py"), "update",
                                 "--input", str(path), "--root", str(self.root), "--patch", "-",
                                 "--expect-sha256", self.sha(path)], cwd=self.root, env=self.env,
                                input=json.dumps({"tasks": {path.stem: operation}}), capture_output=True, text=True)
        self.assertEqual(2, result.returncode, result.stdout + result.stderr)
        self.assertEqual(before, path.read_bytes())
        return json.loads(result.stderr)["error"]

    def test_shared_solution_retains_required_member_until_its_peer_finishes(self):
        from lib.solution_confirmation import bind_decisions, decision_gates
        first = self.record("a", request="orders")
        second = self.record("b", request="orders", path="src/two")
        for path in (first, second):
            value = json.loads(path.read_bytes())
            task = value["task"]
            task["solution_decisions"] = [{"id": "route", "content": "按原渠道退回"}]
            bind_decisions(task)
            value["approved_gates"].extend(decision_gates(task).values())
            self.write(path, value)
            self.reg(path)
        receipt = self.work / "claim-receipt.json"
        release = ["release", "--receipt", str(receipt), *self.capacity, "--outcome", "definitely_not_created"]
        for path in (first, second):
            self.write(receipt, self.claim(path, request="orders"))
            self.withdraw(path, path.stem)
            self.assertEqual("WITHDRAWN", self.call(release)["state"])
            if path == first:
                self.assertIn("shared solution", self.call(["archive", "--record", str(first),
                                                           "--expect-sha256", self.sha(first)], expect=2)["error"])
        for path in (first, second):
            self.assertEqual("archived", self.call(["archive", "--record", str(path),
                                                    "--expect-sha256", self.sha(path)])["status"])

    def test_unbound_withdraw_uses_original_claim_even_after_sibling_progress(self):
        item = self.record("job", level="Full")
        value = json.loads(item.read_bytes())
        value["tasks"].append(self.child(value["tasks"][0]))
        self.write(item, value)
        self.reg(item)
        receipt = self.claim(item)
        # 兄弟任务先撤回，原图整体 SHA 已变；目标原领取的回执仍要归属到具体任务。
        for ident in ("part", "job"):
            self.withdraw(item, ident)
        rows = {row["task_id"]: row for row in self.call(["status", "--query", "job"])["tasks"]}
        self.assertEqual(("STOP_REQUESTED", True), (rows["job"]["state"], rows["job"]["active"]))
        self.assertEqual("WITHDRAWN", rows["part"]["state"])
        file = self.work / "receipt.json"
        self.write(file, receipt)
        cmd = ["release", "--receipt", str(file), *self.capacity, "--outcome"]
        self.assertEqual("retained", self.call([*cmd, "unknown"])["status"])
        self.assertEqual("WITHDRAWN", self.call([*cmd, "definitely_not_created"])["state"])
        self.assertEqual("archived", self.call(["archive", "--record", str(item), "--expect-sha256", self.sha(item)])["status"])

    def test_antigravity_binds_only_its_current_native_creation(self):
        parent, child, other = (str(uuid4()) for _ in range(3))
        self.pm = "antigravity:" + parent
        path = self.record("review")
        qa = json.loads(path.read_bytes())
        qa["task"].update(task_type="qa", role="xy-qa")
        self.write(path, qa)
        self.reg(path)
        old = self.claim(path)
        receipt_path = self.work / "claim.json"
        self.write(receipt_path, old)
        self.call(["release", "--receipt", str(receipt_path), "--outcome", "definitely_not_created", *self.capacity])
        current = self.claim(path)
        marker = current["dispatch_marker"]
        self.assertNotEqual(old["dispatch_marker"], marker)
        self.assertRegex(marker, r"^XY-WORKFLOW-CLAIM [0-9a-f]{64}$")
        claimed = path.read_bytes()
        exported = self.work / "review-handoff.json"
        def export(source, expected):
            return subprocess.run([sys.executable, "-B", str(PACK / "lib/task_graph_cli.py"), "task",
                                   "--root", str(self.root), "--input", str(source), "--output", str(exported),
                                   "--expect-sha256", expected], capture_output=True, text=True, env=self.env)
        result = export(path, "missing")
        self.assertEqual(0, result.returncode, result.stderr)
        # 发布旧格式的交接副本不能帮助人工绑定。之后真正的绑定却仍可刷新这一
        # 输出文件；原生 ID 是领取后才出现，不应破坏原先交接包的 CAS 覆盖约定。
        unproven = self.work / "historical.json"
        historical = json.loads(exported.read_bytes())
        historical["task"]["agent_ref"] = {"host": "antigravity", "agent_id": "xy-qa"}
        self.write(unproven, historical)
        unbound_sha = self.sha(exported)
        denied = export(unproven, unbound_sha)
        self.assertEqual(2, denied.returncode, denied.stdout)
        self.assertIn("AGY first binding", denied.stderr)
        self.assertEqual(unbound_sha, self.sha(exported))
        # 只在本测试进程替换系统日志定位。生产 CLI 无可指定日志路径或验证结果的选项；
        # 登记、两次领取、释放、原件发布和 CAS 都经过与正常入口相同的实际逻辑。
        brain = self.work / "cli-brain"
        relative = Path(".system_generated/logs/transcript.jsonl")
        log = brain / parent / relative
        log.parent.mkdir(parents=True)
        self.enterContext(mock.patch.object(antigravity_dispatch, "_brain_roots", return_value=(self.work / "app-brain", brain)))
        self.enterContext(mock.patch.object(tempfile, "tempdir", str(self.work)))

        def bind(ident=child, receipt=current):
            from lib.hosts.factory import dispatch_policy
            return task_pool.bind(self.root, self.pm, receipt, {"host": "antigravity", "agent_id": ident},
                                  policy=dispatch_policy(self.pm, reference_host="antigravity"))

        def invocation(text, name="invoke_subagent", selector="xy-qa"):
            return {"step_index": 1, "source": "MODEL", "type": "PLANNER_RESPONSE", "status": "DONE",
                    "tool_calls": [{"name": name, "args": {"Prompt": json.dumps(text), "TypeName": json.dumps(selector),
                                                           "Role": json.dumps("xy-qa")}}]}

        native = {"conversationId": child, "logAbsoluteUri": (brain / child / relative).as_uri(),
                  "workspaceUris": [self.root.as_uri()]}
        def response(payload=native):
            return {"step_index": 2, "source": "MODEL", "type": "GENERIC", "status": "DONE",
                    "content": ("Created At: 2026-11-20T17:22:32+08:00\nCompleted At: 2026-11-20T17:22:32+08:00\n"
                                "Created the following subagent:\n" + json.dumps(payload, indent=2)
                                + "\nThe subagent will send you a message when it has completed its task or requires "
                                "guidance. There is no need to poll for its response.")}

        def transcript(events, target=log):
            target.write_text("".join(json.dumps(event) + "\n" for event in events), encoding="utf-8")

        canonical = antigravity_dispatch.initial_prompt(self.root, current["target"], marker)
        creation = invocation(canonical)
        valid = [creation, response()]
        role_source = (PACK / "roles/xy-qa.md").read_text(encoding="utf-8")
        role_prompt = canonical + "\n\n" + role_source.strip("\n")
        # 真 UUID、同父其它领取或其它父会话中的真事件均不够。聊天、命令输出、
        # 已失败或不相邻的调用也不能借相同字符串生成一条成功绑定。
        other_log = brain / other / relative
        other_log.parent.mkdir(parents=True)
        transcript(valid, other_log)
        for label, events in {
                "other parent": [],
                "previous claim": [invocation(old["dispatch_marker"]), response()],
                "two markers": [invocation(old["dispatch_marker"] + "\n" + marker), response()],
                "quoted marker": [invocation("引用 " + marker), response()],
                "user message": [{**creation, "source": "USER_EXPLICIT"}, response()],
                "response in chat": [creation, {**response(), "type": "PLANNER_RESPONSE"}],
                "command output": [invocation(marker, "run_command"), response()],
                "wrong named role": [invocation(role_prompt, selector="xy-backend"), response()],
                "only role label": [invocation(marker, selector="research"), response()],
                "incomplete role": [invocation(role_prompt[:-160], selector="research"), response()],
                "unknown generic alias": [invocation(role_prompt, selector="reviewer"), response()],
                "interrupted": [creation, {**response(), "step_index": 3}],
                "parallel calls": [{**creation, "tool_calls": creation["tool_calls"] * 2}, response()],
                "failed creation": [creation, {**response(), "status": "ERROR"}],
                "wrong workspace": [creation, response({**native, "workspaceUris": [self.work.as_uri()]})],
                "wrong transcript URI": [creation, response({**native, "logAbsoluteUri": other_log.as_uri()})],
        }.items():
            with self.subTest(case=label):
                transcript(events)
                with self.assertRaisesRegex(ValueError, "no matching native"):
                    bind()
                self.assertEqual(claimed, path.read_bytes())
                if label == "wrong named role":
                    self.assertIn("native-bound Reviewer", self.rejected_update(path, {"set": {"state": "QA_PASSED"}}))
        # 通用入口必须在同一创建调用实际交付属于当前版本的完整角色，且保留相同领取与工作区。
        transcript([invocation(role_prompt, selector="research"), response()])
        antigravity_dispatch.verify_creation(parent, child, self.root, marker, "xy-qa",
                                                 expected_prompt=lambda: canonical)
        transcript(valid)
        # 复现 1.5.13 的真实双日志形状。长 Prompt 会被短日志裁切；完整日志携带
        # 原始字符串，子 URI 仍指短日志。命名角色和完整正文交接都必须能首绑。
        full_log = log.with_name("transcript_full.jsonl")
        for selector, prompt in (("xy-qa", canonical), ("research", role_prompt)):
            short_call = {**invocation(prompt[:64]), "truncated_fields": ["tool_calls"]}
            transcript([short_call, response()])
            full_call = {**creation, "tool_calls": [
                {"name": "invoke_subagent", "args": {"Prompt": prompt, "TypeName": selector}},
            ]}
            transcript([full_call, response()], full_log)
            antigravity_dispatch.verify_creation(parent, child, self.root, marker, "xy-qa",
                                                 expected_prompt=lambda: canonical)
        # 完整日志存在而格式不对或证据不符时，不允许改用恰好匹配的短日志。
        transcript(valid)
        for full_events in ([], valid, [full_call, response({**native, "workspaceUris": []})],
                            [{**full_call, "truncated_fields": ["tool_calls"]}, response()]):
            transcript(full_events, full_log)
            with self.assertRaisesRegex(ValueError, "no matching native"):
                bind()
        # 结果中的可见回执仍可解析，但不能把自报截断、路径分段截断或畸形标记
        # 当作完整证据。短日志完全匹配也不能替代已存在的完整日志。
        for fields in (["content"], ["content.payload"], "content", None, [False], [" content"]):
            with self.subTest(receipt_truncated_fields=fields):
                transcript([full_call, {**response(), "truncated_fields": fields}], full_log)
                with self.assertRaisesRegex(ValueError, "no matching native"):
                    bind()
                self.assertEqual(claimed, path.read_bytes())
        full_log.unlink()
        full_log.symlink_to(log)
        with self.assertRaisesRegex(ValueError, "cannot verify"):
            bind()
        full_log.unlink()
        transcript([{**creation, "truncated_fields": ["tool_calls"]}, response()])
        with self.assertRaisesRegex(ValueError, "no matching native"):
            bind()
        transcript([creation, {**response(), "truncated_fields": ["content"]}])
        with self.assertRaisesRegex(ValueError, "no matching native"):
            bind()
        transcript(valid)
        for ident in ("xy-qa", parent, other):
            with self.subTest(agent=ident), self.assertRaises(ValueError):
                bind(ident)
        with self.assertRaisesRegex(ValueError, "original claim"):
            bind(receipt=old)
        with self.assertRaisesRegex(ValueError, "dispatch marker"):
            bind(receipt={**current, "dispatch_marker": old["dispatch_marker"]})
        self.assertEqual(claimed, path.read_bytes())
        result = bind()
        self.assertEqual({"host": "antigravity", "agent_id": child}, result["agent_ref"])
        self.assertEqual(result["agent_ref"], json.loads(path.read_bytes())["task"]["agent_ref"])
        refreshed = export(path, unbound_sha)
        self.assertEqual(0, refreshed.returncode, refreshed.stderr)
        self.assertEqual(result["agent_ref"], json.loads(exported.read_bytes())["task"]["agent_ref"])
        log.unlink()
        self.assertEqual(result, bind())

        # Reproduce the authoritative old claim shape. Its original receipt retains
        # marker-only binding and the already-bound ID still resumes without logs.
        legacy = json.loads(claimed)
        legacy_claim = legacy["task"]["antigravity_claim"]
        legacy_claim.pop("prompt_format")
        self.write(path, legacy)
        marker = antigravity_dispatch.dispatch_marker(self.root, current["target"],
                                                      current["previous_sha256"], legacy_claim)
        legacy_receipt = {**current, "dispatch_marker": marker, "claimed_sha256": self.sha(path)}
        transcript([invocation(marker + "\n旧格式任务说明"), response()])
        legacy_bound = bind(receipt=legacy_receipt)
        log.unlink()
        self.assertEqual(reference := {"host": "antigravity", "agent_id": child}, legacy_bound["agent_ref"])
        self.assertEqual(legacy_bound, bind(receipt=legacy_receipt))
        self.assertEqual(reference, json.loads(path.read_bytes())["task"]["agent_ref"])

    def test_antigravity_app_display_update_acks_must_precede_the_creation_receipt(self):
        parent, child = (str(uuid4()) for _ in range(2))
        app, cli = self.work / "app-brain", self.work / "cli-brain"
        self.enterContext(mock.patch.object(antigravity_dispatch, "_brain_roots", return_value=(app, cli)))
        relative = Path(".system_generated/logs/transcript.jsonl")
        log = app / parent / relative
        full = log.with_name("transcript_full.jsonl")
        marker = "XY-WORKFLOW-CLAIM " + "1" * 64
        steps = {"name": "update_steps", "args": {"steps": [{"status": "in_progress", "title": "派发原型设计师"}]}}
        focus = {"name": "update_focus", "args": {"focus": "派发原型设计师"}}
        create = {"name": "invoke_subagent", "args": {"Prompt": marker, "TypeName": "xy-uiux"}}
        native = {"source": "MODEL", "status": "DONE"}
        request = {**native, "step_index": 84, "type": "PLANNER_RESPONSE", "tool_calls": [steps, create]}
        timestamps = "Created At: 2026-11-23T10:57:46+08:00\nCompleted At: 2026-11-23T10:57:48+08:00\n" * 2
        ack = {**native, "step_index": 85, "type": "GENERIC", "content": timestamps + "OK"}
        payload = {"conversationId": child, "logAbsoluteUri": (app / child / relative).as_uri(),
                   "workspaceUris": [self.root.as_uri()]}
        receipt = {**ack, "step_index": 86, "content": timestamps + "Created the following subagent:\n" + json.dumps(payload)
                   + "\nThe subagent will send you a message when it has completed its task or requires guidance. "
                     "There is no need to poll for its response."}
        batch = {**request, "tool_calls": [steps, focus, create]}
        focus_first = {**request, "tool_calls": [focus, steps, create]}
        focus_ack = {**ack, "step_index": 86}
        batch_receipt = {**receipt, "step_index": 87}

        def write(target, *events):
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("".join(json.dumps(event) + "\n" for event in events), encoding="utf-8")

        def verify():
            antigravity_dispatch.verify_creation(parent, child, self.root, marker, "xy-uiux")

        def short_request(event):
            return {**event, "tool_calls": [
                {**call, "args": {key: json.dumps(value) for key, value in call["args"].items()}}
                for call in event["tool_calls"]
            ]}

        short = short_request(request)
        write(log, short, ack, receipt)
        verify()
        write(log, short_request(batch), ack, focus_ack, batch_receipt)
        verify()
        write(log, short_request(focus_first), ack, focus_ack, batch_receipt)
        verify()
        write(full, request, ack, receipt)
        verify()
        # 实际 App 原型派发批次有两次界面更新，各自确认后才消费子会话回执。
        write(full, batch, ack, focus_ack, batch_receipt)
        verify()
        write(full, focus_first, ack, focus_ack, batch_receipt)
        verify()
        for label, calls in {
                "different sibling tool": [{**steps, "name": "update_focus"}, create],
                "creation first": [create, steps],
                "multiple creations": [steps, create, create],
                "missing step field": [{**steps, "args": {"steps": [{"status": "done"}]}}, create],
                "wrong full encoding": short["tool_calls"],
        }.items():
            with self.subTest(case=label):
                write(full, {**request, "tool_calls": calls}, ack, receipt)
                with self.assertRaisesRegex(ValueError, "no matching native"):
                    verify()
        for label, calls in {
                "different focus tool": [steps, {**focus, "name": "run_command"}, create],
                "focus has extra args": [steps, {**focus, "args": {**focus["args"], "path": "src/one"}}, create],
                "repeated focus": [focus, focus, create],
                "repeated steps": [steps, steps, create],
                "focus batch has multiple creations": [steps, focus, create, create],
                "wrong encoding for batch": short_request(batch)["tool_calls"],
        }.items():
            with self.subTest(case=label):
                write(full, {**batch, "tool_calls": calls}, ack, focus_ack, batch_receipt)
                with self.assertRaisesRegex(ValueError, "no matching native"):
                    verify()
        for invalid_focus in (None, 1, " ", "有效\n非法", "x" * 513):
            with self.subTest(invalid_focus=invalid_focus):
                bad_focus = {**focus, "args": {"focus": invalid_focus}}
                write(full, {**batch, "tool_calls": [steps, bad_focus, create]}, ack, focus_ack, batch_receipt)
                with self.assertRaisesRegex(ValueError, "no matching native"):
                    verify()
        write(full, {**request, "tool_calls": [focus, create]}, ack, receipt)
        with self.assertRaisesRegex(ValueError, "no matching native"):
            verify()
        for label, events in {
                "omitted focus acknowledgement": [batch, ack, receipt],
                "failed focus acknowledgement": [batch, ack, {**focus_ack, "status": "ERROR"}, batch_receipt],
                "foreign focus acknowledgement": [batch, ack, {**focus_ack, "source": "SYSTEM"}, batch_receipt],
                "truncated focus acknowledgement": [batch, ack, {**focus_ack, "truncated_fields": ["content"]}, batch_receipt],
                "unexpected call before second acknowledgement": [batch, ack, {**batch, "step_index": 86,
                                                               "tool_calls": [{"name": "run_command", "args": {}}]},
                                                               {**focus_ack, "step_index": 87},
                                                               {**batch_receipt, "step_index": 88}],
        }.items():
            with self.subTest(case=label):
                write(full, *events)
                with self.assertRaisesRegex(ValueError, "no matching native"):
                    verify()
        for label, events in {
                "truncated request": [{**request, "truncated_fields": ["tool_calls.0.args.steps"]}, ack, receipt],
                "omitted acknowledgement": [request, {**receipt, "step_index": 85}],
                "reversed results": [request, {**receipt, "step_index": 85}, {**ack, "step_index": 86}],
                "unwrapped acknowledgement": [request, {**ack, "content": "OK"}, receipt],
                "failed acknowledgement": [request, {**ack, "status": "ERROR"}, receipt],
                "chat acknowledgement": [request, {**ack, "type": "PLANNER_RESPONSE"}, receipt],
                "foreign acknowledgement": [request, {**ack, "source": "USER_EXPLICIT"}, receipt],
                "truncated acknowledgement": [request, {**ack, "truncated_fields": ["content"]}, receipt],
                "interleaved action": [request, ack, {**ack, "step_index": 86}, {**receipt, "step_index": 87}],
                "receipt index gap": [request, ack, {**receipt, "step_index": 87}],
        }.items():
            with self.subTest(case=label):
                write(full, *events)
                with self.assertRaisesRegex(ValueError, "no matching native"):
                    verify()
        full.unlink()
        write(log, request, ack, receipt)
        with self.assertRaisesRegex(ValueError, "no matching native"):
            verify()
        log.unlink()
        cli_batch_receipt = {**batch_receipt, "content": batch_receipt["content"].replace(str(app), str(cli))}
        write(cli / parent / full.relative_to(app / parent), batch, ack, focus_ack, cli_batch_receipt)
        with self.assertRaisesRegex(ValueError, "no matching native"):
            verify()
        cli_receipt = {**receipt, "content": receipt["content"].replace(str(app), str(cli))}
        write(cli / parent / full.relative_to(app / parent), request, ack, cli_receipt)
        with self.assertRaisesRegex(ValueError, "no matching native"):
            verify()

    def test_antigravity_only_pool_can_release_or_confirm_uncreated(self):
        self.pm = "antigravity:" + str(uuid4())
        path = self.record("waiting")
        self.reg(path)
        receipt_path = self.work / "receipt.json"
        for stopping in (False, True):
            with self.subTest(stopping=stopping):
                receipt = self.claim(path)
                self.write(receipt_path, receipt)
                operation = {"previous_sha256": receipt["previous_sha256"], "outcome": "definitely_not_created"}
                if stopping:
                    self.withdraw(path, path.stem)
                    direct = {"confirm_uncreated": operation}
                else:
                    direct = {"release_claim": {**operation, "prior_state": receipt["prior_state"]}}
                self.assertIn("current PM task pool", self.rejected_update(path, direct))
                cmd = ["release", "--receipt", str(receipt_path), *self.capacity, "--outcome"]
                self.assertEqual("retained", self.call([*cmd, "unknown"])["status"])
                self.assertEqual("WITHDRAWN" if stopping else receipt["prior_state"],
                                 self.call([*cmd, "definitely_not_created"])["state"])

    @unittest.skipUnless(getattr(os, "O_NOFOLLOW_ANY", 0), "系统未提供全路径禁链打开")
    def test_sandbox_scratch_needs_only_target_read_permission_and_rejects_symlink_ancestor(self):
        base = self.work / "native-temp/inner/pool/project"
        base.parent.parent.mkdir(parents=True)
        original_open = os.open
        def sandbox_open(path, flags, *, dir_fd=None):
            # 模拟宿主只允许读取当前临时根：上级可以穿越，但不能单独将其打开为可读目录。
            if dir_fd is None and Path(path) in base.parent.parent.parents:
                raise PermissionError(path)
            return original_open(path, flags, dir_fd=dir_fd)
        with mock.patch.object(os, "open", side_effect=sandbox_open):
            with task_graph_records._scratch_base_directory(base, create=True) as descriptor:
                self.assertEqual(base.stat().st_ino, os.fstat(descriptor).st_ino)
        alias = self.work / "borrowed-temp"
        alias.symlink_to(self.work / "native-temp", target_is_directory=True)
        with self.assertRaises(OSError), task_graph_records._scratch_base_directory(alias / "inner/pool/project"):
            self.fail("系统临时根的祖先软链必须在取得目录描述符之前被拒绝")
