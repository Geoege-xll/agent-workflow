# Requirement Plans, Recovery and Change Handoff

Use when deciding whether to save a plan, revising an approved request, or resuming related unfinished
work. This supports the 2.0 Light/Full routes; it adds no role, confirmation gate or
automatic memory call. Explicit task-scoped workflow opt-out and save/no-save instructions prevail;
applicable project constraints and permission boundaries still apply.

## Save by task level

- Light: do not create a plan by default. PM saves a short recovery plan only for an actual pause,
  cross-session continuation, handoff need, or explicit user request. Saving does not upgrade Light
  to Full, activate Full planning Skills, require a DAG, repeat existing authorization or force independent QA.
- Full: after requirements approval and any applicable prototype choice, PM saves the approved
  current plan under adapter-resolved `docs.plans` before the first design or implementation dispatch.
  xy-plan still only drafts; PM owns persistence. Do not wait for visual approval to save the plan.

Full 正式审阅用 HTML：批准前由 PM 在当前请求 scratch 形成唯一 Markdown 草案并渲染；
批准后才保存 `docs.plans/<name>.md` 并生成同名 `.html`。Markdown 是唯一编辑权威，
变动后在同路径重渲染；具体命令、草案链接基准与失败保护见
[需求 HTML 交付](../../xy-plan/references/requirement-html.md)。Light 按已有保存/复杂度/用户
要求选用，不因生成 HTML 升级流程。页面、勾选或新鲜度检查均不产生批准。

一个稳定主题只维护一份生命周期 Markdown 及其派生 HTML。再次迭代、视觉调整、实施分工或
QA 返工原地更新，不创建版本副本；独立主题才各有文档。Light 是否保存仍按实际必要性，
旧主题曾用 Full 不会令本次无关小修自动继承 Full。

标准模板在 `templates/docs/PLAN.md`，使用普通 Markdown 元信息（不使用 frontmatter）：
`主题 ID`、`阶段`、`模块`、`任务等级`、`已验收版本`。阶段仅取 draft／active／paused／
completed／cancelled／removed；任务等级为 Full／Light；未有真实基线的已验收版本为 `none`。
Full 六节依次为“目标与范围”“需求与验收”“方案与原型关联”“当前进展与恢复入口”
“验收结果与当前已交付行为”“批准依据与必要证据”。最后一节的“批准依据”“验收证据”
引用真实可恢复来源，不能将模板、非空清单或阶段标签当成授权。Light 无基线恢复稿按必要性简化，
不额外建文档或确认；被 PROJECT 当作当前基线引用时仍须明确版本、已交付行为和既有证据。
只在保存实际主题时创建目录；安装不制造需求页、空索引或 plans／features 占位目录。

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

当前计划中的恢复状态和已有启动／交接简报都原地更新：保留当前批准范围、必要已完成
基线、未验证内容、剩余工作、阻塞及下一步，替换已被新事实取代的状态；不要每完成一批
就追加一段完成明细，使启动简报成为累计历史。必要完成基线可简述并链接现有计划、
功能真相与完整证据，读者无需遍历旧批次才能确认下一步；不另建简报副本或归档树，
也不设硬行数／token 门槛。计划仍由 PM 独占维护，简报不成为第二份任务状态或功能规范。

收敛前先确认完整日志、原始批准及唯一历史能从现有证据落点或真实版本历史恢复，并
修复受影响引用；摘要不能替代完整证据。Git 不保护未提交／未跟踪内容或非 Git 原始资料。
不能安全移交或确认可恢复时保留原文，明确标出其历史边界与当前恢复入口，不删除用户
文档或唯一历史，也不为整理新增 QA 报告、账本或确认阶段。

Record the requirement confirmation source and scope, prototype choice, and any still-pending UI
decisions. When a concrete prototype is approved, retain its page/scope, approval source and dependency
fingerprint in this same plan; do not create a companion approval record. If approval evidence is not
recoverable, mark that gap rather than declaring the gate approved from a status label alone.
Do not expose raw DAG JSON, YAML, hashes or full Task Packs in normal user feedback.

PM is the sole plan writer. Workers and QA return scoped results/evidence; they do not race on the
plan. Update on meaningful decisions, completed deliverables, blockers, rework or pause/handoff, not
every tool call. Preserve an accurate checkpoint during long work; do not rely solely on a final save
that may never run. File persistence does not imply permission to commit, publish, or execute it.
设计 Agent 在原交接返回 REQ 编号到具体原型页/实际状态锚点的覆盖，PM 写回这份原稿并
重渲染；不另建映射表文件或原型 QA。纯进度/链接/呈现变化不自动重开需求批准，
HTML 字节新鲜度、requirements_fingerprint 和原型依赖指纹分别保持原职责。

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
已验收基线／PROJECT 仍只通过 the existing post-QA projection below.

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
实施者、分级及例外来源按 `.agent-workflow/product/WORKFLOW.md#implementation-ownership`
核对；只有同任务连续实现或短返工可沿用可用原实例和有效证据，独立任务新实例／ID。
压缩摘要不创造PM实施授权或改变原等级，不复制PM／兄弟完整会话。原生结束／退役、
取消／失效边界按WORKFLOW实例生命周期及当前宿主细则，保留已有成果与必要完整日志。
Restore the current remaining graph from verified facts; the transient CLI snapshot is not the only
carrier of outstanding decisions or work. Report the smallest missing approval or fact when needed.

## Closeout and document boundaries

- PROJECT 是当前概况与已验收基线目录；同主题只有一份 plans 原稿，不按修订追加索引。
- 正在迭代时更新前四节与当前阶段，保留第五节上次已验收行为、已验收版本和对应证据。
  active／paused／cancelled 均不能把本次新目标冒充交付；`completed` 本身不授信。
- Full 在适用 QA PASS 后、Light 在实际必要验证接收后才替换基线；无事实变化不制造文档投影。
  只有明确已验收版本和真实依据的稿件可列入 PROJECT；验收失败保留原基线。
- 已验收删除在同稿标记 removed，保留必要日期、原因、替代与历史，移除当前索引，不改名或另写 feature／ADR。
- 未索引旧执行稿保持历史边界；不按 completed 自动索引，不批改历史，不默认重放旧任务。
  同名 HTML 是原稿投影，不能成为第二份规范或批准来源。
- 旧 `docs.features` 和 FEATURE 模板不在新运行时合同中；已有项目先按 README 的显式单次迁移路径
  保全正文、批准／证据和索引引用，冲突或不明主题关系先停。标准与记忆仍各按实际变化处理。
