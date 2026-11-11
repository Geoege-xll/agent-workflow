# Agent Workflow Pack 2.1

面向项目的原生多 Agent 工作流，支持 **Claude Code、Codex、Antigravity**。
当前源码版本为 **2.1.4**，唯一版本源为 `product/VERSION`；源码版本不代表公开渠道已发布该版本。
公共版本与资产以 [GitHub Releases](https://github.com/Geoege-xll/agent-workflow/releases) 和 Tap 声明为准。
本轮补充三平台主会话 PM 持续接单与跨请求资源准入，暂停需求／计划 HTML 生成并保留 Markdown、历史页面和渲染源码。
原生 Windows 候选已接入共享服务；实际验收边界及入口见[使用手册](docs/usage.md#原生-windows-入口)。

在 macOS/Linux 使用中央程序管理已有项目：项目仅保留配置、薄桥和宿主原生入口，
内置 Skill 软链到不可变中央核心，已有任务继续使用自己的固定版本。
2.1 仅接受 Light／Full 与 schema 2 任务／交接格式，不提供旧版本兼容升级。

## 快速开始

通过 Homebrew 安装 Tap 当前声明的版本：

```bash
brew install Geoege-xll/tap/awf-cli
awf-cli
```

Homebrew 已管理短命令，无需再注册 `--install-cli`。安装、升级与来源排查见
[Homebrew 说明](docs/homebrew.md)。升级中央程序、导入不可变核心和激活中央 current 是三个独立动作。首次使用先 `runtime install`、
`runtime activate CONTENT_ID`，再启用项目；日常用法见使用手册。

macOS/Linux 已有源包也可直接启动；需要现有 **Python 3.11+**，不安装 Python 包或下载运行时：

```bash
# 选择已有项目；也可省略路径，在提示后拖入项目目录。
bash /path/to/agent_workflow/install.sh /path/to/project
# 从任意目录启动管理器。
bash /path/to/agent_workflow/workflow.sh
# 可选：注册到 ~/.local/bin，不修改 PATH 或 shell 配置。
bash /path/to/agent_workflow/workflow.sh --install-cli
# 源码默认注册 awf-dev，与 Homebrew 的 awf-cli 并存。
awf-dev --version
```

安装先执行只读发现和预检，保留项目专属配置及已有非空文档；未知受管修改会停止覆盖。
中央项目后续使用 `awf-cli check --project /path/to/project` 检查，使用
`awf-cli repair /path/to/project --dry-run` 预览修复。根 `setup_*.sh` 是源包开发生成器，
普通项目通过 `install.sh` 或 `awf-cli` 管理。

## 阅读入口

| 需要做什么 | 文档 |
| --- | --- |
| 登记／启停项目、固定版本、模型配置、TUI 键位、失败恢复 | [使用手册](docs/usage.md) |
| 源码结构、开发生成器、验证范围、文档归属与历史保留 | [开发手册](docs/development.md) |
| Homebrew 来源诊断、离线发行构建与发布边界 | [Homebrew 说明](docs/homebrew.md) |
| 查询工作流规则权威 | [产品工作流](product/WORKFLOW.md) 与 [工作流 Skill](platforms/shared/skills/xy-workflow/SKILL.md) |

Windows 目标为 **Windows 11 x64、PowerShell 7+、CPython 3.11+、本地 NTFS**；使用同一发行归档中的
Python／PowerShell／cmd 原生入口，TUI 另需锁定的 `windows-curses==2.4.2`。受管 Skill 需要实际软链权限。
Windows Server 原生检查与 Win11 普通用户桌面验收分别记录；当前 Win11 桌面与 Codex App 原生会话／CUA
仍未验收，不能把载荷存在或 Server 检查当作全平台通过。未发布的 npm／npx 渠道保持移除。Windows 新候选提供 curl 下载引导与私有环境安装，目标资产、前置和验收边界见[使用手册](docs/usage.md#curl-下载与中央安装候选入口)。
完整支持与恢复边界见[使用手册](docs/usage.md#支持范围与安装保护)。
