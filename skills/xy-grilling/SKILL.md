---
name: xy-grilling
description: "Use the bundled interview primitive when the deliverable, scope, impact or acceptance is too unclear for the PM to classify the request."
---

# Grilling 配套需求访谈（本项目薄适配）

PM 自行判级时先确定本轮交付与授权。实施范围、影响和验收清楚时直接判 Light 或 Full。可查事实仍不足以明确其中某项时，才选用本入口，围绕该项分歧提问，补齐后可判任一等级。用户显式调用访谈或由显式的 `xy-grill-me` 转入时，按其委托的访谈范围使用原版。讨论中的答复只澄清需求，明确委托后才执行。

安装包在下方直接提供已按锁校验的 `grilling` 完整原文。源码开发时，原文位于 `third_party/selected-skills/grill-me/skills/productivity/grilling/SKILL.md`。仅阅读此技能无需运行命令。

用户和项目规范、角色所有权、唯一PM派发、独立上下文及当前请求适用的确认优先。复用现有已确认事实，按当前覆盖判断提问；frontier为空不制造问题或重启任务。依当前等级复用有效范围授权；需要需求确认时，上游共享理解确认并入既有 requirements_approved。Worker不嵌套委派，用户禁止代理时遵守；此入口不直接批准、dispatch实现或改生产文件。内部coverage/grill_result schema属于xy-workflow适配，不冒称上游合同。

## 随包原文

---
name: grilling
description: Grill the user relentlessly about a plan, decision, or idea. Use when the user wants to stress-test their thinking, or uses any 'grill' trigger phrases.
---

Interview the user relentlessly until you reach a shared understanding. Map this as a **design tree**: every decision branches into the decisions that hang off it.

Work the tree in **rounds**. The **frontier** is every decision whose prerequisites are already settled: the questions you can ask _now_ without guessing at answers you haven't heard yet. Ask the whole frontier in one round: number each question and give your recommended answer. Then wait for the user's answers before the next round.

Format a round like so:

```
❓ **Q1** - **<question title>**: <question body, might be multiple paragraphs, including multiple choices>

➡️ <your recommended answer>

---

❓ **Q2** - **<question title>**: <question body, might be multiple paragraphs, including multiple choices>

➡️ <your recommended answer>
```

Word each question so "yes" accepts your recommended answer.

Each round the user answers reshapes the tree: settled decisions push the frontier outward and unblock questions that depended on them. Recompute the frontier and ask the next round. A question whose answer depends on another question still open in this round belongs to a _later_ round, not this one.

Finding _facts_ is your job, never the user's. When a frontier question needs a fact from the environment (filesystem, tools, etc.), dispatch a sub-agent with a fresh context window to find it; don't ask the user for anything you could look up yourself. Don't block on it: a running exploration is an unsettled prerequisite, so only the questions downstream of it wait for the sub-agent to report; ask the rest of the frontier now. The _decisions_ are the user's: put each to them and wait.

The session is done when the frontier is empty: every branch of the design tree visited, nothing left silently assumed. Do not act on it until the user confirms you have reached a shared understanding.
