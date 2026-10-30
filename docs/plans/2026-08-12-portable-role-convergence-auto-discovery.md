# Portable Role Convergence and Auto-Discovery Implementation Plan

> **Execution authority:** This pack's PM READY DAG and host-native Agents execute this plan. External
> planning, implementation, TDD, branch-finishing, and Subagent-orchestration Skills are disabled by
> default. Grill Me is only the conditional requirements interview; Superpowers contributes only the
> bounded `requesting-code-review/code-reviewer.md` QA fallback.

**Goal:** Preserve the current multi-agent workflow while replacing language-specific workers with seven agency-inspired canonical roles, including a complete Electron/Tauri desktop engineer, and automatically deriving project roles, workspace scopes, verification commands, and an initial observed engineering baseline.

**Architecture:** Introduce one strict, read-only repository discovery engine that produces an in-memory deterministic project profile consumed by validation and all three host renderers. Keep exact task `owned_paths` as write authorization, keep role and Skill sources canonical, remove retired role/configuration code instead of supporting it, and initialize `ENGINEERING.md` only when it has no user content.

**External Skills:** `grill-me` with its `grilling` primitive is conditional on Full, ambiguous, or
contradictory requirements. Clear bugs use the native bug-fix route. The PM dispatches one `xy-qa`
reviewer, which tries host-native review, one installed and capable Code Review Skill, then its
internal procedure; technical unavailability is the only fallback trigger. The bounded Superpowers
review prompt is one allowed external method, while high-risk swarms remain explicit escalations.

**Tech Stack:** Python 3 standard library, Bash, constrained project YAML, Markdown role sources, unittest, Claude Code/Codex/Antigravity renderers.

---

> The repository has no Git metadata. Execute the verification steps and record file scopes, but do
> not fabricate the commit steps described by the generic planning workflow.

### Task 1: Lock the clean-break contract with RED source tests

**Files:**
- Modify: `tests/test_unified_host_workflow.py`
- Modify: `tests/test_codex_workflow.py`
- Modify: `tests/test_claude_workflow.py`
- Modify: `tests/test_antigravity_workflow.py`

**Steps:**
1. Add a source-contract test requiring exactly `xy-web`, `xy-desktop`, `xy-backend`, `xy-apple`, `xy-android`, `xy-uiux`, and `xy-qa` in role metadata and canonical role files.
2. Assert `xy-python`, `xy-rust`, and `xy-java` source files, metadata entries, generated positive references, aliases, and routing rules do not exist.
3. Assert the portable template does not contain the retired required `sandboxes`, `enabled_roles`, or `commands` sections and contains `workspace.discovery: auto` plus optional overrides.
4. Run the new tests and confirm RED against the current partial six-role/manual-adapter implementation.

**Run:**

```bash
python3 -m unittest -v \
  tests.test_unified_host_workflow.PortableRoleDiscoveryContractTest
```

**Expected:** FAIL with old role roster and configuration-shape findings.

### Task 2: Define the strict discovery profile with RED fixtures

**Files:**
- Create: `tests/fixtures/discovery/` fixture builders inside the test module or minimal checked-in manifests
- Modify: `tests/test_unified_host_workflow.py`
- Create: `lib/project_discovery.py`

**Steps:**
1. Add table-driven repository fixtures for React, Vue, Angular, Svelte, Electron, Tauri, Python, Java, Kotlin Server, Go, Rust, PHP, C/C++, C#, Apple, and Android.
2. Add monorepo fixtures containing multiple Web roots, multiple backend language roots, and desktop modules beside independent browser or backend modules.
3. Define an immutable `ProjectProfile` result with normalized module roots, primary roles, evidence paths, detected stack facts, verification commands, enabled roles, and diagnostics.
4. Add negative fixtures for symlinked roots, traversal overrides, duplicate normalized roots, special files, malformed manifests, conflicting explicit overrides, and ignored vendor/build trees.
5. Confirm RED because discovery is not implemented.
6. Implement the smallest bounded, no-follow, deterministic scanner using the Python standard library.
7. Run the discovery tests and confirm GREEN.

**Run:**

```bash
python3 -m unittest -v \
  tests.test_unified_host_workflow.ProjectDiscoveryContractTest
```

**Expected after implementation:** PASS with stable sorted profile output and no fixture writes.

### Task 3: Implement deterministic module classification

**Files:**
- Modify: `lib/project_discovery.py`
- Modify: `tests/test_unified_host_workflow.py`

**Steps:**
1. Add RED tests distinguishing browser Web UI packages from Node backend packages.
2. Add RED tests requiring valid Electron application evidence and rejecting dependency-only false positives.
3. Add RED tests requiring valid Tauri configuration plus `src-tauri`/Cargo evidence and rejecting dependency-only false positives.
4. Add RED tests proving an Electron renderer/main/preload tree and a Tauri frontend/`src-tauri` tree each form one `xy-desktop` module rather than separate Web and backend modules.
5. Add RED tests distinguishing Apple app targets from server-side Swift packages and Android Gradle modules from Kotlin server modules.
6. Add RED tests for desktop modules beside independent Web/backend modules and for nested monorepo manifests.
7. Implement precedence and evidence rules without assigning arbitrary unknown directories: desktop classification wins over generic Web, Node backend, and Rust only inside the detected desktop root.
8. Treat clear backend/system modules without a more-specific desktop or platform classification as `xy-backend`.
9. Run focused tests and confirm GREEN.

### Task 4: Discover repository-native verification commands

**Files:**
- Modify: `lib/project_discovery.py`
- Modify: `tests/test_unified_host_workflow.py`

**Steps:**
1. Add RED cases for npm/pnpm/yarn/bun scripts, Electron Forge/Builder package scripts, Tauri CLI/Cargo commands, Maven and Gradle wrappers, Python managers, Cargo, Go, Composer/PHPUnit, .NET, CMake/CTest, Meson, Xcode, and Android Gradle.
2. Assert nonexistent scripts are never invented.
3. Assert checked-in wrappers win over global binaries.
4. Assert command output is scoped per module and stably ordered.
5. Implement command derivation from actual manifests, lockfiles, wrappers, and scripts.
6. Run focused tests and confirm GREEN.

### Task 5: Replace the role roster and metadata

**Files:**
- Create: `roles/xy-backend.md`
- Create: `roles/xy-desktop.md`
- Rewrite: `roles/xy-web.md`
- Rewrite: `roles/xy-apple.md`
- Rewrite: `roles/xy-android.md`
- Rewrite: `roles/xy-uiux.md`
- Rewrite: `roles/xy-qa.md`
- Delete: `roles/xy-python.md`
- Delete: `roles/xy-rust.md`
- Delete: `roles/xy-java.md`
- Modify: `product/ROLES.yaml`
- Modify: `product/AGENT_SCHEMA.md`
- Modify: `product/WORKFLOW.md` only where the canonical roster/routing is named
- Modify: `product/GLOBAL_CONSTRAINTS.md` only where the canonical roster/routing is named
- Modify: `tests/test_unified_host_workflow.py`

**Steps:**
1. Add RED structural tests for the approved twelve-section agency-inspired role body.
2. Add RED semantic tests for professional character, repository-driven behavior, direct deliverables, evidence, concise PM communication, strict memory, and project-derived success criteria.
3. Add RED negative tests for default microservices/cloud, invented SLOs, screenshot evidence, permissive memory, nested Agent delegation, and direct user reporting.
4. Write `xy-backend` as the language-neutral backend and systems implementer.
5. Write `xy-desktop` as the complete Electron/Tauri implementer covering renderer, privileged core, secure IPC/capabilities, native integration, packaging, signing/notarization configuration, updates, and repository-owned release logic.
6. Add desktop semantic tests for privileged-boundary validation, least privilege, remote-content isolation, repository-driven versions and release constraints, cross-platform evidence honesty, no invented performance or rollout targets, PM-only communication, strict memory, no screenshots, and no nested delegation.
7. Rewrite `xy-web` to use the actual repository Web stack instead of Vue/React-only locking and to exclude Electron/Tauri module renderers.
8. Rewrite the platform/design/QA roles into the same concise structure without changing their approved boundaries; QA includes desktop boundary and release-evidence review.
9. Replace role metadata with exactly the canonical seven roles and routing tags.
10. Delete the three retired role sources and all positive source references.
11. Run role/source tests and confirm GREEN.

### Task 6: Replace manual adapter validation with discovery validation

**Files:**
- Modify: `lib/validate_project_config.py`
- Delete: `lib/project_sandboxes.py` if it has no remaining safe helper responsibility
- Modify: `lib/common.sh`
- Modify: `scripts/guard.sh`
- Modify: `templates/project.yaml.example`
- Modify: `project.yaml`
- Modify: `tests/test_unified_host_workflow.py`

**Steps:**
1. Add RED tests requiring the new minimal configuration and rejecting retired manual sections as unsupported active configuration.
2. Add RED tests for optional safe include/exclude/role overrides.
3. Make project validation call the discovery engine before any write.
4. Remove scalar/list sandbox parsing and manual enabled-role/command extraction from active runtime code.
5. Render role-scope summaries from the in-memory discovered profile.
6. Update guard reporting to consume discovered scopes instead of parsing YAML role paths.
7. Run config, preflight-zero-write, and guard tests and confirm GREEN.

### Task 7: Generate Claude Code from the discovered profile

**Files:**
- Modify: `setup_claude.sh`
- Modify: `lib/validate_claude_artifacts.py`
- Modify: `tests/test_claude_workflow.py`

**Steps:**
1. Add RED fixtures asserting only discovered canonical roles are generated.
2. Add RED tests for `xy-desktop`, `xy-backend`, and repository-driven `xy-web` role bodies, scopes, detected stack context, and verification commands.
3. Add RED source tests proving no retired role identifier is parsed, rendered, migrated, or specially cleaned at runtime.
4. Remove retired role render/adoption/cleanup/compatibility logic.
5. Render Claude Agents from canonical sources plus the discovered profile.
6. Run setup twice and `--check`; confirm GREEN.

### Task 8: Generate Codex from the discovered profile

**Files:**
- Modify: `setup_codex.sh`
- Modify: `tests/test_codex_workflow.py`

**Steps:**
1. Add equivalent RED discovery, seven-role canonical-roster, desktop, clean-break source, ownership, and generated-content tests for Codex.
2. Remove retired role and manual sandbox/configuration branches.
3. Generate strict TOML Agents from canonical role sources plus the discovered profile.
4. Preserve current strict v1 ownership and atomic replacement behavior.
5. Run setup twice and `--check`; confirm GREEN.

### Task 9: Generate Antigravity from the discovered profile

**Files:**
- Modify: `setup_antigravity.sh`
- Modify: `lib/render_antigravity_agent.py`
- Modify: `lib/validate_antigravity_artifacts.py`
- Modify: `tests/test_antigravity_workflow.py`

**Steps:**
1. Add equivalent RED discovery, seven-role canonical-roster, desktop, clean-break source, ownership, and generated-content tests for Antigravity.
2. Remove retired roles and any manual scope/configuration assumptions without adding legacy migration paths.
3. Render the discovered module scopes and commands into native Agent bodies.
4. Preserve strict current-root ownership, shared Skill auditing, reset rollback, and user-content fail-fast behavior.
5. Run setup twice and `--check`; confirm GREEN.

### Task 10: Initialize an empty ENGINEERING contract from observed facts

**Files:**
- Modify: `scripts/scaffold_project_docs.sh`
- Modify: `lib/apply_antigravity_setup.py`
- Modify: `templates/docs/ENGINEERING.md`
- Modify: `tests/test_unified_host_workflow.py`
- Modify: `tests/test_antigravity_workflow.py`

**Steps:**
1. Add RED tests for missing, empty, untouched-template, and non-empty user-owned `ENGINEERING.md`.
2. Assert only the first three may receive a concise observational baseline and that non-empty user content remains byte-for-byte unchanged.
3. Add RED tests proving detected facts do not become upgrade targets and that Java 21 belongs only in an explicit required-constraints section.
4. Reuse the discovery profile to render the initial observed baseline without creating a Manifest.
5. Publish using the existing no-clobber atomic document path for each host, including Antigravity rollback.
6. Run focused race, hardlink, symlink, mode, and preservation tests; confirm GREEN.

### Task 11: Add stable read-only preflight discovery output

**Files:**
- Modify: `setup_all.sh`
- Modify: `setup_claude.sh`
- Modify: `setup_codex.sh`
- Modify: `setup_antigravity.sh`
- Modify: `lib/project_discovery.py`
- Modify: `tests/test_unified_host_workflow.py`

**Steps:**
1. Add RED tests for stable role/module/evidence/command preview output.
2. Wrap preflight/check in complete tree snapshots, including the embedded pack, and assert no byte, mode, type, inode, mtime, or bytecode changes.
3. Ensure preflight does not initialize project IDs or ENGINEERING.
4. Implement one renderer used by all entry points.
5. Run preflight from repository root and a different current working directory; confirm GREEN.

### Task 12: Delete retired tests, docs, and compatibility code

**Files:**
- Delete or rewrite all active tests whose only purpose is positive support for `xy-python`, `xy-rust`, `xy-java`, manual `sandboxes`, manual `enabled_roles`, or manual `commands`
- Modify: `README.md`
- Modify: active product/template documentation found by source scan
- Delete: superseded multi-sandbox design/implementation docs if no active test or authority requires them

**Steps:**
1. Run a source scan for retired role IDs and retired configuration names.
2. Classify every match as deletion, a negative assertion, or historical plan text scheduled for deletion.
3. Delete positive compatibility fixtures and tests instead of translating them.
4. Keep only strict negative assertions proving retired runtime support is absent.
5. Update the README quick start to copy pack, run preflight/setup, inspect the discovery summary, and avoid ordinary manual adapter editing.
6. Confirm the active runtime/source scan has no positive retired contract.

### Task 13: Verify workflow behavior has not changed

**Files:**
- Modify tests only if an old selector/name references a deleted role rather than current behavior

**Steps:**
1. Run dynamic DAG tests for parallel READY dispatch, downstream-only blocking, capacity delay, and request QA closure.
2. Run business-confirmation policy tests for non-UI requirements-only, UI requirements+visual, architecture clarification, and structured exceptional gates.
3. Run prototype validation tests for stable pages, five-section contracts, direct links, no screenshots, no Manifest, and no companion Markdown.
4. Run shared Skill and memory tests for exact five-source trees, strict project isolation, current-authority precedence, QA PASS before save, and docs fallback.
5. Run desktop QA tests for Electron IPC/preload or Tauri command/capability boundaries, native integration, package/sign/update evidence, and explicit per-platform unverified scope.
6. Confirm all suites are GREEN before real-project installation.

### Task 14: Fresh arbitrary-project integration matrix

**Files:**
- Test fixtures only

**Steps:**
1. Create temporary representative projects: pure Go API, React+Go monorepo, PHP service, C++ service/CLI, Java 21 contract over an older observed baseline, Swift Apple app, Android app, complete Electron app, complete Tauri app, Electron plus an independent React Web app, and a backend-only unknown-language manifest fixture.
2. Copy the pack into each project without editing role scopes, enabled roles, or commands.
3. Run `setup_all.sh --preflight`, setup twice, and `setup_all.sh --check`.
4. Assert the exact discovered seven-role subset for each fixture, single-primary-role ownership for each desktop module, and no retired generated Agents.
5. Assert project/user content preservation and no transaction artifacts.

### Task 15: Final source-pack verification and handoff

**Files:**
- No production changes unless a failing verification identifies a scoped defect

**Steps:**
1. Run Bash syntax checks and Python compilation with bytecode directed outside the repository.
2. Run Claude, Codex, Antigravity, unified workflow, prototype, shared-memory, business-confirmation, and task-graph suites.
3. Run setup twice plus aggregate and per-host checks in a clean fixture.
4. Scan for retired role/config compatibility code, stale generated outputs, cache files, broken links, and transaction artifacts.
5. Report exact test counts, commands, exit codes, remaining limitations, and the fact that no external project was synchronized during source-pack implementation.
