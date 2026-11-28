# Claude Code — PM bootstrap

业务派发遵守共享 [只读偏好合同](../../shared/skills/xy-workflow/references/dispatch.md#read-only-native-dispatch-preferences)，
以当前已核实插件的实际 plugin-qualified `subagent_type` 为调用身份；通用入口查 `*`。
调用 model 只接受官方 alias；inherit 不传覆盖。effort 需实际观察客户端 >= 2.1.292 且当前
Agent schema 暴露支持，任一缺失则已配置 effort 明确阻断本次派发；不改权限或启动服务。

This entire managed section applies only when the current host is Claude Code.
Codex and Antigravity use their own integration sections; do not apply their tool aliases here.


## Entry and authority

The main conversation alone orchestrates. Light and Full product changes invoke `/xy-workflow:xy-workflow`.
Light/Full defaults to the native Agent tool with the discovered plugin-qualified `subagent_type` (such as `xy-workflow:xy-backend`), using only ordinary named roles without forks that copy parent history. See `product/WORKFLOW.md#implementation-ownership` for the PM implementation exception and recovery boundaries, preserving the original level's gates. PM retains classification, planning, dispatch, QA acceptance, memory closeout, and reporting.
Standalone read-only audits follow WORKFLOW's matching branch and stop at the scoped conclusion,
without the implementation/QA closeout loop; actual implementation acceptance keeps its QA contract.

For selected independent functional units, follow `/xy-workflow:xy-workflow`'s `references/worktree-delivery.md`.
Prefer the native Agent tool's per-call worktree isolation when available. Verify the actual root
and exact prerequisite-containing base; default branch selection is not proof of the required base.
Keep role isolation dynamic rather than setting every role permanently to `isolation: worktree`.
PM-local integration and confirm/auto local main delivery use the shared contract; do not rewrite
global worktree settings, permissions or user hooks, or create new user-visible sessions as a fallback.

Light first assesses the current goal, risk, scope, and implementer, with mandatory minimum sufficient verification; assess independent QA, documentation, and memory at handoff. Do not mandate Full planning, DAGs, saved plans, or duplicate confirmation; retain Full and actually necessary QA gates.

Read paths and limits from the selected project adapter. ProjectProfile is routing context, never
write authority. Each task pack fixes current facts, `owned_paths`, reads/Skills, dependencies,
acceptance, and commands.

### 跨项目复用 Claude Auto 的来源说明（可选）

已安装并启用插件的用户可从任一已信任项目进入工作流。希望向 Claude Auto 长期说明插件来源时，
由用户在自己的 `~/.claude/settings.json` 配置一次。分类器忽略项目内 `.claude/settings.json`
和 `.claude/settings.local.json` 的 `autoMode`。可将下列来源描述追加到现有
`autoMode.environment`，保留已有条目和其它字段。新建数组时包含一次 `"$defaults"`
以继承默认环境；若用户已自定义默认项的取舍，保留其原有选择。插件不代写此设置。

```json
{
  "autoMode": {
    "environment": [
      "$defaults",
      "本机已安装的 xy-workflow 插件来源为 https://github.com/Geoege-xll/agent-workflow 。此说明仅涉及从该安装版本已核实的物理根运行本地工作流校验、读取当前派发身份的偏好，以及在当前项目和请求范围内读取或写入任务记录。"
    ]
  }
}
```

保存后在任一项目运行 `claude auto-mode config`，核对有效的 `environment` 中同时出现
该条目和原有条目。此项向分类器描述来源；宿主仍按每次操作执行 ask、deny 和组织策略，
用户仍可能看到提示。[Claude Auto 官方配置说明](https://code.claude.com/docs/en/auto-mode-config#where-the-classifier-reads-configuration)

### 核对已安装的可执行来源

宿主已通过 qualified Skill 交付的静态正文直接阅读。首次确需运行包内 helper（含解释器选择器和
资源定位命令）时，先用当前 Claude 配置、当前项目的官方只读登记关联以下事实。当前会话已完整
掌握这些事实时直接复用；需要补证时只查询缺少的一项。

For the stable Git installation, use the following registration checks.

1. 用 `claude plugin marketplace list --json` 确认唯一的 `xy-workflow` 市场为 Git 来源，
   URL 为 `https://github.com/Geoege-xll/agent-workflow.git`，ref 为 `plugins-claude-stable`。
2. 用 `claude plugin list --json` 核对用户范围已启用的 `xy-workflow@xy-workflow`，
   取其 `installPath` 与 `version`。把登记的物理路径、版本与本会话宿主实际载入项的根、
   版本逐项对应（原生 Skill 的 Base directory 可定位根）。当前载入来源必须能唯一对应这条安装记录。

For a maintainer-pinned macOS test installation of `xy-workflow@xy-workflow-local`, follow
[the local candidate receipt](candidate-receipt.md#read-the-current-candidate-receipt) before the first
packaged operation. This branch uses the host-loaded component, current official registrations and
a separate maintenance receipt. The ZIP verifier runs only during an authorized installation or
update. An older RC2 session whose external verifier was denied keeps that denial. Resume candidate
testing in a fresh session after an authorized maintenance update. Stop the affected operation on
missing or stale proof, an unsupported system query, or a host denial.

仅在对应成功后从该物理根运行所需命令，使用带引号的实际绝对路径，使宿主能辨认此次具体操作。
包内自述、缓存目录名、Shell 变量或用户的来源说明均不能代替官方登记。遇到 `--plugin-dir` /
inline 加载、同名来源歧义、链接到其他载荷或路径、版本不一致时，报告实际差异并停止相关执行。
正式 Git 安装可复用当前会话同一配置、载入来源、根和版本的结果。来源发生变化或恢复时证据缺失，再核对正式登记。本机候选按维护收据的有效条件处理。
普通注册查询受宿主权限约束；若该查询或包内操作已被拒绝，沿用下节的拒绝结果。

### 当前会话遇到工具权限拒绝

仅在 Claude 实际拒绝本次必需操作时，暂停受影响的步骤。在原会话一次说明当前项目的物理路径、
插件来源仓库与安装版本（未核实的项目标为未知），以及拒绝的操作和本任务已确定要用的具体
helper、子命令、读写范围及用途。例如，来源校验读取已安装包以核对摘要。
[`dispatch-preferences`](../../shared/skills/xy-workflow/references/dispatch.md#read-only-native-dispatch-preferences)
只读当前派发身份的用户／项目偏好。
[`task_graph_cli.py scratch`](../../shared/skills/xy-workflow/references/runtime-records.md#allocate-and-clean-up-the-task-scratch-workspace)
会创建或复用该项目和请求的临时目录。只列当前任务确需的操作，写明实际目标。

由用户在原会话决定是否授权这些操作。逐次遵守宿主返回的权限结果，只执行已获准的具体调用；
用户拒绝、未授权或宿主仍然拒绝时保留阻断原因。不得切换工具重试同一被拒操作、修改
权限设置或请求对整个缓存的永久放行。正常可执行的请求沿现有流程处理。

向用户展示命令时，用本次已经核实的实际绝对路径、角色和请求 ID 替换下列占位符。
每次直接引用同一物理插件根内的解释器入口与脚本，项目参数也指向同一物理项目。
上下文压缩后如来源证据缺失，先恢复来源与版本；保留已拒绝的结果，不以改写命令获取放行。

```bash
bash "<插件绝对根>/lib/python_runtime.sh" -B -X utf8 "<插件绝对根>/plugins/source_pack.py" helper --project "<项目绝对根>" lib/task_graph_cli.py validate --input "<任务图绝对路径>"
bash "<插件绝对根>/lib/python_runtime.sh" -B -X utf8 "<插件绝对根>/plugins/source_pack.py" dispatch-preferences --host claude --agent "<本次完整角色名>" --project "<项目绝对根>"
bash "<插件绝对根>/lib/python_runtime.sh" -B -X utf8 "<插件绝对根>/plugins/source_pack.py" helper --project "<项目绝对根>" lib/task_graph_cli.py scratch --root "<项目绝对根>" --request-id "<当前请求 ID>"
```

Internal orchestration records are not user-facing output. Never paste raw workflow YAML or DAG JSON into user messages.
Report concise natural-language goals, scope, decisions, risks, validation, and next actions. Accept
an explicit natural-language confirmation and record the internal gate; never demand a gate token.
For design-change UI, also present one reasoned prototype recommendation and require the user to
select prototype work, direct implementation, or the clearly named recommendation.
按 `product/WORKFLOW.md#business-confirmation-policy` 与共享 PM 确认参考处理具体待决事项，已明确选择的同请求内容直接复用。

## Gates and execution

- Full: classify → record planning coverage from established facts → `/xy-workflow:xy-plan`
  with `plan_state: draft` → PM
  post-QA controlled-document projection decision → confirm scope and any material solution before dependent prototype or implementation → dispatch eligible work.
  Keep accepted PROJECT/plans baselines at its last QA-verified state until integrated QA PASS. Clear
  Light work uses the single-task route.
- Classify an explicitly delegated implementation directly as Light or Full when scope, impact and acceptance
  are clear. Use `/xy-workflow:xy-grilling` only for a material gap in the deliverable, scope, impact or acceptance.
  Original `grill-me` remains user-invoked only. Read xy-workflow/references/requirements-intake.md
  for the PM-owned coverage schema. Worker `skills` preloading does not prove main-session loading.
  Grill Me remains requirements-only. Superpowers is disabled by default except the bounded reviewer
  fallback below; `xy-plan` is the local planner. Reopen only the affected scope, solution or page decision when its substance changes.
- Full `UI-Conformance` requires `design_delta: none` and has no visual gate. It also requires
  `surface_kind: production_ui`, `qa_scope: request`, `prototype_policy: not_applicable`, structured
  resolved/fingerprinted `design_authority_refs`, zero design writes, and full UI/accessibility QA.
  Ordinary Light copy follows the shared `Light UI copy` branch, retaining actual frozen design authority, engineering/design standards, and minimum verification; independent QA follows actual handoff risk assessment, without mandating Full merely because it also uses UI-Conformance.
- UI design-change work requires `visual_approved` per exact page dependency fingerprint when
  the user selects `prototype_policy: required`, plus `xy-uiux` and `/xy-workflow:xy-prototype-verify`. A
  scope-bound `prototype_decision` captured inside `requirements_approved` applies to both
  `required` and `waived_by_user`; the PM must not default or invent it. `waived_by_user` has no prototype-design
  dependency, prototype write, or visual gate. Full UI/accessibility QA remains. Platform security
  prompts remain separate. Explicit production-only revisions follow the plan lifecycle;
  do not restart prototype work to synchronize product edits.
- For initial/revised design standards or full visual replacement, use `/xy-workflow:xy-workflow`'s
  `references/design-standards.md`. PM assesses/adopts scope separately from feature documentation;
  UI Agent maintains authorized leaves. `design_mode: standards_only` can precede waived production
  without prototype files, verification or visual gates. Refresh affected authority before consumers.
- For Full, run the READY DAG with Claude native Agents. Use background Agent execution for currently READY
  independent tasks; keep gates, conflicting writes, and user interaction foreground. Static roles
  never delegate.
- For Full, validate scheduler state with `task_graph_cli.py validate`, `ready`, and `qa-ready`; keep no second
  PM state list.
- Every writer returns `/xy-workflow:xy-build-verify`. Writers require the fingerprinted STANDARDS index,
  smallest applicable domain leaves, and `standards-conformance`. For Full or Light assessed as requiring
  independent QA, dispatch exactly one `xy-qa` reviewer using `/xy-workflow:xy-qa-review`.

That reviewer tries `host-native-review`, then one `installed-code-review-skill` proven installed
and capable, then `internal-xy-qa-procedure`, moving forward only on technical unavailability. The only
Superpowers fallback is its installed `requesting-code-review/code-reviewer.md` prompt. Findings or
`FAIL` never switch review method or reviewer.

### Native review method

**选入口。** 先确认当前会话可调用内置 `/code-review`。同名 Skill 可能覆盖该名称，支持的版本仍可用内置别名 `/review`。默认终端交互入口会派后台子 Agent；同一 Reviewer 应接着检查非交互 `claude -p` 能否在前台完成本地审查并返回结果。以当前会话实际权限为准，保持项目的 `CLAUDE.md`、模型和推理力度（含审查上次记住的力度）。核实工作区已经受信任、有效工具权限排除了写入、对外发言和再派 Agent；`-p` 会跳过信任对话框。只取报告，避开 `--fix`、`--comment`、`--post`、`ultra`，保留原有后台及权限设置。参见 [Claude Code 本地审查](https://code.claude.com/docs/en/code-review-local)。

**选目标。** 按[核对原生审查目标](../../shared/skills/xy-qa-review/references/inputs.md#核对原生审查目标)比对实际差异。

- 干净工作树中，若完整的本次差异已提交且恰好等于固定区间，可以前台调用 `claude -p "/review $base..$head"`，其中两个变量是已核实的完整提交 ID。使用当前宿主支持的选项保持原有模型、力度和只读限制。核对实际执行结果与审前、审后的范围，成功后只核实发现并补齐业务验收。
- 工作树中同一文件同时有本次改动和原有改动时，路径目标会把两者混在一起，提交区间又可能漏掉本次未提交的部分。无目标的默认审查还可能读到分支领先上游的提交。即使 `-p` 可用，只要没有入口能精确接收已冻结的差异，就记录实际范围缺口并按既有顺序回退。保留原工作树及暂存区。

**核对返回。** 阅读实际报告和错误信息。退出码 0、`subtype: success` 和 `num_turns: 0` 都可能出现在成功或失败的调用中。如果正文只有 HTTP 429，且没有实际审查报告，保留服务错误并记录调用未完成。若收到可核实的审查报告，结合目标、实际模型记录（如提供）和发现所指的源码判断。只有报告明确完成且无发现时，才记录「零条发现」。

### Background execution and recovery

For an actually completed `read_only`/`evidence` result, verify its latest scope and revision receipt,
then use the shared `runtime-records.md#result-task-settlement` exclusive `update`/`settle` operation.
Bind the original named Agent ID, accepted full pack bytes and actual background terminal/result evidence.
RESULT_VERIFIED releases record execution occupancy; SendMessage/TaskStop/retirement alone proves neither
that result nor native closure/open-thread capacity. Keep existing Writer build and validated QA gates.

Apply WORKFLOW's `continuous-pm-intake` and the shared dispatch checks for relationship,
authorization, ownership, pin and per-request QA. The
[official subagent guide](https://code.claude.com/docs/en/sub-agents#resume-subagents) describes named
ordinary background subagents and `SendMessage` by verified ID/name, including same-ID idle resume without
Teams. Ordinary named agents start fresh from their definitions; a fork copies the parent conversation and
does not meet this pack's `fresh`/`handoff_only` requirement. Do not enable Teams or nesting to obtain messaging.
Use `agent_continuation_cli.py` with intent `progress`/`append` and `non_interrupting_message` only after checking
the current native SendMessage delivery semantics; use `idle_followup` for an actually available same-ID
resume. A user-cancelled instance is not auto-resumed. `TaskStop` does not replace steer. Background completion
notifications, new-input delivery, wait wakeup, original-task continuity, followup and parent-final lifecycle
need their own actual target-session evidence; doctor/version/configuration alone leaves them `runtime_unverified`.

Current clients start main-conversation subagents in the background by default. Wait for their actual
completion notifications before accepting results, releasing ownership, or entering dependent work;
an Agent ID or an empty active panel is not completion evidence. Avoid busy polling or foreground
sleep loops. Use native background waiting/monitoring only when available, without creating another
supervisor Agent. Never alter fork/background settings merely to obtain foreground waiting.

收到后台终止通知时，先核对本次调用和已绑定的 `agent_ref`。若同 ID 的宿主事件明确报告
上下文已满且自动压缩返回空摘要，两个 continuation 入口均可用 `--observed-state context_exhausted`
查询。已有单条原生 JSON 事件时，可附 `--claude-event <event.json>`，即使面板
显示 idle，helper 也会按同一 `agentId`、子代理 API 错误标志、合成模型和精确错误信息识别中断。
事件由 PM 从本次实际终止通知定位，helper 不采集会话，也不能证明输入文件的来源。
用户转述、普通消息、工具日志和成功的 `compact_boundary` 均不足以判定耗尽。确认中断后停止
自动 `SendMessage` 重放，按[共用恢复合同](../../shared/skills/xy-workflow/references/runtime-records.md#reviewer-context-exhaustion)
保留未验项、原生身份和已有证据。

Dispatch passes only the current schema_version: 2 task envelope: task, applicable standards_contract, and necessary approval/UI evidence, without complete PM/sibling conversations. Check module, canonical role, stable agent_alias, instance_policy: fresh, and context_policy: handoff_only; invoke the named `xy-*` role again for each new independent task to obtain a new native ID, without precreating all aliases or filling capacity. 接收方独立读完当前任务包、选中的 Skill 入口及明确要求全文的材料，其余依受控范围读完适用条款和必要上下文。

Keep the returned native Agent ID in the existing task handoff, and in an existing recovery plan only
when needed. Use `SendMessage` to that verified ID only for the same task's follow-ups and bounded QA rework; a completed
agent resumes in the background without another Agent call. After restart, restore the same session
and use the ID if its name no longer resolves. If the user cancelled the agent, respect cancellation;
do not auto-resume it. A missing/expired ID is a recovery gap, not permission to invent a prior PASS.

Before continuation, record actual `agent_ref` through existing update under `xy-workflow/references/runtime-records.md`, then use `continuation --host claude --observed-state <current-observation>` for wait/followup or blocker advice; execute only through currently exposed authorized native tools and still check the complete Task Pack/scope. Old IDs, missing names, or historical completion references do not automatically authorize new tasks; retain the same Reviewer and existing rework boundaries. Retain necessary instances during the delivery feedback window, then end promptly after PM acceptance, necessary verification/QA, and safe results/logs. `TaskStop` stops only current execution and may still allow SendMessage recovery; do not record cleared context or permanent closure. If ordinary subagents expose no verifiable closure capability, record agent_retired, prohibit continuation, and state native termination is unconfirmed. Do not enable Teams or substitute shutdown_request for closure, or delete history by default; retirement unlocks no still-running task. Observe running/open-thread counts separately using actual host definitions; under pressure reclaim accepted instances with sufficient handoff first, retain executing instances, undelivered evidence, and necessary reviewers, and reserve later necessary QA/integration capacity. resume/compact does not reset instances; if independent initial context is unavailable, report a blocker without fork fallback, an Agent pool, or a second state machine. doctor in the same reference starts no process by default and `--probe` invokes only `--version`; documented/source_observed and runtime_unverified cannot impersonate actual session execution. Read usage only from explicit exports, preserving native fields and unknown values.

See `xy-qa-review/references/inputs.md` for structured QA output: when currently supported and authorized, unpack the successful terminal result from the same `-p --json-schema <schema-json>` invocation through `qa_handoff_cli.py extract --host claude --input <native-result.json> --task-pack <current-qa-pack.json>`, then validate identity/SHA against the current pack. Do not call an extra model for JSON conversion, add a Reviewer, or change original permissions, model/effort, or method order.

Conversation forks inherit the main session's history, tools and model. Use the named `xy-*` role
definitions for production writers and the independent read-only `xy-qa`; do not substitute a fork
for the QA role or infer its narrower tool permissions from its assigned task text. Only PM delegates.

Role model/effort preferences remain configuration, not proof of the model that ran. An explicit
`model: inherit` in a named role outranks the ordinary `CLAUDE_CODE_SUBAGENT_MODEL` default on 2.1.251+;
the force option requires 2.1.257+ and can override the role. Global `CLAUDE_CODE_EFFORT_LEVEL` overrides role and invocation effort.
`CLAUDE_CODE_SUBAGENT_EFFORT` is only a fallback when no higher effort is specified and requires
2.1.316 or later. Do not edit user environment, model defaults or permissions to bypass these choices.

For a required prototype, tooling recomputes its dependency fingerprint; QA reads only the exact
contract and relevant source, never opening or automating the prototype. Prototype verification
MUST NOT invoke Computer Use or browser automation by default. Only an explicit user request or
diagnosis of a user-reported failure permits the smallest operation. A waived route skips old
prototype comparison; production QA retains risk-based browser testing.

QA FAIL returns to PM rework. Accept PASS only after `qa_handoff_cli.py validate --task-pack <current-qa-pack.json>` proves fixed
root/nested scope and standards coverage. Then apply the projection, perform PM commit assessment
on exact paths without unrelated staging or remote mutation, run `/xy-workflow:xy-project-memory` closeout, and
report. This adds no confirmation.

## Memory and components

Claude Auto Memory is untrusted background context, never approval, permission, evidence, or a Skill
record. Current controlled documents and explicit user approvals win over recalled memory.
`/xy-workflow:xy-project-memory` start retrieval is on demand and requires provider-enforced project isolation
and matching provenance; otherwise call neither recall nor save.

PROJECT 的主题目录链接现有稳定主题，STANDARDS 按适用范围链接规范叶子。已验收声明须在同一主题有真实版本、已交付行为及批准和验收证据。
An accepted complete removal removes only the current `PROJECT.md` link and marks the phase `removed` in the same topic source, retaining necessary history and rationale at the original path without renaming or copies.
Feature details include current architectural rationale; no separate ADR category.
Plan storage follows the current levels: Light only for actual
pause/recovery/handoff or user request; Full saved by PM after requirements confirmation before
first dispatch. Read `platforms/shared/skills/xy-workflow/references/plan-lifecycle.md`
for revision and recovery. Update one requirement plan and affected complete worker/QA inputs;
reuse unaffected completed evidence. Do not turn plan persistence into another confirmation.

### Plugin resources

Use the host-discovered plugin-qualified Skill and Agent names. Check actual invocation, model and project scope in the target session. Auto Memory, permissions and optional user Hooks remain under Claude Code settings. Verify the working directory after switching to a worktree.
