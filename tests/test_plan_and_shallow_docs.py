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

    def migrate(self, mapping, *, apply=False, restore=False, recovery=None, request_id=None):
        command = ["bash", str(PACK / "lib/python_runtime.sh"), "-X", "utf8", "-B",
                   str(PACK / "lib/migrate_project_docs.py"), "--project", str(self.root), "--restore" if restore else "--mapping", str(mapping)]
        if apply:
            command.append("--apply")
        if recovery is not None:
            command.extend(("--recovery", str(recovery)))
        if request_id is not None:
            command.extend(("--request-id", request_id))
        result = subprocess.run(command, cwd=PACK, capture_output=True, text=True, timeout=30)
        with (self.root / "migration.log").open("a", encoding="utf-8") as log:
            log.write(json.dumps({"argv": command, "cwd": str(PACK), "exit": result.returncode}, ensure_ascii=False)
                      + "\n" + result.stdout + result.stderr)
        return result

    def notes_fixture(self):
        """两份含历史/日志的旧原稿归入同一既有主题，其中一份同时归入既有规范。

        目标是人工给定的完整最终正文；测试明确区别归纳后的长期结论与恢复包中的
        原字节，不能靠简单把整篇 note 包进新 plan 取得通过。
        """
        notes = self.docs / "notes"
        notes.mkdir(exist_ok=True)
        first, second = notes / "first.md", notes / "second.md"
        first.write_bytes("# 旧经验甲\r\ncompleted / QA PASS 只是历史文字。\r\n完整原始日志 A。\r\n".encode())
        second.write_bytes("# 旧经验乙\n完整原始日志 B。\n".encode())
        first.chmod(0o600)
        second.chmod(0o640)
        target = self.write_plan(self.lifecycle(topic="TOPIC-NOTES"), "existing.md")
        target.chmod(0o640)
        standard = self.standards / "GENERAL.md"
        reader = self.root / "README.md"
        reader.write_text("# 既有项目说明\n[经验甲](docs/notes/first.md#旧经验甲)\n[经验乙](docs/notes/second.md)\n", encoding="utf-8")
        self.config.write_text(self.config.read_text().replace("memory:\n", "memory:\n  fallback_dir: docs/notes/\n")
                               + "  notes: docs/notes/\n", encoding="utf-8")
        manifest = {
            "schema_version": 2, "mode": "notes", "documents": [
                {"source": "docs/notes/first.md", "source_sha256": hashlib.sha256(first.read_bytes()).hexdigest(),
                 "targets": ["docs/plans/existing.md#方案与原型关联", "docs/standards/GENERAL.md"]},
                {"source": "docs/notes/second.md", "source_sha256": hashlib.sha256(second.read_bytes()).hexdigest(),
                 "targets": ["docs/plans/existing.md#当前进展与恢复入口"]},
            ], "target_updates": [
                {"path": "docs/plans/existing.md", "before_sha256": hashlib.sha256(target.read_bytes()).hexdigest(),
                 "content": target.read_text().replace("现有方案，无原型。", "现有方案，无原型。\n必要结论甲与乙。")},
                {"path": "docs/standards/GENERAL.md", "before_sha256": hashlib.sha256(standard.read_bytes()).hexdigest(),
                 "content": standard.read_text() + "\n既有规则的适用说明甲。\n"},
            ], "reference_updates": [
                {"path": "README.md", "before_sha256": hashlib.sha256(reader.read_bytes()).hexdigest(),
                 "content": "# 既有项目说明\n[经验甲主题](docs/plans/existing.md#方案与原型关联)\n"
                            "[经验甲规范](docs/standards/GENERAL.md)\n[经验乙](docs/plans/existing.md#当前进展与恢复入口)\n"},
            ],
        }
        mapping = self.root / "notes-mapping.json"
        mapping.write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
        return (first, second), target, standard, reader, mapping

    def test_notes_multitarget_preflight_apply_and_full_raw_restore(self) -> None:
        sources, target, standard, reader, mapping = self.notes_fixture()
        originals = {path: (path.read_bytes(), stat.S_IMODE(path.stat().st_mode))
                     for path in (*sources, target, standard, reader, self.config)}
        checked = self.migrate(mapping)
        self.assertEqual(0, checked.returncode, checked.stdout + checked.stderr)
        self.assertFalse((self.root / "migration-recovery.json").exists())
        for path, (body, mode) in originals.items():
            self.assertEqual((body, mode), (path.read_bytes(), stat.S_IMODE(path.stat().st_mode)))
        applied = self.migrate(mapping, apply=True)
        self.assertEqual(0, applied.returncode, applied.stdout + applied.stderr)
        self.assertTrue(all(not path.exists() for path in sources))
        self.assertIn("必要结论甲与乙", target.read_text())
        self.assertNotIn("完整原始日志", target.read_text() + standard.read_text())
        self.assertEqual({target}, set((self.docs / "plans").glob("*.md")))
        self.assertNotIn("docs/notes/", reader.read_text() + self.config.read_text())
        self.assertEqual([], validate_documents(self.config, self.root))
        recovery = self.root / "migration-recovery.json"
        snapshot = json.loads(recovery.read_text())
        self.assertEqual(0o600, stat.S_IMODE(recovery.stat().st_mode))
        for path in sources:
            self.assertEqual(originals[path][0], base64.b64decode(snapshot["files"][path.relative_to(self.root).as_posix()]["body_base64"]))
        # 正文编辑和仅权限变化都属于后续用户状态；恢复不得覆盖任何一种变化。
        published = target.read_bytes()
        for change in ("content", "permission"):
            with self.subTest(change=change):
                if change == "content":
                    target.write_bytes(published + "后续真实编辑。\n".encode())
                else:
                    target.chmod(0o600)
                refused = self.migrate(recovery, apply=True, restore=True)
                self.assertNotEqual(0, refused.returncode)
                self.assertIn("迁移后文件已变化", refused.stderr)
                self.assertFalse(sources[0].exists())
                target.write_bytes(published)
                target.chmod(0o640)
        restored = self.migrate(recovery, apply=True, restore=True)
        self.assertEqual(0, restored.returncode, restored.stdout + restored.stderr)
        for path, (body, mode) in originals.items():
            self.assertEqual((body, mode), (path.read_bytes(), stat.S_IMODE(path.stat().st_mode)))

    def test_notes_reference_definitions_full_collapsed_and_shortcut_cannot_keep_old_links(self) -> None:
        """引用定义是 full/collapsed/shortcut 的共同目标，不能只扫描 inline href。"""
        sources, target, standard, reader, mapping = self.notes_fixture()
        controlled = self.write_plan("# 既有引用所有者\n", "references.md")
        originals = {path: path.read_bytes() for path in (*sources, target, standard, reader, self.config)}
        variants = (
            "[旧经验][legacy]\n[legacy]: ../notes/first.md\n",
            "[legacy][]\n[legacy]: ../notes/first.md\n",
            "[legacy]\n[legacy]: ../notes/first.md\n",
            "[旧经验][LEGACY]\n[legacy]: <../notes/first.md> \"旧经验\"\n",
            "[旧经验][legacy]\n[legacy]:\n  ../notes/first.md\n",
            "[legacy]: ../notes/first.md\n",
            "[旧经验][legacy]\n> [legacy]: ../notes/first.md\n",
            "[旧经验][legacy]\n- [legacy]: ../notes/first.md\n",
            "[旧经验][legacy]\n[legacy]: ../note&#115;/first.md\n",
            "[旧经验](../note&#115;/first.md)\n",
        )
        for body in variants:
            with self.subTest(body=body):
                controlled.write_text("# 既有引用所有者\n" + body, encoding="utf-8")
                refused = self.migrate(mapping)
                self.assertNotEqual(0, refused.returncode, refused.stdout + refused.stderr)
                self.assertIn("notes 入站引用", refused.stderr)
                self.assertEqual(originals, {path: path.read_bytes() for path in originals})
                self.assertFalse((self.root / "migration-recovery.json").exists())
        # 合法外部定义不应一律被当作旧 notes；无法解释的定义也不能静默当作已修复。
        controlled.write_text("# 既有引用所有者\n[参考][safe]\n[safe]: <https://example.invalid/reference> \"说明\"\n", encoding="utf-8")
        safe = self.migrate(mapping)
        self.assertEqual(0, safe.returncode, safe.stdout + safe.stderr)
        controlled.write_text("# 既有引用所有者\n[旧经验][legacy]\n[legacy]:\n", encoding="utf-8")
        unknown = self.migrate(mapping)
        self.assertNotEqual(0, unknown.returncode)
        self.assertIn("无法安全解析引用式", unknown.stderr)

    @staticmethod
    def html_renderer():
        # 迁移脚本采用顶层 lib 导入；补丁与真实被调用模块一致，不用另一个包实例掩盖分支。
        with patch.object(sys, "path", [str(PACK / "lib"), *sys.path]):
            return importlib.import_module("requirement_html")

    def render_existing_notes_plan(self, target):
        renderer = self.html_renderer()
        legacy = self.config.read_bytes()
        with patch.object(sys, "path", [str(PACK / "lib"), *sys.path]):
            migration = importlib.import_module("migrate_project_docs")
        # 夹具先模拟在旧键加入前真实生成过的配对页；不放宽渲染器的运行时配置合同。
        self.config.write_bytes(migration.notes_config_view(legacy)[0])
        try:
            renderer.process("render", self.root, target.relative_to(self.root).as_posix(), "notes-html-migration")
        finally:
            self.config.write_bytes(legacy)
        return renderer

    def test_notes_existing_html_is_prepared_published_and_restored_with_markdown(self) -> None:
        sources, target, standard, reader, mapping = self.notes_fixture()
        renderer = self.render_existing_notes_plan(target)
        page = target.with_suffix(".html")
        page.chmod(0o640)
        originals = {path: (path.read_bytes(), stat.S_IMODE(path.stat().st_mode))
                     for path in (*sources, target, page, standard, reader, self.config)}
        missing_request = self.migrate(mapping)
        self.assertNotEqual(0, missing_request.returncode)
        self.assertIn("--request-id", missing_request.stderr)
        checked = self.migrate(mapping, request_id="notes-html-migration")
        self.assertEqual(0, checked.returncode, checked.stdout + checked.stderr)
        changed = {item["path"] for item in json.loads(checked.stdout)["changes"]}
        self.assertIn("docs/plans/existing.html", changed)
        for path, (body, mode) in originals.items():
            self.assertEqual((body, mode), (path.read_bytes(), stat.S_IMODE(path.stat().st_mode)))
        applied = self.migrate(mapping, apply=True, request_id="notes-html-migration")
        self.assertEqual(0, applied.returncode, applied.stdout + applied.stderr)
        self.assertEqual("fresh", renderer.process("check", self.root, "docs/plans/existing.md")["status"])
        recovery = self.root / "migration-recovery.json"
        self.assertIn("docs/plans/existing.html", json.loads(recovery.read_text())["files"])
        self.assertEqual(0o640, stat.S_IMODE(page.stat().st_mode))
        published = page.read_bytes()
        page.write_bytes(published + b"\n<!-- user edit -->\n")
        refused = self.migrate(recovery, apply=True, restore=True)
        self.assertNotEqual(0, refused.returncode)
        self.assertIn("迁移后文件已变化", refused.stderr)
        self.assertFalse(sources[0].exists())
        page.write_bytes(published)
        restored = self.migrate(recovery, apply=True, restore=True)
        self.assertEqual(0, restored.returncode, restored.stdout + restored.stderr)
        for path, (body, mode) in originals.items():
            self.assertEqual((body, mode), (path.read_bytes(), stat.S_IMODE(path.stat().st_mode)))

    def test_notes_unknown_or_modified_html_stops_before_any_source_delete(self) -> None:
        sources, target, standard, reader, mapping = self.notes_fixture()
        renderer = self.render_existing_notes_plan(target)
        page = target.with_suffix(".html")
        managed = page.read_bytes()
        originals = {path: path.read_bytes() for path in (*sources, target, standard, reader, self.config)}
        for body in (b"<html>user-owned</html>\n", managed + b"\n<!-- user edit -->\n"):
            with self.subTest(body=body[:40]):
                page.write_bytes(body)
                refused = self.migrate(mapping, request_id="notes-html-migration")
                self.assertNotEqual(0, refused.returncode, refused.stdout + refused.stderr)
                self.assertIn("保留原页", refused.stderr)
                self.assertEqual(body, page.read_bytes())
                self.assertEqual(originals, {path: path.read_bytes() for path in originals})
                self.assertFalse((self.root / "migration-recovery.json").exists())

    def test_notes_html_render_failure_stops_before_any_source_delete(self) -> None:
        sources, target, standard, reader, mapping = self.notes_fixture()
        renderer = self.render_existing_notes_plan(target)
        originals = {path: path.read_bytes() for path in (*sources, target, target.with_suffix(".html"), standard, reader, self.config)}
        with patch.object(sys, "path", [str(PACK / "lib"), *sys.path]):
            migration = importlib.import_module("migrate_project_docs")
        output = io.StringIO()
        with patch.object(sys, "path", [str(PACK / "lib"), *sys.path]), \
                patch.object(renderer.shutil, "which", return_value=None), contextlib.redirect_stderr(output):
            code = migration.main(["--project", str(self.root), "--mapping", str(mapping),
                                   "--request-id", "notes-html-migration", "--apply"])
        self.assertEqual(2, code)
        self.assertIn("Node.js >= 20", output.getvalue())
        self.assertEqual(originals, {path: path.read_bytes() for path in originals})
        self.assertFalse((self.root / "migration-recovery.json").exists())

    def test_notes_html_concurrent_edit_during_candidate_render_is_preserved(self) -> None:
        sources, target, standard, reader, mapping = self.notes_fixture()
        renderer = self.render_existing_notes_plan(target)
        page = target.with_suffix(".html")
        originals = {path: path.read_bytes() for path in (*sources, target, standard, reader, self.config)}
        actual = renderer.run_renderer
        def edit_target(*args):
            candidate = actual(*args)
            page.write_bytes(b"concurrent user HTML\n")
            return candidate
        with patch.object(sys, "path", [str(PACK / "lib"), *sys.path]):
            migration = importlib.import_module("migrate_project_docs")
        output = io.StringIO()
        with patch.object(sys, "path", [str(PACK / "lib"), *sys.path]), \
                patch.object(renderer, "run_renderer", side_effect=edit_target), contextlib.redirect_stderr(output):
            code = migration.main(["--project", str(self.root), "--mapping", str(mapping),
                                   "--request-id", "notes-html-migration", "--apply"])
        self.assertEqual(2, code)
        self.assertIn("并发变化", output.getvalue())
        self.assertEqual(b"concurrent user HTML\n", page.read_bytes())
        self.assertEqual(originals, {path: path.read_bytes() for path in originals})
        self.assertFalse((self.root / "migration-recovery.json").exists())

    def test_notes_html_publish_conflict_is_checked_before_source_deletion(self) -> None:
        """候选完成后的页面编辑仍必须先遇到条件发布拒绝，不能先删除原稿。"""
        sources, target, standard, reader, mapping = self.notes_fixture()
        self.render_existing_notes_plan(target)
        page = target.with_suffix(".html")
        originals = {path: path.read_bytes() for path in (*sources, target, standard, reader, self.config)}
        applier = self.document_applier()
        publish_file = applier._publish_file
        seen = []
        def change_html_before_publish(change, plan, **kwargs):
            if change.target == page:
                seen.append(page)
                self.assertTrue(all(path.exists() for path in sources))
                page.write_bytes(b"user edit after candidate render\n")
            return publish_file(change, plan, **kwargs)
        with patch.object(sys, "path", [str(PACK / "lib"), *sys.path]):
            migration = importlib.import_module("migrate_project_docs")
        output = io.StringIO()
        with patch.object(sys, "path", [str(PACK / "lib"), *sys.path]), \
                patch.object(applier, "_publish_file", side_effect=change_html_before_publish), contextlib.redirect_stderr(output):
            code = migration.main(["--project", str(self.root), "--mapping", str(mapping),
                                   "--request-id", "notes-html-migration", "--apply"])
        self.assertEqual(2, code)
        self.assertEqual([page], seen)
        self.assertEqual(b"user edit after candidate render\n", page.read_bytes())
        self.assertEqual(originals, {path: path.read_bytes() for path in originals})

    def test_notes_reject_stale_preimages_unknown_assets_and_unassigned_sources(self) -> None:
        sources, target, standard, reader, mapping = self.notes_fixture()
        manifest = json.loads(mapping.read_text())
        originals = {path: path.read_bytes() for path in (*sources, target, standard, reader, self.config)}
        mutations = (
            ("source-before", lambda value: value["documents"][0].update(source_sha256="0" * 64), "原稿摘要"),
            ("target-before", lambda value: value["target_updates"][0].update(before_sha256="0" * 64), "前像摘要"),
            ("reference-before", lambda value: value["reference_updates"][0].update(before_sha256="0" * 64), "前像摘要"),
            ("unmapped-source", lambda value: value["documents"].pop(), "精确覆盖"),
            ("empty-targets", lambda value: value["documents"][0].update(targets=[]), "非空显式"),
            ("new-target", lambda value: value["target_updates"][0].update(path="docs/plans/new.md"), "不创建目标"),
            ("missing-fragment", lambda value: value["documents"][0].update(targets=["docs/plans/existing.md#missing"]), "目标片段不存在"),
            ("invent-acceptance", lambda value: value["target_updates"][0].update(
                content=self.lifecycle(version="v1")), "不能创造主题"),
            ("missing-inbound-owner", lambda value: value["reference_updates"].clear(), "未使用"),
        )
        # README 是显式引用所有者；另外构造真实受控 reader 来证明漏报不能通过。
        controlled_reader = self.write_plan("# 既有执行稿\n[经验](../notes/first.md)\n", "reader.md")
        for name, mutate, expected in mutations:
            with self.subTest(name=name):
                value = copy.deepcopy(manifest)
                mutate(value)
                if name != "missing-inbound-owner":
                    controlled_reader.write_text("# 既有执行稿\n", encoding="utf-8")
                else:
                    controlled_reader.write_text("# 既有执行稿\n[经验](../notes/first.md)\n", encoding="utf-8")
                    expected = "仍有 notes 入站引用"
                mapping.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
                result = self.migrate(mapping, apply=True)
                self.assertNotEqual(0, result.returncode, result.stdout + result.stderr)
                self.assertIn(expected, result.stderr)
                self.assertEqual(originals, {path: path.read_bytes() for path in originals})
                self.assertFalse((self.root / "migration-recovery.json").exists())
        mapping.write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
        asset = self.docs / "notes/unknown.bin"
        asset.write_bytes(b"unknown asset; preserve")
        refused = self.migrate(mapping, apply=True)
        self.assertNotEqual(0, refused.returncode)
        self.assertIn("未明确迁移的资产", refused.stderr)
        self.assertEqual(b"unknown asset; preserve", asset.read_bytes())
        self.assertEqual(originals, {path: path.read_bytes() for path in originals})

    def test_notes_gap_conflicts_keep_raw_protection_without_deleting_sources(self) -> None:
        """真实恢复包写入后注入外部编辑/新增文件，验证发布前第二次核对的实际边界。"""
        sources, target, standard, reader, mapping = self.notes_fixture()
        with patch.object(sys, "path", [str(PACK / "lib"), *sys.path]):
            migration = importlib.import_module("migrate_project_docs")
        preserve = migration.preserve_originals
        for conflict in ("target-edit", "new-source"):
            with self.subTest(conflict=conflict):
                before = target.read_bytes()
                extra = self.docs / "notes/late.md"
                def mutate_after_protection(*args, **kwargs):
                    result = preserve(*args, **kwargs)
                    if conflict == "target-edit":
                        target.write_bytes(before + "并发用户编辑。\n".encode())
                    else:
                        extra.write_text("# 后到原稿\n", encoding="utf-8")
                    return result
                output = io.StringIO()
                # main 的延迟导入也使用与真实脚本一致的 lib 路径，不能依赖此前其他
                # 测试恰好把发布器载入 sys.modules，保证此竞态节点可独立执行。
                with patch.object(sys, "path", [str(PACK / "lib"), *sys.path]), \
                        patch.object(migration, "preserve_originals", side_effect=mutate_after_protection), contextlib.redirect_stderr(output):
                    code = migration.main(["--project", str(self.root), "--mapping", str(mapping), "--apply"])
                with (self.root / "migration.log").open("a", encoding="utf-8") as log:
                    log.write(f"notes gap {conflict}, exit={code}\n" + output.getvalue())
                self.assertEqual(2, code)
                self.assertIn("变化", output.getvalue())
                self.assertTrue(all(path.exists() for path in sources))
                snapshot = json.loads((self.root / "migration-recovery.json").read_text())
                self.assertEqual(sources[0].read_bytes(), base64.b64decode(snapshot["files"]["docs/notes/first.md"]["body_base64"]))
                # 夹具所有者撤回自己的竞态输入，工具本身必须保留该并发内容。
                if extra.exists():
                    extra.unlink()
                target.write_bytes(before)

    def test_features_with_notes_remain_explicit_sequential_migrations(self) -> None:
        sources, target, standard, reader, notes_mapping = self.notes_fixture()
        feature, _old, feature_mapping = self.migration_fixture()
        early = self.migrate(notes_mapping)
        self.assertNotEqual(0, early.returncode)
        self.assertIn("先完成显式 features", early.stderr)
        features = self.migrate(feature_mapping, apply=True)
        self.assertEqual(0, features.returncode, features.stdout + features.stderr)
        self.assertFalse(feature.exists())
        self.assertIn("  notes: docs/notes/", self.config.read_text())
        self.assertIn("  fallback_dir: docs/notes/", self.config.read_text())
        self.assertTrue(any("unsupported docs key: notes" in error for error in validate_documents(self.config, self.root)))
        notes = self.migrate(notes_mapping, apply=True, recovery=self.root / "notes-recovery.json")
        self.assertEqual(0, notes.returncode, notes.stdout + notes.stderr)
        self.assertEqual([], validate_documents(self.config, self.root))
        self.assertTrue(all(not path.exists() for path in sources))

    def test_notes_late_source_during_publication_rolls_back_without_erasing_it(self) -> None:
        """发布结果验收时出现后到原稿，恢复本轮前像但保留该外部新增文件。"""
        sources, target, standard, reader, mapping = self.notes_fixture()
        originals = {path: path.read_bytes() for path in (*sources, target, standard, reader, self.config)}
        with patch.object(sys, "path", [str(PACK / "lib"), *sys.path]):
            migration = importlib.import_module("migrate_project_docs")
        validate_current = migration.validate
        extra = self.docs / "notes/late.md"
        def add_late_source(*args, **kwargs):
            errors = validate_current(*args, **kwargs)
            extra.write_text("# 发布中的外部新原稿\n", encoding="utf-8")
            return errors
        output = io.StringIO()
        with patch.object(sys, "path", [str(PACK / "lib"), *sys.path]), \
                patch.object(migration, "validate", side_effect=add_late_source), contextlib.redirect_stderr(output):
            code = migration.main(["--project", str(self.root), "--mapping", str(mapping), "--apply"])
        with (self.root / "migration.log").open("a", encoding="utf-8") as log:
            log.write(f"notes publication late source, exit={code}\n" + output.getvalue())
        self.assertEqual(2, code)
        self.assertIn("新增未映射原稿", output.getvalue())
        self.assertEqual(originals, {path: path.read_bytes() for path in originals})
        self.assertEqual("# 发布中的外部新原稿\n", extra.read_text())
        self.assertFalse(list(self.root.glob(".agent-workflow-pack-antigravity--*")))

    def test_notes_directory_presence_never_grants_retirement_authority(self) -> None:
        notes = self.docs / "notes"
        notes.mkdir()
        source = notes / "old.md"
        source.write_text("# 没有旧配置授权的原稿\n", encoding="utf-8")
        mapping = self.root / "notes-empty-mapping.json"
        mapping.write_text(json.dumps({"schema_version": 2, "mode": "notes", "documents": [],
            "target_updates": [], "reference_updates": []}), encoding="utf-8")
        before = source.read_bytes(), self.config.read_bytes()
        refused = self.migrate(mapping, apply=True)
        self.assertNotEqual(0, refused.returncode)
        self.assertIn("不会再次迁移或从目录存在", refused.stderr)
        self.assertEqual(before, (source.read_bytes(), self.config.read_bytes()))
        # 仅夹具所有者撤去自己构造的未授权原稿；显式空清单才能处理真实缺失的旧目录。
        source.unlink()
        notes.rmdir()
        self.config.write_text(self.config.read_text().replace("memory:\n", "memory:\n  fallback_dir: docs/notes/\n")
                               + "  notes: docs/notes/\n", encoding="utf-8")
        applied = self.migrate(mapping, apply=True)
        self.assertEqual(0, applied.returncode, applied.stdout + applied.stderr)
        self.assertFalse(notes.exists())
        self.assertNotIn("fallback_dir:", self.config.read_text())
        self.assertNotIn("  notes:", self.config.read_text())

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

    def test_migration_rebases_binary_and_directory_navigation_without_moving_assets(self) -> None:
        """导航目标只需安全元数据；微型合成媒体不是 Markdown 原稿，也不迁入 plans。"""
        source, old, mapping_path = self.migration_fixture()
        assets = self.root / "assets"
        assets.mkdir(exist_ok=True)
        media = assets / "sample.mp4"
        media.write_bytes(b"\x00\xff\x80synthetic-media")
        directory = self.root / "services/creation-service"
        directory.mkdir(parents=True, exist_ok=True)
        old += "[媒体](../../assets/sample.mp4#preview)\n[服务目录](../../services/creation-service/)\n"
        source.write_text(old, encoding="utf-8")
        mapping = json.loads(mapping_path.read_text(encoding="utf-8"))
        mapping["documents"][0].update(target="docs/plans/archive/query.md",
                                       source_sha256=hashlib.sha256(source.read_bytes()).hexdigest())
        mapping_path.write_text(json.dumps(mapping, ensure_ascii=False), encoding="utf-8")
        # 读取合成资产本身可能更新 atime；只比较能证明未发布/替换/改权的稳定元数据。
        def asset_identity(path):
            info = path.stat()
            return info.st_dev, info.st_ino, info.st_mode, info.st_size, info.st_mtime_ns

        media_before = media.read_bytes(), asset_identity(media)
        directory_before = directory.stat()
        originals = {path: path.read_bytes() for path in (source, self.config, self.docs / "PROJECT.md")}
        result = self.migrate(mapping_path, apply=True)
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        target = self.docs / "plans/archive/query.md"
        self.assertIn("[媒体](../../../assets/sample.mp4#preview)", target.read_text(encoding="utf-8"))
        self.assertIn("[服务目录](../../../services/creation-service/)", target.read_text(encoding="utf-8"))
        self.assertEqual([target], list((self.docs / "plans").rglob("*.*")))
        self.assertEqual(media_before, (media.read_bytes(), asset_identity(media)))
        self.assertEqual(directory_before, directory.stat())
        # 原件保护和精确恢复继续由既有迁移协议负责，导航资源不成为恢复写入对象。
        recovery = self.root / "migration-recovery.json"
        self.assertNotIn("assets/sample.mp4", json.loads(recovery.read_text(encoding="utf-8"))["files"])
        restored = self.migrate(recovery, apply=True, restore=True)
        self.assertEqual(0, restored.returncode, restored.stdout + restored.stderr)
        for path, body in originals.items():
            self.assertEqual(body, path.read_bytes())
        self.assertEqual(media_before, (media.read_bytes(), asset_identity(media)))
        self.assertEqual(directory_before, directory.stat())

    def test_migration_navigation_keeps_missing_link_and_special_node_rejections(self) -> None:
        """不读媒体不等于放行危险节点；Markdown 仍须完整安全 UTF-8 读取。"""
        source, old, mapping_path = self.migration_fixture()
        assets = self.root / "assets"
        assets.mkdir(exist_ok=True)
        media = assets / "sample.bin"
        media.write_bytes(b"\x00\xffsynthetic-media")
        (assets / "linked.bin").symlink_to(media)
        os.link(media, assets / "hardlinked.bin")
        os.mkfifo(assets / "pipe.bin")
        (assets / "bad.md").write_bytes(b"\xffinvalid-markdown")
        (self.root / "linked-assets").symlink_to(assets, target_is_directory=True)
        mapping = json.loads(mapping_path.read_text(encoding="utf-8"))
        before = self.config.read_bytes(), (self.docs / "PROJECT.md").read_bytes()
        for href in ("../../assets/missing.bin", "../../assets/linked.bin", "../../assets/hardlinked.bin",
                     "../../assets/pipe.bin", "../../assets/bad.md", "../../linked-assets/sample.bin",
                     "../../assets/sample.bin/child", "../../../outside.bin"):
            with self.subTest(href=href):
                body = old + f"[导航]({href})\n"
                source.write_text(body, encoding="utf-8")
                mapping["documents"][0]["source_sha256"] = hashlib.sha256(source.read_bytes()).hexdigest()
                mapping_path.write_text(json.dumps(mapping, ensure_ascii=False), encoding="utf-8")
                result = self.migrate(mapping_path, apply=True)
                self.assertNotEqual(0, result.returncode, result.stdout + result.stderr)
                self.assertEqual(body, source.read_text(encoding="utf-8"))
                self.assertEqual(before, (self.config.read_bytes(), (self.docs / "PROJECT.md").read_bytes()))
                self.assertFalse((self.docs / "plans").exists())

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

    @staticmethod
    def document_applier():
        # 通过真实脚本采用的 lib 搜索路径加载事务，避免复制发布器或用替身绕过磁盘行为。
        with patch.object(sys, "path", [str(PACK / "lib"), *sys.path]):
            return importlib.import_module("apply_antigravity_setup")

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
