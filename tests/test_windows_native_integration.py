"""真实 windows-curses/ConPTY 生产界面验收；只使用请求私有宿主与项目。

测试通过键盘操作正式 manager.cli → manager.tui，屏幕、属性和模式只来自
ReadConsoleOutputW 等 Win32 读取。Mac 的导入或 skip 不计入任何原生通过。
"""

from __future__ import annotations

import base64
from contextlib import contextmanager
import importlib.metadata
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import time
import unicodedata
import unittest
from unittest.mock import patch
import uuid

from lib import runtime_store
from lib.install.install_process import capture_process
from lib.central.role_preferences import snapshot as preference_snapshot
from lib.hosts.native_context import HostPaths, NativeContext
from manager import central_runtime, model_preferences, project_service, service
from tests.windows_conpty import ConPTYProcess
from tests.windows_console_observer import _publish, message_path, read_message


PACK = Path(__file__).resolve().parents[1]
KEYS = {"left": "\x1b[D", "right": "\x1b[C", "up": "\x1b[A", "down": "\x1b[B",
        "home": "\x1b[H", "end": "\x1b[F", "enter": "\r", "esc": "\x1b",
        "tab": "\t", "backtab": "\x1b[Z", "backspace": "\x7f"}


def isolated_environment(home):
    """消除模型路由/凭据环境对私有目录的覆盖，不读取或记录这些值。"""
    prefixes = ("anthropic_", "claude_", "codex_", "openai_", "aws_", "azure_",
                "google_", "vertex_region_claude_")
    environment = {key: value for key, value in os.environ.items()
                   if not key.casefold().startswith(prefixes)}
    environment.update(HOME=str(home), USERPROFILE=str(home),
                       APPDATA=str(home / "AppData/Roaming"), LOCALAPPDATA=str(home / "AppData/Local"))
    return environment


@unittest.skipUnless(os.name == "nt", "真实 Legacy/Win32 边界必须在 Windows 执行")
class WindowsAcceptanceScriptNativeTest(unittest.TestCase):
    def test_native_acceptance_git_resolution_preserves_path_priority(self):
        with tempfile.TemporaryDirectory(prefix="awf-git-preflight-", dir=os.environ.get("AGENT_WORKFLOW_TEST_SCRATCH")) as raw:
            root = Path(raw).resolve()
            found = shutil.which("git.exe")
            self.assertIsNotNone(found, "需要已有 Git；测试不下载或安装第二套 Git")
            real_git = Path(found).resolve(strict=True)
            alias_directory, empty_directory, home = root / "git-metadata-alias", root / "empty-path", root / "private-home"
            alias_directory.mkdir();empty_directory.mkdir();home.mkdir()
            # 复用本轮已经要求的原生链接能力，只创建私有文件链接供 Get-Command
            # 实际枚举。真实 Git 目录排第一；第二链接从不执行，不复制或部署 DLL。
            os.symlink(real_git, alias_directory / "git.exe")
            environment = isolated_environment(home)
            pwsh = Path(os.environ.get("AGENT_WORKFLOW_PWSH", str(Path(os.environ["ProgramFiles"]) / "PowerShell/7/pwsh.exe")))
            self.assertTrue(pwsh.is_absolute() and pwsh.is_file(), "需要已有 PowerShell 7+")
            environment.update(AWF_GIT_TEST_SCRIPT=str(PACK / "scripts/windows_acceptance.ps1"),
                               AWF_GIT_TEST_REAL=str(real_git), AWF_GIT_TEST_PACK=str(PACK))
            script = r'''
$ErrorActionPreference = 'Stop'
$PSNativeCommandArgumentPassing = 'Legacy'
$pathBefore = $env:PATH
$tokens = $null
$errors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseFile($env:AWF_GIT_TEST_SCRIPT, [ref]$tokens, [ref]$errors)
if ($errors.Count -ne 0) { throw ($errors | Out-String) }
$definitions = @($ast.FindAll({ param($node)
    $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and $node.Name -ceq 'Resolve-AcceptanceGit'
}, $true))
if ($definitions.Count -ne 1) { throw 'Expected the actual production Git resolver.' }
. ([scriptblock]::Create($definitions[0].Extent.Text))
if ($env:AWF_GIT_TEST_MODE -eq 'missing') {
    $refused = $false
    try { Resolve-AcceptanceGit | Out-Null } catch {
        if ($_.FullyQualifiedErrorId -notlike '*CommandNotFoundException*') { throw }
        $refused = $true
    }
    if (-not $refused) { throw 'A missing Git was silently accepted.' }
    Write-Output 'ACCEPTANCE_GIT_MISSING_REFUSED'
} else {
    $gitApplications = @(Get-Command git.exe -CommandType Application -ErrorAction Stop)
    if ($gitApplications.Count -lt 2) { throw 'The real command discovery did not observe both PATH applications.' }
    $git = Resolve-AcceptanceGit
    if ($git -isnot [string] -or [string]::IsNullOrWhiteSpace($git)) { throw 'Git selection was not one string.' }
    if (-not [string]::Equals($git, $env:AWF_GIT_TEST_REAL, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw 'The production resolver did not preserve the first PATH application.'
    }
    $head = (& $git -C $env:AWF_GIT_TEST_PACK rev-parse HEAD | Out-String).Trim()
    $nativeExit = $LASTEXITCODE
    if ($nativeExit -ne 0 -or $head -notmatch '\A[0-9a-f]{40}\z') { throw 'The selected real Git could not consume the checkout.' }
    [ordered]@{ matches = $gitApplications.Count; selected = $git; first = $gitApplications[0].Path; git_exit = $nativeExit; head = $head } |
        ConvertTo-Json -Compress | Write-Output
    Write-Output 'ACCEPTANCE_GIT_MULTIPATH_REAL_BOUNDARY_OK'
}
if ($env:PATH -cne $pathBefore -or $PSNativeCommandArgumentPassing -cne 'Legacy') { throw 'The resolver changed shell settings.' }
'''
            encoded = base64.b64encode(script.encode("utf-16-le")).decode("ascii")
            argv = [str(pwsh), "-NoLogo", "-NoProfile", "-NonInteractive", "-EncodedCommand", encoded]
            for mode in ("multiple", "missing"):
                with self.subTest(mode=mode):
                    selected_environment = dict(environment)
                    selected_environment["AWF_GIT_TEST_MODE"] = mode
                    selected_environment["PATH"] = (str(real_git.parent) + os.pathsep + str(alias_directory)
                        + os.pathsep + environment.get("PATH", "")) if mode == "multiple" else str(empty_directory)
                    # 两种 PATH 使用独立的实际 PS 子进程，避免正例的命令发现
                    # 缓存影响无 Git 负控；仅测试环境变化，用户 PATH 完整保留。
                    result = capture_process(argv, env=selected_environment, timeout=60)
                    line = json.dumps({"kind": "acceptance-git", "mode": mode, "argv": argv, "exit": result.returncode,
                        "stdout_base64": base64.b64encode(result.stdout).decode("ascii"),
                        "stderr_base64": base64.b64encode(result.stderr).decode("ascii")}, ensure_ascii=True)
                    print("\n[native Git preflight evidence] " + line, flush=True)
                    if target := os.environ.get("AWF_TEST_EVIDENCE_LOG"):
                        with open(target, "a", encoding="utf-8") as stream:stream.write(line + "\n")
                    self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                    marker = b"ACCEPTANCE_GIT_MULTIPATH_REAL_BOUNDARY_OK" if mode == "multiple" else b"ACCEPTANCE_GIT_MISSING_REFUSED"
                    self.assertIn(marker, result.stdout)

    def test_native_acceptance_identity_preserves_legacy_quotes_and_exit_codes(self):
        with tempfile.TemporaryDirectory(prefix="awf-acceptance-中文 e\u0301-", dir=os.environ.get("AGENT_WORKFLOW_TEST_SCRATCH")) as raw:
            root = Path(raw).resolve()
            home = root / "private-home"
            home.mkdir()
            environment = isolated_environment(home)
            pwsh = Path(os.environ.get("AGENT_WORKFLOW_PWSH", str(Path(os.environ["ProgramFiles"]) / "PowerShell/7/pwsh.exe")))
            self.assertTrue(pwsh.is_absolute() and pwsh.is_file(), "需要已有 PowerShell 7+")
            negative = root / "真实双流退出.py"
            negative.write_text('import os,sys\nos.write(1,b\'ACCEPTANCE_OUT_"quoted"\\n\'*2048)\nos.write(2,b\'ACCEPTANCE_ERR_"quoted"\\n\'*2048)\nsys.exit(27)\n', encoding="utf-8")
            environment.update(AWF_ACCEPTANCE_TEST_ROOT=str(root), AWF_ACCEPTANCE_TEST_PYTHON=sys.executable,
                AWF_ACCEPTANCE_TEST_SCRIPT=str(PACK / "scripts/windows_acceptance.ps1"),
                AWF_ACCEPTANCE_TEST_NEGATIVE=str(negative))
            # AST 只载入仓内实际生产函数；没有镜像其 argv 拼接、文件发布、
            # 日志或退出码实现，也不执行 Win11 整套入口以递归启动本测试。
            # Legacy 仅属于新建 PS 子进程，不改变调用用户的 shell 偏好。
            script = r'''
$ErrorActionPreference = 'Stop'
$PSNativeCommandArgumentPassing = 'Legacy'
$passingBefore = $PSNativeCommandArgumentPassing
$pathBefore = $env:PATH
$tokens = $null
$errors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseFile($env:AWF_ACCEPTANCE_TEST_SCRIPT, [ref]$tokens, [ref]$errors)
if ($errors.Count -ne 0) { throw ($errors | Out-String) }
foreach ($name in @('Write-AcceptanceLog', 'Invoke-AcceptancePython', 'Write-AcceptanceIdentity')) {
    $definitions = @($ast.FindAll({ param($node)
        $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and $node.Name -ceq $name
    }, $true))
    if ($definitions.Count -ne 1) { throw "Expected one actual production function: $name" }
    . ([scriptblock]::Create($definitions[0].Extent.Text))
}
$workspace = Join-Path $env:AWF_ACCEPTANCE_TEST_ROOT 'identity-workspace'
[System.IO.Directory]::CreateDirectory($workspace) | Out-Null
$identityPath = Join-Path $workspace 'environment.json'
$log = Join-Path $workspace 'acceptance.log'
$interpreter = Get-Item -LiteralPath $env:AWF_ACCEPTANCE_TEST_PYTHON
Write-AcceptanceIdentity
if (-not (Test-Path -LiteralPath $identityPath)) { throw 'The real identity step did not produce its report.' }
$refused = $false
try {
    Invoke-AcceptancePython -Arguments @('-I', '-B', '-X', 'utf8', $env:AWF_ACCEPTANCE_TEST_NEGATIVE)
} catch {
    if ($_.Exception.Message -notlike '*exit 27*') { throw }
    $refused = $true
}
if (-not $refused) { throw 'The real launcher swallowed exit 27.' }
if ($PSNativeCommandArgumentPassing -cne $passingBefore -or $env:PATH -cne $pathBefore) { throw 'The production boundary changed shell preferences.' }
Write-Output 'ACCEPTANCE_LEGACY_REAL_BOUNDARY_OK'
'''
            encoded = base64.b64encode(script.encode("utf-16-le")).decode("ascii")
            argv = [str(pwsh), "-NoLogo", "-NoProfile", "-NonInteractive", "-EncodedCommand", encoded]
            # 沿用既有 Job/capture owner 与双流排空；此测试不新增进程清理器。
            result = capture_process(argv, env=environment, timeout=60)
            log_path = root / "identity-workspace/acceptance.log"
            logs = log_path.read_bytes() if log_path.exists() else b""
            value = {"kind": "acceptance-legacy", "argv": argv, "exit": result.returncode,
                     "stdout_base64": base64.b64encode(result.stdout).decode("ascii"),
                     "stderr_base64": base64.b64encode(result.stderr).decode("ascii"),
                     "log_base64": base64.b64encode(logs).decode("ascii")}
            line = json.dumps(value, ensure_ascii=True)
            print("\n[native acceptance evidence] " + line, flush=True)
            if target := os.environ.get("AWF_TEST_EVIDENCE_LOG"):
                with open(target, "a", encoding="utf-8") as stream:stream.write(line + "\n")
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn(b"ACCEPTANCE_LEGACY_REAL_BOUNDARY_OK", result.stdout)
            self.assertIn(b'ACCEPTANCE_OUT_"quoted"', logs)
            self.assertIn(b'ACCEPTANCE_ERR_"quoted"', logs)
            self.assertIn(b"exit_code=0", logs)
            self.assertIn(b"exit_code=27", logs)
            identity = json.loads((root / "identity-workspace/environment.json").read_text(encoding="utf-8"))
            self.assertTrue(os.path.samefile(identity["executable"], sys.executable))
            self.assertEqual(identity["windows_curses"], "2.4.2")


@unittest.skipUnless(os.name == "nt", "控制台访问权限必须经真实 ConPTY 观测")
class NativeConsoleObserverNativeTest(unittest.TestCase):
    def test_native_console_cursor_access_diagnostics(self):
        with tempfile.TemporaryDirectory(prefix="awf-console-access-", dir=os.environ.get("AGENT_WORKFLOW_TEST_SCRATCH")) as raw:
            root = Path(raw).resolve()
            report = root / "access.json"
            code = "import sys;sys.path.insert(0,sys.argv[1]);from tests.windows_console_observer import cursor_access_diagnostics;cursor_access_diagnostics(sys.argv[2])"
            argv = [sys.executable, "-I", "-B", "-X", "utf8", "-c", code, str(PACK), str(report)]
            environment = isolated_environment(root)
            process = ConPTYProcess(argv, cwd=PACK, env=environment)
            data = None
            try:
                # 立即进入唯一 owner 的 wait/capture，避免先等 UI 响应超时，
                # 再尝试捕捉已经退出的 venv payload；累计屏障仍完整执行。
                self.assertEqual(process.wait(timeout=20), 0)
                data = json.loads(report.read_text(encoding="utf-8"))
                self.assertTrue(os.path.samefile(data["executable"], sys.executable))
                for label in ("read", "readwrite"):
                    row = data["results"][label]
                    self.assertNotIn("open_error", row)
                    for name in ("mode", "buffer", "screen"):
                        self.assertTrue(row[name]["ok"], (label, name, row[name]))
                    self.assertGreater(row["screen"]["width"], 0)
                    self.assertGreater(row["screen"]["height"], 0)
                # READ 的已知错误完整保留；READ|WRITE 也失败或只留下零值，
                # 本节点必须失败，不能把 0/False 光标当成兼容或 UI 通过。
                cursor = data["results"]["readwrite"]["cursor"]
                self.assertTrue(cursor["ok"], cursor)
                self.assertTrue(1 <= cursor["size"] <= 100, cursor)
            finally:
                try:process.close()
                finally:
                    if data is None and report.exists():data = json.loads(report.read_text(encoding="utf-8"))
                    value = {"kind": "console-access-diagnostics", "argv": argv,
                             "exit": process.returncode, "closed": process.closed, "native": data,
                             "raw_base64": base64.b64encode(process.raw_output).decode("ascii")}
                    line = json.dumps(value, ensure_ascii=True)
                    print("\n[native console access evidence] " + line, flush=True)
                    if target := os.environ.get("AWF_TEST_EVIDENCE_LOG"):
                        with open(target, "a", encoding="utf-8") as stream:stream.write(line + "\n")


class NativeUI:
    """测试端请求只读快照；进程/管道回收完全交给既有 ConPTYProcess。"""

    def __init__(self, case, root, argv, environment):
        self.case, self.root, self.argv = case, root, argv
        self.sequence, self.frames = 0, []
        self.started_ns, self.events = time.monotonic_ns(), []
        self.inflight = None
        self.last_request = self.last_response = None
        # 两端各自独占一个方向；目录在 child 启动前建立，消息名发布后不可变。
        (root / "requests").mkdir()
        (root / "responses").mkdir()
        self.process = ConPTYProcess(argv, cwd=PACK, env=environment, columns=120, rows=36)

    def key(self, value):
        payload = KEYS.get(value, value)
        # 记录测试输入的写入边界；返回长度只证明 ConPTY 接受了字节，不能推定
        # curses 已消费/派发。组合查询正文不写入诊断，只记录测试单键和字节数。
        event = {"kind": "input", "key": value if value in KEYS or len(value) == 1 else None,
                 "bytes": len(payload.encode("utf-8")), "started_ns": time.monotonic_ns() - self.started_ns}
        try:
            event["accepted_bytes"] = self.process.write(payload)
            self.case.assertEqual(event["accepted_bytes"], event["bytes"])
        except BaseException as exc:
            event["error"] = type(exc).__name__
            raise
        finally:
            event["finished_ns"] = time.monotonic_ns() - self.started_ns
            self.events.append(event)

    def snapshot(self, timeout=5):
        if self.inflight is not None:
            raise RuntimeError("原生观察已有请求在途，不能提交第二个请求")
        self.sequence += 1
        number = self.inflight = self.sequence
        request = message_path(self.root, "requests", number)
        response = message_path(self.root, "responses", number)
        try:
            _publish(request, {"number": number})
            self.last_request = request
            deadline = time.monotonic() + timeout
            while time.monotonic() < deadline:
                error = self.root / "observer-error.json"
                if error.exists():
                    self.case.fail(error.read_text(encoding="utf-8"))
                if response.exists():
                    value = read_message(response, number, response=True)
                    self.last_response = response
                    observation = value["snapshot"]["observation"]
                    self.case.assertEqual(observation["number"], number)
                    self.case.assertTrue(0 < len(observation["main_stack"]) <= 24)
                    return value["snapshot"]
                if (self.root / "final.json").exists():
                    self.case.fail("生产 TUI 提前结束：" + (self.root / "final.json").read_text(encoding="utf-8"))
                time.sleep(0.02)
            self.case.fail("原生控制台观察响应超时；VT=" + repr(self.process.raw_output[-3000:]))
        finally:
            self.inflight = None

    @staticmethod
    def text(frame):
        # Windows 可返回预组合字符；等价 Unicode 文本只用于查找，原始 UTF-16
        # 字符格与颜色属性始终完整保存，光标/布局断言仍使用原生坐标。
        return unicodedata.normalize("NFC", "\n".join(frame["lines"]))

    def wait(self, label, predicate, timeout=30):
        deadline, last = time.monotonic() + timeout, None
        event = {"kind": "wait", "label": label, "started_ns": time.monotonic_ns() - self.started_ns,
                 "first_number": self.sequence + 1, "outcome": "error"}
        try:
            while time.monotonic() < deadline:
                last = self.snapshot()
                if last["stable"] and predicate(last):
                    self.frames.append({"label": label, "native": last})
                    event["outcome"] = "success"
                    return last
                time.sleep(0.03)
            event["outcome"] = "timeout"
            if last is not None:
                self.frames.append({"label": label + "-failed", "native": last})
            self.case.fail(f"原生屏幕未达到 {label}：\n" + (self.text(last) if last else "无快照"))
        finally:
            # 父子进程各记自身单调时间，以同一请求序号关联，绝不假定两个进程
            # 的相对起点相同；失败也在既有 record finally 中保留实际耗时。
            event["last_number"] = self.sequence
            event["finished_ns"] = time.monotonic_ns() - self.started_ns
            self.events.append(event)

    def text_is(self, *values, absent=(), timeout=30):
        return self.wait(" / ".join(values), lambda frame:
                         all(unicodedata.normalize("NFC", text) in self.text(frame) for text in values)
                         and not any(text in self.text(frame) for text in absent), timeout)

    def ready(self):
        return self.main_is("角色模型", "后端开发")

    @classmethod
    def _main_ready(cls, frame, values):
        # 主标题/草稿数会透过退出弹层留在背景；同一快照还必须证明原生弹层
        # 标题已消失，才能发送下一按键。沿用原等待预算，不增加第二段等待。
        text = cls.text(frame)
        return cls._modal_title(frame) is None and "执行中" not in text and all(value in text for value in values)

    def main_is(self, *values):
        return self.wait(" / ".join(values), lambda frame:self._main_ready(frame, values))

    def assert_frame(self, frame):
        # 直接核对原生格子的边界，中文内容/状态/提示不能覆盖粗框；这里不
        # 导入生产 cell_width，也不以另一个终端模拟器推导最终落格位置。
        units = frame["units"]
        self.case.assertEqual(units[0], [ord("┏"), *([ord("━")] * (frame["width"] - 2)), ord("┓")])
        self.case.assertEqual(units[-1], [ord("┗"), *([ord("━")] * (frame["width"] - 2)), ord("┛")])
        for row in units[1:-1]:
            self.case.assertIn(row[0], (ord("┃"), ord("┠")))
            self.case.assertIn(row[-1], (ord("┃"), ord("┨")))

    def role(self):
        self.key("right");self.key("/xy-backend\r")
        self.text_is("角色模型", "后端开发", "/ xy-backend")

    @staticmethod
    def _modal_title(frame):
        # 既定布局的弹层标题位于原生第 4 行；只读取 ReadConsoleOutputW
        # 已取得的文字范围，不从状态提示、App 私有状态或模拟 Screen 推断视图。
        # 标题与后续计数之间由横线分隔，完整标题去掉两端排版空白后才比较。
        lines = frame["lines"]
        if len(lines) <= 4:return None
        header = unicodedata.normalize("NFC", lines[4])
        _, corner, content = header.partition("╭")
        title, divider, _ = content.partition("─")
        return title.strip() if corner and divider else None

    @classmethod
    def _choice_ready(cls, frame, next_text):
        text, title = cls.text(frame), cls._modal_title(frame)
        previous = "选择模型" if next_text == "选择推理级别" else "选择推理级别"
        # 模型确认后的合法 toast 含“已选择模型”，不能用整屏 absent 误判
        # 旧弹层仍在。目标/旧视图仅在同一原生标题范围比较完整标题；暂存
        # 仍同时要求成功文字和推理弹层消失，执行中条件也按原合同继续拒绝。
        if "执行中" in text or title == previous:return False
        return title == next_text if next_text == "选择推理级别" else next_text in text

    def choose(self, query, next_text):
        # 第一回车只接受筛选，第二回车才激活正式选择器中的选项。
        self.key("/" + query + "\r")
        self.text_is("/ " + query)
        self.key("enter")
        return self.wait(next_text, lambda frame:self._choice_ready(frame, next_text))

    def model(self, query, effort="high"):
        self.key("m");self.text_is("选择模型", absent=("执行中",))
        self.choose(query, "选择推理级别")
        self.choose(effort, "已暂存，尚未保存")

    def preview(self):
        self.key("s")
        return self.wait("保存预览 / 确认备份并保存", lambda frame:
                         self._modal_title(frame) == "保存预览" and "确认备份并保存" in self.text(frame)
                         and "执行中" not in self.text(frame))

    def save(self):
        self.preview()
        self.key("enter");self.text_is("操作结果", "已保存模型配置", absent=("执行中",))
        self.key("esc");self.ready()

    def command(self, query, result):
        self.key(":" + query)
        self.text_is("命令面板", query)
        self.key("enter")
        self.text_is(result, absent=("执行中", "命令面板"))

    def finish(self, interrupted=False):
        if interrupted:self.process.send_ctrl_c()
        else:self.key("q")
        self.case.assertEqual(self.process.wait(timeout=30), 130 if interrupted else 0)
        final = json.loads((self.root / "final.json").read_text(encoding="utf-8"))
        self.case.assertIsNone(final["error"], final)
        self.case.assertEqual(final["observer_errors"], [])
        self.case.assertEqual(final["exit"], 130 if interrupted else 0)
        self.case.assertEqual(final["windows_curses"], "2.4.2")
        self.case.assertTrue(os.path.samefile(final["executable"], sys.executable))
        # 比较同一 ConPTY 内 wrapper 前后真实输入/输出模式，不能拿宿主 runner
        # 的默认模式或仅凭 q/进程结束推断终端已恢复。
        for field in ("input_mode", "output_mode", "cursor_visible", "cursor_size"):
            self.case.assertEqual(final["after"][field], final["before"][field], field)
        return final

    def record(self):
        final_path = self.root / "final.json"
        value = {"kind": "native-tui", "test": self.case.id(), "argv": self.argv,
                 "pid": self.process.pid, "exit": self.process.returncode, "closed": self.process.closed,
                 "raw_base64": base64.b64encode(self.process.raw_output).decode("ascii"),
                 "frames": self.frames, "events": self.events,
                 "final": json.loads(final_path.read_text(encoding="utf-8")) if final_path.exists() else None}
        line = json.dumps(value, ensure_ascii=True)
        print("\n[native TUI evidence] " + line, flush=True)
        target = os.environ.get("AWF_TEST_EVIDENCE_LOG")
        if target:
            with open(target, "a", encoding="utf-8") as stream:
                stream.write(line + "\n")


@unittest.skipUnless(os.name == "nt", "必须真实 Windows 执行；Mac 收集/skip 不是原生验收")
class WindowsNativeTUIIntegrationTest(unittest.TestCase):
    """唯一清单登记这三个真实节点；方法互不依赖执行顺序。"""

    @classmethod
    def setUpClass(cls):
        if importlib.metadata.version("windows-curses") != "2.4.2":
            raise RuntimeError("TUI 验收需要 requirements-windows.txt 锁定的 windows-curses 2.4.2")
        cls.temporary = tempfile.TemporaryDirectory(prefix="awf-native-tui-", dir=os.environ.get("AGENT_WORKFLOW_TEST_SCRATCH"))
        cls.addClassCleanup(cls.temporary.cleanup)
        cls.workspace = Path(cls.temporary.name).resolve()
        cls.state, cls.home, cls.scan = cls.workspace / "state", cls.workspace / "host-home", cls.workspace / "projects"
        cls.scan.mkdir();cls.home.mkdir()
        # 生产 discover 按合同继承调用环境，因此 fixture 的父服务调用和
        # ConPTY 子进程都必须使用同一私有环境。只隔离当前测试进程的环境字典，
        # 不替换任何生产发现器、Win32 API、curses 方法或屏幕；类结束完整恢复。
        environment_patch = patch.dict(os.environ, isolated_environment(cls.home), clear=True)
        environment_patch.start();cls.addClassCleanup(environment_patch.stop)
        cls.context = NativeContext.for_state(cls.state, host_paths=HostPaths.for_home(cls.home, environment={}))
        paths = cls.context.host_paths
        paths.codex.mkdir(parents=True);paths.claude.mkdir(parents=True);paths.antigravity.mkdir(parents=True)
        (paths.codex / "config.toml").write_text('model_catalog_json="models.json"\n', encoding="utf-8")
        (paths.codex / "models.json").write_text(json.dumps({"models": [
            {"id": "fixture-model", "display_name": "本地原生模型", "supported_reasoning_levels": ["high", "max"]}]}), encoding="utf-8")
        (paths.claude / "settings.json").write_text(json.dumps({"modelPicker": {"options": [
            {"value": "fixture-claude", "label": "本地 Claude 模型"}]}}), encoding="utf-8")
        # 从唯一正式 core 边界导入一次；不复制源码候选，也不替换生产安装器。
        # 项目与宿主资源的启用、偏好、停用始终走已冻结的中央业务 API。
        cls.core = runtime_store.import_core(PACK, cls.state)
        central_runtime.apply(central_runtime.preview(cls.state, binding=cls.core.binding(), native_context=cls.context))

    def setUp(self):
        self.root = self.workspace / uuid.uuid4().hex
        self.root.mkdir()
        self.project = self.scan / ("中文 e\u0301 项目-" + uuid.uuid4().hex[:8])
        self.project.mkdir()
        (self.project / "pyproject.toml").write_text('[project]\nname="native-tui-fixture"\nversion="0.1.0"\n', encoding="utf-8")
        self.apply_project("add", enable=True)
        self.addCleanup(self.cleanup_preferences_and_project)
        self.environment = isolated_environment(self.home)
        for name in ("NO_COLOR", "CODEX_HOME", "CLAUDE_CONFIG_DIR", "AGENT_WORKFLOW_STATE_DIR",
                     "AGENT_WORKFLOW_RUNTIME_BINDING", "AGENT_WORKFLOW_PROJECT_ROOT", "AGENT_WORKFLOW_CORE_ROOT", "AGENT_WORKFLOW_CONFIG_PATH"):
            self.environment.pop(name, None)
        self.environment.update(HOME=str(self.home), USERPROFILE=str(self.home),
            APPDATA=str(self.home / "AppData/Roaming"), LOCALAPPDATA=str(self.home / "AppData/Local"),
            PYTHONDONTWRITEBYTECODE="1", AGENT_WORKFLOW_PWSH=os.environ.get("AGENT_WORKFLOW_PWSH", ""))
        # 空覆盖不能传递为坏的显式 pwsh；让正式校验选择已有标准 PS7 路径。
        if not self.environment["AGENT_WORKFLOW_PWSH"]:self.environment.pop("AGENT_WORKFLOW_PWSH")

    def apply_project(self, action, **options):
        plan = project_service.preview_project(self.state, self.project, action, native_context=self.context, **options)
        self.assertTrue(plan.summary["can_apply"], plan.summary)
        return project_service.apply_project(plan)

    def cleanup_preferences_and_project(self):
        # 每方法均回到空的通用默认，失败也由真实恢复 API 清理自己改过的字段；
        # 不 unlink 收据、不手改配置、不借下一方法的 setUp 修复前一方法状态。
        current = preference_snapshot(self.state)[1].get("codex", {}).get("xy-backend", {})
        if current:
            catalogs = model_preferences.load_catalogs(self.state, None, "codex", native_context=self.context)
            plan = model_preferences.preview(self.state, None, "codex", {"xy-backend": {"model": None, "effort": None}}, catalogs,
                                             native_context=self.context)
            model_preferences.apply(plan)
        self.apply_project("del")

    @contextmanager
    def ui(self, *, monochrome=False):
        directory = self.root / "console"
        directory.mkdir()
        environment = dict(self.environment)
        if monochrome:environment["NO_COLOR"] = "1"
        arguments = ["--state-dir", str(self.state), "--host-home", str(self.home),
                     "--scan-root", str(self.scan), "tui", "--project", str(self.project)]
        # 保持生产 venv 的 sys.executable，显式 -I 与唯一仓库根；不退回缺少
        # windows-curses 的 base Python，不修补 sys.stdin/stdout 或 curses。
        code = "import sys;sys.path.insert(0,sys.argv[1]);from tests.windows_console_observer import run_observed;raise SystemExit(run_observed(sys.argv[2],sys.argv[3:]))"
        argv = [sys.executable, "-I", "-B", "-X", "utf8", "-u", "-c", code, str(PACK), str(directory), *arguments]
        ui = NativeUI(self, directory, argv, environment)
        try:
            ui.ready()
            yield ui
        finally:
            # 唯一 owner 的 close 对异常和正常退出同样有效；不另建 Job/PID
            # 清理器，不以任意睡眠替代底座已验证的累计成员静止屏障。
            try:ui.process.close()
            finally:ui.record()

    def test_native_tui_project_preferences_lifecycle_and_focus(self):
        with self.ui() as ui:
            first = ui.ready()
            ui.assert_frame(first)
            # 使用真实 Windows 共享句柄钉住上一轮请求/响应，再通过实际 IPC
            # 取得下一帧。旧固定文件名的 replace 会在此确定性冲突；序号消息
            # 必须保留旧字节并返回新的真实 Win32 快照，不能改为屏幕替身。
            previous_sequence = ui.sequence
            previous_request, previous_response = ui.last_request, ui.last_response
            with previous_request.open("rb") as request_reader, previous_response.open("rb") as response_reader:
                request_before, response_before = request_reader.read(), response_reader.read()
                next_frame = ui.snapshot()
                ui.assert_frame(next_frame)
                self.assertEqual(ui.sequence, previous_sequence + 1)
                self.assertNotEqual(ui.last_request, previous_request)
                self.assertNotEqual(ui.last_response, previous_response)
                request_reader.seek(0);response_reader.seek(0)
                self.assertEqual(request_reader.read(), request_before)
                self.assertEqual(response_reader.read(), response_before)
                ui.frames.append({"label": "held-reader next native frame", "native": next_frame})
            self.assertIn("[1 Codex]", ui.text(first))
            # 活动 tab 的原生属性必须有配色；焦点另由 ◈/▌/▸ 表达，颜色非唯一含义。
            colors = {value & 7 for row in first["attributes"] for value in row}
            self.assertTrue(colors - {0, 7}, colors)
            ui.key("left");ui.text_is("◈ 项目列表")
            ui.key("left");ui.text_is("◈ 项目列表")
            ui.role();ui.text_is("◈ 角色模型")
            before = (self.project / ".agent-workflow/project.yaml").read_bytes()
            ui.key("m");ui.text_is("选择模型")
            ui.key("tab");ui.key("right");ui.text_is("选择模型", "[1 Codex]")
            ui.key("esc");ui.text_is("已取消本次选择")
            self.assertEqual((self.project / ".agent-workflow/project.yaml").read_bytes(), before)
            ui.model("fixture-model", "max")
            ui.key("q");ui.text_is("退出确认", "项未应用草稿")
            ui.key("esc");ui.main_is("角色模型", "1 项未保存")
            ui.preview()
            ui.key("esc");ui.text_is("已取消保存预览", "1 项未保存")
            self.assertEqual((self.project / ".agent-workflow/project.yaml").read_bytes(), before)
            ui.save()
            value = service.role_settings(self.project, "codex", "xy-backend", state=self.state, native_context=self.context)
            self.assertEqual((value["model"], value["effort"]), ("fixture-model", "max"))
            # e 的独立字段路径必须保留已经保存的模型，不靠模型向导顺带
            # 选择推理来代替这个合同；真实文件结果与界面成功反馈一起验证。
            ui.key("e");ui.text_is("选择推理级别", absent=("执行中",))
            ui.choose("high", "已暂存，尚未保存");ui.save()
            value = service.role_settings(self.project, "codex", "xy-backend", state=self.state, native_context=self.context)
            self.assertEqual((value["model"], value["effort"]), ("fixture-model", "high"))
            ui.key("tab");ui.text_is("[2 Claude Code]")
            ui.role();ui.model("fixture-claude", "high");ui.save()
            value = service.role_settings(self.project, "claude", "xy-backend", state=self.state, native_context=self.context)
            self.assertEqual((value["model"], value["effort"]), ("fixture-claude", "high"))
            ui.key("tab");ui.text_is("[3 Antigravity]")
            ui.key("e");ui.text_is("Antigravity 静态角色仅支持继承")
            ui.key("tab");ui.text_is("[1 Codex]")
            ui.key("backtab");ui.text_is("[3 Antigravity]")
            ui.key("1");ui.text_is("[1 Codex]")
            ui.key("p");ui.text_is("项目管理 · 只读预览", "确认停用工作流")
            ui.key("esc");ui.ready()
            self.assertTrue(project_service.project_status(self.state, self.project)["enabled"])
            ui.key("p");ui.text_is("项目管理 · 只读预览", "确认停用工作流")
            ui.key("enter");ui.text_is("操作结果", absent=("执行中",))
            self.assertFalse(project_service.project_status(self.state, self.project)["enabled"])
            ui.key("esc");ui.key("o");ui.text_is("项目管理 · 只读预览", "确认启用工作流")
            ui.key("enter");ui.text_is("操作结果", absent=("执行中",))
            self.assertTrue(project_service.project_status(self.state, self.project)["enabled"])
            ui.key("esc");ui.ready();ui.finish()

    def test_native_tui_global_reset_and_monochrome(self):
        with self.ui(monochrome=True) as ui:
            ui.key("left");ui.key("home");ui.key("right")
            frame = ui.text_is("全局默认 · 工作流子 Agent", "◈ 角色模型")
            self.assertTrue({value & 7 for row in frame["attributes"] for value in row}.issubset({0, 7}))
            ui.role();ui.model("fixture-model", "high");ui.save()
            defaults = preference_snapshot(self.state)[1]["codex"]["xy-backend"]
            self.assertEqual(defaults, {"model": "fixture-model", "effort": "high"})
            ui.key("v");ui.text_is("当前角色值与来源", "全局", "明确设置")
            ui.key("esc")
            ui.command("恢复模型跟随宿主", "已暂存恢复跟随宿主")
            ui.command("恢复推理跟随宿主", "已暂存恢复跟随宿主")
            ui.save()
            self.assertEqual(preference_snapshot(self.state)[1].get("codex", {}).get("xy-backend", {}), {})
            followed = service.role_settings(self.project, "codex", "xy-backend", state=self.state, native_context=self.context)
            self.assertEqual((followed["model"], followed["effort"]), ("inherit", "inherit"))
            ui.key("v");ui.text_is("当前角色值与来源", "跟随宿主默认")
            ui.key("esc");ui.finish()

    def test_native_tui_unicode_resize_and_interrupt_restores_modes(self):
        before = (self.project / ".agent-workflow/project.yaml").read_bytes()
        with self.ui() as ui:
            ui.key("a");ui.text_is("登记项目 · 输入目录")
            ui.key("中文e")
            plain = ui.text_is("中文e")
            self.assertTrue(plain["cursor_visible"])
            ui.key("\u0301")
            combined = ui.text_is("中文é")
            self.assertEqual(combined["cursor"], plain["cursor"], "组合标记不能额外占原生光标列")
            ui.key("left");left = ui.wait("组合字符左移", lambda f: f["cursor"][1] == combined["cursor"][1] - 1)
            ui.key("right");ui.wait("组合字符右移", lambda f: f["cursor"] == combined["cursor"])
            ui.key("backspace");ui.text_is("中文", absent=("中文e", "中文é"))
            ui.key("\x15");ui.key(str(self.project))
            ui.text_is("项目目录 · 输入或拖入现有根目录", "中文")
            # 输入中的 Tab/左右仅编辑，不可切底层宿主或焦点。
            ui.key("tab");ui.key("left");ui.text_is("登记项目 · 输入目录", "[1 Codex]")
            ui.process.resize(62, 18)
            narrow = ui.wait("窄屏输入仍可达", lambda f: (f["width"], f["height"]) == (62, 18)
                             and "登记项目" in ui.text(f) and f["cursor_visible"])
            self.assertTrue(0 <= narrow["cursor"][0] < 18 and 0 <= narrow["cursor"][1] < 62)
            ui.key("esc");ui.ready()
            ui.process.resize(42, 12)
            ui.text_is("请调整至至少", "q 安全退出")
            ui.process.resize(120, 36)
            restored = ui.wait("resize 恢复主框", lambda f: (f["width"], f["height"]) == (120, 36)
                               and "角色模型" in ui.text(f))
            ui.assert_frame(restored)
            ui.finish(interrupted=True)
        self.assertEqual((self.project / ".agent-workflow/project.yaml").read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
