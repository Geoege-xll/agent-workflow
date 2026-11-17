## Codex 原生定义的插件资源边界

本定义由规范角色、`product/ROLES.yaml`、Codex Worker 约束机械生成。
资源绝对根是：__XY_WORKFLOW_PLUGIN_ROOT__

该路径由显式准备入口绑定到当时已经确定的物理插件目录。原生定义可能位于
用户或项目的 `.codex/agents/`，不能按角色文件的相对位置猜测插件根，也不能用
当前工作目录、同名全局角色、另一插件缓存或最新版本替换此来源。

开始执行前，在进程内解析该绝对根的 `sources.json` 和 `workflow-sources.json`，核对
`schema_version: 1`、`plugin_name: xy-workflow`、`product: workflow-core` 与
`host: codex`。在同一进程内计算下方“准备时规范来源摘要”中每个普通文件的实际 SHA-256，
同时核对它们在 `source_files`、`payload_sha256` 和 `workflow-sources.json.files`
中的摘要一致。只输出本定义列明文件的校验结果或失败原因，不将两份完整清单、
全包路径列表或用于哈希的角色正文回灌模型上下文。资源不存在、链接到其他目录、来源改变或摘要不一致时明确失败并
向 PM 报告；禁止自动搜索其他缓存、执行旧中央安装器或借同名角色继续运行。

核对成功后，若当前上下文尚未完整提供该根的 `PLUGIN.md`，补读一次；资源与 helper 均使用此根的真实绝对路径。
调用解释器使用 `bash <插件根>/lib/python_runtime.sh -B -X utf8`，路径作为独立
参数传递，包含空格、引号或反斜杠时使用调用工具支持的参数数组或安全引用，
禁止 eval。完整角色正文和 Codex Worker 约束已经注入本定义，校验成功后直接使用，
不再重复读取其源文件正文。仅按当前任务需要补读尚未提供的同根 `product/WORKFLOW.md`、
选中 Skill 及项目规范叶子；必需选中的 Skill 与受控标准仍须按各自完整读取、
指纹和适用规则要求执行，不因避免重复读取而省略缺失内容。项目文件仍解析在任务指定的项目根。
历史 `.agent-workflow/` 示例通过同根 `plugins/source_pack.py resource` 和
`plugins/project_context.py inspect` 适配，不创建或改写项目发现文件来激活插件。

本段只负责原生定义离开插件目录后的来源定位与核对，不复制业务流程，不赋予
审批、写权限、编排权或 QA PASS。完整角色正文和下方 Codex 约束继续作为规范，
只接收当前完整、独立的新任务包，不继承 PM 或其他 Worker 历史。候选资源本身
不证明原生定义已被发现，也不证明模型或推理设置已经生效；模型、推理和权限
由宿主当前配置决定，本定义不初始化这些设置。
