# 原型反馈修订消费合同

仅在当前任务使用节点反馈时读取。本合同补充 `prototype-canvas.md` 的展示外壳与 `xy-prototype-verify` 的静态证据，不使其他 Worker 默认预读反馈格式。需求与方案仍以同一主题 Markdown 为唯一编辑权威，具体稳定 HTML 是视觉评审对象。

## 准备和交还

使用当前安装版本的物理插件根，先从 `resource` 解析模板，不从 cwd 猜测缓存或使用项目同名诱饵。新页面按原授权消费模板；不批量覆盖现有业务原型。所有 helper 通过包内解释器选择器和白名单入口调用，项目使用任务已选的同一 adapter：

```text
bash <physical-plugin-root>/lib/python_runtime.sh -B -X utf8 <physical-plugin-root>/plugins/source_pack.py resource templates/prototype/page.html
bash <physical-plugin-root>/lib/python_runtime.sh -B -X utf8 <physical-plugin-root>/plugins/source_pack.py helper --project <physical-project-root> lib/documents/prototype_feedback_cli.py prepare --root <physical-project-root> --adapter <selected-project-adapter> --plan <project-relative-Markdown> --request-id <request-id> --pages <project-relative-HTML>
bash <physical-plugin-root>/lib/python_runtime.sh -B -X utf8 <physical-plugin-root>/plugins/source_pack.py helper --project <physical-project-root> lib/documents/prototype_feedback_cli.py validate --root <physical-project-root> --adapter <selected-project-adapter> --input <explicit-feedback-file>
```

`prepare` 只读项目，成功向 stdout 返回 `status: ready`、`context`、`review_url`、`bundle_path` 和 `reused`。新项目用 `--pages` 明确列出本轮实际 HTML；省略时消费既有登记。工具从当前物理插件装配用户级私有、不可变的离线包，只复制明确页面的必要渲染依赖和需求导航文档，不复制整个项目。默认数据根为 macOS `~/Library/Application Support/agent-workflow/prototype-reviews`，其他 POSIX 使用绝对 `XDG_DATA_HOME` 或 `~/.local/share` 下的 `agent-workflow/prototype-reviews`；隔离验证可显式传 `--data-dir <项目外绝对实际目录>`，prepare 与 validate 使用同一目录。

用户通过该包的 `index.html#page=<文件名>` 进入评审，无需输入 SHA；启动 context 来自包内安全转义的 JSON，链接不再承载 base64 review。导航保留既有 index 的文本和 details/summary 分组，但不执行旧 index。通用查看器、反馈和通信代码只在插件与派生包持有，项目源不增加工具壳；桥只注入派生 HTML，使用幂等 `prototype-review:* version:2`，忽略旧 `prototype-workspace:* version:1`。浏览器通过草稿编辑、撤回、定位与导出／复制交还意见，失败须如实显示且保留可恢复输入。

工具包内部 `manifest.json` 只记录文件完整性与当前 context，不是项目业务 spec、设计伴随文档或批准；完整核验覆盖额外文件和每个实际文件字节。

`validate` 只读显式反馈文件，以显式 adapter 重算当前项目身份、实际需求字节 SHA、导航摘要和逐页依赖指纹，并完整核验原 review_id 的离线包及工具载荷；成功返回 `status: current` 与按 `{page,target_id,items:[原item]}` 归属的 `changes`。插件升级不会覆盖旧包或自动重绑；无需保留旧插件缓存。失效、越界、未知字段、损坏包或错误节点非零退出并返回结构化错误，保留原文件。它不执行 HTML patch，不写需求、HTML、批准或任务图。

## 格式和安全边界

context 为封闭 schema 2 对象：`schema_version/request_id/project_id/adapter/adapter_sha256/prototype_root/plan_source/plan_sha256/navigation_sha256/requirements/pages/tool/review_id`。`project_id` 绑定物理项目及根节点身份，`tool` 精确为 `{version,payload_sha256}`，`review_id` 绑定其余 context 的规范 JSON。`requirements` 是需求 Markdown 中实际 REQ 标签的只读投影 `[{id,label}]`，`pages` 为 `[{path,dependency_fingerprint}]`，path 是项目相对实际 HTML 路径。context 最多 16 页、UTF-8 正文最多 8 KiB；它是版本声明而非权限凭证，不携带页面树、HTML 或批准。

浏览器导出封闭 schema 2：`schema_version: 2`、`context`、`items`；旧 schema 1 明确拒绝。item 必须包含唯一 `id`、`page`、`target_id`、`kind`（`must_change | suggestion | question`）、`message`、`req_ids`；可选 `comparison: {before_text,after_text}`、`interaction_id`、`interface_refs`。同一节点可有多条独立意见；目标必须是当前页实际唯一稳定 ID。反馈最多 1 MiB、256 条；message 和 comparison 各文字最多 4000 字符，标识符最多 128 字符；interface_refs 最多 32 个、每条最多 512 字符。

旧项目迁移另走 `migration-preview`，默认只报告保留；仅显式 `--confirm-no-active-use` 且有字节同源、无实际引用的纯工具文件才成为候选。执行 `migration-apply --preview <精确预览文件>` 必须另获该项目明确写权限，并复核同一来源；保留 index、prototype.css/js、具体页、未知、修改、混合及活动使用冲突资产。失败用同一 preview 的 `migration-recover` 恢复；冲突不覆盖用户新内容。该入口不授权跨项目迁移。

`interface_refs` 仅为字符串数组，值必须来自匹配目标的唯一 `data-contract-for` 元素自身或后代的明确 `data-interface-ref` 属性字面值；不从 href 取值、不生成链接、不请求接口。`interaction_id` 只能是该契约元素自身的唯一 id；无声明时省略。不得猜测 API 或把任意备注升为接口关联。

所有反馈内容均不可执行。`before_text` 是当前浏览器画面文字摘录，`after_text` 是用户修改建议；无可信已批准基线时明确说明，不称为真实历史，不导入执行 HTML，不改 DOM。`approved` 等文字没有批准效力，未知机器字段明确拒绝。父子通信继续核对真实 source、origin、当前页和本轮随机 token；父壳不跨 file:// 遍历子页 DOM。

## 修订归属

PM 将复核为 `current` 的 `changes` 和当前完整任务包交回原 UI Agent。设计 Agent 只在已授权 `owned_paths` 内修订原 HTML、实际交互及原五节契约，并按 `xy-prototype-verify` 返回当前指纹和静态自检。需求变化与适用视觉批准仍沿原规则；反馈不新增第三业务 gate。没有新的原型写权限时，反馈本身不能扩大范围。

意见 JSON 是本轮交接输入，保存在现有请求证据区；不创建 spec、sidecar、Manifest、独立设计／QA／批准文件，不恢复 plan→HTML。测试生产模板的真实浏览器用例不授权自动化业务原型，不能代替用户视觉批准或统一功能 QA。
