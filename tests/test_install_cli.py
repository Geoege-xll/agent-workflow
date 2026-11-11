"""只在本请求临时目录验证正式入口与源码入口的来源、安全及真实调用目录。"""

from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from manager import install_cli
from tests import test_workflow_manager as launcher_tests


PACK = Path(__file__).resolve().parents[1]


class DevelopmentEntryTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="awf-entry-", dir=os.environ.get("AWF_TEST_SCRATCH"))
        self.root = Path(self.temp.name).resolve()
        self.bin = self.root / "user bin"
        self.env = {**os.environ, "HOME": str(self.root / "home"),
                    "CODEX_HOME": str(self.root / "codex"), "CLAUDE_CONFIG_DIR": str(self.root / "claude"),
                    "AGENT_WORKFLOW_PYTHON": sys.executable}

    def tearDown(self):
        self.temp.cleanup()

    def run_entry(self, command, *arguments, env=None):
        return subprocess.run([*command, *arguments], cwd=self.root, env=env or self.env,
                              capture_output=True, text=True, timeout=15)

    def test_development_install_preserves_existing_formal_name_and_is_idempotent(self):
        self.bin.mkdir()
        # 旧 source awf-cli 即使能够解析到同一源码也不能自动删除或重写。
        # 迁移必须由外部先确认精确旧前像；安装 awf-dev 本身不授权迁移旧名。
        old = self.bin / "awf-cli"
        old.symlink_to(PACK / "workflow.sh")
        before = old.lstat()
        env = {**self.env, "PATH": str(self.bin) + os.pathsep + self.env["PATH"]}
        arguments = ("--install-cli", "--bin-dir", self.bin.name)
        first = self.run_entry(["/bin/bash", str(PACK / "workflow.sh")], *arguments, env=env)
        self.assertEqual(first.returncode, 0, first.stderr)
        self.assertIn("在任意目录输入 awf-dev", first.stdout)
        target = self.bin / "awf-dev"
        self.assertEqual(os.readlink(target), str(PACK / "workflow.sh"))
        inode = target.lstat().st_ino
        repeated = self.run_entry(["awf-dev"], *arguments, env=env)
        self.assertEqual(repeated.returncode, 0, repeated.stderr)
        self.assertEqual(target.lstat().st_ino, inode)
        self.assertEqual(old.lstat().st_ino, before.st_ino)
        self.assertEqual(os.readlink(old), str(PACK / "workflow.sh"))

    def test_existing_development_targets_are_preserved(self):
        outside = self.root / "outside"
        outside.write_bytes(b"USER COMMAND")
        for kind in ("file", "foreign", "dangling", "cycle", "directory"):
            with self.subTest(kind=kind):
                directory = self.root / kind
                directory.mkdir()
                target = directory / "awf-dev"
                if kind == "file":
                    target.write_bytes(b"EXISTING COMMAND")
                elif kind == "directory":
                    target.mkdir()
                else:
                    target.symlink_to(outside if kind == "foreign" else
                                      (directory / "missing" if kind == "dangling" else target))
                before = target.lstat()
                link = os.readlink(target) if target.is_symlink() else None
                with self.assertRaisesRegex(ValueError, "同名入口"):
                    install_cli.install(directory)
                self.assertEqual(target.lstat().st_ino, before.st_ino)
                if link is not None:
                    self.assertEqual(os.readlink(target), link)
                if kind == "file":
                    self.assertEqual(target.read_bytes(), b"EXISTING COMMAND")
                self.assertEqual(outside.read_bytes(), b"USER COMMAND")

    def test_concurrent_target_and_directory_replacement_do_not_overwrite(self):
        native_symlink = os.symlink
        self.bin.mkdir()
        target = self.bin / "awf-dev"

        def create_foreign(source, name, **kwargs):
            target.write_bytes(b"CONCURRENT COMMAND")
            return native_symlink(source, name, **kwargs)

        # 控制实际发布边界的时机，但最终仍调用真实排他 symlink；这个分支
        # 证明“检查之后才出现”的文件也被保留，而不是只检查预置文件。
        with patch.object(install_cli.os, "symlink", side_effect=create_foreign):
            with self.assertRaisesRegex(ValueError, "其他操作创建"):
                install_cli.install(self.bin)
        self.assertEqual(target.read_bytes(), b"CONCURRENT COMMAND")
        target.unlink()
        moved = self.root / "retained bin"
        outside = self.root / "outside bin"
        outside.mkdir()

        def replace_directory(source, name, **kwargs):
            self.bin.rename(moved)
            native_symlink(str(outside), str(self.bin), target_is_directory=True)
            return native_symlink(source, name, **kwargs)

        with patch.object(install_cli.os, "symlink", side_effect=replace_directory):
            with self.assertRaisesRegex(ValueError, "目录在操作期间被替换"):
                install_cli.install(self.bin)
        self.assertEqual(list(outside.iterdir()), [])
        self.assertEqual(os.readlink(moved / "awf-dev"), str(PACK / "workflow.sh"))

    def test_linked_parent_is_rejected_before_creating_external_directories(self):
        outside = self.root / "outside"
        outside.mkdir()
        alias = self.root / "alias"
        alias.symlink_to(outside, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, "链接或特殊节点"):
            install_cli.install(alias / "new bin")
        self.assertEqual(list(outside.iterdir()), [])

    def test_unwritable_directory_reports_failure_and_preserves_formal_command(self):
        self.bin.mkdir()
        formal = self.bin / "awf-cli"
        formal.write_bytes(b"EXISTING FORMAL COMMAND")
        before = formal.lstat().st_ino
        self.bin.chmod(0o555)
        try:
            if os.access(self.bin, os.W_OK):
                self.skipTest("当前账户或文件系统不执行普通目录写权限限制")
            # 使用真实权限拒绝及真实源码入口，不用 mock 的 PermissionError
            # 冒充原生文件系统证据；退出码须明确失败，正式命令仍完整保留。
            result = self.run_entry(["/bin/bash", str(PACK / "workflow.sh")],
                                    "--install-cli", "--bin-dir", str(self.bin))
            self.assertEqual(result.returncode, 2)
            self.assertIn("[错误]", result.stderr)
            self.assertNotIn("Traceback", result.stderr)
            self.assertFalse((self.bin / "awf-dev").exists())
            self.assertEqual(formal.lstat().st_ino, before)
            self.assertEqual(formal.read_bytes(), b"EXISTING FORMAL COMMAND")
        finally:
            self.bin.chmod(0o755)

    def test_path_diagnosis_checks_development_name_without_running_foreign_command(self):
        target = install_cli.install(self.bin)
        early = self.root / "early"
        early.mkdir()
        foreign = early / "awf-dev"
        foreign.write_text("#!/bin/sh\nexit 99\n", encoding="utf-8")
        foreign.chmod(0o755)
        cases = (
            (str(early) + os.pathsep + str(self.bin), "其他同名命令"),
            ("relative" + os.pathsep + str(self.bin), "相对或空目录项"),
            (str(self.bin) + os.pathsep + "relative", "在任意目录输入 awf-dev"),
            ("/usr/bin:/bin", "PATH 找不到 awf-dev"),
        )
        for lookup, expected in cases:
            with self.subTest(lookup=lookup), patch.dict(os.environ, {"PATH": lookup}):
                self.assertIn(expected, install_cli.command_message(target))

    def test_source_diagnostics_and_relative_project_use_real_caller(self):
        install_cli.install(self.bin)
        env = {**self.env, "PATH": str(self.bin) + os.pathsep + self.env["PATH"]}
        project = self.root / "project"
        project.mkdir()
        host_home = self.root / "home"
        version = (PACK / "product/VERSION").read_text(encoding="ascii").strip()
        expected = [f"awf-cli {version}（源码未打包）", f"中央源根：{PACK}",
                    "入口来源：source（显式源码开发）", f"物理载荷根：{PACK}"]
        for command in (["awf-dev"], ["/bin/bash", str(PACK / "workflow.sh")]):
            with self.subTest(command=command):
                result = self.run_entry(command, "--state-dir", "state", "--version", env=env)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stdout.splitlines(), expected)
                # 独立 state 的宿主读取必须显式绑定本夹具 HOME；不能仅依赖环境
                # 覆盖来绕过隔离保护。project 仍保留相对路径以验证真实调用目录。
                roles = self.run_entry(command, "--state-dir", "state", "--host-home", str(host_home),
                                       "roles", "--project", "project",
                                       "--platform", "codex", env=env)
                self.assertEqual(roles.returncode, 0, roles.stderr)
                self.assertEqual(json.loads(roles.stdout), {})
        self.assertFalse((self.root / "state").exists())
        self.assertFalse(host_home.exists())


def load_tests(loader, tests, pattern):
    """复用未变更的真实入口安全用例，避免把既有覆盖镜像进新文件。"""
    for name in (
        "test_cdpath_does_not_redirect_relative_links_or_pollute_source_directory",
        "test_cdpath_is_preserved_for_python_and_relative_project_arguments",
        "test_relative_python_is_selected_in_caller_directory_without_duplicate_probe",
        "test_invalid_explicit_relative_python_does_not_fall_back",
        "test_link_parent_alias_uses_physical_directory_even_with_logical_decoy",
        "test_relative_link_chain_and_source_directory_with_spaces",
    ):
        tests.addTest(launcher_tests.CliLauncherTest(name))
    return tests
