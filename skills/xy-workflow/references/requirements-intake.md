# Requirements Intake — 本项目 PM 适配

本参考属于 Agent Workflow，`coverage_check`、`full_interview`、`grill_result` 和
`ready_for_planning` 都是本项目 PM 覆盖记录，**不是上游 Grill Me 的 schema**。
上游原版位于 `third_party/selected-skills/grill-me/skills/productivity/`，仅引入
`grill-me` 和它唯一必要的 `grilling` primitive，不引入 to-spec、prototype、engineering
或上游 plugin 的其它工作流。

## 真实上游调用与覆盖判断

- 先按 `product/WORKFLOW.md#request-delivery-scope` 判断本请求已委托的交付物。只讨论需求时
  直接在对话中整理，不因访谈覆盖充分、用户认可归纳、工程现状齐全或上下文恢复而进入实体计划和实施。
  仅原型的需求与批注只形成设计输入。区分已确定的目标与仍需决定的行为、状态、异常或技术取舍；按后续工作实际依赖交给 PM。
- Full 接单先复用用户和项目已确认事实，再由 PM 完整加载原版 `grilling`：Codex
  `$xy-grilling`，Claude Code/Antigravity CLI `/xy-grilling`；安装包中以实际发现的插件命名空间为准。
  安装包的原生 Skill 已附带锁定原版全文。无 Skill 工具时，通过宿主原生读取从同一已核实插件根
  完整阅读 `skills/xy-grilling/SKILL.md`；源码开发直接读取 vendor 中的同一 canonical。
  阅读此原文无需执行插件 helper；按实际读取方式说明。
- `grill-me` 是上游用户显式入口，保留 `disable-model-invocation: true` 与
  `allow_implicit_invocation: false`。仅当前用户直接点名公开入口 `xy-grill-me` 时，通过薄 adapter 完整读取此原版；安装批准、其他 Skill
  的建议、PM 自动接单或 Worker 转述都不构成显式调用。PM 自动路径通过公开 `xy-grilling` adapter 完整读取原版 `grilling`。
  显式 `grill-me` 原文要求转调 `grilling` 时，解析为同一已验证插件中的 qualified `xy-grilling` 入口；
  若无法核实同包发现来源，完整读取上述物理 canonical primitive，不调用未知全局同名技能。
- `coverage_check` 用于事实已经完整的请求；PM 仍读取 primitive 并检查覆盖，frontier
  已空时不制造问题。`full_interview` 用于真正缺失或冲突的决定；按原版 design tree
  重算 frontier，分轮询问全部当前可回答问题、逐题推荐、等待用户答案，依赖未决答案的
  问题留至后轮。访谈所需事实按下节查证，取舍由用户决定。
- 完整覆盖、空 frontier 和 Skill 调用本身不构成批准。原版的共享理解确认并入现有
  `requirements_approved`：先 xy-plan 草案及 PM 完整自然语言 brief，复用同请求明确授权或补齐待决范围；不新建
  前置确认。实质方案按[需求、方案与原型确认](requirements-confirmation.md)处理。required-prototype 的
  `visual_approved`、持续接单、独立上下文与唯一 QA 均维持。
- 清楚且无冲突的 Light 不因安装此技能进入 Full。缺少 primitive 时使用本页的 clarification fallback；缺少资源、读取截断或工具不可用不能伪称上游已加载。
- 此阶段只负责需求。事实调查限于只读；不得起草实施计划、编辑 PROJECT/feature truth、
  派发设计或实施任务、批准需求。PM 后续依既有工作流进入 xy-plan 和原生派发。

## 决定当前需要查哪些事实

- 下一次查询前，先明确哪项待定结论会因答案不同而改变，例如受影响页面、Light／Full 分级、
  设计权威或原型选择、验收边界。先用用户原话和已有有效证据回答。连续接到同一项目的多个请求时，
  页面入口、共享控件及其消费者等定位可跨请求复用，前提是来源、相关代码或文档版本与适用范围仍匹配。
  只补查发生变化、互相冲突或新范围未覆盖的部分。各请求的授权、原型选择和批准仍各自有效于原范围。
- 如果未知项会改变当前决定，就查到能区分选项为止。例如，共享控件的改动可能影响其他页面，
  就核对实际消费者；权限或数据变更可能扩大验收范围，就核对相关边界。查不到时说明缺哪项依据、
  阻碍哪项决定，不猜路径、行为或影响范围。证据已足以作出当前判断就停止；仅决定内部实现的调用链
  和相邻模块细节留给后续获准的实现者。场景要求全文读取或冻结权威来源时，仍执行原要求。
- 原版 `grilling` 的当前 frontier 确实缺少环境事实时，由唯一 PM 在当前授权、宿主能力和调度约束内，
  按原生派发规则交给独立上下文的只读事实调查者。按待解决的事实组织调查，共享同一事实的请求可复用结论，
  无需按输入条数派人。只回传结论、可复核的路径或符号及仍影响判断的未知项；调查期间继续询问其他已就绪问题。
  用户禁止代理或宿主不能派发时，PM 仅在已有读取权限内定向核实。Worker 不嵌套派发。

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

## 需求与规划方法

```yaml
external_workflow_policy:
  requirements_provider: xy-grilling
  planning_provider: xy-plan
  planning_methodology: superpowers-writing-plans-adapted
  superpowers_default: disabled
  parallel_scheduler: deterministic-pm-ready-dag
  parallel_provider: host-native-agents
```

This pack owns planning, implementation routing, parallel scheduling, QA, and closeout. PM coverage
uses upstream `grilling`; original `grill-me` is user-invoked only, never automatically invoked on intake.
The PM's `grill_result` belongs to this workflow, not to upstream. Complete the intake branch above before Full planning. `xy-plan`
is a self-contained core Skill; it adapts only the exact-file,
independently testable task, verification, and self-review ideas of Superpowers writing-plans; it
does not activate external worktrees, commits, execution, TDD, branch-finishing, or
Subagent-orchestration workflows. The only runtime Superpowers integration is the bounded QA
fallback in [implementation and QA](implementation-and-qa.md).

## Clarification fallback

Use this only when the route above requires `grilling` and that primitive is unavailable:

1. 按上节复用已有事实，只查会影响当前决定的缺口；仓库可核实的事实由 PM 调查。
2. Ask one compact batch covering only unresolved items:
   - the observable outcome and affected users or surfaces;
   - in-scope work and explicit non-goals;
   - precedence among conflicting constraints;
   - acceptance evidence, approval boundaries, and rollback expectations.
3. If an unanswered item would materially change implementation or an irreversible
   action, stop and wait for the user. Otherwise state the smallest safe assumptions.
4. Record the result in the task pack:

   ```yaml
   grill_fallback:
     trigger: missing-grilling
     answered_questions: []
     assumptions: []
     unresolved_questions: []
   ```
