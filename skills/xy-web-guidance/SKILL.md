---
name: xy-web-guidance
description: 按任务需要选择并查询随插件固定的GoogleChrome现代Web官方指导，适用于HTML、CSS和浏览器端JavaScript实现或审查。
---

## 官方 Antigravity 插件资源边界

本段仅适配资源与原生传输，不授予业务批准、角色所有权或 QA PASS。
从已加载组件的物理路径解析插件根目录：技能目录上两级，`agents/`、`rules/`
目录上一级；禁止用项目 cwd 或猜测缓存路径。先读根目录 `PLUGIN.md`。
唯一流程依据是其中的 `product/WORKFLOW.md`、`roles/`、
`platforms/shared/skills/`，以下共享正文保持原样。
宿主读取如被截断，按缺失行范围续读，或复用包内已有分页 helper；完整连续覆盖
当前任务所需权威范围后才执行。不重复读取已覆盖内容，不自行实现另一套分页器。

历史 `.agent-workflow/` 资源引用改由本插件的 `plugins/source_pack.py resource`
解析。每次独立调用都使用：
`bash <plugin-root>/lib/python_runtime.sh -B -X utf8 <plugin-root>/plugins/source_pack.py`。
原有辅助命令使用 `helper --project <absolute-project> <original-helper> <arguments>`；
它只选已有 Python 3.11+，不安装软件、不改 PATH。项目文档、任务与业务代码仍属于
真实项目；包内示例不是当前项目配置。

通过同一 helper 调用 `plugins/project_context.py inspect`，复用已验证的
`project.yaml`，或显式 `apply` 新候选 `.awf/project.yaml`；历史配置路径随实际选择
转换。`init --adapter <selected-path>` 必须传入同一配置。此入口不创建文档、不授予
批准。需要宿主集成时读取 `platforms/antigravity/references/pm-integration.md`。
插件原生发现取代旧安装、刷新与中央激活；不得运行 `runtime install`、
`runtime activate`、项目注册、`setup_*.sh`，或创建/修改项目 `AGENTS.md`、
`CLAUDE.md`、`.agent-workflow` 来使插件生效。

公开插件身份与别名以 `product/command_identity.json` 为准：插件 `xy-workflow`，
发现入口 `xy-config`、`xy-grill-me`、`xy-grilling`、`xy-taste`、`xy-playwright`，
按实际发现格式调用；canonical原name只保留在非发现vendor。先完整读取薄adapter及其
canonical，不以未知全局同名Skill代替，不传播原版hooks/allowed-tools为额外权限。

主会话始终是 PM。工作代理只接收当前完整任务包，使用 `instance_policy: fresh`、
`context_policy: handoff_only`，不得继承 PM 或其他代理历史。仅官方宿主派发代理；
使用宿主默认或已配置的模型与推理设置；PM 按 dispatch reference 只读映射业务派发偏好。
核心流程不依赖独立模型配置服务、网页或 MCP。
保留原有需求批准、适用的视觉批准与 Light 显式授权；需要独立 QA 时，仅一名只读
审查者，并遵守原有结项顺序。

Antigravity 通过本插件 `agents/` 原生发现角色。使用定义已核对到当前插件的原生
选择器；角色标签不证明实际角色、模型或上下文隔离。未知同名全局 `xy-*` 可能来自
旧流程，禁止据此作为本插件运行证据，或导入其中央 pin、历史与指令。若只能使用
通用原生入口，应以全新上下文交付当前完整角色正文与任务包；无法保证选择或隔离时
向 PM 报告宿主限制，不得宣称已运行。

当前 alpha 沿用未绑定的源包合同，拒绝中央 `runtime_binding` 与中央项目标记，
不自动迁移。活动任务期间不得更新/替换插件；跨更新资源保留与实际模型/effort
执行仍需真实宿主证明。未获得对应证据时保留 `runtime_verified: false`。


<!-- agent-workflow-pack:managed-skill -->

# xy-web-guidance

本入口是按需可选的项目适配规则，官方 canonical 原文位于非发现 vendor。当前任务选用本技能后，先用当前物理插件
`plugins/source_pack.py selected-skills read modern-web-guidance --offset 0 --length 12000`
读取原文；以返回的 `next_offset` 连续读到 `eof=true`，再按当前任务查询相关指导。

上游原文的 `npx ...@latest` 调用在本项目统一替换为固定本地入口：

```sh
python3 <当前物理插件>/plugins/source_pack.py xy-web-guidance -- search "confirmation modal dialog"
python3 <当前物理插件>/plugins/source_pack.py xy-web-guidance -- retrieve "<实际搜索返回的id>"
python3 <当前物理插件>/plugins/source_pack.py xy-web-guidance -- list
```

通过插件的既有 Python wrapper 选择 Python >=3.11。入口要求已有 Node >=22，使用完整
固定发布包内的模型和指南，关闭遥测、文件日志和隐式更新。`doctor` 只诊断环境；它不证明
实际查询成功或宿主模型采纳。读取长指南时遵照真实返回路径完整读取，不将截断输出当全文。
保留原指南的浏览器支持与项目 `.mwgrc` 约束；此适配器不修改该配置，不运行安装器或
`legacy-scan`。缺失或篡改应报告，不回退用户全局同名技能、npm/latest或未锁代码。

选用前不从 vendor 的 mandatory 措辞倒推必须选择本技能；必需使用由上级指令或当前
Task Pack 明确要求。选用后遵守原文的适用查询步骤，只消费当前任务相关内容。技能不
扩展角色、owned_paths、宿主权限或既有确认与唯一QA规则。
