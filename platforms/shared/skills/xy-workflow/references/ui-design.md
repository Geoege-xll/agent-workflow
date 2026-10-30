- `project.yaml` → `docs.standards_root/prototype/` is the stable prototype workspace.
  It keeps one in-page `Page design and interaction contract` per page and its page dependency
  fingerprint. Required-prototype QA lets the machine read complete bytes; the QA Agent reads only
  that contract and the smallest relevant source slice. A waived route skips old-prototype
  comparison but keeps production UI/accessibility QA.
- Classify `UI-Conformance` only when current approved requirements and controlled evidence fully
  determine the result. Record `route: UI-Conformance`, `design_delta: none`,
  `prototype_policy: not_applicable`, `prototype_decision: null`, structured resolved
  and fingerprinted `design_authority_refs`, affected surfaces, and the objective justification in
  the task pack.
  It does not dispatch `xy-uiux`, does not mutate a prototype, and does not require
  `visual_approved`; it remains Full and still requires Grill coverage, `xy-plan`,
  `requirements_approved`, `xy-build-verify`, and integrated QA.
- A `UI-Conformance` task must not edit `docs.standards_root/DESIGN_*.md`. Its production writer
  uses the frozen authority references and declares both UI and accessibility audit surfaces.
  Missing, stale, contradictory, incomplete, or choice-requiring evidence stops the affected write:
  reclassify the request as `UI-Patch`, `UI-Page`, or `UI-Flow`, update the plan, and reopen
  requirements approval when the material contract changes. A small diff, delivery pressure, or a
  request to skip design is not proof of a zero design delta.
- With `prototype_policy: required`, `UI-Patch`, `UI-Page`, and `UI-Flow` production tasks use
  `design_delta: changed`, depend on the matching `xy-uiux` task, and carry a resolved
  `prototype_contract`. Each prototype authority maps
  exactly to `visual_approved:<authority_id>@<content_fingerprint>`; a stale, generic, or unrelated
  visual Gate does not unlock production. The task also carries the selection record below; a PM
  default or existing prototype files cannot substitute for user choice.
- Both design-change branches carry `prototype_decision` with source
  `requirements_confirmation_user_choice`, a stable `user:` choice reference, the current
  requirement SHA-256, exactly matching affected surfaces, `recommended_policy`, a non-empty
  `recommendation_reason`, and `selected_policy` equal to `ui_change.prototype_policy`. The PM must
  not invent or default this record. When `selected_policy: waived_by_user`, the task has
  no prototype-design dependency, no prototype write, no `prototype_contract`, and no visual gate. It keeps
  `requirements_approved`, production ownership, build verification, standards conformance, and
  full ui and accessibility QA. QA PASS still permits document projection and PM commit assessment;
  absence of a newly updated prototype is not itself a finding.
- A waived task may depend on authorized `standards_only` maintenance, but not on prototype-mode
  work through any dependency chain. Required-prototype work cannot substitute a standards task
  for the matching prototype task. Standard adoption refreshes only affected task authority.
- For an explicit production-only revision during implementation/acceptance, follow WORKFLOW's
  `Production-only revisions after prototype approval` and the
  [plan lifecycle](plan-lifecycle.md). The user's unambiguous current instruction can
  resolve scope and prototype choice without a duplicate confirmation. Replace affected worker/QA
  inputs; do not reopen the old designer or synchronize prototype files. Keep unaffected authority,
  actual task-level verification, and the separate production-path owner. Merely approving a
  prototype for implementation is not a waiver; neither is a generic defect report.
- Required-prototype work in existing or second-development projects without an approved design baseline first runs
  an `xy-uiux` current-product audit. Record `baseline_ready`; do not ask for another
  business confirmation.
- The PM's baseline task pack must authorize the prototype directory derived from
  `project.yaml` → `docs.standards_root/prototype`, plus exact applicable leaves under
  `docs.standards_root/DESIGN_*.md`, and set
  `required_skills: [ui-ux-pro-max]`; otherwise the
  designer cannot establish or write back the baseline truth. When explicit activation
  is needed, use the host alias (Codex: `$ui-ux-pro-max`; Claude Code and Antigravity
  CLI: `/ui-ux-pro-max`).
- With `prototype_policy: required`, `UI-Patch`: targeted artifact or fragment, then `prototype_verified` and
  `visual_review_ready`.
- With `prototype_policy: required`, `UI-Page` and `UI-Flow`: automatic `ia_ready`, prototype work, then explicit
  `xy-prototype-verify`, `prototype_verified`, and `visual_review_ready`.
- The `xy-uiux` task owns deterministic static prototype-verification coverage. The PM reviews
  current scope, evidence freshness and consistency, fingerprints, and the approval handoff. Before
  user handoff, independently compare all five in-page contract sections with the frozen approved
  requirements and acceptance criteria; return missing, invented, broadened, or conflicting
  behavior to `xy-uiux`. This semantic review does not invoke a browser. The PM does not repeat
  deterministic checks already proven by current evidence.
- Prototype verification MUST NOT invoke Computer Use or browser automation by default. Only an
  explicit user request to automate the prototype, or diagnosis of a concrete prototype failure
  reported by the user, permits the smallest scoped browser operation. Complexity, risk, host
  capability, or PM preference does not make browser evidence mandatory.
- Request only the smallest affected static recheck when evidence is missing, stale,
  contradictory, or fingerprints mismatch. The PM does not supplement missing browser evidence,
  repeat completed static verification, or create a new confirmation gate.
- The active concrete page and its in-page `Page design and interaction contract` are the design evidence.
  The thin root index is navigation context only.
- For `UI-Patch`, `UI-Page`, or `UI-Flow` with `prototype_policy: required`, at `visual_review_ready`, ask once for
  `visual_approved` bound to the concrete changed pages,
  changed scope, declared operation sequence, and verified page dependency fingerprints. Reopen
  only the affected confirmation after a material change or when equivalence cannot be established.
  A fingerprint mismatch blocks use of stale evidence until the smallest recheck completes; it does
  not by itself require another user confirmation. Carry non-material changes forward only under
  WORKFLOW's scoped old/new-delta review, retained user approval and verified fingerprint rule.
- The PM MUST provide a direct link to each concrete changed page.
- The root prototype index alone is not sufficient.
- The visual-confirmation workflow MUST NOT generate, persist, attach, or present screenshots.
- Approval remains in workflow task state. Do not create companion design, mapping, or baseline
  Markdown; a Manifest; a screenshot directory; or a companion approval file.
  Preserve the approval source, scope and fingerprint in the existing plan when plan policy saves
  one. The same plan is a recovery aid, not an independent approval authority.
- Required-prototype production UI work cannot start before its approved concrete pages and
  fingerprints have `visual_approved` state. `UI-Conformance` and `waived_by_user` have no such
  gate; each starts only after `requirements_approved` with its respective frozen authority or
  prototype-decision record.
- For a new project, one platform owner builds and verifies the UI Foundation before
  feature-page writers run in parallel.
- Pending UI gates block production UI paths, not every unrelated workstream. Read-only
  diagnosis may proceed. A non-UI writer may proceed only after clarification, exact
  owned paths, a path and semantic conflict check, and confirmation that it has no
  semantic dependency on the pending UI decision; otherwise it waits.
- The `visual_approved` gate is a selective DAG edge: it blocks only tasks that declare a dependency on
  that gate. When the exact gate resolves, dependent tasks enter the ready queue
  immediately; unrelated branches continue.
- `contract_ready`, `plan_ready`, `BUILD_VERIFIED`, QA, and closeout projection are
  automatic evidence states. Platform security prompts remain mandatory for destructive,
  production, paid, external-mutation, or privileged operations and are outside the two
  default business confirmation stages.
