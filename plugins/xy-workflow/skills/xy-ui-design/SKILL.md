---
name: xy-ui-design
description: "For xy-uiux to design high-fidelity interactive HTML prototypes in prototype mode or maintain authorized design standards in standards_only mode; production implementation and QA consume applicable rules only under existing design authority, without creating prototypes or gaining write authority."
---

从本 Skill 的物理目录向上两级确定插件根。使用同包的[宿主资源说明](../../plugins/plugin-context.md)。当前实例已具备同一物理来源、同一版本的完整说明时直接复用；独立启动或内容缺失时补读，来源或版本变化时重新读取。


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

方案仍待决定时，设计者可按 PM 明确的只读咨询整理选项和既有交互依据，交回 PM 统一提案。在收到含已确认范围及所依赖行为的正式设计任务包后，再动手制作页面。设计交接在原回复中列出 REQ、具体 HTML 与对应状态锚点，交 PM 回填原需求主题。新增权限、失败恢复等行为须先回到 PM。

- `prototype`: Work only within the currently authorized required-prototype scope and deliver
  stable, build-free, directly openable, high-fidelity interactive HTML. Early wireframes serve only
  IA and option comparison; they cannot be the final prototype.
- `standards_only`: Maintain only the precisely authorized design-standard leaves under the existing
  `xy-workflow/references/design-standards.md`; do not write HTML/CSS, run prototype verification,
  or request visual approval.
- Production implementation and QA: Read and consume only the currently adopted design authority
  and applicable professional rules. Do not use this Skill to change design direction, expand
  owned_paths, or restore prototype gates for waived/UI-Conformance work.

## 生产实现与 QA 只读入口

生产实现从当前 Writer 包取范围；QA 从 `reviewed_ui_changes` 中的各 Writer 投影或已授权设计规范差异确定验收项。在当前批准依据与项目规范索引中定位对应锚点、规则 ID 和指纹，再核对以下原文的适用条款。沿用已完整读取且仍可用的同版来源。来源访问模式要求全文时仍须读完。

- 基线、颜色与 token、平台约束、字体或无障碍，定位[基础规则](references/foundations-rules.md)中的相应标题或 ID。
- 组件复用、弹窗、分段控件、状态反馈或响应布局，定位[组件与交互规则](references/components-rules.md)中的相应条款。
- 判断跨页面一致性、内容层级或中断恢复时，从[设计质量](references/design-quality.md)的基线、视觉或组件章节定位相应段落。按实际变更追到状态、调用点和项目设计权威。各类示例不构成规则白名单。

<!-- workflow-contract: references/foundations-rules.md -->
<!-- workflow-contract: references/components-rules.md -->
<!-- workflow-contract: references/design-quality.md -->

## 设计 Agent 的创作与交付

`xy-uiux` 按授权模式阅读设计质量中的设计分析、精修、自查及交付条款。需要额外设计方法时按[共享 Skill 选择规则](../xy-workflow/references/skill-selection.md)选用 Impeccable。若仍有具体的图表、表单无障碍、字体、配色或样式问题，可按需[查询一个专题](../xy-workflow/references/skill-selection.md#design-topic-query)。结合适用的基础与组件规则、项目索引的实际链接及相关页面分析，优先使用已批准需求与项目规则，按需核对实际采用的值和映射。

组织原型页面时使用[原型画布](references/prototype-canvas.md)，并按[静态验证合同](../xy-prototype-verify/SKILL.md)验证具体页。Antigravity 直接交付具体 HTML。Codex 与 Claude Code 按[反馈消费合同](references/prototype-feedback.md)准备受管交付入口。Do not generate, save, attach, or present screenshots. Do not automate prototype browser operations by default. 仅既有验证合同允许的用户明确要求或具体故障诊断例外适用。

<!-- workflow-contract: references/prototype-canvas.md -->
