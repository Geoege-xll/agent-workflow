"""从三个发行包运行原调度入口。自然语言及宿主工具行为另由公共逐轮剧本验收。"""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile
import unittest

from lib.delivery.worktree_cli import git, head
from tests.test_dispatch_admission import plugin_helper
from tests.test_plugin_delivery import PACK, builder, isolated_environment
from tests.test_plugin_workflow_contract import visual_request
from tests.test_task_graph_init import ADAPTER, BUILTIN_ENGINEERING, decisions
from tests.test_task_graph_records import graph as production_graph


def project_files(root: Path) -> dict:
    """包含目录和隐藏文件，确保提前创建空图、适配器目录或覆盖旧文件都能观察到。"""
    return {path.relative_to(root): path.read_bytes() if path.is_file() else None
            for path in root.rglob("*")}


class ConversationScopeTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        temporary = tempfile.TemporaryDirectory(prefix="awf-conversation-scope-")
        cls.addClassCleanup(temporary.cleanup)
        cls.root = Path(temporary.name).resolve()
        cls.packages = {}
        for host in builder.HOSTS:
            archive = builder.build(PACK, cls.root / "archives", host)
            installed = cls.root / host
            installed.mkdir()
            builder.unpack_archive(archive, installed)
            cls.packages[host] = installed

    def setUp(self):
        # 调用进程的 cwd 是含同名文件的相邻项目，所有 project 参数显式指向本项目。
        # 两个项目的初始内容有意不同，可以发现误用 cwd 或跨项目写入。
        temporary = tempfile.TemporaryDirectory(dir=self.root)
        self.addCleanup(temporary.cleanup)
        self.workspace = Path(temporary.name)
        self.project = self.workspace / "settings"
        self.neighbor = self.workspace / "neighbor"
        for project in (self.project, self.neighbor):
            project.mkdir()
            (project / "project.yaml").write_text(ADAPTER, encoding="utf-8")
            (project / "settings.txt").write_text(project.name, encoding="utf-8")
        baseline = project_files(self.neighbor)
        self.addCleanup(lambda: self.assertEqual(baseline, project_files(self.neighbor)))

    def invoke(self, host, *args, value=None, code=0, helper="lib/task_graph_cli.py", entry_root=None):
        command = plugin_helper(self.packages[host], entry_root or self.project, helper)
        result = subprocess.run(
            [*command, *map(str, args)], cwd=self.neighbor, env=isolated_environment(self.workspace),
            input=json.dumps(value, ensure_ascii=False) if value is not None else None,
            capture_output=True, text=True, timeout=30,
        )
        self.assertEqual(code, result.returncode, result.stdout + result.stderr)
        return json.loads(result.stdout if code == 0 else result.stderr)

    def test_native_pm_entries_distinguish_discussion_estimates_from_execution(self):
        # 三个宿主通过不同入口交付 PM 指令，Codex 的文本取自实际启动 Hook。
        # 模型如何理解逐轮对话另见配套剧本；这里验证它真正收到的指令。
        for host, package in self.packages.items():
            with self.subTest(host=host):
                if host == "codex":
                    hook = subprocess.run(
                        ["bash", str(package / "lib/python_runtime.sh"), "-B", str(package / "hooks/session_start.py")],
                        cwd=self.project, check=True, capture_output=True, text=True, timeout=15,
                    )
                    entry = json.loads(hook.stdout)["hookSpecificOutput"]["additionalContext"]
                else:
                    entry_path = "agents/pm.md" if host == "claude" else "rules/AGENTS.md"
                    entry = (package / entry_path).read_text(encoding="utf-8")
                paragraphs = entry.splitlines()
                discussion = next(line for line in paragraphs if "**Conversation-only discussion.**" in line)
                delegated = next(line for line in paragraphs if "Use `skills/xy-workflow/SKILL.md`" in line)
                self.assertIn("likely Light or Full level if implementation were requested", discussion)
                self.assertIn("only when the user explicitly delegates the corresponding deliverable", discussion)
                self.assertIn("classify directly as Light or Full", delegated)
                self.assertIn("only for a material gap in the deliverable, scope, impact or acceptance", delegated)
                integration = (package / f"platforms/{host}/references/pm-integration.md").read_text(encoding="utf-8")
                self.assertIn("only for a material gap in the deliverable, scope, impact or acceptance", integration)

    def test_scope_is_checked_before_init_can_publish_a_production_task(self):
        # 客户端只把已解析的 PM 决定交给 init，不能用虚构的词表解析用户消息。
        # 对照组复用相同生产任务，只有本次请求的交付范围不同。
        proposal = decisions()
        proposal["standards"]["leaves"] = proposal["standards"]["leaves"][:1]
        proposal["standards"]["required_engineering_rule_ids"] = ["eng-common-005"]
        proposal["tasks"][0]["selected_standards"] = [BUILTIN_ENGINEERING]
        for host in self.packages:
            target = self.project / f"{host}.json"
            init = ("init", "--root", self.project, "--output", target)
            before = project_files(self.project)
            for restricted in ("discussion_only", "prototype_only"):
                with self.subTest(host=host, scope=restricted):
                    self.invoke(host, *init, value={**proposal, "request_scope": restricted}, code=2)
                    self.assertEqual(before, project_files(self.project))
            with self.subTest(host=host, scope="implementation"):
                self.invoke(host, *init, value={**proposal, "request_scope": "implementation"})
                graph = json.loads(target.read_bytes())
                self.assertEqual({proposal["request_id"]: "implementation"}, graph["request_scope"])
                self.assertEqual([], graph["approved_gates"])
                self.assertEqual([], self.invoke(host, "ready", "--input", target)["ready"])
                # 同意进入实施范围仍可能有待确认的需求。待决图可以查询，但正式
                # Writer 交接必须拒绝，且这个只读尝试不能替 PM 改写批准记录。
                pending = target.read_bytes()
                rejected = self.invoke(host, "task", "--input", target, "--task-id", "api", code=2)
                self.assertIn("requirements_approved", rejected["error"])
                self.assertEqual(pending, target.read_bytes())
                # 正式 init 消费 PM 已核实的需求批准。用另一个输出做同输入正对照，
                # 两个样本只有该门的批准事实不同；不编辑先前的待决图。
                approved = self.project / f"{host}-approved.json"
                self.invoke(host, "init", "--root", self.project, "--output", approved,
                            value={**proposal, "request_scope": "implementation",
                                   "approved_gates": ["requirements_approved"]})
                self.assertEqual(["api"], self.invoke(host, "ready", "--input", approved)["ready"])
                pack = self.invoke(host, "task", "--input", approved, "--task-id", "api")
                self.assertEqual("implementation", pack["request_scope"])
                self.assertEqual(["requirements_approved"], pack["approved_gates"])
                # Light 单包直接走另一条消费路径。沿用已获批准的生产合同，只收紧范围。
                pack["task"]["workflow_level"] = "Light"
                self.invoke(host, "validate", value=pack)
                for restricted in ("discussion_only", "prototype_only"):
                    self.invoke(host, "validate", value={**pack, "request_scope": restricted}, code=2)

    def test_accepted_prototype_ends_without_production_writer_or_qa(self):
        graph, gate = visual_request("UI-Page")
        prototype = graph["tasks"][0]
        graph["tasks"] = [prototype]
        graph["request_id"] = prototype["request_id"]
        graph["request_scope"] = {prototype["request_id"]: "prototype_only"}
        prototype.update(design_mode="prototype", blocks=[], goal="交付设置页原型",
                         input_contracts=["仅原型交付"], output_contracts=["可点击的设置页"],
                         acceptance_evidence=["原型静态核验结果"], verification_commands=["执行原型静态核验"])
        record = self.workspace / "prototype.json"
        for host in self.packages:
            with self.subTest(host=host):
                before = project_files(self.project)
                prototype["state"] = "DECLARED"
                graph["approved_gates"] = ["requirements_approved"]
                self.assertEqual(["prototype"], self.invoke(host, "ready", value=graph)["ready"])
                prototype["state"] = "BUILD_VERIFIED"
                graph["approved_gates"].append(gate)
                self.assertEqual([], self.invoke(host, "ready", value=graph)["ready"])
                self.assertFalse(self.invoke(host, "qa-ready", value=graph)["qa_ready"])
                record.write_text(json.dumps(graph), encoding="utf-8")
                pack = self.invoke(host, "task", "--input", record, "--task-id", prototype["id"])
                self.assertEqual("prototype_only", pack["request_scope"])
                # 同一原型与同一份页面确认，向仅原型图中误加生产任务必须被正式入口拒绝。
                widened, _ = visual_request("UI-Page")
                widened.update(request_scope=graph["request_scope"], approved_gates=graph["approved_gates"])
                self.invoke(host, "ready", value=widened, code=2)
                self.assertEqual(before, project_files(self.project))

    def test_implementation_waits_for_current_page_and_preserves_other_requests_scope(self):
        graph, gate = visual_request("UI-Page", self.project)
        prototype, writer = graph["tasks"]
        other = copy.deepcopy(prototype)
        other.update(id="report", agent_alias="fixture-report", request_id="req-report", blocks=[],
                     owned_paths=["docs/standards/prototype/report.html"])
        # 原 UI 夹具仅服务图级 ready。此处要经真实单包消费，还需提供当前接收者
        # 完整的目标、合同和验证约定，避免图可调度却没有可供交接的任务。
        writer.update(goal="实现已确认的提醒设置页", input_contracts=["采用当前冻结设计"],
                      output_contracts=["设置页支持切换提醒"], acceptance_evidence=["对应交互验证结果"],
                      verification_commands=["执行设置页测试"])
        for rule in other["controlled_document_access"]["documents"]:
            rule["applies_to"] = other["owned_paths"]
        graph["request_id"] = other["request_id"]
        graph["request_scope"] = {writer["request_id"]: "implementation", other["request_id"]: "discussion_only"}
        path = self.workspace / "requests.json"
        for host in self.packages:
            with self.subTest(host=host):
                before = project_files(self.project)
                for approvals in ([gate], ["requirements_approved"],
                                  ["requirements_approved", gate.replace("settings@", "report@")],
                                  ["requirements_approved", "visual_approved:settings@" + "f" * 64]):
                    graph["approved_gates"] = approvals
                    self.assertEqual([], self.invoke(host, "ready", value=graph)["ready"], approvals)
                graph["approved_gates"] = ["requirements_approved", gate]
                self.assertEqual(["web"], self.invoke(host, "ready", value=graph)["ready"])
                # A 的任务使用 A 的许可；图顶层 B 的只讨论范围不能覆盖 A 的单包。
                path.write_text(json.dumps(graph), encoding="utf-8")
                pack = self.invoke(host, "task", "--input", path, "--task-id", writer["id"])
                self.assertEqual("implementation", pack["request_scope"])
                self.assertEqual(writer["request_id"], pack["task"]["request_id"])
                self.assertEqual({"status": "valid"}, self.invoke(host, "validate", value=pack))
                # 若 B 随后获准做原型，同一个图级 requirements_approved 无法分别证明
                # A/B 的需求批准。即便 B 已交付，仍应拒绝这张共享门禁的候选图。
                combined = copy.deepcopy(graph)
                combined["request_scope"][other["request_id"]] = "prototype_only"
                combined["tasks"].append(other)
                rejected = self.invoke(host, "ready", value=combined, code=2)
                self.assertIn("shared approval gates", rejected["error"])
                self.assertEqual(before, project_files(self.project))

    def test_prototype_path_in_project_cannot_resolve_to_neighbor(self):
        # 设计合同里页路径合法，但目录实际指向平级项目。真实适配器和文件系统
        # 必须一起约束准入，避免仅原型任务获得另一个项目的同名页面。
        graph, _ = visual_request("UI-Page")
        prototype = graph["tasks"][0]
        prototype.update(state="DECLARED", blocks=[])
        graph["tasks"] = [prototype]
        graph["request_scope"] = {prototype["request_id"]: "prototype_only"}
        standards = self.project / "docs/standards"
        standards.mkdir(parents=True)
        (standards / "prototype").symlink_to(self.neighbor, target_is_directory=True)
        before = project_files(self.project)
        rejected = self.invoke("codex", "ready", value=graph, code=2)
        self.assertIn("prototype_only", rejected["error"])
        self.assertEqual(before, project_files(self.project))

    def test_isolated_prototype_claim_checks_main_and_execution_worktree(self):
        # 三棵树都由临时仓库真实创建。设计任务在 worker 写文件，主树负责约束，
        # integration 仅作既有交付合同的目标；目录名本身不能证明工作树登记关系。
        git(self.project, "init", "-b", "main")
        git(self.project, "add", "project.yaml", "settings.txt")
        git(self.project, "-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid",
            "commit", "-m", "原型工作树夹具")
        base = head(self.project)
        worker = self.workspace / "worker"
        integration = self.workspace / "integration"
        for tree in (worker, integration):
            git(self.project, "worktree", "add", "--detach", str(tree), base)

        graph, _ = visual_request("UI-Page")
        prototype = graph["tasks"][0]
        request = prototype["request_id"]
        prototype.update(state="DECLARED", blocks=[], execution_workspace={
            "root": str(worker), "base_revision": base, "head_revision": None})
        graph.update(tasks=[prototype], request_scope={request: "prototype_only"}, worktree_integrations={
            request: {"root": str(integration), "target_branch": "main", "target_base": base,
                      "head_revision": None, "verification": []}})
        record = self.workspace / "prototype.json"
        record.write_text(json.dumps(graph), encoding="utf-8")
        original = record.read_bytes()
        manifest = self.workspace / "admission.json"
        descriptors = {
            "schema_version": 1, "project_root": str(self.project),
            "records": [{"path": str(record), "sha256": hashlib.sha256(original).hexdigest(),
                         "execution_roots": {prototype["id"]: str(worker)}}],
            "capacity": {"configured_subagents": 1, "configured_writers": 1, "host_available_subagents": 1},
        }
        manifest.write_text(json.dumps(descriptors), encoding="utf-8")
        worker_manifest = self.workspace / "worker-admission.json"
        worker_manifest.write_text(json.dumps({**descriptors, "project_root": str(worker)}), encoding="utf-8")
        admission = "lib/dispatch_admission_cli.py"
        target = {"record": str(record), "request_id": request, "task_id": prototype["id"]}
        selection = ("--record", record, "--request-id", request, "--task-id", prototype["id"])
        claim = ("claim", "--input", manifest, *selection)
        view = self.invoke("codex", "view", "--input", manifest, helper=admission)
        self.assertEqual([target], view["candidates"])
        worker_entry = {"entry_root": worker, "helper": admission}
        worker_view = self.invoke("codex", "view", "--input", worker_manifest, **worker_entry)
        self.assertEqual([target], worker_view["candidates"])

        for tree in (self.project, worker):
            with self.subTest(tree=tree.name):
                # 每次只改变一棵树。任一边界失配都必须拦住领取且保持现有原记录，
                # 包括路径本身没有软链接、实际页面却与业务文件共享 inode 的情况。
                adapter = tree / "project.yaml"
                adapter.write_text(ADAPTER.replace("docs/standards/", "docs/other/"), encoding="utf-8")
                rejected = self.invoke("codex", *claim, helper=admission, code=2)
                self.assertIn("standards root", rejected["error"])
                if tree == self.project:
                    # 反过来从合法执行树发起调度，此时只有原主树漂移。每个入口都
                    # 必须定位同一个 Git 主树；将命令的项目参数改成 worker 不能越过校验。
                    rejected = self.invoke("codex", "ready", "--input", record, entry_root=worker, code=2)
                    self.assertIn("standards root", rejected["error"])
                    for command in (("view",), ("claim", *selection)):
                        rejected = self.invoke("codex", *command, "--input", worker_manifest,
                                               **worker_entry, code=2)
                        self.assertIn("standards root", rejected["error"])
                adapter.write_text(ADAPTER, encoding="utf-8")
                page = tree / prototype["owned_paths"][0]
                page.parent.mkdir(parents=True)
                page.hardlink_to(tree / "settings.txt")
                rejected = self.invoke("codex", *claim, helper=admission, code=2)
                self.assertIn("links", rejected["error"])
                page.unlink()
                page.symlink_to(tree / "settings.txt")
                rejected = self.invoke("codex", "ready", "--input", record, code=2)
                self.assertIn("links", rejected["error"])
                page.unlink()
                self.assertEqual(original, record.read_bytes())
        # 两棵树恢复后，原 SHA 仍可正常领取，证明负控没有损坏状态或永久封禁原型。
        receipt = self.invoke("codex", *claim, helper=admission)
        self.assertEqual("claimed", receipt["status"])
        self.assertEqual(target, receipt["target"])
        self.assertEqual("RUNNING", json.loads(record.read_bytes())["tasks"][0]["state"])

    def test_admission_keeps_legacy_authority_with_its_own_request(self):
        # 同一项目可以同时接待已实施的旧请求与新原型请求。旧记录缺范围本身允许；
        # 把它改挂到受限的新请求之后，原调度入口必须在领取前发现两份授权冲突。
        prototype_graph, _ = visual_request("UI-Page")
        prototype = prototype_graph["tasks"][0]
        prototype["blocks"] = []
        prototype_graph["tasks"] = [prototype]
        prototype_graph["request_scope"] = {prototype["request_id"]: "prototype_only"}
        design_path = self.project / "design.json"
        design_path.write_text(json.dumps(prototype_graph), encoding="utf-8")
        legacy = production_graph()
        record_path = self.project / "legacy.json"
        manifest_path = self.workspace / "manifest.json"
        manifest = {"schema_version": 1, "project_root": str(self.project),
                    "capacity": {"configured_subagents": 2, "configured_writers": 1,
                                 "host_available_subagents": 2}}
        task = legacy["tasks"][0]
        for request in (task["request_id"], prototype["request_id"]):
            legacy["request_id"] = task["request_id"] = request
            record_path.write_text(json.dumps(legacy), encoding="utf-8")
            manifest["records"] = [
                {"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                 "execution_roots": {task_id: str(self.project)}}
                for path, task_id in ((design_path, prototype["id"]), (record_path, task["id"]))
            ]
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            before = project_files(self.project)
            if request == prototype["request_id"]:
                rejected = self.invoke("codex", "claim", "--input", manifest_path, "--record", record_path,
                                       "--request-id", request, "--task-id", task["id"], code=2,
                                       helper="lib/dispatch_admission_cli.py")
                self.assertIn("request_scope", rejected["error"])
            else:
                observed = self.invoke("codex", "view", "--input", manifest_path,
                                       helper="lib/dispatch_admission_cli.py")
                self.assertEqual([{"record": str(record_path), "request_id": request, "task_id": task["id"]}],
                                 observed["candidates"])
            self.assertEqual(before, project_files(self.project))

    def test_independent_request_claim_preserves_running_owner_and_rejects_replay(self):
        # PM 已经把三个明确的实施委托分别建图。只讨论 B 的轮次没有记录可领取；
        # 对自然语言的判断由宿主剧本验证，此处从现有正式发行包检查领取边界。
        source = self.project / "src"
        source.mkdir()
        (source / "fixture.txt").write_text("公开夹具", encoding="utf-8")
        admission = "lib/dispatch_admission_cli.py"
        manifest = self.workspace / "admission.json"
        paths = {name: self.workspace / f"{name}.json" for name in ("a", "b", "c")}
        capacity = {"configured_subagents": 3, "configured_writers": 3, "host_available_subagents": 3}

        def save_manifest():
            # 每次重新读取原记录字节，避免把旧投影的比较交换失败误解为路径或门禁拦截。
            manifest.write_text(json.dumps({
                "schema_version": 1, "project_root": str(self.project), "capacity": capacity,
                "records": [{"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                             "execution_roots": {"api": str(self.project)}} for path in paths.values()],
            }), encoding="utf-8")

        def claim(name, code=0):
            return self.invoke("codex", "claim", "--input", manifest, "--record", paths[name],
                               "--request-id", name, "--task-id", "api", code=code, helper=admission)

        for name, owned, lock in (("a", "src/settings", "settings"), ("b", "src/report", "report"),
                                  ("c", "src/settings", "settings")):
            record = production_graph()
            record.update(request_id=name, request_scope={name: "implementation"},
                          active_paths=[], active_semantic_locks=[])
            task = record["tasks"][0]
            task.update(request_id=name, owned_paths=[owned], semantic_locks=[lock])
            for document in task["controlled_document_access"]["documents"]:
                document["applies_to"] = [owned]
            # 独立委托 B 仍需自己的批准，不能从 A 借用同名门禁。
            if name == "b":
                record["approved_gates"] = []
            paths[name].write_text(json.dumps(record), encoding="utf-8")

        before = project_files(self.project)
        save_manifest()
        self.assertEqual("claimed", claim("a")["status"])
        active_a = paths["a"].read_bytes()
        save_manifest()
        view = self.invoke("codex", "view", "--input", manifest, helper=admission)
        self.assertEqual([], view["candidates"])
        waiting = {row["request_id"]: row["reasons"] for row in view["waiting"]}
        self.assertIn("record_gates_dependencies_locks_or_qa", waiting["b"])
        self.assertIn("path_conflict", waiting["c"])
        self.assertIn("semantic_lock_conflict", waiting["c"])
        self.assertIn("not an admitted spawn candidate", claim("c", code=2)["error"])

        # B 独立取得批准后仅更改 B 的原记录；持有旧摘要和重新查询后的第二次领取都必须拒绝。
        authorized_b = json.loads(paths["b"].read_bytes())
        authorized_b["approved_gates"] = ["requirements_approved"]
        paths["b"].write_text(json.dumps(authorized_b), encoding="utf-8")
        save_manifest()
        receipt = claim("b")
        self.assertEqual({"record": str(paths["b"]), "request_id": "b", "task_id": "api"}, receipt["target"])
        claimed_b = paths["b"].read_bytes()
        self.assertEqual("RUNNING", json.loads(claimed_b)["tasks"][0]["state"])
        self.assertIn("fingerprint changed", claim("b", code=2)["error"])
        save_manifest()
        self.assertIn("not an admitted spawn candidate", claim("b", code=2)["error"])
        self.assertEqual(active_a, paths["a"].read_bytes())
        self.assertEqual(claimed_b, paths["b"].read_bytes())
        self.assertEqual("DECLARED", json.loads(paths["c"].read_bytes())["tasks"][0]["state"])
        self.assertEqual(before, project_files(self.project))
