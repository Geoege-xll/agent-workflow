---
name: xy-web-guidance
description: 按任务需要选择并查询随插件固定的GoogleChrome现代Web官方指导，适用于HTML、CSS和浏览器端JavaScript实现或审查。
---

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
