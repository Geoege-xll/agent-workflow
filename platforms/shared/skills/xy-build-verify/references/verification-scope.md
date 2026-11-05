# Verification scope and evidence reuse

PMs selecting verification, implementation Agents executing it, QA reviewing evidence and PMs closing out share
this policy. It governs only test scope, evidence reuse and stopping conditions; it does not change task levels,
business confirmation, independent QA, state machines or host permissions. Light uses the current self-contained
task pack and minimum sufficient verification. Referencing this policy does not force Full planning, a DAG or
independent QA. Full and actually required independent review/mandatory checks remain in force.

## Production delivery must build and run

- Every production-code implementer is responsible for successful build/compilation of the affected target,
  with real evidence matching delivered code. Narrower tests cannot omit this delivery baseline. Use existing
  incremental builds, the relevant module/target or a necessary application build; do not default to a clean
  build, every platform/configuration or release packaging.
- Compilation success does not prove the program runs. Use the minimum project-supported startup/smoke or
  key-entry check to verify the target runs in the declared environment. Libraries/shared modules use actual
  consumer compile/link and relevant execution evidence, without forcing a standalone launch. An existing
  command that genuinely covers both build and run need not be split into two executions.
- Do not invent compilation commands for interpreted projects. Use actual import/syntax and startup/key-entry
  checks. Lint, type checking, static reading or mock-only success cannot stand in for real build/runnable results.
- Before reusing build/run evidence, check that its target, actual source/artifacts, dependencies, configuration
  and relevant environment match current delivery, retaining original commands, logs and provenance. A changed
  branch name/commit ID alone neither invalidates evidence nor proves equivalent inputs. If applicability cannot
  be established, verify only the affected scope; do not simply rebind old success to the current version.
  Worktrees still require verification of the composed candidate, not single-branch results as integration proof.
- Report a blocker when necessary environment, permissions or dependencies are missing. Do not deliver a claim
  of successful compilation/runnability or mark `BUILD_VERIFIED` or QA PASS. Verify within authorization;
  do not deploy or change real business data without authority.
- By default, reuse the owning project/service's existing configuration, development database, runtime and
  system dependency/build caches (Maven, Gradle, npm, pnpm, Cargo, uv, DerivedData, etc.). Keep project data and
  configuration isolated. Migrate or incrementally synchronize retained data to the corresponding baseline as
  authorized; do not clean shared resources for this verification. For actual new resources, use original
  input/output contracts and `acceptance_evidence` to explain purpose, location, owner, reuse entry point and
  retention/reclamation conditions. When a temporary directory is genuinely necessary, use
  `task_graph_cli.py scratch --root <project-root> --request-id <request-id>` and reuse it in place throughout
  the task. Do not create isolated test databases, private package repositories or copied source/artifact
  directories per round (such as `-v2`, `-r1`, `replay`, `before`, `packages-qa*`).
- Verify pure documentation/static prototypes by delivery type, without inventing program-build requirements.
  Light distinguishes actual changes and verification inputs using the table below, still defaults to a native
  implementer, adds no Full plan/DAG/repeated confirmation, and assesses necessary independent QA at handoff.
  A change being only copy does not exempt necessary verification of an affected production target.

## Determine minimum sufficient verification first

- Repository-discovered commands are candidates. Keep explicitly required checks.
  Select checks from actual changed behavior, dependencies, acceptance and mandatory project rules. Inspect
  the real command expansion first so an aggregate command does not unintentionally run every module, platform,
  build variant or chained duplicate check. Commands listed by `ProjectProfile`, README or available scripts
  are candidates, not an automatic must-run list.
- Briefly state verification target → selected command/check → expected evidence in existing task Validation,
  retaining the basis for mandatory project checks. Use the current Task Pack; add no Full plan/approval for
  Light. Without changing acceptance or mandatory checks, use repository-supported file, case, package or module
  invocations; do not invent filters. A Writer must not silently remove task-required checks; return conflicts
  or gaps to PM.
- Locate needed coverage at actual test-node/subscenario level, then choose the smallest existing, supported
  entry point. If one file, command or test group contains normal, negative-control and failure branches,
  reuse branches already validly covered. Execute only the missing negative control, repaired failing branch
  or other explicit gap; shared grouping is not grounds to rerun the rest. Reassess invalidated conclusions
  when relevant inputs change; a matching case name alone is not enough for reuse. Prefer existing node/scenario
  selection. If genuinely indivisible, explain the necessary coverage run together and the specific reason it
  cannot be separated. Do not refactor unrelated test infrastructure or create a fixed test checklist to narrow
  one execution.

| Actual change | Default verification scope |
| --- | --- |
| Pure explanatory documentation or ordinary comments (not build/runtime inputs) | Diff and applicable link, format and syntax checks; no program build/start requirement. Workflow instructions and code-generation/compilation directives need verification by actual impact; suffixes or the label comment do not establish low risk |
| Copy/resources loaded only at runtime (not compiled/packaged) | Reuse still-valid build evidence; check keys/placeholders and verify updated resources through the project's real loading path or key entry. Old-resource execution or syntax checks alone do not replace this runtime evidence |
| Source code or copy/resources included in compilation/packaging | Successful affected-target build/compile and minimum generated-result startup/smoke or key-entry verification. Reuse valid evidence already obtained for the same inputs; a text-only change does not exempt it |
| One feature or local defect | Affected-target build/compile, minimum runnable verification, relevant behavioral/regression cases and necessary direct-caller/interface checks. Choose type checks/lint by project requirements and actual risk |
| Public component, shared utility or build configuration | Follow real dependencies to affected consumers; choose tests/integration checks covering their contracts, without automatically running the entire repository merely because the component is shared |
| Core architecture, cross-module migration or broad interface change | Identify impact boundaries/integration risks before selecting modules or full regression. Full task level alone does not mean full-suite testing |

Production delivery retains the build/compile and runnable evidence above. Select additional tests, lint,
type checks and installation smoke tests by actual need rather than requiring every category. Do not separately
rerun checks already covered by a combined command. Line counts, test counts and task names do not replace
risk/coverage judgment.

Local resource loading/runtime verification does not inherently require browser/simulator automation. Use it
only for concrete rendering risk, necessary runnable evidence unobtainable through smaller checks, or explicit
user/project requirements. Verify only the affected scope; do not expand to every page, flow or independent QA.

## Information gained from continued work

Explain judgments/evidence in the current Task Pack's original Validation, `input_contracts`/`output_contracts`
and `acceptance_evidence`. Update only information that actually changed; add no fields, fixed tables, reports
or approvals. Assess each contemplated action separately; every phase need not supply all three:

- Adding tests: which real behavior, boundary or regression protection lacks existing coverage, and how the new
  assertion distinguishes correct from incorrect implementation. A code change, absence of a new file or small
  case count does not establish a coverage gap.
- Re-execution: what coverage will be added, which specific unresolved risk addressed, or which evidence was
  invalidated by an actual source/artifact, dependency, configuration or relevant environment change. Recheck
  only affected conclusions; handoff roles, commit IDs or a final look alone do not justify execution.
- Continuing failed rework: which new diagnosis, testable hypothesis or effective repair progress exists, and
  what evidence the next step should produce. Evidence that rules out a hypothesis is diagnostic progress;
  repeating the same guess is not. Remaining attempt allowance alone does not justify repeating a failing path.

Run explicitly mandatory user/project CI, Hooks, builds and necessary integration verification under the original
contract; lack of added coverage does not cancel them. Reuse evidence sufficient for current acceptance directly.
These judgments do not change independent QA, permissions or completion conditions.

## Expansion or repetition needs specific grounds

Broaden or repeat only for changed inputs, failures, stale evidence, an uncovered requirement,
a concrete unresolved risk, or an explicit user/project requirement.

- Do not default to repository-wide test discovery, full suites or all-platform matrices. Choose full scope
  only for explicit user/applicable-project requirements or when actual impact and necessary coverage cannot
  be satisfied more narrowly. A sole entry point that cannot reasonably be split may be the minimum feasible
  verification; explain why and do not refactor unrelated infrastructure merely to narrow it.
  Allowing full scope does not require another user confirmation.
- Before expansion, state its trigger and added coverage in existing verification records: affected shared
  dependency, changed input/environment, failure clue, missing acceptance evidence, stale evidence or an explicit
  unresolved risk. Fill the nearest gap first. One failed test does not automatically require a whole-repository
  rerun. General reassurance or one last check is not a basis.
- After failure, identify a specific cause or testable hypothesis, then rerun the failing case and affected
  checks after repair. A suspected flaky failure needs a diagnostic purpose for retry and retention of the
  original failure. Do not repeatedly run until green and ignore an unexplained failure.
- Distinguish expected red defect reproduction from a negative control of a rejection contract. For the former,
  the old defect must trigger the predefined regression assertion; output locating the target defect is valid
  reproduction, without requiring the old implementation to reject input correctly. It is not repair success;
  the regression must become green after repair. For the latter, verify that the consumer rejects negative
  input as contracted; absence of expected rejection is failure. Fixture preparation failure, missing dependency/
  environment, executor failure or command error counts as neither reproduction nor rejection coverage. Retain
  original output while filling that branch and reuse other valid branches. One expected red does not invalidate
  a whole group, and unexplained execution failure must not be rewritten as success.
- If relevant inputs, known cause and evidence for the same failing path are unchanged, with no new diagnosis,
  testable hypothesis or effective repair progress, stop that repeated path early and return the specific blocker,
  attempts and original full evidence to PM. Continue independent branches. Do not restart the task, replace the
  Reviewer or mark the blocker passed. Long duration, the same command/error text or a changed commit ID alone
  does not establish lack of progress. Diagnostic investigation, the same command after a repair and mandatory
  checks remain permitted.
- Existing limits accumulate normally: return to PM after two failed implementer repair attempts; PM escalates
  to the user after three failed rework rounds. No progress may justify earlier return, but a new hypothesis,
  repair progress, changed command or resumed instance does not reset or stack limits.
- Preserve explicitly mandatory checks and necessary security/compatibility evidence; duration or reducing tests
  does not exempt them. Missing environment, no matched tests or an unexecutable command is not success. State
  actual alternative verification and remaining gaps. Missing/failing mandatory evidence prevents BUILD_VERIFIED
  or QA PASS.

## New tests and stopping conditions

- For new/changed behavior or defect repair, first inspect whether existing focused tests cover the current
  contract. Add tests only for a concrete behavior/regression gap or mandatory user/project requirement.
  Sufficient coverage needs no new case, and absence of a new test file alone is not QA FAIL. Briefly state a
  necessary gap in existing Validation; do not add a test-decision table, report or approval.
- Prefer extending existing test files and combining/parameterizing related scenarios. Create files only for
  independent test responsibility, unsuitable existing files or a real project convention. Do not create one per
  feature, rule or boundary type, or mechanically cap file count. New files, case counts and test-code lines are
  not completion criteria.
- Unit, component, integration and end-to-end verification each need a real risk/boundary to cover. Do not duplicate
  assertions just to fill layers when existing checks prove the same contract. Different failure modes at different
  layers may coexist. Reducing tests must not remove necessary security, isolation, billing, precision, concurrency,
  retry/recovery or compatibility protection.
- Assert observable behavior, boundaries or contracts; do not mechanically add tests matching only changed copy,
  comments, instruction wording, mock calls or implementation details. Copy/structure assertions relevant to a real
  contract may remain. Mock-only success does not replace necessary real-dependency, build and runtime evidence.
  Reversible low-risk changes with sufficient direct checks need no tests merely for delivery.
- Stop tests and enter existing handoff/closeout once selected mandatory checks actually pass, acceptance evidence
  is sufficient, no material unresolved risk remains and nothing later invalidates evidence. Do not run a new
  insurance regression at Writer completion, QA start, PM acceptance, before/after commit or before the final reply.
- After later code, dependency, configuration or relevant environment changes, recheck only affected conclusions.
  Another module's changes or ordinary documentation updates do not invalidate all evidence. A changed commit ID
  neither proves identical content nor automatically requires a rerun: compare actual inputs, environment and
  provenance, retain original evidence and update current scope bindings under the existing contract.
- Required CI, commit Hooks, builds and integration verification remain. Do not skip, disable or modify them to
  reduce execution count. Reuse successful CI/aggregate-command evidence when scope and environment match, rather
  than starting duplicate work only to obtain the same result.

## Independent QA review and PM delivery

- For selected-byte evidence generation/recheck, reuse existing `task_graph_cli.py fingerprints` from
  `xy-workflow/references/runtime-records.md`, selecting existing receipt fields directly instead of writing
  another temporary verifier or recomputing whole-repository fingerprints. It proves only selected-file matches.
  Check original commands, exit codes, actual build/runnable and QA evidence under this policy; tool success
  does not automatically grant a delivery state.
- QA independently inspects the actual diff/source, relevant standards, command scope, exit codes
  and resolvable logs. It may reuse implementer evidence only after confirming the reviewed inputs,
  dependencies and relevant environment still match. Independent review neither unconditionally reruns every
  test nor trusts only Writer self-report or an old QA PASS.
- When new execution is necessary, use the smallest authorized read-only checks. Return new tests/repairs to PM
  for implementer dispatch. Later related tasks invalidate only evidence affected by actual changes; do not redo
  all previously completed, still-valid verification.
- Worktree merges still require the existing contract's integration verification on the actual composed candidate,
  bound to its exact version. Single-branch tests cannot masquerade as integration evidence; integration also does
  not mean rerunning every branch test. After candidate changes, refresh affected verification, QA and delivery
  bindings under existing rules, without weakening `qa-ready` or merge conditions.
- PM checks that evidence matches current delivery at closeout, without adding another test phase after success.
  Document projection verifies only changed documents/links. If it unintentionally changes behavior or verification
  inputs, return to the corresponding existing repair/QA branch.
- Use existing delivery reports: briefly state verification scope, results and relevant unverified items/limits.
  Retain exact commands, exit codes, applicable inputs and resolvable full-log references internally, distinguishing
  new execution from reuse. Without a full-suite run, do not claim all tests passed. Do not list unrelated unrun
  items one by one or create a test-decision document/user-facing YAML/JSON.

## Verified lessons and adoption boundaries

Verified project commands, necessary prerequisites and environment limitations relevant to later tasks may be
updated under existing project-specific standards' ownership/maintenance contracts, or handed off concisely in
the current task pack to avoid repeated trial and error. Retain factual provenance and applicable inputs; recheck
when contrary evidence or relevant target, dependency, configuration/environment changes appear. Unverified
hypotheses remain leads. Lessons cannot replace current source, real execution evidence, approval or applicable
standards. Do not read old sessions, scan personal Skill inventories or create a lessons ledger for reuse, and
do not force start-mode memory retrieval.

The method draws on Microsoft's [TokenEconomizer](https://github.com/microsoft/TokenEconomizer) ideas for lesson
reuse and intervention in failure loops. Its [plugin design and limits](https://github.com/microsoft/TokenEconomizer/blob/main/docs/PLUGIN.md)
explain learning from self-terminated green turns with no verification failure after the last edit, distinct from
official experimental scoring. That signal cannot replace this pack's build/runnable evidence or independent
QA PASS. This policy adopts only those judgment methods: do not install the plugin, add a judge model, Hook,
supervisory Agent or background process, automatically prune tools/change permissions, claim native Antigravity
integration, or promise token, cost or pass-rate gains.
