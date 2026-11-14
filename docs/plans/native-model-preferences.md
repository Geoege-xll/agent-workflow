# 本机模型目录与子代理调用偏好

- 主题 ID：`native-model-preferences`
- 阶段：`completed`
- 模块：`native_config`、插件偏好读取与配置工作台
- 任务等级：`Full`
- 已验收版本：`3.0.0-alpha.9`

## 目标与范围

恢复本机模型发现、逐模型推理选择和插件子代理调用偏好，使配置页可以实际编辑、预览、保存与回读。当前已交付基线为工作流 alpha.9 和独立配置组件 alpha.5；保留 3.0 插件、两步确认、原型阶段、项目启停和唯一独立 QA。

Windows 继续暂停；不恢复中央运行时、TUI、旧管理器或 2.0 偏好兼容。配置保存、宿主重新加载与实际模型采纳分别判断，不以其中一项推断另外两项。

## 需求与验收

1. Codex 读取实际本机 `codex app-server --stdio` 的 `model/list`，或用户已明确配置的模型目录；保留模型对应的推理元数据、隐藏项过滤、显示名称和来源失效保护。
2. Claude 恢复实际配置根、用户菜单、当前模型及别名映射的只读投影。配置中出现不等于账户可调用；模型偏好不证明推理能力。不读取或输出凭据正文。
3. AGY 使用已核实的 `agy models` 获取本机客户端列表；其会话完整模型 ID 与自定义子代理 tier 合同分开，不将前者直接写入后者。未证实的子代理参数保持明确不支持。
4. 模型选择改变时立即按该模型重算推理选项。保留已有不兼容值并提示用户重选／清除，不顺带修改另一字段。批量编辑不使用不同模型档位的并集。
5. 原生用户／项目完整 Agent 定义维持原有编辑路径；插件缓存始终只读。新增独立调用偏好，使用原生调用身份，不仅支持内置工作流角色。

### 调用偏好合同

偏好属于独立配置工具，不是假称官方原生覆盖的配置。每个宿主在其实际用户配置根的 `native-agent-config/dispatch-preferences.json` 保存一个有界、版本化文件；项目记录按真实物理绝对目录隔离，业务项目不增加指令文件或完整角色副本。测试使用显式临时 home，不能触达真实用户设置。

文件版本为 1，字段为 `schema_version`、`host`、`defaults`、`agents`、`projects`。`defaults` 和每个 agent 记录只允许 `model`、`effort`。项目值含 `defaults`、`agents`；agent key 使用真实 native invocation name。默认偏好采用 UI 专用目标 `*`，不冒充原生 Agent 名称。未配置字段继承，预览中的 null 表示移除本层字段。

解析顺序为用户通用 → 用户该 Agent → 当前项目通用 → 当前项目该 Agent；宿主默认是未配置时的最终来源。目标明确的官方原生完整定义仍可能按其原生规则优先，界面与回执不得宣称参数投影就是运行生效。

`native_config/preference_contract.py` 是纯标准库、只读解析与解析结果投影的唯一源，不能导入 HTTP、服务、安装器或旧 manager。独立核心复用它，插件构建从同一来源投影为 `plugins/dispatch_preferences.py`，不复制第二份手写业务逻辑。文件缺失返回无偏好；损坏、危险路径或未知版本明确报错，不静默当作继承。

该只读入口支持 `--host`、`--agent`、`--project` 和用于隔离的 `--home`。输出固定的 `schema_version`、`host`、`agent`、`status`、`configured`、`preferences`、`sources`、`runtime_verified:false`，其中 preferences 使用逻辑字段 model/effort。PM 在派发前读取，按当前实际原生工具的参数与能力映射；不启动服务、不准备组件、不安装 MCP、不改变模型或权限。不支持的已配置参数阻断该次派发并报告，不能丢弃后假称已采用。

网页 context 新增 `dispatch_preferences`，包含当前范围的 `targets`，每个目标使用 `target`、`name`、`origin`、`overrides`、`effective`、`sources`、`writable`、`read_only_reason`。默认目标必须始终可定位；Codex 不伪造七个插件原生 Agent。

context 同时提供只读 `catalog_source_stamp`，与 catalog 来源摘要可比对且独立于保存 revision。来源不可得时返回 null 和中文诊断，保留偏好编辑；不在 context/render 中启动模型查询，不给旧缓存续盖新来源。

网页仍使用同一个 `/api/preview`、`/api/apply` 事务。新预览独占 `dispatch_preferences: {edits: {target: {model/effort: value-or-null}}, reset: boolean}`；不与原生文件编辑或项目启停混合。context revision 纳入偏好前像；沿用现有 TTL、一次消费、并发拒绝、no-follow 路径与恢复结果。偏好保存与服务位置参数无关，独立源码、发行包和插件只读消费者须解析到同一实际宿主配置根。

### 配置工作台验收条件

- **REQ-101：信息架构。** 顶部统一切换 Codex／Claude Code／Antigravity；“模型与推理”“工作流启停”“诊断与帮助”使用紧凑的横向分类切换，取消常驻大侧栏，首屏默认进入模型设置。提供统一的用户级／当前项目范围，项目路径按需展开，始终能判断当前编辑对象。
- **REQ-102：模型与推理。** 通用默认独立展示；逐 Agent 列表突出真实调用身份、模型、推理、继承来源和草稿状态。原生定义文件为明确的高级入口，不与调用偏好混成同一个编辑范围。保留批量修改、刷新模型目录和清除覆盖；不伪造 Codex 原生角色或将 AGY 会话模型当作子代理 tier。
- **REQ-103：独立启停。** 工作流启停有独立内容与操作区，区分已保存值、当前层覆盖、继承和后续会话加载；保留停用后的恢复说明，不混入模型保存。
- **REQ-104：草稿与保存。** 当前操作区底部固定展示未保存数量、放弃和预览并保存。不同平台／范围与调用偏好／原生／启停草稿按原合同隔离，切换有清楚反馈；预览后才确认保存。演示成功、失败和恢复，不把保存模拟冒充磁盘写入或模型实际采用。
- **REQ-105：诊断与层级。** 目录来源、详细诊断和技术说明按需查看；问题发生时就近提示原因和可执行下一步。保留“已保存／等待重新加载／实际运行未验证”的准确边界，避免整页重复警告。
- **REQ-106：视觉与可访问性。** 采用用户已选择的紧凑专业控制台，以浅色、精细表格和工具栏为主要视觉；灰白层次、清晰分割、统一间距与单一强调色。压缩重复标题与说明，主要配置集中首屏，不通过缩小必要触点或降低字号换取密度；保留系统深浅色、桌面与窄屏、可见键盘焦点、原生可操作控件及清楚标签。诊断文字不能依赖低对比度或颜色独立传意。

### 验证边界

复用 `bash scripts/test_workflow.sh` 的实际节点入口；核心重点覆盖本地目录、逐模型能力、提供方／身份来源变化、偏好继承与清除、同名身份、损坏数据、路径替换、并发预览、首次保存和恢复。网页验证两平台原问题场景、可编辑调用偏好、模型联动、刷新失败、范围切换、预览取消、保存回读、键盘与窄屏；不操作被工具禁止的 Codex App。

两产品从当前源码构建独立产物，在包外消费同一偏好；核对插件只包含纯只读解析器而未带入服务与网页。原生派发参数的实际使用与模型回复分层记录，Claude 既有模型链路无响应不能当作插件成功或失败证据。

## 方案与原型关联

当前设计权威为[第四版配置工作台](../standards/prototype/agent-configuration.html)及该页的 `section-models`／`section-activation`／`section-diagnostics`、`save-bar` 与 `preview-dialog` 状态；依赖指纹 `1085bc733faba6d07307c22711ff18baa9f63c91e1476b31dc5d89b644eac85b`。用户明确回复“认可第四版，按此实现”，批准模型／推理默认与逐身份表格、三平台和范围、项目草稿隔离、原生定义与独立启停、预览保存及诊断恢复。页面使用真实上游 Taste 方法；默认设置与表格共用 28%／30%／22%／20% 列变量及 16px 单元格内边距，平台、范围与功能导航分层，正文 14px、辅助 13px、主要触点至少 44px。继承／本层覆盖／草稿与持续保存回执分开呈现。PM 已独立对照六项需求复核五段契约；53 个关键控件、静态依赖及语法检查通过。

REQ-101 对应顶部平台／范围／项目载入与分类；REQ-102 对应 `section-models`；REQ-103 对应 `section-activation`；REQ-104 对应 `save-bar` 与 `preview-dialog`；REQ-105 对应 `section-diagnostics`；REQ-106 由响应式、深浅色和控件状态共同体现。批准时操作序列为 Codex 默认修改与预览 → Claude 身份表与批量 → 用户级与 atlas／orbit 草稿往返 → 原生定义与独立启停 → 诊断异常和恢复 → AGY 不支持项。原型中的虚构路径与数据只供评审，不能进入生产。前三版均被否定，不能解锁正式实现；其前像、原始日志和历史指纹保留在同请求 scratch 的既有恢复归档，第四版证据另保护于 `dist/evidence/console-prototype/fourth-review-evidence.zip`。

网页实现归 `native_config/web/{index.html,console.css,console.js}` 与 `tests/test_plugin_console.py`，由独立实现代理完成。保留现有请求、三类草稿、异步归属及真实 HTTP／持久化／目录／安全事务合同，按职责重构呈现层；未把演示定时器、反馈桥、需求链接或页内契约复制到生产。真实能力的最小映射为：原生 input＋datalist 保留自定义模型 ID、空目录和未知已保存值，沿用获准控件视觉；被遮蔽上层值缺失时显示“继承值待预览”，由现有预览接口解析；实际异步平台 Tab 使用方向键定位及 Enter／Space 激活。以上不新增模型能力或接口字段，持续可访问的来源与继承说明保留。

### 实现责任与依赖

- 核心作者：`native_config/` 下必要的 Python 核心、目录读取、纯偏好合同和 CLI/HTTP/MCP 接入及对应测试；不得编辑网页或打包器。先交付可执行合同与核心证据。
- 网页作者：核心合同固定后，修改现有 HTML/JS/CSS 及 `tests/test_plugin_console.py`；沿用现有 tokens、表格和预览方式，新增清楚区分的调用偏好编辑区。目录按当前范围按需读取、缓存复用，来源变化和失败不覆盖草稿。
- 插件／打包作者：核心合同固定后，与网页并行完成纯只读解析器投影、派发前调用说明、两产品构建与版本、发行合同测试。不得把配置服务变成工作流必需运行依赖。
- PM：协调单写者边界、采用必要的合同调整，维护本文与现有使用说明、准备发布；一名独立只读 QA 在集成候选完成后验收，返工复用原 Reviewer。

本机发现方法参考 Git 中的 `7d87331`、`625db67` 与 `50e11eb`；只保留已成立的本地目录、编辑前读取、逐模型能力和来源守卫语义，不引入旧 manager 运行依赖。通用原型评审工具的资源归属见 [工作区主题](workflow-document-lifecycle.md)。

## 当前进展与恢复入口

已验证：alpha.9 三渠道及本机三端载荷、组件 alpha.5 完整性与准备、配置服务和浏览器打开、模型偏好保留。正式 UI、纯读取入口和隔离配置保存闭环已各自在原范围内验收；具体来源见后两节。

待验证：三宿主新会话的完整工作流与指定子代理模型实际采纳、Codex App GUI、后台 A/B 并行与完整读屏认证。既有会话抽查只证明前台规划期间追问排队后正常回答，未发现 PM 拒绝；它没有覆盖后台子代理并行，不构成修改调度器的依据。AGY 会话完整模型与子代理 tier 继续分开。

下一步按实际宿主能力完成上述运行验收；Codex Hook 信任必须经官方 `/hooks` 审阅，不能改写信任。Windows 保持暂停。未来升级仍先收尾或交接活动任务，再替换插件物理资源；本次文档整理不更改本主题已交付版本。

## 验收结果与当前已交付行为

工作流 [3.0.0-alpha.9](https://github.com/Geoege-xll/agent-workflow/releases/tag/v3.0.0-alpha.9) 与独立配置组件 [0.1.0-alpha.5](https://github.com/Geoege-xll/agent-workflow/releases/tag/native-agent-config-v0.1.0-alpha.5) 已发布。插件载荷来自 `aa3b6f559cc692b738618d16f66009f8ec02f9d2` 的 [Linux／macOS current CI](https://github.com/Geoege-xll/agent-workflow/actions/runs/43436450887)，各 590 项测试通过、保留 4 项既有跳过；三个官方 Git 来源经[发布作业](https://github.com/Geoege-xll/agent-workflow/actions/runs/43438890253)更新，完整文件与权限匹配同一候选。

本机通过官方客户端更新后，Codex、Claude、AGY 均实际报告 alpha.9 且启用；2015／2022／2020 个安装文件分别与最终 CI ZIP 字节及执行位一致，旧名称安装已移除。真实 alpha.4 原库存保留，正式 alpha.9 启动器成功下载校验并准备 alpha.5；三端 doctor 完整性通过，服务 ready，浏览器打开成功。三个调用偏好文件和 Codex／Claude 的原生模型、推理、默认 Agent 字段与升级前一致；其他 AGY 插件保持原状态。完整本地交付证据留存，不提交用户配置或认证内容。

普通平台／范围／分类切换直接保留草稿并反馈；确认弹窗只用于明确放弃或预览后的保存。正式验收已覆盖实际磁盘保存／回读、平台和两个项目草稿、逐模型推理、目录失败、来源变化、真实第二文件发布故障及恢复收据、键盘、390px 窄屏与深浅色，使用隔离配置与真实生产服务，未触真实用户设置。

alpha.9 将历史库存 BUILD／原包完整性认证与当前完整 ABI 校验分开。公开归档入口、发行装配消费者、当前运行选择和登记重试仍严格；旧包只认证保留，不执行旧代码，不做 2.0 兼容。已补真实历史形态升级、准备失败保留／重试和三个身份文件逐项缺失负控，并在保留本机原 alpha.4 库存的情况下完成正式 alpha.5 准备。独立 QA 接受五路径及 30 条工程规则；既有完整失败日志保留。

## 批准依据与必要证据

- 批准依据：用户批准完整本机模型目录与四层调用偏好方案；配置工作台选择先原型后实现，明确回复“认可第四版，按此实现”。具体视觉依据及指纹见第 3 节，前三版不能解锁实现。
- 验收证据：alpha.9 的两系统 CI、三渠道发布作业和正式 Release 链接见第 5 节；正式 UI 的唯一 QA、组件摘要和原失败证据如下。

本请求唯一 Reviewer 已最终 PASS：四路径、62 条规则，Pack SHA `1d21b53194e4522f9d80a4e152c405fecbae5ad88d7ee63d0807bd119c50b65f`、diff SHA `c5482b04afe365404012be5cdae5c00ef08254342b66a2c97cc85ff2516dac63`；PM 已实际校验 schema 2 交接。初审发现确认放弃后焦点落在已禁用按钮，以及导航 CSS 字面换行；原作者修复后以三事务旧负控／新正控、后续 Tab、桌面 flex／4px 与窄屏完成增量复核。初始规则选择遗漏也已补齐，没有换 Reviewer 或重复无关全套。

独立 alpha.5 ZIP 的三网页、33 成员及全部 BUILD 摘要已核对，SHA 为 `0c8c7e07de79c18b8747c0686555085020955b820fa0c5fbedeeb090e58f52ad`。原本地候选、成功 CI 包、真实 Release 下载及本机安装逐字节一致，固定 descriptor 为 published；alpha.9 薄安装器修复未改变该组件。完整生产证据为 `dist/evidence/console-prototype/production-implementation-evidence.zip`，返工及原 FAIL 资料在本请求 scratch 的 `production-rework-evidence.zip`／`qa-initial-review.zip`。三宿主重新加载、指定模型实际采纳、Windows 和完整读屏认证仍不由 UI QA 或安装回执推断完成。

### 历史源码与证据保留

同一独立 Reviewer 的首轮发现并关闭两项问题：偏好必须按完整最终事务验证受影响继承目标，不能依赖编辑顺序；新增偏好测试必须进入现用 CI 显式清单。修复后七个精准节点和两组实际测试清单验证通过，14 个偏好节点已纳入 `native-config` 与 `current`。浏览器验证包含真实保存／回读、三草稿、来源变化、异步意图、键盘及 390px 窄屏；全部原始失败和成功证据保留。

修复后独立 ZIP 的本机源码构建 SHA 为 `d6a1f370df4c0015eda0a2ae3c06e57c537ec586ab031bc134dbaf435f473851`，30 条目与冻结载荷一致，包外隔离执行通过。发布使用成功 CI 的真实产物，实际 Release 摘要另行核验，不以本机归档名推导已发布状态。

alpha.8 首轮 CI 的两项夹具遗漏、alpha.9 历史库存／当前 ABI 混用的原失败与精准修复均保留；源码 PASS、发行核验与本机安装分别记录，不相互替代。更早 alpha.7／组件 alpha.4 的源码验收仍是历史结论，不能冒充当前安装版本。

必要原始材料仍位于 `dist/evidence/local-plugin-audit/`、`dist/evidence/native-model-preferences/` 与上述配置工作台证据区；本轮不删除或移动它们。alpha.9 整体交付证据归档为 `dist/evidence/native-model-preferences/alpha9-delivery-evidence.zip`，SHA `0b54c161dc9681fba8f341765dbe989d776eef863619cc4282ccb61690a9cacf`。

本轮仅重组已跟踪正文；完整历史、原实施次序和原始证据索引可从[整理前 Git 原文](https://github.com/Geoege-xll/agent-workflow/blob/f63a98bedd9613dbfcf35dd5bbd97253f26f8c56/docs/plans/native-model-preferences.md)恢复。
