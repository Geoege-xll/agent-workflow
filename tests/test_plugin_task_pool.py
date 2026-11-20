"""三宿主离线包的持续接单回归。主会话判断用户意图后，通过真实包内入口操作原记录。"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
import tempfile
import unittest

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
        return self.invoke(host, POOL, command, "--root", self.project, "--pm-id", host + ":main-session",
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
            self.claim(host, row)
            self.claim(host, self.locate(host, title), code=2)
            self.assertEqual("RUNNING", task_in(path)["state"])
        c_bytes = withdrawn.read_bytes()
        self.pool(host, "archive", "--record", withdrawn, "--expect-sha256", digest(withdrawn))
        self.assertEqual(c_bytes, withdrawn.read_bytes())
        self.assertEqual({"a", "b"}, {item["request_id"] for item in self.pool(host, "view")["tasks"]})
