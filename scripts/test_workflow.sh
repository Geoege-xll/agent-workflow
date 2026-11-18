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


# 只登记 3.x 的现行模块。一个模块可同时服务于产品和交付验证；组合选择器时，
# 下方统一按模块和真实用例去重，避免重复执行写入临时项目的集成测试。
GROUPS = {
    "plugin": modules(
        "plugin_delivery", "plugin_resources", "selected_skills", "plugin_workflow_contract",
        "plugin_maintenance_contract", "continuous_intake_capabilities", "agent_continuation",
        "dispatch_admission", "task_settlement", "task_graph", "task_graph_init", "task_graph_records",
        "scheduler_boundaries", "foundation_qa", "qa_handoff", "plugin_worktree_delivery",
        "worktree_delivery", "design_standards_lifecycle", "production_only_revisions", "light_ui_copy",
        "context_read", "profile_context", "project_id_initialization", "project_discovery",
        "bootstrap_routing", "astra_instruction_adaptation", "runtime_and_discovery",
        "workflow_authorities", "rule_boundary_contracts", "shared_memory_contract", "platform_fs", "native_usage",
    ),
    "native-config": modules(
        "native_config", "native_preparation", "native_preferences", "native_inventory",
        "native_config_codecs", "native_config_commands", "native_config_server", "browser_sessions",
        "native_config_mcp", "native_config_packaging", "plugin_console", "plugin_config_launcher",
        "config_distribution",
    ),
    "prototype": modules(
        "document_safety", "prototype_adapters", "prototype_fingerprints", "prototype_workspace",
        "prototype_workspace_runtime", "prototype_feedback", "prototype_review", "prototype_live",
        "prototype_server", "prototype_file_entry",
    ),
    "plans": modules("plan_and_shallow_docs"),
    "packaging": modules(
        "plugin_delivery", "native_config_packaging", "candidate_delivery", "plugin_config_launcher",
        "config_distribution", "plugin_source_publication", "remote_install_smoke",
    ),
}
# current 是 CI 的显式维护清单。full 独立发现仓库测试，可以发现已建立但漏登记的模块。
# 入口自测对照两者，使新增测试必须归到对应产品组才能通过 CI。
GROUPS["current"] = modules("validation_runner") + tuple(target for group in GROUPS.values() for target in group)


def make_parser():
    parser = argparse.ArgumentParser(
        description="运行 3.x 的 unittest 验证，无参数时只显示帮助。",
        epilog=("产品分组：plugin、native-config、prototype、plans、packaging。\n"
                "current：运行上述各组与验证入口自测，用于 PR/push 门禁。\n"
                "full：发现并运行 tests 目录下全部 test_*.py 模块。\n"
                "节点：tests.test_模块[.测试类[.test_方法]]，允许与组组合。\n"
                "示例：bash scripts/test_workflow.sh --list plugin native-config\n"
                "      bash scripts/test_workflow.sh tests.test_task_graph_init\n"
                "依赖：Python >= 3.11，原生配置网页 JS 验证需要 Node。"),
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
