# 角色技能绑定与按需加载

- 主题 ID：`role-skill-routing`
- 阶段：`completed`
- 模块：`lib/skills`、`plugins/selected-skills`、角色与三端插件投影
- 任务等级：`Full`
- 已验收版本：`3.0.1`

## 目标与范围

用户于 2026-11-14 明确批准开始优化 Web、Apple 两个 Agent 的技能内置，并追加所有 Agent 都应按任务使用宿主提供的其他技能。内置精选是可用的推荐能力，不是封闭白名单；不预读或自动安装全部技能。用户进一步澄清：内置绑定不能等于强制选择，因此本轮新增两入口保留可发现性，不放入角色原生强制预载；按当前任务缺口选择，选中后遵守适用指令。

本轮为 xy-web 接入 GoogleChrome modern-web-guidance 的固定完整技能与必要 CLI 资源；为 xy-apple 内置可按需选用的 Apple 官方 SwiftUI 指导本机发现与只读消费适配。官方内容优先使用用户已有 Xcode，未确认再分发授权前不复制 Apple 正文到公开插件。Swift 社区技能作为后续专项候选，不在本轮无差别整包引入。

保持 PM 持续调度、两步确认、原型阶段、fresh/handoff-only、唯一 QA、项目技术栈与权限。Windows 继续暂停；不修复或替换本机 Xcode，不新增常驻服务、MCP、全局安装或业务项目配置副本。

## 需求与验收

- REQ-501：现代 Web 指导绑定 xy-web 的 HTML／CSS／客户端 JavaScript 工作；先按任务技术风险与证据缺口判断是否选用，选用后先搜索再读取相关指导，遵守项目浏览器支持目标，与 Taste 设计权威及 Playwright 验证职责分开。
- REQ-502：现代 Web 上游原文、CLI、必要资源与许可证固定来源和内容身份，复用现有精选依赖管理；不通过 latest npx、隐式更新、遥测或全局 CLI 执行。不把完整性或 Node 就绪冒充指导查询成功。
- REQ-503：Apple 适配在任务需要并被选用时优先读取实际选定 Xcode 的官方 SwiftUI Specialist；What's New in SwiftUI 仅在相关 API／迁移任务加载，不强制项目提高 Swift／OS 版本或改变 UIKit、架构和包管理。来源缺失、格式变化、工具版本变化明确诊断，不从第三方镜像假冒官方来源。
- REQ-504：Apple 指导不复制到 Git 或发布包；适配器只读发现与消费本机官方资源或明确的官方导出。记录实际 Xcode 来源、版本、内容身份与未证边界；普通查询不启动 Xcode、不导出全量技能、不改全局技能目录。相关引用有界读取，不读无关 Xcode 资料。
- REQ-505：所有 Agent 在当前任务、实际技术栈与角色范围内，按需发现并完整读取宿主实际提供的用户级、项目级或其他插件技能。内置固定版本与同名外部来源明确区分；不默认安装、扫描全部目录或一律预载全部技能。
- REQ-506：技能内容不扩大 owned_paths、角色职责、工具／网络权限、确认或独立 QA 权威；冲突回 PM，不静默替换、丢弃约束或声称已执行。PM 的 Task Pack 明确必要技能；实施 Agent 可选择职责内的补充技能并报告实际来源与使用范围。
- REQ-507：来源校验、诊断、读取和运行入口职责分离，三平台按官方实际能力投影，不用 Claude 的预载特性假定另外两平台同样执行。测试覆盖缺失／篡改／不安全路径／版本失效／引用闭包和现有精选依赖消费者；真实三端包外消费与唯一独立 QA 验收。

## 方案与原型关联

复用现有精选依赖声明、canonical 原版与薄适配、离线打包、物理插件 source_pack 入口，不添加第二个包管理器。modern-web-guidance 使用已核对的官方 npm 精确发布 `1.0.0`，源码 gitHead 为 `544c250575f7811d87fef8b1c064bc9571cbfb80`（modern-web-guidance-src）。其完整发布包含本地搜索索引与指导内容，search／retrieve／list 离线读取；Node 22+ 是已有运行前提，不执行 npm／npx，不自动安装 Node。运行禁遥测与文件日志，只开放上述三个只读命令及明确诊断。发布 Git 树 `4dd968349e54ca45a05dd5c818fb035c9054b022` 虽声明 bin，却没有实际 mjs，不能以只复制 Git Skill 冒充 CLI 齐备。最终闭包摘要与许可证由真实内容校验确定。

Apple 的本机专有资源与可再分发 vendor 闭包分离。PM 已观察到 Xcode 27.2（27B52）：官方导出命令因 Xcode 无法启动而失败，但应用内存在 SwiftUI 两项原始模板及引用。应用包路径／格式是本机观察，不冒称稳定官方 API；读取应拒绝不完整或变化的来源，并保留错误而非自动修复系统应用。

共享按需加载规则设单一权威，角色只声明默认技能与触发条件，三宿主约束复用；不把每个角色复制成个人技能清单。本轮没有产品 UI 变更，不需要新增原型；已获准的第四版工作台与原型机制不变。

## 当前进展与恢复入口

- 已验证：当前角色未固定 Apple／现代 Web 指导；现有精选框架只有 Grill Me、Taste、Playwright，需沿其声明与构建机制扩展。modern-web-guidance 本机技能通过 latest npx 调用，不能照抄为内置运行方式。
- 已观察：官方文档确认 Xcode 27 提供两项可导出 SwiftUI 技能；本机官方导出失败，原始模板及其引用实际存在。未据此声明 Xcode 可正常构建或插件宿主已加载这些技能。
- 已派发：依赖／只读消费核心与共享调度／角色规则两个独立 fresh 作者，文件归属无重叠；现代 Web 三命令及 Apple check／分段 read 接口已固定并共享。
- 已实现：两种来源读取、两个可发现薄入口与全角色共享选择规则；本轮新入口不进入角色原生无条件预载。固定 Web CLI 的真实离线查询、本机 Apple 来源绑定读取及安全负控均有实际证据。
- 已集成：完整插件工作流合同及更新后的三端包外精选消费者共 20 项通过（129.325 秒），覆盖实际权威读取、fresh／确认／QA 门禁、可发现但不预载、固定 Web 查询和 Apple 布局消费。
- 已验收：唯一 Reviewer 对 302 路径和 34 条工程规则给出 PASS，PM 实际验证 schema 2 交接；两个入口仅发现／条件推荐，原实例生命周期与确认／QA 边界保持。
- 已交付：独立[正式发行主题](stable-product-release.md)已完成最终 CI、真实资产、三 stable 来源及本机 3.0.1 安装核对；本请求源码 PASS 与发行证据分别保留。

## 验收结果与当前已交付行为

源码候选 `3.0.1` 已接受本轮行为：固定官方现代 Web 完整闭包与离线查询、Apple 本机官方资源安全绑定读取、全 Agent 共享按需选择、两个新入口可发现但不强制预载。Node 22+ 与 Xcode 27.x 观察布局为明确适用边界；未自动安装运行时、启动 Xcode 或修改项目／用户配置。

本行为已随正式 3.0.1 发布，本机三端实际载荷匹配最终 CI 原包；发行证据归独立主题。安装与查询证据不表示宿主已选用技能或指定模型已采纳。

## 批准依据与必要证据

- 批准依据：用户“ok，开始将 web、apple 两个 agent 的技能内置开始优化”，随后明确所有 Agent 都应根据需求按需加载可用 Skill。
- 验收证据：唯一 QA Pack SHA `621beeb630ea6b2accdd12547d45e6ede8e0c707e3fe3da4c0784a9921057cda`，交接 SHA `973538a84616db73985ac8a0a065faad8db43729886fac87f25a5dd34261876d`；PM 实际 validate 退出 0，302 路径与 34 规则完整覆盖。完整来源、许可、原始运行／拒绝／短返工与 QA 证据保全于 `dist/evidence/role-skill-routing/role-skill-routing-evidence.zip`，SHA `faea6a49efff2cf9653b240e1dc5ffc501751c8df8ad2e5b380139922095d800`。

来源：[Apple 官方 SwiftUI 技能介绍](https://developer.apple.com/videos/play/wwdc2026/269/)、[Apple Xcode 扩展说明](https://developer.apple.com/documentation/xcode/extending-and-customizing-agents)、[GoogleChrome 发布源](https://github.com/GoogleChrome/modern-web-guidance)、[GoogleChrome 源码](https://github.com/GoogleChrome/modern-web-guidance-src)。候选固定 commit、具体许可证及完整执行日志由真实调查写回，不用 main 或名称代替内容身份。
