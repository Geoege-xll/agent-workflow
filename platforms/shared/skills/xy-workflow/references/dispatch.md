## Path resolution and role resources

Use existing paths already established in this context. For an unresolved existing file, follow
the adapter's configured index links or run one scoped `rg --files <relevant-directory>` and reuse
the result. For hidden resources, add `--hidden`; use `--no-ignore` only when the requested resource
is excluded by ignore rules, still within the relevant directory and excluding dependencies/build
outputs. No match proves absence only within that search's filters. Do not infer a filename from
a business label, old example or another project's layout.
New paths belong explicitly to the approved plan/`owned_paths`; they are not claimed existing files.
For search, `rg` exit 1 means no match, while exit 2 or a read error needs inspection. Optional
no-match searches may be handled as absence; do not mask missing required files or batch failures.

`xy-uiux` and `xy-qa` are available even before implementation manifests exist; their availability
does not select a UI route, grant writes, or add a confirmation. Implementation roles still follow
current repository facts. After cloning/adding a module, changing the stack, or finding a required
role unavailable, assess the affected host's resources before dispatch; this is not a per-task probe.
Reuse current ProjectProfile facts and prior successful installation evidence while their inputs
and resources remain unchanged. If those facts already establish that a refresh is required, go
directly to refresh rather than running a redundant presence check. When role availability is
unknown, perform one read-only resource check using the current host:

```bash
bash .agent-workflow/lib/python_runtime.sh -X utf8 .agent-workflow/lib/project_profile_cli.py \
  check-roles codex .agent-workflow .
```

Use `claude` or `antigravity` for that host; do not preload other hosts' integration files. This
presence check does not prove configuration/content validity or establish fresh installation evidence.
Refresh when required native resources are missing/invalid, or installation inputs changed:

- Codex persists module/stack/verification-command context in its generated roles. Changed persisted
  facts require one refresh even when role names stay the same.
- Claude/Antigravity receive dynamic module and command facts through the PM task pack. When the
  role set, source pack/configuration, installation root/runtime and design-scaffold needs are unchanged,
  managed resources have valid unchanged installation evidence, and required document/prototype
  scaffolds are complete, refresh only the current task-pack facts; do not reinstall for a module
  path, stack or command change alone. Missing or changed installation inputs still require setup.

Codex 的发现上下文按相同事实组／命令组去重，每个模块仍保留确切 root、命令 cwd 及
证据基点映射；不同参数、用途或证据不会因表面相似被合并。需要核查某角色的完整
映射时，可只读运行 `project_profile_cli.py context .agent-workflow . <role>`，并沿用下文
Python 入口；它复用发现器、不执行候选命令、不写状态或刷新宿主，也不改变上述刷新条件。

For a required refresh, run the current host's normal `setup_<host>.sh`, then `--check` once. Normal
setup already performs its mandatory preflight; do not prepend another standalone `--preflight`
unless a write-free preview or aggregate multi-host preflight is specifically needed. Preserve all
ownership protections, populated documents, user settings, native permissions/Hook trust and active
worktrees. A role description read in PM context is not a substitute for native installation.
If the host caches changed roles, use its supported reload while retaining current task/approvals;
report actual unavailability if necessary. Reuse successful refresh/check evidence until affected
inputs or resources change; do not repeat a completed refresh for the same change. Light/read-only work
does not trigger it merely on a new prompt. This is installation maintenance within existing
dispatch, not a new business gate, QA stage or full test run; Hooks never auto-install roles.

## Workflow helper execution

- Reuse the existing [record tools](runtime-records.md) for common snapshot updates, Task Pack
  export and selected fingerprint checks. Prefer existing project verification commands for behavior.
  Do not create a one-off program or extra receipt for each routine PM metadata operation.
- 实际新增资源时，按 WORKFLOW 的 Task Packs 合同，在原 `input_contracts`、`output_contracts`
  与 `acceptance_evidence` 明确目的、落点、所有者、复用入口和保留／回收条件。先复用所属
  项目／服务的配置、环境、数据与系统缓存；临时文件确有需要才分配本请求唯一 scratch。
  无新增资源不创建空记录，也不因此给 Light 增加 Full 图、计划或 QA。
- 必需 Skill 或指令无法在一次可靠回包中完整返回时，可选用
  [单文件分页器](runtime-records.md#完整读取必需长文)。每次回包读取一页，以同一 SHA
  连续跟进每个 `next_offset` 直到 `eof`，为完整 JSON 预留宿主输出预算；字符预算不是
  精确 token 上限，必要时减小页大小。每位 Agent 仍独立完成必需读取，指纹不是已读证据。
- Use `bash .agent-workflow/lib/python_runtime.sh` for all workflow-owned Python, including
  temporary/inline helpers that generate DAG snapshots, Task Packs or fingerprints, not just bundled
  CLIs. For these workflow calls, pass `-X utf8` before the script path (or `-` for stdin), including
  bundled CLI output that may contain Chinese. Helpers specify `encoding="utf-8"` for text-file
  reads/writes. This does not replace a business project's own
  interpreter, virtual environment or build/test commands.
- Generate/update the current snapshot successfully before validation; a stale file left by a
  failed producer is not current evidence. Establish successful validation before the applicable
  query; a successful `task_graph_cli.py update` already supplies it for unchanged bytes, so do not
  add another `validate`. Within one shell call, connect dependent commands
  with `&&` or explicitly checked branches; across calls, inspect the producer's exit status first.
  On failure, repair that upstream cause before retrying its dependents. Do not fabricate an empty
  graph, suppress a required failure, or let a later success conceal an earlier failure. Independent
  graph branches remain eligible under the existing scheduler.
- Reuse successful runtime-selection evidence while its inputs are unchanged. Only if the selected
  interpreter is still unknown and needed for diagnosis, ask the same entry once:

  ```bash
  bash .agent-workflow/lib/python_runtime.sh -X utf8 -c 'import sys; print(sys.executable)'
  ```

  Respect an explicit `AGENT_WORKFLOW_PYTHON`; do not guess Homebrew paths or versioned executables,
  use unmatched shell globs such as `/opt/homebrew/bin/python3*`, or reread the runtime script merely
  to rediscover a working interpreter. Diagnose the script only when evidence points to it. Missing
  support is a reported environment limitation, not permission to install Python or alter global PATH.

On a Windows project installed through npx, use the native Node helper from PowerShell or cmd
instead of assuming `bash` or Python is on PATH:

```powershell
node .agent-workflow/lib/python_runtime.cjs -X utf8 .agent-workflow/lib/project_profile_cli.py check-roles codex .agent-workflow .
```

For other workflow Python examples, replace only `bash .agent-workflow/lib/python_runtime.sh` with
`node .agent-workflow/lib/python_runtime.cjs` and preserve the arguments. For inline Python, pass
`-` and supply source on stdin using the current shell's syntax; Bash here-doc syntax is not
PowerShell syntax. This helper reads the installed persistent runtime record, not npx's cache,
and retains the caller's cwd and explicit interpreter constraint. Do not infer that arbitrary
Bash commands become PowerShell commands; required host setup/check still runs through the
verified Git for Windows executable, without adding it to global PATH. When a refresh is required,
use the installed helper below for the current host, then run the same command with `--check` once:

```powershell
node .agent-workflow/lib/python_runtime.cjs .agent-workflow/lib/platform_process.py --host codex
```

Use `claude` or `antigravity` for that host. This invokes the existing host setup, not npx init,
a new installation workflow, or an automatic refresh at every task.

These are command-execution boundaries within existing steps, not additional workflow gates.

## Route

派发前先按 WORKFLOW 的 Light／Full 定义判断当前风险与实际消费者。两等级默认使用
对应原生实施者，只有明确的 PM 亲自实施授权例外；文档后缀不能扩大所有权。

### Light：自包含单任务派发

明确当前目标、精确拥有路径、验收、规范与最小验证后，使用 `schema_version: 2` 单包，
其 `task` 保留当前 `state`，带 `workflow_level: Light`、规范化 `module`（根为 `.`）、
`role`、稳定 `agent_alias`、`instance_policy: fresh`、`context_policy: handoff_only`。
当前目标／范围、代码与工作区依据、适用规范、可信授权来源、验收与必要证据、未决事项
必须完整。包不能携带完整 PM／兄弟会话；新实例不继承父历史，每位接收者仍完整读取必需
规范。实际原生参数只按当前宿主细则，不因声明 handoff_only 就声称运行时隔离已实测。

普通Light UI文案仍使用production_ui＋现有UI-Conformance，design_delta:none、
prototype_policy:not_applicable，当前已解析冻结design_authority_refs及工程／设计覆盖。
缺权威先补真实依据，实际设计／交互变化改Full；不得标non_ui或用空权威避过规范。

Light 不强制下述 Full Grill Me、xy-plan、图、计划保存、独立 QA 或再次确认。已有明确
用户范围授权可直接派发；实质未决合同和平台权限依原边界处理。执行最小充分验证，
交接时评估是否需要独立 QA、文档与记忆；选定后完成必需项，没有需要就不创建空记录。
Full 不可借此降级。具体包导出、状态与身份绑定见 [记录工具](runtime-records.md)。

### Full：规划、批准与图派发

下面的完整规划、图与 QA 路线适用于 Full；共享规范选择和最小充分验证原则也适用于 Light。
实施所有权、别名／实例与闭环收口统一遵守 `.agent-workflow/product/WORKFLOW.md` 的
`implementation-ownership` 和 `agent-instance-lifecycle`，本参考不另建实例状态来源。

1. `project.yaml` is the fixed workflow-adapter read for paths, limits, and routing configuration.
   Its `docs.*` values are discoverable indexes, not a static preload list.
   PM、Writer、QA 按实际领域选取内置来源，并在项目索引存在时沿链接补充适用特有叶；
   项目索引/叶不是安装必建副本，内置来源仍为必需规则底线。
   Project documents (`PROJECT.md`, feature details, and requirement plans) and agentmemory are
   auxiliary information sources. Read or query only the smallest task-relevant scope when the PM
   needs to supplement or verify an existing feature, durable decision, engineering or design
   constraint, cross-session background, or historical experience. When available task information
   is sufficient, do not force document retrieval or agentmemory start retrieval. Before opening a
   controlled-document body, create this task-scoped plan:

   ```yaml
   controlled_document_access:
     adapter: project.yaml
     documents:
       - path: <configured docs.* path>
         mode: targeted | full | skip
         reason: <task-specific justification>
         sections_or_queries: []
         content_fingerprint: <64-lowercase-hex-sha256>
         applies_to: []
         rule_ids: []
   ```

   Use `targeted` by default: when `project.yaml` -> `docs.project` (`PROJECT.md`) is needed to locate
   current feature truth, follow only task-relevant links, inspect headings or search task terms,
   then read only matching feature and decision sections. Use `full` only when the whole detailed document is materially required and
   state why. `skip` means do not open the body. Read design standards only for UI work and shared
   architecture details or plans only for a relevant missing fact.
   每位生产代码 Writer 的基线是内置 xy-code-standards/references/rules.md；生产 UI 另选
   xy-ui-design/references/foundations-rules.md、components-rules.md 的适用设计规则，
   xy-uiux + design_ui 只选适用设计来源。三源均以实际源包路径或安装态 .agent-workflow/ 前缀绑定，
   再加入适用项目特有叶。项目索引存在时绑定真实SHA；无项目叶且索引缺失时不生成空索引，
   index_path/root仍取配置，index_fingerprint为null。每个来源按现有字段覆盖owned_paths及适用ID，
   写入当前完整worker/QA包；缺失、过期或覆盖不足仍阻塞，不预载全部规范目录。
2. Classify production scope from the current request and available facts. If classification,
   requirement coverage, or planning materially depends on a missing project fact, apply the
   auxiliary-source policy above and retrieve only that fact before finalizing the classification:
   - Light: 范围明确、风险可控的单一交付面，含普通低风险文案；转上面的单包分支。
   - Full: 多角色、共享合同／数据库／根配置，或超出低风险文案边界的生产 UI。
   Light 仅在真实暂停／恢复／交接或明确要求时保存简短计划；Full 在批准后首次派发前保存。
   需要保存、修改或恢复时读取 [计划生命周期](plan-lifecycle.md)，保存 Light 不激活 Full Skills。
3. Activate `xy-project-memory` in start mode only when bounded cross-session recall or historical
   context is materially needed (Codex: `$xy-project-memory`; Claude Code and Antigravity CLI:
   `/xy-project-memory`). Do not invoke it merely because a new request started. When start retrieval
   runs, put its real `memory_context` only into task packs and the QA handoff that use those recalled
   claims. When no start retrieval ran, omit `memory_context`; do not manufacture an empty or
   ```yaml
   memory_context:
     provider: agentmemory | docs-fallback
     fallback_reason: null | provider-unavailable | project-isolation-unavailable
     project_id: <memory.project_id>
     filter_enforced: true | false
     capability_evidence: []
     query_scope: []
     memory_ids: []
     provenance_refs: []
     document_refs: []
     stale_or_conflicting: []
   ```
4. For UI, first decide whether the change is `UI-Conformance` with `design_delta: none` or a
   design change classified as `UI-Patch`, `UI-Page`, or `UI-Flow`. `UI-Conformance` requires
   `prototype_policy: not_applicable`,
   structured resolved and SHA-256-frozen `design_authority_refs`, no unresolved visual or
   interaction choice, and no write to `docs.standards_root/DESIGN_*.md`.
   Every authority entry contains exactly `kind`, stable `authority_id`, normalized project-relative
   `path`, non-empty `anchor`, 64-lowercase-hex `content_fingerprint`, and
   `resolution_state: resolved`. Allowed kinds are `controlled_document`, `prototype_contract`,
   `design_standard`, and `production_baseline`.
   Do not select a prototype policy for a design-change route yet. Record the exact affected
   surfaces and prepare both consequences so the PM can recommend one branch and the user can choose
   `required` or `waived_by_user` during requirements confirmation.
5. Every `Full` request performs a **Grill Me coverage check** by activating `grill-me`
   (Codex: `$grill-me`; Claude Code and Antigravity CLI: `/grill-me`). Use
   `coverage_check` when project facts may already be complete and `full_interview` only for the
   unresolved material gaps it identifies. A complete request returns without artificial
   questions. Clear Light work does not run this merely because the Skill is installed.
   Keep its complete `grill_result` internal. If the Skill is unavailable, use the local
   clarification fallback and record it internally.
6. After Full coverage is complete, activate `xy-plan` (Codex: `$xy-plan`; Claude Code and
   Antigravity CLI: `/xy-plan`). It returns a self-contained proposal with `plan_state: draft`,
   exact paths, interfaces, task packs, verification commands and expected results, semantic locks,
   and a machine-readable `task_graph`. The graph is internal scheduler input, not user-visible
   output. `xy-plan` does not edit files or dispatch Agents.
7. The PM reviews the draft and decides the post-QA controlled-document projection:

   ```yaml
   controlled_document_projection:
     project_docs_update: required | not_required
     change_type: added | updated | replaced | reimplemented | removed | restored | split | merged | renamed | cancelled | none
     affected_features: []
     project_index_update: required | not_required
     reason: <why current verified project or feature truth changes or remains unchanged>
   ```

   The PM then gives the concise natural-language approval brief and requests confirmation. For a
   design-change UI route, include one PM recommendation with a short reason and ask the user to
   choose design/update prototype or direct implementation. “Follow the recommendation” is an
   explicit choice only when exactly one recommendation is visible; a generic affirmative reply does
   not select a policy.
   Any explicit affirmative reply records `requirements_approved` internally only after both the
   requirements and any applicable prototype choice are resolved. Materialize only the selected
   graph branch and bind its
   `prototype_decision` to the frozen requirement fingerprint and exact affected surfaces. Do not
   edit `PROJECT.md` or an active feature document before explicit approval, and do not project the
   planned result into canonical documents until integrated QA returns PASS. After approval, freeze
   the requirement fingerprint, approved plan, selected decision, and proposed projection;
   implementation tasks consume that frozen contract directly. A material requirement,
   affected-surface, or plan-boundary change returns the plan to draft and reopens approval.
   The PM now saves the Full plan in adapter-resolved `docs.plans`, before any design/implementation
   dispatch. One independent requirement owns one plan; pending UI decisions remain explicit. Do not
   write PROJECT/feature truth just to save intended work. Merge subsequent effective changes into
   this same plan and replace affected complete Task Packs, including in-flight worker/QA inputs,
   before accepting their results. Preserve unaffected work; apply the linked plan lifecycle.
8. Build schema_version: 2 implementation task packs from that frozen plan with exact owned paths, dependencies,
   validation commands, expected concise evidence, and this routing contract:

   Before selecting verification, read
   `xy-build-verify/references/verification-scope.md` in the installed Skill directory. Select by
   changed behavior, dependencies and mandatory rules; discovered commands are candidates, not an
   automatic full-suite requirement. QA independently audits source and valid evidence without
   automatically rerunning all implementer checks.

   ```yaml
   surface_kind: production_ui | design_ui | non_ui
   qa_scope: request
   skill_policy:
     required_skills: []
     audit_surfaces: []
   ```

   `required_skills` contains only hard gates. `audit_surfaces` describes the work to
   inspect; do not copy or manually enumerate the user's installed specialist Skills. Every
   Writer adds `standards-conformance` as a mandatory base audit surface.

   每个 task 带 workflow_level、module、role、agent_alias、instance_policy: fresh 和
   context_policy: handoff_only。原生派发只交当前任务 shell 与必要规范、批准／UI依据，
   不复制完整 PM／兄弟会话、不 fork 继承父历史。独立任务新实例，同任务短返工才可续用。

   Include a brief reporting/reading instruction in every worker and QA task pack: report completion
   and blockers to PM, give meaningful milestones for long work, and answer progress requests at a
   safe work boundary without restarting the task. Return completed/current work, blockers and the
   next step, not raw history. Use only an available, authorized parent-reporting channel.
   Reuse material already fully read and still current in that Agent's available context; recover
   missing/changed parts as needed. Each Agent still reads its applicable standards independently.
   Honor explicit host/Skill reread requirements. Read selected Skills and required instructions
   completely, separately or in contiguous pages through EOF; avoid truncation from batching long
   documents, and recover every missing portion before relying on a partial read. 宿主可读完整
   Task Pack 文件时，可交接确切文件引用、SHA 和简短变化摘要，接收方必须完整读取当前
   包；宿主不可读时仍通过支持的通道发送完整包，不能仅发差量。No new report file is needed.
9. Read `orchestration` limits from `project.yaml`，并按当前宿主真实运行／打开线程口径观察
   容量；按需创建，不预热全部别名，不为填满上限启动实例，为必要 QA／集成安排容量。 One path has one writer. Run
   conflict detection before two or more writers. Do not allow nested delegation.
10. Materialize the approved graph into a transient JSON snapshot. Freeze the configured STANDARDS
    index/root, current index fingerprint, domain-specific applicable hard-rule IDs, and any explicitly
    documented protected-path boundary in `standards_contract`. Protected-path writes outside an
    allowed extension path require the matching `standards_exceptions` record and declared
    `exceptional:<id>` Gate with exact patch surface, rollback, and verification. For any `production_ui` or
    `design_ui` task, include typed `ui_contract.prototype_paths`; derive the design-standard
    boundary from `standards_contract.root/DESIGN_*.md`. Do not let a task self-declare its forbidden
    production boundary or allowed design-writer boundary. Reject every Writer in the graph that
    overlaps either boundary unless it is the `xy-uiux + design_ui` Writer, including
    roleless, broad-parent, direct-dependency, and transitive-dependency disguises. Invoke the deterministic
    scheduler before dispatch and after runtime changes. Set `workflow_graph` to the resolved
    snapshot path. After successful `task_graph_cli.py update`, reuse its validation and query `ready`
    directly when readiness changed. Use this guarded example only for a newly generated or otherwise
    edited snapshot that has no successful validation for its current bytes:

    ```bash
    # 上游快照生成失败时不要进入本段；校验失败时 && 会阻止依赖查询继续执行。
    bash .agent-workflow/lib/python_runtime.sh -X utf8 .agent-workflow/lib/task_graph_cli.py validate --input "${workflow_graph:?set the resolved task graph path}" &&
      bash .agent-workflow/lib/python_runtime.sh -X utf8 .agent-workflow/lib/task_graph_cli.py ready --input "${workflow_graph}"
    ```

    Query `qa-ready` separately at the existing request QA scheduling point. It does not replace
    necessary READY recomputation after state/gate/capacity/lock changes: a request may be QA-ready
    while evidence, read-only or another request's tasks have just become READY. Both queries may
    therefore be necessary; avoid only repeated identical queries without relevant changes. Apply the
    [execution boundary](#workflow-helper-execution) to any preceding snapshot helper as well.

    Never attach, paste, or summarize the raw snapshot field by field in a user message. Report a
    structural scheduler error only when it blocks progress and reduce it to the affected workstream
    and required resolution.

    The graph is the scheduling source of truth; it replaces global implementation waves.
    `depends_on`/`blocks`, named `gates`, `owned_paths`, and `semantic_locks` are validated
    deterministically. Capacity is the minimum remaining project writer/subagent quota and host
    availability; a `capacity_delay` is not a dependency. Dispatch all returned READY independent
    tasks, update the single task `state`, and re-run readiness after each completion.

    In invariant language: Build a DAG before dispatch. Dispatch all currently ready independent tasks.
    Re-evaluate downstream readiness after each completion. A
    capacity delay never becomes a semantic dependency. Failures block only downstream dependents;
    independent branches continue. QA is bounded to the current request dependency closure.
