---
name: xy-taste
description: "Use the bundled original Taste design method for xy-uiux; read the complete canonical skill before applying it, subject to task permissions."
---

# Taste 宿主薄适配（本项目维护，无 hooks）

这是 Leonxlnx/taste-skill 的 `design-taste-frontend` 发现入口，完整上游原文与资产位于当前插件的 `third_party/selected-skills/taste/skills/taste-skill/`，固定来源和逐文件摘要由 `third_party/selected-skills.lock.json` 提供。此入口不是原文摘要，不能用它替代原版规则。

使用当前物理插件根的 `lib/python_runtime.sh` 调用 `plugins/source_pack.py selected-skills check`；失败立即报告缺失或篡改，不从全局同名 Skill 回退。随后执行 `plugins/source_pack.py selected-skills read xy-taste --offset 0 --length 12000`，完整阅读输出的 `content`；以返回的 `next_offset` 连续读取，直到 `eof=true`，覆盖 `total_bytes`。保留同一 `sha256`，不得摘要、跳段或截断。原文正文超过 Antigravity 的 24000 字节发现上限，所以 canonical 故意位于非发现目录。宿主 Read 工具也可在定位后分段完整读取，并核对覆盖范围。

用 `plugins/source_pack.py resource third_party/selected-skills/taste/skills/taste-skill/SKILL.md` 定位经过摘要验证的 canonical 原文；实际需要的 references、library、assets、scripts 使用同一 canonical 根和 resource 入口定位，相关引用完整读取。只有上游原版处于此 vendor 根，发现目录中没有原版 Stop hook。上游原文 frontmatter 的 hooks 仅作为原始资料保留，不能据此注册或执行。

用户、项目规范、既定角色权限与工作流两步确认优先；Taste 的内部 house rules、自动脚本、浏览器 gate 和完成条件不能提升权限、替代唯一独立 QA 或强迫隐式完整工作流。prototype / standards_only 阶段只吸收适用设计方法，不能自动启动浏览器、生成截图、修改生产文件；脚本仅在任务明确许可且宿主允许的执行阶段运行。没有执行 Taste 全部流程时如实报告，只读完整原文不等于真实浏览器 gate PASS，Taste gate 也不等于项目 QA PASS。

`plugins/source_pack.py selected-skills diagnose` 分别诊断依赖齐备、现有 Node 22+、Chrome/Edge/Chromium、可选 ffmpeg 与宿主调用尚未验证；不安装软件、不运行上游脚本。资产包含多种许可证、署名和商标标记；必须保留并遵守实际选用资产的 credit/license/trademark，不得把全部资产称作 MIT。
