# Requirements Intake — 本项目 PM 适配

本参考属于 Agent Workflow，`coverage_check`、`full_interview`、`grill_result` 和
`ready_for_planning` 都是本项目 PM 覆盖记录，**不是上游 Grill Me 的 schema**。
上游原版位于 `third_party/selected-skills/grill-me/skills/productivity/`，仅引入
`grill-me` 和它唯一必要的 `grilling` primitive，不引入 to-spec、prototype、engineering
或上游 plugin 的其它工作流。

## 真实上游调用与覆盖判断

- Full 接单先复用用户和项目已确认事实，再由 PM 完整加载原版 `grilling`：Codex
  `$xy-grilling`，Claude Code/Antigravity CLI `/xy-grilling`；安装包中以实际发现的插件命名空间为准。
  无 Skill 工具时，通过当前物理插件根的 `plugins/source_pack.py resource
  third_party/selected-skills/grill-me/skills/productivity/grilling/SKILL.md` 定位并完整读取；
  源码开发直接读取同一 canonical。说明这是宿主读取适配，不冒称不存在的工具已执行。
- `grill-me` 是上游用户显式入口，保留 `disable-model-invocation: true` 与
  `allow_implicit_invocation: false`。仅当前用户直接点名公开入口 `xy-grill-me` 时，通过薄 adapter 完整读取此原版；安装批准、其他 Skill
  的建议、PM 自动接单或 Worker 转述都不构成显式调用。PM 自动路径通过公开 `xy-grilling` adapter 完整读取原版 `grilling`。
  显式 `grill-me` 原文要求转调 `grilling` 时，解析为同一已验证插件中的 qualified `xy-grilling` 入口；
  若无法核实同包发现来源，完整读取上述物理 canonical primitive，不调用未知全局同名技能。
- `coverage_check` 用于事实已经完整的请求；PM 仍读取 primitive 并检查覆盖，frontier
  已空时不制造问题。`full_interview` 用于真正缺失或冲突的决定；按原版 design tree
  重算 frontier，分轮询问全部当前可回答问题、逐题推荐、等待用户答案，依赖未决答案的
  问题留至后轮。事实由 PM 在现有权限内调查；需要 fresh 事实子代理时仍由唯一 PM
  按原生派发和独立上下文合同处理，Worker 不嵌套委派；用户禁止代理时遵守禁令。
- 完整覆盖、空 frontier 和 Skill 调用本身不构成批准。原版的共享理解确认并入现有
  `requirements_approved`：先 xy-plan 草案及 PM 完整自然语言 brief，再一次确认；不新建
  前置确认。已确认且未变化的事实和当前任务不重启。required-prototype 的
  `visual_approved`、持续接单、独立上下文与唯一 QA 均维持。
- 清楚且无冲突的 Light 不因安装此技能进入 Full。缺少 primitive 时使用 xy-workflow
  的现有 clarification fallback；缺少资源、读取截断或工具不可用不能伪称上游已加载。
- 此阶段只负责需求；不得规划、编辑 PROJECT/feature truth、dispatch implementation
  或批准需求：must not plan, edit PROJECT/feature truth, dispatch Agents, or approve requirements。
  PM 后续依既有工作流进入 xy-plan 和原生派发。

## Internal PM record

Build the following complete structure for planning coverage. It is PM working state, not a
user-facing response. The PM must not emit the raw `grill_result` YAML, its mode/readiness fields,
or empty internal lists to the user. When clarification is required, ask only the smallest natural-
language question that resolves the material gap. When coverage is complete, let the PM summarize
the goal, scope, non-goals, constraints, and acceptance evidence in the later approval brief.

```yaml
grill_result:
  mode: coverage_check | full_interview
  observable_goal: ""
  affected_users_or_surfaces: []
  in_scope: []
  non_goals: []
  constraints: []
  conflicting_constraints: []
  acceptance_evidence: []
  approval_boundaries: []
  rollback_expectations: []
  answered_questions: []
  assumptions: []
  unresolved_questions: []
  readiness: ready_for_planning | blocked
```

When blocked, state the smallest unanswered decision that prevents safe planning. When ready, return
control to the PM; do not continue into planning or implementation. Preserve the complete internal
record for `xy-plan`, but do not announce the schema or a `ready_for_planning` status token to the
user unless the user explicitly asks to inspect the internal record.
