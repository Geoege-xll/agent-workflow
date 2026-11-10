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

目标保持 Windows11 x64、普通用户 PowerShell7+ 与 Python3.11+。CLI／TUI 共用中央服务，三个平台的入口与内置 Skill 归项目并通过链接使用；不新增兼容升级通道、EXE／MSI／WinGet 或立项入口。既有 curses 布局、真实 ConPTY 与 UI／可访问性验收范围保持。


中央读取沿用同根、同 pin 的完整操作级 reader；写入另做 fresh 核对。偏好保存通过明确的纯准备接口与完整 OwnershipSources 固定来源，保留记录、journal retained、目录、完整 Node 与画像核验，再进入原发布、验证和条件补偿。

Windows 文件创建、首写和发布集中在 lib/windows_fs.py。create_regular_stage／seal_regular_stage／write_regular_if_unchanged 保留同一不可继承、share0 HANDLE、完整 owner／DACL／control、有序 ACE、mode／attrs 与源身份守卫；仅在必要的受保护 SD 初始化后完整重读相等才接受。公共写者共用发布边界，Records 的 Windows helper 与 bare／package façade 使用同一模块命名空间；三参数接口、finish → fresh CAS → 最后结算来源顺序保持，不做全局模块 alias。默认 4MiB、明确入口最高 8MiB 及原 marker／core／GC 预算保持。

唯一 registry 当前实际收集为 10 组件／156 方法；Win11 普通用户范围 153 方法，明确排除提升专项 3 方法，所选方法严格拒绝 skip／未执行。完整运行 [42762760967](https://github.com/Geoege-xll/agent-workflow/actions/runs/42762760967) 对应候选 14bc952，实际 PR 合并 e688d54 与候选树相同：macOS／Linux CI、Windows 9／10 组件通过，包括中央完整生命周期、边界 12 项、准入结算 41 项、原语库 75 项和 owner-only 负控。TUI 的两个首次保存预览超 30 秒，尚未进入 apply／refresh；Unicode 方法通过，整体门禁仍失败。

新增全调用阶段钩子可能扰动计时，尚未量化因果。测试观察器现改为显式 opt-in：run_observed 的 phase_profile 与 PhaseProfile.enabled 默认 False，关闭时不绑定或触碰 profiler，证据明确 disabled；只有显式 True 才记录有界阶段数据。原启用合同、读屏、worker 栈、IPC、三个真实 TUI 方法、屏幕断言和 30 秒预算保持；产品与后端无此增量。原唯一 Reviewer 已准许精确两测试文件运输；统一原 CLI 两项 0.042 秒 exit0，已有 Python3.11／3.14 两项各通过，registry 数量保持。默认无 hook 对照 [42767872406](https://github.com/Geoege-xll/agent-workflow/actions/runs/42767872406) 已结束：Mac/Linux 与 Windows9/10组件通过，TUI仅项目保存结果30.031秒超时；预览9.172秒两次与全局保存21.313／21.735秒通过，54个留存frame明确disabled，项目final缺失不补断言。末采样仍在refresh的load_context函数体，无法拆分整段30秒，不据此删校验。

已证实并收束一处遍历职责重复：directory分支未消费的stat由_child_directory的原stat/open/身份核对唯一负责，文件fresh、完整metadata/ACL/member/ancestor与reader尾验不变。真实D12/F15夹具source验证stat83→71、reader首尾102→78；新增回归先红后绿，原四安全节点全过。原Reviewer已准许精确runtime_store.py／tests_runtime_store.py及唯一登记运输；统一CLI新1项0.020秒exit0，实际matrix154/desktop151排3。这仅证明调用数减少，Windows时延与原30秒保存仍待同源完整复验，未引入completion新协议、缓存、UI或SDK改动。

目录优化完整运行[42772624629](https://github.com/Geoege-xll/agent-workflow/actions/runs/42772624629)已结束：Mac/Linux与Windows9/10组件通过，五次模型／推理保存、切换和停用通过；唯一启用确认后30秒未结算，operation已返回，末采样在refresh的状态查询／PowerShell fresh探针等待，不能归因整段30秒。后续仅给App.apply_project.refresh加既有父read_operation，完全位于writer之后，跨pin独立，探针和全部业务来源／安全／尾验保持，无新后端API。原Reviewer已准许精确生产6行、两App回归及唯一登记运输；真实同pin2scan/4verify→1/2，双pin原主/副/主/主4/8→2/4，数据和磁盘bytes相等。三种真实tail漂移拒交Context且保实际启用/journal/草稿来源、阻止重提，下一刷新fresh；统一CLI两项7.269秒OK。新两方法沿现TUI组件curses前置，原3真实UI方法不变，当前TUI共5方法；原预算Windows完整复验与最终QA仍待。

实现、原始失败、完整日志、冻结源及同一 Reviewer 的审查记录保存在请求 upgrade-214-20261109 临时区和 Git 历史；计划只保留当前契约与恢复入口。临时诊断 workflow 从未进入候选或发行载荷，npm／npx 不恢复。用户已明确先完成开发和 CI；Win11 普通用户真机暂缓，最终统一 QA 与正式发布仍待，Server CI 不提升为 Win11 桌面验收。

## 验收结果与当前已交付行为

本主题尚无Windows已验收基线；公开渠道仍为2.1.3，本机及三个跟随项目已按最新授权先行使用2.1.4候选中央核心，项目资料/启停选择/模型偏好保留。该Mac本机更新不等于Windows验收；不得将未来计划、模拟结果、部分节点或Windows Server CI当作Windows11桌面全验收。

## 批准依据与必要证据

- 批准依据: 用户要求原生 Windows11 x64/PowerShell7+ 适配，曾暂停后已明确恢复，并授权完成后发布新版本和升级本机；补充要求必要重构、健壮易维护和依据三平台最新官方规范。生产交新子代理、独立 QA、保留资料和现有修复；布局与流程已定版，当前仅原生平台适配。
- 验收证据: 原始运行、修复与同一 Reviewer 的源审分别保留，最新目录优化完整结果见42772624629（Mac/Linux与Windows9/10组件通过，保存及停用已过，仅启用后的刷新超时）。后置只读共享后的原预算完整复验、Win11普通用户桌面及最终QA尚待；准确命令、环境、stdout/stderr与退出码以原日志为准，不以计划、模拟、部分通过或插桩数据替代整体验收。
