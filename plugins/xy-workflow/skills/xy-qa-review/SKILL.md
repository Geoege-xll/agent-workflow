---
name: xy-qa-review
description: Accept build-verified request-scoped implementation using native code review first and project-specific QA checks, or deliver an explicitly requested standalone read-only audit.
---

## Official plugin resource boundary

This component is assembled from the unchanged shared authority. In this official
plugin, resolve the installation root from the loaded component's physical location:
`../..` from a skill's directory, or `..` from the `agents/` or `rules/` directory.
Do not use the current working directory or a guessed cache path.
Read `PLUGIN.md` there before using workflow helpers. Treat this paragraph as a
resource/transport adapter; it grants no business approval, role ownership or QA PASS.

读取必需长文时，核对宿主返回的起始范围、实际范围、总长度和截断标志。
若 `Read` 受 token／行数上限截断（如 `truncatedByTokenCap`，或末行小于
`totalLines`），只续读缺失范围，或经下述既有 helper 调用
`lib/documents/context_read.py`，遵守其 `offset`／`next_offset`／`sha256`
续页合同。确认同一版本所需范围连续、完整后，再执行依赖该内容的流程；
不能将部分输出当作完整已读，也不要从头重复全量 `Read` 来补缺。
这只是资源传输完整性要求，不新增业务门禁、阅读台账或上下文复制。

Use that root's `product/WORKFLOW.md`, `roles/`, and
`platforms/shared/skills/` as the unchanged workflow authority. The appended shared
text retains historical `.agent-workflow/` examples. In plugin mode, resolve managed
resource references under the plugin root using `plugins/source_pack.py resource`;
select the actual adapter with `plugins/project_context.py inspect` through the
same helper wrapper. Reuse a verified existing `project.yaml`, or explicitly apply
the new `.awf/project.yaml` candidate. Translate historical adapter examples to
that selected actual path. The context entry creates no documents or business
approvals; its `init --adapter <selected-path>` passes that exact adapter to the
original initializer. Resolve project documents, task records and production code
in the actual project. A packaged example is never the current project adapter.
Use the packaged interpreter selector for each independent invocation:
`bash <plugin-root>/lib/python_runtime.sh -B -X utf8 <plugin-root>/plugins/source_pack.py`.
Pass `helper --project <absolute-project>` and the original helper path/arguments
instead of the historical project bridge commands. The selector only locates an
existing Python 3.11+ and never installs software or changes the user's PATH.
Read the current host's packaged `platforms/<host>/references/pm-integration.md`
when host integration is required. Native plugin discovery replaces legacy setup,
role refresh and central activation checks. Do not run `runtime install`,
`runtime activate`, project registration, `setup_*.sh`, or create/edit project
`AGENTS.md`, `CLAUDE.md` or `.agent-workflow` to make this plugin work.
Codex's discovered plugin skill names are `xy-workflow:<skill-name>`; use the
actual discovered name or the packaged physical path when invoking one. Public aliases are
`xy-config`, `xy-grill-me`, `xy-grilling`, `xy-taste` and `xy-playwright`, governed by
`product/command_identity.json`; canonical upstream names remain vendor resources, not discovery entries.
Fully read each selected adapter and its canonical before use; never substitute unknown global names.
Claude's explicit plugin skill commands use `/xy-workflow:<skill-name>` and
its bundled agents use the host-discovered plugin-qualified agent name. Preserve
the original role identity in the task pack; do not infer successful native role
selection from that identity or a generic task label. Use the actual host tool's
documented arguments and report an unavailable native selector.

The main session remains PM. Workers receive only the complete current task pack
with `instance_policy: fresh` and `context_policy: handoff_only`; never fork PM or
sibling history. Only the official host dispatches agents. Use the official host's
default or already configured model and reasoning settings; PM applies the business-only
read-only dispatch preference contract in `xy-workflow/references/dispatch.md` when present. This workflow core
neither requires nor registers a separate model configuration service, web console,
or model MCP. Their absence does not block native dispatch. Requirements approval and applicable visual
approval remain exactly as defined in the authority; existing explicit scope
authorization still applies to Light. A required independent QA remains one
read-only reviewer. Preserve the original closeout order.

Claude Code and Antigravity expose packaged native agents. Codex's documented
portable manifest exposes skills and MCP, with no documented `agents` manifest key:
read the full packaged role and `platforms/codex/WORKER_CONSTRAINTS.md` into the current fresh task
handoff through the host's actual supported native dispatch interface. A role label
alone proves no native role/model selection. If the host cannot supply required
dispatch or independent context, report that limitation instead of claiming it ran.
Do not select an unknown same-named global `xy-*` role as evidence that this package
ran: it may contain an older workflow or central pin. Use a fresh native generic
entry with the complete current packaged role instructions and current task pack,
or a native selector whose definition has actually been verified against this
package. Never import an unknown global role's pin, history or instructions merely
because its name matches. If the host cannot provide this boundary, report the
dispatch limitation to the PM.

This alpha uses the existing unpinned source-pack task contract. It rejects central
`runtime_binding` records and central project markers rather than migrating them.
Do not update/replace the installed plugin during an active task. Retention of old
plugin resources across updates and actual native model/effort execution remain
unverified. `runtime_verified: false` stays visible until a real host session proves
the corresponding behavior.


<!-- agent-workflow-pack:managed-skill -->

# xy-qa-review

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
`.agent-workflow/platforms/<host>/references/pm-integration.md` when invocation needs resolving. A documented feature
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

<!-- workflow-contract: references/inputs.md -->
<!-- workflow-contract: references/implementation-acceptance.md -->

For production UI or design-standard work, also read [UI audit branches](references/ui-review.md),
selecting only the current scoped route. Keep production UI/accessibility audit and current design
authority. Required prototypes use frozen designer evidence, the exact in-page contract and
deterministic fingerprint validation; waived surfaces do not read old prototypes.

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
`bash .agent-workflow/lib/python_runtime.sh -X utf8 .agent-workflow/lib/delivery/qa_handoff_cli.py validate --input <qa-handoff.json> --task-pack <current-qa-task-pack.json>`.
Only valid PASS lets Full enter `QA PASS -> controlled-document projection -> PM commit assessment -> memory closeout -> final report`. Light performs its actually selected audit and closeout assessment.
Keep raw records internal and stop after valid acceptance; ordinary closeout does not trigger another audit.

Results use schema_version:2 and handoff_ref to bind the current QA pack's request_id, task_id, agent_alias,
actual agent_ref and task_pack_sha256. Both validate/extract require current --task-pack; old formats,
identities or old-pack PASS are rejected. The same Reviewer checks rework deltas under the current complete
pack. Stop after valid PASS; close natively or retire after PM accepts evidence and the necessary feedback
window ends. Retirement does not prove physical erasure or lock release.
