# 工作流与配置工具正式发行

- 主题 ID：`stable-product-release`
- 阶段：`active`
- 模块：版本、独立组件发行、三平台 Git 分发与本机安装
- 任务等级：`Full`
- 已验收版本：`3.0.2`

## 目标与范围

本轮用户要求先修复配置页连接与指定布局问题，并完成后续已批准的双网页／唯一原稿评审升级，再发布xy-workflow `3.0.3`／Native Agent Config `0.1.3`并升级本机。工作流包含已独立验收的feedback4精简及新live反馈5。当前正式基线仍为3.0.2／0.1.2；功能分别归模型偏好和原型评审主题，旧证据保持。

现有构建、组件描述和远程发布器已支持正式渠道，复用唯一版本与发行来源。保留两独立产品、唯一构建来源、实际下载摘要、正式宿主入口和配置偏好；不恢复 2.x、Windows 或其它安装渠道。

## 需求与验收

- REQ-601：本轮目标源版本为工作流3.0.3、配置工具0.1.3；构建、描述、provenance、归档和GitHub Release使用真实正式版本，不带prerelease标记。尚未发布／安装时不先写成完成；保留3.0.2／0.1.2旧基线。
- REQ-602：正式与预发行版本／渠道必须匹配，拒绝混合、降级和同版不同载荷；复用唯一版本判定，不增加手工第二套发布器。
- REQ-603：三平台具备正式 Git 分发引用与对应市场身份；历史 alpha 来源保留可审计，公开安装说明以当前正式入口为准。命令名 xy-workflow 与现有调用偏好身份保持。
- REQ-604：组件0.1.3先正式发布，真实下载校验后生成published固定描述；再从同一最终源码的成功CI候选发布插件及三渠道，拒绝未发布地址或本地重建包冒充CI产物。
- REQ-605：覆盖正式／alpha 版本匹配、候选消费、发行摘要、上游历史库存保留及固定身份文件；必要 CI 入口真实收集，不删除旧负控造绿。
- REQ-606：任务／资源收尾后通过官方客户端升级本机 Codex、Claude、AGY；核对真实版本、载荷与偏好保留。安装、重新加载和实际模型采纳分别说明。

## 方案与原型关联

版本与渠道判定、构建者、候选编排、发行描述、发布消费者和宿主安装各有单一职责。新增正式渠道由现有发布器投影，不建立新脚本平行维护；命名仍由唯一 command_identity 声明。组件内容只随源版本与其必要身份变化，不引入新配置功能。

本轮按已批准第六版配置工作台和最终评审工作台实现后发版，UI依据、功能验收分别见[模型偏好主题](native-model-preferences.md)和[评审主题](workflow-document-lifecycle.md)。来源技能及公共按需加载见 [角色技能主题](role-skill-routing.md)，文档质量见 [计划规范主题](plan-document-quality.md)。

## 当前进展与恢复入口

当前安全顺序为各功能源码独立验收 → 双系统CI候选 → 组件0.1.3发布及真实下载固定绑定 → 最终同SHA CI → 插件3.0.3与三stable发布 → 官方客户端更新及本机载荷／配置保留核对。配置页原Reviewer的规范delta PASS已实际校验；检查点`b309dc2392ac0111b1122aaf3eca08a473f279e5`已普通推送。其[首轮CI](https://github.com/Geoege-xll/agent-workflow/actions/runs/43805980053)两平台各649项出现验证器独立清单／fixture遗漏引起的5失败和4既有skip，未生成候选；原失败已保全，清单已补新模块、精准4方法退出0。

后续双网页／live5升级已完成作者验证、三端消费及原唯一QA三项返工delta PASS（40路径／57规范），详见[评审主题](workflow-document-lifecycle.md)。下一步提交当前已验收候选并重新跑双系统CI；当前仍未正式发布3.0.3／0.1.3、未更新三stable或本机。未变的feedback4与配置源码证据继续复用，不能用作者精准验证代替全CI。

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

当前已完整验收、发布并安装的正式组合为xy-workflow 3.0.2与Native Agent Config 0.1.2。已交付第六版深石墨配置工作台、HTML整改评审工作台及其职责整理，具体能力与证据分别见两功能主题。正式／alpha严格版本与渠道判定、候选来源及唯一附件门禁、先组件后插件、同SHA成功CI、真实下载绑定、历史库存认证分离等均保留；没有新增宿主模型能力。

本轮三端dispatch偏好文件及原生模型、推理和Agent字段，均由保全的同一采样脚本生成前后摘要，完全一致；未执行任何真实模型配置保存，未改写用户值。清单的目标启用／范围和其他插件采样摘要保持；Codex清单检查范围仅xy-workflow市场，不能扩大为所有市场。Claude列表仍显示用户级enabled=true、projectEnabled=false；不据此宣布当前项目或新会话已经加载。上一3.0.1升级时Claude采样口径缺失仍属历史未证，本轮新采样不补造旧结论。

安装、服务可达与浏览器打开分别只是相应层证据。Codex CLI／App共享插件缓存已升级，但App图形界面新会话、三端指定模型／推理实际采纳及完整读屏未在本轮实测；官方公开目录尚未上架，Windows继续暂停。新会话仍按宿主原生权限与Hook信任处理，不直接改写信任。三个业务项目的具体原型迁移不是插件升级动作，本轮未执行。

## 批准依据与必要证据

- 批准依据：用户要求“历史讨论定下的需求全部修改完毕后，再做一次验收；验收无误后发布新版，并升级本机为最新版本”。第六版配置工作台和最终整改工作台分别绑定各自已采用的具体原型，不把发行授权当作新设计批准。
- 验收证据：原唯一Reviewer的32路径published绑定Pack SHA `df57db345fe636c61b8a566a3228b81b7f4413f6f21243d6ab98591119d4fce1`，有效交接SHA `d0cda1bbdb08b150c3a1c1e7a73e4966e622d1c2617465894ceb74b2870c3e7b`，PM实际validate退出0；最终操作与事实投影由同Reviewer只读复核，不重跑未变功能。
- 最终artifact `14117960812`外ZIP SHA `8b495c1027039d8c566b1aa6e73675637df1856f5bba269ace2f1205664e571b`与服务端一致；17成员安全，七包和sidecar全部匹配。三个primary ZIP摘要为Codex `c748ecf380ca68af99706777cc898ce12c1576172fcfd7630f4f6625319a5df5`、Claude `9e44809a2799e18c60503a3f4e3860f57944a8b0df46e5ecded9d45d1d38b7f8`、AGY `615eaad705951c112766073d0eb4e34e30261faddb892d06b03ec2e922c9d8f8`。
- 完整原失败／成功日志、分阶段Pack与交接、最终CI／Release／分发及本机回执保全于 `dist/evidence/stable-product-release/stable-302-012-delivery-evidence.zip`；配置UI及原型前像归档保持原位。大型候选与实际发行包从固定CI及Release恢复，不重复纳入证据归档。下列3.0.1记录明确为历史。

- 历史3.0.1批准：用户“升级完成后叠加新版本，去掉 alpha，xy-workflow 3.0.1、Native Agent Config 0.1.1；发布 GitHub 并升级本机”。
- 历史3.0.1验收：同一 Reviewer 的 published 源码 Pack SHA `75cf292db7c1de1958f39ea289ee09957933c86da7b0609094d8bbb7c7bac1af`，有效交接 SHA `7b9cc768e201c88c0f50a90bd9f9eff1a3d24e06e1d790050285683cc5901f43`，PM validate 退出 0；旧Reviewer另只读复核当时CI、远端与本机操作，记录在旧归档内 `qa-final-ops-evidence.json`，与本次同名证据分属独立请求。
- 最终 artifact `14096580701` 的外 ZIP SHA `27e3f6fee07cc9c5089d2b6624aed0b9dcb00042f1d19eb8352bc100728b68f3` 与服务端一致；17 成员安全，七包及 sidecar 全部匹配，native 与先行正式资产为同一字节。
- 完整原失败／成功日志、分阶段 Pack 与交接、Release／Git 树及安装回执保全于 `dist/evidence/stable-product-release/stable-301-011-delivery-evidence.zip`，128 个证据文件，SHA `2c2ab8227cc9ea0b99c091c9bdfddb582ee568876160f8c2fe1b6b5dc9542636`。不重复归档大型候选，原 CI 及真实 Release 可恢复相应资产。

受保护旧未跟踪迁移稿不读、不改、不暂存。文档事实投影为发行后的独立提交，不改变已发布3.0.2的源码／产物身份，也不移动既有3.0.1标签或重发同版不同载荷。
