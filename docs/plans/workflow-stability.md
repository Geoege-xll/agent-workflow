# 工作流结构整理与稳定性收敛

- 主题 ID: `PLAN-WORKFLOW-STABILITY`
- 阶段: `active`
- 模块: `.`
- 任务等级: `Full`
- 已验收版本: `v2.1.1`（结构、源码修正与公开发行；mt-shop 本机恢复待具体批准）

## 目标与范围

用户于 2026-11-07 在结构整理建议后明确要求“开始优化，将历史无用的该清理的进行清理”。当前结构整合单元保留既定工作流、CLI 命令语义、curses TUI 布局与交互、中央不可变版本和任务 pin、三宿主共享 Skill 软链接及 macOS/Linux 安装边界。版本暂为 2.1.1；本单元不自行发布、改真实业务项目或恢复 npm/npx／旧版本兼容。

用户后续明确重述整条任务：先完成本次文件梳理与架构整合及验收，再审计 mt-shop 的“确认双端登录默认验证码”会话最近实际工作流使用，检查偏移、bug、重复文件加载／注入及 token／上下文浪费；确认问题后优化并验证，最后提交推送、发布 GitHub Release／Homebrew Tap 新版本并同步本机中央程序及已登记项目工作流版本。保留项目资料、启停状态与旧任务 pin。此后续授权不让当前实施者越过各自代码范围，也不允许在会话审计与优化完成前发布。

整理受管文件与文档归属，抽取完整项目服务及共用安全文件能力，固定按风险选择的测试入口和 PR/发布验证。只精确删除已证明有相同保留副本的本地历史发行文件；原始备份、批准和必要验收证据保留。

## 需求与验收

| 需求 | 完成标准 |
|---|---|
| REQ-STABLE-001 文档归属 | README 成为快速入口；用户指南、架构维护与 Homebrew 手册职责清楚；规则引用既有权威；发行白名单包含必要手册且相对链接可用，不打包 plans 和原型 |
| REQ-STABLE-002 服务职责 | 项目登记、名称解析、状态与组合计划归项目服务；模型事务保留独立职责；共享安全文件能力有唯一 owner；CLI/TUI 调用同一服务 |
| REQ-STABLE-003 依赖方向 | 公共路径校验不依赖安装入口；进程捕获归现有进程 owner；偏好服务直接消费私有状态的公开读取能力；精确前像、锁序、补偿及失败语义保持 |
| REQ-STABLE-004 验证入口 | 统一 unittest 分组入口，旧四入口薄委派并保持范围；错误参数和测试失败非零退出；PR 与发行门禁消费同一入口；不新增测试框架或安装渠道 |
| REQ-STABLE-005 历史清理 | 精确删除 dist/github-v0.1.0 下三份逐字节重复文件及空目录，保留 dist 根归档/校验与 Formula；.sync-backups、独立 Tap 历史和原始发行说明保留 |
| REQ-STABLE-006 行为稳定 | 实际 CLI/冻结核心、中央启停/pin、模型偏好及恢复、三宿主生成/软链、真实 PTY 与离线发行消费者通过必要验证；同一独立 QA 审查集成差量 |
| REQ-STABLE-007 lib 实质归组 | 36 个普通实现移入 install、project、documents、hosts、skills、delivery、central 七个实际职责目录；根目录保留 20 个有固定自举、协议或跨 pin 源合同依据的真实文件及必要的普通包标识；同步当前调用者、生成器、指令和测试，无转发 shim、路径回退或动态导入别名 |
| REQ-STABLE-008 实际会话审计与优化 | 只读审计 mt-shop 指定会话最近完整交付与阻断轮，按当时 pin 核对路由、子代理、QA、确认、重复读取和真实 usage；修正证实的入口歧义及中央诊断，保留只读／写入权限和冲突保护 |
| REQ-STABLE-009 发行与本机同步 | 使用未占用的 2.1.1 发布 GitHub Release 与同一构建的 Homebrew Tap；更新本机命令、中央核心与已登记项目绑定，保留五处源码修改、项目资料／启停状态／模型覆盖和旧任务 pin |

## 方案与原型关联

三个不重叠实施单元：服务与依赖整理；文档及发行消费者；统一验证入口与 CI。PM 维护本主题及同名生成 HTML，实施者各有独立工作树，集成后进行实际组合验证和唯一独立 QA。用户已批准建议范围，不重复需求确认。项目 parallel_worktrees.merge 为 confirm，最终具体候选通过后按该设置处理本地 main 交付。

服务单元新增 lib/project_paths.py、manager/state_files.py、manager/project_service.py，按真实职责原样抽取；保留不同事务的语义。TUI 仅调整服务调用归属，属于 UI-Conformance、design_delta none；权威为已验收工作台主题及未变的 tui_support.py/tui_state.py，不改原型、布局、按键或视觉值。保留 UI/可访问性审查及真实 PTY 验证。

文档单元将详细使用说明归 docs/usage.md，架构维护归 docs/development.md，复用 docs/homebrew.md。发行器仅白名单加入这些手册；迁移现有文档测试消费者，不以删除断言降低覆盖。共享 Skill、模板和产品规范留在现有源目录。本轮补齐原建议中的 lib 物理归组；不是将整个仓库搬到另一套包框架。

lib 归组独立实施单元接在当前三个已验证检查点之后，使用新的职责实例和一个独立工作树；保留先前成果与唯一 Reviewer。安装执行 5 文件、项目画像与配置 5 文件、文档原型 6 文件、宿主适配 9 文件、Skill 合同 5 文件、交付 4 文件、中央资源生成 2 文件分别归组。目录不做汇总重导出，依真实 owner 使用显式导入；不新增模块级环，不重写既有事务或校验器。

根目录例外来自活跃合同：python_runtime 两入口、windows_bootstrap、common.sh；预校验及加载链 platform_fs、runtime_store、windows_fs、runtime_bridge；task_graph_cli 与它的 8 个直接／动态任务协议依赖；跨 pin Hook 的 workflow_hooks；旧核心角色读取的 role_models；目标 Resources AST 工具常量读取的 validate_antigravity_artifacts。例外保留真实实现，不建兼容空壳。普通 lib/__init__.py 只作可信包标识，不导入或重导出任何能力；该修正来自真实调用方 lib 包抢占的失败验证。生成 launcher_source 与 hook_bridge_source 字节、固定工具常量读取、现有任务 pin 和用户文件保护均保持。

归组要校正 __file__ 根推导、可信直接脚本导入、vendor 实际路径、所有当前源调用及最小核心白名单。既有旧任务继续从自身旧 pin 消费旧核心路径；本轮用归组前真实已验证核心与新核心验证启用、切版、旧 pin helper／Hook、回滚及新核心不可用时的旧 pin 自举。该活动任务合同不等于恢复旧版本安装兼容。广泛导入／路径影响需要当前实际源码全量 unittest 验证；跨布局验证另用本请求唯一前后核心夹具，完整日志保留。

验证单元使用 scripts/test_workflow.sh，分组明确且无参数只展示帮助；不默认执行全套，不自动重试。保持现有测试节点，不为了本轮整理批量移动 TestCase。新增用例仅覆盖统一入口的真实参数/退出语义缺口。

## 当前进展与恢复入口

基础为 main aeb03f34195d6d5b77e430d3ea233c415e6d7f16。原仓五处外部未提交改动全部排除：notes-and-central-runtime.md/.html、lib/task_graph_cli.py、xy-qa-review/references/ui-review.md、tests/test_task_graph.py，不暂存、覆盖或回退。

本请求唯一 scratch 由 task_graph_cli 的 workflow-stability-20261107 解析；包含当前 graph、完整 Task Pack、各实施单元和 integration 工作树及必要原始日志。图是运行状态唯一来源；本节只记录恢复所需事实。验证入口 dcc00f5、文档发行 dd33f04、服务重构及 EOF 修正 52e7eff 已组合到 1915f515。该候选 84 项集成回归通过，原始失败及定向修复证据仍保留。唯一 Reviewer 已读规范并核对范围，尚未形成最终结果；用户追问原 lib 分组目标后，PM发现实施遗漏，暂停其旧范围结论，补齐归组后由同一 Reviewer 复用有效结论并审查完整当前候选。不能声明本轮已验收或合入 main。

归组单元实际根为本请求 lib-layout，基于 1427768；36 实现及当前消费者已迁移，228 条依赖边映射等价，两个生成薄桥字节保持。检查点 8b7b84b 已合入专用 integration。唯一持久路径索引在 docs/development.md，包含七职责的 36 行旧→新路径及 20 个固定根实现的逐项理由。初次 full：1282 项、1381.259 秒，149 failures、23 errors、20 skips，退出 1；路径修正与真实项目 lib 遮蔽负控修复后，19 定点节点通过。后续 184 节点实际执行了首轮被 setUpClass 阻断的 72 个 Codex 节点，剩余八个失败段来自旧夹具与英文锚点；最终四个方法覆盖全部残留分支，489.686 秒、退出 0。当前手册归档离线链接实际通过；原始失败和 skip 均保留，不宣称 Windows 原生通过。

同一真实夹具以旧核心 83f1bb362fd1488e723024dd40d69c2ba63eae32caebfee8aad87f434609df79 和新核心 414206353ba883f4a091e4d981769d2955bd6b0f78ec39d7d43bf48259c69652 验证启用、切版、旧 pin 资源／helper／Hook、回滚、再切版及新核心不可用时旧 pin 自举成功；旧 manifest 和全部旧文件保持不变。初次 Hook 脚本漏 cwd 的失败保留，修正后仅续跑失败分支。完整证据为 layout.log（751323 字节、SHA256 221d128b11a83087abb0a7facdeffe0c691922e5fe98a3887da4cf7be39b3807）、integration.log 及 layout-pin-check.py。当前尚待新布局组合验证和原独立 Reviewer 的完整范围审查，不能用归组前的 84 项结果替代。

历史精确清理已执行：再次核对三对完整字节、固定 SHA、保留归档校验与无匹配进程占用后，只删除 dist/github-v0.1.0 下三个重复文件和四个空目录，共 416855 逻辑字节；未递归删除 dist 或任何工作区，主仓五处外部修改不变。必要原件唯一或引用不明的内容均保留。原始执行输出已移交本请求 integration.log；单元完整证据分别为 services.log、docs.log、validation.log。

## 验收结果与当前已交付行为

结构单元候选 8050fed468fc6aa8ea6edc6e9809cf0913181db0 已完成归组后组合验证：84 项、207.342 秒、退出 0，无 skip，包含两真实 PTY、中央 CLI／pin、三宿主、Node 和 Ruby 发行消费者。原唯一 Reviewer 对 aeb03f3→8050fed 的 167 个路径独立 PASS，差量 SHA256 88ec937f54db0f01f048a35212d714637cc302a479b1efc102fdc276f8c95cf6；schema2 原生交接已由当前 helper 实际验证 valid。旧 guard 手册示例作为非阻断项交给后续修正。尚未合入 main 或发布，不把结构单元 PASS 扩大为整条用户任务完成。

随后完成指定会话两个近期工作轮的只读审计，事实来自精确 thread 01a1a531-1e4e-75e0-9d6f-a44107c1b26c 的原生 rollout，未扫描无关会话、修改业务代码或重跑旧测试。证实两项执行偏移：至少 65 个 exec 调用使用裸 python3，三处生成失败后仍继续检查旧图／旧派生页；最新独立只读审计误建 Full 实施图，并设置 read_only＋production_ui 的不合法字段组合。当时规则已有选择器／UTF-8／失败停依赖链与独立审计先分流，未证实选择器或 schema 源码 bug；不通过放宽 schema 或给审计者 writer 权限修复。当前改现有 Hook 提醒以消除把所有任务强制套入实施路由的歧义，不叠加同义规范或新阶段。

已核实八个新 spawn 均 fork_turns:none，14任务图均 fresh／handoff_only，唯一 QA FAIL 后由原实例做增量复核；原始直接开发和本轮 200% 例外有真实用户回复。规则重读主要跨两次真实压缩或补截断；未证实同事件重复 Hook 注入或无故保险重跑。原生主线程累计输入多数为缓存上下文，不等于唯一文本量，也不能据此虚报可节省 token、成本或全部子代理用量。可避免消耗是已证实的失败返工和错误建图。

mt-shop 的当前阻断来自一个原 AGENTS baseline 的保留节点缺失，当前 AGENTS 与登记前像完全一致，其他 35 个 retained 均一致。缺失原因无法从上述两轮归因；保护本身正确，诊断不应统称为后续保存。binding baseline、journal.binding_before 和当前 AGENTS 剥除唯一受管块后的 553 字节逐字节一致，SHA256 1696e9c2582488392c5009f5cdef9e03d109b3b20e624d092511d607ccc2dfa6，可在严格条件核验和证据保全后重建原字节并登记新 inode；不能声称恢复原 inode 或一般性放行 missing。一次性恢复仍待具体脚本独立审查，尚未执行。

审计后源码差量由 fresh／handoff_only 的职责实例在 audit-fixes 工作树完成，检查点 1c0d0fa80e59addbe25bcaf12120345843e1c166 已集成：现有 Hook 提醒先明确只读审计分流，冲突原因按缺失／内容类型／权限／身份准确区分，保护语义不变；四份手册改为长期有效的版本来源说明，旧 guard 命令按真实源包开发消费者归开发手册。七个定向节点全部通过，包含真实文件差异九子场景、旧 inode 后续保存阻断、未知手改拒绝、Hook 回调及实际归档链接，原件为 audit-fixes.log。未保险重跑全套或 PTY。

一次性恢复初稿 retained-recovery.initial.py SHA256 e6cb8af498b7c22c3d4224197a34ae07d424366422b2986f0ce1314764857683 完成默认只读预演和 14 项纯内存拒绝负控，但原 Reviewer 发现 F-RECOVERY-01：最终检查与发布器重新捕获前像间的外部保存可能被认领覆盖。QA 明确 FAIL，仅阻断该操作；未执行 apply。原始两日志、初稿及 FAIL 交接保留，负控驱动首次嵌套同一非重入锁的失败与修正亦保留。

同一职责作者完成最小修复，检查点 ea7e7d90defeb4a25200fa0053ba032b060b2b39 已集成：既有 write_private 新增可选 expected 完整 Node 参数，实际捕获前像后、建立发布见证前即拒绝失配；不传参数的现有调用保持原语义，内部发布守卫不变。三个真实文件合同方法通过：五个外部保存／替换／权限子场景均拒绝且保全新节点、无发布残留；匹配的缺失／现有前像正常发布，既有默认同步失败补偿保持。恢复脚本仅改为显式传入固定前像，当前 SHA256 41abb732a7e8edfb2f2f59b24a0063b4f346d85eb76e01c13dcf188909805701。真实恢复仍未执行，待精确交错负控及原 Reviewer 复核；发行、本机恢复和同步尚未执行。

原 Reviewer 已对 d376484 完整候选 PASS，F-RECOVERY-01 由实际 expected API 和精确交错拒绝负控关闭；schema2 当前交接实际 valid。该候选快进到 main 并推送，五外部修改的原 SHA 全部保持。一次性恢复的真实写入被自动审批因具体授权不足拒绝，命令未执行，已向用户请求该确切操作批准；不能绕过，亦不阻塞独立发行准备。

真实发行 run 42364434258：macOS 的 84 项全部成功，Ubuntu 同 84 项有两处链接替换夹具失败，release 被门禁跳过，未生成 2.1.1 资产。两夹具先 unlink 再重建同 target，未保证生成不同 inode；原日志没有记录 inode，不能假称已在 Linux 实测复用。fresh／handoff_only 作者只改 tests/test_central_project.py：保留旧 inode 后同 target 重建、显式断言新旧 inode 不同，原 helper 拒绝及 repair 冲突断言全保留，生产合同／代码不变。本机两个方法一次执行 6.455 秒、退出 0；完整 ci-portability.log 和首次远端失败原件保留。接下来仅同 Reviewer 测试差量复核，再以新提交运行真实双系统发行门禁。

## 批准依据与必要证据

截至 2026-11-07，当前源码及发行已交付：原唯一 Reviewer 对 246cdd46d36ef12b8efd29f5cbb957a229a3acd7 的完整 167 路径 PASS，交接实际 valid；真实 run 42365526185 的 Ubuntu／macOS 各 84 项及 release 全部 success。v2.1.1 标签精确指向该提交，GitHub Release 已公开，归档 SHA256 065b39c02ecbc95ec2b8ca6bd2bdaabfd08595b171389ccaf01325d06bbd6da9 与附带校验／Formula 一致；Tap c73a089 已推送相同 Formula，没有恢复 npm/npx。

本机 Homebrew 已从 2.0.3 升到 2.1.1，真实 brew test 通过；其自动打开的 developer mode 已恢复关闭。原 ~/.local/bin 源码入口保持，当前源码与 Homebrew 入口版本均为 2.1.1。正式发行核心已导入 ~/.config/agent-workflow/runtimes/660e8e9bb7ca8172187af37c1466c00cdad591436980ecf5f6b0fca9114b179e/core；旧核心未删除。

ParentsKit 与 TeachingAssistant 预览无冲突后，已实际切到该正式核心，均 enabled、无 conflicts／pending_transaction；previous_binding 保留原版，实际经各项目薄桥指定旧 pin 读取 product/VERSION 得到 2.1.0。三个项目 project.yaml 和全局角色模型偏好 SHA 均与同步前相同。mt-shop 未执行恢复或选版，绑定保持 be648cb…、明确诊断保留旧 inode 路径缺失；其 553B 备份重建及新 inode 登记的具体用户批准仍待回复。该项未完成，主题保持 active；不得绕过自动审批拒绝或把本机三项目同步报告为全部完成。对应实际结果保存在当前请求的 sync-verification.json、发行与本机验收原始记录中。

- 批准依据: 用户本轮“开始优化，将历史无用的该清理的进行清理”，承接前一轮文件归属、lib 按职责分组、服务职责和固定回归建议；后续追问 lib 分组是否纳入，PM补齐原已批准目标的实施遗漏，不增加产品功能或设计选择，不重复需求确认。
- 验收证据: 唯一 QA 当前 PASS、首次 FAIL 与修复闭合原件，真实双系统发行 run 42365526185、正式 v2.1.1 三资产及 Tap c73a089、Homebrew 实际升级／test、sync-verification.json；完整原始日志保留在本请求既有证据区。mt-shop 恢复 apply 未执行，不存在该操作的成功证据。
