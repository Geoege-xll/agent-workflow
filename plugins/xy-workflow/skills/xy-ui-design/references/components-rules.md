# General Component and Interaction Rules

- Domain: design
- Scope: UI prototype design and applicable design constraints for production UI; standards_only adopts or maintains project-specific rules only within the authorized scope. Reading is not mandatory for purely non_ui work. Platform, control, and appearance clauses apply according to actual support.

> Record durable component composition and interaction rules here; page-specific states stay in the
> concrete prototype page contract.

## Maintenance

- UI Agent maintains approved reusable composition/state rules; PM reviews scope and adoption.
  New visual systems replace only the applicable old rules. Do not promote page-local exceptions
  to global hard rules or relax a rule merely to pass an implementation audit.
- Implementers own production components; normative text and prototype runtime are not production
  component code. Unchanged reusable rules require no documentation update.

## Reuse and composition

- `[des-component-001] [hard]` Reuse an approved production component when it already satisfies the
  required behavior and accessibility contract.
- `[des-component-002] [hard]` Controls with the same semantics reuse the same component and
  applicable variants. First determine whether a difference is a state, size, or platform variant;
  explain the reason and scope only when a new variant is actually needed. Do not secretly create
  a second set of foundation controls with page-specific CSS. Prototypes reuse shared styles and
  behavior conventions; production reuses project components without copying prototype runtime code.
- `[des-component-003] [hard]` For components actually used in the current scope, make their
  names/sources, purposes, allowed variants, token mappings, sizes/spacing/radii, states,
  keyboard/touch behavior, and applicability locatable. Reference existing component-library defaults
  by component and version and record only project differences; do not write a separate document for
  each property or build a complete component library.

## Dialogs and Overlays

- `[des-dialog-001] [hard]` Distinguish informational dialogs, confirmations, form dialogs,
  non-modal utility windows, and Popover/Toast. Use a modal only when the current task needs focus
  or a user decision; ordinary success feedback does not default to a confirmation dialog. Do not
  replace a clear flow with a succession of nested dialogs. Choose according to task semantics and
  the project's adopted platform rules.
- `[des-dialog-002] [hard]` Keep width variants, maximum available height, padding,
  title/content/action areas, button hierarchy, scrims, and content scrolling consistent within the
  same dialog category. Keep action order consistent with the target platform; explain consequences
  for dangerous actions and give buttons explicit action names. Exits and necessary actions remain
  reachable on narrow screens and with long content.
- `[des-dialog-003] [hard]` Define opening, confirmation, cancellation, closing, Esc/back-key
  handling, scrim clicks, and unsaved-content handling for each dialog type. Ordinary Web modals
  support cancellation and closing with Esc; if a target platform's special alert has a different
  dismissal convention, explain the basis and retain an available safe exit. Cancellation or closing
  must not implicitly submit or execute dangerous actions.
- `[des-dialog-004] [hard]` When a modal opens, move focus to an appropriate location, make the
  background inoperable, and keep Tab focus inside the modal; after closing, return focus to the
  trigger or a reasonable subsequent location. Non-modal interfaces need not trap focus. Prefer
  correct platform/component-library semantics and native elements on Web; custom appearance must
  retain names, semantics, and keyboard behavior.

## Segmented Controls and Tabs

- `[des-segment-001] [hard]` First determine whether a segmented control selects one value,
  filters with multiple selections, or switches content panels. Do not infer semantics from a pill
  appearance: on Web, mutually exclusive options use radio semantics, multiple selections use
  checkbox or toggle button semantics, associated content panels use Tabs semantics, and actual page
  navigation uses links. Native interfaces follow the corresponding platform control behavior.
- `[des-segment-002] [hard]` Keep height, padding, radii, label style, selection indicators, and
  disabled states consistent for the same control category. Labels in a group use consistent
  phrasing; determine width policy and handling of too many items or long labels from project rules.
  Do not turn one platform's recommended segment count into a hard limit for all platforms or silently
  truncate options until they are unrecognizable.
- `[des-segment-003] [hard]` Define the initial selection, whether empty selection is allowed,
  switching effects, retained data, and corresponding keyboard behavior. Express the selected value
  and keyboard focus separately; Tabs associate panels and selected state and support arrow and
  activation keys according to the pattern. Use automatic activation only when the panel can appear
  immediately; otherwise use manual activation and provide loading feedback.

## Other Common Controls (Apply When Actually Used)

- `[des-control-001] [hard]` Keep primary/secondary/text/danger button variants and sizes
  consistent, expressing actions and hierarchy clearly; icon buttons have accessible names. Handle
  repeated activation during submission according to task behavior; color changes alone or false
  success are insufficient.
- `[des-form-001] [hard]` Keep labels, required/optional indicators, help text, disabled/read-only
  treatment, and error styles consistent across input, selection, and validation. Placeholders cannot
  replace labels; errors identify the field and how to fix it, and failures preserve user input.
- `[des-data-001] [hard]` Keep density, headers, row actions, selection, and sorting/filtering
  feedback consistent in lists/tables. Distinguish an empty list, no search results, permission
  restrictions, and loading failures by their actual causes instead of representing all with one blank page.

## States and feedback

- `[des-state-001] [hard]` Every user-triggered asynchronous action exposes a perceivable progress,
  success, or failure state appropriate to the platform.
- `[des-state-002] [hard]` Check applicable default, hover, focus, pressed, selected, disabled,
  loading, success, and error states and transitions for actual controls. When a prototype exists,
  record recovery paths for page-level loading/empty/error/partial-data states in the existing page
  contract; direct development follows the current task's requirements and acceptance without adding
  a prototype. Explain inapplicable items; do not require every control to implement every state.

## Responsive and adaptive behavior

- `[des-responsive-001] [hard]` Preserve essential actions and information across every supported
  viewport or platform size class.
- `[des-responsive-002] [hard]` Web uses the project's responsive rules, adapting navigation,
  forms, and action areas to available space; tables/canvases that truly require two-dimensional
  browsing may scroll locally while remaining reachable. Do not force fixed window heights or nested
  scrolling on ordinary webpages; native clients follow their own window and safe-area conventions.

## Self-Review and Handoff

- `[des-evidence-001] [hard]` Follow the current task's handoff and review: explain which
  applicable rules/components were reused, what was added or changed, exceptions, and unverified
  items, with relevant paths/IDs. Identify affected pages when shared styles change; do not reread all
  prototypes, create accompanying audit documents, or trigger additional prototype browser automation
  or confirmation because of these rules. Static prototype verification does not establish verified
  focus, responsive rendering, or actual assistive-technology behavior; report honestly when these
  were not exercised. Production implementation continues to use the current task's risks and
  existing QA route; these rules do not limit applicable browser testing of the real product or
  upgrade Light or direct-development tasks back to a complete prototype process.

## Official Sources (Consult as Needed)

Consulted on 2026-10-13. The above are defaults adapted to this workflow; specific values and
platform variants follow the project's adopted rules. These sources do not require the project to
install the corresponding component libraries or switch to Figma.

- [Apple HIG: Segmented controls](https://developer.apple.com/design/human-interface-guidelines/segmented-controls): consistency in segmented content and layout.
- [Microsoft Fluent: Dialog](https://fluent2.microsoft.design/components/web/react/core/dialog/usage): overlay purposes, structure, and interaction.
- [W3C APG: Modal dialog](https://www.w3.org/WAI/ARIA/apg/patterns/dialog-modal/) and [Tabs](https://www.w3.org/WAI/ARIA/apg/patterns/tabs/): Web semantics and keyboard/focus patterns.
- [Ant Design: Customize Theme](https://ant.design/docs/react/customize-theme-cn/): reusable variants maintained through component tokens.
