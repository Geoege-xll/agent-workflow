"""活动来源5的真实文件系统测试；同一运行复用一个最小fixture，不复制源树。"""
from __future__ import annotations

import atexit
import copy
from functools import lru_cache
import json
import os
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest import mock

from lib.documents import prototype_feedback as feedback
from lib.documents import prototype_review as review
from lib.documents.prototype_live import (LiveSource, capture_live, register_live, resolve_live,
    check_draft, LiveError, live_directory)
from tests.test_prototype_workspace import (write_valid_project, bind_requirement_documents,
    PROTOTYPE_RELATIVE, tree_snapshot)


@lru_cache(maxsize=1)
def live_fixture():
    selected = os.environ.get("AGENT_WORKFLOW_PROTOTYPE_FIXTURE")
    base = Path(selected) if selected else Path(tempfile.mkdtemp(prefix="prototype-live-"))
    if not selected: atexit.register(shutil.rmtree, base, ignore_errors=True)
    base.mkdir(parents=True, exist_ok=True)
    project = base / "Project"
    if not project.exists():
        project = write_valid_project(base).resolve()
        bind_requirement_documents(project)
        page = project / PROTOTYPE_RELATIVE / "settings.html"
        source = page.read_text().replace("<main>", "<main data-prototype-page-content>")
        source = source.replace("</main>", '<button id="open-popover" popovertarget="settings-popover" type="button">Open popover</button><div id="settings-popover" popover><p id="popover-text">Popover source content</p></div></main>')
        source = source.replace("</tbody>", '<tr data-contract-for="open-popover"><td>Open popover</td><td>Click</td><td>Show the source popover.</td><td>Opening does not change values.</td></tr></tbody>')
        page.write_text(source, encoding="utf-8")
        (page.parent / "details.html").write_text(source.replace("<title>Settings</title>", "<title>Details</title>"), encoding="utf-8")
    page = (PROTOTYPE_RELATIVE / "settings.html").as_posix()
    data = base / "data"
    return base, project, page, data


def empty_draft(context):
    return {"schema_version": 5, "review_id": context["review_id"], "anchors": [], "items": [], "drafts": {},
        "withdrawn": None, "nextAnchor": 1, "nextItem": 1, "cameras": {}}


class PrototypeLiveTest(unittest.TestCase):
    def setUp(self):
        self.base, self.project, self.page, self.data = live_fixture()
        self.context, self.metadata, _, _ = capture_live(self.project, "project.yaml", "docs/plans/settings.md", "live-test", [self.page])
        register_live(self.project, self.context, data_dir=self.data)
        self.source = LiveSource(self.project, self.context, data_dir=self.data)

    def test_live_metadata_feedback5_and_historical_asset_freeze(self):
        before = tree_snapshot(self.project)
        reference = {key: self.context[key] for key in ("request_id", "review_id")}
        self.assertEqual(self.context, resolve_live(self.project, reference, data_dir=self.data))
        envelope = {"schema_version": 5, "review": reference, "anchors": [], "items": [{"id": "item-1", "number": 1,
            "operation": "modify", "target": {"scope": "node", "page": self.page, "locator": {"type": "id", "id": "open-settings-dialog"}}, "message": "打开弹窗"}]}
        self.assertEqual("current", feedback.validate_feedback(self.project, "project.yaml", envelope, data_dir=self.data)["status"])
        self.assertEqual(envelope, feedback.parse_feedback(review.json_bytes(envelope)))
        with self.assertRaises(ValueError):
            feedback.validate_feedback(self.project, "project.yaml", {**envelope, "schema_version": 4}, data_dir=self.data)
        with mock.patch.object(review, "TOOL_ASSETS", ("never-existing-new-live.js",)):
            ready = feedback.prepare_review(self.project, "project.yaml", "docs/plans/settings.md", "historical-4", [self.page], data_dir=self.data)
            feedback.validate_feedback(self.project, "project.yaml", {"schema_version": 4, "review": {key: ready["context"][key] for key in ("request_id", "review_id")}, "anchors": [], "items": []}, data_dir=self.data)
        self.assertEqual(9, len(review.V4_TOOL_ASSETS))
        self.assertEqual(before, tree_snapshot(self.project))
        with live_directory(self.context, self.data) as (directory, _):
            self.assertEqual({"metadata.json"}, {path.name for path in directory.iterdir()} - {"draft.json"})

    def test_draft_cas_source_change_retains_original_and_precise_reference(self):
        draft = empty_draft(self.context)
        initial = self.source.read_draft()["revision"]
        saved = self.source.save_draft(initial, draft)
        self.assertEqual(initial + 1, saved["revision"])
        with self.assertRaises(LiveError) as conflict: self.source.save_draft(initial, draft)
        self.assertEqual("draft_conflict", conflict.exception.code)
        plan = self.project / "docs/plans/settings.md"
        original = plan.read_bytes()
        try:
            plan.write_bytes(original + b"\nchanged\n")
            with self.assertRaises(LiveError) as changed: self.source.save_draft(saved["revision"], draft)
            self.assertEqual("source_changed", changed.exception.code)
            self.assertEqual(saved, self.source.read_draft())
            current, _, _, _ = capture_live(self.project, "project.yaml", "docs/plans/settings.md", "live-test", [self.page])
            register_live(self.project, current, data_dir=self.data)
            self.assertNotEqual(self.context["review_id"], current["review_id"])
            self.assertEqual(self.context, resolve_live(self.project, {key: self.context[key] for key in ("request_id", "review_id")}, data_dir=self.data))
        finally: plan.write_bytes(original)

    def test_closed_snapshot_rejects_unknown_source_types_and_unsafe_numbers(self):
        draft = empty_draft(self.context)
        self.assertEqual(draft, check_draft(draft, self.context, self.metadata))
        for bad in ({**draft, "context": self.context}, {**draft, "nextItem": True}, {**draft, "schema_version": 4},
                    {**draft, "cameras": {self.page: {"k": float("nan"), "x": 0, "y": 0}}}):
            with self.assertRaises(ValueError): check_draft(bad, self.context, self.metadata)
        bad = copy.deepcopy(draft)
        bad["anchors"] = [{"id": "a-1", "number": 1, "target": {"scope": "node", "page": self.page,
            "locator": {"type": "id", "id": "contract-section"}}}]
        bad["nextAnchor"] = 2
        with self.assertRaises(ValueError): check_draft(bad, self.context, self.metadata)

    def test_live_ignores_absent_added_and_changed_legacy_index_but_v4_keeps_binding(self):
        """真实index三态均不能重绑live；历史4仍必须按原索引字节和标签变化。"""
        index = self.project / PROTOTYPE_RELATIVE / "index.html"
        original = index.read_bytes() if index.exists() else None
        snapshot = review.snapshot
        def reject_index_read(path, *args, **kwargs):
            if Path(path) == index: raise AssertionError("live不应读取可选旧index")
            return snapshot(path, *args, **kwargs)
        try:
            index.unlink(missing_ok=True)
            with mock.patch.object(review, "snapshot", side_effect=reject_index_read):
                absent, _, _, navigation = capture_live(self.project, "project.yaml", "docs/plans/settings.md", "live-test", [self.page])
            self.assertEqual(self.context, absent)
            self.assertEqual([], navigation[0]["groups"])
            self.assertEqual("settings.html", navigation[0]["name"])
            envelope = {"schema_version": 5, "review": {key: absent[key] for key in ("request_id", "review_id")}, "anchors": [], "items": []}
            legacy_tool, _ = review.capture_tool()
            historical = []
            for label in ("Legacy label A", "Legacy label B"):
                body = ('<!doctype html><html><head><title>Legacy</title></head><body><details open><summary>Legacy group</summary><a href="settings.html">' + label + '</a></details></body></html>').encode()
                index.write_bytes(body)
                with mock.patch.object(review, "snapshot", side_effect=reject_index_read):
                    current, _, _, current_navigation = capture_live(self.project, "project.yaml", "docs/plans/settings.md", "live-test", [self.page])
                    self.source.current()
                    result = feedback.validate_feedback(self.project, "project.yaml", envelope, data_dir=self.data)
                self.assertEqual(absent, current)
                self.assertEqual(navigation, current_navigation)
                self.assertEqual("current", result["status"])
                old, _, _, old_navigation = review.capture_review(self.project, "project.yaml", "docs/plans/settings.md", "index-history-control", [self.page], tool=legacy_tool)
                self.assertEqual(review.digest(body), old["navigation_sha256"])
                self.assertEqual(label, old_navigation[0]["label"])
                historical.append(old)
            self.assertNotEqual(historical[0]["review_id"], historical[1]["review_id"])
            self.assertNotEqual(historical[0]["navigation_sha256"], historical[1]["navigation_sha256"])
        finally:
            if original is None: index.unlink(missing_ok=True)
            else: index.write_bytes(original)


if __name__ == "__main__": unittest.main()
