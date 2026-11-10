"""真实 windows-curses/ConPTY 生产界面验收；只使用请求私有宿主与项目。

测试通过键盘操作正式 manager.cli → manager.tui，屏幕、属性和模式只来自
ReadConsoleOutputW 等 Win32 读取。Mac 的导入或 skip 不计入任何原生通过。
"""

from __future__ import annotations

import base64
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
import importlib.metadata
import json
import os
from pathlib import Path
import re
import shutil
import sys
import tempfile
import threading
import time
import unicodedata
import unittest
from unittest.mock import patch
import uuid
import weakref

from lib import runtime_store
from lib.install.install_process import capture_process
from lib.central.role_preferences import snapshot as preference_snapshot
from lib.hosts.native_context import HostPaths, NativeContext
from manager import central_runtime, model_preferences, project_service, service
from manager.tui_state import Job
from tests.windows_conpty import ConPTYProcess
from tests.windows_console_observer import PhaseProfile, _publish, message_path, read_message


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


class ConsolePhaseProfilePortableTest(unittest.TestCase):
    """执行真正 Job/profile/read_operation 的 portable 合同，不依赖终端或原生 API。"""

    def test_job_refresh_profiles_outer_lease_and_preserves_hooks(self):
        main_before, thread_before = sys.getprofile(), threading.getprofile()
        hits = {"main": 0, "thread": 0}
        def marker():return None
        def main_hook(frame,event,arg):
            if main_before is not None:main_before(frame,event,arg)
            if event == "call" and frame.f_code is marker.__code__:hits["main"] += 1
        def thread_hook(frame,event,arg):
            if thread_before is not None:thread_before(frame,event,arg)
            if event == "call":hits["thread"] += 1
        class PrivateValue:pass
        original_finish=runtime_store.CoreReadOperation.finish
        sys.setprofile(main_hook);threading.setprofile(thread_hook)
        try:
            for fails in (False,True):
                with self.subTest(fails=fails):
                    profile=PhaseProfile(enabled=True);self.assertFalse(profile.binding_incomplete)
                    body_done,tail_entered,release=threading.Event(),threading.Event(),threading.Event()
                    resources=[]
                    def operation():
                        local=PrivateValue();local.secret="PROFILE-PRIVATE-LOCAL";resources.append(weakref.ref(local))
                        value=PrivateValue();value.secret="PROFILE-PRIVATE-RETURN"
                        return value
                    @runtime_store.read_operation
                    def body():
                        local=PrivateValue();local.secret="PROFILE-PRIVATE-BODY";resources.append(weakref.ref(local))
                        body_done.set()
                        return "PROFILE-PRIVATE-BODY-RETURN"
                    @runtime_store.read_operation
                    def another_body():return None
                    # 两个真实装饰器 code 相同，但都不是 load_context body；
                    # 采样只能聚合 wrapper，不能从共用 code 猜测业务函数归属。
                    self.assertIs(body.__code__,another_body.__code__)
                    self.assertIs(body.__code__,model_preferences.load_context.__code__)
                    def controlled_finish(read_operation):
                        tail_entered.set()
                        if not release.wait(5):raise RuntimeError("测试未释放 lease 尾验")
                        result=original_finish(read_operation)
                        if fails:raise ValueError("controlled tail failure")
                        return result
                    job=Job(refresh=lambda result:(body(),another_body()))
                    raised=False
                    try:
                        # 只控制真实 lease 的退出时刻；phase 必须等 Job 的 refresh
                        # lambda 整体返回，不能在已返回的 body 处提前结束。
                        with patch.object(runtime_store.CoreReadOperation,"finish",controlled_finish),profile.installed():
                            marker();self.assertIs(sys.getprofile(),main_hook)
                            with ThreadPoolExecutor(max_workers=1) as executor:
                                future=executor.submit(job.execute,operation)
                                try:
                                    self.assertTrue(tail_entered.wait(2));self.assertTrue(body_done.is_set())
                                    self.assertFalse(future.done())
                                    snapshot=profile.snapshot();current=snapshot["workers"][0]["job"]
                                    self.assertTrue(snapshot["enabled"]);self.assertEqual(snapshot["state"],"enabled")
                                    self.assertEqual(current["phase"],"refresh");self.assertFalse(current["closed"])
                                    self.assertIsNotNone(current["phases"]["operation"]["ended_ns"])
                                    refresh=current["phases"]["refresh"]
                                    self.assertIsNone(refresh["ended_ns"])
                                    self.assertEqual(refresh["functions"]["read_operation.wrapper"]["inflight"],1)
                                    self.assertEqual(refresh["functions"]["load_context.body"]["calls"],0)
                                    self.assertTrue(resources);self.assertTrue(all(ref() is None for ref in resources))
                                    self.assertNotIn("PROFILE-PRIVATE",json.dumps(snapshot))
                                finally:release.set()
                                future.result(timeout=5)
                    except ValueError as exc:
                        self.assertTrue(fails);self.assertEqual(str(exc),"controlled tail failure");raised=True
                    self.assertEqual(raised,fails)
                    self.assertIs(threading.getprofile(),thread_hook);self.assertIs(sys.getprofile(),main_hook)
                    done=profile.snapshot();self.assertFalse(done["recording_error"])
                    current=done["workers"][0]["job"];self.assertTrue(current["closed"])
                    self.assertIsNone(current["phase"]);self.assertFalse(current["incomplete"])
                    refresh=current["phases"]["refresh"]
                    self.assertGreaterEqual(refresh["elapsed_ns"],snapshot["workers"][0]["job"]["phases"]["refresh"]["elapsed_ns"])
                    expected=1 if fails else 2
                    for label in ("read_operation.wrapper","CoreReadOperation.finish"):
                        self.assertEqual(refresh["functions"][label]["calls"],expected)
                        self.assertEqual(refresh["functions"][label]["returns"],expected)
                        self.assertEqual(refresh["functions"][label]["inflight"],0)
                    self.assertEqual(set(refresh["functions"]),set(PhaseProfile.LABELS))
                    # return/unwind 不代表业务成功；异常照常传播，结果无成功标志
                    # 或参数/返回值/局部对象。正常和异常均不得握持执行帧。
                    self.assertNotIn("success",current);self.assertNotIn("PROFILE-PRIVATE",json.dumps(done))
                    self.assertTrue(all(ref() is None for ref in resources));marker()
            self.assertGreaterEqual(hits["main"],4);self.assertGreater(hits["thread"],0)
        finally:
            threading.setprofile(thread_before);sys.setprofile(main_before)

    def test_profile_bounds_and_incomplete_binding(self):
        # 默认无 hook 的控制路径实际执行原 Job，而非只检查一个配置值。
        # 原 callable/code 身份、参数及返回对象均保留，既不绑定 code，也不
        # 读取/设置任一 profiler；disabled 证据没有零计数的伪测量字段。
        main_hook,thread_hook=sys.getprofile(),threading.getprofile()
        get_main_hook,get_thread_hook=sys.getprofile,threading.getprofile
        set_main_hook,set_thread_hook=sys.setprofile,threading.setprofile
        def restore_hooks_if_changed():
            if get_thread_hook() is not thread_hook:set_thread_hook(thread_hook)
            if get_main_hook() is not main_hook:set_main_hook(main_hook)
        self.addCleanup(restore_hooks_if_changed)
        before=(Job.execute,model_preferences.apply,model_preferences.load_context,
                model_preferences.load_context.__wrapped__,runtime_store._scan,
                runtime_store._verify_snapshot,runtime_store.CoreReadOperation.finish)
        codes=tuple(function.__code__ for function in before)
        bytecodes=tuple(code.co_code for code in codes)
        result,refreshed=object(),object()
        def operation():return result
        def refresh(value):
            self.assertIs(value,result)
            return refreshed
        job=Job(refresh=refresh)
        operation_code,refresh_code=operation.__code__,refresh.__code__
        with patch("tests.windows_console_observer.dis.get_instructions") as bind, \
             patch.object(threading,"getprofile",wraps=threading.getprofile) as get_thread, \
             patch.object(threading,"setprofile",wraps=threading.setprofile) as set_thread, \
             patch.object(sys,"getprofile",wraps=sys.getprofile) as get_main, \
             patch.object(sys,"setprofile",wraps=sys.setprofile) as set_main:
            disabled=PhaseProfile()
            with disabled.installed():self.assertIs(job.execute(operation),result)
            self.assertIs(job.refreshed,refreshed);self.assertIs(job.refresh,refresh)
            self.assertEqual(disabled.snapshot(),{"enabled":False,"state":"disabled"})
            self.assertFalse(hasattr(disabled,"codes"));self.assertFalse(hasattr(disabled,"job_code"))
            for probe in (bind,get_thread,set_thread,get_main,set_main):probe.assert_not_called()
        self.assertIs(sys.getprofile(),main_hook);self.assertIs(threading.getprofile(),thread_hook)
        after=(Job.execute,model_preferences.apply,model_preferences.load_context,
               model_preferences.load_context.__wrapped__,runtime_store._scan,
               runtime_store._verify_snapshot,runtime_store.CoreReadOperation.finish)
        for previous,current,code,bytecode in zip(before,after,codes,bytecodes):
            self.assertIs(current,previous);self.assertIs(current.__code__,code)
            self.assertEqual(current.__code__.co_code,bytecode)
        self.assertIs(operation.__code__,operation_code);self.assertIs(refresh.__code__,refresh_code)
        @runtime_store.read_operation
        def leaf():return None
        profile=PhaseProfile(enabled=True)
        def many_events():
            for _ in range(1400):leaf()
        with profile.installed(),ThreadPoolExecutor(max_workers=1) as executor:
            executor.submit(Job().execute,many_events).result(timeout=5)
            phase=profile.snapshot()["workers"][0]["job"]["phases"]["operation"]
            self.assertTrue(phase["overflow"]);self.assertTrue(phase["incomplete"])
            self.assertLessEqual(phase["events"],PhaseProfile.MAX_PHASE_EVENTS)
            # 超出 job 数也不建立历史列表；后续真实 Job 仍正常执行，只有诊断
            # 标记不完整，当前/最近记录和所有计数持续受固定上限约束。
            for _ in range(PhaseProfile.MAX_JOBS+1):executor.submit(Job().execute,lambda:None).result(timeout=2)
        bounded=profile.snapshot();worker=bounded["workers"][0]
        self.assertTrue(bounded["overflow"]);self.assertEqual(worker["jobs"],PhaseProfile.MAX_JOBS)
        self.assertLessEqual(worker["events"],PhaseProfile.MAX_WORKER_EVENTS)
        self.assertLessEqual(bounded["events"],PhaseProfile.MAX_EVENTS)
        deep=PhaseProfile(enabled=True)
        @runtime_store.read_operation
        def nested(depth):
            if depth:nested(depth-1)
        with deep.installed(),ThreadPoolExecutor(max_workers=1) as executor:
            executor.submit(Job().execute,lambda:nested(80)).result(timeout=5)
        phase=deep.snapshot()["workers"][0]["job"]["phases"]["operation"]
        self.assertTrue(phase["overflow"]);self.assertTrue(phase["incomplete"])
        self.assertLessEqual(phase["functions"]["read_operation.wrapper"]["calls"],PhaseProfile.MAX_ACTIVE)
        workers=PhaseProfile(enabled=True);release=threading.Event();ready=[threading.Event() for _ in range(5)]
        def wait(index):
            ready[index].set()
            if not release.wait(5):raise RuntimeError("测试未释放 profile worker")
        with workers.installed(),ThreadPoolExecutor(max_workers=5) as executor:
            futures=[executor.submit(Job().execute,lambda index=index:wait(index)) for index in range(5)]
            try:
                self.assertTrue(all(event.wait(2) for event in ready))
                snapshot=workers.snapshot();self.assertTrue(snapshot["overflow"])
                self.assertEqual(len(snapshot["workers"]),PhaseProfile.MAX_WORKERS)
            finally:release.set()
            for future in futures:future.result(timeout=5)
        # 两个调用位于同一行时无法唯一绑定，明确 incomplete；不能拿 CALL
        # cache offset 或同名 lambda 猜测 phase。这个函数只用于元数据负控。
        def ambiguous(self,operation):operation();self.refresh(None)
        with patch.object(Job,"execute",ambiguous):
            incomplete=PhaseProfile(enabled=True).snapshot()
            self.assertTrue(incomplete["binding_incomplete"]);self.assertEqual(incomplete["workers"],[])
        # 元数据绑定有效但 callable 没有 Python call 根时，也必须明示缺失，
        # 不把无计时记录当作已经量到零耗时；原任务仍照常返回真实结果。
        missing=PhaseProfile(enabled=True)
        with missing.installed(),ThreadPoolExecutor(max_workers=1) as executor:
            self.assertEqual(executor.submit(Job().execute,list).result(timeout=2),[])
        job=missing.snapshot()["workers"][0]["job"]
        self.assertTrue(job["closed"]);self.assertTrue(job["incomplete"])
        self.assertTrue(job["phases"]["operation"]["incomplete"])


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

    def key(self, value, *, started_ns=None):
        payload = KEYS.get(value, value)
        # 记录测试输入的写入边界；返回长度只证明 ConPTY 接受了字节，不能推定
        # curses 已消费/派发。组合查询正文不写入诊断，只记录测试单键和字节数。
        event = {"kind": "input", "key": value if value in KEYS or len(value) == 1 else None,
                 "bytes": len(payload.encode("utf-8")), "started_ns": time.monotonic_ns() - self.started_ns if started_ns is None else started_ns}
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

    @staticmethod
    def _busy_elapsed(frame, name):
        # 既定布局的倒数第五行是作业状态。只读原生文字，不把 IPC 序号、
        # 后台线程活跃或复用 toast 当作本次动作响应/可见绘制进展。
        if len(frame["lines"]) < 5:return None
        match = re.search(re.escape(name) + r" · (\d+)s · 执行中\s*┃?$", frame["lines"][-5])
        return int(match[1]) if match else None

    def action(self, key, label, predicate, *, busy_name, baseline=None):
        baseline = self.snapshot() if baseline is None else baseline
        self.case.assertNotIn("执行中", self.text(baseline), "旧作业仍忙，不能发送新动作")
        self.case.assertFalse(predicate(baseline), "动作目标已在基线成立，缺少本次消费证据")
        # 输入记录、5s 响应与 60s 结算严格共用这个起点，write 或后续刷新
        # 都不能重置期限。60s 只是集成测试防挂上限，不是性能/产品 SLA。
        origin = time.monotonic_ns()
        self.key(key, started_ns=origin - self.started_ns)
        return self.wait_action(label, predicate, busy_name=busy_name, origin_ns=origin)

    def wait_action(self, label, predicate, *, busy_name, origin_ns):
        ack_deadline = origin_ns + 5_000_000_000
        final_deadline = origin_ns + 60_000_000_000
        checkpoint = origin_ns + 30_000_000_000
        event = {"kind": "action", "label": label, "busy_name": busy_name,
                 "started_ns": origin_ns - self.started_ns,
                 "ack_deadline_ns": ack_deadline - self.started_ns,
                 "settlement_deadline_ns": final_deadline - self.started_ns,
                 "first_number": self.sequence + 1, "outcome": "error", "ack": None,
                 "checkpoint_30s": None, "busy_samples": 0, "drawing_changes": 0,
                 "busy_elapsed_first": None, "busy_elapsed_last": None}
        last = None;previous_lines = None;last_draw = origin_ns;last_elapsed = origin_ns
        try:
            while True:
                now = time.monotonic_ns()
                limit = final_deadline if event["ack"] is not None else ack_deadline
                if now >= limit:
                    event["outcome"] = "settlement-timeout" if event["ack"] is not None else "ack-timeout"
                    self.case.fail("异步动作未在绝对期限内达到 " + label)
                # 单次观察也受剩余响应/结算预算约束，不能在最后一帧再借5s。
                last = self.snapshot(timeout=min(5, (limit - now) / 1_000_000_000))
                now = time.monotonic_ns();elapsed = now - origin_ns
                if event["checkpoint_30s"] is None and now >= checkpoint:
                    event["checkpoint_30s"] = {"elapsed_ns": elapsed, "number": self.sequence,
                        "stable": last["stable"], "busy_elapsed": self._busy_elapsed(last, busy_name)}
                    self.frames.append({"label": label + "-30s-checkpoint", "native": last})
                # 目标再正确也不能接受期限之后才拿到的快照；记录真实超限耗时。
                if now > limit:
                    event["outcome"] = "settlement-timeout" if event["ack"] is not None else "ack-timeout"
                    self.case.fail("异步动作观察返回已超过绝对期限：" + label)
                complete = last["stable"] and predicate(last)
                busy_elapsed = self._busy_elapsed(last, busy_name) if last["stable"] else None
                if event["ack"] is None and (complete or busy_elapsed is not None):
                    event["ack"] = {"kind": "terminal" if complete else "busy", "elapsed_ns": elapsed,
                                    "number": self.sequence}
                    last_draw = last_elapsed = now
                # 最终帧也不能抹去此前超过5s的可见进展证据缺口；快速完成
                # 在上面首次响应时建立计时，因此不要求它先出现 busy。
                if event["ack"] is not None and (now - last_draw > 5_000_000_000 or
                        event["busy_samples"] > 0 and now - last_elapsed > 5_000_000_000):
                    event["outcome"] = "drawing-stalled"
                    self.case.fail("异步动作缺少持续原生绘制/elapsed进展：" + label)
                if complete:
                    event["outcome"] = "success"
                    self.frames.append({"label": label, "native": last})
                    return last
                if event["ack"] is not None:
                    # 响应之后仍须持续可见绘制。真实 busy 的秒数必须推进，
                    # 仅观察到管道/序号变化或一个长期冻结的 spinner 不算活性。
                    lines = tuple(last["lines"])
                    if last["stable"] and lines != previous_lines:
                        event["drawing_changes"] += 1;last_draw = now;previous_lines = lines
                    if busy_elapsed is not None:
                        event["busy_samples"] += 1
                        previous_elapsed = event["busy_elapsed_last"]
                        if previous_elapsed is None:event["busy_elapsed_first"] = busy_elapsed
                        elif busy_elapsed < previous_elapsed:
                            event["outcome"] = "elapsed-restarted"
                            self.case.fail("同一动作的可见elapsed回退，不能续期：" + label)
                        if previous_elapsed is None or busy_elapsed > previous_elapsed:last_elapsed = now
                        event["busy_elapsed_last"] = busy_elapsed
                remaining = (final_deadline if event["ack"] is not None else ack_deadline) - time.monotonic_ns()
                if remaining > 0:time.sleep(min(0.03, remaining / 1_000_000_000))
        except BaseException:
            if last is not None:self.frames.append({"label": label + "-failed", "native": last})
            raise
        finally:
            event["last_number"] = self.sequence
            event["finished_ns"] = time.monotonic_ns() - self.started_ns
            event["actual_elapsed_ns"] = time.monotonic_ns() - origin_ns
            self.events.append(event)

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
        self.open_choice("m", "选择模型")
        self.choose(query, "选择推理级别")
        self.choose(effort, "已暂存，尚未保存")

    def open_choice(self, key, title):
        baseline = self.snapshot()
        hosts = [name for marker, name in (("[1 Codex]", "Codex"), ("[2 Claude Code]", "Claude Code"))
                 if marker in self.text(baseline)]
        self.case.assertEqual(len(hosts), 1, "编辑入口必须有唯一实际活动宿主")
        return self.action(key, title, lambda frame:self._modal_title(frame) == title and "执行中" not in self.text(frame),
                           busy_name="读取 " + hosts[0] + " 模型目录", baseline=baseline)

    def preview(self):
        return self.action("s", "保存预览 / 确认备份并保存", lambda frame:
                         self._modal_title(frame) == "保存预览" and "确认备份并保存" in self.text(frame)
                         and "执行中" not in self.text(frame), busy_name="生成保存预览")

    def save(self):
        self.preview()
        self.action("enter", "操作结果 / 已保存模型配置", lambda frame:self._modal_title(frame) == "操作结果"
                    and "已保存模型配置" in self.text(frame) and "执行中" not in self.text(frame), busy_name="备份并保存模型配置")
        self.key("esc");self.ready()

    def project_action(self, key, action, *, preview=False):
        name = {"enable": "启用工作流", "disable": "停用工作流"}[action]
        title = "项目管理 · 只读预览" if preview else "操作结果"
        return self.action(key, title + (" / 确认" + name if preview else ""), lambda frame:
                           self._modal_title(frame) == title and "执行中" not in self.text(frame)
                           and (not preview or "确认" + name in self.text(frame)),
                           busy_name=("预览" if preview else "") + name)

    @classmethod
    def _reset_projection(cls, frame):
        """只从同一原生主屏取得选中后端角色的两个字段及其来源。"""
        if not frame["stable"] or not cls._main_ready(frame, ("全局默认 · 工作流子 Agent",)):
            return None
        # 直接匹配 ReadConsoleOutputW 已读取的角色行；不借 App 私有状态、
        # 不用另一个 cell_width 或重新绘制的 Screen 推算字段。选中标记和
        # 后端角色身份必须同时存在，不能把别行重复的“继承”当成本次结果。
        roles = []
        sources = []
        for line in frame["lines"]:
            line = unicodedata.normalize("NFC", line)
            if match := re.search(r"▌[● ]后端开发\s+▸?(\S+)\s+(\S+)\s*┃?$", line):
                roles.append(match.groups())
            if match := re.fullmatch(r"xy-backend · 模型来源 (\S+) / 推理来源 (\S+) · v 详情", line.strip("┃ ")):
                sources.append(match.groups())
        return (*roles[0], *sources[0]) if len(roles) == len(sources) == 1 else None

    @classmethod
    def _reset_ready(cls, frame, baseline, target, result):
        # 两次恢复共用同一个 toast，序号也会在旧画面上继续增长。必须证明
        # 本次目标相对真实基线发生变化，且字段/来源/无弹层/无忙态在同帧成立。
        # 允许动作快到来不及观察 busy：业务投影已变化本身就能证明本次完成。
        return baseline != target and cls._reset_projection(frame) == target and result in cls.text(frame)

    def command(self, query, result, *, before, after):
        frame = self.wait("恢复前的选中角色值与来源", lambda value:self._reset_projection(value) is not None)
        baseline = self._reset_projection(frame)
        self.case.assertEqual(baseline, before, "恢复前实际角色值或来源不符，不能用旧目标画面接受新动作")
        self.case.assertNotEqual(baseline, after, "本次恢复必须有区别于基线的业务画面证据")
        self.key(":" + query)
        menu = self.text_is("命令面板", query)
        return self.action("enter", result, lambda value:self._reset_ready(value, baseline, after, result),
                           busy_name="读取 Codex 模型目录", baseline=menu)

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


class NativeUIResetPredicatePortableTest(unittest.TestCase):
    """回放真实原生行的判据合同；不模拟终端，也不声称 portable 等于原生通过。"""

    # 来源：run42783756527、candidate3b5e152，process artifact 的 global 方法。
    # SHA 是原 native 对象按 sort_keys/紧凑分隔/UTF-8 canonical JSON 计算，
    # 下方仅保存必要角色行、footer 和弹层标题片段；不带巨型 cells/base64。
    # 这些常量是原生已观察业务文本，不从被测判据或生产 draw 生成期望画面。
    RECORDED = {
        728: ("c5fba78d048cdd706f16fa63de07d1a6592157417a446116c74d9a87bddd6532",
              "全局默认 · 工作流子 Agent", "▌ 后端开发         ▸fixture-model                                             high",
              "xy-backend · 模型来源 全局 / 推理来源 全局 · v 详情", "✔ 已保存模型配置 · 全局默认 / Codex"),
        814: ("7a435f62115ea86b508ada4c4f6049a494b3a00e215b55e4f5f03a15baa552f3",
              "全局默认 · 工作流子 Agent", "▌●后端开发         ▸继承                                                      high",
              "xy-backend · 模型来源 宿主 / 推理来源 全局 · v 详情", "▲ 已暂存恢复跟随宿主；尚未保存，按 s 预览"),
        816: ("c7a4347ff73fe916833806febfd0bc26600c239634dcae46bf54b58dbe41a180",
              "╭ 命令面板     ─────────────────────────────────────────────────────────────────────────── 1 / 1 ╮", "",
              "│                                                                                            │", "▲ 已暂存恢复跟随宿主；尚未保存，按 s 预览"),
        817: ("67e0d1c5225a2fe703c44c0d4b9a5791b2652860daa2727b03ad981f6d4c1f9a",
              "全局默认 · 工作流子 Agent", "▌●后端开发         ▸继承                                                      high",
              "│                                                                                            │", "▲ 已暂存恢复跟随宿主；尚未保存，按 s 预览"),
        1299: ("0eb1c11fc52946743e4abf5008faa9f7caa953d74d960df9397224e179302c69",
               "全局默认 · 工作流子 Agent", "▌●后端开发         ▸继承                                                      继承",
               "xy-backend · 模型来源 宿主 / 推理来源 宿主 · v 详情", "▲ 已暂存恢复跟随宿主；尚未保存，按 s 预览"),
    }

    @classmethod
    def recorded(cls, number):
        digest, header, role, source, status = cls.RECORDED[number]
        # 空行只是省略与纯判据无关的原生行；不实现屏幕写入、宽度或渲染行为。
        lines = [""] * 36
        for row, text in ((4, header), (10, role), (29, source), (31, status)):lines[row] = text
        return {"stable": True, "lines": lines, "recorded_number": number, "source_native_sha256": digest}

    def test_reset_requires_selected_fields_and_sources_in_one_native_frame(self):
        saved = ("fixture-model", "high", "全局", "全局")
        model_reset = ("继承", "high", "宿主", "全局")
        both_reset = ("继承", "继承", "宿主", "宿主")
        message = "已暂存恢复跟随宿主"
        self.assertEqual(saved, NativeUI._reset_projection(self.recorded(728)))
        self.assertTrue(NativeUI._reset_ready(self.recorded(814), saved, model_reset, message))
        self.assertTrue(NativeUI._reset_ready(self.recorded(1299), model_reset, both_reset, message))
        for number in (814, 816, 817):
            with self.subTest(native_number=number):
                self.assertFalse(NativeUI._reset_ready(self.recorded(number), model_reset, both_reset, message))
        self.assertFalse(NativeUI._reset_ready(self.recorded(1299), both_reset, both_reset, message))
        # 在原生完成帧上逐项作负控，证明判据没有仅靠 toast、别行字段、旧来源
        # 或“无执行中”放行。变体只属于判据测试，不冒充另一份真实原生证据。
        mutations = {
            "wrong-role": (10, self.recorded(1299)["lines"][10].replace("后端开发", "独立 QA")),
            "wrong-source": (29, "xy-backend · 模型来源 全局 / 推理来源 宿主 · v 详情"),
            "wrong-source-role": (29, "xy-qa · 模型来源 宿主 / 推理来源 宿主 · v 详情"),
            "modal": (4, self.recorded(816)["lines"][4]),
            "busy": (31, "读取来源 · 执行中"),
        }
        for name, (row, text) in mutations.items():
            with self.subTest(control=name):
                frame = self.recorded(1299);frame["lines"][row] = text
                self.assertFalse(NativeUI._reset_ready(frame, model_reset, both_reset, message))
        frame = self.recorded(1299);frame["stable"] = False
        self.assertFalse(NativeUI._reset_ready(frame, model_reset, both_reset, message))

    def test_reset_command_rejects_old_toast_and_waits_for_business_transition(self):
        before = ("继承", "high", "宿主", "全局")
        after = ("继承", "继承", "宿主", "宿主")
        # 执行真实 NativeUI.command/text_is/wait 路由，只把 snapshot 的输入
        # 换成已记录的原生行。既不启动 WinDLL，也不接触 App 私有状态。
        for intermediates in ((814, 817), ()):
            with self.subTest(intermediate_frames=intermediates):
                ui = object.__new__(NativeUI);ui.case = self;ui.sequence = 0
                ui.started_ns = time.monotonic_ns();ui.frames = [];ui.events = []
                modal = self.recorded(816);modal["lines"][7] = "恢复推理跟随宿主"
                pending = [self.recorded(814), modal, *(self.recorded(n) for n in intermediates), self.recorded(1299)]
                inputs = [];seen = []
                def snapshot(timeout=5):
                    self.assertTrue(pending, "真实 command 路由没有在目标业务帧完成")
                    ui.sequence += 1;frame = pending.pop(0);seen.append(frame["recorded_number"]);return frame
                def key(value, **kwargs):inputs.append(value)
                with patch.object(ui, "snapshot", side_effect=snapshot), patch.object(ui, "key", side_effect=key):
                    frame = ui.command("恢复推理跟随宿主", "已暂存恢复跟随宿主", before=before, after=after)
                self.assertEqual(1299, frame["recorded_number"])
                self.assertEqual([":恢复推理跟随宿主", "enter"], inputs)
                self.assertEqual([814, 816, *intermediates, 1299], seen)
                self.assertFalse(pending);self.assertTrue(all(e["outcome"] == "success" for e in ui.events))
                self.assertEqual(1299, ui.frames[-1]["native"]["recorded_number"])


class NativeUIAsyncWaitPortableTest(unittest.TestCase):
    """真实 action/wait_action 消费者的时限合同；不以受控时钟冒充原生性能。"""

    BEFORE = ("继承", "high", "宿主", "全局")
    AFTER = ("继承", "继承", "宿主", "宿主")
    BUSY = "读取 Codex 模型目录"
    MESSAGE = "已暂存恢复跟随宿主"

    @classmethod
    def busy(cls, seconds, *, name=None, spinner="/"):
        # 在真实旧业务行上只变更作业状态，属于明确标记的时限负/正控数据，
        # 不是 Screen 实现，也不产生任何 native 验收或耗时通过结论。
        frame = NativeUIResetPredicatePortableTest.recorded(814)
        frame["lines"][31] = "▲ " + spinner + " " + (name or cls.BUSY) + f" · {seconds}s · 执行中"
        return frame

    @contextmanager
    def replay(self, samples, *, baseline=None):
        ui = object.__new__(NativeUI);ui.case = self;ui.sequence = 0
        ui.started_ns = 2_000_000_000;ui.frames = [];ui.events = []
        clock = [10_000_000_000];origin = clock[0];pending = list(samples)
        inputs = [];calls = [];first = True
        def snapshot(timeout=5):
            nonlocal first
            calls.append({"at_ns":clock[0],"timeout":timeout})
            self.assertTrue(0 < timeout <= 5)
            ui.sequence += 1
            if first:
                first = False
                return NativeUIResetPredicatePortableTest.recorded(814) if baseline is None else baseline
            self.assertTrue(pending, "wait_action 在有界样本结束后仍继续请求")
            seconds, frame = pending.pop(0);sample_time = origin + round(seconds * 1_000_000_000)
            self.assertGreaterEqual(sample_time, clock[0], "回放单调时钟不能倒退")
            clock[0] = sample_time
            return frame
        def key(value, **kwargs):inputs.append((value, kwargs))
        def sleep(seconds):clock[0] += round(seconds * 1_000_000_000)
        with patch.object(ui,"snapshot",side_effect=snapshot), patch.object(ui,"key",side_effect=key), \
             patch.object(time,"monotonic_ns",side_effect=lambda:clock[0]), patch.object(time,"sleep",side_effect=sleep):
            yield ui,inputs,calls

    def perform(self, ui):
        return ui.action("enter", self.MESSAGE, lambda frame:NativeUI._reset_ready(frame,self.BEFORE,self.AFTER,self.MESSAGE),
                         busy_name=self.BUSY)

    def test_action_wait_uses_input_deadlines_and_requires_new_acknowledgement(self):
        target = NativeUIResetPredicatePortableTest.recorded(1299)
        # 快完成直接用本次业务变化响应；无需人为制造一个 busy 帧。
        with self.replay([(0.1,target)]) as (ui,inputs,calls):
            self.assertIs(target,self.perform(ui));event=ui.events[-1]
            self.assertEqual([("enter",{"started_ns":8_000_000_000})],inputs)
            self.assertEqual(8_000_000_000,event["started_ns"])
            self.assertEqual(13_000_000_000,event["ack_deadline_ns"])
            self.assertEqual(68_000_000_000,event["settlement_deadline_ns"])
            self.assertEqual("terminal",event["ack"]["kind"]);self.assertEqual(100_000_000,event["actual_elapsed_ns"])
        for baseline in (self.busy(29), target):
            with self.subTest(baseline=baseline["lines"][31]), self.replay([],baseline=baseline) as (ui,inputs,calls):
                with self.assertRaises(AssertionError):self.perform(ui)
                self.assertEqual([],inputs);self.assertEqual([],ui.events)
        scenarios = {
            "old-toast-new-sequence": [(1,NativeUIResetPredicatePortableTest.recorded(814)),
                                       (3,NativeUIResetPredicatePortableTest.recorded(817)),
                                       (5,NativeUIResetPredicatePortableTest.recorded(814))],
            "other-job-busy": [(1,self.busy(1,name="其他作业")),(5,self.busy(5,name="其他作业"))],
            "late-first-target": [(5.1,target)],
        }
        for name,samples in scenarios.items():
            with self.subTest(control=name), self.replay(samples) as (ui,inputs,calls):
                with self.assertRaisesRegex(AssertionError,"绝对期限"):self.perform(ui)
                event=ui.events[-1];self.assertEqual("ack-timeout",event["outcome"])
                self.assertIsNone(event["ack"]);self.assertEqual(1,len(inputs))
                for call in calls[1:]:self.assertLessEqual(call["timeout"],(15_000_000_000-call["at_ns"])/1e9)

    def test_action_wait_preserves_checkpoint_progress_and_terminal_failures(self):
        target=NativeUIResetPredicatePortableTest.recorded(1299)
        samples=[(n,self.busy(n)) for n in (1,5,9,13,17,21,25,29,30,34,38)]
        with self.replay([*samples,(40,target)]) as (ui,inputs,calls):
            self.assertIs(target,self.perform(ui));event=ui.events[-1]
            self.assertEqual("busy",event["ack"]["kind"])
            self.assertEqual(30_000_000_000,event["checkpoint_30s"]["elapsed_ns"])
            self.assertEqual(40_000_000_000,event["actual_elapsed_ns"])
            self.assertEqual(68_000_000_000,event["settlement_deadline_ns"])
            self.assertEqual(1,event["busy_elapsed_first"]);self.assertEqual(38,event["busy_elapsed_last"])
            self.assertEqual(len(samples),event["busy_samples"]);self.assertGreater(event["drawing_changes"],1)
            self.assertEqual(1,sum(f["label"].endswith("-30s-checkpoint") for f in ui.frames))
        controls={
            "spinner-with-frozen-elapsed": ([(1,self.busy(0)),(4,self.busy(0,spinner="-")),(7,self.busy(0))],"drawing-stalled"),
            "terminal-after-frozen-elapsed": ([(1,self.busy(0)),(4,self.busy(0,spinner="-")),(7,target)],"drawing-stalled"),
            "elapsed-restart": ([(1,self.busy(1)),(4,self.busy(0))],"elapsed-restarted"),
            "late-terminal": ([*( (n,self.busy(n)) for n in (1,5,9,13,17,21,25,29,30,34,38,42,46,50,54,58)),
                               (60.1,target)],"settlement-timeout"),
        }
        for name,(values,outcome) in controls.items():
            with self.subTest(control=name), self.replay(values) as (ui,inputs,calls):
                with self.assertRaises(AssertionError):self.perform(ui)
                event=ui.events[-1];self.assertEqual(outcome,event["outcome"])
                self.assertEqual(68_000_000_000,event["settlement_deadline_ns"])
                self.assertTrue(ui.frames[-1]["label"].endswith("-failed"));self.assertEqual(1,len(inputs))
                for call in calls[1:]:self.assertLessEqual(call["timeout"],(70_000_000_000-call["at_ns"])/1e9)
                if name == "late-terminal":
                    self.assertIsNotNone(event["checkpoint_30s"]);self.assertLess(calls[-1]["timeout"],5)


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
            ui.open_choice("m", "选择模型")
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
            ui.open_choice("e", "选择推理级别")
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
            ui.project_action("p", "disable", preview=True)
            ui.key("esc");ui.ready()
            self.assertTrue(project_service.project_status(self.state, self.project)["enabled"])
            ui.project_action("p", "disable", preview=True)
            ui.project_action("enter", "disable")
            self.assertFalse(project_service.project_status(self.state, self.project)["enabled"])
            ui.key("esc");ui.project_action("o", "enable", preview=True)
            ui.project_action("enter", "enable")
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
            ui.command("恢复模型跟随宿主", "已暂存恢复跟随宿主",
                       before=("fixture-model", "high", "全局", "全局"), after=("继承", "high", "宿主", "全局"))
            ui.command("恢复推理跟随宿主", "已暂存恢复跟随宿主",
                       before=("继承", "high", "宿主", "全局"), after=("继承", "继承", "宿主", "宿主"))
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
