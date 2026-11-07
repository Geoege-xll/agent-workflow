"""原生本地 tgz 消费者；只在自有普通用户 fixture 中验证，不安装到真实项目。"""

from __future__ import annotations

import argparse
import ctypes
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import tempfile
import unittest
import uuid


FIXTURE_ROOT = None
LOCAL_ARCHIVE = None


class NpxFixture(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        archive = LOCAL_ARCHIVE or os.environ.get("AGENT_WORKFLOW_NPX_TGZ")
        if not archive:
            raise AssertionError("需要完整本地 tgz；缺失不能用 skip 代替原生验收")
        cls.archive = Path(archive).absolute()
        if not cls.archive.is_file():
            raise AssertionError("本地 tgz 不存在")
        shell = ctypes.WinDLL("shell32", use_last_error=True)
        shell.IsUserAnAdmin.restype = ctypes.c_int32
        if shell.IsUserAnAdmin():
            raise AssertionError("本消费者必须是真实普通用户，托管管理员结果不能替代")
        cls.node = shutil.which("node.exe")
        npm = shutil.which("npm.cmd")
        if not cls.node or not npm:
            raise AssertionError("需要原生 x64 Node.js/npm")
        cls.npm_cli = Path(npm).parent / "node_modules/npm/bin/npm-cli.js"
        if not cls.npm_cli.is_file():
            raise AssertionError("npm.cmd 同目录没有 npm-cli.js")
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.GetSystemDirectoryW.argtypes = [ctypes.c_wchar_p, ctypes.c_uint32]
        kernel.GetSystemDirectoryW.restype = ctypes.c_uint32
        buffer = ctypes.create_unicode_buffer(32768)
        count = kernel.GetSystemDirectoryW(buffer, len(buffer))
        if not count or count >= len(buffer):
            raise ctypes.WinError(ctypes.get_last_error())
        cls.system = Path(buffer.value)
        cls.powershell = cls.system / "WindowsPowerShell/v1.0/powershell.exe"
        cls.cmd = cls.system / "cmd.exe"
        print("原生 npm 账户：non-administrator；OS=" + platform.platform(), flush=True)
        print("本轮 hosted Server 结果不声明 Win10/11 客户端已经实测。", flush=True)

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="npx-central-", dir=FIXTURE_ROOT)
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.project = self.root / "项目 with spaces & (parentheses)"
        self.project.mkdir()
        self.state = self.root / "private-central-state"
        self.cache = self.root / "owned npm cache"
        self.artifacts = self.root / "local artifacts"
        self.artifacts.mkdir()
        self.tgz = self.artifacts / self.archive.name
        shutil.copyfile(self.archive, self.tgz)
        self.env = dict(os.environ)
        # 实际选择 bundled -> 持久 embedded，不继承 setup-python 覆盖值。
        for key in tuple(self.env):
            if key.upper() in {"AGENT_WORKFLOW_PYTHON", "AGENT_WORKFLOW_BOOTSTRAP",
                               "AGENT_WORKFLOW_CANCEL_FILE", "AGENT_WORKFLOW_PROJECT_RUNTIME",
                               "AGENT_WORKFLOW_RUNTIME_BINDING", "AGENT_WORKFLOW_PROJECT_ROOT",
                               "AGENT_WORKFLOW_CORE_ROOT", "AGENT_WORKFLOW_CONFIG_PATH"}:
                self.env.pop(key)
        self.env.update(AGENT_WORKFLOW_STATE_DIR=str(self.state),
                        npm_config_registry="http://127.0.0.1:9", npm_config_audit="false",
                        npm_config_fund="false", npm_config_update_notifier="false")
        self.sentinel = self.project / "USER_CONTENT.txt"
        self.sentinel.write_bytes(b"never replace user content\n")
        self.sentinel_inode = (self.sentinel.stat().st_dev, self.sentinel.stat().st_ino)

    def execute(self, arguments, *, env=None, timeout=900):
        # npm 的 .cmd 不交给 shell=True；网络注册表不可达且显式 offline/ignore-scripts。
        return subprocess.run(
            [self.node, str(self.npm_cli), "exec", "--offline", "--ignore-scripts", "--yes",
             "--cache", str(self.cache), "--package", str(self.tgz), "--", "agent-workflow", *arguments],
            cwd=self.project, env=self.env if env is None else env, capture_output=True,
            text=True, encoding="utf-8", timeout=timeout)

    def assert_success(self, result):
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def assert_sentinel(self):
        self.assertEqual(self.sentinel.read_bytes(), b"never replace user content\n")
        self.assertEqual((self.sentinel.stat().st_dev, self.sentinel.stat().st_ino), self.sentinel_inode)

    def profile_snapshot(self):
        import winreg
        registry = {}
        for hive, subkey in ((winreg.HKEY_CURRENT_USER, "Environment"),
                             (winreg.HKEY_LOCAL_MACHINE,
                              r"SYSTEM\CurrentControlSet\Control\Session Manager\Environment")):
            with winreg.OpenKey(hive, subkey) as key:
                try:
                    registry[(str(hive), subkey)] = winreg.QueryValueEx(key, "Path")
                except FileNotFoundError:
                    registry[(str(hive), subkey)] = None
        def query(code):
            result = subprocess.run(
                [str(self.powershell), "-NoLogo", "-NoProfile", "-NonInteractive", "-Command",
                 "[Console]::OutputEncoding=[System.Text.UTF8Encoding]::new($false); " + code],
                capture_output=True, timeout=30)
            if result.returncode:
                # 只给这两条固定只读查询保留失败上下文；CalledProcessError 的
                # 默认文字不显示已捕获的 stderr，不能据 exit1 猜测系统原因。
                # 先捕获原始字节，失败输出才容错解码，避免错误码页再次遮蔽
                # 真实诊断；成功路径仍严格 UTF-8，且绝不继续/skip 非零结果。
                label = "execution-policy" if code.startswith("Get-ExecutionPolicy ") else "profile-paths"
                def context(body, limit=4096):
                    return repr(body[:limit].decode("utf-8", errors="backslashreplace"))
                detail = ""
                if label == "execution-policy":
                    # 三个消费者可能在同一前置查询处失败；本进程只执行一次
                    # 固定诊断并复用其文字，不能连续枚举/尝试替代模块制造绿。
                    case = type(self)
                    if not hasattr(case, "_security_module_diagnostic"):
                        diagnostic_code = r"""
[Console]::OutputEncoding=[System.Text.UTF8Encoding]::new($false)
function Bound($value, [int]$limit=512) {
    $text=[string]$value
    if ($text.Length -gt $limit) { return $text.Substring(0,$limit) }
    return $text
}
function ImportFailure($phase, $record) {
    [Console]::Error.WriteLine(('MODULE_DIAG {0} FQID={1} Category={2}' -f $phase,(Bound $record.FullyQualifiedErrorId 256),(Bound $record.CategoryInfo.Category 128)))
    $errorObject=$record.Exception
    for ($depth=0; $null -ne $errorObject -and $depth -lt 4; $depth++) {
        [Console]::Error.WriteLine(('MODULE_DIAG {0} exception[{1}]={2}: {3}' -f $phase,$depth,(Bound ($errorObject.GetType().FullName) 256),(Bound $errorObject.Message 1024)))
        $errorObject=$errorObject.InnerException
    }
}
[Console]::Error.WriteLine(('MODULE_DIAG PSVersion={0}' -f (Bound $PSVersionTable.PSVersion 64)))
$bad=$false
try {
    $count=0
    foreach ($candidate in @(Get-Module -ListAvailable -Name 'Microsoft.PowerShell.Security' -ErrorAction Stop)) {
        if ($count -ge 8) { break }
        $count++
        [Console]::Error.WriteLine(('MODULE_DIAG candidate Name={0} Version={1} PowerShellVersion={2} Path={3}' -f (Bound $candidate.Name 64),(Bound $candidate.Version 64),(Bound $candidate.PowerShellVersion 64),(Bound $candidate.Path 512)))
    }
    [Console]::Error.WriteLine(('MODULE_DIAG candidates_printed={0}' -f $count))
} catch { ImportFailure 'discovery' $_; $bad=$true }
$manifest=[IO.Path]::Combine($PSHOME,'Modules\Microsoft.PowerShell.Security\Microsoft.PowerShell.Security.psd1')
[Console]::Error.WriteLine(('MODULE_DIAG fixed_system_manifest={0}' -f (Bound $manifest 512)))
try {
    $loaded=Import-Module -Name $manifest -PassThru -ErrorAction Stop
    [Console]::Error.WriteLine(('MODULE_DIAG fixed_system_import=OK Name={0} Version={1} Path={2}' -f (Bound $loaded.Name 64),(Bound $loaded.Version 64),(Bound $loaded.Path 512)))
} catch { ImportFailure 'fixed-system-import' $_; $bad=$true }
if ($bad) { exit 1 }
exit 0
"""
                        try:
                            # 沿原系统宿主、令牌与环境，只查询这一个模块名；
                            # 搜索候选只读元数据，导入限定为固定系统绝对路径。
                            diagnostic = subprocess.run(
                                [str(self.powershell), "-NoLogo", "-NoProfile", "-NonInteractive",
                                 "-Command", diagnostic_code], capture_output=True, timeout=30)
                            detail = (f"module_diagnostic_exit={diagnostic.returncode}; "
                                      f"stdout={context(diagnostic.stdout, 24576)} "
                                      f"stderr={context(diagnostic.stderr, 24576)}")
                        except (OSError, subprocess.TimeoutExpired) as error:
                            # 诊断自身失败也不能替换原 query 的非零事实；不把
                            # 完整命令或个人环境放入异常文字，不继续安装。
                            detail = (f"module_diagnostic_error={type(error).__name__}; "
                                      f"errno={getattr(error, 'errno', None)} "
                                      f"winerror={getattr(error, 'winerror', None)}")
                        case._security_module_diagnostic = detail
                    detail = case._security_module_diagnostic
                self.fail(f"PowerShell只读快照query={label} exit={result.returncode}; "
                          f"stdout_bytes={len(result.stdout)} stderr_bytes={len(result.stderr)}; "
                          f"stdout={context(result.stdout)} stderr={context(result.stderr)}; {detail}")
            return result.stdout.decode("utf-8")
        policies = query("Get-ExecutionPolicy -List | ConvertTo-Json -Compress")
        profiles = query("@($PROFILE.AllUsersAllHosts,$PROFILE.AllUsersCurrentHost,"
                         "$PROFILE.CurrentUserAllHosts,$PROFILE.CurrentUserCurrentHost) | ConvertTo-Json -Compress")
        files = [Path(item) for item in json.loads(profiles)]
        files += [Path.home() / name for name in (".bashrc", ".bash_profile", ".profile", ".zshrc",
                                                  ".gitconfig", ".config/git/config")]
        # 只比较摘要，不打印 profile、Git 配置正文或账号信息。
        hashes = {str(file): hashlib.sha256(file.read_bytes()).hexdigest() if file.is_file() else None
                  for file in files}
        return registry, policies, hashes, dict(os.environ)

    def bridge(self, *arguments, timeout=180):
        runtime = self.project / ".agent-workflow"
        return subprocess.run([self.node, str(runtime / "lib/python_runtime.cjs"),
                               str(runtime / "runtime.py"), *arguments],
                              cwd=self.project, env=self.env, capture_output=True, text=True,
                              encoding="utf-8", timeout=timeout)

    def installed(self):
        checked = self.bridge("check")
        self.assert_success(checked)
        pin = json.loads(checked.stdout)["runtime_binding"]
        self.assertEqual(set(pin), {"protocol_version", "content_id", "manifest_sha256"})
        self.assertEqual(pin["content_id"], pin["manifest_sha256"])
        binding_files = list((self.state / "bindings").glob("*.json"))
        self.assertEqual(len(binding_files), 1)
        binding = json.loads(binding_files[0].read_text(encoding="utf-8"))
        self.assertTrue(binding["enabled"])
        self.assertEqual(binding["project_root"], str(self.project))
        self.assertEqual(binding["runtime_binding"], pin)
        core = self.state / "runtimes" / pin["content_id"] / "core"
        manifest_bytes = core.parent.joinpath("manifest.json").read_bytes()
        self.assertEqual(hashlib.sha256(manifest_bytes).hexdigest(), pin["manifest_sha256"])
        runtime = self.project / ".agent-workflow"
        self.assertEqual(sorted(path.name for path in (runtime / "lib").iterdir()),
                         ["python_runtime.cjs", "python_runtime.sh", "windows-runtime.paths", "workflow_hooks.py"])
        for name in ("product", "roles", "platforms", "templates", "manager"):
            self.assertFalse((runtime / name).exists())
        for host in (".agents/skills", ".claude/skills"):
            for name in (core / "platforms/shared/core-skills.txt").read_text().splitlines():
                link = self.project / host / name
                self.assertEqual(link.lstat().st_reparse_tag, 0xA000000C)
                self.assertEqual(link.resolve(strict=True), core / "platforms/shared/skills" / name)
        # 两行路径来自真正项目薄桥；persistent runtime 的每个文件须匹配其清单。
        paths = (runtime / "lib/windows-runtime.paths").read_text(encoding="utf-8").splitlines()
        self.assertEqual(len(paths), 2)
        python, bootstrap = map(Path, paths)
        self.assertEqual(python.name, "python.exe")
        self.assertEqual(bootstrap.parent, python.parent)
        self.assertFalse(python.is_relative_to(self.cache))
        self.assertFalse(python.is_relative_to(self.root))
        self.assertFalse(any(part.lower() in {"_npx", "_cacache"} for part in python.parts))
        document = json.loads((python.parent / "manifest.json").read_text(encoding="utf-8"))
        for name, expected in document["files"].items():
            file = python.parent / name
            self.assertEqual(file.lstat().st_nlink, 1)
            self.assertFalse(file.is_symlink())
            self.assertEqual(hashlib.sha256(file.read_bytes()).hexdigest(), expected)
        self.assertTrue({"python.exe", "windows_bootstrap.py", "windows_fs.py", "windows_runtime.py"}
                        <= set(document["files"]))
        print("真实持久 embedded：" + str(python) + "；pin=" + pin["content_id"], flush=True)
        return pin, core

    def pinned(self, pin, *arguments, timeout=180):
        return self.bridge("--binding", json.dumps(pin), *arguments, timeout=timeout)


@unittest.skipUnless(os.name == "nt", "需要原生 Windows；portable 结果不能当安装验收")
class WindowsNpxEndToEndTest(NpxFixture):
    def test_help_and_invalid_explicit_dependencies_do_not_write_project(self):
        before = self.profile_snapshot()
        for args in ([], ["--help"], ["--version"]):
            self.assert_success(self.execute(args))
        for args, additions in ((["init", "--timeout", "nan"], {}),
                                (["init", "--unknown"], {}),
                                (["init"], {"AGENT_WORKFLOW_PYTHON": "missing-python.exe"}),
                                (["init"], {"AGENT_WORKFLOW_PYTHON": ""}),
                                (["init"], {"AGENT_WORKFLOW_BASH": "missing-bash.exe"})):
            with self.subTest(args=args, additions=additions):
                result = self.execute(args, env={**self.env, **additions})
                self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertEqual([self.sentinel], list(self.project.iterdir()))
                self.assertFalse(self.state.exists())
        self.assertEqual(before, self.profile_snapshot())

    def test_init_with_existing_hooks_and_msys_mount_temp(self):
        before = self.profile_snapshot()
        agents = self.project / ".agents"
        agents.mkdir()
        hooks = agents / "hooks.json"
        user = {"user-protected": {"keep": True},
                "hooks": {"SessionStart": [{"hooks": [{"type": "command", "command": "echo user-hook"}]}]}}
        hooks.write_text(json.dumps(user), encoding="utf-8")
        self.env["TMPDIR"] = "/tmp"
        self.assert_success(self.execute(["init"]))
        merged = json.loads(hooks.read_text(encoding="utf-8"))
        self.assertEqual(merged["user-protected"], user["user-protected"])
        self.assertTrue(any(hook.get("command") == "echo user-hook"
                            for group in merged["hooks"]["SessionStart"] for hook in group["hooks"]))
        pin, core = self.installed()
        read = self.pinned(pin, "read", "product/GLOBAL_CONSTRAINTS.md")
        self.assert_success(read)
        self.assertEqual(read.stdout, (core / "product/GLOBAL_CONSTRAINTS.md").read_text(encoding="utf-8"))
        self.assert_sentinel()
        self.assertEqual(before, self.profile_snapshot())

    def test_offline_reinstall_timeout_cache_independent_workflow_and_hook(self):
        before = self.profile_snapshot()
        path_key = next(key for key in self.env if key.upper() == "PATH")
        self.env[path_key] = ";".join(map(str, (Path(self.node).parent, self.system, self.powershell.parent)))
        self.assert_success(self.execute(["init"]))
        pin, core = self.installed()
        runtime = self.project / ".agent-workflow"
        config = runtime / "project.yaml"
        configured = config.read_bytes() + b"\n# preserved user configuration\n"
        config.write_bytes(configured)
        self.assert_success(self.execute(["init", "--project", "."]))
        self.assertEqual(configured, config.read_bytes())
        expired = self.execute(["init", "--timeout", "0.000001"])
        self.assertNotEqual(expired.returncode, 0, expired.stdout + expired.stderr)
        self.assertEqual(configured, config.read_bytes())
        self.assert_sentinel()
        # 只删除本测试私有 cache/tgz；中央core、持久embedded及用户global缓存不动。
        shutil.rmtree(self.cache)
        self.tgz.unlink()
        read = self.pinned(pin, "read", "product/GLOBAL_CONSTRAINTS.md")
        self.assert_success(read)
        self.assertEqual(read.stdout, (core / "product/GLOBAL_CONSTRAINTS.md").read_text(encoding="utf-8"))
        profile = self.pinned(pin, "helper", "lib/project_profile_cli.py", "roles", ".agent-workflow", ".")
        self.assert_success(profile)
        self.assertIn("xy-qa", profile.stdout)
        # 实际工作流写入口创建本项目唯一请求scratch，再同helper读取并条件清理。
        request = "native-npx-" + uuid.uuid4().hex
        def scratch(*arguments):
            result = self.pinned(pin, "helper", "lib/task_graph_cli.py", *arguments)
            self.assert_success(result)
            return json.loads(result.stdout)
        allocated = scratch("scratch", "--root", str(self.project), "--request-id", request)
        target = Path(allocated["scratch_dir"])
        try:
            self.assertTrue(target.is_dir())
            self.assertFalse(allocated["reused"])
            reused = scratch("scratch", "--root", str(self.project), "--request-id", request)
            self.assertTrue(reused["reused"])
            self.assertEqual(reused["scratch_dir"], str(target))
        finally:
            # 无新增任意删除脚本；沿产品现有snapshot合同收尾这个确证创建的请求。
            preview = scratch("cleanup-scratch", "--root", str(self.project), "--request-id", request, "--dry-run")
            applied = scratch("cleanup-scratch", "--root", str(self.project), "--request-id", request,
                              "--expect-sha256", preview["snapshot_sha256"])
            self.assertEqual(applied["status"], "applied")
            self.assertFalse(target.exists())
        settings = json.loads((self.project / ".claude/settings.json").read_text(encoding="utf-8"))
        commands = [hook["command"] for group in settings["hooks"]["SessionStart"] for hook in group["hooks"]
                    if hook.get("command", "").startswith("powershell.exe ")]
        self.assertEqual(len(commands), 1)
        # 保持产品生成的原命令；真实cmd→PowerShell→持久Python，stdin为真实JSON。
        hooked = subprocess.run([str(self.cmd), "/d", "/s", "/c", commands[0]], cwd=self.project, env=self.env,
                                input=json.dumps({"cwd": str(self.project), "session_id": "native-e2e",
                                                  "hook_event_name": "SessionStart", "source": "resume"}),
                                capture_output=True, text=True, encoding="utf-8", timeout=180)
        self.assert_success(hooked)
        output = json.loads(hooked.stdout)["hookSpecificOutput"]
        self.assertEqual(output["hookEventName"], "SessionStart")
        self.assertTrue(output["additionalContext"])
        self.assertNotIn("permissionDecision", output)
        self.assertFalse(self.cache.exists())
        self.assert_sentinel()
        self.assertEqual(before, self.profile_snapshot())


@unittest.skipUnless(os.name == "nt" and __name__ == "__main__", "缺能力fixture仅显式原生入口")
class WindowsNpxMissingCapabilityTest(NpxFixture):
    def assert_no_symlink_privilege(self):
        # 只查询新令牌，不启用/赋予权限。DWORD0不能代替真实令牌缺权限事实。
        handle, dword = ctypes.c_void_p, ctypes.c_uint32
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        api = ctypes.WinDLL("advapi32", use_last_error=True)
        class Luid(ctypes.Structure):
            _fields_ = [("low", dword), ("high", ctypes.c_int32)]
        class Entry(ctypes.Structure):
            _fields_ = [("luid", Luid), ("attributes", dword)]
        kernel.GetCurrentProcess.restype = handle
        kernel.CloseHandle.argtypes, kernel.CloseHandle.restype = [handle], ctypes.c_int32
        api.OpenProcessToken.argtypes = [handle, dword, ctypes.POINTER(handle)]
        api.GetTokenInformation.argtypes = [handle, ctypes.c_int, handle, dword, ctypes.POINTER(dword)]
        api.LookupPrivilegeValueW.argtypes = [ctypes.c_wchar_p, ctypes.c_wchar_p, ctypes.POINTER(Luid)]
        token = handle()
        if not api.OpenProcessToken(kernel.GetCurrentProcess(), 8, ctypes.byref(token)):
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            wanted, size = Luid(), dword()
            if not api.LookupPrivilegeValueW(None, "SeCreateSymbolicLinkPrivilege", ctypes.byref(wanted)):
                raise ctypes.WinError(ctypes.get_last_error())
            ctypes.set_last_error(0)
            api.GetTokenInformation(token, 3, None, 0, ctypes.byref(size))
            self.assertEqual(ctypes.get_last_error(), 122)
            data = ctypes.create_string_buffer(size.value)
            if not api.GetTokenInformation(token, 3, data, len(data), ctypes.byref(size)):
                raise ctypes.WinError(ctypes.get_last_error())
            count = dword.from_buffer(data).value
            self.assertLessEqual(4 + count * ctypes.sizeof(Entry), len(data))
            entries = ctypes.cast(ctypes.addressof(data) + 4, ctypes.POINTER(Entry))
            self.assertFalse(any((entries[index].luid.low, entries[index].luid.high) ==
                                 (wanted.low, wanted.high) for index in range(count)))
        finally:
            if not kernel.CloseHandle(token):
                raise ctypes.WinError(ctypes.get_last_error())

    def test_real_init_refuses_before_project_and_central_state_writes(self):
        import winreg
        self.assert_no_symlink_privilege()
        # registry值只确认CI夹具；成功/拒绝仍取决于产品真实同flags3调用。
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                            r"SOFTWARE\Microsoft\Windows\CurrentVersion\AppModelUnlock",
                            access=winreg.KEY_READ | winreg.KEY_WOW64_64KEY) as key:
            value, kind = winreg.QueryValueEx(key, "AllowDevelopmentWithoutDevLicense")
        self.assertEqual((value, kind), (0, winreg.REG_DWORD))
        before = self.profile_snapshot()
        result = self.execute(["init"])
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("1314", result.stdout + result.stderr)
        self.assertEqual([self.sentinel], list(self.project.iterdir()))
        self.assertFalse(self.state.exists())
        self.assert_sentinel()
        self.assertEqual(before, self.profile_snapshot())
        print("真实npx init缺软链能力拒绝1314；项目/中央state写前保持", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--case", choices=("positive", "denied"), required=True)
    parser.add_argument("--root", required=True)
    parser.add_argument("--tgz", required=True)
    arguments = parser.parse_args()
    FIXTURE_ROOT = Path(arguments.root).absolute()
    LOCAL_ARCHIVE = arguments.tgz
    if not FIXTURE_ROOT.is_dir():
        raise SystemExit("需要runner已创建并授权的fixture根")
    selected = WindowsNpxEndToEndTest if arguments.case == "positive" else WindowsNpxMissingCapabilityTest
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(selected)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    raise SystemExit(0 if result.wasSuccessful() and not result.skipped else 1)
