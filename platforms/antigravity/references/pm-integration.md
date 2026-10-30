## Antigravity native PM delta

This entire managed section applies only in Antigravity; ignore other hosts' integration sections.

Standalone read-only audits follow WORKFLOW's matching branch and stop at the scoped conclusion,
without the implementation/QA closeout loop; actual implementation acceptance keeps its QA contract.

Use `/xy-workflow` for non-Trivial implementation; roles are `.agents/agents/xy-*.md`, Skills are
`.agents/skills/xy-*/SKILL.md`. Only the PM may use `invoke_subagent`; role Agents never delegate and
`max_depth` is `1`. Dispatch READY tasks: `inherit` stays `inherit`, `worktree` becomes `branch`
only when the actual runtime proves a distinct registered worktree root and the required base;
`share` is forbidden. A branch name alone is not filesystem isolation. For multi-feature selection,
integration and confirm/auto local main delivery, read `/xy-workflow`'s `references/worktree-delivery.md`.
If isolated tool binding is unavailable, report it and retain safe ownership-based scheduling;
never emulate isolation by concurrently switching branches in one directory or overwriting host settings.

Clear one-file non-UI corrections with no shared contract use WORKFLOW's `General Trivial early exit`:
applicable engineering rules, direct local verification, scoped commit assessment, then stop without
DAG, repeated approval, independent QA or automatic document/memory closeout. Reclassify material risk.

Classify Trivial UI copy before UI routes: explicit local wording only, unchanged business/behavior,
no sensitive or unresolved shared impact; follow `.agent-workflow/product/WORKFLOW.md` -> `Trivial UI copy`.
Edit directly with applicable standards and local checks. No repeated approval, Grill/plan/DAG,
prototype choice, independent QA or document/memory churn; assess scoped commit after verification,
without fake QA PASS. Stricter project rules and requested review still apply. The following
execution and post-QA stages govern non-Trivial work, not this early exit.

Full: classify → facts → Grill Me → `xy-plan` draft → projection decision →
`requirements_approved`; Grill Me remains requirements-only. For design-change UI, include the PM
recommendation and prototype choice in that confirmation; freeze truth until QA PASS.
Full work records the Grill Me coverage check and `plan_state: draft`; the pre-approval projection
decision remains a draft, while post-QA controlled-document projection happens only after QA PASS.
PM saves the approved Full plan in `docs.plans` before first design/implementation dispatch.
Trivial does not save by default; Light saves only for actual pause/recovery/handoff or user request.
For revisions/recovery follow `/xy-workflow`'s `references/plan-lifecycle.md`: one requirement, one
current plan; replace affected complete worker/QA inputs and reuse unaffected verified work.
Feature details include current architectural rationale, with no separate ADR category.
`UI-Conformance` uses `prototype_policy: not_applicable`, resolved/fingerprinted
`design_authority_refs`, `surface_kind: production_ui`, `qa_scope: request`, no `xy-uiux`, and no
visual gate. Changed routes require a scope-bound `prototype_decision` from
`requirements_confirmation_user_choice`: `required` adds `xy-uiux` and a dependency fingerprint
page Gate `visual_approved`; `waived_by_user` adds no prototype-design dependency, prototype write, or visual
gate. The PM must not default either choice; full UI/accessibility QA remains. Platform security
prompts remain separate.

For initial/revised standards or full visual replacement, read `/xy-workflow`'s
`references/design-standards.md`. PM assesses/adopts scope separately from feature documentation;
UI Agent writes authorized leaves. `design_mode: standards_only` may precede waived production,
without prototype files, verification or visual gates. PM refreshes affected authority before use.

Prototype verification MUST NOT invoke Computer Use or `/browser` by default. Use `/browser` only
when the user explicitly requests prototype automation or reports a concrete failure needing the
smallest diagnostic operation. Production QA may still use risk-based browser testing. No rendered
frame may be persisted or used as approval evidence.

Current controlled documents and explicit user approvals win over recalled memory. Without strict
isolation or provenance, call neither recall nor save. For non-Trivial implementation, at BUILD_VERIFIED dispatch exactly one
integrated, read-only `xy-qa`. Waived work skips old-prototype comparison.

The reviewer tries `host-native-review`, then one `installed-code-review-skill` proven installed and
capable, then `internal-xy-qa-procedure`, moving forward only on technical unavailability. The sole
Superpowers option is `requesting-code-review/code-reviewer.md`. Findings or `FAIL` never switch
review method or reviewer.

Final QA outcome: PASS | FAIL. Require `qa_handoff_cli.py validate`. Completion: QA PASS → projection
→ PM commit assessment → memory closeout via `/xy-project-memory` → final user report. Setup owns
marked artifacts and one signed, named assist Hook in `.agents/hooks.json`; other host settings,
MCP, plugins, permissions, Agent mode and Artifact review policy stay unchanged. The Hook reminds
once per conversation/workspace, not on every model invocation. It cannot identify user turns or
context recovery reliably and does not invent them. See `.agent-workflow/platforms/shared/HOOKS.md`
only for Hook setup or diagnostics.
