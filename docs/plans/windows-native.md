# 原生 Windows 11 x64 适配与验收

- 主题 ID: `windows-native`
- 阶段: `active`
- 模块: `.`
- 任务等级: `Full`
- 已验收版本: `none`

## 目标与范围

完成当前中央运行时在原生 Windows 11 x64 上的入口、文件事务、Skill 软链接、进程管理与现有 TUI 适配，并取得可复现的原生验收证据。当前公开 2.1.3 仍不支持原生 Windows 安装，本计划不把候选工作或模拟测试当作已交付支持。

用户已明确“先完成原生windows 的适配验收”，选择 Windows 11 x64，并确认有可运行验收脚本的电脑。2026-11-09 曾暂停本主题，随后在[持续接单整合升级](continuous-pm.md)中明确恢复，要求完成后发布新版本并升级本机。该最新授权覆盖适配、必要职责重构、独立 QA、最终发布与本机升级；不制作 EXE/MSI、WinGet、npm/npx，不改变业务项目的独立配置、停用或锁版选择。

## 需求与验收

1. 无 Bash 的原生 Python/PowerShell 7+（pwsh）/cmd 入口可执行 CLI；Windows PowerShell 5.1 不在目标范围，不新增该兼容分支；现有解释器显式无效时拒绝，不静默下载运行时、调整全局 PATH、profile 或 ExecutionPolicy。
2. 本地 NTFS 上以真实句柄和 ChangeTime 验证身份；私有性由 ACL/owner 证明。保全原 DACL/继承策略、用户后续保存及原 inode/file ID，不跳过 POSIX mode 判断来伪装 Windows 安全。
3. 受管 Skill 仍只指向已验证中央核心同名 Skill；实现锚定创建、精确 tag/target 读取、排他移动、身份条件删除和恢复。普通未知 reparse/junction/多硬链、远程卷与不支持能力继续拒绝。
4. 保留 current/follow/pinned、三字段任务 pin、控制协议、全局与项目模型逐字段继承、条件补偿/中断恢复、旧任务资源读取和生命周期保活。普通记录4MiB及独立marker预算不升，不新增旧自包含兼容。
5. 捕获进程、helper和Hook使用可证明的Windows Job生命周期；超时/取消/外层终止后核对后代收尾，统一端到端预算，保留原stdin/stdout字节与退出语义。
6. 沿用已确认的curses框线、分区、Tab/左右焦点、预览、保存和取消；在真实ConPTY验收中文/组合字符、键位、缩放、单色/颜色、Ctrl+C和终端恢复，不以静态Screen或POSIX PTY冒充。
7. 单一Python测试清单供Bash与原生Windows入口共用。真实Windows CI、Win11 x64脚本及桌面补证分别记录；Server运行器不等于Win11桌面。选定必验节点不得以全skip当通过。
8. 保留主工作区五处原有修改、业务资料和偏好；所有破坏/竞态测试仅任务自有临时state/host-home/项目，完整日志保留。所有必要实现和复杂安全边界加入详细中文注释，机器工作流指令保持英文。

## 方案与原型关联

采用现有Python服务内核与平台适配层。CLI/TUI→业务事务→平台原语的依赖方向保持；安全快照、权限、发布和链接语义集中在负责层，避免业务调用点分散增加Windows例外。

TUI为UI-Conformance：design_delta为none，复用manager/tui.py的App.draw/run及tui_support.py的Layout/Theme/TextInput/draw_frame作为冻结生产基线，工程与设计规范均适用。本轮没有新的视觉或交互选择，不创建原型或修改设计标准；实际UI及可访问性证据仍需独立QA。

实施职责：原生探针/测试入口 → 文件系统原语与进程后端 → 中央库/事务/薄桥接入 → TUI/原生整体验收/使用说明 → 单一独立QA。后续验证入口由独立写者伴随库/整体阶段接入，始终维护同一个Python清单；已完成探针检查点不随下游验证改写。下游仅在前置接口与证据冻结后开始。所有生产写者为独立交接的xy-backend实例，规划分析不复用为实施实例。

首先在真实Windows记录目录flush、创建软链权限、ACL、ChangeTime、本地卷、句柄移动/删除等能力。调用成功不等于已证明耐断电；若现有持久化假设不成立，先记录真实错误和可验证方案，不静默删除屏障或虚报支持。

## 当前进展与恢复入口

基线 main 为1235951，公开和本机版本仍为2.1.3。实现使用独立职责工作树和精简任务包，原用户资料、主目录五处 dirty、未跟踪交接和业务项目保持。用户已授权完成必要验收与独立 QA 后发布、升级，无需重复请求同一授权；此前暂停的 Windows 工作已由本轮明确恢复，npm/npx 渠道不恢复。

真实 Server 2025 x64/NTFS 探针已证明 PowerShell7+ 薄入口、目录 flush、Skill 软链与关键 Win32 API 在该环境的实际行为；ChangeTime 不能单独作为充分竞争守卫。后续使用完整身份与 ACL 事实，目录锚定、条件发布、创建句柄归属及原 Job/IOCP 收尾。探针和分批失败/修复的原始报告保留，既不冒充 Win11 普通用户，也不宣称已证明耐断电。

中央消费者已真实完成核心导入、激活、三平台项目安装、薄桥与原 pin helpers、Skill 中央唯一来源软链、Hook 和偏好操作。记录职责重构保留完整 before 恢复正文，after 缩为严格条件守卫，能力选择覆盖所有相关固定 reader；原4MiB、超限零写、pending/旧 reader 保护不变。公开 add/use 后再执行旧 reader 新任务、长短根大记录与生命周期消费者已在 Mac 通过，不推断原生整体通过。

TUI沿用已确认布局，实际输入、Win32最终屏幕和ConPTY进程生命周期共同取证。Unicode/组合字符、resize、Ctrl+C和终端恢复已有真实通过记录；项目与全局保存预览仍须完整复验。后台预览只复用既有单作业，捕获范围、来源和 expected，保留草稿、取消和提交重验；不改设计，不放宽原超时预算。

当前唯一原生清单已收拢为9组件119方法，由 scripts/test_workflow.py 派生聚合、矩阵及范围描述；PR/发行只接受包含2项提升NTFS专项的full Windows gate，原生skip、缺组、取消或未执行都拒绝。普通desktop从同一registry派生117方法，明确排除提升2项，所选仍zeroSkip，不按当前权限自动降级。最新旧106项完整运行42647140927（232f007，实际 merge9840bcac且树相同）整体失败：库41含stage/ACL、瞬时及嵌套Job全部通过，入口6、边界3、脚本3通过；ConPTY Ctrl定向wait超时，另外7项通过；TUI两预览持续忙态超30秒，Unicode项通过；准入跨 pin 领取超60秒，另40项通过。中央在1720.610秒完成回滚，但后续补偿未在30分钟job内验完，不记完整PASS。

Ctrl定向夹具的就绪合同、旧PTY等待和收据ID选择已修正审查，尚未新原生结果。42650533280排队时被取消，避免相同生产代码重复运行已知失败。中央公共读取重构在Mac实测preview单pin12scan→1、双pin23→2，fresh双pin claim从28经A去重21降到8scan/pub1；原record/pin、成员复核、退出完整尾检和发布前检查保持，不把计数当Windows时延证明。

根身份Important已由同一Reviewer代码复核闭合并运输：租约、session/单读/批读、runner三根/reader及模块来源统一使用保留大小写的绝对字面键，完整core字段与原守卫保留。17个有效红测子边界修后通过，14项精准消费者通过。Store/Records/词法节点已精确登记，runner2继承现有Skill软链资格；RolePreferences仍仅POSIX CI。独立NTFS类的2项仅Server/elevated，本地NTFS/fsutil作用于自有空目录，无Node/curses/WSL/软链前置；生产不设置flag，Mac只编译未运行。

资格/describe/脚本增量已完成原Reviewer阶段审查并运输，下一步运行完整同候选门禁。用户Win11 x64电脑可运行脚本，已要求先整体开发；稳定候选后提供固定SHA与可审阅的PowerShell7+入口。脚本保存scope.json及acceptance.json，成功status为SCOPED_PASS、scope为windows11-client-ordinary、full_registry_executed=false，实际selected117/excluded2来自同一registry；描述只收集，不算执行通过。普通用户入口保留原CPython/x64/curses版本检查和prefix记录，不新增已装wheel哈希或私有venv准入；requirements锁哈希在CI准备阶段验证。当前新119项Server门禁、Win11桌面与最终统一QA均未完成，发布和本机升级未执行。

原生探针、旧失败、实际修复与源审记录分别保存在 native-windows-20261109、upgrade-214-20261109 请求暂存区和 Git历史。只保留必要源码/当前主题计划，不把阶段清单、模拟、部分通过或后续取消改写为完整验收。

## 验收结果与当前已交付行为

本主题尚无已验收基线；公开2.1.3及已绑定业务项目保持原状。不得将未来计划、模拟结果、部分节点或Windows Server CI当作Windows11桌面全验收。

## 批准依据与必要证据

- 批准依据: 用户要求原生 Windows11 x64/PowerShell7+ 适配，曾暂停后已明确恢复，并授权完成后发布新版本和升级本机；补充要求必要重构、健壮易维护和依据三平台最新官方规范。生产交新子代理、独立 QA、保留资料和现有修复；布局与流程已定版，当前仅原生平台适配。
- 验收证据: 原语、入口与进程消费者已有对应的真实原生方法证据；ConPTY 八项通过。42614154168 证明真实中央 Hook 通过、偏好 reset 仍失败，并取得两项脚本/API 诊断通过。生产 TUI、中央完整生命周期、最终统一门禁、独立 QA 及 Win11 普通用户桌面尚未验收。后续仅记录真实命令/环境/输出/退出码、原始失败和相应修复，完整证据不以摘要替代。
