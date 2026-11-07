# Windows 中央安装与 npm 发布准备

- 主题 ID: `PLAN-WINDOWS-CENTRAL-NPM`
- 阶段: `active`
- 模块: `.`
- 任务等级: `Full`
- 已验收版本: `none`

## 目标与范围

用户要求 Homebrew Tap 与 npm 都发布。Tap 2.1.0 已按同一 GitHub Release 的 Formula 发布，提交66b708edfc52f9a82699211fbd4397b217608e98；npm 当前不是单纯的账号或元数据问题，Windows中央安装尚有真实后端缺口。用户随后明确先注册账号、当前不发布npm，并选择“继续完成 Windows/npm，再发布”。本轮先完成 Windows/npm 实现与验收，不调用npm publish、不接收用户密码／验证码／令牌；账号就绪和后续发布另按用户当前意愿处理。

实现面向 Windows 10/11 x64、本地 NTFS、普通用户及已具备的原生目录符号链接能力。核心 Skill 继续在中央内容库，通过真实目录符号链接供三宿主使用；无权限或文件系统能力不足时在项目／中央状态写入前明确拒绝。工具不自动修改开发者模式、账户权限、PATH、profile、ExecutionPolicy、Git全局配置或宿主信任，不用复制或junction替代已约定软链接。能力前提依据[Microsoft目录软链接接口](https://learn.microsoft.com/en-us/windows/win32/api/winbase/nf-winbase-createsymboliclinkw)，须由原生正反两类证据核实，不能只凭操作系统名称认定成功。

从已发布e2c981b1f5ff31e5cda41365682605ff747f3000开始，新增代码作为2.1.1候选；不覆盖v2.1.0标签、资产或业务项目绑定。生产由fresh／handoff_only的后端系统子代理负责，PM仅协调、计划、临时CI检查点与Git；保留来源仓5处未提交修改。依现有工作树策略在独立工作树实现和集成，原生Windows验证使用精确提交的临时CI分支；本地main最终合并保留项目confirm策略，候选完成后才进行该决定。

不扩展Windows TUI／管理器、WinGet、macOS npm入口、旧版兼容或立项讨论入口；不改变Light／Full、schema2、角色职责、英文受管指令、中央内容绑定和旧任务pin，不升级无关依赖或调用真实账户模型。

## 需求与验收

| 需求 | 完成标准 |
|---|---|
| REQ-WIN-001 平台文件系统 | 在现有platform_fs／windows_fs职责内补齐中央安装所需的目录软链接创建、锚定读取／身份校验、排他发布、删除与恢复；目录描述符不能回落给不理解伪fd的stdlib。普通文件继续拒绝任意重解析点、多硬链接与目录替换 |
| REQ-WIN-002 中央事务 | 实际中央导入、项目安装、机器binding／journal／retained及恢复路径完整消费后端；保留权限／ACL、同卷准备、精确前像、并发拒绝和持久化屏障。不得把失败fsync改为no-op，不虚构跨资源原子性 |
| REQ-WIN-003 当前npx合同 | 实际npm入口以调用cwd安装，薄runtime.py与三字段pin替代旧项目lib夹具；内置私有Python、完整Git验证、离线／ignore-scripts、重复安装和真实Hook消费当前中央服务。无权限、坏来源或并发／取消失败不留下误报成功的工作流 |
| REQ-WIN-004 发布准备 | product/VERSION、npm元数据、CLI版本、构建器与对应消费者统一2.1.1；候选完整包无lifecycle联网脚本或npm依赖，保留上游许可证和包白名单。可准备公开所需元数据与dry-run，但本轮不实际npm publish，不改已公开2.1.0 |
| REQ-WIN-005 原生证据 | 精确候选在原生Windows NTFS验证受管软链接正常与缺能力拒绝、身份交换／junction／硬链接拒绝、并发／占用、超时／Ctrl+C与恢复、缓存清理后薄桥／Hook、用户配置和系统设置不变；区分托管管理员与普通用户。必要macOS直接消费者通过，唯一独立QA对完整组合验收 |

## 方案与原型关联

本轮non_ui系统与安装功能，不改TUI或设计文件，不做原型。Windows文件系统、中央消费者和npm包是一条高耦合安装链，统一交给一个后端系统实现单元，内部按“底层句柄／软链／发布语义 → 中央直接消费者 → npx及当前E2E／原生CI → 版本与发布准备”顺序推进，避免多作者并写同一跨平台契约。必要代码仅在现有职责处补齐，不制作通用新框架，不全局patch标准库os。

实现使用原有ctypes／Win32和Python／Node／Git for Windows栈。非显然权限、并发、清理和异常策略加入详细中文注释。新增回归只覆盖本次缺失行为，优先扩展现有测试；真正独立的Windows中央原生矩阵可建一个测试模块。先用未修源码证明行为拒绝，再补有效后端与真实消费者。原生CI能力不足或新发现API无法满足原合同必须带具体失败返回PM，不能放宽守卫制造绿色。

验证复用此前Claude／Codex／TUI与真实PTY未受影响结论。保留既有Windows CI的实际相关检查，随精确提交迁移当前E2E；新增普通用户正反能力验证使用自有临时账户／目录并收尾，绝不修改开发机或真实业务项目。首次基线CI可定位原生目录屏障等尚未知能力，已知init拒绝不反复整组重跑。实现者给出成功build／可运行消费者和完整命令、退出码、源SHA及日志，PM在隔离工作树生成仅本任务的CI检查点，只有当前候选的原生证据成立才进入唯一独立QA。

QA后PM原位更新本主题及同名HTML，使用实际required生命周期解析、链接和HTML freshness；source-pack没有PROJECT／STANDARDS索引，保留配置路径及null，不创建空索引或假报全仓文档通过。README、Homebrew及Windows用法由实现单元随真实候选更新，说明来源版本与已公开版本的不同状态。独立候选最终交付只包含本轮改动和已验计划投影。

## 当前进展与恢复入口

准备审计已完成，当前npm init只接受win32/x64，但install_central先调用的require_skill_symlinks对nt无条件拒绝；Windows伪fd后端还缺readlink／link／symlink，既有E2E仍调用旧项目lib路径。已有单例确认拒绝早于中央导入和项目／state写入；该通过仅证明安全拒绝，不是安装支持。

普通npm账号尚未注册／登录，当前不发布。发布准备记录在request-id publish-tap-npm-2.1.0-20261107的既有scratch；本实现请求使用request-id windows-central-npm-2.1.1-20261107的唯一scratch及其中单一graph和作者／CI完整日志。来源分支main基线e2c981b，5处外部修改留在原检出；实现工作树windows-fs，后续集成工作树windows-integration，当前无已验收Windows候选。

## 验收结果与当前已交付行为

本主题尚无已验收版本。GitHub及公共Tap的2.1.0发行事实保持；本轮计划、工作树、绿色便携测试或托管管理员环境结果均不作为Windows普通用户安装成功的证据。

## 批准依据与必要证据

- 批准依据: 用户在npm功能阻塞与需新增实现范围明确后选择“继续完成 Windows/npm，再发布（推荐）”；同时明确先注册账号、当前不发布npm。当前Full范围为Windows文件系统适配、当前中央E2E、原生验证与npm发布准备，沿用既定软链接及工作流，不重复要求已明确的范围批准。
- 验收证据: 尚未进入实施验收；当前仅有准备审计与写入前能力拒绝单例。正式完成须记录精确候选、原生Windows和必要macOS证据、唯一独立QA及实际交付边界，不以完成状态替代验收。
