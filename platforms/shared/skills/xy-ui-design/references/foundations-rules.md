# General Design Foundation Rules

- Domain: design
- Scope: UI prototype design and applicable design constraints for production UI; standards_only adopts or maintains project-specific rules only within the authorized scope. Reading is not mandatory for purely non_ui work. Platform, control, and appearance clauses apply according to actual support.

> Long-lived visual, interaction, platform, token, and accessibility rules. Concrete page behavior
> remains in each approved prototype page contract.

## Maintenance

- PM decides update scope and adoption; UI Agent writes authorized rule changes. Establish or
  replace visual rules from approved decisions, not incidental page styling. Update in place and
  retain unaffected platform/accessibility constraints and stable rule IDs.
- Keep semantic token roles consistent with shared prototype styles and production token mapping.
  Target design adoption is not proof that production migration is complete.

## Project Baseline and Applicability

- `[des-baseline-001] [hard]` Use one adopted visual baseline for the same project, platform, and
  design scope. Reuse existing standards, production tokens, and components first; when establishing
  a baseline for the first time or making an authorized adjustment, propose candidates and adopt them
  through the existing confirmation process. Do not treat this template's defaults, official example
  color values, or visual confirmation of one page as authorization to reskin the entire project.
- `[des-baseline-002] [hard]` Add only the foundation values used by the current task; record their
  applicable platforms/modules, adoption basis, and actual token source paths or identifiers. Existing
  definitions may be referenced precisely without copying the entire theme table. Mark missing values
  as candidates and return them to the PM; do not claim approval. Do not create standards in advance
  for unused components or appearance modes.

## Accessibility

- `[des-accessibility-001] [hard]` Meet WCAG AA unless the platform contract is stricter.
- `[des-accessibility-002] [hard]` Verify applicable keyboard, focus, reduced-motion, contrast,
  Dynamic Type, and assistive-technology behavior.
- `[des-accessibility-003] [hard]` Design Web interfaces to the applicable WCAG 2.2 AA clauses:
  text contrast is at least 4.5:1 for normal text and 3:1 for large text; check necessary control
  boundaries and state indicators for at least 3:1 under the non-text contrast clauses. Follow the
  official definition of large text and exceptions for disabled/decorative content; do not classify
  every thin line or disabled text as a failure. Actionable items have accessible names and visible
  focus and cannot support only hover; native interfaces also follow the target platform's conventions.
- `[des-accessibility-004] [hard]` Select touch targets, spacing, text scaling, and safe areas for
  the target platform and record the basis. Distinguish iOS pt, Android dp, and Web CSS px; do not
  turn one platform's values into universal hard thresholds. Distinguish statically checkable items
  from behavior that has not actually been exercised in the evidence; static success does not establish
  complete accessibility certification.

## Platform constraints

- `[des-platform-001] [hard]` Web prototypes default to a responsive content area and natural
  document flow; iOS/PC prototypes use the project's selected fixed device/window preview. Web uses
  a fixed preview only when viewport comparison is explicitly needed. Top explanations, navigation
  back to the prototype directory, and the bottom page contract belong to the presentation shell;
  product navigation, business messages, and components belong to the product area. Prototype preview
  dimensions do not limit the real product's responsive layout, text scaling, or window resizing.

## Token policy

- `[des-token-001] [hard]` Reuse approved production tokens before introducing new visual values.
- A new semantic token requires a durable product-level reason and accessibility verification.
- `[des-token-002] [hard]` Use semantic tokens for product colors according to purpose; do not
  repeatedly hardcode brand, text, control, or state colors on each page. Base color values may be
  defined centrally in the token source; map native system colors through platform semantic APIs.
  An HTML approximation must not be presented as actual system material or a production implementation.
- `[des-token-003] [hard]` Map the following roles as actually used. Preserve the project's existing
  names without creating synonymous tokens; each used role must resolve to its definition, applicable
  appearance modes, and paired foreground/background.

| Color role | Content to keep consistent |
| --- | --- |
| Brand and primary actions | Primary color and its text/icons; map links and selected states by semantics instead of coloring every emphasis with the primary color |
| Backgrounds and hierarchy | Page background, content surfaces, overlay surfaces, and scrims; define nesting levels and foreground color pairings |
| Text and icons | Primary text, secondary text, subtle hints, inverse content, and disabled content; preserve the same semantics and purpose |
| Boundaries and focus | Dividers, actionable boundaries, and keyboard focus; define decorative dividers separately from necessary interactive boundaries |
| Business feedback | Foregrounds/backgrounds/boundaries for success, warning, error, and information; include supporting text or icons |
| Interaction states | Applicable hover, pressed, selected, focus, and disabled states; selection and focus must remain distinct |

- `[des-token-004] [hard]` Verify actual foreground/background pairings in supported light/dark/
  high-contrast appearances; do not substitute simple color inversion or global opacity for theme
  design. A new visual system replaces only the authorized platforms/modules and related mappings.
  The prototype shell's `--prototype-*` tokens are for presentation and cannot represent a confirmed
  product theme.

## Typography, Scale, and Motion

- `[des-scale-001] [hard]` Share the font stack, heading/body/label hierarchy, font sizes, weights,
  line heights, spacing scale, control sizes, corner radii, borders, shadows/elevation, and icon sizes
  within the current scope. Reuse project tokens or platform defaults instead of defining a separate
  set for each page. Icons retain consistent semantics and style sources; important actions must not
  rely on users guessing from icons alone.
- `[des-motion-001] [hard]` Motion communicates state and spatial relationships, reuses applicable
  durations/curves, and respects reduced-motion; decorative animation must not delay necessary actions.
  Long copy, different languages, and enlarged text must not hide critical content or actions.

## Prohibited patterns

- `[des-prototype-001] [hard]` Do not copy prototype runtime, mock data, contract annotations, or
  debug controls into production.
- `[des-meaning-001] [hard]` Do not use color, motion, or iconography as the only carrier of meaning.

## Official Sources (Consult as Needed)

The following sources informed this workflow's rules and were consulted on 2026-10-13; they do not
require mixing their visual themes. Read the project's adopted rules first, and consult the relevant
official sections only when a related rule is missing, changes, or needs verification. Network access
and full-site reading are not required for every task.

- [Apple HIG: Color](https://developer.apple.com/design/human-interface-guidelines/color): semantic colors, appearance adaptation, and platform conventions.
- [Google Material: Color roles](https://m3.material.io/styles/color/roles): purpose-based color mapping and foreground/background pairings.
- [Microsoft Fluent: Design tokens](https://fluent2.microsoft.design/design-tokens): consistent foundation values such as color, typography, and spacing through tokens.
- [Ant Design: Customize Theme](https://ant.design/docs/react/customize-theme-cn/): the relationship between global themes and component tokens.
- [W3C: Text contrast](https://www.w3.org/WAI/WCAG22/Understanding/contrast-minimum.html) and [non-text contrast](https://www.w3.org/WAI/WCAG22/Understanding/non-text-contrast.html): applicability and exceptions.
