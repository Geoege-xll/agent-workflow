"""MCP 的容量负控与真实 stdio 握手；所有状态均放在临时目录。"""

from __future__ import annotations

import io
import json
import os
from pathlib import Path
import selectors
import signal
import subprocess
import sys
import tempfile
import time
import unittest

from native_config.mcp import MAX_LINE, McpSession, run_stdio
from native_config.server import ROOT, read_connection

AGENT_ID = "agent_" + "a" * 64


def initialize(request_id=1, version="2025-11-25"):
    return {"jsonrpc": "2.0", "id": request_id, "method": "initialize", "params": {
        "protocolVersion": version, "capabilities": {}, "clientInfo": {"name": "test-client", "version": "1"}}}


class FakeService:
    def context(self, host, scope="global", project=None):
        if host == "claude":
            raise ValueError("机密路径 /private/user/secret")
        return {"host": host, "scope": scope, "project": project, "roles": []}

    def resolve_subagent(self, host, role, project=None):
        if host == "antigravity":
            raise RuntimeError("机密路径 /private/user/secret")
        return {"role": role, "dispatch": {}, "dispatch_ready": False,
                "blocked_reason": "unknown_client_version", "runtime_verified": False}


class McpProtocolTest(unittest.TestCase):
    def setUp(self):
        self.session = McpSession(FakeService(), data_dir=Path("/tmp/unused-mcp-data"),
                                  version="0.1.0-alpha.1", console_opener=lambda *_args, **_kwargs: {"url": "http://127.0.0.1:1234/#token=test"})

    def ready(self):
        result = self.session.handle(initialize())
        self.assertEqual(result["result"]["protocolVersion"], "2025-11-25")
        self.assertIsNone(self.session.handle({"jsonrpc": "2.0", "method": "notifications/initialized"}))

    def call(self, name, arguments=None):
        return self.session.handle({"jsonrpc": "2.0", "id": 8, "method": "tools/call", "params": {
            "name": name, "arguments": arguments or {}}})

    def test_lifecycle_notifications_ping_unknown_and_parameter_controls(self):
        self.assertEqual(self.call("get_model_preferences")["error"]["code"], -32002)
        self.assertEqual(self.session.handle({"jsonrpc": "2.0", "id": 0, "method": "ping"})["result"], {})
        self.ready()
        self.assertIsNone(self.session.handle({"jsonrpc": "2.0", "method": "notifications/cancelled", "params": {"requestId": 99}}))
        self.assertIsNone(self.session.handle({"jsonrpc": "2.0", "method": "notifications/unknown"}))
        self.assertEqual(self.session.handle({"jsonrpc": "2.0", "id": 4, "method": "arbitrary/exec"})["error"]["code"], -32601)
        self.assertEqual(self.call("run_command", {"command": "whoami"})["error"]["code"], -32602)
        for name, arguments in (("get_model_preferences", {"scope": ["project"]}),
                                ("get_model_preferences", {"home": "/tmp/other-home"}),
                                ("get_model_preferences", {"project": "relative"}),
                                ("resolve_subagent", {"role": ""}),
                                ("resolve_subagent", {"role": AGENT_ID, "command": "whoami"}),
                                ("open_console", {"open_browser": "true"})):
            self.assertEqual(self.call(name, arguments)["error"]["code"], -32602)

    def test_three_tools_preserve_structured_result_and_redact_errors(self):
        self.ready()
        listed = self.session.handle({"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {"_meta": {}}})["result"]["tools"]
        self.assertEqual({tool["name"] for tool in listed}, {"get_model_preferences", "resolve_subagent", "open_console"})
        self.assertTrue(all(tool["inputSchema"]["additionalProperties"] is False for tool in listed))
        resolved = self.call("resolve_subagent", {"role": AGENT_ID})["result"]
        self.assertFalse(resolved["isError"])
        self.assertFalse(resolved["structuredContent"]["dispatch_ready"])
        self.assertIn("blocked_reason", resolved["structuredContent"])
        self.assertEqual(json.loads(resolved["content"][0]["text"]), resolved["structuredContent"])
        self.assertFalse(self.call("open_console")["result"]["isError"])
        for name, arguments in (("get_model_preferences", {"host": "claude"}),
                                ("resolve_subagent", {"host": "antigravity", "role": AGENT_ID})):
            result = self.call(name, arguments)["result"]
            self.assertTrue(result["isError"])
            self.assertNotIn("secret", json.dumps(result))
            self.assertNotIn("机密", json.dumps(result, ensure_ascii=False))

    def test_existing_readonly_query_projects_actual_dispatch_preferences(self):
        from native_config import ModelService
        with tempfile.TemporaryDirectory() as raw:
            home = Path(raw).resolve()
            service = ModelService(home / "state", home)
            before = service.context("codex")
            plan = service.preview({"host": "codex", "revision": before["revision"],
                                    "dispatch_preferences": {"edits": {"*": {"model": "gpt-6", "effort": "high"}}}})
            self.assertTrue(service.apply(plan["preview_id"])["saved"])
            self.session.service = service
            self.ready()
            result = self.call("get_model_preferences")["result"]
            self.assertFalse(result["isError"])
            self.assertRegex(result["structuredContent"]["catalog_source_stamp"], r"^[0-9a-f]{64}$")
            preferences = result["structuredContent"]["dispatch_preferences"]
            self.assertEqual(preferences["targets"][0]["effective"], {"model": "gpt-6", "effort": "high"})
            self.assertFalse(preferences["runtime_verified"])
            self.assertFalse((home / "state").exists())

    def test_version_negotiation_and_malformed_json_capacity_recovery(self):
        negotiated = self.session.handle(initialize(version="2099-01-01"))["result"]
        self.assertEqual(negotiated["protocolVersion"], "2025-11-25")
        messages = [b"{bad\n", b"x" * (MAX_LINE + 100) + b"\n", b"[]\n",
                    b'{"jsonrpc":"2.0","jsonrpc":"2.0","id":1,"method":"ping"}\n',
                    b'{"jsonrpc":"2.0","id":"\\ud800","method":"ping"}\n',
                    b'{"jsonrpc":"2.0","id":1e999,"method":"ping"}\n',
                    b'{"jsonrpc":"2.0","id":9,"method":"ping"}\n']
        output = io.BytesIO()
        self.assertEqual(run_stdio(FakeService(), data_dir=Path("/tmp/unused"), input_stream=io.BytesIO(b"".join(messages)),
                                   output_stream=output, version="0.1.0-alpha.1", console_opener=lambda *_args, **_kw: {}), 0)
        results = [json.loads(line) for line in output.getvalue().splitlines()]
        self.assertEqual([value["error"]["code"] for value in results[:-1]], [-32700, -32600, -32600, -32700, -32700, -32700])
        self.assertEqual(results[-1], {"jsonrpc": "2.0", "id": 9, "result": {}})


class McpSubprocessTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.data_dir = Path(self.temporary.name).resolve() / "model-data"
        self.project = Path(self.temporary.name).resolve() / "plain-project"
        self.project.mkdir()
        self.home = Path(self.temporary.name).resolve() / "home"
        self.home.mkdir()
        self.native_file = self.project / ".codex" / "agents" / "backend.toml"
        self.native_file.parent.mkdir(parents=True)
        self.native_before = (b'name = "backend"\ndescription = "test native agent"\n'
                              b'model = "gpt-old"\ndeveloper_instructions = "Keep native body"\n')
        self.native_file.write_bytes(self.native_before)
        self.children = []
        self.console_pid = None

    def tearDown(self):
        for child in self.children:
            if child.poll() is None:
                child.terminate()
            child.communicate(timeout=5)
        if self.console_pid:
            try:
                os.kill(self.console_pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            deadline = time.monotonic() + 4
            while (self.data_dir / "console" / "connection.json").exists() and time.monotonic() < deadline:
                time.sleep(0.02)
        self.temporary.cleanup()

    def start(self):
        child = subprocess.Popen([sys.executable, "-B", str(ROOT / "scripts" / "agent_config.py"), "mcp",
                                  "--data-dir", str(self.data_dir), "--home", str(self.home), "--host", "codex", "--project", str(self.project)],
                                 stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                 cwd=self.temporary.name)
        self.children.append(child)
        self.send(child, initialize())
        result = self.read(child)
        self.assertEqual(result["result"]["protocolVersion"], "2025-11-25")
        self.send(child, {"jsonrpc": "2.0", "method": "notifications/initialized"})
        return child

    def send(self, child, message):
        child.stdin.write(json.dumps(message).encode() + b"\n")
        child.stdin.flush()

    def read(self, child):
        with selectors.DefaultSelector() as selector:
            selector.register(child.stdout, selectors.EVENT_READ)
            self.assertTrue(selector.select(8), "MCP 未返回 JSON-RPC")
        line = child.stdout.readline()
        self.assertTrue(line, child.stderr.read().decode() if child.poll() is not None else "MCP 无响应")
        return json.loads(line)

    def call(self, child, name, arguments=None, request_id=3):
        self.send(child, {"jsonrpc": "2.0", "id": request_id, "method": "tools/call", "params": {
            "name": name, "arguments": arguments or {}}})
        return self.read(child)

    def test_real_stdio_three_tools_share_http_and_persistent_service(self):
        first, second = self.start(), self.start()
        self.assertFalse((self.data_dir / "console").exists(), "MCP 初始化不应绑定端口或写连接记录")
        self.send(first, {"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
        tools = self.read(first)["result"]["tools"]
        self.assertEqual(len(tools), 3)
        preferences = self.call(first, "get_model_preferences")["result"]
        self.assertFalse(preferences["isError"])
        self.assertEqual(preferences["structuredContent"]["host"], "codex")
        self.assertEqual(preferences["structuredContent"]["project"], str(self.project))
        resolved = self.call(second, "resolve_subagent", {"role": preferences["structuredContent"]["roles"][0]["role"]})["result"]
        self.assertFalse(resolved["isError"])
        self.assertFalse((self.data_dir / "console").exists(), "模型查询不应启动 HTTP")
        # 两个独立宿主进程并发请求控制台，必须复用同一个持久化数据目录和随机端口。
        for child in (first, second):
            self.send(child, {"jsonrpc": "2.0", "id": 9, "method": "tools/call", "params": {
                "name": "open_console", "arguments": {"open_browser": False}}})
        opened = [self.read(child)["result"] for child in (first, second)]
        for result in opened:
            self.assertFalse(result["isError"], result)
        first_url, second_url = [result["structuredContent"]["url"] for result in opened]
        self.assertEqual(first_url, second_url)
        record = read_connection(self.data_dir / "console")
        self.console_pid = record["pid"]
        self.assertNotIn(self.console_pid, [first.pid, second.pid])
        self.assertEqual(sorted(result["structuredContent"]["reused"] for result in opened), [False, True])
        self.assertFalse((self.project / ".agent-workflow").exists())
        self.assertFalse((self.project / ".awf").exists(), "查询和打开网页不能保存项目模型配置")
        for child in (first, second):
            child.stdin.close()
            child.stdin = None
            self.assertEqual(child.wait(timeout=5), 0)
            self.assertEqual(child.stdout.read(), b"", "stdout 只能包含已读取的协议响应")
            self.assertEqual(child.stderr.read(), b"")
        self.assertTrue((self.data_dir / "console" / "connection.json").exists(), "MCP 结束不应关闭其他会话复用的网页服务")

    def test_real_stdio_unknown_method_and_sigterm(self):
        child = self.start()
        self.send(child, {"jsonrpc": "2.0", "method": "notifications/unknown"})
        self.send(child, {"jsonrpc": "2.0", "id": 11, "method": "ping"})
        self.assertEqual(self.read(child), {"jsonrpc": "2.0", "id": 11, "result": {}})
        self.send(child, {"jsonrpc": "2.0", "id": 12, "method": "run_agent"})
        self.assertEqual(self.read(child)["error"]["code"], -32601)
        child.terminate()
        self.assertEqual(child.wait(timeout=5), -signal.SIGTERM)
        self.assertFalse((self.data_dir / "console").exists())


if __name__ == "__main__":
    unittest.main()
