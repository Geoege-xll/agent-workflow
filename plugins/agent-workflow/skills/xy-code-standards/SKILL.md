---
name: xy-code-standards
description: "When writing, refactoring or reviewing code read-only, combine built-in engineering rules, project-specific standards, actual callers and existing contracts to choose the smallest complete change or report evidence-backed findings; supports quality judgment without replacing project standards, task authorization or verification procedures."
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

# xy-code-standards

Use current user authorization, the existing Task Pack and applicable rules as the basis. The single source
of general engineering text is the [built-in engineering rules](references/rules.md); read applicable clauses
for the actual task. Projects add only approved specific standards, and read a project index only when it exists.
Fully bind current sources, rule IDs and fingerprints. This Skill adds no planning, dispatch, prototype,
approval, QA or record stage.

<!-- workflow-contract: references/rules.md -->

## Choose implementation from facts

- Follow actual call chains to establish the behavioral goal, entry points, data/state owners and consumers.
  Use nearby code, tests and executable configuration to distinguish facts, assumptions and gaps. Verify
  discoverable facts first; return unresolved tradeoffs affecting contracts, permissions or side effects to
  the original decision-maker. Do not automatically treat an observed old implementation as an upgrade target.
- Before reuse, check semantics, inputs/outputs, failure modes and dependency direction. Before extraction,
  identify the actual shared responsibility, variation point or isolation benefit. Similar syntax, fewer lines
  or anticipated future extension does not justify consolidation or added layers.
- Compare approaches by their changed behavior, preserved contracts and affected consumers; choose the smallest
  complete change that meets current requirements. Remove redundancy caused by this change and report other
  issues within the original task boundary. Explain non-obvious tradeoffs with comments required by applicable
  standards and update those comments with behavior.

## Read-only review and evidence

Read-only review does not write code. Findings include a concrete location, trigger, actual impact and supporting
evidence. Distinguish proven defects, evidence gaps and design preferences; naming, line counts or missing evidence
for a platform alone do not establish incorrect behavior. Implementation/review retain the existing verification
contract: reuse still-valid coverage and fill only real gaps. Do not expand static checks or test-double results
into claims about real consumers, other platforms or product quality. Implementation delivery still follows
the applicable `xy-build-verify` branch.

## Read by actual boundary

- When a change/review involves external input, mutable state, resource lifecycles or durable publication,
  read only relevant parts of [boundary reasoning](references/boundary-reasoning.md); do not load every
  specialist topic for an ordinary local change.
- Read [sources and adoption boundaries](references/sources.md) only when maintaining this Skill,
  checking attribution or tracing tradeoffs; do not preload it for ordinary implementation/review.
