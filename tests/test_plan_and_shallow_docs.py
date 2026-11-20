"""分级计划入口与浅层规范的回归：验证实际结构、权限和审计，不触及真实项目。"""

from __future__ import annotations

import copy
import importlib
import os
import subprocess
import sys
import tempfile
import unittest
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
# 保护路径反例必须先具备当前schema 2身份，才能验证真实设计边界，避免被旧格式拒绝掩盖。
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

    def invoke(self, *plans, legacy=False, adapter=None, topic=None):
        arguments = ([str(self.root / "project.yaml"), str(self.root)] if legacy else
                     ["--root", str(self.root), *[value for plan in plans for value in ("--plan", str(plan))]])
        if adapter is not None:
            arguments.extend(("--adapter", str(adapter)))
        if topic is not None:
            arguments.extend(("--topic", topic))
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
        light = self.write_plan(PlanAndShallowDocsTest.lifecycle(topic="TOPIC-LIGHT").replace(
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

    def test_selected_cli_deduplicates_one_file_but_rejects_two_sources_of_one_topic(self):
        plan = self.write_plan()
        duplicate = self.write_plan(PlanAndShallowDocsTest.lifecycle(topic="topic-one"), "draft-copy.md")
        one = self.invoke(plan, Path("docs/plans/../plans/selected.md"))
        self.assertEqual(0, one.returncode, one.stdout + one.stderr)
        two = self.invoke(plan, duplicate)
        self.assertEqual(1, two.returncode, two.stdout + two.stderr)
        for value in ("duplicate 主题 ID", str(plan), str(duplicate)):
            self.assertIn(value, two.stderr)

    def test_topic_cli_reads_only_configured_tracked_headers_and_explicit_candidates(self):
        self.plans = self.root / "docs/topics"
        self.plans.mkdir()
        adapter = self.root / "custom-project.yaml"
        adapter.write_text((PACK / "project.yaml").read_text().replace("plans: docs/plans/", "plans: docs/topics/"))
        tracked = self.write_plan("# 项目\n\n<!--\n## 旧文档的示例标题\n~~~md\n-->\n"
                                  "```md\n- 主题 ID: wrong-example\n## 伪边界\n```\n"
                                  "- 主题 ID: `topic-one`\n\n## 目标与范围\n", "original-name.md")
        with tracked.open("ab") as stream:
            # 非法正文证明定位未解码首个真实 H2 之后的内容，常规 --plan 仍严格验证它。
            stream.write(b"\xff")
        for args in (("init", "--quiet"), ("add", "--", str(tracked.relative_to(self.root)))):
            subprocess.run(["git", "-C", str(self.root), *args], check=True, capture_output=True)
        untracked = self.write_plan(name="isolated-draft.md")
        outside = self.root / "docs/plans/other.md"
        outside.write_text(PlanAndShallowDocsTest.lifecycle())
        before = {path: path.read_bytes() for path in (tracked, untracked, outside)}
        result = self.invoke(adapter=adapter, topic="TOPIC-ONE")
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        self.assertIn("现有计划: docs/topics/original-name.md", result.stdout)
        self.assertEqual(1, self.invoke(tracked).returncode)
        duplicate = self.invoke(untracked, adapter=adapter, topic="TOPIC-ONE")
        self.assertEqual(1, duplicate.returncode, duplicate.stdout + duplicate.stderr)
        self.assertIn("duplicate 主题 ID", duplicate.stderr)
        out_of_scope = self.invoke(outside, adapter=adapter, topic="TOPIC-ONE")
        self.assertEqual(1, out_of_scope.returncode, out_of_scope.stdout + out_of_scope.stderr)
        self.assertIn("docs.plans", out_of_scope.stderr)
        missing = self.invoke(adapter=adapter, topic="wrong-example")
        self.assertEqual(0, missing.returncode, missing.stdout + missing.stderr)
        self.assertIn("未找到主题", missing.stdout)
        self.assertEqual(before, {path: path.read_bytes() for path in before})
        with adapter.open("a", encoding="utf-8") as stream:
            stream.write("\ndocs: # 重复配置\n  plans: docs/plans/\n")
        ambiguous = self.invoke(adapter=adapter, topic="TOPIC-ONE")
        self.assertEqual(1, ambiguous.returncode, ambiguous.stdout + ambiguous.stderr)
        self.assertIn("必须包含唯一 docs 配置", ambiguous.stderr)

    def test_topic_cli_without_git_requires_explicit_candidates(self):
        adapter = self.root / "project.yaml"
        adapter.write_bytes((PACK / "project.yaml").read_bytes())
        plan = self.write_plan()
        missing_scope = self.invoke(adapter=adapter, topic="TOPIC-ONE")
        self.assertEqual(1, missing_scope.returncode, missing_scope.stdout + missing_scope.stderr)
        self.assertIn("--plan", missing_scope.stderr)
        explicit = self.invoke(plan, adapter=adapter, topic="TOPIC-ONE")
        self.assertEqual(0, explicit.returncode, explicit.stdout + explicit.stderr)
        self.assertIn("现有计划: docs/plans/selected.md", explicit.stdout)

    def test_real_cli_reports_every_selected_failure_and_never_rewrites(self):
        first = self.write_plan("# 缺少生命周期元信息\n", "first.md")
        second = self.write_plan(PlanAndShallowDocsTest.lifecycle() + "\n## 需求与验收\n", "second.md")
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
                self.assert_rejected(header + f"\n{fence}\n## " + sections + f"\n{fence}\n", "需求与验收")
        accepted = PlanAndShallowDocsTest.lifecycle(version="v1")
        accepted = accepted.replace("- 批准依据: 原始用户批准记录 request-old", "```\n- 批准依据: 原始用户批准记录 request-old\n```")
        self.assert_rejected(accepted, "批准依据")
        # 示例内的额外标题、重复字段和坏链接均不属于真实文档合同。
        valid = body + "\n   ````md\n- 阶段: cancelled\n## 示例标题\n[示例](../../../../outside.md)\n```\n   ````\n"
        self.assertEqual([], validate_selected_plans(self.root, [self.write_plan(valid)]))

    def test_compact_full_accepts_reader_order_and_requires_unique_effective_sections(self):
        body = PlanAndShallowDocsTest.lifecycle()
        header = body.split("\n## ", 1)[0]
        compact = (header + "\n## 验收结果与当前已交付行为\n尚无基线。\n"
                   "\n## 需求与验收\n能查到指定订单。\n\n## 订单来源\n订单从业务接口读取。\n")
        self.assertEqual([], validate_selected_plans(self.root, [self.write_plan(compact)]))
        self.assert_rejected(compact + "\n## 需求与验收\n另一个目标。", "重复")
        self.assert_rejected(compact.replace("能查到指定订单。", "<!-- 仍待补充 -->"), "非空")
        accepted = PlanAndShallowDocsTest.lifecycle(version="v1")
        # 无关章节不能向上一个证据节“借出”验收依据，避免换标题之后误绑旧证据。
        self.assert_rejected(accepted.replace("- 验收证据:", "## 外部资料\n- 验收证据:"), "验收证据")
        self.assert_rejected(accepted.replace("- 验收证据:", "<!--\n- 验收证据:") + "\n-->", "验收证据")

    def test_adapter_plan_checks_only_incoming_links_to_selected_nodes(self):
        adapter = self.root / "project.yaml"
        adapter.write_bytes((PACK / "project.yaml").read_bytes())
        plan = self.write_plan()
        project = self.root / "docs/PROJECT.md"
        # 同目录含不可解码历史原稿与失效链接。定向校验只核对所选来源及它的目录项。
        self.write_plan(name="unselected.md").write_bytes(b"\xff")
        body = ("## 主题目录\n- [历史待核](plans/unselected.md#坏锚点)\n- [待修复](plans/missing.md)\n"
                "- [查订单](plans/selected.md#需求与验收)\n")
        project.write_text(body)
        result = self.invoke(plan, adapter=adapter)
        self.assertEqual(0, result.returncode, result.stderr)
        project.write_text(body.replace("需求与验收", "不存在的标题"))
        failure = self.invoke(plan, adapter=adapter)
        self.assertEqual(1, failure.returncode)
        self.assertIn("锚点不存在", failure.stderr)
        self.assertEqual(0, self.invoke(plan).returncode)

    def test_selected_cli_validates_explicit_current_requirement_section(self):
        body = PlanAndShallowDocsTest.lifecycle().replace("可观察验收。", "### 当前有效需求\n- REQ-001 可观察验收。")
        self.assertEqual([], validate_selected_plans(self.root, [self.write_plan(body)]))
        commented = body.replace("- REQ-001", "<!--\n### 当前有效需求\n-->\n- REQ-001")
        self.assertEqual([], validate_selected_plans(self.root, [self.write_plan(commented)]))
        self.assert_rejected(body.replace("- REQ-001", "参见 REQ-001"), "至少定义一个 REQ ID")
        self.assert_rejected(body.replace("## 方案与原型关联", "## 方案与原型关联\n### 当前有效需求"), "须唯一")

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

    def test_selected_resolves_titled_links_and_images_to_their_actual_targets(self):
        docs = self.root / "docs"
        standards = docs / "standards"
        decisions = docs / "decisions"
        standards.mkdir()
        decisions.mkdir()
        (standards / "DESIGN_MINI_PROGRAM.md").touch()
        (decisions / "order (v2).md").touch()
        image = decisions / "order (v2).png"
        image.touch()
        compact = (PlanAndShallowDocsTest.lifecycle() +
                   '\n[触控](../standards/DESIGN_MINI_PROGRAM.md#触控与间距 "规范依据")\n'
                   '[决定](<../decisions/order (v2).md> "确定依据")\n'
                   '> ![图](../decisions/order%20(v2).png "示意图")\n'
                   '说明中举例的 `![图](missing.png)` 不产生实际链接。\n')
        result = self.invoke(self.write_plan(compact))
        self.assertEqual(0, result.returncode, result.stderr)
        # 确认图片仍在校验范围，也不允许带标题的格式绕过缺失、父跳转或软链检查。
        image.unlink()
        self.assert_rejected(compact, "order (v2).png")
        image.symlink_to(decisions / "order (v2).md")
        self.assert_rejected(compact, "单链接")
        self.assert_rejected(compact.replace("../standards/DESIGN_MINI_PROGRAM.md", "../../../escape.md"), "越出")
        self.assert_rejected(compact.replace("order (v2).md", "order%09(v2).md"), "文档链接须位于项目内")

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
        self.assertEqual([SECTIONS[4], SECTIONS[1]], list(document.sections))
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

    def test_topic_catalog_distinguishes_navigation_claims_and_archived_sources(self):
        project = self.docs / "PROJECT.md"
        entry = "- [未验收查询](plans/topic.md#需求与验收)\n"
        for stage, version, expected in (("draft", "none", True), ("active", "none", True),
                                         ("paused", "none", True), ("cancelled", "v1", True),
                                         ("cancelled", "none", False), ("completed", "none", False),
                                         ("removed", "v1", False)):
            with self.subTest(stage=stage, version=version):
                self.write_plan(self.lifecycle(stage=stage, version=version))
                project.write_text("## 主题目录\n" + entry)
                self.assertEqual(expected, not validate_documents(self.config, self.root))
        plan = self.write_plan(self.lifecycle())
        for prefix in ("## 主题目录\n- 已验收：", "## 当前已验收基线\n- ", "## 概况\n",
                       "## 概况\n> 原有正文声明："):
            project.write_text(prefix + "[查询](plans/topic.md)\n")
            self.assertTrue(any("只能链接明确" in e for e in validate_documents(self.config, self.root)))
        plan.write_text(self.lifecycle(version="v1"))
        project.write_text("## 主题目录\n- 已验收：[查询](plans/topic.md)\n")
        self.assertEqual([], validate_documents(self.config, self.root))
        plan.write_text("# 无生命周期的旧历史\n")
        self.assertTrue(validate_documents(self.config, self.root))

    def test_topic_catalog_checks_real_anchors_deduplicates_aliases_and_preserves_sources(self):
        project = self.docs / "PROJECT.md"
        plan = self.write_plan(self.lifecycle() + '\n<a id="short"></a>\n### 两个 Step\n')
        directory = "## 主题目录\n"
        for anchor in ("short", "两个-step", "%E9%9C%80%E6%B1%82%E4%B8%8E%E9%AA%8C%E6%94%B6"):
            project.write_text(directory + f"- [查询](plans/topic.md#{anchor})\n")
            self.assertEqual([], validate_documents(self.config, self.root))
        before = plan.read_bytes()
        for links, error in ((("- [查询](plans/topic.md#已删除)",), "锚点不存在"),
                             (("- [一](plans/topic.md#short)", "- [二](./plans/%74opic.md)"), "重复索引"),
                             (("- [旧稿](plans/missing.md)",), "missing"),
                             (("- [其他](STANDARDS.md)",), "docs.plans")):
            with self.subTest(links=links):
                project.write_text(directory + "\n".join(links))
                self.assertTrue(any(error in item for item in validate_documents(self.config, self.root)))
        self.assertEqual(before, plan.read_bytes())

    def test_duplicate_topic_and_missing_baseline_proof_are_rejected(self) -> None:
        self.write_plan(self.lifecycle(version="v1"))
        other = self.write_plan(self.lifecycle(version="v1"), "duplicate.md")
        self.assertTrue(any("duplicate 主题 ID" in error for error in validate_documents(self.config, self.root)))
        other.write_text(self.lifecycle(topic="TOPIC-TWO", version="v2").replace(
            "- 验收证据: 已有验收记录 qa-old", "- 验收证据: none"))
        self.assertTrue(any("不能是待定" in error for error in validate_documents(self.config, self.root)))

    def test_baseline_proof_accepts_angle_destination_but_still_checks_file_and_placeholders(self):
        decision = self.docs / "order (v2).md"
        decision.write_text("用户确认了订单范围。")
        original = self.lifecycle(version="v1").replace(
            "原始用户批准记录 request-old", '[决定](<../order (v2).md> "确定依据")')
        plan = self.write_plan(original)
        (self.docs / "PROJECT.md").write_text("## 主题目录\n- 已验收：[订单](plans/topic.md)")
        self.assertEqual([], validate_documents(self.config, self.root))
        decision.unlink()
        self.assertTrue(any("证据链接不存在" in e for e in validate_documents(self.config, self.root)))
        plan.write_text(original.replace("[决定]", "<待填> [决定]"))
        self.assertTrue(any("模板占位" in e for e in validate_documents(self.config, self.root)))

    def test_project_indexes_each_accepted_plan_once_and_retains_explanatory_links(self):
        accepted = self.write_plan(self.lifecycle(version="v1"))
        project = self.docs / "PROJECT.md"
        explanation = "## 当前项目\n查询行为见[既有解释](plans/topic.md#旧行为)。\n"
        index = ("## 当前已验收基线 <!-- 已验收内容 -->\n"
                 "- [当前查询](plans/topic.md) <!-- [旧行内副本](plans/topic.md) -->\n"
                 "<!--\n## 历史边界仅供参考\n~~~md\n- [旧副本](plans/topic.md)\n"
                 "- [旧链接已缺失](plans/missing.md)\n-->\n")
        more = "## 受控资料入口\n另见[支持信息](plans/topic.md#支持)。\n"
        project.write_text(explanation + index + "```md\n<!--\n- [链接示例](plans/topic.md)\n```\n" + more)
        self.assertEqual([], validate_documents(self.config, self.root))
        project.write_text(explanation + index + "- [另一个标题](./plans/%74opic.md#别名)\n" + more)
        before = {path: path.read_bytes() for path in (accepted, project)}
        self.assertTrue(any("重复索引同一计划" in error for error in validate_documents(self.config, self.root)))
        self.assertEqual(before, {path: path.read_bytes() for path in before})


    @staticmethod
    def document_applier():
        # 通过真实脚本采用的 lib 搜索路径加载事务，避免复制发布器或用替身绕过磁盘行为。
        with patch.object(sys, "path", [str(PACK), *sys.path]):
            return importlib.import_module("lib.hosts.apply_antigravity_setup")


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
            "platforms/shared/skills/xy-project-memory/SKILL.md",
            "platforms/codex/references/pm-integration.md", "platforms/claude/references/pm-integration.md", "platforms/antigravity/references/pm-integration.md",
        ):
            self.assertIn(reference, read_contract(PACK / relative), relative)
        self.assertTrue((PACK / "templates/docs/PLAN.md").is_file())
        html_reference = PACK / "platforms/shared/skills/xy-plan/references/requirements-markdown.md"
        self.assertTrue(html_reference.is_file())
        self.assertIn("references/requirements-markdown.md", read_contract(PACK / "platforms/shared/skills/xy-plan/SKILL.md"))
