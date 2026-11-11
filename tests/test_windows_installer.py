"""安装协议的真实文件/子进程边界；便携执行不冒充 Windows ACL/Job 验收。"""

from __future__ import annotations

from argparse import Namespace
import contextlib
import hashlib
import io
import json
import os
from pathlib import Path
import sys
import tarfile
import tempfile
import unittest
from unittest.mock import patch
import venv

from lib.central.runtime_project import Tree, unique_json
from lib.install import windows_installer as installer


PACK = Path(__file__).resolve().parents[1]
VERSION = "2.1.4"
PREFIX = "agent-workflow-" + VERSION
BINDING = {"protocol_version": 1, "content_id": "a" * 64, "manifest_sha256": "a" * 64}
# 此物理 CLI fixture 只隔离中央业务，仍实际启动最终路径的私有解释器、消费
# argv 并写可观察副作用；不能把它的成功报告成真实中央激活或 Windows 通过。
CLI_FIXTURE = '''import json
from pathlib import Path
import sys
root = Path(__file__).resolve().parents[1]
arguments = sys.argv[1:]
command = arguments[arguments.index("runtime"):]
with (root / "commands.jsonl").open("a", encoding="utf-8") as stream:
    stream.write(json.dumps(command) + "\\n")
binding = {"protocol_version": 1, "content_id": "a" * 64, "manifest_sha256": "a" * 64}
preview = "--dry-run" in command
mode = (root / "test-mode").read_text() if (root / "test-mode").exists() else ""
result = {"runtime_binding": binding}
if command[1] == "activate":
    result.update(can_apply=mode != "conflict")
    if not preview:
        (root / "central-side-effect").write_text("applied")
        if mode == "fail":
            raise SystemExit(17)
        if mode == "unknown":
            print("lost-success-envelope")
            raise SystemExit(0)
        result.update(new_task_allowed=True, management_write_allowed=True,
                      pending_activation=None, issues=[])
print(json.dumps({"schema_version": 1, "command": " ".join(command[:2]),
                  "dry_run": preview, "result": result}))
'''.encode()


def archive_bytes(extra=(), *, cli=CLI_FIXTURE):
    stream = io.BytesIO()
    with tarfile.open(fileobj=stream, mode="w:gz") as archive:
        root = tarfile.TarInfo(PREFIX)
        root.type = tarfile.DIRTYPE
        archive.addfile(root)
        entries = [("workflow.py", cli), ("requirements-windows.txt", b"--require-hashes\n--only-binary=:all:\n"),
                   ("product/VERSION", (VERSION + "\n").encode()),
                   ("manager/release.json", json.dumps({"schema_version": 1, "version": VERSION}).encode()), *extra]
        for name, body in entries:
            if isinstance(name, tarfile.TarInfo):
                archive.addfile(name, io.BytesIO(body) if body else None)
            else:
                member = tarfile.TarInfo(PREFIX + "/" + name)
                member.mode, member.size = 0o644, len(body)
                archive.addfile(member, io.BytesIO(body))
    return stream.getvalue()


class ArchiveConsumptionTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()

    def test_verified_bytes_survive_download_path_replacement(self):
        path = self.root / "release.tar.gz"
        data = archive_bytes([("目录/带 空格.txt", "同一字节".encode())])
        path.write_bytes(data)
        verified = installer._verified_archive(path, hashlib.sha256(data).hexdigest())
        path.unlink()
        path.write_bytes(b"untrusted replacement")
        destination = self.root / "program"
        destination.mkdir()
        with Tree(destination) as tree:
            files = installer.extract_payload(verified, tree, VERSION)
            installer._validate_payload(tree, files)
        self.assertEqual("同一字节", (destination / "payload/目录/带 空格.txt").read_text())
        with self.assertRaises(installer.InstallerError):
            installer._verified_archive(path, hashlib.sha256(data).hexdigest())

    def test_rejects_escape_alias_duplicates_links_and_special_nodes(self):
        bad = ["../outside", "/absolute", "C:/ads", "dir\\outside", "NUL.txt", "tail. ",
               "short~1.py", "dir//name", "e\u0301.py"]
        for name in bad:
            with self.subTest(name=name):
                destination = self.root / "target"
                destination.mkdir(exist_ok=True)
                with Tree(destination) as tree, self.assertRaises((ValueError, OSError)):
                    installer.extract_payload(archive_bytes([(name, b"x")]), tree, VERSION)
                shutil_remove_payload(destination)
        pairs = [[("same", b"1"), ("same", b"2")], [("Dir/a", b"1"), ("dir/b", b"2")],
                 [("File", b"1"), ("file", b"2")]]
        for entries in pairs:
            with self.subTest(entries=entries), self.assertRaises(ValueError):
                installer.extract_payload(archive_bytes(entries), None, VERSION)
        for kind in (tarfile.SYMTYPE, tarfile.LNKTYPE, tarfile.FIFOTYPE, tarfile.CHRTYPE, tarfile.BLKTYPE):
            member = tarfile.TarInfo(PREFIX + "/danger")
            member.type, member.linkname = kind, "../../outside"
            with self.subTest(kind=kind), self.assertRaises(ValueError):
                installer.extract_payload(archive_bytes([(member, b"")]), None, VERSION)
        self.assertFalse((self.root / "outside").exists())

    def test_member_count_size_expanded_budget_and_missing_metadata(self):
        for constant, budget, data in (
            ("MEMBER_LIMIT", 100, archive_bytes()),
            ("MEMBER_COUNT_LIMIT", 2, archive_bytes()),
            ("EXPANDED_LIMIT", 1024, archive_bytes()),
        ):
            with self.subTest(constant=constant), patch.object(installer, constant, budget), self.assertRaises(ValueError):
                installer.extract_payload(data, None, VERSION)
        data = archive_bytes([("manager/release.json", b'{"schema_version":1,"version":"9.9.9"}')])
        with self.assertRaises(ValueError):
            installer.extract_payload(data, None, VERSION)

    def test_archive_reader_rejects_symlink_and_hardlink(self):
        path = self.root / "archive"
        path.write_bytes(archive_bytes())
        linked = self.root / "linked"
        try:
            linked.symlink_to(path)
        except OSError:
            pass
        else:
            with self.assertRaises((ValueError, OSError)):
                installer._verified_archive(linked, hashlib.sha256(path.read_bytes()).hexdigest())
            linked.unlink()
        os.link(path, linked)
        with self.assertRaises((ValueError, OSError)):
            installer._verified_archive(path, hashlib.sha256(path.read_bytes()).hexdigest())


def shutil_remove_payload(root):
    # 测试自有的失败解包现场只在 fixture 清理，不给生产引擎增加删除/回滚能力。
    import shutil
    if (root / "payload").exists():
        shutil.rmtree(root / "payload")


class InstallationTransactionTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name).resolve()
        self.archive = self.directory / "release.tar.gz"
        data = archive_bytes()
        self.archive.write_bytes(data)
        self.digest = hashlib.sha256(data).hexdigest()
        self.args = Namespace(archive=self.archive, archive_sha256=self.digest, version=VERSION,
                              install_root=self.directory / "程序 空间", state_dir=self.directory / "state",
                              host_home=self.directory / "home", json=True)
        self.version_root = self.args.install_root / "versions" / (VERSION + "-" + self.digest)
        self.host_patch = patch.object(installer, "_validate_host")
        self.host_patch.start()
        self.addCleanup(self.host_patch.stop)

    def environment(self, root, runner, mode=""):
        venv.EnvBuilder(with_pip=False, symlinks=False).create(root / "venv")
        if mode:
            (root / "test-mode").write_text(mode)

    def install(self, mode=""):
        with patch.object(installer, "_prepare_environment", side_effect=lambda root, runner: self.environment(root, runner, mode)):
            return installer.install(self.args)

    def receipt(self):
        return unique_json((self.version_root / "install.json").read_bytes())

    def test_final_venv_physical_cli_order_launchers_and_repeat(self):
        result = self.install()
        self.assertEqual("complete", result["phase"])
        self.assertEqual(BINDING, result["runtime_binding"])
        self.assertTrue(installer._python(self.version_root).is_file())
        self.assertIn(str(self.version_root / "venv"), (self.version_root / "venv/pyvenv.cfg").read_text())
        commands = [json.loads(line) for line in (self.version_root / "commands.jsonl").read_text().splitlines()]
        self.assertEqual(["install", "activate", "activate"], [command[1] for command in commands])
        self.assertEqual(str(self.version_root / "payload"), commands[0][2])
        self.assertIn("--dry-run", commands[1])
        self.assertNotIn("--dry-run", commands[2])
        ps = Path(result["launchers"][0]).read_text()
        self.assertIn(str(installer._python(self.version_root)), ps)
        self.assertIn("@workflowOptions @args", ps)
        self.assertEqual("complete", self.receipt()["phase"])
        with patch.object(installer, "_prepare_environment", side_effect=AssertionError("不得重建环境")):
            self.assertEqual("complete", installer.install(self.args)["phase"])
        self.assertEqual(1, len(list((self.args.install_root / "versions").iterdir())))
        old_root, old_receipt = self.version_root, (self.version_root / "install.json").read_bytes()
        data = archive_bytes([("upgrade-marker", b"new delivery")])
        self.archive.write_bytes(data)
        self.args.archive_sha256 = hashlib.sha256(data).hexdigest()
        self.install()
        self.assertEqual(2, len(list((self.args.install_root / "versions").iterdir())))
        self.assertEqual(old_receipt, (old_root / "install.json").read_bytes())
        self.assertTrue(installer._python(old_root).exists())

    def test_activation_failure_and_unknown_response_preserve_environment_and_refuse_retry(self):
        for mode, code in (("fail", 17), ("unknown", 2)):
            with self.subTest(mode=mode):
                self.args.install_root = self.directory / mode
                self.version_root = self.args.install_root / "versions" / (VERSION + "-" + self.digest)
                with self.assertRaises(installer.InstallerError) as caught:
                    self.install(mode)
                self.assertEqual(code, caught.exception.exit_code)
                self.assertEqual("activation_started", caught.exception.phase)
                self.assertTrue((self.version_root / "central-side-effect").exists())
                self.assertTrue(installer._python(self.version_root).exists())
                self.assertEqual("activation_started", self.receipt()["phase"])
                self.assertFalse((self.args.install_root / "bin/awf-cli.ps1").exists())
                commands = (self.version_root / "commands.jsonl").read_bytes()
                with self.assertRaisesRegex(installer.InstallerError, "上次中央激活结果未知"):
                    installer.install(self.args)
                self.assertEqual(commands, (self.version_root / "commands.jsonl").read_bytes())

    def test_preview_conflict_stops_before_activation_and_publication(self):
        with self.assertRaises(installer.InstallerError) as caught:
            self.install("conflict")
        self.assertEqual("activate_preview", caught.exception.phase)
        self.assertEqual("environment_ready", self.receipt()["phase"])
        self.assertFalse((self.version_root / "central-side-effect").exists())
        self.assertFalse((self.args.install_root / "bin/awf-cli.ps1").exists())

    def test_unknown_root_version_launcher_and_extra_payload_are_preserved(self):
        self.args.install_root.mkdir()
        unknown = self.args.install_root / "user-file"
        unknown.write_text("保留")
        with self.assertRaises(installer.InstallerError):
            self.install()
        self.assertEqual("保留", unknown.read_text())
        unknown.unlink()
        self.install()
        launcher = self.args.install_root / "bin/awf-cli.ps1"
        launcher.write_text("用户入口")
        with self.assertRaises(installer.InstallerError):
            installer.install(self.args)
        self.assertEqual("用户入口", launcher.read_text())
        launcher.unlink()
        extra = self.version_root / "payload/manager/user_module.py"
        extra.write_text("raise RuntimeError('不能执行')")
        with self.assertRaisesRegex(installer.InstallerError, "未知文件"):
            installer.install(self.args)
        self.assertTrue(extra.exists())

    def test_unfinished_unknown_version_is_never_overwritten(self):
        self.version_root.mkdir(parents=True)
        (self.args.install_root / installer.ROOT_RECEIPT).write_bytes(installer.ROOT_BYTES)
        user_file = self.version_root / "user-environment"
        user_file.write_text("不能覆盖")
        with patch.object(installer, "_prepare_environment", side_effect=AssertionError("不能修改旧目录")):
            with self.assertRaisesRegex(installer.InstallerError, "已有版本目录未完成"):
                installer.install(self.args)
        self.assertEqual("不能覆盖", user_file.read_text())

    def test_actual_source_cli_readonly_install_envelope(self):
        # 真正消费仓库 CLI 的只读 inspect，不向实际中央状态、宿主或项目安装。
        self.version_root.mkdir(parents=True)
        self.environment(self.version_root, None)
        payload = self.version_root / "payload"
        payload.mkdir()
        (payload / "workflow.py").write_text(
            "import runpy\nrunpy.run_path(" + repr(str(PACK / "workflow.py")) + ", run_name='__main__')\n")
        result = installer._cli(self.version_root, ["--state-dir", str(self.directory / "unused-state")],
                                ["runtime", "install", str(PACK), "--dry-run"], dry_run=True)
        self.assertRegex(result["runtime_binding"]["content_id"], r"^[0-9a-f]{64}$")
        self.assertFalse((self.directory / "unused-state").exists())

    def test_main_json_preserves_child_exit_code(self):
        arguments = ["--archive", str(self.archive), "--archive-sha256", self.digest, "--version", VERSION,
                     "--install-root", str(self.args.install_root), "--state-dir", str(self.args.state_dir),
                     "--host-home", str(self.args.host_home), "--json"]
        output = io.StringIO()
        with patch.object(installer, "_prepare_environment", side_effect=lambda root, runner: self.environment(root, runner, "fail")):
            with contextlib.redirect_stdout(output):
                code = installer.main(arguments)
        self.assertEqual(17, code)
        envelope = json.loads(output.getvalue())
        self.assertFalse(envelope["ok"])
        self.assertEqual("activation_started", envelope["phase"])


class NativeHostGateTest(unittest.TestCase):
    def test_real_venv_and_pip_use_final_private_path_without_network(self):
        # 真正执行生产 venv/pip 入口，只以空且禁网的本地锁清单避免访问 PyPI。
        # windows-curses wheel、原生 TUI 与 ACL/Job 的结果仍由 Windows CI 负责。
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve() / "最终 环境"
            (root / "payload").mkdir(parents=True)
            (root / "payload/requirements-windows.txt").write_text(
                "--no-index\n--require-hashes\n--only-binary=:all:\n", encoding="utf-8")
            runner = installer.SetupRunner(timeout=120)
            token = installer.ACTIVE_RUNNER.set(runner)
            try:
                installer._prepare_environment(root, runner)
                process = installer.capture_process(
                    [str(installer._python(root)), "-I", "-B", "-X", "utf8", "-c",
                     "import sys; print(sys.prefix)"], timeout=30)
            finally:
                installer.ACTIVE_RUNNER.reset(token)
                runner.close()
            self.assertEqual(0, process.returncode)
            self.assertEqual(str(root / "venv"), process.stdout.decode().strip())

    @unittest.skipIf(sys.platform == "win32", "非 Windows 拒绝分支只在便携宿主执行")
    def test_non_windows_main_fails_without_creating_install_root(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "must-not-exist"
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                code = installer.main(["--archive", str(Path(temporary) / "missing"), "--archive-sha256", "a" * 64,
                                       "--version", VERSION, "--install-root", str(root), "--json"])
            self.assertEqual(2, code)
            self.assertEqual("preflight", json.loads(output.getvalue())["phase"])
            self.assertFalse(root.exists())


if __name__ == "__main__":
    unittest.main()
