"""辅助 Hooks 的行为契约：隔离临时项目，不消耗模型、不绕过宿主信任。"""

from __future__ import annotations

import copy
import json
import os
from pathlib import Path
import shlex
import shutil
import stat
import subprocess
import sys
import tempfile
import tomllib
import unittest
from unittest.mock import patch
import uuid

from lib import install_workflow
from lib import workflow_hook_install as installer
from lib import workflow_hooks as hooks
from lib.workflow_hook_settings import hook_mode

PACK = Path(__file__).resolve().parents[1]


class HookTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="workflow-hooks-")
        self.addCleanup(self.temp.cleanup)
        self.project = Path(self.temp.name).resolve() / "Owner's 项目 with spaces"
        self.project.mkdir()
        self.pack = self.project / ".agent-workflow"
        self.pack.mkdir()
        (self.pack / "project.yaml").write_text("workflow_hooks:\n  mode: assist\n")
        (self.project / "AGENTS.md").write_text("<!-- pack:product-begin -->\n")
        for host in (".agents", ".claude"):
            path = self.project / host / "skills/xy-workflow"
            path.mkdir(parents=True)
            (path / "SKILL.md").write_text("---\nname: xy-workflow\n---\n")

    def payload(self, host, **extra):
        result = {"session_id": str(uuid.uuid4()), "cwd": str(self.project),
                  "hook_event_name": "UserPromptSubmit", "prompt": "修改字，不走工作流"}
        if host == "antigravity":
            result = {"conversationId": str(uuid.uuid4()), "workspacePaths": [str(self.project)],
                      "invocationNum": 0, "initialNumSteps": 0}
        return result | extra

    def test_generated_events_are_limited_and_never_register_stop_or_permission(self):
        for host in installer.EVENTS:
            with self.subTest(host=host):
                installer.process(self.pack, self.project, host, "apply")
                path, before, after = installer.plan_hooks(self.pack, self.project, host)
                self.assertEqual(before, after)
                data = json.loads(path.read_text())
                registered = data[installer.OWNER] if host == "antigravity" else data["hooks"]
                self.assertFalse({"Stop", "PermissionRequest", "PostToolUse"} & set(registered))
                if host == "antigravity":
                    self.assertNotIn("PreToolUse", registered)

    def test_existing_native_disabled_flags_permissions_and_hooks_survive(self):
        user = {"disableAllHooks": True, "autoMemoryEnabled": False,
                "permissions": {"deny": ["Bash(rm *)"]}, "env": {"A": "keep"},
                "hooks": {"SessionStart": [{"hooks": [{"type": "command", "command": "echo user"}]}]}}
        path = self.project / ".claude/settings.json"
        path.write_text(json.dumps(user))
        path.chmod(0o600)
        installer.process(self.pack, self.project, "claude", "apply")
        data = json.loads(path.read_text())
        for key in user:
            if key != "hooks":
                self.assertEqual(user[key], data[key])
        self.assertEqual(user["hooks"]["SessionStart"][0], data["hooks"]["SessionStart"][0])
        self.assertEqual(0o600, stat.S_IMODE(path.stat().st_mode))
        stable = path.read_bytes()
        installer.process(self.pack, self.project, "claude", "apply")
        self.assertEqual(stable, path.read_bytes())
        (self.pack / "project.yaml").write_text("workflow_hooks:\n  mode: off\n")
        installer.process(self.pack, self.project, "claude", "apply")
        self.assertEqual(user, json.loads(path.read_text()))

    def test_optional_write_guard_is_independent_of_hooks_and_never_disables_native_protection(self):
        """Hooks 关闭仍可显式收紧权限；回到 inherit 及重复安装均不撤销原生保护。"""
        config = self.pack / "project.yaml"
        config.write_text("workflow_hooks:\n  mode: off\nclaude_options:\n  block_writes_outside_working_directories: true\n")
        path, before, after = installer.plan_hooks(self.pack, self.project, "claude")
        self.assertIsNone(before)
        self.assertFalse(path.exists())
        self.assertEqual({"permissions": {"blockWritesOutsideWorkingDirectories": True}}, json.loads(after))
        installer.process(self.pack, self.project, "claude", "apply")
        enabled = path.read_bytes()
        installer.process(self.pack, self.project, "claude", "check")
        config.write_text("workflow_hooks:\n  mode: off\nclaude_options:\n  block_writes_outside_working_directories: inherit\n")
        installer.process(self.pack, self.project, "claude", "apply")
        self.assertEqual(enabled, path.read_bytes())

    def test_write_guard_preserves_user_permissions_and_refuses_project_or_local_conflicts(self):
        """明确 false、错误容器都不能被覆盖；配置冲突时整个预检保持只读。"""
        (self.pack / "project.yaml").write_text("claude_options:\n  block_writes_outside_working_directories: true\n")
        target = self.project / ".claude/settings.json"
        user = {"permissions": {"deny": ["Bash(rm *)"], "additionalDirectories": ["../approved"]}, "disableAllHooks": True}
        target.write_text(json.dumps(user))
        installer.process(self.pack, self.project, "claude", "apply")
        merged = json.loads(target.read_bytes())
        self.assertEqual(user["permissions"]["deny"], merged["permissions"]["deny"])
        self.assertEqual(user["permissions"]["additionalDirectories"], merged["permissions"]["additionalDirectories"])
        self.assertTrue(merged["disableAllHooks"])
        for relative in ("settings.json", "settings.local.json"):
            for permissions in ({"blockWritesOutsideWorkingDirectories": False}, {"blockWritesOutsideWorkingDirectories": "true"}, []):
                file = target.parent / relative
                saved = file.read_bytes() if file.exists() else None
                file.write_text(json.dumps({"permissions": permissions}))
                current = {p.name: p.read_bytes() for p in target.parent.glob("*.json")}
                with self.subTest(relative=relative, permissions=permissions), self.assertRaises(ValueError):
                    installer.process(self.pack, self.project, "claude", "preflight")
                self.assertEqual(current, {p.name: p.read_bytes() for p in target.parent.glob("*.json")})
                if saved is None:
                    file.unlink()
                else:
                    file.write_bytes(saved)

    def test_write_guard_uses_existing_byte_exact_upgrade_rollback(self):
        """可选权限不创建第二份恢复机制；验收失败仍按原快照恢复用户字节和权限。"""
        other = Path(self.temp.name).resolve() / "guard-upgrade-project"
        other.mkdir()
        # 初始与恢复 setup 使用无写入夹具；升级阶段实际调用受管设置合并器发布权限。
        with patch.object(install_workflow, "_run_setup"):
            install_workflow._install(other, PACK)
        runtime = other / ".agent-workflow"
        config = runtime / "project.yaml"
        config.write_text(config.read_text().replace("block_writes_outside_working_directories: inherit", "block_writes_outside_working_directories: true"))
        old_manifest = (runtime / ".install-manifest.json").read_bytes()
        old_config = config.read_bytes()
        path = other / ".claude/settings.json"
        path.parent.mkdir()
        before = b'{ "permissions": { "deny": ["Bash(rm *)"] } }\n'
        path.write_bytes(before)
        path.chmod(0o600)
        published = False
        failed = False

        def setup(pack, project, *options):
            nonlocal published, failed
            if not options and not published:
                installer.process(pack, project, "claude", "apply")
                self.assertTrue(json.loads(path.read_bytes())["permissions"]["blockWritesOutsideWorkingDirectories"])
                published = True
            elif options == ("--check",) and not failed:
                failed = True
                raise install_workflow.InstallError("injected verification failure")

        with patch.object(install_workflow, "_run_setup", side_effect=setup):
            with self.assertRaises(install_workflow.InstallError):
                install_workflow._install(other, PACK)
        self.assertTrue(published and failed)
        self.assertEqual(before, path.read_bytes())
        self.assertEqual(0o600, stat.S_IMODE(path.stat().st_mode))
        self.assertEqual(old_config, config.read_bytes())
        self.assertEqual(old_manifest, (runtime / ".install-manifest.json").read_bytes())

    def test_agy_user_hook_and_native_disabled_owned_entry_survive(self):
        path = self.project / ".agents/hooks.json"
        custom = {"custom": {"Stop": [{"command": "echo user"}], "enabled": False}}
        path.write_text(json.dumps(custom))
        installer.process(self.pack, self.project, "antigravity", "apply")
        data = json.loads(path.read_text())
        data[installer.OWNER]["enabled"] = False
        path.write_text(json.dumps(data))
        installer.process(self.pack, self.project, "antigravity", "apply")
        self.assertFalse(json.loads(path.read_text())[installer.OWNER]["enabled"])
        (self.pack / "project.yaml").write_text("workflow_hooks:\n  mode: off\n")
        installer.process(self.pack, self.project, "antigravity", "apply")
        self.assertEqual(custom, json.loads(path.read_text()))

    def test_agy_upgrades_only_signed_legacy_event_and_preserves_disabled_state(self):
        """原生事件升级只迁移本包有效签名，不能借迁移覆盖用户编辑或打开禁用条目。"""
        legacy = installer.signed_group(self.pack, self.project, "antigravity", "PreInvocation", "")
        user = {"user-hook": {"PreInvocation": [{"command": "echo keep"}]},
                installer.OWNER: {"enabled": False, "PreInvocation": [legacy]}}
        updated = installer.merge_json(user, self.pack, self.project, "antigravity", "assist")
        self.assertEqual(user["user-hook"], updated["user-hook"])
        self.assertEqual({"enabled", "SessionStart"}, set(updated[installer.OWNER]))
        self.assertFalse(updated[installer.OWNER]["enabled"])
        self.assertEqual(updated, installer.merge_json(updated, self.pack, self.project, "antigravity", "assist"))
        for mutation in ("timeout", "unknown_event"):
            altered = copy.deepcopy(user)
            if mutation == "timeout":
                altered[installer.OWNER]["PreInvocation"][0]["timeout"] = 99
            else:
                altered[installer.OWNER]["Stop"] = [{"command": "echo user"}]
            before = copy.deepcopy(altered)
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                installer.merge_json(altered, self.pack, self.project, "antigravity", "assist")
            self.assertEqual(before, altered)

    def test_codex_inline_uses_same_source_preserving_user_toml_and_disabled_flag(self):
        path = self.project / ".codex/config.toml"
        path.parent.mkdir()
        user = ('# 用户配置\n[features]\nhooks = false\n[[hooks.SessionStart]]\n'
                'matcher = "startup"\n[[hooks.SessionStart.hooks]]\n'
                'type = "command"\ncommand = "echo user"\n')
        path.write_text(user)
        installer.process(self.pack, self.project, "codex", "apply")
        data = tomllib.loads(path.read_text())
        self.assertFalse(data["features"]["hooks"])
        self.assertEqual(2, len(data["hooks"]["SessionStart"]))
        self.assertTrue(path.read_text().startswith(user))
        self.assertFalse((path.parent / "hooks.json").exists())
        installer.process(self.pack, self.project, "codex", "check")
        (self.pack / "project.yaml").write_text("workflow_hooks:\n  mode: off\n")
        installer.process(self.pack, self.project, "codex", "apply")
        self.assertEqual(user, path.read_text())

    def test_codex_agents_and_inline_hooks_stable_and_snapshot_projects_limit_change(self):
        from lib.merge_codex_config import merge
        path = self.project / ".codex/config.toml"
        path.parent.mkdir()
        path.write_text('[[hooks.SessionStart]]\n[[hooks.SessionStart.hooks]]\n'
                        'type = "command"\ncommand = "echo user"\n')
        merge(path, 8)
        installer.process(self.pack, self.project, "codex", "apply")
        stable = path.read_bytes()
        for _ in range(3):
            merge(path, 8)
            installer.process(self.pack, self.project, "codex", "apply")
            self.assertEqual(stable, path.read_bytes())
        (self.pack / "project.yaml").write_text("workflow_hooks:\n  mode: assist\norchestration:\n  max_concurrent_subagents: 9\n")
        _, before, predicted = installer.plan_hooks(self.pack, self.project, "codex", simulate_codex_setup=True)
        merge(path, 9)
        installer.process(self.pack, self.project, "codex", "apply")
        self.assertEqual(predicted, path.read_bytes())
        install_workflow._restore_hook_configs([(path, before, predicted, 0o644)])
        self.assertEqual(stable, path.read_bytes())

    def test_native_codex_and_inline_hook_are_published_once_with_no_intermediate_state(self):
        from lib.merge_codex_config import merge
        path = self.project / ".codex/config.toml"
        path.parent.mkdir()
        path.write_text('[[hooks.SessionStart]]\n[[hooks.SessionStart.hooks]]\n'
                        'type = "command"\ncommand = "echo user"\n')
        merge(path, 8)
        before = path.read_bytes()
        (self.pack / "project.yaml").write_text("workflow_hooks:\n  mode: assist\norchestration:\n  max_concurrent_subagents: 9\n")
        _, original, predicted = installer.plan_hooks(self.pack, self.project, "codex", simulate_codex_setup=True)
        with patch.object(installer, "atomic_write", wraps=installer.atomic_write) as publish:
            installer.process(self.pack, self.project, "codex", "apply-codex-config")
            self.assertEqual(1, publish.call_count)
        self.assertEqual(predicted, path.read_bytes())
        self.assertEqual(9, tomllib.loads(path.read_text())["agents"]["max_concurrent_threads_per_session"])
        install_workflow._restore_hook_configs([(path, original, predicted, 0o644)])
        self.assertEqual(before, path.read_bytes())

    def test_preflight_is_read_only_and_off_creates_no_config(self):
        installer.process(self.pack, self.project, "claude", "preflight")
        self.assertFalse((self.project / ".claude/settings.json").exists())
        (self.pack / "project.yaml").write_text("workflow_hooks:\n  mode: off\n")
        for host in installer.EVENTS:
            installer.process(self.pack, self.project, host, "apply")
        self.assertFalse((self.project / ".claude/settings.json").exists())
        self.assertFalse((self.project / ".codex").exists())
        self.assertFalse((self.project / ".agents/hooks.json").exists())

    def test_signed_managed_edits_and_mixed_groups_are_not_overwritten(self):
        installer.process(self.pack, self.project, "claude", "apply")
        path = self.project / ".claude/settings.json"
        original = json.loads(path.read_text())
        for mutation in ("timeout", "mixed", "command"):
            data = copy.deepcopy(original)
            group = data["hooks"]["SessionStart"][0]
            if mutation == "timeout":
                group["hooks"][0]["timeout"] = 99
            elif mutation == "mixed":
                group["hooks"].append({"type": "command", "command": "echo user"})
            else:
                group["hooks"][0]["command"] += " && echo user"
            path.write_text(json.dumps(data))
            before = path.read_bytes()
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                installer.process(self.pack, self.project, "claude", "apply")
            self.assertEqual(before, path.read_bytes())

    def test_symlinks_hardlinks_duplicate_keys_and_named_conflicts_fail_preflight(self):
        path = self.project / ".claude/settings.json"
        outside = self.project / "keep.json"
        outside.write_text("{}")
        path.symlink_to(outside)
        with self.assertRaises(ValueError):
            installer.process(self.pack, self.project, "claude", "preflight")
        path.unlink()
        os.link(outside, path)
        with self.assertRaises(ValueError):
            installer.process(self.pack, self.project, "claude", "preflight")
        path.unlink()
        path.write_text('{"permissions":{},"permissions":{"deny":["all"]}}')
        with self.assertRaises(ValueError):
            installer.process(self.pack, self.project, "claude", "preflight")
        path = self.project / ".agents/hooks.json"
        path.write_text(json.dumps({installer.OWNER: {"PreInvocation": [{"command": "echo user"}]}}))
        with self.assertRaises(ValueError):
            installer.process(self.pack, self.project, "antigravity", "preflight")

    def test_activation_does_not_classify_or_force_qa_for_any_user_request(self):
        requests = ("解释代码", "把提交改成保存", "不走工作流直接修改", "主会话亲自实现",
                    "不更新原型", "任务A已完成，接着做B", "开发五个模块")
        for host in ("codex", "claude"):
            for request in requests:
                payload = self.payload(host, prompt=request)
                data = hooks.response(host, "UserPromptSubmit", payload, self.project)
                self.assertEqual(hooks.ENTRY, data["hookSpecificOutput"]["additionalContext"])
                self.assertFalse({"decision", "continue", "permissionDecision"} & set(data))
        # 提示词不经过关键词分类，且提醒不含原始用户内容或复制的正文。
        self.assertIn("用户明确跳过", hooks.ENTRY)
        self.assertIn("已完成", hooks.ENTRY)
        self.assertLess(len(hooks.ENTRY), 250)

    def test_recovery_only_restores_missing_context_and_startup_is_quiet(self):
        for host in ("codex", "claude"):
            for source in ("resume", "compact", "clear"):
                data = hooks.response(host, "SessionStart", self.payload(
                    host, hook_event_name="SessionStart", source=source), self.project)
                self.assertEqual(hooks.RECOVERY, data["hookSpecificOutput"]["additionalContext"])
            self.assertEqual({}, hooks.response(host, "SessionStart", self.payload(
                host, hook_event_name="SessionStart", source="startup"), self.project))
        fork = self.payload("codex", hook_event_name="SessionStart", source="fork")
        self.assertEqual(hooks.RECOVERY, hooks.response("codex", "SessionStart", fork, self.project)
                         ["hookSpecificOutput"]["additionalContext"])
        self.assertIn("fork", installer.EVENTS["codex"][0][1])

    def test_explore_progress_notice_is_conditional_and_does_not_block_other_agents(self):
        event = self.payload("claude", hook_event_name="PreToolUse", tool_name="Agent",
                             tool_input={"subagent_type": "Explore"})
        data = hooks.response("claude", "PreToolUse", event, self.project)
        self.assertEqual(hooks.DISPATCH, data["hookSpecificOutput"]["additionalContext"])
        self.assertNotIn("permissionDecision", data["hookSpecificOutput"])
        event["tool_input"]["subagent_type"] = "xy-backend"
        self.assertEqual({}, hooks.response("claude", "PreToolUse", event, self.project))
        for name in ("Edit", "Write", "Read", "Bash"):
            event["tool_name"] = name
            self.assertEqual({}, hooks.response("claude", "PreToolUse", event, self.project))

    def test_agy_session_start_uses_native_lifecycle_without_cache_or_prompt_inspection(self):
        """一次性由宿主事件保证，本工具不再依靠每轮模型调用及磁盘去重猜测会话启动。"""
        event = self.payload("antigravity")
        before = {str(path) for path in Path(self.temp.name).rglob("*")}
        result = hooks.response("antigravity", "SessionStart", event | {"userMessage": "SECRET"}, self.project)
        self.assertEqual({"injectSteps": [{"ephemeralMessage": hooks.ENTRY}]}, result)
        self.assertNotIn("SECRET", json.dumps(result))
        for number in (1, 5, 100, 0):
            self.assertEqual({}, hooks.response("antigravity", "PreInvocation", event |
                                               {"invocationNum": number}, self.project))
        self.assertEqual(before, {str(path) for path in Path(self.temp.name).rglob("*")})

    def test_wrong_workspace_missing_identity_and_multiroot_are_neutral(self):
        other = Path(self.temp.name) / "other"
        other.mkdir()
        (other / "AGENTS.md").write_text("user project")
        for host in ("codex", "claude"):
            self.assertEqual({}, hooks.response(host, "UserPromptSubmit",
                             self.payload(host, cwd=str(other)), self.project))
        for paths in ([], [str(self.project), str(other)], [str(other)]):
            self.assertEqual({}, hooks.response("antigravity", "SessionStart",
                self.payload("antigravity", workspacePaths=paths), self.project))
        self.assertEqual({}, hooks.response("antigravity", "SessionStart",
                self.payload("antigravity", conversationId=None), self.project))

    def test_nested_cwd_and_worktrees_use_actual_root_not_nested_project(self):
        def git(*args):
            return subprocess.run(["git", *args], capture_output=True, text=True, check=True)
        git("-C", str(self.project), "init", "-q")
        git("-C", str(self.project), "-c", "user.name=Test", "-c", "user.email=test@example.invalid",
            "commit", "--allow-empty", "-qm", "initial")
        sub = self.project / "src"
        sub.mkdir()
        self.assertEqual(self.project, hooks.scoped_root("codex", {"cwd": str(sub)}, self.project))
        (sub / "AGENTS.md").write_text("nested project")
        self.assertIsNone(hooks.scoped_root("codex", {"cwd": str(sub)}, self.project))
        worktree = Path(self.temp.name).resolve() / "worktree"
        git("-C", str(self.project), "worktree", "add", "--detach", str(worktree), "HEAD")
        (worktree / "AGENTS.md").write_text("worktree rules")
        self.assertEqual(worktree, hooks.scoped_root("codex", {"cwd": str(worktree)}, self.project))

    def test_off_env_unknown_and_stop_events_are_neutral(self):
        event = self.payload("codex")
        with patch.dict(os.environ, {"AGENT_WORKFLOW_HOOKS": "off"}):
            self.assertEqual({}, hooks.response("codex", "UserPromptSubmit", event, self.project))
        for name in ("Stop", "PermissionRequest", "PostToolUse", "Unknown"):
            self.assertEqual({}, hooks.response("codex", name, event | {"hook_event_name": name}, self.project))
        (self.pack / "project.yaml").write_text("workflow_hooks:\n  mode: off\n")
        self.assertEqual({}, hooks.response("codex", "UserPromptSubmit", event, self.project))

    def test_cli_bad_payload_fails_neutrally_without_echoing_secrets(self):
        for data in ("not-json-secret", "[]", '{"prompt":"SECRET"', "x" * (1024 * 1024 + 1)):
            args = [sys.executable, "-B", str(PACK / "lib/workflow_hooks.py"),
                    "--host", "claude", "--event", "UserPromptSubmit", "--project", str(self.project),
                    "--owner", hooks.OWNER, "--signature", "0" * 64]
            result = subprocess.run(args, input=data, text=True, capture_output=True, timeout=3)
            self.assertEqual(0, result.returncode)
            self.assertEqual({}, json.loads(result.stdout))
            self.assertNotIn("SECRET", result.stderr)
            self.assertNotIn("not-json-secret", result.stderr)

    def test_invalid_mode_and_config_shape_have_no_silent_enforce_mode(self):
        for text in ("workflow_hooks: false", "workflow_hooks:\n  mode: enforce\n",
                     "workflow_hooks:\n  mode: off\n  mode: assist\n",
                     "workflow_hooks:\n  task: Full\n",
                     "workflow_hooks:\n  mode: off\nworkflow_hooks:\n  mode: assist\n"):
            with self.subTest(text=text), self.assertRaises(ValueError):
                hook_mode(text)

    def test_upgrade_restore_only_reverts_exact_owned_output_not_concurrent_user_settings(self):
        path = self.project / ".claude/settings.json"
        before = b'{"permissions":{"deny":["all"]}}\n'
        after = b'{"permissions":{"deny":["all"]},"hooks":{}}\n'
        path.write_bytes(after)
        install_workflow._restore_hook_configs([(path, before, after, 0o600)])
        self.assertEqual(before, path.read_bytes())
        self.assertEqual(0o600, stat.S_IMODE(path.stat().st_mode))
        path.write_bytes(b'{"user-concurrent":true}\n')
        with self.assertRaises(install_workflow.InstallError):
            install_workflow._restore_hook_configs([(path, before, after, 0o600)])
        self.assertEqual(b'{"user-concurrent":true}\n', path.read_bytes())

    def test_upgrade_snapshot_failure_restores_runtime_without_touching_user_settings(self):
        # 模拟完成过的安装与预检后新增的用户配置；快照 ValueError 不能留下新版运行时。
        other = Path(self.temp.name).resolve() / "upgrade-project"
        other.mkdir()
        with patch.object(install_workflow, "_run_setup"):
            install_workflow._install(other, PACK)
        settings = other / ".claude/settings.json"
        settings.parent.mkdir()
        settings.write_bytes(b'{"user-edit":true}\n')
        before = (other / ".agent-workflow/.install-manifest.json").read_bytes()
        with patch.object(install_workflow, "_run_setup") as setup, patch.object(
                install_workflow, "plan_hooks", side_effect=ValueError("concurrent invalid configuration")):
            with self.assertRaisesRegex(install_workflow.InstallError, "发布前准备失败"):
                install_workflow._install(other, PACK)
            self.assertEqual(1, setup.call_count)
        self.assertEqual(before, (other / ".agent-workflow/.install-manifest.json").read_bytes())
        self.assertEqual(b'{"user-edit":true}\n', settings.read_bytes())
        self.assertEqual([], list(other.glob(".agent-workflow-backup-*")))

    def test_agy_hook_rollback_does_not_overwrite_published_concurrent_edit(self):
        # applier 采用原有按路径事务接口；只构造配置变化，避免昂贵且无关的模块发现。
        library = str(PACK / "lib")
        sys.path.insert(0, library)
        self.addCleanup(lambda: sys.path.remove(library))
        import apply_antigravity_setup as applier
        path = self.project / ".agents/hooks.json"
        path.write_bytes(b'{"user":true}\n')
        plan = applier.Plan(self.pack, self.project, self.project, "rollback-test")
        before = applier._fingerprint(path)
        change = applier.FileChange(path, b'{"user":true,"managed":true}\n', 0o644, before)
        plan.hook_changes.append(change)
        applier._publish_file(change, plan)
        path.write_bytes(b'{"user-concurrent":true}\n')
        with self.assertRaisesRegex(applier.ApplyError, "preserved current file"):
            applier._rollback(plan)
        self.assertEqual(b'{"user-concurrent":true}\n', path.read_bytes())
        self.assertIsNotNone(change.backup)
        self.assertEqual(b'{"user":true}\n', change.backup.read_bytes())

    def test_agy_unpublished_hook_does_not_delete_concurrent_new_file(self):
        library = str(PACK / "lib")
        sys.path.insert(0, library)
        self.addCleanup(lambda: sys.path.remove(library))
        import apply_antigravity_setup as applier
        path = self.project / ".agents/hooks.json"
        plan = applier.Plan(self.pack, self.project, self.project, "unpublished-test")
        plan.hook_changes.append(applier.FileChange(path, b'{"managed":true}\n', 0o644,
                                                  applier.Fingerprint("missing")))
        path.write_bytes(b'{"user-created":true}\n')
        applier._rollback(plan)
        self.assertEqual(b'{"user-created":true}\n', path.read_bytes())


class InstalledCallbackTest(unittest.TestCase):
    def test_real_install_keeps_inline_codex_and_user_agy_hooks_and_reinstalls(self):
        """已有用户配置时走真实三平台安装/再安装，不把用户 Hooks 当受管目录删除。"""
        with tempfile.TemporaryDirectory(prefix="workflow-hook-user-config-") as raw:
            project = Path(raw).resolve() / "project"
            project.mkdir()
            source = Path(raw).resolve() / "source"
            shutil.copytree(PACK, source, ignore=shutil.ignore_patterns("tests", "__pycache__", ".DS_Store"))
            (project / ".codex").mkdir()
            codex = project / ".codex/config.toml"
            codex.write_text('[features]\nhooks = false\n[[hooks.SessionStart]]\n'
                             '[[hooks.SessionStart.hooks]]\ntype = "command"\ncommand = "echo user"\n')
            (project / ".agents").mkdir()
            agy = project / ".agents/hooks.json"
            user = {"user-linter": {"enabled": False, "PostToolUse": [{"matcher": "run_command",
                                 "hooks": [{"command": "echo keep"}]}]}}
            agy.write_text(json.dumps(user))
            (project / ".claude").mkdir()
            claude = project / ".claude/settings.json"
            claude.write_text('{"autoMemoryEnabled":false,"disableAllHooks":true}')
            installed = subprocess.run(["bash", str(source / "install.sh"), str(project)],
                                       capture_output=True, text=True, timeout=120)
            self.assertEqual(0, installed.returncode, installed.stdout + installed.stderr)
            runtime = project / ".agent-workflow"
            for attempt in range(2):
                result = subprocess.run(["bash", str(runtime / "setup_all.sh")],
                                        capture_output=True, text=True, timeout=120)
                self.assertEqual(0, result.returncode, result.stdout + result.stderr)
                self.assertFalse((project / ".codex/hooks.json").exists())
                parsed = tomllib.loads(codex.read_text())
                self.assertFalse(parsed["features"]["hooks"])
                self.assertEqual(2, len(parsed["hooks"]["SessionStart"]))
                self.assertEqual(user["user-linter"], json.loads(agy.read_text())["user-linter"])
                self.assertTrue(json.loads(claude.read_text())["disableAllHooks"])
                self.assertFalse(json.loads(claude.read_text())["autoMemoryEnabled"])
            before = agy.read_bytes()
            agents = {path.name: path.read_bytes() for path in (project / ".agents/agents").iterdir()}
            result = subprocess.run(["bash", str(runtime / "setup_antigravity.sh")],
                                    env=os.environ | {"AGENT_WORKFLOW_PACK_TEST_FAILPOINT": "antigravity-generated-validator-failure"},
                                    capture_output=True, text=True, timeout=120)
            self.assertNotEqual(0, result.returncode)
            self.assertEqual(before, agy.read_bytes())
            self.assertEqual(agents, {path.name: path.read_bytes() for path in (project / ".agents/agents").iterdir()})

    def test_all_installed_commands_execute_protocol_after_source_is_removed(self):
        """真实安装、删除源包副本、回调执行；不是对模型行为或信任的冒充验证。"""
        with tempfile.TemporaryDirectory(prefix="workflow-hook-installed-") as raw:
            base = Path(raw).resolve()
            source, project = base / "source", base / "项目 with spaces"
            shutil.copytree(PACK, source, ignore=shutil.ignore_patterns("tests", "__pycache__", ".DS_Store"))
            project.mkdir()
            result = subprocess.run(["bash", str(source / "install.sh"), str(project)],
                                    capture_output=True, text=True, timeout=120)
            self.assertEqual(0, result.returncode, result.stdout + result.stderr)
            shutil.rmtree(source)
            for host, relative in (("codex", ".codex/hooks.json"), ("claude", ".claude/settings.json"),
                                   ("antigravity", ".agents/hooks.json")):
                data = json.loads((project / relative).read_text())
                if host == "antigravity":
                    event = "SessionStart"
                    handler = data[hooks.OWNER][event][0]
                    payload = {"conversationId": str(uuid.uuid4()), "workspacePaths": [str(project)]}
                else:
                    event = "UserPromptSubmit"
                    handler = data["hooks"][event][0]["hooks"][0]
                    payload = {"session_id": str(uuid.uuid4()), "cwd": str(project), "hook_event_name": event}
                call = subprocess.run(shlex.split(handler["command"]), input=json.dumps(payload),
                                      text=True, capture_output=True, cwd=project, timeout=3)
                self.assertEqual(0, call.returncode, call.stderr)
                parsed = json.loads(call.stdout)
                if host == "antigravity":
                    self.assertEqual(hooks.ENTRY, parsed["injectSteps"][0]["ephemeralMessage"])
                else:
                    self.assertEqual(hooks.ENTRY, parsed["hookSpecificOutput"]["additionalContext"])
            checked = subprocess.run(["bash", str(project / ".agent-workflow/setup_all.sh"), "--check"],
                                     capture_output=True, text=True, timeout=120)
            self.assertEqual(0, checked.returncode, checked.stdout + checked.stderr)


if __name__ == "__main__":
    unittest.main()
