---
name: xy-grilling
description: "Load the complete bundled Grill Me interview primitive for PM requirements coverage under the existing workflow."
---

# Grilling 配套需求访谈（本项目薄适配）

这是上游Grill Me的配套primitive grilling在本插件的公开入口。PM主会话主动完整读取，不能依赖Worker预载，用户不必先显式调用xy-grill-me。原版在 `third_party/selected-skills/grill-me/skills/productivity/grilling/SKILL.md`，真实名称、正文和元数据不改；本说明不是原文摘要。

先调用当前物理插件 `plugins/source_pack.py selected-skills check`，再 `selected-skills read xy-grilling --offset 0 --length 12000`，完整阅读content，按next_offset连续读至eof=true。无Skill工具也可由 `resource third_party/selected-skills/grill-me/skills/productivity/grilling/SKILL.md` 定位并完整读取；不得回退未知全局同名Skill。

用户和项目规范、角色所有权、唯一PM派发、独立上下文及两步确认优先。复用现有已确认事实，按当前覆盖判断提问；frontier为空不制造问题或重启任务。上游共享理解确认并入既有requirements_approved，不另加前置确认。Worker不嵌套委派，用户禁止代理时遵守；此入口不直接批准、dispatch实现或改生产文件。内部coverage/grill_result schema属于xy-workflow适配，不冒称上游合同。
