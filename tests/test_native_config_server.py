"""真实回环 HTTP 与固定脚本子进程验证，不访问用户设置或业务项目。"""

from __future__ import annotations

import http.client
import json
import os
from pathlib import Path
import selectors
import signal
import socket
import stat
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock
from urllib.parse import parse_qs, urlsplit

from native_config.server import (ConsoleServer, MAX_BODY, ROOT,
                                   read_connection, service_version)


class FakeConflict(ValueError):
    code = "conflict"


class FakePartialFailure(ValueError):
    code = "partial_failure"

    def __init__(self, result=None, **flags):
        super().__init__("不能泄露的原生配置正文")
        self.result = result if result is not None else {}
        self.__dict__.update(flags)


class FakeService:
    """最小业务夹具只记录调用，传输测试不依赖模型目录或真实宿主。"""
    def __init__(self):
        self.calls = []

    def context(self, host, scope="global", project=None):
        self.calls.append(("context", host, scope, project))
        if project == "/private/secret":
            raise RuntimeError("不可泄露的路径和配置")
        return {"host": host, "scope": scope, "project": project, "revision": "a" * 64,
                "roles": [], "capabilities": {}, "runtime_verified": False}

    def catalog(self, host, project=None):
        self.calls.append(("catalog", host, project))
        return {"models": [], "status": "unavailable"}

    def preview(self, request):
        self.calls.append(("preview", request))
        if request.get("revision") == "stale":
            raise FakeConflict("机密文件路径")
        return {"preview_id": "plan-1", "changes": [], "warnings": [], "effect": {"runtime_verified": False}}

    def apply(self, preview_id):
        self.calls.append(("apply", preview_id))
        if preview_id == "bad":
            raise ValueError("机密文件路径")
        if preview_id == "partial":
            return {"saved": False, "partial_failure": True, "published": True,
                    "results": [{"role": "agent_" + "a" * 64, "status": "rollback_conflict"}],
                    "recovery": [{"role": "agent_" + "a" * 64, "target": "/tmp/native-agent.toml",
                                  "backup": "/tmp/.native-config-test.backup", "sha256": "a" * 64}],
                    "cleanup_pending": ["/tmp/.native-config-test.new"],
                    "effect": {"saved": False, "runtime_verified": False}}
        return {"saved": True, "effect": {"runtime_verified": False}}


class ConsoleHttpTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        web = Path(self.temporary.name)
        for name in ("index.html", "console.js", "console.css"):
            (web / name).write_text("test " + name, encoding="utf-8")
        self.service = FakeService()
        self.server = ConsoleServer(self.service, version="0.1.0-alpha.1", web_root=web)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=3)
        self.temporary.cleanup()

    def request(self, method, path, data=None, *, auth=True, origin=True, extra=None):
        headers = {}
        if auth:
            headers["Authorization"] = "Bearer " + self.server.token
        if origin:
            headers["Origin"] = self.server.origin
        if data is not None:
            data = json.dumps(data).encode("utf-8") if not isinstance(data, bytes) else data
            headers["Content-Type"] = "application/json"
        headers.update(extra or {})
        connection = http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=3)
        try:
            connection.request(method, path, body=data, headers=headers)
            response = connection.getresponse()
            return response.status, dict(response.getheaders()), response.read()
        finally:
            connection.close()

    def test_static_and_api_share_secure_headers_without_cors(self):
        status, headers, body = self.request("GET", "/", auth=False, origin=False)
        self.assertEqual(status, 200)
        self.assertIn(b"index.html", body)
        self.assertIn("default-src 'none'", headers["Content-Security-Policy"])
        self.assertNotIn("https:", headers["Content-Security-Policy"])
        self.assertEqual(headers["Cache-Control"], "no-store")
        self.assertNotIn("Access-Control-Allow-Origin", headers)
        status, _, raw = self.request("GET", "/api/context?host=codex&scope=project&project=%2Ftmp%2Fexample")
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(raw)["project"], "/tmp/example")
        self.assertEqual(self.service.calls[-1], ("context", "codex", "project", "/tmp/example"))
        self.assertEqual(self.request("GET", "/api/catalog?host=codex")[0], 200)
        self.assertEqual(self.service.calls[-1][0], "catalog")

    def test_auth_host_origin_and_method_negative_controls(self):
        self.assertEqual(self.request("GET", "/api/context?host=codex", auth=False)[0], 401)
        self.assertEqual(self.request("GET", "/api/context?host=codex", extra={"Authorization": "Bearer wrong"})[0], 401)
        self.assertEqual(self.request("GET", "/api/context?host=codex", extra={"Authorization": "é"})[0], 401)
        for host in ("evil.example", "localhost:" + str(self.server.server_port), "127.0.0.1", "127.0.0.1.evil"):
            self.assertEqual(self.request("GET", "/", extra={"Host": host})[0], 403)
        for origin in ("null", "https://evil.example", "http://localhost:" + str(self.server.server_port)):
            self.assertEqual(self.request("POST", "/api/apply", {"preview_id": "p"}, extra={"Origin": origin})[0], 403)
        self.assertEqual(self.request("POST", "/api/apply", {"preview_id": "p"}, origin=False)[0], 403)
        self.assertEqual(self.request("OPTIONS", "/api/apply")[0], 405)
        self.assertEqual(self.request("PATCH", "/api/apply")[0], 405)
        self.assertEqual(self.service.calls, [])

    def test_traversal_and_unbounded_inputs_are_rejected(self):
        for path in ("/../product/PLUGIN_VERSION", "/%2e%2e/product/PLUGIN_VERSION", "/foo\\bar", "/%00", "/console.js/../server.py"):
            self.assertEqual(self.request("GET", path)[0], 400, path)
        self.assertEqual(self.request("GET", "/server.py")[0], 404)
        self.assertEqual(self.request("GET", "/api/context?host=codex&host=claude")[0], 400)
        self.assertEqual(self.request("GET", "/api/context?host=codex&project=relative")[0], 400)
        self.assertEqual(self.request("GET", "/api/context?host=codex&home=%2Ftmp")[0], 400)
        self.assertEqual(self.request("GET", "/api/context?host=codex&project=%2Ftmp%2F..%2Fsecret")[0], 400)
        self.assertEqual(self.request("POST", "/api/apply", b"x" * (MAX_BODY + 1))[0], 413)
        self.assertEqual(self.request("POST", "/api/apply", b'{"preview_id":"p","preview_id":"q"}')[0], 400)
        self.assertEqual(self.request("POST", "/api/apply", b"[" * 2000)[0], 400)
        self.assertEqual(self.request("POST", "/api/apply", b"{}", extra={"Content-Type": "text/plain"})[0], 415)
        self.assertEqual(self.service.calls, [])

    def test_preview_apply_errors_and_health_are_sanitized(self):
        preview = {"host": "codex", "scope": "global", "revision": "a" * 64, "edits": {}}
        self.assertEqual(self.request("POST", "/api/preview", preview)[0], 200)
        status, _, raw = self.request("POST", "/api/apply", {"preview_id": "plan-1"})
        self.assertEqual(status, 200)
        self.assertFalse(json.loads(raw)["effect"]["runtime_verified"])
        for path, data, expected in (("/api/preview", {**preview, "revision": "stale"}, 409),
                                     ("/api/apply", {"preview_id": "bad"}, 400),
                                     ("/api/context?host=codex&project=%2Fprivate%2Fsecret", None, 500)):
            status, _, raw = self.request("POST" if data else "GET", path, data)
            self.assertEqual(status, expected)
            self.assertNotIn("机密".encode(), raw)
            self.assertNotIn(b"secret", raw)
        status, _, raw = self.request("GET", "/api/health")
        self.assertEqual(status, 200)
        health = json.loads(raw)
        self.assertEqual(set(health), {"instance_id", "service_version", "protocol_version", "configuration_identity"})
        self.assertNotIn(self.server.token.encode(), raw)

    def test_real_activation_http_preview_and_apply_use_same_authorized_boundary(self):
        from native_config import ModelService
        root = Path(self.temporary.name).resolve()
        home = root / "isolated-home"
        config = home / ".codex/config.toml"
        config.parent.mkdir(parents=True)
        config.write_text('[marketplaces."agent-workflow-alpha"]\nsource_type="git"\n'
                          'source="https://github.com/Geoege-xll/agent-workflow.git"\nref="plugins-codex-alpha"\n'
                          '[plugins."agent-workflow@agent-workflow-alpha"]\nenabled=true\n')
        self.server.service = ModelService(root / "data", home)
        before = config.read_bytes()
        status, _, raw = self.request("GET", "/api/context?host=codex")
        self.assertEqual(status, 200)
        context = json.loads(raw)
        self.assertEqual(context["workflow_activation"]["state"], "enabled")
        request = {"host": "codex", "revision": context["revision"], "workflow_activation": {"state": "disabled"}}
        self.assertEqual(self.request("POST", "/api/preview", request, auth=False)[0], 401)
        self.assertEqual(self.request("POST", "/api/preview", {**request, "edits": {}})[0], 400)
        self.assertEqual(self.request("POST", "/api/preview", {**request, "source_path": "/tmp/injection"})[0], 400)
        status, _, raw = self.request("POST", "/api/preview", request)
        self.assertEqual(status, 200)
        preview = json.loads(raw)
        self.assertEqual(preview["changes"][0]["kind"], "workflow_activation")
        self.assertEqual(config.read_bytes(), before)
        status, _, raw = self.request("POST", "/api/apply", {"preview_id": preview["preview_id"]})
        self.assertEqual(status, 200)
        result = json.loads(raw)
        self.assertTrue(result["saved"])
        self.assertEqual(result["context"]["workflow_activation"]["state"], "disabled")
        self.assertFalse(result["effect"]["runtime_verified"])
        self.assertEqual(self.request("POST", "/api/apply", {"preview_id": preview["preview_id"]})[0], 409)

    def test_partial_save_preserves_every_recovery_field(self):
        status, _, raw = self.request("POST", "/api/apply", {"preview_id": "partial"})
        self.assertEqual(status, 200)
        result = json.loads(raw)
        self.assertTrue(result["partial_failure"])
        self.assertEqual(result["results"][0]["status"], "rollback_conflict")
        self.assertEqual(result["recovery"][0]["backup"], "/tmp/.native-config-test.backup")
        self.assertEqual(result["cleanup_pending"], ["/tmp/.native-config-test.new"])
        # 超大清单可省略，但不能把部分发布的结果换成丢失恢复路径的容量错误。
        with mock.patch.object(self.service, "apply", return_value={**result, "context": "x" * 4096}), \
                mock.patch("native_config.server.MAX_RESPONSE", 2048):
            status, _, raw = self.request("POST", "/api/apply", {"preview_id": "partial"})
        compact = json.loads(raw)
        self.assertEqual(status, 200)
        self.assertTrue(compact["context_unavailable"])
        self.assertEqual(compact["recovery"], result["recovery"])
        self.assertEqual(compact["cleanup_pending"], result["cleanup_pending"])

    def test_http_409_preserves_core_namespace_flags_and_full_recovery_receipt(self):
        receipt = {"results": [{"role": "agent_" + "a" * 64, "status": "rollback_conflict"}],
                   "recovery": [{"role": "agent_" + "a" * 64, "target": "/tmp/native-agent.toml",
                                 "backup": "/tmp/native-agent.backup", "sha256": "a" * 64}],
                   "cleanup_pending": ["/tmp/native-agent.new"],
                   "effect": {"saved": False, "pending_reload": True, "runtime_verified": False},
                   "published": False}
        # 假业务错误走真实回环 POST；False 也是已观察事实，不能因真假判断被遗漏。
        for touched, gap in ((True, True), (True, False), (False, False)):
            supplied = {**receipt, "namespace_touched": touched, "temporary_visibility_gap": gap}
            with self.subTest(namespace_touched=touched, temporary_visibility_gap=gap), \
                    mock.patch.object(self.service, "apply", side_effect=FakePartialFailure(supplied)):
                status, _, raw = self.request("POST", "/api/apply", {"preview_id": "failed-plan"})
            result = json.loads(raw)
            self.assertEqual(status, 409)
            self.assertEqual(result["error"]["code"], "partial_failure")
            self.assertFalse(result["saved"])
            self.assertTrue(result["partial_failure"])
            for key, value in supplied.items():
                self.assertEqual(result[key], value)
            self.assertNotIn("不能泄露".encode(), raw)
        # 现有投影也支持错误对象属性；命名空间字段遵守同一来源优先级与 bool 合同。
        with mock.patch.object(self.service, "apply", side_effect=FakePartialFailure(
                receipt, namespace_touched=False, temporary_visibility_gap=True)):
            status, _, raw = self.request("POST", "/api/apply", {"preview_id": "attribute-plan"})
        self.assertEqual(status, 409)
        self.assertIs(json.loads(raw)["namespace_touched"], False)
        self.assertIs(json.loads(raw)["temporary_visibility_gap"], True)

    def test_errors_do_not_invent_or_coerce_namespace_flags(self):
        conflict = FakeConflict("冲突正文不可泄露")
        conflict.namespace_touched = conflict.temporary_visibility_gap = True
        for error, expected in ((ValueError("普通错误"), 400), (conflict, 409),
                                (FakePartialFailure({"published": True}), 409),
                                (FakePartialFailure({"namespace_touched": "true", "temporary_visibility_gap": 1}), 409)):
            with self.subTest(error=type(error).__name__), mock.patch.object(self.service, "apply", side_effect=error):
                status, _, raw = self.request("POST", "/api/apply", {"preview_id": "unobserved-plan"})
            self.assertEqual(status, expected)
            result = json.loads(raw)
            self.assertNotIn("namespace_touched", result)
            self.assertNotIn("temporary_visibility_gap", result)


class ConsoleStartupTest(unittest.TestCase):
    def test_literal_loopback_bind_does_not_require_reverse_dns(self):
        """真实绑定固定回环地址时，不应为不使用的主机名触发系统反向解析。"""
        with mock.patch("native_config.server.socket.gethostbyaddr", side_effect=AssertionError("回环绑定不应依赖反向DNS")) as resolver:
            server = ConsoleServer(object(), version="0.1.0-test")
        try:
            self.assertEqual(server.server_name, "127.0.0.1")
            self.assertEqual(server.server_address, ("127.0.0.1", server.server_port))
            self.assertGreater(server.server_port, 0)
            resolver.assert_not_called()
        finally:
            server.server_close()


class ConsoleProcessTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.data_dir = Path(self.temporary.name).resolve() / "user-data"
        self.project = Path(self.temporary.name).resolve() / "unregistered-project"
        self.project.mkdir()
        self.home = Path(self.temporary.name).resolve() / "home"
        self.home.mkdir()
        self.native_file = self.project / ".codex" / "agents" / "backend.toml"
        self.native_file.parent.mkdir(parents=True)
        self.native_before = (b'name = "backend"\ndescription = "test native agent"\n'
                              b'model = "gpt-old"\ndeveloper_instructions = "Keep native body"\n')
        self.native_file.write_bytes(self.native_before)
        self.children = []
        self.owned_pids = set()

    def tearDown(self):
        record_path = self.data_dir / "console" / "connection.json"
        if record_path.exists():
            try:
                record = json.loads(record_path.read_text())
                if record["pid"] in self.owned_pids:
                    os.kill(record["pid"], signal.SIGTERM)
            except (OSError, ValueError, KeyError):
                pass
        for child in self.children:
            if child.poll() is None:
                child.terminate()
            child.communicate(timeout=5)
        deadline = time.monotonic() + 3
        while record_path.exists() and time.monotonic() < deadline:
            time.sleep(0.02)
        self.temporary.cleanup()

    def command(self, mode, *extra):
        return [sys.executable, "-B", str(ROOT / "scripts" / "agent_config.py"), mode,
                "--data-dir", str(self.data_dir), "--home", str(self.home), "--host", "codex", "--project", str(self.project), *extra]

    def start_serve(self, *extra, env=None, bootstrap=None):
        command = self.command("serve", *extra)
        if bootstrap is not None:
            command = [sys.executable, "-B", "-c", bootstrap, *command[3:]]
        child = subprocess.Popen(command, stdin=subprocess.DEVNULL, env=env,
                                 stdout=subprocess.PIPE, stderr=subprocess.PIPE, cwd=self.temporary.name)
        self.children.append(child)
        self.owned_pids.add(child.pid)
        with selectors.DefaultSelector() as selector:
            selector.register(child.stdout, selectors.EVENT_READ)
            self.assertTrue(selector.select(5), "服务没有输出启动信息")
        line = child.stdout.readline()
        self.assertTrue(line, child.stderr.read().decode() if child.poll() is not None else "无启动信息")
        return child, json.loads(line)

    def test_real_startup_and_health_handshake_ignore_blocked_reverse_dns(self):
        """仅阻塞测试子进程的系统反向解析，原五秒启动及认证健康握手仍须完成。"""
        marker = Path(self.temporary.name).resolve() / "reverse-dns-stage.json"
        bootstrap = ("import json,socket,sys,time,traceback\nfrom pathlib import Path\n" +
                     f"sys.path.insert(0,{str(ROOT)!r})\n" +
                     "def blocked_reverse_lookup(address):\n" +
                     f" Path({str(marker)!r}).write_text(json.dumps({{'phase':'reverse_lookup','address':address,'stack':traceback.format_stack()}}))\n" +
                     " time.sleep(30)\n" +
                     " return ('localhost',[],[address])\n" +
                     "socket.gethostbyaddr=blocked_reverse_lookup\n" +
                     "from native_config.cli import main\nraise SystemExit(main(sys.argv[1:]))\n")
        try:
            child, started = self.start_serve("--idle-timeout", "0", bootstrap=bootstrap)
        except AssertionError:
            if marker.exists():
                stage = json.loads(marker.read_text())
                self.fail("启动停在受控阶段 " + stage["phase"] + "：" + "".join(stage["stack"]))
            raise
        self.assertFalse(marker.exists(), "固定回环服务不能触发系统反向解析")
        record = read_connection(self.data_dir / "console")
        parsed = urlsplit(started["url"])
        connection = http.client.HTTPConnection("127.0.0.1", parsed.port, timeout=3)
        try:
            connection.request("GET", "/api/health", headers={"Authorization": "Bearer " + parse_qs(parsed.fragment)["token"][0]})
            response = connection.getresponse()
            self.assertEqual(response.status, 200)
            health = json.loads(response.read())
            self.assertEqual(health["instance_id"], record["instance_id"])
            self.assertEqual(health["configuration_identity"], record["configuration_identity"])
        finally:
            connection.close()
        child.terminate()
        self.assertEqual(child.wait(timeout=5), 0)
        self.assertFalse((self.data_dir / "console/connection.json").exists())

    def test_sigterm_waits_for_active_catalog_and_reaps_owned_client(self):
        """真实 fake app-server 超过关闭时刻，退出必须等查询 finally 回收该进程组。"""
        root = Path(self.temporary.name).resolve()
        binaries = root / "bin"
        binaries.mkdir()
        marker = root / "catalog-active.json"
        fake = binaries / "codex"
        fake.write_text("#!" + sys.executable + "\n" +
                        "import json,os,sys,time\n" +
                        "for line in sys.stdin:\n" +
                        " request=json.loads(line)\n" +
                        " if request.get('method')=='initialize':\n" +
                        "  print(json.dumps({'id':request['id'],'result':{}}),flush=True)\n" +
                        " elif request.get('method')=='model/list':\n" +
                        "  open(os.environ['CATALOG_ACTIVE_MARKER'],'w').write(json.dumps({'pid':os.getpid()}))\n" +
                        "  time.sleep(30)\n", encoding="utf-8")
        fake.chmod(0o700)
        child, started = self.start_serve("--idle-timeout", "0", env={**os.environ, "PATH": str(binaries),
                                               "CATALOG_ACTIVE_MARKER": str(marker)})
        parsed = urlsplit(started["url"])
        results = []

        def catalog():
            connection = http.client.HTTPConnection("127.0.0.1", parsed.port, timeout=12)
            try:
                connection.request("GET", "/api/catalog?host=codex", headers={
                    "Authorization": "Bearer " + parse_qs(parsed.fragment)["token"][0]})
                response = connection.getresponse()
                results.append((response.status, json.loads(response.read())))
            except Exception as exc:
                results.append(type(exc).__name__)
            finally:
                connection.close()

        request_thread = threading.Thread(target=catalog)
        request_thread.start()
        fake_pid = None
        try:
            deadline = time.monotonic() + 5
            while not marker.exists() and time.monotonic() < deadline:
                time.sleep(0.02)
            self.assertTrue(marker.exists(), "fake目录查询没有进入活动状态")
            fake_pid = json.loads(marker.read_text())["pid"]
            child.terminate()
            self.assertEqual(child.wait(timeout=10), 0)
            request_thread.join(timeout=2)
            self.assertFalse(request_thread.is_alive())
            self.assertEqual(len(results), 1)
            self.assertIsInstance(results[0], tuple, results)
            self.assertEqual(results[0][0], 200)
            with self.assertRaises(ProcessLookupError):
                os.kill(fake_pid, 0)
            self.assertFalse((self.data_dir / "console/connection.json").exists())
        finally:
            if child.poll() is None:
                child.terminate()
                child.wait(timeout=10)
            if fake_pid is not None:
                try:
                    os.killpg(fake_pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
            request_thread.join(timeout=2)

    def test_sigterm_waits_for_active_apply_before_record_and_lock_cleanup(self):
        """仅在测试子进程暂停核心写入入口，证明退出不会截断已接受的同一服务端计划。"""
        root = Path(self.temporary.name).resolve()
        marker, release, settled = (root / name for name in ("apply-active", "apply-release", "apply-settled"))
        bootstrap = ("import sys,time\nfrom pathlib import Path\n" +
                     f"sys.path.insert(0,{str(ROOT)!r})\n" +
                     "from native_config import storage\nfrom native_config.cli import main\n" +
                     "original=storage.write_batch\n" +
                     "def paused(*args,**kwargs):\n" +
                     f" Path({str(marker)!r}).write_text('active')\n" +
                     " deadline=time.monotonic()+8\n" +
                     f" while not Path({str(release)!r}).exists() and time.monotonic()<deadline: time.sleep(.02)\n" +
                     " try: return original(*args,**kwargs)\n" +
                     f" finally: Path({str(settled)!r}).write_text('settled')\n" +
                     "storage.write_batch=paused\nraise SystemExit(main(sys.argv[1:]))\n")
        child, started = self.start_serve("--idle-timeout", "0", bootstrap=bootstrap)
        parsed = urlsplit(started["url"])
        headers = {"Authorization": "Bearer " + parse_qs(parsed.fragment)["token"][0],
                   "Origin": f"http://127.0.0.1:{parsed.port}", "Content-Type": "application/json"}

        def api(method, path, data=None):
            connection = http.client.HTTPConnection("127.0.0.1", parsed.port, timeout=12)
            try:
                connection.request(method, path, body=json.dumps(data) if data else None, headers=headers)
                response = connection.getresponse()
                result = json.loads(response.read())
                self.assertEqual(response.status, 200, result)
                return result
            finally:
                connection.close()

        context = api("GET", "/api/context?host=codex&scope=project&project=" + str(self.project))
        plan = api("POST", "/api/preview", {"host": "codex", "scope": "project", "project": str(self.project),
                   "revision": context["revision"], "edits": {context["roles"][0]["role"]: {"model": "saved-after-signal"}}})
        result = []

        def apply():
            try:
                result.append(api("POST", "/api/apply", {"preview_id": plan["preview_id"]}))
            except Exception as exc:
                result.append(type(exc).__name__)

        request_thread = threading.Thread(target=apply)
        request_thread.start()
        try:
            deadline = time.monotonic() + 5
            while not marker.exists() and time.monotonic() < deadline:
                time.sleep(0.02)
            self.assertTrue(marker.exists(), "apply没有进入活动写入")
            child.terminate()
            time.sleep(0.35)
            self.assertIsNone(child.poll(), "写入结算前服务不能退出")
            self.assertTrue((self.data_dir / "console/connection.json").exists())
            competing = subprocess.run(self.command("serve", "--idle-timeout", "0"), capture_output=True, timeout=3)
            self.assertNotEqual(competing.returncode, 0, "活动写入结算前服务锁必须仍归原实例")
            self.assertFalse(settled.exists())
            self.assertEqual(self.native_file.read_bytes(), self.native_before)
            release.write_text("release")
            self.assertEqual(child.wait(timeout=5), 0)
            request_thread.join(timeout=2)
            self.assertTrue(settled.exists())
            self.assertEqual(len(result), 1)
            self.assertIsInstance(result[0], dict, result)
            self.assertTrue(result[0]["saved"])
            self.assertIn(b'saved-after-signal', self.native_file.read_bytes())
            self.assertFalse((self.data_dir / "console/connection.json").exists())
        finally:
            release.write_text("release")
            request_thread.join(timeout=5)

    def test_sigterm_cancels_slow_body_despite_keepalive_and_dripped_bytes(self):
        """持续滴入正文不能靠重置单次 socket timeout 阻止服务关闭。"""
        child, started = self.start_serve("--idle-timeout", "0")
        parsed = urlsplit(started["url"])
        slow = socket.create_connection(("127.0.0.1", parsed.port), timeout=2)
        finished = threading.Event()
        body = (f"POST /api/apply HTTP/1.1\r\nHost: 127.0.0.1:{parsed.port}\r\n"
                f"Authorization: Bearer {parse_qs(parsed.fragment)['token'][0]}\r\n"
                f"Origin: http://127.0.0.1:{parsed.port}\r\nContent-Type: application/json\r\n"
                "Content-Length: 1000\r\nConnection: keep-alive\r\n\r\n{")
        slow.sendall(body.encode())

        def drip():
            while not finished.wait(0.05):
                try:
                    slow.sendall(b" ")
                except OSError:
                    break

        writer = threading.Thread(target=drip)
        writer.start()
        try:
            time.sleep(0.15)
            child.terminate()
            self.assertEqual(child.wait(timeout=2), 0)
            self.assertFalse((self.data_dir / "console/connection.json").exists())
            self.assertEqual(self.native_file.read_bytes(), self.native_before)
        finally:
            finished.set()
            slow.close()
            writer.join(timeout=2)

    def test_script_real_service_reuse_save_and_sigterm_cleanup(self):
        child, started = self.start_serve("--idle-timeout", "0")
        record = read_connection(self.data_dir / "console")
        self.assertEqual(stat.S_IMODE((self.data_dir / "console").stat().st_mode), 0o700)
        self.assertEqual(stat.S_IMODE((self.data_dir / "console" / "connection.json").stat().st_mode), 0o600)
        results = [subprocess.run(self.command("console", "--no-browser"), capture_output=True,
                                  timeout=8, cwd=self.temporary.name) for _ in range(2)]
        for result in results:
            self.assertEqual(result.returncode, 0, result.stderr.decode())
            self.assertTrue(json.loads(result.stdout)["reused"])
            self.assertEqual(json.loads(result.stdout)["url"], started["url"])
        self.assertEqual(read_connection(self.data_dir / "console")["pid"], record["pid"])
        other_home = Path(self.temporary.name).resolve() / "other-home"
        other_home.mkdir()
        mismatched = subprocess.run([*self.command("console", "--no-browser"), "--home", str(other_home)],
                                    capture_output=True, timeout=5)
        self.assertNotEqual(mismatched.returncode, 0, "不得复用其他home的配置服务")
        self.assertEqual(read_connection(self.data_dir / "console")["instance_id"], record["instance_id"])
        self.assertIsNone(child.poll(), "拒绝不匹配配置根不能终止原服务")
        parsed = urlsplit(started["url"])
        token = parse_qs(parsed.fragment)["token"][0]
        connection = http.client.HTTPConnection(parsed.hostname, parsed.port, timeout=3)
        headers = {"Authorization": "Bearer " + token, "Origin": f"http://127.0.0.1:{parsed.port}",
                   "Content-Type": "application/json"}

        def api(method, path, data=None):
            connection.request(method, path, body=json.dumps(data) if data else None, headers=headers)
            response = connection.getresponse()
            body = response.read()
            self.assertEqual(response.status, 200, body)
            return json.loads(body)

        try:
            context = api("GET", "/api/context?host=codex&scope=project&project=" + str(self.project))
            preview = api("POST", "/api/preview", {"host": "codex", "scope": "project", "project": str(self.project),
                         "revision": context["revision"], "edits": {context["roles"][0]["role"]: {"model": "gpt-6.1"}}})
            self.assertEqual(self.native_file.read_bytes(), self.native_before)
            applied = api("POST", "/api/apply", {"preview_id": preview["preview_id"]})
            self.assertFalse(applied["effect"]["runtime_verified"])
            self.assertIn(b'model = "gpt-6.1"', self.native_file.read_bytes())
            self.assertIn(b'Keep native body', self.native_file.read_bytes())
            self.assertFalse((self.project / ".awf").exists())
            self.assertFalse((self.project / ".agent-workflow").exists())
        finally:
            connection.close()
        child.terminate()
        self.assertEqual(child.wait(timeout=5), 0)
        self.assertFalse((self.data_dir / "console" / "connection.json").exists())

    def test_idle_exit_and_incompatible_or_bad_records_are_not_trusted(self):
        child, _ = self.start_serve("--idle-timeout", "1")
        self.assertEqual(child.wait(timeout=5), 0)
        directory = self.data_dir / "console"
        self.assertFalse((directory / "connection.json").exists())
        # 不兼容记录即使 PID 指向当前测试进程也不得杀它或覆盖记录。
        record = {"port": 12345, "token": "x" * 43, "pid": os.getpid(), "instance_id": "test",
                  "protocol_version": 999, "service_version": service_version()}
        target = directory / "connection.json"
        target.write_text(json.dumps(record), encoding="utf-8")
        target.chmod(0o600)
        result = subprocess.run(self.command("console", "--no-browser"), capture_output=True, timeout=5)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(json.loads(target.read_text()), record)
        target.write_text("{bad", encoding="utf-8")
        result = subprocess.run(self.command("console", "--no-browser"), capture_output=True, timeout=5)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(target.read_text(), "{bad")
        target.unlink()
        # 连接记录被替换为 FIFO 时也必须立即拒绝，不能在打开记录时无限等待读端。
        os.mkfifo(target, 0o600)
        with self.assertRaises(ValueError):
            read_connection(directory)
        target.unlink()

    def test_shutdown_preserves_replaced_connection_record(self):
        child, _ = self.start_serve("--idle-timeout", "0")
        directory = self.data_dir / "console"
        record = read_connection(directory)
        successor = {**record, "instance_id": "successor-instance"}
        target = directory / "connection.json"
        target.write_text(json.dumps(successor), encoding="utf-8")
        child.terminate()
        self.assertEqual(child.wait(timeout=5), 0)
        self.assertEqual(json.loads(target.read_text()), successor)
        target.unlink()


if __name__ == "__main__":
    unittest.main()
