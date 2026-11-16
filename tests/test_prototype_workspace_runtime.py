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
vm.runInNewContext(JSON.parse(require('node:fs').readFileSync(0,'utf8')), {window});
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
"""
        result = subprocess.run(["node", "-e", script], input=json.dumps(source), text=True, capture_output=True, check=False)
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)

    def test_presentation_keeps_frozen_positive_viewport_bounds(self) -> None:
        """尺寸合同接受最小正数与最大16384，拒绝零、负数、无穷与越界；不默认为桌面尺寸。"""
        script = r"""
const vm=require('node:vm'),assert=require('node:assert/strict'),window={};
vm.runInNewContext(JSON.parse(require('node:fs').readFileSync(0,'utf8')),{window});
const valid=window.PrototypeCanvasPresentation.validSize;
for(const size of [{width:1,height:1},{width:390,height:844},{width:16384,height:16384}]) assert.equal(valid(size),true);
for(const size of [{width:0,height:844},{width:-1,height:844},{width:16385,height:844},{width:Infinity,height:844},{width:'390',height:844}]) assert.equal(valid(size),false);
"""
        result = subprocess.run(["node", "-e", script], input=json.dumps((TEMPLATES / "canvas-presentation.js").read_text(encoding="utf-8")),
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
const window={addEventListener(){},XYFileDeliveryEntry:{state:{name:'settings.html',originalFileURL:original,catalog:{schema_version:1,directory_sha256:'a'.repeat(64),pages:[{name:'settings.html',path:'docs/prototype/settings.html',label:'Settings',viewport:null,binding:{request_id:'one',review_id:'b'.repeat(64),instance:'c'.repeat(48),origin:'http://127.0.0.1:12345'}}]}}},
 PrototypeCanvasPresentation:{create(){return {select(){},read:()=>({width:800,height:600}),close(){}};}},
 PrototypeReviewCamera:{create(options){return {fit(){options.write({x:0,y:0,k:1});},zoom(){},close(){}};}}};
const context={window,parent:window,location:{protocol:'file:',href:original,assign(){throw Error('不能跳到旧目录');}},URL,URLSearchParams,TextEncoder,
 document:{getElementById:get,createElement:node},setTimeout(){throw Error('无握手降级不能等待伪ready');},clearTimeout(){}};
(async()=>{
 await assert.doesNotReject(vm.runInNewContext(source,context));
 assert.equal(get('prototype-preview').src,original,'整个crypto缺失仍必须载入原稿');
 assert.equal(get('prototype-preview').hidden,false);assert.equal(get('prototype-preview').attrs['aria-busy'],'false');
 assert.equal(get('open-review').attrs.href,undefined);assert.equal(get('open-review').attrs['aria-disabled'],'true');
 assert.ok(get('review-status').textContent.includes('位置校验'));
 assert.equal(get('prototype-pages').children.length,1,'不能启用旧目录中的其他页面');
})().catch(error=>{console.error(error);process.exitCode=1;});
"""
        result = subprocess.run(["node", "-e", script], input=json.dumps((TEMPLATES / "file-delivery.js").read_text(encoding="utf-8")),
                                text=True, capture_output=True, check=False)
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)

    def test_production_scripts_compile(self) -> None:
        for name in ("workspace.js", "feedback.js", "page-shell.js", "review-state.js", "review-camera.js", "live-connection.js", "canvas-host.js", "live-workspace.js", "file-entry.js", "file-delivery.js", "file-page.js", "canvas-presentation.js"):
            with self.subTest(name=name):
                result = subprocess.run(["node", "--check", str(TEMPLATES / name)], text=True, capture_output=True, check=False)
                self.assertEqual(0, result.returncode, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
