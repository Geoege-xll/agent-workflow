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

Codex discovery context deduplicates identical fact/command groups, while retaining each module's exact root,
command cwd and evidence-base mapping. Different arguments, purposes or evidence are not merged for superficial
similarity. To inspect a role's full mapping, run read-only `project_profile_cli.py context .agent-workflow . <role>`
with the Python entry below. It reuses the discoverer without executing candidate commands, writing state or
refreshing the host, and does not change the refresh conditions above.

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

### Central projects: use the current task pin on every call

This section is the execution boundary shared by all Skills/roles. A central project with
`.agent-workflow/runtime.json` must not directly execute `.agent-workflow/lib/<helper>.py` from the old
self-contained examples below, or select the current core through host-discovery symlinks. A new workflow,
including Light without an init step, first checks machine-local enablement:

```bash
bash .agent-workflow/lib/python_runtime.sh -B -X utf8 .agent-workflow/runtime.py check
```

Only after success, create a new graph/single pack with the returned strict three-field binding. `init`
itself also checks enabled through the bridge. Clones lacking machine records, disabled projects or resource
conflicts cannot start automatically; automatic installation must not bypass failure. New tasks adopt the
project version verified now; running tasks use only top-level `runtime_binding` from the current Task Pack.

For every independent tool/shell call, take the three-field JSON unchanged from the current pack and pass
it as explicit `--binding` to the project's thin entry. Replace the placeholder JSON below with actual
current-pack values; do not assume a variable from a previous shell exists. The bridge executes only that
pin's `lib/*.py` and freshly exports for this child process
`AGENT_WORKFLOW_RUNTIME_BINDING`、`AGENT_WORKFLOW_STATE_DIR`、
`AGENT_WORKFLOW_PROJECT_ROOT`, `AGENT_WORKFLOW_CONFIG_PATH` and
`AGENT_WORKFLOW_CORE_ROOT`. The last three are computed from the trusted machine binding; packs/projects
cannot self-declare an arbitrary core path.

```bash
bash .agent-workflow/lib/python_runtime.sh -B -X utf8 .agent-workflow/runtime.py \
  --binding '<complete three-field runtime_binding JSON from current Task Pack>' \
  helper lib/task_graph_cli.py validate --input '<current graph or single-pack path>'
bash .agent-workflow/lib/python_runtime.sh -B -X utf8 .agent-workflow/runtime.py \
  --binding '<complete three-field runtime_binding JSON from the same current Task Pack>' \
  helper lib/context_read.py .agent-workflow/product/WORKFLOW.md \
  --task-pack '<current single-pack path>' --limit 6000
```

Use the same substitution for `ready`, `qa-ready`, export, update, standards checks, QA handoff and other
helpers; ordinary business build/test commands retain the project's own environment. Obtain complete required
managed text such as Skills/roles through that pin's `read` or a pager with `--task-pack`; do not assemble old/new
text through a host Skill symlink whose version changed. Read project configuration from `.agent-workflow/project.yaml`,
not `core/project.yaml` or a path derived from `core.parent`.

Explicit `--binding` takes precedence over the environment at bridge invocation. After bridge selection,
the helper's pack pin must match the exported environment pin. Existing valid tasks may continue reading
old versions under this project's `used_bindings`; disabling prevents new tasks. Missing pins, cross-project
roots and unknown/corrupt versions fail immediately, without latest-version fallback. This defines only the
invocation contract; it does not prove host loading or Agent execution.

### Source pack and old self-contained installations

Source packs/old installations without a central marker/bridge context retain the Python entries below
and existing unpinned contract. Other old-path examples in this reference belong to this branch. Central
projects always replace them with pinned-core bridge calls under the preceding section.

- Reuse the existing [record tools](runtime-records.md) for common snapshot updates, Task Pack
  export and selected fingerprint checks. Prefer existing project verification commands for behavior.
  Do not create a one-off program or extra receipt for each routine PM metadata operation.
- For actual new resources, follow WORKFLOW's Task Packs contract: state purpose, location, owner, reuse
  entry point and retention/reclamation conditions in original `input_contracts`, `output_contracts` and
  `acceptance_evidence`. First reuse the owning project/service's configuration, environment, data and
  system caches; allocate this request's unique scratch only when temporary files are necessary. Without
  new resources, create no empty records or additional Full graph, plan or QA for Light.
- When a required Skill/instruction cannot fit completely in one reliable response, optionally use the
  [single-file pager](runtime-records.md#完整读取必需长文). Read one page per response, following each
  `next_offset` continuously with the same SHA until `eof`. Reserve host output budget for complete JSON;
  a character budget is not an exact token cap, so reduce page size when necessary. Each Agent still
  completes required reading independently; a fingerprint is not evidence of reading.
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

Before dispatch, judge current risk and actual consumers under WORKFLOW's Light／Full definitions. Both
levels default to the corresponding native implementer; only explicit authority for PM itself to implement
creates an exception. A document suffix cannot expand ownership. Both levels use original Validation,
input/output contracts and acceptance_evidence to explain real test gaps, re-execution grounds and failed-
rework progress under the three judgments in `xy-build-verify/references/verification-scope.md`, without
new fields, fixed tables or approvals. Concisely hand off verified, still-applicable project commands,
necessary prerequisites/environment limits and provenance to avoid repeated trial and error. Lessons do
not replace current evidence or justify passing full history.

### Light: self-contained single-task dispatch

Once the current goal, exact owned paths, acceptance, standards and minimum verification are clear, use
a `schema_version: 2` single pack whose `task` retains current `state`, with `workflow_level: Light`,
normalized `module` (root is `.`), `role`, stable `agent_alias`, `instance_policy: fresh` and
`context_policy: handoff_only`. Current goal/scope, code/workspace basis, applicable standards, trusted
authorization sources, acceptance/necessary evidence and unresolved items must be complete. Packs cannot
carry full PM/sibling conversations; new instances do not inherit parent history, and each recipient still
reads required standards completely. Actual native arguments follow only current-host details. Declaring
handoff_only does not prove runtime isolation was tested.

Ordinary Light UI copy still uses production_ui＋existing UI-Conformance, design_delta:none,
prototype_policy:not_applicable, current resolved/frozen design_authority_refs and engineering/design
coverage. Fill missing authority with real grounds first; actual design/interaction changes become Full.
Do not use non_ui or empty authority to evade standards.

Light does not force the Full Grill Me, xy-plan, graph, plan persistence, independent QA or repeated
confirmation below. Explicit user scope authority permits direct dispatch; material unresolved contracts
and platform permissions follow their original boundaries. Run minimum sufficient verification and assess
independent QA, documentation and memory at handoff. Complete selected mandatory items; create no empty
records without a need. Full cannot use this to downgrade. See [record tools](runtime-records.md) for pack
export, state and identity binding.

### Full: planning, approval and graph dispatch

The complete planning, graph and QA route below applies to Full. Shared standards selection and minimum
sufficient verification also apply to Light. Implementation ownership, aliases/instances and lifecycle
closure follow `.agent-workflow/product/WORKFLOW.md`'s `implementation-ownership` and `agent-instance-lifecycle`;
this reference creates no separate instance-state source.

1. `project.yaml` is the fixed workflow-adapter read for paths, limits, and routing configuration.
   Its `docs.*` values are discoverable indexes, not a static preload list.
   PM, Writer and QA select built-in sources by actual domain and follow project-index links when present
   to add applicable specific leaves. Project indexes/leaves are not mandatory installation copies;
   built-in sources remain the required rule baseline.
   Project documents (`PROJECT.md` and topic lifecycle plans) and agentmemory are
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
   Each production-code Writer's baseline is built-in xy-code-standards/references/rules.md. Production UI
   also selects applicable design rules from xy-ui-design/references/foundations-rules.md and
   components-rules.md; xy-uiux + design_ui selects only applicable design sources. Bind all three sources
   through actual source-pack paths or installed .agent-workflow/ prefixes, then add applicable project-specific
   leaves. Bind the real SHA when the project index exists. With no project leaves and a missing index,
   create no empty index: retain configured index_path/root and null index_fingerprint. Each source covers
   owned_paths and applicable IDs through existing fields in the complete current worker/QA pack. Missing,
   stale or insufficient coverage still blocks; do not preload the whole standards directory.
2. Classify production scope from the current request and available facts. If classification,
   requirement coverage, or planning materially depends on a missing project fact, apply the
   auxiliary-source policy above and retrieve only that fact before finalizing the classification:
   - Light: one clear, bounded-risk delivery surface, including ordinary low-risk copy; use the single-pack branch above.
   - Full: multiple roles, shared contracts/database/root configuration, or production UI beyond low-risk copy.
   Light saves a brief plan only for actual pause/recovery/handoff or explicit request. Full saves after
   approval and before first dispatch. Read [plan lifecycle](plan-lifecycle.md) when saving, revising or
   recovering; saving Light does not activate Full Skills.
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
   output. `xy-plan` does not edit files or dispatch Agents. PM follows
   [requirements HTML delivery](../../xy-plan/references/requirement-html.md) to render the single Markdown
   draft in this request's scratch for formal Full review, without writing formal plans before approval.
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
   edit `PROJECT.md` or a topic plan’s accepted baseline before explicit approval, and do not project the
   planned result into canonical documents until integrated QA returns PASS. After approval, freeze
   the requirement fingerprint, approved plan, selected decision, and proposed projection;
   implementation tasks consume that frozen contract directly. A material requirement,
   affected-surface, or plan-boundary change returns the plan to draft and reopens approval.
   The PM now saves the Full plan in adapter-resolved `docs.plans`, before any design/implementation
   dispatch, then renders its same-name HTML from the single Markdown. One independent requirement owns one plan; pending UI decisions remain explicit. Do not
   write accepted PROJECT/plans baselines just to save intended work. Merge subsequent effective changes into
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

   Each task carries workflow_level, module, role, agent_alias, instance_policy: fresh and
   context_policy: handoff_only. Native dispatch supplies only the current task shell and necessary standards,
   approval/UI authority, without full PM/sibling conversations or a parent-history fork. Independent tasks
   use new instances; only short rework of the same task may reuse one.

   Include a brief reporting/reading instruction in every worker and QA task pack: report completion
   and blockers to PM, give meaningful milestones for long work, and answer progress requests at a
   safe work boundary without restarting the task. Return completed/current work, blockers and the
   next step, not raw history. Use only an available, authorized parent-reporting channel.
   Reuse material already fully read and still current in that Agent's available context; recover
   missing/changed parts as needed. Each Agent still reads its applicable standards independently.
   Honor explicit host/Skill reread requirements. Read selected Skills and required instructions
   completely, separately or in contiguous pages through EOF; avoid truncation from batching long
   documents, and recover every missing portion before relying on a partial read. When the host can read
   complete Task Pack files, hand off the exact file reference, SHA and brief change summary; the recipient
   must read the complete current pack. Otherwise send the complete pack through a supported channel,
   not just deltas. No new report file is needed.
9. Read `orchestration` limits from `project.yaml` and observe capacity using the current host's actual
   running/open-thread accounting. Create on demand, without prewarming all aliases or launching instances
   merely to fill capacity. Reserve capacity for necessary QA/integration. One path has one writer. Run
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
