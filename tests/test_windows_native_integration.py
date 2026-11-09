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
import sys
import tempfile
import time
import unicodedata
import unittest
from unittest.mock import patch
import uuid

from lib import runtime_store
from lib.central.role_preferences import snapshot as preference_snapshot
from lib.hosts.native_context import HostPaths, NativeContext
from manager import central_runtime, model_preferences, project_service, service
from tests.windows_conpty import ConPTYProcess


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


class NativeUI:
    """测试端请求只读快照；进程/管道回收完全交给既有 ConPTYProcess。"""

    def __init__(self, case, root, argv, environment):
        self.case, self.root, self.argv = case, root, argv
        self.sequence, self.frames = 0, []
        self.process = ConPTYProcess(argv, cwd=PACK, env=environment, columns=120, rows=36)

    def key(self, value):
        self.process.write(KEYS.get(value, value))

    def snapshot(self, timeout=5):
        self.sequence += 1
        pending, request = self.root / "request.pending", self.root / "request.json"
        pending.write_text(json.dumps({"number": self.sequence}), encoding="utf-8")
        pending.replace(request)
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            error = self.root / "observer-error.json"
            if error.exists():
                self.case.fail(error.read_text(encoding="utf-8"))
            response = self.root / "response.json"
            if response.exists():
                value = json.loads(response.read_text(encoding="utf-8"))
                if value["number"] == self.sequence:
                    return value["snapshot"]
            if (self.root / "final.json").exists():
                self.case.fail("生产 TUI 提前结束：" + (self.root / "final.json").read_text(encoding="utf-8"))
            time.sleep(0.02)
        self.case.fail("原生控制台观察响应超时；VT=" + repr(self.process.raw_output[-3000:]))

    @staticmethod
    def text(frame):
        # Windows 可返回预组合字符；等价 Unicode 文本只用于查找，原始 UTF-16
        # 字符格与颜色属性始终完整保存，光标/布局断言仍使用原生坐标。
        return unicodedata.normalize("NFC", "\n".join(frame["lines"]))

    def wait(self, label, predicate, timeout=30):
        deadline, last = time.monotonic() + timeout, None
        while time.monotonic() < deadline:
            last = self.snapshot()
            if last["stable"] and predicate(last):
                self.frames.append({"label": label, "native": last})
                return last
            time.sleep(0.03)
        if last is not None:
            self.frames.append({"label": label + "-failed", "native": last})
        self.case.fail(f"原生屏幕未达到 {label}：\n" + (self.text(last) if last else "无快照"))

    def text_is(self, *values, absent=(), timeout=30):
        return self.wait(" / ".join(values), lambda frame:
                         all(unicodedata.normalize("NFC", text) in self.text(frame) for text in values)
                         and not any(text in self.text(frame) for text in absent), timeout)

    def ready(self):
        return self.text_is("角色模型", "后端开发", absent=("执行中",))

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

    def choose(self, query, next_text):
        # 第一回车只接受筛选，第二回车才激活正式选择器中的选项。
        self.key("/" + query + "\r")
        self.text_is("/ " + query)
        self.key("enter")
        previous = "选择模型" if next_text == "选择推理级别" else "选择推理级别"
        return self.text_is(next_text, absent=("执行中", previous))

    def model(self, query, effort="high"):
        self.key("m");self.text_is("选择模型", absent=("执行中",))
        self.choose(query, "选择推理级别")
        self.choose(effort, "已暂存，尚未保存")

    def save(self):
        self.key("s");self.text_is("保存预览", "确认备份并保存", absent=("执行中",))
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
                 "frames": self.frames,
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
            ui.key("esc");ui.text_is("角色模型", "1 项未保存")
            ui.key("s");ui.text_is("保存预览", "确认备份并保存")
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
