## Codex-only integration

业务派发先遵守共享 [只读偏好合同](../../shared/skills/xy-workflow/references/dispatch.md#read-only-native-dispatch-preferences)。
通用 fresh 工具没有原生角色选择器时使用 `--agent '*'`，不按 `task_name` 或角色标签查偏好。
仅当前实际 schema 提供 model／reasoning_effort 时才按其语义映射；inherit 不传 model，
未配置 effort 不传 effort，不支持的已配置字段阻断该次派发。完整原生定义可能更高优先，
参数投影仍为 runtime 未验。此步骤不启动独立服务、不准备组件，显式维护分支不执行。

- Light and Full implementation activate `$xy-workflow:xy-workflow`; Light does not require Full planning or a DAG.
  Light requires minimum sufficient verification and assesses independent QA, documentation, and memory at handoff; Full retains planning and independent QA. For request scope, material solutions before dependent design or implementation, and concrete page decisions, use `product/WORKFLOW.md#business-confirmation-policy` and the shared PM confirmation reference.
- Standalone read-only audits use WORKFLOW's matching branch and stop at the scoped conclusion,
  without the implementation/QA closeout loop; actual implementation acceptance keeps its QA contract.
- `$xy-workflow:xy-project-memory`: retrieve only needed cross-session/history facts; retain post-QA closeout.
- Load discovered plugin Skills progressively, using their Codex-qualified names.
  Classify an explicitly delegated implementation directly as Light or Full when scope, impact and acceptance
  are clear. Use `$xy-workflow:xy-grilling` only for a material gap in the deliverable, scope, impact or acceptance.
  A clear Full request uses established facts for planning coverage and proceeds to `xy-plan`.
  `$xy-workflow:xy-grill-me` is user-invoked only. When the primitive is selected and no Skill tool is available, fully read the packaged canonical primitive;
  discovery and handoff declarations do not prove loading or runtime execution.
- Native Codex definitions can be discovered in user and project agent directories. Resolve package roles and Skills against the verified plugin. Confirm the actual native selector before applying per-role preferences.
- Source observation for Codex `rust-v0.166.0`: enabled configuration layers load from low to high; a trusted project role definition takes precedence over the same user role name, subject to other native overrides. See [role loader](https://github.com/openai/codex/blob/rust-v0.166.0/codex-rs/agent-roles/src/loader.rs) and [configuration layer priorities](https://github.com/openai/codex/blob/rust-v0.166.0/codex-rs/config/src/config_layer_source.rs). This is source-observed behavior, not proof of actual role/model execution in the current session.
- Plan revision/recovery: `$xy-workflow:xy-workflow`'s `references/plan-lifecycle.md`.
- For Full, the main-session PM dispatches independent READY tasks in parallel through Codex-native
  custom Agents and keeps nested delegation disabled.
  Light/Full defaults to the corresponding native role subagent; see `product/WORKFLOW.md#implementation-ownership` for the PM implementation exception and recovery boundaries, preserving the original level's gates.
- Superpowers planning, execution, TDD, branch-finishing, and Subagent orchestration remain
  disabled by default.
- Testing and delivery follow installed `xy-build-verify/references/verification-scope.md`: choose the minimum sufficient scope at dispatch and do not repeat valid accepted evidence as PM. Full suites or additional checks need concrete justification; production delivery still requires successful affected-target build/compile and runnable evidence. Preserve Full/necessary Light independent QA, mandatory verification, and worktree integration requirements; proceed to existing closeout when stop conditions are met.
- For Full implementation or Light work assessed as requiring independent QA, the PM dispatches exactly one `xy-qa` reviewer. That same reviewer tries Codex native review as
  `host-native-review`, then one `installed-code-review-skill` proven installed and capable, then
  `internal-xy-qa-procedure`, moving forward only on technical unavailability. The allowed
  Superpowers option is only its installed `requesting-code-review/code-reviewer.md` prompt; Grill
  Me remains requirements-only. Findings or `FAIL` never switch review method or reviewer.
- Role TOML references boundaries and project documents; do not duplicate their content.
- The plugin SessionStart Hook provides a bounded entry reminder, not approvals or QA results.
  Respect native project/Hook trust and disabled settings; never bypass trust to make setup pass.
  See `platforms/shared/HOOKS.md` only for Hook configuration or diagnostics.
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

按[核对原生审查目标](../../shared/skills/xy-qa-review/references/inputs.md#核对原生审查目标)比对这些选项实际覆盖的差异。尤其留意 `--uncommitted` 读到同一文件中的其它改动，以及 `--base` 所解析的合并基点与冻结基点不同。没有精确入口就记录具体原因并依序回退。保留实际调用和结果，核对审查前后的冻结范围后，由同一 Reviewer 核实发现并补齐业务验收。参见 [Codex CLI 审查参数](https://developers.openai.com/codex/cli/reference/#codex-review)。

## Native Tool Short Path

After a `read_only`/`evidence` worker actually completes, accept its latest-scope result and revision
acknowledgement, then use the existing record `update` exclusive `settle` operation under shared
`runtime-records.md#result-task-settlement`. Bind the original Codex native ID and accepted complete pack
bytes plus actual native result/event and verification evidence. RESULT_VERIFIED ends record execution
occupancy; optional retirement does not prove close or release open native threads. Writer/QA gates remain.

Apply WORKFLOW's `continuous-pm-intake` and the shared dispatch checks for all relationship,
authorization, ownership, pin and request-QA decisions; this adapter supplies only Codex-native differences.
The [current CLI documentation](https://learn.chatgpt.com/docs/developer-commands?surface=cli) says Enter
injects instructions into the working turn and Tab queues a followup for the next turn; inspect actual
client/key bindings and use injection when B needs PM coordination during A. The
[App setting](https://learn.chatgpt.com/docs/reference/settings) is General → Follow-up behavior: steer
the current run or queue the next run. Do not write an invented universal TOML key, treat IDE
`chatgpt.followUpQueueMode` as CLI/App configuration, or edit host databases to change this behavior.

The [subagent guide](https://learn.chatgpt.com/docs/agent-configuration/subagents) describes steering,
stopping and closing; actual tool exposure still controls what PM can do. When exposed and authorized,
`collaboration.send_message` sends to a running original ID without interrupting; native wait can yield to
new input/results. `followup_task` may resume an idle original ID. Query `agent_continuation_cli.py` with
the appropriate intent and only capabilities verified on that current surface. `interrupt_agent` stops
execution and must not substitute for non-interrupting steer. For direct app-server integrations,
[`turn/steer`](https://learn.chatgpt.com/docs/app-server) requires the matching `expectedTurnId` and appends
to an active turn; `turn/interrupt` requests cancellation. This pack does not start another app-server/daemon.

In the actual target CLI and App, separately retain evidence for B delivery, wait wakeup, A continuing on
the same ID without restart/duplicate dispatch, same-ID followup, and child lifecycle after parent final or
interruption. A successful version probe/configuration projection proves none of these. Unknown cases remain
`runtime_unverified`; do not assume final keeps children alive or proactively finish while coordination is needed.

Codex 的每项独立设计／实现沿用同一任务池。先使用共享派发入口领取原件并导出当前包，然后 spawn。从该次返回取实际 ID 并用原领取回执执行 `pool bind`。同时发起多个独立任务时，各自匹配回执及实际 ID。宿主没有确认创建时按原释放／保留规则处理。

### Codex 项目写入分工

在官方 `/hooks` 中审阅并信任本版 PreToolUse 后，使用受管项目的物理目录开始新会话。
普通已委托开发由 PM 完成现有批准、领取和实际原生派发，取得实例 ID 后立即执行
`pool bind`。在 Writer 开始编辑前核对其领取、当前批准、工作树和确切 `owned_paths`。
守卫使用当前原生事件和同一线程的会话元数据核对父线程和完整子线程 ID 或原生路径。
工具标签、昵称和交接文本不能代替身份。先于绑定到达的编辑须等 PM 绑定后重试。

守卫覆盖原生 `apply_patch` 和 Bash。使用独立命令执行读取、包内 helper、原件已登记的
验证及写入。可用的 Bash 写入形态包括字面路径的 `touch`、`mkdir`、简单 stdout 重定向
和单引号分隔符的 `cat` heredoc。用 `apply_patch` 表达应用代码的多文件编辑和移动。
守卫需要在工具运行前确认每个写目标，无法识别的脚本、扩展或复合 Bash 写入会被拦截。
已登记验证命令运行的项目代码继续受宿主沙箱约束。第三方工具、外部进程和任意间接副作用
不属于此 Hook 的覆盖范围。

PM 可直接准备当前项目计划与请求交接文件。用户根据现有例外规则明确指定 PM 实施时，
Hook 从当前原生 UserMessage 核对实际目标。例如“请 PM 本人直接修改 src/example.py”。
其他已获准的实际范围若无法从当前事件核对，先提交精确文件范围供用户确认或按原有委托派发。
任务内原有批准、构建和独立 QA 仍按适用规则执行。用户明确调用的 `xy-config` 维护使用
原固定启动器和本轮预览确认。Hook 的放行仍进入宿主自己的权限流程。

### Codex 原生结果收尾

新登记取当前原生主会话身份，使用 `--pm-id codex:<session_id>`，项目根使用该主会话的物理工作目录。已用其他获准标识登记的任务继续通过其原池找回。暂停或找不回原池时保留原占用，并按共享恢复规则核实。

收到绑定 Worker 的原生完成结果时，PM 直接走上述结果验收。主会话准备结束时，已受信任的 [Codex Stop Hook](https://learn.chatgpt.com/docs/hooks#stop) 只读查询同一项目与会话的登记，在有仍占用的已绑定 Codex `read_only` 或 `evidence` 任务时提醒 PM 继续本轮。该轮已有 Stop 续行时由 `stop_hook_active` 跳过，查询失败显示提示并保留原件。Hook 沿用当前用户的暂停、撤回和授权范围。

PM 重读原池和当前原件，通过宿主实际提供的完成结果或原生 wait/status 核对原 ID。Worker 仍在运行且允许等待时，PM 使用宿主等待来继续协调。`SubagentStop` 可以在 Worker 真正完成前触发，结算使用后续实际完成观察、当前已交付并接受的完整包（含适用修订回执）以及结果和验证证据。实际结算释放记录占用后，用当前宿主容量重新查询准入，按原流程启动已有批准且可领取的任务。Writer、唯一独立 QA、宿主线程回收和取消各沿用现有入口。

Stop 只在当前主会话结束前运行。会话已空闲、Hook 被禁用或未受信任、宿主无法提供原 ID 的完成证据时，按现有原生交接和任务池恢复入口核实，保留未确认占用。

Dispatch new schema 2 tasks through a schema_version: 2 single-task envelope containing only the current task, applicable standards_contract, and necessary approval/UI evidence, without copying complete PM or sibling conversations. Stable agent_alias binds project-relative module and canonical role; create new native instances/IDs on demand for independent tasks, without precreation or filling capacity. Tasks retain workflow_level, instance_policy: fresh, and context_policy: handoff_only. When the current tool is collaboration.spawn_agent, explicitly set `fork_turns: "none"`; other native entries must also prove independent initial context and receive only a self-contained current-task prompt. Report a blocker if unavailable rather than falling back to a parent-history fork. Current effective configuration still determines host permissions, model, and effort. Inspect the current native spawn schema for its supported role selector; `task_name` names the task and does not prove a `xy-*` descriptor, model, or effort was selected. Use a native role argument only when that current authorized surface actually exposes it. Do not report native role/model execution as verified from file parsing or a task label; preserve the existing dispatch flow and report the missing native selection evidence.

Continuous same-task implementation, recent short rework, and same-round Reviewer delta checks may reuse the original ID. After the feedback window, PM acceptance, necessary verification/QA, and safe results/logs, use the currently exposed authorized termination capability. If this session exposes only interrupt_agent, it stops current execution without clearing context or proving closure/thread-capacity release; without close/kill or when execution fails, record agent_retired and prohibit continuation, with native termination unconfirmed. Retirement releases no still-running task locks. Record stop, retirement, closure, and permanent history deletion separately; do not delete history without authority. Use [the shared closeout and cleanup steps](../../shared/skills/xy-workflow/references/closeout.md#回收已验收的原生实例) for the registered request and exact target. Observe running and open-thread counts separately using actual host definitions; under pressure reclaim accepted instances with sufficient handoff first, retain executing instances, undelivered evidence, and necessary reviewers, and reserve capacity for later necessary QA/integration. resume/compact restores only original context, not prepareForReuse; create no Agent pool or second state machine.

Use doctor, native usage, and `continuation` paths in `xy-workflow/references/runtime-records.md` as needed; diagnostic documented/source_observed/runtime_unverified is not evidence of this session's execution. The PM obtains actual IDs from current native tools and records `agent_ref` through existing update. After querying with a live running/idle observation, reuse the same Agent only for continuous same-task work or short rework through currently exposed native follow-up/wait capabilities. Do not automatically recover cancelled, retired, invalid, unknown, or cross-host instances, or create a runner/Reviewer. Still hand off the complete Task Pack and scope. Report absent follow-up capabilities truthfully; a new user chat is not same-Agent continuation.

See `xy-qa-review/references/inputs.md` for structured QA output: when supported, use `codex exec --output-schema <schema-file>` in the same authorized invocation, obtain the final object with `--output-last-message <native-result.json>`, then run `qa_handoff_cli.py extract --host codex --input <native-result.json> --task-pack <current-qa-pack.json>`. `codex review` does not support this schema flag; do not change the original method order, model/effort, or permissions to obtain structured output. Deduplicate native usage by response, disclose sample scope and missing values truthfully, and infer no costs or savings rates.

Use the official Codex marketplace for updates. Resource checks remain `runtime_unverified` until an actual native invocation exercises the role and model.
