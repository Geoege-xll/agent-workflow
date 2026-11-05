## Antigravity native PM delta

This entire managed section applies only in Antigravity; ignore other hosts' integration sections.

Standalone read-only audits follow WORKFLOW's matching branch and stop at the scoped conclusion,
without the implementation/QA closeout loop; actual implementation acceptance keeps its QA contract.

Use `/xy-workflow` for Light and Full implementation; roles are `.agents/agents/xy-*.md`, Skills are
`.agents/skills/xy-*/SKILL.md`. Only the PM may use `invoke_subagent`; role Agents never delegate and
`max_depth` is `1`. Light/Full defaults to the corresponding subagent; see `.agent-workflow/product/WORKFLOW.md#implementation-ownership` for the PM implementation exception and recovery boundaries, preserving the original level's gates.
For Full READY tasks: `inherit` stays `inherit`, `worktree` becomes `branch`
only when the actual runtime proves a distinct registered worktree root and the required base;
`share` is forbidden. A branch name alone is not filesystem isolation. For multi-feature selection,
integration and confirm/auto local main delivery, read `/xy-workflow`'s `references/worktree-delivery.md`.
If isolated tool binding is unavailable, report it and retain safe ownership-based scheduling;
never emulate isolation by concurrently switching branches in one directory or overwriting host settings.

Light first assesses the current goal, risk, scope, and implementer, dispatching the corresponding native role subagent by default with mandatory minimum sufficient verification; assess independent QA, documentation, and memory at handoff without mandatory Full planning, DAG, saved plans, or duplicate confirmation.

Full: classify → facts → Grill Me → `xy-plan` draft → projection decision →
`requirements_approved`; Grill Me remains requirements-only. For design-change UI, include the PM
recommendation and prototype choice in that confirmation; freeze truth until QA PASS.
Full work records the Grill Me coverage check and `plan_state: draft`; the pre-approval projection
decision remains a draft, while post-QA controlled-document projection happens only after QA PASS.
PM saves the approved Full plan in `docs.plans` before first design/implementation dispatch.
Light saves only for actual pause/recovery/handoff or user request.
For revisions/recovery follow `/xy-workflow`'s `references/plan-lifecycle.md`: one requirement, one
current plan; replace affected complete worker/QA inputs and reuse unaffected verified work.
Feature details include current architectural rationale, with no separate ADR category.
`UI-Conformance` uses `prototype_policy: not_applicable`, resolved/fingerprinted
`design_authority_refs`, `surface_kind: production_ui`, `qa_scope: request`, no `xy-uiux`, and no
visual gate. Changed routes require a scope-bound `prototype_decision` from
`requirements_confirmation_user_choice`: `required` adds `xy-uiux` and a dependency fingerprint
page Gate `visual_approved`; `waived_by_user` adds no prototype-design dependency, prototype write, or visual
gate. The PM must not default either choice; full UI/accessibility QA remains. Platform security
prompts remain separate.

For initial/revised standards or full visual replacement, read `/xy-workflow`'s
`references/design-standards.md`. PM assesses/adopts scope separately from feature documentation;
UI Agent writes authorized leaves. `design_mode: standards_only` may precede waived production,
without prototype files, verification or visual gates. PM refreshes affected authority before use.

Prototype verification MUST NOT invoke Computer Use or `/browser` by default. Use `/browser` only
when the user explicitly requests prototype automation or reports a concrete failure needing the
smallest diagnostic operation. Production QA may still use risk-based browser testing. No rendered
frame may be persisted or used as approval evidence.

Current controlled documents and explicit user approvals win over recalled memory. Without strict
isolation or provenance, call neither recall nor save. For Full or Light assessed as requiring independent QA, at BUILD_VERIFIED dispatch exactly one
integrated, read-only `xy-qa`. Waived work skips old-prototype comparison.

The reviewer tries `host-native-review`, then one `installed-code-review-skill` proven installed and
capable, then `internal-xy-qa-procedure`, moving forward only on technical unavailability. The sole
Superpowers option is `requesting-code-review/code-reviewer.md`. Findings or `FAIL` never switch
review method or reviewer.

Final QA outcome: PASS | FAIL. Require `qa_handoff_cli.py validate --task-pack <current-qa-pack.json>`. Completion: QA PASS → projection
→ PM commit assessment → memory closeout via `/xy-project-memory` → final user report. Setup owns
marked artifacts and one signed, named assist Hook in `.agents/hooks.json`; other host settings,
MCP, plugins, permissions, Agent mode and Artifact review policy stay unchanged. The Hook reminds
at native SessionStart, not on every model invocation, and creates no temporary deduplication markers.
It does not infer user turns or context recovery from invocation counters or user message content.
The actual client must support and execute SessionStart; generated configuration alone is not proof.
See `.agent-workflow/platforms/shared/HOOKS.md`
only for Hook setup or diagnostics.

## Native Tool Short Path

2.0 dispatches only current schema_version: 2 single-task packs: task, applicable standards_contract, and necessary approval/UI evidence. Stable agent_alias binds project-relative module and canonical role; instance_policy: fresh and context_policy: handoff_only forbid complete PM/sibling history copies. Invoke invoke_subagent on demand for each independent task, obtaining a new ID with a self-contained current-task initial Prompt; still read required current files and standards completely. If native independent initial context cannot be proven, report a blocker without falling back to a parent-history fork, precreating instances, or filling platform capacity.

Continuous same-task implementation, recent short rework, and same-round Reviewer delta checks may follow up to the original ID. After the feedback window, PM acceptance, and necessary verification/QA, first protect temporary-worktree results, unique logs, and necessary evidence, then use the currently exposed authorized native termination capability. Official kill removes temporary worktrees and prevents recovery while retaining historical transcripts; never kill before retrieving the only delivery, or claim permanent history deletion. Without native capabilities such as manage_subagents kill, or if invocation fails, only record agent_retired and prohibit continuation, with native termination unconfirmed; do not claim destruction, context clearing, or thread-capacity release. Retirement releases no still-running task locks. Observe running/open-thread counts separately under actual host definitions; under pressure reclaim accepted instances with sufficient handoff first, retain executing instances, undelivered evidence, and necessary reviewers, and reserve later necessary QA/integration capacity. resume/compact is not prepareForReuse; create no Agent pool, runner, daemon, or second state machine.

Use doctor, usage, and continuation paths in `xy-workflow/references/runtime-records.md` as needed. doctor starts no process by default; `--probe` invokes only `--version`, never `/skills`. Its documented/source_observed/runtime_unverified distinguishes documentation, explicit project provenance, and unverified runtime. A declaration/SHA for `.agents/skills/grill-me/SKILL.md` and same_name_risk=possible cannot prove current `/grill-me` actual_source (still unknown). Verify actual paths and instructions in the target host before use; native `/grill-me` does not automatically replace this pack's Full requirements coverage check or change aliases.

PM records the actual `invoke_subagent` result ID as `agent_ref` through existing update and queries `continuation --host antigravity --observed-state <current-observation>`; only currently exposed authorized native follow-up/wait tools may execute its advice. Cancelled, unknown, invalid, or cross-host states block automatic continuation; still hand off the complete Task Pack/scope. Retirement prohibits continuation; absent capabilities do not justify a custom runner, daemon, MCP, or replacement Reviewer. AGY native cumulative usage retains an unknown initial baseline, last_cumulative, and observed_delta rather than summing each record.

See `xy-qa-review/references/inputs.md` for structured QA output: when supported, use `--json-schema <schema-json>` in the same authorized invocation, then `qa_handoff_cli.py extract --host antigravity --input <native-result.json> --task-pack <current-qa-pack.json>`. Missing optional usage is not a QA gate. Human diff/Artifact review must not impersonate native AI review or independent AI QA; do not automatically enable native, boost, or teamwork modes, or adjust existing Artifact policy, permissions, or model/effort to enable invocation.
