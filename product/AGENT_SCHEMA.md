# Standardized Subagent Role Schema 2.0 (xy Team)

This schema adapts the [agency-agents](https://github.com/msitarzewski/agency-agents) model of
"narrow specialization + deliverables + workflow + success criteria" to this pack's
**`project.yaml` sandbox model + setup-generated multi-platform agents**.

## 1. Role ID Conventions

| Rule | Description |
|:-----|:------------|
| Prefix | Always `xy-` |
| Naming | Lowercase kebab-case: `xy-web`, `xy-desktop`, `xy-backend`, `xy-apple`, `xy-android`, `xy-uiux`, `xy-qa` |
| Single responsibility | One role equals one delivery surface. `xy-desktop` owns complete Electron/Tauri applications, `xy-backend` covers backend and systems work across languages, and native platform roles remain separate |
| Enablement | Setup generates the canonical roles automatically discovered from repository modules, always including `xy-qa` and adding `xy-uiux` for UI-bearing modules |

## 2. `ROLES.yaml` Metadata (Machine-Readable and Required)

说明正文、交流和新增代码注释遵守用户及项目语言，本包当前使用中文。
机器解析的稳定字段、角色／Skill ID、枚举和既有固定标题保留原格式；语言偏好不授权
翻译这些接口，也不改变三宿主的生成或解析合同。

```yaml
xy-example:
  description: One-sentence specialization used in the Claude agent description
  division: engineering | design | quality | architecture | product
  sandbox_key: xy-example          # Role key used to bind automatically discovered module scopes
  toolsets: write | write+delegation | write-tests | read
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
| `toolsets` | Setup mapping for tools and `disallowedTools` |
| `sandbox_key` | Role key used to bind automatically discovered module scopes as a soft preference |
| `claude_skills` | List only hard gates whose absence makes it unsafe for the role to start; optional specialist Skills are matched on demand by the Skill tool |

Each role may receive one or more normalized module roots from strict repository discovery. These
scopes support routing and context selection only; they never broaden exact task-pack `owned_paths`
or replace an explicit exceptional workspace override.

PM metadata is outside the ordinary role schema. The top-level `pm.toolsets: none` value describes
the main-session orchestrator and does not extend the role `toolsets` enum above.

Claude generation rules:

- Every role receives the `Skill tool`; non-delegation roles also receive `disallowedTools: Agent`.
- Codex, Claude Code, and shared configuration use the same hyphenated role ID, such as `xy-web`,
  and generate `.codex/agents/xy-*.toml` and `.claude/agents/xy-*.md`, respectively.
- Implementation roles preload `xy-code-standards` and `xy-build-verify`; production UI reads
  the applicable `xy-ui-design` branch only when `surface_kind: production_ui`.
- `xy-uiux` preloads `xy-ui-design`, `ui-ux-pro-max` and `xy-prototype-verify`; a missing hard gate blocks UI design.
  Preloading does not execute an inapplicable branch: `standards_only` never runs prototype verification.
- `xy-qa` preloads `xy-qa-review`; other local specialist Skills are matched on demand from
  `audit_surfaces` and are not written into the role manifest.
- QA 按实际代码或 UI 审查面只读消费同一专业方法，纯文档／后端任务不预载 UI 全文。
  静态绑定来自 `lib/role_skills.py`；metadata 和三宿主当前产物必须匹配，读取不产生新权限或阶段。
- Generated Claude Agents always use `permissionMode: default`, preserving the parent session's
  normal permission prompts. The sandbox remains a soft role scope.

Generation destinations for the three hosts:

| Host | PM entry point | Role artifacts | Core Skill artifacts |
|:-----|:---------------|:---------------|:---------------------|
| Codex | Root `AGENTS.md` + `$xy-workflow` | `.codex/agents/xy-*.toml` | `.agents/skills/xy-*` |
| Claude Code | `AGENTS.md` + `/xy-workflow` | `.claude/agents/xy-*.md` | `.claude/skills/xy-*` |
| Antigravity | Root `AGENTS.md` + `/xy-workflow` | `.agents/agents/xy-*.md` | `.agents/skills/xy-*` |

The nine core Skills have one authoritative source: `platforms/shared/skills/`. Host adapter layers
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

2.0只接受Light／Full和schema_version:2。两等级默认原生实施者；PM例外必须覆盖用户
明确指定的当前范围。Light交接当前自包含单包与最小验证，不强制DAG、Full规划或QA，
按实际风险评估独立审计及文档。Full保留已批准规划、请求调度和唯一独立QA。
任何当前包都不携带完整PM或兄弟会话历史。

### Scheduling Fields (Machine-Readable Task-Pack Contract)

每个2.0任务携带下列身份／上下文字段。依赖与图调度字段用于Full；Light保留当前task.state，
无需为派发创建DAG：

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
design_mode: prototype | standards_only  # Only xy-uiux + design_ui; omit for other roles
depends_on: []       # Semantic prerequisite task IDs, never capacity waits
blocks: []           # Exact reverse edges for depends_on; the validator requires consistency
gates: []            # Supported business/safety gates only
owned_paths: []      # Normalized project-relative ownership; ordered handoff may reuse a path
semantic_locks: []   # Shared contracts that cannot be changed concurrently
state: DECLARED      # Runtime dispatch state; saved plan keeps concise recoverable progress, not a second scheduler
qa_scope: request    # Current request dependency closure, not the entire project
# 派发后仅PM核对真实原生结果补记，首次绑定后不可改／清空。
# agent_ref: {host: codex, agent_id: <actual-native-id>}
```

`agent_ref`只接受host（codex／claude／antigravity）与agent_id（1..256字符，无空白／
控制字符）。PM先确认任务真实进入RUNNING或显式QA，再通过update补记实际ID；同值幂等，
不可替换／清空。同图不同任务包括历史完成任务不能共享ID。agent_retired可选bool、缺省
false，只能变true，禁止复用但不释放仍活动锁，也不证明原生进程已结束。

agent_alias绑定规范化module与规范role；独立任务可重用职责别名，但实例／ID必须新建。
同任务短返工、同轮原Reviewer差量复查可续用可用原实例。完整生命周期统一见WORKFLOW
的agent-instance-lifecycle：禁止父／兄弟完整历史、不fork继承、不预热、不建池，并在
实际原生结束或退役前保护成果、日志与worktree。
`continuation --input PACK_OR_GRAPH --task-id ID --host HOST --observed-state running|idle|cancelled|missing|unknown`
只返回建议，不探测、派发、恢复取消、清空历史或创建批准。

派发shell为schema_version:2、task、适用standards_contract和必要批准／UI依据。Full使用
`task --input GRAPH --task-id ID`只导出本任务；Light用`task --input PACK`校验／返回同形
shell，不要求Full图。update／continuation沿用唯一当前记录，不创建第二Agent账本。
接收者仍核对当前文件并完整读取必需规范。具体CLI参数见xy-workflow/references/runtime-records.md。

Full计划任务同时要求role、surface_kind与qa_scope；Light保留规范role及实际surface_kind，
不为派发强加Full闭包字段。Light UI仅允许普通低风险文案的UI-Conformance与当前真实
已解析权威，生产UI仍有工程／设计覆盖；设计／交互变化使用Full。 The runtime
snapshot also carries typed `ui_contract.prototype_paths` and derives the design-standard boundary
from `standards_contract.root/DESIGN_*.md` whenever any task is `production_ui` or `design_ui`; this makes both
the forbidden production boundary and allowed design-writer boundary deterministic CLI checks.
Every Writer in that graph which overlaps either boundary must be `xy-uiux + design_ui`, including
roleless, broadly scoped, direct-dependency, and transitive-dependency tasks.

For `xy-uiux + design_ui`, omitted `design_mode` means `prototype`. `standards_only` restricts writes
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

For Full work, the task graph comes from `xy-plan` with `plan_state: draft`. Before asking for
`requirements_approved`, the PM reviews that draft and records the post-QA controlled-document
projection. After approval the PM freezes the requirements fingerprint, graph, and proposed
projection; canonical PROJECT/plans accepted-baseline truth is not changed until integrated QA PASS. The PM then
invokes:

```text
bash .agent-workflow/lib/python_runtime.sh .agent-workflow/lib/task_graph_cli.py validate --input <runtime-task-graph.json>
bash .agent-workflow/lib/python_runtime.sh .agent-workflow/lib/task_graph_cli.py ready --input <runtime-task-graph.json>
bash .agent-workflow/lib/python_runtime.sh .agent-workflow/lib/task_graph_cli.py qa-ready --input <runtime-task-graph.json>
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
每位Writer独立读取适用内置工程/UI来源与项目特有规范，存在项目索引才沿链接读取。
non_ui用工程，production_ui用两领域，xy-uiux + design_ui用设计。每个选定来源绑定当前SHA、
适用ID和拥有路径；缺失/过期/覆盖不足仍回PM。index_path/root保持配置值；无项目规则叶且
索引物理缺失时index_fingerprint为null，已有索引绑定真实SHA；无需新建空索引或GENERAL。
只有三个精确内置路径及其.agent-workflow/前缀可作为内置来源，项目写权限边界不扩大。
init/文档校验检查实际存在性，纯JSON图校验只检查结构。

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
`design_authority_refs`, no unresolved design choice, no `xy-uiux` dependency, no visual gate, and
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
retains `requirements_approved`, standards authority, build verification, and full ui and
accessibility QA. Existing prototype bytes remain untouched and are not current authority for the
waived scope.

Full任务包在规划阶段声明投影决定；Light在交接时按实际需要评估，不强制预填Full投影记录：

```yaml
controlled_document_projection:
  project_docs_update: required | not_required
  change_type: added | updated | replaced | reimplemented | removed | restored | split | merged | renamed | cancelled | none
  affected_features: []
  project_index_update: required | not_required
  reason: <why current verified project or feature truth changes or remains unchanged>
```

已验证的当前功能事实或PROJECT索引需要变化时才用required；Full必须QA PASS，Light完成其实际必需的验证／审计接收。 A
major behavior-preserving rewrite may use `reimplemented`; routine refactors, dependency upgrades,
internal performance work, and pure visual styling use `not_required` with `change_type: none`
only when recorded current facts remain unchanged. A changed documented runtime/dependency baseline,
architecture rationale or scope requires the smallest in-place fact update, not a new document or log.
Every task pack still carries the approved goal, non-goals, constraints, acceptance evidence, and
applicable UI authority regardless of document projection. Required-prototype tasks carry concrete
pages; `UI-Conformance` tasks carry frozen `design_authority_refs`; `waived_by_user` tasks carry the
scope-bound `prototype_decision` and no prototype authority. Required-prototype tasks carry the same
decision record plus concrete page authority.

Full 集成 QA PASS 后，或 Light 完成实际必需验证／审计接收并评估需要后，PM 才投影当前基线。
同一稳定主题在 `docs.plans` 只有一份 Markdown 及同名派生 HTML，分开记录本次目标／执行阶段和
上次真实已验收版本／行为／批准与验收证据。`PROJECT.md` 是当前目录，只链接明确已验收基线，不设大小上限或任务日志。
再次迭代、暂停或取消本次目标不能抹掉旧基线；completed 不产生批准或交付。已验收删除在同稿
标记 `removed`、保留原因／日期／替代与必要历史，移除当前索引；不另建 feature／ADR 或改名副本。
未索引旧执行稿保持历史边界，不能按完成标签认定当前事实。

Light 仅为实际暂停／恢复／交接或明确请求保存；Full 由 PM 在需求批准后、首次设计／实施派发前
保存到 `docs.plans`。同主题复用原稿，模板普通中文元信息及六节合同见 plan-lifecycle；
Light 按必要性简化，不添加确认字段或必建文档。旧 docs.features 仅能通过显式单次迁移删除，运行时无别名。
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

PM只提交本请求拥有、按当前等级验证／验收的路径，加已验证的controlled-document
projection, using exact pathspecs and complete staged-diff inspection. It must not stage unrelated or unverified changes,
must not use `git add -A` or `git add .`, and must preserve pre-existing user work. Unsafe overlap
yields `action: blocked`, not whole-file staging. Nested repositories are assessed independently
and deepest first. This automatic action does not create a third business-confirmation stage or
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

同一次已授权的原生 QA 调用支持结构化输出时，可用 `qa_handoff_cli.py schema` 获取
当前 JSON Schema，再以 `extract --host H --input native-result.json` 解包终端成功
输出并执行原 handoff 语义校验；原 `validate` 合同保持可用。传输结构成功不代表 QA
PASS，不取代真实执行、固定 scope 和规范证据。Codex exec 使用 `--output-schema`
（review 无此旗标），Claude `-p --json-schema`，AGY `--json-schema`；当前版本与
权限仍须核对。详细终端形状与调用路径只在 `xy-qa-review/references/inputs.md` 维护。
Task Pack 仍用任务图 `task` 机械导出，不为转换 JSON 额外调用模型或增加 Reviewer。

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

QA result 使用 `schema_version: 2`，并以 `handoff_ref: {request_id, task_id, agent_alias,
agent_ref: {host, agent_id}, task_pack_sha256}` 绑定当前完整 QA 包。validate／extract 必须
传 `--task-pack`，身份、请求、别名或包 SHA 不符即拒绝，旧 PASS 不能绑定新任务。
QA PASS另携带内部standards_policy_coverage，绑定受管内置来源、实际项目叶及存在时的索引指纹（无叶且缺索引为null），
Task Pack rule IDs, independently resolved engineering/design rule IDs, one classification for every
fixed changed path, and rule checks containing source paths/anchors, `hard | advisory` severity,
`pass | fail | not_applicable`, affected paths, and evidence references. If QA discovers an
applicable rule omitted from the Task Pack, it returns FAIL instead of silently repairing the
contract. The PM runs `qa_handoff_cli.py validate --input RESULT --task-pack CURRENT_QA_PACK`; incomplete coverage,
evidence-free applicable rules, scope mismatch, or any hard-rule failure makes PASS invalid. This
machine projection is never shown to the user as raw JSON or YAML.

`READY`, `RUNNING`, `BUILD_VERIFIED`, and `QA` are scheduler runtime facts in the runtime graph
snapshot, not independently maintained task-pack claims or PM completion lists.

- `READY`: a derived queue membership: semantic dependencies and applicable gates are satisfied, so
  the task may be dispatched when capacity is available. Unmet, failed, or pending prerequisites
  keep the task out of READY instead of creating another task-state enum value. If no slot is
  available, record `capacity_delay`; never disguise it as a new semantic dependency.
- `RUNNING`: a writer is assigned and executing.
- `BUILD_VERIFIED`: the writer has completed and returned real build/test evidence.
- `QA`: unified QA is running on the current request dependency closure. The QA barrier includes
  only `task_type: writer`; read-only, evidence, and QA tasks cannot make it wait on itself.
- `QA_PASSED`: only an explicit `task_type: qa` node may use it, after its current PASS handoff validates.
  Re-review/failure resets its state; stale PASS cannot override a running or failed review at delivery.

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
| Conversion to multiple IDEs | **setup_claude / codex / antigravity** |

**Do not copy:** the full marketing/sales role set, heavy vibe personas, or default hard write locks.

**Do adopt:** tagged `division`/`tags`, Deliverables, Workflow steps, Success Metrics, and narrow specialization.

All three hosts must preserve the same memory, verification, and closeout order. Implementation tasks
are dynamically scheduled through the task dependency graph. The default business-confirmation
policy is:

```yaml
business_confirmation_policy:
  default_gates:
    - requirements_approved
  ui_only_gates:
    - visual_approved
  additional_gates: exceptional
```

`baseline_ready`, `ia_ready`, `prototype_verified`, `visual_review_ready`, `contract_ready`,
`plan_ready`, `BUILD_VERIFIED`, QA, document projection, PM commit assessment, and closeout are automatic states or evidence,
and do not themselves require user confirmation. `UI-Conformance`, non-UI, and a valid
`waived_by_user` request have no business confirmation after `requirements_approved` by default.
This describes development gates; selected worktree delivery separately follows its configured final
confirm/auto local-merge policy without creating another prerequisite for implementation.
原型由设计 Agent 自检需求覆盖、规范符合性和交付一致性，复用现有 prototype_verify 的
static_checks、blocking_findings 与 result；不新增原型 QA 角色、报告、审批或浏览器/截图要求。
用户最终确认具体页面，后续生产实现的统一功能 QA 保留。
For prototypes, `prototype_verified` means deterministic structure, local-dependency, contract, and
fingerprint validation; it does not claim Computer Use, browser automation, rendered visual review,
or user approval. Before `visual_review_ready`, the PM separately compares all five contract sections
with the frozen approved requirements and acceptance criteria without invoking a browser.
For design-change UI, `requirements_approved` is not complete until the prototype choice is also
resolved; this choice is part of the existing confirmation rather than an additional gate.
Reversible architecture details are automatic and may be retained in current feature rationale
after verification. A material architecture change that changes approved requirements, scope, key constraints, or
acceptance evidence normally reopens `requirements_approved`.
The PM may ask architecture questions and request a user choice as clarification, but that question
or choice does not automatically create a third business-confirmation stage. If the answer materially changes approved
requirements, scope, key constraints, or acceptance evidence, reopen `requirements_approved`;
use an exceptional task-scoped confirmation only when it cannot safely be folded into an existing stage.
Platform security prompts remain mandatory for destructive, production, paid, external-mutation, or
privileged operations and are outside this default business-confirmation policy.

An exceptional task pack uses this complete record and omits it otherwise:

```yaml
additional_business_confirmation:
  name: <stable gate name>
  reason: <why the default two stages are insufficient>
  decision_scope: <what the user is deciding>
  options: []
  evidence: []
  resume_condition: <exact answer that resumes dependent work>
```

The exception requires an explicit user request or a material unresolved decision. It blocks only
dependent DAG tasks and must not become a permanent default stage.

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

Visual approval is authoritative only in the existing workflow task state:

```yaml
visual_approval:
  status: pending | approved
  pages:
    - path: docs/standards/prototype/<stable-page>.html
      dependency_fingerprint: <verified-dependency-fingerprint>
      changed_scope: []
      interactions: []
```

`gates` contains strings. A dependent required-prototype UI task uses
`"visual_approved:<page-id>@<dependency-fingerprint>"`; it never uses a YAML mapping.

```text
classification/clarification with on-demand auxiliary retrieval -> task graph READY queue
-> dependent visual_approved gate / implementers as each task becomes ready
-> build verification -> independent QA
-> QA PASS -> controlled-document projection -> PM commit assessment -> memory closeout -> final report
```

- The main-session PM exclusively owns classification, clarification, user approvals, task packs,
  dispatch, rework, commit assessment, and the final report.
- Implementation roles write only task-owned paths, return real build/test evidence, and perform no
  nested delegation.
- `UI-Conformance` does not dispatch `xy-uiux`; its implementation and QA bind to the frozen
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
4. Run `bash .agent-workflow/setup_all.sh`.
5. Update `/xy-workflow` routing and the role's hard Skill contract if PM auto-routing requires it.
