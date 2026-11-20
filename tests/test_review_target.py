"""真实 Git 候选与普通 Full QA 包的只读比对。"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from lib.delivery.review_target import compare_target
from lib.delivery.worktree_cli import DeliveryError, diff_bytes, local_objects_only, scope
from tests.test_qa_handoff import qa_task_pack


class ReviewTargetTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.project = self.root / "project"
        self.project.mkdir()
        self.cli = Path(__file__).resolve().parents[1] / "lib/delivery/qa_handoff_cli.py"
        # 仓库、提交者和冻结包全在夹具内；隔离本机 Git 配置使两个补丁编码的差异可复现。
        config = patch.dict(os.environ, GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_SYSTEM=os.devnull)
        config.start()
        self.addCleanup(config.stop)
        self.environment = dict(os.environ)
        self.git("init", "-q")
        self.file = self.project / "logic.py"
        self.clean = "refund = 10\n" + "# 业务规则\n" * 12 + "discount = 10\n"
        self.file.write_text(self.clean, encoding="utf-8")
        self.git("add", "logic.py")
        self.commit()
        self.base = self.git("rev-parse", "HEAD").decode().strip()
        self.pack = qa_task_pack()
        self.pack["task"]["qa_scope_fingerprint"] = "f" * 64
        self.uncommitted = {"kind": "uncommitted", "repository": "."}

    def git(self, *arguments):
        return subprocess.check_output(["git", "-C", str(self.project), *arguments], env=self.environment)

    def commit(self):
        self.git("-c", "user.name=QA", "-c", "user.email=qa@example.invalid", "commit", "-qm", "测试基线")

    def freeze(self, record):
        self.pack["task"]["qa_scope_ref"] = {"repositories": [record]}

    def freeze_worktree(self):
        self.freeze({"path": ".", "base_revision": self.base, "head_revision": self.base,
                     "changed_paths": ["logic.py"], "diff_fingerprint": hashlib.sha256(
                         diff_bytes(self.project, self.base)).hexdigest()})

    def invoke(self, target, *, cwd=None, compact=False):
        # 包放在项目外，避免用于传输的文件污染需要观察的未跟踪目标。
        self.body = json.dumps(self.pack, indent=None if compact else 2).encode()
        pack_path = self.root / "current.json"
        pack_path.write_bytes(self.body)
        process = subprocess.run([sys.executable, "-B", str(self.cli), "compare-target",
                                  "--task-pack", str(pack_path)], cwd=cwd or self.project,
                                 env=self.environment, input=json.dumps(target).encode(), capture_output=True)
        self.assertEqual(0, process.returncode, process.stderr)
        result = json.loads(process.stdout)
        self.assertNotIn("audit_result", result)
        return result

    def test_commit_range_compares_objects_and_binds_original_bytes_and_reviewer(self):
        self.file.write_text(self.clean.replace("10", "12"), encoding="utf-8")
        self.git("add", "logic.py")
        self.commit()
        tip = self.git("rev-parse", "HEAD").decode().strip()
        self.freeze(scope(self.project, self.base, tip))
        target = {"kind": "commit-range", "repository": ".", "base_revision": self.base, "head_revision": tip}
        result = self.invoke(target)
        self.assertEqual("match", result["status"])
        self.assertEqual(self.pack["task"]["qa_scope_ref"]["repositories"][0], result["observed"])
        self.assertEqual(hashlib.sha256(self.body).hexdigest(), result["handoff_ref"]["task_pack_sha256"])
        # 固定提交区间仍可复查；宿主如果其实打开了工作区，须按那个实际目标重新比对。
        self.file.write_text("后来的工作区内容", encoding="utf-8")
        self.assertEqual(result, self.invoke(target))
        self.pack["task"]["agent_ref"]["agent_id"] = "another-reviewer"
        new = self.invoke(target, compact=True)
        self.assertNotEqual(result["handoff_ref"], new["handoff_ref"])
        self.assertEqual("another-reviewer", new["handoff_ref"]["agent_ref"]["agent_id"])
        self.assertEqual("not-representable", self.invoke(dict(target, head_revision=self.base))["status"])
        self.assertEqual("needs-evidence", self.invoke(dict(target, head_revision="HEAD"))["status"])

    def test_dirty_baseline_two_findings_in_same_file_never_match_by_path(self):
        # 先取得只含本次折扣缺陷的对照补丁，再重放真实时间线：Writer 开始前退款就已
        # 出错，Writer 只改折扣。整个工作区的文件名与对照补丁完全相同，但多出退款 hunk。
        requested = self.clean.replace("discount = 10", "discount = -10")
        self.file.write_text(requested, encoding="utf-8")
        self.freeze_worktree()
        self.assertEqual("match", self.invoke(self.uncommitted)["status"])
        baseline = self.clean.replace("refund = 10", "refund = -10")
        self.file.write_text(baseline, encoding="utf-8")
        self.file.write_text(baseline.replace("discount = 10", "discount = -10"), encoding="utf-8")
        mixed = self.invoke(self.uncommitted)
        self.assertEqual("needs-evidence", mixed["status"])
        expected = self.pack["task"]["qa_scope_ref"]["repositories"][0]
        self.assertEqual(expected["changed_paths"], mixed["observed"]["changed_paths"])
        self.assertNotEqual(expected["diff_fingerprint"], mixed["observed"]["diff_fingerprint"])
        self.assertIn("hunk", mixed["reason"])
        del self.pack["task"]["qa_scope_fingerprint"]
        self.assertEqual("needs-evidence", self.invoke(self.uncommitted)["status"])
        del self.pack["task"]["qa_scope_ref"]
        self.assertEqual("needs-evidence", self.invoke(self.uncommitted)["status"])

    def test_alternative_diff_encoding_and_uncommitted_coverage(self):
        self.file.write_text(self.clean + "x = 1\n", encoding="utf-8")
        self.freeze_worktree()
        frozen = self.pack["task"]["qa_scope_ref"]["repositories"][0]
        saved = frozen["diff_fingerprint"]
        # 普通 Full 允许 PM 冻结实际补丁原字节，短对象 ID 编码产生另一合法摘要。
        frozen["diff_fingerprint"] = hashlib.sha256(self.git("diff", "HEAD", "--")).hexdigest()
        self.assertNotEqual(saved, frozen["diff_fingerprint"])
        self.assertEqual("needs-evidence", self.invoke(self.uncommitted)["status"])
        frozen["diff_fingerprint"] = saved
        self.git("add", "logic.py")
        index_path = self.project / ".git/index"
        before = index_path.read_bytes()
        self.assertEqual("match", self.invoke(self.uncommitted)["status"])
        self.assertEqual(before, index_path.read_bytes())
        # 索引里有两个版本，直接拿最终工作文件对 HEAD 的 patch 会消掉这一层。
        self.file.write_text(self.clean, encoding="utf-8")
        self.assertEqual("needs-evidence", self.invoke(self.uncommitted)["status"])
        (self.project / "untracked.txt").write_text("未跟踪内容", encoding="utf-8")
        self.assertEqual("not-representable", self.invoke(self.uncommitted)["status"])
        frozen["changed_paths"].append("untracked.txt")
        self.assertEqual("needs-evidence", self.invoke(self.uncommitted)["status"])

    def test_nested_project_physical_identity_and_partial_candidate(self):
        self.file.write_text(self.clean + "tax = 1\n", encoding="utf-8")
        self.freeze_worktree()
        frozen = self.pack["task"]["qa_scope_ref"]["repositories"][0]
        frozen.update(path="project", changed_paths=["project/logic.py"])
        target = dict(self.uncommitted, repository="project")
        self.assertEqual("match", self.invoke(target, cwd=self.root)["status"])
        self.pack["task"]["qa_scope_ref"]["repositories"].append(dict(frozen, path=".", changed_paths=["outside.txt"]))
        self.assertEqual("not-representable", self.invoke(target, cwd=self.root)["status"])
        self.pack["task"]["qa_scope_ref"]["repositories"].pop()
        try:
            (self.root / "alias").symlink_to(self.project, target_is_directory=True)
        except OSError as exc:
            self.skipTest(f"此平台无法创建测试用目录链接：{exc}")
        frozen.update(path="alias", changed_paths=["alias/logic.py"])
        self.assertEqual("needs-evidence", self.invoke(dict(target, repository="alias"), cwd=self.root)["status"])
        # 普通目录会被 Git 自动向上归入外层仓库，不能据此声明嵌套仓库已核验。
        (self.project / "alias").mkdir()
        self.assertEqual("needs-evidence", self.invoke(dict(target, repository="alias"))["status"])

    def test_staged_and_unstaged_on_distinct_paths_are_fully_represented(self):
        # A 的新版本只在工作区，B 的新版本已暂存。两个路径各有一层实际变化，
        # HEAD→工作区能表示两者，同文件暂存中间版本的拒绝规则不应阻碍这次比对。
        self.file.write_text(self.clean + "tax = 2\n", encoding="utf-8")
        (self.project / "orders.py").write_text("quantity = 2\n", encoding="utf-8")
        self.git("add", "orders.py")
        self.freeze_worktree()
        self.pack["task"]["qa_scope_ref"]["repositories"][0]["changed_paths"].append("orders.py")
        result = self.invoke(self.uncommitted)
        self.assertEqual("match", result["status"], result["reason"])
        self.assertEqual(["logic.py", "orders.py"], result["observed"]["changed_paths"])

    def test_empty_unknown_or_changing_targets_cannot_supply_evidence(self):
        self.freeze({"path": ".", "base_revision": self.base, "head_revision": self.base,
                     "changed_paths": ["logic.py"], "diff_fingerprint": hashlib.sha256(b"").hexdigest()})
        self.assertEqual("not-representable", self.invoke(self.uncommitted)["status"])
        for incomplete in ({}, {"kind": "commit-range", "repository": "."},
                           dict(self.uncommitted, pathspec="logic.py"), {"kind": "host-default", "repository": "."}):
            self.assertEqual("needs-evidence", self.invoke(incomplete)["status"])
        # 两次取证之间发生同文件改写时，保留证据缺口，即便其余参数都合法。
        with patch("lib.delivery.review_target._worktree_snapshot", side_effect=[({"sha": 1}, ""), ({"sha": 2}, "")]):
            report = compare_target(self.pack["task"], {}, self.uncommitted, self.project)
        self.assertEqual("needs-evidence", report["status"])
        self.assertIn("取证期间", report["reason"])

    def test_filter_configuration_only_matters_for_paths_that_use_it(self):
        self.file.write_text(self.clean + "tax = 2\n", encoding="utf-8")
        self.freeze_worktree()
        config = self.root / "gitconfig"
        self.git("config", "--file", str(config), "filter.lfs.clean", "false")
        self.environment["GIT_CONFIG_GLOBAL"] = str(config)
        self.git("config", "core.fsmonitor", "false")
        self.assertEqual("match", self.invoke(self.uncommitted)["status"])
        # 只登记过滤器不会改变原范围。明确配置应用后应在 status 调用前结束取证，
        # 保留这一原因供 PM 判断宿主的真实读取方式。私有 attributes 不改变工作树清单。
        attributes = self.project / ".git/info/attributes"
        attributes.write_text("logic.py filter=demo\n", encoding="utf-8")
        self.assertEqual("match", self.invoke(self.uncommitted)["status"])
        self.git("config", "filter.demo.clean", "")
        self.assertEqual("match", self.invoke(self.uncommitted)["status"])
        self.git("config", "filter.demo.clean", "false")
        report = self.invoke(self.uncommitted)
        self.assertEqual("needs-evidence", report["status"])
        self.assertIn("内容过滤器", report["reason"])
        attributes.write_text("logic.py filter=lfs\n", encoding="utf-8")
        self.git("config", "filter.lfs.clean", "")
        self.assertEqual("match", self.invoke(self.uncommitted)["status"])

    def test_partialclonefilter_alone_never_fetches_missing_blobs(self):
        self.file.write_text(self.clean + "tax = 3\n", encoding="utf-8")
        self.git("add", "logic.py")
        self.commit()
        tip = self.git("rev-parse", "HEAD").decode().strip()
        self.freeze(scope(self.project, self.base, tip))
        self.git("config", "uploadpack.allowFilter", "true")
        clone = self.root / "partial"
        # file:// 保证走真正的过滤传输；未检出时两次提交的 blob 均未下载。
        self.git("-c", "protocol.file.allow=always", "clone", "-q", "--no-checkout",
                 "--filter=blob:none", self.project.as_uri(), str(clone))
        for key in ("remote.origin.promisor", "extensions.partialclone"):
            subprocess.run(["git", "-C", str(clone), "config", "--unset-all", key],
                           capture_output=True, check=False, env=self.environment)
        self.assertEqual(b"blob:none\n", self.git("-C", str(clone), "config", "--get", "remote.origin.partialclonefilter"))
        missing = self.git("-C", str(clone), "rev-list", "--objects", "--all", "--missing=print")
        self.assertIn(b"?" + self.git("rev-parse", "HEAD:logic.py").strip(), missing.splitlines())

        def objects():
            # 比较整个对象库的文件清单和字节，捕捉隐式 file 传输新增的 pack/idx/promisor。
            return {path: path.read_bytes() for path in (clone / ".git/objects").rglob("*") if path.is_file()}

        before = objects()
        target = {"kind": "commit-range", "repository": ".", "base_revision": self.base, "head_revision": tip}
        self.assertEqual("needs-evidence", self.invoke(target, cwd=clone)["status"])
        # 确保 scope 下游的 Git 子进程确实收到限制；外部同名变量无法通过环境
        # 清理绕开它，源仓仍在线且具备提供缺失对象的能力。
        with patch.dict(os.environ, GIT_NO_LAZY_FETCH="0", GIT_ALLOW_PROTOCOL="file"), local_objects_only():
            with self.assertRaises(DeliveryError):
                scope(clone, self.base, tip)
        self.assertEqual(before, objects())
        # 人为准备第二个合法前置状态：将两份已知 blob 原字节写入测试克隆。
        # 比对本身不补对象；已有本地字节时，保留 partialclonefilter 也能精确匹配。
        for revision in (self.base, tip):
            body = self.git("show", f"{revision}:logic.py")
            subprocess.run(["git", "-C", str(clone), "hash-object", "-w", "--stdin"],
                           env=self.environment, input=body, capture_output=True, check=True)
        ready = objects()
        self.assertEqual("match", self.invoke(target, cwd=clone)["status"])
        self.assertEqual(ready, objects())

    def test_split_index_preserves_shared_mtime_and_allows_immutable_range_or_stale_files(self):
        self.file.write_text(self.clean + "tax = 3\n", encoding="utf-8")
        self.git("add", "logic.py")
        self.commit()
        tip = self.git("rev-parse", "HEAD").decode().strip()
        fixed = scope(self.project, self.base, tip)
        target = {"kind": "commit-range", "repository": ".", "base_revision": self.base, "head_revision": tip}
        self.base = tip
        self.file.write_text(self.clean + "tax = 4\n", encoding="utf-8")
        self.freeze_worktree()
        work = self.pack["task"]["qa_scope_ref"]["repositories"][0]
        self.git("update-index", "--split-index")
        shared = list((self.project / ".git").glob("sharedindex.*"))
        self.assertTrue(shared)
        # 让刷新动作可观察，即便测试机器的时间戳粒度较低也能区分。
        for path in shared:
            os.utime(path, (1_700_000_000, 1_700_000_000))
        before = [path.stat().st_mtime_ns for path in shared]
        report = self.invoke(self.uncommitted)
        self.assertEqual("needs-evidence", report["status"])
        self.assertIn("拆分索引", report["reason"])
        self.freeze(fixed)
        self.assertEqual("match", self.invoke(target)["status"])
        self.assertEqual(before, [path.stat().st_mtime_ns for path in shared])
        # Git 的拆分配置关闭后可以留下旧文件，它们不应阻碍普通索引的未提交目标。
        self.git("-c", "splitIndex.sharedIndexExpire=never", "update-index", "--no-split-index")
        self.assertTrue(all(path.exists() for path in shared))
        self.freeze(work)
        self.assertEqual("match", self.invoke(self.uncommitted)["status"])
