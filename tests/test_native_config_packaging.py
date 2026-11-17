"""独立包离线、可复现和脱离工作流源码后的真实入口验收。"""

from __future__ import annotations

import hashlib
import http.client
import json
import os
from pathlib import Path
import runpy
import selectors
import shlex
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from urllib.parse import parse_qs, urlencode, urlsplit
import zipfile

ROOT = Path(__file__).resolve().parents[1]


class StandalonePackageTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.base = Path(self.temporary.name).resolve()
        self.children = []
        self.home = self.base / "isolated-home"
        self.project = self.base / "plain-project"
        self.state = self.base / "state"
        self.home.mkdir()
        self.project.mkdir()
        self.native_file = self.project / ".codex" / "agents" / "reviewer.toml"
        self.native_file.parent.mkdir(parents=True)
        self.before = (b'name = "reviewer"\ndescription = "native reviewer"\nmodel = "gpt-old"\n'
                       b'developer_instructions = "Preserve the native body"\n')
        self.native_file.write_bytes(self.before)
        self.user_files = {}
        for host, relative, model in (("claude", ".claude/agents/user-scout.md", "sonnet"),
                                      ("antigravity", ".gemini/config/agents/user-scout.md", "flash")):
            path = self.home / relative
            path.parent.mkdir(parents=True)
            path.write_text("---\nname: user-scout\ndescription: native scout\nmodel: " + model + "\n---\nKeep user native body.\n")
            self.user_files[host] = path
        self.plugin = self.home / ".claude/plugins/cache/local-kit/1.0"
        (self.plugin / ".claude-plugin").mkdir(parents=True)
        (self.plugin / "agents").mkdir()
        (self.plugin / ".claude-plugin/plugin.json").write_text('{"name":"local-kit"}')
        (self.plugin / "agents/plugin-scout.md").write_text("---\nname: plugin-scout\ndescription: read only native scout\nmodel: sonnet\n---\nKeep plugin body.\n")
        (self.home / ".claude/plugins/installed_plugins.json").write_text(json.dumps({
            "version": 2, "plugins": {"local-kit@local": [{"scope": "user", "installPath": str(self.plugin)}]}}))
        (self.home / ".claude/settings.json").write_text('{"enabledPlugins":{"local-kit@local":true}}')

    def tearDown(self):
        for child in self.children:
            if child.poll() is None:
                child.terminate()
            child.communicate(timeout=6)
        self.temporary.cleanup()

    def build(self, directory):
        result = subprocess.run([sys.executable, "-B", str(ROOT / "packaging/build_agent_config.py"),
                                 "--output-dir", str(directory)], cwd=self.base,
                                capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)
        report = json.loads(result.stdout)
        self.assertEqual(report["status"], "BUILD_VERIFIED")
        return Path(report["artifact"])

    def unpack(self):
        archive = self.build(self.base / "build")
        installed = self.base / "independent-installed"
        with zipfile.ZipFile(archive) as package:
            package.extractall(installed)
        return installed

    def command(self, installed, mode, *extra):
        # 只交付独立包路径；当前目录没有任何工作流模块，PYTHONPATH 也不参与导入。
        return ["bash", str(installed / "scripts/agent_config.sh"), mode,
                "--data-dir", str(self.state), "--home", str(self.home), "--host", "codex",
                "--project", str(self.project), *extra]

    def test_detached_preference_reader_matches_source_for_all_hosts(self):
        installed = self.unpack()
        relative = "native_config/preference_contract.py"
        self.assertEqual((ROOT / relative).read_bytes(), (installed / relative).read_bytes())
        self.assertEqual((ROOT / "product/command_identity.json").read_bytes(),
                         (installed / "product/command_identity.json").read_bytes())
        # 独立包从包外读取同一显式 home；查询不需要 data-dir 或服务。宿主间仅
        # 根位置不同，内容与逐字段继承均由唯一合同负责，不在打包器另写解析。
        for host, suffix in (("codex", ".codex"), ("claude", ".claude"), ("antigravity", ".gemini/config")):
            with self.subTest(host=host):
                path = self.home / suffix / "native-agent-config/dispatch-preferences.json"
                path.parent.mkdir(parents=True)
                path.write_text(json.dumps({"schema_version": 1, "host": host,
                    "defaults": {"model": "inherit"}, "agents": {}, "projects": {str(self.project): {
                        "defaults": {"model": "inherit"}, "agents": {}}}}))
                before = path.read_bytes()
                arguments = ["--host", host, "--agent", "*", "--home", str(self.home),
                             "--project", str(self.project)]
                values = []
                for source in (installed / relative, ROOT / relative):
                    result = subprocess.run([sys.executable, "-I", "-B", str(source), *arguments],
                        cwd=self.base, capture_output=True, text=True, timeout=8)
                    self.assertEqual(0, result.returncode, result.stderr)
                    values.append(json.loads(result.stdout))
                self.assertEqual(values[0], values[1])
                self.assertEqual({"model": "inherit"}, values[0]["preferences"])
                self.assertFalse(values[0]["runtime_verified"])
                self.assertEqual(before, path.read_bytes())
        self.assertFalse(self.state.exists())

    def test_reproducible_offline_payload_and_shell_queries_have_no_http_prerequisite(self):
        first, second = self.build(self.base / "first"), self.build(self.base / "second")
        self.assertEqual(first.read_bytes(), second.read_bytes())
        with zipfile.ZipFile(first) as package:
            names = package.namelist()
            self.assertTrue(all(name.startswith(("native_config/", "scripts/")) or name in {"README.md", "BUILD.json", "product/command_identity.json", "product/command_identity.py", "product/release_channels.py", "product/__init__.py"} for name in names))
            self.assertFalse(any(name.startswith(("lib/", "manager/", "plugin_runtime/", "plugins/")) for name in names))
            self.assertEqual(package.read("scripts/python_runtime.sh"), (ROOT / "lib/python_runtime.sh").read_bytes())
            self.assertEqual(package.read("native_config/VERSION"), (ROOT / "native_config/VERSION").read_bytes())
            self.assertIn("native_config/activation.py", names)
            self.assertIn("native_config/activation_codecs.py", names)
            self.assertIn("native_config/preparation.py", names)
            record = json.loads(package.read("BUILD.json"))
            self.assertEqual(record["third_party_dependencies"], [])
            for name, digest in record["files"].items():
                self.assertEqual(hashlib.sha256(package.read(name)).hexdigest(), digest)
            installed = self.base / "installed"
            package.extractall(installed)
        environment = dict(os.environ)
        environment.pop("PYTHONPATH", None)
        before_environment = {key: environment.get(key) for key in ("HOME", "CODEX_HOME", "PATH")}
        listed = subprocess.run(self.command(installed, "list"), cwd=self.base, env=environment,
                                capture_output=True, text=True, timeout=8)
        self.assertEqual(listed.returncode, 0, listed.stderr)
        context = json.loads(listed.stdout)
        self.assertNotIn("native_preparation", context)
        self.assertEqual(len(context["roles"]), 1)
        role = context["roles"][0]["role"]
        self.assertTrue(role.startswith("agent_"))
        resolved = subprocess.run(self.command(installed, "resolve", "--role", role), cwd=self.base,
                                  env=environment, capture_output=True, text=True, timeout=8)
        self.assertEqual(resolved.returncode, 0, resolved.stderr)
        self.assertEqual(json.loads(resolved.stdout)["role"], role)
        self.assertFalse(self.state.exists(), "脚本只读查询不能创建HTTP连接或中央状态")
        self.assertEqual({key: environment.get(key) for key in before_environment}, before_environment)
        self.assertEqual(self.native_file.read_bytes(), self.before)
        # 直接入口在旧默认 Python 上必须明确指出可行动的 shell 入口。
        default_python = shutil.which("python3")
        if default_python:
            version = subprocess.run([default_python, "-c", "import sys;print(sys.version_info >= (3,11))"],
                                     capture_output=True, text=True, timeout=4)
            if version.stdout.strip() == "False":
                old = subprocess.run([default_python, str(installed / "scripts/agent_config.py"), "--help"],
                                     capture_output=True, text=True, timeout=4)
                self.assertEqual(old.returncode, 2)
                self.assertIn("agent_config.sh", old.stderr)

    def read_line(self, child):
        with selectors.DefaultSelector() as selector:
            selector.register(child.stdout, selectors.EVENT_READ)
            self.assertTrue(selector.select(8), "独立包入口无响应")
        line = child.stdout.readline()
        self.assertTrue(line, child.stderr.read().decode() if child.poll() is not None else "缺少响应")
        return json.loads(line)

    def send(self, child, message):
        child.stdin.write(json.dumps(message).encode() + b"\n")
        child.stdin.flush()

    def test_extracted_package_real_http_save_and_optional_stdio_share_same_core(self):
        installed = self.unpack()
        environment = dict(os.environ)
        environment.pop("PYTHONPATH", None)
        server = subprocess.Popen(self.command(installed, "serve", "--idle-timeout", "0"), cwd=self.base,
                                  env=environment, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        self.children.append(server)
        started = self.read_line(server)
        parsed = urlsplit(started["url"])
        headers = {"Authorization": "Bearer " + parse_qs(parsed.fragment)["token"][0],
                   "Origin": f"http://127.0.0.1:{parsed.port}", "Content-Type": "application/json"}

        def api(method, path, data=None, expected=200):
            connection = http.client.HTTPConnection("127.0.0.1", parsed.port, timeout=4)
            try:
                connection.request(method, path, body=json.dumps(data) if data else None, headers=headers)
                response = connection.getresponse()
                raw = response.read()
                self.assertEqual(response.status, expected, raw)
                return json.loads(raw)
            finally:
                connection.close()

        context = api("GET", "/api/context?" + urlencode({"host": "codex", "scope": "project", "project": str(self.project)}))
        role = context["roles"][0]["role"]
        plan = api("POST", "/api/preview", {"host": "codex", "scope": "project", "project": str(self.project),
                   "revision": context["revision"], "edits": {role: {"model": "future-model", "effort": "ultra"}}})
        self.assertEqual(self.native_file.read_bytes(), self.before)
        saved = api("POST", "/api/apply", {"preview_id": plan["preview_id"]})
        self.assertTrue(saved["saved"])
        self.assertFalse(saved["effect"]["runtime_verified"])
        self.assertIn(b'model = "future-model"', self.native_file.read_bytes())
        self.assertIn(b'model_reasoning_effort = "ultra"', self.native_file.read_bytes())
        self.assertIn(b"Preserve the native body", self.native_file.read_bytes())
        # 同一已解压服务覆盖另两平台的用户定义，并真实拒绝插件来源写入。
        for host, model in (("claude", "opus"), ("antigravity", "pro")):
            native_context = api("GET", "/api/context?" + urlencode({"host": host, "scope": "global"}))
            user = next(row for row in native_context["roles"] if row["origin"] == "user")
            if host == "claude":
                plugin = next(row for row in native_context["roles"] if row["origin"] == "plugin")
                self.assertFalse(plugin["writable"])
                denied = api("POST", "/api/preview", {"host": host, "scope": "global",
                    "revision": native_context["revision"], "edits": {plugin["role"]: {"model": "opus"}}}, expected=400)
                self.assertEqual(denied["error"]["code"], "invalid_request")
            user_before = self.user_files[host].read_bytes()
            plan = api("POST", "/api/preview", {"host": host, "scope": "global",
                       "revision": native_context["revision"], "edits": {user["role"]: {"model": model}}})
            self.assertEqual(self.user_files[host].read_bytes(), user_before)
            outcome = api("POST", "/api/apply", {"preview_id": plan["preview_id"]})
            self.assertTrue(outcome["saved"])
            saved_user = next(row for row in outcome["context"]["roles"] if row["role"] == user["role"])
            self.assertEqual(saved_user["overrides"]["model"], model)
            self.assertNotEqual(self.user_files[host].read_bytes(), user_before)
            reset = api("POST", "/api/preview", {"host": host, "scope": "global",
                        "revision": outcome["context"]["revision"], "reset": True})
            reset_result = api("POST", "/api/apply", {"preview_id": reset["preview_id"]})
            self.assertTrue(reset_result["saved"])
            self.assertNotIn(b"model:", self.user_files[host].read_bytes())
            self.assertIn(b"Keep user native body.", self.user_files[host].read_bytes())
        self.assertIn(b"model: sonnet", (self.plugin / "agents/plugin-scout.md").read_bytes())
        # 网页先独立启动并完成保存，随后才手动开启可选 MCP。
        mcp = subprocess.Popen(self.command(installed, "mcp"), cwd=self.base, env=environment,
                               stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        self.children.append(mcp)
        self.send(mcp, {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
            "protocolVersion": "2025-11-25", "capabilities": {}, "clientInfo": {"name": "isolated-test", "version": "1"}}})
        self.assertEqual(self.read_line(mcp)["result"]["serverInfo"]["name"], "native-agent-config")
        self.send(mcp, {"jsonrpc": "2.0", "method": "notifications/initialized"})
        self.send(mcp, {"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
        tools = self.read_line(mcp)["result"]["tools"]
        self.assertEqual({tool["name"] for tool in tools}, {"get_model_preferences", "resolve_subagent", "open_console"})
        resolver = next(tool for tool in tools if tool["name"] == "resolve_subagent")
        self.assertNotIn("enum", resolver["inputSchema"]["properties"]["role"])
        self.send(mcp, {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "get_model_preferences"}})
        preferences = self.read_line(mcp)["result"]["structuredContent"]
        self.assertEqual(preferences["roles"][0]["overrides"]["model"], "future-model")
        self.send(mcp, {"jsonrpc": "2.0", "id": 4, "method": "tools/call", "params": {"name": "open_console"}})
        opened = self.read_line(mcp)["result"]["structuredContent"]
        self.assertEqual(opened["url"], started["url"])
        self.assertTrue(opened["reused"])
        mcp.stdin.close()
        mcp.stdin = None
        self.assertEqual(mcp.wait(timeout=5), 0)
        self.assertIsNone(server.poll())
        server.terminate()
        self.assertEqual(server.wait(timeout=5), 0)
        self.assertFalse((self.state / "console/connection.json").exists())
        self.assertFalse((self.project / ".awf").exists())
        self.assertFalse((self.project / ".agent-workflow").exists())

    def test_missing_version_and_workflow_dependency_are_rejected(self):
        source = self.base / "source"
        # 负向边界在版本与导入审查处即应拒绝；仅构造最小输入，避免复制真实源码树。
        (source / "native_config").mkdir(parents=True)
        version = source / "native_config/VERSION"
        saved_version = (ROOT / "native_config/VERSION").read_bytes()

        def attempt():
            return subprocess.run([sys.executable, "-B", str(ROOT / "packaging/build_agent_config.py"),
                                   "--source", str(source), "--output-dir", str(self.base / "invalid")],
                                  capture_output=True, text=True, timeout=8)

        self.assertNotEqual(attempt().returncode, 0)
        version.write_bytes(saved_version)
        # 补齐真实必要身份闭包后，拒绝必须来自依赖审查，不能被缺 JSON 提前遮蔽。
        (source / "product").mkdir()
        for name in ("__init__.py", "command_identity.py", "command_identity.json", "release_channels.py"):
            shutil.copyfile(ROOT / "product" / name, source / "product" / name)
        payload = runpy.run_path(str(ROOT / "packaging/build_agent_config.py"))["payload"]
        for dependency in ("import manager", "from product import command_identity",
                           "from product.command_identity import *", "from .product.command_identity import load_identity",
                           "from ..product.command_identity import load_identity", "from . import missing_module",
                           "from .missing_module import value", "import native_config.missing_module"):
            with self.subTest(dependency=dependency):
                (source / "native_config/cli.py").write_text(dependency + "\n")
                # CLI 有意隐藏内部错误；在公开构建函数边界验证真实拒绝原因。
                with self.assertRaisesRegex(ValueError, "独立核心包含非标准库或工作流依赖"):
                    payload(source)
        self.assertFalse((self.base / "invalid").exists())

    def test_current_abi_rejects_missing_session_and_web_resources_with_valid_build(self):
        """摘要自洽仍不足以执行当前包；历史认证与当前 ABI 拒绝保持两条边界。"""
        store = runpy.run_path(str(ROOT / "plugins/maintenance/component_store.py"))
        archive = self.build(self.base / "build")
        with zipfile.ZipFile(archive) as package:
            complete = {name: package.read(name) for name in package.namelist()}
        version = complete["native_config/VERSION"].decode("ascii").strip()
        # 每次只移除一个实际运行资源，并同步重算 BUILD 与 ZIP 摘要，防止
        # 普通完整性报错遮蔽当前 ABI 的缺失拒绝。无需启动或修改任何用户组件。
        rejected = self.base / "incomplete.zip"
        for missing in ("native_config/web/connection.js", "native_config/web/native-definitions.js",
                        "native_config/browser_sessions.py"):
            with self.subTest(missing=missing):
                bodies = {name: body for name, body in complete.items() if name != missing}
                manifest = json.loads(bodies["BUILD.json"])
                del manifest["files"][missing]
                bodies["BUILD.json"] = json.dumps(manifest, sort_keys=True).encode()
                self.assertEqual(store["checked_build"](bodies, version), manifest)
                with zipfile.ZipFile(rejected, "w") as package:
                    for name, body in bodies.items():
                        package.writestr(name, body)
                digest = hashlib.sha256(rejected.read_bytes()).hexdigest()
                with self.assertRaisesRegex(store["ComponentError"], "invalid_build_manifest"):
                    store["archive_payload"](rejected, version, digest)

    def test_detached_package_consumes_session_and_exact_static_resource_closure(self):
        """包外真实 HTTP 兑换并使用派生会话，同时逐字节消费两个新增页面脚本。"""
        installed = self.unpack()
        environment = dict(os.environ)
        environment.pop("PYTHONPATH", None)
        server = subprocess.Popen(self.command(installed, "serve", "--idle-timeout", "0"),
            cwd=self.base, env=environment, stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        self.children.append(server)
        started = self.read_line(server)
        parsed = urlsplit(started["url"])
        origin = f"http://127.0.0.1:{parsed.port}"

        def request(method, path, headers, data=None):
            connection = http.client.HTTPConnection("127.0.0.1", parsed.port, timeout=4)
            try:
                connection.request(method, path, body=json.dumps(data) if data is not None else None,
                                   headers=headers)
                response = connection.getresponse()
                return response.status, response.read()
            finally:
                connection.close()

        headers = {"Authorization": "Bearer " + parse_qs(parsed.fragment)["token"][0],
                   "Origin": origin, "Content-Type": "application/json"}
        status, raw = request("POST", "/api/session", headers, {})
        self.assertEqual(status, 200, raw)
        session = json.loads(raw)
        headers["Authorization"] = "Bearer " + session["session_token"]
        status, raw = request("GET", "/api/context?" + urlencode({"host": "codex", "scope": "project",
                              "project": str(self.project)}), headers)
        self.assertEqual(status, 200, raw)
        self.assertEqual(json.loads(raw)["host"], "codex")
        # 静态资源通过公开 HTTP 路由读取；不能只看 ZIP 名称就声称浏览器可加载。
        for name in ("index.html", "console.css", "console.js", "connection.js", "native-definitions.js"):
            with self.subTest(resource=name):
                path = "/" if name == "index.html" else "/" + name
                status, body = request("GET", path, {})
                self.assertEqual(status, 200, body)
                self.assertEqual(body, (ROOT / "native_config/web" / name).read_bytes())
        self.assertEqual(self.native_file.read_bytes(), self.before)

    def test_identity_content_pin_rejects_safe_but_unapproved_changes(self):
        """唯一数据声明经规范化 pin 约束；安全形状不能放宽插件、别名或旧角色权限。"""
        from product.command_identity import load_identity
        source = self.base / "identity-source"
        (source / "product").mkdir(parents=True)
        identity = source / "product/command_identity.json"
        approved = json.loads((ROOT / "product/command_identity.json").read_bytes())
        identity.write_text(json.dumps(approved, sort_keys=True))
        self.assertEqual(load_identity(source), approved)
        for field, value in (("schema_version", True), ("plugin_name", "other-plugin"),
                             ("skill_aliases", {**approved["skill_aliases"], "xy-taste": "grill-me"}),
                             ("managed_roles", approved["managed_roles"][:-1] + ["xy-unknown"]),
                             ("legacy_plugin_name", "other-legacy"),
                             ("marketplaces", {"alpha": "other-alpha", "local": "xy-workflow-local"})):
            with self.subTest(field=field):
                identity.write_text(json.dumps({**approved, field: value}))
                with self.assertRaises(ValueError):
                    load_identity(source)
        identity.write_text('{"schema_version":1,"schema_version":1}')
        with self.assertRaises(ValueError):
            load_identity(source)
        identity.unlink()
        identity.symlink_to(ROOT / "product/command_identity.json")
        with self.assertRaises(ValueError):
            load_identity(source)

    def test_disabled_workflow_recovers_by_reopening_extracted_independent_package(self):
        """停用后关闭服务，真实执行解压包给出的 open 命令并恢复；不借工作流源码导入。"""
        installed = self.unpack()
        user_config = self.home / ".codex/config.toml"
        user_config.parent.mkdir(parents=True)
        user_config.write_text('[marketplaces."agent-workflow-alpha"]\nsource_type="git"\n'
                               'source="https://github.com/Geoege-xll/agent-workflow.git"\n'
                               'ref="plugins-codex-alpha"\n'
                               '[plugins."agent-workflow@agent-workflow-alpha"]\nenabled=true\n')
        target = self.project / ".codex/config.toml"
        original = (b'# Preserve native preferences\nmodel = "existing-model"\n'
                    b'[plugins."unrelated@market"]\nenabled = true\n')
        target.write_bytes(original)
        environment = dict(os.environ)
        environment.pop("PYTHONPATH", None)
        connection_path = self.state / "console/connection.json"
        record = None

        def stop():
            nonlocal record
            if record is None:
                return
            # PID 仅取本测试独立状态根的连接记录；不搜索或回收本机其他用户服务。
            try:
                os.kill(record["pid"], signal.SIGTERM)
            except ProcessLookupError:
                pass
            deadline = time.monotonic() + 6
            while connection_path.exists() and time.monotonic() < deadline:
                time.sleep(0.05)
            self.assertFalse(connection_path.exists(), "本测试独立服务应完成关闭及连接清理")
            connection = http.client.HTTPConnection("127.0.0.1", record["port"], timeout=1)
            try:
                with self.assertRaises(OSError):
                    connection.connect()
            finally:
                connection.close()
            record = None

        def start(command):
            nonlocal record
            result = subprocess.run(command, cwd=self.base, env=environment,
                                    capture_output=True, text=True, timeout=12)
            # 即使 open 返回失败也保留自有 PID，以便 finally 真正关闭可能已启动的服务。
            if connection_path.exists():
                record = json.loads(connection_path.read_text())
            self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
            opened = json.loads(result.stdout)
            self.assertEqual(opened["state"], "ready")
            self.assertEqual(Path(opened["component"]["root"]), installed)
            self.assertEqual(opened["component"]["source"], "release")
            self.assertFalse(opened["service"]["reused"])

        def api(method, path, data=None):
            connection = http.client.HTTPConnection("127.0.0.1", record["port"], timeout=4)
            try:
                headers = {"Authorization": "Bearer " + record["token"],
                           "Origin": f'http://127.0.0.1:{record["port"]}', "Content-Type": "application/json"}
                connection.request(method, path, body=json.dumps(data) if data is not None else None, headers=headers)
                response = connection.getresponse()
                raw = response.read()
                self.assertEqual(response.status, 200, raw)
                return json.loads(raw)
            finally:
                connection.close()

        query = "/api/context?" + urlencode({"host": "codex", "scope": "project", "project": str(self.project)})
        try:
            start(self.command(installed, "open", "--no-browser"))
            context = api("GET", query)
            recovery = context["workflow_activation"]["recovery"]["open_command"]
            self.assertEqual(Path(shlex.split(recovery)[1]), installed / "scripts/agent_config.sh")
            for state in ("disabled", "enabled", "inherit"):
                before = target.read_bytes()
                plan = api("POST", "/api/preview", {"host": "codex", "scope": "project",
                           "project": str(self.project), "revision": context["revision"],
                           "workflow_activation": {"state": state}})
                self.assertEqual(target.read_bytes(), before)
                outcome = api("POST", "/api/apply", {"preview_id": plan["preview_id"]})
                self.assertTrue(outcome["saved"])
                self.assertFalse(outcome["effect"]["runtime_verified"])
                context = outcome["context"]
                self.assertEqual(context["workflow_activation"]["state"], state)
                self.assertEqual(self.native_file.read_bytes(), self.before)
                self.assertIn(b'model = "existing-model"', target.read_bytes())
                self.assertIn(b'[plugins."unrelated@market"]\nenabled = true', target.read_bytes())
                if state == "disabled":
                    stop()
                    # 页面命令必须自行携带原配置根与状态根，消费者只关闭浏览器打开行为；
                    # 手工补根参数会掩盖停用后重开到错误配置位置的恢复缺陷。
                    start(shlex.split(recovery) + ["--no-browser"])
                    context = api("GET", query)
                    self.assertEqual(context["workflow_activation"]["state"], "disabled")
            self.assertEqual(context["workflow_activation"]["effective_state"], "enabled")
        finally:
            stop()

    def test_thin_plugin_prepares_real_zip_outside_repository_and_reuses_safe_service(self):
        """真实源码包只通过显式 ZIP 进入独立根；插件目录始终没有配置核心或网页。"""
        archive = self.build(self.base / "release")
        hosts = ("codex", "claude", "antigravity")
        thins = {}
        for host in hosts:
            thin = self.base / (host + " standalone plugin with spaces") / "plugins" / "maintenance"
            thin.mkdir(parents=True)
            thins[host] = thin
            for name in ("launcher.py", "launcher.sh", "component_store.py"):
                shutil.copyfile(ROOT / "plugins/maintenance" / name, thin / name)
            # 三个物理插件根共享同一真实组件，但来源身份不同。-I 子进程从包外
            # 启动，不借源码根掩盖缺失依赖，也不在薄插件里放核心或网页。
            product = thin.parents[1] / "product"
            product.mkdir()
            for name in ("__init__.py", "release_channels.py"):
                shutil.copyfile(ROOT / "product" / name, product / name)
        with zipfile.ZipFile(archive) as package:
            version = package.read("native_config/VERSION").decode("ascii").strip()
        from product.release_channels import version_channel
        component = {"schema_version": 1, "product": "native-agent-config", "version": version,
                     "channel": version_channel(version), "cli_protocol": 1, "service_protocol": 2, "release_status": "unpublished",
                     "artifact": {"name": archive.name, "sha256": hashlib.sha256(archive.read_bytes()).hexdigest(), "url": ""}}
        descriptors = {}
        for host, thin in thins.items():
            descriptors[host] = thin / "component.json"
            descriptors[host].write_text(json.dumps(component))
        component_root = self.base / "independent user components"
        environment = dict(os.environ)
        environment.pop("PYTHONPATH", None)
        before_environment = {key: environment.get(key) for key in ("HOME", "CODEX_HOME", "PATH")}
        # API 依赖注入只选择临时组件根；生产 CLI 不提供替换 descriptor/root 的参数。
        harness = ("import json,sys;from pathlib import Path;sys.path.insert(0,sys.argv[1]);import launcher;"
                   "result,code=launcher.run(json.loads(sys.argv[2]),component_root=Path(sys.argv[3]),"
                   "descriptor_path=Path(sys.argv[4]));print(json.dumps(result));raise SystemExit(code)")

        def launch(action, *extra, host="codex"):
            args = [action, "--host", host, "--home", str(self.home), "--project", str(self.project), *extra]
            result = subprocess.run([sys.executable, "-I", "-B", "-c", harness, str(thins[host]), json.dumps(args),
                                     str(component_root), str(descriptors[host])], cwd=self.base, env=environment,
                                    capture_output=True, text=True, timeout=45)
            return result, json.loads(result.stdout)

        connection_paths = {host: component_root / "state" / host / "console/connection.json" for host in hosts}
        connection_path = connection_paths["codex"]
        pids = {}
        try:
            result, missing = launch("open", "--no-browser")
            self.assertEqual((result.returncode, missing["state"]), (2, "preparation_required"))
            self.assertFalse(component_root.exists())
            result, opened = launch("open", "--prepare", "--artifact", str(archive), "--no-browser")
            if connection_path.exists():
                pids["codex"] = json.loads(connection_path.read_text())["pid"]
            self.assertEqual(result.returncode, 0, (result.stderr, opened))
            self.assertEqual((opened["state"], opened["service"]["reused"]), ("ready", False))
            self.assertNotIn("token=", json.dumps(opened))
            launch_file = Path(opened["launch_file"])
            self.assertTrue(launch_file.is_file())
            self.assertEqual(launch_file.stat().st_mode & 0o777, 0o600)
            self.assertIn("#token=", launch_file.read_text())
            self.assertEqual(opened["component"]["source"], "release")
            result, reused = launch("open", "--no-browser")
            self.assertEqual((result.returncode, reused["service"]["reused"]), (0, True), reused)
            self.assertEqual(opened["console_url"], reused["console_url"])
            self.assertEqual(json.loads(connection_path.read_text())["pid"], pids["codex"])
            # 连续从三个不同物理插件入口真实打开，组件只安装一份；宿主状态
            # 各有来源绑定，不能要求用户先停止另一宿主的控制台才能打开本宿主。
            for host in hosts[1:]:
                result, other = launch("open", "--no-browser", host=host)
                if connection_paths[host].exists():
                    pids[host] = json.loads(connection_paths[host].read_text())["pid"]
                self.assertEqual((result.returncode, other["state"]), (0, "ready"), (host, other, result.stderr))
                self.assertFalse(other["service"]["reused"])
            self.assertEqual(len(set(pids.values())), 3)
            identities = [json.loads(path.read_text())["configuration_identity"] for path in connection_paths.values()]
            self.assertEqual(len(set(identities)), 3)
            self.assertFalse((component_root / "state/console").exists())
            for host in hosts:
                result, repeated = launch("open", "--no-browser", host=host)
                self.assertEqual((result.returncode, repeated["state"], repeated["service"]["reused"]), (0, "ready", True), (host, repeated))
                self.assertEqual(json.loads(connection_paths[host].read_text())["pid"], pids[host])
            before = {str(path.relative_to(component_root)): (path.stat().st_mode, path.read_bytes() if path.is_file() else None)
                      for path in component_root.rglob("*")}
            for host in hosts:
                for action in ("status", "doctor"):
                    result, readonly = launch(action, host=host)
                    self.assertEqual((result.returncode, readonly["state"]), (0, "ready"), (host, readonly))
                    self.assertIsNone(readonly["launch_file"])
                    self.assertNotIn("token=", json.dumps(readonly))
                    if action == "doctor":
                        self.assertEqual(readonly["component"]["integrity"], "verified")
            # 启动器的隔离不能削弱独立 CLI：手工复用同一 data-dir 却换来源，
            # 仍必须明确拒绝，而非复用旧服务或悄悄重新绑定现有连接记录。
            independent = Path(opened["component"]["root"]) / "scripts/agent_config.sh"
            for action in ("open", "status"):
                command = ["bash", str(independent), action, "--host", "codex", "--home", str(self.home),
                           "--project", str(self.project), "--data-dir", str(component_root / "state/codex"),
                           "--preparation-source", str(thins["claude"].parents[1])]
                if action == "open":
                    command.append("--no-browser")
                conflict = subprocess.run(command, cwd=self.base, env=environment, capture_output=True, text=True, timeout=15)
                response = json.loads(conflict.stdout)
                self.assertEqual((conflict.returncode, response["code"]), (1, "configuration_conflict"), response)
            after = {str(path.relative_to(component_root)): (path.stat().st_mode, path.read_bytes() if path.is_file() else None)
                     for path in component_root.rglob("*")}
            self.assertEqual(after, before)
            self.assertTrue(all(not (thin / "native_config").exists() for thin in thins.values()))
            self.assertFalse((self.project / ".awf").exists())
            self.assertFalse((self.project / "AGENTS.md").exists())
            self.assertEqual(self.native_file.read_bytes(), self.before)
            self.assertEqual({key: environment.get(key) for key in before_environment}, before_environment)
        finally:
            # 只回收本测试独立根记录的真实服务，绝不探测或终止本机已有用户服务。
            # 兼容断言失败时的旧单 state 路径，仅清理本测试临时根内真正启动的
            # 子服务，不扫描用户目录，也不迁移或关闭任何生产旧控制台。
            cleanup_paths = [*connection_paths.values(), component_root / "state/console/connection.json"]
            for path in cleanup_paths:
                if not path.exists():
                    continue
                pid = json.loads(path.read_text())["pid"]
                try:
                    os.kill(pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass
                deadline = time.monotonic() + 5
                while path.exists() and time.monotonic() < deadline:
                    time.sleep(0.05)


if __name__ == "__main__":
    unittest.main()
