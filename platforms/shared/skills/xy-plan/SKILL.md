---
name: xy-plan
description: Draft a Full request implementation plan after Grill Me coverage and before requirements approval.
---

<!-- agent-workflow-pack:managed-skill -->

# xy-plan

Adapt the mature exactness and self-review ideas of Superpowers writing-plans to this pack's PM-owned
Task Pack and READY-DAG model.

```yaml
methodology_reference: superpowers-writing-plans
plan_owner: pm
plan_state: draft
```

## Boundaries

- Work only after `grill_result.readiness: ready_for_planning` for a Full request.
- Produce a draft for PM review; the draft is not approval or execution authorization.
- This Skill must not edit files, dispatch Agents, update PROJECT/feature truth, or request approval.
- Do not create worktrees, commits, implementation branches, nested Agents, or another workflow.
- Identify controlled-document candidates, but leave the post-QA projection decision to the PM.
- This draft Skill does not persist files. After requirements approval PM saves Full plans under
  adapter-resolved `docs.plans` before first dispatch, following
  `.agent-workflow/platforms/shared/skills/xy-workflow/references/plan-lifecycle.md`.

## Drafting procedure

1. Map the affected modules, exact owned paths, existing interfaces, repository verification
   commands, and controlled-document reads before drawing task boundaries.
   Resolve `docs.standards` and `docs.standards_root` once. For every Writer, fingerprint the compact
   STANDARDS index, select only applicable leaf documents, and map stable hard-rule IDs to all owned
   paths. Non-UI implementation selects engineering leaves; production UI selects engineering and
   design leaves; `xy-uiux + design_ui` selects design leaves. Never preload the complete standards
   tree. Extract a protected-path rule only when an engineering leaf states it explicitly.
   For standards maintenance, follow WORKFLOW's `Standards document granularity and maintenance`:
   locate the existing topic and actual rule delta before proposing a new leaf; do not attach
   automatic documentation cleanup or a new rule document to every implementation task.
2. For every production UI task, classify `UI-Conformance` only with `design_delta: none`,
   structured resolved and SHA-256-frozen `design_authority_refs`, no design-workspace write, and no
   unresolved design choice; record `prototype_policy: not_applicable`. Otherwise use the explicit
   `UI-Patch`, `UI-Page`, or `UI-Flow` route. For those routes, identify exact affected surfaces,
   recommend `required` or `waived_by_user` with one task-specific reason, and draft the consequences
   of both choices. Do not treat the recommendation as the user's selection and do not make either
   conditional branch dispatchable. After requirements confirmation, the PM materializes only the
   selected branch and adds the scope-bound `prototype_decision`. The `required` branch adds a
   matching `xy-uiux` dependency and page-fingerprint-bound visual Gate. The `waived_by_user` branch
   has no prototype-design dependency, prototype write, prototype authority, or visual gate. Both retain
   full production ui and accessibility QA.
   Independently identify initial, incremental, replacement, or unnecessary design-standard updates;
   a PROJECT/feature no-op does not decide this question. Use the existing `input_contracts` and
   `output_contracts` for scope, approval basis, replaced/retained rules, ownership and adoption order.
   Read `.agent-workflow/platforms/shared/skills/xy-workflow/references/design-standards.md` when relevant.
   A necessary `xy-uiux + design_ui` standards task uses `design_mode: standards_only`, exact standard
   Markdown leaves, and no visual gate/prototype procedure. Waived production may depend on it;
   required production still needs a genuine prototype task. Schedule shared-rule adoption and PM
   fingerprint refresh before affected consumers, preserving unrelated work and existing approvals.
3. Split tasks by independently testable deliverables. Keep setup, configuration, documentation,
   and tests with the deliverable that needs them; do not create administrative microtasks.
4. State exact consumes/produces interfaces so isolated workers do not invent neighboring names,
   types, schemas, or protocol behavior.
5. Add `depends_on`, `blocks`, business or safety `gates`, `semantic_locks`, and proposed parallel
   lanes. A shared contract, database schema, root configuration, or shared UI token is a semantic
   dependency even when file paths differ.
   For multiple independent functional units, propose worktree isolation and the adapter's confirm/auto
   delivery policy using `xy-workflow/references/worktree-delivery.md`. Include the common base,
   prerequisite handoffs, integration owner and cross-feature verification. PM resolves Git facts
   before execution; this draft Skill still creates no worktrees, commits or user confirmations.
6. For each task, provide concrete verification commands and expected output. Apply
   `xy-build-verify/references/verification-scope.md` from the installed Skill directory; discovered
   commands are candidates and selected checks must cover actual risk and mandatory rules. Reuse
   sufficient existing coverage first. Only when a concrete regression-coverage gap needs a test,
   prefer proving that regression before implementation in an existing suitable test file; otherwise
   name the strongest repository-native evidence. Do not require new tests or test files per task.
7. Include no placeholders such as TBD, generic "add validation", "handle edge cases", or "write
   tests". Name the behavior, boundary, command, and expected evidence.
8. Self-review requirement coverage, task independence, interface consistency, path/semantic
   conflicts, verification completeness, and missing failure cases. Fix gaps inline.

## Output projections

Before returning the Full draft, read [internal plan and task-graph contract](references/task-graph.md).
Return the complete internal record and a concise approval brief, keeping raw JSON/YAML hidden
unless requested. The PM, not this Skill, decides projection, resolves user choices, saves the
approved plan and dispatches.

<!-- workflow-contract: references/task-graph.md -->
