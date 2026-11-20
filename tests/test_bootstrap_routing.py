"""验证实际插件的主会话、业务资源与宿主调度入口之间的合同。"""

import json
import os
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from lib.skills.business_confirmation_policy import (
    HOST_INTEGRATIONS, read_instruction_contract, validate_execution_texts,
)


PACK = Path(__file__).resolve().parents[1]


class PluginRoutingTest(unittest.TestCase):
    @unittest.skipUnless(shutil.which("claude"), "需要本机 Claude CLI 读取有效的 Auto 配置")
    def test_claude_auto_example_reuses_user_source_across_projects(self):
        # 用官方配置查询直接消费面向用户的示例。配置、两个项目和工作目录均在临时
        # 范围；无需启动模型、使用用户凭证或写入任何真实用户与项目设置。
        page = (PACK / HOST_INTEGRATIONS["claude"]).read_text(encoding="utf-8")
        example = json.loads(re.search(r"```json\n(.+?)\n```", page, re.S).group(1))
        entries = example["autoMode"]["environment"]
        self.assertEqual(["$defaults"], entries[:1])
        self.assertEqual(1, len(entries[1:]))
        self.assertIn("https://github.com/Geoege-xll/agent-workflow", entries[1])
        with tempfile.TemporaryDirectory(prefix="xy-claude-auto-") as temporary:
            root = Path(temporary)
            config = root / "user"
            config.mkdir()
            env = {"PATH": os.environ["PATH"], "CLAUDE_CONFIG_DIR": str(config),
                   "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1"}

            def effective(directory):
                result = subprocess.run(["claude", "auto-mode", "config"], cwd=directory, env=env,
                                        capture_output=True, text=True, timeout=15)
                self.assertEqual(0, result.returncode, result.stderr)
                return json.loads(result.stdout)

            defaults = effective(root)
            # 先模拟用户已有的环境条目，再按文档仅追加一条来源，保留系统默认。
            entries.insert(1, "Existing personal environment entry")
            (config / "settings.json").write_text(json.dumps(example), encoding="utf-8")
            for name in ("one", "two"):
                project = root / name
                (project / ".claude").mkdir(parents=True)
                local = {"autoMode": {"environment": ["project-local marker"]}}
                (project / ".claude/settings.local.json").write_text(json.dumps(local), encoding="utf-8")
                result = effective(project)
                self.assertEqual(defaults["environment"] + entries[1:], result["environment"])
                for key in ("allow", "soft_deny", "hard_deny"):
                    self.assertEqual(defaults[key], result[key])

    def test_first_claude_helper_links_to_the_official_install_receipts(self):
        # 真实模型先取通用包适配，再决定是否调用解释器。只在权限拒绝这一节补说明，
        # 会让首次正常路径先执行缓存代码；检查实际链接位置和两种外部登记的字段。
        adapter_path = PACK / "plugins/plugin-context.md"
        adapter = adapter_path.read_text(encoding="utf-8")
        link = re.search(r"\[Claude 安装来源核对\]\(([^)#]+)#([^)]+)\)", adapter)
        self.assertIsNotNone(link)
        self.assertLess(link.start(), adapter.index("bash <plugin-root>/lib/python_runtime.sh"))
        target = (adapter_path.parent / link.group(1)).resolve()
        self.assertEqual(PACK / HOST_INTEGRATIONS["claude"], target)
        section = target.read_text(encoding="utf-8").split("### " + link.group(2) + "\n", 1)[1].split("\n### ", 1)[0]
        for field in ("claude plugin marketplace list --json", "https://github.com/Geoege-xll/agent-workflow.git",
                      "plugins-claude-stable", "claude plugin list --json", "xy-workflow@xy-workflow",
                      "installPath", "version", "--plugin-dir"):
            self.assertIn(field, section)

    def test_claude_denial_examples_resolve_to_their_actual_helper_contracts(self):
        # 只验证拒绝后的说明能链接到正确的命令与副作用合同；模型是否遵从
        # 用户决定和宿主权限，仍须以发生拒绝的真实会话为准。
        page = PACK / HOST_INTEGRATIONS["claude"]
        links = dict(re.findall(r"\[`([^`]+)`\]\(([^)]+)\)", page.read_text(encoding="utf-8")))
        for command, filename in (("dispatch-preferences", "dispatch.md"),
                                  ("task_graph_cli.py scratch", "runtime-records.md")):
            with self.subTest(command=command):
                relative, anchor = links[command].split("#")
                target = (page.parent / relative).resolve()
                self.assertEqual(PACK / "platforms/shared/skills/xy-workflow/references" / filename, target)
                body = target.read_text(encoding="utf-8")
                headings = [heading.casefold().replace(" ", "-") for heading in re.findall(r"(?m)^#+ (.+)$", body)]
                self.assertIn(anchor, headings)
                self.assertIn(command, body)

    def test_business_routes_must_reach_their_installed_authorities(self):
        routes = {
            "plugins/main-session-context.md": ("@BUSINESS_ADAPTER@", "skills/xy-config/SKILL.md", "skills/xy-workflow/SKILL.md"),
            "plugins/plugin-context.md": ("platforms/<host>/references/pm-integration.md",),
            "plugins/antigravity/plugin-context.md": (HOST_INTEGRATIONS["antigravity"],),
        }
        for relative, anchors in routes.items():
            path = PACK / relative
            body = read_instruction_contract(PACK, relative)
            self.assertEqual([], validate_execution_texts(((path, body),)))
            for anchor in anchors:
                with self.subTest(path=relative, anchor=anchor):
                    # 将真实入口指向诱饵；即使正确文件仍存于包中，此调用链也必须报错。
                    redirected = body.replace(anchor, "other-package/entry.md")
                    self.assertTrue(validate_execution_texts(((path, redirected),)))

    def test_each_host_checks_its_own_dispatch_and_nested_agent_boundary(self):
        guards = {
            "codex": ('fork_turns: "none"', "nested delegation disabled"),
            "claude": ("SendMessage", "never delegate"),
            "antigravity": ("invoke_subagent", "role Agents never delegate"),
        }
        for host, relative in HOST_INTEGRATIONS.items():
            path = PACK / relative
            body = read_instruction_contract(PACK, relative)
            self.assertEqual([], validate_execution_texts(((path, body),)))
            for anchor in (*guards[host], "instance_policy: fresh", "context_policy: handoff_only"):
                with self.subTest(host=host, anchor=anchor):
                    self.assertTrue(validate_execution_texts(((path, body.replace(anchor, "removed")),)))


if __name__ == "__main__":
    unittest.main()
