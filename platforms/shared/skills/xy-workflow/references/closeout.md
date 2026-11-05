## Verification evidence and delivery boundaries

Closeout follows `xy-build-verify/references/verification-scope.md`: PM checks successful production
build/compile and runnable evidence, and confirms current delivery matches the verified scope. Do not run
builds, tests or acceptance without information gain merely because a commit is pending, QA PASS exists
or a user reply is imminent. Judge added coverage, invalidated evidence and specific risks under that
policy; ordinary explanatory closeout alone is no reason to rerun. Actual input changes invalidate only
affected conclusions. Mandatory CI/Hooks and worktree-candidate integration checks retain their requirements.
After minimum verification, Light assesses independent audit, documentation and memory by actual risk;
do not create a Full graph, plan or empty closeout record to apply this section. Full still requires its
single valid QA PASS. Both levels default to native implementers; a PM exception needs explicit authority.
Final feedback states only actual verification scope, results and relevant limits, accurately distinguishing
scoped success from full-suite success. Complete commands, logs and reuse provenance remain in existing
evidence references, without a new report/approval step. Read-only audits do not enter this implementation
closeout chain after delivering conclusions. Ordinary explanatory documentation/low-risk copy closeout after
QA checks only changed links, semantics, resources or runtime inputs. Update delivery bindings through
existing mechanisms when needed; do not restart review of unchanged functionality for closeout. Markdown/
copy status does not exempt workflow instructions, permissions, security, APIs or business-contract changes.
New risks, invalidated evidence and explicit user/project rereview requirements still apply to affected scope.

- Every implementation task pack carries its approved goal, non-goals, constraints, acceptance
  evidence, and applicable UI authority. Required-prototype design tasks carry concrete pages;
  `UI-Conformance` tasks carry `design_authority_refs`; waived tasks carry the scope-bound
  `prototype_decision` and must not treat an old prototype as current authority. Required-prototype
  tasks carry the same decision plus concrete page authority. Full packs record the projection decision
  in advance; Light assesses actual needs at handoff without mandatory prefilled Full projection records:

  ```yaml
  controlled_document_projection:
    project_docs_update: required | not_required
    change_type: added | updated | replaced | reimplemented | removed | restored | split | merged | renamed | cancelled | none
    affected_features: []
    project_index_update: required | not_required
    reason: <why current verified project or feature truth changes or remains unchanged>
  ```

  For Full work this decision belongs to PM review of the `plan_state: draft` proposal. It describes
  a post-QA projection and is never early write authority. Canonical documents remain the last
  QA-verified project truth while implementation and QA are in progress.

  Use `required` for an added, changed, replaced, restored, renamed, split, merged, cancelled, or
  removed feature truth. Also use `reimplemented` for a major behavior-preserving rewrite that future
  work must recognize; routine refactors, dependency upgrades, internal performance work, and pure
  visual styling use `not_required` with `change_type: none` only when recorded current facts remain
  unchanged. Update an existing runtime/dependency baseline, rationale or scope in place when it
  changes; do not add a document or chronology merely for the task. A durable UI behavior change updates the
  affected topic plan. Approved concrete HTML remains visual and interaction authority for
  current required-prototype work, or when an unchanged concrete page is explicitly frozen as valid
  `UI-Conformance` authority. If a production-only revision makes an existing document's
  prototype link misleading, project the verified production truth and scoped authority boundary;
  do not synchronize the historical prototype during closeout.

  Full projects after integrated QA PASS; Light updates on acceptance of actual minimum verification and
  necessary independent audit, without calling unaudited results QA-verified. PM updates the topic plan's
  accepted version, delivered behavior and necessary evidence in place. PROJECT retains only current baseline
  links, without appended execution states or one entry per revision. Preserve the old baseline during
  iteration; canceling the current goal does not erase old delivery. completed does not prove acceptance,
  and unindexed old drafts do not automatically become facts. Without changes, add no feature document/ADR.
  Mark accepted complete deletion as removed in the same source, retaining reason/date/replacement and
  necessary history, removing the current PROJECT link and repairing references. Do not project after QA
  failure. Markdown is the sole editing authority; rerender relevant HTML at the same path.
- Full performs PM commit assessment after QA PASS, and Light after acceptance of minimum verification and
  actually mandatory audit, including verified document projection.
  Keep the result internal:

  ```yaml
  commit_decision:
    needed: true | false
    reason: <request-level evidence>
    repositories:
      - path: . | <nested-repository-path>
        action: committed | skipped | blocked
        scoped_paths: []
        staged_diff_fingerprint: null | <64-lowercase-hex-sha256>
        commit_revision: null | <full-commit-id>
        reason: <repository-specific evidence>
  ```

  Commit only request-owned changes verified/accepted for the current level, plus verified PM projection;
  Full requires valid QA PASS. Use exact
  pathspecs and inspect the complete staged diff; the PM must not stage unrelated or unverified changes
  and must not use `git add -A` or `git add .`. Preserve pre-existing user edits. Unsafe overlap is
  `blocked`, not permission to stage a whole file. Assess nested repositories independently and
  deepest first. Verify the committed patch against the inspected staged snapshot. This automatic
  action does not create a third business-confirmation stage or authorize push, merge, tag, release,
  or another remote mutation.
  The selected [worktree delivery](worktree-delivery.md) branch separately grants bounded PM-local
  checkpoint/integration authority before final QA and confirm/auto delivery after all work completes.
  It never grants workers commit/merge authority or implies a remote operation.
- Before the final report, close out actual task-temporary resources only under the original contract.
  First stop relevant writers and verify task ownership, active use and current plan/handoff/recovery
  references. Continue reusing shared configuration, project environments, databases, system caches and user
  material for their intended roles. Transfer authorized retained valid data/results to the corresponding
  project/service baseline. First place mandatory complete logs and approval/recovery evidence at a readable
  durable location and repair current references; a summary cannot replace the sole complete evidence.
  If transfer is impossible, retain only necessary files/ancestors, not an entire candidate for one reference.
  For scratch, follow the [record-tool preview and cleanup contract](runtime-records.md#allocate-and-clean-up-the-task-scratch-workspace):
  preview this `request-id` read-only with the same necessary `--keep` values, then execute against its reviewed
  snapshot fingerprint. Recheck an invalidated snapshot; `--all` is not default closeout. Likewise reclaim only
  task-owned isolated databases, containers and rolling snapshots with proven ownership, no active use and no
  necessary references. If cleanup occurs, briefly record results/remaining limits in the original task.
  `removed_logical_bytes` counts removed files' logical bytes only; do not claim physical disk space released.

## Instance and evidence closure

Follow WORKFLOW's `agent-instance-lifecycle`: after PM accepts results, necessary verification/QA ends and
evidence is safely preserved, use actually exposed native close capabilities. Without a reliable tool,
record agent_retired:true only in the existing task to prevent misdispatch, and state closure is unconfirmed.
Do not claim physical erasure/destruction or released unconfirmed capacity; retirement does not unlock active
tasks. Keep necessary short-rework/original-Reviewer delta-review windows for the current delivery unit.
Under pressure, prefer accepted, sufficiently handed-off instances; do not simply LRU-evict executing,
evidence-unreceived or necessary-review instances. Protect temporary worktrees/sole logs before AGY kill.
Preserve existing recovery boundaries for cancellation/exceptions. Native closure/scratch cleanup must not
delete still-referenced sole evidence.
