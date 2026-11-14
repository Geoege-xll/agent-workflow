# 计划文档组织与有界校验

- 主题 ID：`plan-document-quality`
- 阶段：`completed`
- 模块：`platforms/shared/skills`、`lib/documents`、`templates/docs`
- 任务等级：`Full`
- 已验收版本：`3.0.0-alpha.10`

## 目标与范围

让计划能直接回答当前有效要求、已验收行为和下一步，减少重复、冲突状态与会话流水。用户于 2026-11-14 明确要求结合 Anthropic 官方 doc-coauthoring 优化，并承接此前六节格式、原地更新与有界校验建议。

本轮覆盖现有 xy-plan、PM 生命周期、唯一 QA 的文档可理解性检查、PLAN 模板及指定文件校验入口。整理 `native-model-preferences.md`、`workflow-document-lifecycle.md`、`selected-upstream-skills.md` 三份近期主题；保留真实需求、批准、验收及历史恢复来源。

不新增独立文档 Skill、不引入额外访谈或确认、不添加第二 Reviewer、不恢复计划 HTML，不批量迁移历史计划。用户未跟踪的旧迁移文档不读取、不修改、不暂存；不创建空 PROJECT／STANDARDS。

## 需求与验收

- REQ-401：保留五项元信息与六个固定章节；Full 章节顺序不变，Light 按既有保存需要保持轻量。
- REQ-402：借鉴分节组织、局部精修、去重一致性和读者问题检查；复用已知需求，不照搬上游多轮确认、占位输出或额外读者子代理。
- REQ-403：PM 更新原主题并替换失效内容。已验收基线与当前执行状态独立，完整日志和历史通过可恢复引用保存。
- REQ-404：新增 `validate_project_docs.py --root PROJECT_ROOT --plan PLAN`，`--plan` 可重复；不要求 PROJECT 已存在，不扫描未选择计划，不访问网络。原两位置参数入口和历史识别规则保持。
- REQ-405：显式选择的受管计划缺字段、无效字段、重复／错序／额外二级章节、危险路径或坏本地链接明确失败；代码围栏中的示例不冒充真实元信息或章节。不用关键词猜测自然语言事实矛盾。
- REQ-406：三份现有主题与本计划通过同一指定文件校验；唯一 QA 验源、回归和读者可理解性，验证工作流确认／权限边界不变。

## 方案与原型关联

固定参考为 [Anthropic doc-coauthoring](https://github.com/anthropics/skills/blob/00756142ab04c82a447693cf373c4e0c554d1005/skills/doc-coauthoring/SKILL.md)。原文只读保存为任务证据；本项目自行概括方法，不安装或执行第三方脚本。

写作细则放在 xy-plan 按需参考中，模板承载固定形状，生命周期说明 PM 写入时机；读者检查并入既有 QA。解析与路径／链接验证复用现有文档核心，CLI 仅负责参数映射；不另建文档框架或任务状态副本。此工作不涉及 UI 或原型变更。

两条实现工作可并行：规范与模板、解析器与回归；共同消费上述 CLI 和章节合同。PM 负责三份主题的结构整理；全部集成后由唯一独立 Reviewer 验收。沿用已授权的发布与本机同步顺序，验收前不替换安装中的插件。

## 当前进展与恢复入口

已验证：两条作者实现、plans＋runner 的实际 40 项、四份指定计划，以及三平台真实物理插件 helper 的包外消费。原 Reviewer 发现整理模型主题时遗漏具体第四版页面链接，PM 恢复后完成同一 Reviewer 增量验收；原失败和修复均保留。

已完成：本请求唯一 QA 对 16 路径、34 条工程规则及四份计划读者检查给出 PASS，PM 实际验证 schema 2 交接有效。源码验收不代表远程已发布或本机已更新；当前安装仍 alpha.9。

下一步：与用户已批准的角色技能绑定请求分别验收后，按同一最终源码完成 CI、发布及官方客户端更新。Apple／Modern Web 的实现与验收见 [角色技能主题](role-skill-routing.md)，不由本请求 PASS 推断完成。

## 验收结果与当前已交付行为

源码候选 `3.0.0-alpha.10` 已接受本轮行为：Full 五项元信息与固定六节、按需写作细则与同一 QA 读者检查；指定文件 CLI 无需 PROJECT 或配置，不扫描未选计划或读取链接目标正文。显式坏格式和危险路径返回失败，旧双位置参数与历史识别保持。三份主题已原地重组，保留既有 alpha.9 基线、需求编号、第四版页面／状态／指纹和必要历史。

本次没有新增访谈、确认、读者 Agent、文档 Skill 或计划 HTML；Light 的按需保存与简化边界保持。当前远程发布及本机版本另行记录。

## 批准依据与必要证据

- 批准依据：2026-11-14 用户“结合 Anthropic 官方 doc-coauthoring 进行优化”，承接此前已说明的模板、PM 更新规则、指定文件校验和活跃计划整理范围。
- 验收证据：唯一 Reviewer 当前 Pack SHA `6d0019d85ca35bad29a625559f199dc90f5d28b78c20eb3594e800caedd641f6`，handoff SHA `23501c62d4aa92167044abfb0fbae3225cf7ef0cf8741205921c2a99a956d1a9`；PM 实际 `qa_handoff_cli.py validate` 退出 0。完整差异 SHA `86578f5a4696ecfc4d7a41f400085e876e913af7b024428f8a71ac740128a8c4`，16 路径及 34 规则全部覆盖。

三份整理对象均在当前 Git 基线 `f63a98bedd9613dbfcf35dd5bbd97253f26f8c56` 中可恢复；本轮不删除原始日志或非 Git 材料。实际命令、完整日志和独立交接保留在本请求证据目录，不在计划中累积每次工具操作。

可恢复原始证据：`dist/evidence/plan-document-quality/plan-document-quality-evidence.zip`，SHA `0a6969379c2c3d425df914b6044a4dd26168c5ec25ecbd21150e204cec43d1d6`。包含首次缺 PyYAML、旧 CLI／坏 H2 复现、实际成功日志、PM 包外消费、初次审查发现与修复、完整当前 QA Pack 和交接；不把临时目录存在作为唯一恢复依据。
