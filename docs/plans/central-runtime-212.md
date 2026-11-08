# 中央运行时统一管理与原生角色继承

- 主题 ID: `central-runtime-212`
- 阶段: `completed`
- 模块: `.`
- 任务等级: `Full`
- 已验收版本: `v2.1.3`

## 目标与范围

将不可变核心、任务固定版本、项目策略和模型逐字段继承整合为统一中央运行时。CLI 是管理入口，TUI 调用相同服务；一次中央激活更新启用且跟随的项目。按既有七点方案完成实现、独立 QA、公开发行、本机升级及 mt-shop、ParentsKit、TeachingAssistant 的历史遗留和备份整理。

用户指定的 2.1.2 已先公开；真实迁移发现发布见证容量缺陷后，按原“稳定修复并发布最新版”的授权完成必要补丁 2.1.3。2.1.2 标签与资产保持不可变，没有新增功能范围，也不将 2.1.3 记作用户另行明确指定的版本。

不改变 PM／实施／验证／独立 QA 流程，不实施立项讨论入口，不恢复 npm/npx 或 Windows 安装，不引入常驻调度器、数据库、Agent 池或旧自包含安装兼容层。保留业务资料、用户偏好、有效旧 pin 与主工作区五处原有修改。

## 需求与验收

1. 中央 current 与项目实际 binding 分离；默认 follow，use 建立项目锁版，follow 清除锁版。停用项目不因中央激活重启，下次启用采用有效策略版本。
2. 激活／回退冻结影响集合和前像，逐项目结算、条件补偿及中断恢复；current 最后条件发布。新任务初始化共用短协调锁，旧任务按原 pin 读固定核心，不覆盖未知并发修改。
3. 三端全局原生 subagent 精确归属；项目只投影实际覆盖或平台策略所需角色。模型／推理按字段解析项目覆盖、通用默认、宿主／会话；显式 inherit 直接选择宿主。内置 Skill 保持仓内单一来源和宿主发现软链，正文先按任务 pin 定位。
4. CLI／TUI 统一中央状态、激活／回退、项目 follow／锁版；当前项目当前平台全部角色一键恢复通用默认。独立预览，取消／失败保留草稿，成功只结算本提案范围，无改动明确提示未写、未备份。
5. 健康分别表达声明启用、当前资源、历史恢复、新任务与管理写许可。历史缺失不伪装当前停用；配置与发现检查不冒充真实模型执行。
6. 备份生命周期保留最新完整批次和未结算恢复依赖，raw applied journal 不改写。核心按 current／previous／项目实际、used、pin 和事务引用保活，未知引用保留；旧清理脚本不执行。
7. 正式 awf-cli 来自 Homebrew，源码开发入口与其分离。程序升级、核心导入、中央激活分别执行；最终公开修复版并将本机与三个登记项目统一到最新中央版本，核对资料、偏好、旧核心和遗留备份。

## 方案与原型关联

沿用已确认的 curses 粗外框、虚线项目分隔、顶部平台 Tab 与左右区域焦点；管理动作复用现有预览和结果弹层。用户明确“分析完成后，直接开工，按照有UI规范不设计原型图”，本范围 prototype_policy 为 waived_by_user。历史原型未改，工程／设计规范、真实 PTY、UI 和可访问性审查保留；未执行辅助技术会话。

职责及依赖保持为 CLI／TUI → 管理服务 → 状态原语、不可变内容库与宿主适配：

- central_runtime 负责固定计划、全局激活／恢复和 current 最终发布；runtime_policy／runtime_state 负责协调、封闭记录与条件写入。
- runtime_service／project_service 负责项目策略和事务；native_agents 通过冻结 HostPaths／NativeContext 管理三端全局角色和必要项目投影。
- runtime_lifecycle 统一备份／核心盘点与条件清理；runtime_bridge／runtime_pins 保留旧任务资源和初始化边界。现有文件归属和入口说明见开发手册，不再为行数搬动模块。

binding schema 1 和三字段任务 pin 不变。current、policy、activation 与原生归属分别记录；native_roots 与 generation 同次发布，最后一次失败日志不成为旧 current 的准入权威。current 必须声明受支持控制协议 1；该协议与任务 helper 准入协议独立，旧 helper 0 由新控制器持父锁执行，旧固定任务资源继续可读。

普通记录／资源保留 4 MiB 上限；完整发布见证按 base64 长度和封闭元数据使用独立有限预算。项目与原生生产者复用实际 builder 计算上界，中央在预览、锁前与最终前像复核后检查全部阶段。预算占位不作为真实 Node／收据／归属；诊断有实际持久化字节上限，完整 before 不截断。持久 generic .publish 仍失败关闭，没有新增通用跨进程修复命令。

生产实现按职责交给四个独立交接子代理；同任务窄返工沿用原 owner，独立 QA 始终由同一 Reviewer 承担。新实例仅接收单任务交接，不复制 PM 或兄弟会话。

## 当前进展与恢复入口

功能、发行、本机升级、三个项目统一激活和旧备份清理均已完成。当前执行依据是本页已验收基线；此前稳定性计划中当时的 mt-shop 待办保留作历史，不再回放为当前安装或恢复任务。

- GitHub v2.1.3 的代码标签为 09bb37a；归档、SHA 文件和同次 Formula 的摘要／尺寸／版本／目标提交全部核对。Tap 检查点 bc258e5 已发布。
- 默认命令为 /opt/homebrew/bin/awf-cli，实际载荷根为 /opt/homebrew/Cellar/awf-cli/2.1.3/libexec；来源为 formal，Homebrew 安装和测试通过。测试自动开启的开发模式已恢复关闭。
- 正式核心已导入 ~/.config/agent-workflow/runtimes 下的不可变内容库；中央生效记录为 ~/.config/agent-workflow/central/current.json。原 2.1.2 未结算事务先经条件补偿恢复，再执行一次 2.1.3 中央激活；最终 activation 为 applied，无 pending，真实记录 4,005,129 字节。
- 三个项目实际 binding 与有效 binding 均为 2.1.3，保持启用和 follow。三个宿主各 7 个全局角色的归属及资源验证无冲突。
- 统一生命周期服务已删除 351 个旧受管备份节点及两处明确批准归档，保留 111 个最新批次／恢复依赖节点。源码最新备份保留 9 文件／153,755 字节，指纹未变；二次只读清理计划为零候选，清理为 applied，无 pending。

恢复本主题时先查看本节和已验收行为，按需只读运行 awf-cli --version、runtime status --json、list --json。不要重放已完成激活／补偿或旧备份脚本；未来出现新 pending 时先核对对应恢复预览和精确前像，不手删日志／见证。实施工作树是已交付源副本，不是运行时依赖；必要完整日志和原始审批／QA 证据继续保留在当前请求暂存区。

## 验收结果与当前已交付行为

| 项目 | 状态／策略 | 实际及有效版本 | 资源／当前恢复能力 | 新任务／管理写 |
| --- | --- | --- | --- | --- |
| mt-shop | 启用／follow | 2.1.3 | 健康／可恢复 | 允许／允许 |
| ParentsKit | 启用／follow | 2.1.3 | 健康／可恢复 | 允许／允许 |
| TeachingAssistant | 启用／follow | 2.1.3 | 健康／可恢复 | 允许／允许 |

已交付中央选版、锁版／跟随、条件恢复、原生全局角色与项目覆盖、整平台恢复通用默认、分层健康和统一生命周期维护。CLI 与 TUI 共用服务；后续中央激活统一结算启用 follow 项目，无需逐项目复制运行时。未登记的 MuYeCha／omni-mind 未纳入本次操作。

1073 项业务资料／项目配置及全局模型偏好在补偿、激活、清理后分别核对均未变化。主工作区五处既有修改保留，已删除的历史备份不重建、不伪造历史。清理前后 10 个已验证核心列表一致，包含 2.1.1 及旧 pin 所需版本；备份删除不等于删除受引用核心。

资源和归属通过验证，doctor 仅进行了本地配置投影；真实原生角色选择／模型执行、宿主信任和辅助技术执行仍未验证。runtime_verified 保持 false，不能由文件生成、CLI 版本或测试通过推定这些运行行为。

## 批准依据与必要证据

- 批准依据: 用户要求按七点中央运行时方案直接实施、原版本为 2.1.2、推送 GitHub／Tap 并升级本机和三个项目；明确当前项目当前平台全部角色恢复默认、生产交给 subagent、新实例不复制完整 PM 会话，以及按既有 UI 规范直接实现、不设计原型。历史清理和跳过用户已删备份有明确授权。2.1.3 是公开 2.1.2 故障后的必要稳定补丁，沿既有修复发布授权执行。
- 验收证据: 同一独立 Reviewer 对完整 57 路径／45 规则给出 PASS（43 pass、2 not_applicable）；容量、跨平台夹具和事实差量均复审通过，schema2 交接与实际提交／差量精确绑定。正式第二轮 Linux／macOS 各 194 项全部通过（712.095／770.608 秒），含真实 PTY 和离线打包；公开发行、本机安装及真实三项目／生命周期验收均已完成。

必要证据入口：

- 正式发行与成功 CI：[v2.1.3](https://github.com/Geoege-xll/agent-workflow/releases/tag/v2.1.3)、[42430383645](https://github.com/Geoege-xll/agent-workflow/actions/runs/42430383645)。2.1.2 原资产保持，旧说明已指向修复版。
- 原始失败仍保留：2.1.2 真实 3,302,153 字节日志被封装为 4,403,382 字节，超过旧共用上限，导致 partial；原记录／前像未丢。2.1.3 首轮矩阵 42428523327 两系统各 194 项中仅同两夹具阈值失败；56af194 保留断言、增加真实用户段并通过短／长根各两节点后，才运行上述成功矩阵。
- 当前请求证据目录：/private/var/folders/w9/cgyn8nj14fs91j8rrc220l3w0000gn/T/agent-workflow-request-scratch/agent_workflow-65c9b3d90960/request-ed56655ecb1d9cbc295a7c2ed19d170f298eff1214685c4dfe508b71efd703dc。完整原始输出保留于 entry.log、runtime.log、native.log、adapters.log、qa.log 及各正式 CI 日志；原审批／完整单任务包／QA 交接保持可恢复。
- 发行与安装事实：release-213-artifact-verification.json、release-213-published.json、brew-upgrade-2.1.3.log、brew-test-2.1.3.log；中央／角色验收为 central-213-acceptance.json、native-213-acceptance.json。
- 数据及清理事实：pre-activation-preservation.json、preservation-after-213-cleanup.json、backup-latest-preservation-213.json、runtime-cleanup-213-applied.json、runtime-cleanup-213-final-status.json 和零候选后续预览。原始 baseline 不覆盖。

本页已将累计实施历史收敛为当前基线；完整旧内容可由既有 Git 提交和上述原始日志恢复，不以本摘要替代完整证据。两个临时 macOS 诊断分支已撤除，其独有差量与失败／成功日志仍保留；没有把 observer 或临时发行工作流并入正式源码。
