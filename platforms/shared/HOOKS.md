# 3.x 插件的宿主入口

Codex 的插件包声明 SessionStart Hook。用户在官方客户端的 `/hooks` 中核对并信任定义后，新会话可以收到主会话入口提示。提示只负责把本轮显式维护调用或业务请求交给相应流程。安装、信任、事件执行和 PM 实际接管分别核验。

Claude Code 使用插件的 PM Agent 和官方默认设置。Antigravity 使用插件声明的规则及原生 Agent。用户级和项目级的权限、信任与自有 Hook 由相应客户端管理。

按当前宿主的实际入口验证首次业务任务、A 运行中追加 B、同任务追加与独立 QA。安装命令和平台差异见插件随包的 `INSTALL.md`。

Antigravity CLI 还从插件根的 `hooks.json` 加载原生 PreToolUse 写入守卫。启用后的主会话可读、准备任务、派发与核验。业务文件编辑按当前用户指令、原生派发回执和任务范围判断，宿主继续执行自己的权限检查。当前 CLI 的工具、用例与适用边界见 AGY 包内 `platforms/antigravity/references/pm-integration.md` 的「CLI 工具执行前的写入分工」。
