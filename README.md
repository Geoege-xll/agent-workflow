# Agent Workflow Pack 2.0

面向项目的原生多Agent工作流，发行版本为 **2.0.2**。使用 `awf-cli --version` 核对实际中央程序
版本与源码位置；项目工作流通过原安装入口显式升级。仅Light／Full及schema_version:2，
不兼容旧任务／交接格式；用户文件、已有成果和必要证据保护继续有效。
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

可通过公共 Tap 安装其当前声明的版本；新版本需完成[发行及 Tap 更新](docs/homebrew.md#首次发布)：

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

新版入口支持只读来源诊断：`awf-cli --version` 显示构建版本和实际中央源根，未打包源码显示
`源码未打包`，不会根据 README 或目录名宣称已发布版本。可同时运行
`bash /path/to/agent_workflow/workflow.sh --version` 与 `type -a awf-cli` 核对是否仍启动旧程序。
旧版入口若不认识 `--version`，请按 [Homebrew 说明](docs/homebrew.md) 检查链接和已安装版本；
更新源码不会改变既有二进制、Cellar 载荷或公共 Tap。

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
  已有明确推理能力时按目录限制档位，不启用涉及自动委派的 `ultra`。
- Claude Code 读取当前模型、别名映射及代理工具写入的 `modelPicker.options`。
  缓存中的 `modelSettings` 仅为偏好，不能推断模型推理能力。
- Antigravity 静态角色使用官方 `inherit / flash / pro` 档位，不猜测内部模型 ID。

模型与推理档位可独立修改。模型能力未知时，Codex 可写入 `none / minimal / low / medium /
high / xhigh / max`，Claude Code 可写入 `low / medium / high / xhigh / max`，也可选择继承。
这些是宿主允许的配置值，不代表所选模型已支持、模型 API 调用成功或已经通过服务验收。
损坏或嵌套过深的来源显示读取失败；CLI 只返回安全投影，TUI 保留其他项目和宿主的未应用草稿。

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
# Claude 已知配置覆盖关系；保留配置值与来源，不冒充实际会话运行结果。
awf-cli roles --platform claude --project /path/to/project --effective
# 默认只读配置，不启动宿主；--probe 才显式执行固定的 --version 查询。
awf-cli doctor --project /path/to/project
awf-cli doctor --platform claude --project /path/to/project --probe
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

`doctor` 区分官方文档能力、源包目标事件、当前可见配置与显式探测到的版本；不根据版本号
推定 Hook 已获信任、事件已经触发或模型实际可用。最低支持版本没有官方依据时保留未知。
默认诊断不执行宿主；`--probe` 只运行 `codex/claude/agy --version`，不登录、不更新、不调用模型，
不回显宿主原始 stdout/stderr。宿主程序自身仍可能产生启动缓存，CLI 版本也不代表 App/IDE 版本。

Claude 来源页及 `roles --effective` 白名单投影模型强制覆盖、全局 effort 与子 Agent 默认 effort，
隐藏无效值和非相关环境变量。普通本地会话通常由设置文件 env 覆盖 shell 的同名值；
组织策略、`--settings`、调用参数、运行中会话和特殊 env 处理不在本地推导范围内。
具名角色模型优先级按 Claude Code 2.1.251+ 合同解释，强制模型覆盖要求 2.1.257+；
角色显式 `model: inherit` 仍高于普通子 Agent 默认模型；默认 effort 要求 2.1.316+，
不会因为配置里出现该变量就认定旧客户端支持。fork/后台模式的变化不使模型草稿失效。

Claude 可选能力独立放在安装源或项目 `.agent-workflow/project.yaml` 的 `claude_options`，
不扩展模型管理器的可写字段；默认空窗口表和 `inherit` 都保持宿主原有选择。例如：

```yaml
claude_options:
  auto_compact_windows: {"xy-qa": 200000, "xy-backend": 300000}
  block_writes_outside_working_directories: true
```

修改后运行 `bash .agent-workflow/setup_claude.sh`，再用 `--check` 检查生成一致性。
角色窗口要求 Claude Code 2.1.296+，只接受 100000..1000000 的完整整数，角色字段不能写
`200k`。它仅能降低原本继承的窗口，作为 `--agent` 主会话角色时不生效；全局
`CLAUDE_CODE_AUTO_COMPACT_WINDOW` 通常优先（环境变量缩写要求 2.1.304+）。
`roles --effective` 显示请求值、来源及未知的实际窗口；不会把字段存在当成真实压缩验收。
窗口、后台模式及写入保护变化都不会无故废弃模型草稿。

写入保护需要 Claude Code 2.1.314+，启用时只合并
`permissions.blockWritesOutsideWorkingDirectories: true`，保留其他权限和用户 Hooks。
项目或 local 层已有 false/无效值时预检停止并保留文件。该设置独立于 Hooks 开关：
`workflow_hooks.mode: off` 不会关闭它；回到 `inherit` 也不会撤销已启用的原生保护，
如需关闭请直接管理原生设置。本包不写 false、不修改全局权限、不自动增加工作目录。
它约束 Write/Edit/NotebookEdit 的工作目录外路径，不覆盖 Bash，也不等同于每个任务的
`owned_paths`；隔离 worktree 的实际工作目录仍需在目标会话核验。`doctor` 只报告当前可见
配置及版本门槛；managed/调用时设置、实际工作目录和运行中行为保留未验证状态。

压缩恢复继续复用 `SessionStart(compact)`；不增加 PreCompact/PostCompact 日志、门禁或
重复恢复注入。Claude 的这两个事件会忽略恢复指令所需的上下文输出；Codex 的压缩事件
也不能用普通 stdout 文本替代原生恢复入口。详见 [Hooks 边界](platforms/shared/HOOKS.md)、
[Claude 窗口合同](https://code.claude.com/docs/en/sub-agents#auto-compaction)、
[环境变量合同](https://code.claude.com/docs/en/env-vars)、
[写入保护发布记录](https://code.claude.com/docs/en/changelog#21314)。

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
升级验收通过后仅自动轮换具有创建时文件内容及 POSIX 权限位（mode）指纹且核对一致的旧运行时备份，保留最近一份。
指纹包含项目自有的 `project.yaml`、清单中的附加字段及附加文件；内容／mode 改变或缺少原始指纹的历史备份保留并提示人工核对。
该指纹不覆盖扩展 ACL、所有者及 xattr；依赖这些元数据保留恢复状态时，应另行保留所需备份。
Windows 尚无经过原生验收的 ACL 权限指纹，旧运行时备份暂不自动轮换删除，并明确提示保留原因。
指纹登记属于新运行时验收后的维护：登记失败或取消会保留旧备份并跳过轮换，不回滚已经验收的安装。
首次安装或升级时，若 `project_name` 仍是默认占位名 `MyProject`，安装器会在暂存配置中将其替换为目标项目根目录名
（例如 `/path/to/ParentsKit` → `ParentsKit`），保留原大小写、中文和空格；已明确配置的其他名称保持不变。
名称初始化不修改源包配置或已有的 `memory.project_id`；新生成的文档使用真实名称，已有非空项目文档不批量改写。

通用规则正文统一随运行时内置 Skill 安装：工程规则在 `xy-code-standards/references/rules.md`，
设计规则在 `xy-ui-design/references/foundations-rules.md`、`components-rules.md`。
项目只维护已批准的特有规范；存在实际特有叶时才维护有内容的 `docs/STANDARDS.md` 薄索引，
无特有叶时不生成 GENERAL、默认设计叶、UPSTREAM 占位或空索引。既有说明索引可原样保留。
迁移仅整理可精确识别的旧通用内容，保留项目特有规则、修改、权限及并发/回滚保护；
无法确认归属或语义冲突时报告受影响项，不把用户规范当模板覆盖或用近似语义放过重复ID。
规则来源变化须刷新当前指纹和任务包，不增加业务确认或无依据的全量测试。

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
| `platforms/shared/skills/` | 九个宿主共用的内置 Skill；三宿主使用同一份源资源 |
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

每个宿主的Full请求沿用以下完整生命周期；Light使用下面的按需分支：

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

Light／Full默认派对应原生subagent。只有用户明确指定PM本身亲自实施当前范围才改变实施者；
PM正常职责限于协调和其拥有的文档。普通“优化／开始／继续”及摘要不产生例外，原等级要求保留。
见[实施所有权与PM例外](product/WORKFLOW.md#implementation-ownership)。

Light派发前判断目标、消费者、范围与风险，使用当前自包含2.0单任务包并做最小充分验证；
不强制Full规划、DAG、保存计划、重复确认或独立QA。交接时评估必要独立审计、文档与记忆，
没有需要不制造记录或QA PASS。普通低风险UI文案可用此分支，多语言文件数量不自动升级；
实际UI文案仍用production_ui＋UI-Conformance及真实已解析冻结权威，工程／设计规范不省略；
任意设计／交互变化都Full。业务／权限／隐私／破坏操作语义和未知共享影响除外，见[Light UI copy](product/WORKFLOW.md#light-ui-copy)。

稳定别名绑定模块与角色职责。独立任务按需新原生实例／新ID，只交当前目标范围、代码／工作区
事实、适用规范、可信授权、验收证据及未决事项；不复制完整PM／兄弟会话或fork父历史。
同任务连续实现、短返工及同轮原Reviewer差量复查可续，不能称resume／compact已清空历史。
交付接收、必要验证／QA和证据保护后及时原生结束；能力缺失只退役阻止误派，不称销毁、清空
或释放未确认容量，退役不释放仍活动锁。按宿主真实运行／打开线程口径安排后续QA／集成容量，
不预热全部别名、不填满上限，也不按简单LRU淘汰仍执行／未交证据／必要复查实例。
AGY kill前保护临时worktree与唯一日志；完整规则见[实例生命周期](product/WORKFLOW.md#agent-instance-lifecycle)。

Project documents (`PROJECT.md`, feature details, and requirement plans) and agentmemory are
auxiliary information sources at task intake. The PM reads or queries only the smallest relevant
scope when a current feature fact, durable decision, engineering or design constraint, cross-session
background, or historical lesson is needed. Sufficient task information requires no document
retrieval or agentmemory start retrieval. `project.yaml` remains the workflow adapter. Every Writer
读取适用内置规则及项目特有叶，项目索引存在才读；non_ui使用工程规则，
production_ui使用工程/设计，原型使用设计规则。不因索引物理缺失而跳过内置规则。

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
常用内部记录操作由同一 CLI 的 `init`、`update`、`task`、`fingerprints` 提供：根据 PM
明示决定初始化新图、按旧指纹更新当前快照、显式导出完整任务包、从已有回执核对指定
文件；不再为这些机械操作反复生成临时 Python。`init` 复用原校验器、拒绝覆盖已有图，
不推导批准或适用规范。安装态输入须显式设置 `adapter_path: ".agent-workflow/project.yaml"`：

```bash
bash .agent-workflow/lib/python_runtime.sh -X utf8 .agent-workflow/lib/task_graph_cli.py init \
  --root "${project_root:?set actual project root}" \
  --input "${workflow_decisions:?use PM decisions JSON}" --output "${workflow_graph:?set new graph path}"
```

完整输入字段与操作说明按需读取
[runtime-records.md](platforms/shared/skills/xy-workflow/references/runtime-records.md)。
查询仍只读，更新不自动派发、批准或判断完成；构建成功、可运行和独立 QA 要求不变。
宿主可读导出的完整 Task Pack 文件时，可交接确切文件引用、SHA 与简短变化摘要，接收方
独立完整读取当前包；同一实例已读完同版本正文时直接复用，文件只是另一种传输方式。
宿主不可读时仍发送完整包，不能仅发差量。
每位Writer携带覆盖拥有路径的当前内置来源、适用规则ID及项目特有规范，索引存在时绑定真实SHA。
无项目叶且索引缺失时保留配置路径/null指纹；QA按当前内置来源、存在的项目索引及实际差异独立判定； `qa_handoff_cli.py validate --input RESULT --task-pack CURRENT_QA_PACK` prevents PASS when the Task Pack omitted a rule, fixed diff
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

Full请求在规划后使用一次`requirements_approved`；Light已有明确范围授权时不重复确认。 Non-UI work and proven
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

`docs/plans/` holds decided changes and enough current progress to resume unfinished work. Light saves only for actual pause/recovery/handoff or explicit user
request; Full is saved by PM after requirements confirmation (including applicable prototype choice)
and before first design/implementation dispatch. Saving Light does not invoke Full planning Skills.
One independent requirement owns one plan, updated in place for effective visual changes or QA rework.

Full 正式需求审阅使用 HTML：模型只维护 `docs.plans/<name>.md`，同目录 `.html` 由固定
`answer-me-with-html` CLI 生成。批准前草案只放当前请求 scratch；批准后保存正式原稿再生成。
需求用稳定 REQ 编号链接具体原型页/状态，设计交接后 PM 写回同一原稿并重渲染；页面状态
不构成批准，历史 MD/HTML 不成为当前功能真相。用法、受控语法及草案链接基准见
[需求 HTML 交付](platforms/shared/skills/xy-plan/references/requirement-html.md)。适配器需现有
Node.js >= 20，三个宿主共用安装态 `lib/requirement_html.py`，无需安装上游 Skill 或全局依赖。
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
and acceptance criteria. 设计Agent先在同一交接完成需求覆盖、规范符合性、交付一致性自检，
沿用static_checks/blocking_findings/result；不新增独立原型QA、报告、审批或默认浏览器/截图步骤，
用户最终确认，生产功能QA保留。Omitted, invented, broadened, or conflicting behavior returns to the
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

Light／Full都坚持一条拥有路径一个Writer；Full继续以下请求QA链。 Every writer returns real build
or test evidence. After all writers in the current request dependency closure finish, the
PM runs one integrated QA; unrelated project work neither blocks that QA nor needs to stop.
QA reports to the PM and does not modify production business code. Full中只有有效QA PASS才允许
warranted controlled-document updates, PM commit assessment, memory closeout, and the final user report.

### Generated core workflow

```text
platforms/shared/skills/          # authoritative one shared source
  xy-workflow/                    # only main workflow entry
  grill-me/                       # Full-request requirements coverage/interview
  xy-plan/                        # self-contained exact draft planning + task graph
  xy-project-memory/              # optional agentmemory + docs fallback
  xy-build-verify/                # implementer evidence
  xy-code-standards/              # 代码实现与只读审查的共用方法
  xy-ui-design/                   # 高保真设计与按既有权威消费的条件规则
  xy-qa-review/                   # native-review-first project acceptance
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

`xy-code-standards` 提供实现判断和只读审查方法，`xy-ui-design` 提供规范落实、一致性与
高保真交付方法与通用规范正文。三份内置来源、已批准项目特有规则及当前指纹构成适用权威；
参考项目的满意评价不构成通用颜色、材质或审美授权。Light同样适用代码方法，按当前包与实际风险交接。
角色常驻职责与权限保留，条件细节从 Skill 读取；字符／字节体积变化不等于真实 token 节省。

Codex 角色中的发现上下文复用原发现器，将相同技术栈／证据和命令模板分组，再保留
每个模块的 root、命令 cwd 与证据基点映射；差异化参数、用途和证据仍分别保留。
这只去除重复事实，不裁剪模块、不修改角色权限，也不自动执行候选验证命令。需要
核查角色完整映射时可只读运行：

```bash
bash .agent-workflow/lib/python_runtime.sh -X utf8 .agent-workflow/lib/project_profile_cli.py \
  context .agent-workflow . xy-backend
```

PM, implementers and QA share the [verification scope policy](platforms/shared/skills/xy-build-verify/references/verification-scope.md).
Select checks by changed behavior, dependencies and mandatory project rules. Discovered commands are
candidates, not a requirement to run every suite. QA independently audits source and standards and
may reuse evidence after validating its inputs, dependencies and environment. Repeat or expand checks
only for a concrete change, failure, evidence gap, unresolved concern or explicit requirement.
生产交付要求受影响目标构建／编译成功，并具有最小可运行验证证据；纯文档／静态原型
按各自类型验证。验证策略区分局部修改、受影响模块和必要的全量回归；必需检查通过且证据仍有效后
停止，不在 Writer、QA、PM 或提交环节分别重复测试。保留强制 CI／Hook、独立 QA 与
worktree 集成验证；最终只汇报实际覆盖范围、结果和相关限制，不宣称未运行的全量通过。
补负控或修复失败分支时按已有最小测试节点／子场景执行，复用其他有效分支；混合入口
不可拆须说明原因，预期红不能掩盖夹具／执行失败。详细判断沿用上述验证策略。
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
QA. Local PM transport checkpoints are not final QA/merge authorization. Ordinary Light
tasks, prototype choice, standards and memory assessment remain unchanged. Runtime metadata stays
internal and useful recovery facts stay in the existing plan, not a second worktree ledger.

### Claude-native generated layout

- `AGENTS.md` is the shared compact instruction entry: essential boundaries and task-triggered
  navigation. The Claude-only section routes to its own on-demand integration details.
- `CLAUDE.md` contains only `@AGENTS.md`, using Claude's official import syntax without duplicating rules.
- `/xy-workflow` owns the Light／Full routes; no phase or compatibility command layer is installed.
- Every generated Custom Agent has the Claude `Skill` tool. Implementers preload
  `xy-code-standards` and `xy-build-verify`; UI preloads `xy-ui-design`, `ui-ux-pro-max` and `xy-prototype-verify`; QA preloads
  `xy-qa-review`.
- 生产 UI 实现按 `surface_kind: production_ui` 读取设计 Skill 的适用规则；QA 按实际代码／UI
  审查面只读消费共用方法。预载不等于执行；`standards_only` 不运行原型验证，读取不授予写入权、
  恢复原型门槛或增加确认。纯文档／后端 QA 不预载 UI 全文。
- Additional QA specialist Skills are matched on demand from their descriptions. There is
  no local-Skill inventory scan or extra selection phase.
- QA uses the host's native code-review capability first, then one proven installed review Skill,
  then the internal procedure only on technical unavailability. The same reviewer verifies native
  findings and supplements project acceptance; it does not repeat a complete generic review.
  `review_method` binds actual capability, permissions, model/effort, fixed scope and fallback
  evidence. Its validation does not prove execution by itself. Current-host invocation constraints
  live in `platforms/<host>/references/pm-integration.md`; UI and design checks load only when applicable.
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
当前PM首次编排时只读自己的平台细则；Light只读适用分支，不预读整套Full流程。
同一实例上下文已完整读取、版本未变且仍可用的任务包／Skill／规范直接复用；缺失、
截断、压缩或变化时只恢复受影响内容，保留显式重读要求。完整边界见下述长文读取说明。

每位 Agent 仍须独立完整读取其必需 Skill、指令及适用规范。长文应分开读取，使用连续
页直到 EOF，避免把多个长返回挤进一个被截断的工具结果。可选只读工具
`context_read.py` 返回有界文本、连续字符位置、完整文件 SHA-256 和明确的
`next_offset`／`eof`；续页必须携带同一 SHA，文件变化时拒绝继续拼接。默认页为
6000 字符、最多 24000 字符，采用字符预算而非精确 token 上限；须为完整 JSON 预留
宿主回包空间，必要时减小页大小。它复用 4 MiB 安全读取边界，保留中文、长单行和
CRLF，不写读缓存／状态，也不增加必跑门禁或读取记录。机器指纹不能证明模型已读；
普通项目文档仍按需定位相关章节。具体调用见
[长文完整读取](platforms/shared/skills/xy-workflow/references/runtime-records.md#完整读取必需长文)。

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

按需复用原生能力的操作路径集中在
[运行记录工具](platforms/shared/skills/xy-workflow/references/runtime-records.md#原生能力观察用量与同-agent-续用)：
doctor 区分文档、明确来源观察和运行未验证；native_usage 读取显式本地导出并保留原生
计数语义；2.0图／单包按模块职责绑定agent_alias，派发后agent_ref绑定真实ID且不可覆盖；
continuation只建议同任务等待／续用，退役／取消／未知／失效／跨宿主不得自动恢复。ID不证明
批准、存活或完成；不新增Agent池、runner或第二状态账本。
[QA 输入合同](platforms/shared/skills/xy-qa-review/references/inputs.md#原生结构化交接)
提供2.0 schema／extract；validate与extract必须传当前--task-pack，以handoff_ref绑定当前
QA任务、别名、原生ID和包SHA。Full只导出本任务及必要权威，Light同形单包无需DAG。
各宿主差异见下列PM integration，不因工具存在新增门禁或自动启用可选模式。

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
- 角色职责与权限 → `roles/xy-*.md`；共用代码／设计方法 → `xy-code-standards`／`xy-ui-design`
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
| `docs/STANDARDS.md` | 存在实际项目特有规范时维护的薄索引；既有说明索引保留 |
| `docs/standards/*.md` | 实际项目特有工程规范、保护边界等，不复制内置通用正文 |
| `docs/standards/DESIGN_*.md` | 实际采用的项目设计值、组件变体与平台差异；无差异不创建 |
| `docs/PROJECT.md` | Current verified project directory and active feature links |
| `docs/features/` | Current detailed feature truth; `*.removed.md` is historical only |
| `docs/plans/` | Lazy PM-owned Markdown + same-name derived HTML; intended changes/recovery/history, not feature truth |
| `docs/standards/prototype/` | Lightweight `index.html`, `prototype.css`, and direct `<page>.html`; resource directories only when needed |

`templates/docs/FEATURE.md` is the PM-owned shape for a newly approved feature document. The legacy
`docs.contracts` / `docs.progress` schema and its `SPEC.md` / `STATUS.md` authorities, plus the old
single-file `ENGINEERING.md` / `DESIGN_SYSTEM.md` authorities, are unsupported:
upgrade current truth directly into `PROJECT.md` plus feature documents and remove the old authorities
instead of installing a compatibility bridge or retaining dual truth.

Plans and notes are lazy: setup preserves existing content but does not create empty placeholder
trees or plans. `templates/docs/PLAN.md` is an optional writing aid, not a mandatory form for small work.
当前恢复／交接简报按[计划生命周期](platforms/shared/skills/xy-workflow/references/plan-lifecycle.md)
原地替换为当前状态与下一步，不逐批累加完成明细；必要基线引用现有计划、功能和完整证据。
先确认原始批准、完整日志与唯一历史可恢复并修复引用，无法安全移交则保留原文及历史边界；
不新增归档树、简报副本或硬长度门槛。

项目特有叶仍直接位于 `docs.standards_root`：设计叶保留 DESIGN_ 前缀及 Domain: design，
工程叶声明 engineering；通用正文从三份精确内置来源读取，内置路径不扩大项目写权限。
配置的 index_path/root 始终保留；无项目规则叶且索引物理缺失时 index_fingerprint 为 null，
索引实际存在则记录真实SHA。init/文档校验检查文件系统，纯JSON图校验不冒称已核对文件存在性。
来源、领域、稳定ID、覆盖和指纹检查继续执行，不能把可选索引解释成可跳过规范。

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
