"""离线评审包与迁移事务的真实文件系统回归，只使用显式临时 data-dir。"""
from __future__ import annotations

import copy
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest import mock
from urllib.parse import urlsplit

from lib.documents import prototype_feedback as feedback
from lib.documents import prototype_review as review
from tests.test_prototype_feedback import legacy_fixture
from lib.documents.prototype_targets import inject_source_targets
from tests.test_prototype_workspace import PACK, PROTOTYPE_RELATIVE, bind_requirement_documents, tree_snapshot, write_valid_project


class PrototypeReviewTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="prototype-review-")
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name).resolve()
        self.project = write_valid_project(self.base / "project").resolve()
        self.plan, _ = bind_requirement_documents(self.project)
        self.page = (PROTOTYPE_RELATIVE / "settings.html").as_posix()
        source = self.project / self.page
        source.write_text(source.read_text().replace("<main>", "<main data-prototype-page-content>"), encoding="utf-8")
        self.prototype = self.project / PROTOTYPE_RELATIVE
        self.data = self.base / "data"

    def prepare(self, **kwargs):
        return feedback.prepare_review(self.project, "project.yaml", "docs/plans/settings.md", "review-1", [self.page], data_dir=self.data, **kwargs)

    def validate(self, ready):
        return feedback.validate_feedback(self.project, "project.yaml", {"schema_version": 3, "context": ready["context"], "anchors": [], "items": []}, data_dir=self.data)

    def preview(self, **kwargs):
        return review.migration_preview(self.project, "project.yaml", "docs/plans/settings.md", "review-1", [self.page], **kwargs)

    def test_released_v2_bundle_is_readable_without_new_assets_or_new_assembly(self):
        """把原提交真实派生包原样落盘，旧分支不可借新白名单或新装配通过。"""
        fixture, entries = legacy_fixture()
        context = fixture["context"]
        source = {name.removeprefix("source/"): body for name, body in entries.items() if name.startswith("source/")}
        bundle = {name.removeprefix("bundle/"): body for name, body in entries.items() if name.startswith("bundle/")}
        with review._request_directory(context, self.data, create=True) as (_, request_fd):
            descriptor = review._child(request_fd, context["review_id"])
            try:
                for name, body in bundle.items(): review._write_at(descriptor, name, body)
                review._tree(descriptor, freeze=True); os.fchmod(descriptor, 0o500)
            finally: os.close(descriptor)
        with mock.patch.object(review, "TOOL_ASSETS", ("nonexistent-new.js",)), mock.patch.object(review, "_assemble", side_effect=AssertionError("旧包调用了新装配")):
            result = review.validate_bundle(context, data_dir=self.data, source_files=source, navigation=fixture["navigation"], format_version=2)
        self.assertEqual(2, result["schema_version"])
        self.assertEqual(6, len([name for name in bundle if name.startswith("tool/") and name != "tool/version.txt"]))
        corrupted = dict(source); corrupted[self.page] += b"changed"
        with self.assertRaises(ValueError): review.validate_bundle(context, data_dir=self.data, source_files=corrupted, navigation=fixture["navigation"], format_version=2)

    def test_standalone_selected_page_has_no_index_or_tool_requirement(self):
        (self.prototype / "index.html").unlink()
        (self.prototype / "broken-unselected.html").write_text("unrelated unfinished business page")
        (self.prototype / "private-business.txt").write_text("not a render dependency")
        before = tree_snapshot(self.project)
        ready = self.prepare()
        bundle = Path(ready["bundle_path"])
        self.assertEqual("file", urlsplit(ready["review_url"]).scheme)
        self.assertEqual(before, tree_snapshot(self.project))
        self.assertFalse((bundle / "project" / PROTOTYPE_RELATIVE / "broken-unselected.html").exists())
        self.assertFalse((bundle / "project" / PROTOTYPE_RELATIVE / "private-business.txt").exists())
        self.assertTrue((bundle / "project" / self.page).is_file())
        original = (self.project / self.page).read_text()
        derived = (bundle / "project" / self.page).read_text()
        injection = '<script src="../../../../tool/page-shell.js" data-prototype-review-bridge="3"></script>'
        self.assertEqual(inject_source_targets(self.page, original.encode()).decode().replace("</body>", injection + "</body>"), derived)
        self.assertEqual("current", self.validate(ready)["status"])
        self.assertTrue(self.prepare()["reused"])
        command = ["bash", str(PACK / "lib/python_runtime.sh"), "-B", "-X", "utf8",
                   str(PACK / "lib/documents/validate_prototype_workspace.py"), str(self.project),
                   PROTOTYPE_RELATIVE.as_posix(), "--standalone", "--page", "settings.html", "--adapter", "project.yaml", "--json"]
        result = subprocess.run(command, text=True, capture_output=True)
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual(ready["context"]["pages"], json.loads(result.stdout)["pages"])

    def test_existing_standalone_main_gets_only_derived_content_marker(self):
        """旧合法HTML不必改源；唯一main兼容只发生在项目外派生快照中。"""
        source = self.project / self.page
        original = source.read_bytes().replace(b" data-prototype-page-content", b"")
        source.write_bytes(original)
        before = tree_snapshot(self.project)
        ready = self.prepare()
        derived = (Path(ready["bundle_path"]) / "project" / self.page).read_bytes()
        self.assertEqual(1, derived.count(b" data-prototype-page-content"))
        self.assertIn(b"data-prototype-review-source=", derived)
        self.assertEqual("current", self.validate(ready)["status"])
        self.assertEqual(original, source.read_bytes())
        self.assertEqual(before, tree_snapshot(self.project))
        for invalid in (original.replace(b"</body>", b"<main>ambiguous</main></body>"), original.replace(b"<main>", b"<section>").replace(b"</main>", b"</section>")):
            source.write_bytes(invalid)
            with self.assertRaises(ValueError): self.prepare()
            self.assertEqual(invalid, source.read_bytes())

    def test_custom_navigation_groups_labels_and_script_safe_boot(self):
        index = self.prototype / "index.html"
        index.write_text('<!doctype html><title>旧业务入口</title><details open><summary>设置 &amp; 账号</summary>'
                         '<details><summary>离线</summary><a href="./settings.html#legacy-state">设置 &lt;/script&gt; 中文</a></details></details>'
                         '<script>customBusiness()</script>')
        ready = self.prepare()
        source = (Path(ready["bundle_path"]) / "index.html").read_text()
        self.assertIn('id="prototype-review-data"', source)
        self.assertIn('\\u003c/script\\u003e', source)
        start = source.index('id="prototype-review-data">') + len('id="prototype-review-data">')
        boot = json.loads(source[start:source.index('</script>', start)])
        entry = boot["pages"][0]
        self.assertEqual("设置 </script> 中文", entry["label"])
        self.assertEqual([{"label": "设置 & 账号", "open": True}, {"label": "离线", "open": False}], entry["groups"])
        self.assertEqual("project/" + self.page, entry["url"])
        self.assertNotIn("customBusiness()", source)
        index.write_text(index.read_text() + '<a href="settings.html">重复</a>')
        with self.assertRaises(ValueError): self.prepare()

    def test_tool_upgrade_is_new_bundle_and_old_feedback_does_not_need_cache(self):
        fixture = self.base / "tool-fixture"
        (fixture / "product").mkdir(parents=True)
        (fixture / "templates/prototype").mkdir(parents=True)
        (fixture / "product/PLUGIN_VERSION").write_bytes((PACK / "product/PLUGIN_VERSION").read_bytes())
        for name in review.TOOL_ASSETS:
            (fixture / "templates/prototype" / name).write_bytes((PACK / "templates/prototype" / name).read_bytes())
        with mock.patch.object(review, "TOOL_ROOT", fixture):
            old = self.prepare()
            old_source = (Path(old["bundle_path"]) / "index.html").read_bytes()
            (fixture / "product/PLUGIN_VERSION").write_text("3.0.0-fixture-next\n")
            with (fixture / "templates/prototype/workspace.js").open("ab") as stream: stream.write(b"\n// next fixture\n")
            new = self.prepare()
            self.assertNotEqual(old["context"]["tool"], new["context"]["tool"])
            self.assertNotEqual(old["bundle_path"], new["bundle_path"])
            self.assertEqual(old_source, (Path(old["bundle_path"]) / "index.html").read_bytes())
        shutil.rmtree(fixture)
        self.assertEqual("current", self.validate(old)["status"])
        self.plan.write_bytes(self.plan.read_bytes() + b"changed")
        with self.assertRaises(ValueError): self.validate(old)

    def test_corruption_unknown_files_and_forged_manifest_are_rejected(self):
        ready = self.prepare(); bundle = Path(ready["bundle_path"])
        target = bundle / "index.html"
        original = target.read_bytes()
        target.chmod(0o600); target.write_bytes(original + b"broken")
        with self.assertRaises(ValueError): self.prepare()
        with self.assertRaises(ValueError): self.validate(ready)
        manifest_path = bundle / "manifest.json"
        manifest = json.loads(manifest_path.read_text())
        for entry in manifest["files"]:
            if entry["path"] == "index.html":
                entry.update(size=target.stat().st_size, sha256=review.digest(target.read_bytes()))
        manifest_path.chmod(0o600); manifest_path.write_bytes(review.json_bytes(manifest))
        # 即使篡改者同时重算清单摘要，派生物仍须匹配真实来源与固定工具。
        with self.assertRaises(ValueError): self.validate(ready)
        target.write_bytes(original)
        for entry in manifest["files"]:
            if entry["path"] == "index.html": entry.update(size=len(original), sha256=review.digest(original))
        manifest_path.write_bytes(review.json_bytes(manifest))
        bundle.chmod(0o700); (bundle / "unexpected.txt").write_text("extra")
        with self.assertRaises(ValueError): self.validate(ready)

    def test_private_no_follow_paths_hardlinks_and_schema_one_fail_closed(self):
        alias = self.base / "data-alias"; alias.symlink_to(self.base, target_is_directory=True)
        with self.assertRaises(ValueError):
            feedback.prepare_review(self.project, "project.yaml", "docs/plans/settings.md", "r", [self.page], data_dir=alias)
        self.data.mkdir(mode=0o755); self.data.chmod(0o755)
        with self.assertRaises(ValueError): self.prepare()
        self.data.chmod(0o700)
        ready = self.prepare(); bundle = Path(ready["bundle_path"])
        with self.assertRaises(ValueError):
            feedback.validate_feedback(self.project, "project.yaml", {"schema_version": 1, "context": ready["context"], "items": []}, data_dir=self.data)
        body = bundle / "tool/workspace.js"
        os.link(body, self.base / "linked-tool")
        with self.assertRaises(ValueError): self.validate(ready)
        (self.base / "linked-tool").unlink()
        body.parent.chmod(0o700); original = body.read_bytes(); body.unlink(); body.symlink_to(self.project / self.page)
        with self.assertRaises(ValueError): self.prepare()
        body.unlink(); body.write_bytes(original)

    def test_concurrent_real_process_publication_and_retry_share_one_bundle(self):
        command = ["bash", str(PACK / "lib/python_runtime.sh"), "-B", "-X", "utf8", str(PACK / "lib/documents/prototype_feedback_cli.py"),
                   "prepare", "--root", str(self.project), "--adapter", "project.yaml", "--plan", "docs/plans/settings.md",
                   "--request-id", "review-1", "--pages", self.page, "--data-dir", str(self.data)]
        def run(_): return subprocess.run(command, text=True, capture_output=True)
        with ThreadPoolExecutor(max_workers=3) as pool: results = list(pool.map(run, range(3)))
        paths = set()
        for result in results:
            if result.returncode:
                self.assertIn("正在发布", result.stdout, result.stderr)
                result = run(None)
            self.assertEqual(0, result.returncode, result.stdout + result.stderr)
            paths.add(json.loads(result.stdout)["bundle_path"])
        self.assertEqual(1, len(paths))
        bundle = Path(paths.pop())
        self.assertEqual([bundle.name], [path.name for path in bundle.parent.iterdir() if path.is_dir()])
        self.assertEqual(0o500, bundle.stat().st_mode & 0o777)
        self.assertEqual(0o400, (bundle / "index.html").stat().st_mode & 0o777)

    def test_failed_publication_keeps_old_bundle_and_does_not_publish_partial(self):
        old = self.prepare(); old_bytes = (Path(old["bundle_path"]) / "index.html").read_bytes()
        self.plan.write_bytes(self.plan.read_bytes() + b"\nREQ-002: new source\n")
        original = review._write_at
        writes = 0
        def fail(*args, **kwargs):
            nonlocal writes
            writes += 1
            if writes == 2: raise OSError("fixture interruption")
            return original(*args, **kwargs)
        with mock.patch.object(review, "_write_at", side_effect=fail), self.assertRaises(OSError): self.prepare()
        parent = Path(old["bundle_path"]).parent
        self.assertEqual(1, len([path for path in parent.iterdir() if path.name.startswith(".building-")]))
        self.assertEqual(old_bytes, (Path(old["bundle_path"]) / "index.html").read_bytes())
        new = self.prepare()
        self.assertNotEqual(old["bundle_path"], new["bundle_path"])
        self.assertEqual("current", self.validate(new)["status"])

    def test_migration_preserves_business_assets_and_requires_exact_preview(self):
        candidate = self.prototype / "feedback.css"
        candidate.write_bytes((PACK / "templates/prototype/feedback.css").read_bytes())
        for name in ("prototype.css", "prototype.js"):
            if name == "prototype.js": (self.prototype / name).write_text("// custom business JS")
        before = tree_snapshot(self.project)
        unknown = self.preview()
        self.assertEqual([], unknown["candidates"])
        self.assertEqual(before, tree_snapshot(self.project))
        preview = self.preview(confirm_no_active_use=True)
        paths = [item["path"] for item in preview["candidates"]]
        self.assertIn((PROTOTYPE_RELATIVE / "feedback.css").as_posix(), paths)
        self.assertNotIn((PROTOTYPE_RELATIVE / "page-shell.js").as_posix(), paths)
        self.assertTrue(any(item["path"].endswith("prototype.css") for item in preview["preserved"]))
        candidate.write_bytes(candidate.read_bytes() + b"/* user business rule */")
        with self.assertRaises(ValueError): review.migration_apply(self.project, "project.yaml", preview, data_dir=self.data)
        self.assertTrue(candidate.exists())
        candidate.write_bytes((PACK / "templates/prototype/feedback.css").read_bytes())
        result = review.migration_apply(self.project, "project.yaml", preview, data_dir=self.data)
        self.assertEqual("applied", result["status"])
        self.assertFalse(candidate.exists())
        self.assertTrue((self.prototype / "index.html").exists())
        self.assertTrue((self.prototype / "prototype.css").exists())
        self.assertEqual((PACK / "templates/prototype/feedback.css").read_bytes(),
                         (Path(result["recovery_path"]) / "preimages" / PROTOTYPE_RELATIVE / "feedback.css").read_bytes())

    def test_project_local_data_dir_and_interrupted_preimage_collection_are_safe(self):
        with self.assertRaises(ValueError):
            feedback.prepare_review(self.project, "project.yaml", "docs/plans/settings.md", "r", [self.page], data_dir=self.project / "private-data")
        self.assertFalse((self.project / "private-data").exists())
        candidate = self.prototype / "feedback.css"
        candidate.write_bytes((PACK / "templates/prototype/feedback.css").read_bytes())
        preview = self.preview(confirm_no_active_use=True)
        before = tree_snapshot(self.project)
        original = review._write_at
        def fail_preimage(root_fd, relative, body, **kwargs):
            if relative.startswith("preimages/"): raise OSError("fixture interrupted preimage collection")
            return original(root_fd, relative, body, **kwargs)
        with mock.patch.object(review, "_write_at", side_effect=fail_preimage), self.assertRaises(OSError):
            review.migration_apply(self.project, "project.yaml", preview, data_dir=self.data)
        self.assertEqual(before, tree_snapshot(self.project))
        self.assertEqual("recovered", review.migration_recover(self.project, "project.yaml", preview, data_dir=self.data)["status"])
        self.assertEqual("applied", review.migration_apply(self.project, "project.yaml", preview, data_dir=self.data)["status"])
        self.assertFalse(candidate.exists())

    def test_migration_atomic_move_preserves_racing_user_content(self):
        candidate = self.prototype / "feedback.css"
        candidate.write_bytes((PACK / "templates/prototype/feedback.css").read_bytes())
        preview = self.preview(confirm_no_active_use=True)
        rename = review.os.rename
        def replace_before_move(source, target, *args, **kwargs):
            if source == "feedback.css":
                candidate.write_text("new user business content during apply")
            return rename(source, target, *args, **kwargs)
        with mock.patch.object(review.os, "rename", side_effect=replace_before_move), self.assertRaises(ValueError):
            review.migration_apply(self.project, "project.yaml", preview, data_dir=self.data)
        self.assertEqual("new user business content during apply", candidate.read_text())

    def test_migration_failure_restores_exact_preimages_and_conflicts_do_not_overwrite(self):
        for name in ("feedback.css", "feedback.js"):
            (self.prototype / name).write_bytes((PACK / "templates/prototype" / name).read_bytes())
        preview = self.preview(confirm_no_active_use=True)
        before = tree_snapshot(self.project)
        rename = review.os.rename
        calls = 0
        def interrupt(name, target, *args, **kwargs):
            nonlocal calls
            if name in {"feedback.css", "feedback.js"}:
                calls += 1
                if calls == 2: raise OSError("fixture move interrupted")
            return rename(name, target, *args, **kwargs)
        with mock.patch.object(review.os, "rename", side_effect=interrupt), self.assertRaises(OSError):
            review.migration_apply(self.project, "project.yaml", preview, data_dir=self.data)
        # 恢复保留原业务字节、节点类型与权限，目录mtime可以合法变化。
        content = lambda entries: [(entry[0], entry[1], entry[2], entry[7]) for entry in entries]
        self.assertEqual(content(before), content(tree_snapshot(self.project)))
        self.assertEqual("recovered", review.migration_recover(self.project, "project.yaml", preview, data_dir=self.data)["status"])
        # 显式模拟进程中断后的 prepared 日志；恢复不得覆盖用户新内容。
        transaction = self.data / preview["context"]["project_id"] / "review-1/migrations" / preview["source_digest"]
        state = json.loads((transaction / "state.json").read_text()); state["status"] = "prepared"
        (transaction / "state.json").write_bytes(review.json_bytes(state))
        changed = self.project / preview["candidates"][0]["path"]
        changed.write_text("user new contents")
        with self.assertRaises(ValueError): review.migration_recover(self.project, "project.yaml", preview, data_dir=self.data)
        self.assertEqual("user new contents", changed.read_text())
        self.assertEqual("recovery_conflict", json.loads((transaction / "state.json").read_text())["status"])


if __name__ == "__main__": unittest.main()
