# Agent Workflow official plugin alpha

The plugin version comes only from `product/PLUGIN_VERSION`. The packaged 2.x
`product/VERSION` identifies preserved source authority, not the plugin release.
Python 3.11+ is required. Windows delivery is paused. The build is offline and
uses Python's standard library; the preserved requirements HTML helper also needs
an existing Node runtime when that branch is actually used.
Use the unchanged `lib/python_runtime.sh` interpreter selector because a machine's
default `python3` can be older even when a supported version is already installed.
It selects existing Python only, without installing software or changing PATH.

The host owns plugin installation, enablement, disablement and updates. No central
runtime import, activation, project registration or instruction-file writes are
prerequisites. The default build contains the workflow core only: product authority,
shared skills, roles, native host resources, original workflow helpers and their
required dependencies. It contains no model configuration service, configuration
web page, model MCP declaration, or service launch script. Core dispatch uses the
official host's default or already configured model/reasoning settings. Missing
configuration software never blocks the core workflow.

Native Agent Configuration is a separate product implemented in `native_config/`
and delivered by its own builder and version source. This workflow builder has no
configuration-service or MCP integration mode. Its plugin payload, source manifest,
version and startup do not depend on that product. The earlier AWF-only seven-role
configuration experiment and its integrated assembly have been retired.

The generated `skills/` tree is a discovery projection of the single source at
`platforms/shared/skills/`. Its SKILL frontmatter and original body remain intact;
only the resource adapter from `plugins/plugin-context.md` is inserted after the
frontmatter. Reference files are copied byte-for-byte. `roles/` and `product/`
remain canonical; native agent prompts retain complete original role bodies.
`sources.json` records source hashes, generated projections, package hashes and
the result of the existing business-confirmation/execution-contract validators.
These hashes prove content fidelity, not actual host dispatch.
See `INSTALL.md` for commands that build a complete local marketplace/source
payload and install or temporarily load it with the official clients. No remote
one-line installation route has been published for this alpha.

From the repository checkout, generate a new local candidate:

```bash
bash lib/python_runtime.sh -B -X utf8 packaging/build_plugin.py --host all --output-dir /absolute/new-output-directory --local-source
```

Then load it temporarily in Claude, or intentionally install the Codex local
marketplace through the official client:

```bash
claude --plugin-dir /absolute/new-output-directory/local/claude/plugins/agent-workflow
codex plugin marketplace add /absolute/new-output-directory/local/codex
codex plugin add agent-workflow@agent-workflow-local
```

The Codex install commands change the client's installation state when the user
chooses to run them. Building the candidate performs no user-environment install.

Resolve historical managed paths explicitly, without a project bridge:

```text
bash <plugin-root>/lib/python_runtime.sh -B -X utf8 <plugin-root>/plugins/source_pack.py resource .agent-workflow/product/WORKFLOW.md
bash <plugin-root>/lib/python_runtime.sh -B -X utf8 <plugin-root>/plugins/source_pack.py resource platforms/shared/skills/xy-workflow/SKILL.md
bash <plugin-root>/lib/python_runtime.sh -B -X utf8 <plugin-root>/plugins/source_pack.py helper --project <absolute-project> lib/task_graph_cli.py validate --input <absolute-task-file>
```

`resource` returns the exact packaged absolute path and SHA-256; it does not read
project configuration. `helper` runs only the packaged helper allowlist with the
actual project as cwd and uses the original helper implementation. It never runs
an agent or invents approvals. The selected adapter is the actual project's
verified `project.yaml` or `.awf/project.yaml`. For a new project, use:

```text
bash <plugin-root>/lib/python_runtime.sh -B -X utf8 <plugin-root>/plugins/source_pack.py helper --project <absolute-project> plugins/project_context.py inspect
bash <plugin-root>/lib/python_runtime.sh -B -X utf8 <plugin-root>/plugins/source_pack.py helper --project <absolute-project> plugins/project_context.py apply --adapter .awf/project.yaml
bash <plugin-root>/lib/python_runtime.sh -B -X utf8 <plugin-root>/plugins/source_pack.py helper --project <absolute-project> plugins/project_context.py init --adapter .awf/project.yaml --input <decisions.json> --output <new-graph.json>
```

Inspection is read-only. Explicit `apply` creates only the missing adapter and
reuses valid existing configuration without rewriting it. It creates no PROJECT,
STANDARDS, plan, HTML, instruction file, central registration or bridge. Initial
task decisions retain their original gates and approvals; the adapter is not an
approval and adds no confirmation stage. Ambiguous adapters, unsafe nodes and old
central bindings are rejected. Missing documents, standards,
host capabilities or external skills retain their original blocking behavior.
Resolve each call from the same installed plugin version, preserving original
task inputs and ownership. The source-pack path is independent of old central
bindings and refuses their markers or environment instead of silently clearing
them. Existing central tasks must remain with their original runtime.

The alpha has no automatic resource-retention protocol for an in-progress task
when a host replaces its plugin cache. Finish or hand off such tasks before
updating the plugin; update/resume retention remains pending host acceptance.
Codex plugin-native custom-role discovery is not documented and is not claimed.
Packaged role instructions can be used only through a supported fresh native
handoff. Neither manifest parsing nor `claude plugin validate` establishes native
model/effort application, context isolation or end-to-end workflow acceptance.
Every built package starts with `runtime_verified: false` in `sources.json`.

| Host | Main-session entry | Native role discovery | Actual acceptance status |
| --- | --- | --- | --- |
| Codex | Packaged SessionStart reminder, with actual CLI default-startup acceptance currently blocked; explicit discovered `agent-workflow:xy-workflow` remains available | No documented portable `agents` manifest key; use complete role instructions through a supported fresh native handoff | CLI 0.167.0 isolated install/list and app-server skills/list discovered nine enabled plugin skills; hooks/list did not discover the packaged Hook |
| Claude Code | Plugin `settings.json` selects the packaged `pm` entry in the main conversation; explicit `/agent-workflow:xy-workflow` also works | Seven native worker agents with complete role bodies plus the separate main-session entry | Native validate and `--plugin-dir ... plugin details` inventory accepted; model-backed startup/dispatch remain unverified |
| Antigravity | Plugin-owned `rules/AGENTS.md` points main-session task intake to `xy-workflow` | Packaged `agents/` with full role bodies | Desktop 2.29.0 has official Marketplace/Installed plugin management; no official `agy` CLI was found in PATH or the app bundle. This candidate has not been loaded in the desktop, so its rules/agents are not verified |

Claude's plugin default is below the user's own default-agent setting; it changes
no global configuration or model. The `pm` entry only points the main session to
the shared authority. It is not another worker or an independent orchestrator.
Codex skips the packaged Hook until the user trusts it through the official client.
The plugin never writes trust or bypasses permission review. Codex currently
documents plugin hooks for manually installed desktop/local plugins and excludes
hook-containing plugins from its public directory; this package makes no public
directory eligibility claim. CLI local-marketplace installation does not prove
the CLI delivered a trusted Hook to a new model session.
The current CLI result remains an explicit default-startup acceptance blocker,
including after declaring `extensions.com.openai.hooks` explicitly. Do not fill
that gap by writing global/project instruction files, hook trust or permission
overrides. The actual host must prove supported plugin startup delivery first.

Neither inventory discovery, direct Hook-script output nor manifest validation
establishes a complete newly opened session or native worker dispatch. That still
requires an authenticated real host session; no credentials are copied into the
isolated verification fixtures, and no permission bypass is used.

Official format references, checked on 2026-11-11:

- https://developers.openai.com/plugins/build/plugins
- https://developers.openai.com/plugins/deploy/desktop-only
- https://code.claude.com/docs/en/plugins-reference
- https://antigravity.google/docs/build-plugins/
