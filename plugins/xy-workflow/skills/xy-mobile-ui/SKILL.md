---
name: xy-mobile-ui
description: "按需指导 iOS、iPadOS、Android 原生界面和微信小程序的设计、实现与审查，覆盖安全区与键盘、导航与返回、状态生命周期及无障碍。"
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


# 移动端界面指导

当前任务影响 iOS、iPadOS、Android 原生界面或微信小程序的相关行为时，由设计者、实现者或 QA 按职责选用。普通 Web（含移动 H5）、桌面、纯业务逻辑及无关文案通常无需加载。嵌入原生 App 或小程序的 H5 若涉及宿主交互，本文仅指导受影响的宿主边界，网页本身沿用现有 Web 指导。

相对链接用于已发现的 Skill 内导航。通过插件的 `source_pack.py resource` 定位或以 `helper`
调用 `lib/documents/context_read.py` 分页时，从已验证的插件包读取，使用包内规范路径，例如
`platforms/shared/skills/xy-mobile-ui/references/mobile-rules.md`。

1. 完整读取[移动端共享规则](references/mobile-rules.md)，从当前需求、项目规范和实际页面选择适用条款。
2. 按受影响的平台读取 [Apple](references/apple.md)、[Android](references/android.md)或[微信小程序](references/wechat-miniprogram.md)。按实际框架、已接入的组件库和支持的系统或基础库版本选择方案。SwiftUI 存在实际平台知识缺口时，可继续选用已核验的 `xy-apple-guidance` 本机官方资料。
3. 设计沿用现有页面契约，开发与 QA 沿用现有交接。只有涉及来源核对或维护时才读[参考来源与许可](references/sources.md)。

现有设计、工程标准和项目批准范围继续适用。此指导采用项目现有技术栈、依赖和系统基线，并沿用已授权的原型、确认和独立 QA 流程。
