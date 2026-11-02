---
name: xy-build-verify
description: "验证Light／Full当前交付的构建、可运行结果与相关测试，按实际风险交接真实证据。"
---

<!-- agent-workflow-pack:managed-skill -->

# xy-build-verify

Light／Full 都执行与实际交付类型相符的最小充分验证。生产代码保留受影响目标构建／
编译成功和最小启动／冒烟或关键入口证据；文档与静态原型按各自类型验证。Light
默认原生实施者，使用当前自包含任务包；加载本 Skill 不强制 Full 计划、DAG 或独立 QA。
完成后由 PM 依据实际风险评估独立审计、文档和记忆。Full 及选定的必需独立 QA 不得省略。
普通文案使用 WORKFLOW 的 `Light UI copy` 消费者与资源检查，不能按后缀豁免实际构建输入。

验证前读取 [verification scope](references/verification-scope.md)。
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

`BUILD_VERIFIED` is evidence, not a QA result or user-facing completion state. For Full work, preserve the order
`QA PASS -> controlled-document projection -> PM commit assessment -> memory closeout -> final report`;
this Skill creates no QA report, design artifact,
approval record, or metadata file. Light 按实际交接评估收口，未审计不得称 QA PASS。
PM 接收证据并完成必要反馈窗口后，按 WORKFLOW 的实例生命周期结束或退役；完整日志
须保留可读引用，不能因结束原生实例失去唯一证据。

For isolated tasks, hand evidence back with the exact worktree/base/checkpoint identity; only PM
creates scoped local transport checkpoints. Follow `xy-workflow/references/worktree-delivery.md` for
composed-result verification and confirm/auto main-branch delivery. A unit's green tests are not
integration proof; keep checks proportional and preserve the ordinary non-worktree route.
