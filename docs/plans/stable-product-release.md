# 工作流与配置工具正式发行

- 主题 ID：`stable-product-release`
- 阶段：`completed`
- 模块：版本、独立组件发行、三平台 Git 分发与本机安装
- 任务等级：`Full`
- 已验收版本：`3.0.8`

## 目标与范围

本轮发布 `xy-workflow 3.0.8`，插件继续使用已发布的 Native Agent Config `0.1.6`。上一版 `3.0.7` 的两项独立验收分别记录在 [UI 与 QA 整改](ui-qa-audit-remediation.md) 和 [受管计划改进](plan-document-quality.md)。

上一版已正式发布xy-workflow `3.0.6`／Native Agent Config `0.1.5`，并通过官方客户端升级本机三端插件和独立组件。交付自动补齐缺失内置原生Agent、简洁名称列表、单一搜索焦点、调用偏好自动准备目录、统一工具外壳及画布原生滚动边界。升级后已完成旧版本与重复产物清理，保留模型、推理、项目启停、原稿及评审记录。功能与边界见[模型配置主题](native-model-preferences.md)和[工具外壳主题](workbench-solid-glass-style.md)。

只消费同一完整来源SHA的成功CI候选：先独立组件发布并真实下载核验，再生成published描述和最终插件来源，最后发布插件、三条stable及本机官方更新。保留现有模型、启停、安装范围和旧服务；插件安装不自动创建全局原生定义。源码QA、正式安装、宿主新会话和真实模型执行分别取证。

上一轮已在具体file HTML完整交付入口整改通过唯一独立QA后，发布xy-workflow `3.0.4`、升级本机三端插件，并用正式入口处理mt-shop交付目录。当时Native Agent Config保持已发布 `0.1.3`，没有修改descriptor或重复发布；旧证据继续保留，见[评审主题](workflow-document-lifecycle.md)。

上一轮3.0.3／0.1.3已完成配置页连接与指定布局、双网页／唯一原稿评审、feedback4精简及live5升级；3.0.2／0.1.2作为历史保留，功能分别归模型偏好和原型评审主题，旧证据保持。

现有构建、组件描述和远程发布器已支持正式渠道，复用唯一版本与发行来源。保留两独立产品、唯一构建来源、实际下载摘要、正式宿主入口和配置偏好；不恢复 2.x、Windows 或其它安装渠道。

## 需求与验收

- 本轮在两个整改任务各自验收后，先发出独立 `0.1.6` 并核对下载，再由最终插件来源绑定其正式地址和摘要。两个 GitHub CI 作业和三端实际本机安装均有独立回执。
- 3.0.6 阶段的首轮 unpublished 描述仅供候选，正式插件绑定实际发布的 0.1.5 摘要。P1／P2 协议沿用既有版本。
- Native首次发行后其产物闭包冻结；最终插件CI重建Native须与首次正式包同字节。只使用现有构建者、描述生成器和publisher，不在本机运行会扫描未跟踪资料的build_candidates。
- 官方升级后逐项核对版本、载荷及偏好保留。新控制台仅在固定宿主子state保存连接，不自动删除或停止旧state中的65352；不修改用户信任、特性开关或实际全局Agent文件。

以下REQ-601—606为上一轮3.0.4已完成发行范围，历史语义保持。

- REQ-601：本轮目标为工作流3.0.4、配置工具仍为已发行0.1.3；构建、provenance、归档和GitHub Release使用真实正式版本，不带prerelease标记。尚未发布／安装时不先写成完成；保留旧基线。
- REQ-602：正式与预发行版本／渠道必须匹配，拒绝混合、降级和同版不同载荷；复用唯一版本判定，不增加手工第二套发布器。
- REQ-603：三平台具备正式 Git 分发引用与对应市场身份；历史 alpha 来源保留可审计，公开安装说明以当前正式入口为准。命令名 xy-workflow 与现有调用偏好身份保持。
- REQ-604：组件0.1.3既有正式资产和published固定描述保持；从本轮同一最终源码的成功CI候选发布插件及三渠道，拒绝未发布地址或本地重建包冒充CI产物。
- REQ-605：覆盖正式／alpha 版本匹配、候选消费、发行摘要、上游历史库存保留及固定身份文件；必要 CI 入口真实收集，不删除旧负控造绿。
- REQ-606：任务／资源收尾后通过官方客户端升级本机 Codex、Claude、AGY；核对真实版本、载荷与偏好保留。安装、重新加载和实际模型采纳分别说明。

## 方案与原型关联

版本与渠道判定、构建者、候选编排、发行描述、发布消费者和宿主安装各有单一职责。新增正式渠道由现有发布器投影，不建立新脚本平行维护；命名仍由唯一 command_identity 声明。组件内容只随源版本与其必要身份变化，不引入新配置功能。

本轮按已批准第六版配置工作台和最终评审工作台实现后发版，UI依据、功能验收分别见[模型偏好主题](native-model-preferences.md)和[评审主题](workflow-document-lifecycle.md)。来源技能及公共按需加载见 [角色技能主题](role-skill-routing.md)，文档质量见 [计划规范主题](plan-document-quality.md)。

## 当前进展与恢复入口

### 3.0.8 发布范围与后续实测

`v3.0.8` 已设为 GitHub 最新正式版，标签指向 `c1759ebf00d00687dbec2469cd3172de5eac070c`。首轮 CI 发现仅原型入口提前引用下游派发细则，另有文档目录断言与已批准规则冲突。修复经独立 QA 复核，最终 macOS、Ubuntu 各执行 1,197 项，分别通过 1,192 和 1,191 项，其余分别跳过 5 和 6 项。三端 stable 分支由同一成功候选发布。8 项公开附件重新下载后的 SHA-256 全部匹配，独立组件 `0.1.6` 包与既有发行一致。[正式发行](https://github.com/Geoege-xll/agent-workflow/releases/tag/v3.0.8) · [双平台 CI](https://github.com/Geoege-xll/agent-workflow/actions/runs/44679144597) · [三端分发](https://github.com/Geoege-xll/agent-workflow/actions/runs/44681896028)

本机已启用三个客户端的正式来源。Codex、Claude Code、Antigravity 分别核对 2,386、2,385、2,382 个安装文件，内容及可执行位均与正式包匹配。Codex 新启动的 app-server 发现正式来源的 17 个 Skill，本地候选为 0。Claude 用户级候选已停用，Antigravity 已用正式分支替换候选。

本机 Codex 的两项激活状态另外跟踪。宿主将 SessionStart Hook 标记为 `modified`，需在官方 `/hooks` 审阅。七份用户级原生角色仍逐字节匹配 `3.0.7` 正式模板，引用的旧缓存已被宿主移除；配置组件 `0.1.6` 的只读重绑预览返回 0 项。更新这七份定义须保留旧原件，并验证正式组件实际生成的新文件。

独立 QA 已通过冻结源码、三端候选包及原型目录分组恢复。三个宿主的插件均包含 17 个使用英文描述的 Skill。项目维护者批准先发布并更新本机，下列三项保留为发布后的真实会话验收。

| 项目 | 已验证 | 后续通过条件 |
| --- | --- | --- |
| Claude Code 普通 Auto | 隔离会话已加载插件及原生角色，首次模型调用返回 HTTP 429 | 在 Quotio 新开普通 Auto 会话，交办业务任务，确认 PM 完成原生派发，全程无需为插件自身的来源校验切换模式或重复授权。 |
| Codex 与 Antigravity 持续调度 | Codex 官方客户端已发现 17 个 Skill，隔离账户未登录模型。两端均已核对打包入口。 | 在两端分别验证 A 执行时可以讨论、派发独立的 B，重叠的 C 可以追加给合适的原执行者，任务记录和原生回执一致。 |
| 自测范围与上下文占用 | 已通过按实际输入变化判断测试证据能否复用、按章节恢复规范的定向回归。 | 从一次修复后的业务会话核对文案变更后的测试命令及压缩后的读取范围，区分必要复验、重复输出与缓存输入，再评估实际节省。 |

### 3.0.7／0.1.6 最终交付

独立组件先由 [组件候选 CI](https://github.com/Geoege-xll/agent-workflow/actions/runs/44284219147) 生成，经实际下载验证后固定到插件。最终插件来源为 `e9c1f3043accc64e01155de833cbf62add2f73f5`，[最终 CI](https://github.com/Geoege-xll/agent-workflow/actions/runs/44287770931) 在 macOS 和 Ubuntu 各收集 1,053 项，1,049 项通过、4 项因宿主或隔离能力跳过。最终归档 `14421430972` 的七包及校验单通过复核，独立组件包和已发行包逐字节一致。

[三端分发](https://github.com/Geoege-xll/agent-workflow/actions/runs/44291116380) 完成正式分支更新，实际 Git 树的路径、内容及执行位与最终归档一致。[xy-workflow 3.0.7](https://github.com/Geoege-xll/agent-workflow/releases/tag/v3.0.7) 已设为 Latest，八份资产的服务端摘要及重新下载一致。[Native Agent Config 0.1.6](https://github.com/Geoege-xll/agent-workflow/releases/tag/native-agent-config-v0.1.6) 为独立正式发行。

本机三个官方客户端均回读到已启用的 3.0.7，安装文件与正式包逐项匹配。Claude 保持原用户级安装范围及项目启用状态，Claude 和 Antigravity 的官方插件校验通过。三端均核对了组件 0.1.6 的安装完整性，Codex 控制台服务就绪。Codex 七份既有原生定义已重绑新版资源，模型、推理字段和其余用户内容逐项核对保留。此次本机证据覆盖安装、发现、组件状态与重绑，未执行 Codex App 图形界面新会话或真实模型推理。

两项独立 QA 的任务包及回执和发布、分发、本机证据已在本机归档 `dist/evidence/stable-product-release/stable-307-016-delivery-evidence.zip`。共 41 项证据及摘要索引，SHA-256 `861570acf5fa0822f2c00d7739851f8a34822571a1a2dbdfd08c01176723f36f`。

### 3.0.6／0.1.5最终交付

正式组件来源为`be11bbb64aa0beca8083fcf2da8b89208066d5c7`，成功CI为`44056747104`，两平台各712项、4项既有跳过。Native [0.1.5 Release](https://github.com/Geoege-xll/agent-workflow/releases/tag/native-agent-config-v0.1.5)为正式非draft／prerelease、latest=false，原ZIP和sidecar服务端摘要、真实重下载与CI原成员均匹配；ZIP SHA为`06885f7f2f2a675f8a61f0914532f01ca1ffdeb0613fcbd8b3f8ba3cfd7f6c37`。首次正式发行后Native源码及独立README常量冻结，B重建包与其逐字节一致。

最终插件来源为`bf1911998788fe9fa1b834cf8121b51fdb50b0da`，成功CI为`44060254474`，两平台各714项、4项既有跳过。唯一附件`14318612349`外SHA为`d2411505ebd124e5436353d168c57460fe467a231e26ac1641cb396ad6755e43`；17成员／七包及sidecar完整核验通过。[3.0.6 Release](https://github.com/Geoege-xll/agent-workflow/releases/tag/v3.0.6)八资产的服务端摘要和真实下载均匹配同B来源，正式非draft／prerelease且已设Latest。现有publisher工作流`44063960826`同B成功，普通atomic发布，未使用force或本机替代构建。

三个实际stable提交为Codex `d14a8a3fd9fe12d523d4827551353a99e52998cf`、Claude `69a46eef522e3c6bb21c1618a61d9270c7e6a292`、AGY `6546aca25967fd8f65d9e512f59088778edf7cb9`。独立QA直接读取真实远端Git树和blob，2338／2336／2333路径、字节与执行位逐项匹配B候选。最初A的双平台旧原型fixture失败原日志完整保留；原作者仅修测试对象范围，保留业务iframe负控。同轮发现并修复受管旧工具重新准备问题：只识别真实3.0.4／3.0.5的固定17项闭包，新19项仍完整严格，旧字节不能直接作为当前工具打开；真实旧helper→新helper红绿及变造负控均留证。

本机官方列表均为xy-workflow3.0.6 enabled；Codex CLI市场及App持久cache、Claude用户级cache、AGY实际cache的2336／2334／2332载荷字节与执行位均匹配B。其他21个Codex及2个AGY插件身份、版本与启用状态不变；Claude当前源码项目projectEnabled=false及user安装范围保持。Native0.1.5实际准备成功，三宿主doctor均integrity verified；Codex／Claude当前服务ready，AGY服务未启动，不将安装与完整性推断为模型实际运行。

Codex官方升级已自动移除3.0.5旧cache。七份既有原生定义经正式新cache闭包、两manifest及内嵌四类规范摘要核验后，按原字节CAS仅替换一处3.0.5→3.0.6资源路径；其余字段及正文不变。60项配置采样中53项原字节相同，仅这七项是批准的路径变化，模型、推理、调用偏好及项目设置保持。正式Codex维护open再次验证七定义无重写。mt-shop原55页受管外壳刷新为当前版本，55份HTML、gitignore及三个旧评审请求原字节不变；两个外部feedback-hub入口未触碰。

按用户后续清理授权，已移除19个旧安装缓存／组件目录或原包、28个重复候选／测试展开路径、40个退役生成物／旧启动页，以及8份可重下载Release副本。合计文件逻辑大小`2419270722`字节，约2.42GB，不将其等同APFS实际释放空间。Codex／Claude版本目录仅3.0.6，Native库存及认证原包仅0.1.5；旧Tap预览、alpha.8二进制副本清除，必要诊断文本和验收归档保留。用户评审、草稿、业务资料、旧评审所需资源、外部runtime和Git历史不在删除范围。无新增备份或旧任务兼容迁移。

### 发行过程与此前暂停事实

用户在本地候选验收通过后明确要求“开始发布与本机升级”，现恢复3.0.6／0.1.5正式发行。沿用已完成的唯一QA和本地浏览器证据，先提交完整来源并取得新成功CI，先发行Native并真实下载固定，再取得最终插件CI、发布三个stable和升级本机。当前仍未创建本轮Release或完成本机更新；下文暂停描述保留为此前阶段事实，不再阻止本次已授权执行。

用户随后明确暂停发行，先按Solid Glass统一Agent控制台、交付外壳和评审工作台的工具视觉，见[统一外壳主题](workbench-solid-glass-style.md)。三页原型已获用户确认，生产实现和隔离候选验收按该主题继续，不自动恢复发行。main已保留A提交`97a8d31ebdc8baef5b0a4969a9835e37c88e49cf`；CI`44033709555`两系统各707项、同一旧集成夹具失败，候选跳过。夹具已由原作者改为真实插件来源并精准验证通过；旧服务并存的状态寻址修复经同一Reviewer增量复核通过。当前新增视觉与滚动规则的本地证据不替代新的完整CI。3.0.6／0.1.5均未创建正式Release或tag，三个stable及本机安装未更改。此前“准备发行”的进展不构成继续发行授权。

换肤前的3.0.6／0.1.5阶段候选曾冻结21路径，diff SHA `8429453c819f5384cfa62f3aabcd1a0b63687e635a02d6411e4606df591174c4`；唯一Reviewer当时源码审查无剩余重要问题。该阶段独立Native候选ZIP38成员／BUILD37项逐字节匹配冻结闭包；随后增加共享主题和许可，当前包的资源闭包与实际验收以工具外壳主题记录为准，不沿用旧包摘要。当前unpublished绑定无下载URL。早期9项版本target仅保留于原执行会话工具输出，未单独落盘完整日志；不补造历史日志，后续CI另保留完整权威输出。正式发行与安装尚未执行。

以下为3.0.5／0.1.4已完成的发行与本机更新，不代表上述候选已发布。

本轮功能、清理、恢复与published绑定均由同一Reviewer按实际delta复核PASS，PM实际机器validate有效；初始有效包SHA `124a419bb512676281b505847ee6b56dffa2601070660da6acba67356b59ff87`、交接SHA `ef437fa6b0fd8f6d55e5c1077f99f30bc60777401abd9d3512b20945b5d305b0`及后续各交接均完整保留。正式Release、三stable及本机升级已完成，不重复不变功能测试或新建Reviewer。

首轮A `30f2e93cf52bf9e19215ed622c062aebbf670ec2` 的CI `44004116389` 两系统各697项、5个验证入口夹具断言失败、4项既有跳过，候选跳过；原失败完整保留。单处独立名单补齐后，A2 `ca52dcaee79aa73796eddb79ad1716f3a46b1886` 的CI `44006177251` 两系统各697项OK、4项既有跳过，唯一附件 `14294208318` 外摘要 `b194b8c0d7d3af1ce0338bfb01f706a9917fe288418e193b647dc5477141f71c` 已核验。A2原始插件正常拒绝未发布组件准备；Native原包的临时七定义闭环、真实Codex8模型／8推理只读选择放弃和配置摘要一致均通过。

A2原包追加导航测试发现项目→用户级→刷新后丢已知项目，当时继续阻断发行。原作者精准修复、同Reviewer增量PASS后，A3 `6edaa59dc65bfbb9ebf970b5992910d0eba5e6b6` 的CI `44010918923`双系统各697项OK／4项既有跳过，实际原包恢复同场景通过并核对静态摘要；A2原包红、A3源码绿、A3原包绿分别保留，未修改旧包或混用结果。

Native [0.1.4正式发行](https://github.com/Geoege-xll/agent-workflow/releases/tag/native-agent-config-v0.1.4)的tag精确指向A3，非draft／prerelease、latest=false；原ZIP与sidecar两资产摘要、真实重新下载及37项BUILD均匹配，ZIP SHA为`82a50eb69457d7d486491934f4cf6443881d4274a3fece06b613589c350fb8f6`。唯一描述生成器再次实际下载后写published绑定；Native源码及独立README常量自此冻结，旧A2未发布包摘要不作最终绑定。

最终插件来源B为`140f4642dcff6d10c90be4ece9f54562011789f6`。[最终CI](https://github.com/Geoege-xll/agent-workflow/actions/runs/44016392056)两系统各运行697项OK、4项既有跳过，唯一附件`14299815879`外SHA `c1ba7bb1d3b6e5d9008e397c811e67772950ce05abced76f5248dee9065eba36`，17文件／七包及sidecar通过。Native ZIP逐字节等于已正式包。B原始薄启动器仅隔离component_root／home、未覆盖descriptor／invoke的真实安装链ready／verified；本机默认根另行正控，不用隔离结果替代。

工作流[3.0.5正式Release](https://github.com/Geoege-xll/agent-workflow/releases/tag/v3.0.5)八资产摘要均已核验：七资产直接匹配B的CI外包原成员，`PLUGIN-SHA256SUMS`为同一候选三个正式插件ZIP摘要生成的专用单，内容及发布摘要一致；不是外包根校验单改名。tag精确B、latest=true、非draft／prerelease。现有唯一publisher本机预览后普通atomic apply一次，没有Actions发布run或force；实际Codex `6c8378aff9236b980cff398bf8d4b4b669cd06ad`、Claude `0dbc1f9b523801a76034ccbd8734c77f8743bb5b`、AGY `df7fc00b4af3174c73595e842f3f74d395ec233f`。真实远端2336／2334／2331分发文件的完整blob字节与mode匹配B投影，source_revision=B；没有把本地生成或排队状态当远端成功。

本机已通过官方客户端升级，仅xy-workflow目标：Codex、Claude、AGY分别2334／2332／2330载荷文件逐字节与执行位匹配B；Codex App／CLI持久共享cache的3.0.5也独立核对。模型、推理、原生字段、dispatch、用户文档／设置、启停、范围及其他插件同口径摘要前后均为`98882273fa8868e33c9b4eecc9a7d59e43244237d247a59c5a5e50ab033efd8a`。Claude官方列表仍user／enabled=true、当前源码项目projectEnabled=false；静态activation观察不替代官方启停事实。

实际持久Codex cache原始launcher在真实默认组件根open／status／doctor均ready、integrity=verified，Native0.1.4正式字节与来源绑定正确，用户新服务留ready。市场临时根先前正控仅本轮PID正常退役，完整过程保留；真实默认根未传--home或注入组件根。只读context为原生定义0／missing候选7，未创建Agent或保存模型／启停。GUI新会话、named调用和实际模型执行仍未验，Windows暂停。

以下为已完成的3.0.4及更早真实发行、安装与归档事实。

3.0.4源码功能已由唯一Reviewer验收，原F1 FAIL及修复后完整Pack绑定PASS均保留，PM实际validate有效。最终生产来源为`484760aab0fc3010dbce8e7b18bc7defeca62baf`，源码QA后仅作两行长期文案收口。[正式CI](https://github.com/Geoege-xll/agent-workflow/actions/runs/43852641432)Ubuntu／macOS各681项OK，含4项既有跳过；唯一artifact `14221082620`外摘要为`bf9e8df70d4b0e6e7650da94917be357d45acb5322201e6667b60e7b091239d1`，17文件／七包及sidecar核验通过。Native仍是原0.1.3的`368faac571dfa438a25c103ec2b1ab27b1483ee7692eaa982d248c5647618c26`。

[3.0.4 Release](https://github.com/Geoege-xll/agent-workflow/releases/tag/v3.0.4)已发布，八资产服务端摘要与同一CI匹配，标签指向最终来源。Actions发布运行`43856230433`持续显示排队，取消响应却称已结束，未拿该状态冒充发布成功。PM复用仓库现有发布器、同一已核验CI附件和原版本／摘要／原子约束，在本机执行普通atomic push成功；临时Git工作区限本请求目录，未本地重建或force。三个实际远端提交为Codex `e5198f8ca957cb476dd4bf6e1b621e1dd262b620`、Claude `b1aadd7ccfe02322d16f9ec94cd6aa46913daf3d`、AGY `4510e94ecba708f34fab374c31c9bb10fc0ceaa9`，`git ls-remote`及不可变分发记录与CI完整比较均通过。过期本机watch进程已停止；同输入幂等，不扩大为Actions运行成功。

本机官方客户端已更新Codex／Claude／AGY到3.0.4，2325／2332／2330个载荷文件字节和执行位匹配最终CI；AGY额外仅distribution.json与Git控制资料，其他插件不变。模型偏好三平台摘要一致；Claude当前源码项目停用、用户级安装范围保留。配置组件0.1.3未重复prepare、doctor或发行，不把上一轮相关证据写成新执行。mt-shop55页入口已准备、原文除entry外不变、业务依赖保持，纯导航index保全原件后清理，当前三页评审服务ready。

开发手册同流程文档delta和本轮实际交付事实已由原Reviewer验收，最终Pack SHA `25cde05b131450a5e244e8f1dcc94e46c3a1a410379646cbaeaf8bc80e8bfc8c`、交接SHA `0d6bd2b376b220c488c78b83cbc04e83e35d6b15137cf6eb82b99ef4139e4317`，PM实际validate有效；后续普通接受／归档事实投影不重启功能QA。Codex App共享缓存已升级，GUI新会话、指定模型采纳和完整读屏仍按各自实际证据判断。实际业务原型未自动化，Windows暂停。

本轮私有证据归`dist/evidence/stable-product-release/stable-304-013-delivery-evidence.zip`，594文件加索引，SHA `a034ae66b4ac9dd25135347f6729116af1b7f5fcc2f3a44cf4183f0e45c0b7d2`；完整原失败／成功日志、源码diff、机器交接、CI／Release／分发／安装及实际项目旧导航原件均保留。6994项可恢复的正式容器或已展开包按索引保留摘要与恢复来源，不重复存二进制；原未发布first三包与F1代表包保留。归档CRC与逐项摘要已复核。唯一请求临时目录按元数据快照绑定精确回收，`cleanup-304-*.json`保留实际回执；正式mt-shop服务清理后仍ready。无本轮待发布、待安装或待迁移事项，旧归档和用户资料保持。

以下为上一轮3.0.3／0.1.3已完成的真实发行事实，不作为本轮3.0.4的完成证据。

Native Agent Config [0.1.3](https://github.com/Geoege-xll/agent-workflow/releases/tag/native-agent-config-v0.1.3)固定首个成功CI来源6f02b043cdbdb515a734725ff9df56475d86379d，包SHA `368faac571dfa438a25c103ec2b1ab27b1483ee7692eaa982d248c5647618c26`。原作者真实重新下载生成published固定描述，同Reviewer四文件增量PASS经PM实际validate为valid。

最终生产来源f65c290b410299c5f37b42b6b6892118473ccfd8的[最终CI](https://github.com/Geoege-xll/agent-workflow/actions/runs/43824452436)两系统各666项OK、4项既有跳过，candidate成功；Native仍与先行正式包同字节。[工作流3.0.3](https://github.com/Geoege-xll/agent-workflow/releases/tag/v3.0.3)八个资产的服务端摘要逐项匹配同一CI，[三个stable发布](https://github.com/Geoege-xll/agent-workflow/actions/runs/43825922146)核对同一来源与不可变附件后普通atomic push成功。

本机官方命令安装三端3.0.3，2320／2327／2325个载荷文件逐字节和执行位匹配最终CI，AGY额外仅分发记录与Git控制资料。组件0.1.3实际prepare/open(no-browser)成功，三端新启动器doctor均integrity verified、service ready。模型偏好摘要和原启停／范围保持，Claude当前源码项目仍projectEnabled=false，另两AGY插件观察不变。安装不证明GUI新会话、模型实际采纳或所有项目启用。

前两轮CI的独立夹具清单缺项、macOS默认临时根及包外启动超时原日志均保留。三文件窄修复经原Reviewer PASS后双系统通过；生产路径保护、12秒预算和就绪握手未放宽。本机未复现旧CI实际resolver等待，不将已消除的无关DNS依赖当作全部原超时的既定原因。

### 3.0.2／0.1.2已完成历史

本轮配置工作台与评审工作台源码、真实浏览器、三端包外消费及各自唯一QA已通过。首轮[CI](https://github.com/Geoege-xll/agent-workflow/actions/runs/43599159117)两系统各633项、2项旧测试失败／4项既有跳过，原日志与修复历史保留。两个精准修复经原Reviewer扩展32路径PASS后，以 `cae70ccf40e2608e0a4cb8b6212db3f72e7c1dff` 推送，新的[成功CI](https://github.com/Geoege-xll/agent-workflow/actions/runs/43600866794)两系统各633项OK、保留4项既有跳过，候选成功。

CI附件17文件的外摘要、七包和sidecar已核。Native Agent Config [0.1.2](https://github.com/Geoege-xll/agent-workflow/releases/tag/native-agent-config-v0.1.2)已实际正式发布，真实重新下载与CI相同，SHA `db5b3bdf225bce5a788f3a6894e7ca27d59ffc250f6e8fd12887e3d55a2b2ce0`；包内三个已批准网页源同字节。原作者通过既有公开入口再次下载生成published固定描述，ABI仍1／2；原Reviewer对四文件绑定／状态说明完成最小delta PASS，未重做未变功能审查。

最终产品来源为 `5186d48822d2358379223d1d50b2ffc3920ff144`，[最终CI](https://github.com/Geoege-xll/agent-workflow/actions/runs/43603486736)两系统各633项OK（4项既有跳过）及candidate成功。工作流 [3.0.2](https://github.com/Geoege-xll/agent-workflow/releases/tag/v3.0.2)八个正式资产的服务端摘要逐项匹配同一CI候选；[三stable发布](https://github.com/Geoege-xll/agent-workflow/actions/runs/43605162892)核对同一来源与不可变附件后普通atomic push成功。Native正式发行固定首个成功CI的 `cae70ccf40e2608e0a4cb8b6212db3f72e7c1dff`，最终CI重建Native仍为相同字节；未重建本地包冒充发行来源。

本机通过官方客户端升级Codex、Claude及AGY后，实际清单均为3.0.2且启用；2310／2317／2315个载荷文件的字节和执行位与CI相同，AGY额外仅官方分发记录。配置组件0.1.2真实准备成功，浏览器打开，三个已安装启动器的doctor均报告完整性verified、服务ready。前后同口径模型偏好摘要相同，启停覆盖及安装范围保持；Claude当前项目仍为projectEnabled=false，不能宣称所有项目均启用。无剩余已批准的本轮实现／发行任务。

发行后文档提交 `83891ffff3a42284f4d83612898d73368804e06d` 的自动CI首次在Ubuntu暴露旧测试夹具通知竞态：标记文件创建后、JSON写入前被读取；同轮macOS通过，candidate跳过，完整原失败保留。独立Light维护仅将该测试fake的PID通知改为同目录完整写入后原子公布，保留全部退出／回收断言和超时；受控旧负控、新正控及真实精准节点通过，PM审查接受。该test-only维护与文档收口不改变已发行产品载荷、标签和本机安装；后续自动CI及完整证据归本节最终归档，不能把此前失败抹为成功。

以下保留上一3.0.1／0.1.1发行证据，不是本轮完成声明。

上一正式发行与本机升级均已完成。组件先用首个成功 CI 原生包正式发布并真实下载核验；published 描述提交后，最终来源为 `9a602babf924723c5d74d18692be173d8481de34` 的[成功 CI](https://github.com/Geoege-xll/agent-workflow/actions/runs/43549655014)，两系统各 628 项，624 通过、4 项既有跳过。原唯一旧计数失败及同作者／同 Reviewer 修复证据保留。

[三 stable 发布](https://github.com/Geoege-xll/agent-workflow/actions/runs/43550996430)普通 atomic push 成功，完整路径／字节／模式与最终 CI 投影一致。工作流 [3.0.1](https://github.com/Geoege-xll/agent-workflow/releases/tag/v3.0.1) 和组件 [0.1.1](https://github.com/Geoege-xll/agent-workflow/releases/tag/native-agent-config-v0.1.1) 均为真实非 prerelease Release；工作流八资产摘要与候选匹配，组件为冻结 SHA `ad7c60fdbf5a417adaa67620f4c41d8315a36eb75cdec54e70601d8184a2a567`。

本机通过官方客户端移除旧 alpha 安装及其市场登记，Codex／Claude／AGY 均安装启用 3.0.1；2306／2313／2311 个插件文件的字节和执行位与 CI 原包相同。AGY 额外仅自身 Git 资料与分发记录，另外两个插件不变。Native Agent Config 0.1.1 实际准备成功，三端 doctor 完整性 verified、服务 ready，浏览器打开回执成功；原普通沙箱回环不可达及获准只读复核均保全。

作者及原 Reviewer 的结果已保全后逻辑退休，不再承接新独立需求；无原生关闭工具，未宣称历史清空或强制进程销毁。后续工作台第五版视觉重设计是新的请求，先原型确认，不能继承本发行 QA 或第四版视觉批准。

## 验收结果与当前已交付行为

当前正式组合为 xy-workflow 3.0.7 和 Native Agent Config 0.1.6。已发布 GitHub 正式版、更新三条稳定分支和本机三端。前一节记录本轮实际验收，以下为历史。

3.0.6 阶段完成 GitHub 发行、三端稳定分支、本机官方安装、配置保留、受管路径切换和旧版本清理。Codex App 持久缓存逐项核对。

此前3.0.5阶段已完整验收、发布并安装xy-workflow 3.0.5与Native Agent Config 0.1.4，包含当时的范围点击／刷新恢复、显式原生准备、单快照来源CAS和上下文去重复。配置连接与既有布局、原型交付／评审能力保持，具体证据见对应功能主题。先组件后插件、同SHA成功CI、真实下载绑定和历史库存认证分离均保留；不声称新增或验证宿主模型调用能力。

3.0.5阶段的保留摘要与官方列表结论见历史记录，当时真实Agent首次创建需用户在产品中明确预览确认；3.0.6已改为显式open自动补齐缺失定义。以下3.0.3及更早的证据保留为历史，不替代本轮操作结果；历史采样缺失不由本轮补造。

3.0.5阶段的安装、服务可达与浏览器打开分别只是相应层证据。当时Codex CLI／App共享插件缓存已升级，但App图形界面新会话、三端指定模型／推理实际采纳及完整读屏未实测；官方公开目录尚未上架，Windows继续暂停。新会话仍按宿主原生权限与Hook信任处理，不直接改写信任。该阶段未执行三个业务项目的具体原型迁移；本轮mt-shop55页受管外壳刷新见最新交付记录。

## 批准依据与必要证据

本轮用户在文档治理审计后明确要求修复、提交 GitHub 新版本并升级本机。实际操作证据见 3.0.7 最终交付记录。

3.0.6 阶段用户先明确“开始发布与本机升级”，随后追加“本机升级完成后，对本地历史老版本等进行清理”。代码／浏览器既有QA、两轮成功CI、真实Release下载、publisher及远端闭包、官方安装、60项配置保留、七路径CAS、55页原稿／评审保留和四组清理回执统一保全于`dist/evidence/stable-product-release/stable-306-015-delivery-evidence.zip`；大CI容器及重复展开已移除，固定run／artifact摘要、原资产摘要和正式Release恢复入口保留。认证入口、私有launch HTML内容和浏览器profile不进入归档。

下文为3.0.5及更早发行的历史证据。

本轮完整日志、红绿回归、浏览器脚本与结果、六组原QA包／交接、CI、发行、分发及本机回执保全于 `dist/evidence/stable-product-release/stable-305-014-configuration-evidence.zip`：233个证据文件加映射索引，SHA `729a53ca9e1c755b67dd0f6052cfc3d769349ce900e6f68f681be5fffce4b299`，逐项SHA与ZIP CRC均核验。保留A2未发布失败Native小包；大型CI容器、正式包及分发Git对象由索引中的固定CI／Release恢复，不归档认证入口、服务状态和浏览器配置。

同一Reviewer最后只核操作证据，未重开代码QA或新增测试；`qa-final-operations-evidence.json`结论CONSISTENT，SHA `54990abfa6bc832c332edaadaa93398c95408f5f6a991877e69361d88f14e9f9`，已纳入上述归档。默认根context原响应只在进程内解析断言，未保存原始字节；提取结果保存在`installed-default-launcher-receipt.json`，不补造原响应。任务实例已逻辑退役；本轮临时目录按归属及元数据快照精确回收，用户正式服务及旧state不在清理范围。

### 3.0.3历史证据

- 本轮published绑定Pack SHA `3725f762511d0e7f00aaa33ef9a9a7f4e93c84aeb697bdebad6f791207e60100`，同Reviewer交接SHA `655e8a225461673eaca59c51f229bc758d55d55b99bb52a4c47efe4dd52cdf05`，PM实际validate valid。配置功能与原型独立QA完整证据分别保留，不互相替代。
- 最终artifact `14206591282`外摘要 `ea352ab5ea2fef6711d0c3dca72cf89bb6e42778c3e7e0d686103979a8c38e87`与GitHub一致，17成员、七包及sidecar安全且匹配；八个Release资产服务端摘要与最终CI相同。
- 本轮完整原失败／成功命令、Pack、交接、CI、Release、stable及本机回执保全于 `dist/evidence/stable-product-release/stable-303-013-delivery-evidence.zip`。归档共447个证据文件及映射索引，SHA `54345855bb38d74410a802f0db20a05c693555b39bcaab5efc4544bdafa898b9`；所有被引用完整日志均在，认证入口临时回执已清理。两个本轮请求临时目录经只读预览与元数据快照绑定后精确回收；完整日志及浏览器结构快照已归档，正式用户级服务与项目原稿保持。live5前期完整源证据归档 `dist/evidence/plugin-prototype-viewer/live-review-303-evidence.zip` SHA `207b3560fadb131a520d17c856b4deb94a09b0b65ae9af9b61daf4c235010145`保持。大型候选及正式包从固定CI／Release恢复；本地审计资料不上传公开发行。

### 3.0.2及更早历史证据

- 批准依据：用户要求“历史讨论定下的需求全部修改完毕后，再做一次验收；验收无误后发布新版，并升级本机为最新版本”。第六版配置工作台和最终整改工作台分别绑定各自已采用的具体原型，不把发行授权当作新设计批准。
- 验收证据：原唯一Reviewer的32路径published绑定Pack SHA `df57db345fe636c61b8a566a3228b81b7f4413f6f21243d6ab98591119d4fce1`，有效交接SHA `d0cda1bbdb08b150c3a1c1e7a73e4966e622d1c2617465894ceb74b2870c3e7b`，PM实际validate退出0；最终操作与事实投影由同Reviewer只读复核，不重跑未变功能。
- 最终artifact `14117960812`外ZIP SHA `8b495c1027039d8c566b1aa6e73675637df1856f5bba269ace2f1205664e571b`与服务端一致；17成员安全，七包和sidecar全部匹配。三个primary ZIP摘要为Codex `c748ecf380ca68af99706777cc898ce12c1576172fcfd7630f4f6625319a5df5`、Claude `9e44809a2799e18c60503a3f4e3860f57944a8b0df46e5ecded9d45d1d38b7f8`、AGY `615eaad705951c112766073d0eb4e34e30261faddb892d06b03ec2e922c9d8f8`。
- 完整原失败／成功日志、分阶段Pack与交接、最终CI／Release／分发及本机回执保全于 `dist/evidence/stable-product-release/stable-302-012-delivery-evidence.zip`；配置UI及原型前像归档保持原位。大型候选与实际发行包从固定CI及Release恢复，不重复纳入证据归档。下列3.0.1记录明确为历史。

- 历史3.0.1批准：用户“升级完成后叠加新版本，去掉 alpha，xy-workflow 3.0.1、Native Agent Config 0.1.1；发布 GitHub 并升级本机”。
- 历史3.0.1验收：同一 Reviewer 的 published 源码 Pack SHA `75cf292db7c1de1958f39ea289ee09957933c86da7b0609094d8bbb7c7bac1af`，有效交接 SHA `7b9cc768e201c88c0f50a90bd9f9eff1a3d24e06e1d790050285683cc5901f43`，PM validate 退出 0；旧Reviewer另只读复核当时CI、远端与本机操作，记录在旧归档内 `qa-final-ops-evidence.json`，与本次同名证据分属独立请求。
- 最终 artifact `14096580701` 的外 ZIP SHA `27e3f6fee07cc9c5089d2b6624aed0b9dcb00042f1d19eb8352bc100728b68f3` 与服务端一致；17 成员安全，七包及 sidecar 全部匹配，native 与先行正式资产为同一字节。
- 完整原失败／成功日志、分阶段 Pack 与交接、Release／Git 树及安装回执保全于 `dist/evidence/stable-product-release/stable-301-011-delivery-evidence.zip`，128 个证据文件，SHA `2c2ab8227cc9ea0b99c091c9bdfddb582ee568876160f8c2fe1b6b5dc9542636`。不重复归档大型候选，原 CI 及真实 Release 可恢复相应资产。

受保护旧未跟踪迁移稿不读、不改、不暂存。文档事实投影为发行后的独立提交，不改变已发布3.0.5／0.1.4的源码与产物身份，不移动既有标签或重发同版不同载荷。
