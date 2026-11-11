# 3.0 官方插件与原生 Agent 配置

- 主题 ID：`PLAN-PLUGIN-V3`
- 阶段：`active`；alpha.2 的审计返工、本地门禁及源码 QA 完成，官方客户端整体验收未完成。
- 当前修复基线：`e07694450c7267eecb0c51423ff73e4f2e8e6f24`；此前 main 保全基线为 `de847fd6e10de5b31d04591b4fe596808ae8fa1d`。
- 实施分支：`codex/plugin-v3-20261111`；本机、业务项目与既有 Tap 安装未替换。
- 工作流唯一版本源 `product/PLUGIN_VERSION`：`3.0.0-alpha.2`。
- 独立配置工具唯一版本源 `native_config/VERSION`：`0.1.0-alpha.2`。
- 稳定发行及三宿主完整运行验收：`none`，`runtime_verified=false`。

## 已批准范围与不变量

使用 Codex、Claude Code、Antigravity 的官方插件机制。独立配置工具采用平台原生 Agent 身份，识别用户级、项目级和插件角色，不限 AWF 固定角色；两个产品独立版本、独立打包，工作流不以服务、网页或 MCP 为前置。

Full 的需求确认和适用的视觉确认保留；Light 已有授权、一致性任务及用户明确直接开发继续按原适用规则，不新增业务确认。主会话 PM 持续接单，按真实重叠、依赖和容量协调并行、复用、追加或等待。生产实现原生委派，新任务 fresh/handoff_only，最小完整交接不复制 PM/兄弟会话；同任务返工和原 Reviewer 差量复查可复用。Full 保留请求级唯一独立只读 QA 与原收口顺序。

用户最新决定删除计划 Markdown→HTML 生成链，覆盖此前“注释保留”的决定。计划维护唯一 Markdown；**原型设计、原型 HTML、静态原型验收、指纹、视觉确认及生产 QA 门禁完整保留**。历史计划 HTML 与既有原型页面内容不变。Windows 暂停。

## 架构与生产归属

| 包 | 唯一职责 | 当前结果 |
| --- | --- | --- |
| R1 | task_settlement、task_graph、dispatch_admission 及所属测试 | 实现合同与原生事实/元数据分层；单图与跨物理 Git 域请求唯一 QA；源码 QA 通过 |
| R2 | 原型 adapter、documents 安全读取、计划渲染退役、插件载荷及模型指引 | 精确传递已选 adapter，安全原语独立，原型串联通过；源码 QA 通过 |
| R3 | native_config 保存结算、原生名称与必要收据 UI | 完整收尾结果、未知位置、Claude 名称及碰撞保护；追加容器问题已关闭 |
| R4 | 当前 PR/push 门禁、版本源、两产品候选编排 | Python 3.11 当前门禁通过，七包/源码摘要合同通过 |
| PM | 本计划、README、使用与架构说明、整合提交 | 不代写生产实现 |
| 唯一 QA | 冻结来源、只读审查与原作者差量返工复核 | 同一实例覆盖各包；无第二实现验收 Reviewer |

工作流权威仍在 product、roles、共用 Skill。项目配置与物理插件内权威分开读取，旧中央 binding/桥混用明确拒绝。空项目显式 apply 仅创建缺失的 `.awf/project.yaml`，不复制规范、不创建空文档或伪造批准。claim 是预留，unknown 创建结果不释放/重派，单 PM 显式记录不冒充全局跨 PM 调度。

原生配置核心不导入 lib、manager 或 AWF 角色枚举。网页、HTTP、脚本与可选 MCP 共用发现、校验、预览、保存和诊断；不按名称合并同名来源，不用旧字段偏好合并替代原生整定义优先级。插件缓存只读，未知能力或不完整清单不生成可派发结论。

## 整体审计及修复

审计基线与原负控记录：`/private/tmp/awf-v3-overall-audit-e076944.json`。

| 问题 | 修复与必要证据 | 源码 QA |
| --- | --- | --- |
| AUD-001：新 .awf 配置未进入原型导航 | CLI/API 精确传已选 adapter；仅 .awf、根配置、双配置、自定义 docs、安全竞态及三宿主脱离源码串联 | 关闭 |
| AUD-002：合法元数据/首次身份时序阻断结算 | 实际接受的实现合同与创建后绑定事实分开核；首发无 ref 包可用于只读/证据结算，错身份/范围/批准/规范/原包 SHA 仍拒绝 | 关闭 |
| AUD-003：同请求可并发领取两个 QA | 公共图校验与跨权威记录按物理 Git 域/request 拒重复；原 Reviewer 同节点失败恢复/复查保留 | 关闭 |
| AUD-004：目录退出错误覆盖真实保存收据 | 退出与清理纳入结算，保留 published/逐项结果/前像；无法定位时 unknown/null 与原声明位置、观察身份 | 关闭 |
| AUD-005：Claude 插件调用名错误 | 默认扫描采用子目录与 frontmatter 名；manifest 显式文件省子目录；原生调用名碰撞阻派发 | 关闭 |
| AUD-006：PR 未跑当前两产品 | PR/main/开发分支 push 的 current 覆盖两产品、原型与实际协议；Node 缺失执行前失败 | 关闭 |
| R3-QA-001：只移保留容器仍伪报可定位 | fd 关闭前核容器名称、目录身份与恢复对象名称/身份，再合并父目录退出核验；六种真实移动/同字节替换负控 | 关闭 |

恢复项失联不自动扫描定位或删除，原 inode 与固定前像完整保留。只移动保留资料且目标保存成功时仍保留 saved/published 事实；完整请求因目录退出异常未获确认时，界面说明实际发布与最终确认的区别。观察 SHA 与不可变预览 SHA 分开，不承诺返回后的未来路径恒定。

## 验证记录

- 唯一完整 `current`：Python **3.11.15**、Node **v22.23.2**、获准真实回环；**392 项，391 通过、1 个 Codex 官方临时隔离入口限制 skip，exit 0**，81.838 秒。源码前后摘要一致，无重试。日志 `/private/tmp/awf-r4-current-final-py311.log`，结构记录 `/private/tmp/awf-r4-current-final-evidence.json`。
- R1 作者六模块：169 项中 168 通过，既有 legacy `RecordInstalledRuntimeTest` 缺 `central` 失败保留，未修兼容/吞错/伪 skip。另真实 Git 身份 1/1 及原审计时序重放通过。当前门禁不宣称 legacy 全仓 PASS。
- R2 已通过原型、安全读取、模型合同及真实包串联。初始自定义 docs、PROJECT 夹具错误分别仅修夹具/重跑失败节点；旧发行目标的两项离线链接失败随明确授权的目标退役处理，未算成通过。详情 `/private/tmp/awf-r2-build-evidence.json`。
- R3 作者受影响 46/46；追加定位负控后 storage 模块 31/31。受限回环 EPERM 与获准运行分别保留，未改测试绕过。详情 `/private/tmp/awf-r3-native-build-verified.json`、`/private/tmp/awf-r3-retention-build-verified.json`。
- R4 定向 Python 3.11 合同 22/22；实际官方 tag/固定提交校验 checkout、setup-python、upload-artifact，完整 SHA 与工作流一致。详情 `/private/tmp/awf-r4-build-evidence.json`、`/private/tmp/awf-r4-ci-preflight.json`。
- 唯一 Reviewer：R1/R3 首轮 12 SHA、R2/R4 52 SHA/10删除、R3 两文件返工首尾一致；独立针对性 5/5、6/6及六子场景/原保留容器负控通过。结论分别在 `/private/tmp/awf-v3r-r1-r3-independent-qa.json`、`/private/tmp/awf-v3r-r2-r4-independent-qa.json`、`/private/tmp/awf-v3r-r3-retention-independent-qa.json`。

这些结果属于源码与临时夹具验证，不证明官方会话已加载、真实模型派发或推理生效。远端 Mac/Linux 结果按对应源码提交的 GitHub Actions 实际运行记录判断。

## 交付与清理边界

`packaging/build_candidates.py` 仅编排两个既有构建器，在源码树外全新目录生成三宿主 plugin/local-source 六包和一个 native 独立包、校验与源码摘要。版本和包摘要从实际构建生成，不手工维护另一份版本源。拒绝源码漂移、混包、错版与覆盖旧输出；运行验证标志保持 false。自动工作流只读源码并上传候选附件，不创建 tag 或 Release。

已退役计划生成器、专用 vendor、入口、专属测试和旧 reference；通用安全原语归 `safe_documents.py`，现行 Markdown 合同归 `requirements-markdown.md`。已有历史计划 HTML 与 `docs/standards/prototype` 相对基线差异为空。

3.0 分支已退役旧 `build_release.py`、Formula 和专属 Homebrew 归档测试；其专属 import/安装模拟随目标退出，开发入口覆盖保留。历史 2.x 发行使用对应 Git 源版本，现有 main、Tap、用户程序与项目不受源码清理影响。旧中央启用/TUI/安装等其它产品面仍待对应原生验收后按消费者退役；不加入旧数据兼容层。

## 剩余官方运行边界

- Codex CLI 已发现九项插件 Skill，候选默认 Hook 入口尚未通过；不以写全局指令或 trust 掩盖。
- Claude Code 校验/发现通过，继承模型的短 smoke 未取得有效回答；新会话 PM 与实际派发需正常响应的原生环境。
- AGY 仅只读确认官方插件管理界面，候选未实际加载，未发现可用官方 CLI。
- fresh 上下文、持续接单/追加 ACK、独立 QA 收口、模型及推理实际生效仍须真实客户端验收。
- 活动任务跨插件更新的自动资源保留协议尚未实现，alpha 当前使用先收尾再更新的限制；源码及离线包不证明自动跨版本恢复。

稳定发布、本机替换和跨更新能力继续受上述边界约束。Windows 不执行；不会把本轮源码问题关闭写成三宿主 runtime PASS。
