---
name: xy-build-verify
description: "Verify the build, runnable results and relevant tests for the current Light/Full delivery, handing off real evidence according to actual risk."
---

从本 Skill 的物理目录向上两级确定插件根。使用同包的[宿主资源说明](../../plugins/antigravity/plugin-context.md)。当前实例已具备同一物理来源、同一版本的完整说明时直接复用；独立启动或内容缺失时补读，来源或版本变化时重新读取。


<!-- agent-workflow-pack:managed-skill -->

# xy-build-verify

Light／Full 实现角色都保留本入口。确定具体验证工作时，才按阶段定位[验证范围](references/verification-scope.md)。多项适用时合并读取，覆盖完整条款、前提、例外与依赖。标题或片段只用于定位，截断须同版本续读；要求全文的来源仍读完。相对链接以本 Skill 为基准；包内 helper 的规范路径从 `platforms/shared/skills/xy-build-verify/` 起。

- 选择命令时读[范围与命令](references/verification-scope.md#determine-minimum-sufficient-verification-first)和[交付类型](references/verification-scope.md#verification-by-change-type)。逐项核对任务与项目必做检查的执行条件、依赖和已有证据；须本版重跑的照常执行，逐项记录真实退出码。仅修改某项资源时按[逐命令输入核对](references/verification-scope.md#核对一条命令的证据能否复用)判断各项旧证据，另做受影响目标的实际构建和加载。普通文案循包内 `product/WORKFLOW.md` 的 `Light UI copy` 核对消费者、真实加载和打包路径；静态原型走 [xy-prototype-verify](../xy-prototype-verify/SKILL.md)。
- 生产代码（含 CLI）及编译／打包资源读[构建与运行](references/verification-scope.md#production-delivery-must-build-and-run)。必须有当前受影响目标成功构建／编译和启动、冒烟或关键入口运行证据；解释型项目做实际导入／语法检查及运行。核对输入、依赖、配置与环境后才可复用。
- 项目现有证据仍缺生产 Web 浏览器交互时，完整读[浏览器验证政策](references/web-browser-verification.md)。
- 补测或重跑先读[增量证据](references/verification-scope.md#information-gained-from-continued-work)，按实际动作读[新增测试](references/verification-scope.md#new-tests-and-stopping-conditions)或[扩大范围](references/verification-scope.md#expansion-or-repetition-needs-specific-grounds)。失败读[失败诊断](references/verification-scope.md#failure-diagnosis-and-repair-limits)，保留原始证据。无新进展提前交 PM，两次修复失败即停止。
- 交接读[停止条件](references/verification-scope.md#handoff-and-valid-evidence)，PM／QA 按职责读[审查与交付](references/verification-scope.md#independent-qa-review-and-pm-delivery)。隔离 worktree 按[交付合同](../xy-workflow/references/worktree-delivery.md)绑定 worktree、base、checkpoint，并验证实际合成候选。

<!-- workflow-contract: references/verification-scope.md -->
<!-- workflow-contract: references/web-browser-verification.md -->

## Evidence contract

```text
## Build-verify
- Role: xy-*
- Scope: <变更、必做覆盖、已执行／有效复用、相关未验证项>
- Build / runnable result: <目标、环境、实际构建和运行结果；非生产交付写明适用检查>
- Commands: <逐项记录真实命令>
- Exit code: <每条命令的实际退出码>
- Evidence summary: <成功尾行与相关警告，或失败摘要与 Status: BLOCKED>
- Full log: <QA 能读取的完整线程引用或已忽略的本地日志路径>
```

验证执行失败或必做证据缺失须报 `Status: BLOCKED`，禁止标记 `BUILD_VERIFIED`。`BUILD_VERIFIED` 仅表示实现验证，独立 QA 保持只读。Light 默认由原生实现角色验证，交接时由 PM 按风险决定独立审查、文档和记忆；Full 或已选为必需的独立 QA 必须执行。
