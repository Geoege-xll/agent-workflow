# Portable Role Convergence and Auto-Discovery Design

## Goal

Make `agent_workflow` portable to an arbitrary repository without requiring users to hand-maintain
role directories, enabled-role lists, or ordinary verification commands. Preserve the current PM
orchestration, dynamic parallel DAG, exact task ownership, two-stage business-confirmation policy,
request-scoped read-only QA, lightweight HTML prototype contract, and strict project-isolated
agentmemory closeout.

This is a clean contract upgrade. Retired language-specific roles and configuration modes are
deleted rather than parsed, converted, invoked, or preserved through compatibility branches.

## Design Influences

Role bodies follow the useful parts of the `agency-agents` model: a professional identity, core
mission, repository-driven expertise, critical rules, explicit deliverables, an executable workflow,
communication style, and success criteria. The pack does not copy its large persona library,
marketing voice, fixed performance numbers, screenshot evidence, seven-phase gates, or permissive
memory model.

The canonical role body remains concise and written in English. Shared orchestration, memory, QA,
and prototype rules remain in the existing progressively loaded core Skills instead of being copied
into every role.

## External Skill Boundary

The pack remains the only orchestration authority. The PM uses the READY DAG and host-native Agent
dispatch directly; no external planning, execution, TDD, branch-finishing, or Subagent-orchestration
Skill wraps the workflow. Grill Me is the lightweight user-facing requirements interview and
`grilling` is its runtime primitive. It is invoked only for Full, ambiguous, or contradictory work;
clear work and clear reproducible bugs do not pay its interview cost.

Request QA uses exactly one `xy-qa` reviewer. That same reviewer tries host-native review first, one
installed and capable Code Review Skill second, and its internal procedure last. Technical
unavailability is the only fallback trigger; findings and `FAIL` route rework without switching
method or reviewer. The installed Superpowers `requesting-code-review/code-reviewer.md` prompt is one
allowed external method, not another workflow. A read-only multi-review swarm or simplify review
requires explicit high-risk or user-requested escalation and never enters the ordinary fallback
chain.

## Preserved Workflow Contracts

The following contracts do not change:

- The main host session is the PM and is not an ordinary Subagent.
- The PM creates the smallest task DAG for the current request.
- Every semantically ready task whose write paths do not conflict may run in parallel within the
  configured capacity limits.
- `depends_on` represents semantic prerequisites only. Capacity delays never become dependencies.
- A failed task blocks only downstream dependents; unrelated branches continue.
- Every writer receives exact task-scoped `owned_paths`; discovered role scopes are routing context,
  not write authorization.
- Every implementation handoff contains real build, compile, typecheck, or test evidence.
- Unified `xy-qa` audits the current request dependency closure read-only and returns only `PASS` or
  `FAIL`.
- Default business confirmation remains `requirements_approved`; UI work additionally requires
  `visual_approved`. Architecture clarification does not create `architecture_approved`.
- QA PASS precedes strict agentmemory closeout, and memory closeout precedes the final user report.
- Current controlled documents, current code, task-pack facts, and current evidence override memory.

## Canonical Role Roster

The generated worker roster contains exactly seven roles:

| Role | Delivery surface |
|---|---|
| `xy-web` | Repository-driven browser Web and Web UI implementation outside desktop application modules |
| `xy-desktop` | Complete Electron and Tauri desktop application implementation, native integration, packaging, and release engineering |
| `xy-backend` | General backend and systems implementation across repository languages and toolchains |
| `xy-apple` | Apple-native iOS, iPadOS, macOS, and visionOS implementation |
| `xy-android` | Android-native implementation |
| `xy-uiux` | Stable, build-free, framework-neutral interactive HTML prototypes |
| `xy-qa` | Project-wide read-only request QA |

The source roles `xy-python`, `xy-rust`, and `xy-java` are deleted. Their metadata, routing aliases,
generated-host logic, adapters, fixtures, tests, and positive documentation references are deleted.
There is no runtime compatibility map from those IDs to `xy-backend`.

The runtime does not enumerate, parse, migrate, validate, or specially clean those retired IDs.
Fresh setup owns only the discovered canonical roster. General current-inventory ownership checks may
remove a strictly proven stale artifact without knowing any retired name; every unproven extra remains
user-owned. Operators upgrading a historical installation remove its old host files before installing
this clean-break pack.

## Agency-Inspired Role Schema

Every canonical `roles/xy-*.md` uses this body structure:

1. `Identity and Professional Character`
2. `Core Mission`
3. `Repository-Driven Expertise`
4. `Critical Operating Rules`
5. `Task Intake Contract`
6. `Execution Workflow`
7. `Technical Deliverables`
8. `Verification and Evidence`
9. `Communication Style`
10. `Memory Contract`
11. `Success Criteria`
12. `Routing`

Professional character is concise and operational rather than theatrical. Role bodies do not embed
large code examples, invented service-level targets, default microservices, default cloud systems,
or duplicated shared workflow text. Machine metadata remains in `product/ROLES.yaml`; role bodies
remain the canonical human-readable role behavior.

## `xy-backend`

`xy-backend` is a direct implementation role, not an architecture-only adviser. It covers backend,
service, worker, gateway, CLI, data, database, migration, native module, and general non-frontend
code across Python, Java, Kotlin Server, Go, Rust, PHP, C, C++, C#, Ruby, Elixir, Node.js backend,
Swift Server, and repository technologies not named in advance.

It must inspect and preserve the repository's real runtime, language version, framework, package
manager, build system, concurrency model, persistence layer, migration mechanism, module boundaries,
and public contracts. It selects the smallest coherent architecture that satisfies approved
requirements and must not introduce a second stack or migrate a foundational technology unless the
task explicitly authorizes it.

## `xy-web`

`xy-web` becomes repository-driven rather than Vue-or-React locked. It supports the Web framework,
package manager, router, state model, component system, and build tool already present, including
React, Vue, Angular, Svelte, Solid, Astro, Next.js, Nuxt, Remix, Web Components, or a plain
HTML/CSS/JavaScript application.

It must not introduce a parallel UI framework or silently migrate the application. Approved UI
work continues to use concrete prototype pages and dependency fingerprints, reuse production
components and tokens first, and reject prototype-only mock/runtime artifacts in production.

An Electron renderer or Tauri Web UI is part of its containing desktop module and routes to
`xy-desktop`, not `xy-web`. An independent browser application in the same monorepo remains an
`xy-web` module.

## `xy-desktop`

`xy-desktop` is the primary implementer for complete Electron and Tauri application modules. Its
scope includes renderer or Web UI code, Electron main and preload processes, Tauri Rust core and
commands, IPC and capability contracts, native modules and sidecars, OS integration, packaging,
signing, notarization, installers, auto-update configuration, and repository-owned release logic.
The same desktop module is not split between `xy-web` and `xy-backend`; exact task `owned_paths`
remain the write-authorization boundary.

The renderer or WebView is an unprivileged boundary. Electron IPC and preload APIs must be narrow,
typed where the repository supports it, and validated on the privileged side; generic filesystem,
shell, or Node access must not be exposed to renderer code. Tauri commands, plugins, and
capabilities follow least privilege and validate privileged-side inputs. Remote content never
inherits local privileges. Native modules, plugins, and sidecars must account for the configured
OS targets, CPU architectures, ABI, lifecycle, and failure behavior.

The role preserves the repository's current Electron or Tauri runtime, version, package manager,
build system, and release architecture. It does not initiate an Electron-to-Tauri or
Tauri-to-Electron migration without explicit task authorization. Supported operating systems and
architectures, installer formats, distribution channels, signing identities, notarization and
entitlement policy, updater rollout and rollback policy, and footprint budgets belong in current
repository configuration or `ENGINEERING.md`; the role never invents universal values for them.

Verification uses only repository-native scripts, checked-in wrappers, manifests, CI, and platform
tools actually available. A build on one operating system does not prove another platform. Missing
certificates, notarization credentials, signing infrastructure, target operating systems, or CI
evidence are reported as unverified release scope, never as successful distribution. Desktop UI
work consumes the approved concrete prototype page and dependency fingerprint and follows the same
no-screenshot contract as other roles.

## Platform, Design, and QA Roles

`xy-apple` and `xy-android` remain separate because their build systems, lifecycle models,
permissions, signing, concurrency, and platform validation are materially different. Their concrete
version targets come from `ENGINEERING.md` and executable project configuration, not hardcoded
universal versions in the role.

`xy-uiux` adopts professional interaction-design, information-architecture, accessibility, and
developer-ready-deliverable behavior while retaining the approved stable prototype workspace,
five-section in-page contract, concrete-page link handoff, no Manifest, no companion design Markdown,
and absolute no-screenshot user approval contract.

`xy-qa` adopts evidence-over-claims and actionable expected-versus-actual findings while remaining
read-only. Browser inspection may use an ephemeral in-memory rendered frame only when needed; it
must never generate, persist, attach, present, or use a screenshot as approval evidence.

## Automatic Workspace Discovery

Normal installation derives role scopes from repository evidence on every setup, preflight, and
check. Discovery is deterministic, read-only, bounded, does not follow symlinks, and emits no
Manifest or cache.

The scanner ignores at least:

- the copied `agent_workflow/` pack;
- `.git/` and other VCS metadata;
- `node_modules/`, vendored dependency trees, virtual environments, and package caches;
- generated build, distribution, coverage, IDE, and compiler-cache directories;
- configured explicit exclusions.

It recognizes module roots from build and project manifests rather than assigning arbitrary folders.
Examples include Web package manifests and framework configs; Electron application entry points plus
Forge, Builder, or equivalent configuration; Tauri configuration, `src-tauri/`, and matching Cargo
dependencies; Python project manifests; Maven and Gradle builds; Go workspaces; Cargo packages;
Composer, Ruby, Elixir, .NET, CMake, Meson, and Make projects; Xcode workspaces and Apple targets;
Android manifests and Android Gradle plugins; and machine-readable API or service definitions when
paired with source/build evidence.

Desktop classification has precedence over generic Web, Node backend, and Rust classification only
within the detected Electron or Tauri module root. The entire renderer/main/preload or
frontend/`src-tauri` application is one `xy-desktop` module. Merely listing an Electron or Tauri
package without a valid application entry point or configuration is insufficient evidence. Separate
browser and backend modules in the same monorepo keep their own `xy-web` and `xy-backend` primary
roles.

One role may receive multiple ordered module roots. Nested and monorepo roots are normalized,
deduplicated, and stably ordered. A mixed application receives a deterministic primary role for
module-level routing, while the PM may route a task to another capable role using exact task paths.
Discovered scopes never override task-pack authorization.

Unknown ordinary asset or document directories remain unassigned. A code module with clear backend
or systems evidence and no more-specific Web, desktop, Apple, or Android classification routes to
`xy-backend`. Discovery never assigns every unknown directory to `xy-backend`.

## Automatic Role Enablement

Generated hosts enable only roles justified by discovered project surfaces, with these rules:

- `xy-qa` is always enabled and remains project-wide read-only;
- `xy-web`, `xy-desktop`, `xy-backend`, `xy-apple`, and `xy-android` are enabled by discovered
  implementation modules;
- `xy-uiux` is enabled when a user-facing UI surface exists or a configured design workspace is
  present;
- the PM remains the main session and is always available.

Users do not maintain an ordinary `enabled_roles` list.

## Automatic Verification Command Discovery

Verification commands come only from checked-in wrappers, manifests, lockfiles, package scripts,
CI configuration, or other repository-native evidence. The detector may expose existing lint,
typecheck, compile, test, build, package, and release-verification commands per module, including
real Electron Forge or Builder scripts and Tauri CLI/Cargo commands when supported by repository
evidence. It never invents a script, installs a tool, assumes signing credentials, or treats a
generic global command as preferable to a checked-in wrapper.

If no reliable command exists, setup remains usable. The implementation Agent must inspect nearby
project documentation and CI, then report the missing verification contract if no command can be
established.

## Project Configuration

The ordinary portable adapter removes required `sandboxes`, `enabled_roles`, and `commands` fields.
It retains memory, orchestration limits, discovery mode, optional exceptional overrides, and document
paths. A minimal shape is:

```yaml
project_name: <project-name>

memory:
  provider: agentmemory
  mode: preferred
  isolation: strict
  project_id: <auto-derived>
  qa_requires_provider: false
  portable_checkpoint: docs/STATUS.md
  fallback_dir: docs/notes/

orchestration:
  max_concurrent_subagents: 8
  max_parallel_writers: 6
  max_writers_per_path: 1
  max_depth: 1

workspace:
  discovery: auto

workspace_overrides: {}

docs:
  engineering: docs/ENGINEERING.md
  design_system: docs/DESIGN_SYSTEM.md
  contracts: docs/SPEC.md
  progress: docs/STATUS.md
  design: docs/design/
```

Overrides are exceptional include/exclude or role assignments for an unusual repository. Unsafe,
ambiguous, duplicate, escaping, symlinked, or type-conflicting overrides fail before writes. The
pack does not preserve the retired configuration shape as a compatibility mode.

## Engineering Contract Initialization

Project-specific target constraints such as Java 21 belong in `docs/ENGINEERING.md`, not in
`xy-backend`, discovery output, project memory, or `project.yaml`.

On first installation only, setup may initialize a missing, empty, or untouched stock
`ENGINEERING.md` with observed facts proven by repository configuration, such as the current runtime,
framework, package manager, build wrapper, and module root. This baseline is explicitly observational,
not an upgrade target. Existing user content is never overwritten.

Target constraints remain explicit, for example:

```markdown
## Required Technology Constraints

| Scope | Category | Required Contract |
|---|---|---|
| `educational-cloud/` | Runtime | Java 21 |
| `educational-cloud/` | Build | Use the checked-in Maven or Gradle wrapper |
```

If observed executable state and the required contract disagree, an ordinary unrelated task must
not silently perform the migration. The PM checks whether the approved task includes the upgrade and
reopens requirements approval only when the change materially alters approved scope, constraints,
or acceptance evidence.

## Read-Only Discovery Preview

`--preflight` prints a stable discovery plan containing each enabled role, module root, evidence,
and detected verification commands. It does not prompt for confirmation, initialize project IDs,
write documents, create bytecode, or generate host artifacts.

`--check` recomputes discovery and verifies generated artifacts against the current repository. A
new or removed module creates a clear drift diagnostic. Normal setup regenerates current pack-owned
artifacts from the new discovery result.

## Authority and Memory

Authority remains ordered as follows:

1. current user requirements and approved task scope;
2. current controlled `SPEC.md` and `ENGINEERING.md` contracts;
3. current executable manifests, lockfiles, code, and evidence;
4. task-pack exact paths and acceptance criteria;
5. canonical role behavior;
6. strictly project-isolated memory as supporting historical context only.

Workers may identify memory-worthy observations but return them to the PM. Only the PM performs
project memory closeout after QA PASS. If strict project filtering or matching provenance is
unavailable, the workflow calls neither provider recall nor provider save and uses checked-in docs.

## Safety and Failure Behavior

Discovery and ownership validation complete before the first project write. Unsafe paths, symlinks,
special files, malformed manifests, conflicting overrides, unprovable generated-target ownership,
or inconsistent host staging fail closed. Unknown user content is preserved.

Normal setup may replace or delete only artifacts whose current strict ownership and expected type
are proven at mutation time. It uses the pack's existing atomic and rollback behavior. No retired
compatibility parser or approximate content adoption is introduced.

## Verification

Implementation uses test-driven development with fixtures for representative Web, backend language,
Apple, Android, Electron, Tauri, Electron-plus-independent-Web monorepo, and other monorepo projects.
Tests cover deterministic discovery, desktop-over-Web/backend classification precedence, automatic
role enablement, repository-native desktop command discovery, exceptional overrides, unsafe paths,
current-inventory ownership, user-owned collision preservation, ENGINEERING initialization, all three
host renderers, setup idempotency, preflight/check zero writes, dynamic DAG behavior, UI contracts,
desktop security and release evidence, QA, and agentmemory.

The final source pack must contain no active positive references to `xy-python`, `xy-rust`, or
`xy-java`, and generated fixtures must contain exactly the canonical role set justified by their
detected project surfaces.
