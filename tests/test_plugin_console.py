"""配置网页的真实静态入口，以及同一生产 JS 的协议、草稿和异步归属回归。"""

from __future__ import annotations

from html.parser import HTMLParser
import http.client
from pathlib import Path
import shutil
import subprocess
import threading
import unittest

from native_config.server import ConsoleServer


ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "native_config" / "web"


class PageParser(HTMLParser):
    """只检查生产入口的依赖/表单语义，不以字符串快照冒充浏览器交互验证。"""

    def __init__(self):
        super().__init__()
        self.elements = []

    def handle_starttag(self, tag, attrs):
        self.elements.append((tag, dict(attrs)))


class ConsoleEntryTest(unittest.TestCase):
    def test_self_hosted_entry_has_accessible_forms_and_real_static_routes(self):
        page = PageParser()
        page.feed((WEB / "index.html").read_text(encoding="utf-8"))
        self.assertEqual([attrs["src"] for tag, attrs in page.elements if tag == "script"], ["/console.js"])
        self.assertEqual([attrs["href"] for tag, attrs in page.elements if tag == "link"], ["/console.css"])
        self.assertFalse(any(key.startswith("on") for _, attrs in page.elements for key in attrs))
        ids = [attrs["id"] for _, attrs in page.elements if "id" in attrs]
        self.assertEqual(len(ids), len(set(ids)))
        tabs = [attrs for _, attrs in page.elements if attrs.get("role") == "tab"]
        self.assertEqual({tab["data-host"] for tab in tabs}, {"codex", "claude", "antigravity"})
        self.assertEqual(sum(tab["aria-selected"] == "true" for tab in tabs), 1)
        self.assertEqual(len([tag for tag, _ in page.elements if tag == "dialog"]), 2)
        self.assertTrue(any(attrs.get("aria-live") == "polite" for _, attrs in page.elements))

        # 真实回环服务消费本次生产文件；无宿主/用户目录参与，不依赖测试替身静态页面。
        server = ConsoleServer(object(), version="3.0.0-test")
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            for path, filename, content_type in (("/", "index.html", "text/html"),
                                                   ("/console.js", "console.js", "javascript"),
                                                   ("/console.css", "console.css", "text/css")):
                with self.subTest(path=path):
                    connection = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=3)
                    try:
                        connection.request("GET", path)
                        response = connection.getresponse()
                        self.assertEqual(response.status, 200)
                        self.assertIn(content_type, response.getheader("Content-Type"))
                        self.assertEqual(response.read(), (WEB / filename).read_bytes())
                        self.assertIn("script-src 'self'", response.getheader("Content-Security-Policy"))
                    finally:
                        connection.close()
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=3)


@unittest.skipUnless(shutil.which("node"), "生产网页 JS 验证需要 Node")
class ConsoleJavascriptTest(unittest.TestCase):
    def run_javascript(self, body):
        # Node 直接导入生产函数；令牌只用测试字符串，不接触本机连接记录或真实配置。
        script = r"""
const assert = require('node:assert/strict');
const {ModelApi, ApiError, Draft, RequestOwner, contextContract, applyReceiptContract, applyFailed, applyNeedsAttention, locationKey} = require('./native_config/web/console.js');
const row = (id, fields = {}) => ({role: id, name: '同名 Agent', origin: 'user', scope: 'global', writable: true,
  overrides: {model: 'saved/unknown:model', effort: 'high'}, effective: {model: 'saved/unknown:model', effort: 'high'},
  sources: {model: 'user', effort: 'user'}, dispatch_ready: false, blocked_reason: '尚未观察到客户端版本', ...fields});
const context = (rows = [row('opaque:a')]) => ({host: 'codex', scope: 'global', project: null,
  revision: 'rev-1', roles: rows, capabilities: {model: true, effort: true, efforts: ['low', 'high', 'ultra']}});
const response = (value, status = 200) => ({ok: status < 400, status, json: async () => value});
(async () => {
""" + body + r"""
})().catch(error => { console.error(error); process.exitCode = 1; });
"""
        result = subprocess.run([shutil.which("node"), "-e", script], cwd=ROOT,
                                text=True, capture_output=True, timeout=12)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_dynamic_identity_independent_fields_read_only_and_draft_recovery(self):
        self.run_javascript(r"""
const longId = 'plugin:vendor:' + 'long-agent-name-'.repeat(28);
const plugin = row(longId, {origin: 'plugin', writable: false, read_only_reason: '插件缓存只读'});
const draft = new Draft({host: 'codex', scope: 'global'});
draft.accept(context([row('opaque:a'), row('opaque:b'), plugin, row('__proto__')]));
draft.set('opaque:a', 'model', 'future/unknown:model');
assert.equal(draft.value('opaque:a', 'effort'), 'high', '模型编辑不能固化或清除 effort');
draft.set('opaque:a', 'effort', 'ultra');
draft.set('opaque:b', 'model', null);
draft.set('__proto__', 'model', 'inherit');
draft.set(longId, 'model', 'must-not-write');
const payload = draft.payload();
assert.equal(payload['opaque:b'].model, null);
assert.equal(payload.__proto__.model, 'inherit');
assert.equal(Object.prototype.hasOwnProperty.call(payload, longId), false);
assert.equal(draft.count, 4);
payload['opaque:a'].model = 'client-mutation';
assert.equal(draft.value('opaque:a', 'model'), 'future/unknown:model');
// 目录更新或切走再返回不负责重置任何字段；草稿身份包含平台、范围和完整项目路径。
draft.catalog = {models: [{id: 'other-model'}]};
const cache = new Map([[locationKey(draft.location), draft]]);
assert.notEqual(locationKey(draft.location), locationKey({host: 'claude', scope: 'global'}));
assert.notEqual(locationKey({host:'codex',scope:'project',project:'/a'}), locationKey({host:'codex',scope:'project',project:'/b'}));
assert.equal(cache.get(locationKey(draft.location)).value('opaque:a', 'model'), 'future/unknown:model');
draft.selected.add(longId); draft.selected.add('opaque:a');
const fresh = context([row('opaque:a', {overrides: {model:'remote', effort:'low'}}), row('opaque:b'), plugin, row('__proto__')]);
fresh.revision = 'rev-2'; draft.accept(fresh);
assert.equal(draft.value('opaque:a','model'), 'future/unknown:model');
assert.equal(draft.value('opaque:a','effort'), 'ultra');
assert.equal(draft.selected.has(longId), false);
assert.equal(draft.context.revision, 'rev-2');
// 若定义消失或权限变化，显式阻止保存且保留可见草稿，不能把同名来源当作同一 Agent。
draft.accept(context([row('opaque:a', {writable:false}), row('opaque:b'), plugin]));
assert.deepEqual(draft.unavailableEdits.sort(), ['__proto__', 'opaque:a']);
assert.equal(draft.dirty, true);
draft.clear(); assert.equal(draft.dirty, false);
const unknown = new Draft({host:'codex',scope:'global'});
unknown.accept(context([row('unknown-permission', {writable:undefined})]));
unknown.set('unknown-permission','model','unsafe');
assert.equal(unknown.dirty, false);
assert.throws(() => contextContract(context([row('same'),row('same')])), ApiError);
assert.equal(contextContract(context([row(longId)] )).roles[0].role, longId);
""")

    def test_protocol_scope_null_preview_apply_and_recoverable_errors(self):
        self.run_javascript(r"""
const calls = [];
const api = new ModelApi('test-token', async (path, init) => {
  calls.push({path, init});
  if (path.startsWith('/api/context')) return response(context());
  if (path.startsWith('/api/catalog')) return response({models:[{id:'catalog-model'}],status:'ready'});
  if (path === '/api/preview') return response({preview_id:'server-plan',changes:[],warnings:[],effect:{runtime_verified:false}});
  return response({saved:true,effect:{runtime_verified:false},context:context()});
});
assert.equal(calls.length, 0, '初始化不得探测目录或客户端版本');
await api.context({host:'codex',scope:'global',project:'/must-be-omitted'});
assert.equal(calls[0].path.includes('project='), false);
assert.equal(calls[0].init.headers.Authorization, 'Bearer test-token');
assert.equal(calls[0].init.credentials, 'omit');
const location = {host:'claude',scope:'project',project:'/tmp/project with space'};
await api.catalog(location);
assert.equal(new URL(calls[1].path, 'http://localhost').searchParams.get('project'), location.project);
await api.preview(location, 'revision-a', {'opaque:plugin':{model:null, effort:'inherit'}}, false);
assert.deepEqual(JSON.parse(calls[2].init.body), {host:'claude',scope:'project',project:location.project,revision:'revision-a',edits:{'opaque:plugin':{model:null,effort:'inherit'}}});
await api.preview({host:'codex',scope:'global'}, 'revision-b', {}, true);
assert.deepEqual(JSON.parse(calls[3].init.body), {host:'codex',scope:'global',revision:'revision-b',edits:{},reset:true});
await api.apply('server-plan');
assert.deepEqual(JSON.parse(calls[4].init.body), {preview_id:'server-plan'}, '应用只能提交服务端计划 ID');
const conflict = new ModelApi('test', async () => response({error:{code:'conflict',message:'配置已变更'}},409));
await assert.rejects(conflict.apply('old-plan'), error => error.code==='conflict' && error.status===409);
const invalid = new ModelApi('test', async () => response({host:'codex',roles:[]}));
await assert.rejects(invalid.context({host:'codex',scope:'global'}), error => error.code==='invalid_response');
const denied = new ModelApi('test', async () => response({error:{code:'unauthorized',message:'private-token-must-not-display'}},401));
await assert.rejects(denied.context({host:'codex',scope:'global'}), error => !error.message.includes('private-token'));
const missing = new ModelApi('', async () => {throw Error('must-not-fetch');});
await assert.rejects(missing.context({host:'codex',scope:'global'}), error => error.code==='authentication');
// 多文件发布不具有跨文件系统原子性；即使回读 context 不可用，也必须交付恢复路径。
const partial = new ModelApi('test', async () => response({saved:false,partial_failure:true,
  effect:{saved:false,pending_reload:true,runtime_verified:false},
  results:[{role:'opaque:a',status:'rollback_conflict'}],
  recovery:[{role:'opaque:a',target:'/tmp/native-agent.md',backup:'/tmp/recovery.backup',sha256:'a'.repeat(64)}]}));
const recovered = await partial.apply('partial-plan');
assert.equal(recovered.partial_failure,true);
assert.equal(recovered.recovery[0].backup,'/tmp/recovery.backup');
assert.equal(recovered.context,undefined);
const unavailable = new ModelApi('test', async () => response({saved:true,partial_failure:false,
  effect:{saved:true,pending_reload:true,runtime_verified:false},results:[{role:'opaque:a',status:'saved'}],recovery:[],
  context_unavailable:true,context_diagnostic:'回读不安全，保留逐项收据'}));
const published = await unavailable.apply('saved-without-context');
assert.equal(published.saved,true);
assert.equal(published.context_unavailable,true);
assert.equal(published.results[0].status,'saved');
""")

    def test_apply_error_receipts_keep_recovery_and_reject_untrusted_shapes(self):
        self.run_javascript(r"""
const receipt = {saved:false,partial_failure:true,published:false,namespace_touched:true,temporary_visibility_gap:true,
  effect:{saved:false,pending_reload:true,runtime_verified:false},
  error:{code:'partial_failure',message:'检查逐项结果及保留资料'},
  results:[{role:'opaque:a',status:'rollback_conflict'},{role:'opaque:b',status:'rolled_back'}],
  recovery:[{role:'opaque:a',target:'/tmp/native-agent.md',backup:'/tmp/preimage.backup',sha256:'a'.repeat(64),kind:'preview_preimage'},
    {role:'opaque:a',target:'/tmp/native-agent.md',backup:'/tmp/isolated-object',sha256:null,kind:'isolated_object',container_mode:448,original_mode:null}],
  cleanup_pending:['/tmp/staged-file'],retention_policy:'until_explicit_safe_cleanup_contract'};
receipt.recovery[0].sha256_semantics='immutable_preview_bytes';receipt.recovery[0].content_may_change=false;
receipt.recovery[1].sha256_semantics='observed_at_isolation_not_current';receipt.recovery[1].content_may_change=true;
receipt.recovery[1].object_role='target_at_initial_isolation';
let calls=0;
const api = new ModelApi('test', async () => {calls++;return response(receipt,409);});
await assert.rejects(api.apply('consumed-plan'), error => {
  assert.equal(error.code,'partial_failure');assert.equal(error.status,409);
  assert.deepEqual(error.receipt,receipt);
  assert.equal(error.receipt.recovery[1].sha256,null);
  assert.equal(error.receipt.namespace_touched,true);
  return true;
});
assert.equal(calls,1,'失败不得自动重放已消费的apply');
const namespaceOnly={...receipt,partial_failure:false,error:'exclusive publication blocked'};
const namespaceApi=new ModelApi('test',async()=>response(namespaceOnly));
const blocked=await namespaceApi.apply('namespace-changed');
assert.equal(blocked.partial_failure,false);assert.equal(applyFailed(blocked),true);
assert.equal(applyNeedsAttention(blocked),true);
// 保存成功也能正常保留原inode/前像；有资料需要展示，但不能据此宣称失败。
const retained={...receipt,saved:true,partial_failure:false,published:true,
  effect:{saved:true,pending_reload:true,runtime_verified:false},results:[{role:'opaque:a',status:'saved'}],context:context()};
delete retained.error;
assert.equal(applyFailed(applyReceiptContract(retained)),false);
assert.equal(applyNeedsAttention(retained),true);
const badResults={...retained,results:[{role:'opaque:a',status:'rolled_back'}]};
assert.equal(applyFailed(badResults),true);
// 真实发布后的目录退出冲突仍是完整收据；未知当前位置不能回退显示原绝对路径。
const finalization={...receipt,published:true,finalization_failed:true,finalization_error_type:'ConflictError',
  results:[{role:'opaque:a',status:'published_location_unknown'}],
  recovery:receipt.recovery.map(row=>({...row,backup:null,declared_backup:row.backup,location_status:'unknown',
    observed_identity:[1,2,33152,1,40,12,13],container_identity:[1,3]}))};
const finalized=await new ModelApi('test',async()=>response(finalization)).apply('consumed-finalization-plan');
assert.equal(finalized.published,true);assert.equal(finalized.saved,false);
assert.equal(finalized.results[0].status,'published_location_unknown');
assert.equal(finalized.recovery[0].backup,null);
assert.equal(finalized.recovery[0].declared_backup,'/tmp/preimage.backup');
assert.equal(applyNeedsAttention(finalized),true);
for(const [status,code] of [[409,'conflict'],[401,'partial_failure']]) {
  const ordinary=new ModelApi('test',async()=>response({...receipt,error:{code,message:'普通错误'}},status));
  await assert.rejects(ordinary.apply('ordinary-plan'),error=>error.status===status&&error.receipt===undefined);
}
// 只有通过同一200/409收据边界校验的路径、摘要和权限才交给安全文字渲染。
const malformed=[
  {...receipt,namespace_touched:'yes'},
  {...receipt,recovery:[{...receipt.recovery[0],backup:['/tmp/not-a-string']}]},
  {...receipt,recovery:[{...receipt.recovery[0],sha256:{digest:'unsafe'}}]},
  {...receipt,recovery:[{...receipt.recovery[1],container_mode:'0700'}]},
  {...receipt,recovery:[{...receipt.recovery[1],content_may_change:'true'}]},
  {...finalization,recovery:[{...finalization.recovery[0],backup:'/tmp/old-location'}]},
  {...finalization,recovery:[{...finalization.recovery[0],declared_backup:null}]},
  {...finalization,recovery:[{...finalization.recovery[0],location_status:'verified_at_finalization'}]},
  {...finalization,recovery:[{...finalization.recovery[0],observed_identity:{inode:2}}]},
  {...finalization,finalization_failed:'true'},
  {...receipt,cleanup_pending:[{path:'/tmp/unknown'}]},
  {...receipt,results:[{role:'opaque:a',status:1}]},
  {...receipt,saved:true}
];
for(const value of malformed) {
  const invalid=new ModelApi('test',async()=>response(value,409));
  await assert.rejects(invalid.apply('invalid-plan'),error=>error.code==='invalid_response'&&error.receipt===undefined);
}
""")

    def test_superseded_response_cancellation_and_bounded_timeout(self):
        self.run_javascript(r"""
const owner = new RequestOwner();
const old = owner.begin(); const latest = owner.begin();
assert.equal(old.signal.aborted, true);
assert.equal(owner.current(old), false);
assert.equal(owner.current(latest), true);
owner.cancel(); assert.equal(owner.current(latest), false);
const waitsForAbort = async (_path, init) => await new Promise((_resolve, reject) => {
  if (init.signal.aborted) reject(new Error('aborted'));
  else init.signal.addEventListener('abort', () => reject(new Error('aborted')), {once:true});
});
const api = new ModelApi('test', waitsForAbort, 15);
await assert.rejects(api.context({host:'codex',scope:'global'}), error => error.code==='timeout');
const controller = new AbortController();
const pending = api.context({host:'codex',scope:'global'}, controller.signal); controller.abort();
await assert.rejects(pending, error => error.code==='cancelled');
""")


if __name__ == "__main__":
    unittest.main()
