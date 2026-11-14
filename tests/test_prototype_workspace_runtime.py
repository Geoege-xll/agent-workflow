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
const boot = {schema_version:3, context: {schema_version:2, request_id:'review-302', project_id:'1'.repeat(64), adapter:'project.yaml', adapter_sha256:'2'.repeat(64), prototype_root:'docs/prototype', plan_source:'docs/plans/review.md', plan_sha256:'a'.repeat(64), navigation_sha256:'3'.repeat(64), tool:{version:'3.0.2',payload_sha256:'4'.repeat(64)},review_id:'5'.repeat(64),requirements:[{id:'REQ-007',label:'业务整改'}],pages:[{path:'docs/prototype/settings.html',dependency_fingerprint:'b'.repeat(64)},{path:'docs/prototype/reports.html',dependency_fingerprint:'c'.repeat(64)}]},pages:['settings','reports'].map(name=>({name:name+'.html',path:'docs/prototype/'+name+'.html',url:'project/docs/prototype/'+name+'.html',label:name,groups:[]}))};
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
assert.equal(window.PrototypeReviewState.parseStartup(encode(boot).replace('"schema_version":3','"schema_version":3,"schema_version":3')).context,null);
assert.equal(window.PrototypeReviewState.parseStartup(encode({...boot,pages:[{...boot.pages[0],url:'../escape.html'},boot.pages[1]]})).context,null);
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
const payload=model.exportPayload(); assert.equal(payload.schema_version,3); assert.equal(payload.context.schema_version,2);
assert.deepEqual(Object.keys(payload).sort(),['anchors','context','items','schema_version']);
assert.ok(!JSON.stringify(payload).includes('severity')); assert.ok(!JSON.stringify(payload).includes('drafts'));
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
for(let i=0;i<10;i++) { model.openEditor({scope:'global'}); message('汉'.repeat(4000)); model.completeEditor(); }
const before=JSON.stringify(model.state), storedBefore=JSON.stringify([...store.entries()]);
assert.ok(new TextEncoder().encode(JSON.stringify(model.exportPayload())).length<1048576);
assert.throws(()=>format(model.exportPayload()),/交还全文.*1MiB.*缩短正文或撤回部分整改/);
assert.equal(JSON.stringify(model.state),before);
assert.equal(JSON.stringify([...store.entries()]),storedBefore);
model.openEditor({scope:'global'}); message('保留未完成交还草稿');
const draftBefore=JSON.stringify(model.state), draftStoredBefore=JSON.stringify([...store.entries()]);
assert.throws(()=>model.completeAll(format),/交还全文.*1MiB/);
assert.equal(JSON.stringify(model.state),draftBefore);
assert.equal(JSON.stringify([...store.entries()]),draftStoredBefore);
assert.equal(model.activeDrafts().length,1);
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
        self.assertEqual(3, parsed["schema_version"])
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
"""
        result = subprocess.run(["node", "-e", script], input=json.dumps(source), text=True, capture_output=True, check=False)
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)

    def test_production_scripts_compile(self) -> None:
        for name in ("workspace.js", "feedback.js", "page-shell.js", "review-state.js", "review-camera.js"):
            with self.subTest(name=name):
                result = subprocess.run(["node", "--check", str(TEMPLATES / name)], text=True, capture_output=True, check=False)
                self.assertEqual(0, result.returncode, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
