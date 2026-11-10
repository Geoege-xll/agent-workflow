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
            # AGY 的发布/补偿/ACL 漂移消费者为普通 Windows fixture；独立
            # owner-only 提升负控不继承此 TestCase，必须在下方单独组件登记。
            "tests.test_antigravity_windows_native.AntigravityStageWindowsNativeTest",
            # 只收集当前 cmd/PowerShell 生产协议；旧 Git Bash 和自包含 Hook
            # 夹具不是原生支持合同，不可把含这些方法的整类静默升级为必跑。
            "tests.test_windows_hook_command.NativeWindowsHookProtocolTest.test_cmd_actual_command_string_protocol",
            "tests.test_windows_hook_command.NativeWindowsHookProtocolTest.test_powershell_actual_command_string_protocol",
            "tests.test_windows_hook_command.NativeWindowsHookProtocolTest.test_supervised_payload_preserves_raw_streams_exit_and_authoritative_deadline",
            "tests.test_windows_hook_command.NativeWindowsHookProtocolTest.test_supervised_budget_is_end_to_end_and_discards_partial_output",
            "tests.test_windows_hook_command.NativeWindowsHookProtocolTest.test_terminating_outer_powershell_drains_supervised_descendants",
        ),
        # 普通与原生 CI 共同消费的操作租约负控只在这里声明一次；原生分组
        # 自动包含，普通 ci 也由这个字段派生，不另抄 Store/Records 方法清单。
        "portable_ci_targets": (
            "tests.test_runtime_store.RuntimeStoreTest.test_operation_unifies_load_batch_and_builtin_catalog_then_expires",
            "tests.test_runtime_store.RuntimeStoreTest.test_operation_checkpoint_rejects_unread_member_and_ancestor_drift",
            "tests.test_runtime_store.RuntimeStoreTest.test_operation_isolates_roots_pins_threads_processes_and_module_aliases",
            "tests.test_runtime_store.RuntimeStoreTest.test_operation_checkpoint_keeps_manifest_version_mode_and_member_guards",
            "tests.test_task_graph_records.RecordPublicationTest.test_operation_finish_rejects_source_drift_before_any_temporary_or_publish",
            "tests.test_task_graph_records.RecordPublicationTest.test_operation_finish_precedes_last_fresh_cas_and_settlement_sources",
            "tests.test_runtime_store.RuntimeStoreTest.test_windows_literal_roots_do_not_alias_operation_or_core_locators",
            # 同一预算消费者同时验证便携 CI 与 Windows 实际文件链；共享登记
            # 避免将含原生/提升类的整个 AGY 模块塞进普通 CI 或重复运行两方法。
            "tests.test_antigravity_windows_native.AntigravityFileBudgetTest.test_large_root_publication_restore_and_cleanup_keep_original_eight_mib_boundary",
            "tests.test_antigravity_windows_native.AntigravityFileBudgetTest.test_merged_overflow_controlled_docs_and_codex_caps_reject_before_stage_or_backup",
            # 引用解析与安全同步只需 Python/localFS；精确选择合法换行及损坏
            # 行负控，避免把同模块中其它 shell 宿主安装夹具扩成原生必跑。
            "tests.test_astra_instruction_adaptation.ProgressiveContractTest.test_workflow_references_accept_lf_crlf_mixed_and_eof",
            "tests.test_astra_instruction_adaptation.ProgressiveContractTest.test_workflow_reference_line_damage_is_rejected_before_reading",
            "tests.test_astra_instruction_adaptation.ProgressiveContractTest.test_shared_skill_sync_preserves_source_line_endings",
            "tests.test_bootstrap_routing.BootstrapReferenceTest.test_real_entries_accept_lf_crlf_mixed_and_eof",
            "tests.test_bootstrap_routing.BootstrapReferenceTest.test_bootstrap_reference_line_damage_is_rejected_before_reading",
            # 公开异常与原 cause 的合同沿实际平台 facade 关闭目录 fd；只注入
            # 发布边界故障，不以此替代真实 NTFS 权限/发布验收或扩选 shell 夹具。
            "tests.test_project_id_initialization.ProjectIdNativePublisherContractTest.test_native_write_failure_preserves_public_initialization_error_and_exact_cause",
        ),
        "qualification": "ordinary",
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
        "qualification": "ordinary",
        "node_required": False, "curses_required": False,
    },
    "windows-native-central": {
        "targets": (
            "tests.test_central_project.WindowsCentralComposedNativeTest.test_source_install_detached_pin_helper_hooks_and_admission",
        ),
        # 保留已冻结中央消费者的 Node 前置；HTML 已暂停，不把旧 renderer
        # 节点放回聚合，也不在收敛清单时擅自改变中央运行时契约。
        "qualification": "ordinary",
        "node_required": True, "curses_required": False,
    },
    "windows-native-central-boundaries": {
        "targets": (
            "tests.test_central_project.WindowsCentralComposedNativeTest.test_project_junction_is_rejected_before_resolve_and_writes",
            # 创建/封口故障与 ready-save 顺序使用独立普通 Windows fixture；
            # central_project 在便携 CI 已整模块覆盖，不再补精确子方法选择。
            "tests.test_central_project.WindowsStageConsumerNativeTest",
            "tests.test_runtime_store.RuntimeStoreTest.test_explicit_core_reader_is_scoped_fresh_and_rejects_wrong_core_or_member",
            "tests.test_runtime_store.RuntimeStoreTest.test_recursive_snapshot_rejects_unknown_members_and_directory_exchange",
            # central_project 已整体进入普通 ci；这里只补原生侧，不再重复其
            # 精确普通 CI 登记。词法负控验证实际方法，不冒称 NTFS 实体证明。
            "tests.test_central_project.CentralProjectTest.test_fixed_graph_runner_validates_once_and_rejects_changed_sources_before_cas",
            "tests.test_central_project.CentralProjectTest.test_fixed_graph_runner_keeps_old_pin_helper_path_and_target_provenance",
            "tests.test_central_project.CentralProjectTest.test_fixed_runner_windows_literal_root_guards_are_case_sensitive",
            # 保存阶段的纯读取准备/尾验负控复用原中央 fixture；原生侧精确登记，
            # 普通 ci 继续由 central_project 整模块覆盖，不增第二次执行选择。
            "tests.test_central_project.CentralProjectTest.test_model_commit_read_preparation_keeps_callback_boundary_and_single_scan",
            "tests.test_central_project.CentralProjectTest.test_model_commit_read_preparation_rejects_finish_and_mutable_drift_before_write",
            # 项目/中央纯预览共享读取证明及退出漂移拒绝同样属于 ordinary 边界；
            # 沿用中央 Skill 软链 fixture，无 Node/curses，普通 ci 仍由整模块覆盖。
            "tests.test_central_project.CentralProjectTest.test_project_previews_share_read_operation_and_preserve_source_inspection",
            "tests.test_central_project.CentralProjectTest.test_central_preview_separates_pins_and_withholds_plan_on_exit_drift",
        ),
        "qualification": "ordinary",
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
        "qualification": "ordinary",
        "node_required": False, "curses_required": False,
    },
    "windows-native-tui": {
        "targets": (
            "tests.test_windows_native_integration.WindowsNativeTUIIntegrationTest.test_native_tui_project_preferences_lifecycle_and_focus",
            "tests.test_windows_native_integration.WindowsNativeTUIIntegrationTest.test_native_tui_global_reset_and_monochrome",
            "tests.test_windows_native_integration.WindowsNativeTUIIntegrationTest.test_native_tui_unicode_resize_and_interrupt_restores_modes",
        ),
        "qualification": "ordinary",
        "node_required": False, "curses_required": True,
    },
    "windows-native-tui-diagnostics": {
        "targets": (
            "tests.test_windows_native_integration.WindowsAcceptanceScriptNativeTest.test_native_acceptance_identity_preserves_legacy_quotes_and_exit_codes",
            "tests.test_windows_native_integration.WindowsAcceptanceScriptNativeTest.test_native_acceptance_git_resolution_preserves_path_priority",
            "tests.test_windows_native_integration.NativeConsoleObserverNativeTest.test_native_console_cursor_access_diagnostics",
            "tests.test_validation_runner.WindowsAcceptanceScopeNativeTest.test_native_script_consumes_desktop_description_and_rejects_full_scope",
        ),
        # Legacy 方法真实调用身份函数并导入 curses/_curses；不启动 TUI 也需要
        # 已锁 windows-curses，缺依赖应失败，不以跳过身份边界换取绿色。
        "qualification": "ordinary",
        "node_required": False, "curses_required": True,
    },
    "windows-native-intake": {
        # 四模块的实际 CLI 已按 os.name 选择隔离 Windows bootstrap，且没有
        # POSIX 专属或 skip 节点；它们验证调度/续用/证据分层合同，不冒充宿主
        # 消息送达。settlement 已由 owner 冻结，同样使用隔离 Windows 入口、
        # 无 skip；保留 installed pin 的真实 CAS/准入释放消费者，数量由收集决定。
        "targets": (),
        "portable_ci_targets": modules("dispatch_admission", "agent_continuation", "continuous_intake_capabilities", "task_settlement"),
        "qualification": "ordinary",
        "node_required": False, "curses_required": False,
    },
    "windows-native-case-sensitive": {
        # 提升只用于本例新建空 NTFS 父目录的 fsutil 标志准备；不写生产目录、
        # 不引入 WSL/软链/预置根。缺权限或实际大小写负控失败必须 FAIL，无 skip。
        "targets": (
            "tests.test_runtime_store.WindowsCaseSensitiveCoreNativeTest.test_case_sensitive_ntfs_roots_get_independent_readers_and_guards",
            "tests.test_runtime_store.WindowsCaseSensitiveCoreNativeTest.test_case_sensitive_ntfs_fixed_runner_rejects_cross_root_before_cas",
        ),
        "qualification": "elevated",
        "node_required": False, "curses_required": False,
    },
    "windows-native-security-ownership": {
        # Server 管理员夹具需真实 BA→当前合法 SID 的 owner-only 差异；可信
        # System32 whoami/icacls 与既有 PS7 Get-Acl 仅操作本例临时文件。
        # 无差异/能力不足必须 FAIL，不改产品权限、不要求普通桌面用户提权；
        # 独立于 NTFS flag 专项，desktop 仍由同一资格规则明确排除此组件。
        "targets": (
            "tests.test_antigravity_windows_native.AntigravityOwnerSecurityWindowsElevatedTest.test_owner_only_drift_preserves_published_and_backup_nodes_during_rollback_and_cleanup",
        ),
        "qualification": "elevated",
        "node_required": False, "curses_required": False,
    },
}


def component_targets(component):
    """同一组件合并专属和共享 CI 节点；调用方不得自行补一份平行方法名单。"""
    return component["targets"] + component.get("portable_ci_targets", ())


GROUPS.update((name, component_targets(component)) for name, component in NATIVE_COMPONENTS.items())
GROUPS["windows-native"] = tuple(target for component in NATIVE_COMPONENTS.values() for target in component_targets(component))
# 桌面范围是显式资格选择，不从 token/权限动态降级；缺失或未知资格在每次
# 原生收集/执行前拒绝。只派生目标，不养第二套方法名单；所选仍逐项 zeroSkip。
NATIVE_SCOPES = frozenset(("windows-native", "windows-native-desktop"))
GROUPS["windows-native-desktop"] = tuple(
    target for component in NATIVE_COMPONENTS.values() if component.get("qualification") == "ordinary"
    for target in component_targets(component)
)
NATIVE_GROUPS = frozenset((*NATIVE_COMPONENTS, *NATIVE_SCOPES))
# 共享操作/续用节点复用同一登记；提升专项没有此字段，不进入 POSIX ci。
GROUPS["ci"] += tuple(target for component in NATIVE_COMPONENTS.values() for target in component.get("portable_ci_targets", ()))
# RolePrefs 的计数及保存尾阶段消费者使用既有 pty/termios/curses 与 POSIX sourcebuilder，
# 只补精准普通 CI；它不是普通 Windows 或提升 NTFS 的执行资格。
GROUPS["ci"] += (
    "tests.test_role_preferences.RolePreferencesTest.test_preview_proves_each_pin_once_and_never_retains_live_reader",
    "tests.test_role_preferences.RolePreferencesTest.test_native_global_unchanged_projects_batch_final_read_phase",
    "tests.test_role_preferences.RolePreferencesTest.test_native_global_unchanged_projects_recheck_original_observation_and_compensate",
)


def make_parser():
    parser = argparse.ArgumentParser(
        description="唯一 unittest 入口；无参数只显示帮助，全套必须显式选择 full。",
        epilog=("组：" + ", ".join((*GROUPS, "full")) + "。\n"
                "节点：tests.test_模块[.测试类[.test_方法]]；允许与组组合。\n"
                "示例：bash scripts/test_workflow.sh --list ci\n"
                "      bash scripts/test_workflow.sh service tests.test_runtime_store\n"
                "      python -I -B -X utf8 scripts/test_workflow.py windows-native\n"
                "Windows 完整验收：windows-native；--matrix windows-native 只校验并输出 CI 组件矩阵。\n"
                "普通用户范围：windows-native-desktop；--describe 输出同一登记派生的所选与排除事实。\n"
                "原生库/CLI/ConPTY 使用 stdlib；TUI/脚本身份需要 requirements-windows.txt 锁定依赖。\n"
                "依赖：Python >= 3.11；HTML 生成已暂停；ci 保留 Node 前置，packaging/ci 需要 Ruby；PTY 需要 POSIX。"),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    display = parser.add_mutually_exclusive_group()
    display.add_argument("--list", action="store_true", help="校验后逐行显示实际测试目标，不运行测试")
    display.add_argument("--matrix", action="store_true", help="只收集 windows-native 完整清单，输出含实际方法数和依赖的 JSON 矩阵")
    display.add_argument("--describe", action="store_true", help="只收集完整原生或普通桌面范围，输出所选/排除的 JSON 描述")
    parser.add_argument("selectors", nargs="*", metavar="组或节点")
    return parser


def flatten(suite):
    for item in suite:
        if isinstance(item, unittest.TestSuite):
            yield from flatten(item)
        else:
            yield item


def validate_native_components(parser):
    """资格是显式登记合同，不能把遗漏或拼错默认为普通用户可用。"""
    if not NATIVE_COMPONENTS:
        parser.error("原生组件矩阵不能为空")
    for name, component in NATIVE_COMPONENTS.items():
        if component.get("qualification") not in ("ordinary", "elevated"):
            parser.error("原生组件缺少有效资格：" + name)
        if component["qualification"] == "elevated" and component.get("portable_ci_targets"):
            parser.error("提升专项不能进入普通 CI 共享节点：" + name)
        if any(type(component.get(key)) is not bool for key in ("node_required", "curses_required")):
            parser.error("原生组件依赖必须是明确布尔值：" + name)


def native_partition(resolved, parser):
    """完整收集一次，再供矩阵和范围描述共享；分区必须非空、互斥且覆盖全部 ID。"""
    validate_native_components(parser)
    rows, registered_ids = [], set()
    for name, component in NATIVE_COMPONENTS.items():
        identifiers = {case.id() for target in component_targets(component) for case in resolved[target]}
        if not identifiers or registered_ids.intersection(identifiers):
            parser.error("原生组件为空或测试跨组件重复：" + name)
        registered_ids.update(identifiers)
        rows.append({"group": name, "methods": len(identifiers), "ids": sorted(identifiers),
                     "qualification": component["qualification"],
                     "node_required": component["node_required"], "curses_required": component["curses_required"]})
    if registered_ids != {case.id() for cases in resolved.values() for case in cases}:
        parser.error("原生聚合与组件矩阵的实际测试集合不一致")
    return rows


def native_matrix(resolved, parser):
    """CI 仍只消费完整分区，资格字段只留证，不过滤提升专项或将其变成 skip。"""
    return {"include": [{key: value for key, value in row.items() if key != "ids"}
                        for row in native_partition(resolved, parser)]}


def native_description(scope, resolved, parser):
    """描述是收集证据而非运行成功；脚本直接消费所选和排除，不自己推导差集。"""
    if scope not in NATIVE_SCOPES:
        parser.error("--describe 只接受完整原生或普通用户桌面范围")
    selected, excluded, registry_ids = [], [], set()
    for row in native_partition(resolved, parser):
        registry_ids.update(row["ids"])
        if scope == "windows-native" or row["qualification"] == "ordinary":
            selected.append(row)
        else:
            excluded.append({**row, "reason": "requires-elevated-test-fixture"})
    if not selected:
        parser.error("所选原生范围不能为空")

    def section(rows):
        identifiers = sorted({identifier for row in rows for identifier in row["ids"]})
        # 每个分区的 IDs 只在本层出现，组件保留资格/计数/原因；报告由权威登记
        # 即时生成，不能成为下一轮手写维护的另一份方法名单。
        return {"count": len(identifiers), "ids": identifiers,
                "components": [{key: value for key, value in row.items() if key != "ids"} for row in rows]}

    return {"schema_version": 1, "scope": scope, "full_registry_scope": "windows-native",
            "collection_only": True, "scope_is_full": scope == "windows-native",
            "registry": {"count": len(registry_ids), "ids": sorted(registry_ids)},
            "selected": section(selected), "excluded": section(excluded)}


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
    if args.describe and (len(args.selectors) != 1 or args.selectors[0] not in NATIVE_SCOPES):
        parser.error("--describe 必须且只能选择 windows-native 或 windows-native-desktop")
    native_requested = NATIVE_GROUPS.intersection(args.selectors)
    if native_requested:
        validate_native_components(parser)
        if not (args.matrix or args.describe):
            for group in native_requested:
                if not GROUPS[group]:
                    parser.error("原生范围不能为空：" + group)
    if not args.selectors:
        parser.print_help()
        return 0
    targets = []
    # describe 即使选择桌面，也先解析完整登记来证明排除项真实存在；这里只收集，
    # 不执行被排除的提升 TestCase，其权限准备必须留在各自 setUp/方法生命周期。
    selectors = ("windows-native",) if args.describe else args.selectors
    for selector in selectors:
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
    if args.describe:
        print(json.dumps(native_description(args.selectors[0], resolved, parser), separators=(",", ":")))
        return 0
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
