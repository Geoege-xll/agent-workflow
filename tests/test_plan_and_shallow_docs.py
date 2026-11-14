"""分级计划入口与浅层规范的回归：验证实际结构、权限和审计，不触及真实项目。"""

from __future__ import annotations

import copy
import base64
import contextlib
import io
import stat
import hashlib
import importlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch
from tests.skill_contract_helpers import read_contract

from lib.standard_paths import canonical_standard_path, standard_domain, source_domain, canonical_standard_source_path
from lib.project.validate_project_config import validate_docs
from lib.validate_project_docs import validate as validate_documents
from lib.documents.plan_documents import SECTIONS, parse_plan, validate_selected_plans
from lib.documents.validate_prototype_workspace import ValidationError, validate_workspace
from tests import test_design_standards_lifecycle as design_cases
from tests import test_prototype_workspace as prototype_cases
from tests import test_qa_handoff as qa_cases
# 保护路径反例必须先具备当前2.0身份，才能验证真实设计边界，避免被旧格式拒绝掩盖。
from tests.test_scheduler_boundaries import v2_graph


PACK = Path(__file__).resolve().parents[1]


class SelectedPlanValidationTest(unittest.TestCase):
    """指定计划的真实 CLI 和安全负控；不依赖 PROJECT，也不扩大历史计划的读取范围。"""

    def setUp(self) -> None:
        supplied = os.environ.get("AWF_TEST_SCRATCH")
        if supplied:
            self.root = Path(supplied) / "selected-plan-fixtures" / self._testMethodName
            self.root.mkdir(parents=True, exist_ok=True)
        else:
            temporary = tempfile.TemporaryDirectory(prefix="selected-plan-")
            self.addCleanup(temporary.cleanup)
            self.root = Path(temporary.name).resolve()
        self.plans = self.root / "docs/plans"
        self.plans.mkdir(parents=True, exist_ok=True)

    def write_plan(self, body=None, name="selected.md") -> Path:
        path = self.plans / name
        path.write_text(PlanAndShallowDocsTest.lifecycle() if body is None else body, encoding="utf-8")
        return path

    def invoke(self, *plans, legacy=False):
        arguments = ([str(self.root / "project.yaml"), str(self.root)] if legacy else
                     ["--root", str(self.root), *[value for plan in plans for value in ("--plan", str(plan))]])
        return subprocess.run(
            ["bash", str(PACK / "lib/python_runtime.sh"), "-B", "-X", "utf8",
             str(PACK / "lib/validate_project_docs.py"), *arguments],
            cwd=self.root, capture_output=True, text=True, timeout=20,
        )

    def assert_rejected(self, body, reason):
        path = self.write_plan(body)
        errors = validate_selected_plans(self.root, [path])
        self.assertTrue(any(reason in error for error in errors), errors)

    def test_real_cli_without_project_repeats_absolute_and_relative_plans_without_writes(self):
        full = self.write_plan()
        light = self.write_plan(PlanAndShallowDocsTest.lifecycle().replace(
            "`Full`", "`Light`").split("\n## ", 1)[0] + "\n恢复本次小改动。\n", "light.md")
        # 同目录放置故意损坏的未选计划和软链：扫描目录会失败，选中文件入口应成功。
        ignored = self.write_plan("坏的未选计划", "unselected.md")
        ignored.chmod(0)
        self.addCleanup(ignored.chmod, 0o600)
        (self.plans / "unselected-link.md").symlink_to(self.root / "missing.md")
        before = {path: path.read_bytes() for path in (full, light)}
        result = self.invoke(full.relative_to(self.root), light)
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        self.assertIn("selected plans: 2", result.stdout)
        self.assertEqual(before, {path: path.read_bytes() for path in before})
        self.assertFalse((self.root / "project.yaml").exists())
        self.assertFalse((self.root / "docs/PROJECT.md").exists())
        self.assertFalse((self.root / ".agent-workflow").exists())
        self.assertEqual([], list(self.root.rglob("*.pyc")))

    def test_real_cli_reports_every_selected_failure_and_never_rewrites(self):
        first = self.write_plan("# 缺少生命周期元信息\n", "first.md")
        second = self.write_plan(PlanAndShallowDocsTest.lifecycle() + "\n## 多余专题\n", "second.md")
        before = {path: path.read_bytes() for path in (first, second)}
        result = self.invoke(first, second)
        self.assertEqual(1, result.returncode, result.stdout + result.stderr)
        self.assertIn(str(first), result.stderr)
        self.assertIn("主题 ID", result.stderr)
        self.assertIn(str(second), result.stderr)
        self.assertIn("H2", result.stderr)
        self.assertEqual(before, {path: path.read_bytes() for path in before})

    def test_all_five_metadata_fields_are_required_unique_and_single_valued(self):
        body = PlanAndShallowDocsTest.lifecycle()
        fields = ("主题 ID", "阶段", "模块", "任务等级", "已验收版本")
        for field in fields:
            line = next(line for line in body.splitlines() if line.startswith("- " + field + ":"))
            with self.subTest(field=field, defect="missing"):
                self.assert_rejected(body.replace(line + "\n", ""), field)
            for duplicate in (line, "- " + field + ":"):
                with self.subTest(field=field, defect=duplicate):
                    self.assert_rejected(body.replace(line, line + "\n" + duplicate), field)
        for old, new, reason in (("`active`", "`active, paused`", "阶段"),
                                 ("`Full`", "`Full / Light`", "任务等级"),
                                 ("`none`", "`v1, v2`", "已验收版本"),
                                 ("`TOPIC-ONE`", "`ONE TWO`", "主题 ID"),
                                 ("- 模块: `.`", "- 模块: ``", "模块")):
            with self.subTest(value=new):
                self.assert_rejected(body.replace(old, new), reason)

    def test_fenced_examples_cannot_supply_metadata_headings_or_baseline_evidence(self):
        body = PlanAndShallowDocsTest.lifecycle()
        for fence in ("```", "~~~~"):
            with self.subTest(fence=fence):
                self.assert_rejected(f"# 示例\n{fence}markdown\n{body}\n{fence}\n", "主题 ID")
                header, sections = body.split("\n## ", 1)
                self.assert_rejected(header + f"\n{fence}\n## " + sections + f"\n{fence}\n", "六节")
        accepted = PlanAndShallowDocsTest.lifecycle(version="v1")
        accepted = accepted.replace("- 批准依据: 原始用户批准记录 request-old", "```\n- 批准依据: 原始用户批准记录 request-old\n```")
        self.assert_rejected(accepted, "批准依据")
        # 示例内的额外标题、重复字段和坏链接均不属于真实文档合同。
        valid = body + "\n   ````md\n- 阶段: cancelled\n## 示例标题\n[示例](../../../../outside.md)\n```\n   ````\n"
        self.assertEqual([], validate_selected_plans(self.root, [self.write_plan(valid)]))

    def test_full_rejects_extra_duplicate_reordered_h2_but_accepts_h3(self):
        body = PlanAndShallowDocsTest.lifecycle()
        swapped = body.replace("## 目标与范围", "## 临时").replace(
            "## 需求与验收", "## 目标与范围").replace("## 临时", "## 需求与验收")
        for modified, reason in ((body + "\n## 新专题\n", "H2"),
                                 (body + "\n## 目标与范围\n", "重复"),
                                 (swapped, "乱序"),
                                 (body.replace("## 需求与验收", "## 方案与原型关联"), "重复")):
            with self.subTest(reason=reason):
                self.assert_rejected(modified, reason)
        self.assertEqual([], validate_selected_plans(self.root, [self.write_plan(body + "\n### 额外专题\n说明。\n")]))

    def test_light_simplifies_without_baseline_and_accepted_baseline_requires_proof(self):
        light = PlanAndShallowDocsTest.lifecycle().replace("`Full`", "`Light`")
        self.assertEqual([], validate_selected_plans(self.root, [self.write_plan(light.split("\n## ", 1)[0])]))
        accepted = PlanAndShallowDocsTest.lifecycle(version="v1").replace("`Full`", "`Light`")
        self.assertEqual([], validate_selected_plans(self.root, [self.write_plan(accepted)]))
        self.assert_rejected(accepted.replace("- 验收证据: 已有验收记录 qa-old", "- 验收证据: none"), "不能是待定")
        self.assert_rejected(accepted.split("\n## ", 1)[0], "必要证据")

    def test_paths_reject_escape_symlink_hardlink_special_missing_and_invalid_utf8(self):
        selected = self.write_plan()
        link = self.plans / "link.md"
        link.symlink_to(selected)
        hard = self.plans / "hard.md"
        os.link(selected, hard)
        directory_link = self.root / "alias"
        directory_link.symlink_to(self.plans, target_is_directory=True)
        invalid = self.plans / "invalid.md"
        invalid.write_bytes(b"\xff")
        fifo = self.plans / "special.md"
        os.mkfifo(fifo)
        for path in (selected, link, hard, directory_link / "selected.md", directory_link / "../docs/plans/invalid.md",
                     Path("../outside.md"), self.root.parent / "outside.md", self.plans / "missing.md", invalid,
                     fifo, self.plans, Path("docs/plans/../../../outside.md")):
            with self.subTest(path=path):
                self.assertTrue(validate_selected_plans(self.root, [path]))
        self.assertTrue(validate_selected_plans(directory_link, [Path("selected.md")]))
        hard.unlink()
        self.assertEqual([], validate_selected_plans(self.root, [Path("docs/plans/../plans/selected.md")]))

    def test_links_check_existence_and_safety_without_reading_target_or_unselected_body(self):
        target = self.root / "opaque.md"
        target.write_bytes(b"\xffnot UTF-8")
        target.chmod(0)
        self.addCleanup(target.chmod, 0o600)
        selected = self.write_plan(PlanAndShallowDocsTest.lifecycle() +
                                   "\n[本地](../../opaque.md) [目录](../) [页内](#x) "
                                   "[远程](https://invalid.example/no-request) [邮件](mailto:reader@example.test)\n")
        from lib.documents import plan_documents
        original = plan_documents.read_file
        with patch.object(plan_documents, "read_file", wraps=original) as reader:
            self.assertEqual([], validate_selected_plans(self.root, [selected]))
        self.assertEqual([selected], [call.args[0] for call in reader.call_args_list])
        result = self.invoke(selected)
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)

    def test_links_reject_missing_escape_encoded_escape_and_soft_or_hardlinks(self):
        target = self.root / "target.bin"
        target.write_bytes(b"not a document")
        (self.root / "link.bin").symlink_to(target)
        os.link(target, self.root / "hard.bin")
        (self.root / "alias").symlink_to(self.plans, target_is_directory=True)
        for raw in ("missing.md", "../../../outside.md", "../../%2e%2e/outside.md", "/absolute.md",
                    "file:///outside.md", "../../link.bin", "../../hard.bin", "../../target.bin",
                    "../../alias/../target.bin", "../../target.bin?query=1", "..%5coutside.md"):
            for label in ("[错误链接]", "![图片]"):
                with self.subTest(link=raw, label=label):
                    self.assert_rejected(PlanAndShallowDocsTest.lifecycle() + f"\n{label}({raw})\n", "")

    def test_legacy_cli_and_default_parser_keep_unindexed_history_behavior(self):
        legacy = self.write_plan("# 历史计划\n- Status: completed\n", "legacy.md")
        self.assertIsNone(parse_plan(legacy.read_text(), str(legacy)))
        old_extra = PlanAndShallowDocsTest.lifecycle() + "\n## 历史额外标题\n"
        self.assertIsNotNone(parse_plan(old_extra, "old"))
        (self.root / "project.yaml").write_bytes((PACK / "project.yaml").read_bytes())
        (self.root / "docs/PROJECT.md").write_text("# 项目\n", encoding="utf-8")
        result = self.invoke(legacy=True)
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        self.assertIn("PROJECT/plans baseline", result.stdout)
        selected = self.invoke(legacy)
        self.assertEqual(1, selected.returncode)
        self.assertIn("主题 ID", selected.stderr)


class PlanAndShallowDocsTest(unittest.TestCase):
    def setUp(self) -> None:
        supplied = os.environ.get("AWF_TEST_SCRATCH")
        if supplied:
            self.root = Path(supplied) / "plan-model-fixtures" / self._testMethodName
            self.root.mkdir(parents=True, exist_ok=True)
        else:
            temporary = tempfile.TemporaryDirectory(prefix="plan-shallow-docs-")
            self.addCleanup(temporary.cleanup)
            self.root = Path(temporary.name).resolve()
        self.config = self.root / "project.yaml"
        self.config.write_text((PACK / "project.yaml").read_text(), encoding="utf-8")
        self.docs = self.root / "docs"
        self.standards = self.docs / "standards"
        self.standards.mkdir(parents=True, exist_ok=True)
        (self.docs / "PROJECT.md").write_text("# Project\n", encoding="utf-8")
        (self.docs / "STANDARDS.md").write_text(
            "# Standards\n\n[General](standards/GENERAL.md)\n"
            "[Design](standards/DESIGN_FOUNDATIONS.md)\n", encoding="utf-8",
        )
        (self.standards / "GENERAL.md").write_text(
            "# General\n- Domain: engineering\n- `[eng-example] [hard]` Keep contracts.\n",
            encoding="utf-8",
        )
        (self.standards / "DESIGN_FOUNDATIONS.md").write_text(
            "# Design\n- Domain: design\n- `[des-example] [hard]` Keep accessibility.\n",
            encoding="utf-8",
        )

    def test_current_config_uses_plans_without_creating_a_plan(self) -> None:
        errors: list[str] = []
        docs = validate_docs(self.config.read_text().splitlines(), self.root, errors)
        self.assertEqual([], errors)
        self.assertEqual("docs/plans/", docs["plans"])
        self.assertNotIn("adr", docs)
        self.assertFalse((self.docs / "plans").exists())
        self.assertEqual([], validate_documents(self.config, self.root))

    def test_old_adr_key_is_rejected_not_silently_aliased(self) -> None:
        lines = self.config.read_text().replace("plans: docs/plans/", "adr: docs/ADR/").splitlines()
        errors: list[str] = []
        validate_docs(lines, self.root, errors)
        self.assertTrue(any("unsupported docs key: adr" in error for error in errors))
        self.assertTrue(any("missing keys: plans" in error for error in errors))

    @staticmethod
    def lifecycle(topic="TOPIC-ONE", stage="active", version="none") -> str:
        # 模拟已有验收来源，不能用阶段 completed 替代版本与批准／验收证据。
        header = (f"# 主题\n\n- 主题 ID: `{topic}`\n- 阶段: `{stage}`\n- 模块: `.`\n"
                  f"- 任务等级: `Full`\n- 已验收版本: `{version}`\n")
        content = ["本次目标。", "可观察验收。", "现有方案，无原型。", "下一步与恢复入口。",
                   "尚无已验收基线。" if version == "none" else "旧版本已交付查询行为；本次写入功能尚未交付。",
                   "- 批准依据: none\n- 验收证据: none" if version == "none" else
                   "- 批准依据: 原始用户批准记录 request-old\n- 验收证据: 已有验收记录 qa-old"]
        return header + "".join(f"\n## {name}\n\n{body}\n" for name, body in zip(SECTIONS, content))

    def write_plan(self, body, name="topic.md"):
        plans = self.docs / "plans"
        plans.mkdir(exist_ok=True)
        path = plans / name
        path.write_text(body, encoding="utf-8")
        return path

    def test_template_and_config_share_the_real_lifecycle_model(self) -> None:
        template = (PACK / "templates/docs/PLAN.md").read_text()
        document = parse_plan(template, "PLAN.md", required=True)
        self.assertEqual("none", document.accepted_version)
        self.assertFalse(document.has_current_baseline)
        self.assertEqual(list(SECTIONS), list(document.sections))
        self.assertFalse((PACK / "templates/docs/FEATURE.md").exists())
        errors = []
        validate_docs((self.config.read_text() + "  features: docs/plans/\n").splitlines(), self.root, errors)
        self.assertTrue(any("unsupported docs key: features" in error for error in errors))
        self.assertFalse((self.docs / "features").exists())

    def test_iteration_pause_and_cancellation_preserve_old_accepted_baseline(self) -> None:
        for stage in ("active", "paused", "cancelled", "completed"):
            with self.subTest(stage=stage):
                plan = self.write_plan(self.lifecycle(stage=stage, version="v1"))
                (self.docs / "PROJECT.md").write_text("# 项目\n[已验收查询](plans/topic.md)\n")
                before = plan.read_bytes()
                self.assertEqual([], validate_documents(self.config, self.root))
                self.assertEqual(before, plan.read_bytes())
                self.assertEqual("v1", parse_plan(plan.read_text(), "topic").accepted_version)

    def test_unindexed_legacy_completed_plan_is_preserved_but_cannot_be_indexed(self) -> None:
        body = "# 旧执行稿\n- Status: completed\n旧任务完成标签不证明当前事实。\n"
        plan = self.write_plan(body)
        self.assertEqual([], validate_documents(self.config, self.root))
        (self.docs / "PROJECT.md").write_text("# 项目\n[旧稿](plans/topic.md)\n")
        self.assertTrue(any("只能链接明确" in error for error in validate_documents(self.config, self.root)))
        self.assertEqual(body, plan.read_text())

    def test_completed_unaccepted_or_removed_plan_cannot_be_current_baseline(self) -> None:
        (self.docs / "PROJECT.md").write_text("# 项目\n[主题](plans/topic.md)\n")
        for stage, version in (("completed", "none"), ("removed", "v1")):
            with self.subTest(stage=stage):
                self.write_plan(self.lifecycle(stage=stage, version=version))
                self.assertTrue(any("只能链接明确" in error for error in validate_documents(self.config, self.root)))

    def test_duplicate_topic_and_missing_baseline_proof_are_rejected(self) -> None:
        self.write_plan(self.lifecycle(version="v1"))
        other = self.write_plan(self.lifecycle(version="v1"), "duplicate.md")
        self.assertTrue(any("duplicate 主题 ID" in error for error in validate_documents(self.config, self.root)))
        other.write_text(self.lifecycle(topic="TOPIC-TWO", version="v2").replace(
            "- 验收证据: 已有验收记录 qa-old", "- 验收证据: none"))
        self.assertTrue(any("不能是待定" in error for error in validate_documents(self.config, self.root)))


    @staticmethod
    def document_applier():
        # 通过真实脚本采用的 lib 搜索路径加载事务，避免复制发布器或用替身绕过磁盘行为。
        with patch.object(sys, "path", [str(PACK), *sys.path]):
            return importlib.import_module("lib.hosts.apply_antigravity_setup")

    def test_document_transaction_validates_standard_leaves_with_backups_retained(self) -> None:
        applier = self.document_applier()
        general = self.standards / "GENERAL.md"
        design = self.standards / "DESIGN_FOUNDATIONS.md"
        index = self.docs / "STANDARDS.md"
        general.chmod(0o640)
        design.chmod(0o600)
        updates = {
            general: general.read_bytes() + "项目专有约束继续保留。\n".encode(),
            design: None,
            index: b"# Standards\n\n[General](standards/GENERAL.md)\n",
        }
        inputs = {path: path.read_bytes() for path in updates}
        originals = {(body, stat.S_IMODE(path.stat().st_mode), path.stat().st_ino)
                     for path, body in inputs.items()}

        def validate_after():
            # 关键回归入口必须调用严格真实校验：合法规范叶不能被本轮仍可回滚的
            # 两个旧 inode 备份污染；同时验收前不允许靠删除唯一原件来取得绿色。
            self.assertEqual([], validate_documents(self.config, self.root))
            backups = list(self.root.rglob(applier.TRANSACTION_PREFIX + "backup--*"))
            self.assertEqual(originals, {
                (path.read_bytes(), stat.S_IMODE(path.stat().st_mode), path.stat().st_ino)
                for path in backups
            })
            self.assertTrue(all(path.stat().st_nlink == 1 for path in backups))

        applier.publish_document_changes(self.root, updates, inputs, validate_after)
        self.assertEqual(updates[general], general.read_bytes())
        self.assertEqual(0o640, stat.S_IMODE(general.stat().st_mode))
        self.assertFalse(design.exists())
        self.assertEqual(updates[index], index.read_bytes())
        self.assertFalse(list(self.root.rglob(applier.TRANSACTION_PREFIX + "*")))

    def test_document_transaction_strict_failure_restores_bytes_modes_and_rejects_forgery(self) -> None:
        applier = self.document_applier()
        general = self.standards / "GENERAL.md"
        design = self.standards / "DESIGN_FOUNDATIONS.md"
        index = self.docs / "STANDARDS.md"
        created = self.standards / "PROJECT_NOTES.md"
        general.chmod(0o640)
        design.chmod(0o600)
        originals = {path: (path.read_bytes(), stat.S_IMODE(path.stat().st_mode), path.stat().st_ino)
                     for path in (general, design, index)}
        forged = self.standards / (applier.TRANSACTION_PREFIX + "backup--forged--unknown")
        for reason in ("invalid-domain", "unknown-entry", "forged-backup"):
            with self.subTest(reason=reason):
                unknown = self.standards / "unknown.bin" if reason == "unknown-entry" else forged
                updates = {
                    general: originals[general][0] + "合法的项目专有补充。\n".encode(),
                    design: None,
                    index: b"# Standards\n\n[General](standards/GENERAL.md)\n",
                    created: "# 仅本轮创建的项目说明\n".encode(),
                }
                inputs = {path: originals[path][0] if path in originals else None for path in updates}
                if reason == "invalid-domain":
                    updates[general] = updates[general].replace(b"Domain: engineering", b"Domain: design")
                    expected_error = "standards leaf must declare Domain: engineering"
                else:
                    unknown.write_bytes(b"foreign entry; the transaction must preserve it\n")
                    unknown.chmod(0o600)
                    expected_error = "standards tree contains unsupported entry: " + str(unknown)

                def validate_after():
                    # 失败必须来自真实规范边界；未知条目即使伪造事务前缀也不能获豁免。
                    errors = validate_documents(self.config, self.root)
                    self.assertTrue(any(expected_error in error for error in errors), errors)
                    raise ValueError("strict docs validation: " + "; ".join(errors))

                with self.assertRaisesRegex(ValueError, "strict docs validation"):
                    applier.publish_document_changes(self.root, updates, inputs, validate_after,
                                                    desired_modes={general: 0o600})
                for path, original in originals.items():
                    self.assertEqual(original, (path.read_bytes(), stat.S_IMODE(path.stat().st_mode),
                                                path.stat().st_ino))
                self.assertFalse(created.exists())
                if reason != "invalid-domain":
                    self.assertEqual(b"foreign entry; the transaction must preserve it\n", unknown.read_bytes())
                    self.assertEqual(0o600, stat.S_IMODE(unknown.stat().st_mode))
                    # 仅夹具所有者在断言后撤去自己构造的陌生条目，事务不能代为清理。
                    unknown.unlink()
                self.assertFalse(list(self.root.rglob(applier.TRANSACTION_PREFIX + "*")))

    def test_document_transaction_preserves_concurrent_content_and_changed_backup(self) -> None:
        applier = self.document_applier()
        for moment, target in (("published-document", self.standards / "GENERAL.md"),
                               ("late-backup", self.docs / "STANDARDS.md")):
            with self.subTest(moment=moment):
                original = target.read_bytes()
                original_inode = target.stat().st_ino
                published = original + "事务发布的合法补充。\n".encode()
                concurrent = (published if moment == "published-document" else original) + "并发用户保存。\n".encode()
                prior_backups = set(self.root.rglob(applier.TRANSACTION_PREFIX + "backup--*"))
                retained = []

                def validate_after():
                    self.assertEqual([], validate_documents(self.config, self.root))
                    backups = set(self.root.rglob(applier.TRANSACTION_PREFIX + "backup--*")) - prior_backups
                    self.assertEqual(1, len(backups))
                    backup = backups.pop()
                    retained.append(backup)
                    if moment == "published-document":
                        target.write_bytes(concurrent)
                        raise ValueError("验收期间发生外部修改")
                    # 编辑器持有旧 inode 时可能迟到写入；即使真实校验已通过，后置指纹
                    # 仍必须阻止提交清理，回滚也不得覆盖已变化的唯一原件。
                    backup.write_bytes(concurrent)

                with self.assertRaisesRegex(applier.ApplyError, "rollback failed"):
                    applier.publish_document_changes(self.root, {target: published}, {target: original}, validate_after)
                self.assertEqual(1, len(retained))
                backup = retained[0]
                self.assertEqual(concurrent if moment == "published-document" else published, target.read_bytes())
                self.assertEqual(original if moment == "published-document" else concurrent, backup.read_bytes())
                self.assertEqual(original_inode, backup.stat().st_ino)
                self.assertEqual(1, backup.stat().st_nlink)

    def test_document_transaction_rejects_unsafe_backup_destination_before_any_write(self) -> None:
        applier = self.document_applier()
        target = self.standards / "GENERAL.md"
        created = self.standards / "PROJECT_NOTES.md"
        original = target.read_bytes(), stat.S_IMODE(target.stat().st_mode), target.stat().st_ino
        updates = {created: b"# New note\n", target: target.read_bytes() + b"New rule note.\n"}
        inputs = {created: None, target: original[0]}
        fingerprint = applier._fingerprint

        def different_device(path, *, read_file=True):
            node = fingerprint(path, read_file=read_file)
            return replace(node, device=node.device + 1) if path == target else node

        # 用设备身份反例覆盖无挂载权限时的跨卷拒绝分支；第二个原件不合格时，
        # 排在它前面的新文档也不得先被发布，磁盘断言区分真正预检与事后补偿。
        with patch.object(applier, "_fingerprint", side_effect=different_device):
            with self.assertRaisesRegex(applier.ApplyError, "project filesystem"):
                applier.publish_document_changes(self.root, updates, inputs,
                    lambda: self.fail("预检失败不得进入结果验收"))
        self.assertFalse(created.exists())
        self.assertEqual(original, (target.read_bytes(), stat.S_IMODE(target.stat().st_mode), target.stat().st_ino))
        self.assertFalse(list(self.root.rglob(applier.TRANSACTION_PREFIX + "*")))

        nonce = "occupied-backup-test"
        occupied = self.root / applier._temp_path(target, nonce, "backup").name
        occupied.write_bytes(b"foreign backup destination\n")
        occupied.chmod(0o600)
        with patch.object(applier.secrets, "token_hex", return_value=nonce):
            with self.assertRaisesRegex(applier.ApplyError, "owned backup path already exists"):
                applier.publish_document_changes(self.root, updates, inputs,
                    lambda: self.fail("备份归属冲突不得进入结果验收"))
        self.assertFalse(created.exists())
        self.assertEqual(original, (target.read_bytes(), stat.S_IMODE(target.stat().st_mode), target.stat().st_ino))
        self.assertEqual(b"foreign backup destination\n", occupied.read_bytes())
        self.assertEqual(0o600, stat.S_IMODE(occupied.stat().st_mode))

    def test_document_transaction_backup_root_fsync_failure_removes_owned_temp(self) -> None:
        applier = self.document_applier()
        target = self.standards / "GENERAL.md"
        target.chmod(0o640)
        original = target.read_bytes(), stat.S_IMODE(target.stat().st_mode), target.stat().st_ino
        published = original[0] + "仅此夹具的发布补充。\n".encode()
        fsync = applier._fsync_directory
        captured = []

        def fail_backup_root_fsync(path):
            if path == self.root and not captured:
                temporary, = self.standards.glob(applier.TRANSACTION_PREFIX + "temp--*")
                node = applier._fingerprint(temporary)
                captured.append((temporary, (node.device, node.inode)))
                raise OSError("injected backup-root fsync failure")
            fsync(path)

        def cleanup_own_red_fixture():
            # 仅测试所有者在断言结束后撤去旧实现遗留的本例原 temp，复用固定夹具。
            # 此处同样按采样身份/完整内容/权限条件撤回，绝不触碰 QA 的独立现场。
            if captured:
                temporary, identity = captured[0]
                if applier._fingerprint(temporary, read_file=False).kind != "missing":
                    applier.remove_created_standard(temporary, published, 0o640, identity)

        self.addCleanup(cleanup_own_red_fixture)
        with patch.object(applier, "_fsync_directory", side_effect=fail_backup_root_fsync):
            with self.assertRaisesRegex(OSError, "injected backup-root fsync failure"):
                applier.publish_document_changes(self.root, {target: published}, {target: original[0]},
                    lambda: self.fail("备份根刷新失败不得进入结果验收"))
        self.assertEqual(1, len(captured))
        self.assertEqual(original, (target.read_bytes(), stat.S_IMODE(target.stat().st_mode), target.stat().st_ino))
        # 回归断言必须发生在夹具清理前：原文恢复之外，严格规范扫描也要能立即再用。
        self.assertEqual([], validate_documents(self.config, self.root))
        self.assertFalse(list(self.root.rglob(applier.TRANSACTION_PREFIX + "*")))

    def test_document_transaction_backup_root_fsync_failure_preserves_changed_temp(self) -> None:
        applier = self.document_applier()
        target = self.standards / "GENERAL.md"
        target.chmod(0o640)
        original = target.read_bytes(), stat.S_IMODE(target.stat().st_mode), target.stat().st_ino
        published = original[0] + "本例待发布的正文。\n".encode()
        fsync = applier._fsync_directory
        for mutation in ("rewritten", "replaced-with-same-bytes", "permissions"):
            with self.subTest(mutation=mutation):
                prior_temps = set(self.standards.glob(applier.TRANSACTION_PREFIX + "temp--*"))
                captured = []

                def fail_after_concurrent_change(path):
                    if path == self.root and not captured:
                        temporary, = set(self.standards.glob(applier.TRANSACTION_PREFIX + "temp--*")) - prior_temps
                        if mutation == "rewritten":
                            temporary.write_bytes("并发用户已经改写临时路径。\n".encode())
                        elif mutation == "replaced-with-same-bytes":
                            # 字节和权限相同仍不是本轮 inode；如果身份在 fd 关闭后
                            # 才按路径取得，这个反例会暴露误删并发替换的问题。
                            replacement = self.root / "concurrent-temp-replacement"
                            replacement.write_bytes(published)
                            replacement.chmod(0o640)
                            os.replace(replacement, temporary)
                        else:
                            temporary.chmod(0o600)
                        info = temporary.stat()
                        captured.append((temporary, (temporary.read_bytes(), stat.S_IMODE(info.st_mode), info.st_ino)))
                        raise OSError("injected backup-root fsync failure")
                    fsync(path)

                with patch.object(applier, "_fsync_directory", side_effect=fail_after_concurrent_change):
                    with self.assertRaisesRegex(applier.ApplyError, "document temporary preserved at"):
                        applier.publish_document_changes(self.root, {target: published}, {target: original[0]},
                            lambda: self.fail("备份根刷新失败不得进入结果验收"))
                self.assertEqual(1, len(captured))
                temporary, concurrent = captured[0]
                self.assertEqual(concurrent, (temporary.read_bytes(), stat.S_IMODE(temporary.stat().st_mode),
                                               temporary.stat().st_ino))
                self.assertEqual(original, (target.read_bytes(), stat.S_IMODE(target.stat().st_mode), target.stat().st_ino))
                self.assertFalse(list(self.root.glob(applier.TRANSACTION_PREFIX + "backup--*")))
                # 并发 temp 保留供诊断，严格校验继续拒绝它；不能为取得绿色隐藏残留。
                self.assertIn("standards tree contains unsupported entry: " + str(temporary),
                              validate_documents(self.config, self.root))


    def test_leaf_domain_cannot_be_relabelled(self) -> None:
        leaf = self.standards / "DESIGN_FOUNDATIONS.md"
        leaf.write_text(leaf.read_text().replace("Domain: design", "Domain: engineering"))
        self.assertTrue(any("Domain: design" in item for item in validate_documents(self.config, self.root)))

    def test_builtin_sources_do_not_expand_project_write_paths(self) -> None:
        source = "platforms/shared/skills/xy-code-standards/references/rules.md"
        for path in (source, ".agent-workflow/" + source):
            self.assertEqual("engineering", source_domain(path, "docs/standards"))
            self.assertTrue(canonical_standard_source_path(path, "docs/standards"))
            self.assertIsNone(standard_domain(path, "docs/standards"))
            self.assertFalse(canonical_standard_path(path, "docs/standards"))
        for path in (source.upper(), source.replace("rules.md", "other.md"),
                     ".agents/skills/xy-code-standards/references/rules.md",
                     ".claude/skills/xy-code-standards/references/rules.md"):
            for root in ("docs/standards", path.rsplit("/", 1)[0]):
                self.assertIsNone(source_domain(path, root))
                self.assertFalse(canonical_standard_source_path(path, root))

    def test_project_standards_are_optional_and_notes_do_not_become_rules(self) -> None:
        for path in self.standards.glob("*.md"):
            path.unlink()
        (self.docs / "STANDARDS.md").unlink()
        self.standards.rmdir()
        self.assertEqual([], validate_documents(self.config, self.root))
        self.standards.mkdir()
        note = self.standards / "GENERAL.md"
        original = "# 项目历史说明\n\n仅保留项目背景，未声明通用规范。\n".encode("utf-8")
        note.write_bytes(original)
        self.assertEqual([], validate_documents(self.config, self.root))
        (self.docs / "STANDARDS.md").write_text("# 项目资料\n[保留说明](standards/GENERAL.md)\n", encoding="utf-8")
        self.assertEqual([], validate_documents(self.config, self.root))
        self.assertEqual(original, note.read_bytes())

    def test_project_rule_requires_index_and_cannot_shadow_builtin_or_bad_severity(self) -> None:
        index = self.docs / "STANDARDS.md"
        original = index.read_bytes()
        index.unlink()
        self.assertTrue(any("require a standards index" in item for item in validate_documents(self.config, self.root)))
        index.write_bytes(original)
        leaf = self.standards / "GENERAL.md"
        for text, message in (("[eng-common-005] [hard] 修改内置规则", "duplicate standards rule ID"),
                              ("[eng-common-005] [HARD] 伪装成说明", "invalid standards severity"),
                              ("| [eng-common-005] [CRITICAL] | 表格伪装 |", "invalid standards severity"),
                              ("保留说明中的 [eng-common-005] [unknown]", "invalid standards severity")):
            leaf.write_text("# 保留项目内容\n- Domain: engineering\n- `" + text + "`\n", encoding="utf-8")
            self.assertTrue(any(message in item for item in validate_documents(self.config, self.root)))

    def test_old_nested_standards_are_not_hidden_from_validation(self) -> None:
        (self.standards / "design/references").mkdir(parents=True)
        self.assertTrue(any("migrate nested directory" in item for item in validate_documents(self.config, self.root)))

    def test_path_classification_preserves_design_type_for_case_aliases(self) -> None:
        for path in ("docs/standards/design_foundations.md", "docs/STANDARDS/DESIGN_FOUNDATIONS.md"):
            with self.subTest(path=path):
                self.assertEqual("design", standard_domain(path, "docs/standards"))
                self.assertFalse(canonical_standard_path(path, "docs/standards"))

    def test_production_writer_cannot_edit_design_through_case_alias(self) -> None:
        helper = design_cases.DesignStandardsLifecycleTest()
        for path in ("docs/standards/design_foundations.md", "docs/STANDARDS/DESIGN_FOUNDATIONS.md"):
            with self.subTest(path=path):
                payload = v2_graph(helper.fixture(production=True))
                payload["tasks"][1]["owned_paths"] = [path]
                for document in payload["tasks"][1]["controlled_document_access"]["documents"]:
                    document["applies_to"] = [path]
                self.assertNotEqual(0, helper.invoke(payload).returncode)

    def test_ui_agent_cannot_write_engineering_leaf_in_flat_root(self) -> None:
        helper = design_cases.DesignStandardsLifecycleTest()
        payload = v2_graph(helper.fixture())
        payload["tasks"][0]["owned_paths"] = ["docs/standards/GENERAL.md"]
        self.assertIn("standards_only owns only exact", helper.invoke(payload).stderr)

    def test_all_selected_standards_must_be_registered_even_outside_required_domain(self) -> None:
        helper = design_cases.DesignStandardsLifecycleTest()
        for path in ("docs/standards/engineering/HIDDEN.md", "docs/standards/HIDDEN.md", "docs/standards/design/OLD.md"):
            with self.subTest(path=path):
                payload = v2_graph(helper.fixture())
                documents = payload["tasks"][0]["controlled_document_access"]["documents"]
                document = copy.deepcopy(documents[1])
                document.update(path=path, rule_ids=["rogue-rule"])
                documents.append(document)
                self.assertIn("absent from contract", helper.invoke(payload).stderr)

    def test_qa_rejects_domain_spoofing_and_case_alias(self) -> None:
        helper = qa_cases.QAHandoffValidationTest()
        helper.setUp()
        for path in ("docs/standards/DESIGN_FOUNDATIONS.md", "docs/standards/design_foundations.md", "docs/standards/engineering/GENERAL.md"):
            with self.subTest(path=path):
                payload = copy.deepcopy(helper.payload)
                payload["standards_policy_coverage"]["rule_checks"][0]["source_path"] = path
                self.assertNotEqual(0, helper.invoke(payload).returncode)

    def test_prototype_assets_cannot_hide_an_unreviewed_page_or_plan(self) -> None:
        for relative in ("ignored.HTML", "ignored.htm", "assets/ignored.HTML", "assets/task.MD"):
            with self.subTest(relative=relative), tempfile.TemporaryDirectory() as temporary:
                project = prototype_cases.write_valid_project(Path(temporary))
                prototype = project / prototype_cases.PROTOTYPE_RELATIVE
                target = prototype / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text("unreviewed", encoding="utf-8")
                with self.assertRaises(ValidationError):
                    validate_workspace(project, prototype_cases.PROTOTYPE_RELATIVE.as_posix())

    def test_plan_lifecycle_reference_is_shipped_and_discoverable(self) -> None:
        # 这是分发连接测试，不假装用关键字匹配证明宿主实际执行了计划恢复。
        reference = "references/plan-lifecycle.md"
        workflow = PACK / "platforms/shared/skills/xy-workflow"
        self.assertTrue((workflow / reference).is_file())
        for relative in (
            "platforms/shared/skills/xy-workflow/SKILL.md", "platforms/shared/skills/xy-plan/SKILL.md",
            "platforms/shared/skills/xy-project-memory/SKILL.md", "platforms/shared/AGENTS.product.tpl",
            "platforms/codex/AGENTS.codex.tpl", "platforms/claude/AGENTS.claude.tpl", "platforms/antigravity/AGENTS.antigravity.tpl",
        ):
            self.assertIn(reference, read_contract(PACK / relative), relative)
        self.assertTrue((PACK / "templates/docs/PLAN.md").is_file())
        html_reference = PACK / "platforms/shared/skills/xy-plan/references/requirements-markdown.md"
        self.assertTrue(html_reference.is_file())
        self.assertIn("references/requirements-markdown.md", read_contract(PACK / "platforms/shared/skills/xy-plan/SKILL.md"))
