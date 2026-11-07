# 使用手册

本手册面向日常安装、项目管理和模型配置；快速入口见 [README](../README.md)，
Homebrew 的安装、升级与发行构建见 [Homebrew 说明](homebrew.md)。
源码开发与生成器维护见[开发手册](development.md)。工作流的完整规则由
[产品工作流](../product/WORKFLOW.md) 和[工作流 Skill](../platforms/shared/skills/xy-workflow/SKILL.md)维护。

## 支持范围与安装保护

当前源码版本为 **2.1.2**，唯一版本源为 `product/VERSION`；源码版本不代表公开渠道已发布该版本。
GitHub 与 Tap 的公开版本以各自发布声明为准；源码更新不会改变既有二进制、Cellar 载荷或 Tap。

当前安装通过 macOS/Linux 源包或 Homebrew 使用中央运行时。未发布的 npm／npx Windows
安装渠道已移除，不提供对应包、构建器或安装命令。Windows 安全文件系统后端尚不支持受管
Skill 的锚定软链发布，安装在创建项目资源或中央状态前明确拒绝。跨平台启动器和安全合同仍保留，
不表示 Windows 安装已经验收。

源包需要 Python 3.11+（含标准库 `tomllib`），无需安装 Python 包。入口从现有 PATH 选择
支持的 `python3` 或带版本命令；可用 `AGENT_WORKFLOW_PYTHON` 指定解释器路径，显式值无效时
直接失败，不静默切换环境。安装器不下载运行时，也不改全局 shell、宿主或 Python 配置。
重新生成需求 HTML 时才需要现有 Node.js >= 20；setup 不启动渲染器，无需全局 npm 安装。

```bash
bash /path/to/agent_workflow/install.sh
# 提示后拖入已有项目目录；也可直接传路径。
bash /path/to/agent_workflow/install.sh /path/to/project
```

安装先完成只读配置、发现与预检，再条件发布三宿主原生资源；首次使用必须先显式导入核心并激活中央 current。
`install.sh` 与 `awf-cli open` 使用同一中央事务。项目专属配置与已有非空文档保留，
用户自有同名 Agent／Skill 不会被覆盖，未知受管修改会停止。中央项目没有本地 setup 脚本。

2.1 不提供旧版本兼容升级，只接受 Light／Full 和 schema 2 任务／交接格式。发现旧项目内
`agent_workflow/` 或旧自包含运行时会拒绝安装。先确认旧任务收尾，保全项目文档、专有配置和必要证据，
再按已核对的受管归属单独移除旧工作流，重新预览普通安装；没有自动转换或旧版本运行分支。

## 启动与来源诊断

Homebrew 安装后直接运行 `awf-cli`；源包可直接运行 `workflow.sh`，也可注册短命令：

```bash
bash /path/to/agent_workflow/workflow.sh --install-cli
awf-dev
awf-dev tui --project /path/to/project
awf-dev --version
bash /path/to/agent_workflow/workflow.sh --version
type -a awf-cli
```

源包短命令默认名为 `awf-dev`，与正式 `awf-cli` 并存；默认链接到 `~/.local/bin`，不复制管理器、不改 PATH 或 `.zshrc`。可用
`--bin-dir /path/on/PATH` 选择已有命令目录。保留中央源包；移动后先核对并移除旧链接，再重新注册。
已有其他同名命令会保留，PATH 遮蔽或只有相对／空 PATH 项时会区分“入口已创建”与“任意目录可用”。
Homebrew 已管理入口，无需再注册；来源排查见 [Homebrew 说明](homebrew.md#用户安装)。

`--version` 保留版本、中央源根两行，并增加 source/formal 身份及物理载荷根，区分源码和构建发行载荷，不启动 TUI、不读取模型来源、
不创建管理状态。旧入口若不认识该选项，先核对链接和已安装版本。
相对项目路径、相对 Python 和相对 PATH 按调用目录解释；相对链接按物理父目录解析。
入口内部 `cd` 仅在该次操作中隔离 CDPATH，原 PATH、CDPATH 及传给 Python 的环境保持。

## 项目登记与中央版本

添加默认只登记已存在目录，启用才建立三宿主入口。项目列表合并独立登记与默认桌面目录的直接子项目；
不递归读取业务代码、Git worktree 或会话。可用 `--scan-root /path/to/projects` 指定扫描目录。
管理状态和模型备份默认在 `~/.config/agent-workflow`；可用 `--state-dir` 或
`AGENT_WORKFLOW_STATE_DIR` 指定，后续操作必须沿用同一目录。显式独立状态的宿主操作还必须
传 `--host-home HOST_HOME`；它固定三个宿主配置根并忽略 `CODEX_HOME`／`CLAUDE_CONFIG_DIR` 覆盖，
不会由独立状态猜测真实 HOME。只读项目状态和核心导入不需要宿主根。

```bash
# STATE、PROJECT、SOURCE 替换为明确目录；所有状态读写使用同一个 STATE。
awf-cli --state-dir STATE --host-home HOST_HOME add PROJECT
awf-cli --state-dir STATE --host-home HOST_HOME list --json
awf-cli --state-dir STATE --host-home HOST_HOME status PROJECT --json
awf-cli --state-dir STATE --host-home HOST_HOME runtime install SOURCE --dry-run --json
awf-cli --state-dir STATE --host-home HOST_HOME runtime install SOURCE
awf-cli --state-dir STATE --host-home HOST_HOME runtime activate CONTENT_ID --dry-run --json
awf-cli --state-dir STATE --host-home HOST_HOME runtime activate CONTENT_ID
awf-cli --state-dir STATE --host-home HOST_HOME runtime status --json
awf-cli --state-dir STATE --host-home HOST_HOME open PROJECT --dry-run --json
awf-cli --state-dir STATE --host-home HOST_HOME open PROJECT
awf-cli --state-dir STATE --host-home HOST_HOME close PROJECT
awf-cli --state-dir STATE --host-home HOST_HOME runtime list --json
awf-cli --state-dir STATE --host-home HOST_HOME use PROJECT CONTENT_ID
awf-cli --state-dir STATE --host-home HOST_HOME follow PROJECT
awf-cli --state-dir STATE --host-home HOST_HOME rollback PROJECT
awf-cli --state-dir STATE --host-home HOST_HOME runtime rollback --dry-run
awf-cli --state-dir STATE --host-home HOST_HOME runtime recover --dry-run
awf-cli --state-dir STATE --host-home HOST_HOME repair PROJECT --dry-run --json
awf-cli --state-dir STATE --host-home HOST_HOME del PROJECT
# 一次登记并启用；也可用 --content-id CONTENT_ID 选择已导入的精确版本。
awf-cli --state-dir STATE --host-home HOST_HOME add PROJECT --enable --source SOURCE
```

列表、目录和预览只读；`add` 默认只登记。CLI 直接动作默认执行，`--dry-run` 完全只读，
不创建项目、状态目录、内容库或登记文件。仅接受已有项目目录。裸短名称必须唯一匹配已登记项目，
未知或重名时列出候选，可用完整路径消除歧义。`--state-dir`、`--scan-root` 放在命令前，
`--json` 也可放在具体子命令后。

`open`／`enable`、`close`／`disable` 分别同义。普通首次启用必须有已激活 current，缺失时会提示先 `runtime install` 再 `runtime activate`。
只有显式 `--source` 才从所选来源导入；`runtime install` 仅导入核心。
`runtime activate` 更新中央 current 与已启用的跟随项目，`runtime rollback` 选择中央前次版本。
不支持控制协议的历史核心不能激活为 current，固定任务资源仍保留。
`use` 和项目 `rollback` 建立项目锁版，`follow` 清除锁版；停用项目保持停用，下次启用采用有效策略。
中央激活预览列出锁版保留、停用后续采用和本次应用的固定项目集合。
`runtime status` 查看中央许可，未结算中央事务先只读预览 `runtime recover --dry-run`，再恢复。
`use` 只接受已验证的完整 SHA-256 内容 ID，不接受前缀或版本标签。

中央内容库保存不可变核心。项目仅保留 `.agent-workflow/project.yaml`、locator、薄桥和宿主原生入口，
内置 Skill 目录软链到选定核心。原始导入源删除后仍可读已验证固定核心；状态目录或核心损坏会明确拒绝，
不搜索“最新版”、不静默回退源码、不自动清理旧核心。克隆项目只有可提交定位信息，不继承另一物理项目的本机启用记录。
停用仅撤下新任务入口，保留配置、必要薄桥与旧核心；不终止已有任务，旧任务继续显式传入自己的固定 pin。

`del` 必须先成功停用新任务入口才解除登记，不删除项目目录或业务文件。停用冲突会保留项目和登记并报告诊断。
登记表并发修改会拒绝覆盖；原生动作已结算而登记保存失败时会明确报错，可用 `status` 查看实际状态。
`check` 只读检查受管资源，不运行可能修复文件的 setup，也不证明宿主已加载模型；缺失或发现变化先用
`repair --dry-run` 核对，再显式应用。管理器不提交、合并、推送，也不改宿主主会话的全局模型设置。

### 备份与核心清理

`runtime cleanup` 默认只读预览，`--dry-run` 是显式同义写法；追加 `--apply` 才在同一进程生成并应用服务提案。
管理器不猜测或扫描真实 HOME、业务会话及任意旧目录。服务保留当前/前次及历史绑定、明确任务 pin、
最新完整备份和未结算恢复依赖；遇到未知引用会保守保留核心。

```bash
awf-cli --state-dir STATE runtime cleanup
awf-cli --state-dir STATE runtime cleanup --dry-run --task-record /path/to/task.json
awf-cli --state-dir STATE runtime cleanup --apply --task-record /path/to/task.json
# 每个ROOT必须是明确授权的精确旧工作流归档批次；可重复传入不同批次。
awf-cli --state-dir STATE runtime cleanup --backups-only \
  --approved-backup-root /path/to/.sync-backups/BATCH_A \
  --approved-backup-root /path/to/.sync-backups/BATCH_B
# 核对上述预览后，在同样参数后追加 --apply；--backups-only不回收核心。
awf-cli --state-dir STATE runtime cleanup --recover
awf-cli --state-dir STATE runtime cleanup --recover --apply
```

`--task-record` 可重复传入明确 JSON 记录，使其中 pin 参与保活；不指定的业务目录不会被扫描。
`--recover` 默认只读查看既有清理状态，`--recover --apply` 仅恢复原先已确认的集合；
不能与 `--approved-backup-root`、`--backups-only` 或 `--task-record` 混用。
`--apply` 与 `--dry-run` 互斥。中断或冲突时保留原清理记录，先核对恢复摘要再继续，不能重新扩大候选。
中央状态分别展示激活和清理未结算门；`runtime recover` 只恢复激活，清理须用 `runtime cleanup --recover`。

### JSON 与退出码

成功结构为 `{"schema_version":1,"command":"…","dry_run":false,"result":…}`；
状态分别包含 `declared_enabled`、`resources_healthy`、`history_recoverable`、`new_task_allowed`、
`management_write_allowed` 和 `issues`；`policy` 是 follow/pinned，`effective_binding` 为策略目标，
`runtime_binding` 为实际已应用版本。停用、锁版、资源健康、历史恢复与新任务许可分别显示，不能从 enabled 或 current 推导全部正常。
预览另含登记前后、`runtime_action`、`can_apply` 与受管 `changes`，不含文件原文或秘密。
拒绝结构为 `{"schema_version":1,"error":{"code":"…","message":"…"}}`，stdout 只有一份 JSON。
短名称拒绝另给 `candidates`，原生冲突另给安全 `conflicts`，解析错误不投影配置正文。
正常完成或可应用预览退出 `0`；业务／参数拒绝、含冲突预览退出 `2`；键盘取消退出 `130`。

## TUI 工作台与键位

普通交互终端运行 `awf-cli`。左侧项目、右侧角色／模型／推理共用完整外框，只有键盘焦点所在面板整行高亮。
顶部显示宿主及全部范围的未保存草稿数，草稿标为 `●`；无草稿只表示没有待保存编辑，不表示已同步或验收。
项目按名称、状态、固定版本分行，管理条显示选中项目状态与启停入口。启停都先读取服务只读预览，再按 Enter 确认；
状态待刷新或冲突时以预览诊断为准。底部保留状态与最多两行主要提示，完整键位按 `?` 查看。
80 列以上并排显示，窄终端用左右键切换区域；55 列 × 16 行收起辅助详情并保留滚动选择。
支持默认终端背景，无颜色或不支持默认背景时回退为粗体、反色与文字提示。

项目列表上方固定“全局默认”，不计入项目数；项目区域按 Home 可选择，右箭头或 Enter 打开角色表。
全局按平台／角色管理，复用模型与推理选择器，不显示项目启停。草稿、前像、目录与角色选择按全局／项目／平台隔离。

| 按键 | 操作 |
| --- | --- |
| ↑ / ↓ | 选择项目、角色、弹层选项或搜索匹配项 |
| Home / End | 列表首尾、文本页首尾、输入区行首尾 |
| PageUp / PageDown | 列表或文本页翻页，搜索期间也可用 |
| Tab / Shift+Tab | 主界面切换下一个／上一个平台，首尾循环 |
| ← / → | 主界面聚焦项目／右侧区域；重复同方向保持区域 |
| / | 搜索名称、ID 或项目路径；Enter 接受筛选，再 Enter 才确认 |
| : | 按中文操作名或英文别名搜索命令；不可用项说明原因，写操作保留确认 |
| Enter | 打开角色表；按选中列编辑模型或推理，鼠标可选择列 |
| m / e | 选模型／单独选推理；模型后继续选推理，再 Enter 暂存 |
| 1 / 2 / 3 | 切换 Codex／Claude Code／Antigravity |
| s | 预览当前范围与平台草稿；全局列受影响项目／冲突，Enter 确认备份保存 |
| u | 丢弃当前角色草稿并重读基线，保留其他范围草稿 |
| v | 查看有效模型、推理与各字段来源，窄屏可滚动 |
| g | 中央状态／导入／激活／回退／恢复、项目管理及本地来源；复用滚动弹层 |
| o / p | 预览启用／停用，再 Enter 确认，不终止运行中任务 |
| a | 输入目录，选“仅登记”或“登记并启用三宿主”，读取预览后确认 |
| r | 按需刷新本地模型目录和角色，保留未应用草稿 |
| Esc | 取消搜索并恢复选择；已有筛选先清除，再逐层返回；保存预览返回保留草稿 |
| ? / q | 帮助／退出；任意项目或宿主有草稿时先确认放弃 |

路径输入支持左右、Home／End、Delete／Backspace、Ctrl+U 清空，长路径围绕光标滚动。
搜索、命令与路径输入中的 `q/s/u/o/p/1/2/3/?/:` 是正文，左右键移动光标；弹层按当前上下文处理 Tab／左右键。
忙态阻止切换和重复操作；鼠标单击仅聚焦或选中，仍须 Enter。Tab 切换保留项目、焦点、匹配角色与各范围草稿。
刷新尽量按角色 ID 保持选择；外部已移除但仍有草稿的角色标为“已移除”，可用 `u` 单独丢弃。
小窗口退出及空闲 Ctrl+C 也保护全部草稿；提示不能完整显示时禁止盲确认，需放大窗口。

选择、暂存、保存是不同阶段：选择器 Esc 取消本次选择，暂存后 `s` 进入保存预览；无改动不写入。
保存显示真实任务状态，服务完成并验收后才提示成功，失败或冲突保留草稿与诊断。
管理菜单中央版本列表按 `i` 查看完整内容 ID、清单摘要和核心路径，Enter 只读切版预览，再次确认才应用。
TUI 添加预览前后都不提前登记或安装，Esc 可逐层返回。`g`／`:` 可打开中央运行时动作与项目跟随。
当前项目当前平台的“全部角色恢复跟随全局”生成独立提案，不修改模型草稿；取消和失败保留草稿与授权，
确认并经服务核验成功后，仅消费提案生成时该固定范围已有草稿；持久来源无改动时同样替代这些草稿，
结果明确不写入、不备份。全局默认页不提供整平台批量恢复。
写入成功后展示刷新失败时仍报告真实完成，提示刷新核对，不重复提交。

## 模型目录、默认值与事务恢复

三宿主原生角色选择与模型实际执行仍须在目标宿主会话验收。当前工具若没有原生角色选择参数，
任务名称 `task_name` 只是名称，不能作为已选角色、模型或推理档位的执行证明；文件解析通过不能标为原生运行已验证。

模型目录只投影允许的元数据，不显示或复制凭据、不发起模型推理；原生目录遵循宿主的缓存及网络策略。

- Codex 先读显式 `model_catalog_json`，包括 CPA、CC-Switch 等写入的目录。相对路径按声明字段的用户配置目录或项目 `.codex/` 解释。
  没有显式目录时，POSIX 通过当前 Codex 的原生 `app-server model/list` 获取分页模型、展示名、推理档位并过滤隐藏项；每项目／宿主复用结果，`r` 按需刷新。
  默认 `models_cache.json` 身份是不透明摘要，标为未确认来源，不读凭据猜归属、不将其能力直接加入候选。
  原生查询失败时报告并回退继承／当前明确配置；非 POSIX 启动进程前降级，显式目录仍可用。
  查询期间身份、有效提供方或可执行文件变化会丢弃结果；宿主自行更新模型缓存允许复用。
  不读废弃 `profile`／`[profiles.*]`，独立 profile 会话需明确目录来源；不启用涉及自动委派的 `ultra`。
- Claude Code 读取当前模型、别名映射和 `modelPicker.options`。缓存 `modelSettings` 只是偏好，不能推断模型能力。
- Antigravity 静态角色使用官方 `inherit / flash / pro`，不猜内部模型 ID。

模型与推理可独立修改。能力未知时 Codex 可写 `none / minimal / low / medium / high / xhigh / max`，
Claude 可写 `low / medium / high / xhigh / max`，或选择继承。这些配置值不证明模型支持、API 成功或服务验收。
损坏或过深来源显示读取失败，CLI 仅安全投影，TUI 保留其他范围草稿。
目录暂时失败或来源失效后，重进编辑会复核并有界重试；稳定目录继续复用。旧来源草稿不自动重设基线，需重选或 `u` 丢弃。
绘制、保存预览和事务内来源守卫不重启原生目录进程。

全局角色默认在状态目录 `preferences/role-models.json`，位于不可变核心外；空配置只读不建文件。
项目覆盖只写 `.agent-workflow/project.yaml` 的 `role_models`，启停、切版和修复保留。
各字段按“项目覆盖 → 全局默认 → 宿主”解析，显式 `inherit` 始终继承宿主。只改模型不会覆盖推理，反之亦然。
选择器区分“跟随全局（当前有效值）”与“继承宿主”；直接确认跟随项保留来源，明确选具体值或宿主继承才形成覆盖，
即使有效值相同。模型选完后推理仍保留原来源。
`g` 或 `:` 中恢复跟随动作仅暂存清除对应覆盖，`s` 后确认才写；全局恢复跟随宿主，`u` 仅丢弃草稿。

全局保存列出所有受影响登记项目和冲突，仅已启用且实际跟随的原生字段立即更新；停用或未管理项目下次启用采用有效值，不自动安装。
明确项目覆盖、宿主继承、核心绑定和旧任务 pin 保留。项目模型应用只更新该区块和选中角色模型字段，保留角色正文、
工具权限、Hooks 与编排规则，成功前校验中央受管资源及原生归属；已有 Agent 不重启，宿主显式调用与强制设置仍有优先级。
项目模型写入要求当前宿主工作流已启用；全局默认可独立编辑，不维护旧版适配。

```bash
awf-cli models --platform codex --project /path/to/project
awf-cli roles --platform codex --project /path/to/project
awf-cli roles --platform codex --global
awf-cli roles --platform claude --project /path/to/project --effective
# set 与 restore 默认仅预览，添加 --apply 才写入。
awf-cli set --project /path/to/project --platform codex \
  --role xy-backend --model your-local-model --effort high
awf-cli set --global --platform codex --role xy-backend --effort high
awf-cli set --project /path/to/project --platform codex --role xy-backend --reset model
awf-cli set --global --platform codex --role xy-backend --reset all
# 当前项目当前平台全部角色，含未安装角色及停用宿主的持久覆盖。
awf-cli set --project /path/to/project --platform codex --all-roles --reset all
# 确认上述固定提案：追加 --apply；无改动不写入、不备份。
awf-cli check --project /path/to/project
awf-cli backups --project /path/to/project
awf-cli restore --project /path/to/project BACKUP_ID
```

`roles`／`set` 必须选互斥的 `--project` 或 `--global`。`--reset model/effort/all` 与同字段赋值互斥，
可在同次命令清一个字段并设置另一个。`--all-roles` 与 `--role` 互斥，
仅允许项目范围的 `--reset all`，不与赋值混用，也不提供全局批量恢复。角色值用内联 JSON（合法 YAML），无需 YAML 解析包，推荐 TUI：

```yaml
role_models:
  codex:
    xy-backend: {"model": "your-local-model", "effort": "high"}
  claude:
    xy-qa: {"model": "opus", "effort": "inherit"}
  antigravity:
    xy-uiux: {"model": "pro", "effort": "inherit"}
```

预览及发布前核对本地来源摘要，提供方、目录或能力改变时保留草稿并要求重选；无关权限、Hooks、废弃 profiles 和其他平台配置不使其失效。
Codex 原生快照另绑定可执行文件、身份文件只读元数据与缓存 identity，不读 auth 正文；凭据刷新可能保守使草稿失效。
尚未反映到本地的外部 keyring 变化无法保证即时发现，`r` 重新取目录；目录可见不等于推理权限。
并发冲突可 `u` 丢弃该角色后重编，普通刷新不会重设编辑基线。

每次模型写入保留精确备份和旧文件 inode 到项目同文件系统 `.agent-workflow-backup-models-<ID>/`，
结果与备份记录给出路径；不参与模块发现、不生成另一份工作流。恢复预览展示文件范围并再次备份，
发布前及验收后重核原版本指纹、后续保存和权限；并发变化停止覆盖并保留冲突版本。
验证失败只撤回仍属于本轮的修改。旧 inode 后续编辑或归档失败记 `conflict` 与保留路径；
发布前为正写、回滚和冲突索引预留容量，日志保存失败仍返回原错误、备份 ID 与路径。
损坏备份标 `invalid`、不能恢复，但不阻断其他备份或清空草稿。

模型事务自动取得仅允许模型字段与 `role_models` 的合法编辑收据，同步中央受管前像；后续停用／换版可识别本工具写入。
夹带正文、权限、MCP、provider 等额外字段会拒绝，Skill 换链仍校验原生归属，不追认未知修改。
后台任务只显示真实名称、活动与耗时，不显示虚构百分比或恢复阶段。
取消在应用前无副作用；同步中央事务开始后等待结算，`cancel_requested` 是迟到请求，不将完成误报取消，不强杀正在结算的事务。

## 宿主诊断与 Claude 可选配置

```bash
# 默认只读本地配置；--probe 才显式运行固定的宿主 --version。
awf-cli doctor --project /path/to/project
awf-cli doctor --platform claude --project /path/to/project --probe
```

`doctor` 区分官方文档能力、目标事件、可见配置和明确探测版本，不据版本号推定 Hook 信任、事件触发或模型可用。
没有官方依据的最低版本保留未知。探测不登录、不更新、不调用模型、不回显宿主原始输出；宿主可能产生启动缓存，CLI 版本不代表 App／IDE 版本。

Claude 来源页及 `roles --effective` 仅投影模型强制覆盖、全局 effort、子 Agent 默认 effort 的允许字段。
普通本地会话通常由设置文件 env 覆盖 shell 同名值；组织策略、调用参数、`--settings`、运行会话与特殊 env 不在本地推导范围。
具名模型优先级按 Claude Code 2.1.251+ 解释，强制模型覆盖要求 2.1.257+，子 Agent 默认 effort 要求 2.1.316+；
显式 `model: inherit` 仍高于普通子 Agent 默认模型。字段存在不证明旧客户端支持，fork／后台变化不使模型草稿失效。

安装源或项目 `.agent-workflow/project.yaml` 的 `claude_options` 独立于模型可写字段，空窗口表与 `inherit` 保持宿主选择：

```yaml
claude_options:
  auto_compact_windows: {"xy-qa": 200000, "xy-backend": 300000}
  block_writes_outside_working_directories: true
```

修改后先 `awf-cli repair /path/to/project --dry-run`，确认再 `repair`，最后 `check --project`。
角色窗口要求 2.1.296+，仅接受 100000..1000000 完整整数，不接受 `200k`；只能降低继承窗口，
作为 `--agent` 主会话不生效。全局 `CLAUDE_CODE_AUTO_COMPACT_WINDOW` 通常优先，环境变量缩写要求 2.1.304+。
`roles --effective` 展示请求值、来源与未知实际窗口，不证明真实压缩验收。

仅选中 Claude 且显式为 `true` 时，中央服务与 setup 合并
`permissions.blockWritesOutsideWorkingDirectories: true`（要求 2.1.314+）。`inherit` 不读改 settings，
改回 `inherit` 或停用也不撤销已启用保护。已有 false／无效值会停止预检并保留文件，其他权限、MCP、Hooks、信任字段保留。
这独立于 `workflow_hooks.mode`；关闭 Hooks 不关闭保护。本包不写 false、不改全局权限、不自动加工作目录。
原生保护约束 Write／Edit／NotebookEdit，不覆盖 Bash，也不等同任务 `owned_paths`；worktree 会话需核验实际工作目录。
`doctor` 对 managed／调用时设置、实际工作目录与运行行为仍标未验证。

Claude 的 `CLAUDE.md` 仅为一行 `@AGENTS.md`，共用精简指令入口，角色与 Skill 仍在各自原生目录。
只接受缺失入口或精确薄入口；其他内容预检拒绝并保留，不自动转换旧正文。发布失败回滚本轮入口修改。
在真实 Claude 会话运行 `/context` 核对加载，`--check` 仅证明磁盘产物，不证明会话加载或模型执行。
压缩恢复继续复用 `SessionStart(compact)`，不重复注入完整指令。辅助 Hooks 可通过 `workflow_hooks.mode: off` 关闭，
其所有权、信任及验证边界见 [Hooks 说明](../platforms/shared/HOOKS.md) 和[Claude 平台细则](../platforms/claude/references/pm-integration.md)。

可选严格 guard 是源包开发工具，其布局要求、`deny_prefixes` 和真实调用入口见
[开发手册](development.md#源包可选-guard)；普通中央薄项目不包含该脚本。

## 项目文档与可选记忆

默认 `workspace.discovery: auto`。ProjectProfile preview 在写入前报告实际角色、模块根、技术栈证据与候选验证命令，
普通项目不必手改角色分配、模块路径或命令。仅证据无法消除的特殊歧义才用 `workspace_overrides`。
UI／UX、QA 是基线可用角色，不表示必须做 UI；实施角色仍按真实清单发现。宿主私有 `.claude`、`.codex`、`.agents`
在各扫描层排除。栈或模块变更后由 `check` 查看，再用 `repair --dry-run` 预览资源变化，不逐任务重复探测。

项目文档只补缺失或空内容，不覆盖已有非空正文。存在实际项目特有规范才维护 `docs/STANDARDS.md` 薄索引和叶，
不复制内置通用规则、不建 GENERAL／默认设计叶／空索引。`docs/PROJECT.md` 保留项目概况与明确已验收计划基线链接；
同主题计划只有一份 Markdown 和同名派生 HTML，历史状态或 `completed` 标签不能证明当前功能。plans 仅实际保存时创建，
不创建 features／plans／notes 空目录。旧 `docs.features`、`docs.notes`、`memory.fallback_dir` 和旧权威格式明确拒绝，
2.1 不提供转换入口；处理前先证明完整原文、批准、验收证据、权限与引用可恢复，未知归属或并发修改时停止。
详细生命周期与安全保留规则见[计划生命周期](../platforms/shared/skills/xy-workflow/references/plan-lifecycle.md)，
Full 六节写作形状见 [PLAN 模板](../templates/docs/PLAN.md)，需求 HTML 见[生成方法](../platforms/shared/skills/xy-plan/references/requirement-html.md)。

普通安装在模板占位值仍存在时，自动派生 `memory.project_id` 并原子写入配置；这是项目唯一稳定 slug，不是文件系统路径。
已配置 ID 不覆盖，自定义命名空间可手改。`--check` 和 `--preflight` 从不初始化该值，保持只读。

agentmemory 是可选服务，安装器不安装它、不快照个人记忆、不改全局宿主配置。已有服务且主动选择接入时才运行：

```bash
agentmemory connect codex
agentmemory connect claude-code
```

这些命令向宿主暴露工具，动作 Skill 单独安装，随后重载／重启宿主；Claude setup 不运行 connect。
Claude Auto Memory 保持用户管理，它是不受信背景上下文，不是审计后的记忆、批准、权限或历史命中证明。
严格隔离仅在工具可强制项目过滤并返回匹配出处时使用 provider；否则不 recall／save，继续用已有相关主题计划和适用项目规范。
离线仍可 setup／check，不新增 notes 或替代杂记目录，也不将每条经验自动升为规范。
