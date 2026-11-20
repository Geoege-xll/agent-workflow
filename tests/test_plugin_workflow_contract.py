"""验证插件实际加载内容和原helper的业务门禁，不另写简化工作流。"""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import tomllib
import unittest

from lib import task_graph_records as records
from lib.delivery import worktree_cli as delivery
from lib.skills import business_confirmation_policy as policy
from lib.skills.role_skills import CORE_SKILLS, ROLE_SKILLS
from lib.task_graph_cli import _execute, export_task_pack
from tests.test_foundation_qa import graph as qa_graph, working_root
from tests.test_plugin_delivery import PACK, builder, isolated_environment
from tests.test_qa_handoff import qa_task_pack
from tests.test_scheduler_boundaries import _writer_payload
from tests.test_task_graph_init import ADAPTER, BUILTIN_ENGINEERING, decisions
from tests.test_task_graph import _standards_payload


def visual_request(route: str, project: Path | None = None) -> tuple[dict, str]:
    """沿用原UI路由夹具的真实合同结构，验证已装配 helper 对需求与具体页面批准的处理。"""
    from tests.test_scheduler_boundaries import write_visual_page
    page_sha = write_visual_page(project) if project is not None else "b" * 64
    requirements_sha = "a" * 64
    gate = "visual_approved:settings@" + page_sha
    writer = {
        "id": "web", "request_id": "req-design", "task_type": "writer", "role": "xy-web",
        "surface_kind": "production_ui", "qa_scope": "request", "depends_on": ["prototype"],
        "blocks": [], "gates": ["requirements_approved", gate], "owned_paths": ["apps/web/settings/"],
        "semantic_locks": [], "state": "DECLARED", "audit_surfaces": ["ui", "accessibility", "engineering-conformance"],
        "ui_change": {
            "route": route, "design_delta": "changed", "prototype_policy": "required",
            "prototype_decision": {
                "source": "requirements_confirmation_user_choice", "choice_ref": "user:req-design/use-prototype",
                "requirement_fingerprint": requirements_sha, "affected_surfaces": ["settings-page"],
                "recommended_policy": "required", "recommendation_reason": "页面交互变化需要先核对原型",
                "selected_policy": "required",
            },
            "design_authority_refs": [{"kind": "prototype_contract", "authority_id": "settings",
                "path": "docs/standards/prototype/settings.html", "anchor": "page-design-and-interaction-contract",
                "content_fingerprint": page_sha, "resolution_state": "resolved"}],
            "affected_surfaces": ["settings-page"], "justification": "实现用户选择的设置页设计变更",
        },
        "controlled_document_access": {"adapter": "project.yaml", "documents": [{
            "path": "docs/ENGINEERING.md", "mode": "full", "reason": "读取适用工程规范",
            "sections_or_queries": [], "content_fingerprint": "e" * 64,
            "applies_to": ["apps/web/settings/"], "rule_ids": ["eng-baseline"],
        }]},
    }
    prototype = {
        "id": "prototype", "request_id": "req-design", "task_type": "writer", "role": "xy-uiux",
        "surface_kind": "design_ui", "qa_scope": "request", "depends_on": [], "blocks": ["web"],
        "gates": ["requirements_approved"], "owned_paths": ["docs/standards/prototype/settings.html"],
        "semantic_locks": [], "state": "BUILD_VERIFIED", "audit_surfaces": ["ui", "accessibility"],
    }
    return _standards_payload({
        "tasks": [prototype, writer], "ui_contract": {"prototype_paths": ["docs/standards/prototype/"]},
        "engineering_contract": {"path": "docs/ENGINEERING.md", "content_fingerprint": "e" * 64,
                                 "required_rule_ids": ["eng-baseline"], "protected_paths": []},
        "requirements_fingerprint": requirements_sha, "approved_gates": ["requirements_approved"],
        "active_paths": [], "active_semantic_locks": [], "capacity": 1,
    }), gate


class PluginWorkflowContractTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory(prefix="awf-plugin-contract-")
        cls.root = Path(cls.temporary.name).resolve()
        cls.installed = {}
        for host in builder.HOSTS:
            archive = builder.build(PACK, cls.root / "archives", host)
            target = cls.root / host
            target.mkdir()
            # 复用本地分发的安全解包，保留原版 CLI 与 helper 的执行位供安装完整性检查。
            builder.unpack_archive(archive, target)
            cls.installed[host] = target

    @classmethod
    def tearDownClass(cls):
        cls.temporary.cleanup()

    def helper(self, host, project, command, *args, env=None, input=None):
        return subprocess.run([sys.executable, "-B", str(self.installed[host] / "plugins/source_pack.py"),
                               "helper", "--project", str(project), "lib/task_graph_cli.py", command, *map(str, args)],
                              cwd=project, env=env or isolated_environment(self.root / "home"),
                              input=input, capture_output=True, text=True, timeout=15)

    def test_loaded_skills_retain_complete_frontmatter_body_and_references(self):
        for host, root in self.installed.items():
            with self.subTest(host=host):
                # 宿主适配路径由测试独立明确，不能读取生成器选择结果再自我验证。
                # AGY 只精简资源说明；所有共享正文与引用仍必须逐字节完整交付。
                adapter_source = ("plugins/antigravity/plugin-context.md" if host == "antigravity"
                                  else "plugins/plugin-context.md")
                envelope = (PACK / adapter_source).read_bytes()
                metadata = json.loads((root / "sources.json").read_bytes())
                self.assertEqual(envelope, (root / adapter_source).read_bytes())
                self.assertEqual(hashlib.sha256(envelope).hexdigest(), metadata["source_files"][adapter_source])
                for skill in CORE_SKILLS:
                    original = PACK / "platforms/shared/skills" / skill / "SKILL.md"
                    header, body = builder.split_frontmatter(original.read_bytes())
                    loaded = (root / "skills" / skill / "SKILL.md").read_bytes()
                    loaded_header, loaded_body = builder.split_frontmatter(loaded)
                    self.assertEqual(header, loaded_header)
                    self.assertTrue(loaded_body.endswith(body))
                    # 从实包入口解析相对链接，独立启动也须到达该宿主的完整说明。
                    # 同一实例可复用当前来源版本；独立、缺失或变更时须能按链接补读。
                    locator = loaded_body[:-len(body)]
                    link = re.search(rb"\]\(([^)]+plugin-context\.md)\)", locator)
                    self.assertIsNotNone(link)
                    target = (root / "skills" / skill / link.group(1).decode()).resolve()
                    self.assertEqual(root / adapter_source, target)
                    self.assertLess(len(locator), len(envelope))
                    for boundary in ("当前实例", "同一物理来源", "同一版本", "完整说明", "独立启动", "重新读取"):
                        self.assertIn(boundary.encode(), locator)
                    # 新 PM 必须先等来源说明成功，再决定当前阶段要读哪一节。
                    # 从实际包检查首批唯一目标；其它 Worker 的定位不继承 PM 首轮指令。
                    serial_read = "第一批只读取下方链接的宿主资源说明".encode()
                    if skill == "xy-workflow":
                        self.assertEqual([link.group(1)], re.findall(rb"\]\(([^)]+)\)", locator))
                        self.assertLess(locator.index(serial_read), locator.index("等它成功返回后".encode()))
                        self.assertIn("不要把产品全文、阶段引用或项目文件并入这次读取".encode(), locator)
                        # 仅原型首轮遇到的是范围确认；不在这个分支摆放待批的下游文件链接。
                        # 同时检查后续设计链接和 Full 必读的覆盖原版，防止直接删规则来通过负控。
                        route = body.decode().split("**只做原型**", 1)[1].split("**已委托开发**", 1)[0]
                        self.assertNotIn("](references/", route)
                        self.assertIn("已有有效确认则直接复用", route)
                        self.assertIn("到设计交接时再读", route)
                        self.assertIn(b"](references/ui-design.md)", body)
                        self.assertIn("完整读取[需求接单](references/requirements-intake.md)及选中的 `grilling` 原版".encode(), body)
                    else:
                        self.assertNotIn(serial_read, locator)
                    self.assertEqual(adapter_source,
                                     metadata["projections"][f"skills/{skill}/SKILL.md"]["adapter"])
                    for reference in original.parent.rglob("*"):
                        if reference.is_file() and reference != original:
                            self.assertEqual(reference.read_bytes(),
                                             (root / "skills" / skill / reference.relative_to(original.parent)).read_bytes())
                self.assertEqual([], policy.validate_business_confirmation_pack(root, host))

    def test_selected_skill_consumers_preserve_native_workflow_boundaries(self):
        """消费已构建三端的真实接入文字，锁定自动/显式入口与默认原型权限边界。"""
        for host, root in self.installed.items():
            with self.subTest(host=host):
                # 从实际发现入口解析随包分发的分支，确认 Full 的上游选择可达。
                workflow = policy.read_instruction_contract(root, "skills/xy-workflow/SKILL.md")
                intake = (root / "skills/xy-workflow/references/requirements-intake.md").read_text(encoding="utf-8")
                design = (root / "skills/xy-ui-design/SKILL.md").read_text(encoding="utf-8")
                adapter = (root / "skills/xy-taste/SKILL.md").read_text(encoding="utf-8")
                original = root / "third_party/selected-skills/taste/skills/taste-skill/SKILL.md"
                self.assertIn("requirements_provider: xy-grilling", workflow)
                self.assertIn("`grill-me` 是上游用户显式入口", intake)
                self.assertIn("不是上游 Grill Me 的 schema", intake)
                self.assertIn("同一已验证插件", intake)
                # 分页合同只存在于真实包的共享规则。先验整包或重新把 Taste 写成固定依赖，
                # 会让沿用现有设计系统的局部任务被无关资源阻断。
                selection_path = "platforms/shared/skills/xy-workflow/references/skill-selection.md"
                selection = (root / selection_path).read_text(encoding="utf-8")
                taste_policy = selection.split("## Taste design guidance", 1)[1].split("\n## ", 1)[0]
                for boundary in ("next_offset", "eof", "sha256", "total_bytes",
                                 "selected-skills read xy-taste", str(original.relative_to(root))):
                    self.assertIn(boundary, taste_policy)
                self.assertNotRegex(taste_policy, r"(?m)^bash .*selected-skills check\b")
                self.assertIn(selection_path + "#taste-design-guidance", adapter)
                self.assertNotIn("selected-skills read", adapter)
                self.assertNotIn(b"hooks:", builder.split_frontmatter(adapter.encode())[0])
                self.assertGreater(len(builder.split_frontmatter(original.read_bytes())[1]), 24000)
                # 原版仍在非发现目录，默认原型必须保留静态验收和截图禁令。
                self.assertIn("Do not automate prototype browser operations by", design)
                self.assertIn("Do not generate, save, attach, or present screenshots", " ".join(design.split()))
                self.assertNotIn("ui-ux-pro-max", workflow + intake + design)
                for path in ("roles/xy-uiux.md", "product/AGENT_SCHEMA.md", "product/ROLES.yaml",
                             "product/WORKFLOW.md", "skills/xy-workflow/references/ui-design.md"):
                    self.assertNotIn("xy-taste", (root / path).read_text(encoding="utf-8"))
                self.assertNotIn("xy-taste", (root / "platforms/shared/skills/xy-ui-design/SKILL.md").read_text(encoding="utf-8"))

    def test_all_roles_resolve_one_shared_skill_selection_authority(self):
        """沿三端已装配 WORKFLOW 的真实链接读取权威，防止只有实现角色能消费新规则。"""
        relative = "platforms/shared/skills/xy-workflow/references/skill-selection.md"
        expected = (PACK / relative).read_bytes()
        for host, root in self.installed.items():
            project = self.root / ("skill-selection-project-" + host)
            project.mkdir()
            # 项目同名内容故意冲突；真实 resource/pager 必须读取当前物理插件，
            # 不能仅靠复制字符串的断言掩盖清单漏收或项目同名文件覆盖权威的问题。
            decoy = project / relative
            decoy.parent.mkdir(parents=True)
            decoy.write_text("project-owned skill-selection decoy", encoding="utf-8")
            with self.subTest(host=host):
                workflow = root / "product/WORKFLOW.md"
                links = re.findall(r"\]\(([^)]+skill-selection\.md)\)", workflow.read_text(encoding="utf-8"))
                self.assertTrue(links, "WORKFLOW must route every Agent to the shared policy")
                self.assertEqual({root / relative}, {(workflow.parent / link).resolve() for link in links})
                # 按阶段读的冷启动 PM 不一定已经打开产品手册。直接从发现入口正文
                # 跟随“即将选 Skill”的条件链接，读取同一权威；同名项目诱饵不能生效。
                entry = root / "skills/xy-workflow/SKILL.md"
                prefix, core = entry.read_text(encoding="utf-8").split("<!-- agent-workflow-pack:managed-skill -->", 1)
                position = core.index("**选用其他 Skill 时。**")
                selection = core[position:core.index("## Standalone read-only audit", position)]
                link = re.search(r"\]\((references/skill-selection\.md)\)", selection)
                self.assertIsNotNone(link)
                self.assertEqual(expected, (entry.parent / link.group(1)).read_bytes())
                self.assertIn("仅当下一步确实要选择或使用 Skill", selection[:link.start()])
                self.assertLess(position, core.index("**Full 需求与计划。**"))
                # 负控保证首批资源说明、普通讨论和原型范围确认没有直接预载此规则；
                # 独立审查、Full 规划和后续角色需要它时仍从上方共用入口到达。
                self.assertNotIn("skill-selection.md", prefix + core[:position])
                self.assertIn("恢复上下文本身均不触发读取", selection)
                base = [sys.executable, "-B", str(root / "plugins/source_pack.py")]
                located = subprocess.run([*base, "resource", relative], cwd=project,
                    env=isolated_environment(self.root / "home"), capture_output=True, text=True, timeout=15)
                self.assertEqual(0, located.returncode, located.stdout + located.stderr)
                resource = json.loads(located.stdout)
                self.assertEqual(root / relative, Path(resource["path"]))
                self.assertEqual(hashlib.sha256(expected).hexdigest(), resource["sha256"])
                loaded = subprocess.run(
                    [*base, "helper", "--project", str(project), "lib/documents/context_read.py",
                     relative, "--root", str(project), "--limit", "24000"],
                    cwd=project, env=isolated_environment(self.root / "home"),
                    capture_output=True, text=True, timeout=15)
                self.assertEqual(0, loaded.returncode, loaded.stdout + loaded.stderr)
                page = json.loads(loaded.stdout)
                self.assertTrue(page["eof"])
                self.assertEqual(expected.decode("utf-8"), page["text"])
                # 按需入口可由宿主发现；原生角色和 PM 的固定预载不得在任务选择前引入。
                # 消费包内真实角色CLI与宿主frontmatter，避免只检查源码绑定常量。
                candidates = ("xy-web-guidance", "xy-apple-guidance", "xy-taste", "agent-desktop",
                              "xy-playwright", "xy-prototype-verify")
                for candidate in candidates:
                    header, _ = builder.split_frontmatter((root / "skills" / candidate / "SKILL.md").read_bytes())
                    self.assertIn(("name: " + candidate).encode(), header)
                for role in ROLE_SKILLS:
                    selected = subprocess.run(
                        [sys.executable, "-B", str(root / "lib/skills/role_skills.py"), role],
                        cwd=project, env=isolated_environment(self.root / "home"),
                        capture_output=True, text=True, timeout=15)
                    self.assertEqual(0, selected.returncode, selected.stdout + selected.stderr)
                    self.assertTrue(set(candidates).isdisjoint(selected.stdout.splitlines()))
                # 共用包络让设计与 QA 同样到达 WORKFLOW；计划 Skill 也走相同入口。
                # 验证真实投影而非为七角色复制七份细则或强制预载全部 Skill。
                envelope = "plugins/antigravity/plugin-context.md" if host == "antigravity" else "plugins/plugin-context.md"
                envelope_body = (root / envelope).read_bytes()
                self.assertIn(b"product/WORKFLOW.md", envelope_body)
                self.assertIn(("../../" + envelope).encode(), (root / "skills/xy-plan/SKILL.md").read_bytes())
                if host != "codex":
                    for role in ROLE_SKILLS:
                        self.assertIn(envelope_body, (root / "agents" / (role + ".md")).read_bytes())
                        header, _ = builder.split_frontmatter((root / "agents" / (role + ".md")).read_bytes())
                        for candidate in candidates:
                            self.assertNotIn(candidate.encode(), header)
                    if host == "claude":
                        header, _ = builder.split_frontmatter((root / "agents/pm.md").read_bytes())
                        for candidate in candidates:
                            self.assertNotIn(candidate.encode(), header)
                else:
                    self.assertIn(relative, (root / "platforms/codex/WORKER_CONSTRAINTS.md").read_text(encoding="utf-8"))
                # 桌面实现与独立 QA 应从同一物理包取到同一节规则。没有 GUI 权限时，
                # 此合同只能验证路由，真实交互与权限拒绝由对应运行证据验证。
                for role in ("xy-desktop", "xy-qa"):
                    role_path = root / "roles" / (role + ".md")
                    link = re.search(r"\]\(([^)#]+skill-selection\.md)#desktop-verification\)",
                                     role_path.read_text(encoding="utf-8"))
                    self.assertIsNotNone(link)
                    self.assertEqual(root / relative, (role_path.parent / link.group(1)).resolve())
                self.assertIn(b"## Desktop verification", expected)

    def test_web_browser_policy_uses_bundled_cli_without_widening_qa(self):
        """检查真实三端包的公开绑定和权限边界，避免原Skill安装段扩权或全体QA预载。"""
        for host, root in self.installed.items():
            with self.subTest(host=host):
                policy_path = "skills/xy-build-verify/references/web-browser-verification.md"
                browser_policy = (root / policy_path).read_text(encoding="utf-8")
                for boundary in ("项目已有", "xy-playwright", "具体能力", "桌面能力", "只读权限",
                                 "本任务命名会话", "snapshot", "非上游原生命令", "-- doctor"):
                    self.assertIn(boundary, browser_policy)
                self.assertIn("不因本政策自动启动浏览器或生成截图", browser_policy)
                adapter = (root / "skills/xy-playwright/SKILL.md").read_bytes()
                header, _ = builder.split_frontmatter(adapter)
                self.assertIn(b"name: xy-playwright", header)
                self.assertNotIn(b"allowed-tools:", header)
                self.assertNotIn(b"hooks:", header)
                canonical = root / ("third_party/selected-skills/playwright-cli/runtime/node_modules/"
                                    "@playwright/cli/skills/playwright-cli/SKILL.md")
                original_header, _ = builder.split_frontmatter(canonical.read_bytes())
                self.assertIn(b"name: playwright-cli", original_header)
                self.assertIn(b"allowed-tools:", original_header)
                # 从各宿主真正派发的角色提示词验证四种任务。仅取消预载却丢失交付时
                # 的触发规则，会让浏览器取证和具体原型的静态验收同时失去入口。
                role_text = {}
                for role in ("xy-web", "xy-uiux"):
                    if host == "codex":
                        template = root / "native-agent-templates/codex" / (role + ".toml")
                        prompt = tomllib.loads(template.read_text(encoding="utf-8"))["developer_instructions"]
                    else:
                        prompt = (root / "agents" / (role + ".md")).read_text(encoding="utf-8")
                    role_text[role] = " ".join(prompt.split())
                self.assertIn("reuse project tests first, then fully read the bundled `$xy-playwright`", role_text["xy-web"])
                self.assertIn("纯小程序逻辑无需加载 `xy-playwright`", role_text["xy-web"])
                self.assertIn("Do not load or invoke `xy-prototype-verify`", role_text["xy-uiux"])
                self.assertIn("Invoke `$xy-prototype-verify` to validate static path readiness", role_text["xy-uiux"])
                # 原版桌面 Skill 是唯一直接发现的上游入口，其余精选 Skill 继续使用项目薄入口。
                discovered = {path.parent.name for path in (root / "skills").glob("*/SKILL.md")}
                self.assertTrue({"xy-config", "xy-grill-me", "xy-grilling", "xy-taste", "xy-playwright",
                                 "agent-desktop"} <= discovered)
                self.assertEqual({"agent-desktop"}, {name for name in discovered if not name.startswith("xy-")})
                self.assertNotIn("xy-agent-desktop", discovered)

    def test_native_role_prompts_keep_full_original_body_and_no_history_fork(self):
        for host, root in self.installed.items():
            with self.subTest(host=host):
                metadata = json.loads((root / "sources.json").read_bytes())
                adapter_source = ("plugins/antigravity/plugin-context.md" if host == "antigravity"
                                  else "plugins/plugin-context.md")
                envelope = (PACK / adapter_source).read_bytes()
                for role in ROLE_SKILLS:
                    original = (PACK / "roles" / (role + ".md")).read_bytes()
                    self.assertEqual(original, (root / "roles" / (role + ".md")).read_bytes())
                    if host != "codex":
                        _, body = builder.split_frontmatter(original)
                        native = (root / "agents" / (role + ".md")).read_bytes()
                        self.assertTrue(native.endswith(body))
                        header, native_body = builder.split_frontmatter(native)
                        self.assertEqual(b"\n" + envelope + b"\n" + body, native_body)
                        self.assertEqual(adapter_source,
                                         metadata["projections"][f"agents/{role}.md"]["adapter"])
                        if host == "claude":
                            self.assertIn(b", Skill", header)
                            self.assertNotIn(b", Agent", header)
                            self.assertNotIn(b"model:", header)
                            self.assertNotIn(b"effort:", header)
                        else:
                            self.assertIn(b"model: inherit", header)
                            self.assertNotIn(b"  - invoke_subagent", header)
                            if role == "xy-qa":
                                self.assertIn(b"  - run_command", header)
                                self.assertNotIn(b"  - write_to_file", header)
                        self.assertIn(b"context_policy: handoff_only", native)
                        self.assertIn(b"instance_policy: fresh", native)
                        # 两种宿主说明表达同一不可继承历史的强约束；不能删掉负控
                        # 或只保留 fresh 标签，从而放任父会话/兄弟代理历史进入任务包。
                        if host == "antigravity":
                            self.assertIn("不得继承 PM 或其他代理历史".encode("utf-8"), native)
                        else:
                            self.assertIn(b"never fork PM or", native)
                self.assertFalse(metadata["runtime_verified"])

    def test_loaded_confirmation_policy_rejects_unrelated_mandatory_approvals(self):
        root = self.installed["codex"]
        # 校验器看到的正文必须从实际发现入口展开。只读 SKILL.md 会漏掉
        # 阶段引用中的额外确认；独立验证从产品权威及当前安装路径取证。
        relative = "skills/xy-workflow/SKILL.md"
        full_contract = policy.read_instruction_contract(root, relative)
        actual = [(Path("product/WORKFLOW.md"), (root / "product/WORKFLOW.md").read_text(encoding="utf-8")),
                  (Path(relative), full_contract)]
        self.assertEqual([], policy.validate_business_confirmation_texts(actual))
        invalid = [*actual, (Path("plugin-envelope.md"), "PM must obtain build approval before implementation.")]
        self.assertTrue(policy.validate_business_confirmation_texts(invalid))
        # 适配文字没有自动批准、跳过Full或另设Reviewer；真正业务规则来自唯一原文。
        source = (root / "product/WORKFLOW.md").read_text(encoding="utf-8")
        self.assertEqual(1, source.count(policy.DEFAULT_POLICY))
        self.assertIn("requirements_approved", source)
        self.assertIn("solution_approved", source)
        self.assertIn("visual_approved", source)
        self.assertIn("max_active_reviewers: 1", source)
        light = (root / "skills/xy-workflow/SKILL.md").read_text(encoding="utf-8")
        # 已有授权须在入口直接可见；再沿真实安装入口核对 Light 单包与适用确认。
        self.assertIn("已有明确范围授权直接执行", light)
        self.assertIn("Explicit user scope authority permits direct dispatch", full_contract)

    def test_detached_real_helper_preserves_requirement_gate_and_fresh_context(self):
        project = self.root / "gate-project"
        project.mkdir()
        value = _writer_payload()
        value["approved_gates"] = []
        target = project / "current.json"
        for host in builder.HOSTS:
            with self.subTest(host=host):
                target.write_text(json.dumps(value), encoding="utf-8")
                result = self.helper(host, project, "ready", "--input", target)
                self.assertEqual(0, result.returncode, result.stderr)
                self.assertEqual([], json.loads(result.stdout)["ready"])
                approved = copy.deepcopy(value)
                approved["approved_gates"] = ["requirements_approved"]
                target.write_text(json.dumps(approved), encoding="utf-8")
                result = self.helper(host, project, "ready", "--input", target)
                self.assertEqual(0, result.returncode, result.stderr)
                self.assertEqual(["backend"], json.loads(result.stdout)["ready"])
                for field, wrong in (("instance_policy", "reuse"), ("context_policy", "full_history")):
                    invalid = copy.deepcopy(approved)
                    invalid["tasks"][0][field] = wrong
                    target.write_text(json.dumps(invalid), encoding="utf-8")
                    rejected = self.helper(host, project, "validate", "--input", target)
                    self.assertEqual(2, rejected.returncode, rejected.stdout)
        self.assertFalse((project / ".agent-workflow").exists())
        self.assertFalse((project / "AGENTS.md").exists())
        self.assertFalse((project / "CLAUDE.md").exists())

    def test_solution_approval_unlocks_dependent_design_and_api_only(self):
        """同一待决行为影响原型和接口，走安装包的 init、显式批准与 ready。"""
        design_rules = "platforms/shared/skills/xy-ui-design/references/foundations-rules.md"
        solution = {"id": "retry-policy", "content": "设置保存失败后保留输入，由用户手动重试"}
        proposal = decisions()
        proposal.update(request_id="req-settings", capacity=3, approved_gates=["requirements_approved"],
                        requirements_fingerprint="a" * 64)
        proposal["standards"].update(required_engineering_rule_ids=["eng-common-005"],
                                     required_design_rule_ids=["des-baseline-001"])
        proposal["standards"]["leaves"] = [
            {"path": BUILTIN_ENGINEERING, "domain": "engineering", "rule_ids": ["eng-common-005"]},
            {"path": design_rules, "domain": "design", "rule_ids": ["des-baseline-001"]},
        ]
        api = proposal["tasks"][0]
        api["selected_standards"] = [BUILTIN_ENGINEERING]
        independent = {**api, "id": "report", "agent_alias": "fixture-report",
                       "owned_paths": ["src/report.py"], "goal": "验证独立报表接口"}
        api["solution_decisions"] = [solution]
        prototype = {**api, "id": "prototype", "role": "xy-uiux", "agent_alias": "fixture-prototype",
                     "surface_kind": "design_ui", "design_mode": "prototype", "goal": "设计设置页失败恢复状态",
                     "owned_paths": ["docs/standards/prototype/settings.html"], "selected_standards": [design_rules],
                     "audit_surfaces": ["ui", "accessibility", "standards-conformance"]}
        proposal["tasks"].extend([independent, prototype])
        for host in self.installed:
            with self.subTest(host=host):
                project = self.root / ("solution-" + host)
                project.mkdir()
                (project / "project.yaml").write_text(ADAPTER, encoding="utf-8")
                target = project / "graph.json"
                initialized = self.helper(host, project, "init", "--root", project, "--output", target,
                                          input=json.dumps(proposal, ensure_ascii=False))
                self.assertEqual(0, initialized.returncode, initialized.stderr)
                before = self.helper(host, project, "ready", "--input", target)
                self.assertEqual(0, before.returncode, before.stderr)
                self.assertEqual(["report"], json.loads(before.stdout)["ready"])

                # PM 从用户取得这项行为决定后才登记；相同请求和正文只需登记一次。
                # 两个任务都依赖同一行为，但其余工作在登记之前也能派发。
                update = {"approve_solutions": [{"request_id": "req-settings", "task_id": "api", **solution}]}
                recorded = self.helper(host, project, "update", "--input", target, "--patch", "-",
                                       "--expect-sha256", json.loads(initialized.stdout)["sha256"],
                                       input=json.dumps(update, ensure_ascii=False))
                self.assertEqual(0, recorded.returncode, recorded.stderr)
                after = self.helper(host, project, "ready", "--input", target)
                self.assertEqual(0, after.returncode, after.stderr)
                self.assertCountEqual(["api", "prototype", "report"], json.loads(after.stdout)["ready"])

    def test_detached_init_uses_plugin_builtins_without_copying_them_into_project(self):
        # 复用原task_graph_init决定夹具，仅选择真实内置工程底线；项目不复制Skills。
        for host in builder.HOSTS:
            project = self.root / ("init-project-" + host)
            project.mkdir()
            (project / "project.yaml").write_text(ADAPTER, encoding="utf-8")
            value = decisions()
            value["standards"]["leaves"] = value["standards"]["leaves"][:1]
            value["standards"]["required_engineering_rule_ids"] = ["eng-common-005"]
            value["tasks"][0]["selected_standards"] = [BUILTIN_ENGINEERING]
            decision = project / "decisions.json"
            decision.write_text(json.dumps(value), encoding="utf-8")
            target = project / "graph.json"
            with self.subTest(host=host):
                result = self.helper(host, project, "init", "--root", project, "--input", decision, "--output", target)
                self.assertEqual(0, result.returncode, result.stderr)
                graph = json.loads(target.read_bytes())
                self.assertEqual([], graph["approved_gates"])
                self.assertNotIn("runtime_binding", graph)
                self.assertIsNone(graph["standards_contract"]["index_fingerprint"])
                self.assertEqual(0, self.helper(host, project, "validate", "--input", target).returncode)
                waiting = self.helper(host, project, "ready", "--input", target)
                self.assertEqual([], json.loads(waiting.stdout)["ready"])
                self.assertFalse((project / "platforms").exists())
                self.assertFalse((project / ".agent-workflow").exists())
                self.assertFalse((project / "docs").exists())

    def test_packaged_qa_specialist_example_passes_the_actual_task_schema(self):
        """三个已装配权威的真实示例均经过原init/validate，防止非法容器回归。"""
        examples = (
            ("qa-inputs", "skills/xy-qa-review/references/inputs.md",
             "- the task's specialist policy fields, directly inside `task`:"),
            ("workflow", "product/WORKFLOW.md",
             "Every Full task pack and applicable Light task pack also includes these fields directly inside `task`:"),
            ("dispatch", "skills/xy-workflow/references/dispatch.md",
             "The following `non_ui` example shows the direct members of `task`:"),
        )
        for host, root in self.installed.items():
            for name, relative, marker in examples:
                with self.subTest(host=host, example=name):
                    text = (root / relative).read_text(encoding="utf-8")
                    # 示例使用JSON这一可独立解析的YAML子集；测试不另造一份同名
                    # 常量，更不只断言文案中包含字段名，而是消费包内原始示例。
                    example = text.split(marker, 1)[1].split("```json", 1)[1].split("```", 1)[0]
                    members = json.loads(example)
                    # qa_scope是原init生成的派发成员，不是精简决定输入。其余
                    # 示例成员全部原样交init；再把qa_scope交真实运行时validate，
                    # 不过滤未知字段，保证skill_policy回归时会被原schema拒绝。
                    initialization = copy.deepcopy(members)
                    runtime_only = {field: initialization.pop(field) for field in ("qa_scope",)
                                    if field in initialization}
                    project = self.root / ("qa-specialist-example-" + host + "-" + name)
                    project.mkdir()
                    (project / "project.yaml").write_text(ADAPTER, encoding="utf-8")
                    value = decisions()
                    value["standards"]["leaves"] = value["standards"]["leaves"][:1]
                    value["standards"]["required_engineering_rule_ids"] = ["eng-common-005"]
                    value["tasks"][0]["selected_standards"] = [BUILTIN_ENGINEERING]
                    value["tasks"][0].update(initialization)
                    decision = project / "decisions.json"
                    decision.write_text(json.dumps(value), encoding="utf-8")
                    target = project / "graph.json"
                    accepted = self.helper(host, project, "init", "--root", project,
                                           "--input", decision, "--output", target)
                    self.assertEqual(0, accepted.returncode, accepted.stdout + accepted.stderr)
                    graph = json.loads(target.read_bytes())
                    graph["tasks"][0].update(runtime_only)
                    target.write_text(json.dumps(graph), encoding="utf-8")
                    self.assertEqual(0, self.helper(host, project, "validate", "--input", target).returncode)
                    # 回归真实验收中被拒绝的旧嵌套形态：它必须仍被原schema拒绝，
                    # 修复只改变示例，不把非法容器放进业务合同或放宽现有门禁。
                    invalid = copy.deepcopy(value)
                    specialist = {field: members[field] for field in ("required_skills", "audit_surfaces")}
                    for field in specialist:
                        invalid["tasks"][0].pop(field)
                    invalid["tasks"][0]["skill_policy"] = specialist
                    decision.write_text(json.dumps(invalid), encoding="utf-8")
                    rejected = self.helper(host, project, "init", "--root", project,
                                           "--input", decision, "--output", project / "invalid.json")
                    self.assertEqual(2, rejected.returncode)
                    self.assertIn("unsupported field(s): skill_policy", rejected.stderr)
                    self.assertFalse((project / "invalid.json").exists())

    def test_packaged_qa_source_evidence_reads_the_located_lines(self):
        """从 Reviewer 导航进入源码取证分支，用包内 helper 定位并回读同版条目。"""
        for host, root in self.installed.items():
            with self.subTest(host=host):
                entry = root / "skills/xy-qa-review/SKILL.md"
                link = re.search(r"\[源码取证示例\]\(([^)#]+)#(.*?)\)", entry.read_text())
                self.assertIsNotNone(link)
                reference = (entry.parent / link[1]).read_text()
                self.assertIn("## " + link[2], reference)
                project = self.root / ("source-review-" + host)
                project.mkdir()
                source = project / "requests.py"
                source.write_text("# 同文件的其它内容\ndef accept():\n    return 1\n", encoding="utf-8")
                cli = ["bash", str(root / "lib/python_runtime.sh"), "-B", "-X", "utf8",
                       str(root / "plugins/source_pack.py"), "helper", "--project", str(project),
                       "lib/documents/context_read.py", str(source)]
                execution = {"cwd": project, "env": isolated_environment(self.root / "home"),
                             "capture_output": True, "text": True, "timeout": 15}
                found = subprocess.run([*cli, "--find", "def accept", "--max-matches", "1", "--limit", "16"],
                                       **execution)
                self.assertEqual(0, found.returncode, found.stderr)
                location = json.loads(found.stdout)
                line = location["matches"][0]["line"]
                # 行号和摘要都取自首次真实输出；查找与回读间删除、改写文件时，
                # 上游必须保留缺口。成功时单次输出只包含选中行，且有原文件定位。
                excerpt = subprocess.run([*cli, "--lines", f"{line}:{line}", "--limit", "16",
                                          "--expect-sha256", location["sha256"]], **execution)
                self.assertEqual(0, excerpt.returncode, excerpt.stderr)
                result = json.loads(excerpt.stdout)
                self.assertEqual(str(source), result["path"])
                self.assertEqual("def accept():\n", result["text"])
                self.assertTrue(result["eof"])

    def test_packaged_qa_compare_target_reads_the_original_frozen_scope(self):
        """三端从实际规则找到同一命令，在临时 Git 仓库区分请求差异与同文件的其它变更。"""
        project = self.root / "target-project"
        project.mkdir()
        with working_root(project):
            # 普通 Full 走真实 freeze / task 导出。测试数据与插件包都在仓库外，
            # 因此未跟踪诊断能否匹配只取决于业务文件，不会读到测试自己的输入输出。
            source = qa_graph(project)
            source["tasks"][2].pop("foundation_task_id")
            source["tasks"][1]["state"] = "BUILD_VERIFIED"
            relative = "src/feature.py"
            feature = project / relative
            baseline = "request = 0\n" + "# context\n" * 12 + "unrelated = 0\n"
            feature.write_text(baseline, encoding="utf-8")
            delivery.git(project, "init", "-b", "main")
            delivery.git(project, "config", "user.name", "QA scope fixture")
            delivery.git(project, "config", "user.email", "qa@example.invalid")
            delivery.git(project, "add", ".")
            delivery.git(project, "commit", "-m", "fixture baseline")
            base = delivery.head(project)
            requested = baseline.replace("request = 0", "request = 1")
            feature.write_text(requested, encoding="utf-8")
            delivery.git(project, "add", relative)
            delivery.git(project, "commit", "-m", "fixture request only")
            head = delivery.head(project)
            fixed = delivery.scope(project, base, head)

            def task_pack(host, frozen):
                """使用现有调度操作绑定该宿主的原 Reviewer 和实际项目内容。"""
                graph = records.update(source, {"tasks": {"qa": {
                    "freeze_qa_scope": {"repositories": [frozen]},
                }}}, project, _execute)
                graph = records.update(graph, {"tasks": {"qa": {"set": {"state": "QA"}}}}, project, _execute)
                binding = {"agent_ref": {"host": host, "agent_id": "scope-fixture"}}
                graph = records.update(graph, {"tasks": {"qa": {"set": binding}}}, project, _execute)
                return export_task_pack(graph, "qa", root=project)

            # 先验证干净提交，再构造同一文件两处改动。按已知归属独立生成请求补丁，
            # 工作区另有一处变更，即使路径和 base/head 都相同，也必须区分差异内容。
            for kind in ("commit-range", "uncommitted"):
                if kind == "uncommitted":
                    requested = requested.replace("request = 1", "request = 2")
                    feature.write_text(requested, encoding="utf-8")
                    patch = delivery.git(project, "diff", "--binary", "--full-index", "--no-renames",
                                         "--no-ext-diff", "--no-textconv", head, "--")
                    fixed = dict(fixed, base_revision=head, diff_fingerprint=hashlib.sha256(patch).hexdigest())
                    feature.write_text(requested.replace("unrelated = 0", "unrelated = 1"), encoding="utf-8")
                for host, root in self.installed.items():
                    with self.subTest(host=host, candidate=kind):
                        # 从三种正常入口检查导航。PM/Reviewer 发现目录和宿主规范目录各有
                        # 自己的相对位置，但必须指向同版规则，再原样执行文档中的 helper。
                        inputs = root / "skills/xy-qa-review/references/inputs.md"
                        for entry in (root / "skills/xy-qa-review/SKILL.md",
                                      root / "skills/xy-workflow/references/implementation-and-qa.md",
                                      root / f"platforms/{host}/references/pm-integration.md"):
                            link = re.search(r"\[核对原生审查目标\]\(([^)#]+)#核对原生审查目标\)",
                                             entry.read_text(encoding="utf-8"))
                            self.assertIsNotNone(link, entry)
                            self.assertEqual(inputs.read_bytes(), (entry.parent / link[1]).read_bytes())
                        section = inputs.read_text(encoding="utf-8").split("### 核对原生审查目标\n", 1)[1]
                        example = re.search(r"```sh\n(.*?)\n```", section, re.DOTALL)[1]
                        candidate = (json.loads(section.split("```json\n", 1)[1].split("```", 1)[0])
                                     if kind == "commit-range" else
                                     json.loads(re.search(r"`(\{\"kind\":\"uncommitted\".*?\})`", section)[1]))
                        if kind == "commit-range":
                            candidate.update(base_revision=base, head_revision=head)
                        candidate_path = self.root / "target.json"
                        candidate_path.write_text(json.dumps(candidate), encoding="utf-8")
                        pack_path = self.root / "target-pack.json"
                        pack_path.write_text(json.dumps(task_pack(host, fixed)), encoding="utf-8")
                        env = isolated_environment(self.root / "home")
                        # 用户全局配置可能注册 Git LFS 或文件监控；用空的临时 Git 配置，
                        # 才能把负例明确归因于补丁字节变化，而非测试机器的其它能力限制。
                        empty_config = self.root / "scope-test.gitconfig"
                        empty_config.touch()
                        env.update(GIT_CONFIG_GLOBAL=str(empty_config), GIT_CONFIG_SYSTEM=str(empty_config),
                                   plugin=str(root), project=str(project), qa_task_pack=str(pack_path),
                                   candidate=str(candidate_path))
                        result = subprocess.run(["bash", "-c", example], env=env, cwd=project,
                                                capture_output=True, text=True, timeout=15)
                        self.assertEqual(0, result.returncode, result.stderr)
                        diagnosis = json.loads(result.stdout)
                        if kind == "commit-range":
                            self.assertEqual("match", diagnosis["status"], diagnosis)
                        else:
                            self.assertEqual("needs-evidence", diagnosis["status"], diagnosis)
                            self.assertEqual(fixed["changed_paths"], diagnosis["observed"]["changed_paths"])
                            self.assertNotEqual(fixed["diff_fingerprint"], diagnosis["observed"]["diff_fingerprint"])
                        self.assertEqual(hashlib.sha256(pack_path.read_bytes()).hexdigest(),
                                         diagnosis["handoff_ref"]["task_pack_sha256"])
                        self.assertNotIn("audit_result", diagnosis)

    def test_packaged_qa_compose_example_passes_validate_and_rejects_missing_evidence(self):
        """从每个宿主包的真实入口读取分组示例，走业务项目外的插件构造与验证命令。"""
        for host, root in self.installed.items():
            with self.subTest(host=host):
                reviewer = root / "skills/xy-qa-review"
                inputs = reviewer / "references/inputs.md"
                pm = root / "skills/xy-workflow/references/implementation-and-qa.md"
                # 检查 Reviewer、PM 都能从正常入口到达同一规范和当前示例，防止
                # 新命令虽被打包，却只能从源码开发环境或口头说明中找到。
                for entry in (reviewer / "SKILL.md", pm):
                    link = re.search(r"\[固定回执构造\]\(([^)#]+)#固定回执构造\)", entry.read_text())
                    self.assertIsNotNone(link)
                    self.assertEqual(inputs, (entry.parent / link[1]).resolve(strict=True))
                section = inputs.read_text().split("## 固定回执构造\n", 1)[1].split("\n## ", 1)[0]
                decisions = json.loads(section.split("```json\n", 1)[1].split("```", 1)[0])

                # 原包使用已有身份/规范夹具，显式冻结项目范围。仅将文档中留给
                # Reviewer 的证据值换为测试标识，字段和分组结构完全来自安装包示例。
                project = self.root / ("reviewer-evidence-" + host)
                project.mkdir()
                pack = qa_task_pack(host)
                pack["task"]["qa_scope_ref"] = {"repositories": [{
                    "path": ".", "base_revision": "base", "head_revision": "reviewed",
                    "diff_fingerprint": "d" * 64, "changed_paths": ["services/api.py"],
                }]}
                current = project / "pack.json"
                current.write_text(json.dumps(pack), encoding="utf-8")
                decisions["task_pack_sha256"] = hashlib.sha256(current.read_bytes()).hexdigest()
                decisions["review_method"]["capability_evidence"] = ["fixture:reviewer-event"]
                decisions["review_details"]["verification"][0].update(command="fixture-check", log_ref="fixture:full-log")
                decisions["rule_groups"][0]["evidence_refs"] = ["fixture:reviewed/services/api.py#L21-L27"]
                cli = ["bash", str(root / "lib/python_runtime.sh"), "-B", "-X", "utf8",
                       str(root / "plugins/source_pack.py"), "helper", "--project", str(project),
                       "lib/delivery/qa_handoff_cli.py"]
                decision_path = project / "decisions.json"
                decision_path.write_text(json.dumps(decisions), encoding="utf-8")
                candidate = project / "candidate.json"
                environment = isolated_environment(self.root / "home")
                environment.update(qa_task_pack=str(current), qa_decisions=str(decision_path),
                                   qa_candidate=str(candidate), test_plugin=str(root), test_project=str(project))
                execution = {"cwd": project, "env": environment,
                             "capture_output": True, "text": True, "timeout": 15}
                # PM 按真实文档命令保存候选，原样执行代码块中的固定命令；
                # 把路径占位符替换成带引号的环境变量，不把路径拼成可执行代码。
                example = section.split("```bash\n", 1)[1].split("```", 1)[0]
                example = example.replace("<plugin-root>", "${test_plugin}").replace("<absolute-project>", "${test_project}")
                generated = subprocess.run(["bash", "-c", example], **execution)
                self.assertEqual(0, generated.returncode, generated.stderr)
                self.assertEqual("", generated.stdout)
                original = candidate.read_bytes()
                receipt = json.loads(original)
                self.assertEqual(pack["task"]["agent_ref"], receipt["handoff_ref"]["agent_ref"])
                self.assertEqual("PASS", receipt["audit_result"])
                accepted = subprocess.run([*cli, "validate", "--task-pack", str(current),
                                           "--input", str(candidate)], **execution)
                self.assertEqual(0, accepted.returncode, accepted.stderr)
                self.assertEqual({"status": "valid"}, json.loads(accepted.stdout))

                # 同一 schema 2 对象仍可走每个已装配宿主原有的终端封装；这里的
                # 成功终端是夹具，只确认提取兼容性，不声称发生了原生模型调用。
                terminal = {
                    "codex": receipt,
                    "claude": {"type": "result", "subtype": "success", "is_error": False,
                               "structured_output": receipt},
                    "antigravity": {"conversation_id": "fixture", "status": "SUCCESS",
                                    "structured_output": receipt},
                }[host]
                terminal_file = project / "native.json"
                terminal_file.write_text(json.dumps(terminal), encoding="utf-8")
                extracted = subprocess.run([*cli, "extract", "--host", host, "--input", str(terminal_file),
                                            "--task-pack", str(current)], **execution)
                self.assertEqual(0, extracted.returncode, extracted.stderr)
                self.assertEqual(receipt, json.loads(extracted.stdout))

                # 只移除唯一适用规则的直接证据，同一已装配入口必须拒绝给出
                # 回执内容。再误用前一次输出路径，示例也须保全旧回执的原字节。
                decisions["rule_groups"][0]["evidence_refs"] = []
                rejected = subprocess.run([*cli, "compose", "--task-pack", str(current)],
                                          input=json.dumps(decisions), **execution)
                self.assertEqual(2, rejected.returncode, rejected.stderr)
                self.assertEqual("", rejected.stdout)
                self.assertIn("evidence", rejected.stderr)
                decision_path.write_text(json.dumps(decisions), encoding="utf-8")
                repeated = subprocess.run(["bash", "-c", example], **execution)
                self.assertNotEqual(0, repeated.returncode)
                self.assertEqual(original, candidate.read_bytes())

    def test_detached_ui_routes_wait_for_the_exact_applicable_visual_gate(self):
        project = self.root / "visual-project"
        project.mkdir()
        target = project / "current.json"
        for host in builder.HOSTS:
            for route in ("UI-Patch", "UI-Page", "UI-Flow"):
                with self.subTest(host=host, route=route):
                    value, gate = visual_request(route, project)
                    target.write_text(json.dumps(value), encoding="utf-8")
                    waiting = self.helper(host, project, "ready", "--input", target)
                    self.assertEqual(0, waiting.returncode, waiting.stderr)
                    self.assertEqual([], json.loads(waiting.stdout)["ready"])
                    value["approved_gates"].append(gate)
                    target.write_text(json.dumps(value), encoding="utf-8")
                    ready = self.helper(host, project, "ready", "--input", target)
                    self.assertEqual(0, ready.returncode, ready.stderr)
                    self.assertEqual(["web"], json.loads(ready.stdout)["ready"])

    def test_request_qa_waits_for_all_related_writers(self):
        project = self.root / "qa-project"
        project.mkdir()
        target = project / "current.json"
        for host in builder.HOSTS:
            with self.subTest(host=host):
                value = _writer_payload()
                value["request_id"] = "req-boundaries"
                first = value["tasks"][0]
                first["state"] = "BUILD_VERIFIED"
                first["blocks"] = ["consumer"]
                second = copy.deepcopy(first)
                second.update(id="consumer", agent_alias="fixture-consumer", state="DECLARED",
                              owned_paths=["backend/consumer.py"], blocks=[], depends_on=[first["id"]])
                for document in second["controlled_document_access"]["documents"]:
                    document["applies_to"] = second["owned_paths"]
                value["tasks"].append(second)
                target.write_text(json.dumps(value), encoding="utf-8")
                waiting = self.helper(host, project, "qa-ready", "--input", target)
                self.assertEqual(0, waiting.returncode, waiting.stderr)
                self.assertFalse(json.loads(waiting.stdout)["qa_ready"])
                second["state"] = "BUILD_VERIFIED"
                target.write_text(json.dumps(value), encoding="utf-8")
                ready = self.helper(host, project, "qa-ready", "--input", target)
                self.assertEqual(0, ready.returncode, ready.stderr)
                self.assertTrue(json.loads(ready.stdout)["qa_ready"])

    def test_packaged_pager_separates_authority_from_the_real_project_adapter(self):
        project = self.root / "pager-project"
        project.mkdir()
        (project / "project.yaml").write_text(ADAPTER, encoding="utf-8")
        # 项目同名product文件不能覆盖插件内原始权威；实际适配器继续取项目文件。
        (project / "product").mkdir()
        (project / "product/WORKFLOW.md").write_text("project shadow", encoding="utf-8")
        for host, root in self.installed.items():
            with self.subTest(host=host):
                base = [sys.executable, "-B", str(root / "plugins/source_pack.py"),
                        "helper", "--project", str(project), "lib/documents/context_read.py"]
                result = subprocess.run([*base, "product/WORKFLOW.md", "--root", str(project)],
                                        cwd=project, env=isolated_environment(self.root / "home"),
                                        capture_output=True, text=True, timeout=15)
                self.assertEqual(0, result.returncode, result.stderr)
                page = json.loads(result.stdout)
                self.assertEqual((PACK / "product/WORKFLOW.md").stat().st_size, page["total_bytes"])
                self.assertTrue(page["text"].startswith("# Agent Workflow"))
                actual = subprocess.run([*base, "project.yaml", "--root", str(project)],
                                        cwd=project, env=isolated_environment(self.root / "home"),
                                        capture_output=True, text=True, timeout=15)
                self.assertEqual(0, actual.returncode, actual.stderr)
                self.assertEqual(ADAPTER, json.loads(actual.stdout)["text"])
                wrong_resource = subprocess.run([sys.executable, "-B", str(root / "plugins/source_pack.py"),
                                                  "resource", ".agent-workflow/project.yaml"],
                                                 cwd=project, env=isolated_environment(self.root / "home"),
                                                 capture_output=True, text=True, timeout=15)
                self.assertEqual(2, wrong_resource.returncode)

    def test_ui_skills_resolve_and_page_their_canonical_references(self):
        project = self.root / "ui-reference-project"
        project.mkdir()
        env = isolated_environment(self.root / "home")
        references = (
            ("xy-ui-design", "xy-ui-design/references/design-quality.md"),
            ("xy-mobile-ui", "xy-mobile-ui/references/mobile-rules.md"),
            ("xy-qa-review", "xy-qa-review/references/inputs.md"),
            ("xy-prototype-verify", "xy-ui-design/references/prototype-feedback.md"),
        )
        for skill, reference in references:
            relative = f"platforms/shared/skills/{reference}"
            original = (PACK / relative).read_bytes()
            # 三端从真实项目 cwd 调用白名单工具。保留同名项目文件作为反例，防止
            # 只测试相对链接或投影副本，放过实际分页错误读取项目内容的回归。
            decoy = project / relative
            decoy.parent.mkdir(parents=True, exist_ok=True)
            decoy.write_text("project-owned decoy", encoding="utf-8")
            for host, root in self.installed.items():
                with self.subTest(host=host, skill=skill):
                    skill_body = (root / f"skills/{skill}/SKILL.md").read_text(encoding="utf-8")
                    self.assertIn(f"`{relative}`", skill_body)
                    self.assertEqual(original, (root / "skills" / reference).read_bytes())
                    base = [sys.executable, "-B", str(root / "plugins/source_pack.py")]
                    located = subprocess.run([*base, "resource", relative], cwd=project,
                                             env=env, capture_output=True, text=True, timeout=15)
                    self.assertEqual(0, located.returncode, located.stderr)
                    resource = json.loads(located.stdout)
                    self.assertEqual(root / relative, Path(resource["path"]))
                    self.assertEqual(hashlib.sha256(original).hexdigest(), resource["sha256"])
                    pager = [*base, "helper", "--project", str(project), "lib/documents/context_read.py",
                             relative, "--root", str(project)]
                    first = subprocess.run([*pager, "--limit", "128"], cwd=project,
                                           env=env, capture_output=True, text=True, timeout=15)
                    self.assertEqual(0, first.returncode, first.stderr)
                    first_page = json.loads(first.stdout)
                    self.assertFalse(first_page["eof"])
                    rest = subprocess.run(
                        [*pager, "--offset", str(first_page["next_offset"]), "--expect-sha256",
                         first_page["sha256"], "--limit", "24000"], cwd=project,
                        env=env, capture_output=True, text=True, timeout=15,
                    )
                    self.assertEqual(0, rest.returncode, rest.stderr)
                    last_page = json.loads(rest.stdout)
                    self.assertTrue(last_page["eof"])
                    self.assertEqual(resource["sha256"], last_page["sha256"])
                    self.assertEqual(original.decode("utf-8"), first_page["text"] + last_page["text"])

    def test_central_markers_and_bridge_environment_are_rejected_without_fallback(self):
        project = self.root / "central-project"
        project.mkdir()
        marker = project / ".agent-workflow/runtime.json"
        marker.parent.mkdir()
        marker.write_text("{}", encoding="utf-8")
        target = project / "current.json"
        target.write_text(json.dumps(_writer_payload()), encoding="utf-8")
        result = self.helper("codex", project, "validate", "--input", target)
        self.assertEqual(2, result.returncode)
        self.assertIn("original pinned runtime", result.stderr)
        marker.unlink()
        environment = isolated_environment(self.root / "home")
        environment["AGENT_WORKFLOW_RUNTIME_BINDING"] = "{}"
        result = self.helper("codex", project, "validate", "--input", target, env=environment)
        self.assertEqual(2, result.returncode)
        self.assertIn("central bridge environment", result.stderr)

    def test_a_task_pin_is_not_silently_migrated_to_the_plugin(self):
        project = self.root / "pinned-record-project"
        project.mkdir()
        value = _writer_payload()
        value["runtime_binding"] = {"protocol_version": 1, "content_id": "a" * 64,
                                    "manifest_sha256": "b" * 64}
        target = project / "current.json"
        target.write_text(json.dumps(value), encoding="utf-8")
        for host in builder.HOSTS:
            with self.subTest(host=host):
                result = self.helper(host, project, "validate", "--input", target)
                self.assertEqual(2, result.returncode)
                self.assertNotIn('"status": "valid"', result.stdout)
        self.assertFalse((project / ".agent-workflow").exists())

    def test_the_wrapper_does_not_expose_old_install_or_agent_runner_entrypoints(self):
        project = self.root / "entry-project"
        project.mkdir()
        root = self.installed["codex"]
        for path in ("manager/cli.py", "setup_codex.sh", "scripts/arbitrary.py"):
            with self.subTest(path=path):
                result = subprocess.run([sys.executable, "-B", str(root / "plugins/source_pack.py"),
                                         "helper", "--project", str(project), path],
                                        cwd=project, env=isolated_environment(self.root / "home"),
                                        capture_output=True, text=True, timeout=15)
                self.assertEqual(2, result.returncode)
        self.assertEqual([], list(project.iterdir()))

    def test_packaged_continuation_adapter_is_available_without_a_second_scheduler(self):
        project = self.root / "continuation-project"
        project.mkdir()
        current = project / "current.json"
        current.write_text(json.dumps(_writer_payload()), encoding="utf-8")
        for host, root in self.installed.items():
            with self.subTest(host=host):
                result = subprocess.run([sys.executable, "-B", str(root / "plugins/source_pack.py"),
                    "helper", "--project", str(project), "lib/agent_continuation_cli.py", "--input", str(current),
                    "--task-id", "backend", "--host", host, "--observed-state", "unknown", "--intent", "observe"],
                    cwd=project, env=isolated_environment(self.root / "home"),
                    capture_output=True, text=True, timeout=15)
                self.assertEqual(0, result.returncode, result.stderr)
                status = json.loads(result.stdout)
                self.assertFalse(status["reuse_allowed"])
                self.assertFalse(status["runtime_verified"])
                self.assertEqual("blocked", status["action"])

    def test_empty_project_bootstrap_init_validate_ready_keep_the_original_gates(self):
        for host, root in self.installed.items():
            project = self.root / ("bootstrap-empty-" + host)
            project.mkdir()
            base = [sys.executable, "-B", str(root / "plugins/source_pack.py"), "helper", "--project", str(project),
                    "plugins/project_context.py"]
            def invoke(*arguments):
                return subprocess.run([*base, *map(str, arguments)], cwd=project,
                    env=isolated_environment(self.root / "bootstrap-context"), capture_output=True, text=True, timeout=15)
            with self.subTest(host=host):
                inspected = invoke("inspect")
                self.assertEqual(0, inspected.returncode, inspected.stdout + inspected.stderr)
                self.assertFalse(json.loads(inspected.stdout)["exists"])
                self.assertEqual([], list(project.iterdir()))
                applied = invoke("apply", "--adapter", ".awf/project.yaml")
                self.assertEqual(0, applied.returncode, applied.stdout + applied.stderr)
                self.assertTrue(json.loads(applied.stdout)["created"])
                self.assertEqual([".awf"], [item.name for item in project.iterdir()])
                self.assertEqual(["project.yaml"], [item.name for item in (project / ".awf").iterdir()])
                original = (project / ".awf/project.yaml").read_bytes()
                reused = invoke("apply", "--adapter", ".awf/project.yaml")
                self.assertEqual(0, reused.returncode, reused.stdout)
                self.assertFalse(json.loads(reused.stdout)["created"])
                self.assertEqual(original, (project / ".awf/project.yaml").read_bytes())
                value = decisions()
                value["standards"]["leaves"] = value["standards"]["leaves"][:1]
                value["standards"]["required_engineering_rule_ids"] = ["eng-common-005"]
                value["tasks"][0]["selected_standards"] = [BUILTIN_ENGINEERING]
                decision = project / "decisions.json"; decision.write_text(json.dumps(value), encoding="utf-8")
                graph_path = project / "graph.json"
                initialized = invoke("init", "--adapter", ".awf/project.yaml", "--input", decision, "--output", graph_path)
                self.assertEqual(0, initialized.returncode, initialized.stdout + initialized.stderr)
                graph = json.loads(graph_path.read_bytes())
                self.assertEqual([], graph["approved_gates"])
                self.assertEqual(".awf/project.yaml", graph["tasks"][0]["controlled_document_access"]["adapter"])
                self.assertEqual(0, self.helper(host, project, "validate", "--input", graph_path).returncode)
                waiting = self.helper(host, project, "ready", "--input", graph_path)
                self.assertEqual([], json.loads(waiting.stdout)["ready"])
                self.assertFalse((project / "docs").exists())
                self.assertFalse((project / ".agent-workflow").exists())
                self.assertFalse((project / "AGENTS.md").exists())

    def test_project_bootstrap_reuses_valid_root_adapter_and_rejects_ambiguous_selection(self):
        project = self.root / "bootstrap-existing"
        project.mkdir()
        root = self.installed["claude"]
        base = [sys.executable, "-B", str(root / "plugins/source_pack.py"), "helper", "--project", str(project),
                "plugins/project_context.py"]
        def invoke(*arguments):
            return subprocess.run([*base, *arguments], cwd=project, env=isolated_environment(self.root / "context"),
                                  capture_output=True, text=True, timeout=15)
        self.assertEqual(0, invoke("apply", "--adapter", ".awf/project.yaml").returncode)
        adapter = project / ".awf/project.yaml"
        (project / "project.yaml").write_bytes(adapter.read_bytes())
        self.assertEqual(2, invoke("inspect").returncode)
        adapter.unlink();adapter.parent.rmdir()
        original = (project / "project.yaml").read_bytes()
        selected = invoke("inspect")
        self.assertEqual("project.yaml", json.loads(selected.stdout)["adapter"])
        self.assertEqual(0, invoke("apply", "--adapter", "project.yaml").returncode)
        self.assertEqual(original, (project / "project.yaml").read_bytes())
        self.assertFalse((project / ".awf").exists())
        self.assertEqual(2, invoke("apply", "--adapter", ".awf/project.yaml").returncode)
        self.assertFalse((project / ".awf").exists())

    def test_plugin_adapter_extension_rejects_untrusted_roots_and_arbitrary_paths(self):
        project = self.root / "adapter-negative-project"
        project.mkdir()
        value = _writer_payload()
        value["tasks"][0]["controlled_document_access"]["adapter"] = "docs/other.yaml"
        current = project / "current.json"; current.write_text(json.dumps(value), encoding="utf-8")
        result = self.helper("codex", project, "validate", "--input", current)
        self.assertEqual(2, result.returncode)
        self.assertIn("controlled_document_access.adapter", result.stderr)
        value["tasks"][0]["controlled_document_access"]["adapter"] = ".awf/project.yaml"
        current.write_text(json.dumps(value), encoding="utf-8")
        environment = isolated_environment(self.root / "fake-root")
        environment["AGENT_WORKFLOW_PLUGIN_ROOT"] = str(project)
        rejected = self.helper("codex", project, "validate", "--input", current, env=environment)
        self.assertEqual(2, rejected.returncode)
        self.assertFalse((project / ".awf").exists())


if __name__ == "__main__":
    unittest.main()
