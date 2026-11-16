"""真实环回HTTP正负控与可信CLI进程生命周期；复用来源测试同一fixture。"""
from __future__ import annotations

import http.client
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import threading
import unittest
from unittest import mock
from urllib.parse import urlsplit

from lib.documents import prototype_review as review
from lib.documents import prototype_feedback as feedback
from lib.documents.prototype_live import LiveSource, capture_live, register_live
from lib.documents.prototype_server import PrototypeServer
from lib.documents.prototype_service import open_service, service_status, stop_service
from lib.documents.prototype_file_entry import prepare_delivery, ENTRY
from tests.test_prototype_live import live_fixture, empty_draft
from tests.test_prototype_workspace import tree_snapshot


class PrototypeServerBindingTest(unittest.TestCase):
    def test_numeric_loopback_bind_has_no_dns_dependency(self):
        """服务只绑定数字环回地址，真实socket启动不应等待任何名称解析器。"""
        source = mock.Mock()
        source.current.return_value = ({}, {}, [])
        # 这里只替换与合同无关的DNS副作用；实际TCP bind和内核随机端口照常执行，
        # 无磁盘fixture/业务源/认证输出。旧HTTPServer会在此负控精确失败。
        with mock.patch("socket.getfqdn", side_effect=AssertionError("数字环回服务不应执行DNS解析")):
            server = PrototypeServer(source, {}, [])
        try:
            self.assertEqual("127.0.0.1", server.server_address[0])
            self.assertEqual("127.0.0.1", server.server_name)
            self.assertEqual(server.server_address[1], server.server_port)
            self.assertGreater(server.server_port, 0)
        finally: server.server_close()


class PrototypeServerTest(unittest.TestCase):
    def setUp(self):
        self.base, self.project, self.page, self.data = live_fixture()
        prepare_delivery(self.project, "project.yaml", [self.page], data_dir=self.data)
        self.context, _, _, navigation = capture_live(self.project, "project.yaml", "docs/plans/settings.md", "http-test", [self.page])
        register_live(self.project, self.context, data_dir=self.data)
        _, tools = review.capture_tool(format_version=5)
        self.server = PrototypeServer(LiveSource(self.project, self.context, data_dir=self.data), tools, navigation)
        self.thread = threading.Thread(target=self.server.run)
        self.thread.start()
        self.addCleanup(self.close)

    def close(self):
        self.server.stopping.set()
        self.thread.join(timeout=7)
        self.assertFalse(self.thread.is_alive())

    def request(self, method, path, value=None, headers=None, raw=None):
        client = http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=3)
        try:
            client.request(method, path, body=raw if raw is not None else review.json_bytes(value) if value is not None else None, headers=headers or {})
            response = client.getresponse()
            return response.status, dict(response.getheaders()), response.read()
        finally: client.close()

    def auth(self): return {"Origin": self.server.origin, "Authorization": "Bearer " + self.server.token, "Content-Type": "application/json"}

    def test_http_auth_cap_isolation_and_runtime_assembly_preserve_source(self):
        before = tree_snapshot(self.project)
        url = urlsplit(self.server.navigation[0]["url"])
        status, _, body = self.request("GET", "/health")
        self.assertEqual((200, {"status": "ready"}), (status, json.loads(body)))
        self.assertNotIn(self.server.token.encode(), body)
        _, cors_headers, _ = self.request("GET", url.path, headers={"Origin": "null"})
        self.assertEqual("null", cors_headers.get("Access-Control-Allow-Origin"))
        self.assertEqual("Origin", cors_headers.get("Vary"))
        self.assertNotIn("Access-Control-Allow-Credentials", cors_headers)
        _, foreign_headers, _ = self.request("GET", url.path, headers={"Origin": "http://evil.invalid"})
        self.assertNotIn("Access-Control-Allow-Origin", foreign_headers)
        _, control_headers, _ = self.request("GET", "/api/context", headers={**self.auth(), "Origin": "null"})
        self.assertNotIn("Access-Control-Allow-Origin", control_headers)
        self.assertEqual(403, self.request("GET", "/health", headers={"Host": "localhost:" + str(self.server.server_port)})[0])
        for headers in ({}, {**self.auth(), "Origin": "null"}, {**self.auth(), "Origin": "http://evil.invalid"}):
            self.assertEqual(403, self.request("GET", "/api/context", headers=headers)[0])
        status, _, body = self.request("GET", "/api/context?name=settings.html", headers=self.auth())
        self.assertEqual((200, self.page), (status, json.loads(body)["page"]))
        browser_get = {"Authorization": "Bearer " + self.server.token, "Sec-Fetch-Site": "same-origin"}
        self.assertEqual(200, self.request("GET", "/api/context", headers=browser_get)[0])
        self.assertEqual(403, self.request("GET", "/api/context", headers={**browser_get, "Sec-Fetch-Site": "cross-site"})[0])
        self.assertEqual(403, self.request("PUT", "/api/draft", {"revision": 0, "draft": None}, browser_get)[0])
        status, headers, body = self.request("GET", "/review/settings.html")
        self.assertEqual(200, status)
        self.assertIn(b'"schema_version":5', body)
        self.assertEqual(1, body.count(b'id="prototype-review-data"'))
        self.assertNotIn(self.server.token.encode(), body)
        self.assertIn("frame-ancestors 'none'", headers["Content-Security-Policy"])
        status, headers, body = self.request("GET", url.path)
        self.assertEqual(200, status)
        self.assertIn(b'data-prototype-review-bridge="5"', body)
        self.assertIn(b'data-prototype-review-source=', body)
        self.assertIn("sandbox allow-scripts", headers["Content-Security-Policy"])
        self.assertNotIn("allow-same-origin", headers["Content-Security-Policy"])
        self.assertNotIn(self.server.token.encode(), body)
        for path in ("/content/bad/" + self.page, "/assets/not-listed.js", url.path.replace("settings.html", "../../project.yaml"),
                     "/content/" + self.server.content_cap + "/project.yaml", "/content/" + self.server.content_cap + "/docs/plans/settings.md"):
            self.assertIn(self.request("GET", path)[0], (400, 404))
        self.assertEqual(403, self.request("POST", "/_service/" + self.server.management + "/stop", {}, self.auth())[0])
        self.assertEqual(403, self.request("GET", "/_service/" + "0" * 64 + "/status")[0])
        self.assertEqual(before, tree_snapshot(self.project))

    def test_http_draft_conflict_duplicate_fields_source_change_and_old_read(self):
        initial = json.loads(self.request("GET", "/api/draft", headers=self.auth())[2])
        self.assertEqual(400, self.request("PUT", "/api/draft", headers=self.auth(), raw=b'{"revision":0,"revision":0,"draft":null}')[0])
        self.assertEqual(400, self.request("PUT", "/api/draft", headers={**self.auth(), "Content-Length": "1048577"})[0])
        payload = {"revision": initial["revision"], "draft": empty_draft(self.context)}
        self.assertEqual(200, self.request("PUT", "/api/draft", payload, self.auth())[0])
        status, _, body = self.request("PUT", "/api/draft", payload, self.auth())
        self.assertEqual((409, "draft_conflict"), (status, json.loads(body)["error"]["code"]))
        # 两个真实HTTP线程竞争同一revision，只能一个成功；锁争用也须是409，不能伪装400。
        payload["revision"] += 1
        with ThreadPoolExecutor(max_workers=2) as pool:
            responses = list(pool.map(lambda _: self.request("PUT", "/api/draft", payload, self.auth()), range(2)))
        self.assertEqual([200, 409], sorted(response[0] for response in responses))
        payload["revision"] += 1
        original = (self.project / self.page).read_bytes()
        content_path = urlsplit(self.server.navigation[0]["url"]).path
        original_rendered = self.request("GET", content_path)[2]
        try:
            (self.project / self.page).write_bytes(original + b"\nchanged\n")
            status, _, body = self.request("GET", "/api/context", headers=self.auth())
            self.assertEqual((409, "source_changed"), (status, json.loads(body)["status"]))
            content_status, _, content_body = self.request("GET", content_path)
            self.assertEqual((200, original_rendered), (content_status, content_body))
            self.assertEqual(200, self.request("GET", "/api/draft", headers=self.auth())[0])
            status, _, body = self.request("PUT", "/api/draft", payload, self.auth())
            self.assertEqual((409, "source_changed"), (status, json.loads(body)["error"]["code"]))
        finally: (self.project / self.page).write_bytes(original)

    def test_idle_service_closes_its_owned_socket(self):
        self.server.idle_seconds = .01
        self.thread.join(timeout=2)
        self.assertFalse(self.thread.is_alive())
        with self.assertRaises(OSError): self.request("GET", "/health")

    def test_public_top_level_bootstrap_rejects_opaque_and_subresources(self):
        path = "/_entry-review/" + self.server.instance + "/" + self.context["review_id"] + "/settings.html"
        browser = {"Sec-Fetch-Dest": "document", "Sec-Fetch-Mode": "navigate", "Sec-Fetch-Site": "cross-site"}
        status, headers, body = self.request("GET", path, headers=browser)
        self.assertEqual(200, status)
        self.assertEqual(1, body.count(b'id="prototype-browser-connection"'))
        self.assertIn(self.server.token.encode(), body)
        self.assertEqual("same-origin", headers["Cross-Origin-Opener-Policy"])
        self.assertEqual("DENY", headers["X-Frame-Options"])
        for denied in ({}, {**browser, "Origin": "null"}, {**browser, "Sec-Fetch-Dest": "iframe"},
                       {**browser, "Sec-Fetch-Dest": "script"}, {**browser, "Sec-Fetch-Dest": "object"},
                       {**browser, "Sec-Fetch-Mode": "cors"}, {**browser, "Sec-Fetch-Dest": "empty"}):
            code, denied_headers, denied_body = self.request("GET", path, headers=denied)
            self.assertEqual(403, code)
            self.assertNotIn(self.server.token.encode(), denied_body)
            self.assertNotIn("Access-Control-Allow-Origin", denied_headers)
        for wrong in (path.replace(self.server.instance, "a" * 48), path.replace(self.context["review_id"], "a" * 64), path.replace("settings.html", "unknown.html")):
            self.assertEqual(404, self.request("GET", wrong, headers=browser)[0])
        content = self.request("GET", urlsplit(self.server.navigation[0]["url"]).path)[2]
        self.assertNotIn(ENTRY.encode(), content)


class PrototypeServiceLifecycleTest(unittest.TestCase):
    def test_cli_live_keeps_registered_revision_after_legacy_index_changes(self):
        """用公开CLI证明旧壳新增/改字后复用同实例，反馈5仍绑定原登记修订。"""
        base, project, page, data = live_fixture()
        prepare_delivery(project, "project.yaml", [page], data_dir=data)
        index = project / "docs/standards/prototype/index.html"
        original = index.read_bytes() if index.exists() else None
        request_id = "index-cli-test"
        command = [sys.executable, "-B", str(review.TOOL_ROOT / "lib/documents/prototype_feedback_cli.py")]
        args = ["--root", str(project), "--request-id", request_id, "--data-dir", str(data)]
        def open_registered():
            result = subprocess.run(command + ["open"] + args + ["--adapter", "project.yaml", "--plan", "docs/plans/settings.md", "--pages", page], text=True, capture_output=True, timeout=20)
            self.assertEqual(0, result.returncode, result.stderr + result.stdout)
            return json.loads(result.stdout)
        try:
            index.unlink(missing_ok=True)
            opened = open_registered()
            for label in ("Legacy label A", "Legacy label B"):
                index.write_text('<html><body><a href="settings.html">' + label + '</a></body></html>', encoding="utf-8")
                again = open_registered()
                self.assertTrue(again["reused"])
                self.assertEqual(opened["review_id"], again["review_id"])
                envelope = {"schema_version": 5, "review": {"request_id": request_id, "review_id": opened["review_id"]}, "anchors": [], "items": []}
                self.assertEqual("current", feedback.validate_feedback(project, "project.yaml", envelope, data_dir=data)["status"])
                url = urlsplit(again["review_url"])
                client = http.client.HTTPConnection(url.hostname, url.port, timeout=3)
                try:
                    client.request("GET", url.path, headers={"Sec-Fetch-Dest": "document", "Sec-Fetch-Mode": "navigate", "Sec-Fetch-Site": "none"})
                    response = client.getresponse()
                    self.assertEqual(200, response.status)
                    boot = re.search(rb'<script type="application/json" id="prototype-browser-connection">(.*?)</script>', response.read())
                    self.assertIsNotNone(boot)
                    token = json.loads(boot[1])["token"]
                    client.request("GET", "/api/context?name=settings.html", headers={"Origin": "http://" + url.netloc, "Authorization": "Bearer " + token})
                    response = client.getresponse()
                    self.assertEqual(200, response.status)
                    self.assertEqual("ready", json.loads(response.read())["status"])
                finally: client.close()
        finally:
            stop_service(project, request_id, data_dir=data)
            if original is None: index.unlink(missing_ok=True)
            else: index.write_bytes(original)

    def test_real_cli_process_open_reuse_status_stop_and_private_state(self):
        base, project, page, data = live_fixture()
        command = [sys.executable, "-B", str(review.TOOL_ROOT / "lib/documents/prototype_feedback_cli.py")]
        args = ["--root", str(project), "--request-id", "lifecycle-test", "--data-dir", str(data)]
        prepared = subprocess.run(command + ["prepare-delivery", "--root", str(project), "--adapter", "project.yaml",
            "--pages", page, "--data-dir", str(data)], text=True, capture_output=True, timeout=20)
        self.assertEqual(0, prepared.returncode, prepared.stderr + prepared.stdout)
        self.assertEqual("prepared", json.loads(prepared.stdout)["status"])
        before = tree_snapshot(project)
        def run(operation, *extra):
            result = subprocess.run(command + [operation] + args + list(extra), text=True, capture_output=True, timeout=20)
            self.assertEqual(0, result.returncode, result.stderr + result.stdout)
            return json.loads(result.stdout)
        try:
            opened = run("open", "--adapter", "project.yaml", "--plan", "docs/plans/settings.md", "--pages", page)
            again = run("open", "--adapter", "project.yaml", "--plan", "docs/plans/settings.md", "--pages", page)
            self.assertTrue(opened["review_url"] == again["review_url"], "重复打开未复用同一实例链接")
            self.assertTrue(again["reused"])
            self.assertEqual("file", urlsplit(opened["delivery_url"]).scheme)
            self.assertEqual([opened["delivery_url"]], opened["delivery_urls"])
            self.assertFalse(urlsplit(opened["review_url"]).fragment)
            self.assertFalse(urlsplit(opened["http_delivery_url"]).fragment)
            for link in (opened["delivery_url"], opened["review_url"], opened["http_delivery_url"]):
                self.assertNotIn("token", link)
            state = run("status")
            self.assertEqual("ready", state["status"])
            self.assertNotIn("token", json.dumps(state))
            self.assertEqual("stopped", run("stop")["status"])
            self.assertEqual("stopped", run("status")["status"])
            self.assertEqual(before, tree_snapshot(project))
            self.assertFalse(any(path.suffix == ".html" for path in (data / review.project_id(project) / "lifecycle-test" / "live").rglob("*")))
        finally: stop_service(project, "lifecycle-test", data_dir=data)


if __name__ == "__main__": unittest.main()
