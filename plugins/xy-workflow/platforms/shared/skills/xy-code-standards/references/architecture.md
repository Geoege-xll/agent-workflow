# 架构设计与增量演进

当改动涉及职责拆分、跨模块复用、状态归属或公开契约演进时，按实际问题选读。通用约束仍以 [rules.md](rules.md) 中的适用规则为准。

## 从实际入口定位职责

从一个现有页面、命令、路由或任务入口追到结果，找出哪段代码解释业务规则、哪段代码负责协议转换、谁能写入状态、谁处理失败。结合调用方、构建依赖和已有验证，判断哪些部分同因变化，以及哪些部分本应独立变化却被迫一起修改。`eng-common-010`、`eng-common-011`、`eng-common-012`

| 观察到的事实 | 适合先尝试的边界 |
| --- | --- |
| 私有实现围绕同一业务职责、共用生命周期且总是一起改 | 在同一个文件保持就近协作，按需要提取私有函数、类型或组件 |
| 职责可以独立变化，例如同一入口同时解析协议和决定业务资格 | 在现有模块内分开规则与映射，让入口只协调实际流程 |
| 不同调用方对同一能力的输入、结果、错误和归属达成一致 | 复用或扩展已有入口，缺少合适入口时提取到能力归属方 |
| 需要限制跨模块访问、独立构建或部署，且现有边界无法表达 | 权衡新模块带来的约束和构建、迁移、维护成本，再选择项目支持的边界 |

例如，CLI 的参数解析和帮助文案可以在同一个文件内协作。导入校验若还供后台任务使用，可以把共享校验放在导入模块，由 CLI 和任务各自处理输出。若两个入口对缺失字段的业务含义不同，先厘清契约。强行共用一个带有 `forCli` 选项的校验函数，会让调用方分别猜测默认行为。

## 看清依赖和公开契约

检查实际导入、构建依赖、公开签名和装配入口。模块之间的源码依赖应指向承诺该能力的公开契约，避免把具体页面、存储实现或框架内部类型带入公共契约。运行时的调用顺序可以与源码依赖方向不同。`eng-common-008`、`eng-common-010`、`eng-common-013`、`eng-common-014`

当业务规则必须与变化频繁的外部协议解耦时，可以从业务所需操作定义小契约，让各适配器实现它，由现有启动或装配入口选择实现。举例来说，导入流程只需按约定保存已校验的数据，具体存储适配器负责映射和执行。若项目已有满足语义的存储能力，沿用现有入口。若两个模块开始相互导入，先找出数据或行为的真正归属，检查能否通过归属方的契约单向协作。

在开源基座或外部框架上二次开发时，优先从已有公开 API、扩展点或适配器接入。必要的上游改动沿 `eng-common-029` 确认可写范围并缩小补丁，验证现有下游行为及受影响的升级路径。涉及受保护路径时适用 `eng-upstream-001` 和 `eng-upstream-002`。

按 [通用工程规则](rules.md#configuration-errors-and-maintenance) 中的 `eng-common-009` 验证公开接口。优先从可访问且获准验证的真实调用点检查。新增或已有入口确无这类调用方时，用代表性的已知契约输入调用正式入口，核对输出、错误和适用行为，并在交接中列明仍未验证的真实消费者。看必填信息、返回结果、失败含义、适用的取消和副作用能否从参数、返回类型及项目约定读出来。若每个调用者都要拆响应包、判断底层驱动异常或记住隐含调用顺序，检查能否在归属边界消除重复。

## 跟踪状态和副作用

分别找出状态的权威来源、允许的更新入口及实际写入系统。界面筛选条件可由使用它的界面持有，筛选结果可从条件和原始列表派生。持久化业务结果由业务契约指定的权威来源确认。若界面和后台任务都能提交，检查两条路径是否通过同一业务决策入口。`eng-common-025`、`eng-common-026`

沿调用链标出读取、外部调用、提交及发布发生的位置。确认哪一方可以决定执行副作用，哪一方拥有资源生命周期并执行释放。适用的事务、取消、重试、并发和恢复语义参见 `eng-common-017`、`eng-common-026`、`eng-common-027` 及[边界判断](boundary-reasoning.md)中的相关部分。

遇到需要取舍的模式时，按实际变化点选读[设计模式案例](design-patterns.md)。

## 通过兼容步骤演进

1. 从真实生产者追到受影响的消费者，检查公开接口、已有数据及部署边界。字段意义、默认值、错误类型、配置和新旧版本的读写次序都可能影响既有调用。迁移前确认哪些行为需要保留，以及哪些消费者无法同步更新。`eng-common-014`、`eng-common-028`
2. 在现有边界落实最小可用改动。需要分批切换时，先选能保持现有行为的兼容入口，再迁移实际调用方，确认旧路径仍需支持的范围及结束条件。例如，持久化字段改名且新旧版本会并行运行时，先确认读写兼容和历史数据，再切换使用方。每步都要明确失败后的恢复路径，尤其要检查回退后的旧版本能否读取已写入的数据。发现超出批准范围的契约破坏时，带着受影响调用方和迁移风险交 PM 按现有流程处理。
3. 按 `eng-common-009` 选择验证入口，核对结果及与改动相关的失败、取消或恢复行为。必要时包含历史数据、独立部署的消费者或真实装配。针对性测试可以定位规则，实际入口和依赖验证能检查接线及跨边界行为。沿用现有计划和 QA 交接，说明相关消费者、兼容策略、验证结果和仍有的证据缺口。验证范围按 `eng-common-019` 和 `eng-verification-001` 至 `eng-verification-003` 选择。

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
