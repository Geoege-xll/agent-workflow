# Claude 辅助 Hooks

本包默认合并项目 `.claude/settings.json` 中带内容签名的辅助 Hook 条目。
仅注册 SessionStart、UserPromptSubmit，以及匹配 Agent 的 PreToolUse；后者只在 Explore
派发时提醒“普通进度询问原工作 Agent”，不阻止正常探索，也保留用户明确查看进度的例外。

安装器只拥有签名一致的本包条目，已有权限、MCP、插件、Claude Auto Memory 和所有
非本包 Hook 都由用户管理；`autoMemoryEnabled` 不会被修改。受管条目若被修改，
安装器停止覆盖，不靠名称或路径认定所有权。没有默认硬性写入禁令。

完整开关、信任边界、三平台差异与验证方法见 [共享 Hooks 说明](../../shared/HOOKS.md)。
`scripts/guard.sh` 仍是模块归属的 report-only 检查，不是 QA 或权限锁。
用户已有硬 Guard 不会被本包删除、接管或中和。
