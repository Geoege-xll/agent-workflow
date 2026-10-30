# Windows npx 项目安装（本地、未发布）

目标是在 **Windows 10/11 x64、本地 NTFS、普通用户**环境，从项目目录安装现有工作流，
不是安装 Windows 管理器。当前 npm 包是 `@geoege-xll/agent-workflow` 的本地 `0.1.0`
准备版本，`private: true`，**尚未发布，也尚未完成原生 Windows 安全/恢复与端到端验收**。
macOS 上的打包和模拟测试通过，不能视为 Windows 已支持。

未来通过完整验收并获准公开发布后，拟用命令才是：

```powershell
# 未来发布后的用法；现在不要把它当成已可用的远程包。
cd C:\work\my-project
npx @geoege-xll/agent-workflow init
```

本阶段只构建本地 tgz，并在独立临时项目中验证；不上传、发布或同步真实项目。

## 前置条件与范围

- 使用 Windows x64 版 Node.js LTS/npm（包声明 Node.js >= 22）。
- 预先安装完整 **Git for Windows**，包括 `bash.exe`、`git.exe` 和 `usr\bin` 工具集。
  不依赖 WSL，不接受 `C:\Windows\System32\bash.exe` 或单独复制的 Bash。
  Git 不在 PATH 时，会检查标准安装目录、现有 PATH 中的 Git 目录及 Git 安装注册信息；
  不自动安装 Git、不修改 PATH。
- 不必预装 Python。完整 tgz 内已包含锁定的官方 CPython x64 嵌入式运行时；
  首次 `init` 不下载 Python，也没有联网 `postinstall`。
- `init` 只面向 Windows x64；macOS/Linux/Windows ARM64 的 `init` 明确拒绝。
  `node npm/bin/agent-workflow.cjs --help`、版本和便携单元测试可以在其他平台运行。
- 不包含 manager/TUI、WinGet、独立 EXE 或 PowerShell 安装器。

工具不调整用户/系统环境变量、shell/profile、ExecutionPolicy、Git 全局配置或宿主信任。
如 PowerShell 的 npm `.ps1` shim 被策略拦截，请使用 `npx.cmd` / `npm.cmd`，不要降低执行策略。

## 本地 tgz 的临时项目验证

先按下一节在源码之外准备完整包。以下路径是假定的本地构建输出，不是网络发布地址：

```powershell
# 只进入一个专门创建的临时测试项目，不操作真实项目。
cd 'C:\awf-test\临时项目 with spaces'
npx.cmd --offline --ignore-scripts --package 'C:\awf-build\tgz\geoege-xll-agent-workflow-0.1.0.tgz' agent-workflow --help
npx.cmd --offline --ignore-scripts --package 'C:\awf-build\tgz\geoege-xll-agent-workflow-0.1.0.tgz' agent-workflow init
```

完整包在本地可取得时，`--offline --ignore-scripts` 不影响首次运行时部署。
没有下载钩子、安装钩子或 npm 运行时依赖。不要直接把只含入口源码的 `npm/` 当成完整发行包。

入口仅接受：

```text
agent-workflow
agent-workflow --help
agent-workflow --version
agent-workflow init [--project PATH] [--timeout SECONDS]
```

无参数只显示帮助；帮助/版本不检查项目、不部署 Python、不写文件。
`init` 的默认项目是 **调用命令时的 cwd**，不是 npm 缓存、包目录或 npm 的 `INIT_CWD`。
`--project` 的相对路径也以该 cwd 解析，目录必须已存在；含空格或中文的路径须正常引用。
未知参数、重复参数、非有限/非正数 timeout 会在部署前报错。参数使用数组与
`shell: false` 传递，不拼接成 shell 命令。

```powershell
# 使用已缓存的同一个本地包入口时，也可显式选择其他临时目录。
npx.cmd --offline --ignore-scripts --package 'C:\awf-build\tgz\geoege-xll-agent-workflow-0.1.0.tgz' agent-workflow init --project '..\另一个临时项目' --timeout 120
```

`--timeout` 交给 Python 安装事务处理，不是 Node 强杀计时器。Ctrl+C 会通知受控 Python
停止写者并恢复，入口等待清理/恢复后退出，不对正在恢复的安装器调用 `child.kill()`。
请保留终端，等待恢复结束；恢复有独立预算，可能超过安装 timeout。
helper 必须返回持久私有控制目录下的绝对 `cancel` 路径；缺失或仍位于包缓存中的取消通道会阻止安装。

## Python 与 Git 的显式选择

通常无须设置。需要时，由调用者在自己的当前会话中显式提供：

- `AGENT_WORKFLOW_PYTHON`：Python 可执行文件路径，必须能以隔离模式运行且版本 >= 3.11。
  相对路径先锚定到调用 cwd；空值、缺失文件、版本过旧或探测失败均直接报错，**不回退**。
  Node 入口在部署前只探测一次显式解释器；部署 helper 仍始终使用包内 Python。
  后续原有宿主 setup 启动的独立 Bash 进程仍各自校验所选解释器，不代表整次安装仅有一次版本探测。
- `AGENT_WORKFLOW_BASH`：完整 Git for Windows 的 `bin\bash.exe` 或 `usr\bin\bash.exe`。
  相对路径同样锚定到调用 cwd；显式无效时不继续搜索其他安装。

安装器只把已经验证的绝对解释器、Git Bash 和稳定 bootstrap/control 路径放入受控子进程
环境，不修改调用者环境，也不添加 PATH。宿主自身的批准/信任步骤仍由用户完成。

## 持久运行时与重复 init

首次 `init` 完成平台、项目、Git、包完整性及显式解释器预检后，由可信 Windows helper
验证整个运行时并部署到系统已知的 LocalAppData 下：

```text
%LOCALAPPDATA%\AgentWorkflow\runtimes\cpython-<精确版本>-x64-<载荷摘要>\
```

目录摘要来自规范化 JSON manifest。`manifest.json` 覆盖解释器、stdlib ZIP、DLL、
上游许可及 `windows_bootstrap.py`、`windows_fs.py`、`windows_runtime.py`，唯独不自哈希。
保留官方 `_pth` 的 stdlib ZIP 与运行时根目录项，不导入任意 cwd 或全局 PYTHONPATH。
bootstrap 及其部署依赖不留在 npx 缓存；项目运行辅助命令和 Hook 不应引用 npm 暂存目录。

运行时按内容不可变发布；同一运行时可复用，新版可以并存。不自动删除旧版，因为其他项目
可能仍引用它。来源未知或损坏的目录不会被自动覆盖/修复。项目安装失败可以保留已经验证的
运行时。取消控制目录仅由可信 helper 回收，不让 Node 对 helper 返回的目录递归删除。

项目安装复用 `lib/install_workflow.py`，将受管内容放入项目 `.agent-workflow`，保留
`project.yaml` 的用户配置。重复 `init` 是显式升级操作；未知同名内容或用户改过的受管文件
会报冲突，而不是直接覆盖。删除 npx 缓存不等于卸载项目或持久 Python；不提供自动全局清理。

## 安装后的原生辅助命令

在 PowerShell/cmd 中，工作流 Python CLI 使用项目内 Node helper，不要求 `bash` 或 Python
出现在全局 PATH，也不依赖已删除的 npx 缓存：

```powershell
node .agent-workflow/lib/python_runtime.cjs -X utf8 .agent-workflow/lib/project_profile_cli.py check-roles codex .agent-workflow .
```

其他文档中的 `bash .agent-workflow/lib/python_runtime.sh` 可在 Windows 替换成
`node .agent-workflow/lib/python_runtime.cjs`，后续参数保持不变；inline Python 的 stdin
须使用当前 shell 的语法，不能把 Bash heredoc 原样放进 PowerShell。helper 读取受管的
`.agent-workflow/lib/windows-runtime.paths` 两行记录，以隔离、UTF-8 模式启动持久 Python/bootstrap，
保留 cwd、参数和退出码。损坏、链接、缓存内或非本地绝对路径记录会报错，不自动选择其他解释器。

仅在原有工作流要求当前宿主刷新时，运行现有 setup，然后验收一次：

```powershell
node .agent-workflow/lib/python_runtime.cjs .agent-workflow/lib/platform_process.py --host codex
# 上一条成功后才执行；不要让 check 的成功掩盖 setup 失败。
node .agent-workflow/lib/python_runtime.cjs .agent-workflow/lib/platform_process.py --host codex --check
```

当前宿主为 Claude 或 Antigravity 时分别使用 `claude` / `antigravity`。该入口只通过已验证的
Git for Windows 调用原 `setup_all.sh --only=<host>`，不是 Windows manager，也不在每个任务自动重装。
独立写入前预览可用 `--preflight`；正常 setup 已有预检，不额外前置重复预检。

## 离线构建（不执行下载的二进制）

构建主机可使用 Python >= 3.11，不必是 Windows。先通过独立、明确的下载步骤取得锁定归档，
将下载内容放在源码、构建脚本和解压输出之外的**新空目录**。构建器本身不联网：

- 官方 ZIP：<https://www.python.org/ftp/python/3.14.10/python-3.14.10-embed-amd64.zip>
- 精确版本/架构：CPython `3.14.10` / `x64`
- SHA-256：`90905e64a840557d8c1bc4f5b74db3d7ee85e3ffb217611cac1c7813acea4159`
- 大小：`12619664` 字节
- 来源记录：`packaging/windows/runtime.lock.json`。2026-10-30 从官方 HTTPS 地址实际取得
  ZIP 并计算摘要，且核对官方目录大小；未运行其二进制，未声称完成独立签名验证。

在可信源码目录运行，并保持 Python `-I` 隔离参数：

```powershell
python -I -B packaging/build_npm_release.py --runtime-archive 'C:\awf-download-new\python-3.14.10-embed-amd64.zip' --output 'C:\awf-build\prepared-new'
```

输出目录必须不存在，位于源码和归档之外；父目录须已存在且不能经由符号链接。
构建器校验实际 ZIP 的大小与 SHA-256，以 AST 静态读取安装器 `PACK_FILES/PACK_DIRECTORIES`，
不导入安装器。载荷包含完整 lib 依赖和安装器本身；scripts 只带运行需要的 `guard.sh`、
`lint_rules.sh`、`scaffold_project_docs.sh`，不带可执行的测试脚本，也不带 manager/TUI、测试、
缓存或备份。缺失的 Python/脚本依赖会阻止构建。

ZIP 路径越界、链接/特殊文件、Win32 保留名、大小写别名、重复项、文件/目录冲突、加密或
超限展开都会拒绝；来源文件的链接/硬链接/特殊类型也会拒绝。验证完成后才在新目录写入
`payload/`、`runtime/` 与单一 `bin/` 入口，不执行归档中的任何程序。

接着单独执行 npm 打包；该步骤可以完全离线并忽略 lifecycle scripts：

```powershell
cd 'C:\awf-build\prepared-new'
npm.cmd pack --offline --ignore-scripts --dry-run --json
# C:\awf-build\tgz 是另外准备的空输出目录。
npm.cmd pack --offline --ignore-scripts --pack-destination 'C:\awf-build\tgz'
```

相同输入与工具链生成相同载荷/manifest 和 tgz 字节。已有输出一律保留；重建请使用新的目录。
官方 `runtime/LICENSE.txt` 原样保留 Python 及其附带第三方许可；`THIRD_PARTY_NOTICES.txt`
不替项目选择许可证。项目许可证仍须作者自行确定；本任务不授权公开发布。

## 测试与发布门槛

在源码目录可以运行：

```text
python3.11 -I -B -m unittest discover -s tests -p test_npm_packaging.py
node --test npm/*.test.cjs
python3.11 -I -B -m unittest discover -s tests -p test_platform_bridge.py
python3.11 -I -B -m unittest discover -s tests -p test_windows_fs_contract.py
python3.11 -I -B -m unittest discover -s tests -p test_windows_runtime_boundaries.py
```

覆盖离线 pack、白名单/依赖、完整哈希、恶意 ZIP、来源链接/特殊文件、可重复构建，以及
CLI 参数、无写入预检、Git/Python 显式选择、cwd/Unicode/参数数组、退出码和安全取消模拟。
测试只用临时夹具；另含 manifest/bootstrap 的便携测试和真正仅在 Windows 运行的文件后端测试，
覆盖目录身份、junction/硬链接、私有 SID/DACL、tempfile/fchmod 和真实目录 flush 能力。
另有原生测试覆盖成功的句柄重命名/删除、NUL 相对路径拒绝、清理时身份替换/写入占用、
受保护和继承 DACL 的替换及后续父目录策略传播。目录发布前后使用真实持久化屏障；
清理通过同一个禁止写入/替换共享的句柄校验身份与哈希，再标记删除。能力不足时拒绝，不能降为 no-op。
非 Windows 会明确跳过原生测试，不用模拟 Win32 的通过结果代替验收。
模拟 `win32` 或成功打包不等于原生 Windows 验收。

新增便携边界回归覆盖目录枚举句柄释放、Skill 创建经显式文件后端、inventory/journal
的实际描述符读取、配置安全读取、同卷候选准备失败时保留旧目标，以及仅对已声明路径调用
已定位 Git 安装中的 `cygpath.exe`。Windows 发布 Skill 时先在目标父目录排他准备、校验并
刷新候选，再同卷原子重命名；不使用 `shutil.move` 跨卷回退。无法证明归属的半成品保留，
不递归盲删。预检仍只使用独立暂存区，不提前向项目写候选。

当前部分 Skill/Antigravity 清理仍按路径删除，目标检查与替换也尚未全部绑定同一文件身份；
这些仍是发布前的安全阻塞项。上述便携测试不能证明全部 Windows 文件事务已满足安全合同。

在原生 Windows 源码目录中，给测试进程指定完整本地包后运行端到端夹具：

```powershell
$env:AGENT_WORKFLOW_NPX_TGZ = 'C:\awf-build\tgz\geoege-xll-agent-workflow-0.1.0.tgz'
python -I -B -m unittest discover -s tests -p test_windows_npx_e2e.py -v
```

此变量只供当前测试会话使用，不要写入用户/系统环境。夹具始终新建临时项目和私有 npm 缓存，
通过离线 npm JS CLI 安装、重复升级、超时失败，再删除本测试缓存和来源副本，执行项目 helper
及真实 cmd → PowerShell → Python SessionStart 恢复事件；对 PATH 注册项、profile、ExecutionPolicy
和 Git 全局配置仅取快照对比，不写这些配置。另含已有合法 `.agents/hooks.json` 且
`TMPDIR=/tmp` 的首次安装回归，覆盖不执行整树重置的路径。未设置 tgz 或在非 Windows
上跳过不算验收成功；临时目录和项目位于不同实际卷的验证仍须在相应 Windows 环境完成。

`.github/workflows/windows-npx.yml` 提供独立、手动触发的只读权限 CI 配置，无发布/上传步骤。
下载、可信构建器和准备输出分离；准备完成后才离线 pack 和执行本地 tgz。
目录 flush 能力失败会直接阻塞，不跳过为成功。该文件尚未推送或远程执行；托管 runner 的
管理员令牌结果也不能替代普通用户实测，完整并发/故障恢复矩阵仍须另外完成。

公开支持/发布前，必须在原生 Windows 用本地 tgz 验证实际安装/重复升级、完整 Git 探测、
断网与 `--ignore-scripts`、特殊路径、运行时/项目并发、junction/硬链接/目录替换、占用、
Ctrl+C/超时后代树停止与精确恢复、用户配置保留，以及清空 npm 缓存后的真实宿主 Hook。
还须比较 PATH/profile/ExecutionPolicy/Git 全局配置前后不变，并通过现有 macOS 回归。
当前 macOS 开发机无法证明这些原生 Windows 行为；未完成之前不能宣称 Windows 已支持。
