---
name: xy-ui-design
description: "For xy-uiux to design high-fidelity interactive HTML prototypes in prototype mode or maintain authorized design standards in standards_only mode; production implementation and QA consume applicable rules only under existing design authority, without creating prototypes or gaining write authority."
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
`platforms/shared/skills/` as the unchanged workflow authority. Resolve canonical package-relative paths using `plugins/source_pack.py resource`; select the actual project adapter with `plugins/project_context.py inspect` through the same helper wrapper. Reuse a verified existing `project.yaml`, or explicitly apply the new `.awf/project.yaml` candidate. The context entry creates no documents or business
approvals; its `init --adapter <selected-path>` passes that exact adapter to the
original initializer. Resolve project documents, task records and production code
in the actual project. A packaged example is never the current project adapter.
Use the packaged interpreter selector for each independent invocation:
`bash <plugin-root>/lib/python_runtime.sh -B -X utf8 <plugin-root>/plugins/source_pack.py`.
Pass `helper --project <absolute-project>` and the documented helper path/arguments. The selector only locates an
existing Python 3.11+ and never installs software or changes the user's PATH.
Read the current host's packaged `platforms/<host>/references/pm-integration.md`
when host integration is required. The host discovers and manages the installed plugin. Project instruction or configuration files do not activate it.
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
ran: its authority may come from another source. Use a fresh native generic
entry with the complete current packaged role instructions and current task pack,
or a native selector whose definition has actually been verified against this
package. Never import an unknown global role's history or instructions merely
because its name matches. If the host cannot provide this boundary, report the
dispatch limitation to the PM.

This plugin uses the existing unpinned source-pack task contract. It rejects central
`runtime_binding` records and central project markers rather than migrating them.
Do not update/replace the installed plugin during an active task. Retention of old
plugin resources across updates and actual native model/effort execution remain
unverified. `runtime_verified: false` stays visible until a real host session proves
the corresponding behavior.


<!-- agent-workflow-pack:managed-skill -->

# xy-ui-design

## Usage Boundaries

相对链接用于已发现的 Skill 内导航。通过插件的 `source_pack.py resource` 定位或以 `helper`
调用 `lib/documents/context_read.py` 分页时，从已验证的插件包读取，使用包内规范路径，例如
`platforms/shared/skills/xy-ui-design/references/design-quality.md`。跨 Skill 引用使用目标 Skill
在 `platforms/shared/skills/` 下的规范路径。

Follow the current Task Pack, applicable project standards, and the permanent responsibilities of
`xy-uiux`. Loading this Skill does not grant write authority or change the task level, implementer,
user's prototype choice, UI-Conformance, approvals, or the single independent QA route. The PM's
selected `design_mode` determines the applicable stage; preloading does not require every branch.

- `prototype`: Work only within the currently authorized required-prototype scope and deliver
  stable, build-free, directly openable, high-fidelity interactive HTML. Early wireframes serve only
  IA and option comparison; they cannot be the final prototype.
- `standards_only`: Maintain only the precisely authorized design-standard leaves under the existing
  `xy-workflow/references/design-standards.md`; do not write HTML/CSS, run prototype verification,
  or request visual approval.
- Production implementation and QA: Read and consume only the currently adopted design authority
  and applicable professional rules. Do not use this Skill to change design direction, expand
  owned_paths, or restore prototype gates for waived/UI-Conformance work.

## Baseline and Design Analysis

The following design operations apply to authorized `xy-uiux` tasks; production implementation and
QA consume applicable rules against existing authority without executing design stages or triggering
prototype verification. Read the applicable clauses in [design foundations](references/foundations-rules.md)
and [component interactions](references/components-rules.md) for general rules; the project retains only
its actually adopted tokens, styles, dimensions, platform mappings, and business differences. When a
project-specific standards index exists, follow its actual links, then check relevant product evidence
and current pages. Reuse context that has been read in full and remains unchanged; do not assume leaf
filenames or preload the entire project. Approved requirements and project rules take precedence.
Activate the bundled `xy-taste` **no-hooks adapter** for Taste design judgment and follow
its complete canonical reading contract below. Advice is subordinate to the current user requirements,
project standards, role permissions and frozen authority. Establish the actual page type and density
first: compact application consoles/configuration pages must not inherit marketing hero sections,
full-screen whitespace, oversized type or decorative imagery by default. Reuse the existing project
baseline; original upstream guidance does not establish suitability for every page.

## Taste Canonical Reading and Execution Boundary

The original is kept intact outside host discovery at
`third_party/selected-skills/taste/skills/taste-skill/SKILL.md`; provenance, fixed commit, complete
inventory and licenses are in `third_party/selected-skills.lock.json`. The discovered adapter is
project-authored and carries **no hooks**. Never copy/register the original Stop hook, run `--hook`,
or replace the original with a summary or a truncated discovery body.

For an installed plugin, resolve only its current physical plugin root, then run:

```text
bash <plugin-root>/lib/python_runtime.sh -B -X utf8 <plugin-root>/plugins/source_pack.py selected-skills check
bash <plugin-root>/lib/python_runtime.sh -B -X utf8 <plugin-root>/plugins/source_pack.py selected-skills read xy-taste --offset 0 --length 12000
```

Read every returned `content` completely. Continue with the returned `next_offset` (UTF-8 byte
position) and the same length until `eof: true`; verify continuous offsets, consistent `path`, `sha256`
and `total_bytes` across chunks, and coverage from zero through total_bytes. If output is truncated,
request a smaller chunk at the unconsumed offset; byte validation alone is not the Agent reading.
Source-pack development reads that same canonical completely, in bounded segments when needed.
After the full SKILL.md, use `source_pack.py resource` with the canonical skill prefix to locate and
fully read references actually needed by the current stage. Preserve assets/credit/license/trademark
metadata; top-level MIT is not a license claim for every asset. Missing/corrupt files, incomplete reads
or unavailable tools block the dependent design work and return to PM; never claim they were loaded.
No per-task reading report is required; retain actual read evidence in the ordinary handoff.

Reading Taste does not run its complete operational pipeline. In `prototype` and `standards_only`,
consume applicable design judgment only: do not automatically arm a gate, execute scripts, launch a
browser, capture screenshots, start a server, fetch fonts/assets, install tools, write production code,
or dispatch another workflow. Existing build-free/file:// prototypes, static verification and the
no-screenshot rule take precedence. A script may run only when the current Task Pack and host
permissions authorize that exact operation; never execute merely because an upstream step is mandatory.
`selected-skills diagnose` checks existing Node >=22/browser/optional ffmpeg separately from bundled
resource completeness without installing or running upstream scripts. A Taste gate is never workflow
QA PASS; if the pipeline/gate was not run, say so and do not claim upstream full-run completion.
This boundary adds no design/QA/approval file, gate, parallel reviewer or confirmation stage.

<!-- workflow-contract: references/foundations-rules.md -->
<!-- workflow-contract: references/components-rules.md -->

## Read by Stage

For design analysis, page refinement, or standards maintenance, read
[design quality and completion criteria](references/design-quality.md). Address content hierarchy,
components, states, platforms, and accessibility as applicable to the current task; do not expand
design scope to fill a checklist.

<!-- workflow-contract: references/design-quality.md -->

Only when organizing pages and presentation in `prototype` mode, read the
[HTML prototype canvas](references/prototype-canvas.md). It carries forward the role's existing canvas
contract without requiring unrelated page rework or adding prototypes to direct-development branches.

<!-- workflow-contract: references/prototype-canvas.md -->

## Verification and Handoff

For `prototype`, the design Agent self-checks requirement coverage, standards conformance, and
delivery consistency, reusing `xy-prototype-verify` static verification and the five-section in-page
contract. Hand off results through the existing `static_checks`, `blocking_findings`, and `result`;
do not create independent prototype QA, reports, or approvals. Final confirmation remains with the
user. Hand off only concrete pages, scope, operations, shared impact, real evidence, and unverified
items to the PM. Static success does not establish visual satisfaction or correctness of all
interactions; the PM still handles user visual confirmation through the existing route. Do not
generate, save, attach, or present screenshots. Do not automate prototype browser operations by
default; preserve only the user-request/failure-diagnosis exceptions in the existing verification
contract. PM semantic review and QA boundaries continue to use that contract.
In the existing handoff, return requirement coverage by stable REQ identifiers with concrete pages
and actual state anchors. The PM writes these back to the single requirements Markdown.
Requirements/plan Markdown-to-HTML generation is retired under [the retained reference](../xy-plan/references/requirements-markdown.md);
keep any existing HTML as historical material without requiring an update.
The design Agent does not edit the PM's source or create a mapping report; this association does not
change the prototype page, dependency fingerprint, or visual-approval contract.

交付具体原型页时，按[反馈消费合同](references/prototype-feedback.md)的当前交付入口
先执行 `prepare-delivery`，再以同一范围执行 `open`，向用户提供经验证的各具体 HTML 的 file URI。
需要批注或消费评审反馈时，按需读取该合同其余适用条款，复核来源修订后仅将有效意见交回原设计 Agent。
交付、批注和反馈沿用既有需求批准与适用的视觉批准流程。

For `standards_only`, return rule differences, their basis, applicability, and existing document
validation results. Distinguish candidates, adopted rules, and completed production migration; do not
add prototype requirements because HTML or browser evidence is absent. Reuse unchanged rules and do
not create extra reports, approval files, or memory records for closeout.
