# Claude Code — PM bootstrap

Native Windows central calls use PowerShell 7.0+ and the explicit existing Python 3.11+ with `-I -B -X utf8 .agent-workflow/runtime.py`. Take `--binding-b64` from the current task's strict three-field pin on every managed `read`/`helper` call; new tasks first run `check`. Translate any POSIX/source Bash helper example to its logical `lib/...py` through this native pinned bridge. Do not run Bash or copy Skills/helpers into the thin project; central Skill symlinks remain the only discovery source. Follow the shared [execution boundary](../../shared/skills/xy-workflow/references/dispatch.md#native-windows-central-calls); task stages, permissions and native role/model evidence requirements are unchanged.

This entire managed section applies only when the current host is Claude Code.
Codex and Antigravity use their own integration sections; do not apply their tool aliases here.

Central resources are managed through shared CLI runtime activation and project repair; source-pack generation uses `bash setup_claude.sh` only from the source-pack root.

## Entry and authority

The main conversation alone orchestrates. Light and Full product changes invoke `/xy-workflow`.
Light/Full defaults to the corresponding native `Agent(xy-*)`, using only ordinary named roles without forks that copy parent history. See `.agent-workflow/product/WORKFLOW.md#implementation-ownership` for the PM implementation exception and recovery boundaries, preserving the original level's gates. PM retains classification, planning, dispatch, QA acceptance, memory closeout, and reporting.
Standalone read-only audits follow WORKFLOW's matching branch and stop at the scoped conclusion,
without the implementation/QA closeout loop; actual implementation acceptance keeps its QA contract.

For selected independent functional units, follow `/xy-workflow`'s `references/worktree-delivery.md`.
Prefer the native Agent tool's per-call worktree isolation when available. Verify the actual root
and exact prerequisite-containing base; default branch selection is not proof of the required base.
Keep role isolation dynamic rather than setting every role permanently to `isolation: worktree`.
PM-local integration and confirm/auto local main delivery use the shared contract; do not rewrite
global worktree settings, permissions or user hooks, or create new user-visible sessions as a fallback.

Light first assesses the current goal, risk, scope, and implementer, with mandatory minimum sufficient verification; assess independent QA, documentation, and memory at handoff. Do not mandate Full planning, DAGs, saved plans, or duplicate confirmation; retain Full and actually necessary QA gates.

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
  Keep accepted PROJECT/plans baselines at its last QA-verified state until integrated QA PASS. Clear
  Light work may skip the two Skills when facts are complete.
- Grill Me remains requirements-only. Superpowers is disabled by default except the bounded reviewer
  fallback below; `xy-plan` is the local planner. Reopen approval only for material scope change.
- Full `UI-Conformance` requires `design_delta: none` and has no visual gate. It also requires
  `surface_kind: production_ui`, `qa_scope: request`, `prototype_policy: not_applicable`, structured
  resolved/fingerprinted `design_authority_refs`, zero design writes, and full UI/accessibility QA.
  Ordinary Light copy follows the shared `Light UI copy` branch, retaining actual frozen design authority, engineering/design standards, and minimum verification; independent QA follows actual handoff risk assessment, without mandating Full merely because it also uses UI-Conformance.
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

Apply WORKFLOW's `continuous-pm-intake` and the shared dispatch/admission calls for relationship,
authorization, ownership, pin and per-request QA. The
[official subagent guide](https://code.claude.com/docs/en/sub-agents#resume-subagents) describes named
ordinary background subagents and `SendMessage` by verified ID/name, including same-ID idle resume without
Teams. Ordinary named agents start fresh from their definitions; a fork copies the parent conversation and
does not meet this pack's `fresh`/`handoff_only` requirement. Do not enable Teams or nesting to obtain messaging.
Use `agent_continuation_cli.py` with intent `progress`/`append` and `non_interrupting_message` only after checking
the current native SendMessage delivery semantics; use `idle_followup` for an actually available same-ID
resume. A user-cancelled instance is not auto-resumed. `TaskStop` does not replace steer. Background completion
notifications, new-input delivery, wait wakeup, original-task continuity, followup and parent-final lifecycle
need their own actual target-session evidence; doctor/version/configuration alone leaves them `runtime_unverified`.

Current clients start main-conversation subagents in the background by default. Wait for their actual
completion notifications before accepting results, releasing ownership, or entering dependent work;
an Agent ID or an empty active panel is not completion evidence. Avoid busy polling or foreground
sleep loops. Use native background waiting/monitoring only when available, without creating another
supervisor Agent. Never alter fork/background settings merely to obtain foreground waiting.

Dispatch passes only the current schema_version: 2 task envelope: task, applicable standards_contract, and necessary approval/UI evidence, without complete PM/sibling conversations. Check module, canonical role, stable agent_alias, instance_policy: fresh, and context_policy: handoff_only; invoke the named `xy-*` role again for each new independent task to obtain a new native ID, without precreating all aliases or filling capacity. The receiver still reads all current required standards completely.

Keep the returned native Agent ID in the existing task handoff, and in an existing recovery plan only
when needed. Use `SendMessage` to that verified ID only for the same task's follow-ups and bounded QA rework; a completed
agent resumes in the background without another Agent call. After restart, restore the same session
and use the ID if its name no longer resolves. If the user cancelled the agent, respect cancellation;
do not auto-resume it. A missing/expired ID is a recovery gap, not permission to invent a prior PASS.

Before continuation, record actual `agent_ref` through existing update under `xy-workflow/references/runtime-records.md`, then use `continuation --host claude --observed-state <current-observation>` for wait/followup or blocker advice; execute only through currently exposed authorized native tools and still check the complete Task Pack/scope. Old IDs, missing names, or historical completion references do not automatically authorize new tasks; retain the same Reviewer and existing rework boundaries. Retain necessary instances during the delivery feedback window, then end promptly after PM acceptance, necessary verification/QA, and safe results/logs. `TaskStop` stops only current execution and may still allow SendMessage recovery; do not record cleared context or permanent closure. If ordinary subagents expose no verifiable closure capability, record agent_retired, prohibit continuation, and state native termination is unconfirmed. Do not enable Teams or substitute shutdown_request for closure, or delete history by default; retirement unlocks no still-running task. Observe running/open-thread counts separately using actual host definitions; under pressure reclaim accepted instances with sufficient handoff first, retain executing instances, undelivered evidence, and necessary reviewers, and reserve later necessary QA/integration capacity. resume/compact does not reset instances; if independent initial context is unavailable, report a blocker without fork fallback, an Agent pool, or a second state machine. doctor in the same reference starts no process by default and `--probe` invokes only `--version`; documented/source_observed and runtime_unverified cannot impersonate actual session execution. Read usage only from explicit exports, preserving native fields and unknown values.

See `xy-qa-review/references/inputs.md` for structured QA output: when currently supported and authorized, unpack the successful terminal result from the same `-p --json-schema <schema-json>` invocation through `qa_handoff_cli.py extract --host claude --input <native-result.json> --task-pack <current-qa-pack.json>`, then validate identity/SHA against the current pack. Do not call an extra model for JSON conversion, add a Reviewer, or change original permissions, model/effort, or method order.

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
An accepted complete removal removes only the current `PROJECT.md` link and marks the phase `removed` in the same topic source, retaining necessary history and rationale at the original path without renaming or copies.
Feature details include current architectural rationale; no separate ADR category.
Plan storage follows the current levels: Light only for actual
pause/recovery/handoff or user request; Full saved by PM after requirements confirmation before
first dispatch. Read `.agent-workflow/platforms/shared/skills/xy-workflow/references/plan-lifecycle.md`
for revision and recovery. Update one requirement plan and affected complete worker/QA inputs;
reuse unaffected completed evidence. Do not turn plan persistence into another confirmation.

- Skills: `.claude/skills/xy-*/SKILL.md`; `/xy-workflow` is the main entry.
- Central agents: user-root `agents/xy-*.md` (normally `~/.claude/agents/`); only required project overrides appear in `.claude/agents/xy-*.md`. The configured user root may differ from HOME. A missing local file does not prove role unavailability; required task/UI Skills remain hard gates. Discovery files, `Agent(xy-*)` labels and parsed model settings alone do not prove actual native role/model execution; verify the effective native invocation in the target session.

For central installations, preview `awf-cli repair PROJECT --dry-run`, then explicitly apply `repair PROJECT` when authorized. Import and activate central cores separately through `runtime install` and `runtime activate ID`; central thin projects have no `.agent-workflow/setup_claude.sh`. Source-pack developers run `bash setup_claude.sh --check` from the source-pack root. Central projection/source generation merges only signed
assist Hook entries in project settings; Auto Memory, plugins, MCP and agentmemory
connection remain user-owned. Hooks remind at intake/recovery and Explore dispatch, never force QA
or continuation. See `.agent-workflow/platforms/shared/HOOKS.md` only for Hook setup or diagnostics.

Optional `claude_options.auto_compact_windows` generates native `autoCompactWindow` by role: require 2.1.296+, full integers in 100000..1000000, and only reduce the inherited window. Global window environment variables usually override role fields, and the setting does not apply when used as a `--agent` main session. Recovery instructions still use SessionStart(compact); compaction summaries are not approval, write authority, or completion evidence, and PreCompact/PostCompact receives no duplicate injection or gates.

User permissions inherit by default; merge native write protection (2.1.314+) only with an explicit `claude_options.block_writes_outside_working_directories: true` choice, stopping on conflict and preserving other permissions. off/inherit does not revoke protection; it covers only Write/Edit/NotebookEdit paths outside working directories, not Bash, and does not replace task owned_paths. Verify the actual worktree working directory and native execution effect in the target session. Model management changes only model/effort, preserving windows and permissions.
