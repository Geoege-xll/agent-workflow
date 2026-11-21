"""三宿主离线包的持续接单回归。主会话判断用户意图后，通过真实包内入口操作原记录。"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from uuid import uuid4

from tests.test_conversation_scope import project_files
from tests.test_dispatch_admission import plugin_helper
from tests.test_plugin_delivery import PACK, builder, isolated_environment
from tests.test_task_graph_init import ADAPTER, BUILTIN_ENGINEERING, decisions
from tests.test_task_graph_records import graph


POOL = "lib/task_pool_cli.py"
GRAPH = "lib/task_graph_cli.py"
CAPACITY = ("--configured-subagents", "2", "--configured-writers", "2", "--host-available-subagents", "2")


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def task_in(path):
    value = json.loads(path.read_bytes())
    return value["task"] if "task" in value else value["tasks"][0]


class PackagedTaskPoolTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # 各宿主只构建一次，后续命令均从实际解包目录启动。相邻项目没有源码库，
        # 从而能发现白名单未登记、传递依赖漏装或意外依赖开发仓 cwd 的回归。
        temporary = tempfile.TemporaryDirectory(prefix="awf-pool-packages-")
        cls.addClassCleanup(temporary.cleanup)
        cls.root = Path(temporary.name).resolve()
        cls.plugins = {}
        for host in builder.HOSTS:
            archive = builder.build(PACK, cls.root / "archives", host)
            package = cls.root / host
            package.mkdir()
            builder.unpack_archive(archive, package)
            cls.plugins[host] = package

    def setUp(self):
        temporary = tempfile.TemporaryDirectory(dir=self.root)
        self.addCleanup(temporary.cleanup)
        self.workspace = Path(temporary.name)
        self.project = self.workspace / "project"
        self.project.mkdir()
        (self.project / "project.yaml").write_text(ADAPTER, encoding="utf-8")
        (self.project / "src").mkdir()
        (self.project / "src/fixture.txt").write_text("既有项目内容", encoding="utf-8")
        # 系统 scratch 也放入这一个夹具，以便断言纯讨论没有建立索引或写入其他文件。
        self.env = isolated_environment(self.workspace)
        self.env["TMPDIR"] = str(self.workspace)
        self.agy_pm = "antigravity:" + str(uuid4())

    def invoke(self, host, helper, *args, value=None, code=0):
        command = plugin_helper(self.plugins[host], self.project, helper)
        result = subprocess.run(
            [*command, *map(str, args)], cwd=self.workspace, env=self.env,
            input=json.dumps(value, ensure_ascii=False) if value is not None else None,
            capture_output=True, text=True, timeout=45,
        )
        self.assertEqual(code, result.returncode, result.stdout + result.stderr)
        return json.loads(result.stdout if code == 0 else result.stderr)

    def pool(self, host, command, *args, code=0):
        # 新进程只拿到宿主提供的同一 PM 标识，恢复查询不传上轮记录名或任务 ID。
        pm = self.agy_pm if host == "antigravity" else host + ":main-session"
        return self.invoke(host, POOL, command, "--root", self.project, "--pm-id", pm,
                           *args, code=code)

    def register(self, host, request, title, *, light=False, owned=None):
        # 模拟现存未升级的普通 Full 图；Light 复用原任务导出入口生成旧单包形状。
        # 两种原件的 task ID 故意相同，只有标题、请求及实际文件能定位这一次操作。
        path = self.workspace / (request + ".json")
        value = graph()
        value.update(request_id=request, active_paths=[], active_semantic_locks=[])
        task = value["tasks"][0]
        owned = owned or ("src/" + request + ".txt")
        task.update(request_id=request, goal=title, owned_paths=[owned], semantic_locks=[Path(owned).stem])
        for document in task["controlled_document_access"]["documents"]:
            document["applies_to"] = [owned]
        path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
        if light:
            pack = self.invoke(host, GRAPH, "task", "--input", path, "--task-id", task["id"])
            pack["task"]["workflow_level"] = "Light"
            path.write_text(json.dumps(pack, ensure_ascii=False), encoding="utf-8")
        original = path.read_bytes()
        self.pool(host, "register", "--record", path, "--expect-sha256", digest(path), "--title", title)
        self.assertEqual(original, path.read_bytes())
        return path

    def locate(self, host, title):
        view = self.pool(host, "view", "--query", title)
        self.assertEqual([], view["errors"])
        self.assertEqual(1, len(view["tasks"]), view)
        return view["tasks"][0]

    def claim(self, host, row, *, code=0):
        return self.pool(host, "claim", "--record", row["record"], "--request-id", row["request_id"],
                         "--task-id", row["task_id"], "--expect-sha256", row["sha256"], *CAPACITY, code=code)

    def update(self, host, row, operation, *, expected=None, code=0):
        return self.invoke(host, GRAPH, "update", "--input", row["record"], "--expect-sha256",
                           expected or row["sha256"], "--patch", "-", code=code,
                           value={"tasks": {row["task_id"]: operation}})

    def test_codex_prototype_only_single_packs_are_claimed_and_bound_before_handoff(self):
        from tests.test_plugin_workflow_contract import visual_request
        # 正常仅原型入口直接消费两个独立单包，测试不建 Full 图或生产 QA。
        # 两个包可共享同一请求、角色与别名，用真实目标和领取回执区分执行身份。
        example, _ = visual_request("UI-Page")
        receipts, paths = [], []
        # 在已有原型工作区追加独立页面。未建立的共同父目录仍由原资源锁保守
        # 占用；此夹具提供真实节点，不把未来目录的名称语义冒充已知事实。
        pages = self.project / "docs/standards/prototype"
        pages.mkdir(parents=True)
        for name in ("checkout", "settings"):
            (pages / (name + ".html")).write_text("<main></main>", encoding="utf-8")
        for name in ("checkout", "settings"):
            task = json.loads(json.dumps(example["tasks"][0]))
            task.update(workflow_level="Light", id=name, state="DECLARED", blocks=[],
                        goal=name, input_contracts=["user:确认的页面需求"], output_contracts=["可审阅原型"],
                        verification_commands=["检查原型页面"], acceptance_evidence=["静态核验"],
                        owned_paths=["docs/standards/prototype/" + name + ".html"])
            for doc in task["controlled_document_access"]["documents"]:
                doc["applies_to"] = task["owned_paths"]
            pack = {key: example[key] for key in ("schema_version", "standards_contract", "ui_contract")}
            pack.update(task=task, request_scope="prototype_only", approved_gates=[])
            path = self.workspace / (name + ".json")
            path.write_text(json.dumps(pack), encoding="utf-8")
            def prepare(code=0):
                return self.pool("codex", "claim", "--register", "--title", name, "--record", path,
                                 "--task-id", name, "--request-id", task["request_id"], "--expect-sha256",
                                 digest(path), *CAPACITY, code=code)
            before = project_files(self.workspace)
            self.assertIn("approvals", prepare(code=2)["error"])
            self.assertEqual(before, project_files(self.workspace))
            for scope in ("discussion_only", "implementation", None):
                value = {**pack, "request_scope": scope}
                if scope is None:
                    value.pop("request_scope")
                self.invoke("codex", GRAPH, "validate", value=value, code=2)
            pack["approved_gates"] = ["requirements_approved"]
            path.write_text(json.dumps(pack), encoding="utf-8")
            if name == "checkout":
                # Light 只声明实质方案正文时，由原包计算批准门。即使需求已批，
                # 缺少该决定的当前批准，也不能因未手写派生门名而创建池记录。
                decision = {"id": "retry", "content": "提交失败后保留输入并允许重试"}
                task["solution_decisions"] = [decision]
                path.write_text(json.dumps(pack), encoding="utf-8")
                before = project_files(self.workspace)
                self.assertIn("approvals", prepare(code=2)["error"])
                self.assertEqual(before, project_files(self.workspace))
                self.invoke("codex", GRAPH, "update", "--input", path, "--expect-sha256", digest(path),
                            "--patch", "-", value={"approve_solutions": [
                                {**decision, "task_id": name, "request_id": task["request_id"],
                                 "source_ref": "user:确认失败重试"}]})
            pm = "codex:main-session"
            self.assertIn("claim", self.invoke("codex", GRAPH, "task", "--input", path, "--pm-id", pm, code=2)["error"])
            self.invoke("codex", GRAPH, "update", "--input", path, "--expect-sha256", digest(path),
                        "--patch", "-", value={"tasks": {name: {"set": {"state": "RUNNING"}}}}, code=2)
            receipt = prepare()
            receipt_file = self.workspace / (name + "-claim.json")
            receipt_file.write_text(json.dumps(receipt), encoding="utf-8")
            exported = self.invoke("codex", GRAPH, "task", "--input", path, "--pm-id", pm)
            self.assertEqual(("prototype_only", "RUNNING"), (exported["request_scope"], exported["task"]["state"]))
            self.update("codex", self.locate("codex", name), {"set": {"state": "BUILD_VERIFIED"}}, code=2)
            if name == "checkout":
                # 同路径竞争者虽持自己原件的 SHA，公开 update 的 claim 补丁和手工
                # 删掉已占用任务的显式清单都不能替代真正的全池领取。
                rival = self.workspace / "rival.json"
                other = json.loads(path.read_bytes())
                other["task"].update(id="rival", state="DECLARED")
                other["task"].pop("claim_basis_sha256")
                other["task"].pop("claim_prior_state")
                rival.write_text(json.dumps(other), encoding="utf-8")
                expected = digest(rival)
                denied = self.invoke("codex", GRAPH, "update", "--input", rival, "--expect-sha256", expected,
                                     "--patch", "-", value={"tasks": {"rival": {"claim": {"previous_sha256": expected}}}},
                                     code=2)
                self.assertIn("registered task pool", denied["error"])
                self.assertEqual(expected, digest(rival))
                manifest = self.workspace / "incomplete.json"
                manifest.write_text(json.dumps({"schema_version": 1, "project_root": str(self.project),
                    "records": [{"path": str(rival), "sha256": expected, "execution_roots": {"rival": str(self.project)}}],
                    "capacity": {"configured_writers": 2, "configured_subagents": 2, "host_available_subagents": 2}
                }), encoding="utf-8")
                denied = self.invoke("codex", "lib/dispatch_admission_cli.py", "claim", "--input", manifest,
                                     "--record", rival, "--request-id", task["request_id"], "--task-id", "rival", code=2)
                self.assertIn("registered PM task pool", denied["error"])
                # 拷贝真正已领取的字节再登记自己，依然缺少本路径的冻结领取依据。
                rival.write_bytes(path.read_bytes())
                # 单独的 PM 索引承载人为导入的活跃副本，正常项目池继续保留两个
                # 独立任务的准确占用。既无权靠换 PM 导出，也不能借用原生 ID。
                other_pm = "codex:separate-session"
                self.invoke("codex", POOL, "register", "--root", self.project, "--pm-id", other_pm,
                            "--record", rival, "--expect-sha256", digest(rival))
                denied = self.invoke("codex", GRAPH, "task", "--input", rival, "--pm-id", other_pm, code=2)
                self.assertIn("recorded admission", denied["error"])
                denied = self.invoke("codex", GRAPH, "update", "--input", rival, "--expect-sha256", digest(rival),
                                     "--patch", "-", value={"tasks": {name: {"set": {"agent_ref": {
                                         "host": "codex", "agent_id": "unproven-id"}}}}}, code=2)
                self.assertIn("registered task pool", denied["error"])
            receipts.append(receipt_file)
            paths.append(path)

        def bind(index, native_id, code=0):
            return self.pool("codex", "bind", "--receipt", receipts[index], "--host", "codex",
                             "--agent-id", native_id, code=code)
        first = bind(0, "native-one")
        self.assertEqual(first, bind(0, "native-one"))
        # 相同的真实原件、领取回执及原生 ID 只在最初准入它的 PM 池中幂等。
        # 另一主会话事后登记同一原件，可报告状态，却不能生成自己的成功绑定回执。
        self.invoke("codex", POOL, "register", "--root", self.project, "--pm-id", other_pm,
                    "--record", paths[0], "--expect-sha256", digest(paths[0]))
        denied = self.invoke("codex", POOL, "bind", "--root", self.project, "--pm-id", other_pm,
                             "--receipt", receipts[0], "--host", "codex", "--agent-id", "native-one", code=2)
        self.assertIn("claim recorded by this PM pool", denied["error"])
        self.assertIn("already bound", bind(1, "native-one", code=2)["error"])
        second = bind(1, "native-two")
        # 回查、修订和撤回仍落同一个原件；其它已领取的独立任务不被停止或重派。
        self.update("codex", self.locate("codex", "checkout"), {"revise": {
            "set": {"goal": "checkout 增加空状态"}, "source": "user:补充空状态"}})
        self.update("codex", self.locate("codex", "settings"), {"withdraw": {"reason": "user:撤回设置页"}})
        self.assertEqual("STOP_REQUESTED", task_in(paths[1])["state"])
        self.update("codex", self.locate("codex", "settings"), {"confirm_stop": {
            "agent_ref": second["agent_ref"], "observed_state": "stopped", "source": "native:停止回执"}})
        self.assertEqual("WITHDRAWN", task_in(paths[1])["state"])
        row = self.locate("codex", "checkout")
        self.assertEqual(("RUNNING", first["agent_ref"], False),
                         (row["state"], row["agent_ref"], row["revision_acknowledged"]))
        # 同一设计实例接收最新范围，按原版号交回结果；另一个实例的撤回不妨碍
        # 本项完成。检查记录可通过自然语言标题恢复到实际绑定及交付态。
        latest = self.invoke("codex", GRAPH, "task", "--input", paths[0], "--pm-id", pm)["task"]
        delivery = {"revision": latest["task_revision"], "agent_ref": first["agent_ref"]}
        ack = self.update("codex", row, {"ack_revision": {**delivery, "delivery_source": "native:投递",
                                                          "ack_source": "native:同实例接收"}})
        self.update("codex", row, {"set": {"state": "BUILD_VERIFIED"},
                                   "revision_result": {**delivery, "source": "native:本版原型核验"}},
                    expected=ack["sha256"])
        completed = self.locate("codex", "checkout")
        self.assertEqual(("BUILD_VERIFIED", first["agent_ref"], True),
                         (completed["state"], completed["agent_ref"], completed["revision_result_recorded"]))

    def test_codex_discussion_recovery_and_revised_result(self):
        host = "codex"
        a = self.register(host, "a", "导出报表")
        row = self.locate(host, "报表")
        claim = self.claim(host, row)
        ref = {"host": host, "agent_id": "fixture-export-worker"}
        bound = self.update(host, row, {"set": {"agent_ref": ref}}, expected=claim["claimed_sha256"])

        # 「先讨论通知功能」应保持 A 在跑。用原 init 的生产任务负控证明即使误走建图，
        # 只讨论范围仍拒绝发布；随后重新查询任务池和整个项目/scratch 的真实字节。
        proposal = decisions()
        proposal["standards"]["leaves"] = proposal["standards"]["leaves"][:1]
        proposal["standards"]["required_engineering_rule_ids"] = ["eng-common-005"]
        proposal["tasks"][0]["selected_standards"] = [BUILTIN_ENGINEERING]
        before = project_files(self.workspace)
        rejected = self.invoke(host, GRAPH, "init", "--root", self.project, "--output", self.workspace / "b.json",
                               value={**proposal, "request_scope": "discussion_only"}, code=2)
        self.assertIn("discussion_only", rejected["error"])
        self.assertEqual([], self.pool(host, "view", "--query", "通知")["tasks"])
        self.assertEqual(before, project_files(self.workspace))
        row = self.locate(host, "报表")
        self.assertEqual(("RUNNING", bound["sha256"]), (row["state"], row["sha256"]))

        # 先留一份已经送达过的旧版回执，再修改一次。这样负控使用曾经有效的正整数
        # 版号、同一实例和真实通过回读的旧合同，拒绝原因不能只是伪造了零版号。
        first = self.update(host, row, {"revise": {"set": {"goal": "导出报表增加日期"},
                                                  "source": "user:fixture-add-date"}})
        older_version = task_in(a)["task_revision"]
        delivery = {"revision": older_version, "agent_ref": ref, "delivery_source": "native:fixture-send-v1",
                    "ack_source": "native:fixture-ack-v1"}
        first_ack = self.update(host, row, {"ack_revision": delivery}, expected=first["sha256"])
        revised = self.update(host, row, {"revise": {"set": {"goal": "导出报表增加日期列"},
                                                    "source": "user:fixture-separate-date-column"}},
                              expected=first_ack["sha256"])
        version = task_in(a)["task_revision"]
        received = self.invoke(host, GRAPH, "task", "--input", a, "--task-id", row["task_id"])
        self.assertEqual("导出报表增加日期列", received["task"]["goal"])
        self.assertEqual(version, received["task"]["task_revision"])
        completion = {"set": {"state": "BUILD_VERIFIED"}}
        # 旧 SHA 和伪装成当前 SHA 的旧结果都不能覆盖新合同。只有实际同一实例的
        # 新版接收与新版结果一起具备时，原 Writer 结果入口才可以发布。
        self.update(host, row, completion, code=2)
        current = {"revision": version, "agent_ref": ref, "source": "native:fixture-current-build"}
        self.update(host, row, {**completion, "revision_result": current}, expected=revised["sha256"], code=2)
        ack = self.update(host, row, {"ack_revision": {"revision": version, "agent_ref": ref,
                                "delivery_source": "native:fixture-send", "ack_source": "native:fixture-ack"}},
                          expected=revised["sha256"])
        old = {**current, "revision": older_version, "source": "native:fixture-old-build"}
        self.update(host, row, {**completion, "revision_result": old}, expected=ack["sha256"], code=2)
        self.assertEqual(ack["sha256"], digest(a))
        self.update(host, row, {**completion, "revision_result": current}, expected=ack["sha256"])
        self.assertEqual("BUILD_VERIFIED", task_in(a)["state"])

    def test_claude_withdrawal_keeps_unknown_claim_and_independent_work(self):
        host = "claude"
        a = self.register(host, "a", "导出报表")
        row = self.locate(host, "报表")
        claim = self.claim(host, row)
        receipt = self.workspace / "original-claim.json"
        receipt.write_text(json.dumps(claim), encoding="utf-8")
        b = self.register(host, "b", "修正通知文案", light=True)
        self.register(host, "c", "复用报表输出", owned=task_in(a)["owned_paths"][0])
        self.update(host, row, {"withdraw": {"reason": "用户撤回报表改动"}}, expected=claim["claimed_sha256"])

        # 宿主没有给出创建/停止结果时保留原回执。并行的 B 拿到自己的线程，依赖
        # A 输出路径的 C 仍须等待；即使换进程或只按名称查看也不能把 A 再领一次。
        retained = self.pool(host, "release", "--receipt", receipt, "--outcome", "unknown", *CAPACITY)
        self.assertEqual("retained", retained["status"])
        self.assertEqual("STOP_REQUESTED", task_in(a)["state"])
        before = a.read_bytes()
        admission = self.pool(host, "view", *CAPACITY)["admission"]
        self.assertEqual(1, admission["active_writers"])
        self.assertEqual(["b"], [item["request_id"] for item in admission["candidates"]])
        self.claim(host, self.locate(host, "修正通知"))
        self.assertEqual("RUNNING", task_in(b)["state"])
        self.claim(host, row, code=2)
        self.assertEqual(before, a.read_bytes())
        confirmed = self.pool(host, "release", "--receipt", receipt, "--outcome", "definitely_not_created", *CAPACITY)
        self.assertEqual("WITHDRAWN", confirmed["state"])
        self.assertEqual("WITHDRAWN", self.locate(host, "导出报表")["state"])

    def test_antigravity_two_legacy_records_and_pending_withdrawal(self):
        host = "antigravity"
        a = self.register(host, "a", "普通的全量交付")
        b = self.register(host, "b", "普通的小修改", light=True)
        withdrawn = self.register(host, "c", "取消的格式调整")
        row = self.locate(host, "格式调整")
        self.update(host, row, {"withdraw": {"reason": "用户撤回尚未开始的调整"}})
        self.assertEqual("WITHDRAWN", task_in(withdrawn)["state"])
        self.claim(host, self.locate(host, "格式调整"), code=2)
        # 两项原业务任务均不带改版字段。按描述找回、并行领取并通过原入口继续，
        # 不强行给旧合同增加接收回执。撤回或归档第三项只影响第三项。
        for path, title in ((a, "全量交付"), (b, "小修改")):
            self.assertNotIn("task_revision", task_in(path))
            row = self.locate(host, title)
            receipt = self.claim(host, row)
            file = self.workspace / (path.stem + "-receipt.json")
            file.write_text(json.dumps(receipt), encoding="utf-8")
            # 普通 Full 及 Light 同走实包首绑守卫。冒用角色名、改 --host，
            # 或使用无宿主证明的旧 update，均应原样保留 RUNNING 和原件字节。
            for other_host in ("antigravity", "codex"):
                expected = digest(path)
                denied = self.pool(host, "bind", "--host", other_host, "--agent-id", "xy-backend",
                                   "--receipt", file, code=2)
                self.assertIn("AGY", denied["error"])
                denied = self.update(host, row, {"set": {"agent_ref": {"host": other_host,
                                     "agent_id": "xy-backend"}}}, expected=expected, code=2)
                self.assertIn("AGY", denied["error"])
                self.assertEqual(expected, digest(path))
            self.claim(host, self.locate(host, title), code=2)
            self.assertEqual("RUNNING", task_in(path)["state"])
        c_bytes = withdrawn.read_bytes()
        self.pool(host, "archive", "--record", withdrawn, "--expect-sha256", digest(withdrawn))
        self.assertEqual(c_bytes, withdrawn.read_bytes())
        self.assertEqual({"a", "b"}, {item["request_id"] for item in self.pool(host, "view")["tasks"]})

    def test_antigravity_independent_qa_needs_bound_reviewer_and_natural_language_route(self):
        host = "antigravity"
        rules = (self.plugins[host] / "rules/AGENTS.md").read_text(encoding="utf-8")
        # 这里检查用户实际安装后由 AGY 自动加载的入口。其它宿主继续采用原模板。
        for term in ("自然语言", "即进入 xy-workflow", "明确授权继续有效", "invoke_subagent", "dispatch_marker",
                     "独立 QA 仍须真实 Reviewer", "纯讨论和显式维护"):
            self.assertIn(term, rules)
        for other in ("codex", "claude"):
            self.assertNotIn("dispatch_marker", (self.plugins[other] / "main-session-context.md").read_text())
        original = self.register(host, "writer", "原始实现", light=True)
        qa = self.workspace / "review.json"
        value = json.loads(original.read_bytes())
        task = value["task"]
        task.update(state="RUNNING", task_type="qa", role="xy-qa")
        row = {"record": str(qa), "task_id": task["id"]}
        for historical_ref in (None, {"host": host, "agent_id": "xy-qa"}):
            if historical_ref:
                task["agent_ref"] = historical_ref
            qa.write_text(json.dumps(value), encoding="utf-8")
            row["sha256"] = digest(qa)
            self.invoke(host, GRAPH, "validate", "--input", qa)
            error = self.update(host, row, {"set": {"state": "QA_PASSED"}}, code=2)
            self.assertIn("native-bound Reviewer", error["error"])
            self.assertEqual(row["sha256"], digest(qa))

    def test_non_antigravity_packages_validate_native_history_without_native_modules(self):
        host = "antigravity"
        original = self.register(host, "history", "已有 AGY 任务", light=True)
        claim = self.claim(host, self.locate(host, "已有 AGY 任务"))
        self.assertIn("dispatch_marker", claim)
        value = json.loads(original.read_bytes())
        task = value["task"]
        child = str(uuid4())
        task["agent_ref"] = {"host": host, "agent_id": child}
        original.write_text(json.dumps(value), encoding="utf-8")
        before = original.read_bytes()

        # 使用同一个在途旧格式原件。从两个独立包真实运行核验及恢复，
        # 即使没有 AGY 解释器也要识别任务占用和有效身份，并拒绝相同父子 UUID。
        modules = ("lib/hosts/antigravity_dispatch.py", "lib/hosts/antigravity_handoff.py", "hooks/write_guard.py")
        for other in ("codex", "claude"):
            with self.subTest(host=other):
                self.assertTrue(all(not (self.plugins[other] / name).exists() for name in modules))
                self.assertEqual("valid", self.invoke(other, GRAPH, "validate", "--input", original)["status"])
                self.pool(other, "register", "--record", original, "--expect-sha256", digest(original),
                          "--title", "已有 AGY 任务")
                row = self.locate(other, "已有 AGY 任务")
                self.assertEqual(("RUNNING", True, child), (row["state"], row["active"], row["agent_ref"]["agent_id"]))
                self.assertEqual(before, original.read_bytes())
                try:
                    task["agent_ref"]["agent_id"] = task["antigravity_claim"]["parent"]
                    original.write_text(json.dumps(value), encoding="utf-8")
                    invalid = self.invoke(other, GRAPH, "validate", "--input", original, code=2)
                    self.assertIn("child conversation UUID", invalid["error"])
                finally:
                    task["agent_ref"]["agent_id"] = child
                    original.write_bytes(before)

    def test_antigravity_light_example_validates_and_claims_from_the_installed_guide(self):
        host = "antigravity"
        installed = self.plugins[host]
        guide = (installed / "skills/xy-workflow/references/dispatch.md").read_text(encoding="utf-8")
        section = guide.split('<a id="light-non-ui-pack"></a>', 1)[1]
        template = section.split("```json\n", 1)[1].split("\n```", 1)[0]
        # 读实际装配的发现入口及当前包提供的规范摘要。这里只替换文档明确标出的槽，
        # 不从测试 fixture 拼任务字段，这样模板缺字段、相对链接或规范路径失效都会暴露。
        relative = json.loads(template)["standards_contract"]["leaves"][0]["path"]
        resource = subprocess.run(["bash", str(installed / "lib/python_runtime.sh"), "-B", "-X", "utf8",
                                   str(installed / "plugins/source_pack.py"), "resource", relative],
                                  cwd=self.project, env=self.env, text=True, capture_output=True, timeout=30)
        self.assertEqual(0, resource.returncode, resource.stderr)
        pack = json.loads(template.replace("<rules-sha256>", json.loads(resource.stdout)["sha256"]))
        pack["task"]["input_contracts"] = ["测试用户明确委托修复 total([]) 并覆盖回归。"]
        path = self.workspace / "total.json"
        def claim(code):
            return self.pool(host, "claim", "--register", "--record", path, "--request-id", pack["task"]["request_id"],
                             "--task-id", pack["task"]["id"], "--expect-sha256", digest(path), *CAPACITY, code=code)
        self.assertEqual([], pack["approved_gates"])
        path.write_text(json.dumps(pack, ensure_ascii=False), encoding="utf-8")
        self.assertIn("approvals", claim(2)["error"])
        pack["approved_gates"] = ["requirements_approved"]
        path.write_text(json.dumps(pack, ensure_ascii=False), encoding="utf-8")
        self.assertEqual("valid", self.invoke(host, GRAPH, "validate", "--input", path)["status"])
        result = claim(0)
        self.assertEqual("claimed", result["status"])
        self.assertRegex(result["dispatch_marker"], r"^XY-WORKFLOW-CLAIM [0-9a-f]{64}$")

    def agy_log(self, identifier, *events, short_events=None):
        location = self.workspace / "brain" / identifier / ".system_generated" / "logs"
        location.mkdir(parents=True, exist_ok=True)
        for name, rows in (("transcript.jsonl", events if short_events is None else short_events),
                           ("transcript_full.jsonl", events)):
            body = "".join(json.dumps(event, ensure_ascii=False) + "\n" for event in rows)
            (location / name).write_text(body, encoding="utf-8")
        return location / "transcript_full.jsonl"

    def hook_decision(self, transcript, tool, args, user="请直接修改并验证", *, with_reason=False):
        plugin = self.plugins["antigravity"]
        # 唯一替身是临时宿主 brain 物理根；保留实际包内 stdin/stdout 入口、原生
        # 结构校验、工作区外安装路径、任务池状态、执行目录和子会话识别的完整链路。
        entry = (
            "from pathlib import Path\nimport sys,runpy\n"
            "sys.path.insert(0, sys.argv[1])\nfrom lib.hosts import antigravity_dispatch\n"
            "antigravity_dispatch._brain = lambda: Path(sys.argv[2])\n"
            "runpy.run_path(str(Path(sys.argv[1])/'hooks/write_guard.py'), run_name='__main__')\n"
        )
        event = {"toolCall": {"name": tool, "args": args}, "conversationId": transcript.parents[2].name,
                 "transcriptPath": str(transcript), "lastUserInput": user, "workspacePaths": [str(self.project)],
                 "cwd": str(plugin)}
        result = subprocess.run(
            ["bash", str(plugin / "lib/python_runtime.sh"), "-I", "-B", "-c", entry, str(plugin),
             str(self.workspace / "brain")], cwd=plugin, env=self.env, input=json.dumps(event),
            capture_output=True, text=True, timeout=20,
        )
        self.assertEqual(0, result.returncode, result.stderr)
        value = json.loads(result.stdout)
        self.assertLessEqual(set(value), {"decision", "reason"})
        return value if with_reason else value["decision"]

    def test_antigravity_pretool_pm_current_request_and_preparation(self):
        pm = self.agy_pm.split(":")[1]
        start = {"step_index": 0, "source": "USER_EXPLICIT", "type": "USER_INPUT", "status": "DONE"}
        log = self.agy_log(pm, start)
        plugin = self.plugins["antigravity"]
        manifest = json.loads((plugin / "hooks.json").read_bytes())
        self.assertIn("write_guard.py", manifest["xy-workflow-write-ownership"]["PreToolUse"][0]["hooks"][0]["command"])
        for other in ("codex", "claude"):
            self.assertFalse((self.plugins[other] / "hooks.json").exists())
            self.assertFalse((self.plugins[other] / "hooks/write_guard.py").exists())
        scratch = Path(self.invoke("antigravity", GRAPH, "scratch", "--root", self.project,
                                   "--request-id", "pm-guard")["scratch_dir"])
        self.assertEqual(self.project / ".awf/agy-requests", scratch.parent)
        subprocess.run(["git", "init", "-q", str(self.project)], check=True, env=self.env)
        self.assertEqual(0, subprocess.run(["git", "check-ignore", "-q", str(scratch / "task.json")],
                                           cwd=self.project, env=self.env).returncode)
        target = scratch / "task.json"
        source_pack = f"bash {plugin}/lib/python_runtime.sh -B -X utf8 {plugin}/plugins/source_pack.py"
        prefix = f"{source_pack} helper --project {self.project}"
        helper = f"{prefix} {GRAPH}"
        usage = f"{prefix} lib/delivery/native_usage.py --host antigravity"
        prototype = f"{prefix} lib/documents/validate_prototype_workspace.py"
        feedback = f"{prefix} lib/documents/prototype_feedback_cli.py"
        worktree = f"{prefix} lib/delivery/worktree_cli.py"
        capabilities = f"{prefix} lib/hosts/capabilities.py --platform antigravity"
        git_show = "git --no-pager --no-lazy-fetch show --no-ext-diff --no-textconv"
        outside = self.workspace / "outside-private"
        subprocess.run(["git", "init", "-q", str(outside)], check=True, env=self.env)
        for command, result in (
                ("pwd", "allow"), ("git log -n 5 --oneline && git status", "allow"),
                (f"git --no-pager -C {self.project} status --short", "allow"),
                ("git -C src status --short", "allow"),
                ("rg -n total src | head -n 30", "allow"), ("git status && touch src/no.txt", "deny"),
                ("find . -maxdepth 3 -type f -name '*dispatch*'", "allow"),
                ("find . -name '*.py' -delete", "deny"), ("find . -name *dispatch*", "deny"),
                (r"rg -n '\btotal\b' --no-ignore --max-depth 2 --glob '*.py' src 2>/dev/null", "allow"),
                ("rg --files --max-depth=2 --glob='*.py' --no-ignore", "allow"),
                (r"rg -n \btotal src 2>/dev/null", "deny"),
                (r'rg -n "\btotal" src 2>/dev/null', "deny"),
                ("rg --max-depth --no-ignore src", "deny"), ("rg --glob *.py src", "deny"),
                ("rg --no-ignore --pre touch src", "deny"),
                ("rg total src 2>/dev/null && touch src/no.txt", "deny"),
                ("rg total src 2>src/fixture.txt", "deny"), ("rg total src 1>/dev/null", "deny"),
                ("rg total src 2>/dev/null > src/no.txt", "deny"),
                ("rg total src & 2>/dev/null", "deny"), ("git show HEAD", "deny"),
                ("git --no-pager show --no-ext-diff --no-textconv HEAD", "deny"),
                (f"{git_show} HEAD:README.md", "allow"),
                ("git --no-pager --no-lazy-fetch -C src show --no-ext-diff --no-textconv HEAD", "allow"),
                (f"{git_show} --output=src/fixture.txt HEAD", "deny"),
                ("git -c core.pager=cat --no-pager --no-lazy-fetch show --no-ext-diff --no-textconv HEAD", "deny"),
                ("GIT_NO_LAZY_FETCH=1 git --no-pager show --no-ext-diff --no-textconv HEAD", "deny"),
                (f"{capabilities} ", "allow"), (f"{capabilities} --probe-version", "deny"),
                (f"{usage} --input {target} --input usage.jsonl", "allow"),
                (f"{usage} --input {self.workspace}/another-session.json", "deny"),
                (f"{usage} --input usage.jsonl --output arbitrary.log", "deny"),
                (f"{prototype} {self.project} ui --standalone --adapter project.yaml "
                 "--page first.html --page second.html --json", "allow"),
                (f"{prototype} {self.workspace} ui --json", "deny"),
                (f"{prototype} {self.project} ../ui --json", "deny"),
                (f"{feedback} status --root {self.project} --request-id current", "allow"),
                (f"{feedback} status --root {self.workspace} --request-id current", "deny"),
                (f"{feedback} status --root {self.project} --request-id current --data-dir {self.workspace}", "deny"),
                (f"{feedback} validate --root {self.project} --adapter project.yaml --input {target}", "allow"),
                (f"{feedback} migration-preview --root {self.project} --adapter project.yaml --plan docs/plans/a.md "
                 "--pages ui/a.html ui/b.html --request-id current", "allow"),
                (f"{feedback} migration-preview --root {self.project} --adapter project.yaml "
                 "--plan docs/plans/a.md --request-id current --confirm-no-active-use", "deny"),
                (f"{feedback} stop --root {self.project} --request-id current", "deny"),
                (f"{feedback} prepare-delivery --root {self.project} --adapter project.yaml --pages ui/a.html", "deny"),
                (f"{worktree} target --repo {self.project} --config project.yaml", "allow"),
                (f"{worktree} inspect --repo {self.project} --base {'0' * 40} --head {'1' * 40}", "allow"),
                (f"{worktree} inspect --repo {self.workspace} --base base --head head", "deny"),
                (f"{worktree} merge-ready --repo {self.project} --config project.yaml --input {target}", "deny"),
                (f"{worktree} create --repo {self.project} --path {self.workspace}/new --base HEAD", "deny"),
                (f"{source_pack} selected-skills check", "allow"),
                (f"{source_pack} xy-web-guidance -- search 'dialog keyboard'", "allow"),
                (f"{source_pack} xy-web-guidance -- install", "deny"),
                (f"{source_pack} apple-skills check", "allow"),
                (f"{source_pack} apple-skills check --developer-dir {self.workspace}", "deny"),
                (f"{source_pack} xy-playwright -- open http://localhost:1234", "deny"),
                (f"{prefix} lib/delivery/qa_handoff_cli.py schema --output {target}", "deny"),
                ("mkdir -p docs/plans", "allow"),
                ("git diff --output=src/other.txt", "deny"), ("echo changed > src/fixture.txt", "deny"),
                ("python3 -c 'print(1)'", "deny"), ("mkdir -p src/new", "deny"),
                (f"{helper} task --input {target} --task-id api > {scratch}/export.json", "allow"),
                (f"{helper} task --input {target} --task-id api --output {self.project}/src/fixture.txt", "deny"),
                (f"{helper} task --input {target} --task-id api --output {scratch}/../outside.json", "deny")):
            with self.subTest(command=command):
                self.assertEqual(result, self.hook_decision(log, "run_command", {"CommandLine": command}))
        for tool, args, reason in (
                ("run_command", {"CommandLine": "git add src/private.txt"}, "拒绝此命令形式"),
                ("write_file", {"Path": str(self.workspace / "private.txt")}, "目标路径"),
                ("write_file", {"Path": "src/private.txt"}, "未找到 PM")):
            outcome = self.hook_decision(log, tool, args, with_reason=True)
            self.assertEqual("deny", outcome["decision"])
            self.assertIn(reason, outcome["reason"])
            self.assertNotIn("private.txt", outcome["reason"])
        # 路径越界与命令形态失败分别报告。现有 Git 查询、复合只读命令、
        # 终端 Cwd 与 helper 的二次选根都经相同的脱敏路径拒绝分支。
        for details in (
                {"CommandLine": f"git --no-pager -C {outside} status"},
                {"CommandLine": f"pwd && git -C {outside} diff --stat"},
                {"CommandLine": "git -C ../outside-private log --oneline"},
                {"CommandLine": f"git --no-pager --no-lazy-fetch -C {outside} "
                                "show --no-ext-diff --no-textconv HEAD"},
                {"CommandLine": "pwd", "Cwd": str(outside)},
                {"CommandLine": "pwd", "Cwd": "../outside-private"},
                {"CommandLine": f"{source_pack} helper --project {outside} lib/hosts/capabilities.py "
                                "--platform antigravity"},
                {"CommandLine": f"{worktree} target --repo {outside}"},
                {"CommandLine": f"{prototype} {outside} ui --json"},
                {"CommandLine": f"{usage} --input {outside}/usage-private.json"}):
            with self.subTest(details=details):
                outcome = self.hook_decision(log, "run_command", details, with_reason=True)
                self.assertEqual("deny", outcome["decision"])
                self.assertIn("目标路径的工作区归属", outcome["reason"])
                self.assertNotIn("outside-private", outcome["reason"])
                self.assertNotIn("usage-private.json", outcome["reason"])
                self.assertNotIn(details["CommandLine"], outcome["reason"])
        for path, prompt, result in (
                (str(target), "准备任务包", "allow"), (str(scratch / "test_payload.py"), "准备任务包", "deny"),
                ("docs/plans/release.md", "准备计划", "allow"),
                ("docs/PROJECT.md", "整理索引", "allow"), ("src/fixture.txt", "这次由主会话亲自改", "allow"),
                ("src/fixture.txt", "请 PM 本人直接修改 src/fixture.txt，参考 README.md。", "allow"),
                ("README.md", "请 PM 本人直接修改 src/fixture.txt，参考 README.md。", "deny"),
                (".git/config", "这次由主会话亲自改", "deny"),
                ("src/fixture.txt", "例如“这次由主会话亲自改”", "deny"),
                ("Makefile", "这次由主会话亲自改 Makefile\n然后运行 test_labels.py", "allow"),
                ("other.txt", "这次由主会话亲自改 Makefile\n然后运行 test_labels.py", "deny"),
                ("Makefile", "这次由主会话亲自改\n目标文件：Makefile\n验证输出是“ok”。", "allow"),
                ("src/fixture.txt", "请 PM 本人修改 src/fixture.txt\n运行 test_labels.py", "allow"),
                ("Makefile", "如果验收失败，再执行下面的指令\n这次由主会话亲自改 Makefile", "deny"),
                ("Makefile", "这次由主会话亲自改 Makefile\n前提是用户另行批准。", "deny"),
                ("Makefile", "这次由主会话亲自改 Makefile\n如果测试失败才修改。", "deny"),
                ("Makefile", "这次由主会话亲自改 Makefile。\n运行 test_labels.py；如果测试失败，请报告结果。", "allow"),
                ("客户与订单.md", "请 PM 本人直接修改 客户与订单.md", "allow"),
                ("订单.md", "请 PM 本人直接修改 客户与订单.md", "deny"),
                ("客户", "请 PM 本人直接修改 客户与订单.md", "deny"),
                ("文件管理.py", "请 PM 本人直接修改 文件管理.py", "allow"),
                ("管理.py", "请 PM 本人直接修改 文件管理.py", "deny"),
                ("文件管理.py", "这次由主会话亲自改\n文件管理.py", "allow"),
                ("管理.py", "这次由主会话亲自改\n文件管理.py", "deny"),
                ("客户以及订单.md", "请 PM 本人直接修改 客户和地址.md、客户以及订单.md", "allow"),
                ("地址.md", "请 PM 本人直接修改 客户和地址.md、客户以及订单.md", "deny"),
                ("src/fixture.txt", "请不要让 PM 本人直接修改 src/fixture.txt", "deny"),
                ("src/fixture.txt", "继续修复，可以直接修改", "deny")):
            with self.subTest(prompt=prompt, path=path):
                self.assertEqual(result, self.hook_decision(log, "write_file", {"Path": path}, prompt))
        prompt = "这次由主会话亲自改 labels.py 并运行 test_labels.py"
        for file, expected in (("labels.py", "allow"), ("test_labels.py", "deny")):
            self.assertEqual(expected, self.hook_decision(log, "edit_file", {"Path": file}, prompt))
        for file, expected in (("test_labels.py", "allow"), ("test_other.py", "deny")):
            self.assertEqual(expected, self.hook_decision(log, "run_command", {"CommandLine": "python3 " + file}, prompt))
        launcher = f"bash {plugin}/plugins/maintenance/launcher.sh"
        for user, action, expected in (("/xy-config doctor", "doctor", "allow"), ("/xy-config", "open", "allow"),
                                       ("/xy-config status", "open", "deny"), ("修复 /xy-config status", "status", "deny")):
            command = f"{launcher} {action} --host antigravity --project {self.project}"
            self.assertEqual(expected, self.hook_decision(log, "run_command", {"CommandLine": command}, user))
        # 准备组件需要同一项 open 的真实回执及当前明确同意。普通打开和冒用旧同意均不能批准。
        open_cmd = f"{launcher} open --host antigravity --project {self.project}"
        prepare = {"CommandLine": open_cmd + " --prepare"}
        self.assertEqual("deny", self.hook_decision(log, "run_command", prepare, "/xy-config open"))
        invocation = {**start, "content": "<USER_REQUEST>/xy-config open</USER_REQUEST>"}
        consent = {**start, "content": "<USER_REQUEST>同意准备组件</USER_REQUEST>"}
        events = [invocation, {"source": "MODEL", "type": "PLANNER_RESPONSE", "tool_calls": [
            {"name": "run_command", "args": {"CommandLine": open_cmd}}]},
                  {"source": "MODEL", "type": "GENERIC", "content": '{"state":"preparation_required"}'}, consent]
        self.agy_log(pm, *events)
        self.assertEqual("allow", self.hook_decision(log, "run_command", prepare, "同意准备组件"))
        self.agy_log(pm, *events, consent)
        self.assertEqual("deny", self.hook_decision(log, "run_command", prepare, "同意准备组件"))
        # 文件系统别名不能把默认可写计划或临时交接输出指向业务文件。
        linked = scratch / "linked.json"
        linked.symlink_to(self.project / "src/fixture.txt")
        self.assertEqual("deny", self.hook_decision(log, "edit_file", {"Path": str(linked)}))
        self.assertEqual("deny", self.hook_decision(log, "run_command", {"CommandLine":
            f"{helper} task --input {target} --task-id api --output {linked}"}))
        self.assertEqual("deny", self.hook_decision(log, "run_command", {"CommandLine": f"{usage} --input {linked}"}))

    def test_antigravity_pretool_writer_before_binding_and_read_only_role(self):
        host = "antigravity"
        pm = self.agy_pm.split(":")[1]
        path = self.register(host, "changes", "修正", light=True, owned="src/fixture.txt")
        # 和项目发现器使用相同的真实清单入口，核对登记命令、模块 cwd 与实际终端
        # 是否一致。这些仅为守卫入参，不在开发机上安装或执行 Gradle/Xcode 等工具。
        manifests = {"build.gradle.kts": 'plugins { id("java") }', "gradlew": "#!/bin/sh\n",
                     "api/pyproject.toml": '[project]\nname="api"\nversion="1"\ndependencies=["pytest"]',
                     "api/uv.lock": "version = 1\n",
                     "jobs/pyproject.toml": '[tool.poetry]\nname="jobs"\nversion="1"\n[tool.poetry.group.dev.dependencies]\npytest="^9"',
                     "jobs/poetry.lock": "package = []\n",
                     "ios/App.xcodeproj/project.pbxproj": ('// !$*UTF8*$!\n{\n objects = {\n A1 = {\n isa = PBXNativeTarget;\n'
                                                          ' productType = "com.apple.product-type.application";\n };\n };\n}\n'),
                     "ios/App.xcodeproj/xcshareddata/xcschemes/App.xcscheme": '<Scheme version="1.7"/>'}
        for relative, body in manifests.items():
            file = self.project / relative
            file.parent.mkdir(parents=True, exist_ok=True)
            file.write_text(body, encoding="utf-8")
        checks = ["python3 test_total.py", "./gradlew test", "uv run pytest", "poetry run pytest",
                  "xcodebuild -scheme App build", "python3 -c 'print(1)'"]
        self.update(host, self.locate(host, "修正"), {"set": {"verification_commands": checks}})
        claim = self.claim(host, self.locate(host, "修正"))
        marker = claim["dispatch_marker"]
        child = str(uuid4())
        child_log = self.agy_log(child, {
            "step_index": 0, "source": "SYSTEM", "type": "SYSTEM_MESSAGE", "status": "DONE",
            "content": "\n<SYSTEM_MESSAGE>\n[Message] timestamp=2026-11-20T10:01:46Z sender=" + pm
                       + " priority=MESSAGE_PRIORITY_HIGH content=" + marker + "\n实现当前任务\n</SYSTEM_MESSAGE>",
        })
        def dispatch(role, receipt_fields=None):
            # 真长提示词在 1.5.13 的短日志中丢失独立标记。Hook 必须使用完整日志
            # 的原始字符串参数，且创建回执里的子 URI 仍按短日志定位。
            call = {"name": "invoke_subagent", "args": {"TypeName": role, "Prompt": "完整任务包\n" * 1200 + marker}}
            receipt = {"conversationId": child, "logAbsoluteUri": child_log.with_name("transcript.jsonl").as_uri(),
                       "workspaceUris": [self.project.as_uri()]}
            start = {"step_index": 0, "source": "USER_EXPLICIT", "type": "USER_INPUT", "status": "DONE"}
            planner = {"step_index": 1, "source": "MODEL", "status": "DONE",
                       "type": "PLANNER_RESPONSE", "tool_calls": [call]}
            short = {**planner, "truncated_fields": ["tool_calls"],
                     "tool_calls": [{"name": "invoke_subagent", "args": {"TypeName": json.dumps(role),
                                                                         "Prompt": json.dumps("完整任务包")}}]}
            created = {"step_index": 2, "source": "MODEL", "status": "DONE", "type": "GENERIC",
                       "content": "Created the following subagent:\n" + json.dumps(receipt)
                       + "\nThe subagent will send you a message when it has completed its task or requires guidance. "
                         "There is no need to poll for its response."}
            if receipt_fields is not None:
                created["truncated_fields"] = receipt_fields
            return self.agy_log(pm, start, planner, created, short_events=(start, short, created))
        parent_log = dispatch("xy-backend")
        self.assertNotIn("agent_ref", task_in(path))
        self.assertEqual("allow", self.hook_decision(child_log, "edit_file", {"Path": "src/fixture.txt"}))
        violation = self.hook_decision(child_log, "edit_file", {"Path": "src/other.txt"}, with_reason=True)
        self.assertEqual("deny", violation["decision"])
        self.assertIn("已核对实现派发", violation["reason"])
        for current in (parent_log, child_log):
            self.assertEqual("allow", self.hook_decision(current, "run_command", {"CommandLine": "python3 test_total.py"}))
            self.assertEqual("allow", self.hook_decision(current, "run_command", {"CommandLine": "python -B test_total.py"}))
            self.assertEqual("deny", self.hook_decision(current, "run_command", {"CommandLine": "python3 test_other.py"}))
            for cmd, subdir, allowed in (("./gradlew test", ".", "allow"), ("uv run pytest", "api", "allow"),
                                         ("poetry run pytest", "jobs", "allow"), ("xcodebuild -scheme App build", "ios", "allow"),
                                         ("uv run pytest", "jobs", "deny"), ("./gradlew build", ".", "deny"),
                                         ("python3 -c 'print(1)'", ".", "deny")):
                with self.subTest(actor=current, command=cmd, directory=subdir):
                    self.assertEqual(allowed, self.hook_decision(current, "run_command", {
                        "CommandLine": cmd, "Cwd": str(self.project / subdir)}))
        for role, receipt_fields in (("xy-backend", ["content"]), ("xy-qa", None)):
            dispatch(role, receipt_fields)
            refusal = self.hook_decision(child_log, "edit_file", {"Path": "src/fixture.txt"},
                                         "这次由主会话亲自改", with_reason=True)
            self.assertEqual("deny", refusal["decision"])
            self.assertIn("无法核对当前子会话的可写派发", refusal["reason"])
        self.assertEqual("allow", self.hook_decision(child_log, "run_command", {"CommandLine": "git diff --stat"}))
        # 宿主声明摘要变化后，原生入口应回有效 deny，包括原来无需解析会话的状态查询。
        definition = self.plugins[host] / "hooks.json"
        original_definition = definition.read_bytes()
        try:
            definition.write_bytes(original_definition + b"\n")
            self.assertEqual("deny", self.hook_decision(child_log, "manage_task", {"Action": "status"}))
        finally:
            definition.write_bytes(original_definition)
