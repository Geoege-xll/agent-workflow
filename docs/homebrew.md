# Homebrew 安装与 2.1 发行构建

源码仓库：<https://github.com/Geoege-xll/agent-workflow>，公开 Tap 为
`Geoege-xll/homebrew-tap`，Formula 名称为 `Geoege-xll/tap/awf-cli`。
发行归档、校验文件与 Formula 来自同一次构建。Tap 使用对应 Release 的 Formula，
安装时核对归档 SHA-256；用已安装入口的 `--version` 核对实际版本和中央程序位置。

当前源码候选版本为 **2.1.1**，尚未发布；唯一人工维护值在 `product/VERSION`。
GitHub 已公开的版本与资产以 [Releases](https://github.com/Geoege-xll/agent-workflow/releases) 为准。
下面的公共安装命令只安装 Tap 已声明的版本；发布 GitHub Release 不会自动更新公共 Tap，
不能据此认定已经取得 2.1.1。

## 用户安装

按公共 Tap 当前声明的版本安装或升级：

```bash
brew install Geoege-xll/tap/awf-cli
awf-cli

brew update
brew upgrade Geoege-xll/tap/awf-cli
```

Homebrew 将完整程序装入当前版本的 `libexec`，并在 Homebrew 的 `bin` 中提供
`awf-cli`。Formula 声明 `python@3.14` 与 `node`（需求 HTML CLI，要求 >= 20）依赖；包装器仅为其子进程选择默认解释器，
不修改 PATH、CDPATH 或 shell 配置。非空的 `AGENT_WORKFLOW_PYTHON` 显式设置仍被保留：
相对解释器仍按调用目录解析，无效解释器仍报错，不自动回退。
现有 `workflow.sh`、共享 Python 选择器及项目安装编排均不改变。
同一运行时载荷包含 `lib/requirement_html.py`、原样 bundled CLI/许可证和
[需求 HTML 方法](../platforms/shared/skills/xy-plan/references/requirement-html.md)。它按需渲染，
setup 不启动渲染器；不需要全局 npm 安装，缺失 Node 只阻塞需要重新生成的需求页。

无需也不建议再运行 `awf-cli --install-cli`：Homebrew 已经管理命令入口，额外注册的
用户链接可能在升级后仍指向旧版本。以前安装过源包命令时，先只读检查：

```bash
type -a awf-cli
"$(brew --prefix)/bin/awf-cli" --version
brew list --versions awf-cli
```

如果旧的 `~/.local/bin/awf-cli` 优先，核对后自行决定是否移除旧链接；不要自动覆盖，
也不要使用 `brew link --overwrite` 解决来源不明的同名入口。本方案不安装或调整
Homebrew 自身；若 Homebrew 的 `bin` 不在现有 PATH，使用以上完整路径启动。

`--version` 不启动 TUI、不读取模型来源，也不创建管理状态。源码入口读取 `product/VERSION`，
明确显示源码身份；构建发行载荷使用与该值一致的生成元数据，并显示物理载荷根。
发行元数据仅写入归档中的 `manager/release.json`，随 Formula 复制到 `libexec`，源码不保留发行标记。
源码、归档与 Cellar 的中央源根可以据此直接比较。

`brew upgrade` 只采用 Tap 已声明的版本；GitHub 上另有较新的 Release 或本地候选，不会让旧 Formula 自动升级。

`brew upgrade` 只更新中央程序，不自动安装、选版或同步任何项目。项目使用 `add` / `list` /
`del` / `open` / `close` 及 `use` / `rollback` / `repair` 管理，写入前可用 `--dry-run` 预览。
2.1 采用普通中央安装，不提供旧版本兼容升级；旧工作流须在任务收尾和文档、专有配置保全后，
按明确受管归属单独移除，再运行 `open`。`brew uninstall awf-cli` 不删除项目内工作流、
项目配置或 `~/.config/agent-workflow` 中的用户数据。

## 本地构建（不联网、不安装、不发布）

在源码根目录使用现有 Python 选择器；构建版本必须与 `product/VERSION` 一致：

```bash
bash lib/python_runtime.sh -I -B -X utf8 packaging/build_release.py 2.1.1
```

生成：

- `dist/agent-workflow-2.1.1.tar.gz`
- `dist/agent-workflow-2.1.1.tar.gz.sha256`
- `dist/Formula/awf-cli.rb`

发行包使用运行所需文件/目录白名单，不包含 `.sync-backups`、Git 元数据、发行输出、
测试、发布工具或 Python 缓存。存在的根目录许可证会一并打包，但构建器不替作者选择
或生成许可证。仓库首次公开发布前，请自行确定代码授权方式。

归档固定排序、时间戳、所有者及权限；在源内容/可执行位及工具链一致时，重复构建得到
相同字节。Formula 的 URL 指向同一版本的 **Release 资产**，SHA-256 来自本次构建的
确切压缩包，不能改用 GitHub 自动生成的 Source code 压缩包。
已有输出一律保留，重建请用新的空目录：

```bash
bash lib/python_runtime.sh -I -B -X utf8 packaging/build_release.py 2.1.1 --output-dir /path/to/new-output
```

离线测试在独立临时目录中验证发行包及实际 Formula 的安装方法、模拟 Cellar 启动器、
路径含空格、相对项目参数、CDPATH/PATH 保留和显式解释器约束；测试不改 PATH、
不运行 `brew install`、不操作真实项目。模拟安装不等于真实 Homebrew 验收。
生成 Formula 的测试还会通过安装后的入口核对 `--version` 与 `libexec`，不只检查 Formula 的版本字符串。

## 发布边界

所有创建远端仓库、上传代码、发布资产和推送 Tap 的操作均需明确确认后执行。
本地构建器不执行这些操作；当前源包也不自动初始化 Git 或同步项目。

1. 核对源码上传清单和授权方式，将审阅过的源文件推送到
   `Geoege-xll/agent-workflow`。`.gitignore` 排除本地备份、缓存及 `dist/`。
2. 在源码仓库的 **Actions → Prepare release → Run workflow** 输入与 `product/VERSION` 一致的版本 `2.1.1`
   （不带 `v`），并选择希望发布的分支。工作流先运行离线打包测试，再构建三份产物，
   然后创建 **Draft Release**；它不会自动公开 Release，也不会推送 Tap。
3. 核对 Draft 的目标提交、压缩包、校验文件和 `awf-cli.rb` 后，再手动发布 Release。
   同名标签若指向另一个提交则拒绝，已有 Release/资产也不会自动替换。
4. 确认后创建公开仓库 `Geoege-xll/homebrew-tap`。从该 Release 下载
   `awf-cli.rb`，将其作为 Tap 仓库的 `Formula/awf-cli.rb` 提交并推送。
   应使用该 Release 同一次构建的 Formula，不混用其他本地构建的校验值。
5. 在获准的机器上完成真实安装验收：

   ```bash
   brew install --build-from-source Geoege-xll/tap/awf-cli
   brew test Geoege-xll/tap/awf-cli
   "$(brew --prefix)/bin/awf-cli" --help
   ```

工作流仅使用当前仓库的 `GITHUB_TOKEN` 创建草稿，权限限制为该发布任务的
`contents: write`；无需提供能写其他仓库的个人令牌。GitHub Actions 固定到不可变提交。

## 后续中央程序版本

对新的源代码提交先更新唯一版本源，再手动运行相同工作流并输入一致的未使用版本，审核并
公开 Release，再将该版本附带的 Formula 更新到 Tap。用户随后运行 `brew update`
及 `brew upgrade` 即可。不要覆盖同版本 Release 资产：旧 Formula 的校验值和已安装
版本应继续对应原发行包；需要修正时发布新版本。
