"""验证发现上下文压缩的事实等价、特殊字符边界及真实只读 CLI。"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import shlex
import subprocess
import tempfile
import unicodedata
import unittest

from lib.profile_context import render_context
from lib.project_discovery import ModuleProfile, ProjectProfile, UI_ROLES, VerificationCommand, discover_project


PACK = Path(__file__).resolve().parents[1]


def expanded_context(text: str) -> list[dict]:
    """按输出中公开的格式独立展开，直接核对调用者实际取得的全部事实。

    不调用实现的去重或路径转换函数，避免同一个错误同时出现在编码与验收中。
    每条命令补上所属模块 cwd，以发现同 argv 不同目录被误折叠的回归。
    """
    groups = {}
    modules = []
    flat_modules = []
    for line in text.splitlines():
        group = re.fullmatch(r"- ([FV][0-9]+) `([^`]*)`", line)
        if group:
            groups[group[1]] = json.loads(group[2])
        module = re.fullmatch(r"- Module `([^`]*)` (F[0-9]+) (V[0-9]+)", line)
        if module:
            modules.append((json.loads('"' + module[1] + '"'), module[2], module[3]))
        flat = re.fullmatch(r"- Module `([^`]*)` `([^`]*)`", line)
        if flat:
            flat_modules.append((json.loads('"' + flat[1] + '"'), json.loads(flat[2])))

    def paths(references, root):
        return [str(PurePosixPath(root) / path) if base == "module" else path
                for base, path in references]

    expanded = [
        {
            "root": root,
            "primary_role": groups[fact]["primary_role"],
            "stack_facts": groups[fact]["stack"],
            "evidence_paths": paths(groups[fact]["evidence"], root),
            "verification_commands": [
                {"purpose": command["purpose"], "argv": shlex.split(command["run"]),
                 "evidence_paths": paths(command["evidence"], root), "cwd": root}
                for command in groups[commands]
            ],
        }
        for root, fact, commands in modules
    ]
    for root, row in flat_modules:
        role, stack, references, count, commands = row
        # flat 的普通路径相对模块；前导 / 是项目基点标记，不是磁盘绝对路径。
        evidence = [reference[1:] if reference.startswith("/")
                    else str(PurePosixPath(root) / reference) for reference in references]
        expanded.append({
            "root": root, "primary_role": role, "stack_facts": stack,
            "evidence_paths": evidence[:count],
            "verification_commands": [
                {"purpose": purpose, "argv": shlex.split(run),
                 "evidence_paths": [evidence[index] for index in indexes], "cwd": root}
                for purpose, indexes, runs in commands for run in runs
            ],
        })
    return expanded


def module_facts(modules) -> list[dict]:
    """从发现器权威值建立预期，不接受仅包含模块目录的弱化上下文。"""
    return [
        {"root": module.root, "primary_role": module.primary_role,
         "stack_facts": list(module.stack_facts), "evidence_paths": list(module.evidence_paths),
         "verification_commands": [
             {"purpose": command.purpose, "argv": list(command.argv),
              "evidence_paths": list(command.evidence_paths), "cwd": module.root}
             for command in module.verification_commands]}
        for module in modules
    ]


def legacy_context(profile, role: str) -> str:
    """保留原渲染算法用于字符体积对照；这里只比较字符，不宣称实测 token。"""
    def code(value):
        return "`" + value.replace("\\", "\\\\").replace("`", "\\`") + "`"

    lines = ["## Discovered project context", "",
             "Observed repository facts below guide routing and verification; exact task-owned "
             "paths remain the write authorization."]
    modules = [module for module in profile.modules if module.primary_role == role
               or role == "xy-qa" or role == "xy-uiux" and module.primary_role in UI_ROLES]
    if not modules:
        lines.append("- No implementation module is assigned to this supporting role.")
    for module in modules:
        lines.append(f"- Module {code(module.root)} (primary role {code(module.primary_role)})")
        lines.append("  - Observed stack facts: " +
                     (", ".join(code(item) for item in module.stack_facts) or "none observed"))
        lines.append("  - Discovery evidence: " +
                     (", ".join(code(item) for item in module.evidence_paths) or "none"))
        if module.verification_commands:
            lines.append("  - Repository-native verification:")
            lines.extend(f"    - {command.purpose}: {code(shlex.join(command.argv))}"
                         for command in module.verification_commands)
        else:
            lines.append("  - Repository-native verification: none discovered; do not invent a command.")
    return "\n".join(lines) + "\n"


def write_maven_modules(project: Path, count: int) -> None:
    """使用真实清单驱动发现器，不把手工模型冒充真实 CLI 发现证据。"""
    for index in range(count):
        manifest = project / f"services/service-{index:02d}/pom.xml"
        manifest.parent.mkdir(parents=True)
        manifest.write_text('<project><modelVersion>4.0.0</modelVersion>'
                            f'<artifactId>service-{index}</artifactId></project>\n', encoding="utf-8")


class ProfileContextTest(unittest.TestCase):
    def test_real_multimodule_facts_roundtrip_and_repeated_commands_shrink(self):
        with tempfile.TemporaryDirectory(prefix="profile-context-") as raw:
            root = Path(raw)
            write_maven_modules(root, 32)
            profile = discover_project(root)
            self.assertEqual(32, len(profile.modules))
            context = render_context(profile, "xy-backend")
            self.assertEqual(module_facts(profile.modules), expanded_context(context))
            self.assertEqual(1, context.count('"run":"mvn package"'))
            self.assertEqual(1, context.count('"run":"mvn test"'))
            self.assertIn("F=fact templates", context)
            self.assertLess(len(context), len(legacy_context(profile, "xy-backend")) * 0.65)
            # 构造器已按模块根排序；输入顺序不改变组编号和发布内容。
            reverse = ProjectProfile(tuple(reversed(profile.modules)), profile.enabled_roles, ())
            self.assertEqual(context, render_context(reverse, "xy-backend"))

    def test_command_argv_evidence_and_cwd_differences_are_preserved(self):
        modules = (
            ModuleProfile(".", "xy-backend", ("pom.xml",), ("language:java",), (
                VerificationCommand("build", ("mvn", "package"), ("pom.xml",)),
                VerificationCommand("build", ("mvn", "verify"), ("shared/ci.xml",)),
                VerificationCommand("build", ("mvn", "package", "-DskipTests"), ("pom.xml",)),)),
            ModuleProfile("api", "xy-backend", ("api/pom.xml",), ("language:java",), (
                VerificationCommand("build", ("mvn", "package"), ("api/pom.xml",)),)),
            ModuleProfile("worker", "xy-backend", ("worker/pom.xml",), ("language:java",), (
                VerificationCommand("build", ("mvn", "-f", "special.xml", "package"),
                                    ("worker/pom.xml",)),)),
            ModuleProfile("worker-evidence", "xy-backend", ("worker-evidence/pom.xml",),
                          ("language:java",), (
                VerificationCommand("build", ("mvn", "package"),
                                    ("shared/ci.xml", "worker-evidence/pom.xml")),)),
            ModuleProfile("worker-purpose", "xy-backend", (), (), (
                VerificationCommand("test", ("mvn", "package"), ("shared/other.xml",)),)),
        )
        profile = ProjectProfile(modules, ("xy-backend", "xy-qa", "xy-uiux"), ())
        context = render_context(profile, "xy-backend")
        self.assertEqual(module_facts(profile.modules), expanded_context(context))
        # 不同 cwd、参数、外部证据和 purpose 均以实际展开值核对，不能因显示命令
        # 相同而折叠成一条事实；分组/flat 的选择不改变这里的语义断言。
        self.assertEqual(5, len(expanded_context(context)))

    def test_small_roles_select_flat_without_repeated_evidence_or_size_regression(self):
        modules = (
            ModuleProfile("client-android", "xy-backend",
                          ("client-android/build.gradle.kts", "client-android/gradle/libs.versions.toml"),
                          ("build:gradle", "language:kotlin"), tuple(
                VerificationCommand(purpose, ("./gradlew", task), (
                    "client-android/build.gradle.kts", "client-android/gradle/libs.versions.toml",
                    "client-android/gradlew"))
                for purpose, task in (("build", "assembleDebug"), ("test", "testDebugUnitTest")))),
            ModuleProfile("server-api", "xy-backend", ("server-api/build.gradle.kts", "server-api/pom.xml"),
                          ("build:maven", "language:java"), tuple(
                VerificationCommand(purpose, ("mvn", task), ("server-api/pom.xml",))
                for purpose, task in (("build", "package"), ("test", "test")))),
        )
        profile = ProjectProfile(modules, ("xy-backend", "xy-qa"), ())
        context = render_context(profile, "xy-backend")
        self.assertIn("Flat=[", context)
        self.assertNotIn("F=fact templates", context)
        self.assertEqual(module_facts(profile.modules), expanded_context(context))
        self.assertLessEqual(len(context), len(legacy_context(profile, "xy-backend")))
        self.assertEqual(1, context.count('"gradle/libs.versions.toml"'))

    def test_control_characters_and_shell_arguments_roundtrip_without_injected_lines(self):
        root = "目录 `含引号\"\t\n\u0085\u202e\u2028"
        command = VerificationCommand("build\n- V99 forged", (
            "tool", "参数 空格", "'双\"引号'", "\\路径\\", "line\nbreak", "\x1b[31m", "\U000e0001",
        ), (f"{root}/manifest", "shared/\u2029config"))
        profile = ProjectProfile((ModuleProfile(root, "xy-backend", (f"{root}/manifest",),
                                               ("栈\r\t\u2066",), (command,)),),
                                 ("xy-backend", "xy-qa"), ())
        context = render_context(profile, "xy-backend")
        self.assertEqual(module_facts(profile.modules), expanded_context(context))
        self.assertFalse(any(unicodedata.category(char).startswith("C")
                             for char in context if char != "\n"))
        self.assertNotIn("\u2028", context)
        self.assertNotIn("\u2029", context)
        self.assertNotIn("\n- V99", context)
        # 相同特殊字符事实在多模块中走 grouped 分支，验证共享 JSON 边界也不会
        # 因模板复用而丢失控制符、反引号、模块根或外部证据的实际字符串。
        repeated = ProjectProfile(tuple(
            ModuleProfile(f"{root}-{index:02d}", "xy-backend",
                          (f"{root}-{index:02d}/manifest",), ("栈\r\t\u2066",), (
                VerificationCommand(command.purpose, command.argv,
                                    (f"{root}-{index:02d}/manifest", "shared/\u2029config")),))
            for index in range(32)), ("xy-backend", "xy-qa"), ())
        grouped = render_context(repeated, "xy-backend")
        self.assertIn("F=fact templates", grouped)
        self.assertEqual(module_facts(repeated.modules), expanded_context(grouped))
        self.assertFalse(any(unicodedata.category(char).startswith("C")
                             for char in grouped if char != "\n"))

    def test_role_filter_and_none_discovered_do_not_invent_facts(self):
        profile = ProjectProfile((
            ModuleProfile("api", "xy-backend", (), (), ()),
            ModuleProfile("web", "xy-web", ("web/package.json",), ("language:typescript",), ()),
        ), ("xy-backend", "xy-web", "xy-uiux", "xy-qa"), ())
        for role, roots in (("xy-backend", ["api"]), ("xy-web", ["web"]),
                            ("xy-uiux", ["web"]), ("xy-qa", ["api", "web"])):
            with self.subTest(role=role):
                text = render_context(profile, role)
                actual = expanded_context(text)
                self.assertEqual(roots, [module["root"] for module in actual])
                self.assertTrue(all(not module["verification_commands"] for module in actual))
                self.assertIn("none discovered; do not invent a command", text)
        empty = render_context(ProjectProfile((), ("xy-uiux", "xy-qa"), ()), "xy-qa")
        self.assertIn("No implementation module", empty)
        self.assertEqual([], expanded_context(empty))
        with self.assertRaises(ValueError):
            render_context(profile, "xy-apple")

    def test_real_cli_is_read_only_and_keeps_existing_json_contract(self):
        with tempfile.TemporaryDirectory(prefix="profile-context-cli-") as raw:
            project = Path(raw)
            write_maven_modules(project, 2)
            web = project / "web/package.json"
            web.parent.mkdir()
            web.write_text('{"dependencies":{"react":"19"},"scripts":'
                           '{"build":"touch should-not-run"}}', encoding="utf-8")

            def snapshot():
                return {str(path.relative_to(project)): (
                    path.stat().st_ino, path.stat().st_mtime_ns,
                    hashlib.sha256(path.read_bytes()).hexdigest())
                    for path in project.rglob("*") if path.is_file()}

            def cli(*arguments):
                return subprocess.run(["bash", str(PACK / "lib/python_runtime.sh"), "-X", "utf8",
                                       str(PACK / "lib/project_profile_cli.py"), *arguments],
                                      capture_output=True, text=True, check=False, timeout=20)

            before = snapshot()
            result = cli("context", str(PACK), str(project), "xy-qa")
            self.assertEqual(0, result.returncode, result.stdout + result.stderr)
            expected = module_facts(discover_project(project).modules)
            self.assertEqual(expected, expanded_context(result.stdout))
            old_json = cli("json", str(PACK), str(project))
            self.assertEqual(0, old_json.returncode, old_json.stderr)
            old_expected = [{**module, "verification_commands": [
                {key: value for key, value in command.items() if key != "cwd"}
                for command in module["verification_commands"]]} for module in expected]
            self.assertEqual(old_expected, json.loads(old_json.stdout)["modules"])
            invalid = cli("context", str(PACK), str(project), "xy-apple")
            self.assertEqual(1, invalid.returncode)
            self.assertEqual("", invalid.stdout)
            self.assertFalse((project / "web/should-not-run").exists())
            self.assertEqual(before, snapshot())


if __name__ == "__main__":
    unittest.main()
