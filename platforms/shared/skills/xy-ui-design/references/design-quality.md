# Design Quality and Completion Criteria

This guidance supports design judgment and refinement; it does not replace current requirements,
project design standards, or the prototype-verification contract. Interpret satisfaction with a
reference project only within the scope explicitly evaluated by the user. This Skill distills methods
for applying standards, keeping components consistent, and delivering high fidelity; it does not infer
a preference for warm colors, soft textures, or any aesthetic, or establish that all interactions and
data semantics are correct. Each project's approved standards determine colors, materials, styles,
and dimensions; business and mental models also remain project-specific.

## Establish the Current Baseline and Main Task First

- First read applicable rules from the built-in `foundations-rules.md` and `components-rules.md`;
  when a project index exists, follow its links to current project-specific foundation values,
  components, and platform differences. Inspect only relevant tokens, pages, and dependencies.
  Official guidance and canonical Taste are references and cannot override approved requirements,
  project standards, compact application layouts or the existing static prototype-verification boundary.
- Determine target users, use contexts, main tasks, content density, platform/module, existing
  baseline, color and scale token sources, reusable components, and allowed variants. If a baseline
  is missing, propose only the candidate values needed by this task and adopt them through the existing
  confirmation process; template defaults and search results are not approved project facts.
- Web、桌面、原生 App 和小程序按受影响的运行端核对跨页面一致性。先找到项目已批准的规则，再追到实际使用的
  语义设计变量（token）与组件变体。有同类消费者时，选至少一个相关页面进行对照，比较同一语义的组件来源、
  变量映射和适用状态。以 [组件规则](components-rules.md) 判断差异，已有页面的用法可提供实现证据，采用频率
  不能作为批准依据。
- Organize content and action priorities first: make the main task discoverable, critical information
  scannable, and secondary explanations expandable as needed. Refine the structure with representative
  copy and data lengths close to actual tasks, rather than filling content gaps with repeated
  placeholder cards or decoration. Demo data must not pretend to be actual business results; design
  needs do not authorize new features, metrics, or promises.
- Early in the existing UI route, use wireframes to compare IA, flows, and information relationships;
  once direction is established, continue refinement to high-fidelity pages. Gray boxes, text
  wireframes, and static images are not completed interactive prototypes; add no planning/approval stage.

## Make Visual Details Serve Content

- Apply the project's type scale to headings, body text, supporting information, and numbers,
  establishing clear hierarchy through copy length, line height, weight, alignment, and content width.
  Express relationships through consistent spacing rhythm and grouping; do not give every piece of
  content an equally weighted card.
- Use colors by semantics and foreground/background pairing; typography, spacing, radii, elevation,
  icons, and applicable appearances share existing scales. The product area uses project product
  tokens without hardcoding a second set of foundation values per page; `--prototype-*` serves only
  the presentation shell.
- Handle borders, shadows, materials, and graphics within the project's allowed direction, controlling
  hierarchy, density, and decoration. Refinement does not prescribe gradients, glass, large radii, or
  extensive whitespace; the native platform, brand, and content needs determine these choices.
- Preserve the project's icon and visual-asset system, keeping semantics, strokes/sizes, and alignment
  consistent; decoration does not replace action text or states. Without explicit authorization, do
  not generate image assets or introduce remote fonts, CDNs, or package dependencies to pursue a style.

## Components, States, and Platform Applicability

- Reuse components actually used by the project, such as buttons, forms, dialogs, segmented controls,
  and Tabs, with consistent variants, sizes, states, and behavior. Preserve the same semantics on the
  same platform; native platform behavior need not be mechanically identical.
- Show necessary initial, selected, loading, empty, error, disabled, and success states according to
  current requirements; do not mechanically require every page to include every category. Critical
  actions provide clear feedback and an understandable next step; failure, cancellation, and
  incompletion must not appear successful. Update demonstrable interactions together with the in-page
  contract; drawing controls that merely look operable is insufficient.
- 按当前需求走查关键流程遇到中断之后如何继续。按实际入口核对返回、取消、失败恢复、重试与完成反馈，
  让用户知道发生了什么、保留了哪些进度、下一步可做什么。依据已批准的产品语义决定返回时恢复的输入、
  筛选、滚动位置或当前步骤，以及取消或完成时清理的临时状态。结合实际失败原因提供可执行的下一步，
  例如就地修正校验错误，或在提交结果未明时先查结果。反馈的内容和形式跟随当前任务及运行端。
- 已有原型时，把走查结果填入原五段契约。沿用 `purpose` 记录主任务及运行端，`navigation` 记录返回目标
  与恢复的上下文，`interactions` 记录取消、重试和完成后的操作，`states` 记录失败、恢复、取消、完成等
  适用状态的可见结果，`exceptions` 记录有依据的平台差异与必要的模拟限制。只覆盖当前需求和已有原型范围。
- Clarify navigation destinations, back behavior, dialog exits and focus, form validation, and
  segmented-selection/panel-switching semantics. Handle touch, keyboard, accessible names, visible
  focus, foreground/background contrast, and states that do not rely solely on color for the target
  platform. Return designs that exceed existing authority, are ambiguous, or need broader scope to
  the PM; do not decide business rules independently.
- Use actual content lengths to account for narrow spaces, long text, multiple languages, and enlarged
  text; avoid unexplained truncation of critical copy. Responsive pages and fixed prototype artboards
  each follow their canvas rules; a fixed preview does not limit real product adaptation.
- Use motion to explain change and feedback; timing and amplitude follow platform, component,
  performance, and reduced-motion preferences. Do not force one duration, spring curve, skeleton
  screen, or staggered animation onto all tasks.

## Completion Judgment and Standards Maintenance

- At prototype completion, the product area should show high-fidelity content, typography, component
  details, and necessary states consistent with the project baseline, forming a directly demonstrable
  main flow within the declared platforms and layout scope. Presentation explanations, simulation
  limits, and the in-page contract remain outside the product area. Distinguish appearance,
  interaction/contract, and standards conformance: success in one does not establish the others.
- Pages share a baseline, and shared CSS/standards have an explicit single Writer. Reuse compatible
  existing patterns and fill only real gaps in the current scope; do not redesign unrelated pages
  or overwrite existing shared styles along the way.
- After initial confirmation, incremental rule changes, or approval of a new visual system, maintain
  authorized leaves and shared styles under `xy-workflow/references/design-standards.md`; do not
  update documents without new rules. Page exceptions remain in the existing contract and general
  rules in built-in sources; project leaves record only actual project-specific differences. Do not
  copy general text or create a second design system, component showcase page, or report.
- `standards_only` changes only currently authorized rules, preserves stable IDs, unchanged constraints,
  and platform applicability, and explains the basis and differences. Keep candidates, adopted rules,
  and completed production migration distinct. Approval of one page does not establish project-wide
  adoption or prove production migration.
- Briefly state rules/components used, actual changes, shared impact, and unverified items in the
  existing handoff. Reuse existing static verification; the PM checks the five-section contract against
  approved requirements, and QA reviews standards within the current scope. Add no screenshots,
  automated browser operations, confirmation stages, or full regression runs. The PM continues to
  handle visual confirmation according to the user's selected prototype branch.

## Three-Dimensional Prototype Self-Check

The design Agent self-checks before the existing prototype handoff without adding independent
prototype QA; the user gives final confirmation through concrete pages.

- Requirement coverage: Map approved scope and acceptance to page navigation, operations, states,
  validation, and the five-section contract; check omissions, unauthorized additions, and conflicts.
  Self-checking does not restore unrelated or waived prototype work.
- Standards conformance: Check applicable IDs, components/tokens, platforms, and accessibility against
  current built-in rules and project-specific standards, explaining exceptions and parts not actually
  exercised. User satisfaction or static success does not establish complete conformance.
- Delivery consistency: Check consistency among concrete HTML, contracts, stable controls, relative
  navigation, declared results, and shared styles. Confirm that current page and dependency
  fingerprints match the handoff scope; high-fidelity content and necessary states cannot remain
  merely in wireframes.

Briefly record the three dimensions and evidence in the existing `prototype_verify.static_checks`,
put issues in `blocking_findings`, and state the conclusion through the existing `result`. Return gaps
to the same design Agent and recheck only affected parts after correction; create no reports, approval
files, new states, or default browser/screenshot steps. The PM checks the current handoff and approval
basis without repeating valid static checks; unified functional QA after production implementation
continues through the original route.

## Reference Sources and Processes Not Adopted

This independently authored guidance does not copy external Skill bodies or databases.
Sources support checks as needed; network access is not required for every task.

- Anthropic [frontend-design](https://raw.githubusercontent.com/anthropics/skills/main/skills/frontend-design/SKILL.md),
  with the directory's [Apache-2.0 license](https://raw.githubusercontent.com/anthropics/skills/main/skills/frontend-design/LICENSE.txt).
  It informs visual intent around a real subject, content-driven typography, and restrained
  self-review; its screenshot self-review and any additional confirmation process are not adopted.
- Leonxlnx [Taste](https://github.com/Leonxlnx/taste-skill), fixed by the bundled selected-skills lock.
  The complete original and its MIT LICENSE plus asset-specific credits stay in the canonical vendor
  directory. Use the no-hooks adapter and fully read the original under xy-ui-design's contract;
  do not register Stop hooks or execute its screenshot/gate pipeline during default prototype work.
  Its marketing patterns are conditional advice, not a required layout for compact product consoles.
- 跨页面一致性参考 wg-skills 的取证方法，用项目基线解释同语义组件之间的差异。固定提交附 Apache-2.0 许可。
  [frontend-style-harmonizer](https://github.com/jiushiwon/wg-skills/blob/ff6680f4a722a057e00c54a2abde6d574f582bd7/frontend/frontend-style-harmonizer-skill/SKILL.md) · [许可证](https://github.com/jiushiwon/wg-skills/blob/ff6680f4a722a057e00c54a2abde6d574f582bd7/LICENSE)
- 流程反馈参考 mobile-app-ui-design 按任务阶段给出状态和后续动作的思路。固定提交的 README 标注 MIT，
  该提交缺少独立许可文件，仅参考理念。[Smart Patterns](https://github.com/ceorkm/mobile-app-ui-design/blob/0ad61f025fc647417d4b8fb0ca786cb493c5156a/SKILL.md#smart-patterns-to-apply)

If substantive source code or text is copied in the future, first preserve the required notices and
license materials under the applicable license; these references grant no additional rights to use
assets, brands, or data.
