# UI and design acceptance

Read this branch only for production UI or design-standard work. For `standards_only`, use the
design-standard checks below; do not activate production-page/prototype checks without that scope.

先核对下列共享投影与权限约束，再对每个生产 Writer 阅读其路线、实际运行端证据和通用取证边界；设计规范变更另核对规范差异。

The request QA task remains read-only and may use `surface_kind: non_ui`; its audit surfaces still
include both UI and accessibility when production UI is in scope. Consume every entry in
`reviewed_ui_changes`, including each writer's route, affected surfaces, authority, ownership and gates.
For Full, the PM exports that projection from the current request graph. For Light selected for
independent QA, the PM supplies the corresponding projection from the current production Writer's
single-task pack. `surface_kind: production_ui`, `ui_change`, and the production gates describe the
reviewed Writer. Use `qa_scope: request` for Full. A Light Writer may omit `qa_scope`; if present it
must be `request`.

Before accepting production UI review, run the pinned task-graph helper's `verify-ui-scope --input
<current-qa-pack> --source <current-authoritative-source>`: the source is the Full request graph or
the Light production Writer pack, respectively. Use the actual current source and QA pack bytes, retain
the returned SHA-256 values, and independently establish their provenance and current scope from the
request and implementation evidence. A self-declared digest or this comparison alone cannot authenticate
a substituted or stale source. Missing source, an empty or altered projection, a mismatch, or inability
to establish current source provenance is FAIL. Plain `validate` checks structure only and cannot prove
that a projection is complete. This comparison is not required solely because a non-production review
mentions UI or accessibility.

Ordinary Light copy enters this review only when PM actually selects independent QA. Still verify
production_ui, zero design delta and real frozen UI-Conformance authority; do not disguise it as non_ui.
Reading this branch does not force Full planning, repeated confirmation or a prototype on Light. Return
any actual design/interaction change to PM for Full routing.

## UI-Conformance

1. Require the Writer projection's `surface_kind: production_ui`, `route: UI-Conformance`,
   `design_delta: none`, `prototype_policy: not_applicable`, non-empty structured authority refs,
   and both UI/accessibility audit surfaces on the QA task. Every ref must contain an allowed `kind`,
   stable `authority_id`, normalized `path`, non-empty `anchor`, 64-lowercase-hex
   `content_fingerprint`, and `resolution_state: resolved`.
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
   evidence appropriate to the affected runtime. If the current authority points to a frozen prototype
   anchor, read only that reference for conformance. The required-prototype checks run only when the
   current Writer's policy is `required`.
4. Fail if the task dispatched `xy-uiux`, mutated `docs.standards_root/DESIGN_*.md`, carried a
   visual gate, silently made a design choice, or cannot prove conformance. Return the finding to
   the PM so it can reclassify the request as `UI-Patch`, `UI-Page`, or `UI-Flow`; QA must not
   perform the reclassification or design work itself.

## prototype_policy: required

1. Require explicit `UI-Patch`, `UI-Page`, or `UI-Flow`, `design_delta: changed`,
   `prototype_policy: required`, a valid requirements-confirmation `prototype_decision` whose
   `selected_policy` is `required`, and the matching `xy-uiux` dependency. Run the deterministic
   workspace validator and recompute the page dependency fingerprint without activating the full
   `xy-prototype-verify` procedure. The machine reads the complete dependency bytes; the QA Agent
   must not preload or manually read the complete prototype dependency tree. Every resolved
   `prototype_contract` must map exactly to
   `visual_approved:<authority_id>@<content_fingerprint>`; a mismatch makes approval stale and is FAIL.
2. When the fingerprint matches, consume the designer's frozen verification evidence and read the
   exact in-page contract. Reuse the design Agent's existing handoff self-check evidence for requirements
   coverage, standards conformance and delivery consistency. This is functional QA after production
   implementation; do not dispatch separate prototype QA. Open only the smallest relevant source slice—such as a selector, inline
   handler, or dependency—needed to resolve a concrete production-mapping question. Do not read all
   shared CSS, JavaScript, pages, or unrelated dependencies by default.
3. Verify that the contract and designer evidence cover stable control IDs, matching
   `data-contract-for` mappings, navigation, dialogs, validation, cancel, disabled, loading, empty,
   error, and success outcomes. QA MUST NOT invoke Computer Use or browser automation against the
   prototype.
4. Compare the approved contract and evidence with production behavior. Check structure, visual
   scope, interactions, states, responsiveness, accessibility, localization, keyboard/focus,
   security, privacy, tokens, and shared-component reuse.
5. Reject prototype-only mock data, fake APIs, demo timers, routing, debug/state controls,
   `data-prototype-*` metadata, or page-contract markup copied into production.
6. Missing, stale, contradictory, incomplete, or fingerprint-mismatched prototype evidence is not
   permission for QA to redo the complete design audit. Return FAIL to the PM for `xy-uiux` rework.
   Expand source reading only to the smallest risk-triggered slice, or when the user explicitly asks
   for a full prototype source audit.

## prototype_policy: waived_by_user

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
3. Audit the frozen requirements, applicable design-standard and production-baseline rules, and real
   production implementation. Check functional states, responsiveness, localization, accessibility,
   regression risk, standards conformance, and build/test evidence for the actual runtime.
4. Missing prototype work alone is not a finding. A scope expansion, stale requirement fingerprint,
   invented decision, production defect, accessibility failure, or standards violation is FAIL.
   Otherwise QA may return PASS, permitting controlled-document projection and PM commit assessment.

## 实际运行端证据

根据当前生产 Writer 投影和项目实际运行端，复用仍有效的构建、测试与运行证据，核对受影响的
界面、交互状态和无障碍行为。iOS、iPadOS、macOS 和 Android 原生页面使用项目对应的设备、
模拟器或原生应用已有证据；微信小程序使用微信开发者工具、其模拟器或微信客户端的相应证据。
生产 Web 的实际浏览器缺口按[共用 Web 验证规则](../../xy-build-verify/references/web-browser-verification.md)
处理；混合界面只在实际受影响的宿主与网页边界分别核对。无法在当前只读权限下补齐必须证据时，
向 PM 报告具体缺口，由有权限的原 Writer 补证。

## Design-standard and artifact boundaries

For design-standard establishment, incremental changes or visual replacement, follow installed
`xy-workflow/references/design-standards.md`. Compare the authorized rule delta with its prior basis
and approved scope, not just newly edited rules. Verify replacement boundaries, preserved nonvisual
constraints, stable rule IDs, index links and current consumer fingerprints. Adopted rules are not
proof of completed migration. For `standards_only`, audit normative text and applicable constraints
without demanding HTML, prototype verification or browser evidence. With production changes, audit
against the adopted scope-specific rules; self-authored weakening cannot convert a defect into PASS.

## 通用取证边界

Material divergence from an approved required-prototype page or frozen UI-Conformance authority is
FAIL. Only PM may dispatch rework, reopen the scoped visual gate or upgrade the design-change route.
Prototype review MUST NOT invoke Computer Use or browser automation. Only when risk-based testing of
the real production implementation requires browser inspection may QA view a rendered frame
ephemerally in memory. QA must not persist, save, write, attach, present or use that frame as approval evidence;
there is no screenshot artifact on disk.

The QA workflow MUST NOT generate, persist, attach, or present screenshots. It creates no companion
QA, baseline, mapping or design Markdown; no Manifest, visual-capture directory or other design metadata.
