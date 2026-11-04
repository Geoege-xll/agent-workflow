"""分级计划入口与浅层规范的回归：验证实际结构、权限和审计，不触及真实项目。"""

from __future__ import annotations

import copy
import base64
import stat
import hashlib
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from tests.skill_contract_helpers import read_contract

from lib.standard_paths import canonical_standard_path, standard_domain, source_domain, canonical_standard_source_path
from lib.validate_project_config import validate_docs
from lib.validate_project_docs import validate as validate_documents
from lib.plan_documents import SECTIONS, parse_plan
from lib.validate_prototype_workspace import ValidationError, validate_workspace
from tests import test_design_standards_lifecycle as design_cases
from tests import test_prototype_workspace as prototype_cases
from tests import test_qa_handoff as qa_cases
# 保护路径反例必须先具备当前2.0身份，才能验证真实设计边界，避免被旧格式拒绝掩盖。
from tests.test_scheduler_boundaries import v2_graph


PACK = Path(__file__).resolve().parents[1]


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

    def migration_fixture(self, *, missing_proof=False, unsafe_link=False):
        legacy = self.docs / "features"
        legacy.mkdir(exist_ok=True)
        source = legacy / "query.md"
        old = ("# 查询功能\n- Feature ID: FEATURE-QUERY\n- Status: active\n- Current version: v1\n"
               "- Approval basis: 原始用户批准记录 request-old\n"
               "- Acceptance evidence: 已有验收记录 qa-old\n\n项目专有内容、必要历史与实际查询行为。\n")
        if missing_proof:
            old = old.replace("- Approval basis: 原始用户批准记录 request-old\n", "")
        if unsafe_link:
            old += "[外逃](../../../outside.md)\n"
        source.write_text(old, encoding="utf-8")
        self.config.write_text(self.config.read_text() + "  features: docs/features/\n")
        (self.docs / "PROJECT.md").write_text("# 项目专有标题\n[查询基线](features/query.md)\n保留项目说明。\n")
        content = self.lifecycle(version="v1").replace(
            "旧版本已交付查询行为；本次写入功能尚未交付。", "{{原文}}")
        mapping = {"schema_version": 1, "documents": [{
            "source": "docs/features/query.md", "target": "docs/plans/query.md",
            "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(), "content": content}]}
        path = self.root / "migration.json"
        path.write_text(json.dumps(mapping, ensure_ascii=False), encoding="utf-8")
        return source, old, path

    def migrate(self, mapping, *, apply=False, restore=False):
        command = ["bash", str(PACK / "lib/python_runtime.sh"), "-X", "utf8", "-B",
                   str(PACK / "lib/migrate_project_docs.py"), "--project", str(self.root), "--restore" if restore else "--mapping", str(mapping)]
        if apply:
            command.append("--apply")
        result = subprocess.run(command, cwd=PACK, capture_output=True, text=True, timeout=30)
        with (self.root / "migration.log").open("a", encoding="utf-8") as log:
            log.write(json.dumps({"argv": command, "cwd": str(PACK), "exit": result.returncode}, ensure_ascii=False)
                      + "\n" + result.stdout + result.stderr)
        return result

    def test_explicit_single_migration_preserves_body_index_and_noop_preflight(self) -> None:
        source, old, mapping = self.migration_fixture()
        before = {p: p.read_bytes() for p in self.root.rglob("*") if p.is_file()}
        result = self.migrate(mapping)
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        self.assertTrue(all(path.read_bytes() == body for path, body in before.items()))
        self.assertFalse((self.docs / "plans").exists())
        result = self.migrate(mapping, apply=True)
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        self.assertFalse(source.exists())
        target = self.docs / "plans/query.md"
        self.assertIn(old, target.read_text())
        self.assertNotIn("features:", self.config.read_text())
        self.assertIn("[查询基线](plans/query.md)", (self.docs / "PROJECT.md").read_text())
        self.assertIn("保留项目说明", (self.docs / "PROJECT.md").read_text())
        self.assertEqual([], validate_documents(self.config, self.root))
        repeated = self.migrate(mapping, apply=True)
        self.assertNotEqual(0, repeated.returncode)
        self.assertIn("不会再次迁移", repeated.stderr)

    def test_migration_stops_on_target_conflict_without_mutating_sources(self) -> None:
        source, old, mapping = self.migration_fixture()
        target = self.write_plan("# 既有真实主题，不能覆盖\n", "query.md")
        before = self.config.read_bytes(), (self.docs / "PROJECT.md").read_bytes(), target.read_bytes()
        result = self.migrate(mapping, apply=True)
        self.assertNotEqual(0, result.returncode)
        self.assertIn("目标冲突", result.stderr)
        self.assertEqual(old, source.read_text())
        self.assertEqual(before, (self.config.read_bytes(), (self.docs / "PROJECT.md").read_bytes(), target.read_bytes()))

    def test_migration_cannot_invent_old_approval_or_follow_unsafe_links(self) -> None:
        source, old, mapping = self.migration_fixture(missing_proof=True)
        result = self.migrate(mapping, apply=True)
        self.assertNotEqual(0, result.returncode)
        self.assertIn("旧来源缺少匹配", result.stderr)
        self.assertEqual(old, source.read_text())
        self.assertFalse((self.docs / "plans").exists())

    def test_migration_unsafe_link_stops_before_any_publication(self) -> None:
        source, old, mapping = self.migration_fixture(unsafe_link=True)
        result = self.migrate(mapping, apply=True)
        self.assertNotEqual(0, result.returncode)
        self.assertIn("越出项目", result.stderr)
        self.assertEqual(old, source.read_text())
        self.assertFalse((self.docs / "plans").exists())

    def test_migration_rebases_preserved_body_and_explicit_reference_owners(self) -> None:
        source, old, mapping_path = self.migration_fixture()
        old += "[项目规范](../standards/GENERAL.md)\n"
        source.write_text(old, encoding="utf-8")
        notes = self.docs / "notes"
        notes.mkdir()
        reader = notes / "reader.md"
        reader.write_text("# 既有项目说明\n[查询](../features/query.md#历史)\n保留专有文字。\n")
        mapping = json.loads(mapping_path.read_text())
        mapping["documents"][0].update(target="docs/plans/archive/query.md", source_sha256=hashlib.sha256(source.read_bytes()).hexdigest())
        mapping["reference_updates"] = ["docs/notes/reader.md"]
        mapping_path.write_text(json.dumps(mapping, ensure_ascii=False), encoding="utf-8")
        result = self.migrate(mapping_path, apply=True)
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        target = self.docs / "plans/archive/query.md"
        self.assertIn(old.replace("../standards/GENERAL.md", "../../standards/GENERAL.md"), target.read_text())
        self.assertEqual("# 既有项目说明\n[查询](../plans/archive/query.md#历史)\n保留专有文字。\n", reader.read_text())
        self.assertIn("(plans/archive/query.md)", (self.docs / "PROJECT.md").read_text())

    def test_failed_final_validation_rolls_back_all_migration_files(self) -> None:
        source, old, mapping = self.migration_fixture()
        self.write_plan("# 旧执行历史\n- Status: completed\n", "unverified.md")
        project = self.docs / "PROJECT.md"
        project.write_text(project.read_text() + "[未验收稿](plans/unverified.md)\n")
        config_before, project_before = self.config.read_bytes(), project.read_bytes()
        result = self.migrate(mapping, apply=True)
        self.assertNotEqual(0, result.returncode)
        self.assertIn("迁移结果校验失败", result.stderr)
        self.assertEqual(old, source.read_text())
        self.assertEqual(config_before, self.config.read_bytes())
        self.assertEqual(project_before, project.read_bytes())
        self.assertFalse((self.docs / "plans/query.md").exists())
        self.assertFalse(list(self.docs.rglob(".agent-workflow-pack-antigravity--*")))

    def test_migration_cannot_promote_removed_or_unindexed_old_material(self) -> None:
        source, old, mapping_path = self.migration_fixture()
        mapping = json.loads(mapping_path.read_text())
        for state, indexed in (("removed", True), ("active", False), ("active", True)):
            with self.subTest(state=state, indexed=indexed):
                source.write_text(old.replace("- Status: active", "- Status: " + state), encoding="utf-8")
                (self.docs / "PROJECT.md").write_text("# 项目\n" + ("[查询](features/query.md)\n" if indexed else "未列入当前功能的历史材料。\n"))
                mapping["documents"][0]["source_sha256"] = hashlib.sha256(source.read_bytes()).hexdigest()
                mapping_path.write_text(json.dumps(mapping, ensure_ascii=False), encoding="utf-8")
                before = source.read_bytes(), self.config.read_bytes()
                result = self.migrate(mapping_path, apply=True)
                if state == "active" and indexed:
                    self.assertEqual(0, result.returncode, result.stdout + result.stderr)
                    self.assertEqual([], validate_documents(self.config, self.root))
                    self.assertIn(old, (self.docs / "plans/query.md").read_text())
                    continue
                self.assertNotEqual(0, result.returncode)
                self.assertIn("不能", result.stderr)
                self.assertEqual(before, (source.read_bytes(), self.config.read_bytes()))
                self.assertFalse((self.docs / "plans/query.md").exists())

    def test_untracked_original_and_permissions_survive_success_and_exact_restore(self) -> None:
        source, old, mapping_path = self.migration_fixture()
        old += "[原规范](../standards/GENERAL.md)\n"
        source.write_bytes(old.encode("utf-8"))
        source.chmod(0o600)
        mapping = json.loads(mapping_path.read_text())
        mapping["documents"][0].update(target="docs/plans/archive/query.md", source_sha256=hashlib.sha256(source.read_bytes()).hexdigest())
        mapping_path.write_text(json.dumps(mapping, ensure_ascii=False), encoding="utf-8")
        paths = (source, self.config, self.docs / "PROJECT.md")
        originals = {path: (path.read_bytes(), stat.S_IMODE(path.stat().st_mode)) for path in paths}
        result = self.migrate(mapping_path, apply=True)
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        recovery = self.root / "migration-recovery.json"
        snapshot = json.loads(recovery.read_text())
        self.assertEqual(0o600, stat.S_IMODE(recovery.stat().st_mode))
        self.assertEqual(originals[source][0], base64.b64decode(snapshot["files"]["docs/features/query.md"]["body_base64"]))
        self.assertFalse(source.exists())
        target = self.docs / "plans/archive/query.md"
        self.assertEqual(0o600, stat.S_IMODE(target.stat().st_mode))
        self.assertIn("../../standards/GENERAL.md", target.read_text())
        published = target.read_bytes()
        target.write_bytes(published + "\n外部编辑，不能覆盖。".encode())
        conflict = self.migrate(recovery, apply=True, restore=True)
        self.assertNotEqual(0, conflict.returncode)
        self.assertIn("迁移后文件已变化", conflict.stderr)
        self.assertIn("外部编辑", target.read_text())
        # 测试所有者主动撤回模拟并发编辑，才允许按原快照恢复；工具不能自行覆盖它。
        target.write_bytes(published)
        restored = self.migrate(recovery, apply=True, restore=True)
        self.assertEqual(0, restored.returncode, restored.stdout + restored.stderr)
        self.assertTrue(recovery.exists())
        self.assertFalse(target.exists())
        for path, (body, mode) in originals.items():
            self.assertEqual(body, path.read_bytes())
            self.assertEqual(mode, stat.S_IMODE(path.stat().st_mode))

    def test_conflicting_recovery_file_stops_before_original_deletion(self) -> None:
        source, old, mapping = self.migration_fixture()
        recovery = self.root / "migration-recovery.json"
        recovery.write_bytes(b"existing user recovery; must preserve\n")
        before = self.config.read_bytes(), (self.docs / "PROJECT.md").read_bytes(), recovery.read_bytes()
        result = self.migrate(mapping, apply=True)
        self.assertNotEqual(0, result.returncode)
        self.assertIn("固定恢复副本已存在", result.stderr)
        self.assertEqual(old, source.read_text())
        self.assertEqual(before, (self.config.read_bytes(), (self.docs / "PROJECT.md").read_bytes(), recovery.read_bytes()))
        self.assertFalse((self.docs / "plans").exists())

    def test_git_head_bytes_do_not_hide_unrecorded_private_permissions(self) -> None:
        source, old, mapping = self.migration_fixture()
        # 仅在此临时夹具创建真实 Git 基线；不提交源仓库、不写全局 Git 配置。
        commands = [
            ["git", "init", str(self.root)],
            ["git", "-C", str(self.root), "config", "user.name", "Workflow Fixture"],
            ["git", "-C", str(self.root), "config", "user.email", "workflow-fixture@example.invalid"],
            ["git", "-C", str(self.root), "add", "project.yaml", "docs/PROJECT.md", "docs/features/query.md"],
            ["git", "-C", str(self.root), "commit", "-m", "fixture original bytes"],
        ]
        if (self.root / ".git").is_dir():
            # 固定夹具重试复用已存在的真实提交，不能为重跑再造一个历史版本。
            commands = [["git", "-C", str(self.root), "rev-parse", "--verify", "HEAD"]]
        for command in commands:
            result = subprocess.run(command, cwd=PACK, capture_output=True, text=True, timeout=15)
            with (self.root / "git-fixture.log").open("a", encoding="utf-8") as log:
                log.write(json.dumps({"argv": command, "cwd": str(PACK), "exit": result.returncode}) + "\n" + result.stdout + result.stderr)
            self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        source.chmod(0o600)
        result = self.migrate(mapping, apply=True)
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        recovery = self.root / "migration-recovery.json"
        snapshot = json.loads(recovery.read_text())
        # Git 精确保护了配置／索引，但没有记录原稿的 0600；只为这个缺口保存原字节。
        self.assertIsNone(snapshot["files"]["project.yaml"]["body_base64"])
        self.assertIsNotNone(snapshot["files"]["project.yaml"]["git_path"])
        self.assertEqual(0o600, snapshot["files"]["docs/features/query.md"]["before_mode"])
        self.assertEqual(old.encode(), base64.b64decode(snapshot["files"]["docs/features/query.md"]["body_base64"]))
        restored = self.migrate(recovery, apply=True, restore=True)
        self.assertEqual(0, restored.returncode, restored.stdout + restored.stderr)
        self.assertEqual(old, source.read_text())
        self.assertEqual(0o600, stat.S_IMODE(source.stat().st_mode))

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
        html_reference = PACK / "platforms/shared/skills/xy-plan/references/requirement-html.md"
        self.assertTrue(html_reference.is_file())
        self.assertIn("references/requirement-html.md", read_contract(PACK / "platforms/shared/skills/xy-plan/SKILL.md"))
