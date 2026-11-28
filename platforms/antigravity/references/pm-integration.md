## Antigravity native PM delta

业务派发遵守共享 [只读偏好合同](../../shared/skills/xy-workflow/references/dispatch.md#read-only-native-dispatch-preferences)，
以已核实插件的实际 native invocation name 查询；通用入口查 `*`。`agy models` 会话 slug
不能传作 subagent tier。当前仅证实 inherit/flash/pro，无独立 effort；未观察实际
`invoke_subagent` schema 时不猜参数，已配置而无法映射则明确阻断本次派发。inherit 不传
model 覆盖，此步骤不启动服务或准备组件。

This entire managed section applies only in Antigravity; ignore other hosts' integration sections.

Standalone read-only audits follow WORKFLOW's matching branch and stop at the scoped conclusion,
without the implementation/QA closeout loop; actual implementation acceptance keeps its QA contract.

Use the installed plugin’s workflow Skill for Light and Full implementation. Resolve roles from its declared `agents/` directory and use the actual host selector. Verify the native role and model in the target session.

Only the PM may use `invoke_subagent`; role Agents never delegate and
`max_depth` is `1`. Light/Full defaults to the corresponding subagent; see `product/WORKFLOW.md#implementation-ownership` for the PM implementation exception and recovery boundaries, preserving the original level's gates.
For Full READY tasks: `inherit` stays `inherit`, `worktree` becomes `branch`
only when the actual runtime proves a distinct registered worktree root and the required base;
`share` is forbidden. A branch name alone is not filesystem isolation. For multi-feature selection,
integration and confirm/auto local main delivery, read `/xy-workflow`'s `references/worktree-delivery.md`.
If isolated tool binding is unavailable, report it and retain safe ownership-based scheduling;
never emulate isolation by concurrently switching branches in one directory or overwriting host settings.

自然语言委托开发、设计交付或独立 QA 时，主会话直接进入 xy-workflow。复用用户对当前范围的明确批准，按现有业务门禁处理尚缺的实质决定。运行包内已知 helper 默认沿用宿主沙箱。参数错误、摘要过期或校验失败时先修正具体输入，不用 `BypassSandbox` 重跑。确实需要额外访问时遵循宿主权限流程。用户明确指定 PM 实施的范围沿用现有例外，独立 QA 由真实 Reviewer 完成。

普通设计委托仍由原生设计角色在登记执行根制作可直接打开的具体 HTML。按 [静态验证合同](../../shared/skills/xy-prototype-verify/SKILL.md) 使用包内 helper，外层 `--project` 传物理绝对项目根，校验器使用 `.` 与 `--standalone`，并传原任务选择的适配器与具体页。交付每页绝对 HTML 路径或 `file://` URI、变更范围、操作步骤及内部依赖指纹。设计关联以当前批准需求为准。页面如在 `data-prototype-plan-source` 中声明需求路径，PM 将其与本请求实际批准的需求 Markdown 路径核对，再请用户确认具体页。AGY 的交付直接使用原稿，跳过 `prepare-delivery` 和本机 HTTP 评审。用户明确点名 PM 实施具体页面时才沿用已有 PM 写入例外。

本地主分支交付由登记原图的 PM 执行。把交付 JSON 放在本请求交接槽，使用已接受的 QA 包和回执原件。按共享 worktree-delivery 合同取得当前候选的 confirm 或 auto 授权后，对交付文件运行 `shasum -a 256 <delivery.json>`，将摘要和实际 PM 会话 ID 填入两次调用：

```text
bash <plugin-root>/lib/python_runtime.sh -B -X utf8 <plugin-root>/plugins/source_pack.py helper --project <main-checkout> lib/delivery/worktree_cli.py merge-ready --repo <main-checkout> --config <selected-project.yaml> --input <delivery.json> --pm-id antigravity:<current-PM-UUID> --expect-sha256 <delivery-json-SHA256>
bash <plugin-root>/lib/python_runtime.sh -B -X utf8 <plugin-root>/plugins/source_pack.py helper --project <main-checkout> lib/delivery/worktree_cli.py merge --repo <main-checkout> --config <selected-project.yaml> --input <delivery.json> --pm-id antigravity:<current-PM-UUID> --expect-sha256 <delivery-json-SHA256>
```

两次使用同一份已核对的交付文件。若文件或原图已变化，按已有交付合同复核受影响的范围、QA 和授权，再固定当前输入。

Light first assesses the current goal, risk, scope, and implementer, dispatching the corresponding native role subagent by default with mandatory minimum sufficient verification; assess independent QA, documentation, and memory at handoff without mandatory Full planning, DAG, saved plans, or duplicate confirmation.

<a id="writer-completion"></a>

### Writer 验证结果回写

App 或 CLI 收到已经登记的 `task_type: writer` 的交付时，由登记原件的 PM 核对原生结果。以真实父会话 UUID 和请求 ID 查看当前任务池：

```text
bash "<plugin-root>/lib/python_runtime.sh" -B -X utf8 "<plugin-root>/plugins/source_pack.py" helper --project "<project-root>" lib/task_pool_cli.py view --root "<project-root>" --pm-id "antigravity:<parent-uuid>" --query "<request-id>"
```

确认原生 Inbox 或结果来自该行 `agent_ref`，并核对实际构建、运行或其他适用检查的命令、退出码和完整日志。结果须覆盖原件的当前范围和版本。单包 `prototype_only` 的 `xy-uiux` 也是 Writer，须核对成功的静态校验和页面依赖指纹。只有这些检查都达到现有要求，才以 PM 身份登记。将当前行的原件、SHA 和任务身份传给以下命令，同时提供原生结果定位和本次核定的一行验证证据摘要：

```text
bash "<plugin-root>/lib/python_runtime.sh" -B -X utf8 "<plugin-root>/plugins/source_pack.py" helper --project "<project-root>" lib/task_pool_cli.py complete-writer --root "<project-root>" --pm-id "antigravity:<parent-uuid>" --record "<record>" --request-id "<request-id>" --task-id "<task-id>" --expect-sha256 "<record-sha256>" --agent-id "<bound-child-uuid>" --verification-exit-code 0 --source "<native-result-reference>" --evidence "<accepted-build-verification-with-log-reference>"
```

如有 `task_revision`，须同时传 `--revision <current-number>`，原件中须已有同一实例对当前修订的确认。只有 PM 在核对实际证据后才传退出码 0。命令核对已登记原件、任务、原生绑定、修订、批准和 SHA，使用现有状态更新协议落盘并回查。Inbox 消息的来源、完成措辞与状态提示都不能代替 PM 对验证证据的核对。此命令无需创建补丁文件，也不会读取其他 PM 的任务池来决定本原件的身份。其他原件、查不到的任务池索引及其写入保护仍按现有规则处理。

确保回执为 `state: BUILD_VERIFIED`、`active: false`，再进入现有独立 QA 或仅原型交付。原型继续按规则交付具体 HTML，取得并保留对当前页面的用户确认。若 SHA 已变化，先回读当前原件并重新核对结果。证据缺失、验证失败或回查失败时，保留任务及证据，以当前原件为准。已经准备的旧更新补丁仍可走正式 `task_graph_cli.py update`。

Full: classify → facts → Grill Me coverage through original `/xy-grilling` → `xy-plan` draft → projection decision →
`requirements_approved`. Grill Me remains requirements-only. For applicable solution and page decisions follow `product/WORKFLOW.md#business-confirmation-policy` and the shared PM confirmation reference. Confirm the material solution before dispatching dependent design or implementation. Retain the user’s applicable prototype choice and the last accepted baseline until QA PASS.
`/xy-grill-me` is user-invoked only; use the actually discovered plugin-qualified `/xy-grilling` for PM intake.
Read xy-workflow/references/requirements-intake.md for the PM-owned schema and canonical fallback;
declared skills paths do not prove runtime loading.
Full work records the Grill Me coverage check and `plan_state: draft`; the pre-approval projection
decision remains a draft, while post-QA controlled-document projection happens only after QA PASS.
PM 在首次设计或实现派发前保存单一可恢复的 Full 批准稿，按计划生命周期选择稳定主题或现有持久请求交接。原型绑定配置的 `docs.plans` 内稳定原稿与当前 REQ。
Light saves only for actual pause/recovery/handoff or user request.
For revisions/recovery follow `/xy-workflow`'s `references/plan-lifecycle.md`: one requirement, one
current plan; replace affected complete worker/QA inputs and reuse unaffected verified work.
Feature details include current architectural rationale, with no separate ADR category.
`UI-Conformance` uses `prototype_policy: not_applicable`, resolved/fingerprinted
`design_authority_refs`, `surface_kind: production_ui`, `qa_scope: request`, no `xy-uiux`, and no
visual gate. Changed routes require a scope-bound `prototype_decision` from
`requirements_confirmation_user_choice`: `required` adds `xy-uiux` and a dependency fingerprint
page Gate `visual_approved`; `waived_by_user` adds no prototype-design dependency, prototype write, or visual
gate. The PM must not default either choice; full UI/accessibility QA remains. Platform security
prompts remain separate.

For initial/revised standards or full visual replacement, read `/xy-workflow`'s
`references/design-standards.md`. PM assesses/adopts scope separately from feature documentation;
UI Agent writes authorized leaves. `design_mode: standards_only` may precede waived production,
without prototype files, verification or visual gates. PM refreshes affected authority before use.

Prototype verification MUST NOT invoke Computer Use or `/browser` by default. Use `/browser` only
when the user explicitly requests prototype automation or reports a concrete failure needing the
smallest diagnostic operation. Production QA may still use risk-based browser testing. No rendered
frame may be persisted or used as approval evidence.

Current controlled documents and explicit user approvals win over recalled memory. Without strict
isolation or provenance, call neither recall nor save. For Full or Light assessed as requiring independent QA, at BUILD_VERIFIED dispatch exactly one
integrated, read-only `xy-qa`. Waived work skips old-prototype comparison.

<a id="full-qa-closeout"></a>

### Full QA 派发与收口

1. Writer 回写并回查完成后，先运行 `qa-ready` 核对 Writer 与预定检查点。普通 Full 在领取 QA 前，按[共享验收合同](../../shared/skills/xy-workflow/references/runtime-records.md#full-qa-acceptance)通过 `update` 的独占 `freeze_qa_scope` 固定实际差异。对于基线干净的单仓未提交任务，可在项目终端分别运行 `git diff --binary --full-index --no-renames --no-ext-diff --no-textconv <已核对的基线> -- <本次归属路径> > <scratch-dir>/writer.diff` 和 `shasum -a 256 <scratch-dir>/writer.diff`。核对完整项目相对路径及真实 base/head。若文件在开工前已有改动，先从原 Writer 取得足以识别本次变更的证据。隔离或 Foundation 沿用各自原检查点。
2. 有需回填的计划时，在冻结前留存包含当前批准稿的 Markdown 原字节。可用 `cat <原主题绝对路径> > <scratch-dir>/reviewed-plan.md` 及独立 `shasum`；保留非空的「需求与验收」。普通单树对未跟踪或与 Git 字节不同的原稿，以 `projection_paths` 与 Writer 范围一并冻结。通过 PM 的最新原图 SHA 依次更新、领取与导出。
3. 首次派发用 `invoke_subagent` 创建唯一 `xy-qa`。用下文的 `pool handoff` 生成初始完整包和标记。Reviewer 以随后包含其 `agent_ref` 的正式包办理验收。收到创建回执后立即 `pool bind`，再从同一图通过 `task --root <项目根> --input <原图> --task-id <QA任务ID> --output <scratch-dir>/qa-bound.json --expect-sha256 missing` 导出正式包，以原生消息交给已绑定的实例。已绑定的原 Reviewer 续审直接使用当前正式包。同一轮只接纳正式包和该实例的回传。
4. 从原 Reviewer 的原生结果保留真实 handoff，运行 `qa_handoff_cli.py validate --task-pack <正式包> --input <handoff>`。有效 PASS 通过独占 `accept_request` 写回，引用正式包和 handoff 的绝对路径与字节 SHA-256。直接设置 `QA_PASSED` 不生成回执。用 `pool view --root <项目根> --pm-id antigravity:<当前PM UUID> --query <请求ID>` 回查状态。
5. 有计划回填时，获得有效 `request_receipt` 后在原主题写入真实验收版本、行为与证据，保留「需求与验收」和原批准。在现有 `update` 入口用独占 `record_qa_projection` 登记适配器、原主题相对路径、留存原稿引用及更新后的字节 SHA-256。适配器必须是原任务选择的同一文件。验收证据引用本次已接收 handoff 的 SHA-256；工作区未提交版本可用实际受审补丁的摘要定位。回查 QA 通过、回执当前有效及计划回填后才报告完整收口。只走任务池收口时，分别说明尚未完成的回填。具体格式见[QA 后登记已验收事实](../../shared/skills/xy-workflow/references/closeout.md#qa-后登记已验收事实)。

### Native review method

The reviewer tries `host-native-review`, then one `installed-code-review-skill` proven installed and
capable, then `internal-xy-qa-procedure`, moving forward only on technical unavailability. The sole
Superpowers option is `requesting-code-review/code-reviewer.md`. Findings or `FAIL` never switch
review method or reviewer. Human diff/Artifact review must not impersonate native AI review or independent AI QA; do not automatically enable native, boost, or teamwork modes, or adjust existing Artifact policy, permissions, or model/effort to enable invocation.

先查看当前 Reviewer 实际可用工具。若只提供 Artifact／diff 人工审阅，记录缺少可调用的原生 AI 审查入口，按既有顺序回退。若宿主确实提供同一 Reviewer 可只读调用的 AI 审查工具，按[核对原生审查目标](../../shared/skills/xy-qa-review/references/inputs.md#核对原生审查目标)核对它接收的实际范围和返回结果。不要套用其他宿主的 slash 命令或 CLI 参数。

Final QA outcome: PASS | FAIL. Require `qa_handoff_cli.py validate --task-pack <current-qa-pack.json>`. Completion: QA PASS → projection
→ PM commit assessment → memory closeout via `/xy-project-memory` → final user report. The installed plugin rule supplies the entry point. Verify actual host discovery and task dispatch in the current session.

## Native Tool Short Path

After actual `read_only`/`evidence` completion, accept its current-scope result/revision receipt and use
shared `runtime-records.md#result-task-settlement` exclusive `update`/`settle`, binding the original AGY ID,
accepted full pack bytes and actual native result/verification evidence. RESULT_VERIFIED ends record
execution occupancy; idle, retirement or kill alone is not accepted result evidence. Preserve necessary
worktree results and logs before kill; native closure/capacity and Writer/QA gates remain separate.

Apply WORKFLOW's `continuous-pm-intake` and shared dispatch checks for cross-request relationships,
authority, ownership, pin and QA; this adapter supplies native differences. The
[official lifecycle](https://antigravity.google/docs/subagents?app=cli#subagent-lifecycle-and-states) says
Running → Parent control permits the parent to interrupt by sending a message or terminating the child.
Therefore do not infer `non_interrupting_message` from AGY message support: for a running instance with
no independently verified non-interrupting tool, `agent_continuation_cli.py` with intent `progress`/`append`
recommends waiting for its report/completion. Do not send an interrupting progress request or stop/restart A
to coordinate B. The documented idle re-awakening preserves prior context; when the actual native message
tool is available, declare `idle_followup` for the same task/ID. Killed agents cannot be re-awoken.
Target-session delivery, wait wakeup, A's continuity, idle followup and parent-final/cancellation lifecycle
remain separate runtime checks; documentation/configuration/version probes cannot make them verified.

Dispatch only current schema_version: 2 single-task packs: task, applicable standards_contract, and necessary approval/UI evidence. Stable agent_alias binds project-relative module and canonical role; instance_policy: fresh and context_policy: handoff_only forbid complete PM/sibling history copies. Invoke invoke_subagent on demand for each independent task, obtaining a new ID with a self-contained current-task initial Prompt. 接收方独立读完当前任务包、选中的 Skill 入口及明确要求全文的材料，其余依受控范围读完适用条款和必要上下文。 If native independent initial context cannot be proven, report a blocker without falling back to a parent-history fork, precreating instances, or filling platform capacity.

Continuous same-task implementation, recent short rework, and same-round Reviewer delta checks may follow up to the original ID. After the feedback window, PM acceptance, and necessary verification/QA, first protect temporary-worktree results, unique logs, and necessary evidence, then use the currently exposed authorized native termination capability. Official kill removes temporary worktrees and prevents recovery while retaining historical transcripts; never kill before retrieving the only delivery, or claim permanent history deletion. Without native capabilities such as manage_subagents kill, or if invocation fails, only record agent_retired and prohibit continuation, with native termination unconfirmed; do not claim destruction, context clearing, or thread-capacity release. Retirement releases no still-running task locks. Observe running/open-thread counts separately under actual host definitions; under pressure reclaim accepted instances with sufficient handoff first, retain executing instances, undelivered evidence, and necessary reviewers, and reserve later necessary QA/integration capacity. resume/compact is not prepareForReuse; create no Agent pool, runner, daemon, or second state machine.

Use doctor, usage, and continuation paths in `xy-workflow/references/runtime-records.md` as needed. doctor starts no process by default; `--probe-version` invokes only `--version`, never `/skills`. Its documented/source_observed/runtime_unverified distinguishes documentation, explicit project provenance, and unverified runtime. A declaration/SHA for `.agents/skills/grill-me/SKILL.md` and same_name_risk=possible cannot prove current `/xy-grill-me` actual_source (still unknown). Verify actual paths and instructions in the target host before use; native `/xy-grill-me` remains user-invoked and does not replace PM coverage through bundled `grilling` or change aliases.

普通非 UI 的 Light 修复从[完整单包示例](../../shared/skills/xy-workflow/references/dispatch.md#light-non-ui-pack)填写原件。PM 从当前宿主取得真实父会话 UUID，以 `--pm-id antigravity:<UUID>` 执行共享派发说明中的 `pool claim`。每个独立任务分别领取，然后只用它自己的领取回执生成初始交接：

```text
bash "<plugin-root>/lib/python_runtime.sh" -B -X utf8 "<plugin-root>/plugins/source_pack.py" helper --project "<project-root>" lib/task_pool_cli.py handoff --root "<project-root>" --pm-id "antigravity:<parent-uuid>" --receipt "<claim-receipt>"
```

将返回的 `prompt` 原样用于 `invoke_subagent.Prompt`，`role` 用于命名派发的 `TypeName`。这个 Prompt 包含本次领取标记和从当前原件导出的唯一完整任务包。初始派发不加整批需求、原会话历史或另列页面和路径。只能选已验证的 `research` 类型时，在同一 Prompt 末尾以一个空行接完整的同包 `roles/<task.role>.md` 正文（可包含 YAML 头），仍须满足任务的工具及隔离要求。显示用的 `Role` 标签不能证明角色交接。专用 Light QA 如需从同请求 Writer 导出证据，沿用带 `--source` 的 QA 正式包交接。

一次只发一个 `invoke_subagent` 调用，以便匹配紧邻的原生创建结果。取得 `conversationId` 后立即执行 `pool bind --host antigravity --agent-id <conversationId> --receipt <原领取回执>`。新领取的原件记有 `prompt_format: task-pack-v1`，守卫和首次绑定据此核对原件派生的完整 Prompt、角色、工作区和创建回执。删除 Prompt 中的格式行也会拒绝。升级前已发出的历史领取继续核对原生角色和领取标记，所有 Writer 的编辑权限以原件的 `owned_paths` 为准。

在 POSIX 上，App 和 CLI 的原生日志分别位于系统账号目录下的 `~/.gemini/antigravity/brain` 和 `~/.gemini/antigravity-cli/brain`。首次绑定要求父会话日志只出现在其中一个目录，核对该会话最近 32 MiB 中的原生创建回执。日志不可读、回执缺失或工具格式变化时保留占用，请核实创建结果后再继续。已绑定的同一 ID 可幂等重试。

CLI 1.5.13 的原生记录以单个 `invoke_subagent` 配对紧邻的创建回执。App 2.34.0 实际还会先调用 `update_steps`，或依次调用 `update_steps`、`update_focus`，然后在同一批仅调用一次 `invoke_subagent`。绑定按记录顺序核对这些状态工具的每条完整 `OK` 和紧邻的创建回执。[官方子代理说明](https://antigravity.google/docs/subagents?app=cli)和[官方 Hook 协议](https://antigravity.google/docs/hooks/)。

PM queries `continuation --host antigravity --observed-state <current-observation>`; only currently exposed authorized native follow-up/wait tools may execute its advice. Cancelled, unknown, invalid, or cross-host states block automatic continuation; still hand off the complete Task Pack/scope. Retirement prohibits continuation; absent capabilities do not justify a custom runner, daemon, MCP, or replacement Reviewer. AGY native cumulative usage retains an unknown initial baseline, last_cumulative, and observed_delta rather than summing each record.

See `xy-qa-review/references/inputs.md` for structured QA output: when supported, use `--json-schema <schema-json>` in the same authorized invocation, then `qa_handoff_cli.py extract --host antigravity --input <native-result.json> --task-pack <current-qa-pack.json>`. Missing optional usage is not a QA gate.

### App 与 CLI 工具执行前的写入分工

启用本插件后，Antigravity App 和 CLI 从插件根的 `hooks.json` 加载 `xy-workflow-write-ownership`。PreToolUse 依据宿主提供的 `transcriptPath` 核对当前会话，子会话的派发回执必须来自同一客户端目录。守卫覆盖原生 `edit_file`、`write_file`、兼容文件编辑工具及 `run_command`。放行后由宿主继续检查权限。[官方 Hook 协议](https://antigravity.google/docs/hooks/)

- PM 可通过原生工具读取工作区，直接核对角色与当前任务，调用原生派发、消息和等待。终端可分别运行 `pwd`、`git status --short`、`git diff --stat`、`rg -n`、`sed -n '1,80p'` 等只读命令。使用实际工作区的物理绝对路径。只有一个工作区时可使用相对路径。
- PM 用固定包内命令 `bash <插件绝对路径>/lib/python_runtime.sh -B -X utf8 <插件绝对路径>/plugins/source_pack.py helper --project <项目绝对路径> lib/task_graph_cli.py scratch --root <项目绝对路径> --request-id <请求ID>` 分配本次目录。从输出取 `scratch_dir`，用原生 `write_file` 在其中准备任务包、方案输入和验收资料。沿用同一个包内入口执行 `pool claim --register`、`task` 导出和 `pool bind`，将实际领取回执重定向到该目录内的具体文件。将示例占位符、变量换为真实值。派发角色和原样 marker 的完整步骤见上文及随包 `skills/xy-workflow/references/dispatch.md`。
- AGY 的 `scratch_dir` 位于本项目 `.awf/agy-requests/request-<请求摘要>/`。PM 和工作者在宿主默认工作区内即可交接；该目录自带局部 Git 忽略规则。使用实际返回路径。已登记请求使用当前 PM 身份和原请求 ID 预览、清理。保留登记直到清理结束，原件及其引用的验收与终态证据自动保留。原件之外的必要证据用 `--keep` 指定。
- 新项目先用同一包的 `plugins/project_context.py inspect`，需要建立适配器时调用 `apply --adapter .awf/project.yaml`。PM 可以写入所选唯一适配器指明的 PROJECT、同目录 ARCHITECTURE 及计划目录内的 Markdown，也可以准备当前会话的任务、实施计划和交接 Artifact。规范正文与实现者的其他资源仍按原有所有权和阶段处理。
- 用户当前原话明确指定执行者，例如“这次由主会话亲自改”，在单工作区仅对当前用户轮次生效。指明具体相对文件的“请 PM 本人直接修改 total.py”仅对该文件生效。后续普通委托恢复默认分工。按现有 WORKFLOW 执行请求范围、验证及独立 QA。
- 实现者以当前领取、原生父子会话、执行目录及原件中的 `owned_paths` 核对编辑范围。若实现者先于 PM 绑定开始编辑，使用同一原生创建回执核对。QA 和只读任务使用原生读取和只读核验。原任务已明确登记的常规测试命令可由 PM 或当前实现者从对应工作区运行。Xcode 工程或 workspace 的设备及 Simulator 构建需同时匹配已发现的本地工程、共享 scheme、固定目标和登记的完整参数。workspace 的每条直接工程引用都须指向同模块内真实存在、无符号链接的工程文件。忽略目录内明确引用的本地依赖仍可验证其确切路径。测试内部的项目代码继续由宿主沙箱管理。
- 常用的纯只读命令可以用 `&&` 或管道组合，每一段分别核对。带写入的复合命令、变量展开、任意解释器程序和交互式终端输入无法在执行前确定目标。可使用原生文件工具进行任务内编辑，将读取、派工、验收分别写为独立调用。新工具、第三方 MCP、外部进程以及工具执行后的文件系统副作用不在这些原生入口的覆盖范围。


已验收的实例按[共用收口入口](../../shared/skills/xy-workflow/references/closeout.md#回收已验收的原生实例)
核对当前请求、证据保全和精确原生 ID，再用当前会话实际提供的工具处理。 AGY 的精确 kill 可能删除临时工作树。先把实际交付、唯一日志和验收证据保存在该工作树之外，再根据原生终止结果登记。若工具会移除任务池仍须核对的固定执行根，先保留该根；只能安全退役时使用退役流程。
