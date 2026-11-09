import argparse
import importlib
import os
from pathlib import Path
import re
import sys
import unittest


# 原生 Python 和 Bash 都只进入本文件。先固定源码物理根，再显式加入仓库导入路径，
# 因而从其他 cwd 或以 -I 启动时仍收集同一清单，不误用调用目录中的 tests 包。
PACK = Path(__file__).resolve().parents[1]


def modules(*names):
    return tuple("tests.test_" + name for name in names)


# 分组只声明真实模块/类/方法，不导入 TestCase 作为夹具。旧入口的模块范围保持不变；
# service/tui 与 pty 按真实节点拆开，因此普通单元验证不会隐式启动伪终端。
GROUPS = {
    "codex": modules("codex_workflow", "shared_memory_contract"),
    "claude": modules("claude_workflow", "claude_instructions", "shared_memory_contract"),
    "antigravity": modules("antigravity_workflow"),
    "prototype": modules("prototype_workspace"),
    "packaging": modules("homebrew_packaging"),
    "central": modules("central_project", "runtime_store", "runtime_state", "central_runtime", "runtime_lifecycle") + (
        "tests.test_workflow_manager.CentralCliIntegrationTest",
        "tests.test_workflow_manager.InstalledProjectIntegrationTest",
    ),
    "service": tuple("tests.test_workflow_manager." + name for name in (
        "ModelContractTest", "CatalogTest", "ClaudeExecutionAndDiagnosticsTest",
        "TransactionTest", "AddInstallTest", "InstallerBoundaryTest", "CliLauncherTest",
        "TerminalAndCliTest.test_deep_json_model_source_cli_has_safe_projection",
        "TerminalAndCliTest.test_tui_interrupt_waits_for_synchronous_central_settlement",
        "TerminalAndCliTest.test_launcher_preserves_relative_project_paths",
    )) + modules("role_preferences", "native_usage", "platform_bridge", "native_agents", "install_cli"),
    "tui": tuple("tests.test_manager_tui." + name for name in (
        "TextInputTest", "TuiTest", "TerminalCellsTest",
        "ProjectTuiIntegrationTest.test_real_project_lifecycle_versions_details_and_deletion_focus",
        "ProjectTuiIntegrationTest.test_hand_edit_conflict_and_unknown_pin_remain_visible_without_fallback",
        "ProjectTuiIntegrationTest.test_damaged_version_list_fails_and_keeps_model_draft",
    )),
    "pty": (
        "tests.test_manager_tui.ProjectTuiIntegrationTest.test_real_pty_registration_cancel_enable_disable_versions_conflict_and_resize",
        "tests.test_workflow_manager.TerminalAndCliTest.test_real_terminal_keyboard_and_resize_smoke",
    ),
}
GROUPS["hosts"] = (
    GROUPS["codex"] + GROUPS["claude"] + GROUPS["antigravity"]
    + modules("unified_host_workflow", "antigravity_upgrade_boundaries", "claude_options",
              "bootstrap_routing", "astra_instruction_adaptation", "project_role_lifecycle")
)
# CI 是有明确合同的组合：当前 CLI/pin/模型收据、记录/见证容量、三宿主共享正文和中央软链、真实
# PTY、离线归档及 Ruby Formula 消费者。Node 对应需求 HTML 的真实运行时消费者。
GROUPS["ci"] = (
    modules("validation_runner")
    + ("tests.test_workflow_manager.CentralCliIntegrationTest",)
    + modules("central_project", "runtime_state", "central_runtime", "runtime_lifecycle", "native_agents", "install_cli")
    + ("tests.test_manager_tui.TuiTest.test_platform_reset_is_independent_and_consumes_only_captured_keys",
       "tests.test_manager_tui.TuiTest.test_runtime_actions_use_captured_context_and_modal_focus")
    + ("tests.test_unified_host_workflow.UnifiedSetupContractTest.test_all_hosts_generate_core_skills_from_one_shared_source",)
    + modules("requirement_html") + GROUPS["pty"] + GROUPS["packaging"]
)

# 初始原生集合只绑定已经存在的真实 Win32 测试类；后续平台消费者由本入口 owner
# 增补。此组不引入 POSIX PTY、Git Bash 或 portable mock 来充当 Windows 验收。
GROUPS["windows-native"] = (
    "tests.test_windows_runtime.WindowsFilesystemNativeTest",
    "tests.test_install_process_windows.NativeWindowsJobTest",
)


def make_parser():
    parser = argparse.ArgumentParser(
        description="唯一 unittest 入口；无参数只显示帮助，全套必须显式选择 full。",
        epilog=("组：" + ", ".join((*GROUPS, "full")) + "。\n"
                "节点：tests.test_模块[.测试类[.test_方法]]；允许与组组合。\n"
                "示例：bash scripts/test_workflow.sh --list ci\n"
                "      bash scripts/test_workflow.sh service tests.test_runtime_store\n"
                "      python -I -B -X utf8 scripts/test_workflow.py windows-native\n"
                "依赖：Python >= 3.11；requirement_html/ci 需要 Node，packaging/ci 需要 Ruby；PTY 需要 POSIX。"),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--list", action="store_true", help="校验后逐行显示实际测试目标，不运行测试")
    parser.add_argument("selectors", nargs="*", metavar="组或节点")
    return parser


def flatten(suite):
    for item in suite:
        if isinstance(item, unittest.TestSuite):
            yield from flatten(item)
        else:
            yield item


def load_target(target, parser):
    # 只允许仓内 test_ 模块及真实 TestCase/test 方法，拒绝任意模块/可调用对象。
    # 先校验完整计划再执行任何测试，避免拼错后半个参数却已执行前半个计划。
    if not re.fullmatch(r"tests\.test_[A-Za-z0-9_]+(?:\.[A-Za-z_][A-Za-z0-9_]*){0,2}", target):
        parser.error("未知测试组或节点：" + target)
    parts = target.split(".")
    module_name = ".".join(parts[:2])
    if not Path(*parts[:2]).with_suffix(".py").is_file():
        parser.error("未知测试模块：" + module_name)
    module = importlib.import_module(module_name)
    loader = unittest.TestLoader()
    if len(parts) == 2:
        suite = loader.loadTestsFromModule(module)
    else:
        case = getattr(module, parts[2], None)
        if not (isinstance(case, type) and issubclass(case, unittest.TestCase)
                and case.__module__ == module_name):
            parser.error("未知测试类：" + target)
        if len(parts) == 4:
            if parts[3] not in loader.getTestCaseNames(case):
                parser.error("未知测试方法：" + target)
            suite = unittest.TestSuite((case(parts[3]),))
        else:
            suite = loader.loadTestsFromTestCase(case)
    # 模块复用夹具不得让外部导入类参与本模块收集；真实用例仍在所属模块执行。
    tests = [case for case in flatten(suite) if case.__class__.__module__ == module_name]
    if not tests:
        parser.error("目标没有可运行测试：" + target)
    return tests


class ExecutionResult(unittest.TextTestResult):
    def startTest(self, test):
        super().startTest(test)
        self.started_ids.add(test.id())

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.started_ids = set()


def run_cases(cases, required_native_ids=()):
    result = unittest.TextTestRunner(verbosity=2, resultclass=ExecutionResult).run(unittest.TestSuite(cases))
    # unittest 把全 skip 当成功，但原生必验集合必须真正执行。逐个 required id 核对，
    # 既拒绝全 skip，也拒绝自定义 suite 未执行节点；失败用原退出码 1 向上传播。
    skipped = {case.id() for case, _ in result.skipped}
    executed = result.started_ids - skipped
    if required_native_ids and not set(required_native_ids).issubset(executed):
        print("原生必验节点未实际执行或被 skip；不能作为 Windows 验收成功。", file=sys.stderr)
        return 1
    return 0 if result.wasSuccessful() else 1


def main():
    os.chdir(PACK)
    sys.path.insert(0, str(PACK))
    parser = make_parser()
    args = parser.parse_args()
    if not args.selectors:
        parser.print_help()
        return 0
    targets = []
    for selector in args.selectors:
        if selector == "full":
            targets.extend("tests." + path.stem for path in sorted(Path("tests").glob("test_*.py")))
        elif selector in GROUPS:
            targets.extend(GROUPS[selector])
        else:
            # 未知组选项会在 load_target 的语法/存在性边界拒绝，不退回 discovery。
            targets.append(selector)
    # 保留首次出现顺序，并提前折叠被模块/类覆盖的子节点。不能把父模块和它的
    # 子方法一起交给 unittest，造成重复执行和重复获取有状态的类级夹具。
    targets = list(dict.fromkeys(targets))
    # 即使某个子节点会被父模块覆盖，也必须先验证用户显式写入的节点。否则
    # “有效模块 + 拼错方法”会被折叠成成功，违反错误参数必须先拒绝的边界。
    resolved = {target: load_target(target, parser) for target in targets}
    plan = [target for target in targets
            if not any(target.startswith(parent + ".") for parent in targets if parent != target)]
    collected = [(target, resolved[target]) for target in plan]
    if args.list:
        print("\n".join(plan))
        return 0
    # 同一真实 case 即使经多个模块别名到达也只执行一次；这不是失败重试入口。
    cases = {}
    for _, tests in collected:
        for case in tests:
            cases.setdefault(case.id(), case)
    native_requested = "windows-native" in args.selectors
    if native_requested and os.name != "nt":
        print("windows-native 必须在真实 Windows 运行；未执行原生必验节点。", file=sys.stderr)
        return 1
    required_native_ids = set()
    if native_requested:
        for target in GROUPS["windows-native"]:
            required_native_ids.update(case.id() for case in resolved[target])
    return run_cases(cases.values(), required_native_ids)


if __name__ == "__main__":
    raise SystemExit(main())
