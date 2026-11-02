# Reuse runtime record tools

仅在维护现有内部任务快照、导出变化后的完整 Task Pack、生成／核对文件指纹，或需要
有界读取长文时使用本说明。它不增加任务等级、状态、业务确认、QA 阶段、强制报告，
也不要求 Trivial 工作创建快照。

## Prefer the existing tool

- Use the installed `task_graph_cli.py` commands below instead of creating fresh `prepare-*`,
  `amend-*`, `authorize-*`, `verify-*`, or `save-checkpoint-*` Python programs for the same mechanical
  operations. Do not merely move equivalent programs into large inline Python or shell commands.
- Native build/test/run commands remain the evidence for production delivery. A genuinely missing
  behavioral regression may need a project test; a one-off adapter or complex evidence format may
  justify a temporary helper. Keep it task-scoped, reuse it during that task, and do not turn it
  into a default deliverable or an additional acceptance gate.
- Internal records stay in the current resolved execution workspace, not the business source tree
  or a new controlled-document layer. Allocate the task scratch directory with `task_graph_cli.py
  scratch --root <project-root> --request-id <request-id>` and reuse that single path in place across
  retries, rework and QA rounds. Do not invent dated or random `/tmp/<project>-*` folders, clone source
  trees (`work/`, `replay/`, `before/`, `packages-qa*`), or redirect global dependency/build caches
  (`Maven`, `Gradle`, `npm`, `Cargo`, `DerivedData`) into task scratch directories. Reuse the current
  graph and available receipts. Do not create a second task-state source, a receipt per step, or a new
  checkpoint script just to update metadata.
- Clean up the task's scratch workspace at closeout with `task_graph_cli.py cleanup-scratch` after
  the task and references are finished, retaining only distilled evidence in the task record. Never
  delete active task files, another Agent's temporary workspace, or evidence still needed while
  implementation/QA is in flight. Before cleanup, ensure complete logs still referenced by a plan,
  handoff or recovery path have a readable persistent reference, such as the original Agent chat.
  A summary or a path into the directory being deleted is not a replacement for required full evidence;
  retain the needed artifacts when no persistent reference exists.

## 初始化任务图

`init` 将 PM 已明确的精简决定机械组装为现有格式的新图；旧图仍使用 `update`，原有
读取、查询与校验合同不变。输入必须给出 `request_id`、`capacity`、`standards` 和非空
`tasks`，通过 `--input <file>` 或 stdin 提供。以下调用复用当前 scratch 中已准备好的
决定文件，不另外建立第二份任务状态：

```bash
bash .agent-workflow/lib/python_runtime.sh -X utf8 .agent-workflow/lib/task_graph_cli.py init \
  --root "${project_root:?set actual project root}" \
  --input "${workflow_decisions:?use PM decisions JSON}" \
  --output "${workflow_graph:?set new graph path}"
```

- `standards` 明示 `required_engineering_rule_ids`、`required_design_rule_ids`、
  `leaves: [{path, domain, rule_ids}]` 及 `protected_paths`；保护项包含 `path`、`rule_id`、
  `allowed_paths`，省略 `direct_edit` 时固定补 `forbidden_without_exception`，其他值拒绝。
  PM 必须列明全部适用必需规则、叶和保护边界，不能只列一条示例规则或让工具猜测。
- 默认从根内 `project.yaml` 读取规范索引／根目录；安装态顶层显式设置
  `adapter_path: ".agent-workflow/project.yaml"`。源包等明确场景可在 `standards` 成对设置
  `index_path`／`root`，此时不再提供 `adapter_path`。不扫描整个规范目录。
- 每个 Writer 保留实际 `id`、`task_type`、`role`、`surface_kind`、`goal`、`gates`、
  `owned_paths`、输入／输出合同、验收证据和 `verification_commands`，用
  `selected_standards: [叶路径]` 明确该任务采用的已列叶。依赖、锁及其他适用业务字段
  仍由 PM 提供；UI、保护路径例外和确认照常受原校验器约束。
- 可选顶层 `requirements_fingerprint`、`approved_gates`、`active_paths`、
  `active_semantic_locks` 只接收 PM 已建立的事实，后三者缺省为空，不推导批准。
  工具机械补当前 SHA、规范访问引用、`standards-conformance`、`DECLARED`、请求级
  QA 及空依赖／阻塞／锁默认值；规范访问中的逻辑 `adapter` 仍为 `project.yaml`。
  不接收完成态、执行身份或回执来制造已完成工作。

工具先复用原图／规范／READY 校验，再原子发布到明确的新文件；已存在的输出、非法
授权、缺失规范覆盖、不安全路径或读取期间变化均失败且不发布。成功摘要为
`initialized`、`path`、`sha256`、`task_count`，不返回整图。初始化已校验当前字节，
无需紧接着重复 `validate`；需要派发时再查询 `ready`，QA 调度时仍单独查询 `qa-ready`。
成功不代表任务已 READY、需求获批、验证通过或 QA PASS。

## Update the current snapshot

`update` requires an existing `--input`, an explicit old `--expect-sha256`, and a patch from
`--patch <file>` or `--patch -` (stdin). Reuse the digest returned by the previous successful update;
if it is unknown, use `fingerprints` on just this graph file, not a whole-project scan.
The patch supports:

- `tasks`: an object keyed by existing task ID. Each operation may contain `set`, `append`,
  `documents`, and `checkpoint`. `set` accepts `state`, `owned_paths`, `semantic_locks`, `input_contracts`,
  `output_contracts`, `acceptance_evidence`, `verification_commands`, and
  `controlled_document_access` and optional `agent_ref`; `append` supports their existing arrays,
  except the non-array fields `state`, `controlled_document_access` and `agent_ref`.
- `documents`: within a task operation, map an existing document path to the owned paths that
  should be appended to its `applies_to`. Select actual applicable documents; the tool does not
  silently broaden every document. Existing standards coverage and write-boundary validation apply.
- `checkpoint`: within an existing isolated Writer operation, record its PM-verified full Git object
  ID in `execution_workspace.head_revision`. It may be combined with the actual completion state in
  one update; it cannot create/change a workspace, root or base. Null is allowed only while the
  original worktree validator permits a pending head.
- `integrations`: an object keyed by existing isolated request ID. Update only that record's
  `head_revision` and/or `verification` using the original evidence schema (exact command, exit code,
  resolvable log reference and verified head). Root, target branch and target base stay protected.
  A new head never rewrites old verification heads. Missing, failed or stale integration evidence
  continues to block the original `qa-ready` gate. This operation runs no Git, build, QA or merge.
- `capacity`: the PM's explicit current available capacity. It is not inferred from task count.
- `refresh_documents`: explicitly selected existing controlled-document paths. With `--root` set
  to the actual project root, recompute their bytes and refresh existing task references. This does
  not adopt new standards/visual authority, change rule IDs, grant approval or invalidate unrelated
  build evidence. A standards change still follows the ordinary adoption and affected-evidence rules.

For example, after the PM has established a task's actual ready/dispatch decision:

```bash
bash .agent-workflow/lib/python_runtime.sh -X utf8 .agent-workflow/lib/task_graph_cli.py update \
  --input "${workflow_graph:?set actual graph path}" \
  --expect-sha256 "${workflow_graph_sha:?reuse observed graph digest}" --patch - <<'JSON'
{"tasks":{"api":{"set":{"state":"RUNNING"}}}}
JSON
```

Replace the example ID with the existing task ID; do not infer one from its business label.
The command preserves other fields and external locks, derives only known running task locks
(including explicit QA nodes in their existing `QA` or `RUNNING` state),
validates with the existing graph/standards/worktree rules, and atomically writes only changed bytes.
An old digest, invalid patch, detected concurrent edit or busy cooperative writer lock fails instead
of overwriting the newer record. Publication uses a same-directory temporary file and atomic replace;
it never moves the current graph away or creates permanent lock files. The PM remains the single
writer for this record. Pause its automatic updates before manually editing the same file; advisory
locks cannot protect against an external editor ignoring them in the final check/replace window or
writing an already open old inode. If directory advisory locking is unavailable, writes fail closed.
Do not silently retry a rejected patch against new inputs; inspect only the conflict first.

Only record states established by actual work and the existing handoff. A file match or successful
update is not compilation, runnable-result evidence, independent review, `BUILD_VERIFIED` or QA PASS.
Entering RUNNING, entering an explicit QA node's QA state, or changing running paths/locks respects dependencies,
approved gates and locks; QA still uses the existing request QA barrier. Changing a completed task's
owned scope, input/output contracts, verification commands, locks or controlled-document contract
requires an explicit pending state and the existing affected-work/verification branch, not silent
reuse of its old completion. Appending actual evidence references or refreshing an unchanged-scope
plan checkpoint does not by itself invalidate completed builds or grant review approval.
Pure changes to a document reference's `reason` also preserve completion when its other fields and
implementation contracts stay unchanged. New functional requirements belong in input/output contracts,
not hidden in a reason. Changes to paths, read mode, query selection, rules or reference authority
still use the existing affected-work branch. Recording worktree heads/checks does not establish
input equivalence: PM/QA must inspect actual revisions, evidence and scope under the original policy.

`update` already validates the resulting snapshot. Reuse that result instead of calling `validate`
again on unchanged bytes. Recompute `ready` when state, gates, capacity or locks change; query
`qa-ready` separately at the existing request QA point. Neither query substitutes for the other:
QA readiness does not imply an empty READY queue. Avoid repeated identical queries only while their
relevant inputs are unchanged. Queries remain read-only and never dispatch an Agent.

## Export a complete changed Task Pack

Use `task --input <graph> --task-id <existing-id>` to return the complete current task object.
An explicit `--output <task-pack.json> --expect-sha256 missing` safely creates a new internal pack;
for an existing output, pass its observed digest instead of `missing`. The graph cannot be the output.
No pack or revision archive is created by default. A scope/contract change requires complete affected
handoff under the plan lifecycle; a state-only change does not require rebuilding every Task Pack.
Export preserves the recorded state; it never resets work, changes acceptance or messages a worker.

接收方宿主可读取导出文件时，交接确切的完整文件引用、当前文件 SHA-256 和简短变化
摘要；接收方核对版本并完整读取当前 Task Pack，不能用摘要或差量代替。宿主无法读取
该文件时，仍通过支持的通道交付完整包。合同未变时，不仅为切换传输方式重新生成包。

## 原生能力观察、用量与同 Agent 续用

以下入口都按需使用，不为普通只读或 Trivial 工作增加快照、验证、报告或门禁。
它们复用当前宿主能力，不启动 runner、daemon、MCP 或第二套 Agent 调度器；原生
能力、boost、teamwork 和其他可选模式不因安装或诊断自动启用。

能力诊断从中央管理工具的源包根运行；业务项目的安装态 `.agent-workflow` 不包含
`manager`，不能从该运行时目录执行管理器模块。`--project` 指向实际业务项目根：

```bash
# 子 shell 只为本次诊断切换目录，不影响后续安装态命令的工作目录。
(
  cd "${workflow_manager_source_root:?请设置中央管理工具源包根}"
  bash lib/python_runtime.sh -X utf8 -m manager.cli doctor --platform antigravity \
    --project "${project_root:?请设置实际业务项目根}"
)
```

`documented` 仅表示文档能力，`source_observed` 仅表示明确来源字节已观察，
`runtime_unverified` 表示尚未验证当前会话实际行为。默认不启动宿主进程；显式
`--probe` 只运行该宿主 `--version`，不登录、不调用模型、不执行 `/skills`。
AGY 只检查明确项目路径 `.agents/skills/grill-me/SKILL.md`，
`customization_sources.grill_me.project_definition` 披露 `status`、`sha256`、
`declared_name` 等；同名时 `same_name_risk: possible`，实际使用来源仍为
`actual_source.status: unknown`。不能据文件存在断言当前会话加载了哪一份技能。
AGY 原生 `/grill-me` 与本包的自包含 requirements coverage check 要核对实际来源和
适用合同，不能自动替换、改别名或省略本包的 Full 需求覆盖；也不扫描个人技能目录。

显式导出当前授权范围的原生用量元数据后，从实际业务项目根运行安装态只读适配器，
不是从中央管理工具源包根或 `.agent-workflow` 目录运行：

```bash
cd "${project_root:?请设置实际业务项目根}"
bash .agent-workflow/lib/python_runtime.sh -X utf8 .agent-workflow/lib/native_usage.py \
  --host codex --input "${native_usage_input:?set explicit exported JSON or JSONL}"
```

`--input` 可重复，按输入观察顺序读取，数据留在本地任务范围，不扫账户或其他会话。
Codex 按 `(thread_id, response_id)` 去重响应，不能再混加其他口径的 turn 计数；
Claude 使用终端 result 的原生字段与身份。AGY result 的 usage 是累计快照，初始
基线未知须保留 `unknown`，输出 `last_cumulative` 与首末 `observed_delta`；单次快照
差值为 null，不能逐条 sum 或把未知填零。缺失计数保持 null，真实零仍为 0，缓存／
推理子项不再加进原生 total，不计算费用或 token 节省百分比。只说明实际采样的会话、
响应与完成轮范围；主会话样本不代表子 Agent，未采样宿主不以零值冒充基线。

任务图可选 `agent_ref: {host: codex|claude|antigravity, agent_id: <真实原生 ID>}`
只保存原生引用，不存另一份 Agent 状态。旧图省略字段继续合法，`init` 拒绝导入该
执行身份。PM 先从实际已授权的原生派发结果核对 ID，再经 `update` 的
`set.agent_ref` 补记到补丁前已经 `RUNNING` 或显式 `task_type: qa` 的 `QA` 任务；
不能把首次派发状态与身份一次补丁合并，不能用 `append` 绕过类型校验。
ID 为 1..256 字符，无空白或控制字符，形状合法不证明身份真实。已有引用只能同值
幂等，不能静默替换／清空；同 `(host, agent_id)` 不能占用两个活动任务。完成任务
可保留历史引用，但不能据此自动授权新任务。写入仍走原 CAS、协作锁与全部原校验。

PM 当前通过已暴露原生工具观察身份后，同样从实际业务项目根运行安装态只读查询：

```bash
cd "${project_root:?请设置实际业务项目根}"
bash .agent-workflow/lib/python_runtime.sh -X utf8 .agent-workflow/lib/task_graph_cli.py continuation \
  --input "${workflow_graph:?set actual graph path}" --task-id "${task_id:?set existing ID}" \
  --host codex --observed-state idle
```

`running` 建议 `action: wait`，`idle` 建议 `action: followup`，两者可复用图中同一 ID；
跨宿主、`cancelled`、`missing`、`unknown`、未绑定或非活动任务返回
`reuse_allowed: false`、`action: blocked`，先由 PM 解决真实恢复缺口。阻塞建议是正常
查询结果（退出 0），输入错误退出 2。查询不探测存活、不派发、不发消息、不改状态，
也不创建替代 Worker 或 Reviewer。后续原生动作只由当前 host 的已暴露且已授权工具
执行；取消不能自动恢复，未知不能当作 idle，ID 存在不证明批准、角色权限或完成。
执行前仍须交接并核对当前完整 Task Pack 和 scope；摘要与引用不能替代完整输入。
READY、QA-ready、BUILD_VERIFIED、QA_PASSED 和同一独立 Reviewer 的返工规则保持原约束。

QA 原生结构化输出的 schema／extract 操作见
[`xy-qa-review` 的输入合同](../../xy-qa-review/references/inputs.md#原生结构化交接)。
Task Pack 仍使用上面的 `task` 机械导出，不为把自然语言转成 JSON 额外调用模型。

## 完整读取必需长文

`context_read.py <file> [--offset <n>] [--limit <n>] [--expect-sha256 <sha>]` 是可选的标准库
只读单文件分页器，不增加必跑命令、门禁、回执或读取记录。每位 Agent 独立完整读取
其必需 Skill、指令和适用规范；同一 Agent 上下文中已完整读取、未变化且仍可用的
内容可依既有重读规则复用。普通项目文档仍按任务相关标题或查询定位，不默认读取
整个目录或业务秘密。

JSON 包含 `text`、`sha256`、`offset`、`end_offset`、`next_offset`、`eof`、`total_chars` 和
`total_bytes`。位置采用 Unicode 字符数，表示半开区间 `[offset, end_offset)`。默认
`limit` 为 6000 字符、最多 24000 字符；它约束返回正文，不是精确 token 上限或总 JSON
序列化体积，转义、元数据及各宿主 tokenizer 另有开销。为完整回包保留足够输出预算，
否则降低 `--limit`。长文分开读取，每次工具回包只取一页。

```bash
# 首页：只指定当前必需的一个文件；安装态从项目根运行。
bash .agent-workflow/lib/python_runtime.sh -X utf8 .agent-workflow/lib/context_read.py \
  .agents/skills/xy-workflow/SKILL.md --limit 6000
# 续页：填入上一完整回包的 next_offset 与首次页 sha256，不猜测位置。
bash .agent-workflow/lib/python_runtime.sh -X utf8 .agent-workflow/lib/context_read.py \
  .agents/skills/xy-workflow/SKILL.md --offset "${document_offset:?use previous next_offset}" \
  --limit 6000 --expect-sha256 "${document_sha:?use first page sha256}"
```

Claude 使用实际 `.claude/skills/` 路径，其他宿主同样复用当前已知路径。严格按上一页
`next_offset` 连续读取，直到 `eof: true` 且 `next_offset: null`。空文件或显式等于总字符
数的位置返回空 EOF 页。使用全文前须补齐所有缺失或截断区间；文件指纹只证明字节／
版本匹配，不能证明模型已读。

每次调用都对完整原始字节计算 SHA，并严格解码 UTF-8、不归一化 CRLF，允许超长单行
跨字符页。将各页解码后的 `text` 按顺序拼接可还原原始 UTF-8 字节。所有 `offset > 0`
均要求首次页的 `--expect-sha256`；正文变化时拒绝续读，须从 offset 0 重读。沿用安全
读取器的 4 MiB 输入上限，拒绝符号链接、硬链接、FIFO 等特殊节点、不安全父目录、
非法 UTF-8、不完整／变化中的读取、非法预算与越界位置。退出 0 返回一页；退出 2 在
stderr 报告输入或读取错误，不回显正文。工具不写读取缓存或状态。

## Generate or check selected fingerprints

`fingerprints --root <actual-root> [--input <manifest-or-receipt>]` reads JSON from the file or stdin:

- A non-empty array of exact root-relative files generates their SHA-256 map.
- An existing map of relative files to expected SHA-256 values checks it without replacing the
  expectations. `--select <field>` (repeatable) selects existing receipt map fields, avoiding a new
  reformatted receipt. Different roots use separate explicitly rooted calls.
- No recursive discovery, glob expansion, code execution, receipt promotion or state change occurs.
  Symlinks, hard links, traversal and files changing during reading are rejected.
- Expected-map checks return only counts and changed paths. Exit 0 means the selected bytes match,
  exit 1 means evidence is stale, and exit 2 means input/I/O failure. On mismatch assess affected
  evidence; do not overwrite old expectations with fresh hashes to turn it green.

Example using an implementer's existing receipt fields:

```bash
bash .agent-workflow/lib/python_runtime.sh -X utf8 .agent-workflow/lib/task_graph_cli.py fingerprints \
  --root "${project_root:?set actual project root}" --input "${evidence_receipt:?use existing receipt}" \
  --select owned_paths_sha256 --select artifacts_sha256
```

Review the relevant original command, exit status, scope, native result and environment as before.
Matching bytes alone never proves that a command ran, tests passed, the program runs, or QA passed.

## Allocate and clean up the task scratch workspace

Use `scratch` to resolve one deterministic scratch directory per project/request instead of creating
ad-hoc `/tmp/<project>-<date>` folders, and `cleanup-scratch` at closeout to reclaim disk space:

Request IDs retain the task graph's non-empty string contract, including Unicode and punctuation.
The directory name uses the full ID's SHA-256, keeping case-distinct requests separate even on a
case-insensitive filesystem; the returned `request_id` remains the original logical ID. The new
`agent-workflow-request-scratch` container is separate from legacy `agent-workflow-scratch`; legacy
directories are not adopted or automatically deleted, even when an old ID looks like a new hash name.
Cleanup retains the empty project scratch root to avoid removing an unpinned parent path after closing
its descriptor. Directories that cannot be opened safely, including those without read/search access,
are preserved with an error; do not fall back to changing permissions through an unchecked path.

```bash
bash .agent-workflow/lib/python_runtime.sh -X utf8 .agent-workflow/lib/task_graph_cli.py scratch \
  --root "${project_root:?set actual project root}" --request-id "${request_id:?set request id}"
bash .agent-workflow/lib/python_runtime.sh -X utf8 .agent-workflow/lib/task_graph_cli.py cleanup-scratch \
  --root "${project_root:?set actual project root}" --request-id "${request_id:?set request id}"
```

