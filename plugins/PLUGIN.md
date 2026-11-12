# Agent Workflow official plugin alpha

The plugin version comes only from `product/PLUGIN_VERSION`. The packaged 2.x
`product/VERSION` identifies preserved source authority, not the plugin release.
Python 3.11+ is required. Windows delivery is paused. The build is offline and
uses Python's standard library. Plan delivery uses Markdown; the retired plan HTML
generator and its dedicated renderer are excluded. Prototype HTML and visual approval remain active.
Use the unchanged `lib/python_runtime.sh` interpreter selector because a machine's
default `python3` can be older even when a supported version is already installed.
It selects existing Python only, without installing software or changing PATH.

The host owns plugin installation, enablement, disablement and updates. No central
runtime import, activation, project registration or instruction-file writes are
prerequisites. The build contains product authority, shared skills, roles, native
host resources, original workflow helpers and their required dependencies.
另有独立的 `agent-config` 维护 Skill、固定轻量启动器和组件发行描述，仅在用户显式
调用时定位或准备独立组件。插件不包含配置服务实现、网页、独立组件 ZIP 或模型 MCP。
Core dispatch uses the
official host's default or already configured model/reasoning settings. Missing
configuration software never blocks the core workflow.

Native Agent Configuration is a separate product implemented in `native_config/`
and delivered by its own builder and version source. 插件构建器只装配薄入口及固定发行
元数据，不导入或读取独立配置核心源码；业务流程不依赖组件已安装或服务运行。
核心与网页仍分别发布，模型配置维护失败不能阻断普通工作流。The earlier AWF-only seven-role
configuration experiment and its integrated assembly have been retired.

生成的九个核心 Skill 来自 `platforms/shared/skills/`，`agent-config` 来自独立维护
目录，不计入 CORE_SKILLS 或任何 Worker 的预载。核心 Skill 的前置元数据与原正文
完整保留，只在前置元数据后插入实际宿主的资源适配说明；引用文件逐字节复制。
`roles/` and `product/`
remain canonical; native agent prompts retain complete original role bodies.
`sources.json` records source hashes, generated projections, package hashes and
the result of the existing business-confirmation/execution-contract validators.
These hashes prove content fidelity, not actual host dispatch.
维护 Skill 不注入工作流 envelope。三端主会话先读取短路由，仅用户真正显式调用
维护 Skill 时执行固定启动器；“实现 agent-config”等普通需求继续读取原完整工作流。
维护动作不建任务图、不派子代理，不替代网页的预览确认，也不授予业务批准。
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
| Codex | Packaged SessionStart reminder after official Hook review; explicit discovered `agent-workflow:xy-workflow` is also available | No plugin `agents` manifest field is claimed; use complete role instructions through a supported fresh native handoff or verified native role definition | CLI 0.167.0 已验 Alpha.3 的九个核心 Skill 与 Hook；当前候选另增维护 Skill，按当前构建和实际宿主发现记录单独验收 |
| Claude Code | Plugin `settings.json` selects the packaged `pm` entry in the main conversation; explicit `/agent-workflow:xy-workflow` also works | Seven native worker agents with complete role bodies plus the separate main-session entry | CLI 2.1.311 confirms the default main agent, fresh native dispatch, same-ID continuation and configured model/effort through host events; this does not establish unrelated client surfaces |
| Antigravity | Plugin-owned `rules/AGENTS.md` routes business intake to `xy-workflow` and explicit maintenance to `agent-config` | Packaged `agents/` with full role bodies | CLI 1.5.5 已验 Alpha.3 的九个核心 Skill、七个 Agent 和一条规则；当前维护 Skill 单独验核。每个实际发现 Skill 继续受 24,000 字节构建上限保护；真实派发另判 |

Claude's plugin default is below the user's own default-agent setting; it changes
no global configuration or model. The `pm` entry only points the main session to
the shared authority. It is not another worker or an independent orchestrator.
Codex skips the packaged Hook until the user trusts it through the official client.
The plugin never writes trust or bypasses permission review. Codex currently
documents plugin hooks for manually installed desktop/local plugins and excludes
hook-containing plugins from its public directory; this package makes no public
directory eligibility claim. CLI local-marketplace installation does not prove
the CLI delivered a trusted Hook to a new model session.
Real CLI 0.167.0 install controls found that a portable root `plugin.json` omitted
Hooks even with `extensions.com.openai.hooks` or a compatibility manifest present.
This Codex payload therefore emits only `.codex-plugin/plugin.json`, whose Hook
is discovered by the actual client. Do not reintroduce both formats or substitute
global/project instruction files, direct trust writes or permission overrides.
Default-startup behavior still requires its own authenticated native-session evidence.

Neither inventory discovery, direct Hook-script output nor manifest validation
establishes a complete newly opened session or native worker dispatch. That still
requires an authenticated real host session; no credentials are copied into the
isolated verification fixtures, and no permission bypass is used.

Official format references, checked on 2026-11-11:

- https://developers.openai.com/plugins/build/plugins
- https://developers.openai.com/plugins/deploy/desktop-only
- https://code.claude.com/docs/en/plugins-reference
- https://antigravity.google/docs/build-plugins/
