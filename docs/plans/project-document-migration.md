# OmniMind 与 GhkEducational：工作流和文档结构迁移

- 任务等级：Full
- 当前状态：已完成。OmniMind 与 GhkEducational 均已迁移，三宿主安装检查及独立发布复核通过。
- 确认依据：用户在本会话明确要求迁移两个实际项目，使用新工作流继续开发并反馈。
- 原型选择：不适用。本次只迁移已有原型路径及依赖，不改变页面视觉、业务交互或批准范围。

## 范围与方案

- 按用户补充要求，先备份，再整体替换旧工作流源包、同步整理后的文档，最后重建三个宿主入口；保留项目名称、记忆隔离标识、并行参数和项目专属配置。
- 规范叶压平并保留规则 ID 与当前内容；已有 HTML 页面移到 prototype 根并修复相对链接。
- 旧 ADR 的有效理由合并到相关 feature；现行事实优先于过时方案，未完成设计明确放入 plans，不能据旧稿宣称已实现。
- PROJECT 仅保留项目边界与目录，标准索引同步新路径。删除的是已迁移的旧副本和空目录，不删除业务实现或开发成果。
- 不修改业务代码、子仓库、Claude worktree、宿主权限或密钥设置；不提交或推送。

## 工作与验证

1. 创建 scoped 文件快照和哈希基线，核对未提交内容；暂存迁移，不直接覆盖实际项目。
2. 并行分类两个项目的 ADR/feature/设计资料并提出暂存归并草案；PM 审查后统一发布，保留必要历史背景。
3. 校验规范规则集合、Markdown 链接、原型依赖与结构，独立审查迁移差异。
4. 发布前检测并发修改、创建项目外备份；迁移并运行三宿主安装及 --check，核对配置和业务改动未被覆盖。

## 已交付结果

- 两个项目均整体换入已确认新版源包，重建 Codex、Claude Code、Antigravity 入口并通过最终 `setup_all.sh --check`。没有修改工作流源代码或新增确认环节。
- 实际发布的 20 个 HTML（OmniMind 14、GhkEducational 6）仅迁移路径和依赖；结构、正文、脚本、共享样式及链接保真检查通过。规范规则 ID/等级、文档索引与详情契约通过验证。
- OmniMind：17 份 ADR 归并到既有功能详情；原工作流及 docs 在独立备份的 `OmniMind/replaced-live/` 中保留。
- GhkEducational：按用户再次确认的当前 main `e81c539babf1` 迁移，未恢复旧工作区。原 12 个功能文档全部保留，15 份 ADR 归并形成 4 份共享详情，共 16 个活动入口；10 份旧参考资料归入对应规范/功能/计划，保留 4 个明确未完成的计划。
- GhkEducational 新交互规则 015/016 整段原文保留；V13/V14 既有文档口径差异已标注，没有推断真实数据库状态或恢复旧 MEMBER、收费、移动规范及原型。
- GhkEducational 使用既有发现配置排除 `.claude` 与 `educational-server-web/.claude`，防止宿主 worktree 被识别成业务模块；未修改其中内容。旧受管 Antigravity Agent 与空目录造成的安装阻碍已通过备份、精确移出和单宿主重装解决，未放宽安装器校验。
- 两项目发布内容与审查稿一致，受控范围外 Git 状态差异均为零；宿主本地设置、Codex 配置及入口管理块外内容保留。独立 QA 完成最终发布复核。

## 证据、备份与后续边界

- OmniMind 验证日志与暂存：`/private/tmp/workflow-project-migration.X4hYcG/`；独立备份：`/Users/liqunmacmini/Desktop/workflow-migration-backups/20260904-X4hYcG/`。
- GhkEducational 当前 main 的验证日志与暂存：`/private/tmp/ghk-main-migration.CVynxe/`；独立备份：`/Users/liqunmacmini/Desktop/workflow-migration-backups/20260904-GHK-main-CVynxe/`。原包、docs 和 4 个旧受管 Agent 均可从 `GhkEducational/replaced-live/` 恢复；备份根权限 700。
- GhkEducational 最终证据：`GhkEducational-antigravity-install.log`、`GhkEducational-check.log`、`GhkEducational-published-verification.log`；最终命令退出码均为 0。中途失败日志仅保留作诊断，不能当作当前未完成状态。
- 不重跑已经使用的一次性发布/续装脚本；后续变更应读取新基线。下一步由用户在两个项目实际开发中测试并反馈。
- 收口评估：遵守本次不提交、不推送的范围；迁移结果由本计划、项目文档和备份承接，不重复写入 agentmemory，也不生成业务功能 QA PASS 记录。
- 验证边界：没有运行数据库、部署、浏览器自动化或业务全量测试；安装与文档迁移通过不代表新增业务功能或视觉验证通过。
