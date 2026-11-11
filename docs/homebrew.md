# 2.x Homebrew 历史渠道与现有安装维护

本页用于识别和维护已有的 2.x 安装。当前 3.0 工作流采用官方插件，原生 Agent 配置工具独立交付；入口见[插件说明](plugin-v3.md)和[配置工具说明](agent-configuration.md)。本轮源码清理不卸载或修改用户已安装的 Tap 程序、中央状态及业务项目。

## 核对现有来源

源码仓库为 [agent-workflow](https://github.com/Geoege-xll/agent-workflow)，历史 Tap 为 `Geoege-xll/homebrew-tap`，Formula 名称为 `Geoege-xll/tap/awf-cli`。公开版本与资产分别以 [GitHub Releases](https://github.com/Geoege-xll/agent-workflow/releases) 和 Tap 中的声明为准；当前开发候选不代表这些渠道已经发布相应版本。

现有用户可只读核对：

```bash
type -a awf-cli
awf-cli --version
brew list --versions awf-cli
```

Homebrew 管理的命令和源码注册命令应按物理来源区分。来源不明时先查入口和已安装版本，沿用[2.x 使用手册](usage.md)中的检查、事务恢复与固定任务保护规则。CLI 版本、磁盘文件和配置校验不证明宿主会话已经加载或按指定模型运行。

## 历史发行来源

2.x 的发行与 Formula 构建应使用对应历史源版本。[保全基线中的完整发行说明](https://github.com/Geoege-xll/agent-workflow/blob/de847fd6e10de5b31d04591b4fe596808ae8fa1d/docs/homebrew.md)保留归档、解释器包装、校验、Tap 发布及已有安装恢复边界。

3.0 开发源码已退役 `packaging/build_release.py`、旧 Formula 模板和专属归档测试。当前主 README 与手册围绕两个独立产品维护，候选分别使用官方插件构建器和原生配置构建器。新的构建入口、输出与原生验收限制见[3.0 插件说明](plugin-v3.md)。

计划 HTML 生成器和专用 vendor 同时退役，计划以 Markdown 交付。原型设计、原型 HTML、原型验收、视觉确认和已有历史计划页面保留。公开旧 Formula 仍可能声明原来的运行依赖，源码退役不会自动重写已发布 Tap 或本机 Cellar。

已有 2.x 中央任务继续沿自己的安装和固定资源处理；3.0 的稳定发布、本机替换及旧启用面完整退役仍按实际验收结果推进。
