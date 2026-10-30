# Requirement Plans, Recovery and Change Handoff

Use when deciding whether to save a plan, revising an approved request, or resuming related unfinished
work. This supports the existing Trivial/Light/Full routes; it adds no role, confirmation gate or
automatic memory call. Explicit task-scoped workflow opt-out and save/no-save instructions prevail;
applicable project constraints and permission boundaries still apply.

## Save by task level

- Trivial: do not create a plan by default. An explicit save request may create a short note without
  invoking Grill Me/xy-plan, prototype work, a graph or independent QA merely to save it.
- Light: do not create a plan by default. PM saves a short recovery plan only for an actual pause,
  cross-session continuation, handoff need, or explicit user request. Saving does not upgrade Light
  to Full, activate Full planning Skills, or add approval/QA beyond the existing Light route.
- Full: after requirements approval and any applicable prototype choice, PM saves the approved
  current plan under adapter-resolved `docs.plans` before the first design or implementation dispatch.
  xy-plan still only drafts; PM owns persistence. Do not wait for visual approval to save the plan.

One independent requirement has one plan. Multiple independent requirements may have separate plans;
subagent tasks, visual iterations and QA rework do not create additional plans. Continue an existing
unfinished requirement in its existing file when relevant. An unrelated small fix to a previously
completed feature is classified on its own, not inherited as Full from the old plan.

`templates/docs/PLAN.md` is a writing aid, not a mandatory field-heavy schema. Create the directory
only when saving a real plan; setup must not create placeholder plans. Use stable descriptive names,
not per-revision copies. A plan records a decided change, not an automatically actionable idea backlog.

## Minimal recoverable content

Keep the approved goal, scope/non-goals, chosen solution and essential acceptance; meaningful task
boundaries/interfaces/dependencies; verified progress with evidence references; implemented but
unverified work; remaining work/blockers and next safe action. Reference applicable feature/standards
instead of copying them. Persist only information needed to restore the approved work, not full logs,
conversation transcripts, every command or another serialized DAG.

Record the requirement confirmation source and scope, prototype choice, and any still-pending UI
decisions. When a concrete prototype is approved, retain its page/scope, approval source and dependency
fingerprint in this same plan; do not create a companion approval record. If approval evidence is not
recoverable, mark that gap rather than declaring the gate approved from a status label alone.
Do not expose raw DAG JSON, YAML, hashes or full Task Packs in normal user feedback.

PM is the sole plan writer. Workers and QA return scoped results/evidence; they do not race on the
plan. Update on meaningful decisions, completed deliverables, blockers, rework or pause/handoff, not
every tool call. Preserve an accurate checkpoint during long work; do not rely solely on a final save
that may never run. File persistence does not imply permission to commit, publish, or execute it.

## Visual iteration and task replacement

1. Assess the actual impact of a proposed change before replacing approved requirements. Undecided
   alternatives remain explicitly pending; they must not silently override the approved baseline.
2. During prototype design/review, visual-only refinements within approved behavior update the
   prototype and only material plan implications. Keep concrete styling in the prototype/standards,
   not duplicated in the plan. Use the existing final visual confirmation; do not reopen requirements
   merely for a visual refinement. An explicit production-only revision during implementation or
   acceptance instead follows the cutover below; the old prototype choice is not perpetual authority.
3. A change to functionality, permissions, data/API contracts, acceptance or approved scope returns
   the affected requirement to existing clarification/approval. Preserve unaffected approvals and
   work; do not add a third business-confirmation stage or repeat the whole interview.
4. Before affected dispatch, PM merges effective changes into the same current plan and refreshes
   affected Task Packs, interfaces, acceptance and prototype/standards references. Each affected Agent
   receives the latest complete self-contained task, not an obsolete task plus unexplained amendments.
   Use existing input_contracts to reference the plan and current applicable scope; no new scheduler
   field or second runtime plan is required.
5. If an affected worker is already running, send the updated contract and pause/interrupt that
   affected work when necessary. Establish that the worker is using the replacement before continuing
   dependent work; an unacknowledged old task cannot satisfy the new contract. Preserve existing edits,
   inspect their applicability, and dispatch only necessary rework. Never reset unrelated work.
6. Refresh the same internal DAG snapshot, invalidate only affected stale evidence/gates, and run the
   existing graph checks before further dispatch. Do not declare the whole plan unapproved for a local
   refinement or reuse an old page fingerprint after a material change. Unrelated ready work continues.
7. QA receives the same current scope, acceptance and complete applicable changes. Update an in-flight
   affected review before accepting its result. An old-scope PASS cannot close a revised task.

### Production-only cutover

When the user explicitly selects real-product edits without prototype synchronization, preserve the
current prototype files unchanged. A generic start/defect report, or approval to implement the
prototype, does not establish that choice. Do not reinterpret every post-approval correction as a
waiver. Where scope and choice are already explicit, the instruction itself supplies the existing
confirmation; ask only for missing material decisions, not another approval of the same request.

- Update this revision's requirements, scope, acceptance and `prototype_decision` in the current
  task state and same plan if one is saved; bind the user instruction to the current requirement
  fingerprint and exact affected surfaces with `selected_policy: waived_by_user`. Do not turn an
  actual interaction/design change into `UI-Conformance`, Trivial work, or a non-material hash refresh.
- Replace affected active task/QA inputs and dependency closure using existing graph fields. Detach
  superseded prototype-mode tasks and visual gates from this revision, retaining earlier authorized
  work as history, not unfinished work to replay or fake-complete. If an affected designer is running,
  stop its superseded assignment and establish acknowledgment before accepting further results;
  preserve its existing edits. Unrelated work and approvals remain unchanged.
- Dispatch only the authorized production correction (plus separately justified standards-only
  maintenance). Do not edit prototype HTML, CSS/JS, index or contract as an intermediate or closeout
  synchronization step. Prototype work resumes only with an explicit, scoped user request.
- Give QA the current user instruction, replacement scope, applicable engineering/design standards
  and real production evidence. Delimit this revision's diff from earlier authorized prototype work
  without concealing new unauthorized writes; do not fail the correction solely because the old
  prototype differs. Unaffected required-prototype tasks retain their original checks. Refresh an
  affected in-flight audit before using its result.

No new plan, approval artifact, gate, scheduler field or automatic document/memory update is added.
This choice does not authorize PM to replace the production owner or skip the task's required checks.

## Resume without repeating completed work

For isolated functional units, also follow [worktree delivery](worktree-delivery.md): keep only useful
root/base/head and pending-merge recovery facts in this same plan. Reopen existing worktrees by verified
identity, not by recreating completed tasks; a waiting merge is not a completed main-branch delivery.

When available context is sufficient, do not reload all plans or project documents. For a concrete
recovery gap, locate the relevant plan by task/feature terms and read only that plan and necessary
references. Check its state, pending decisions, current files and evidence; plans supplement the host
conversation and task state rather than replacing them.

Treat recorded completion and approval as evidence to verify, not as self-executing authorization.
Reuse completed work whose scope/artifacts/evidence remain valid; recheck or rework only affected or
uncertain parts. Do not replay the old plan from its first step, restart live workers, reconstruct stale
locks as active, or mark prior work failed just because its Agent session is no longer active.
Restore the current remaining graph from verified facts; the transient CLI snapshot is not the only
carrier of outstanding decisions or work. Report the smallest missing approval or fact when needed.

## Closeout and document boundaries

- PROJECT remains a directory of current verified feature details plus stable plan/standards entry
  points; do not append task statuses or one index row per plan revision.
- Features contain current verified behavior, acceptance and necessary functional/architectural
  rationale. Cross-feature rationale may have one shared detail in the same directory. No separate
  ADR category, duplicate decision document or chronology is required.
- After applicable QA passes, assess feature/PROJECT projection. Update only changed current truth.
  Mark the plan completed only when the approved work and required closeout are genuinely done; link
  the result and stop maintaining the plan as a second current feature specification. Paused or
  cancelled plans remain non-current work, never evidence that implementation exists.
- Keep completed plans available as historical execution context, clearly marked and not dispatched
  by default. Do not auto-delete user plans or create a growing recap in PROJECT.
- Standards adoption keeps its existing lifecycle. Plan writes alone do not trigger feature,
  STANDARDS, PROJECT or agentmemory updates; evaluate each actual change separately.
