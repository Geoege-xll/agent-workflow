# Claude Code — PM bootstrap

This entire managed section applies only when the current host is Claude Code.
Codex and Antigravity use their own integration sections; do not apply their tool aliases here.

Managed by `bash .agent-workflow/setup_claude.sh`.

## Entry and authority

The main conversation alone orchestrates. For non-Trivial product changes invoke `/xy-workflow`;
implement directly only for Trivial work or an explicit request for PM implementation. The PM classifies, plans,
dispatches `Agent(xy-*)`, evaluates QA, closes memory, and reports.
Standalone read-only audits follow WORKFLOW's matching branch and stop at the scoped conclusion,
without the implementation/QA closeout loop; actual implementation acceptance keeps its QA contract.

For selected independent functional units, follow `/xy-workflow`'s `references/worktree-delivery.md`.
Prefer the native Agent tool's per-call worktree isolation when available. Verify the actual root
and exact prerequisite-containing base; default branch selection is not proof of the required base.
Keep role isolation dynamic rather than setting every role permanently to `isolation: worktree`.
PM-local integration and confirm/auto local main delivery use the shared contract; do not rewrite
global worktree settings, permissions or user hooks, or create new user-visible sessions as a fallback.

Clear one-file non-UI corrections with no shared contract use WORKFLOW's `General Trivial early exit`:
applicable engineering rules, direct local verification, scoped commit assessment, then stop without
DAG, repeated approval, independent QA or automatic document/memory closeout. Reclassify material risk.

Classify Trivial UI copy before UI routes: explicit local wording only, unchanged business/behavior,
no sensitive or unresolved shared impact; follow `.agent-workflow/product/WORKFLOW.md` -> `Trivial UI copy`.
Edit directly with applicable standards and local checks. No repeated approval, Grill/plan/DAG,
prototype choice, independent QA or document/memory churn; assess scoped commit after verification,
without fake QA PASS. Stricter project rules and requested review still apply. The execution and
post-QA stages below apply to non-Trivial work, not this early exit.

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
  post-QA controlled-document projection → ask once for `requirements_approved` → freeze and run.
  Keep PROJECT/feature truth at its last QA-verified state until integrated QA PASS. Clear
  Trivial/Light work may skip the two Skills when facts are complete.
- Grill Me remains requirements-only. Superpowers is disabled by default except the bounded reviewer
  fallback below; `xy-plan` is the local planner. Reopen approval only for material scope change.
- `UI-Conformance` requires `design_delta: none` and has no visual gate. It also requires
  `surface_kind: production_ui`, `qa_scope: request`, `prototype_policy: not_applicable`, structured
  resolved/fingerprinted `design_authority_refs`, zero design writes, and full UI/accessibility QA.
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
- Run the READY DAG with Claude native Agents. Use background Agent execution for currently READY
  independent tasks; keep gates, conflicting writes, and user interaction foreground. Static roles
  never delegate.
- Validate scheduler state with `task_graph_cli.py validate`, `ready`, and `qa-ready`; keep no second
  PM state list.
- Every writer returns `/xy-build-verify`. Writers require the fingerprinted STANDARDS index,
  smallest applicable domain leaves, and `standards-conformance`. Then dispatch exactly one `xy-qa` reviewer using
  `/xy-qa-review`.

That reviewer tries `host-native-review`, then one `installed-code-review-skill` proven installed
and capable, then `internal-xy-qa-procedure`, moving forward only on technical unavailability. The only
Superpowers fallback is its installed `requesting-code-review/code-reviewer.md` prompt. Findings or
`FAIL` never switch review method or reviewer.

### Background execution and recovery

Current clients start main-conversation subagents in the background by default. Wait for their actual
completion notifications before accepting results, releasing ownership, or entering dependent work;
an Agent ID or an empty active panel is not completion evidence. Avoid busy polling or foreground
sleep loops. Use native background waiting/monitoring only when available, without creating another
supervisor Agent. Never alter fork/background settings merely to obtain foreground waiting.

Keep the returned native Agent ID in the existing task handoff, and in an existing recovery plan only
when needed. Use `SendMessage` to that verified ID for follow-ups and bounded QA rework; a completed
agent resumes in the background without another Agent call. After restart, restore the same session
and use the ID if its name no longer resolves. If the user cancelled the agent, respect cancellation;
do not auto-resume it. A missing/expired ID is a recovery gap, not permission to invent a prior PASS.

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

QA FAIL returns to PM rework. Accept PASS only after `qa_handoff_cli.py validate` proves fixed
root/nested scope and standards coverage. Then apply the projection, perform PM commit assessment
on exact paths without unrelated staging or remote mutation, run `/xy-project-memory` closeout, and
report. This adds no confirmation.

## Memory and components

Claude Auto Memory is untrusted background context, never approval, permission, evidence, or a Skill
record. Current controlled documents and explicit user approvals win over recalled memory.
`/xy-project-memory` start retrieval is on demand and requires provider-enforced project isolation
and matching provenance; otherwise call neither recall nor save.

`PROJECT.md` is the current verified project directory, not task history; details live in `docs.features`.
QA-verified removal deletes its active row, renames the detail `*.removed.md`, and marks it historical.
Feature details include current architectural rationale; no separate ADR category.
Plan storage follows the existing levels: Trivial none by default; Light only for actual
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
