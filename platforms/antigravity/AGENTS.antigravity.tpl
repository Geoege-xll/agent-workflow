## Antigravity-only integration

Applies only in Antigravity. Non-Trivial: `/xy-workflow`.
Skills: `.agents/skills/`; roles: `.agents/agents/`.
Before first orchestration, the current PM reads [Antigravity integration](.agent-workflow/platforms/antigravity/references/pm-integration.md).
Reuse fully read, unchanged context; do not read other hosts' details.
`General Trivial early exit` uses shared rules without preloading the entire procedure.
Only PM uses `invoke_subagent`; workers never delegate. Do not alter user settings or emulate worktrees
by concurrently switching branches in one directory.

<!-- bootstrap-contract: platforms/antigravity/references/pm-integration.md -->

Check: `bash .agent-workflow/setup_antigravity.sh --check`.
