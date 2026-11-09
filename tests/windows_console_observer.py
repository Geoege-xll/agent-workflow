"""测试专用的只读 Win32 控制台观察器，不解析 VT 或替代 curses 屏幕。

ABI 来源：Microsoft Learn 的 CHAR_INFO、CONSOLE_SCREEN_BUFFER_INFO、
ReadConsoleOutputW、GetConsoleMode 与 GetConsoleCursorInfo。所有观察都在
ConPTY 自有子进程中进行，不 AttachConsole/FreeConsole，也不改变 runner 模式。
"""

from __future__ import annotations

from contextlib import contextmanager
import ctypes as C
import importlib.metadata
import json
import os
from pathlib import Path
import sys
import threading
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


def run_observed(root, arguments):
    """真实 CLI/TUI 在主线程运行；旁路线程只读取原生 buffer/modes/cursor。

    请求/响应文件只位于本方法专有目录，最终报告保留 wrapper 前后的实际模式。
    不包装 App、不注入按键、不读取 App 的私有选择状态；交互完全经过 ConPTY。
    """
    from manager.cli import main

    root = Path(root)
    observer = ConsoleObserver()
    before = observer.snapshot()
    stop = threading.Event()
    failures = []

    def watch():
        number = 1
        while not stop.wait(0.02):
            request = message_path(root, "requests", number)
            if not request.is_file():
                continue
            try:
                read_message(request, number)
                _publish(message_path(root, "responses", number), {"number": number, "snapshot": observer.snapshot()})
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
        result = main(arguments)
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
                 "python": list(sys.version_info[:3]),
                 "windows_curses": importlib.metadata.version("windows-curses")})
