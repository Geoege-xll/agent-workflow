---
name: xy-workflow
description: "Route discussions, prototype-only requests, independent read-only reviews, and authorized Light or Full development through schema 2 tasks, native dispatch, verification, and closeout."
---

用户仅想讨论、澄清或归纳且对话材料已足够时，直接在对话中回答，跳过以下资源定位步骤，无须读取项目、适配器或插件文件。已委托的工作需要访问资源、且当前缺少宿主资源说明时，第一批只读取下方链接的宿主资源说明，等它成功返回后再选当前阶段所需材料。不要把产品全文、阶段引用或项目文件并入这次读取。读取被拒时暂停依赖它的操作，不得换工具绕过。
从本 Skill 的物理目录向上两级确定插件根。使用同包的[宿主资源说明](../../plugins/antigravity/plugin-context.md)。当前实例已具备同一物理来源、同一版本的完整说明时直接复用；独立启动或内容缺失时补读，来源或版本变化时重新读取。


<!-- agent-workflow-pack:managed-skill -->

# xy-workflow

## 先确定当前请求的交付范围

主会话 PM 按本请求的原话、当前待答的问题和已获授权的交付物选择下一步。进度询问只报告对应任务，其他已授权工作照常进行。短句“可以”“继续”只回答能明确对应的那一个问题。话题交错或上下文压缩后，先复用同源同版本已掌握的约定；必要时回查该请求的原话或有效任务包，仍缺依据时只澄清影响下一步的决定。范围规则有缺口时，定位 `product/WORKFLOW.md#request-delivery-scope` 的相应条款。

- **只讨论需求**时，在对话里比较、澄清、归纳；用户另行指定保存某份材料时，只保存该材料。只要求方案或文档时，按指定内容与形式交付后结束，不进入实现。普通讨论不自动调用 Skill、初始化项目、写实体计划、建图或派发。用户明确调用访谈 Skill 或要求查证具体事实时，只做该项工作；读取被拒时尊重原权限。A 在执行时可继续讨论 B；B 的答复不改变 A，也不因 A 已获授权而启动 B。
- **只做原型**时，先核对页面范围与验收；尚未明确时只确认本次设计目标，已有有效确认则直接复用。影响页面行为、状态或异常的选择仍待定时，由 PM 先说明方案并取得决定。到设计交接时再读下方 UI 分支的适用条款。通过静态验证后交付具体页、接收批注、核对修订与依赖指纹。用户确认当前页面后，保留页面、范围及指纹，结束设计请求。没有生产 Writer、生产验收 QA 或自动发布。
- **已委托开发**时，按下方 Light／Full 分级。完整开发中的“先做原型”只在本请求目标、依赖的实质方案及相应页面视觉确认均有效后，放行依赖该页面的已授权生产任务。选择原型或同意视觉结果本身都不产生开发委托。
- **只审查现有工作**时，进入以下独立审查分支。以后明确委托修复时，再给实际修复判级。

**选用其他 Skill 时。** 仅当下一步确实要选择或使用 Skill，先读[共享 Skill 选择规则](references/skill-selection.md)，再按当前任务选用。用户显式访谈、Full 需求覆盖与规划、原型设计、实现、验证和独立审查都遵循此规则。同一实例已完整掌握同源同版本规则时直接复用。普通讨论、只核对页面范围及恢复上下文本身均不触发读取。首次需要包内资源且宿主说明缺失时，仍只先读宿主说明，成功后再进入此步骤。

## Standalone read-only audit

For a standalone audit, PM reviews directly or dispatches one read-only reviewer for the requested scope and applicable standards. Honor explicitly requested independent/full re-review and mandatory project checks. Report evidence gaps, deliver the scoped conclusion and stop. Do not create a writer, BUILD_VERIFIED, an implementation QA PASS or another audit of the report. Full implementation and Light acceptance requiring QA still need independent QA, the latest complete scope, standards and a validated handoff. See `product/WORKFLOW.md#standalone-read-only-audit`.

## Light and Full

只接受 `schema_version: 2`。按实际消费者、风险、共享契约、数据、根配置、角色及界面变化判级。Light 用自足单任务包、对应原生实现角色和最小充分验证；已有明确范围授权直接执行，交接时按风险评估独立 QA、文档和记忆。普通 UI 文案只有通过真实消费者、语义和资源检查，且有当前冻结设计依据、零设计变化时，才用 `production_ui`＋`UI-Conformance`。实际设计或交互变化、共享契约或数据、根配置、多角色交付走 Full，禁止拆小绕过批准或 QA。

**Full 需求与计划。** 完整读取[需求接单](references/requirements-intake.md)及选中的 `grilling` 原版；原版 `grill-me` 只接受用户显式调用。覆盖完成后由 `xy-plan` 起草，PM 判断 QA 后的受控文档投影，按[需求、方案与原型确认](references/requirements-confirmation.md)说明目标范围及验收，再判断哪些实质行为或技术选择需要用户决定。已明确的同请求授权可以复用；依赖方案的新 UI 在交给设计者前先取得决定。已委托完整开发的 UI 设计变更须让用户明确选择原型或直接开发；PM 给出有理由的推荐。审批后、派发前由 PM 保存同一份可恢复 Markdown。已有长期主题原位更新，独立新能力才建页；纯执行或符合性修复可复用持久请求交接。原型须绑定项目内稳定批准原稿与当前有效 REQ。保存、修订、恢复及回填覆盖时按[计划生命周期](references/plan-lifecycle.md)。文档、摘要或指纹均不产生批准。

<!-- workflow-contract: references/requirements-intake.md -->
<!-- workflow-contract: references/requirements-confirmation.md -->

**UI 设计与授权。** 判定 UI 路由、交接或验证原型、变更生产权威时，按[原型与 UI 分支](references/ui-design.md)的对应条款执行。`UI-Conformance` 依赖已冻结的适用权威。UI 设计变更的直接开发分支依赖用户对准确表面的有效豁免。需要原型时，生产 UI 依赖具体页、范围及指纹对应的 `visual_approved`。只维护设计规范或替换视觉系统时另读[设计规范](references/design-standards.md)。仅授权的规范叶子可由 `standards_only` 设计任务修改。

<!-- workflow-contract: references/ui-design.md -->

**派发及持续接单。** PM 在实际派发前读[派发规则](references/dispatch.md)中当前等级、原生偏好和实际操作适用的部分，首次使用包内 helper 或原生派发时，按同包宿主资源说明核对所需的来源、运行与权限边界；复用已验证的当前插件和项目适配器。Light／Full 默认由对应原生实现者修改生产代码，只有用户明确要求 PM 本人实现此范围才例外。每个新实例只收当前完整任务包、适用角色和标准，使用 `instance_policy: fresh`、`context_policy: handoff_only`。实际启动前，PM 为本次委托登记并领取已经就绪的原包／原图；创建返回后立即把真实宿主 ID 绑定到同一项，供进度、追加或撤回使用。Light 和仅原型均可使用独立单包。

B 的独立委托满足其自身确认条件后，PM 立即依据当前记录、执行根、路径、语义锁及实际原生容量判断能否与 A 并行；就绪且资源可用时派发独立任务。C 与 A 或 B 重叠时，只复用已交付且实际输入、验收范围和来源仍匹配的成果。复用成果不继承原批准、Worker 或 QA。同任务追加须在角色和授权内，更新完整约定与受影响任务包，完成必要确认并核实原实例收到后才接收新范围结果；独立任务用新实例。真实前置关系进入依赖，资源冲突只等待。具体按 `product/WORKFLOW.md#continuous-pm-intake` 和派发规则的 continuous-intake-dispatch。进度、续办、结算、任务包导出或证据更新时再查[运行记录](references/runtime-records.md)，禁止用中断代替非打断消息。

<!-- workflow-contract: references/dispatch.md -->

**实施、验证与收口。** 代码改动执行 `xy-code-standards`。缺陷修复、实施交接、独立验收或返工按[实施与 QA](references/implementation-and-qa.md)的适用分支。Full 生产实现始终由唯一独立只读 `xy-qa` 验收；Light 完成按风险选中的强制项，没有实际 QA 时不得声称 QA PASS。原 Reviewer 只复核受影响差异，保留有效证据。到文档投影判断、交付或关闭实例时按[收口规则](references/closeout.md)。多功能隔离、worktree 集成或本地合并交付才读[工作树交付](references/worktree-delivery.md)；遵守相应 confirm/auto 策略和 Git 安全边界，合并不授予远程推送。

<!-- workflow-contract: references/implementation-and-qa.md -->
<!-- workflow-contract: references/closeout.md -->
<!-- workflow-contract: references/worktree-delivery.md -->

## 读取和反馈

以上链接是当前阶段的查阅入口，不是预读清单。以当前插件根的 `product/WORKFLOW.md` 为权威，需要补齐规则时定位对应章节；普通接单无需默认全文读取。项目使用真实适配器。每个 Agent 独立读完当前任务包、选中的 Skill 入口及明确要求全文的材料。`controlled_document_access` 为 `targeted` 时，读完适用条款及其范围、例外和依赖。同一实例中已完整可用的同源同版本内容可以复用；缺失、截断、压缩或变更时按[完整读取必需长文](references/runtime-records.md#完整读取必需长文)补足，显式重读要求仍适用。Hooks 只提醒激活或恢复；自动记忆不能决定权限或流程。Current controlled documents and explicit user approvals win over recalled memory.

Internal orchestration records are not user-facing output. Never paste raw workflow YAML or DAG JSON into user messages. 任务包、指纹、门禁、调度状态及 `commit_decision` 等记录仅在用户明确要求检查或导出时提供；用户要求的项目产物可按其格式交付。进度报告说明结果、阻塞与待决事项；最终交代改动、验证、剩余风险和用户需要的操作。Skill 导致暂停、额外确认或偏离请求时，指出具体文件、适用条款和影响。遵守上级规则及宿主权限。
