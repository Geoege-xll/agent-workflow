# Agent Workflow 3.0 开发手册

当前产品是官方工作流插件与独立原生 Agent 配置工具。已正式发布 `xy-workflow 3.0.1` 与 `Native Agent Config 0.1.1`，版本分别来自 `product/PLUGIN_VERSION` 和 `native_config/VERSION`。文档规范、角色技能与正式发行合同分别完成唯一独立 QA；最终 CI、三 stable 来源和本机三端载荷均已核验，组件完整性及服务 ready。真实来源与边界见[发行主题](plans/stable-product-release.md)，不从安装推断新会话或模型采纳。用户入口见[使用手册](usage.md)，架构见[插件说明](plugin-v3.md)，宿主命令见[安装说明](../plugins/INSTALL.md)。

## 权威与职责

| 路径 | 职责 |
| --- | --- |
| `product/WORKFLOW.md` | 工作流唯一产品权威：Light/Full、确认、调度、所有权、QA 与收口 |
| `roles/xy-*.md` | 角色职责、技术边界与权限 |
| `platforms/shared/skills/` | 内部公共 Skill、条件适配与按需 references |
| `product/command_identity.json`、`product/command_identity.py` | 公开命名的唯一数据定义及标准库校验；两个独立产品按原字节交付 |
| `third_party/selected-skills.lock.json`、`third_party/selected-skills/` | 精选上游固定来源、完整文件与许可清单及原版资源；不混入本地流程修改 |
| `lib/skills/selected_skills.py` | 精选资源完整性、安全读取和候选归档校验的公共实现 |
| `lib/skills/playwright_runtime.py` | 固定 Playwright CLI、Node／浏览器环境与命名会话执行；不拥有 PM 流程 |
| `platforms/codex/`、`platforms/claude/`、`platforms/antigravity/` | 原生宿主资源和平台细则 |
| `plugins/` | 官方清单、入口、精确资源解析、项目引导与维护薄启动器 |
| `plugins/maintenance/skills/` | 独立的 xy-config 维护 Skill，不加入核心业务 Skill 或 Worker 预载 |
| `lib/` | 插件使用的原有任务图、持续接单、准入与结算、文档和交付 helper；以构建白名单确定实际载荷 |
| `templates/` | 项目适配器、主题 Markdown 与通用原型模板 |
| `native_config/` | 独立发现、读取、校验、预览、保存、恢复和诊断核心，以及 HTTP、网页、脚本、可选 MCP |
| `packaging/build_plugin.py` | 三宿主插件及完整本地市场来源包 |
| `packaging/build_agent_config.py` | 独立配置组件 ZIP 与依赖闭包核验 |
| `packaging/build_config_distribution.py` | 根据真实资产下载与校验生成组件发行描述 |
| `packaging/build_candidates.py` | 两个独立构建器的候选编排、七包与摘要 |
| `packaging/publish_plugin_sources.py` | 校验已构建候选并投影所选 stable／alpha 的三宿主 Git 分支，不另建插件构建链 |
| `.github/workflows/publish-plugins.yml` | 仅 main 手动触发，固定来源 SHA 并发布同 SHA 成功 CI 的候选 |
| `tests/`、`scripts/test_workflow.sh` | 当前产品行为、合同、原型与候选交付验证 |

产品、角色和 Skill 保持单一权威；使用文档说明入口与边界，不复制完整执行规则。插件不导入配置服务，普通业务不依赖组件、HTTP 或 MCP。配置网页、HTTP、脚本和 MCP 复用同一核心，不各写一套校验或保存。插件缓存只读，原生完整定义的覆盖语义不变。

调用偏好的唯一只读合同源是 `native_config/preference_contract.py`，纯标准库且不导入服务。插件构建逐字节投影为 `plugins/dispatch_preferences.py` 并记录来源摘要，`source_pack.py dispatch-preferences` 校验出处后调用；源包开发运行原文件。两边共用固定宿主根、版本化格式与字段解析，不手写第二份验证逻辑，也不恢复只支持固定七角色的旧管理器。目录发现、偏好预览和保存仍由独立核心持有，UI 不直接写文件。

3.0 不以中央登记、CLI/TUI 管理器、Homebrew/npm 或旧项目同步作为当前入口。尚存的历史源码和测试只按真实消费者维护；`product/VERSION` 不表示插件版本，不将旧安装机制重新包装成默认流程。

## 本地构建

普通用户优先使用[远程安装](../plugins/INSTALL.md)；本节仅供源码开发、离线候选和发布维护，不作为普通用户安装前置。源码开发需要 Git、已有 Python 3.11+ 和 Bash。

使用已有 Python 3.11+；选择器只发现已安装解释器，不安装软件或修改 PATH。每次输出使用源码树外的新目录：

```bash
bash lib/python_runtime.sh -B -X utf8 packaging/build_plugin.py \
  --host all --output-dir /absolute/new-output-directory --local-source
bash lib/python_runtime.sh -B -X utf8 packaging/build_candidates.py \
  --output-dir /absolute/another-new-output-directory
```

插件 ZIP、完整 local-source ZIP 与本地市场目录用途不同；构建本身不安装到用户客户端。Codex/Claude 开发本地市场名为 `xy-workflow-local`，正式远程市场为 `xy-workflow`，历史 alpha 市场为 `xy-workflow-alpha`；来源变更通过官方客户端明确执行，不能当作自动迁移。候选编排核验两产品版本、同一修订与源码摘要、包种类和包摘要，拒绝混包、源码漂移及覆盖旧输出。

开发候选可按实际宿主本地加载：

```bash
codex plugin marketplace add /absolute/new-output-directory/local/codex
codex plugin add xy-workflow@xy-workflow-local
claude --plugin-dir /absolute/new-output-directory/local/claude/plugins/xy-workflow
agy plugin validate --strict /absolute/new-output-directory/local/antigravity/xy-workflow
agy plugin install /absolute/new-output-directory/local/antigravity/xy-workflow
```

这些官方命令在执行时会改变对应客户端状态，构建本身不安装。保留来源目录，不将临时测试安装误报为用户全局迁移。Codex Hook 仍须官方审阅与信任；本地和远程同名候选避免同时启用。

## 发行分发维护

唯一构建器继续生成三宿主 plugin/local-source 六包及独立配置一包。手动发布工作流只允许 main，固定触发时的 `github.sha`，从成功的 `release.yml` push/main 运行中读取同 SHA 的唯一候选 artifact；不是再从发布分支另行构建。

发布器校验候选来源、摘要、版本与干净输入，向固定仓库 `Geoege-xll/agent-workflow` 的 所选渠道的 `plugins-codex-*`、`plugins-claude-*`、`plugins-antigravity-*` 投影对应宿主完整来源。正式渠道市场名为 `xy-workflow`；历史 alpha 市场为 `xy-workflow-alpha`，开发本地市场为 `xy-workflow-local`，均取自唯一命令身份声明。拒绝未知分支和同版不同载荷；相同输入重发幂等，三个分支通过普通 Git atomic push 一并发布，不 force 覆盖未知历史。

CI 验证作业与发布作业分离，只有专用发布 job 获得写权限。正式 Git 分发与官方公开目录审查分别判断，渠道名不授予额外权限。实际分支与安装发现应在发布后分别核对，并与源码 SHA、artifact 和载荷摘要对应；设计与验收见[远程安装计划](plans/plugin-remote-install.md)。

独立工具的源码命令、HTTP 生命周期、包结构和恢复资料边界见[原生配置说明](agent-configuration.md)。组件发行描述只登记实际发布且下载校验过的资产，不猜测 URL，不把本地构建成功写成公开稳定发行。

## 项目与原型边界

插件资源从同一安装版本精确解析，helper 在明确的实际项目目录执行；项目 adapter 与插件权威分开。inspect 只读，显式 apply 仅创建缺失的最小 `.awf/project.yaml`。不能写全局或项目指令替代官方发现、Hook 信任和权限审阅。

原型工具必须接收任务已选择的同一 adapter，沿其 `docs.plans` 和 `docs.standards_root` 读取。计划仅维护 Markdown；具体原型 HTML、静态校验和视觉依赖指纹继续保留。项目只维护具体页、契约和业务资产；新项目只初始化可维护的 `prototype.css`，不复制通用查看器。本项目既有[原型入口](standards/prototype/index.html)继续保留为导航，当前通用评审工具通过 prepare 生成私有快照，不把项目旧壳当作最新工具。维护规则见[文档与原型指南](plans/workflow-document-lifecycle.md)。

反馈入口复用 `lib/documents` 与 `templates/prototype` 的现有白名单打包，不增加构建链。`prototype_review.py` 负责封闭 schema 2、明确依赖快照、工具摘要和有界迁移；`prototype_feedback.py` 负责反馈项及项目当前源校验，CLI 只路由。三宿主包中的 `source_pack.py resource templates/prototype/index.html` 解析真实物理模板；`helper --project <project> lib/documents/prototype_feedback_cli.py prepare --root <project> --adapter <selected-adapter> --plan <project-relative-Markdown> --request-id <id>` 返回私有不可变快照的 `review_url`，`validate --root <project> --adapter <selected-adapter> --input <explicit-feedback-file>` 只读复核当前源和原包后输出 `changes`。工具代码随插件，快照独立于插件缓存保留；业务源不注入桥。接口和边界见[反馈消费合同](../platforms/shared/skills/xy-ui-design/references/prototype-feedback.md)，不把 JSON 输入当需求或批准。

## 验证与证据

指定计划可独立做只读机械校验，无需 `PROJECT.md` 或项目配置；路径相对实际项目根，也可使用根内绝对路径：

```bash
bash lib/python_runtime.sh -B -X utf8 lib/validate_project_docs.py --root /path/to/project --plan docs/plans/topic.md --plan docs/plans/another.md
```

该模式只读取显式选中的计划，检查五项元信息、Full 六节的标题与顺序，以及本地链接的安全路径和存在性；代码围栏示例不参与合同识别，链接目标不读取正文，远程链接不请求。Light 无基线计划仍可简化。校验不会扫描未选计划、创建配置或修改文档。通过仅代表机械结构成立，内容是否去重、前后一致、能回答读者问题，仍由 PM 和适用的独立 QA 判断；文档、勾选与校验成功不能代替用户批准或验收。原两位置参数入口保留 PROJECT 基线与规范校验及历史计划识别行为。

当前门禁入口为：

```bash
bash scripts/test_workflow.sh --list current
bash scripts/test_workflow.sh current
```

`prototype` 及继承它的 `current` 包含 `prototype_workspace_runtime`、`prototype_feedback` 与 `prototype_review` 的真实模块，runner 隔离样本和独立 expected 同步维护。runtime 用例消费生产模板，不是业务原型自动化授权。三宿主独立包的 prepare／validate 集成由 `plugin_delivery` 覆盖；浏览器、CLI、静态证据与宿主模型运行分层报告。

按影响可选 `plugin`、`native-config`、`prototype` 或 `packaging`，组合节点按实际入口去重。`current` 覆盖两个当前产品、原型及交付合同；`ci` 是 `legacy-ci` 别名，`full` 仍含历史消费者，不用名称推断当前产品验收。纯文档整理以受影响引用、链接、原型静态合同及独立文档复核为准，不重复无关全量回归。

离线包清单、来源 SHA、静态配置和安装发现只证明各自层次。默认 PM、fresh/handoff_only、新 Agent 模型与推理生效、持续接单、同 ID 追加和独立 QA 收口需要对应真实宿主事件。包内 `runtime_verified:false` 不因构建成功自动改为 true。

历史工作流插件 alpha.4 的本机精确安装结论为：Codex CLI 实际启动通过；Claude 发现通过、默认模型 90 秒无回应，PM 接管未验；AGY 安装通过待登录；App GUI 未验。历史插件 alpha.5 的远程发布和安装发现单独记录，这些插件序号不等同独立配置组件的同名 alpha 序号，也不证明当前正式候选已发布或实际运行通过。以前候选的单项原生证据在[验收记录](plans/plugin-v3-native-acceptance.md)中按历史范围保留。Windows 暂停，活动任务跨插件更新自动保留协议尚未实现，更新前先收尾或交接。

## 交付与文档维护

生产职责实例完成必要验证后交请求级唯一独立 QA；返工由原职责作者处理，增量复核沿原 Reviewer。PM 在适用验收后投影当前已交付事实，并按已有授权完成 Git 与发布操作。候选附件、独立组件预发行、插件公开市场、源码合并和本机安装分别记录，不能互相替代。

旧渠道与旧计划执行记录可从 Git 追溯。当前导航不保留退役 TUI、中央运行时或旧同步说明；有效的确认、PM 调度、原型、QA、交付、主题文档与 notes 归属要求已归入使用手册和文档指南，执行权威仍由产品与 Skill 源维护。

命令身份统一由 `product/command_identity.json` 管理，加载器严格拒绝未知字段、修改身份、重复键或不安全来源；两个独立产品原样投影并记录摘要。配置业务不导入工作流服务，构建器只负责封闭标准库载荷与同源投影。组件状态以真实 `plugins/maintenance/component.json` 为准；正式候选先从实际独立 ZIP 生成空 URL 的 unpublished 描述，经成功 CI、真实发布与下载核验后才更新为 published。
