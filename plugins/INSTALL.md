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
a documented `--plugin-dir` temporary load argument. For CLI 0.167.0, this candidate
uses the official `.codex-plugin/plugin.json` compatibility format without a root
`plugin.json`: real local-install controls found that the portable root format
silently omitted bundled Hooks. After installation, open the official `/hooks`
manager, inspect the candidate SessionStart command and trust its current definition
through the client. Installing or enabling the plugin alone does not grant Hook trust.
Never write trust records directly or add global instruction files to substitute
for this review. Start a new conversation after the official review.

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

The installed desktop has official Marketplace/Installed plugin management. The
native acceptance work uses the vendor's CLI 1.5.5, downloaded into a temporary
directory and checked against its official SHA-512 manifest, without changing PATH
or installing a second shell environment. The strict validator also checks the
24,000-byte Skill body limit; the builder rejects a payload that would be truncated.
Validation and an installation receipt alone do not establish model-backed execution.

## 安装后的“模型配置”入口

维护 Skill 名为 `agent-config`，省略动作即打开配置台。Claude 使用
`/agent-workflow:agent-config`，Codex 在原生 `/skills` 或 `$` 选择器中选择实际发现的
插件 Skill，AGY 当前载荷使用 `/agent-config`，以实际发现项为准。可加 `status` 或
`doctor` 做只读检查。

平台由当前插件构建固定；项目使用当前会话明确的绝对目录，没有项目时进入用户级。
缺少独立组件时先报告准备信息，用户确认后才调用固定准备参数。组件来自已核验的
独立发行包，校验后安装到用户级版本目录，不使用源码路径或从插件缓存寻找后端。
未发布的候选发行描述不会自动尝试不存在的下载地址；显式离线包也须匹配固定摘要。

服务已就绪但浏览器失败时保留私有打开入口，并分别报告这两个状态。只读命令不创建
组件、连接或权限记录，不启动 HTTP 或模型查询。正常业务流程不调用此入口，不需要
配置组件或 MCP。插件只读角色和平台原生字段限制不因打开配置台而改变。

工作流插件的公开市场条目与远程一键安装仍以实际发布记录为准，不能从本地构建命令
推断已发布。独立配置组件的 alpha 资产单独发布，只有经实际下载核验的地址与摘要
才写入组件描述。上述插件路径是实际本地构建输出，不是尚未发布的下载地址，也不
指向被忽略的开发 dist 目录。
