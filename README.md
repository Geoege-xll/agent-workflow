# Agent Workflow 3.0

面向 Codex、Claude Code 和 Antigravity 的原生多 Agent 工作流。主会话持续作为 PM 接收需求，按任务重叠、依赖和容量协调原生子代理，保留适用的需求确认、原型与视觉确认、独立 QA 和交付流程。

当前版本为 **3.0.0-alpha.4**，已验证官方客户端的本地插件安装，尚未完成官方市场稳定发行。各端运行验收范围见下表。**Windows 暂停**。

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

## 克隆、构建与本地安装

需要已有 Git、Bash、**Python 3.11+** 和所用平台的官方客户端；模型运行还需要完成该客户端登录。构建只生成文件，不安装客户端或修改原生配置。

```bash
git clone https://github.com/Geoege-xll/agent-workflow.git
cd agent-workflow

# 每次构建使用新的持久目录，保留该来源供官方客户端使用。
AWF_PLUGIN_OUTPUT="$HOME/.local/share/agent-workflow/plugin-sources/3.0.0-alpha.4/$(date +%Y%m%d-%H%M%S)"
bash lib/python_runtime.sh -B -X utf8 packaging/build_plugin.py \
  --host all --output-dir "$AWF_PLUGIN_OUTPUT" --local-source
```

输出包含三个宿主的插件 ZIP、完整 `local/` 来源和各自的本地来源 ZIP。以下命令沿用同一终端的 `AWF_PLUGIN_OUTPUT`，按所用宿主选择执行。

### Codex CLI

```bash
codex plugin marketplace add "$AWF_PLUGIN_OUTPUT/local/codex"
codex plugin add agent-workflow@agent-workflow-local
codex plugin list --json
```

安装后在官方 `/hooks` 中审阅并信任当前 SessionStart 定义，再启动新会话；安装或启用本身不授予 Hook 信任。Codex App 的实际 GUI 验证单独进行。

### Claude Code

```bash
claude plugin marketplace add "$AWF_PLUGIN_OUTPUT/local/claude"
claude plugin install agent-workflow@agent-workflow-local --scope user --json
```

安装后启动新会话，检查插件发现与启用状态；用户原生设置仍按客户端规则优先。

### Antigravity CLI

```bash
agy plugin validate --strict "$AWF_PLUGIN_OUTPUT/local/antigravity/agent-workflow"
agy plugin install "$AWF_PLUGIN_OUTPUT/local/antigravity/agent-workflow"
agy plugin enable agent-workflow
agy plugin list --json
```

AGY 使用本地插件目录安装，没有上述本地市场注册步骤。详细载荷区别、官方信任和加载说明见 [INSTALL](plugins/INSTALL.md)。当前不提供未经验证的远程一键安装地址。

## 项目与模型配置

在实际项目目录中开启新会话。新项目通过插件 helper 显式创建最小 `.awf/project.yaml`，已有有效根 `project.yaml` 可复用；不会复制整套规范或覆盖业务文档。项目引导与权威读取方式见 [3.0 插件说明](docs/plugin-v3.md)。

维护入口名为 `agent-config`：Claude 使用 `/agent-workflow:agent-config`；Codex 从 `/skills` 或 `$` 选择器选择插件实际发现的入口；AGY 使用 `/agent-config`，以客户端实际发现项为准。省略动作等价 `open`，另有只读 `status` 和 `doctor`。

首次缺少独立配置组件时，入口先报告版本、来源及诊断，**用户明确同意本次准备后**才获取并校验固定组件。正常业务流程不准备组件或启动配置服务；配置修改先预览、再确认保存。

**插件缓存角色只读**。用户级、项目级对象能否写入，以及模型、推理字段和重载方式，取决于平台的真实支持；保存成功与实际模型运行分别验证。详情见 [配置工具说明](docs/agent-configuration.md)。

## 当前验证范围

| 范围 | 当前状态 |
| --- | --- |
| 本地插件安装 | Codex、Claude Code、AGY 的本地安装已验证 |
| Codex CLI | 新插件启动验证通过，不代表全部业务与模型行为均已验收 |
| Claude Code PM 运行 | 现有默认模型调用在 90 秒内未响应，尚未验收 |
| AGY CLI 模型运行 | 待完成登录后验证 |
| Codex App GUI | 尚未实际验证 |
| 官方市场稳定发行 | 尚未完成；当前为 alpha 本地安装 |

活动任务应先收尾再更新插件；当前 alpha 尚不提供活动任务跨更新的自动资源保留。独立配置组件的发行与工作流插件分别管理，已公开资产以 [GitHub Releases](https://github.com/Geoege-xll/agent-workflow/releases) 为准。

继续阅读：[使用指南](docs/usage.md)、[开发指南](docs/development.md)、[3.0 计划](docs/plans/plugin-v3.md)。构建、静态校验和安装收据不替代官方客户端实际运行证据。
