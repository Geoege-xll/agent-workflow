"""验证实际插件的主会话、业务资源与宿主调度入口之间的合同。"""

import unittest
from pathlib import Path

from lib.skills.business_confirmation_policy import (
    HOST_INTEGRATIONS, read_instruction_contract, validate_execution_texts,
)


PACK = Path(__file__).resolve().parents[1]


class PluginRoutingTest(unittest.TestCase):
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
