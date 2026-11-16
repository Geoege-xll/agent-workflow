# Agent Workflow 3.0 使用手册

Agent Workflow 3.0 通过 Codex、Claude Code、Antigravity 的官方插件运行。[xy-workflow 3.0.3](https://github.com/Geoege-xll/agent-workflow/releases/tag/v3.0.3) 与独立配置工具 [Native Agent Config 0.1.3](https://github.com/Geoege-xll/agent-workflow/releases/tag/native-agent-config-v0.1.3) 均已正式发布，三个 stable 来源已从同一成功最终 CI 更新。本机三端插件／组件已升级为 `3.0.3`／`0.1.3`，载荷字节及执行位核对一致，模型偏好和原有项目启停／安装范围保持；Claude 当前源码项目仍停用，不表示全部项目启用。三端组件 doctor 均为 service ready／integrity verified，组件以 no-browser 打开；服务就绪与安装不证明指定模型实际运行。上一 [3.0.2](https://github.com/Geoege-xll/agent-workflow/releases/tag/v3.0.2)／[0.1.2](https://github.com/Geoege-xll/agent-workflow/releases/tag/native-agent-config-v0.1.2) 发行和安装记录保留为历史，完整证据见[发行主题](plans/stable-product-release.md)。Codex App 共享缓存已更新，但 App GUI 新会话、三平台指定模型实际运行及完整读屏未在本轮实测；官方公开目录尚未上架，Windows 暂停。helper 需要已有 Python 3.11+ 与 Bash，安装见[插件安装说明](../plugins/INSTALL.md)。

## 安装与会话入口

普通用户由官方客户端直接安装远程 stable，无需克隆本仓库或构建。Codex 使用 Git 市场的 `--ref plugins-codex-stable`，Claude 使用 Git URL 的 `#plugins-claude-stable`，两者正式市场名均为 `xy-workflow`；AGY 使用 GitHub `tree/plugins-antigravity-stable` URL。具体完整命令与检查步骤见安装说明；不要把不同宿主的分支语法互换。安装不需要中央运行时、项目登记、TUI、Homebrew 或 npm 安装步骤。

开发用 `xy-workflow-local` 与远程 stable 及历史 alpha 来源分开，旧安装不会自动迁移。按官方客户端确认来源与范围，停用旧候选或使用其卸载流程移除，避免两个同名插件同时启用。源码构建及临时加载仅供开发，见[开发手册](development.md)。

安装后开启新会话，并按宿主实际发现的入口使用工作流。Codex 的 SessionStart Hook 需要在官方客户端审阅并信任；Claude 的插件默认 PM 仍受用户设置优先级约束；Antigravity 由插件规则路由业务请求。发现 Skill、安装成功和配置文件正确，分别只能证明对应层次的状态，不能代替模型实际接管证据。

历史工作流插件 alpha.5 的 CI、发布与安装发现按[远程安装记录](plans/plugin-remote-install.md)分别验收，不从发布推断模型运行。更早插件 alpha.4 的本机精确安装检查中，Codex CLI 实际启动通过；Claude 插件发现通过，但默认模型在 90 秒预算内未回应，PM 实际接管未验；Antigravity 安装通过，后续运行等待登录；App 图形界面未验。这些历史插件版本不等同本轮独立组件 `0.1.0-alpha.5` 候选；较早的单项证据见[原生验收记录](plans/plugin-v3-native-acceptance.md)，不能扩大为当前所有客户端均通过。

市场刷新与已安装插件更新按宿主分别处理，具体步骤见[安装说明](../plugins/INSTALL.md)。插件更新前先收尾或交接活动任务；当前版本尚无活动任务跨缓存更新的自动资源保留协议。仓库清理和本机安装不代表自动替换其他用户、其他项目或所有旧安装。

## 项目接入

PM 使用会话中明确的实际项目目录。插件权威资源从当前安装包读取，项目配置从所选 adapter 读取，两者分开；不向项目复制第二套完整工作流规范。

已有有效 `project.yaml` 可以复用。新项目由插件包内 `plugins/project_context.py` 的 inspect 只读检查；用户明确接入后 apply 只创建缺失的 `.awf/project.yaml`，不制造空 PROJECT、规范、计划、原型或批准记录。多个 adapter 必须明确选择，后续任务与原型工具继续使用同一 adapter。原生配置、旧中央绑定或来源混用的拒绝信息应按真实原因处理，不能伪造绑定或写全局指令绕过。

## PM 持续接单与调度

主会话持续担当 PM。任务 A 运行时收到 B，PM 先判断它是补充、纠正还是独立请求，再结合真实路径、语义资源、依赖与平台容量决定并行、复用原 Agent、追加或等待。收到针对 A 的 C 时，将当前增量完整交给原职责实例；不同请求的需求批准、视觉批准和唯一 QA 分别维护，不共享批准标记。

PM 负责协调、计划、任务包、文档归属和交付。生产实现默认委派对应的原生子代理；新任务使用 fresh/handoff_only 的最小完整交接包，不复制 PM 或兄弟会话。同任务返工和原 Reviewer 的增量复查可复用原实例。claim 只表示准入预留；创建结果未知时，不能当作已创建或自动释放后重复派发。

复用的是角色／配置及同任务必要上下文，不把空闲会话当作无关任务的通用池。任务收口后先保全交接和必要证据，再按宿主能力原生关闭；缺少关闭工具时逻辑退休，禁止误派，不宣称历史已擦除、进程已销毁或仍运行任务的锁已释放。

## 按需技能与推荐入口

所有 Agent 都按当前任务和职责使用宿主实际可用的 Skill，包括用户级、项目级和其它插件提供的
能力；内置入口是候选推荐，不强制选用，也不是封闭白名单。先判断当前技术风险和知识／证据
缺口，再按名称与说明选择；选中后完整读取 Skill 与必要引用并遵守适用指令，不扫描个人目录
或加载全部技能。上级明确要求仍遵守，但未选用 vendor Skill 内的 mandatory 字样不构成强制选择
理由。任务包 `required_skills` 只列当前真正不可缺的依赖，不因内置推荐自动加入；缺失或同名来源
不清时由 PM 协调。不会为了补齐技能自动全局安装、升级工具或扩大权限。统一细则见
[Skill 选择规则](../platforms/shared/skills/xy-workflow/references/skill-selection.md)。

Web Agent 可在 Web API、兼容性或实现方案存在实际风险／缺口时选用 `xy-web-guidance`，选中后
按适用指令查询随包固定的现代 Web 指导，再结合项目浏览器支持策略实现。存在 HTML/CSS/客户端
JavaScript 文件并不要求必选；已有可靠项目方案或纯业务逻辑可无需选用。查询需要已有 Node 22+；
`search`、`retrieve`、`list` 使用本地随包数据，不调用 npm 或自动下载。Apple Agent 可在 SwiftUI 平台/API、状态、布局
或兼容性存在知识缺口时选用 `xy-apple-guidance`，不因文件存在就必须加载；选中后优先只读使用
本机 Apple 官方 Specialist，仅在新 API 或迁移时读取 What's New；本机没有相应资源就报告限制，
不自动下载镜像。相关的用户自有并发、SwiftData 或性能 Skill 仍可按需使用。
技能不会更改项目栈、最低系统、设计依据、原型权限或 QA 职责；实际读取、查询运行和模型采纳
分层判断，构建／测试／签名仍需各自真实证据。

## 需求与视觉两步确认

Full 在目标、范围、约束、验收和方案完整可评审后，请求一次需求确认。PM 先完整展示简洁方案与必要建议，再提出确认选择。涉及 UI 设计变化时，在同一次需求确认中给出原型建议并记录用户选择；需要原型的任务完成具体 HTML 页面和静态检查后，再请求一次视觉确认。视觉批准绑定实际页面、变更范围和依赖指纹。

非 UI、UI 一致性实现、用户明确免除原型的任务，默认仅保留适用的需求确认。Light 使用当前明确授权，不强加 Full 计划、DAG、保存计划或重复确认。原型验证、BUILD_VERIFIED、独立 QA 和文档投影是证据或状态，不自动增加业务确认；实际平台安全权限另按客户端要求处理。

用户明确要求“本次仅改实际产品、不改原型”时，按其当前授权范围处理，并在任务与交接中说明旧原型不作为本次新增设计依据；该选择不成为以后任务的默认豁免。原型评审阶段的修改仍归原型，“按已批准原型实现”仍需读取有效原型依据。

## 原型、验证与独立 QA

需要原型的 UI 任务由设计 Agent 在所选 adapter 的 `docs.standards_root/prototype` 内制作可交互 HTML，并返回需求覆盖、规范符合性和交付一致性的三维自检。PM 将 REQ 到具体页面及实际状态锚点的关联写入同一主题计划；原型 HTML、静态验收、依赖指纹与视觉确认继续保留，不恢复计划 Markdown 转 HTML 生成链，也不增加第二个原型 QA。

已完成独立功能 QA 的 live 5 双网页交付使用当前物理插件根的白名单 `prototype_feedback_cli.py open`，显式指定实际项目、同一 adapter、唯一需求 Markdown、request-id 和本轮 pages。交付时启动本机服务，提供返回的具体页 `delivery_url`：共用可缩放画布保留真实产品交互，左目录默认收起且由统一元数据派生；“进入评审”通过 noopener 新标签页准确打开当前页，原交付页保留。评审进入即批注，没有目录、持久浏览模式切换或开发说明；按工具提示的修饰键临时操作设计，释放后继续批注。两页共享画布组件，分别保留相机与交互状态。

```text
bash <physical-plugin-root>/lib/python_runtime.sh -B -X utf8 <physical-plugin-root>/plugins/source_pack.py helper --project <physical-project-root> lib/documents/prototype_feedback_cli.py open --root <physical-project-root> --adapter <selected-project-adapter> --plan <project-relative-Markdown> --request-id <request-id> --pages <project-relative-HTML>
```

目录只包含本次 `--pages` 明确登记、属于同一需求且通过安全校验的 1—16 个具体页；上面的单页示例只显示一页，不会扫描整个项目、其他需求或未登记页面。需要多页目录时，在同一次 `open` 中传入各实际页面路径，共用同一个 `--plan` 和 `--request-id`：

```text
bash <physical-plugin-root>/lib/python_runtime.sh -B -X utf8 <physical-plugin-root>/plugins/source_pack.py helper --project <physical-project-root> lib/documents/prototype_feedback_cli.py open --root <physical-project-root> --adapter <selected-project-adapter> --plan <project-relative-Markdown> --request-id <request-id> --pages <project-relative-HTML-1> <project-relative-HTML-2>
```

两页从交付目录读取同一物理原稿，桥和来源键只在 HTTP 内存响应注入，不为活动评审在磁盘维护业务 HTML 副本。项目只保存具体页面、五段契约和必要业务资产；新项目不生成通用导航 index、不复制工具脚本或样式。既有业务首页与未知文件不能按名称删除。原稿通过 file:// 仍可离线查看与操作，但不承诺完整目录／相机、一键冷启动或发现随机服务端口。服务不可用时，由交付方用同样显式参数重跑 open 并提供新链接；status 查询指定项目请求的有限状态，stop 停止精确实例并保留意见。不把 token、随机端口或机器绝对路径写回原稿，也不配置系统自启动或系统 URL 协议。

新 live 使用 boot 5、严格 context 3 与 feedback 5 四字段 `schema_version/review/anchors/items`。短 review 只有 request_id/review_id，绑定真实来源修订；复制和下载采用相同紧凑 JSON／Markdown，不附重复摘要。标记 A 与整改分别编号且不设等级；节点修改／新增／删除、页面修改／新增、整体修改及显式跨页引用保持。REQ／交互／接口只从真实目标源还原，匿名来源键仅在响应注入，动态无来源节点明确要求选择真实源父层。

草稿通过带 revision 的 CAS 保存，刷新或重新进入可恢复；冲突明确提示，不静默覆盖。原稿变化保留旧意见并阻止错误定位与交还，不用活动指针重绑旧 review_id。validate 以相同项目和 adapter 核验显式反馈及其真实 live 修订，只返回 current、短 review、必要 anchors、按目标分组的精简 changes 和“修订输入非批准”提示；PM 将这些结果连同当前完整任务包交回原 UI Agent。普通整改只交还明确引用的 A，无整改时交还全部明确标记，不推断整改。

本机服务仅绑定 127.0.0.1 随机端口，严格验证 Host／Origin／认证，网页没有任意 root、argv 或 file 接口。设计内容处于只读资源闭包与 allow-scripts sandbox 内，不能读取父控制认证；桥联合核验 source、当前页、token 与 null origin。认证 URL 仅用于受信本机入口，不进入公开日志。新工具与旧 V4 资产分别冻结，三端携带相同核心与完整白名单。

历史 prepare 及 feedback 2／3／4 的离线不可变包继续按原合同只读装配／消费，原 index、浏览／批注、开发说明及对应 manifest／boot／bridge 不受 live 分支替换；不迁移旧包或草稿。已验收的 feedback 4 精简交接和配置恢复仍保留。工作流 3.0.3 与组件 0.1.3 已正式发布，最终绑定 CI、三 stable 分发与本机升级均已完成；这些证据不替代真实宿主的指定模型运行采纳。旧壳迁移仍需明确授权的预览／执行／恢复，只清理可证明归属的纯工具，保留混合及未知业务资产。调用与封闭格式见[反馈消费合同](../platforms/shared/skills/xy-ui-design/references/prototype-feedback.md)。

实施者按实际改动完成必要构建、运行或文档检查，提交真实证据。Full 由请求级唯一独立只读 QA 检查集成范围，失败交原职责作者修复并由原 Reviewer 复查。Light 按风险与明确请求选择必要独立审查；未做独立 QA 时只报告真实验证结果，不宣称 QA PASS。

QA 通过后由 PM 接收结果，按当前事实评估并原位更新受控文档，再执行已选择的本地交付策略。要求确认的 worktree 最终交付需呈现具体可评审结果；已有自动交付或明确合并推送授权按其范围执行。完成收口仍需说明实际改动、验证、交付位置及未验证边界，不用源码检查冒充宿主模型运行。

## 文档、notes 与可选记忆

同一稳定主题只有一份可编辑 Markdown，贯穿需求、实施、恢复与验收。PROJECT 仅索引明确已验收的基线；执行完成、文档存在、勾选框和旧 completed 标签不构成当前功能验收。进行中的目标与上一已验收行为分开记录，失败、暂停和取消保留原基线。具体规则见[文档与原型指南](plans/workflow-document-lifecycle.md)、[计划模板](../templates/docs/PLAN.md)及[需求交付规则](../platforms/shared/skills/xy-plan/references/requirements-markdown.md)。

必要结论归既有相关主题或适用且获准的项目规范；没有合适归属时保留在当前交接。不要新建 notes、替代杂记目录、空索引、占位主题或另写 feature/ADR，也不把每条经验自动提升为规范。完整日志、原始批准和唯一恢复资料留在请求证据区，Git 保留可追溯历史；长期文字不存凭据、个人数据或完整日志。

agentmemory 是可选服务。只有工具能强制按项目过滤并返回匹配出处时才 recall/save；不足时沿现有计划、规范与交接继续工作，不阻塞普通工作流，也不把未经审计的背景记忆当作批准或权限。

## 模型配置与工作流启停

没有调用偏好时，工作流沿宿主当前模型与推理设置。显式调用插件的 `xy-config [open|status|doctor]` 可打开配置页，省略动作等价 open；操作细节见[原生 Agent 配置工具](agent-configuration.md)。普通业务请求中出现命令名称不会触发维护路径。

首次缺组件时先展示固定版本、来源和准备信息，经确认才下载已核验发行包。配置页默认管理“调用偏好”，提供用户级和当前项目的通用默认／逐 Agent 设置；没有原生文件时也有通用入口。设置先预览再保存，PM 在下一次派发前通过纯只读 helper 解析，不需要常驻 HTTP 或 MCP。无法表达的已配置字段会明确报告，不会悄悄忽略。

0.1.3 通过短期派生会话恢复普通刷新后的平台／范围／真实项目；原入口片段首次使用后清除，原入口令牌不写浏览器存储。派生会话绑定精确 origin 与服务实例并有期限；存储拒绝时当前有效页面仅内存运行，刷新须重新打开。失效页面明确提示重开，恢复不会自动保存草稿。

“原生定义文件”采用搜索列表与详情双栏，保留实际身份、来源和未知状态以及完整定义编辑，插件缓存始终只读；模型目录按本机对应客户端／有效配置读取，推理选项按当前模型处理。调用偏好保存、原生文件重新加载和实际指定模型运行分别判断，不改变当前主会话或运行中的 Agent。

组件提供 Codex／Claude 工作流用户级默认与项目三态设置；Claude 当前项目使用个人 local 范围，AGY 启停为只读官方管理说明。当前工作台将通用默认和动态 Agent 表格集中呈现，模型、原生字段和启停使用独立草稿，当前事务统一预览保存；普通切换保留草稿。停用后可用页面给出的独立命令重新打开。发行状态与准确安装版本按固定描述和官方客户端回执判断，不把已接受源码功能当作现有安装已具备。
