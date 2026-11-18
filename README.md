# xy-workflow

面向 Codex、Claude Code 和 Antigravity 的原生多 Agent 工作流。主会话持续作为 PM 接收需求，按任务重叠、依赖和容量协调原生子代理，保留适用的需求确认、原型与视觉确认、独立 QA 和交付流程。

当前正式版为 **xy-workflow 3.0.6**，配套 **Native Agent Config 0.1.5**。本工作树的下一补丁候选为 3.0.7／0.1.6，尚未发布。三个 stable 来源提供正式插件，候选配套组件的发行状态由随包描述记录。[插件版本源](product/PLUGIN_VERSION) · [固定组件描述](plugins/maintenance/component.json) · [发行记录](docs/plans/stable-product-release.md)

`3.0.6` 修正配置页搜索选择控件的重复边框，原生定义左侧列表仅显示名称；Codex 显式打开时自动补齐用户级缺失内置原生定义，并跳过当前项目已有同名。调用偏好预览会按需准备缺失或过期模型目录并复用进行中查询；模型字段、调用偏好与工作流启停仍分别预览确认，保存、宿主加载和实际模型运行分别验收。该发行版启动器使用固定配套的 Native `0.1.5`。

## 工作流保持

- PM 持续接单：A 执行期间可以继续讨论 B、C，按真实依赖选择并行、复用、追加或等待。
- 需要原型的 Full UI 设计变更保留需求确认、视觉确认。Light、非 UI、一致性任务及用户明确选择直接开发，按各自原有规则执行。
- 原型设计、可交互 HTML、原型验收与视觉确认保留；计划使用 Markdown，不生成计划 HTML。
- 实现交给对应原生子代理。独立新任务使用新实例和必要交接，不复制完整 PM 会话；同任务追加及短返工可复用。收口保全证据后原生关闭，缺少关闭能力时逻辑退休，不把退休当作清空记忆或释放仍在占用的资源。
- Full 保留请求级唯一独立只读 QA。内置技能提供精选能力，所有角色仍按当前任务选择可用技能，不无条件预读所有内容。

完整规则以 [WORKFLOW](product/WORKFLOW.md) 和实际任务适用的 Skill 为准。安装插件或打开模型配置不会产生业务批准。

## 两个独立产品

| 产品 | 职责 | 说明 |
| --- | --- | --- |
| xy-workflow 插件 | PM 入口、工作流 Skill、角色和任务 helper | [插件说明](docs/plugin-v3.md) |
| Native Agent Config | 本机模型目录、原生定义、调用偏好和工作流启停 | [配置工具说明](docs/agent-configuration.md) |

工作流通过官方客户端安装到插件缓存，不要求中央登记、配置服务或 MCP。项目只保存轻量 adapter 和业务资料；网页、脚本与可选 MCP 共用独立配置核心。

## 远程安装正式插件

需要已有对应平台官方客户端、**Python 3.11+** 和 **Bash**；模型运行还需要客户端登录。helper 发现现有解释器，不自动安装软件或修改 PATH。

### Codex CLI

```bash
codex plugin marketplace add https://github.com/Geoege-xll/agent-workflow.git --ref plugins-codex-stable
codex plugin add xy-workflow@xy-workflow
codex plugin list --json
```

安装后在官方 `/hooks` 中审阅并信任当前 SessionStart 定义，再开始新会话。安装不自动授予 Hook 信任；Codex App 图形界面的运行验证单独判定。

### Claude Code

```bash
claude plugin marketplace add 'https://github.com/Geoege-xll/agent-workflow.git#plugins-claude-stable'
claude plugin install xy-workflow@xy-workflow --scope user
claude plugin list --json
```

安装后开始新会话；用户自有默认设置按客户端规则优先。

### Antigravity CLI

```bash
agy plugin install https://github.com/Geoege-xll/agent-workflow/tree/plugins-antigravity-stable
agy plugin enable xy-workflow
agy plugin list --json
```

AGY 使用 GitHub `tree/分支` 地址，不能换成 Claude 的 `#分支` 写法。三个分支只承载同一成功 CI 的已校验宿主产物；Codex／Claude 的正式市场名和插件名均为 `xy-workflow`。历史 alpha／local 安装不会自动切换，先收尾活动任务，再通过官方客户端移除旧安装并安装所选正式来源，避免同名双来源启用。

更新、来源检查和卸载见 [INSTALL](plugins/INSTALL.md)。源码构建仅供开发及维护，见[开发指南](docs/development.md)。自有 Git 正式分发不等于官方公开目录上架。

## 项目与模型配置

在实际项目目录开启新会话。新项目通过插件 helper 显式创建最小 `.awf/project.yaml`，已有有效根 `project.yaml` 可复用；不会复制整套规范或覆盖业务文档，详见[插件说明](docs/plugin-v3.md)。

配置入口为 `xy-config`：Claude 使用 `/xy-workflow:xy-config`；Codex 从 `/skills` 或 `$` 选择器选择实际发现的入口；AGY 使用 `/xy-config`，以客户端实际发现项为准。省略动作等价 `open`，另有只读 `status` 和 `doctor`。首次缺少组件时先说明固定版本及来源，经用户明确确认才准备；普通业务不准备组件或启动服务。

配置页默认进入“调用偏好”，提供用户级和项目级的通用默认及逐 Agent 设置，插件缓存角色保持只读。模型目录来自本机对应客户端或有效配置，推理选项按当前模型处理；设置先预览、再确认保存，PM 在后续派发前读取。保存、原生文件重新加载与指定模型实际运行分别判断，不改变当前主会话或运行中的 Agent。

Codex 从完整插件调用 `xy-config open`（省略动作同样适用）时，会先按显式校验的模板自动补齐用户级缺失的七个内置原生 Agent，再实际回读并启动或复用控制台；独立组件须已安装。项目打开会先检查本次项目完整清单，项目已有同名定义会跳过，避免新增重复用户来源；其余缺失项补到用户级，供全部项目按宿主规则发现，当前项目文件保持。只创建缺失项，同名定义、用户正文、模型和推理字段全部保留，重复打开与后续插件升级不重写现有定义，也不设置模型、推理、启停或信任默认。网页模型保存仍需预览确认。插件安装本身、`status`、`doctor`、普通 GET/context、Claude 和 AGY 不创建 Codex 文件；未绑定完整插件来源的独立工具不自动补齐。维护入口不扫描其他业务项目，后续无项目打开仍可能创建用户同名定义；跨来源加载优先级未验证。已有定义中的插件路径保留首次来源。候选插件可通过 `xy-config rebind` 预览用户级受管定义的重新绑定，用户核对后再应用；坏来源、权限或并发失败明确诊断且不自动重试。详见[原生定义说明](docs/agent-configuration.md)。

Codex／Claude 提供用户级和项目级工作流启停、恢复继承；AGY 保留官方管理说明。0.1.3 增加普通刷新后的短期连接恢复，保持原平台、范围与真实项目路径；连接失效或存储拒绝时明确提示重新打开。界面对齐指定中央业务稿，提供通用默认和逐身份表格、原生定义搜索列表与详情双栏；保留三类独立草稿、只读边界、未知值和失败收据。停用前保存页面给出的独立恢复命令。实际组件版本和原有项目启停设置以对应客户端及配置回执为准，不代表所有项目均启用。

## 精选技能与文档

Grill Me、需求访谈 primitive、Taste、Playwright CLI 随插件固定交付，分别通过 `xy-grill-me`、`xy-grilling`、`xy-taste`、`xy-playwright` 访问。原版资源、许可与薄适配分开维护；不要求另装全局 Skill 或 CLI。原有工作流方法保持，所有角色也可按任务使用宿主实际提供的其他技能。

新增 `xy-web-guidance` 和 `xy-apple-guidance` **可发现、按条件推荐，不进入角色无条件预载**。前者随包提供 GoogleChrome 官方固定版本的完整现代 Web 指导与离线查询，查询需要已有 Node 22+；后者只读使用本机 Xcode 官方 SwiftUI 指导，当前验证边界为观察到的 Xcode 27.x 布局，不再分发 Apple 正文。详见[角色技能主题](docs/plans/role-skill-routing.md)。

计划文档借鉴 Anthropic doc-coauthoring 的分节精修与读者检查，保留五项元信息、六个固定章节及原地更新；显式计划校验不扫描未选文件，不增加访谈、确认或读者 Agent，见[计划规范主题](docs/plans/plan-document-quality.md)。

3.0.2 的通用评审工作台提供浏览／批注、固定视口相机、独立 A 标记和节点／页面／全局整改，不设置意见等级。JSON 与 Markdown 交还同一 feedback 3，先通过后端重读源复核。项目保留具体页面及业务资产；私有离线评审快照固定工具版本，插件更新不覆盖正在使用的快照，原型阶段完整保留。

3.0.3 提供 feedback 4 精简交接：复制／导出仅携带短 `review` 引用、必要标记和用户整改，完整 context 3 保留在本机真实快照中；缺包或来源变化明确拒绝。PM 只把复核为 `current` 的精简结果和当前完整任务包交原 UI Agent，反馈仍不构成需求或视觉批准。旧 feedback 2／3 与各自已生成评审包继续严格只读消费；当前新交付使用下述 live 5，历史 prepare／feedback 4 保持原合同。历史评审包保持各自固定工具和严格读取合同。调用细节见[反馈消费合同](platforms/shared/skills/xy-ui-design/references/prototype-feedback.md)。

3.0.4 修正完整交付入口：Agent／PM 交付前先用可信 `prototype_feedback_cli.py prepare-delivery --root --adapter --pages` 幂等准备受管入口，再用 `open` 显式登记项目、同一 adapter、需求、request-id 与具体页并启动受限评审服务。open 缺准备返回 `preparation_required`，不暗改业务 HTML。正式 `delivery_url` 是当前具体 HTML 的 file URI，`delivery_urls` 列出各页；file 入口提供完整缩放／移动／复位画布及默认收起目录。未准备的裸模板不能作为完整交付。

“进入评审”只用当前页无秘密 binding，以 noopener 新标签导航到同页独立 HTTP 引导；file 壳不创建控制连接、不获取 token。公开 binding 只代表最后登记入口，不证明服务当前 ready；stop 后 file 仍可看稿，需要 Agent 显式重开恢复评审，不新增探测或后台连接。评审进入即批注，无目录、持久模式切换或开发说明；原稿只在独立 file 设计 iframe 执行业务一次，HTTP 评审仍隔离为 allow-scripts。共用相机保留真实 stage/frame 和平台尺寸，不统一为 1120×860。原稿变化保护、CAS 草稿、boot／feedback 5 和历史 feedback 2／3／4 合同保留。

项目只保留具体页、业务资产、固定相对 entry 标签、受管 `.xy-prototype-entry` 链接及精确忽略项，不生成导航 index，不复制业务 HTML 或完整工具。唯一 delivery.html 模板投影到中央经典 shell；通用同 payload 工具只缓存一份。目录按项目登记元数据合并，最多256页；单次open仍只绑定本次已批准需求的最多16页。不同页可绑定不同请求，不扫描未登记页面。未准备／失效显示准确恢复说明，由交付方重跑相同显式 prepare-delivery／open，不猜端口、不冷启动、不虚称服务 ready。具体命令及安全边界见[使用说明](docs/usage.md)和[反馈消费合同](platforms/shared/skills/xy-ui-design/references/prototype-feedback.md)。

各版本的功能验收、原失败与返工、CI、发行、实际项目及本机操作证据统一保留在[发行主题](docs/plans/stable-product-release.md)及其关联计划中。安装和服务就绪不代表指定模型实际运行或业务原型已获视觉批准。

## 验证与支持边界

| 范围 | 判定依据与边界 |
| --- | --- |
| 插件版本与发行 | 工作树版本见 [PLUGIN_VERSION](product/PLUGIN_VERSION)，正式资产与来源见 GitHub Release 和对应 stable 分发记录 |
| 独立组件 | 正式插件配套 Native `0.1.5`，候选版本和获取方式见[随包组件描述](plugins/maintenance/component.json) |
| 原生定义 | Codex 显式打开自动补齐用户级缺失定义，当前项目同名及既有定义保持；文件创建、发现、宿主加载与按名称调用分别核实 |
| 模型与推理 | 使用实际目录和当前模型能力；目录可见、草稿选择及保存均不证明指定模型已实际运行 |
| 本机安装与范围 | 以客户端实际列表和安装回执核对版本、载荷、启用与安装范围；不从源码或缓存存在推断 |
| 官方公开目录与系统 | 自有 Git stable 分发不等同公开目录上架；Windows 继续暂停 |

具体版本的 QA、CI、失败与修复、服务及本机安装记录见[发行主题](docs/plans/stable-product-release.md)和[原生验收记录](docs/archive/plugin-v3-native-acceptance.md)，按各自证据范围读取。

活动任务先收尾再更新插件；当前没有活动任务跨缓存更新的自动资源保留协议。完整发行及本机证据见[正式发行主题](docs/plans/stable-product-release.md)。继续阅读：[使用指南](docs/usage.md)、[开发指南](docs/development.md)、[配置工具说明](docs/agent-configuration.md)。
