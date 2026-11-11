# Requirements Markdown delivery — HTML generation suspended

Requirements and plans have one editable Markdown source under adapter-resolved `docs.plans`.
Formal Full review uses that current Markdown draft; PM may keep a pre-approval draft in the current
request scratch. After requirements approval and any applicable prototype choice, PM saves the approved
`.md` before first dispatch. `xy-plan` returns only a draft. Light saves only when actual recovery,
complexity or user requirements need it; persistence adds no Full plan, DAG, QA or approval stage.

Requirements/plan HTML generation and freshness checks are suspended on every platform. Do not call
`requirement_html.py render` or `check`, its Python generation entry points, or the vendored CLI as a
workaround. Public adapter calls explicitly reject with `RequirementHtmlError` or CLI exit 2 before
reading project input, creating scratch or starting Node. There is no enable flag. Current planning,
review, dispatch and QA must not require a same-name HTML file or current HTML hash. Node is not needed
for this suspended feature.

## Current source and prototype coverage

Keep the accepted version and `验收结果与当前已交付行为` section in the same Markdown source;
PROJECT indexes only explicitly accepted baselines. Completed execution, document existence and checked
boxes create neither acceptance nor requirements/prototype-choice/visual approval. Pause or cancellation
of the current goal preserves the last accepted baseline. Follow the existing
[plan lifecycle](../../xy-workflow/references/plan-lifecycle.md) for recovery and in-place revisions.

Use stable REQ IDs and ordinary links for prototype coverage. The design Agent returns concrete pages
and actual state anchors in the existing handoff; PM writes them into the same Markdown. For default
paths, a link may be `[Editor error](../standards/prototype/editor.html#error-state)`. Check only actual
scoped references, without preloading the whole prototype tree or adding a mapping report/independent
prototype QA. Requirement fingerprints, prototype dependency fingerprints, visual approval and production
QA retain their separate responsibilities. Implementers receive complete current Markdown/task packs.

A requirements-bound prototype page declares the canonical Markdown in `body[data-prototype-plan-source]`
and has one Markdown link in its unique `nav.prototype-requirement-links`. An existing same-name historical
HTML link is optional. Both kinds require their safe actual file, `target="_blank"` and `rel` containing
`noopener`; they remain document navigation rather than render dependencies. Old HTML records, engine
identities and source hashes cannot block Markdown edits. An unlinked old HTML is not read. Preserve
canonical paths, project boundaries, safe single-link regular-file reads and concurrent-input rejection.
Do not bulk-edit historical prototypes merely to remove their retained HTML links.

## Retained implementation and recovery boundary

Keep existing HTML, the fixed `lib/vendor/answer-me-with-html` bundle, its provenance and all licenses.
They are historical/recovery material, not a second editing authority, current approval or automatic
execution permission. Do not regenerate, delete, rename or bulk-convert old documents for this pause.

`lib/documents/requirement_html.py` retains its original execution bodies as commented historical code
under `run_renderer`, `render_candidate`, `process` and `main`, with Chinese recovery instructions. Its
common safety/parsing/snapshot helpers remain available to current navigation consumers. Historical
renderer tests are retained as non-discovered reference classes; current required tests exercise the
pause, zero side effects, source/installed entry points and vendor preservation without reporting skips
as renderer success.

Restoration needs a new explicit authorization and coordinated changes to all four public entry points,
workflow/Skill/template rules, active tests and affected source/installed/native consumers. Restore the
former implementation only together with its source/path integrity, pinned runtime, isolated Node stage,
resource/cancellation, conditional-publication and race protections, then obtain real required verification.
No environment variable, direct private call or vendored command may silently restore generation.
