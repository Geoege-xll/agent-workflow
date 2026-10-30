## Claude Code-only integration

Applies only in Claude Code. Non-Trivial: `/xy-workflow`; native dispatch: `Agent(xy-*)`.
Skills: `.claude/skills/`; roles: `.claude/agents/`.
Before first orchestration, the current PM reads [Claude integration](.agent-workflow/platforms/claude/references/pm-integration.md).
Reuse fully read, unchanged context; do not read other hosts' details.
`General Trivial early exit` uses shared rules without preloading the entire procedure.
Root `CLAUDE.md` imports only root `AGENTS.md`, not these full detail files.

<!-- bootstrap-contract: platforms/claude/references/pm-integration.md -->

Check: `bash .agent-workflow/setup_claude.sh --check`.
