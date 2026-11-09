#requires -Version 7.0
<#
Win11 普通用户整体验收。由 PM 在整体开发完成后提供固定 commit/version。
示例：& .\scripts\windows_acceptance.ps1 -Python 'C:\awf-venv\Scripts\python.exe' `
  -ExpectedCommit '<40位提交>' -ExpectedVersion '<product/VERSION中的版本>'
已有 Python 必须已按 requirements-windows.txt 装好依赖；本入口不下载/安装软件，
不改真实宿主、PATH、profile、ExecutionPolicy。NO_COLOR=1 只选择既有单色主题。
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][ValidateNotNullOrEmpty()][string]$Python,
    [Parameter(Mandatory = $true)][ValidatePattern('\A[0-9a-f]{40}\z')][string]$ExpectedCommit,
    [Parameter(Mandatory = $true)][ValidateNotNullOrEmpty()][string]$ExpectedVersion,
    [string]$OutputParent = [System.IO.Path]::GetTempPath()
)
$ErrorActionPreference = 'Stop'
$PSNativeCommandUseErrorActionPreference = $false
if (-not $IsWindows) { throw 'This acceptance entry requires native Windows 11 x64 and PowerShell 7+.' }
if (-not [System.IO.Path]::IsPathFullyQualified($Python)) { throw 'Pass one absolute existing python.exe path.' }
$interpreter = Get-Item -LiteralPath $Python -Force -ErrorAction Stop
if ($interpreter -isnot [System.IO.FileInfo] -or $interpreter.Extension -ine '.exe' -or $interpreter.Name -ieq 'py.exe') {
    throw 'Pass the existing interpreter .exe, not py.exe, a command name or a script.'
}
$parent = Get-Item -LiteralPath $OutputParent -Force -ErrorAction Stop
if ($parent -isnot [System.IO.DirectoryInfo]) { throw 'OutputParent must be an existing local directory.' }
$root = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
if ($parent.FullName.TrimEnd('\') -ieq $root.TrimEnd('\') -or
    $parent.FullName.StartsWith($root.TrimEnd('\') + '\', [System.StringComparison]::OrdinalIgnoreCase)) {
    throw 'Keep acceptance evidence outside the candidate source tree.'
}
$git = (Get-Command git.exe -CommandType Application -ErrorAction Stop).Source
$actualCommit = (& $git -C $root rev-parse HEAD | Out-String).Trim()
if ($LASTEXITCODE -ne 0 -or $actualCommit -cne $ExpectedCommit) { throw 'The source HEAD does not match ExpectedCommit.' }
$dirty = @(& $git -C $root status --porcelain --untracked-files=normal)
if ($LASTEXITCODE -ne 0 -or $dirty.Count -ne 0) { throw 'Use the exact clean candidate checkout for acceptance.' }
$version = [System.IO.File]::ReadAllText((Join-Path $root 'product/VERSION')).Trim()
if ($version -cne $ExpectedVersion) { throw 'The source product/VERSION does not match ExpectedVersion.' }

# 能力事实和私有 NTFS 工作根完全复用既有探针，不复制 token/ACL/symlink API。
# 探针原始 JSON 自带环境和错误码；即使未产生报告，stdout 仍保留失败全文。
$capabilityArguments = @('-I', '-B', '-X', 'utf8', (Join-Path $PSScriptRoot 'windows_capabilities.py'),
    '--output-parent', $parent.FullName)
Write-Host ('command=' + (ConvertTo-Json -InputObject (@($interpreter.FullName) + $capabilityArguments) -Compress))
$capabilityOutput = @(& $interpreter.FullName @capabilityArguments 2>&1)
$capabilityExit = $LASTEXITCODE
$capabilityText = $capabilityOutput | Out-String
Write-Host $capabilityText
Write-Host "capabilities_exit_code=$capabilityExit"
if ($null -eq $capabilityExit -or $capabilityExit -ne 0) { throw 'The existing capabilities probe failed; acceptance did not run.' }
$capability = $capabilityText | ConvertFrom-Json
if ($capability.status -ne 'report-produced' -or -not $capability.workspace -or -not $capability.report_file) {
    throw 'The capabilities probe did not produce a complete private report.'
}
$workspace = $capability.workspace
$log = Join-Path $workspace 'acceptance.log'
$identityPath = Join-Path $workspace 'environment.json'
$summaryPath = Join-Path $workspace 'acceptance.json'
$stream = [System.IO.File]::Open($log, [System.IO.FileMode]::CreateNew, [System.IO.FileAccess]::Write, [System.IO.FileShare]::Read)
$stream.Dispose()
('command=' + (ConvertTo-Json -InputObject (@($interpreter.FullName) + $capabilityArguments) -Compress)) |
    Add-Content -LiteralPath $log -Encoding utf8
$capabilityText | Add-Content -LiteralPath $log -Encoding utf8
"capabilities_exit_code=$capabilityExit" | Add-Content -LiteralPath $log -Encoding utf8

function Write-AcceptanceLog([string]$Text) {
    $Text | Tee-Object -FilePath $log -Append | Out-Host
}
function Invoke-AcceptancePython([string[]]$Arguments) {
    Write-AcceptanceLog ('command=' + (ConvertTo-Json -InputObject (@($interpreter.FullName) + $Arguments) -Compress))
    & $interpreter.FullName @Arguments 2>&1 | Tee-Object -FilePath $log -Append | Out-Host
    $nativeExit = $LASTEXITCODE
    Write-AcceptanceLog "exit_code=$nativeExit"
    if ($null -eq $nativeExit -or $nativeExit -ne 0) { throw "The explicit Python command failed with exit $nativeExit." }
}
function Write-AcceptanceIdentity {
    $identityCode = @'
import ctypes, importlib.metadata, json, os, pathlib, platform, sys
if os.name != "nt" or sys.version_info < (3, 11) or ctypes.sizeof(ctypes.c_void_p) != 8:
    raise RuntimeError("An existing native CPython >= 3.11 x64 is required")
if platform.python_implementation() != "CPython":
    raise RuntimeError("Only the declared CPython runtime is accepted")
import curses, _curses
version = importlib.metadata.version("windows-curses")
if version != "2.4.2":
    raise RuntimeError("Install the reviewed requirements-windows.txt into the selected environment before acceptance")
value = {"python": sys.version, "executable": sys.executable, "prefix": sys.prefix,
         "base_prefix": sys.base_prefix, "windows_curses": version, "curses_extension": _curses.__file__}
body = json.dumps(value, ensure_ascii=True, indent=2)
with pathlib.Path(sys.argv[1]).open("x", encoding="utf-8") as stream: stream.write(body + "\n")
print(body)
'@
    # PowerShell 7.0–7.2 与 Legacy native argv 会再次处理 -c 代码中的双引号。
    # 固定代码只排他写入能力探针创建的本次私有目录，再按脚本路径调用：无需
    # 改用户 ArgumentPassing，也不引入另一套进程/Job、重定向或取消清理逻辑。
    # 保留该文件作为实际执行输入，便于与环境报告及完整 argv 日志共同复核。
    $identityScript = Join-Path $workspace 'environment_probe.py'
    $identityStream = [System.IO.File]::Open($identityScript, [System.IO.FileMode]::CreateNew,
        [System.IO.FileAccess]::Write, [System.IO.FileShare]::Read)
    try {
        $identityBytes = [System.Text.UTF8Encoding]::new($false).GetBytes($identityCode)
        $identityStream.Write($identityBytes, 0, $identityBytes.Length)
    } finally {
        $identityStream.Dispose()
    }
    Invoke-AcceptancePython -Arguments @('-I', '-B', '-X', 'utf8', $identityScript, $identityPath)
}

$environmentNames = @('TEMP', 'TMP', 'AGENT_WORKFLOW_TEST_SCRATCH', 'AWF_TEST_EVIDENCE_LOG',
    'AGENT_WORKFLOW_PYTHON', 'AGENT_WORKFLOW_BOOTSTRAP', 'AGENT_WORKFLOW_PWSH')
$previousEnvironment = @{}
foreach ($name in $environmentNames) { $previousEnvironment[$name] = [Environment]::GetEnvironmentVariable($name, 'Process') }
$code = 1
$failure = $null
try {
    Write-AcceptanceLog "candidate_commit=$actualCommit"
    Write-AcceptanceLog "candidate_version=$version"
    Write-AcceptanceLog "powershell_path=$(Join-Path $PSHOME 'pwsh.exe')"
    Write-AcceptanceLog "powershell_version=$($PSVersionTable.PSVersion)"
    # Win32 探针中的 product_type=1 才是客户端；Server CI 的 PASS 不能投影成
    # Win11 普通桌面证据。普通用户 token 同样由已有探针提供，不重复实现。
    $environment = $capability.environment
    if ($environment.os -ne 'Windows' -or $environment.windows_product_type -ne 1 -or
        [version]$environment.version -lt [version]'10.0.22000' -or $environment.pointer_bits -ne 64 -or
        $environment.machine -notin @('AMD64', 'x86_64')) { throw 'This is not the declared Windows 11 x64 client environment.' }
    if (-not $environment.token_elevation.ok -or $environment.token_elevation.elevated) {
        throw 'Run this ordinary-user acceptance from a non-elevated PowerShell 7+ session.'
    }
    $data = Join-Path $workspace 'test-data'
    [System.IO.Directory]::CreateDirectory($data) | Out-Null
    $env:TEMP = $data
    $env:TMP = $data
    $env:AGENT_WORKFLOW_TEST_SCRATCH = $data
    $env:AWF_TEST_EVIDENCE_LOG = Join-Path $workspace 'native-evidence.jsonl'
    $env:AGENT_WORKFLOW_PYTHON = $interpreter.FullName
    $env:AGENT_WORKFLOW_BOOTSTRAP = Join-Path $root 'lib/windows_bootstrap.py'
    $env:AGENT_WORKFLOW_PWSH = Join-Path $PSHOME 'pwsh.exe'
    Write-AcceptanceIdentity
    $entry = Join-Path $PSScriptRoot 'test_workflow.py'
    # 唯一测试清单决定最终组合，脚本不持有第二套方法名、计数或动态 skip 规则。
    # --list 只确认节点存在；随后同一组必须真实执行，退出码由原 runner 拒绝
    # missing/skip/未执行。原始 VT、原生格/属性/模式存入独立 evidence JSONL。
    Invoke-AcceptancePython -Arguments @('-I', '-B', '-X', 'utf8', $entry, '--list', 'windows-native')
    Invoke-AcceptancePython -Arguments @('-I', '-B', '-X', 'utf8', $entry, 'windows-native')
    $afterCommit = (& $git -C $root rev-parse HEAD | Out-String).Trim()
    if ($LASTEXITCODE -ne 0 -or $afterCommit -cne $ExpectedCommit) { throw 'The candidate changed during acceptance.' }
    $afterDirty = @(& $git -C $root status --porcelain --untracked-files=normal)
    if ($LASTEXITCODE -ne 0 -or $afterDirty.Count -ne 0) { throw 'The candidate source changed during acceptance.' }
    $code = 0
} catch {
    $failure = $_ | Out-String
    Write-AcceptanceLog $failure
} finally {
    foreach ($name in $environmentNames) { [Environment]::SetEnvironmentVariable($name, $previousEnvironment[$name], 'Process') }
    $summary = [ordered]@{ schema_version = 1; scope = 'windows11-client-native-full';
        status = $(if ($code -eq 0) { 'PASS' } else { 'FAIL' }); exit_code = $code;
        candidate_commit = $actualCommit; candidate_version = $version;
        powershell_version = $PSVersionTable.PSVersion.ToString(); python = $interpreter.FullName;
        capabilities = $capability.report_file; environment = $identityPath;
        log = $log; native_evidence = (Join-Path $workspace 'native-evidence.jsonl'); failure = $failure }
    $summary | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $summaryPath -Encoding utf8
    Write-AcceptanceLog "acceptance_exit_code=$code"
    Write-Host "完整验收结果：$summaryPath"
}
exit $code
