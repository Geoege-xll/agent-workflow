---
name: xy-grilling
description: "Load the complete bundled Grill Me interview primitive for PM requirements coverage under the existing workflow."
---

# Grilling 配套需求访谈（本项目薄适配）

PM 主会话通过本插件的 qualified 入口加载上游 `grilling`；用户无需先调用 `xy-grill-me`。安装包在下方直接提供已按锁校验的完整原文，读至结尾即可进行覆盖判断。源码开发时，原文位于 `third_party/selected-skills/grill-me/skills/productivity/grilling/SKILL.md`。仅阅读此技能无需运行命令。

用户和项目规范、角色所有权、唯一PM派发、独立上下文及当前请求适用的确认优先。复用现有已确认事实，按当前覆盖判断提问；frontier为空不制造问题或重启任务。上游共享理解确认并入既有requirements_approved，不另加前置确认。Worker不嵌套委派，用户禁止代理时遵守；此入口不直接批准、dispatch实现或改生产文件。内部coverage/grill_result schema属于xy-workflow适配，不冒称上游合同。

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
