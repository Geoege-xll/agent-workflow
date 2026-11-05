# 工作流管理工具

- 主题 ID: `PLAN-WORKFLOW-MANAGER`
- 阶段: `completed`
- 模块: `.`
- 任务等级: `Full`
- 已验收版本: `v2.0.3`

## 目标与范围

维护项目、三宿主角色模型及配置恢复的统一管理入口。Codex 候选目录与身份竞态的源代码修复已验收；本轮按用户追加授权发布 v2.0.3、更新公开 Homebrew Tap，并完成本机实际 CLI／TUI 升级验收，重点确认目录来自当前 Codex 原生接口。发布涉及源仓、Tap 和本机中央程序，按 Full 执行原生实施者与唯一独立审查，保留既有源修复和有效验证。

本轮采用已推送源提交 973e73168666001c43c6376a13ff26e0e080b0d2，使用现有 Prepare release 工作流生成同次归档、校验文件和 Formula，审查后公开 Release，再更新 Tap、正常升级本机。仅升级中央管理程序；三个业务项目已完成的同步及其配置继续保留。没有新 UI 设计、流程改造、模型推理、凭据调整或 Windows npm 发布，不覆盖任何已有版本资产。

## 需求与验收

| 需求 | 当前行为与验收边界 |
|---|---|
| REQ-001 原生候选 | 未声明显式目录时，从当前 Codex 的 app-server model/list 读取可见模型、展示名与推理档位；不硬编码型号，不从未知归属默认缓存拼出菜单 |
| REQ-002 来源与身份 | 保留显式目录声明层、提供方隔离及草稿来源检查；查询期间身份或稳定来源变化时丢弃旧结果，查询自身只刷新模型缓存时仍可复用 |
| REQ-003 有界与复用 | 协议分页、消息、输出和时间有界，结束本次进程组并等待回收；TUI 当前项目／宿主复用一次结果，r 刷新当前范围，预览与配置锁内不重复启动查询 |
| REQ-004 安全回退 | 不读取 auth 正文或发起推理；原生目录不可用时给安全诊断并回退继承／当前明确配置，保留其他草稿。非 POSIX 在启动前降级，显式目录仍可用 |
| REQ-005 同次发布 | v2.0.3 使用指定源提交，GitHub Actions 的强制离线打包检查通过；归档、校验文件和 Formula 同次构建且 SHA 对应，公开新版本并正常推送 Tap，不替换旧资产 |
| REQ-006 真实升级 | 正常 Homebrew upgrade 后公共入口实际报告 2.0.3 及对应 Cellar 物理载荷根，brew test 与 CLI 必要入口通过；原用户配置和业务项目保持 |
| REQ-007 目录展示 | 从安装后的公共入口查询 Codex 目录，核对原生 model/list 来源、实际模型标识和推理档位；实际 PTY 中进入模型选择并核对菜单及安全退出，不保存模型偏好；不将目录可见冒充真实推理授权 |

## 方案与原型关联

沿用 Python 3.11+ 标准库和 curses，无新增依赖。manager/codex_models.py 只负责 stdio 协议及进程生命周期，manager/catalog.py 负责目录投影和快照，service.py 与 tui.py 复用当前来源检查。CLI 与 TUI 共用目录发现；布局、按键和操作顺序不变，无新原型。

显式 model_catalog_json 继续优先，按声明该字段的配置目录解析相对路径。没有显式目录时，使用当前 PATH、CODEX_HOME、项目 cwd 及宿主信任启动原生接口，不覆盖模型、账户、权限或提供方配置。使用返回的 model 字段作为配置值，排除隐藏项与 ultra；模型目录可见不证明推理权限。

身份守卫只读取 auth 文件元数据，默认缓存只提供不透明 identity 失效信号。查询前后身份及稳定来源必须一致；仅缓存刷新允许后置绑定。宿主尚未反映到本地的外部 keyring 变化不能保证即时发现；凭据刷新可能保守使草稿失效，r 可重新获取。

发布先准备并冻结 Draft 产物与 Tap Formula，由唯一 Reviewer 复核实际产物、源提交和已有模型目录证据。通过后 PM 公开 Release、提交推送 Tap；正常安装与现场 CLI／TUI 交付验证由对应原生实施者执行，PM 接收结果后原位更新本稿及同名 HTML。只对新发行载荷、真实安装和现场目录补必要验证，未变的源码回归不重新运行，GitHub Actions 强制检查按原工作流执行。

## 当前进展与恢复入口

源修复已完成，由同一实现者关闭独立 QA 发现的唯一身份竞态，同一 Reviewer 差量验收通过。初始 19 个选定节点的有效结论继续复用；只补查竞态及受影响的快照子场景。此前正常本机权限下源入口真实返回 8 个可见模型及继承项，属于当时的现场样本，不固定为本轮应返回的数量。

v2.0.3 已于 2026-11-05 通过[真实发布任务](https://github.com/Geoege-xll/agent-workflow/actions/runs/41948749299)及唯一独立发行审查后[正式公开](https://github.com/Geoege-xll/agent-workflow/releases/tag/v2.0.3)，标签精确指向源提交 973e73168666001c43c6376a13ff26e0e080b0d2。强制离线打包检查 12 项通过；146 个源载荷文件字节与模式一致，三份资产及待发布参数的完整性已独立核实。Tap 单文件提交 f3d7a6171b980037874cd6474bdb99b382c6be11 已正常推送，远端与本地一致。

本机正常 Homebrew upgrade 与 brew test 均退出 0，公共入口实际为 2.0.3，物理中央源根为 /opt/homebrew/Cellar/awf-cli/2.0.3/libexec，8 项核心安装代码与已审发行包一致。CLI 当前真实原生目录返回 9 个候选及继承项；真实 PTY 中 mt-shop／Codex／xy-backend 的 10 项模型菜单与 CLI 标签、顺序一致，逐项导航、查看推理档位后取消退出 0，退出前没有待应用设置。没有调用模型推理或写入模型偏好。

24 个相关用户及三项目配置的内容、权限保持一致，认证只取元数据且未变化；brew test 自动开启的 developer mode 已通过正常命令恢复 disabled。Brew 自身正常更新必要依赖并清理旧 awf-cli kegs，既有无关 Tap 信任和 Node 路径遮蔽提示保留现状，不扩大到本轮修复。发行审查的原生审批策略不匹配诊断、按 ID 读取草稿的原 404、CI 原日志、正常升级和 PTY 原始转录均保留，没有通过覆盖旧证据或重复验收取得结论。

唯一恢复入口为本稿及同名 HTML，当前发布任务记录和完整日志复用 request-id `release-v2-0-3-cli-tui` 的唯一本请求证据区；不复制项目或环境。旧源修复证据保留在 `tui-codex-model-discovery` 请求，前次源码与三项目安装证据保留在 `audit-sync-three-projects-push` 请求。Git 基线 `50ca8a9` 及当前已推送源提交保留历史；既有备份、用户配置和会话记录不由本次清理。

## 验收结果与当前已交付行为

当前已验收版本为 v2.0.3，包含正式 Release、同次产物对应的 Tap 更新、正常本机升级和真实 CLI／TUI 目录验收。原源码基线 qa-36ae27156092 及其六路径完整审查范围 `36ae271560926ac16fc40580edb9c98bbe3867f64a66a3980ed18a5743d9e0e6` 保留；未变源码、19 个定向节点与竞态证据按输入匹配复用，不冒充新的全仓回归。

现场的 9 个原生模型 ID 为 gpt-6.1-sol、gpt-6-astra、gpt-6-sol、gpt-6-luna、gpt-5.6-sol、gpt-6.1-terra、gpt-5.6-terra、gpt-5.6-luna、gpt-5.5，另有 inherit。前 8 项返回 low／medium／high／xhigh／max，gpt-5.5 支持至 xhigh；这是当前本机原生接口的可见目录样本，不是静态型号表或真实推理权限证明。TUI 在 180×48、TERM=xterm-256color 的实际终端中显示全部 10 项，正常取消退出，没有模型设置落盘。

原有行为继续保留：角色模型偏好存入项目 .agent-workflow/project.yaml 的 role_models，应用前预览并备份，只更新选中角色的模型字段，保持正文、工具、权限、Hooks 和编排；已有 Agent 不会因此重启。旧 inode 原件位于项目同文件系统的 .agent-workflow-backup-models-ID，记录 previous_files；恢复前检查后续修改并保留冲突版本。安装升级沿用原事务安装器，manager 不复制进项目隐藏运行时。

当前全局 awf-cli 来自 Homebrew 2.0.3。在目标项目根目录可通过公共入口查看版本、当前目录和界面：

```bash
awf-cli --version
awf-cli models --platform codex --project .
awf-cli tui --project .
```

## 批准依据与必要证据

- 批准依据: 用户 2026-11-05 明确要求“继续发布新版本并更新 Homebrew Tap，完成本机 CLI/TUI 升级验收，重点确认 Codex 模型列表能拉取真实可用模型”，来源 `user:2026-11-05:release-homebrew-cli-tui`，覆盖新版本、Tap 提交推送及正常本机验收；没有新 UI 设计或额外确认阶段。
- 验收证据: 本轮唯一 Reviewer `/root/homebrew_release_qa` 正式发行 PASS，工程 36 条逐项覆盖，`release-qa-handoff.json` SHA256 为 `270bda0e997cdfeb8cebb2cdc83e4188b77f37c8de5862f9bda5b6b3ef834a03`，当前包绑定校验 valid；真实 CI 12 项通过。随后实际本机验收 PASS 的 `cli-acceptance-handoff.json` SHA256 为 `9edd39f12939b58827f11a288cd67ab04acb4ba23d3ad3e483c0fd07e89a0239`，完整日志为 `5886df1bfe87407f0864f7c80ac40c1848196e4ad75a9fb6d0b98e08dd31f837`，PTY 转录为 `82b4ea2a20ce55ebea1a346831d68c006a0914606283ce1ecd7b20fbf9b3da25`；PM 核对三份原件指纹匹配后接收。
- 上一轮源码批准: 用户报告 TUI 的 Codex Agent 模型列表只有 gpt-6.1-sol，要求纠正为读取宿主可用目录；按范围明确的 Light 缺陷直接修复。
- 上一轮源码验收: Reviewer `/root/codex_models_qa_1` 的六路径、36 工程规则 PASS，`qa-handoff.json` SHA256 为 `205d8d9b5278f8ea5e41048465117dc11310a3a498f4d2a6f9a2efc9a5e35661`，绑定包 `c3d3ed062c4207e3793e957e97783cb460a4ab3a147309710b1d65649a2520d1`；首轮 F1/P2 已关闭，原始证据保留。
- 发行完整性: 归档 SHA256 为 `35ab42582ecc4f53be1c03cbcb69ec77e9221f2044270b078c6945cbadd19962`，Formula SHA256 为 `188572bf8681db7ada65c528cefc13cacc7fc20b743f415f0b475d3c20a5d317`；源标签与 Tap 提交分别绑定上述真实提交。PM 只维护文档及 Git 收口，不重新构建或替换已公开同版本资产。
- 方法与边界: 原生 review 虽退出 0，但实际审批策略未保持 never，因此同一 Reviewer 使用既定已安装审查提示完成，不增加 Reviewer 或重跑 CI。当前验收为本机 macOS 的真实公共入口、原生可见目录及 PTY，不声称模型推理、隐藏型号或 Windows 原生执行已验证。
