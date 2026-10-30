"""原型指纹必须复用静态验证的安全字节快照，且按页面隔离依赖闭包。"""

from __future__ import annotations

import contextlib
import hashlib
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from lib import validate_prototype_workspace as validator
from tests.test_prototype_workspace import (
    PAGE_HTML,
    PROTOTYPE_RELATIVE,
    tree_snapshot,
    write_valid_project,
)


class PrototypeFingerprintTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="prototype-fingerprint-")
        self.addCleanup(self.temporary.cleanup)
        self.project = write_valid_project(Path(self.temporary.name)).resolve()
        self.prototype = self.project / PROTOTYPE_RELATIVE

    def run_cli(self, *arguments: str) -> tuple[int, str, str]:
        stdout, stderr = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            code = validator.main([
                "validate_prototype_workspace.py", str(self.project),
                PROTOTYPE_RELATIVE.as_posix(), *arguments,
            ])
        return code, stdout.getvalue(), stderr.getvalue()

    def fingerprints(self, *arguments: str) -> dict[str, str]:
        code, stdout, stderr = self.run_cli("--json", *arguments)
        self.assertEqual(0, code, stdout + stderr)
        result = json.loads(stdout)
        self.assertEqual({"pages"}, set(result))
        return {page["path"]: page["dependency_fingerprint"] for page in result["pages"]}

    def rewrite(self, name: str, before: str, after: str) -> None:
        path = self.prototype / name
        body = path.read_text(encoding="utf-8")
        self.assertIn(before, body)
        path.write_text(body.replace(before, after, 1), encoding="utf-8")

    def add_page(self, name: str = "reports.html") -> None:
        (self.prototype / name).write_text(PAGE_HTML, encoding="utf-8")
        self.rewrite("index.html", "</nav>", f'<a href="{name}">Reports</a></nav>')

    def add_script(self, body: str) -> None:
        (self.prototype / "page.js").write_text(body, encoding="utf-8")
        self.rewrite("settings.html", "</head>", '<script type="module" src="page.js"></script></head>')

    def test_default_output_and_public_api_match_fixed_hash_domain(self) -> None:
        before = tree_snapshot(self.project)
        actual = self.fingerprints()
        digest = hashlib.sha256(b"agent-workflow/prototype-dependency-fingerprint/v1\0")
        # 独立构造规范编码，避免测试仅用实现自身的哈希函数来证明自身正确。
        for name in ["prototype.css", "settings.html"]:
            path_bytes = name.encode("utf-8")
            raw = (self.prototype / name).read_bytes()
            digest.update(len(path_bytes).to_bytes(8, "big"))
            digest.update(path_bytes)
            digest.update(len(raw).to_bytes(8, "big"))
            digest.update(raw)
        page = (PROTOTYPE_RELATIVE / "settings.html").as_posix()
        self.assertEqual({page: digest.hexdigest()}, actual)
        self.assertEqual({"pages": [{"path": page, "dependency_fingerprint": actual[page]}]},
                         validator.validate_workspace(self.project, PROTOTYPE_RELATIVE.as_posix()))
        self.assertEqual(actual, self.fingerprints())
        self.assertEqual(before, tree_snapshot(self.project))

    def test_legacy_success_text_is_unchanged(self) -> None:
        code, stdout, stderr = self.run_cli()
        self.assertEqual((0, f"[OK] prototype workspace is valid: {PROTOTYPE_RELATIVE.as_posix()}\n", ""),
                         (code, stdout, stderr))

    def test_normalized_paths_use_string_order_and_length_prefixes(self) -> None:
        (self.prototype / "a").mkdir()
        (self.prototype / "a" / "icon.bin").write_bytes(b"nested")
        (self.prototype / "a.bin").write_bytes(b"flat")
        self.rewrite("settings.html", "</main>",
                     '<img src="a/../a.bin?cache=1" alt="Flat">'
                     '<img src="a/./icon.bin" alt="Nested"></main>')
        actual = next(iter(self.fingerprints().values()))
        digest = hashlib.sha256(b"agent-workflow/prototype-dependency-fingerprint/v1\0")
        # 完整路径的字符串排序与 PurePosixPath 的分段排序不同，这里固定协议选择。
        for name in ["a.bin", "a/icon.bin", "prototype.css", "settings.html"]:
            path_bytes, raw = name.encode("utf-8"), (self.prototype / name).read_bytes()
            for field in (path_bytes, raw):
                digest.update(len(field).to_bytes(8, "big"))
                digest.update(field)
        self.assertEqual(digest.hexdigest(), actual)

    def test_media_srcset_inline_css_and_inline_js_are_in_the_closure(self) -> None:
        for name in ["first.bin", "second.bin", "poster.bin", "inline.bin"]:
            (self.prototype / name).write_bytes(b"\x00\xffinitial")
        (self.prototype / "inline.js").write_text("export const ready = true;", encoding="utf-8")
        self.rewrite("settings.html", "</main>",
                     '<img srcset="first.bin 1x, second.bin 2x" alt="Preview">'
                     '<video poster="poster.bin"></video>'
                     '<div style="background: url(inline.bin)">Inline style</div>'
                     '<script type="module">import "inline.js";</script></main>')
        for name in ["first.bin", "second.bin", "poster.bin", "inline.bin", "inline.js"]:
            with self.subTest(name=name):
                before = self.fingerprints()
                asset = self.prototype / name
                asset.write_bytes(asset.read_bytes() + b" ")
                self.assertNotEqual(before, self.fingerprints())

    def test_direct_binary_and_transitive_css_dependency_changes_invalidate(self) -> None:
        (self.prototype / "image.bin").write_bytes(b"\0\xff\x80first")
        (self.prototype / "theme.css").write_text('body { background: url("image.bin"); }', encoding="utf-8")
        self.rewrite("prototype.css", "body", '@import "theme.css";\nbody')
        before = self.fingerprints()
        (self.prototype / "image.bin").write_bytes(b"\0\xff\x80other")
        self.assertNotEqual(before, self.fingerprints())
        before = self.fingerprints()
        self.rewrite("theme.css", "body", "main")
        self.assertNotEqual(before, self.fingerprints())

    def test_multiline_export_transitive_dependency_changes_invalidate(self) -> None:
        self.add_script('export {\n value\n} from "feature.js";\n')
        (self.prototype / "feature.js").write_text("export const value = 1;\n", encoding="utf-8")
        before = self.fingerprints()
        (self.prototype / "feature.js").write_text("export const value = 2;\n", encoding="utf-8")
        self.assertNotEqual(before, self.fingerprints())

    def test_multiline_exports_reject_external_and_missing_modules(self) -> None:
        for reference in ["https://cdn.example.test/feature.js", "missing.js"]:
            with self.subTest(reference=reference):
                (self.prototype / "prototype.js").write_text(
                    f'export {{\n value\n}}\nfrom "{reference}";\n', encoding="utf-8")
                code, stdout, stderr = self.run_cli()
                self.assertNotEqual(0, code)
                self.assertEqual("", stdout)
                self.assertIn("[ERROR]", stderr)

    def test_static_export_forms_cannot_hide_external_modules(self) -> None:
        for header in ["export{value}from", "export*from", "export *\n as namespace\n from"]:
            with self.subTest(header=header):
                (self.prototype / "prototype.js").write_text(
                    f'{header} "https://cdn.example.test/feature.js";', encoding="utf-8")
                code, stdout, stderr = self.run_cli()
                self.assertEqual(1, code)
                self.assertEqual("", stdout)
                self.assertIn("external dependency", stderr)

    def test_unicode_namespace_export_rejects_external_and_missing_modules(self) -> None:
        for reference in ["https://cdn.example.test/module.js", "missing.js"]:
            with self.subTest(reference=reference):
                (self.prototype / "prototype.js").write_text(
                    f'export * as 名称 from "{reference}";', encoding="utf-8")
                code, stdout, stderr = self.run_cli("--json")
                self.assertEqual(1, code)
                self.assertEqual("", stdout)
                self.assertIn("[ERROR]", stderr)

    def test_unicode_namespace_export_tracks_a_valid_local_module(self) -> None:
        self.add_script('export * as 名称 from "feature.js";')
        (self.prototype / "feature.js").write_text("export const value = 1;", encoding="utf-8")
        before = self.fingerprints()
        self.rewrite("feature.js", "1", "2")
        self.assertNotEqual(before, self.fingerprints())

    def test_export_names_support_strings_unicode_escapes_and_multiline_comments(self) -> None:
        # ModuleExportName 可为字符串；其中的花括号、分号与 from 不能当作语法边界。
        heads = [
            'export * as "名称" from',
            r'export * as \u540d\u{79f0} from',
            'export /* one\n two */ * /* three */ as 名称 /* four\n five */ from',
            'export { value as "a;}from" } from',
            r'export * as "name\"with quote" from',
        ]
        for header in heads:
            with self.subTest(header=header):
                (self.prototype / "prototype.js").write_text(
                    f'{header} "https://cdn.example.test/module.js";', encoding="utf-8")
                code, stdout, stderr = self.run_cli("--json")
                self.assertEqual(1, code)
                self.assertEqual("", stdout)
                self.assertIn("external dependency", stderr)

    def test_quoted_and_escaped_names_keep_valid_local_dependencies(self) -> None:
        self.add_script('export * from "feature.js";')
        feature = self.prototype / "feature.js"
        feature.write_text('const value = 1; export { value as "local-name" };', encoding="utf-8")
        heads = [
            'export * as "名称" from',
            r'export * as \u540d\u{79f0} from',
            'export /* multi\n line */ * as 名称 from',
            'export { "local-name" as "a;}from" } from',
        ]
        for header in heads:
            with self.subTest(header=header):
                (self.prototype / "page.js").write_text(
                    header + r' "\u0066eature.js";', encoding="utf-8")
                before = self.fingerprints()
                feature.write_text(feature.read_text(encoding="utf-8") + "\n// change", encoding="utf-8")
                self.assertNotEqual(before, self.fingerprints())

    def test_escaped_export_module_specifiers_are_checked_as_decoded_paths(self) -> None:
        for reference in [r"\x68ttps://cdn.example.test/module.js", r"\u006dissing.js"]:
            with self.subTest(reference=reference):
                (self.prototype / "prototype.js").write_text(
                    f'export * as 名称 from "{reference}";', encoding="utf-8")
                code, stdout, stderr = self.run_cli("--json")
                self.assertEqual(1, code)
                self.assertEqual("", stdout)
                self.assertIn("[ERROR]", stderr)

    def test_unsupported_export_names_fail_closed(self) -> None:
        for header in ["export * as call() from", "export * as (名称) from", r"export * as \uZZZZ from"]:
            with self.subTest(header=header):
                (self.prototype / "prototype.js").write_text(
                    f'{header} "https://cdn.example.test/module.js";', encoding="utf-8")
                code, stdout, stderr = self.run_cli("--json")
                self.assertEqual(1, code)
                self.assertEqual("", stdout)
                self.assertIn("unsupported static JavaScript export", stderr)

    def test_regular_expression_export_text_is_not_a_module_declaration(self) -> None:
        bodies = [
            r"const exportSpacing = /export */;",
            r"const exportSpacing = /[/*]export[{}]/g;",
            r"const exportSpacing = /\/export */;",
            r'''const exportSpacing = /export \* from ["']/;''',
            r"function spacing() { return /export */; }",
        ]
        for body in bodies:
            with self.subTest(body=body):
                (self.prototype / "prototype.js").write_text(body, encoding="utf-8")
                self.fingerprints()

    def test_regular_expressions_do_not_hide_following_real_module_dependencies(self) -> None:
        prefixes = [
            r"const exportSpacing = /export */;",
            r"const ratio = total / divisor;",
            r"const ratio = object.return / divisor;",
            r"const of = 1; const ratio = of / divisor;",
            r"const ratio = ({ value: 2 }).value / divisor;",
            r"const ratio = total++ / divisor;",
        ]
        declarations = [
            'export * from "https://cdn.example.test/module.js";',
            'export * as 名称 from "missing.js";',
            'import "https://cdn.example.test/module.js";',
        ]
        for prefix in prefixes:
            for declaration in declarations:
                with self.subTest(prefix=prefix, declaration=declaration):
                    (self.prototype / "prototype.js").write_text(
                        prefix + "\n" + declaration, encoding="utf-8")
                    code, stdout, stderr = self.run_cli("--json")
                    self.assertEqual(1, code)
                    self.assertEqual("", stdout)
                    self.assertIn("[ERROR]", stderr)

    def test_unterminated_regular_expression_fails_closed(self) -> None:
        (self.prototype / "prototype.js").write_text(
            'const pattern = /export *\nexport * from "https://cdn.example.test/module.js";',
            encoding="utf-8")
        code, stdout, stderr = self.run_cli("--json")
        self.assertEqual(1, code)
        self.assertEqual("", stdout)
        self.assertIn("JavaScript regular expression", stderr)

    def test_asi_regex_and_string_prefixes_cannot_swallow_real_imports(self) -> None:
        prefixes = ['const matcher = /import/\n', 'const matcher = "import"\n']
        for prefix in prefixes:
            for reference in ["https://cdn.example.test/module.js", "missing.js"]:
                with self.subTest(prefix=prefix, reference=reference):
                    (self.prototype / "prototype.js").write_text(
                        prefix + f'import value from "{reference}";', encoding="utf-8")
                    code, stdout, stderr = self.run_cli("--json")
                    self.assertEqual(1, code)
                    self.assertEqual("", stdout)
                    self.assertIn("[ERROR]", stderr)

    def test_asi_regex_and_string_prefixes_keep_local_import_fingerprint_sensitive(self) -> None:
        self.add_script('import value from "feature.js";')
        feature = self.prototype / "feature.js"
        feature.write_text("export default 1;", encoding="utf-8")
        for prefix in ['const matcher = /import/\n', 'const matcher = "import"\n']:
            with self.subTest(prefix=prefix):
                (self.prototype / "page.js").write_text(
                    prefix + 'import value from "feature.js";', encoding="utf-8")
                before = self.fingerprints()
                feature.write_text(feature.read_text(encoding="utf-8") + "\n// changed", encoding="utf-8")
                self.assertNotEqual(before, self.fingerprints())

    def test_static_import_forms_consume_only_their_own_declaration(self) -> None:
        heads = [
            "import", "import value from", "import * as 名称 from",
            "import { value as 名称 } from", "import value, * as 名称 from",
            'import value, { "名称" as localName } from',
            r"import \u540d\u{79f0} from",
        ]
        for header in heads:
            with self.subTest(header=header):
                (self.prototype / "prototype.js").write_text(
                    'const matcher = "import"\n' + header + r' "\x68ttps://cdn.example.test/module.js";',
                    encoding="utf-8")
                code, stdout, stderr = self.run_cli("--json")
                self.assertEqual(1, code)
                self.assertEqual("", stdout)
                self.assertIn("external dependency", stderr)

    def test_import_meta_and_local_imports_work_but_dynamic_import_stays_forbidden(self) -> None:
        self.add_script('const source = import.meta.url;\nimport { value } from "feature.js";')
        (self.prototype / "feature.js").write_text("export const value = 1;", encoding="utf-8")
        self.fingerprints()
        (self.prototype / "page.js").write_text(
            'const matcher = /import/\nimport("feature.js");', encoding="utf-8")
        code, stdout, stderr = self.run_cli("--json")
        self.assertEqual(1, code)
        self.assertEqual("", stdout)
        self.assertIn("dynamic JavaScript import", stderr)

    def test_import_as_a_module_name_or_object_property_is_not_a_new_declaration(self) -> None:
        self.add_script(
            'import { import as value } from "feature.js";\n'
            'const object = { import: value };\n'
            'const current = object.import;\n'
            'export { value as import };')
        (self.prototype / "feature.js").write_text(
            'const value = 1; export { value as import };', encoding="utf-8")
        self.fingerprints()

    def test_navigation_index_and_unreferenced_shared_js_do_not_pollute_page_hash(self) -> None:
        self.add_page()
        self.rewrite("settings.html", "</main>", '<a href="reports.html">Reports</a></main>')
        self.rewrite("reports.html", "</main>", '<a href="settings.html">Settings</a></main>')
        before = self.fingerprints()
        self.rewrite("reports.html", "<h1>Settings</h1>", "<h1>Reports</h1>")
        self.rewrite("index.html", "<h1>Prototype</h1>", "<h1>Updated index</h1>")
        (self.prototype / "prototype.js").write_text("const ready = true;", encoding="utf-8")
        after = self.fingerprints()
        settings = (PROTOTYPE_RELATIVE / "settings.html").as_posix()
        reports = (PROTOTYPE_RELATIVE / "reports.html").as_posix()
        self.assertEqual(before[settings], after[settings])
        self.assertNotEqual(before[reports], after[reports])

    def test_shared_resource_invalidates_each_consumer(self) -> None:
        self.add_page()
        before = self.fingerprints()
        self.rewrite("prototype.css", "system-ui", "monospace")
        after = self.fingerprints()
        self.assertEqual(2, len(after))
        for page in before:
            self.assertNotEqual(before[page], after[page])

    def test_cyclic_dependencies_are_finite_and_stable(self) -> None:
        self.add_script('import "feature.js";\n')
        (self.prototype / "feature.js").write_text('export * from "page.js";\n', encoding="utf-8")
        before = self.fingerprints()
        self.assertEqual(before, self.fingerprints())
        self.rewrite("feature.js", "export", "/* change */ export")
        self.assertNotEqual(before, self.fingerprints())

    def test_page_selection_and_expectation_comparison(self) -> None:
        self.add_page()
        selected = self.fingerprints("--page", "settings.html", "--page", "settings.html")
        self.assertEqual(1, len(selected))
        digest = next(iter(selected.values()))
        self.assertEqual(selected, self.fingerprints("--page", "settings.html", "--expect", f"settings.html={digest.upper()}"))
        code, stdout, stderr = self.run_cli("--json", "--expect", "settings.html=" + "0" * 64)
        self.assertEqual(1, code)
        self.assertEqual("", stdout)
        self.assertIn("fingerprint mismatch", stderr)

    def test_bad_page_and_expectation_arguments_are_rejected(self) -> None:
        self.add_page()
        cases = [
            ("--page", "index.html"), ("--page", "missing.html"),
            ("--page", "../settings.html"), ("--page", "/settings.html"),
            ("--expect", "settings.html=invalid"), ("--expect", "settings.html"),
            ("--page", "settings.html", "--expect", "reports.html=" + "0" * 64),
            ("--expect", "settings.html=" + "0" * 64, "--expect", "settings.html=" + "1" * 64),
        ]
        for arguments in cases:
            with self.subTest(arguments=arguments):
                code, stdout, stderr = self.run_cli("--json", *arguments)
                self.assertNotEqual(0, code)
                self.assertEqual("", stdout)
                self.assertIn("[ERROR]", stderr)

    def test_selected_page_does_not_skip_workspace_safety_checks(self) -> None:
        self.add_page()
        self.rewrite("reports.html", "</head>", '<script src="https://cdn.example.test/bad.js"></script></head>')
        code, stdout, stderr = self.run_cli("--json", "--page", "settings.html")
        self.assertEqual(1, code)
        self.assertEqual("", stdout)
        self.assertIn("external dependency", stderr)

    def test_each_file_content_is_captured_once_for_validation_and_hash(self) -> None:
        self.add_page()
        original = validator._read_descriptor
        reads: list[str] = []

        def read_once(descriptor: int, label: str, limit: int) -> bytes:
            reads.append(label)
            return original(descriptor, label, limit)

        with mock.patch.object(validator, "_read_descriptor", side_effect=read_once):
            self.fingerprints()
        self.assertEqual(4, len(reads), reads)

    def test_binary_resource_symlink_and_hardlink_are_rejected(self) -> None:
        self.rewrite("settings.html", "</main>", '<img src="image.bin" alt="Preview"></main>')
        external = self.project / "external.bin"
        external.write_bytes(b"\x00\xff")
        image = self.prototype / "image.bin"
        for kind in ["symlink", "hardlink"]:
            with self.subTest(kind=kind):
                if kind == "symlink":
                    image.symlink_to(external)
                else:
                    os.link(external, image)
                try:
                    before = tree_snapshot(self.project)
                    code, stdout, stderr = self.run_cli("--json")
                    self.assertEqual(1, code)
                    self.assertEqual("", stdout)
                    self.assertIn("[ERROR]", stderr)
                    self.assertEqual(before, tree_snapshot(self.project))
                finally:
                    image.unlink()

    def test_dependency_replacement_after_capture_is_rejected(self) -> None:
        original = validator._validate_page_structure

        def replace_dependency(parser: object) -> None:
            original(parser)
            replacement = self.prototype / "replacement.css"
            replacement.write_bytes((self.prototype / "prototype.css").read_bytes())
            replacement.replace(self.prototype / "prototype.css")

        with mock.patch.object(validator, "_validate_page_structure", side_effect=replace_dependency):
            code, stdout, stderr = self.run_cli("--json")
        self.assertEqual(1, code)
        self.assertEqual("", stdout)
        self.assertIn("changed during validation", stderr)

    def test_binary_reads_obey_per_file_and_total_budgets(self) -> None:
        self.rewrite("settings.html", "</main>", '<img src="image.bin" alt="Preview"></main>')
        (self.prototype / "image.bin").write_bytes(b"binary resource")
        for budget, limit in [("MAX_DEPENDENCY_SIZE", 4), ("MAX_DEPENDENCY_TOTAL_SIZE", 8)]:
            with self.subTest(budget=budget), mock.patch.object(validator, budget, limit):
                code, stdout, stderr = self.run_cli("--json")
                self.assertEqual(1, code)
                self.assertEqual("", stdout)
                self.assertIn("exceeds", stderr)

    def test_resource_change_while_reading_does_not_emit_a_hash(self) -> None:
        self.rewrite("settings.html", "</main>", '<img src="image.bin" alt="Preview"></main>')
        image = self.prototype / "image.bin"
        image.write_bytes(b"initial")
        original = validator._read_descriptor

        def mutate_after_read(descriptor: int, label: str, limit: int) -> bytes:
            raw = original(descriptor, label, limit)
            if label.endswith("image.bin"):
                image.write_bytes(b"mutated while reading")
            return raw

        with mock.patch.object(validator, "_read_descriptor", side_effect=mutate_after_read):
            code, stdout, stderr = self.run_cli("--json")
        self.assertEqual(1, code)
        self.assertEqual("", stdout)
        self.assertIn("changed while it was being read", stderr)

    def test_javascript_export_comments_and_strings_are_not_dependencies(self) -> None:
        self.add_script('/* export { value } from "missing.js"; */\n'
                        'const text = "export * from \'absent.js\';";\n')
        self.fingerprints()

    def test_navigation_to_css_still_validates_its_external_dependency(self) -> None:
        (self.prototype / "download.css").write_text(
            '@import "https://cdn.example.test/theme.css";', encoding="utf-8")
        self.rewrite("settings.html", "</main>", '<a href="download.css">Download CSS</a></main>')
        code, stdout, stderr = self.run_cli("--json")
        self.assertEqual(1, code)
        self.assertEqual("", stdout)
        self.assertIn("external dependency", stderr)


if __name__ == "__main__":
    unittest.main()
