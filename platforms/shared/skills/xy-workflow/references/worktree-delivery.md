# Parallel worktrees and local main-branch delivery

Read for multi-feature isolation assessment, isolated dispatch, integration, delivery or recovery.
This is the pack's own conditional execution branch, not a Superpowers worktree/finishing workflow.
Trivial tasks and read-only reviews do not acquire worktrees or delivery consent merely by loading it.

## Select the execution mode

- Resolve `parallel_worktrees` in the project adapter: `mode: auto | off`, `merge: confirm | auto`,
  `target_branch: auto | <exact-local-branch>`. Omitted settings mean auto assessment, confirm delivery,
  and target discovery. `auto` isolation means assess, not create a worktree for every task.
- During existing planning, prefer worktrees when at least two substantive, independently writable
  functional units can run concurrently and the project is a Git repository. Keep shared foundations,
  schemas and semantic contracts ordered. Preserve `owned_paths`, protected paths, standards and
  semantic locks across worktrees; isolation does not grant overlapping write authority.
- Include the selected execution and delivery approach in the existing concise requirements brief.
  A request using confirm delivery gets one conditional user decision at the end. This is not a
  requirements/visual gate and does not block implementation. Auto delivery requires an explicit
  project setting; ordinary task approval does not silently enable it. User no-merge/no-commit
  instructions override the default; preserve the work and report what remains undelivered.
- Create worktrees only when dispatch is authorized. If the host cannot actually bind each Agent's
  tools to an independent root, do not claim isolation from a branch label or a prompt alone.
  Use a supported native path; otherwise report the limitation and use safe ownership-based scheduling
  (serial when required). Do not create new user-visible tasks just to simulate subagent isolation.

## Pin and prepare

1. Resolve the main branch from explicit configuration, local `origin/HEAD`, or one unambiguous
   existing `main`/`master`. Never guess from the current feature branch, fetch implicitly, or invent
   a main branch. `worktree_cli.py target --repo <checkout> --config <project.yaml>` is read-only.
2. Pin its full commit ID as `target_base`. Inspect the actual current branch and dirty scope.
   Do not stash, reset, stage unrelated files, or silently omit approved earlier work. When needed,
   PM prepares only attributable authorized changes as a local checkpoint in an isolated checkout;
   overlap or an explicit no-commit policy requires a bounded alternative or a reported blocker.
3. Prefer host-native isolated subagents when available. Otherwise the portable creation command is
   `worktree_cli.py create --repo <checkout> --path <new-absolute-root> --base <full-commit-id>`.
   It creates a detached checkout outside the original worktree, never a branch switch. Verify
   actual root, common Git directory, base, and host write permissions before allowing edits.
4. Each independently deliverable writer unit has one root; keep serial implementation steps within
   that unit rather than allocating a new worktree for every small step. The integration root is separate.
   A downstream unit starts from a checkpoint containing all completed prerequisite changes, not
   blindly from the default branch. Keep the latest complete task pack and existing approval scope.
5. Check that needed host entrypoints, installed Skills, plan and targeted STANDARDS references are
   actually available at the new root. If ignored/untracked, copy only explicitly selected safe setup
   files with the host-supported setup mechanism. Do not copy secrets, an entire checkout or caches
   indiscriminately. Missing required context or permissions stops that unit, not unrelated work.
   Keep one logical `memory.project_id` for the project across its worktrees; never create new memory
   namespaces or run setup just because a worktree directory has a different name.
6. Isolate ports, writable build outputs and test databases where needed. Worktrees do not isolate
   external services. Account for disk, build resources and actual host slots before dispatch.

## Checkpoints, integration and QA

- Workers stay within their assigned root/paths, run selected checks and return exact evidence.
  They do not merge, publish, delete worktrees or independently commit. After checking attribution,
  PM may create a scoped **local checkpoint before QA only inside an isolated worktree** to transport
  that unit's changes. This explicit exception is not a final delivery commit, not QA PASS and not
  permission to advance the main branch. Use exact staging and preserve hooks/user settings.
- Add `execution_workspace` to each isolated writer: `root`, `base_revision`, `head_revision` (null
  until a PM checkpoint is ready). One request cannot mix untracked shared-root writers with isolated
  writers; design/prototype units are included when they belong to the current request. External
  already-verified dependencies remain bounded inputs and must actually exist in the chosen base.
  A historical delivered checkpoint is verified against the current target base; its old worktree
  need not survive cleanup and its owned paths do not enlarge this request's write authority.
- In the same runtime graph, `worktree_integrations` maps each isolated request ID to `root`,
  `target_branch`, `target_base`, `head_revision` (null before integration), and `verification`.
  Each verification entry has `command`, integer `exit_code`, resolvable `log_ref`, and the exact
  integrated `head_revision`. These are internal runtime fields, not another document or user output.
  Reuse the existing [record tools](runtime-records.md): task `checkpoint` records a verified unit
  head, and `integrations` records the existing request's integration head/checks. These operations
  preserve worktree identity and run no Git, verification or merge; existing evidence review applies.
- PM integrates completed checkpoint commits in dependency order into the isolated integration root,
  preserving commit ancestry. This bounded local integration is authorized for the selected worktree
  route; it is not delivery to main. Conflicts return to the relevant implementer; PM does not invent
  production fixes, run force/reset operations or discard another unit. Preserve failed worktrees.
- Verification runs on the composed result. Reuse still-valid unit evidence, but select concrete
  cross-feature checks for interactions and mandatory project rules. No automatic full-suite rerun.
  `task_graph_cli.py qa-ready` remains the entry to the same single QA; for isolated requests it also
  requires successful verification pinned to the integrated head. JSON assertions do not replace
  actual Git inspection, source review or real log inspection by PM/QA.
- QA audits the combined request diff, applicable standards and concrete prototype authority in the
  integration root; no default new browser/prototype audit or separate reviewer per branch. Export the
  actual range with `worktree_cli.py inspect --repo <integration-root> --base <target-base> --head <head>`.
  Its binary/full-index/no-renames/no-external-diff SHA-256 is the `scope_ref.repositories` record.
  After all requested work and dependencies finish, accept only a valid current `qa_handoff` PASS.
  If the graph carries an explicit QA node, mark it `QA_PASSED` only after that handoff validates;
  re-review returns to `QA`/`RUNNING`, failure to `FAILED`. A cached PASS cannot override those states.
- Apply only the already-assessed PM document projection after QA PASS, in the integration checkout,
  and validate it. If projection or rework changes the reviewed head, the same QA reviewer checks the
  affected delta and refreshes its final full scope binding; reuse unaffected checks, not an old PASS
  for a different tree. Checkpoints and a green branch alone cannot satisfy final delivery.

## Deliver to the local main branch

The ordinary closeout sequence stays unchanged outside this branch. For worktree delivery the order
is: integrated QA PASS → assessed/validated projection and scoped candidate commit → current final
QA binding → confirm or auto local merge → memory closeout → final report. Final candidate refinement
revalidates only affected evidence. There is no new implementation DAG gate or repeated requirements
interview. Local candidate commits and default commit assessment do not by themselves authorize a merge.

- PM builds one internal delivery object with `task_graph`, `qa_handoff`, optional exact
  `projection_paths` (only configured PROJECT/features/plans), and `authorization`.
  Projection entries are unique actual changed Markdown file paths, including deletions, never directories.
- `authorization` binds `request_id`, `target_branch`, `target_base`, `head_revision`, and
  `diff_fingerprint`, plus `mode` and `source`. In confirm mode, first show the user the completed
  features, resolved target branch, current QA/verification result, and any meaningful risk; ask one
  natural-language question about merging this candidate. An explicit affirmative reply supplies
  `mode: confirm` and `source: user:<reply-reference>`. Silence, recommendation or requirements
  approval is not this reply. Reuse consent only while its exact candidate remains unchanged.
- In auto mode, the actual target project's `parallel_worktrees.merge: auto` supplies
  `mode: auto` and `source: project:parallel_worktrees.merge`. Preserve explicit user opt-outs and
  stricter repository policy. All task, QA, scope and Git checks still apply.
- Use `worktree_cli.py merge-ready --repo <main-checkout> --config <project.yaml> --input <delivery.json>`
  for a read-only final check, then `worktree_cli.py merge` with the same arguments. Prefix all commands
  here with `bash .agent-workflow/lib/python_runtime.sh .agent-workflow/lib/` at the calling project.
  The command accepts only a clean checkout already on the resolved target branch and a fast-forward
  from the pinned target base to the exact reviewed candidate. It never checks out another branch,
  creates a speculative merge commit, resolves conflicts, pushes, force-updates or overwrites ignored files.
- Every current-request task and required predecessor must be complete, every applicable gate
  satisfied, all writer checkpoints incorporated, and all actual changes attributable to the request
  or validated PM projection. Missing/failed/stale evidence, changed writer/integration heads, dirty
  target, target movement or ambiguous main branch blocks mutation. Refresh integration and affected
  evidence/consent instead of merging with stale authority; no blanket rerun of unaffected work.
  A moved main branch is integrated into a refreshed candidate before new QA/consent. Unchanged
  completed units keep their original bases/checkpoints; do not recreate them just to match the new target base.
- Coordinate exclusive use of the target checkout during final delivery; external writers or branch
  switches must not run concurrently. Recheck the resulting head and worktree after Git completes.
  An uncertain/interrupted result is inspected before any retry, never reset or automatically undone.
- The portable final merger handles one repository at a time and stops on submodules. Nested repository
  delivery needs explicit per-repository targets, authorization and QA; do not infer it from a parent
  pointer or silently bypass the guard. No part of this policy authorizes remote push/PR merge/release.

## Recovery, documents and cleanup

PM records selected mode, resolved target/base, worktree locations, delivered revisions, remaining
tasks and pending merge in the existing saved plan only when needed for recovery. Do not create
one plan per Agent, a separate worktree ledger, a growing PROJECT history, or automatic memory entries.
After a pause, inspect the actual existing worktrees and refs; reuse valid completed work instead of
recreating all units. Missing baseline/provenance is a recovery gap, not permission to discard files.

After a confirmed successful merge, update the same recovery plan with the actual result and assess
any small record-only commit separately; do not rerun development QA merely to record completion.
Report local merged versus awaiting consent/blocked accurately. Pending delivery never becomes
"main branch complete" in PROJECT, a plan or memory. Close memory against the actual delivered revision
only when warranted; do not save merely because worktrees were used.

Release finished Agents before cleanup. Remove only identified task-owned worktrees after proving
their commits are preserved in the delivered main history and no dirty, untracked, ignored needed
files or active users remain. Prefer the host's safe cleanup; otherwise use non-force `git worktree
remove` for an exact registered path. Keep any uncertain or unfinished worktree. Never recursively
delete a workspace root, force removal, delete user branches, or treat the final merge as cleanup consent
for unrelated work. Briefly report what was removed and where the committed work remains recoverable.
