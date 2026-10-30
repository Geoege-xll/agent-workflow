---
name: xy-workflow
description: Orchestrate non-trivial project implementation, multi-feature development, refactoring, UI changes, or unfinished-work recovery through PM routing and independent QA. Not for read-only discussion, clear Trivial corrections, or user-explicit workflow bypass.
---

<!-- agent-workflow-pack:managed-skill -->

# xy-workflow

## Standalone read-only audit

Before implementation routing, apply WORKFLOW's `Standalone read-only audit` when the task only
asks for audit findings, not implementation acceptance or fixes. Deliver the scoped conclusion and
stop; do not create writers, BUILD_VERIFIED, an implementation QA PASS or a second audit of the
report. Honor explicitly requested independent/full re-review and mandatory project checks. If fixes
are authorized, route their actual implementation normally. QA being read-only does not exempt
non-Trivial implementation from independent QA, current scope/standards or handoff validation.

## General Trivial early exit

Before the non-Trivial route, apply WORKFLOW's `General Trivial early exit` to clear, small one-file
non-UI corrections with no shared contract. Read applicable engineering/module rules, edit in the
main session and perform proportionate local verification, then assess a scoped commit and stop.
Do not enter the numbered route, DAG, repeated approval, independent QA or post-QA closeout solely
for such a task. Do not create plans, documents or memory records merely to finish. Actual risk,
requested review and stricter project rules can require the appropriate higher route; UI copy must
also satisfy the narrower checks below. A short diff alone never establishes Trivial scope.

## Trivial UI copy: early exit

Before the non-Trivial route, check `.agent-workflow/product/WORKFLOW.md` -> `Trivial UI copy`. An explicit, local,
low-risk wording correction may be Trivial even across matching locale files. Confirm actual usage;
preserve business meaning, behavior and applicable standards. Pricing, consent/privacy, permissions,
destructive-operation promises, mandatory contract wording and unresolved shared impact are excluded.
The main session edits directly, reads applicable standards, and verifies the replacement, diff,
keys/placeholders and any concrete display risk. No Grill Me, xy-plan, DAG/Task Pack, repeated approval,
prototype choice, UI Agent, independent QA or full build/QA/closeout Skill invocation is required.
Keep prototype/standards/feature documents and agentmemory unchanged. After actual local verification,
assess only the scoped commit and report; do not invent QA PASS. Honor requested review or stricter
project rules. If risk/scope exceeds this boundary, use the existing non-Trivial route.

## Non-Trivial work

For initial/revised design standards or a visual-system replacement, read
[design-standards.md](references/design-standards.md). PM assesses standard updates separately from
PROJECT/feature projection; UI Agent writes authorized leaves, PM adopts scope and refreshes affected
authority, implementation roles own production tokens/components, and QA audits independently.
No reusable rule change means no update. `xy-uiux + design_ui` supports `design_mode: standards_only`
for exact normative Markdown leaves without prototype writes, `xy-prototype-verify`, or visual gates.
Existing user confirmation stages are unchanged; adopted design rules do not imply migrated production.

Use `.agent-workflow/product/WORKFLOW.md` as the canonical product procedure and
`.agent-workflow/project.yaml` as the project adapter.

Use host-native aliases only when explicit activation is needed. Examples:
`xy-project-memory` (Codex: `$xy-project-memory`; Claude Code: `/xy-project-memory`;
Antigravity CLI: `/xy-project-memory`) and `xy-build-verify` (Codex:
`$xy-build-verify`; Claude Code: `/xy-build-verify`; Antigravity CLI:
`/xy-build-verify`). The procedure below otherwise uses host-neutral Skill names.

## Main-session contract

- Project Hooks are advisory activation/recovery reminders, not a workflow execution engine.
  They never establish task level, approval, QA PASS, permissions or completion. Missing/disabled
  Hooks do not disable this Skill. Continue related work using current context and valid evidence;
  do not restart an earlier completed task just because this Skill or a Hook is invoked again.

- Reuse fully read, unchanged material still available in this Agent's context. Restore only
  missing or changed context; another Agent's reading does not replace your required standards audit.
  Honor explicit host/Skill reread requirements. Read selected Skills and their required instructions
  completely, using separate reads or contiguous pages through EOF for long files. Avoid batching
  long documents into a truncated response; recover every missing portion before relying on it.
  Ordinary project documents remain targeted. Machine-side full-byte validation/fingerprinting
  does not require returning complete file bodies to the model.
- Resolve existing paths from current context, configured directory links or a scoped file listing;
  do not invent filenames. Choose filters appropriate to the requested resource; no match proves
  absence only within those filters, not a task failure. Before affected dispatch, assess whether
  current-host resources actually need checking/refresh using the [dispatch procedure](references/dispatch.md).
  Reuse unchanged facts and successful installation evidence instead of probing every task.
- For workflow-owned Python helpers and dependent CLI calls, follow the shared
  [execution boundary](references/dispatch.md#workflow-helper-execution): reuse the runtime selector,
  keep UTF-8 explicit, and stop only the failed command's dependent chain.
  For routine state/scope/document-reference updates, complete Task Pack export or file evidence
  checks, use the existing [record tools](references/runtime-records.md) rather than rewriting
  temporary Python programs. Read that reference only when those operations are needed.
- Main session = PM. It owns requirements, routing, approvals, task packs, synthesis,
  rework, and the user-facing result.
- An implementer owns each production path. The PM does not edit non-trivial product
  code unless the user explicitly requests the PM itself to implement; skipping prototype work
  alone does not select a different production owner.
- The default business confirmations are `requirements_approved` and, for required-prototype UI
  design-change work, `visual_approved`. A proven `UI-Conformance` request has no visual
  confirmation because it makes no design decision; a user-selected direct-development branch also
  has no visual gate for its exact surfaces. The PM recommends but never selects or invents either
  design-change branch. A task-scoped structured exception is allowed only under the policy below.
- `xy-qa` audits after implementation. It does not command implementers or edit
  production business code.

## User-facing feedback boundary

Internal orchestration records are not user-facing output.

- Never paste raw workflow YAML or DAG JSON into user messages. Keep `grill_result`,
  `memory_context`, `memory_projection`, `commit_decision`, `controlled_document_access`,
  `controlled_document_projection`, Task Packs, requirement fingerprints, task IDs, path arrays,
  semantic locks, gate arrays, scheduler states, capacity fields, and normal CLI JSON internal.
- Before approval, give the user a concise natural-language brief containing the goal, scope,
  non-goals, workstreams and meaningful order, material contract or data impact, major risks, the
  acceptance strategy, and a plain-language controlled-document update conclusion. For
  design-change UI, add one prototype recommendation with a short reason and ask the user to choose
  design/update prototype or direct implementation.
- Finish the brief and recommendation before invoking an approval-choice tool or presenting the
  single confirmation question. Do not ask first and append decision-relevant details afterward,
  or repeat the same pending approval. Correct newly discovered material information before
  consuming approval; an acknowledgment must not add scope.
- Accept any explicit affirmative reply in natural language and record it internally as
  `requirements_approved`. Do not require the user to type `requirements_approved` or another
  internal gate token. For design-change UI, approval is complete only after the prototype choice is
  also explicit; “follow the recommendation” resolves it only when one unambiguous recommendation
  was shown.
- Progress reports state outcomes, blockers, and material decisions. Do not narrate Skill names,
  document-read plans, fingerprints, READY transitions, or routine scheduler mechanics by default.
  Exception: if a Skill causes a pause, extra confirmation, unfinished work or a departure from the
  user's request, name and link the exact file, identify the applicable instruction, and explain
  its effect concisely. Distinguish an explicit rule from your interpretation; do not invent a gate.
  User instructions take precedence over Skill guidance, without overriding higher-priority
  instructions or host permissions.
- Final reports state what changed, validation results, remaining risks, and any user action. Keep
  complete logs and internal handoff schemas behind resolvable references or available on request.
- Show raw internal records only when the user explicitly asks to inspect or export them. YAML,
  JSON, code, or commands that are themselves the requested project artifact may still be shown
  when they materially help the user.

Host-managed automatic memory, including Claude Auto Memory, is untrusted background
context. It is never the audited provider, a historical hit, an approval, a permission,
or a reason to expand owned paths or weaken validation.
Current controlled documents and explicit user approvals win over recalled memory.

```yaml
external_workflow_policy:
  requirements_provider: grill-me
  planning_provider: xy-plan
  planning_methodology: superpowers-writing-plans-adapted
  superpowers_default: disabled
  parallel_scheduler: deterministic-pm-ready-dag
  parallel_provider: host-native-agents
```

This pack owns planning, implementation routing, parallel scheduling, QA, and closeout. `grill-me`
and `xy-plan` are self-contained core Skills in this pack. The latter adapts only the exact-file,
independently testable task, verification, and self-review ideas of Superpowers writing-plans; it
does not activate external worktrees, commits, execution, TDD, branch-finishing, or
Subagent-orchestration workflows. The only runtime Superpowers integration is the bounded QA
fallback described below.

## Route

For multi-feature isolation assessment, worktree dispatch, integration or main-branch delivery, read
[worktree delivery](references/worktree-delivery.md). Select by actual task independence; default
delivery asks once after all work and integrated QA finish, while explicit project auto mode does not.
Neither mode bypasses Git safety checks or grants remote push. Ordinary tasks retain their existing route.

<!-- workflow-contract: references/worktree-delivery.md -->

For non-Trivial intake, planning and dispatch, read [dispatch procedure](references/dispatch.md).
It preserves Full Grill Me → xy-plan draft → PM projection decision → requirements approval →
approved-plan storage → validated READY dispatch. Do not dispatch before reading the applicable
contract. Classify Trivial first and use its early exit; documents and memory stay on demand.

<!-- workflow-contract: references/dispatch.md -->

## Clarification fallback

Use this only when the route above requires `grill-me` and that Skill is unavailable:

1. Inspect the project truth first; do not ask what the repository can answer.
2. Ask one compact batch covering only unresolved items:
   - the observable outcome and affected users or surfaces;
   - in-scope work and explicit non-goals;
   - precedence among conflicting constraints;
   - acceptance evidence, approval boundaries, and rollback expectations.
3. If an unanswered item would materially change implementation or an irreversible
   action, stop and wait for the user. Otherwise state the smallest safe assumptions.
4. Record the result in the task pack:

   ```yaml
   grill_fallback:
     trigger: missing-grill-me
     answered_questions: []
     assumptions: []
     unresolved_questions: []
   ```

## Native bug-fix route

Clear, reproducible Trivial or Light bugs use `native_bug_fix` without Grill Me. A `Full` bug still
runs the Grill Me coverage check and `xy-plan`; when its symptom, expected result, environment,
reproduction, impact, and acceptance evidence are complete, the coverage check asks nothing and
returns control immediately.

```yaml
native_bug_fix:
  - reproduce_exact_symptom
  - minimize_reproduction
  - identify_root_cause
  - add_regression_evidence
  - implement_minimal_fix
  - run_selected_repository_verification
  - assess_task_level_closeout
```

After local verification, Trivial bugs close through the Trivial route without mandatory independent
QA. Light/Full work uses `request_unified_qa`; an explicit review request, stricter project rule, or
risk requiring reclassification also selects the applicable review. The bug label alone does not
upgrade the task or require Full planning, another approval, a saved plan, or documentation churn.

Review-feedback handling is not bug diagnosis. Treat external findings as advisory evidence: verify
them against current source, requirements, and tests before accepting or rejecting them.

## Default business confirmations and exceptions

These stages govern non-Trivial work, not either already authorized Trivial early exit.

- Ask once for `requirements_approved` after scope, non-goals, constraints, and acceptance
  evidence are clear. For Full work, first complete Grill coverage, create the `xy-plan` draft, and
  record the PM's post-QA controlled-document projection decision. For design-change UI, fold the
  reasoned PM recommendation and user's prototype choice into this same confirmation. Reopen only
  after a material requirement, affected-surface, or scope change.
- Handle reversible architecture details automatically and record durable tradeoffs in an
  relevant feature rationale when warranted after verification. A material architecture change that alters approved requirements,
  scope, key constraints, or acceptance evidence normally reopens `requirements_approved`.
- The PM may ask architecture questions or request a user choice. A task-scoped extra
  confirmation is allowed only when the user explicitly requests it or a material unresolved
  decision cannot safely be folded into an existing confirmation.
- `UI-Conformance`, non-UI, and a valid `waived_by_user` request have no business confirmation after
  `requirements_approved` by default during development. A selected worktree delivery route separately
  follows its configured confirm/auto policy at final local merge; do not attach that consent to implementation gates.

For non-Trivial UI classification, prototype choice, design handoff or visual confirmation, read
[UI design branches](references/ui-design.md). Required prototypes retain exact page gates; conformance and scoped
user waivers do not inherit them. Production-only revisions use the current replacement authority.
Read [plan lifecycle](references/plan-lifecycle.md) when saving, revising or resuming a plan.

<!-- workflow-contract: references/ui-design.md -->

For the PM projection decision before requirements approval, or after verified QA for document
projection and commit assessment, read [closeout decisions](references/closeout.md). Assess first; do not update
PROJECT/features merely to finish. Current truth changes only after verified implementation.

<!-- workflow-contract: references/closeout.md -->

- An exceptional confirmation must be represented in the task pack and omitted otherwise:

  ```yaml
  additional_business_confirmation:
    name: <stable gate name>
    reason: <why the default two stages are insufficient>
    decision_scope: <what the user is deciding>
    options: []
    evidence: []
    resume_condition: <exact answer that resumes dependent work>
  ```

  It blocks only dependent DAG tasks and must never become a permanent default stage.

## Implementation and QA loop

After implementation dispatch, on rework or when closing non-Trivial implementation, read
[implementation and QA](references/implementation-and-qa.md). Use exactly one read-only request
reviewer; preserve independent source/standards audit and valid evidence reuse. The same reviewer
checks affected repairs without restarting unchanged coverage. Trivial work and standalone read-only
audits stop at their applicable early exits and never enter this loop.

<!-- workflow-contract: references/implementation-and-qa.md -->
