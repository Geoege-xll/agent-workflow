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

# 原生库阶段与最终组合使用同一份节点清单；库阶段仅绑定实际交接的 Win32 类，
# 不引入 POSIX PTY、Git Bash 或 portable mock。新增消费者由本入口 owner 在交接
# 后补入最终组，缺失节点仍走 load_target 的真实导入/存在性拒绝，不动态忽略。
GROUPS["windows-native-libraries"] = (
    "tests.test_windows_runtime.WindowsFilesystemNativeTest",
    "tests.test_windows_fs_native.WindowsSafePrimitivesNativeTest",
    "tests.test_install_process_windows.NativeWindowsJobTest",
    "tests.test_windows_hook_command.NativeWindowsHookProtocolTest.test_cmd_actual_command_string_protocol",
    "tests.test_windows_hook_command.NativeWindowsHookProtocolTest.test_powershell_actual_command_string_protocol",
    "tests.test_windows_hook_command.NativeWindowsHookProtocolTest.test_supervised_payload_preserves_raw_streams_exit_and_authoritative_deadline",
    "tests.test_windows_hook_command.NativeWindowsHookProtocolTest.test_supervised_budget_is_end_to_end_and_discards_partial_output",
    "tests.test_windows_hook_command.NativeWindowsHookProtocolTest.test_terminating_outer_powershell_drains_supervised_descendants",
)
# CI42550963192 的同一 rename 参数错误只影响以下五个真实方法；保留已绿的
# 其余二十五方法原始证据，修复后仅补这五方法及其全部原生子场景。完整库组仍
# 供新环境或完整库验收显式选择；修复组不做动态筛选，不把失败节点退化为 skip。
GROUPS["windows-native-repair"] = (
    "tests.test_windows_runtime.WindowsFilesystemNativeTest.test_exhausted_or_context_closed_scandir_does_not_pin_directory",
    "tests.test_windows_runtime.WindowsFilesystemNativeTest.test_replacement_preserves_acl_protection_and_future_parent_inheritance",
    "tests.test_windows_runtime.WindowsFilesystemNativeTest.test_successful_backend_file_directory_rename_and_delete",
    "tests.test_windows_fs_native.WindowsSafePrimitivesNativeTest.test_consuming_regular_move_preserves_identity_and_excludes_existing_target",
    "tests.test_windows_fs_native.WindowsSafePrimitivesNativeTest.test_managed_skill_exact_create_read_move_delete_and_stale_refusal",
)
# 中央阶段仅绑定新增消费者及其直接依赖的条件删除原语。已有库与 rename 修复
# 证据继续按输入有效性复用，不因中央接入重复执行全库；本组仍要求每个方法及
# 原生子场景真实执行，输入未组合或节点未冻结时不得以缺失/skip 声称验收成功。
GROUPS["windows-native-central"] = (
    "tests.test_windows_fs_native.WindowsSafePrimitivesNativeTest.test_complete_regular_delete_preserves_acl_writer_replacement_and_deletes_owned",
    "tests.test_windows_fs_native.WindowsSafePrimitivesNativeTest.test_conditional_empty_directory_and_streaming_read_exclude_changes",
    "tests.test_windows_fs_native.WindowsSafePrimitivesNativeTest.test_independent_initial_private_gate_rejects_public_acl_before_core",
    "tests.test_central_project.WindowsCentralComposedNativeTest.test_source_install_detached_pin_helper_hooks_and_admission",
    "tests.test_central_project.WindowsCentralComposedNativeTest.test_project_junction_is_rejected_before_resolve_and_writes",
)
# 中央首轮 CI42559903683 仅此组合消费者在早期 VERSION 解析失败；保留四个
# 已绿方法的原始证据，修复后只补实际失败方法，不重复原库或以部分阶段冒充全验收。
GROUPS["windows-native-central-repair"] = (
    "tests.test_central_project.WindowsCentralComposedNativeTest.test_source_install_detached_pin_helper_hooks_and_admission",
)
# HTML 阶段单独验证真实 Node 消费者的固定源码/vendor 字节、junction 拒绝及
# Job 后代收尾；仅使用现有 Node >=20 和 stdlib，不引入 curses 或第二套清单。
# 方法名来自 renderer owner 的冻结接入合同；组合源码缺失仍须真实导入失败。
GROUPS["windows-native-renderer"] = (
    "tests.test_requirement_html.WindowsRequirementHtmlNativeTest.test_native_render_check_preserves_source_and_vendor_bytes",
    "tests.test_requirement_html.WindowsRequirementHtmlNativeTest.test_native_stage_and_home_junctions_are_rejected",
    "tests.test_requirement_html.WindowsRequirementHtmlNativeTest.test_native_node_timeout_terminates_descendants",
)
# CI42563956735 已将失败收敛到中央 scratch/installed ACL 投影和共享 Job wait
# 屏障。下列两组只补真实受影响节点：中央组合消费者复用既有登记，HTML 的已绿
# junction 方法及未受影响的底层/Job 方法保留原证据，不因共享后端修复全量重跑。
GROUPS["windows-native-central-acl-repair"] = GROUPS["windows-native-central-repair"] + (
    "tests.test_windows_fs_native.WindowsSafePrimitivesNativeTest.test_private_directory_chmod_is_idempotent_and_preserves_security",
)
GROUPS["windows-native-renderer-process-repair"] = (
    "tests.test_requirement_html.WindowsRequirementHtmlNativeTest.test_native_render_check_preserves_source_and_vendor_bytes",
    "tests.test_requirement_html.WindowsRequirementHtmlNativeTest.test_native_node_timeout_terminates_descendants",
    "tests.test_install_process_windows.NativeWindowsJobTest.test_wait_confirms_normal_descendant_handles",
    "tests.test_install_process_windows.NativeWindowsJobTest.test_timeout_drains_child_and_grandchild_before_recovery",
    "tests.test_install_process_windows.NativeWindowsJobTest.test_capture_cancel_file_drains_its_job",
)
# CI42566554380 已验证 renderer/process 五方法及私有目录 chmod；后续仅补中央
# 组合与精确 DACL 复制的新边界。组合消费者已执行 Full HTML，CI 需保留现有
# Node 前置；本阶段不重复已绿节点，临时 repair 名称留待最终稳定清单统一收敛。
GROUPS["windows-native-central-copy-repair"] = GROUPS["windows-native-central-repair"] + (
    "tests.test_windows_fs_native.WindowsSafePrimitivesNativeTest.test_exact_dacl_copy_is_idempotent_and_private_state_republishes",
)
# CI42568804698 的精确 DACL 复制已绿，中央消费者后续停在 Skill 发布见证。
# 此组只补实际 stage→目标父移动的原生见证与完整消费者，不重复已验 copy，
# 也不在验证入口放宽生产 guard；真实诊断和修复仍由中央 owner 冻结后组合。
GROUPS["windows-native-central-link-repair"] = GROUPS["windows-native-central-repair"] + (
    "tests.test_windows_fs_native.WindowsSafePrimitivesNativeTest.test_managed_skill_stage_publication_preserves_frozen_witness",
)
# 稳定 CLI 组件组只绑定已合入的六个原生方法，分别验证 Python/pwsh/cmd 入口、
# 字面 argv 与退出码、显式坏解释器拒绝及导入前隔离。它不启动 TUI/HTML，CI
# 必须独立使用 stdlib venv，不把 Node/curses 或未修复的中央消费者混入本轮取证。
GROUPS["windows-native-entry"] = (
    "tests.test_windows_native_entry.WindowsNativeEntryTest.test_python_help_version_and_empty_list",
    "tests.test_windows_native_entry.WindowsNativeEntryTest.test_powershell_legacy_help_version_and_empty_list",
    "tests.test_windows_native_entry.WindowsNativeEntryTest.test_cmd_help_version_and_empty_list",
    "tests.test_windows_native_entry.WindowsNativeEntryTest.test_shells_preserve_literal_arguments_and_exit_codes",
    "tests.test_windows_native_entry.WindowsNativeEntryTest.test_explicit_invalid_python_is_refused_without_fallback",
    "tests.test_windows_native_entry.WindowsNativeEntryTest.test_python_isolation_precedes_stdlib_imports",
)
# 首个直接 Python smoke 已在 CI42576076285 通过；后续仅补剩余五个入口方法。
# 从同一有序六方法清单派生，保留完整组件组且避免第二份手写名单漂移；本组同样
# 必须真实运行，不能因夹具隔离/清理修复而用 skip 或已绿 smoke 代替剩余验证。
GROUPS["windows-native-entry-shells"] = GROUPS["windows-native-entry"][1:]
GROUPS["windows-native"] = GROUPS["windows-native-libraries"]
# 任一原生阶段都必须在 Windows 真正执行所有选定节点。单独声明组名而复用
# GROUPS 值，防止 CI 或拒绝逻辑另养第二份方法清单，造成新增节点未纳入必验。
NATIVE_GROUPS = frozenset((
    "windows-native-libraries", "windows-native-repair", "windows-native-central",
    "windows-native-central-repair", "windows-native-renderer",
    "windows-native-central-acl-repair", "windows-native-renderer-process-repair",
    "windows-native-central-copy-repair", "windows-native-central-link-repair",
    "windows-native-entry", "windows-native-entry-shells", "windows-native",
))


def make_parser():
    parser = argparse.ArgumentParser(
        description="唯一 unittest 入口；无参数只显示帮助，全套必须显式选择 full。",
        epilog=("组：" + ", ".join((*GROUPS, "full")) + "。\n"
                "节点：tests.test_模块[.测试类[.test_方法]]；允许与组组合。\n"
                "示例：bash scripts/test_workflow.sh --list ci\n"
                "      bash scripts/test_workflow.sh service tests.test_runtime_store\n"
                "      python -I -B -X utf8 scripts/test_workflow.py windows-native\n"
                "原生库阶段：windows-native-libraries；完整中央/TUI 组合验收仍待接入。\n"
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
