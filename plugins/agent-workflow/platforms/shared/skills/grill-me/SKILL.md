---
name: grill-me
description: Check Full-request requirements for material gaps before planning; interview only when coverage is incomplete.
---

<!-- agent-workflow-pack:managed-skill -->

# Grill Me

Run after the PM has classified the request as Full and retrieved only any auxiliary project facts
materially needed for requirement coverage. Do not require document or agentmemory retrieval when
available information is already sufficient. Pressure-test the requirement brief without taking
ownership of planning or execution.

## Boundaries

- Use only facts and questions within the current request.
- Reuse facts already established by the user or repository; never ask the user to repeat them.
- Challenge material gaps, conflicts, irreversible decisions, and unverifiable acceptance claims.
- Stop as soon as the requirement brief is sufficient for planning.
- This Skill must not plan, edit PROJECT/feature truth, dispatch Agents, or approve requirements.
- Do not edit files, call another workflow, or create a second business-confirmation gate.

## Adaptive modes

Choose exactly one mode:

- `coverage_check`: use when goal, scope, non-goals, constraints, and acceptance evidence already
  appear complete. Confirm coverage and return immediately when no material gap remains.
- `full_interview`: use when any material fact is missing, ambiguous, or contradictory. Ask one
  compact batch at a time and follow up only on answers that leave a material decision unresolved.

## Procedure

1. Check the observable goal and affected users or surfaces.
2. Check in-scope work and explicit non-goals.
3. Check precedence among conflicting constraints and existing project contracts.
4. Check acceptance evidence, failure behavior, approval boundaries, rollback expectations, and
   irreversible or privileged actions.
5. Separate facts, user decisions, safe assumptions, and unresolved questions. Do not convert an
   unresolved material decision into an assumption.
6. Return `ready_for_planning` only when the PM can draft a plan without changing the intended
   product outcome or inventing authorization.

## Internal PM record

Build the following complete structure for planning coverage. It is PM working state, not a
user-facing response. The PM must not emit the raw `grill_result` YAML, its mode/readiness fields,
or empty internal lists to the user. When clarification is required, ask only the smallest natural-
language question that resolves the material gap. When coverage is complete, let the PM summarize
the goal, scope, non-goals, constraints, and acceptance evidence in the later approval brief.

```yaml
grill_result:
  mode: coverage_check | full_interview
  observable_goal: ""
  affected_users_or_surfaces: []
  in_scope: []
  non_goals: []
  constraints: []
  conflicting_constraints: []
  acceptance_evidence: []
  approval_boundaries: []
  rollback_expectations: []
  answered_questions: []
  assumptions: []
  unresolved_questions: []
  readiness: ready_for_planning | blocked
```

When blocked, state the smallest unanswered decision that prevents safe planning. When ready, return
control to the PM; do not continue into planning or implementation. Preserve the complete internal
record for `xy-plan`, but do not announce the schema or a `ready_for_planning` status token to the
user unless the user explicitly asks to inspect the internal record.
