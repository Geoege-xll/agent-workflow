"""当前暂停契约的真实入口验证；旧引擎用例原样保留为不收集的恢复资料。"""

from __future__ import annotations

import hashlib
import contextlib
import io
import base64
import ctypes
from html.parser import HTMLParser
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import threading
import time
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


class _RequirementHtmlFixture:
    def setUp(self):
        supplied = os.environ.get("AWF_TEST_SCRATCH")
        parent = Path(supplied) / "requirement-html-fixtures" if supplied else None
        if parent is not None:
            parent.mkdir(parents=True, exist_ok=True)
        # 同一请求仍复用既有父目录；每次TestCase实例拥有唯一短命目录，防止
        # 前次合法负控留下的alias/hardlink、手改HTML、故损core或安装项目串入
        # 下一次调用。既有固定名称历史目录及engine.log从不删除或覆盖。
        temporary = tempfile.TemporaryDirectory(prefix=self._testMethodName + "-", dir=parent)
        self.addCleanup(temporary.cleanup)
        self.work = Path(temporary.name).resolve()
        # cleanup按后进先出执行：先转移本次真实依赖的完整过程证据，再回收
        # 本实例目录；setUp或测试中途失败也进入相同出口，不丢失唯一日志。
        self.evidence_log = os.environ.get("AWF_TEST_EVIDENCE_LOG")
        self.addCleanup(self.preserve_process_evidence)
        self.root = self.work / "project"
        self.root.mkdir(exist_ok=True)
        (self.root / "project.yaml").write_bytes((PACK / "project.yaml").read_bytes())
        self.plans = self.root / "docs/plans"
        self.plans.mkdir(parents=True, exist_ok=True)
        self.source = self.plans / "change.md"
        self.source.write_text(SAMPLE, encoding="utf-8", newline="")
        self.source.chmod(0o640)
        self.target = self.source.with_suffix(".html")

    def preserve_process_evidence(self):
        """只追加本实例已知日志，不收集业务目录或把旧日志当成本轮证据。"""
        if not self.evidence_log:
            return
        for name in ("engine.log", "install.log", "installed-render.log", "installed-check.log"):
            path = self.work / name
            if path.is_file():
                with Path(self.evidence_log).open("ab") as output:
                    output.write((f"\n--- REQUIREMENT HTML PROCESS EVIDENCE {self.id()} / {name} ---\n").encode("utf-8"))
                    output.write(path.read_bytes())
                    output.write(b"\n--- REQUIREMENT HTML PROCESS EVIDENCE END ---\n")

    def process(self, action="render", **kwargs):
        return renderer.process(action, self.root, "docs/plans/change.md", REQUEST, **kwargs)

    def prototype(self):
        root = self.root / "docs/standards/prototype"
        root.mkdir(parents=True, exist_ok=True)
        page = root / "editor.html"
        page.write_text('<!doctype html><html><body><section id="error-state">错误</section></body></html>', encoding="utf-8")
        return page


class RequirementHtmlEngineHistory(_RequirementHtmlFixture):
    """暂停前的历史渲染用例：无 TestCase 基类，不被当前测试收集，也不报告 skip。

    恢复生成须重新授权、恢复全部入口/规则并重新启用这些真实依赖用例；保留正文
    不是本轮已执行或仍可用的引擎证据。当前契约由 RequirementHtmlSuspendedTest 验证。
    """
    def test_vendor_checkout_filters_preserve_upstream_bytes(self):
        """真实消费 Git checkout 过滤器，防止 Windows CRLF 改写固定上游载荷。"""
        upstream = json.loads((renderer.VENDOR / "UPSTREAM.json").read_text(encoding="utf-8"))
        for name, facts in upstream["files"].items():
            relative = (renderer.VENDOR / name).relative_to(PACK).as_posix()
            command = ["git", "-c", "core.autocrlf=true", "cat-file", "--filters",
                       "--path=" + relative, "HEAD:" + relative]
            result = subprocess.run(command, cwd=PACK, capture_output=True, timeout=10)
            self.assertEqual(0, result.returncode, result.stderr.decode("utf-8", errors="replace"))
            self.assertEqual(facts["sha256"], hashlib.sha256(result.stdout).hexdigest(), name)

    def test_stage_links_and_unowned_configuration_are_rejected(self):
        """直接消费真实舞台节点；错误实现不能靠不存在的外部目录偶然拒绝。"""
        outside = self.work / "outside-stage"
        outside.mkdir()
        marker = outside / "private.txt"
        marker.write_bytes(b"owned fixture; must remain untouched")
        before = renderer.snapshot(marker)
        stage_link = self.work / "stage-link"
        stage_link.symlink_to(outside, target_is_directory=True)
        with self.assertRaises((OSError, ValueError)):
            renderer.run_renderer(stage_link, SAMPLE.encode())
        stage = self.work / "stage"
        stage.mkdir()
        home = stage / "am-home"
        home.symlink_to(outside, target_is_directory=True)
        with self.assertRaises((OSError, ValueError)):
            renderer.run_renderer(stage, SAMPLE.encode())
        home.unlink()
        home.mkdir()
        (home / "config.json").write_bytes(b"{}")
        with self.assertRaisesRegex(renderer.RequirementHtmlError, "非本轮配置"):
            renderer.run_renderer(stage, SAMPLE.encode())
        self.assertEqual(before, renderer.snapshot(marker))
        self.assertEqual({"private.txt"}, {path.name for path in outside.iterdir()})
        self.assertFalse((stage / "input.md").exists())
        self.assertFalse((stage / "output.html").exists())

    def test_vendor_and_real_render_fresh_stale_source_properties(self):
        upstream = json.loads((renderer.VENDOR / "UPSTREAM.json").read_text())
        for name, facts in upstream["files"].items():
            body = (renderer.VENDOR / name).read_bytes()
            self.assertEqual(hashlib.sha256(body).hexdigest(), facts["sha256"])
            blob = hashlib.sha1(b"blob " + str(len(body)).encode() + b"\0" + body).hexdigest()
            self.assertEqual(blob, facts["git_blob"])
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
        with patch.object(renderer.subprocess, "run", side_effect=capture):
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


class WindowsRequirementHtmlNativeHistory(_RequirementHtmlFixture):
    """暂停前的原生 Windows 恢复资料；不收集、不 skip、不作为当前原生验收。"""

    def test_native_render_check_preserves_source_and_vendor_bytes(self):
        upstream = json.loads((renderer.VENDOR / "UPSTREAM.json").read_text(encoding="utf-8"))
        for name, facts in upstream["files"].items():
            self.assertEqual(facts["sha256"], hashlib.sha256((renderer.VENDOR / name).read_bytes()).hexdigest(), name)
        before = renderer.snapshot(self.source)
        # 使用确实存在的项目 node.exe 作为搜索负控。它不是可执行替身：正确实现
        # 应在进程创建前报告缺少显式 PATH 运行时，错误搜索执行则会以其他错误失败。
        (self.root / "node.exe").write_bytes(b"MZ untrusted project fixture")
        relative = self.root / "relative-node-bin"
        relative.mkdir()
        (relative / "node.exe").write_bytes(b"MZ untrusted relative PATH fixture")
        original_cwd = Path.cwd()
        try:
            os.chdir(self.root)
            for path in ("", ".", "relative-node-bin"):
                with self.subTest(path=path), patch.dict(os.environ, {"PATH": path}):
                    with self.assertRaisesRegex(renderer.RequirementHtmlError, "Node.js >= 20"):
                        self.process()
                    self.assertEqual(before, renderer.snapshot(self.source))
                    self.assertFalse(self.target.exists())
            # 只观察并保留实际调用结果，不提供模拟进程输出；固定 bundle 必须由
            # 已有 Node 经真实 Windows Job 执行，输出仍由真实 HTML 结构断言验证。
            actual_run = renderer._run_node

            def record(command, **options):
                result = actual_run(command, **options)
                with (self.work / "engine.log").open("ab") as log:
                    log.write((json.dumps({"argv": command, "cwd": str(options["stage"]),
                        "env": options["env"], "exit": result.returncode}, ensure_ascii=False) + "\n").encode())
                    log.write(result.stdout + result.stderr + b"\n")
                return result

            with patch.object(renderer, "_run_node", side_effect=record):
                self.assertTrue(self.process()["rendered"])
                page_before = renderer.snapshot(self.target)
                self.assertEqual("fresh", self.process("check")["status"])
                self.assertFalse(self.process()["rendered"])
                self.assertEqual(page_before, renderer.snapshot(self.target))
        finally:
            os.chdir(original_cwd)
        self.assertEqual(before, renderer.snapshot(self.source))
        page = Page(self.target.read_bytes())
        self.assertIn("svg", page.tags)
        self.assertIn("table", page.tags)
        self.assertEqual(2, page.hrefs.count(renderer.PROJECT_REPOSITORY))
        self.assertIn(renderer.UPSTREAM_REPOSITORY, page.hrefs)

    def test_native_stage_and_home_junctions_are_rejected(self):
        outside = self.work / "outside-junction"
        outside.mkdir()
        marker = outside / "private.txt"
        marker.write_bytes(b"must not change through any junction")
        before = renderer.snapshot(marker)
        stage = self.work / "junction-stage"
        home_stage = self.work / "home-junction-stage"
        home_stage.mkdir()
        nested_stage = self.work / "nested-junction-stage"
        nested_stage.mkdir()
        for link, consumed_stage in ((stage, stage), (home_stage / "am-home", home_stage),
                                      (nested_stage / "nested", nested_stage)):
            command = ["cmd.exe", "/d", "/c", "mklink", "/J", str(link), str(outside)]
            result = subprocess.run(command, capture_output=True, timeout=10)
            with (self.work / "engine.log").open("ab") as log:
                log.write((json.dumps({"argv": command, "exit": result.returncode}) + "\n").encode())
                log.write(result.stdout + result.stderr + b"\n")
            self.assertEqual(0, result.returncode, result.stdout + result.stderr)
            try:
                with self.subTest(link=link), self.assertRaises((OSError, ValueError)):
                    renderer.run_renderer(consumed_stage, SAMPLE.encode())
                self.assertEqual(before, renderer.snapshot(marker))
                self.assertEqual({"private.txt"}, {path.name for path in outside.iterdir()})
            finally:
                # 只移除刚创建的确切 junction 自身；不递归扫描、追随或清理目标。
                os.rmdir(link)
        held_stage = self.work / "held-stage"
        held_stage.mkdir()
        with renderer._renderer_stage(held_stage):
            # 原生 DELETE sharing 边界必须覆盖 Node 实际消费的 stage 和 am-home，
            # 仅完成一次 no-reparse 检查而随后释放句柄的实现会允许这两个重命名。
            for path in (held_stage, held_stage / "am-home"):
                with self.subTest(held=path), self.assertRaises(OSError):
                    os.rename(path, path.with_name(path.name + "-replaced"))
        # Windows 实际路径比较不区分大小写，不能只拒绝小写 config.json/themes。
        for name in ("CONFIG.JSON", "THEMES"):
            configured = held_stage / "am-home" / name
            configured.write_bytes(b"{}")
            try:
                with self.subTest(configuration=name), self.assertRaisesRegex(
                        renderer.RequirementHtmlError, "非本轮配置"):
                    renderer.run_renderer(held_stage, SAMPLE.encode())
            finally:
                configured.unlink()

    def test_native_node_timeout_terminates_descendants(self):
        from lib.install import install_process, windows_process as backend

        node = renderer._node_executable()
        self.assertIsNotNone(node, "requires an existing Node >= 20 on explicit absolute PATH")
        stage = self.work / "timeout-stage"
        stage.mkdir()
        ready, late = stage / "ready.json", stage / "late.txt"
        grandchild, child, parent = (self.work / name for name in ("grandchild.mjs", "child.mjs", "parent.mjs"))
        grandchild.write_text(
            "import fs from 'node:fs';\n"
            # 先写临时叶再改名，观察线程只会读到完整 JSON，避免把准备竞争当后端失败。
            "fs.writeFileSync('ready.tmp', JSON.stringify([Number(process.argv[2]), process.ppid, process.pid]));\n"
            "fs.renameSync('ready.tmp', 'ready.json');\n"
            "setTimeout(() => fs.writeFileSync('late.txt', 'late'), 20000);\n", encoding="utf-8")
        child.write_text("import {spawn} from 'node:child_process';\n"
            f"spawn(process.execPath, [{json.dumps(str(grandchild))}, process.argv[2]], {{stdio:'inherit'}});\n"
            "setInterval(() => {}, 1000);\n", encoding="utf-8")
        parent.write_text("import {spawn} from 'node:child_process';\n"
            f"spawn(process.execPath, [{json.dumps(str(child))}, String(process.pid)], {{stdio:'inherit'}});\n"
            "setInterval(() => {}, 1000);\n", encoding="utf-8")
        api, handles, observer_errors = backend._Win32API(), [], []
        owners, observed, returned_states = [], [], []
        actual_owner = backend.WindowsJobProcess

        def record_owner(*args, **options):
            # 只保留实际构造出的生产 owner 供查询其具体 Job；不伪造 PID、
            # communicate、close 或任何内核返回值，也不延迟生产清理。
            owner = actual_owner(*args, **options)
            owners.append(owner)
            return owner

        def observe_started_tree():
            try:
                deadline = time.monotonic() + 6
                while (not ready.exists() or not owners) and time.monotonic() < deadline:
                    time.sleep(0.01)
                pids = json.loads(ready.read_text(encoding="utf-8"))
                for pid in pids:
                    handle = api.OpenProcess(0x00101000, False, pid)  # SYNCHRONIZE | QUERY_LIMITED_INFORMATION
                    if not handle:
                        raise api.error("Open live Node fixture process")
                    handles.append(handle)
                    created, exited, kernel, user = (ctypes.c_uint64() for _ in range(4))
                    if not api.GetProcessTimes(handle, ctypes.byref(created), ctypes.byref(exited),
                                               ctypes.byref(kernel), ctypes.byref(user)):
                        raise api.error("Read Node fixture creation time")
                    associated = backend.BOOL()
                    if not api.IsProcessInJob(handle, owners[0]._job, ctypes.byref(associated)):
                        raise api.error("Query actual Node owner Job association")
                    state = api.WaitForSingleObject(handle, 0)
                    observed.append({"pid": pid, "handle": handle, "created": created.value,
                                     "owner_pid": owners[0].pid, "job": owners[0]._job,
                                     "in_owner_job": bool(associated.value), "initial_wait": state})
                    if state != 258:  # WAIT_TIMEOUT
                        raise AssertionError("Node fixture exited before containment was exercised")
            except BaseException as exc:
                observer_errors.append(exc)

        observer = threading.Thread(target=observe_started_tree)
        observer.start()
        command = [node, str(parent)]
        error = None
        try:
            with renderer._renderer_stage(stage):
                with patch.object(backend, "WindowsJobProcess", side_effect=record_owner):
                    try:
                        renderer._run_node(command, stage=stage, env=renderer.node_environment(stage), timeout=8)
                    except BaseException as exc:
                        error = exc
                    finally:
                        # 在退出舞台上下文、join 或写日志之前只取一次即时状态。
                        # 断言复用这份原始采样，不能靠稍后的二次查询把 258 等成绿。
                        returned_states = [api.WaitForSingleObject(handle, 0) for handle in handles]
            observer.join(timeout=7)
            with (self.work / "engine.log").open("a", encoding="utf-8") as log:
                log.write(json.dumps({"argv": command, "cwd": str(stage), "timeout": 8,
                    "owner_pids": [owner.pid for owner in owners], "observed": observed,
                    "immediate_return_waits": returned_states, "exception": repr(error),
                    "observer_errors": [repr(exc) for exc in observer_errors]}) + "\n")
            if error is not None and not isinstance(error, subprocess.TimeoutExpired):
                raise error
            self.assertIsInstance(error, subprocess.TimeoutExpired)
            self.assertFalse(observer.is_alive(), "Node fixture observer did not finish")
            self.assertFalse(observer_errors, str(observer_errors))
            self.assertEqual(3, len(handles), "root, child and grandchild must all actually start")
            self.assertEqual(observed[0]["pid"], owners[0].pid)
            self.assertTrue(all(item["in_owner_job"] for item in observed))
            # 在超时返回之前持有真实进程句柄，既不靠 PID 重用猜测，也不靠 sleep
            # 后没有写文件推断清理成功；三个句柄在返回时都必须已经 signaled。
            self.assertEqual([0, 0, 0], returned_states)  # WAIT_OBJECT_0
            self.assertFalse(late.exists())
        finally:
            observer.join(timeout=7)
            for handle in handles:
                api.CloseHandle(handle)


class RequirementHtmlSuspendedTest(_RequirementHtmlFixture, unittest.TestCase):
    """当前必须通过的暂停行为；实际源入口和安装态入口都不能产生派生文件。"""

    def test_public_python_entries_reject_before_any_input_or_side_effect(self):
        # 故意保留手写旧页且给部分调用无效路径：暂停必须先于输入校验，不能为了
        # 返回“暂停”先读用户文档、验证 Node、建 scratch 或覆盖已有 HTML。
        self.target.write_bytes(b"<!doctype html><html>historical user material</html>")
        before = (renderer.snapshot(self.source), renderer.snapshot(self.target))
        nodes = sorted(path.relative_to(self.root).as_posix() for path in self.root.rglob("*"))
        calls = (
            lambda: renderer.process("render", self.root, "docs/plans/change.md", REQUEST),
            lambda: renderer.process("check", self.root, "../invalid.md"),
            lambda: renderer.process("render", self.work / "missing", "missing.md", draft=True),
            lambda: renderer.render_candidate(self.root, self.source, SAMPLE.encode(), self.source,
                self.root / "docs/standards/prototype", REQUEST),
            lambda: renderer.run_renderer(self.work / "never-create-stage", SAMPLE.encode()),
        )
        with contextlib.ExitStack() as stack:
            for name in ("resolve_inputs", "stage_markdown", "scratch_workspace", "publish", "_renderer_stage", "_run_node"):
                stack.enter_context(patch.object(renderer, name, side_effect=AssertionError(name + " must not run")))
            for index, invoke in enumerate(calls):
                with self.subTest(entry=index), self.assertRaisesRegex(renderer.RequirementHtmlError, "HTML 生成功能已暂停"):
                    invoke()
            stdout, stderr = io.StringIO(), io.StringIO()
            with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                self.assertEqual(2, renderer.main(["render", "--project", str(self.root), "--source", "../invalid.md"]))
            self.assertEqual("", stdout.getvalue())
            self.assertIn(renderer.SUSPENDED_MESSAGE, stderr.getvalue())
        self.assertEqual(before, (renderer.snapshot(self.source), renderer.snapshot(self.target)))
        self.assertEqual(nodes, sorted(path.relative_to(self.root).as_posix() for path in self.root.rglob("*")))
        self.assertFalse((self.work / "never-create-stage").exists())

    def test_real_source_cli_render_check_and_draft_are_suspended(self):
        # 直接执行仓库真实入口，以选定 Python wrapper 固定解释器；不使用 mock 输出。
        # 空项目和错误路径同样只得到暂停，不会创建计划、scratch 或访问 Node。
        self.target.write_bytes(b"historical HTML must stay byte-for-byte")
        before = (renderer.snapshot(self.source), renderer.snapshot(self.target))
        for action, extra in (("render", ["--request-id", REQUEST]), ("check", []),
                              ("render", ["--draft"]), ("render", [])):
            with self.subTest(action=action, extra=extra):
                command = ["bash", str(PACK / "lib/python_runtime.sh"), "-B", "-X", "utf8",
                           str(PACK / "lib/documents/requirement_html.py"), action,
                           "--project", str(self.root), "--source", "docs/plans/change.md", *extra]
                result = subprocess.run(command, cwd=self.work, capture_output=True, text=True, timeout=20)
                with (self.work / "engine.log").open("a", encoding="utf-8") as log:
                    log.write(json.dumps({"argv": command, "exit": result.returncode}, ensure_ascii=False) + "\n")
                    log.write(result.stdout + result.stderr)
                self.assertEqual(2, result.returncode, result.stdout + result.stderr)
                self.assertEqual("", result.stdout)
                self.assertIn("HTML 生成功能已暂停", result.stderr)
        # --help 只展示用法，继续保持原有成功退出，便于安装包/消费者检查入口可用性。
        help_command = ["bash", str(PACK / "lib/python_runtime.sh"), "-B", "-X", "utf8",
                        str(PACK / "lib/documents/requirement_html.py"), "--help"]
        help_result = subprocess.run(help_command, cwd=self.work, capture_output=True, text=True, timeout=20)
        with (self.work / "engine.log").open("a", encoding="utf-8") as log:
            log.write(json.dumps({"argv": help_command, "exit": help_result.returncode}) + "\n")
            log.write(help_result.stdout + help_result.stderr)
        self.assertEqual(0, help_result.returncode, help_result.stdout + help_result.stderr)
        self.assertIn("--source", help_result.stdout)
        self.assertEqual(before, (renderer.snapshot(self.source), renderer.snapshot(self.target)))
        self.assertEqual({"project.yaml", "docs"}, {path.name for path in self.root.iterdir()})

    def test_vendor_checkout_filters_preserve_upstream_bytes(self):
        """真实消费 Git checkout 过滤器，防止 Windows CRLF 改写固定上游载荷。"""
        upstream = json.loads((renderer.VENDOR / "UPSTREAM.json").read_text(encoding="utf-8"))
        for name, facts in upstream["files"].items():
            relative = (renderer.VENDOR / name).relative_to(PACK).as_posix()
            command = ["git", "-c", "core.autocrlf=true", "cat-file", "--filters",
                       "--path=" + relative, "HEAD:" + relative]
            result = subprocess.run(command, cwd=PACK, capture_output=True, timeout=10)
            self.assertEqual(0, result.returncode, result.stderr.decode("utf-8", errors="replace"))
            self.assertEqual(facts["sha256"], hashlib.sha256(result.stdout).hexdigest(), name)

    def test_installed_runtime_preserves_payload_and_rejects_generation(self):
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
            self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
            self.assertEqual("", result.stdout)
            self.assertIn("HTML 生成功能已暂停", result.stderr)
        self.assertFalse((plans / "installed.html").exists())
        self.assertEqual(SAMPLE, (plans / "installed.md").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
