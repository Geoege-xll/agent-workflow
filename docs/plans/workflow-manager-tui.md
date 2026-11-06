# 工作流管理工具

- 主题 ID: `PLAN-WORKFLOW-MANAGER`
- 阶段: `completed`
- 模块: `.`
- 任务等级: `Full`
- 已验收版本: `local-2.1.0-stability-41eddbc3b5ee`

## 目标与范围

本轮对既有2.1工作流管理实现进行适当内部重构。功能、TUI布局与键位、CLI参数和JSON形状、项目资料、既定PM委派和独立QA流程作为固定合同。来源获取、草稿授权、后台结算和私有状态发布现有清楚的职责与可重复验证边界。

范围限于三包：来源与编辑上下文、TUI会话状态与作业结算、中央私有记录边界。Codex全局保存问题是首要验收用例。保留全局／项目按字段来源、reset与显式inherit区别、预览确认、失败条件补偿、Skill源包及三平台软链接、不可变核心与旧任务pin。

不新增功能或改变业务工作流；不重写store、薄桥、pin、项目inode发布及模型事务；不做老版兼容迁移、核心自动切版、真实账户写入、三业务项目同步或远端发行。外部七条未提交修改保持原归属，不混入本轮交付。用户已明确回复“开始实施”，批准上述三包及固定功能边界；原已验收基线和批准输入已保全，本稿现投影本轮实际验收结果。

## 需求与验收

| 需求 | 完成标准 |
|---|---|
| REQ-STAB-001 功能固定 | CLI/TUI现有参数、结果形状、布局、键位、角色职责、项目启停／选版／恢复流程保持；内部抽取不引入第二套业务逻辑 |
| REQ-STAB-002 编辑快照 | 一次编辑的范围、角色值／来源／跟随值、目录和目标集合由偏好服务提供完整上下文；正常原生目录连续获取不得自我废弃；真正provider、auth元数据、能力、登记集合或发布后来源变化仍拒绝旧授权；刷新不静默重绑旧草稿 |
| REQ-STAB-003 TUI生命周期 | 草稿及其前像作为同一生命周期单元，显示缓存与授权状态分开；绘制只读已取回投影，不读易失败的实时配置或启动native；弹层期间外部配置异常不退出工作台，草稿可保留、取消、刷新或丢弃 |
| REQ-STAB-004 作业结算 | 每个后台作业有明确作用范围、返回入口和结算结果；区分写入失败与写入已成功但列表刷新失败；按所有受影响范围失效显示缓存，保留未应用草稿，不复活旧确认页，不重复提交；取消等待真实结算 |
| REQ-STAB-005 中央私有记录 | 同一内部边界先完整校验binding／journal／retained，再交动作编排；坏结构稳定拒绝且诊断不含正文；进程在私有发布中途退出后不得把不确定状态当作从未管理；精确归属恢复或安全拒绝，不猜测随机残留、不删除未知保存 |
| REQ-STAB-006 验证与保全 | 隔离假Codex真实stdio、双项目保存、来源变更、弹层与作业失败、真实进程中断、CLI／收据／pin和离线载荷依赖均有实际证据；必要集成PTY及唯一独立QA；复用未失效结论，不以显式JSON或mock替代原生来源合同；外部修改与业务资料保留 |

## 方案与原型关联

采用UI-Conformance：零设计变化，视觉与交互依据为当前已验收行为和现有布局；不再制作、同步或审查原型。三包按职责交fresh／handoff_only生产实例，生产实例不复制PM或兄弟会话。各包在同一代码树按依赖顺序完成并冻结，避免共享测试夹具或服务接口交叉修改；本轮不是多个独立功能，不为并行数创建额外worktree。

| 包 | 明确职责与文件 | 依赖与完成边界 |
|---|---|---|
| P1 来源与编辑上下文 | manager/catalog.py、manager/model_preferences.py、manager/cli.py及tests/test_role_preferences.py、tests/test_workflow_manager.py。目录层明确权威来源、原生结果与共享缓存提示；偏好服务拥有批次快照、一致性检查和编辑投影；CLI仅必要适配，不自取计划内部target | 首先实施。保留既有roles/view/preview/apply等入口及CLI形状；不新增持久化缓存，不简单删除identity校验或事后盲绑旧结果。冻结供P2消费的上下文、失效含义与保留旧授权规则 |
| P2 TUI会话与作业 | manager/tui.py、新manager/tui_state.py、tests/test_manager_tui.py。状态模块只管理范围、草稿／前像、显示失效和一次作业的结算；App保留输入路由、视图与渲染，继续调用原服务 | 依赖P1合同冻结；所有入口按生命周期统一收尾。保留tui_support布局／字符格，不引入通用状态机框架或大量控制器，不把业务写入移进状态模块 |
| P3 中央私有记录 | manager/runtime_service.py、新manager/runtime_state.py、新tests/test_runtime_state.py、tests/test_central_project.py；tests/test_workflow_manager.py仅最小核心依赖清单；packaging/build_npm_release.py和tests/test_npm_packaging.py仅必要载荷依赖闭合 | P1/P2之后实施并验证，避免共享夹具并发写入。runtime_service保留动作编排；现有读取入口可转调内部记录边界。先固定崩溃验收再选择发布实现，不用裸replace取消并发守卫，不统一apply/repair或模型收据的不同结算语义 |

三包均保留preferences→registry/model→install→central-state锁序、完整RestorePlan类型、精确前像、旧inode及条件补偿。P3新模块属于真正核心依赖，必须同时纳入最小测试核心与npm精确白名单，不能仅在源码树可导入就认为安装态可用。

验证顺序为每包最小回归、真实直接消费者、三包整合后必要集成、唯一QA。首次必要通过后不为提交重跑未失效测试；发生修复仅重跑受影响结论。实际命令与完整日志进入同一请求证据位置，用户反馈仅说明有意义结果。

| 包／阶段 | 验证内容与现有入口 |
|---|---|
| P1 | 将已完成的稳定identity／按scope刷新identity对照纳入长期原生stdio回归；补获取中与发布后真正换源拒绝、旧草稿授权不重绑。直接消费RolePreferencesTest，以及CatalogTest的native_snapshot_rechecks_sources_without_requery_or_auth_read、native_result_is_discarded_when_stable_sources_change_during_query、tui_failed_and_invalidated_native_catalog_recovers_only_on_editor_entry和TransactionTest的stale_source_draft_requires_reselection_before_preview等既有节点 |
| P2 | TuiTest覆盖完整状态路由；新增弹层打开后全局配置异常、重复绘制无来源IO、应用成功但刷新失败、全局失败多范围显示失效、回调失败作业清理。保留job_results_never_return_to_old_confirmation、tui_restore_confirmation_keeps_original_version_guard和tui_interrupt_waits_for_synchronous_central_settlement直接消费者 |
| P3 | 新runtime_state测试涵盖嵌套坏结构、精确前像、后续保存、描述符／锁释放；真实子进程在发布关键点退出，重启后读取／repair必须明确。复核CentralProjectTest现有failure_rolls_back_exact_outputs_and_never_enables、recovery_refuses_post_failure_edit、prepared_recovery_restores_machine_binding_after_process_exit、old_inode_later_save_is_retained_and_blocks_overwrite及model_receipt消费者；离线npm的real_source_allowlist_and_dependency_closure_excludes_executable_test_helpers核依赖，不下载或发布 |
| 整合 | 在最终候选上运行已失效的CLI／TUI／中央收据／pin关键消费者；现有ProjectTuiIntegrationTest真实PTY一次覆盖导航、全局／项目编辑保存、取消、启停、冲突与缩放；原生stdio覆盖补足PTY显式目录边界。随后唯一独立QA审完整组合范围、来源、故障与证据；不得以模型调用或Windows原生未执行的检查冒充通过 |

必要文档投影在唯一QA PASS后，原位更新本主题及同名HTML，保留当前已验事实到那时。不存在的PROJECT／STANDARDS不新建空索引；不新增重构报告、ADR或替代notes。PM只精确提交本轮已验代码和文档，不push/tag/release或替业务项目切核心。

## 当前进展与恢复入口

三包重构及最终组合验证已完成。来源与编辑上下文、TUI会话状态／作业结算、中央私有记录各有明确内部边界，CLI公共参数／JSON、TUI布局与键位、角色职责和核心pin合同保持。Codex全局保存已在真实App与按scope刷新identity的stdio假宿主中完成双项目落盘；真正provider换源后旧授权仍拒绝，显示刷新和重新取目录不会续期旧草稿。

中央私有记录已用真实进程固定中断边界，完整codec、精确恢复、后续保存保护和最小核心／npm依赖均有直接消费者证据。唯一独立QA初审发现F-001：两个裸fd取得后到stream接管前异常可泄漏；由原P3作者仅在记录模块和对应测试内修复，四真实fd故障子场景先红后绿，再以正常发布／晚保存／四真实退出检查受影响边界。同一Reviewer复核后正式PASS，无新增阻断。

当前无待重做实现或验收阻断。继续使用现有awf-cli与README入口；本轮没有切换三业务项目的核心版本或修改真实偏好。后续独立需求按新范围处理，不重放本轮已完成任务。下方描述当前已验收行为；前次布局与全局默认基线可从24d0059的本稿及原请求证据恢复。

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

- 批准依据: 用户明确要求对已基本定版的流程和TUI进行适当重构以获得稳定可靠版本，并回复“开始实施”。三包范围、固定功能／布局／键位／CLI合同、fresh／handoff_only生产委派与唯一独立QA均按该批准执行。采用UI-Conformance零设计变化，保留既有curses、软链接内置Skill、旧任务pin和项目资料，不新增立项入口或旧版兼容。
- 验收证据: 唯一Reviewer /root/stability_final_qa 使用同一installed-code-review-skill完成初审与F-001 delta，最终正式PASS。qa-handoff.json原102102字节，SHA256 713f4e21de869b1c03e5cb0c8154dc4510b11bfc4763d344dc1ad4501c6282b5，绑定当前QA包74eb13ae441be232a29e66a5c4431c1f50b746948ba7df554be0e03549663b2a；PM正式validate退出0／valid，16路径、28工程与23设计规则闭合，唯一F-001关闭。qa-source-graph.json SHA6d24ab03a7df37c6586c6282485add9c513fed47d52ce8b0aacde653dff96687，verify-ui-scope退出0／valid。
- 冻结范围: base commit24d0059caa6b11b00877db1bd2d45421a2f703df，QA候选为真实Git tree41eddbc3b5eeb7cb8e9fce0c73b1fd244e99183e；request.patch226581字节，SHAe36bf4c9b509cc564948825b8fe14b125244a85f342cf511361cc6ba9349fc1b，scope.json SHAccce1ab341d90596015d0f1f6771344bbfa13c8338847a68d02b6a46f17a1f2d。29原件绑定完整，7条外部修改排除。QA后仅本稿及同名HTML作普通完成态投影，生产字节保持，不重导或重绑原执行QA包。
- 来源与App证据: p1-handoff.json SHAae493eb543e0fd28040dcdfd1262304d43946357ef79562d9a58a288075e14fd，p1.log SHA0c008fe0c1ba20ae9388efcb87197ec2f5440f654eaf28ad58a8d15e07816a07。组件必要25节点的原fixture失败与定向修正完整保留，未重复已有成功集合。最终真实App导航／executor／stdio按scope刷新共享identity的单节点首次通过0／3.987秒，双项目模型与推理保存、零隐式native及真实provider换源旧授权拒绝均成立；9个自有native进程TERM／wait、executor和fixture关闭。原组件日志前36529字节严格保留。
- TUI与PTY证据: p2-handoff.json SHAb5ee1b58e15cf4fd8be73ecfd960d6408732e840490131ca8b7fa43d317688c8，p2.log SHA1d661b515b53cf463d417fedf884d400bd97c499326fd54cbc95b332eddcd9b1。48个必要组件节点分批验证及夹具修正证据保留，最终3个实际App来源／旧草稿消费者加唯一真实PTY共4节点通过0／27.032秒，18个稳定帧覆盖导航、全局／项目编辑、启停、取消、冲突与缩放；pid69365经q／wait退出0，fixture和fd关闭。p2-pty.raw SHA98c190a875c90f492a6aceae5ee0ff1cb4c3906542e0a054c02350c03fe8b412，cells SHAdc5d09b3bf12e8b5cbb735599c038fc883e38cb9648ed7b22682c1523ac15287；原日志前55422字节保持，返工复用有效UI／可访问性结论。
- 私有记录与返工证据: p3-handoff.json SHA865257f346cfb11aed37fa69b8d677b4db84c2bddcfb86180846e4612f56dac7，p3.log43625字节SHAa01994bf6c17cf3b76d79e1f06a2419f07bfbdb190d3f250f481a5bdd136963e。旧公开入口坏结构／真实中断红证、6个中央消费者与隔离-I npm真实载荷消费者成功均保留。初审qa-handoff-initial.json89827字节SHAf8dd94a75268201076b84c3144ae728deba4077efb49cbb9470dbc19766dead0及原包／源图／scope／patch保全。F-001仅改runtime_state和test_runtime_state：四子场景旧源红exit1，修复后真实fd均EBADF且EIO／KeyboardInterrupt按原类型传播，未知inode／marker保留安全拒绝；新故障节点、正常精确恢复、晚保存final_guard及四真实exit73节点合4项通过0／0.286秒，fd／锁／子进程／fixture关闭。原22954字节日志前缀严格保留，其他14源和7外部字节未变，不重跑P1／P2／PTY／中央／npm整组。
- 实际边界与恢复资料: 现有ParentsKit、TeachingAssistant、mt-shop机器binding／journal经新codec只读核对，均valid且检查前后一致，无安装、切版或账户写入。实际账户推理、屏幕阅读器认证和Windows原生运行未验，不宣称全仓一次全绿。完整批准输入、组件原件、失败／成功日志、PTY原流、QA原字节与补丁继续保留在本请求既有scratch中，可用下方现有命令定位；不新增报告、ADR、替代notes或空索引。PROJECT／STANDARDS在source-pack中实际不存在，本主题仅执行required解析、当前链接与HTML freshness核查，不制造全仓文档通过结论。

```bash
bash lib/python_runtime.sh -B -X utf8 lib/task_graph_cli.py scratch --root . --request-id fix-global-codex-save-20261106
```
