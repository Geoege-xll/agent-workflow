# Requirements Markdown and HTML delivery

The model and PM maintain one requirements Markdown source. HTML is an offline projection from the pinned
`answer-me-with-html` CLI. Formal files live under adapter-resolved `docs.plans` as same-name `.md` + `.html`.
The source's accepted version and `验收结果与当前已交付行为` section retain the current feature baseline;
PROJECT indexes only explicitly accepted topics. Design prototypes remain under configured
`docs.standards_root/prototype/`. Do not add requirements copies, mapping reports, template HTML, empty
folders or bulk conversions of historical plans.

Formal Full requirements review delivers HTML. `xy-plan` only returns a draft, without writing files,
dispatching or requesting approval. Before approval, PM may write the current draft to this request's scratch
and render it; only after approval does PM save formal Markdown and generate same-name HTML. Light selects
this by complexity, recovery need or user request. Rendering adds no Full plan, DAG, QA or confirmation stage.
Page existence, checked boxes, source copying and successful `check` do not create requirements/prototype-choice/
visual approval.

## Invoke the same adapter

Run from the project root in installed mode; for source-pack development, remove the `.agent-workflow/` prefix.
Prefer the target project's `.agent-workflow/project.yaml`; use that project's `project.yaml` when installed
configuration is absent.

```bash
bash .agent-workflow/lib/python_runtime.sh -X utf8 .agent-workflow/lib/requirement_html.py render --project . --source docs/plans/change.md --request-id current-request
bash .agent-workflow/lib/python_runtime.sh -X utf8 .agent-workflow/lib/requirement_html.py check --project . --source docs/plans/change.md
```

Replace `--source` with the actual `docs.plans` path; the sample default is not configuration. There is no arbitrary
`-o`: output is always same-directory, same-name `.html`. A formal source must be a single-link regular `.md` file
at a canonical relative path under plans. Reject symlinks, hard links, unsafe ancestors and path escape. Upstream
CLI never receives the original source; it may read/clean only the staging copy in scratch. Original bytes,
permissions and node identity remain unchanged.

On Windows, use the persistent in-project Python entry with the same arguments:

```powershell
node .agent-workflow/lib/python_runtime.cjs -X utf8 .agent-workflow/lib/requirement_html.py render --project . --source docs/plans/change.md --request-id current-request
```

Runtime requires existing Node.js >= 20 (the Windows installation route already has Node 22). Do not install global
dependencies or start the renderer on every setup. Missing/outdated Node blocks only the rendering needed now;
existing fresh pages and read-only checks do not start Node. The Brew Formula declares the Node dependency;
existing Python selection/explicit-interpreter rules still apply.

## Pre-approval draft

PM obtains the unique request scratch with existing `task_graph_cli.py scratch --root <project> --request-id <id>`,
writes the draft at an authorized location inside it, then runs:

```bash
bash .agent-workflow/lib/python_runtime.sh -X utf8 .agent-workflow/lib/requirement_html.py render --project . --source /absolute/current-request-scratch/change.md --request-id current-request --draft
bash .agent-workflow/lib/python_runtime.sh -X utf8 .agent-workflow/lib/requirement_html.py check --project . --source /absolute/current-request-scratch/change.md --request-id current-request --draft
```

Draft output stays in the same scratch; do not write formal plans early. Interpret project-relative draft links
against the future `docs.plans/<draft-filename>.md`. After approval, save the original bytes there so links remain
valid. The adapter relocates checked links only in the staging copy passed to CLI, enabling scratch HTML navigation
without writing back to the source. Do not bypass this basis with cross-volume absolute paths, raw HTML, reference
links or ambiguous paths containing whitespace/parentheses. Unsupported syntax is rejected with line locations.
Progress, link or presentation-only changes require only rerendering. Existing semantic-change rules determine
whether requirements approval reopens; HTML byte fingerprints cannot replace `requirements_fingerprint`.

## Prototype associations and controlled Markdown

Express requirements coverage using stable REQ IDs and ordinary links. The design Agent returns concrete prototype
pages and actual `id` state anchors in the existing handoff; PM writes them into the same source and rerenders.
For example, when plans and standards use default configuration:

```markdown
| Requirement | Acceptance | Prototype coverage |
|---|---|---|
| REQ-001 | Recoverable error state | [Editor error state](../standards/prototype/editor.html#error-state) |
```

Checks read only local Markdown/concrete prototype HTML and anchors actually linked from this source. Reject missing
files, project escape, linked nodes, directory indexes substituted for concrete pages and HTML outside the prototype
directory. Do not scan the whole prototype tree, relax prototype navigation outside its directory, or alter prototype
templates/fingerprints. Prototype dependency fingerprints, visual approval and production QA retain their responsibilities;
add no independent prototype QA. Implementers receive the complete current Markdown/applicable task pack, without
preloading all HTML.

Supported syntax includes ordinary paragraphs, headings, lists, tables, ordinary `[text](target)` links, inline code
and unindented triple-backtick code fences. Flows/sequences use upstream `flow` / `sequence` fence syntax. Code fences
may display common language text. Reject frontmatter, embedded images, `src=` imports, raw HTML/SVG and reference-style
links. External http(s)/mailto links navigate only, without embedding content. The fixed invocation uses only `render`,
disables auto-open/update checks and uses private AM_HOME. It does not start browsers, models, video or services, or
read files outside the project for embedding. Input safety uses a conservative subset: image markers and HTML-like
opening strings are rejected throughout the source, including escaped forms, multiline tags, inline code and fenced
examples. Explain such syntax with plain text or entities such as `&lt;`. Ordinary-link examples are checked as raw
project-path text too; backtick appearance does not bypass constraints.

## Freshness, failure and historical boundaries

HTML's version record binds canonical source path, source-byte SHA, pinned engine/adapter identity and generated-HTML
digest. `check` is read-only freshness/current-reference verification. It fails after source changes; `render` updates
the same path and directly reuses fresh output for identical inputs/renderer. Preserve and reject old HTML that was
hand-edited, lacks this tool's record or belongs to another source. Its owner must explicitly resolve it; do not
blindly overwrite it.

Rendering uses a fixed staging area in the current request-id scratch, then reuses existing conditional atomic
publication on success. Errors, timeouts or detected concurrent source/target edits preserve formal originals.
As with the existing publication entry, a cooperative directory lock does not promise to stop a non-cooperative
external editor between final check and replace, or guarantee power-loss transactional durability. Record execution
and accepted baseline separately in the same source. Canceling the current goal does not undo an old baseline;
completed does not create acceptance. Unindexed old execution drafts/derived HTML retain their historical boundary
and cannot become a second standard or automatic recovery-execution authority.

Generated-page primary branding and project GitHub links point to `https://github.com/Geoege-xll/agent-workflow`;
the footer still clearly identifies the pinned renderer source. Branding adaptation is part of renderer identity
and HTML integrity; do not change upstream bundles, licenses or source files.
