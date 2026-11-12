# 3.0 主题文档与原型工作区

本页保留通用文档生命周期和原型工作区的有效要求，替代此前夹带 2.x 安装、同步及计划 HTML 生成记录的说明。当前产品规则以 [WORKFLOW](../../product/WORKFLOW.md)、[计划生命周期](../../platforms/shared/skills/xy-workflow/references/plan-lifecycle.md)和[Markdown 交付合同](../../platforms/shared/skills/xy-plan/references/requirements-markdown.md)为准；旧执行记录在 Git 中追溯。

## 单一主题与已验收基线

同一稳定主题在所选项目 adapter 的 `docs.plans` 内维护一份可编辑 Markdown，原位承载需求、方案、原型关联、当前恢复入口、上一已验收行为及必要批准证据。Full 采用[计划模板](../../templates/docs/PLAN.md)的六节形状；批准前草稿可留在当前请求证据区，批准后首次派发前保存。Light 按实际恢复需要保存，不强加 Full 计划或 QA。

当前目标、阶段和恢复状态与已交付事实分开。PROJECT 仅维护当前概况和明确验收的主题基线链接；completed、勾选和文档存在不证明功能已交付。Full 等集成 QA PASS 后，由 PM 投影当前已验收事实；Light 等必要验证及实际选择的审查接收后再投影。失败、暂停和取消保留原基线，不新建 feature 或 ADR 形成第二权威。

业务项目中已有计划、原型、规范、批准与恢复证据按原归属保留；此前迁移归档的 notes 原件与恢复资料继续由原资料位置保管，本仓旧说明删除不代表删除业务原件，也不抬升或撤回任何业务验收。项目自有字节、权限和工作区改动按实际授权保护；协作按项目语言约定，代码编写与优化保留详细中文注释，内置指令语言不改变确认、角色权限、fresh/handoff 与 QA 语义。完整日志与唯一恢复资料留在请求证据区，Git 保存完整历史。必要经验归既有相关主题或适用规范；没有归属时留当前交接，不建立 notes、替代杂记目录、空索引或占位主题。

## Markdown 需求与原型 HTML

需求和计划只以 Markdown 编辑、评审、派发与验收，不再生成同名 HTML。原型设计、具体原型 HTML、静态验证、依赖指纹和适用视觉确认仍有效。用户需求确认先包含原型建议与选择，需要原型时，具体页面准备完成后再进行视觉确认；原型验证本身不新增业务确认。

设计 Agent 在所选 adapter 的 `docs.standards_root/prototype` 内交付交互页面，并在原交接中返回需求覆盖、规范符合性、交付一致性自检。PM 将稳定 REQ ID 与具体页面、实际状态锚点的关联写入同一 Markdown，不另建映射报告或独立原型 QA。批准绑定实际页与依赖指纹；公共依赖改变时仅重开受影响页面。

## 通用工作区

本主题继续使用样稿既有的稳定需求 ID：

| 需求 | 当前有效内容 | 原型关联 |
| --- | --- | --- |
| REQ-004 原型工作区 | 入口直接进入工作区；分组折叠、侧栏收起和当前独立页面按需展示 | [概览状态](../standards/prototype/prototype-workspace.html#demo-overview) |
| REQ-005 画面优先 | 当前页名称、紧凑说明、实际画面、平台尺寸和折叠五节契约，产品区与展示外壳分离 | [需求详情状态](../standards/prototype/prototype-workspace.html#demo-requirement) |
| REQ-006 双向关联 | 需求指向具体页/状态，原型回到唯一 Markdown；文档导航不成为渲染依赖 | [页面说明状态](../standards/prototype/prototype-workspace.html#demo-guidance) |

[原型入口](../standards/prototype/index.html)保留通用[原型浏览工作区样稿](../standards/prototype/prototype-workspace.html)。`index.html` 的普通相对链接是唯一页面登记来源；最左侧分组可折叠、侧栏可收起，右侧按需承载当前独立页面，不预载全部页面。同页状态和弹窗不拆成多个文件。当前页保留名称、紧凑说明、高保真画面、平台尺寸与折叠五节契约，圆形返回定位当前导航，产品内容与展示外壳分开；本次移除退役 TUI 产品专用原型，不改变通用工作区交互或视觉规范。

原型页通过 `body[data-prototype-plan-source]` 绑定配置 `docs.plans` 下的规范 Markdown 路径；唯一 `nav.prototype-requirement-links` 包含一个 Markdown 链接，独立打开并包含 `target="_blank"` 与 `rel="noopener"`。已有业务项目的同名历史 HTML 可作为可选安全导航，不作为当前编辑权威或渲染依赖。本仓库退役计划 HTML 的导航已移除，通用样稿关联本页 Markdown。

页面与资源限制在所选原型根中，需求链接限制在明确关联的 plans 文档。项目存在多个 adapter 时显式选择并贯穿任务初始化与原型验证，不自行挑选另一配置。静态 HTML 验证与依赖指纹不替代用户视觉批准；用户批准、生产构建与唯一独立功能 QA 也分别承担各自职责。

## 维护与交付

先保留明确已验收的项目基线与原始批准，再更新当前任务包及必要链接。用户明确“本次只改实际产品、不改原型”按本次范围落实，并说明旧原型对本次变更的适用边界；原型评审中的修改仍归原型，按已批准原型实现仍需读取有效依据。

QA 检查当前受影响链接、主题归属与实际变更，不把本次文档清理扩大为业务项目批量迁移。当前产品使用官方插件，不再以安装器同步项目规范或中央 TUI 管理作为文档生命周期前置。实际运行、模型配置与宿主验收边界见[使用手册](../usage.md)。
