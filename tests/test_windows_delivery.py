"""Windows curl 交付的真实消费者；便携配置证据不替代原生安装证据。"""

from __future__ import annotations

import base64
import ctypes
from functools import partial
import hashlib
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import ssl
import subprocess
import sys
import tempfile
import threading
import time
import unittest


PACK = Path(__file__).resolve().parents[1]


def python_command():
    # 非 Windows 子消费者沿用仓库运行时入口；Windows 必须使用当前明确的
    # 原生解释器，不经 Git Bash、WSL 或 PATH 上的另一个 Python 冒充消费。
    return ([sys.executable] if os.name == "nt" else
            ["bash", str(PACK / "lib/python_runtime.sh")]) + ["-I", "-B", "-X", "utf8"]


def loopback_environment(environment):
    # Windows 环境变量名不区分大小写；先移除继承环境中 NO_PROXY 的所有别名，
    # 再写唯一规范名。只为本机 HTTPS fixture 绕过代理，不放宽 SDK 对其它重复
    # 环境名的拒绝，也不修改调用者原环境或全局代理设置。
    return {**{key: value for key, value in environment.items() if key.casefold() != "no_proxy"},
            "NO_PROXY": "127.0.0.1,localhost"}


def initial_tui_read_settled(raw):
    # 仅用于本例全新进程、尚未发送任何输入时的首次读取：App.poll_job 完成
    # 回调与 finish_job 后，下一次 draw 才能画出这条成功 toast。标题本身在
    # 作业忙时已经可见，此时 dispatch 会丢弃 q。VT 是累积流，历史忙态不能
    # 用“全文不含执行中”来排除；这里也不把此单次判据扩成通用 TUI 等待器。
    header = raw.find(b"awf-cli")
    settled = raw.find("✔ 已读取预览 / 状态，尚未写入".encode("utf-8"))
    return header >= 0 and settled > header


class ReleaseWorkflowPortableTest(unittest.TestCase):
    def test_release_policy_routes_stable_and_candidate_and_rejects_invalid_identity(self):
        workflow = (PACK / ".github/workflows/release.yml").read_text(encoding="utf-8")
        # 直接执行工作流实际携带的校验代码，避免在测试中复制标签判定算法。
        # 此代码仅写本例 GITHUB_OUTPUT；不调用 gh、创建 tag 或发布任何资产。
        match = re.search(r"          bash lib/python_runtime.sh -B -X utf8 - <<'PY'\n(.*?)          PY\n", workflow, re.S)
        self.assertIsNotNone(match, "发行身份必须在构建和远端写入之前校验")
        code = "\n".join(line[10:] for line in match.group(1).splitlines()) + "\n"
        version = (PACK / "product/VERSION").read_text(encoding="ascii").strip()
        with tempfile.TemporaryDirectory(prefix="awf-release-policy-") as raw:
            root = Path(raw)
            script = root / "identity.py"
            script.write_text(code, encoding="utf-8")
            values = [(version, "", "draft"), (version, f"v{version}-rc.1", "prerelease"),
                      (version, f"v{version}-rc.0", "prerelease"),
                      (version, f"v{version}-rc.01", None), (version, f"v{version}", None),
                      (version, "v99.0.0-rc.1", None), (version, f"v{version}-rc.1\nkind=draft", None),
                      (version, "$(touch unexpected)", None), ("99.0.0", "", None)]
            for number, (requested_version, tag, kind) in enumerate(values):
                with self.subTest(version=requested_version, tag=tag):
                    output = root / f"output-{number}"
                    result = subprocess.run([*python_command(), str(script)], cwd=PACK,
                        env={**os.environ, "RELEASE_VERSION": requested_version,
                             "REQUESTED_RELEASE_TAG": tag, "GITHUB_OUTPUT": str(output)},
                        capture_output=True, text=True, encoding="utf-8", timeout=20)
                    if kind is None:
                        self.assertNotEqual(0, result.returncode, result.stdout + result.stderr)
                        self.assertFalse(output.exists(), "无效身份不得留下可供后续消费的 Actions output")
                    else:
                        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
                        self.assertEqual(f"tag={tag or 'v' + version}\nkind={kind}\n", output.read_text())
        # 这些是发布配置的安全合同：双门禁、远端原子不覆盖、同一 SHA、完整六资产。
        self.assertIn("needs: [validate, windows_gate]", workflow)
        self.assertIn('gh api --method POST "repos/$GH_REPO/git/refs"', workflow)
        self.assertIn('-f "ref=refs/tags/$RELEASE_TAG" -f "sha=$GITHUB_SHA"', workflow)
        self.assertIn('--verify-tag "${visibility[@]}"', workflow)
        self.assertIn('visibility=(--prerelease --latest=false)', workflow)
        self.assertIn('--target "$GITHUB_SHA"', workflow)
        for asset in ('"dist/agent-workflow-$RELEASE_VERSION.tar.gz"',
                      '"dist/agent-workflow-$RELEASE_VERSION.tar.gz.sha256"', 'dist/Formula/awf-cli.rb',
                      '"dist/agent-workflow-windows-$RELEASE_TAG.pyz"',
                      '"dist/install-agent-workflow-$RELEASE_TAG.ps1"',
                      '"dist/agent-workflow-$RELEASE_TAG-manifest.json"'):
            self.assertIn(asset, workflow)
        self.assertNotIn("--clobber", workflow)


class ReleaseHandler(SimpleHTTPRequestHandler):
    """仅绑定本机回环的 HTTPS 资产目录；记录真实请求而不替代 curl 客户端。"""

    def do_GET(self):
        self.server.requests.append(self.path)
        super().do_GET()

    def log_message(self, format, *args):
        print("[fixture HTTPS] " + format % args, flush=True)


@unittest.skipUnless(os.name == "nt", "必须在真实 Windows 执行；Mac 无 pwsh，不构成原生证据")
class WindowsDeliveryNativeTest(unittest.TestCase):
    """精确节点仅由 NATIVE_COMPONENTS 登记；Windows 缺前置能力一律失败。"""

    @classmethod
    def setUpClass(cls):
        spec = importlib.util.spec_from_file_location("windows_delivery_release", PACK / "packaging/build_release.py")
        cls.release = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.release)
        cls.root = Path(tempfile.mkdtemp(prefix="awf-curl-", dir=os.environ.get("AGENT_WORKFLOW_TEST_SCRATCH"))).resolve()
        cls.cleanup_confirmed = True
        cls.addClassCleanup(cls.cleanup_scene)
        cls.assets = cls.root / "assets"
        cls.version = (PACK / "product/VERSION").read_text(encoding="ascii").strip()
        cls.tag = f"v{cls.version}-rc.1"
        # 同一真实发行构建同时产生 PS/pyz/归档，不安装源码仓，也不虚构中央 pin。
        cls.archive, _, _ = cls.release.build(PACK, cls.version, cls.assets, release_tag=cls.tag)
        cls.pyz = cls.assets / f"agent-workflow-windows-{cls.tag}.pyz"
        cls.pwsh = Path(os.environ.get("AGENT_WORKFLOW_PWSH",
            str(Path(os.environ["ProgramFiles"]) / "PowerShell/7/pwsh.exe")))
        if not cls.pwsh.is_absolute() or not cls.pwsh.is_file():
            raise RuntimeError("真实消费需要已有 PowerShell 7+")
        cls.cmd = Path(os.environ["SystemRoot"]) / "System32/cmd.exe"
        if not cls.cmd.is_file() or shutil.which("curl.exe") is None:
            raise RuntimeError("真实消费需要现有 cmd.exe 和 curl.exe")
        cls.cert, cls.key = cls.root / "fixture.pem", cls.root / "fixture-key.pem"
        # .NET 在内存生成短命证书并导出本例文件；不提交私钥、不安装依赖、不读写
        # 用户/系统证书库。Schannel 由测试构建期 --cacert 信任，绝不关闭 TLS 校验。
        certificate = r'''
$ErrorActionPreference = 'Stop'
$rsa = [System.Security.Cryptography.RSA]::Create(2048)
try {
    $request = [System.Security.Cryptography.X509Certificates.CertificateRequest]::new(
        'CN=localhost', $rsa, [System.Security.Cryptography.HashAlgorithmName]::SHA256,
        [System.Security.Cryptography.RSASignaturePadding]::Pkcs1)
    $san = [System.Security.Cryptography.X509Certificates.SubjectAlternativeNameBuilder]::new()
    $san.AddDnsName('localhost')
    $san.AddIpAddress([System.Net.IPAddress]::Loopback)
    $request.CertificateExtensions.Add($san.Build())
    $request.CertificateExtensions.Add([System.Security.Cryptography.X509Certificates.X509BasicConstraintsExtension]::new($true, $false, 0, $true))
    $certificate = $request.CreateSelfSigned([DateTimeOffset]::UtcNow.AddMinutes(-5), [DateTimeOffset]::UtcNow.AddHours(2))
    try {
        $certificatePem = "-----BEGIN CERTIFICATE-----`n" + [Convert]::ToBase64String($certificate.RawData, [Base64FormattingOptions]::InsertLineBreaks) + "`n-----END CERTIFICATE-----`n"
        $keyPem = "-----BEGIN PRIVATE KEY-----`n" + [Convert]::ToBase64String($rsa.ExportPkcs8PrivateKey(), [Base64FormattingOptions]::InsertLineBreaks) + "`n-----END PRIVATE KEY-----`n"
        [System.IO.File]::WriteAllText($env:AWF_CERT_FILE, $certificatePem, [System.Text.Encoding]::ASCII)
        [System.IO.File]::WriteAllText($env:AWF_KEY_FILE, $keyPem, [System.Text.Encoding]::ASCII)
    } finally { $certificate.Dispose() }
} finally { $rsa.Dispose() }
'''
        result = cls.capture_native([str(cls.pwsh), "-NoLogo", "-NoProfile", "-EncodedCommand",
            base64.b64encode(certificate.encode("utf-16-le")).decode("ascii")],
            env={**os.environ, "AWF_CERT_FILE": str(cls.cert), "AWF_KEY_FILE": str(cls.key)},
            timeout=30)
        if result.returncode:
            raise RuntimeError(repr(result.stdout + result.stderr))
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), partial(ReleaseHandler, directory=str(cls.assets)))
        cls.server.requests = []
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(cls.cert, cls.key)
        cls.server.socket = context.wrap_socket(cls.server.socket, server_side=True)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.addClassCleanup(cls.stop_https)

    @classmethod
    def cleanup_scene(cls):
        # 原 Job owner 无法证明归零时不递归回收测试现场；这个场景也不得算作
        # 成功。正常的 HTTPS server 会先停止，所有已知子进程均由 owner 收尾。
        if cls.cleanup_confirmed:
            shutil.rmtree(cls.root)
        else:
            print("[保留未确认收尾的测试现场] " + str(cls.root), flush=True)

    @classmethod
    def capture_native(cls, command, *, env, timeout, cwd=None):
        from lib.install.install_process import capture_process
        from lib.install.windows_process import WindowsJobCleanupError, WindowsJobProcess
        try:
            # 真实 PS/curl/Python/venv/pip 共用原 Windows Job owner；超时只能在
            # 子树归零后传播，禁止 subprocess.run 只杀 PowerShell 留下安装进程。
            if cwd is None:
                return capture_process(command, env=env, timeout=timeout)
            # 原捕获薄桥没有 cwd 参数；需要调用目录负控时直接消费同一 Job
            # owner 已有的 cwd 能力，不临时改变测试父进程或 HTTPS 线程的 cwd。
            process = None
            try:
                process = WindowsJobProcess(command, cwd=cwd, env=env, stdin=subprocess.DEVNULL,
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                output, error = process.communicate(timeout=timeout)
                return subprocess.CompletedProcess(command, process.returncode, output, error)
            finally:
                if process is not None:
                    process.close()
        except WindowsJobCleanupError:
            cls.cleanup_confirmed = False
            raise

    @classmethod
    def stop_https(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=5)
        if cls.thread.is_alive():
            cls.cleanup_confirmed = False
            raise RuntimeError("本例 HTTPS 线程未确认退出，保留夹具")

    def setUp(self):
        self.scene = self.root / self._testMethodName.removeprefix("test_")
        self.scene.mkdir()
        self.home, self.state, self.install = (self.scene / "home", self.scene / "state", self.scene / "程序 空格")
        self.downloads, self.scan = self.scene / "downloads", self.scene / "projects"
        for path in (self.home, self.downloads, self.scan):
            path.mkdir()
        self.env = loopback_environment({**os.environ, "HOME": str(self.home), "USERPROFILE": str(self.home),
            "APPDATA": str(self.home / "AppData/Roaming"), "LOCALAPPDATA": str(self.home / "AppData/Local"),
            "HOMEDRIVE": self.home.drive, "HOMEPATH": str(self.home)[2:],
            "TEMP": str(self.downloads), "TMP": str(self.downloads),
            "CODEX_HOME": str(self.home / ".codex"), "CLAUDE_CONFIG_DIR": str(self.home / ".claude"),
            "PYTHONDONTWRITEBYTECODE": "1", "AGENT_WORKFLOW_PWSH": str(self.pwsh)})
        for key in ("AGENT_WORKFLOW_STATE_DIR", "AGENT_WORKFLOW_RUNTIME_BINDING", "AGENT_WORKFLOW_PROJECT_ROOT",
                    "AGENT_WORKFLOW_CORE_ROOT", "AGENT_WORKFLOW_CONFIG_PATH", "AGENT_WORKFLOW_CALLER_DIR"):
            self.env.pop(key, None)
        self.fields = {"VERSION": self.version, "RELEASE_TAG": self.tag,
            "ARCHIVE_NAME": self.archive.name, "ARCHIVE_SHA256": hashlib.sha256(self.archive.read_bytes()).hexdigest(),
            "PYZ_NAME": self.pyz.name, "PYZ_SHA256": hashlib.sha256(self.pyz.read_bytes()).hexdigest(),
            "BASE_URL": f"https://127.0.0.1:{self.server.server_port}"}

    def record(self, label, command, result):
        record = {"kind": "windows-delivery-consumer", "label": label, "command": command,
                  "exit_code": result.returncode, "stdout": result.stdout, "stderr": result.stderr,
                  # archive 摘要绑定本次真实构建的载荷字节；GITHUB_SHA 只是 CI 的
                  # 来源索引，不能替代资产摘要或把 fixture 成功提升为公开 URL 成功。
                  "delivery_identity": {"source_root": str(PACK), "source_sha": os.environ.get("GITHUB_SHA"),
                      "product_version": self.version, "release_tag": self.tag,
                      "archive": self.archive.name, "archive_sha256": self.fields["ARCHIVE_SHA256"],
                      "pyz": self.pyz.name, "pyz_sha256": self.fields["PYZ_SHA256"]}}
        if hasattr(result, "raw_stdout"):
            record.update(stdout_base64=base64.b64encode(result.raw_stdout).decode("ascii"),
                          stderr_base64=base64.b64encode(result.raw_stderr).decode("ascii"))
        if hasattr(result, "cwd"):
            record["cwd"] = result.cwd
        target = os.environ.get("AWF_TEST_EVIDENCE_LOG")
        if target:
            # CI 只导出生成 PS、已知下载资产和程序收据；证书私钥、宿主配置、环境与整个
            # 私有 state 不进入 artifact。按内容摘要去重，既保留坏资产的原字节，
            # 又不为每个子场景重复复制相同发行包。此目录不参与任何测试选择/执行。
            destination = Path(target).with_suffix(".delivery")
            destination.mkdir(exist_ok=True)
            downloads = []
            for cache in self.downloads.glob("awf-delivery-*"):
                for name in (self.pyz.name, self.archive.name):
                    path = cache / name
                    if not path.is_file():
                        continue
                    body = path.read_bytes()
                    digest = hashlib.sha256(body).hexdigest()
                    exported = destination / (digest + "-" + name)
                    if not exported.exists():
                        with exported.open("xb") as stream:
                            stream.write(body)
                    downloads.append({"source": str(path), "sha256": digest, "artifact": exported.name})
            record["download_evidence"] = downloads
            scripts = []
            for script in self.scene.glob("*.ps1"):
                body = script.read_bytes()
                digest = hashlib.sha256(body).hexdigest()
                exported = destination / (digest + "-" + script.name)
                if not exported.exists():
                    with exported.open("xb") as stream:
                        stream.write(body)
                scripts.append({"source": str(script), "sha256": digest, "artifact": exported.name})
            record["script_evidence"] = scripts
            for receipt in self.install.glob("versions/*/install.json") if self.install.exists() else ():
                body = receipt.read_bytes()
                exported = destination / (hashlib.sha256(body).hexdigest() + "-install.json")
                if not exported.exists():
                    with exported.open("xb") as stream:
                        stream.write(body)
        print(json.dumps(record, ensure_ascii=False), flush=True)
        if target:
            with Path(target).open("a", encoding="utf-8") as stream:
                stream.write(json.dumps(record, ensure_ascii=True) + "\n")

    def execute(self, label, command, *, timeout=1200, cwd=None, env=None):
        try:
            raw = self.capture_native(command, env=self.env if env is None else env, timeout=timeout, cwd=cwd)
        except subprocess.TimeoutExpired as error:
            result = subprocess.CompletedProcess(command, None,
                repr(error.output), "执行超时；原 Job owner 已返回收尾后传播：" + repr(error.stderr))
            self.record(label, command, result)
            raise
        result = subprocess.CompletedProcess(command, raw.returncode,
            raw.stdout.decode("utf-8", errors="replace"), raw.stderr.decode("utf-8", errors="replace"))
        result.raw_stdout, result.raw_stderr = raw.stdout, raw.stderr
        result.cwd = str(cwd) if cwd is not None else None
        self.record(label, command, result)
        return result

    def render(self, name, *, changes=None, stdin_fault=False, trusted_ca=True, replace_cached_pyz=False):
        fields = {**self.fields, **(changes or {})}
        body = self.release.render_windows_installer(PACK, fields,
            test_ca_path=str(self.cert) if trusted_ca else None).decode("utf-8")
        if replace_cached_pyz:
            # 只替换已校验之后的下载路径；生产 loader/内存字节/摘要逻辑均未修改。
            # 随后的真实重复安装必须仍成功，以区分“执行同一字节”和重新信任路径。
            anchor = "    $phase = 'download-archive'"
            self.assertEqual(1, body.count(anchor))
            body = body.replace(anchor, "    [System.IO.File]::WriteAllBytes($pyzPath, [byte[]]@(0))\n" + anchor)
        if stdin_fault:
            # 仅修改本例生成的 PS，在真实 Process.Start 后关闭 stdin 并确认该
            # 空输入 Python 已退出，再触发真实 .NET Write 异常。签名、loader、摘要
            # 与生产模板不变；此例只证明 PS 的未知生命周期分支，不能宣称引擎取消。
            anchor = "        $process.StandardInput.Write($loader)"
            self.assertEqual(1, body.count(anchor))
            body = body.replace(anchor,
                "        $process.StandardInput.Close()\n"
                "        $process.WaitForExit()\n"
                "        [Console]::Error.WriteLine('[TEST] fault_child_exit=' + $process.ExitCode)\n" + anchor)
        path = self.scene / (name + ".ps1")
        # 渲染器保留模板原始 CRLF；Windows 的 write_text 会再次把 LF 换成
        # CRLF，制造 CRCRLF 并破坏 PowerShell 反引号续行。这里只写渲染后的
        # 原字节，包含测试注入也不再经过平台文本换行转换。
        path.write_bytes(body.encode("utf-8"))
        return path

    def install_via_ps(self, script, *, install_root=None, legacy=False):
        arguments = ["-Python", sys.executable, "-InstallRoot", str(install_root or self.install),
                     "-StateDir", str(self.state), "-HostHome", str(self.home), "-Json"]
        entry = script
        if legacy:
            # 仅首次真实安装使用 Legacy 参数路径；设置只存在于本例 pwsh 子进程，
            # 不写 profile 或宿主偏好。逐项参数转发，不把中文路径拼成 shell 源码。
            # 这证明现有 pwsh 的 Legacy 行为，不等于运行过旧版 PS7.0 二进制。
            entry = self.scene / "legacy-first-install.ps1"
            entry.write_text(r'''param(
    [string]$Installer, [string]$Python, [string]$InstallRoot,
    [string]$StateDir, [string]$HostHome, [switch]$Json
)
$ErrorActionPreference = 'Stop'
$global:PSNativeCommandArgumentPassing = 'Legacy'
[Console]::Error.WriteLine('[TEST] first-install PSNativeCommandArgumentPassing=' + $global:PSNativeCommandArgumentPassing)
& $Installer -Python $Python -InstallRoot $InstallRoot -StateDir $StateDir -HostHome $HostHome -Json:$Json
exit $LASTEXITCODE
''', encoding="utf-8")
            arguments = ["-Installer", str(script), *arguments]
        return self.execute(script.stem, [str(self.pwsh), "-NoLogo", "-NoProfile", "-File", str(entry), *arguments])

    def snapshot(self, root):
        return {path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
                for path in root.rglob("*") if path.is_file()} if root.exists() else {}

    def installed_cmd(self, label, arguments, *, cwd):
        # 复用既有 Windows 源码入口测试的 cmd 单次引用规则：/d 禁用 AutoRun，
        # /v:off 禁用延迟展开，内层引号不再经过 C-runtime argv 编码器改写。
        quoted = []
        for argument in arguments:
            self.assertFalse(any(char in argument for char in ('"', '\r', '\n')))
            trailing = len(argument) - len(argument.rstrip('\\'))
            quoted.append('"' + argument + '\\' * trailing + '"')
        command = f'"{self.cmd}" /d /v:off /c ""{self.install / "bin/awf-cli.cmd"}" ' + ' '.join(quoted) + '"'
        return self.execute(label, command, cwd=cwd)

    def installed_legacy(self, label, arguments):
        launcher = self.install / "bin/awf-cli.ps1"
        environment = {**self.env, "AWF_DELIVERY_TEST_SCRIPT": str(launcher),
            "AWF_DELIVERY_TEST_ARGV": json.dumps(arguments, ensure_ascii=False),
            "AWF_DELIVERY_TEST_CWD": str(self.scene)}
        # PS7.0/Legacy 模式只作用于本子进程。参数经 JSON 传给 PS 字符串数组，
        # 受验者是安装产出的正式入口。故意让初始 OS cwd 与 Set-Location 不同，
        # 让相对扫描根能够验证正式入口采用调用者的真实 FileSystem 位置。
        script = ("$ErrorActionPreference='Stop';$global:PSNativeCommandArgumentPassing='Legacy';"
            "[Console]::Error.WriteLine('[TEST] installed-launcher PSNativeCommandArgumentPassing=Legacy');"
            "Set-Location -LiteralPath $env:AWF_DELIVERY_TEST_CWD;"
            "$vector=@(ConvertFrom-Json -InputObject $env:AWF_DELIVERY_TEST_ARGV);"
            "& $env:AWF_DELIVERY_TEST_SCRIPT @vector;exit $LASTEXITCODE")
        encoded = base64.b64encode(script.encode("utf-16-le")).decode("ascii")
        result = self.execute(label, [str(self.pwsh), "-NoLogo", "-NoProfile", "-NonInteractive",
            "-EncodedCommand", encoded], env=environment, cwd=self.home)
        self.assertIn("[TEST] installed-launcher PSNativeCommandArgumentPassing=Legacy", result.stderr)
        return result

    def reject_shared_empty_root(self, script, installed_before):
        from lib import windows_fs as fs
        shared = self.scene / "shared-empty-root"
        fs.secure_os.mkdir(shared, 0o700)
        fs.assert_private(shared)

        def observe():
            # 原句柄边界读取完整 owner/control/DACL 字节；比较不只依赖摘要或
            # POSIX mode。日志只公开摘要和目录身份，不写出本机用户 SID 正文。
            with fs.Directory(shared) as directory, fs._security_policy(directory.handle) as policy:
                return {"identity": directory.identity, "owner": policy.owner,
                        "control": policy.control, "acl": policy.acl_bytes, "security": policy.fingerprint}

        private_before = observe()
        handle = fs._open_handle(shared, 0x60080, directory=True)
        descriptor = fs.HANDLE()
        try:
            # 复用既有 WindowsRuntime 原生夹具的 SDDL/SetSecurityInfo 授权方式。
            # 只给本例新建空目录增加 Everyone 完全控制（含写入、删除子项），
            # 不操作系统/用户目录，不改变 owner，也不让生产代码修正这份未知 ACL。
            api = fs._api()
            sid = fs.current_sid()
            sddl = f"D:P(A;OICI;GA;;;{sid})(A;OICI;GA;;;SY)(A;OICI;GA;;;WD)"
            self.assertTrue(api.security.ConvertStringSecurityDescriptorToSecurityDescriptorW(
                sddl, 1, ctypes.byref(descriptor), None))
            self.assertEqual(0, api.security.SetSecurityInfo(handle, 1, 0x80000004,
                None, None, fs._dacl(descriptor), None), "无法为自有空根准备真实弱 ACL 负控")
        finally:
            if descriptor.value:
                fs._api().kernel.LocalFree(descriptor)
            fs._close(handle)
        weak_before = observe()
        self.assertEqual(private_before["identity"], weak_before["identity"])
        self.assertEqual(private_before["owner"], weak_before["owner"])
        self.assertNotEqual(private_before["acl"], weak_before["acl"])
        with self.assertRaises(ValueError):
            fs.assert_private(shared)
        self.assertEqual([], list(shared.iterdir()))
        failed = self.install_via_ps(script, install_root=shared)
        self.assertEqual(2, failed.returncode, failed.stdout + failed.stderr)
        value = json.loads(failed.stdout)
        self.assertEqual((False, "preflight", 2), (value["ok"], value["phase"], value["exit_code"]))
        self.assertIn("private Windows node requires current-user/SYSTEM protected DACL", value["error"])
        self.assertIsNone(value["retained_version_root"])
        self.assertEqual([], list(shared.iterdir()), "弱 ACL 拒绝前不得写 root marker、bin 或 versions")
        after = observe()
        self.assertEqual(weak_before, after, "拒绝必须保全原目录身份、owner、控制位和完整 DACL")
        self.assertEqual(installed_before, (self.snapshot(self.install), self.snapshot(self.state)))
        print("[native shared-root preserved] " + json.dumps({"identity": after["identity"],
            "private_security_sha256": private_before["security"], "weak_security_sha256": weak_before["security"],
            "after_security_sha256": after["security"], "grant": "Everyone OICI GA (includes write/delete-child)",
            "phase": value["phase"], "exit_code": failed.returncode, "root_empty": True}, ensure_ascii=False), flush=True)

    def tui_smoke(self, version_root):
        from tests.windows_conpty import ConPTYProcess
        self.assertEqual([], list(self.scan.iterdir()), "只读参数用例的临时项目必须先回收，TUI 使用正常空扫描根")
        python = version_root / "venv/Scripts/python.exe"
        argv = [str(python), "-I", "-B", "-X", "utf8", str(version_root / "payload/workflow.py"),
                "--state-dir", str(self.state), "--host-home", str(self.home),
                "--scan-root", str(self.scan), "tui"]
        process = ConPTYProcess(argv, cwd=self.scene, env=self.env, columns=120, rows=36)
        ready_vt_bytes, q_accepted_bytes = None, None
        try:
            # 等待本次初始只读作业真正结算后才发 q；标题/首帧不能证明输入就绪。
            # 仍只进入/退出，不复制已有完整生命周期，也不延长原等待或退出预算。
            deadline = time.monotonic() + 30
            while time.monotonic() < deadline:
                output = process.raw_output
                if initial_tui_read_settled(output):
                    ready_vt_bytes = len(output)
                    break
                if process.returncode is not None:
                    self.fail("安装后 TUI 在初始读取结算前退出：" + repr(output))
                time.sleep(0.05)
            else:
                self.fail("安装后 TUI 初始读取结算超时：" + repr(process.raw_output[-4000:]))
            q_accepted_bytes = process.write("q")
            self.assertEqual(1, q_accepted_bytes)
            self.assertEqual(0, process.wait(timeout=15), repr(process.raw_output))
            self.assertTrue(process.closed)
        finally:
            try:
                process.close()
            except BaseException:
                # ConPTY 的关闭证明失败同样不能靠 TemporaryDirectory 清理掩盖。
                type(self).cleanup_confirmed = False
                raise
            raw = process.raw_output
            result = subprocess.CompletedProcess(argv, process.returncode, base64.b64encode(raw).decode("ascii"),
                "raw_stdout_encoding=base64; owner=ConPTYProcess; closed=" + str(process.closed)
                + "; initial_read_settled_vt_bytes=" + str(ready_vt_bytes) + "; q_accepted_bytes=" + str(q_accepted_bytes))
            self.record("installed-tui-q", argv, result)

    def test_https_install_cli_repeat_and_failure_preservation(self):
        script = self.render("install")
        result = self.install_via_ps(script, legacy=True)
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        self.assertIn("[TEST] first-install PSNativeCommandArgumentPassing=Legacy", result.stderr)
        value = json.loads(result.stdout)
        self.assertEqual((True, "complete", 0), (value["ok"], value["phase"], value["exit_code"]))
        version_root = Path(value["version_root"])
        self.assertEqual(self.install / "versions" / (self.version + "-" + self.fields["ARCHIVE_SHA256"]), version_root)
        self.assertEqual(self.version, json.loads((version_root / "payload/manager/release.json").read_bytes())["version"])
        self.assertIn("phase=engine-exited", result.stderr)
        self.assertIn("确认无安装进程后删除", result.stderr)
        self.assertNotIn("暂勿删除", result.stderr)
        caches = list(self.downloads.glob("awf-delivery-*"))
        self.assertEqual(1, len(caches))
        self.assertEqual(self.pyz.read_bytes(), (caches[0] / self.pyz.name).read_bytes())
        self.assertEqual(self.archive.read_bytes(), (caches[0] / self.archive.name).read_bytes())
        self.assertIn("/" + self.pyz.name, self.server.requests)
        self.assertIn("/" + self.archive.name, self.server.requests)
        launcher = self.install / "bin/awf-cli.ps1"
        version = self.execute("installed-ps-version", [str(self.pwsh), "-NoLogo", "-NoProfile", "-File", str(launcher), "--version"])
        self.assertEqual(0, version.returncode, version.stdout + version.stderr)
        self.assertIn("awf-cli " + self.version, version.stdout)
        self.assertNotIn("源码未打包", version.stdout)
        self.assertNotIn(str(PACK), version.stdout)
        shadow = self.scene / "cmd-shadow"
        shadow.mkdir()
        decoy = shadow / "pwsh.exe"
        decoy.write_bytes(b"invalid executable: cwd must not select this pwsh")
        cmd_version = self.installed_cmd("installed-cmd-version-with-cwd-shadow", ["--version"], cwd=shadow)
        self.assertEqual(0, cmd_version.returncode, cmd_version.stdout + cmd_version.stderr)
        self.assertEqual(version.stdout, cmd_version.stdout)
        self.assertEqual(b"invalid executable: cwd must not select this pwsh", decoy.read_bytes())
        listing = self.installed_cmd("installed-cmd-list", ["--json", "--scan-root", str(self.scan), "list"], cwd=shadow)
        self.assertEqual(0, listing.returncode, listing.stdout + listing.stderr)
        self.assertEqual([], json.loads(listing.stdout)["result"])
        legacy_version = self.installed_legacy("installed-legacy-version", ["--version"])
        self.assertEqual(0, legacy_version.returncode, legacy_version.stdout + legacy_version.stderr)
        self.assertEqual(version.stdout, legacy_version.stdout)
        with tempfile.TemporaryDirectory(prefix="caller-project-", dir=self.scan) as raw:
            project = Path(raw)
            marker = project / ".agent-workflow/project.yaml"
            marker.parent.mkdir()
            marker.write_text("schema: 1\n", encoding="utf-8")
            original = marker.read_bytes()
            legacy_list = self.installed_legacy("installed-legacy-relative-list", ["--json", "--scan-root", "projects", "list"])
            self.assertEqual(0, legacy_list.returncode, legacy_list.stdout + legacy_list.stderr)
            self.assertEqual([str(project.resolve())], [row["project"] for row in json.loads(legacy_list.stdout)["result"]])
            self.assertEqual(original, marker.read_bytes())
        from tests.test_windows_native_entry import LITERAL
        for label, arguments in (("quoted-argument", ["list", "--unexpected", LITERAL]),
                                 ("empty-argument", ["list", ""])):
            with self.subTest(legacy_boundary=label):
                rejected = self.installed_legacy("installed-legacy-" + label, arguments)
                self.assertEqual(2, rejected.returncode, rejected.stdout + rejected.stderr)
                if label == "quoted-argument":
                    self.assertIn(LITERAL, rejected.stderr)
        status = self.execute("installed-runtime-status", [str(self.pwsh), "-NoLogo", "-NoProfile", "-File", str(launcher), "--json", "runtime", "status"])
        self.assertEqual(0, status.returncode, status.stdout + status.stderr)
        central = json.loads(status.stdout)["result"]
        self.assertEqual(value["runtime_binding"], central["runtime_binding"])
        self.assertTrue(central["new_task_allowed"])
        dependency = self.execute("installed-private-runtime", [str(version_root / "venv/Scripts/python.exe"), "-I", "-B", "-X", "utf8", "-c",
            "import importlib.metadata,json,sys;print(json.dumps({'python':sys.executable,'curses':importlib.metadata.version('windows-curses')}))"])
        self.assertEqual(0, dependency.returncode, dependency.stdout + dependency.stderr)
        self.assertEqual({"python": str(version_root / "venv/Scripts/python.exe"), "curses": "2.4.2"}, json.loads(dependency.stdout))
        self.tui_smoke(version_root)
        interpreter = version_root / "venv/Scripts/python.exe"
        before_python = interpreter.stat()
        repeated = self.install_via_ps(self.render("repeat-with-replaced-cache", replace_cached_pyz=True))
        self.assertEqual(0, repeated.returncode, repeated.stdout + repeated.stderr)
        self.assertEqual(str(version_root), json.loads(repeated.stdout)["version_root"])
        self.assertEqual((before_python.st_ino, before_python.st_mtime_ns), (interpreter.stat().st_ino, interpreter.stat().st_mtime_ns))
        self.assertIn(b"\0", [(path / self.pyz.name).read_bytes() for path in self.downloads.glob("awf-delivery-*")])
        before = self.snapshot(self.install), self.snapshot(self.state)
        # 失败均经过真实 HTTPS/curl 与生产 PS；坏 pyz 在执行前拒绝，坏 tar 由
        # 真实引擎校验拒绝，TLS 未受信控制必须失败。旧入口/中央快照不能变化。
        for name, changes, trusted_ca, expected in (
            ("bad-pyz", {"PYZ_SHA256": "0" * 64}, True, "安装器 SHA256 不匹配"),
            ("bad-archive", {}, True, "SHA256"),
            ("untrusted-tls", {}, False, "curl"),
        ):
            with self.subTest(failure=name):
                original_archive = self.archive.read_bytes()
                try:
                    if name == "bad-archive":
                        # 保留 pyz 固定身份，只改变 HTTPS 服务器实际发送的归档，
                        # 使真实引擎的同流 hash 拒绝成为本负控的唯一预期结果。
                        self.archive.write_bytes(original_archive + b"corrupt")
                    failed = self.install_via_ps(self.render(name, changes=changes, trusted_ca=trusted_ca))
                finally:
                    if name == "bad-archive":
                        self.archive.write_bytes(original_archive)
                self.assertNotEqual(0, failed.returncode, failed.stdout + failed.stderr)
                self.assertIn(expected, failed.stdout + failed.stderr)
                self.assertEqual(before, (self.snapshot(self.install), self.snapshot(self.state)))
        foreign = self.scene / "foreign"
        (foreign / "bin").mkdir(parents=True)
        old_entry = foreign / "bin/awf-cli.cmd"
        old_entry.write_bytes(b"@echo foreign entry\r\n")
        original = self.snapshot(foreign)
        failed = self.install_via_ps(script, install_root=foreign)
        self.assertNotEqual(0, failed.returncode, failed.stdout + failed.stderr)
        self.assertEqual(original, self.snapshot(foreign))
        self.assertEqual(before[1], self.snapshot(self.state))
        self.reject_shared_empty_root(script, before)

    def test_real_child_stdin_failure_retains_unknown_lifecycle_scene(self):
        failed = self.install_via_ps(self.render("stdin-fault", stdin_fault=True))
        self.assertEqual(2, failed.returncode, failed.stdout + failed.stderr)
        self.assertEqual("", failed.stdout, "-Json 不得混入薄 PS 的恢复提示")
        self.assertIn("[TEST] fault_child_exit=0", failed.stderr, "必须先确认本例真实 Python 子进程退出才允许测试回收")
        self.assertIn("phase=engine-running", failed.stderr)
        self.assertIn("未确认退出，暂勿删除", failed.stderr)
        self.assertNotIn("确认无安装进程后删除", failed.stderr)
        caches = list(self.downloads.glob("awf-delivery-*"))
        self.assertEqual(1, len(caches))
        self.assertEqual(self.pyz.read_bytes(), (caches[0] / self.pyz.name).read_bytes())
        self.assertEqual(self.archive.read_bytes(), (caches[0] / self.archive.name).read_bytes())
        self.assertFalse(self.install.exists())
        self.assertFalse(self.state.exists())


if __name__ == "__main__":
    unittest.main()
