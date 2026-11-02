## Codex-only integration

- Light and Full implementation activate `$xy-workflow`; Light does not require Full planning or a DAG.
  Light 必做最小充分验证，交接评估独立 QA、文档与记忆；Full 保留既定确认、规划和独立 QA。
- Standalone read-only audits use WORKFLOW's matching branch and stop at the scoped conclusion,
  without the implementation/QA closeout loop; actual implementation acceptance keeps its QA contract.
- `$xy-project-memory`: retrieve only needed cross-session/history facts; retain post-QA closeout.
- Load `.agents/skills/` progressively, using only Codex `$xy-*` aliases, never other hosts' slash commands.
- Custom agents: canonical `xy-*` IDs in `.codex/agents/`; settings in `.codex/config.toml` come from
  `project.yaml` → `orchestration`.
- Plan revision/recovery: `$xy-workflow`'s `references/plan-lifecycle.md`.
- For Full, the main-session PM dispatches independent READY tasks in parallel through Codex-native
  custom Agents and keeps nested delegation disabled.
  Light／Full 默认派对应原生角色 subagent；PM 亲自实施例外及恢复边界见
  `.agent-workflow/product/WORKFLOW.md#implementation-ownership`，原等级门槛不变。
- Superpowers planning, execution, TDD, branch-finishing, and Subagent orchestration remain
  disabled by default.
- 测试与交付沿用已安装 `xy-build-verify/references/verification-scope.md`：派发时选最小
  充分范围，接收有效证据后不以 PM 身份重复跑一遍。全量测试或追加检查要有具体依据；
  生产交付仍必须有受影响目标构建／编译成功和可运行证据。
  保留 Full／必要 Light 的独立 QA、强制验证和 worktree 集成要求，满足停止条件即进入既有收口。
- For Full implementation or Light work assessed as requiring independent QA, the PM dispatches exactly one `xy-qa` reviewer. That same reviewer tries Codex native review as
  `host-native-review`, then one `installed-code-review-skill` proven installed and capable, then
  `internal-xy-qa-procedure`, moving forward only on technical unavailability. The allowed
  Superpowers option is only its installed `requesting-code-review/code-reviewer.md` prompt; Grill
  Me remains requirements-only. Findings or `FAIL` never switch review method or reviewer.
- Role TOML references boundaries and project documents; do not duplicate their content.
- Project command Hooks provide bounded intake/recovery reminders, not approvals or QA results.
  Respect native project/Hook trust and disabled settings; never bypass trust to make setup pass.
  See `.agent-workflow/platforms/shared/HOOKS.md` only for Hook configuration or diagnostics.
- SessionStart recovery includes native `fork` and `compact` sources. After a fork, verify the actual
  workspace and still-valid task authority; copied conversation context does not authorize another
  writer or repeat completed work. Do not add a second PostCompact reminder for the same recovery.

## Native review method

Use an exposed `/review` capability or `codex review` only when the unique QA reviewer can invoke
it without nested Agent delegation. Merely having a CLI binary or an installed third-party review
Skill does not prove native method availability. Resolve the selected project's effective QA
model/effort and native override layers; preserve them through supported invocation options rather
than introducing review-specific defaults or silently using another CLI profile.

For a CLI whose current help confirms the options, read-only invocation has the form
`codex --sandbox read-only --ask-for-approval never review <scope-options>`.
This invocation must remain inside existing host/project permissions and trust; do not widen them
to make review launch. `--uncommitted` covers staged, unstaged and untracked changes; `--commit`
covers that commit's introduced change; `--base` compares against the selected base branch's
merge-base semantics. Select only an option whose actual diff equals the frozen request scope.
A base argument alone is not an arbitrary pinned base/head pair, and a clean worktree does not
remove already committed request changes. Do not assume optional scope flags combine with custom
instructions: use the installed version's supported syntax and reject scope mismatches.

Bind root/nested-repository base/head, complete changed paths and dirty-diff fingerprints before and
after review. Discard output if inputs changed, a nested repository was omitted or the native range
cannot represent the request. Preserve native findings as general review evidence; the same QA
verifies findings and adds only uncovered project-acceptance checks. Record actual capability,
effective invocation, scope and result references in the existing `review_method`. Help output is
capability discovery, never proof of a completed model review. If the current tool surface cannot
invoke native review safely, record the technical reason and continue the existing method order.

## 原生工具短路径

2.0 新任务从 schema_version: 2 的单任务外壳派发：仅当前 task、适用
standards_contract 和必要批准／UI 依据，不复制完整 PM 或兄弟会话。稳定 agent_alias
绑定项目相对 module 与规范 role；独立任务按需创建新原生实例、新 ID，不预建或填满额度。
任务保留 workflow_level、instance_policy: fresh 与 context_policy: handoff_only。
当前工具为 collaboration.spawn_agent 时必须明确 `fork_turns: "none"`；其他原生入口也须
证明独立初始上下文，只提供自包含当前任务 prompt。没有该能力就报告阻塞，不能用父历史
fork 降级。宿主权限、模型及 effort 仍由当前有效配置决定。

同任务连续实现、近期短返工及同轮 Reviewer 差量复查可以续用原 ID。反馈窗口结束且 PM
已接收交付、必要验证／QA 完成、成果日志安全后，使用当前实际暴露且获授权的结束能力。
本会话若只有 interrupt_agent，它只停止当前执行，不清空上下文，也不证明关闭或释放
线程额度；没有 close／kill 或执行失败时，记录 agent_retired 并禁止续用，原生结束未确认。
退役不释放仍执行的任务锁。停止、退役、关闭与永久删除历史须分别记录，不能擅删历史。
按宿主实际口径分别观察运行数与打开线程数；容量压力先回收已验收且交接充分实例，
保留正在执行、证据未交付和必要复查实例，并为后续必要 QA／集成安排容量。
resume／compact 只恢复原上下文，不能视为 prepareForReuse；不建立 Agent 池或第二状态机。

按需使用 `xy-workflow/references/runtime-records.md` 的 doctor、原生用量和 `continuation`
操作路径；诊断的 documented/source_observed/runtime_unverified 不等于本会话执行证明。
PM 从当前原生工具取得真实 ID，经现有 update 补记 `agent_ref`，依实时 running/idle
观察查询后，仅为同任务连续工作或短返工通过当前已暴露的原生 follow-up／wait 能力复用同一 Agent。取消、退役、失效、
未知或跨宿主不自动恢复；不新建 runner／Reviewer。完整 Task Pack 与 scope 仍须交接。
当前工具表没有续发能力时如实报告，不用新开用户 chat 冒充同 Agent 续用。

QA 结构化输出见 `xy-qa-review/references/inputs.md`：支持时在同次授权调用使用
`codex exec --output-schema <schema-file>`，并用 `--output-last-message <native-result.json>`
取得最终对象，再 `qa_handoff_cli.py extract --host codex --input <native-result.json> --task-pack <current-qa-pack.json>`。
`codex review` 不支持该 schema 旗标；不得改变原审查方法顺序、模型／effort 或权限来
凑结构化输出。原生用量按响应去重，样本范围和缺失值照实披露，不推算费用或节省比例。

Regenerate with `bash .agent-workflow/setup_codex.sh`; validate with
`bash .agent-workflow/setup_codex.sh --check`.
