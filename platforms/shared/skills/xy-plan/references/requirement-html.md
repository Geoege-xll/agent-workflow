# 需求 Markdown 与 HTML 交付

模型和 PM 只维护一份需求 Markdown；HTML 是固定版本 `answer-me-with-html` CLI 的离线投影。
正式文件放在适配器 `docs.plans` 下，使用同名 `.md` + `.html`。同稿的已验收版本与“验收结果与当前已交付行为”
保留当前功能基线，PROJECT 只索引明确已验收主题，设计原型仍在配置 `docs.standards_root/prototype/`。
不要增加需求副本、映射报告、模板 HTML、空目录或批量转换历史计划。

Full 正式需求审阅交付 HTML。`xy-plan` 只返回草案，不写文件、派发或请求批准；PM 可在
批准前把当前草案写入本请求 scratch 并渲染，批准后才保存正式 Markdown 并生成同名 HTML。
Light 按复杂度、恢复需要或用户要求选用，渲染本身不增加 Full 计划、DAG、QA 或确认阶段。
页面存在、勾选、复制原稿和 `check` 成功都不产生需求/原型选择/视觉批准。

## 调用同一适配器

安装态从项目根执行；源包开发把 `.agent-workflow/` 前缀去掉。配置优先使用目标项目的
`.agent-workflow/project.yaml`，没有安装态配置时使用该项目 `project.yaml`。

```bash
bash .agent-workflow/lib/python_runtime.sh -X utf8 .agent-workflow/lib/requirement_html.py render --project . --source docs/plans/change.md --request-id current-request
bash .agent-workflow/lib/python_runtime.sh -X utf8 .agent-workflow/lib/requirement_html.py check --project . --source docs/plans/change.md
```

`--source` 必须按真实 `docs.plans` 替换，不能把示例默认路径当作配置。没有任意 `-o`；
输出永远是原稿同目录、同名 `.html`。正式原稿须为 plans 下规范相对路径的单链接普通
`.md` 文件，拒绝符号链接、硬链接、危险祖先与路径逃逸。原稿不交给上游 CLI；只有
scratch 内的舞台副本可被上游读取/清理，原稿字节、权限和节点身份保持不变。

Windows 使用项目内持久 Python 入口，参数相同：

```powershell
node .agent-workflow/lib/python_runtime.cjs -X utf8 .agent-workflow/lib/requirement_html.py render --project . --source docs/plans/change.md --request-id current-request
```

运行时需要现有 Node.js >= 20（Windows 安装路线已有 Node 22），不安装全局依赖、不在
每次 setup 启动渲染器。Node 缺失/过旧只阻塞本次需要的渲染；已有 fresh 页及只读检查
无需启动 Node。Brew Formula 声明 Node 依赖，原 Python 选择/显式解释器规则仍适用。

## 批准前草案

PM 用既有 `task_graph_cli.py scratch --root <project> --request-id <id>` 获取唯一请求
scratch，把草案写到其中已授权的位置，再执行：

```bash
bash .agent-workflow/lib/python_runtime.sh -X utf8 .agent-workflow/lib/requirement_html.py render --project . --source /absolute/current-request-scratch/change.md --request-id current-request --draft
bash .agent-workflow/lib/python_runtime.sh -X utf8 .agent-workflow/lib/requirement_html.py check --project . --source /absolute/current-request-scratch/change.md --request-id current-request --draft
```

草案输出仍在同一 scratch；不能提前写正式 plans。草案中的项目相对链接统一按未来
`docs.plans/<草案文件名>.md` 解释；批准后原字节保存到这个位置，链接继续有效。适配器
只在给 CLI 的舞台副本重定位这些已检查链接，使 scratch HTML 也可跳转；不会回写原稿。
不要用跨盘绝对路径、原始 HTML、引用式链接或含空白/括号的含混路径绕过此基准；不支持
的语法会定位行号拒绝。纯进度、链接或呈现变化只需重渲染，是否重开需求批准取决于
既有实际语义变化规则，不能拿 HTML 字节指纹替代 `requirements_fingerprint`。

## 原型关联与受控 Markdown

以稳定 REQ 编号和普通链接表达需求覆盖；具体原型页及其实际 `id` 状态锚点由设计 Agent
在原有交接返回，PM 写回同一稿件再渲染。例如 plans 与 standards 采用默认配置时：

```markdown
| 需求 | 验收 | 原型覆盖 |
|---|---|---|
| REQ-001 | 错误状态可恢复 | [编辑页错误状态](../standards/prototype/editor.html#error-state) |
```

检查只读取本稿实际引用的本地 Markdown/具体原型 HTML 及其锚点，拒绝缺失、越出项目、
链接节点、目录索引代替具体页和原型目录外 HTML；不扫描完整原型树、不放宽原型向目录外
导航、不修改原型模板或指纹。原型依赖指纹、视觉批准和生产实现 QA 保持原职责；不新增
独立原型 QA。派发给实施者的是完整当前 Markdown/适用任务包，不要求预载整份 HTML。

支持普通段落、标题、列表、表格、普通 `[文字](目标)` 链接、行内代码和顶格三个反引号
代码围栏；流程/时序使用上游 `flow` / `sequence` 围栏语法。代码围栏可展示常用语言文字。
拒绝 frontmatter、图片嵌入、`src=` 文件导入、原始 HTML/SVG 与引用式链接；外部 http(s)/
mailto 链接只导航，不嵌入内容。固定调用仅 `render`，关闭自动打开和更新检查，使用私有
AM_HOME；不启动浏览器、模型、视频或服务，也不读取项目外文件嵌入页面。
输入安全检查采用保守子集：图片标记和类似 HTML 标签的起始串在整稿中一律拒绝，包含
转义写法、跨行标签、行内代码和代码围栏中的示例；需要说明这些语法时用普通文字或
`&lt;` 等实体表示。普通链接示例也按原始文字检查项目路径，不凭反引号外观跳过约束。

## 新鲜度、失败与历史边界

HTML 内的版本记录绑定规范原稿路径、原稿字节 SHA、固定引擎/适配器身份及生成 HTML 摘要。
`check` 是只读的新鲜度/当前引用检查；原稿变动后失败，`render` 在原路径更新，完全相同
输入及渲染器的 fresh 输出直接复用。被手改、没有本工具记录或不属于此原稿的旧 HTML
一律保留并报错，须由所有者明确处置，不能盲目覆盖。

渲染在当前 request-id 的固定 scratch 舞台完成，成功后复用现有条件原子发布入口；错误、
超时或检测到生成期间原稿/目标并发修改都保留正式原件。与既有发布入口一样，协作目录锁
不承诺阻止外部编辑器在最后检查和替换之间的非协作写入，也不宣称断电事务持久性。
同稿分开记录执行与已验收基线；取消本次目标不撤销旧基线，completed 不产生验收。
未索引旧执行稿及派生 HTML 保持历史边界，不能成为第二份规范或自动恢复执行依据。

生成页主品牌与项目 GitHub 指向 `https://github.com/Geoege-xll/agent-workflow`；固定渲染器来源仍在页脚明确标出。
品牌适配属于 renderer 身份与 HTML 完整性；不修改上游 bundle、许可或来源文件。
