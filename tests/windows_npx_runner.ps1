# 此脚本仅在一次性 GitHub Windows runner 中验证真实账户能力。
# 产品安装器不会调用此脚本、创建账户或修改任何账户权限。
param(
    [ValidateSet('native-capabilities')]
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
$probe = Join-Path $PSScriptRoot 'test_windows_central_fs.py'
$name = 'awfprobe' + [guid]::NewGuid().ToString('N').Substring(0, 10)
$root = Join-Path ($env:SystemDrive + '\') ('awf-capabilities-' + [guid]::NewGuid().ToString('N'))
$created = $false
$rightsAssigned = $false
$sid = $null
$failures = [Collections.Generic.List[string]]::new()

# LSA 修改限定为刚创建的随机测试 SID。禁止使用本 helper 更改 runner
# 或任何现有账户；finally 先移除该 SID 的赋权再删除账户与 profile。
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

function Invoke-OrdinaryProbe([string]$Stage, [pscredential]$Credential) {
    $stdout = Join-Path $root ($Stage + '.stdout.log')
    $stderr = Join-Path $root ($Stage + '.stderr.log')
    $process = $null
    try {
        # 每阶段都重新登录；先无权限、后赋权后的新令牌，不能复用缓存令牌。
        # 参数只含本轮路径与固定枚举；凭证只经 Credential API 传递。
        $arguments = '-I -B "' + $probe + '" --probe ' + $Stage + ' --root "' + $root + '"'
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
    & $python -I -B $probe --probe host-directory --root $root
    if ($LASTEXITCODE -ne 0) { $failures.Add("host-directory exit=$LASTEXITCODE") }
    Invoke-OrdinaryProbe 'ordinary-denied' $credential
    [AwfProbeRights]::Set($sid, $true)
    $rightsAssigned = $true
    Invoke-OrdinaryProbe 'ordinary-allowed' $credential
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
