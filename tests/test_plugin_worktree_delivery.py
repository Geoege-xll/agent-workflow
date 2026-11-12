"""当前 3.0 真实源码／插件交付合同，避免把历史安装器整组引入当前门禁。"""

from __future__ import annotations

import copy
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock
import zipfile

from lib.delivery import worktree_cli as delivery
from tests import test_plugin_delivery as plugin_fixtures
from tests import test_worktree_delivery as git_fixtures
from tests import test_qa_handoff as qa_fixtures


PACK = Path(__file__).resolve().parents[1]
BUILTIN = "platforms/shared/skills/xy-code-standards/references/rules.md"


class DeliveryFixture:
    """复用真实 Git 夹具方法，不继承旧 TestCase，防止额外收集历史宿主测试。"""

    setUp = git_fixtures.GitDeliveryTest.setUp
    refresh_candidate = git_fixtures.GitDeliveryTest.refresh_candidate

    def refresh_pack(self):
        """合同变更后生成实际当前 QA 包，不能只改 handoff 中的自报指纹。"""
        pack = {"schema_version": 2, "task": copy.deepcopy(self.qa_task),
                "standards_contract": copy.deepcopy(self.graph["standards_contract"]), "approved_gates": []}
        pack["task"]["state"] = "QA"
        body = json.dumps(pack).encode("utf-8")
        self.qa_pack_file.write_bytes(body)
        self.payload["qa_handoff"]["handoff_ref"] = qa_fixtures.handoff_ref(pack, body)

    def allow_writer_path(self, relative):
        """增加夹具 Writer 的明确所有权及规范覆盖，不以 PM 投影放行代码或配置。"""
        self.tasks[0]["owned_paths"].append(relative)
        for document in self.tasks[0]["controlled_document_access"]["documents"]:
            document["applies_to"].append(relative)

    def commit_candidate(self, *paths):
        delivery.git(self.integration, "add", "-A", "--", *paths)
        delivery.git(self.integration, "commit", "-m", "fixture reviewed candidate update")
        self.refresh_candidate()

    def writer_adapter(self, transform):
        """让实际 Writer 检查点携带配置修改，并重新集成、刷新完整 QA 与授权。"""
        relative = self.config.relative_to(self.repo).as_posix()
        self.allow_writer_path(relative)
        candidate = self.workers[0] / relative
        candidate.write_text(transform(candidate.read_text()), encoding="utf-8")
        delivery.git(self.workers[0], "add", relative)
        delivery.git(self.workers[0], "commit", "-m", "fixture writer adapter change")
        self.tasks[0]["execution_workspace"]["head_revision"] = delivery.head(self.workers[0])
        delivery.git(self.integration, "merge", "--no-edit", delivery.head(self.workers[0]))
        self.refresh_candidate()

    def builtin_only(self, *, index_path="docs/STANDARDS.md"):
        """在真实共同基线删除项目规范；仅保留执行源包的内置工程规则和 null 索引。"""
        delivery.git(self.repo, "rm", "docs/STANDARDS.md", "docs/standards/GENERAL.md")
        if index_path != "docs/STANDARDS.md":
            self.config.write_text(self.config.read_text().replace("docs/STANDARDS.md", index_path))
            delivery.git(self.repo, "add", self.config.relative_to(self.repo).as_posix())
        delivery.git(self.repo, "commit", "-m", "fixture project without specific standards")
        current_base = delivery.head(self.repo)
        delivery.git(self.integration, "merge", "--no-edit", current_base)
        contract = self.graph["standards_contract"]
        contract.update(index_path=index_path, index_fingerprint=None,
                        required_engineering_rule_ids=["eng-common-005"])
        contract["leaves"] = [leaf for leaf in contract["leaves"] if leaf["path"] == BUILTIN]
        for task in self.tasks[:2]:
            task["controlled_document_access"]["documents"] = [
                document for document in task["controlled_document_access"]["documents"]
                if document["path"] == BUILTIN]
        coverage = self.payload["qa_handoff"]["standards_policy_coverage"]
        coverage.update(index_path=index_path, index_fingerprint=None,
                        task_pack_rule_ids=["eng-common-005"], required_engineering_rule_ids=["eng-common-005"])
        coverage["rule_checks"] = [check for check in coverage["rule_checks"] if check["source_path"] == BUILTIN]
        self.refresh_candidate(current_base)
        # refresh_candidate 的通用夹具默认使用项目规则；这里改回当前真正的内置来源。
        for check in coverage["path_checks"]:
            check["applicable_rule_ids"] = ["eng-common-005"]
        self.refresh_pack()
        self.base = current_base

    def refresh_builtin_candidate(self):
        self.refresh_candidate()
        for check in self.payload["qa_handoff"]["standards_policy_coverage"]["path_checks"]:
            check["applicable_rule_ids"] = ["eng-common-005"]

    def add_projection(self):
        """提交真实 PM 主题投影并刷新候选指纹，保持文档验收和最终完整 diff 绑定。"""
        relative = "docs/plans/features.md"
        (self.integration / relative).write_text("# 已验收交付\n两个功能单元已完成验证。\n", encoding="utf-8")
        self.payload["projection_paths"] = [relative]
        self.commit_candidate(relative)
        return relative

    def invoke(self, *, command="merge", payload=None, config=None):
        """子进程执行真正的源码入口；插件类仅替换 wrapper 前缀。"""
        return subprocess.run([sys.executable, "-B", str(PACK / "lib/delivery/worktree_cli.py"), command,
                               "--repo", str(self.repo), "--config", str(config or self.config)],
                              input=json.dumps(payload or self.payload), capture_output=True, text=True,
                              env=plugin_fixtures.isolated_environment(self.root), timeout=45)

    def assert_rejected(self, *, payload=None, config=None):
        before = delivery.head(self.repo)
        result = self.invoke(payload=payload, config=config)
        self.assertEqual(2, result.returncode, result.stdout + result.stderr)
        self.assertNotIn("Traceback", result.stderr)
        self.assertEqual(before, delivery.head(self.repo))
        return result

    def assert_merged(self):
        result = self.invoke()
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        self.assertEqual("merged", json.loads(result.stdout)["status"])
        self.assertFalse(json.loads(result.stdout)["pushed"])
        self.assertEqual(self.tip, delivery.head(self.repo))


class SourceWorktreeDeliveryTest(DeliveryFixture, unittest.TestCase):
    def test_source_delivery_never_requires_business_copy_of_builtin_sources(self):
        self.assertFalse((self.integration / BUILTIN).exists())
        self.assert_merged()

    def test_builtin_logical_alias_ignores_same_named_business_decoy(self):
        alias = ".agent-workflow/" + BUILTIN
        contract = self.graph["standards_contract"]
        next(leaf for leaf in contract["leaves"] if leaf["path"] == BUILTIN)["path"] = alias
        for task in self.tasks[:2]:
            next(doc for doc in task["controlled_document_access"]["documents"] if doc["path"] == BUILTIN)["path"] = alias
        next(check for check in self.payload["qa_handoff"]["standards_policy_coverage"]["rule_checks"]
             if check["source_path"] == BUILTIN)["source_path"] = alias
        self.refresh_pack()
        for relative in (BUILTIN, alias):
            decoy = self.integration / relative
            decoy.parent.mkdir(parents=True, exist_ok=True)
            decoy.write_text("untrusted project rule replacement\n")
            self.allow_writer_path(relative)
        self.commit_candidate(BUILTIN, alias)
        self.assert_merged()

    def test_null_index_without_project_leaves_merges(self):
        self.builtin_only()
        self.assertFalse((self.integration / "docs/STANDARDS.md").exists())
        self.assert_merged()

    def test_new_index_requires_current_contract_and_qa_instead_of_old_null(self):
        self.builtin_only()
        (self.integration / "docs/STANDARDS.md").write_text("# 新项目规范索引\n")
        self.allow_writer_path("docs/STANDARDS.md")
        self.commit_candidate("docs/STANDARDS.md")
        self.refresh_builtin_candidate()
        self.assertIn("refresh standards contract and QA", self.assert_rejected().stderr)
        fingerprint = hashlib.sha256((self.integration / "docs/STANDARDS.md").read_bytes()).hexdigest()
        self.graph["standards_contract"]["index_fingerprint"] = fingerprint
        self.payload["qa_handoff"]["standards_policy_coverage"]["index_fingerprint"] = fingerprint
        # 新索引从可选缺失变成实际来源后，每个 Writer 也必须明确读取这个当前版本。
        for task in self.tasks[:2]:
            task["controlled_document_access"]["documents"].append({
                "path": "docs/STANDARDS.md", "mode": "full", "reason": "读取新增的真实项目索引",
                "sections_or_queries": [], "content_fingerprint": fingerprint,
                "applies_to": list(task["owned_paths"]), "rule_ids": []})
        self.refresh_pack()
        self.assert_merged()

    def test_null_index_rejects_symlink_directory_and_hardlink(self):
        self.builtin_only()
        relative = "docs/STANDARDS.md"
        self.allow_writer_path(relative)
        index = self.integration / relative
        outside = self.root / "outside-index.md"
        outside.write_text("# 外部索引\n")
        for kind in ("symlink", "directory", "hardlink"):
            with self.subTest(kind=kind):
                if index.is_symlink() or index.is_file():
                    index.unlink()
                elif index.is_dir():
                    shutil.rmtree(index)
                if kind == "symlink":
                    index.symlink_to(outside)
                elif kind == "directory":
                    index.mkdir()
                    (index / "entry").write_text("unsafe index directory\n")
                else:
                    os.link(outside, index)
                self.commit_candidate(relative)
                self.refresh_builtin_candidate()
                self.assert_rejected()

    def test_null_index_rejects_invalid_or_symlink_ancestor(self):
        self.builtin_only(index_path="docs/index/STANDARDS.md")
        self.allow_writer_path("docs/index")
        ancestor = self.integration / "docs/index"
        ancestor.write_text("ancestor is a regular file\n")
        self.commit_candidate("docs/index")
        self.refresh_builtin_candidate()
        self.assert_rejected()
        ancestor.unlink()
        ancestor.symlink_to(self.root / "missing-index-directory")
        self.commit_candidate("docs/index")
        self.refresh_builtin_candidate()
        self.assert_rejected()

    def test_changed_project_index_or_rule_fingerprint_blocks_merge(self):
        for relative in ("docs/STANDARDS.md", "docs/standards/GENERAL.md"):
            with self.subTest(relative=relative):
                document = self.integration / relative
                original = document.read_text()
                document.write_text(original + "\nchanged after standards freeze\n")
                self.allow_writer_path(relative)
                self.commit_candidate(relative)
                self.assertIn(relative, self.assert_rejected().stderr)
                document.write_text(original)
                self.commit_candidate(relative)

    def test_selected_adapter_must_exist_at_same_path_in_candidate(self):
        relative = self.config.relative_to(self.repo).as_posix()
        self.allow_writer_path(relative)
        (self.integration / relative).unlink()
        self.commit_candidate(relative)
        self.assertIn("selected project adapter", self.assert_rejected().stderr)
        # 即使候选存在另一个合法名称的 project.yaml，也不能替换用户选定的路径。
        alternate = self.integration / "other/project.yaml"
        alternate.parent.mkdir()
        alternate.write_bytes(self.config.read_bytes())
        self.allow_writer_path("other/project.yaml")
        self.commit_candidate("other/project.yaml")
        self.assertIn("selected project adapter", self.assert_rejected().stderr)

    def test_main_and_candidate_adapter_reject_symlinks_or_hardlinks(self):
        relative = self.config.relative_to(self.repo).as_posix()
        for root in (self.repo, self.integration):
            for kind in ("symlink", "hardlink"):
                with self.subTest(root=root.name, kind=kind):
                    path = root / relative
                    original = path.read_bytes()
                    external = self.root / (root.name + "-adapter.yaml")
                    external.write_bytes(original)
                    path.unlink()
                    if kind == "symlink":
                        path.symlink_to(external)
                    else:
                        os.link(external, path)
                    self.assert_rejected()
                    path.unlink()
                    path.write_bytes(original)

    def test_safe_read_detects_adapter_change_between_digest_and_body(self):
        original = delivery.file_digest
        changed = False

        def mutate_once(root, relative):
            nonlocal changed
            fingerprint = original(root, relative)
            if not changed and root == self.repo:
                changed = True
                self.config.write_text(self.config.read_text().replace("merge: confirm", "merge: auto"))
            return fingerprint

        with mock.patch.object(delivery, "file_digest", side_effect=mutate_once):
            with self.assertRaisesRegex(delivery.DeliveryError, "changed while reading"):
                delivery.merge_check(self.repo, self.config, self.payload)
        self.assertEqual(self.base, delivery.head(self.repo))

    def test_reviewed_writer_adapter_change_can_deliver(self):
        self.writer_adapter(lambda text: text.replace("project_name: MyProject", "project_name: ReviewedProject"))
        self.add_projection()
        self.assert_merged()
        self.assertIn("project_name: ReviewedProject", self.config.read_text())

    def test_candidate_confirm_to_auto_cannot_authorize_its_own_delivery(self):
        self.writer_adapter(lambda text: text.replace("merge: confirm", "merge: auto"))
        self.payload["authorization"].update(mode="auto", source="project:parallel_worktrees.merge")
        self.assertIn("explicit project configuration", self.assert_rejected().stderr)
        self.payload["authorization"].update(mode="confirm", source="user:reviewed-current-adapter-change")
        self.assert_merged()

    def test_candidate_standards_paths_must_match_frozen_graph(self):
        self.writer_adapter(lambda text: text.replace("standards_root: docs/standards/", "standards_root: docs/new-standards/"))
        self.assertIn("standards paths do not match", self.assert_rejected().stderr)

    def test_projection_requires_both_main_and_candidate_document_boundaries(self):
        self.writer_adapter(lambda text: text.replace("plans: docs/plans/", "plans: docs/new-plans/"))
        (self.integration / "docs/new-plans").mkdir()
        relative = "docs/new-plans/extra.md"
        (self.integration / relative).write_text("# 候选新文档目录\n")
        self.payload["projection_paths"] = [relative]
        self.commit_candidate(relative)
        self.assertIn("both checkouts", self.assert_rejected().stderr)

    def test_projection_does_not_expand_scope_or_accept_stale_or_wrong_reviewer(self):
        self.add_projection()
        for defect in ("scope", "authorization", "reviewer", "qa_state", "projection_code"):
            with self.subTest(defect=defect):
                payload = copy.deepcopy(self.payload)
                if defect == "scope":
                    payload["qa_handoff"]["review_method"]["scope_ref"]["repositories"][0]["head_revision"] = self.base
                elif defect == "authorization":
                    payload["authorization"]["head_revision"] = self.base
                elif defect == "reviewer":
                    payload["task_graph"]["tasks"][-1]["agent_ref"]["agent_id"] = "substitute-reviewer"
                elif defect == "qa_state":
                    payload["task_graph"]["tasks"][-1]["state"] = "QA"
                else:
                    payload["projection_paths"].append("src/a.py")
                self.assert_rejected(payload=payload)

    def test_real_foundation_pass_cannot_replace_final_request_qa(self):
        # 使用生产导出的真实阶段包及通过正式 QA 校验的 PASS；负控不依赖坏 JSON
        # 或缺字段提前失败，明确证明完整交付入口拒绝拿阶段检查点代替请求验收。
        from lib.task_graph_cli import export_task_pack
        from tests import test_foundation_qa as foundation_fixtures

        stage_root = self.root / "foundation-stage"
        stage_root.mkdir()
        with foundation_fixtures.working_root(stage_root):
            graph = foundation_fixtures.graph(stage_root)
            graph["tasks"][2].update(state="QA", agent_ref={"host": "codex", "agent_id": "current-reviewer"})
            pack = export_task_pack(graph, "qa")
            body = json.dumps(pack, ensure_ascii=False).encode("utf-8")
            handoff = foundation_fixtures.handoff(pack, body)
            delivery.validate_qa_handoff(handoff, body)
        self.assertEqual("foundation", pack["qa_checkpoint"]["kind"])
        self.qa_pack_file.write_bytes(body)
        self.payload["qa_handoff"] = handoff
        self.assertIn("Foundation QA checkpoint cannot authorize final request delivery", self.assert_rejected().stderr)


class PluginWorktreeDeliveryTest(DeliveryFixture, unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        """构建并解包实际 Codex 插件；执行 source_pack wrapper，不伪造插件环境。"""
        cls.temporary = tempfile.TemporaryDirectory(prefix="plugin-worktree-package-")
        cls.package_root = Path(cls.temporary.name).resolve()
        archive = plugin_fixtures.builder.build(PACK, cls.package_root / "build", "codex")
        cls.plugin = cls.package_root / "installed"
        cls.plugin.mkdir()
        with zipfile.ZipFile(archive) as payload:
            payload.extractall(cls.plugin)

    @classmethod
    def tearDownClass(cls):
        cls.temporary.cleanup()

    def invoke(self, *, command="merge", payload=None, config=None):
        return subprocess.run([sys.executable, "-B", str(self.plugin / "plugins/source_pack.py"), "helper",
                               "--project", str(self.repo), "lib/delivery/worktree_cli.py", command,
                               "--repo", str(self.repo), "--config", str(config or self.config)],
                              input=json.dumps(payload or self.payload), capture_output=True, text=True,
                              cwd=self.root, env=plugin_fixtures.isolated_environment(self.root), timeout=45)

    def test_packaged_delivery_ignores_business_builtin_decoy(self):
        decoy = self.integration / BUILTIN
        decoy.parent.mkdir(parents=True)
        decoy.write_text("this project file is never the plugin rule authority\n")
        self.allow_writer_path(BUILTIN)
        self.commit_candidate(BUILTIN)
        self.assertEqual((PACK / BUILTIN).read_bytes(), (self.plugin / BUILTIN).read_bytes())
        self.assert_merged()

    def test_packaged_null_index_delivery_without_copied_builtin(self):
        self.builtin_only()
        self.assertFalse((self.integration / BUILTIN).exists())
        self.assert_merged()

    def test_packaged_pm_projection_uses_real_candidate_config_after_commit(self):
        relative = self.add_projection()
        self.assert_merged()
        self.assertEqual((self.integration / relative).read_bytes(), (self.repo / relative).read_bytes())

    def test_packaged_selected_candidate_adapter_cannot_be_replaced(self):
        relative = self.config.relative_to(self.repo).as_posix()
        self.allow_writer_path(relative)
        (self.integration / relative).rename(self.integration / "project.yaml")
        self.allow_writer_path("project.yaml")
        self.commit_candidate(relative, "project.yaml")
        self.assertIn("selected project adapter", self.assert_rejected().stderr)
