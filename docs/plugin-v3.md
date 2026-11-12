# Agent Workflow 3.0 插件候选

3.0 使用三平台官方插件机制分发工作流。当前版本为 `3.0.0-alpha.5`，唯一版本源是 `product/PLUGIN_VERSION`。本页描述 alpha 候选与自有 Git 分发，不表示官方公开目录上架、稳定发行或自动迁移业务项目。本机官方客户端的候选安装与原生验收独立记录；Windows 工作暂停。

## 工作流保持

完整流程以 `product/WORKFLOW.md` 和共用 Skill 为准。Full 保留需求确认，需要原型的 UI 设计变更保留视觉确认；Light 的已有授权、零设计增量的一致性任务和用户明确选择直接开发，继续按原规则执行。安装插件或修改模型不产生业务批准。

主会话是持续接单的 PM，按任务重叠、依赖和真实容量决定并行、复用、追加或等待。新生产任务交给原生子代理，使用 fresh/handoff_only 和当前最小完整任务包，不复制 PM 或兄弟会话。Full 保留请求级唯一独立只读 QA 与原收口顺序。准入 claim 仅代表预留，不能代替原生实例已创建；无法确认的实例不得自动释放并重新派发。

计划维护主题 Markdown，计划 HTML 生成器、专用 vendor 和运行入口已退役。原型设计、原型 HTML、静态原型验收及视觉确认完整保留；本仓库的退役计划 HTML 已清理，业务项目历史资料仍按原归属保护。Markdown 交付与历史页面边界见[需求交付规则](../platforms/shared/skills/xy-plan/references/requirements-markdown.md)。

## 插件与配置工具

插件交付工作流入口、共用产品/Skill/角色及必要 helper，并增加可选的“模型配置”维护 Skill 与轻量启动器。业务执行不要求中央项目登记、TUI 启用、配置服务或 MCP；不向项目复制第二套完整规范，不自动改写旧业务项目和用户客户端设置。

原生 Agent 模型与推理管理是[独立配置工具](agent-configuration.md)，拥有自己的版本和离线包。它使用平台原生标识发现用户级、项目级和插件角色，不限工作流内置角色。网页、脚本与按需开启的 MCP 共用配置核心；服务不创建或调度子代理，保存不表示当前会话已经加载。

显式调用插件的 `agent-config [open|status|doctor]` 仅走维护路径，不读取整份 WORKFLOW、不创建业务任务图或派发子代理。入口不会因普通需求里出现命令名而触发；三端主会话的业务分支仍加载完整原权威。组件首次准备需要用户确认，使用固定发行描述和真实包摘要；独立核心、网页和 ZIP 不进入插件。

## 安装与构建

源码按职责单向依赖：

| 路径 | 职责与依赖 |
| --- | --- |
| `product/`、`roles/`、`platforms/shared/skills/` | 工作流唯一权威与共用角色/Skill；不依赖配置服务 |
| `plugins/` | 三宿主清单、发现入口、精确资源、项目引导及白名单维护启动器；不夹带配置核心 |
| `lib/` | 任务图、持续接单、准入与结算、文档和交付合同；插件路径拒绝旧中央绑定 |
| `packaging/build_plugin.py` | 从白名单装配三宿主离线载荷及真实本地市场，不夹带配置服务 |
| `native_config/` | 独立原生发现、编解码、预览/保存核心及 HTTP/网页/可选 MCP；不导入 `lib`、`manager` 或 AWF 角色枚举 |
| `packaging/build_agent_config.py` | 标准库依赖闭包检查与独立配置 ZIP |
| `packaging/build_config_distribution.py` | 独立组件发行描述；已发布模式核验真实下载字节，不编造资产 |
| `tests/`、`scripts/test_workflow.sh` | 行为/合同/真实消费者验证，不进入运行载荷 |

网页、HTTP 和 MCP 只能调用配置核心，不能各自实现一份校验、保存或恢复。模型定义字段、命名 Agent 调用和单次覆盖参数分开表达；平台能力未知时返回诊断，不生成猜测参数。两套产品版本分别来自 `product/PLUGIN_VERSION` 和 `native_config/VERSION`；`product/VERSION` 不表示插件版本。

普通用户通过官方客户端直接安装三个固定 Git 分发分支，无需克隆或本地构建。Codex/Claude 远程市场统一为 `agent-workflow-alpha`，插件名为 `agent-workflow`；AGY 直接安装宿主专属分支的 GitHub tree URL。各端完整命令、登录、Hook 信任、来源检查和更新区别见[安装说明](../plugins/INSTALL.md)。运行 helper 仍需已有 Python 3.11+ 和 Bash。

源码构建只供开发与维护，沿既有 `packaging/build_plugin.py` 与 `build_candidates.py` 唯一构建链生成三宿主插件、本地来源与独立组件七包，详见[开发手册](development.md)。开发市场 `agent-workflow-local` 不与远程市场自动迁移或同时启用。

新手动发布工作流仅从 main 固定源码 SHA，读取同 SHA 成功 `release.yml` 的唯一候选 artifact。独立发布 job 校验来源、候选摘要、版本与干净输入后，将三个宿主来源普通 atomic push 到 `plugins-codex-alpha`、`plugins-claude-alpha`、`plugins-antigravity-alpha`；不另建构建链、不 force 覆盖未知分支，拒绝同版不同载荷，相同候选可幂等重发。发布是自有 Git alpha 渠道，不代替官方公开目录或稳定发行审查。实际发布证据见[远程安装计划](plans/plugin-remote-install.md)。

空项目通过包内 `plugins/project_context.py` 显式创建最小 `.awf/project.yaml`；inspect 本身零写入。已有有效根 `project.yaml` 可复用。项目 adapter 和安装插件中的权威资源分开读取；旧中央绑定或混用来源明确拒绝，不靠伪造 pin 或全局指令文件补入口。

原型验证沿本次明确选择的项目 adapter 读取 `docs.plans` 与 `docs.standards_root`，包括新项目 `.awf/project.yaml`。同一项目存在多个候选时，调用方须传递明确选择；原型工具不自行决定优先级，也不创建第二份配置。

## 验证范围

离线构建、载荷清单、资源来源、脱离源码的新项目引导、持续接单、跨请求准入与结果结算分别验证。它们不能证明客户端新会话默认进入 PM，也不能证明模型实际运行。

两产品的当前回归使用唯一入口：

```bash
bash scripts/test_workflow.sh --list current
bash scripts/test_workflow.sh current
```

`current` 运行两个产品、保留的原型链、验证入口与候选交付合同，是 PR 和开发分支 push 的门禁。可按实际变更单独选择 `plugin`、`native-config`、`prototype` 或 `packaging`；组合时按真实节点去重。`ci` 保留为 `legacy-ci` 的别名，`full` 仍含 2.x 历史消费者，不能把它们的名称当成当前产品验收。PTY 与官方客户端运行另按实际范围记录。

原生验收发现并修复了两项仅靠离线构建无法发现的问题：Codex CLI 0.167.0 对根级 portable 清单漏载 Hook，候选改用单一官方 `.codex-plugin/plugin.json` 格式；AGY CLI 1.5.5 会截断超过 24,000 字节的 Skill 正文，候选改用宿主专属适配说明并在构建时阻断超限，共用工作流正文保持完整。

上一 alpha.4 精确本机候选已完成三端本地安装：Codex CLI 实际启动通过；Claude 插件发现通过，但默认模型在 90 秒预算内未回应，PM 实际接管未验；AGY 安装通过待登录；App GUI 未验。alpha.5 的远程发布与安装发现单独验收，不从来源可用、状态列表或安装回执推断 PM 模型运行。较早 alpha 候选的单项真实模型响应、PM、原生子代理与持续接单证据按[原生验收记录](plans/plugin-v3-native-acceptance.md)的历史范围保留，不扩大为当前三端全部通过。

活动任务跨官方插件更新的自动资源保留协议尚未实现，当前 alpha 使用活动任务先收尾再更新的限制。源码与离线包校验不能据此声明自动跨版本恢复通过。

实施范围与证据见[3.0 计划](plans/plugin-v3.md)。当前导航已移除旧安装、中央运行时、TUI 与旧同步资料；有效工作流要求归入[使用手册](usage.md)和[文档与原型指南](plans/workflow-document-lifecycle.md)。本仓文档清理不自动操作其他用户或业务项目的安装。

## 官方依据

- [Codex 插件](https://developers.openai.com/plugins/build/plugins)及[子代理配置](https://learn.chatgpt.com/docs/agent-configuration/subagents)。
- [Claude Code 插件参考](https://code.claude.com/docs/en/plugins-reference)及[子代理](https://code.claude.com/docs/en/sub-agents)。
- [Antigravity 插件](https://antigravity.google/docs/build-plugins/)及[子代理](https://antigravity.google/docs/subagents/)。
