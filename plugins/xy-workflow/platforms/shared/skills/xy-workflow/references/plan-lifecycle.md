# Requirement Plans, Recovery and Change Handoff

Use when deciding whether to save a plan, revising an approved request, or resuming related unfinished
work. This supports the current Light/Full routes with schema 2 task packs; it adds no role, confirmation gate or
automatic memory call. Explicit task-scoped workflow opt-out and save/no-save instructions prevail;
applicable project constraints and permission boundaries still apply.

## 执行等级与批准稿去向

Light 仅在实际暂停、跨会话恢复、交接或用户指定保存时落稿。Full 用单一 Markdown 草稿正式审阅，批准前可放本请求的草稿区。需求范围明确后，PM 保存同一份可恢复原稿，给拟议方案与已确认方案标明各自状态；在每次相关设计或实现派发前补入刚生效的决定。用户明确的保存要求、工作流豁免及已有权限边界仍适用。保存本身不改变任务等级。

PM 在起草时根据本次会改变的事实选择归属。先查现有入口、主题及范围，再决定是否需要新页。

| 这次发生什么变化 | 原稿与长期知识写在哪里 |
| --- | --- |
| 已有业务能力、长期接口或架构取舍改变 | 在原主题原位更新本轮批准要求。保留上次真实已验收基线及对应证据，直到本轮实际验收。 |
| 出现需要单独查找、独立维护的新能力或跨主题决定 | 在适配器的 `docs.plans` 下创建一个稳定主题，从 PROJECT 的主题目录链接它；执行批次、任务编号和版本号不能单独构成建页理由。 |
| 只执行既定步骤、排查或修复不符合已有规定的行为，原业务事实未变 | Full 批准稿可放本请求已有的持久交接位置；让后续实例能按请求和已知路径取回完整原稿、批准范围、原始证据与下一步。确认保存期覆盖实际交接和恢复，清理前保留仍需使用的原件并修复引用。会话摘要、临时目录或可能随清理消失的 scratch 不能单独承担此职责。无需为这次任务新增业务主题。 |
| 项目特有规范或具体交互变化 | 项目长期规则写入对应规范叶子，STANDARDS 按适用范围链接；具体交互写入原型页面及状态。批准的任务原稿引用规则或页面，遵守原有所有权、采纳与验收顺序。 |

需要绑定原型评审时，选取 `docs.plans` 下范围相符的现有稳定主题作为批准源，确有独立新主题才新建。PM 保留可绑定的项目内 Markdown 路径、当前 REQ 定义、具体页及状态覆盖。实际要求原型的任务继续执行静态校验、依赖指纹和最终视觉确认；绑定来源的需要不能用临时交接链接替代。原型导航与历史 HTML 见[需求 Markdown](../../xy-plan/references/requirements-markdown.md)。

## 稳定主题的写法

`templates/docs/PLAN.md` 保留五个普通 Markdown 元信息字段：`主题 ID`、`阶段`、`模块`、`任务等级`、`已验收版本`。每项各填一个当前值。阶段使用 draft／active／paused／completed／cancelled／removed，任务等级为 Full 或 Light；没有已验收基线时版本为 `none`。

先说明当前可观察的行为及其边界。Full 原稿须有含实质内容的 `## 需求与验收`；用其余节表达实际需要。有已验收行为时，保留 `## 验收结果与当前已交付行为` 和 `## 批准依据与必要证据`，后者用 `批准依据`、`验收证据` 分别定位原始材料。需要恢复时用 `## 当前进展与恢复入口` 记录下一安全动作。只有确有取舍、范围或交互要展开时才单列方案等章节。旧六节稿可继续按原顺序读写，同一主题始终用同一路径。

一个长期事实只维护一份正文。项目内所有 Markdown 引用具体项目文档时，从引用所在文件写可点击的相对链接；指向具体章节必须带真实标题锚点或显式 ID，同页可直接用片段。链接文字说明关系，路径以实际目录为准。以下只示意表达方式，写入项目时须使用实际存在的目标。

```markdown
退款资格遵循[订单权限规则](../standards/ORDERS.md#退款资格)。
提交后的交互见[退款确认页的待审核状态](../standards/prototype/refund.html#pending)。
保留原订单号的决定依据见[订单标识规则的批准记录](order-identity.md#批准依据与必要证据)。
```

目录只负责发现，任务、规范和原型分别保留自己的正文。仅保存实际内容，安装不创建占位需求或空目录。

For drafting, substantive refinement, save/handoff self-check or the existing QA's plan review, read
[document quality](../../xy-plan/references/document-quality.md). It supplies section refinement and reader
checks without adding a reader Agent, report or approval gate. Apply the request’s scope, material-solution and page decisions as needed; format or wording fixes do not create a new business confirmation.

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

按已发生的阶段原位维护同一主题。需求范围明确后写目标、约束与可观察验收。涉及用户取舍时，写明拟议行为、正常状态、异常及后果；用户决定后以其原意更新同一段，注明适用范围和可恢复出处。若选择原型，再关联实际 HTML 页、状态锚点、覆盖的 REQ 及该版批准和依赖指纹。验收后更新已交付行为、已验证的当前做法，以及维护者能找到的源码和测试入口，明确仍未验证的范围。只修正既有间距且长期事实未变时复用现有依据和任务交接，无需新主题、空章节或单独批准日志。
Do not expose raw DAG JSON, YAML, hashes or full Task Packs in normal user feedback.

PM is the sole plan writer. Workers and QA return scoped results/evidence; they do not race on the
plan. Update on meaningful decisions, completed deliverables, blockers, rework or pause/handoff, not
every tool call. Preserve an accurate checkpoint during long work; do not rely solely on a final save
that may never run. File persistence does not imply permission to commit, publish, or execute it.
The design Agent returns coverage from REQ IDs to concrete prototype pages/actual state anchors in the original
handoff. PM writes it into this Markdown source, without generating HTML, a separate mapping file or
prototype QA. Progress, link or presentation-only changes do not automatically reopen requirements approval.
区分语义变更与文档投影。准备原型前，在既有请求证据或可恢复的版本历史中保全正式批准的原始 Markdown 字节、批准范围及来源。现行主题增补页面链接、进度或代码／测试定位时，旧批准和原型评审仍指向当时的原件。读取历史评审时沿用已登记的不可变快照；需要验证当前来源时仍比较实际规范路径及完整字节，不能以备份替代当前源。若当前稿有变，按既有指纹及等价性规则核实差异，需要新评审时重新捕获当前来源和页。不得把旧摘要改标为新文件的批准，也不能据一次文档投影重开无关业务决定。

## 定位现有主题

已知路径或章节时直接读相关原文。按问题从 PROJECT 的主题目录定位业务能力，从 STANDARDS 的规范目录定位适用规则。长文先看顶层标题，只沿相关分支列子标题，在目标节读直属正文；需要子节时才展开。[标题路径与分页](runtime-records.md#按当前合同读取长文)给出命令示例。目录或任务引用不足以确认原稿时，按稳定主题 ID 查询已选适配器的 `docs.plans`；查到同一主题就原位更新。
在工作流源码根执行以下命令。

```bash
bash lib/python_runtime.sh -B -X utf8 lib/validate_project_docs.py \
  --root PROJECT_ROOT --adapter SELECTED_ADAPTER --topic TOPIC_ID [--plan KNOWN_CANDIDATE ...]
```

安装插件时复用下文的 `helper`。查询只读取实际 plans 路径下 Git 已跟踪 Markdown 的首个可见 H2 之前的元信息，
围栏和 HTML 注释中的章节示例不会提前结束查询。
用 `--plan` 明确加入已知未跟踪稿；项目根无 Git 工作树时，必须显式指定已知候选。未找到只代表本次检索范围。
若多个文件匹配，或候选页首无法安全判定，先核实原稿再保存。查询只读候选的页首，无需读取 PROJECT、链接目标或候选正文。

需要判断哪些已知材料引用某个文件，或选中主题引用了哪些来源时，运行只读关系查询。

```bash
bash lib/python_runtime.sh -B -X utf8 lib/validate_project_docs.py \
  --root PROJECT_ROOT --adapter SELECTED_ADAPTER --relations TARGET [--source SOURCE] ... [--limit LIMIT]
```

目标为项目内普通非隐藏文件。默认检查目标 Markdown 的出链，以及 PROJECT、STANDARDS 直接列出的主题和规范中的一跳入链，旧目录也可使用。显式 `--source` 可将候选限定到最多 64 份已知 Markdown。HTML 等非 Markdown 目标仅检查入链。结果区分目录导航和正文引用，报告来源、行号、章节与链接携带的片段。根据 `sources_read`、`scope_truncated`、`results_truncated` 判断查了哪些资料、候选或显示数量是否截断。`--limit` 默认为 32，可选 1–100。复核影响时沿命中关系核对原文和实际消费者。某范围内无命中只能说明本次查询结果。

## Validate the selected saved plan

After initial persistence and after substantive updates or a handoff checkpoint, PM validates the current
selected plan(s), not every tool write or every historical plan. From the workflow source root, use:

```bash
bash lib/python_runtime.sh -B -X utf8 lib/validate_project_docs.py --root PROJECT_ROOT --plan PLAN_PATH [--plan PLAN_PATH ...]
```

插件模式先从已加载组件的物理位置确定当前插件根，遵守该根的 `PLUGIN.md`；
经同一插件的现有 helper 执行，不从业务项目推断插件位置或假定项目含复制的核心：

```bash
bash "<plugin-root>/lib/python_runtime.sh" -B -X utf8 "<plugin-root>/plugins/source_pack.py" \
  helper --project "<absolute-project>" lib/validate_project_docs.py \
  --root "<absolute-project>" --plan "<plan-path>" [--plan "<plan-path>" ...]
```

`--project` 指向真实业务项目的物理绝对目录，`--root` 指向同一项目根；
每个 `--plan` 选择该根下的计划。helper 校验当前物理插件的源包／载荷摘要并以该项目为 cwd，
不创建项目桥或 `.agent-workflow/lib`。No config or PROJECT file is required for this independent plan
format check. It checks only selected files and link/path safety, without reading link-target bodies,
scanning unselected plans or using the network. Explicit selection must not silently skip a new plan missing
metadata as historical material. The original two-positional-argument mode and its historical recognition
remain available for their existing callers. 同次选择同一物理文件可去重；若两个不同文件的主题 ID 大小写折叠后相同，校验失败。

有主题或其 PROJECT 目录项的实际变化时，用同一命令加上 `--adapter SELECTED_ADAPTER` 和一个或多个 `--plan PLAN_PATH`，定向核对选中节点与其对应的目录链接、锚点及明确的已验收声明。批准稿仅驻留于持久请求交接时按其实际位置核对内容、读取权限和恢复引用，避免把它注册成业务目录项。原两位置参数命令保留给明确的项目级校验。

普通 Markdown 的链接检查可单独运行。源码根的 `python3` 为 3.11 或更高版本时可用以下命令，也可用仓库的 `bash lib/python_runtime.sh -B -X utf8` 代替 `python3 -B` 选择已有解释器。每个 `--document` 只选择一份本轮改动的项目 Markdown 或需要复核的引用来源，路径相对项目根。安装包使用上文同一 helper，将 `--plan` 换为 `--document`。

```bash
python3 -B -m lib.validate_project_docs --root PROJECT_ROOT --document PATH [--document OTHER_PATH ...]
```

移动、重命名或删除文件与标题时，在编辑前按[文件引用关系](#定位现有主题)定位入链，并在已知受影响的项目资料中查找旧路径、文件名与片段。目录以外的来源可显式指定。修复实际引用，再用 `--document` 检查变动页和相关来源；单次一跳查询有范围和数量边界，不能据此推断全项目没有其他入链。

Return format failures to PM for in-place correction under the same scope, with actual command/exit/log
evidence; do not dispatch from a malformed selected Full plan. A successful check proves only its format/path
scope, not reader comprehension, approval, QA PASS or accepted delivery. Light retains its allowed simplified
recovery shape. Apply the reader check within existing PM self-check and the single QA when selected,
without a second gate or additional reviewer.

## Visual iteration and task replacement

1. Assess the actual impact of a proposed change before replacing approved requirements. Undecided
   alternatives remain explicitly pending; they must not silently override the approved baseline.
2. During prototype design/review, visual-only refinements within approved behavior update the
   prototype and only material plan implications. Keep concrete styling in the prototype/standards,
   not duplicated in the plan. Use the existing final visual confirmation; do not reopen requirements
   merely for a visual refinement. An explicit production-only revision during implementation or
   acceptance instead follows the cutover below; the old prototype choice is not perpetual authority.
3. A change to functionality, permissions, data/API contracts, acceptance or approved scope returns
   the affected scope or solution decision to the PM before its dependent design or implementation resumes. Preserve unrelated decisions and work.
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

恢复时复用同一实例中版本和范围仍匹配的资料。只缺下一步时，先定位当前主题的 `当前进展与恢复入口`
及阶段字段。对批准范围、已交付行为或证据另有疑问时，再展开相应原文和必要引用。主题路径未知时按
[定位现有主题](#定位现有主题)查找，并对照当前文件、原对话和任务状态核实。

Treat recorded completion and approval as evidence to verify, not as self-executing authorization.
Reuse completed work whose scope/artifacts/evidence remain valid; recheck or rework only affected or
uncertain parts. Do not replay the old plan from its first step, restart live workers, reconstruct stale
locks as active, or mark prior work failed just because its Agent session is no longer active.
Check implementer, classification and exception authority against
`product/WORKFLOW.md#implementation-ownership`. Only continuous implementation or short rework
of the same task may reuse the available original instance and valid evidence; independent tasks need new
instances/IDs. Compacted summaries do not authorize PM implementation or change the original level. Do not
copy full PM/sibling conversations. Native closure/retirement and cancellation/invalidation follow WORKFLOW's
instance lifecycle and current-host details, preserving existing results and necessary complete logs.
Restore the current remaining graph from verified facts; the transient CLI snapshot is not the only
carrier of outstanding decisions or work. Report the smallest missing approval or fact when needed.

## Closeout and document boundaries

- PROJECT 的 `## 主题目录` 每个现行主题只列一次，普通链接表示可查阅。新目录中，行首以“已验收：”标记的条目（如 `- 已验收：[主题](相对路径)`）才作已验收声明。旧 `## 当前已验收基线` 及主题目录之外的原有主题链接继续适用既有基线检查。已完成或取消且没有已验收基线的历史稿、已移除主题留在原址，撤下当前目录链接。声明须能追溯到同一主题的真实版本、交付行为及批准与验收原件。围栏示例和 HTML 注释不构成索引项。
- 本轮仅修改发生变化的条款。Full 经当前集成 QA PASS、Light 经必要验证及选定审查验收后，再更新已验收行为和必要目录声明。进行中、暂停或取消仍保留上次已验收基线；`completed` 自身不能证明交付。没有长期事实变化时，只完成请求交接。
- 当实际代码结构变化时，开发 Agent 在既有交接列出入口、模块或依赖的实际变动与源码位置，本轮已有 QA 独立核对。PM 据验收结果在 `docs/ARCHITECTURE.md` 原节更新当前结构，首次确需记录才创建。PROJECT 在项目简介处、主题目录之前链接该文件一次；业务主题需要结构依据时链接具体架构章节。初始化和无结构变化的任务无需创建架构文件或空链接。
- Mark accepted deletion as removed in the same source, retaining necessary dates, reason, replacement and
  history. Remove its current index entry; do not rename it or create a feature/ADR document.
- Unindexed old execution drafts retain historical boundaries. Do not auto-index by completed, bulk-edit
  history or replay old tasks by default. Existing same-name HTML is retained historical material after
  generation retirement; it is not a second standard or approval source.
- Old `docs.features` and FEATURE templates are outside the current runtime contract, and version 2.1
  provides no old-document conversion CLI. Preserve complete text, approvals/evidence and index references
  under README's document-protection boundary before removing rejected old keys; stop for conflicts or
  unclear topic relationships. Standards and memory still follow actual changes.
