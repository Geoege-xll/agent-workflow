# Agent Workflow 3.0

面向 Codex、Claude Code 和 Antigravity 的原生多 Agent 工作流。主会话持续作为 PM 接收需求，按任务重叠、依赖和容量协调原生子代理，保留适用的需求确认、原型与视觉确认、独立 QA 和交付流程。

当前源码候选版本为 **3.0.0-alpha.6**，已完成本轮工作流闭环修复及独立代码验收，尚未发布；已发布的远程安装版本仍为 **3.0.0-alpha.5**。现有自有 Git 远程 alpha 分发渠道由官方客户端直接安装，无需克隆本仓库或本地构建；公开官方目录与稳定发行仍分别待验。远程发布和安装发现按实际交付记录判断，模型运行范围见下表。**Windows 暂停**。

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
| Native Agent Config | 发现原生 Agent，预览和保存受支持的模型、推理设置 | [配置工具说明](docs/agent-configuration.md) |

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

**插件缓存角色只读**。用户级、项目级对象能否写入，以及模型、推理字段和重载方式，取决于平台的真实支持；保存成功与实际模型运行分别验证。详情见 [配置工具说明](docs/agent-configuration.md)。

## 当前验证范围

| 范围 | 当前状态 |
| --- | --- |
| alpha.4 本地安装 | Codex、Claude Code、AGY 已验证；属于上一候选记录 |
| alpha.5 远程渠道 | 三个 Git 来源已发布；安装发现与文件校验结果见[原生安装 CI](https://github.com/Geoege-xll/agent-workflow/actions/workflows/native-install-smoke.yml)，不代表模型运行 |
| alpha.4 Codex CLI | 新插件启动验证通过，不代表全部业务与模型行为均已验收 |
| alpha.4 Claude Code PM 运行 | 现有默认模型调用在 90 秒内未响应，尚未验收 |
| AGY CLI 模型运行（沿用未验项） | 待完成登录后验证 |
| Codex App GUI | 尚未实际验证 |
| 官方公开目录与稳定发行 | 尚未完成；自有 Git alpha 分发不代替上架审查 |

活动任务应先收尾再更新插件；当前 alpha 尚不提供活动任务跨更新的自动资源保留。独立配置组件的发行与工作流插件分别管理，已公开资产以 [GitHub Releases](https://github.com/Geoege-xll/agent-workflow/releases) 为准。

继续阅读：[使用指南](docs/usage.md)、[开发指南](docs/development.md)、[远程安装计划](docs/plans/plugin-remote-install.md)、[3.0 计划](docs/plans/plugin-v3.md)。构建、静态校验和安装收据不替代官方客户端实际运行证据。
