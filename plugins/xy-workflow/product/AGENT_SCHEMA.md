# Standardized Subagent Role Schema 2 (xy Team)

This schema adapts the [agency-agents](https://github.com/msitarzewski/agency-agents) model of
"narrow specialization + deliverables + workflow + success criteria" to this pack's
**host-discovered plugin roles and task-pack ownership**.

## 1. Role ID Conventions

| Rule | Description |
|:-----|:------------|
| Prefix | Always `xy-` |
| Naming | Lowercase kebab-case: `xy-web`, `xy-desktop`, `xy-backend`, `xy-apple`, `xy-android`, `xy-uiux`, `xy-qa` |
| Single responsibility | One role equals one delivery surface. `xy-desktop` owns complete Electron/Tauri applications, `xy-backend` covers backend and systems work across languages, and native platform roles remain separate |
| Enablement | The plugin ships all seven canonical roles. Repository modules guide PM selection; the current task pack grants exact write scope |

## 2. `ROLES.yaml` Metadata (Machine-Readable and Required)

Release instruction prose uses English. Communication and new code comments follow user and project language requirements; this project currently requires Chinese for both. Preserve the original format of machine-parsed stable fields, role/Skill IDs, enums, and existing fixed headings; language preferences do not authorize translating these interfaces or changing generation/parsing contracts for the three hosts.

```yaml
xy-example:
  description: One-sentence specialization used in the Claude agent description
  division: engineering | design | quality | architecture | product
  sandbox_key: xy-example          # Role key used to bind automatically discovered module scopes
  toolsets: write | read
  tags: [ios, android, flutter]    # Search and routing tags
  deliverables:                    # Artifact types that count as completion for this role
    - "Compilable mobile changes"
    - "Platform verification logs"
  claude_color: cyan
  claude_max_turns: 40
  claude_skills: []                # Hard-gate preload Skills required before this Claude role starts
  codex_effort: medium
  codex_sandbox: workspace-write
  nicknames: [Example, xy-example]
```

| Field | Purpose |
|:------|:--------|
| `division` | Department or function classification aligned with the agency division categories |
| `tags` | PM routing keywords such as mobile, ios, or api |
| `deliverables` | Acceptance-checklist hints for task packs |
| `toolsets` | Role capability class. Native tool allowlists and the current task pack constrain each Worker |
| `sandbox_key` | Role key used to bind automatically discovered module scopes as a soft preference |
| `claude_skills` | List only hard gates whose absence makes it unsafe for the role to start; optional specialist Skills are matched on demand by the Skill tool |

Each role may receive one or more normalized module roots from strict repository discovery. These
scopes support routing and context selection only; they never broaden exact task-pack `owned_paths`
or replace an explicit exceptional workspace override.

PM metadata is outside the ordinary role schema. The top-level `pm.toolsets: none` value describes
the main-session orchestrator and does not extend the role `toolsets` enum above.

Plugin role and Skill projection rules:

- Claude Worker definitions allow the Skill tool and exclude the Agent tool. The QA definition also excludes Edit and Write.
- All three packages use the same canonical role ID, such as `xy-web`. The host entry points below refer to paths relative to the verified plugin root.
- Implementation roles preload `xy-code-standards` and `xy-build-verify`; production UI reads
  the applicable `xy-ui-design` branch only when `surface_kind: production_ui`.
- `xy-web` 优先使用项目测试。仍需生产浏览器交互证据时，首选按需加载 `xy-playwright`。纯小程序逻辑使用项目与微信宿主工具。
- `xy-uiux` 固定预载 `xy-ui-design`，交付具体 HTML 原型时必须加载并执行 `xy-prototype-verify`。
  额外设计方法按[共享 Skill 选择规则](../platforms/shared/skills/xy-workflow/references/skill-selection.md)选用。
  `standards_only` 只验证设计规范文档。
- `xy-qa` preloads `xy-qa-review`; other local specialist Skills are matched on demand from
  `audit_surfaces` and are not written into the role manifest.
- QA consumes the same specialist methods read-only for actual code or UI review surfaces; pure-document/backend tasks do not preload complete UI text. Static bindings come from `lib/skills/role_skills.py`; metadata and current artifacts across all three hosts must match. Reading creates no new permissions or stages.
- Workers use the host's applicable permission prompts. Static module scopes only assist task routing.

| Host | PM entry point | Role artifacts | Core Skill artifacts |
|:-----|:---------------|:---------------|:---------------------|
| Codex | Trusted SessionStart Hook in `hooks/` or discovered `$xy-workflow:xy-workflow` | Full roles in `roles/`, Worker constraints, and opt-in native definitions prepared from `native-agent-templates/codex/` | `skills/xy-*/SKILL.md` |
| Claude Code | Plugin `settings.json` selects `agents/pm.md` | `agents/xy-*.md` | `skills/xy-*/SKILL.md` |
| Antigravity | Plugin `rules/AGENTS.md` | `agents/xy-*.md` | `skills/xy-*/SKILL.md` |

The built-in Skills have one authoritative source: `platforms/shared/skills/`. Host adapter layers
provide only native bootstrap behavior, Agent formats, tool policies, and invocation aliases. They
must not copy or fork the core workflow text.

## 3. Body Structure for `roles/xy-*.md` (Human-Readable Required Sections)

Align with agency-agents Persona + Operations, remove exaggerated personas, and retain executable
engineering instructions. Roles are defined by their delivery surface and repository-driven
expertise, not by hardcoded language or framework versions. Project-specific technology targets
belong in the applicable engineering leaf under `docs.standards_root` and executable repository configuration.

```markdown
---
name: xy-example
description: ... (include technology-stack keywords)
toolsets: [write]
workspace: inherit
---

# xy-example - Role Name

## 1. Identity and Professional Character
## 2. Core Mission
## 3. Repository-Driven Expertise
## 4. Critical Operating Rules
## 5. Task Intake Contract
## 6. Execution Workflow
## 7. Technical Deliverables
## 8. Verification and Evidence
## 9. Communication Style
## 10. Memory Contract
## 11. Success Criteria
## 12. Routing
```

Professional character must guide engineering judgment without role-play or marketing language.
Role bodies must not duplicate shared workflow, confirmation, QA, or memory authority. They define
only role-specific expertise, operating boundaries, deliverables, evidence, communication, and
routing. Success criteria come from approved project contracts and real verification; roles must not
invent SLOs, coverage targets, architecture migrations, or technology upgrades.

## 4. Relationship to Orchestration (Already Provided by This Pack)

The current workflow accepts only Light/Full and schema_version:2. Both levels default to native implementers; a PM exception must cover the current scope explicitly named by the user. Light hands off the current self-contained single-task pack and minimum verification, without mandatory DAGs, Full planning, or QA; assess independent audit and documentation by actual risk. Full retains approved planning, request scheduling, and exactly one independent QA. No current pack carries complete PM or sibling conversation history.

### Scheduling Fields (Machine-Readable Task-Pack Contract)

可选的顶层 `request_scope` 反映用户已明确委托的交付范围，取值为 `discussion_only`、
`prototype_only` 或 `implementation`。init 决策与导出的单包只写本请求一个值；Full 图以
`request_id` 为键，示例为 `"request_scope": {"checkout": "prototype_only"}`。同请求的当前
记录共享这一约定，缺字段的历史请求继续按其原始授权运行。既有批准数组按门禁名记录，两个独立
请求的可执行任务有同名门禁时，各自保留权威图，避免把其中一个请求的确认算给另一个请求。
同图可以记录尚无执行任务的讨论请求。新建相关任务和交接时从原始委托填写；
字段不授予写权限、替代需求确认或选择原型。仅讨论通常没有任务记录；仅原型委托在需求和所需方案获批后，通过任务池派发 `xy-uiux + design_ui` 原型 Writer。独立任务采用顶层 `request_scope: prototype_only` 的 Light 单包，已有 Full 依赖图沿用原图。每个设计实例只写其约定的原型子路径。交付与视觉确认后结束，
无生产 QA。完整实现沿用原有 Light／Full 及页面门禁。详见 [请求交付范围](WORKFLOW.md#request-delivery-scope)。

任务的 `verification_commands` 兼容命令字符串和 `{run, expected}`。当项目原生检查的相关文件可确切列举时，后者可选 `inputs`（项目相对文件路径数组）。该清单供逐命令核对字节变化；原生执行结果、环境、真实资源加载、用户或项目要求的重跑及独立 QA 仍按原验证合同判断。

Every schema 2 task carries the identity/context fields below. Dependency and graph-scheduling fields apply to Full; Light retains current task.state without creating a DAG for dispatch:

```yaml
id: <stable-id>
request_id: <stable-request-id>
workflow_level: Light | Full
module: .  # normalized project-relative module root
agent_alias: <stable-module-and-role-slot>
instance_policy: fresh
context_policy: handoff_only
task_type: writer | evidence | read_only | qa
role: <canonical xy-* role>
surface_kind: production_ui | design_ui | non_ui
design_mode: prototype | standards_only  # 仅用于 xy-uiux 的 design_ui Writer；只读咨询省略
depends_on: []       # Semantic prerequisite task IDs, never capacity waits
blocks: []           # Exact reverse edges for depends_on; the validator requires consistency
gates: []            # Supported business/safety gates only
# solution_decisions: [{id: retry-policy, content: 失败后允许手动重试一次}]  # 只列本任务依赖的实质方案
owned_paths: []      # Normalized project-relative ownership; ordered handoff may reuse a path
semantic_locks: []   # Shared contracts that cannot be changed concurrently
state: DECLARED      # Runtime dispatch state; saved plan keeps concise recoverable progress, not a second scheduler
qa_scope: request    # Current request dependency closure, not the entire project
# Optional, immutable, Full QA only; points to the same request's production UI Foundation writer.
# foundation_task_id: <foundation-writer-id>
# Only PM records this after checking actual native dispatch results; once bound, it cannot be changed/cleared.
# agent_ref: {host: codex, agent_id: <actual-native-id>}
```

For new-project Foundation work, the same QA node and original native Reviewer perform Foundation
and final request checkpoints. Feature writers depend on Foundation and require its protected PASS
receipt; they must not depend on the QA node. Exported QA packs derive top-level
`qa_checkpoint: {kind: foundation | request, writer_ids: [...]}` and `qa_checkpoint_fingerprint` from
the graph. `qa_scope` stays `request`. Exclusive `accept_foundation` binds current task-pack/handoff
original-byte SHA references, saves protected `foundation_receipt`, and returns QA to `DECLARED`
without retiring its identity or granting `QA_PASSED`. Final `accept_request` validates complete request
scope and saves protected `request_receipt` with `QA_PASSED`. Ordinary `set` cannot create either
receipt or this Foundation request's final PASS. These records prove mechanical evidence binding,
not native completion; PM must still observe that completion before releasing occupancy. No second QA
node, generic phase engine or user confirmation is introduced; existing recovery limits apply.

`agent_ref` accepts only host (codex/claude/antigravity) and agent_id (1..256 characters, without whitespace/control characters). The PM first claims actual RUNNING (or the applicable explicit QA execution state), freezes/exports the complete current pack without an as-yet-unknown native ID, creates the native instance with those bytes, then records its actual ID through a separate update; the same value is idempotent, but replacement/clearing is forbidden. Different tasks in the same graph, including historical completed tasks, cannot share an ID. Optional bool agent_retired defaults to false and may only become true; it prevents reuse but releases no active lock and does not prove native process termination.

Within one physical project and `request_id`, at most one `task_type: qa` task may be declared across
explicit current records and failed/passed/retired history. Original-Reviewer delta review reuses that task
and the same immutable `agent_ref`. If the instance is unavailable or retired, PM handles the existing
request's recovery/acceptance boundary; no automatic second QA task or identity replacement is allowed.
This rule does not add mandatory QA to Light.

agent_alias binds a normalized module and canonical role; independent tasks may reuse the responsibility alias, but require new instances/IDs. Short rework on the same task and same-round original-Reviewer delta checks may reuse an available original instance. The complete lifecycle is centralized in WORKFLOW's agent-instance-lifecycle: no complete parent/sibling history, inherited forks, prewarming, or pools; protect results, logs, and worktrees before actual native termination or retirement.
`continuation --input PACK_OR_GRAPH --task-id ID --host HOST --observed-state running|idle|cancelled|missing|unknown` returns advice only, without probing, dispatching, reviving cancellations, clearing history, or creating approval.

写入任务（`task_type: writer`）按需在 `solution_decisions` 逐项保存 `id` 和具体 `content`。未受实质决定影响的任务省略此字段；依赖同一决定的原型和实现 Writer 使用同一事项及内容。
现有初始化入口按这些事项补齐各 Writer 的 `gates`，每项格式为 `solution_approved:<id>@<sha256>`。标识使用 `[a-z0-9][a-z0-9._-]*`；
摘要是 `json.dumps([request_id, id, content], ensure_ascii=False, separators=(',', ':'))` 的 UTF-8 字节的 SHA-256 小写十六进制。
用户明确选定本请求的当前内容后，PM 通过既有 `update` 的独立 `approve_solutions` 补丁把完整门值记入 `approved_gates`，调用示例见[派发规则](../platforms/shared/skills/xy-workflow/references/dispatch.md)；裸 `solution_approved` 没有授权效力。
更新内容后使用新的摘要，只让依赖本事项的原型或生产工作等待新批准。用户撤回未执行的方案时，通过独立的 `revoke_solutions` 补丁撤回相同绑定；已有运行中或已交付的 Writer 使用此门时，更新被拒绝。已有明确授权可以出自同一简报的答复，应能追溯到用户同意的内容。

所有 Writer 正式交接及新登记 `RUNNING`、`BUILD_VERIFIED`、`QA_SCOPE_READY` 或 Writer 的 `QA` 时，都核对该任务声明的全部批准。Full 同时核对直接与间接依赖的当前交付、所需的 QA 回执和适用的 UI Foundation 阶段回执。已领取的 Writer 可以导出自己的包。Light 不声明图依赖，按自身声明的门核对。待决图仍可 `validate`、查询 `ready` 和修订，普通无实质方案的 Writer 继续沿用同一准入规则。

The dispatch envelope contains schema_version:2, task, applicable standards_contract, and necessary approval/UI evidence. Full uses `task --input GRAPH --task-id ID` to export only this task; Light uses `task --input PACK` to validate/return the same-shaped envelope without a Full graph. update/continuation reuse the single current record rather than creating a second Agent ledger. 接收方核对当前文件，依照 `controlled_document_access` 独立读完所需规范的适用条款、例外及必要依赖；明确要求全文的材料读完整份。 See xy-workflow/references/runtime-records.md for exact CLI arguments.

Full planned tasks require role, surface_kind, and qa_scope together; Light retains its canonical role and actual surface_kind without imposing Full closure fields for dispatch. Light UI permits only ordinary low-risk copy under UI-Conformance with actual current resolved authority; production UI still has engineering/design coverage, and design/interaction changes use Full. The runtime
snapshot also carries typed `ui_contract.prototype_paths` and derives the design-standard boundary
from `standards_contract.root/DESIGN_*.md` whenever any task is `production_ui` or `design_ui`; this makes both
the forbidden production boundary and allowed design-writer boundary deterministic CLI checks.
Every Writer in that graph which overlaps either boundary must be `xy-uiux + design_ui`, including
roleless, broadly scoped, direct-dependency, and transitive-dependency tasks.

Full 实施委托内的专业方案咨询须显式声明 `solution_consultation: true`，并使用 `task_type: read_only` 和空 `owned_paths`。工程角色使用 `non_ui`，设计角色使用 `xy-uiux + design_ui`。咨询任务省略 `design_mode`、`ui_change`、`standards_exceptions` 及 Writer 的方案事项和门值；结果用于 PM 推荐方案，沿用既有 `RESULT_VERIFIED` 结算。其他 `read_only` 或 `evidence` 任务可保留原有路径资源锁，锁不构成写入授权。实际字段用法见[只读咨询派发](../platforms/shared/skills/xy-workflow/references/dispatch.md#read-only-design-consultation)。

For an `xy-uiux + design_ui` Writer, omitted `design_mode` means `prototype`. `standards_only` restricts writes
to exact `DESIGN_*.md` leaves directly under the standards root, excluding prototype artifacts.
It still requires `requirements_approved`, current design reads and UI/accessibility/standards audit
surfaces, but no HTML, `xy-prototype-verify`, or visual gate. A waived production task may depend on
this maintenance; transitive prototype tasks remain forbidden. Required-prototype production must
still depend on a genuine prototype-mode task. The configured prototype path is only a protected
boundary for a standards-only request; no prototype artifact needs to exist.
Use `input_contracts`/`output_contracts` and PM plan state for standard-update assessment, scope,
approval basis, rule delta and adoption order, separately from feature-document projection. Follow
`platforms/shared/skills/xy-workflow/references/design-standards.md`; PM refreshes adopted standards
and affected consumer fingerprints without manufacturing user approval or completed migration.
Preserve original input contracts and recoverable before/diff evidence in the existing task evidence
before refreshing current `controlled_document_access`, including affected completed tasks still in
the graph. A snapshot refresh does not overwrite historical inputs, imply a past read of new rules,
or reopen a completed task. `design_standard` authority fingerprints must match the current same-path
leaf contract; prototype dependency fingerprints retain their separate meaning.

For Full work, the task graph comes from `xy-plan` with `plan_state: draft`. Before binding current scope authority to
`requirements_approved`, the PM reviews that draft and records the post-QA controlled-document
projection. After approval the PM freezes the requirements fingerprint, graph, and proposed
projection; canonical PROJECT/plans accepted-baseline truth is not changed until integrated QA PASS. The PM then
invokes:

```text
bash "<plugin-root>/lib/python_runtime.sh" -B -X utf8 "<plugin-root>/plugins/source_pack.py" helper --project "<absolute-project>" lib/task_graph_cli.py validate --input <runtime-task-graph.json>
bash "<plugin-root>/lib/python_runtime.sh" -B -X utf8 "<plugin-root>/plugins/source_pack.py" helper --project "<absolute-project>" lib/task_graph_cli.py ready --input <runtime-task-graph.json>
bash "<plugin-root>/lib/python_runtime.sh" -B -X utf8 "<plugin-root>/plugins/source_pack.py" helper --project "<absolute-project>" lib/task_graph_cli.py qa-ready --input <runtime-task-graph.json>
```

Every implementation task pack also declares the controlled-document decision:

```yaml
controlled_document_access:
  adapter: project.yaml
  documents:
    - path: <configured docs.* path>
      mode: targeted | full | skip
      reason: <task-specific justification>
      sections_or_queries: []
      content_fingerprint: <64-lowercase-hex-sha256>
      applies_to: []
      rule_ids: []
```

`project.yaml` is the fixed workflow-adapter read for paths, limits, and routing configuration.
Its `docs.*` paths are discoverable authorities, not a static preload list. The PM resolves
`docs.project` only when the task needs to locate or verify current
feature truth, then follows only task-relevant feature or other controlled-document links.
`targeted` is the default and
requires heading or keyword selection before detailed-body reading. `full` requires an explicit
whole-document justification. `skip` means the body must not be opened. Shared architecture details
and recovery plans are read only when relevant.
Every Writer independently reads applicable built-in engineering/UI sources and project-specific standards, following project-index links only when the index exists. non_ui uses engineering, production_ui uses both domains, and xy-uiux + design_ui uses design. Every selected source binds current SHA, applicable IDs, and owned paths; return missing/stale/insufficient coverage to the PM. index_path/root retain configured values; index_fingerprint is null only with no project rule leaves and a physically absent index, while an existing index binds actual SHA. Do not create an empty index or GENERAL. Write only the three canonical plugin-relative built-in paths in new records. Their source does not expand project write boundaries. init/document validation checks actual existence; JSON-only graph validation checks structure alone.

The runtime graph freezes one unified standards authority and any explicit protected upstream boundary:

```yaml
standards_contract:
  index_path: docs/STANDARDS.md
  root: docs/standards
  index_fingerprint: <actual-index-sha256-or-null-when-absent>
  required_engineering_rule_ids: []
  required_design_rule_ids: []
  leaves:
    - path: <exact-built-in-source or project-specific-leaf>
      domain: engineering | design
      content_fingerprint: <64-lowercase-hex-sha256>
      rule_ids: []
  protected_paths:
    - path: <protected-upstream-root>
      rule_id: <stable-hard-rule-id>
      direct_edit: forbidden_without_exception
      allowed_paths: []
```

Protected-path writes outside `allowed_paths` require a matching `standards_exceptions` record
with an `exceptional:<id>` Gate, exact patch surface, reason, rollback plan, and real verification
commands. Missing, skipped, stale, uncovered, or unapproved standards authority makes task-graph
validation fail. Every Writer declares `standards-conformance` in `audit_surfaces`.

Every production UI task pack declares both a scope route and an independent prototype policy.
`UI-Conformance` uses `not_applicable` only with a proven zero design delta. A design-change route
uses `required` or `waived_by_user` only after the PM recommends one branch and the user selects a
branch during requirements confirmation:

```yaml
ui_change:
  route: UI-Conformance | UI-Patch | UI-Page | UI-Flow
  design_delta: none | changed
  prototype_policy: not_applicable | required | waived_by_user
  prototype_decision: null | {
    source: requirements_confirmation_user_choice,
    choice_ref: user:<stable-reference>,
    requirement_fingerprint: <64-lowercase-hex-sha256>,
    affected_surfaces: [],
    recommended_policy: required | waived_by_user,
    recommendation_reason: <task-specific PM reason>,
    selected_policy: required | waived_by_user
  }
  design_authority_refs:
    - kind: controlled_document | prototype_contract | design_standard | production_baseline
      authority_id: <stable-lowercase-id>
      path: <normalized-project-relative-path>
      anchor: <heading-or-contract-anchor>
      content_fingerprint: <64-lowercase-hex-sha256>
      resolution_state: resolved
  affected_surfaces: []
  justification: <objective routing evidence>
```

For `route: UI-Conformance`, require `design_delta: none`, `prototype_policy: not_applicable`,
`prototype_decision: null`, structured resolved and fingerprinted
`design_authority_refs`, no unresolved design choice, no `xy-uiux` Writer dependency, no visual gate, and
no owned-path overlap with adapter-resolved `docs.standards_root/DESIGN_*.md`. The production
writer still carries `requirements_approved`, `xy-build-verify`, and both `ui` and `accessibility`
audit surfaces. A `prototype_contract` path must be inside `ui_contract.prototype_paths`; a
`design_standard` path must be a leaf under `standards_contract.root/DESIGN_*.md`, and paths in either typed
boundary cannot use another authority kind. Missing, stale, contradictory, or incomplete authority requires the PM to
reclassify the request as `UI-Patch`, `UI-Page`, or `UI-Flow` before the affected production write.
Those three routes use `design_delta: changed`. With `prototype_policy: required`, they depend on
the matching `xy-uiux` task and carry a resolved `prototype_contract`; each prototype authority maps
exactly to `visual_approved:<authority_id>@<content_fingerprint>`. The required branch still needs a
valid `prototype_decision`; prototype files or a PM default do not prove user choice.

For every `UI-Patch`, `UI-Page`, or `UI-Flow`, `prototype_decision.source` is exactly
`requirements_confirmation_user_choice`; the record binds a stable user choice reference and
current requirement fingerprint to exactly the same non-empty `affected_surfaces`. Its
`recommended_policy` may differ from `selected_policy`, but `selected_policy` must exactly match
`ui_change.prototype_policy`. The PM must not invent this record. The `waived_by_user` policy has no
prototype-design dependency, no prototype write, no `prototype_contract` authority, and no visual gate. It
retains `requirements_approved`, applicable scoped solution decisions, standards authority, build verification, and full ui and
accessibility QA. Existing prototype bytes remain untouched and are not current authority for the
waived scope.

当目标、业务规则、技术方案或原型有长期维护价值时，PM 在同一需求主题更新当前约定和已批准的页面链接；实现、测试、验收提供证据后，再补充已交付事实和后续维护入口。详见 [xy-plan 需求 Markdown](../platforms/shared/skills/xy-plan/references/requirements-markdown.md)。字段记录授权和执行证据；确认意向本身不足以更新已验收基线。

Full task packs declare the projection decision during planning; Light assesses actual needs at handoff without requiring the Full projection record in advance:

```yaml
controlled_document_projection:
  project_docs_update: required | not_required
  change_type: added | updated | replaced | reimplemented | removed | restored | split | merged | renamed | cancelled | none
  affected_features: []
  project_index_update: required | not_required
  reason: <why current verified project or feature truth changes or remains unchanged>
```

Use required only when verified current feature facts or the PROJECT index need changes; Full requires QA PASS, while Light completes acceptance of actually required verification/audit. A
major behavior-preserving rewrite may use `reimplemented`; routine refactors, dependency upgrades,
internal performance work, and pure visual styling use `not_required` with `change_type: none`
only when recorded current facts remain unchanged. A changed documented runtime/dependency baseline,
architecture rationale or scope requires the smallest in-place fact update, not a new document or log.
Every task pack still carries the approved goal, non-goals, constraints, acceptance evidence, and
applicable UI authority regardless of document projection. Required-prototype tasks carry concrete
pages; `UI-Conformance` tasks carry frozen `design_authority_refs`; `waived_by_user` tasks carry the
scope-bound `prototype_decision` and no prototype authority. Required-prototype tasks carry the same
decision record plus concrete page authority.

Full 经集成 QA PASS、Light 经必要验证和选定审查验收后，PM 才更新已验收版本和行为。`PROJECT.md` 的 `## 主题目录` 与 STANDARDS 的规范目录分别导航到业务与规则原文。目录收录可以发生在验收前；声称已验收须定位真实版本、行为及批准与验收原件。旧已验收目录维持相同证明要求。暂停、取消保留上次基线。完整移除经实际验收后在原主题标记 `removed`、保留原因、时间及替代关系，撤下当前入口。既有 HTML 作为历史材料保留。

Full 在批准后、首次设计或实现派发前保存一份可恢复的批准 Markdown。已有主题原地更新，独立新主题才建页。纯执行或纯符合性修复可以复用当前请求已有的持久交接位置；需绑定原型时须由配置的 `docs.plans` 内稳定原稿提供当前有效 REQ。Light 仅在暂停、恢复、交接或明确要求时保存。具体约定见[计划生命周期](../platforms/shared/skills/xy-workflow/references/plan-lifecycle.md)。旧 docs.features 的移除仍需按显式一次性迁移保护原件和引用。
Existing `input_contracts` carry its reference and current applicable scope; changes
replace affected complete task inputs and QA acceptance, not merely append amendments. Preserve
unaffected results and verify saved evidence on resumption. Follow the plan-lifecycle reference.

After the projection, the PM performs a local commit assessment before memory persistence and the
final report. The canonical order is `QA PASS -> controlled-document projection -> PM commit assessment -> memory closeout -> final report`.
This internal record is never presented as raw YAML:

```yaml
commit_decision:
  needed: true | false
  reason: <request-level evidence>
  repositories:
    - path: . | <nested-repository-path>
      action: committed | skipped | blocked
      scoped_paths: []
      staged_diff_fingerprint: null | <64-lowercase-hex-sha256>
      commit_revision: null | <full-commit-id>
      reason: <repository-specific evidence>
```

The PM commits only request-owned paths verified/accepted under the current level, plus validated controlled-document
projection, using exact pathspecs and complete staged-diff inspection. It must not stage unrelated or unverified changes,
must not use `git add -A` or `git add .`, and must preserve pre-existing user work. Unsafe overlap
yields `action: blocked`, not whole-file staging. Nested repositories are assessed independently
and deepest first. This automatic action does not create a business-confirmation stage or
authorize push, merge, tag, release, or another remote mutation.

For the selected worktree execution branch, `xy-workflow/references/worktree-delivery.md` explicitly
defines PM-local pre-QA transport checkpoints/integration and post-QA confirm/auto local delivery.
Those scoped exceptions do not grant workers commit/merge authority or authorize a remote operation.
Isolated writers carry `execution_workspace` with canonical root/base_revision/head_revision. Runtime
`worktree_integrations` is keyed by request ID and binds integration root/target_branch/target_base/
head_revision/verification. The same DAG validates these fields and keeps ordinary tasks unchanged.

The PM also records the review method used by the single `xy-qa` reviewer in the request QA
handoff. This is runtime routing evidence, not permission for `xy-qa` to delegate:

```yaml
qa_review_policy:
  owner: xy-qa
  max_active_reviewers: 1
  method_selection_order:
    - host-native-review
    - installed-code-review-skill
    - internal-xy-qa-procedure
  external_skill_selection: installed-and-capable-only
  superpowers_prompt: requesting-code-review/code-reviewer.md
  fallback_on_technical_unavailability_only: true
  findings_or_fail_do_not_trigger_fallback: true
review_method:
  selected: host-native-review | installed-code-review-skill | internal-xy-qa-procedure
  external_skill: null | <host-exposed installed code-review Skill identifier>
  capability_evidence: [<actual-capability-and-execution-evidence-reference>]
  fallback_reason: null | missing | launch-failed | timeout | malformed-output | unsafe-mutation | recursive-delegation
  scope_ref:
    repositories:
      - path: . | <nested-repository-path>
        base_revision: <fixed-base>
        head_revision: <fixed-head>
        diff_fingerprint: <64-lowercase-hex-sha256>
        changed_paths: []
```

All shown `review_method` fields are required. The handoff validator restricts `selected` to the
three methods, requires non-empty unique `capability_evidence` references, and permits a non-empty
`external_skill` only for the installed method; native/internal methods use `null`. Native selection
has `fallback_reason: null`; installed/internal selection needs one listed technical reason and
evidence explaining preceding methods' unavailability. Unpinned output is `malformed-output`;
findings or FAIL never justify fallback. PM/QA still verify referenced actual capabilities,
effective permissions/model/effort, fixed scope and execution: schema validity is not runtime proof.

When the same authorized native QA invocation supports structured output, obtain the current JSON Schema using `qa_handoff_cli.py schema`, then unpack successful terminal output with `extract --host H --input native-result.json` and apply existing handoff semantic validation; the original `validate` contract remains available. Successful transport structure is not QA PASS and does not replace real execution, fixed scope, or standards evidence. Codex exec uses `--output-schema` (review has no such flag), Claude uses `-p --json-schema`, and AGY uses `--json-schema`; still check the current version and permissions. Detailed terminal shapes and invocation paths live only in `xy-qa-review/references/inputs.md`. Task Packs are still mechanically exported through task-graph `task`; do not call another model or add a Reviewer to convert JSON.

普通后台 Reviewer 缺少结构化输出时，由原 Reviewer 提供已核对的分组判定和直接证据，PM 通过[固定回执构造](../platforms/shared/skills/xy-qa-review/references/inputs.md#固定回执构造)还原同一 schema 2 回执。

The implementation-acceptance handoff below does not apply to WORKFLOW's `Standalone read-only
audit` branch. An audit-only conclusion creates no writer/BUILD_VERIFIED or implementation QA PASS;
Full implementation and Light acceptance requiring independent QA still use the writer barrier and validated handoff.
On rework, the same reviewer checks findings and the affected delta, reuses unchanged conclusions,
and refreshes the latest complete scope and affected standards/evidence without restarting the full audit.

There is exactly one `xy-qa` reviewer. An external Skill is selected only when installed and proven
capable; the allowed Superpowers option uses only `requesting-code-review/code-reviewer.md` as that
same reviewer's prompt. No nested Reviewer is spawned, and Grill Me remains requirements-only.
Findings and `FAIL` are valid review results, not fallback reasons. An explicit high-risk
multi-review escalation is outside this ordinary method enum and requires PM-owned orchestration.

QA results use `schema_version: 2` and bind the current complete QA pack through `handoff_ref: {request_id, task_id, agent_alias, agent_ref: {host, agent_id}, task_pack_sha256}`. validate/extract must receive `--task-pack`; reject mismatched identity, request, alias, or pack SHA, and never bind old PASS to a new task. QA PASS also carries internal standards_policy_coverage, binding managed built-in sources, actual project leaves, and the index fingerprint when present (null with no leaves and an absent index),
Task Pack rule IDs, independently resolved engineering/design rule IDs, one classification for every
fixed changed path, and rule checks containing source paths/anchors, `hard | advisory` severity,
`pass | fail | not_applicable`, affected paths, and evidence references. If QA discovers an
applicable rule omitted from the Task Pack, it returns FAIL instead of silently repairing the
contract. The PM runs `qa_handoff_cli.py validate --input RESULT --task-pack CURRENT_QA_PACK`; incomplete coverage,
evidence-free applicable rules, scope mismatch, or any hard-rule failure makes PASS invalid. This
machine projection is never shown to the user as raw JSON or YAML.

`READY`, `RUNNING`, `BUILD_VERIFIED`, and `QA` are scheduler runtime facts in the runtime graph
snapshot, not independently maintained task-pack claims or PM completion lists.

The PM task pool locates the authoritative Light pack or Full graph. A pending withdrawal can end
as `WITHDRAWN` immediately. An allocated task enters `STOP_REQUESTED` and retains its occupancy until
the host outcome is established. The task's amendment and acknowledgement identify the revision and
the bound native agent. See the [record operations](../platforms/shared/skills/xy-workflow/references/runtime-records.md).

- `READY`: a derived queue membership: semantic dependencies and applicable gates are satisfied, so
  the task may be dispatched when capacity is available. Unmet, failed, or pending prerequisites
  keep the task out of READY instead of creating another task-state enum value. If no slot is
  available, record `capacity_delay`; never disguise it as a new semantic dependency.
- `RUNNING`: allocated for execution; an unbound claim is not proof a native worker started.
- `BUILD_VERIFIED`: the writer has completed and returned real build/test evidence.
- `QA`: unified QA is running on the current request dependency closure. The QA barrier includes
  only `task_type: writer`; read-only, evidence, and QA tasks cannot make it wait on itself.
- `QA_PASSED`: only an explicit `task_type: qa` node may use it, after its current PASS handoff validates.
  Re-review/failure resets its state; stale PASS cannot override a running or failed review at delivery.
- `RESULT_VERIFIED`: only `read_only`/`evidence`, after the exclusive evidence-bound record `settle`
  operation accepts the current result. It is neither Writer BUILD_VERIFIED nor implementation QA PASS.
  Bind the original native ID, latest accepted complete Task Pack bytes/SHA, real completion source,
  revised-scope result and actual declared verification evidence. An accepted first-dispatch pack may omit
  `agent_ref`; any included ID and both settlement/completion IDs must match the current immutable binding.
  Runtime/closeout `state`, `agent_ref`, `agent_retired`, `handoff_assessment` and `acceptance_evidence` do
  not redefine accepted implementation scope; task/request/role, ownership, contracts, validation,
  standards and approvals remain strict. Unknown/running or stale inputs remain
  active; retirement never completes them. Settlement atomically releases record execution occupancy,
  not unconfirmed native threads. See WORKFLOW's `Result-task settlement` and runtime-records for wire use.

The PM dispatches all currently ready independent tasks within configured limits and re-evaluates
downstream readiness after each completion. `depends_on` and `gates` are semantic dependency fields;
a capacity delay is not a dependency. UI gates block only tasks that declare a dependency on them.
A task failure blocks only its downstream dependents; unrelated branches continue. Unified QA for
`qa_scope: request` runs after every relevant writer in the current request dependency closure has
completed and been verified. It does not wait for all project work, and unrelated branches may
continue while request QA is pending. The complete current-request dependency closure is the QA
boundary; unrelated project work does not enter `qa_scope: request`.

Equivalently: UI gates only block tasks that declare a dependency; failures block only downstream
dependents; unrelated branches continue. The QA boundary is the current request dependency closure,
not all project work.

| agency-agents | This pack |
|:--------------|:----------|
| Agents Orchestrator persona | **Main-session PM** + native host `xy-workflow` entry point |
| One-file oversized persona prompt | **Lean host bootstrap + progressively loaded shared core Skills** |
| 140+ cross-industry roles | **Seven canonical workers selected by automatic repository discovery** |
| Conversion to multiple IDEs | **Official Claude, Codex and Antigravity plugin packages** |

**Do not copy:** the full marketing/sales role set, heavy vibe personas, or default hard write locks.

**Do adopt:** tagged `division`/`tags`, Deliverables, Workflow steps, Success Metrics, and narrow specialization.

All three hosts must preserve the same memory, verification, and closeout order. Implementation tasks
are dynamically scheduled through the task dependency graph. The [Business confirmation policy](WORKFLOW.md#business-confirmation-policy) defines when each decision applies.
需求范围复用当前授权。方案按事项和内容绑定，所选原型另按页面依赖指纹确认。
`baseline_ready`, `ia_ready`, `prototype_verified`, `visual_review_ready`, `contract_ready`,
`plan_ready`, `BUILD_VERIFIED`, QA, document projection, PM commit assessment, and closeout are automatic states or evidence.
Selected worktree delivery separately follows its configured final confirm/auto local-merge policy.
The design Agent self-checks prototype requirements coverage, standards conformance, and delivery consistency using existing prototype_verify static_checks, blocking_findings, and result; do not add a prototype QA role, report, approval, or browser/screenshot requirement. The user finally confirms concrete pages, and unified functional QA for subsequent production implementation remains.
For prototypes, `prototype_verified` means deterministic structure, local-dependency, contract, and
fingerprint validation; it does not claim Computer Use, browser automation, rendered visual review,
or user approval. Before `visual_review_ready`, the PM separately compares the concrete page behavior, developer notes and linked requirements
with the frozen approved requirements and acceptance criteria without invoking a browser.
For design-change UI, `requirements_approved` is not complete until the prototype choice is also
resolved; this choice is part of the existing confirmation rather than an additional gate.
直接开发、非 UI 和按既定原型修正均单独判断方案事项；跳过页面视觉确认只修改原型分支。
影响需求范围的变化回到原需求；影响某一方案的变化只更新该决定及其依赖任务。
Platform security prompts remain mandatory for destructive, production, paid, external-mutation, or
privileged operations and are outside this default business-confirmation policy.

An exceptional task pack uses this complete record and omits it otherwise:

```yaml
additional_business_confirmation:
  name: <stable gate name>
  reason: <explicit user request or why the applicable confirmations are insufficient>
  decision_scope: <what the user is deciding>
  options: []
  evidence: []
  resume_condition: <exact answer that resumes dependent work>
```

The exception requires an explicit user request or a distinct decision outside the applicable confirmations. It blocks only
dependent DAG tasks and must not become a permanent default stage.

正式 JSON 任务将上述六个字段放在单个 `task.additional_business_confirmation` 对象中。`name` 使用稳定 ID 或完整的 `exceptional:<id>`，与本任务声明的门逐字匹配。`options` 和 `evidence` 必须各含至少一项具体内容。PM 可在 `init` 中记录已明确取得的门，待决时保留完整问题。本任务包携带原记录，QA 包按实际受审 Writer 在 `reviewed_business_confirmations` 中携带问题、依据与对应门。已有受保护上游修改可继续沿用经校验且覆盖确切补丁面的 `standards_exceptions`，只满足它声明的技术例外门。

### UI routing and approval fields

See `product/WORKFLOW.md` for the authoritative UI lifecycle, page-contract behavior, and approval
semantics. `UI-Conformance` uses the `ui_change` record above and has no `visual_approval` record.
`UI-Patch`, `UI-Page`, and `UI-Flow` use the standard design paths only with
`prototype_policy: required`; `waived_by_user` has no `visual_approval` record:

```text
docs/standards/prototype/index.html
docs/standards/prototype/prototype.css
docs/standards/prototype/<stable-page>.html
```

PM 在用户确认具体页面后，用下述正式操作将来源、需求和页面依赖指纹一同保存到 `task.visual_approval`。其中 `status: approved` 描述 `pages` 中已记录的页面。任务需用的其余页面分别等待对应门。新记录的每页包含 `request_id`、`task_id`、`requirements_fingerprint`、`authority_id`、`path`、`dependency_fingerprint`、`approval_ref`、`changed_scope` 和 `interactions`。既有仅保存精确页面门值的图也使用当前原型交付状态及实物页面依赖指纹。无论是否已有新格式回执，后续交接、就绪及新交付登记均须核实原型页和依赖字节。多请求或不同路径复用同一门值时，须能匹配相应请求和页面的批准来源。 [视觉批准的 CAS 操作](../platforms/shared/skills/xy-workflow/references/ui-design.md#登记具体页的视觉批准)

`gates` contains strings. A dependent required-prototype UI task uses
`"visual_approved:<page-id>@<dependency-fingerprint>"`; it never uses a YAML mapping.

```text
classification/clarification with on-demand auxiliary retrieval -> task graph READY queue
-> applicable scoped solution decisions / affected prototype and implementation tasks
-> dependent visual_approved gate / implementers as each task becomes ready
-> build verification -> independent QA
-> QA PASS -> controlled-document projection -> PM commit assessment -> memory closeout -> final report
```

- The main-session PM exclusively owns classification, clarification, user approvals, task packs,
  dispatch, rework, commit assessment, and the final report.
- Implementation roles write only task-owned paths, return real build/test evidence, and perform no
  nested delegation.
- `UI-Conformance` does not dispatch an `xy-uiux` Writer; its implementation and QA bind to the frozen
  `design_authority_refs`. `xy-uiux` writes prototypes only for required-prototype work, or exact
  normative leaves in `standards_only` mode. A valid `waived_by_user` task has no prototype-design
  dependency or visual Gate; implementation and QA
  bind to the frozen requirement and exact decision surfaces.
  Real-project baseline analysis, IA, and prototype verification produce automatic evidence; only
  the user may grant `visual_approved` for the exact concrete changed pages and their verified
  dependency fingerprints.
- `xy-qa` independently audits after all relevant writers in the `qa_scope: request` current-request
  dependency closure reach `BUILD_VERIFIED`; unrelated writers may continue. QA neither dispatches
  implementers nor modifies production business code.
- Codex enforces `max_depth: 1` and a read-only QA sandbox. Claude Code disables the `Agent` tool for
  non-dispatch roles. Antigravity static roles receive no nested-dispatch tool, and QA receives no
  write tool.

## 5. Current Standard Role Catalog

| ID | division | tag summary | Typical sandbox |
|:---|:---------|:------------|:----------------|
| xy-web | engineering | repository-driven independent browser UI, accessibility, localization | Automatically discovered Web module roots |
| xy-desktop | engineering | Electron, Tauri, renderer, privileged core, IPC/capabilities, native integration, packaging/release | Automatically discovered desktop application roots |
| xy-backend | engineering | repository-driven backend, systems, API, service, worker, CLI, data, native | Automatically discovered backend and systems roots |
| xy-apple | engineering | repository-driven native Apple application targets | Automatically discovered Apple application roots |
| xy-android | engineering | repository-driven native Android application modules | Automatically discovered Android application roots |
| xy-uiux | design | ui, ux, wireframe, prototype, design-system | `project.yaml` -> `docs.standards_root/DESIGN_*.md` |
| xy-qa | quality | read-only review, security, desktop boundary, release evidence | Current request closure / read-only review |

## 6. Checklist for Adding a Role

1. Add metadata to `ROLES.yaml`, including `division`, `tags`, and `deliverables`.
2. Add `roles/xy-*.md` using the Section 3 structure.
3. Extend automatic discovery and routing evidence for the new delivery surface.
4. Build the three host packages and run the plugin delivery and role contract tests.
5. Update `/xy-workflow` routing and the role's hard Skill contract if PM auto-routing requires it.
