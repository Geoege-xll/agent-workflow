# Design Foundations — {{PROJECT_NAME}}

- Domain: design

> Long-lived visual, interaction, platform, token, and accessibility rules. Concrete page behavior
> remains in each approved prototype page contract.

## Maintenance

- PM decides update scope and adoption; UI Agent writes authorized rule changes. Establish or
  replace visual rules from approved decisions, not incidental page styling. Update in place and
  retain unaffected platform/accessibility constraints and stable rule IDs.
- Keep semantic token roles consistent with shared prototype styles and production token mapping.
  Target design adoption is not proof that production migration is complete.

## Product principles

- Product character and interaction priorities: **TODO**
- Information-density and hierarchy rules: **TODO**
- Existing production patterns to preserve: **TODO**

## 项目基线与适用范围

- `[des-baseline-001] [hard]` 同一项目、平台和设计范围沿用一套已采用的视觉基线。
  先复用已有规范、生产 token 和组件；首次建立或获准调整基线时提出候选，按已有确认流程采用。
  不把本模板的默认规则、官方示例色值或单页视觉确认当作全项目换肤授权。
- `[des-baseline-002] [hard]` 仅补齐当前任务使用的基础值；记录其适用平台／模块、已采用
  依据和真实 token 来源路径或标识。已有定义可精确引用，无需复制整张主题表；缺失值
  标为候选并交 PM 处理，不伪称已批准。不为未使用的组件或外观模式提前创建规范。

## Accessibility

- `[des-accessibility-001] [hard]` Meet WCAG AA unless the platform contract is stricter.
- `[des-accessibility-002] [hard]` Verify applicable keyboard, focus, reduced-motion, contrast,
  Dynamic Type, and assistive-technology behavior.
- `[des-accessibility-003] [hard]` Web 按 WCAG 2.2 AA 的适用条款设计：普通文本对比度至少
  4.5:1，大文本至少 3:1；必要的控件边界和状态标识按非文本对比度条款检查至少 3:1。大文本定义
  与禁用／装饰等例外依官方条款，不能把所有细线或禁用文本一律判为不合格。
  可操作项有可访问名称和可见焦点，不能仅支持 hover；原生端同时遵循目标平台约定。
- `[des-accessibility-004] [hard]` 触控目标、间距、文字缩放与安全区按目标平台选择并记录
  依据，区分 iOS pt、Android dp 和 Web CSS px，不能把某个平台的数值当成通用硬门槛。
  验证证据区分静态可检查项与尚未实际操作的行为，不以静态通过宣称完整无障碍认证。

## Platform constraints

- Supported platforms, viewports, input methods, and appearance modes: **TODO**
- Native platform conventions that must not be replaced: **TODO**
- `[des-platform-001] [hard]` Web 原型默认采用响应式内容区和自然文档流；iOS／PC 原型
  使用项目选定的固定设备／窗口预览。只有明确需要视口对比时，Web 才使用固定预览。
  顶部说明、返回原型目录和页底契约属于展示外壳；产品导航、业务提示和组件属于产品区。
  原型展示尺寸不限制真实产品的响应式、文字放大或窗口缩放能力。

## Token policy

- `[des-token-001] [hard]` Reuse approved production tokens before introducing new visual values.
- A new semantic token requires a durable product-level reason and accessibility verification.
- `[des-token-002] [hard]` 产品颜色按用途使用语义 token，不在每个页面重复硬编码品牌色、
  文本色、控件色或状态色。基础色值允许集中定义于 token 源；原生系统色通过平台语义 API
  映射，HTML 中的近似模拟不能冒充真实系统材质或生产实现。
- `[des-token-003] [hard]` 下列角色按实际使用建立映射。沿用项目现有命名即可，不要求
  再建同义 token；每个已用角色可定位到定义、适用外观模式及配对前景／背景。

| 颜色角色 | 需要统一的内容 |
| --- | --- |
| 品牌与主操作 | 主色、主色上的文字／图标；链接与选中态按语义映射，不把所有强调都涂成主色 |
| 背景与层级 | 页面背景、内容表面、浮层表面、遮罩；明确嵌套层级与前景色配对 |
| 文字与图标 | 主文本、次文本、弱提示、反色内容、禁用内容；同语义同用途 |
| 边界与焦点 | 分隔线、可操作边界、键盘焦点；装饰分隔与必要交互边界分别定义 |
| 业务反馈 | 成功、警告、错误、信息的前景／背景／边界；有文字或图标辅助说明 |
| 交互状态 | 适用的 hover、pressed、selected、focus、disabled；选中与焦点不得混为一态 |

- `[des-token-004] [hard]` 在支持的浅色／深色／高对比外观中验证实际前景与背景配对，
  不用简单反色或全局透明度替代主题设计。全新视觉只替换获准的平台／模块及相关映射。
  原型外壳的 `--prototype-*` 是展示用 token，不能充当产品已经确认的主题。

## 排版、尺度与动效

- `[des-scale-001] [hard]` 当前范围共享字体栈、标题／正文／标签层级、字号、字重、行高、
  间距阶梯、控件尺寸、圆角、边框、阴影／层级和图标尺寸。复用项目 token 或平台默认值，
  不逐页另设一套；图标保持同一语义与风格来源，重要操作不能仅靠图标猜测。
- `[des-motion-001] [hard]` 动效表达状态和空间关系，复用适用时长／曲线并尊重 reduced-motion；
  不因装饰动画延迟必要操作。长文案、不同语言和文字放大不得隐藏关键内容或操作。

## Prohibited patterns

- `[des-prototype-001] [hard]` Do not copy prototype runtime, mock data, contract annotations, or
  debug controls into production.
- `[des-meaning-001] [hard]` Do not use color, motion, or iconography as the only carrier of meaning.

## 官方依据（按需查阅）

以下是本工作流归纳规则的依据，查阅于 2026-10-13；不是要求混用各家视觉主题。
优先读本项目已采用的规则，只在相关规则缺失、变更或需要核实时查对应官方章节，
不要求每次任务联网或全文读取这些站点。

- [Apple HIG：Color](https://developer.apple.com/design/human-interface-guidelines/color)：语义色、外观适配与平台约定。
- [Google Material：Color roles](https://m3.material.io/styles/color/roles)：按用途映射颜色及前景／背景配对。
- [Microsoft Fluent：Design tokens](https://fluent2.microsoft.design/design-tokens)：以 token 统一颜色、排版、间距等基础值。
- [Ant Design：定制主题](https://ant.design/docs/react/customize-theme-cn/)：全局主题与组件 token 的关系。
- [W3C：文字对比度](https://www.w3.org/WAI/WCAG22/Understanding/contrast-minimum.html)与[非文本对比度](https://www.w3.org/WAI/WCAG22/Understanding/non-text-contrast.html)：适用对象与例外。
