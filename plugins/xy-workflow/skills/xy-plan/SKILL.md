---
name: xy-plan
description: Draft a Full implementation plan from the PM’s established requirements and acceptance evidence before requirements approval.
---

从本 Skill 的物理目录向上两级确定插件根。使用同包的[宿主资源说明](../../plugins/plugin-context.md)。当前实例已具备同一物理来源、同一版本的完整说明时直接复用；独立启动或内容缺失时补读，来源或版本变化时重新读取。


<!-- agent-workflow-pack:managed-skill -->

# xy-plan

Adapt the mature exactness and self-review ideas of Superpowers writing-plans to this pack's PM-owned
Task Pack and READY-DAG model. For plan drafting or substantive refinement, read
[document quality](references/document-quality.md): it adapts doc-coauthoring's section refinement and
reader checks within the existing PM/QA route, without adding interviews or approval stages.

```yaml
methodology_reference: superpowers-writing-plans
plan_owner: pm
plan_state: draft
```

## Boundaries

- Work only after `grill_result.readiness: ready_for_planning` for a Full request.
  The PM fills this internal record from established scope, impact and acceptance evidence under
  `xy-workflow/references/requirements-intake.md`. A clear Full request needs no interview.
  Include any earlier classification questions that were actually asked.
  This Skill's availability does not force a plan/DAG on Light; schema 2 drafts/tasks express only the currently authorized Full scope.
- Produce a draft for PM review; the draft is not approval or execution authorization.
- This Skill must not edit files, dispatch Agents, update accepted PROJECT/plans baselines, or request approval.
- Do not create worktrees, commits, implementation branches, nested Agents, or another workflow.
- Identify controlled-document candidates, but leave the post-QA projection decision to the PM.
- PM 在同一主题分阶段登记已确认的需求范围、实质方案与适用页面；首次设计或实现派发前保存已有决定。先判断原业务事实、项目规范或交互是否改变。已有主题原位更新，需要独立维护的新能力才建页。纯执行或符合性修复可用已有持久请求交接。原型须绑定项目内稳定批准源和当前有效 REQ。见[计划生命周期](../xy-workflow/references/plan-lifecycle.md)。
- Formal Full requirements review uses one Markdown source. PM owns the pre-approval scratch draft
  and post-approval `.md` persistence before dispatch. Requirements/plan Markdown-to-HTML generation is retired;
  existing plan HTML remains historical material; prototype HTML and verification remain active under
  [the Markdown delivery reference](references/requirements-markdown.md). This Skill returns only a draft.
  Reserve concrete prototype page/state coverage with stable REQ IDs; page state is not approval.

## Drafting procedure

1. Map the affected modules, exact owned paths, existing interfaces, repository verification
   commands, and controlled-document reads before drawing task boundaries.
   沿用[需求接单](../xy-workflow/references/requirements-intake.md)已核实且仍适用的定位与结论，
   只补齐会改变任务边界、接口、依赖或验证安排的事实。
   Resolve configured docs.standards/docs.standards_root once. Select applicable built-in sources for each Writer,
   then add project-specific leaves, binding current SHA, stable rule IDs and owned paths. Bind the real SHA
   when the project index exists. With no project leaves and a physically missing index, retain configured
   paths and record a null index fingerprint without creating an empty file. Use engineering for non_ui,
   engineering/design for production_ui, and design for xy-uiux + design_ui; do not preload the whole tree.
   Protected upstream roots, allowed extensions and exception grounds must come from actual project standards,
   not general sources or repository shape.
   For standards maintenance, follow WORKFLOW's `Standards document granularity and maintenance`:
   locate the existing topic and actual rule delta before proposing a new leaf; do not attach
   automatic documentation cleanup or a new rule document to every implementation task.
2. 对每个依赖实质分歧的任务，列明会改变验收或交付的可观察行为、状态、异常及技术选择。其余实现细节留给实现者。同请求已有明确决定时标出原意和适用边界；否则写为拟议方案和后果，由 PM 在相关设计或实施派发前取得决定。实际原型只呈现明确的行为。
   For every production UI task, classify `UI-Conformance` only with `design_delta: none`,
   structured resolved and SHA-256-frozen `design_authority_refs`, no design-workspace write, and no
   unresolved design choice; record `prototype_policy: not_applicable`. Otherwise use the explicit
   `UI-Patch`, `UI-Page`, or `UI-Flow` route. For those routes, identify exact affected surfaces,
   recommend `required` or `waived_by_user` with one task-specific reason, and draft the consequences
   of both choices. Do not treat the recommendation as the user's selection and do not make either
   conditional branch dispatchable. After requirements confirmation, the PM materializes only the
   selected branch and adds the scope-bound `prototype_decision`. The `required` branch adds a
   matching `xy-uiux` dependency and page-fingerprint-bound visual Gate. The `waived_by_user` branch
   has no prototype-design dependency, prototype write, prototype authority, or visual gate. Both retain
   full production ui and accessibility QA.
   Independently identify initial, incremental, replacement, or unnecessary design-standard updates;
   a PROJECT/feature no-op does not decide this question. Use the existing `input_contracts` and
   `output_contracts` for scope, approval basis, replaced/retained rules, ownership and adoption order.
   Read `platforms/shared/skills/xy-workflow/references/design-standards.md` when relevant.
   A necessary `xy-uiux + design_ui` standards task uses `design_mode: standards_only`, exact standard
   Markdown leaves, and no visual gate/prototype procedure. Waived production may depend on it;
   required production still needs a genuine prototype task. Schedule shared-rule adoption and PM
   fingerprint refresh before affected consumers, preserving unrelated work and existing approvals.
3. Split tasks by independently testable deliverables. Keep setup, configuration, documentation,
   and tests with the deliverable that needs them; do not create administrative microtasks.
4. State exact consumes/produces interfaces so isolated workers do not invent neighboring names,
   types, schemas, or protocol behavior.
5. Add `depends_on`, `blocks`, business or safety `gates`, `semantic_locks`, and proposed parallel
   lanes. A shared contract, database schema, root configuration, or shared UI token is a semantic
   dependency even when file paths differ.
   For multiple independent functional units, propose worktree isolation and the adapter's confirm/auto
   delivery policy using `xy-workflow/references/worktree-delivery.md`. Include the common base,
   prerequisite handoffs, integration owner and cross-feature verification. PM resolves Git facts
   before execution; this draft Skill still creates no worktrees, commits or user confirmations.
6. For each task, provide concrete verification commands and expected output. Identify the affected behavior or build/resource inputs for each check and the source of any requirement to run it on every revision. Use separate repository-supported checks when their inputs differ. Apply
   `xy-build-verify/references/verification-scope.md` from the installed Skill directory; discovered
   commands are candidates and selected checks must cover actual risk and mandatory rules. Reuse
   sufficient existing coverage first. Only when a concrete regression-coverage gap needs a test,
   prefer proving that regression before implementation in an existing suitable test file; otherwise
   name the strongest repository-native evidence. Do not require new tests or test files per task.
7. Include no placeholders such as TBD, generic "add validation", "handle edge cases", or "write
   tests". Name the behavior, boundary, command, and expected evidence.
8. Self-review requirement coverage, task independence, interface consistency, path/semantic
   conflicts, verification completeness, and missing failure cases. Apply the document-quality
   reader check to this draft, fixing gaps inline for the PM; do not launch a reader Agent or gate.

## Output projections

Before returning the Full draft, use the [internal plan and task-graph contract](references/task-graph.md) to check the applicable projections. During recovery, use the current pack and draft first. For a missing field or decision, read the relevant section (planning record, approval brief, graph example, design authority, or single-task handoff).
Return the complete internal record and a concise approval brief, keeping raw JSON/YAML hidden
unless requested. The PM, not this Skill, decides projection, resolves user choices, saves the
approved plan and dispatches.

<!-- workflow-contract: references/task-graph.md -->
<!-- workflow-contract: references/requirements-markdown.md -->
<!-- workflow-contract: references/document-quality.md -->
