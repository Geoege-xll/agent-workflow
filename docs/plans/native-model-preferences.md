# 本机模型目录与子代理调用偏好

状态：已发布并完成本机安装核验。用户已选择完整方案、沿用现有规范直接实现；源码独立 QA、远程发行和本机安装分别验收，指定模型实际运行仍按以下边界记录。

## 当前交付

工作流 [3.0.0-alpha.7](https://github.com/Geoege-xll/agent-workflow/releases/tag/v3.0.0-alpha.7) 与独立配置组件 [0.1.0-alpha.4](https://github.com/Geoege-xll/agent-workflow/releases/tag/native-agent-config-v0.1.0-alpha.4) 已发布。最终载荷来自 `d61b8c4b997e93d91664abd1807476af768027e9` 的 [Linux／macOS current CI](https://github.com/Geoege-xll/agent-workflow/actions/runs/43370630507)，三个官方 Git 来源经[发布作业](https://github.com/Geoege-xll/agent-workflow/actions/runs/43371302213)验证并更新。

本机通过官方客户端更新后，Codex、Claude、AGY 均实际报告 alpha.7 且启用；169／176／174 个安装载荷文件分别与最终 CI ZIP 逐字节一致。组件 alpha.4 实际 Release 下载与摘要核验、安装及 doctor 完整性检查通过；服务 ready。三端只读 context 均包含可写通用偏好入口，Codex 无原生文件、Claude 仅插件角色的入口问题已覆盖；现有模型／提供方／推理和默认 Agent 字段保持原值。完整记录位于 `dist/evidence/native-model-preferences/`，不会提交用户配置或认证内容。

源 CI 首轮发现测试运行器的独立清单／隔离样本遗漏新偏好模块；原作者补齐后 23 项验证和同一 Reviewer 增量复核通过，随后两系统 CI 成功。真实发行描述也经同一 Reviewer 单文件复核；原失败、源码 PASS、CI 修复 PASS 和发行绑定 PASS 均保留。

安装成功不等于当前会话已重新加载。更新后使用新会话；Codex Hook 仍遵循官方 `/hooks` 审阅，未改写信任。Codex App GUI、指定子代理模型实际采纳及后台 A/B 并行不因本次安装核验而宣称通过；Windows 继续暂停。

## 已接受的源码基线

2026-11-13 接受工作流 `3.0.0-alpha.7` 与独立配置组件 `0.1.0-alpha.4` 的本轮源码。三端目录来源、通用／逐 Agent 四层偏好、单次预览事务、原生定义与调用偏好模式、缓存失效及纯只读插件接入均已实现；现有工作流两步确认、原型和项目启停保持。

同一独立 Reviewer 的首轮发现并关闭两项问题：偏好必须按完整最终事务验证受影响继承目标，不能依赖编辑顺序；新增偏好测试必须进入现用 CI 显式清单。修复后七个精准节点和两组实际测试清单验证通过，14 个偏好节点已纳入 `native-config` 与 `current`。浏览器验证包含真实保存／回读、三草稿、来源变化、异步意图、键盘及 390px 窄屏；全部原始失败和成功证据保留。

修复后独立 ZIP 的本机源码构建 SHA 为 `d6a1f370df4c0015eda0a2ae3c06e57c537ec586ab031bc134dbaf435f473851`，30 条目与冻结载荷一致，包外隔离执行通过。发布使用成功 CI 的真实产物，实际 Release 摘要另行核验，不以本机归档名推导已发布状态。

目录和参数投影仍不证明指定模型实际执行。AGY 完整会话模型与子代理 tier 保持分离；Codex App GUI、真实后台 A/B 调度及具体模型采纳按各自证据验收。追加的用户会话审计只证实前台规划期间追问排队后正常回答，未发现被 PM 拒绝，也未覆盖后台子代理并行；不据此更改调度器。

## 目标与边界

修复配置页无法满足当前插件子代理模型／推理配置需求的问题，恢复 2.x 已成立的本地模型发现语义。保留现有 3.0 插件、两步业务确认、原型阶段、独立 QA 和未发布 alpha.4 的项目启停。Windows 继续暂停，不恢复中央运行时、TUI 或旧管理器依赖。

1. Codex 读取实际本机 `codex app-server --stdio` 的 `model/list`，或用户已明确配置的模型目录；保留模型对应的推理元数据、隐藏项过滤、显示名称和来源失效保护。
2. Claude 恢复实际配置根、用户菜单、当前模型及别名映射的只读投影。配置中出现不等于账户可调用；模型偏好不证明推理能力。不读取或输出凭据正文。
3. AGY 使用已核实的 `agy models` 获取本机客户端列表；其会话完整模型 ID 与自定义子代理 tier 合同分开，不将前者直接写入后者。未证实的子代理参数保持明确不支持。
4. 模型选择改变时立即按该模型重算推理选项。保留已有不兼容值并提示用户重选／清除，不顺带修改另一字段。批量编辑不使用不同模型档位的并集。
5. 原生用户／项目完整 Agent 定义维持原有编辑路径；插件缓存始终只读。新增独立调用偏好，使用原生调用身份，不仅支持内置工作流角色。

## 调用偏好合同

偏好属于独立配置工具，不是假称官方原生覆盖的配置。每个宿主在其实际用户配置根的 `native-agent-config/dispatch-preferences.json` 保存一个有界、版本化文件；项目记录按真实物理绝对目录隔离，业务项目不增加指令文件或完整角色副本。测试使用显式临时 home，不能触达真实用户设置。

文件版本为 1，字段为 `schema_version`、`host`、`defaults`、`agents`、`projects`。`defaults` 和每个 agent 记录只允许 `model`、`effort`。项目值含 `defaults`、`agents`；agent key 使用真实 native invocation name。默认偏好采用 UI 专用目标 `*`，不冒充原生 Agent 名称。未配置字段继承，预览中的 null 表示移除本层字段。

解析顺序为用户通用 → 用户该 Agent → 当前项目通用 → 当前项目该 Agent；宿主默认是未配置时的最终来源。目标明确的官方原生完整定义仍可能按其原生规则优先，界面与回执不得宣称参数投影就是运行生效。

`native_config/preference_contract.py` 是纯标准库、只读解析与解析结果投影的唯一源，不能导入 HTTP、服务、安装器或旧 manager。独立核心复用它，插件构建从同一来源投影为 `plugins/dispatch_preferences.py`，不复制第二份手写业务逻辑。文件缺失返回无偏好；损坏、危险路径或未知版本明确报错，不静默当作继承。

该只读入口支持 `--host`、`--agent`、`--project` 和用于隔离的 `--home`。输出固定的 `schema_version`、`host`、`agent`、`status`、`configured`、`preferences`、`sources`、`runtime_verified:false`，其中 preferences 使用逻辑字段 model/effort。PM 在派发前读取，按当前实际原生工具的参数与能力映射；不启动服务、不准备组件、不安装 MCP、不改变模型或权限。不支持的已配置参数阻断该次派发并报告，不能丢弃后假称已采用。

网页 context 新增 `dispatch_preferences`，包含当前范围的 `targets`，每个目标使用 `target`、`name`、`origin`、`overrides`、`effective`、`sources`、`writable`、`read_only_reason`。默认目标必须始终可定位；Codex 不伪造七个插件原生 Agent。

context 同时提供只读 `catalog_source_stamp`，与 catalog 来源摘要可比对且独立于保存 revision。来源不可得时返回 null 和中文诊断，保留偏好编辑；不在 context/render 中启动模型查询，不给旧缓存续盖新来源。

网页仍使用同一个 `/api/preview`、`/api/apply` 事务。新预览独占 `dispatch_preferences: {edits: {target: {model/effort: value-or-null}}, reset: boolean}`；不与原生文件编辑或项目启停混合。context revision 纳入偏好前像；沿用现有 TTL、一次消费、并发拒绝、no-follow 路径与恢复结果。偏好保存与服务位置参数无关，独立源码、发行包和插件只读消费者须解析到同一实际宿主配置根。

## 实施归属与顺序

- 核心作者：`native_config/` 下必要的 Python 核心、目录读取、纯偏好合同和 CLI/HTTP/MCP 接入及对应测试；不得编辑网页或打包器。先交付可执行合同与核心证据。
- 网页作者：核心合同固定后，修改现有 HTML/JS/CSS 及 `tests/test_plugin_console.py`；沿用现有 tokens、表格和预览方式，新增清楚区分的调用偏好编辑区。目录按当前范围按需读取、缓存复用，来源变化和失败不覆盖草稿。
- 插件／打包作者：核心合同固定后，与网页并行完成纯只读解析器投影、派发前调用说明、两产品构建与版本、发行合同测试。不得把配置服务变成工作流必需运行依赖。
- PM：协调单写者边界、采用必要的合同调整，维护本文与现有使用说明、准备发布；一名独立只读 QA 在集成候选完成后验收，返工复用原 Reviewer。

## 验证与发布

复用 `bash scripts/test_workflow.sh` 的实际节点入口；核心重点覆盖本地目录、逐模型能力、提供方／身份来源变化、偏好继承与清除、同名身份、损坏数据、路径替换、并发预览、首次保存和恢复。网页验证两平台原问题场景、可编辑调用偏好、模型联动、刷新失败、范围切换、预览取消、保存回读、键盘与窄屏；不操作被工具禁止的 Codex App。

两产品从当前源码构建独立产物，在包外消费同一偏好；核对插件只包含纯只读解析器而未带入服务与网页。原生派发参数的实际使用与模型回复分层记录，Claude 既有模型链路无响应不能当作插件成功或失败证据。

QA 通过后再更新当前功能说明、发布说明与主页；发布配置组件新预发行、生成经实际下载核验的固定描述，再发布工作流插件新预发行及三个 Git 分发分支，最后更新本机。未发布候选不能伪装远程发布。本轮现有 alpha.6 会话继续使用原物理包，更新安排在工作与交接收尾后；不改正在执行任务的资源根。

审计原始证据位于忽略提交的 `dist/evidence/local-plugin-audit/`。本轮唯一临时目录由 `task_graph_cli.py scratch` 分配，完整必要日志在清理前转存 `dist/evidence/native-model-preferences/`；不清其他任务或用户资料。原未跟踪迁移文档保持原样。

本机模型发现参考既有 `7d87331` 的原生 Codex 目录接口、`625db67` 的编辑前读取／逐模型档位交互，以及 `50e11eb` 的来源守卫与 Claude 配置投影；独立组件未引入旧 `manager` 的运行依赖。纯 reader 与保存核心共享格式，项目按物理根隔离；该持久化格式不迁移旧中央偏好。
