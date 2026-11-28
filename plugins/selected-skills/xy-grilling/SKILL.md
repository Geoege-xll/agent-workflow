---
name: xy-grilling
description: "Use the bundled interview primitive when the deliverable, scope, impact or acceptance is too unclear for the PM to classify the request."
---

# Grilling 配套需求访谈（本项目薄适配）

PM 自行判级时先确定本轮交付与授权。实施范围、影响和验收清楚时直接判 Light 或 Full。可查事实仍不足以明确其中某项时，才选用本入口，围绕该项分歧提问，补齐后可判任一等级。用户显式调用访谈或由显式的 `xy-grill-me` 转入时，按其委托的访谈范围使用原版。讨论中的答复只澄清需求，明确委托后才执行。

安装包在下方直接提供已按锁校验的 `grilling` 完整原文。源码开发时，原文位于 `third_party/selected-skills/grill-me/skills/productivity/grilling/SKILL.md`。仅阅读此技能无需运行命令。

用户和项目规范、角色所有权、唯一PM派发、独立上下文及当前请求适用的确认优先。复用现有已确认事实，按当前覆盖判断提问；frontier为空不制造问题或重启任务。依当前等级复用有效范围授权；需要需求确认时，上游共享理解确认并入既有 requirements_approved。Worker不嵌套委派，用户禁止代理时遵守；此入口不直接批准、dispatch实现或改生产文件。内部coverage/grill_result schema属于xy-workflow适配，不冒称上游合同。

## 随包原文
