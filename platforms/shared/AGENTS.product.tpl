# Agent Workflow 2.0 bootstrap

由`agent_workflow`生成；适配器：`.agent-workflow/project.yaml`。

## 必需边界

- 仅Light／Full与schema_version:2，不保留旧等级／任务交接兼容。PM负责协调、计划、交接、
  文档目录和已验收投影。实施默认派对应原生subagent；只有用户明确让PM本身亲自实现当前
  范围时例外，原等级要求不降。普通“开始／继续／优化”和摘要不产生例外。
- 派发前判断实际范围、消费者与风险。Light使用当前自包含任务包、最小充分验证；不强制
  Full规划、DAG、保存计划、重复确认或独立QA。交接时评估必要独立审计、文档与记忆。
  Full保留适用需求确认、规划、DAG与唯一只读请求QA；局部验证不能写QA PASS。
- 任务含workflow_level、规范化module、role、稳定agent_alias、instance_policy:fresh、
  context_policy:handoff_only。新实现者／QA不得继承或复制完整PM／兄弟会话，不fork父历史，
  只接收当前目标范围、代码／工作区事实、规范、可信授权、验收证据和未决事项。
  每位接收者完整读当前包与必需规范，指纹和别人已读不是自己已读证明。
- 职责别名长期保留，独立任务按需新实例／新ID；同任务连续实现、短返工以及同轮原Reviewer
  差量复查可续用。不可改历史agent_ref，不以resume／compact宣称清空旧历史。
  不预热全部别名、不填满上限，按宿主真实运行／打开线程口径为必要QA／集成安排容量。
- 完成接收、必要验证／QA和证据保护后原生结束；无工具或失败只不可逆退役、阻止误派，
  不宣称物理清空／销毁或释放未确认容量，退役不释放仍活动锁。压力时优先已验收且交接
  充分实例，不能简单LRU淘汰执行中、未交证据或必要复查者。AGY kill前保护临时worktree
  与唯一日志；取消／异常保留恢复边界，不删除仍被引用的成果／证据。
- Full按READY在真实容量内派发独立任务，一路径一Writer；失败只阻塞下游，容量等待不是
  语义依赖。只读审计交付结论后停止，不对审计报告再审或创造实现QA PASS。
- Full的requirements_approved及原型选择沿现有规则；UI-Conformance使用冻结设计权威，
  无视觉门禁；设计变化由用户选择原型或直接开发，只有required原型增加visual_approved。
  不能发明用户选择或为同步生产修改重启原型。设计Agent三维自检、用户最终确认及原型
  豁免保留。平台安全权限单独执行，别名与任务字段不授予新权限。
- 项目文档／agentmemory仅补具体缺失事实；当前用户授权、代码和有效证据优先。没有严格
  项目隔离与来源时不调用provider recall／save。ProjectProfile只帮助路由，不授予写权限。
- 路径从已知事实、配置索引或一次范围限定列表定位，不猜文件；检查当前宿主实际资源变化，
  复用有效安装证据，不因新提示重复安装。工程／UI规范按领域选择，索引存在才读适用项目叶，
  不复制通用正文。编写代码按[代码方法与工程规则](.agent-workflow/platforms/shared/skills/xy-code-standards/SKILL.md)。
- 独立QA使用当前2.0包与结果身份／SHA绑定，validate／extract必须传当前--task-pack。
  Full顺序为QA PASS→文档投影→PM提交评估→按需记忆→最终报告；Light完成实际选定分支。
  现有强制检查、保护路径、唯一Reviewer及有界差量返工保留。
- Worker向PM报告完成、阻塞与有意义进度；PM需要时询问原Worker，不例行读子会话历史。
  内部YAML／DAG不直接输出给用户；单次确认前先给完整的决策说明。Hooks只辅助提醒，
  不证明授权、完成、QA或实例已结束，不新增runner、Agent池或默认团队模式。

## 按当前操作读取

实施先用当前宿主的xy-workflow；本入口链接同一权威，不是另一份需重复加载的流程。
选定Skill与其必需指令完整读取；普通项目资料和条件分支按实际需要，恢复缺失／变化部分。

| 当前操作 | 详细规则 |
| --- | --- |
| Light／Full编排入口 | [xy-workflow](.agent-workflow/platforms/shared/skills/xy-workflow/SKILL.md) |
| 接收、风险分级、Light单包或Full规划确认／派发 | `xy-workflow/references/dispatch.md` |
| UI分类、原型选择、契约和用户视觉确认 | `xy-workflow/references/ui-design.md` |
| 初始、增量或替换设计规范 | `xy-workflow/references/design-standards.md` |
| 计划保存、修改、恢复与完整任务替换 | `xy-workflow/references/plan-lifecycle.md` |
| 验证、反馈、必要QA与差量返工 | `xy-workflow/references/implementation-and-qa.md` |
| 多功能独立worktree、集成与本地主分支交付 | `xy-workflow/references/worktree-delivery.md` |
| 文档／记忆与提交评估、实例和证据收口 | `xy-workflow/references/closeout.md` |
| 2.0包导出、身份／续用／退役的记录工具 | `xy-workflow/references/runtime-records.md` |
| 产品权威与实例边界 | `.agent-workflow/product/WORKFLOW.md`的implementation-ownership／agent-instance-lifecycle |

<!-- bootstrap-contract: platforms/shared/skills/xy-workflow/SKILL.md -->
