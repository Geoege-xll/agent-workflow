# Reuse runtime record tools

Use this reference to locate registered originals, maintain internal task snapshots, export changed complete Task Packs,
generate/check file fingerprints or read long documents within bounds. It adds no task level, state,
business confirmation, QA phase or mandatory report. Light may directly maintain a same-shape single-task
pack without creating a Full graph or second ledger. Accept only schema_version:2.

Use the verified plugin root and the actual project for each [helper invocation](dispatch.md#workflow-helper-execution). Keep the selected adapter and task identity unchanged across calls.

## 任务池中的修改、撤回和停止

主会话收到「改一下刚才那项」或「撤回导出」时，先按[持续接单与恢复](dispatch.md#continuous-intake-dispatch)从当前项目、当前 PM 的任务池查到原件。进度查询只读。对修改类操作，核对用户指向的标题、目标和现行授权，从同一行取 `record`、`task_id`、`sha256`。只对这一版本调用现有更新入口：

```bash
bash "$plugin_root/lib/python_runtime.sh" -B -X utf8 "$plugin_root/plugins/source_pack.py" \
  helper --project "$project_root" lib/task_graph_cli.py update --input "$record" \
  --expect-sha256 "$record_sha" --patch "$patch_file"
```

下表给出 `{"tasks":{"<实际 task_id>":{…}}}` 中单个任务操作的例子。来源字段填写能回查的当前用户消息、宿主送达、同一实例明确接收或执行结果。PM 从源事件核对事实。更新返回的 `sha256` 可用于随后的独立操作。若文件在用户所见版本之后已经改变，先回读确认当前对象与意图，避免重放旧操作。

| 用户或宿主事件 | 对原记录的操作 |
| --- | --- |
| 用户修改同一任务的交付约定 | `{"revise":{"set":{"goal":"导出增加日期列"},"source":"user:当前修改消息"}}`。按原门禁核实批准，保留原路径和角色。超出所有权或发生角色变化时按既有独立任务流程办理。 |
| 正在执行的原实例收到本版完整包 | PM 导出现行完整包（独立仅原型的 `task` 追加 `--pm-id "$pm_id"`），用可用的原生消息工具交给已绑定实例，核实其明确接受的版本，再写 `{"ack_revision":{"revision":2,"agent_ref":{"host":"codex","agent_id":"实际绑定ID"},"delivery_source":"native:实际投递","ack_source":"native:同实例对本版的回执"}}`。版号取原件中的 `task_revision`。 |
| 同一实例提交本版结果 | 按任务类型使用已有 Writer 构建验证、结果结算或 QA 验收操作，并在同一个任务操作旁附 `"revision_result":{"revision":2,"agent_ref":{"host":"codex","agent_id":"实际绑定ID"},"source":"native:本版结果"}`。原批准、证据和版本分别核实；迟到的旧版结论保留作历史。 |
| 用户撤回待派任务，或要求运行中的实例停止 | `{"withdraw":{"reason":"用户撤回导出改动"}}`。待派原件变为 `WITHDRAWN`；已经领取的任务进入 `STOP_REQUESTED`，仍占用相关资源。主会话对实际实例调用受支持的停止方式，保留已有改动、唯一日志和回执。 |
| 宿主明确观察到已绑定实例停止 | `{"confirm_stop":{"agent_ref":{"host":"codex","agent_id":"实际绑定ID"},"observed_state":"stopped","source":"native:该实例停止回执"}}`。结果未知、仅发出请求或逻辑退休时保持占用并继续核实。独立工作仍按现有准入推进。 |

用户撤回多项工作时，先核对实际受影响的任务；同一张图可以在同一个 `tasks` 补丁列出多个 `withdraw`。多个原件要分别带各自 SHA，汇报时区分已成功、仍需核实和不受影响的任务。

### Full QA 发现需要返工的缺陷

如果 Writer 在执行中接收过修订、已经交付，而本请求的独立 QA 随后返回 `FAIL`，PM 读这份回执，找到属于原 Writer 的阻断项。在该 Writer 上单独提交 `rework_from_qa`，提供 `reviewer_id`（QA 任务 ID）、`task_pack` 和 `handoff`（各自的 `path`、`sha256`）、`finding_index`（从 0 起）及 `affected_path`（受此项影响、属于该 Writer 的项目相对路径）。已有回执用硬性规则记录失败时，可用对应的 `rule_id` 代替序号。同轮有多个受影响的 Writer 时，在同一次更新中分别列出各自的依据。

原 Writer 回到 `DECLARED` 后，PM 按既有依赖与占用将其续派给原实例。原实例接收新的 `task_revision`、确认并提交修复。复审时，普通 Full 请求按原步骤重新冻结实际变化的范围；Foundation 检查点和集成工作树按其既有阶段入口恢复。已修订的 Reviewer 继续使用原实例，确认新版后再交回结果。

尚未绑定实例、宿主明确证实创建失败时，使用 `pool release --receipt "$claim_receipt" --outcome definitely_not_created "${capacity[@]}"`，沿用原始领取回执和最新观察的容量。创建结果未知时传 `--outcome unknown` 并保留回执与占用，核实后再绑定或释放。若旧版本的领取回执无法与原件可靠对应，保留占用，回查原宿主创建结果。整份原件中的任务已终结、资源占用已解除并完成证据交接后，PM 可用 `pool archive --record "$record" --expect-sha256 "$record_sha"` 移除该条索引，原记录继续保留供交接与审计。

## Prefer the existing tool

- Use the installed `task_graph_cli.py` commands below instead of creating fresh `prepare-*`,
  `amend-*`, `authorize-*`, `verify-*`, or `save-checkpoint-*` Python programs for the same mechanical
  operations. Do not merely move equivalent programs into large inline Python or shell commands.
- Native build/test/run commands remain the evidence for production delivery. A genuinely missing
  behavioral regression may need a project test; a one-off adapter or complex evidence format may
  justify a temporary helper. Keep it task-scoped, reuse it during that task, and do not turn it
  into a default deliverable or an additional acceptance gate.
- Internal records stay in the current resolved execution workspace, not the business source tree
  or a new controlled-document layer. Allocate this request's unique path with `scratch` below only when
  temporary files are actually needed, reusing it in place across retries, rework and QA. Light without
  that need creates no scratch or empty record.
  Do not invent dated or random `/tmp/<project>-*` folders, clone source trees (`work/`, `replay/`,
  `before/`, `packages-qa*`), or redirect global dependency/build caches (`Maven`, `Gradle`, `npm`,
  `Cargo`, `DerivedData`) into task scratch directories. Reuse the current graph and available
  receipts. Do not create a second task-state source, a receipt per step, or a new checkpoint script
  just to update metadata.
- For temporary resources needing reclamation, use the read-only preview, selective retention and
  snapshot-bound cleanup below. The caller first stops relevant writers and verifies ownership, active
  use and necessary references. First transfer mandatory complete logs to readable durable locations and
  repair references; otherwise retain exactly necessary files. Summaries or paths inside a directory about
  to be deleted cannot replace complete evidence. The tool neither infers semantic references nor authorizes
  cleanup of shared environments, databases, system caches, user material or other tasks' resources.

## Initialize a task graph

`init` mechanically assembles PM's explicit decisions into a new schema_version:2 graph. Existing schema 2
graphs still use `update`, retaining existing read/query/validation contracts. Input requires `request_id`,
`capacity`, `standards` and non-empty `tasks`, supplied with `--input <file>` or stdin. The call below
reuses a prepared decisions file in current scratch, without another task-state source. Declare top-level
schema_version:2 and provide each task's workflow_level, normalized module, role, agent_alias,
instance_policy:fresh and context_policy:handoff_only:

```bash
bash "<plugin-root>/lib/python_runtime.sh" -B -X utf8 "<plugin-root>/plugins/source_pack.py" helper --project "<absolute-project>" lib/task_graph_cli.py init \
  --root "${project_root:?set actual project root}" \
  --input "${workflow_decisions:?use PM decisions JSON}" \
  --output "${workflow_graph:?set new graph path}"
```

- `standards` explicitly lists `required_engineering_rule_ids`, `required_design_rule_ids`,
  `leaves: [{path, domain, rule_ids}]` and `protected_paths`. Protected entries include `path`, `rule_id`
  and `allowed_paths`. Omitted `direct_edit` becomes fixed `forbidden_without_exception`; reject other values.
  PM must list all applicable required rules, leaves and protected boundaries, not one sample rule or a guess
  left to the tool.
- Use the selected real project adapter. Source development can explicitly supply paired index/root paths. Read only the selected built-in or project-specific standards leaves. An absent index has a null fingerprint. An existing index uses its real SHA. Built-in rules come from the verified plugin, project rules from the project root.
- Each Writer retains its actual `id`, `task_type`, `role`, `surface_kind`, `goal`, `gates`, `owned_paths`,
  input/output contracts, acceptance evidence and `verification_commands`. 在 `selected_standards` 列出当前任务采用的叶子。
  路径字符串默认按该叶的 `rule_ids` 定向读取。需要关联章节时可传
  `{"path":"…","mode":"targeted","reason":"…","sections_or_queries":["适用范围"]}`，保留全部已选规则 ID。
  整份叶子构成任务依据时用 `{"path":"…","mode":"full","reason":"…"}` 写明原因。
  已有项目规范索引仍整份核对，以发现其他适用叶子和例外。PM still provides dependencies, locks and other applicable
  business fields; UI, protected-path exceptions and confirmations remain subject to the original validator.
- Optional top-level `requirements_fingerprint`, `approved_gates`, `active_paths` and `active_semantic_locks`
  accept only PM-established facts. The last three default empty, without inferred approval. The tool
  mechanically adds current SHA, standards-access references, `standards-conformance`, `DECLARED`, request-level
  QA and empty dependency/block/lock defaults. `controlled_document_access.adapter` 记录本次选定的实际适配器路径。
  Completion states, execution identities and receipts are not accepted as a way to fabricate completed work.

The tool first reuses original graph/standards/READY validation, then atomically publishes to the explicit
new file. Existing output, invalid authorization, missing standards coverage, unsafe paths or changes during
reading fail without publication. Success returns only `initialized`, `path`, `sha256`, `task_count`, not
the full graph. Initialization already validates current bytes; do not immediately repeat `validate`.
Query `ready` when dispatch is needed and `qa-ready` separately when scheduling QA. Success does not mean
a task is READY, requirements approved, verification passed or QA PASS.

## Update the current snapshot

`update` requires an existing `--input`, an explicit old `--expect-sha256`, and a patch from
`--patch <file>` or `--patch -` (stdin). Reuse the digest returned by the previous successful update;
if it is unknown, use `fingerprints` on just this graph file, not a whole-project scan.
The patch supports:

- PM 用独立的 `approve_solutions` 或 `revoke_solutions` 登记或撤回已核实的方案决定，适用的字段与来源见[方案交接](dispatch.md)。页面初次批准及真实原型返工后的重新绑定使用独立的 [`approve_visuals`](ui-design.md#登记具体页的视觉批准)。
- 普通 Full 的 PM 在 QA 通过后使用单一任务操作 [`record_qa_projection`](closeout.md) 登记文档回写，保留原审查包与回执。

- `tasks`: an object keyed by existing task ID. Each operation may contain `set`, `append`,
  `documents`, and `checkpoint`, or the exclusive result-task `settle` below. New-project Foundation
  QA also supports the exclusive checkpoint accept operations described below. `set` accepts `state`, `owned_paths`, `semantic_locks`, `input_contracts`,
  `output_contracts`, `acceptance_evidence`, `verification_commands`, and
  `controlled_document_access`, and optional `agent_ref`, `agent_retired`, `handoff_assessment`; `append` supports their existing arrays,
  except non-array fields; agent_ref, agent_retired and handoff_assessment cannot be appended.
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

### Full QA acceptance

普通 Full 在 Writer 达到交接条件后，由 PM 依据每个仓库的实际提交、Writer 开工时的基线与交付差异确定本次范围。同一文件已有未提交改动时，要能区分哪些改动属于本次，并保留可回读的差异证据。归属不清时先找原 Writer 补证；给整个工作区或文件列表计算摘要无法补出归属。冻结实际仓库、base/head、差异字节 SHA-256 和完整的项目相对路径。Use `update --input GRAPH --expect-sha256 GRAPH_SHA --patch -`
with only the `freeze_qa_scope` operation and reuse the returned graph SHA for subsequent writes:

```json
{"tasks":{"qa":{"freeze_qa_scope":{"repositories":[{
  "path":".","base_revision":"BASE","head_revision":"HEAD",
  "diff_fingerprint":"<actual-diff-sha256>","changed_paths":["src/current-file.py"]
}]}}}}
```

需在 QA 通过后回写 Full 主题时，先在原主题补齐非空的 `## 需求与验收`，保留本次已批准的原稿。单树的 PM 文档若未跟踪，或工作区原稿的字节与受审 Git 提交不同，导出 Reviewer 包前在同一个 `freeze_qa_scope` 对象内传入 `"scope_ref"` 与 `"projection_paths"`。前者使用上述范围对象，后者逐项填写本次回写的实际项目相对路径。QA 通过后，`record_qa_projection` 的 `reviewed` 引用该原稿及其 SHA-256。

Start or resume the original Reviewer and export its current task pack with
`task --input GRAPH --task-id QA --output PACK --expect-sha256 missing`. Ordinary Full exports
`qa_checkpoint.kind: request`, the actual reviewed Writer IDs, the frozen `task.qa_scope_ref`,
and `qa_checkpoint_fingerprint`. The Reviewer returns the complete frozen scope in
`review_method.scope_ref`. The fingerprint incorporates the Writer contracts, build evidence, exact
changed-file contents and applicable authority. Changes to these inputs require a fresh freeze.
For isolation, actual Git integration scope supplies this binding directly. Foundation keeps its
checkpoint contract.

After validating the handoff and observing actual native completion, record PASS with the existing
`update` command and one exclusive operation:

```json
{"tasks":{"qa":{"accept_request":{
  "task_pack":{"path":"/absolute/current-qa-pack.json","sha256":"<original-byte-sha256>"},
  "handoff":{"path":"/absolute/current-handoff.json","sha256":"<original-byte-sha256>"}
}}}}
```

Keep both original files readable as independent evidence. The update validates the current graph and
original bytes and writes the protected `request_receipt` together with `QA_PASSED`. Ordinary
`set state: QA_PASSED` is forbidden for Full. Writer rework or affected contract/evidence changes
reopen obsolete acceptance and preserve the original Reviewer identity and retirement state. Resume
that Reviewer with a newly exported pack after the affected Writers are verified. A historical
ordinary `QA_PASSED` without a receipt neither satisfies dependencies nor authorizes delivery.
Light continues through its single-pack acceptance.

### Foundation checkpoint acceptance

Only a Full QA node with immutable `foundation_task_id` uses these operations. Initialize that reference
with the original graph; feature writers depend on Foundation, while QA dependencies stay in its closure.
`qa-ready` and `task` derive the current Foundation/request checkpoint; never hand-edit checkpoint scope.
After a current PASS and successful native execution have actually been checked, use exactly one task
and one operation in the existing update patch:

```json
{"tasks":{"qa":{"accept_foundation":{
  "task_pack":{"path":"/absolute/current-qa-pack.json","sha256":"<original-byte-sha256>"},
  "handoff":{"path":"/absolute/current-handoff.json","sha256":"<original-byte-sha256>"}
}}}}
```

`accept_foundation` reuses the handoff validator, checks the current graph-derived checkpoint, exact
original Reviewer identity, closure fingerprint and integration evidence, and atomically saves protected
`foundation_receipt` while returning QA to `DECLARED`. It preserves `agent_ref` and never retires the
Reviewer or grants final `QA_PASSED`. Actual native completion and host occupancy remain PM observations.
Foundation contract/build/content/authority changes invalidate this receipt; normal feature edits and
integration HEAD advancement alone do not. Ordinary `set` cannot create a receipt.

After every request writer is `BUILD_VERIFIED` and current integration evidence is available, resume the
same QA node/Reviewer and export the complete `request` checkpoint. Use the same reference shape under
exclusive `accept_request` to validate the final current-byte PASS and record `QA_PASSED` with protected
`request_receipt`. Old Foundation packs and mixed phases are rejected.
The existing three-round recovery limit is shared; no additional business gate is created.

For example, after the PM has established a task's actual ready/dispatch decision:

```bash
bash "<plugin-root>/lib/python_runtime.sh" -B -X utf8 "<plugin-root>/plugins/source_pack.py" helper --project "<absolute-project>" lib/task_graph_cli.py update \
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
owned scope, input/output contracts, solution decisions, verification commands, locks or controlled-document contract
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

<a id="result-task-settlement"></a>

## Result-task settlement

Apply WORKFLOW's `Result-task settlement` for `task_type: read_only|evidence` only. PM first verifies the
actual native completion, accepted current-scope result and latest revised-pack acknowledgement. Then use
the existing `update` CLI with exactly one task's exclusive `settle`; no new CLI, state store or report is
required. Source example below uses absolute task-owned files. Plugin execution uses the verified
current source-pack entry for this same logical helper. 3.0 rejects every old runtime_binding in either
record or accepted pack and never enters an older bridge/content store.

```bash
bash lib/python_runtime.sh -B -X utf8 lib/task_graph_cli.py update \
  --input '<absolute-original-record>' --expect-sha256 '<current-original-record-sha>' --patch - <<'JSON'
{"tasks":{"existing-task-id":{"settle":{
  "schema_version":1,
  "agent_ref":{"host":"codex","agent_id":"actual-original-native-id"},
  "task_pack":{"path":"/absolute/accepted-current-task-pack.json","sha256":"<original-pack-byte-sha>"},
  "completion":{"state":"completed","agent_ref":{"host":"codex","agent_id":"actual-original-native-id"},
    "task_pack_sha256":"<same-original-pack-byte-sha>",
    "evidence":{"path":"/absolute/existing-native-events-or-result.json","sha256":"<evidence-byte-sha>"}},
  "result":{"task_pack_sha256":"<same-original-pack-byte-sha>",
    "evidence":[{"path":"/absolute/existing-current-result.log","sha256":"<result-byte-sha>"}]},
  "verification":[{"command":"<exact-current-verification-command>","exit_code":0,
    "evidence":{"path":"/absolute/existing-verification.log","sha256":"<log-byte-sha>"}}],
  "retire":true
}}}}
JSON
```

Replace all placeholders with actual current identities, accepted pack and evidence; `completion` is PM's
real tool observation, not a CLI host probe or a worker's unsupported completion assertion. Bind original
Task Pack bytes with existing `fingerprints` and reuse the complete pack actually delivered/acknowledged.
Keep necessary accepted-pack bytes and evidence readable for review. The helper compares the complete
current implementation contract/authority separately from runtime/closeout `state`, `agent_ref`,
`agent_retired`, `handoff_assessment` and `acceptance_evidence`, plus omitted empty Light graph fields.
An accepted first-dispatch pack may omit the not-yet-known native ID; any included `agent_ref` must match
the current immutable binding, and `settle.agent_ref` plus `completion.agent_ref` always match it exactly.
Legitimate metadata updates do not authorize changed task/request/role, ownership, contracts, validation,
standards or approvals. Changed scope, approvals, standards, resource authority, wrong identity or old result SHA rejects.
Use the explicit complete Task Pack snapshot actually delivered/acknowledged, physically separate from
the mutable original record. Existing `task` export supports the task artifact; retain its delivered bytes
and SHA. A Light record cannot serve simultaneously as the accepted snapshot being preserved and the
record being overwritten. No new report or second ledger is required.

Evidence references reuse explicit existing task-owned native exports/results/logs. Each is an absolute
single-link regular file with exact SHA and the existing safe-reader 4MiB limit; do not scan histories or
replace raw evidence with summaries. A large native export may use an already exported scoped native
result; no new per-task report or mandatory ledger is introduced. PM verifies the actual latest-scope
acknowledgement and meaning of the source; file shape/SHA alone cannot prove native execution.

`verification` follows the current declared commands in order, exactly once. Ordinary string commands
require actual exit 0 and their real logs. A frozen `{run, expected}` command additionally requires matching
`expected` text in its verification item, allowing an explicitly expected negative-control result; PM
verifies that the observed exit/output actually satisfies that contract. An observation-only task may
declare no shell commands and use `verification: []`; its real result/native evidence remains required.
Do not manufacture shell success for a native observation or human audit.

`retire` is optional boolean; true only records logical non-reuse. Success publishes RESULT_VERIFIED,
the compact settlement/evidence references in existing acceptance_evidence, and optional retirement in
one original CAS. It releases record execution occupancy and owned locks; actual native close/capacity is
still unknown until observed separately. A stale original SHA, failed check or busy publication lock leaves
the original unchanged; inspect conflicts before retry. Plain `set.state=RESULT_VERIFIED`, mixed settle/set,
multi-task settlement and Writer/QA settlement reject. Existing Writer build and QA handoff gates remain.
Current 3.0 result records reject legacy Writer success values BUILD_VERIFIED, QA_SCOPE_READY and QA;
only evidence-bound RESULT_VERIFIED completes read_only/evidence work. Historical files remain ordinary
read-only audit material without migration or fabricated settlement evidence. At publication,
the original locked CAS boundary rechecks this round's new receipt sources and rejects every accepted-pack,
completion, result or verification source physically aliasing the target record. Independent copies with the same bytes remain valid; unrelated updates do not rescan old receipts.
Refresh the admission manifest SHA after success, then use `view` only when its relevant inputs changed.
Old runtime bindings are rejected, not migrated; never mutate old cores or hand-edit historical native
failure fixtures to make current settlement pass.

## Export a complete changed Task Pack

Use `task --input <graph> --task-id <existing-id>` to return the complete current task object.
An explicit `--output <task-pack.json> --expect-sha256 missing` safely creates a new internal pack;
for an existing output, pass its observed digest instead of `missing`. The graph cannot be the output.
No pack or revision archive is created by default. A scope/contract change requires complete affected
handoff under the plan lifecycle; a state-only change does not require rebuilding every Task Pack.
The exported shell contains schema_version:2, current task, applicable standards_contract and necessary
approval/UI authority, without sibling tasks, the full graph or PM/sibling history. Export preserves the recorded state; it never resets work,
changes acceptance or messages a worker.

Light uses a same-shape single pack: `task --input PACK` without --task-id validates/returns the current
shell. Explicit output retains --output/--expect-sha256. `update --input PACK --expect-sha256 SHA --patch PATCH`
retains the `{tasks:{current-id:{set/append/...}}}` patch for this task. To record the user’s approval of its exact current solution after a pause, use the separate `approve_solutions` patch described in [dispatch](dispatch.md). Light retains current task.state but does not require a Full graph, dependencies, planning
or QA fields. continuation still includes current --task-id.

Optional `handoff_assessment` records only an actual handoff judgment:
`{independent_qa: required|not_required, documentation: required|not_required, reason: <non-empty grounds>}`.
Omit it when no assessment record is needed; add no mandatory Light ledger. Full must not use not_required
to skip independent QA. Memory persistence still follows existing on-demand principles; create no empty memory.

When the recipient's host can read the exported file, hand off the exact complete-file reference, current
file SHA-256 and brief change summary. The recipient verifies version and reads the current Task Pack under
the complete-reading rules below; summaries/deltas cannot replace it. If that host cannot read the file,
deliver the complete pack through a supported channel. If the same instance already received/read that
version completely, the file is merely another transport and needs no reread. An unchanged contract does
not require pack regeneration merely for transport.

## Native capability observations, usage and same-Agent continuation

Use the entries below on demand, without a new Full graph, report or gate for ordinary read-only/Light work.
They reuse current-host capabilities without starting a runner, daemon, MCP or second Agent scheduler.
Installation/diagnosis does not automatically enable native capabilities, boost, teamwork or other optional modes.

Use the same verified plugin and actual project for a read-only capability report:

```bash
bash "<plugin-root>/lib/python_runtime.sh" -B -X utf8 "<plugin-root>/plugins/source_pack.py" \
  helper --project "<absolute-project>" lib/hosts/capabilities.py --platform antigravity
```

`documented` means only documented capability, `source_observed` only that explicit source bytes were
observed, and `runtime_unverified` that current-session behavior remains unverified. By default no host
process starts; explicit `--probe-version` runs only that host's `--version`, without login, model invocation or
`/skills`. AGY checks only the explicit project path `.agents/skills/grill-me/SKILL.md`.
`customization_sources.grill_me.project_definition` discloses `status`, `sha256`, `declared_name`, etc.
A matching name yields `same_name_risk: possible`; the actual source remains `actual_source.status: unknown`.
File existence does not establish which Skill the current session loaded. Check actual provenance/applicable
contracts for the historical AGY native `/grill-me` source observation versus this pack's current
`xy-grill-me` user-invoked adapter and PM coverage via `xy-grilling` loading original `grilling`. Do not
automatically substitute, rename aliases or omit this pack's Full requirement coverage, or scan personal
Skill directories.

`continuous_intake` keeps separate `runtime_checks` for message delivery, native wait wakeup, original
task continuity, same-ID followup and parent-final/cancellation lifecycle. Each stays `runtime_unverified`
with no evidence reference until actual target-session evidence exists; doctor does not ingest proofs or
change these records. `observed_capabilities` remains unknown, never inferred from versions/configuration.
`not_found` means only that this probe's PATH did not find that executable, not that the user has not installed
the product. Use the current-host integration for official client controls, without writing host settings or databases.

After exporting native usage metadata for the authorized project, invoke its read-only adapter:

```bash
cd "${project_root:?请设置实际业务项目根}"
bash "<plugin-root>/lib/python_runtime.sh" -B -X utf8 "<plugin-root>/plugins/source_pack.py" helper --project "<absolute-project>" lib/delivery/native_usage.py \
  --host codex --input "${native_usage_input:?set explicit exported JSON or JSONL}"
```

`--input` is repeatable and reads in input-observation order. Data stays within the local task scope;
do not scan accounts or other sessions. Codex deduplicates responses by `(thread_id, response_id)`;
do not additionally mix turn counts using another accounting basis. Claude uses native terminal-result
fields/identity. AGY result usage is a cumulative snapshot. Preserve `unknown` when the initial baseline
is unknown, returning `last_cumulative` and first-to-last `observed_delta`. A single snapshot has null delta;
do not sum entries or replace unknown with zero. Missing counts remain null; real zero remains 0. Do not
add cache/reasoning subcounts into native total again or calculate cost/token-savings percentages. State
only sampled session, response and completed-turn scope. Main-session samples do not represent sub-Agents;
zero values from unsampled hosts cannot masquerade as a baseline.

### Task identity, same-task continuation and retirement

A schema 2 task's module／role／agent_alias bind ongoing responsibilities; instance_policy is fixed fresh and
context_policy fixed handoff_only. Create new instances on demand for independent tasks, without prewarming
all aliases or copying full parent/sibling history. WORKFLOW's agent-instance-lifecycle owns lifecycle
authority. The task-pool index points back to those same original task records.

Record `agent_ref: {host: codex|claude|antigravity, agent_id: <actual-native-ID>}` only after PM verifies
actual authorized dispatch results. First put the task into actual RUNNING (an explicit qa may also use QA),
freeze/export its complete current pack, create the native instance with those bytes, then bind the actual
returned ID in a separate update, never combined with first execution-state entry. The accepted complete
pack can omit `agent_ref`; read_only/evidence settlement keeps its original byte SHA without requiring a
resend solely to add the ID. QA handoff still binds its current complete QA pack and actual identity. After first binding,
only same-value idempotent writes are allowed, without overwrite/clear. Different tasks in one graph,
including historically completed tasks, cannot share identities. A valid ID shape proves neither actual
liveness, role, approval nor completion.

Request QA uses at most one task across the same physical project's explicit records for that request,
including failed/passed/retired history. Delta review uses that same task and original immutable identity.
Missing/cancelled/retired Reviewer state returns to PM for explicit request recovery/acceptance handling;
it does not authorize a second QA task, automatic replacement or identity rebinding.

`agent_retired` is an optional bool, default false. It may move only from absent/false to true, irreversibly.
Retirement prevents misdispatch; it cannot change an executing task's state or release path/semantic locks,
and does not mean native close succeeded. Record missing/failed native-close capability in the existing
task. For cancellation/unknown state, first verify existing results and recovery boundaries.

After observing actual state through exposed tools, PM runs the installed read-only query from the
business-project root:

```bash
bash "<plugin-root>/lib/python_runtime.sh" -B -X utf8 "<plugin-root>/plugins/source_pack.py" helper --project "<absolute-project>" lib/agent_continuation_cli.py \
  --input "${workflow_record:?set current schema 2 graph or Light pack}" --task-id "${task_id:?set existing ID}" \
  --host codex --observed-state running --intent append --capability non_interrupting_message
```

`--intent` accepts
`observe` (default), `progress`, `append` or `independent`. Repeat `--capability` only for names actually
verified on the current exposed authorized native tools: `non_interrupting_message` and `idle_followup`.
Do not copy the example capability merely because a product's documentation mentions messaging. Unknown
or duplicate capability names reject. `observe` + running recommends `wait`; `progress`/`append` + running
recommends `message` only with `non_interrupting_message`, otherwise `wait`. Idle needs `idle_followup`
for `followup`, otherwise it blocks. Independent work recommends `new_task`, never reuses the old ID.
All identity, retirement, cancelled/unknown and active-task checks run before these decisions. The old
`task_graph_cli.py continuation` still supports its original observation-only wait/followup contract.

<a id="reviewer-context-exhaustion"></a>

两个入口均接受 `--observed-state context_exhausted`。仅当 PM 从当前绑定实例、本次原生调用的
终止事件确认上下文耗尽时使用，查询会返回 `blocked`，即使已核实同 ID 续发能力也停止自动重放。
面板显示 idle、耗时、用量、用户转述及日志中的报错文字均不足以确认终止原因。
已确认的中断由 PM 在原任务保留证据定位，后续恢复须核对此记录；如果只有含糊的终止通知则用
`unknown` 等待核实。普通运行或成功压缩沿用原有恢复路径。

Claude 的两个入口还可附 `--claude-event <单条原生事件.json>`，在传入的当前面板观察上判别
已知的空摘要中断。PM 须核实原生通知与事件的来源、最新调用及身份；helper 只读给定事件，
检查绑定 ID、事件标记及具体原因，既不扫描转录也不持久化。完整调用方式见
[Claude 恢复说明](../../../../claude/references/pm-integration.md#background-execution-and-recovery)。
原 Reviewer 缺少本轮已验证的最终回执时，保持 QA 待验，保留有效的构建、测试和已核查范围。
中断不会自动发起替代审查或修改 QA 身份。PM 依现有请求恢复约定处理未覆盖项。

Before append, apply WORKFLOW's `continuous-pm-intake`: revise the complete scope/contract and necessary
approval, send the complete affected pack and confirm receipt before accepting new-scope results. The query's
`revision_required`/`acceptance_requires_ack` are reminders, not approval/receipt evidence. Execute a suggested
message only with the verified non-interrupting native tool to the same ID; interrupt/stop is not steer.
Short rework may continue on the same instance; the original same-round QA Reviewer performs delta review.
No automatic continuation for
independent tasks, cross-host work, cancelled／missing／unknown, unbound, completed or retired tasks. The query
does not probe, dispatch, message, unlock or clear context. A blocking recommendation is a normal query result
(exit 0); invalid input exits 2. Still hand off current complete pack/scope, reusing or restoring complete
reading under the rules below. resume／compact does not prove history erasure.

Keep instances through the current delivery unit's feedback window. Close natively promptly after closure,
acceptance and necessary evidence protection. When capacity is tight, prefer accepted/sufficiently handed-off
instances; do not LRU-evict executing, evidence-unreceived or necessary-review instances. Reserve subsequent
QA/integration capacity using actual host running/open-thread accounting. Without reliable close tools,
retire only, without claiming destruction or capacity release. Protect temporary worktrees/sole logs before
AGY kill; do not delete still-referenced evidence.

For schema/extract of native structured QA output, see
[`xy-qa-review` input contracts](../../xy-qa-review/references/inputs.md#原生结构化交接).
Task Packs still export mechanically with `task` above. Do not add model calls to convert natural language into JSON.

<a id="完整读取必需长文"></a>
<a id="read-required-long-documents-completely"></a>

## 按当前合同读取长文

压缩后先从现行任务包和交接取回所在阶段、已读版本、仍适用的决定及当前缺口。比如检查批准摘要只需 task-graph 的 “Concise user approval brief”；资源变化后的复核可从 verification-scope 的 “Handoff and valid evidence” 与对应交付类型开始。已知标题直接 `--section` 读取，检查依赖或例外。首次使用、来源换版、交接遗漏、上下文实质缺失或合同指定全文时，按实际所需范围恢复；显式全文不能用标题清单或摘要代替。

按问题定位长篇 Markdown 时，先用 `--outline` 看顶层标题，再重复 `--heading` 指定从父到子的标题路径。路径加 `--outline` 只列直接子标题。只给路径时返回该节直属正文及直接子标题；需要子节正文时才加 `--subtree`。已知标题路径即可直接读取，不同分支的同名子节用其父标题区分。在工作流源码根可以用架构模板试读：

```bash
bash lib/python_runtime.sh -B -X utf8 lib/documents/context_read.py templates/docs/ARCHITECTURE.md --outline
bash lib/python_runtime.sh -B -X utf8 lib/documents/context_read.py templates/docs/ARCHITECTURE.md --heading 项目架构 --outline
bash lib/python_runtime.sh -B -X utf8 lib/documents/context_read.py templates/docs/ARCHITECTURE.md --heading 项目架构 --heading 关键调用与数据流
```

标题列表只用于选路。实际项目使用当前文件及标题，必要时沿相邻约束与原文链接补齐依据。标题或正文都受 `--limit` 约束，续页保留原模式、标题路径、上一回包的 `next_offset` 与首次 `sha256`，分别作为 `--offset` 和 `--expect-sha256`。选区的 `eof` 只表示该次所选范围结束。插件使用下文同一物理插件的 helper 执行。

已有字面查询 `--find`、整节 `--section`、行段 `--lines`、全文分页和任务包读取继续按各自合同使用。该工具按需读取单一文件。

- 已知代码或日志的行号时，用 `--lines` 读取含首尾两行的原文，行号从 1 起算。长行按字符预算分页；续读保留同一行段、完整文件 SHA 和上一页给出的下一偏移。可参考 [QA 的源码取证示例](../../xy-qa-review/references/implementation-acceptance.md#按符号和行段核对源码)。

- 每个实例独立读完当前完整任务包、已选 Skill 入口及明确要求全文的指令、规范或引用。受控资料遵循 `controlled_document_access`。对于 `full`，从开头连续读到 EOF；对于 `targeted`，读完选中条款或章节，并补齐适用范围、例外、上位规则和必要上下文；对于 `skip`，不打开正文。其他实例的摘要、字段声明或 SHA 不能替代当前实例所需的正文。
- Directly reuse material fully read, unchanged and still completely available in the same instance context,
  including a complete task pack received/read as body text. A same-version file is only another transport.
  File-only receipt also needs only one complete read; do not repeatedly include the whole pack in later
  Skill/standards read commands. Explicit host/Skill reread requirements still apply. Do not add reading
  ledgers or force all-material rereads merely to prove reuse.
- Restore actual missing portions when absence, tool truncation or context compaction removes complete
  availability. For actual content changes, restore affected required content and check the rest remains
  available. A previous read does not allow new rules to be skipped or require reloading the unchanged whole
  tree. Contract changes still require the latest complete self-contained task pack under the original
  lifecycle; deltas/summaries cannot replace it.
- 先按固定路径、规则 ID 或标题定位。可选的 `--find` 按字面返回命中位置与有限片段，查找结果的 `eof` 仅表示搜索结束。用同一文件、同一 SHA 的正文分页展开所需范围，必要时从命中之前的条款标题读起。未命中时核对标题、相邻章节与引用；仍缺少必需依据就报告缺口。命中、片段和机器校验均不能证明已读完所需条款。
- Markdown 采用井号标题（ATX）且标题唯一时，可用 `--section '当前进展与恢复入口'` 读取标题、正文和子节，止于下一个同级或上级标题之前。首次省略 `--offset`，后续保留同一标题，带上 `next_offset` 和同一 `--expect-sha256`。回包的 `section_start_offset`、`section_end_offset` 及分页位置均为全文件内的 Unicode 字符偏移。该模式的 `eof` 仅表示到达该节末尾。标题缺失、同名，或下划线标题、原始 HTML 等复杂结构使边界无法确定时，按上条用 `--find` 和周边正文核实位置。若所需条款还引用上位约束、例外或其他章节，继续按引用展开。

普通正文页返回实际物理 `path`、`text`、`sha256`、`offset`、`end_offset`、`next_offset`、`eof`、`total_chars` 和 `total_bytes`。
Positions count Unicode characters and represent half-open `[offset, end_offset)` ranges. Default `limit`
is 6000 characters, maximum 24000. It bounds returned text, not an exact token cap or total serialized-JSON
size; escaping, metadata and host tokenizers add overhead. Reserve enough output budget for the complete
response, or lower `--limit`. Read long documents separately, one page per tool response.

例如，核对规则可先用 `--find '规则 ID' --max-matches 3 --limit 240`，再取同版回包的
`matches[].offset` 或已定位的条款起点，以 `--offset`、`--expect-sha256` 和适当的 `--limit` 展开原文。
继续查其他命中时保留原查询与 SHA，使用搜索回包的 `next_offset`。

```bash
# 首页只传宿主已选中的一个物理入口。此例读取发行包中的 xy-workflow。
bash "<plugin-root>/lib/python_runtime.sh" -B -X utf8 "<plugin-root>/plugins/source_pack.py" helper --project "<absolute-project>" lib/documents/context_read.py \
  "<plugin-root>/skills/xy-workflow/SKILL.md" --limit 1000
# 续页：填入上一完整回包的 next_offset 与首次页 sha256，不猜测位置。
bash "<plugin-root>/lib/python_runtime.sh" -B -X utf8 "<plugin-root>/plugins/source_pack.py" helper --project "<absolute-project>" lib/documents/context_read.py \
  "<plugin-root>/skills/xy-workflow/SKILL.md" --offset "${document_offset:?use previous next_offset}" \
  --limit 1000 --expect-sha256 "${document_sha:?use first page sha256}"
```

全文读取时，按上一正文页的 `next_offset` 无间断续读，直至 `eof: true` 且 `next_offset: null`。空文件或恰好到达字符总数的偏移返回空 EOF 页。定向读取在所需正文及依赖完整时结束。

若一次任务选中四个入口，四份正文分别返回。收到完整回包且宿主未标记截断时，核对实际路径、
SHA、起点和正文字符数与区间长度相符，再采纳该页的下一位置或 EOF。若第三份文件的某页
缺失或截断，保留前两份的完整正文和第三份的已确认前缀，从该页起点用更小的预算重取。
完整确认第三份之后再读第四份。文件版本变化时，重新核对该文件在新版本中的所需范围；用于全文读取的旧页不能与新页拼接。

插件原样资源按来源清单读取；发行包发现入口使用已选安装根下
`skills/<name>/SKILL.md` 的绝对路径，按发行载荷 SHA 核对实际生成的正文。
项目适配器、业务文件和任务记录继续由项目读取器读取。包外的宿主 Skill 按各自资源机制
读取实际入口，沿用同样的单页确认与恢复原则。

Each call computes SHA over complete original bytes, decodes strict UTF-8 without CRLF normalization and
allows very long single lines across character pages. Concatenating decoded `text` pages in order restores
original UTF-8 bytes. Every `offset > 0` requires a matching `--expect-sha256`. A changed body rejects
continuation. Obtain the current digest and locate the required range again. Retain the safe reader's 4 MiB input limit. Reject
symlinks, hard links, special nodes such as FIFOs, unsafe parents, invalid UTF-8, incomplete/changing reads,
invalid budgets and out-of-bounds positions. Exit 0 returns one page; exit 2 reports input/read errors on
stderr without echoing text. The tool writes no read cache/state.

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
bash "<plugin-root>/lib/python_runtime.sh" -B -X utf8 "<plugin-root>/plugins/source_pack.py" helper --project "<absolute-project>" lib/task_graph_cli.py fingerprints \
  --root "${project_root:?set actual project root}" --input "${evidence_receipt:?use existing receipt}" \
  --select owned_paths_sha256 --select artifacts_sha256
```

Review the relevant original command, exit status, scope, native result and environment as before.
Matching bytes alone never proves that a command ran, tests passed, the program runs, or QA passed.

## Allocate and clean up the task scratch workspace

Use `scratch` to resolve each project/request's unique directory only when temporary files are actually
needed; reuse it in place through closeout. Create no date-, round- or candidate-named copies. Keep new
resources' purpose, owner, reuse entry point and retention/reclamation conditions in original Task Pack
contracts/acceptance evidence, without a separate directory inventory, resource ledger or report.

Request IDs retain the task graph's non-empty string contract, including Unicode and punctuation.
The directory name uses the full ID's SHA-256, keeping case-distinct requests separate even on a
case-insensitive filesystem; the returned `request_id` remains the original logical ID. The new
`agent-workflow-request-scratch` container is separate from legacy `agent-workflow-scratch`; legacy
directories are not adopted or automatically deleted, even when an old ID looks like a new hash name.
Cleanup retains the empty project scratch root to avoid removing an unpinned parent path after closing
its descriptor. Directories that cannot be opened safely, including those without read/search access,
are preserved with an error; do not fall back to changing permissions through an unchecked path.

```bash
bash "<plugin-root>/lib/python_runtime.sh" -B -X utf8 "<plugin-root>/plugins/source_pack.py" helper --project "<absolute-project>" lib/task_graph_cli.py scratch \
  --root "${project_root:?set actual project root}" --request-id "${request_id:?set request id}"
```

For registered request closeout, include `--pm-id <host>:<current-native-PM-id>` in both calls.
The helper revalidates current request acceptance, the original native instances' recorded terminal
observations and the registered originals. The preview automatically retains original records and
current, explicitly referenced scratch evidence, including native observation evidence and preservation manifests. Supply
explicit `--keep` values for additional evidence and references held outside the task records.
Keep the registration through cleanup, and continue to preserve native history and accepted work.
The older cleanup route serves unregistered scratch only. The project-wide option requires an empty
registered inventory. Both routes coordinate with project registration and authoritative record
publication while determining references and applying the reviewed deletion.

`cleanup-scratch` requires a read-only preview before execution with the same target and retained items:

```bash
bash "<plugin-root>/lib/python_runtime.sh" -B -X utf8 "<plugin-root>/plugins/source_pack.py" helper --project "<absolute-project>" lib/task_graph_cli.py cleanup-scratch \
  --root "${project_root:?set actual project root}" --request-id "${request_id:?set request id}" --pm-id "${pm_id:?set actual PM identity}" --dry-run
# 核对归属、使用和引用后，将预览返回的 snapshot_sha256 设为 scratch_snapshot_sha256。
bash "<plugin-root>/lib/python_runtime.sh" -B -X utf8 "<plugin-root>/plugins/source_pack.py" helper --project "<absolute-project>" lib/task_graph_cli.py cleanup-scratch \
  --root "${project_root:?set actual project root}" --request-id "${request_id:?set request id}" --pm-id "${pm_id:?set actual PM identity}" \
  --expect-sha256 "${scratch_snapshot_sha256:?use the reviewed preview snapshot SHA}"
```

To retain a still-referenced sole file, add identical `--keep <relative-file>` values to both commands;
repeat for multiple files. Only existing canonical relative regular files inside target scratch are
accepted, preserving necessary ancestor directories. Reject missing files, linked ancestors, wildcards
and traversal. Transferring evidence/repairing references first can narrow retention; one referenced file
does not require the whole candidate directory. Do not delete targets without proven ownership and absence
of active use.

Preview creates, chmods and deletes nothing. It returns totals and at most 20 `candidate_sample` items,
with `candidate_sample_truncated` explicitly indicating truncation. `snapshot_kind: metadata` and
`snapshot_sha256` bind metadata for the complete target/retained items, without reading large-file contents
or imposing a file-size limit. This is not a content fingerprint or proof of task completion/reference
transfer. Execution requires a current snapshot matching `--expect-sha256` and item-by-item rechecks, rejecting
changes. The caller still must stop task writers first; no atomic safety against non-cooperative malicious
concurrency before final unlink is promised. `--dry-run` and `--expect-sha256` are mutually exclusive;
old unpinned deletion is no longer accepted.

By default, close out only this `--request-id`. `--all` is only for explicitly authorized administrative
cleanup with known ownership of every target and no active use. It likewise requires preview/snapshot
binding and cannot combine with `--keep`; it is not a default action per task round. POSIX does not follow
links; ordinary hard links only unlink task-owned entries without changing external contents/permissions.
Windows retains its existing safe backend/link-rejection policy and does not label ctime as changeTime.
Permission/partial-deletion failure returns nonzero and truthfully retains successful counts, restoring
permissions temporarily adjusted to preserve necessary directories. `planned_logical_bytes`/
`removed_logical_bytes` count pending/removed entries by logical file length, not physical disk reclamation;
the misleading `reclaimed_bytes` is no longer used.

