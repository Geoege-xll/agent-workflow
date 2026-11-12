#!/usr/bin/env bash
# 唯一 unittest 入口：使用源包物理根和已有解释器选择器，不下载依赖或改变宿主配置。
set -euo pipefail
export PYTHONDONTWRITEBYTECODE=1
SCRIPT_DIR="$(CDPATH= cd -P -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
PACK_DIR="$(CDPATH= cd -P -- "${SCRIPT_DIR}/.." && pwd -P)"
cd -- "${PACK_DIR}"
# exec 使测试失败/中断直接成为入口的退出状态；不加重试，也不吞掉 unittest 输出。
exec bash "${PACK_DIR}/lib/python_runtime.sh" -B -X utf8 - "$@" <<'PY'
import argparse
import importlib
from pathlib import Path
import re
import shutil
import sys
import unittest


def modules(*names):
    return tuple("tests.test_" + name for name in names)


# 分组只声明真实模块/类/方法，不导入 TestCase 作为夹具。旧入口的模块范围保持不变；
# service/tui 与 pty 按真实节点拆开，因此普通单元验证不会隐式启动伪终端。
GROUPS = {
    # 两个当前产品各自声明真实模块，不混入旧安装器/TUI/PTY或另一产品生命周期。
    # records 只选择插件实际使用的记录/发布/CLI/临时目录合同；历史三宿主安装
    # 夹具仍留在 full，不能借此宣称已经修复或通过旧安装器的完整兼容验收。
    "plugin": modules("plugin_delivery", "plugin_resources", "plugin_workflow_contract", "plugin_maintenance_contract",
                      "continuous_intake_capabilities", "agent_continuation", "dispatch_admission", "task_settlement",
                      "task_graph", "scheduler_boundaries") + tuple(
                          "tests.test_task_graph_records." + name for name in (
                              "RecordUpdateTest", "RecordPublicationTest", "RecordCliTest", "ScratchWorkspaceTest")),
    "native-config": modules("native_config", "native_inventory", "native_config_codecs", "native_config_commands",
                             "native_config_server", "native_config_mcp", "native_config_packaging", "plugin_console",
                             "plugin_config_launcher", "config_distribution"),
    "codex": modules("codex_workflow", "shared_memory_contract"),
    "claude": modules("claude_workflow", "claude_instructions", "shared_memory_contract"),
    "antigravity": modules("antigravity_workflow"),
    "prototype": modules("document_safety", "prototype_adapters", "prototype_fingerprints", "prototype_workspace"),
    "packaging": modules("plugin_delivery", "native_config_packaging", "candidate_delivery",
                         "plugin_config_launcher", "config_distribution"),
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
# legacy CI 保留2.x CLI/pin/中央软链和真实PTY的显式维护范围，
# 不代表两个当前产品的3.0全套验收；当前产品请显式选plugin或native-config。
GROUPS["legacy-ci"] = (
    modules("validation_runner")
    + ("tests.test_workflow_manager.CentralCliIntegrationTest",)
    + modules("central_project", "runtime_state", "central_runtime", "runtime_lifecycle", "native_agents", "install_cli")
    + ("tests.test_manager_tui.TuiTest.test_platform_reset_is_independent_and_consumes_only_captured_keys",
       "tests.test_manager_tui.TuiTest.test_runtime_actions_use_captured_context_and_modal_focus")
    + ("tests.test_unified_host_workflow.UnifiedSetupContractTest.test_all_hosts_generate_core_skills_from_one_shared_source",)
    + GROUPS["pty"]
)
# 保留现有显式调用的兼容别名；自动 PR/push 门禁只消费 current。
GROUPS["ci"] = GROUPS["legacy-ci"]
GROUPS["current"] = (modules("validation_runner", "candidate_delivery") + GROUPS["plugin"]
                     + GROUPS["native-config"] + GROUPS["prototype"])


def make_parser():
    parser = argparse.ArgumentParser(
        description="唯一 unittest 入口；无参数只显示帮助；full 是混合历史全仓显式发现，不代表3.0全套。",
        epilog=("当前产品组：plugin、native-config；两者均不隐式运行PTY。\n"
                "current：两个产品、保留原型链、验证入口和候选交付合同；是当前PR/push门禁。\n"
                "legacy/通用预置组：" + ", ".join(name for name in GROUPS if name not in {"plugin", "native-config", "current"}) + "。\n"
                "ci 是 legacy-ci 的兼容别名，仅维护2.x；不代表当前产品门禁。\n"
                "full：显式发现全部现有test_模块，包含尚未退役的2.x夹具。\n"
                "节点：tests.test_模块[.测试类[.test_方法]]；允许与组组合。\n"
                "示例：bash scripts/test_workflow.sh --list plugin native-config\n"
                "      bash scripts/test_workflow.sh plugin tests.test_task_graph_init\n"
                "依赖：Python >= 3.11；native-config/current 的网页JS需要 Node；PTY 需要 POSIX。"),
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


def main():
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
    # 网页 JS 是当前产品的真实消费者。显式选择它却没有 Node 时必须失败，
    # 避免 unittest 的历史 skip 装饰器让 current 门禁在缺依赖时显示绿色。
    if (any(name.startswith("tests.test_plugin_console.ConsoleJavascriptTest.") for name in cases)
            and shutil.which("node") is None):
        parser.error("原生配置网页 JS 验证需要已有 Node；未执行测试")
    result = unittest.TextTestRunner(verbosity=2).run(unittest.TestSuite(cases.values()))
    return 0 if result.wasSuccessful() else 1


raise SystemExit(main())
PY
