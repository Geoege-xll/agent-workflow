# 配置页中的工作流项目启停

- 主题 ID：`workflow-project-activation`
- 阶段：`completed`
- 模块：独立原生配置核心、配置网页、官方插件设置
- 任务等级：`Full`
- 已验收版本：`0.1.0-alpha.4`

## 目标与范围

用户已批准在 agent-config 网页管理工作流启停，并明确选择“沿用现有规范，直接实现”。提供用户级默认以及当前项目的继承／启用／停用，保存各平台原生配置，复用现有预览、条件保存、冲突保护与恢复收据。独立配置工具增加本功能，插件维护 Skill 仍仅接受 open／status／doctor。

本轮不发布、不安装、不修改真实宿主或业务项目配置；不恢复中央运行时、TUI、npm 或 Windows。已有 alpha.7 原型反馈实现及未跟踪用户文档保持。当前配置、安装观察和实际运行结果分开，不能把文件保存当 PM 已接管。

## 需求与验收

| 需求 | 验收条件 |
| --- | --- |
| REQ-ACT-001 原生三态 | Codex 用户／可信项目插件 enabled 布尔；Claude 用户／个人项目 local enabledPlugins 布尔。继承仅移除目标键，保留其他字段、注释、正文与换行。 |
| REQ-ACT-002 真实优先级 | 展示本层值、继承来源、配置目标与观察边界；Claude local 继承后仍可能采用 shared project 值；未知不能当启用。Codex 项目信任、启动参数和托管策略保持宿主权威。 |
| REQ-ACT-003 安全保存 | 预览零写入；来源、前像、目录及安装身份改变拒绝旧计划；首次创建固定配置路径支持排他发布，不覆盖外部新文件；失败保留实际发布与恢复事实。 |
| REQ-ACT-004 网页体验 | 沿用现有布局、语义样式与控件；工作流与模型草稿分开，禁止一次混合提交；预览明确平台、项目、目标层及后果。切换范围、并发响应、错误恢复、键盘、焦点、窄屏可用。 |
| REQ-ACT-005 恢复与生效 | 停用前提供独立组件重新打开方式及官方恢复步骤；保存／等待新会话加载／真实运行未验证明确分开，当前会话不承诺清除已加载上下文。 |
| REQ-ACT-006 平台边界 | AGY 未有足够官方项目覆盖配置合同，显示不支持及官方管理说明，不编造配置键或执行全局命令冒充项目操作。 |
| REQ-ACT-007 回归与交付 | 模型配置和原维护路由不回归；独立包包含新核心并能离开源码运行；作者定向验证后由唯一独立 Reviewer 接收。 |

## 方案与原型关联

本轮为生产配置页 UI-Patch，用户明确直接实现，不新增或修改原型、设计规范。界面沿用 native_config/web 的生产基础和适用工程／设计规则。配置卡独立于 Agent 模型字段，使用同一鉴权 HTTP 边界与预览／应用核心，不新增 MCP、安装器或通用任意文件写入能力。

HTTP 复用 /api/context、/api/preview、/api/apply。context 新增 workflow_activation；preview 新增 workflow_activation: {state: inherit|enabled|disabled}，不得与 edits/reset 混合；apply 请求仍仅 preview_id。启停变更以独立 kind 区分，不扩充模型 FIELDS。revision 必须绑定目标配置及继承来源。完整具体响应合同由核心作者先冻结，再交网页作者消费。

Claude 项目范围写 .claude/settings.local.json，明确仅本机当前项目；shared settings.json 为继承来源，不修改。Codex 项目写 .codex/config.toml；用户根尊重现有 CODEX_HOME／CLAUDE_CONFIG_DIR 选择。只允许已发现并明确识别的工作流插件身份，不扫描缓存推断生效或接受客户端指定任意路径。

核心作者独占 activation 模块、storage、service、server 及相应测试；网页作者独占三个生产网页文件和网页测试；交付作者维护独立版本、打包及包外恢复验证。先冻结接口，核心与网页再并行；交付在实际新增模块确定后进行。全部生产实现由 fresh/handoff_only 原生子代理完成，不复制 PM 会话。

## 当前进展与恢复入口

实现基线：29cdecf22e164f4bb46553d22564d6c6e818d0e5；分支：codex/project-workflow-activation。源码候选已获唯一独立 QA 最终 PASS，尚未合并、推送、发布或安装。核心 65 项、网页 6 项、独立包 5 项及其余直接调用者 53 项已分段通过，真实浏览器与包外恢复亦已执行；首次沙箱及驱动失败原日志保留。首轮 QA-RECOVERY-001/P2 已由原核心／打包作者修复：命令本身保留同一配置与状态根，新增两项精准核心检查和一项包恢复检查通过；同一 Reviewer 复用未变结论并关闭该问题，不建立第二轮全套审查。

后续恢复入口为本分支源码、同一主题和 `dist/evidence/workflow-project-activation/` 的完整证据。三作者使用 fresh／handoff_only 原生实例，唯一 Reviewer 为 `/root/activation_qa`；未复制 PM 或兄弟会话。测试浏览器及包外自有服务均已关闭，不把安装文件或保存回执当作宿主新会话已运行。临时执行路径不是持久恢复前置，不重新派发本轮已完成任务。

完整任务包、初审失败／最终交接、固定审查输入、原始成功／失败日志和真实候选保存在上述私有持久目录，不纳入 Git 或公开发布。初审原件保留 initial- 前缀；review-graph.json 是最终审查输入，graph.json 是收口后的原任务快照，都不是后续新任务的调度源。原包／日志中的临时绝对路径已退役：同名原字节文件在本持久目录解析，审查输入图映射到 review-graph.json，保持包与交接 SHA 不变。author-verification.json 明确是 PM 对实际收到的原生作者交接的命令／退出码投影，与原始日志并列，不冒充执行器 stdout。独立工具候选为 0.1.0-alpha.4；现有插件 descriptor 仍指向已发布的 0.1.0-alpha.3，发行和本机升级另行执行。

必要原字节和浏览器文字快照转存并核对后，仅本请求的临时 fixture／解压副本／工作记录已按预览快照清理；未清理其他任务、系统缓存或用户资料。完整证据和真实候选仍在上述持久目录，测试没有保存截图。

## 验收结果与当前已交付行为

已验收源码候选 0.1.0-alpha.4：Codex／Claude 的用户级默认与个人项目三态、明确继承来源、独立启停草稿／预览、安全首次创建与冲突保护、实际失败恢复收据，以及停用后的独立打开与官方恢复说明。AGY 保持只读不支持，未伪造项目写入接口。模型字段、插件维护路由和业务工作流确认／QA 规则保持。

真实验证运行于 macOS 和已有 Chromium，含 390 CSS px、键盘／焦点、浅深色配对对比度、真实 HTTP 409、包外隔离恢复及全部 26 载荷字节检查。Linux 排他目录发布仅完成源码审计，未执行原生分支；Windows 暂停。真实宿主加载、项目信任、Hook 信任和模型执行不由这些检查证明，runtime_verified 继续为 false。

现有 alpha.6 本机插件、已发布配置组件 0.1.0-alpha.3 及固定 descriptor 保持；当前用户通过旧插件入口不会自动获得本候选的新页面。后续需发布独立组件、核实实际资产并更新插件描述，按官方客户端升级；不在本轮自动执行。完整原型反馈 alpha.7 实现及其独立待发布计划仍归原主题，不混入本次验收结论。

## 批准依据与必要证据

- 批准依据：用户在项目启停方案后回复“可以，开始优化”；随后明确选择“沿用现有规范，直接实现（推荐）”。
- 验收证据：唯一 Reviewer 初审 FAIL 后，同实例增量复查最终 PASS，69 条规则覆盖、完整 16 路径实现 dirty 范围及 UI 范围校验均有效。最终结构化交接为私有持久目录中的 activation-qa-handoff.json，SHA256 为 b62472a416327304e839afe76b67b331ec99f0e76e82969fe197112f92d2d8d7；绑定 QA 包 SHA256 为 7ee259142be2330a87e2131b4e18f8680b7cefb79015a149f7375d80198dd0f4。最终独立候选 ZIP SHA256 为 70d378978189013e0f44bed88aa817fed7a987c7501cc37793864fc1dbfddef2。QA 之后只有 PM 说明文档投影，另查格式、链接和已验收源码一致性，不冒充新的功能审查。
- 官方配置依据：[Codex 配置](https://learn.chatgpt.com/docs/config-file/config-reference)、[Claude 插件范围](https://code.claude.com/docs/en/plugins/cli-reference)、[AGY 插件](https://antigravity.google/docs/plugins?tab=cli)。AGY 当前资料不能证明项目三态文件合同，因此不提供猜测写入。
