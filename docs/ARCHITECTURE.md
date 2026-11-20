# Agent Workflow 代码架构

## 系统概览

Codex、Claude 和 Antigravity 共享工作流规则和 Python 工具。各平台的插件入口负责接入宿主，PM 根据规则组织任务和文档，独立配置组件负责本机模型与角色设置。按业务主题查需求可回到[项目目录](PROJECT.md#主题目录)。

## 模块与目录

### 平台插件与构建

[插件构建器](../packaging/build_plugin.py)选择宿主资源、共享规则与工具，生成对应的插件包。[插件入口](../plugins/source_pack.py)负责在指定项目目录调用许可的工具。验证实际成品可从[解包测试](../tests/test_plugin_delivery.py)进入。

### PM 与任务交接

[工作流定义](../product/WORKFLOW.md)说明谁负责需求确认、实现与验收。[任务图命令](../lib/task_graph_cli.py)导出单任务所需的上下文，独立 QA 通过[验收交接命令](../lib/delivery/qa_handoff_cli.py)校验正式回执。

PM 统一向用户提方案。[业务确认规则](../product/WORKFLOW.md#business-confirmation-policy)定义何时要问，团队在这里维护产品行为。[方案确认模块](../lib/solution_confirmation.py)绑定请求和具体决定，并校验受影响任务的批准；批准记录、就绪查询和派发继续使用原任务图。

### 持续接单与任务池

[任务池入口](../lib/task_pool_cli.py)按当前项目与 PM 身份恢复登记。[索引](../lib/task_pool.py)定位任务原件，查询时再读当前摘要、任务状态和执行者。[准入命令](../lib/dispatch_admission_cli.py)依据实际容量、占用和批准裁决领取。[任务修订与撤回](../lib/task_intent.py)在原记录上处理新的要求、执行者确认和停止结果。对照用户指令可查看[持续接单示例](usage.md#pm-持续接单与调度)。

### 项目文档

[文档读取器](../lib/documents/context_read.py)按目标截取内容。[文档校验器](../lib/validate_project_docs.py)检查选定来源或查询引用关系。格式与验收范围由[文档管理主题](plans/plan-document-quality.md#需求与验收)维护。

### 本机模型配置

[配置命令](../native_config/cli.py)是独立组件入口。[偏好模块](../native_config/preferences.py)处理调用偏好；操作流程见[原生 Agent 配置](agent-configuration.md)。

## 关键调用链

### 方案确定后哪些任务可以开始

1. PM 在已有主题记录用户要决定的行为，为依赖该行为的原型或开发任务指定同一项决定。[方案确认指引](../platforms/shared/skills/xy-workflow/references/requirements-confirmation.md)
2. 用户明确选择后，PM 通过[任务记录更新](../lib/task_graph_records.py)提交当前请求、任务、决定及其内容。[方案确认模块](../lib/solution_confirmation.py)校验是否匹配。
3. PM 用[调度命令](../lib/task_graph_cli.py)查询就绪任务。正式交接与登记开发交付共用 [Writer 前置检查](../lib/writer_prerequisites.py)，核对当前批准、原型和基础阶段验收。多份任务记录共用一个决定时，[跨记录准入](../lib/dispatch_admission_cli.py)登记参与记录，[成员关系检查](../lib/shared_solution_records.py)向原记录查询当前正文和批准。

### 验收后怎样回写项目文档

[请求验收](../lib/foundation_qa.py)把独立 QA 的回执绑定到当时的开发产物、方案和实际采用的依据。PM 需要在受审文档上补记验收事实时，[文档投影校验](../lib/qa_projection.py)核对原稿、当前字节和可以修改的部分。[隔离交付检查](../lib/delivery/worktree_cli.py)使用同一请求的验收依据核对最终提交。核查返工后旧回执是否仍有效，可从[阶段与请求验收回归](../tests/test_foundation_qa.py)进入。

### 从插件读取一个项目文档章节

1. PM 指定项目物理目录、项目内文档和目标章节。平台通过[插件入口](../plugins/source_pack.py)的 `helper --project` 派发请求。
2. [文档读取器](../lib/documents/context_read.py)定位标题和范围，输出可继续读取的位置。读者按问题选择子节。
3. 修改该主题后，PM 用[文档校验器](../lib/validate_project_docs.py)检查来源中的文件与章节链接。读取边界的回归用例位于[文档读取测试](../tests/test_context_read.py)。
