# UI and design acceptance

Read this branch only for production UI or design-standard work. For `standards_only`, use the
design-standard checks below; do not activate production-page/prototype checks without that scope.

For `UI-Conformance`:

1. Require `surface_kind: production_ui`, `qa_scope: request`, `route: UI-Conformance`,
   `design_delta: none`, both UI/accessibility audit surfaces, and non-empty structured authority
   refs. Every ref must contain an allowed `kind`, stable `authority_id`, normalized `path`,
   non-empty `anchor`, 64-lowercase-hex `content_fingerprint`, and `resolution_state: resolved`.
   Verify that `prototype_contract` and `design_standard` kinds match the prototype and standards paths in
   both directions; a generic authority kind cannot disguise a path inside those boundaries.
   Reject any `ui_contract.prototype_paths` or `standards_contract.root/DESIGN_*.md` boundary in the
   implementation diff or production-task ownership; these typed paths must be adapter-resolved,
   not declared by the production task itself.
2. Confirm the authority is current, internally consistent, and sufficient to determine the exact
   intended production result without a new layout, hierarchy, copy, navigation, interaction,
   state, token, responsive, or accessibility decision.
3. Compare production behavior and appearance directly with the frozen authority, and verify the
   regression, accessibility, localization, responsiveness, and repository-native build/test
   evidence appropriate to the affected surface.
4. Fail if the task dispatched `xy-uiux`, mutated `docs.standards_root/DESIGN_*.md`, carried a
   visual gate, silently made a design choice, or cannot prove conformance. Return the finding to
   the PM so it can reclassify the request as `UI-Patch`, `UI-Page`, or `UI-Flow`; QA must not
   perform the reclassification or design work itself.

For every scoped design-change UI page with `prototype_policy: required`:

1. Require explicit `UI-Patch`, `UI-Page`, or `UI-Flow`, `design_delta: changed`,
   `prototype_policy: required`, a valid requirements-confirmation `prototype_decision` whose
   `selected_policy` is `required`, and the matching `xy-uiux` dependency. Run the deterministic
   workspace validator and recompute the page dependency fingerprint without activating the full
   `xy-prototype-verify` procedure. The machine reads the complete dependency bytes; the QA Agent
   must not preload or manually read the complete prototype dependency tree. Every resolved
   `prototype_contract` must map exactly to
   `visual_approved:<authority_id>@<content_fingerprint>`; a mismatch makes approval stale and is FAIL.
2. When the fingerprint matches, consume the designer's frozen verification evidence and read the
   exact in-page contract. Open only the smallest relevant source slice—such as a selector, inline
   handler, or dependency—needed to resolve a concrete production-mapping question. Do not read all
   shared CSS, JavaScript, pages, or unrelated dependencies by default.
3. Verify that the contract and designer evidence cover stable control IDs, matching
   `data-contract-for` mappings, navigation, dialogs, validation, cancel, disabled, loading, empty,
   error, and success outcomes. QA MUST NOT invoke Computer Use or browser automation against the
   prototype when that evidence is current and bound to the unchanged fingerprint.
4. Compare the approved contract and evidence with production behavior. Check structure, visual
   scope, interactions, states, responsiveness, accessibility, localization, keyboard/focus,
   security, privacy, tokens, and shared-component reuse.
5. Reject prototype-only mock data, fake APIs, demo timers, routing, debug/state controls,
   `data-prototype-*` metadata, or page-contract markup copied into production.
6. Missing, stale, contradictory, incomplete, or fingerprint-mismatched prototype evidence is not
   permission for QA to redo the complete design audit. Return FAIL to the PM for `xy-uiux` rework.
   Expand source reading only to the smallest risk-triggered slice, or when the user explicitly asks
   for a full prototype source audit.

For `prototype_policy: waived_by_user`:

An explicit production-only revision can replace an earlier required-prototype scope through the
plan lifecycle. Use the latest scoped user decision and replacement task/QA contract, not the plan's
first prototype policy. Separate this revision's diff from earlier authorized prototype edits without
hiding new unauthorized writes. Missing replacement evidence returns to PM; QA must not silently
waive a gate or request prototype synchronization merely to restore an obsolete contract.

1. Require `UI-Patch`, `UI-Page`, or `UI-Flow`, `design_delta: changed`,
   `prototype_decision.source: requirements_confirmation_user_choice`, a stable `user:` choice
   reference, a current approved-requirement SHA-256, a non-empty PM recommendation reason,
   `selected_policy: waived_by_user`, and decision surfaces exactly matching
   `ui_change.affected_surfaces`. The PM must not invent or default the record.
2. Require no prototype-design dependency, no prototype write, no `prototype_contract` authority, and no
   visual gate. Do not read or compare the unchanged prototype for the waived surfaces.
   A necessary `xy-uiux` task with `design_mode: standards_only` is allowed, but its full dependency
   closure must contain no prototype-mode work.
3. Audit the frozen requirements, applicable design-standard and production-baseline rules, real
   production implementation, functional states, responsiveness, localization, browser behavior,
   accessibility, regression risk, standards conformance, and build/test evidence.
4. Missing prototype work alone is not a finding. A scope expansion, stale requirement fingerprint,
   invented decision, production defect, accessibility failure, or standards violation is FAIL.
   Otherwise QA may return PASS, permitting controlled-document projection and PM commit assessment.

## Design-standard and artifact boundaries

For design-standard establishment, incremental changes or visual replacement, follow installed
`xy-workflow/references/design-standards.md`. Compare the authorized rule delta with its prior basis
and approved scope, not just newly edited rules. Verify replacement boundaries, preserved nonvisual
constraints, stable rule IDs, index links and current consumer fingerprints. Adopted rules are not
proof of completed migration. For `standards_only`, audit normative text and applicable constraints
without demanding HTML, prototype verification or browser evidence. With production changes, audit
against the adopted scope-specific rules; self-authored weakening cannot convert a defect into PASS.

Material divergence from an approved required-prototype page or frozen UI-Conformance authority is
FAIL. Only PM may dispatch rework, reopen the scoped visual gate or upgrade the design-change route.
Prototype review MUST NOT invoke Computer Use or browser automation. Only when risk-based testing of
the real production implementation requires browser inspection may QA view a rendered frame
ephemerally in memory. QA must not persist, save, write, attach, present or use that frame as approval evidence;
there is no screenshot artifact on disk.

The QA workflow MUST NOT generate, persist, attach, or present screenshots. It creates no companion
QA, baseline, mapping or design Markdown; no Manifest, visual-capture directory or other design metadata.
