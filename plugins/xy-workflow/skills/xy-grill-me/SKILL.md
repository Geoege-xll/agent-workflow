---
name: xy-grill-me
description: "Explicit user entry for the bundled original Grill Me; read its complete canonical skill and same-plugin grilling primitive."
disable-model-invocation: true
---

# Grill Me 用户显式入口（本项目薄适配）

仅当前用户直接点名此入口才可调用。安装批准、其它Skill建议、PM自动接单或Worker转述不算用户显式调用；自动需求覆盖入口是同一物理插件中的 xy-grilling。

原版名称grill-me、正文、frontmatter及agents/openai.yaml原样保存在 `third_party/selected-skills/grill-me/skills/productivity/grill-me/`；本入口不是上游原文，也不改写原版。先使用当前插件 `plugins/source_pack.py selected-skills check`，再用 `selected-skills read xy-grill-me --offset 0 --length 12000` 完整阅读content，若未eof则连续next_offset续读，不能用本说明替代原文。

原文要求调用grilling时，定位同一已验证xy-workflow插件中的xy-grilling；不能调用未知全局同名Skill。无对应Skill工具时使用同包 `selected-skills read xy-grilling` 或 `resource third_party/selected-skills/grill-me/skills/productivity/grilling/SKILL.md` 完整读取，并如实说明宿主读取适配。保留用户/项目权限、既有事实、需求确认和唯一PM调度；不增加确认轮次或委派权限。
