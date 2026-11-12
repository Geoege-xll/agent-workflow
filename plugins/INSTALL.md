# 安装或加载 3.0 本地插件

当前工作流插件为 `3.0.0-alpha.4` 本地候选，公开市场与稳定发行尚未就绪；Windows 暂停。工作流使用官方插件机制，独立模型配置组件另行交付。日常流程见[使用手册](../docs/usage.md)，载荷边界见[插件说明](PLUGIN.md)。

## 生成完整来源包

仓库中的清单模板是构建输入，不能直接当作完整安装目录。先使用已有 Python 3.11+ 生成候选：

```bash
bash lib/python_runtime.sh -B -X utf8 packaging/build_plugin.py \
  --host all --output-dir /absolute/new-output-directory --local-source
```

每次使用新的输出目录。输出包含确定性插件 ZIP 和 `local/` 下完整的宿主来源目录及实际本地市场清单；各市场只引用自身的 `plugins/agent-workflow`。`*-local-source.zip` 是可分享的完整宿主来源目录，解压到新目录后再交给下列官方命令。单独插件 ZIP 不是市场 ZIP，Codex 安装市场还需要其中的市场清单。

构建不安装到用户环境。构建后的工作流载荷不要求源码 checkout、中央运行时、Node、包管理器或配置服务。下列命令在用户主动执行时修改对应客户端的安装状态；不会自动替换其他用户或业务项目的既有安装。

## Codex CLI

已核对的 CLI 0.167.0 本地市场入口：

```bash
codex plugin marketplace add /absolute/new-output-directory/local/codex
codex plugin add agent-workflow@agent-workflow-local
codex plugin list --json
```

该版本没有已文档化的 `--plugin-dir` 临时加载参数。候选使用单一官方 `.codex-plugin/plugin.json` 清单；实际对照发现根级 portable 格式会漏载打包 Hook，不能同时放两种清单掩盖问题。

安装后进入官方 `/hooks` 管理界面，审阅候选 SessionStart 命令并信任当前定义，再开始新会话。安装或启用不自动授予 Hook 信任，不直接写 trust 记录，不以全局或项目指令文件替代客户端审阅。

## Claude Code

可临时加载完整插件目录：

```bash
claude --plugin-dir /absolute/new-output-directory/local/claude/plugins/agent-workflow
```

需要持久本地安装时：

```bash
claude plugin marketplace add /absolute/new-output-directory/local/claude
claude plugin install agent-workflow@agent-workflow-local --scope user
```

Claude Code 2.1.311 也接受 `--plugin-dir` 传入插件 ZIP；完整目录便于检查来源。安装后开始新会话，客户端才能应用插件主会话默认入口；用户自有默认设置仍保持其优先级。

## Antigravity

使用官方 CLI 的本地目录路径：

```bash
agy plugin validate --strict /absolute/new-output-directory/local/antigravity/agent-workflow
agy plugin install /absolute/new-output-directory/local/antigravity/agent-workflow
agy plugin enable agent-workflow
```

桌面端也提供官方 Marketplace/Installed 管理入口。严格校验包含 Skill 正文 24,000 字节限制，构建器会拒绝超限载荷。安装、登录和模型执行分别判定，不从 strict 或安装回执推断模型派发通过。

## 当前本机结论

当前候选已在本机三端完成本地安装。Codex CLI 新插件实际启动通过；Claude 插件发现通过，默认模型在 90 秒预算内未回应，PM 实际接管未验；AGY 安装通过，后续模型运行待登录；Codex App GUI 未验。较早候选的 CLI 原生实验按其[验收记录](../docs/plans/plugin-v3-native-acceptance.md)单独保留，不扩大为所有宿主与界面均通过。

活动任务跨插件缓存更新的自动资源保留协议尚未实现；更新前先收尾或交接活动任务。插件公开市场与远程一键安装以实际发布记录为准，本地构建命令不代表已发布稳定插件。

## 安装后的模型配置入口

维护 Skill 名为 `agent-config`，省略动作即 open。Claude 使用 `/agent-workflow:agent-config`；Codex 在原生 `/skills` 或 `$` 选择器中选择实际发现的插件 Skill；AGY 当前载荷使用 `/agent-config`，以实际发现项为准。可加 `status` 或 `doctor` 只读检查。

平台由当前插件构建固定，项目来自会话明确的绝对目录；已知唯一项目必须传递，未明确项目才进入用户级。插件物理资源目录与本地项目目录分开，不能用 AGY 项目 ID/name 推导文件路径。

缺少独立组件时先报告准备信息，经用户确认才调用固定准备参数。组件来自已发布且实际核验的独立发行包，安装到用户级版本目录；插件只包含薄入口，不夹带核心、网页、组件 ZIP 或 MCP。显式离线包也必须匹配固定摘要。服务与浏览器分别报告状态，浏览器失败保留 ready 服务及私有打开入口。

status/doctor 不准备组件、创建连接或权限记录，不启动 HTTP、浏览器或模型查询。普通业务无需组件或 MCP；显式维护不读取整份 WORKFLOW、不建业务任务图或派发子代理。插件缓存角色只读，各平台可写原生字段和覆盖范围见[原生配置说明](../docs/agent-configuration.md)。

独立配置工具 `0.1.0-alpha.3` 已作为预发行资产发布；这一事实不代表工作流插件已上架公开市场或成为稳定发行。当前固定组件描述只采用真实下载核验的地址与摘要。
