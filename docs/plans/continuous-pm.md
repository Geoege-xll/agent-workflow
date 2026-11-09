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
8. 生产实现分给全新职责子代理，精简交接，不复制完整 PM 会话；整合后进行单一独立 QA。必要检查通过后才发布 GitHub/Tap 和升级本机中央程序及 current，保留项目锁版与停用选择。

## 方案与原型关联

复用现有任务图、记录更新/CAS、实例续用和平台原生执行。新增跨请求准入职责负责资源投影与短期协作领取；原记录继续是任务状态权威。先完成 HTML 暂停及准入接口，再接入三平台共享协调规则与 Codex 续用诊断。Windows ConPTY 与中央偏好消费者可独立推进，接口冻结后接入 TUI 和统一验证入口。

TUI 沿用已确认布局与交互，属于 UI-Conformance，设计增量为零，保留真实 UI/可访问性 QA；本轮没有原型设计任务。依用户明确指令，本计划只保存 Markdown，不生成同名 HTML。

## 当前进展与恢复入口

HTML 计划生成的公开入口和流程要求已暂停，代码以注释保留；Markdown 计划、原型能力及历史页面保持。跨请求准入共用原 Task.state、原记录 CAS 和平台原生子代理，各请求独立授权、核心 pin、资源占用与 QA；追加送达原实例并取得确认，未知结果不重派，不建立第二状态机或 Agent 池。

真实 Codex app-server 已证明 A 运行期间自然 B 引导同一 PM，确认后领取并派发 B，A 同 ID 追加且工作者确认。补验中 PM 自己结算 evidence 原包至 RESULT_VERIFIED、占用1→0；PM/Worker正常结束，unsubscribe后约60秒出现thread/closed。初次失败记录保持。此证据不覆盖Codex App GUI、父回合final后仍运行的任务或所有模型/角色设置；App自动化被工具安全策略禁止，不绕过读取用户会话。

完整运行42679088902（b8d7a8b，实际PR merge fcb2243563且树相同）已结束失败：macOS/Linux CI各收集273项、按既有平台条件分别skip3/4后suite成功；Windows119项中7/9组件通过，包含中央完整生命周期1739.339秒、Hook7秒、真实NTFS两项与库48项。TUI两次保存等待超30秒；全局首次保存29.641秒实际成功，后续恢复宿主继承的第二次超时。Unicode body退出及模式恢复，但cleanup冲突导致该方法整体ERROR。边界失败是CRLF夹具未移除能力声明，生产按能力1选择新runner正确；夹具已修并由原QA接受，待原生复验。

保存链已按职责重构并完成原Reviewer阶段复核：显式CommitReadPreparation只合并完整guard/status/收据的纯准备，普通before_write保持原合同；完整尾验结束后fresh核对可变来源、绑定、Node、目录和必要画像，再进入原备份、写入、独立publish/verify及条件补偿。父读取租约提前拒绝，Plan不留reader。OwnershipSources使global与receipt共用CONFIG/managed、record及journal retained、Skill名、完整Node/目录事实，沿原inventory复核，不重建基准。QA发现的retained遗漏与Windows目录注入两Important均已代码层闭合。

同源真实服务计数：项目完整apply8scan→4、refresh另1；全局首次及恢复宿主继承的第二保存均7→4、refresh0。3个实际native产物与15次journal写入保留，新增4节点18.566秒及6直接消费者12.053秒通过。这些是Mac实际计数，不证明新的Windows30秒预算已过；前轮claim28→21→8的实际证据按各冻结源独立保留。

唯一registry的最终登记已同Reviewer接受并运输，实际9组件121方法；Server full始终包含提升资格的NTFS2。普通desktop从同一登记派生119方法、明确排除2项，所选仍zeroSkip；Win11成功只报告SCOPED_PASS、full_registry_executed=false及实际selected/excluded。下一步用完整同候选运行macOS/Linux及Windows门禁，再取得Win11普通用户桌面与最终独立QA，随后发布GitHub/Tap并升级本机中央程序及current。三个跟随项目自动使用新current，锁版、停用及偏好保留；npm/npx不恢复。

实现仍在独立请求工作树中，生产按职责交接、精简任务包，不复制完整PM会话。主目录五处原有未提交修改及用户交接逐字节保持，不纳入候选。全部原始失败、任务图、profile和复核日志保存在upgrade-214-20261109暂存区；本计划保留当前决策与恢复入口，历史由Git和原始日志追溯。

## 验收结果与当前已交付行为

尚未取得本轮整体验收、最终独立 QA 或发布结果。工作树候选为2.1.4，主仓 main、本机及公开渠道仍是2.1.3；不得将候选、静态检查、模拟或部分 Windows 节点作为新版已发布/全平台已验收的证据。

## 批准依据与必要证据

- 批准依据: 用户在讨论七项优化方案后明确“开始优化，同时完成Windows适配，取消plan生成html（代码注释保留），完成后发布新版本并升级本机”；随后明确必要重构和三平台最新官方规范要求。这覆盖实施和最终发布/本机升级，无需重复请求同一授权。
- 验收证据: 本轮三路职责分析及官方最新主文档；Codex 核心报告 codex-native-test/native-verification.md、收口补验 settlement/native-verification.md 与原事件保存在请求暂存区。Windows CI 42598994710 ConPTY八项通过；42614154168 的Hook通过、reset失败与脚本/API两项通过；42618163143 reset已过、restore与TUI通信失败。修复、原始失败及独立审查记录全部保留。后续只补真实命令、环境、退出结果和定位证据，未运行的原生交互及 Win11 桌面保持未验证。
