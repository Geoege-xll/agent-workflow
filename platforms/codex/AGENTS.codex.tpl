## Codex-only integration

Applies only in Codex. Non-Trivial implementation: `$xy-workflow`; Trivial: shared early exit.
Skills: `.agents/skills/`; roles: `.codex/agents/`. Keep native collaboration and no nested dispatch.
Before first orchestration, the current PM reads [Codex integration](.agent-workflow/platforms/codex/references/pm-integration.md).
Reuse fully read, unchanged context; do not read other hosts' details.
`General Trivial early exit` does not preload the entire host or product procedure.

<!-- bootstrap-contract: platforms/codex/references/pm-integration.md -->

Check: `bash .agent-workflow/setup_codex.sh --check`.
