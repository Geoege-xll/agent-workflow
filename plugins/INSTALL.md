# Install or load the current local plugin

The repository's manifest templates are build inputs. Generate a complete local
source bundle first; the official clients install or load that generated payload:

```bash
bash lib/python_runtime.sh -B -X utf8 packaging/build_plugin.py \
  --host all --output-dir /absolute/new-output-directory --local-source
```

Use a new output directory for each candidate. The command emits deterministic
plugin ZIP files and complete source directories under `local/`, including the
official local marketplace manifests. Each marketplace references only its own
real `plugins/agent-workflow` directory. No source checkout, runtime installer,
Node runtime, package installation or configuration service is required after building.
Each `*-local-source.zip` is a shareable copy of that complete host-specific
directory. Unpack it into a new folder, then pass the unpacked folder to the
marketplace/directory commands below. The separate plugin ZIP is not a marketplace
ZIP; a Codex marketplace install needs the included marketplace manifest too.

Codex local marketplace commands, supported by CLI 0.167.0:

```bash
codex plugin marketplace add /absolute/new-output-directory/local/codex
codex plugin add agent-workflow@agent-workflow-local
codex plugin list --json
```

These user-run install commands modify the official client's own installation
state. They are provided for an intentional local install; build and verification
do not run them against the user's environment. The current CLI does not provide
a documented `--plugin-dir` temporary load argument. Packaged Hook discovery and
default-startup delivery remain an explicit acceptance blocker in CLI 0.167.0.
Never bypass Hook trust or add global instruction files to hide that limitation.

Claude Code can load a candidate without a persistent marketplace installation:

```bash
claude --plugin-dir /absolute/new-output-directory/local/claude/plugins/agent-workflow
```

For an intentional persistent local installation:

```bash
claude plugin marketplace add /absolute/new-output-directory/local/claude
claude plugin install agent-workflow@agent-workflow-local
```

Claude Code 2.1.311 also accepts a plugin ZIP in `--plugin-dir`. The generated
directory is useful for inspecting the exact installed source. Start a new
conversation after installation so the client can apply the plugin's main-session
default; user settings retain their documented precedence.

When an official Antigravity CLI is available, its documented local-directory path is:

```bash
agy plugin validate --strict /absolute/new-output-directory/local/antigravity/agent-workflow
agy plugin install /absolute/new-output-directory/local/antigravity/agent-workflow
```

The installed desktop has official Marketplace/Installed plugin management, but
this candidate has not been loaded there and no official `agy` CLI was found in
the inspected app bundle. These commands describe the documented CLI route, not
a completed local-host acceptance result.

No remote release asset, public plugin listing, tag or remotely installable branch
has been published for this alpha. There is currently no verified remote one-line
install command. The paths above are real local build outputs, not unpublished URLs
or checked-in manifests that point into an ignored `dist/` directory.
