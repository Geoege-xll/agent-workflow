"""真实独立发行元数据：摘要从 ZIP 计算，published 必须核对下载字节。"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import socket
import sys
import tempfile
import threading
import time
import unittest
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
from product.command_identity import load_identity
from product.release_channels import compare_versions, validate_channel, version_channel


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


distribution = load("config_distribution_test", ROOT / "packaging/build_config_distribution.py")
builder = load("config_distribution_builder_test", ROOT / "packaging/build_agent_config.py")


class ConfigDistributionTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.base = Path(self.temporary.name).resolve()
        self.report = builder.build(ROOT, self.base)
        self.artifact = Path(self.report["artifact"])

    def tearDown(self):
        self.temporary.cleanup()

    def test_unpublished_uses_actual_zip_sha_and_has_no_download_url(self):
        report = distribution.assemble(self.artifact)
        self.assertEqual(report["release_status"], "unpublished")
        # 真实独立包必须跟随唯一版本源，不能让旧发行号把正确的新版本构建误判
        # 为失败；渠道仍由现有严格合同推导，不从待验证的 report 自证期望值。
        version = (ROOT / "native_config/VERSION").read_text(encoding="ascii").strip()
        self.assertEqual((report["version"], report["channel"]), (version, version_channel(version)))
        self.assertEqual(report["artifact"]["url"], "")
        self.assertEqual(report["artifact"]["sha256"], hashlib.sha256(self.artifact.read_bytes()).hexdigest())
        self.assertEqual((report["cli_protocol"], report["service_protocol"]), (1, 2))

    def test_published_descriptor_requires_verified_download_from_reviewed_repo(self):
        url = "https://github.com/Geoege-xll/agent-workflow/releases/download/native-v" + self.report["version"] + "/" + self.artifact.name
        calls = []
        def fetch(data, destination):
            calls.append(data["artifact"]["url"])
            shutil.copyfile(self.artifact, destination)
        report = distribution.assemble(self.artifact, url=url, downloader=fetch)
        self.assertEqual(report["release_status"], "published")
        self.assertEqual(calls, [url])
        def tamper(data, destination):
            destination.write_bytes(b"not the release asset")
        with self.assertRaises(distribution.store.ComponentError):
            distribution.assemble(self.artifact, url=url, downloader=tamper)

    def test_arbitrary_mirror_repo_asset_name_and_insecure_url_are_rejected(self):
        for url in ("http://github.com/Geoege-xll/agent-workflow/releases/download/native-v1/" + self.artifact.name,
                    "https://github.com/attacker/repo/releases/download/native-v1/" + self.artifact.name,
                    "https://example.com/" + self.artifact.name,
                    "https://github.com/Geoege-xll/agent-workflow/releases/download/native-v1/wrong.zip"):
            with self.subTest(url=url), self.assertRaises(distribution.store.ComponentError):
                distribution.assemble(self.artifact, url=url)

    def test_unique_release_contract_strictly_matches_versions_channels_and_order(self):
        self.assertEqual("stable", version_channel("3.0.1"))
        self.assertEqual("alpha", version_channel("3.0.0-alpha.9"))
        for value in ("03.0.1", "3.00.1", "3.0.01", "3.0.1-alpha.0", "3.0.1-alpha.01",
                      "3.0.1-beta.1", "3.0.1+build.1", "3.0.1\n", None, 301):
            with self.subTest(value=value), self.assertRaises(ValueError):
                version_channel(value)
        for version, channel in (("3.0.1", "alpha"), ("3.0.1-alpha.1", "stable"), ("3.0.1", "beta")):
            with self.subTest(version=version, channel=channel), self.assertRaises(ValueError):
                validate_channel(version, channel)
        ordered = ("3.0.0-alpha.9", "3.0.0-alpha.10", "3.0.0", "3.0.1-alpha.1", "3.0.1", "3.1.0")
        for left, right in zip(ordered, ordered[1:]):
            self.assertEqual(-1, compare_versions(left, right))
            self.assertEqual(1, compare_versions(right, left))
            self.assertEqual(0, compare_versions(left, left))

    def test_stable_identity_is_pinned_without_inventing_legacy_market_or_aliases(self):
        identity = load_identity(ROOT)
        self.assertEqual("xy-workflow", identity["marketplaces"]["stable"])
        self.assertEqual({"alpha", "local"}, set(identity["legacy_marketplaces"]))
        isolated = self.base / "identity-fixture"
        (isolated / "product").mkdir(parents=True)
        for mutate in (lambda item: item["marketplaces"].update(stable="unapproved"),
                       lambda item: item["marketplaces"].update(beta="xy-workflow-beta"),
                       lambda item: item["legacy_marketplaces"].update(stable="agent-workflow"),
                       lambda item: item["skill_aliases"].update({"xy-config": "other"})):
            value = json.loads((ROOT / "product/command_identity.json").read_bytes())
            mutate(value)
            (isolated / "product/command_identity.json").write_text(json.dumps(value))
            with self.subTest(value=value), self.assertRaises(ValueError):
                load_identity(isolated)

    def test_descriptor_rejects_mixed_or_unknown_channel_without_changing_published_source(self):
        descriptor = distribution.assemble(self.artifact)
        path = self.base / "descriptor.json"
        for channel in ("alpha", "beta", "local"):
            path.write_text(json.dumps({**descriptor, "channel": channel}))
            with self.subTest(channel=channel), self.assertRaises(distribution.store.ComponentError):
                distribution.store.descriptor(path)
        # 新共享模块是真实发行闭包的一部分，不能仅在源码 checkout 中碰巧可导入。
        _, bodies = distribution.store.archive_payload(self.artifact, self.report["version"])
        self.assertEqual(bodies["product/release_channels.py"], (ROOT / "product/release_channels.py").read_bytes())

    def test_redirects_allow_only_bounded_https_github_asset_hosts(self):
        handler = distribution.store.ReleaseRedirect()
        request = urllib.request.Request("https://github.com/Geoege-xll/agent-workflow/releases/download/v1/file.zip")
        redirected = handler.redirect_request(request, None, 302, "Found", {},
                                               "https://release-assets.githubusercontent.com/asset?signature=private")
        self.assertEqual(redirected.component_redirects, 1)
        for url in ("http://release-assets.githubusercontent.com/asset", "https://attacker.example/asset",
                    "https://user:password@github.com/asset", "https://github.com:444/asset",
                    "https://github.com/attacker/repo/releases/download/v1/file.zip"):
            with self.subTest(url=url), self.assertRaises(distribution.store.ComponentError):
                handler.redirect_request(request, None, 302, "Found", {}, url)
        request.component_redirects = 4
        with self.assertRaises(distribution.store.ComponentError):
            handler.redirect_request(request, None, 302, "Found", {}, "https://release-assets.githubusercontent.com/asset")

    def test_real_drip_headers_and_body_share_hard_total_budget_and_reap_only_download_worker(self):
        """真实 socket 持续滴入头部/正文；仅将 HTTPS 传输端点注入回环，下载代码保持原样。"""
        fixture = self.base / "loopback_worker.py"
        fixture.write_text('''import http.client,importlib.util,json,os,pathlib,sys,urllib.request
from unittest.mock import patch
spec=importlib.util.spec_from_file_location("download_store",sys.argv[1]);store=importlib.util.module_from_spec(spec);spec.loader.exec_module(store)
payload=json.load(sys.stdin)
pathlib.Path(sys.argv[3]).write_text(str(os.getpid()))
class LoopbackConnection(http.client.HTTPConnection):
 def __init__(self,host,*,deadline,**options):
  super().__init__("127.0.0.1",int(sys.argv[2]),timeout=store.download_remaining(deadline))
try:
 with patch.object(store,"DeadlineHTTPSConnection",LoopbackConnection),patch.object(store.urllib.request,"getproxies",return_value={}):
  store.download_transfer(payload["data"],pathlib.Path(payload["destination"]),payload["deadline"])
 report,code={"code":"ok"},0
except store.ComponentError as error:report,code={"code":str(error)},1
print(json.dumps(report));raise SystemExit(code)
''')
        data = {"artifact": {"name": self.artifact.name,
                "url": "https://github.com/Geoege-xll/agent-workflow/releases/download/native-v" + self.report["version"] + "/" + self.artifact.name}}
        for mode in ("complete", "headers", "body", "redirect_headers", "redirect_chain"):
            with self.subTest(mode=mode):
                listener = socket.socket()
                listener.bind(("127.0.0.1", 0))
                listener.listen(4)
                listener.settimeout(2)
                port = listener.getsockname()[1]
                stopped = threading.Event()
                received_close = threading.Event()
                def serve():
                    try:
                        if mode == "redirect_chain":
                            for redirect in ("https://release-assets.githubusercontent.com/asset",
                                             "https://objects.githubusercontent.com/asset"):
                                connection, _ = listener.accept()
                                with connection:
                                    connection.recv(4096)
                                    if stopped.wait(0.16):
                                        return
                                    connection.sendall(("HTTP/1.0 302 Found\r\nLocation: " + redirect +
                                                        "\r\nContent-Length: 0\r\n\r\n").encode())
                        connection, _ = listener.accept()
                        with connection:
                            connection.recv(4096)
                            if mode == "complete":
                                body = self.artifact.read_bytes()
                                connection.sendall(f"HTTP/1.0 200 OK\r\nContent-Length: {len(body)}\r\n\r\n".encode() + body)
                                return
                            elif mode == "body":
                                connection.sendall(b"HTTP/1.0 200 OK\r\nContent-Length: 65536\r\n\r\n")
                            elif mode == "headers":
                                connection.sendall(b"HTTP/1.0 200 OK\r\nX-Slow: ")
                            else:
                                connection.sendall(b"HTTP/1.0 302 Found\r\nX-Slow: ")
                            while not stopped.wait(0.02):
                                connection.sendall(b"x")
                    except (BrokenPipeError, ConnectionResetError):
                        received_close.set()
                    except TimeoutError:
                        pass
                    finally:
                        listener.close()
                thread = threading.Thread(target=serve, daemon=True)
                thread.start()
                started = time.monotonic()
                pid_file = self.base / (mode + ".pid")
                try:
                    if mode == "complete":
                        distribution.store.download(data, self.base / (mode + ".zip"), _budget=0.4,
                            _worker_command=[sys.executable, "-I", "-B", str(fixture),
                                str(ROOT / "plugins/maintenance/component_store.py"), str(port), str(pid_file)])
                        self.assertEqual((self.base / (mode + ".zip")).read_bytes(), self.artifact.read_bytes())
                        continue
                    with self.assertRaises(distribution.store.ComponentError) as error:
                        distribution.store.download(data, self.base / (mode + ".zip"), _budget=0.4,
                            _worker_command=[sys.executable, "-I", "-B", str(fixture),
                                str(ROOT / "plugins/maintenance/component_store.py"), str(port), str(pid_file)])
                    elapsed = time.monotonic() - started
                    self.assertEqual(str(error.exception), "download_timeout")
                    self.assertLess(elapsed, 0.9, "滴入响应不能把0.4秒总预算拖成整个响应持续时间")
                    with self.assertRaises(ProcessLookupError):
                        os.kill(int(pid_file.read_text()), 0)
                    if mode != "redirect_chain":
                        self.assertTrue(received_close.wait(0.3), "超时必须回收本次worker并关闭其连接")
                finally:
                    stopped.set()
                    thread.join(timeout=2)


if __name__ == "__main__":
    unittest.main()
