---
name: xy-plan
description: Draft a Full request implementation plan after Grill Me coverage and before requirements approval.
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
Codex's discovered plugin skill names are `agent-workflow:<skill-name>`; use the
actual discovered name or the packaged physical path when invoking one.
Claude's explicit plugin skill commands use `/agent-workflow:<skill-name>` and
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

# xy-plan

Adapt the mature exactness and self-review ideas of Superpowers writing-plans to this pack's PM-owned
Task Pack and READY-DAG model.

```yaml
methodology_reference: superpowers-writing-plans
plan_owner: pm
plan_state: draft
```

## Boundaries

- Work only after `grill_result.readiness: ready_for_planning` for a Full request.
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
   conflicts, verification completeness, and missing failure cases. Fix gaps inline.

## Output projections

Before returning the Full draft, read [internal plan and task-graph contract](references/task-graph.md).
Return the complete internal record and a concise approval brief, keeping raw JSON/YAML hidden
unless requested. The PM, not this Skill, decides projection, resolves user choices, saves the
approved plan and dispatches.

<!-- workflow-contract: references/task-graph.md -->
<!-- workflow-contract: references/requirements-markdown.md -->
