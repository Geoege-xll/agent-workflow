## Codex-only integration

Applies only in Codex. Light and Full implementation use `$xy-workflow`.
Skills: `.agents/skills/`; roles: `.codex/agents/`. Keep native collaboration and no nested dispatch.
Before first orchestration, the current PM reads [Codex integration](.agent-workflow/platforms/codex/references/pm-integration.md).
Reuse fully read, unchanged context; do not read other hosts' details.
Light reads only its applicable branch; Full retains planning, confirmation and independent QA.

<!-- bootstrap-contract: platforms/codex/references/pm-integration.md -->

Check: `bash .agent-workflow/setup_codex.sh --check`.
