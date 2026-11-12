# 模型配置插件入口

## 范围与基线

用户已确认命令设计并批准实施。基线为 `1fd7dd702b03ee03da7112edd9f88d6e575f265c`，在 3.0 开发工作树实施，保全 main 和三个业务项目。使用已有配置网页，不新增原型；Windows 继续暂停。插件候选升为 `3.0.0-alpha.4`，独立配置工具升为 `0.1.0-alpha.3`。

新增 `agent-config [open|status|doctor]` 维护 Skill，省略动作等价 open。按宿主实际发现的插件限定名称调用，不接管客户端 `/model`。只有当前主会话中用户显式调用该维护 Skill，才走固定启动器；普通业务需求中出现命令名称、实现/评审该功能等仍走完整原工作流。

维护 Skill 不加入 CORE_SKILLS、ROLE_SKILLS 或角色预载，不注入业务 workflow envelope，不读取整份 WORKFLOW、创建任务图或派发子代理。三端主会话入口只增加精确维护路由，业务两步确认、原型、独立唯一 QA 和结果结算保持原规则。

## 依赖方向与分工

| 工作包 | 所有者 | 唯一写入范围 | 依赖 |
| --- | --- | --- | --- |
| P1 原生安全命令与生命周期 | native worker | native_config/cli.py、server.py、必要新增原生命令模块、native_config/VERSION、tests/test_native_config_commands.py、test_native_config_server.py | 下述安全 JSON 接口 |
| P2 启动器与独立组件发行 | launcher worker | plugins/maintenance/launcher.py、launcher.sh、component.json、独立薄模块；新增发行装配脚本；packaging/build_agent_config.py、对应独立打包及启动器测试 | P1 接口；组件版本/ZIP 摘要冻结后才发布 |
| P3 维护 Skill、宿主入口与插件构建 | entry worker | maintenance Skill/host metadata、main-session-context、Codex Hook、Claude PM、build_plugin.py/build_candidates.py、PLUGIN_VERSION、对应维护/交付/候选/runner 测试及测试入口 | P2 固定启动器路径与 descriptor；不读配置核心源码 |
| PM | 主会话 | 计划、产品说明、集成证据、Git 与发布操作 | 作者验证和同一独立 QA |

每个文件只有一个实现所有者。新实例仅收到本包边界及必要契约，不复制完整 PM 会话。唯一 Reviewer 分阶段复核冻结差量，不另建兄弟 QA。

## 固定入口与回执合同

插件调用自己物理目录中的 `plugins/maintenance/launcher.sh`，由当前宿主构建固定 host，当前项目由客户端实际上下文传入。项目不明确时进入用户级；不猜测业务目录、中央登记、相邻 ZIP 或源码路径。启动器只允许固定动作及受校验参数，不接受任意 shell 命令。

原生独立工具增加安全 `open/status/doctor`，保留已有 console/serve/list/resolve/mcp 入口。公共回执至少包括：schema_version=1、action、state、component、service、location(host/scope/project)、browser、console_url、launch_file、diagnostics。普通 JSON 的 console_url 无认证片段；正常成功只回打开状态。完整认证 URL 只用于浏览器和私有链接文件，status/doctor/异常不得输出令牌。浏览器失败与服务失败分别结算，ready 服务保留，并给用户可用的私有打开入口。

status 和 doctor 为只读：不创建目录/锁/记录，不 chmod，不安装，不启动 HTTP/浏览器，不刷新模型目录或执行宿主 CLI。doctor 检查本组件完整性、依赖、来源与配置范围诊断。open 的启动锁等待、握手及子进程回收有界；复用须验证真实协议、版本、配置根身份与健康，不能只看 PID/端口。不同项目可复用同一配置根服务；版本不匹配不强杀正在保存的服务。

## 首次准备与分发

插件只包含轻量启动器及固定组件 descriptor，不包含 native_config、网页、独立 ZIP 或 MCP。组件安装在用户级独立版本目录，不在插件缓存或工作流源码中；不改 PATH、HOME、认证或客户端权限。

descriptor 使用 schema_version=1、product=native-agent-config、version、channel=alpha、cli_protocol=1、service_protocol=2、release_status，以及 artifact(name/sha256/url)。未发布时 url 为空、release_status=unpublished，不能发起猜测地址的下载或宣称已发布。离线显式提供真实 ZIP 时也必须匹配 descriptor 已冻结的 SHA 和 BUILD 清单。

open 缺组件先返回 preparation_required，不自动安装。首次经用户确认后调用固定准备参数（如 --prepare），从真实发行包获取并校验外层 SHA、ZIP 路径/类型/大小和 BUILD 全闭包；暂存成功后原子登记。失败不破坏已有活动版本；已有服务的版本目录不覆盖、不自动删除或终止。

实施先用真实独立包和临时根验证闭环。组件代码冻结并获独立 QA 后，发布独立 alpha 资产，核对真实下载字节，再生成已发布 descriptor；随后构建插件新候选。沿用既有发布授权，不创建 stable、不合并 main、不替换业务项目 2.x。

## 必要验证

- 精确维护路由正负控，三端原生静态发现；十个总 Skill 中九个核心规则保持，维护入口不预载到 Worker。
- status/doctor 全路径无落盘、无启动；坏记录/版本/配置根冲突保持真实状态，且无令牌泄露。
- 浏览器 false/异常仍保留 ready 服务和可用私有入口；并发首次 open 只启动一个实例，超时回收仅本次子进程；原关闭/保存等待合同继续通过。
- 首次未确认零安装；真实独立 ZIP 离开源码后安装/启动/复用；摘要、版本、ZIP 路径、重复项、注册表篡改、并发准备负控。
- 插件在独立配置源码物理缺席时仍能离线构建；服务异常不影响普通业务工作流；网页仍用原预览/保存核心，不修改插件只读角色。
- 定向完成后集成 current 一次，独立 QA 后净源构建/实际 CI/下载附件及精确本机候选核对。

本轮仅增加入口与组件准备，不把现有用户级 Agent 列表冒充通用默认设置，也不宣称已解决全部平台的插件角色持久覆盖、模型因果、App GUI、活动任务跨插件更新或 Windows 验收。

## 阶段证据

P1 独立工具安全命令与原生命周期定向 35 项通过，唯一 Reviewer 的五路径源码及五节点补测通过。P3 作者五模块 64 项通过、一个既有 Codex 官方临时隔离限制 skip；同一 Reviewer 的三项实际三宿主载荷检查通过。静态投影和原生清单不代替后续模型前向路由记录。

P2 初审发现并保留两项 Important：版本目录已发布而 registry 发布失败时无法重试，以及 HTTP 持续滴入可越过外层下载预算。原作者改为完整核验精确残留版本后幂等补登记，并用剩余 socket 预算加本次下载 worker 的硬总预算监督连接、响应头、重定向和正文。作者修复后 26 项通过，原进程日志 `/private/tmp/awf-p2-freeze/p2-important-fixed-full.log`；旧冻结与失败证据保留，同一 Reviewer 已复核关闭两问题。

本轮构建、真实发行、净源 CI、宿主前向与精确安装结论按最终收据追加，不能把阶段通过扩展为已经发布或完整原生运行通过。

## 交付收据

首个净源提交为 `b43ebc4fb655c813d21054570d5db8855f07f362`。本机 current 为 443 项、442 通过、一个既有 Codex 官方临时隔离限制跳过；[该提交实际 CI](https://github.com/Geoege-xll/agent-workflow/actions/runs/43136571691) 的 macOS、Linux 各 443 项、439 通过、四项跳过，分别为三个 CI 未安装 Claude CLI 的原生检查及一个 Codex 隔离限制。两平台验证和候选构建均成功；下载七个真实 CI 附件后，逐包 SHA 与独立 QA 审核包一致。

独立组件已发布为 [Native Agent Config 0.1.0-alpha.3](https://github.com/Geoege-xll/agent-workflow/releases/tag/native-agent-config-v0.1.0-alpha.3)，target 为上述净源提交，标记 prerelease 且不设为 latest。ZIP 为 86,481 字节，SHA-256 为 `74d015e0c005c980694acf09985345ae342c15ffc3ff8b448b1cb406843181dd`。发行描述由工具实际下载同一公开资产、核验 SHA 与 BUILD 后生成 published；这项独立组件预发行不代表工作流插件已进入公开市场或稳定发行。

原作者在显式临时组件根验证真实公开下载及首次准备：未确认的 open 零安装；准备后服务就绪，第二次 open 复用同一进程、实例及 URL；status/doctor 不改变文件字节、权限、inode、mtime 或服务进程；doctor 核验发行完整性通过。网页 GET 返回 200，内容摘要与包内资源一致，没有保存配置。通过正式 SIGTERM 生命周期关闭本次自有服务后，连接记录移除、进程为零，后续只读检查返回 stopped。安全报告位于 `/private/tmp/awf-config-entry-remote/`，交由同一 Reviewer 独立复核，不冒充完整 UI 操作验收。

AGY 初次官方 strict 校验识别十个 Skill、七个 Agent 和一个 Rule，alpha.4 安装文件全等；该阶段真实模型前向停在新临时目录信任确认。自动审批拒绝授予整个目录的读、写、执行信任，理由是超出当时精确只读命令测试范围；未绕过该信任门，未执行 launcher，业务负控也未启动。该阶段测试结束官方停用，其他插件保留，自有进程为零。这个初次 blocked 结果作为历史保留，不能由静态校验推导通过。

published 描述对应的净源为 `489b99a2630a10822760cdd123932d3e51b20e7f`，[该提交的实际 CI](https://github.com/Geoege-xll/agent-workflow/actions/runs/43137630707) 两平台验证与候选构建均成功。两端仍各 443 项、439 通过、四个已知跳过；实际下载的七 ZIP、sidecar、总 SHA 和 manifest 与本机净源候选一致。此结果只属于该提交，不代替后续两份路径澄清文本的新净源验证。

Codex、Claude 的四项实际路由观察已由同一 Reviewer 独立审查：两个显式正向真实执行固定 status，得到 preparation_required 并完成回合，没有读取业务 WORKFLOW、创建任务图、派发子代理或修改项目；两个业务负控真实读取原业务权威、没有执行维护启动器，但完整方案均在 90 秒预算内未结束。Claude 负控出现连接拒绝重试；其正向提交至 Stop 为 32.748 秒，118.69 秒进程总时长包含首次正式信任等待，不能混为模型耗时。安全收据位于 `/private/tmp/awf-config-entry-forward/summary.json`。

Codex 的 161 文件实际安装载荷与上述净源候选全等，Hook 已通过官方逐项复审及 trusted 查询；用户级停用，仅本轮临时 Codex 项目启用，旧 App 临时项目停用，原用户 Hook 保留。Claude 的结论限临时 plugin-dir 加载与官方 validator/inventory，没有新建持久用户级安装。Claude manifest 校验成功，但公开目录检查仍有 LICENSE_MISSING blocking/error、ICON_MISSING 非阻断 warning 和 README 安装行建议；公开目录上架尚未就绪，未推定或添加 LICENSE/SPDX。

## AGY 授权补测与路径澄清

用户随后单独批准两个测试目录的官方读、写、执行信任：`/private/tmp/awf-config-entry-forward/agy/explicit-status-project` 与 `/private/tmp/awf-config-entry-forward/agy/business-negative-project`。权限不扩展到业务项目或全局策略。官方 CLI 在实际启动时自动升级至 1.5.6，后续只读 strict 仍为十 Skill、七 Agent、一个 Rule。

首次授权正向确实读取维护 Skill，并执行唯一固定 status，但省略本地项目参数，回执为 antigravity/global/project=null。启动 cwd、官方信任目录和 UI cwd 一致，尚无结构化证据证明模型实际收到本地 workspace 字段，因此不能直接认定模型忽略了可见项目。该次 Bash completed 距起点 97 秒，超过事前 90 秒预算；159 秒仅为人工 ESC 后观察最终 ready 的窗口，没有官方 Done 时间戳。记录为验收控制失误，不计合格 PASS；该次已正常退出、官方停用，自有 CLI/服务为零，两个目录及维护目录未改动。

针对已确认的文字歧义，仅澄清 `plugins/main-session-context.md` 与维护 Skill：相对插件根解析的是插件资源，本地项目物理目录独立来自宿主实际 session/workspace；已知唯一目录必须传 `--project`，没有明确目录才使用用户级。AGY CLI 的项目 ID/name 与配置工具所需的本地目录分属两层，不推导文件路径。[官方项目说明](https://antigravity.google/docs/projects/)及[命令参考](https://antigravity.google/docs/cli/reference/)支持这一区分。未增加 cwd 探针、隐式 PWD 推断、元数据解析器、关键词分流或宽权限。作者沿用三端实际构建与维护/业务合同，22 项通过；同一 Reviewer 复核源码及七包投影通过，native 已发布包字节保持不变。

新的两项 AGY 测试事前采用原生 `--add-dir` 将已授权目录明确注册到 workspace，纯用户提示不注入预期行为；信任与模型计时分开，正向 180 秒硬预算、负控 90 秒硬预算。独立 PTY 父控制器在同一操作中启动单调时钟并提交提示，预算前分阶段中断、终止及回收本次自有进程组；本地无网络定时自检和同一 Reviewer 的控制器审查通过。原无效用例不改记。

正向在 130.015 秒观察到 native-ready 上界，130.785 秒正常退出并回收，处于 180 秒预算内。公开工具记录中的实际固定 status 命令带正确的 approved 项目物理路径；没有业务 WORKFLOW 读取、代理派发或写入。原生工具 JSON 在 TUI 中折叠，当时的 `location` 字段未直接取得，不以助手摘要冒充工具证据。另一次明确分栏的非模型 direct_readonly_replay 使用同一实际 argv，只读返回 exit 2、preparation_required、antigravity/project/正确目录，browser 为 not_requested，service 为 unknown，无 URL 或链接文件；它不补造历史模型工具响应。

业务负控的初始 90 秒阶段只完成只读目录检查，85.915 秒正常退出；没有维护命令执行，但尚未到达完整业务讨论。随后从该次官方退出提示精确确认自有会话 ID，在同一会话、同一批准目录和同一载荷下，仅发“继续刚才的只读讨论”，单次 300 秒硬预算续跑；没有扫描他人会话或注入预期工作流路径。续跑于 262.420 秒观察到 ready 上界，263.310 秒正常退出，形成实现与边界讨论。公共工具记录包括 README、插件目录、AGY 业务适配和作为源码参考的维护 Skill 读取；维护启动器、Agent 和写工具均为零。初始未完成结果与续跑结果分别保留，不改写为一次 90 秒通过。

该精确负控会话是否原生提供了完整 `xy-workflow` 正文和本次讨论所需产品权威，仍未获可靠时点证据。仅发现名称/路径不能当正文已加载，公共 Read 缺失也不能排除宿主原生提供或同实例复用。源码确认短规则未内联业务全文，独立 WORKFLOW 为 129,121 字节；不把全篇强塞进 always-on rule，也不要求每轮重复全文读取。停用后重新打开当前 context 快照不足以证明历史，故未重新注入规则补证。结论限维护命令参数及维护执行隔离的实际观察，不扩展为完整 AGY 业务 bootstrap、完整 UI 或整体 runtime PASS。

AGY 最终官方停用，其他插件保持原状，两个批准目录逐文件无新增、删除或修改，组件/服务目录未变，本次 CLI、控制器及配置服务进程均为零。scope-review 两份文案也已通过 Codex 官方精确同步与 Hook 复审，161 文件全等，新 Hook 查询为 trusted；全局停用、原临时项目启用、旧 App 临时项目停用。Claude 168 文件清单与 manifest 校验通过，公开目录许可证阻断保留，没有新增模型用例。后续净源构建须核已安装载荷与最终 ZIP 字节相同，不能用旧 dirty 来源代替最终提交的 CI。
