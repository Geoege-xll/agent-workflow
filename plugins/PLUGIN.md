# xy-workflow 3.1.2

本包为 `xy-workflow 3.1.2`，配套 Native Agent Config `0.1.8`。版本来自 `product/PLUGIN_VERSION` 和 `native_config/VERSION`，维护入口根据包内组件描述校验下载来源和摘要。正式安装使用 Git stable 来源和 GitHub Release，实际安装范围与版本以客户端回执为准。Windows 分发暂停。 [安装说明](INSTALL.md) · [发行记录](https://github.com/Geoege-xll/agent-workflow/blob/main/docs/plans/stable-product-release.md) · [使用手册](https://github.com/Geoege-xll/agent-workflow/blob/main/docs/usage.md)

## 载荷与职责

插件由官方宿主负责安装、启用、停用和更新。业务执行无需中央运行时、项目登记、TUI、Homebrew/npm 或配置服务，不向业务项目复制第二套完整规范。普通用户无需克隆工作流源码或本地构建；helper 运行仍需已有 Python 3.11+ 和 Bash。离线构建使用 Python 3.11+ 标准库；通过 `lib/python_runtime.sh` 选择已有解释器，不安装软件或修改 PATH。

载荷保留 `product/`、`roles/`、`platforms/shared/skills/` 权威及必要 helper 的白名单依赖。内置核心 Skill 保留共用前置元数据、完整正文和原字节 references。每个入口使用相对链接定位同一物理插件包的宿主资源说明。当前实例可复用同一来源、同一版本的完整说明；独立启动或说明缺失时补读，来源或版本变化时重新读取。原生角色提示词保持完整角色正文。`sources.json` 记录来源、投影、包摘要与业务确认/执行合同检查结果；摘要证明内容一致性，不能证明宿主已经派发。

计划交付只维护 Markdown，已退役生成器及专用 renderer 不入包；两档交付按实际委托确认目标、实质方案及适用原型，相关设计或实施依赖先确定的行为；原型 HTML、静态验收、依赖指纹和视觉确认继续有效。完整工作流规则由产品、角色、共用 Skill 维护。

精选第三方 Skill 包括 Matt Pocock 的 `grill-me` 与 `grilling`、Paul Bakaus 的 Impeccable、官方 Playwright
CLI/Skill，以及官方 `agent-desktop`。前四个发现入口为无 hooks 薄适配 `xy-grill-me`、`xy-grilling`、
`xy-impeccable`、`xy-playwright`。Impeccable 的正式分发 Markdown、LICENSE 与 NOTICE 随包保存在
非发现目录，供设计角色按需离线读取。`agent-desktop` 按上游名称与原文直接发现，首版随包提供 macOS `arm64` 和 `x86_64`
的 v1.3.1 原版 CLI 及同目录 helper。

锁 `third_party/selected-skills.lock.json` 记录 `third_party/selected-skills/` 原版资源的固定来源、提交或
发行版本、逐文件大小与摘要，随包保留许可证、引用、脚本、资产及署名元数据。

构建器把锁定的 `grilling` 和 `grill-me` 原文从同一批校验过的字节投影到各自的原生 Skill，
并在 `sources.json` 记录原文依赖。两个小入口随宿主调用直接交付全文，源码只维护 vendor 中的一份原版。
PM 只在仍有影响判级依据的实质缺口时通过 `xy-grilling` 完整加载原版。`xy-grill-me` 只接受当前用户显式调用，原版转调解析为同包
qualified `xy-grilling` 或读取同包 canonical，不能误调未知全局同名技能。`grill_result` 属于
xy-workflow 的 PM 适配。`xy-uiux` 固定绑定 `xy-ui-design`。交付具体 HTML 原型时必须加载并执行
`xy-prototype-verify`，仅维护设计规范时按文档验收。`xy-impeccable` 由当前设计需求决定是否选用。
Claude 子代理的 skills 声明仅描述其预载配置。

UI UX Pro Max 的 MIT 原版检索引擎、五个专题数据表和上游引用记录在非发现目录随包交付。
有具体未决设计问题时，`xy-uiux` 通过同一物理插件的 `source_pack.py selected-skills query` 显式检索。沿用项目规范与 Impeccable 主设计方法。

Playwright CLI采用锁定的官方发布包，不依赖用户全局命令或npm/npx临时下载；三个原包与
原版Skill完整随包，Node仍为运行前提，浏览器复用官方匹配缓存、按已有任务授权和宿主权限准备。
生产Web优先复用项目测试，补充交互首选 `xy-playwright`；其它浏览器需具体理由，电脑操控需
桌面能力。QA仅按实际Web审查面加载，不普遍预载或扩大权限。DOM snapshot不证明视觉通过。

所有 Agent（包括 PM、设计、计划与唯一 QA）都按当前任务、实际技术栈及职责按需选择 Skill，
统一规则位于物理插件根的 `platforms/shared/skills/xy-workflow/references/skill-selection.md`，包括
Impeccable 选中后的正文和参考分段读取和 `xy-desktop`、`xy-qa` 的桌面取证与权限边界。
内置入口是候选推荐，不强制选用；宿主实际提供的用户级、项目级及其它插件 Skill 也可按需使用。
先按名称与说明缩小范围，完整读取选中 Skill 入口。引用按该分支指定的章节或条款及其必要依赖读取；明确要求全文的读完整份。不扫描个人目录或全量预载。
任务包的 `required_skills` 只记当前任务真正不可缺的依赖，不因内置推荐自动加入；缺失会阻断对应
阶段。同名来源歧义和约束冲突交 PM 协调。上级明确要求仍遵守，选中 Skill 后完整读取并遵守其
适用指令；未选用的 vendor Skill 中的 mandatory 字样不构成强制选择理由。

`xy-web-guidance` 是 Web API、兼容性或实现方案存在实际风险／缺口时的推荐候选，不因存在
HTML/CSS/客户端 JavaScript 文件就必须查询；已有可靠项目方案或纯业务逻辑可无需选用。
选中后按适用指令查询随包固定版本的现代 Web 指导，保留项目浏览器兼容策略与项目测试／Playwright
验证优先级。
运行查询需要已有 Node 22+；固定现代 Web 指导的 `search`、`retrieve`、`list` 使用随包本地数据，
不调用 npm、不自动联网或安装。`xy-apple-guidance` 是 SwiftUI 平台/API、状态、布局或兼容性存在
知识缺口时的推荐候选，不因存在 SwiftUI 文件就必须加载。选中后优先只读解析本机 Apple 官方
Specialist，新 API／迁移才读 What's New；本机资源不随插件复制，缺失如实
报告，不自动安装或用第三方镜像补齐。用户实际提供的并发、SwiftData、性能等 Skill 可按需补充，
不改变语言模式、UI 框架或最低系统要求。读取成功、CLI 查询成功与宿主模型实际采纳分别报告，
不能代替构建、运行、签名或唯一 QA。任何 Skill 都不扩大权限、路径、网络或原型自动化授权。

`xy-ui-design` 的组件一致性与关键流程规则适用于 Web、桌面、原生 App 和小程序。`xy-mobile-ui` 为 iOS、iPadOS、Android 和微信小程序提供按需平台指导。设计、开发与 QA 根据运行端选读安全区、键盘、导航、状态生命周期和无障碍规则，并沿用现有交接记录原型行为与实际运行证据。

另有独立 `xy-config` 维护 Skill、固定薄启动器和组件发行描述，不计入 CORE_SKILLS 或 Worker 预载，不注入业务 envelope。仅用户在当前主会话显式调用时执行；普通需求中出现命令名称、实现或评审配置功能仍进入完整业务流程。维护动作不读整份 WORKFLOW、不建图、不派代理，也不产生业务批准。

独立配置核心位于 `native_config/`，由自身构建器交付，插件不导入服务、不包含网页、独立 ZIP 或模型 MCP。首次组件准备需要明确确认并校验真实发行包；维护失败不阻断普通工作流。插件缓存角色只读，原生文件与调用偏好分开管理。

Codex 七角色的完整定义由同源角色生成到非发现目录 `native-agent-templates/codex`。通过完整插件显式执行 `xy-config open` 时，配套组件按已校验模板自动补齐用户级缺失原生 Agent，再回读并打开控制台；当前项目已有同名定义时跳过，不写项目文件。已有定义及模型、推理字段保持，重复打开与升级不重写。独立组件未指定 `--preparation-source` 时不自动补齐；网页不提供手动准备入口。插件安装不创建这些文件，升级也不自动更新或删除已准备定义，来源版本变化后，显式调用 `xy-config rebind` 查看候选角色；确认本次预览后才会写入用户级受管定义。用户级完整定义不等于统一模型默认，文件创建和发现不证明宿主按名称调用或指定模型已生效。新版启动器的 `--preparation-source` 仅与固定描述绑定的组件配套，不沿用旧组件。

Agent 控制台与原型交付／评审外壳共同使用限定在 `.sg-scope` 的 SolidGlass 静态主题，完整 MIT 许可随包保留，业务原稿保持独立。原型普通滚轮由业务页面滚动；鼠标平移使用 Space 拖动或中键，Ctrl/Cmd 滚轮缩放。响应式长页保持可用设计视口，不把 iframe 撑成整页高度。

唯一纯标准库只读合同 `native_config/preference_contract.py` 逐字节投影为插件的 `plugins/dispatch_preferences.py`，记录来源及投影摘要。PM 在派发前通过 `source_pack.py dispatch-preferences` 读取用户／项目偏好，无偏好时沿宿主默认；有偏好时只映射实际原生工具支持的字段，异常不静默回退。它不启动或准备组件、HTTP/MCP，不写设置，不改变业务确认、角色权限或当前主会话模型；维护 Skill 分支不进入该业务步骤。

当前公开命名由 `product/command_identity.json` 唯一维护；远程分发与组件可用性以真实 Release 资产和
`plugins/maintenance/component.json` 为准，本机是否已切换以客户端列表和实际安装回执为准；先完成当前活动任务。

## 正式来源与历史 alpha

三个正式分发分支为 `plugins-codex-stable`、`plugins-claude-stable`、`plugins-antigravity-stable`，Codex/Claude 的正式远程市场名为 `xy-workflow`，插件名为 `xy-workflow`。历史 `plugins-codex-alpha`、`plugins-claude-alpha`、`plugins-antigravity-alpha` 与 `xy-workflow-alpha` 市场保留审计；开发本地来源仍为 `xy-workflow-local`。完整官方命令见 [INSTALL](INSTALL.md)，不要交换 Codex 的 `--ref`、Claude 的 `#分支` 和 AGY 的 GitHub `tree/分支` 语法。

载荷来自同一成功 CI 的固定源码 SHA 与校验候选，发布过程不创建第二条构建链。旧来源不会自动迁移；已有本地测试安装按官方客户端确认来源与范围，避免同名候选同时启用。官方登录、权限和 Codex Hook 信任保持原流程；自有 Git 市场不代表官方公开目录审核通过。

## 精确资源与项目引导

在同一个安装版本中解析实际物理资源，保留原 helper 和明确的项目边界：

```text
bash <plugin-root>/lib/python_runtime.sh -B -X utf8 <plugin-root>/plugins/source_pack.py resource product/WORKFLOW.md
bash <plugin-root>/lib/python_runtime.sh -B -X utf8 <plugin-root>/plugins/source_pack.py resource platforms/shared/skills/xy-workflow/SKILL.md
bash <plugin-root>/lib/python_runtime.sh -B -X utf8 <plugin-root>/plugins/source_pack.py helper --project <absolute-project> lib/task_graph_cli.py validate --input <absolute-task-file>
```

`resource` 返回打包资源绝对路径与 SHA-256，不读取项目配置。`helper` 仅运行白名单 helper，以真实项目为 cwd，不创建 Agent 或虚构批准。项目使用实际验证的 `project.yaml` 或 `.awf/project.yaml`，不要从插件目录推断项目。

空项目可使用包内引导：

```text
bash <plugin-root>/lib/python_runtime.sh -B -X utf8 <plugin-root>/plugins/source_pack.py helper --project <absolute-project> plugins/project_context.py inspect
bash <plugin-root>/lib/python_runtime.sh -B -X utf8 <plugin-root>/plugins/source_pack.py helper --project <absolute-project> plugins/project_context.py apply --adapter .awf/project.yaml
bash <plugin-root>/lib/python_runtime.sh -B -X utf8 <plugin-root>/plugins/source_pack.py helper --project <absolute-project> plugins/project_context.py init --adapter .awf/project.yaml --input <decisions.json> --output <new-graph.json>
```

inspect 只读；显式 apply 只创建缺失 adapter，复用已有有效配置而不重写，不创建 PROJECT、规范、计划、HTML、指令文件、中央登记或桥。adapter 本身不是批准，不增加确认阶段；初始化仍保留原批准、门禁与所有权。多个 adapter、危险节点或旧中央绑定明确拒绝，不自动清理旧标记绕过来源检查。缺少必要规范、宿主能力或外部 Skill 时保留真实阻断原因。

## 原生入口与验收边界

| 宿主 | 主会话入口与角色 |
| --- | --- |
| Codex | 官方审阅后的 SessionStart Hook；亦可显式调用实际发现的 xy-workflow。插件不自动向用户配置创建角色，使用受支持的 fresh 原生交接或显式准备并核实加载的原生定义 |
| Claude Code | 插件 settings 选择主会话 pm，低于用户自有默认设置优先级；另有七个原生 Worker |
| Antigravity | 插件 rules/AGENTS.md 路由业务与显式维护；agents 保留七个完整角色正文 |

Codex 包只生成 `.codex-plugin/plugin.json`。客户端官方 Hook 审阅和信任不可绕过，不直接写信任记录或以全局指令替代；安装成功不自动授予 Hook 信任。AGY 构建保护每个 Skill 的 24,000 字节正文上限。

宿主入口、发现、安装、真实模型响应与完整工作流收口按各自证据分层判定。历史运行范围、失败及安装记录见[原生验收记录](https://github.com/Geoege-xll/agent-workflow/blob/main/docs/archive/plugin-v3-native-acceptance.md)、[远程安装记录](https://github.com/Geoege-xll/agent-workflow/blob/main/docs/archive/plugin-remote-install.md)及[发行主题](https://github.com/Geoege-xll/agent-workflow/blob/main/docs/plans/stable-product-release.md)。每个新包从 `runtime_verified:false` 开始，不能因构建、静态验证或安装回执宣称完整原生运行通过。

活动任务跨插件更新的自动资源保留协议尚未实现，更新前先收尾或交接。组件发行、插件 Git 分发与官方公开目录分别判定；本机安装不代表全局替换所有用户或业务项目。

## 已采用的官方格式依据

以下为此前实施核对的官方资料入口，本轮文档整理未另行扩展平台能力：

- [Codex 插件构建](https://developers.openai.com/plugins/build/plugins)及[桌面本地分发边界](https://developers.openai.com/plugins/deploy/desktop-only)。
- [Claude Code 插件参考](https://code.claude.com/docs/en/plugins-reference)。
- [Antigravity 插件构建](https://antigravity.google/docs/build-plugins/)。
