"""验证插件实际加载内容和原helper的业务门禁，不另写简化工作流。"""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import zipfile

from lib.skills import business_confirmation_policy as policy
from lib.skills.role_skills import CORE_SKILLS, ROLE_SKILLS
from tests.test_plugin_delivery import PACK, builder, isolated_environment
from tests.test_scheduler_boundaries import _writer_payload
from tests.test_task_graph_init import ADAPTER, BUILTIN_ENGINEERING, decisions
from tests.test_task_graph import _standards_payload


def visual_request(route: str) -> tuple[dict, str]:
    """沿用原UI路由夹具的真实合同结构，专门验证已装配helper的两阶段门禁。"""
    page_sha, requirements_sha = "b" * 64, "a" * 64
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
            with zipfile.ZipFile(archive) as payload:
                payload.extractall(target)
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
                    self.assertEqual(header + b"\n" + envelope + b"\n" + body, loaded)
                    self.assertEqual(adapter_source,
                                     metadata["projections"][f"skills/{skill}/SKILL.md"]["adapter"])
                    for reference in original.parent.rglob("*"):
                        if reference.is_file() and reference != original:
                            self.assertEqual(reference.read_bytes(),
                                             (root / "skills" / skill / reference.relative_to(original.parent)).read_bytes())
                self.assertEqual([], policy.validate_business_confirmation_pack(root, host))

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

    def test_loaded_confirmation_policy_rejects_a_third_business_gate(self):
        root = self.installed["codex"]
        actual = [(Path("product/WORKFLOW.md"), (root / "product/WORKFLOW.md").read_text(encoding="utf-8")),
                  (Path("skills/xy-workflow/SKILL.md"), (root / "skills/xy-workflow/SKILL.md").read_text(encoding="utf-8"))]
        self.assertEqual([], policy.validate_business_confirmation_texts(actual))
        invalid = [*actual, (Path("plugin-envelope.md"), "PM must obtain build approval before implementation.")]
        self.assertTrue(policy.validate_business_confirmation_texts(invalid))
        # 适配文字没有自动批准、跳过Full或另设Reviewer；真正业务规则来自唯一原文。
        source = (root / "product/WORKFLOW.md").read_text(encoding="utf-8")
        self.assertEqual(1, source.count(policy.DEFAULT_POLICY))
        self.assertIn("requirements_approved", source)
        self.assertIn("visual_approved", source)
        self.assertIn("max_active_reviewers: 1", source)
        light = (root / "skills/xy-workflow/SKILL.md").read_text(encoding="utf-8")
        self.assertIn("does not repeat confirmation when an explicit user instruction", light)

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

    def test_detached_ui_routes_wait_for_the_exact_applicable_visual_gate(self):
        project = self.root / "visual-project"
        project.mkdir()
        target = project / "current.json"
        for host in builder.HOSTS:
            for route in ("UI-Patch", "UI-Page", "UI-Flow"):
                with self.subTest(host=host, route=route):
                    value, gate = visual_request(route)
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
                result = subprocess.run([*base, ".agent-workflow/product/WORKFLOW.md", "--root", str(project)],
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
