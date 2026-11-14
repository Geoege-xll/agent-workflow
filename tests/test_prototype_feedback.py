"""只读反馈协议的行为用例：绑定真实来源，拒绝越界输入且不写回原型。"""

from __future__ import annotations

import copy
from functools import lru_cache
import zipfile
import json
import os
from pathlib import Path
from unittest import mock
import subprocess
import tempfile
import unittest
from urllib.parse import parse_qs, urlsplit

from lib.documents import prototype_feedback as feedback
from tests.test_prototype_workspace import (
    PACK, PAGE_HTML, PROTOTYPE_RELATIVE, bind_requirement_documents,
    tree_snapshot, write_valid_project,
)


LEGACY_REVISION = "a99cd86356f5574fe99273b2cec323feea8a16af"


@lru_cache(maxsize=1)
def legacy_fixture():
    """CI直接读取固定真实旧包，不需要Git历史、旧安装或旧源码执行。"""
    with zipfile.ZipFile(PACK / "tests/fixtures/prototype-review-v2.zip") as archive:
        entries = {name: archive.read(name) for name in archive.namelist()}
    metadata = json.loads(entries["fixture.json"])
    if metadata["revision"] != LEGACY_REVISION: raise AssertionError("旧包来源提交不匹配")
    return metadata, entries


def prepare_legacy(project, data_dir, page):
    """常规旧协议用真实冻结六资源；独立旧包用例验证原派生物逐字节一致。"""
    from lib.documents import prototype_review as review
    fixture, entries = legacy_fixture()
    tools = {name.removeprefix("bundle/"): body for name, body in entries.items() if name.startswith("bundle/tool/")}
    context, _, files, navigation = feedback.capture_review(project, "project.yaml", "docs/plans/settings.md", "review-1", None, tool=fixture["context"]["tool"], format_version=2)
    assembled = review._assemble_v2(context, files, tools, navigation)
    assembled["manifest.json"] = review.json_bytes({"schema_version": 2, "context": context, "files": [
        {"path": path, "size": len(body), "sha256": review.digest(body)} for path, body in sorted(assembled.items())]})
    with review._request_directory(context, data_dir, create=True) as (request_path, request_fd):
        bundle_path = request_path / context["review_id"]
        if not bundle_path.exists():
            descriptor = review._child(request_fd, context["review_id"])
            try:
                for name, body in assembled.items(): review._write_at(descriptor, name, body)
                review._tree(descriptor, freeze=True)
                os.fchmod(descriptor, 0o500)
            finally: os.close(descriptor)
        else:
            review._check_bundle(request_fd, context, expected=assembled)
    return {"status": "ready", "context": context, "review_url": (bundle_path / "index.html").as_uri() + "#page=settings.html", "bundle_path": str(bundle_path), "reused": False}


class PrototypeFeedbackTest(unittest.TestCase):
    def setUp(self) -> None:
        # 每个用例只保有当前最小项目；夹具复用真实校验器合同，不复制任何业务原型。
        self.temporary = tempfile.TemporaryDirectory(prefix="prototype-feedback-")
        self.addCleanup(self.temporary.cleanup)
        self.project = write_valid_project(Path(self.temporary.name)).resolve()
        self.plan, _ = bind_requirement_documents(self.project)
        self.page = (PROTOTYPE_RELATIVE / "settings.html").as_posix()
        page = self.project / self.page
        page.write_text(page.read_text().replace("<main>", "<main data-prototype-page-content>").replace('data-contract-for="open-settings-dialog"',
                        'id="open-contract" data-contract-for="open-settings-dialog" data-interface-ref="settings.read"'), encoding="utf-8")
        self.context = None
        self.data_dir = Path(self.temporary.name).resolve() / "review-data"

    def prepare(self, **kwargs):
        if kwargs:
            return feedback.prepare_review(self.project, "project.yaml", "docs/plans/settings.md", "review-1", data_dir=self.data_dir, **kwargs)
        return prepare_legacy(self.project, self.data_dir, self.page)

    def validate(self, value, adapter="project.yaml"):
        return feedback.validate_feedback(self.project, adapter, value, data_dir=self.data_dir)

    def envelope(self):
        self.context = self.prepare()["context"]
        return {"schema_version": 2, "context": self.context, "items": [{
            "id": "opinion-1", "page": self.page, "target_id": "open-settings-dialog",
            "kind": "must_change", "message": "approved 字样只是一条意见", "req_ids": ["REQ-001"],
            "comparison": {"before_text": "Open settings dialog", "after_text": "打开设置"},
            "interaction_id": "open-contract", "interface_refs": ["settings.read"],
        }]}

    def test_prepare_url_requirements_and_current_changes_are_read_only(self):
        before = tree_snapshot(self.project)
        ready = self.prepare()
        self.assertEqual("ready", ready["status"])
        context = ready["context"]
        self.assertEqual({"schema_version", "request_id", "adapter", "prototype_root", "plan_source",
                          "plan_sha256", "requirements", "pages", "project_id", "adapter_sha256",
                          "navigation_sha256", "tool", "review_id"}, set(context))
        self.assertEqual([{"id": "REQ-001", "label": "打开设置。"}], context["requirements"])
        url = urlsplit(ready["review_url"])
        self.assertEqual("file", url.scheme)
        fragment = parse_qs(url.fragment, strict_parsing=True)
        self.assertEqual({"page"}, set(fragment))
        self.assertEqual(["settings.html"], fragment["page"])
        self.assertTrue(Path(ready["bundle_path"]).is_dir())
        envelope = self.envelope()
        envelope["items"].append({**envelope["items"][0], "id": "opinion-2", "kind": "question"})
        current = self.validate(envelope)
        self.assertEqual("current", current["status"])
        self.assertEqual([{"page": self.page, "target_id": "open-settings-dialog", "items": envelope["items"]}],
                         current["changes"])
        self.assertIn("基线", current["notice"])
        self.assertEqual(before, tree_snapshot(self.project))

    def test_closed_schema_types_sizes_and_duplicate_ids(self):
        original = self.envelope()
        mutations = [
            lambda v: v.update(approved=True),
            lambda v: v.update(schema_version=True),
            lambda v: v["context"].update(runtime_binding={}),
            lambda v: v["context"]["pages"][0].update(approved=True),
            lambda v: v["context"]["requirements"][0].update(extra=True),
            lambda v: v["items"][0].update(apply=True),
            lambda v: v["items"][0].update(kind="approved"),
            lambda v: v["items"][0].update(message=""),
            lambda v: v["items"][0].update(message="x" * 4001),
            lambda v: v["items"][0].update(comparison={"before_text": "a", "after_text": "b", "html": "<b>x</b>"}),
            lambda v: v["items"].append(copy.deepcopy(v["items"][0])),
            lambda v: v["context"]["pages"].append(copy.deepcopy(v["context"]["pages"][0])),
        ]
        for mutate in mutations:
            value = copy.deepcopy(original)
            mutate(value)
            with self.subTest(mutate=mutate), self.assertRaises(ValueError):
                self.validate(value)
        for raw in ['{"schema_version":1,"schema_version":1}', '{"items":NaN}', '[1]', '"' + 'x' * 1048576 + '"']:
            with self.subTest(raw=raw[:60]), self.assertRaises(ValueError):
                feedback.parse_feedback(raw.encode())

    def test_stale_plan_page_and_transitive_resource_fail_without_rebinding(self):
        for path in (self.plan, self.project / PROTOTYPE_RELATIVE / "prototype.css",
                     self.project / self.page):
            value = self.envelope()
            old = path.read_bytes()
            path.write_bytes(old + b"\n ")
            before = tree_snapshot(self.project)
            with self.subTest(path=path.name), self.assertRaises(ValueError):
                self.validate(value)
            self.assertEqual(before, tree_snapshot(self.project))
            path.write_bytes(old)

    def test_explicit_adapter_plan_and_prototype_boundary_even_without_navigation(self):
        # 原校验器按需检查导航；反馈必须无条件核对显式 adapter/plans/prototype 根。
        page = self.project / self.page
        page.write_text(PAGE_HTML.replace('data-contract-for="open-settings-dialog"',
                        'id="open-contract" data-contract-for="open-settings-dialog" data-interface-ref="settings.read"'), encoding="utf-8")
        self.assertEqual("ready", self.prepare()["status"])
        for plan in ("project.yaml", "docs/standards/out.md", "../settings.md", "/settings.md", "docs//plans/settings.md"):
            with self.subTest(plan=plan), self.assertRaises(ValueError):
                feedback.prepare_review(self.project, "project.yaml", plan, "review-1")
        (self.project / "other.yaml").write_text("docs:\n  plans: docs/plans/\n", encoding="utf-8")
        with self.assertRaises(ValueError):
            feedback.prepare_review(self.project, "other.yaml", "docs/plans/settings.md", "review-1")
        value = self.envelope()
        value["context"]["prototype_root"] = "docs/elsewhere/prototype"
        with self.assertRaises(ValueError):
            self.validate(value)
        with self.assertRaises(ValueError):
            self.validate(self.envelope(), "other.yaml")

    def test_unknown_target_requirement_and_interaction_are_rejected(self):
        original = self.envelope()
        for change in ({"target_id": "missing"}, {"target_id": "../escape"}, {"req_ids": ["REQ-999"]},
                       {"req_ids": ["REQ-001", "REQ-001"]}, {"interaction_id": "settings-dialog"},
                       {"interface_refs": ["invented-api"]}, {"page": "docs/standards/prototype/index.html"}):
            value = copy.deepcopy(original)
            value["items"][0].update(change)
            with self.subTest(change=change), self.assertRaises(ValueError):
                self.validate(value)
        page = self.project / self.page
        page.write_text(page.read_text().replace("</main>", '<p id="open-settings-dialog">重复</p></main>'), encoding="utf-8")
        with self.assertRaises(ValueError):
            self.prepare()

    def test_path_nodes_and_old_binding_are_rejected(self):
        for node in (self.plan, self.project / "project.yaml"):
            old = node.read_bytes()
            node.unlink()
            node.symlink_to(self.project / self.page)
            try:
                with self.subTest(node=node.name), self.assertRaises(ValueError):
                    self.prepare()
            finally:
                node.unlink()
                node.write_bytes(old)
        (self.project / ".agent-workflow").mkdir()
        (self.project / ".agent-workflow/runtime.json").write_text("{}")
        with self.assertRaises(ValueError):
            self.prepare()

    def test_context_is_bounded_and_paths_are_canonical(self):
        for pages in ([self.page, self.page], ["settings.html"], ["docs/standards/prototype/../prototype/settings.html"]):
            with self.subTest(pages=pages), self.assertRaises(ValueError):
                self.prepare(pages=pages)
        value = self.envelope()
        value["context"]["request_id"] = "x" * 9000
        with self.assertRaises(ValueError):
            self.validate(value)
        self.plan.write_text("# 需求\n" + "\n".join(f"REQ-{i:03}: " + "长" * 150 for i in range(100)), encoding="utf-8")
        with self.assertRaises(ValueError):
            self.prepare()

    def test_declared_contract_references_have_exact_node_ownership(self):
        page = self.project / self.page
        body = page.read_text().replace('data-interface-ref="settings.read"', '')
        body = body.replace(
            '<td>Open dialog</td>', '<td data-interface-ref="settings.read">Open dialog</td>')
        body = body.replace('<main>', '<main data-interface-ref="outside.contract">')
        page.write_text(body, encoding="utf-8")
        value = self.envelope()
        self.assertEqual("current", self.validate(value)["status"])
        for refs in (["outside.contract"], ["settings.read", "settings.read"], []):
            value["items"][0]["interface_refs"] = refs
            with self.subTest(refs=refs), self.assertRaises(ValueError):
                self.validate(value)
        page.write_text(body.replace('id="open-contract"', ''), encoding="utf-8")
        value = self.envelope()
        with self.assertRaises(ValueError):
            self.validate(value)
        del value["items"][0]["interaction_id"]
        self.assertEqual("current", self.validate(value)["status"])
        page.write_text(body.replace('id="open-settings-dialog"', 'id=" open-settings-dialog "'), encoding="utf-8")
        with self.assertRaises(ValueError):
            self.prepare()

    def test_page_limit_and_requirement_projection_cannot_be_forged(self):
        index = self.project / PROTOTYPE_RELATIVE / "index.html"
        for number in range(16):
            name = f"screen-{number}.html"
            (index.parent / name).write_text(PAGE_HTML.replace("<main>", "<main data-prototype-page-content>"), encoding="utf-8")
            index.write_text(index.read_text().replace('</nav>', f'<a href="{name}">页面</a></nav>'), encoding="utf-8")
        with self.assertRaises(ValueError):
            self.prepare()
        selected = [(PROTOTYPE_RELATIVE / f"screen-{number}.html").as_posix() for number in range(16)]
        ready = self.prepare(pages=selected)
        self.assertEqual(16, len(ready["context"]["pages"]))
        value = {"schema_version": 2, "context": ready["context"], "items": []}
        value["context"]["requirements"][0]["label"] = "伪造标签"
        with self.assertRaises(ValueError):
            self.validate(value)

    def test_hardlinks_nested_duplicate_keys_and_read_races_fail_closed(self):
        # snapshot 的安全属性也必须贯穿新入口，不因文件字节相同就信任硬链接或换入节点。
        backup = self.project / "hardlink-plan.md"
        os.link(self.plan, backup)
        try:
            with self.assertRaises(ValueError):
                self.prepare()
        finally:
            backup.unlink()
        with self.assertRaises(ValueError):
            feedback.parse_feedback(b'{"schema_version":1,"context":{"adapter":"a","adapter":"b"},"items":[]}')
        original = feedback.workspace.capture_selected_pages

        def mutate_after_validation(*args, **kwargs):
            result = original(*args, **kwargs)
            self.plan.write_bytes(self.plan.read_bytes() + b"changed")
            return result

        with mock.patch.object(feedback.workspace, "capture_selected_pages", side_effect=mutate_after_validation):
            with self.assertRaises(ValueError):
                self.prepare()
        alias = self.project.parent / "linked-project"
        alias.symlink_to(self.project, target_is_directory=True)
        with self.assertRaises(ValueError):
            feedback.prepare_review(alias, "project.yaml", "docs/plans/settings.md", "review-1")

    def test_cli_real_process_and_structured_failures_preserve_files(self):
        command = ["bash", str(PACK / "lib/python_runtime.sh"), "-B", "-X", "utf8",
                   str(PACK / "lib/documents/prototype_feedback_cli.py")]
        before = tree_snapshot(self.project)
        result = subprocess.run(command + ["prepare", "--root", str(self.project), "--adapter", "project.yaml",
                                "--plan", "docs/plans/settings.md", "--request-id", "review-1", "--pages", self.page, "--data-dir", str(self.data_dir)],
                                capture_output=True, text=True)
        self.assertEqual(0, result.returncode, result.stderr + result.stdout)
        self.assertEqual("ready", json.loads(result.stdout)["status"])
        self.assertEqual(before, tree_snapshot(self.project))
        input_file = Path(self.temporary.name).resolve() / "feedback.json"
        input_file.write_text(json.dumps(self.envelope(), ensure_ascii=False), encoding="utf-8")
        result = subprocess.run(command + ["validate", "--root", str(self.project), "--adapter", "project.yaml",
                                "--input", str(input_file), "--data-dir", str(self.data_dir)], capture_output=True, text=True)
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        self.assertEqual("current", json.loads(result.stdout)["status"])
        input_file.write_text('{"schema_version":1,"schema_version":1}', encoding="utf-8")
        result = subprocess.run(command + ["validate", "--root", str(self.project), "--adapter", "project.yaml",
                                "--input", str(input_file), "--data-dir", str(self.data_dir)], capture_output=True, text=True)
        self.assertNotEqual(0, result.returncode)
        self.assertEqual("error", json.loads(result.stdout)["status"])
        self.assertEqual('{"schema_version":1,"schema_version":1}', input_file.read_text())
        self.assertEqual(before, tree_snapshot(self.project))


    def envelope_v3(self, pages=None):
        ready = feedback.prepare_review(self.project, "project.yaml", "docs/plans/settings.md", "review-1", pages or [self.page], data_dir=self.data_dir)
        return {"schema_version": 3, "context": ready["context"], "anchors": [
            {"id": "anchor-1", "number": 3, "target": {"scope": "node", "page": self.page, "locator": {"type": "id", "id": "open-settings-dialog"}}}],
            "items": [{"id": "opinion-1", "number": 7, "operation": "modify", "target": {"scope": "node", "page": self.page,
                      "locator": {"type": "id", "id": "open-settings-dialog"}}, "message": "实际修改意见", "req_ids": [], "reference_ids": ["anchor-1"]}]}

    def test_v3_real_source_anonymous_scopes_references_and_read_only(self):
        from lib.documents.prototype_targets import capture_targets
        source_path = self.project / self.page
        source = source_path.read_bytes()
        other_page = (PROTOTYPE_RELATIVE / "another.html").as_posix()
        (self.project / other_page).write_bytes(source)
        metadata = capture_targets(other_page, source)
        key = next(key for key, locator in metadata["source_keys"].items() if locator["type"] == "source")
        before = tree_snapshot(self.project)
        value = self.envelope_v3([self.page, other_page])
        # 节点整改可以引用另一个登记页面上的A；引用关系不能按当前页面裁掉。
        anonymous = {"scope": "node", "page": other_page, "locator": {"type": "source", "key": key}}
        value["anchors"].append({"id": "anchor-2", "number": 9, "target": anonymous})
        value["items"][0]["reference_ids"].append("anchor-2")
        value["items"].extend([
            {"id": "opinion-2", "number": 20, "operation": "add", "target": {"scope": "page", "page": self.page}, "message": "新增页面模块", "req_ids": [], "reference_ids": []},
            {"id": "opinion-3", "number": 21, "operation": "modify", "target": {"scope": "global"}, "message": "统一视觉", "req_ids": [], "reference_ids": ["anchor-1"]},
            {"id": "opinion-4", "number": 22, "operation": "delete", "target": anonymous, "message": "", "req_ids": [], "reference_ids": []}])
        current = self.validate(value)
        self.assertEqual("current", current["status"])
        self.assertEqual(value["anchors"], current["anchors"])
        self.assertEqual(4, sum(len(change["items"]) for change in current["changes"]))
        self.assertEqual(before, tree_snapshot(self.project))
        self.assertEqual(source, source_path.read_bytes())

    def test_v3_closed_boundaries_and_business_mapping(self):
        value = self.envelope_v3()
        mutations = [
            lambda v: v["items"][0].update(kind="must_change"),
            lambda v: v["items"][0].update(severity="high"),
            lambda v: v["items"][0].update(position="after"),
            lambda v: v["items"][0].update(number=True),
            lambda v: v["items"][0].update(target={"scope": []}),
            lambda v: v["items"][0].update(reference_ids=["missing"]),
            lambda v: v["items"][0].update(req_ids=["REQ-001"]),
            lambda v: v["items"][0].update(target={"scope": "page", "page": self.page}, operation="delete"),
            lambda v: v["items"][0].update(target={"scope": "global"}, operation="add"),
            lambda v: v["items"][0].update(target={"scope": "node", "page": self.page, "locator": {"type": "source", "key": "source-" + "0" * 64}}),
            lambda v: v["items"][0].update(target={"scope": "node", "page": self.page, "locator": {"type": "id", "id": "prototype-page-title"}}),
            lambda v: v["anchors"].append({**v["anchors"][0], "id": "anchor-other", "number": 4}),
            lambda v: v["items"][0].update(operation="add", comparison={"before_text": "a", "after_text": "b"}),
        ]
        for mutate in mutations:
            bad = copy.deepcopy(value); mutate(bad)
            with self.subTest(mutate=mutate), self.assertRaises(ValueError): self.validate(bad)
        source = self.project / self.page
        original = source.read_text()
        source.write_text(original.replace('id="open-settings-dialog"', 'id="open-settings-dialog" data-req-ids="REQ-001"'))
        value = self.envelope_v3(); value["items"][0]["req_ids"] = ["REQ-001"]
        self.assertEqual("current", self.validate(value)["status"])
        source.write_text(original.replace('<main', '<main data-prototype-review-source="forged"', 1))
        with self.assertRaises(ValueError): self.envelope_v3()

    def test_v3_markdown_unique_payload_and_cross_version_binding(self):
        value = self.envelope_v3()
        markdown = "# 可读摘要\n这些文字不授予批准。\n\n" + feedback.MARKDOWN_PAYLOAD_HEADING + "\n```json\n" + json.dumps(value, ensure_ascii=False) + "\n```\n"
        self.assertEqual(value, feedback.parse_feedback(markdown.encode()))
        self.assertEqual("current", self.validate(feedback.parse_feedback(markdown.encode()))["status"])
        input_path = Path(self.temporary.name).resolve() / "feedback.md"
        input_path.write_text(markdown, encoding="utf-8")
        command = ["bash", str(PACK / "lib/python_runtime.sh"), "-B", "-X", "utf8", str(PACK / "lib/documents/prototype_feedback_cli.py"),
                   "validate", "--root", str(self.project), "--adapter", "project.yaml", "--input", str(input_path), "--data-dir", str(self.data_dir)]
        result = subprocess.run(command, text=True, capture_output=True)
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        self.assertEqual("current", json.loads(result.stdout)["status"])
        self.assertEqual(markdown, input_path.read_text())
        for bad in (markdown + markdown, markdown + "\n```json\n{}\n```", markdown.replace("```json", "```javascript"), markdown.replace(feedback.MARKDOWN_PAYLOAD_HEADING, "## 近似标题")):
            with self.subTest(bad=bad[-40:]), self.assertRaises(ValueError): feedback.parse_feedback(bad.encode())
        legacy = self.envelope()
        legacy["context"] = value["context"]
        with self.assertRaises(ValueError): self.validate(legacy)
        value["context"] = self.context
        with self.assertRaises(ValueError): self.validate(value)


if __name__ == "__main__":
    unittest.main()
