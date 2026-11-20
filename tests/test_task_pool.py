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
