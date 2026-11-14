# xy-workflow 3.0 官方插件候选

插件唯一版本源为 `product/PLUGIN_VERSION`；独立配置工具版本源为 `native_config/VERSION`。本轮本机模型目录、调用偏好、配置页及只读派发接入已通过独立 QA，见[主题计划](https://github.com/Geoege-xll/agent-workflow/blob/main/docs/plans/native-model-preferences.md)。实际发行以 Git alpha 分支和真实 Release 资产为准，独立组件固定发行与发布状态以 `plugins/maintenance/component.json` 为准；固定组件描述只在真实下载校验后标记 published。本机安装状态以客户端列表和实际安装回执为准。默认使用自有 Git alpha 分发，官方公开目录与稳定发行尚未就绪，Windows 暂停。实际命令见 [INSTALL](INSTALL.md)，工作方式见[使用手册](https://github.com/Geoege-xll/agent-workflow/blob/main/docs/usage.md)。

## 载荷与职责

插件由官方宿主负责安装、启用、停用和更新。业务执行无需中央运行时、项目登记、TUI、Homebrew/npm 或配置服务，不向业务项目复制第二套完整规范。普通用户无需克隆工作流源码或本地构建；helper 运行仍需已有 Python 3.11+ 和 Bash。离线构建使用 Python 3.11+ 标准库；通过 `lib/python_runtime.sh` 选择已有解释器，不安装软件或修改 PATH。

载荷保留 `product/`、`roles/`、`platforms/shared/skills/` 权威及必要 helper 的白名单依赖。八个内置核心 Skill 保留共用前置元数据与完整正文，只插入实际宿主资源适配说明，references 按原字节复制。原生角色提示词保持完整角色正文。`sources.json` 记录来源、投影、包摘要与业务确认/执行合同检查结果；摘要证明内容一致性，不能证明宿主已经派发。

计划交付只维护 Markdown，已退役生成器及专用 renderer 不入包；原型 HTML、静态验收、依赖指纹和视觉确认继续有效。完整工作流规则由产品、角色、共用 Skill 维护。

精选第三方 Skill 独立于八个内置核心随包交付：Matt Pocock 的原版 `grill-me` 与唯一必要
primitive `grilling`、Leonxlnx Taste 和官方 Playwright CLI/Skill。公开发现只提供无hooks薄adapter
`xy-grill-me`、`xy-grilling`、`xy-taste`、`xy-playwright`，真实canonical名字和原文不改。
不引入上游 plugin、to-spec/prototype/engineering 全家桶。唯一原版资源保存在
`third_party/selected-skills/`，同包锁 `third_party/selected-skills.lock.json` 记录固定来源、commit、
逐文件大小与摘要；许可证、references、scripts、assets 及 credit 元数据完整保留。
所有发现入口都是本项目adapter；原版只在非发现vendor。Taste 原文超过 AGY 24k 正文限制且带 Stop hook，原文只在
非发现目录，发现目录中的本项目 adapter 无 hooks，必须逐段全文读取 canonical 与实际所需引用。

PM 自动需求覆盖通过 `xy-grilling` 完整加载原版；`xy-grill-me` 只接受当前用户显式调用，原版转调解析为同包
qualified `xy-grilling` 或读取同包 canonical，不能误调未知全局同名技能。`grill_result` 属于
xy-workflow 的 PM 适配。xy-uiux 保持 `xy-ui-design`、`xy-taste`、`xy-prototype-verify`
绑定；Claude 子代理 skills 声明不证明主会话已加载。用户与项目设计规范、紧凑应用布局、
原型静态验收及不截图边界优先；Taste gate 不替代唯一 QA，也不自动运行 scripts 或 Stop hook。

Playwright CLI采用锁定的官方发布包，不依赖用户全局命令或npm/npx临时下载；三个原包与
原版Skill完整随包，Node仍为运行前提，浏览器复用官方匹配缓存、按已有任务授权和宿主权限准备。
生产Web优先复用项目测试，补充交互首选 `xy-playwright`；其它浏览器需具体理由，电脑操控需
桌面能力。QA仅按实际Web审查面加载，不普遍预载或扩大权限。DOM snapshot不证明视觉通过。

所有 Agent（包括 PM、设计、计划与唯一 QA）都按当前任务、实际技术栈及职责按需选择 Skill，
统一规则位于物理插件根的 `platforms/shared/skills/xy-workflow/references/skill-selection.md`。
内置入口是候选推荐，不强制选用；宿主实际提供的用户级、项目级及其它插件 Skill 也可按需使用。
先按名称与说明缩小范围，再完整读取选中 Skill 及其要求的相关引用；不扫描个人目录或全量预载。
任务包的 `required_skills` 只记当前任务真正不可缺的依赖，不因内置推荐自动加入；缺失会阻断对应
阶段。同名来源歧义和约束冲突交 PM 协调。上级明确要求仍遵守，选中 Skill 后完整读取并遵守其
适用指令；未选用的 vendor Skill 中的 mandatory 字样不构成强制选择理由。

`xy-web-guidance` 是 Web API、兼容性或实现方案存在实际风险／缺口时的推荐候选，不因存在
HTML/CSS/客户端 JavaScript 文件就必须查询；已有可靠项目方案或纯业务逻辑可无需选用。
选中后按适用指令查询随包固定版本的现代 Web 指导，保留项目浏览器兼容策略、Taste 设计职责与
项目测试／Playwright 验证优先级。
运行查询需要已有 Node 22+；固定现代 Web 指导的 `search`、`retrieve`、`list` 使用随包本地数据，
不调用 npm、不自动联网或安装。`xy-apple-guidance` 是 SwiftUI 平台/API、状态、布局或兼容性存在
知识缺口时的推荐候选，不因存在 SwiftUI 文件就必须加载。选中后优先只读解析本机 Apple 官方
Specialist，新 API／迁移才读 What's New；本机资源不随插件复制，缺失如实
报告，不自动安装或用第三方镜像补齐。用户实际提供的并发、SwiftData、性能等 Skill 可按需补充，
不改变语言模式、UI 框架或最低系统要求。读取成功、CLI 查询成功与宿主模型实际采纳分别报告，
不能代替构建、运行、签名或唯一 QA。任何 Skill 都不扩大权限、路径、网络或原型自动化授权。

另有独立 `xy-config` 维护 Skill、固定薄启动器和组件发行描述，不计入 CORE_SKILLS 或 Worker 预载，不注入业务 envelope。仅用户在当前主会话显式调用时执行；普通需求中出现命令名称、实现或评审配置功能仍进入完整业务流程。维护动作不读整份 WORKFLOW、不建图、不派代理，也不产生业务批准。

独立配置核心位于 `native_config/`，由自身构建器交付，插件不导入服务、不包含网页、独立 ZIP 或模型 MCP。首次组件准备需要明确确认并校验真实发行包；维护失败不阻断普通工作流。插件缓存角色只读，原生文件与调用偏好分开管理。

唯一纯标准库只读合同 `native_config/preference_contract.py` 逐字节投影为插件的 `plugins/dispatch_preferences.py`，记录来源及投影摘要。PM 在派发前通过 `source_pack.py dispatch-preferences` 读取用户／项目偏好，无偏好时沿宿主默认；有偏好时只映射实际原生工具支持的字段，异常不静默回退。它不启动或准备组件、HTTP/MCP，不写设置，不改变业务确认、角色权限或当前主会话模型；维护 Skill 分支不进入该业务步骤。

当前公开命名由 `product/command_identity.json` 唯一维护；远程分发与组件可用性以真实 Release 资产和
`plugins/maintenance/component.json` 为准，本机是否已切换以客户端列表和实际安装回执为准；先完成当前活动任务。

## alpha 来源与安装

三个分发分支为 `plugins-codex-alpha`、`plugins-claude-alpha`、`plugins-antigravity-alpha`。Codex/Claude 的远程市场名统一为 `xy-workflow-alpha`，插件名为 `xy-workflow`；开发本地来源仍为 `xy-workflow-local`。完整官方命令见 [INSTALL](INSTALL.md)，不要交换 Codex 的 `--ref`、Claude 的 `#分支` 和 AGY 的 GitHub `tree/分支` 语法。

载荷来自同一成功 CI 的固定源码 SHA 与校验候选，发布过程不创建第二条构建链。旧来源不会自动迁移；已有本地测试安装按官方客户端确认来源与范围，避免同名候选同时启用。官方登录、权限和 Codex Hook 信任保持原流程；自有 Git 市场不代表官方公开目录审核通过。

## 精确资源与项目引导

在同一个安装版本中解析实际物理资源，保留原 helper 和明确的项目边界：

```text
bash <plugin-root>/lib/python_runtime.sh -B -X utf8 <plugin-root>/plugins/source_pack.py resource .agent-workflow/product/WORKFLOW.md
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

| 宿主 | 主会话入口与角色 | 上一 alpha.4 精确本机安装结论 |
| --- | --- | --- |
| Codex | 官方审阅后的 SessionStart Hook；亦可显式调用实际发现的 xy-workflow。未宣称插件 agents 清单自动发现角色，生产使用受支持的 fresh 原生交接或已核实原生定义 | 本地安装与 CLI 新插件实际启动通过；不扩大为全部业务、模型或 App GUI 行为通过 |
| Claude Code | 插件 settings 选择主会话 pm，低于用户自有默认设置优先级；另有七个原生 Worker | 插件发现通过；默认模型 90 秒未回应，PM 实际接管未验 |
| Antigravity | 插件 rules/AGENTS.md 路由业务与显式维护；agents 保留七个完整角色正文 | 本地安装通过；后续模型运行待登录 |

Codex 0.167.0 的实际对照发现根 portable 清单漏载 Hook，候选只生成 `.codex-plugin/plugin.json`。客户端官方 Hook 审阅和信任不可绕过，不直接写信任记录或以全局指令替代。安装成功不自动授予 Hook 信任。AGY 构建继续保护每个 Skill 的 24,000 字节正文上限。

早期 alpha.5 远程渠道的 CI、发布和安装发现分别记入[远程安装记录](https://github.com/Geoege-xll/agent-workflow/blob/main/docs/plans/plugin-remote-install.md)，不提前宣称三端模型运行通过。较早 alpha 候选的默认 PM、原生派发、同 ID 追加、配置与推理实验见[原生验收记录](https://github.com/Geoege-xll/agent-workflow/blob/main/docs/plans/plugin-v3-native-acceptance.md)，保留当时具体范围与失败。当前 App GUI 未验；发现、安装、真实模型响应与完整工作流收口分层判定。每个新包仍从 `runtime_verified:false` 开始，不因构建、静态验证或安装回执宣称完整原生运行通过。

活动任务跨插件更新的自动资源保留协议尚未实现，更新前先收尾或交接。独立配置预发行不代表插件公开市场稳定发行；本机安装也不代表全局替换所有用户或业务项目。

## 已采用的官方格式依据

以下为此前实施核对的官方资料入口，本轮文档整理未另行扩展平台能力：

- [Codex 插件构建](https://developers.openai.com/plugins/build/plugins)及[桌面本地分发边界](https://developers.openai.com/plugins/deploy/desktop-only)。
- [Claude Code 插件参考](https://code.claude.com/docs/en/plugins-reference)。
- [Antigravity 插件构建](https://antigravity.google/docs/build-plugins/)。
