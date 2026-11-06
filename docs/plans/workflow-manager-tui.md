# 工作流管理工具

- 主题 ID: `PLAN-WORKFLOW-MANAGER`
- 阶段: `completed`
- 模块: `.`
- 任务等级: `Full`
- 已验收版本: `local-2.1.0-claude-sources-295186ff19c7`

## 目标与范围

本轮修复独立审计确认的三项Claude模型来源缺陷：settings.env与shell同名变量优先级反向、提供方路由开关未纳入来源身份、project/local的modelPicker被错误当作原生有效菜单。用户在三项缺陷、触发与修复建议明确后回复“开始修复”，授权当前范围；不重复确认既有决定。

修复以普通本地Claude会话的实际配置合同为依据，让目录、别名、当前模型和来源戳消费同一有效来源投影，并按字段真实作用范围处理。全局／项目偏好解析、reset与显式inherit、预览确认和旧草稿授权保持。来源变化不能静默续期旧草稿，非生效来源变化也不应误伤现有草稿。

生产范围限manager/catalog.py、必要时manager/claude_execution.py；长期回归限tests/test_workflow_manager.py和tests/test_role_preferences.py。PM维护本主题及同名HTML，其他5条外部修改保留。不新增功能、依赖、公共CLI/JSON字段、通用配置框架或持久化缓存，不改TUI布局／键位／交互结构、角色职责、Skill源包与三平台软链接、中央记录、版本pin或旧版本兼容；不修改真实账户、项目启停或三个业务项目绑定，不升级宿主、不调用付费推理或远端发布。

## 需求与验收

| 需求 | 完成标准 |
|---|---|
| REQ-CLAUDE-001 有效env | 同名settings.env按适用设置层级覆盖普通shell值；ANTHROPIC_MODEL等环境变量对顶层model的独立优先级仍保持。目录、映射、当前值与来源身份来自同一解析结果，合法对象菜单回归覆盖；真实生效文件变化拒绝旧来源，被遮住的shell变化不误废弃 |
| REQ-CLAUDE-002 路由身份 | Bedrock／Vertex／Foundry等实际提供方选择及必要非敏感路由字段纳入有效来源校验；换提供方不得继续授权旧目录。不得简单哈希全部环境变量或读取凭据正文；不凭文档猜测托管、Desktop、runner或运行中会话实际值 |
| REQ-CLAUDE-003 菜单作用范围 | modelPicker按原生允许的来源层处理，project/local不能替换有效用户菜单或成为可选目录证据；保留正确显式用户设置，区分显式当前配置与旧目录缓存，不让同层或更高层真实模型配置丢失 |
| REQ-CLAUDE-004 消费者与保全 | 三项最小长期回归先在未修源证明行为红；修复后目录／来源守卫、偏好服务及真实App全局／项目保存和旧授权拒绝有直接证据。现有agy（Antigravity）静态档位与三平台草稿隔离有效结论复用；必要直接消费者及唯一独立QA通过。完整日志和外部修改保全 |

## 方案与原型关联

本轮为后端来源正确性修复，production surface为non_ui；不写TUI或设计文件。现有界面、键位、提示及原型保持，真实App测试验证后端结果被现有界面正确消费；不启动原型、设计升级或原型审查。现有通用布局、字符格和PTY结论在输入未变时复用。

一个fresh／handoff_only的xy-backend实现包统一拥有上述4条生产／测试路径，先补三项行为回归，再修正Claude有效来源边界；若提取共用env解析，仅放现有claude_execution职责内并由catalog和controls消费，保持对外discover、Catalog和偏好API不变。该包是同一高度耦合缺陷链，不并行写同一解析逻辑，不创建额外worktree、源码候选副本或新框架。PM协调并由唯一新的xy-qa独立验收，不复用已经结束的审计实例作为实施作者。

必要验证按具体风险选取：三项目录回归、Claude controls与相关已有目录节点、偏好服务全局／项目物化、实际App编辑／预览／确认及换源拒绝，最小Antigravity合同消费者。不重跑未受影响的Codex原生组、中央发布故障组、npm载荷或整仓；明确实测fixture／CLI与宿主加载／账户推理的不同边界。普通绘制／预览／guard不得启动原生查询，失败保留旧expected／stamp与草稿。发生修复仅重验受影响结论，不为提交追加保险回归。

唯一QA正式PASS后，原位更新本主题当前已交付的Claude来源事实和必要证据、同名HTML；不创建报告、ADR、替代notes、PROJECT或STANDARDS空索引。PM精确本地提交已验改动，保留其他任务归属，不push/tag/release或切换业务项目核心。

## 当前进展与恢复入口

三项Claude来源缺陷已完成修复，原作者有界返工后的SDK端点和区域生效条件也已由同一独立Reviewer正式PASS；原生结果经PM正式校验valid，6路径和28条适用工程规则闭合。当前已验收版本绑定候选tree295186ff19c7843d1c3ca25326fe4012da40a2ae，产品版本仍为2.1.0；QA后仅本主题及同名HTML作完成态投影，生产和测试保持验收字节。

初审FAIL、修复前行为红、测试fixture修正及最后4节点成功的完整输出均保留在request-id fix-claude-catalog-sources-20261106的既有scratch。恢复时以该请求当前scope、完整作者交接、原生QA结果和当前主题为准；初审原件以initial后缀保留，旧日志摘要仅对应保全的25345字节前缀，不作为当前全日志身份。原8d26540稳定性基线可由d331f81历史恢复，既有TUI和中央运行时的已验行为继续有效。

前序只读审计的24个相关节点和真实App双平台保存链成功，不替代本轮三项缺陷的定向证据。审计日志仍在request-id audit-claude-agy-20261106的audit.log，70841字节，SHA256 2d3eeb040e028ede8b404936b9c103979d4f6c5fac241213c89a4f31aa398a75；实际Claude版本探针为2.1.311。agy在当前PATH及两个限定Applications位置未发现，Claude具名角色原生加载、实际账户推理和运行中宿主最终路由未验；本轮未安装宿主、登录、调用付费推理或切换业务项目核心。

## 验收结果与当前已交付行为

整个工作台由完整粗线外框包裹，标题、顶部平台、内容、状态和操作提示分区清楚，内部使用较轻分隔。主界面、等待状态、路径输入、模型选择、预览、帮助和结果弹层共用 Layout 坐标与外框；文字、光标、滚动条及鼠标命中使用同一可用区域，右下角与弹层接头闭合。80 列以上并排显示项目与右侧内容，55×16 保留单区域选择和滚动，过小窗口可安全退出；中文字符格、单色焦点及缩放行为已覆盖。

主界面 Tab 切换下一个顶部平台，Shift+Tab 切换上一个，首尾循环；1／2／3 和顶部点击继续可用。平台切换保留项目、区域焦点、匹配角色和各范围草稿。左箭头聚焦项目，右箭头聚焦右侧内容，重复同方向保持当前区域；上下选择当前区域条目。m／e 继续独立编辑模型／推理级别，Enter 和鼠标保留相应编辑能力。搜索、路径输入及弹层优先处理自身按键，左右仍移动输入光标；忙态继续阻止底层平台／区域切换和重复管理操作。

外框内有独立工作流管理条，其下横线分开管理操作和内容区；两栏统一“项目列表／角色模型”标题及辅助信息。项目条目使用轻虚线，状态／版本辅助文字保持普通字重，选中背景仍可辨认。按钮显示“启用工作流／停用工作流”，o／p 先打开变更预览，Enter 才确认，不终止已运行任务。

项目列表上方固定“全局默认”，不计入项目数量；项目区域按 Home 可直达，再按右箭头或 Enter 打开角色表。全局范围复用平台及角色表，隐藏项目启停操作；角色选择、草稿、编辑前像和目录按全局／项目／平台隔离。v 详情展示有效模型、推理、字段来源及跟随关系，窄屏可滚动。

全局默认按平台×角色保存在中央状态的 preferences/role-models.json，不属于不可变核心。空配置只读查询不创建文件。每个字段依次取项目覆盖、全局默认、宿主；项目直接修改模型只覆盖模型，单独修改推理只覆盖推理。项目选择器明确区分“跟随全局”和显式“继承宿主”：前者清除对应覆盖，后者保留 inherit；即使当前有效值相同，也按用户选择的来源处理。模型选择后进入推理选择器时，未修改的推理继续保持原来源。

g 管理菜单或冒号命令可暂存恢复模型／推理跟随全局，全局范围则恢复跟随宿主；u 只丢弃当前角色草稿。s 先预览保存范围，全局预览列出受影响登记项目及冲突，Enter 确认后才备份保存，取消不写入。应用成功后反馈备份及真实结果；写入失败保留草稿和安全诊断；业务已经完成而显示刷新失败时，按实际完成结果结算并清除已应用草稿。明确项目覆盖和显式宿主继承保留，停用／未管理项目不自动安装，后续启用／选版使用当前有效值，核心绑定与旧任务 pin 保持。

CLI 的 roles／set 必须选择互斥的全局或项目范围。模型、推理可独立设置；reset 清除指定字段，all 清两字段，未传字段保持当前来源。set 默认只读预览，--apply 才调用共享计划。CLI／TUI 共用偏好解析、目录来源检查、协调锁和事务；全局先准备全部目标，失败按精确前像条件补偿，存在并发编辑则保留冲突和恢复明细。

模型目录按范围／宿主复用，失败或失效后重进编辑可有界恢复；绘制、保存预览和事务守卫不启动原生目录进程。旧草稿来源基线保留，必须重新确认或丢弃后才能应用。恢复备份时，按拟恢复项目配置与当前全局默认核对原生模型／推理；仅恢复原生或仅恢复配置导致来源不一致的计划均在写入前拒绝，不自动制造项目覆盖或改全局。确认前及验收后检查配置来源、未改角色和原版本前像，正常明确项目恢复及失败补偿仍有效。

来源层保留每次原生查询的前后收据，只对同一未发布批次内连续、稳定的自身缓存刷新归一共享提示。偏好服务一次取回角色值、字段来源、跟随值和目录上下文；旧草稿的expected与来源戳独立保留。普通绘制、预览、guard与保存后显示刷新均不启动原生目录查询。

Claude普通本地来源由catalog与controls共用有效env投影：同名值按shell、user、project、local的适用覆盖关系解析，保留每个字段的真实来源；环境变量ANTHROPIC_MODEL对顶层model的独立优先级保持。模型目录、别名映射、当前值和来源校验消费同一结果。project/local的modelPicker不作为有效菜单，用户显式菜单与当前有效模型保留；本工具不读取组织managed或--settings菜单，不把旧缓存当作当前账户可用性。

Claude的提供方开关及必要非敏感路由值进入私有来源身份。Bedrock的控制面和运行面各按service SDK端点再global SDK端点选择；显式ANTHROPIC_BEDROCK_BASE_URL优先，AWS_IGNORE_CONFIGURED_ENDPOINT_URLS只屏蔽SDK配置端点。双服务端点覆盖global、显式client覆盖SDK或provider关闭时，被遮住的变化不废弃授权。Bedrock的small-fast-region须满足Haiku／当前原生仍接受的SMALL_FAST模型选择条件；Mantle按官方独立语义处理，Anthropic AWS不消费该变量。Vertex非法位置按未设置回退，合法区域变化仍进入校验。不读取SDK profile/config或凭据正文，不哈希全部env，也不声称解析了运行中账户路由。

有效文件env、provider或SDK端点在预览后变化，真实确认apply会拒绝旧授权；被遮住的shell、端点或非生效区域变化不误伤草稿。重取目录和显示刷新保留原expected与stamp，旧草稿不会静默续期。真实App覆盖全局取消不写、确认双项目落盘、项目override／inherit／reset及换源拒绝；这些路径不启动原生目录或账户推理。

TUI的Session集中保存每个范围的草稿／前像及显示缓存，后台Job单独记录业务是否已完成、刷新与回调是否成功。实际写入成功而后置刷新失败时，结果仍说明已完成的动作并清除已应用草稿；失败不复活旧确认页，相关显示按真实影响范围失效，busy、回调与输入状态最终结算。

中央私有记录统一校验binding、journal与retained后再交动作编排。发布中以私有marker明确标识未完成边界，使用原有精确前像、旧inode与无覆盖发布；进程中断或外部晚保存时安全拒绝并保留必要恢复材料，不凭随机残留猜测恢复或删除未知写入。新增runtime_state已接入最小核心和npm精确载荷。

真实 PTY 覆盖平台／区域导航、全局入口、来源与覆盖选择、暂存／保存／取消、并发失败、项目启停、输入隔离及窄屏缩放。键盘、焦点、单色与字符格检查通过；实际账户模型推理、屏幕阅读器认证及 Windows 原生运行不在本次验收范围。候选模型始终来自当前来源，不把历史现场数量写成固定菜单。角色正文、权限、Hooks、软链接内置 Skill 和编排职责保持。

公共入口与完整键位说明见 [README](../../README.md)：

```bash
awf-cli --version
awf-cli models --platform codex --project .
awf-cli roles --platform codex --global
awf-cli set --global --platform codex --role xy-backend --effort high
awf-cli set --project . --platform codex --role xy-backend --reset effort
awf-cli tui --project .
```

## 批准依据与必要证据

- 批准依据: 用户在前序三项独立审计缺陷及集中修正建议明确后回复“开始修复”，授权当前普通本地Claude来源修正、必要回归和最终本地提交。单一fresh／handoff_only后端作者负责生产和测试，PM只协调及维护主题／内部记录／Git，唯一新实施Reviewer独立验收。保持既有2.1工作流、功能／布局／键位／CLI合同、Skill软链接、旧任务pin和项目资料，无新功能或旧版兼容。
- 验收证据: 唯一Reviewer /root/claude_source_qa 沿同一installed-code-review-skill完成初审与F-QA-01／02 delta，正式PASS。qa-handoff.json原31962字节，SHA256 85ad0d9ef31eb41d2978d21248c479dfadf3084b7256aa26f45c0a83344527da，绑定当前QA包5fb7f1961bb4a01553de95c0d030cbb97649fd93c2a7539a23d92eb8b7e0ea6d；PM正式validate退出0／valid，6路径与28工程规则闭合，无设计变化。执行QA源图qa-source-graph.json SHA036580e1af2e6168e4ebe58b5098b343397b69a4bb90db2a9b425bbb1069123c保全，原执行包不重导或重绑。
- 冻结范围: base commit d331f81ea8cd7ed52515a8611efc6880678589f9，QA候选为真实Git tree295186ff19c7843d1c3ca25326fe4012da40a2ae；request.patch103480字节，SHA0600244f08dc04f71da3cc2dcc6de5fc3cc6be7ed9a957928938f6466ecb1eb9，scope.json SHA31ce247ccc4311e6ce35e5f11228bf5a823b33bc0354f8c40c703d43a1e80872。source6／external5／artifacts13实际matched，其他5条外部修改排除。QA后仅本稿及同名HTML作完成态投影，4条生产／测试路径保持QA字节。
- 作者与初次验证: backend-handoff.json SHA f24902e3039136f34256e721eb52de49ef96b362a030b0037942205f283b6ccd，绑定返工backend-task.json SHA1134759aaaff1e6d19b68942adabf00991a07b5f1778ac937b74b9108fcb8738。fix.log完整78162字节，SHAe4516c44bb2d9c936b680e12e4c2ec85d4ac7ac945107ed10d6fc69d75a20452。最初3目录节点在未修源有7项行为失败exit1；修后目录首绿，App fixture覆盖受管Hooks导致真实安全拒绝，修正fixture保留Hooks后App通过0／7.235秒。路由规范化后12个必要消费者通过0／10.699秒，含既有目录、4个controls和跨平台偏好保全；仅补App预览后文件env换源的确认时序后，该节点0／7.565秒。其余有效结论按具体输入复用。
- 有界返工与资源: 初审qa-handoff-initial.json原37999字节SHAb674d466027a223194c0f213e92e7417c4c721154462a86d8b4440e6322e1e78、初审包／源图／scope／patch及作者交接原件均保全。新2节点首轮fixture缺project，完整13失败保留但不计服务红；只补真实目录后，同一初审生产源2节点11子场景行为红exit1，证实SDK换源错误放行及非生效region错误拒绝。修复后仅新2、旧route与原真实App共4节点一次通过0／7.861秒，SDK预览后换源确认apply拒绝；没有放松守卫或重跑旧12／24／PTY／中央／npm整组。原fix.log前25345字节SHA95b7762a99f5b4706d6ae30a3b6185038ae922239dd828f9ca844635aae4c3a9严格保持。executor shutdown／wait、子进程wait、临时项目／HOME／state fixture清理完成，native启动0。
- 主源与验收边界: [Claude环境变量](https://code.claude.com/docs/en/env-vars)、[菜单作用范围](https://code.claude.com/docs/en/settings-reference#modelpicker)、[AWS端点优先级](https://docs.aws.amazon.com/sdkref/latest/guide/feature-ss-endpoints.html#precedence-of-settings)、[Bedrock配置](https://code.claude.com/docs/en/amazon-bedrock#3-configure-claude-code)、[Vertex位置](https://code.claude.com/docs/en/google-vertex-ai#region-configuration)及[官方changelog](https://code.claude.com/docs/en/changelog)已按相关字段核对；2.0.71直接确认显式Bedrock端点用于token counting和profile listing。仅验证普通本地投影与真实工具消费者，组织策略／--settings／Desktop／runner／运行中会话及实际账户模型访问保持未核。不宣称全仓一次全绿；旧稳定性／真实PTY／可访问性及未受影响三平台结论复用自8d26540基线。
- 恢复与文档: 完整批准MD／HTML、作者原件、所有失败／成功日志、原生QA字节和补丁保留在本请求scratch，可用下方现有命令定位。PROJECT／STANDARDS在source-pack中实际不存在，不创建空索引；本主题仅执行required生命周期解析、实际链接与同名HTML freshness。模板memory.project_id与当前provider缺少可验证严格项目过滤，未调用recall／save；具有长期价值的有效来源／端点遮蔽／旧授权事实已原位写入本主题，不新增报告或替代notes。

```bash
bash lib/python_runtime.sh -B -X utf8 lib/task_graph_cli.py scratch --root . --request-id fix-claude-catalog-sources-20261106
```
