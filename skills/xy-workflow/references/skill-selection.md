# On-demand Skill selection

This is the single shared Skill-selection policy for every Agent on Codex, Claude Code and
Antigravity: the PM, all implementation roles, `xy-uiux`, the single `xy-qa` reviewer, and consumers
of `xy-plan` or another workflow Skill. Apply it before selecting or using a Skill. It adds no
workflow stage, approval, role, delegation right or required inventory.

## Select from the actual task

1. Start with current explicit user instructions, the complete current Task Pack, actual repository
   stack, role responsibilities, applicable standards and the evidence gap to solve. Follow explicit
   higher-priority requirements and genuinely required Task Pack dependencies. Otherwise select a
   Skill only when it helps resolve the current technical risk or knowledge/evidence gap; reliable
   established project patterns or pure business-logic changes may need no supplemental Skill.
2. Narrow candidates using names and descriptions already exposed by the host. Built-in role
   recommendations are candidates, not mandatory selection or a closed whitelist. User-level,
   project-level and other-plugin Skills actually available in the current host may also be selected
   when they serve the authorized task.
   Do not enumerate personal Skill directories, scan every installed package, or preload every Skill.
3. Before application, completely read the selected `SKILL.md` and the relevant references it requires,
   using its own resource mechanism and complete-reading contract. A catalog description or a name
   alone is not the Skill body. Once selected, follow its applicable instructions; mandatory wording
   inside an unselected vendor Skill does not itself require selecting that Skill. Reuse unchanged
   text already fully available in the same instance under WORKFLOW's complete-reading policy;
   restore missing or changed required content.
4. Resolve the actual source before invoking it. Selected packaged recommendations use this verified
   plugin's qualified adapter or physical resource, its fixed canonical source and lock. A host-exposed
   same-named user/project/other-plugin Skill is a distinct source; never silently substitute it,
   mix its references/runtime with the packaged source, or call an unknown global name/latest release.
   Return unresolved same-name ambiguity or conflicting instructions to the PM.

## Required and supplemental Skills

`task.required_skills` contains only Skills genuinely indispensable to completing the current task,
not an inventory or an automatic copy of packaged recommendations. Invoke every required entry for
its applicable phase; unavailable or unresolved required Skills block that phase and must be reported
to the PM. A role's static resource binding alone does
not prove that its adapter/canonical text was read or that a command ran.

Within current responsibilities, each Agent may choose additional relevant Skills without asking
the PM to enumerate or approve an installed inventory. An unavailable optional Skill alone does not
block the base workflow: report the actual limitation and any uncovered required evidence. If an
explicit higher-priority requirement, required selected-Skill instruction or actual acceptance cannot
be met, return that specific blocker rather than treating the Skill as optional. Do not silently install, update or globally
configure Skills, tools or runtimes to fill a gap. Any such operation retains its existing user
authorization, host permission and dependency requirements.

## Recommended Web and Apple candidates

- For HTML/CSS/client-side JavaScript implementation or review with relevant Web API, compatibility
  or implementation uncertainty, consider `xy-web-guidance` to resolve that gap. The presence of Web
  files alone does not require loading it or querying guidance; established reliable project solutions
  and pure business-logic changes may proceed without it. When selected, follow its complete canonical
  read and fixed-runtime query instructions. Respect the repository's actual browser
  support policy and provide compatible fallbacks when required; guidance does not change approved
  UI authority or authorize dependency/browser-target upgrades. Backend, infrastructure and pure
  renames do not trigger an unconditional Web query. `xy-desktop` or `xy-uiux` may load it for an
  actual Web surface while retaining their original owner and prototype boundaries. `xy-taste`
  remains the design specialist, and production browser evidence follows the existing project-test
  and `xy-playwright` policy.
- For SwiftUI work with an actual platform/API, state, layout or compatibility knowledge gap,
  consider `xy-apple-guidance`; SwiftUI files alone do not require loading it. Established reliable
  project solutions and pure business-logic changes may proceed without it. When selected, first
  resolve the local Apple-official SwiftUI Specialist.
  Use What's New guidance only for relevant new-API or migration work. Check and read the actual
  local source through the adapter's read-only resolver; missing local resources are reported, not
  replaced by automatically installed third-party mirrors. Relevant host-exposed concurrency,
  SwiftData or performance Skills may supplement it on demand. Do not impose Swift 6.2, replace
  UIKit with SwiftUI, change architecture or raise the minimum OS without current task authority.

After selecting the relevant entry, use the verified physical plugin root and its existing Python
selector for each independent call; these are conditional examples, not an every-task checklist:

```text
bash <plugin-root>/lib/python_runtime.sh -B -X utf8 <plugin-root>/plugins/source_pack.py selected-skills read modern-web-guidance
bash <plugin-root>/lib/python_runtime.sh -B -X utf8 <plugin-root>/plugins/source_pack.py xy-web-guidance -- search '<task-specific query>'
bash <plugin-root>/lib/python_runtime.sh -B -X utf8 <plugin-root>/plugins/source_pack.py xy-web-guidance -- retrieve '<selected ids>'
bash <plugin-root>/lib/python_runtime.sh -B -X utf8 <plugin-root>/plugins/source_pack.py xy-web-guidance -- list
bash <plugin-root>/lib/python_runtime.sh -B -X utf8 <plugin-root>/plugins/source_pack.py apple-skills check
bash <plugin-root>/lib/python_runtime.sh -B -X utf8 <plugin-root>/plugins/source_pack.py apple-skills read --skill swiftui-specialist --resource SKILL.md --expect-source-sha256 <source_sha256-from-check> --offset 0 --length 16000
```

The modern Web `search`, `retrieve` and `list` use the fixed packaged runtime/data offline and require
an existing Node 22+; do not run upstream npm/npx installation instructions or enable telemetry/log
files. The adapter's `doctor` only diagnoses readiness. Read the chosen guides, not every guide.
Apple `check` reports actual local source/version/build and resource fingerprints; follow `read`'s
offset/length continuation to read the complete selected Skill and required references, preserving
`--expect-source-sha256` from that check. Use `swiftui-whats-new-27` only when its subject applies.
If an explicit local developer directory is needed, use the same `--developer-dir <absolute-path>`
for check and read; do not change system Xcode selection or launch/export Xcode to manufacture resources.
Changed source fingerprints require a fresh check rather than combining bytes from different sources.

## Authority and evidence stay with their existing owners

Skills provide methods and evidence within existing authorization. They do not expand exact
`owned_paths`, roles, network/tool permissions, native dispatch authority or read-only QA scope;
do not propagate upstream hooks or allowed-tools as new permissions. Preserve the existing
requirements/visual two-step policy, applicable prototype choice, fresh/handoff_only instances,
and the single independent QA reviewer. External workflows never replace or wrap this control plane.
Loading Web guidance does not authorize prototype browser automation or screenshots; Apple official
guidance does not replace destination-specific build/test, signing or release evidence.

In the existing handoff, state the actual Skill source (qualified name or physical path and known
version/fingerprint), purpose/scope and any relevant conflict or limitation. Distinguish complete
Skill reading, successful actual CLI/query execution and observed host-model adoption: none proves
the next. Report commands, exit codes and resolvable full logs only for work actually executed;
do not create a second Skill registry, approval record, evidence stage or QA process.
