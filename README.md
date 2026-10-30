# Agent Workflow Pack

Portable **multi-subagent collaboration workflow** for any project.
Keep this installer folder anywhere and select a project when launching it — works with
**Claude Code / Codex / Antigravity**.

## Windows 项目安装（npx，本地准备版）

Windows 方案只做**在项目目录执行 `npx … init` 安装工作流**，不提供 TUI、WinGet 或全局管理器。
前置条件为 Windows 10/11 x64、本地 NTFS、Node.js LTS/npm 和完整 Git for Windows；不依赖 WSL，
不需要预装 Python，不修改 PATH、profile、ExecutionPolicy 或 Git 全局配置。

npm 包目前 `private: true`，**尚未发布，尚未通过原生 Windows 安全、恢复与端到端验收**。
下面只是未来完成验收并获准发布后的目标用法，不是现在可用的远程安装命令：

```powershell
cd C:\work\my-project
npx @geoege-xll/agent-workflow init
```

本地 tgz 构建、离线 `npx.cmd --offline --ignore-scripts` 验证、持久 Python 和当前限制见
[Windows 说明](docs/windows.md)。本地验证仅使用独立临时项目，不同步真实项目。

## 终端管理工具（macOS/Linux）

在普通交互终端启动已确认的 TUI，无新增 Python 包依赖。

### Homebrew 安装

完成[首次发行及 Tap 发布](docs/homebrew.md#首次发布)后，可通过 Homebrew 安装：

```bash
brew install Geoege-xll/tap/awf-cli
awf-cli
# 后续只升级中央程序，不自动同步项目。
brew update
brew upgrade Geoege-xll/tap/awf-cli
```

Homebrew 管理完整程序及 Python 依赖，不需要再注册 `--install-cli`，不修改 PATH 或用户
shell 配置。现有同名用户命令不会被移除；请先用 `type -a awf-cli` 核对来源。
仅创建 GitHub 源码仓库还不能安装，发布包、Formula 生成及验收见 [Homebrew 说明](docs/homebrew.md)。

### 源包直接安装

```bash
# 只需安装一次短命令，默认放入 ~/.local/bin；不会修改 PATH 或 .zshrc。
bash /path/to/agent_workflow/workflow.sh --install-cli
# 随后在任意目录启动 TUI。
awf-cli
# 也可以指定初始项目；相对路径按执行命令时所在目录解释。
awf-cli tui --project /path/to/project
```

命令入口链接到当前源包，源包更新后直接生效，不在每个项目复制管理器。请保留中央源包；
移动源包后需先核对并移除旧链接，再从新位置重新注册；已有其他同名命令会被保留并提示先核对。
若 `~/.local/bin` 未加入 PATH，安装器会提示；也可通过 `--bin-dir /path/on/PATH` 选择已有命令目录。
注册器会核对 PATH 中实际优先找到的命令；被其他同名命令遮蔽、仅有相对/空 PATH 项时，
会区分“入口已创建”和“任意目录可用”，保留现有命令及 PATH。相对 Python 解释器和相对 PATH
在启动时先按调用目录定位；相对链接按物理父目录解析，避免目录别名及 `..` 指向错误源包。
内部 `cd` 仅在该次命令中隔离 `CDPATH`，避免同名目录搜索和额外输出干扰；原 `CDPATH`、PATH
及随后传给 Python 的环境保持，不修改用户 shell 配置。

主界面采用轻分隔线布局：左侧项目，右侧角色、模型和推理级别；仅键盘焦点所在面板整行高亮。
顶部显示当前宿主及全部范围的待应用数，草稿以 `*` 标记；底部保留状态及最多两行主要操作提示，完整键位按 `?` 查看。
80 列以上并排显示，较窄终端使用 Tab 切换项目与角色区域；55 列 × 16 行收起辅助详情。
支持默认终端背景；无颜色或不支持默认背景时回退为粗体、反色和文字提示。

新项目安装：选中列表末尾的“＋ 添加并安装项目”并回车，或直接按 `a`，
将项目根目录拖入输入区，按一次回车即可安装三平台工作流。安装成功后自动选中项目并进入角色模型配置。
已有工作流会通过同一安装器升级，保留项目配置；错误和取消仍由安装器预检、备份及恢复机制处理。
源包可以集中存放，通过上方命令从任意当前目录启动，无需复制到项目内，也无需先在项目目录运行。

| 按键 | 操作 |
| --- | --- |
| ↑ / ↓ | 选择项目、角色或弹层选项；搜索输入时选择匹配项 |
| Home / End | 列表首尾；文本页页首 / 页尾；输入区行首 / 行尾 |
| PageUp / PageDown | 列表或文本页翻页，搜索输入期间也可翻页 |
| Tab / Shift+Tab | 正向 / 反向切换项目列表和角色表 |
| / | 搜索当前列表的名称、ID 或项目路径；Enter 接受筛选，再按 Enter 才确认 |
| : | 按中文操作名或英文别名搜索命令；不可用操作显示原因，写操作仍走原确认流程 |
| Enter | 打开角色，选择模型及推理级别并暂存 |
| 1 / 2 / 3 | 切换 Codex、Claude Code、Antigravity |
| s | 预览当前项目及平台的变更，Enter 确认后备份应用 |
| u | 丢弃当前角色草稿，重新读取基线；保留其他角色和项目的草稿 |
| g | 安装升级、检查安装、模型配置备份恢复、本地来源 |
| a | 添加并安装项目：拖入项目根目录，回车直接安装 |
| r | 按需刷新本地模型目录及角色设置，保留未应用草稿 |
| Esc | 取消搜索输入并恢复原选择；已有筛选时先清除，再逐层返回 |
| ? / q | 帮助 / 退出；有任何项目或宿主的草稿时先确认放弃 |

路径输入支持 `← / →`、`Home / End`、`Delete / Backspace` 和 `Ctrl+U` 清空；长路径围绕光标横向滚动。
搜索、命令和路径输入中的 `q/s/u/1/2/3/?/:` 都作为正文，不触发全局操作。鼠标单击仅聚焦或选中，仍需 Enter 确认。
刷新或切换宿主时尽量按角色 ID 保持选择；被外部移除但仍有草稿的角色显示“已移除”，可用 `u` 单独丢弃。
小窗口退出和空闲 Ctrl+C 同样保护全部草稿；提示无法完整显示时禁止盲确认，需放大窗口。

项目列表合并独立登记记录和默认桌面目录的直接子项目；不递归读取业务代码、Git worktree 或会话。
使用 `--scan-root /path/to/projects` 指定扫描目录。管理状态及模型备份默认保存在
`~/.config/agent-workflow`，可通过 `--state-dir` 或 `AGENT_WORKFLOW_STATE_DIR` 改为其他目录。
每次模型写入还会将旧文件 inode 保留到项目同文件系统的 `.agent-workflow-backup-models-<ID>/`，
路径记入备份并在操作结果中展示；旧编辑器后续保存仍可找回。恢复前会检查这些版本是否有后续变更。
恢复预览会保留原版本指纹；确认发布前及验收结束后再次核对，期间发生后续保存或权限变化会停止并保留冲突版本。
该目录使用现有运行时备份排除前缀，不参与项目模块发现，也不生成第二份工作流。
列表/目录/预览命令只读；TUI 添加入口在安装成功后登记项目。
CLI 的 `projects add` 仍只登记；自动安装通过 TUI 添加入口或 `install --apply` 执行。

模型目录只投影允许的元数据，不显示或复制凭据，也不请求上游服务：

- Codex 读取明确配置的 `model_catalog_json`；CPA、CC-Switch 等工具写入宿主的显式目录可以直接识别。
  相对路径按声明该字段的用户配置目录或项目 `.codex/` 目录解析。
  默认 `models_cache.json` 的真实身份为不透明摘要；不读取凭据猜归属，未确认时只提供继承与当前已配置模型，
  缓存标为未确认来源，不将其中模型及能力当成当前提供方的可用性证据。
  不读取废弃的 `profile` / `[profiles.*]`；独立 profile 会话需明确目录来源，不自动推断。
  推理级别按目录能力提供，不启用涉及自动委派的 `ultra`。
- Claude Code 读取当前模型、别名映射及代理工具写入的 `modelPicker.options`。
  缓存中的 `modelSettings` 仅为偏好，不能推断推理能力；第一版未知时保留继承。
- Antigravity 静态角色使用官方 `inherit / flash / pro` 档位，不猜测内部模型 ID。

角色模型偏好写入现有 `.agent-workflow/project.yaml` 的 `role_models` 区块，升级会保留。
模型应用只更新该区块与选中角色的模型字段，保留角色正文、工具权限、Hooks 和编排规则；
成功前仅检查有变更的平台。已有 Agent 不会被重启，宿主的显式调用及强制设置仍有自身优先级。
预览和最终发布前均核对本地来源摘要；提供方、目录或能力变化时保留草稿并要求重选。
摘要仅包含有效模型、提供方、声明层、映射和能力证据；权限、Hooks、凭据、废弃 profiles、未启用缓存及其他平台的配置变化不会让草稿失效。
并发配置冲突可按 `u` 丢弃该角色草稿后重新编辑；普通刷新不会悄悄重设编辑基线。
项目需要先安装当前版本才能使用模型写入；此工具不维护旧版适配。

```yaml
role_models:
  codex:
    xy-backend: {"model": "your-local-model", "effort": "high"}
  claude:
    xy-qa: {"model": "opus", "effort": "inherit"}
  antigravity:
    xy-uiux: {"model": "pro", "effort": "inherit"}
```

每个角色值使用内联 JSON（合法 YAML），无需安装 YAML 解析包；推荐通过 TUI 修改。
安装/升级复用原有事务安装器及运行时备份；管理器的“备份/恢复”专门处理模型配置，
恢复前展示文件范围并再次备份。预览后有并发变更会停止覆盖，验证失败则撤回仍属于本轮的改动。
观察到旧 inode 的并发保存或旧版本归档失败时，记录 `conflict` 及可核对的保留路径。
发布前为正向写入、回滚和冲突索引预留容量；日志保存失败时仍返回原错误、备份标识和保留路径。
单个损坏备份显示为 `invalid`，不能恢复，但不阻断其他备份或清空界面草稿。
安装管理器传入 600 秒应用预算，由安装器停止 setup 进程组并恢复；管理器不会超时强杀安装器，
也不会在恢复完成前释放项目锁。恢复阶段使用独立预算，避免继承已耗尽的应用时间。
TUI 后台显示实际任务名称、活动指示和已用时间，不显示虚构百分比或恢复阶段。
仅安装期间支持 Ctrl+C 请求取消；界面保持响应，等待安装器退出及必要恢复后才释放项目锁。
模型应用、检查和恢复暂不支持中途取消，Ctrl+C 会提示等待，不会强杀或提前报告已终止。

无交互命令同样可用，所有写操作显式确认：

```bash
awf-cli projects add /path/to/project
awf-cli models --platform codex --project /path/to/project
awf-cli roles --platform codex --project /path/to/project
# 默认仅预览；确认后添加 --apply。
awf-cli set --project /path/to/project --platform codex \
  --role xy-backend --model your-local-model --effort high
awf-cli install --project /path/to/project
awf-cli check --project /path/to/project
awf-cli backups --project /path/to/project
awf-cli restore --project /path/to/project BACKUP_ID
```

`manager/` 与 `workflow.sh` 仅属于管理工具，不复制进每个项目运行时。
删除原安装包后，项目内 `.agent-workflow/` 仍可独立工作；继续使用 TUI 则需保留一份中央源包。
管理器不会自动同步项目、提交、合并、推送或修改全局宿主设置。

宿主模型字段依据：[Codex 子 Agent](https://learn.chatgpt.com/docs/agent-configuration/subagents)、
[Claude Code 子 Agent](https://code.claude.com/docs/en/sub-agents)、
[Antigravity 自定义子 Agent](https://antigravity.google/docs/subagents/)。

## Python runtime

The pack requires **Python 3.11 or newer**, including its standard-library `tomllib`; no Python
packages need to be installed. Setup selects a supported `python3` or versioned Python command
already on PATH before writing project files. If needed, set `AGENT_WORKFLOW_PYTHON` to the desired
executable path. An invalid explicit selection fails instead of silently changing environments.
The macOS/Linux source installer never installs a runtime. The separate Windows npx preparation
bundles Python and deploys it privately on first init; it does not change global shell, host, or
Python configuration. See the [Windows limitations and verification status](docs/windows.md).

For direct workflow CLI calls and workflow-owned temporary/inline Python helpers, use the same
selector rather than assuming the system `python3` meets the requirement. Workflow calls use
`-X utf8` for UTF-8 input/output, and helpers use explicit UTF-8 text-file I/O; business build/test
toolchains remain unchanged:

```bash
bash .agent-workflow/lib/python_runtime.sh -X utf8 .agent-workflow/lib/project_profile_cli.py \
  json .agent-workflow .
```

Dependent commands run only after upstream success: snapshot generation/update → validation → the
current stage's readiness query. Reuse runtime evidence instead of guessing interpreter paths or
repeating probes; see the shared [execution boundary](platforms/shared/skills/xy-workflow/references/dispatch.md#workflow-helper-execution).

## New project

```bash
bash /path/to/agent_workflow/install.sh
# 出现提示后，将项目文件夹拖入终端并按回车。
# 也可直接传参：bash /path/to/agent_workflow/install.sh /path/to/NewProject
```

安装器先在项目内暂存运行时，并显示只读的 `ProjectProfile preview` 完成预检；通过后发布到项目根目录的 `.agent-workflow/`，生成三个宿主入口、
补齐缺失文档并运行 `--check`。成功后原始 `agent_workflow/` 安装包可以移除；
**项目内的 `.agent-workflow/` 不能删除**。安装器不会代替用户删除原包。
以后取得新版安装包时，运行新版的 `install.sh` 并选择同一项目即可升级：项目专属 `project.yaml` 保留，上一版隐藏运行时
留在 `.agent-workflow-backup-*` 供恢复；受管运行时被手工修改时，升级会停止而不覆盖。
首次安装或升级时，若 `project_name` 仍是默认占位名 `MyProject`，安装器会在暂存配置中将其替换为目标项目根目录名
（例如 `/path/to/ParentsKit` → `ParentsKit`），保留原大小写、中文和空格；已明确配置的其他名称保持不变。
名称初始化不修改源包配置或已有的 `memory.project_id`；新生成的文档使用真实名称，已有非空项目文档不批量改写。

默认文档结构仍为 `docs/PROJECT.md`、`docs/STANDARDS.md` 与 `docs/standards/GENERAL.md`
（实际路径由项目适配器配置）。安装器自动补齐通用规范的索引链接，不重排或覆盖项目的其他规范入口。
`GENERAL.md` 的 `agent-workflow:general-common:begin/end` 标记区是内置共通开发规范，
升级时只刷新该区；标题、仓库观察、验证策略及 `Project-specific rules` 等区外内容与文件权限保留。
项目补充写在区外，不在受管区编辑；内容相同不重写文件。已有非空文件没有完整可识别边界时，
无标记的原文保留并提示受控整理，残缺／重复／倒置标记则停止更新，不按旧标题猜测并覆盖。
`--check` 只读检查受管区是否与当前运行时一致；更新改变的规范指纹沿现有任务交接规则处理，
不会增加业务确认阶段或自动触发全量测试。升级验收失败时，仅对仍为本轮精确产物的通用区更新和索引补链回滚；
出现并发项目修改则保留现场并报错，不覆盖用户内容。

项目内也可独立复核：`bash .agent-workflow/setup_all.sh --check`。
新入口不迁移旧的项目内 `agent_workflow/` 安装包；检测到旧包时会停止。
请先自行备份并移除旧包，再安装，避免两个工作流同时生效。

The portable default is `workspace.discovery: auto`. The preview reports the exact selected
roles, module roots, stack evidence, and repository-native verification commands before setup
writes business documents or host entry files. Ordinary projects do not edit role assignments,
module paths, or commands.
Use `workspace_overrides` only for an exceptional repository ambiguity that cannot be resolved
from checked-in evidence; keep explicit technology requirements such as Java 21 in the applicable
engineering leaf under `docs/standards/`.
UI/UX and QA are baseline available roles even in a requirements/prototype-only project; implementation
roles remain discovered from source manifests. Availability does not require UI work. Pure backend
projects retain their engineering-only document scaffold. After cloning/adding modules or changing
the stack, assess actual current-host resource changes using `xy-workflow/references/dispatch.md`.
Use `project_profile_cli.py check-roles <host> .agent-workflow .` through the runtime selector only
when availability is unknown, not before an already-needed refresh. Normal host setup includes
preflight; follow it with `--check` once. Codex refreshes changed persisted module/command context;
Claude/Antigravity may update task-pack facts without reinstalling when installation inputs and
verified resources remain unchanged. Reuse valid evidence instead of probing each new task.
Host-managed `.claude`, `.codex`, and `.agents` directories are excluded at every scan depth, so
their worktrees are not rediscovered as business modules. Explicit module-role overrides remain
available for intentional exceptional routing without scanning a host's private working copies.

## Design principles

Design standards are maintained on demand: PM assesses/adopts the scope, UI Agent writes authorized
leaves, implementers own production tokens/components, and QA independently checks the result.
Initial adoption, incremental rules and full visual replacement follow the
[design-standard lifecycle](platforms/shared/skills/xy-workflow/references/design-standards.md).
This decision is independent of PROJECT/feature updates. `design_mode: standards_only` supports
normative Markdown maintenance even when the user skips prototypes; it adds no HTML, prototype
verification, or visual confirmation. Approved design adoption never implies completed production
migration, and the prototype index remains a page directory rather than a second specification.

| Principle | Meaning |
|:----------|:--------|
| **Portable** | Repository evidence discovers modules, roles, stacks, and verification commands |
| **Soft workspace preferences** | Discovered module roots guide assignment; task-pack authorization controls writes |
| **No default hard write bans** | Claude setup does **not** install PreToolUse deny hooks |
| **Soft guard** | `scripts/guard.sh` prints discovered module attribution; exit 0 by default |
| **Opt-in strict** | `GUARD_STRICT=1` + optional `deny_prefixes` in project.yaml |

## Layout

| Path | Meaning |
|:-----|:--------|
| `project.yaml` | Minimal auto-discovery policy and exceptional safe overrides |
| `install.sh` | 从任意位置选择目标项目并安装或升级 |
| `.agent-workflow/` | 项目内单份自包含运行时；原始安装包移除后保留 |
| `product/` | Cross-platform product discipline |
| `roles/xy-*.md` | Role technical baselines |
| `platforms/*/` | Per-CLI templates |
| `platforms/shared/skills/` | Seven host-neutral core Skills; one shared source for all hosts |
| `platforms/shared/HOOKS.md` | 三平台辅助 Hooks、开关、所有权与原生信任说明 |
| `scripts/` | guard (soft) / portable conflict-marker lint |
| `setup_claude.sh` | → root `AGENTS.md` Claude section + `CLAUDE.md` thin import + `.claude/agents/` + skills |
| `setup_codex.sh` | → root `AGENTS.md` + `.codex/**` |
| `setup_antigravity.sh` | → root `AGENTS.md` block + `.agents/agents/` + shared skills |
| `setup_all.sh` | All platforms |

Generated prompt budgets use UTF-8 bytes and word count as conservative anti-bloat guards while
each host's frontmatter, tool, permission, and managed-artifact schema remains authoritative.
Markdown line count is not a context-cost proxy and never blocks setup or validation; keep prompts
lean by removing duplication while preserving required safety and execution contracts.

## Unified PM lifecycle

Every host implements this non-Trivial lifecycle natively:

```text
classification with on-demand auxiliary document or agentmemory retrieval
-> Full: Grill Me coverage check -> xy-plan draft -> PM post-QA document projection decision
-> requirements approval (+ prototype choice for design-change UI) -> approved-plan/projection freeze
-> deterministic task dependency graph validation
-> dispatch all currently READY tasks -> unlock downstream tasks as dependencies resolve
-> per-writer build verification -> one integrated QA for the request dependency closure
-> fixed root/nested-repository scope + engineering/design-rule coverage validation
-> QA PASS -> controlled-document projection -> PM commit assessment -> memory closeout -> final report
```

The main session is the PM. It dispatches all currently `READY` tasks within the configured
agent, writer, path, and semantic-conflict limits; task completion immediately unlocks
eligible downstream work. A capacity delay never becomes a semantic dependency.

Bounded low-risk UI copy uses the existing Trivial route before UI classification: direct main-session
edit, applicable standards, local verification and scoped commit assessment. No repeated approval,
Grill Me, full plan/DAG, prototype choice, independent QA or document/memory churn is required.
The same correction across matching locale files is not Full merely because it touches several files.
Business/permission/privacy/destructive semantics, mandatory contract wording and unknown shared impact
are excluded; see [Trivial UI copy](product/WORKFLOW.md#trivial-ui-copy). Do not claim QA PASS when
only local verification ran. All non-Trivial UI and protected-path rules remain unchanged.

Project documents (`PROJECT.md`, feature details, and requirement plans) and agentmemory are
auxiliary information sources at task intake. The PM reads or queries only the smallest relevant
scope when a current feature fact, durable decision, engineering or design constraint, cross-session
background, or historical lesson is needed. Sufficient task information requires no document
retrieval or agentmemory start retrieval. `project.yaml` remains the workflow adapter. Every Writer
reads the compact STANDARDS index plus only applicable leaves: non-UI implementation uses
engineering, production UI uses engineering/design, and prototype design uses design.

Every Full request runs the self-contained `grill-me` coverage check. Complete requirements produce
no artificial questions; unresolved material gaps receive a bounded interview. The self-contained
`xy-plan` Skill then drafts exact files, interfaces, Task Packs, verification commands and expected
results, semantic locks, and a machine-readable graph. It borrows the exactness and self-review
methodology of Superpowers writing-plans without activating its execution, worktree, commit, or
Subagent workflows. Before requesting `requirements_approved`, the PM decides whether QA-verified
project or feature truth will need a closeout projection. `PROJECT.md` and active feature documents
remain the last QA-verified truth until integrated QA passes.

The PM validates and drives the same transient JSON snapshot using `task_graph_cli.py validate`,
`task_graph_cli.py ready`, and `task_graph_cli.py qa-ready`. This prevents each host from interpreting
dependencies, state, path conflicts, capacity, or QA readiness differently.
常用内部记录操作由同一 CLI 的 `update`、`task`、`fingerprints` 提供：按旧指纹校验后
更新当前快照、显式导出完整任务包、从已有回执核对指定文件；不再为这些机械操作反复
生成临时 Python。操作说明按需读取
[runtime-records.md](platforms/shared/skills/xy-workflow/references/runtime-records.md)。
查询仍只读，更新不自动派发、批准或判断完成；构建成功、可运行和独立 QA 要求不变。
Every Writer carries a fingerprinted `STANDARDS.md` index plus targeted leaves covering its owned
paths and applicable hard rules. QA independently resolves applicable leaves from the index and
actual diff; `qa_handoff_cli.py validate` prevents PASS when the Task Pack omitted a rule, fixed diff
scope is incomplete, or changed-path/rule evidence is missing. These machine
records remain internal; users receive concise natural-language decisions.

After QA PASS and any validated controlled-document projection, the PM evaluates whether the
request warrants local Git commits. It commits only the exact request-owned, QA-verified patch and
validated projection, never unrelated user changes; unsafe overlap is reported rather than broadly
staged. This is an automatic closeout decision, not a third user confirmation, and it never implies
push, merge, tag, or release authority.

That structured state remains internal. User messages never paste raw workflow YAML, the DAG JSON,
requirement fingerprints, task IDs/states, memory/provider schemas, or routine scheduler output by
default. Before approval, the PM provides only a concise natural-language goal, scope/non-goals,
workstreams and meaningful order, material risks, acceptance strategy, and controlled-document
update conclusion. For design-change UI it also provides one prototype recommendation with a short
reason and asks the user to select prototype design/update or direct implementation.
Any explicit affirmative reply records the internal `requirements_approved` gate; users are not
required to type that token. A design-change UI approval is complete only after the prototype
choice is also explicit; “按建议” is sufficient when the displayed recommendation is unambiguous.
Raw internals remain available only when explicitly requested.

User business confirmation defaults to two stages:

```yaml
business_confirmation_policy:
  default_gates:
    - requirements_approved
  ui_only_gates:
    - visual_approved
  additional_gates: exceptional
```

Every non-Trivial request asks once for `requirements_approved`. Non-UI work and proven
`UI-Conformance` work have no later business confirmation. `UI-Conformance` is limited to production
corrections with `surface_kind: production_ui`, `qa_scope: request`, `design_delta: none`,
`prototype_policy: not_applicable`, structured
resolved and SHA-256-frozen `design_authority_refs`, no design-workspace write or design-task
dependency, and integrated UI/accessibility QA. It skips the design Agent and prototype confirmation.
For `UI-Patch`, `UI-Page`, and `UI-Flow`, the PM recommends a policy and the user selects it as part
of requirements confirmation. Selecting `required` adds the matching design task and binds
`visual_approved` to each concrete changed HTML page and its verified dependency fingerprint.
Selecting `waived_by_user` for the exact affected surfaces has no prototype-design task, prototype write, or
visual Gate, but still receives full production UI/accessibility QA. Both choices are stored in a
scope- and requirement-bound `prototype_decision`; PM defaults are invalid. Baseline analysis, IA,
prototype verification,
plans, contracts, documentation, build verification, integrated QA, PM commit assessment, memory
projection, and closeout advance automatically from evidence; they do not ask for separate approval.
A material requirement or affected-UI-scope change invalidates the prototype choice and reopens
`requirements_approved`, while a material final
page dependency fingerprint change reopens only `visual_approved`.

The document model has one human entry point: `docs/PROJECT.md`. It lists current verified project
facts and active feature links without a line/byte cap or historical task log. Detailed current
feature truth lives under `docs/features/`; full revision history stays in Git. After QA verifies a
complete feature removal, PM performs one closeout update: remove its PROJECT row, rename its detail
to `*.removed.md`, mark the document historical with removal metadata, and repair current links.
Feature details include current functional and architectural rationale; a cross-feature solution may
have one shared detail in the same directory. There is no separate ADR category and no chronological
decision log. Replace obsolete explanations in place.

`docs/plans/` holds decided changes and enough current progress to resume unfinished work. Trivial
does not save a plan by default; Light saves only for actual pause/recovery/handoff or explicit user
request; Full is saved by PM after requirements confirmation (including applicable prototype choice)
and before first design/implementation dispatch. Saving Light does not invoke Full planning Skills.
One independent requirement owns one plan, updated in place for effective visual changes or QA rework.
PM replaces affected complete worker/QA inputs and reuses unaffected verified work; a recorded status
alone cannot revive approval or prove completion. See
[plan lifecycle](platforms/shared/skills/xy-workflow/references/plan-lifecycle.md).

This does not suppress architecture analysis or user choices. Reversible implementation
details proceed automatically and may be retained in feature rationale after verification. If a newly discovered
architecture choice materially changes scope, compatibility, migration cost, data
boundaries, or long-term constraints, the PM presents the options and reopens the existing
`requirements_approved` category by default. When the user explicitly requests another
decision point, or a material unresolved decision cannot safely be folded into an existing
confirmation, a task may declare a reasoned `additional_business_confirmation` with its
decision scope, evidence, options, and resume condition. It blocks only dependent DAG tasks
and never becomes a permanent default stage.

For design-change work with `prototype_policy: required`, the HTML prototype is the authoritative
visual-review artifact. The PM gives the user direct
links to the concrete changed pages; the root index alone is insufficient. The design task owns
deterministic static verification of structure, local dependencies, page contracts, controls, and
fingerprints. Prototype verification does not invoke Computer Use or browser automation by default;
only an explicit user request to automate the prototype, or diagnosis of a concrete prototype failure
reported by the user, permits the smallest scoped browser operation. The PM reviews current evidence
and, before user handoff, compares all five contract sections with the frozen approved requirements
and acceptance criteria. Omitted, invented, broadened, or conflicting behavior returns to the
designer. This semantic review does not invoke a browser; the PM does not repeat proven static checks
or supplement missing browser evidence.
After implementation, deterministic QA tooling may scan complete dependency bytes and recompute the
approved fingerprint, but the QA Agent reads only the exact contract and smallest relevant source
slice. It does not open or automate the prototype; missing or stale design evidence returns to the
designer. This does not prevent risk-based browser testing of the real production implementation. A
user-waived scope does not use the unchanged prototype as current authority.
The workflow must not generate, persist, attach, or present screenshots for visual approval. QA may
inspect an ephemeral rendered frame in browser-tool memory when necessary, but it must not become an
artifact or approval evidence. The workflow does not generate image assets unless the user explicitly
requests them; existing project assets may be reused.

Platform security prompts for destructive, production, paid, external-mutation, or
privileged operations remain mandatory and are outside the default business-confirmation policy.

Non-Trivial production work has one writer per owned path. Every writer returns real build
or test evidence. After all writers in the current request dependency closure finish, the
PM runs one integrated QA; unrelated project work neither blocks that QA nor needs to stop.
QA reports to the PM and does not modify production business code. For non-Trivial work, only a QA PASS permits
warranted controlled-document updates, PM commit assessment, memory closeout, and the final user report.

### Generated core workflow

```text
platforms/shared/skills/          # authoritative one shared source
  xy-workflow/                    # only main workflow entry
  grill-me/                       # Full-request requirements coverage/interview
  xy-plan/                        # self-contained exact draft planning + task graph
  xy-project-memory/              # optional agentmemory + docs fallback
  xy-build-verify/                # implementer evidence
  xy-qa-review/                   # independent QA base
  xy-prototype-verify/            # UI prototype and approval evidence

.agents/skills/xy-*/SKILL.md      # Codex and Antigravity generated copies
.claude/skills/xy-*/SKILL.md      # Claude Code generated copies
```

Core Skill entrypoints retain routing and essential boundaries. Read a linked branch only when its
stated task condition applies; internal schemas and detailed procedures live in `references/`.
Installers copy the complete trees and validate explicitly declared contract references, so a short
entrypoint does not remove approval, ownership, standards or QA rules. These are context-maintenance
choices, not invented platform line/token limits. Codex workers receive compact execution boundaries
instead of a repeated copy of the PM's entire global procedure; model and reasoning preferences stay
under user control.

PM, implementers and QA share the [verification scope policy](platforms/shared/skills/xy-build-verify/references/verification-scope.md).
Select checks by changed behavior, dependencies and mandatory project rules. Discovered commands are
candidates, not a requirement to run every suite. QA independently audits source and standards and
may reuse evidence after validating its inputs, dependencies and environment. Repeat or expand checks
only for a concrete change, failure, evidence gap, unresolved concern or explicit requirement.
生产交付要求受影响目标构建／编译成功，并具有最小可运行验证证据；纯文档／静态原型
按各自类型验证。验证策略区分局部修改、受影响模块和必要的全量回归；必需检查通过且证据仍有效后
停止，不在 Writer、QA、PM 或提交环节分别重复测试。保留强制 CI／Hook、独立 QA 与
worktree 集成验证；最终只汇报实际覆盖范围、结果和相关限制，不宣称未运行的全量通过。
Normal feedback stays concise; when a Skill causes a pause or extra confirmation, identify its exact
rule and practical effect rather than hiding the reason or dumping internal workflow records.

### Conditional worktree delivery

For substantive independent functional units, PM now assesses `parallel_worktrees` in the adapter.
`mode: auto` prefers verified isolation when useful; `off` retains existing scheduling. The default
`merge: confirm` asks once after completed work and integrated QA; explicit `auto` enables checked
local delivery without that final question. Neither mode pushes remotely or bypasses dirty work,
conflicts, changed target/candidate revisions, ownership or required evidence. Main-branch selection
uses actual repository facts, not an assumed branch name. Host-native isolation is preferred only
when its actual root/base and tool binding are verified; unsupported hosts safely fall back.

Read [worktree execution and delivery](platforms/shared/skills/xy-workflow/references/worktree-delivery.md)
only for that branch. `lib/worktree_cli.py` provides creation, exact Git scope inspection and guarded
fast-forward delivery; the existing DAG now includes revision-bound integration verification before
QA. Local PM transport checkpoints are not final QA/merge authorization. Ordinary Trivial/Light
tasks, prototype choice, standards and memory assessment remain unchanged. Runtime metadata stays
internal and useful recovery facts stay in the existing plan, not a second worktree ledger.

### Claude-native generated layout

- `AGENTS.md` is the shared compact instruction entry: essential boundaries and task-triggered
  navigation. The Claude-only section routes to its own on-demand integration details.
- `CLAUDE.md` contains only `@AGENTS.md`, using Claude's official import syntax without duplicating rules.
- `/xy-workflow` owns the complete non-Trivial route; no phase or compatibility command layer is installed.
- Every generated Custom Agent has the Claude `Skill` tool. Implementers preload
  `xy-build-verify`; UI preloads `ui-ux-pro-max` and `xy-prototype-verify`; QA preloads
  `xy-qa-review`.
- Additional QA specialist Skills are matched on demand from their descriptions. There is
  no local-Skill inventory scan or extra selection phase.
- A missing `ui-ux-pro-max` blocks UI design. Optional QA specialist gaps remain explicit;
  missing task-declared required Skills block QA PASS.
- `setup_claude.sh` merges only signed assist Hook entries in `.claude/settings.json`.
  User permissions, other Hooks, MCP, plugins and Claude Auto Memory settings remain unchanged.
- User-owned same-name Agent/Skill files are never overwritten. `--check` structurally
  compares managed artifacts with their sources and rejects stale or contradictory output.

#### 共享正文与 Claude 薄入口（2026-09-27）

`AGENTS.md` 是共用的精简规则入口；根目录 `CLAUDE.md` 固定只有一行 `@AGENTS.md`。
这是统一的当前安装方案，不增加旧版本分支或第二份规则。SessionStart 只作短恢复提醒，
不重复注入 AGENTS.md、Skill 正文或完整项目文档。
`.claude/agents/` 与 `.claude/skills/` 仍是原生角色和 Skill 目录；PM、确认、原型、QA、
worktree 流程以及 Codex、Antigravity 的入口均不变。

根据 [官方共享指令方案](https://code.claude.com/docs/en/memory#share-one-file-with-other-coding-tools)
及 [加载差异](https://code.claude.com/docs/en/memory#where-agents-md-differs-from-claude-md)：

- 使用实际 `@` 导入，不使用“请阅读 AGENTS.md”的普通文字，不复制正文。官方明确这种
  导入会去重，但被导入的正文仍占用上下文，不能把薄入口当作按需读取或节省正文 token。
- 不再依赖默认“没有 Claude 指令文件才回退到 AGENTS.md”的条件；`claude-md` 设置下
  也通过导入加载。组织的 `managed-only` 等策略仍可能排除项目入口，薄入口不绕过策略。
- 经 `CLAUDE.md` 导入会触发 `InstructionsLoaded`；安装器本身不添加或修改任何 hook。
- 根入口只导入同目录的 `AGENTS.md`，不递归导入子目录规则；项目有嵌套规则时应按
  [官方目录加载规则](https://code.claude.com/docs/en/memory#when-claude-code-reads-agents-md)
  核对其实际作用域，安装器不改写这些规则或用户设置。
- 在真实 Claude 会话运行 `/context` 确认入口加载。`--check` 只验证磁盘产物，不能证明
  当前会话已经加载，也不能证明模型执行效果。

新安装直接生成薄入口；已有共享正文的安装补上薄入口，单独安装 Claude 也会生成共享
基础规则区块。只接受缺失的 `CLAUDE.md` 或精确的一行 `@AGENTS.md`；不再自动转换旧版
正文入口，不创建旧入口迁移备份或保留旧运行模式。其他内容在预检时拒绝，原文件不动。
已有精确薄入口原样保留；发布失败仍回滚本轮入口修改。安装整体备份、用户文件保护和
所有权检查保留，它们是数据安全措施，不是旧版本兼容运行分支。

#### 目录化入口与按需加载（2026-10-02）

根 `AGENTS.md` 只常驻任务分级、关键确认、所有权、规范/QA 和输出边界，以及
带读取条件的流程索引。详细共用流程复用现有 `xy-workflow` 与其 references；
各平台 PM 细则位于 `.agent-workflow/platforms/<host>/references/pm-integration.md`，
当前 PM 仅在首次编排时读取自己的平台细则。Trivial 局部修改不预读整套流程。
同一上下文已完整读取且未改变的内容可复用；上下文缺失或规则变更时恢复所需部分。

这是一套内容的不同加载入口，不新增项目记忆文档体系，不改变需求确认、原型选择、
视觉确认、计划状态、并行隔离或 QA 收口。根入口不使用全文 include 来导入细则：
Claude 的 `@path` 和 Antigravity 的 `@[label](path)` 都会展开正文，不能用来省 token。
`CLAUDE.md` 仍只导入同目录的精简 `AGENTS.md`；Skills 继续分别安装到 Codex/Antigravity
的 `.agents/skills/` 与 Claude 的 `.claude/skills/`，不会因共用 AGENTS 而合并发现目录。

安装器通过显式契约标记完整检查入口和其详细规则；缺失、空白、错配、非法引用均拒绝
安装，注释不会要求宿主预载正文。校验仍保留安全读取和用户自有内容保护，不按固定
行数裁剪规则，也不再把原有的 8 KiB 自设目标当成平台限制。Codex 的 32 KiB 保护对应
官方默认配置，而非不可调整的模型上下文上限；真实会话加载及 Agent 判断需使用反馈验证。

Claude setup and official local diagnostics (`claude doctor`):

```bash
bash .agent-workflow/setup_claude.sh
bash .agent-workflow/setup_claude.sh --check
claude doctor
```

### Optional strict guard

```yaml
# project.yaml (optional)
deny_prefixes:
  - secrets/
  - production-keys/
```

```bash
GUARD_STRICT=1 bash .agent-workflow/scripts/guard.sh
```

## Native landing points

| Platform | PM instructions / entry | Roles | Core Skills |
|:---------|:------------------------|:------|:------------|
| Codex | `AGENTS.md` / `$xy-workflow` | `.codex/agents/xy-*.toml` | `.agents/skills/xy-*` |
| Claude Code | `CLAUDE.md` → `AGENTS.md` / `/xy-workflow` | `.claude/agents/xy-*.md` | `.claude/skills/xy-*` |
| Antigravity | `AGENTS.md` / `/xy-workflow` | `.agents/agents/xy-*.md` | `.agents/skills/xy-*` |

Codex uses repository Skills and project Agent TOML. Claude Code uses Custom Agent
frontmatter and the Skill tool, merging only owned assist Hook entries. Antigravity uses
official static Agent frontmatter and native tools. None of the three hosts requires prototype
browser automation for normal visual handoff; the PM retains approval orchestration, while each
`xy-qa` Agent remains strictly read-only.

Each installer is independently usable and checkable:

三平台默认接入可关闭的轻量辅助 Hooks，不新增审批/QA门禁或状态台账。配置/回调通过
不等于模型行为测试通过；Codex 仍须原生信任审查，AGY 不猜测任务轮次或压缩恢复。
详见 [Hooks 开关与验证边界](platforms/shared/HOOKS.md)。

```bash
bash .agent-workflow/setup_codex.sh --preflight
bash .agent-workflow/setup_codex.sh
bash .agent-workflow/setup_codex.sh --check
bash .agent-workflow/setup_claude.sh --preflight
bash .agent-workflow/setup_claude.sh
bash .agent-workflow/setup_claude.sh --check
bash .agent-workflow/setup_antigravity.sh --preflight
bash .agent-workflow/setup_antigravity.sh
bash .agent-workflow/setup_antigravity.sh --check
```

Aggregate setup preflights every selected host before the first project write. Limit it
to one host with `--only=claude`, `--only=codex`, or `--only=antigravity`.

## Maintain

- Discipline → `product/WORKFLOW.md`
- Role coding norms → `roles/xy-*.md`
- Core workflow Skills → `platforms/shared/skills/`
- Host adapters → `platforms/codex/`, `platforms/claude/`, `platforms/antigravity/`
- 修改源包也先选与变更相关的现有测试模块／用例。文案或局部指令变更只核对受影响
  的合同、引用和必要的宿主生成，不默认执行整包回归；通过且无新缺口后停止。
- Full pack regression, only for justified broad impact or an explicit requirement (from the pack directory):
  `bash lib/python_runtime.sh -m unittest discover -s tests -v`.
  Discovery includes scheduler, runtime, standards, prototype and installation regressions;
  individual `scripts/test_*.sh` entries are focused checks, not the complete suite.
- 要把已验证的源包变更应用到项目时，再对用户指定并授权同步的目标运行 `install.sh`；
  仅优化源包不自动重装或同步项目。

## Portable docs scaffold

Every host setup and `setup_all.sh` creates only missing or empty current-profile documents from
`templates/docs/` and never overwrites non-empty user content:

| Path | Purpose |
|------|---------|
| `docs/STANDARDS.md` | Concise index of enforceable engineering/design rules |
| `docs/standards/*.md` | Direct engineering leaves, including repository baseline and upstream boundaries |
| `docs/standards/DESIGN_*.md` | Direct design foundations/components or platform leaves; UI profile only |
| `docs/PROJECT.md` | Current verified project directory and active feature links |
| `docs/features/` | Current detailed feature truth; `*.removed.md` is historical only |
| `docs/plans/` | Lazy PM-owned plans by task level, not placeholder files or implemented feature truth |
| `docs/standards/prototype/` | Lightweight `index.html`, `prototype.css`, and direct `<page>.html`; resource directories only when needed |

`templates/docs/FEATURE.md` is the PM-owned shape for a newly approved feature document. The legacy
`docs.contracts` / `docs.progress` schema and its `SPEC.md` / `STATUS.md` authorities, plus the old
single-file `ENGINEERING.md` / `DESIGN_SYSTEM.md` authorities, are unsupported:
upgrade current truth directly into `PROJECT.md` plus feature documents and remove the old authorities
instead of installing a compatibility bridge or retaining dual truth.

Plans and notes are lazy: setup preserves existing content but does not create empty placeholder
trees or plans. `templates/docs/PLAN.md` is an optional writing aid, not a mandatory form for small work.

Normative leaves are direct children of `docs.standards_root`. Design leaves use the `DESIGN_`
filename prefix and `- Domain: design`; engineering leaves declare `- Domain: engineering`.
The index groups applicable leaves, and runtime/QA contracts bind their domain, rule IDs and hashes.
The shallow layout does not reduce required standards reads or upstream protection.

This is a direct schema upgrade: replace `docs.adr` with `docs.plans`; consolidate useful ADR rationale
into the related feature or shared architecture detail. Move engineering leaves to the standards root,
design leaves to `DESIGN_*.md`, and prototype pages to `standards/prototype/`; repair relative URLs,
index links and fingerprints. Classify old design reference content as actual rules, an unfinished
plan, or verified feature truth before moving it. Do not infer implementation from an old proposal.
Setup never deletes or overwrites populated project documents; migrate old project content explicitly
with a backup before reinstalling. Keeping old/new authorities active together is unsupported.

New project: launch `install.sh` → drag or pass the project path → inspect the automatic
preflight and `--check` result → fill the scaffolded docs. Normal setup automatically
derives `memory.project_id` from the project directory name when the template placeholder
is still present.

See also `templates/project.yaml.example`.

## Optional host wiring

The project adapter never installs agentmemory, snapshots personal memory, or changes
global host configuration. Operators who have the service and want host tools may run:

```bash
agentmemory connect codex
agentmemory connect claude-code
```

These explicit commands expose tools to each host; action Skills are installed separately,
and the hosts must be reloaded or restarted. Setup and `--check` remain usable when the
service is offline through the checked-in docs fallback.

For this workflow, agentmemory is optional. Claude setup never runs either connect command.
Claude Auto Memory may remain enabled as a user-managed feature, but it is untrusted
background context: it is not an audited `memory_context` provider, approval, permission,
historical-hit proof, or substitute for current project documents.

`memory.project_id` is a stable project slug unique to the project, not a filesystem
path. Normal setup automatically derives `memory.project_id` from the project directory
name and atomically writes it to `project.yaml` when the template placeholder is still
present. Configured IDs are never overwritten; edit the value manually when a custom
memory namespace is required. `--check` and `--preflight` never initialize the value and
remain strictly read-only. With
`memory.isolation: strict`, all three host workflows use agentmemory only when the available tools
can enforce that project filter and return matching project provenance. Otherwise they
automatically use the checked-in docs fallback and call neither provider recall nor save.
