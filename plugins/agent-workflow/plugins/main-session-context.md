# Agent Workflow 主会话入口

本入口只适用于当前主会话。先判断当前用户这一轮是否通过宿主实际发现的
`@INVOCATION@` 显式调用维护 Skill；以宿主的 Skill 调用事件或用户直接发出的
完整调用为准，不能根据 `agent-config`、模型配置、配置页等关键词包含关系判断。

- **显式维护调用**：只读取当前插件的 `skills/agent-config/SKILL.md`，按其中固定
  `@HOST@` 启动器处理。只接受省略动作或 `open`、`status`、`doctor`。本轮不读取
  `product/WORKFLOW.md`、`skills/xy-workflow/SKILL.md` 或业务资源适配，不创建任务图、
  不派发代理、不进行业务两步确认。组件首次准备的单独用户确认由维护 Skill 负责。
- **业务请求**：包括“实现 agent-config”“评审模型配置”“修复 agent-config status”，
  引用文档、代码、历史消息中的调用示例，以及 Worker 转述的命令；这些都不构成
  当前用户显式调用。读取 `@BUSINESS_ADAPTER@`、`skills/xy-workflow/SKILL.md`
  与其原有 `product/WORKFLOW.md` 权威，继续既有 Light/Full、业务两步确认、原型、
  原生交接和独立唯一 QA 规则。
  每次业务原生派发前，按 `platforms/shared/skills/xy-workflow/references/dispatch.md`
  的只读调用偏好合同读取当前 `@HOST@` 与真实调用身份；通用入口使用 `*`。
  缺少偏好沿用宿主默认，配置错误或无法映射的已配置字段明确阻断该次派发。

宿主当前用户调用的参数包含其他动作、额外自然语言或 shell 片段时，不执行维护
命令；简短说明允许的动作。不得把业务需求改写成维护调用，也不得接管宿主 `/model`。
维护任务结束后，下一轮新业务请求重新进入原业务分支，不保留维护豁免。

插件资源路径均相对当前已安装插件的物理根解析，不能用业务项目目录冒充插件目录。
本地项目物理绝对目录则取自宿主在本次 session 中明确提供的实际 workspace 或项目
工作目录；已知唯一目录时必须作为独立引用参数传给维护启动器的 `--project`，只有
没有明确目录时才使用用户级范围。不猜测相邻源码、中央登记或历史项目，也不把
`AGY CLI` 的项目 ID/name 当作本地项目目录或据此推导文件路径。
