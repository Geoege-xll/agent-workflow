---
name: xy-grill-me
description: "Explicit user entry for the bundled original Grill Me; read its complete canonical skill and same-plugin grilling primitive."
disable-model-invocation: true
---

# Grill Me 用户显式入口（本项目薄适配）

仅当前用户直接点名此入口才可调用。安装批准、其它Skill建议、PM自动接单或Worker转述不算用户显式调用；自动需求覆盖入口是同一物理插件中的 xy-grilling。

安装包在下方直接提供已按锁校验的完整原文。源码开发时，原文位于 `third_party/selected-skills/grill-me/skills/productivity/grill-me/SKILL.md`。仅阅读此技能无需运行命令。

原文的 `grilling` 调用指向同一物理插件中实际发现的 qualified `xy-grilling`，在 Claude Code 中为 `/xy-workflow:xy-grilling`。缺少 Skill 工具时，从同包发现目录完整阅读该原生入口。保留用户/项目权限、既有事实、需求确认和唯一 PM 调度；不调用未知全局同名 Skill。

## 随包原文

---
name: grill-me
description: A relentless interview to sharpen a plan or design.
disable-model-invocation: true
---

Call the Skill tool with "grilling".
