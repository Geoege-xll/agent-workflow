# Agent Workflow 3.0 插件候选

3.0 使用三平台官方插件机制分发工作流。当前版本为 `3.0.0-alpha.2`，唯一版本源是 `product/PLUGIN_VERSION`。本页描述开发候选，不表示已发布稳定版、替换本机安装或迁移业务项目。Windows 工作暂停。

## 工作流保持

完整流程以 `product/WORKFLOW.md` 和共用 Skill 为准。Full 保留需求确认，需要原型的 UI 设计变更保留视觉确认；Light 的已有授权、零设计增量的一致性任务和用户明确选择直接开发，继续按原规则执行。安装插件或修改模型不产生业务批准。

主会话是持续接单的 PM，按任务重叠、依赖和真实容量决定并行、复用、追加或等待。新生产任务交给原生子代理，使用 fresh/handoff_only 和当前最小完整任务包，不复制 PM 或兄弟会话。Full 保留请求级唯一独立只读 QA 与原收口顺序。准入 claim 仅代表预留，不能代替原生实例已创建；无法确认的实例不得自动释放并重新派发。

计划维护主题 Markdown，计划 HTML 生成器、专用 vendor 和运行入口已退役。原型设计、原型 HTML、静态原型验收及视觉确认完整保留，历史计划 HTML 仍可作为可选导航。Markdown 交付与历史页面边界见[需求交付规则](../platforms/shared/skills/xy-plan/references/requirements-markdown.md)。

## 插件与配置工具

插件只交付工作流入口、共用产品/Skill/角色及必要 helper。它不要求中央项目登记、TUI 启用、配置服务或 MCP；不向项目复制第二套完整规范，不自动改写旧业务项目和用户客户端设置。

原生 Agent 模型与推理管理是[独立配置工具](agent-configuration.md)，拥有自己的版本和离线包。它使用平台原生标识发现用户级、项目级和插件角色，不限工作流内置角色。网页、脚本与按需开启的 MCP 共用配置核心；服务不创建或调度子代理，保存不表示当前会话已经加载。

## 构建与本地加载

源码按职责单向依赖：

| 路径 | 职责与依赖 |
| --- | --- |
| `product/`、`roles/`、`platforms/shared/skills/` | 工作流唯一权威与共用角色/Skill；不依赖配置服务 |
| `plugins/` | 三宿主清单、发现入口、精确资源及项目引导；复用既有 helper |
| `lib/` | 任务图、持续接单、准入与结算、文档和交付合同；插件路径拒绝旧中央绑定 |
| `packaging/build_plugin.py` | 从白名单装配三宿主离线载荷及真实本地市场，不夹带配置服务 |
| `native_config/` | 独立原生发现、编解码、预览/保存核心及 HTTP/网页/可选 MCP；不导入 `lib`、`manager` 或 AWF 角色枚举 |
| `packaging/build_agent_config.py` | 标准库依赖闭包检查与独立配置 ZIP |
| `tests/`、`scripts/test_workflow.sh` | 行为/合同/真实消费者验证，不进入运行载荷 |

网页、HTTP 和 MCP 只能调用配置核心，不能各自实现一份校验、保存或恢复。模型定义字段、命名 Agent 调用和单次覆盖参数分开表达；平台能力未知时返回诊断，不生成猜测参数。两套产品版本分别来自 `product/PLUGIN_VERSION` 和 `native_config/VERSION`，旧 `product/VERSION` 仅属于保留的 2.x 源码。

构建需要已有 Python 3.11+。源码入口通过选择器运行，不依赖系统默认 `python3` 恰好满足版本：

```bash
bash lib/python_runtime.sh -B -X utf8 packaging/build_plugin.py \
  --host all --output-dir /absolute/new-output-directory --local-source
```

输出包含三个宿主的插件 ZIP、本地载荷及对应的本地市场来源包。每次候选使用新的输出目录。具体官方加载与安装命令、载荷区别及验收限制见[安装说明](../plugins/INSTALL.md)。这里没有尚未发布的远程一键安装地址。

维护者可在 Git 源码树中用 `packaging/build_candidates.py --output-dir <源码树外的新目录>` 统一调用两个独立构建器，生成七包和 `SHA256SUMS`。编排器检查双 alpha 版本、同一源码修订与树摘要、包种类及版本一致性，拒绝源码漂移和覆盖旧输出。自动 PR/push 工作流运行 `current` 并上传这些候选附件，保持只读仓库权限，不创建 tag 或 Release。

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

当前原生观察：Codex CLI 能发现九项插件 Skill，但未发现候选 Hook，默认启动入口仍待验收；Claude Code 能校验并发现 Skill/Agent，但短模型 smoke 未取得有效回答；AGY 仅只读确认了官方插件管理界面，尚未实际加载候选。当前没有三平台原生运行全部通过的结论。

活动任务跨官方插件更新的自动资源保留协议尚未实现，当前 alpha 使用活动任务先收尾再更新的限制。源码与离线包校验不能据此声明自动跨版本恢复通过。

实施范围与证据见[3.0 计划](plans/plugin-v3.md)。旧安装/启用产品面的清理按现有消费者和对应验证分批执行，不自动卸载用户正在使用的 2.x 安装。

## 官方依据

- [Codex 插件](https://developers.openai.com/plugins/build/plugins)及[子代理配置](https://learn.chatgpt.com/docs/agent-configuration/subagents)。
- [Claude Code 插件参考](https://code.claude.com/docs/en/plugins-reference)及[子代理](https://code.claude.com/docs/en/sub-agents)。
- [Antigravity 插件](https://antigravity.google/docs/build-plugins/)及[子代理](https://antigravity.google/docs/subagents/)。
