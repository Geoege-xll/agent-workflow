---
name: xy-build-verify
description: "Verify the build, runnable results and relevant tests for the current Light／Full delivery, handing off real evidence according to actual risk."
---

## 官方 Antigravity 插件资源边界

本段仅适配资源与原生传输，不授予业务批准、角色所有权或 QA PASS。
从已加载组件的物理路径解析插件根目录：技能目录上两级，`agents/`、`rules/`
目录上一级；禁止用项目 cwd 或猜测缓存路径。先读根目录 `PLUGIN.md`。
唯一流程依据是其中的 `product/WORKFLOW.md`、`roles/`、
`platforms/shared/skills/`，以下共享正文保持原样。
宿主读取如被截断，按缺失行范围续读，或复用包内已有分页 helper；完整连续覆盖
当前任务所需权威范围后才执行。不重复读取已覆盖内容，不自行实现另一套分页器。

历史 `.agent-workflow/` 资源引用改由本插件的 `plugins/source_pack.py resource`
解析。每次独立调用都使用：
`bash <plugin-root>/lib/python_runtime.sh -B -X utf8 <plugin-root>/plugins/source_pack.py`。
原有辅助命令使用 `helper --project <absolute-project> <original-helper> <arguments>`；
它只选已有 Python 3.11+，不安装软件、不改 PATH。项目文档、任务与业务代码仍属于
真实项目；包内示例不是当前项目配置。

通过同一 helper 调用 `plugins/project_context.py inspect`，复用已验证的
`project.yaml`，或显式 `apply` 新候选 `.awf/project.yaml`；历史配置路径随实际选择
转换。`init --adapter <selected-path>` 必须传入同一配置。此入口不创建文档、不授予
批准。需要宿主集成时读取 `platforms/antigravity/references/pm-integration.md`。
插件原生发现取代旧安装、刷新与中央激活；不得运行 `runtime install`、
`runtime activate`、项目注册、`setup_*.sh`，或创建/修改项目 `AGENTS.md`、
`CLAUDE.md`、`.agent-workflow` 来使插件生效。

主会话始终是 PM。工作代理只接收当前完整任务包，使用 `instance_policy: fresh`、
`context_policy: handoff_only`，不得继承 PM 或其他代理历史。仅官方宿主派发代理；
使用宿主默认或已配置的模型与推理设置。核心流程不依赖独立模型配置服务、网页或 MCP。
保留原有需求批准、适用的视觉批准与 Light 显式授权；需要独立 QA 时，仅一名只读
审查者，并遵守原有结项顺序。

Antigravity 通过本插件 `agents/` 原生发现角色。使用定义已核对到当前插件的原生
选择器；角色标签不证明实际角色、模型或上下文隔离。未知同名全局 `xy-*` 可能来自
旧流程，禁止据此作为本插件运行证据，或导入其中央 pin、历史与指令。若只能使用
通用原生入口，应以全新上下文交付当前完整角色正文与任务包；无法保证选择或隔离时
向 PM 报告宿主限制，不得宣称已运行。

当前 alpha 沿用未绑定的源包合同，拒绝中央 `runtime_binding` 与中央项目标记，
不自动迁移。活动任务期间不得更新/替换插件；跨更新资源保留与实际模型/effort
执行仍需真实宿主证明。未获得对应证据时保留 `runtime_verified: false`。


<!-- agent-workflow-pack:managed-skill -->

# xy-build-verify

Both Light／Full use minimum sufficient verification appropriate to the actual delivery type. Production
code retains evidence of a successful affected-target build/compile and minimum startup/smoke or key entry;
verify documentation/static prototypes by type. Light defaults to a native implementer with the current
self-contained task pack; loading this Skill does not force a Full plan, DAG or independent QA. At handoff,
PM assesses independent audit, documentation and memory by actual risk. Full and selected mandatory
independent QA must not be omitted. Ordinary copy uses WORKFLOW's `Light UI copy` consumer/resource checks;
file suffixes do not exempt actual build inputs.

Before verification, read [verification scope](references/verification-scope.md).
Select proportionate commands from the task pack, adapter and repository evidence; discovered
commands are candidates, not a mandatory full-suite list. Preserve required checks, run selected
commands for real, and record every exit code. Reuse valid evidence and stop when coverage is
sufficient; expand or repeat only for a specific gap identified by the linked policy.
Determine the minimum sufficient scope before execution. Repository-wide tests require an actual coverage
need or explicit requirement, not merely entry into delivery. Production-target build/compile and runnable
evidence are mandatory. Hand off when coverage is sufficient and evidence remains valid; do not append
unsupported repeated builds/regressions.

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
In existing Validation, explain added coverage, invalidated evidence/specific risk, or the new diagnosis,
testable hypothesis/repair progress and expected evidence for continued failed rework. Keep relevant
unverified scope explicit. Without progress, stop the current repeated failing path early and return it to
PM under the policy above; do not reset existing limits or treat stopping as success. Without a gap, add
no verification report/test file. A scoped pass supports only that scope, not a claim that all tests passed.

`BUILD_VERIFIED` is evidence, not a QA result or user-facing completion state. For Full work, preserve the order
`QA PASS -> controlled-document projection -> PM commit assessment -> memory closeout -> final report`;
this Skill creates no QA report, design artifact,
approval record, or metadata file. Light assesses closeout at the actual handoff; an unaudited result is not QA PASS.
After PM accepts evidence and the necessary feedback window ends, close or retire the instance under WORKFLOW's
instance lifecycle. Retain readable full-log references; ending a native instance must not lose the sole evidence.

For isolated tasks, hand evidence back with the exact worktree/base/checkpoint identity; only PM
creates scoped local transport checkpoints. Follow `xy-workflow/references/worktree-delivery.md` for
composed-result verification and confirm/auto main-branch delivery. A unit's green tests are not
integration proof; keep checks proportional and preserve the ordinary non-worktree route.
