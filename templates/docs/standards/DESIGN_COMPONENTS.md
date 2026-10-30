# Component and Interaction Standards — {{PROJECT_NAME}}

- Domain: design

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
- Component variants and extension rules: **TODO**
- `[des-component-002] [hard]` 同语义控件复用相同组件及适用变体。出现差异先判断是状态、
  尺寸或平台变体；确需新增才说明原因和范围，不能用页面专属 CSS 暗建第二套基础控件。
  原型复用共享样式与行为约定；生产端复用项目组件，不复制原型运行时代码。
- `[des-component-003] [hard]` 当前实际使用的组件需能定位到名称／来源、用途、允许变体、
  token 映射、尺寸／间距／圆角、状态、键盘／触控行为及适用范围。已有组件库默认规则
  可按组件和版本引用，只记录项目差异；不要为每项属性另写一份文档或搭建完整组件库。

## 弹窗与浮层

- `[des-dialog-001] [hard]` 区分提示、确认、表单弹窗、非模态辅助窗口和 Popover／Toast。
  需要聚焦当前任务或让用户决策才使用模态；普通成功反馈不默认弹确认框，不以连续嵌套弹窗
  代替清晰流程。具体选择服从任务语义和项目已采用的平台规则。
- `[des-dialog-002] [hard]` 同类弹窗统一宽度变体、最大可用高度、内边距、标题／内容／
  操作区、按钮层级、遮罩及内容滚动方式。动作顺序按目标平台统一；危险动作说明后果，
  按钮使用明确动作名称。窄屏／长内容仍保留可达的退出和必要操作。
- `[des-dialog-003] [hard]` 为每种弹窗定义打开、确认、取消、关闭、Esc／返回键、点遮罩
  和未保存内容的处理。普通 Web 模态支持 Esc 取消关闭；目标平台的特殊警示若有不同
  关闭约定，明确说明依据并保留可用的安全退出。取消或关闭不能隐式提交／执行危险动作。
- `[des-dialog-004] [hard]` 模态打开时把焦点移入适当位置，背景不可操作，Tab 焦点留在
  模态内；关闭后回到触发项或合理的后续位置。非模态不强制困住焦点。优先使用平台／
  组件库的正确语义，Web 优先原生元素；自定义外观仍须保留名称、语义和键盘行为。

## 分段控件与 Tabs

- `[des-segment-001] [hard]` 先明确分段控件是在选择一个值、多选过滤，还是切换内容面板。
  不凭胶囊外观决定语义：Web 互斥选项使用 radio 语义，多选使用 checkbox 或 toggle button
  语义，关联内容面板使用 Tabs 语义；实际页面跳转使用链接。原生端按相应平台控件行为。
- `[des-segment-002] [hard]` 同类控件统一高度、内边距、圆角、标签风格、选中指示和禁用态。
  同一组标签保持一致的表达方式；宽度策略、项目过多和长标签的处理按项目规则确定，
  不把某平台推荐的段数当成全平台硬限制，也不静默截断到无法辨认选项。
- `[des-segment-003] [hard]` 定义初始选中项、是否允许空选、切换影响、保留的数据和
  对应键盘行为。选择值与键盘焦点分别表达；Tabs 关联面板及选中状态，按模式支持方向键
  与激活键。仅在面板可即时显示时自动激活，否则使用手动激活并提供加载反馈。

## 其他常用控件（实际使用时适用）

- `[des-control-001] [hard]` 按钮统一主／次／文本／危险变体及尺寸，清楚表达动作和层级；
  图标按钮有可访问名称。提交中的重复触发按任务行为处理，不能只有颜色变化或假成功。
- `[des-form-001] [hard]` 输入、选择和校验统一标签、必填／可选、帮助文案、禁用／只读
  以及错误样式。占位符不能替代标签；错误指出字段和修复方式，失败时保留用户已输入内容。
- `[des-data-001] [hard]` 列表／表格统一密度、表头、行操作、选中和排序／过滤反馈；
  空列表、无搜索结果、权限限制和加载失败按真实原因区分，不用一个空白页表示全部情况。

## States and feedback

- Required loading, empty, error, disabled, success, and partial-data patterns: **TODO**
- `[des-state-001] [hard]` Every user-triggered asynchronous action exposes a perceivable progress,
  success, or failure state appropriate to the platform.
- `[des-state-002] [hard]` 对实际控件检查适用的 default、hover、focus、pressed、selected、
  disabled、loading、success、error 状态及转换。页面级加载／空／异常／部分数据的恢复
  路径在有原型时写入现有页面契约；直接开发沿用当前任务需求与验收，不补建原型。
  不适用项注明原因，不强制每个控件实现全部状态。

## Responsive and adaptive behavior

- Breakpoints, size classes, window constraints, and content-priority rules: **TODO**
- `[des-responsive-001] [hard]` Preserve essential actions and information across every supported
  viewport or platform size class.
- `[des-responsive-002] [hard]` Web 使用项目约定的响应式规则，导航、表单和操作区按空间
  调整；确需二维浏览的表格／画布可局部滚动并保持可达。不为普通网页强制固定窗口高度
  或多层滚动；原生客户端遵循自身窗口和安全区约定。

## 自查与交接

- `[des-evidence-001] [hard]` 沿用当前任务的交接和审查：说明复用了哪些适用规则／组件、
  新增或变更了什么、例外及未验证项，并提供相关路径／ID。共享样式变化指出影响页面，
  不重复读取全部原型、不新建配套审计文档、不因这些规则额外触发原型浏览器自动化或确认。
  静态原型验证不等于已验证焦点、响应式渲染和真实辅助技术行为；如未执行须如实说明。
  生产实现仍按当前任务的风险和既有 QA 路由验证；这里不限制真实产品适用的浏览器测试，
  也不把 Trivial 或直接开发任务重新升级为完整原型流程。

## 官方依据（按需查阅）

查阅于 2026-10-13。上述为适配本工作流的默认要求，具体数值和平台变体以项目采用的
规则为准；这些资料不意味着项目必须安装对应组件库或改用 Figma。

- [Apple HIG：Segmented controls](https://developer.apple.com/design/human-interface-guidelines/segmented-controls)：分段内容与布局一致性。
- [Microsoft Fluent：Dialog](https://fluent2.microsoft.design/components/web/react/core/dialog/usage)：浮层用途、结构与交互。
- [W3C APG：Modal dialog](https://www.w3.org/WAI/ARIA/apg/patterns/dialog-modal/)及[Tabs](https://www.w3.org/WAI/ARIA/apg/patterns/tabs/)：Web 语义和键盘／焦点模式。
- [Ant Design：定制主题](https://ant.design/docs/react/customize-theme-cn/)：以组件 token 维护复用变体。
