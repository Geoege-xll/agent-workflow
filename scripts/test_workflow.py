import argparse
import base64
import importlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import time
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
    # 安装引擎的纯逻辑/事务模块只归便携 CI；其非 Windows 负控在 Windows
    # 会明确 skip，因此不能整模块放进要求零 skip 的原生组件共享清单。
    + modules("central_project", "runtime_state", "central_runtime", "runtime_lifecycle", "native_agents", "install_cli", "windows_installer")
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
    "windows-native-delivery": {
        "targets": (
            "tests.test_windows_delivery.WindowsDeliveryNativeTest.test_https_install_cli_repeat_and_failure_preservation",
            "tests.test_windows_delivery.WindowsDeliveryNativeTest.test_real_child_stdin_failure_retains_unknown_lifecycle_scene",
        ),
        # 发布策略只操作环境输入和本地输出，不依赖 PowerShell/网络；从唯一登记
        # 派生便携 CI，避免维护第二份 curl 安装验收名单。真实安装会自行在最终
        # 私有 venv 按原 hash/binary 锁准备 curses，组件 runner 本身只需 stdlib。
        "portable_ci_targets": (
            "tests.test_windows_delivery.ReleaseWorkflowPortableTest.test_release_policy_routes_stable_and_candidate_and_rejects_invalid_identity",
        ),
        "qualification": "ordinary",
        "node_required": True, "curses_required": False,
    },
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
            # 可信路径纯策略及 SID 长度接口合同精确共享；所属模块
            # 还有 Windows 专属类，不能整模块纳入普通 CI 或破坏原生零 skip。
            "tests.test_windows_fs_native.TrustedPathPolicyTest.test_effective_masks_inherit_only_owner_and_unknown_acl_fail_closed",
            "tests.test_windows_fs_native.TrustedPathPolicyTest.test_only_same_sid_prior_deny_can_discharge_a_dangerous_grant",
            "tests.test_windows_fs_native.TrustedPathPolicyTest.test_trusted_installer_lookup_uses_validated_sid_length_within_capacity",
            "tests.test_runtime_store.RuntimeStoreTest.test_operation_unifies_load_batch_and_builtin_catalog_then_expires",
            "tests.test_runtime_store.RuntimeStoreTest.test_operation_checkpoint_rejects_unread_member_and_ancestor_drift",
            "tests.test_runtime_store.RuntimeStoreTest.test_operation_isolates_roots_pins_threads_processes_and_module_aliases",
            "tests.test_runtime_store.RuntimeStoreTest.test_operation_checkpoint_keeps_manifest_version_mode_and_member_guards",
            # 递归目录 stat 由单一快照守卫负责，精确验证收束后的目录身份边界。
            "tests.test_runtime_store.RuntimeStoreTest.test_recursive_snapshot_directory_stats_have_one_guard_owner",
            "tests.test_task_graph_records.RecordPublicationTest.test_operation_finish_rejects_source_drift_before_any_temporary_or_publish",
            "tests.test_task_graph_records.RecordPublicationTest.test_operation_finish_precedes_last_fresh_cas_and_settlement_sources",
            # Records 独立脚本/包导入的发布消费者应共享目录 fd 注册与读取
            # 操作归属；只登记这一合同，不扩选同模块的其他运行时/宿主夹具。
            "tests.test_task_graph_records.RecordNativePublisherContractTest.test_standalone_and_package_publication_keep_directory_registry_and_read_operation_owner",
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
            # 控制台阶段 profile 的外层 lease/hooks 及不完整 binding 边界
            # 只共享两个便携合同，不扩选同模块的原生 TUI/curses 用例。
            "tests.test_windows_native_integration.ConsolePhaseProfilePortableTest.test_job_refresh_profiles_outer_lease_and_preserves_hooks",
            "tests.test_windows_native_integration.ConsolePhaseProfilePortableTest.test_profile_bounds_and_incomplete_binding",
            # reset/分层等待谓词仅依赖 stdlib；原 App 两方法仍归下方 curses
            # 组件并由原 CLI 监督，不将这些纯谓词扩成另一个子执行名单。
            "tests.test_windows_native_integration.NativeUIResetPredicatePortableTest.test_reset_requires_selected_fields_and_sources_in_one_native_frame",
            "tests.test_windows_native_integration.NativeUIResetPredicatePortableTest.test_reset_command_rejects_old_toast_and_waits_for_business_transition",
            "tests.test_windows_native_integration.NativeUIAsyncWaitPortableTest.test_action_wait_uses_input_deadlines_and_requires_new_acknowledgement",
            "tests.test_windows_native_integration.NativeUIAsyncWaitPortableTest.test_action_wait_preserves_checkpoint_progress_and_terminal_failures",
            # 监督协议本身也必须在真实 Windows 消费原 Job owner；精确共享
            # 六个便携合同，不扩选带平台保护的整个 validation_runner 模块。
            "tests.test_validation_runner.SupervisedPortableBatchTest.test_selected_registry_cases_run_once_with_required_ids_and_raw_evidence",
            "tests.test_validation_runner.SupervisedPortableBatchTest.test_failure_skip_and_class_cleanup_cannot_be_reported_as_success",
            "tests.test_validation_runner.SupervisedPortableBatchTest.test_timeout_preserves_partial_raw_and_real_started_events",
            "tests.test_validation_runner.SupervisedPortableBatchTest.test_missing_or_forged_terminal_record_is_rejected",
            "tests.test_validation_runner.SupervisedPortableBatchTest.test_unknown_cleanup_retains_private_scene_without_replaying_live_raw",
            "tests.test_validation_runner.SupervisedPortableBatchTest.test_parent_partitions_only_registry_portable_cases_without_rerun",
            "tests.test_validation_runner.SupervisedPortableBatchTest.test_raw_forward_failures_preserve_durable_evidence_and_fail_closed",
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
        # App 后置刷新的共享读取与尾验漂移合同同样需要 curses；CI/原生
        # 同源复用两方法，不扩选整个模块或引入其它 POSIX PTY 夹具。
        "portable_ci_targets": (
            "tests.test_manager_tui.ProjectTuiIntegrationTest.test_apply_project_refresh_shares_core_read_scope_per_pin",
            "tests.test_manager_tui.ProjectTuiIntegrationTest.test_apply_project_refresh_tail_drift_preserves_commit_truth_and_drafts",
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
                "Windows 完整 --matrix/--describe 会导入 TUI 模块；所选解释器须先按 requirements-windows.txt 准备依赖。\n"
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
        self.event("start", test.id())

    def stopTest(self, test):
        self.stopped_ids.add(test.id())
        self.event("stop", test.id())
        self.active_test_id = None
        super().stopTest(test)

    def addSkip(self, test, reason):
        super().addSkip(test, reason)
        # unittest 的 subTest skip 只登记子场景 id，父方法仍然算已启动并且整体
        # wasSuccessful() 为真。使用 start/stop 生命周期记录当前父方法，不依赖
        # 私有 _SubTest 类型；任一原生必验子场景未执行，都使所属方法不能获验收。
        self.skipped_ids.add(self.active_test_id or test.id())
        self.event("skip", self.active_test_id or test.id())

    def event(self, kind, identifier):
        if self.event_stream is not None:
            _write_execution_event(self.event_stream, {"kind": kind, "id": identifier})

    def __init__(self, *args, event_stream=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.started_ids = set()
        self.stopped_ids = set()
        self.skipped_ids = set()
        self.active_test_id = None
        self.event_stream = event_stream


def _write_execution_event(stream, event):
    # start/skip/stop 是真实生命周期证据，及时 flush 使执行 deadline 到达时
    # 仍可读取已发生的事实；stopTest 只代表方法结束，绝不推导成功。
    sys.stdout.flush()
    sys.stderr.flush()
    stream.write(json.dumps(event, ensure_ascii=True, separators=(",", ":")) + "\n")
    stream.flush()
    os.fsync(stream.fileno())


def run_cases(cases, required_native_ids=(), *, _event_stream=None):
    result = unittest.TextTestRunner(
        verbosity=2, resultclass=lambda *args, **kwargs: ExecutionResult(
            *args, event_stream=_event_stream, **kwargs),
    ).run(unittest.TestSuite(cases))
    # unittest 把全 skip 当成功，但原生必验集合必须真正执行。逐个 required id 核对，
    # 既拒绝全 skip，也拒绝自定义 suite 未执行节点；失败用原退出码 1 向上传播。
    executed = result.started_ids - result.skipped_ids
    complete = not required_native_ids or set(required_native_ids).issubset(executed)
    if not complete:
        print("原生必验节点未实际执行或被 skip；不能作为 Windows 验收成功。", file=sys.stderr)
    code = 0 if complete and result.wasSuccessful() else 1
    if _event_stream is not None:
        # TextTestRunner.run 已返回：包括 tearDownClass/doClassCleanups 和完整
        # 终端摘要。只有此处的结果才可结算；单个 stop 事件不代表类清理已完成。
        _write_execution_event(_event_stream, {
            "kind": "terminal", "expected_ids": sorted(required_native_ids),
            "started_ids": sorted(result.started_ids), "stopped_ids": sorted(result.stopped_ids),
            "skipped_ids": sorted(result.skipped_ids), "tests_run": result.testsRun,
            "failures": len(result.failures), "errors": len(result.errors),
            "skips": len(result.skipped), "unexpected_successes": len(result.unexpectedSuccesses),
            "successful": result.wasSuccessful(), "exit_code": code,
        })
    return code


# 只约束当前登记的 App 子批次执行期限，不改变产品操作 deadline，也不承诺
# Windows 内核终止/Job 归零有绝对墙钟上限。恢复确认仍完全归原 capture_process。
SUPERVISED_EXECUTION_SECONDS = 600


def _supervised_portable_ids():
    # 监督只负责当前登记的 App 子集；合法的最小组件计划可以没有 TUI。
    # 实际 TUI 存在时仍完整返回其唯一共享字段，不改变 required/noSkip。
    component = NATIVE_COMPONENTS.get("windows-native-tui")
    return tuple(component.get("portable_ci_targets", ())) if component is not None else ()


def _run_supervised_child(body):
    # 无公共 child 参数或任意模块入口；固定 bootstrap 只进入本函数。请求携带
    # 的方法必须来自同一 registry，随后仍经原 load_target/run_cases 验证执行。
    request = json.loads(body)
    directory = Path(request["directory"])
    identifiers = request["ids"]
    if (not identifiers or len(set(identifiers)) != len(identifiers)
            or not set(identifiers).issubset(_supervised_portable_ids())):
        raise ValueError("受监督子批次必须来自原 TUI portable_ci_targets")
    os.chdir(PACK)
    sys.path.insert(0, str(PACK))
    # 父进程已用 x 模式在私有独占目录创建三个文件；子进程不截断旧证据。
    # -u 与 fd 重定向覆盖 Python、原生 fd 写入及异常 traceback，不依赖超时
    # 异常能否携带 capture 管道的 partial bytes。
    with (directory / "stdout.raw").open("ab", buffering=0) as output, \
            (directory / "stderr.raw").open("ab", buffering=0) as error, \
            (directory / "events.jsonl").open("a", encoding="utf-8", newline="\n") as events:
        sys.stdout.flush()
        sys.stderr.flush()
        os.dup2(output.fileno(), 1)
        os.dup2(error.fileno(), 2)
        cases = [case for target in identifiers for case in load_target(target, make_parser())]
        # 显式传 required，不能因精确 CLI 方法没有 native 组 selector 而变空。
        code = run_cases(cases, required_native_ids=set(identifiers), _event_stream=events)
        sys.stdout.flush()
        sys.stderr.flush()
        os.fsync(output.fileno())
        os.fsync(error.fileno())
        return code


def _validate_supervised_events(raw, identifiers, returncode):
    # 逐事件核对真实启动/停止与终态；未知、截断、重复、skip、遗漏或 exit
    # 不匹配都不能变绿。终态必须位于最后，且来自完整 runner 返回后的结果。
    expected = set(identifiers)
    try:
        if not raw.endswith(b"\n"):
            return False
        events = [json.loads(line) for line in raw.decode("utf-8").splitlines()]
        terminal = events[-1]
        active, started, stopped = set(), set(), set()
        for event in events[:-1]:
            identifier = event["id"]
            if identifier not in expected:
                return False
            if event["kind"] == "start" and identifier not in started and not active:
                active.add(identifier)
                started.add(identifier)
            elif event["kind"] == "stop" and identifier in active:
                active.remove(identifier)
                stopped.add(identifier)
            else:
                return False
        return (returncode == 0 and not active and started == stopped == expected
                and terminal["kind"] == "terminal" and terminal["successful"] is True
                and type(terminal["exit_code"]) is int and terminal["exit_code"] == 0
                and type(terminal["tests_run"]) is int and terminal["tests_run"] == len(expected)
                and terminal["expected_ids"] == sorted(expected)
                and terminal["started_ids"] == sorted(expected)
                and terminal["stopped_ids"] == sorted(expected)
                and terminal["skipped_ids"] == []
                and all(type(terminal[key]) is int and terminal[key] == 0
                        for key in ("failures", "errors", "skips", "unexpected_successes")))
    except (KeyError, IndexError, TypeError, ValueError, UnicodeError):
        return False


def _forward_raw(stream, raw):
    # 真实入口具有 binary buffer，原字节原样转发；StringIO 仅用于进程级
    # 合同的重定向断言，不能改变生产 stdout/stderr 的原始字节。
    if hasattr(stream, "buffer"):
        stream.flush()
        if stream.buffer.write(raw) != len(raw):
            raise OSError("原始测试流转发发生短写")
        stream.buffer.flush()
    else:
        text = raw.decode("utf-8", errors="backslashreplace")
        if stream.write(text) != len(text):
            raise OSError("测试流转发发生短写")
        stream.flush()


def _publish_supervised_evidence(record):
    destination = os.environ.get("AWF_TEST_EVIDENCE_LOG")
    if destination:
        # 复用 CI/Win11 的现有 artifacts 出口，完整双流 base64 保留任意字节；
        # 只有成功写入并 flush 后，父进程才可删除已归零的私有临时场景。
        with Path(destination).open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(record, ensure_ascii=True, separators=(",", ":")) + "\n")
            stream.flush()
            os.fsync(stream.fileno())


def _run_supervised_cases(identifiers):
    from lib.install.install_process import capture_process, SetupRunError
    from lib.install.windows_process import WindowsJobCleanupError

    identifiers = tuple(identifiers)
    if (not identifiers or len(set(identifiers)) != len(identifiers)
            or not set(identifiers).issubset(_supervised_portable_ids())):
        raise ValueError("受监督目标不在唯一 TUI registry 中")
    directory = Path(tempfile.mkdtemp(prefix="awf-validation-app-", dir=os.environ.get("AGENT_WORKFLOW_TEST_SCRATCH")))
    directory.chmod(0o700)
    for name in ("stdout.raw", "stderr.raw", "events.jsonl"):
        with (directory / name).open("xb") as stream:
            os.chmod(stream.name, 0o600)
    # 固定代码/固定源码路径，不提供公开 child flag 或任意 target 输入。
    bootstrap = ("import runpy,sys; scope=runpy.run_path(sys.argv[1]); "
                 "raise SystemExit(scope['_run_supervised_child'](sys.stdin.buffer.read()))")
    command = [sys.executable, "-I", "-B", "-u", "-X", "utf8", "-c", bootstrap, str(PACK / "scripts/test_workflow.py")]
    started = time.monotonic()
    record = {"kind": "validation-supervised-batch", "expected_ids": sorted(identifiers),
              "execution_deadline_seconds": SUPERVISED_EXECUTION_SECONDS,
              # POSIX 只沿原 capture_process 的父进程退出/异常进程组停止合同，
              # 不将本机回归描述成 Windows Job 全成员归零证明。
              "owner_protocol": "windows-job-zero" if os.name == "nt" else "posix-capture-process",
              "owner_quiescent": False, "ownership_evidence": "unconfirmed",
              "raw_complete": False, "scene": str(directory)}
    completed = None
    try:
        completed = capture_process(command, body=json.dumps({"directory": str(directory), "ids": identifiers}).encode(),
                                    timeout=SUPERVISED_EXECUTION_SECONDS)
        record.update(owner_quiescent=True, ownership_evidence="capture-process-returned",
                      outcome="exited", child_exit=completed.returncode)
    except subprocess.TimeoutExpired as error:
        # 现接口的执行超时来自 communicate；底座 stop/close 成功后才传播。
        # 无法确认 Job 回收则改抛 WindowsJobCleanupError，不进入此分支。
        record.update(owner_quiescent=True, ownership_evidence="capture-timeout-stop-returned",
                      outcome=type(error).__name__, child_exit=None, error_detail=str(error))
    except (WindowsJobCleanupError, KeyboardInterrupt, SetupRunError) as error:
        # KI 可能来自 POSIX Popen 尚未进入 communicate 清理 try 的接缝；
        # SetupRunError 同时用于启动前拒绝/取消，现接口没有可区分的 owner
        # 收据。不能从异常名字追认“已停止”或实际创建过 Windows Job。
        # 一律保守 unknown，不读可能仍写入的 raw，不删现场，也不造归零证明。
        record.update(outcome="unknown-" + type(error).__name__, child_exit=None, error_detail=str(error))
    except Exception as error:
        # 不理解的启动/回收异常保守保留现场，不读取可能仍在写入的 raw 文件。
        record.update(outcome="unknown-" + type(error).__name__, child_exit=None, error_detail=str(error))
    record["elapsed_seconds"] = time.monotonic() - started
    record["windows_job_zero_proved"] = os.name == "nt" and record["owner_quiescent"]
    code = 1
    output = error = b""
    if record["owner_quiescent"]:
        output = (directory / "stdout.raw").read_bytes() + (completed.stdout if completed is not None else b"")
        error = (directory / "stderr.raw").read_bytes() + (completed.stderr if completed is not None else b"")
        events = (directory / "events.jsonl").read_bytes()
        valid = completed is not None and _validate_supervised_events(events, identifiers, completed.returncode)
        record.update(raw_complete=completed is not None, protocol_valid=valid,
                      stdout_b64=base64.b64encode(output).decode(), stderr_b64=base64.b64encode(error).decode(),
                      events_b64=base64.b64encode(events).decode())
        code = (completed.returncode or (0 if valid else 1)) if completed is not None else 1
    # 首先持久化完整 raw/lifecycle，之后才接触可能 BrokenPipe 的控制台。
    # 此记录明确是待转发快照，exit_code=None，不能冒充最终 CLI 成功。
    record.update(phase="captured-before-forward", scene_retained=True, exit_code=None,
                  child_result_exit=code, forward_errors=[])
    try:
        _publish_supervised_evidence(record)
    except OSError as error:
        try:
            print(f"监督证据写入失败，保留场景 {directory}：{error}", file=sys.stderr, flush=True)
        except OSError:
            pass
        return 1

    if record["owner_quiescent"]:
        for name, stream, raw in (("stdout", sys.stdout, output), ("stderr", sys.stderr, error)):
            try:
                _forward_raw(stream, raw)
            except OSError as failure:
                record["forward_errors"].append({"stream": name, "error": str(failure),
                                                  "type": type(failure).__name__})
                code = code or 1
    # 未知 owner 不读/转发活 raw；任一转发故障也保留已知静止场景，完整字节已
    # 进入原 AWF 出口，最终记录明确非 0，不依赖 traceback 或临时路径救证据。
    record.update(phase="final", exit_code=code,
                  scene_retained=not record["owner_quiescent"] or bool(record["forward_errors"]))
    try:
        _publish_supervised_evidence(record)
        summary = {key: value for key, value in record.items() if key not in ("stdout_b64", "stderr_b64")}
        print("validation-supervised-batch " + json.dumps(summary, ensure_ascii=True), file=sys.stderr, flush=True)
    except OSError as failure:
        # 最终出口/摘要本身也可能失败。保现场并尽力追加非 0 收据；首份 raw
        # 快照已持久化时仍在，失败的摘要绝不让函数以原 child 的 0 返回。
        code = code or 1
        record.update(exit_code=code, scene_retained=True)
        record["forward_errors"].append({"stream": "final-evidence-or-summary", "error": str(failure),
                                          "type": type(failure).__name__})
        try:
            _publish_supervised_evidence(record)
        except OSError:
            pass
    if not record["scene_retained"]:
        try:
            shutil.rmtree(directory)
        except OSError as failure:
            code = code or 1
            record.update(exit_code=code, scene_retained=True, cleanup_error=str(failure))
            _publish_supervised_evidence(record)
    return code


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
    # 仅从原 TUI portable 字段取交集；即使经 ci/父模块/精确方法选择到达，
    # App 方法也只进入一次受监督 child，父 runner 不再执行或伪填其 started。
    child_ids = tuple(identifier for identifier in _supervised_portable_ids() if identifier in cases)
    ordinary = [case for identifier, case in cases.items() if identifier not in child_ids]
    ordinary_code = run_cases(ordinary, required_native_ids - set(child_ids)) if ordinary else 0
    child_code = _run_supervised_cases(child_ids) if child_ids else 0
    return ordinary_code or child_code


if __name__ == "__main__":
    raise SystemExit(main())
