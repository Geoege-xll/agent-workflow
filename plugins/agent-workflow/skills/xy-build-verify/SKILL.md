---
name: xy-build-verify
description: "Verify the build, runnable results and relevant tests for the current Light／Full delivery, handing off real evidence according to actual risk."
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

# xy-build-verify

Both Light／Full use minimum sufficient verification appropriate to the actual delivery type. Production
code retains evidence of a successful affected-target build/compile and minimum startup/smoke or key entry;
verify documentation/static prototypes by type. Light defaults to a native implementer with the current
self-contained task pack; loading this Skill does not force a Full plan, DAG or independent QA. At handoff,
PM assesses independent audit, documentation and memory by actual risk. Full and selected mandatory
independent QA must not be omitted. Ordinary copy uses WORKFLOW's `Light UI copy` consumer/resource checks;
file suffixes do not exempt actual build inputs.

Before verification, read [verification scope](references/verification-scope.md).
Select proportionate commands from the task pack, adapter and repository evidence; discovered
commands are candidates, not a mandatory full-suite list. Preserve required checks, run selected
commands for real, and record every exit code. Reuse valid evidence and stop when coverage is
sufficient; expand or repeat only for a specific gap identified by the linked policy.
Determine the minimum sufficient scope before execution. Repository-wide tests require an actual coverage
need or explicit requirement, not merely entry into delivery. Production-target build/compile and runnable
evidence are mandatory. Hand off when coverage is sufficient and evidence remains valid; do not append
unsupported repeated builds/regressions.

<!-- workflow-contract: references/verification-scope.md -->

## Evidence contract

```text
## Build-verify
- Role: xy-*
- Scope: <changed behavior and mandatory coverage; distinguish new execution from valid reused evidence>
- Build / runnable result: <affected target, environment and actual build plus run/smoke evidence; non-production applicability>
- Commands: <exact commands>
- Exit code: 0
- Evidence summary: <success trailer and relevant warnings>
- Full log: <subagent thread reference or ignored local artifact path>
```

Do not paste a long raw log into the PM handoff. The full reference must be resolvable
by QA. If a command fails, include the exit code, a short failure excerpt, the full-log
reference, and `Status: BLOCKED`. After two failed repair attempts, stop and report to
the PM. Never invent, paraphrase away, or claim unexecuted validation.
In existing Validation, explain added coverage, invalidated evidence/specific risk, or the new diagnosis,
testable hypothesis/repair progress and expected evidence for continued failed rework. Keep relevant
unverified scope explicit. Without progress, stop the current repeated failing path early and return it to
PM under the policy above; do not reset existing limits or treat stopping as success. Without a gap, add
no verification report/test file. A scoped pass supports only that scope, not a claim that all tests passed.

`BUILD_VERIFIED` is evidence, not a QA result or user-facing completion state. For Full work, preserve the order
`QA PASS -> controlled-document projection -> PM commit assessment -> memory closeout -> final report`;
this Skill creates no QA report, design artifact,
approval record, or metadata file. Light assesses closeout at the actual handoff; an unaudited result is not QA PASS.
After PM accepts evidence and the necessary feedback window ends, close or retire the instance under WORKFLOW's
instance lifecycle. Retain readable full-log references; ending a native instance must not lose the sole evidence.

For isolated tasks, hand evidence back with the exact worktree/base/checkpoint identity; only PM
creates scoped local transport checkpoints. Follow `xy-workflow/references/worktree-delivery.md` for
composed-result verification and confirm/auto main-branch delivery. A unit's green tests are not
integration proof; keep checks proportional and preserve the ordinary non-worktree route.
