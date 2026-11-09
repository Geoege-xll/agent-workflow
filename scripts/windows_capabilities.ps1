#requires -Version 7.0
# 薄入口只启动用户显式选择的已有 python.exe；不修改 ExecutionPolicy/PATH/profile。
# 示例：& .\scripts\windows_capabilities.ps1 -Python 'C:\Python311\python.exe'
# py.exe 属于带版本选择的启动器，本接口明确不接收它，避免把 -3 参数误传给 python.exe。
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidateNotNullOrEmpty()]
    [string]$Python,
    [string]$OutputParent = [System.IO.Path]::GetTempPath()
)
$ErrorActionPreference = 'Stop'
# 接口只接受绝对文件路径；Get-Item 的 LiteralPath 不解释通配符，也不会像
# Get-Command 的 PATH 查询那样返回多个已安装版本。无效显式路径直接拒绝。
$driveAbsolute = $Python -match '\A[A-Za-z]:[\\/]'
$uncAbsolute = $Python -match '\A\\\\[^\\/]+[\\/][^\\/]+[\\/]'
if (-not ($driveAbsolute -or $uncAbsolute)) {
    throw 'Pass one absolute path to an existing python.exe; command names and relative paths are not accepted.'
}
$files = @(Get-Item -LiteralPath $Python -Force -ErrorAction Stop)
if ($files.Count -ne 1 -or $files[0] -isnot [System.IO.FileInfo] -or -not $files[0].Exists) {
    throw 'The explicit Python path must identify exactly one existing executable file.'
}
$executable = $files[0]
if ($executable.Name -ieq 'py.exe' -or $executable.Extension -ine '.exe') {
    throw 'Pass an existing Python interpreter .exe path, not py.exe or a command script. Python >= 3.11 is required.'
}
# PowerShell 7+ 直接消费独立脚本；不为旧壳层切换共享控制台编码。
# -I 隔离调用者 PYTHONPATH/cwd；版本和原生平台仍由独立脚本再次验证。
# 调用运算符保持各参数边界，不拼接命令文本、不查找替代解释器。
& $executable.FullName -I -B -X utf8 (Join-Path $PSScriptRoot 'windows_capabilities.py') --output-parent $OutputParent
exit $LASTEXITCODE
