import argparse
import importlib
import json
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
# PTY、离线归档及 Ruby Formula 消费者。HTML 仅验证暂停合同，历史引擎不收集；
# 其它消费者的既有 Node 前置仍由 CI 保留，不因暂停 HTML 擅自删除。
GROUPS["ci"] = (
    modules("validation_runner")
    + ("tests.test_workflow_manager.CentralCliIntegrationTest",)
    + modules("central_project", "runtime_state", "central_runtime", "runtime_lifecycle", "native_agents", "install_cli")
    # 后台保存预览必须在校验阻塞时保持真实 App 可响应并保留草稿；仅纳入已冻结
    # 的精确消费者，不因新增回归把整个 TUI 模块或现有 PTY 分支重复执行。
    + ("tests.test_manager_tui.TuiTest.test_platform_reset_is_independent_and_consumes_only_captured_keys",
       "tests.test_manager_tui.TuiTest.test_runtime_actions_use_captured_context_and_modal_focus",
       "tests.test_manager_tui.TuiTest.test_save_preview_blocked_validation_keeps_ui_responsive_and_drafts")
    + ("tests.test_unified_host_workflow.UnifiedSetupContractTest.test_all_hosts_generate_core_skills_from_one_shared_source",)
    + ("tests.test_requirement_html.RequirementHtmlSuspendedTest",)
    + GROUPS["pty"] + GROUPS["packaging"]
)

# 稳定原生组件的唯一登记：目标、依赖都归本入口所有；GROUPS、最终聚合与 CI
# matrix 仅从这里派生。历史 repair/entry-shells 别名已完成使命，不参与现行门禁；
# 原始 CI 日志保留原名，不通过修改旧证据把阶段成功重标为最终验收。
NATIVE_COMPONENTS = {
    "windows-native-libraries": {
        "targets": (
            "tests.test_windows_runtime.WindowsFilesystemNativeTest",
            "tests.test_windows_fs_native.WindowsSafePrimitivesNativeTest",
            "tests.test_install_process_windows.NativeWindowsJobTest",
            # 只收集当前 cmd/PowerShell 生产协议；旧 Git Bash 和自包含 Hook
            # 夹具不是原生支持合同，不可把含这些方法的整类静默升级为必跑。
            "tests.test_windows_hook_command.NativeWindowsHookProtocolTest.test_cmd_actual_command_string_protocol",
            "tests.test_windows_hook_command.NativeWindowsHookProtocolTest.test_powershell_actual_command_string_protocol",
            "tests.test_windows_hook_command.NativeWindowsHookProtocolTest.test_supervised_payload_preserves_raw_streams_exit_and_authoritative_deadline",
            "tests.test_windows_hook_command.NativeWindowsHookProtocolTest.test_supervised_budget_is_end_to_end_and_discards_partial_output",
            "tests.test_windows_hook_command.NativeWindowsHookProtocolTest.test_terminating_outer_powershell_drains_supervised_descendants",
        ),
        "node_required": False, "curses_required": False,
    },
    "windows-native-entry": {
        "targets": (
            "tests.test_windows_native_entry.WindowsNativeEntryTest.test_python_help_version_and_empty_list",
            "tests.test_windows_native_entry.WindowsNativeEntryTest.test_powershell_legacy_help_version_and_empty_list",
            "tests.test_windows_native_entry.WindowsNativeEntryTest.test_cmd_help_version_and_empty_list",
            "tests.test_windows_native_entry.WindowsNativeEntryTest.test_shells_preserve_literal_arguments_and_exit_codes",
            "tests.test_windows_native_entry.WindowsNativeEntryTest.test_explicit_invalid_python_is_refused_without_fallback",
            "tests.test_windows_native_entry.WindowsNativeEntryTest.test_python_isolation_precedes_stdlib_imports",
        ),
        "node_required": False, "curses_required": False,
    },
    "windows-native-central": {
        "targets": (
            "tests.test_central_project.WindowsCentralComposedNativeTest.test_source_install_detached_pin_helper_hooks_and_admission",
        ),
        # 保留已冻结中央消费者的 Node 前置；HTML 已暂停，不把旧 renderer
        # 节点放回聚合，也不在收敛清单时擅自改变中央运行时契约。
        "node_required": True, "curses_required": False,
    },
    "windows-native-central-boundaries": {
        "targets": (
            "tests.test_central_project.WindowsCentralComposedNativeTest.test_project_junction_is_rejected_before_resolve_and_writes",
            "tests.test_runtime_store.RuntimeStoreTest.test_explicit_core_reader_is_scoped_fresh_and_rejects_wrong_core_or_member",
            "tests.test_runtime_store.RuntimeStoreTest.test_recursive_snapshot_rejects_unknown_members_and_directory_exchange",
        ),
        "node_required": False, "curses_required": False,
    },
    "windows-native-conpty": {
        "targets": (
            "tests.test_windows_conpty_transport.NativeConPTYTransportTest.test_native_utf8_input_and_vt_output",
            "tests.test_windows_conpty_transport.NativeConPTYTransportTest.test_native_resize_reports_console_dimensions",
            "tests.test_windows_conpty_transport.NativeConPTYTransportTest.test_native_ctrl_c_targets_owned_console",
            "tests.test_windows_conpty_transport.NativeConPTYTransportTest.test_native_large_output_and_exit_codes",
            "tests.test_windows_conpty_transport.NativeConPTYTransportTest.test_native_timeout_and_cancel_quiesce_job",
            "tests.test_windows_conpty_transport.NativeConPTYTransportTest.test_native_console_modes_restore",
            "tests.test_windows_conpty_transport.NativeConPTYTransportTest.test_native_start_failure_releases_owned_resources",
            "tests.test_windows_conpty_transport.NativeConPTYTransportTest.test_native_interpreter_and_standard_handle_diagnostics",
        ),
        "node_required": False, "curses_required": False,
    },
    "windows-native-tui": {
        "targets": (
            "tests.test_windows_native_integration.WindowsNativeTUIIntegrationTest.test_native_tui_project_preferences_lifecycle_and_focus",
            "tests.test_windows_native_integration.WindowsNativeTUIIntegrationTest.test_native_tui_global_reset_and_monochrome",
            "tests.test_windows_native_integration.WindowsNativeTUIIntegrationTest.test_native_tui_unicode_resize_and_interrupt_restores_modes",
        ),
        "node_required": False, "curses_required": True,
    },
    "windows-native-tui-diagnostics": {
        "targets": (
            "tests.test_windows_native_integration.WindowsAcceptanceScriptNativeTest.test_native_acceptance_identity_preserves_legacy_quotes_and_exit_codes",
            "tests.test_windows_native_integration.WindowsAcceptanceScriptNativeTest.test_native_acceptance_git_resolution_preserves_path_priority",
            "tests.test_windows_native_integration.NativeConsoleObserverNativeTest.test_native_console_cursor_access_diagnostics",
        ),
        # Legacy 方法真实调用身份函数并导入 curses/_curses；不启动 TUI 也需要
        # 已锁 windows-curses，缺依赖应失败，不以跳过身份边界换取绿色。
        "node_required": False, "curses_required": True,
    },
    "windows-native-intake": {
        # 四模块的实际 CLI 已按 os.name 选择隔离 Windows bootstrap，且没有
        # POSIX 专属或 skip 节点；它们验证调度/续用/证据分层合同，不冒充宿主
        # 消息送达。settlement 已由 owner 冻结，同样使用隔离 Windows 入口、
        # 无 skip；保留 installed pin 的真实 CAS/准入释放消费者，数量由收集决定。
        "targets": modules("dispatch_admission", "agent_continuation", "continuous_intake_capabilities", "task_settlement"),
        "node_required": False, "curses_required": False,
    },
}
GROUPS.update((name, component["targets"]) for name, component in NATIVE_COMPONENTS.items())
GROUPS["windows-native"] = tuple(target for component in NATIVE_COMPONENTS.values() for target in component["targets"])
NATIVE_GROUPS = frozenset((*NATIVE_COMPONENTS, "windows-native"))
# 新功能在三平台执行同一已冻结模块；这里只复用登记，不再维护第二套模块名单。
GROUPS["ci"] += NATIVE_COMPONENTS["windows-native-intake"]["targets"]


def make_parser():
    parser = argparse.ArgumentParser(
        description="唯一 unittest 入口；无参数只显示帮助，全套必须显式选择 full。",
        epilog=("组：" + ", ".join((*GROUPS, "full")) + "。\n"
                "节点：tests.test_模块[.测试类[.test_方法]]；允许与组组合。\n"
                "示例：bash scripts/test_workflow.sh --list ci\n"
                "      bash scripts/test_workflow.sh service tests.test_runtime_store\n"
                "      python -I -B -X utf8 scripts/test_workflow.py windows-native\n"
                "Windows 完整验收：windows-native；--matrix windows-native 只校验并输出 CI 组件矩阵。\n"
                "原生库/CLI/ConPTY 使用 stdlib；TUI/脚本身份需要 requirements-windows.txt 锁定依赖。\n"
                "依赖：Python >= 3.11；HTML 生成已暂停；ci 保留 Node 前置，packaging/ci 需要 Ruby；PTY 需要 POSIX。"),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    display = parser.add_mutually_exclusive_group()
    display.add_argument("--list", action="store_true", help="校验后逐行显示实际测试目标，不运行测试")
    display.add_argument("--matrix", action="store_true", help="只收集 windows-native 完整清单，输出含实际方法数和依赖的 JSON 矩阵")
    parser.add_argument("selectors", nargs="*", metavar="组或节点")
    return parser


def flatten(suite):
    for item in suite:
        if isinstance(item, unittest.TestSuite):
            yield from flatten(item)
        else:
            yield item


def native_matrix(resolved, parser):
    """发布同一登记的真实组件分区；缺失、空集合或跨组重复都不能成为 CI 计划。"""
    include, registered_ids = [], set()
    if not NATIVE_COMPONENTS:
        parser.error("原生组件矩阵不能为空")
    for name, component in NATIVE_COMPONENTS.items():
        identifiers = {case.id() for target in component["targets"] for case in resolved[target]}
        if not identifiers or registered_ids.intersection(identifiers):
            parser.error("原生组件为空或测试跨组件重复：" + name)
        if any(type(component[key]) is not bool for key in ("node_required", "curses_required")):
            parser.error("原生组件依赖必须是明确布尔值：" + name)
        registered_ids.update(identifiers)
        include.append({"group": name, "methods": len(identifiers),
                        "node_required": component["node_required"], "curses_required": component["curses_required"]})
    # 拒绝未来调用方另改聚合而漏进矩阵的漂移；客户端完整组与 Server 组件并集
    # 必须是同一集合，不能只有各组件非空就把未登记的新消费者遗漏为绿色。
    if registered_ids != {case.id() for cases in resolved.values() for case in cases}:
        parser.error("原生聚合与组件矩阵的实际测试集合不一致")
    return {"include": include}


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
        self.active_test_id = test.id()

    def stopTest(self, test):
        self.active_test_id = None
        super().stopTest(test)

    def addSkip(self, test, reason):
        super().addSkip(test, reason)
        # unittest 的 subTest skip 只登记子场景 id，父方法仍然算已启动并且整体
        # wasSuccessful() 为真。使用 start/stop 生命周期记录当前父方法，不依赖
        # 私有 _SubTest 类型；任一原生必验子场景未执行，都使所属方法不能获验收。
        self.skipped_ids.add(self.active_test_id or test.id())

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.started_ids = set()
        self.skipped_ids = set()
        self.active_test_id = None


def run_cases(cases, required_native_ids=()):
    result = unittest.TextTestRunner(verbosity=2, resultclass=ExecutionResult).run(unittest.TestSuite(cases))
    # unittest 把全 skip 当成功，但原生必验集合必须真正执行。逐个 required id 核对，
    # 既拒绝全 skip，也拒绝自定义 suite 未执行节点；失败用原退出码 1 向上传播。
    executed = result.started_ids - result.skipped_ids
    if required_native_ids and not set(required_native_ids).issubset(executed):
        print("原生必验节点未实际执行或被 skip；不能作为 Windows 验收成功。", file=sys.stderr)
        return 1
    return 0 if result.wasSuccessful() else 1


def main():
    os.chdir(PACK)
    sys.path.insert(0, str(PACK))
    parser = make_parser()
    args = parser.parse_args()
    if args.matrix and args.selectors != ["windows-native"]:
        parser.error("--matrix 必须且只能选择完整 windows-native；不能把局部分组当作完整发布门禁")
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
    if args.matrix:
        # 收集遵循与 --list/执行相同的真实导入和节点存在性边界；不会运行 TestCase
        # 或把静态预期计数冒充方法数。单行 JSON 可直接进入 GITHUB_OUTPUT，不能带
        # 日志或用户输入；实际原生成功仍由随后逐组件执行和汇总确认。
        print(json.dumps(native_matrix(resolved, parser), separators=(",", ":")))
        return 0
    if args.list:
        print("\n".join(plan))
        return 0
    # 同一真实 case 即使经多个模块别名到达也只执行一次；这不是失败重试入口。
    cases = {}
    for _, tests in collected:
        for case in tests:
            cases.setdefault(case.id(), case)
    native_requested = NATIVE_GROUPS.intersection(args.selectors)
    if native_requested and os.name != "nt":
        print("原生 Windows 组必须在真实 Windows 运行；未执行原生必验节点。", file=sys.stderr)
        return 1
    required_native_ids = set()
    for group in native_requested:
        for target in GROUPS[group]:
            required_native_ids.update(case.id() for case in resolved[target])
    return run_cases(cases.values(), required_native_ids)


if __name__ == "__main__":
    raise SystemExit(main())
