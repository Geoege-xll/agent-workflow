"""受管文件交付独立责任：真实目录、精确标签、窄依赖例外和条件发布负控。"""
from __future__ import annotations

import os
import hashlib
import json
from pathlib import Path
import unittest
from unittest import mock

from lib.documents import prototype_file_entry as entry
from lib.documents import prototype_review as review
from lib.documents import validate_prototype_workspace as workspace
from lib.documents.prototype_targets import inject_source_targets, capture_targets
from tests.test_prototype_live import live_fixture
from tests.test_prototype_workspace import tree_snapshot


class PrototypeFileEntryTest(unittest.TestCase):
    def setUp(self):
        self.base, self.project, self.page, self.data = live_fixture()
        self.prototype = (self.project / self.page).parent

    def prepare(self, pages=None):
        return entry.prepare_delivery(self.project, "project.yaml", pages or [self.page], data_dir=self.data)

    def test_exact_tag_ignores_comment_example_and_preserves_original_source_keys(self):
        body = ('<!doctype html><html><head><!--' + entry.ENTRY + '-->' + entry.ENTRY + '</head><body><main data-prototype-page-content><p>中文匿名节点</p></main></body></html>').encode()
        self.assertTrue(entry.entry_present(body))
        metadata = capture_targets(self.page, body)
        rendered = entry.strip_entry(inject_source_targets(self.page, body))
        self.assertIn(b"<!--" + entry.ENTRY.encode() + b"-->", rendered)
        for key in metadata["source_keys"]: self.assertIn(key.encode(), rendered)
        self.assertFalse(entry.entry_present(rendered))
        self.assertFalse(entry.entry_present(("<!--" + entry.ENTRY + "-->").encode()))
        for bad in (entry.ENTRY.replace('charset="utf-8"', 'charset="UTF-8"'), '<script>1</script>' + entry.ENTRY,
                    entry.ENTRY + entry.ENTRY):
            with self.assertRaises(entry.PreparationError): entry.entry_present(bad.encode())

    def test_presentation_uses_declared_frame_without_guessing(self):
        self.assertEqual({"platform": "", "display": "", "viewport": None, "plan_source": ""}, entry.presentation(b"<body><div></div></body>"))
        declared = b'<body data-prototype-platform="ios" data-prototype-display="fixed"><div class="prototype-frame" style="--prototype-frame-width:390px;--prototype-frame-height:844px"></div></body>'
        self.assertEqual({"width": 390, "height": 844}, entry.presentation(declared)["viewport"])
        for invalid in (b"-1px", b"99999px", b"100%", b"var(--width)"):
            self.assertIsNone(entry.presentation(declared.replace(b"390px", invalid))["viewport"])

    def test_prepare_idempotence_trusted_mount_catalog_binding_and_fingerprint(self):
        self.prepare()
        before = tree_snapshot(self.project)
        self.assertEqual("prepared", self.prepare()["status"])
        self.assertEqual(before, tree_snapshot(self.project))
        catalog = entry.require_prepared(self.project, "project.yaml", [self.page], data_dir=self.data)
        self.assertEqual({"schema_version", "project_id", "directory_sha256", "tool", "pages"}, set(catalog))
        self.assertEqual(1, (self.project / self.page).read_text().count(entry.ENTRY))
        source = workspace.capture_selected_pages(self.project, str(Path(self.page).parent), pages=[Path(self.page).name], adapter="project.yaml")
        self.assertFalse(any(entry.MOUNT in name for name in source["files"]))
        fingerprint = source["pages"][0]["dependency_fingerprint"]
        context = {"project_id": catalog["project_id"], "request_id": "public-binding", "review_id": "f" * 64}
        entry.publish_binding(self.project, "project.yaml", [self.page], context, {"instance": "a" * 48, "port": 43210}, data_dir=self.data)
        current = workspace.capture_selected_pages(self.project, str(Path(self.page).parent), pages=[Path(self.page).name], adapter="project.yaml")
        self.assertEqual(fingerprint, current["pages"][0]["dependency_fingerprint"])
        text = (self.prototype / entry.MOUNT / "catalog.js").read_text()
        for forbidden in ("token", "management", str(self.project), "argv", "active_request"):
            self.assertNotIn(forbidden, text)
        self.assertFalse(any(path.suffix == ".html" for path in (self.data / catalog["project_id"] / "delivery").iterdir()))

    @staticmethod
    def historical_file_tool(version):
        """构造已冻结17项schema的有界测试输入，不把它冒称历史发行运行时。"""
        _, captured = review.capture_tool(format_version=5)
        # 这是旧发布schema的fixture数据，独立于当前LIVE名单；今后当前包再新增资产
        # 不能悄悄进入历史测试输入，也不能靠引用生产私有常量掩盖历史名单被改动。
        historical_names = (
            "delivery.html", "review.html", "live-workspace.js", "live-connection.js",
            "canvas-host.js", "live.css", "workspace.css", "review-state.js", "review-camera.js",
            "feedback.js", "feedback.css", "page-shell.js", "THIRD_PARTY_NOTICES.txt",
            "file-entry.js", "file-delivery.js", "file-page.js", "canvas-presentation.js",
        )
        tools = {"tool/" + name: captured["tool/" + name] for name in historical_names}
        raw_version = (version + "\n").encode()
        tools["tool/version.txt"] = raw_version
        assets = {name.removeprefix("tool/"): body for name, body in tools.items()
                  if name != "tool/version.txt"}
        # 真实3.0.5 helper→当前helper的原字节升级另有发行证据；此处执行生产发布/
        # 验证路径，专门保护封闭名单、version/catalog绑定、完整摘要与补偿边界。
        return {"version": version, "payload_sha256": review._payload(raw_version, assets, format_version=5)}, tools

    def verify_current_mount(self):
        fd = workspace._open_root(self.prototype, "受管历史工具负控")
        try:
            return entry.verify_mount(fd, self.project, str(Path(self.page).parent), expected_data_dir=self.data)
        finally:
            os.close(fd)

    def test_published_file_tool_schema_upgrades_without_rewriting_original(self):
        """旧3.0.4/3.0.5完整挂载可维护升级，不能因当前新增主题资产而误判篡改。"""
        self.prepare()
        original = (self.project / self.page).read_bytes()
        for version in ("3.0.4", "3.0.5"):
            with self.subTest(version=version):
                historical = self.historical_file_tool(version)
                with mock.patch.object(review, "capture_tool", return_value=historical):
                    self.prepare()
                self.assertEqual(historical[0], self.verify_current_mount()["tool"])
                # 识别旧完整挂载并不把旧代码当作当前正式工具；open仍要求重新prepare。
                with self.assertRaisesRegex(entry.PreparationError, "交付工具版本已更新"):
                    entry.require_prepared(self.project, "project.yaml", [self.page], data_dir=self.data)
                self.assertEqual("prepared", self.prepare()["status"])
                current, _ = review.capture_tool(format_version=5)
                self.assertEqual(current, self.verify_current_mount()["tool"])
                self.assertEqual(original, (self.project / self.page).read_bytes())

    def test_file_tool_schema_never_accepts_missing_unknown_or_tampered_assets(self):
        """新闭包缺主题、历史闭包变造/多项与新版本伪装旧schema均保持拒绝。"""
        self.prepare()
        original = (self.project / self.page).read_bytes()
        cache = self.prototype / entry.MOUNT / "assets"
        for missing in (("tool-theme.css",), ("tool-theme.css", "solid-glass-LICENSE.txt")):
            saved = {name: ((cache / name).read_bytes(), (cache / name).stat().st_mode & 0o777) for name in missing}
            try:
                for name in missing: (cache / name).unlink()
                with self.subTest(missing=missing), self.assertRaises(entry.PreparationError):
                    self.verify_current_mount()
            finally:
                for name, (body, mode) in saved.items():
                    (cache / name).write_bytes(body); (cache / name).chmod(mode)
        historical = self.historical_file_tool("3.0.5")
        with mock.patch.object(review, "capture_tool", return_value=historical):
            self.prepare()
        self.verify_current_mount()
        for name, body in (("unknown.js", b"unknown"), ("file-page.js", b"changed"), ("shell.js", b"changed"), ("version.txt", b"3.0.6\n")):
            path = cache / name
            before = path.read_bytes() if path.exists() else None
            mode = path.stat().st_mode & 0o777 if path.exists() else None
            try:
                if mode is not None: path.chmod(0o600)
                path.write_bytes(body)
                with self.subTest(changed=name), self.assertRaises(entry.PreparationError):
                    self.verify_current_mount()
            finally:
                if before is None: path.unlink()
                else: path.write_bytes(before); path.chmod(mode)
        self.prepare()
        for version in ("3.0.3", "3.0.6", "2.9.9"):
            before = tree_snapshot(self.project)
            with self.subTest(impostor_version=version), mock.patch.object(review, "capture_tool", return_value=self.historical_file_tool(version)):
                with self.assertRaises(entry.PreparationError): self.prepare()
            self.assertEqual(before, tree_snapshot(self.project), "被拒绝的schema不能改业务原稿或现有挂载")
        self.assertEqual(original, (self.project / self.page).read_bytes())

    def test_tampering_mount_cache_tag_and_hardlink_rejected_without_source_mutation(self):
        self.prepare()
        original = (self.project / self.page).read_bytes()
        mount = self.prototype / entry.MOUNT
        destination = os.readlink(mount)
        try:
            mount.unlink(); mount.symlink_to(self.prototype)
            with self.assertRaises(entry.PreparationError): entry.require_prepared(self.project, "project.yaml", [self.page], data_dir=self.data)
        finally:
            mount.unlink(); mount.symlink_to(destination)
        cache_file = mount / "assets" / "file-page.js"
        body = cache_file.read_bytes(); mode = cache_file.stat().st_mode & 0o777
        try:
            cache_file.chmod(0o600); cache_file.write_bytes(body + b"\nchanged")
            with self.assertRaises(entry.PreparationError): entry.require_prepared(self.project, "project.yaml", [self.page], data_dir=self.data)
        finally: cache_file.write_bytes(body); cache_file.chmod(mode)
        try:
            (self.project / self.page).write_bytes(original.replace(b'charset="utf-8"></script>', b'charset="UTF-8"></script>', 1))
            before = tree_snapshot(self.project)
            with self.assertRaises(ValueError): self.prepare()
            self.assertEqual(before, tree_snapshot(self.project))
        finally: (self.project / self.page).write_bytes(original)
        linked = self.base / "file-core-negative-hardlink"
        try:
            os.link(self.project / self.page, linked)
            with self.assertRaises(ValueError): entry.require_prepared(self.project, "project.yaml", [self.page], data_dir=self.data)
        finally: linked.unlink(missing_ok=True)

    def test_cas_conflict_does_not_overwrite_user_bytes(self):
        fd = workspace._open_root(self.prototype, "条件写入负控")
        try:
            original = review._read_at(fd, Path(self.page).name)
            with self.assertRaisesRegex(ValueError, "用户修改已保留"):
                entry._cas(fd, Path(self.page).name, original + b"wrong expected", b"must not write")
            self.assertEqual(original, review._read_at(fd, Path(self.page).name))
        finally: os.close(fd)

    def test_open_requires_explicit_preparation_and_page_bindings_merge(self):
        from lib.documents.prototype_service import open_service
        self.prepare()
        path = self.project / self.page
        source = path.read_bytes()
        try:
            path.write_bytes(entry.strip_entry(source))
            before = tree_snapshot(self.project)
            with self.assertRaises(entry.PreparationError) as caught:
                open_service(self.project, "project.yaml", "docs/plans/settings.md", "not-prepared", [self.page], data_dir=self.data)
            self.assertEqual("preparation_required", caught.exception.code)
            self.assertEqual(before, tree_snapshot(self.project))
        finally: path.write_bytes(source)
        details = str(Path(self.page).with_name("details.html"))
        self.prepare([details])
        value = entry.require_prepared(self.project, "project.yaml", [self.page, details], data_dir=self.data)
        for page, request, digit in ((self.page, "page-a", "a"), (details, "page-b", "b")):
            context = {"project_id": value["project_id"], "request_id": request, "review_id": digit * 64}
            entry.publish_binding(self.project, "project.yaml", [page], context, {"instance": digit * 48, "port": 43210}, data_dir=self.data)
        merged = entry.require_prepared(self.project, "project.yaml", [self.page, details], data_dir=self.data)
        self.assertEqual({self.page: "page-a", details: "page-b"}, {page["path"]: page["binding"]["request_id"] for page in merged["pages"]})

    def test_multifile_failure_restores_unchanged_output_and_preserves_user_edit(self):
        details = str(Path(self.page).with_name("details.html"))
        self.prepare([self.page, details])
        paths = [self.project / page for page in (self.page, details)]
        originals = [path.read_bytes() for path in paths]
        catalog_path = self.prototype / entry.MOUNT / "catalog.js"
        old_catalog = catalog_path.read_bytes()
        real_cas = entry._cas
        try:
            first = entry.strip_entry(originals[0]).replace(b"<title>Settings</title>", b"<title>Transaction</title>")
            second = entry.strip_entry(originals[1])
            paths[0].write_bytes(first); paths[1].write_bytes(second)
            user_edit = second + b"\n<!-- user concurrent edit -->"
            def fail_second(fd, name, expected, body, **kwargs):
                if name == paths[1].name and entry.ENTRY.encode() in body:
                    paths[1].write_bytes(user_edit)
                    raise ValueError("预定负控：第二原稿发生并发修改")
                return real_cas(fd, name, expected, body, **kwargs)
            with mock.patch.object(entry, "_cas", side_effect=fail_second):
                with self.assertRaisesRegex(ValueError, "预定负控"): self.prepare([self.page, details])
            self.assertEqual(first, paths[0].read_bytes())
            self.assertEqual(user_edit, paths[1].read_bytes())
            self.assertEqual(old_catalog, catalog_path.read_bytes())
        finally:
            for path, original in zip(paths, originals): path.write_bytes(original)

    def test_prepared_source_is_consumable_by_v4_without_copying_file_entry(self):
        from lib.documents.prototype_feedback import prepare_review, validate_feedback
        self.prepare()
        before = (self.project / self.page).read_bytes()
        ready = prepare_review(self.project, "project.yaml", "docs/plans/settings.md", "prepared-v4", [self.page], data_dir=self.data)
        context = ready["context"]
        with review._request_directory(context, self.data, create=False) as (_, fd):
            bundle = review._read_at(fd, context["review_id"] + "/project/" + self.page)
        self.assertNotIn(entry.ENTRY.encode(), bundle)
        self.assertIn(b"data-prototype-review-source=", bundle)
        self.assertEqual(before, (self.project / self.page).read_bytes())
        self.assertEqual("current", validate_feedback(self.project, "project.yaml", {"schema_version": 4,
            "review": {key: context[key] for key in ("request_id", "review_id")}, "anchors": [], "items": []}, data_dir=self.data)["status"])
        path = self.project / self.page
        try:
            # 同provider原地验证无tag公开prepare；以旧装配的identity-strip投影比较
            # 完整派生字节，证明兼容分支没有为新入口改变原本无tag的V4输出。
            path.write_bytes(entry.strip_entry(before))
            legacy = prepare_review(self.project, "project.yaml", "docs/plans/settings.md", "untagged-v4", [self.page], data_dir=self.data)
            tool, tools = review.capture_tool()
            current, _, files, navigation = review.capture_review(self.project, "project.yaml", "docs/plans/settings.md", "untagged-v4", [self.page], tool=tool)
            with mock.patch.object(entry, "strip_entry", side_effect=lambda value: value):
                unchanged = review._assemble(current, files, tools, navigation)
            self.assertEqual(unchanged["project/" + self.page], (Path(legacy["bundle_path"]) / "project" / self.page).read_bytes())
            self.assertEqual("current", validate_feedback(self.project, "project.yaml", {"schema_version": 4,
                "review": {key: current[key] for key in ("request_id", "review_id")}, "anchors": [], "items": []}, data_dir=self.data)["status"])
        finally: path.write_bytes(before)

    def test_directory_digest_and_public_field_bounds_fail_closed(self):
        self.prepare()
        path = self.prototype / entry.MOUNT / "catalog.js"
        raw = path.read_bytes()
        value = json.loads(raw[len(entry.CATALOG_PREFIX):-3])
        expected = hashlib.sha256((self.prototype.as_uri() + "/").encode("utf-8")).hexdigest()
        self.assertEqual(expected, value["directory_sha256"])
        try:
            for change in ({"directory_sha256": "f" * 64}, {"token": "not-public"}):
                path.write_bytes(entry.CATALOG_PREFIX + review.json_bytes({**value, **change}) + b");\n")
                with self.assertRaises(entry.PreparationError): entry.require_prepared(self.project, "project.yaml", [self.page], data_dir=self.data)
            for size, accepted in ((1, True), (16384, True), (0, False), (16385, False), (True, False)):
                registered = next(page for page in value["pages"] if page["path"] == self.page)
                page = {**registered, "label": "长" * 1024, "viewport": {"width": size, "height": size}}
                path.write_bytes(entry.CATALOG_PREFIX + review.json_bytes({**value, "pages": [page]}) + b");\n")
                if accepted: entry.require_prepared(self.project, "project.yaml", [self.page], data_dir=self.data)
                else:
                    with self.assertRaises(entry.PreparationError): entry.require_prepared(self.project, "project.yaml", [self.page], data_dir=self.data)
        finally: path.write_bytes(raw)

    def test_catalog_display_projection_preserves_original_live_navigation_identity(self):
        from lib.documents.prototype_live import capture_live
        self.prepare()
        tool, _ = review.capture_tool(format_version=5)
        before, _, files, navigation = capture_live(self.project, "project.yaml", "docs/plans/settings.md", "display-projection", [self.page], tool=tool)
        source = files[self.page]
        try:
            # 只改变file目录的纯展示投影，同tool、同原稿字节下不得改变旧live5的
            # canonical导航/修订；HTTP startup和feedback继续使用原五字段页面合同。
            with mock.patch.object(entry, "presentation", return_value={"platform": "ios", "display": "fixed",
                    "viewport": {"width": 390, "height": 844}, "plan_source": ""}):
                self.prepare()
            after, _, new_files, new_navigation = capture_live(self.project, "project.yaml", "docs/plans/settings.md", "display-projection", [self.page], tool=tool)
            self.assertEqual(source, new_files[self.page])
            self.assertEqual(before, after)
            self.assertEqual(navigation, new_navigation)
            self.assertEqual({"name", "path", "url", "label", "groups"}, set(navigation[0]))
            self.assertEqual(review.digest(review.json_bytes(navigation)), before["navigation_sha256"])
        finally: self.prepare()

    def test_delivery_directory_exceeds_review_batch_and_merges_across_prepares(self):
        from lib.documents.prototype_live import capture_live
        self.prepare()
        catalog_path = self.prototype / entry.MOUNT / "catalog.js"
        original_catalog = catalog_path.read_bytes()
        source = entry.strip_entry((self.project / self.page).read_bytes())
        generated = []
        try:
            # 在同provider原地创建真实的18个具体页，仅为目录范围负控；没有复制源树、
            # 工具载荷或独立环境。名字独占本节点，收尾仅删除正文仍与本测试相符的文件。
            for number in range(18):
                path = self.prototype / f"delivery-bound-{number:02d}.html"
                self.assertFalse(path.exists())
                path.write_bytes(source); generated.append(path)
            pages = [path.relative_to(self.project).as_posix() for path in generated]
            self.prepare(pages[:17])
            self.prepare(pages[17:])
            value = entry.require_prepared(self.project, "project.yaml", pages, data_dir=self.data)
            self.assertTrue(set(pages) <= {page["path"] for page in value["pages"]})
            self.assertGreater(len(value["pages"]), 16)
            self.assertLessEqual(len(catalog_path.read_bytes()), review.MAX_MANIFEST_BYTES)
            with self.assertRaises(ValueError):
                capture_live(self.project, "project.yaml", "docs/plans/settings.md", "review-limit", pages[:17])
            # 生产序列化在任何换名前拒绝超过原字节预算的目录，原可读目录保持完整。
            current = catalog_path.read_bytes()
            with entry._delivery(self.project, self.data) as (_, fd):
                with mock.patch.object(review, "MAX_MANIFEST_BYTES", len(current) - 1):
                    with self.assertRaisesRegex(ValueError, "字节限额"): entry._write_catalog(fd, value)
            self.assertEqual(current, catalog_path.read_bytes())
        finally:
            catalog_path.write_bytes(original_catalog)
            for path in generated:
                if entry.strip_entry(path.read_bytes()) == source: path.unlink()


if __name__ == "__main__": unittest.main()
