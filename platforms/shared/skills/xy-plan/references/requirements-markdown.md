# Requirements Markdown delivery and retained prototype navigation

Full 用一份 Markdown 正式审阅。批准前可以暂存本请求的草稿区，由 PM 按范围、实质方案及实际页面的确认进展在同一原稿逐步补齐，相关设计或实现派发前保存当前可恢复内容。已有主题原位更新，纯执行或符合性修复可使用已有、跨会话可取回的请求交接。Light 仅在存在实际恢复、交接需要或用户明确要求时保存。具体归属见[计划生命周期](../../xy-workflow/references/plan-lifecycle.md)。

Requirements/plan Markdown-to-HTML generation has been retired. Its Python module, renderer bundle,
licenses and helper entry have been removed from current source and packages. Current planning, review,
dispatch and QA use Markdown and must not require a same-name HTML file or current HTML hash. The
workflow needs no Node runtime for plan delivery. Prototype design, concrete HTML pages, prototype
verification, dependency fingerprints and user visual approval remain required wherever applicable.

## Current source and prototype coverage

原型绑定要求批准源位于适配器配置的 `docs.plans`，优先选用与本次页面及当前有效需求相符的已有主题。保留真实批准来源和原始 Markdown，继续校验页面、范围、依赖指纹与视觉确认。主题原稿分别陈述本次需求与上次已验收版本和行为。PROJECT 的普通目录项可以导航至在研主题，已验收声明须有真实证据。取消本轮目标仍保留上次基线。

Use stable REQ IDs and ordinary links for prototype coverage. The design Agent returns concrete pages
and actual state anchors in the existing handoff; PM writes them into the same Markdown. For default
paths, a link may be `[Editor error](../standards/prototype/editor.html#error-state)`. Check only actual
scoped references, without preloading the whole prototype tree or adding a mapping report/independent
prototype QA. Requirement fingerprints, prototype dependency fingerprints, visual approval and production
QA retain their separate responsibilities. 实现者读完当前自包含任务包。PM 提供完整需求 Markdown 的来源，
在包中用 REQ ID、章节及必要依赖标出读取范围，按[受控文档读取约定](../../xy-workflow/references/runtime-records.md#完整读取必需长文)执行。

同一稿件保留历史需求时，在建立新原型评审前，将唯一的 `### 当前有效需求` 直接放在
`## 需求与验收` 下。每条定义以稳定 REQ ID 开头，例如 `- **REQ-001** 可验证行为`；可用行首、列表项、
表格首列或下级标题。下一个同级或更高标题结束当前范围，历史定义放在其他标题下。
正文引用、其他章节、围栏示例和 HTML 注释不会进入新评审目录。可见标记重复、位置不符或没有有效定义时，
指定计划校验与新评审捕获会明确失败。未标记的计划沿用既有提取规则，按需只更新当前主题。
评审身份仍绑定 Markdown 的完整原始字节；已发布快照保留登记目录，通过当前来源验证仍须匹配完整来源指纹。

A requirements-bound prototype page declares the canonical Markdown in `body[data-prototype-plan-source]`
and has one Markdown link in its unique `nav.prototype-requirement-links`. An existing same-name historical
HTML link is optional. Both kinds require their safe actual file, `target="_blank"` and `rel` containing
`noopener`; they remain document navigation rather than render dependencies. Old HTML records, engine
identities and source hashes cannot block Markdown edits. An unlinked old HTML is not read. Preserve
canonical paths, project boundaries, safe single-link regular-file reads and concurrent-input rejection.
Do not bulk-edit historical prototypes merely to remove their retained HTML links.

## Explicit project adapter and retained material

Use the exact project adapter selected during project inspection and task initialization. Pass that same
project-relative path through the prototype validator's `--adapter` option and its API's `adapter` argument;
do not independently search or prefer `.awf/project.yaml`, `project.yaml` by precedence.
Multiple adapters require an explicit selection. The configured `docs.plans` and `docs.standards_root` both
come from that selected adapter, including custom document roots. Plugin helpers retain the actual physical
plugin/project boundary.

Existing plan HTML, original Markdown, prototype HTML, design standards and project information remain
historical or active project material according to their existing role. Removing the generation chain does
not authorize deletion, renaming, regeneration or bulk conversion of those files. Historical HTML has no
current editing authority and grants no acceptance or approval. Its optional prototype navigation link
continues to require a safe actual file and concurrent-input verification through the shared
`lib/documents/safe_documents.py` primitives.
