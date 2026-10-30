---
name: xy-build-verify
description: Verify scoped build or compilation success and runnable-result evidence for production implementation, with relevant tests before independent QA handoff.
---

<!-- agent-workflow-pack:managed-skill -->

# xy-build-verify

All Trivial work uses proportionate local verification and stops before this full handoff procedure;
non-UI corrections follow WORKFLOW's `General Trivial early exit`. A missing full build is not itself
a reason to create an independent QA task. Requested checks and stricter project rules still apply.

Trivial UI copy uses the local verification in `.agent-workflow/product/WORKFLOW.md` -> `Trivial UI copy`;
do not invoke this full handoff procedure merely because a text edit touches production UI.
Loading this Skill does not create a build, independent QA or post-QA closeout requirement.
生产代码交付本身要求受影响目标构建／编译成功并具有可运行证据；Trivial 在主会话
完成相应局部验证，无需执行本 Skill 的完整交接。纯文档／静态原型按各自类型验证。

For non-Trivial verification, read [verification scope](references/verification-scope.md).
Select proportionate commands from the task pack, adapter and repository evidence; discovered
commands are candidates, not a mandatory full-suite list. Preserve required checks, run selected
commands for real, and record every exit code. Reuse valid evidence and stop when coverage is
sufficient; expand or repeat only for a specific gap identified by the linked policy.
执行前确定最小充分范围；仓库级全量测试必须有实际覆盖需要或显式要求，不能仅因任务
进入交付而执行。生产目标的构建／编译与可运行证据是必需项；覆盖充分且证据仍有效
即交接，不再追加无依据的重复构建／回归。

<!-- workflow-contract: references/verification-scope.md -->

## Evidence contract

```text
## Build-verify
- Role: xy-*
- Scope: <changed behavior and mandatory coverage; distinguish new execution from valid reused evidence>
- Build / runnable result: <affected target, environment and actual build plus run/smoke evidence; non-production applicability>
- Commands: <exact commands>
- Exit code: 0
- Evidence summary: <success trailer and relevant warnings>
- Full log: <subagent thread reference or ignored local artifact path>
```

Do not paste a long raw log into the PM handoff. The full reference must be resolvable
by QA. If a command fails, include the exit code, a short failure excerpt, the full-log
reference, and `Status: BLOCKED`. After two failed repair attempts, stop and report to
the PM. Never invent, paraphrase away, or claim unexecuted validation.
现有 Validation 中说明扩大／重跑的触发原因以及仍未验证的相关范围；没有缺口不新增
验证报告或测试文件。局部通过只能支持该范围，不写成“全部测试通过”。

`BUILD_VERIFIED` is evidence, not a QA result or user-facing completion state. For non-Trivial work, preserve the order
`QA PASS -> controlled-document projection -> PM commit assessment -> memory closeout -> final report`;
this Skill creates no QA report, design artifact,
approval record, or metadata file.

For isolated tasks, hand evidence back with the exact worktree/base/checkpoint identity; only PM
creates scoped local transport checkpoints. Follow `xy-workflow/references/worktree-delivery.md` for
composed-result verification and confirm/auto main-branch delivery. A unit's green tests are not
integration proof; keep checks proportional and preserve the ordinary non-worktree route.
