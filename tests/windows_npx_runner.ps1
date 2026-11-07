# 此脚本仅在一次性 GitHub Windows runner 中验证真实账户能力。
# 产品安装器不会调用此脚本、创建账户或修改任何账户权限。
param(
    [ValidateSet('native-capabilities', 'native-negative-fixture', 'native-negative-cleanup', 'native-backend')]
    [string]$Mode = 'native-capabilities'
)

$ErrorActionPreference = 'Stop'
if (-not $env:GITHUB_ACTIONS -or -not $env:RUNNER_TEMP) {
    throw '仅允许在本任务的一次性 GitHub Actions runner 执行账户能力探针'
}
$principal = [Security.Principal.WindowsPrincipal]::new([Security.Principal.WindowsIdentity]::GetCurrent())
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw '准备限定测试账户需要 runner 管理员令牌；测试本身另以标准用户执行'
}
if ($Mode -ne 'native-negative-cleanup') {
    # setup-python 已在当前 job 声明唯一解释器。Get-Command 可能一次返回
    # PATH 上多个 Application，不能把 Source 集合拼接成可执行文件名。
    # 仅采用该已配置目录中的单个真实文件，不回退 WindowsApps 或另一版本。
    if ([string]::IsNullOrWhiteSpace($env:pythonLocation)) {
        throw '当前 job 未提供 setup-python 的 pythonLocation'
    }
    $pythonFile = Get-Item -LiteralPath (Join-Path $env:pythonLocation 'python.exe')
    if ($pythonFile -isnot [IO.FileInfo]) {
        throw 'setup-python 的 python.exe 必须是一个已存在的普通文件'
    }
    [string]$python = $pythonFile.FullName
    Write-Host "已配置解释器：$python"
}

$probe = Join-Path $PSScriptRoot 'test_windows_central_fs.py'
$name = 'awfprobe' + [guid]::NewGuid().ToString('N').Substring(0, 10)
$root = Join-Path ($env:SystemDrive + '\') ('awf-capabilities-' + [guid]::NewGuid().ToString('N'))
$created = $false
$rightsAssigned = $false
$sid = $null
$failures = [Collections.Generic.List[string]]::new()

# LSA 修改限定为刚创建的随机测试 SID。禁止使用本 helper 更改 runner
# 或任何现有账户；finally 先移除该 SID 的赋权再删除账户与 profile。
if ($Mode -eq 'native-capabilities') {
Add-Type -TypeDefinition @'
using System;
using System.ComponentModel;
using System.Runtime.InteropServices;
using System.Security.Principal;
public static class AwfProbeRights {
    [StructLayout(LayoutKind.Sequential)]
    struct ObjectAttributes {
        public uint Length; public IntPtr RootDirectory; public IntPtr ObjectName;
        public uint Attributes; public IntPtr SecurityDescriptor; public IntPtr SecurityQualityOfService;
    }
    [StructLayout(LayoutKind.Sequential)]
    struct UnicodeString { public ushort Length; public ushort MaximumLength; public IntPtr Buffer; }
    [DllImport("advapi32.dll")] static extern uint LsaOpenPolicy(
        IntPtr name, ref ObjectAttributes attributes, uint access, out IntPtr policy);
    [DllImport("advapi32.dll")] static extern uint LsaAddAccountRights(
        IntPtr policy, IntPtr sid, UnicodeString[] rights, uint count);
    [DllImport("advapi32.dll")] static extern uint LsaRemoveAccountRights(
        IntPtr policy, IntPtr sid, [MarshalAs(UnmanagedType.U1)] bool all, IntPtr rights, uint count);
    [DllImport("advapi32.dll")] static extern uint LsaClose(IntPtr policy);
    [DllImport("advapi32.dll")] static extern uint LsaNtStatusToWinError(uint status);
    static void Check(uint status) {
        if (status != 0) throw new Win32Exception((int)LsaNtStatusToWinError(status));
    }
    public static void Set(string textSid, bool add) {
        var sid = new SecurityIdentifier(textSid);
        var bytes = new byte[sid.BinaryLength]; sid.GetBinaryForm(bytes, 0);
        IntPtr sidBuffer = Marshal.AllocHGlobal(bytes.Length);
        IntPtr rightBuffer = IntPtr.Zero; IntPtr policy = IntPtr.Zero;
        try {
            Marshal.Copy(bytes, 0, sidBuffer, bytes.Length);
            var attributes = new ObjectAttributes();
            attributes.Length = (uint)Marshal.SizeOf(typeof(ObjectAttributes));
            Check(LsaOpenPolicy(IntPtr.Zero, ref attributes, 0x810, out policy));
            if (add) {
                string right = "SeCreateSymbolicLinkPrivilege";
                rightBuffer = Marshal.StringToHGlobalUni(right);
                var value = new UnicodeString {
                    Length = (ushort)(right.Length * 2),
                    MaximumLength = (ushort)((right.Length + 1) * 2), Buffer = rightBuffer
                };
                Check(LsaAddAccountRights(policy, sidBuffer, new[] { value }, 1));
            } else {
                Check(LsaRemoveAccountRights(policy, sidBuffer, true, IntPtr.Zero, 0));
            }
        } finally {
            uint closeStatus = policy != IntPtr.Zero ? LsaClose(policy) : 0;
            if (rightBuffer != IntPtr.Zero) Marshal.FreeHGlobal(rightBuffer);
            Marshal.FreeHGlobal(sidBuffer);
            Check(closeStatus);
        }
    }
}
'@

}

function Invoke-OrdinaryProbe([string]$Stage, [pscredential]$Credential) {
    $stdout = Join-Path $root ($Stage + '.stdout.log')
    $stderr = Join-Path $root ($Stage + '.stderr.log')
    $process = $null
    try {
        # 每阶段都重新登录；先无权限、后赋权后的新令牌，不能复用缓存令牌。
        # 参数只含本轮路径与固定枚举；凭证只经 Credential API 传递。
        # -I 忽略环境开关；重定向的普通用户 stdout 必须显式 UTF-8，
        # 否则中文诊断会在调用能力 API 前因默认 cp1252 失败。
        $arguments = '-I -B -X utf8 "' + $probe + '" --probe ' + $Stage + ' --root "' + $root + '"'
        $process = Start-Process -FilePath $python -ArgumentList $arguments -Credential $Credential -LoadUserProfile -WorkingDirectory $root -RedirectStandardOutput $stdout -RedirectStandardError $stderr -PassThru
        if (-not $process.WaitForExit(120000)) {
            # 只终止当前脚本持有的测试子进程树；不枚举或终止其他用户进程。
            & "$env:SystemRoot\System32\taskkill.exe" /PID $process.Id /T /F | Out-Host
            if (-not $process.WaitForExit(30000)) { throw "测试子进程终止失败：$Stage" }
            throw "能力阶段超时：$Stage"
        }
        $process.Refresh()
        if ($process.ExitCode -ne 0) { $failures.Add("$Stage exit=$($process.ExitCode)") }
    } catch {
        $failures.Add("$Stage executor: $($_.Exception.Message)")
    } finally {
        foreach ($path in @($stdout, $stderr)) {
            if (Test-Path -LiteralPath $path) {
                Write-Host "--- $Stage $([IO.Path]::GetFileName($path)) ---"
                Get-Content -LiteralPath $path | Write-Host
            }
        }
        if ($null -ne $process) { $process.Dispose() }
    }
}


# 只供本仓临时 CI 分支使用的负向环境 fixture；生产入口没有此调用链。
$negativeRepository = 'Geoege-xll/agent-workflow'
$negativeBranch = 'refs/heads/ci/windows-central-npm-2.1.1'
$negativeSubkey = 'SOFTWARE\Microsoft\Windows\CurrentVersion\AppModelUnlock'
$negativeValue = 'AllowDevelopmentWithoutDevLicense'

function Assert-HostedEnvironment([bool]$RequireTemporaryBranch) {
    if ($env:GITHUB_ACTIONS -cne 'true' -or $env:RUNNER_ENVIRONMENT -cne 'github-hosted' -or
        $env:GITHUB_REPOSITORY -cne $negativeRepository -or
        ($RequireTemporaryBranch -and $env:GITHUB_REF -cne $negativeBranch)) {
        throw '原生 fixture 仅授权本仓 GitHub-hosted 一次性 VM；负向必须在临时 CI 分支'
    }
    $head = & git -C (Split-Path $PSScriptRoot -Parent) rev-parse HEAD
    if ($LASTEXITCODE -ne 0 -or $head -cne $env:GITHUB_SHA) {
        throw '实际 checkout HEAD 与本次 GitHub SHA 不符'
    }
    Write-Host "原生 fixture 环境：$env:RUNNER_ENVIRONMENT $env:GITHUB_REPOSITORY $env:GITHUB_REF $head"
}

function Open-NegativeRegistry {
    $base = [Microsoft.Win32.RegistryKey]::OpenBaseKey(
        [Microsoft.Win32.RegistryHive]::LocalMachine, [Microsoft.Win32.RegistryView]::Registry64)
    try {
        $key = $base.OpenSubKey($negativeSubkey, $true)
        if ($null -eq $key) { throw '授权的既有 AppModelUnlock 注册表项不存在' }
        return $key
    } finally { $base.Dispose() }
}

function Set-NegativeSwitch([bool]$Restore) {
    $key = Open-NegativeRegistry
    try {
        $kind = $key.GetValueKind($negativeValue)
        $value = $key.GetValue($negativeValue)
        if ($kind -ne [Microsoft.Win32.RegistryValueKind]::DWord -or
            ($Restore -and $value -notin @(0, 1)) -or (-not $Restore -and $value -ne 1)) {
            throw "注册表前像/当前状态未知，保留且拒绝覆盖：kind=$kind value=$value"
        }
        # 此处是独占一次性 VM、无其他配置 writer 前提下的条件恢复。
        # RegistryKey 没有原子 CompareExchange，不能声称排除非合作外部写者。
        $desired = if ($Restore) { 1 } else { 0 }
        if ($value -ne $desired) {
            $key.SetValue($negativeValue, $desired, [Microsoft.Win32.RegistryValueKind]::DWord)
            $key.Flush()
        }
        if ($key.GetValueKind($negativeValue) -ne [Microsoft.Win32.RegistryValueKind]::DWord -or
            $key.GetValue($negativeValue) -ne $desired) {
            throw '注册表条件更新后核对失败'
        }
        Write-Host "授权单值状态：DWORD$value -> DWORD$desired；restore=$Restore"
    } finally { $key.Dispose() }
}

function Assert-NegativeControl([string]$Control) {
    $parent = [IO.Path]::GetFullPath($env:RUNNER_TEMP).TrimEnd('\')
    $full = [IO.Path]::GetFullPath($Control).TrimEnd('\')
    if (-not [string]::Equals([IO.Path]::GetDirectoryName($full), $parent,
                             [StringComparison]::OrdinalIgnoreCase) -or
        [IO.Path]::GetFileName($full) -cnotmatch '^awf-negative-control-([0-9a-f]{32})$') {
        throw '备用恢复位置必须是 RUNNER_TEMP 下本任务的直接子目录'
    }
    $id = [regex]::Match([IO.Path]::GetFileName($full), '^awf-negative-control-([0-9a-f]{32})$').Groups[1].Value
    if (Test-Path -LiteralPath $full) {
        $directory = Get-Item -LiteralPath $full
        if ($directory -isnot [IO.DirectoryInfo] -or
            ($directory.Attributes -band [IO.FileAttributes]::ReparsePoint)) {
            throw '控制器目录不能是链接或特殊节点'
        }
        $acl = Get-Acl -LiteralPath $full
        $owner = [Security.Principal.WindowsIdentity]::GetCurrent().User.Value
        $rules = @($acl.GetAccessRules($true, $true, [Security.Principal.SecurityIdentifier]))
        if (-not $acl.AreAccessRulesProtected -or
            $acl.GetOwner([Security.Principal.SecurityIdentifier]).Value -ne $owner -or $rules.Count -ne 2) {
            throw '控制器快照目录不是受保护的当前控制器所有'
        }
        $seen = @()
        foreach ($rule in $rules) {
            if ($rule.IsInherited -or $rule.AccessControlType -ne 'Allow' -or
                $rule.FileSystemRights -ne [Security.AccessControl.FileSystemRights]::FullControl -or
                $rule.IdentityReference.Value -notin @($owner, 'S-1-5-18')) {
                throw '控制器快照目录向其他主体授予访问'
            }
            $seen += $rule.IdentityReference.Value
        }
        if (@($seen | Select-Object -Unique).Count -ne 2) { throw '控制器 DACL 主体不完整' }
    }
    return $id
}

function Read-NegativeSnapshot([string]$Control) {
    $id = Assert-NegativeControl $Control
    $file = Get-Item -LiteralPath (Join-Path $Control 'negative-state.json')
    if ($file -isnot [IO.FileInfo] -or $file.Length -gt 4096 -or
        ($file.Attributes -band [IO.FileAttributes]::ReparsePoint)) {
        throw '备用恢复快照不是有界普通文件'
    }
    $state = [IO.File]::ReadAllText($file.FullName) | ConvertFrom-Json
    $fields = @('schema_version','fixture_id','run_id','run_attempt','repository','branch','owner_sid','registry_kind','registry_value')
    $actual = @($state.PSObject.Properties.Name)
    if (@(Compare-Object ($fields | Sort-Object) ($actual | Sort-Object)).Count -ne 0 -or
        $state.schema_version -ne 1 -or $state.fixture_id -cne $id -or
        $state.run_id -cne $env:GITHUB_RUN_ID -or $state.run_attempt -cne $env:GITHUB_RUN_ATTEMPT -or
        $state.repository -cne $negativeRepository -or $state.branch -cne $negativeBranch -or
        $state.owner_sid -cne [Security.Principal.WindowsIdentity]::GetCurrent().User.Value -or
        $state.registry_kind -cne 'DWord' -or $state.registry_value -ne 1) {
        throw '备用恢复快照身份/固定前像不符'
    }
    # 注册表路径和值均由源码常量决定；快照不能指定任意键或任意原值。
    return $state
}

function Remove-NegativeResources($State) {
    $accountName = 'awfneg' + $State.fixture_id.Substring(0, 12)
    $description = "AWF negative $($State.run_id)/$($State.run_attempt) $($State.fixture_id.Substring(0, 8))"
    $account = Get-LocalUser -Name $accountName -ErrorAction SilentlyContinue
    if ($null -ne $account) {
        if ($account.Description -cne $description) { throw '同名账户不是本次 fixture，拒绝删除' }
        $accountSid = $account.SID.Value
        # 正常调用已释放进程；取消后的 always 只收回本轮随机测试账户的
        # Python 进程，不终止 runner 或任何现有用户的进程。
        foreach ($process in @(Get-CimInstance Win32_Process -Filter "Name='python.exe'")) {
            $identity = Invoke-CimMethod -InputObject $process -MethodName GetOwnerSid
            if ($identity.ReturnValue -eq 0 -and $identity.Sid -ceq $accountSid) {
                Stop-Process -Id $process.ProcessId -Force -ErrorAction SilentlyContinue
                Wait-Process -Id $process.ProcessId -Timeout 30 -ErrorAction SilentlyContinue
                if (Get-Process -Id $process.ProcessId -ErrorAction SilentlyContinue) {
                    throw '本轮测试进程尚未退出，保留恢复快照'
                }
            }
        }
        Get-CimInstance Win32_UserProfile -Filter "SID='$accountSid'" | Remove-CimInstance
        Remove-LocalUser -Name $accountName
    }
    $fixture = Join-Path ($env:SystemDrive + '\') ('awf-negative-' + $State.fixture_id)
    if (Test-Path -LiteralPath $fixture) {
        if ((Get-Item -LiteralPath $fixture).Attributes -band [IO.FileAttributes]::ReparsePoint) {
            throw '测试根被替换成链接，保留且拒绝递归删除'
        }
        Remove-Item -LiteralPath $fixture -Recurse -Force
    }
}

function Complete-NegativeFixture([bool]$Final) {
    if ([string]::IsNullOrWhiteSpace($env:AWF_NEGATIVE_CONTROL)) {
        Write-Host '未登记控制器快照，注册表修改许可尚未取得，无需恢复。'
        return
    }
    $id = Assert-NegativeControl $env:AWF_NEGATIVE_CONTROL
    if (-not (Test-Path -LiteralPath $env:AWF_NEGATIVE_CONTROL)) {
        # always 成功清理后再次调用只核对，不创建资源、改值或重新运行测试。
        $key = Open-NegativeRegistry
        try {
            if ($key.GetValueKind($negativeValue) -ne [Microsoft.Win32.RegistryValueKind]::DWord -or
                $key.GetValue($negativeValue) -ne 1) { throw '快照已回收但固定前像不符，拒绝盲目恢复' }
        } finally { $key.Dispose() }
        $account = Get-LocalUser -Name ('awfneg' + $id.Substring(0, 12)) -ErrorAction SilentlyContinue
        $fixture = Join-Path ($env:SystemDrive + '\') ('awf-negative-' + $id)
        if ($null -ne $account -or (Test-Path -LiteralPath $fixture)) {
            throw '快照已回收但存在未结算资源，拒绝猜测归属'
        }
        Write-Host '备用恢复幂等核对完成：前像为 DWORD1，本轮账户/数据目录已不存在。'
        return
    }
    $state = Read-NegativeSnapshot $env:AWF_NEGATIVE_CONTROL
    $errors = [Collections.Generic.List[string]]::new()
    try { Set-NegativeSwitch $true } catch { $errors.Add("registry restore: $($_.Exception.Message)") }
    try { Remove-NegativeResources $state } catch { $errors.Add("resource cleanup: $($_.Exception.Message)") }
    if ($errors.Count) { throw ($errors -join '; ') }
    Write-Host '负向 fixture 清理完成：固定前像 DWORD1、账户、profile、测试进程及数据已核对。'
    if ($Final) {
        # finally 保留快照供 always 再核对；只有备用恢复完成后才删除控制器。
        Remove-Item -LiteralPath $env:AWF_NEGATIVE_CONTROL -Recurse -Force
        Write-Host 'always 备用恢复已完成，控制器快照已回收。'
    }
}

function Invoke-NegativeFixture {
    $id = [guid]::NewGuid().ToString('N')
    $control = Join-Path $env:RUNNER_TEMP ('awf-negative-control-' + $id)
    $script:root = Join-Path ($env:SystemDrive + '\') ('awf-negative-' + $id)
    $script:name = 'awfneg' + $id.Substring(0, 12)
    $credential = $null
    $controlCreated = $false
    if (-not [string]::IsNullOrWhiteSpace($env:AWF_NEGATIVE_CONTROL)) { throw '存在未结算控制器，请先恢复' }
    try {
        # 先核既有 DWORD1，不创建/修复不存在或未知类型的机器配置。
        $key = Open-NegativeRegistry
        try {
            if ($key.GetValueKind($negativeValue) -ne [Microsoft.Win32.RegistryValueKind]::DWord -or
                $key.GetValue($negativeValue) -ne 1) { throw '负向 fixture 只接受既有 DWORD1' }
        } finally { $key.Dispose() }
        New-Item -ItemType Directory -Path $control | Out-Null
        $controlCreated = $true
        $owner = [Security.Principal.WindowsIdentity]::GetCurrent().User
        $acl = [Security.AccessControl.DirectorySecurity]::new()
        $acl.SetAccessRuleProtection($true, $false)
        $acl.SetOwner($owner)
        foreach ($sidText in @($owner.Value, 'S-1-5-18')) {
            $sid = [Security.Principal.SecurityIdentifier]::new($sidText)
            $rule = [Security.AccessControl.FileSystemAccessRule]::new(
                $sid, 'FullControl', 'ContainerInherit,ObjectInherit', 'None', 'Allow')
            $acl.AddAccessRule($rule)
        }
        Set-Acl -LiteralPath $control -AclObject $acl
        $state = [ordered]@{
            schema_version=1; fixture_id=$id; run_id=$env:GITHUB_RUN_ID; run_attempt=$env:GITHUB_RUN_ATTEMPT
            repository=$negativeRepository; branch=$negativeBranch; owner_sid=$owner.Value
            registry_kind='DWord'; registry_value=1
        }
        $body = [Text.UTF8Encoding]::new($false).GetBytes(($state | ConvertTo-Json -Compress))
        $stream = [IO.File]::Open((Join-Path $control 'negative-state.json'), 'CreateNew', 'Write', 'None')
        try { $stream.Write($body, 0, $body.Length); $stream.Flush($true) } finally { $stream.Dispose() }
        $null = Read-NegativeSnapshot $control
        # 控制器路径与非秘密快照先持久化到本 job 的恢复入口，再允许变更。
        $entry = [Text.UTF8Encoding]::new($false).GetBytes("AWF_NEGATIVE_CONTROL=$control" + [Environment]::NewLine)
        $environment = [IO.File]::Open($env:GITHUB_ENV, 'Append', 'Write', 'Read')
        try { $environment.Write($entry, 0, $entry.Length); $environment.Flush($true) } finally { $environment.Dispose() }
        $env:AWF_NEGATIVE_CONTROL = $control
        New-Item -ItemType Directory -Path $root | Out-Null
        $password = 'Awf!a9-' + [Convert]::ToHexString([Security.Cryptography.RandomNumberGenerator]::GetBytes(32))
        Write-Host "::add-mask::$password"
        $secure = ConvertTo-SecureString $password -AsPlainText -Force
        $description = "AWF negative $env:GITHUB_RUN_ID/$env:GITHUB_RUN_ATTEMPT $($id.Substring(0, 8))"
        $account = New-LocalUser -Name $name -Password $secure -AccountNeverExpires -PasswordNeverExpires -UserMayNotChangePassword -Description $description
        $users = Get-LocalGroup -SID ([Security.Principal.SecurityIdentifier]::new('S-1-5-32-545'))
        Add-LocalGroupMember -Group $users -Member $account
        $credential = [pscredential]::new("$env:COMPUTERNAME\$name", $secure)
        & "$env:SystemRoot\System32\icacls.exe" $root /grant ('*' + $account.SID.Value + ':(OI)(CI)F') | Out-Host
        if ($LASTEXITCODE -ne 0) { throw '负向测试 SID 的数据目录 ACL 设置失败' }
        Set-NegativeSwitch $false
        Invoke-OrdinaryProbe 'ordinary-denied-only' $credential
        if ($failures.Count) { throw '负向未成立，立即停止能力试探，仅执行恢复' }
        Set-NegativeSwitch $true
        # 此调用只证明恢复后的实际能力；不重跑目录或已赋权正向矩阵。
        Invoke-OrdinaryProbe 'ordinary-restored' $credential
    } catch {
        $failures.Add("negative fixture: $($_.Exception.Message)")
    } finally {
        try {
            if ($env:AWF_NEGATIVE_CONTROL) { Complete-NegativeFixture $false }
            elseif ($controlCreated) {
                # 尚未发布恢复入口时没有修改注册表或创建测试账户；只回收
                # 此函数确证创建的控制器，不留下半写入的无效快照。
                Remove-Item -LiteralPath $control -Recurse -Force
            }
        } catch { $failures.Add("finally restore: $($_.Exception.Message)") }
        $credential = $null; $secure = $null; $password = $null
    }
    if ($failures.Count) { throw ($failures -join '; ') }
    Write-Host '负向能力与恢复调用完成；仍不是中央安装或 npm 最终验收。'
}

if ($Mode -in @('native-negative-fixture', 'native-negative-cleanup')) {
    Assert-HostedEnvironment $true
    if ($Mode -eq 'native-negative-cleanup') { Complete-NegativeFixture $true }
    else { Invoke-NegativeFixture }
    return
}

# 正向后端也由默认 acceptance 消费，允许 main 上同一 hosted/仓库/HEAD
# 绑定；只有会修改 registry 的负向 fixture 和 cleanup 才限制临时分支。
if ($Mode -eq 'native-backend') { Assert-HostedEnvironment $false }

try {
    New-Item -ItemType Directory -Path $root | Out-Null
    # 使用密码学随机值并在任何账户 API 前登记 CI mask；不写源码/文件/交接。
    $password = 'Awf!a9-' + [Convert]::ToHexString([Security.Cryptography.RandomNumberGenerator]::GetBytes(32))
    Write-Host "::add-mask::$password"
    $secure = ConvertTo-SecureString $password -AsPlainText -Force
    $account = New-LocalUser -Name $name -Password $secure -AccountNeverExpires -PasswordNeverExpires -UserMayNotChangePassword -Description 'Agent Workflow disposable capability probe'
    $created = $true
    $sid = $account.SID.Value
    # 只加入内置普通 Users 组，按稳定 SID 解析以兼容不同语言的 Windows。
    $users = Get-LocalGroup -SID ([Security.Principal.SecurityIdentifier]::new('S-1-5-32-545'))
    Add-LocalGroupMember -Group $users -Member $account
    $credential = [pscredential]::new("$env:COMPUTERNAME\$name", $secure)
    # 根目录位于自有盘符根路径，避免 runneradmin profile 父目录 ACL 混入
    # 能力结论；仅授予新测试 SID 对本轮 fixture 的访问，不更改源码 ACL。
    & "$env:SystemRoot\System32\icacls.exe" $root /grant ('*' + $sid + ':(OI)(CI)F') | Out-Host
    if ($LASTEXITCODE -ne 0) { throw '测试 SID 的 fixture ACL 设置失败' }
    Write-Host "宿主管理员 SID: $([Security.Principal.WindowsIdentity]::GetCurrent().User.Value)"
    if ($Mode -eq 'native-backend') {
        # 只运行当前新增真实后端消费者；不重复已经通过的能力/目录矩阵。
        Invoke-OrdinaryProbe 'backend-native' $credential
    } else {
        & $python -I -B -X utf8 $probe --probe host-directory --root $root
        if ($LASTEXITCODE -ne 0) { $failures.Add("host-directory exit=$LASTEXITCODE") }
        Invoke-OrdinaryProbe 'ordinary-denied' $credential
        [AwfProbeRights]::Set($sid, $true)
        $rightsAssigned = $true
        Invoke-OrdinaryProbe 'ordinary-allowed' $credential
    }
} catch {
    $failures.Add("preparation: $($_.Exception.Message)")
} finally {
    $beforeCleanupFailures = $failures.Count
    if ($created) {
        if ($rightsAssigned) {
            try { [AwfProbeRights]::Set($sid, $false) }
            catch { $failures.Add("rights cleanup: $($_.Exception.Message)") }
        }
        try {
            # LoadUserProfile 可能创建临时用户 profile，须在进程全退出后收回。
            Get-CimInstance Win32_UserProfile -Filter "SID='$sid'" | Remove-CimInstance
        } catch { $failures.Add("profile cleanup: $($_.Exception.Message)") }
        try { Remove-LocalUser -Name $name }
        catch { $failures.Add("account cleanup: $($_.Exception.Message)") }
    }
    try {
        if (Test-Path -LiteralPath $root) { Remove-Item -LiteralPath $root -Recurse -Force }
    } catch { $failures.Add("fixture cleanup: $($_.Exception.Message)") }
    $credential = $null
    $secure = $null
    $password = $null
    # 测试失败不等于清理失败。先输出 finally 的实际结果再抛测试错误，
    # 避免失败路径把已经成功收尾的事实一起隐藏；清理错误仍保留并失败。
    if ($failures.Count -eq $beforeCleanupFailures) {
        Write-Host 'finally 清理完成：本轮测试账户、赋权、profile、进程句柄与 fixture 已回收。'
    } else {
        Write-Host 'finally 清理失败：具体错误保留在阶段失败记录中。'
    }
}
if ($failures.Count) { throw ($failures -join '; ') }
Write-Host '能力探针通过；此结果不是中央安装或 npm 最终验收。'
