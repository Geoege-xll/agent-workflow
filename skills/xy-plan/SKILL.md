---
name: xy-plan
description: Draft a Full request implementation plan after Grill Me coverage and before requirements approval.
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

公开插件身份与别名以 `product/command_identity.json` 为准：插件 `xy-workflow`，
发现入口 `xy-config`、`xy-grill-me`、`xy-grilling`、`xy-taste`、`xy-playwright`，
按实际发现格式调用；canonical原name只保留在非发现vendor。先完整读取薄adapter及其
canonical，不以未知全局同名Skill代替，不传播原版hooks/allowed-tools为额外权限。

主会话始终是 PM。工作代理只接收当前完整任务包，使用 `instance_policy: fresh`、
`context_policy: handoff_only`，不得继承 PM 或其他代理历史。仅官方宿主派发代理；
使用宿主默认或已配置的模型与推理设置；PM 按 dispatch reference 只读映射业务派发偏好。
核心流程不依赖独立模型配置服务、网页或 MCP。
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
  This is the PM record defined in `xy-workflow/references/requirements-intake.md`, produced from
  coverage via bundled upstream `grilling`; it is not an upstream Grill Me schema or approval.
  This Skill's availability does not force a plan/DAG on Light; schema 2 drafts/tasks express only the currently authorized Full scope.
- Produce a draft for PM review; the draft is not approval or execution authorization.
- This Skill must not edit files, dispatch Agents, update accepted PROJECT/plans baselines, or request approval.
- Do not create worktrees, commits, implementation branches, nested Agents, or another workflow.
- Identify controlled-document candidates, but leave the post-QA projection decision to the PM.
- This draft Skill does not persist files. After requirements approval PM saves Full plans under
  adapter-resolved `docs.plans` before first dispatch, following
  `.agent-workflow/platforms/shared/skills/xy-workflow/references/plan-lifecycle.md`.
- Formal Full requirements review uses one Markdown source. PM owns the pre-approval scratch draft
  and post-approval `.md` persistence before dispatch. Requirements/plan Markdown-to-HTML generation is retired;
  existing plan HTML remains historical material; prototype HTML and verification remain active under
  [the Markdown delivery reference](references/requirements-markdown.md). This Skill returns only a draft.
  Reserve concrete prototype page/state coverage with stable REQ IDs; page state is not approval.

## Drafting procedure

1. Map the affected modules, exact owned paths, existing interfaces, repository verification
   commands, and controlled-document reads before drawing task boundaries.
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
2. For every production UI task, classify `UI-Conformance` only with `design_delta: none`,
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
   Read `.agent-workflow/platforms/shared/skills/xy-workflow/references/design-standards.md` when relevant.
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
6. For each task, provide concrete verification commands and expected output. Apply
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

Before returning the Full draft, read [internal plan and task-graph contract](references/task-graph.md).
Return the complete internal record and a concise approval brief, keeping raw JSON/YAML hidden
unless requested. The PM, not this Skill, decides projection, resolves user choices, saves the
approved plan and dispatches.

<!-- workflow-contract: references/task-graph.md -->
<!-- workflow-contract: references/requirements-markdown.md -->
<!-- workflow-contract: references/document-quality.md -->
