---
name: xy-ui-design
description: "供 xy-uiux 在 prototype 模式设计高保真可交互 HTML 原型，或在 standards_only 模式维护获准设计规范；生产实现与 QA 只按既有设计权威消费适用规则，不因此创建原型或取得写入权。"
---

<!-- agent-workflow-pack:managed-skill -->

# xy-ui-design

## 使用边界

沿用当前 Task Pack、项目适用规范与 `xy-uiux` 永久职责。加载本 Skill 不授予写入权，
不改变任务等级、实施者、用户原型选择、UI-Conformance、审批或唯一独立 QA 路线。
PM 已选择的 `design_mode` 决定适用阶段；预加载不等于必须执行全部分支。

- `prototype`：仅在当前获准的 required 原型范围内工作，最终交付稳定、免构建、
  可直接打开的高保真可交互 HTML。前期线框只用于 IA 与方案比较，不能充当最终原型。
- `standards_only`：仅维护精确授权的设计规范叶，遵守现有
  `xy-workflow/references/design-standards.md`；不写 HTML/CSS，不运行原型验证，不请求视觉批准。
- 生产实现与 QA：只读消费当前已采用的设计 authority 及适用专业规则，
  不借本 Skill 修改设计方向、扩大 owned_paths，或恢复 waived/UI-Conformance 的原型门槛。

## 基线与设计分析

以下设计操作用于 `xy-uiux` 的授权任务；生产实现与 QA 只对照既有 authority 消费适用规则，
不执行设计阶段或触发原型验证。
通用规则读取 [设计基础](references/foundations-rules.md) 与
[组件交互](references/components-rules.md) 的适用条款；项目只保留实际采用的 token、风格、尺寸、
平台映射和业务差异。存在项目特有规范索引时沿实际链接读取，再核对相关产品证据和当前页面，
复用完整读过且未变的上下文，不假定叶文件名或预读全部项目。已批准需求与项目规则优先。
复用 `ui-ux-pro-max` 做设计分析，按其说明选择最小相关查询；结果只作建议，
不持久化另一份设计系统、不调用安装或构建流程，不让通用风格替换项目基线。

<!-- workflow-contract: references/foundations-rules.md -->
<!-- workflow-contract: references/components-rules.md -->

## 按阶段读取

设计分析、细化页面或维护规范时，读 [设计质量与完成标准](references/design-quality.md)。
按当前任务适用性处理内容层级、组件、状态、平台和可访问性，不为凑检查项扩大设计范围。

<!-- workflow-contract: references/design-quality.md -->

仅在 `prototype` 模式组织页面与展示时，读 [HTML 原型画布](references/prototype-canvas.md)。
它承接角色原有画布合同，不要求重做无关页面或给直接开发分支补原型。

<!-- workflow-contract: references/prototype-canvas.md -->

## 验证与交接

`prototype` 由设计 Agent 完成需求覆盖、规范符合性、交付一致性三维自检，复用
`xy-prototype-verify` 的静态验证和五节页内契约；结果沿已有 `static_checks`、
`blocking_findings` 与 `result` 交接，不新建独立原型 QA、报告或审批。用户仍最终确认。
只向 PM 交接具体页面、范围、操作、共享影响、真实证据与未验证项；静态通过不代表
视觉满意或全部交互已合格，用户视觉确认仍由 PM 按现有路线处理。不得生成、保存、
附加或呈现截图。原型浏览器默认不自动操作，仅沿用现有验证合同的用户请求/故障诊断例外；
PM 语义复核和 QA 边界继续使用该合同。
需求覆盖在原有交接中按稳定 REQ 编号返回具体页面和实际状态锚点；PM 写回唯一需求
Markdown 并按 [需求 HTML 交付](../xy-plan/references/requirement-html.md) 重渲染同名 HTML。
设计 Agent 不改 PM 原稿、不新增映射报告；此关联不改变原型页面、依赖指纹或视觉批准合同。

`standards_only` 返回规则差异、依据、适用范围及既有文档校验结果；区分候选、已采用
规则与已完成生产迁移，不因缺少 HTML 或浏览器证据而新增原型要求。没有规则变化就复用，
不为收尾创建额外报告、审批文件或记忆记录。
