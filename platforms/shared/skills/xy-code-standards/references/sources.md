# 来源与采用边界

本文件供维护与追溯时按需读取，不是每次实现的必读资料，也不要求联网、安装或运行
第三方工具。以下只借鉴方法，正文为中文重新组织；项目规范、授权与验证合同保持原权威。

## Karpathy 社区指南

- 原入口：[forrestchang/andrej-karpathy-skills](https://github.com/forrestchang/andrej-karpathy-skills)；
  核对时重定向至 `multica-ai/andrej-karpathy-skills`。
- 一手文件：[karpathy-guidelines/SKILL.md](https://github.com/multica-ai/andrej-karpathy-skills/blob/main/skills/karpathy-guidelines/SKILL.md)。
  该文件 frontmatter 声明 `license: MIT`；这是整理 Karpathy 观察的社区项目，不称作其官方发布。
- 采用：显式区分假设、控制修改范围、以可核对结果判断完成。
- 未采用：固定行数目标、单次使用一律不得抽象、所有疑问都停止询问，以及示例中的
  测试先行步骤。是否抽象、确认或补测试仍按实际边界和既有合同判断。

## Vercel 官方工程 Skill

- 一手仓库：[vercel-labs/agent-skills](https://github.com/vercel-labs/agent-skills)。
- 一手文件：[react-best-practices/SKILL.md](https://github.com/vercel-labs/agent-skills/blob/main/skills/react-best-practices/SKILL.md)。
  文件标注作者 `vercel` 并声明 `license: MIT`。
- 采用：按实际影响组织关注点，用命中条件决定详细参考的读取范围。
- 未采用：React/Next.js API、缓存与渲染规则、依赖、版本或该技术栈的风险排序；
  不将它们推广成所有语言和项目的要求。

## 本地抽查与维护

已用不同技术栈的项目规范及真实模块/测试校验方法的适用性。具体项目、源码位置和
会话证据留在任务交接，不作为使用本 Skill 的前置依赖，不复制业务规则或机器路径，
也不从示例推断统一框架、版本或视觉风格。

后续更新应核对实际采用文件的来源与许可声明；若复制第三方文本或代码，按该版本保留
适用的许可与归属信息。当前内容不引入强制 TDD、额外 review、提交或发布流程。
