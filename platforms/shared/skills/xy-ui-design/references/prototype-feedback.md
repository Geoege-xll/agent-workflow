# 原型反馈修订消费合同

仅在当前任务使用评审整改时读取。本合同补充 `prototype-canvas.md` 的展示外壳与 `xy-prototype-verify` 的静态证据，不使其他 Worker 默认预读反馈格式。需求与方案仍以同一主题 Markdown 为唯一编辑权威，具体稳定 HTML 是视觉评审对象。

## 准备和交还

使用当前安装版本的物理插件根，先从 `resource` 解析模板，不从 cwd 猜测缓存或使用项目同名诱饵。新页面按原授权消费模板；不批量覆盖现有业务原型。所有 helper 通过包内解释器选择器和白名单入口调用，项目使用任务已选的同一 adapter：

```text
bash <physical-plugin-root>/lib/python_runtime.sh -B -X utf8 <physical-plugin-root>/plugins/source_pack.py resource templates/prototype/page.html
bash <physical-plugin-root>/lib/python_runtime.sh -B -X utf8 <physical-plugin-root>/plugins/source_pack.py helper --project <physical-project-root> lib/documents/prototype_feedback_cli.py prepare --root <physical-project-root> --adapter <selected-project-adapter> --plan <project-relative-Markdown> --request-id <request-id> --pages <project-relative-HTML>
bash <physical-plugin-root>/lib/python_runtime.sh -B -X utf8 <physical-plugin-root>/plugins/source_pack.py helper --project <physical-project-root> lib/documents/prototype_feedback_cli.py validate --root <physical-project-root> --adapter <selected-project-adapter> --input <explicit-feedback-file>
```

`prepare` 只读项目，成功向 stdout 返回 `status: ready`、`context`、`review_url`、`bundle_path` 和 `reused`。新项目用 `--pages` 明确列出本轮实际 HTML；省略时消费既有登记。工具从当前物理插件装配用户级私有、不可变的离线包，只复制明确页面的必要渲染依赖和需求导航文档，不复制整个项目。默认数据根为 macOS `~/Library/Application Support/agent-workflow/prototype-reviews`，其他 POSIX 使用绝对 `XDG_DATA_HOME` 或 `~/.local/share` 下的 `agent-workflow/prototype-reviews`；隔离验证可显式传 `--data-dir <项目外绝对实际目录>`，prepare 与 validate 使用同一目录。

用户通过该包的 `index.html#page=<文件名>` 进入评审，无需输入 SHA；启动 context 来自包内安全转义的 JSON，链接不承载 base64 review。导航保留既有 index 的文本和 details/summary 分组，但不执行旧 index。通用查看器、反馈和通信代码只在插件与派生包持有，项目源不增加工具壳；新快照使用 manifest 3、boot 3 和幂等 `prototype-review:* version:3` 桥，忽略旧 `prototype-workspace:* version:1`。

工作台固定设计视口，以相机缩放／移动查看而不重排页面；浮动控件、默认收起的导航抽屉、“整改／标记”两个 Tab 和独立开发说明大对话框属于工具。浏览模式保留业务按钮、输入、滚动与内页导航，批注模式才拦截节点选择。节点／页面／全局入口打开同一个编辑对话框，入口固定目标范围。父壳唯一 state 管理选择、A、整改、草稿和导出；子页独占 DOM 命中、局部几何、高亮及有限摘录。失败如实显示并保留可恢复输入，意见不设等级。

工具包内部 `manifest.json` 只记录文件完整性与当前 context，不是项目业务 spec、设计伴随文档或批准；完整核验覆盖额外文件和每个实际文件字节。

`validate` 只读显式反馈文件，以显式 adapter 重算当前项目身份、实际需求字节 SHA、导航摘要和逐页依赖指纹，并完整核验原 review_id 的离线包及工具载荷。新格式成功返回 `status: current`、原 `anchors` 与按 `{target,items:[原item]}` 归属的 `changes`。插件升级不会覆盖旧包或自动重绑；无需保留旧插件缓存。失效、越界、未知字段、损坏包或错误节点非零退出并返回结构化错误，保留原文件。它不执行 HTML patch，不写需求、HTML、批准或任务图。

## 格式和安全边界

context 为封闭 schema 2 对象：`schema_version/request_id/project_id/adapter/adapter_sha256/prototype_root/plan_source/plan_sha256/navigation_sha256/requirements/pages/tool/review_id`。`project_id` 绑定物理项目及根节点身份，`tool` 精确为 `{version,payload_sha256}`，`review_id` 绑定其余 context 的规范 JSON。`requirements` 是需求 Markdown 中实际 REQ 标签的只读投影 `[{id,label}]`，`pages` 为 `[{path,dependency_fingerprint}]`，path 是项目相对实际 HTML 路径。context 最多 16 页、UTF-8 正文最多 8 KiB；它是版本声明而非权限凭证，不携带页面树、HTML 或批准。

新浏览器导出封闭 schema 3，只有 `schema_version: 3`、`context`、`anchors`、`items` 四个顶层字段；context 保持上述严格 schema 2。JSON 与 Markdown 承载同一个真实 envelope，不添加批准或演示元数据。Markdown 必须以唯一标题 `## Agent Workflow Feedback Payload` 标识机器载荷，其下只有一个 `json` 代码围栏；直接把该 Markdown 文件交给同一 `validate --input`，不从自由文字推断整改或引用关系。

每个 A 标记为 `{id,number,target}`，target 仅允许 node。每个整改为 `{id,number,operation,target,message,req_ids,reference_ids}`，可选 `comparison: {before_text,after_text}`、`interaction_id`、`interface_refs`。两序列分别具有唯一 id 和正整数 number，跨页稳定、不复用，允许缺号；同一来源节点不重复创建 A，但可有多条独立整改。`reference_ids` 可以多对多和跨页引用，必须全部对应本 envelope 中真实存在的 A，不能从正文里的“A1”等字样推断。

target 按范围严格封闭：节点为 `{scope:"node",page:<登记路径>,locator:{type:"id",id:<源唯一ID>}}` 或 `{scope:"node",page:<登记路径>,locator:{type:"source",key:<装配来源键>}}`；页面为 `{scope:"page",page:<登记路径>}`；全局只有 `{scope:"global"}`。节点支持 `modify/add/delete`，页面只支持 `modify/add`，全局只支持 `modify`。修改／新增正文必填，删除原因允许空；comparison 只用于节点 modify。正文和比较各文字最多 4000 字符；整体反馈最多 1 MiB，A／整改各最多 256 项，标识符最多 128 字符，interface_refs 最多 32 个、每条最多 512 字符。`kind`、`severity`、`position`、`approval`、`demo_only`、`demo_locator`、`source_stamp` 等未声明字段均明确拒绝。

稳定唯一源 ID 优先。没有可用 ID 的原始 HTML 元素由 Python 按源结构生成确定性来源键，仅在快照派生页注入保留属性 `data-prototype-review-source`；源页面自带该属性、来源键不存在、重复 ID 或不允许区域都不能通过来源复核。业务源优先使用唯一 `[data-prototype-page-content]`；合法独立页没有该标记时仅可采用唯一 main，marker 也只注入派生副本，不改业务源。`validate` 每次重读源独立重建目标，不相信浏览器传回的摘录。动态生成且无来源的节点明确不可独立确认，保留用户输入，让用户显式选择有来源父层，绝不静默绑父。

`req_ids` 仅允许目标业务源元素 `data-req-ids` 明确声明、且存在于当前需求 Markdown 目录的映射；未声明为 `[]`，页面／全局没有节点业务映射也为 `[]`，不从自由文字猜测。草稿、相机与撤回属于绑定 `review_id` 的独立封闭会话快照，不进入反馈 envelope；旧草稿不迁移。

已发布旧 feedback 2／manifest 2／bridge 2 保持原严格只读分支：旧 envelope 为 `schema_version/context/items`，item 的 `page/target_id/kind` 等原字段继续依旧合同复核，成功 `changes` 仍按 `{page,target_id,items}` 归属。旧包不用新 TOOL_ASSETS 或新装配逻辑回验，不把新导出降级，也不迁移旧草稿；schema 1 拒绝。这里保留的是 3.x 不可变评审包读取，不恢复旧 2.0 安装兼容。

旧项目迁移另走 `migration-preview`，默认只报告保留；仅显式 `--confirm-no-active-use` 且有字节同源、无实际引用的纯工具文件才成为候选。执行 `migration-apply --preview <精确预览文件>` 必须另获该项目明确写权限，并复核同一来源；保留 index、prototype.css/js、具体页、未知、修改、混合及活动使用冲突资产。失败用同一 preview 的 `migration-recover` 恢复；冲突不覆盖用户新内容。该入口不授权跨项目迁移。

`interface_refs` 仅为字符串数组，值必须来自匹配目标的唯一 `data-contract-for` 元素自身或后代的明确 `data-interface-ref` 属性字面值；不从 href 取值、不生成链接、不请求接口。`interaction_id` 只能是该契约元素自身的唯一 id；无声明时省略。不得猜测 API 或把任意备注升为接口关联。

所有反馈内容均不可执行。`before_text` 是当前浏览器画面文字摘录，`after_text` 是用户修改建议；无可信已批准基线时明确说明，不称为真实历史，不导入执行 HTML，不改 DOM。`approved` 等文字没有批准效力，未知机器字段明确拒绝。父子通信继续核对真实 source、origin、当前页和本轮随机 token；父壳不跨 file:// 遍历子页 DOM。

## 修订归属

PM 将复核为 `current` 的 `changes` 和当前完整任务包交回原 UI Agent。设计 Agent 只在已授权 `owned_paths` 内修订原 HTML、实际交互及原五节契约，并按 `xy-prototype-verify` 返回当前指纹和静态自检。需求变化与适用视觉批准仍沿原规则；反馈不新增第三业务 gate。没有新的原型写权限时，反馈本身不能扩大范围。

意见 JSON／Markdown 是本轮交接输入，保存在现有请求证据区；不创建 spec、sidecar、Manifest、独立设计／QA／批准文件，不恢复 plan→HTML。工具资源精确包含 index.html、workspace.css/js、feedback.css/js、page-shell.js、review-state.js、review-camera.js 和 THIRD_PARTY_NOTICES.txt，随三端插件同字节交付；固定上游相机／面板来源、提交与完整 MIT 许可保留在随包 notices 中。测试生产模板的真实浏览器用例不授权自动化业务原型，不能代替用户视觉批准或统一功能 QA。
