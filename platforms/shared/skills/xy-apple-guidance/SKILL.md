---
name: xy-apple-guidance
description: 按任务需要选择并只读消费本机选定Xcode内Apple官方SwiftUI Specialist与What’s New in SwiftUI资料，用于相关SwiftUI实现或审查。
---

<!-- agent-workflow-pack:managed-skill -->

# xy-apple-guidance

此适配器是可发现的按需入口，不携带Apple正文。当前任务选用本技能后，通过当前物理
插件的既有 Python wrapper 使用 Python >=3.11：

```sh
python3 <当前物理插件>/plugins/source_pack.py apple-skills check
python3 <当前物理插件>/plugins/source_pack.py apple-skills read --skill swiftui-specialist --resource SKILL.md --expect-source-sha256 <check返回的source_sha256> --offset 0 --length 12000
```

`check` 按 `xcode-select` 或显式 `--developer-dir` 发现本机官方原始Markdown，报告真实
Xcode版本/build、物理来源和资源身份。当前只支持实际观察的Xcode27.x模板布局，它不是
Apple稳定导出API，不代表Xcode启动、导出或宿主模型采纳成功。

需要基础SwiftUI最佳实践时完整读 `swiftui-specialist` 的 `SKILL.md`；涉及SDK27新增或
变更行为时完整读 `swiftui-whats-new-27` 的 `SKILL.md`。再按原文选择当前任务必要的
`references/<name>.md`，使用同一 `source_sha256`，以 `next_offset` 连续读到 `eof=true`。
返回来源变化时丢弃未完成片段，重新check并从头读取；缺失、损坏或不支持应如实报告。

不启动Xcode、不全量导出、不修改系统或全局技能目录、不vendor正文或回退第三方镜像。
未选用时不由上游正文的强制措辞倒推必须选择；必需使用由上级指令或当前 Task Pack
明确要求，选用后遵守相关原文的适用步骤。其他宿主可用Skill按任务需要单独选择，不能
冒称Apple本机官方来源。此技能不扩展角色、
owned_paths、宿主权限或既有确认与唯一QA规则。
