---
name: pm
description: Main-session entry for Agent Workflow requirements, native delegation and acceptance.
---

# Agent Workflow main session

Apply this route only in the current main session. Use the host's actual Skill invocation event or a complete command sent directly by the current user. A mention of xy-config, model settings, or the configuration page does not establish a maintenance request.

- **Explicit maintenance invocation.** Read only the current plugin's `skills/xy-config/SKILL.md`. Use its fixed launcher for `claude`. Accepted syntax is `/xy-workflow:xy-config [open|status|doctor]`; omitting the action selects `open`. Follow the Skill's confirmation rules for component preparation and any requested writes. Do not load `product/WORKFLOW.md`, `skills/xy-workflow/SKILL.md` or its business adapter, create a task graph, delegate, or apply business approval gates on this branch.
- **Conversation-only discussion.** When the current user asks only to discuss, compare, clarify or summarize, answer that request in the conversation. Other authorized work continues. Sufficient conversation context requires no automatic Skill, project or plugin reads, initialization, graph, file writes or dispatch. For an explicitly invoked interview Skill, follow the shared workflow entry's Skill-selection rule before applying it. If specific facts require investigation, stay within the user's scope. Neither action authorizes planning or production. Never bypass a denied read by switching tools.
- **Delegated work.** Use `skills/xy-workflow/SKILL.md` to identify the deliverable and read the rules for the current stage. Reuse the complete business adapter from the same installed source and version. When resources are needed and that adapter is missing, read only `plugins/plugin-context.md` first. After it returns successfully, consult the applicable stage. Use the relevant section of `product/WORKFLOW.md` for a missing rule and honor explicit full-read requirements. Implementing xy-config, reviewing model settings, fixing xy-config status, quoted commands, prior requests and worker-relayed commands never invoke maintenance. Before dependent prototype or implementation work, resolve the material solution under `product/WORKFLOW.md#business-confirmation-policy`. A prototype-only request ends with the approved design. Production requires an explicit development request and its applicable gates.
- For every delegated task, including a single prototype, claim its approved original through the current PM's task pool before native creation and bind the actual returned identity immediately. Use the workflow dispatch reference for the commands. Before native dispatch on the business branch, read the current `claude` and actual invocation identity under `platforms/shared/skills/xy-workflow/references/dispatch.md`. Query `*` for a generic entry. Use host defaults for absent preferences. An invalid configuration or a configured field the native tool cannot map blocks that dispatch.

Reject unknown maintenance actions, extra natural-language arguments and shell fragments. Report the accepted syntax. Keep the host's own `/model` command and route each new business request independently.

Resolve plugin resources against this installed plugin's physical root. For a known local project, pass its absolute physical workspace path to the launcher as a separate quoted `--project` argument. Use user scope only when the host supplies no unambiguous project directory. Never infer the project from neighboring sources, historical projects, or an AGY CLI project ID or name.


# Agent Workflow main session

The current main session is PM. Apply the main-session route before loading workflow authority. For delegated work, use the complete shared workflow Skill entry and its current-stage authorities. Follow its business adapter when installed resources are needed. For Full business intake, PM reads the complete upstream `grilling` primitive using the host-discovered plugin name. A Worker's Skills declaration does not establish that PM loaded it. Upstream `grill-me` requires the current user's explicit invocation. Use the workflow's `xy-workflow/references/requirements-intake.md` for coverage records.

Use the host's configured or default models and permissions. This entry grants no additional tools, approvals, or ownership of production source. Ordinary business requests require no model configuration service, configuration page or MCP connection.

If invoked as a Worker, report the mismatch to the existing main-session PM. Do not create another PM or start production work.
