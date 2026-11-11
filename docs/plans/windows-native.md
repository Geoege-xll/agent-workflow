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

实施职责：原生探针/测试入口 → 文件系统原语与进程后端 → 中央库/事务/薄桥接入 → TUI/原生整体验收/使用说明 → 单一独立QA。后续验证入口由独立写者伴随库/整体阶段接入，始终维护同一个Python清单；已完成探针检查点不随下游验证改写。下游仅在前置接口与证据冻结后开始。所有生产写者按后端职责独立交接；源码仓开发使用支持无中央绑定的职责实例，已绑定业务项目使用xy-backend实例，规划分析不复用为实施实例。

首先在真实Windows记录目录flush、创建软链权限、ACL、ChangeTime、本地卷、句柄移动/删除等能力。调用成功不等于已证明耐断电；若现有持久化假设不成立，先记录真实错误和可验证方案，不静默删除屏障或虚报支持。

## 当前进展与恢复入口

目标保持 Windows11 x64、普通用户 PowerShell7+ 与 Python3.11+。CLI／TUI 共用中央服务，三个平台的入口与内置 Skill 归项目并通过链接使用；不新增兼容升级通道、EXE／MSI／WinGet 或立项入口。既有 curses 布局、真实 ConPTY 与 UI／可访问性验收范围保持。


中央读取沿用同根、同pin的操作级完整reader，写入另做fresh核对。偏好保存保留完整OwnershipSources、Node、目录、画像、journal及条件补偿。Windows创建、首写和发布集中在lib/windows_fs.py，同一不可继承share0 HANDLE在必要的精确SD初始化后完整重读，再允许payload／CRT转移；完整owner、DACL、control、有序ACE、身份和源守卫保持。Records与façade使用一致的bare／package模块命名空间；默认4MiB、明确入口最高8MiB及原marker／core／GC预算保持。

两处已审职责整理减少重复工作：directory未消费的stat由原子目录守卫唯一负责；App.apply_project的writer返回后，状态列表和选中Context共用父read_operation。跨pin独立、PowerShell fresh探针、完整来源／安全／退出尾验保持。真实App同pin2scan／4verify→1／2，双pin4／8→2／4，完整数据和私有夹具bytes相等；三个真实tail漂移拒交Context并保已完成写入、journal和旧草稿。调用数减少不等于时延已验收。

上轮冻结开发基线为 ccd8ba9e102d511b0a1740deea406a86d908e51c，tree 5b8aee01990578186b467ac2f185ae0bb261b27e。完整运行 [42799003531](https://github.com/Geoege-xll/agent-workflow/actions/runs/42799003531) 已通过 macOS、Linux 与 Windows Server 门禁；PR 合并 checkout 与候选同树。Windows 组件 10 个、实际方法 167 个；普通桌面范围排除提升专项 3 个，为 164 个。原 TUI 等待／屏幕判据问题已修复，动作响应、业务结算与进程回收仍是独立合同，不以防挂上限冒充性能指标。

该候选已完成开发与 CI 阶段的独立 QA；原始日志、观察帧、最终状态、可重复构建及消费证据位于请求 upgrade-214-20261109 的 candidate-ccd8ba9-* 记录。Windows Server 结果不替代 Win11 普通用户真机与 Codex App 人工观察。后续新增 curl 安装入口仅复用仍适用的证据，对新资产、下载与安装路径补齐原生验证；未通过真机前不宣称 Windows 已验收。

## 验收结果与当前已交付行为

本主题尚无Windows已验收基线；公开渠道仍为2.1.3，本机及三个跟随项目已按最新授权先行使用2.1.4候选中央核心，项目资料/启停选择/模型偏好保留。该Mac本机更新不等于Windows验收；不得将未来计划、模拟结果、部分节点或Windows Server CI当作Windows11桌面全验收。

## 批准依据与必要证据

- 批准依据: 用户要求原生 Windows11 x64/PowerShell7+ 适配，曾暂停后已明确恢复，并授权完成后发布新版本和升级本机；补充要求必要重构、健壮易维护和依据三平台最新官方规范。生产交新子代理、独立 QA、保留资料和现有修复；布局与流程已定版，当前仅原生平台适配。
- 验收证据: ccd8ba9 的开发与 CI 阶段见运行 42799003531；Win11 普通用户真机仍待。curl 新入口的验证必须绑定组合后的实际源码与资产，不能直接沿用旧候选成功。

## curl 下载入口补充（2026-11-11）

用户在下载方案讨论后明确“开始”，批准直接实施。沿用本主题，工程与只读独立 QA 继续，TUI 布局不变，无原型任务。

目标：Windows11 x64 普通用户 PowerShell7+ 通过 curl.exe 下载固定候选/稳定资产，使用现有 CPython3.11+ 与 Node20+，私有 venv，复用中央 runtime install/activate。无 npm/npx、WinGet、EXE、自动下载解释器、全局PATH/profile/ExecutionPolicy修改。

安装协议：独立确定性 pyz 包含同源最小SDK和 lib/install/windows_installer.py；PS执行已校验的同一字节而不重新信任路径。引擎入口 --archive PATH --archive-sha256 HEX --version X.Y.Z --install-root ABS [--state-dir ABS] [--host-home ABS] [--json]；引擎 main(argv=None)。默认程序目录 LOCALAPPDATA/AgentWorkflow，版本摘要目录 payload/venv，bin/awf-cli.ps1与cmd。独立核心状态仍用现有服务。venv在最终物理路径创建，禁迁移。

解压同一已校验流，拒绝逃逸/链接/特殊项/Windows名称别名/重复；每成员和总量设预算，逐项复用锚定SDK，不使用extractall。依赖按原requirements-windows.txt hash/binary锁；子进程复用现有Job/process所有者。

程序环境就绪→物理payload CLI runtime install→activate dry-run→activate→受管launcher条件发布。激活开始后失败/未知保留现场，不盲删解释器或回滚中央；未知目录/入口不覆盖。重复与升级保留旧版和任务pin，诚实报告阶段/退出码。

build(source,version,output)原3元组返回保持；扩展可选 release_tag，允许vX.Y.Z及vX.Y.Z-rc.N，产品VERSION仍2.1.4。资产tar.gz→pyz→PS→manifest单向依赖，无自引用hash。manager/release.json严格原两字段，不塞交付身份。

验收延用scripts/test_workflow.py唯一组件清单，新增真实Windows交付消费测试。Mac静态/纯逻辑不能冒充Windows。原Git完整验收不替换为ZIP模拟。


先并行完成引擎与交付资产，再接原生消费测试／CI，冻结组合候选后由单一独立 QA 审查。候选使用不可变 rc 标签，公开候选资产可下载后进入 Win11 普通用户真机验收；真实验收通过前不发布稳定版、不声称 Win11 已通过。

原候选 ccd8ba9 的开发与 CI 阶段已通过，真实运行见 https://github.com/Geoege-xll/agent-workflow/actions/runs/42799003531 。原 Windows 167 方法、普通桌面 164 方法为旧候选证据，新下载入口需新增原生消费验证；保留原 Git 源码完整验收。Mac 本机仍为先前 2.1.4 候选，不能称为最终版本。

恢复入口为 [草稿 PR #1](https://github.com/Geoege-xll/agent-workflow/pull/1) 的 `codex/upgrade-2.1.4-20261109` 分支；主工作区原五处修改及交接文件不纳入本轮运输。curl 组合 495863f 的[完整运行 42956603721](https://github.com/Geoege-xll/agent-workflow/actions/runs/42956603721)实际通过三平台和 11 个 Windows 组件／170 方法，原生所选节点零 skip；Mac/Linux 各自有平台／文件系统 skip，不得写成三平台全部零 skip。该成功不直接授予发行资格：独立 QA 随后发现自定义程序路径的持久 ACL 信任缺口，作为本主题必修回归收口。

安全职责固定为 `lib/windows_fs.py` 的只读可信路径原语，安装器复用，不在业务层复制 Win32／ACE 解析或修改既有 ACL。创建根之前检查所有现存祖先；受管根、bin、版本树、venv 与实际执行叶均按真实权限检查，pip 首用、CLI 调用及入口发布前重新核对。外部祖先纯创建新子项与删除／替换已有路径的权限明确区分；未知权限保守失败。真实原生负控覆盖弱根、私有根加不可信父目录 DELETE_CHILD、既有危险子目录及执行叶，核对零受管写入、ACL／身份和原正常程序／中央快照不变。受验程序位置必须本身可信，不对白名单 CI 路径放宽。

守卫只对本安装器拥有的程序树签署结论；state／host 高级位置沿既有服务职责，用户预装 Python／Node 沿运行环境边界，不将本次程序路径修复描述成全部旧服务路径安全审计完成。最终修复须回原独立 QA 实例，核对实际组合源码、原生结果与完整门禁后才可发布可下载 rc；Win11 普通用户真机、公开 URL 消费及稳定发布仍各自留证。精确后续源码与运行号以该 PR 最终同源证据和对应 Release 为准，旧成功不得重新绑定为修复后成功。

当前组合 `691a9bc` 的[运行 42967460102](https://github.com/Geoege-xll/agent-workflow/actions/runs/42967460102)已结束：macOS、Linux 与 Windows 其余十个原生组件通过，SDK 实际 91 方法通过；交付组件已完成正确 `0x40` 权限负控，但实际跨私有 venv 升级在中央激活预览被拒，完整 Windows 门禁失败，尚不能发布。升级夹具从同一真实 tar 派生第二核心，仅追加工作流说明注释，保持产品 VERSION、严格两字段元数据及 SDK；必须证明新核心、新解释器、新入口和 current 生效，旧环境与任务资源保留。

原独立 QA 已解析该轮真实过程记录，并从 tar／pyz 比对受验源码，单独关闭程序路径权限 Important；这不授予升级验收或最终发布资格。

继续定位原生角色事务容量：Windows 解释器路径变化会合法刷新三平台全部角色，现有成功／条件补偿日志重复持有完整正文。本地以完整 Windows 编译正文、真实 POSIX 发布／补偿推进器复现了补偿投影超限及实际持久日志超限；它不是原生 Windows 异常的替代证据。当前先在原失败现场补齐旧／新解释器的只读 traceback。生命周期释放实验不足以承担完整 Windows 正文，因此拟在同一日志内部以独立纯 codec 去重正文，manager 保留原授权、完整 Node 校验及推进器；原独立 QA 已核可这一受限方向，具体实现与中断前缀仍待审。普通物理容量上限、完整 Node／ACL／所有权及条件恢复语义保持；不通过抬高读写预算或忽略用户修改放行。
