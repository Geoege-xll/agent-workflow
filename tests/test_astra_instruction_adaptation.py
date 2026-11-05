"""Astra 适配的可执行边界：引用校验、三宿主安装及用户配置保留。

自然语言指令的最终执行判断仍需独立情境审查/真实宿主反馈；这里不以文本断言
冒充模型行为测试，也不调用模型或实际业务项目。
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path
from unittest.mock import Mock

from lib.skill_contracts import expand_skill_contract, verification_scope_errors
from tests.skill_contract_helpers import read_contract
from tests.test_unified_host_workflow import HOSTS, UnifiedHostFixture


PACK = Path(__file__).resolve().parents[1]

# 只豁免现有机器协议字面量、兼容 fragment，以及用户要求保留的示例中文代码注释/
# 终端提示。按精确来源和完整片段列举；绝不忽略整段引号或围栏，避免漏翻自然语言。
MODEL_PROTOCOL_EXCEPTIONS = {
    "product/WORKFLOW.md": (
        "#完整读取必需长文", "`验收结果与当前已交付行为`", "`阶段`", "`当前进展与恢复入口`",
    ),
    "platforms/shared/skills/xy-workflow/SKILL.md": ("#完整读取必需长文",),
    "platforms/shared/skills/xy-qa-review/references/inputs.md": ('<a id="原生结构化交接"></a>',),
    "platforms/shared/skills/xy-workflow/references/plan-lifecycle.md": (
        "`主题 ID`", "`阶段`", "`模块`", "`任务等级`", "`已验收版本`", "`目标与范围`",
        "`需求与验收`", "`方案与原型关联`", "`当前进展与恢复入口`", "`验收结果与当前已交付行为`",
        "`批准依据与必要证据`", "`批准依据`", "`验收证据`",
    ),
    "platforms/shared/skills/xy-plan/references/requirement-html.md": ("`验收结果与当前已交付行为`",),
    "platforms/shared/skills/xy-workflow/references/dispatch.md": (
        "#完整读取必需长文", "# 上游快照生成失败时不要进入本段；校验失败时 && 会阻止依赖查询继续执行。",
    ),
    "platforms/shared/skills/xy-workflow/references/runtime-records.md": (
        "# 子 shell 只为本次诊断切换目录，不影响后续安装态命令的工作目录。",
        "${workflow_manager_source_root:?请设置中央管理工具源包根}",
        "${project_root:?请设置实际业务项目根}", "#原生结构化交接",
        '<a id="完整读取必需长文"></a>',
        "# 首页：只指定当前必需的一个文件；安装态从项目根运行。",
        "# 续页：填入上一完整回包的 next_offset 与首次页 sha256，不猜测位置。",
        "# 核对归属、使用和引用后，将预览返回的 snapshot_sha256 设为 scratch_snapshot_sha256。",
    ),
    "platforms/shared/skills/xy-prototype-verify/SKILL.md": (
        "# 复用此列表记录需求覆盖、规范符合性、交付一致性及各自证据/限制",
    ),
}


def without_model_protocol_literals(body: str, relative: str) -> str:
    """只去掉本来源明确保留的完整字面量；普通引号/代码围栏内仍检查语言。"""
    for literal in MODEL_PROTOCOL_EXCEPTIONS.get(relative, ()):
        body = body.replace(literal, "")
    return body


class ProgressiveContractTest(unittest.TestCase):
    def test_builtin_model_visible_sources_are_english_with_exact_protocol_exceptions(self) -> None:
        sources = [*(PACK / "product").glob("*.md"), *(PACK / "roles").glob("xy-*.md"),
                   PACK / "platforms/shared/AGENTS.product.tpl", PACK / "platforms/codex/WORKER_CONSTRAINTS.md",
                   *(PACK / "platforms").glob("*/references/pm-integration.md"),
                   *(PACK / "platforms/shared/skills").rglob("*.md")]
        for source in sources:
            relative = source.relative_to(PACK).as_posix()
            body = source.read_text(encoding="utf-8")
            with self.subTest(source=relative):
                for literal in MODEL_PROTOCOL_EXCEPTIONS.get(relative, ()):
                    self.assertIn(literal, body)
                self.assertNotRegex(without_model_protocol_literals(body, relative), r"[\u4e00-\u9fff]")
        # 负控防止未来把“代码示例/引号”整体忽略，导致模型可见自然语言再次漏翻。
        for body in ('"未翻译的模型指令"', '```text\n未翻译的模型指令\n```'):
            self.assertRegex(without_model_protocol_literals(body, "product/WORKFLOW.md"), r"[\u4e00-\u9fff]")

    def test_verification_policy_keeps_mandatory_evidence_and_rejects_inversions(self) -> None:
        body = read_contract(PACK / "platforms/shared/skills/xy-build-verify/SKILL.md")
        self.assertEqual([], verification_scope_errors(body))
        for inversion in ("QA may skip mandatory checks.", "Always run all discovered commands.",
                          "Reuse evidence without checking inputs."):
            with self.subTest(inversion=inversion):
                self.assertTrue(verification_scope_errors(body + "\n" + inversion))

    def test_expansion_preserves_sequence_and_ignores_auxiliary_links(self) -> None:
        reader = Mock(return_value="required approval\n")
        source = ("before\n[When dispatching](references/dispatch.md)\n"
                  "<!-- workflow-contract: references/dispatch.md -->\n"
                  "after\n[Optional history](references/history.md)\n")
        result = expand_skill_contract(source, reader)
        reader.assert_called_once_with("references/dispatch.md")
        self.assertLess(result.index("before"), result.index("required approval"))
        self.assertLess(result.index("required approval"), result.index("after"))
        self.assertIn("[Optional history](references/history.md)", result)

    def test_invalid_reference_is_rejected_before_reading(self) -> None:
        # 输入不合法时不得调用读取器，避免把 Markdown 指令升级为任意文件读取。
        for reference in ("../secret.md", "/private/secret.md", "references/../secret.md",
                          "references/nested/rule.md", "https://example.test/rule.md"):
            with self.subTest(reference=reference):
                reader = Mock()
                source = f"[Read]({reference})\n<!-- workflow-contract: {reference} -->\n"
                with self.assertRaisesRegex(ValueError, "malformed"):
                    expand_skill_contract(source, reader)
                reader.assert_not_called()

    def test_duplicate_unlinked_empty_and_recursive_references_fail(self) -> None:
        marker = "<!-- workflow-contract: references/rules.md -->"
        source = f"[Read when needed](references/rules.md)\n{marker}\n"
        for body, detail, expected in (
            (source + marker, "rule", "duplicate"),
            (marker, "rule", "routing link"),
            (source, " \n", "empty"),
            (source, marker, "nested"),
        ):
            with self.subTest(expected=expected), self.assertRaisesRegex(ValueError, expected):
                expand_skill_contract(body, lambda _reference: detail)

    def test_entrypoints_are_smaller_and_all_relative_markdown_links_resolve(self) -> None:
        for skill in ("xy-workflow", "xy-plan", "xy-qa-review"):
            directory = PACK / "platforms/shared/skills" / skill
            entry = directory / "SKILL.md"
            self.assertLess(len(entry.read_bytes()), len(read_contract(entry).encode("utf-8")))
            for path in directory.rglob("*.md"):
                for target in re.findall(r"\[[^\]\n]+\]\(([^)]+\.md)(?:#[^)]*)?\)",
                                         path.read_text(encoding="utf-8")):
                    if "://" not in target:
                        self.assertTrue((path.parent / target).is_file(), (path, target))


class ThreeHostAdaptationTest(UnifiedHostFixture, unittest.TestCase):
    def test_shared_coordination_contract_refresh_reaches_all_hosts(self) -> None:
        """验证源合同更新会真正进入三宿主入口和派发材料，而不是只检查某句文案。

        在临时夹具中先安装、再改变源合同、再安装，对比完整产物；不调用模型、
        不运行真实业务任务，也不把源文件复制成功等同于 Agent 行为已经得到证明。
        """

        temporary, project, pack = self.install_all()
        self.addCleanup(temporary.cleanup)
        bootstrap = pack / "platforms/shared/AGENTS.product.tpl"
        references = pack / "platforms/shared/skills/xy-workflow/references"
        changed_sources = [bootstrap, references / "dispatch.md",
                           references / "implementation-and-qa.md"]
        for source in changed_sources:
            # 在临时副本模拟升级；入口用等长说明替换，避免测试数据触发无关的入口
            # 体积限制。详细指令追加无语义注释，验证引用文件也会替换旧安装副本。
            body = source.read_text(encoding="utf-8")
            if source == bootstrap:
                changed = body.replace("Generated by", "Installed by", 1)
            else:
                changed = body + "\n<!-- coordination-refresh-fixture -->\n"
            self.assertNotEqual(body, changed)
            source.write_text(changed, encoding="utf-8")

        result = self.run_script(project, "setup_all.sh")
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        self.assertIn(bootstrap.read_text(encoding="utf-8").strip(),
                      (project / "AGENTS.md").read_text(encoding="utf-8"))
        # 发行模型正文与三宿主全部已生成角色均实际到达消费者，不能只筛查源模板。
        generated = [(project / "AGENTS.md", "AGENTS.md")]
        for directory in (".codex/agents", ".claude/agents", ".agents/agents"):
            generated.extend((path, path.relative_to(project).as_posix())
                             for path in (project / directory).glob("xy-*.*"))
        self.assertGreater(len(generated), 3)
        for path, relative in generated:
            with self.subTest(english_generated=relative):
                self.assertNotRegex(path.read_text(encoding="utf-8"), r"[\u4e00-\u9fff]")
        for root in (".agents/skills", ".claude/skills"):
            # Codex/Antigravity 共用 .agents，Claude 独立安装；两处都必须替换旧副本。
            for source in changed_sources[1:]:
                installed = project / root / "xy-workflow/references" / source.name
                self.assertEqual(source.read_bytes(), installed.read_bytes())
        for host in HOSTS:
            with self.subTest(host=host):
                checked = self.run_script(project, f"setup_{host}.sh", "--check")
                self.assertEqual(0, checked.returncode, checked.stdout + checked.stderr)

    def test_missing_reference_blocks_every_host_before_project_writes(self) -> None:
        for host, reference in ((host, reference) for host in HOSTS for reference in (
                "xy-plan/references/task-graph.md", "xy-build-verify/references/verification-scope.md")):
            with self.subTest(host=host, reference=reference):
                temporary, project, pack = self.make_fixture()
                self.addCleanup(temporary.cleanup)
                # 只删除临时夹具中唯一明确的规则文件；正式项目与源文件不受影响。
                (pack / "platforms/shared/skills" / reference).unlink()
                before = {str(path.relative_to(project)): path.read_bytes()
                          for path in project.rglob("*") if path.is_file()}
                result = self.run_script(project, f"setup_{host}.sh", "--preflight")
                self.assertNotEqual(0, result.returncode, result.stdout + result.stderr)
                self.assertNotIn("Traceback", result.stdout + result.stderr)
                self.assertIn(Path(reference).name, result.stdout + result.stderr)
                after = {str(path.relative_to(project)): path.read_bytes()
                         for path in project.rglob("*") if path.is_file()}
                self.assertEqual(before, after)

    def test_codex_worker_source_is_required_only_for_codex(self) -> None:
        temporary, project, pack = self.make_fixture()
        self.addCleanup(temporary.cleanup)
        source = pack / "platforms/codex/WORKER_CONSTRAINTS.md"
        source.unlink()
        blocked = self.run_script(project, "setup_codex.sh", "--preflight")
        self.assertNotEqual(0, blocked.returncode, blocked.stdout + blocked.stderr)
        self.assertIn("WORKER_CONSTRAINTS.md", blocked.stdout + blocked.stderr)
        self.assert_no_project_outputs(project)
        for host in ("claude", "antigravity"):
            checked = self.run_script(project, f"setup_{host}.sh", "--preflight")
            self.assertEqual(0, checked.returncode, checked.stdout + checked.stderr)
            self.assert_no_project_outputs(project)

    def test_codex_worker_source_rejects_links_and_extra_confirmation(self) -> None:
        for defect in ("symlink", "hardlink", "empty", "extra-gate"):
            with self.subTest(defect=defect):
                temporary, project, pack = self.make_fixture()
                self.addCleanup(temporary.cleanup)
                source = pack / "platforms/codex/WORKER_CONSTRAINTS.md"
                if defect == "empty":
                    source.write_text(" \n")
                elif defect == "extra-gate":
                    source.write_text(source.read_text() + "\nMust obtain another release approval.\n")
                else:
                    saved = pack / "worker-backup.md"
                    source.rename(saved)
                    if defect == "symlink":
                        source.symlink_to(saved)
                    else:
                        source.hardlink_to(saved)
                blocked = self.run_script(project, "setup_codex.sh", "--preflight")
                self.assertNotEqual(0, blocked.returncode, blocked.stdout + blocked.stderr)
                self.assert_no_project_outputs(project)

    def test_three_host_reinstall_keeps_references_and_user_preferences(self) -> None:
        temporary, project, pack = self.install_all()
        self.addCleanup(temporary.cleanup)
        config = project / ".codex/config.toml"
        # 模型、推理与输出风格属于用户；安装器不得借模型适配覆盖这些字段。
        user_settings = ('model = "gpt-6-astra"\nmodel_reasoning_effort = "high"\n'
                         'model_verbosity = "high"\n')
        config.write_text(user_settings + config.read_text(), encoding="utf-8")
        custom = project / ".claude/skills/user-helper/SKILL.md"
        custom.parent.mkdir(parents=True)
        custom.write_text("---\nname: user-helper\ndescription: User owned helper.\n---\n", encoding="utf-8")
        original_user = custom.read_bytes()
        first = self.run_script(project, "setup_all.sh")
        self.assertEqual(0, first.returncode, first.stdout + first.stderr)
        # Codex 和 Antigravity 原本共享 .agents/skills；不引入第二份分叉实现。
        for host, root in zip(HOSTS, (".claude/skills", ".agents/skills", ".agents/skills")):
            with self.subTest(host=host):
                checked = self.run_script(project, f"setup_{host}.sh", "--check")
                self.assertEqual(0, checked.returncode, checked.stdout + checked.stderr)
                for skill in ("xy-workflow", "xy-plan", "xy-qa-review", "xy-build-verify"):
                    source = pack / "platforms/shared/skills" / skill
                    for path in source.rglob("*.md"):
                        self.assertEqual(path.read_bytes(),
                                         (project / root / skill / path.relative_to(source)).read_bytes())
        self.assertTrue(config.read_text().startswith(user_settings))
        self.assertEqual(original_user, custom.read_bytes())
        before = {str(path.relative_to(project)): path.read_bytes()
                  for root in (".agents", ".claude", ".codex")
                  for path in (project / root).rglob("*") if path.is_file()}
        again = self.run_script(project, "setup_all.sh")
        self.assertEqual(0, again.returncode, again.stdout + again.stderr)
        after = {str(path.relative_to(project)): path.read_bytes()
                 for root in (".agents", ".claude", ".codex")
                 for path in (project / root).rglob("*") if path.is_file()}
        self.assertEqual(before, after)
