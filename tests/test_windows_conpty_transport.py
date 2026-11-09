"""ConPTY 原生传输验收；Mac 只收集原生节点、执行可移植参数边界。"""

from __future__ import annotations

import base64
import ctypes
import json
import os
from pathlib import Path
import queue
import signal
import subprocess
import sys
import tempfile
import textwrap
import time
import unittest
from unittest.mock import Mock, patch

from lib.install import windows_process as win
from lib.install.windows_process import WindowsJobCleanupError, WindowsJobProcess, WindowsProcessCancelled
from tests.windows_conpty import COORD, ConPTYProcess, _size, _timeout, _validate_launch


class PortableConPTYContractTest(unittest.TestCase):
    def test_launch_and_abi_boundaries_reject_ambiguous_inputs(self):
        self.assertEqual(ctypes.sizeof(COORD), 4)
        self.assertEqual((COORD.X.offset, COORD.Y.offset), (0, 2))
        valid = [sys.executable, "-I", "-B", "-X", "utf8", "-c", "pass"]
        _validate_launch(valid, Path.cwd(), {"AWF_LITERAL": "中文 e\u0301 & !"}, 4096)
        for argv in ("python -c pass", [], ["python", "-c", "pass"], [sys.executable, "a\0b"]):
            with self.subTest(argv=argv), self.assertRaises(ValueError):
                _validate_launch(argv, None, None, 4096)
        for env in ({"PATH": "a", "Path": "b"}, {"A": "x\0y"}, {"A=B": "x"}, {"A": 2}):
            with self.subTest(env=env), self.assertRaises(ValueError):
                _validate_launch(valid, None, env, 4096)
        for cwd in ("relative", b"/bytes", 7, str(Path.cwd()) + "\0suffix"):
            with self.subTest(cwd=cwd), self.assertRaises(ValueError):
                _validate_launch(valid, cwd, None, 4096)
        for value in (True, 0, -1, 32768, 1.5):
            with self.subTest(size=value), self.assertRaises(ValueError):
                _size(value, 24)
        for value in (None, True, 0, -1, float("nan"), float("inf")):
            with self.subTest(timeout=value), self.assertRaises(ValueError):
                _timeout(value)
        for value in (0, True, 4 * 1024 * 1024 + 1):
            with self.subTest(limit=value), self.assertRaises(ValueError):
                _validate_launch(valid, None, None, value)

    def test_pseudoconsole_rejects_stdio_conflicts_before_native_allocation(self):
        # 这些是真实入口的前置拒绝，不替换 Win32 API，也不将本机结果计为 ConPTY 成功。
        for stream in (subprocess.PIPE, subprocess.DEVNULL):
            for name in ("stdin", "stdout", "stderr"):
                with self.subTest(name=name, stream=stream), self.assertRaises(ValueError):
                    WindowsJobProcess([sys.executable], pseudoconsole=1, **{name: stream})
        for handle in (0, -1, True, 1 << (ctypes.sizeof(ctypes.c_void_p) * 8)):
            with self.subTest(handle=handle), self.assertRaises(ValueError):
                WindowsJobProcess([sys.executable], pseudoconsole=handle)

    def test_job_failure_survives_repeated_close_and_conpty_releases_only_io(self):
        # 复用既有 Win32 测试替身控制“累计 2、只持有 1”的已证原生失败，验证
        # 实际 Job/ConPTY owner 的生命周期，不把替身结果声称为原生附着成功。
        from tests.test_install_process_windows import FakeWin32
        api = FakeWin32(total=2)
        api.after_stop = [0]
        with patch.object(win, "_Win32API", return_value=api):
            owner = WindowsJobProcess([sys.executable])
        channel = ConPTYProcess.__new__(ConPTYProcess)
        channel._process, channel._closed, channel._closing = owner, False, False
        channel._api = Mock()
        channel._api.CloseHandle.return_value = True
        channel._console, channel._input, channel._output_handle = (
            ctypes.c_void_p(value) for value in (710, 711, 712))
        channel._reader = channel._writer = channel._closer = None
        channel._requests = queue.Queue()
        previous = signal.getsignal(signal.SIGINT)
        try:
            with self.assertRaises(WindowsJobCleanupError) as first:
                owner.wait(timeout=0)
            for action in (channel.close, channel.close, owner.close, owner.stop, owner.wait):
                with self.subTest(action=action.__qualname__), self.assertRaises(WindowsJobCleanupError) as caught:
                    action()
                self.assertIs(caught.exception, first.exception)
                self.assertTrue(owner.closed)
                self.assertFalse(owner._quiescent)
                self.assertTrue(channel.closed)
            self.assertEqual(api.events.count("terminate_job"), 1)
            self.assertEqual(api.closed.count(100), 1)
            self.assertEqual(api.closed.count(200), 1)
            channel._api.ClosePseudoConsole.assert_called_once_with(710)
            self.assertEqual(channel._api.CloseHandle.call_count, 2)
            self.assertIsNone(channel._console.value)
            self.assertIsNone(channel._input.value)
            self.assertIsNone(channel._output_handle.value)
        finally:
            # 致命生产路径故意忽略后续 SIGINT；测试只还原自己的解释器信号。
            signal.signal(signal.SIGINT, previous)


# 子程序只操作自己在 ConPTY 中获得的标准 console handles。父 runner 不调用
# SetConsoleMode/AttachConsole/GenerateConsoleCtrlEvent，因此不会触碰用户终端模式。
CONSOLE_CHILD = """
import ctypes, os, signal, sys
K = ctypes.WinDLL('kernel32', use_last_error=True)
K.GetStdHandle.argtypes = [ctypes.c_uint32]
K.GetStdHandle.restype = ctypes.c_void_p
K.GetConsoleMode.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_uint32)]
K.GetConsoleMode.restype = ctypes.c_int32
K.SetConsoleMode.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
K.SetConsoleMode.restype = ctypes.c_int32
hin, hout = K.GetStdHandle(0xfffffff6), K.GetStdHandle(0xfffffff5)
def mode(handle):
    result = ctypes.c_uint32()
    if not K.GetConsoleMode(handle, ctypes.byref(result)):
        raise ctypes.WinError(ctypes.get_last_error())
    return result.value
def set_mode(handle, value):
    if not K.SetConsoleMode(handle, value):
        raise ctypes.WinError(ctypes.get_last_error())
signal.signal(signal.SIGINT, signal.default_int_handler)
"""


# 诊断结果经任务临时文件传回，不能依赖正在排查的 stdout 路由。独立 CONOUT$
# 写入只用于区分“控制台已附着但标准句柄错误”与“根本没有控制台”；不重设
# 标准句柄、不为生产入口补丁，也不改变其环境或解释器。短暂握手让父进程
# 有机会在正常 wait 内保留真实 payload 句柄，仅用于诊断，不是终止证明方案。
CONSOLE_DIAGNOSTIC_CHILD = r"""
import ctypes, json, os, pathlib, sys, time
K = ctypes.WinDLL('kernel32', use_last_error=True)
H, D = ctypes.c_void_p, ctypes.c_uint32
for name, args, result in (
    ('GetStdHandle', [D], H), ('GetFileType', [H], D),
    ('GetConsoleMode', [H, ctypes.POINTER(D)], ctypes.c_int32),
    ('CreateFileW', [ctypes.c_wchar_p, D, D, H, D, D, H], H),
    ('WriteFile', [H, H, D, ctypes.POINTER(D), H], ctypes.c_int32),
    ('CloseHandle', [H], ctypes.c_int32)):
    fn = getattr(K, name)
    fn.argtypes, fn.restype = args, result
def describe(handle):
    ctypes.set_last_error(0)
    file_type = K.GetFileType(handle)
    file_error = ctypes.get_last_error()
    value = D()
    ctypes.set_last_error(0)
    ok = bool(K.GetConsoleMode(handle, ctypes.byref(value)))
    return {'handle': handle, 'file_type': file_type, 'file_error': file_error,
            'console_mode_ok': ok, 'console_mode': value.value,
            'console_mode_error': ctypes.get_last_error()}
data = {'pid': os.getpid(), 'ppid': os.getppid(), 'executable': sys.executable,
        'base_executable': getattr(sys, '_base_executable', None),
        'prefix': sys.prefix, 'base_prefix': sys.base_prefix, 'version': list(sys.version_info[:3]),
        'standard': {name: describe(K.GetStdHandle(D(number).value))
                     for name, number in (('stdin', -10), ('stdout', -11), ('stderr', -12))}}
data['console_devices'] = {}
for name in ('CONIN$', 'CONOUT$'):
    ctypes.set_last_error(0)
    handle = K.CreateFileW(name, 0xc0000000, 3, None, 3, 0x80, None)
    if handle in (None, 0, H(-1).value):
        data['console_devices'][name] = {'open_error': ctypes.get_last_error()}
        continue
    try:
        item = data['console_devices'][name] = describe(handle)
        if name == 'CONOUT$':
            marker = b'AWF_DIAGNOSTIC_CONOUT\r\n'
            count = D()
            item['write_ok'] = bool(K.WriteFile(handle, marker, len(marker), ctypes.byref(count), None))
            item['write_count'], item['write_error'] = count.value, ctypes.get_last_error()
    finally:
        K.CloseHandle(handle)
report = pathlib.Path(sys.argv[1])
pending = report.with_suffix('.pending')
pending.write_text(json.dumps(data), encoding='utf-8')
pending.replace(report)
print('AWF_DIAGNOSTIC_STDOUT', flush=True)
release = pathlib.Path(sys.argv[2])
deadline = time.monotonic() + 8
while not release.exists() and time.monotonic() < deadline:
    time.sleep(.01)
time.sleep(.25)
"""


@unittest.skipUnless(os.name == "nt", "必须由真实 Windows 执行；收集或 skip 不能作为原生通过")
class NativeConPTYTransportTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(
            prefix="awf-conpty-中文 e\u0301-", dir=os.environ.get("AGENT_WORKFLOW_TEST_SCRATCH"))
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.home = self.root / "隔离 HOME"
        self.home.mkdir()
        self.env = {**os.environ, "HOME": str(self.home), "USERPROFILE": str(self.home),
                    "APPDATA": str(self.home / "AppData/Roaming"),
                    "LOCALAPPDATA": str(self.home / "AppData/Local"),
                    "PYTHONDONTWRITEBYTECODE": "1"}
        self.kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        signatures = {
            "OpenProcess": ([ctypes.c_uint32, ctypes.c_int32, ctypes.c_uint32], ctypes.c_void_p),
            "WaitForSingleObject": ([ctypes.c_void_p, ctypes.c_uint32], ctypes.c_uint32),
            "CloseHandle": ([ctypes.c_void_p], ctypes.c_int32),
            "GetCurrentProcess": ([], ctypes.c_void_p),
            "GetProcessHandleCount": ([ctypes.c_void_p, ctypes.POINTER(ctypes.c_uint32)], ctypes.c_int32),
        }
        for name, (arguments, result) in signatures.items():
            method = getattr(self.kernel, name)
            method.argtypes, method.restype = arguments, result

    def argv(self, code, *arguments):
        return [sys.executable, "-I", "-B", "-X", "utf8", "-u", "-c",
                textwrap.dedent(code), *arguments]

    def record(self, process, label, *, diagnostic=None):
        # base64 保存每个 VT/UTF-8 原字节，避免终端控制序列修改 runner 日志的显示。
        # 只记录本夹具 argv，不展开继承环境；可选 process.log 沿用既有 CI 证据入口。
        entry = {"kind": "conpty", "test": self.id(), "label": label, "argv": process.args,
                 "pid": process.pid, "exit": process.returncode, "closed": process.closed,
                 "raw_base64": base64.b64encode(process.raw_output).decode("ascii")}
        if diagnostic is not None:
            entry["diagnostic"] = diagnostic
        line = json.dumps(entry, ensure_ascii=False)
        print("\n[conpty evidence] " + line, flush=True)
        target = os.environ.get("AWF_TEST_EVIDENCE_LOG")
        if target:
            with open(target, "a", encoding="utf-8") as stream:
                stream.write(line + "\n")

    def launch(self, code, *arguments, label="child", **options):
        process = ConPTYProcess(self.argv(code, *arguments), cwd=self.root, env=self.env,
                                columns=120, rows=30, **options)
        self.addCleanup(self.record, process, label)
        self.addCleanup(process.close)
        # 持有真实句柄跨越 close 后确认结束，不能按 PID 重开并假设它尚未被复用。
        handle = self.kernel.OpenProcess(0x00100000, False, process.pid)
        if not handle:
            raise ctypes.WinError(ctypes.get_last_error())
        self.addCleanup(self.kernel.CloseHandle, handle)
        process._test_retained_handle = handle
        return process

    def assert_quiet(self, process):
        self.assertTrue(process.closed)
        self.assertEqual(self.kernel.WaitForSingleObject(process._test_retained_handle, 0), 0)

    def handle_count(self):
        count = ctypes.c_uint32()
        if not self.kernel.GetProcessHandleCount(self.kernel.GetCurrentProcess(), ctypes.byref(count)):
            raise ctypes.WinError(ctypes.get_last_error())
        return count.value

    def test_native_interpreter_and_standard_handle_diagnostics(self):
        # 基础解释器只作对照；全部既有原生验收仍从 sys.executable（生产 venv
        # 入口）启动。路径由当前运行时提供，并核对真实文件与 base_prefix，不能
        # 从 PATH 搜索一个“能绿”的 Python，也不加载/打印用户环境和业务文件。
        base = Path(sys._base_executable).resolve(strict=True)
        self.assertTrue(os.path.samefile(base, Path(sys.base_prefix) / Path(sys.executable).name))
        for label, executable in (("production-entry", Path(sys.executable)), ("base-comparison", base)):
            with self.subTest(entry=label):
                report, release = self.root / (label + ".json"), self.root / (label + ".release")
                argv = self.argv(CONSOLE_DIAGNOSTIC_CHILD, str(report), str(release))
                argv[0] = str(executable)
                process = ConPTYProcess(argv, cwd=self.root, env=self.env)
                data = None
                try:
                    deadline = time.monotonic() + 8
                    while not report.exists() and time.monotonic() < deadline:
                        time.sleep(.01)
                    self.assertTrue(report.exists(), "诊断 child 未写入任务临时 JSON")
                    data = json.loads(report.read_text(encoding="utf-8"))
                    self.assertTrue(os.path.samefile(data["executable"], executable))
                    self.assertEqual(data["version"], list(sys.version_info[:3]))
                    release.touch()
                    self.assertEqual(process.wait(), 0)
                finally:
                    try:
                        process.close()
                    finally:
                        # 即使 Job 屏障拒绝，也把已有身份/句柄投影保留到原日志。
                        self.record(process, label, diagnostic=data)

    def test_native_utf8_input_and_vt_output(self):
        literal = "中文 e\u0301 🧪 & !"
        self.env["AWF_CONPTY_LITERAL"] = literal
        code = CONSOLE_CHILD + """
assert sys.argv[1] == os.environ['AWF_CONPTY_LITERAL']
assert os.getcwd() == sys.argv[2]
print('AWF_CONTEXT:OK', flush=True)
set_mode(hout, mode(hout) | 4)
print('\x1b[31mAWF_VT\x1b[0m', flush=True)
print('AWF_INPUT_READY', flush=True)
value = input()
assert value == sys.argv[1], repr(value)
print('AWF_UNICODE:' + value, flush=True)
"""
        process = self.launch(code, literal, str(self.root))
        process.expect(b"AWF_INPUT_READY")
        self.assertEqual(process.write(literal + "\r"), len((literal + "\r").encode("utf-8")))
        self.assertEqual(process.wait(), 0)
        self.assertIn(b"AWF_CONTEXT:OK", process.raw_output)
        self.assertIn(b"\x1b[", process.raw_output)
        self.assertIn(b"AWF_VT", process.raw_output)
        self.assertIn(("AWF_UNICODE:" + literal).encode("utf-8"), process.raw_output)
        self.assert_quiet(process)

    def test_native_resize_reports_console_dimensions(self):
        process = self.launch("""
            import os
            print('AWF_RESIZE_READY', flush=True)
            input()
            size = os.get_terminal_size(1)
            print(f'AWF_SIZE:{size.columns},{size.lines}', flush=True)
        """)
        process.expect(b"AWF_RESIZE_READY")
        process.resize(101, 37)
        process.write(b"size\r")
        self.assertEqual(process.wait(), 0)
        self.assertIn(b"AWF_SIZE:101,37", process.raw_output)
        self.assert_quiet(process)

    def test_native_ctrl_c_targets_owned_console(self):
        other = self.launch("""
            print('AWF_BYSTANDER_READY', flush=True)
            assert input() == 'alive'
            print('AWF_BYSTANDER_ALIVE', flush=True)
        """, label="independent-console")
        other.expect(b"AWF_BYSTANDER_READY")
        target = self.launch(CONSOLE_CHILD + """
print('AWF_CTRL_READY', flush=True)
try:
    input()
except KeyboardInterrupt:
    print('AWF_OWNED_CTRL_C', flush=True)
else:
    raise AssertionError('ETX 未触发自有控制台 KeyboardInterrupt')
""", label="ctrl-target")
        target.expect(b"AWF_CTRL_READY")
        target.send_ctrl_c()
        self.assertEqual(target.wait(), 0)
        self.assertIn(b"AWF_OWNED_CTRL_C", target.raw_output)
        other.write(b"alive\r")
        self.assertEqual(other.wait(), 0)
        self.assertIn(b"AWF_BYSTANDER_ALIVE", other.raw_output)
        self.assert_quiet(target)
        self.assert_quiet(other)

    def test_native_large_output_and_exit_codes(self):
        # 同一个已受影响 native 方法保留默认 capture 分支的真实最小消费者，
        # 直接证明 optional HPCON=None 没有破坏原二进制 stdout/stderr/exit 语义。
        capture = WindowsJobProcess(self.argv("import os, sys; os.write(1, b'out\\x00'); os.write(2, b'err\\xff'); sys.exit(17)"),
                                    cwd=self.root, env=self.env, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        try:
            stdout, stderr = capture.communicate(timeout=10)
            self.assertEqual((stdout, stderr, capture.returncode), (b"out\x00", b"err\xff", 17))
            print("[conpty default capture] stdout=" + stdout.hex() + " stderr=" + stderr.hex() + " exit=17", flush=True)
        finally:
            capture.close()
        process = self.launch("""
            import sys
            for index in range(3000):
                print(f'AWF_FLOW_{index:04d}:' + 'x' * 80, flush=True)
            print('AWF_FINAL_OUTPUT', flush=True)
            sys.stderr.write('AWF_STDERR_OUTPUT\\n')
            sys.stderr.flush()
            sys.exit(23)
        """)
        self.assertEqual(process.wait(timeout=30), 23)
        self.assertIn(b"AWF_FINAL_OUTPUT", process.raw_output)
        self.assertIn(b"AWF_STDERR_OUTPUT", process.raw_output)
        self.assertGreater(len(process.raw_output), 65536)
        self.assert_quiet(process)
        overflowing = self.launch("""
            while True:
                print('AWF_BUDGET:' + 'x' * 100, flush=True)
        """, label="output-budget", output_limit=4096)
        with self.assertRaises(BufferError):
            overflowing.expect(b"AWF_NEVER_EMITTED", timeout=10)
        self.assertEqual(len(overflowing.raw_output), 4096)
        self.assert_quiet(overflowing)

    def test_native_timeout_and_cancel_quiesce_job(self):
        code = "import time; print('AWF_WAIT_READY', flush=True); time.sleep(60)"
        timed = self.launch(code, label="timeout")
        timed.expect(b"AWF_WAIT_READY")
        with self.assertRaises(subprocess.TimeoutExpired) as caught:
            timed.wait(timeout=0.1)
        self.assertIn(b"AWF_WAIT_READY", caught.exception.output)
        self.assert_quiet(timed)
        cancelled = self.launch(code, label="cancel")
        cancelled.expect(b"AWF_WAIT_READY")
        cancelled.cancel()
        with self.assertRaises(WindowsProcessCancelled):
            cancelled.wait()
        self.assert_quiet(cancelled)
        cancelled.close()  # 已关闭实例再次收尾不应重复关闭本机句柄。

    def test_native_console_modes_restore(self):
        for outcome in ("normal", "exception", "ctrl-c"):
            with self.subTest(outcome=outcome):
                process = self.launch(CONSOLE_CHILD + """
before_in, before_out = mode(hin), mode(hout)
print(f'AWF_MODE_BEFORE:{before_in},{before_out}', flush=True)
try:
    set_mode(hin, before_in & ~4)  # 仅取消自有 console 的 ECHO_INPUT。
    set_mode(hout, before_out | 4)
    print('AWF_MODE_HIDDEN_READY', flush=True)
    input()
    if sys.argv[1] == 'exception':
        raise RuntimeError('预定异常')
except (RuntimeError, KeyboardInterrupt):
    pass
finally:
    set_mode(hin, before_in)
    set_mode(hout, before_out)
assert (mode(hin), mode(hout)) == (before_in, before_out)
print(f'AWF_MODE_AFTER:{mode(hin)},{mode(hout)}', flush=True)
print('AWF_MODE_RESTORED_READY', flush=True)
assert input() == 'visible-after'
print('AWF_MODE_DONE', flush=True)
""", outcome, label="modes-" + outcome)
                before = process.expect(b"AWF_MODE_HIDDEN_READY")
                if outcome == "ctrl-c":
                    process.send_ctrl_c()
                else:
                    process.write(b"secret-before\r")
                process.expect(b"AWF_MODE_RESTORED_READY")
                process.write(b"visible-after\r")
                self.assertEqual(process.wait(), 0)
                self.assertNotIn(b"secret-before", process.raw_output)
                self.assertIn(b"AWF_MODE_DONE", process.raw_output)
                # after 的真实 Win32 数值由 child 重新查询并断言；测试另检查 echo
                # 恢复后的真实输入回显，避免只比较测试自己拼出的静态模式记录。
                marker = before.split(b"AWF_MODE_BEFORE:", 1)[1].split(b",", 1)[0]
                if int(marker) & 4:
                    self.assertIn(b"visible-after", process.raw_output)
                self.assert_quiet(process)

    def test_native_start_failure_releases_owned_resources(self):
        # 先暖启动 Windows 自己可能延迟建立的 ConPTY 设施，再比较本次失败前后的
        # runner 句柄数。三次失败复用同一 scope，不复制 runner/环境或覆盖原始红日志。
        warm = ConPTYProcess(self.argv("pass"), cwd=self.root, env=self.env)
        self.assertEqual(warm.wait(), 0)
        self.record(warm, "warm-start")
        before = self.handle_count()
        for _ in range(3):
            with self.assertRaises(OSError):
                ConPTYProcess([str(self.root / "不存在.exe")], cwd=self.root, env=self.env)
        after = self.handle_count()
        print(f"[conpty handles] before={before} after={after}", flush=True)
        self.assertEqual(after, before)


if __name__ == "__main__":
    unittest.main()
