# npm／npx Windows 安装渠道移除与稳定版收尾

- 主题 ID: `PLAN-WINDOWS-CENTRAL-NPM`
- 阶段: `completed`
- 模块: `.`
- 任务等级: `Full`
- 已验收版本: `2.1.1`

## 目标与范围

用户先要求取消 npm 安装方式、清理干净 npm，随后明确最终范围为“彻底移除 npm/npx Windows 安装渠道，审计只用于收尾”。本轮撤下项目自身未发布的 npm/npx Windows 分发路线，不继续修复其安装器或尝试让旧链路验收通过。中央运行时、CLI/TUI、Homebrew 和源码安装保持既有职责；不改既定工作流、不做旧版兼容或立项讨论入口。

从已公开稳定基线 e2c981b1f5ff31e5cda41365682605ff747f3000 形成2.1.1候选。未验收Windows/npm实验完整保留在旧请求工作树及提交60c522b287bf335ec8bbb9e6f3e103f5e2ed433b、原日志和执行快照中；新候选不自动引入它们。原仓五处外部未提交修改原样保留，不暂存、还原或混入本轮。现有项目文档和三业务项目不修改，npm账号和系统Node/npm及共享缓存不处理。

## 需求与验收

| 需求 | 完成标准 |
|---|---|
| REQ-RETIRE-001 渠道撤下 | npm包入口、元数据、渠道专属notice、离线构建器／下载锁、Windows npx CI和专属E2E退出当前产品；无可执行的npm安装／发布入口或继续开发该渠道的有效声明 |
| REQ-RETIRE-002 依赖收口 | 沿真实调用边界清理npx安装指引和仅供该渠道的部署分支；通用Python启动器、跨平台安全合同和有效测试按实际依赖保留，必要时将混在npm目录或打包测试中的通用测试移到原测试目录；不提供替代兼容入口 |
| REQ-RETIRE-003 稳定性 | 中央运行时、CLI/TUI、Homebrew与源码安装未产生行为回归；业务项目npm/pnpm识别和需求页固定Node渲染能力保留；product/VERSION及实际版本消费者统一2.1.1，不机械改写有意义旧版本fixture |
| REQ-RETIRE-004 收尾证据 | 必要构建／真实消费者与单一独立QA成立；QA覆盖清理完整性、通用测试保全、资料与失败事实保全，不以审计旧Windows/npx为名继续实施或宣称其已通过 |

## 方案与原型关联

non_ui，不改TUI界面或读取原型／设计规则。生产交给fresh／handoff_only后端系统单元，不复制完整PM或兄弟会话。先按已列文件的真实依赖区分渠道专用与通用部分，再删除／迁移／调整现有边界，保持最小职责清晰的改动，不添加通用清理框架或替代发行渠道。PM只维护计划、记录、Git与集成。

必要验证从真实依赖选择：保留的Node启动器合同、通用Windows安全测试的实际迁移与导入、macOS中央安装／薄桥、Homebrew归档及启动版本。复用未改变的TUI／PTY／宿主行为证据，不触发旧Windows npx CI或下载CPython，不运行npm publish。新增回归只补实际缺口；达到必要覆盖后进入唯一独立QA。

交付使用独立实施与集成工作树，主分支基线固定e2c981b。项目merge:confirm仍在最终候选通过QA后作一次具体合并决定；原仓五处修改不由本请求清理。GitHub/Tap公开2.1.0资产不覆盖，2.1.1不自动发布。

## 当前进展与恢复入口

当前唯一执行请求为retire-npm-channel-2.1.1-20261107，scratch由现有task_graph_cli分配，实施根npm-retirement、集成根retirement-integration。fresh后端单元已完成生产清理并交接BUILD_VERIFIED：12条渠道专用路径已移除，Node6个通用合同逐字节迁入tests，bootstrap3个与原生文件系统11个方法AST保全；通用启动器和安全边界保留，当前源码为2.1.1。唯一handoff为retirement-handoff.json，完整命令和原始输出在retirement-implementation.log。

必要实际消费者已经通过：Node6例、共享安全40个有效节点、macOS交互中央安装／固定pin helper／源码版本3例、Homebrew真实归档到Formula安装后版本1例；共享组首次误写类名及过时PreInvocation夹具的原始失败保留，只补跑缺失和修复的7个节点，未修改生产拒绝旧事件的语义。Windows原生11例保留但本轮未执行，不作为成功证据。PM已读相关源／差量与完整执行结果，并以现有fingerprints核对33项实际输入匹配；实际集成根的中央CLI／固定pin helper／repair／disable／delete消费者1 test／9.311s通过。

唯一独立QA已对清理组合给出PASS，27路径与29工程规则完整覆盖；原始schema2结果和当时完整QA包保留，PM已正式validate为valid。首次审查仅有本计划末尾空行格式nit，已并入当前受控投影修正，不把原完整范围diffcheck的exit2改写为成功。最终文档delta已由同一Reviewer复核，当前完整原生交接retirement-qa-handoff.json绑定最终候选48332a1，PM正式validate为valid，无剩余阻断项或格式nit；未重复未变程序回归。

旧windows-central-npm-2.1.1-20261107目标已取消，作者已停止并退役，旧图保留实际失败而非BUILD_VERIFIED／QA PASS。旧Windows源码中央单项曾通过普通用户安装／固定pin/helper／重复安装，但npx产品init与真实Hook没有进入成功验收。

旧最后诊断run42344893409／60c522b仍失败：系统PS5.1查到PS7 Security模块在前，固定系统模块可以导入，原只读query继续失败；不再沿该机制修复。旧完整windows-capabilities.log保留1112233字节，SHA759e9cb618e16f0b8fdcbc731fc1c09941d40ae34d4dccbc6f231093a435e648；其余原生日志、作者日志、handoff和执行源码快照都留在原请求scratch，不复制成新报告。新请求仅保留本轮必要日志与交接。

source-pack缺docs/PROJECT.md与docs/STANDARDS.md，指纹null；适用29工程规则来自现有内置源，不造空索引、不假报全仓文档校验成功。memory.project_id仍模板，provider缺严格项目过滤和provenance，不recall/save。原仓五处修改逐项指纹与清理前一致。用户在最终QA后明确批准普通Git快进合并并保留这五处修改；main已从e2c981b快进到48332a162170a41e41f4ecc5a73f0245b6858b08，合并后五处指纹仍全部匹配。2.1.1本轮未公开发布。

## 验收结果与当前已交付行为

本主题已交付2.1.1清理版本至本地main：npm/npx Windows渠道的12条专属路径撤下，通用启动器／安全边界及有效测试保全，业务包管理器发现和固定Node渲染能力继续保留。该验收针对渠道移除与保留能力，不代表Windows安装通过；旧Windows/npx实验没有完成完整安装验收，不作为当前产品能力或默认恢复入口。

实际代码交付为main上的48332a162170a41e41f4ecc5a73f0245b6858b08，使用用户批准的merge --ff-only完成，无stash/reset或合并冲突处理。公开GitHub/Tap2.1.0、原仓五处未提交修改和三个业务项目保持原状；尚未公开发布2.1.1。本次合并后仅补记交付事实及生成页的实际项目根归属，不改变生产行为、协议、权限或宿主配置。

## 批准依据与必要证据

- 批准依据: 用户明确“清理干净npm”，并最终选择“彻底移除 npm/npx Windows 安装渠道，审计只用于收尾”；该指令替换旧Windows/npm实施目标，未授权恢复旧链开发。
- 验收证据: 清理实现、通用测试迁移、必要真实消费者及精确集成证据已核；唯一独立收尾QA原始结果retirement-qa-initial.json与完整QA包绑定，PM验证valid。最终文档delta已沿同Reviewer及当前完整最终QA包验证PASS，PM验证valid；完整失败／成功日志和旧取消事实保留。本地main已完成明确批准的快进交付，2.1.1公开发布未执行。
