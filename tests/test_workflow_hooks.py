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

from lib.install import install_workflow
from lib.hosts import workflow_hook_install as installer
from lib import workflow_hooks as hooks
from lib.hosts.workflow_hook_settings import hook_mode

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
        # 即使历史事件具有合法签名，当前合并器也不负责转换它；必须保留并拒绝。
        old = {installer.OWNER: {"enabled": False, "PreInvocation": [
            installer.signed_group(self.pack, self.project, "antigravity", "PreInvocation", "")]}}
        original = json.dumps(old).encode()
        path.write_bytes(original)
        with self.assertRaisesRegex(ValueError, "collision"):
            installer.process(self.pack, self.project, "antigravity", "apply")
        self.assertEqual(original, path.read_bytes())


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
        from lib.hosts.merge_codex_config import merge
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

    def test_native_codex_and_inline_hook_are_published_once_with_no_intermediate_state(self):
        from lib.hosts.merge_codex_config import merge
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
                    "不更新原型", "任务A已完成，接着做B", "开发五个模块", "开始优化",
                    "功能不变，代码少，只改 CSS", "角色缺失或失败了，继续")
        for host in ("codex", "claude"):
            for request in requests:
                payload = self.payload(host, prompt=request)
                data = hooks.response(host, "UserPromptSubmit", payload, self.project)
                self.assertEqual(hooks.ENTRY, data["hookSpecificOutput"]["additionalContext"])
                self.assertFalse({"decision", "continue", "permissionDecision"} & set(data))
        # 提示词不经过关键词分类，且提醒不含原始用户内容或复制的正文；
        # 这里只核对回调合同，不把提醒文本匹配当成模型服从或用户授权的证据。
        self.assertIn("explicit user opt-outs", hooks.ENTRY)
        self.assertIn("already completed", hooks.ENTRY)
        # 现有提醒由真实宿主回调加载；只读先分流，Light/Full 与默认委派
        # 明确属于实施，避免将 findings-only 审计误导成实施依赖图。
        for message in (hooks.ENTRY, hooks.RECOVERY):
            self.assertIn("Standalone read-only audit branch for findings-only requests", message)
            self.assertIn("Light/Full implementation", message)
            self.assertLess(message.index("Standalone read-only audit"), message.index("Light/Full implementation"))
            self.assertNotIn("Only Light/Full", message)
        self.assertNotIn("Trivial", hooks.ENTRY + hooks.RECOVERY)
        self.assertIn("retirement prohibits reuse", hooks.RECOVERY)
        # 提醒是模型可见串，必须英文；不筛查整个 Python 文件，中文实现注释继续保留。
        self.assertNotRegex(hooks.ENTRY + hooks.RECOVERY + hooks.DISPATCH, r"[\u4e00-\u9fff]")
        # 英文说明保持同一有限提醒职责；按实际英文长度约束，不能复用中文字符预算。
        self.assertLess(len(hooks.ENTRY), 1000)

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

    def test_git_uses_one_remaining_budget_and_decodes_paths_as_utf8(self):
        from lib.install import install_process
        # 两次 Git 命令共享同一截止时间，第二次只能使用递减后的剩余量；
        # 原生代码页不参与路径解码，也不重新给每一步完整的 0.7 秒预算。
        common = str(self.project / "中文.git")
        answers = [subprocess.CompletedProcess([], 0, common.encode("utf-8") + b"\n", b""),
                   subprocess.CompletedProcess([], 0, str(self.project).encode("utf-8") + b"\n", b"")]
        with patch.object(hooks.time, "monotonic", side_effect=(100.1, 100.8)), \
                patch.object(install_process, "capture_process", side_effect=answers) as capture:
            self.assertEqual(common, hooks.common_git(self.project, deadline=101))
        self.assertAlmostEqual(0.7, capture.call_args_list[0].kwargs["timeout"])
        self.assertAlmostEqual(0.2, capture.call_args_list[1].kwargs["timeout"])
        with patch.object(hooks.time, "monotonic", return_value=102), \
                patch.object(install_process, "capture_process") as capture, self.assertRaises(subprocess.TimeoutExpired):
            hooks.common_git(self.project, deadline=101)
        capture.assert_not_called()

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


    def test_agy_hook_rollback_does_not_overwrite_published_concurrent_edit(self):
        # applier 采用原有按路径事务接口；只构造配置变化，避免昂贵且无关的模块发现。
        library = str(PACK)
        sys.path.insert(0, library)
        self.addCleanup(lambda: sys.path.remove(library))
        import lib.hosts.apply_antigravity_setup as applier
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
        library = str(PACK)
        sys.path.insert(0, library)
        self.addCleanup(lambda: sys.path.remove(library))
        import lib.hosts.apply_antigravity_setup as applier
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
            source = PACK
            state = Path(raw).resolve() / "state"
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
            # 同一用例复用自己的内容库；不访问默认用户状态，也不复制另一份源码。
            installed = subprocess.run(["bash", str(source / "install.sh"), str(project), "--state-dir", str(state)],
                                       capture_output=True, text=True, timeout=120)
            self.assertEqual(0, installed.returncode, installed.stdout + installed.stderr)
            runtime = project / ".agent-workflow"
            for attempt in range(2):
                result = subprocess.run(["bash", str(source / "install.sh"), str(project), "--state-dir", str(state)],
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
            agents = {path.name: path.read_bytes() for path in (project / ".agents/agents").glob("xy-*.md")}
            from manager import runtime_service as central_service
            (project / "go.mod").write_text("module example.test/hook-rollback\n")
            binding = json.loads((runtime / "runtime.json").read_bytes())["runtime_binding"]
            plan = central_service.preview(state, project, "enable", binding=binding)
            target = ".agents/agents/xy-backend.md"
            self.assertIn(target, {change.relative for change in plan.changes})
            original = central_service._publish
            published = []

            def fail_after_native_publish(tree, row, core, save):
                # 先真正发布新 AGY 角色并登记 journal，再模拟失败；这样验证的是
                # 原生中央事务的条件回滚，而不是一个尚未写入就返回失败的替身。
                result = original(tree, row, core, save)
                published.append(row["path"])
                if row["path"] == target:
                    raise OSError("fixture native publication interrupted")
                return result

            with patch.object(central_service, "_publish", side_effect=fail_after_native_publish):
                with self.assertRaisesRegex(OSError, "native publication interrupted"):
                    central_service.apply(plan)
            self.assertIn(target, published)
            self.assertFalse((project / target).exists())
            self.assertEqual(before, agy.read_bytes())
            # 原生角色正文必须逐字节恢复；中央事务为保护旧 inode 保留的私有条目
            # 由机器记录和 ownership 验证，不把它们误当作新 Agent 或删除这些恢复资料。
            self.assertEqual(agents, {path.name: path.read_bytes() for path in (project / ".agents/agents").glob("xy-*.md")})
            restored = central_service.status(state, project)
            self.assertTrue(restored["enabled"], restored)
            self.assertEqual([], restored["conflicts"])


if __name__ == "__main__":
    unittest.main()
