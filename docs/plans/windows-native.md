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

基线main为1235951，公开仍为2.1.3，本机已按最新授权先行升级为2.1.4候选；Windows尚未最终验收。独立职责工作树保留主目录五处dirty、交接及业务资料。用户已授权必要验收与独立QA后发布、升级；此前暂停的Windows已由本轮明确恢复，npm/npx不恢复。

真实Server2025 x64/NTFS探针和消费者已取得目录flush、完整身份/ACL、条件发布、创建句柄归属、中央Skill软链与Job/ConPTY收尾证据；ChangeTime不能单独证明安全，未宣称耐断电或Win11普通用户等价。记录before保完整恢复正文，after只存严格条件守卫，能力选择保护所有相关固定reader，原4MiB/超限零写/pending及旧reader保护保持。

完整运行42699711396（ec0e8f3，实际merge 63076e9且树相同）已结束失败。macOS/Linux CI成功，平台条件skip不当Windows证据。Windows121项中库48、入口6、ConPTY8、诊断4、准入41、提升NTFS2及中央完整1项通过；完整生命周期、原inode补偿与并发保存保留均完成。原CRLF能力夹具及Unicode/cleanup已经原生复验通过，整轮仍因两个组件失败而未通过。

TUI五次模型/推理保存实际成功，项目保存约19.8秒、两次全局保存约13.5秒，取消与停用也完成；剩余一个body失败为随后项目启用预览30秒未结束。既有observer实际捕获executor停在preview重复核心校验栈，未见refresh或worker异常。三个纯preview入口的操作级完整只读范围和两个精准回归已同Reviewer接受并整合，Mac实际同pin1scan/2verify、双pin2/4；显式source双inspect保留，apply仍fresh。同Reviewer已完成代码阶段复核，等待Windows30秒实际复验，不增加预算或改变curses布局。

中央边界8项的10个错误同在普通既有config.toml的setup：同父stage精确权限复制后source control=0x8004、target=0x8404，有序ACE由3变4，故障注入尚未执行。当前Tree无私有ACL准入，不能强改fixture绕过真实外部配置。同Reviewer接受的最小原生节点与隔离单job已运行42708668152：单方法0.034秒ERROR，SetSecurityInfo实际return0；source owner BA、private stage owner LA，父CREATOR OWNER继承重算新增LA全权ACE，source及父security稳定。完整stage见证还包含owner，不能仅忽略AI/ACE差异。创建时源SD实验42712087273随后实际1方法0.022秒通过：owner BA、control8004、有序ACE及完整security精确保留，READ/WRITE/DELETE重开均真实错误32，seal与关闭首读七标量相同。create+seal两原语及存活creator绑定契约已实现；同Reviewer确认公共replace遗漏后，统一完整快照发布helper已实现并完成代码阶段复核，覆盖项目ID、Claude指令、Codex独立合并、任务记录及Hook原读接缝。原记录三参数发布接口、lock/finish/freshCAS/最后结算来源顺序保留，原有空stage登记及完整ready见证不改。中央/原生/AGY调用侧已代码层闭合两Important，14文件原语/发布与7文件消费者均已完成同一Reviewer代码阶段复核；消费者实际合入真实依赖后5项精准便携测试一次0.735秒通过，真实Windows生产路径仍待执行证明。原始失败保留，临时workflow不进入发行，精确ACL、sharing与rollback合同保持。

保存阶段5生产+2测试已完成同一Reviewer审查并运输：只合并显式纯准备，封口后按完整OwnershipSources固定inventory fresh核对，再走原written/publish/verify与补偿。record/journal retained遗漏已用正式producer真实故障、条件补偿与外部编辑保留闭合；稳定missing历史保留。目录负控区分真实Windows5/32内核阻止与实际替换后的guard拒绝，退出后真实rename证句柄结清，不放宽sharing。Mac同源project apply4scan+refresh1、global两次各4+0；实际产物/journal保持，仍需Windows实测。

此前完整门禁的唯一原生registry实际收集9组件121方法（48/6/1/8/8/3/4/41/2）；本轮新增生产原语、中央/AGY与独立owner权限节点后，最终数量必须从同一登记重新实际收集。PR/发行仅接受Server full，任何selected skip/缺组/取消/未执行均拒。普通desktop明确排除提升NTFS2与owner权限1共3项，不按权限自动降级；两个新中央guard节点进ordinary boundaries，RolePrefs两个新回归仅POSIX CI，避免顶层pty/termios/curses依赖冒充原生。提升flag只改测试自有空目录，生产不设置、不新增用户提权/WSL要求。

稳定候选后向用户提供固定SHA、可审阅的PowerShell7+入口；用户Win11机器可运行但已要求先整体开发。脚本保存scope.json及acceptance.json，成功SCOPED_PASS、scope=windows11-client-ordinary、full_registry_executed=false，selected/excluded实际数量来自同registry；补入新节点后重新派生，describe仅收集不是执行PASS。脚本保原CPython/x64/curses版本与prefix记录，锁哈希由CI安装准备验证，不新增私有venv或已装wheel哈希准入。用户2026-11-10最新授权将本机更新提前：macOS完整检查和真实PTY/TUI通过后先安装2.1.4候选程序与中央current，再继续真实Windows。完整同候选Server门禁、Win11桌面及最终统一QA完成后才正式发布GitHub/Tap；本机候选安装已完成，Mac285项340.176秒exit0（5项Windows-only skip不作原生证明）、真实PTY2均通过并获同一Reviewer本机候选许可；来源6eac3ea/归档7c516caf…8259。Homebrew实际程序2.1.4与中央current 1b9b2b54738c92b27ff64caf1058b854e1daef378a1f32c0c4e7edfbc305da3e已由原CLI导入/预览/激活exit0，三个登记项目healthy/follow、54软链及模型偏好保持。Windows验收及正式发布仍待。

探针、原始失败、实际修复及源审分别保存在native-windows-20261109、upgrade-214-20261109暂存区和Git历史。当前主题仅保留必要架构与恢复信息，不以部分节点、模拟或取消改写整体验收。

原生组件42736740442首次65方法69.522秒/9errors后，取证轮42739662508（50518ad，与I cfac28e生产树相同）实际65方法60.182秒/6errors、零skip。公开异常3种真实资源fault已通过；custom五子例的owner、raw ACL、有序ACE、mode0666和attrs32全同，源control9404而初始stage9004，仅AUTO_INHERITED缺失，完整安全守卫正确拒绝。原FS按官方SetSecurityInfo HANDLE规范集中实现首写前精确初始化，保其余完整守卫，仍待冻结/原QA/真实Windows。余下Budget错误所在共享parser合法CRLF缺陷已真实safe-sync红绿验证并获原QA接受；N1已将新六精准合同加入唯一registry，当前10组件149方法、desktop146排3，后续新native方法继续按实际清单派生。携CRLF修复的71项组件42743528209（2ce2503）已实际55.568秒/5errors、零skip：大root预算与新六合同真实Windows通过，仅custom五子例仍拒绝；原始失败、30条SD事件与完整artifact保留在请求暂存区。

SDK完整修复2485cc4已按原soleQA最终许可（新patch8a4875，旧910be2许可撤回）精确合入候选8b9ca0c。独立原生库运行42750791601/18d3131实际72方法72.253秒全部OK、零skip、test_exit_code=0；五写者source/初始化stage完整SD均9404且owner/ACL/ACE/security全等，原源身份/正文不变，同一不可继承HANDLE，三种共享重开均错误32。原probe EOF Important已用64bit位置保存/0起读/finally恢复及真实读取链回归闭合。隔离YAML因延后stdout JSON使末尾摘要断言报错，job仍failure并保留原流，不重标绿；生产gate原样传原CLI退出码，不受此临时包装器影响。临时workflow不进入候选/main/归档，不为临时汇总器再改生产。接下来执行同一候选完整Mac/Linux与10组件150项Server gate、Win11普通桌面147项（排3）及最终独立QA。用户已实测CLI可用，并追加只读抽查mt-shop今天最新会话，原验证owner正在有限样本取证，不能等同App GUI验收。

## 验收结果与当前已交付行为

本主题尚无Windows已验收基线；公开渠道仍为2.1.3，本机及三个跟随项目已按最新授权先行使用2.1.4候选中央核心，项目资料/启停选择/模型偏好保留。该Mac本机更新不等于Windows验收；不得将未来计划、模拟结果、部分节点或Windows Server CI当作Windows11桌面全验收。

## 批准依据与必要证据

- 批准依据: 用户要求原生 Windows11 x64/PowerShell7+ 适配，曾暂停后已明确恢复，并授权完成后发布新版本和升级本机；补充要求必要重构、健壮易维护和依据三平台最新官方规范。生产交新子代理、独立 QA、保留资料和现有修复；布局与流程已定版，当前仅原生平台适配。
- 验收证据: 原语、入口与进程消费者已有对应的真实原生方法证据；ConPTY 八项通过。42614154168 证明真实中央 Hook 通过、偏好 reset 仍失败，并取得两项脚本/API 诊断通过。生产 TUI、中央完整生命周期、最终统一门禁、独立 QA 及 Win11 普通用户桌面尚未验收。后续仅记录真实命令/环境/输出/退出码、原始失败和相应修复，完整证据不以摘要替代。
