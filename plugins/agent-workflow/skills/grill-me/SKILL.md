---
name: grill-me
description: Check Full-request requirements for material gaps before planning; interview only when coverage is incomplete.
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
default or already configured model and reasoning settings. This workflow core
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

# Grill Me

Run after the PM has classified the request as Full and retrieved only any auxiliary project facts
materially needed for requirement coverage. Do not require document or agentmemory retrieval when
available information is already sufficient. Pressure-test the requirement brief without taking
ownership of planning or execution.

## Boundaries

- Use only facts and questions within the current request.
- Reuse facts already established by the user or repository; never ask the user to repeat them.
- Challenge material gaps, conflicts, irreversible decisions, and unverifiable acceptance claims.
- Stop as soon as the requirement brief is sufficient for planning.
- This Skill must not plan, edit PROJECT/feature truth, dispatch Agents, or approve requirements.
- Do not edit files, call another workflow, or create a second business-confirmation gate.

## Adaptive modes

Choose exactly one mode:

- `coverage_check`: use when goal, scope, non-goals, constraints, and acceptance evidence already
  appear complete. Confirm coverage and return immediately when no material gap remains.
- `full_interview`: use when any material fact is missing, ambiguous, or contradictory. Ask one
  compact batch at a time and follow up only on answers that leave a material decision unresolved.

## Procedure

1. Check the observable goal and affected users or surfaces.
2. Check in-scope work and explicit non-goals.
3. Check precedence among conflicting constraints and existing project contracts.
4. Check acceptance evidence, failure behavior, approval boundaries, rollback expectations, and
   irreversible or privileged actions.
5. Separate facts, user decisions, safe assumptions, and unresolved questions. Do not convert an
   unresolved material decision into an assumption.
6. Return `ready_for_planning` only when the PM can draft a plan without changing the intended
   product outcome or inventing authorization.

## Internal PM record

Build the following complete structure for planning coverage. It is PM working state, not a
user-facing response. The PM must not emit the raw `grill_result` YAML, its mode/readiness fields,
or empty internal lists to the user. When clarification is required, ask only the smallest natural-
language question that resolves the material gap. When coverage is complete, let the PM summarize
the goal, scope, non-goals, constraints, and acceptance evidence in the later approval brief.

```yaml
grill_result:
  mode: coverage_check | full_interview
  observable_goal: ""
  affected_users_or_surfaces: []
  in_scope: []
  non_goals: []
  constraints: []
  conflicting_constraints: []
  acceptance_evidence: []
  approval_boundaries: []
  rollback_expectations: []
  answered_questions: []
  assumptions: []
  unresolved_questions: []
  readiness: ready_for_planning | blocked
```

When blocked, state the smallest unanswered decision that prevents safe planning. When ready, return
control to the PM; do not continue into planning or implementation. Preserve the complete internal
record for `xy-plan`, but do not announce the schema or a `ready_for_planning` status token to the
user unless the user explicitly asks to inspect the internal record.
