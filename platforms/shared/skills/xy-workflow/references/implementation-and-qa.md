## Implementation and QA loop

Do not enter this loop for any locally verified Trivial work, including Trivial UI copy. Its applicable early exit above also
avoids the post-QA memory/projection loop; no QA result is synthesized to satisfy it.
Standalone read-only audit also stops at its scoped conclusion under WORKFLOW's corresponding
branch; this implementation loop does not audit that report again. A read-only reviewer performing
implementation acceptance still follows this loop and its full handoff requirements.

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

### Execution and acceptance

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
   生产实现须有受影响目标构建／编译成功及可运行证据。按其中的 `verification-scope.md`
   先选最小充分范围，明确需要新执行或可复用的证据。
   必需项通过即交接；扩大或重跑需说明具体缺口，不能每个实现者默认全仓测试。
4. Run `task_graph_cli.py qa-ready` for the request. Only `task_type: writer` tasks participate in
   this barrier; `evidence`, `read_only`, and `qa` tasks do not create a circular wait. When it
   returns true, dispatch exactly one integrated read-only `xy-qa` reviewer for this request. That same reviewer tries
   `host-native-review`, then one `installed-code-review-skill` proven installed and capable, then
   `internal-xy-qa-procedure`, moving forward only on technical unavailability. The allowed
   Superpowers option is only its installed `requesting-code-review/code-reviewer.md` prompt;
   Grill Me remains requirements-only. Findings or `FAIL` never switch review method or reviewer.
   Do not wait for
   unrelated project work.
   QA receives the approved contract, applicable concrete page links and fingerprints, diff,
   evidence references, any task-relevant start-mode `memory_context` that actually exists, and the
   Skill policy. The absence of `memory_context` when no retrieval ran is not a QA finding. QA
   applies `xy-qa-review` as its
   base procedure and matches optional specialist Skills to `audit_surfaces` on demand.
   QA 独立核对源码、规范与证据有效性，复用未失效的测试结果；新执行只补实际缺口。
   全请求统一 QA 是审查范围要求，不是运行整个项目所有测试的要求。
   An unavailable required Skill blocks PASS; missing optional coverage remains explicit.
   Freeze each root or nested repository as an explicit base/head range, changed-path list, and
   SHA-256 diff fingerprint. Validate QA's internal changed-path classifications and per-rule
   standards evidence with `qa_handoff_cli.py validate`; raw scope and coverage JSON stay internal.
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
   only to the PM, which issues bounded rework to the appropriate implementer. The same independent
   reviewer rechecks the findings, repair delta and actually affected contracts; it does not restart
   the unchanged full audit. Bind the latest complete request scope, refresh affected rule checks
   and evidence, reuse unaffected conclusions, and run the existing handoff validation again.
   Expand only for a concrete new risk, invalidated evidence or explicit user/project requirement;
   after three failed rework rounds, escalate to the user rather than looping.
6. After QA PASS, activate `xy-project-memory` in closeout mode and apply the frozen
   controlled-document projection when required. Verify current links and removal naming; perform the PM commit assessment above,
   then finish truthful memory persistence against the resulting
   revision, release agent threads, and report to the user.

The closeout order is `QA PASS -> controlled-document projection -> PM commit assessment -> memory closeout -> final report`.
For a selected worktree route, apply [worktree delivery](worktree-delivery.md) within closeout:
pin the final reviewed candidate and complete confirm/auto local merge before memory/final completion.
Never create a separate QA
Markdown report merely to carry the concise QA result.

Keep raw exploration, command output, and full logs in subagent threads or ignored
local artifacts. Return distilled evidence and resolvable references to the PM.
