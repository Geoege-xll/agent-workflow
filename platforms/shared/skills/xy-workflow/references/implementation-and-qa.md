## Implementation and QA loop

Light uses the current single-task pack, defaults to a native implementer and minimum sufficient verification,
and assesses independent QA, documentation and memory at handoff by actual risk, without forcing a Full graph
or QA. Full uses the graph and single independent QA chain below. Light actually requiring QA uses the same
read-only acceptance contract; local verification cannot be relabeled QA PASS. Independent read-only audits
stop after delivering conclusions, without creating implementers, BUILD_VERIFIED or another audit of the report.

### Progress and worker reports

- Workers report completion and blockers to PM through an available, authorized parent-reporting
  channel; long tasks give meaningful milestone updates. Keep updates to completed/current work,
  blockers and the next step. Do not repeat unchanged status on a fixed timer or create a status log.
- PM consumes these reports and host completion notifications; while work runs, continue unrelated
  READY tasks. If waiting is needed, use the host's available notification/wait mechanism and its
  supported event cursor when applicable; do not repeatedly fetch already-delivered results.
- If a long task has no useful feedback, PM asks that worker for a brief progress update at a safe
  work boundary: continue the existing task, do not restart it or repeat operations. Do not keep
  sending the same unanswered inquiry. A progress-only request does not change scope or authority.
- Do not read a worker's conversation history or execution logs to check progress unless the user
  explicitly requests that inspection; then inspect only the requested scope. A timeout or missing
  report is not permission to inspect history, interrupt work, or start a duplicate worker.
- Use only capabilities and messaging authority actually available on that host. If non-interrupting
  messaging is unavailable, wait for the worker's next report/completion; if interim reports are not
  supported, do not invent them. State the visibility limitation when it affects the user. Do not
  substitute history polling, forced interruption or configuration changes for missing capabilities.
- Completion reports include the existing concise handoff and resolvable validation evidence.
  Receiving and reviewing that delivery/evidence is not progress polling. Self-reported completion
  never substitutes for build verification, independent QA or validated acceptance.

At prototype stage, the design Agent performs three self-checks and the user gives final confirmation;
there is no independent prototype QA. Unified QA below still reviews production functionality, applicable
built-in rules, project-specific standards and real evidence. With a physically missing project index and
no specific leaves, bind configured paths/null fingerprints; create no GENERAL/empty index or duplicated
general rules for QA. Requirements-review HTML projects one Markdown source. Implementers consume the
complete current source/task pack without preloading all HTML. QA follows
[requirements HTML delivery](../../xy-plan/references/requirement-html.md) to check affected-page freshness
and this source's actual prototype references, reusing valid evidence without rescanning the prototype tree,
adding approval or independent prototype QA.

### Execution and acceptance

The graph, qa-ready and mandatory QA steps below apply to Full. Light uses only actually applicable
verification, handoff and audit branches. Both levels follow WORKFLOW's `agent-instance-lifecycle` for
instance identity, context and closure boundaries, without a separate pool.

1. Establish successful snapshot validation, then run `task_graph_cli.py ready`. Reuse a successful
   `update` result for the same bytes; otherwise run `validate` first. Dispatch every returned task
   within the effective host/thread/writer capacity. Do not wait for unrelated tasks or a global
   design phase. The validator rejects cycles, unknown edges, inconsistent `depends_on`/`blocks`,
   invalid gates, unordered path overlap, and unordered semantic-lock overlap.
2. When any task state, approved gate, active path, active semantic lock, or capacity value changes,
   update the same runtime snapshot and run `task_graph_cli.py ready` again. A failed task blocks
   only its downstream dependents; independent branches continue.
   Use [record tools](runtime-records.md) for supported metadata updates and reuse their successful
   validation. Query `qa-ready` separately at the request QA scheduling point; it cannot replace
   required READY recomputation. A QA-ready request may still unlock other runnable tasks. Reuse a
   query result only while its relevant inputs remain unchanged, not merely because QA is starting.
   Record actual completed work; the update tool does not create success, approval or QA evidence.
3. Activate `xy-build-verify` for every implementer (Codex: `$xy-build-verify`; Claude
   Code and Antigravity CLI: `/xy-build-verify`) and return its evidence: exact command,
   exit code, concise relevant output, and a complete-log reference.
   Production implementation needs successful affected-target build/compile and runnable evidence.
   First select minimum sufficient scope under its `verification-scope.md`, identifying evidence needing
   new execution or available for reuse. Hand off once mandatory checks pass. For new tests, re-execution
   and continued failed rework, state information gain under that policy's three judgments; do not default
   every implementer to whole-repository tests. Return to PM early without progress; original self-repair
   limits do not reset or stack. Reuse configuration, environments, data and caches, and govern ownership/
   closeout of actual new resources under that policy and built-in `eng-common-030`, without new resource rules here.
4. Run `task_graph_cli.py qa-ready` for the request. Only `task_type: writer` tasks participate in
   this barrier; `evidence`, `read_only`, and `qa` tasks do not create a circular wait. When it
   returns true, dispatch exactly one integrated read-only `xy-qa` reviewer for this request. That same reviewer tries
   `host-native-review`, then one `installed-code-review-skill` proven installed and capable, then
   `internal-xy-qa-procedure`, moving forward only on technical unavailability. The allowed
   Superpowers option is only its installed `requesting-code-review/code-reviewer.md` prompt;
   Grill Me remains requirements-only. Findings or `FAIL` never switch review method or reviewer.
   Native review supplies general code-review evidence; QA verifies findings and source/evidence,
   then supplements uncovered project-acceptance constraints without another complete generic review.
   Keep actual method capability, fixed scope, effective model/effort, read-only permissions and any
   preceding-method technical unavailability in the existing `review_method` evidence.
   Do not wait for
   unrelated project work.
   QA receives the approved contract, applicable concrete page links/fingerprints, diff, current self-contained
   schema 2 QA pack and necessary approval/standards authority, without full sibling tasks or conversations.
   A new Reviewer must not inherit parent history. Bind the current QA pack's request/task/alias/agent_ref
   and byte SHA through schema_version:2 and handoff_ref. QA also receives evidence references,
   any task-relevant start-mode `memory_context` that actually exists, and the
   Skill policy. The absence of `memory_context` when no retrieval ran is not a QA finding. QA
   applies `xy-qa-review` as its
   base procedure and matches optional specialist Skills to `audit_surfaces` on demand.
   QA independently checks source, standards and evidence validity, reusing still-valid test results;
   new execution fills only actual gaps. Request-wide unified QA defines review scope, not a demand to
   run every test in the project.
   An unavailable required Skill blocks PASS; missing optional coverage remains explicit.
   Freeze each root or nested repository as an explicit base/head range, changed-path list, and
   SHA-256 diff fingerprint. Validate QA's internal changed-path classifications and per-rule
   standards evidence with `qa_handoff_cli.py validate --input RESULT --task-pack CURRENT_QA_PACK`; raw scope and coverage JSON stay internal.
   Isolated work also requires the pinned integration verification described in
   [worktree delivery](worktree-delivery.md); QA reviews the composed result, not separate branch PASSes.
   For a required prototype, deterministic validation may read the complete dependency bytes and
   recompute its fingerprint, but the QA Agent must not preload or manually read the complete
   prototype dependency tree. It consumes the frozen designer evidence and exact in-page contract,
   opens only the smallest relevant source slice, and audits the production implementation. It does
   not open or automate the prototype. Missing or stale design evidence returns
   FAIL to the PM for `xy-uiux` rework. A waived route skips prototype authority checks and still
   performs full production ui and accessibility QA. Risk-based browser testing of the real
   production implementation remains available.
5. QA PASS permits closeout only after that validation succeeds. QA FAIL or an invalid PASS returns
   only to the PM. PM dispatches bounded rework to its original author under existing recovery boundaries. The same independent
   reviewer rechecks the findings, repair delta and actually affected contracts; it does not restart
   the unchanged full audit. Bind the latest complete request scope, refresh affected rule checks
   and evidence, reuse unaffected conclusions, and run the existing handoff validation again.
   Expand only for a concrete new risk, invalidated evidence or explicit user/project requirement;
   after three failed rework rounds, escalate to the user rather than looping.
   Continued rework needs a new diagnosis, testable hypothesis or effective repair progress and expected
   evidence. Without progress, first stop the current repeated failing path and return it to PM; this is
   not success, and new progress does not reset or stack the three-round limit above.
6. After QA PASS, activate `xy-project-memory` in closeout mode and apply the frozen
   controlled-document projection when required. Verify current links and removal naming; perform the PM commit assessment above,
   then finish truthful memory persistence against the resulting
   revision. Preserve complete logs/results and close natively under the instance lifecycle; without tools,
   irreversibly retire only, without claiming erasure/released capacity or unlocking active tasks.
   Finally report to the user.

The closeout order is `QA PASS -> controlled-document projection -> PM commit assessment -> memory closeout -> final report`.
For a selected worktree route, apply [worktree delivery](worktree-delivery.md) within closeout:
pin the final reviewed candidate and complete confirm/auto local merge before memory/final completion.
Never create a separate QA
Markdown report merely to carry the concise QA result.

Keep raw exploration, command output, and full logs in subagent threads or ignored
local artifacts. Return distilled evidence and resolvable references to the PM.
