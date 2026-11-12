# Agent Workflow 3.0

面向 Codex、Claude Code 和 Antigravity 的原生多 Agent 工作流，正在升级为官方插件。主会话持续作为 PM 接收需求，按任务重叠、依赖和容量协调原生子代理；保留适用的两步确认、独立 QA 与原有交付流程。

当前是 **3.0.0-alpha.4 开发候选**，版本源为 `product/PLUGIN_VERSION`，不表示已替换业务项目的 2.x 安装。Windows 暂停。已公开资产及是否为预发行以 [GitHub Releases](https://github.com/Geoege-xll/agent-workflow/releases) 为准。

## 两个独立产品

| 产品 | 职责 | 入口 |
| --- | --- | --- |
| Agent Workflow 插件 | PM 工作流、Skill、平台角色与任务 helper | [插件说明](docs/plugin-v3.md)、[本地构建与安装](plugins/INSTALL.md) |
| Native Agent Config | 发现平台原生 Agent，配置模型与推理，网页预览保存 | [配置工具说明](docs/agent-configuration.md) |

插件业务流程无需中央登记、TUI 启用或配置服务。新增显式“模型配置”维护 Skill，按需定位并打开独立配置工具；未调用时不启动服务、不准备组件。配置工具识别用户级、项目级和插件角色，使用稳定原生身份，不限工作流角色；网页、脚本与可选 MCP 共用核心，客户端实际运行状态另行验证。

## 安装插件后打开模型配置

在 Claude Code 使用 `/agent-workflow:agent-config`；Codex 从 `/skills` 或 `$` 选择器选择插件的 `agent-config`；AGY 使用客户端实际发现的插件限定 Skill。省略动作等价 `open`，另有 `status` 和 `doctor`。入口由插件携带，用户无需寻找开发工作树。

首次缺少独立配置组件时先显示准备信息，确认后才获取并校验组件。后续复用本用户已安装的版本和健康服务；自动定位当前平台及明确的项目，没有项目时进入用户级。准备组件不修改模型配置，网页仍先预览、再确认保存。状态与诊断为只读，不安装、不启动服务，也不查询模型目录。

组件是否已发布由包内发行描述及真实资产决定；待发布候选不会猜测下载地址。当前工具仍需已有 Python 3.11+ 和 Bash；配置组件与工作流分别版本化。使用范围和错误状态见[配置工具说明](docs/agent-configuration.md)，实施与验证见[入口计划](docs/plans/agent-config-entry.md)。

## 本地构建候选

需要已有 Python 3.11+ 和 Bash。构建不安装客户端、不改用户配置：

在 Git 源码树中生成完整的七包候选、源码与版本摘要、校验文件：

```bash
bash lib/python_runtime.sh -B -X utf8 packaging/build_candidates.py \
  --output-dir /absolute/new-candidate-output
```

输出叶目录须尚不存在且位于源码树外。两个独立产品也可分别构建：

```bash
# 三宿主插件 ZIP、完整本地来源及市场清单。
bash lib/python_runtime.sh -B -X utf8 packaging/build_plugin.py \
  --host all --output-dir /absolute/new-plugin-output --local-source

# 独立配置工具，不夹带工作流或中央管理器。
bash scripts/python_runtime.sh -B -X utf8 packaging/build_agent_config.py \
  --output-dir /absolute/new-config-output
```

插件官方本地加载命令见[安装说明](plugins/INSTALL.md)。目前没有已验证的远程一键安装地址。插件格式、离线构建及源码检查通过，不等同于三个官方客户端的新会话默认 PM 入口和实际派发均已通过。

开发者仍可从源码按需打开独立配置网页：

```bash
bash scripts/agent_config.sh open --host codex
```

默认读取本机真实原生配置，应用预览会修改所选可写定义。测试隔离参数、只读插件限制、并发冲突、部分失败与重载语义见[配置工具说明](docs/agent-configuration.md)。MCP 仅在主动选择时启动，不是网页或插件的前置。

## 工作流与维护

产品工作流权威在 [product/WORKFLOW.md](product/WORKFLOW.md)，角色职责在 `roles/`，九个共用 Skill 在 `platforms/shared/skills/`。可选维护 Skill 独立位于 `plugins/maintenance/`，不进入角色预载。插件从这些唯一来源装配；项目配置与包内权威资源分开读取，不复制整套规范。计划以 Markdown 交付，计划 HTML 生成器及其专用依赖退役。原型设计、原型 HTML、原型验收和视觉确认保留，已有历史计划页面继续作为可选导航。

实施状态与验收边界见 [3.0 计划](docs/plans/plugin-v3.md)。旧中央运行时、项目启停、TUI 和 Homebrew 产品面分批退役；历史项目资料、计划和已有用户安装不自动删除。仓库尚保留的 2.x 代码不属于 3.0 插件载荷，`product/VERSION` 仍记录其保留源码版本。

PR 与开发分支 push 使用 `current` 验证门禁，并构建候选附件；源码中的自动工作流不创建 tag 或 Release。源码、附件和本机保存验证均不替代官方客户端实际运行验收。

[2.x 使用手册](docs/usage.md)、[2.x 开发与文件迁移记录](docs/development.md)、[2.x Homebrew 说明](docs/homebrew.md) 只供现有安装维护与历史追溯，不是 3.0 安装入口。3.0 当前原生验收尚未完成，因此不触发现有本机和业务项目的替换。
