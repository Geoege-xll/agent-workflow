## Implementation and QA loop

Light 使用当前单任务包、默认原生实施者及最小充分验证；交接时按实际风险评估独立 QA、
文档与记忆，不强制 Full 图或 QA。Full 使用下述图与唯一独立 QA 链；Light 实际需要 QA
时使用同一只读验收合同，不能把局部验证改写成 QA PASS。独立只读审计交付结论后停止，
不为审计报告创建实现者、BUILD_VERIFIED 或另一轮审计。

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

原型阶段由设计 Agent 三维自检并经用户最终确认，不进入独立原型 QA；下述统一 QA 仍审查
生产实现的功能、适用内置规则、项目特有规范与真实证据。项目索引物理不存在但无特有叶时，
按配置路径及 null 指纹绑定，不为 QA 新建 GENERAL/空索引或重复通用规则。
需求审阅 HTML 由唯一 Markdown 投影；实施者消费完整当前原稿/任务包，无需预载整份 HTML。
QA 按 [需求 HTML 交付](../../xy-plan/references/requirement-html.md) 核对受影响页新鲜度和
本稿实际原型引用，复用有效证据；不重扫原型树、增加批准或独立原型 QA。

### Execution and acceptance

下述图、qa-ready 与强制 QA 步骤适用于 Full；Light 仅使用其实际适用的验证、交接和审计分支。
两等级实例身份／上下文／结束边界统一按 WORKFLOW 的 `agent-instance-lifecycle`，不另建池。

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
   必需项通过即交接；新增测试、再次执行与继续失败返工均按该策略的三个判断说明信息
   增量，不能每个实现者默认全仓测试。无进展时提前交 PM，原自行修复上限不重置或叠加。
   配置、环境、数据与缓存复用，以及实际新增资源的归属与收口，沿该策略及内置
   `eng-common-030`，不在此另造资源规则。
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
   QA receives the approved contract, applicable concrete page links and fingerprints, diff,
   当前自包含2.0 QA包与必要批准／规范依据，不含兄弟完整任务或会话。新Reviewer不得继承父历史，
   并以schema_version:2及handoff_ref绑定当前QA包的请求／任务／别名／agent_ref与字节SHA。
   evidence references, any task-relevant start-mode `memory_context` that actually exists, and the
   Skill policy. The absence of `memory_context` when no retrieval ran is not a QA finding. QA
   applies `xy-qa-review` as its
   base procedure and matches optional specialist Skills to `audit_surfaces` on demand.
   QA 独立核对源码、规范与证据有效性，复用未失效的测试结果；新执行只补实际缺口。
   全请求统一 QA 是审查范围要求，不是运行整个项目所有测试的要求。
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
   only to the PM. PM 沿现有恢复边界把有界返工派回所属原作者。The same independent
   reviewer rechecks the findings, repair delta and actually affected contracts; it does not restart
   the unchanged full audit. Bind the latest complete request scope, refresh affected rule checks
   and evidence, reuse unaffected conclusions, and run the existing handoff validation again.
   Expand only for a concrete new risk, invalidated evidence or explicit user/project requirement;
   after three failed rework rounds, escalate to the user rather than looping.
   继续返工要有新定位、可检验假设或有效修复进展及预期证据；缺少进展先停当前重复失败
   路径并交 PM，不等同通过，也不因新进展重置或叠加上述三轮上限。
6. After QA PASS, activate `xy-project-memory` in closeout mode and apply the frozen
   controlled-document projection when required. Verify current links and removal naming; perform the PM commit assessment above,
   then finish truthful memory persistence against the resulting
   revision, 按实例生命周期保护完整日志与成果后原生结束；无工具只不可逆退役、不声称清空
   或释放容量，不解锁仍活动的任务。最后报告用户。

The closeout order is `QA PASS -> controlled-document projection -> PM commit assessment -> memory closeout -> final report`.
For a selected worktree route, apply [worktree delivery](worktree-delivery.md) within closeout:
pin the final reviewed candidate and complete confirm/auto local merge before memory/final completion.
Never create a separate QA
Markdown report merely to carry the concise QA result.

Keep raw exploration, command output, and full logs in subagent threads or ignored
local artifacts. Return distilled evidence and resolvable references to the PM.
