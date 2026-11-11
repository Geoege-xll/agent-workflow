"""Windows curl 交付的真实消费者；便携配置证据不替代原生安装证据。"""

from __future__ import annotations

import base64
import ctypes
from functools import partial
import gzip
import hashlib
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import importlib.util
import io
import json
import os
from pathlib import Path
import re
import shutil
import ssl
import subprocess
import sys
import tarfile
import tempfile
import threading
import time
import unittest
import uuid
import zipfile


PACK = Path(__file__).resolve().parents[1]


# 固定失败诊断只在已失败的升级后运行；证据输出目录独立于 state/宿主根。
# 不导入另一套 runner、不取得协调锁，也不调用任何 apply/recover/save 入口。
UPGRADE_STATE_DIAGNOSTIC = r'''
import hashlib
import json
from pathlib import Path
import stat
import sys
import traceback

payload, state, home, evidence = map(Path, sys.argv[1:5])
content_id, engine_phase = sys.argv[5:7]
sys.path.insert(0, str(payload))
from lib import role_models, runtime_store
from lib.central.runtime_project import LIMIT, Node, Tree, identity, unique_json
from lib.hosts import native_agents as native
from lib.hosts.native_context import HostPaths, NativeContext
from lib.platform_fs import os
from manager import central_runtime, native_agents, runtime_policy

context = NativeContext.for_state(state, host_paths=HostPaths.for_home(home, environment={}))
errors = []
def emit(step, **value):
    print(json.dumps({'step': step, **value}, ensure_ascii=False), flush=True)

def attempt(label, function):
    # 每个独立事实保留完整原 traceback；读取一处失败不能阻断其它已授权根。
    # 不吞掉诊断失败：末尾非零退出；父测试仍保留最初升级 FAIL 和其余四诊断。
    try:
        return function()
    except Exception:
        errors.append(label)
        emit('state-read-error', fact=label)
        traceback.print_exc()
        return None

def fact(node):
    return {'kind': node.kind, 'mode': node.mode, 'identity': list(node.identity),
            'security': node.security, 'bytes': len(node.payload),
            'sha256': hashlib.sha256(node.payload).hexdigest()}

def snapshot():
    # 仅完整遍历本例显式授权的 state 和三个 HostPaths 根，不遍历 HOME。
    # Tree 锚定每级目录且拒绝换链；文件使用既有有界 reader，不跟随未知链接。
    # atime 不属身份，正常读取不会误报写入；ACL 摘要使用原 SDK 而非复制权限判定。
    result = {}
    for label, root in [('state', state), *((host, context.host_paths.root(host)) for host in role_models.HOSTS)]:
        rows = {}
        result[label] = rows
        def collect():
            try:
                with Tree(root) as tree:
                    pending = ['']
                    while pending:
                        relative = pending.pop()
                        descriptor = tree.directory(relative)
                        info = os.fstat(descriptor)
                        rows[relative] = {'kind': 'directory', 'identity': list(identity(info)),
                                          'security': list(runtime_store._security(descriptor))}
                        for name in sorted(os.listdir(descriptor)):
                            child = relative + '/' + name if relative else name
                            if sum(map(len, result.values())) > 10000:
                                raise ValueError('只读快照条目超过固定诊断预算，不能声称完整零写')
                            observed = os.stat(name, dir_fd=descriptor, follow_symlinks=False)
                            if stat.S_ISDIR(observed.st_mode):
                                pending.append(child)
                            else:
                                value = attempt(label + '/' + child, lambda: tree.read(child, skill_link=True, max_bytes=2 * LIMIT))
                                rows[child] = fact(value) if value is not None else {'read_error': True}
            except FileNotFoundError:
                # 只有根自身缺失才是有效事实；子目录中途消失必须保留失败。
                if root.exists():
                    raise
                rows[''] = {'kind': 'missing'}
        attempt('snapshot-' + label, collect)
    return result

def save_node(name, node):
    # 只把三个固定记录的原始有界 bytes 写入本例证据目录，不写回其来源。
    # 文件名由测试代码固定；不使用记录正文中的路径生成 artifact 路径。
    if node.kind == 'file':
        with (evidence / name).open('xb') as stream:
            stream.write(node.payload)
    emit('raw-state-node', artifact=name if node.kind == 'file' else None, **fact(node))
    return node

def read_raw(root, relative, name):
    with Tree(root) as tree:
        return save_node(name, tree.read(relative))

emit('state-diagnostic-context', python=sys.executable, payload=str(payload), state=str(state),
     home=str(home), target_content_id=content_id, engine_phase=engine_phase)
before_errors = len(errors)
before = snapshot()
before_complete = len(errors) == before_errors
activation_node = attempt('raw-activation', lambda: read_raw(state, runtime_policy.ACTIVATION, 'activation.json'))
current_node = attempt('raw-current', lambda: read_raw(state, runtime_policy.CURRENT, 'current.json'))
activation = attempt('validate-activation', lambda: central_runtime._validate_journal(unique_json(activation_node.payload))) if activation_node and activation_node.kind == 'file' else None
current = attempt('validate-current', lambda: runtime_policy.validate_current(unique_json(current_node.payload))) if current_node and current_node.kind == 'file' else None
if activation is not None:
    emit('central-persistent-stop', phase=activation['phase'], action=activation['action'],
         activation_id=activation['id'], activation_content_id=activation['runtime_binding']['content_id'],
         activation_matches_target=activation['runtime_binding']['content_id'] == content_id,
         conflicts=activation['conflicts'], current_generation=current['generation'] if current else None,
         generation_matches_activation=current['generation'] == activation['id'] if current else None,
         current_content_id=current['runtime_binding']['content_id'] if current else None)

    def authorized_ref():
        # 先限定 state、宿主根和精确 nonce，允许即使完整 loader 拒绝正文也保存
        # 原 wire；此头校验绝不授权读取日志中的 target/stage/held/retained。
        ref = activation['native_ref']
        if (not isinstance(ref, dict) or ref.get('schema_version') != 1 or ref.get('state') != str(state)
                or not isinstance(ref.get('targets'), list)):
            raise ValueError('取证 native_ref 未限定同一显式 state')
        for target in ref['targets']:
            if (not isinstance(target, dict) or set(target) != {'host', 'native_root'}
                    or target['host'] not in role_models.HOSTS
                    or target['native_root'] != str(context.host_paths.root(target['host']))):
                raise ValueError('取证 native_ref 超出显式 HostPaths')
        relative = native_agents._journal_relative(ref['transaction_id'])
        attempt('raw-native-wire', lambda: read_raw(state, relative, 'native-wire.json'))
        return ref

    ref = attempt('native-ref-header', authorized_ref)
    loaded = attempt('native-load-ref', lambda: native_agents._load_ref(ref, context)) if ref is not None else None
    if loaded is not None and loaded[1] is not None:
        journal = loaded[1]
        emit('native-persistent-stop', transaction_id=journal['transaction_id'], status=journal['status'],
             conflicts=journal['conflicts'], root_identities=journal['root_identities'],
             writes=len(journal['writes']), compensations=len(journal.get('compensations', [])))
        # 只有完整 _load_ref 验证成功后，日志登记的同父临时节点才获准 fresh 读。
        # 每行拆开输出以保留已推进字段；不把 planned Node 当成实际磁盘事实。
        for group, node_keys in [('writes', ('before', 'after', 'published', 'staged', 'restored')),
                                  ('compensations', ('expected', 'after', 'staged', 'isolated', 'result'))]:
            for number, row in enumerate(journal.get(group, [])):
                emit('native-row', group=group, row=number, root=row['root'], path=row['path'],
                     returned=row.get('returned'), stage=row.get('stage'), held=row.get('held'))
                for key in node_keys:
                    if row.get(key) is not None:
                        attempt(group + '-node-' + str(number) + '-' + key,
                                lambda: emit('native-recorded-node', group=group, row=number, field=key,
                                             **fact(Node.from_value(row[key]))))
                paths = [('target', row['path'])] + [(key, row[key]) for key in ('stage', 'held') if row.get(key) is not None]
                for number_retained, retained in enumerate(row.get('retained', [])):
                    attempt('retained-recorded-node', lambda: emit('native-recorded-node', group=group, row=number,
                            field='retained-' + str(number_retained), **fact(Node.from_value(retained['expected']))))
                    paths.append(('retained-' + str(number_retained), retained['path']))
                for field, relative in paths:
                    attempt(group + '-actual-' + str(number) + '-' + field,
                            lambda: emit('native-actual-node', group=group, row=number, field=field,
                                         root=row['root'], path=relative, **fact(native.read_node(Path(row['root']), relative))))
        attempt('native-verify-global', lambda: emit('native-verification', conflicts=native_agents.verify_global(ref, context=context)))

# owner/index 根授权独立于日志是否能加载；即使一个宿主损坏仍继续其它宿主。
for host in role_models.HOSTS:
    root = context.host_paths.root(host)
    owner = attempt(host + '-owner', lambda: native.read_node(root, native.OWNER))
    index = attempt(host + '-index', lambda: native.read_node(state, native.record_relative(root)))
    if owner is not None:
        emit('host-owner', host=host, root=str(root), **fact(owner))
    if index is not None:
        emit('host-index', host=host, path=native.record_relative(root), **fact(index))
    if owner is not None and index is not None:
        emit('host-owner-index-conditions', host=host, payload_equal=owner.payload == index.payload,
             owner_is_file=owner.kind == 'file', owner_mode=owner.mode, owner_mode_is_0600=owner.mode == 0o600,
             index_kind=index.kind, index_mode=index.mode, owner_without_index=index.kind == 'missing' and owner.kind != 'missing')
        attempt(host + '-parse-index', lambda: emit('host-index-validation', host=host,
                valid=native.parse_record(index, state=state, root=root, host=host, identity=native.root_identity(root)) is not None))

after_errors = len(errors)
after = snapshot()
after_complete = len(errors) == after_errors
# 保存完整逐节点摘要，供复核差异；不导出整私有 state 或任意宿主正文。
with (evidence / 'snapshots.json').open('x', encoding='utf-8') as stream:
    json.dump({'before': before, 'after': after, 'before_complete': before_complete,
               'after_complete': after_complete}, stream, ensure_ascii=False, sort_keys=True, indent=2)
unchanged = before_complete and after_complete and before == after
emit('state-host-zero-write', unchanged=unchanged, before_complete=before_complete,
     after_complete=after_complete, errors=errors)
assert unchanged, '只读诊断未证明完整 state/宿主零写；保留前后快照及原始 traceback'
if errors:
    raise RuntimeError('只读诊断部分事实读取失败：' + ', '.join(errors))
'''


# 只在真实升级已经失败后，由现有 execute/Job 调用的固定只读诊断代码。
# 两个解释器均以 argv 接收同一新 payload/state/home/CID，不拼接路径到代码，
# 不创建第二测试实例，也不把诊断成功或失败算作安装/激活重试。
UPGRADE_READ_ONLY_DIAGNOSTIC = r'''
import copy
import json
from pathlib import Path
import sys

payload, state, home = map(Path, sys.argv[1:4])
content_id, mode = sys.argv[4:6]
# -I 保证标准库隔离；业务模块只来自同一份新物理 payload，旧/新解释器的
# 对照仅改变 sys.executable，不混入旧 payload 或源码仓的业务实现。
sys.path.insert(0, str(payload))
from lib.hosts.native_context import HostPaths, NativeContext
from manager import central_runtime, native_agents, project_service

# 显式 HostPaths 是原 CLI --host-home 的同一边界，不读取真实用户宿主覆盖。
context = NativeContext.for_state(state, host_paths=HostPaths.for_home(home, environment={}))
binding = project_service.runtime_binding(state, content_id)
print(json.dumps({'step': 'context', 'python': sys.executable, 'payload': str(payload),
                  'state': str(state), 'home': str(home), 'binding': binding, 'mode': mode},
                 ensure_ascii=False), flush=True)

original_json_bytes = native_agents.json_bytes
def observe_json_bytes(value, **kwargs):
    # 已核实真实 json_bytes：ensure_ascii=False、sort_keys=True、indent=2、
    # 末尾 LF，再以 UTF-8 编码。先仅在 RAM 测长，才能在原4MiB拒绝前留证。
    # deepcopy 只投影“已发布行的 staged=None”，不改原对象/Node/编译器/归属；
    # 不调用 _save，不把投影当作可应用记录。最后仍调用原函数保留真实异常。
    if isinstance(value, dict) and isinstance(value.get('writes'), list):
        wire = (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + '\n').encode('utf-8')
        projected = copy.deepcopy(value)
        cleared = 0
        for row in projected['writes']:
            if isinstance(row, dict) and row.get('published') is not None:
                row['staged'] = None
                cleared += 1
        smaller = (json.dumps(projected, ensure_ascii=False, sort_keys=True, indent=2) + '\n').encode('utf-8')
        print(json.dumps({'step': 'native-wire-size', 'status': value.get('status'),
                          'writes': len(value['writes']), 'compensations': len(value.get('compensations', [])),
                          'wire_bytes': len(wire), 'published_staged_none_bytes': len(smaller),
                          'published_rows': cleared}, ensure_ascii=False), flush=True)
    return original_json_bytes(value, **kwargs)

# 观察器仅存于这个短命诊断子进程；不替换生产源码或持久状态中的任何入口。
native_agents.json_bytes = observe_json_bytes
native_plan = native_agents.preview_global(state, binding, context=context)
summary = native_plan.summary
print(json.dumps({'step': 'native-preview', 'summary': summary,
                  'preview_write_count': sum(row.get('operation') == 'write' for row in summary['changes']),
                  'desired_resources': len(native_plan.desired)}, ensure_ascii=False), flush=True)
if mode == 'native-budget':
    print(json.dumps({'step': 'native-receipt-budget', 'bytes': native_agents.receipt_budget(native_plan)}), flush=True)
elif mode == 'central-preview':
    central_plan = central_runtime.preview(state, 'activate', binding=binding, native_context=context)
    print(json.dumps({'step': 'central-preview', 'summary': central_plan.summary}, ensure_ascii=False), flush=True)
else:
    raise ValueError('unknown fixed diagnostic mode')
# 故意不捕获异常：预算或预览抛出的原生 traceback 必须完整进入 execute 双流。
'''


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


def upgrade_archive_bytes(data, version):
    """从本次真实归档快照派生最窄升级夹具；不落地源码或改变生产版本。"""
    target = f"agent-workflow-{version}/product/WORKFLOW.md"
    output, changed = io.BytesIO(), False
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as source:
        with gzip.GzipFile(filename="", mode="wb", fileobj=output, mtime=0) as compressed:
            with tarfile.open(fileobj=compressed, mode="w", format=tarfile.PAX_FORMAT) as destination:
                for member in source:
                    if not (member.isdir() or member.isfile()):
                        raise ValueError("升级夹具只接受正式归档中的普通成员")
                    body = source.extractfile(member).read() if member.isfile() else None
                    if member.name == target:
                        if changed or body is None:
                            raise ValueError("升级资源必须是唯一的普通文件")
                        # product 是真实 core 清单的一部分；只追加无行为注释，使
                        # 内容 ID 改变，SDK/代码/VERSION/严格 release.json 均保持原字节。
                        body += b"\n<!-- awf-curl upgrade fixture: no behavior change -->\n"
                        member.size, changed = len(body), True
                    destination.addfile(member, io.BytesIO(body) if body is not None else None)
    if not changed:
        raise ValueError("真实归档缺少升级夹具资源 product/WORKFLOW.md")
    return output.getvalue()


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
        cls.program_parent_owned = False
        cls.addClassCleanup(cls.cleanup_scene)
        # RUNNER_TEMP 的祖先可能允许共享用户删除子项，不适合持久程序信任边界。
        # 只把程序测试根放到真实 LOCALAPPDATA 下的自有私有目录；下载、证书、
        # state 与原始日志仍归请求 scratch。生产守卫会真实核验这条链，无 CI 豁免。
        from lib import windows_fs as fs
        local = Path(os.environ["LOCALAPPDATA"])
        if not local.is_absolute() or not local.is_dir():
            raise RuntimeError("真实程序根验证需要已有的绝对 LOCALAPPDATA 用户目录")
        cls.program_parent = local / ("awf-delivery-test-" + uuid.uuid4().hex)
        fs.secure_os.mkdir(cls.program_parent, 0o700)
        cls.program_parent_owned = True
        fs.assert_private(cls.program_parent)
        print("[native program fixture] " + json.dumps({"program_parent": str(cls.program_parent),
            "scratch": str(cls.root), "reason": "程序持久祖先必须真实可信；下载/日志仍归原 scratch"}, ensure_ascii=False), flush=True)
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
            if cls.program_parent_owned and cls.program_parent.exists():
                shutil.rmtree(cls.program_parent)
            shutil.rmtree(cls.root)
        else:
            print("[保留未确认收尾的测试现场] " + str(cls.root)
                  + "; program_parent=" + str(getattr(cls, "program_parent", None)), flush=True)

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
        self.home, self.state = self.scene / "home", self.scene / "state"
        self.install = self.program_parent / ("程序 空格-" + uuid.uuid4().hex[:8])
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
        if hasattr(self, "fixture_derivation"):
            # source_sha 仅是原始快照来源；第二包的真实内容由新摘要及固定派生
            # 说明绑定，不能误标成首包字节或暗示公开发布的候选已被修改。
            record["delivery_identity"]["fixture_derivation"] = self.fixture_derivation
        if hasattr(result, "raw_stdout"):
            record.update(stdout_base64=base64.b64encode(result.raw_stdout).decode("ascii"),
                          stderr_base64=base64.b64encode(result.raw_stderr).decode("ascii"))
        if hasattr(result, "cwd"):
            record["cwd"] = result.cwd
        target = os.environ.get("AWF_TEST_EVIDENCE_LOG")
        if target:
            # CI 导出生成 PS、已知下载资产、程序收据及固定失败诊断原记录；证书私钥、
            # 环境与整个私有 state 不进入 artifact。按内容摘要去重，既保留坏资产的原字节，
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
            # 文件名封闭到此诊断的四个产物；不递归导出 state/HOME，也不从恢复
            # 日志接受 artifact 路径。原始记录与逐节点前后摘要均由现有 writer 留存。
            state_evidence = []
            for name in ("activation.json", "current.json", "native-wire.json", "snapshots.json"):
                path = self.scene / "upgrade-state-evidence" / name
                if path.is_file():
                    body = path.read_bytes()
                    digest = hashlib.sha256(body).hexdigest()
                    exported = destination / (digest + "-upgrade-" + name)
                    if not exported.exists():
                        with exported.open("xb") as stream:
                            stream.write(body)
                    state_evidence.append({"source": str(path), "sha256": digest, "artifact": exported.name})
            record["upgrade_state_evidence"] = state_evidence
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

    @staticmethod
    def observe_program_node_security(path):
        from lib import windows_fs as fs
        # 原句柄边界读取完整 owner/control/DACL 字节；比较不只依赖摘要或
        # POSIX mode。日志只公开摘要和目录身份，不写出本机用户 SID 正文。
        with fs.Directory(path.parent):
            handle = fs._open_handle(path, fs.READ_CONTROL | 0x80, directory=path.is_dir())
            try:
                information = fs._information(handle)
                with fs._security_policy(handle) as policy:
                    return {"identity": (information.volume, information.index_high << 32 | information.index_low),
                            "owner": policy.owner, "control": policy.control,
                            "acl": policy.acl_bytes, "security": policy.fingerprint}
            finally:
                fs._close(handle)

    def grant_owned_node_world_access(self, path, rights, *, directory=True):
        from lib import windows_fs as fs
        self.assertTrue(path.is_relative_to(self.program_parent), "只允许改变本例自有程序夹具节点权限")
        handle = fs._open_handle(path, 0x60080, directory=directory)
        descriptor = fs.HANDLE()
        try:
            # 复用既有 WindowsRuntime 原生夹具的 SDDL/SetSecurityInfo 授权方式。
            # 只给本例已拥有节点增加指定的 Everyone ACE（不向子项继承），
            # 不操作系统/用户目录，不改变 owner，也不让生产代码修正这份未知 ACL。
            api = fs._api()
            sid = fs.current_sid()
            flags = "OICI" if directory else ""
            sddl = f"D:P(A;{flags};GA;;;{sid})(A;{flags};GA;;;SY)(A;;{rights};;;WD)"
            self.assertTrue(api.security.ConvertStringSecurityDescriptorToSecurityDescriptorW(
                sddl, 1, ctypes.byref(descriptor), None))
            self.assertEqual(0, api.security.SetSecurityInfo(handle, 1, 0x80000004,
                None, None, fs._dacl(descriptor), None), "无法准备自有节点的真实弱 ACL 负控")
        finally:
            if descriptor.value:
                fs._api().kernel.LocalFree(descriptor)
            fs._close(handle)

    def reject_shared_empty_root(self, script, installed_before):
        from lib import windows_fs as fs
        shared = self.program_parent / "shared-empty-root"
        fs.secure_os.mkdir(shared, 0o700)
        fs.assert_private(shared)
        private_before = self.observe_program_node_security(shared)
        self.grant_owned_node_world_access(shared, "GA")
        weak_before = self.observe_program_node_security(shared)
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
        self.assertIn("untrusted Windows program path permissions: " + str(shared), value["error"])
        self.assertIsNone(value["retained_version_root"])
        self.assertEqual([], list(shared.iterdir()), "弱 ACL 拒绝前不得写 root marker、bin 或 versions")
        after = self.observe_program_node_security(shared)
        self.assertEqual(weak_before, after, "拒绝必须保全原目录身份、owner、控制位和完整 DACL")
        self.assertEqual(installed_before, (self.snapshot(self.install), self.snapshot(self.state)))
        print("[native shared-root preserved] " + json.dumps({"identity": after["identity"],
            "private_security_sha256": private_before["security"], "weak_security_sha256": weak_before["security"],
            "after_security_sha256": after["security"], "grant": "Everyone GA (includes write/delete-child)",
            "phase": value["phase"], "exit_code": failed.returncode, "root_empty": True}, ensure_ascii=False), flush=True)

    def reject_untrusted_program_paths(self, script, installed_before):
        from lib import windows_fs as fs
        version_name = self.version + "-" + self.fields["ARCHIVE_SHA256"]
        # 每个负控独占本例一个私有程序根；危险目录不共用，避免前一个弱 ACL
        # 掩盖后一个边界，也无需把 venv 的继承 ACL 用 chmod 猜测恢复。
        scenarios = []
        parent = self.program_parent / "delete-child-parent"
        fs.secure_os.mkdir(parent, 0o700)
        private_root = parent / "private-root"
        fs.secure_os.mkdir(private_root, 0o700)
        # SDDL 的 DC 属于目录服务权利（位 0x2），落到文件目录是 ADD_FILE，
        # 不能按名称把它当作文件系统 DELETE_CHILD。这里明确用 FILE_DELETE_CHILD
        # 的 0x40，并读回真实 ACE 验证，防止负控误变成守卫允许的纯创建权限。
        # 来源：Microsoft Learn /windows/win32/secauthz/ace-strings 与
        # /windows/win32/fileio/file-access-rights-constants。
        self.grant_owned_node_world_access(parent, "0x40")
        with fs.Directory(parent) as directory, fs._security_policy(directory.handle) as policy:
            masks = []
            everyone = fs._sid_bytes("S-1-1-0")
            for index in range(int.from_bytes(policy.acl_bytes[4:6], "little")):
                pointer = fs.HANDLE()
                self.assertTrue(fs._api().security.GetAce(policy.acl, index, ctypes.byref(pointer)))
                header = ctypes.string_at(pointer, 8)
                size = int.from_bytes(header[2:4], "little")
                self.assertTrue(8 <= size <= len(policy.acl_bytes))
                ace = ctypes.string_at(pointer, size)
                if ace[0] == 0 and ace[8:] == everyone:
                    self.assertEqual(0, ace[1], "Everyone ACE 必须直接作用于父目录")
                    masks.append(int.from_bytes(ace[4:8], "little"))
            self.assertEqual([0x40], masks, "必须真实授予且只授予 Everyone FILE_DELETE_CHILD")
        print("[native delete-child ACE readback] Everyone allow masks=" + json.dumps(masks), flush=True)
        fs.assert_private(private_root)
        scenarios.append(("parent-delete-child", private_root, parent))
        for label, relative, leaf in (("bin", "bin", False), ("versions", "versions", False),
                                     ("version-root", "versions/" + version_name, False),
                                     ("venv-scripts", "versions/" + version_name + "/venv/Scripts", False),
                                     ("interpreter-leaf", "versions/" + version_name + "/venv/Scripts/python.exe", True)):
            root = self.program_parent / ("unsafe-" + label)
            fs.secure_os.mkdir(root, 0o700)
            current = root
            parts = relative.split("/")
            for part in parts[:-1] if leaf else parts:
                current /= part
                fs.secure_os.mkdir(current, 0o700)
            if leaf:
                # 叶只用已拥有的普通文本夹具，不创建或复制第二套 venv；权限
                # 守卫必须在解释器格式/收据消费之前拒绝这个实际危险叶。
                current /= parts[-1]
                descriptor = fs.secure_os.open(current, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
                try:
                    os.write(descriptor, b"owned fixture, not an interpreter; preflight must reject first")
                    fs.secure_os.fsync(descriptor)
                finally:
                    fs.secure_os.close(descriptor)
            self.grant_owned_node_world_access(current, "GA", directory=not leaf)
            fs.assert_private(root)
            scenarios.append((label, root, current))
        for label, root, rejected_node in scenarios:
            with self.subTest(program_permission=label):
                nodes = [root, *sorted(root.rglob("*"))]
                if rejected_node == parent:
                    nodes.append(parent)
                before_security = {str(path): self.observe_program_node_security(path) for path in nodes}
                before_members = sorted(path.relative_to(root).as_posix() for path in root.rglob("*"))
                before_payload = self.snapshot(root)
                failed = self.install_via_ps(script, install_root=root)
                self.assertEqual(2, failed.returncode, failed.stdout + failed.stderr)
                value = json.loads(failed.stdout)
                self.assertEqual((False, "preflight", 2), (value["ok"], value["phase"], value["exit_code"]))
                self.assertIsNone(value["retained_version_root"])
                # 由公共 FS 守卫给出实际失败节点；测试只核对其错误合同，绝不
                # 自行复制“哪些 SID/ACL mask 可受信”的生产权限判定。
                self.assertIn("untrusted Windows program path permissions: " + str(rejected_node), value["error"])
                self.assertEqual(before_members, sorted(path.relative_to(root).as_posix() for path in root.rglob("*")))
                self.assertEqual(before_payload, self.snapshot(root))
                self.assertEqual(before_security, {str(path): self.observe_program_node_security(path) for path in nodes})
                self.assertEqual(installed_before, (self.snapshot(self.install), self.snapshot(self.state)))
                print("[native untrusted-program-path preserved] " + json.dumps({"scenario": label,
                    "root": str(root), "rejected_node": str(rejected_node), "phase": value["phase"],
                    "exit_code": failed.returncode, "members_unchanged": True,
                    "security": {name: {"identity": observation["identity"], "sha256": observation["security"]}
                                 for name, observation in before_security.items()}}, ensure_ascii=False), flush=True)

    def prepare_upgrade_assets(self):
        from lib.runtime_store import CORE_DIRECTORIES
        self.assertIn("product", CORE_DIRECTORIES, "修改的资源必须实际参与核心身份")
        original = self.archive.read_bytes()
        data = upgrade_archive_bytes(original, self.version)
        digest = hashlib.sha256(data).hexdigest()
        self.assertNotEqual(self.fields["ARCHIVE_SHA256"], digest)
        tag = f"v{self.version}-rc.2"
        self.release.release_identity(self.version, tag)
        pyz = self.release.installer_bytes(data, self.version, digest)
        prefix = f"agent-workflow-{self.version}/"
        with tarfile.open(fileobj=io.BytesIO(original), mode="r:gz") as before, \
                tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as after, \
                zipfile.ZipFile(io.BytesIO(pyz)) as installer:
            self.assertEqual(before.getnames(), after.getnames())
            changed = [item.name for item in after if item.isfile()
                       and before.extractfile(item.name).read() != after.extractfile(item).read()]
            self.assertEqual([prefix + "product/WORKFLOW.md"], changed)
            self.assertEqual(before.extractfile(prefix + "product/VERSION").read(), after.extractfile(prefix + "product/VERSION").read())
            metadata = after.extractfile(prefix + "manager/release.json").read()
            self.assertEqual(before.extractfile(prefix + "manager/release.json").read(), metadata)
            self.assertEqual({"schema_version": 1, "version": self.version}, json.loads(metadata))
            self.assertEqual(set((*self.release.WINDOWS_INSTALLER_FILES, "__main__.py")), set(installer.namelist()))
            for name in self.release.WINDOWS_INSTALLER_FILES:
                self.assertEqual(after.extractfile(prefix + name).read(), installer.read(name), "升级 pyz SDK 必须来自同一 tar 快照")
        directory = self.assets / "upgrade"
        directory.mkdir()
        archive = directory / self.archive.name
        installer = directory / f"agent-workflow-windows-{tag}.pyz"
        for path, body in ((archive, data), (installer, pyz)):
            with path.open("xb") as stream:
                stream.write(body)
        fields = {"VERSION": self.version, "RELEASE_TAG": tag,
            "ARCHIVE_NAME": archive.name, "ARCHIVE_SHA256": digest,
            "PYZ_NAME": installer.name, "PYZ_SHA256": hashlib.sha256(pyz).hexdigest(),
            "BASE_URL": self.fields["BASE_URL"] + "/upgrade"}
        return archive, installer, fields

    def upgrade_same_install(self, old_root, old_binding):
        from lib import runtime_store
        old_environment = self.snapshot(old_root)
        old_receipt = (old_root / "install.json").read_bytes()
        old_manifest = self.state / "runtimes" / old_binding["content_id"] / "manifest.json"
        old_manifest_bytes = old_manifest.read_bytes()
        original_digest = self.fields["ARCHIVE_SHA256"]
        archive, installer, fields = self.prepare_upgrade_assets()
        # 此方法位于正常方法最后；只切换当前 TestCase 的资产身份，第二个原生
        # 方法仍从类的原始资产初始化。所有 upgrade execute/诊断记录因此均绑定
        # 第二包，不沿用首包字段；同一 install-root/state/home 和 HTTPS owner 不变。
        self.archive, self.pyz, self.fields, self.tag = archive, installer, fields, fields["RELEASE_TAG"]
        self.fixture_derivation = {"base_archive_sha256": original_digest, "changed_member": "product/WORKFLOW.md",
                                   "change": "append fixed behavior-free HTML comment"}
        result = self.install_via_ps(self.render("upgrade"))
        self.assertIn("/upgrade/" + archive.name, self.server.requests)
        self.assertIn("/upgrade/" + installer.name, self.server.requests)
        new_root = self.install / "versions" / (self.version + "-" + fields["ARCHIVE_SHA256"])
        new_python, new_payload = new_root / "venv/Scripts/python.exe", new_root / "payload"
        if result.returncode:
            # 仅消费已保留的新物理载荷做只读诊断；不重试激活、不修冲突或修改
            # 核心。实际 CID 由既有只读 SDK 算法读取，绝不按目录/摘要虚构 pin。
            self.assertTrue(new_python.is_file() and (new_payload / "workflow.py").is_file(), result.stdout + result.stderr)
            inspected = runtime_store.inspect_core(new_payload)
            # 先保真实持久停点，再运行可能只报告“未结算”的旧预览诊断。记录本次
            # engine.phase/CID，不能把先前已结算冷装事务误认成本次升级失败事务。
            # 证据目录在本例 scene；诊断 exit 非零只留双流，绝不掩盖最初升级 FAIL。
            evidence = self.scene / "upgrade-state-evidence"
            evidence.mkdir()
            try:
                engine_phase = json.loads(result.stdout).get("phase")
            except (ValueError, AttributeError):
                engine_phase = "unparsed-engine-output"
            self.execute("upgrade-readonly-persistent-state", [str(new_python), "-I", "-B", "-X", "utf8", "-c",
                UPGRADE_STATE_DIAGNOSTIC, str(new_payload), str(self.state), str(self.home), str(evidence),
                inspected["content_id"], str(engine_phase)])
            diagnostic = self.execute("upgrade-activate-preview-text-diagnostic", [str(new_python), "-I", "-B", "-X", "utf8",
                str(new_payload / "workflow.py"), "--state-dir", str(self.state), "--host-home", str(self.home),
                "runtime", "activate", inspected["content_id"], "--dry-run"])
            # receipt_budget 可能先抛；拆为两个只读模式才能让 central.preview
            # 也获得独立原始 traceback，且无需吞掉/重写任何异常。四个子进程仍
            # 使用同一 state/home/新 payload，只改变解释器和诊断入口，不做 apply。
            for interpreter, python in (("old", old_root / "venv/Scripts/python.exe"), ("new", new_python)):
                for mode in ("native-budget", "central-preview"):
                    self.execute("upgrade-readonly-" + interpreter + "-" + mode,
                        [str(python), "-I", "-B", "-X", "utf8", "-c", UPGRADE_READ_ONLY_DIAGNOSTIC,
                         str(new_payload), str(self.state), str(self.home), inspected["content_id"], mode])
            self.fail("真实跨私有解释器升级失败；已保存持久状态、文本预览及旧/新解释器只读原始诊断：\n" + result.stdout + result.stderr
                      + "\n[diagnostic]\n" + diagnostic.stdout + diagnostic.stderr)
        value = json.loads(result.stdout)
        self.assertEqual((True, "complete", 0), (value["ok"], value["phase"], value["exit_code"]))
        self.assertEqual(str(new_root), value["version_root"])
        self.assertNotEqual(old_root, new_root)
        self.assertNotEqual(old_binding["content_id"], value["runtime_binding"]["content_id"])
        inspected = runtime_store.inspect_core(new_payload)
        self.assertEqual(inspected["content_id"], value["runtime_binding"]["content_id"])
        self.assertFalse(os.path.samefile(old_root / "venv/Scripts/python.exe", new_python))
        launcher = self.install / "bin/awf-cli.ps1"
        self.assertIn(str(new_python).replace("'", "''"), launcher.read_text(encoding="utf-8"))
        version = self.execute("upgrade-launcher-version", [str(self.pwsh), "-NoLogo", "-NoProfile", "-File", str(launcher), "--version"])
        self.assertEqual(0, version.returncode, version.stdout + version.stderr)
        self.assertIn(str(new_payload), version.stdout)
        status = self.execute("upgrade-runtime-status", [str(self.pwsh), "-NoLogo", "-NoProfile", "-File", str(launcher), "--json", "runtime", "status"])
        self.assertEqual(0, status.returncode, status.stdout + status.stderr)
        current = json.loads(status.stdout)["result"]
        self.assertEqual(value["runtime_binding"], current["runtime_binding"])
        self.assertTrue(current["new_task_allowed"])
        self.assertEqual(old_environment, self.snapshot(old_root), "升级不得重建或删除旧私有环境")
        self.assertEqual(old_receipt, (old_root / "install.json").read_bytes())
        self.assertEqual(old_manifest_bytes, old_manifest.read_bytes())

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
        foreign = self.program_parent / "foreign"
        # 未受管入口负控仍需先满足权限前置，避免被新的可信路径守卫提前拒绝，
        # 从而把“权限不安全”误当作“未知入口不得认领”的原有证据。
        from lib import windows_fs as fs
        fs.secure_os.mkdir(foreign, 0o700)
        fs.secure_os.mkdir(foreign / "bin", 0o700)
        old_entry = foreign / "bin/awf-cli.cmd"
        old_entry.write_bytes(b"@echo foreign entry\r\n")
        original = self.snapshot(foreign)
        failed = self.install_via_ps(script, install_root=foreign)
        self.assertNotEqual(0, failed.returncode, failed.stdout + failed.stderr)
        self.assertEqual(original, self.snapshot(foreign))
        self.assertEqual(before[1], self.snapshot(self.state))
        self.reject_shared_empty_root(script, before)
        self.reject_untrusted_program_paths(script, before)
        self.upgrade_same_install(version_root, value["runtime_binding"])

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
