# Requirements Markdown delivery and retained prototype navigation

Requirements and plans have one editable Markdown source under adapter-resolved `docs.plans`.
Formal Full review uses that current Markdown draft; PM may keep a pre-approval draft in the current
request scratch. After requirements approval and any applicable prototype choice, PM saves the approved
`.md` before first dispatch. `xy-plan` returns only a draft. Light saves only when actual recovery,
complexity or user requirements need it; persistence adds no Full plan, DAG, QA or approval stage.

Requirements/plan Markdown-to-HTML generation has been retired. Its Python module, renderer bundle,
licenses and helper entry have been removed from current source and packages. Current planning, review,
dispatch and QA use Markdown and must not require a same-name HTML file or current HTML hash. The
workflow needs no Node runtime for plan delivery. Prototype design, concrete HTML pages, prototype
verification, dependency fingerprints and user visual approval remain required wherever applicable.

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

## Explicit project adapter and retained material

Use the exact project adapter selected during project inspection and task initialization. Pass that same
project-relative path through the prototype validator's `--adapter` option and its API's `adapter` argument;
do not independently search or prefer `.awf/project.yaml`, `project.yaml` or the legacy central adapter.
Multiple adapters require an explicit selection. The configured `docs.plans` and `docs.standards_root` both
come from that selected adapter, including custom document roots. Plugin helpers retain the actual physical
plugin/project boundary; central tasks retain their original fixed runtime and central adapter.

Existing plan HTML, original Markdown, prototype HTML, design standards and project information remain
historical or active project material according to their existing role. Removing the generation chain does
not authorize deletion, renaming, regeneration or bulk conversion of those files. Historical HTML has no
current editing authority and grants no acceptance or approval. Its optional prototype navigation link
continues to require a safe actual file and concurrent-input verification through the shared
`lib/documents/safe_documents.py` primitives.
