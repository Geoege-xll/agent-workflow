# Agent Workflow 3.0

面向 Codex、Claude Code 和 Antigravity 的原生多 Agent 工作流。主会话持续作为 PM 接收需求，按任务重叠、依赖和容量协调原生子代理，保留适用的需求确认、原型与视觉确认、独立 QA 和交付流程。

当前源码版本为 **3.0.0-alpha.7**，独立配置组件为 **0.1.0-alpha.4**。本轮恢复本机模型目录、加入用户级／项目级子代理调用偏好，并保留项目工作流启停；源码、受控浏览器和独立 QA 已通过。官方客户端从自有 Git alpha 渠道安装，无需克隆本仓库或本地构建；实际发行以 [GitHub Releases](https://github.com/Geoege-xll/agent-workflow/releases) 和客户端列表为准。公开官方目录、稳定发行与模型运行分别验收，**Windows 暂停**。

## 工作流保持

- PM 持续接单：A 执行期间可以继续讨论 B、C，按真实依赖选择并行、复用、追加或等待。
- 需要原型的 Full UI 设计变更保留两步业务确认：需求确认、原型完成后的视觉确认。Light、非 UI、一致性任务及用户明确选择直接开发，仍按各自原有规则执行。
- 原型设计、可交互 HTML、原型验收与视觉确认保留；计划使用 Markdown 交付。
- 实现交给对应原生子代理，使用独立上下文和明确职责；Full 保留请求级唯一独立只读 QA 与原收口顺序。

完整规则以 [WORKFLOW](product/WORKFLOW.md) 和实际任务适用的 Skill 为准。安装插件或打开模型配置不会产生业务批准。

## 两个独立产品

| 产品 | 职责 | 说明 |
| --- | --- | --- |
| Agent Workflow 插件 | PM 入口、工作流 Skill、角色和任务 helper | [3.0 插件说明](docs/plugin-v3.md) |
| Native Agent Config | 读取本机模型目录，管理原生定义、子代理调用偏好和工作流启停 | [配置工具说明](docs/agent-configuration.md) |

工作流通过各官方客户端安装到插件缓存，无需中央登记、配置服务或 MCP。项目使用轻量 adapter，业务文档继续保留在项目内。

## 远程安装 alpha 插件

需要已有对应平台官方客户端、**Python 3.11+** 和 **Bash**；模型运行还需要完成客户端登录。helper 通过包内选择器发现现有解释器，不自动安装依赖或更改 PATH。按所用平台执行以下命令。

### Codex CLI

```bash
codex plugin marketplace add https://github.com/Geoege-xll/agent-workflow.git --ref plugins-codex-alpha
codex plugin add agent-workflow@agent-workflow-alpha
codex plugin list --json
```

安装后在官方 `/hooks` 中审阅并信任当前 SessionStart 定义，再开始新会话。安装或启用不自动授予 Hook 信任；Codex App GUI 的运行验证单独判定。

### Claude Code

```bash
claude plugin marketplace add 'https://github.com/Geoege-xll/agent-workflow.git#plugins-claude-alpha'
claude plugin install agent-workflow@agent-workflow-alpha --scope user
claude plugin list --json
```

安装后开始新会话；用户自有默认设置仍按客户端规则优先。

### Antigravity CLI

```bash
agy plugin install https://github.com/Geoege-xll/agent-workflow/tree/plugins-antigravity-alpha
agy plugin enable agent-workflow
agy plugin list --json
```

AGY 使用 GitHub `tree/分支` 地址，不能替换为 Claude 的 `#分支` 写法。

三个分发分支只承载已校验的宿主构建产物。Codex 和 Claude 的市场名均为 `agent-workflow-alpha`，插件名为 `agent-workflow`；旧开发来源 `agent-workflow-local` 不会自动迁移。已有本地测试版本时先在官方客户端确认来源、范围与启用状态，再停用旧候选或按其官方卸载流程移除，避免两个同名候选同时启用。

安装后的状态检查、更新与退出渠道见 [INSTALL](plugins/INSTALL.md)。源码构建仅供开发、离线候选和维护验证，见[开发指南](docs/development.md)。自有 Git 市场不等于官方公开目录审查或稳定发行。

## 项目与模型配置

在实际项目目录中开启新会话。新项目通过插件 helper 显式创建最小 `.awf/project.yaml`，已有有效根 `project.yaml` 可复用；不会复制整套规范或覆盖业务文档。项目引导与权威读取方式见 [3.0 插件说明](docs/plugin-v3.md)。

维护入口名为 `agent-config`：Claude 使用 `/agent-workflow:agent-config`；Codex 从 `/skills` 或 `$` 选择器选择插件实际发现的入口；AGY 使用 `/agent-config`，以客户端实际发现项为准。省略动作等价 `open`，另有只读 `status` 和 `doctor`。

首次缺少独立配置组件时，入口先报告版本、来源及诊断，**用户明确同意本次准备后**才获取并校验固定组件。正常业务流程不准备组件或启动配置服务；配置修改先预览、再确认保存。

配置页默认进入“调用偏好”：即使 Codex 没有自定义 Agent 文件、Claude 只有插件角色，也可设置通用默认和已发现 Agent 的偏好。用户级与当前项目分别保存，PM 在后续派发前通过同源只读解析器读取；无需常驻 HTTP 或 MCP。**插件缓存角色保持只读**，原生定义文件编辑使用独立模式，保存成功与实际模型运行分别验证。

模型目录来自对应本机客户端或有效配置：Codex 使用原生 `model/list`，Claude 读取本机菜单、当前模型和别名映射，AGY 读取 `agy models`。推理选项按当前模型处理；AGY 会话模型 ID 与子代理 tier、Claude 完整模型 ID 与调用别名明确区分，不把未证实的能力当作可用。详情见[配置工具说明](docs/agent-configuration.md)和[本轮计划](docs/plans/native-model-preferences.md)。

独立配置工具 `0.1.0-alpha.4` 同时提供 Codex／Claude 的工作流用户级与项目级启停、恢复继承，AGY 启停保留官方管理说明。停用插件前保存页面给出的独立恢复命令；已有会话和正在运行的 Agent 不因保存而被改写。

## 当前验证范围

| 范围 | 当前状态 |
| --- | --- |
| alpha.7／组件 alpha.4 源码 | 本机目录、偏好继承与最终态校验、预览保存、只读派发接入、独立包已通过作者验证和同一独立 QA |
| 生产配置网页 | 实际 Chromium 覆盖空清单、只读插件角色、保存回读、来源变化、三草稿隔离、键盘与窄屏；使用隔离配置 |
| 远程渠道 | 三个 Git 来源由固定 SHA 的成功 CI 候选发布；安装发现不代表模型运行 |
| alpha.6 Codex CLI | 默认新会话加载工作流、显式维护入口隔离已实际验证；新版本指定子代理模型仍须单独核实 |
| alpha.6 Claude Code | 实际新会话选中 PM；用户会话中前台规划与排队追问正常，未覆盖后台 A/B 并行派发 |
| AGY CLI 模型运行 | 本机模型目录可读取，指定子代理模型与调用能力仍按真实接口分别验证 |
| Codex App GUI | 尚未实际验证 |
| 官方公开目录与稳定发行 | 尚未完成；自有 Git alpha 分发不代替上架审查 |

活动任务应先收尾再更新插件；当前 alpha 尚不提供活动任务跨更新的自动资源保留。独立配置组件的发行与工作流插件分别管理，已公开资产以 [GitHub Releases](https://github.com/Geoege-xll/agent-workflow/releases) 为准。

继续阅读：[使用指南](docs/usage.md)、[开发指南](docs/development.md)、[远程安装计划](docs/plans/plugin-remote-install.md)、[3.0 计划](docs/plans/plugin-v3.md)。构建、静态校验和安装收据不替代官方客户端实际运行证据。
