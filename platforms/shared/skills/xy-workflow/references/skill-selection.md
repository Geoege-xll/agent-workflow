# On-demand Skill selection

This is the single shared Skill-selection policy for every Agent on Codex, Claude Code and
Antigravity: the PM, all implementation roles, `xy-uiux`, the single `xy-qa` reviewer, and consumers
of `xy-plan` or another workflow Skill. Apply it before selecting or using a Skill. It adds no
workflow stage, approval, role, delegation right or required inventory.

## Select from the actual task

1. Start with current explicit user instructions, the complete current Task Pack, actual repository
   stack, role responsibilities, applicable standards and the evidence gap to solve. Follow explicit
   higher-priority requirements and genuinely required Task Pack dependencies. Otherwise select a
   Skill only when it helps resolve the current technical risk or knowledge/evidence gap; reliable
   established project patterns or pure business-logic changes may need no supplemental Skill.
2. Narrow candidates using names and descriptions already exposed by the host. Built-in role
   recommendations are candidates, not mandatory selection or a closed whitelist. User-level,
   project-level and other-plugin Skills actually available in the current host may also be selected
   when they serve the authorized task.
   Do not enumerate personal Skill directories, scan every installed package, or preload every Skill.
3. Before application, completely read the selected `SKILL.md`. 使用各来源的读取机制，按该 Skill 当前分支要求的范围读引用。明确要求全文的引用须读完全文；定向引用须读完所选章节或条款及必要依赖。 A catalog description or a name
   alone is not the Skill body. Once selected, follow its applicable instructions; mandatory wording
   inside an unselected vendor Skill does not itself require selecting that Skill. Reuse unchanged
   text already fully available in the same instance under WORKFLOW's complete-reading policy;
   restore missing or changed required content.
4. Resolve the actual source before invoking it. Selected packaged recommendations use this verified
   plugin's qualified adapter or physical resource. Follow its packaged canonical source and vendor lock
   when applicable. A host-exposed same-named user/project/other-plugin Skill is a distinct source;
   never silently substitute it, mix its references/runtime with the packaged source, or call an
   unknown global name/latest release.
   Return unresolved same-name ambiguity or conflicting instructions to the PM.

读取多份已选 Skill 时，从宿主实际给出的物理入口逐份读取。每个工具回包只放一个文件的一页，
为正文和元数据留足输出预算，避免多文件 `cat` 或并行结果汇总后被宿主一起截断。
按物理路径、内容 SHA 和连续范围确认进度。某页截断时，仅从该文件上一完整页的末尾缩小分页续读；
其他文件已确认且仍在本实例上下文中的部分可直接复用。独立实例各自完整读取。
同包发现入口的分页命令和 EOF 判定见[完整读取必需长文](runtime-records.md#完整读取必需长文)。

## Required and supplemental Skills

`task.required_skills` contains only Skills genuinely indispensable to completing the current task,
not an inventory or an automatic copy of packaged recommendations. Invoke every required entry for
its applicable phase; unavailable or unresolved required Skills block that phase and must be reported
to the PM. A role's static resource binding alone does
not prove that its adapter/canonical text was read or that a command ran.

Within current responsibilities, each Agent may choose additional relevant Skills without asking
the PM to enumerate or approve an installed inventory. An unavailable optional Skill alone does not
block the base workflow: report the actual limitation and any uncovered required evidence. If an
explicit higher-priority requirement, required selected-Skill instruction or actual acceptance cannot
be met, return that specific blocker rather than treating the Skill as optional. Do not silently install, update or globally
configure Skills, tools or runtimes to fill a gap. Any such operation retains its existing user
authorization, host permission and dependency requirements.

## Recommended Web, Apple and mobile UI candidates

- For HTML/CSS/client-side JavaScript implementation or review with relevant Web API, compatibility
  or implementation uncertainty, consider `xy-web-guidance` to resolve that gap. The presence of Web
  files alone does not require loading it or querying guidance; established reliable project solutions
  and pure business-logic changes may proceed without it. When selected, follow its complete canonical
  read and fixed-runtime query instructions. Respect the repository's actual browser
  support policy and provide compatible fallbacks when required; guidance does not change approved
  UI authority or authorize dependency/browser-target upgrades. Backend, infrastructure and pure
  renames do not trigger an unconditional Web query. `xy-desktop` or `xy-uiux` may load it for an
  actual Web surface while retaining their original owner and prototype boundaries. Production browser
  evidence follows the existing project-test and `xy-playwright` policy.
- For SwiftUI work with an actual platform/API, state, layout or compatibility knowledge gap,
  consider `xy-apple-guidance`; SwiftUI files alone do not require loading it. Established reliable
  project solutions and pure business-logic changes may proceed without it. When selected, first
  resolve the local Apple-official SwiftUI Specialist.
  Use What's New guidance only for relevant new-API or migration work. Check and read the actual
  local source through the adapter's read-only resolver; missing local resources are reported, not
  replaced by automatically installed third-party mirrors. Relevant host-exposed concurrency,
  SwiftData or performance Skills may supplement it on demand. Do not impose Swift 6.2, replace
  UIKit with SwiftUI, change architecture or raise the minimum OS without current task authority.
- For design, implementation or read-only review of iOS, iPadOS or Android native UI or a WeChat
  Mini Program, consider `xy-mobile-ui` when the affected behavior raises a question about safe
  areas or insets, the keyboard, navigation or Back, state and lifecycle, or accessibility.
  Identify the target from the current Task Pack even when the prototype is delivered in HTML.
  Ordinary Web surfaces (including mobile H5), desktop surfaces and pure business logic do not
  qualify. For embedded H5, this candidate applies only to affected native or Mini Program host
  interactions. WeChat Mini Program behavior uses evidence from its host runtime and tooling.
  Read the shared mobile rules and relevant platform references from the same verified physical
  plugin root using the Skill's instructions. Continue to use applicable project standards and the
  established design, implementation and QA branches. SwiftUI-specific gaps may still need
  `xy-apple-guidance`; neither recommendation authorizes a framework change, a newer API requirement
  or a target upgrade.

After selecting the relevant entry, use the verified physical plugin root and its existing Python
selector for each independent call; these are conditional examples, not an every-task checklist:

```text
bash <plugin-root>/lib/python_runtime.sh -B -X utf8 <plugin-root>/plugins/source_pack.py selected-skills read modern-web-guidance
bash <plugin-root>/lib/python_runtime.sh -B -X utf8 <plugin-root>/plugins/source_pack.py xy-web-guidance -- search '<task-specific query>'
bash <plugin-root>/lib/python_runtime.sh -B -X utf8 <plugin-root>/plugins/source_pack.py xy-web-guidance -- retrieve '<selected ids>'
bash <plugin-root>/lib/python_runtime.sh -B -X utf8 <plugin-root>/plugins/source_pack.py xy-web-guidance -- list
bash <plugin-root>/lib/python_runtime.sh -B -X utf8 <plugin-root>/plugins/source_pack.py apple-skills check
bash <plugin-root>/lib/python_runtime.sh -B -X utf8 <plugin-root>/plugins/source_pack.py apple-skills read --skill swiftui-specialist --resource SKILL.md --expect-source-sha256 <source_sha256-from-check> --offset 0 --length 16000
```

The modern Web `search`, `retrieve` and `list` use the fixed packaged runtime/data offline and require
an existing Node 22+; do not run upstream npm/npx installation instructions or enable telemetry/log
files. The adapter's `doctor` only diagnoses readiness. Read the chosen guides, not every guide.
Apple `check` reports actual local source/version/build and resource fingerprints; follow `read`'s
offset/length continuation to read the complete selected Skill and required references, preserving
`--expect-source-sha256` from that check. Use `swiftui-whats-new-27` only when its subject applies.
If an explicit local developer directory is needed, use the same `--developer-dir <absolute-path>`
for check and read; do not change system Xcode selection or launch/export Xcode to manufacture resources.
Changed source fingerprints require a fresh check rather than combining bytes from different sources.

## Impeccable design guidance

`xy-uiux` 在当前获准设计任务确有设计方法缺口时，可按需选用提供离线方法的 `xy-impeccable`。沿用现有
设计系统即可完成的局部调整，可直接使用项目规范。用户要求、项目已采用的设计规范和适用移动端
规则优先。先确认页面类型和信息密度，紧凑应用、控制台和设置页按现有产品层级、组件及密度设计。

原版是当前物理插件根下非发现目录的 `third_party/selected-skills/impeccable/plugin/skills/impeccable/SKILL.md`。
选中后从同一物理根调用分段读取入口。每次 `read` 核对当前受管文件与必要来源。整包
`selected-skills check` 用于显式诊断，可独立运行。

```text
bash "<plugin-root>/lib/python_runtime.sh" -B -X utf8 "<plugin-root>/plugins/source_pack.py" selected-skills read xy-impeccable --offset 0 --length 12000
```

完整读完每段 `content`，用返回的 UTF-8 字节位置 `next_offset` 接续，核对 `path`、`sha256`、
`total_bytes` 一致，直至 `eof` 为真并覆盖全部字节。输出截断时从未读位置缩小分页重新读取。
读取原文链接的适用参考时，在同一条命令加上 `--reference reference/layout.md`（换成所需的
`reference/*.md` 相对路径），依相同分页合同读取。新表面可读取 `reference/new-work.md`，
设计细节可读取 `reference/craft-floor.md`；沿用既有设计系统时以该系统为准。必需来源缺失、损坏或读取不完整时，向 PM 报告受影响工作。

原型与 `standards_only` 只使用适用的设计方法，继续遵守既有静态原型验收、截图禁令和角色权限。
将上游 Setup、命令表与参考中的引擎、下载、hooks、截图、浏览器、后台及委派步骤作为原文背景。
本入口只读随包 Markdown；直接使用当前任务已有的产品背景、设计规范和获准工具。无需启动器或初始化。

## Desktop verification

`xy-desktop` 与 `xy-qa` 优先使用当前项目原生测试及已有有效运行证据。只有实际生产桌面能力
仍有证据缺口，且应用、数据、操作范围与宿主权限匹配时，才选用随包原版 `agent-desktop`。
浏览器交互继续遵循 `xy-playwright` 的 Web 取证规则，移动端使用对应宿主运行证据。
该工具沿用原型自动化边界、截图禁令与 QA 只读范围。原版描述中的宽泛触发词和示例均在当前
已授权任务范围内适用。

选中后完整读取同一物理插件根下的 `skills/agent-desktop/SKILL.md`。首版提供 macOS 运行时，
使用 `source_pack.py resource` 核验所选架构的包内资源，从其绝对路径直接运行原版 CLI：

```text
"<plugin-root>/third_party/selected-skills/agent-desktop/runtime/macos/<arm64-or-x86_64>/agent-desktop" status
"<plugin-root>/third_party/selected-skills/agent-desktop/runtime/macos/<arm64-or-x86_64>/agent-desktop" skills get platform
```

选择实际运行环境的 `arm64` 或 `x86_64`；CLI 使用同目录的 helper。后续命令也调用该绝对路径，
并按实际操作读取原版引用。由 `status` 核对平台、权限和支持的界面，资源缺失、权限被拒或平台
不支持时报告相关证据缺口。全局同名命令、自动安装和权限修改均不作为回退。

限定到隔离测试应用与数据，或用户明确授权的应用、窗口和数据；默认不读私人桌面、不自动执行
破坏性操作。动作前从当前视图核对应用、窗口、控件和业务对象名称（含目标行标签），使用与目标
一一对应的新鲜 ref。界面变化后重新获取，目标含糊或 ref 失效时先回读定位；动作结果不确定时
先核对状态，按上游的投递与重试约定处理，避免重复提交。动作后回读同一对象并核对预期状态；涉及
相邻条目的验证还要确认旁边条目未被误改。默认使用语义动作，物理输入须有明确用户授权和宿主许可。
QA 仅执行获准的只读取证，需写入或提交的验证请求交回 PM。分别记录资源校验、实际命令和 GUI
结果，只有实际应用的回读才能作为对应交互的运行证据。

## Authority and evidence stay with their existing owners

Skills provide methods and evidence within existing authorization. They do not expand exact
`owned_paths`, roles, network/tool permissions, native dispatch authority or read-only QA scope;
do not propagate upstream hooks or allowed-tools as new permissions. Preserve the existing
request-scoped decision policy in `product/WORKFLOW.md#business-confirmation-policy`, applicable prototype choice, fresh/handoff_only instances,
and the single independent QA reviewer. External workflows never replace or wrap this control plane.
Loading Web guidance does not authorize prototype browser automation or screenshots; Apple official
guidance does not replace destination-specific build/test, signing or release evidence.

In the existing handoff, state the actual Skill source (qualified name or physical path and known
version/fingerprint), purpose/scope and any relevant conflict or limitation. Distinguish complete
Skill reading, successful actual CLI/query execution and observed host-model adoption: none proves
the next. Report commands, exit codes and resolvable full logs only for work actually executed;
do not create a second Skill registry, approval record, evidence stage or QA process.
