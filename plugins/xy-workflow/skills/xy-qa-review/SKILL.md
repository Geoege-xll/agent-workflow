---
name: xy-qa-review
description: Accept build-verified request-scoped implementation using native code review first and project-specific QA checks, or deliver an explicitly requested standalone read-only audit.
---

从本 Skill 的物理目录向上两级确定插件根。使用同包的[宿主资源说明](../../plugins/plugin-context.md)。当前实例已具备同一物理来源、同一版本的完整说明时直接复用；独立启动或内容缺失时补读，来源或版本变化时重新读取。


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

先读当前宿主 `platforms/<host>/references/pm-integration.md` 的「Native review method」。如果交互入口会再派 Agent，继续核对同一 Reviewer 能否使用已有权限的前台入口。能前台运行后，仍须按[核对原生审查目标](references/inputs.md#核对原生审查目标)确认它实际会读到的差异与 PM 冻结的本次差异一致，并保留现行模型、推理力度和只读权限。

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

原生审查成功返回且范围核对通过后，同一 Reviewer 核实发现的源码和证据，只补尚未覆盖的需求、规范、集成或专项验收。原生结果为零条发现时也要核对这些验收项。保留原生结果引用，避免并行或事后重做整轮通用审查。

`review-swarm` is an explicit high-risk escalation, never automatic fallback.
`review-and-simplify-changes` is allowed only in `review-only` mode for an explicitly requested
maintainability audit. Both must not enter the ordinary fallback chain. Grill Me, feedback handling and bug
investigation are not code-review methods.

### 按验收项取证

完整读取当前任务包。先用验收项、每个固定变更路径及其受影响调用方、声明的审计面，独立确定要核对的规则和证据。以包内 `rule_ids`、`sections_or_queries` 和既有索引为起点，同时检查实际变更可能触发的漏派规则。按[输入约定](references/inputs.md)中的「Inputs」「当前包与范围」绑定身份与依据，依[实现验收](references/implementation-acceptance.md)中的「Scope, source and verification」「Independent standards coverage」核对固定范围、验证及规则；其余按适用条件展开。

| 当前要判断什么 | 从哪里取证 |
| --- | --- |
| 行为、错误处理、构建或回归 | 实际差异、调用方、原 Writer 的命令及完整日志引用；按[工程规范入口](../xy-code-standards/SKILL.md#read-only-review-and-evidence) 定位原规则 |
| 生产 UI 或设计规范变更 | [UI 验收](references/ui-review.md)中各 Writer 实际路线、运行端与无障碍证据；从[设计规范入口](../xy-ui-design/SKILL.md#生产实现与-qa-只读入口)直接定位适用条款 |
| 计划本身或计划编写规则属于验收对象 | [读者检查](../xy-plan/references/document-quality.md#在现有自查与唯一-qa-中检查读者理解)与被审修订。仅作功能依据的长期计划按当前批准项、锚点和指纹取证 |
| 宿主调用或回执存在缺口 | 只定位当前宿主 `pm-integration.md` 中所选方法的调用段，或输入约定中的当前宿主回执段 |

长文件或相近实现依[源码取证示例](references/implementation-acceptance.md#按符号和行段核对源码)先定位符号，再逐个读取命中处、受影响调用方和必要行段。规则按同版原文展开条件、例外及依赖，未命中时核对相邻章节和实际入口。全文合同仍须连续读完。每批结论依[分批取证](references/inputs.md#分批取证)保留证据与待查项。

本轮计划确属审查对象时，复用[计划生命周期](../xy-workflow/references/plan-lifecycle.md)中适用的已有校验，向 PM 交回范围歧义、状态冲突或缺失依据。若声称已验收，核对原始批准、实际行为和验收证据。目录收录或格式校验均不能产生批准或 PASS，沿用同一 Reviewer 和既有业务确认。

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

同一次授权调用支持结构化输出时，按[原生提取](references/inputs.md#原生结构化交接)取得最终回执。
普通后台 Reviewer 无此输出时，只通过原交接提交自己已完成的判定和证据，由 PM 按[固定回执构造](references/inputs.md#固定回执构造)组装。已有完整 schema 2 回执可直接校验。未完成的批次继续待验。
