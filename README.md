# xy-workflow 3.0

面向 Codex、Claude Code 和 Antigravity 的原生多 Agent 工作流。主会话持续作为 PM 接收需求，按任务重叠、依赖和容量协调原生子代理，保留适用的需求确认、原型与视觉确认、独立 QA 和交付流程。

当前源码候选版本为 **xy-workflow 3.0.2** 和独立配置工具 **Native Agent Config 0.1.2**，正在完成生产评审工作台、包外消费验证和正式发行验收；候选尚未发布或安装到本机，组件描述保持 `unpublished`，下载地址和摘要待成功 CI 的真实发行产物确认后填写。现有正式版为 **[xy-workflow 3.0.1](https://github.com/Geoege-xll/agent-workflow/releases/tag/v3.0.1)** 和 **[Native Agent Config 0.1.1](https://github.com/Geoege-xll/agent-workflow/releases/tag/native-agent-config-v0.1.1)**。官方公开目录上架、客户端新会话与指定模型实际采纳分别验收；**Windows 暂停**。

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

Codex／Claude 提供用户级和项目级工作流启停、恢复继承；AGY 保留官方管理说明。0.1.2 候选包含已通过独立验收的第六版工作台：深石墨主题、148px 窄导航、顶部平台与范围上下文、统一选择器，以及就近的恢复继承按钮；保留独立草稿、未知值和失败收据。停用前保存页面给出的独立恢复命令；候选的源码验收不表示本机现有 0.1.1 已升级。

## 精选技能与文档

Grill Me、需求访谈 primitive、Taste、Playwright CLI 随插件固定交付，分别通过 `xy-grill-me`、`xy-grilling`、`xy-taste`、`xy-playwright` 访问。原版资源、许可与薄适配分开维护；不要求另装全局 Skill 或 CLI。原有工作流方法保持，所有角色也可按任务使用宿主实际提供的其他技能。

新增 `xy-web-guidance` 和 `xy-apple-guidance` **可发现、按条件推荐，不进入角色无条件预载**。前者随包提供 GoogleChrome 官方固定版本的完整现代 Web 指导与离线查询，查询需要已有 Node 22+；后者只读使用本机 Xcode 官方 SwiftUI 指导，当前验证边界为观察到的 Xcode 27.x 布局，不再分发 Apple 正文。详见[角色技能主题](docs/plans/role-skill-routing.md)。

计划文档借鉴 Anthropic doc-coauthoring 的分节精修与读者检查，保留五项元信息、六个固定章节及原地更新；显式计划校验不扫描未选文件，不增加访谈、确认或读者 Agent，见[计划规范主题](docs/plans/plan-document-quality.md)。

3.0.2 候选的通用评审工作台提供浏览／批注、固定视口相机、独立 A 标记和节点／页面／全局整改，不设置意见等级。JSON 与 Markdown 交还同一 feedback 3，先通过后端重读源复核。项目保留具体页面及业务资产；私有离线评审快照固定工具版本，插件更新不覆盖正在使用的快照，原型阶段完整保留。

## 当前验证范围

| 范围 | 已有证据与边界 |
| --- | --- |
| 3.0.2／0.1.2 候选 | 当前源码版本已冻结，尚待生产工作台验收、成功 CI 正式产物、发布及本机升级；下列正式发行及本机记录均属已有 3.0.1／0.1.1 |
| 3.0.1／0.1.1 | 文档规范、技能接入和发行合同分别完成唯一独立 QA；两产品为正式非 prerelease 资产 |
| 最终 CI | [Linux／macOS](https://github.com/Geoege-xll/agent-workflow/actions/runs/43549655014)各 628 项，624 通过、4 项既有跳过，七包与摘要通过 |
| 远程分发 | [stable 发布](https://github.com/Geoege-xll/agent-workflow/actions/runs/43550996430)三分支完整文件与权限匹配同一候选，Release 八附件摘要匹配 |
| 本机安装 | Codex／Claude／AGY 均为启用的 3.0.1；2306／2313／2311 个插件文件的字节和执行位匹配 CI 原包 |
| 独立配置组件 | 0.1.1 实际准备成功，三端 doctor 完整性 verified、服务 ready；浏览器打开回执成功。本轮未保存模型设置 |
| 生产网页及原型工具 | 配置工作台已验收字节保持；3.0.2 评审工作台候选待独立验收，不用既有原型或打开回执代替生产运行证据 |
| 新会话与模型采纳 | 历史单项见[原生记录](docs/plans/plugin-v3-native-acceptance.md)；不扩大为 3.0.1 三端指定模型均已实测。Codex App GUI 尚未实际验证 |
| 官方公开目录、Windows | 公开目录尚未上架；Windows 继续暂停 |

活动任务先收尾再更新插件；当前没有活动任务跨缓存更新的自动资源保留协议。完整发行及本机证据见[正式发行主题](docs/plans/stable-product-release.md)。继续阅读：[使用指南](docs/usage.md)、[开发指南](docs/development.md)、[配置工具说明](docs/agent-configuration.md)。
