# Reuse runtime record tools

Use this reference only to maintain existing internal task snapshots, export changed complete Task Packs,
generate/check file fingerprints or read long documents within bounds. It adds no task level, state,
business confirmation, QA phase or mandatory report. Light may directly maintain a same-shape single-task
pack without creating a Full graph or second ledger. Accept only schema_version:2.

Central projects first follow the [shared helper execution boundary](dispatch.md#workflow-helper-execution):
each call goes through the project thin entry with explicit current-pack `runtime_binding`; do not assume
shell environment persists across tool calls. The `.agent-workflow/lib/<helper>.py` commands below remain
source-pack development examples, resolved against the actual source root. Central mode passes the helper/arguments to the same pin's
`runtime.py --binding '<three-field JSON>' helper lib/<helper>.py`. New workflows first check machine-local
enabled state. New graphs freeze their top-level pin from the verified bridge environment or an explicitly
verified binding. Task export projects it unchanged; update/refresh do not alter it. Reject old packs with
missing pins, bridge conflicts or corrupt cores. Do not fill the current version from the project locator
or accept arbitrary `core_root` paths.

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
bash .agent-workflow/lib/python_runtime.sh -X utf8 .agent-workflow/lib/task_graph_cli.py init \
  --root "${project_root:?set actual project root}" \
  --input "${workflow_decisions:?use PM decisions JSON}" \
  --output "${workflow_graph:?set new graph path}"
```

- `standards` explicitly lists `required_engineering_rule_ids`, `required_design_rule_ids`,
  `leaves: [{path, domain, rule_ids}]` and `protected_paths`. Protected entries include `path`, `rule_id`
  and `allowed_paths`. Omitted `direct_edit` becomes fixed `forbidden_without_exception`; reject other values.
  PM must list all applicable required rules, leaves and protected boundaries, not one sample rule or a guess
  left to the tool.
- Source-pack mode reads the standards index/root from root-local `project.yaml` by default. Old self-contained
  installations explicitly set top-level `adapter_path: ".agent-workflow/project.yaml"`. Explicit source-pack
  cases may set paired `index_path`/`root` in `standards`, then omit `adapter_path`. Do not scan the entire
  standards directory. Central bridge context automatically uses the verified physical project's
  `.agent-workflow/project.yaml`, never core configuration. Explicit index/root must match that configuration;
  reject `--root` differing from the bridge project root. New graphs with an explicit pin also use the project's
  central adapter.
- leaves/selected_standards use exact built-in sources or actual project-specific leaves. Installed mode adds
  .agent-workflow/ only to the three managed sources; do not change project standards_root into a runtime
  directory. index_path/root always retain configured values. With no project rule leaves and a physically
  absent index, index_fingerprint is null; an existing explanatory index still uses its real SHA. init/document
  validation check real presence/absence; JSON-only validation does not claim filesystem checks. Add no fields
  or approvals. Central built-in sources read text, IDs, severities and fingerprints only from the task-pinned
  core. Standards classification still accepts only the three exact sources/existing aliases. Ordinary
  `file_digest` gains no permission to escape boundaries or follow symbolic/hard links.
- Each Writer retains its actual `id`, `task_type`, `role`, `surface_kind`, `goal`, `gates`, `owned_paths`,
  input/output contracts, acceptance evidence and `verification_commands`. Use `selected_standards: [leaf-path]`
  to identify listed leaves adopted by that task. PM still provides dependencies, locks and other applicable
  business fields; UI, protected-path exceptions and confirmations remain subject to the original validator.
- Optional top-level `requirements_fingerprint`, `approved_gates`, `active_paths` and `active_semantic_locks`
  accept only PM-established facts. The last three default empty, without inferred approval. The tool
  mechanically adds current SHA, standards-access references, `standards-conformance`, `DECLARED`, request-level
  QA and empty dependency/block/lock defaults. The logical `adapter` in standards access remains `project.yaml`.
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
`request_receipt`. Old Foundation packs and mixed phases are rejected. For this optional Foundation
contract, ordinary `set state: QA_PASSED` is forbidden. Requests without Foundation keep existing acceptance.
The existing three-round recovery limit is shared; no additional business gate is created.

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
retains the `{tasks:{current-id:{set/append/...}}}` patch, updating only this task, without changing other
tasks or approval. Light retains current task.state but does not require a Full graph, dependencies, planning
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

Run capability diagnosis from the central management tool's source-pack root. A business project's installed
`.agent-workflow` does not contain `manager`; do not execute manager modules from that runtime directory.
`--project` points to the actual business-project root:

```bash
# 子 shell 只为本次诊断切换目录，不影响后续安装态命令的工作目录。
(
  cd "${workflow_manager_source_root:?请设置中央管理工具源包根}"
  bash lib/python_runtime.sh -X utf8 -m manager.cli doctor --platform antigravity \
    --project "${project_root:?请设置实际业务项目根}"
)
```

`documented` means only documented capability, `source_observed` only that explicit source bytes were
observed, and `runtime_unverified` that current-session behavior remains unverified. By default no host
process starts; explicit `--probe` runs only that host's `--version`, without login, model invocation or
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

After explicitly exporting native usage metadata for the currently authorized scope, run the installed
read-only adapter from the actual business-project root, not the central-management source-pack root or
`.agent-workflow` directory:

```bash
cd "${project_root:?请设置实际业务项目根}"
bash .agent-workflow/lib/python_runtime.sh -X utf8 .agent-workflow/lib/delivery/native_usage.py \
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
authority. This file describes existing record tools only, without another pool.

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
bash .agent-workflow/lib/python_runtime.sh -B -X utf8 .agent-workflow/lib/agent_continuation_cli.py \
  --input "${workflow_record:?set current schema 2 graph or Light pack}" --task-id "${task_id:?set existing ID}" \
  --host codex --observed-state running --intent append --capability non_interrupting_message
```

In central mode translate this logical helper through the current pin's thin bridge above. `--intent` accepts
`observe` (default), `progress`, `append` or `independent`. Repeat `--capability` only for names actually
verified on the current exposed authorized native tools: `non_interrupting_message` and `idle_followup`.
Do not copy the example capability merely because a product's documentation mentions messaging. Unknown
or duplicate capability names reject. `observe` + running recommends `wait`; `progress`/`append` + running
recommends `message` only with `non_interrupting_message`, otherwise `wait`. Idle needs `idle_followup`
for `followup`, otherwise it blocks. Independent work recommends `new_task`, never reuses the old ID.
All identity, retirement, cancelled/unknown and active-task checks run before these decisions. The old
`task_graph_cli.py continuation` still supports its original observation-only wait/followup contract.

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

## Read required long documents completely

`context_read.py <file> [--offset <n>] [--limit <n>] [--expect-sha256 <sha>] [--task-pack <current-pack>]`
is an optional standard-library, read-only single-file pager. It adds no mandatory command, gate, receipt
or reading record. Apply these reading/reuse boundaries:

- Each Agent independently reads the complete current self-contained task pack, required Skills/instructions
  and applicable standards. Another Agent's reading, field declarations, summaries or SHA do not replace
  this instance's full reading. New instances do not inherit old instances' read status.
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
- Read long documents separately or in contiguous pages through EOF. Reduce individual text size when output
  budget is insufficient and restore all truncated ranges before relying on conclusions. Locate ordinary
  business material by task-relevant headings/queries. Complete required-standards reading does not expand
  to the entire business directory or secrets. Complete machine-byte checks may return only fingerprints/
  results, but cannot prove model reading.

JSON contains `text`, `sha256`, `offset`, `end_offset`, `next_offset`, `eof`, `total_chars` and `total_bytes`.
Positions count Unicode characters and represent half-open `[offset, end_offset)` ranges. Default `limit`
is 6000 characters, maximum 24000. It bounds returned text, not an exact token cap or total serialized-JSON
size; escaping, metadata and host tokenizers add overhead. Reserve enough output budget for the complete
response, or lower `--limit`. Read long documents separately, one page per tool response.

```bash
# 首页：只指定当前必需的一个文件；安装态从项目根运行。
bash .agent-workflow/lib/python_runtime.sh -X utf8 .agent-workflow/lib/documents/context_read.py \
  .agents/skills/xy-workflow/SKILL.md --limit 6000
# 续页：填入上一完整回包的 next_offset 与首次页 sha256，不猜测位置。
bash .agent-workflow/lib/python_runtime.sh -X utf8 .agent-workflow/lib/documents/context_read.py \
  .agents/skills/xy-workflow/SKILL.md --offset "${document_offset:?use previous next_offset}" \
  --limit 6000 --expect-sha256 "${document_sha:?use first page sha256}"
```

Claude uses the actual `.claude/skills/` path; other hosts likewise reuse current known paths. Follow the
previous page's `next_offset` strictly and continuously until `eof: true` and `next_offset: null`. Empty
files or an explicit offset equal to total characters return an empty EOF page. Restore every missing/
truncated range before using the whole text. File fingerprints prove only matching bytes/version, not
model reading.

The host-discovery path examples above apply to source-pack development. Central
reads must use the bridge linked at the start, also passing `--task-pack` to the pager. Managed resources
use fixed logical paths such as `.agent-workflow/platforms/shared/skills/xy-workflow/SKILL.md` or
`.agent-workflow/product/WORKFLOW.md`. The pager takes the pin from the current pack and reads original
content directly from the content-store manifest. Changed project Skill/directory symlinks cannot alter
that text; continuation pages still check the same complete SHA. `.agent-workflow/project.yaml`, locators,
business files and ordinary scratch documents still use the project's safe real-file reader. A pin does
not permit following arbitrary project symlinks or making all `.agent-workflow` a link. Source calls without
central context retain their source semantics; version 2.1 has no old self-contained compatibility branch.

Each call computes SHA over complete original bytes, decodes strict UTF-8 without CRLF normalization and
allows very long single lines across character pages. Concatenating decoded `text` pages in order restores
original UTF-8 bytes. Every `offset > 0` requires first-page `--expect-sha256`. A changed body rejects
continuation and requires rereading from offset 0. Retain the safe reader's 4 MiB input limit. Reject
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
bash .agent-workflow/lib/python_runtime.sh -X utf8 .agent-workflow/lib/task_graph_cli.py fingerprints \
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
bash .agent-workflow/lib/python_runtime.sh -X utf8 .agent-workflow/lib/task_graph_cli.py scratch \
  --root "${project_root:?set actual project root}" --request-id "${request_id:?set request id}"
```

`cleanup-scratch` requires a read-only preview before execution with the same target and retained items:

```bash
bash .agent-workflow/lib/python_runtime.sh -X utf8 .agent-workflow/lib/task_graph_cli.py cleanup-scratch \
  --root "${project_root:?set actual project root}" --request-id "${request_id:?set request id}" --dry-run
# 核对归属、使用和引用后，将预览返回的 snapshot_sha256 设为 scratch_snapshot_sha256。
bash .agent-workflow/lib/python_runtime.sh -X utf8 .agent-workflow/lib/task_graph_cli.py cleanup-scratch \
  --root "${project_root:?set actual project root}" --request-id "${request_id:?set request id}" \
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

