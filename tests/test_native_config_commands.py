"""安全维护命令的纯读取、令牌边界与真实并发启动；所有根均显式使用临时目录。"""

from __future__ import annotations

from contextlib import ExitStack
import hashlib
import json
import os
from pathlib import Path
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

from native_config import commands
from native_config.cli import open_console
from native_config.server import (ConsoleLifecycleError, ROOT, configuration_identity,
                                  process_lock, read_connection, service_version)
from native_config.service import ModelService


class SafeCommandTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name).resolve()
        self.data = self.root / "missing-data"
        self.home = self.root / "missing-home"
        self.project = self.root / "project"
        self.project.mkdir()

    def tearDown(self):
        self.temporary.cleanup()

    def execute(self, action, **kwargs):
        return commands.execute(action, self.data, home=self.home, **kwargs)

    def record(self, **changes):
        directory = self.data / "console"
        directory.mkdir(parents=True, mode=0o700)
        record = {"port": 12345, "token": "s" * 43, "pid": os.getpid(), "instance_id": "instance",
                  "protocol_version": 2, "service_version": service_version(),
                  "configuration_identity": configuration_identity(ModelService(self.data, home=self.home))}
        record.update(changes)
        target = directory / "connection.json"
        target.write_text(json.dumps(record))
        target.chmod(0o600)
        return target, record

    def snapshot(self):
        return {str(path.relative_to(self.root)): (path.stat().st_mode, path.read_bytes() if path.is_file() else None)
                for path in self.root.rglob("*")}

    def assert_read_only(self, action, expected, **kwargs):
        before = self.snapshot()
        # 快照验证字节和模式；主动禁止写操作及启动依赖，防止创建后删除绕过快照。
        with ExitStack() as stack:
            for name in ("mkdir", "chmod", "write_bytes", "write_text", "unlink", "rename", "replace"):
                stack.enter_context(mock.patch.object(Path, name, side_effect=AssertionError("只读命令发生写操作")))
            for target in ("native_config.cli.open_console", "native_config.cli.process_lock", "subprocess.Popen",
                           "webbrowser.open", "native_config.service.ModelService.context",
                           "native_config.service.ModelService.catalog", "native_config.service.ModelService._capture"):
                stack.enter_context(mock.patch(target, side_effect=AssertionError("只读命令启动依赖")))
            result, exit_code = self.execute(action, **kwargs)
        self.assertEqual(result["state"], expected, result)
        self.assertEqual(self.snapshot(), before)
        self.assertIsNone(result["launch_file"])
        return result, exit_code

    def test_missing_status_and_doctor_do_not_create_any_roots(self):
        for action in ("status", "doctor"):
            result, code = self.assert_read_only(action, "stopped")
            self.assertEqual(code, 0)
            self.assertEqual(result["component"]["integrity"], "development_source")
            self.assertFalse(self.data.exists())
            self.assertFalse(self.home.exists())
            self.assertEqual(result["location"], {"host": "codex", "scope": "global", "project": None})

    def test_bad_records_and_version_conflicts_are_unchanged_and_sanitized(self):
        target, record = self.record(protocol_version=999)
        for action in ("status", "doctor", "open"):
            if action == "open":
                result, code = self.execute(action)
            else:
                result, code = self.assert_read_only(action, "incompatible_service")
            self.assertEqual(code, 1)
            self.assertEqual(result["code"], "incompatible_service")
            self.assertNotIn(record["token"], json.dumps(result))
            self.assertEqual(json.loads(target.read_text()), record)
        target.write_text('{"token":"' + record["token"] + '",bad')
        for action in ("status", "doctor"):
            result, code = self.assert_read_only(action, "invalid_record")
            self.assertEqual(code, 1)
            self.assertNotIn(record["token"], json.dumps(result))

    def test_configuration_conflict_and_public_directory_are_not_repaired(self):
        target, record = self.record(configuration_identity="other-home")
        for action in ("status", "doctor"):
            result, code = self.assert_read_only(action, "configuration_conflict")
            self.assertEqual(code, 1)
        target.parent.chmod(0o755)
        self.assert_read_only("status", "invalid_record")
        self.assertEqual(stat.S_IMODE(target.parent.stat().st_mode), 0o755)

    def test_status_does_not_follow_connection_directory_symlink(self):
        self.data.mkdir()
        external = self.root / "other"
        external.mkdir()
        (self.data / "console").symlink_to(external, target_is_directory=True)
        result, code = self.assert_read_only("doctor", "invalid_record")
        self.assertEqual(code, 1)

    def test_dead_service_has_honest_read_only_state(self):
        self.record()
        with mock.patch("native_config.server._health", side_effect=ConnectionRefusedError):
            result, code = self.assert_read_only("status", "unreachable")
        self.assertEqual(code, 1)
        self.assertIsNone(result["console_url"])

    def test_read_only_status_requires_actual_health_identity_not_pid_or_port(self):
        target, record = self.record()
        health = {key: record[key] for key in ("protocol_version", "service_version", "instance_id", "configuration_identity")}
        with mock.patch("native_config.server._health", return_value=health):
            result, code = self.assert_read_only("status", "ready")
        self.assertEqual(code, 0)
        self.assertEqual(result["console_url"], "http://127.0.0.1:12345/")
        self.assertNotIn(record["token"], json.dumps(result))
        for key in health:
            wrong = {**health, key: "incorrect-identity"}
            with mock.patch("native_config.server._health", return_value=wrong):
                result, code = self.assert_read_only("status", "handshake_failed")
            self.assertEqual(code, 1)
            self.assertEqual(json.loads(target.read_text()), record)

    def test_project_scope_is_selected_without_discovery_or_host_execution(self):
        result, code = self.assert_read_only("doctor", "stopped", project=str(self.project))
        self.assertEqual(code, 0)
        self.assertEqual(result["location"], {"host": "codex", "scope": "project", "project": str(self.project)})
        invalid, code = self.execute("status", project="relative")
        self.assertEqual(code, 2)
        self.assertEqual(invalid["code"], "invalid_arguments")

    def test_release_doctor_checks_manifest_bytes_and_full_closure(self):
        package = self.root / "release"
        package.mkdir()
        files = {}
        for relative in commands.REQUIRED_FILES:
            path = package / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("component " + relative)
            files[relative] = hashlib.sha256(path.read_bytes()).hexdigest()
        manifest = package / "BUILD.json"
        manifest.write_text(json.dumps({"name": commands.PRODUCT, "version": service_version(),
                                        "third_party_dependencies": [], "files": files}))
        with mock.patch.object(commands, "ROOT", package):
            result, code = self.assert_read_only("doctor", "stopped")
            self.assertEqual(code, 0)
            self.assertEqual(result["component"]["integrity"], "verified")
            (package / "native_config/cli.py").write_text("tampered")
            result, code = self.assert_read_only("doctor", "error")
            self.assertEqual(code, 1)
            self.assertEqual(result["code"], "invalid_component")
            (package / "native_config/cli.py").write_text("component native_config/cli.py")
            (package / "unlisted.py").write_text("unexpected")
            result, code = self.assert_read_only("doctor", "error")
            self.assertEqual(code, 1)

    def test_open_browser_false_exception_and_no_browser_keep_private_link(self):
        (self.data / "console").mkdir(parents=True, mode=0o700)
        secret = "a" * 43
        authenticated = f"http://127.0.0.1:12345/#token={secret}&host=codex"
        opened = {"url": authenticated, "reused": True, "protocol_version": 2, "service_version": service_version()}
        for behavior in (False, RuntimeError("secret exception " + secret), True, "no_browser"):
            with mock.patch("native_config.cli.open_console", return_value=opened) as opener, \
                 mock.patch("native_config.commands.webbrowser.open", side_effect=behavior if isinstance(behavior, Exception) else None,
                            return_value=behavior is True) as browser:
                result, code = self.execute("open", no_browser=behavior == "no_browser")
            self.assertEqual(result["state"], "ready")
            self.assertNotIn(secret, json.dumps(result))
            self.assertEqual(result["console_url"], "http://127.0.0.1:12345/")
            launch = Path(result["launch_file"])
            self.assertEqual(stat.S_IMODE(launch.stat().st_mode), 0o600)
            self.assertIn("token=" + secret, launch.read_text())
            self.assertIn("&amp;host=codex", launch.read_text())
            self.assertFalse(opener.call_args.kwargs["open_browser"])
            if behavior == "no_browser":
                self.assertEqual(code, 0)
                browser.assert_not_called()
                self.assertEqual(result["browser"]["state"], "not_requested")
            elif behavior is True:
                self.assertEqual(code, 0)
                self.assertEqual(result["browser"]["state"], "opened")
            else:
                self.assertEqual(code, 3)
                self.assertEqual(result["code"], "browser_failed")
                self.assertEqual(result["service"]["state"], "ready")

    def test_private_launch_file_rejects_nonprivate_or_linked_parent(self):
        directory = self.data / "console"
        directory.mkdir(parents=True, mode=0o755)
        directory.chmod(0o755)
        with self.assertRaises(ValueError):
            commands._private_launch_file(self.data, "http://127.0.0.1:12345/#token=private")
        self.assertEqual(list(directory.iterdir()), [])
        directory.rmdir()
        external = self.root / "external"
        external.mkdir(mode=0o700)
        directory.symlink_to(external, target_is_directory=True)
        with self.assertRaises(OSError):
            commands._private_launch_file(self.data, "http://127.0.0.1:12345/#token=private")
        self.assertEqual(list(external.iterdir()), [])

    def test_startup_exception_is_fixed_safe_json(self):
        with mock.patch("native_config.cli.open_console", side_effect=ValueError("token=secret-value")):
            result, code = self.execute("open")
        self.assertEqual(code, 1)
        self.assertEqual(result["code"], "startup_failed")
        self.assertNotIn("secret-value", json.dumps(result))

    def test_missing_private_link_does_not_discard_ready_service(self):
        opened = {"url": "http://127.0.0.1:12345/#token=" + "x" * 43, "reused": True,
                  "protocol_version": 2, "service_version": service_version()}
        with mock.patch("native_config.cli.open_console", return_value=opened), \
             mock.patch("native_config.commands._private_launch_file", side_effect=OSError("secret")):
            result, code = self.execute("open")
        self.assertEqual(code, 1)
        self.assertEqual(result["code"], "launch_file_failed")
        self.assertEqual(result["service"]["state"], "ready")
        self.assertEqual(result["state"], "ready")
        self.assertNotIn("secret", json.dumps(result))

    def test_launch_lock_wait_and_partial_line_share_finite_budget(self):
        directory = self.data / "console"
        directory.mkdir(parents=True, mode=0o700)
        with process_lock(directory / "launch.lock"):
            started = time.monotonic()
            with self.assertRaises(ConsoleLifecycleError) as caught:
                open_console(self.data, home=self.home, timeout=0.3)
            self.assertEqual(caught.exception.code, "launch_timeout")
            self.assertLess(time.monotonic() - started, 0.8)
        original = subprocess.Popen
        # 真实子进程写半行后睡眠；若仍使用 readline，该测试会挂到外层超时。
        owned = []
        def partial_child(*_args, **kwargs):
            child = original([sys.executable, "-B", "-c",
                              "import signal,sys,time;signal.signal(signal.SIGTERM,signal.SIG_IGN);"
                              "sys.stdout.write('{');sys.stdout.flush();time.sleep(10)"], **kwargs)
            owned.append(child)
            return child
        with mock.patch("native_config.cli.subprocess.Popen", side_effect=partial_child):
            started = time.monotonic()
            with self.assertRaises(ConsoleLifecycleError) as caught:
                open_console(self.data, home=self.home, timeout=0.4)
            self.assertEqual(caught.exception.code, "launch_timeout")
            self.assertLess(time.monotonic() - started, 1)
        self.assertEqual(len(owned), 1)
        owned[0].wait(timeout=0.5)
        self.assertIsNotNone(owned[0].poll(), "启动超时后必须回收本次子进程")


class SafeCommandLoopbackTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name).resolve()
        self.data = self.root / "data"
        self.home = self.root / "home"
        self.home.mkdir()
        self.project = self.root / "project"
        self.project.mkdir()
        self.pid = None

    def tearDown(self):
        if self.pid is not None:
            try:
                os.kill(self.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            deadline = time.monotonic() + 5
            while (self.data / "console/connection.json").exists() and time.monotonic() < deadline:
                time.sleep(0.02)
        self.temporary.cleanup()

    def command(self, action, *extra):
        return [sys.executable, "-B", str(ROOT / "scripts/agent_config.py"), action,
                "--home", str(self.home), "--data-dir", str(self.data), *extra]

    def test_concurrent_first_open_uses_one_service_and_status_doctor_stay_read_only(self):
        first = subprocess.Popen(self.command("open", "--no-browser"), stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        second = subprocess.Popen(self.command("open", "--no-browser", "--project", str(self.project)),
                                  stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        receipts = []
        try:
            for child in (first, second):
                stdout, stderr = child.communicate(timeout=12)
                self.assertEqual(child.returncode, 0, stderr.decode())
                receipts.append(json.loads(stdout))
            record = read_connection(self.data / "console")
            self.pid = record["pid"]
            self.assertEqual(sorted(item["service"]["reused"] for item in receipts), [False, True])
            self.assertEqual(len({item["console_url"] for item in receipts}), 1)
            for item in receipts:
                self.assertNotIn(record["token"], json.dumps(item))
                self.assertEqual(stat.S_IMODE(Path(item["launch_file"]).stat().st_mode), 0o600)
            before = {str(p): (p.read_bytes(), p.stat().st_mode) for p in self.data.rglob("*") if p.is_file()}
            for action in ("status", "doctor"):
                queried = subprocess.run(self.command(action, "--project", str(self.project)), capture_output=True, timeout=4)
                self.assertEqual(queried.returncode, 0, queried.stderr.decode())
                result = json.loads(queried.stdout)
                self.assertEqual(result["state"], "ready")
                self.assertNotIn(record["token"], queried.stdout.decode())
                self.assertIsNone(result["launch_file"])
            self.assertEqual(before, {str(p): (p.read_bytes(), p.stat().st_mode) for p in self.data.rglob("*") if p.is_file()})
            self.assertEqual(read_connection(self.data / "console")["pid"], self.pid)
        finally:
            for child in (first, second):
                if child.poll() is None:
                    child.kill()
                child.communicate(timeout=2)
            if self.pid is None:
                record = read_connection(self.data / "console")
                self.pid = record["pid"] if record else None

    def test_health_probe_cannot_be_kept_alive_by_dripped_partial_headers(self):
        from native_config.server import _health
        listener = socket.socket()
        try:
            listener.bind(("127.0.0.1", 0))
            listener.listen(1)
        except BaseException:
            listener.close()
            raise
        stopped = threading.Event()
        def drip():
            connection, _ = listener.accept()
            try:
                connection.recv(4096)
                while not stopped.wait(0.03):
                    connection.sendall(b"H")
            except OSError:
                pass
            finally:
                connection.close()
        thread = threading.Thread(target=drip)
        thread.start()
        try:
            started = time.monotonic()
            with self.assertRaises(TimeoutError):
                _health({"port": listener.getsockname()[1], "token": "x" * 43}, 0.2)
            self.assertLess(time.monotonic() - started, 0.6)
        finally:
            stopped.set()
            listener.close()
            thread.join(timeout=2)


if __name__ == "__main__":
    unittest.main()
