---
name: xy-code-standards
description: "When writing, refactoring or reviewing code read-only, combine built-in engineering rules, project-specific standards, actual callers and existing contracts to choose the smallest complete change or report evidence-backed findings; supports quality judgment without replacing project standards, task authorization or verification procedures."
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

# xy-code-standards

Use current user authorization, the existing Task Pack and applicable rules as the basis. The single source
of general engineering text is the [built-in engineering rules](references/rules.md); read applicable clauses
for the actual task. Projects add only approved specific standards, and read a project index only when it exists.
Fully bind current sources, rule IDs and fingerprints. This Skill adds no planning, dispatch, prototype,
approval, QA or record stage.

<!-- workflow-contract: references/rules.md -->

## Choose implementation from facts

- Follow actual call chains to establish the behavioral goal, entry points, data/state owners and consumers.
  Use nearby code, tests and executable configuration to distinguish facts, assumptions and gaps. Verify
  discoverable facts first; return unresolved tradeoffs affecting contracts, permissions or side effects to
  the original decision-maker. Do not automatically treat an observed old implementation as an upgrade target.
- Before reuse, check semantics, inputs/outputs, failure modes and dependency direction. Before extraction,
  identify the actual shared responsibility, variation point or isolation benefit. Similar syntax, fewer lines
  or anticipated future extension does not justify consolidation or added layers.
- Compare approaches by their changed behavior, preserved contracts and affected consumers; choose the smallest
  complete change that meets current requirements. Remove redundancy caused by this change and report other
  issues within the original task boundary. Explain non-obvious tradeoffs with comments required by applicable
  standards and update those comments with behavior.

## Read-only review and evidence

Read-only review does not write code. Findings include a concrete location, trigger, actual impact and supporting
evidence. Distinguish proven defects, evidence gaps and design preferences; naming, line counts or missing evidence
for a platform alone do not establish incorrect behavior. Implementation/review retain the existing verification
contract: reuse still-valid coverage and fill only real gaps. Do not expand static checks or test-double results
into claims about real consumers, other platforms or product quality. Implementation delivery still follows
the applicable `xy-build-verify` branch.

## Read by actual boundary

- When a change/review involves external input, mutable state, resource lifecycles or durable publication,
  read only relevant parts of [boundary reasoning](references/boundary-reasoning.md); do not load every
  specialist topic for an ordinary local change.
- Read [sources and adoption boundaries](references/sources.md) only when maintaining this Skill,
  checking attribution or tracing tradeoffs; do not preload it for ordinary implementation/review.
