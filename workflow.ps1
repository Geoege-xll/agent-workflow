#requires -Version 7.0
# 原生源码入口：先配置已有解释器的绝对路径，然后传入普通 CLI 参数。
# $env:AGENT_WORKFLOW_PYTHON = 'C:\Python311\python.exe'
# & .\workflow.ps1 --help
# 程序化参数（含空串、嵌套引号）用字符串数组：& .\workflow.ps1 @cliArgs。
# 本脚本没有 param 绑定层，所有业务参数保持在自动 $args 数组中；它与
# workflow.py 共用 manager.cli.main，不安装依赖、不更改宿主或 shell 设置。
$ErrorActionPreference = 'Stop'

try {
    if (-not $IsWindows) {
        throw '此 PowerShell 薄入口需要原生 Windows；其他平台请直接运行 workflow.py。'
    }
    $python = [Environment]::GetEnvironmentVariable('AGENT_WORKFLOW_PYTHON')
    # 显式配置必须确定地指向已有本地解释器，不能由 PATH、cwd、py.exe 或
    # 命令脚本另选运行时。先检查原始拼写，避免规范化隐藏相对段、ADS 等别名。
    if ([string]::IsNullOrWhiteSpace($python) -or $python -notmatch '\A[A-Za-z]:[\\/]') {
        throw '请将 AGENT_WORKFLOW_PYTHON 设为已有 CPython 3.11+ x64 的本地绝对 python.exe 路径。'
    }
    $tail = $python.Substring(3)
    if ($tail.Contains(':') -or $python.Contains('"') -or $python.IndexOf([char]0) -ge 0) {
        throw 'AGENT_WORKFLOW_PYTHON 包含无效路径字符。'
    }
    foreach ($component in ($tail -split '[\\/]')) {
        if ($component -eq '.' -or $component -eq '..' -or $component.EndsWith('.') -or $component.EndsWith(' ')) {
            throw 'AGENT_WORKFLOW_PYTHON 不能包含相对段或末尾点/空格。'
        }
    }
    $file = Get-Item -LiteralPath $python -Force -ErrorAction Stop
    if ($file -isnot [System.IO.FileInfo] -or -not $file.Exists -or
        $file.Name -notmatch '\Apython(?:3(?:\.\d+)?)?\.exe\z') {
        throw 'AGENT_WORKFLOW_PYTHON 必须指向已有 Python 控制台解释器，不能使用启动器或其他程序。'
    }

    $start = [System.Diagnostics.ProcessStartInfo]::new()
    $start.FileName = $file.FullName
    $start.UseShellExecute = $false
    # 显式保留调用者 cwd；绝不为导入源码切换到脚本根。Windows 的 CPython
    # 隔离、版本和 x64 校验集中在 workflow.py 最前面，不额外执行解释器探针。
    # PowerShell 的 Set-Location 不保证同步 .NET CurrentDirectory；使用真实
    # FileSystem provider 的当前位置，避免交互切目录后相对参数跑回旧目录。
    $location = Get-Location
    if ($location.Provider.Name -ne 'FileSystem') {
        throw '请从文件系统目录调用原生源码入口。'
    }
    $start.WorkingDirectory = $location.ProviderPath
    foreach ($argument in @('-I', '-B', '-X', 'utf8', (Join-Path $PSScriptRoot 'workflow.py'))) {
        $start.ArgumentList.Add($argument)
    }
    foreach ($argument in $args) {
        if ($argument -isnot [string] -or $argument.IndexOf([char]0) -ge 0) {
            throw 'CLI 参数必须为不含 NUL 的字符串；复杂参数请通过 PowerShell 字符串数组传入。'
        }
        # ArgumentList 在 .NET 层编码每个参数，绕过 PowerShell 7.0/Legacy
        # 的 native argv 拼接；空串、引号、反斜线和符号都作为数据单次转发。
        $start.ArgumentList.Add($argument)
    }
    $process = [System.Diagnostics.Process]::Start($start)
    try {
        $process.WaitForExit()
        $result = $process.ExitCode
    }
    finally {
        $process.Dispose()
    }
}
catch {
    [Console]::Error.WriteLine('[错误] 原生源码入口启动失败：' + $_.Exception.Message)
    exit 2
}
# stdout/stderr/stdin 均直接继承；成功、业务拒绝和取消退出码不在薄桥中改写。
exit $result
