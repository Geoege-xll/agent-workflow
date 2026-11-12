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

AGY 官方 strict 校验识别十个 Skill、七个 Agent 和一个 Rule，alpha.4 安装文件全等；真实模型前向停在新临时目录信任确认。自动审批拒绝授予整个目录的读、写、执行信任，理由是超出本次精确只读命令测试范围；未绕过该信任门，未执行 launcher，业务负控也未启动。测试结束官方停用，其他插件保留，自有进程为零。因此 AGY 本轮实际维护路由仍为 blocked，不能由静态校验推导通过。

Codex 实际正向已使用原生发现的维护 Skill 调用固定 status 启动器，未读取业务 WORKFLOW、创建任务图或派发子代理。其余前向结果、最终 published 描述候选及精确安装仍须以同一轮最终收据为准；本段中的首个 CI 不是后续元数据差量提交的 CI 结果。
