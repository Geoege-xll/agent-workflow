# Requirement Plans, Recovery and Change Handoff

Use when deciding whether to save a plan, revising an approved request, or resuming related unfinished
work. This supports the current Light/Full routes with schema 2 task packs; it adds no role, confirmation gate or
automatic memory call. Explicit task-scoped workflow opt-out and save/no-save instructions prevail;
applicable project constraints and permission boundaries still apply.

## Save by task level

- Light: do not create a plan by default. PM saves a short recovery plan only for an actual pause,
  cross-session continuation, handoff need, or explicit user request. Saving does not upgrade Light
  to Full, activate Full planning Skills, require a DAG, repeat existing authorization or force independent QA.
- Full: after requirements approval and any applicable prototype choice, PM saves the approved
  current plan under adapter-resolved `docs.plans` before the first design or implementation dispatch.
  xy-plan still only drafts; PM owns persistence. Do not wait for visual approval to save the plan.

Formal Full review uses the single Markdown draft. Before approval, PM may keep that draft in the current
request scratch. Only after approval does PM save `docs.plans/<name>.md` before dispatch. Markdown remains
the sole editing authority. Requirements/plan Markdown-to-HTML generation is retired; preserve
existing plan HTML and active prototype HTML under [the retained reference](../../xy-plan/references/requirements-markdown.md).
Light selects persistence by existing save needs, complexity or user requirements, without upgrading the
workflow. Document existence and checkbox selections do not create approval.

Maintain one lifecycle Markdown per stable topic. Update in place for further iterations,
visual adjustments, implementation assignments or QA rework, without version copies. Independent topics
have separate documents. Light persistence still depends on actual need; an old topic's Full level does
not automatically make an unrelated small correction Full.

The standard template is `templates/docs/PLAN.md`, using ordinary Markdown metadata rather than frontmatter.
Preserve these literal protocol fields: `主题 ID`, `阶段`, `模块`, `任务等级`, `已验收版本`.
Stage accepts only draft／active／paused／completed／cancelled／removed; task level is Full／Light;
the accepted version is `none` when no real baseline exists. Preserve the six Full section-title literals
in this order: `目标与范围`, `需求与验收`, `方案与原型关联`, `当前进展与恢复入口`,
`验收结果与当前已交付行为`, `批准依据与必要证据`. The final section's literal evidence keys
`批准依据` and `验收证据` reference real recoverable sources. Templates, non-empty lists and stage labels
are not authorization. Simplify a baseline-free Light recovery draft as needed without extra documents or
confirmation. If PROJECT links it as a current baseline, it must still state the version, delivered behavior
and existing evidence. Create directories only when saving an actual topic. Installation creates no
requirements page, empty index or placeholder plans／features directories.

Discussion alone requires neither a saved document nor a plan. When persistence is needed, keep
necessary questions and conclusions in the relevant existing plan or authorized requirement/proposal
location, distinguishing pending proposals from effective approved scope. Do not create a discussion,
change-note or v2/final copy for each revision.

## Minimal recoverable content

Keep the approved goal, scope/non-goals, chosen solution and essential acceptance; meaningful task
boundaries/interfaces/dependencies; verified progress with evidence references; implemented but
unverified work; remaining work/blockers and next safe action. Reference applicable feature/standards
instead of copying them. Persist only information needed to restore the approved work, not full logs,
conversation transcripts, every command or another serialized DAG.

Update recovery state in the current plan and existing start/handoff briefs in place. Retain current
approved scope, necessary completed baselines, unverified content, remaining work, blockers and next steps,
replacing state superseded by new facts. Do not append completion details for every batch and turn a start
brief into cumulative history. Briefly describe necessary completed baselines with links to existing plans,
feature truth and complete evidence, so readers find the next action without traversing old batches. Add
no brief copies/archive tree or hard line/token threshold. PM remains the sole plan writer; a brief is not
a second task-state source or feature standard.

Before consolidation, confirm complete logs, original approvals and sole history are recoverable from existing
evidence locations or actual version history, and repair affected references. Summaries cannot replace complete
evidence. Git does not protect uncommitted/untracked content or original non-Git material. When safe transfer/
recoverability cannot be established, preserve originals and explicitly mark their historical boundary and
current recovery entry. Do not delete user documents/sole history or add QA reports, ledgers or confirmation
stages for organization.

Record the requirement confirmation source and scope, prototype choice, and any still-pending UI
decisions. When a concrete prototype is approved, retain its page/scope, approval source and dependency
fingerprint in this same plan; do not create a companion approval record. If approval evidence is not
recoverable, mark that gap rather than declaring the gate approved from a status label alone.
Do not expose raw DAG JSON, YAML, hashes or full Task Packs in normal user feedback.

PM is the sole plan writer. Workers and QA return scoped results/evidence; they do not race on the
plan. Update on meaningful decisions, completed deliverables, blockers, rework or pause/handoff, not
every tool call. Preserve an accurate checkpoint during long work; do not rely solely on a final save
that may never run. File persistence does not imply permission to commit, publish, or execute it.
The design Agent returns coverage from REQ IDs to concrete prototype pages/actual state anchors in the original
handoff. PM writes it into this Markdown source, without generating HTML, a separate mapping file or
prototype QA. Progress, link or presentation-only changes do not automatically reopen requirements approval.
requirements_fingerprint and prototype dependency fingerprints retain their separate responsibilities;
historical HTML freshness is not required after generation retirement.

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
   affected Task Packs, interfaces, acceptance and prototype/standards references. Reconcile superseded
   discussion/proposal material as below before affected work resumes. Each affected Agent receives
   the latest complete self-contained task, not an obsolete task plus unexplained amendments.
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

### Superseded discussion and plan documents

For an effective approved revision, reconcile only related material within authorized paths, not all
project documents. A newer date or filename is not approval. Keep one clear current execution basis
for the requirement; retain independent requirements and unaffected approvals separately.

- Update the existing current requirement/proposal and plan in place where applicable. Replace
  obsolete goals, acceptance and queued work, preserving valid progress and necessary reasons;
  do not make readers reconstruct the current scope from appended conflicting amendments.
- Consolidate redundant discussion/proposal content into its current authoritative location. Transfer
  unique still-valid information and repair affected current links and task references before
  removing a duplicate. Do not copy whole requirements into every plan or companion document.
- Retain useful superseded material as historical, not a competing execution input. State the
  replacement and scope briefly in an authorized location; no new archive tree, register or report
  is needed. Completed/cancelled plans and their old tasks are not defaults to replay on recovery.

Before rewriting, merging or deleting, preserve required original approved inputs and evidence in
recoverable existing task/input evidence or actual version history. Do not presume Git can restore
uncommitted or untracked content. Delete obsolete duplicate files only with explicit authorization
covering those paths, after unique relevant content and current references are handled, without losing
required evidence, user material or a live consumer's input. Plan ownership grants no wider file rights.

If safe deletion is not authorized or recoverability is unclear, preserve the original and delimit
its non-current scope in the authorized current basis. Physical cleanup is not a dispatch prerequisite
when the replacement basis is clear; add no cleanup approval gate. If the current execution basis or
necessary authority is still unresolved, return only that affected work to existing clarification.
Pending discussion never silently withdraws an approved baseline. Planned goals remain intended work;
accepted baselines/PROJECT still change only through the existing post-QA projection below.

### Production-only cutover

When the user explicitly selects real-product edits without prototype synchronization, preserve the
current prototype files unchanged. A generic start/defect report, or approval to implement the
prototype, does not establish that choice. Do not reinterpret every post-approval correction as a
waiver. Where scope and choice are already explicit, the instruction itself supplies the existing
confirmation; ask only for missing material decisions, not another approval of the same request.

- Update this revision's requirements, scope, acceptance and `prototype_decision` in the current
  task state and same plan if one is saved; bind the user instruction to the current requirement
  fingerprint and exact affected surfaces with `selected_policy: waived_by_user`. Do not turn an
  actual interaction/design change into `UI-Conformance`, low-risk Light copy, or a non-material hash refresh.
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
Check implementer, classification and exception authority against
`.agent-workflow/product/WORKFLOW.md#implementation-ownership`. Only continuous implementation or short rework
of the same task may reuse the available original instance and valid evidence; independent tasks need new
instances/IDs. Compacted summaries do not authorize PM implementation or change the original level. Do not
copy full PM/sibling conversations. Native closure/retirement and cancellation/invalidation follow WORKFLOW's
instance lifecycle and current-host details, preserving existing results and necessary complete logs.
Restore the current remaining graph from verified facts; the transient CLI snapshot is not the only
carrier of outstanding decisions or work. Report the smallest missing approval or fact when needed.

## Closeout and document boundaries

- PROJECT is the current overview and accepted-baseline index. Each topic has one plans source; do not append
  index entries per revision.
- During iteration, update the first four sections/current stage and preserve the fifth section's last accepted
  behavior, accepted version and corresponding evidence. active／paused／cancelled must not present new goals
  as delivery; `completed` alone establishes no trust.
- Replace baselines only after applicable QA PASS for Full or acceptance of actually necessary verification for
  Light. Without factual changes, create no projection. PROJECT may list only sources with an explicit accepted
  version and real grounds; failed acceptance preserves the original baseline.
- Mark accepted deletion as removed in the same source, retaining necessary dates, reason, replacement and
  history. Remove its current index entry; do not rename it or create a feature/ADR document.
- Unindexed old execution drafts retain historical boundaries. Do not auto-index by completed, bulk-edit
  history or replay old tasks by default. Existing same-name HTML is retained historical material after
  generation retirement; it is not a second standard or approval source.
- Old `docs.features` and FEATURE templates are outside the current runtime contract, and version 2.1
  provides no old-document conversion CLI. Preserve complete text, approvals/evidence and index references
  under README's document-protection boundary before removing rejected old keys; stop for conflicts or
  unclear topic relationships. Standards and memory still follow actual changes.
