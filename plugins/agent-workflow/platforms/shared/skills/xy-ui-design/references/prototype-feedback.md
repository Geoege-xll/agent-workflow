# 原型反馈修订消费合同

仅在当前任务使用节点反馈时读取。本合同补充 `prototype-canvas.md` 的展示外壳与 `xy-prototype-verify` 的静态证据，不使其他 Worker 默认预读反馈格式。需求与方案仍以同一主题 Markdown 为唯一编辑权威，具体稳定 HTML 是视觉评审对象。

## 准备和交还

使用当前安装版本的物理插件根，先从 `resource` 解析模板，不从 cwd 猜测缓存或使用项目同名诱饵。新页面按原授权消费模板；不批量覆盖现有业务原型。所有 helper 通过包内解释器选择器和白名单入口调用，项目使用任务已选的同一 adapter：

```text
bash <physical-plugin-root>/lib/python_runtime.sh -B -X utf8 <physical-plugin-root>/plugins/source_pack.py resource templates/prototype/index.html
bash <physical-plugin-root>/lib/python_runtime.sh -B -X utf8 <physical-plugin-root>/plugins/source_pack.py helper --project <physical-project-root> lib/documents/prototype_feedback_cli.py prepare --root <physical-project-root> --adapter <selected-project-adapter> --plan <project-relative-Markdown> --request-id <request-id> --pages <project-relative-HTML>
bash <physical-plugin-root>/lib/python_runtime.sh -B -X utf8 <physical-plugin-root>/plugins/source_pack.py helper --project <physical-project-root> lib/documents/prototype_feedback_cli.py validate --root <physical-project-root> --adapter <selected-project-adapter> --input <explicit-feedback-file>
```

`prepare` 只读项目，成功向 stdout 返回 `status: ready`、`context` 和 `review_url`；`--pages` 可列出本轮实际 HTML，省略时由原型校验器选择已登记页面。用户通过准备好的链接进入本轮评审，无需输入 SHA。链接仅声明版本绑定，导航保留 `review`；坏 context 只停用反馈，普通浏览继续可用。浏览器通过草稿编辑、撤回、定位与导出／复制交还意见，失败须如实显示且保留可恢复输入。

`validate` 只读显式反馈文件，以显式 adapter 重算实际需求字节 SHA 和原校验器逐页依赖指纹；成功返回 `status: current` 与按 `{page,target_id,items:[原item]}` 归属的 `changes`。失效、越界、未知字段或错误节点非零退出并返回结构化错误，保留原文件，不自动重绑。它不执行 HTML patch，不写需求、HTML、批准或任务图，不提供 output/apply 动作。

## 格式和安全边界

context 为封闭对象：`schema_version/request_id/adapter/prototype_root/plan_source/plan_sha256/requirements/pages`；`requirements` 是需求 Markdown 中实际 REQ 标签的只读投影 `[{id,label}]`，`pages` 为 `[{path,dependency_fingerprint}]`，path 是项目相对实际 HTML 路径。context 最多 16 页、UTF-8 解码正文最多 8 KiB；fragment 最多 12 KiB，只允许唯一 `page`／`review`，review 使用 base64url UTF-8。它是版本声明而非权限凭证，不携带页面树、HTML 或批准。

浏览器导出封闭 schema 1：`schema_version: 1`、`context`、`items`。item 必须包含唯一 `id`、`page`、`target_id`、`kind`（`must_change | suggestion | question`）、`message`、`req_ids`；可选 `comparison: {before_text,after_text}`、`interaction_id`、`interface_refs`。同一节点可有多条独立意见；目标必须是当前页实际唯一稳定 ID。反馈最多 1 MiB、256 条；message 和 comparison 各文字最多 4000 字符，标识符最多 128 字符；interface_refs 最多 32 个、每条最多 512 字符。

`interface_refs` 仅为字符串数组，值必须来自匹配目标的唯一 `data-contract-for` 元素自身或后代的明确 `data-interface-ref` 属性字面值；不从 href 取值、不生成链接、不请求接口。`interaction_id` 只能是该契约元素自身的唯一 id；无声明时省略。不得猜测 API 或把任意备注升为接口关联。

所有反馈内容均不可执行。`before_text` 是当前浏览器画面文字摘录，`after_text` 是用户修改建议；无可信已批准基线时明确说明，不称为真实历史，不导入执行 HTML，不改 DOM。`approved` 等文字没有批准效力，未知机器字段明确拒绝。父子通信继续核对真实 source、origin、当前页和本轮随机 token；父壳不跨 file:// 遍历子页 DOM。

## 修订归属

PM 将复核为 `current` 的 `changes` 和当前完整任务包交回原 UI Agent。设计 Agent 只在已授权 `owned_paths` 内修订原 HTML、实际交互及原五节契约，并按 `xy-prototype-verify` 返回当前指纹和静态自检。需求变化与适用视觉批准仍沿原规则；反馈不新增第三业务 gate。没有新的原型写权限时，反馈本身不能扩大范围。

意见 JSON 是本轮交接输入，保存在现有请求证据区；不创建 spec、sidecar、Manifest、独立设计／QA／批准文件，不恢复 plan→HTML。测试生产模板的真实浏览器用例不授权自动化业务原型，不能代替用户视觉批准或统一功能 QA。
