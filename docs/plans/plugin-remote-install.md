# 3.0 alpha 远程安装

- 主题：`PLAN-PLUGIN-REMOTE-INSTALL`。
- 当前候选：工作流 `3.0.0-alpha.5`；独立配置 `0.1.0-alpha.3` 保持不变。
- 阶段：远程来源发布与文档实现进行中；真实公开分支、CI 和安装发现按交付收据追加，不预填模型运行通过。

## 目标与范围

用户已同意优化 3.0 插件远程安装。普通用户通过官方客户端直接安装，无需 clone 或构建；开发源码构建保留。采用固定仓库的三个 alpha Git 分发分支，Codex/Claude 市场名统一 `agent-workflow-alpha`，插件名保持 `agent-workflow`；AGY 直接安装对应 GitHub tree URL。[完整安装说明](../../plugins/INSTALL.md)是命令入口。

工作流 helper 仍要求已有 Python 3.11+ 与 Bash，客户端登录、权限及 Codex Hook 审阅信任保持。PM 持续接单、原生子代理 fresh/handoff_only、适用的需求/视觉两步确认、原型、唯一独立 QA 和交付规则均保持。Windows 暂停，不恢复旧管理器、中央同步、npm 或计划 HTML。

## 方案与验收

| 项目 | 合同与必要证据 |
| --- | --- |
| 单一构建 | 沿原构建器和 release.yml 生成七包，发布不另建或重编载荷 |
| 固定来源 | publish-plugins.yml 仅允许 main 手动触发；固定 github.sha，只接受成功 release.yml push/main 同 SHA 的唯一候选 artifact |
| 安全发布 | 校验候选摘要、来源、版本与干净输入；仅写固定三个 alpha 分支，未知历史拒绝，同版不同载荷拒绝，相同输入重发幂等；普通 atomic push，不 force 覆盖 |
| 权限 | 验证/准备作业只读，独立发布 job 才取得写权限；不把仓库写权限放进插件载荷 |
| 宿主安装 | Codex Git URL + --ref；Claude Git URL + #分支；AGY GitHub tree/分支；核实际来源、installed/enabled/版本，不把发现算模型执行 |
| 更新边界 | 市场刷新与已安装插件更新分别按宿主处理；不编不存在的统一 update 命令；活动任务先收尾再更新 |
| 旧来源 | agent-workflow-local 不自动迁移为 alpha；通过官方管理确认范围并停用/卸载旧候选，避免同名并启 |
| 模型配置 | agent-config 首次组件准备仍需确认；不默认安装 MCP 或启动服务；插件缓存只读、平台能力差异保持 |
| 文档交付 | 首页默认远程安装，构建移至开发指南；源码与包内重定位链接均须可用；唯一 Reviewer 复核当前增量 |

## 当前进展与恢复入口

本机官方 help 已分别核对：Codex marketplace upgrade 声明刷新 Git 快照；Claude marketplace update 与 plugin update 为不同命令；AGY 1.5.6 未提供 plugin update 子命令。文档据此保留真实边界，不承诺一条命令完成所有客户端更新。

三个分支由 CI 通过与同一独立 QA 后的实际发布建立，最终仓库 SHA、CI/artifact 与分支回执由 PM 记录。自有 Git 市场不是官方公开目录，许可证和公开目录审核不因此视为通过；stable 若将来提供需另行定义，不在本轮承诺内。

## 已验收基线与未验证范围

上一 alpha.4 已完成三端本地安装：Codex CLI 新插件启动通过；Claude 默认模型 90 秒未响应，PM 接管未验；AGY 模型运行待登录；Codex App GUI 未验。本轮 alpha.5 远程安装、CI 与发布单独记录，不重用旧模型结论补造新版本全通过。

当前没有活动任务跨官方插件缓存更新的自动资源保留协议，更新前先收尾或交接。独立配置预发行仍沿现有真实资产；远程市场安装与 helper 健康检查不自动调用模型、不写业务项目，也不产生业务批准。
