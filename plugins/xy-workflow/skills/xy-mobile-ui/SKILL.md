---
name: xy-mobile-ui
description: "Guide design, implementation, and review of native iOS, iPadOS, Android, and WeChat Mini Program interfaces, including safe areas, keyboards, navigation, state lifecycle, and accessibility."
---

从本 Skill 的物理目录向上两级确定插件根。使用同包的[宿主资源说明](../../plugins/plugin-context.md)。当前实例已具备同一物理来源、同一版本的完整说明时直接复用；独立启动或内容缺失时补读，来源或版本变化时重新读取。


# 移动端界面指导

当前任务影响 iOS、iPadOS、Android 原生界面或微信小程序的相关行为时，由设计者、实现者或 QA 按职责选用。普通 Web（含移动 H5）、桌面、纯业务逻辑及无关文案通常无需加载。嵌入原生 App 或小程序的 H5 若涉及宿主交互，本文仅指导受影响的宿主边界，网页本身沿用现有 Web 指导。

相对链接用于已发现的 Skill 内导航。通过插件的 `source_pack.py resource` 定位或以 `helper`
调用 `lib/documents/context_read.py` 分页时，从已验证的插件包读取，使用包内规范路径，例如
`platforms/shared/skills/xy-mobile-ui/references/mobile-rules.md`。

1. 完整读取[移动端共享规则](references/mobile-rules.md)，从当前需求、项目规范和实际页面选择适用条款。
2. 按受影响的平台读取 [Apple](references/apple.md)、[Android](references/android.md)或[微信小程序](references/wechat-miniprogram.md)。按实际框架、已接入的组件库和支持的系统或基础库版本选择方案。SwiftUI 存在实际平台知识缺口时，可继续选用已核验的 `xy-apple-guidance` 本机官方资料。
3. 设计沿用现有页面契约，开发与 QA 沿用现有交接。只有涉及来源核对或维护时才读[参考来源与许可](references/sources.md)。

现有设计、工程标准和项目批准范围继续适用。此指导采用项目现有技术栈、依赖和系统基线，并沿用已授权的原型、确认和独立 QA 流程。
