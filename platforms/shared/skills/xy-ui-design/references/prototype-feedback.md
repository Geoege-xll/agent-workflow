# 原型反馈修订消费合同

仅在当前任务使用评审整改时读取。本合同补充 `prototype-canvas.md` 的展示外壳与 `xy-prototype-verify` 的静态证据，不使其他 Worker 默认预读反馈格式。需求与方案仍以同一主题 Markdown 为唯一编辑权威，具体稳定 HTML 是视觉评审对象。

## 当前交付：具体 file HTML 与同页独立评审

本节的受管交付和本机 HTTP 评审适用于 Codex 与 Claude Code。Antigravity 按[静态验证合同](../../xy-prototype-verify/SKILL.md)直接交付可打开的具体 HTML。

3.0.4 的具体 file HTML 交付入口按本节操作；实际安装版本以官方客户端清单为准。Agent 交付前，先从当前物理插件的白名单 helper 显式执行 `prepare-delivery --root --adapter --pages`，准备受管入口与公开目录；此命令幂等、不启动服务、不执行业务请求。再以同一项目、adapter、需求、request-id 和具体 pages 执行 `open`。`open` 先验证已准备，缺失返回准确的 `preparation_required`，不会悄悄修改业务 HTML。历史 `prepare` 仍是下节独立的不可变离线评审合同；处理新的 prepared 源时，先按原始字节注入来源键再移除精确 entry，旧无标签 2／3／4 字节及 V4 九项资产不变。

```text
bash <physical-plugin-root>/lib/python_runtime.sh -B -X utf8 <physical-plugin-root>/plugins/source_pack.py helper --project <physical-project-root> lib/documents/prototype_feedback_cli.py prepare-delivery --root <physical-project-root> --adapter <selected-project-adapter> --pages <project-relative-HTML>
bash <physical-plugin-root>/lib/python_runtime.sh -B -X utf8 <physical-plugin-root>/plugins/source_pack.py helper --project <physical-project-root> lib/documents/prototype_feedback_cli.py open --root <physical-project-root> --adapter <selected-project-adapter> --plan <project-relative-Markdown> --request-id <request-id> --pages <project-relative-HTML>
bash <physical-plugin-root>/lib/python_runtime.sh -B -X utf8 <physical-plugin-root>/plugins/source_pack.py helper --project <physical-project-root> lib/documents/prototype_feedback_cli.py status --root <physical-project-root> --request-id <request-id>
bash <physical-plugin-root>/lib/python_runtime.sh -B -X utf8 <physical-plugin-root>/plugins/source_pack.py helper --project <physical-project-root> lib/documents/prototype_feedback_cli.py stop --root <physical-project-root> --request-id <request-id>
bash <physical-plugin-root>/lib/python_runtime.sh -B -X utf8 <physical-plugin-root>/plugins/source_pack.py helper --project <physical-project-root> lib/documents/prototype_feedback_cli.py validate --root <physical-project-root> --adapter <selected-project-adapter> --input <explicit-feedback-file>
```

正式交付入口是当前具体 HTML 的 `file://` URI：`delivery_url` 为首个具体页，`delivery_urls` 列出各页；可保留的 HTTP 诊断链接另名为 `http_delivery_url`，必须无 fragment 秘密，不能替代 file 入口；正式 file／review URL 均无秘密。完整目录、缩放、移动、复位、平台画板及真实业务交互都在 file 交付工具中；目录默认收起并浮出，不挤占画布，相机工具浮于画布，删除旧大标题背景。开发说明仍在具体 HTML，交付壳以大弹窗查看，不占主画布。目录使用项目已登记具体页元数据，当前页由实际文件名选择。项目完整交付 catalog 最多 256 页，与单次 review 的 16 页限额分开；一次 open 仅绑定本次已批准同需求的 1—16 页，不扫描全项目或从旧 index 推断；同项目不同页可绑定不同请求，公开目录按项目锁合并，不能用单一 active_request 覆盖其他页。多页时，prepare-delivery 与 open 都显式传入 `--pages <project-relative-HTML-1> <project-relative-HTML-2>`。

项目原稿仅保留固定相对经典入口 `<script src=".xy-prototype-entry/entry.js" data-xy-delivery-entry="1" charset="utf-8"></script>`，且先于所有业务脚本。`.xy-prototype-entry` 是指向用户级本项目发布目录的受管链接，目录级 `.gitignore` 只维护精确受管忽略项并保留用户内容。项目不复制完整工具或业务 HTML 副本，不生成导航 index；已有业务首页、未知文件及用户修改必须保留。受管链接须验证属主、版本与摘要后才获窄依赖例外，普通 symlink/hardlink 仍拒绝。通用工具同 payload 仅缓存一份，`delivery.html` 是唯一 markup；受信模板生成经典 `shell.js`，不手抄第二套 HTML。

file 顶层经典 bootstrap 不依赖 file fetch 或 ES 模块，在原始业务脚本执行前停止顶层业务解析；独立一层 file 设计 iframe 执行原稿业务一次。仅此明确 file 分支使用 `sandbox="allow-scripts allow-same-origin"`，支持相对 CSS／经典 JS；HTTP 评审内容仍仅 `sandbox="allow-scripts"`，绝不授予 allow-same-origin。父子消息同时核对准确 `event.source`、当前页、随机 nonce 和 `origin=null`，不能把相同 null 字符串当信任。保留原始 stage/frame、声明或受限实际测量的画板尺寸，公共相机不得统一成 1120×860 或清空 frame 约束。

公开 `catalog.js` 只通过 `window.XYFileDeliveryEntry.receiveCatalog(data)` 提供封闭 schema 1：`{schema_version,project_id,directory_sha256,tool:{version,payload_sha256},pages:[{name,path,label,groups,platform,display,viewport,plan_source,binding}]}`。viewport 为 `{width,height}` 或 null；binding 为 null 或 `{request_id,review_id,instance,origin}`，origin 仅为固定 `http://127.0.0.1:<端口>`。name/path 必须合法有界且指向同目录具体页。directory_sha256 是实际 prototype 目录 canonical file URI 末尾带 `/` 的 UTF-8 字节 SHA256；file UI 以 `new URL('.', originalFileURL).href` 和 WebCrypto 同口径核验后才信任目录／评审绑定，缺失、不匹配或 crypto 不可用时保留画稿、拒绝旧绑定并提示 Agent 重新准备，防止复制目录沿旧链接错入原项目。label 与原导航合同一致，最多 1024 字符；viewport 每轴为 1..16384 的有限正数，不静默缩窄或猜固定宽高。它没有 token、management、root 或 argv 权限字段，动态目录及工具引用不进入业务 render 摘要，tool 独立绑定。

file 壳完全不创建控制连接、不获取 token。公开 binding 只代表最后登记的入口，不证明当前服务 ready；不新增探测或后台连接。stop 后 file 仍可看稿，评审恢复由 Agent 显式重开服务。用户点击“进入评审”后，仅按当前页公开 binding 以 `noopener` 新标签导航到 精确引导入口 `/_entry-review/<instance>/<review_id>/<registered-name>`，原交付页保留。未准备、服务不可用或 binding 失效显示准确恢复说明，不猜端口、不冷启动、不虚称 ready；交付方用同样显式参数重跑 prepare-delivery／open。status/stop 管理精确项目请求实例，不设置系统自启动或系统 URL 协议。

服务仅绑定 127.0.0.1 随机端口，HTTP 引导严格核验当前实例、修订、登记页和精确 Host，只允许可核浏览器顶层 document/navigate；拒绝 `Origin:null` 及 iframe/script/object/fetch 取得秘密。公开 ID 和 Fetch Metadata 都不是秘密认证。合法顶层响应通过单独安全转义的 `script#prototype-browser-connection` 提供 `{schema_version:1,review_id,token}`，并设置 no-store、no-referrer、nosniff、frame-ancestors none、X-Frame-Options DENY 和 COOP 隔离。无秘密跳转 URL、cookie、凭据 CORS 或 JSONP。live-connection 仅在可信 HTTP 父工具消费原认证入口或此 bootstrap，核对相同 review_id，绝不向业务 frame 泄露认证；控制 API 继续使用 Bearer 和精确 Origin，管理 cap 保持私有。工具仅从固定 `/assets/<name>` 白名单加载，内容仅来自 `/content/<随机只读cap>/<已登记资源>`。

独立评审进入即批注，没有目录、持久浏览模式切换或开发说明；按工具提示的修饰键临时操作设计，释放回批注。交付与评审复用画布组件，各自持有相机和交互状态，不承诺任意业务内存同步。原始 HTML 字节先装配来源目标，再在 HTTP 内存响应移除精确 file 入口；不能先删后算偏移。没有 ID 的节点仍按原始字节定位，动态无来源节点保留用户输入并要求显式选择真实源父层，不静默改绑。

启动 JSON 仍精确为 boot 5 的 `{schema_version,context,pages}`，脚本为 `script#prototype-review-data`；新登记使用下述 context 4，绑定 live 来源；历史 context 3 按原规则重读。两者均限 8 KiB。新反馈保留封闭 schema 5 `{schema_version:5,review:{request_id,review_id},anchors,items}`；完整来源、修订与草稿在用户私有 live 元数据中，review_id 不由活动指针重绑。`GET /api/context` 返回 `{status:'ready'|'source_changed',context,page}`，`GET /api/draft` 返回 `{revision,draft}`；`PUT /api/draft` 用 revision 和相同快照做 CAS，冲突返回 `409 draft_conflict`。原稿变化返回 `409 source_changed`，保留旧正文和可读草稿，阻止错误定位、保存与交还。客户端不能上传可信 context、自动续期或重放写请求。相机、撤回及工具状态不进入反馈；validate 严格复核真实 live 修订后只输出 current 精简交接，不产生批准。

live 固定 17 项资产：`delivery.html`、`review.html`、`live-workspace.js`、`live-connection.js`、`canvas-host.js`、`live.css`、`workspace.css`、`review-state.js`、`review-camera.js`、`feedback.js`、`feedback.css`、`page-shell.js`、`THIRD_PARTY_NOTICES.txt`、`file-entry.js`、`file-delivery.js`、`file-page.js`、`canvas-presentation.js`。三端按 backend 的 LIVE_TOOL_ASSETS 权威名单同字节交付；packaging 只消费与历史 V4 九项的有序并集。V4 及 TOOL_ASSETS 旧别名保持，不用 live 名单回验旧包。

## 历史离线 prepare 与 feedback 2／3／4

本节的快照、index、浏览／批注、开发说明及 manifest／boot／bridge 4 仅描述历史离线分支。`prepare` 继续保留原只读装配与严格消费语义；新交付使用上面的 open 路线，不因下文而重新生成项目导航壳。


以下格式是历史 feedback 4 消费合同；3.0.4 的 file 交付不会改变这些旧包合同。实际调用使用当前所选版本的物理插件根，先从 `resource` 解析模板，不从 cwd 猜测缓存或使用项目同名诱饵。新页面按原授权消费模板；不批量覆盖现有业务原型。所有 helper 通过包内解释器选择器和白名单入口调用，项目使用任务已选的同一 adapter：

```text
bash <physical-plugin-root>/lib/python_runtime.sh -B -X utf8 <physical-plugin-root>/plugins/source_pack.py resource templates/prototype/page.html
bash <physical-plugin-root>/lib/python_runtime.sh -B -X utf8 <physical-plugin-root>/plugins/source_pack.py helper --project <physical-project-root> lib/documents/prototype_feedback_cli.py prepare --root <physical-project-root> --adapter <selected-project-adapter> --plan <project-relative-Markdown> --request-id <request-id> --pages <project-relative-HTML>
bash <physical-plugin-root>/lib/python_runtime.sh -B -X utf8 <physical-plugin-root>/plugins/source_pack.py helper --project <physical-project-root> lib/documents/prototype_feedback_cli.py validate --root <physical-project-root> --adapter <selected-project-adapter> --input <explicit-feedback-file>
```

`prepare` 只读项目，成功向 stdout 返回 `status: ready`、`context`、`review_url`、`bundle_path` 和 `reused`。新项目用 `--pages` 明确列出本轮实际 HTML；省略时消费既有登记。工具从当前物理插件装配用户级私有、不可变的离线包，只复制明确页面的必要渲染依赖和需求导航文档，不复制整个项目。默认数据根为 macOS `~/Library/Application Support/agent-workflow/prototype-reviews`，其他 POSIX 使用绝对 `XDG_DATA_HOME` 或 `~/.local/share` 下的 `agent-workflow/prototype-reviews`；隔离验证可显式传 `--data-dir <项目外绝对实际目录>`，prepare 与 validate 使用同一目录。

用户通过该包的 `index.html#page=<文件名>` 进入评审，无需输入 SHA；启动 context 来自包内安全转义的 JSON，链接不承载 base64 review。导航保留既有 index 的文本和 details/summary 分组，但不执行旧 index。通用查看器、反馈和通信代码只在插件与派生包持有，项目源不增加工具壳；当前源码新快照使用 manifest 4、boot 4 和幂等 `prototype-review:* version:4` 桥，新捕获的 context 单独声明版本 4 并绑定 offline 来源，忽略旧 `prototype-workspace:* version:1`。

工作台固定设计视口，以相机缩放／移动查看而不重排页面；浮动控件、默认收起的导航抽屉、“整改／标记”两个 Tab 和独立开发说明大对话框属于工具。浏览模式保留业务按钮、输入、滚动与内页导航，批注模式才拦截节点选择。节点／页面／全局入口打开同一个编辑对话框，入口固定目标范围。父壳唯一 state 管理选择、A、整改、草稿和导出；子页独占 DOM 命中、局部几何、高亮及有限摘录。失败如实显示并保留可恢复输入，意见不设等级。

工具包内部 `manifest.json` 只记录文件完整性与当前 context，不是项目业务 spec、设计伴随文档或批准；完整核验覆盖额外文件和每个实际文件字节。

`validate` 只读显式反馈文件，以显式 adapter 重算当前项目身份、实际需求字节 SHA、导航摘要和逐页依赖指纹，并完整核验原 review_id 的离线包及工具载荷。新格式成功只返回 `{status:"current",review,anchors,changes,notice}`；`review` 为短引用，`changes` 按 target 分组，组内 item 保留当前用户字段但不重复 target，源 `req_ids/interaction_id/interface_refs` 只在组层还原一次且仅在非空时出现。结果不包含完整 context、需求目录或自动摘录。`notice` 简短明确说明这是修订输入，不是批准。插件升级不会覆盖旧包或自动重绑；无需保留旧插件缓存。失效、越界、未知字段、损坏包或错误节点非零退出并返回结构化错误，保留原文件。它不执行 HTML patch，不写需求、HTML、批准或任务图。

## 格式和安全边界

历史 context 为封闭 schema 3 对象：`schema_version/request_id/project_id/adapter/adapter_sha256/prototype_root/plan_source/plan_sha256/navigation_sha256/requirements/pages/tool/review_id`。`project_id` 绑定物理项目根、设备及 inode 身份，`tool` 精确为 `{version,payload_sha256}`，`review_id` 绑定其余 context 的规范 JSON。`requirements` 仅为需求 Markdown 中完整、唯一的真实 REQ ID 字符串数组，不含标签正文；`pages` 为 `[{path,dependency_fingerprint}]`，path 是项目相对实际 HTML 路径。context 最多 16 页、UTF-8 正文最多 8 KiB；不得为满足上限截断丢弃真实 REQ。它是版本声明而非权限凭证，不携带页面树、HTML 或批准。

新建的离线快照和活动评审使用封闭 context 4，沿用上述字段并增加 `source_kind`。离线为 `offline`，活动源为 `live`，种类及版本均参与 `review_id` 计算。新需求目录与计划校验共用围栏规则。只在同类、长度足够且行尾仅有空白的闭栏后恢复提取 REQ；未闭合围栏中的示例直到文末均被屏蔽。验证先定位原离线包或 live 元数据，再按其中的上下文版本重读同一来源。历史 context 2／3 保留当时的围栏及标签语义，来源种类或修订身份冲突会使验证失败。

历史 feedback 4 精确为封闭 schema 4：`{schema_version:4,review:{request_id,review_id},anchors,items}`。review 只有稳定 request_id 和 64 位十六进制 review_id。复制只输出固定唯一标题 `## Agent Workflow Feedback Payload`，其下单个 `json` 围栏内为紧凑 JSON，不附同义摘要；纯 JSON 输入仍受支持。Markdown 与 JSON 交给同一 `validate --input`，不从自由文字推断整改或引用关系。

短引用只允许按显式 root／adapter 推导当前真实 project_id，在该项目与 request_id／review_id 的本机私有不可变目录定位既有包；不扫描、不信任浏览器路径、不接受外部完整 context 回退、不自动绑定 latest。先按 no-follow、属主、唯一普通文件与大小限制读取 manifest，再严格核版本、context、整包白名单、所有源／工具摘要；重读当前项目、plan、adapter、navigation、pages 及目标。来源变化、缺包或损坏明确失败，验证全程不改源、输入或快照；仅相同 review_id 或 manifest 哈希不足以证明 current。

每个 A 标记为 `{id,number,target}`，target 仅允许 node。每个整改必需 `{id,number,operation,target,message}`；可选非空 `reference_ids` 和 `after_text`，后者只用于 node／modify、非空且最多 4000 字符。浏览器不交还 context、req_ids、interaction_id、interface_refs、before_text、comparison 或其他未知字段。两序列的 id 和正整数 number 分别唯一、跨页稳定且不复用，允许缺号；同一来源节点不重复创建 A，但可有多条独立整改。`reference_ids` 可以多对多和跨页引用，必须全部对应 envelope 中真实存在的 A，不能从正文“A1”等字样推断。普通整改交还仅保留实际引用的 A；无整改时交还全部明确标记且不推断整改，未引用 A 仍保留在模型／草稿中，引用移除保护不变。

target 按范围严格封闭：节点为 `{scope:"node",page:<登记路径>,locator:{type:"id",id:<源唯一ID>}}` 或 `{scope:"node",page:<登记路径>,locator:{type:"source",key:<装配来源键>}}`；页面为 `{scope:"page",page:<登记路径>}`；全局只有 `{scope:"global"}`。节点支持 `modify/add/delete`，页面只支持 `modify/add`，全局只支持 `modify`。修改／新增正文必填，删除原因允许空；正文和 after_text 各最多 4000 字符；整体反馈最多 1 MiB，A／整改各最多 256 项，标识符最多 128 字符，number 受 JavaScript 安全整数边界约束。未知字段、重复 JSON 键、NaN 和越界值均明确拒绝。`kind`、`severity`、`position`、`approval`、`demo_only`、`demo_locator`、`source_stamp` 等未声明字段均明确拒绝。

稳定唯一源 ID 优先。没有可用 ID 的原始 HTML 元素由 Python 按源结构生成确定性来源键，仅在快照派生页注入保留属性 `data-prototype-review-source`；源页面自带该属性、来源键不存在、重复 ID 或不允许区域都不能通过来源复核。业务源优先使用唯一 `[data-prototype-page-content]`；合法独立页没有该标记时仅可采用唯一 main，marker 也只注入派生副本，不改业务源。`validate` 每次重读源独立重建目标，不相信浏览器传回的摘录。动态生成且无来源的节点明确不可独立确认，保留用户输入，让用户显式选择有来源父层，绝不静默绑父。

`req_ids` 仅允许目标业务源元素 `data-req-ids` 明确声明、且存在于当前需求 Markdown 目录的映射；未声明或页面／全局没有节点业务映射时在精简分组中省略，不从自由文字猜测。草稿、相机与撤回属于绑定 `review_id` 的独立封闭会话快照，不进入反馈 envelope；旧草稿不迁移。

已生成旧 feedback 3／context 2／manifest 3／boot 3／bridge 3 保持原严格只读分支及原资产／装配／提取语义：旧四字段 envelope 仍含 context，item 的 req_ids、reference_ids、comparison、interaction_id、interface_refs 依旧合同复核。旧 feedback 2／manifest 2／bridge 2 同样保持原严格只读分支：旧 envelope 为 `schema_version/context/items`，item 的 `page/target_id/kind` 等原字段继续依旧合同复核，成功 `changes` 仍按 `{page,target_id,items}` 归属。旧包不用新 TOOL_ASSETS 或新装配逻辑回验，不把新导出降级，也不迁移旧草稿；schema 1 拒绝。这里保留的是 3.x 不可变评审包读取，不恢复旧 2.0 安装兼容。

旧项目迁移另走 `migration-preview`，默认只报告保留；仅显式 `--confirm-no-active-use` 且有字节同源、无实际引用的纯工具文件才成为候选。执行 `migration-apply --preview <精确预览文件>` 必须另获该项目明确写权限，并复核同一来源；保留 index、prototype.css/js、具体页、未知、修改、混合及活动使用冲突资产。失败用同一 preview 的 `migration-recover` 恢复；冲突不覆盖用户新内容。该入口不授权跨项目迁移。

`interface_refs` 仅为字符串数组，值必须来自匹配目标的唯一 `data-contract-for` 元素自身或后代的明确 `data-interface-ref` 属性字面值；不从 href 取值、不生成链接、不请求接口。`interaction_id` 只能是该契约元素自身的唯一 id；无声明时省略。不得猜测 API 或把任意备注升为接口关联。

所有反馈内容均不可执行。新反馈的 `after_text` 仅是用户修改建议；旧格式 before_text／comparison 仍依原语义读取，不称为真实已批准历史，不导入执行 HTML，不改 DOM。`approved` 等文字没有批准效力，未知机器字段明确拒绝。父子通信继续核对真实 source、origin、当前页和本轮随机 token；父壳不跨 file:// 遍历子页 DOM。

## 修订归属

PM 只将复核为 `current` 的精简 `changes`、必要 `anchors` 和短 `review` 引用连同当前完整任务包交回原 UI Agent，不重复转发原反馈全文或完整校验 context。设计 Agent 只在已授权 `owned_paths` 内修订原 HTML、实际交互及适用的开发说明，并按 `xy-prototype-verify` 返回当前指纹和静态自检。需求变化与适用视觉批准仍沿原规则；反馈不新增第三业务 gate。没有新的原型写权限时，反馈本身不能扩大范围。

意见 JSON／Markdown 是本轮交接输入，保存在现有请求证据区；不创建 spec、sidecar、Manifest、独立设计／QA／批准文件，不恢复 plan→HTML。历史离线工具资源精确包含 index.html、workspace.css/js、feedback.css/js、page-shell.js、review-state.js、review-camera.js 和 THIRD_PARTY_NOTICES.txt，随三端插件同字节交付；固定上游相机／面板来源、提交与完整 MIT 许可保留在随包 notices 中。测试生产模板的真实浏览器用例不授权自动化业务原型，不能代替用户视觉批准或统一功能 QA。
