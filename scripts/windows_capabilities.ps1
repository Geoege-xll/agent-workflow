# 薄入口只启动用户显式选择的已有 python.exe；不修改 ExecutionPolicy/PATH/profile。
# 示例：& .\scripts\windows_capabilities.ps1 -Python 'C:\Python311\python.exe'
# py.exe 属于带版本选择的启动器，本接口明确不接收它，避免把 -3 参数误传给 python.exe。
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$Python,
    [string]$OutputParent = [System.IO.Path]::GetTempPath()
)
$ErrorActionPreference = 'Stop'
$executable = Get-Command -Name $Python -CommandType Application -ErrorAction Stop
if ([System.IO.Path]::GetFileName($executable.Source) -ieq 'py.exe') {
    throw 'Pass an existing python.exe path, not py.exe. Python >= 3.11 is required.'
}
# -I 隔离调用者的 PYTHONPATH 与 cwd；实际版本和原生平台由独立脚本再次验证。
# 调用运算符保持每个参数的边界；绝不拼接命令字符串或回退到其他解释器。
& $executable.Source -I -B -X utf8 (Join-Path $PSScriptRoot 'windows_capabilities.py') --output-parent $OutputParent
exit $LASTEXITCODE
