---
name: xy-qa-review
description: Accept build-verified request-scoped implementation using native code review first and project-specific QA checks, or deliver an explicitly requested standalone read-only audit.
---

## 官方 Antigravity 插件资源边界

本段仅适配资源与原生传输，不授予业务批准、角色所有权或 QA PASS。
从已加载组件的物理路径解析插件根目录：技能目录上两级，`agents/`、`rules/`
目录上一级；禁止用项目 cwd 或猜测缓存路径。先读根目录 `PLUGIN.md`。
唯一流程依据是其中的 `product/WORKFLOW.md`、`roles/`、
`platforms/shared/skills/`，以下共享正文保持原样。
宿主读取如被截断，按缺失行范围续读，或复用包内已有分页 helper；完整连续覆盖
当前任务所需权威范围后才执行。不重复读取已覆盖内容，不自行实现另一套分页器。

包内资源使用相对插件根的规范路径，通过 `plugins/source_pack.py resource` 解析。每次独立调用都使用：
`bash <plugin-root>/lib/python_runtime.sh -B -X utf8 <plugin-root>/plugins/source_pack.py`。
原有辅助命令使用 `helper --project <absolute-project> <original-helper> <arguments>`；
它只选已有 Python 3.11+，不安装软件、不改 PATH。项目文档、任务与业务代码仍属于
真实项目；包内示例不是当前项目配置。

通过同一 helper 调用 `plugins/project_context.py inspect`，复用已验证的
`project.yaml`，或显式 `apply` 新候选 `.awf/project.yaml`。`init --adapter <selected-path>` 必须传入同一配置。此入口不创建文档、不授予
批准。需要宿主集成时读取 `platforms/antigravity/references/pm-integration.md`。
插件由宿主原生发现、启用及更新。业务项目仅保留其自身配置。

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

当前插件沿用未绑定的源包合同，拒绝中央 `runtime_binding` 与中央项目标记，
不自动迁移。活动任务期间不得更新/替换插件；跨更新资源保留与实际模型/effort
执行仍需真实宿主证明。未获得对应证据时保留 `runtime_verified: false`。


<!-- agent-workflow-pack:managed-skill -->

# xy-qa-review

相对链接用于已发现的 Skill 内导航。通过插件的 `source_pack.py resource` 定位或以 `helper`
调用 `lib/documents/context_read.py` 分页时，从已验证的插件包读取，使用包内规范路径，例如
`platforms/shared/skills/xy-qa-review/references/inputs.md`。跨 Skill 引用使用目标 Skill
在 `platforms/shared/skills/` 下的规范路径。

Use the latest complete PM-issued scope and acceptance. A saved plan helps recover an actual gap;
it is not approval or completion evidence. Acknowledge scope replacements before returning a result,
reuse unaffected valid evidence, and never apply an old-scope PASS to a revised request.

QA is independent, read-only and request-scoped. It does not edit production code, direct implementers,
create a Markdown QA report, or declare the project complete to the user.
QA must not generate screenshots or dispatch another reviewer. Communicate only with the PM.

## Select the review branch

- PM assesses Light's independent-audit need at handoff by actual risk. Without a real need, do not dispatch
  QA or relabel local verification as PASS. Explicit review requests, mandatory project checks and actual
  risk may still require the single independent review; auditing Light does not force a Full plan or DAG.
- For an audit-only request, follow WORKFLOW's `Standalone read-only audit`: inspect requested
  source/contracts, standards and necessary evidence; return findings, conclusion and limitations,
  then stop. Honor explicit full/independent re-review and mandatory checks. Missing evidence is a
  limitation or blocker. Do not fabricate writers, BUILD_VERIFIED, Task Packs or implementation QA
  PASS, audit the report again, or activate projection/commit/memory closeout. Authorized fixes route
  through PM. For a code-review audit, prefer safe available native review without imposing
  implementation intake or records. Full and Light implementation acceptance that actually requires independent
  QA use the current-task-pack contract below.

Select applicable rules from managed built-in sources and actual project-specific leaves. Read/bind the
real SHA of a project index only when it exists. With no specific leaves and a missing index, use configured
paths/null fingerprints; create no GENERAL or empty index. At prototype stage, the design Agent performs
three self-checks and the user gives final confirmation. This Skill adds no independent prototype QA;
functional acceptance after production implementation still uses the single independent review below.

## Implementation acceptance

Final QA outcome: PASS | FAIL

After relevant Full Writers reach BUILD_VERIFIED, or Light completes required verification with independent
QA selected, PM dispatches only one `xy-qa`. A new Reviewer receives only the current self-contained schema 2
task pack, without copying full PM/sibling conversations or forking parent history.
That same reviewer uses one code-review method in this order:

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
```

Use the current host's native review when its exposed capability, fixed scope, effective read-only
permissions and non-recursive execution are established; read only that host's existing
`platforms/<host>/references/pm-integration.md` when invocation needs resolving. A documented feature
or installed binary alone does not prove this reviewer can invoke it safely.

Otherwise select at most one host-exposed installed Skill proven code-review capable, read-only,
request-scoped and non-recursive. Do not scan personal Skill directories. The installed
`requesting-code-review/code-reviewer.md` prompt is allowed for this same reviewer; it does not enable
a named Superpowers reviewer or other Superpowers workflows. Internal fallback uses this pack's
procedure without an external review Skill.

Move forward only for a missing method, read-only launch failure, timeout, malformed output/unpinned
scope, unsafe mutation or recursive-delegation attempt. Record actual capability and earlier-method
unavailability in `review_method`; findings, disagreement and FAIL require PM-owned bounded rework,
not another method or reviewer. Reject mutated/unbound output and return any workspace change to PM;
do not silently restore files or accept stale evidence before continuing.

Native review supplies the general code-review evidence. Independently verify its findings and the
source/evidence needed for project acceptance; supplement uncovered request, standards, integration
or specialist checks. Do not launch a second complete generic review merely because this Skill is
active. No findings is not implementation QA PASS. Model/effort and permissions retain their current
project/host authority; a review method grants no additional tools or actions.

`review-swarm` is an explicit high-risk escalation, never automatic fallback.
`review-and-simplify-changes` is allowed only in `review-only` mode for an explicitly requested
maintainability audit. Both must not enter the ordinary fallback chain. Grill Me, feedback handling and bug
investigation are not code-review methods.

Read [input contracts](references/inputs.md) and [implementation checks](references/implementation-acceptance.md)
for Full acceptance or Light acceptance requiring independent QA. They retain mandatory evidence, independent standards coverage, memory
authority, worktree integration and bounded rework. Missing mandatory evidence blocks PASS.

When the current scope includes a saved plan or plan-writing rules, read
[document quality](../xy-plan/references/document-quality.md) and apply its reader check within this same
review. Inspect only the selected current plan and necessary references; return ambiguous scope, conflicting
status/baselines or missing authority to PM. Reuse applicable selected-plan validation evidence from
[plan lifecycle](../xy-workflow/references/plan-lifecycle.md); a format pass is not approval or QA PASS.
Do not launch reader Agents, add a reader report/gate or require another business confirmation for wording fixes.

<!-- workflow-contract: references/inputs.md -->
<!-- workflow-contract: references/implementation-acceptance.md -->

审查生产 UI 或设计规范时，读取 [UI 审查分支](references/ui-review.md)。生产 UI 逐项使用 QA 包
中 `reviewed_ui_changes` 的生产 Writer 投影，并按实际运行端核对界面与无障碍证据。仅
`prototype_policy: required` 触发原型静态身份复核、设计交接及页内契约审查；其余生产分支
按本轮冻结依据核对生产行为，无须复读旧原型。

<!-- workflow-contract: references/ui-review.md -->

For actual production Web browser evidence gaps, read the shared
[Web browser verification policy](../xy-build-verify/references/web-browser-verification.md) through
implementation acceptance. Load `xy-playwright` only for the relevant Web audit surface; no universal
third-party preload, extra reviewer, prototype automation or permission expansion.

## Return to PM

Return one concise task handoff to PM:

```text
[Audit result] PASS | FAIL
[Scope] reviewed request closure and production modules/pages
[Contract checks] complete or specific failures
[Validation] exact commands, exit codes and complete-log references reviewed
[Skill evidence] skills_used / unavailable_required_skills / uncovered_audit_surfaces
[Blocking findings] none or actionable findings with severity, evidence and owner
[Recommended assignment] xy-* when rework is required
[Blocks completion] yes/no
```

```yaml
skill_evidence:
  skills_used: []
  unavailable_required_skills: []
  uncovered_audit_surfaces: []
```

List only Skills actually applied; unavailable required Skills block PASS. Suggestions/nits remain
findings within PASS or blockers within FAIL, never a third outcome. Return FAIL to PM for rework.
Before accepting PASS, PM validates the internal `review_method.scope_ref` and
`standards_policy_coverage` using
`bash "<plugin-root>/lib/python_runtime.sh" -B -X utf8 "<plugin-root>/plugins/source_pack.py" helper --project "<absolute-project>" lib/delivery/qa_handoff_cli.py validate --input <qa-handoff.json> --task-pack <current-qa-task-pack.json>`.
Only valid PASS lets Full enter `QA PASS -> controlled-document projection -> PM commit assessment -> memory closeout -> final report`. Light performs its actually selected audit and closeout assessment.
Keep raw records internal and stop after valid acceptance; ordinary closeout does not trigger another audit.

Results use schema_version:2 and handoff_ref to bind the current QA pack's request_id, task_id, agent_alias,
actual agent_ref and task_pack_sha256. Both validate/extract require current --task-pack; old formats,
identities or old-pack PASS are rejected. The same Reviewer checks rework deltas under the current complete
pack. Stop after valid PASS; close natively or retire after PM accepts evidence and the necessary feedback
window ends. Retirement does not prove physical erasure or lock release.

原生结构化交接在同一份回执的 `review_details` 提供 `findings` 和 `verification`，携带有证据的
发现、返工角色、验证命令、退出码与完整日志引用。字段合同见[输入约定](references/inputs.md)。
现有文本型交接继续适用。复用同一次回执校验，无须再发一次调用收集这些字段。
