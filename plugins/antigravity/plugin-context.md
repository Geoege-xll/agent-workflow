## 官方 Antigravity 插件资源边界

本段仅适配资源与原生传输，不授予业务批准、角色所有权或 QA PASS。
从已加载组件的物理路径解析插件根目录：技能目录上两级，`agents/`、`rules/`
目录上一级；禁止用项目 cwd 或猜测缓存路径。先读根目录 `PLUGIN.md`。
当前实例已具备同一物理来源、同一版本的完整内容时直接复用。
唯一流程依据是其中的 `product/WORKFLOW.md`、`roles/`、
`platforms/shared/skills/`，以下共享正文保持原样。
宿主读取如被截断，按缺失行范围续读，或复用包内已有分页 helper；完整连续覆盖
当前任务所需权威范围后才执行。不重复读取已覆盖内容，不自行实现另一套分页器。

包内资源使用相对插件根的规范路径，通过 `plugins/source_pack.py resource` 解析。每次独立调用都使用：
`bash <plugin-root>/lib/python_runtime.sh -B -X utf8 <plugin-root>/plugins/source_pack.py`。
原有辅助命令使用 `helper --project <absolute-project> <original-helper> <arguments>`；
它只选已有 Python 3.11+，不安装软件、不改 PATH。项目文档、任务与业务代码仍属于
真实项目；包内示例不是当前项目配置。

通过同一 helper 调用 `plugins/project_context.py inspect`，复用已验证的
`project.yaml`，或显式 `apply` 新候选 `.awf/project.yaml`。`init --adapter <selected-path>` 必须传入同一配置。此入口不创建文档、不授予
批准。PM 收到已登记 Writer 的原生验收结果时，从插件根定位
`platforms/antigravity/references/pm-integration.md#writer-completion`，按「Writer 验证结果回写」
使用 `pool complete-writer` 核对并回写原件。仅原型设计也用这一入口。新的初始派发按同一宿主说明使用
`pool handoff` 的完整 Prompt，每次仅交接该领取的任务包及 owned_paths。所有已登记状态只能通过正式 helper 回写。
Full 开始独立 QA 前，先读同一说明的 `#full-qa-closeout` 并执行到收口：普通 Full 先冻结范围再领取，
绑定原生 QA 后导出正式验收包，接纳有效回执，按计划回填并核对已有主题。Writer 与 QA 的任务池状态均须回查。
其他宿主操作按需定位 `platforms/antigravity/references/pm-integration.md` 的相关小节。Reviewer 遇到审查方法缺口时读其中的 `Native review method` 小节及其调用约束。
插件由宿主原生发现、启用及更新。业务项目仅保留其自身配置。

公开插件身份与别名以 `product/command_identity.json` 为准：插件 `xy-workflow`，
发现入口 `xy-config`、`xy-grill-me`、`xy-grilling`、`xy-impeccable`、`xy-playwright`，
按实际发现格式调用。官方 `agent-desktop` 使用上游原名直接发现。通过 `xy-` 别名
提供的上游技能须完整读取选中的薄适配及其包内原文。不要用未知全局同名技能代替，
也不传播原版 hooks/allowed-tools 为额外权限。

主会话始终是 PM。工作代理只接收当前完整任务包，使用 `instance_policy: fresh`、
`context_policy: handoff_only`，不得继承 PM 或其他代理历史。仅官方宿主派发代理；
使用宿主默认或已配置的模型与推理设置；PM 按 dispatch reference 只读映射业务派发偏好。
核心流程不依赖独立模型配置服务、网页或 MCP。
需求、实质方案与具体页面的适用确认遵循 `product/WORKFLOW.md#business-confirmation-policy`，沿用 Light 显式授权；需要独立 QA 时，仅一名只读
审查者，并遵守原有结项顺序。

Antigravity 通过本插件 `agents/` 原生发现角色。使用定义已核对到当前插件的原生
选择器；角色标签不证明实际角色、模型或上下文隔离。未知同名全局 `xy-*` 可能来自
旧流程，禁止据此作为本插件运行证据，或导入其中央 pin、历史与指令。若只能使用
通用原生入口，应以全新上下文交付当前完整角色正文与任务包；无法保证选择或隔离时
向 PM 报告宿主限制，不得宣称已运行。

当前插件沿用未绑定的源包合同，拒绝中央 `runtime_binding` 与中央项目标记，
不自动迁移。活动任务期间不得更新/替换插件；跨更新资源保留与实际模型/effort
执行仍需真实宿主证明。未获得对应证据时保留 `runtime_verified: false`。
