---
name: xy-code-standards
description: "When writing, refactoring or reviewing code read-only, combine built-in engineering rules, project-specific standards, actual callers and existing contracts to choose the smallest complete change or report evidence-backed findings; supports quality judgment without replacing project standards, task authorization or verification procedures."
---

<!-- agent-workflow-pack:managed-skill -->

# xy-code-standards

Use current user authorization, the existing Task Pack and applicable rules as the basis. The single source
of general engineering text is the [built-in engineering rules](references/rules.md); read applicable clauses
for the actual task. Projects add only approved specific standards, and read a project index only when it exists.
Fully bind current sources, rule IDs and fingerprints. This Skill adds no planning, dispatch, prototype,
approval, QA or record stage.

<!-- workflow-contract: references/rules.md -->

## Choose implementation from facts

- Follow actual call chains to establish the behavioral goal, entry points, data/state owners and consumers.
  Use nearby code, tests and executable configuration to distinguish facts, assumptions and gaps. Verify
  discoverable facts first; return unresolved tradeoffs affecting contracts, permissions or side effects to
  the original decision-maker. Do not automatically treat an observed old implementation as an upgrade target.
- Before reuse, check semantics, inputs/outputs, failure modes and dependency direction. Before extraction,
  identify the actual shared responsibility, variation point or isolation benefit. Similar syntax, fewer lines
  or anticipated future extension does not justify consolidation or added layers.
- Compare approaches by their changed behavior, preserved contracts and affected consumers; choose the smallest
  complete change that meets current requirements. Remove redundancy caused by this change and report other
  issues within the original task boundary. Explain non-obvious tradeoffs with comments required by applicable
  standards and update those comments with behavior.

## Read-only review and evidence

Read-only review does not write code. Findings include a concrete location, trigger, actual impact and supporting
evidence. Distinguish proven defects, evidence gaps and design preferences; naming, line counts or missing evidence
for a platform alone do not establish incorrect behavior. Implementation/review retain the existing verification
contract: reuse still-valid coverage and fill only real gaps. Do not expand static checks or test-double results
into claims about real consumers, other platforms or product quality. Implementation delivery still follows
the applicable `xy-build-verify` branch.

## Read by actual boundary

- When a change/review involves external input, mutable state, resource lifecycles or durable publication,
  read only relevant parts of [boundary reasoning](references/boundary-reasoning.md); do not load every
  specialist topic for an ordinary local change.
- Read [sources and adoption boundaries](references/sources.md) only when maintaining this Skill,
  checking attribution or tracing tradeoffs; do not preload it for ordinary implementation/review.
