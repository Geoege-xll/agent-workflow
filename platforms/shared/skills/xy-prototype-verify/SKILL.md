---
name: xy-prototype-verify
description: Use when a design Agent must statically validate concrete build-free HTML pages before user visual review, visual approval, or required-prototype production UI work.
---

<!-- agent-workflow-pack:managed-skill -->

# xy-prototype-verify

The active concrete page and its in-page `Page design and interaction contract` are the design
evidence. The verifier is read-only: it validates the stable workspace and returns deterministic
static evidence without creating metadata, reports, screenshots, or revision copies. The prototype
is a user-review artifact; this procedure is not a second visual reviewer or an automated UI test.

## Required checks

This procedure applies only to prototype-mode work. For `design_mode: standards_only`, return to
the PM's standard-maintenance task without running these checks, creating prototype files, or
requesting visual approval. A preloaded Skill is not a mandate to execute an inapplicable procedure.

1. Resolve `project.yaml` -> `docs.standards_root`, then derive its `prototype` child. The
   default active workspace is:

   ```text
   docs/standards/prototype/index.html
   docs/standards/prototype/prototype.css
   docs/standards/prototype/<stable-page>.html
   ```

2. Run the repository validator from the project root:

   ```bash
   bash .agent-workflow/lib/python_runtime.sh .agent-workflow/lib/validate_prototype_workspace.py \
     <project-root> docs/standards/prototype --json --page <stable-page>.html
   ```

   Substitute the configured project-relative `docs.standards_root` path when it differs. A nonzero
   exit is FAIL. Do not weaken or bypass its path, dependency, structure, contract, or interaction
   checks. Repeat `--page` for multiple scoped concrete pages; omitting it returns all concrete pages.
   Keep the returned per-page fingerprints as internal evidence, not a user-facing JSON report.
3. Verify every scoped active page contains exactly one non-empty
   `Page design and interaction contract` with these exact five sections:

   ```html
   <section data-contract-section="purpose">...</section>
   <section data-contract-section="navigation">...</section>
   <section data-contract-section="interactions">...</section>
   <section data-contract-section="states">...</section>
   <section data-contract-section="exceptions">...</section>
   ```

   Each material interactive control needs a stable `id`, exactly one matching
   `data-contract-for`, and executable declared outcomes.
4. Confirm every changed prototype path is under the configured
   `docs.standards_root/prototype`, except a separately task-authorized design-standard leaf
   update under `docs.standards_root/DESIGN_*.md`. Reject revision-suffixed, dated, `final`, `new`, or
   task-scoped page copies.
5. Confirm the workspace opens through `file://` with ordinary relative navigation and without a
   build, package installation, framework, router, external CDN, live API, database, account,
   credential, or real user data.
6. Use the same command's per-page dependency fingerprints, computed from the safe local transitive
   dependency closure defined by `product/WORKFLOW.md`. Do not reconstruct the algorithm in a separate
   script. To compare approved evidence, add `--expect <stable-page>.html=<approved-sha256>` for every
   scoped approved page. A mismatch exits nonzero and blocks use of the stale scoped approval.
   External, workspace-escaping, missing, dynamic, or unsupported dependencies are FAIL. Only the PM
   may carry non-material changes forward after the documented old/new-delta review and retained user
   approval; uncertain or material changes return to the existing scoped visual-confirmation step.
   The verifier never grants approval or decides visual equivalence.
7. Compare the five contract sections with the frozen approved requirements and acceptance criteria.
   Every declared navigation, interaction, state, validation, and exception must be traceable to
   those requirements; missing required behavior, invented behavior, or a conflicting outcome is
   FAIL. This is a semantic text review and does not require rendering the page.
8. Confirm that every concrete changed page can be handed to the user through its direct absolute
   HTML path, and that the handoff names the changed scope and declared operation sequence. Static
   validation proves file readiness; it does not claim that an Agent rendered or operated the page.
9. Record `baseline_ready`, `ia_ready`, `prototype_verified`, and `visual_review_ready` only as
   automatic workflow evidence. Only the PM may record `visual_approved`, and approval remains in
   workflow task state. PM preserves recoverable approval evidence in the existing saved plan when
   the task-level policy saves one; this verifier creates no plan or companion approval document.

## Prototype browser boundary

Prototype verification MUST NOT invoke Computer Use or browser automation by default. Do not open
or operate prototype pages through Computer Use, Playwright, `/browser`, a browser MCP, or an
equivalent UI-driving tool merely to reach `prototype_verified` or `visual_review_ready`.

Only either of these user-originated conditions permits the smallest scoped prototype-browser
operation:

1. the user explicitly requests automated operation or browser testing of the prototype; or
2. the user reports that the prototype cannot open or that a concrete interaction is broken, and
   browser operation is needed to diagnose that reported failure.

Prototype complexity, interaction count, material UI risk, host capability, PM preference, or
missing browser evidence does not create an exception. An allowed diagnostic operation is not a
default gate, does not replace user visual approval, and must not create persisted browser evidence.

## Verification ownership and PM review

The `xy-uiux` task owns the deterministic static prototype-verification coverage defined above and
returns current, internally consistent evidence. A host without browser capability is fully capable
of completing the default procedure; browser evidence is not required and the PM must not supplement
it merely because the host could not render or operate the prototype.

Before user handoff, the PM independently compares all five in-page contract sections with the frozen
approved requirements and acceptance criteria. The PM rejects omitted, invented, broadened, or
conflicting behavior and returns it to `xy-uiux`; it must not ask the user to approve a knowingly
divergent contract. The PM also reviews scope, contract completeness, static evidence freshness and
consistency, fingerprints, and the user-approval handoff. This is a text-and-requirements conformance
review, not browser testing. The PM does not repeat completed static verification. Missing, stale, or
contradictory evidence or a fingerprint mismatch triggers only the smallest affected static recheck;
it does not authorize Computer Use or create a second verification pass.

Integrated QA consumes this frozen handoff instead of activating this procedure again. QA may run
deterministic workspace validation and dependency-fingerprint recomputation, whose machine process
reads complete dependency bytes, but QA does not open or automate the prototype and does not preload
the complete prototype source tree. Missing or stale handoff evidence returns to the PM for
`xy-uiux` rework. This restriction applies to the prototype artifact, not to risk-based testing of
the real production implementation.

## User handoff boundary

The PM MUST provide a direct link to each concrete changed page.

The root prototype index alone is not sufficient.

The visual-confirmation workflow MUST NOT generate, persist, attach, or present screenshots.
Do not create image assets unless the user explicitly requests an image asset; an image never
substitutes for the interactive page.

Do not create companion design, mapping, QA, or baseline Markdown; a Manifest; a screenshot
directory; or any other companion metadata. Update stable pages in place.

## Report

Return only concise task evidence:

```yaml
prototype_verify:
  result: PASS | FAIL
  prototype_refs:
    - path: <docs.standards_root>/prototype/<stable-page>.html
      clickable_absolute_path: <absolute-html-path>
      localhost_url: null
      dependency_fingerprint: <verified-value>
      changed_scope: []
      declared_operation_sequence: []
  validator:
    command: <exact-command>
    exit_code: <integer>
  static_checks: []
  blocking_findings: []
  pending_business_gate: none | visual_approved
```

Use `localhost_url` only when one already exists as a convenience. The concrete HTML path remains
authoritative.
