# Reuse runtime record tools

仅在维护现有内部任务快照、导出变化后的完整 Task Pack、生成／核对文件指纹，或需要
有界读取长文时使用本说明。它不增加任务等级、状态、业务确认、QA 阶段、强制报告，
Light 可直接维护同形单任务包，不要求创建Full图或第二账本。仅接受schema_version:2。

中央项目先遵守 [统一 helper 执行边界](dispatch.md#workflow-helper-execution)：每次调用
通过项目薄入口并显式传入当前包 `runtime_binding`，不假定 shell 环境跨工具调用持续。
下列 `.agent-workflow/lib/<helper>.py` 命令保留为源包／旧自包含示例；中央模式把 helper
及其参数交给同一 pin 的 `runtime.py --binding '<三字段 JSON>' helper lib/<helper>.py`。
新工作流先做本机 enabled 检查；新图从已验证桥环境或明确已验证 binding 冻结顶层
pin，任务导出原样投影，update／refresh 不改变它。旧包缺 pin、与桥冲突或核心损坏
均拒绝，不从项目 locator 补当前版，不接受任意 `core_root` 路径。

## Prefer the existing tool

- Use the installed `task_graph_cli.py` commands below instead of creating fresh `prepare-*`,
  `amend-*`, `authorize-*`, `verify-*`, or `save-checkpoint-*` Python programs for the same mechanical
  operations. Do not merely move equivalent programs into large inline Python or shell commands.
- Native build/test/run commands remain the evidence for production delivery. A genuinely missing
  behavioral regression may need a project test; a one-off adapter or complex evidence format may
  justify a temporary helper. Keep it task-scoped, reuse it during that task, and do not turn it
  into a default deliverable or an additional acceptance gate.
- Internal records stay in the current resolved execution workspace, not the business source tree
  or a new controlled-document layer. 仅实际需要临时文件时，使用下文 `scratch` 分配本请求
  唯一路径，跨重试、返工与 QA 原地复用；无此需要的 Light 不创建 scratch 或空记录。
  Do not invent dated or random `/tmp/<project>-*` folders, clone source trees (`work/`, `replay/`,
  `before/`, `packages-qa*`), or redirect global dependency/build caches (`Maven`, `Gradle`, `npm`,
  `Cargo`, `DerivedData`) into task scratch directories. Reuse the current graph and available
  receipts. Do not create a second task-state source, a receipt per step, or a new checkpoint script
  just to update metadata.
- 有待回收临时资源时，按下文的只读预览、选择保留及快照绑定清理；调用方先停止相关
  写者并核实归属、活跃使用和必要引用。必需完整日志先移交到可读持久落点并修复引用，
  否则精确保留必要文件。摘要或即将删除目录中的路径不能代替完整证据；工具不推断
  语义引用，也不授权清理共享环境、数据库、系统缓存、用户材料或其他任务资源。

## 初始化任务图

`init` 将PM已明确的决定机械组装为schema_version:2的新图；已有2.0图仍使用`update`，原有
读取、查询与校验合同不变。输入必须给出 `request_id`、`capacity`、`standards` 和非空
`tasks`，通过 `--input <file>` 或 stdin 提供。以下调用复用当前 scratch 中已准备好的
决定文件，不另外建立第二份任务状态。输入顶层声明schema_version:2，每个task给出
workflow_level、规范化module、role、agent_alias、instance_policy:fresh与context_policy:handoff_only：

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
- 源包默认从根内 `project.yaml` 读取规范索引／根目录；旧自包含安装态顶层显式设置
  `adapter_path: ".agent-workflow/project.yaml"`。源包等明确场景可在 `standards` 成对设置
  `index_path`／`root`，此时不再提供 `adapter_path`。不扫描整个规范目录。
  中央桥上下文自动使用已验证物理项目 `.agent-workflow/project.yaml`，不能读核心中的
  配置；显式索引／根也必须与该配置一致，`--root` 与桥项目根不同则拒绝。
  显式传入 pin 的新图同样使用项目中央适配器。
- leaves/selected_standards 使用精确内置来源或实际项目特有叶；安装态只给三份受管来源加
  .agent-workflow/ 前缀，不把项目 standards_root 改成运行时目录。index_path/root 始终保留配置值，
  无项目规则叶且索引物理不存在时 index_fingerprint 为 null，已有说明索引仍取真实 SHA。
  init 和文档校验检查真实存在/缺失，纯 JSON 校验不声称检查了文件系统；不新增字段或审批。
  中央内置来源只从任务 pin 的核心读取正文、ID、严重性和指纹，规范分类仍只接受三份
  精确来源及既有别名；普通 `file_digest` 不因此取得越界或跟随符号／硬链接的权限。
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
  `controlled_document_access`、可选`agent_ref`、`agent_retired`与`handoff_assessment`; `append` supports their existing arrays,
  except non-array fields; agent_ref、agent_retired、handoff_assessment不能append。
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
导出外壳为schema_version:2、当前task、适用standards_contract与必要批准／UI依据；
不含兄弟任务、完整图或PM／兄弟历史。Export preserves the recorded state; it never resets work,
changes acceptance or messages a worker.

Light使用同形单包：`task --input PACK`不带--task-id，校验并返回当前shell；明确写出时
沿用--output与--expect-sha256。`update --input PACK --expect-sha256 SHA --patch PATCH`
沿用`{tasks:{当前id:{set/append/...}}}`补丁，只更新本任务，不改其他任务或批准。Light保留
当前task.state，但不要求Full图、依赖、规划与QA字段。continuation仍带当前--task-id。

可选`handoff_assessment`只记录实际交接判断：
`{independent_qa: required|not_required, documentation: required|not_required, reason: <非空依据>}`。
不需要评估记录就省略，不为Light新增必填账本；Full不得以not_required跳过独立QA。
记忆是否值得保存仍按现有按需原则，不创建空记忆。

接收方宿主可读取导出文件时，交接确切的完整文件引用、当前文件 SHA-256 和简短变化
摘要；接收方按下文完整读取规则核对版本并读取当前 Task Pack，不能用摘要或差量代替。
宿主无法读取该文件时，仍通过支持的通道交付完整包。同一实例已完整收到且读完同版本
正文时，文件只是另一种传输方式，不再重复读取；合同未变时也不因此重新生成包。

## 原生能力观察、用量与同 Agent 续用

以下入口都按需使用，不为普通只读或Light新增Full图、报告或门禁。
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

### 任务身份、同任务续用与退役

2.0任务的module／role／agent_alias绑定长期职责，instance_policy固定fresh、context_policy
固定handoff_only；新独立任务按需创建新实例，不预热全部别名、不复制完整父／兄弟历史。
生命周期权威在WORKFLOW的agent-instance-lifecycle，本文只说明既有记录工具，不另建池。

`agent_ref: {host: codex|claude|antigravity, agent_id: <真实原生ID>}`只在PM从实际已授权
派发结果核对后补记。先让任务实际进入RUNNING（显式qa也可QA），再独立update绑定ID，
不能与首次执行态合并。引用首次绑定后只允许同值幂等，不可覆盖／清空；同图不同任务
包括历史完成任务不能共用身份。ID形状合法不证明真实存活、角色、批准或完成。

`agent_retired`可选bool，缺省false；只能由缺失／false变为true，不能撤销。退役阻止
误派，不能改变仍执行任务的状态或释放路径／语义锁，不等于原生close已成功。原生结束
缺工具／失败时在现有任务记录这一事实；取消／未知仍先核实已有成果与恢复边界。

PM通过已暴露工具观察真实状态后，从业务项目根运行安装态只读查询：

```bash
bash .agent-workflow/lib/python_runtime.sh -X utf8 .agent-workflow/lib/task_graph_cli.py continuation \
  --input "${workflow_record:?set current 2.0 graph or Light pack}" --task-id "${task_id:?set existing ID}" \
  --host codex --observed-state idle
```

同任务running建议wait，idle建议followup；短期返工可续同一实例，同轮QA原Reviewer差量复查。
独立任务、跨宿主、cancelled／missing／unknown、未绑定、已完成或已退役任务禁止自动续用。
查询不探测、不派发、不发消息、不解锁或清空上下文。阻塞建议是正常查询结果（退出0），
输入错误退出2。当前完整包与scope仍须交接，按下文规则复用或补齐完整读取；
resume／compact不证明历史清空。

围绕当前交付单元的反馈窗口保留实例；闭环、接收与必要证据保护后及时原生结束。
容量不足优先已验收且交接充分者，不按LRU淘汰仍执行、证据未交付或必要复查实例；
按宿主真实运行／打开线程口径安排后续QA／集成容量。缺可靠结束工具只退役，不宣称
已销毁或释放容量。AGY kill前保护临时worktree与唯一日志；不删除仍被引用的证据。

QA 原生结构化输出的 schema／extract 操作见
[`xy-qa-review` 的输入合同](../../xy-qa-review/references/inputs.md#原生结构化交接)。
Task Pack 仍使用上面的 `task` 机械导出，不为把自然语言转成 JSON 额外调用模型。

## 完整读取必需长文

`context_read.py <file> [--offset <n>] [--limit <n>] [--expect-sha256 <sha>] [--task-pack <当前包>]`
是可选的标准库
只读单文件分页器，不增加必跑命令、门禁、回执或读取记录。读取与复用按以下边界执行：

- 每位 Agent 独立完整读取当前自包含任务包、必需 Skill／指令及适用规范；其他 Agent
  已读、字段声明、摘要或 SHA 不能替代本实例读取全文。新实例不继承旧实例的已读结论。
- 同一实例上下文中已完整读取、版本未变且仍完整可用的材料直接复用，包括已通过正文
  送达并读完的完整任务包；其同版本文件只是传输方式。只通过文件接收时也只需完整
  读取一次，不把包全文夹带到后续 Skill／规范读取命令中反复加载。显式宿主／Skill
  重读要求仍适用；不为证明复用新增读取账本或强制重读全部材料。
- 缺失、工具截断或上下文压缩使内容不再完整可用时，补齐实际缺失部分；内容实际变化
  时恢复受影响的必需内容并核对其余部分仍可用。不能因一次旧读取跳过新规则，也不因此
  重载未变全树。合同变化仍按原生命周期交付最新完整自包含任务包，差量／摘要不能代替。
- 长文分开读取或连续分页至 EOF，输出预算不足时缩小单次正文，补齐所有截断区间后再
  依赖其结论。普通业务资料按任务相关标题／查询定位；必需规范完整读取不扩大到整个
  业务目录或秘密。机器完整字节核验可只返回指纹／结果，不能证明模型已读正文。

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

上述宿主发现路径示例用于源包／旧自包含安装。中央读取必须按开头链接的桥调用，
同时给分页器 `--task-pack`，受管资源使用固定逻辑路径，例如
`.agent-workflow/platforms/shared/skills/xy-workflow/SKILL.md` 或
`.agent-workflow/product/WORKFLOW.md`。分页器从当前包取 pin 后直接读内容库清单内原文，
项目已换版的 Skill／目录软链不能改变正文；续页仍校验同一完整 SHA。`.agent-workflow/project.yaml`、
locator、业务文件与普通 scratch 文档继续由项目安全实文件读取器处理，不能借 pin
跟随任意项目软链或把整个 `.agent-workflow` 改成链接。无中央上下文的旧调用保持原语义。

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

仅实际需要临时文件时用 `scratch` 解析每个项目／请求的唯一目录，原地复用到任务收口；
不创建按日期、轮次或候选命名的副本。新增资源的目的、所有者、复用入口及保留／回收
条件留在原 Task Pack 合同与验收证据，不另建目录清单、资源台账或报告。

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
```

`cleanup-scratch` 必须先只读预览，再按相同目标与保留项执行：

```bash
bash .agent-workflow/lib/python_runtime.sh -X utf8 .agent-workflow/lib/task_graph_cli.py cleanup-scratch \
  --root "${project_root:?set actual project root}" --request-id "${request_id:?set request id}" --dry-run
# 核对归属、使用和引用后，将预览返回的 snapshot_sha256 设为 scratch_snapshot_sha256。
bash .agent-workflow/lib/python_runtime.sh -X utf8 .agent-workflow/lib/task_graph_cli.py cleanup-scratch \
  --root "${project_root:?set actual project root}" --request-id "${request_id:?set request id}" \
  --expect-sha256 "${scratch_snapshot_sha256:?use the reviewed preview snapshot SHA}"
```

需要保留仍被引用的唯一文件时，两次命令都添加相同的 `--keep <relative-file>`，多文件可
重复该参数。它只接受目标 scratch 内已存在的规范相对普通文件，保留其必要祖先目录；
拒绝缺失文件、链接祖先、通配符和路径穿越。先移交并修复引用可以减少保留范围，不因
一个文件有引用保留整个候选目录。无法证明归属或无活跃使用的目标不执行删除。

预览不创建、chmod 或删除文件；返回总计及最多 20 项的 `candidate_sample`，
`candidate_sample_truncated` 明示是否截断。`snapshot_kind: metadata` 与 `snapshot_sha256`
绑定完整目标与保留项的元数据，不读取大文件内容、不引入文件大小上限；它不是内容
指纹，也不证明任务已结束或引用已移交。执行要求当前快照匹配 `--expect-sha256` 并逐项
复核，变化时拒绝；先停止本任务写者仍是调用方责任，不承诺最终 unlink 前对非协作恶意
并发的原子安全。`--dry-run` 与 `--expect-sha256` 互斥，旧式无指纹删除不再接受。

默认只收口本 `--request-id`。`--all` 仅用于已显式授权、全部目标归属明确且无活跃使用的
管理清理，同样先预览再绑定快照，且不能与 `--keep` 共用；它不是每轮任务的默认动作。
POSIX 不跟随链接，普通硬链接仅 unlink 本任务归属项，不修改外部内容或权限；Windows
保留原安全后端与链接拒绝策略，不将其 ctime 声称为 changeTime。权限或部分删除失败
返回非零并如实保留已成功计数，恢复为保留必要目录而临时调整的权限。
`planned_logical_bytes`／`removed_logical_bytes` 按文件逻辑长度统计待删／已删项，
不表示实际物理磁盘回收量，也不再使用误导的 `reclaimed_bytes`。

