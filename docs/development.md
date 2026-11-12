# Agent Workflow 3.0 开发手册

当前产品是官方工作流插件与独立原生 Agent 配置工具。插件版本来自 `product/PLUGIN_VERSION`（`3.0.0-alpha.4`），独立工具版本来自 `native_config/VERSION`（`0.1.0-alpha.3`）；两者分别构建和交付。用户入口见[使用手册](usage.md)，架构见[插件说明](plugin-v3.md)，宿主命令见[安装说明](../plugins/INSTALL.md)。

## 权威与职责

| 路径 | 职责 |
| --- | --- |
| `product/WORKFLOW.md` | 工作流唯一产品权威：Light/Full、确认、调度、所有权、QA 与收口 |
| `roles/xy-*.md` | 角色职责、技术边界与权限 |
| `platforms/shared/skills/` | 九个核心 Skill 共用源及按需 references |
| `platforms/codex/`、`platforms/claude/`、`platforms/antigravity/` | 原生宿主资源和平台细则 |
| `plugins/` | 官方清单、入口、精确资源解析、项目引导与维护薄启动器 |
| `plugins/maintenance/skills/` | 独立的 agent-config 维护 Skill，不加入核心业务 Skill 或 Worker 预载 |
| `lib/` | 插件使用的原有任务图、持续接单、准入与结算、文档和交付 helper；以构建白名单确定实际载荷 |
| `templates/` | 项目适配器、主题 Markdown 与通用原型模板 |
| `native_config/` | 独立发现、读取、校验、预览、保存、恢复和诊断核心，以及 HTTP、网页、脚本、可选 MCP |
| `packaging/build_plugin.py` | 三宿主插件及完整本地市场来源包 |
| `packaging/build_agent_config.py` | 独立配置组件 ZIP 与依赖闭包核验 |
| `packaging/build_config_distribution.py` | 根据真实资产下载与校验生成组件发行描述 |
| `packaging/build_candidates.py` | 两个独立构建器的候选编排、七包与摘要 |
| `tests/`、`scripts/test_workflow.sh` | 当前产品行为、合同、原型与候选交付验证 |

产品、角色和 Skill 保持单一权威；使用文档说明入口与边界，不复制完整执行规则。插件不导入配置核心，普通业务不依赖组件、HTTP 或 MCP。配置网页、HTTP、脚本和 MCP 复用同一核心，不各写一套校验或保存。插件缓存只读，原生配置能力按宿主字段与覆盖语义处理，不恢复固定七角色的旧偏好合并机制。

3.0 不以中央登记、CLI/TUI 管理器、Homebrew/npm 或旧项目同步作为当前入口。尚存的历史源码和测试只按真实消费者维护；`product/VERSION` 不表示插件版本，不将旧安装机制重新包装成默认流程。

## 本地构建

使用已有 Python 3.11+；选择器只发现已安装解释器，不安装软件或修改 PATH。每次输出使用源码树外的新目录：

```bash
bash lib/python_runtime.sh -B -X utf8 packaging/build_plugin.py \
  --host all --output-dir /absolute/new-output-directory --local-source
bash lib/python_runtime.sh -B -X utf8 packaging/build_candidates.py \
  --output-dir /absolute/another-new-output-directory
```

插件 ZIP、完整 local-source ZIP 与本地市场目录用途不同；构建本身不安装到用户客户端。完整本地来源目录及官方安装步骤见[INSTALL](../plugins/INSTALL.md)。候选编排核验两产品版本、同一修订与源码摘要、包种类和包摘要，拒绝混包、源码漂移及覆盖旧输出。

独立工具的源码命令、HTTP 生命周期、包结构和恢复资料边界见[原生配置说明](agent-configuration.md)。组件发行描述只登记实际发布且下载校验过的资产，不猜测 URL，不把本地构建成功写成公开稳定发行。

## 项目与原型边界

插件资源从同一安装版本精确解析，helper 在明确的实际项目目录执行；项目 adapter 与插件权威分开。inspect 只读，显式 apply 仅创建缺失的最小 `.awf/project.yaml`。不能写全局或项目指令替代官方发现、Hook 信任和权限审阅。

原型工具必须接收任务已选择的同一 adapter，沿其 `docs.plans` 和 `docs.standards_root` 读取。计划仅维护 Markdown；具体原型 HTML、工作区、静态校验和视觉依赖指纹继续保留。通用工作台见[原型入口](standards/prototype/index.html)，维护规则见[文档与原型指南](plans/workflow-document-lifecycle.md)。

## 验证与证据

当前门禁入口为：

```bash
bash scripts/test_workflow.sh --list current
bash scripts/test_workflow.sh current
```

按影响可选 `plugin`、`native-config`、`prototype` 或 `packaging`，组合节点按实际入口去重。`current` 覆盖两个当前产品、原型及交付合同；`ci` 是 `legacy-ci` 别名，`full` 仍含历史消费者，不用名称推断当前产品验收。纯文档整理以受影响引用、链接、原型静态合同及独立文档复核为准，不重复无关全量回归。

离线包清单、来源 SHA、静态配置和安装发现只证明各自层次。默认 PM、fresh/handoff_only、新 Agent 模型与推理生效、持续接单、同 ID 追加和独立 QA 收口需要对应真实宿主事件。包内 `runtime_verified:false` 不因构建成功自动改为 true。

当前本机精确安装结论：Codex CLI 实际启动通过；Claude 发现通过、默认模型 90 秒无回应，PM 接管未验；AGY 安装通过待登录；App GUI 未验。以前候选的单项原生证据在[验收记录](plans/plugin-v3-native-acceptance.md)中按历史范围保留。Windows 暂停，活动任务跨插件更新自动保留协议尚未实现，更新前先收尾或交接。

## 交付与文档维护

生产职责实例完成必要验证后交请求级唯一独立 QA；返工由原职责作者处理，增量复核沿原 Reviewer。PM 在适用验收后投影当前已交付事实，并按已有授权完成 Git 与发布操作。候选附件、独立组件预发行、插件公开市场、源码合并和本机安装分别记录，不能互相替代。

旧渠道与旧计划执行记录可从 Git 追溯。当前导航不保留退役 TUI、中央运行时或旧同步说明；有效的确认、PM 调度、原型、QA、交付、主题文档与 notes 归属要求已归入使用手册和文档指南，执行权威仍由产品与 Skill 源维护。
