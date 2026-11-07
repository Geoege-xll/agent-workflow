# Windows 中央安装与 npm 发布准备

- 主题 ID: `PLAN-WINDOWS-CENTRAL-NPM`
- 阶段: `active`
- 模块: `.`
- 任务等级: `Full`
- 已验收版本: `none`

## 目标与范围

用户要求 Homebrew Tap 与 npm 都发布。Tap 2.1.0 已按同一 GitHub Release 的 Formula 发布，提交66b708edfc52f9a82699211fbd4397b217608e98；npm 当前不是单纯的账号或元数据问题，Windows中央安装尚有真实后端缺口。用户随后明确先注册账号、当前不发布npm，并选择“继续完成 Windows/npm，再发布”。本轮先完成 Windows/npm 实现与验收，不调用npm publish、不接收用户密码／验证码／令牌；账号就绪和后续发布另按用户当前意愿处理。

实现面向 Windows 10/11 x64、本地 NTFS、普通用户及已具备的原生目录符号链接能力。核心 Skill 继续在中央内容库，通过真实目录符号链接供三宿主使用；无权限或文件系统能力不足时在项目／中央状态写入前明确拒绝。工具不自动修改开发者模式、账户权限、PATH、profile、ExecutionPolicy、Git全局配置或宿主信任，不用复制或junction替代已约定软链接。能力前提依据[Microsoft目录软链接接口](https://learn.microsoft.com/en-us/windows/win32/api/winbase/nf-winbase-createsymboliclinkw)，须由原生正反两类证据核实，不能只凭操作系统名称认定成功。

从已发布e2c981b1f5ff31e5cda41365682605ff747f3000开始，新增代码作为2.1.1候选；不覆盖v2.1.0标签、资产或业务项目绑定。生产由fresh／handoff_only的后端系统子代理负责，PM仅协调、计划、临时CI检查点与Git；保留来源仓5处未提交修改。依现有工作树策略在独立工作树实现和集成，原生Windows验证使用精确提交的临时CI分支；本地main最终合并保留项目confirm策略，候选完成后才进行该决定。

不扩展Windows TUI／管理器、WinGet、macOS npm入口、旧版兼容或立项讨论入口；不改变Light／Full、schema2、角色职责、英文受管指令、中央内容绑定和旧任务pin，不升级无关依赖或调用真实账户模型。

## 需求与验收

| 需求 | 完成标准 |
|---|---|
| REQ-WIN-001 平台文件系统 | 在现有platform_fs／windows_fs职责内补齐中央安装所需的目录软链接创建、锚定读取／身份校验、排他发布、删除与恢复；目录描述符不能回落给不理解伪fd的stdlib。普通文件继续拒绝任意重解析点、多硬链接与目录替换 |
| REQ-WIN-002 中央事务 | 实际中央导入、项目安装、机器binding／journal／retained及恢复路径完整消费后端；保留权限／ACL、同卷准备、精确前像、并发拒绝和持久化屏障。不得把失败fsync改为no-op，不虚构跨资源原子性 |
| REQ-WIN-003 当前npx合同 | 实际npm入口以调用cwd安装，薄runtime.py与三字段pin替代旧项目lib夹具；内置私有Python、完整Git验证、离线／ignore-scripts、重复安装和真实Hook消费当前中央服务。无权限、坏来源或并发／取消失败不留下误报成功的工作流 |
| REQ-WIN-004 发布准备 | product/VERSION、npm元数据、CLI版本、构建器与对应消费者统一2.1.1；候选完整包无lifecycle联网脚本或npm依赖，保留上游许可证和包白名单。可准备公开所需元数据与dry-run，但本轮不实际npm publish，不改已公开2.1.0 |
| REQ-WIN-005 原生证据 | 精确候选在原生Windows NTFS验证受管软链接正常与缺能力拒绝、身份交换／junction／硬链接拒绝、并发／占用、超时／Ctrl+C与恢复、缓存清理后薄桥／Hook、用户配置和系统设置不变；区分托管管理员与普通用户。必要macOS直接消费者通过，唯一独立QA对完整组合验收 |

## 方案与原型关联

本轮non_ui系统与安装功能，不改TUI或设计文件，不做原型。Windows文件系统、中央消费者和npm包是一条高耦合安装链，统一交给一个后端系统实现单元，内部按“底层句柄／软链／发布语义 → 中央直接消费者 → npx及当前E2E／原生CI → 版本与发布准备”顺序推进，避免多作者并写同一跨平台契约。必要代码仅在现有职责处补齐，不制作通用新框架，不全局patch标准库os。

实现使用原有ctypes／Win32和Python／Node／Git for Windows栈。非显然权限、并发、清理和异常策略加入详细中文注释。新增回归只覆盖本次缺失行为，优先扩展现有测试；真正独立的Windows中央原生矩阵可建一个测试模块。先用未修源码证明行为拒绝，再补有效后端与真实消费者。原生CI能力不足或新发现API无法满足原合同必须带具体失败返回PM，不能放宽守卫制造绿色。

源码文本检出由仓库根.gitattributes声明text=auto及eol=lf，二进制保持Git自动识别；现有tracked blob均已为LF，不进行批量重写或renormalize，也不修改用户Git配置。真实Git的autocrlf转换已能复现VERSION及角色frontmatter的失败；原生CI需记录实际配置与检出字节并强制校验LF，随后继续原消费者，不能只放宽单字段解析掩盖同链差异。

验证复用此前Claude／Codex／TUI与真实PTY未受影响结论。保留既有Windows CI的实际相关检查，随精确提交迁移当前E2E；新增普通用户正反能力验证使用自有临时账户／目录并收尾，绝不修改开发机或真实业务项目。首次基线CI可定位原生目录屏障等尚未知能力，已知init拒绝不反复整组重跑。实现者给出成功build／可运行消费者和完整命令、退出码、源SHA及日志，PM在隔离工作树生成仅本任务的CI检查点，只有当前候选的原生证据成立才进入唯一独立QA。

托管Windows环境已证明无软链权限的普通用户仍可创建链接，原负向环境假设不成立。仅本任务的GitHub-hosted一次性虚拟机测试允许临时将已存在且类型为DWORD、值为1的AllowDevelopmentWithoutDevLicense设为0，构造一次真实缺能力检查；这不是产品行为，也不授权修改本机、共享runner或真实账户设置。测试须先记录精确前像，仅修改该一个值，使用全新普通用户令牌及相同flags3调用，以真实ERROR_PRIVILEGE_NOT_HELD、无链接及sentinel不变证明拒绝。finally和workflow always路径按前像恢复并验证，不覆盖未知并发值，取消后也保留明确清理结果。若写0后仍可创建链接，停止此方案而不换参数、重试或降低验收。已通过的目录和赋权正向证据继续复用，不为该补缺重跑整组。

QA后PM原位更新本主题及同名HTML，使用实际required生命周期解析、链接和HTML freshness；source-pack没有PROJECT／STANDARDS索引，保留配置路径及null，不创建空索引或假报全仓文档通过。README、Homebrew及Windows用法由实现单元随真实候选更新，说明来源版本与已公开版本的不同状态。独立候选最终交付只包含本轮改动和已验计划投影。

## 当前进展与恢复入口

准备审计的e2c981b基线中，npm init只接受win32/x64，但require_skill_symlinks对nt无条件拒绝，Windows后端缺中央所需链接接口，E2E仍调用旧项目lib。该历史拒绝单例只证明写前拒绝；后续已按下述检查点补齐后端与真实中央消费者，不能把旧基线描述当作当前源码行为。

用户尚未告知npm账号注册／登录完成，本轮不发布。发布准备记录在request-id publish-tap-npm-2.1.0-20261107的既有scratch；本实现请求使用request-id windows-central-npm-2.1.1-20261107的唯一scratch及其中单一graph和作者／CI完整日志。来源分支main基线e2c981b，5处外部修改留在原检出；实现工作树windows-fs，后续集成工作树windows-integration，当前无已验收Windows候选。

底层能力及四个后端消费者已完成原生补证：目录fsync、软链正反能力与恢复、真硬链及普通文件守卫、junction拒绝、软链读建移删和普通文件排他移动／碰撞保全均有真实普通用户证据。当前检查点2549d8e9已包含中央事务、私有记录叶DACL、项目ACL保全、薄桥自举与Job helper；本地中央／补偿、私有发布、未确认Job保留现场、探针创建后失败、全新进程的pkgutil影子拒绝已通过。

当前生产检查点b2d81aa24b2b5e123002e3c4dd721ec803492ca6／原生run42341668197已通过完整中央消费者：真实普通用户安装启用、两次prepared桥exit0、私有记录／核心DACL、Skill真目录软链、Node薄入口check、固定pin读取、真实Job画像helper和重复安装，1 test／511.832s。finally账户／赋权／profile／进程句柄／fixture全部回收。该总时长包括多次核心验证和两次安装，未取得单阶段耗时，不能当作单次安装耗时；此节点也不代替内置Python的npm最终E2E或完整BUILD_VERIFIED／QA PASS。

此前helper路径诊断错配已在configuration边界修复：仅将已证明归属和核心目标的精确Skill路径渲染为验证器的本机显示格式，原两类白名单及未知链接／普通文件／文档／角色守卫保留，逻辑协议仍为POSIX路径。新增Windows／POSIX精确匹配及未知拒绝回归、真实foreign链接与缺角色消费者通过。真实切版消费者另暴露retained项目恢复叶误走私有记录包装器的TypeError，已仅将该调用切回项目reader以保留真实mode／DACL；唯一失败节点重验1 test／8.315s通过，原失败输出保留。

中央验收初始失败及三轮返工的记录保留。用户在明确获知helper路径诊断错配、当前失败上限及剩余验收后回复“继续”，授权恢复该已定位修复并完成原Full剩余目标；此前停写决定已结束，累计失败历史不清零，不把本次授权理解为无限重试或放宽校验。当前继续npm持久embedded／当前E2E与缓存独立真实Hook／产品缺能力写前拒绝、2.1.1元数据、必要macOS消费者和唯一独立QA。有新故障须有新诊断或可验证进展，无进展先停止该路径返回PM。

2.1.1 tgz切片40ab293已迁移当前薄桥／三字段pin、持久embedded校验、普通用户与缓存后helper写读／真实Hook入口，VERSION及直接消费者统一。实际Node帮助版本7节点、包／锁／离线pack／Homebrew安装后版本／能力传播／macOS交互中央6 tests／3.457s通过。当前仍private:true，产品公开元数据尚未切换。

首轮native-npx run42343690163／40ab293的可信archive准备及离线pack通过，但3 tests／3.860s全在产品执行前的只读PowerShell快照失败，未显示已捕获的两流。仅补失败上下文的检查点00072b1224da882baaa43c3b8b53b53df55dc585／run42344194095取得新诊断：3 tests／8.886s，Get-ExecutionPolicy已找到Microsoft.PowerShell.Security模块但无法加载，exit1／stderr564字节。模块内部原因尚未确认，不能归因到策略、权限、编码或搜索路径；init／持久embedded／真实Hook尚未执行，两轮finally均收回账户／profile／进程及fixture。当前只读核对进程边界和必要主源，下一步须取得最小模块加载诊断或有依据的修复，不盲重跑、不跳过快照或修改用户设置。

产品缺能力负向仍未触发。默认acceptance的原生Job／Hook／NTFS检查、真实控制台Ctrl+C、持久Python和项目并发、Windows中央补偿／晚保存等仍缺必要证据；cancellation-file、模拟SIGINT与macOS补偿不能冒充这些结果。完成真实tgz入口后按具体缺口补验，再做公开元数据和唯一独立QA。

实现及临时CI分支均保留，集成工作树尚未推进。完整历史输出持续保存在本请求windows-capabilities.log（当前901083字节，SHAb6ea9d4ac736d3fdfb802df4b598aa601a084b34ee6fe210e56d712ead9cd05e），同windows-handoff.json原位更新并保留各次实际执行输入快照，原失败未覆盖。npm继续暂不发布，既有公开2.1.0、原仓五处修改与三个业务项目不变；剩余验收完成前不标记整体BUILD_VERIFIED或QA PASS。

## 验收结果与当前已交付行为

本主题尚无已验收版本。GitHub及公共Tap的2.1.0发行事实保持；本轮计划、工作树、绿色便携测试或托管管理员环境结果均不作为Windows普通用户安装成功的证据。

## 批准依据与必要证据

- 批准依据: 用户在npm功能阻塞与需新增实现范围明确后选择“继续完成 Windows/npm，再发布（推荐）”；同时明确先注册账号、当前不发布npm。当前Full范围为Windows文件系统适配、当前中央E2E、原生验证与npm发布准备，沿用既定软链接及工作流，不重复要求已明确的范围批准。
- 验收证据: 底层能力和普通用户中央完整消费者已有精确检查点及分段原生证据，npm内置Python／当前E2E／真实Hook与产品负向仍在实施；尚未进入完整候选独立验收。正式完成须记录精确候选、原生Windows和必要macOS证据、唯一独立QA及实际交付边界，不以完成状态替代验收。
