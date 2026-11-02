"""通用规范单一来源迁移：只操作临时项目，保留项目字节与原事务安全边界。"""
from __future__ import annotations

from functools import lru_cache
import importlib
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from lib import install_workflow
from lib.standards_baseline import COMMON_BEGIN, COMMON_END, common_block, common_span
from lib.validate_project_config import validate_with_profile
from lib.validate_project_docs import validate as validate_documents
from tests import test_unified_host_workflow as host_cases

PACK = host_cases.PACK
# 两份最小历史输入只作测试数据：旧 UPSTREAM 证明整文归属，旧索引证明链接清理。
# 它们不是规范来源；通用规则始终以 Skill 为唯一 authority。测试不依赖 Git 历史。


LEGACY_UPSTREAM = b'# Upstream and Second-Development Standards \xe2\x80\x94 {{PROJECT_NAME}}\n\n- Domain: engineering\n\n> Define protected upstream/open-source boundaries here. If the project has no embedded upstream\n> source, state that explicitly instead of inventing a protected path.\n\n## Boundary declaration\n\n- Protected upstream roots: **TODO or not applicable**\n- Allowed extension/adaptor/overlay paths: **TODO or not applicable**\n- Direct upstream edits: **forbidden without an approved exception | allowed by project policy**\n- Upstream synchronization strategy: **TODO or not applicable**\n\n## Exceptional change contract\n\n- `[eng-upstream-001] [hard]` A protected upstream write requires the matching exceptional approval,\n  exact patch surface, reason, rollback plan, upstream-sync impact, and verification commands.\n- `[eng-upstream-002] [hard]` An exception authorizes only its declared paths and does not weaken\n  unrelated engineering or design rules.\n'
LEGACY_INDEX = b"# Standards \xe2\x80\x94 {{PROJECT_NAME}}\n\n> Canonical directory for enforceable engineering and design rules. Keep this file as a concise\n> index; detailed rules live in the linked leaf documents, while approved prototype evidence lives\n> under standards/prototype and is read only when it applies.\n\n## Usage contract\n\n- Every rule uses a stable lowercase ID and declares `hard` or `advisory` severity.\n- Normative Markdown leaves live directly in the configured standards root. Design leaves use\n  `DESIGN_*.md` and `- Domain: design`; other leaves declare `- Domain: engineering`. Group links\n  below by domain and describe applicable modules/paths; do not add engineering/design/references subtrees.\n- PM Task Packs select the smallest applicable leaf documents, bind their current fingerprints and\n  rule IDs to exact owned paths, and never preload the whole standards tree.\n- `GENERAL.md` \xe6\x98\xaf\xe7\x94\x9f\xe4\xba\xa7\xe4\xbb\xa3\xe7\xa0\x81\xe5\x8f\x98\xe6\x9b\xb4\xef\xbc\x88\xe5\x8c\x85\xe6\x8b\xac Trivial \xe4\xb8\xbb\xe4\xbc\x9a\xe8\xaf\x9d\xe7\x9b\xb4\xe6\x8e\xa5\xe4\xbf\xae\xe6\x94\xb9\xef\xbc\x89\xe7\x9a\x84\xe5\x9f\xba\xe7\xa1\x80\xe5\xb7\xa5\xe7\xa8\x8b\xe8\xa7\x84\xe8\x8c\x83\xe5\x8f\xb6\xe3\x80\x82\n  \xe6\x89\xa7\xe8\xa1\x8c\xe8\x80\x85\xe9\xa1\xbb\xe8\xaf\xbb\xe5\x8f\x96\xe5\x85\xb6\xe4\xb8\xad\xe9\x80\x82\xe7\x94\xa8\xe7\x9a\x84\xe5\x85\xb1\xe9\x80\x9a\xe5\xbc\x80\xe5\x8f\x91\xe8\xa7\x84\xe8\x8c\x83\xef\xbc\x9b\xe6\x9c\x89\xe6\xb4\xbe\xe5\x8f\x91\xe5\x92\x8c\xe7\x8b\xac\xe7\xab\x8b QA \xe6\x97\xb6\xef\xbc\x8cPM\xe3\x80\x81\xe5\xae\x9e\xe7\x8e\xb0 Agent \xe4\xb8\x8e QA\n  \xe5\x90\x84\xe8\x87\xaa\xe6\x8c\x89\xe8\x81\x8c\xe8\xb4\xa3\xe8\xaf\xbb\xe5\x8f\x96\xe3\x80\x82\xe5\x85\xb6\xe4\xbb\x96\xe5\xb7\xa5\xe7\xa8\x8b\xe8\xa7\x84\xe8\x8c\x83\xe5\x8f\xb6\xe6\x8c\x89\xe4\xbb\xbb\xe5\x8a\xa1\xe7\x9b\xb8\xe5\x85\xb3\xe6\x80\xa7\xe9\x80\x89\xe5\x8f\x96\xef\xbc\x9b\xe7\xba\xaf\xe5\x8e\x9f\xe5\x9e\x8b\xe8\xae\xbe\xe8\xae\xa1\xe4\xbb\xbb\xe5\x8a\xa1\xe5\x8f\xaa\xe4\xbd\xbf\xe7\x94\xa8\xe8\xae\xbe\xe8\xae\xa1\xe8\xa7\x84\xe8\x8c\x83\xe5\x8f\xb6\xe3\x80\x82\n- Subagents must follow every selected rule. A missing, stale, or incomplete applicable rule set\n  blocks dispatch or QA PASS; \xe2\x80\x9cread on demand\xe2\x80\x9d is not permission to ignore a relevant standard.\n- Update current rules in place. Git retains history; this directory does not record task logs.\n- Maintain stable topics: extend the existing section first; a new leaf needs a justified independent\n  boundary, not one rule or task per file. Keep common rules authoritative and specialist differences\n  scoped. Apply WORKFLOW's `Standards document granularity and maintenance` without weakening the\n  reading and coverage contract above.\n- PM assesses/adopts design-rule changes; UI Agent maintains authorized leaves. Initial adoption,\n  incremental changes and full visual replacement update only their approved scope. A feature-doc\n  no-op does not imply a standards no-op; refresh affected consumers after rule adoption.\n- Normative design rules live in leaves, not a duplicate HTML index. Adopted rules do not assert\n  that all production pages have migrated; use verified feature truth for completed migration.\n\n## Engineering standards\n\n{{ENGINEERING_STANDARDS_INDEX}}\n\n## Design standards\n\n{{DESIGN_STANDARDS_INDEX}}\n\n## Related controlled truth\n\n- Current project and feature index: `{{DOC_PROJECT}}`\n- Current functional and architectural rationale: `{{DOC_FEATURES_DIR}}/`\n- Prototype evidence, when configured: `{{DOC_DESIGN_DIR}}/prototype/`\n"

@lru_cache(maxsize=None)
def legacy_template(name: str) -> bytes:
    """用当前规则原文和最小旧壳构造迁移样本，不再复制三十条规范正文。"""
    from lib.standards_baseline import RULE_ITEM_RE
    if name == "UPSTREAM.md":
        return LEGACY_UPSTREAM
    if name == "STANDARDS.md":
        return LEGACY_INDEX
    source_name = {
        "GENERAL.md": "xy-code-standards/references/rules.md",
        "DESIGN_FOUNDATIONS.md": "xy-ui-design/references/foundations-rules.md",
        "DESIGN_COMPONENTS.md": "xy-ui-design/references/components-rules.md",
    }[name]
    source = (PACK / "platforms/shared/skills" / source_name).read_bytes()
    paragraphs = {match[1]: match.group().rstrip(b"\r\n") for match in RULE_ITEM_RE.finditer(source)}
    if name == "GENERAL.md":
        outside = b"\n".join(value for key, value in paragraphs.items()
                               if key.startswith(b"eng-verification-") or key == b"eng-secrets-001")
        # 正例必须是真实历史完整受管区：仅拼接规则 ID/条目不能证明区内没有项目资料。
        common_rules = source.split("## 共通开发规范\n\n".encode(), 1)[1].split("\n## 上游与二次开发适用边界".encode(), 1)[0]
        managed_header = "## 共通开发规范\n\n本区由工作流安装器维护，升级时仅更新此标记区块；项目专属要求写在区块外的 Project-specific rules 中。\n\n".encode()
        common = managed_header + common_rules.rstrip(b"\n")
        return b"# Legacy engineering\n- Domain: engineering\n\n" + outside + b"\n\n## Managed common\n\n" + COMMON_BEGIN + b"\n" + common + b"\n" + COMMON_END + b"\n"
    return b"# Legacy design\n- Domain: design\n\n" + b"\n".join(paragraphs.values()) + b"\n"


def rendered_legacy(name: str, project: Path, pack: Path) -> bytes:
    from lib.standards_baseline import _observed_baseline
    discovered = validate_with_profile(pack / "project.yaml", project, pack / "roles")
    assert not discovered.errors and discovered.profile is not None, discovered.errors
    values = {
        "PROJECT_NAME": "MyProject", "DOC_PROJECT": "docs/PROJECT.md", "DOC_FEATURES_DIR": "docs/features",
        "DOC_DESIGN_DIR": "docs/standards", "OBSERVED_BASELINE": _observed_baseline(discovered.profile),
        "ENGINEERING_STANDARDS_INDEX": "- [General engineering rules](standards/GENERAL.md)\n- [Upstream and second-development boundaries](standards/UPSTREAM.md)",
        "DESIGN_STANDARDS_INDEX": "- No design standards are configured for the discovered project profile.",
    }
    return re.sub(r"\{\{([A-Z_]+)\}\}", lambda match: values[match[1]], legacy_template(name).decode()).encode()


class GeneralOwnershipTest(unittest.TestCase):
    def test_malformed_markers_are_rejected(self):
        valid = COMMON_BEGIN + b"\nold\n" + COMMON_END
        self.assertEqual((0, len(valid)), common_span(valid))
        self.assertIsNone(common_span(b"# Project rules\n"))
        for damaged in (COMMON_BEGIN, COMMON_END, valid + COMMON_BEGIN,
                        COMMON_END + b"\n" + COMMON_BEGIN, b"inline " + valid):
            with self.subTest(damaged=damaged), self.assertRaisesRegex(ValueError, "markers"):
                common_span(damaged)


class GeneralPublisherTest(host_cases.UnifiedHostFixture, unittest.TestCase):
    def fixture(self):
        temporary, project, pack = self.make_fixture()
        self.addCleanup(temporary.cleanup)
        (project / "go.mod").write_text("module example.test/general\n", encoding="utf-8")
        return project, pack

    def publish(self, project, pack, host="shared", *, success=True):
        result = (self.run_script(project, "scripts/scaffold_project_docs.sh") if host == "shared"
                  else host_cases.UnifiedSetupContractTest.run_antigravity_applier(self, project, pack))
        self.assertEqual(0 if success else 1, 0 if result.returncode == 0 else 1,
                         result.stdout + result.stderr)
        return result

    def old_documents(self, project, pack):
        root = project / "docs/standards"
        root.mkdir(parents=True, exist_ok=True)
        for name in ("GENERAL.md", "UPSTREAM.md", "DESIGN_FOUNDATIONS.md", "DESIGN_COMPONENTS.md"):
            (root / name).write_bytes(rendered_legacy(name, project, pack))
        (project / "docs/STANDARDS.md").write_bytes(rendered_legacy("STANDARDS.md", project, pack))

    def test_new_install_creates_no_generic_leaves_or_empty_index(self):
        for host in ("shared", "antigravity"):
            with self.subTest(host=host):
                project, pack = self.fixture()
                self.publish(project, pack, host)
                self.assertFalse((project / "docs/STANDARDS.md").exists())
                self.assertFalse((project / "docs/standards").exists())
                self.assertTrue((project / "docs/PROJECT.md").is_file())
                self.assertEqual([], validate_documents(pack / "project.yaml", project))

    def test_exact_old_default_is_removed_by_both_publishers_and_not_recreated(self):
        for host in ("shared", "antigravity"):
            with self.subTest(host=host):
                project, pack = self.fixture()
                target = project / "docs/standards/UPSTREAM.md"
                target.parent.mkdir(parents=True)
                target.write_bytes(rendered_legacy("UPSTREAM.md", project, pack))
                index = project / "docs/STANDARDS.md"
                index.write_bytes(rendered_legacy("STANDARDS.md", project, pack))
                self.publish(project, pack, host)
                self.assertFalse(target.exists())
                self.assertFalse(index.exists())
                if host == "antigravity":
                    # 测试辅助器的 staging 是本夹具独占过程产物；只清理它，原项目与
                    # 已发布原生资源继续原地复用，才能验证真正的再次安装幂等。
                    shutil.rmtree(project / "antigravity-test-staging")
                before = {p: (p.read_bytes(), p.stat().st_ino) for p in (project / "docs").rglob("*") if p.is_file()}
                self.publish(project, pack, host)
                self.assertEqual(before, {p: (p.read_bytes(), p.stat().st_ino) for p in before})

    def test_common_region_removal_preserves_exact_project_bytes_and_mode(self):
        for host in ("shared", "antigravity"):
            with self.subTest(host=host):
                project, pack = self.fixture()
                target = project / "docs/standards/GENERAL.md"
                target.parent.mkdir(parents=True)
                prefix = "# 专有约束\r\n- Domain: engineering\r\n\r\n".encode()
                suffix = "\r\n\r\n- `[eng-project-only] [hard]` 项目约束。  ".encode()
                target.write_bytes(prefix + common_block(legacy_template("GENERAL.md")) + suffix)
                target.chmod(0o600)
                self.publish(project, pack, host)
                self.assertEqual(prefix + suffix, target.read_bytes())
                self.assertEqual(0o600, stat.S_IMODE(target.stat().st_mode))
                self.assertIn(b"standards/GENERAL.md", (project / "docs/STANDARDS.md").read_bytes())
                self.assertEqual([], validate_documents(pack / "project.yaml", project))

    def test_unmarked_project_file_is_preserved_and_index_only_gains_missing_link(self):
        project, pack = self.fixture()
        general = project / "docs/standards/GENERAL.md"
        general.parent.mkdir(parents=True)
        original = b"# Project General\n- Domain: engineering\n- `[eng-local-only] [hard]` Project rule.\n"
        general.write_bytes(original)
        index = project / "docs/STANDARDS.md"
        before = b"# Custom index\r\n\r\nProject index text.\r\n"
        index.write_bytes(before)
        self.publish(project, pack)
        self.assertEqual(original, general.read_bytes())
        self.assertTrue(index.read_bytes().startswith(before))
        self.assertEqual(1, index.read_bytes().count(b"standards/GENERAL.md"))

    def test_known_default_rule_paragraphs_move_but_project_notes_survive(self):
        from lib.standards_baseline import RULE_ITEM_RE
        for host in ("shared", "antigravity"):
            with self.subTest(host=host):
                project, pack = self.fixture()
                target = project / "docs/standards/GENERAL.md"
                target.parent.mkdir(parents=True)
                old = legacy_template("GENERAL.md")
                secret = next(m.group().rstrip(b"\r\n") for m in RULE_ITEM_RE.finditer(old) if m[1] == b"eng-secrets-001")
                prefix = b"# Project notes\r\n- Domain: engineering\r\n\r\n"
                note = "\r\n\r\n## 项目备注\r\n保留项目说明及尾部 空格  ".encode()
                target.write_bytes(prefix + secret.replace(b"\n", b"\r\n") + note)
                self.publish(project, pack, host)
                self.assertEqual(prefix + note, target.read_bytes())
                self.assertFalse((project / "docs/STANDARDS.md").exists())

    def test_modified_builtin_id_or_unknown_common_rule_stops_before_writes(self):
        from lib.standards_baseline import RULE_ITEM_RE
        source = (PACK / "platforms/shared/skills/xy-code-standards/references/rules.md").read_bytes()
        secret = next(m.group().rstrip(b"\r\n") for m in RULE_ITEM_RE.finditer(source)
                      if m[1] == b"eng-secrets-001")
        common = common_block(legacy_template("GENERAL.md"))
        modified = re.sub(rb"(?m)^- `\[eng-common-005\] \[hard\]`[^\r\n]*",
                          b"- `[eng-common-005] [hard]` USER-MODIFIED-CONTRACT", common, count=1)
        extended = tuple(common.replace(COMMON_END, addition + COMMON_END) for addition in (
            b"\nUSER-PLAIN-CONTRACT\n", b"\n  USER-CONTINUATION\n",
            b"\n| USER-TABLE | project contract |\n| --- | --- |\n| Keep | this value |\n",
        ))
        common_prefix = b"# Project rules\n- Domain: engineering\n"
        for variant, body in enumerate((
            b"# Custom General\n- Domain: engineering\n- `[eng-secrets-001] [hard]` Custom meaning must survive.\n",
            b"# General\n- Domain: engineering\n" + COMMON_BEGIN + b"\n- `[eng-project-private] [hard]` Keep me.\n" + COMMON_END,
            COMMON_BEGIN,
            b"# Project rule\n- Domain: engineering\n\n" + secret
            + b"\n\n  Project-specific continuation must retain its rule identity.\n",
            *(common_prefix + region for region in (modified, *extended)),
        )):
            with self.subTest(variant=variant):
                project, pack = self.fixture()
                general = project / "docs/standards/GENERAL.md"
                general.parent.mkdir(parents=True)
                general.write_bytes(body)
                self.publish(project, pack, success=False)
                self.assertEqual(body, general.read_bytes())
                self.assertFalse((project / "docs/PROJECT.md").exists())
                self.assertFalse((project / "docs/STANDARDS.md").exists())

    def test_custom_design_rule_survives_generic_paragraph_migration(self):
        project, pack = self.fixture()
        target = project / "docs/standards/DESIGN_FOUNDATIONS.md"
        target.parent.mkdir(parents=True)
        custom = "\n- `[des-project-brand] [hard]` 品牌映射遵循项目专用源。\n".encode()
        target.write_bytes(rendered_legacy(target.name, project, pack) + custom)
        self.publish(project, pack)
        self.assertTrue(target.read_bytes().endswith(custom))
        ids = re.findall(rb"\[(des-[a-z0-9-]+)\] \[(?:hard|advisory)\]", target.read_bytes())
        self.assertEqual([b"des-project-brand"], ids)
        self.assertEqual([], validate_documents(pack / "project.yaml", project))

    def test_same_size_concurrent_project_edit_is_not_overwritten(self):
        project, pack = self.fixture()
        target = project / "docs/standards/GENERAL.md"
        target.parent.mkdir(parents=True)
        target.write_bytes(legacy_template("GENERAL.md"))
        size = target.stat().st_size
        with patch.dict(os.environ, {"AGENT_WORKFLOW_PACK_TEST_SCAFFOLD_RACE": "managed:docs/standards/GENERAL.md"}):
            result = self.run_script(project, "scripts/scaffold_project_docs.sh")
        self.assertNotEqual(0, result.returncode)
        self.assertIn("changed during publish", result.stdout + result.stderr)
        self.assertEqual(b"X" * size, target.read_bytes())
        self.assertFalse((project / "docs/PROJECT.md").exists())

    def test_edit_after_planning_cannot_be_rebound_as_the_original_input(self):
        """计划后的新内容不得被快照追认为 before，再被旧 after 覆盖。"""
        project, pack = self.fixture()
        target = project / "docs/standards/UPSTREAM.md"
        target.parent.mkdir(parents=True)
        target.write_bytes(legacy_template("UPSTREAM.md"))
        planner = install_workflow.plan_standard_updates
        concurrent = b"# Project-specific replacement\n"

        def change_after_plan(*args, **kwargs):
            result = planner(*args, **kwargs)
            target.write_bytes(concurrent)
            return result

        with patch.object(install_workflow, "plan_standard_updates", side_effect=change_after_plan):
            with self.assertRaisesRegex(install_workflow.InstallError, "迁移规划后发生变更"):
                install_workflow._standard_update_snapshots(pack, project)
        self.assertEqual(concurrent, target.read_bytes())
        self.assertFalse((project / "docs/PROJECT.md").exists())

    def test_antigravity_rollback_restores_deleted_defaults_with_original_mode(self):
        project, pack = self.fixture()
        self.old_documents(project, pack)
        general = project / "docs/standards/GENERAL.md"
        general.chmod(0o640)
        before = {p: (p.read_bytes(), stat.S_IMODE(p.stat().st_mode)) for p in (project / "docs").rglob("*.md")}
        with patch.dict(os.environ, {"AGENT_WORKFLOW_PACK_TEST_FAILPOINT": "antigravity-after-agents-publish"}):
            self.publish(project, pack, "antigravity", success=False)
        self.assertEqual(before, {p: (p.read_bytes(), stat.S_IMODE(p.stat().st_mode)) for p in before})

    def test_antigravity_failure_removes_only_the_created_project_index(self):
        """由真实规划器标记新建薄索引，并在宿主失败后安全撤回，避免只测手工标记。"""
        project, pack = self.fixture()
        leaf = project / "docs/standards/LOCAL.md"
        leaf.parent.mkdir(parents=True)
        original = b"# Local project rules\n- Domain: engineering\n- `[eng-project-local] [hard]` Keep project constraint.\n"
        leaf.write_bytes(original)
        with patch.dict(os.environ, {"AGENT_WORKFLOW_PACK_TEST_FAILPOINT": "antigravity-after-agents-publish"}):
            self.publish(project, pack, "antigravity", success=False)
        self.assertEqual(original, leaf.read_bytes())
        self.assertFalse((project / "docs/STANDARDS.md").exists())


class GeneralAtomicPublicationTest(unittest.TestCase):
    @staticmethod
    def applier():
        # 发布器也是直接脚本入口，按它实际使用的 lib 搜索路径加载，不修改全局环境。
        with patch.object(sys, "path", [str(PACK / "lib"), *sys.path]):
            return importlib.import_module("apply_antigravity_setup")

    def test_antigravity_document_publication_and_rollback_preserve_concurrent_content(self):
        applier = self.applier()
        for moment in ("gap", "after"):
            with self.subTest(moment=moment), tempfile.TemporaryDirectory() as raw:
                project = Path(raw).resolve()
                target = project / "GENERAL.md"
                target.write_bytes(b"original project rules\n")
                change = applier.FileChange(target, b"new common rules\n", 0o600, applier._fingerprint(target))
                plan = applier.Plan(PACK, project, project, "general-publication-test")
                plan.doc_changes.append(change)
                concurrent = b"concurrent project-specific note\n"
                replace = os.replace

                def publish_gap(source, destination):
                    replace(source, destination)
                    if Path(source) == target:
                        target.write_bytes(concurrent)

                if moment == "gap":
                    with patch.object(applier.os, "replace", side_effect=publish_gap):
                        with self.assertRaisesRegex(applier.ApplyError, "cannot atomically replace"):
                            applier._publish_file(change, plan)
                else:
                    applier._publish_file(change, plan)
                    target.write_bytes(concurrent)
                with self.assertRaisesRegex(applier.ApplyError, "Document.*preserved current file and backup"):
                    applier._rollback(plan)
                self.assertEqual(concurrent, target.read_bytes())
                self.assertEqual(b"original project rules\n", change.backup.read_bytes())

    def test_antigravity_keeps_late_modified_document_backup(self):
        applier = self.applier()
        with tempfile.TemporaryDirectory() as raw:
            project = Path(raw).resolve()
            target = project / "GENERAL.md"
            target.write_bytes(b"original project rules\n")
            change = applier.FileChange(target, b"new common rules\n", 0o600, applier._fingerprint(target))
            plan = applier.Plan(PACK, project, project, "general-backup-test")
            plan.doc_changes.append(change)
            applier._publish_file(change, plan)
            # 模拟编辑器仍持有原 inode，在文件已移入事务备份后继续保存专项。
            change.backup.write_bytes(b"late project-specific change\n")
            with self.assertRaisesRegex(applier.ApplyError, "preserve changed document backup"):
                applier._cleanup_committed(plan)
            self.assertEqual(b"late project-specific change\n", change.backup.read_bytes())
            self.assertEqual(change.body, target.read_bytes())

    def test_deleted_document_restore_preserves_recreation_after_missing_sample(self):
        applier = self.applier()
        with tempfile.TemporaryDirectory() as raw:
            project = Path(raw).resolve()
            target = project / "GENERAL.md"
            target.write_bytes(b"original default\n")
            change = applier.FileChange(target, None, 0o600, applier._fingerprint(target))
            plan = applier.Plan(PACK, project, project, "restore-missing-race")
            plan.doc_changes.append(change)
            applier._publish_file(change, plan)
            check = applier._assert_unchanged
            concurrent = b"USER-RECREATED-AFTER-SAMPLE\n"
            injected = False

            def inject_after_missing_sample(path, expected):
                nonlocal injected
                check(path, expected)
                if Path(path) == change.backup and not injected:
                    injected = True
                    target.write_bytes(concurrent)

            with patch.object(applier, "_assert_unchanged", side_effect=inject_after_missing_sample):
                with self.assertRaises(applier.ApplyError):
                    applier._rollback(plan)
            self.assertTrue(injected)
            self.assertEqual(concurrent, target.read_bytes())
            self.assertEqual(b"original default\n", change.backup.read_bytes())

    def test_created_index_rollback_preserves_replacement_after_sampling(self):
        applier = self.applier()
        published = b"# Published project standards index\n"
        for replacement in (None, b"USER-REPLACED-INDEX\n", published):
            with self.subTest(replacement=replacement), tempfile.TemporaryDirectory() as raw:
                project = Path(raw).resolve()
                target = project / "STANDARDS.md"
                change = applier.FileChange(target, published, 0o600, applier._fingerprint(target), created_standard_index=True)
                plan = applier.Plan(PACK, project, project, "remove-created-race")
                plan.doc_changes.append(change)
                applier._publish_file(change, plan)
                if replacement is None:
                    applier._rollback(plan)
                    self.assertFalse(target.exists())
                    continue
                read = applier._read_regular
                injected = False

                def inject_after_sampling(path, label):
                    nonlocal injected
                    body = read(path, label)
                    if Path(path) == target and not injected:
                        injected = True
                        candidate = project / "user-index-replacement"
                        candidate.write_bytes(replacement)
                        candidate.chmod(0o600)
                        os.replace(candidate, target)
                    return body

                with patch.object(applier, "_read_regular", side_effect=inject_after_sampling):
                    with self.assertRaises(applier.ApplyError):
                        applier._rollback(plan)
                self.assertTrue(injected)
                self.assertEqual(replacement, target.read_bytes())



class GeneralDeletionTransactionTest(unittest.TestCase):
    def test_deletion_rollback_restores_original_and_preserves_concurrent_recreation(self):
        applier = GeneralAtomicPublicationTest.applier()
        for concurrent in (False, True):
            with self.subTest(concurrent=concurrent), tempfile.TemporaryDirectory() as raw:
                project = Path(raw).resolve()
                target = project / "GENERAL.md"
                target.write_bytes(b"original managed default\n")
                target.chmod(0o640)
                change = applier.FileChange(target, None, 0o640, applier._fingerprint(target))
                plan = applier.Plan(PACK, project, project, "deletion-test")
                plan.doc_changes.append(change)
                applier._publish_file(change, plan)
                self.assertFalse(target.exists())
                if concurrent:
                    target.write_bytes(b"concurrent project rule\n")
                    with self.assertRaisesRegex(applier.ApplyError, "changed after deletion"):
                        applier._rollback(plan)
                    self.assertEqual(b"concurrent project rule\n", target.read_bytes())
                    self.assertEqual(b"original managed default\n", change.backup.read_bytes())
                else:
                    applier._rollback(plan)
                    self.assertEqual(b"original managed default\n", target.read_bytes())
                    self.assertEqual(0o640, stat.S_IMODE(target.stat().st_mode))


class GeneralInstallerRecoveryTest(unittest.TestCase):
    def test_real_three_host_install_then_migration_preserves_business_and_project_rules(self):
        with tempfile.TemporaryDirectory(prefix="workflow-builtin-install-") as raw:
            root = Path(raw).resolve()
            project = root / "中文 Project"
            project.mkdir()
            business = project / "go.mod"
            business.write_bytes(b"module example.test/general\n")
            def install():
                result = subprocess.run(["bash", str(PACK / "install.sh"), str(project)], cwd=root,
                                        text=True, capture_output=True, check=False, timeout=180)
                self.assertEqual(0, result.returncode, result.stdout + result.stderr)
                for host in ("Claude", "Codex", "Antigravity"):
                    self.assertIn(f"{host} --check", result.stdout)
            install()
            self.assertFalse((project / "docs/STANDARDS.md").exists())
            general = project / "docs/standards/GENERAL.md"
            general.parent.mkdir(parents=True)
            prefix = b"# Project rules\n- Domain: engineering\n"
            suffix = "\n- `[eng-project-only] [hard]` 保留本项目特有约束。\n".encode()
            general.write_bytes(prefix + common_block(legacy_template("GENERAL.md")) + suffix)
            general.chmod(0o600)
            index = project / "docs/STANDARDS.md"
            index_before = b"# Custom index\n\nProject explanation.\n"
            index.write_bytes(index_before)
            protected = {p: (p.read_bytes(), p.stat().st_ino) for p in (business, project / "docs/PROJECT.md")}
            config = (project / ".agent-workflow/project.yaml").read_bytes()
            install()
            self.assertEqual(prefix + suffix, general.read_bytes())
            self.assertEqual(0o600, stat.S_IMODE(general.stat().st_mode))
            self.assertTrue(index.read_bytes().startswith(index_before))
            self.assertEqual(config, (project / ".agent-workflow/project.yaml").read_bytes())
            self.assertEqual(protected, {p: (p.read_bytes(), p.stat().st_ino) for p in protected})

    def test_recovery_handles_deletion_and_refuses_concurrent_permission_change(self):
        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw).resolve() / "GENERAL.md"
            install_workflow._restore_standard_updates([(path, b"previous rules\n", None, 0o600)])
            self.assertEqual(b"previous rules\n", path.read_bytes())
            self.assertEqual(0o600, stat.S_IMODE(path.stat().st_mode))
            path.write_bytes(b"published rules\n")
            path.chmod(0o640)
            with self.assertRaisesRegex(install_workflow.InstallError, "发生其他变更"):
                install_workflow._restore_standard_updates([(path, b"previous rules\n", b"published rules\n", 0o600)])
            self.assertEqual(b"published rules\n", path.read_bytes())
            self.assertEqual(0o640, stat.S_IMODE(path.stat().st_mode))

    def test_deleted_snapshot_restore_preserves_recreation_after_missing_read(self):
        with tempfile.TemporaryDirectory() as raw:
            target = Path(raw).resolve() / "GENERAL.md"
            read = install_workflow.read_file
            concurrent = b"USER-RECREATED-AFTER-READ\n"
            injected = False

            def inject_after_missing_read(path):
                nonlocal injected
                body = read(path)
                if Path(path) == target and body is None and not injected:
                    injected = True
                    target.write_bytes(concurrent)
                return body

            with patch.object(install_workflow, "read_file", side_effect=inject_after_missing_read):
                with self.assertRaises(install_workflow.InstallError):
                    install_workflow._restore_standard_updates([(target, b"old default\n", None, 0o600)])
            self.assertTrue(injected)
            self.assertEqual(concurrent, target.read_bytes())

    def test_created_index_snapshot_rollback_preserves_replacement_after_sampling(self):
        published = b"# Published project standards index\n"
        for replacement in (None, b"USER-REPLACED-INDEX\n", published):
            with self.subTest(replacement=replacement), tempfile.TemporaryDirectory() as raw:
                project = Path(raw).resolve()
                target = project / "STANDARDS.md"
                target.write_bytes(published)
                target.chmod(0o600)
                if replacement is None:
                    install_workflow._restore_standard_updates([(target, None, published, 0o600)])
                    self.assertFalse(target.exists())
                    continue
                read = install_workflow.read_file
                injected = False

                def inject_after_sampling(path):
                    nonlocal injected
                    body = read(path)
                    if Path(path) == target and not injected:
                        injected = True
                        candidate = project / "user-index-replacement"
                        candidate.write_bytes(replacement)
                        candidate.chmod(0o600)
                        os.replace(candidate, target)
                    return body

                with patch.object(install_workflow, "read_file", side_effect=inject_after_sampling):
                    with self.assertRaises(install_workflow.InstallError):
                        install_workflow._restore_standard_updates([(target, None, published, 0o600)])
                self.assertTrue(injected)
                self.assertEqual(replacement, target.read_bytes())

    def test_failed_upgrade_restores_deleted_default_and_index_before_old_setup(self):
        for concurrent in (False, True):
            with self.subTest(concurrent=concurrent), tempfile.TemporaryDirectory() as raw:
                project = Path(raw).resolve() / "project"
                project.mkdir()
                with patch.object(install_workflow, "_run_setup"):
                    install_workflow._install(project, PACK)
                general = project / "docs/standards/UPSTREAM.md"
                general.parent.mkdir(parents=True)
                original = legacy_template("UPSTREAM.md")
                general.write_bytes(original)
                general.chmod(0o600)
                index = project / "docs/STANDARDS.md"
                index_original = legacy_template("STANDARDS.md")
                index.write_bytes(index_original)
                calls = []
                def setup(runtime, target, *options):
                    calls.append(options)
                    if len(calls) == 2:
                        for path, _before, after, _mode in install_workflow._standard_update_snapshots(runtime, target):
                            if after is None:
                                path.unlink()
                            else:
                                path.write_bytes(after)
                        if concurrent:
                            general.write_bytes(b"concurrent project rule\n")
                        raise subprocess.CalledProcessError(7, "setup_all.sh")
                    if len(calls) >= 3:
                        self.assertEqual(original, general.read_bytes())
                        self.assertEqual(index_original, index.read_bytes())
                with patch.object(install_workflow, "_run_setup", side_effect=setup):
                    with self.assertRaises(install_workflow.InstallError):
                        install_workflow._install(project, PACK)
                self.assertEqual(b"concurrent project rule\n" if concurrent else original, general.read_bytes())
                self.assertEqual(index_original, index.read_bytes())
                self.assertEqual(2 if concurrent else 4, len(calls))


if __name__ == "__main__":
    unittest.main()
