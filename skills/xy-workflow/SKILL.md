---
name: xy-workflow
description: "Orchestrate current Light／Full implementation, UI changes and recovery of unfinished work, selecting schema 2 task packs, native implementers and acceptance by risk; use a separate branch for read-only audits."
---

## 官方 Antigravity 插件资源边界

本段仅适配资源与原生传输，不授予业务批准、角色所有权或 QA PASS。
从已加载组件的物理路径解析插件根目录：技能目录上两级，`agents/`、`rules/`
目录上一级；禁止用项目 cwd 或猜测缓存路径。先读根目录 `PLUGIN.md`。
唯一流程依据是其中的 `product/WORKFLOW.md`、`roles/`、
`platforms/shared/skills/`，以下共享正文保持原样。
宿主读取如被截断，按缺失行范围续读，或复用包内已有分页 helper；完整连续覆盖
当前任务所需权威范围后才执行。不重复读取已覆盖内容，不自行实现另一套分页器。

历史 `.agent-workflow/` 资源引用改由本插件的 `plugins/source_pack.py resource`
解析。每次独立调用都使用：
`bash <plugin-root>/lib/python_runtime.sh -B -X utf8 <plugin-root>/plugins/source_pack.py`。
原有辅助命令使用 `helper --project <absolute-project> <original-helper> <arguments>`；
它只选已有 Python 3.11+，不安装软件、不改 PATH。项目文档、任务与业务代码仍属于
真实项目；包内示例不是当前项目配置。

通过同一 helper 调用 `plugins/project_context.py inspect`，复用已验证的
`project.yaml`，或显式 `apply` 新候选 `.awf/project.yaml`；历史配置路径随实际选择
转换。`init --adapter <selected-path>` 必须传入同一配置。此入口不创建文档、不授予
批准。需要宿主集成时读取 `platforms/antigravity/references/pm-integration.md`。
插件原生发现取代旧安装、刷新与中央激活；不得运行 `runtime install`、
`runtime activate`、项目注册、`setup_*.sh`，或创建/修改项目 `AGENTS.md`、
`CLAUDE.md`、`.agent-workflow` 来使插件生效。

主会话始终是 PM。工作代理只接收当前完整任务包，使用 `instance_policy: fresh`、
`context_policy: handoff_only`，不得继承 PM 或其他代理历史。仅官方宿主派发代理；
使用宿主默认或已配置的模型与推理设置。核心流程不依赖独立模型配置服务、网页或 MCP。
保留原有需求批准、适用的视觉批准与 Light 显式授权；需要独立 QA 时，仅一名只读
审查者，并遵守原有结项顺序。

Antigravity 通过本插件 `agents/` 原生发现角色。使用定义已核对到当前插件的原生
选择器；角色标签不证明实际角色、模型或上下文隔离。未知同名全局 `xy-*` 可能来自
旧流程，禁止据此作为本插件运行证据，或导入其中央 pin、历史与指令。若只能使用
通用原生入口，应以全新上下文交付当前完整角色正文与任务包；无法保证选择或隔离时
向 PM 报告宿主限制，不得宣称已运行。

当前 alpha 沿用未绑定的源包合同，拒绝中央 `runtime_binding` 与中央项目标记，
不自动迁移。活动任务期间不得更新/替换插件；跨更新资源保留与实际模型/effort
执行仍需真实宿主证明。未获得对应证据时保留 `runtime_verified: false`。


<!-- agent-workflow-pack:managed-skill -->

# xy-workflow

Accept only Light／Full and `schema_version: 2`. Code changes retain applicable methods and standards
from `xy-code-standards`; both levels default to native implementers. PM exceptions, independent context
and instance closure follow
`.agent-workflow/product/WORKFLOW.md#implementation-ownership` and `#agent-instance-lifecycle`.

## Standalone read-only audit

Before implementation routing, apply WORKFLOW's `Standalone read-only audit` when the task only
asks for audit findings, not implementation acceptance or fixes. Deliver the scoped conclusion and
stop; do not create writers, BUILD_VERIFIED, an implementation QA PASS or a second audit of the
report. Honor explicitly requested independent/full re-review and mandatory project checks. If fixes
are authorized, route their actual implementation normally. QA being read-only does not exempt
Full implementation or actual Light acceptance requiring QA from current scope/standards and handoff validation.

## Light and Full

Before dispatch, assess the goal, actual consumers, scope, risk and implementer. Light uses the current
self-contained single-task pack, defaults to the corresponding native implementer and minimum sufficient
verification, and does not repeat confirmation when an explicit user instruction already authorizes the
current scope. It does not force Grill Me, xy-plan, a DAG, a saved plan or independent QA. At handoff,
assess independent audit, documentation and memory by actual risk and complete selected mandatory items;
without actual QA, do not claim QA PASS. Ordinary UI copy follows WORKFLOW's `Light UI copy` real-consumer,
semantic and resource checks. Use production_ui＋UI-Conformance, zero design delta and current resolved,
frozen authority; do not label it non_ui to evade engineering/design standards. Actual design/interaction
changes are Full. Shared contracts, data, root configuration, multiple roles or actual UI design changes
use Full and retain the complete route below. Do not split risky work into Light to evade confirmation,
or use handoff assessment to skip Full's single independent QA.

Each new implementer/QA receives only the current task pack. Do not copy full PM/sibling conversations or
fork parent history. Continuous implementation, short rework of the same task and same-round delta review
by the original Reviewer may reuse the instance; independent tasks use new instances/IDs. Close natively
promptly after acceptance/evidence protection. Without that capability, retire only to prevent misdispatch;
do not claim erased history or released unconfirmed capacity. Follow the product authority above for the
full lifecycle, reading current-host details when operating; add no Agent pool.

## Applicable specialist branches

For initial/revised design standards or a visual-system replacement, read
[design-standards.md](references/design-standards.md). PM assesses standard updates separately from
PROJECT/plans baseline projection; UI Agent writes authorized leaves, PM adopts scope and refreshes affected
authority, implementation roles own production tokens/components, and QA audits independently.
No reusable rule change means no update. `xy-uiux + design_ui` supports `design_mode: standards_only`
for exact normative Markdown leaves without prototype writes, `xy-prototype-verify`, or visual gates.
Existing user confirmation stages are unchanged; adopted design rules do not imply migrated production.

Use `.agent-workflow/product/WORKFLOW.md` as the canonical product procedure and
`.agent-workflow/project.yaml` as the project adapter.

In central mode, first verify machine-local enablement under WORKFLOW's “Centrally Pinned Versions and
Project Adapters”. Host Skill symlinks aid discovery only; a clone without a machine binding cannot
orchestrate automatically. New graphs/single packs pin a strict three-field `runtime_binding`. Running
tasks do not switch versions, and missing pins, conflicts or corruption do not fall back. For each managed
read/helper execution, use the linked shared bridge boundary with the current pack's pin. A changed project
Skill version must not redirect reads/execution to a new version; do not assume shell environment survives
from a previous tool call. Source-pack development retains its source entry points; version 2.1 has no
old self-contained execution branch. The central adapter
always belongs to the actual project's `.agent-workflow/project.yaml`.

Formal Full requirements review uses one Markdown source. PM keeps any pre-approval draft in the current
request scratch, saves the approved plans `.md` before dispatch, and writes prototype coverage back to it.
Requirements/plan Markdown-to-HTML generation is retired under
[the retained reference](../xy-plan/references/requirements-markdown.md); preserve historical plan HTML and the active prototype workflow. Document existence creates no approval and replaces neither requirement nor prototype fingerprints.

Use host-native aliases only when explicit activation is needed. Examples:
`xy-project-memory` (Codex: `$xy-project-memory`; Claude Code: `/xy-project-memory`;
Antigravity CLI: `/xy-project-memory`) and `xy-build-verify` (Codex:
`$xy-build-verify`; Claude Code: `/xy-build-verify`; Antigravity CLI:
`/xy-build-verify`). The procedure below otherwise uses host-neutral Skill names.

## Main-session contract

- Keep accepting natural-language requirements while existing workers run. Apply
  `.agent-workflow/product/WORKFLOW.md#continuous-pm-intake` for independent requests, result reuse,
  same-task append, splitting and resource waiting; do not require users to supply IDs or manage Agents.
  Before dispatch, PM checks explicit current records and actual native occupancy through
  [shared dispatch](references/dispatch.md#continuous-intake-dispatch). Original records own state;
  separate requests keep their own approval, execution-resource authority and QA. For same-ID progress/append use the intent and
  verified capability query in [runtime records](references/runtime-records.md), never interrupt as steer.

- Project Hooks are advisory activation/recovery reminders, not a workflow execution engine.
  They never establish task level, approval, QA PASS, permissions or completion. Missing/disabled
  Hooks do not disable this Skill. Continue related work using current context and valid evidence;
  do not restart an earlier completed task just because this Skill or a Hook is invoked again.

- Each Agent independently reads the complete current task pack, required Skills/instructions and applicable
  standards. Reuse unchanged text already fully available in the same instance; file transport of the same
  pack version does not require rereading. Restore affected content when missing, truncated, compacted or
  changed. Explicit host/Skill reread requirements remain. See [complete reading of required long documents](references/runtime-records.md#完整读取必需长文)
  for reuse boundaries and the optional pager; add no reading ledger or mandatory gate. Ordinary business
  material remains on demand. Machine byte checks/fingerprints do not replace this Agent's required reading.
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
- Light／Full default to the corresponding native subagent, except when the user explicitly instructs PM
  itself to implement the current scope. PM maintains only coordination and its owned documents. The exception
  does not lower the original level's requirements; summaries create neither authorization nor downgrades.
- The default business confirmations are `requirements_approved` and, for required-prototype UI
  design-change work, `visual_approved`. A proven `UI-Conformance` request has no visual
  confirmation because it makes no design decision; a user-selected direct-development branch also
  has no visual gate for its exact surfaces. The PM recommends but never selects or invents either
  design-change branch. A task-scoped structured exception is allowed only under the policy below.
- Full and Light actually requiring audit use the single `xy-qa` after implementation. It does not command implementers or edit
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

For Light／Full intake and dispatch, read the [dispatch procedure](references/dispatch.md).
It preserves Full Grill Me → xy-plan draft → PM projection decision → requirements approval →
approved-plan storage → validated READY dispatch. Do not dispatch before reading the applicable
contract. Light uses that reference's lightweight branch; documentation/memory remain on demand. Do not enter a Full graph merely to dispatch.

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

Clear, reproducible Light bugs use `native_bug_fix` without Grill Me. A `Full` bug still
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

After minimum verification, Light defects assess handoff by risk; Full uses `request_unified_qa`. Explicit
review requests, mandatory project rules or actual risk still select necessary independent review. The defect
label itself does not force Full. The bug label alone does not
upgrade the task or require Full planning, another approval, a saved plan, or documentation churn.

Review-feedback handling is not bug diagnosis. Treat external findings as advisory evidence: verify
them against current source, requirements, and tests before accepting or rejecting them.

## Default business confirmations and exceptions

These confirmations apply to Full. Light with explicit scope authorization does not repeat confirmation;
clarify only affected decisions when material gaps exist.

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

For Full UI classification, prototype choice, design handoff or visual confirmation, read
[UI design branches](references/ui-design.md). Required prototypes retain exact page gates; conformance and scoped
user waivers do not inherit them. Production-only revisions use the current replacement authority.
Read [plan lifecycle](references/plan-lifecycle.md) when saving, revising or resuming a plan.

<!-- workflow-contract: references/ui-design.md -->

For the PM projection decision before requirements approval, or after verified QA for document
projection and commit assessment, read [closeout decisions](references/closeout.md). Assess first; do not update
PROJECT/plans merely to finish. Current truth changes only after verified implementation.

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

For implementation handoff, rework or closeout, read the current level's applicable branch of
[implementation and QA](references/implementation-and-qa.md). Use exactly one read-only request
reviewer; preserve independent source/standards audit and valid evidence reuse. The same reviewer
checks affected repairs without restarting unchanged coverage. Light first assesses independent-audit need
by actual risk. Read-only audits stop after delivering conclusions, without entering implementation closeout.

<!-- workflow-contract: references/implementation-and-qa.md -->
