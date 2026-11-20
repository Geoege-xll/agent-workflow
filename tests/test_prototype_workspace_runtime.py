from __future__ import annotations

import json
import shutil
import subprocess
import unittest
from pathlib import Path


PACK = Path(__file__).resolve().parents[1]
TEMPLATES = PACK / "templates/prototype"

# 只执行真实生产状态/相机纯函数，不以假DOM证明浏览器布局或跨file授权。
# 真正的source/origin/page/token桥、原生控件和键盘操作另由prepare产物浏览器证据覆盖。
STATE_SETUP = r"""
const assert = require('node:assert/strict');
const vm = require('node:vm');
const {webcrypto} = require('node:crypto');
const input = JSON.parse(require('node:fs').readFileSync(0, 'utf8'));
const store = new Map();
const storage = {getItem(key) { return store.get(key) || null; }, setItem(key, value) { store.set(key, value); }};
const window = {crypto: webcrypto, sessionStorage: storage};
vm.runInNewContext(input.source, {window, TextEncoder, TextDecoder, console});
const boot = {schema_version:4, context: {schema_version:3, request_id:'review-302', project_id:'1'.repeat(64), adapter:'project.yaml', adapter_sha256:'2'.repeat(64), prototype_root:'docs/prototype', plan_source:'docs/plans/review.md', plan_sha256:'a'.repeat(64), navigation_sha256:'3'.repeat(64), tool:{version:'3.0.2',payload_sha256:'4'.repeat(64)},review_id:'5'.repeat(64),requirements:['REQ-007'],pages:[{path:'docs/prototype/settings.html',dependency_fingerprint:'b'.repeat(64)},{path:'docs/prototype/reports.html',dependency_fingerprint:'c'.repeat(64)}]},pages:['settings','reports'].map(name=>({name:name+'.html',path:'docs/prototype/'+name+'.html',url:'project/docs/prototype/'+name+'.html',label:name,groups:[]}))};
const encode = value => JSON.stringify(value).replace(/[<>&\u2028\u2029]/g, char => `\\u${char.charCodeAt(0).toString(16).padStart(4,'0')}`);
const parsed = window.PrototypeReviewState.parseStartup(encode(boot));
assert.ok(parsed.context, parsed.error);
const model = window.PrototypeReviewState.create(parsed, storage);
const target = (id, page='settings') => ({scope:'node',page:'docs/prototype/'+page+'.html',locator:{type:'id',id}});
const record = (id, page='settings') => ({key:'source-'+(id==='first'?'a':'b').repeat(64),target:target(id,page),text:'当前摘录',label:'button '+id,has_parent:true,req_ids:['REQ-007'],interaction_id:'',interaction_text:'',interface_refs:[]});
model.setCatalog('docs/prototype/settings.html',[record('first'),record('second')]);
model.setCatalog('docs/prototype/reports.html',[record('first','reports')]);
const message = value => model.updateDraft({message:value});
const snapshot = () => JSON.stringify({items:model.state.items,anchors:model.state.anchors,nextItem:model.state.nextItem,nextAnchor:model.state.nextAnchor});
"""

SCENARIOS = {
    "strict_startup": r"""
for (const patch of [{schema_version:2},{kind:'suggestion'},{context:{...boot.context,approval:true}}]) {
  assert.equal(window.PrototypeReviewState.parseStartup(encode({...boot,...patch})).context,null);
}
assert.equal(window.PrototypeReviewState.parseStartup(encode(boot).replace('"schema_version":4','"schema_version":4,"schema_version":4')).context,null);
assert.equal(window.PrototypeReviewState.parseStartup(encode({...boot,pages:[{...boot.pages[0],url:'../escape.html'},boot.pages[1]]})).context,null);
for(const requirements of [[{id:'REQ-007',label:'旧目录'}],['REQ-007','REQ-007'],['伪造需求']]) {
  assert.equal(window.PrototypeReviewState.parseStartup(encode({...boot,context:{...boot.context,requirements}})).context,null);
}
assert.equal(window.PrototypeReviewState.parseStartup(encode({...boot,schema_version:3})).context,null);
assert.equal(window.PrototypeReviewState.parseStartup(encode({...boot,context:{...boot.context,schema_version:2}})).context,null);
// 新上下文只接受与启动入口相同的来源种类，旧上下文仍拒绝多余字段。
const offlineContext = {...boot.context,schema_version:4,source_kind:'offline'};
assert.ok(window.PrototypeReviewState.parseStartup(encode({...boot,context:offlineContext})).context);
for (const context of [{...offlineContext,source_kind:'live'},{...boot.context,schema_version:4},{...boot.context,source_kind:'offline'}]) {
  assert.equal(window.PrototypeReviewState.parseStartup(encode({...boot,context})).context,null);
}
""",
    "operations_and_independent_numbers": r"""
model.select(record('first')); const anchor=model.addAnchor(); assert.equal(anchor.number,1);
assert.equal(model.addAnchor().id,anchor.id);
model.openEditor(target('first')); message('甲'.repeat(4000));
model.updateDraft({reference_ids:[anchor.id],after_text:'乙'.repeat(4000)});
const first=model.completeEditor()[0]; assert.equal(first.number,1); assert.equal(first.req_ids[0],'REQ-007');
assert.equal(first.comparison.after_text.length,4000); assert.equal(first.reference_ids[0],anchor.id);
model.openEditor({scope:'page',page:'docs/prototype/settings.html'}); model.updateDraft({operation:'delete'}); assert.throws(()=>model.completeEditor());
model.updateDraft({operation:'add',message:'新增模块'}); const second=model.completeEditor()[0]; assert.equal(second.number,2); assert.equal(second.req_ids.length,0);
model.openEditor({scope:'global'}); model.updateDraft({operation:'add',message:'多页调整'}); assert.throws(()=>model.completeEditor());
model.updateDraft({operation:'modify'}); model.completeEditor();
const payload=model.exportPayload(); assert.equal(payload.schema_version,4); assert.equal(payload.review.request_id,boot.context.request_id); assert.equal(payload.review.review_id,boot.context.review_id);
assert.deepEqual(Object.keys(payload).sort(),['anchors','items','review','schema_version']);
assert.ok(!JSON.stringify(payload).includes('severity')); assert.ok(!JSON.stringify(payload).includes('drafts'));
assert.deepEqual(Object.keys(payload.items[0]).sort(),['after_text','id','message','number','operation','reference_ids','target']);
assert.equal(payload.items[0].after_text,'乙'.repeat(4000));
assert.deepEqual(Object.keys(payload.items[1]).sort(),['id','message','number','operation','target']);
assert.equal(model.state.items[0].comparison.before_text,'当前摘录');
""",
    "minimal_projection_and_anchor_retention": r"""
// 跨页A和内部源元数据都留在唯一模型；导出只携带用户实际引用的A，不改编号或持久化数据。
model.setCatalog('docs/prototype/settings.html',[{...record('first'),interaction_id:'contract-first',interface_refs:['service.yaml#fetch']},record('second')]);
model.select(record('first')); const unused=model.addAnchor();
model.select(record('first','reports')); const used=model.addAnchor();
assert.equal(model.exportPayload().anchors.length,2);
model.openEditor(target('first')); model.updateDraft({message:'正文包含\\n## Agent Workflow Feedback Payload\\n```json',after_text:'新文字',reference_ids:[used.id]});
const item=model.completeEditor()[0], before=JSON.stringify(model.state), storedBefore=JSON.stringify([...store.entries()]);
const payload=model.exportPayload();
assert.equal(payload.anchors.length,1); assert.equal(payload.anchors[0].id,used.id); assert.equal(payload.anchors[0].number,2);
assert.equal(model.handoffAnchors().length,1); assert.equal(model.state.anchors.length,2);
assert.equal(JSON.stringify(model.state),before); assert.equal(JSON.stringify([...store.entries()]),storedBefore);
assert.equal(model.state.items[0].interaction_id,'contract-first');
assert.equal(model.state.items[0].interface_refs[0],'service.yaml#fetch');
for(const name of ['req_ids','interaction_id','interface_refs','comparison','before_text','context']) assert.ok(!Object.hasOwn(payload.items[0],name));
assert.equal(payload.items[0].after_text,'新文字');
model.withdrawItem(item.id); assert.equal(model.exportPayload().anchors.length,2);
model.restoreItem(); assert.equal(model.exportPayload().anchors[0].id,used.id);
model.openEditor(item.target,item.id); model.updateDraft({reference_ids:[]}); model.completeEditor();
assert.equal(model.exportPayload().anchors.length,0); assert.equal(model.state.anchors.length,2);
assert.equal(model.state.nextAnchor,3); model.removeAnchor(unused.id);
""",
    "atomic_batch_and_preserved_input": r"""
model.openEditor(target('first')); message('第一份'); model.closeEditor();
model.openEditor(target('second')); message(''); model.updateDraft({operation:'add'}); model.closeEditor();
const before=snapshot(); let failed;
try { model.completeAll(); } catch(error) { failed=error; }
assert.ok(failed); assert.ok(failed.draftKey); assert.equal(snapshot(),before); assert.equal(model.activeDrafts().length,2);
model.resumeEditor(failed.draftKey); message('第二份'); model.completeAll();
assert.equal(model.state.items.length,2); assert.equal(model.state.items[0].number,1); assert.equal(model.state.items[1].number,2);
model.openEditor(target('first')); message('超'.repeat(4001)); assert.throws(()=>model.completeEditor()); assert.equal(model.state.drafts[model.state.editor].message.length,4001);
""",
    "reference_protection_withdraw_restore": r"""
model.select(record('first')); const anchor=model.addAnchor();
model.openEditor(target('second')); message('引用定位'); model.updateDraft({reference_ids:[anchor.id]});
assert.throws(()=>model.removeAnchor(anchor.id)); const item=model.completeEditor()[0]; assert.throws(()=>model.removeAnchor(anchor.id));
model.openEditor(item.target,item.id); message('编辑未完成'); model.closeEditor();
model.withdrawItem(item.id); assert.equal(model.activeDrafts().length,0); assert.equal(model.state.items.length,0);
model.removeAnchor(anchor.id); model.restoreItem(); assert.equal(model.state.items[0].number,1); assert.equal(model.activeDrafts().length,1);
assert.equal(model.state.drafts['edit:'+item.id].message,'编辑未完成');
model.resumeEditor('edit:'+item.id); assert.throws(()=>model.completeEditor());
model.updateDraft({reference_ids:[]}); const edited=model.completeEditor()[0]; assert.equal(edited.number,1); assert.equal(edited.id,item.id);
model.select(record('second')); assert.equal(model.addAnchor().number,2);
model.openEditor(target('first')); message('下一条'); assert.equal(model.completeEditor()[0].number,2);
""",
    "source_and_session_boundaries": r"""
model.select({...record('first'),target:null,key:'runtime-1'}); model.openEditor(null); message('动态元素意图'); assert.throws(()=>model.completeEditor());
model.closeEditor(); model.select(record('first')); assert.ok(model.state.drafts.unresolved);
model.select(record('first'),true); assert.ok(!model.state.drafts.unresolved);
model.openEditor(target('first')); assert.equal(model.state.drafts[model.state.editor].message,'动态元素意图'); model.completeEditor();
model.setCamera('docs/prototype/settings.html',{x:22,y:33,k:.5});
const restored=window.PrototypeReviewState.create(parsed,storage); assert.equal(restored.state.items.length,1); assert.equal(restored.state.cameras['docs/prototype/settings.html'].k,.5);
assert.equal(restored.exportPayload().items.length,1);
const key=[...store.keys()][0]; const saved=JSON.parse(store.get(key)); saved.unknown=true; store.set(key,JSON.stringify(saved));
assert.equal(window.PrototypeReviewState.create(parsed,storage).state.items.length,0);
// v3草稿与不同review_id均不读取、不迁移；v4旧格式伪装也必须由封闭schema检查拒绝。
store.clear(); saved.unknown=undefined; saved.schema_version=3; store.set('prototype-review:v3:'+boot.context.review_id,JSON.stringify(saved));
assert.equal(window.PrototypeReviewState.create(parsed,storage).state.items.length,0);
store.set('prototype-review:v4:'+boot.context.review_id,JSON.stringify(saved));
assert.equal(window.PrototypeReviewState.create(parsed,storage).state.items.length,0);
saved.schema_version=4; saved.review_id='9'.repeat(64); store.set('prototype-review:v4:'+boot.context.review_id,JSON.stringify(saved));
assert.equal(window.PrototypeReviewState.create(parsed,storage).state.items.length,0);
const unavailable={getItem(){throw Error('denied');},setItem(){throw Error('quota');}};
const memory=window.PrototypeReviewState.create(parsed,unavailable); memory.openEditor({scope:'global'}); memory.updateDraft({message:'内存保留'}); memory.completeEditor();
assert.equal(memory.state.items.length,1); assert.ok(memory.state.storageMessage.includes('存储失败'));
model.block(); assert.throws(()=>model.exportPayload());
""",
}


@unittest.skipUnless(shutil.which("node"), "Node is required to execute production browser JavaScript")
class PrototypeWorkspaceRuntimeTests(unittest.TestCase):
    def test_restore_byte_budget_is_atomic(self) -> None:
        """条数未满时恢复仍受同一1MiB预算约束，失败不吞掉撤回快照或编辑草稿。"""
        source = (TEMPLATES / "review-state.js").read_text(encoding="utf-8")
        scenario = r"""
for(let i=0;i<86;i++) { model.openEditor({scope:'global'}); message('汉'.repeat(4000)); model.completeEditor(); }
assert.equal(model.state.items.length,86);
const original=model.state.items[0];
model.openEditor(original.target,original.id); message('保留撤回关联编辑草稿'); model.closeEditor();
model.withdrawItem(original.id);
model.openEditor({scope:'global'}); message('汉'.repeat(4000)); model.completeEditor();
const before=JSON.stringify(model.state), storageBefore=JSON.stringify([...store.entries()]);
assert.throws(()=>model.restoreItem(),/1MiB/);
assert.equal(JSON.stringify(model.state),before);
assert.equal(JSON.stringify([...store.entries()]),storageBefore);
assert.equal(model.state.items.length,86);
assert.equal(model.state.withdrawn.item.id,original.id);
assert.equal(model.state.withdrawn.draft.message,'保留撤回关联编辑草稿');
assert.ok(new TextEncoder().encode(JSON.stringify(model.exportPayload())).length<=1048576);
"""
        result = subprocess.run(["node", "-e", STATE_SETUP + scenario], input=json.dumps({"source": source}),
                                text=True, capture_output=True, check=False)
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)

    def test_actual_formatter_limits_utf8_and_preserves_failed_batch(self) -> None:
        """执行视图真正使用的formatter，验证多字节全文上限和提交前拒绝不改变草稿。"""
        # 此处消费真实生产生成文字与当前Python解析器，不复制formatter或伪造浏览器通信。
        from lib.documents.prototype_feedback import parse_feedback

        scenario = r"""
vm.runInNewContext(input.feedback, {window, TextEncoder, TextDecoder, console});
const checkBytes=window.PrototypeReviewState.checkFeedbackBytes;
const exact='汉'.repeat(Math.floor(1048576/3))+'a';
assert.equal(new TextEncoder().encode(exact).length,1048576);
assert.equal(checkBytes(exact),exact); assert.throws(()=>checkBytes(exact+'汉'),/1MiB/);
const format=payload=>window.PrototypeFeedback.formatExport(payload,()=> '本轮整体');
for(let i=0;i<40;i++) { model.openEditor({scope:'global'}); message('汉'.repeat(4000)); model.completeEditor(); }
const validBefore=JSON.stringify(model.state), validText=format(model.exportPayload());
assert.equal(JSON.stringify(model.state),validBefore);
assert.ok(new TextEncoder().encode(validText).length<=1048576);
assert.ok(validText.includes('汉'.repeat(4000)));
assert.equal(validText,'## Agent Workflow Feedback Payload\n```json\n'+JSON.stringify(model.exportPayload())+'\n```\n');
// 紧凑格式不再重复正文：先填满真实项目集合，再按候选JSON字节数构造仅围栏超限边界。
// 固定长度UUID替身只用于预测新增条目的序列化长度，不替代实际completeAll编号与原子提交。
for(let i=40;i<86;i++) { model.openEditor({scope:'global'}); message('汉'.repeat(4000)); model.completeEditor(); }
const candidate=JSON.parse(JSON.stringify(model.exportPayload()));
candidate.items.push({id:'item-'+'0'.repeat(36),number:87,operation:'modify',target:{scope:'global'},message:''});
const remaining=1048575-new TextEncoder().encode(JSON.stringify(candidate)).length;
assert.ok(remaining>0 && remaining<=12000);
// 正文仍遵守4000字符上限，用三字节汉字与末尾ASCII精确补足UTF8预算。
model.openEditor({scope:'global'}); message('汉'.repeat(Math.floor(remaining/3))+'a'.repeat(remaining%3));
const draftBefore=JSON.stringify(model.state), draftStoredBefore=JSON.stringify([...store.entries()]);
assert.throws(()=>model.completeAll(format),/交还全文.*1MiB/);
assert.equal(JSON.stringify(model.state),draftBefore);
assert.equal(JSON.stringify([...store.entries()]),draftStoredBefore);
assert.equal(model.activeDrafts().length,1);
model.completeAll();
assert.equal(new TextEncoder().encode(JSON.stringify(model.exportPayload())).length,1048575);
const before=JSON.stringify(model.state), storedBefore=JSON.stringify([...store.entries()]);
assert.throws(()=>format(model.exportPayload()),/交还全文.*1MiB.*缩短正文或撤回部分整改/);
assert.equal(JSON.stringify(model.state),before);
assert.equal(JSON.stringify([...store.entries()]),storedBefore);
process.stdout.write(validText);
"""
        result = subprocess.run(["node", "-e", STATE_SETUP + scenario],
                                input=json.dumps({"source": (TEMPLATES / "review-state.js").read_text(encoding="utf-8"),
                                                  "feedback": (TEMPLATES / "feedback.js").read_text(encoding="utf-8")}),
                                text=True, capture_output=True, check=False)
        self.assertEqual(0, result.returncode, result.stderr)
        raw = result.stdout.encode("utf-8")
        self.assertLessEqual(len(raw), 1048576)
        parsed = parse_feedback(raw)
        self.assertEqual(4, parsed["schema_version"])
        self.assertEqual(40, len(parsed["items"]))
        self.assertEqual("汉" * 4000, parsed["items"][0]["message"])

    def test_restore_capacity_boundary_is_atomic(self) -> None:
        """恢复遵守256条上限；拒绝时保留编号、撤回关联草稿和持久化原状。"""
        source = (TEMPLATES / "review-state.js").read_text(encoding="utf-8")
        scenario = r"""
for(let i=0;i<256;i++) { model.openEditor(target('first')); message('整改'+i); model.completeEditor(); }
const original=model.state.items[0];
model.openEditor(original.target,original.id); message('被撤回整改的编辑草稿'); model.closeEditor();
model.withdrawItem(original.id);
assert.equal(model.state.items.length,255);
model.restoreItem();
assert.equal(model.state.items.length,256);
assert.equal(model.state.items.at(-1).id,original.id);
assert.equal(model.state.items.at(-1).number,original.number);
assert.equal(model.state.drafts['edit:'+original.id].message,'被撤回整改的编辑草稿');
model.withdrawItem(original.id);
model.openEditor(target('first')); message('撤回后补满的新整改'); model.completeEditor();
assert.equal(model.state.items.length,256);
const before=JSON.stringify(model.state), storageBefore=JSON.stringify([...store.entries()]);
assert.throws(()=>model.restoreItem(),/256条整改上限/);
assert.equal(JSON.stringify(model.state),before);
assert.equal(JSON.stringify([...store.entries()]),storageBefore);
assert.equal(model.state.withdrawn.item.id,original.id);
assert.equal(model.state.withdrawn.draft.message,'被撤回整改的编辑草稿');
assert.equal(model.exportPayload().items.length,256);
"""
        result = subprocess.run(["node", "-e", STATE_SETUP + scenario], input=json.dumps({"source": source}),
                                text=True, capture_output=True, check=False)
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)

    def test_state_machine_regressions(self) -> None:
        """编号/原子提交/受保护引用和来源绑定的真实生产函数回归。"""
        source = (TEMPLATES / "review-state.js").read_text(encoding="utf-8")
        for name, scenario in SCENARIOS.items():
            with self.subTest(name=name):
                result = subprocess.run(["node", "-e", STATE_SETUP + scenario], input=json.dumps({"source": source}),
                                        text=True, capture_output=True, check=False)
                self.assertEqual(0, result.returncode, result.stdout + result.stderr)

    def test_live_boot_and_draft_protocol_are_separate(self) -> None:
        """真实模型验证live登记cap、草稿恢复、反馈5与旧快照互不混用。"""
        scenario = r"""
const liveBoot={...boot,schema_version:5,pages:boot.pages.map(entry=>({...entry,url:'/content/'+'a'.repeat(48)+'/'+entry.path+'#bridge='+'b'.repeat(32)}))};
const live=window.PrototypeReviewState.parseStartup(encode(liveBoot)); assert.ok(live.context,live.error); assert.equal(live.schema_version,5);
for (const kind of ['offline','live']) {
  const context={...liveBoot.context,schema_version:4,source_kind:kind};
  assert.equal(Boolean(window.PrototypeReviewState.parseStartup(encode({...liveBoot,context})).context),kind==='live');
}
for(const url of ['https://evil.test/content/'+ 'a'.repeat(48)+'/'+boot.pages[0].path, '/content/'+'a'.repeat(48)+'/../escape#bridge='+'b'.repeat(32), 'project/'+boot.pages[0].path]) {
  assert.equal(window.PrototypeReviewState.parseStartup(encode({...liveBoot,pages:[{...liveBoot.pages[0],url},liveBoot.pages[1]]})).context,null);
}
const liveModel=window.PrototypeReviewState.create(live,storage);
liveModel.openEditor({scope:'global'}); liveModel.updateDraft({message:'新协议意见'}); liveModel.completeEditor();
assert.equal(liveModel.exportPayload().schema_version,5);
assert.equal(JSON.parse(store.get('prototype-review:v5:'+boot.context.review_id)).schema_version,5);
assert.equal(window.PrototypeReviewState.create(live,storage).state.items[0].message,'新协议意见');
assert.equal(window.PrototypeReviewState.create(parsed,storage).state.items.length,0);
assert.equal(liveModel.exportPayload().review.review_id,boot.context.review_id);
liveModel.block(); assert.throws(()=>liveModel.exportPayload()); assert.throws(()=>liveModel.addAnchor(),/原稿已变化/); assert.equal(liveModel.state.items[0].message,'新协议意见');
"""
        result = subprocess.run(["node", "-e", STATE_SETUP + scenario],
                                input=json.dumps({"source": (TEMPLATES / "review-state.js").read_text(encoding="utf-8")}),
                                text=True, capture_output=True, check=False)
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)

    def test_live_connection_keeps_cas_and_credentials_at_boundary(self) -> None:
        """HTTP边界不重放冲突PUT，首次凭据清除fragment且刷新只恢复本轮受限凭据。"""
        script = r"""
const vm=require('node:vm'),assert=require('node:assert/strict');
const source=JSON.parse(require('node:fs').readFileSync(0,'utf8'));
const saved=new Map(),calls=[]; let cleaned='';
const location={origin:'http://127.0.0.1:45123',pathname:'/review/a.html',search:'',hash:'#token='+'a'.repeat(64)};
const context={review_id:'b'.repeat(64)},window={};
const response={revision:0,draft:null};
vm.runInNewContext(source,{window,location,URLSearchParams,sessionStorage:{getItem:key=>saved.get(key),setItem:(key,value)=>saved.set(key,value)},
  history:{replaceState(a,b,url){cleaned=url;}},AbortController,setTimeout,clearTimeout,
  fetch:async(path,options)=>{calls.push({path,options});return options.method==='PUT'?{ok:false,status:409,json:async()=>({status:'error',error:{code:'draft_conflict',message:'冲突'}})}:{ok:true,json:async()=>response};}});
(async()=>{
const api=window.PrototypeLiveConnection.create(context); assert.equal(cleaned,'/review/a.html');
assert.equal(saved.size,1); assert.ok([...saved.keys()][0].includes(context.review_id));
assert.equal((await api.readDraft()).revision,0);
await assert.rejects(api.saveDraft(0,{schema_version:5}),error=>error.code==='draft_conflict');
assert.equal(calls.filter(call=>call.options.method==='PUT').length,1);
assert.equal(calls[1].options.credentials,'omit'); assert.equal(calls[1].options.headers.Authorization,'Bearer '+'a'.repeat(64));
assert.equal(JSON.parse(calls[1].options.body).revision,0);
assert.ok(api.reviewURL('a.html').startsWith(location.origin+'/review/a.html#token='));
api.close(); await assert.rejects(api.readDraft()); assert.equal(calls.length,2);
})().catch(error=>{console.error(error);process.exitCode=1;});
"""
        result = subprocess.run(["node", "-e", script],
                                input=json.dumps((TEMPLATES / "live-connection.js").read_text(encoding="utf-8")),
                                text=True, capture_output=True, check=False)
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)

    def test_browser_bootstrap_binds_exact_review_without_url_secret(self) -> None:
        """执行正式连接边界：顶层引导同修订可用，错修订/重复槽不能回退旧缓存。"""
        script = r"""
const vm=require('node:vm'),assert=require('node:assert/strict');
const source=JSON.parse(require('node:fs').readFileSync(0,'utf8'));
function load(value, duplicate=false) {
 const window={},saved=new Map(),calls=[];let removed=false;
 const slot={type:'application/json',textContent:JSON.stringify(value),remove(){removed=true;}};
 vm.runInNewContext(source,{window,location:{origin:'http://127.0.0.1:45123',pathname:'/review/a.html',search:'',hash:''},
  document:{querySelectorAll:()=>duplicate?[slot,slot]:[slot]},URLSearchParams,
  sessionStorage:{getItem:()=> 'c'.repeat(64),setItem:(key,value)=>saved.set(key,value)},history:{replaceState(){}},
  AbortController,setTimeout,clearTimeout,fetch:async(path,options)=>{calls.push(options);return {ok:true,json:async()=>({revision:0,draft:null})};}});
 return {window,calls,saved,removed:()=>removed};
}
(async()=>{
 const value={schema_version:1,review_id:'b'.repeat(64),token:'a'.repeat(64)};
 const good=load(value),api=good.window.PrototypeLiveConnection.create({review_id:value.review_id});
 await api.readDraft();assert.equal(good.calls[0].headers.Authorization,'Bearer '+value.token);assert.equal(good.removed(),true);api.close();
 for(const [bad,duplicate] of [[{...value,review_id:'d'.repeat(64)},false],[{...value,token:''},false],[value,true]]) {
   const result=load(bad,duplicate);assert.throws(()=>result.window.PrototypeLiveConnection.create({review_id:value.review_id}));assert.equal(result.calls.length,0);
 }
})().catch(error=>{console.error(error);process.exitCode=1;});
"""
        result = subprocess.run(["node", "-e", script], input=json.dumps((TEMPLATES / "live-connection.js").read_text(encoding="utf-8")),
                                text=True, capture_output=True, check=False)
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)

    def test_live_link_intents_keep_legacy_modifier_semantics(self) -> None:
        """执行真实click监听器：live Alt交由登记导航，旧V4修饰键边界保持。"""
        script = r"""
const vm=require('node:vm'),assert=require('node:assert/strict');
const source=JSON.parse(require('node:fs').readFileSync(0,'utf8'));
// 此节点只验证生产监听器的事件决策；真实iframe导航和重新握手另由浏览器覆盖。
const begin=source.indexOf('  document.addEventListener("click", (event) => {');
const end=source.indexOf('  document.addEventListener("pointermove"',begin);
assert.ok(begin>=0 && end>begin);
function run({live=true,mode='annotate',temporary=false,altKey=false,href='details.html',ctrlKey=false,metaKey=false,shiftKey=false}={}) {
 let listener,chosen=false;const messages=[];
 const target={closest(selector){return selector==='a[href]'?{getAttribute(){return href;}}:null;}};
 const event={target,button:0,altKey,ctrlKey,metaKey,shiftKey,defaultPrevented:false,preventDefault(){this.defaultPrevented=true;},stopImmediatePropagation(){}};
 vm.runInNewContext(source.slice(begin,end),{document:{addEventListener(type,callback){listener=callback;}},session:'active',panMoved:false,live,mode,temporary,inContent:()=>target,choose(){chosen=true;},send(type,body){messages.push({type,...body});}});
 listener(event);return {prevented:event.defaultPrevented,chosen,messages};
}
let result=run({altKey:true,temporary:true});assert.equal(result.prevented,true,'live Alt链接必须阻止iframe默认导航');
assert.equal(result.messages[0]?.intent,'navigate');assert.equal(result.messages[0]?.target,'details.html');
result=run({mode:'browse'});assert.equal(result.prevented,true);assert.equal(result.messages[0]?.target,'details.html');
result=run();assert.equal(result.chosen,true);assert.equal(result.messages.length,0);
for(const href of ['missing.html','../outside.html','https://example.invalid/']) {result=run({altKey:true,temporary:true,href});assert.equal(result.prevented,true);assert.equal(result.messages[0]?.target,href);}
for(const modifier of [{altKey:true},{ctrlKey:true},{metaKey:true},{shiftKey:true}]) {result=run({live:false,mode:'browse',...modifier});assert.equal(result.prevented,false);assert.equal(result.messages.length,0);}
"""
        result = subprocess.run(["node", "-e", script], input=json.dumps((TEMPLATES / "page-shell.js").read_text(encoding="utf-8")),
                                text=True, capture_output=True, check=False)
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)

    def test_bridge_resolve_accepts_persisted_key_order(self) -> None:
        """真实resolve按字段语义解析服务排序JSON，不能把同一来源误判为失效。"""
        script = r"""
const vm=require('node:vm'),assert=require('node:assert/strict');const source=JSON.parse(require('node:fs').readFileSync(0,'utf8'));
const begin=source.indexOf('  function resolve(value) {'),end=source.indexOf('  function parentNode(',begin);assert.ok(begin>=0&&end>begin);
const exact=(value,keys)=>value&&Object.keys(value).length===keys.length&&keys.every(key=>Object.hasOwn(value,key));
for(const locator of [{type:'id',id:'title'},{type:'source',key:'source-'+'a'.repeat(64)}]){
 const node={},actual={scope:'node',page:'docs/prototype/details.html',locator};
 const context={exact,sourceAttr:'data-prototype-review-source',page:actual.page,stableId:value=>value==='title',sourceKey:value=>value===locator.key,unique:(attr,value)=>value===(locator.id||locator.key)?node:null,target:()=>actual};
 vm.createContext(context);vm.runInContext(source.slice(begin,end)+';globalThis.invoke=resolve;',context);
 const ordered=JSON.parse(JSON.stringify(actual,(key,value)=>value&&typeof value==='object'&&!Array.isArray(value)?Object.fromEntries(Object.entries(value).sort()):value));
 assert.equal(context.invoke(ordered),node,'服务JSON键排序不应破坏真实目标解析');
 assert.equal(context.invoke({...ordered,page:'docs/prototype/other.html'}),null);
 assert.equal(context.invoke({...ordered,unknown:true}),null);
 assert.equal(context.invoke({...ordered,locator:{...ordered.locator,unknown:true}}),null);
}
"""
        result = subprocess.run(["node", "-e", script], input=json.dumps((TEMPLATES / "page-shell.js").read_text(encoding="utf-8")),
                                text=True, capture_output=True, check=False)
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)

    def test_live_sorted_node_draft_restores_same_target(self) -> None:
        """消费服务同样排序的真实快照，节点草稿与定位身份必须按封闭字段语义恢复。"""
        scenario = r"""
const liveBoot={...boot,schema_version:5,pages:boot.pages.map(entry=>({...entry,url:'/content/'+'a'.repeat(48)+'/'+entry.path+'#bridge='+'b'.repeat(32)}))};
const live=window.PrototypeReviewState.parseStartup(encode(liveBoot));const original=window.PrototypeReviewState.create(live,storage);
original.setCatalog('docs/prototype/settings.html',[record('first'),record('second')]);original.select(record('first'));const anchor=original.addAnchor();
original.openEditor(target('second'));original.updateDraft({message:'排序后节点草稿保留',reference_ids:[anchor.id]});
const key='prototype-review:v5:'+boot.context.review_id;
const sortJSON=value=>JSON.stringify(value,(name,entry)=>entry&&typeof entry==='object'&&!Array.isArray(entry)?Object.fromEntries(Object.entries(entry).sort()):entry);
store.set(key,sortJSON(JSON.parse(store.get(key))));
const restored=window.PrototypeReviewState.create(live,storage);assert.equal(restored.state.anchors.length,1);assert.equal(restored.activeDrafts().length,1);
restored.setCatalog('docs/prototype/settings.html',[record('first'),record('second')]);assert.ok(restored.recordFor(restored.state.anchors[0].target));
assert.equal(restored.targetKey(restored.state.anchors[0].target),restored.targetKey(target('first')));
restored.openEditor(target('second'));assert.equal(restored.state.drafts[restored.state.editor].message,'排序后节点草稿保留');assert.equal(restored.completeEditor()[0].reference_ids[0],anchor.id);
for(const bad of [{...target('first'),unknown:true},{scope:'node',page:'docs/prototype/settings.html',locator:{type:'id',id:'first',unknown:true}}])assert.equal(restored.validTarget(bad),false);
for(const legal of [{scope:'global'},{scope:'page',page:'docs/prototype/settings.html'},target('first'),{scope:'node',page:'docs/prototype/settings.html',locator:{type:'source',key:'source-'+'a'.repeat(64)}}])assert.equal(restored.targetKey(legal),JSON.stringify(legal));
"""
        result = subprocess.run(["node", "-e", STATE_SETUP + scenario], input=json.dumps({"source": (TEMPLATES / "review-state.js").read_text(encoding="utf-8")}),
                                text=True, capture_output=True, check=False)
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)

    def test_camera_preserves_world_point_and_scale(self) -> None:
        """复用相机的缩放中心和仅平移定位不改变缩放。"""
        source = (TEMPLATES / "review-camera.js").read_text(encoding="utf-8")
        script = r"""
const vm=require('node:vm'),assert=require('node:assert/strict'); const window={};
const context={window};
vm.runInNewContext(JSON.parse(require('node:fs').readFileSync(0,'utf8')), context);
const cam={x:10,y:20,k:.5}, next=window.PrototypeReviewCamera.zoomAt(cam,2,100,200);
assert.equal((100-cam.x)/cam.k,(100-next.x)/next.k); assert.equal((200-cam.y)/cam.k,(200-next.y)/next.k);
assert.equal(window.PrototypeReviewCamera.focusBounds(cam,{x:40,y:50,w:200,h:100},800,600).k,.5);
assert.equal(window.PrototypeReviewCamera.zoomAt(cam,100,0,0).k,3);
assert.ok(window.PrototypeReviewCamera.fitCam(390,600).k>=.08);
// 固定手机的适应比例由真实尺寸决定，不能继续暗用桌面1120×860。
const mobile=window.PrototypeReviewCamera.fitCam(900,1000,390,844,76);
assert.equal(mobile.k,1); assert.equal(mobile.x,255);
const desktop=window.PrototypeReviewCamera.fitCam(900,1000,1440,900,76);
assert.ok(desktop.k<mobile.k);
// 实际 create 注册的事件决定相机归属：不复制 wheel/pan 实现，也不以宿主证明浏览器滚动。
const listeners=new Map(),windowEvents=new Map();let value={x:10,y:20,k:1},writes=0;
window.addEventListener=(type,fn)=>windowEvents.set(type,fn);window.removeEventListener=()=>{};
context.ResizeObserver=class {observe(){} disconnect(){}};
const viewport={addEventListener:(type,fn)=>listeners.set(type,fn),getBoundingClientRect:()=>({left:0,top:0,width:900,height:700}),setPointerCapture(){},classList:{add(){},remove(){}}};
const world={style:{},offsetWidth:800,offsetHeight:600};
const camera=window.PrototypeReviewCamera.create({viewport,world,read:()=>value,write:next=>{value=next;writes++;}});
const event=patch=>({target:viewport,button:0,pointerId:1,clientX:10,clientY:20,deltaX:30,deltaY:90,preventDefault(){this.prevented=true;},...patch});
viewport.closest=()=>null;
for(const patch of [{},{shiftKey:true},{deltaY:-90}]) {const e=event(patch),before=JSON.stringify(value);listeners.get('wheel')(e);assert.equal(e.prevented,undefined);assert.equal(JSON.stringify(value),before);}
listeners.get('pointerdown')(event());listeners.get('pointermove')(event({clientX:30,clientY:40}));assert.equal(writes,0,'普通左键空白拖动不接管相机');
listeners.get('keydown')(event({code:'Space'}));const ordinary=event();listeners.get('wheel')(ordinary);assert.equal(ordinary.prevented,undefined);assert.equal(writes,0,'Space+wheel也不能平移');
listeners.get('pointerdown')(event());listeners.get('pointermove')(event({clientX:30,clientY:50}));assert.equal(value.x,30);assert.equal(value.y,50);listeners.get('pointerup')();
listeners.get('keyup')(event({code:'ShiftLeft'}));listeners.get('pointerdown')(event());listeners.get('pointermove')(event({clientX:20,clientY:30}));assert.equal(value.x,40,'释放其他键不结束仍按住的Space');listeners.get('pointercancel')();
listeners.get('keyup')(event({code:'Space'}));
for(const modifier of ['ctrlKey','metaKey']) {const e=event({[modifier]:true,clientX:100,clientY:200}),before={...value};listeners.get('wheel')(e);assert.equal(e.prevented,true);assert.notEqual(value.k,before.k);assert.ok(Math.abs((100-before.x)/before.k-(100-value.x)/value.k)<1e-9);}
const beforeMiddle={...value};listeners.get('pointerdown')(event({button:1}));listeners.get('pointermove')(event({clientX:35,clientY:45}));assert.equal(value.x,beforeMiddle.x+25);assert.equal(value.y,beforeMiddle.y+25);listeners.get('pointerup')();
listeners.get('keydown')(event({code:'Space'}));windowEvents.get('blur')();const beforeBlur=JSON.stringify(value);listeners.get('pointerdown')(event());listeners.get('pointermove')(event({clientX:99}));assert.equal(JSON.stringify(value),beforeBlur,'失焦后不保留Space状态');
listeners.get('keydown')(event({key:'ArrowLeft'}));assert.equal(value.x,JSON.parse(beforeBlur).x+40,'聚焦画布的既有方向键可访问性保留');
camera.close();
// 两个正式外壳传入同一可用区，位置随工具组改变；缩放或定位后由使用者接管相机。
let usable={width:600,height:450,paddingX:24,paddingY:24};
const modern=window.PrototypeReviewCamera.create({viewport,world,read:()=>value,write:next=>{value=next;},
  dimensions:()=>({width:390,height:844}),readArea:()=>usable});
function assertCentered() {
  assert.ok(Math.abs(value.x + 390*value.k/2 - usable.width/2)<1e-9);
  assert.ok(Math.abs(value.y + 844*value.k/2 - usable.height/2)<1e-9);
  assert.ok(value.y >= 0 && value.y + 844*value.k < usable.height, '完整画板在底部工具条之前');
}
modern.fit();assertCentered();
usable={...usable,height:360};modern.refresh();assertCentered();
modern.zoom(1.25);const manual=value;usable={width:290,height:48,paddingX:24,paddingY:12};modern.refresh();assert.equal(value,manual);
modern.fit();assertCentered();assert.ok(value.k>0 && value.k<.08,'极短视口仍能适应完整手机');
const compact=value.k;modern.zoom(1.25);assert.equal(value.k,compact*1.25);
// 放大后的比例仍低于历史 8% 时，减按钮和组合键滚轮都必须能缩回同一个适应下限。
modern.zoom(1/1.25);assert.ok(Math.abs(value.k-compact)<1e-9,'缩小按钮缩回极短视口原始适应比例');
modern.zoom(.5);assert.equal(value.k,compact,'再次缩小仍停在实际适应比例');
for(const modifier of ['ctrlKey','metaKey']) {
  listeners.get('wheel')(event({[modifier]:true,deltaY:-90}));assert.ok(value.k>compact && value.k<.08);
  listeners.get('wheel')(event({[modifier]:true,deltaY:180}));assert.equal(value.k,compact,'组合键滚轮可缩回同一适应下限');
}
modern.zoom(1.25);const compactManual=value;
usable={width:600,height:450,paddingX:24,paddingY:24};modern.refresh();assert.equal(value,compactManual,'手动相机在尺寸变化后保持显示比例');
modern.zoom(.5);assert.equal(value.k,compact,'未重新适应时，保留已由当前画板建立的下限');
modern.fit();modern.zoom(.01);assert.equal(value.k,.08,'宽视口重新适应后沿用常规下限');
usable={width:290,height:48,paddingX:24,paddingY:12};modern.fit();
value={x:10,y:20,k:.12};modern.restore();modern.zoom(.5);
assert.equal(value.k,.08,'恢复另一页的持久相机时，采用历史下限');
modern.focus({x:10,y:24,w:20,h:16});assert.equal(value.y+(24+8)*value.k,usable.height/2);
modern.resetZoom();assert.equal(value.k,1,'百分比按钮按当前展示相机恢复 100%');
modern.close();
"""
        result = subprocess.run(["node", "-e", script], input=json.dumps(source), text=True, capture_output=True, check=False)
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)

    def test_presentation_keeps_frozen_positive_viewport_bounds(self) -> None:
        """尺寸合同接受最小正数与最大16384，拒绝零、负数、无穷与越界；不默认为桌面尺寸。"""
        script = r"""
const vm=require('node:vm'),assert=require('node:assert/strict'),window={};
const context={window};vm.runInNewContext(JSON.parse(require('node:fs').readFileSync(0,'utf8')),context);
const valid=window.PrototypeCanvasPresentation.validSize;
for(const size of [{width:1,height:1},{width:390,height:844},{width:16384,height:16384}]) assert.equal(valid(size),true);
for(const size of [{width:0,height:844},{width:-1,height:844},{width:16385,height:844},{width:Infinity,height:844},{width:'390',height:844}]) assert.equal(valid(size),false);
const observed=[];let observer;context.ResizeObserver=class {constructor(fn){observer=fn;}observe(node){observed.push(node);}disconnect(){}};
let rect={top:50,width:900,height:700},toolbarTop=690,reportedHeight;
const viewport={getBoundingClientRect:()=>rect},toolbar={getBoundingClientRect:()=>({top:toolbarTop})},world={style:{}},preview={style:{}};
const presentation=window.PrototypeCanvasPresentation.create({viewport,world,preview,toolbar,entry:{display:'responsive',viewport:null},onResize:()=>{reportedHeight=preview.style.height;}});
assert.deepEqual(observed,[viewport,toolbar]);assert.equal(presentation.read().height,592);assert.equal(presentation.read().width,852);
assert.equal(presentation.resize({width:852,height:12000},true),false,'长内容不能扩大responsive iframe');assert.equal(preview.style.height,'592px');
toolbarTop=630;observer();assert.equal(reportedHeight,'532px','只有工具组换行时也先更新子视口，再重算相机');
rect={top:50,width:800,height:600};toolbarTop=570;observer();assert.equal(preview.style.height,'472px','窗口变化更新可用设计视口');
presentation.select({display:'fixed',viewport:{width:390,height:844}});assert.equal(preview.style.height,'844px');
assert.equal(presentation.resize({width:390,height:12000},true),false,'子稿不能覆盖固定声明');assert.equal(preview.style.height,'844px');
presentation.select({display:'fixed',viewport:null});assert.equal(presentation.resize({width:390,height:844},true),true);
assert.equal(presentation.resize({width:390,height:12000},true),false,'只接受首次真实fixed frame测量');assert.equal(preview.style.height,'844px');
presentation.select({display:'responsive',viewport:{width:390,height:844}});assert.equal(preview.style.width,'752px','responsive按父可用视口而非历史设备尺寸');
assert.equal(presentation.resize({display:'fixed',width:390,height:844},true),false,'目录明示 responsive 时拒绝子稿固定尺寸');
presentation.select({label:'HTTP 登记页'});
assert.equal(presentation.resize({width:390,height:844},true),false,'导航目录没有展示声明时不接受无类型尺寸');
assert.equal(presentation.resize({display:'fixed',width:390,height:844},true),true,'认证 HTTP 子桥可用真实画板补足固定视口');
assert.equal(presentation.resize({display:'fixed',width:390,height:12000},true),false,'固定视口补足只接受一次');
presentation.matchColorScheme('only light');assert.equal(preview.style.colorScheme,'light');
presentation.select({display:'responsive',viewport:null});assert.equal(preview.style.colorScheme,'','切页重新协商色系');
presentation.matchColorScheme('light dark');assert.equal(preview.style.colorScheme,'','保留支持双色系稿件的当前偏好');
let frameHeight=12000;context.document={body:{dataset:{prototypeDisplay:'responsive'}},querySelectorAll:()=>[{getBoundingClientRect:()=>({width:390,height:frameHeight})}]};context.innerWidth=752;context.innerHeight=552;
assert.equal(window.PrototypeCanvasPresentation.measure().height,552,'responsive测量返回视口而非自然长内容');
context.document.body.dataset.prototypeDisplay='fixed';frameHeight=844;assert.equal(window.PrototypeCanvasPresentation.measure().height,844);
presentation.close();
"""
        result = subprocess.run(["node", "-e", script], input=json.dumps((TEMPLATES / "canvas-presentation.js").read_text(encoding="utf-8")),
                                text=True, capture_output=True, check=False)
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)

    def test_child_wheel_and_drag_keep_native_scroll_ownership(self) -> None:
        """执行两种真实子稿入口：根containment、普通wheel/边界不接管、显式缩放与拖动。"""
        script = r"""
const vm=require('node:vm'),assert=require('node:assert/strict');
const source=JSON.parse(require('node:fs').readFileSync(0,'utf8'));
function run(file) {
 const documentEvents=new Map(),windowEvents=new Map(),messages=[],scrollCalls=[];
 class Node {
  constructor(tag='DIV'){this.tagName=tag;this.style={};this.dataset={};this.attrs={};this.children=[];this.classes=new Set();this.classList={add:v=>this.classes.add(v),toggle(){},remove(){}};this.textContent='Long content';this.innerText='Long content';this.id='';}
  append(child){this.children.push(child);child.parentElement=this;}addEventListener(){}setAttribute(k,v){this.attrs[k]=v;}getAttribute(k){return this.attrs[k]??null;}querySelectorAll(){return [];}querySelector(){return null;}closest(selector){return this.classes.has(selector.slice(1))?this:null;}matches(){return false;}contains(node){return node===this || this.children.some(child=>child.contains(node));}getBoundingClientRect(){return {left:0,top:0,x:0,y:0,width:800,height:12000};}setPointerCapture(){}replaceChildren(){this.children=[];}scrollTo(options){scrollCalls.push({node:this,options});this.scrollTop=options.top;this.scrollLeft=options.left;}
 }
 const html=new Node('HTML'),body=new Node('BODY'),head=new Node('HEAD'),stage=new Node(),frame=new Node(),root=new Node('MAIN'),nested=new Node();
 stage.classes.add('prototype-stage');html.append(body);body.append(stage);stage.append(frame);frame.append(root);
 nested.style={overflow:'auto',overscrollBehavior:'auto'};nested.scrollTop=0;root.append(nested);
 body.dataset.prototypeDisplay='responsive';root.id='design';root.attrs.id='design';root.attrs['data-prototype-review-source']='source-'+'a'.repeat(64);
 Object.assign(html,{scrollTop:0,scrollLeft:0,scrollHeight:12000,clientHeight:600,scrollWidth:800,clientWidth:800});
 root.getBoundingClientRect=()=>({left:20,top:2400-html.scrollTop,x:20,y:2400-html.scrollTop,width:200,height:40});
 const document={documentElement:html,scrollingElement:html,body,head,readyState:'complete',
 currentScript:{src:file?'file:///fixture/assets/file-page.js':'http://127.0.0.1:12345/assets/page-shell.js',getAttribute:key=>({'data-prototype-review-bridge':'5','data-prototype-review-page':'docs/prototype/settings.html','data-prototype-review-token':'a'.repeat(48)})[key]},
 querySelector(selector){return {'[data-prototype-page-content]':root,'.prototype-frame':frame,'.prototype-stage':stage}[selector]??null;},
 querySelectorAll(selector){return ['[data-prototype-page-content]','[id]','[data-prototype-review-source]'].includes(selector)?[root]:[];},createElement:tag=>new Node(tag.toUpperCase()),addEventListener:(type,fn)=>documentEvents.set(type,fn)};
 const parent={postMessage:value=>messages.push(value)},window={parent,location:{protocol:file?'file:':'http:',pathname:'/docs/prototype/settings.html'},XYFilePageContext:{name:'settings.html',nonce:'b'.repeat(48)},addEventListener:(type,fn)=>windowEvents.set(type,fn)};
 const context={window,parent,document,location:window.location,URL,Element:Node,HTMLElement:Node,getComputedStyle:()=>({display:'block',visibility:'visible',opacity:'1',colorScheme:'light'}),ResizeObserver:class{observe(){}},MutationObserver:class{observe(){}},requestAnimationFrame:()=>1,setTimeout:()=>1,innerWidth:800,innerHeight:600};
 vm.runInNewContext(source.presentation,context);
 vm.runInNewContext(file?source.file:source.review,context);
 assert.equal(html.classes.has('prototype-canvas-embedded'),false,'握手前不启用透明派生样式');
 windowEvents.get('message')({source:parent,origin:file?'null':'http://127.0.0.1:12345',data:file?{type:'xy-file:connect',page:'settings.html',nonce:'b'.repeat(48)}:{type:'prototype-review:connect',version:5,page:'docs/prototype/settings.html',token:'a'.repeat(48),mode:'browse'}});
 assert.equal(html.style.overscrollBehavior,'contain');assert.deepEqual(nested.style,{overflow:'auto',overscrollBehavior:'auto'},'不得修改业务nested scrollport');
 assert.equal(messages.find(value=>value.type.endsWith(':ready')).colorScheme,'light');
 assert.equal(html.classes.has('prototype-canvas-embedded'),true);assert.equal(stage.classes.has('prototype-canvas-stage'),true);
 assert.equal(frame.classes.has('prototype-canvas-stage'),false,'业务画板本身不应用透明背景');
 assert.equal(messages.some(value=>value.type.endsWith(':size')),false,'responsive长内容不再向父层上报整页高度');
 if(!file) {
  const locate=()=>windowEvents.get('message')({source:parent,origin:'http://127.0.0.1:12345',data:{type:'prototype-review:review',version:5,page:'docs/prototype/settings.html',token:'a'.repeat(48),action:'locate',request:'root-location',target:{scope:'node',page:'docs/prototype/settings.html',locator:{type:'id',id:'design'}}}});
  locate();const first=html.scrollTop,located=messages.findLast(value=>value.type==='prototype-review:located');
  assert.equal(first,2120);assert.equal(located.ok,true);assert.equal(located.bounds.y,280,'回传滚后viewport坐标而非旧屏外坐标');
  locate();assert.equal(html.scrollTop,first,'再次定位不能重复减document根偏移');
  root.getBoundingClientRect=()=>({left:20,top:30,x:20,y:30,width:200,height:40});const styles=JSON.stringify(root.style);
  locate();assert.equal(html.scrollTop,first,'视口内sticky/fixed几何不强迫根再居中');assert.equal(JSON.stringify(root.style),styles,'不改节点原定位样式');
  // 实际消息路径先完成业务既有nested定位，再滚根；宿主scrollTo只实现原生位置赋值。
  const target=new Node('BUTTON');target.id='nested-target';target.attrs.id=target.id;target.attrs['data-prototype-review-source']='source-'+'b'.repeat(64);nested.append(target);
  Object.assign(nested,{scrollTop:0,scrollLeft:0,scrollHeight:1200,clientHeight:200,scrollWidth:400,clientWidth:400});html.scrollTop=0;scrollCalls.length=0;
  nested.getBoundingClientRect=()=>({left:0,top:2400-html.scrollTop,width:400,height:200});
  target.getBoundingClientRect=()=>({left:20,top:3000-nested.scrollTop-html.scrollTop,width:100,height:40});
  const oldQuery=document.querySelectorAll;document.querySelectorAll=selector=>selector==='[id]'||selector==='[data-prototype-review-source]'?[root,target]:oldQuery(selector);
  windowEvents.get('message')({source:parent,origin:'http://127.0.0.1:12345',data:{type:'prototype-review:review',version:5,page:'docs/prototype/settings.html',token:'a'.repeat(48),action:'locate',request:'nested-location',target:{scope:'node',page:'docs/prototype/settings.html',locator:{type:'id',id:target.id}}}});
  assert.equal(scrollCalls[0].node,nested);assert.equal(scrollCalls[1].node,html);assert.ok(scrollCalls.every(call=>call.options.behavior==='instant'),'不受业务smooth滚动影响而回传旧geometry');
  assert.equal(nested.scrollTop,520);assert.equal(messages.findLast(value=>value.request==='nested-location').bounds.y,280);
  assert.deepEqual(nested.style,{overflow:'auto',overscrollBehavior:'auto'});
 }
 const gestures=()=>messages.filter(value=>value.type.endsWith(':gesture'));
 const event=patch=>({target:nested,button:0,pointerId:1,clientX:10,clientY:20,deltaX:20,deltaY:100,preventDefault(){this.prevented=true;},stopImmediatePropagation(){this.stopped=true;},...patch});
 for(const position of [0,10000]) {nested.scrollTop=position;const before=gestures().length,e=event();documentEvents.get('wheel')(e);assert.equal(e.prevented,undefined);assert.equal(gestures().length,before,'顶部/底部普通wheel均不发送外相机手势');assert.equal(nested.scrollTop,position,'桥不手动滚动业务内容');}
 documentEvents.get('keydown')(event({target:root,code:'Space',key:' '}));let e=event(),before=gestures().length;documentEvents.get('wheel')(e);assert.equal(e.prevented,undefined);assert.equal(gestures().length,before,'Space+wheel仍为原生滚动');
 for(const modifier of ['ctrlKey','metaKey']) {e=event({[modifier]:true});documentEvents.get('wheel')(e);assert.equal(e.prevented,true);assert.equal(gestures().at(-1).gesture,'zoom');}
 e=event({ctrlKey:true,defaultPrevented:true});before=gestures().length;documentEvents.get('wheel')(e);assert.equal(gestures().length,before,'尊重已由业务消费的组合键事件');
 documentEvents.get('keyup')(event({code:'Space'}));before=gestures().length;documentEvents.get('pointerdown')(event());documentEvents.get('pointermove')(event({clientX:40,clientY:60}));assert.equal(gestures().length,before,'普通稿内拖动不能变成外画布平移');
 for(const space of [false,true]) {
  if(space)documentEvents.get('keydown')(event({target:root,code:'Space',key:' '}));
  e=event({button:space?0:1});documentEvents.get('pointerdown')(e);assert.equal(e.prevented,true);documentEvents.get('pointermove')(event({clientX:35,clientY:50}));assert.equal(gestures().at(-1).gesture,'pan');assert.equal(gestures().at(-1).dx,25);assert.equal(gestures().at(-1).dy,30);
  documentEvents.get('pointercancel')(event());before=gestures().length;documentEvents.get('pointermove')(event({clientX:50,clientY:90}));assert.equal(gestures().length,before,'取消手势后不继续平移');
 }
 windowEvents.get('blur')();before=gestures().length;documentEvents.get('pointerdown')(event());documentEvents.get('pointermove')(event({clientX:80}));assert.equal(gestures().length,before,'失焦后没有残留Space/pan');
}
run(true);run(false);
"""
        result = subprocess.run(["node", "-e", script], input=json.dumps({
            "presentation": (TEMPLATES / "canvas-presentation.js").read_text(encoding="utf-8"),
            "file": (TEMPLATES / "file-page.js").read_text(encoding="utf-8"),
            "review": (TEMPLATES / "page-shell.js").read_text(encoding="utf-8")}),
            text=True, capture_output=True, check=False)
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)

    def test_file_delivery_without_crypto_keeps_untrusted_original(self) -> None:
        """整个crypto不可用时实际执行生产入口：保留原稿src，但不伪造nonce或启用旧评审绑定。"""
        script = r"""
const vm=require('node:vm'),assert=require('node:assert/strict');
const source=JSON.parse(require('node:fs').readFileSync(0,'utf8'));
function node() {return {style:{},dataset:{},hidden:false,attrs:{},textContent:'',children:[],addEventListener(){},append(value){this.children.push(value);},replaceChildren(){this.children=[];},querySelectorAll(){return [];},setAttribute(key,value){this.attrs[key]=value;},removeAttribute(key){delete this.attrs[key];}};}
const elements=new Map(),get=id=>{if(!elements.has(id))elements.set(id,node());return elements.get(id);};
const original='file:///fixture/prototype/settings.html';
const window={addEventListener(){},XYFileDeliveryEntry:{state:{name:'settings.html',originalFileURL:original,catalog:{schema_version:1,directory_sha256:'a'.repeat(64),pages:[{name:'settings.html',path:'docs/prototype/settings.html',label:'Settings',groups:[],viewport:null,binding:{request_id:'one',review_id:'b'.repeat(64),instance:'c'.repeat(48),origin:'http://127.0.0.1:12345'}}]}}},
 PrototypeCanvasPresentation:{create(){return {select(){},read:()=>({width:800,height:600}),close(){}};}},
 PrototypeReviewCamera:{create(options){return {fit(){options.write({x:0,y:0,k:1});},zoom(){},close(){}};}}};
const context={window,parent:window,location:{protocol:'file:',href:original,assign(){throw Error('不能跳到旧目录');}},URL,URLSearchParams,TextEncoder,
 document:{getElementById:get,createElement:node,addEventListener(){}},setTimeout(){throw Error('无握手降级不能等待伪ready');},clearTimeout(){}};
(async()=>{
 const fake=window.PrototypeCanvasPresentation;vm.runInNewContext(source.presentation,context);window.PrototypeCanvasPresentation={...window.PrototypeCanvasPresentation,...fake};
 await assert.doesNotReject(vm.runInNewContext(source.file,context));
 assert.equal(get('prototype-preview').src,original,'整个crypto缺失仍必须载入原稿');
 assert.equal(get('prototype-preview').hidden,false);assert.equal(get('prototype-preview').attrs['aria-busy'],'false');
 assert.equal(get('open-review').attrs.href,undefined);assert.equal(get('open-review').attrs['aria-disabled'],'true');
 assert.ok(get('review-status').textContent.includes('位置校验'));
 assert.equal(get('prototype-pages').children.length,1,'不能启用旧目录中的其他页面');
})().catch(error=>{console.error(error);process.exitCode=1;});
"""
        result = subprocess.run(["node", "-e", script], input=json.dumps({"file": (TEMPLATES / "file-delivery.js").read_text(), "presentation": (TEMPLATES / "canvas-presentation.js").read_text()}),
                                text=True, capture_output=True, check=False)
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)

    def test_delivery_navigation_closes_and_returns_to_real_toggle(self) -> None:
        """执行 file/HTTP 的生产监听器：切页和 Esc 都收起同一目录并回焦真实触发 ID。"""
        script = r"""
const vm=require('node:vm'),assert=require('node:assert/strict'),{webcrypto}=require('node:crypto');
const source=JSON.parse(require('node:fs').readFileSync(0,'utf8'));
async function run(file) {
 const elements=new Map(),events=new Map();let focused='',assigned='';
 function node(){return {children:[],style:{},attrs:{},dataset:{},hidden:false,listeners:new Map(),classList:{contains(){return false;}},addEventListener(type,fn){this.listeners.set(type,fn);},append(...items){for(const item of items){item.parentElement=this;this.children.push(item);}},replaceChildren(){this.children=[];},setAttribute(k,v){this.attrs[k]=v;},getAttribute(k){return this.attrs[k];},removeAttribute(k){delete this.attrs[k];},querySelectorAll(){return this.children;},focus(){focused=this.id;},showModal(){},close(){}};}
 const get=id=>{if(!elements.has(id)){const value=node();value.id=id;elements.set(id,value);}return elements.get(id);};
 get('delivery-navigation').hidden=true;get('prototype-preview').attrs.sandbox='allow-scripts';get('prototype-preview').contentWindow={postMessage(){}};
 const pages=['settings','details','orders'].map((name,i)=>({name:name+'.html',path:'docs/prototype/'+name+'.html',label:name,groups:[{label:i===1?'门店':'用户',open:false},{label:'主页面',open:false}]}));
 const original='file:///fixture/prototype/settings.html';
 const digest=await webcrypto.subtle.digest('SHA-256',new TextEncoder().encode(new URL('.',original).href));
 const directory_sha256=Buffer.from(digest).toString('hex'),context={review_id:'a'.repeat(64)};
 const boot={schema_version:5,context,pages};
 const window={addEventListener(){},XYFileDeliveryEntry:{state:{name:'settings.html',originalFileURL:original,catalog:{schema_version:1,directory_sha256,pages}}},
 PrototypeCanvasPresentation:{create:()=>({select(){},read(){},close(){}})},
 PrototypeReviewCamera:{create:options=>({fit(){options.write({x:0,y:0,k:1});},zoom(){},close(){}})},
 PrototypeReviewState:{parseStartup:()=>boot,create:()=>({state:{page:pages[0].path,cameras:{}},setStorageMessage(){}})},
 PrototypeLiveConnection:{create:()=>({context:async()=>({context}),close(){}})},
 PrototypeCanvasHost:{create:options=>({attachViews(){},camera:{fit(){},zoom(){}},navigate:async path=>options.onNavigate(pages.find(page=>page.path===path)),close(){}})}};
 const document={body:{classList:{contains:()=>false}},getElementById:get,createElement:node,
 querySelectorAll:selector=>selector==='script#prototype-review-data'?[{type:'application/json',textContent:'boot'}]:[get('prototype-preview')],
 querySelector:()=>({nextSibling:null}),addEventListener(type,fn){events.set(type,fn);}};
 get('review-workspace').insertBefore=()=>{};
 const location={protocol:file?'file:':'http:',href:original,pathname:'/delivery/settings.html',assign(value){assigned=value;}};
 const runtime={window,parent:window,document,location,crypto:webcrypto,URL,URLSearchParams,TextEncoder,history:{replaceState(){}},setTimeout:()=>1,clearTimeout(){},setInterval:()=>1,clearInterval(){}};
 const fake=window.PrototypeCanvasPresentation;vm.runInNewContext(source.presentation,runtime);window.PrototypeCanvasPresentation={...window.PrototypeCanvasPresentation,...fake};
 await vm.runInNewContext(file?source.file:source.live,runtime);await new Promise(resolve=>setImmediate(resolve));
 const toggle=get('navigation-toggle'),nav=get('delivery-navigation');
 toggle.listeners.get('click')();assert.equal(nav.hidden,false);assert.equal(toggle.attrs['aria-expanded'],'true');
 const event={key:'Escape',preventDefault(){this.prevented=true;}};events.get('keydown')(event);
 assert.equal(nav.hidden,true);assert.equal(toggle.attrs['aria-expanded'],'false');assert.equal(focused,'navigation-toggle');assert.equal(event.prevented,true);
 toggle.listeners.get('click')();const groups=get('prototype-pages').children;assert.equal(groups.length,2);
 assert.equal(groups[0].children[0].textContent,'用户');assert.equal(groups[0].open,true);assert.equal(groups[1].open,false);
 const firstSubgroup=groups[0].children[1];assert.equal(firstSubgroup.children.length,3);assert.equal(firstSubgroup.children[1].attrs['aria-current'],'page');
 const link=groups[1].children[1].children[1];assert.equal(link.dataset.page,'details.html');
 const click={button:0,preventDefault(){this.prevented=true;}};link.listeners.get('click')(click);
 assert.equal(click.prevented,true);assert.equal(nav.hidden,true);assert.equal(toggle.attrs['aria-expanded'],'false');assert.equal(focused,'navigation-toggle');
 if(file)assert.equal(assigned,'file:///fixture/prototype/details.html');else {assert.equal(link.attrs['aria-current'],'page');assert.equal(firstSubgroup.children[1].attrs['aria-current'],undefined);assert.equal(groups[1].open,true);}
}
(async()=>{await run(true);await run(false);})().catch(error=>{console.error(error);process.exitCode=1;});
"""
        result = subprocess.run(["node", "-e", script], input=json.dumps({
            "file": (TEMPLATES / "file-delivery.js").read_text(encoding="utf-8"),
            "presentation": (TEMPLATES / "canvas-presentation.js").read_text(),
            "live": (TEMPLATES / "live-workspace.js").read_text(encoding="utf-8")}),
            text=True, capture_output=True, check=False)
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)

    def test_review_labels_keep_independent_numbers_and_payload(self) -> None:
        """执行真实清单渲染：R/A 文案不同，底层序号、ID 与反馈载荷保持原样。"""
        scenario = r"""
model.select(record('first'));const anchor=model.addAnchor();
model.openEditor(target('first'));message('修订');model.updateDraft({reference_ids:[anchor.id]});model.completeEditor();
const before=JSON.stringify(model.exportPayload());
const nodes=new Map();
function node() {return {children:[],style:{},attrs:{},hidden:false,classList:{toggle(){}},addEventListener(){},append(...values){this.children.push(...values);},replaceChildren(...values){this.children=[...values];},setAttribute(k,v){this.attrs[k]=v;},focus(){},querySelectorAll(){return [];}};}
const get=id=>{if(!nodes.has(id))nodes.set(id,node());return nodes.get(id);};
// 此宿主只覆盖真实视图的文本投影，不替代浏览器的 dialog、布局或通信验收。
const document={getElementById:get,createElement:node,querySelectorAll(){return [];}};
const context={window,document,TextEncoder,TextDecoder,matchMedia:()=>({matches:false,addEventListener(){}}),HTMLDialogElement:{prototype:{closedBy:''}}};
vm.runInNewContext(input.feedback,context);
window.PrototypeFeedback.create({model,send(){},locate(){},verifySources(){},camera:{},announce(){}});
const row=get('rectification-list').children[0],anchorRow=get('anchor-list').children[0];
assert.equal(row.id,'item-'+model.state.items[0].id);
assert.equal(row.children[0].children[0].textContent,'R01');
assert.equal(anchorRow.children[0].children[0].textContent,'A01');
model.setCamera(boot.pages[0].path,{x:0,y:0,k:1});
let receive;window.addEventListener=(type,handler)=>{if(type==='message')receive=handler;};
window.PrototypeCanvasPresentation={create:()=>({select(){},read:()=>({width:800,height:600}),matchColorScheme(){},close(){}})};
let cameraIO;
window.PrototypeReviewCamera={create:options=>{cameraIO=options;return {applyCam(){},fit(){},restore(){},close(){}};}};
get('prototype-preview').contentWindow={postMessage(){}};
Object.assign(context,{URL,location:{origin:'http://127.0.0.1:12345'},setTimeout:()=>1,clearTimeout(){}});
vm.runInNewContext(input.host,context);
const host=window.PrototypeCanvasHost.create({boot,model,reviewing:true,announce(){}});
const pending=host.navigate(boot.pages[0].path);
const emit=data=>receive({source:get('prototype-preview').contentWindow,origin:'null',data:{version:5,page:boot.pages[0].path,token:'',...data}});
emit({type:'prototype-review:ready'});emit({type:'prototype-review:catalog',nodes:[record('first'),record('second')]});
const item=model.state.items[0];
emit({type:'prototype-review:geometry',marks:[{kind:'item',id:item.id,number:item.number,offset:0,operation:item.operation,bounds:{x:1,y:1,w:20,h:20}},{kind:'anchor',id:anchor.id,number:anchor.number,offset:1,bounds:{x:1,y:1,w:20,h:20}}]});
const markers=get('canvas-viewport').children[0].children.filter(child=>child.className?.startsWith('live-marker'));
assert.deepEqual(markers.map(child=>child.textContent),['R01','A01']);
// 短视口临时相机只推动当前图层；稀疏标记及导出仍使用已存在的整改记录和旧相机合同。
const storedCamera=model.state.cameras[boot.pages[0].path];
cameraIO.write({x:5,y:12,k:.04});
assert.equal(cameraIO.read().k,.04);assert.equal(model.state.cameras[boot.pages[0].path],storedCamera);
cameraIO.onApply(cameraIO.read());
assert.equal(get('canvas-viewport').children[0].children.find(child=>child.textContent==='R01').style.left,'5.04px');
assert.equal(JSON.stringify(model.exportPayload()),before);
"""
        result = subprocess.run(["node", "-e", STATE_SETUP + scenario],
                                input=json.dumps({"source": (TEMPLATES / "review-state.js").read_text(encoding="utf-8"),
                                                  "feedback": (TEMPLATES / "feedback.js").read_text(encoding="utf-8"),
                                                  "host": (TEMPLATES / "canvas-host.js").read_text(encoding="utf-8")}),
                                text=True, capture_output=True, check=False)
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)

    def test_production_scripts_compile(self) -> None:
        for name in ("workspace.js", "feedback.js", "page-shell.js", "review-state.js", "review-camera.js", "live-connection.js", "canvas-host.js", "live-workspace.js", "file-entry.js", "file-delivery.js", "file-page.js", "canvas-presentation.js"):
            with self.subTest(name=name):
                result = subprocess.run(["node", "--check", str(TEMPLATES / name)], text=True, capture_output=True, check=False)
                self.assertEqual(0, result.returncode, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
