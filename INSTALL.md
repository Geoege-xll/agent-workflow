# 安装 xy-workflow 正式插件

插件唯一版本源为 `product/PLUGIN_VERSION`，独立配置工具版本源为 `native_config/VERSION`；实际发行以 Git stable 分支和真实 Release 资产为准，独立组件固定发行与发布状态以 `plugins/maintenance/component.json` 为准，本机安装状态以客户端列表和实际安装回执为准。默认使用官方客户端从自有 Git stable 渠道安装，无需克隆工作流源码或本地构建。自有 Git 正式渠道不等于官方公开目录上架，Windows 暂停。工作方式见[使用手册](https://github.com/Geoege-xll/agent-workflow/blob/main/docs/usage.md)，载荷合同见[PLUGIN](PLUGIN.md)。

本页 `xy-workflow` 身份由 `product/command_identity.json` 唯一维护；使用下列命令时核对匹配的远程分发资产与客户端回执，
不能仅凭源码版本或命令说明判断本机已经切换。活动任务使用原物理资源完成后再按官方客户端切换。

## 前置条件

已有对应宿主的官方客户端、Python 3.11+ 和 Bash。helper 使用包内解释器选择器发现现有 Python，不安装软件或改变 PATH。模型运行需完成宿主登录与实际权限确认；普通工作流不要求配置组件、配置 HTTP 服务或 MCP。

以下命令只管理对应客户端当前安装范围，不自动替换其他用户、业务项目或旧来源。Codex/Claude 的正式远程市场名为 `xy-workflow`，插件名为 `xy-workflow`。三个 Git 分支分别提供对应宿主的已构建载荷，不要使用 main 源码目录充当插件来源。

## 随包精选 Skill

新机器安装本插件时一起获得原版 Grill Me、唯一必要primitive grilling、Taste，以及官方
Playwright CLI与其完整Skill；公开入口统一 `xy-grill-me`、`xy-grilling`、`xy-taste`、
`xy-playwright`，配置入口为 `xy-config`。无需逐个安装全局Skill或完整上游plugin。
固定来源、commit/发布版本、inventory、LICENSE、NOTICE和资产credit位于当前包的
`third_party/selected-skills.lock.json` 及 `third_party/selected-skills/`；构建只消费本地锁定资源。

从官方客户端取得实际插件物理目录后，可只读区分资源齐备与现有运行环境：

```text
bash <plugin-root>/lib/python_runtime.sh -B -X utf8 <plugin-root>/plugins/source_pack.py selected-skills check
bash <plugin-root>/lib/python_runtime.sh -B -X utf8 <plugin-root>/plugins/source_pack.py selected-skills diagnose
```

check 成功只证明资源锁匹配；diagnose 检查已有 Node >=22、浏览器与可选 ffmpeg，不安装软件，
不执行 Taste 脚本。设计方法读取与 Taste 完整脚本/gate 运行分别判断；默认原型仍静态验收且
不截图，不注册上游 Stop hook。实际 Skill 调用、全文阅读和宿主运行需要本次会话证据。
PM 自动通过同包 `xy-grilling` 加载原版，`xy-grill-me` 仅用户显式；不会因安装而默认启用其它上游工作流。

Playwright只读诊断入口为：

```text
bash <plugin-root>/lib/python_runtime.sh -B -X utf8 <plugin-root>/plugins/source_pack.py xy-playwright -- doctor
```

doctor是本项目诊断，不是上游CLI命令。CLI原版固定版本与Node>=20、匹配浏览器分别诊断；
三份发布包不含浏览器可执行文件。缺少浏览器且已有准备授权时，按adapter通过固定官方
`install-browser chromium` 和宿主审批准备，复用官方缓存、不改PATH、不清理旧版本缓存。
资源齐全、版本输出及静态doctor均不等于真实open/snapshot/close通过。所有公开别名/namespace
以 `product/command_identity.json` 为唯一命名权威；当前插件 `xy-workflow`、市场
`xy-workflow`（stable）、`xy-workflow-alpha`（历史预发行）／`xy-workflow-local`，GitHub仓库地址和宿主分发分支保留。

## Codex CLI

```bash
codex plugin marketplace add https://github.com/Geoege-xll/agent-workflow.git --ref plugins-codex-stable
codex plugin add xy-workflow@xy-workflow
codex plugin list --json
```

安装后在官方 `/hooks` 中审阅并信任当前 SessionStart 定义，再开始新会话。安装或启用不授予 Hook 信任，不直接写 trust 记录，不以全局或项目指令文件替代官方审阅。候选保留单一 `.codex-plugin/plugin.json` 清单，避免已发现的 portable 根清单漏载 Hook 问题。

## Claude Code

```bash
claude plugin marketplace add 'https://github.com/Geoege-xll/agent-workflow.git#plugins-claude-stable'
claude plugin install xy-workflow@xy-workflow --scope user
claude plugin list --json
```

安装后开始新会话。插件主会话默认 PM 低于用户自有默认设置优先级；发现插件不证明模型已经接管。

## Antigravity CLI

```bash
agy plugin install https://github.com/Geoege-xll/agent-workflow/tree/plugins-antigravity-stable
agy plugin enable xy-workflow
agy plugin list --json
```

AGY 使用 GitHub `tree/分支` URL，不能使用 Claude 的 `#分支` 写法。严格校验与构建继续保护每个 Skill 正文的 24,000 字节上限。安装、登录、模型执行分别判定。

## 检查安装与来源

先通过客户端官方列表确认实际 installed/enabled 状态、版本、来源及安装范围；不同客户端暴露字段不同，缺失项保持未知，不根据缓存存在补写成功。Codex/Claude 可进一步查看其官方 marketplace 列表，核对 `xy-workflow` 指向本页对应分支。

需要只读资源健康检查时，从官方安装信息中取得当前实际插件物理目录，将下列 `<plugin-root>` 和 `<absolute-project>` 替换为明确路径：

```text
bash <plugin-root>/lib/python_runtime.sh -B -X utf8 <plugin-root>/plugins/source_pack.py resource .agent-workflow/product/WORKFLOW.md
bash <plugin-root>/lib/python_runtime.sh -B -X utf8 <plugin-root>/plugins/source_pack.py helper --project <absolute-project> plugins/project_context.py inspect
```

resource 检查打包权威路径与摘要；inspect 检查明确项目及 adapter，不创建文件、不改配置、不启动模型或配置服务。资源可读、安装成功和状态列表均不代表新会话实际进入 PM，默认 PM 与原生子代理运行需要独立的真实宿主证据。

## 更新、旧来源与卸载

先收尾或交接活动任务，再更新插件；当前插件没有活动任务跨缓存更新的自动资源保留协议。保留官方登录、权限和 Hook 信任流程，更新后检查实际来源、版本、启用状态并开始新会话。

- Codex：`codex plugin marketplace upgrade xy-workflow` 刷新 Git 市场快照。该命令的帮助只承诺刷新来源，不据此宣布已安装插件更新完成；随后检查 `codex plugin list --json`，按当前客户端提供的插件安装/更新流程处理实际版本。不要编造 `codex plugin update`。
- Claude：先执行 `claude plugin marketplace update xy-workflow` 刷新目录，再执行 `claude plugin update xy-workflow@xy-workflow --scope user` 更新已安装插件；完成后重启会话。市场刷新与插件更新是不同操作。
- AGY：本机 1.5.6 的 `agy plugin` 帮助没有 `update` 子命令。通过官方插件管理确认来源和版本，按客户端实际提供的安装/替换流程处理相同 Git 目标；不承诺重新执行 install 会热更新活动会话。

旧 `xy-workflow-local` 是开发本地来源，与远程 stable／历史 alpha 不是同一市场。已有 alpha.4 测试安装不会自动迁移；先在官方客户端确认旧来源与范围，停用旧候选或按其卸载流程移除，再启用所选 stable 来源，避免两个同名插件同时生效。不要删除共享用户 Hook、改写信任记录或批量清理其他项目。

停用与卸载使用各官方客户端的插件管理；Codex 提供 `plugin remove` 和 `plugin marketplace remove`，Claude 提供 `plugin disable/uninstall` 和 `plugin marketplace remove`，AGY 提供 `plugin disable/uninstall`。移除市场来源与卸载插件不是同一行为，按实际来源/范围确认后操作，不手工删客户端缓存当作卸载。

## 当前验收边界

历史远程 alpha 的 CI、发布、安装和发现以[远程安装记录](https://github.com/Geoege-xll/agent-workflow/blob/main/docs/plans/plugin-remote-install.md)为准，未先行声明三平台真实模型运行通过。上一 alpha.4 本机记录为：三端本地安装通过，Codex CLI 新插件启动通过；Claude 默认模型在 90 秒预算内未回应，PM 接管未验；AGY 后续模型运行待登录；Codex App GUI 未验。更早实验见[原生验收记录](https://github.com/Geoege-xll/agent-workflow/blob/main/docs/plans/plugin-v3-native-acceptance.md)。

自有 Git 分发不绕过许可证、官方公开目录审核或客户端信任。正式版本及三端 stable 分支必须在实际发布后才可安装；历史 alpha 分支保留审计，不能替代当前正式入口；源码构建与临时本地加载见[开发手册](https://github.com/Geoege-xll/agent-workflow/blob/main/docs/development.md)。

## 安装后的模型配置入口

维护 Skill 名为 `xy-config`，省略动作即 open。Claude 使用 `/xy-workflow:xy-config`；Codex 在原生 `/skills` 或 `$` 选择器中选择实际发现的插件 Skill；AGY 当前载荷使用 `/xy-config`，以实际发现项为准。可加 `status` 或 `doctor` 只读检查。

平台由当前插件构建固定，项目来自会话明确的绝对目录；已知唯一项目必须传递，未明确项目才进入用户级。插件物理资源目录与本地项目目录分开，不能用 AGY 项目 ID/name 推导文件路径。

缺少独立组件时先报告准备信息，经用户确认才调用固定准备参数。组件来自已发布且实际核验的独立发行包，安装到用户级版本目录；插件只包含薄入口，不夹带核心、网页、组件 ZIP 或 MCP。显式离线包也必须匹配固定摘要。服务与浏览器分别报告状态，浏览器失败保留 ready 服务及私有打开入口。

status/doctor 不准备组件、创建连接或权限记录，不启动 HTTP、浏览器或模型查询。普通业务无需组件或 MCP；显式维护不读取整份 WORKFLOW、不建业务任务图或派发子代理。插件缓存角色只读，各平台可写原生字段和覆盖范围见[原生配置说明](https://github.com/Geoege-xll/agent-workflow/blob/main/docs/agent-configuration.md)。

既有组件功能提供本机模型目录、用户／项目调用偏好和工作流项目启停；准确发行状态以 Release 资产与固定描述为准，不从源码版本推断已经安装。配置页默认进入“调用偏好”，原生定义文件为独立模式；Codex 零原生文件或 Claude 仅有只读插件角色时仍有通用偏好入口。纯只读解析器随插件交付，不需要常驻配置服务。

组件首次准备仍须单独确认，并只采用实际下载核验的固定地址与摘要。它不代表工作流已上架公开目录或成为稳定发行；停用后的独立恢复、字段支持和实际运行边界见[配置工具说明](https://github.com/Geoege-xll/agent-workflow/blob/main/docs/agent-configuration.md)。
