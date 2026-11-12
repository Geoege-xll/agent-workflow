"""独立包离线、可复现和脱离工作流源码后的真实入口验收。"""

from __future__ import annotations

import hashlib
import http.client
import json
import os
from pathlib import Path
import selectors
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

    def test_reproducible_offline_payload_and_shell_queries_have_no_http_prerequisite(self):
        first, second = self.build(self.base / "first"), self.build(self.base / "second")
        self.assertEqual(first.read_bytes(), second.read_bytes())
        with zipfile.ZipFile(first) as package:
            names = package.namelist()
            self.assertTrue(all(name.startswith(("native_config/", "scripts/")) or name in {"README.md", "BUILD.json"} for name in names))
            self.assertFalse(any(name.startswith(("lib/", "manager/", "plugin_runtime/", "plugins/", "product/")) for name in names))
            self.assertEqual(package.read("scripts/python_runtime.sh"), (ROOT / "lib/python_runtime.sh").read_bytes())
            self.assertEqual(package.read("native_config/VERSION"), (ROOT / "native_config/VERSION").read_bytes())
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
        shutil.copytree(ROOT / "native_config", source / "native_config", ignore=shutil.ignore_patterns("__pycache__"))
        (source / "scripts").mkdir()
        for name in ("agent_config.py", "agent_config.sh", "python_runtime.sh"):
            shutil.copyfile(ROOT / "scripts" / name, source / "scripts" / name)
        version = source / "native_config/VERSION"
        saved_version = version.read_bytes()
        version.unlink()

        def attempt():
            return subprocess.run([sys.executable, "-B", str(ROOT / "packaging/build_agent_config.py"),
                                   "--source", str(source), "--output-dir", str(self.base / "invalid")],
                                  capture_output=True, text=True, timeout=8)

        self.assertNotEqual(attempt().returncode, 0)
        version.write_bytes(saved_version)
        with (source / "native_config/cli.py").open("a", encoding="utf-8") as stream:
            stream.write("\nimport manager\n")
        self.assertNotEqual(attempt().returncode, 0)
        self.assertFalse((self.base / "invalid").exists())

    def test_thin_plugin_prepares_real_zip_outside_repository_and_reuses_safe_service(self):
        """真实源码包只通过显式 ZIP 进入独立根；插件目录始终没有配置核心或网页。"""
        archive = self.build(self.base / "release")
        thin = self.base / "standalone plugin with spaces" / "plugins" / "maintenance"
        thin.mkdir(parents=True)
        for name in ("launcher.py", "launcher.sh", "component_store.py"):
            shutil.copyfile(ROOT / "plugins/maintenance" / name, thin / name)
        with zipfile.ZipFile(archive) as package:
            version = package.read("native_config/VERSION").decode("ascii").strip()
        component = {"schema_version": 1, "product": "native-agent-config", "version": version,
                     "channel": "alpha", "cli_protocol": 1, "service_protocol": 2, "release_status": "unpublished",
                     "artifact": {"name": archive.name, "sha256": hashlib.sha256(archive.read_bytes()).hexdigest(), "url": ""}}
        descriptor = thin / "component.json"
        descriptor.write_text(json.dumps(component))
        component_root = self.base / "independent user components"
        environment = dict(os.environ)
        environment.pop("PYTHONPATH", None)
        before_environment = {key: environment.get(key) for key in ("HOME", "CODEX_HOME", "PATH")}
        # API 依赖注入只选择临时组件根；生产 CLI 不提供替换 descriptor/root 的参数。
        harness = ("import json,sys;from pathlib import Path;sys.path.insert(0,sys.argv[1]);import launcher;"
                   "result,code=launcher.run(json.loads(sys.argv[2]),component_root=Path(sys.argv[3]),"
                   "descriptor_path=Path(sys.argv[4]));print(json.dumps(result));raise SystemExit(code)")

        def launch(action, *extra):
            args = [action, "--host", "codex", "--home", str(self.home), "--project", str(self.project), *extra]
            result = subprocess.run([sys.executable, "-I", "-B", "-c", harness, str(thin), json.dumps(args),
                                     str(component_root), str(descriptor)], cwd=self.base, env=environment,
                                    capture_output=True, text=True, timeout=45)
            return result, json.loads(result.stdout)

        connection_path = component_root / "state/console/connection.json"
        pid = None
        try:
            result, missing = launch("open", "--no-browser")
            self.assertEqual((result.returncode, missing["state"]), (2, "preparation_required"))
            self.assertFalse(component_root.exists())
            result, opened = launch("open", "--prepare", "--artifact", str(archive), "--no-browser")
            if connection_path.exists():
                pid = json.loads(connection_path.read_text())["pid"]
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
            self.assertEqual(json.loads(connection_path.read_text())["pid"], pid)
            before = {str(path.relative_to(component_root)): (path.stat().st_mode, path.read_bytes() if path.is_file() else None)
                      for path in component_root.rglob("*")}
            for action in ("status", "doctor"):
                result, readonly = launch(action)
                self.assertEqual((result.returncode, readonly["state"]), (0, "ready"), readonly)
                self.assertIsNone(readonly["launch_file"])
                self.assertNotIn("token=", json.dumps(readonly))
                if action == "doctor":
                    self.assertEqual(readonly["component"]["integrity"], "verified")
            after = {str(path.relative_to(component_root)): (path.stat().st_mode, path.read_bytes() if path.is_file() else None)
                     for path in component_root.rglob("*")}
            self.assertEqual(after, before)
            self.assertFalse((thin / "native_config").exists())
            self.assertFalse((self.project / ".awf").exists())
            self.assertFalse((self.project / "AGENTS.md").exists())
            self.assertEqual(self.native_file.read_bytes(), self.before)
            self.assertEqual({key: environment.get(key) for key in before_environment}, before_environment)
        finally:
            # 只回收本测试独立根记录的真实服务，绝不探测或终止本机已有用户服务。
            if pid is None and connection_path.exists():
                pid = json.loads(connection_path.read_text())["pid"]
            if pid is not None:
                try:
                    os.kill(pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass
                deadline = time.monotonic() + 5
                while connection_path.exists() and time.monotonic() < deadline:
                    time.sleep(0.05)


if __name__ == "__main__":
    unittest.main()
