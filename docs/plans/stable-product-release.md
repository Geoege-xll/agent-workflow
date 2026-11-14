# 工作流与配置工具正式发行

- 主题 ID：`stable-product-release`
- 阶段：`active`
- 模块：版本、独立组件发行、三平台 Git 分发与本机安装
- 任务等级：`Full`
- 已验收版本：`3.0.1`

## 目标与范围

本轮用户要求将历史讨论已确认的Agent配置工作台与原型评审需求全部落地，统一验收无误后发布xy-workflow `3.0.2`／Native Agent Config `0.1.2`，并升级本机。上一正式基线3.0.1／0.1.1与完整证据保留；本轮未发布前不更新已验收版本。功能分别由模型偏好、原型评审主题及其唯一QA验收，本主题负责发行和安装合同。

现有构建、组件描述和远程发布器已支持正式渠道，复用唯一版本与发行来源。保留两独立产品、唯一构建来源、实际下载摘要、正式宿主入口和配置偏好；不恢复 2.x、Windows 或其它安装渠道。

## 需求与验收

- REQ-601：源版本为工作流 3.0.2、配置工具 0.1.2；构建、描述、provenance、归档和 GitHub Release 使用真实正式版本，不带 prerelease 标记。
- REQ-602：正式与预发行版本／渠道必须匹配，拒绝混合、降级和同版不同载荷；复用唯一版本判定，不增加手工第二套发布器。
- REQ-603：三平台具备正式 Git 分发引用与对应市场身份；历史 alpha 来源保留可审计，公开安装说明以当前正式入口为准。命令名 xy-workflow 与现有调用偏好身份保持。
- REQ-604：组件先正式发布，下载校验后生成 published 的 0.1.2 固定描述；再从同一最终源码的成功 CI 候选发布插件及三渠道，拒绝未发布地址或本地重建包冒充 CI 产物。
- REQ-605：覆盖正式／alpha 版本匹配、候选消费、发行摘要、上游历史库存保留及固定身份文件；必要 CI 入口真实收集，不删除旧负控造绿。
- REQ-606：任务／资源收尾后通过官方客户端升级本机 Codex、Claude、AGY；核对真实版本、载荷与偏好保留。安装、重新加载和实际模型采纳分别说明。

## 方案与原型关联

版本与渠道判定、构建者、候选编排、发行描述、发布消费者和宿主安装各有单一职责。新增正式渠道由现有发布器投影，不建立新脚本平行维护；命名仍由唯一 command_identity 声明。组件内容只随源版本与其必要身份变化，不引入新配置功能。

本轮按已批准第六版配置工作台和最终评审工作台实现后发版，UI依据、功能验收分别见[模型偏好主题](native-model-preferences.md)和[评审主题](workflow-document-lifecycle.md)。来源技能及公共按需加载见 [角色技能主题](role-skill-routing.md)，文档质量见 [计划规范主题](plan-document-quality.md)。

## 当前进展与恢复入口

本轮配置工作台与评审工作台源码、真实浏览器、三端包外消费及各自唯一QA已通过，原失败与有界修复保留。当前进入新版本CI、组件先发／真实下载绑定、工作流及三stable发布、本机升级；尚未发生的操作不计完成。以下保留上一3.0.1／0.1.1发行证据，不是本轮完成声明。

上一正式发行与本机升级均已完成。组件先用首个成功 CI 原生包正式发布并真实下载核验；published 描述提交后，最终来源为 `9a602babf924723c5d74d18692be173d8481de34` 的[成功 CI](https://github.com/Geoege-xll/agent-workflow/actions/runs/43549655014)，两系统各 628 项，624 通过、4 项既有跳过。原唯一旧计数失败及同作者／同 Reviewer 修复证据保留。

[三 stable 发布](https://github.com/Geoege-xll/agent-workflow/actions/runs/43550996430)普通 atomic push 成功，完整路径／字节／模式与最终 CI 投影一致。工作流 [3.0.1](https://github.com/Geoege-xll/agent-workflow/releases/tag/v3.0.1) 和组件 [0.1.1](https://github.com/Geoege-xll/agent-workflow/releases/tag/native-agent-config-v0.1.1) 均为真实非 prerelease Release；工作流八资产摘要与候选匹配，组件为冻结 SHA `ad7c60fdbf5a417adaa67620f4c41d8315a36eb75cdec54e70601d8184a2a567`。

本机通过官方客户端移除旧 alpha 安装及其市场登记，Codex／Claude／AGY 均安装启用 3.0.1；2306／2313／2311 个插件文件的字节和执行位与 CI 原包相同。AGY 额外仅自身 Git 资料与分发记录，另外两个插件不变。Native Agent Config 0.1.1 实际准备成功，三端 doctor 完整性 verified、服务 ready，浏览器打开回执成功；原普通沙箱回环不可达及获准只读复核均保全。

作者及原 Reviewer 的结果已保全后逻辑退休，不再承接新独立需求；无原生关闭工具，未宣称历史清空或强制进程销毁。后续工作台第五版视觉重设计是新的请求，先原型确认，不能继承本发行 QA 或第四版视觉批准。

## 验收结果与当前已交付行为

当前正式产品为 xy-workflow 3.0.1 与 Native Agent Config 0.1.1，已发布并核对本机安装。正式／alpha 严格版本与渠道判定、候选来源及唯一附件门禁、先组件后插件、同 SHA 成功 CI、真实下载绑定、历史库存认证分离等均保留；没有新增模型能力或修改 UI。

三端 dispatch 偏好文件升级前后均不存在，Codex 原生模型字段投影摘要一致；本轮未执行任何模型配置保存。Claude 原生模型字段旧采样的序列化方式未保全，无法完成同口径摘要对比，因此其字段保持明确未证实，未猜测或恢复用户值。Claude 列表显示用户级 enabled=true、projectEnabled=false；不据此宣布当前项目或新会话已经加载。

安装、服务可达与浏览器打开分别只是相应层证据。三端指定模型／推理实际采纳、Codex App GUI、官方公开目录尚未验收；Windows 继续暂停。新会话仍按宿主原生权限与 Hook 信任处理，不直接改写信任。

## 批准依据与必要证据

- 批准依据：用户“升级完成后叠加新版本，去掉 alpha，xy-workflow 3.0.1、Native Agent Config 0.1.1；发布 GitHub 并升级本机”。
- 验收证据：同一 Reviewer 的 published 源码 Pack SHA `75cf292db7c1de1958f39ea289ee09957933c86da7b0609094d8bbb7c7bac1af`，有效交接 SHA `7b9cc768e201c88c0f50a90bd9f9eff1a3d24e06e1d790050285683cc5901f43`，PM validate 退出 0；原 Reviewer 另只读复核最终 CI、远端与本机操作，结论及未证边界记录在 `qa-final-ops-evidence.json`。
- 最终 artifact `14096580701` 的外 ZIP SHA `27e3f6fee07cc9c5089d2b6624aed0b9dcb00042f1d19eb8352bc100728b68f3` 与服务端一致；17 成员安全，七包及 sidecar 全部匹配，native 与先行正式资产为同一字节。
- 完整原失败／成功日志、分阶段 Pack 与交接、Release／Git 树及安装回执保全于 `dist/evidence/stable-product-release/stable-301-011-delivery-evidence.zip`，128 个证据文件，SHA `2c2ab8227cc9ea0b99c091c9bdfddb582ee568876160f8c2fe1b6b5dc9542636`。不重复归档大型候选，原 CI 及真实 Release 可恢复相应资产。

受保护旧未跟踪迁移稿不读、不改、不暂存。文档事实投影为发行后的独立提交，不改变已发布 3.0.1 的源码／产物身份。
