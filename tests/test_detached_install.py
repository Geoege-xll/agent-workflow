from __future__ import annotations

import json
import shutil
import stat
import subprocess
import tempfile
import tomllib
import unittest
from pathlib import Path
from unittest.mock import patch

from lib import install_workflow


PACK = Path(__file__).resolve().parents[1]


class ProjectNameInstallationTest(unittest.TestCase):
    """项目名只由安装目标初始化，不修改显式名称或其他项目配置。"""

    def test_first_install_uses_target_name_before_preflight(self) -> None:
        with tempfile.TemporaryDirectory(prefix="workflow-project-name-") as raw:
            project = Path(raw).resolve() / "ParentsKit"
            project.mkdir()
            source_before = (PACK / "project.yaml").read_bytes()
            seen = []

            def check_name(runtime, target, *options):
                # 预检和正式安装均应拿到真实名称，而不是暂存目录名或源包父目录名。
                body = (runtime / "project.yaml").read_bytes()
                expected = source_before.replace(b"project_name: MyProject", b'project_name: "ParentsKit"', 1)
                self.assertEqual(expected, body)
                seen.append(options)

            with patch.object(install_workflow, "_run_setup", side_effect=check_name):
                install_workflow._install(project, PACK)
            self.assertEqual([("--preflight",), (), ("--check",)], seen)
            self.assertEqual(source_before, (PACK / "project.yaml").read_bytes())

    def test_upgrade_replaces_only_placeholder_and_preserves_config(self) -> None:
        values = ("MyProject", "'MyProject'", '"MyProject"', '"团队自定义名称"')
        for value in values:
            with self.subTest(value=value), tempfile.TemporaryDirectory(prefix="workflow-upgrade-name-") as raw:
                project = Path(raw).resolve() / "ParentsKit"
                project.mkdir()
                with patch.object(install_workflow, "_run_setup"):
                    install_workflow._install(project, PACK)
                config = project / ".agent-workflow/project.yaml"
                # 保留 CRLF、行内注释、记忆 ID 和其他配置；旧运行时备份必须仍是原字节。
                original = (PACK / "project.yaml").read_text().replace(
                    "project_name: MyProject", f"project_name: {value}  # 项目显示名", 1
                ).replace("\n", "\r\n").encode("utf-8")
                config.write_bytes(original)
                config.chmod(0o640)
                with patch.object(install_workflow, "_run_setup"):
                    install_workflow._install(project, PACK)
                expected = original if value == '"团队自定义名称"' else original.replace(
                    f"project_name: {value}".encode(), b'project_name: "ParentsKit"', 1
                )
                self.assertEqual(expected, config.read_bytes())
                self.assertEqual(0o640, stat.S_IMODE(config.stat().st_mode))
                backup = next(project.glob(".agent-workflow-backup-*/project.yaml"))
                self.assertEqual(original, backup.read_bytes())

    def test_repeated_upgrades_keep_only_latest_runtime_backup(self) -> None:
        with tempfile.TemporaryDirectory(prefix="workflow-backup-rotation-") as raw:
            project = Path(raw).resolve() / "ParentsKit"
            project.mkdir()
            # 角色模型备份和失败版本由其他流程维护，轮换只能处理安装器运行时备份。
            models = project / ".agent-workflow-backup-models-keep"
            failed = project / ".agent-workflow-failed-0123456789ab"
            models.mkdir()
            failed.mkdir()
            with patch.object(install_workflow, "_run_setup"):
                for _ in range(3):
                    install_workflow._install(project, PACK)
            runtime_backups = [
                path for path in project.glob(".agent-workflow-backup-*")
                if install_workflow.RUNTIME_BACKUP_NAME.fullmatch(path.name)
            ]
            self.assertEqual(1, len(runtime_backups))
            self.assertTrue((runtime_backups[0] / "project.yaml").is_file())
            self.assertTrue(models.is_dir())
            self.assertTrue(failed.is_dir())

            # 用户手工新增或修改过内容的备份目录不会被自动轮换删除。
            user_touched = runtime_backups[0]
            (user_touched / "user-note.txt").write_text("keep me\n", encoding="utf-8")
            with patch.object(install_workflow, "_run_setup"):
                install_workflow._install(project, PACK)
            self.assertTrue(user_touched.is_dir())
            self.assertTrue((user_touched / "user-note.txt").is_file())
            remaining = [
                path for path in project.glob(".agent-workflow-backup-*")
                if install_workflow.RUNTIME_BACKUP_NAME.fullmatch(path.name)
            ]
            self.assertEqual(2, len(remaining))

    def test_backup_config_edits_and_permission_changes_survive_next_upgrade(self) -> None:
        """项目配置不受升级清单约束，但它的后续修改必须阻止整份备份被轮换删除。"""
        for change in ("content", "permissions"):
            with self.subTest(change=change), tempfile.TemporaryDirectory(prefix="workflow-backup-config-") as raw:
                project = Path(raw).resolve() / "project"
                project.mkdir()
                with patch.object(install_workflow, "_run_setup"):
                    install_workflow._install(project, PACK)
                    install_workflow._install(project, PACK)
                    backup = next(project.glob(".agent-workflow-backup-*"))
                    config = backup / "project.yaml"
                    if change == "content":
                        config.write_bytes(b"project_name: unique-recovery-config\n")
                    else:
                        config.chmod(0o600 if stat.S_IMODE(config.stat().st_mode) != 0o600 else 0o640)
                    expected_body = config.read_bytes()
                    expected_mode = stat.S_IMODE(config.stat().st_mode)
                    install_workflow._install(project, PACK)
                self.assertTrue(backup.is_dir())
                self.assertEqual(expected_body, config.read_bytes())
                self.assertEqual(expected_mode, stat.S_IMODE(config.stat().st_mode))

    def test_legacy_backup_without_creation_snapshot_is_preserved(self) -> None:
        """历史备份没有原始配置指纹，不能在清理时追认其当前内容为安全基线。"""
        with tempfile.TemporaryDirectory(prefix="workflow-backup-legacy-") as raw:
            project = Path(raw).resolve() / "project"
            project.mkdir()
            with patch.object(install_workflow, "_run_setup"):
                install_workflow._install(project, PACK)
                install_workflow._install(project, PACK)
                backup = next(project.glob(".agent-workflow-backup-*"))
                manifest_path = backup / install_workflow.MANIFEST_NAME
                manifest = json.loads(manifest_path.read_bytes())
                del manifest["backup_snapshot"]
                manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
                (backup / "project.yaml").write_bytes(b"project_name: legacy-recovery-config\n")
                install_workflow._install(project, PACK)
            self.assertTrue(backup.is_dir())
            self.assertEqual(b"project_name: legacy-recovery-config\n", (backup / "project.yaml").read_bytes())

    def test_manifest_user_fields_and_permission_changes_preserve_backup(self) -> None:
        """清单只排除自身快照字段，不能连用户恢复备注和清单权限也一并忽略。"""
        for change in ("user_field", "permissions"):
            with self.subTest(change=change), tempfile.TemporaryDirectory(prefix="workflow-backup-manifest-") as raw:
                project = Path(raw).resolve() / "project"
                project.mkdir()
                with patch.object(install_workflow, "_run_setup"):
                    install_workflow._install(project, PACK)
                    install_workflow._install(project, PACK)
                    backup = next(project.glob(".agent-workflow-backup-*"))
                    manifest_path = backup / install_workflow.MANIFEST_NAME
                    if change == "user_field":
                        manifest = json.loads(manifest_path.read_bytes())
                        manifest["user_recovery_note"] = "保留这份恢复依据"
                        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
                    else:
                        manifest_path.chmod(0o600 if stat.S_IMODE(manifest_path.stat().st_mode) != 0o600 else 0o640)
                    expected_body = manifest_path.read_bytes()
                    expected_mode = stat.S_IMODE(manifest_path.stat().st_mode)
                    install_workflow._install(project, PACK)
                self.assertTrue(backup.is_dir())
                self.assertEqual(expected_body, manifest_path.read_bytes())
                self.assertEqual(expected_mode, stat.S_IMODE(manifest_path.stat().st_mode))

    def test_windows_backup_rotation_waits_for_native_acl_evidence(self) -> None:
        """模拟平台选择只验证保守分支，不能把此测试当成原生 Windows ACL 验收。"""
        with tempfile.TemporaryDirectory(prefix="workflow-backup-acl-") as raw:
            project = Path(raw).resolve()
            backup = project / ".agent-workflow-backup-0123456789ab"
            backup.mkdir()
            note = backup / "recovery.txt"
            note.write_bytes(b"keep until ACL verification exists")
            manifest_path = backup / install_workflow.MANIFEST_NAME
            manifest_path.write_bytes(b"original manifest and permissions stay untouched")
            with patch.object(install_workflow.os, "name", "nt"):
                install_workflow._record_backup_snapshot(backup)
                install_workflow._prune_runtime_backups(project, project / ".agent-workflow-backup-111111111111")
            self.assertEqual(b"keep until ACL verification exists", note.read_bytes())
            self.assertEqual(b"original manifest and permissions stay untouched", manifest_path.read_bytes())

    def test_failed_backup_record_before_or_after_write_keeps_verified_installation(self) -> None:
        """验收后的维护失败不回滚新版本；写后取消也不能把带新快照的旧目录搬回运行时。"""
        recorder = install_workflow._record_backup_snapshot
        for after_write in (False, True):
            with self.subTest(after_write=after_write), tempfile.TemporaryDirectory(prefix="workflow-backup-failure-") as raw:
                project = Path(raw).resolve() / "project"
                project.mkdir()
                with patch.object(install_workflow, "_run_setup"):
                    install_workflow._install(project, PACK)
                runtime = project / ".agent-workflow"
                original_inode = runtime.stat().st_ino
                original_manifest = (runtime / install_workflow.MANIFEST_NAME).read_bytes()

                def fail_record(backup, snapshot):
                    if after_write:
                        recorder(backup, snapshot)
                        raise KeyboardInterrupt()
                    raise OSError("cannot record backup")

                with patch.object(install_workflow, "_run_setup") as setup, \
                        patch.object(install_workflow, "_record_backup_snapshot", side_effect=fail_record), \
                        patch.object(install_workflow, "_prune_runtime_backups") as prune:
                    install_workflow._install(project, PACK)
                self.assertEqual(3, setup.call_count)  # 预检、发布、验收，没有旧版本恢复重建。
                prune.assert_not_called()
                self.assertNotEqual(original_inode, runtime.stat().st_ino)
                self.assertEqual(original_manifest, (runtime / install_workflow.MANIFEST_NAME).read_bytes())
                backup = next(project.glob(".agent-workflow-backup-*"))
                self.assertTrue((backup / "project.yaml").is_file())
                self.assertEqual([], list(project.glob(".agent-workflow-failed-*")))

    def test_special_directory_names_round_trip_through_both_doc_readers(self) -> None:
        names = ("中文 项目", 'Owner\'s "App" #1', r"Project & {{DATE}} | \\ Demo", "Project ")
        for name in names:
            with self.subTest(name=name), tempfile.TemporaryDirectory(prefix="workflow-name-scalar-") as raw:
                project = Path(raw).resolve() / name
                project.mkdir()
                with patch.object(install_workflow, "_run_setup"):
                    install_workflow._install(project, PACK)
                runtime = project / ".agent-workflow"
                config = runtime / "project.yaml"
                name_line = next(line for line in config.read_text().splitlines() if line.startswith("project_name:"))
                self.assertEqual(name, json.loads(name_line.partition(":")[2]))
                # 共享脚手架和 Antigravity 的事务发布器必须解出相同文字，不能留下
                # YAML/JSON 转义符，不能把 # 当名称外的注释，也不能裁掉名称尾部空格。
                script = 'source "$1/lib/common.sh" && py_yaml "$2" project_name'
                shared = subprocess.run(
                    ["bash", "-c", script, "project-name-test", str(runtime), str(config)],
                    capture_output=True, text=True, check=False, timeout=15,
                )
                self.assertEqual(0, shared.returncode, shared.stderr)
                self.assertEqual(name + "\n", shared.stdout)
                antigravity = subprocess.run(
                    ["bash", str(runtime / "lib/python_runtime.sh"), "-c",
                     "import sys; from pathlib import Path; sys.path.insert(0, sys.argv[1]); "
                     "from apply_antigravity_setup import _parse_project_values; "
                     "print(_parse_project_values(Path(sys.argv[2]))['project_name'])",
                     str(runtime / "lib"), str(config)],
                    capture_output=True, text=True, check=False, timeout=15,
                )
                self.assertEqual(0, antigravity.returncode, antigravity.stderr)
                self.assertEqual(name + "\n", antigravity.stdout)

    def test_preflight_failure_leaves_existing_name_and_runtime_unchanged(self) -> None:
        with tempfile.TemporaryDirectory(prefix="workflow-name-preflight-") as raw:
            project = Path(raw).resolve() / "ParentsKit"
            project.mkdir()
            with patch.object(install_workflow, "_run_setup"):
                install_workflow._install(project, PACK)
            config = project / ".agent-workflow/project.yaml"
            original = (PACK / "project.yaml").read_bytes()
            config.write_bytes(original)
            # 初始化只发生在尚未发布的暂存配置；失败不能提前写入项目现有配置。
            with patch.object(install_workflow, "_run_setup", side_effect=subprocess.CalledProcessError(7, "preflight")):
                with self.assertRaises(subprocess.CalledProcessError):
                    install_workflow._install(project, PACK)
            self.assertEqual(original, config.read_bytes())
            self.assertEqual([], list(project.glob(".agent-workflow-stage-*")))
            self.assertEqual([], list(project.glob(".agent-workflow-backup-*")))


class DetachedInstallTest(unittest.TestCase):
    def test_existing_path_with_apostrophe_is_not_reparsed(self) -> None:
        """参数形式的真实路径允许文件夹名含单引号。"""

        with tempfile.TemporaryDirectory(prefix="workflow-quoted-path-") as raw:
            project = Path(raw) / "Owner's Project"
            project.mkdir()
            self.assertEqual(project.resolve(), install_workflow._target_path(str(project), PACK))

    def test_dragged_path_preserves_escaped_trailing_space(self) -> None:
        """终端拖入路径时不能把文件夹名末尾的空格裁掉。"""

        with tempfile.TemporaryDirectory(prefix="workflow-trailing-space-") as raw:
            project = Path(raw) / "Project "
            project.mkdir()
            dragged = str(project).replace(" ", "\\ ")
            self.assertEqual(project.resolve(), install_workflow._target_path(dragged, PACK))

    def test_old_in_project_pack_requires_explicit_removal(self) -> None:
        """新入口拒绝和旧项目内安装包形成双工作流。"""

        with tempfile.TemporaryDirectory(prefix="workflow-old-pack-") as raw:
            project = Path(raw) / "project"
            old_pack = project / "agent_workflow"
            (old_pack / "product").mkdir(parents=True)
            (old_pack / "setup_all.sh").write_text("#!/bin/bash\n", encoding="utf-8")
            (old_pack / "product/WORKFLOW.md").write_text("old\n", encoding="utf-8")
            with self.assertRaisesRegex(install_workflow.InstallError, "旧工作流目录"):
                install_workflow._install(project, PACK)
            self.assertFalse((project / ".agent-workflow").exists())

    def test_first_install_failure_keeps_runtime_path(self) -> None:
        """首次发布失败后保留宿主入口会引用的运行时路径。"""

        with tempfile.TemporaryDirectory(prefix="workflow-first-failure-") as raw:
            # 与 CLI 的 _target_path 保持一致：macOS 的 /var 临时目录需先解析为真实路径。
            project = Path(raw).resolve() / "project"
            project.mkdir()
            # 模拟预检成功、随后宿主生成失败；此时不能把运行时改名为
            # failed 目录，否则已经生成的入口会指向不存在的路径。
            setup_failure = subprocess.CalledProcessError(7, "setup_all.sh")
            with patch.object(
                install_workflow,
                "_run_setup",
                side_effect=[None, setup_failure],
            ):
                with self.assertRaises(install_workflow.InstallError):
                    install_workflow._install(project, PACK)
            self.assertTrue((project / ".agent-workflow/setup_all.sh").is_file())
            self.assertEqual([], list(project.glob(".agent-workflow-failed-*")))

    def test_terminal_drag_install_survives_source_removal(self) -> None:
        """拖入带空格的目录后，三平台产物只依赖项目内隐藏运行时。"""

        with tempfile.TemporaryDirectory(prefix="workflow-detached-install-") as raw:
            workspace = Path(raw)
            source = workspace / "downloaded workflow pack"
            project = workspace / "Project With Spaces"
            shutil.copytree(
                PACK,
                source,
                ignore=shutil.ignore_patterns("tests", "__pycache__", "*.pyc"),
            )
            project.mkdir()
            (project / "package.json").write_text(
                '{"name":"detached-fixture","dependencies":{"react":"19"},'
                '"scripts":{"build":"echo build"}}\n',
                encoding="utf-8",
            )
            (project / "src").mkdir()
            (project / "src/App.jsx").write_text(
                "export function App() { return null; }\n", encoding="utf-8"
            )
            source_config = (source / "project.yaml").read_bytes()

            # 终端拖入目录通常粘贴反斜杠转义的空格；通过 stdin 验证交互入口。
            dragged = str(project).replace(" ", "\\ ") + "\n"
            installed = subprocess.run(
                ["bash", str(source / "install.sh")],
                input=dragged,
                text=True,
                capture_output=True,
                cwd=workspace,
                check=False,
            )
            self.assertEqual(0, installed.returncode, installed.stdout + installed.stderr)

            runtime = project / ".agent-workflow"
            self.assertIn('project_name: "Project With Spaces"', (runtime / "project.yaml").read_text())
            self.assertIn("# Project — Project With Spaces", (project / "docs/PROJECT.md").read_text())
            self.assertEqual(source_config, (source / "project.yaml").read_bytes())
            self.assertTrue((runtime / "setup_all.sh").is_file())
            self.assertTrue((runtime / ".install-manifest.json").is_file())
            # UI Agent 从受管运行时读取模板；源包删除后不能丢失 HTML 或共享样式。
            for name in ("page.html", "prototype.css", "index.html"):
                self.assertEqual((source / "templates/prototype" / name).read_bytes(),
                                 (runtime / "templates/prototype" / name).read_bytes())
            self.assertFalse((runtime / "tests").exists())
            self.assertFalse((runtime / "lib/install_workflow.py").exists())
            self.assertTrue((project / "AGENTS.md").is_file())
            self.assertEqual((project / "CLAUDE.md").read_bytes(), b"@AGENTS.md\n")
            self.assertTrue((project / ".agents/skills/xy-workflow/SKILL.md").is_file())
            self.assertTrue((project / ".claude/skills/xy-workflow/SKILL.md").is_file())
            self.assertTrue((project / ".codex/agents/xy-qa.toml").is_file())
            self.assertTrue((project / ".codex/agents/xy-web.toml").is_file())
            # 三个宿主的设计角色都必须指向留下来的模板，而不是可删除的源包目录。
            codex_ui = tomllib.loads((project / ".codex/agents/xy-uiux.toml").read_text())
            ui_bodies = {
                "codex": codex_ui["developer_instructions"],
                "claude": (project / ".claude/agents/xy-uiux.md").read_text(),
                "antigravity": (project / ".agents/agents/xy-uiux.md").read_text(),
            }
            for host, body in ui_bodies.items():
                with self.subTest(host=host):
                    self.assertIn(".agent-workflow/templates/prototype/page.html", body)
            for relative in (
                "AGENTS.md",
                "CLAUDE.md",
                ".agents/skills/xy-workflow/SKILL.md",
                ".claude/skills/xy-workflow/SKILL.md",
                ".codex/agents/xy-qa.toml",
            ):
                body = (project / relative).read_text(encoding="utf-8")
                self.assertNotIn("agent_workflow/", body, relative)

            # 同一入口也可升级已安装项目；项目专属配置保留，旧运行时留作备份。
            project_config_path = runtime / "project.yaml"
            project_config_path.write_bytes(
                project_config_path.read_bytes() + b"\n# project-owned setting\n"
            )
            project_config = project_config_path.read_bytes()
            # 模拟上一版仅含 AGENTS.md 的安装：升级应只补薄入口，正文保持一致。
            original_agents = (project / "AGENTS.md").read_bytes()
            (project / "CLAUDE.md").unlink()
            upgraded = subprocess.run(
                ["bash", str(source / "install.sh"), str(project)],
                text=True,
                capture_output=True,
                cwd=workspace,
                check=False,
            )
            self.assertEqual(0, upgraded.returncode, upgraded.stdout + upgraded.stderr)
            self.assertEqual(project_config, project_config_path.read_bytes())
            self.assertEqual(original_agents, (project / "AGENTS.md").read_bytes())
            self.assertEqual((project / "CLAUDE.md").read_bytes(), b"@AGENTS.md\n")
            self.assertEqual(1, len(list(project.glob(".agent-workflow-backup-*"))))

            # 项目手工修改过受管运行时后，升级必须拒绝覆盖并保留现状。
            workflow = runtime / "product/WORKFLOW.md"
            original_workflow = workflow.read_bytes()
            workflow.write_bytes(original_workflow + b"\n# local edit\n")
            blocked = subprocess.run(
                ["bash", str(source / "install.sh"), str(project)],
                text=True,
                capture_output=True,
                cwd=workspace,
                check=False,
            )
            self.assertEqual(2, blocked.returncode)
            self.assertIn("受管文件", blocked.stderr)
            self.assertEqual(original_workflow + b"\n# local edit\n", workflow.read_bytes())
            workflow.write_bytes(original_workflow)

            shutil.rmtree(source)
            checked = subprocess.run(
                ["bash", str(runtime / "setup_all.sh"), "--check"],
                text=True,
                capture_output=True,
                cwd=project,
                check=False,
            )
            self.assertEqual(0, checked.returncode, checked.stdout + checked.stderr)
            self.assertTrue((runtime / "templates/prototype/page.html").is_file())
            for cli in ("task_graph_cli.py", "qa_handoff_cli.py"):
                with self.subTest(cli=cli):
                    result = subprocess.run(
                        [
                            "bash",
                            str(runtime / "lib/python_runtime.sh"),
                            str(runtime / "lib" / cli),
                            "--help",
                        ],
                        text=True,
                        capture_output=True,
                        cwd=project,
                        check=False,
                    )
                    self.assertEqual(0, result.returncode, result.stdout + result.stderr)

    def test_failed_upgrade_restores_entry_before_running_original_setup(self) -> None:
        """验收失败后先恢复升级前的入口字节和权限，不能让旧生成器处理新产物。"""
        for original in (None, b"previous managed entry\n", b"@AGENTS.md\n"):
            with self.subTest(original=original), tempfile.TemporaryDirectory(prefix="workflow-entry-rollback-") as raw:
                project = Path(raw).resolve() / "project"
                project.mkdir()
                with patch.object(install_workflow, "_run_setup"):
                    install_workflow._install(project, PACK)
                # 升级失败时也要恢复仍含占位名的旧配置，不能泄漏暂存初始化结果。
                config = project / ".agent-workflow/project.yaml"
                old_config = (PACK / "project.yaml").read_bytes()
                config.write_bytes(old_config)
                entry = project / "CLAUDE.md"
                if original is not None:
                    entry.write_bytes(original)
                    entry.chmod(0o600)
                calls = []

                def run_setup(runtime, target, *options):
                    calls.append(options)
                    if len(calls) == 2:
                        entry.write_bytes(b"@AGENTS.md\n")
                    elif len(calls) == 3:
                        raise subprocess.CalledProcessError(7, "setup_all.sh --check")
                    elif len(calls) >= 4:
                        # 原生成器只能看到升级前的入口，而不是被迫兼容新版薄入口。
                        self.assertEqual(entry.read_bytes() if entry.exists() else None, original)
                        self.assertEqual(old_config, config.read_bytes())
                        if original is not None:
                            self.assertEqual(stat.S_IMODE(entry.stat().st_mode), 0o600)

                with patch.object(install_workflow, "_run_setup", side_effect=run_setup):
                    with self.assertRaisesRegex(install_workflow.InstallError, "安装或验收失败"):
                        install_workflow._install(project, PACK)
                self.assertEqual(calls, [("--preflight",), (), ("--check",), (), ("--check",)])
                self.assertEqual(old_config, config.read_bytes())
                self.assertTrue((project / ".agent-workflow/setup_all.sh").is_file())
                self.assertEqual(1, len(list(project.glob(".agent-workflow-failed-*"))))
                self.assertEqual([], list(project.glob(".agent-workflow-backup-*")))

    def test_failed_upgrade_preserves_concurrent_user_entry(self) -> None:
        """升级期间用户改过入口时不自动覆盖，也不继续运行会写入口的恢复脚本。"""
        with tempfile.TemporaryDirectory(prefix="workflow-entry-concurrent-") as raw:
            project = Path(raw).resolve() / "project"
            project.mkdir()
            with patch.object(install_workflow, "_run_setup"):
                install_workflow._install(project, PACK)
            entry = project / "CLAUDE.md"
            calls = []

            def run_setup(runtime, target, *options):
                calls.append(options)
                if len(calls) == 2:
                    entry.write_bytes(b"user concurrent instructions\n")
                    raise subprocess.CalledProcessError(7, "setup_all.sh")

            with patch.object(install_workflow, "_run_setup", side_effect=run_setup):
                with self.assertRaisesRegex(install_workflow.InstallError, "发生其他变更"):
                    install_workflow._install(project, PACK)
            self.assertEqual(calls, [("--preflight",), ()])
            self.assertEqual(entry.read_bytes(), b"user concurrent instructions\n")
            self.assertTrue((project / ".agent-workflow/setup_all.sh").is_file())


if __name__ == "__main__":
    unittest.main()
