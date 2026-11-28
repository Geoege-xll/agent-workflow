# 3.x 插件的宿主入口

Codex 的插件包声明 SessionStart、PreToolUse 和 Stop Hook。用户在官方客户端的 `/hooks` 中核对并信任定义后，新会话可以收到主会话入口提示。Stop 在本轮即将结束时，只读查询当前物理工作目录与原生主会话身份对应的任务池。如果仍有已绑定的只读或证据任务占用，可以在同一轮提示 PM 通过原生结果和现有证据流程核对一次。结算和后续领取由 PM 使用现有入口。安装、信任、事件执行和 PM 实际接管分别核验。详见 [Codex Stop Hook](https://learn.chatgpt.com/docs/hooks#stop)。

PreToolUse 在官方信任后检查物理已配置项目及其已核实 worktree 的常规写入。已领取、原生身份已绑定且当前门禁有效的 Writer 可编辑授权路径。PM 继续读文件、登记、派发、验证及维护项目计划。当前用户明确指定 PM 实现时，守卫只放行能从当前原生用户消息核对的具体目标。独立 QA 保持只读。覆盖工具、命令及恢复入口见 [Codex 项目写入分工](../codex/references/pm-integration.md#codex-项目写入分工)。

Claude Code 使用插件的 PM Agent 和官方默认设置。Antigravity 使用插件声明的规则及原生 Agent。用户级和项目级的权限、信任与自有 Hook 由相应客户端管理。

按当前宿主的实际入口验证首次业务任务、A 运行中追加 B、同任务追加与独立 QA。安装命令和平台差异见插件随包的 `INSTALL.md`。

Antigravity App 和 CLI 从插件根的 `hooks.json` 加载原生 PreToolUse 写入守卫。启用后的主会话可读、准备任务、派发与核验。业务文件编辑按当前用户指令、原生派发回执和任务范围判断，宿主继续执行自己的权限检查。工具、用例与适用边界见 AGY 包内 `platforms/antigravity/references/pm-integration.md` 的「App 与 CLI 工具执行前的写入分工」。
