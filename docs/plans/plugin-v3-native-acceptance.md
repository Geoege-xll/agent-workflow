# 3.0 原生客户端验收

本轮由用户授权使用本机 Codex CLI、Codex App、Claude Code 完成验收；同时补齐可用的第三平台原生校验。生产修复按宿主职责分工，新实例只收到当前最小任务包。源码基线为 `5b2070b`，修复候选工作流为 `3.0.0-alpha.3`，独立配置工具仍为 `0.1.0-alpha.2`。

验收目录为 `/private/tmp/awf-native-acceptance`。其中是脱敏事件、临时项目、配置保存收据和对照实验；不复制认证文件，不改写 HOME/CODEX_HOME，不以直接写入客户端信任状态或业务项目根指令文件制造入口。

## 已定位的原生交付缺陷

| 问题 | 原生失败证据 | 修复边界 |
| --- | --- | --- |
| Codex 0.167.0 未发现插件 Hook | 四个真实官方安装对照：仅纯 `.codex-plugin/plugin.json` 能发现 Hook；带根 portable 清单的三个形态均未发现 | Codex 使用单一官方兼容清单；保留正常发现、官方 review/trust 和新会话加载 |
| AGY Skill 正文被截断 | CLI 1.5.5 严格校验报告 `xy-workflow` 为 24,397 字节，原生只加载前 24,000 字节 | 精简 AGY 宿主适配说明，完整保留共用正文；记录真实 adapter 来源，并在构建时拒绝超限 |
| 长文读取的宿主截断未在入口明确处理 | Claude 原生结果包含 `startLine:1`、`numLines:1278`、`totalLines:1521`、`truncatedByTokenCap:true`；部分能力探针未续读，不能算完整流程证据 | 资源适配层明确缺失范围续读或复用已有分页 helper；真实新 PM 已按 1–1278、1279–1521 连续读取，不从头重读 |
| 技能策略示例与实际任务 schema 不一致 | `xy-qa-review/references/inputs.md`、`product/WORKFLOW.md` 与派发说明的示例将 `required_skills`、`audit_surfaces` 放在 `skill_policy` 下；真实 Codex PM 照此构造被原 helper 拒绝 | 三处统一使用原 schema 的 `task` 成员字段，并保持 `qa_scope` 的真实层级；同一个测试覆盖三示例 × 三宿主，不放宽 schema、不增加兼容分支 |

Codex 对照插件均已由官方命令卸载并移除临时市场。必要测试覆盖 Hook 清单单入口、权威正文与实际适配来源、UTF-8 字节预算和超限拒绝；不能靠删除共用流程正文通过校验。

## 本机观察与回归

| 行为 | 已取得的证据 | 范围 |
| --- | --- | --- |
| Codex 普通默认入口 | 默认功能开关下，原生 `hook/completed` 来源为 plugin、状态 completed；随后读取该版本 cache 的 Skill、PLUGIN 与工作流 | CLI/app-server；不替代 App 图形界面 |
| Codex 停用对照 | 进程级官方配置停用候选后，候选 Hook 数量及执行次数为零，两个原有用户 Hook 保留 | 不写用户全局配置的对照实验 |
| Claude 默认 PM | 无 `--agent` 时 `SessionStart.agent_type=agent-workflow:pm`；同项目不加载候选的负控没有该值 | 官方临时 `--plugin-dir`，使用现有登录 |
| Claude A/B/C | B 的原生 Agent 在 A 首次结束前启动；C 的 `SendMessage` 指向原 A ID，并由该 ID 返回 ACK | 插件限定的真实原生角色；不以 description 代替原生 ID |
| Claude 模型与推理配置 | 临时项目定义经 ModelService 发现、预览、保存；新子代理 model 为 `gpt-6.1-sol`，宿主 effort 为 high，PM 为 low | 保存回执仍保持 `runtime_verified:false`，实际执行另以宿主证据确认 |
| Codex 模型与推理配置 | 临时项目原生定义保存后，实际子代理事件解析模型为 `gpt-6.1-terra`、effort 为 low | 单项执行证据，不提前扩大为完整 A/B/C 收口通过 |
| AGY 原生交付 | CLI 1.5.5 strict 校验与官方安装/list；9 Skill、7 Worker、1 Rule，主 Skill 正文小于 24,000 字节 | CLI 校验和安装；模型派发另判 |

Claude 的 `model` 字段虽然已保存且有原生运行结果，但主 PM 与该子代理均使用 `gpt-6.1-sol`，不能单独证明模型覆盖的差异因果。已用当前 alpha.3 包做一次不同模型的受限对照，现有 `sonnet` 映射指向 `gemini-3.8-flash-high`；23.545 秒内没有取得有效模型回答并已回收进程。该项保持 `NOT_PROVEN`，不能断言模型永久不可用，也不影响原有 effort high/low 的差异证据。

AGY 的实际原生派发已取得 `xy-backend` 实例 ID；已核对七个角色声明的工具在实际 CLI init schema 中均存在。子代理读取审批等待超时后进入 idle，完整 fresh/handoff_only、独立 QA 和 A/B/C 收口不标通过。临时 `--agent` 新主会话能读取配置探针标记，只证明定义重读；主会话 `/model` 仍报告 Argon 模型，不能替代子代理 `model:flash` 的实际路由证明。精简证据及具体限制在 `agy/summary.json`。

AGY 已通过原生管理接口回收两个临时子代理，后续列表为空，TTY 正常退出，自有 CLI 进程为零。候选通过官方命令停用，其他插件状态保持；首启记录包含默认终端主题、拒绝可选交互数据收集和仅临时项目信任。未修改 PATH、HOME、认证或业务项目。

Codex 的完整后续输入已取得证据：B 在 A 首次完成前创建；C 进入同一 PM 后并入原 A，A idle 后经同 ID followup 恢复，读取 revision 2 包并完成追加任务，没有新建 A。唯一原生 QA 返回 schema 2 的完整 `PASS` JSON，原 PM 经原 helper 验证为 `valid` 并成功提取结果，随后回合完成。保留首次驱动漏识别新事件、720 秒中断，以及从原父 PM 恢复原 QA 的全部失败与恢复记录；不以重建 Reviewer 掩盖中断。

原生生命周期单列：原 PM 后查只列自身，三个原 ID 的官方状态均为 `notLoaded`，自有进程退出，记录的逻辑退役成立。该会话没有 `close_agent` 或等价关闭工具，故不声称完成显式关闭或直接证明平台容量释放。完成的任务与卸载状态允许结束本次候选安装测试，不能扩展为活动任务跨插件更新保留通过。

本轮本机 `current` 初跑 **397 项**：394 通过、2 个旧适配测试失败、1 个既有 Codex 官方临时隔离 skip。两处失败保留在 `/private/tmp/awf-native-acceptance/current-alpha3.log`；修复的是测试固定通用适配路径和英文句子的假设，完整正文、来源摘要与禁止继承历史的断言保持。相关合同及 AGY 定向 **17/17** 通过，长文装配保真另 **1/1** 通过。这里不将该次 exit 1 的全量初跑改写为完整绿色运行；最终提交另取实际 CI 结果。

`ee3ec56` 的真实 CI 已成功：Mac/Linux 各 398 项，394 通过、4 个环境限制 skip，候选上传成功，日志与包摘要已保留。之后同类检索发现另外两处策略示例仍错误，因此该提交只作为历史候选，未宣布最终交付。新增测试现对三示例 × 三宿主逐个执行原 helper `init → validate`，九个旧嵌套负控均拒绝且不生成输出。最终净源由新提交重新构建，并以对应修订的真实 CI 和包摘要为准，不能复用旧包冒充新修复。

## 验收判定边界

发现、安装、模型响应、默认 PM、原生派发、推理生效、持续接单和最终收口分别判定。来源自报或模型回答“已使用工作流”不能代替宿主事件与实际产物；配置保存也不能代替新 Agent 的真实执行证据。

Codex App 的 `com.openai.codex` 入口被 Computer Use 工具明确禁止访问，用户授权不能解除此项工具限制。没有改用其他界面自动化绕过；CLI/app-server 的协议验收不替代 App 界面验收。已准备独立临时项目和最小人工观察任务，实际结果待记录。

活动任务跨官方插件更新的自动资源保留协议仍未实现；当前 alpha 限制为先收尾再更新，不能把普通停用/启用或空闲更新的成功写成活动任务热更新通过。Windows 保持暂停。

本页随本轮证据结算更新；本轮独立 QA 和最终精确构建摘要完成前，不声明稳定发行或三平台完整运行通过。
