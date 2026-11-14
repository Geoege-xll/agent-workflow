# 精选上游 Skill 随插件交付

- 主题 ID：`selected-upstream-skills`
- 阶段：`completed`
- 模块：`plugins`、`lib/skills`、角色与三端发行
- 任务等级：`Full`
- 已验收版本：`3.0.0-alpha.9`

## 目标与范围

用户明确要求工作流插件提供标准流程与精选技能组合；新机器安装插件后无需逐个安装第三方 Skill。2026-11-13 确认接入上游 Grill Me 与 Taste，并明确指示“开始优化”；实施中进一步明确批准将 playwright-cli 及其 Skill 同样内置交付。PM 使用 Grill Me 深挖需求，xy-uiux 使用 Taste 完成设计方法，Web 实现验证及 Web 应用验收优先使用 Playwright CLI；不引入这些上游的其他无关技能。

现有本地改写的 grill-me 不能继续冒充第三方原版。第三方内容保留固定上游版本、真实名称、必要文件与许可证；本项目自己的覆盖记录、调度、确认与交接规则归入工作流适配层。

范围为 Grill Me、Taste、Playwright CLI 及其必要依赖、三端角色接入和 xy-* 命名。配置页视觉实现、通用原型工具及业务项目迁移由各自主题维护。Windows 暂停；不新增常驻服务、MCP、中央运行时或 TUI。Apple／Swift 与 modern-web-guidance 的新增讨论目前仅为评估，尚未纳入本主题已交付依赖。

## 需求与验收

- REQ-301：使用 mattpocock/skills 的真实 Grill Me 及其必要关联 Skill，接单时由 PM 负责需求访谈与覆盖判断；现有事实复用，后续需求不重启正在执行的任务。
- REQ-302：使用 Leonxlnx/taste-skill 的真实 design-taste-frontend，供 xy-uiux 使用；清理 ui-ux-pro-max 的强制依赖、预载与隐式回退。
- REQ-303：统一声明第三方来源、固定 commit、文件摘要、许可证、依赖闭包和角色绑定。构建读取已经审阅的本地原版资源，不联网、不运行上游脚本；校验失败明确拒绝。
- REQ-304：三端发行包带齐必要 Skill、脚本、资源与引用；新机器无需另装这些 Skill。安装齐备与 Node／浏览器等运行环境、宿主调用能力分别诊断。
- REQ-305：按官方能力投影角色声明与调用入口。Claude 的 skills 预载、AGY 的路径声明、Codex 的可用技能与指令交接分别处理；声明存在不冒称实际执行。
- REQ-306：上游原版内容与工作流适配分离。保留 PM 持续接单、原生派发、两步确认、独立上下文、原型阶段约束和唯一 QA；不得让第三方命令接管整个工作流。
- REQ-307：具备可复用的显式上游更新入口，固定候选后校验差异和依赖；不在会话开始时自动拉取 latest，不偷偷安装全局技能或启用第三方 Hook。
- REQ-308：独立验收覆盖三端干净载荷消费、依赖缺失／篡改拒绝、角色调用规则和保留原流程。记录真实宿主验证范围，未验证项明确保留。
- REQ-309：Playwright CLI 的真实上游 Skill、官方已发布固定版本 CLI 和必要运行依赖随插件齐备，不依赖用户另外安装全局 playwright-cli 或运行临时 latest npx；记录源码／包来源、完整性、许可证与版本对应关系。
- REQ-310：Node 保留为明确运行前提，不修改 PATH 或自动安装系统运行时；浏览器复用官方已有缓存，缺失时通过固定版本官方入口按宿主权限准备。不得运行会向业务项目写 .playwright 或修改 .gitignore 的初始化命令来冒充插件安装。
- REQ-311：优先复用项目已有测试。需要补充 Web 交互验收时，优先 playwright-cli 与其 Skill；其他浏览器工具只在存在具体能力／环境限制或用户指定时采用，电脑操控用于确需桌面能力的场景。记录实际工具选择、环境、范围和证据，禁止失败后无理由随机切换或绕过权限限制。
- REQ-312：原型阶段默认不自动化／截图、独立只读 QA、项目数据与现有登录边界继续保留。Playwright 的会话及临时产物明确归属本轮任务，复用系统浏览器缓存，关闭本轮自建会话，不清理用户已有浏览器／配置；真实运行与技能完整阅读分别报告。
- REQ-313：用户追加并明确选择“插件名改为 xy-workflow，对外短指令也统一 xy-*”。保留既有 xy-* 内置名称；配置入口为 xy-config，精选入口为 xy-grill-me（显式）、xy-grilling（PM 自动）、xy-taste、xy-playwright。Codex／Claude 命名空间按官方格式为 xy-workflow，第三方 canonical 名称、正文、包 metadata 与许可证不改。
- REQ-314：命名调整覆盖真实官方清单、角色／命令入口、打包与分发验证、配置组件识别和必要偏好身份处理；保留现有用户／项目模型偏好、项目资料与本地数据目录，不顺带改 GitHub 仓库地址或做 2.0 兼容迁移。旧 3.0 插件切换使用官方客户端，在任务收尾后进行；本轮实施期间不替换正在使用的物理资源。

保留合同：用户再次明确“文档记忆优先，配合 agentmemory”。现有可选增强、按需召回、严格项目隔离与溯源、文档和明确批准优先的合同不删除。独立只读评估确认本项目 ID 仍是模板占位符，当前工具注册信息尚不足以证明服务端项目隔离，因此本轮不召回／保存、不声称已实际使用；这不阻断工作流或精选技能交付，也不转化为安装／重构记忆服务任务。

### 验收方法

- 精选技能的每个发行文件可追溯到固定上游原文或明确的本项目适配，引用关联技能与本地资源均齐备。
- 实际调用现有构建器生成三端候选，并从包外执行资源校验和代表性入口；运行环境检测不自动安装软件。
- 缺失文件、篡改内容、危险路径／链接与错误依赖声明明确失败；构建全程不需要网络。
- 当前角色绑定、需求覆盖、设计规则和单 Reviewer 合同的受影响测试通过；不将静态／fixture 成功表述为三端模型实际运行通过。
- 复用仍匹配的证据，新增或重跑测试说明对应风险；证据保护到 dist/evidence/selected-upstream-skills，scratch 仅用于本轮工作与返工。
- 通过独立 QA 后更新本计划、插件交付说明和必要使用文档的当前事实；不修改业务项目资料。

## 方案与原型关联

固定上游原版、锁定声明、离线资源校验与工作流薄适配各有单一归属：构建只读本地已审原版；工作流覆盖、调度、确认和交接归适配层。依赖与流程作者按精确文件归属协作，纯偏好读取由独立配置核心投影，唯一 QA 集成验收。没有 UI 变更或新增原型批准。

Grill Me 固定来源为 `mattpocock/skills@5863806dd4e15c63174bee4e7515a4256792ecfa`，仅两个必要 Skill 目录及 LICENSE；Taste 为 `Leonxlnx/taste-skill@f6b76575f949707b4e3c37cd86cb44b0b98643e8`，完整技能目录及 LICENSE，资产原始 credits 保留。

Playwright 追加采用官方已发布 @playwright/cli@0.1.24 及其精确的 playwright、playwright-core@1.66.0-alpha-1794252756000 闭包；运行时 alpha 名称如实保留，不与用户已有 0.1.18 混用。三份官方包保持原版文件、许可证与 NOTICE，随插件提供标准 Node 模块布局和薄启动器，不依赖全局 npm 安装。其内置的完整 Skill 与当前本机 Skill 一致，来源和运行版本以发行包锁定为准。

运行时通过 NO_UPDATE_NOTIFIER=1 禁止隐式 npm 更新查询，通过已核实的 PLAYWRIGHT_SKIP_BROWSER_GC=1 保留其他浏览器缓存。不会使用外层 CLI 不接受的 --no-remove，也不执行卸载或全会话清理。浏览器默认通道、固定 revision 与准备命令以本轮固定源码合同为准；首次运行不能把不同版本的缓存冒充匹配。

### 上游与官方资料

- Grill Me：https://github.com/mattpocock/skills
- Taste：https://github.com/Leonxlnx/taste-skill
- Playwright CLI：https://github.com/microsoft/playwright-cli
- Playwright CLI 安装：https://playwright.dev/agent-cli/installation
- Claude 子代理：https://code.claude.com/docs/en/sub-agents
- AGY 子代理：https://antigravity.google/docs/subagents?app=cli
- Codex 子代理：https://learn.chatgpt.com/docs/agent-configuration/subagents

## 当前进展与恢复入口

已验证：精选资源、三端实际候选与包外消费、Playwright 真实 HTTP 最小闭环、命名／身份与发布权限修复，已随 alpha.9 发布并完成本机三端核验。

待验证：三宿主模型实际调用与运行效果不由技能存在、参数投影或插件安装证明。当前记忆 ID 仍为模板值，服务端项目隔离未获证；本轮未查询或保存 agentmemory，未查询不代表服务故障。

维护入口是锁定清单、现有显式上游候选更新命令和第 3 节固定来源。未来更新先审差异、许可证与依赖闭包，再构建／验收；不在新会话启动时拉取 latest。插件物理资源仅在活动任务收尾或完整交接后更新。本轮结构整理不改变已安装技能或真实偏好。

## 验收结果与当前已交付行为

- 三端候选包含八个内部核心 Skill、四个精选公开别名和独立 `xy-config`，共十三个发现入口；Grill Me 仅引入原版用户入口与必要 grilling，Taste 和 Playwright 的上游资源、许可证和模式保留。
- Playwright CLI 固定为官方 `0.1.24` 及其两个精确运行包，真实 HTTP fixture 的打开、快照、点击、再次快照与关闭通过；旧 file:// 拒绝记录保留。未对业务原型自动化或截图，也未改本机全局 CLI。
- 命名、偏好读取和独立配置 alpha.5 的实包、包外入口及两个产品身份三文件同源通过；已有用户／项目偏好未写入。
- 原独立 QA 发现发布器把 local-source 全部视为 644，与十五个上游可执行文件冲突。修复后 producer／publisher 共用唯一 archive_modes；严格特殊权限与同步篡改负控、十个发布消费者节点、当前六包同一生产比较分支通过，原 Reviewer 完成增量 PASS。
- Git 交付评估：两个相关请求（通用评审工具与正式配置工作台）均分别独立 QA 接受。已按“真实 CI 组件资产发布及下载校验 → 固定绑定并独立复核 → 插件 CI／三渠道发布 → 官方客户端安装核验”完成交付。最终为 alpha.9／组件 alpha.5，本机三端文件与同源候选逐字节一致；模型偏好、业务资料与用户旧文件保留，真实模型采纳不由安装证明。alpha.8 末端发现的历史库存校验缺陷已在 alpha.9 修复并完成实际准备，详见 `native-model-preferences.md`。

## 批准依据与必要证据

- 批准依据：用户明确要求精选技能随插件交付，并先后批准 Grill Me、Taste、Playwright CLI；另明确选择“插件名改为 xy-workflow，对外短指令也统一 xy-*”。
- 验收证据：唯一 Reviewer 已接受三提供者及发布权限修复；最终插件来源 `aa3b6f559cc692b738618d16f66009f8ec02f9d2` 的[两系统 CI](https://github.com/Geoege-xll/agent-workflow/actions/runs/43436450887)及[三渠道发布](https://github.com/Geoege-xll/agent-workflow/actions/runs/43438890253)通过，本机载荷与同一候选一致。

完整命令、原失败、来源指纹及 schema 2 QA 交接保存在 `dist/evidence/selected-upstream-skills/`。本主题 PASS 不覆盖通用原型工具或配置页视觉，后者分别由自己的唯一 QA 验收。

历史双提供者阶段曾完成三端构建、26 个受影响测试及 Claude／AGY 官方 normal／strict 校验；旧 Codex 大类在当时存在 fixture 字段守卫及角色名断言失败，不得称整个旧大类通过。Playwright 加入后由同一请求唯一 Reviewer 验收完整范围，没有借用先前两提供者结果冒充三提供者完成。

完整历史分工、阶段材料与原始索引见[整理前 Git 原文](https://github.com/Geoege-xll/agent-workflow/blob/f63a98bedd9613dbfcf35dd5bbd97253f26f8c56/docs/plans/selected-upstream-skills.md)。原始材料保持原位，本轮不读取或改动未跟踪迁移文档。
