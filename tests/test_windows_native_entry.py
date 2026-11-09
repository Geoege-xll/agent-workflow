"""原生源码 CLI 的实际消费者；可移植入口检查与 Windows 必验节点分开。"""

from __future__ import annotations

import base64
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


PACK = Path(__file__).resolve().parents[1]
ENTRY = PACK / "workflow.py"
LITERAL = '中文 空格 & e\u0301 "引号" \' %PATH% !value! ^ $(Get-Item .) ends\\'
# cmd 只承诺其正常 shell 引用；成对 %VAR% 是 cmd 自身的变量展开语法，
# 因而用未配对的字面 100% 检查百分号，复杂引号留给 PS 数组与直接 Python。
CMD_LITERAL = '中文 空格 & e\u0301 !value! 100% ^ (分组) ends\\'


class EntryFixture:
    """只建立本方法拥有的目录；所有子进程均显式隔离 state、HOME 与扫描根。"""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(
            prefix="awf-entry-中文 空格 & e\u0301-", dir=os.environ.get("AGENT_WORKFLOW_TEST_SCRATCH"))
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.caller = self.root / "调用目录 空格 & e\u0301"
        self.home = self.caller / "宿主 HOME"
        self.scan = self.caller / "扫描 中文 & e\u0301"
        self.state = self.caller / "状态 中文 & e\u0301"
        self.decoy = self.root / "旧 Bash caller"
        for path in (self.home, self.scan, self.decoy):
            path.mkdir(parents=True)
        self.env = {**os.environ, "HOME": str(self.home), "USERPROFILE": str(self.home),
                    "APPDATA": str(self.home / "AppData/Roaming"),
                    "LOCALAPPDATA": str(self.home / "AppData/Local"),
                    "CODEX_HOME": str(self.home / ".codex"),
                    "CLAUDE_CONFIG_DIR": str(self.home / ".claude"),
                    "AGENT_WORKFLOW_PYTHON": sys.executable,
                    "AGENT_WORKFLOW_CALLER_DIR": str(self.decoy),
                    "PYTHONPATH": str(self.caller), "PYTHONDONTWRITEBYTECODE": "1"}
        self.env.pop("AGENT_WORKFLOW_STATE_DIR", None)
        if os.name == "nt":
            self.env.update(HOMEDRIVE=self.home.drive, HOMEPATH=str(self.home)[2:])
        self.options = ["--state-dir", self.state.name, "--host-home", self.home.name,
                        "--scan-root", self.scan.name]

    def execute(self, command, *, env=None, cwd=None):
        # 完整命令、输出和 exit 进入唯一 runner 的原始日志；只包含本夹具路径，
        # 不打印继承环境，因此不会把宿主凭据附带写入验证产物。
        print("\n[entry command] " + json.dumps(command, ensure_ascii=False), flush=True)
        result = subprocess.run(command, cwd=self.caller if cwd is None else cwd,
                                env=self.env if env is None else env,
                                capture_output=True, text=True, encoding="utf-8", timeout=30)
        print("[entry stdout]\n" + result.stdout, end="" if result.stdout.endswith("\n") else "\n", flush=True)
        print("[entry stderr]\n" + result.stderr, end="" if result.stderr.endswith("\n") else "\n", flush=True)
        print("[entry exit] " + str(result.returncode), flush=True)
        return result

    def python(self, arguments, *, isolated=True):
        flags = (["-I"] if isolated else []) + ["-B", "-X", "utf8"]
        # Mac 上连测试启动的 Python 子消费者也经过项目现有运行时选择器。
        command = ([sys.executable] if os.name == "nt" else
                   ["bash", str(PACK / "lib/python_runtime.sh")])
        return self.execute([*command, *flags, str(ENTRY), *self.options, *arguments])

    def assert_read_only(self):
        self.assertFalse(self.state.exists(), "只读入口创建了 state")
        self.assertEqual(list(self.home.iterdir()), [], "只读入口修改了隔离宿主目录")
        self.assertFalse((self.caller / "poison-executed").exists())

    def poison_stdlib(self):
        sentinel = self.caller / "poison-executed"
        poison = f"open({str(sentinel)!r}, 'w').write('poison')\nraise RuntimeError('business cwd poison')\n"
        for name in ("pathlib", "ctypes", "argparse"):
            (self.caller / (name + ".py")).write_text(poison, encoding="utf-8")
        return sentinel

    def smoke(self, launch):
        help_result = launch(["--help"])
        self.assertEqual(help_result.returncode, 0, help_result.stderr)
        self.assertIn("usage: awf-cli", help_result.stdout)
        version = launch(["--version"])
        self.assertEqual(version.returncode, 0, version.stderr)
        expected = (PACK / "product/VERSION").read_text(encoding="ascii").strip()
        self.assertEqual(version.stdout.splitlines(), [f"awf-cli {expected}（源码未打包）",
            f"中央源根：{PACK}", "入口来源：source（显式源码开发）", f"物理载荷根：{PACK}"])
        listing = launch(["--json", "list"])
        self.assertEqual(listing.returncode, 0, listing.stderr)
        self.assertEqual(json.loads(listing.stdout), {"schema_version": 1, "command": "list",
                                                     "dry_run": False, "result": []})
        self.assert_read_only()

    def literal_and_relative(self, launch, literal=LITERAL):
        # 只读 list 自己扫描夹具中的空项目即可证明原 cwd/相对 scan-root 生效，
        # 无需登记、安装中央核心或触发任何写事务。引号等 Win32 禁用字符仅放入
        # 错误参数，另外验证 argv 数据边界与业务 exit=2，不能拼成 shell 指令。
        project = self.scan / "项目 中文 & e\u0301"
        marker = project / ".agent-workflow/project.yaml"
        marker.parent.mkdir(parents=True)
        marker.write_text("schema: 1\n", encoding="utf-8")
        before = marker.read_bytes()
        listing = launch(["--json", "list"])
        self.assertEqual(listing.returncode, 0, listing.stderr)
        rows = json.loads(listing.stdout)["result"]
        self.assertEqual([row["project"] for row in rows], [str(project.resolve())])
        self.assertEqual(marker.read_bytes(), before)
        rejected = launch(["list", "--unexpected", literal])
        self.assertEqual(rejected.returncode, 2, rejected.stdout + rejected.stderr)
        self.assertIn(literal, rejected.stderr)
        # 空字符串若被壳层丢弃就会退化成合法 list/exit=0，因此独立检查此
        # 负例可真实区分保留空参数与静默丢参，不能只检查含空格字符串。
        empty = launch(["list", ""])
        self.assertEqual(empty.returncode, 2, empty.stdout + empty.stderr)
        self.assert_read_only()


class PortableNativeEntryTest(EntryFixture, unittest.TestCase):
    """这些真实 Python 入口证据只声明当前宿主平台，不代替 Windows 验收。"""

    def test_isolated_python_help_version_and_empty_list(self):
        self.smoke(self.python)

    def test_relative_scan_and_literal_error_preserve_caller(self):
        self.literal_and_relative(self.python)

    def test_isolated_python_ignores_stdlib_shadows(self):
        self.poison_stdlib()
        result = self.python(["--version"])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("源码未打包", result.stdout)
        self.assert_read_only()

    def test_entry_source_compiles_and_imports_without_starting_cli(self):
        for path in (ENTRY, Path(__file__)):
            compile(path.read_bytes(), str(path), "exec")
        before_path, before_cwd = sys.path[:], Path.cwd()
        spec = importlib.util.spec_from_file_location("workflow_native_entry_import_check", ENTRY)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        self.assertTrue(callable(module.main))
        self.assertEqual(sys.path, before_path)
        self.assertEqual(Path.cwd(), before_cwd)
        self.assert_read_only()


@unittest.skipUnless(os.name == "nt", "必须在真实 Windows 执行；不能以可移植检查代替")
class WindowsNativeEntryTest(EntryFixture, unittest.TestCase):
    """由 N1 唯一 GROUPS 显式登记；缺少解释器或 PS7 是失败，不能 skip。"""

    def setUp(self):
        super().setUp()
        self.pwsh = Path(os.environ.get("AGENT_WORKFLOW_PWSH",
            str(Path(os.environ["ProgramFiles"]) / "PowerShell/7/pwsh.exe")))
        self.assertTrue(self.pwsh.is_absolute() and self.pwsh.is_file(), "需要已有 PowerShell 7+")
        self.cmd = Path(os.environ["SystemRoot"]) / "System32/cmd.exe"
        self.assertTrue(self.cmd.is_file())
        self.env["AGENT_WORKFLOW_PWSH"] = str(self.pwsh)

    def powershell(self, arguments, *, env=None):
        environment = dict(self.env if env is None else env)
        environment.update(AWF_ENTRY_TEST_SCRIPT=str(PACK / "workflow.ps1"),
                           AWF_ENTRY_TEST_CWD=str(self.caller),
                           AWF_ENTRY_TEST_ARGV=json.dumps([*self.options, *arguments], ensure_ascii=False))
        # 测试上游只把数据经环境 JSON 交给固定脚本；PS7.0 的 Legacy 模式被
        # 明确设定，真正受验者仍是生产 .ps1 -> .NET ArgumentList -> Python。
        script = ("$ErrorActionPreference='Stop';$PSNativeCommandArgumentPassing='Legacy';"
                  "Set-Location -LiteralPath $env:AWF_ENTRY_TEST_CWD;"
                  "$vector=@(ConvertFrom-Json -InputObject $env:AWF_ENTRY_TEST_ARGV);"
                  "& $env:AWF_ENTRY_TEST_SCRIPT @vector;exit $LASTEXITCODE")
        encoded = base64.b64encode(script.encode("utf-16-le")).decode("ascii")
        return self.execute([str(self.pwsh), "-NoLogo", "-NoProfile", "-NonInteractive",
                             "-EncodedCommand", encoded], env=environment, cwd=self.decoy)

    def command_prompt(self, arguments, *, env=None):
        environment = dict(self.env if env is None else env)
        # 正常双引号参数不包含嵌套引号或成对变量表达式。/d 禁用 AutoRun，
        # /v:off 与生产批处理的 DisableDelayedExpansion 共同保护字面 !。
        quoted = []
        for value in [*self.options, *arguments]:
            self.assertFalse(any(char in value for char in ('"', '\r', '\n')))
            # 原生命令行按 Windows argv 规则保留结束反斜线；所有值都引用，
            # 连没有空格的 & 参数也不会在 cmd 解析阶段成为命令分隔符。
            trailing = len(value) - len(value.rstrip('\\'))
            quoted.append('"' + value + '\\' * trailing + '"')
        # cmd /c 使用自身引号语法，不能交给 subprocess 的 C-runtime argv
        # 编码器给内层引号加反斜线；在自己的 shell 引用层构造一次命令。
        command = f'"{self.cmd}" /d /v:off /c ""{PACK / "workflow.cmd"}" ' + ' '.join(quoted) + '"'
        return self.execute(command, env=environment)

    def test_python_help_version_and_empty_list(self):
        self.smoke(self.python)

    def test_powershell_legacy_help_version_and_empty_list(self):
        self.smoke(self.powershell)

    def test_cmd_help_version_and_empty_list(self):
        self.smoke(self.command_prompt)

    def test_shells_preserve_literal_arguments_and_exit_codes(self):
        for launch in (self.python, self.powershell, self.command_prompt):
            with self.subTest(entry=launch.__name__):
                self.literal_and_relative(launch, CMD_LITERAL if launch == self.command_prompt else LITERAL)
                # 同一 scan 夹具原位复用，下个入口需要重新建立同一项目标记。
                marker = self.scan / "项目 中文 & e\u0301/.agent-workflow/project.yaml"
                marker.unlink()
                marker.parent.rmdir()
                marker.parent.parent.rmdir()

    def test_explicit_invalid_python_is_refused_without_fallback(self):
        bad_executable = self.caller / "python.exe"
        bad_executable.write_bytes(b"not a Windows executable\r\n")
        for value in ("", "python.exe", str(self.root / "missing/python.exe"), str(bad_executable), str(self.cmd)):
            for launch in (self.powershell, self.command_prompt):
                with self.subTest(python=value, entry=launch.__name__):
                    result = launch(["--version"], env={**self.env, "AGENT_WORKFLOW_PYTHON": value})
                    self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
                    self.assertIn("[错误]", result.stderr)
                    self.assertNotIn("源码未打包", result.stdout)
        self.assert_read_only()

    def test_python_isolation_precedes_stdlib_imports(self):
        sentinel = self.poison_stdlib()
        refused = self.python(["--help"], isolated=False)
        self.assertEqual(refused.returncode, 2, refused.stdout + refused.stderr)
        self.assertIn("-I", refused.stderr)
        self.assertFalse(sentinel.exists(), "非隔离拒绝之前执行了业务目录标准库影子")
        for launch in (self.python, self.powershell, self.command_prompt):
            with self.subTest(entry=launch.__name__):
                result = launch(["--version"])
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn("源码未打包", result.stdout)
                self.assertFalse(sentinel.exists(), "隔离启动执行了业务目录标准库影子")
        self.assert_read_only()
