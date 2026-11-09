from __future__ import annotations

import contextlib
import io
import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
import uuid
from html.parser import HTMLParser
from pathlib import Path
from unittest import mock

from lib.documents import validate_prototype_workspace as validator_module
from lib.documents import requirement_html as requirement_renderer


PACK = Path(__file__).resolve().parents[1]
VALIDATOR = PACK / "lib/documents/validate_prototype_workspace.py"
TEMPLATE_ROOT = PACK / "templates/prototype"
PROTOTYPE_RELATIVE = Path("docs/standards/prototype")
MANDATORY_SECTIONS = (
    "purpose",
    "navigation",
    "interactions",
    "states",
    "exceptions",
)

OPEN_MAPPING_HTML = (
    '<tr data-contract-for="open-settings-dialog">'
    "<td>Open dialog</td><td>Click</td><td>Open the settings dialog.</td>"
    "<td>Opening does not modify values.</td></tr>"
)
CLOSE_MAPPING_HTML = (
    '<tr data-contract-for="close-settings-dialog">'
    "<td>Cancel</td><td>Click</td><td>Close the settings dialog.</td>"
    "<td>Cancel preserves the current values.</td></tr>"
)

SECTION_HTML = {
    "purpose": (
        '<section data-contract-section="purpose"><h2>Page purpose</h2>'
        "<p>Configure the project settings.</p></section>"
    ),
    "navigation": (
        '<section data-contract-section="navigation"><h2>Navigation</h2>'
        "<p>Enter from the prototype index and return through the Back link.</p></section>"
    ),
    "interactions": (
        '<section data-contract-section="interactions"><h2>Interaction contract</h2>'
        f"<table><tbody>{OPEN_MAPPING_HTML}{CLOSE_MAPPING_HTML}"
        "</tbody></table></section>"
    ),
    "states": (
        '<section data-contract-section="states"><h2>Required states</h2>'
        "<p>Default and dialog-open states are demonstrated.</p></section>"
    ),
    "exceptions": (
        '<section data-contract-section="exceptions"><h2>Page-specific exceptions</h2>'
        "<p>No page-specific exceptions. Follow the shared prototype styles and current "
        "controlled documents.</p></section>"
    ),
}
CONTRACT_HTML = (
    '<details class="prototype-contract">'
    "<summary>Page design and interaction contract</summary>"
    + "".join(SECTION_HTML[name] for name in MANDATORY_SECTIONS)
    + "</details>"
)

INDEX_HTML = """<!doctype html>
<html lang="en">
<head><meta charset="utf-8"><title>Prototype</title></head>
<body>
  <h1>Prototype</h1>
  <nav aria-label="Prototype pages"><a href="settings.html">Settings</a></nav>
</body>
</html>
"""

# 只扩展真实索引的当前单页承载形状，页面登记依然来自 nav 中的普通链接。
PREVIEW_INDEX_HTML = INDEX_HTML.replace(
    '<nav aria-label="Prototype pages">',
    '<nav id="prototype-pages" aria-label="Prototype pages" hidden>',
).replace(
    '</body>', '<iframe id="prototype-preview" src="settings.html" title="Settings preview"></iframe></body>',
)

PAGE_HTML = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Settings</title>
  <link rel="stylesheet" href="prototype.css">
</head>
<body>
  <a href="index.html">Back to prototype index</a>
  <main>
    <h1>Settings</h1>
    <button id="open-settings-dialog" type="button">Open settings dialog</button>
    <dialog id="settings-dialog" aria-labelledby="settings-dialog-title">
      <h2 id="settings-dialog-title">Settings dialog</h2>
      <button id="close-settings-dialog" type="button">Cancel</button>
    </dialog>
  </main>
  {CONTRACT_HTML}
  <script>
    const settingsDialog = document.getElementById("settings-dialog");
    document.getElementById("open-settings-dialog").addEventListener("click", () => {{
      settingsDialog.showModal();
    }});
    document.getElementById("close-settings-dialog").addEventListener("click", () => {{
      settingsDialog.close();
    }});
  </script>
</body>
</html>
"""

PROTOTYPE_CSS = """body { font-family: system-ui, sans-serif; }
.prototype-contract { margin-block-start: 2rem; }
"""

PURPOSE_BODY_HTML = "<p>Configure the project settings.</p>"
EXPLICIT_NOT_APPLICABLE_STATES_HTML = (
    "<p>Loading, empty, and error states are not applicable because this page reads no "
    "asynchronous or persisted data.</p>"
)


def write_valid_project(parent: Path) -> Path:
    project = parent / "Project"
    prototype = project / PROTOTYPE_RELATIVE
    pages = prototype
    pages.mkdir(parents=True)
    project_id = f"prototype-{uuid.uuid4().hex}"
    (project / "project.yaml").write_text(
        f"memory:\n  project_id: {project_id}\n", encoding="utf-8"
    )
    (prototype / "index.html").write_text(INDEX_HTML, encoding="utf-8")
    (prototype / "prototype.css").write_text(PROTOTYPE_CSS, encoding="utf-8")
    (pages / "settings.html").write_text(PAGE_HTML, encoding="utf-8")
    return project


def bind_requirement_documents(project: Path, *, source_body: str | None = None) -> tuple[Path, Path]:
    """保留带旧版本记录的历史 HTML 夹具；当前不执行暂停的渲染器。

    导航只承诺实际文件/路径/竞态安全，不要求历史页记录或摘要与修订后原稿一致，
    也不把 helper 代码变动当作重验所有历史原型的理由。
    """
    (project / "project.yaml").write_bytes((PACK / "project.yaml").read_bytes())
    plans = project / "docs/plans"
    plans.mkdir(parents=True, exist_ok=True)
    source = plans / "settings.md"
    text = source_body or (
        "# 设置需求\n\n- 主题 ID：settings\n- 阶段：active\n- 模块：settings\n"
        "- 任务等级：Full\n- 已验收版本：none\n\n"
        "## 目标与范围\n保留设置。\n\n## 需求与验收\nREQ-001：打开设置。\n\n"
        "## 方案与原型关联\n[设置弹窗](../standards/prototype/settings.html#open-settings-dialog)\n\n"
        "## 当前进展与恢复入口\n等待确认。\n\n## 验收结果与当前已交付行为\n暂无基线。\n\n"
        "## 批准依据与必要证据\n本夹具不授予批准。\n"
    )
    source.write_text(text, encoding="utf-8")
    payload = b"<!doctype html><html><head><title>Requirement</title></head><body>Review</body></html>"
    record = {
        "project": str(project.absolute()), "source": "docs/plans/settings.md", "draft": False,
        "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        "renderer": "retained-renderer-version", "html_sha256": hashlib.sha256(payload).hexdigest(),
    }
    html = source.with_suffix(".html")
    html.write_bytes(requirement_renderer.MARKER + json.dumps(record, sort_keys=True).encode() + b" -->\n" + payload)
    page = project / PROTOTYPE_RELATIVE / "settings.html"
    body = PAGE_HTML.replace('<body>', '<body data-prototype-plan-source="docs/plans/settings.md">', 1)
    body = body.replace("</main>", (
        '</main><nav class="prototype-requirement-links" aria-label="关联需求">'
        '<a data-prototype-document="html" href="../../plans/settings.html" target="_blank" rel="noopener">需求 HTML</a>'
        '<a data-prototype-document="markdown" href="../../plans/settings.md" target="_blank" rel="noopener">需求 Markdown</a></nav>'
    ), 1)
    page.write_text(body, encoding="utf-8")
    return source, html


def tree_snapshot(root: Path) -> tuple[tuple[object, ...], ...]:
    """Capture content and link/type identity without opening non-regular files."""

    entries: list[tuple[object, ...]] = []

    def visit(path: Path) -> None:
        metadata = path.lstat()
        relative = "." if path == root else path.relative_to(root).as_posix()
        file_type = stat.S_IFMT(metadata.st_mode)
        payload: bytes | str | None = None
        if stat.S_ISREG(metadata.st_mode):
            payload = path.read_bytes()
        elif stat.S_ISLNK(metadata.st_mode):
            payload = os.readlink(path)
        entries.append(
            (
                relative,
                file_type,
                stat.S_IMODE(metadata.st_mode),
                metadata.st_ino,
                metadata.st_nlink,
                metadata.st_size,
                metadata.st_mtime_ns,
                payload,
            )
        )
        if stat.S_ISDIR(metadata.st_mode):
            for child in sorted(path.iterdir(), key=lambda item: item.name):
                visit(child)

    visit(root)
    return tuple(entries)


class PrototypeTemplateParser(HTMLParser):
    """记录模板节点及祖先，用结构关系验证外壳，不依赖中文文案或排版换行。"""

    def __init__(self) -> None:
        super().__init__()
        self.nodes: list[tuple[str, dict[str, str | None], tuple[int, ...]]] = []
        self.stack: list[int] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        index = len(self.nodes)
        self.nodes.append((tag, dict(attrs), tuple(self.stack)))
        if tag not in {"meta", "link", "input", "img", "br", "hr", "source"}:
            self.stack.append(index)

    def handle_endtag(self, tag: str) -> None:
        for position in range(len(self.stack) - 1, -1, -1):
            if self.nodes[self.stack[position]][0] == tag:
                del self.stack[position:]
                break


class PrototypeWorkspaceValidatorTest(unittest.TestCase):
    maxDiff = None

    def run_validator(
        self, project: Path, *, timeout: float = 4.0
    ) -> subprocess.CompletedProcess[str]:
        canonical_project = project.resolve(strict=True)
        return self.run_validator_argument(
            canonical_project,
            cwd=canonical_project,
            timeout=timeout,
        )

    def run_validator_argument(
        self,
        project_argument: str | Path,
        *,
        cwd: Path,
        timeout: float = 4.0,
    ) -> subprocess.CompletedProcess[str]:
        environment = os.environ.copy()
        environment["PYTHONDONTWRITEBYTECODE"] = "1"
        try:
            return subprocess.run(
                [
                    sys.executable,
                    str(VALIDATOR),
                    str(project_argument),
                    PROTOTYPE_RELATIVE.as_posix(),
                ],
                cwd=cwd,
                env=environment,
                text=True,
                capture_output=True,
                check=False,
                timeout=timeout,
            )
        except subprocess.TimeoutExpired as exc:
            self.fail(f"prototype validator blocked for more than {timeout}s: {exc}")

    @staticmethod
    def page(project: Path) -> Path:
        return project / PROTOTYPE_RELATIVE / "settings.html"

    @staticmethod
    def prototype(project: Path) -> Path:
        return project / PROTOTYPE_RELATIVE

    @staticmethod
    def replace_once(path: Path, old: str, new: str) -> None:
        body = path.read_text(encoding="utf-8")
        if body.count(old) != 1:
            raise AssertionError(f"fixture expected exactly one occurrence of {old!r}")
        path.write_text(body.replace(old, new, 1), encoding="utf-8")

    def assert_rejected_without_mutation(self, project: Path, case: str) -> None:
        before = tree_snapshot(project)
        result = self.run_validator(project)
        after = tree_snapshot(project)
        self.assertEqual(before, after, f"validator mutated the project for {case}")
        self.assertNotEqual(0, result.returncode, f"validator accepted {case}")
        combined = result.stdout + result.stderr
        self.assertIn("[ERROR]", combined, f"uncontrolled failure for {case}: {combined}")
        self.assertNotIn("Traceback", combined, f"traceback leaked for {case}: {combined}")

    def test_validator_entrypoint_exists(self) -> None:
        self.assertTrue(VALIDATOR.is_file(), "missing future prototype validator entrypoint")

    def test_minimal_templates_are_build_free_and_self_describing(self) -> None:
        index_path = TEMPLATE_ROOT / "index.html"
        page_path = TEMPLATE_ROOT / "page.html"
        css_path = TEMPLATE_ROOT / "prototype.css"
        missing = [
            path.name
            for path in (index_path, page_path, css_path, *(TEMPLATE_ROOT / name for name in ("workspace.css", "workspace.js", "page-shell.js")))
            if not path.is_file()
        ]
        self.assertEqual([], missing, f"missing prototype templates: {missing}")

        index = index_path.read_text(encoding="utf-8")
        page = page_path.read_text(encoding="utf-8")
        self.assertIn('aria-label="Prototype pages"', index)
        self.assertNotIn("prototype-contract", index)
        self.assertEqual(1, index.count('<iframe id="prototype-preview"'))
        self.assertIn('<script src="workspace.js" defer></script>', index)
        self.assertIn('href="prototype.css"', page)
        self.assertIn('href="index.html"', page)
        self.assertEqual(1, page.count('class="prototype-contract"'))
        self.assertEqual(
            list(MANDATORY_SECTIONS),
            re.findall(r'data-contract-section="([^"]+)"', page),
        )
        self.assertIn('<script src="page-shell.js" defer></script>', page)

    def test_page_template_separates_header_frame_content_and_contract(self) -> None:
        """三功能区保持独立；普通 Web 默认不带固定尺寸或多余的滚动焦点入口。"""
        parser = PrototypeTemplateParser()
        parser.feed((TEMPLATE_ROOT / "page.html").read_text(encoding="utf-8"))
        body = next(attrs for tag, attrs, _ in parser.nodes if tag == "body")
        self.assertEqual("web", body.get("data-prototype-platform"))
        self.assertEqual("responsive", body.get("data-prototype-display"))

        def one_class(name: str) -> int:
            matches = [index for index, (_, attrs, _) in enumerate(parser.nodes)
                       if name in (attrs.get("class") or "").split()]
            self.assertEqual(1, len(matches), name)
            return matches[0]

        header = one_class("prototype-header")
        description = one_class("prototype-description")
        back = one_class("prototype-back-link")
        stage = one_class("prototype-stage")
        frame = one_class("prototype-frame")
        contract = one_class("prototype-contract")
        self.assertEqual("header", parser.nodes[header][0])
        self.assertEqual("index.html", parser.nodes[back][1].get("href"))
        self.assertNotIn("onclick", parser.nodes[back][1])
        self.assertIn(header, parser.nodes[back][2])
        self.assertIn(header, parser.nodes[description][2])
        self.assertIn(stage, parser.nodes[frame][2])
        self.assertNotIn("style", parser.nodes[frame][1])
        self.assertNotIn("tabindex", parser.nodes[stage][1])
        self.assertNotIn(frame, parser.nodes[description][2])
        self.assertLess(header, stage)
        self.assertLess(stage, contract)
        self.assertNotIn(stage, parser.nodes[contract][2])
        self.assertNotIn("open", parser.nodes[contract][1])
        contents = [node for node in parser.nodes if "data-prototype-page-content" in node[1]]
        self.assertEqual(1, len(contents))
        self.assertIn(frame, contents[0][2])
        self.assertEqual("main", contents[0][0])

    def test_shared_css_keeps_baseline_size_and_independent_scroll_boundaries(self) -> None:
        """静态检查默认 Web 自然流和显式 fixed 分支，防止固定窗口样式泄漏到网页。

        这里只检查尺寸和滚动边界的 CSS 声明；实际渲染及辅助技术表现不由本测试证明。
        """
        css = (TEMPLATE_ROOT / "prototype.css").read_text(encoding="utf-8")
        css = re.sub(r"/\*.*?\*/", "", css, flags=re.DOTALL)

        def declarations(selector: str) -> dict[str, str]:
            rule = re.search(r"(?m)^" + re.escape(selector) + r"\s*\{([^}]+)\}", css)
            self.assertIsNotNone(rule, selector)
            return {name.strip(): value.strip() for name, value in
                    (item.split(":", 1) for item in rule[1].split(";") if ":" in item)}

        responsive = declarations(".prototype-frame")
        self.assertEqual("auto", responsive["width"])
        self.assertEqual("auto", responsive["height"])
        for property_name in ("border", "outline", "box-shadow", "container-type", "contain"):
            self.assertNotIn(property_name, responsive)
        self.assertEqual("block", declarations(".prototype-stage")["display"])
        for selector in (".prototype-stage", ".prototype-content"):
            self.assertEqual("visible", declarations(selector)["overflow"])

        fixed = '[data-prototype-display="fixed"] '
        frame = declarations(fixed + ".prototype-frame")
        self.assertEqual("var(--prototype-frame-width)", frame["width"])
        self.assertEqual("var(--prototype-frame-height)", frame["height"])
        self.assertEqual("0 0 auto", frame["flex"])
        self.assertEqual("auto", frame["margin"])
        self.assertEqual("inline-size", frame["container-type"])
        self.assertEqual("layout", frame["contain"])
        self.assertEqual("hidden", frame["overflow"])
        for selector in (".prototype-stage", ".prototype-content"):
            self.assertEqual("auto", declarations(fixed + selector)["overflow"])
        self.assertNotIn("position", declarations(".prototype-contract"))

    def test_directory_template_remains_a_thin_page_link_directory(self) -> None:
        """入口只有一个当前页承载器，不汇总多个产品画板或复制页面契约。"""
        parser = PrototypeTemplateParser()
        parser.feed((TEMPLATE_ROOT / "index.html").read_text(encoding="utf-8"))
        self.assertEqual(1, sum(tag == "nav" and attrs.get("aria-label") == "Prototype pages"
                                for tag, attrs, _ in parser.nodes))
        for _, attrs, _ in parser.nodes:
            classes = (attrs.get("class") or "").split()
            self.assertFalse({"prototype-frame", "prototype-stage", "prototype-contract"}.intersection(classes))
            self.assertNotIn("data-prototype-page-content", attrs)

    def test_new_page_template_passes_existing_validator_without_mutation(self) -> None:
        """两种显示模式都兼容现有路径／控件／契约校验，不为模板变化增加验证门禁。"""
        for mode in ("responsive", "fixed"):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory(
                prefix="prototype-template-shell-"
            ) as temporary:
                project = write_valid_project(Path(temporary))
                shutil.copy2(TEMPLATE_ROOT / "page.html", self.page(project))
                shutil.copy2(TEMPLATE_ROOT / "prototype.css", self.prototype(project) / "prototype.css")
                shutil.copy2(TEMPLATE_ROOT / "page-shell.js", self.prototype(project) / "page-shell.js")
                if mode == "fixed":
                    # 按模板声明的扩展点切换为一个测试窗口，不把该尺寸写成项目默认规范。
                    self.replace_once(self.page(project), 'data-prototype-display="responsive"',
                                      'data-prototype-display="fixed"')
                    self.replace_once(self.page(project), '<div class="prototype-frame">',
                                      '<div class="prototype-frame" '
                                      'style="--prototype-frame-width: 1200px; '
                                      '--prototype-frame-height: 800px;">')
                    self.replace_once(self.page(project), 'aria-label="当前页面原型">',
                                      'aria-label="当前页面原型" tabindex="0">')
                    # 校验器只做结构静态验证；同步夹具描述也不能替代真实任务的语义审查。
                    self.replace_once(self.page(project), '· 响应式内容区 ·',
                                      '· 固定预览：1200 × 800 CSS px ·')
                    self.replace_once(self.page(project),
                                      'Display: responsive. 内容按可用宽度自然展开，使用 CSS px，无固定窗口。',
                                      'Display: fixed. 固定预览 1200 × 800 CSS px，按原尺寸显示。')
                    self.replace_once(self.page(project), '初始显示响应式产品插槽', '初始显示固定尺寸产品插槽')
                before = tree_snapshot(project)
                result = self.run_validator(project)
                self.assertEqual(0, result.returncode, result.stdout + result.stderr)
                self.assertEqual(before, tree_snapshot(project))

    def test_minimal_valid_workspace_passes_without_mutation(self) -> None:
        with tempfile.TemporaryDirectory(prefix="prototype-valid-") as temporary:
            project = write_valid_project(Path(temporary))
            before = tree_snapshot(project)

            result = self.run_validator(project)

            self.assertEqual(before, tree_snapshot(project))
            self.assertEqual(0, result.returncode, result.stdout + result.stderr)
            self.assertNotIn("Traceback", result.stdout + result.stderr)

    def test_navigation_groups_are_native_and_stay_inside_the_unique_directory(self) -> None:
        """折叠只改变目录呈现，不能提供第二套登记来源或绕过原目录负控。"""
        with tempfile.TemporaryDirectory(prefix="prototype-navigation-groups-") as temporary:
            project = write_valid_project(Path(temporary))
            index = self.prototype(project) / "index.html"
            grouped = INDEX_HTML.replace(
                '<nav aria-label="Prototype pages">',
                '<nav id="prototype-pages" aria-label="Prototype pages">',
            ).replace(
                '<a href="settings.html">Settings</a>',
                '<details open><summary>设置模块</summary><a href="settings.html">Settings</a></details>',
            )
            index.write_text(grouped, encoding="utf-8")
            before = tree_snapshot(project)
            result = self.run_validator(project)
            self.assertEqual(0, result.returncode, result.stdout + result.stderr)
            self.assertEqual(before, tree_snapshot(project))
            cases = {
                "group outside navigation": grouped.replace('<details open>', '</nav><details open>').replace('</details></nav>', '</details>'),
                "missing summary": grouped.replace('<summary>设置模块</summary>', ''),
                "duplicate summary": grouped.replace('</summary>', '</summary><summary>重复分组</summary>'),
                "unclosed group": grouped.replace('</details>', ''),
                "standalone summary": INDEX_HTML.replace('</nav>', '</nav><summary>孤立说明</summary>'),
                "group without canonical registry": grouped.replace(' id="prototype-pages"', ''),
                "summary without native parent": grouped.replace('<summary>设置模块</summary>', '<div><summary>设置模块</summary></div>'),
            }
            for case, body in cases.items():
                with self.subTest(case=case):
                    index.write_text(body, encoding="utf-8")
                    self.assert_rejected_without_mutation(project, case)

    def test_native_summary_accepts_an_exact_contract_mapping(self) -> None:
        """支持真实原生折叠目标，静态文字与重复映射继续按原合同拒绝。"""
        with tempfile.TemporaryDirectory(prefix="prototype-summary-mapping-") as temporary:
            project = write_valid_project(Path(temporary))
            body = PAGE_HTML.replace(
                '</main>', '<details><summary id="toggle-help">页面说明</summary><p>说明内容。</p></details></main>',
            ).replace(
                OPEN_MAPPING_HTML,
                OPEN_MAPPING_HTML + '<p data-contract-for="toggle-help">原生折叠或展开说明。</p>',
            )
            self.page(project).write_text(body, encoding="utf-8")
            result = self.run_validator(project)
            self.assertEqual(0, result.returncode, result.stdout + result.stderr)
            cases = {
                "summary without a details owner": body.replace('<details><summary id="toggle-help">', '<div><summary id="toggle-help">').replace('<p>说明内容。</p></details>', '<p>说明内容。</p></div>'),
                "summary inside an ordinary child": body.replace('<summary id="toggle-help">页面说明</summary>', '<div><summary id="toggle-help">页面说明</summary></div>'),
                "second summary is ordinary content": body.replace('<details><summary id="toggle-help">', '<details><summary>首个折叠标题</summary><summary id="toggle-help">'),
            }
            for case, invalid in cases.items():
                with self.subTest(case=case):
                    self.page(project).write_text(invalid, encoding="utf-8")
                    self.assert_rejected_without_mutation(project, case)

    def test_index_preview_accepts_one_registered_page_and_checks_its_render_resources(self) -> None:
        """iframe按嵌入资源检查具体页闭包，不能只把src当作免检查的文档导航。"""
        with tempfile.TemporaryDirectory(prefix="prototype-index-preview-") as temporary:
            project = write_valid_project(Path(temporary))
            index = self.prototype(project) / 'index.html'
            index.write_text(PREVIEW_INDEX_HTML, encoding='utf-8')
            before = tree_snapshot(project)
            result = self.run_validator(project)
            self.assertEqual(0, result.returncode, result.stdout + result.stderr)
            self.assertEqual(before, tree_snapshot(project))
            assets = self.prototype(project) / 'assets'
            assets.mkdir()
            stylesheet = assets / 'embedded.css'
            stylesheet.write_text('@import "https://example.test/hidden.css";', encoding='utf-8')
            self.replace_once(self.page(project), '</head>', '<link rel="stylesheet" href="assets/embedded.css"></head>')
            self.assert_rejected_without_mutation(project, 'external transitive resource of the embedded page')

    def test_production_workspace_accepts_empty_and_registered_controller_startup(self) -> None:
        """消费真实生产五资产：空登记不加载假页面，有登记时由唯一控制器派生加载。"""
        with tempfile.TemporaryDirectory(prefix="prototype-controller-startup-") as temporary:
            project = write_valid_project(Path(temporary)).resolve()
            self.page(project).unlink()
            for name in ('index.html', 'prototype.css', 'workspace.css', 'workspace.js', 'page-shell.js'):
                shutil.copy2(TEMPLATE_ROOT / name, self.prototype(project) / name)
            self.assertEqual({'pages': []}, validator_module.validate_workspace(project, PROTOTYPE_RELATIVE.as_posix()))
            shutil.copy2(TEMPLATE_ROOT / 'page.html', self.page(project))
            index = self.prototype(project) / 'index.html'
            self.replace_once(index, '</nav>', '<a href="settings.html">设置</a></nav>')
            before = tree_snapshot(project)
            result = self.run_validator(project)
            self.assertEqual(0, result.returncode, result.stdout + result.stderr)
            self.assertEqual(before, tree_snapshot(project))
            index_body = index.read_text(encoding='utf-8')
            page_body = self.page(project).read_text(encoding='utf-8')
            for case, body in {
                'foreign controller': index_body.replace('src="workspace.js"', 'src="other.js"'),
                'duplicate controller': index_body.replace('</head>', '<script src="workspace.js"></script></head>'),
                'inline controller body': index_body.replace('src="workspace.js" defer></script>', 'src="workspace.js" defer>alert(1)</script>'),
                'visible uninitialized frame': index_body.replace('referrerpolicy="no-referrer" hidden', 'referrerpolicy="no-referrer"'),
            }.items():
                with self.subTest(case=case):
                    index.write_text(body, encoding='utf-8')
                    self.assert_rejected_without_mutation(project, case)
            index.write_text(index_body, encoding='utf-8')
            for asset in ('workspace.js', 'workspace.css'):
                with self.subTest(asset=asset):
                    reference = f'<script src="{asset}"></script>' if asset.endswith('.js') else f'<link rel="stylesheet" href="{asset}">'
                    self.page(project).write_text(page_body.replace('</head>', reference + '</head>'), encoding='utf-8')
                    self.assert_rejected_without_mutation(project, 'index-only asset loaded by a business page')

    def test_index_rejects_meta_refresh_redirects(self) -> None:
        """refresh会在登记路由之外离开入口，外部和任意本地目标都不获得此权限。"""
        with tempfile.TemporaryDirectory(prefix="prototype-meta-refresh-") as temporary:
            project = write_valid_project(Path(temporary))
            index = self.prototype(project) / 'index.html'
            for target in ('https://example.test/escape', '../outside.html', 'settings.html'):
                with self.subTest(target=target):
                    index.write_text(INDEX_HTML.replace('</head>', f'<meta http-equiv=" Refresh " content="0;url={target}"></head>'), encoding='utf-8')
                    self.assert_rejected_without_mutation(project, 'meta refresh redirect')
            # 同一受控 iframe 的具体页也必须拒绝外部和越界声明；不能只保护 index。
            index.write_text(PREVIEW_INDEX_HTML, encoding='utf-8')
            for target in ('https://example.test/outside', '../../plans/settings.html'):
                with self.subTest(page_target=target):
                    self.page(project).write_text(PAGE_HTML.replace('</head>', f'<meta http-equiv=" Refresh " content="0;url={target}"></head>'), encoding='utf-8')
                    self.assert_rejected_without_mutation(project, 'concrete page meta refresh redirect')

    def test_index_preview_rejects_unregistered_unsafe_and_additional_frames(self) -> None:
        """src只接受登记的规范具体页，额外frame、srcdoc和内联路由不能扩大权限。"""
        with tempfile.TemporaryDirectory(prefix="prototype-index-preview-routes-") as temporary:
            project = write_valid_project(Path(temporary))
            index = self.prototype(project) / 'index.html'
            frame = '<iframe id="prototype-preview" src="settings.html" title="Settings preview"></iframe>'
            cases = {
                'missing src': PREVIEW_INDEX_HTML.replace(' src="settings.html"', ''),
                'empty src': PREVIEW_INDEX_HTML.replace('src="settings.html"', 'src=""'),
                'external src': PREVIEW_INDEX_HTML.replace('src="settings.html"', 'src="https://example.test/settings.html"'),
                'protocol-relative src': PREVIEW_INDEX_HTML.replace('src="settings.html"', 'src="//example.test/settings.html"'),
                'escaping src': PREVIEW_INDEX_HTML.replace('src="settings.html"', 'src="../settings.html"'),
                'document navigation impersonation': PREVIEW_INDEX_HTML.replace('src="settings.html"', 'data-prototype-document="html" src="../../plans/settings.html"'),
                'unregistered src': PREVIEW_INDEX_HTML.replace('src="settings.html"', 'src="reports.html"'),
                'self-embedding index': PREVIEW_INDEX_HTML.replace('src="settings.html"', 'src="index.html"'),
                'noncanonical relative src': PREVIEW_INDEX_HTML.replace('src="settings.html"', 'src="./settings.html"'),
                'fragment src': PREVIEW_INDEX_HTML.replace('src="settings.html"', 'src="settings.html#dialog"'),
                'srcdoc even when empty': PREVIEW_INDEX_HTML.replace('<iframe ', '<iframe srcdoc="" '),
                'inline route mutation': PREVIEW_INDEX_HTML.replace('<iframe ', '<iframe onload="this.src=\'reports.html\'" '),
                'inline external style': PREVIEW_INDEX_HTML.replace('<iframe ', '<iframe style="background:url(https://example.test/x.png)" '),
                'wrong frame id': PREVIEW_INDEX_HTML.replace('id="prototype-preview"', 'id="another-preview"'),
                'reserved id impersonation': PREVIEW_INDEX_HTML.replace('</body>', '<div id="prototype-preview"></div></body>'),
                'missing accessible name': PREVIEW_INDEX_HTML.replace(' title="Settings preview"', ''),
                'extra iframe': PREVIEW_INDEX_HTML.replace('</body>', frame + '</body>'),
                'legacy frame': PREVIEW_INDEX_HTML.replace('</body>', '<frame src="settings.html"></body>'),
                'legacy frameset': PREVIEW_INDEX_HTML.replace('</body>', '<frameset></frameset></body>'),
                'preview nested in registry': PREVIEW_INDEX_HTML.replace(frame, '').replace('</nav>', frame + '</nav>'),
                'preview in head': PREVIEW_INDEX_HTML.replace(frame, '').replace('</head>', frame + '</head>'),
                'missing canonical registry': PREVIEW_INDEX_HTML.replace(' id="prototype-pages"', ''),
                'unclosed iframe': PREVIEW_INDEX_HTML.replace('</iframe>', ''),
                'self-closing iframe': PREVIEW_INDEX_HTML.replace('></iframe>', '/>'),
            }
            for case, body in cases.items():
                with self.subTest(case=case):
                    index.write_text(body, encoding='utf-8')
                    self.assert_rejected_without_mutation(project, case)

    def test_product_pages_cannot_reuse_the_index_frame_permission(self) -> None:
        """产品页即使照抄指定ID/本地目标，也不能成为另一个嵌入工作区。"""
        with tempfile.TemporaryDirectory(prefix="prototype-product-frame-") as temporary:
            project = write_valid_project(Path(temporary))
            for frame in (
                '<iframe id="prototype-preview" src="settings.html" title="Nested"></iframe>',
                '<iframe src="index.html" title="Workspace"></iframe>',
                '<frame src="settings.html">', '<frameset></frameset>',
            ):
                with self.subTest(frame=frame):
                    self.page(project).write_text(PAGE_HTML.replace('</main>', frame + '</main>'), encoding='utf-8')
                    self.assert_rejected_without_mutation(project, 'frame in a concrete product page')

    def test_index_preview_target_cannot_bypass_safe_regular_file_checks(self) -> None:
        """实际嵌入的目标仍拒绝链接与特殊节点，FIFO检查及时返回且不改输入。"""
        with tempfile.TemporaryDirectory(prefix="prototype-preview-nodes-") as temporary:
            project = write_valid_project(Path(temporary))
            (self.prototype(project) / 'index.html').write_text(PREVIEW_INDEX_HTML, encoding='utf-8')
            page = self.page(project)
            body = page.read_bytes()
            unrelated = project / 'unrelated-page.txt'
            unrelated.write_bytes(body)
            for kind in ('symlink', 'hardlink', 'fifo', 'directory', 'missing'):
                with self.subTest(kind=kind):
                    page.unlink()
                    if kind == 'symlink':
                        page.symlink_to(unrelated)
                    elif kind == 'hardlink':
                        os.link(unrelated, page)
                    elif kind == 'fifo':
                        os.mkfifo(page)
                    elif kind == 'directory':
                        page.mkdir()
                    self.assert_rejected_without_mutation(project, kind)
                    if kind == 'directory':
                        page.rmdir()
                    elif kind != 'missing':
                        page.unlink()
                    page.write_bytes(body)

    def test_requirement_navigation_only_allows_explicit_markdown_and_optional_historical_html(self) -> None:
        """普通链接、资源引用和伪装槽位不能继承 plans 导航的窄权限。"""
        with tempfile.TemporaryDirectory(prefix="prototype-requirement-navigation-") as temporary:
            project = write_valid_project(Path(temporary)).resolve()
            source, html = bind_requirement_documents(project)
            page = self.page(project)
            valid_page, valid_source, valid_html = page.read_bytes(), source.read_bytes(), html.read_bytes()
            result = self.run_validator(project)
            self.assertEqual(0, result.returncode, result.stdout + result.stderr)
            text = valid_page.decode()
            cases = {
                "ordinary cross-root href": text.replace('class="prototype-requirement-links"', 'class="ordinary-links"').replace(' data-prototype-document="html"', '').replace(' data-prototype-document="markdown"', ''),
                "resource cross-root src": text.replace('</main>', '<iframe src="../../plans/settings.html"></iframe></main>'),
                "missing source declaration": text.replace(' data-prototype-plan-source="docs/plans/settings.md"', ''),
                "noncanonical source declaration": text.replace('docs/plans/settings.md', 'docs/plans/../plans/settings.md'),
                "source outside configured plans": text.replace('data-prototype-plan-source="docs/plans/settings.md"', 'data-prototype-plan-source="docs/notes/settings.md"'),
                "mismatched html target": text.replace('../../plans/settings.html', '../../plans/other.html'),
                "html target outside configured plans": text.replace('../../plans/settings.html', '../../notes/settings.html'),
                "external target": text.replace('../../plans/settings.html', 'https://example.test/settings.html'),
                "project-escaping target": text.replace('../../plans/settings.html', '../../../../settings.html'),
                "query target": text.replace('../../plans/settings.html', '../../plans/settings.html?copy=1'),
                "duplicate type": text.replace('data-prototype-document="markdown"', 'data-prototype-document="html"'),
                "untyped anchor": text.replace(' data-prototype-document="markdown"', ''),
                "duplicate slot": text.replace('</body>', '<nav class="prototype-requirement-links"></nav></body>'),
                "wrong slot element": text.replace('<nav class="prototype-requirement-links"', '<div class="prototype-requirement-links"').replace('</nav>', '</div>'),
            }
            for case, body in cases.items():
                with self.subTest(case=case):
                    page.write_text(body, encoding="utf-8")
                    self.assert_rejected_without_mutation(project, case)
            page.write_bytes(valid_page)
            for case, source_bytes, html_bytes in (
                ("stale source binding", valid_source + b"\nchanged", valid_html),
                ("modified html payload", valid_source, valid_html + b"\nchanged"),
                ("manual html", valid_source, b"<!doctype html><html>Manual</html>"),
                ("different source binding", valid_source, valid_html.replace(b'docs/plans/settings.md', b'docs/plans/another.md')),
                ("draft binding", valid_source, valid_html.replace(b'"draft": false', b'"draft": true')),
            ):
                with self.subTest(case=case):
                    source.write_bytes(source_bytes)
                    html.write_bytes(html_bytes)
                    # 历史页的旧原稿摘要、手改内容及旧记录不再是当前新鲜度合同。
                    # 实际导航只保证路径与安全文件，并且绝不重新生成或改写任何输入。
                    before = tree_snapshot(project)
                    result = self.run_validator(project)
                    self.assertEqual(0, result.returncode, result.stdout + result.stderr)
                    self.assertEqual(before, tree_snapshot(project))
            # Markdown 是必选项；没有 HTML 链接时，即使旧页缺失也应正常校验。
            source.write_bytes(valid_source)
            html.unlink()
            markdown_only = re.sub(r'<a data-prototype-document="html"[^>]*>.*?</a>', '', text)
            page.write_text(markdown_only, encoding="utf-8")
            result = self.run_validator(project)
            self.assertEqual(0, result.returncode, result.stdout + result.stderr)
            page.write_text(re.sub(r'<a data-prototype-document="markdown"[^>]*>.*?</a>', '', text), encoding="utf-8")
            self.assert_rejected_without_mutation(project, "missing mandatory Markdown anchor")
            # 没有声明的旧 HTML 不得读取；放入真实链接负控也不能影响 Markdown-only 导航。
            html.symlink_to(source)
            page.write_text(markdown_only, encoding="utf-8")
            result = self.run_validator(project)
            self.assertEqual(0, result.returncode, result.stdout + result.stderr)

    def test_requirement_navigation_requires_independent_safe_browsing_context(self) -> None:
        """无 page-shell 的合法页也须保护工作区上下文，两个文档锚点逐一校验。"""
        with tempfile.TemporaryDirectory(prefix="prototype-requirement-context-") as temporary:
            project = write_valid_project(Path(temporary)).resolve()
            bind_requirement_documents(project)
            page = self.page(project)
            text = page.read_text(encoding="utf-8")
            self.assertNotIn("page-shell.js", text)
            # rel 是不区分大小写的 token 集合；附加 noreferrer 不改变独立打开合同。
            page.write_text(text.replace('target="_blank" rel="noopener"',
                                         'target="_BLANK" rel="noreferrer NOOPENER"'), encoding="utf-8")
            result = self.run_validator(project)
            self.assertEqual(0, result.returncode, result.stdout + result.stderr)
            for kind, extension in (("html", "html"), ("markdown", "md")):
                anchor = (f'<a data-prototype-document="{kind}" href="../../plans/settings.{extension}"'
                          ' target="_blank" rel="noopener">')
                cases = {"missing target": anchor.replace(' target="_blank"', ""),
                         "missing rel": anchor.replace(' rel="noopener"', ""),
                         "unsafe rel": anchor.replace('rel="noopener"', 'rel="noreferrer"'),
                         "non-HTML rel separator": anchor.replace('rel="noopener"', 'rel="noreferrer\u00a0noopener"'),
                         "duplicate target": anchor.replace('target="_blank"', 'target="_blank" TARGET="_self"'),
                         "duplicate rel": anchor.replace('rel="noopener"', 'rel="noopener" REL="opener"')}
                for target in ("_self", "_top", "_parent", "review-window", " _blank ", "_BLAN\u212a"):
                    cases[target] = anchor.replace('target="_blank"', f'target="{target}"')
                for case, replacement in cases.items():
                    with self.subTest(kind=kind, case=case):
                        page.write_text(text.replace(anchor, replacement, 1), encoding="utf-8")
                        self.assert_rejected_without_mutation(project, case)

    def test_requirement_navigation_refuses_linked_and_special_document_nodes(self) -> None:
        """新导航入口复用单链接普通文件检查；FIFO 负控必须及时返回，不能阻塞读取。"""
        with tempfile.TemporaryDirectory(prefix="prototype-requirement-nodes-") as temporary:
            project = write_valid_project(Path(temporary)).resolve()
            source, html = bind_requirement_documents(project)
            for target in (source, html):
                body = target.read_bytes()
                unrelated = project / "unrelated-document.txt"
                unrelated.write_bytes(body)
                for kind in ("symlink", "hardlink", "fifo", "directory", "missing"):
                    with self.subTest(target=target.suffix, kind=kind):
                        target.unlink()
                        if kind == "symlink":
                            target.symlink_to(unrelated)
                        elif kind == "hardlink":
                            os.link(unrelated, target)
                        elif kind == "fifo":
                            os.mkfifo(target)
                        elif kind == "directory":
                            target.mkdir()
                        self.assert_rejected_without_mutation(project, kind)
                        if kind == "directory":
                            target.rmdir()
                        elif kind != "missing":
                            target.unlink()
                        target.write_bytes(body)
                unrelated.unlink()

    def test_page_links_outside_the_thin_index_directory_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory(prefix="prototype-index-scope-") as temporary:
            project = write_valid_project(Path(temporary))
            index = self.prototype(project) / "index.html"
            self.replace_once(
                index,
                '<nav aria-label="Prototype pages"><a href="settings.html">Settings</a></nav>',
                '<nav aria-label="Prototype pages"></nav>'
                '<a href="settings.html">Settings outside the page directory</a>',
            )

            self.assert_rejected_without_mutation(
                project, "page link outside the thin index directory"
            )

    def test_valid_fixture_implements_its_declared_dialog_interactions(self) -> None:
        self.assertEqual(1, PAGE_HTML.count("settingsDialog.showModal()"))
        self.assertEqual(1, PAGE_HTML.count("settingsDialog.close()"))
        section_names = re.findall(
            r'data-contract-section="([^"]+)"', PAGE_HTML
        )
        self.assertEqual(list(MANDATORY_SECTIONS), section_names)
        for control_id in ("open-settings-dialog", "close-settings-dialog"):
            with self.subTest(control_id=control_id):
                self.assertIn(f'id="{control_id}"', PAGE_HTML)
                self.assertEqual(
                    1,
                    PAGE_HTML.count(f'data-contract-for="{control_id}"'),
                    "each interactive control needs exactly one contract mapping",
                )

    def test_dialog_pages_require_demonstrable_open_and_close_behavior(self) -> None:
        for case, behavior in (
            ("missing dialog-open behavior", "settingsDialog.showModal();"),
            ("missing dialog-close behavior", "settingsDialog.close();"),
        ):
            with self.subTest(case=case), tempfile.TemporaryDirectory(
                prefix="prototype-dialog-behavior-"
            ) as temporary:
                project = write_valid_project(Path(temporary))
                self.replace_once(self.page(project), behavior, "")
                self.assert_rejected_without_mutation(project, case)

    def test_explicit_not_applicable_reason_is_valid_contract_content(self) -> None:
        with tempfile.TemporaryDirectory(prefix="prototype-not-applicable-") as temporary:
            project = write_valid_project(Path(temporary))
            page = self.page(project)
            self.replace_once(
                page,
                "<p>Default and dialog-open states are demonstrated.</p>",
                EXPLICIT_NOT_APPLICABLE_STATES_HTML,
            )
            body = page.read_text(encoding="utf-8")
            self.assertIn("not applicable because", body)

            result = self.run_validator(project)

            self.assertEqual(0, result.returncode, result.stdout + result.stderr)

    def test_missing_or_duplicate_contract_is_rejected(self) -> None:
        def missing(project: Path) -> None:
            self.replace_once(self.page(project), CONTRACT_HTML, "")

        def duplicate(project: Path) -> None:
            self.replace_once(
                self.page(project), "</body>", f"{CONTRACT_HTML}\n</body>"
            )

        for case, mutation in (("missing contract", missing), ("duplicate contract", duplicate)):
            with self.subTest(case=case), tempfile.TemporaryDirectory(
                prefix="prototype-contract-"
            ) as temporary:
                project = write_valid_project(Path(temporary))
                mutation(project)
                self.assert_rejected_without_mutation(project, case)

    def test_each_mandatory_contract_section_is_required(self) -> None:
        for section in MANDATORY_SECTIONS:
            with self.subTest(section=section), tempfile.TemporaryDirectory(
                prefix="prototype-section-"
            ) as temporary:
                project = write_valid_project(Path(temporary))
                self.replace_once(self.page(project), SECTION_HTML[section], "")
                self.assert_rejected_without_mutation(
                    project, f"missing {section} section"
                )

    def test_duplicate_or_unknown_contract_sections_are_rejected(self) -> None:
        for section in MANDATORY_SECTIONS:
            with self.subTest(section=section), tempfile.TemporaryDirectory(
                prefix="prototype-duplicate-section-"
            ) as temporary:
                project = write_valid_project(Path(temporary))
                self.replace_once(
                    self.page(project),
                    SECTION_HTML[section],
                    SECTION_HTML[section] + SECTION_HTML[section],
                )
                body = self.page(project).read_text(encoding="utf-8")
                self.assertEqual(
                    2, body.count(f'data-contract-section="{section}"')
                )
                self.assert_rejected_without_mutation(
                    project, f"duplicate {section} section"
                )

        with tempfile.TemporaryDirectory(
            prefix="prototype-unknown-section-"
        ) as temporary:
            project = write_valid_project(Path(temporary))
            unknown = (
                '<section data-contract-section="unknown"><h2>Unknown</h2>'
                "<p>Unknown contract sections are not permitted.</p></section>"
            )
            self.replace_once(
                self.page(project), "</details>", unknown + "</details>"
            )
            body = self.page(project).read_text(encoding="utf-8")
            names = re.findall(r'data-contract-section="([^"]+)"', body)
            for required in MANDATORY_SECTIONS:
                self.assertEqual(1, names.count(required))
            self.assertEqual(1, names.count("unknown"))
            self.assert_rejected_without_mutation(project, "unknown contract section")

    def test_empty_or_placeholder_only_contract_section_is_rejected(self) -> None:
        replacements = {
            "empty": "<p>   </p>",
            "TBD": "<p>TBD</p>",
            "bare N/A": "<p>N/A</p>",
            "comment only": "<!-- Purpose intentionally omitted. -->",
        }
        for case, replacement in replacements.items():
            with self.subTest(case=case), tempfile.TemporaryDirectory(
                prefix="prototype-placeholder-"
            ) as temporary:
                project = write_valid_project(Path(temporary))
                self.replace_once(
                    self.page(project), PURPOSE_BODY_HTML, replacement
                )
                body = self.page(project).read_text(encoding="utf-8")
                self.assertIn("<h2>Page purpose</h2>", body)
                self.assertNotIn(PURPOSE_BODY_HTML, body)
                self.assert_rejected_without_mutation(project, case)

    def test_control_and_contract_mapping_errors_are_rejected(self) -> None:
        def button_without_id(project: Path) -> None:
            self.replace_once(
                self.page(project),
                '<button id="open-settings-dialog" type="button">',
                '<button type="button">',
            )
            self.replace_once(
                self.page(project),
                ' data-contract-for="open-settings-dialog"',
                "",
            )
            body = self.page(project).read_text(encoding="utf-8")
            self.assertNotIn('id="open-settings-dialog"', body)
            self.assertNotIn('data-contract-for="open-settings-dialog"', body)

        def button_without_contract(project: Path) -> None:
            self.replace_once(
                self.page(project),
                ' data-contract-for="open-settings-dialog"',
                "",
            )
            body = self.page(project).read_text(encoding="utf-8")
            self.assertIn('id="open-settings-dialog"', body)
            self.assertNotIn('data-contract-for="open-settings-dialog"', body)

        def missing_contract_target(project: Path) -> None:
            self.replace_once(
                self.page(project),
                OPEN_MAPPING_HTML,
                OPEN_MAPPING_HTML
                + '<tr data-contract-for="missing-control"><td>Missing control</td>'
                "<td>Click</td><td>Must be rejected.</td><td>No fallback.</td></tr>",
            )

        def duplicate_contract_mapping(project: Path) -> None:
            self.replace_once(
                self.page(project),
                OPEN_MAPPING_HTML,
                OPEN_MAPPING_HTML + OPEN_MAPPING_HTML,
            )
            body = self.page(project).read_text(encoding="utf-8")
            self.assertIn('id="open-settings-dialog"', body)
            self.assertEqual(
                2, body.count('data-contract-for="open-settings-dialog"')
            )

        def duplicate_control_id(project: Path) -> None:
            self.replace_once(
                self.page(project),
                "</main>",
                '<div id="open-settings-dialog">Duplicate control identity</div></main>',
            )
            body = self.page(project).read_text(encoding="utf-8")
            self.assertEqual(2, body.count('id="open-settings-dialog"'))
            self.assertEqual(
                1, body.count('data-contract-for="open-settings-dialog"')
            )

        def mapping_outside_interactions(project: Path) -> None:
            self.replace_once(self.page(project), OPEN_MAPPING_HTML, "")
            outside_mapping = f"<table><tbody>{OPEN_MAPPING_HTML}</tbody></table>"
            self.replace_once(
                self.page(project),
                SECTION_HTML["exceptions"],
                SECTION_HTML["exceptions"].replace(
                    "</section>", outside_mapping + "</section>"
                ),
            )
            body = self.page(project).read_text(encoding="utf-8")
            self.assertEqual(1, body.count(OPEN_MAPPING_HTML))
            self.assertEqual(
                1, body.count('data-contract-for="open-settings-dialog"')
            )
            interactions_start = body.index(
                'data-contract-section="interactions"'
            )
            interactions_end = body.index("</section>", interactions_start)
            mapping_position = body.index(
                'data-contract-for="open-settings-dialog"'
            )
            self.assertGreater(mapping_position, interactions_end)
            exceptions_start = body.index('data-contract-section="exceptions"')
            exceptions_end = body.index("</section>", exceptions_start)
            self.assertGreater(mapping_position, exceptions_start)
            self.assertLess(mapping_position, exceptions_end)

        cases = (
            ("button without stable id", button_without_id),
            ("button without matching contract", button_without_contract),
            ("contract target does not exist", missing_contract_target),
            ("control with duplicate contract mappings", duplicate_contract_mapping),
            ("duplicate control id", duplicate_control_id),
            ("mapping outside interactions section", mapping_outside_interactions),
        )
        for case, mutation in cases:
            with self.subTest(case=case), tempfile.TemporaryDirectory(
                prefix="prototype-control-"
            ) as temporary:
                project = write_valid_project(Path(temporary))
                mutation(project)
                self.assert_rejected_without_mutation(project, case)

    def test_button_like_inputs_require_stable_id_and_exactly_one_mapping(self) -> None:
        original_button = (
            '<button id="open-settings-dialog" type="button">'
            "Open settings dialog</button>"
        )

        for input_type in ("button", "submit", "reset"):
            for condition in ("missing id", "missing mapping"):
                with self.subTest(
                    input_type=input_type, condition=condition
                ), tempfile.TemporaryDirectory(
                    prefix="prototype-input-control-"
                ) as temporary:
                    project = write_valid_project(Path(temporary))
                    control_id = (
                        "" if condition == "missing id" else ' id="open-settings-dialog"'
                    )
                    replacement = (
                        f'<input{control_id} type="{input_type}" '
                        'value="Open settings dialog">'
                    )
                    self.replace_once(self.page(project), original_button, replacement)
                    self.replace_once(
                        self.page(project),
                        ' data-contract-for="open-settings-dialog"',
                        "",
                    )
                    body = self.page(project).read_text(encoding="utf-8")
                    if condition == "missing id":
                        self.assertNotIn('id="open-settings-dialog"', body)
                    else:
                        self.assertIn('id="open-settings-dialog"', body)
                    self.assertNotIn(
                        'data-contract-for="open-settings-dialog"', body
                    )
                    self.assert_rejected_without_mutation(
                        project, f"input type={input_type} with {condition}"
                    )

    def test_external_script_style_and_cdn_dependencies_are_rejected(self) -> None:
        def external_script(project: Path) -> None:
            self.replace_once(
                self.page(project),
                "</head>",
                '<script src="https://cdn.example.test/app.js"></script></head>',
            )

        def external_stylesheet(project: Path) -> None:
            index = self.prototype(project) / "index.html"
            self.replace_once(
                index,
                "</head>",
                '<link rel="stylesheet" href="http://example.test/theme.css"></head>',
            )

        def protocol_relative_cdn(project: Path) -> None:
            self.replace_once(
                self.page(project),
                "</head>",
                '<link rel="stylesheet" href="//cdn.example.test/ui.css"></head>',
            )

        def quoted_external_css_import(project: Path) -> None:
            css = self.prototype(project) / "prototype.css"
            css.write_text(
                '@import "https://cdn.example.test/theme.css";\n' + PROTOTYPE_CSS,
                encoding="utf-8",
            )

        def url_external_css_import(project: Path) -> None:
            css = self.prototype(project) / "prototype.css"
            css.write_text(
                '@import url("https://cdn.example.test/theme.css");\n'
                + PROTOTYPE_CSS,
                encoding="utf-8",
            )

        def external_css_url(project: Path) -> None:
            css = self.prototype(project) / "prototype.css"
            css.write_text(
                PROTOTYPE_CSS
                + 'body { background-image: url("https://cdn.example.test/bg.svg"); }\n',
                encoding="utf-8",
            )

        def protocol_relative_css_url(project: Path) -> None:
            css = self.prototype(project) / "prototype.css"
            css.write_text(
                PROTOTYPE_CSS
                + 'body { background-image: url("//cdn.example.test/bg.svg"); }\n',
                encoding="utf-8",
            )

        cases = (
            ("external script", external_script),
            ("external stylesheet", external_stylesheet),
            ("protocol-relative CDN", protocol_relative_cdn),
            ("quoted external CSS import", quoted_external_css_import),
            ("URL external CSS import", url_external_css_import),
            ("external CSS URL", external_css_url),
            ("protocol-relative CSS URL", protocol_relative_css_url),
        )
        for case, mutation in cases:
            with self.subTest(case=case), tempfile.TemporaryDirectory(
                prefix="prototype-external-"
            ) as temporary:
                project = write_valid_project(Path(temporary))
                mutation(project)
                self.assert_rejected_without_mutation(project, case)

    def test_local_relative_css_url_is_allowed(self) -> None:
        with tempfile.TemporaryDirectory(prefix="prototype-local-css-url-") as temporary:
            project = write_valid_project(Path(temporary))
            prototype = self.prototype(project)
            assets = prototype / "assets"
            assets.mkdir()
            (assets / "pattern.svg").write_text(
                '<svg viewBox="0 0 1 1"><path d="M0 0h1v1H0z"/></svg>\n',
                encoding="utf-8",
            )
            css = prototype / "prototype.css"
            css.write_text(
                PROTOTYPE_CSS
                + 'body { background-image: url("./assets/pattern.svg"); }\n',
                encoding="utf-8",
            )
            before = tree_snapshot(project)

            result = self.run_validator(project)

            self.assertEqual(before, tree_snapshot(project))
            self.assertEqual(0, result.returncode, result.stdout + result.stderr)

    def test_version_copy_page_filenames_are_rejected(self) -> None:
        forbidden_names = (
            "settings-r2.html",
            "settings-v3.html",
            "settings-final.html",
            "settings-new.html",
            "settings-2026-08-11.html",
        )
        for filename in forbidden_names:
            with self.subTest(filename=filename), tempfile.TemporaryDirectory(
                prefix="prototype-version-copy-"
            ) as temporary:
                project = write_valid_project(Path(temporary))
                page = self.page(project)
                page.rename(page.with_name(filename))
                index = self.prototype(project) / "index.html"
                self.replace_once(index, "settings.html", f"{filename}")
                self.assertFalse(page.exists())
                self.assertTrue(page.with_name(filename).is_file())
                self.assert_rejected_without_mutation(
                    project, f"version-copy page {filename}"
                )

    def test_legitimate_page_filenames_are_allowed(self) -> None:
        legitimate_names = (
            "two-factor-auth.html",
            "oauth2-settings.html",
            "chat-history.html",
            "new-user.html",
            "final-review.html",
        )
        for filename in legitimate_names:
            with self.subTest(filename=filename), tempfile.TemporaryDirectory(
                prefix="prototype-legitimate-name-"
            ) as temporary:
                project = write_valid_project(Path(temporary))
                page = self.page(project)
                page.rename(page.with_name(filename))
                index = self.prototype(project) / "index.html"
                self.replace_once(index, "settings.html", f"{filename}")
                before = tree_snapshot(project)

                result = self.run_validator(project)

                self.assertEqual(before, tree_snapshot(project))
                self.assertEqual(0, result.returncode, result.stdout + result.stderr)

    def test_symlink_inputs_are_rejected(self) -> None:
        def page_symlink(project: Path) -> None:
            page = self.page(project)
            target = self.prototype(project) / "settings-source.html"
            page.replace(target)
            page.symlink_to("../settings-source.html")

        def css_symlink(project: Path) -> None:
            css = self.prototype(project) / "prototype.css"
            target = css.with_name("prototype-source.css")
            css.replace(target)
            css.symlink_to(target.name)

        def workspace_symlink(project: Path) -> None:
            workspace = self.prototype(project)
            target = workspace.with_name("prototype-source")
            workspace.replace(target)
            workspace.symlink_to(target.name, target_is_directory=True)

        for case, mutation in (
            ("page symlink", page_symlink),
            ("CSS symlink", css_symlink),
            ("workspace symlink", workspace_symlink),
        ):
            with self.subTest(case=case), tempfile.TemporaryDirectory(
                prefix="prototype-symlink-"
            ) as temporary:
                project = write_valid_project(Path(temporary))
                mutation(project)
                self.assert_rejected_without_mutation(project, case)

    def test_hardlink_inputs_are_rejected(self) -> None:
        def page_hardlink(project: Path) -> None:
            page = self.page(project)
            target = page.with_name("settings-source.html")
            page.replace(target)
            os.link(target, page)

        def css_hardlink(project: Path) -> None:
            css = self.prototype(project) / "prototype.css"
            target = css.with_name("prototype-source.css")
            css.replace(target)
            os.link(target, css)

        def workspace_hardlink_collision(project: Path) -> None:
            workspace = self.prototype(project)
            shutil.rmtree(workspace)
            target = workspace.with_name("prototype-source")
            target.write_text("not a workspace\n", encoding="utf-8")
            os.link(target, workspace)

        for case, mutation in (
            ("page hardlink", page_hardlink),
            ("CSS hardlink", css_hardlink),
            ("workspace hardlink collision", workspace_hardlink_collision),
        ):
            with self.subTest(case=case), tempfile.TemporaryDirectory(
                prefix="prototype-hardlink-"
            ) as temporary:
                project = write_valid_project(Path(temporary))
                mutation(project)
                self.assert_rejected_without_mutation(project, case)

    def test_fifo_inputs_are_rejected_without_blocking(self) -> None:
        def page_fifo(project: Path) -> None:
            page = self.page(project)
            page.unlink()
            os.mkfifo(page)

        def css_fifo(project: Path) -> None:
            css = self.prototype(project) / "prototype.css"
            css.unlink()
            os.mkfifo(css)

        def workspace_fifo(project: Path) -> None:
            workspace = self.prototype(project)
            shutil.rmtree(workspace)
            os.mkfifo(workspace)

        for case, mutation in (
            ("page FIFO", page_fifo),
            ("CSS FIFO", css_fifo),
            ("workspace FIFO", workspace_fifo),
        ):
            with self.subTest(case=case), tempfile.TemporaryDirectory(
                prefix="prototype-fifo-"
            ) as temporary:
                project = write_valid_project(Path(temporary))
                mutation(project)
                self.assert_rejected_without_mutation(project, case)

    def test_file_directory_type_collisions_are_rejected(self) -> None:
        def page_directory(project: Path) -> None:
            page = self.page(project)
            page.unlink()
            page.mkdir()

        def css_directory(project: Path) -> None:
            css = self.prototype(project) / "prototype.css"
            css.unlink()
            css.mkdir()

        def workspace_file(project: Path) -> None:
            workspace = self.prototype(project)
            shutil.rmtree(workspace)
            workspace.write_text("not a workspace\n", encoding="utf-8")

        for case, mutation in (
            ("page directory collision", page_directory),
            ("CSS directory collision", css_directory),
            ("workspace file collision", workspace_file),
        ):
            with self.subTest(case=case), tempfile.TemporaryDirectory(
                prefix="prototype-type-"
            ) as temporary:
                project = write_valid_project(Path(temporary))
                mutation(project)
                self.assert_rejected_without_mutation(project, case)

    def test_invalid_utf8_in_complete_workspace_files_is_rejected(self) -> None:
        cases = (
            (
                "page",
                lambda project: self.page(project),
                b"Configure the project settings.",
                b"Configure the project \xffsettings.",
                "prototype-contract",
            ),
            (
                "index",
                lambda project: self.prototype(project) / "index.html",
                b"<h1>Prototype</h1>",
                b"<h1>Proto\xfftype</h1>",
                'aria-label="Prototype pages"',
            ),
            (
                "prototype CSS",
                lambda project: self.prototype(project) / "prototype.css",
                b"system-ui",
                b"system-\xffui",
                "font-family: system-ui",
            ),
        )
        for case, resolve, original, corrupted, surviving_anchor in cases:
            with self.subTest(case=case), tempfile.TemporaryDirectory(
                prefix="prototype-invalid-utf8-"
            ) as temporary:
                project = write_valid_project(Path(temporary))
                target = resolve(project)
                body = target.read_bytes()
                self.assertEqual(1, body.count(original))
                target.write_bytes(body.replace(original, corrupted, 1))
                with self.assertRaises(UnicodeDecodeError):
                    target.read_text(encoding="utf-8")
                ignored = target.read_bytes().decode("utf-8", errors="ignore")
                replaced = target.read_bytes().decode("utf-8", errors="replace")
                self.assertIn(surviving_anchor, ignored)
                self.assertIn(surviving_anchor, replaced.replace("�", ""))
                if case == "page":
                    for section in MANDATORY_SECTIONS:
                        self.assertEqual(
                            1,
                            ignored.count(f'data-contract-section="{section}"'),
                        )
                self.assert_rejected_without_mutation(
                    project, f"invalid UTF-8 in {case}"
                )

    def test_optional_shared_javascript_must_be_strict_utf8(self) -> None:
        with tempfile.TemporaryDirectory(prefix="prototype-invalid-js-utf8-") as temporary:
            project = write_valid_project(Path(temporary))
            javascript = self.prototype(project) / "prototype.js"
            javascript.write_bytes(b"const prototypeReady = true;\n\xff")

            self.assert_rejected_without_mutation(
                project, "invalid UTF-8 in optional prototype.js"
            )

    def test_project_root_rejects_symlinked_or_parent_path_components(self) -> None:
        cases = ("absolute intermediate symlink", "relative intermediate symlink", "parent component")
        for case in cases:
            with self.subTest(case=case), tempfile.TemporaryDirectory(
                prefix="prototype-project-root-"
            ) as temporary:
                outer = Path(temporary)
                real_parent = outer / "real"
                real_parent.mkdir()
                project = write_valid_project(real_parent)
                alias = outer / "alias"
                alias.symlink_to(real_parent, target_is_directory=True)
                if case == "absolute intermediate symlink":
                    argument: str | Path = alias / "Project"
                elif case == "relative intermediate symlink":
                    argument = Path("alias/Project")
                else:
                    argument = "real/../real/Project"
                before = tree_snapshot(project)

                result = self.run_validator_argument(argument, cwd=outer)

                self.assertEqual(before, tree_snapshot(project))
                self.assertNotEqual(0, result.returncode, f"validator accepted {case}")
                combined = result.stdout + result.stderr
                self.assertIn("[ERROR]", combined)
                self.assertNotIn("Traceback", combined)

    def test_dot_project_root_anchors_the_current_directory(self) -> None:
        with tempfile.TemporaryDirectory(prefix="prototype-dot-root-") as temporary:
            project = write_valid_project(Path(temporary)).resolve(strict=True)
            before = tree_snapshot(project)

            result = self.run_validator_argument(".", cwd=project)

            self.assertEqual(before, tree_snapshot(project))
            self.assertEqual(0, result.returncode, result.stdout + result.stderr)
            self.assertNotIn("Traceback", result.stdout + result.stderr)

    def test_pages_directory_replacement_is_detected_before_success(self) -> None:
        with tempfile.TemporaryDirectory(prefix="prototype-pages-swap-") as temporary:
            project = write_valid_project(Path(temporary))
            prototype = self.prototype(project)
            pages = prototype
            replacement = prototype.parent / "prototype-replacement"
            held = prototype.parent / "prototype-held"
            shutil.copytree(pages, replacement)
            prototype_metadata = prototype.stat()
            parent_metadata = prototype.parent.stat()
            before = tree_snapshot(project)
            swapped = False

            original_validate_page = validator_module._validate_page_structure

            def swap_pages(parser: object) -> None:
                nonlocal swapped
                original_validate_page(parser)
                if not swapped:
                    pages.rename(held)
                    replacement.rename(pages)
                    swapped = True

            stdout = io.StringIO()
            stderr = io.StringIO()
            try:
                with mock.patch.object(
                    validator_module,
                    "_validate_page_structure",
                    side_effect=swap_pages,
                ), contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                    result = validator_module.main(
                        [
                            str(VALIDATOR),
                            str(project.resolve(strict=True)),
                            PROTOTYPE_RELATIVE.as_posix(),
                        ]
                    )
            finally:
                if swapped:
                    pages.rename(replacement)
                    held.rename(pages)
                    os.utime(
                        prototype,
                        ns=(prototype_metadata.st_atime_ns, prototype_metadata.st_mtime_ns),
                    )
                    os.utime(
                        prototype.parent,
                        ns=(parent_metadata.st_atime_ns, parent_metadata.st_mtime_ns),
                    )

            self.assertEqual(before, tree_snapshot(project))
            self.assertNotEqual(0, result, "validator accepted a replaced pages directory")
            combined = stdout.getvalue() + stderr.getvalue()
            self.assertIn("[ERROR]", combined)
            self.assertNotIn("Traceback", combined)

    def test_thin_index_requires_exact_nav_page_membership(self) -> None:
        def non_page_link(project: Path) -> None:
            index = self.prototype(project) / "index.html"
            self.replace_once(
                index,
                "</nav>",
                '<a href="prototype.css">Shared CSS is not a page</a></nav>',
            )

        def preload_impersonation(project: Path) -> None:
            index = self.prototype(project) / "index.html"
            self.replace_once(
                index,
                '<a href="settings.html">Settings</a>',
                '<link rel="preload" href="settings.html">',
            )

        def base_element(project: Path) -> None:
            index = self.prototype(project) / "index.html"
            self.replace_once(index, "</head>", '<base href="./"></head>')

        def extra_application_structure(project: Path) -> None:
            index = self.prototype(project) / "index.html"
            self.replace_once(index, "</body>", "<main>Prototype changelog</main></body>")

        def non_canonical_page_link(project: Path) -> None:
            index = self.prototype(project) / "index.html"
            self.replace_once(index, "settings.html", "./settings.html")

        cases = (
            ("non-page navigation link", non_page_link),
            ("preload impersonating a page link", preload_impersonation),
            ("base element", base_element),
            ("extra application structure", extra_application_structure),
            ("non-canonical page link", non_canonical_page_link),
        )
        for case, mutation in cases:
            with self.subTest(case=case), tempfile.TemporaryDirectory(
                prefix="prototype-thin-index-"
            ) as temporary:
                project = write_valid_project(Path(temporary))
                mutation(project)
                self.assert_rejected_without_mutation(project, case)

    def test_recursive_local_dependencies_are_closed_and_strict(self) -> None:
        def external_srcset(project: Path) -> None:
            self.replace_once(
                self.page(project),
                "</main>",
                '<img alt="" srcset="https://cdn.example.test/icon.png 2x"></main>',
            )

        def invalid_local_javascript(project: Path) -> None:
            assets = self.prototype(project) / "assets"
            assets.mkdir()
            (assets / "page.js").write_bytes(b"export const ready = true;\n\xff")
            self.replace_once(
                self.page(project),
                "</head>",
                '<script type="module" src="assets/page.js"></script></head>',
            )

        def local_javascript_external_import(project: Path) -> None:
            assets = self.prototype(project) / "assets"
            assets.mkdir()
            (assets / "page.js").write_text(
                'import "https://cdn.example.test/runtime.js";\n', encoding="utf-8"
            )
            self.replace_once(
                self.page(project),
                "</head>",
                '<script type="module" src="assets/page.js"></script></head>',
            )

        def nested_css_external_import(project: Path) -> None:
            assets = self.prototype(project) / "assets"
            assets.mkdir()
            (assets / "base.css").write_text(
                '@import "https://cdn.example.test/theme.css";\n', encoding="utf-8"
            )
            css = self.prototype(project) / "prototype.css"
            css.write_text(
                '@import "./assets/base.css";\n' + PROTOTYPE_CSS,
                encoding="utf-8",
            )

        def dynamic_javascript_import(project: Path) -> None:
            assets = self.prototype(project) / "assets"
            assets.mkdir()
            (assets / "feature.js").write_text(
                "export const feature = true;\n", encoding="utf-8"
            )
            (assets / "page.js").write_text(
                'import("./feature.js");\n', encoding="utf-8"
            )
            self.replace_once(
                self.page(project),
                "</head>",
                '<script type="module" src="assets/page.js"></script></head>',
            )

        cases = (
            ("external srcset", external_srcset),
            ("invalid UTF-8 local JavaScript", invalid_local_javascript),
            ("external import in local JavaScript", local_javascript_external_import),
            ("external import in nested local CSS", nested_css_external_import),
            ("unsupported dynamic JavaScript import", dynamic_javascript_import),
        )
        for case, mutation in cases:
            with self.subTest(case=case), tempfile.TemporaryDirectory(
                prefix="prototype-recursive-dependency-"
            ) as temporary:
                project = write_valid_project(Path(temporary))
                mutation(project)
                self.assert_rejected_without_mutation(project, case)

    def test_dialog_wiring_rejects_decoys_and_unbound_dialogs(self) -> None:
        def missing_dialog_binding(project: Path) -> None:
            self.replace_once(
                self.page(project),
                'const settingsDialog = document.getElementById("settings-dialog");',
                'const settingsDialog = document.getElementById("missing-dialog");',
            )

        def comment_and_string_decoys(project: Path) -> None:
            self.replace_once(
                self.page(project),
                "settingsDialog.showModal();",
                "// settingsDialog.showModal();",
            )
            self.replace_once(
                self.page(project),
                "settingsDialog.close();",
                'const closeDecoy = "settingsDialog.close()";',
            )

        def unrelated_object_calls(project: Path) -> None:
            self.replace_once(
                self.page(project), "settingsDialog.showModal();", "analytics.showModal();"
            )
            self.replace_once(
                self.page(project), "settingsDialog.close();", "analytics.close();"
            )

        def second_unwired_dialog(project: Path) -> None:
            self.replace_once(
                self.page(project),
                "</main>",
                '<dialog id="confirmation-dialog"><p>Confirm the change.</p></dialog></main>',
            )

        def wrong_open_control_binding(project: Path) -> None:
            self.replace_once(
                self.page(project),
                'document.getElementById("open-settings-dialog").addEventListener',
                'document.getElementById("close-settings-dialog").addEventListener',
            )

        cases = (
            ("missing dialog binding", missing_dialog_binding),
            ("comment and string dialog decoys", comment_and_string_decoys),
            ("unrelated object dialog calls", unrelated_object_calls),
            ("second unwired dialog", second_unwired_dialog),
            ("wrong open control binding", wrong_open_control_binding),
        )
        for case, mutation in cases:
            with self.subTest(case=case), tempfile.TemporaryDirectory(
                prefix="prototype-dialog-wiring-"
            ) as temporary:
                project = write_valid_project(Path(temporary))
                mutation(project)
                self.assert_rejected_without_mutation(project, case)

    def test_dialog_native_form_close_is_accepted(self) -> None:
        with tempfile.TemporaryDirectory(prefix="prototype-native-dialog-close-") as temporary:
            project = write_valid_project(Path(temporary))
            page = self.page(project)
            self.replace_once(
                page,
                '<button id="close-settings-dialog" type="button">Cancel</button>',
                '<form method="dialog"><button id="close-settings-dialog" '
                'type="submit">Cancel</button></form>',
            )
            self.replace_once(page, "settingsDialog.close();", "")
            before = tree_snapshot(project)

            result = self.run_validator(project)

            self.assertEqual(before, tree_snapshot(project))
            self.assertEqual(0, result.returncode, result.stdout + result.stderr)

    def test_placeholder_sentences_are_rejected(self) -> None:
        replacements = (
            "<p>TODO: fill this in later.</p>",
            "<p>TBD — pending design.</p>",
            "<p>Placeholder content.</p>",
        )
        for replacement in replacements:
            with self.subTest(replacement=replacement), tempfile.TemporaryDirectory(
                prefix="prototype-placeholder-sentence-"
            ) as temporary:
                project = write_valid_project(Path(temporary))
                self.replace_once(self.page(project), PURPOSE_BODY_HTML, replacement)
                self.assert_rejected_without_mutation(project, replacement)

    def test_additional_version_copy_page_filenames_are_rejected(self) -> None:
        forbidden_names = (
            "2026-08-11-settings.html",
            "settings-r2-copy.html",
            "settings-v3-copy.html",
            "settings-final-copy.html",
            "settings-new-copy.html",
        )
        for filename in forbidden_names:
            with self.subTest(filename=filename), tempfile.TemporaryDirectory(
                prefix="prototype-version-copy-expanded-"
            ) as temporary:
                project = write_valid_project(Path(temporary))
                page = self.page(project)
                page.rename(page.with_name(filename))
                index = self.prototype(project) / "index.html"
                self.replace_once(index, "settings.html", f"{filename}")
                self.assert_rejected_without_mutation(project, filename)

    def test_minimal_html_document_structure_is_required(self) -> None:
        def missing_doctype(project: Path) -> None:
            index = self.prototype(project) / "index.html"
            self.replace_once(index, "<!doctype html>\n", "")

        def duplicate_body(project: Path) -> None:
            self.replace_once(self.page(project), "<body>", "<body><body>")

        def unclosed_index_navigation(project: Path) -> None:
            index = self.prototype(project) / "index.html"
            self.replace_once(index, "</nav>", "")

        def unclosed_page_script(project: Path) -> None:
            self.replace_once(self.page(project), "</script>", "")

        cases = (
            ("missing doctype", missing_doctype),
            ("duplicate body", duplicate_body),
            ("unclosed index navigation", unclosed_index_navigation),
            ("unclosed page script", unclosed_page_script),
        )
        for case, mutation in cases:
            with self.subTest(case=case), tempfile.TemporaryDirectory(
                prefix="prototype-html-structure-"
            ) as temporary:
                project = write_valid_project(Path(temporary))
                mutation(project)
                self.assert_rejected_without_mutation(project, case)

    def test_contract_mapping_target_must_be_interactive(self) -> None:
        with tempfile.TemporaryDirectory(prefix="prototype-noninteractive-mapping-") as temporary:
            project = write_valid_project(Path(temporary))
            page = self.page(project)
            self.replace_once(
                page,
                "</main>",
                '<div id="plain-status">Static status</div></main>',
            )
            self.replace_once(
                page,
                OPEN_MAPPING_HTML,
                OPEN_MAPPING_HTML
                + '<tr data-contract-for="plain-status"><td>Status</td><td>Read</td>'
                '<td>Displays status.</td><td>No action.</td></tr>',
            )
            self.assert_rejected_without_mutation(project, "mapping to a static div")

    def test_thin_index_rejects_manifest_style_id(self) -> None:
        with tempfile.TemporaryDirectory(prefix="prototype-index-manifest-") as temporary:
            project = write_valid_project(Path(temporary))
            index = self.prototype(project) / "index.html"
            self.replace_once(
                index,
                "</body>",
                '<div id="prototype-manifest">Generated page inventory</div></body>',
            )

            self.assert_rejected_without_mutation(
                project, "manifest-style index structure"
            )

    def test_multiline_static_javascript_external_import_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory(prefix="prototype-multiline-import-") as temporary:
            project = write_valid_project(Path(temporary))
            assets = self.prototype(project) / "assets"
            assets.mkdir()
            (assets / "page.js").write_text(
                'import {\n  externalFeature\n} from "https://cdn.example.test/runtime.js";\n',
                encoding="utf-8",
            )
            self.replace_once(
                self.page(project),
                "</head>",
                '<script type="module" src="assets/page.js"></script></head>',
            )

            self.assert_rejected_without_mutation(
                project, "multiline external static JavaScript import"
            )

    def test_empty_dialog_form_is_not_close_evidence(self) -> None:
        with tempfile.TemporaryDirectory(prefix="prototype-empty-dialog-form-") as temporary:
            project = write_valid_project(Path(temporary))
            page = self.page(project)
            self.replace_once(
                page,
                '<button id="close-settings-dialog" type="button">Cancel</button>',
                '<form method="dialog"></form>',
            )
            self.replace_once(page, CLOSE_MAPPING_HTML, "")
            self.replace_once(
                page,
                '    document.getElementById("close-settings-dialog").addEventListener("click", () => {\n'
                "      settingsDialog.close();\n"
                "    });\n",
                "",
            )

            self.assert_rejected_without_mutation(
                project, "empty form method=dialog without a submit control"
            )

    def test_text_input_with_exact_mapping_is_interactive(self) -> None:
        with tempfile.TemporaryDirectory(prefix="prototype-text-input-") as temporary:
            project = write_valid_project(Path(temporary))
            page = self.page(project)
            self.replace_once(
                page,
                '<button id="open-settings-dialog" type="button">'
                "Open settings dialog</button>",
                '<input id="open-settings-dialog" type="text" '
                'value="Open settings dialog">',
            )
            before = tree_snapshot(project)

            result = self.run_validator(project)

            self.assertEqual(before, tree_snapshot(project))
            self.assertEqual(0, result.returncode, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
