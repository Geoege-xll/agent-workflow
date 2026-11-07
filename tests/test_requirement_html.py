"""需求投影独立职责：真实 CLI、唯一原稿、路径/故障保护和安装消费者。"""

from __future__ import annotations

import hashlib
import base64
from html.parser import HTMLParser
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch
from urllib.parse import unquote, urlsplit

from lib.documents import requirement_html as renderer
from lib import runtime_pins
from lib import runtime_store
from lib.task_graph_records import scratch_workspace


PACK = Path(__file__).resolve().parents[1]
REQUEST = "requirement-html-test"
SAMPLE = """# 需求审阅

当前需求只有这一份 Markdown。

## 范围与验收

| 需求 | 验收 |
|---|---|
| REQ-001 | 保留原稿 |

## 流程

```flow LR
需求 -> 原型 -> 实现
```
"""


class Page(HTMLParser):
    """检查真实生成文档的结构与链接，避免只匹配模拟输出。"""
    def __init__(self, body):
        super().__init__()
        self.tags: list[str] = []
        self.hrefs: list[str] = []
        self.feed(body.decode("utf-8"))

    def handle_starttag(self, tag, attrs):
        self.tags.append(tag)
        self.hrefs.extend(value for key, value in attrs if tag == "a" and key == "href")


class RequirementHtmlTest(unittest.TestCase):
    def setUp(self):
        # 当前任务可指定唯一 scratch，其他调用仍沿仓库普通临时夹具约定；没有私有依赖缓存。
        supplied = os.environ.get("AWF_TEST_SCRATCH")
        if supplied:
            self.work = Path(supplied) / "requirement-html-fixtures" / self._testMethodName
            self.work.mkdir(parents=True, exist_ok=True)
        else:
            temporary = tempfile.TemporaryDirectory(prefix="requirement-html-")
            self.addCleanup(temporary.cleanup)
            self.work = Path(temporary.name).resolve()
        self.root = self.work / "project"
        self.root.mkdir(exist_ok=True)
        (self.root / "project.yaml").write_bytes((PACK / "project.yaml").read_bytes())
        self.plans = self.root / "docs/plans"
        self.plans.mkdir(parents=True, exist_ok=True)
        self.source = self.plans / "change.md"
        self.source.write_text(SAMPLE, encoding="utf-8", newline="")
        self.source.chmod(0o640)
        self.target = self.source.with_suffix(".html")

    def process(self, action="render", **kwargs):
        return renderer.process(action, self.root, "docs/plans/change.md", REQUEST, **kwargs)

    def prototype(self):
        root = self.root / "docs/standards/prototype"
        root.mkdir(parents=True, exist_ok=True)
        page = root / "editor.html"
        page.write_text('<!doctype html><html><body><section id="error-state">错误</section></body></html>', encoding="utf-8")
        return page

    def test_vendor_and_real_render_fresh_stale_source_properties(self):
        upstream = json.loads((renderer.VENDOR / "UPSTREAM.json").read_text())
        for name, facts in upstream["files"].items():
            body = (renderer.VENDOR / name).read_bytes()
            self.assertEqual(hashlib.sha256(body).hexdigest(), facts["sha256"])
            blob = hashlib.sha1(b"blob " + str(len(body)).encode() + b"\0" + body).hexdigest()
            self.assertEqual(blob, facts["git_blob"])
        # 固定 scratch 复用失败夹具时更新同一源的验证版本，保留原页与 engine.log，
        # 让本测试仍覆盖一次真实渲染；fresh 分支在下文单独验证。
        if self.target.exists():
            self.source.write_text(SAMPLE + "\n验证输入版本：" + renderer.digest(self.target.read_bytes()), encoding="utf-8")
        before = renderer.snapshot(self.source)
        calls = []
        actual_run = subprocess.run

        def capture(command, **kwargs):
            calls.append((command, kwargs))
            result = actual_run(command, **kwargs)
            # 保留实际 Node argv、隔离环境、退出码和完整输出，供 QA 复用真实依赖证据。
            with (self.work / "engine.log").open("a", encoding="utf-8") as log:
                log.write(json.dumps({"argv": command, "env": kwargs.get("env"), "exit": result.returncode}, ensure_ascii=False) + "\n")
                log.write(result.stdout.decode("utf-8") + result.stderr.decode("utf-8"))
            return result

        with patch.object(renderer.subprocess, "run", side_effect=capture):
            result = self.process()
        self.assertTrue(result["rendered"])
        self.assertEqual(before, renderer.snapshot(self.source))
        page = Page(self.target.read_bytes())
        self.assertEqual(2, page.hrefs.count(renderer.PROJECT_REPOSITORY))
        self.assertIn(renderer.UPSTREAM_REPOSITORY, page.hrefs)
        self.assertIn('content="agent-workflow (Answer me with HTML 0.5.10)"', self.target.read_text())
        self.assertIn("渲染器来源", self.target.read_text())
        self.assertIn("table", page.tags)
        self.assertIn("svg", page.tags)
        self.assertIn("当前需求只有这一份", self.target.read_text())
        command, options = next(call for call in calls if "render" in call[0])
        self.assertIn("--no-open", command)
        self.assertEqual(options["env"]["AM_NO_UPDATE_CHECK"], "1")
        self.assertEqual(options["env"]["AM_NO_OPEN"], "1")
        self.assertTrue(Path(options["env"]["AM_HOME"]).is_relative_to(Path(tempfile.gettempdir()).resolve()))
        self.assertNotIn("NODE_OPTIONS", options["env"])
        self.assertNotIn("OPENAI_API_KEY", options["env"])
        self.assertEqual(command[2], "render")
        self.assertNotEqual(Path(command[3]), self.source)
        self.assertNotEqual(Path(command[5]), self.target)
        old = renderer.snapshot(self.target)
        # fresh 分支连版本探测都不能启动，check 也不能重新渲染。
        with patch.object(renderer.subprocess, "run", side_effect=AssertionError("fresh 不启动 Node")):
            self.assertFalse(self.process()["rendered"])
            self.assertFalse(self.process("check")["rendered"])
        self.assertEqual(old, renderer.snapshot(self.target))
        self.source.write_text(SAMPLE + "\n新增已决定的验收。\n", encoding="utf-8")
        with self.assertRaisesRegex(renderer.RequirementHtmlError, "过期"):
            self.process("check")
        self.assertTrue(self.process()["rendered"])
        self.assertEqual(Path(result["html"]), self.target)
        self.assertEqual(self.process("check")["status"], "fresh")

    def test_draft_then_same_bytes_in_plans_keeps_prototype_links(self):
        prototype = self.prototype()
        prototype_before = renderer.snapshot(prototype)
        # 一张无关错误页面不被预载/验证，本次只消费明确引用的页面与锚点。
        (prototype.parent / "unrelated.html").write_text("broken unrelated prototype", encoding="utf-8")
        body = (SAMPLE + "\n[REQ-001 错误状态](../standards/prototype/editor.html#error-state)\n").encode()
        draft = Path(scratch_workspace(self.root, REQUEST)["scratch_dir"]) / "change.md"
        draft.write_bytes(body)
        before = renderer.snapshot(draft)
        result = renderer.process("render", self.root, str(draft), REQUEST, draft=True)
        self.assertTrue(Path(result["html"]).is_relative_to(draft.parent))
        self.assertEqual(before, renderer.snapshot(draft))
        self.assertEqual(renderer.process("check", self.root, str(draft), REQUEST, draft=True)["status"], "fresh")
        href = next(h for h in Page(Path(result["html"]).read_bytes()).hrefs if "editor.html" in h)
        self.assertEqual(Path(os.path.normpath(draft.parent / unquote(urlsplit(href).path))), prototype)
        self.source.write_bytes(body)
        self.process()
        self.assertIn("../standards/prototype/editor.html#error-state", Page(self.target.read_bytes()).hrefs)
        self.assertEqual(body, self.source.read_bytes())
        self.assertEqual(prototype_before, renderer.snapshot(prototype))

    def test_bad_links_and_unsupported_embedding_are_located_before_node(self):
        page = self.prototype()
        (page.parent / "alias.html").symlink_to(page)
        hard = page.parent / "hard.html"
        os.link(page, hard)
        # 硬链接反例完成后仍保留两个节点；后面的合法路径不使用此页面。
        cases = (
            "[x](../standards/prototype/missing.html)",
            "[x](../../../../escape.md)",
            "[x](../standards/prototype/alias.html)",
            "[x](../standards/prototype/hard.html)",
            "[x](../standards/prototype/editor.html#missing-state)",
            "[x](../standards/prototype/index.html)",
            "![x](/outside.png)", "<img src='/outside.png'>", "[x]: /outside.md",
            "```python src=/outside\n```", "```html\n<img src='/outside'>\n```",
            "---\ntheme: /outside.json\n---", "~~~python\n![x](/outside.png)\n~~~",
        )
        with patch.object(renderer.subprocess, "run", side_effect=AssertionError("负输入不启动 Node")):
            for text in cases:
                with self.subTest(text=text):
                    self.source.write_text(text, encoding="utf-8")
                    with self.assertRaisesRegex(ValueError, "行|代码围栏"):
                        self.process()
                    self.assertEqual(text, self.source.read_text())
                    self.assertFalse(self.target.exists())

    def test_real_markdown_image_bypasses_are_rejected_before_node(self):
        # 图片确实存在于项目之外、当前任务夹具之内；错误实现不能靠“文件不存在”
        # 偶然避免泄漏。两项主输入已由 QA 使用固定 bundle 的 marked 实际解析为 img。
        outside = self.work / "private.png"
        outside.write_bytes(base64.b64decode(
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jF9sAAAAASUVORK5CYII="
        ))
        self.process()
        old_page = renderer.snapshot(self.target)
        prefix = "# 审阅\n\n## 范围\n\n"
        cases = {
            "escaped_backticks": prefix + r"\`![本地图片](" + str(outside) + r")\`" + "\n",
            "multiline_raw_img": prefix + '<img\n src="' + str(outside) + '">\n',
            # 同源变体覆盖反引号数量和 HTML 大小写/CRLF；不能只拦 QA 原字符串。
            "escaped_double_backticks": prefix + r"\`\`![本地图片](" + str(outside) + r")\`\`" + "\n",
            "uppercase_crlf_img": prefix + '<IMG\r\n SRC="' + str(outside) + '">\r\n',
        }
        with patch.object(renderer.subprocess, "run", side_effect=AssertionError("图片负控必须在 Node 前拒绝")):
            for name, text in cases.items():
                with self.subTest(name=name):
                    self.source.write_bytes(text.encode("utf-8"))
                    source_before = renderer.snapshot(self.source)
                    with self.assertRaisesRegex(renderer.RequirementHtmlError, "第 5 行：不支持图片或原始 HTML"):
                        self.process()
                    self.assertEqual(source_before, renderer.snapshot(self.source))
                    self.assertEqual(old_page, renderer.snapshot(self.target))

    def test_manual_and_modified_html_are_never_overwritten(self):
        self.target.write_text("<html>用户原件</html>", encoding="utf-8")
        before = renderer.snapshot(self.target)
        with self.assertRaisesRegex(ValueError, "版本记录"):
            self.process()
        self.assertEqual(before, renderer.snapshot(self.target))
        # 另一个明确测试所有的目标用于已生成页面被编辑的反例，不删除用户原件。
        self.source = self.plans / "other.md"
        self.source.write_text(SAMPLE, encoding="utf-8")
        renderer.process("render", self.root, "docs/plans/other.md", REQUEST)
        target = self.source.with_suffix(".html")
        target.write_bytes(target.read_bytes() + b"\n<!-- user edit -->")
        edited = renderer.snapshot(target)
        with self.assertRaisesRegex(ValueError, "已被修改"):
            renderer.process("render", self.root, "docs/plans/other.md", REQUEST)
        self.assertEqual(edited, renderer.snapshot(target))

    def test_linked_sources_targets_and_path_escape_are_refused(self):
        original = renderer.snapshot(self.source)
        source_link = self.plans / "linked.md"
        source_link.symlink_to(self.source)
        hard_link = self.plans / "hard.md"
        os.link(self.source, hard_link)
        for source in ("docs/plans/linked.md", "docs/plans/hard.md", "docs/features/no.md",
                       "docs/plans/../plans/change.md", str(self.source)):
            with self.subTest(source=source), self.assertRaises(ValueError):
                renderer.process("render", self.root, source, REQUEST)
        self.assertEqual(original[0], self.source.read_bytes())
        other = self.plans / "target-source.md"
        other.write_text(SAMPLE, encoding="utf-8")
        other.with_suffix(".html").symlink_to(self.source)
        with self.assertRaises(ValueError):
            renderer.process("render", self.root, "docs/plans/target-source.md", REQUEST)
        with self.assertRaisesRegex(ValueError, "scratch"):
            renderer.process("render", self.root, str(other), REQUEST, draft=True)

    def central_cores(self):
        """仅给逻辑链接准备两份最小清单资源；不是可执行核心或宿主模型 E2E。"""
        source = self.work / "link-core-source"
        for directory in runtime_store.CORE_DIRECTORIES:
            (source / directory).mkdir(parents=True, exist_ok=True)
        for name in runtime_store.SETUP_FILES:
            (source / name).write_bytes(b"#!/bin/sh\nexit 0\n")
        logical = "platforms/shared/skills/xy-code-standards/references/rules.md"
        rules = source / logical
        rules.parent.mkdir(parents=True, exist_ok=True)
        (source / "product/WORKFLOW.md").write_bytes(b"# fixture workflow\n")
        state = self.work / "link-core-state"
        rules.write_bytes(b"# first pinned rules\n")
        first = runtime_store.import_core(source, state)
        # 原地更新同一最小来源获得另一内容 ID，避免复制完整 runtime 候选。
        rules.write_bytes(b"# second pinned rules\n")
        second = runtime_store.import_core(source, state)
        adapter = self.root / runtime_pins.CENTRAL_ADAPTER
        adapter.parent.mkdir(exist_ok=True)
        adapter.write_bytes((self.root / "project.yaml").read_bytes())
        (self.root / runtime_pins.CENTRAL_MARKER).write_bytes(b"{}\n")

        def environment(core):
            return {"AGENT_WORKFLOW_STATE_DIR": str(state), runtime_pins.BINDING_ENV: json.dumps(core.binding()),
                    runtime_pins.PROJECT_ENV: str(self.root), runtime_pins.CONFIG_ENV: str(adapter),
                    runtime_pins.CORE_ENV: str(core.root)}

        return first, second, logical, environment

    def test_central_pinned_links_navigation_and_freshness(self):
        first, second, logical, environment = self.central_cores()
        body = ("# 中央链接测试夹具\n\n[工程规则](../../.agent-workflow/" + logical + ")\n").encode()
        self.source.write_bytes(body)
        skill = self.root / ".agents/skills/xy-code-standards"
        skill.parent.mkdir(parents=True)
        skill.symlink_to(first.root / "platforms/shared/skills/xy-code-standards")
        with patch.dict(os.environ, environment(first)):
            self.assertTrue(self.process()["rendered"])
            self.assertEqual("fresh", self.process("check")["status"])
            href = next(h for h in Page(self.target.read_bytes()).hrefs if "rules.md" in h)
            self.assertEqual(first.root / logical, Path(os.path.normpath(self.target.parent / unquote(href))))
            # 宿主发现链接换版不能改变旧任务固定 pin 的实际导航或新鲜度。
            skill.unlink()
            skill.symlink_to(second.root / "platforms/shared/skills/xy-code-standards")
            self.assertFalse(self.process("check")["rendered"])
            old = self.target.read_bytes()
        with patch.dict(os.environ, environment(second)):
            with self.assertRaisesRegex(ValueError, "过期"):
                self.process("check")
            self.assertTrue(self.process()["rendered"])
            self.assertNotEqual(old, self.target.read_bytes())
            href = next(h for h in Page(self.target.read_bytes()).hrefs if "rules.md" in h)
            self.assertEqual(second.root / logical, Path(os.path.normpath(self.target.parent / unquote(href))))
            # 草案使用相同逻辑原稿；只有舞台/派生页导航使用机器上已验证的固定核心。
            draft = Path(scratch_workspace(self.root, REQUEST)["scratch_dir"]) / "central-link.md"
            draft.write_bytes(body)
            result = renderer.process("render", self.root, str(draft), REQUEST, draft=True)
            href = next(h for h in Page(Path(result["html"]).read_bytes()).hrefs if "rules.md" in h)
            self.assertEqual(second.root / logical, Path(os.path.normpath(draft.parent / unquote(href))))
            self.assertEqual(body, draft.read_bytes())
            self.target.write_bytes(self.target.read_bytes() + b"\nmanual edit\n")
            before = self.target.read_bytes()
            with self.assertRaisesRegex(ValueError, "已被修改"):
                self.process()
            self.assertEqual(before, self.target.read_bytes())
        self.assertEqual(body, self.source.read_bytes())

    def test_central_pin_failures_and_project_symlinks_are_refused(self):
        first, second, logical, environment = self.central_cores()
        body = ("# 拒绝夹具\n\n[x](../../.agent-workflow/" + logical + ")\n").encode()
        self.source.write_bytes(body)
        valid = environment(first)
        missing = {key: value for key, value in valid.items() if key != runtime_pins.BINDING_ENV}
        unknown = dict(valid)
        unknown[runtime_pins.BINDING_ENV] = json.dumps({"protocol_version": 1, "content_id": "f" * 64,
                                                      "manifest_sha256": "f" * 64})
        mismatch = {**valid, runtime_pins.CORE_ENV: str(second.root)}
        for env in (missing, unknown, mismatch, {**valid, runtime_pins.BINDING_ENV: "broken"}):
            with self.subTest(env_keys=sorted(env)), patch.dict(os.environ, env, clear=True):
                with self.assertRaises(ValueError):
                    self.process()
                self.assertFalse(self.target.exists())
        with patch.dict(os.environ, valid):
            linked = self.plans / "alias.md"
            linked.symlink_to(first.root / logical)
            self.source.write_text("# 项目链接负控\n\n[x](alias.md)\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "安全普通文件"):
                self.process()
            self.assertFalse(self.target.exists())
            # 已有固定核心损坏也必须拒绝；不能回退另一个完整版本或宿主发现链接。
            rules = first.root / logical
            rules.chmod(0o644)
            rules.write_bytes(b"corrupted pinned rules\n")
            rules.chmod(0o444)
            self.source.write_bytes(body)
            with self.assertRaises(ValueError):
                self.process()
            self.assertFalse(self.target.exists())

    def test_missing_old_failed_timed_out_node_preserves_old_html(self):
        self.process()
        old = renderer.snapshot(self.target)
        self.source.write_text(SAMPLE + "\n修改后等待渲染。", encoding="utf-8")
        source = renderer.snapshot(self.source)
        low = subprocess.CompletedProcess(["node", "--version"], 0, b"v18.0.0\n", b"")
        good = subprocess.CompletedProcess(["node", "--version"], 0, b"v22.23.2\n", b"")
        bad = subprocess.CompletedProcess(["node", "render"], 3, b"", b"failure")
        with patch.object(renderer.shutil, "which", return_value=None):
            with self.assertRaisesRegex(ValueError, "Node.js >= 20"):
                self.process()
        for result, message in (([low], "版本"), ([good, bad], "exit 3"),
                                ([good, subprocess.TimeoutExpired("render", 30)], "超时")):
            with self.subTest(message=message), patch.object(renderer.subprocess, "run", side_effect=result):
                with self.assertRaisesRegex(ValueError, message):
                    self.process()
            self.assertEqual(old, renderer.snapshot(self.target))
            self.assertEqual(source, renderer.snapshot(self.source))

    def test_concurrent_source_or_target_edit_is_kept(self):
        self.process()
        old = renderer.snapshot(self.target)
        self.source.write_text(SAMPLE + "\n请求更新。", encoding="utf-8")

        def edit_source(*args):
            self.source.write_text("# 外部编辑器的新原稿\n", encoding="utf-8")
            return b"<html><textarea id='am-source'></textarea></html>"

        with patch.object(renderer, "run_renderer", side_effect=edit_source):
            with self.assertRaisesRegex(ValueError, "并发修改"):
                self.process()
        self.assertEqual(old, renderer.snapshot(self.target))
        self.assertIn("外部编辑器", self.source.read_text())

        def edit_target(*args):
            self.target.write_bytes(b"external target edit")
            return b"<html><textarea id='am-source'></textarea></html>"

        with patch.object(renderer, "run_renderer", side_effect=edit_target):
            with self.assertRaisesRegex(ValueError, "并发修改"):
                self.process()
        self.assertEqual(self.target.read_bytes(), b"external target edit")

    def test_check_does_not_write_or_start_node(self):
        before = {p.relative_to(self.root): p.stat().st_mtime_ns for p in self.root.rglob("*")}
        with patch.object(renderer.subprocess, "run", side_effect=AssertionError("check 不启动 Node")):
            with self.assertRaisesRegex(ValueError, "缺失或已过期"):
                self.process("check")
        self.assertEqual(before, {p.relative_to(self.root): p.stat().st_mtime_ns for p in self.root.rglob("*")})

    def test_candidate_render_binds_new_bytes_without_publishing_source_or_html(self):
        """候选入口只提供给同事务消费者，不能为了渲染先覆盖正式 Markdown/HTML。"""
        self.process()
        source_before, page_before = renderer.snapshot(self.source), renderer.snapshot(self.target)
        body = SAMPLE.encode() + "\n迁移候选中已明确归属的结论。\n".encode()
        candidate = renderer.render_candidate(self.root, self.source, body, self.source,
            self.root / "docs/standards/prototype", REQUEST)
        self.assertEqual(source_before, renderer.snapshot(self.source))
        self.assertEqual(page_before, renderer.snapshot(self.target))
        binding = {"project": str(self.root), "source": "docs/plans/change.md", "draft": False}
        record, _ = renderer.page_record(candidate, binding)
        self.assertEqual(renderer.digest(body), record["source_sha256"])
        self.assertIn("迁移候选中已明确归属的结论", candidate.decode())

    def test_installed_runtime_distributes_three_hosts_and_runs_without_source_imports(self):
        project = self.work / "installed-project"
        project.mkdir(exist_ok=True)
        state = self.work / "installed-state"
        command = ["bash", str(PACK / "lib/python_runtime.sh"), "-X", "utf8", "-B",
                   str(PACK / "lib/install/install_workflow.py"), str(project), "--state-dir", str(state)]
        installed = subprocess.run(command, cwd=project, capture_output=True, text=True, timeout=120)
        (self.work / "install.log").write_text(json.dumps(command) + "\n" + installed.stdout + installed.stderr, encoding="utf-8")
        self.assertEqual(installed.returncode, 0, installed.stdout + installed.stderr)
        runtime = project / ".agent-workflow"
        reference = "xy-plan/references/requirement-html.md"
        from manager import runtime_service
        binding = runtime_service.status(state, project)["runtime_binding"]
        core = runtime_store.load_core(binding, state)
        for host in (project / ".agents/skills", project / ".claude/skills"):
            self.assertEqual((host / reference).read_bytes(), (PACK / "platforms/shared/skills" / reference).read_bytes())
        for relative in ("lib/documents/requirement_html.py", "lib/documents/plan_documents.py",
                         "lib/documents/prototype_navigation.py", "lib/documents/validate_prototype_workspace.py",
                         *("templates/prototype/" + name for name in ("index.html", "page.html", "prototype.css", "workspace.css", "workspace.js", "page-shell.js")),
                         "templates/docs/PLAN.md", "lib/vendor/answer-me-with-html/am.mjs",
                         "lib/vendor/answer-me-with-html/LICENSE", "lib/vendor/answer-me-with-html/OFL-Bangers.txt"):
            self.assertEqual(runtime_store.read_core_source(core, relative), (PACK / relative).read_bytes())
        plans = project / "docs/plans"
        self.assertFalse((project / "docs/features").exists())
        self.assertFalse(plans.exists())
        plans.mkdir()
        (plans / "installed.md").write_text(SAMPLE, encoding="utf-8")
        # 使用安装态 wrapper、cwd 与清空的 PYTHONPATH；没有源包参数或源目录导入路径。
        env = {**os.environ, "PYTHONPATH": "", "AGENT_WORKFLOW_STATE_DIR": str(state)}
        for action in ("render", "check"):
            command = ["bash", str(runtime / "lib/python_runtime.sh"), "-X", "utf8", "-B",
                       str(runtime / "runtime.py"), "--binding", json.dumps(binding), "helper",
                       "lib/documents/requirement_html.py", "--", action, "--project", str(project),
                       "--source", "docs/plans/installed.md"]
            if action == "render":
                command.extend(["--request-id", REQUEST])
            result = subprocess.run(command, cwd=project, env=env, capture_output=True, text=True, timeout=45)
            (self.work / f"installed-{action}.log").write_text(json.dumps(command) + "\n" + result.stdout + result.stderr, encoding="utf-8")
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertEqual(json.loads(result.stdout)["status"], "fresh")
        self.assertIn("svg", Page((plans / "installed.html").read_bytes()).tags)


if __name__ == "__main__":
    unittest.main()
