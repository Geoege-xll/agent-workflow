## Claude Code-only integration

Applies only in Claude Code. Light and Full implementation: `/xy-workflow`; native dispatch: `Agent(xy-*)`.
Skills: `.claude/skills/`; roles: `.claude/agents/`.
Before first orchestration, the current PM reads [Claude integration](.agent-workflow/platforms/claude/references/pm-integration.md).
Reuse fully read, unchanged context; do not read other hosts' details.
Light reads only its applicable branch; Full retains planning, confirmation and independent QA.
Root `CLAUDE.md` imports only root `AGENTS.md`, not these full detail files.

<!-- bootstrap-contract: platforms/claude/references/pm-integration.md -->

Check: `bash .agent-workflow/setup_claude.sh --check`.
