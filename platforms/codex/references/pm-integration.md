## Codex-only integration

- Light and Full implementation activate `$xy-workflow`; Light does not require Full planning or a DAG.
  Light requires minimum sufficient verification and assesses independent QA, documentation, and memory at handoff; Full retains established confirmation, planning, and independent QA.
- Standalone read-only audits use WORKFLOW's matching branch and stop at the scoped conclusion,
  without the implementation/QA closeout loop; actual implementation acceptance keeps its QA contract.
- `$xy-project-memory`: retrieve only needed cross-session/history facts; retain post-QA closeout.
- Load `.agents/skills/` progressively, using only Codex `$xy-*` aliases, never other hosts' slash commands.
- Custom agents: canonical `xy-*` IDs in `.codex/agents/`; settings in `.codex/config.toml` come from
  `project.yaml` → `orchestration`.
- Plan revision/recovery: `$xy-workflow`'s `references/plan-lifecycle.md`.
- For Full, the main-session PM dispatches independent READY tasks in parallel through Codex-native
  custom Agents and keeps nested delegation disabled.
  Light/Full defaults to the corresponding native role subagent; see `.agent-workflow/product/WORKFLOW.md#implementation-ownership` for the PM implementation exception and recovery boundaries, preserving the original level's gates.
- Superpowers planning, execution, TDD, branch-finishing, and Subagent orchestration remain
  disabled by default.
- Testing and delivery follow installed `xy-build-verify/references/verification-scope.md`: choose the minimum sufficient scope at dispatch and do not repeat valid accepted evidence as PM. Full suites or additional checks need concrete justification; production delivery still requires successful affected-target build/compile and runnable evidence. Preserve Full/necessary Light independent QA, mandatory verification, and worktree integration requirements; proceed to existing closeout when stop conditions are met.
- For Full implementation or Light work assessed as requiring independent QA, the PM dispatches exactly one `xy-qa` reviewer. That same reviewer tries Codex native review as
  `host-native-review`, then one `installed-code-review-skill` proven installed and capable, then
  `internal-xy-qa-procedure`, moving forward only on technical unavailability. The allowed
  Superpowers option is only its installed `requesting-code-review/code-reviewer.md` prompt; Grill
  Me remains requirements-only. Findings or `FAIL` never switch review method or reviewer.
- Role TOML references boundaries and project documents; do not duplicate their content.
- Project command Hooks provide bounded intake/recovery reminders, not approvals or QA results.
  Respect native project/Hook trust and disabled settings; never bypass trust to make setup pass.
  See `.agent-workflow/platforms/shared/HOOKS.md` only for Hook configuration or diagnostics.
- SessionStart recovery includes native `fork` and `compact` sources. After a fork, verify the actual
  workspace and still-valid task authority; copied conversation context does not authorize another
  writer or repeat completed work. Do not add a second PostCompact reminder for the same recovery.

## Native review method

Use an exposed `/review` capability or `codex review` only when the unique QA reviewer can invoke
it without nested Agent delegation. Merely having a CLI binary or an installed third-party review
Skill does not prove native method availability. Resolve the selected project's effective QA
model/effort and native override layers; preserve them through supported invocation options rather
than introducing review-specific defaults or silently using another CLI profile.

For a CLI whose current help confirms the options, read-only invocation has the form
`codex --sandbox read-only --ask-for-approval never review <scope-options>`.
This invocation must remain inside existing host/project permissions and trust; do not widen them
to make review launch. `--uncommitted` covers staged, unstaged and untracked changes; `--commit`
covers that commit's introduced change; `--base` compares against the selected base branch's
merge-base semantics. Select only an option whose actual diff equals the frozen request scope.
A base argument alone is not an arbitrary pinned base/head pair, and a clean worktree does not
remove already committed request changes. Do not assume optional scope flags combine with custom
instructions: use the installed version's supported syntax and reject scope mismatches.

Bind root/nested-repository base/head, complete changed paths and dirty-diff fingerprints before and
after review. Discard output if inputs changed, a nested repository was omitted or the native range
cannot represent the request. Preserve native findings as general review evidence; the same QA
verifies findings and adds only uncovered project-acceptance checks. Record actual capability,
effective invocation, scope and result references in the existing `review_method`. Help output is
capability discovery, never proof of a completed model review. If the current tool surface cannot
invoke native review safely, record the technical reason and continue the existing method order.

## Native Tool Short Path

Dispatch new 2.0 tasks through a schema_version: 2 single-task envelope containing only the current task, applicable standards_contract, and necessary approval/UI evidence, without copying complete PM or sibling conversations. Stable agent_alias binds project-relative module and canonical role; create new native instances/IDs on demand for independent tasks, without precreation or filling capacity. Tasks retain workflow_level, instance_policy: fresh, and context_policy: handoff_only. When the current tool is collaboration.spawn_agent, explicitly set `fork_turns: "none"`; other native entries must also prove independent initial context and receive only a self-contained current-task prompt. Report a blocker if unavailable rather than falling back to a parent-history fork. Current effective configuration still determines host permissions, model, and effort.

Continuous same-task implementation, recent short rework, and same-round Reviewer delta checks may reuse the original ID. After the feedback window, PM acceptance, necessary verification/QA, and safe results/logs, use the currently exposed authorized termination capability. If this session exposes only interrupt_agent, it stops current execution without clearing context or proving closure/thread-capacity release; without close/kill or when execution fails, record agent_retired and prohibit continuation, with native termination unconfirmed. Retirement releases no still-running task locks. Record stop, retirement, closure, and permanent history deletion separately; do not delete history without authority. Observe running and open-thread counts separately using actual host definitions; under pressure reclaim accepted instances with sufficient handoff first, retain executing instances, undelivered evidence, and necessary reviewers, and reserve capacity for later necessary QA/integration. resume/compact restores only original context, not prepareForReuse; create no Agent pool or second state machine.

Use doctor, native usage, and `continuation` paths in `xy-workflow/references/runtime-records.md` as needed; diagnostic documented/source_observed/runtime_unverified is not evidence of this session's execution. The PM obtains actual IDs from current native tools and records `agent_ref` through existing update. After querying with a live running/idle observation, reuse the same Agent only for continuous same-task work or short rework through currently exposed native follow-up/wait capabilities. Do not automatically recover cancelled, retired, invalid, unknown, or cross-host instances, or create a runner/Reviewer. Still hand off the complete Task Pack and scope. Report absent follow-up capabilities truthfully; a new user chat is not same-Agent continuation.

See `xy-qa-review/references/inputs.md` for structured QA output: when supported, use `codex exec --output-schema <schema-file>` in the same authorized invocation, obtain the final object with `--output-last-message <native-result.json>`, then run `qa_handoff_cli.py extract --host codex --input <native-result.json> --task-pack <current-qa-pack.json>`. `codex review` does not support this schema flag; do not change the original method order, model/effort, or permissions to obtain structured output. Deduplicate native usage by response, disclose sample scope and missing values truthfully, and infer no costs or savings rates.

Regenerate with `bash .agent-workflow/setup_codex.sh`; validate with
`bash .agent-workflow/setup_codex.sh --check`.
