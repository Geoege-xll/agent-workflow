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
        self.assertEqual([attrs["src"] for tag, attrs in page.elements if tag == "script"], ["/connection.js", "/native-definitions.js", "/console.js"])
        self.assertEqual([attrs["href"] for tag, attrs in page.elements if tag == "link"], ["/console.css"])
        self.assertFalse(any(key.startswith("on") for _, attrs in page.elements for key in attrs))
        ids = [attrs["id"] for _, attrs in page.elements if "id" in attrs]
        self.assertEqual(len(ids), len(set(ids)))
        tabs = [attrs for _, attrs in page.elements if attrs.get("role") == "tab"]
        self.assertEqual({tab["data-host"] for tab in tabs}, {"codex", "claude", "antigravity"})
        self.assertEqual(sum(tab["aria-selected"] == "true" for tab in tabs), 1)
        self.assertEqual(len([tag for tag, _ in page.elements if tag == "dialog"]), 2)
        self.assertTrue(any(attrs.get("aria-live") == "polite" for _, attrs in page.elements))
        self.assertTrue(any(tag == "label" and attrs.get("for") == "activation-state" for tag, attrs in page.elements))
        self.assertTrue(any(attrs.get("id") == "activation-state" and attrs.get("aria-describedby") for _, attrs in page.elements))

        # 真实回环服务消费本次生产文件；无宿主/用户目录参与，不依赖测试替身静态页面。
        server = ConsoleServer(object(), version="3.0.0-test")
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            for path, filename, content_type in (("/", "index.html", "text/html"),
                                                   ("/console.js", "console.js", "javascript"),
                                                   ("/connection.js", "connection.js", "javascript"),
                                                   ("/native-definitions.js", "native-definitions.js", "javascript"),
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
const {ModelApi, ApiError, Draft, RequestOwner, CatalogLoader, contextContract, activationContract, applyReceiptContract, applyFailed, applyNeedsAttention, locationKey, preferenceContract, modelCandidates, effortOptions, resolvedField, validCustomModelId, modelChoices} = require('./native_config/web/console.js');
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

    def test_context_menus_wait_for_focus_destination_and_preserve_dismissal(self):
        # 直接绑定生产监听器；这里只验证事件边界，不模拟浏览器的 label 默认激活。
        # 真实点击与范围切换仍需浏览器验收，避免用测试替身冒充原生表单行为。
        self.run_javascript(r"""
const {bindContextMenus} = require('./native_config/web/console.js');
const root = new EventTarget();
const emit = (receiver, type, target, fields = {}) => {
  const event = new Event(type, {cancelable:true});
  Object.defineProperty(event, 'target', {value:target});
  for (const [key,value] of Object.entries(fields)) Object.defineProperty(event,key,{value});
  receiver.dispatchEvent(event);
  return event;
};
let focused = null, choiceCloses = 0;
class Menu extends EventTarget {
  constructor(id) {
    super(); this.id = id; this.open = false;
    this.summary = {parent:this,focus:()=>{focused=this.summary;emit(root,'focusin',this.summary);}};
  }
  contains(target) { for (let node = target; node; node = node.parent) if (node === this) return true; return false; }
  querySelector(selector) { assert.equal(selector,'summary'); return this.summary; }
}
const menus = ['platform','scope','project'].map(id => new Menu(id));
bindContextMenus(menus,root,()=>choiceCloses++);
const outside = {};
for (const menu of menus) {
  const label = {parent:menu}, control = {parent:label};
  menu.open = true;
  // 对应真实 Chrome：按下菜单内文字后 summary 先失焦，relatedTarget 暂时为 null。
  emit(root,'pointerdown',label);
  emit(menu,'focusout',menu.summary,{relatedTarget:null});
  assert.equal(menu.open,true,menu.id+'：未知焦点落点不能提前隐藏待激活控件');
  emit(root,'focusin',control);
  assert.equal(menu.open,true,menu.id+'：菜单内焦点移动保持展开');
  emit(root,'focusin',outside);
  assert.equal(menu.open,false,menu.id+'：Tab/程序焦点离开时关闭');

  menu.open = true;
  emit(root,'pointerdown',outside);
  assert.equal(menu.open,false,menu.id+'：不接收焦点的外部区域仍可关闭');

  menu.open = true;
  const enter = emit(menu,'keydown',control,{key:'Enter'});
  assert.equal(enter.defaultPrevented,false,'不接管原生控件的激活按键');
  assert.equal(menu.open,true);
  const escape = emit(menu,'keydown',control,{key:'Escape'});
  assert.equal(escape.defaultPrevented,true);
  assert.equal(menu.open,false);
  assert.equal(focused,menu.summary,menu.id+'：Esc 返回自身 summary');

  menus.forEach(item=>{item.open=true;});
  emit(menu,'toggle',menu);
  assert.deepEqual(menus.map(item=>item.open),menus.map(item=>item===menu),'展开仍保持互斥');
  menu.open = false;
  const before = choiceCloses;
  emit(menu,'toggle',menu);
  assert.equal(choiceCloses,before,'关闭事件不额外关闭字段选择浮层');
}
assert.equal(choiceCloses,menus.length);
""")

    def test_connection_exchange_reload_priority_expiry_and_storage_boundaries(self):
        # 同一生产连接模块验证原token只交换一次、恢复先健康核验，且不损坏其它history消费者。
        self.run_javascript(r"""
const {Connection, STORAGE_KEY, HISTORY_KEY, sessionContract, navigation, validProject} = require('./native_config/web/connection.js');
const values = new Map(), origin = 'http://127.0.0.1:43210';
const storage = {getItem:key=>values.get(key)||null,setItem:(key,value)=>values.set(key,value),removeItem:key=>values.delete(key)};
const history = {state:{unrelated:'preserved'},replaceState(value, _title, url){this.state=value;assert.equal(url,'/');}};
const env = {origin,history,storage:()=>storage,cleanUrl:'/'};
const derived = {schema_version:1,session_token:'a'.repeat(43),instance_id:'b'.repeat(32),origin,expires_at:Date.now()+1700000};
const calls=[]; const api = new ModelApi('',async(path,init)=>{
 calls.push({path,authorization:init.headers.Authorization,body:init.body});
 return response(path==='/api/session'?derived:{protocol_version:2,instance_id:derived.instance_id});
});
const connection = new Connection(api,env);api.connection=connection;
await connection.start(new URLSearchParams({token:'original-entry',host:'claude',project:'/fixture/project'}));
assert.equal(connection.ready,true);assert.equal(calls[0].body,'{}');assert.equal(calls[0].authorization,'Bearer original-entry');
assert.equal(calls[1].authorization,'Bearer '+derived.session_token);
assert.equal(values.get(STORAGE_KEY).includes('original-entry'),false);
assert.equal(JSON.stringify(history.state).includes('original-entry'),false);assert.equal(history.state.unrelated,'preserved');
connection.remember({host:'antigravity',scope:'project',project:'/fixture/very long project'},'native');
const restored = new Connection(api,env);api.connection=restored;
await restored.start(new URLSearchParams());
assert.deepEqual(restored.initial,{host:'antigravity',scope:'project',project:'/fixture/very long project',view:'native'});
assert.equal(calls.filter(call=>call.path==='/api/session').length,1,'普通reload不能再签发/延长');
assert.equal(history.state[HISTORY_KEY].project,'/fixture/very long project');
// 精确重现项目 → 用户级 → 普通刷新：当前 API 范围保持 global，独立导航提示应保留已知项目。
restored.remember({host:'antigravity',scope:'global'},'native');
const globalReload = new Connection(api,env);api.connection=globalReload;
await globalReload.start(new URLSearchParams());
assert.deepEqual(globalReload.initial,{host:'antigravity',scope:'global',view:'native'});
assert.equal(globalReload.knownProject,'/fixture/very long project','普通刷新不应丢失已知项目导航提示');
assert.equal(Object.hasOwn(history.state[HISTORY_KEY],'project'),false,'global 历史导航不能冒充项目范围');
assert.equal(history.state[HISTORY_KEY].knownProject,globalReload.knownProject);
assert.equal(Object.hasOwn(JSON.parse(values.get(STORAGE_KEY)),'knownProject'),false,'会话存储仍只有派生凭据');
// 用真实业务 API 验证提示不会混入 global 请求，再由实际导航合同切回该项目。
const contextRequests=[];
const contextApi=new ModelApi('test',async path=>{
  contextRequests.push(path);const query=new URL(path,origin).searchParams;
  return response({...context(),host:query.get('host'),scope:query.get('scope'),project:query.get('project')});
});
await contextApi.context(globalReload.initial);
assert.equal(new URL(contextRequests[0],origin).searchParams.has('project'),false);
const returnLocation=navigation({...globalReload.initial,scope:'project',project:globalReload.knownProject});
assert.equal(returnLocation.project,'/fixture/very long project');
globalReload.remember(returnLocation,'native');
await contextApi.context(returnLocation);
assert.equal(new URL(contextRequests[1],origin).searchParams.get('project'),'/fixture/very long project');
// history 是可篡改输入；非法提示只能被忽略，不能扩大当前范围或保留到下一次历史记录。
for(const hint of [undefined,null,42,{},'relative/project','/fixture/../other','/'+'a'.repeat(4096),'/fixture/\ncontrol','/fixture/\x00control']) {
  assert.equal(validProject(hint),false);
  history.state[HISTORY_KEY]={host:'codex',scope:'global',view:'native',knownProject:hint};
  const invalidHint=new Connection(api,env);api.connection=invalidHint;
  await invalidHint.start(new URLSearchParams());
  assert.deepEqual(invalidHint.initial,{host:'codex',scope:'global',view:'native'});
  assert.equal(invalidHint.knownProject,null);
  assert.equal(Object.hasOwn(history.state[HISTORY_KEY],'knownProject'),false);
}
history.state[HISTORY_KEY]={host:'antigravity',scope:'global',view:'native',knownProject:'/fixture/old'};
// 新有效入口优先，旧项目目标不能覆盖新host/global；非法会话和实例切换均撤销恢复凭据。
const replacement = new Connection(api,env);api.connection=replacement;
await replacement.start(new URLSearchParams({token:'new-original',host:'codex'}));
assert.equal(replacement.initial.scope,'global');assert.equal(replacement.initial.host,'codex');
assert.equal(replacement.knownProject,null);assert.equal(Object.hasOwn(history.state[HISTORY_KEY],'knownProject'),false);
history.state[HISTORY_KEY]={host:'antigravity',scope:'global',view:'native',knownProject:'/fixture/old'};
const newProject=new Connection(api,env);api.connection=newProject;
await newProject.start(new URLSearchParams({token:'new-project-entry',host:'claude',project:'/fixture/new'}));
assert.equal(newProject.initial.project,'/fixture/new');assert.equal(newProject.knownProject,'/fixture/new');
assert.equal(history.state[HISTORY_KEY].knownProject,'/fixture/new','新项目入口优先于旧提示');
const badApi = new ModelApi('',async()=>response({protocol_version:2,instance_id:'c'.repeat(32)}));
const mismatched = new Connection(badApi,env);badApi.connection=mismatched;
await assert.rejects(mismatched.start(new URLSearchParams()),error=>error.code==='instance_changed');
assert.equal(values.has(STORAGE_KEY),false);assert.equal(badApi.token,'');
assert.equal(sessionContract({...derived,expires_at:Date.now()-1},origin),null);
assert.equal(sessionContract({...derived,origin:'http://127.0.0.1:other'},origin),null);
const missing = new Connection(api,env);api.connection=missing;
await assert.rejects(missing.start(new URLSearchParams()),error=>error.code==='authentication');
assert.equal(missing.knownProject,'/fixture/new','认证失败只保留导航提示，不恢复可写连接');assert.equal(missing.ready,false);
const blockedEnv={...env,storage:()=>{throw Error('blocked');}};
const memory = new Connection(api,blockedEnv);api.connection=memory;
await memory.start(new URLSearchParams({token:'memory-original',project:'/fixture/memory'}));assert.equal(memory.ready,true);assert.equal(memory.storageAvailable,false);
memory.remember({host:'codex',scope:'global'},'native');
const blockedReload=new Connection(api,blockedEnv);api.connection=blockedReload;
await assert.rejects(blockedReload.start(new URLSearchParams()),error=>error.code==='authentication');
assert.equal(blockedReload.initial.scope,'global');assert.equal(blockedReload.knownProject,'/fixture/memory');assert.equal(blockedReload.ready,false);
memory.session.expires_at=0;assert.throws(()=>memory.authorize(),error=>error.code==='authentication');assert.equal(api.token,'');
values.set(STORAGE_KEY,JSON.stringify({...derived,expires_at:Date.now()-1}));
const expiredReload=new Connection(api,env);api.connection=expiredReload;
await assert.rejects(expiredReload.start(new URLSearchParams()),error=>error.code==='authentication');
assert.equal(expiredReload.initial.scope,'global');assert.equal(expiredReload.knownProject,'/fixture/memory');
assert.equal(values.has(STORAGE_KEY),false);assert.equal(api.token,'');
// 401/403从共享请求层失效，不能继续使用上次context保存。
for(const status of [401,403]) {
 let invalidated=0; const denied=new ModelApi('derived',async()=>response({error:{code:'unauthorized'}},status));
 denied.connection={authorize(){},clear(){denied.token='';}};denied.onInvalidConnection=()=>invalidated++;
 await assert.rejects(denied.context({host:'codex',scope:'global'}));assert.equal(invalidated,1);assert.equal(denied.token,'');
}
""")

    def test_native_search_keeps_opaque_selection_and_truthful_unknown_facts(self):
        # 搜索无结果与同名不同来源不能偷换保存身份；没有权限/启用字段必须明确未知。
        self.run_javascript(r"""
const {NativeDefinitions,facts} = require('./native_config/web/native-definitions.js');
const view=new NativeDefinitions();
const rows=[row('user:a',{name:'same',description:'用户定义',source_path:'/user/same.md'}),row('plugin:b',{name:'same',description:'插件职责',source_path:'/plugin/same.md',writable:false})];
assert.equal(view.project('global',rows).selected.role,'user:a');
view.select('global','plugin:b',rows);view.search('global','用户');
assert.deepEqual(view.project('global',rows).rows.map(row=>row.role),['user:a']);
assert.equal(view.project('global',rows).selected.role,'plugin:b');
// 名称导航简化后仍按职责和来源路径搜索，且筛选不改变原始稳定身份。
view.search('global','/plugin/');
assert.deepEqual(view.project('global',rows).rows.map(row=>row.role),['plugin:b']);
assert.equal(view.project('global',rows).selected.role,'plugin:b');
view.search('global','no-match');assert.equal(view.project('global',rows).rows.length,0);
assert.equal(view.project('global',rows).selected.role,'plugin:b');
assert.equal(view.project('global',[rows[0]]).selected,null,'消失身份不能回退到同名首项');
assert.equal(view.project('project',rows).selected.role,'user:a','不同上下文独立选中');
assert.equal(facts(rows[0]).find(row=>row[0]==='权限')[1],'宿主未提供可核验权限信息');
assert.equal(facts({...rows[0],enabled:false}).find(row=>row[0]==='启用状态')[1],'已观察到停用');
""")

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

    def test_preference_consecutive_saves_automatically_prepare_and_reuse_catalog(self):
        # 同一生产草稿、目录所有者和HTTP协议连续预览/确认两次，模拟同页继续编辑。
        # 服务端每次保存推进revision但保持模型来源，验证无需人工刷新且仍提交最新CAS基线。
        self.run_javascript(r"""
let revision=1, saved='model-a', catalogReads=0, applies=0, pending;
const ctx=()=>({...context(),revision:'rev-'+revision,catalog_source_stamp:'source-stable',
  dispatch_preferences:{status:'ready',runtime_verified:false,capabilities:{model:true,effort:true,efforts:['low','high']},
    targets:[{target:'*',writable:true,overrides:{model:saved},effective:{model:saved},sources:{model:'user_default'}}]}});
const api=new ModelApi('test',async(path,init)=>{
  if(path.startsWith('/api/catalog')) {catalogReads++;return response({status:'ready',source_stamp:'source-stable',models:[]});}
  if(path.startsWith('/api/context')) return response(ctx());
  const body=JSON.parse(init.body);
  if(path==='/api/preview') {
    assert.equal(body.revision,'rev-'+revision,'预览必须保留服务端最新CAS');
    pending=body.dispatch_preferences.edits['*'].model;
    return response({preview_id:'plan-'+revision,changes:[{target:'*',field:'model',before:saved,after:pending}],warnings:[],effect:{kind:'dispatch_preferences',runtime_verified:false}});
  }
  assert.equal(path,'/api/apply');assert.equal(body.preview_id,'plan-'+revision);
  saved=pending;revision++;applies++;
  return response({saved:true,effect:{saved:true,runtime_verified:false},context:ctx()});
});
const draft=new Draft({host:'codex',scope:'global'});draft.accept(contextContract(ctx()));
const loader=new CatalogLoader(api,value=>value===draft);
assert.equal(loader.current(draft),null,'首次编辑没有目录缓存');
for(const model of ['model-b','model-c']) {
  draft.preferences.set('*','model',model);
  assert.ok(await loader.load(draft),'每次预览自动准备目录，首次缺失也不能跳过');
  assert.equal(draft.preferences.value('*','model'),model,'目录回读必须保留编辑');
  const plan=await api.previewPreferences(draft.location,draft.context.revision,draft.preferences.payload(),false);
  const receipt=await api.apply(plan.preview_id);
  draft.accept(receipt.context,'dispatch_preferences');
  assert.equal(draft.preferences.dirty,false);assert.equal(draft.preferences.value('*','model'),model);
}
assert.equal(applies,2);assert.equal(catalogReads,1,'来源不变时后续保存不能全量刷新目录');
""")

    def test_catalog_stale_inflight_join_bounded_source_retry_and_failures(self):
        # 目录实际异步所有者处理空缓存、过期、同范围去重及最多一次来源变化重读。
        self.run_javascript(r"""
const draft=new Draft({host:'codex',scope:'global'});draft.accept({...context(),catalog_source_stamp:'source-new'});
draft.catalog={status:'ready',source_stamp:'source-old',models:[]};draft.catalogStamp='source-old';
draft.set('opaque:a','model','keep-draft');
let release, reads=0, contexts=0;
const loader=new CatalogLoader({catalog:()=>{reads++;return new Promise(resolve=>{release=resolve;});},
  context:async()=>{contexts++;return {...context(),catalog_source_stamp:'source-new'};}},value=>value===draft);
assert.equal(loader.current(draft),null);
const first=loader.load(draft), second=loader.load(draft,true);
assert.equal(first,second,'预览与已进行读取必须等待同一个promise');
let joined=false;second.then(()=>{joined=true;});await Promise.resolve();
assert.equal(joined,false,'目录未响应时不能让第二个等待者提前继续');
release({status:'ready',source_stamp:'source-new',models:[]});await Promise.all([first,second]);
assert.equal(reads,1);assert.equal(contexts,1);assert.ok(loader.current(draft));
assert.equal(draft.value('opaque:a','model'),'keep-draft');
// 单次来源漂移自动恢复，持续漂移与真实读取失败均有明确拒绝，草稿不清空。
let drift=0;
const changing=new CatalogLoader({catalog:async()=>({status:'ready',source_stamp:++drift===1?'old':'stable',models:[]}),
  context:async()=>({...context(),catalog_source_stamp:'stable'})},()=>true);
draft.catalogStamp=null;assert.ok(await changing.load(draft));assert.equal(drift,2);
let unstableReads=0;
const unstable=new CatalogLoader({catalog:async()=>{unstableReads++;return {status:'ready',source_stamp:'always-old',models:[]};},
  context:async()=>({...context(),catalog_source_stamp:'always-new'})},()=>true);
await assert.rejects(unstable.load(draft,true),error=>error.code==='catalog_changed');assert.equal(unstableReads,2);
const unavailable=new CatalogLoader({catalog:async()=>({status:'failed',models:[]}),context:async()=>context()},()=>true);
await assert.rejects(unavailable.load(draft,true),error=>error.code==='catalog_unavailable');
assert.equal(draft.value('opaque:a','model'),'keep-draft');
let networkAttempts=0;
const transient=new CatalogLoader({catalog:async()=>{
  if(++networkAttempts===1)throw new ApiError('network','临时读取失败');
  return {status:'ready',source_stamp:'recovered',models:[]};
},context:async()=>({...context(),catalog_source_stamp:'recovered'})},()=>true);
await assert.rejects(transient.load(draft),error=>error.code==='network');
assert.ok(await transient.load(draft),'下次预览可重试同一来源，不要求人工刷新');assert.equal(networkAttempts,2);
""")

    def test_catalog_scope_switch_cancels_late_context_and_preview_intent(self):
        # 取消期间fetch可忽略AbortSignal；真实owner仍须阻止晚到回读和后续预览/保存。
        self.run_javascript(r"""
const old=new Draft({host:'codex',scope:'global'});old.accept({...context(),catalog_source_stamp:'old'});
const next=new Draft({host:'codex',scope:'project',project:'/fixture/other'});next.accept({...context(),scope:'project',project:'/fixture/other',catalog_source_stamp:'next'});
let active=old, release, previews=0, applies=0;
const loader=new CatalogLoader({catalog:async()=>({status:'ready',source_stamp:'late',models:[]}),
  context:()=>new Promise(resolve=>{release=resolve;})},value=>value===active);
const intended=old;
const previewIntent=loader.load(old).then(catalog=>{
  if(!catalog||active!==intended)return;
  previews++;applies++;
});
await Promise.resolve();assert.equal(typeof release,'function');
loader.cancel();active=next;
release({...context(),revision:'late-revision',catalog_source_stamp:'late'});await previewIntent;
assert.equal(old.context.revision,'rev-1');assert.equal(old.catalog,null);
assert.equal(previews,0);assert.equal(applies,0);
// 返回相同Draft对象也不能复活已取消的预览意图。
active=old;assert.equal(loader.current(old),null);
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

    def test_activation_contract_independent_drafts_and_exclusive_preview(self):
        # 同一生产 Draft/API 验证两类草稿的归属与请求边界；不以页面文案快照替代业务断言。
        self.run_javascript(r"""
const activation = {supported:true,writable:true,state:'inherit',plugin_id:'agent-workflow@market',
  source_path:'/tmp/project/.codex/config.toml',inherited_state:'disabled',inherited_source:'/tmp/home/.codex/config.toml',
  effective_state:'disabled',diagnostics:[],recovery:{open_command:'bash /tmp/agent_config.sh open',official_steps:['使用官方插件设置恢复'],documentation_url:'https://example.test/plugins'},
  runtime_verified:false,scope:'global',read_only_reason:null};
const ctx = state => ({...context(), workflow_activation:{...activation,state}});
const draft = new Draft({host:'codex',scope:'global'});
draft.accept(contextContract(ctx('inherit')));
draft.set('opaque:a','model','new-model'); draft.activation.set('enabled');
assert.equal(draft.anyDirty,true);
draft.accept(ctx('inherit'), 'model');
assert.equal(draft.dirty,false); assert.equal(draft.activation.value,'enabled'); assert.equal(draft.activation.dirty,true);
draft.set('opaque:a','effort','low');
draft.accept(ctx('enabled'), 'workflow_activation');
assert.equal(draft.activation.dirty,false); assert.equal(draft.value('opaque:a','effort'),'low');
const created = {saved:false,partial_failure:true,effect:{saved:false,pending_reload:true,runtime_verified:false},
  created_directories:['/tmp/project/.codex'],created_files:[{role:'workflow_activation',target:'/tmp/project/.codex/config.toml',
  before_absent:true,published:true,observed_identity:[1,2],location_status:'unknown',recovery_action:'保留实际发布对象并重新预览'}]};
assert.equal(applyReceiptContract(created).created_files[0].published,true);
for (const bad of [{...created,created_directories:['../unsafe']},{...created,created_files:[{...created.created_files[0],location_status:'assumed'}]}])
  assert.throws(()=>applyReceiptContract(bad), error=>error.code==='invalid_response');
draft.activation.set('disabled'); draft.accept(ctx('inherit'));
assert.equal(draft.activation.value,'disabled','重新读取不能丢弃启停草稿');
draft.clear(); assert.equal(draft.activation.dirty,true,'放弃模型草稿不能丢弃启停草稿');
draft.activation.clear(); assert.equal(draft.anyDirty,false);
draft.accept({...context(),workflow_activation:{...activation,supported:false,writable:false,state:'unknown',plugin_id:null,source_path:null}});
draft.activation.set('enabled'); assert.equal(draft.activation.value,'unknown'); assert.equal(draft.activation.dirty,false);
for (const bad of [{...activation,state:'yes'},{...activation,effective_state:'inherit'},
  {...activation,supported:false},{...activation,plugin_id:null},{...activation,recovery:{...activation.recovery,official_steps:[false]}},
  {...activation,runtime_verified:true}]) assert.throws(() => activationContract(bad), error => error.code==='invalid_response');
assert.throws(() => contextContract({...context(),workflow_activation:{...activation,scope:'project'}}));
const change = {kind:'workflow_activation',field:'enabled',scope:'project',source_path:activation.source_path,
  plugin_id:activation.plugin_id,before:'inherit',after:'disabled',effective_before:'unknown',effective_after:'disabled'};
const plan = {preview_id:'activation-plan',changes:[change],warnings:[],effect:{saved:false,runtime_verified:false}};
const calls=[]; const api = new ModelApi('test',async (path, init) => {calls.push(JSON.parse(init.body));return response(plan);});
const location={host:'claude',scope:'project',project:'/tmp/project'};
await api.previewActivation(location,'revision-a','disabled');
assert.deepEqual(calls[0],{...location,revision:'revision-a',workflow_activation:{state:'disabled'}});
assert.equal(Object.hasOwn(calls[0],'edits'),false); assert.equal(Object.hasOwn(calls[0],'reset'),false);
await assert.rejects(api.previewActivation(location,'revision-a','unknown'), error => error.code==='invalid_input');
const mixed = new ModelApi('test',async () => response({...plan,changes:[{role:'opaque:a',field:'model'}]}));
await assert.rejects(mixed.previewActivation(location,'revision-a','enabled'), error => error.code==='invalid_response');
const wrongScope = new ModelApi('test',async () => response({...plan,changes:[{...change,scope:'global'}]}));
await assert.rejects(wrongScope.previewActivation(location,'revision-a','enabled'), error => error.code==='invalid_response');
""")

    def test_preferences_empty_native_inventory_three_drafts_and_model_specific_options(self):
        # 直接运行生产状态/API：Codex 空定义与 Claude 只读插件都不能让独立偏好入口失效。
        self.run_javascript(r"""
const target = (id, fields={}) => ({target:id,name:id,origin:id==='*'?'default':'plugin',overrides:{},effective:{},
  sources:{model:'host_default',effort:'host_default'},writable:true,read_only_reason:null,dispatch_ready:false,
  discovered:id!=='*',invoke_name_verified:id!=='*',runtime_verified:false,...fields});
const preferences = targets => ({status:'ready',targets,capabilities:{model:true,effort:true,model_format:'model_id',efforts:['low','high','ultra']},runtime_verified:false});
const draft = new Draft({host:'codex',scope:'global'});
const ctx={...context([]),dispatch_preferences:preferences([target('*')])};
draft.accept(contextContract(ctx));
draft.preferences.set('*','model','model-a'); draft.preferences.set('*','effort','high');
assert.equal(draft.preferences.dirty,true,'无原生 Agent 仍可编辑 *');
assert.equal(draft.dirty,false); assert.equal(draft.anyDirty,true);
draft.accept(ctx); assert.equal(draft.preferences.value('*','effort'),'high','重读保留偏好草稿');
draft.accept({...ctx,roles:[row('native-user')],dispatch_preferences:preferences([target('*'),target('vendor:worker')])});
draft.set('native-user','model','native-draft'); draft.preferences.set('vendor:worker','model','model-b');
draft.accept(draft.context,'dispatch_preferences');
assert.equal(draft.preferences.dirty,false);assert.equal(draft.value('native-user','model'),'native-draft');
draft.preferences.set('*','model','model-a'); draft.accept(draft.context,'model');
assert.equal(draft.dirty,false);assert.equal(draft.preferences.dirty,true);
const claude={...ctx,host:'claude',roles:[row('plugin-only',{writable:false,origin:'plugin'})],
 dispatch_preferences:{...preferences([target('*'),target('agent-workflow:xy-web')]),
 capabilities:{model:true,effort:true,model_format:'alias',model_aliases:['sonnet','opus','inherit'],efforts:['low','high']}}};
draft.accept(contextContract(claude));draft.preferences.set('agent-workflow:xy-web','model','opus');
assert.equal(draft.preferences.value('agent-workflow:xy-web','model'),'opus');assert.equal(draft.context.roles[0].writable,false);
assert.throws(()=>preferenceContract({...ctx.dispatch_preferences,targets:[]}),ApiError);
assert.throws(()=>preferenceContract({...ctx.dispatch_preferences,targets:[target('*'),target('*')]}),ApiError);
const catalog={models:[{id:'model-a',efforts:['low'],efforts_verified:true},{id:'model-b',efforts:['high'],efforts_verified:true},
{id:'sonnet',label:'sonnet → local-full-id',usage:'dispatch_alias',efforts:[],efforts_verified:false},
{id:'full-id',usage:'native_definition_only'}]};
assert.deepEqual(effortOptions(ctx,catalog,'model-a',true).values,['low']);
assert.deepEqual(effortOptions(ctx,catalog,'model-b',true).values,['high']);
assert.equal(effortOptions(ctx,catalog,'unknown',true).verified,false);
assert.equal(modelCandidates(claude,catalog,true).some(row=>row.id==='full-id'),false);
assert.equal(modelCandidates(claude,catalog,false).some(row=>row.id==='full-id'),true);
assert.equal(modelCandidates(claude,catalog,true).find(row=>row.id==='sonnet').label,'sonnet → local-full-id');
const agy={...ctx,host:'antigravity',dispatch_preferences:{...ctx.dispatch_preferences,
capabilities:{model:true,effort:false,model_format:'tier',model_tiers:['inherit','flash','pro']}}};
assert.deepEqual(modelCandidates(agy,{models:[{id:'session-only',usage:'session_only'}],subagent_models:[{id:'pro',usage:'subagent_tier'}]},true).map(row=>row.id),['inherit','flash','pro']);
assert.deepEqual(effortOptions(agy,catalog,'pro',true).values,[]);
const calls=[];const api=new ModelApi('test',async(path,init)=>{calls.push(JSON.parse(init.body));return response({preview_id:'preference-plan',changes:[{target:'*',role:'*',field:'model'}],warnings:[],effect:{kind:'dispatch_preferences',runtime_verified:false}});});
await api.previewPreferences({host:'codex',scope:'project',project:'/tmp/isolated'},'rev',{ '*':{model:null,effort:'low'} });
assert.deepEqual(calls[0],{host:'codex',scope:'project',project:'/tmp/isolated',revision:'rev',dispatch_preferences:{edits:{'*':{model:null,effort:'low'}},reset:false}});
assert.equal(Object.hasOwn(calls[0],'edits'),false);assert.equal(Object.hasOwn(calls[0],'reset'),false);assert.equal(Object.hasOwn(calls[0],'workflow_activation'),false);
""")

    def test_visible_draft_resolution_preserves_hidden_inheritance_and_custom_ids(self):
        # 只投影公开的当前层/最终来源；清除被遮蔽字段必须等后端预览，不能猜测上层。
        self.run_javascript(r"""
const draft = new Draft({host:'codex',scope:'global'});
const target=(id,overrides,effective,sources)=>({target:id,name:id,origin:'user',writable:true,overrides,effective,sources});
draft.accept({...context([]),dispatch_preferences:{status:'ready',runtime_verified:false,capabilities:{model:true,effort:true},targets:[
 target('*',{model:'saved/unknown:model'},{model:'saved/unknown:model'},{model:'user_default'}),
 target('vendor:worker',{}, {model:'saved/unknown:model'}, {model:'user_default'})]}});
assert.equal(resolvedField(draft.preferences,'*','model',true).value,'saved/unknown:model');
assert.equal(resolvedField(draft.preferences,'*','model',true,true).pending,true,'继承选项不能把被删除的已保存覆盖冒充继承值');
draft.preferences.set('*','model','future/custom-id');
assert.equal(resolvedField(draft.preferences,'vendor:worker','model',true).value,'future/custom-id');
draft.preferences.set('*','model',null);
assert.equal(resolvedField(draft.preferences,'*','model',true).pending,true);
assert.equal(resolvedField(draft.preferences,'vendor:worker','model',true).value,null);
assert.equal(resolvedField(draft.preferences,'vendor:worker','model',true).source,'继承值待预览');
assert.deepEqual(draft.preferences.payload(),{'*':{model:null}});
// 逐身份的本层覆盖高于通用草稿，不能跟着默认联动被悄悄改值。
draft.preferences.set('vendor:worker','model','private-model');
assert.equal(resolvedField(draft.preferences,'vendor:worker','model',true).value,'private-model');
assert.equal(draft.preferences.value('*','effort'),null);
// 真实原生context的inherit仅表示宿主默认未观察，不能冒充模型ID或有效推理值。
const native = new Draft({host:'codex',scope:'global'});
native.accept(context([row('native-inherits',{overrides:{},effective:{model:'inherit',effort:'inherit'},sources:{model:'host_unresolved',effort:'host_unresolved'}})]));
assert.equal(resolvedField(native,'native-inherits','effort').value,null);
assert.equal(resolvedField(native,'native-inherits','model').value,null);
native.set('native-inherits','model','fixture-model');assert.equal(resolvedField(native,'native-inherits','model').value,'fixture-model');
native.set('native-inherits','model','inherit');assert.equal(resolvedField(native,'native-inherits','model').value,'inherit','明确草稿覆盖不能被占位规范化吞掉');
native.accept(context([row('known-inherit',{overrides:{},effective:{model:'inherit'},sources:{model:'user'}})]));
assert.equal(resolvedField(native,'known-inherit','model').value,'inherit','已知来源不能被当作宿主未观察占位');


""")

    def test_picker_projection_preserves_unknown_ids_and_validates_custom_input(self):
        # 真实选择器使用同一投影/字符校验函数：搜索内容不能暗自裁剪成配置值，
        # 未知历史ID必须仍可见可选，名称只负责展示，不代替提交的原始ID。
        self.run_javascript(r"""
const choices = modelChoices([{id:'known/id',label:'完整模型名称'}], 'saved/unknown:model', '继承值待预览');
assert.deepEqual(choices.map(row => row.value), ['', 'known/id', 'saved/unknown:model']);
assert.equal(choices[0].inherited, true);
assert.equal(choices[1].label, '完整模型名称');
assert.equal(choices[2].unknown, true);
assert.equal(modelChoices([{id:'known/id'}], 'known/id', '宿主默认').length, 2);
for (const value of ['a', 'vendor/model-v2:preview+fast@1[beta]', 'a'.repeat(200)]) assert.equal(validCustomModelId(value), true);
for (const value of ['', ' a', 'a ', 'a\n', 'a\r', 'a\u2028', '中文', '<img>', 'a'.repeat(201)]) assert.equal(validCustomModelId(value), false, JSON.stringify(value));
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
