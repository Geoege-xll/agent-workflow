"""三宿主离线包的持续接单回归。主会话判断用户意图后，通过真实包内入口操作原记录。"""

from __future__ import annotations

import copy
import hashlib
import http.client
import json
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import tempfile
import unittest
from urllib.parse import urlsplit
from urllib.request import urlopen
from uuid import uuid4

from tests.test_conversation_scope import project_files
from tests.test_dispatch_admission import plugin_helper
from tests.test_plugin_delivery import PACK, builder, isolated_environment
from tests.test_task_graph_init import ADAPTER, BUILTIN_ENGINEERING, decisions
from tests.test_task_graph_records import graph


POOL = "lib/task_pool_cli.py"
GRAPH = "lib/task_graph_cli.py"
FEEDBACK = "lib/documents/prototype_feedback_cli.py"
PROTOTYPE = "lib/documents/validate_prototype_workspace.py"
WORKTREE = "lib/delivery/worktree_cli.py"
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

    def codex_hook(self, transcript, tool, command, *, actor=None, turn="current", cwd=None):
        plugin = self.plugins["codex"]
        hooks = json.loads((plugin / "hooks/hooks.json").read_bytes())["hooks"]
        handler = hooks["PreToolUse"][0]["hooks"][0]["command"].replace("${PLUGIN_ROOT}", str(plugin))
        event = {"hook_event_name": "PreToolUse", "tool_name": tool, "tool_input": {"command": command},
                 "session_id": "main-session", "turn_id": turn, "cwd": str(cwd or self.project),
                 "transcript_path": str(transcript)}
        if actor:
            event["agent_id"] = actor
        raw = subprocess.run(shlex.split(handler), input=json.dumps(event), env=self.env, cwd=self.workspace,
                             capture_output=True, text=True, timeout=15)
        self.assertEqual(0, raw.returncode, raw.stderr)
        output = json.loads(raw.stdout)
        return output.get("hookSpecificOutput", {}).get("permissionDecision", "allow")

    def codex_rollout(self, name, *, agent_path=None, user=None, item_type="UserMessage", cwd=None):
        path = self.workspace / (name + ".jsonl")
        metadata = {"id": name, "cwd": str(cwd or self.project), "source": "cli"}
        if agent_path:
            metadata.update(agent_path=agent_path, source={"subagent": {"thread_spawn": {
                "depth": 1, "parent_thread_id": "main-session", "agent_path": agent_path,
                "agent_nickname": "writer", "agent_role": "xy-backend",
            }}})
        entries = [{"type": "session_meta", "payload": metadata}]
        if user:
            entries.append({"type": "event_msg", "payload": {"type": "item_completed", "turn_id": "current",
                "thread_id": name, "item": {"type": item_type, "content": [{"type": "text", "text": user}]}}})
        path.write_text("".join(json.dumps(entry, ensure_ascii=False) + "\n" for entry in entries))
        return path

    def test_codex_write_ownership_uses_current_native_task_and_user_item(self):
        host, request = "codex", "guarded"
        path = self.register(host, request, request, light=True, owned="src/fixture.txt")
        compile_command = "python3 -m py_compile src/runtime_check.py"
        (self.project / "src/runtime_check.py").write_text("answer = 42\n")
        source = json.loads(path.read_bytes())
        source["task"]["verification_commands"] = [compile_command]
        path.write_text(json.dumps(source))
        pm = self.codex_rollout("main-session", user="实现当前功能")
        child = self.codex_rollout("writer-thread", agent_path="/root/guarded")
        reviewer = self.codex_rollout("review-thread", agent_path="/root/review")
        patch = "*** Begin Patch\n*** Add File: src/fixture.txt\n+content\n*** End Patch"
        move = "*** Begin Patch\n*** Update File: src/fixture.txt\n*** Move to: src/peer.txt\n@@\n-old\n+new\n*** End Patch"
        self.assertEqual("deny", self.codex_hook(pm, "apply_patch", patch))
        self.assertEqual("deny", self.codex_hook(pm, "Bash", "printf '%s' content > src/fixture.txt"))
        self.assertEqual("allow", self.codex_hook(pm, "Bash", "rg -n fixture src && git diff --stat"))
        self.assertEqual("allow", self.codex_hook(pm, "Bash", "pwd\ngit status --short\nrg --files src"))
        self.assertEqual("deny", self.codex_hook(pm, "Bash", "pwd\nprintf '%s' content > src/fixture.txt"))
        self.assertEqual("allow", self.codex_hook(pm, "apply_patch",
            "*** Begin Patch\n*** Add File: docs/plans/fixture.md\n+# Plan\n*** End Patch"))
        scratch = self.invoke(host, GRAPH, "scratch", "--root", self.project, "--request-id", request)["scratch_dir"]
        plugin = self.plugins[host]
        graph_command = ["bash", str(plugin / "lib/python_runtime.sh"), "-B", "-X", "utf8",
                         str(plugin / "plugins/source_pack.py"), "helper", "--project", str(self.project), GRAPH]
        self.assertEqual("allow", self.codex_hook(pm, "Bash", shlex.join([
            *graph_command, "scratch", "--root", str(self.project), "--request-id", request])))
        self.assertEqual("allow", self.codex_hook(pm, "Bash", f"cat > {scratch}/candidate.json <<'JSON'\n{{}}\nJSON"))
        self.assertEqual("deny", self.codex_hook(child, "apply_patch", patch, actor="writer-thread"))

        claim_file = self.workspace / "claim.json"
        claim_file.write_text(json.dumps(self.claim(host, self.locate(host, request))))
        self.pool(host, "bind", "--host", host, "--agent-id", "/root/guarded", "--receipt", claim_file)
        self.assertEqual("allow", self.codex_hook(child, "apply_patch", patch, actor="writer-thread"))
        self.assertEqual("allow", self.codex_hook(child, "Bash", compile_command, actor="writer-thread"))
        self.assertEqual("deny", self.codex_hook(reviewer, "Bash", compile_command, actor="review-thread"))
        self.assertEqual("allow", self.codex_hook(child, "Bash", "printf '%s' content > src/fixture.txt",
                                                 actor="writer-thread"))
        self.assertEqual("deny", self.codex_hook(child, "apply_patch", move, actor="writer-thread"))
        self.assertEqual("deny", self.codex_hook(reviewer, "apply_patch", patch, actor="review-thread"))
        self.assertEqual("deny", self.codex_hook(reviewer, "apply_patch", patch, actor="writer-thread"))

        pm = self.codex_rollout("main-session", user="请 PM 本人直接修改 src/fixture.txt")
        self.assertEqual("allow", self.codex_hook(pm, "apply_patch", patch))
        self.assertEqual("deny", self.codex_hook(pm, "apply_patch", move))
        self.assertEqual("deny", self.codex_hook(pm, "apply_patch", patch, turn="next"))
        pm = self.codex_rollout("main-session", user="PM 自己修改 src/fixture.txt", item_type="HookPrompt")
        self.assertEqual("deny", self.codex_hook(pm, "apply_patch", patch))

        before = path.read_bytes()
        row = self.locate(host, request)
        self.update(host, row, {"withdraw": {"reason": "user requested stop"}})
        self.assertNotEqual(before, path.read_bytes())
        self.assertEqual("deny", self.codex_hook(child, "apply_patch", patch, actor="writer-thread"))

    def test_packaged_closeout_keeps_evidence_and_uses_scratch_snapshot(self):
        host, request = "codex", "closing"
        original = self.register(host, request, request, light=True)
        pm = "codex:main-session"
        report = self.pool(host, "closeout", "--request-id", request)
        self.assertEqual("request_contains_unaccepted_work", report["reason"])
        receipt_path = self.workspace / "claim.json"
        receipt_path.write_text(json.dumps(self.claim(host, self.locate(host, request))))
        agent = {"host": host, "agent_id": "/root/closing"}
        self.pool(host, "bind", "--host", host, "--agent-id", agent["agent_id"], "--receipt", receipt_path)
        self.update(host, self.locate(host, request), {"set": {"state": "BUILD_VERIFIED"}})

        scratch = Path(self.invoke(host, GRAPH, "scratch", "--root", self.project, "--request-id", request)["scratch_dir"])
        proof, log, unused = (scratch / name for name in ("preserved.json", "native.log", "regenerable.txt"))
        log.write_text("verified native close and delivery evidence")
        deliverable = self.workspace / "actual-result.bin"
        deliverable.write_bytes(b"\xff\xfe" * 100)
        unused.write_text("temporary output")
        proof.write_text(json.dumps([{"path": str(path), "sha256": digest(path)} for path in (log, deliverable)]))
        preview = self.pool(host, "closeout", "--request-id", request, "--preservation", proof)
        target, = preview["targets"]
        self.assertEqual(agent, target["agent_ref"])

        evidence = scratch / "terminal.json"
        observation = {"schema_version": 1, "agent_ref": agent, "outcome": "closed",
                       "native_evidence": {"path": str(log), "sha256": digest(log)},
                       "preservation": preview["preservation"]}
        args = ("--request-id", request, "--task-id", target["task_id"], "--record", original,
                "--expect-sha256", target["sha256"], "--evidence", evidence)
        evidence.write_text(json.dumps({**observation, "agent_ref": {"host": host, "agent_id": "different"}}))
        self.assertIn("exact native ID", self.pool(host, "finish-closeout", *args, code=2)["error"])
        evidence.write_text(json.dumps(observation))
        out = self.pool(host, "finish-closeout", *args)
        self.assertEqual(("closed", True), (out["status"], out["agent_retired"]))

        command = ("cleanup-scratch", "--root", self.project, "--pm-id", pm, "--request-id", request)
        scan = self.invoke(host, GRAPH, *command, "--dry-run")
        self.assertEqual({"native.log", "preserved.json"}, set(scan["kept_files"]))
        unused.write_text("changed since scan")
        self.invoke(host, GRAPH, *command, "--expect-sha256", scan["snapshot_sha256"], code=2)
        scan = self.invoke(host, GRAPH, *command, "--dry-run")
        overlap = self.workspace / "second-original.json"
        other = json.loads(original.read_bytes())
        other.pop("native_closeout")
        other["task"].pop("agent_ref")
        other["task"].pop("agent_retired")
        overlap.write_text(json.dumps(other))
        self.invoke(host, POOL, "register", "--root", self.project, "--pm-id", "codex:other",
                    "--record", overlap, "--expect-sha256", digest(overlap))
        refusal = self.invoke(host, GRAPH, *command, "--expect-sha256", scan["snapshot_sha256"], code=2)
        self.assertIn("scratch request ownership", refusal["error"])
        self.invoke(host, POOL, "archive", "--root", self.project, "--pm-id", "codex:other",
                    "--record", overlap, "--expect-sha256", digest(overlap))
        self.invoke(host, GRAPH, *command, "--expect-sha256", scan["snapshot_sha256"])
        self.assertTrue(original.is_file() and log.is_file() and proof.is_file())
        self.assertFalse(unused.exists())

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

        # 使用同一个在途已绑定原件。从两个独立包真实运行核验及恢复，
        # 即使没有 AGY 解释器也要识别任务占用和有效身份，并拒绝相同父子 UUID。
        modules = ("lib/hosts/antigravity_dispatch.py", "lib/hosts/antigravity_handoff.py")
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

    def test_antigravity_app_completes_registered_light_writer_from_the_installed_guide(self):
        host = "antigravity"
        installed = self.plugins[host]
        context_path = "plugins/antigravity/plugin-context.md"
        reference = "platforms/antigravity/references/pm-integration.md"
        self.assertIn(context_path, (installed / "rules/AGENTS.md").read_text(encoding="utf-8"))
        self.assertIn(reference + "#writer-completion", (installed / context_path).read_text(encoding="utf-8"))
        completion = (installed / reference).read_text(encoding="utf-8").split('<a id="writer-completion"></a>', 1)[1]
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
        task = pack["task"]
        task["input_contracts"] = ["测试用户明确委托修复 total([]) 并覆盖回归。"]
        pm = self.agy_pm.split(":")[1]
        start = {"step_index": 0, "source": "USER_EXPLICIT", "type": "USER_INPUT", "status": "DONE"}
        parent_log = self.agy_log(pm, start, app=True).with_name("transcript.jsonl")
        scratch = Path(self.host_delivery(host, parent_log, GRAPH, "scratch", "--root", self.project,
                                         "--request-id", task["request_id"])["scratch_dir"])
        path = scratch / "total.json"
        self.assertEqual("allow", self.hook_decision(parent_log, "write_file", {"Path": str(path)}))

        def claim(code):
            return self.host_delivery(host, parent_log, POOL, "claim", "--root", self.project, "--pm-id", self.agy_pm,
                                      "--register", "--record", path, "--request-id", task["request_id"],
                                      "--task-id", task["id"], "--expect-sha256", digest(path), *CAPACITY, code=code)

        self.assertEqual([], pack["approved_gates"])
        path.write_text(json.dumps(pack, ensure_ascii=False), encoding="utf-8")
        self.assertIn("approvals", claim(2)["error"])
        pack["approved_gates"] = ["requirements_approved"]
        path.write_text(json.dumps(pack, ensure_ascii=False), encoding="utf-8")
        self.assertEqual("valid", self.invoke(host, GRAPH, "validate", "--input", path)["status"])
        result = claim(0)
        self.assertEqual("claimed", result["status"])
        self.assertRegex(result["dispatch_marker"], r"^XY-WORKFLOW-CLAIM [0-9a-f]{64}$")
        claim_sha = digest(path)
        self.assertEqual("task-pack-v1", task_in(path)["antigravity_claim"]["prompt_format"])

        receipt = scratch / "claim.json"
        receipt.write_text(json.dumps(result), encoding="utf-8")
        handoff = self.host_delivery(host, parent_log, POOL, "handoff", "--root", self.project,
                                     "--pm-id", self.agy_pm, "--receipt", receipt)
        self.assertEqual(result["target"], handoff["target"])
        self.assertEqual(task["role"], handoff["role"])
        prompt = handoff["prompt"]
        received = json.loads(prompt.splitlines()[3])
        self.assertEqual(task["owned_paths"], received["task"]["owned_paths"])
        self.assertEqual(pack["standards_contract"], received["standards_contract"])

        child = str(uuid4())
        marker = result["dispatch_marker"]
        child_start = {"step_index": 0, "source": "SYSTEM", "type": "SYSTEM_MESSAGE", "status": "DONE",
                       "content": f"\n<SYSTEM_MESSAGE>\n[Message] timestamp=2026-11-20T10:01:46Z sender={pm} "
                                  f"priority=MESSAGE_PRIORITY_HIGH content={prompt}\n</SYSTEM_MESSAGE>"}
        child_log = self.agy_log(child, child_start, app=True).with_name("transcript.jsonl")
        bind = ("bind", "--root", self.project, "--pm-id", self.agy_pm, "--receipt", receipt,
                "--host", host, "--agent-id", child)
        stripped_tag = prompt.replace("\nXY-WORKFLOW-TASK-PACK-V1\n", "\n")
        for invalid in (stripped_tag, marker + "\nImplement all 56 pages.", prompt + "\nAlso implement 56 pages.",
                        prompt.replace("src/totals.py", "src/other.py")):
            parent_log = self.agy_parent_log(pm, child_log, marker, task["role"], self.project,
                                             app=True, with_steps=True, prompt=invalid).with_name("transcript.jsonl")
            self.assertIn("no matching native", self.host_delivery(host, parent_log, POOL, *bind, code=2)["error"])
            self.assertEqual("deny", self.hook_decision(child_log, "edit_file", {"Path": task["owned_paths"][0]}))
            self.assertEqual(claim_sha, digest(path))
        parent_log = self.agy_parent_log(pm, child_log, marker, task["role"], self.project,
                                         app=True, with_steps=True, prompt=prompt).with_name("transcript.jsonl")
        bound = self.host_delivery(host, parent_log, POOL, *bind)
        self.assertEqual("allow", self.hook_decision(child_log, "edit_file", {"Path": task["owned_paths"][0]}))
        self.assertEqual("deny", self.hook_decision(child_log, "edit_file", {"Path": "src/other.py"}))

        # Assert the exact packaged host command shape described to PM and use the same argv after PreToolUse.
        def recipe(fragment, **slots):
            line = next(line for line in completion.splitlines() if line.startswith("bash ") and fragment in line)
            for placeholder, value in {"plugin-root": installed, "project-root": self.project, **slots}.items():
                line = line.replace(f"<{placeholder}>", str(value))
            return shlex.split(line)

        view = recipe(f"{POOL} view", **{"parent-uuid": pm, "request-id": task["request_id"]})
        running = self.host_command(host, parent_log, view)
        self.assertEqual([], running["errors"])
        self.assertEqual(1, len(running["tasks"]))
        row = running["tasks"][0]
        self.assertEqual((str(path), task["id"], "RUNNING", True, bound["agent_ref"]),
                         (row["record"], row["task_id"], row["state"], row["active"], row["agent_ref"]))

        (self.project / "tests").mkdir()
        (self.project / "src/totals.py").write_text("def total(values):\n    return sum(values)\n", encoding="utf-8")
        (self.project / "tests/test_totals.py").write_text(
            "from unittest import TestCase\nfrom src.totals import total\n\n"
            "class TotalsTest(TestCase):\n"
            "    def test_empty(self):\n        self.assertEqual(0, total([]))\n"
            "    def test_nonempty(self):\n        self.assertEqual(3, total([1, 2]))\n", encoding="utf-8")
        check = task["verification_commands"][0]
        self.assertEqual("allow", self.hook_decision(child_log, "run_command", {"CommandLine": check}))
        worker_check = subprocess.run([sys.executable, *shlex.split(check)[1:]], cwd=self.project, env=self.env,
                                      capture_output=True, text=True, timeout=30)
        self.assertEqual(0, worker_check.returncode, worker_check.stderr)
        self.assertIn("Ran 2 tests", worker_check.stderr)
        # The PM has reviewed the actual exit and full log before attesting in the
        # command. The synthetic Inbox receipt is a native result locator, not proof of success.
        evidence = f"{check} exit {worker_check.returncode} native log ran 2 tests"
        source = f"native-inbox:{child}/light-result"
        pool_root, = (self.workspace / "agent-workflow-request-scratch").glob("*/task-pools")
        sibling = pool_root / hashlib.sha256(("antigravity:" + str(uuid4())).encode()).hexdigest()
        sibling.mkdir(mode=0o700)
        refused = self.hook_decision(parent_log, "write_file", {"Path": str(scratch / "writer-result.json")},
                                     with_reason=True)
        self.assertEqual("deny", refused["decision"])
        self.assertIn("index.json", refused["reason"])
        slots = {"record": path, "request-id": row["request_id"], "task-id": row["task_id"],
                 "bound-child-uuid": child, "native-result-reference": source,
                 "accepted-build-verification-with-log-reference": evidence, "parent-uuid": pm,
                 "record-sha256": row["sha256"]}

        def settle(**changes):
            return recipe(f"{POOL} complete-writer", **{**slots, **changes})

        self.host_command(host, child_log, settle(), denied=True)
        self.host_command(host, parent_log, [*settle(), "--state", "QA_PASSED"], denied=True)
        stale = settle(**{"record-sha256": claim_sha})
        self.assertIn("fingerprint changed", self.host_command(host, parent_log, stale, code=2)["error"])
        wrong_id = settle(**{"bound-child-uuid": str(uuid4())})
        self.assertIn("native-bound Writer", self.host_command(host, parent_log, wrong_id, code=2)["error"])
        missing = settle(**{"accepted-build-verification-with-log-reference": " "})
        self.assertIn("accepted verification", self.host_command(host, parent_log, missing, code=2)["error"])
        failed = settle()
        failed[failed.index("--verification-exit-code") + 1] = "1"
        self.assertIn("successful verification", self.host_command(host, parent_log, failed, code=2)["error"])
        self.assertEqual(row["sha256"], digest(path))
        updated = self.host_command(host, parent_log, settle())
        self.assertEqual(("completed", "BUILD_VERIFIED", False),
                         (updated["status"], updated["state"], updated["active"]))
        settled = self.host_command(host, parent_log, view)
        self.assertEqual([], settled["errors"])
        self.assertEqual([{**row, "sha256": updated["sha256"], "state": "BUILD_VERIFIED", "active": False}],
                         settled["tasks"])
        self.assertEqual([*task["acceptance_evidence"], f"{evidence} | Native result: {source}"],
                         task_in(path)["acceptance_evidence"])
        self.assertEqual([], list(sibling.iterdir()))

    def test_antigravity_full_writer_completion_requires_acknowledged_revision(self):
        host = "antigravity"
        pm_id = self.agy_pm
        pm = pm_id.split(":")[1]
        start = {"step_index": 0, "source": "USER_EXPLICIT", "type": "USER_INPUT", "status": "DONE"}
        parent = self.agy_log(pm, start, app=True).with_name("transcript.jsonl")
        request = "full-writer"
        scratch = Path(self.host_delivery(host, parent, GRAPH, "scratch", "--root", self.project,
                                         "--request-id", request)["scratch_dir"])
        record = scratch / "full.json"
        original = graph()
        original.update(request_id=request, active_paths=[], active_semantic_locks=[])
        writer = original["tasks"][0]
        for task in original["tasks"]:
            task["request_id"] = request
        record.write_text(json.dumps(original), encoding="utf-8")
        target = ("--record", record, "--request-id", request, "--task-id", writer["id"])
        claim = self.host_delivery(host, parent, POOL, "claim", "--root", self.project, "--pm-id", pm_id,
                                   *target, "--expect-sha256", digest(record), "--register", *CAPACITY)
        receipt = scratch / "claim.json"
        receipt.write_text(json.dumps(claim), encoding="utf-8")
        handoff = self.host_delivery(host, parent, POOL, "handoff", "--root", self.project,
                                     "--pm-id", pm_id, "--receipt", receipt)
        self.assertEqual(writer["owned_paths"], json.loads(handoff["prompt"].splitlines()[3])["task"]["owned_paths"])
        parent, child = self.bind_agy(claim, writer["role"], self.project, app_receipt=receipt,
                                      prompt=handoff["prompt"])
        row = self.locate(host, writer["goal"])
        reference = row["agent_ref"]
        revised = self.update(host, row, {"revise": {"set": {"goal": "Revised Full Writer"},
                                                    "source": "user:current-requirement"}})
        self.assertEqual("allow", self.hook_decision(child, "edit_file", {"Path": writer["owned_paths"][0]}))
        revision = task_in(record)["task_revision"]
        completion = ("complete-writer", "--root", self.project, "--pm-id", pm_id, *target, "--agent-id",
                      reference["agent_id"], "--verification-exit-code", "0", "--source", "native-inbox:current",
                      "--evidence", "current build exit 0 and runnable evidence in native log")
        self.assertIn("acknowledged task revision", self.host_delivery(
            host, parent, POOL, *completion, "--expect-sha256", revised["sha256"], "--revision", revision,
            code=2)["error"])
        proof = {"revision": revision, "agent_ref": reference}
        ack = self.update(host, row, {"ack_revision": {**proof, "delivery_source": "native:delivered",
                                                       "ack_source": "native:acknowledged"}},
                          expected=revised["sha256"])
        latest = ("--expect-sha256", ack["sha256"])
        self.assertIn("acknowledged task revision", self.host_delivery(
            host, parent, POOL, *completion, *latest, "--revision", revision - 1, code=2)["error"])
        result = self.host_delivery(host, parent, POOL, *completion, *latest, "--revision", revision)
        self.assertEqual(("BUILD_VERIFIED", False), (result["state"], result["active"]))
        self.assertEqual({**proof, "source": "native-inbox:current"}, task_in(record)["revision_result"])
        completed = json.loads(record.read_bytes())
        self.assertEqual(original["approved_gates"], completed["approved_gates"])
        self.assertEqual(original["tasks"][1:], completed["tasks"][1:])

    def agy_log(self, identifier, *events, short_events=None, app=False):
        client = "antigravity" if app else "antigravity-cli"
        location = self.workspace / "agy-account/.gemini" / client / "brain" / identifier / ".system_generated/logs"
        location.mkdir(parents=True, exist_ok=True)
        for name, rows in (("transcript.jsonl", events if short_events is None else short_events),
                           ("transcript_full.jsonl", events)):
            body = "".join(json.dumps(event, ensure_ascii=False) + "\n" for event in rows)
            (location / name).write_text(body, encoding="utf-8")
        return location / "transcript_full.jsonl"

    def agy_environment(self):
        # AGY 以操作系统账号目录为宿主日志权威，单改 HOME 无效。测试解释器只替换
        # 本 uid 的账号目录，保证真正的 Hook、绑定和交付入口均读取同一份隔离的原生事件。
        runtime = self.workspace / "agy-python"
        if not runtime.exists():
            entry = (
                "import os,pwd,runpy,sys\n"
                "lookup = pwd.getpwuid\n"
                "account = list(lookup(os.getuid()))\n"
                f"account[5] = {str(self.workspace / 'agy-account')!r}\n"
                "pwd.getpwuid = lambda uid: pwd.struct_passwd(account) if uid == os.getuid() else lookup(uid)\n"
                "sys.argv = sys.argv[1:]\nrunpy.run_path(sys.argv[0], run_name='__main__')\n"
            )
            python = shlex.quote(sys.executable)
            runtime.write_text("#!/usr/bin/env bash\nflags=()\nwhile (($#)); do\n  case \"$1\" in\n"
                               "    */hooks/write_guard.py|*/plugins/source_pack.py)\n"
                               f"      exec {python} \"${{flags[@]}}\" -c {shlex.quote(entry)} \"$@\" ;;\n"
                               '    -c|-m) break ;;\n  esac\n  flags+=("$1")\n  shift\ndone\n'
                               f"exec {python} \"${{flags[@]}}\" \"$@\"\n", encoding="utf-8")
            runtime.chmod(0o700)
        return {**self.env, "AGENT_WORKFLOW_PYTHON": str(runtime)}

    def hook_decision(self, transcript, tool, args, user="请直接修改并验证", *, with_reason=False):
        plugin = self.plugins["antigravity"]
        event = {"toolCall": {"name": tool, "args": args}, "conversationId": transcript.parents[2].name,
                 "transcriptPath": str(transcript), "lastUserInput": user, "workspacePaths": [str(self.project)],
                 "cwd": str(plugin)}
        manifest = json.loads((plugin / "hooks.json").read_bytes())
        hook = manifest["xy-workflow-write-ownership"]["PreToolUse"][0]["hooks"][0]["command"]
        result = subprocess.run(["bash", "-c", hook], cwd=plugin, env=self.agy_environment(),
                                input=json.dumps(event), capture_output=True, text=True, timeout=20)
        self.assertEqual(0, result.returncode, result.stderr)
        value = json.loads(result.stdout)
        self.assertLessEqual(set(value), {"decision", "reason"})
        return value if with_reason else value["decision"]

    def host_delivery(self, host, transcript, helper, *args, denied=False, code=0):
        plugin = self.plugins[host]
        command = ["bash", str(plugin / "lib/python_runtime.sh"), "-B", "-X", "utf8",
                   str(plugin / "plugins/source_pack.py"), "helper", "--project", str(self.project),
                   helper, *map(str, args)]
        return self.host_command(host, transcript, command, denied=denied, code=code)

    def host_command(self, host, transcript, command, *, denied=False, code=0):
        if host == "antigravity":
            # 终端只在真实 Hook 对这条确切命令放行后执行同一 argv，不能重选参数或原件。
            decision = self.hook_decision(transcript, "run_command", {"CommandLine": shlex.join(command),
                                          "Cwd": str(self.project)}, with_reason=True)
            self.assertEqual("deny" if denied else "allow", decision["decision"], (command, decision))
            if denied:
                return
        else:
            self.assertFalse(denied)
        env = self.agy_environment() if host == "antigravity" else self.env
        result = subprocess.run(command, cwd=self.project, env=env, text=True, capture_output=True, timeout=45)
        self.assertEqual(code, result.returncode, result.stdout + result.stderr)
        return json.loads(result.stdout if code == 0 else result.stderr)

    def test_antigravity_pretool_pm_current_request_and_preparation(self):
        pm = self.agy_pm.split(":")[1]
        start = {"step_index": 0, "source": "USER_EXPLICIT", "type": "USER_INPUT", "status": "DONE"}
        log = self.agy_log(pm, start)
        plugin = self.plugins["antigravity"]
        manifest = json.loads((plugin / "hooks.json").read_bytes())
        self.assertIn("write_guard.py", manifest["xy-workflow-write-ownership"]["PreToolUse"][0]["hooks"][0]["command"])
        for other in ("codex", "claude"):
            self.assertFalse((self.plugins[other] / "hooks.json").exists())
        self.assertFalse((self.plugins["claude"] / "hooks/write_guard.py").exists())
        codex_sources = json.loads((self.plugins["codex"] / "sources.json").read_bytes())
        self.assertEqual("plugins/codex/hooks/write_guard.py",
                         codex_sources["projections"]["hooks/write_guard.py"]["source"])
        self.assertFalse((self.plugins["codex"] / "lib/hosts/antigravity_dispatch.py").exists())
        self.assertFalse((plugin / "hooks/native_event.py").exists())
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
        prototype = f"{prefix} {PROTOTYPE}"
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
                (f"{prototype} . ui --standalone --adapter project.yaml --page first.html --json", "allow"),
                (f"{prototype} {self.project} ui --adapter project.yaml --json", "allow"),
                (f"{prototype} . ui --adapter project.yaml --json", "deny"),
                (f"{prototype} {self.workspace} ui --json", "deny"),
                (f"{prototype} . ../ui --standalone --adapter project.yaml --page first.html --json", "deny"),
                (f"{prototype} . ui --standalone --adapter ../project.yaml --page first.html --json", "deny"),
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
                (f"git diff --binary --full-index --no-renames --no-ext-diff --no-textconv "
                 f"HEAD -- src/fixture.txt > {scratch}/writer.diff", "allow"),
                ("git diff --output=src/other.txt", "deny"), ("echo changed > src/fixture.txt", "deny"),
                ("python3 -c 'print(1)'", "deny"), ("mkdir -p src/new", "deny"),
                (f"{helper} task --input {target} --task-id api > {scratch}/export.json", "allow"),
                (f"{prefix} {POOL} closeout --root {self.project} --pm-id {self.agy_pm} "
                 f"--request-id pm-guard --preservation {scratch}/keeps.json", "allow"),
                (f"{helper} cleanup-scratch --root {self.project} --pm-id {self.agy_pm} "
                 "--request-id pm-guard --dry-run", "allow"),
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

    def claim_agy_design(self, *, app=False):
        from tests.test_plugin_workflow_contract import visual_request

        host = "antigravity"
        example, _ = visual_request("UI-Page")
        task = example["tasks"][0]
        task.update(workflow_level="Light", state="DECLARED", blocks=[], goal="设计设置页",
                    input_contracts=["已确认的页面需求"], output_contracts=["设置原型"],
                    verification_commands=["检查原型页面"], acceptance_evidence=["静态核验"])
        page = self.project / task["owned_paths"][0]
        if not page.exists():
            page.parent.mkdir(parents=True, exist_ok=True)
            page.write_text("<main></main>", encoding="utf-8")
        pack = {key: example[key] for key in ("schema_version", "standards_contract", "ui_contract")}
        pack.update(task=task, request_scope="prototype_only", approved_gates=["requirements_approved"])
        if app:
            pm = self.agy_pm.split(":")[1]
            start = {"step_index": 0, "source": "USER_EXPLICIT", "type": "USER_INPUT", "status": "DONE"}
            log = self.agy_log(pm, start, app=True).with_name("transcript.jsonl")
            scratch = Path(self.host_delivery(host, log, GRAPH, "scratch", "--root", self.project,
                                             "--request-id", task["request_id"])["scratch_dir"])
            path = scratch / "design-pack.json"
            self.assertEqual("allow", self.hook_decision(log, "write_file", {"Path": str(path)}))
        else:
            path = self.workspace / "design-pack.json"
        path.write_text(json.dumps(pack), encoding="utf-8")
        arguments = ("--register", "--title", task["goal"], "--record", path,
                     "--task-id", task["id"], "--request-id", task["request_id"],
                     "--expect-sha256", digest(path), *CAPACITY)
        claim = (self.host_delivery(host, log, POOL, "claim", "--root", self.project, "--pm-id", self.agy_pm, *arguments)
                 if app else self.pool(host, "claim", *arguments))
        app_receipt = path.parent / "claim.json" if app else None
        parent_log, log = self.bind_agy(claim, task["role"], self.project, app_receipt=app_receipt)
        self.assertEqual(log.parents[2].name, task_in(path)["agent_ref"]["agent_id"])
        return path, parent_log, log

    def bind_agy(self, claim, role, execution_root, *, app_receipt=None, prompt=None):
        marker = claim["dispatch_marker"]
        pm, child = self.agy_pm.split(":")[1], str(uuid4())
        receipt_path = app_receipt if app_receipt is not None else self.workspace / (child + "-claim.json")
        if not receipt_path.exists():
            receipt_path.write_text(json.dumps(claim), encoding="utf-8")
        if prompt is None:
            prompt = self.pool("antigravity", "handoff", "--receipt", receipt_path)["prompt"]
        log = self.agy_log(child, {"step_index": 0, "source": "SYSTEM", "type": "SYSTEM_MESSAGE", "status": "DONE",
            "content": "\n<SYSTEM_MESSAGE>\n[Message] timestamp=2026-11-20T10:01:46Z sender=" + pm
                       + " priority=MESSAGE_PRIORITY_HIGH content=" + prompt + "\n</SYSTEM_MESSAGE>"},
                           app=app_receipt is not None)
        parent_log = self.agy_parent_log(pm, log, marker, role, execution_root, app=app_receipt is not None,
                                         with_steps=app_receipt is not None, prompt=prompt)
        if app_receipt is not None:
            parent_log = parent_log.with_name("transcript.jsonl")
            self.assertEqual("allow", self.hook_decision(parent_log, "write_file", {"Path": str(app_receipt)}))
        arguments = ("bind", "--root", self.project, "--pm-id", self.agy_pm,
                     "--receipt", receipt_path, "--host", "antigravity", "--agent-id", child)
        if app_receipt is not None:
            bound = self.host_delivery("antigravity", parent_log, POOL, *arguments)
            self.assertEqual({"host": "antigravity", "agent_id": child}, bound["agent_ref"])
            return parent_log, log.with_name("transcript.jsonl")
        plugin = self.plugins["antigravity"]
        command = ["bash", str(plugin / "lib/python_runtime.sh"), "-B", "-X", "utf8",
                   str(plugin / "plugins/source_pack.py"), "helper", "--project", str(self.project),
                   POOL, *map(str, arguments)]
        result = subprocess.run(command, cwd=self.project, env=self.agy_environment(), text=True,
                                capture_output=True, timeout=45)
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual({"host": "antigravity", "agent_id": child}, json.loads(result.stdout)["agent_ref"])
        return parent_log, log

    def agy_parent_log(self, pm, child_log, marker, role, execution_root, *, app=False, with_steps=False,
                       prompt=None):
        receipt = {"conversationId": child_log.parents[2].name,
                   "logAbsoluteUri": child_log.with_name("transcript.jsonl").as_uri(),
                   "workspaceUris": [execution_root.as_uri()]}
        start = {"step_index": 0, "source": "USER_EXPLICIT", "type": "USER_INPUT", "status": "DONE"}
        calls = [{"name": "invoke_subagent", "args": {"TypeName": role, "Prompt": marker if prompt is None else prompt}}]
        request = {"step_index": 1, "source": "MODEL", "type": "PLANNER_RESPONSE", "status": "DONE", "tool_calls": calls}
        results = []
        timestamps = ""
        if with_steps:
            calls[:0] = [
                {"name": "update_focus", "args": {"focus": "派发实现者"}},
                {"name": "update_steps", "args": {"steps": [{"status": "in_progress", "title": "派发实现者"}]}},
            ]
            timestamps = "Created At: 2026-11-23T10:57:46+08:00\nCompleted At: 2026-11-23T10:57:48+08:00\n" * 2
            results.extend({"step_index": index, "source": "MODEL", "type": "GENERIC", "status": "DONE",
                            "content": timestamps + "OK"} for index in (2, 3))
        results.append({"step_index": 2 + len(results), "source": "MODEL", "type": "GENERIC", "status": "DONE",
                        "content": timestamps + "Created the following subagent:\n" + json.dumps(receipt)
                        + "\nThe subagent will send you a message when it has completed its task or requires guidance. "
                          "There is no need to poll for its response."})
        short_calls = [{**call, "args": {key: json.dumps(value) for key, value in call["args"].items()}} for call in calls]
        return self.agy_log(pm, start, request, *results, app=app,
                            short_events=[start, {**request, "tool_calls": short_calls}, *results])

    def test_antigravity_app_hook_and_first_bind_require_same_client_receipt(self):
        host = "antigravity"
        pm, child = self.agy_pm.split(":")[1], str(uuid4())
        path = self.register(host, "changes", "修正", light=True, owned="src/fixture.txt")
        claim = self.claim(host, self.locate(host, "修正"))
        marker = claim["dispatch_marker"]
        claimed = path.read_bytes()
        scratch = self.invoke(host, GRAPH, "scratch", "--root", self.project, "--request-id", "changes")
        receipt = Path(scratch["scratch_dir"]) / "claim.json"
        receipt.write_text(json.dumps(claim), encoding="utf-8")
        prompt = self.pool(host, "handoff", "--receipt", receipt)["prompt"]
        child_start = {"step_index": 0, "source": "SYSTEM", "type": "SYSTEM_MESSAGE", "status": "DONE",
                       "content": f"\n<SYSTEM_MESSAGE>\n[Message] timestamp=2026-11-20T10:01:46Z sender={pm} "
                                  f"priority=MESSAGE_PRIORITY_HIGH content={prompt}\n</SYSTEM_MESSAGE>"}
        app_child = self.agy_log(child, child_start, app=True).with_name("transcript.jsonl")
        cli_child = self.agy_log(child, child_start)

        def dispatch(log, *, app=False):
            return self.agy_parent_log(pm, log, marker, "xy-backend", self.project,
                                       app=app, with_steps=app, prompt=prompt)

        target = {"Path": "src/fixture.txt"}
        cli_parent = dispatch(cli_child)
        self.assertEqual("allow", self.hook_decision(cli_child, "edit_file", target))
        result = self.hook_decision(app_child, "edit_file", target, with_reason=True)
        self.assertEqual("deny", result["decision"])
        self.assertIn("无法核对当前子会话的可写派发", result["reason"])


        def bind(log, code=0):
            return self.host_delivery(host, log, POOL, "bind", "--root", self.project, "--pm-id", self.agy_pm,
                                      "--receipt", receipt, "--host", host, "--agent-id", child, code=code)

        dispatch(app_child)
        self.assertIn("no matching native", bind(cli_parent, code=2)["error"])
        self.assertEqual(claimed, path.read_bytes())

        app_parent = dispatch(app_child, app=True).with_name("transcript.jsonl")
        self.assertEqual("allow", self.hook_decision(app_child, "edit_file", target))
        self.assertEqual("deny", self.hook_decision(cli_child, "edit_file", target))
        self.assertIn("both App and CLI", bind(app_parent, code=2)["error"])
        self.assertEqual(claimed, path.read_bytes())

        shutil.rmtree(cli_parent.parents[3])
        self.assertEqual("allow", self.hook_decision(app_parent, "run_command", {"CommandLine": "git status --short"}))
        self.assertEqual("deny", self.hook_decision(app_parent, "edit_file", target))
        explicit = "请 PM 本人直接修改 src/fixture.txt"
        self.assertEqual("allow", self.hook_decision(app_parent, "edit_file", target, explicit))
        self.assertEqual("deny", self.hook_decision(app_parent, "edit_file", {"Path": ".git/config"},
                                                   "这次由主会话亲自改"))
        self.assertEqual("allow", self.hook_decision(app_child, "edit_file", target))
        self.assertEqual("deny", self.hook_decision(app_child, "edit_file", {"Path": "src/other.txt"}))
        bound = bind(app_parent)
        self.assertEqual({"host": host, "agent_id": child}, bound["agent_ref"])
        self.assertEqual(bound["agent_ref"], task_in(path)["agent_ref"])

    def test_antigravity_binds_revised_withdrawn_claim_only_to_stop_its_child(self):
        host = "antigravity"
        request = "revise-before-stop"
        pm, child = self.agy_pm.split(":")[1], str(uuid4())
        owned = "src/fixture.txt"
        path = self.register(host, request, "Original scope", light=True, owned=owned)
        old_row = self.locate(host, request)
        claim = self.claim(host, old_row)
        marker = claim["dispatch_marker"]
        scratch = self.invoke(host, GRAPH, "scratch", "--root", self.project, "--request-id", request)
        receipt = Path(scratch["scratch_dir"]) / "claim.json"
        receipt.write_text(json.dumps(claim), encoding="utf-8")
        prompt = self.pool(host, "handoff", "--receipt", receipt)["prompt"]
        start = {
            "step_index": 0, "source": "SYSTEM", "type": "SYSTEM_MESSAGE", "status": "DONE",
            "content": f"\n<SYSTEM_MESSAGE>\n[Message] timestamp=2026-11-20T10:01:46Z sender={pm} "
                       f"priority=MESSAGE_PRIORITY_HIGH content={prompt}\n</SYSTEM_MESSAGE>",
        }
        child_log = self.agy_log(child, start, app=True).with_name("transcript.jsonl")

        def dispatch(workspace):
            return self.agy_parent_log(pm, child_log, marker, "xy-backend", workspace,
                                       app=True, prompt=prompt).with_name("transcript.jsonl")

        bind = ("bind", "--root", self.project, "--pm-id", self.agy_pm, "--receipt", receipt,
                "--host", host, "--agent-id", child)
        edit = {"Path": owned}
        parent = dispatch(self.project)
        self.assertEqual("allow", self.hook_decision(child_log, "edit_file", edit))
        running = self.locate(host, request)
        revised = self.update(host, running, {"revise": {"set": {"goal": "Revised scope"},
                                                         "source": "user:change-before-binding"}})
        self.assertIn("no matching native", self.host_delivery(host, parent, POOL, *bind, code=2)["error"])
        self.assertEqual(revised["sha256"], digest(path))
        self.assertEqual("deny", self.hook_decision(child_log, "edit_file", edit))

        stopped = self.update(host, running, {"withdraw": {"reason": "user:withdraw-revised-task"}},
                              expected=revised["sha256"])
        row = self.locate(host, request)
        self.assertEqual(("STOP_REQUESTED", True, stopped["sha256"]), (row["state"], row["active"], row["sha256"]))
        self.assertEqual("deny", self.hook_decision(child_log, "edit_file", edit))
        wrong_parent = dispatch(self.workspace)
        self.assertIn("no matching native", self.host_delivery(host, wrong_parent, POOL, *bind, code=2)["error"])
        self.assertEqual(stopped["sha256"], digest(path))

        parent = dispatch(self.project)
        bound = self.host_delivery(host, parent, POOL, *bind)
        reference = {"host": host, "agent_id": child}
        self.assertEqual(reference, bound["agent_ref"])
        row = self.locate(host, request)
        self.assertEqual(("STOP_REQUESTED", True, bound["sha256"]), (row["state"], row["active"], row["sha256"]))
        self.assertEqual("deny", self.hook_decision(child_log, "edit_file", edit))

        self.update(host, row, {"confirm_stop": {"agent_ref": reference, "observed_state": "stopped",
                                                 "source": "native:stop-receipt"}})
        row = self.locate(host, request)
        self.assertEqual(("WITHDRAWN", False, reference), (row["state"], row["active"], row["agent_ref"]))

    def test_antigravity_design_child_can_query_one_topic_read_only(self):
        path, _, log = self.claim_agy_design()
        plugin = self.plugins["antigravity"]
        page = self.project / task_in(path)["owned_paths"][0]
        self.assertEqual("allow", self.hook_decision(log, "edit_file", {"Path": str(page)}))
        command = (f'bash "{plugin}/lib/python_runtime.sh" -B -X utf8 "{plugin}/plugins/source_pack.py" '
                   'selected-skills query ux "error summary form validation"')
        for suffix, expected in (("", "allow"), (" --max-results 2", "allow"), (" --max-results 21", "deny"),
                                 (" --persist", "deny"), (" --design-system", "deny"), (f' > "{page}"', "deny")):
            with self.subTest(suffix=suffix):
                self.assertEqual(expected, self.hook_decision(log, "run_command", {"CommandLine": command + suffix}))

    def test_antigravity_full_graph_design_uses_its_task_request(self):
        from tests.test_plugin_workflow_contract import visual_request
        from tests.test_prototype_workspace import bind_requirement_documents, write_valid_project

        self.project = write_valid_project(self.workspace / "multi-request")
        bind_requirement_documents(self.project)
        graph, _ = visual_request("UI-Page")
        first = graph["tasks"][0]
        first.update(state="DECLARED", blocks=[], goal="更新本任务原型",
                     input_contracts=["只使用此任务的页面范围"], output_contracts=["交付当前 HTML"],
                     verification_commands=["静态核验当前原型"], acceptance_evidence=["页面静态验证通过"])
        other = copy.deepcopy(first)
        page = self.project / first["owned_paths"][0]
        sibling = page.with_name("profile.html")
        sibling.write_bytes(page.read_bytes())
        other.update(id="profile", agent_alias="profile", request_id="req-profile",
                     owned_paths=[sibling.relative_to(self.project).as_posix()])
        for document in other["controlled_document_access"]["documents"]:
            document["applies_to"] = other["owned_paths"]
        graph.update(request_id=first["request_id"], tasks=[other, first])
        record = self.workspace / "design-graph.json"
        record.write_text(json.dumps(graph), encoding="utf-8")
        # 即使图首请求与本次任务不同，具体页仍由这次设计任务原件限定。
        claim = self.pool("antigravity", "claim", "--register", "--record", record, "--request-id", other["request_id"],
                          "--task-id", other["id"], "--expect-sha256", digest(record), *CAPACITY)
        _, child = self.bind_agy(claim, "xy-uiux", self.project)
        self.assertEqual("allow", self.hook_decision(child, "edit_file", {"Path": str(sibling)}))
        self.assertEqual("deny", self.hook_decision(child, "edit_file", {"Path": str(page)}))

    def assert_review_link(self, opened):
        url = urlsplit(opened["review_url"])
        self.assertEqual(("http", "127.0.0.1", ""), (url.scheme, url.hostname, url.fragment))
        client = http.client.HTTPConnection(url.hostname, url.port, timeout=5)
        try:
            client.request("GET", url.path, headers={"Sec-Fetch-Mode": "navigate",
                           "Sec-Fetch-Dest": "document", "Sec-Fetch-Site": "none"})
            response = client.getresponse()
            self.assertEqual(200, response.status)
            self.assertIn(b'id="prototype-review-data"', response.read())
        finally:
            client.close()

    def test_antigravity_packaged_design_delivers_statically_verified_html_without_review(self):
        from tests.test_prototype_workspace import PROTOTYPE_RELATIVE, bind_requirement_documents, write_valid_project

        host = "antigravity"
        self.project = write_valid_project(self.workspace / "AGY design")
        plan, _ = bind_requirement_documents(self.project)
        (self.project / PROTOTYPE_RELATIVE / "index.html").unlink()
        record, pm, child = self.claim_agy_design(app=True)
        task = task_in(record)
        relative, = task["owned_paths"]
        page = self.project / relative
        before = page.read_bytes()
        static = (".", PROTOTYPE_RELATIVE, "--standalone", "--adapter", "project.yaml", "--page", page.name, "--json")
        self.assertEqual("allow", self.hook_decision(child, "edit_file", {"Path": str(page)}))
        evidence = self.host_delivery(host, child, PROTOTYPE, *static)
        self.assertEqual([relative], [item["path"] for item in evidence["pages"]])
        fingerprint = evidence["pages"][0]["dependency_fingerprint"]
        self.assertRegex(fingerprint, r"^[a-f0-9]{64}$")

        selected = ("--root", self.project, "--adapter", "project.yaml", "--pages", relative)
        review = (*selected, "--plan", plan.relative_to(self.project), "--request-id", task["request_id"])
        self.host_delivery(host, child, FEEDBACK, "prepare-delivery", *selected, denied=True)
        self.host_delivery(host, child, FEEDBACK, "open", *review, denied=True)
        original = record.read_bytes()
        for tool, args in (
                ("edit_file", {"Path": str(record)}),
                ("write_file", {"Path": str(record)}),
                ("multi_replace_file_content", {"TargetFile": str(record)}),
                ("run_command", {"CommandLine": f"pwd > {shlex.quote(str(record))}"}),
                ("run_command", {"CommandLine": f"touch {shlex.quote(str(record))}"})):
            with self.subTest(tool=tool):
                denied = self.hook_decision(pm, tool, args, with_reason=True)
                self.assertEqual("deny", denied["decision"])
                self.assertIn("已登记的任务原件", denied["reason"])
                self.assertNotIn(str(record), denied["reason"])
        self.assertEqual(original, record.read_bytes())
        other_pm = self.agy_log(str(uuid4()), {"step_index": 0, "source": "USER_EXPLICIT",
                                              "type": "USER_INPUT", "status": "DONE"}, app=True)
        self.assertEqual("deny", self.hook_decision(other_pm, "edit_file", {"Path": str(record)}))
        self.assertEqual("allow", self.hook_decision(other_pm, "write_file", {"Path": str(record.with_name("handoff.json"))}))
        alias = record.with_name(record.name.upper())
        if alias.exists() and alias.samefile(record):
            self.assertEqual("deny", self.hook_decision(pm, "edit_file", {"Path": str(alias)}))
        # 导出工件可覆盖原有的普通交接包，但其另一个输入不能借 --output 覆盖本原件。
        export_source = record.with_name("another-source.json")
        export_source.write_text(json.dumps(graph()), encoding="utf-8")
        self.host_delivery(host, pm, GRAPH, "task", "--root", self.project, "--input", export_source,
                           "--task-id", task_in(export_source)["id"], "--output", record,
                           "--expect-sha256", digest(record), denied=True)
        # 原件正文暂缺不等于解除登记。其余证据文件仍可在同一请求目录内写入。
        record.unlink()
        try:
            self.assertEqual("deny", self.hook_decision(pm, "write_file", {"Path": str(record)}))
            self.assertEqual("allow", self.hook_decision(pm, "write_file", {"Path": str(record.with_name("result.json"))}))
            plugin = self.plugins[host]
            init = (f"bash {plugin}/lib/python_runtime.sh -B -X utf8 {plugin}/plugins/source_pack.py "
                    f"helper --project {self.project} plugins/project_context.py init "
                    f"--adapter project.yaml --output {shlex.quote(str(record))}")
            self.assertEqual("deny", self.hook_decision(pm, "run_command", {"CommandLine": init}))
        finally:
            record.write_bytes(original)

        view = ("view", "--root", self.project, "--pm-id", self.agy_pm, "--query", task["request_id"])
        row, = self.host_delivery(host, pm, POOL, *view)["tasks"]
        accepted = f"原生设计实例静态通过 {relative}，exit 0，dependency_fingerprint={fingerprint}"
        source = f"native-inbox:{child.parents[2].name}/prototype-result"
        updated = self.host_delivery(host, pm, POOL, "complete-writer", "--root", self.project,
                                     "--pm-id", self.agy_pm, "--record", record, "--request-id", row["request_id"],
                                     "--task-id", row["task_id"], "--expect-sha256", row["sha256"],
                                     "--agent-id", row["agent_ref"]["agent_id"], "--verification-exit-code", "0",
                                     "--source", source, "--evidence", accepted)
        self.assertEqual([{**row, "sha256": updated["sha256"], "state": "BUILD_VERIFIED", "active": False}],
                         self.host_delivery(host, pm, POOL, *view)["tasks"])
        self.assertEqual([*task["acceptance_evidence"], f"{accepted} | Native result: {source}"],
                         task_in(record)["acceptance_evidence"])
        patch = record.with_name("writer-result.json")
        patch.write_text("retained verification attachment", encoding="utf-8")
        self.host_delivery(host, pm, FEEDBACK, "open", *review, denied=True)
        self.assertEqual(evidence, self.host_delivery(host, pm, PROTOTYPE, *static,
                         "--expect", f"{page.name}={fingerprint}"))
        with urlopen(page.as_uri()) as original:
            self.assertEqual(before, original.read())
        self.assertFalse((page.parent / ".xy-prototype-entry").exists())
        cleanup = ("cleanup-scratch", "--root", self.project, "--request-id", task["request_id"])
        result = self.host_delivery(host, pm, GRAPH, *cleanup, "--dry-run", code=2)
        self.assertIn("registered request scratch", result["error"])
        scoped = (*cleanup, "--pm-id", self.agy_pm)
        result = self.host_delivery(host, pm, GRAPH, *scoped, "--dry-run", code=2)
        self.assertIn("before accepted instances are retired", result["error"])

        native_log = record.with_name("native-end.log")
        native_log.write_text("fixture native result preserved, instance no longer reused")
        proof = record.with_name("preserved.json")
        evidence = {"path": str(native_log), "sha256": digest(native_log)}
        proof.write_text(json.dumps([evidence]))
        scope = ("--root", self.project, "--pm-id", self.agy_pm, "--request-id", task["request_id"])
        plan = self.host_delivery(host, pm, POOL, "closeout", *scope, "--preservation", proof)
        target, = plan["targets"]
        terminal = record.with_name("terminal.json")
        terminal.write_text(json.dumps({"schema_version": 1, "agent_ref": target["agent_ref"], "outcome": "retired",
                                        "native_evidence": evidence, "preservation": plan["preservation"]}))
        finished = self.host_delivery(host, pm, POOL, "finish-closeout", *scope, "--record", record,
                                      "--task-id", task["id"], "--expect-sha256", target["sha256"],
                                      "--evidence", terminal)
        self.assertEqual("retired", finished["status"])
        preview = self.host_delivery(host, pm, GRAPH, *scoped, "--dry-run")
        result = self.host_delivery(host, pm, GRAPH, *scoped, "--expect-sha256", preview["snapshot_sha256"])
        self.assertEqual("applied", result["status"])
        self.assertFalse(patch.exists())
        self.assertTrue(native_log.is_file() and proof.is_file())
        self.assertEqual(finished["sha256"], digest(record))


    def test_codex_and_claude_packaged_prototype_delivery_serves_the_page_and_stops(self):
        from tests.test_prototype_workspace import PROTOTYPE_RELATIVE, bind_requirement_documents, write_valid_project

        for host in ("codex", "claude"):
            with self.subTest(host=host):
                self.project = write_valid_project(self.workspace / host)
                plan, _ = bind_requirement_documents(self.project)
                page = self.project / PROTOTYPE_RELATIVE / "settings.html"
                relative = page.relative_to(self.project).as_posix()
                request = "req-design"
                # prepare/open 走用户的默认数据位置；只为本例子进程提供独立家目录。
                home = self.workspace / host / "home"
                home.mkdir()
                self.env.update(HOME=str(home), XDG_DATA_HOME=str(home / ".local/share"))
                def feedback(action, *options):
                    return self.host_delivery(host, None, FEEDBACK, action, "--root", self.project, *options)

                selected = ("--adapter", "project.yaml", "--pages", relative)
                identity = ("--request-id", request)
                review = (*selected, "--plan", plan.relative_to(self.project), *identity)
                self.assertEqual("prepared", feedback("prepare-delivery", *selected)["status"])
                self.assertTrue((page.parent / ".xy-prototype-entry/entry.js").is_file())
                self.assertIn('data-xy-delivery-entry="1"', page.read_text(encoding="utf-8"))
                opened = feedback("open", *review)
                try:
                    self.assertEqual(("ready", request, [page.as_uri()]),
                                     (opened["status"], opened["request_id"], opened["delivery_urls"]))
                    self.assertEqual(page.as_uri(), opened["delivery_url"])
                    self.assert_review_link(opened)
                    state = feedback("status", *identity)
                    self.assertEqual(("ready", opened["review_id"]), (state["status"], state["review_id"]))
                    self.assertEqual("stopped", feedback("stop", *identity)["status"])
                    self.assertEqual("stopped", feedback("status", *identity)["status"])
                finally:
                    # 即使 HTTP 断言失败，夹具所有者仍回收刚创建的本机进程。
                    self.invoke(host, FEEDBACK, "stop", "--root", self.project, *identity)

    def accept_host_candidate(self, host, candidate, scratch):
        from tests.test_qa_handoff import handoff_ref

        candidate.graph.update(active_paths=[], active_semantic_locks=[], capacity=2)
        graph_path = scratch / "graph.json"
        graph_path.write_text(json.dumps(candidate.graph), encoding="utf-8")
        claim = self.pool(host, "claim", "--register", "--record", graph_path, "--request-id",
                          candidate.graph["request_id"], "--task-id", "qa", "--expect-sha256",
                          digest(graph_path), *CAPACITY)
        if host == "antigravity":
            parent, reviewer = self.bind_agy(claim, "xy-qa", candidate.integration)
            reviewer_id = reviewer.parents[2].name
        else:
            parent = reviewer = None
            reviewer_id = str(uuid4())
            receipt = scratch / "claim.json"
            receipt.write_text(json.dumps(claim), encoding="utf-8")
            self.pool(host, "bind", "--receipt", receipt, "--host", host, "--agent-id", reviewer_id)
        qa_pack = scratch / "qa-pack.json"
        self.invoke(host, GRAPH, "task", "--input", graph_path, "--task-id", "qa",
                    "--output", qa_pack, "--expect-sha256", "missing")
        body = qa_pack.read_bytes()
        pack = json.loads(body)
        self.assertEqual({"host": host, "agent_id": reviewer_id}, pack["task"]["agent_ref"])
        # 验收消费实际导出的本版包及该宿主 Reviewer 的结果；随后的 PM 只能使用原收据。
        qa_handoff = candidate.payload["qa_handoff"]
        qa_handoff["handoff_ref"] = handoff_ref(pack, body)
        handoff = scratch / "qa-handoff.json"
        handoff.write_text(json.dumps(qa_handoff), encoding="utf-8")
        accepted = {"task_pack": {"path": str(qa_pack), "sha256": digest(qa_pack)},
                    "handoff": {"path": str(handoff), "sha256": digest(handoff)}}
        self.invoke(host, GRAPH, "update", "--input", graph_path, "--expect-sha256", digest(graph_path),
                    "--patch", "-", value={"tasks": {"qa": {"accept_request": accepted}}})
        candidate.payload.update(task_graph=json.loads(graph_path.read_bytes()), qa_task_pack=str(qa_pack))
        qa = next(task for task in candidate.payload["task_graph"]["tasks"] if task["id"] == "qa")
        self.assertEqual(("QA_PASSED", accepted["task_pack"]), (qa["state"], qa["request_receipt"]["task_pack"]))
        return parent, reviewer

    def test_packaged_pm_fast_forwards_only_the_approved_reviewed_candidate(self):
        from lib.delivery.worktree_cli import git, head
        from tests.test_worktree_delivery import GitDeliveryTest

        for host in self.plugins:
            with self.subTest(host=host):
                # 复用真实工作树、组合验证及 QA 导出/接收夹具，每个宿主各交付一次。
                candidate = GitDeliveryTest()
                self.addCleanup(candidate.doCleanups)
                candidate.setUp(pending_qa=True, adapter="project.yaml")
                self.project = candidate.repo
                request = candidate.graph["request_id"]
                scratch = Path(self.invoke(host, GRAPH, "scratch", "--root", self.project,
                                           "--request-id", request)["scratch_dir"])
                path = scratch / "delivery.json"
                parent, reviewer = self.accept_host_candidate(host, candidate, scratch)

                def invoke(action, payload, *, actor=parent, denied=False, code=0):
                    path.write_text(json.dumps(payload), encoding="utf-8")
                    options = ["--repo", self.project, "--config", candidate.config.relative_to(self.project),
                               "--input", path]
                    if host == "antigravity":
                        options += ["--pm-id", self.agy_pm, "--expect-sha256", digest(path)]
                    return self.host_delivery(host, actor, WORKTREE, action, *options, denied=denied, code=code)

                self.assertNotEqual(candidate.tip, candidate.base)
                if host == "antigravity":
                    other_pm = self.agy_log(str(uuid4()), {"step_index": 0, "source": "USER_EXPLICIT",
                                                          "type": "USER_INPUT", "status": "DONE"})
                    invoke("merge", candidate.payload, actor=other_pm, denied=True)
                    invoke("merge", candidate.payload, actor=reviewer, denied=True)
                    substitute = copy.deepcopy(candidate.payload)
                    substitute["task_graph"]["approved_gates"].append("unregistered")
                    invoke("merge", substitute, denied=True)
                    self.assertEqual(candidate.base, head(self.project))
                for field in ("authorization", "qa_handoff"):
                    invalid = copy.deepcopy(candidate.payload)
                    if field == "authorization":
                        invalid[field]["head_revision"] = candidate.base
                        expected_error = "merge authorization is missing or stale"
                    else:
                        invalid[field]["audit_result"] = "FAIL"
                        invalid[field]["standards_policy_coverage"]["rule_checks"][0]["disposition"] = "fail"
                        expected_error = "QA FAIL blocks delivery"
                    for action in ("merge-ready", "merge"):
                        with self.subTest(host=host, defect=field, action=action):
                            self.assertIn(expected_error, invoke(action, invalid, code=2)["error"])
                            self.assertEqual(candidate.base, head(self.project))
                self.assertEqual("merge_ready", invoke("merge-ready", candidate.payload)["status"])
                self.assertEqual(candidate.base, head(self.project))
                result = invoke("merge", candidate.payload)
                self.assertEqual("merged", result["status"])
                self.assertFalse(result["pushed"])
                self.assertEqual(candidate.tip, head(self.project))
                self.assertEqual(candidate.base, git(self.project, "merge-base", candidate.base, "HEAD").decode().strip())
                self.assertEqual("b = 1\n", (self.project / "src/b.py").read_text())

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
                                                          ' productType = "com.apple.product-type.application";\n'
                                                          ' IPHONEOS_DEPLOYMENT_TARGET = 16.0;\n };\n };\n}'),
                     "ios/App.xcodeproj/xcshareddata/xcschemes/App.xcscheme": '<Scheme version="1.7"/>',
                     "ios/App.xcworkspace/contents.xcworkspacedata":
                         '<Workspace><FileRef location="group:App.xcodeproj"/></Workspace>'}
        for relative, body in manifests.items():
            file = self.project / relative
            file.parent.mkdir(parents=True, exist_ok=True)
            file.write_text(body, encoding="utf-8")
        device = ("xcodebuild -workspace App.xcworkspace -scheme App -destination "
                  "generic/platform=iOS CODE_SIGNING_ALLOWED=NO build")
        wrong_bundle = device.replace("App.xcworkspace", "../App.xcworkspace")
        override = device.replace("CODE_SIGNING_ALLOWED=NO", "CODE_SIGNING_ALLOWED=YES")
        simulator = device.replace("generic/platform=iOS", "'generic/platform=iOS Simulator'")
        checks = ["python3 test_total.py", "./gradlew test", "uv run pytest", "poetry run pytest",
                  "xcodebuild -scheme App build", "python3 -c 'print(1)'", device, wrong_bundle, override,
                  simulator.replace("CODE_SIGNING_ALLOWED=NO ", "")]
        self.update(host, self.locate(host, "修正"), {"set": {"verification_commands": checks},
                    "append": {"acceptance_evidence": ["构建证据 " * 800]}})
        claim = self.claim(host, self.locate(host, "修正"))
        receipt = self.workspace / "fixture-claim.json"
        receipt.write_text(json.dumps(claim), encoding="utf-8")
        prompt = self.pool(host, "handoff", "--receipt", receipt)["prompt"]
        child = str(uuid4())
        child_log = self.agy_log(child, {
            "step_index": 0, "source": "SYSTEM", "type": "SYSTEM_MESSAGE", "status": "DONE",
            "content": "\n<SYSTEM_MESSAGE>\n[Message] timestamp=2026-11-20T10:01:46Z sender=" + pm
                       + " priority=MESSAGE_PRIORITY_HIGH content=" + prompt + "\n</SYSTEM_MESSAGE>",
        })
        def dispatch(role, receipt_fields=None):
            # 真长提示词在 1.5.13 的短日志中丢失独立标记。Hook 必须使用完整日志
            # 的原始字符串参数，且创建回执里的子 URI 仍按短日志定位。
            call = {"name": "invoke_subagent", "args": {"TypeName": role, "Prompt": prompt}}
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
                                         ("python3 -c 'print(1)'", ".", "deny"), (device, "ios", "allow"),
                                         (device, ".", "deny"), (wrong_bundle, "ios", "deny"),
                                         (override, "ios", "deny"), (device + " && git status", "ios", "deny"),
                                         (simulator, "ios", "deny"),
                                         (simulator.replace("CODE_SIGNING_ALLOWED=NO ", ""), "ios", "allow")):
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
