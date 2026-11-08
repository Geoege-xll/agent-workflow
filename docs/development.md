# 开发手册

本手册说明源包结构、开发生成器、维护和验证入口。日常项目操作见[使用手册](usage.md)，
发行构建与发布边界见 [Homebrew 说明](homebrew.md)，快速开始见 [README](../README.md)。

## 权威与源码职责

用户操作说明放在三份手册；产品语义、角色权限和 Skill 规则仍由对应源文件维护，
手册只说明入口与边界，不作为第二份完整规则。修改当前规则时应同时检查实际生成器、调用者与合同测试。

| 路径 | 职责 |
| --- | --- |
| `product/WORKFLOW.md` | 产品工作流权威，含 Light／Full、确认、所有权、QA 与收口 |
| `product/VERSION` | 唯一人工维护版本值；公开版本以 Release 与 Tap 各自声明为准 |
| `roles/xy-*.md` | 各角色技术职责与权限 |
| `platforms/shared/skills/` | 九个内置 Skill 的唯一共用源（one shared source）及按需 references |
| `platforms/codex/`、`platforms/claude/`、`platforms/antigravity/` | 三宿主模板、适配和 PM 平台细则 |
| `platforms/shared/HOOKS.md` | 辅助 Hooks 开关、所有权与原生信任合同 |
| `templates/` | 项目配置、文档、原型等实际生成输入 |
| `manager/cli.py`、`manager/tui.py` | 命令协议与 curses 交互，调用业务服务，不复制业务规则 |
| `manager/project_service.py` | 项目扫描、登记、添加／删除计划与登记发布 |
| `manager/service.py` | 模型配置应用、备份／恢复、收据与精确回滚事务 |
| `manager/runtime_service.py` | 单项目启停、选版、回滚与修复的唯一事务编排 |
| `manager/central_runtime.py`、`manager/runtime_policy.py` | 中央 current 激活／恢复协调、follow／pinned 策略与准入门 |
| `manager/native_agents.py`、`lib/hosts/native_context.py` | 用户级原生资源归属与显式不可变宿主上下文 |
| `manager/runtime_lifecycle.py` | 固定任务／历史引用保护的生命周期 preview/apply/status/recover，CLI `runtime cleanup` 是公开维护入口 |
| `manager/state_files.py` | 管理状态普通文件的有界读取、前像核对与安全发布 |
| `lib/install/project_paths.py` | 规范项目路径与目录身份边界，供实际服务调用者复用 |
| `manager/catalog.py`、`manager/codex_models.py`、`manager/model_preferences.py` | 模型来源、能力与字段偏好 |
| `manager/runtime_state.py` | 中央绑定及事务日志的私有记录读写边界 |
| `lib/runtime_store.py`、`lib/central/runtime_project.py`、`lib/runtime_bridge.py` | 不可变核心、项目受管资源与 pin 薄桥 |
| `lib/install/` | 安装编排、项目路径及平台子进程的超时／取消／资源回收 |
| `lib/project/` | 项目发现、画像、配置验证及项目记忆身份初始化 |
| `lib/documents/` | 计划与需求文档、原型导航、规范基线和有界分页读取 |
| `lib/hosts/` | 三宿主指令、原生产物、配置及 Hook 安装适配 |
| `lib/skills/` | Skill 绑定与共用正文合同、业务确认和 QA 策略的 Python 工具；Skill 正文仍在 `platforms/shared/skills/` |
| `lib/delivery/` | 原生交接／用量、QA 交接与 worktree 交付入口 |
| `lib/central/` | 中央项目受管资源及角色偏好字段解析；事务编排仍归 `manager/runtime_service.py` |
| `lib/` 固定根文件 | 解释器、自举及存储安全边界、任务图、固定 Hook 与模型／AST 合同；`__init__.py` 仅标识可信普通包 |
| `scripts/` | 统一验证入口、guard、冲突标记 lint 与宿主检查薄委派 |
| `packaging/` | 离线归档构建器和 Homebrew Formula 模板，不进入运行时发行载荷 |
| `tests/` | 行为、合同与真实消费者验证，不进入运行时发行载荷 |

CLI/TUI 入口只构造一次 `NativeContext`／`HostPaths` 并向项目、中央和模型角色／上下文／目录／预览调用透传。
显式 custom state 的宿主操作要求 `--host-home`；模型目录、资源校验和文件投影不能宣称原生角色／模型执行已验证。
整平台恢复调用 `model_preferences.reset_platform` 的同一固定提案；UI 不先修改草稿或自行写配置。
`runtime cleanup` 默认只读，`--apply` 调同一进程生命周期提案；`--recover` 读取公共状态，
`--recover --apply` 只恢复已确认原计划。候选、归属、引用保活与删除全部由生命周期服务维护，CLI不另写扫描或索引。

`service` 仅负责模型事务，`runtime_service` 保持中央事务的单一所有者；项目登记归 `project_service`，
状态文件和项目路径共用边界分别归 `state_files`、`project_paths`。下游通过所属模块调用，
不增加兼容空转发层，也不绕过所有者直接改私有记录。`install_process` 管理外部 setup 进程，
取消／超时须先停止写入并回收进程，再交回安装恢复；它不承担中央版本选取或模型事务。

中央核心按完整内容 ID 固定，模型偏好和机器状态位于核心之外。项目根、配置根与核心根由薄桥分别验证，
不能把 core 父目录当项目。中央状态或核心损坏应明确拒绝，不回退其他版本；已有任务 pin 保持，
受管归属、用户内容保护、并发冲突与精确回滚是安全合同，不能作为“历史兼容”删除。

中央控制器资格与内容身份分开验证。当前桥在 `lib/runtime_bridge.py` 声明
`CENTRAL_CONTROL_PROTOCOL = 1`；`controller_protocol(core)` 从已验证不可变核心中静态解析
这一声明，不导入或执行候选桥探测。缺失或 0 表示没有控制器资格，错误、动态或重复声明拒绝使用。
激活、中央回退、状态和新任务准入，以及薄桥的 current 控制入口，都要求受支持的控制协议。
这不改变三字段 `runtime_binding` 或 manifest 协议，也不等同于 helper 的发布锁协议。

2.1.3 将普通记录与类型化发布见证的容量预算分开：普通记录和资源仍受 4 MiB 上界约束，
发布见证按完整 before 的 base64 长度及封闭元数据计算专用上界，读取与写入使用同一边界。
中央激活/回退预览和应用在首次 prepared/目标写入前汇总原生收据、项目 binding/journal、
中央终态与失败补偿诊断的序列化预算；超限先拒绝，不截断历史原文、权限或归属前像。
容量占位只用于内存中的预算证明，不作为真实 Node/收据发布。恢复沿原固定计划与精确前像核验，
仍拒绝后续未知修改；程序升级不会自动执行恢复。`tests.test_runtime_state` 纳入实际 `ci` 组以保护这些容量边界。

显式固定任务的资源读取继续保留；helper 协议 0 的旧核心仍由合格 current 控制器在父锁保护下执行，
不会因不能担任 current 而被删除。最小协议测试夹具复制源码中真实的桥及声明，只验证各自实际覆盖的消费者；
不能靠注入一个常量冒充完整控制器，也不能把资格或文件校验当作原生角色、模型执行或发布验收。

### lib 文件归属与迁移路径

下表是本次职责归组唯一的旧路径到当前实现路径对照。修复时先确定当前 owner，再同步检查实际 imports、字符串命令、patch 目标和最小冻结白名单；旧路径只用于说明迁移，不再提供转发或回退。
当前源包使用表中的所属路径；既有任务仍通过自己的固定 pin 读取该旧 core 清单内的路径，不能按当前源码目录猜测旧任务路径。Skill 正文始终归 `platforms/shared/skills/`，`lib/skills/` 只放 Python 合同工具。

| 当前职责 | 旧路径（已移除） | 当前实现路径 |
| --- | --- | --- |
| `install`：安装与平台进程 | `lib/install_workflow.py` | [lib/install/install_workflow.py](../lib/install/install_workflow.py) |
| `install`：安装与平台进程 | `lib/install_process.py` | [lib/install/install_process.py](../lib/install/install_process.py) |
| `install`：安装与平台进程 | `lib/project_paths.py` | [lib/install/project_paths.py](../lib/install/project_paths.py) |
| `install`：安装与平台进程 | `lib/platform_process.py` | [lib/install/platform_process.py](../lib/install/platform_process.py) |
| `install`：安装与平台进程 | `lib/windows_process.py` | [lib/install/windows_process.py](../lib/install/windows_process.py) |
| `project`：项目发现与配置 | `lib/project_discovery.py` | [lib/project/project_discovery.py](../lib/project/project_discovery.py) |
| `project`：项目发现与配置 | `lib/profile_context.py` | [lib/project/profile_context.py](../lib/project/profile_context.py) |
| `project`：项目发现与配置 | `lib/project_profile_cli.py` | [lib/project/project_profile_cli.py](../lib/project/project_profile_cli.py) |
| `project`：项目发现与配置 | `lib/ensure_project_id.py` | [lib/project/ensure_project_id.py](../lib/project/ensure_project_id.py) |
| `project`：项目发现与配置 | `lib/validate_project_config.py` | [lib/project/validate_project_config.py](../lib/project/validate_project_config.py) |
| `documents`：文档与原型工具 | `lib/plan_documents.py` | [lib/documents/plan_documents.py](../lib/documents/plan_documents.py) |
| `documents`：文档与原型工具 | `lib/requirement_html.py` | [lib/documents/requirement_html.py](../lib/documents/requirement_html.py) |
| `documents`：文档与原型工具 | `lib/prototype_navigation.py` | [lib/documents/prototype_navigation.py](../lib/documents/prototype_navigation.py) |
| `documents`：文档与原型工具 | `lib/validate_prototype_workspace.py` | [lib/documents/validate_prototype_workspace.py](../lib/documents/validate_prototype_workspace.py) |
| `documents`：文档与原型工具 | `lib/standards_baseline.py` | [lib/documents/standards_baseline.py](../lib/documents/standards_baseline.py) |
| `documents`：文档与原型工具 | `lib/context_read.py` | [lib/documents/context_read.py](../lib/documents/context_read.py) |
| `hosts`：宿主适配 | `lib/apply_antigravity_setup.py` | [lib/hosts/apply_antigravity_setup.py](../lib/hosts/apply_antigravity_setup.py) |
| `hosts`：宿主适配 | `lib/render_antigravity_agent.py` | [lib/hosts/render_antigravity_agent.py](../lib/hosts/render_antigravity_agent.py) |
| `hosts`：宿主适配 | `lib/validate_claude_artifacts.py` | [lib/hosts/validate_claude_artifacts.py](../lib/hosts/validate_claude_artifacts.py) |
| `hosts`：宿主适配 | `lib/claude_instructions.py` | [lib/hosts/claude_instructions.py](../lib/hosts/claude_instructions.py) |
| `hosts`：宿主适配 | `lib/claude_options.py` | [lib/hosts/claude_options.py](../lib/hosts/claude_options.py) |
| `hosts`：宿主适配 | `lib/merge_codex_config.py` | [lib/hosts/merge_codex_config.py](../lib/hosts/merge_codex_config.py) |
| `hosts`：宿主适配 | `lib/workflow_hook_install.py` | [lib/hosts/workflow_hook_install.py](../lib/hosts/workflow_hook_install.py) |
| `hosts`：宿主适配 | `lib/workflow_hook_settings.py` | [lib/hosts/workflow_hook_settings.py](../lib/hosts/workflow_hook_settings.py) |
| `hosts`：宿主适配 | `lib/windows_hook_command.py` | [lib/hosts/windows_hook_command.py](../lib/hosts/windows_hook_command.py) |
| `skills`：Skill 合同工具 | `lib/role_skills.py` | [lib/skills/role_skills.py](../lib/skills/role_skills.py) |
| `skills`：Skill 合同工具 | `lib/shared_core_skills.py` | [lib/skills/shared_core_skills.py](../lib/skills/shared_core_skills.py) |
| `skills`：Skill 合同工具 | `lib/skill_contracts.py` | [lib/skills/skill_contracts.py](../lib/skills/skill_contracts.py) |
| `skills`：Skill 合同工具 | `lib/business_confirmation_policy.py` | [lib/skills/business_confirmation_policy.py](../lib/skills/business_confirmation_policy.py) |
| `skills`：Skill 合同工具 | `lib/qa_review_policy.py` | [lib/skills/qa_review_policy.py](../lib/skills/qa_review_policy.py) |
| `delivery`：交接与交付 | `lib/native_handoff.py` | [lib/delivery/native_handoff.py](../lib/delivery/native_handoff.py) |
| `delivery`：交接与交付 | `lib/native_usage.py` | [lib/delivery/native_usage.py](../lib/delivery/native_usage.py) |
| `delivery`：交接与交付 | `lib/qa_handoff_cli.py` | [lib/delivery/qa_handoff_cli.py](../lib/delivery/qa_handoff_cli.py) |
| `delivery`：交接与交付 | `lib/worktree_cli.py` | [lib/delivery/worktree_cli.py](../lib/delivery/worktree_cli.py) |
| `central`：中央项目资源与偏好 | `lib/runtime_project.py` | [lib/central/runtime_project.py](../lib/central/runtime_project.py) |
| `central`：中央项目资源与偏好 | `lib/role_preferences.py` | [lib/central/role_preferences.py](../lib/central/role_preferences.py) |

以下 20 个固定根文件继续保留真实实现，原因来自现有直接入口、薄桥生成字节、预校验链或固定依赖合同。

| 固定根实现 | 保留理由 |
| --- | --- |
| [lib/python_runtime.sh](../lib/python_runtime.sh) | 源码、薄项目及工具共享的受支持解释器入口；现有命令固定引用此路径。 |
| [lib/python_runtime.cjs](../lib/python_runtime.cjs) | 保留的项目本地 Windows 启动器，只消费已配置解释器与显式运行时记录。 |
| [lib/windows_bootstrap.py](../lib/windows_bootstrap.py) | 保留的跨平台启动边界，按公开 CLI 的类型化参数位置转换路径。 |
| [lib/common.sh](../lib/common.sh) | 根 setup 脚本共享的 Shell 配置、解释器与预检入口。 |
| [lib/platform_fs.py](../lib/platform_fs.py) | 薄桥完整验证 core 前必须先校验并加载的文件系统边界。 |
| [lib/runtime_store.py](../lib/runtime_store.py) | 薄桥预校验链中的内容清单、固定版本加载与完整性验证实现。 |
| [lib/windows_fs.py](../lib/windows_fs.py) | 固定 platform_fs 的 Windows 后端，保持预校验依赖链和拒绝边界。 |
| [lib/runtime_bridge.py](../lib/runtime_bridge.py) | 生成的 launcher 固定导入的资源／helper 分发实现。 |
| [lib/agent_continuation.py](../lib/agent_continuation.py) | 固定任务图 CLI 的原生身份、续用状态和错误类型依赖。 |
| [lib/worktree_policy.py](../lib/worktree_policy.py) | 固定任务图入口共享的 worktree 验证合同；交付命令实现归 delivery。 |
| [lib/standard_paths.py](../lib/standard_paths.py) | 固定任务图与 pin 工具共用的规范来源路径和领域合同。 |
| [lib/validate_project_docs.py](../lib/validate_project_docs.py) | 固定任务图 CLI 直接导入的项目文档、规范目录与规则目录验证器。 |
| [lib/runtime_pins.py](../lib/runtime_pins.py) | 固定图记录与薄桥的任务 pin、逻辑资源和项目身份读取边界。 |
| [lib/workflow_hooks.py](../lib/workflow_hooks.py) | 生成 Hook 薄桥的固定 helper 目标；生成字节与原生 Hook 行为保持。 |
| [lib/role_models.py](../lib/role_models.py) | 角色模型字段、原生产物映射和固定角色集合的真实合同。 |
| [lib/validate_antigravity_artifacts.py](../lib/validate_antigravity_artifacts.py) | 中央角色生成器按固定路径读取 AST 工具源，宿主验证也直接使用。 |
| [lib/task_graph_cli.py](../lib/task_graph_cli.py) | 公开任务图命令入口，含直接脚本导入合同，本轮受保护且保持原字节。 |
| [lib/task_graph.py](../lib/task_graph.py) | 固定任务图 CLI 与记录工具共享的图模型、合法状态及错误合同。 |
| [lib/task_graph_records.py](../lib/task_graph_records.py) | 固定任务图记录的 CAS、指纹和请求 scratch 真实读写入口。 |
| [lib/task_graph_init.py](../lib/task_graph_init.py) | 固定任务图 CLI 惰性加载的初始图组装入口。 |

[lib/__init__.py](../lib/__init__.py) 是额外的普通 Python 包标识，仅含文档字符串，不导入、不重导出 API、不设置路径或执行其他副作用。它确保可信 core 根先加入搜索路径后，项目自己的普通 `lib` 包不能取代核心。七个职责目录的 `__init__.py` 同样只含文档；固定根实现仍是上列 20 项。

## 普通入口与源包开发生成器

`install.sh` 从任意位置选择已有项目，`workflow.sh` 是源码入口，默认短命令 `awf-dev`；
Homebrew 管理正式 `awf-cli`。`--version` 显示版本、中央源根、source/formal 身份及物理载荷根。
中央项目内仅有 `.agent-workflow/` 配置、locator、薄桥和原生资源，没有 `.agent-workflow/setup_*.sh`。
检查／修复中央项目分别用 `check` 和先预览的 `repair`，不在项目内执行根 setup。

根 `setup_codex.sh`、`setup_claude.sh`、`setup_antigravity.sh` 和 `setup_all.sh` 是源包开发生成器。
仅在源包开发模式下从源包根运行；生成前先完成所选宿主预检，保留用户文件及原生设置。
聚合 setup 在首次项目写入前预检所有选中宿主，可用 `--only=claude`、`--only=codex`、`--only=antigravity` 限定：

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
bash setup_all.sh --only=codex
```

三平台都消费 `platforms/shared/skills/` 的同一份源包；普通中央安装的受管 Skill 通过锚定软链指向固定核心，
不在项目维护另一份规则源。宿主发现目录和角色格式各自保持：

| 宿主 | 指令／入口 | 角色 | Skill 目录 |
| --- | --- | --- | --- |
| Codex | `AGENTS.md`／`$xy-workflow` | 用户 `~/.codex/agents/`；项目稀疏 `.codex/agents/xy-*.toml` | `.agents/skills/` |
| Claude Code | `CLAUDE.md` → `AGENTS.md`／`/xy-workflow` | 用户 `~/.claude/agents/`；项目稀疏 `.claude/agents/xy-*.md` | `.claude/skills/` |
| Antigravity | `AGENTS.md`／`/xy-workflow` | 用户 `~/.gemini/config/agents/`；项目稀疏 `.agents/agents/xy-*.md` | `.agents/skills/` |

以上用户目录为默认示例，实际位置取入口固定的 HostPaths。源包开发生成器的角色全部生成在源码项目内，
不等同于中央安装的用户角色与项目稀疏覆盖。

### 源包可选 guard

`scripts/guard.sh` 仅适用于源包作为待审计 Git 项目一级子目录的开发布局：
脚本固定以源包父目录为审计根，读取源包根的 `project.yaml`。普通中央薄项目没有该脚本，
不能在其中运行 `.agent-workflow/scripts/guard.sh`，也不能把独立源码仓库根误当成审计根。
默认仅提示已改文件的模块归属并退出 0；在源包 `project.yaml` 配置禁止前缀后，显式严格模式命中才退出 1：

```yaml
# /path/to/project/agent_workflow/project.yaml（源包配置，可选）
deny_prefixes:
  - secrets/
  - production-keys/
```

```bash
GUARD_STRICT=1 bash /path/to/project/agent_workflow/scripts/guard.sh
```

`deny_prefixes` 仅检查审计根中的已改路径，不是操作系统写入锁，也不代替任务 `owned_paths`。

### Claude 原生生成合同

`AGENTS.md` 是精简共用入口，`CLAUDE.md` 固定为一行 `@AGENTS.md`，不复制全文。
导入会去重，但被导入正文仍占上下文，不承诺省 token，也不绕过 managed-only 等组织策略。
根导入不递归合并子目录规则。SessionStart 仅提醒恢复，不重复注入指令或项目全文。
实际加载须在 Claude 会话用 `/context` 核对，磁盘 `--check` 不能证明加载和模型执行效果。

每个生成 Custom Agent 使用原生 Skill 工具；实施者预载 `xy-code-standards`、`xy-build-verify`，
UI 按职责预载 `xy-ui-design`、`ui-ux-pro-max`、`xy-prototype-verify`，QA 预载 `xy-qa-review`。
其他 QA 专项 Skill 按描述匹配、按需读取，不扫描个人 Skill 全库存。缺失任务声明的必需 Skill 会阻止相应交付，
缺失 `ui-ux-pro-max` 阻止 UI 设计；读取与预载不授予额外写权限，也不自动启用原型阶段。
`xy-project-memory` 提供可选记忆方法，实际隔离和离线边界见[使用手册](usage.md#项目文档与可选记忆)。

`setup_claude.sh` 仅合并 `.claude/settings.json` 中带签名的辅助 Hook 条目；用户权限、其他 Hooks、
MCP、插件和 Claude Auto Memory 设置保留。原生写入保护只按显式 true 合并单键，不独占 settings 或重签 Hooks。
只接受缺失或精确薄入口，未知正文不自动迁移；用户自有同名 Agent／Skill 保留。
`--check` 对比受管产物与当前来源，拒绝过期或矛盾输出。必要时可运行本机 `claude doctor`，
工具配置或回调成功不等于模型行为验收；Hooks 详细合同见 [Hooks 说明](../platforms/shared/HOOKS.md)。

## 维护工作流与验证

Light／Full、任务分派、确认、独立 QA 和收口以[产品工作流](../product/WORKFLOW.md)为准。
Full 使用确定性任务依赖图（task dependency graph），PM 在容量与所有权边界内推进当前可执行任务，
请求依赖闭包完成后进行一次集成 QA；任务完成不会自动构成批准或可交付证明。
QA 通过后的顺序仍为受控文档投影、PM 提交评估、记忆收口、最终报告。
完整实例、图、原生交接与 worktree 方法分别按[工作流 Skill](../platforms/shared/skills/xy-workflow/SKILL.md)
的读取条件进入，手册不复制规则全文。

角色职责与权限维护在 `roles/`；工程方法与规则维护在
[代码规范 Skill](../platforms/shared/skills/xy-code-standards/SKILL.md)，设计方法与规则维护在
[设计 Skill](../platforms/shared/skills/xy-ui-design/SKILL.md)。根指令只保留关键边界和条件索引，
各 Agent 独立完整读其必需文档；长文分开分页至 EOF，未变且完整可用的已读内容直接复用，
截断或变化只恢复受影响内容。[运行记录工具](../platforms/shared/skills/xy-workflow/references/runtime-records.md)
含 `context_read.py` 有界只读入口和图工具用法，机器指纹不证明模型已读。

工作流自有 Python 调用及临时／内联 helper 都使用同一现有解释器选择器，UTF-8 文本显式读写，
不改变业务项目原工具链：

```bash
# 直接选择真实 unittest 节点仍可用；不必为了单个节点运行整组。
bash lib/python_runtime.sh -B -X utf8 -m unittest -v \
  tests.test_homebrew_packaging.ReleaseArchiveTest.test_real_archive_manual_links_resolve_without_private_docs
bash lib/python_runtime.sh -B -X utf8 lib/project/project_profile_cli.py json /path/to/agent_workflow /path/to/project
```

中央项目通过 `.agent-workflow/runtime.py` 的 `helper` 入口调用固定核心 helper，显式传任务 `runtime_binding`；
不要把源包相对路径命令直接当作中央项目命令。上下游操作必须前一步成功才继续，具体调用见
[helper 执行边界](../platforms/shared/skills/xy-workflow/references/dispatch.md#workflow-helper-execution)。

先定位现有测试节点、真实消费者和受影响调用链，再选择最小充分验证。生产代码须有受影响目标成功构建／编译与
最小可运行证据；解释型项目用实际导入／语法和关键入口执行，纯说明文档用差异与链接检查。
候选验证命令不等于必须全部运行，通过且无新缺口后停止；保留原始失败、真实退出码和完整日志，
不在 Writer、QA、PM、提交各阶段重复“保险回归”。新增覆盖、重跑、失败返工的依据沿用
[验证范围策略](../platforms/shared/skills/xy-build-verify/references/verification-scope.md)。

### 统一验证入口与风险分组

`scripts/test_workflow.sh` 统一选择源包物理根、现有 Python 解释器与 UTF-8／禁字节码参数，
保留 unittest 的真实输出和失败／中断状态，不重试、不下载依赖。无参数只显示帮助，不默认跑全套；
先用 `--list` 校验并查看实际目标，再按变更风险选择组或完整节点：

```bash
bash scripts/test_workflow.sh
bash scripts/test_workflow.sh --list ci
# 以下是独立选择示例，按受影响范围选用，不要求逐条执行。
bash scripts/test_workflow.sh service
bash scripts/test_workflow.sh central
bash scripts/test_workflow.sh tui
bash scripts/test_workflow.sh pty
bash scripts/test_workflow.sh packaging
# 也可传入现有 unittest 模块、类或方法，并与组组合。
bash scripts/test_workflow.sh tests.test_runtime_store
```

| 组 | 适用风险与范围 |
| --- | --- |
| `service` | 模型来源／偏好、模型事务、原生归属、登记／安装边界、CLI 与短命令入口 |
| `central` | 中央项目启停、固定核心／绑定、current 协调、生命周期和中央 CLI／安装消费者 |
| `tui` | 输入、终端单元格、草稿交互及选定项目流程；不隐式启动 PTY |
| `pty` | 真实伪终端键盘、窗口缩放与项目生命周期；需要 POSIX |
| `packaging` | 离线归档、手册、启动器和 Ruby Formula 安装模拟；Formula 消费者需要 Ruby |
| `ci` | 已明确的入口、中央 current／记录容量／生命周期／原生归属／短命令、pin／模型收据、三宿主共享源、需求 HTML、PTY 和离线发行组合；需要 Node、Ruby 与 POSIX |

`codex`、`claude`、`antigravity`、`prototype` 保留各自聚焦范围，`hosts` 覆盖三宿主及其共享合同。
旧四个 `scripts/test_codex.sh`、`test_claude.sh`、`test_antigravity.sh`、`test_prototype.sh`
仅薄委派到统一入口的对应组，保留原测试范围。分组不会改变直接 unittest 节点的调用方式；
入口先校验完整计划、折叠已被父模块／类覆盖的子节点并去重，未知组或节点明确拒绝，不退回全套发现。

只有广泛影响确需或明确要求时，才显式选择完整回归：

```bash
bash scripts/test_workflow.sh full
```

`full` 覆盖现有全部 `test_*.py` 模块，`ci` 是明确组合而非全套别名。完整范围包含调度、运行时、规范、原型与安装，
不能把单个风险组通过描述为全套通过。
源包优化不会自动重装／同步真实项目；仅对用户明确授权目标显式导入、选版或预览修复。
本地构建、模拟 Cellar 或某平台通过，不能扩大为远端发布、真实 Homebrew 或其他平台已经验收。

## 文档归属与历史保留

- `README.md` 只保留快速开始、版本和手册导航。
- `docs/usage.md` 维护用户操作、CLI／TUI、支持范围与恢复说明。
- `docs/development.md` 维护源码职责、开发生成器与维护入口。
- `docs/homebrew.md` 维护 Homebrew、离线发行和远程发布边界。
- `product/`、`roles/`、Skill 与 references 保持指令权威，项目模板不复制内置通用规则。

业务项目文档仍遵循已配置的 `docs/PROJECT.md`、规范和同主题计划归属；当前源包没有 PROJECT／STANDARDS 实体时，
不为说明而新建空索引。源包 `docs/plans/` 的历史 Markdown、同名 HTML 和已批准原型保留在原位，
用于恢复批准、设计与验收依据；未索引计划或历史状态不自动成为当前功能事实。
完整日志留在请求证据位置，长期正文仅归纳必要结论并引用现有证据，不新建归档树或杂记副本。

`.sync-backups` 是既有恢复材料，`dist/` 保存本地发行产物与历史；不进入运行时载荷，不因本轮结构整理批量删除。
本轮仅由 PM 在重新核对完整字节、固定 SHA、保留归档校验且确认无进程占用后，精确移除了
`dist/github-v0.1.0/` 内归档、校验与 Formula 的三份重复文件及四个空目录；`dist/` 根产物、Tap 独立历史、
release-notes 和全部 `.sync-backups` 仍保留。后续清理须先证明恢复输入与必要引用安全，归属未知或并发修改时保留。

离线发行显式加入且仅加入三份手册，禁止把整个 `docs/` 打包，避免历史计划、原型和私有材料泄入用户载荷。
手册及 README 内部链接须在实际归档／安装后的目录结构解析；构建与真实消费者验证见 [Homebrew 说明](homebrew.md#本地构建不联网不安装不发布)。
