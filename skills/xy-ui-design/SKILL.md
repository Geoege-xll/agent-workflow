---
name: xy-ui-design
description: "For xy-uiux to design high-fidelity interactive HTML prototypes in prototype mode or maintain authorized design standards in standards_only mode; production implementation and QA consume applicable rules only under existing design authority, without creating prototypes or gaining write authority."
---

## 官方 Antigravity 插件资源边界

本段仅适配资源与原生传输，不授予业务批准、角色所有权或 QA PASS。
从已加载组件的物理路径解析插件根目录：技能目录上两级，`agents/`、`rules/`
目录上一级；禁止用项目 cwd 或猜测缓存路径。先读根目录 `PLUGIN.md`。
唯一流程依据是其中的 `product/WORKFLOW.md`、`roles/`、
`platforms/shared/skills/`，以下共享正文保持原样。
宿主读取如被截断，按缺失行范围续读，或复用包内已有分页 helper；完整连续覆盖
当前任务所需权威范围后才执行。不重复读取已覆盖内容，不自行实现另一套分页器。

历史 `.agent-workflow/` 资源引用改由本插件的 `plugins/source_pack.py resource`
解析。每次独立调用都使用：
`bash <plugin-root>/lib/python_runtime.sh -B -X utf8 <plugin-root>/plugins/source_pack.py`。
原有辅助命令使用 `helper --project <absolute-project> <original-helper> <arguments>`；
它只选已有 Python 3.11+，不安装软件、不改 PATH。项目文档、任务与业务代码仍属于
真实项目；包内示例不是当前项目配置。

通过同一 helper 调用 `plugins/project_context.py inspect`，复用已验证的
`project.yaml`，或显式 `apply` 新候选 `.awf/project.yaml`；历史配置路径随实际选择
转换。`init --adapter <selected-path>` 必须传入同一配置。此入口不创建文档、不授予
批准。需要宿主集成时读取 `platforms/antigravity/references/pm-integration.md`。
插件原生发现取代旧安装、刷新与中央激活；不得运行 `runtime install`、
`runtime activate`、项目注册、`setup_*.sh`，或创建/修改项目 `AGENTS.md`、
`CLAUDE.md`、`.agent-workflow` 来使插件生效。

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

当前 alpha 沿用未绑定的源包合同，拒绝中央 `runtime_binding` 与中央项目标记，
不自动迁移。活动任务期间不得更新/替换插件；跨更新资源保留与实际模型/effort
执行仍需真实宿主证明。未获得对应证据时保留 `runtime_verified: false`。


<!-- agent-workflow-pack:managed-skill -->

# xy-ui-design

## Usage Boundaries

Follow the current Task Pack, applicable project standards, and the permanent responsibilities of
`xy-uiux`. Loading this Skill does not grant write authority or change the task level, implementer,
user's prototype choice, UI-Conformance, approvals, or the single independent QA route. The PM's
selected `design_mode` determines the applicable stage; preloading does not require every branch.

- `prototype`: Work only within the currently authorized required-prototype scope and deliver
  stable, build-free, directly openable, high-fidelity interactive HTML. Early wireframes serve only
  IA and option comparison; they cannot be the final prototype.
- `standards_only`: Maintain only the precisely authorized design-standard leaves under the existing
  `xy-workflow/references/design-standards.md`; do not write HTML/CSS, run prototype verification,
  or request visual approval.
- Production implementation and QA: Read and consume only the currently adopted design authority
  and applicable professional rules. Do not use this Skill to change design direction, expand
  owned_paths, or restore prototype gates for waived/UI-Conformance work.

## Baseline and Design Analysis

The following design operations apply to authorized `xy-uiux` tasks; production implementation and
QA consume applicable rules against existing authority without executing design stages or triggering
prototype verification. Read the applicable clauses in [design foundations](references/foundations-rules.md)
and [component interactions](references/components-rules.md) for general rules; the project retains only
its actually adopted tokens, styles, dimensions, platform mappings, and business differences. When a
project-specific standards index exists, follow its actual links, then check relevant product evidence
and current pages. Reuse context that has been read in full and remains unchanged; do not assume leaf
filenames or preload the entire project. Approved requirements and project rules take precedence.
Activate the bundled `xy-taste` **no-hooks adapter** for Taste design judgment and follow
its complete canonical reading contract below. Advice is subordinate to the current user requirements,
project standards, role permissions and frozen authority. Establish the actual page type and density
first: compact application consoles/configuration pages must not inherit marketing hero sections,
full-screen whitespace, oversized type or decorative imagery by default. Reuse the existing project
baseline; original upstream guidance does not establish suitability for every page.

## Taste Canonical Reading and Execution Boundary

The original is kept intact outside host discovery at
`third_party/selected-skills/taste/skills/taste-skill/SKILL.md`; provenance, fixed commit, complete
inventory and licenses are in `third_party/selected-skills.lock.json`. The discovered adapter is
project-authored and carries **no hooks**. Never copy/register the original Stop hook, run `--hook`,
or replace the original with a summary or a truncated discovery body.

For an installed plugin, resolve only its current physical plugin root, then run:

```text
bash <plugin-root>/lib/python_runtime.sh -B -X utf8 <plugin-root>/plugins/source_pack.py selected-skills check
bash <plugin-root>/lib/python_runtime.sh -B -X utf8 <plugin-root>/plugins/source_pack.py selected-skills read xy-taste --offset 0 --length 12000
```

Read every returned `content` completely. Continue with the returned `next_offset` (UTF-8 byte
position) and the same length until `eof: true`; verify continuous offsets, consistent `path`, `sha256`
and `total_bytes` across chunks, and coverage from zero through total_bytes. If output is truncated,
request a smaller chunk at the unconsumed offset; byte validation alone is not the Agent reading.
Source-pack development reads that same canonical completely, in bounded segments when needed.
After the full SKILL.md, use `source_pack.py resource` with the canonical skill prefix to locate and
fully read references actually needed by the current stage. Preserve assets/credit/license/trademark
metadata; top-level MIT is not a license claim for every asset. Missing/corrupt files, incomplete reads
or unavailable tools block the dependent design work and return to PM; never claim they were loaded.
No per-task reading report is required; retain actual read evidence in the ordinary handoff.

Reading Taste does not run its complete operational pipeline. In `prototype` and `standards_only`,
consume applicable design judgment only: do not automatically arm a gate, execute scripts, launch a
browser, capture screenshots, start a server, fetch fonts/assets, install tools, write production code,
or dispatch another workflow. Existing build-free/file:// prototypes, static verification and the
no-screenshot rule take precedence. A script may run only when the current Task Pack and host
permissions authorize that exact operation; never execute merely because an upstream step is mandatory.
`selected-skills diagnose` checks existing Node >=22/browser/optional ffmpeg separately from bundled
resource completeness without installing or running upstream scripts. A Taste gate is never workflow
QA PASS; if the pipeline/gate was not run, say so and do not claim upstream full-run completion.
This boundary adds no design/QA/approval file, gate, parallel reviewer or confirmation stage.

<!-- workflow-contract: references/foundations-rules.md -->
<!-- workflow-contract: references/components-rules.md -->

## Read by Stage

For design analysis, page refinement, or standards maintenance, read
[design quality and completion criteria](references/design-quality.md). Address content hierarchy,
components, states, platforms, and accessibility as applicable to the current task; do not expand
design scope to fill a checklist.

<!-- workflow-contract: references/design-quality.md -->

Only when organizing pages and presentation in `prototype` mode, read the
[HTML prototype canvas](references/prototype-canvas.md). It carries forward the role's existing canvas
contract without requiring unrelated page rework or adding prototypes to direct-development branches.

<!-- workflow-contract: references/prototype-canvas.md -->

## Verification and Handoff

For `prototype`, the design Agent self-checks requirement coverage, standards conformance, and
delivery consistency, reusing `xy-prototype-verify` static verification and the five-section in-page
contract. Hand off results through the existing `static_checks`, `blocking_findings`, and `result`;
do not create independent prototype QA, reports, or approvals. Final confirmation remains with the
user. Hand off only concrete pages, scope, operations, shared impact, real evidence, and unverified
items to the PM. Static success does not establish visual satisfaction or correctness of all
interactions; the PM still handles user visual confirmation through the existing route. Do not
generate, save, attach, or present screenshots. Do not automate prototype browser operations by
default; preserve only the user-request/failure-diagnosis exceptions in the existing verification
contract. PM semantic review and QA boundaries continue to use that contract.
In the existing handoff, return requirement coverage by stable REQ identifiers with concrete pages
and actual state anchors. The PM writes these back to the single requirements Markdown.
Requirements/plan Markdown-to-HTML generation is retired under [the retained reference](../xy-plan/references/requirements-markdown.md);
keep any existing HTML as historical material without requiring an update.
需要评审整改时，按需读取 [反馈消费合同](references/prototype-feedback.md)，通过当前物理插件根
`prepare` 生成项目外不可变快照；项目只保留具体 HTML/CSS/JS 与五段页面契约，不复制通用壳。
新 JSON／Markdown 导出承载相同的 feedback 3 四字段 envelope，context 仍为严格版本 2；先由
`validate` 重读源页面确认，再消费节点／页面／全局整改及显式 REQ、A 引用，不把意见当批准。
节点优先唯一稳定 ID；匿名源元素使用工具派生来源键，不在业务源手写保留属性
`data-prototype-review-source`。业务 REQ 映射须明确写在源元素 `data-req-ids`，无映射时为 `[]`。
动态无来源节点保留输入并提示显式选有来源父层；不得凭局部摘录或静默改绑确认来源。
标记 A 与整改独立编号，不恢复意见等级；旧 feedback 2 仅保留原严格只读消费，不迁移旧草稿。
The design Agent does not edit the PM's source or create a mapping report; this association does not
change the prototype page, dependency fingerprint, or visual-approval contract.

For `standards_only`, return rule differences, their basis, applicability, and existing document
validation results. Distinguish candidates, adopted rules, and completed production migration; do not
add prototype requirements because HTML or browser evidence is absent. Reuse unchanged rules and do
not create extra reports, approval files, or memory records for closeout.
