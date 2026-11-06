# Agent Workflow Pack 2.1

面向项目的原生多Agent工作流，当前源码版本为 **2.1.0**，本次变更尚未发布到 Homebrew 或 npm。
版本唯一来源为 `product/VERSION`；使用 `awf-cli --version` 核对实际中央程序的版本与来源。
2.1 采用普通中央安装，不提供旧版本兼容升级。仅Light／Full及schema_version:2，
不兼容旧任务／交接格式；用户文件、已有成果和必要证据保护继续有效。
Keep this installer folder anywhere and select a project when launching it — works with
**Claude Code / Codex / Antigravity**.

## Windows 项目安装（npx，本地准备版）

Windows 方案只做**在项目目录执行 `npx … init` 安装工作流**，不提供 TUI、WinGet 或全局管理器。
前置条件为 Windows 10/11 x64、本地 NTFS、Node.js LTS/npm 和完整 Git for Windows；不依赖 WSL，
不需要预装 Python，不修改 PATH、profile、ExecutionPolicy 或 Git 全局配置。

npm 包目前 `private: true`，**尚未发布，尚未通过原生 Windows 安全、恢复与端到端验收**。
源码、打包与 npx 项目入口共用中央运行时服务；当前 Windows 安全文件系统后端尚不支持
受管 Skill 的锚定软链发布，因此会在创建项目资源或中央状态前明确拒绝，不会自动退回完整复制。
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

可通过公共 Tap 安装其当前声明的版本；本地 2.1.0 尚未发布，Tap 不会因此自动改变。
发行流程见 [Homebrew 说明](docs/homebrew.md#发布边界)：

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

入口支持只读来源诊断：`awf-cli --version` 从唯一版本源显示版本和实际中央源根，并区分源码与
构建发行载荷；源码版本不代表远端已发布。可同时运行
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
顶部显示当前宿主及全部范围的未保存草稿数，草稿以 `●` 标记；没有草稿只表示没有待保存编辑，不代表配置已经同步或验收。
项目条目按名称、状态及固定版本分行，条目间有分隔。主界面始终显示选中项目的工作流状态和 `o` 启用、`p` 停用入口；
两个动作都先读取服务的只读预览，再按 Enter 确认。状态待刷新或存在冲突时以预览诊断为准，不直接执行启停。
底部保留状态及最多两行主要操作提示，完整键位按 `?` 查看。
80 列以上并排显示，较窄终端使用 Tab 切换项目与角色区域；55 列 × 16 行收起辅助详情。
支持默认终端背景；无颜色或不支持默认背景时回退为粗体、反色和文字提示。

项目添加和启用是两个明确动作：添加默认只登记已存在目录，启用才建立三宿主原生入口。
CLI 可用 `add <path> --enable` 一次完成；TUI 消费相同项目计划和业务服务。
TUI 按 `a` 输入目录，回车后选择默认“仅登记”或“登记并启用三宿主”，再次回车读取只读预览，
核对后再回车应用。Esc 可逐层返回；预览前后都不会提前登记或安装。
已有中央项目默认沿用当前固定版本；导入和切换版本均须显式执行，保留项目配置和旧任务 pin。
源包可以集中存放，通过上方命令从任意当前目录启动，无需复制到项目内，也无需先在项目目录运行。

| 按键 | 操作 |
| --- | --- |
| ↑ / ↓ | 选择项目、角色或弹层选项；搜索输入时选择匹配项 |
| Home / End | 列表首尾；文本页页首 / 页尾；输入区行首 / 行尾 |
| PageUp / PageDown | 列表或文本页翻页，搜索输入期间也可翻页 |
| Tab / Shift+Tab | 正向 / 反向切换项目列表和角色表 |
| / | 搜索当前列表的名称、ID 或项目路径；Enter 接受筛选，再按 Enter 才确认 |
| : | 按中文操作名或英文别名搜索命令；不可用操作显示原因，写操作仍走原确认流程 |
| Enter | 打开选中项目的角色表；在角色表按当前列进入模型或推理编辑，左右键切列 |
| m / e | 选择模型 / 单独选择推理；模型确认后继续选推理，再 Enter 暂存，尚未写入配置 |
| 1 / 2 / 3 | 切换 Codex、Claude Code、Antigravity |
| s | 保存预览：核对当前项目及平台的草稿，Enter 确认后才备份保存；Esc 返回保留草稿 |
| u | 丢弃当前角色草稿，重新读取基线；保留其他角色和项目的草稿 |
| g | 启停、导入当前来源并启用、中央版本、条件恢复、项目/三宿主详情、删除登记、模型备份及本地来源 |
| o / p | 预览启用 / 停用选中项目的工作流，再按 Enter 确认；不终止已运行任务 |
| a | 登记项目：输入目录，选择登记方式，读取预览后再确认；默认仅登记 |
| r | 按需刷新本地模型目录及角色设置，保留未应用草稿 |
| Esc | 取消搜索输入并恢复原选择；已有筛选时先清除，再逐层返回 |
| ? / q | 帮助 / 退出；有任何项目或宿主的草稿时先确认放弃 |

路径输入支持 `← / →`、`Home / End`、`Delete / Backspace` 和 `Ctrl+U` 清空；长路径围绕光标横向滚动。
搜索、命令和路径输入中的 `q/s/u/o/p/1/2/3/?/:` 都作为正文，不触发全局操作。鼠标单击仅聚焦或选中，仍需 Enter 确认。
刷新或切换宿主时尽量按角色 ID 保持选择；被外部移除但仍有草稿的角色显示“已移除”，可用 `u` 单独丢弃。
小窗口退出和空闲 Ctrl+C 同样保护全部草稿；提示无法完整显示时禁止盲确认，需放大窗口。
选择、暂存和保存是不同阶段：选择器中 Esc 取消本次选择，暂存后按 `s` 才进入保存预览；无改动不会写入。
保存执行中显示真实任务状态，服务完成并验收后才提示项目、宿主及保存成功；失败或冲突保留草稿和诊断。
模型目录暂时失败或来源失效后，重新进入模型／推理编辑会复核并有界重试；稳定成功目录继续复用。
旧来源草稿不会自动更新来源基线，仍须重新确认选择或按 `u` 丢弃。绘制、保存预览和事务内的来源守卫不会重启原生目录进程。
管理菜单的中央版本列表可按 `i` 查看完整内容 ID、清单摘要与核心路径；回到列表按 Enter
只读取切版预览，再次确认才应用。删除登记也必须经过停用预览；冲突时保留项目及登记并展示诊断。

项目列表合并独立登记记录和默认桌面目录的直接子项目；不递归读取业务代码、Git worktree 或会话。
使用 `--scan-root /path/to/projects` 指定扫描目录。管理状态及模型备份默认保存在
`~/.config/agent-workflow`，可通过 `--state-dir` 或 `AGENT_WORKFLOW_STATE_DIR` 改为其他目录。
每次模型写入还会将旧文件 inode 保留到项目同文件系统的 `.agent-workflow-backup-models-<ID>/`，
路径记入备份并在操作结果中展示；旧编辑器后续保存仍可找回。恢复前会检查这些版本是否有后续变更。
恢复预览会保留原版本指纹；确认发布前及验收结束后再次核对，期间发生后续保存或权限变化会停止并保留冲突版本。
该目录不参与项目模块发现，也不生成第二份工作流。
列表、目录和预览命令只读；`add` 默认只登记。
`del` 必须先成功停用新任务入口才解除登记，绝不删除项目目录或业务文件。
登记表发生并发修改时拒绝覆盖；若原生动作已结算而登记保存失败，会明确报错，实际状态可由 `status` 查看。

中央状态中保存不可变内容库，每个核心由完整 SHA256 内容 ID 固定。项目内仅保留
`.agent-workflow/project.yaml`、薄桥与三宿主原生资源；内置 Skill 目录软链到选定核心。
状态目录或核心损坏会明确拒绝，不搜索“最新版”、不静默改读源码，也不自动清理旧核心。
克隆项目只有可提交的定位信息，不会自动继承另一物理项目的本机启用记录。

模型目录只投影允许的元数据，不显示或复制凭据，不发起模型推理；原生目录遵循宿主自身的缓存及网络策略：

- Codex 读取明确配置的 `model_catalog_json`；CPA、CC-Switch 等工具写入宿主的显式目录可以直接识别。
  相对路径按声明该字段的用户配置目录或项目 `.codex/` 目录解析。
  未声明显式目录时，POSIX 环境通过当前 Codex 的原生 `app-server model/list` 获取可见模型、展示名和推理档位，
  按分页和隐藏标记生成选项；每个项目／宿主复用一次结果，`r` 按需重新获取，绘制和配置事务锁内不重复查询。
  默认 `models_cache.json` 的真实身份为不透明摘要；不读取凭据猜归属，缓存标为未确认来源，
  不将其中模型及能力直接加入候选。原生查询失败时明确诊断并回退继承／当前明确配置；
  非 POSIX 在启动原生进程前降级，显式目录仍可使用。
  原生查询期间身份、有效提供方配置或可执行文件变化时丢弃本次结果并提示刷新；仅宿主自行更新模型缓存时允许复用。
  不读取废弃的 `profile` / `[profiles.*]`；独立 profile 会话需明确目录来源，不自动推断。
  已有明确推理能力时按目录限制档位，不启用涉及自动委派的 `ultra`。
- Claude Code 读取当前模型、别名映射及代理工具写入的 `modelPicker.options`。
  缓存中的 `modelSettings` 仅为偏好，不能推断模型推理能力。
- Antigravity 静态角色使用官方 `inherit / flash / pro` 档位，不猜测内部模型 ID。

模型与推理档位可独立修改。模型能力未知时，Codex 可写入 `none / minimal / low / medium /
high / xhigh / max`，Claude Code 可写入 `low / medium / high / xhigh / max`，也可选择继承。
这些是宿主允许的配置值，不代表所选模型已支持、模型 API 调用成功或已经通过服务验收。
损坏或嵌套过深的来源显示读取失败；CLI 只返回安全投影，TUI 保留其他项目和宿主的未应用草稿。

角色模型偏好写入现有 `.agent-workflow/project.yaml` 的 `role_models` 区块，启停、选版和修复均保留。
模型应用只更新该区块与选中角色的模型字段，保留角色正文、工具权限、Hooks 和编排规则；
成功前只读校验中央受管资源及其原生归属。已有 Agent 不会被重启，
宿主的显式调用及强制设置仍有自身优先级。
预览和最终发布前均核对本地来源摘要；提供方、目录或能力变化时保留草稿并要求重选。
摘要只绑定影响当前来源的有效模型、提供方、声明层、映射和能力证据；无关权限、Hooks、废弃 profiles 和其他平台配置不使草稿失效。
Codex 原生快照另绑定可执行文件、身份文件的只读元数据与缓存 identity 信号，不读取 auth 正文；凭据刷新可能保守使草稿失效。
宿主尚未反映到本地的外部 keyring 变化不能保证即时发现，`r` 会重新取得目录；目录可见不等于推理调用权限。
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
启停、切版和条件恢复复用唯一中央项目事务；管理器的“备份/恢复”专门处理模型配置，
恢复前展示文件范围并再次备份。预览后有并发变更会停止覆盖，验证失败则撤回仍属于本轮的改动。
观察到旧 inode 的并发保存或旧版本归档失败时，记录 `conflict` 及可核对的保留路径。
发布前为正向写入、回滚和冲突索引预留容量；日志保存失败时仍返回原错误、备份标识和保留路径。
单个损坏备份显示为 `invalid`，不能恢复，但不阻断其他备份或清空界面草稿。
中央模型事务在原有备份和精确回滚中自动获取合法编辑收据，仅允许模型字段及 `role_models` 变化。
收据同步中央受管前像，因此本工具写入不会使下一次停用或换版变成手改冲突；模型变更夹带正文、
权限、MCP 或 provider 等额外字段时拒绝，Skill 换链仍须通过原生归属校验，不自动追认受管资源的未知编辑。
TUI 后台显示实际任务名称、活动指示和已用时间，不显示虚构百分比或恢复阶段。
取消请求在应用开始前没有副作用；同步中央事务开始后等待其结算，结果中的 `cancel_requested`
表示迟到请求，不把已完成动作假报为取消。模型应用、检查和恢复不强杀正在结算的事务。

CLI 的直接动作默认执行，`--dry-run` 完全只读，不创建项目、状态目录、内容库或登记文件。
目前只接受已经存在的项目目录。裸短名称必须唯一匹配已登记项目；未知或重名时列出明确候选，
可用完整路径消除歧义。`--state-dir`、`--scan-root` 放在命令之前，`--json` 也可放在具体子命令后。

```bash
# 下列 STATE、PROJECT、SOURCE 均替换为明确目录；所有状态读写使用同一个 STATE。
awf-cli --state-dir STATE add PROJECT
awf-cli --state-dir STATE list --json
awf-cli --state-dir STATE status PROJECT --json
awf-cli --state-dir STATE open PROJECT --dry-run --json
awf-cli --state-dir STATE open PROJECT
awf-cli --state-dir STATE close PROJECT
awf-cli --state-dir STATE runtime install SOURCE --dry-run --json
awf-cli --state-dir STATE runtime install SOURCE
awf-cli --state-dir STATE runtime list --json
awf-cli --state-dir STATE use PROJECT CONTENT_ID
awf-cli --state-dir STATE rollback PROJECT
awf-cli --state-dir STATE repair PROJECT --dry-run --json
awf-cli --state-dir STATE del PROJECT
# 一次登记并启用；也可用 --content-id CONTENT_ID 选择已导入的精确版本。
awf-cli --state-dir STATE add PROJECT --enable --source SOURCE
```

`open` / `enable`、`close` / `disable` 分别同义。首次启用默认使用当前中央源码，重开默认保持
原绑定；显式 `--source` 才从所选来源导入，`use` 只接受已验证的完整内容 ID，不接受前缀或版本标签。
`runtime install` 只导入中央核心，不启用或切换任何项目。旧自包含安装不在 2.1 安装合同内；
检测到不兼容残留会明确拒绝。旧工作流须先确认任务收尾、保全项目文档和专有配置，并按已核对的
受管归属清单单独移除，再使用普通 `open`。本版本不提供自动转换或旧版本运行分支。

新命令的 JSON 成功结构为 `{"schema_version":1,"command":"…","dry_run":false,"result":…}`。
状态结果含 `state`、`enabled`、当前 `runtime_binding`、`previous_binding`、`hosts` 和 `conflicts`；
预览另含登记前后、`runtime_action`、`can_apply` 与受管 `changes`，不含文件原文或秘密。
JSON 拒绝结构为 `{"schema_version":1,"error":{"code":"…","message":"…"}}`，stdout 只有一份 JSON。
退出码：正常完成或可应用预览为 `0`，业务/参数拒绝及含冲突预览为 `2`，键盘取消为 `130`。
短名称拒绝另给 `candidates`，原生冲突另给安全 `conflicts`；其他解析错误不会投影配置正文。

模型配置的 `set` 和 `restore` 默认只预览，必须添加 `--apply` 才写入。
它们沿用模型备份/恢复的确认合同；项目登记和启停使用前述直接动作。

```bash
awf-cli add /path/to/project
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
awf-cli check --project /path/to/project
awf-cli backups --project /path/to/project
awf-cli restore --project /path/to/project BACKUP_ID
```

`workflow.sh` 是中央管理入口，项目不再保存一份完整管理器。核心按内容 ID 保存在中央状态目录，
原始导入源删除后，已验证固定核心仍可通过项目薄桥读取；删除状态库会使依赖它的项目明确拒绝。
停用会撤下新任务入口，但保留配置、必要薄桥和旧版本，已有任务必须继续显式传入其固定 pin。
`check` 只读校验项目受管资源，不运行可能修复文件的 setup 脚本，也不证明宿主已经加载模型。
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

中央项目修改角色窗口后先运行 `awf-cli repair /path/to/project --dry-run`，核对后运行
`awf-cli repair /path/to/project`，再用 `awf-cli check --project /path/to/project` 只读检查。
未注册短命令时，用 `bash /中央源码/workflow.sh` 替换 `awf-cli`。
中央项目没有本地 setup 脚本；源包开发模式的 setup 仅在源包根目录使用。
角色窗口要求 Claude Code 2.1.296+，只接受 100000..1000000 的完整整数，角色字段不能写
`200k`。它仅能降低原本继承的窗口，作为 `--agent` 主会话角色时不生效；全局
`CLAUDE_CODE_AUTO_COMPACT_WINDOW` 通常优先（环境变量缩写要求 2.1.304+）。
`roles --effective` 显示请求值、来源及未知的实际窗口；不会把字段存在当成真实压缩验收。
窗口、后台模式及写入保护变化都不会无故废弃模型草稿。

中央服务与原有 setup 共用显式保护合并：仅选中 Claude 且配置为 `true` 时，在项目 settings
补充下面的单个键；`inherit` 不读取或修改 settings，后续改回 `inherit` 或停用也不会撤销已开启的保护。
其他权限、MCP、Hooks 与信任字段保留，不重新签名已有 Hooks，也不独占整个 settings 文件。
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

以下直接 Python 路径用于源包开发模式。中央项目通过 `.agent-workflow/runtime.py`
的 `helper` 入口执行固定核心中的 Python helper，显式传入任务 `runtime_binding`；项目根、
配置与核心根由同一薄桥分别校验，不能把 core 的父目录当作项目。

```bash
bash /path/to/agent_workflow/lib/python_runtime.sh -B -X utf8 /path/to/agent_workflow/lib/project_profile_cli.py \
  json /path/to/agent_workflow /path/to/project
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

默认安装通过同一中央服务完成只读配置/发现预检，再将来源导入不可变内容库并条件发布项目原生资源。
项目只保存适配器、薄桥与原生入口，Skill 软链指向固定中央核心；`install.sh` 和
`awf-cli open /path/to/project` 均使用同一中央事务。状态目录可由 `--state-dir` 或
`AGENT_WORKFLOW_STATE_DIR` 显式选择，后续命令必须使用同一目录。
项目专属配置和已有非空文档保留；未知受管手改会停止覆盖。不兼容残留须先保全并按明确归属
处理，再重新预览普通安装；没有旧版本兼容升级入口。中央核心及旧版本不自动清理。
首次生成配置使用实际项目名，并派生符合合同的项目 ID；已有名称和 ID 不自动改写。
原始导入源移除后仍可读取已验证核心，但中央状态目录与项目薄桥必须保留。

通用规则正文统一随运行时内置 Skill 安装：工程规则在 `xy-code-standards/references/rules.md`，
设计规则在 `xy-ui-design/references/foundations-rules.md`、`components-rules.md`。
项目只维护已批准的特有规范；存在实际特有叶时才维护有内容的 `docs/STANDARDS.md` 薄索引，
无特有叶时不生成 GENERAL、默认设计叶、UPSTREAM 占位或空索引。既有说明索引可原样保留。
规范补齐保留项目特有规则、修改、权限及并发/回滚保护；无法确认归属或语义冲突时报告
受影响项，不把用户规范当模板覆盖或用近似语义放过重复ID。
规则来源变化须刷新当前指纹和任务包，不增加业务确认或无依据的全量测试。

中央项目复核使用 `awf-cli check --project /path/to/project`，缺失受管资源使用 `repair` 先预览再应用。
中央项目没有 `.agent-workflow/setup_*.sh`，四个 setup 的 `--preflight` 不适用于中央项目。
检测到旧的项目内 `agent_workflow/` 安装包或旧自包含运行时会停止；先确认旧任务收尾，
保全项目文档和专有配置，核对受管范围后单独移除旧工作流，再普通安装。

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
源包开发模式仅在角色可用性未知时，通过 Python 选择器调用 `project_profile_cli.py check-roles`。
中央项目用 `check` 查看状态，并用 `repair --dry-run` 预览发现后的资源变化，确认后应用。
源包 host setup 自带 preflight，完成后只需检查一次。Codex refreshes changed persisted module/command context;
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
| `install.sh` | 从任意位置选择已有目标项目并执行普通中央安装 |
| `.agent-workflow/` | 中央项目的适配器、locator 与薄桥 |
| `~/.config/agent-workflow/runtimes/<ID>/core/` | 默认中央不可变核心；自定义状态目录下保持相同相对结构 |
| `product/` | Cross-platform product discipline |
| `roles/xy-*.md` | Role technical baselines |
| `platforms/*/` | Per-CLI templates |
| `platforms/shared/skills/` | 九个宿主共用的内置 Skill；三宿主使用同一份源资源 |
| `platforms/shared/HOOKS.md` | 三平台辅助 Hooks、开关、所有权与原生信任说明 |
| `scripts/` | guard (soft) / portable conflict-marker lint |
| `setup_claude.sh` | 源包开发模式：Claude 入口、角色与 Skill |
| `setup_codex.sh` | 源包开发模式：Codex 入口与 `.codex/**` |
| `setup_antigravity.sh` | 源包开发模式：Antigravity 入口、角色与 Skill |
| `setup_all.sh` | 源包开发模式的聚合 setup；中央项目使用统一管理命令 |

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

Light派发前判断目标、消费者、范围与风险，使用当前自包含schema 2单任务包并做最小充分验证；
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

Project documents (`PROJECT.md` and topic lifecycle plans) and agentmemory are
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
project or feature truth will need a closeout projection. `PROJECT.md` and accepted plan baselines
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

文档使用一个人类入口：`docs/PROJECT.md`。它保留当前项目概况并只链接 plans 中的明确已验收基线，
不设行数／字节限制，不追加任务日志。一个稳定主题只有一份 Markdown 与同名派生 HTML；
当前需求、方案、执行恢复、已验收行为和必要依据放在同一稿中，Git 保留完整修订历史。
再次迭代在原路径更新本次目标与进度，保留上次已验收版本；未验收或取消的本次目标不能冒充交付，
`completed` 标签本身不证明批准、QA 或当前事实。已验收删除在同稿标记 `removed`、保留必要依据并移除 PROJECT 当前链接。

Light 只为实际暂停／恢复／交接或明确用户要求保存；Full 由 PM 在需求确认和适用原型选择后、
首次设计／实施派发前保存。模板面向 Full 六节完整形状，Light 按必要性简化；保存或渲染不升级等级、增加审批。

Full 正式需求审阅使用 HTML：模型只维护 `docs.plans/<name>.md`，同目录 `.html` 由固定
`answer-me-with-html` CLI 生成。批准前草案只放当前请求 scratch；批准后保存正式原稿再生成。
需求用稳定 REQ 编号链接具体原型页/状态，设计交接后 PM 写回同一原稿并重渲染；页面状态
不构成批准；已验收基线与历史执行明细分开，历史 HTML 不成为第二份当前规范。用法、受控语法及草案链接基准见
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

源包开发模式的 Claude setup 与官方本地诊断（`claude doctor`）：

```bash
bash /path/to/agent_workflow/setup_claude.sh
bash /path/to/agent_workflow/setup_claude.sh --check
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
计数语义；schema 2图／单包按模块职责绑定agent_alias，派发后agent_ref绑定真实ID且不可覆盖；
continuation只建议同任务等待／续用，退役／取消／未知／失效／跨宿主不得自动恢复。ID不证明
批准、存活或完成；不新增Agent池、runner或第二状态账本。
[QA 输入合同](platforms/shared/skills/xy-qa-review/references/inputs.md#原生结构化交接)
提供schema 2合同／extract；validate与extract必须传当前--task-pack，以handoff_ref绑定当前
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

下列独立 setup 命令只用于源包开发模式，在源包根目录执行；中央项目使用前文的 `check` / `repair`：

原有 setup 可接入可关闭的轻量辅助 Hooks；中央启停和 repair 仅按显式 `true` 收紧上述写入保护
单键，保留其他权限、Hooks、MCP 与信任字段，不新增 Hook 体系或重签已有 Hooks。不新增审批/QA门禁或状态台账。配置/回调通过
不等于模型行为测试通过；Codex 仍须原生信任审查，AGY 不猜测任务轮次或压缩恢复。
详见 [Hooks 开关与验证边界](platforms/shared/HOOKS.md)。

```bash
bash setup_codex.sh --preflight
bash setup_codex.sh
bash setup_codex.sh --check
bash setup_claude.sh --preflight
bash setup_claude.sh
bash setup_claude.sh --check
bash setup_antigravity.sh --preflight
bash setup_antigravity.sh
bash setup_antigravity.sh --check
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
- 要把已验证的源包变更应用到项目时，对用户指定并授权同步的目标显式导入并选版，
  或预览 `repair` 处理受管资源；仅优化源包不自动重装或同步项目。

## Portable docs scaffold

Every host setup and `setup_all.sh` creates only missing or empty current-profile documents from
`templates/docs/` and never overwrites non-empty user content:

| Path | Purpose |
|------|---------|
| `docs/STANDARDS.md` | 存在实际项目特有规范时维护的薄索引；既有说明索引保留 |
| `docs/standards/*.md` | 实际项目特有工程规范、保护边界等，不复制内置通用正文 |
| `docs/standards/DESIGN_*.md` | 实际采用的项目设计值、组件变体与平台差异；无差异不创建 |
| `docs/PROJECT.md` | 当前项目概况与 plans 明确已验收基线链接 |
| `docs/plans/` | 实际保存才创建；同主题单一 Markdown／派生 HTML，分清本次执行与上次已验收行为 |
| `docs/standards/prototype/` | Lightweight `index.html`, `prototype.css`, and direct `<page>.html`; resource directories only when needed |

`templates/docs/PLAN.md` 是 Full 生命周期写作形状：普通 Markdown 元信息为主题 ID、阶段、模块、
任务等级和已验收版本，六节为目标与范围、需求与验收、方案与原型关联、当前进展与恢复入口、
验收结果与当前已交付行为、批准依据与必要证据。阶段 token 为 draft／active／paused／completed／
cancelled／removed，已验收版本为真实标识或 `none`；已有版本的批准依据与验收证据须真实可恢复。
模板示例不产生批准或事实。Light 无基线恢复稿可简化；PROJECT 不能将无明确基线的稿件索引为当前功能。

新 schema 删除 `docs.features`、`docs.notes`、`memory.fallback_dir` 与独立 FEATURE 模板；
旧键明确拒绝，不保留运行时别名或旧数据转换工具。
安装不创建 features／plans／notes 空目录、不创建需求页或基线占位条目。源包未索引历史计划保持原样，
不能按 completed 自动转为当前事实。旧 STATUS／SPEC／ENGINEERING／DESIGN_SYSTEM 权威仍不兼容，
必要项目内容、批准和历史先安全迁入相应主题，再移除旧权威；不恢复双重事实。

当前恢复／交接简报按[计划生命周期](platforms/shared/skills/xy-workflow/references/plan-lifecycle.md)
原地替换为当前状态与下一步，不逐批累加完成明细；必要基线引用现有计划、功能和完整证据。
先确认原始批准、完整日志与唯一历史可恢复并修复引用，无法安全移交则保留原文及历史边界；
不新增归档树、简报副本或硬长度门槛。

项目特有叶仍直接位于 `docs.standards_root`：设计叶保留 DESIGN_ 前缀及 Domain: design，
工程叶声明 engineering；通用正文从三份精确内置来源读取，内置路径不扩大项目写权限。
配置的 index_path/root 始终保留；无项目规则叶且索引物理缺失时 index_fingerprint 为 null，
索引实际存在则记录真实SHA。init/文档校验检查文件系统，纯JSON图校验不冒称已核对文件存在性。
来源、领域、稳定ID、覆盖和指纹检查继续执行，不能把可选索引解释成可跳过规范。

2.1 不提供旧 features／notes 的转换入口。处理旧资料前必须先证明完整原文、批准、验收证据、
权限和必要引用可恢复，再按真实归属保留在现有主题或适用规范；归属未知或存在并发修改时停止。
旧键须在资料与引用已经安全处理后移除；不能靠删除配置键绕过文档保护，也不能将历史执行状态
直接认定为当前基线。已完成的资料整理结果和恢复证据继续保留。

New project: launch `install.sh` → drag or pass the project path → inspect the automatic
preflight and `--check` result → fill the scaffolded docs. Normal setup automatically
derives `memory.project_id` from the project directory name when the template placeholder
is still present.

See also `templates/project.yaml.example`.

完整日志保留在请求证据位置；长期正文仅归纳必要结论并引用证据。记忆服务不可用时，PM 继续
在已有相关主题稿或经适用性与批准核对后的已有项目规范章节中记录必要结论；没有既有归属时
保留当前交接待决依据，不建立 notes 或替代杂记目录，不把每条经验自动升级为强制规范。

## Optional host wiring

The project adapter never installs agentmemory, snapshots personal memory, or changes
global host configuration. Operators who have the service and want host tools may run:

```bash
agentmemory connect codex
agentmemory connect claude-code
```

These explicit commands expose tools to each host; action Skills are installed separately,
and the hosts must be reloaded or restarted. Setup and `--check` remain usable when the
service is offline through the existing topic plans and applicable project-standard sections.

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
use existing topic plans and applicable project-standard sections and call neither provider recall nor save.
