---
name: xy-workflow
description: "编排2.0 Light／Full实施、UI变更与未完成工作恢复，按风险选择当前任务包、原生实施者和验收；只读审计使用独立分支。"
---

<!-- agent-workflow-pack:managed-skill -->

# xy-workflow

仅接受 2.0 Light／Full 和 `schema_version: 2`。代码修改沿用 `xy-code-standards` 的
适用方法与规范；两等级都默认原生实施者。PM 例外、独立上下文和实例收口统一遵守
`.agent-workflow/product/WORKFLOW.md#implementation-ownership` 与 `#agent-instance-lifecycle`。

## Standalone read-only audit

Before implementation routing, apply WORKFLOW's `Standalone read-only audit` when the task only
asks for audit findings, not implementation acceptance or fixes. Deliver the scoped conclusion and
stop; do not create writers, BUILD_VERIFIED, an implementation QA PASS or a second audit of the
report. Honor explicitly requested independent/full re-review and mandatory project checks. If fixes
are authorized, route their actual implementation normally. QA being read-only does not exempt
Full implementation or actual Light acceptance requiring QA from current scope/standards and handoff validation.

## Light 与 Full

派发前先判断目标、实际消费者、范围、风险与实施者。Light 使用当前自包含单任务包，
默认派对应原生实施者并做最小充分验证；明确用户指令已授权当前范围时不重复确认。
不强制 Grill Me、xy-plan、DAG、保存计划或独立 QA。交接时按实际风险评估独立审计、
文档与记忆，执行选定必需项；未执行 QA 不能写 QA PASS。普通 UI 文案按 WORKFLOW 的
`Light UI copy`核对真实消费者／语义／资源验证；使用production_ui＋UI-Conformance、
零设计差量和当前已解析冻结权威，不标non_ui避过工程／设计规范。实际设计／交互变化Full。
共享合同、数据、根配置、多角色或实际 UI 设计变化使用 Full，保留下面的完整路线。
不能把危险工作拆成 Light 规避确认，不能以交接评估跳过 Full 唯一独立 QA。

每个新实现者或 QA 都只能接收当前任务包；禁止复制完整 PM／兄弟会话或使用继承父历史的
fork。同一任务连续实现、短返工及同轮原 Reviewer 的差量复查可续用，独立任务使用新
实例／ID。接收与证据保护后及时原生结束，缺能力只退役阻止误派；不声称清空历史或释放
未确认容量。完整生命周期按上述产品权威，操作时再读当前宿主细则，不增加 Agent 池。

## 适用专业分支

For initial/revised design standards or a visual-system replacement, read
[design-standards.md](references/design-standards.md). PM assesses standard updates separately from
PROJECT/plans 基线投影; UI Agent writes authorized leaves, PM adopts scope and refreshes affected
authority, implementation roles own production tokens/components, and QA audits independently.
No reusable rule change means no update. `xy-uiux + design_ui` supports `design_mode: standards_only`
for exact normative Markdown leaves without prototype writes, `xy-prototype-verify`, or visual gates.
Existing user confirmation stages are unchanged; adopted design rules do not imply migrated production.

Use `.agent-workflow/product/WORKFLOW.md` as the canonical product procedure and
`.agent-workflow/project.yaml` as the project adapter.

中央模式先按 WORKFLOW 的“中央固定版本与项目适配器”验证本机启用；宿主 Skill 软链
只能帮助发现入口，克隆后缺机器 binding 不能自动编排。新图／单包固定严格三字段
`runtime_binding`，现有任务换版、缺 pin、冲突或损坏不回退。每次读取受管正文或执行
helper 都按当前包 pin 使用下面链接的统一桥执行边界，不能因项目当前 Skill 已换版
而改读或执行新版；不假定上一工具调用留下的 shell 环境仍存在。源包／旧自包含入口
保留原用法，中央适配器始终属于实际项目 `.agent-workflow/project.yaml`。

Full 需求以 HTML 正式审阅，模型只维护一份 Markdown；PM 按
[需求 HTML 交付](../xy-plan/references/requirement-html.md) 处理批准前 scratch 草案、批准后
plans 同名 `.md`/`.html` 与原型覆盖回写。HTML 新鲜度不创建批准，也不替代需求/原型指纹。

Use host-native aliases only when explicit activation is needed. Examples:
`xy-project-memory` (Codex: `$xy-project-memory`; Claude Code: `/xy-project-memory`;
Antigravity CLI: `/xy-project-memory`) and `xy-build-verify` (Codex:
`$xy-build-verify`; Claude Code: `/xy-build-verify`; Antigravity CLI:
`/xy-build-verify`). The procedure below otherwise uses host-neutral Skill names.

## Main-session contract

- Project Hooks are advisory activation/recovery reminders, not a workflow execution engine.
  They never establish task level, approval, QA PASS, permissions or completion. Missing/disabled
  Hooks do not disable this Skill. Continue related work using current context and valid evidence;
  do not restart an earlier completed task just because this Skill or a Hook is invoked again.

- 每位 Agent 独立完整读取当前任务包、必需 Skill／指令及适用规范；同一实例中已完整
  可用且版本未变的正文直接复用，不因同版本包改用文件传输而重读。缺失、截断、压缩
  或变化时恢复受影响内容，显式宿主／Skill 重读要求仍保留。详细复用边界及可选分页器见
  [完整读取必需长文](references/runtime-records.md#完整读取必需长文)；不新增读取账本或
  必跑门禁。普通业务资料仍按需；机器字节核验／指纹不代替当前 Agent 读取必需正文。
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
- Light／Full 默认派对应原生 subagent；只有用户明确指定 PM 本身亲自实施当前范围时
  例外。PM 只维护协调与其拥有的文档，例外不降低原等级门槛；摘要不创造授权或降级。
- The default business confirmations are `requirements_approved` and, for required-prototype UI
  design-change work, `visual_approved`. A proven `UI-Conformance` request has no visual
  confirmation because it makes no design decision; a user-selected direct-development branch also
  has no visual gate for its exact surfaces. The PM recommends but never selects or invents either
  design-change branch. A task-scoped structured exception is allowed only under the policy below.
- Full 与实际要求审计的 Light 使用唯一 `xy-qa` after implementation. It does not command implementers or edit
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

进行 Light／Full 接收与派发时，读取 [dispatch procedure](references/dispatch.md)。
It preserves Full Grill Me → xy-plan draft → PM projection decision → requirements approval →
approved-plan storage → validated READY dispatch. Do not dispatch before reading the applicable
contract. Light 使用该参考的轻量分支；文档与记忆仍按需，不进入 Full 图只是为了派发。

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

Light 缺陷完成最小验证后按风险交接评估；Full 使用 `request_unified_qa`。显式审查要求、
项目强制规则或实际风险仍选择必要独立审查，缺陷标签本身不强制 Full。 The bug label alone does not
upgrade the task or require Full planning, another approval, a saved plan, or documentation churn.

Review-feedback handling is not bug diagnosis. Treat external findings as advisory evidence: verify
them against current source, requirements, and tests before accepting or rejecting them.

## Default business confirmations and exceptions

这些确认适用于 Full；Light 已有明确范围授权时不重复确认，实质缺口只澄清受影响决定。

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

实施交接、返工或收口时，按当前等级读取
[implementation and QA](references/implementation-and-qa.md). Use exactly one read-only request
reviewer; preserve independent source/standards audit and valid evidence reuse. The same reviewer
checks affected repairs without restarting unchanged coverage. Light 先按实际风险评估是否需要
独立审计；只读审计交付结论后停止，不进入实现收口链。

<!-- workflow-contract: references/implementation-and-qa.md -->
