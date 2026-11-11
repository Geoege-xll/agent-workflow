# 3.0 官方插件与原生 Agent 配置

- 主题 ID：`PLAN-PLUGIN-V3`
- 阶段：`active`，源码候选完成，官方客户端完整运行待验收。
- 基线：`de847fd6e10de5b31d04591b4fe596808ae8fa1d`，已保全并推送 main。
- 实施分支：`codex/plugin-v3-20261111`；本轮未替换用户本机安装或业务项目。
- 整体验收版本：`none`；不发布稳定 tag，不把源码 QA 当成三宿主运行 PASS。

## 已批准范围与不变量

完成官方插件化，并按用户纠正开发独立原生 Agent 配置工具。配置对象使用平台原生身份，覆盖用户级、项目级和插件角色，不限 AWF 固定角色。两个产品独立版本、独立打包；工作流不以网页、服务或 MCP 为前置。Windows 暂停。沿已确认 UI 规范直接开发，不另做原型。

Full 的需求确认和需要原型时的视觉确认保留；Light 已授权、一致性任务及明确直接开发继续按原适用规则，不新增业务确认。主会话 PM 持续接单，按真实重叠、依赖和容量协调并行、复用、追加或等待。生产实现原生委派，新任务 fresh/handoff_only，最小完整交接不复制 PM/兄弟会话；同任务返工和原 Reviewer 差量复查可复用。Full 保留请求级唯一独立只读 QA 与原收口顺序。

计划维护主题 Markdown；计划 HTML 公开生成入口暂停且保留代码，历史 HTML 与原型 HTML 保留。项目资料、现有修复、旧分支与用户安装不自动删除。

## 架构与当前归属

| 范围 | 实现与职责 | 当前结果 |
| --- | --- | --- |
| P3 | plugins、build_plugin、本地市场、最小项目 context | 三宿主载荷及独立重建通过；无中央/服务前置 |
| P5 | plugin_resources、runtime_pins、精确权威读取 | 拒绝缺项回退、旧 binding/桥混用，独立审查通过 |
| P6 | 持续接单、同任务修订/ACK、HTML 暂停 | 定向 106 项通过 |
| P7 | dispatch_admission、task_settlement、任务图/交付 | 作者 159 项通过；原 Reviewer 定向反伪及真实 Light QA 复核通过 |
| P8 | native_config 纯核心/发现/编解码/条件保存 | 42 项通过；数据保护及启用状态问题已独立关闭 |
| P10 | HTTP/CLI/可选 MCP、脚本、独立包 | 退出与收据问题已独立关闭；不注册宿主 MCP |
| P4 | native_config/web、动态原生角色网页 | 三平台临时原生闭环、错误边界及最终独立包真实保存通过 |
| PM | 本计划与当前说明 | 维护范围/证据/剩余阻断；不改生产实现 |
| 唯一 QA | 冻结来源、只读审查、原作者返工复查 | 同一 Reviewer 完成各差量，无新增第二 Reviewer |

工作流权威来自 product、roles、共用 Skill；插件根来自当前物理安装和精确清单。项目配置与包内权威分开读取，空项目显式 apply 只创建缺失的 `.awf/project.yaml`，不中央登记、不创建空文档、不复制第二套规范或伪造批准。claim 只是预留，未知原生创建结果不自动释放/重派；单 PM 显式记录不冒充全局跨 PM 调度。结算绑定原实例、当前完整接受包、范围、批准及独立不可变证据。

独立 native_config 不导入 lib、manager 或 AWF 角色枚举。网页、HTTP、脚本及按需开启的 MCP 共用发现、校验、预览、保存和诊断。稳定 opaque ID 区分同名来源；插件缓存只读，未知/遮蔽/不完整发现不生成可派发结论。整定义优先级、inherit/null、模型字段、命名派发与单次覆盖按平台实际能力区分；Codex ultra 不沿用旧枚举禁令，AGY 未核调用 schema 保持诊断。详细入口见 [插件说明](../plugin-v3.md)与[原生配置](../agent-configuration.md)。

## 验证与已关闭问题

| 当前验证 | 结果 | 证据 |
| --- | --- | --- |
| plugin 产品组 | 89 项，88 通过、1 个原生隔离入口限制 skip | `/private/tmp/awf-v3-final-plugin-tests.log` |
| native-config 产品组 | 68/68 通过 | `/private/tmp/awf-v3-final-native-tests-authorized.log` |
| 核心冻结审查 | 67 路径首尾 SHA 一致；离线/项目/Light QA/准入结算通过 | `/private/tmp/awf-core-qa-source-review.json` |
| 退役与纯核心差量 | 26 项匹配、7 预期缺失；六包独立重建一致 | `/private/tmp/awf-core-qa-final-retirement-review.json` |
| 最终 native 差量 | 29 路径首尾 SHA 一致；临时真实产品流程通过 | `/private/tmp/awf-native-final-review-verdict.json` |

初次受限环境中回环 bind EPERM 的 native 运行保留在 `/private/tmp/awf-v3-final-native-tests.log`；确认限制后获准运行同组得到 68/68，不修改或跳过测试。旧 ci/full 仍含 2.x 遗留消费者，不宣称本轮全仓 PASS。

独立审查发现并由原作者修复、原 Reviewer 关闭：

- 权威缺项回退项目同名诱饵：插件内置缺项明确拒绝。
- 发布/恢复最后窗口覆盖外部原子保存：实际对象隔离与排他 link，真实 EEXIST 负控验证。
- 提前持有原 fd 的后写字节被清理：成功及回滚保留真实隔离 inode 与固定预览前像，返回后继续写及双 fd 负控通过，不靠最后一次 stat 保证。
- 未知高层插件启用值继承 lower true：降为 unknown/incomplete，禁止直接派发。
- 退出截断 daemon 请求并遗留查询组：停止接收后等待活动保存/查询结算、回收自有组，再清理自身连接和锁；慢正文负控通过。
- HTTP 409 收据在网页丢失：完整逐项结果/保留资料同路径呈现，普通错误不伪造收据；命名空间布尔值只透传真实值。

保存正常返回恢复资料不等于失败。固定 preview SHA 与可被旧 fd 继续写入的隔离对象观察 SHA 明确区分；本轮没有自动清理真实原对象的合同。状态区分已保存、等待重新加载、实际运行已验证，最后一项没有官方执行证据就保持 false。

真实浏览器验证包括三平台原生文件十阶段闭环及六场景 HTTP 错误边界，后者是固定业务回执夹具，不冒称写入原生文件。Reviewer 另用最终独立包实际执行临时 home→生产 core/HTTP→浏览器保存：只改 model，CRLF/正文/注释保持，原 inode 和固定前像可定位，saved=true/partial=false/recovery 两项，apply 一次，375px 无横向溢出，退出清理自身连接。证据 `/private/tmp/awf-native-final-review-m3ehxhwn/review-result.json`。

## 交付与清理边界

工作流版本源 `product/PLUGIN_VERSION` 为 `3.0.0-alpha.1`；配置工具 `native_config/VERSION` 为 `0.1.0-alpha.1`。已删除早期 plugin_runtime 五源码、两个专属测试、可选集成开关和三个旧 skip，新增两个明确产品测试组。旧中央入口、manager/TUI 与 2.x 发行面仍用于现有安装维护，其完整退役等待相应原生验收；它们不进入新插件或独立配置包。历史手册已标为 2.x，项目资料和计划保留。

完整暂存检查发现两处 EOF 多余空行，最终只各删除一个换行字节，原字节与严格变换证明保留，未重复行为大套。最新双产品包在 `/private/tmp/awf-v3-final-eof-e_jce8lk/`，不覆盖前一轮包；总清单 `final-build-manifest.json` 保存构建器 SHA、源命令及七个精确摘要：

| 产物 | SHA-256 |
| --- | --- |
| `agent-workflow-antigravity-3.0.0-alpha.1-local-source.zip` | `0386e5cc159956392404451ae3f1eac487ae63310d06466f4234dcc95e91a02c` |
| `agent-workflow-antigravity-3.0.0-alpha.1.zip` | `7401e701bf02048856b47e0d6c8000d8eb2317203e45b53024ab566a41a21d68` |
| `agent-workflow-claude-3.0.0-alpha.1-local-source.zip` | `de22b4aa3e6cdb25bedfa5b4ba06db26c101270f28f77c868e27f064d8528cb7` |
| `agent-workflow-claude-3.0.0-alpha.1.zip` | `1aa44f9e89eb307625221a2ba55c5855140e6fd9a84f6066f891c231e5099e59` |
| `agent-workflow-codex-3.0.0-alpha.1-local-source.zip` | `6ee164dccfbdc4d845e6a89bbb9c61c3b3d52567e22dc66fadf004275e685d3b` |
| `agent-workflow-codex-3.0.0-alpha.1.zip` | `1ebb61640070fe24f8076cc28484852107ff2dfb75535dda98a5d93065115fc3` |
| `native-agent-config-0.1.0-alpha.1.zip` | `08fe3d51f6cbc6e74080ab565695998298ce9037983840b81e593f6a251a7b0d` |

## 剩余官方运行验收

- Codex CLI 已实际发现九项插件 Skill，但未发现候选 Hook；默认新会话 PM 入口与原生派发尚未通过，不能通过写全局指令或 trust 掩盖。
- Claude Code 实际校验/发现通过；继承模型的短 smoke 未取得有效回答，新会话默认 PM 与实际派发仍待能正常响应的原生环境验证。
- AGY 仅只读确认官方插件管理界面，候选未加载，未发现可用官方 CLI。
- 运行中任务跨官方插件更新的资源保留需实际验收，不用离线包代替。

这些限制阻止稳定发布和本机/业务项目替换，不阻止保全已通过源码 QA 的候选。Windows 不执行。没有发布正式 tag、市场远程安装地址或以客户端文件发现冒充实际模型运行结论。
