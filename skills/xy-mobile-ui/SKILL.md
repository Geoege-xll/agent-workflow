---
name: xy-mobile-ui
description: "按需指导 iOS、iPadOS、Android 原生界面和微信小程序的设计、实现与审查，覆盖安全区与键盘、导航与返回、状态生命周期及无障碍。"
---

## 官方 Antigravity 插件资源边界

本段仅适配资源与原生传输，不授予业务批准、角色所有权或 QA PASS。
从已加载组件的物理路径解析插件根目录：技能目录上两级，`agents/`、`rules/`
目录上一级；禁止用项目 cwd 或猜测缓存路径。先读根目录 `PLUGIN.md`。
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
批准。需要宿主集成时读取 `platforms/antigravity/references/pm-integration.md`。
插件由宿主原生发现、启用及更新。业务项目仅保留其自身配置。

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

当前插件沿用未绑定的源包合同，拒绝中央 `runtime_binding` 与中央项目标记，
不自动迁移。活动任务期间不得更新/替换插件；跨更新资源保留与实际模型/effort
执行仍需真实宿主证明。未获得对应证据时保留 `runtime_verified: false`。


# 移动端界面指导

当前任务影响 iOS、iPadOS、Android 原生界面或微信小程序的相关行为时，由设计者、实现者或 QA 按职责选用。普通 Web（含移动 H5）、桌面、纯业务逻辑及无关文案通常无需加载。嵌入原生 App 或小程序的 H5 若涉及宿主交互，本文仅指导受影响的宿主边界，网页本身沿用现有 Web 指导。

相对链接用于已发现的 Skill 内导航。通过插件的 `source_pack.py resource` 定位或以 `helper`
调用 `lib/documents/context_read.py` 分页时，从已验证的插件包读取，使用包内规范路径，例如
`platforms/shared/skills/xy-mobile-ui/references/mobile-rules.md`。

1. 完整读取[移动端共享规则](references/mobile-rules.md)，从当前需求、项目规范和实际页面选择适用条款。
2. 按受影响的平台读取 [Apple](references/apple.md)、[Android](references/android.md)或[微信小程序](references/wechat-miniprogram.md)。按实际框架、已接入的组件库和支持的系统或基础库版本选择方案。SwiftUI 存在实际平台知识缺口时，可继续选用已核验的 `xy-apple-guidance` 本机官方资料。
3. 设计沿用现有页面契约，开发与 QA 沿用现有交接。只有涉及来源核对或维护时才读[参考来源与许可](references/sources.md)。

现有设计、工程标准和项目批准范围继续适用。此指导采用项目现有技术栈、依赖和系统基线，并沿用已授权的原型、确认和独立 QA 流程。
