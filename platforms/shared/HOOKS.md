# 辅助 Hooks：安装与边界

这是可关闭的本地脚本辅助层，不改变 Trivial/Light/Full、两项业务确认、原型选择、
用户明确跳过流程/亲自实现、不更新原型、单次集成 QA、计划与文档/agentmemory 按需原则。
Hooks 不判断需求是否获批、任务是否完成，也不提供工作流“必然遵守”的保证。

## 各平台的原生接入

| 平台 | 项目配置 | 本包事件及作用 |
| --- | --- | --- |
| Codex | `.codex/hooks.json`；已有 TOML Hooks 时沿用 `.codex/config.toml` | SessionStart 的 resume/compact/clear/fork 恢复提醒及入口资源检查；UserPromptSubmit 简短任务路由提醒 |
| Claude Code | `.claude/settings.json` 的 hooks 字段 | 同上；Agent/Explore 派发时提醒进度询问原工作 Agent |
| Antigravity App/CLI/IDE | `.agents/hooks.json` 中单独命名的配置 | 原生 SessionStart 在新会话启动时给出短入口提醒，不在每次模型调用重复 |

AGY 接入依据为当前官方 SessionStart 合同，不再写临时去重标记或注册 PreInvocation。
升级只迁移签名仍完整的本包旧事件，保留 enabled:false 和用户其他 Hooks；用户修改过的
同名条目停止升级并保留。旧去重缓存不再使用，也不在安装时扫描或删除它们。
SessionStart 只代表新会话开始，不代表新的用户轮次或压缩恢复；本包仍不根据 invocationNum、
initialNumSteps、用户消息或 transcriptPath 猜任务/批准。各客户端逐步发布，官方未标明
SessionStart 的最早支持版本；生成与 --check 通过不能替代目标客户端的实际事件验收。

Codex 已通过 SessionStart(compact) 恢复压缩后的上下文，本批不再同时注册 PostCompact，
避免重复注入；fork 只提醒核对当前工作区和现有证据，不创建新的批准或写入权限。

Claude 同样在 SessionStart(compact) 注入恢复指令。PreCompact/PostCompact 会忽略
`systemMessage` 和 `continue`，PostCompact 也不能把恢复指令加到模型上下文；
PreCompact 的阻止压缩合同不用于本包门禁。Codex 的压缩事件忽略普通文本 stdout，
也不借 `continue:false` 阻止压缩。本包不额外注册这两个事件、不读写压缩摘要日志。
恢复仍核对原计划、当前工作区和持久证据，不能从压缩摘要推断批准或 QA PASS。

三平台使用同一个 Python 标准库脚本，每次超时上限 3 秒。脚本只读小型配置/入口，
不联网、不调用模型、不扫描业务 diff、不读子会话历史、不自动测试、提交或改项目文档。
入口资源就绪不是任务遵循证明，更不是 QA PASS。没有 Stop/结束时强制继续，没有
PreToolUse allow/deny，也不修改工具参数。脚本故障返回中性结果，原生权限照常生效。

从项目子目录启动仍绑定实际项目入口；Git worktree 只在共同 Git 仓库可核实时使用
当前工作区规则。不同项目、嵌套项目及无法确定的多工作区不借用本项目状态。

## 开关与所有权

安装前在包内、安装后在项目 `.agent-workflow/project.yaml` 的 `workflow_hooks.mode`
选择 `assist`（默认）或 `off`。改为 off 后运行 `bash .agent-workflow/setup_all.sh`，
只撤下可证明属于本包的 Hook 条目，保留用户其他配置与 Hook；不兼容旧工作流格式。
临时关闭脚本提醒可在启动宿主前设置环境变量 `AGENT_WORKFLOW_HOOKS=off`。
原生禁用开关也保留，不强制开启 Codex features.hooks、Claude disableAllHooks，或 AGY
条目的 enabled。本包只拥有内容签名一致的条目/块；签名是覆盖保护，不是安全认证。

Claude 的 `claude_options` 是独立的可选原生能力，并非 Hook 门禁。
`auto_compact_windows` 按规范角色生成完整整数的 `autoCompactWindow`（2.1.296+）；
只降低继承窗口，全局 `CLAUDE_CODE_AUTO_COMPACT_WINDOW` 通常覆盖它。
写入保护默认 inherit；显式 true 时只合并原生
`permissions.blockWritesOutsideWorkingDirectories: true`（2.1.314+），保留其他权限。
项目/local 明确 false 或无效值会停止预检；off/inherit 都不自动写 false 或移除已启用保护。
该设置只约束 Write/Edit/NotebookEdit，实际工作目录、Bash、任务 owned_paths 和组织策略
仍依各自合同。安装事务复用现有配置快照，不另造权限备份或审批台账。

Codex 的项目配置和精确 Hook 定义必须经过原生信任审查。CLI 可在 `/hooks` 查看；
桌面使用原生审查入口。升级后的定义可能需要重新审查。安装器不预写信任记录、不
使用 dangerously-bypass-hook-trust；安装成功不等于 Hook 已获信任或实际执行。
本地命令 Hooks 不适用于 Codex 云端编排，不能将本地验收结论套用到云端。

## 验证范围

`setup_all.sh --preflight` 只预检，`--check` 校验生成的受管配置与安装源一致，不能证明
模型服从流程。测试覆盖三平台 JSON 输入输出、失败中性处理、开关、项目/会话/worktree
隔离、重复注入抑制、用户配置保护，以及真实安装命令的回调契约。

宿主实际行为仍应使用少量代表性任务验证：只读问答、改字、明确跳过流程、Full 多模块、
A 完成后继续关联 B、上下文恢复和询问原工作 Agent 进度。比较 Skill 是否触发及触发后
是否遵循规则；不把“配置存在”当作行为测试通过。不为测试修改真实项目或绕过信任。

需要诊断时可按需使用 Claude `/doctor prompt-audit`、`/skill-doctor` 或宿主 `/hooks`；
它们不是每次任务的必跑步骤，本包不安装监督 Agent、Mods 或额外插件。

官方依据：[Codex Hooks](https://learn.chatgpt.com/docs/hooks)、
[Claude Hooks](https://code.claude.com/docs/en/hooks)、
[Antigravity Hooks](https://antigravity.google/docs/hooks)。
