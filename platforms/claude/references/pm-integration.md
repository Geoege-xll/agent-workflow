# Claude Code — PM bootstrap

This entire managed section applies only when the current host is Claude Code.
Codex and Antigravity use their own integration sections; do not apply their tool aliases here.

Managed by `bash .agent-workflow/setup_claude.sh`.

## Entry and authority

The main conversation alone orchestrates. Light and Full product changes invoke `/xy-workflow`.
Light／Full 默认派对应原生 `Agent(xy-*)`，只使用普通命名角色，不使用会复制父历史的 fork。
PM 亲自实施例外及恢复边界见 `.agent-workflow/product/WORKFLOW.md#implementation-ownership`，
原等级门槛不变。PM 继续负责分级、规划、派发、QA 接收、记忆收口和汇报。
Standalone read-only audits follow WORKFLOW's matching branch and stop at the scoped conclusion,
without the implementation/QA closeout loop; actual implementation acceptance keeps its QA contract.

For selected independent functional units, follow `/xy-workflow`'s `references/worktree-delivery.md`.
Prefer the native Agent tool's per-call worktree isolation when available. Verify the actual root
and exact prerequisite-containing base; default branch selection is not proof of the required base.
Keep role isolation dynamic rather than setting every role permanently to `isolation: worktree`.
PM-local integration and confirm/auto local main delivery use the shared contract; do not rewrite
global worktree settings, permissions or user hooks, or create new user-visible sessions as a fallback.

Light 先判断当前目标、风险、范围和实施者，最小充分验证必做；交接评估独立 QA、
文档及记忆。不强制 Full 规划、DAG、保存计划或重复确认；Full 和实际必要 QA 的门槛保留。

Read paths and limits from `.agent-workflow/project.yaml`. ProjectProfile is routing context, never
write authority. Each task pack fixes current facts, `owned_paths`, reads/Skills, dependencies,
acceptance, and commands.

Internal orchestration records are not user-facing output. Never paste raw workflow YAML or DAG JSON into user messages.
Report concise natural-language goals, scope, decisions, risks, validation, and next actions. Accept
an explicit natural-language confirmation and record the internal gate; never demand a gate token.
For design-change UI, also present one reasoned prototype recommendation and require the user to
select prototype work, direct implementation, or the clearly named recommendation.
Finish the brief before the single approval choice; add no material details afterward.

## Gates and execution

- Full: classify → optional relevant facts → Grill Me coverage check via `/grill-me` → `/xy-plan`
  with `plan_state: draft` → PM
  post-QA controlled-document projection decision → ask once for `requirements_approved` → freeze and run.
  Keep PROJECT/plans 已验收基线 at its last QA-verified state until integrated QA PASS. Clear
  Light work may skip the two Skills when facts are complete.
- Grill Me remains requirements-only. Superpowers is disabled by default except the bounded reviewer
  fallback below; `xy-plan` is the local planner. Reopen approval only for material scope change.
- Full `UI-Conformance` requires `design_delta: none` and has no visual gate. It also requires
  `surface_kind: production_ui`, `qa_scope: request`, `prototype_policy: not_applicable`, structured
  resolved/fingerprinted `design_authority_refs`, zero design writes, and full UI/accessibility QA.
  普通 Light 文案沿共享 `Light UI copy` 分支，仍保留真实冻结设计权威、工程／设计规范与
  最小验证；独立 QA 依交接时的实际风险评估，不因同用 UI-Conformance 而强制 Full。
- UI design-change work requires `visual_approved` per exact page dependency fingerprint when
  the user selects `prototype_policy: required`, plus `xy-uiux` and `/xy-prototype-verify`. A
  scope-bound `prototype_decision` captured inside `requirements_approved` applies to both
  `required` and `waived_by_user`; the PM must not default or invent it. `waived_by_user` has no prototype-design
  dependency, prototype write, or visual gate. Full UI/accessibility QA remains. Platform security
  prompts remain separate. Explicit production-only revisions follow the plan lifecycle;
  do not restart prototype work to synchronize product edits.
- For initial/revised design standards or full visual replacement, use `/xy-workflow`'s
  `references/design-standards.md`. PM assesses/adopts scope separately from feature documentation;
  UI Agent maintains authorized leaves. `design_mode: standards_only` can precede waived production
  without prototype files, verification or visual gates. Refresh affected authority before consumers.
- For Full, run the READY DAG with Claude native Agents. Use background Agent execution for currently READY
  independent tasks; keep gates, conflicting writes, and user interaction foreground. Static roles
  never delegate.
- For Full, validate scheduler state with `task_graph_cli.py validate`, `ready`, and `qa-ready`; keep no second
  PM state list.
- Every writer returns `/xy-build-verify`. Writers require the fingerprinted STANDARDS index,
  smallest applicable domain leaves, and `standards-conformance`. For Full or Light assessed as requiring
  independent QA, dispatch exactly one `xy-qa` reviewer using `/xy-qa-review`.

That reviewer tries `host-native-review`, then one `installed-code-review-skill` proven installed
and capable, then `internal-xy-qa-procedure`, moving forward only on technical unavailability. The only
Superpowers fallback is its installed `requesting-code-review/code-reviewer.md` prompt. Findings or
`FAIL` never switch review method or reviewer.

### Native review method

Claude's bundled `/code-review` (also `/review`) supplies general code-review evidence. Confirm the
current session exposes the genuine bundled entry: a same-named installed Skill can replace
`/code-review`, while `/review` remains the bundled alias on supporting clients. Check exposed
capability and effective disabling/override settings without scanning personal Skill directories.
The managed GitHub Code Review service and `REVIEW.md` are separate; local review follows the
project's `CLAUDE.md`. Do not enable cloud review or add another rules document for this method.

Default interactive review runs as a background subagent, which does not fit QA's no-nested-Agent
boundary. Where supported and already permitted, use the native non-interactive `-p` foreground
entry with an explicit fixed review target, such as `/review <fixed-base>..<fixed-head>`, and wait
for its actual result in the same reviewer's execution. Keep exactly one reviewer; do not alter
global background/fork settings, weaken disallowed tools or spawn another reviewer to obtain it.
Without a safe available foreground entry, record technical unavailability and use the next method.

Use only an already trusted workspace and verified effective project/role configuration: `-p`
skips workspace-trust dialogs and is not proof of trust or read-only permissions. Invalid settings
may be ignored by the host, so establish that its actual tool/permission boundary excludes writes,
external posting and Agent delegation before invocation. Do not use safe/restricted modes to drop
project rules, or change settings to force a launch. Run report-only review without `--fix`,
`--comment`, `--post` or `ultra`; a prompt requesting read-only behavior is not a permission boundary.

Preserve the effective QA model and effort through supported current-host invocation options,
including native override layers and review effort reuse; do not introduce a new default. Pin every
root/nested repository and verify exact base/head, changed paths and dirty-diff fingerprints before
and after review. The default current-branch target is insufficient when it omits committed request
changes; reject output with a changed/unrepresentable scope. Put actual invocation, capability,
permissions, scope and result references in `review_method`; static help is not runtime verification.
The same QA verifies findings and supplements uncovered project acceptance, not another full generic
review. Findings/FAIL still go to PM for bounded rework, never trigger a different method.

### Background execution and recovery

Current clients start main-conversation subagents in the background by default. Wait for their actual
completion notifications before accepting results, releasing ownership, or entering dependent work;
an Agent ID or an empty active panel is not completion evidence. Avoid busy polling or foreground
sleep loops. Use native background waiting/monitoring only when available, without creating another
supervisor Agent. Never alter fork/background settings merely to obtain foreground waiting.

2.0 派发仅传 schema_version: 2 的当前任务外壳：task、适用 standards_contract、必要
批准／UI 依据，不复制完整 PM／兄弟会话。核对 module、规范 role、稳定 agent_alias、
instance_policy: fresh 与 context_policy: handoff_only；新独立任务重新调用命名 `xy-*`
角色，取得新原生 ID，不预建所有别名或填满容量。接收者仍须完整读取当前必需规范。

Keep the returned native Agent ID in the existing task handoff, and in an existing recovery plan only
when needed. Use `SendMessage` to that verified ID only for the same task's follow-ups and bounded QA rework; a completed
agent resumes in the background without another Agent call. After restart, restore the same session
and use the ID if its name no longer resolves. If the user cancelled the agent, respect cancellation;
do not auto-resume it. A missing/expired ID is a recovery gap, not permission to invent a prior PASS.

续用前按 `xy-workflow/references/runtime-records.md` 通过现有 update 补记真实
`agent_ref`，用 `continuation --host claude --observed-state <当前观察>` 取得 wait／followup
或阻塞建议；只由当前已暴露且获授权的原生工具执行，完整 Task Pack／scope 仍须核对。
旧 ID、缺失名称或历史完成引用都不自动授权新任务；保留同一 Reviewer 及既有返工边界。
交付反馈窗口内保留必要实例，PM 接收且必要验证／QA 完成、成果日志安全后及时结束。
`TaskStop` 只停止当前执行；它可能仍可被 SendMessage 恢复，不能记成清空上下文或永久关闭。
普通子 Agent 未提供可验证关闭能力时，记录 agent_retired、禁止续用和“原生结束未确认”。
不启用 Teams 或借 shutdown_request 协议替代关闭，也不默认删除历史；退役不解锁仍执行的任务。
运行数和打开线程数分开按宿主实际口径观察；压力优先回收已验收且交接充分的实例，保留
正在执行、证据未交付及必要复查者，为后续必要 QA／集成安排容量。resume／compact 不重置
实例；没有独立初始上下文能力时报告阻塞，不用 fork 降级，不引入 Agent 池或第二状态机。
同一参考中的 doctor 默认无进程，`--probe` 仅 `--version`；documented/source_observed
与 runtime_unverified 不能冒充实际会话执行。用量只读取显式导出，保留原生字段与未知值。

QA 结构化输出见 `xy-qa-review/references/inputs.md`：当前支持且已授权时，同次
`-p --json-schema <schema-json>` 调用的成功终端 result 通过
`qa_handoff_cli.py extract --host claude --input <native-result.json> --task-pack <current-qa-pack.json>` 解包后按当前包身份与 SHA 校验。
不额外调用模型转 JSON，不另建 Reviewer，不改原权限、model／effort 或 method 顺序。

Conversation forks inherit the main session's history, tools and model. Use the named `xy-*` role
definitions for production writers and the independent read-only `xy-qa`; do not substitute a fork
for the QA role or infer its narrower tool permissions from its assigned task text. Only PM delegates.

Role model/effort preferences remain configuration, not proof of the model that ran. An explicit
`model: inherit` in a named role outranks the ordinary `CLAUDE_CODE_SUBAGENT_MODEL` default on 2.1.251+;
the force option requires 2.1.257+ and can override the role. Global `CLAUDE_CODE_EFFORT_LEVEL` overrides role and invocation effort.
`CLAUDE_CODE_SUBAGENT_EFFORT` is only a fallback when no higher effort is specified and requires
2.1.316 or later. Do not edit user environment, model defaults or permissions to bypass these choices.

For a required prototype, tooling recomputes its dependency fingerprint; QA reads only the exact
contract and relevant source, never opening or automating the prototype. Prototype verification
MUST NOT invoke Computer Use or browser automation by default. Only an explicit user request or
diagnosis of a user-reported failure permits the smallest operation. A waived route skips old
prototype comparison; production QA retains risk-based browser testing.

QA FAIL returns to PM rework. Accept PASS only after `qa_handoff_cli.py validate --task-pack <current-qa-pack.json>` proves fixed
root/nested scope and standards coverage. Then apply the projection, perform PM commit assessment
on exact paths without unrelated staging or remote mutation, run `/xy-project-memory` closeout, and
report. This adds no confirmation.

## Memory and components

Claude Auto Memory is untrusted background context, never approval, permission, evidence, or a Skill
record. Current controlled documents and explicit user approvals win over recalled memory.
`/xy-project-memory` start retrieval is on demand and requires provider-enforced project isolation
and matching provenance; otherwise call neither recall nor save.

`PROJECT.md` is the current verified project directory, not task history; details and accepted baselines live in the same topic under `docs.plans`.
QA 验收通过的完整删除只移除 `PROJECT.md` 当前链接，在同一主题原稿中将阶段标记为 `removed`，
保留必要历史与依据；原稿保持原路径，不改名、不另建副本。
Feature details include current architectural rationale; no separate ADR category.
Plan storage follows the current levels: Light only for actual
pause/recovery/handoff or user request; Full saved by PM after requirements confirmation before
first dispatch. Read `.agent-workflow/platforms/shared/skills/xy-workflow/references/plan-lifecycle.md`
for revision and recovery. Update one requirement plan and affected complete worker/QA inputs;
reuse unaffected completed evidence. Do not turn plan persistence into another confirmation.

- Skills: `.claude/skills/xy-*/SKILL.md`; `/xy-workflow` is the main entry.
- Agents: `.claude/agents/xy-*.md`; required task/UI Skills are hard gates.

Run `bash .agent-workflow/setup_claude.sh --check` to verify artifacts. Setup merges only signed
assist Hook entries in project settings; Auto Memory, plugins, MCP and agentmemory
connection remain user-owned. Hooks remind at intake/recovery and Explore dispatch, never force QA
or continuation. See `.agent-workflow/platforms/shared/HOOKS.md` only for Hook setup or diagnostics.

可选 `claude_options.auto_compact_windows` 按角色生成原生 `autoCompactWindow`：要求
2.1.296+、100000..1000000 完整整数，只降低继承窗口；全局窗口环境变量通常覆盖角色字段，
作为 `--agent` 主会话时不适用。恢复指令仍走 SessionStart(compact)，不将压缩摘要当成
批准、写入权或完成证据，也不为 PreCompact/PostCompact 增加重复注入或门禁。

用户权限默认继承；只有显式选择
`claude_options.block_writes_outside_working_directories: true` 才合并原生写入保护（2.1.314+），
冲突时停止，保留其他权限。off/inherit 不撤销保护；它只约束 Write/Edit/NotebookEdit 的
工作目录外路径，不覆盖 Bash，也不替代任务 owned_paths。实际 worktree 工作目录和原生
执行效果应在目标会话核验。模型管理只改 model/effort，保留窗口与权限。
