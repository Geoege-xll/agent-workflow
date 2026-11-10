# 持续接单的 PM 与 2.1.4 整合升级

- 主题 ID: `continuous-pm`
- 阶段: `active`
- 模块: `.`
- 任务等级: `Full`
- 已验收版本: `none`

## 目标与范围

三个平台的主会话 PM 持续接单，由 PM 判断需求之间的重叠、依赖和资源占用，决定并行、复用成果、连续任务追加或等待。用户自然讨论 B、C，不负责分配子代理或整理任务关系。保留 Claude Code、AGY 已有交互，重点补齐 Codex CLI 与 App 的消息送达、等待和协调合同。

本轮同时恢复[原生 Windows](windows-native.md)适配；暂停计划 HTML 生成，保留实现和历史文件；完成后发布新的补丁版本并升级本机。用户明确允许必要的职责重构，要求架构合理、健壮、易扩展维护，并依据三平台最新官方规范。当前候选从 main 1235951 及 Windows 整合检查点 4d88b02 开始，公开 2.1.3 的支持声明尚未改变。候选版本暂定 2.1.4。

## 需求与验收

1. A 执行期间可讨论 B；B 获准后具备条件即派发，A 不停止、不重启、不重复派发。
2. 独立请求保留各自图或 Light 单包、授权、固定核心及 QA；统一资源视图复用原 Task.state，不建立第二状态机或 Agent 池。
3. 复用成果、同任务追加、新建独立实例分别处理；修订送达和工作者确认可追踪，旧结果不证明新范围已完成。
4. 跨请求核算路径、语义锁及线程/Writer容量；派发前领取与复核，结果不明先核实而不自动重派。容量不足不阻止讨论，暂停任务不自动恢复。
5. Codex CLI/App 及 Claude Code/AGY 的官方能力、当前工具和真实验收分别记录，配置声明或算法测试不得冒充原生交互。主回合结束/中断与子代理生命周期单独验证。
6. plan HTML 的 CLI、Python 公开入口及流程要求暂停，调用保留为注释和恢复说明；Markdown 计划、授权、原型、验证合同保留。原型需求导航允许仅 Markdown，保留安全边界及旧页面；不删除已有 HTML，不暂停原型 HTML。
7. Windows 目标为 Win11 x64、PowerShell7+、CPython3.11+；完成中央组合、真实 ConPTY TUI、进程收尾和验收入口。Windows Server CI 与 Win11 普通用户桌面证据明确区分。
8. 生产实现分给全新职责子代理，精简交接，不复制完整 PM 会话；整合后进行单一独立 QA。按用户最新顺序，macOS完整检查与真实PTY通过后，先安装本机2.1.4候选中央程序并切换current；真实Windows、Win11桌面及最终独立QA完成后再正式发布GitHub/Tap。候选安装记录源码与归档来源，保留项目锁版、停用与模型覆盖。

## 方案与原型关联

复用现有任务图、记录更新/CAS、实例续用和平台原生执行。新增跨请求准入职责负责资源投影与短期协作领取；原记录继续是任务状态权威。先完成 HTML 暂停及准入接口，再接入三平台共享协调规则与 Codex 续用诊断。Windows ConPTY 与中央偏好消费者可独立推进，接口冻结后接入 TUI 和统一验证入口。

TUI 沿用已确认布局与交互，属于 UI-Conformance，设计增量为零，保留真实 UI/可访问性 QA；本轮没有原型设计任务。依用户明确指令，本计划只保存 Markdown，不生成同名 HTML。

## 当前进展与恢复入口

HTML 计划生成的公开入口和流程要求已暂停，代码以注释保留；Markdown 计划、原型能力及历史页面保持。跨请求准入共用原 Task.state、原记录 CAS 和平台原生子代理，各请求独立授权、核心 pin、资源占用与 QA；追加送达原实例并取得确认，未知结果不重派，不建立第二状态机或 Agent 池。

真实 Codex app-server 已证明 A 运行期间自然 B 引导同一 PM，确认后领取并派发 B，A 同 ID 追加且工作者确认。补验中 PM 自己结算 evidence 原包至 RESULT_VERIFIED、占用1→0；PM/Worker正常结束，unsubscribe后约60秒出现thread/closed。初次失败记录保持。此证据不覆盖Codex App GUI、父回合final后仍运行的任务或所有模型/角色设置；App自动化被工具安全策略禁止，不绕过读取用户会话。

完整运行42699711396（ec0e8f3，实际PR merge 63076e9且树相同）已结束失败：macOS/Linux CI成功；Windows121项中7/9组件通过，中央完整生命周期、入口、库、ConPTY、诊断、准入及提升NTFS全部通过。TUI五次实际模型/推理保存均成功，原Unicode及cleanup问题已复验通过；剩余一个body失败为项目启用预览超30秒。实际executor栈停在preview内重复核心校验，无worker异常或refresh阻塞。原CRLF能力夹具亦已原生通过，历史失败保留。

中央边界8项中10个子例同在准备阶段失败：普通既有config.toml复制权限至同父stage后，DACL control由0x8004变为0x8404、有序ACE由3变4，尚未进入各故障注入。单节点诊断42708668152已原生复现：source owner为BA、private stage owner为当前用户LA，父目录CREATOR OWNER继承在目标owner语境映射为新增LA全权ACE；源及父权限保持稳定。权限复制还需满足包含owner的完整stage见证，不能忽略AI或多出的ACE。最小测试与隔离单job已同Reviewer接受，原0.034秒ERROR及完整SDDL保留；后续创建时源SD实验42712087273实际1方法0.022秒通过，owner/control/ACE、完整安全及三种独占重开错误32均已核实。create+seal及统一完整快照发布按文件系统职责实现，公共replace写者已完成归属审计和统一迁移，14文件原语/发布实现与7文件中央/原生/AGY消费者均已通过同一Reviewer的代码阶段复核。消费者已实际合入真实依赖，5项精准便携消费者一次0.735秒通过；新生产路径的Windows执行及完整门禁仍待。临时workflow不进入发行候选，API实验不当整体验收PASS。

保存链已按职责重构并完成原Reviewer阶段复核：显式CommitReadPreparation只合并完整guard/status/收据的纯准备，普通before_write保持原合同；完整尾验结束后fresh核对可变来源、绑定、Node、目录和必要画像，再进入原备份、写入、独立publish/verify及条件补偿。父读取租约提前拒绝，Plan不留reader。OwnershipSources使global与receipt共用CONFIG/managed、record及journal retained、Skill名、完整Node/目录事实，沿原inventory复核，不重建基准。QA发现的retained遗漏与Windows目录注入两Important均已代码层闭合。

同源真实服务计数：项目完整apply8scan→4、refresh另1；全局首次及恢复宿主继承的第二保存均7→4、refresh0。3个实际native产物与15次journal写入保留，新增4节点18.566秒及6直接消费者12.053秒通过。这些是Mac实际计数，不证明新的Windows30秒预算已过；前轮claim28→21→8的实际证据按各冻结源独立保留。

三个纯preview入口的操作级只读范围已同Reviewer接受并整合，复用既有完整reader与尾验，同pin实际1scan/2verify、双pin2/4，显式source仍双inspect且零导入，writer/apply独立fresh。两个精准节点Mac实跑通过且原Reviewer已完成代码阶段复核，等待原生复验，不修改30秒预算。旧完整门禁的registry为9组件121方法；本轮新增原语、中央/AGY与独立owner权限节点，最终数量由唯一登记实际重新收集，不能沿用旧数字。Server full保留提升NTFS及独立owner权限证明，desktop明确排除这3项提升节点且所选zeroSkip。Win11成功只报告SCOPED_PASS、full_registry_executed=false及实际selected/excluded。用户最新授权先更新本机：先完成macOS完整回归和真实PTY/TUI，安装已复核的2.1.4候选程序与中央current，之后继续真实Windows；完整同候选门禁、Win11桌面及最终独立QA完成后再正式发布GitHub/Tap，必要时用最终正式归档重装同版本本机候选。三个跟随项目自动使用新current，锁版、停用及偏好保留；npm/npx不恢复。

实现仍在独立请求工作树中，生产按职责交接、精简任务包，不复制完整PM会话。主目录五处原有未提交修改及用户交接逐字节保持，不纳入候选。全部原始失败、任务图、profile和复核日志保存在upgrade-214-20261109暂存区；本计划保留当前决策与恢复入口，历史由Git和原始日志追溯。

原生组件42736740442首次65方法69.522秒/9errors后，取证轮42739662508（50518ad，与I cfac28e生产树相同）实际65方法60.182秒/6errors、零skip。公开异常3种真实资源fault已通过；custom五子例的owner、raw ACL、有序ACE、mode0666和attrs32全同，源control9404而初始stage9004，仅AUTO_INHERITED缺失，完整安全守卫正确拒绝。原FS按官方SetSecurityInfo HANDLE规范集中实现首写前精确初始化，保其余完整守卫，仍待冻结/原QA/真实Windows。余下Budget错误所在共享parser合法CRLF缺陷已真实safe-sync红绿验证并获原QA接受；N1已将新六精准合同加入唯一registry，当前10组件149方法、desktop146排3，后续新native方法继续按实际清单派生。携CRLF修复的71项组件42743528209（2ce2503）已实际55.568秒/5errors、零skip：大root预算与新六合同真实Windows通过，仅custom五子例仍拒绝；原始失败、30条SD事件与完整artifact保留在请求暂存区。

SDK完整修复2485cc4已按原soleQA最终许可（新patch8a4875，旧910be2许可撤回）精确合入候选8b9ca0c。独立原生库运行42750791601/18d3131实际72方法72.253秒全部OK、零skip、test_exit_code=0；五写者source/初始化stage完整SD均9404且owner/ACL/ACE/security全等，原源身份/正文不变，同一不可继承HANDLE，三种共享重开均错误32。原probe EOF Important已用64bit位置保存/0起读/finally恢复及真实读取链回归闭合。隔离YAML因延后stdout JSON使末尾摘要断言报错，job仍failure并保留原流，不重标绿；生产gate原样传原CLI退出码，不受此临时包装器影响。临时workflow不进入候选/main/归档，不为临时汇总器再改生产。完整门禁42753036097已结束失败：候选dba7e53，实际PR合并8829398与候选树均ef18e492。macOS CI通过；Linux仅保留inode替换测试的假设失败。Windows 10组件150项中，库72、边界12、ConPTY8、入口6、诊断4及大小写2通过；中央1与准入41暴露standalone Records的bare/package文件描述符注册表混用；owner-only1的backup测试在改owner时连带改变DACL；TUI3的保存操作30秒内未结束，尚待性能归因。完整日志与21份原生文件均保留，原FS/C实例按职责返修，未放宽安全断言或时间预算，未重新标绿失败。Win11普通桌面147项（排3）、最终独立QA及正式发布仍待。

mt-shop今日最新主线程“梳理并清理Admin侧边栏”的只读抽查已完成，截至上海2026-11-10 11:48:55。实际A派发后接收B、B范围纠正交回原审计实例；8次新建均fork_turns=none，10次原实例续用包含用户补充与QA返工，独立QA发现键盘问题后已返工。受限样本未证成明显工作流偏移或需回滚bug；仅一组同参数文档查询疑似重试，输出不同且无中间文件SHA，不能认定或量化浪费。373个唯一response的输入去重统计含98.62% cached，不将全部输入当新增消耗，也不据高缓存宣称零冗余。未解密handoff或修改业务项目；此为CLI样本，App GUI未验收。证据mtshop-today-usage-audit.json，SHA1bf8d4b786d9465cc6caa4cb278a43b25d2528e876df1b34d05d25b34f5b4451。

正式门禁返修已按原职责和同一Reviewer精确整合：Records的Windows SDK导入与创建虚拟fd的bare/package façade保持同namespace，原三参数、finish/CAS/最后结算顺序不动；新增回归使用当前原生Python child，无Bash依赖。Linux retained测试在旧inode仍存活时构造不同实体替换，owner-only测试在批准前固定DACL并保留完整安全断言。新增测试专用有界phase观察器不改产品/屏幕/30秒预算：按Job.execute两个唯一CALL positions记录operation/refresh及完整外层尾验，共享wrapper/body分开，不读敏感值或保frame，并有固定caps/hook恢复。两节点在CPython3.14与3.11各实际通过；统一源码原CLI再次2项0.045秒exit0，原Records统一回归1项0.130秒exit0。唯一登记已实际收集为10组件153项、ordinary desktop150项排3，两个新profile ID均唯一；这些便携结果不冒充Windows执行。新同源完整门禁及实际阶段数据仍待，最终Win11桌面/原soleQA/正式发布仍未完成。

## 验收结果与当前已交付行为

本机已按最新授权先行更新为2.1.4候选版：同源Mac285项340.176秒exit0（280通过/5 Windows-only skip），真实PTY两节点均通过，同一Reviewer允许本机候选更新。来源提交6eac3ea、双构建归档SHA7c516caf34bf10bdfff3370913c33b83efc55f5d3e51150261b44e10a3168259；实际Homebrew程序根为/opt/homebrew/Cellar/awf-cli/2.1.4/libexec。Homebrew标准README搬移与两Node首行改写已逐字节核实，185文件直接同归档、其余3项仅上述标准处理。实际安装后新CLI预览/导入/激活全部exit0，current为1b9b2b54738c92b27ff64caf1058b854e1daef378a1f32c0c4e7edfbc305da3e。三个登记项目enabled/follow/healthy，零冲突与pending，54个Skill软链指向同一新core，项目角色与全局偏好、主目录五原修改均保持。旧核心/任务pin未清理，公共Tap Formula恢复原字节且clean，brew test临时开启的developer模式已恢复off。详证在请求暂存区local-first-upgrade-result.json及原始日志。

尚未取得本轮整体验收、最终独立QA或稳定发布结果。主仓main与GitHub/Tap正式版仍为2.1.3；本机候选先行不代表Windows生产路径、Win11桌面或全平台已验收。接下来继续唯一registry143方法的真实Windows门禁与固定SHA桌面脚本，必要修复仍由原职责实例与同一Reviewer闭合，正式发行后按最终归档更新本机。

## 批准依据与必要证据

- 批准依据: 用户在讨论七项优化方案后明确“开始优化，同时完成Windows适配，取消plan生成html（代码注释保留），完成后发布新版本并升级本机”；随后明确必要重构和三平台最新官方规范要求。这覆盖实施和最终发布/本机升级，无需重复请求同一授权；2026-11-10用户进一步明确允许先升级本机、再进入真实Windows验证。
- 验收证据: 本轮三路职责分析及官方最新主文档；Codex 核心报告 codex-native-test/native-verification.md、收口补验 settlement/native-verification.md 与原事件保存在请求暂存区。Windows CI 42598994710 ConPTY八项通过；42614154168 的Hook通过、reset失败与脚本/API两项通过；42618163143 reset已过、restore与TUI通信失败。修复、原始失败及独立审查记录全部保留。后续只补真实命令、环境、退出结果和定位证据，未运行的原生交互及 Win11 桌面保持未验证。
