"""同一 Full 请求跨业务批准、原型返工、生产交付、独立 QA 和 PM 文档回写的回归。"""
from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from lib.delivery.worktree_cli import create, git, head, scope
from lib.documents.validate_prototype_workspace import capture_selected_pages
from lib.foundation_qa import current_request_receipt
from lib.solution_confirmation import bind_decisions
from lib.task_graph_records import digest
from tests.test_foundation_qa import REPO, handoff, required_prototype_graph
from tests.test_prototype_workspace import PROTOTYPE_RELATIVE, write_valid_project


class WorkflowClosureTest(unittest.TestCase):
    def setUp(self):
        self.workspace = Path(self.enterContext(tempfile.TemporaryDirectory())).resolve()
        self.project = write_valid_project(self.workspace)
        (self.project / "project.yaml").write_bytes((REPO / "project.yaml").read_bytes())
        self.graph = self.workspace / "graph.json"

    def cli(self, action, *args, patch=None, rejected=False):
        """走 PM 实际使用的 CLI；拒绝或旧证据必须保全权威图的原字节。"""
        before = self.graph.read_bytes()
        output = subprocess.run([sys.executable, "-B", str(REPO / "lib/task_graph_cli.py"),
                                 action, "--input", str(self.graph), *args], cwd=self.project,
                                input=json.dumps(patch) if patch is not None else None,
                                capture_output=True, text=True, timeout=20)
        self.assertEqual(2 if rejected else 0, output.returncode, output.stderr)
        if rejected:
            self.assertEqual(before, self.graph.read_bytes())
            return json.loads(output.stderr)["error"]
        return json.loads(output.stdout)

    def update(self, patch, *, rejected=False):
        return self.cli("update", "--expect-sha256", digest(self.graph.read_bytes()),
                        "--patch", "-", patch=patch, rejected=rejected)

    def set_state(self, task, state, *, rejected=False):
        return self.update({"tasks": {task: {"set": {"state": state}}}}, rejected=rejected)

    def test_reworked_page_and_reviewed_decision_survive_only_the_permitted_closeout(self):
        # 已确认需求用同一主题文件贯穿图、审查与回写；真实 Git 范围把独立工作和功能工作合并验收。
        decision = {"id": "retry", "content": "提交失败保留输入，可手动重试。"}
        plan = self.project / "docs/plans/settings.md"
        plan.parent.mkdir(parents=True)
        plan.write_text("# 设置保存\n\n- 主题 ID：`settings`\n- 阶段：`active`\n- 模块：`settings`\n- 任务等级：`Full`\n- 已验收版本：`none`\n"
                        "\n## 需求与验收\n\n" + decision["content"] +
                        "\n\n## 验收结果与当前已交付行为\n\n当前没有已验收基线。\n"
                        "\n## 批准依据与必要证据\n\n- 批准依据：当前请求。\n- 验收证据：待写回。\n")
        source, page = required_prototype_graph(self.project, digest(plan.read_bytes()))
        independent, feature, qa, design = source["tasks"]
        source["approved_gates"] = ["requirements_approved"]
        for writer in (independent, feature, design):
            writer["state"] = "DECLARED"
        for writer in (feature, design):
            writer["solution_decisions"] = [decision]
            bind_decisions(writer)
        self.graph.write_text(json.dumps(source))
        git(self.project, "init", "-b", "main")
        git(self.project, "config", "user.name", "Workflow Fixture")
        git(self.project, "config", "user.email", "workflow@example.invalid")
        git(self.project, "add", ".")
        git(self.project, "commit", "-m", "准备本轮设置页及需求")
        base = head(self.project)

        self.assertEqual([independent["id"]], self.cli("ready")["ready"])
        self.cli("task", "--task-id", feature["id"], rejected=True)
        self.set_state(independent["id"], "RUNNING")
        (self.project / "src/foundation.py").write_text("def preserve(value):\n    return value\n")
        self.set_state(independent["id"], "BUILD_VERIFIED")
        approval = {**decision, "request_id": design["request_id"], "task_id": design["id"],
                    "source_ref": "user:settings/retry"}
        self.update({"approve_solutions": [approval]})
        self.set_state(design["id"], "RUNNING")
        self.set_state(design["id"], "BUILD_VERIFIED")
        first = {"request_id": feature["request_id"], "task_id": feature["id"],
                 "requirements_fingerprint": source["requirements_fingerprint"], "authority_id": "settings",
                 "path": page["path"], "dependency_fingerprint": page["dependency_fingerprint"],
                 "previous_fingerprint": page["dependency_fingerprint"], "approval_ref": "user:settings/v1",
                 "changed_scope": ["设置页失败时的输入"], "interactions": ["保留设置值后手动重试"]}
        self.update({"approve_visuals": [first]})
        self.assertIn(feature["id"], self.cli("ready")["ready"])

        # 用户要求返工，先检查仍在制作的设计，再检查已重新交付但尚未获新授权的真实字节。
        self.set_state(design["id"], "DECLARED")
        self.cli("task", "--task-id", feature["id"], rejected=True)
        self.set_state(feature["id"], "BUILD_VERIFIED", rejected=True)
        html = self.project / page["path"]
        html.write_text(html.read_text().replace("Configure the project settings.", "Keep settings on failure and retry."))
        revised, = capture_selected_pages(self.project, PROTOTYPE_RELATIVE.as_posix(),
                                          pages=[html.name], adapter="project.yaml")["pages"]
        self.assertNotEqual(page["dependency_fingerprint"], revised["dependency_fingerprint"])
        self.set_state(design["id"], "BUILD_VERIFIED")
        self.cli("task", "--task-id", feature["id"], rejected=True)
        self.update({"approve_visuals": [{**first, **revised, "approval_ref": "user:settings/v2"}]})
        self.set_state(feature["id"], "RUNNING")
        self.cli("task", "--task-id", feature["id"])
        (self.project / "src/feature.py").write_text("from src.foundation import preserve\n\n"
                                                     "def retry(value):\n    return preserve(value)\n")
        subprocess.run([sys.executable, "-B", "-c", "from src.feature import retry; assert retry('input') == 'input'"],
                       cwd=self.project, check=True)
        self.set_state(feature["id"], "BUILD_VERIFIED")
        git(self.project, "add", "--", page["path"], "src/foundation.py", "src/feature.py")
        git(self.project, "commit", "-m", "交付获得确认的设置重试")
        reviewed_scope = {"repositories": [scope(self.project, base, head(self.project))]}
        self.update({"tasks": {qa["id"]: {"freeze_qa_scope": reviewed_scope}}})
        self.set_state(qa["id"], "QA")
        self.update({"tasks": {qa["id"]: {"set": {"agent_ref": {"host": "codex", "agent_id": "fixture-reviewer"}}}}})
        pack = self.cli("task", "--task-id", qa["id"])
        choice, = pack["reviewed_solution_decisions"]
        self.assertEqual((decision["content"], approval["source_ref"]), (choice["content"], choice["source_ref"]))
        self.assertEqual(sorted([design["id"], feature["id"]]), choice["writer_ids"])
        body = json.dumps(pack).encode()
        reviewed = handoff(pack, body, scope_ref=reviewed_scope)
        refs = {}
        for field, data in (("task_pack", body), ("handoff", json.dumps(reviewed).encode())):
            path = self.workspace / (field + ".json")
            path.write_bytes(data)
            refs[field] = {"path": str(path), "sha256": digest(data)}
        self.update({"tasks": {qa["id"]: {"accept_request": refs}}})

        # 允许原位写验收结果和证据，原决定属于被审正文；改掉失败策略必须使旧回执失效。
        original = self.workspace / "reviewed-plan.md"
        original.write_bytes(plan.read_bytes())
        plan.write_text(plan.read_text().replace("当前没有已验收基线。", "参数在失败后保留。")
                        .replace("待写回。", refs["handoff"]["sha256"]).replace("`none`", "`local-v1`"))
        projection = {"adapter": "project.yaml", "documents": [{
            "path": plan.relative_to(self.project).as_posix(), "projected_sha256": digest(plan.read_bytes()),
            "reviewed": {"path": str(original), "sha256": digest(original.read_bytes())}}]}
        self.update({"tasks": {qa["id"]: {"record_qa_projection": projection}}})
        current = json.loads(self.graph.read_bytes())
        accepted = next(task for task in current["tasks"] if task["id"] == qa["id"])
        self.assertEqual("QA_PASSED", accepted["state"])
        self.assertTrue(current_request_receipt(current, accepted, root=self.project))
        plan.write_text(plan.read_text().replace(decision["content"], "失败后清空输入。"))
        self.assertFalse(current_request_receipt(current, accepted, root=self.project))


    def test_isolated_visual_approval_uses_design_checkout_then_consumer_and_integration(self):
        from lib.task_graph_cli import _execute
        from lib.task_graph_records import publish, update

        graph, initial = required_prototype_graph(self.project, "c" * 64)
        common, feature, _, designer = graph["tasks"]
        request = feature["request_id"]
        git(self.project, "init", "-b", "main")
        git(self.project, "config", "user.name", "Visual Checkout Fixture")
        git(self.project, "config", "user.email", "visual@example.invalid")
        git(self.project, "add", ".")
        git(self.project, "commit", "-m", "保留主树的旧设置页")
        base = head(self.project)
        combined = self.workspace / "integration"
        design = self.workspace / "design"
        common_root = self.workspace / "common"
        consumer = self.workspace / "production"
        for checkout in (combined, design, common_root):
            create(self.project, checkout, base)

        page = initial["path"]
        revised_html = design / page
        revised_html.write_text(revised_html.read_text().replace("Configure the project settings.", "Revise the settings."))
        git(design, "add", "--", page)
        git(design, "commit", "-m", "正式设计检查点")
        design_tip = head(design)
        # 集成树保留独立历史并以 merge 组合设计；消费方从该组合开工，主树没有这次改动。
        git(combined, "commit", "--allow-empty", "-m", "准备组合")
        git(combined, "merge", "--no-ff", design_tip, "-m", "组合原型")
        combined_tip = head(combined)
        create(self.project, consumer, combined_tip)
        common["execution_workspace"] = {"root": str(common_root), "base_revision": base, "head_revision": base}
        designer["execution_workspace"] = {"root": str(design), "base_revision": base, "head_revision": design_tip}
        feature.update(state="DECLARED", execution_workspace={"root": str(consumer), "base_revision": combined_tip,
                                                              "head_revision": None})
        graph["approved_gates"] = ["requirements_approved"]
        graph["worktree_integrations"] = {request: {"root": str(combined), "target_branch": "main", "target_base": base,
                                                    "head_revision": combined_tip, "verification": []}}
        self.graph.write_text(json.dumps(graph))
        revised, = capture_selected_pages(design, PROTOTYPE_RELATIVE.as_posix(), pages=["settings.html"],
                                          adapter="project.yaml")["pages"]
        self.assertNotEqual(initial, revised)
        approval = {**revised, "request_id": request, "task_id": feature["id"], "authority_id": "settings",
                    "requirements_fingerprint": graph["requirements_fingerprint"],
                    "previous_fingerprint": initial["dependency_fingerprint"], "approval_ref": "user:settings/merge",
                    "changed_scope": ["设置页说明"], "interactions": ["打开设置页核对说明"]}
        self.update({"approve_visuals": [{**approval, **initial}]}, rejected=True)
        # 旧主树始终可读。已登记的设计树缺失、集成树实际 HEAD 落后，都必须给出
        # 相应失败，不能靠主树上碰巧同名的页面或另一个任务目录完成视觉批准。
        moved = self.workspace / "moved-design"
        design.rename(moved)
        try:
            failure = self.update({"approve_visuals": [approval]}, rejected=True)
            self.assertIn("design Writer worktree", failure)
        finally:
            moved.rename(design)
        git(combined, "checkout", "--detach", base)
        failure = self.update({"approve_visuals": [approval]}, rejected=True)
        self.assertIn("integration worktree", failure)
        git(combined, "checkout", "--detach", combined_tip)
        # 验证与发布之间改变设计树时，CAS 锁内的独立复核同样拒绝且保全图。
        original = self.graph.read_bytes()
        candidate = update(graph, {"approve_visuals": [approval]}, self.project,
                           lambda op, data: _execute(op, data, root=self.project))
        css = design / PROTOTYPE_RELATIVE / "prototype.css"
        pristine = css.read_bytes()
        css.write_bytes(pristine + b"\n")
        with self.assertRaisesRegex(ValueError, "fingerprint is stale"):
            publish(self.graph, json.dumps(candidate).encode(), digest(original), root=self.project)
        self.assertEqual(original, self.graph.read_bytes())
        css.write_bytes(pristine)
        self.update({"approve_visuals": [approval]})
        self.assertIn(feature["id"], self.cli("ready")["ready"])
        self.cli("task", "--task-id", feature["id"])

        adopted = consumer / page
        contents = adopted.read_bytes()
        adopted.unlink()
        self.assertNotIn(feature["id"], self.cli("ready")["ready"])
        self.cli("task", "--task-id", feature["id"], rejected=True)
        self.set_state(feature["id"], "RUNNING", rejected=True)
        adopted.write_bytes(contents)
        git(consumer, "checkout", "--detach", base)
        self.cli("task", "--task-id", feature["id"], rejected=True)
        git(consumer, "checkout", "--detach", combined_tip)
        self.set_state(feature["id"], "RUNNING")
        (consumer / "src/feature.py").write_text("def feature():\n    return True\n")
        git(consumer, "add", "--", "src/feature.py")
        git(consumer, "commit", "-m", "完成设置页消费方")
        feature_tip = head(consumer)
        self.update({"tasks": {feature["id"]: {"checkpoint": feature_tip, "set": {"state": "BUILD_VERIFIED"}}}})
        self.assertFalse(self.cli("qa-ready")["qa_ready"])
        git(combined, "merge", "--ff-only", feature_tip)
        self.update({"integrations": {request: {"head_revision": feature_tip, "verification": [
            {"command": "project-build-and-smoke", "exit_code": 0, "log_ref": "fixture:smoke", "head_revision": feature_tip}]}}})
        self.assertTrue(self.cli("qa-ready")["qa_ready"])
        integrated_css = combined / PROTOTYPE_RELATIVE / "prototype.css"
        integrated_css.write_bytes(pristine + b"\n")
        self.assertFalse(self.cli("qa-ready")["qa_ready"])
        self.set_state("qa", "QA", rejected=True)
        self.assertEqual(initial["dependency_fingerprint"], capture_selected_pages(
            self.project, PROTOTYPE_RELATIVE.as_posix(), pages=["settings.html"],
            adapter="project.yaml")["pages"][0]["dependency_fingerprint"])
