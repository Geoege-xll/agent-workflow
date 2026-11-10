"""测试专用的只读 Win32 控制台观察器，不解析 VT 或替代 curses 屏幕。

ABI 来源：Microsoft Learn 的 CHAR_INFO、CONSOLE_SCREEN_BUFFER_INFO、
ReadConsoleOutputW、GetConsoleMode 与 GetConsoleCursorInfo。所有观察都在
ConPTY 自有子进程中进行，不 AttachConsole/FreeConsole，也不改变 runner 模式。
"""

from __future__ import annotations

from contextlib import contextmanager
import ctypes as C
import dis
import importlib.metadata
import inspect
import json
import os
from pathlib import Path
import sys
import threading
import time
import traceback


# 使用固定宽度，保证 Mac 的导入/ABI 检查不会把宿主 wchar_t/long 当作 Win32。
WORD, DWORD, BOOL, HANDLE = C.c_uint16, C.c_uint32, C.c_int32, C.c_void_p


class COORD(C.Structure):
    _fields_ = [("X", C.c_int16), ("Y", C.c_int16)]


class SMALL_RECT(C.Structure):
    _fields_ = [(name, C.c_int16) for name in ("Left", "Top", "Right", "Bottom")]


class CHAR_INFO(C.Structure):
    # 观察器只调用 W 变体，因此联合体的 WCHAR 和 WORD 具有相同的两字节布局。
    _fields_ = [("UnicodeChar", WORD), ("Attributes", WORD)]


class CONSOLE_SCREEN_BUFFER_INFO(C.Structure):
    _fields_ = [("dwSize", COORD), ("dwCursorPosition", COORD),
                ("wAttributes", WORD), ("srWindow", SMALL_RECT), ("dwMaximumWindowSize", COORD)]


class CONSOLE_CURSOR_INFO(C.Structure):
    _fields_ = [("dwSize", DWORD), ("bVisible", BOOL)]


class ConsoleObserver:
    """只拥有短命控制台观察句柄；不拥有进程、Job 或伪控制台。"""

    def __init__(self):
        if os.name != "nt":
            raise OSError("原生控制台观察器只能在 Windows 使用")
        self.kernel = C.WinDLL("kernel32", use_last_error=True)
        for name, args, result in (
            ("CreateFileW", [C.c_wchar_p, DWORD, DWORD, HANDLE, DWORD, DWORD, HANDLE], HANDLE),
            ("CloseHandle", [HANDLE], BOOL),
            ("GetConsoleMode", [HANDLE, C.POINTER(DWORD)], BOOL),
            ("GetConsoleScreenBufferInfo", [HANDLE, C.POINTER(CONSOLE_SCREEN_BUFFER_INFO)], BOOL),
            ("GetConsoleCursorInfo", [HANDLE, C.POINTER(CONSOLE_CURSOR_INFO)], BOOL),
            ("ReadConsoleOutputW", [HANDLE, C.POINTER(CHAR_INFO), COORD, COORD, C.POINTER(SMALL_RECT)], BOOL),
        ):
            method = getattr(self.kernel, name)
            method.argtypes, method.restype = args, result

    def check(self, result):
        if not result:
            raise C.WinError(C.get_last_error())
        return result

    @contextmanager
    def device(self, name):
        # 每次重新打开活动 buffer：PDCurses 可切换 screen buffer，保留启动前
        # 句柄会读到旧 shell 屏幕。CI42614154168 的同 console 原生对照证明：
        # CONOUT$ 的 READ 可读格子/模式，但 GetConsoleCursorInfo 返回错误 5；
        # READ|WRITE 才能完整读取光标。句柄访问权限与执行写操作是两回事：
        # 本观察器仍仅调用 Get/Read APIs，绝不靠 Set/Write 或临时输出校准屏幕。
        # CONIN$ 的模式读取不需要扩大权限，保持 GENERIC_READ。
        access = 0xc0000000 if name == "CONOUT$" else 0x80000000
        handle = self.kernel.CreateFileW(name, access, 3, None, 3, 0, None)
        if handle in (None, HANDLE(-1).value):
            raise C.WinError(C.get_last_error())
        try:
            yield handle
        finally:
            self.check(self.kernel.CloseHandle(handle))

    def mode(self, handle):
        value = DWORD()
        self.check(self.kernel.GetConsoleMode(handle, C.byref(value)))
        return value.value

    def snapshot(self):
        with self.device("CONIN$") as input_handle, self.device("CONOUT$") as output_handle:
            before, after = CONSOLE_SCREEN_BUFFER_INFO(), CONSOLE_SCREEN_BUFFER_INFO()
            self.check(self.kernel.GetConsoleScreenBufferInfo(output_handle, C.byref(before)))
            window = before.srWindow
            width, height = window.Right - window.Left + 1, window.Bottom - window.Top + 1
            if not (0 < width <= 240 and 0 < height <= 120):
                raise ValueError(f"测试快照超出有界视口：{width}×{height}")
            region = SMALL_RECT(window.Left, window.Top, window.Right, window.Bottom)
            cells = (CHAR_INFO * (width * height))()
            self.check(self.kernel.ReadConsoleOutputW(output_handle, cells, COORD(width, height),
                                                     COORD(0, 0), C.byref(region)))
            cursor = CONSOLE_CURSOR_INFO()
            self.check(self.kernel.GetConsoleCursorInfo(output_handle, C.byref(cursor)))
            self.check(self.kernel.GetConsoleScreenBufferInfo(output_handle, C.byref(after)))
            wanted = (window.Left, window.Top, window.Right, window.Bottom)
            actual = (region.Left, region.Top, region.Right, region.Bottom)
            current = (after.srWindow.Left, after.srWindow.Top, after.srWindow.Right, after.srWindow.Bottom)
            units, attrs, lines = [], [], []
            for row in range(height):
                data = cells[row * width:(row + 1) * width]
                units.append([cell.UnicodeChar for cell in data])
                attrs.append([cell.Attributes for cell in data])
                # ReadConsoleOutputW 的原生 TRAILING_BYTE 标志表示宽字符尾格。
                # 展示文本仅排除这些重复格，不使用自写 Unicode 宽度或 VT 终端模型。
                line = "".join(chr(cell.UnicodeChar or 32) for cell in data
                               if not cell.Attributes & 0x0200)
                lines.append(line)
            return {"width": width, "height": height, "window": wanted,
                    "stable": wanted == actual == current,
                    "cursor": [after.dwCursorPosition.Y - window.Top,
                               after.dwCursorPosition.X - window.Left],
                    "cursor_visible": bool(cursor.bVisible), "cursor_size": cursor.dwSize,
                    "input_mode": self.mode(input_handle), "output_mode": self.mode(output_handle),
                    "units": units, "attributes": attrs, "lines": lines}


def _publish(path, value):
    """单写者排他发布一次 JSON；已发布名字永远不再覆盖或删除。

    每个序号/方向只有一个写者。先关闭 pending 的写句柄，再 rename 到
    未出现过的名字；Windows rename 还会原生拒绝目标碰撞。读者无需共享
    删除权限，后续序号也不会替换其持有的文件。错误直接传播，不重试权限错误。
    """
    if path.exists():
        raise FileExistsError(f"原生观察消息已经发布：{path.name}")
    pending = path.with_suffix(".pending")
    with pending.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=True)
    pending.rename(path)


def message_path(root, direction, number):
    """父测试与观察线程共用序号命名；这只是单次测试 IPC 的局部游标。"""
    if direction not in {"requests", "responses"} or type(number) is not int or number <= 0:
        raise ValueError("原生观察消息方向或序号无效")
    return Path(root) / direction / f"{number:08d}.json"


def read_message(path, number, *, response=False):
    """关闭读取句柄后校验封闭信封；权限/解码/序号错误都是真实协议失败。"""
    value = json.loads(path.read_text(encoding="utf-8"))
    keys = {"number", "snapshot"} if response else {"number"}
    if (not isinstance(value, dict) or set(value) != keys or type(value["number"]) is not int
            or value["number"] != number or response and not isinstance(value["snapshot"], dict)):
        raise ValueError(f"原生观察消息不属于预期序号 {number}：{path.name}")
    return value


def cursor_access_diagnostics(path):
    """实际比较两种 CONOUT$ 访问权限；保留每个 Get API 的原始状态。

    首轮真实 Server 在 GENERIC_READ 的 GetConsoleCursorInfo 返回错误 5，
    而前面的 buffer/ReadConsoleOutputW 成功。本入口只诊断该差异，不修改
    snapshot 默认访问、不写入控制台、不替换生产 UI，也不把失败字段的零值
    当成有效光标信息。结果文件仅位于调用测试的私有目录。
    """
    observer = ConsoleObserver()
    results = {}
    for label, access in (("read", 0x80000000), ("readwrite", 0xc0000000)):
        handle = observer.kernel.CreateFileW("CONOUT$", access, 3, None, 3, 0, None)
        item = results[label] = {"access": access}
        if handle in (None, HANDLE(-1).value):
            item["open_error"] = C.get_last_error()
            continue
        try:
            for name, value in (("mode", DWORD()), ("buffer", CONSOLE_SCREEN_BUFFER_INFO()),
                                ("cursor", CONSOLE_CURSOR_INFO())):
                method = {"mode": "GetConsoleMode", "buffer": "GetConsoleScreenBufferInfo",
                          "cursor": "GetConsoleCursorInfo"}[name]
                C.set_last_error(0)
                ok = bool(getattr(observer.kernel, method)(handle, C.byref(value)))
                record = item[name] = {"ok": ok, "winerror": C.get_last_error()}
                if not ok:
                    continue
                if name == "mode":record["value"] = value.value
                elif name == "cursor":record.update(size=value.dwSize, visible=bool(value.bVisible))
                else:
                    record["window"] = [value.srWindow.Left, value.srWindow.Top,
                                        value.srWindow.Right, value.srWindow.Bottom]
                    record["cursor"] = [value.dwCursorPosition.Y, value.dwCursorPosition.X]
            if item["buffer"]["ok"]:
                left, top, right, bottom = item["buffer"]["window"]
                width, height = right - left + 1, bottom - top + 1
                if not (0 < width <= 240 and 0 < height <= 120):
                    raise ValueError("原生访问权限诊断超出有界视口")
                cells = (CHAR_INFO * (width * height))()
                region = SMALL_RECT(left, top, right, bottom)
                C.set_last_error(0)
                ok = bool(observer.kernel.ReadConsoleOutputW(handle, cells, COORD(width, height),
                                                            COORD(0, 0), C.byref(region)))
                item["screen"] = {"ok": ok, "winerror": C.get_last_error()}
                if ok:
                    item["screen"].update(width=width, height=height,
                        region=[region.Left, region.Top, region.Right, region.Bottom],
                        units=[[cell.UnicodeChar for cell in cells[row * width:(row + 1) * width]] for row in range(height)],
                        attributes=[[cell.Attributes for cell in cells[row * width:(row + 1) * width]] for row in range(height)])
        finally:
            observer.check(observer.kernel.CloseHandle(handle))
    _publish(Path(path), {"executable": sys.executable, "results": results})


def _stack_positions(frame):
    """把现有 Python 栈立即投影为有界 JSON 字段，不保留任何 frame 引用。"""
    stack = []
    truncated = False
    try:
        # 从叶子向外最多取 24 层；长路径/函数名也封顶，并显式记录截断。
        # 只读 code 元数据和当前行号，不读源码正文、locals 或 Job 的私有状态。
        while frame is not None and len(stack) < 24:
            filename, function = frame.f_code.co_filename, frame.f_code.co_name
            truncated = truncated or len(filename) > 1024 or len(function) > 128
            stack.append({"file": filename[:1024], "function": function[:128], "line": frame.f_lineno})
            frame = frame.f_back
        return list(reversed(stack)), truncated or frame is not None
    finally:
        # 包括异常出口也解除参数引用，避免诊断延长执行栈及其局部资源生命周期。
        del frame


def _main_thread_observation(number, started):
    """同一观察线程一次采样主线程及既有 App executor，不读取业务对象。"""
    # App.loop 使用标准 ThreadPoolExecutor 的默认前缀；只枚举已存在的线程，
    # 不读取 App/executor 实例、不增加观察线程，也不把 native helper 混入此表。
    workers = sorted((thread.name, thread.ident) for thread in threading.enumerate()
                     if thread.name.startswith("ThreadPoolExecutor-") and thread.ident is not None)
    frames = sys._current_frames()
    try:
        main_ident = threading.main_thread().ident
        if main_ident not in frames:
            raise RuntimeError("无法取得生产 TUI 主线程调用位置")
        main_stack, _ = _stack_positions(frames[main_ident])
        executor_stacks = []
        for name, ident in workers[:4]:
            # 线程可在枚举和采样间结束；available 明示这个竞态，不能用空栈
            # 冒充已取得执行位置。列表超限与每个栈/名称的截断分别显式保留。
            stack, truncated = _stack_positions(frames.get(ident))
            executor_stacks.append({"name": name[:128], "ident": ident, "available": ident in frames,
                                    "stack": stack, "truncated": truncated or len(name) > 128})
        return {"number": number, "elapsed_ns": time.monotonic_ns() - started, "main_stack": main_stack,
                "executor_stacks": {"total": len(workers), "truncated": len(workers) > 4, "threads": executor_stacks}}
    finally:
        # _current_frames 返回的私有字典握持全部线程栈。成功/异常均立即清空并
        # 删除它，返回值只含标量和普通容器，不依赖后续 GC 才释放文件或 locals。
        frames.clear()
        del frames


class PhaseProfile:
    """测试专用的有界阶段遥测；只存固定标签、整数及 code 绑定，不存执行帧。"""

    MAX_WORKERS, MAX_JOBS, MAX_ACTIVE = 4, 64, 64
    MAX_PHASE_EVENTS, MAX_WORKER_EVENTS, MAX_EVENTS = 4096, 32768, 65536
    LABELS = ("apply", "load_context.body", "read_operation.wrapper", "_scan", "_verify_snapshot", "CoreReadOperation.finish")

    def __init__(self, started=None):
        from lib import runtime_store
        from manager import model_preferences
        from manager.tui_state import Job

        self.started = time.monotonic_ns() if started is None else started
        self.lock = threading.RLock()
        self.workers = {}
        self.events = self.recording_ns = 0
        self.overflow = self.recording_error = False
        self.previous = None
        self.job_code = Job.execute.__code__
        # 只接受 Job.execute 现有的两个唯一 CALL 源位置。3.11..3.14 的 CALL
        # cache/字节偏移可不同，因此仅用 code identity 与位置元数据，不猜偏移。
        calls = [row for row in dis.get_instructions(Job.execute) if row.opname == "CALL"]
        lines = [row.positions.lineno for row in calls]
        self.binding_incomplete = len(lines) != 2 or None in lines or len(set(lines)) != 2
        self.sites = dict(zip(lines, ("operation", "refresh"))) if not self.binding_incomplete else {}
        self.codes = {
            model_preferences.apply.__code__: "apply",
            inspect.unwrap(model_preferences.load_context).__code__: "load_context.body",
            model_preferences.load_context.__code__: "read_operation.wrapper",
            runtime_store._scan.__code__: "_scan",
            runtime_store._verify_snapshot.__code__: "_verify_snapshot",
            runtime_store.CoreReadOperation.finish.__code__: "CoreReadOperation.finish",
        }
        # read_operation 的 scoped 被多个来源函数共享，只能聚合为 wrapper，
        # 绝不把共享 code 的所有调用误标为 load_context。生成器不作普通计时。
        self.binding_incomplete |= len(self.codes) != 6 or any(code.co_flags & inspect.CO_GENERATOR for code in self.codes)

    @contextmanager
    def installed(self):
        """仅影响之后创建的 worker；保留旧 thread hook，不触碰 main 的 sys hook。"""
        previous = threading.getprofile()
        self.previous = previous
        threading.setprofile(self._profile)
        try:
            yield self
        finally:
            threading.setprofile(previous)

    @staticmethod
    def _phase():
        return {"started": None, "ended": None, "incomplete": False, "overflow": False, "events": 0,
                "functions": {label: {"calls": 0, "returns": 0, "inclusive_ns": 0} for label in PhaseProfile.LABELS}}

    def _overflow(self, worker, job, phase=None):
        self.overflow = worker["overflow"] = job["incomplete"] = True
        if phase is not None:phase["incomplete"] = phase["overflow"] = True

    def _accept(self, worker, job, phase):
        if (phase["events"] >= self.MAX_PHASE_EVENTS or worker["events"] >= self.MAX_WORKER_EVENTS
                or self.events >= self.MAX_EVENTS):
            self._overflow(worker, job, phase)
            return False
        phase["events"] += 1;worker["events"] += 1;self.events += 1
        return True

    def _profile(self, frame, event, arg):
        # 原 hook 总是按原参数透传；不查看 arg（参数/返回值/异常对象），旧 hook
        # 自身的行为及异常不由本诊断吞掉。未选事件不取时钟、不 resolve 路径。
        if self.previous is not None:self.previous(frame, event, arg)
        if self.binding_incomplete or event not in {"call", "return"}:return
        code, ident = frame.f_code, threading.get_ident()
        worker = self.workers.get(ident)
        if code is not self.job_code and (worker is None or worker["job"] is None):return
        if code is not self.job_code:
            job = worker["job"]
            if job["closed"]:return
            # phase 内未选函数直接走 fastpath；只有等待直系 phase 根调用时
            # 才检查一个 parent，不对每个事件遍历栈或读取 Job/locals。
            if job["phase"] is not None and code not in self.codes and not (event == "return" and id(frame) == job["phase_frame"]):return
        begin = time.monotonic_ns()
        try:
            with self.lock:
                self._record(frame, event, code, ident, begin)
                # 仅统计选中记录路径的开销，不含旧 hook/未选 fastpath；不能从
                # phase wall time 扣除此数宣称得到“无插桩业务耗时”。
                self.recording_ns += time.monotonic_ns() - begin
        except Exception:
            # 诊断自身出错只标记不完整；不改变生产调用结果，也不记录异常正文。
            self.recording_error = True
            if worker is not None and worker["job"] is not None:worker["job"]["incomplete"] = True

    def _record(self, frame, event, code, ident, now):
        worker = self.workers.get(ident)
        frame_id = id(frame)
        if code is self.job_code and event == "call":
            name = threading.current_thread().name
            if not name.startswith("ThreadPoolExecutor-"):return
            if worker is None:
                if len(self.workers) >= self.MAX_WORKERS:self.overflow = True;return
                worker = self.workers[ident] = {"name": name[:128], "events": 0, "jobs": 0, "overflow": False, "job": None}
            if worker["job"] is not None and not worker["job"]["closed"]:
                self._overflow(worker, worker["job"]);return
            if worker["jobs"] >= self.MAX_JOBS:
                self._overflow(worker, worker["job"]);return
            worker["jobs"] += 1
            worker["job"] = {"index": worker["jobs"], "frame": frame_id, "closed": False, "incomplete": False,
                             "phase": None, "phase_frame": None, "active": {},
                             "phases": {"operation": self._phase(), "refresh": self._phase()}}
            return
        if worker is None or worker["job"] is None:return
        job = worker["job"]
        if job["closed"]:return
        if code is self.job_code and event == "return" and frame_id == job["frame"]:
            # 非 Python callable 等情况没有可绑定的直系 call 根；明确报告缺口，
            # 不能把没有 operation 计时的区间伪装成完整的零耗时。
            if job["phases"]["operation"]["started"] is None:
                job["incomplete"] = job["phases"]["operation"]["incomplete"] = True
            if job["phase"] is not None:
                job["incomplete"] = True
                job["phases"][job["phase"]]["incomplete"] = True
            job["closed"] = True;job["active"].clear();return
        if job["phase"] is None and event == "call":
            parent = frame.f_back
            try:
                phase_name = self.sites.get(parent.f_lineno) if parent is not None and parent.f_code is self.job_code and id(parent) == job["frame"] else None
            finally:del parent
            if phase_name is None:return
            job["phase"], job["phase_frame"] = phase_name, frame_id
            job["phases"][phase_name]["started"] = now
        if job["phase"] is None:return
        phase = job["phases"][job["phase"]]
        label = self.codes.get(code)
        if event == "call" and label is not None:
            if len(job["active"]) >= self.MAX_ACTIVE:self._overflow(worker, job, phase)
            elif self._accept(worker, job, phase):
                job["active"][frame_id] = (label, now)
                phase["functions"][label]["calls"] += 1
        elif event == "return" and frame_id in job["active"]:
            label, started = job["active"].pop(frame_id)
            if self._accept(worker, job, phase):
                metric = phase["functions"][label]
                metric["returns"] += 1;metric["inclusive_ns"] += now - started
        if event == "return" and frame_id == job["phase_frame"]:
            # 这是 Job 直系 operation/refresh callable 的退出，故包含 lambda
            # 内装饰器 with 的 lease 尾验；不靠 load_context body 返回判断阶段结束。
            phase["ended"] = now
            if job["active"]:phase["incomplete"] = job["incomplete"] = True
            job["active"].clear();job["phase"] = job["phase_frame"] = None

    def snapshot(self):
        """只返回当前/最近一次 Job 的固定两阶段，不输出逐事件或历史列表。"""
        now = time.monotonic_ns()
        with self.lock:
            workers = []
            for ident, worker in self.workers.items():
                row = {"ident": ident, "name": worker["name"], "jobs": worker["jobs"], "events": worker["events"], "overflow": worker["overflow"], "job": None}
                job = worker["job"]
                if job is not None:
                    phases = {}
                    for name, phase in job["phases"].items():
                        # 各函数是包容耗时，可能相互嵌套；active_ns 只描述尚未
                        # 返回的选中调用，不能把这些值相加或当作无插桩性能结果。
                        functions = {label: {**metric, "inflight": 0, "active_ns": 0} for label, metric in phase["functions"].items()}
                        if job["phase"] == name:
                            for label, started in job["active"].values():
                                functions[label]["inflight"] += 1;functions[label]["active_ns"] += now - started
                        phases[name] = {"started_ns": None if phase["started"] is None else phase["started"] - self.started,
                                        "ended_ns": None if phase["ended"] is None else phase["ended"] - self.started,
                                        "elapsed_ns": 0 if phase["started"] is None else (phase["ended"] or now) - phase["started"],
                                        "incomplete": phase["incomplete"], "overflow": phase["overflow"], "events": phase["events"], "functions": functions}
                    # return/unwind 只表示区间闭合，不表示业务成功；成功事实仍由
                    # 正式结果/错误/原生屏幕断言决定，不查看 profile 的返回参数。
                    row["job"] = {"index": job["index"], "closed": job["closed"], "phase": job["phase"], "incomplete": job["incomplete"], "phases": phases}
                workers.append(row)
            return {"binding_incomplete": self.binding_incomplete, "recording_error": self.recording_error,
                    "overflow": self.overflow, "events": self.events, "recording_ns": self.recording_ns,
                    "workers": workers}


def run_observed(root, arguments):
    """真实 CLI/TUI 在主线程运行；原观察线程只读原生控制台与有界栈位置。

    请求/响应文件只位于本方法专有目录，最终报告保留 wrapper 前后的实际模式。
    不包装 App、不注入按键、不读取 App 的私有选择状态；交互完全经过 ConPTY。
    """
    from manager.cli import main

    root = Path(root)
    observer = ConsoleObserver()
    before = observer.snapshot()
    stop = threading.Event()
    failures = []
    started = time.monotonic_ns()
    phases = PhaseProfile(started)

    def watch():
        number = 1
        while not stop.wait(0.02):
            request = message_path(root, "requests", number)
            if not request.is_file():
                continue
            try:
                read_message(request, number)
                snapshot = observer.snapshot()
                snapshot["observation"] = _main_thread_observation(number, started)
                snapshot["observation"]["phase_profile"] = phases.snapshot()
                _publish(message_path(root, "responses", number), {"number": number, "snapshot": snapshot})
                # 响应发布后才推进游标；父端也必须取得该响应才能提交下一请求。
                # 历史消息保留到进程/线程结束，不在读者打开文件期间回收名字。
                number += 1
            except BaseException:
                # 观察失败是原生验收失败；保留 traceback，不改为模拟屏幕或空快照。
                error = traceback.format_exc()
                failures.append(error)
                _publish(root / "observer-error.json", {"error": error})
                return

    worker = threading.Thread(target=watch, name="awf-native-console-observer")
    worker.start()
    result, error = None, None
    try:
        # 观察线程已启动，profile 仅安装到之后的 App executor；现有 main hook
        # 保持原状，成功/异常均先恢复 thread hook，再沿原 final/模式出口收尾。
        with phases.installed():result = main(arguments)
        return result
    except BaseException:
        error = traceback.format_exc()
        raise
    finally:
        stop.set()
        worker.join(5)
        if worker.is_alive():
            raise RuntimeError("只读原生控制台观察线程未结束")
        after = observer.snapshot()
        _publish(root / "final.json", {"before": before, "after": after, "exit": result,
                 "error": error, "observer_errors": failures, "executable": sys.executable,
                 "phase_profile": phases.snapshot(),
                 "python": list(sys.version_info[:3]),
                 "windows_curses": importlib.metadata.version("windows-curses")})
