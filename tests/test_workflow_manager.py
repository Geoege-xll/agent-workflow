"""只使用隔离目录验证管理器合同，不读取真实账户或修改示例项目。"""

from __future__ import annotations

import hashlib
import io
from contextlib import redirect_stderr, redirect_stdout
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import pty
import re
import select
import signal
import shlex
import shutil
import struct
import subprocess
import sys
import tempfile
import termios
import time
from threading import Event
import tomllib
import uuid
import unittest
from unittest.mock import patch

from lib import role_models
from lib.install import install_workflow
from lib.install.install_process import SetupRunner, SetupRunError
from manager.catalog import Catalog, Model, discover
from manager.codex_models import NativeModel, NativeModels
from manager.claude_execution import effective_role
from manager.capabilities import diagnose
from manager.cli import main as cli_main
from manager import service, project_service, state_files
from manager.install_cli import install as install_cli
from manager.tui import App, cell_width, clip

PACK=Path(__file__).resolve().parents[1]


def codex_agent(model=None,effort="high"):
    payload='name = "xy-backend"\ndescription = "fixture"\n'
    if model:payload+=f'model = "{model}"\n'
    if effort:payload+=f'model_reasoning_effort = "{effort}"\n'
    payload+='sandbox_mode = "workspace-write"\nnickname_candidates = ["Backend"]\n\ndeveloper_instructions = "fixture instructions"\n'
    return f'# agent-workflow-pack:managed-codex-agent:v1 sha256={hashlib.sha256(payload.encode()).hexdigest()}\n{payload}'.encode()


def deep_json_source(home: Path, host: str) -> bool:
    """写入真实深层 JSON；探测当前解析器，不用 mock 或全局递归上限制造异常。"""
    text='{"private_payload":"DEEP-SOURCE-SECRET","padding":'+'['*2000+'0'+']'*2000+'}'
    directory=home/('.codex' if host == 'codex' else '.claude');directory.mkdir(parents=True,exist_ok=True)
    if host == 'codex':
        (directory/'config.toml').write_text('model_catalog_json="models.json"\n',encoding='utf-8')
    (directory/('models.json' if host == 'codex' else 'settings.json')).write_text(text,encoding='utf-8')
    try:json.loads(text)
    except RecursionError:return True
    # Python 3.14 的 JSON 解析器可接受同一输入；3.11 必须确实命中被修复的异常路径。
    if sys.version_info[:2] == (3,11):raise AssertionError('真实 Python 3.11 未触发深 JSON 回归所需的 RecursionError')
    return False


def select_fixture_current(state, binding):
    """只初始化既有最小投影夹具的中央控制前提，不生成全局原生资源替代local测试。"""
    from manager import runtime_policy
    from manager.runtime_state import read_state, write_control
    from lib.central.runtime_project import Tree, json_bytes
    with runtime_policy.coordination(state), Tree(state) as tree:
        write_control(tree,runtime_policy.CURRENT,json_bytes({"schema_version":1,"runtime_binding":binding,
                      "previous_binding":None,"generation":uuid.uuid4().hex}),expected=read_state(state,runtime_policy.CURRENT))


class TemporaryProject(unittest.TestCase):
    central_fixture = False

    @classmethod
    def setUpClass(cls):
        if cls.central_fixture:
            from lib import runtime_store
            cls.central_temp = tempfile.TemporaryDirectory(prefix="model-current-central-")
            root = Path(cls.central_temp.name).resolve()
            source = CentralCliIntegrationTest.create_source(root)
            cls.central_state = root / "state"
            cls.central_core = runtime_store.import_core(source, cls.central_state)
            select_fixture_current(cls.central_state,cls.central_core.binding())

    @classmethod
    def tearDownClass(cls):
        if cls.central_fixture:
            cls.central_temp.cleanup()

    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix="workflow-manager-test-")
        self.root=Path(self.temp.name).resolve();self.project=self.root/"项目 A";self.project.mkdir()
        self.state=self.root/"state"
        self.write(".agent-workflow/project.yaml","project_name: test\nworkspace: auto\n")
        self.write(".agent-workflow/lib/role_models.py","# fixture\n")
        self.write(".codex/agents/xy-backend.toml",codex_agent())
        if self.central_fixture:
            from lib.central.runtime_project import Node, project_key, json_bytes
            self.state = self.central_state
            from lib.central.runtime_project import Resources, initial_config, role_resource
            self.write("pyproject.toml", '[project]\nname="fixture"\nversion="0.1.0"\n')
            resources = Resources(self.central_core.root, json_bytes(self.central_core.binding()),
                                  self.central_core.label, self.central_core)
            self.write(".agent-workflow/project.yaml", initial_config(resources, self.project).replace(b"  mode: assist", b"  mode: off"))
            role = self.project / ".codex/agents/xy-backend.toml"
            info = self.project.stat()
            # 单元事务使用当前机器记录合同及唯一共享最小核心；不重建旧 manifest。
            record = {"schema_version": 1, "project_root": str(self.project),
                      "project_identity": [info.st_dev, info.st_ino], "runtime_binding": self.central_core.binding(),
                      "enabled": True, "hosts": ["codex"], "previous_binding": None,
                      "used_bindings": [self.central_core.binding()], "retained_nodes": [], "generation": "1" * 32,
                      "managed": {".codex/agents/xy-backend.toml": {"purpose": "role", "baseline": Node().value(),
                                   "expected": Node("file", role.read_bytes(), 0o644).value()}}}
            # 健康投影要求完整profile角色；backend继续保留人工模型补丁前像，
            # QA/UIUX由固定core编译为真实完整local，不能靠缺角色暗中借用global。
            for selected_role in ("xy-qa", "xy-uiux"):
                relative = f".codex/agents/{selected_role}.toml"
                rendered = role_resource(resources, (self.project / ".agent-workflow/project.yaml").read_bytes(),
                                         "codex", selected_role, self.central_core.binding())
                self.write(relative, rendered)
                record["managed"][relative] = {"purpose": "role", "baseline": Node().value(),
                                                "expected": Node("file", rendered, 0o644).value()}
            target = self.state / "bindings" / (project_key(self.project) + ".json")
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(json_bytes(record)); target.chmod(0o600)
        self.catalog=Catalog("codex",[Model("inherit","继承","fixture",("high","max")),Model("local-model","本地模型","fixture",("high","max"))])
        self.value={"model":"local-model","effort":"max"}

    def tearDown(self):self.temp.cleanup()

    def write(self,relative,value):
        path=self.project/relative;path.parent.mkdir(parents=True,exist_ok=True)
        path.write_bytes(value if isinstance(value,bytes) else value.encode());return path

    def prepare(self):return service.prepare(self.project,"codex",{"xy-backend":self.value},self.catalog,state=self.state)


class ModelContractTest(unittest.TestCase):
    def test_unknown_capabilities_allow_standard_host_effort_without_claiming_support(self):
        for host,levels in (('codex',('none','minimal','low','medium','high','xhigh','max')),
                            ('claude',('low','medium','high','xhigh','max'))):
            catalog=Catalog(host,[Model('inherit','继承','fixture')])
            for effort in levels:
                with self.subTest(host=host,effort=effort):
                    self.assertEqual(service.validate_selection(host,{'model':'inherit','effort':effort},catalog)['effort'],effort)
            # 可写入宿主标准值不等于模型能力证据，且不能放开 ultra 的自动委派语义。
            self.assertEqual(catalog.as_dict()['models'][0]['efforts'],())
            with self.assertRaises(ValueError):service.validate_selection(host,{'model':'inherit','effort':'ultra'},catalog)

    def test_config_update_preserves_unrelated_text_and_crlf(self):
        original="project_name: test\r\n# 保留原配置\r\nworkspace:\r\n  discovery: auto\r\n"
        updated=role_models.update(original,{"codex":{"xy-backend":{"model":"custom/model","effort":"max"}}})
        self.assertTrue(updated.startswith(original));self.assertNotIn("\n",updated.replace("\r\n",""))
        second=role_models.update(updated,role_models.parse(updated));self.assertEqual(updated,second)

    def test_model_block_replacement_keeps_following_sections(self):
        original='role_models:\n  codex:\n    xy-qa: {"model":"inherit"}\n\ndocs:\n  project: docs/PROJECT.md\n'
        updated=role_models.update(original,{"antigravity":{"xy-qa":{"model":"pro"}}})
        self.assertTrue(updated.endswith('docs:\n  project: docs/PROJECT.md\n'))
        self.assertEqual(role_models.parse(updated)["antigravity"]["xy-qa"]["model"],"pro")

    def test_last_line_without_newline_is_replaced_once(self):
        original='project_name: x\nrole_models:\n  codex:\n    xy-qa: {"model":"old"}'
        result=role_models.update(original,{'codex':{'xy-qa':{'model':'new'}}})
        self.assertEqual(role_models.parse(result)['codex']['xy-qa']['model'],'new')
        self.assertEqual(result.count('xy-qa:'),1)

    def test_invalid_and_duplicate_fields_are_rejected(self):
        for text in ['role_models:\n  other:\n','role_models:\n  codex:\n    xy-qa: {"model":"a","model":"b"}\n','role_models: []\n']:
            with self.subTest(text=text),self.assertRaises(ValueError):role_models.parse(text)
        for host,value in [('codex',{'effort':'ultra'}),('antigravity',{'model':'gpt-x'}),('claude',{'model':'oops\npermissionMode: bypassPermissions'})]:
            with self.subTest(host=host),self.assertRaises(ValueError):role_models.validate(host,value)

    def test_top_level_comments_inside_model_block_keep_one_host(self):
        original='role_models:\n  codex:\n    xy-backend: {"model":"inherit"}\n# Claude 模型\n  claude:\n    xy-qa: {"model":"opus"}\n# 外部说明\ndocs:\n  project: docs/PROJECT.md\n'
        values=role_models.parse(original);result=role_models.update(original,values)
        self.assertEqual(role_models.parse(result),values)
        self.assertEqual(result.count('  claude:'),1);self.assertIn('# Claude 模型',result)
        self.assertTrue(result.endswith('# 外部说明\ndocs:\n  project: docs/PROJECT.md\n'))

    def test_codex_patch_preserves_non_model_fields_and_hash(self):
        original=codex_agent();result=role_models.patch_artifact(original,'codex',{'model':'local-model','effort':'max'})
        before=tomllib.loads(original.decode());after=tomllib.loads(result.decode())
        for key in ('name','description','developer_instructions','sandbox_mode','nickname_candidates'):self.assertEqual(before[key],after[key])
        self.assertEqual(after['model'],'local-model');self.assertEqual(after['model_reasoning_effort'],'max')
        header,payload=result.split(b'\n',1);self.assertTrue(header.endswith(hashlib.sha256(payload).hexdigest().encode()))
        inherited=role_models.patch_artifact(result,'codex',{'model':'inherit','effort':'inherit'})
        self.assertNotIn('model_reasoning_effort',tomllib.loads(inherited.decode()));self.assertNotIn('model',tomllib.loads(inherited.decode()))

    def test_markdown_patch_has_no_duplicate_effort_and_preserves_body(self):
        original=b'---\nname: xy-backend\nmodel: inherit\neffort: high\ntools: Read\n---\n<!-- agent-workflow-pack:managed-agent -->\nBODY\n'
        result=role_models.patch_artifact(original,'claude',{'model':'custom/model','effort':'max'})
        self.assertEqual(result.count(b'\neffort:'),1)
        self.assertTrue(result.endswith(b'<!-- agent-workflow-pack:managed-agent -->\nBODY\n'))
        self.assertIn(b'tools: Read',result)


class CatalogTest(unittest.TestCase):
    def setUp(self):self.temp=tempfile.TemporaryDirectory();self.home=Path(self.temp.name).resolve()
    def tearDown(self):self.temp.cleanup()
    def write(self,name,value):
        path=self.home/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_text(value if isinstance(value,str) else json.dumps(value));return path

    def native_fixture(self, pages, mode="ok", cache_identity=None):
        """用真实 stdio 子进程提供可控宿主协议；环境只指向本测试目录，不借用真实账户。"""
        fixture=self.write('native-fixture.json',{'pages':pages,'mode':mode,'cache_identity':cache_identity})
        program=self.write('bin/codex', '#!'+sys.executable+'\n'+'''import json, os, signal, subprocess, sys, time
from pathlib import Path
root=Path(os.environ["HOME"])
fixture=json.loads(Path(os.environ["NATIVE_FIXTURE"]).read_text())
(root/"native-pid").write_text(str(os.getpid()))
page=0
for line in sys.stdin:
    request=json.loads(line)
    with (root/"native-calls").open("a") as log:
        log.write(json.dumps(request)+"\\n")
    method=request["method"]
    if method == "initialized": continue
    mode=fixture["mode"]
    if mode == "exit":
        sys.stderr.write("NATIVE-PRIVATE-SECRET");sys.stderr.flush();raise SystemExit(3)
    if mode == "timeout":
        signal.signal(signal.SIGTERM,signal.SIG_IGN)
        child="import os,signal,sys,time;from pathlib import Path;signal.signal(signal.SIGTERM,lambda *_:(Path(os.environ['HOME']+'/native-child-ended').write_text(str(os.getpid())),sys.exit(0)));Path(os.environ['HOME']+'/native-child').write_text(str(os.getpid()));time.sleep(30)"
        subprocess.Popen([sys.executable,"-c",child])
        while not (root/"native-child").exists(): time.sleep(.005)
        time.sleep(30)
    if mode == "flood":
        sys.stderr.buffer.write(b"NATIVE-PRIVATE-SECRET"+b"x"*(4*1024*1024+1));sys.stderr.flush();time.sleep(30)
    if mode == "json": print("invalid NATIVE-PRIVATE-SECRET",flush=True);continue
    if method == "initialize": result={"userAgent":"fixture"}
    else:
        if method != "model/list": raise SystemExit(4)
        result=fixture["pages"][min(page,len(fixture["pages"])-1)];page+=1
        if fixture["cache_identity"] is not None:
            target=Path(os.environ["CODEX_HOME"])/"models_cache.json";target.parent.mkdir(parents=True,exist_ok=True)
            identity=fixture["cache_identity"]
            if mode == "scope": identity += ":" + str(Path.cwd())
            target.write_text(json.dumps({"identity":identity,"models":[{"slug":"stale-cache-only"}]}))
    reply={"id": "wrong" if mode == "id" else request["id"],"result":result}
    if mode == "error": reply={"id":request["id"],"error":{"message":"NATIVE-PRIVATE-SECRET"}}
    print(json.dumps(reply),flush=True)
''')
        program.chmod(0o700)
        return {'HOME':str(self.home),'CODEX_HOME':str(self.home/'.codex'),
                'PATH':str(program.parent),'NATIVE_FIXTURE':str(fixture)}

    def native_row(self, model, **extra):
        return {'id':'opaque-'+model,'model':model,'displayName':'名称 '+model,'hidden':False,
                'supportedReasoningEfforts':[{'reasoningEffort':level} for level in ('high','max','ultra')],
                'defaultReasoningEffort':'high',**extra}

    def test_codex_native_pages_map_model_values_visibility_and_efforts(self):
        self.write('.codex/config.toml','model="dynamic-a"\n')
        self.write('.codex/models_cache.json','broken default cache')
        pages=[{'data':[self.native_row('dynamic-a'),self.native_row('hidden',hidden=True)],'nextCursor':'second'},
               {'data':[self.native_row('dynamic-b',displayName='动态'+chr(27)+'模型')],'nextCursor':None}]
        env=self.native_fixture(pages)
        catalog=discover('codex',self.home,self.home,env)
        self.assertEqual([row.id for row in catalog.models],['inherit','dynamic-a','dynamic-b'])
        self.assertEqual(catalog.models[0].efforts,('high','max'))
        self.assertEqual(catalog.models[2].label,'动态模型')
        calls=[json.loads(line) for line in (self.home/'native-calls').read_text().splitlines()]
        self.assertEqual([row['method'] for row in calls],['initialize','initialized','model/list','model/list'])
        self.assertEqual([row['params']['cursor'] for row in calls[2:]],[None,'second'])
        self.assertTrue(all(row['params']['includeHidden'] is False for row in calls[2:]))
        self.assertEqual(service.validate_selection('codex',{'model':'dynamic-b','effort':'max'},catalog)['model'],'dynamic-b')
        with self.assertRaises(ValueError):service.validate_selection('codex',{'model':'dynamic-b','effort':'ultra'},catalog)
        # CLI 是同一 discover 的直接消费者，输出必须保留真正可写的 model，而非目录 id。
        output=io.StringIO()
        with patch.dict(os.environ,env,clear=True),redirect_stdout(output):
            self.assertEqual(cli_main(['models','--platform','codex']),0)
        self.assertEqual([row['id'] for row in json.loads(output.getvalue())['models']],['inherit','dynamic-a','dynamic-b'])

    def test_codex_native_protocol_failures_reap_process_and_keep_safe_fallback(self):
        self.write('.codex/config.toml','model="current"\n')
        self.write('.codex/models_cache.json',{'identity':'old-provider','models':[{'slug':'stale-only'}]})
        for mode,pages in (('exit',[]),('id',[]),('json',[]),('error',[]),('flood',[]),
                           ('ok',[{'data':[self.native_row('partial')],'nextCursor':'repeat'}]),
                           ('ok',[{'data':[{'model':'invalid'}],'nextCursor':None}])):
            with self.subTest(mode=mode,pages=pages):
                env=self.native_fixture(pages,mode)
                processes=[];popen=subprocess.Popen
                def spawn(*args,**kwargs):
                    process=popen(*args,**kwargs);processes.append(process);return process
                with patch('manager.codex_models.subprocess.Popen',side_effect=spawn):
                    catalog=discover('codex',self.home,env=env)
                self.assertEqual([row.id for row in catalog.models],['inherit','current'])
                output=json.dumps(catalog.as_dict(),ensure_ascii=False)
                self.assertIn('原生目录获取失败',output);self.assertNotIn('NATIVE-PRIVATE-SECRET',output)
                self.assertTrue(processes);self.assertTrue(all(row.returncode is not None for row in processes))
        # 启动失败也由目录边界投影，不能把可执行文件错误正文当模型候选或秘密诊断。
        env=self.native_fixture([],"ok")
        (self.home/'bin/codex').write_text('#!/nonexistent-native-interpreter\n')
        catalog=discover('codex',self.home,env=env)
        self.assertEqual([row.id for row in catalog.models],['inherit','current'])
        self.assertTrue(any('无法启动' in note for note in catalog.notes))
        diagnostic=' '.join(catalog.notes)
        self.assertIn('阶段：spawn',diagnostic);self.assertIn('异常：FileNotFoundError',diagnostic)
        self.assertIn('errno：2',diagnostic)

    def test_codex_native_timeout_reaps_owned_process_group(self):
        env=self.native_fixture([],"timeout")
        start=time.monotonic()
        processes=[];popen=subprocess.Popen
        def spawn(*args,**kwargs):
            process=popen(*args,**kwargs);processes.append(process);return process
        with patch('manager.codex_models.TIMEOUT_SECONDS',.35),patch('manager.codex_models.subprocess.Popen',side_effect=spawn):
            catalog=discover('codex',self.home,env=env)
        self.assertLess(time.monotonic()-start,3)
        self.assertTrue(any('超时' in note for note in catalog.notes))
        # 父进程忽略 TERM，必须已被 KILL 并 wait；后代通过退出处理确认收到组取消。
        self.assertEqual([process.returncode for process in processes],[-signal.SIGKILL])
        self.assertEqual((self.home/'native-child').read_text(),(self.home/'native-child-ended').read_text())

    def test_codex_native_result_is_discarded_when_stable_sources_change_during_query(self):
        # 直接控制查询返回前的真实来源写入，覆盖身份、有效提供方和可执行文件这三类竞态。
        # query 只用内存替身；auth 正文的读取仍被明确禁止，不触碰真实宿主或账户。
        for changed in ('auth','provider','binary'):
            with self.subTest(changed=changed):
                self.write('.codex/config.toml','model="current"\n')
                auth=self.write('.codex/auth.json','AUTH-PRIVATE-SECRET')
                env=self.native_fixture([])
                read_text=Path.read_text
                def safe_read(path,*args,**kwargs):
                    if path == auth:raise AssertionError('禁止读取 auth 正文')
                    return read_text(path,*args,**kwargs)
                def query_before_source_change(*args):
                    if changed == 'auth':auth.write_text('NEW-AUTH-PRIVATE-SECRET')
                    elif changed == 'provider':self.write('.codex/config.toml','model="new-current"\nmodel_provider="new-provider"\n')
                    else:self.write('bin/codex','changed executable bytes')
                    return NativeModels((NativeModel('old-account-visible','旧身份模型',('high',),'high'),))
                with patch.object(Path,'read_text',safe_read):
                    with patch('manager.catalog.codex_models.query',side_effect=query_before_source_change) as native:
                        first=discover('codex',self.home,self.home,env)
                    self.assertEqual(native.call_count,1)
                    self.assertEqual([row.id for row in first.models],['inherit'])
                    self.assertTrue(any('查询期间' in note and '已丢弃' in note for note in first.notes))
                    with patch('manager.catalog.codex_models.query',side_effect=AssertionError('拒绝后不得自动重查')):
                        recheck=discover('codex',self.home,self.home,env,_snapshot=first)
                    self.assertNotIn('old-account-visible',[row.id for row in recheck.models])
                    self.assertNotEqual(first.stamp,recheck.stamp)
                    self.assertNotIn('PRIVATE-SECRET',json.dumps(first.as_dict()))

    def test_codex_native_snapshot_rechecks_sources_without_requery_or_auth_read(self):
        self.write('.codex/config.toml','model="dynamic"\n')
        auth=self.write('.codex/auth.json','AUTH-PRIVATE-SECRET')
        self.write('.codex/models_cache.json',{'identity':'before-query'})
        env=self.native_fixture([{'data':[self.native_row('dynamic')],'nextCursor':None}],cache_identity='after-query')
        read_text=Path.read_text
        def safe_read(path,*args,**kwargs):
            if path == auth:raise AssertionError('禁止读取 auth 正文')
            return read_text(path,*args,**kwargs)
        with patch.object(Path,'read_text',safe_read):
            first=discover('codex',self.home,self.home,env)
            self.assertEqual([row.id for row in first.models],['inherit','dynamic'])
            with patch('manager.codex_models.query',side_effect=AssertionError('来源校验不得启动原生进程')):
                same=discover('codex',self.home,self.home,env,_snapshot=first)
                self.assertEqual(first.stamp,same.stamp)
                self.write('.codex/models_cache.json',{'identity':'after-query','models':[{'slug':'unrelated'}]})
                self.assertEqual(first.stamp,discover('codex',self.home,self.home,env,_snapshot=first).stamp)
                with patch.dict(os.environ,env,clear=True):
                    service.ensure_source(first,self.home)
                    auth.write_text('NEW-AUTH-PRIVATE-SECRET')
                    with self.assertRaisesRegex(ValueError,'来源'):service.ensure_source(first,self.home)
                changed=discover('codex',self.home,self.home,env,_snapshot=first)
                self.assertNotEqual(first.stamp,changed.stamp)
                self.assertTrue(all(not row.efforts for row in changed.models))
                self.assertNotIn('PRIVATE-SECRET',json.dumps(changed.as_dict()))

    def test_tui_failed_and_invalidated_native_catalog_recovers_only_on_editor_entry(self):
        # 真实来源读取和 App 状态机保持生产路径；只替换跨进程目录返回，
        # 准确区分可恢复失败、身份失效及已有草稿来源，不借用真实账户。
        self.write('.codex/config.toml','model="current"\n')
        auth=self.write('.codex/auth.json','private-fixture-auth')
        env={'HOME':str(self.home),'CODEX_HOME':str(self.home/'.codex'),'PATH':''}
        native=NativeModels((NativeModel('current','当前',('high','max'),'high'),
                             NativeModel('dynamic','动态',('high','max'),'high')))
        outcome={'result':NativeModels(failure='原生 model/list 查询超时')}
        def source(host,*,project=None,_snapshot=None):
            return discover(host,self.home,project,env,_snapshot=_snapshot)
        with patch('manager.tui.project_service.projects',return_value=[self.home]), \
             patch('manager.tui.service.roles',return_value=['xy-backend']), \
             patch('manager.tui.service.role_settings',return_value={'model':'inherit','effort':'high'}), \
             patch.dict(os.environ,env,clear=True), \
             patch('manager.tui.discover',side_effect=source), \
             patch('manager.service.discover',side_effect=source), \
             patch('manager.model_preferences.discover',side_effect=source), \
             patch('manager.catalog.codex_models.query',side_effect=lambda *_:outcome['result']) as query:
            app=App(self.home/'state',self.home/'scan',self.home)
            self.assertEqual(app.catalog()._status,'stale');query.assert_not_called()
            app.open_model();self.assertEqual(app.catalog()._status,'failed')
            self.assertEqual(query.call_count,1)
            app.options();app.options();self.assertEqual(query.call_count,1)
            app.dispatch('esc');outcome['result']=native
            app.act('host','2');app.act('host','1');app.open_effort()
            self.assertEqual(app.catalog()._status,'ready');self.assertEqual(query.call_count,2)
            self.assertEqual([row.id for row in app.catalog().models],['inherit','current','dynamic'])
            self.assertNotIn('_status',app.catalog().as_dict())
            app.index=next(i for i,(_,value) in enumerate(app.options()) if value == 'max')
            app.confirm();key=app.scope();stamp=app.source_stamps[key];baseline=dict(app.expected[key])
            other=(str(self.home),'claude','xy-qa');app.drafts[other]={'model':'inherit','effort':'high'}
            selected_catalog=app.catalog();auth.write_text('new-private-fixture-auth')
            app.dispatch('s')
            # 失效守卫只读拒绝；已发布目录仍是原查询结果，不能改写其状态或来源。
            self.assertIn('来源',app.toast);self.assertIs(app.catalog(),selected_catalog)
            self.assertEqual(query.call_count,2)
            with self.assertRaisesRegex(ValueError,'来源'):service.ensure_source(selected_catalog,self.home)
            self.assertEqual(query.call_count,2)
            app.act('host','2');app.act('host','1');app.open_model()
            self.assertEqual(query.call_count,3);self.assertEqual(app.catalog()._status,'ready')
            self.assertEqual(app.source_stamps[key],stamp);self.assertEqual(app.expected[key],baseline)
            app.dispatch('esc');app.dispatch('s')
            self.assertIsNone(app.modal);self.assertIn('来源',app.toast)
            self.assertIn(other,app.drafts)
            # 用户重新确认选择后才更新该草稿来源；稳定成功快照不再次查询。
            app.open_effort();app.confirm();self.assertEqual(query.call_count,3)
            self.assertNotEqual(app.source_stamps[key],stamp)
            self.assertEqual(app.expected[key],baseline);self.assertIn(other,app.drafts)

    def test_codex_explicit_catalog_precedes_native_and_provider_changes_reject_snapshot(self):
        env=self.native_fixture([{'data':[self.native_row('native-only')],'nextCursor':None}])
        with patch('manager.codex_models.query',side_effect=AssertionError('显式目录不得被 native 合并')):
            self.write('.codex/config.toml','model_provider="proxy"\nmodel_catalog_json="catalog.json"\n')
            self.write('.codex/catalog.json',{'models':[{'slug':'proxy-only'}]})
            self.assertEqual([row.id for row in discover('codex',self.home,env=env).models],['inherit','proxy-only'])
        self.write('.codex/config.toml','model="native-only"\n')
        before=discover('codex',self.home,env=env)
        self.write('.codex/config.toml','model="new-current"\nmodel_provider="new-provider"\n')
        with patch('manager.codex_models.query',side_effect=AssertionError('失效检测不得重新查询')):
            after=discover('codex',self.home,env=env,_snapshot=before)
        self.assertNotEqual(before.stamp,after.stamp)
        self.assertEqual([row.id for row in after.models],['inherit','new-current'])

    def test_deep_json_source_uses_safe_failure_projection(self):
        for host in ('codex','claude'):
            with self.subTest(host=host):
                rejected=deep_json_source(self.home,host)
                catalog=discover(host,self.home,env={});output=json.dumps(catalog.as_dict(),ensure_ascii=False)
                self.assertNotIn('DEEP-SOURCE-SECRET',output);self.assertNotIn('private_payload',output)
                if rejected:
                    self.assertTrue(any('模型来源读取失败' in note for note in catalog.notes))
                    self.assertEqual([row.id for row in catalog.models],['inherit'])
                    if host == 'claude':self.assertEqual(catalog.execution['status'],'unavailable')

    def test_codex_visible_current_cache_and_efforts(self):
        self.write('.codex/config.toml','model="visible"\nmodel_catalog_json="models_cache.json"\n')
        self.write('.codex/models_cache.json',{'models':[{'slug':'visible','supported_reasoning_levels':[{'effort':'max'},{'effort':'ultra'}]},{'slug':'hidden','visibility':'hide'}]})
        self.write('.codex/cc-switch-model-catalog.json',{'models':[{'slug':'inactive'}]})
        catalog=discover('codex',self.home,env={})
        self.assertEqual([row.id for row in catalog.models],['inherit','visible'])
        self.assertEqual(catalog.models[0].efforts,('max',));self.assertEqual(len(catalog.inactive),1)

    def test_explicit_cc_switch_catalog_and_provider_isolation(self):
        self.write('.codex/config.toml','model_provider="proxy"\nmodel_catalog_json="cc-switch-model-catalog.json"\n')
        self.write('.codex/cc-switch-model-catalog.json',{'models':[{'slug':'proxy-model'}]})
        self.write('.codex/models_cache.json',{'models':[{'slug':'openai-model'}]})
        self.assertEqual([row.id for row in discover('codex',self.home,env={}).models],['inherit','proxy-model'])
        self.write('.codex/config.toml','model_provider="proxy"\nmodel="current"\n')
        self.assertEqual([row.id for row in discover('codex',self.home,env={}).models],['inherit','current'])

    def test_claude_proxy_menu_and_mapping_without_secrets_or_guessed_effort(self):
        self.write('.claude/settings.json',{'env':{'ANTHROPIC_AUTH_TOKEN':'TOP-SECRET','ANTHROPIC_DEFAULT_OPUS_MODEL':'custom/model'},'modelPicker':{'options':[{'model':'custom/model','label':'自定义'}]},'modelSettings':{'custom/model':{'effortLevel':'max'}}})
        catalog=discover('claude',self.home,env={});output=json.dumps(catalog.as_dict())
        self.assertNotIn('TOP-SECRET',output);self.assertNotIn('AUTH_TOKEN',output)
        self.assertTrue(any(row.id == 'custom/model' for row in catalog.models));self.assertTrue(all(not row.efforts for row in catalog.models))
        self.assertIn('custom/model',next(row.label for row in catalog.models if row.id == 'opus'))

    def test_claude_settings_env_precedes_shell_and_tracks_effective_sources(self):
        """同名 env 先按文件层合并；环境模型再独立覆盖顶层 model。"""
        shell = {'ANTHROPIC_MODEL': 'shell-model', 'ANTHROPIC_BASE_URL': 'shell-endpoint',
                 'ANTHROPIC_DEFAULT_OPUS_MODEL': 'shell-opus'}
        settings = {'model': 'top-model', 'env': {
            'ANTHROPIC_MODEL': 'file-model', 'ANTHROPIC_BASE_URL': 'file-endpoint',
            'ANTHROPIC_DEFAULT_OPUS_MODEL': 'file-opus'},
            'modelPicker': {'options': [{'model': 'menu-model', 'label': '合法用户菜单'}]}}
        self.write('.claude/settings.json', settings)
        first = discover('claude', self.home, env=shell)
        self.assertEqual(first._status, 'ready')
        self.assertIn('file-model', [row.id for row in first.models])
        self.assertNotIn('shell-model', [row.id for row in first.models])
        self.assertNotIn('top-model', [row.id for row in first.models])
        self.assertIn('file-opus', next(row.label for row in first.models if row.id == 'opus'))
        # 被文件遮住的 shell 和顶层 model 不再是当前来源，变化不能废弃草稿。
        masked_shell = {key: value + '-changed' for key, value in shell.items()}
        self.assertEqual(first.stamp, discover('claude', self.home, env=masked_shell).stamp)
        settings['model'] = 'masked-top-model'
        self.write('.claude/settings.json', settings)
        self.assertEqual(first.stamp, discover('claude', self.home, env=shell).stamp)
        for key in shell:
            with self.subTest(effective_file_variable=key):
                settings['env'][key] += '-changed'
                self.write('.claude/settings.json', settings)
                changed = discover('claude', self.home, env=shell)
                self.assertEqual(changed._status, 'ready')
                self.assertNotEqual(first.stamp, changed.stamp)
                first = changed
        # local > project > user 的规则只作用于同名 env；不同变量保留各自来源。
        project = self.home / 'project'
        self.write('project/.claude/settings.json', {'env': {'ANTHROPIC_MODEL': 'project-model'}})
        self.write('project/.claude/settings.local.json', {'env': {'ANTHROPIC_MODEL': 'local-model'}})
        local = discover('claude', self.home, project, shell)
        self.assertIn('local-model', [row.id for row in local.models])
        self.assertNotIn('project-model', [row.id for row in local.models])
        settings['env'].pop('ANTHROPIC_MODEL')
        self.write('.claude/settings.json', settings)
        self.assertIn('shell-model', [row.id for row in discover('claude', self.home, env=shell).models])

    def test_claude_provider_routes_invalidate_authorized_catalogs(self):
        """路由切换废弃旧授权，但当前显式设置仍是新目录的证据。"""
        settings = {'model': 'configured-model', 'modelPicker': {
            'options': [{'model': 'configured-menu', 'label': '当前用户菜单'}]}}
        self.write('.claude/settings.json', settings)
        previous = discover('claude', self.home, env={})
        for selector, route in (
                ('CLAUDE_CODE_USE_BEDROCK', {'ANTHROPIC_BEDROCK_BASE_URL': 'bedrock-endpoint', 'AWS_REGION': 'us-east-1'}),
                ('CLAUDE_CODE_USE_VERTEX', {'ANTHROPIC_VERTEX_PROJECT_ID': 'fixture-project', 'CLOUD_ML_REGION': 'us-east5'}),
                ('CLAUDE_CODE_USE_FOUNDRY', {'ANTHROPIC_FOUNDRY_RESOURCE': 'fixture-resource'}),
                ('CLAUDE_CODE_USE_ANTHROPIC_AWS', {'ANTHROPIC_AWS_WORKSPACE_ID': 'fixture-workspace'}),
                ('CLAUDE_CODE_USE_MANTLE', {'ANTHROPIC_BEDROCK_MANTLE_BASE_URL': 'mantle-endpoint'})):
            with self.subTest(provider=selector):
                environment = {selector: '1', **route}
                current = discover('claude', self.home, env=environment)
                self.assertEqual(current._status, 'ready')
                self.assertNotEqual(previous.stamp, current.stamp)
                self.assertIn('configured-model', [row.id for row in current.models])
                self.assertIn('configured-menu', [row.id for row in current.models])
                for key in route:
                    changed = discover('claude', self.home, env={**environment, key: route[key] + '-changed'})
                    self.assertNotEqual(current.stamp, changed.stamp)
                self.assertEqual(current.stamp, discover('claude', self.home, env={
                    **environment, 'ANTHROPIC_AUTH_TOKEN': 'PRIVATE-TOKEN',
                    'AWS_SECRET_ACCESS_KEY': 'PRIVATE-KEY'}).stamp)
                previous = current
        # 文件明确关闭 shell 中的 Vertex；关闭的路由与被遮住的开关均不生效。
        settings['env'] = {'CLAUDE_CODE_USE_VERTEX': ''}
        self.write('.claude/settings.json', settings)
        first = discover('claude', self.home, env={'CLAUDE_CODE_USE_VERTEX': '1'})
        self.assertEqual(first.stamp, discover('claude', self.home, env={
            'CLAUDE_CODE_USE_VERTEX': '0', 'ANTHROPIC_VERTEX_PROJECT_ID': 'inactive'}).stamp)
        settings['env']['CLAUDE_CODE_USE_VERTEX'] = '0'
        self.write('.claude/settings.json', settings)
        self.assertEqual(first.stamp, discover('claude', self.home, env={}).stamp)
        settings['env']['CLAUDE_CODE_USE_VERTEX'] = '1'
        self.write('.claude/settings.json', settings)
        self.assertNotEqual(first.stamp, discover('claude', self.home, env={}).stamp)
        # 同一提供方的低优先级/非法 region 不构成当前路由；真实首选值变化仍失效。
        self.write('.claude/settings.json', {'model': 'configured-model'})
        regions = {'CLAUDE_CODE_USE_BEDROCK': '1', 'AWS_REGION': 'us-east-1', 'AWS_DEFAULT_REGION': 'us-west-2'}
        first = discover('claude', self.home, env=regions)
        self.assertEqual(first.stamp, discover('claude', self.home, env={**regions, 'AWS_DEFAULT_REGION': 'eu-west-1'}).stamp)
        invalid = {**regions, 'AWS_REGION': 'invalid/region'}
        fallback = discover('claude', self.home, env=invalid)
        self.assertEqual(fallback.stamp, discover('claude', self.home, env={**invalid, 'AWS_REGION': 'still invalid'}).stamp)
        self.assertNotEqual(fallback.stamp, discover('claude', self.home, env={**invalid, 'AWS_DEFAULT_REGION': 'eu-west-1'}).stamp)

    def _assert_claude_source_transition(self, before_env, after_env, *, changed):
        """真实磁盘配置与业务守卫必须对同一次来源变化给出一致结果。

        此处不 mock discover/check_catalogs/_guard，也不加载账户或启动宿主；
        缺失的私有 state 只读投影为 Node()，目录/预览检查不能顺手创建它。
        先收齐全部观察再断言，旧源行为红也能保留真实守卫是否误接受的证据。
        """
        from lib.central.runtime_project import Node
        from manager import model_preferences

        state, project = self.home / 'state', self.home / 'project'
        # check_catalogs 的真实入口要求项目目录存在；先建立本例空项目，避免
        # “项目不存在”提前拒绝掩盖本测试真正要观察的来源守卫结果。
        project.mkdir(exist_ok=True)
        common = {'HOME': str(self.home), 'CLAUDE_CONFIG_DIR': str(self.home / '.claude')}
        with patch.dict(os.environ, {**common, **before_env}, clear=True):
            before = discover('claude', project=project)
        with patch.dict(os.environ, {**common, **after_env}, clear=True):
            after = discover('claude', project=project)
            accepted = model_preferences.check_catalogs(state, project, 'claude', before)
            plan = model_preferences.ModelPreferencePlan(state, project, 'claude', Node(), b'{}',
                                                         None, before, (), b'{}')
            refused = False
            try:
                model_preferences._guard(plan)
            except ValueError as exc:
                self.assertIn('来源', str(exc))
                refused = True
        observed = (before._status, after._status, before.stamp == after.stamp, accepted, refused)
        self.assertEqual(observed, ('ready', 'ready', not changed, not changed, changed))
        self.assertFalse(state.exists())

    def test_claude_bedrock_sdk_endpoints_follow_effective_precedence(self):
        """SDK运行/控制端点各自选择有效值，忽略层不误伤，换有效端点拒旧授权。"""
        self.write('.claude/settings.json', {'model': 'configured-model', 'modelPicker': {
            'options': [{'model': 'configured-model'}]}})
        base = {'CLAUDE_CODE_USE_BEDROCK': '1', 'AWS_REGION': 'us-east-1'}
        endpoint_keys = ('AWS_ENDPOINT_URL', 'AWS_ENDPOINT_URL_BEDROCK', 'AWS_ENDPOINT_URL_BEDROCK_RUNTIME')
        for key in endpoint_keys:
            with self.subTest(effective_sdk_endpoint=key):
                self._assert_claude_source_transition(
                    {**base, key: 'https://first.example.com'},
                    {**base, key: 'https://second.example.com'}, changed=True)
        services = {**base, 'AWS_ENDPOINT_URL_BEDROCK': 'https://control.example.com',
                    'AWS_ENDPOINT_URL_BEDROCK_RUNTIME': 'https://runtime.example.com',
                    'AWS_ENDPOINT_URL': 'https://masked.example.com'}
        with self.subTest(both_services_mask_global=True):
            self._assert_claude_source_transition(services, {**services, 'AWS_ENDPOINT_URL': 'https://ignored.example.com'},
                                                 changed=False)
        # 只覆盖一种服务时，global 对另一种服务仍生效；不能把三变量取成一个
        # “优先级最高端点”而丢掉控制面或运行面的独立路由身份。
        for service in endpoint_keys[1:]:
            with self.subTest(global_still_used_by_other_service=service):
                first = {**base, service: 'https://service.example.com', 'AWS_ENDPOINT_URL': 'https://first.example.com'}
                self._assert_claude_source_transition(first, {**first, 'AWS_ENDPOINT_URL': 'https://second.example.com'},
                                                     changed=True)
        with self.subTest(ignore_configured_endpoints=True):
            first = {**services, 'AWS_IGNORE_CONFIGURED_ENDPOINT_URLS': 'true'}
            second = {**first, **{key: 'https://ignored-change.example.com' for key in endpoint_keys}}
            self._assert_claude_source_transition(first, second, changed=False)
            self._assert_claude_source_transition(first, {**first, 'AWS_IGNORE_CONFIGURED_ENDPOINT_URLS': 'false'},
                                                 changed=True)
        with self.subTest(explicit_client_masks_sdk_and_ignore=True):
            first = {**services, 'ANTHROPIC_BEDROCK_BASE_URL': 'https://client.example.com'}
            second = {**first, **{key: 'https://masked-change.example.com' for key in endpoint_keys},
                      'AWS_IGNORE_CONFIGURED_ENDPOINT_URLS': 'true'}
            self._assert_claude_source_transition(first, second, changed=False)
            self._assert_claude_source_transition(second, {**second, 'ANTHROPIC_BEDROCK_BASE_URL': 'https://client-new.example.com'},
                                                 changed=True)
        with self.subTest(provider_disabled=True):
            first = {**services, 'CLAUDE_CODE_USE_BEDROCK': ''}
            second = {**first, **{key: 'https://inactive.example.com' for key in endpoint_keys},
                      'AWS_IGNORE_CONFIGURED_ENDPOINT_URLS': 'true'}
            self._assert_claude_source_transition(first, second, changed=False)

    def test_claude_ignored_auxiliary_and_invalid_vertex_regions_keep_authorization(self):
        """辅助region须满足原生生效条件；非法Vertex位置按未设置回退。"""
        self.write('.claude/settings.json', {'model': 'configured-model'})
        region_key = 'ANTHROPIC_SMALL_FAST_MODEL_AWS_REGION'
        bedrock = {'CLAUDE_CODE_USE_BEDROCK': '1', 'AWS_REGION': 'us-east-1'}
        for model in ({}, {'ANTHROPIC_DEFAULT_HAIKU_MODEL': '', 'ANTHROPIC_SMALL_FAST_MODEL': ''}):
            with self.subTest(unused_small_fast_model=model):
                self._assert_claude_source_transition(
                    {**bedrock, **model, region_key: 'us-west-1'},
                    {**bedrock, **model, region_key: 'eu-west-1'}, changed=False)
        for model_key in ('ANTHROPIC_DEFAULT_HAIKU_MODEL', 'ANTHROPIC_SMALL_FAST_MODEL'):
            with self.subTest(explicit_small_fast_model=model_key):
                self._assert_claude_source_transition(
                    {**bedrock, model_key: 'haiku-fixture', region_key: 'us-west-1'},
                    {**bedrock, model_key: 'haiku-fixture', region_key: 'eu-west-1'}, changed=True)
        with self.subTest(unrelated_anthropic_aws_provider=True):
            first = {'CLAUDE_CODE_USE_ANTHROPIC_AWS': '1', region_key: 'us-west-1'}
            self._assert_claude_source_transition(first, {**first, region_key: 'eu-west-1'}, changed=False)
        with self.subTest(mantle_haiku_region_documented_separately=True):
            first = {'CLAUDE_CODE_USE_MANTLE': '1', region_key: 'us-west-1'}
            self._assert_claude_source_transition(first, {**first, region_key: 'eu-west-1'}, changed=True)
        vertex = {'CLAUDE_CODE_USE_VERTEX': '1', 'ANTHROPIC_VERTEX_PROJECT_ID': 'fixture-project'}
        for key in ('CLOUD_ML_REGION', 'VERTEX_REGION_CLAUDE_HAIKU_4_5'):
            with self.subTest(invalid_vertex_region=key):
                first = {**vertex, key: 'invalid/region'}
                self._assert_claude_source_transition(first, {**first, key: 'still invalid'}, changed=False)
                self._assert_claude_source_transition(first, vertex, changed=False)
            for before, after in (('global', 'eu'), ('eu', 'us'), ('us-east5', 'europe-west1')):
                with self.subTest(valid_vertex_region=key, before=before, after=after):
                    self._assert_claude_source_transition({**vertex, key: before}, {**vertex, key: after}, changed=True)
        with self.subTest(invalid_model_region_falls_back_to_global=True):
            first = {**vertex, 'CLOUD_ML_REGION': 'us-east5', 'VERTEX_REGION_CLAUDE_HAIKU_4_5': 'invalid/region'}
            self._assert_claude_source_transition(first, {**first, 'CLOUD_ML_REGION': 'europe-west1'}, changed=True)

    def test_claude_project_model_picker_is_ignored(self):
        """原生只允许用户等可信层提供菜单；项目仍能明确设置顶层模型。"""
        settings = {'modelPicker': {'options': [{'model': 'user-menu', 'label': '用户菜单'}]}}
        self.write('.claude/settings.json', settings)
        project = self.home / 'project'
        self.write('project/.claude/settings.json', {'model': 'project-current', 'modelPicker': {
            'options': [{'model': 'project-menu', 'label': '项目无效菜单'}]}})
        self.write('project/.claude/settings.local.json', {'modelPicker': {
            'options': [{'model': 'local-menu', 'label': '本地无效菜单'}]}})
        first = discover('claude', self.home, project, {})
        self.assertIn('user-menu', [row.id for row in first.models])
        self.assertIn('project-current', [row.id for row in first.models])
        self.assertNotIn('project-menu', [row.id for row in first.models])
        self.assertNotIn('local-menu', [row.id for row in first.models])
        self.write('project/.claude/settings.local.json', {'modelPicker': {
            'options': [{'model': 'changed-ignored-menu'}]}})
        self.assertEqual(first.stamp, discover('claude', self.home, project, {}).stamp)
        self.write('.claude/settings.json', {})
        self.assertNotIn('changed-ignored-menu', [row.id for row in discover('claude', self.home, project, {}).models])

    def test_project_provider_change_preserves_explicit_user_configuration_but_invalidates_stamp(self):
        # Claude 当前用户字段不是历史目录缓存：新 provider 仍读取它们。真正需要
        # 拒绝的是换源前的授权快照，不能通过清空有效菜单/model 假装修复隔离。
        self.write('.claude/settings.json',{'model':'configured-model','env':{'ANTHROPIC_BASE_URL':'old'},
            'modelPicker':{'options':[{'model':'configured-menu'}]}})
        project=self.home/'project';self.write('project/.claude/settings.json',{'env':{'ANTHROPIC_BASE_URL':'new'}})
        before=discover('claude',self.home,env={});after=discover('claude',self.home,project,{})
        self.assertIn('configured-model',[row.id for row in after.models])
        self.assertIn('configured-menu',[row.id for row in after.models])
        self.assertNotEqual(before.stamp,after.stamp)

    def test_mismatched_codex_cache_identity_is_not_trusted(self):
        self.write('.codex/config.toml','model_provider="openai"\n')
        self.write('.codex/models_cache.json',{'identity':{'model_provider':'private-proxy'},'models':[{'slug':'proxy-only'}]})
        self.assertEqual([row.id for row in discover('codex',self.home,env={}).models],['inherit'])

    def test_broken_cache_fails_closed_and_antigravity_is_tier_only(self):
        self.write('.codex/models_cache.json','broken json')
        catalog=discover('codex',self.home,env={});self.assertEqual(len(catalog.models),1);self.assertTrue(catalog.notes)
        self.assertEqual([row.id for row in discover('antigravity',self.home,env={}).models],['inherit','flash','pro'])

    def test_real_opaque_identity_is_inactive_without_explicit_catalog(self):
        self.write('.codex/config.toml','model="current"\n')
        self.write('.codex/models_cache.json',{'identity':'f'*64,'models':[{'slug':'previous-provider','supported_reasoning_levels':[{'effort':'max'}]}]})
        catalog=discover('codex',self.home,env={})
        self.assertEqual([row.id for row in catalog.models],['inherit','current'])
        self.assertTrue(catalog.inactive);self.assertTrue(all(not row.efforts for row in catalog.models))

    def test_project_relative_catalog_uses_declaring_config_directory(self):
        self.write('.codex/catalog.json',{'models':[{'slug':'global-only'}]})
        self.write('project/.codex/config.toml','model_catalog_json="catalog.json"\n')
        self.write('project/.codex/catalog.json',{'models':[{'slug':'project-only'}]})
        catalog=discover('codex',self.home,self.home/'project',{})
        self.assertEqual([row.id for row in catalog.models],['inherit','project-only'])

    def test_retired_profiles_do_not_override_base_model(self):
        self.write('.codex/config.toml','model="current"\nprofile="retired"\n[profiles.retired]\nmodel="obsolete"\nmodel_catalog_json="old.json"\n')
        self.write('.codex/old.json',{'models':[{'slug':'old-only'}]})
        catalog=discover('codex',self.home,env={})
        self.assertEqual([row.id for row in catalog.models],['inherit','current'])

    def test_claude_new_provider_keeps_same_layer_model_and_env_override(self):
        self.write('.claude/settings.json',{'model':'old','env':{'ANTHROPIC_BASE_URL':'old'}})
        self.write('project/.claude/settings.json',{'model':'new-project','env':{'ANTHROPIC_BASE_URL':'new'}})
        self.assertIn('new-project',[row.id for row in discover('claude',self.home,self.home/'project',{}).models])
        self.write('project/.claude/settings.local.json',{'model':'new-local'})
        self.assertIn('new-local',[row.id for row in discover('claude',self.home,self.home/'project',{}).models])
        catalog=discover('claude',self.home,self.home/'project',{'ANTHROPIC_MODEL':'new-env'})
        self.assertIn('new-env',[row.id for row in catalog.models]);self.assertNotIn('old',[row.id for row in catalog.models])

    def test_source_stamp_changes_without_exposing_config_or_secrets(self):
        self.write('.claude/settings.json',{'model':'first','env':{'ANTHROPIC_AUTH_TOKEN':'SECRET'}})
        first=discover('claude',self.home,env={});second=discover('claude',self.home,env={})
        self.assertEqual(first.stamp,second.stamp)
        self.write('.claude/settings.json',{'model':'second','env':{'ANTHROPIC_AUTH_TOKEN':'SECRET'}})
        self.assertNotEqual(first.stamp,discover('claude',self.home,env={}).stamp)
        self.assertNotIn('SECRET',json.dumps(first.as_dict()));self.assertNotIn('_inputs',first.as_dict())

    def test_unrelated_configuration_does_not_invalidate_model_drafts(self):
        """权限、Hooks、凭据、废弃层和未启用缓存变化均不属于模型选择证据。"""
        self.write('.claude/settings.json',{'model':'same','permissions':{'allow':['Read']},'env':{'ANTHROPIC_AUTH_TOKEN':'first'}})
        before=discover('claude',self.home,env={})
        self.write('.claude/settings.json',{'model':'same','permissions':{'allow':['Write']},'hooks':{},'env':{'ANTHROPIC_AUTH_TOKEN':'second'}})
        self.assertEqual(before.stamp,discover('claude',self.home,env={'OPENAI_BASE_URL':'irrelevant'}).stamp)
        self.write('.codex/config.toml','model="same"\n[profiles.old]\nmodel="old"\n')
        self.write('.codex/models_cache.json',{'models':[{'slug':'inactive-first'}],'fetchedAt':1})
        before=discover('codex',self.home,env={})
        self.write('.codex/config.toml','model="same"\n[profiles.old]\nmodel="changed-old"\n')
        self.write('.codex/models_cache.json',{'models':[{'slug':'inactive-second'}],'fetchedAt':2})
        self.assertEqual(before.stamp,discover('codex',self.home,env={'ANTHROPIC_MODEL':'irrelevant'}).stamp)
        self.assertEqual(discover('antigravity',self.home,env={}).stamp,
                         discover('antigravity',self.home,env={'OPENAI_BASE_URL':'irrelevant'}).stamp)
        self.write('.claude/settings.json',{'env':{'ANTHROPIC_MODEL':'overridden-first'}})
        before=discover('claude',self.home,env={'ANTHROPIC_MODEL':'selected'})
        self.write('.claude/settings.json',{'env':{'ANTHROPIC_MODEL':'overridden-second'}})
        # 同根因旧断言曾将 shell 当成最高来源；实际生效的是 settings.env。
        self.assertNotEqual(before.stamp,discover('claude',self.home,env={'ANTHROPIC_MODEL':'selected'}).stamp)
        after=discover('claude',self.home,env={'ANTHROPIC_MODEL':'selected'})
        self.assertEqual(after.stamp,discover('claude',self.home,env={'ANTHROPIC_MODEL':'masked-shell-change'}).stamp)

    def test_effective_provider_layer_mapping_and_capability_still_invalidate(self):
        self.write('.codex/config.toml','model="same"\nmodel_provider="proxy"\nmodel_catalog_json="catalog.json"\n[model_providers.proxy]\nbase_url="first"\n')
        self.write('.codex/catalog.json',{'models':[{'slug':'same','supported_reasoning_levels':['high']}]})
        before=discover('codex',self.home,env={})
        self.write('.codex/catalog.json',{'models':[{'slug':'same','supported_reasoning_levels':['high','max']}]})
        self.assertNotEqual(before.stamp,discover('codex',self.home,env={}).stamp)
        before=discover('codex',self.home,env={})
        path=self.home/'.codex/config.toml';path.write_text(path.read_text().replace('base_url="first"','base_url="second"'))
        self.assertNotEqual(before.stamp,discover('codex',self.home,env={}).stamp)
        before=discover('codex',self.home,self.home/'project',{})
        self.write('project/.codex/config.toml','model="same"\n')
        self.assertNotEqual(before.stamp,discover('codex',self.home,self.home/'project',{}).stamp)
        before=discover('codex',self.home,self.home/'project',{})
        self.write('project/.codex/config.toml','model="same"\nmodel_provider="project-proxy"\n[model_providers.project-proxy]\nbase_url="project-endpoint"\n')
        self.assertNotEqual(before.stamp,discover('codex',self.home,self.home/'project',{}).stamp)
        self.write('.claude/settings.json',{'env':{'ANTHROPIC_BASE_URL':'first','ANTHROPIC_DEFAULT_OPUS_MODEL':'first-model'}})
        before=discover('claude',self.home,env={})
        self.assertEqual(before.stamp,discover('claude',self.home,env={'ANTHROPIC_BASE_URL':'second'}).stamp)
        self.assertEqual(before.stamp,discover('claude',self.home,env={'ANTHROPIC_DEFAULT_OPUS_MODEL':'second-model'}).stamp)
        self.write('.claude/settings.json',{'env':{'ANTHROPIC_BASE_URL':'second','ANTHROPIC_DEFAULT_OPUS_MODEL':'second-model'}})
        self.assertNotEqual(before.stamp,discover('claude',self.home,env={}).stamp)


class ClaudeExecutionAndDiagnosticsTest(unittest.TestCase):
    """验证真实配置投影与命令输出；不启动真实模型或访问用户账户。"""

    setUp = CatalogTest.setUp
    tearDown = CatalogTest.tearDown
    write = CatalogTest.write

    def test_v2_lifecycle_diagnostics_never_infer_live_tools_or_native_end(self):
        """官方能力和版本观测都不能冒充本会话隔离、关闭或容量释放证明。"""
        expected = {"codex": {"fresh_subagent_context", "native_stop_and_close"},
                    "claude": {"fresh_named_subagent_context", "send_message_resume", "task_stop"},
                    "antigravity": {"fresh_subagent_context", "subagent_kill"}}
        with patch('manager.capabilities.subprocess.run', side_effect=AssertionError('不得探测模型或工具')):
            for host, names in expected.items():
                result = diagnose(host, home=self.home, environment={})
                with self.subTest(host=host):
                    features = {row['name']: row for row in result['documented_capabilities']}
                    self.assertTrue(names.issubset(features))
                    self.assertTrue(all(not features[name]['runtime_verified'] for name in names))
                    boundary = result['agent_lifecycle_boundary']
                    self.assertEqual(2, boundary['workflow_schema_version'])
                    self.assertEqual('handoff_only', boundary['context_policy'])
                    self.assertEqual('fresh', boundary['instance_policy'])
                    self.assertEqual('not_inspected', boundary['current_tool_surface'])
                    self.assertEqual('retire_without_reuse', boundary['unavailable_end_action'])
                    self.assertFalse(boundary['native_end_confirmed'])
                    if host == 'codex':
                        self.assertIn('interrupt', features['native_stop_and_close']['boundary'])

    def test_window_override_and_write_guard_projection_are_safe_and_do_not_invalidate_model_drafts(self):
        self.write('.claude/settings.json', {'permissions': {'blockWritesOutsideWorkingDirectories': True, 'deny': ['PRIVATE-RULE']}})
        project = self.home / 'project'
        self.write('project/.claude/settings.local.json', {'permissions': {'blockWritesOutsideWorkingDirectories': False},
            'env': {'CLAUDE_CODE_AUTO_COMPACT_WINDOW': '200k'}})
        first = discover('claude', self.home, project, {'CLAUDE_CODE_AUTO_COMPACT_WINDOW': '300000'})
        result = effective_role({'model': 'opus', 'effort': 'inherit'}, first.execution['controls'], 100000)
        window = result['auto_compact_window']
        self.assertEqual(100000, window['configured_role'])
        self.assertEqual(200000, window['requested'])
        self.assertIsNone(window['actual'])
        self.assertEqual('CLAUDE_CODE_AUTO_COMPACT_WINDOW', window['source'])
        guard = first.execution['write_scope_guard']
        self.assertFalse(guard['value'])
        self.assertTrue(guard['source'].endswith('settings.local.json'))
        self.assertNotIn('PRIVATE-RULE', json.dumps(first.as_dict()))
        self.write('project/.claude/settings.local.json', {'permissions': {'blockWritesOutsideWorkingDirectories': True},
            'env': {'CLAUDE_CODE_AUTO_COMPACT_WINDOW': '1m'}})
        second = discover('claude', self.home, project, {})
        self.assertEqual(first.stamp, second.stamp)
        self.assertEqual(1000000, second.execution['controls']['CLAUDE_CODE_AUTO_COMPACT_WINDOW']['value'])
        self.write('project/.claude/settings.local.json', {'permissions': {'blockWritesOutsideWorkingDirectories': 'SECRET'},
            'env': {'CLAUDE_CODE_AUTO_COMPACT_WINDOW': 'SECRET'}})
        invalid = discover('claude', self.home, project, {})
        self.assertNotIn('SECRET', json.dumps(invalid.as_dict()))
        self.assertEqual('invalid', invalid.execution['write_scope_guard']['status'])
        self.assertIsNone(effective_role({'model': 'opus', 'effort': 'inherit'}, invalid.execution['controls'], 100000)['auto_compact_window']['requested'])

    def test_doctor_distinguishes_supported_window_from_unsupported_guard(self):
        completed = subprocess.CompletedProcess(['fixture', '--version'], 0, '2.1.309 (Claude Code)\n', '')
        with patch('manager.capabilities.shutil.which', return_value='/fixture/claude'), \
                patch('manager.capabilities.subprocess.run', return_value=completed):
            result = diagnose('claude', probe=True, home=self.home, environment={})
        features = {row['name']: row for row in result['documented_capabilities']}
        self.assertTrue(features['role_auto_compact_window']['version_meets_minimum'])
        self.assertFalse(features['block_writes_outside_working_directories']['version_meets_minimum'])
        self.assertEqual('SessionStart(compact)', result['compaction_lifecycle']['recovery_event'])
        self.assertFalse(result['compaction_lifecycle']['pre_post_compact_registered'])
        self.assertTrue(all(not row['runtime_verified'] for row in features.values()))

    def test_unreadable_source_cannot_be_reported_as_absent_overrides(self):
        """损坏的来源必须让有效值推导失败；不能把空目录投影误当成“角色字段生效”。"""
        project = self.home / 'project'
        self.write('project/.claude/agents/xy-backend.md',
                   '---\nname: xy-backend\nmodel: opus\nautoCompactWindow: 200000\n---\nfixture\n')
        self.write('.claude/settings.json', '{BROKEN JSON')
        output, error = io.StringIO(), io.StringIO()
        with patch('pathlib.Path.home', return_value=self.home), patch.dict(os.environ, {'CLAUDE_CODE_AUTO_COMPACT_WINDOW': '300000'}, clear=True), \
                redirect_stdout(output), redirect_stderr(error):
            code = cli_main(['roles', '--project', str(project), '--platform', 'claude', '--effective'])
        self.assertEqual(2, code)
        self.assertEqual('', output.getvalue())
        self.assertIn('来源读取失败', error.getvalue())
        result = diagnose('claude', project=project, home=self.home, environment={})
        self.assertEqual('unavailable', result['execution']['status'])
        self.assertIsNone(result['execution']['write_scope_guard']['value'])

    def test_effort_sources_and_role_priority_follow_local_settings(self):
        self.write('.claude/settings.json', {'env': {'CLAUDE_CODE_SUBAGENT_EFFORT': 'low'}})
        project = self.home / 'project'
        self.write('project/.claude/settings.json', {'env': {'CLAUDE_CODE_EFFORT_LEVEL': 'medium'}})
        self.write('project/.claude/settings.local.json', {'env': {'CLAUDE_CODE_EFFORT_LEVEL': 'xhigh'}})
        catalog = discover('claude', self.home, project, {'CLAUDE_CODE_EFFORT_LEVEL': 'high'})
        controls = catalog.execution['controls']
        self.assertNotIn('CLAUDE_CODE_SUBAGENT_EFFORT', controls)
        self.assertEqual('xhigh', controls['CLAUDE_CODE_EFFORT_LEVEL']['value'])
        self.assertTrue(controls['CLAUDE_CODE_EFFORT_LEVEL']['source'].endswith('settings.local.json'))
        result = effective_role({'model': 'opus', 'effort': 'high'}, controls)
        self.assertEqual('xhigh', result['effort']['value'])
        self.assertEqual('role.model', result['model']['source'])
        self.assertFalse(result['runtime_verified'])
        self.assertEqual('>=2.1.251', result['version_requirements']['model_definition_precedence'])
        defaults = {'CLAUDE_CODE_SUBAGENT_EFFORT': {'status': 'configured', 'value': 'low'}}
        self.assertEqual('high', effective_role({'model': 'opus', 'effort': 'high'}, defaults)['effort']['value'])
        self.assertIsNone(effective_role({'model': 'opus', 'effort': 'inherit'}, defaults)['effort']['value'])

    def test_model_force_and_explicit_inherit_do_not_guess_main_session(self):
        configured = {'model': 'inherit', 'effort': 'inherit'}
        self.write('.claude/settings.json', {'env': {'CLAUDE_CODE_SUBAGENT_MODEL': 'haiku'}})
        controls = discover('claude', self.home, env={}).execution['controls']
        self.assertIsNone(effective_role(configured, controls)['model']['value'])
        self.write('.claude/settings.json', {'env': {'CLAUDE_CODE_SUBAGENT_MODEL': 'haiku',
                                                  'CLAUDE_CODE_SUBAGENT_MODEL_FORCE': 'true'}})
        controls = discover('claude', self.home, env={}).execution['controls']
        self.assertEqual('haiku', effective_role({'model': 'opus', 'effort': 'high'}, controls)['model']['value'])
        controls['CLAUDE_CODE_SUBAGENT_MODEL']['value'] = 'inherit'
        self.assertIsNone(effective_role(configured, controls)['model']['value'])

    def test_invalid_controls_and_unrelated_secrets_are_not_exposed(self):
        self.write('.claude/settings.json', {'env': {'ANTHROPIC_AUTH_TOKEN': 'TOP-SECRET',
            'CLAUDE_CODE_SUBAGENT_EFFORT': 'SECRET\ninjection',
            'CLAUDE_CODE_SUBAGENT_MODEL_FORCE': {'secret': 'DO-NOT-ECHO'}}})
        catalog = discover('claude', self.home, env={})
        output = json.dumps(catalog.as_dict(), ensure_ascii=False)
        for secret in ('TOP-SECRET', 'SECRET', 'DO-NOT-ECHO', 'AUTH_TOKEN'):
            self.assertNotIn(secret, output)
        controls = catalog.execution['controls']
        self.assertNotIn('CLAUDE_CODE_SUBAGENT_EFFORT', controls)
        self.assertIsNone(effective_role({'model': 'opus', 'effort': 'inherit'}, controls)['model']['value'])

    def test_only_effective_model_controls_invalidate_source_stamp(self):
        self.write('.claude/settings.json', {'env': {'CLAUDE_CODE_EFFORT_LEVEL': 'high'}})
        before = discover('claude', self.home, env={})
        self.assertEqual(before.stamp, discover('claude', self.home, env={
            'CLAUDE_CODE_EFFORT_LEVEL': 'low', 'CLAUDE_CODE_FORK_SUBAGENT': '0'}).stamp)
        self.write('.claude/settings.json', {'env': {'CLAUDE_CODE_EFFORT_LEVEL': 'max'}})
        self.assertNotEqual(before.stamp, discover('claude', self.home, env={}).stamp)

    def test_doctor_default_is_read_only_and_does_not_start_clients(self):
        project = self.home / 'project'
        self.write('project/.agent-workflow/project.yaml', 'workflow_hooks:\n  mode: off\n')
        before = {str(p): p.read_bytes() for p in self.home.rglob('*') if p.is_file()}
        with patch('manager.capabilities.subprocess.run', side_effect=AssertionError('不得默认启动宿主')):
            results = [diagnose(host, project=project, home=self.home, environment={})
                       for host in ('codex', 'claude', 'antigravity')]
        self.assertTrue(all(row['client']['status'] == 'not_probed' for row in results))
        self.assertTrue(all(row['workflow']['mode'] == 'off' for row in results))
        self.assertTrue(all(not row['runtime_verified'] for row in results))
        self.assertEqual(['SessionStart'], results[-1]['workflow']['target_hook_events'])
        self.assertEqual(before, {str(p): p.read_bytes() for p in self.home.rglob('*') if p.is_file()})

    def test_antigravity_capabilities_separate_documentation_from_runtime_and_ai_review(self):
        """文档列出的入口只证明合同存在，人工审阅面板不能冒充专用 AI 审查。"""
        result = diagnose('antigravity', home=self.home, environment={})
        features = {row['name']: row for row in result['documented_capabilities']}
        expected = {'diff_review_ui', 'artifact_review_ui', 'independent_subagents', 'send_message_resume',
                    'conversation_resume', 'context_usage', 'quota_usage', 'headless_json',
                    'structured_output_schema', 'cumulative_session_usage', 'skill_source_inspection',
                    'skill_reload', 'native_grill_me', 'native_plan'}
        self.assertTrue(expected.issubset(features))
        self.assertTrue(all(row['evidence_level'] == 'documented' for row in features.values()))
        self.assertTrue(all(row['runtime_status'] == 'runtime_unverified' for row in features.values()))
        for name in ('diff_review_ui', 'artifact_review_ui'):
            self.assertEqual('human_review_ui', features[name]['kind'])
        self.assertEqual('--json-schema', features['structured_output_schema']['interface'])
        self.assertEqual('cumulative_session', features['cumulative_session_usage']['counter_scope'])
        self.assertEqual('not_confirmed_in_reference', result['review_boundary']['dedicated_ai_review']['status'])
        self.assertFalse(result['review_boundary']['dedicated_ai_review']['runtime_verified'])

    def test_antigravity_skill_source_is_bounded_project_metadata_and_actual_source_stays_unknown(self):
        """只读取明确项目技能；当前文件和文档优先级均不足以确认宿主实际命中。"""
        project = self.home / 'project'
        path = self.write('project/.agents/skills/grill-me/SKILL.md',
                          '---\nname: "grill-me"\ndescription: fixture\n---\nPRIVATE-SKILL-BODY\n')
        self.write('.gemini/skills/grill-me/SKILL.md', 'PERSONAL-SKILL-SECRET')
        before = path.read_bytes()
        with patch('pathlib.Path.rglob', side_effect=AssertionError('不得递归扫描技能目录')), \
                patch('pathlib.Path.glob', side_effect=AssertionError('不得枚举技能目录')), \
                patch('manager.capabilities.subprocess.run', side_effect=AssertionError('不得启动宿主')):
            result = diagnose('antigravity', project=project, home=self.home, environment={})
        source = result['customization_sources']['grill_me']
        definition = source['project_definition']
        self.assertEqual('.agents/skills/grill-me/SKILL.md', definition['relative_path'])
        self.assertEqual('source_observed', definition['status'])
        self.assertEqual('source_observed', definition['evidence_level'])
        self.assertEqual('grill-me', definition['declared_name'])
        self.assertEqual(hashlib.sha256(before).hexdigest(), definition['sha256'])
        self.assertEqual('possible', source['same_name_risk'])
        self.assertEqual('unknown', source['actual_source']['status'])
        self.assertIsNone(source['actual_source']['source'])
        self.assertEqual('runtime_unverified', source['actual_source']['evidence_level'])
        self.assertFalse(result['customization_sources']['personal_directories_scanned'])
        self.assertNotIn('PRIVATE-SKILL-BODY', json.dumps(result))
        self.assertNotIn('PERSONAL-SKILL-SECRET', json.dumps(result))
        self.assertEqual(before, path.read_bytes())

    def test_antigravity_skill_declaration_does_not_trust_filename_or_echo_invalid_names(self):
        project = self.home / 'project'
        for declaration, name, risk in (("name: different-skill", 'different-skill', 'unknown'),
                                        ('name: grill-me\nname: grill-me', None, 'unknown'),
                                        ('name: grill-me\ndescription: first\ndescription: second', None, 'unknown'),
                                        ('name: grill-me\nBROKEN-FRONTMATTER', None, 'unknown'),
                                        ('name: grill-me\ndescription: "SECRET', None, 'unknown'),
                                        ('name: grill-me\ndescription:   ', None, 'unknown'),
                                        ('name: "grill-me\\u001bSECRET"', None, 'unknown'),
                                        ('name: ' + 'a' * 65, None, 'unknown'),
                                        ('name: [SECRET]', None, 'unknown')):
            with self.subTest(declaration=declaration):
                self.write('project/.agents/skills/grill-me/SKILL.md', '---\n' + declaration + '\n---\n')
                result = diagnose('antigravity', project=project, home=self.home, environment={})
                source = result['customization_sources']['grill_me']
                self.assertEqual(name, source['project_definition']['declared_name'])
                self.assertEqual(risk, source['same_name_risk'])
                self.assertEqual('unknown', source['actual_source']['status'])
                self.assertNotIn('SECRET', json.dumps(result))

    def test_antigravity_skill_source_failure_remains_unknown_and_uses_safe_reader(self):
        """链接、特殊节点、非法编码和超限内容全部拒绝；失败不能退回成功或空覆盖。"""
        project = self.home / 'project'
        path = self.write('project/.agents/skills/grill-me/SKILL.md', '---\nname: grill-me\n---\n')
        outside = self.write('outside-skill', 'OUTSIDE-SECRET')
        for kind in ('symlink', 'parent_symlink', 'hardlink', 'fifo', 'invalid_utf8', 'oversized'):
            with self.subTest(kind=kind):
                if path.is_symlink() or path.exists():
                    path.unlink()
                if kind == 'symlink':
                    path.symlink_to(outside)
                elif kind == 'parent_symlink':
                    directory = path.parent
                    directory.rmdir()
                    directory.symlink_to(self.home, target_is_directory=True)
                elif kind == 'hardlink':
                    os.link(outside, path)
                elif kind == 'fifo':
                    os.mkfifo(path)
                else:
                    path.write_bytes(b'\xff' if kind == 'invalid_utf8' else b'x' * (4 * 1024 * 1024 + 1))
                result = diagnose('antigravity', project=project, home=self.home, environment={})
                source = result['customization_sources']['grill_me']
                self.assertEqual('invalid_or_unreadable', source['project_definition']['status'])
                self.assertIsNone(source['project_definition']['sha256'])
                self.assertEqual('unknown', source['same_name_risk'])
                self.assertEqual('unknown', source['actual_source']['status'])
                self.assertNotIn('OUTSIDE-SECRET', json.dumps(result))
                if kind == 'parent_symlink':
                    path.parent.unlink()
                    path.parent.mkdir()
        path.unlink()
        source = diagnose('antigravity', project=project, home=self.home, environment={})['customization_sources']['grill_me']
        self.assertEqual('not_found', source['project_definition']['status'])
        self.assertEqual('unknown', source['actual_source']['status'])

    def test_doctor_probe_only_requests_version_and_keeps_unverified_source_after_failure(self):
        """显式探测也不扩展到 help、面板或模型，探测失败只返回固定安全状态。"""
        for response in (subprocess.CompletedProcess(['fixture', '--version'], 0, 'agy 1.4.4\n', ''),
                         subprocess.CompletedProcess(['fixture', '--version'], 2, 'SECRET', 'SECRET'),
                         OSError('SECRET')):
            with self.subTest(response=type(response).__name__), \
                    patch('manager.capabilities.shutil.which', return_value='/fixture/agy'), \
                    patch('manager.capabilities.subprocess.run', **({'side_effect': response} if isinstance(response, OSError)
                                                                  else {'return_value': response})) as run:
                result = diagnose('antigravity', probe=True, home=self.home, environment={})
            self.assertEqual(['/fixture/agy', '--version'], run.call_args.args[0])
            self.assertEqual(3, run.call_args.kwargs['timeout'])
            self.assertEqual(subprocess.DEVNULL, run.call_args.kwargs['stdin'])
            self.assertEqual(1, run.call_count)
            self.assertEqual('source_observed' if result['client']['status'] == 'version_observed' else 'runtime_unverified',
                             result['client']['evidence_level'])
            self.assertFalse(result['runtime_verified'])
            self.assertNotIn('SECRET', json.dumps(result))

    def test_cli_doctor_exposes_source_evidence_without_spawning_or_writing(self):
        project = self.home / 'project'
        path = self.write('project/.agents/skills/grill-me/SKILL.md', '---\nname: grill-me\n---\nBODY\n')
        before = path.read_bytes()
        output = io.StringIO()
        with patch('pathlib.Path.home', return_value=self.home), patch.dict(os.environ, {}, clear=True), \
                patch('manager.capabilities.subprocess.run', side_effect=AssertionError('不得启动宿主')), redirect_stdout(output):
            self.assertEqual(0, cli_main(['doctor', '--platform', 'antigravity', '--project', str(project)]))
        result = json.loads(output.getvalue())[0]
        self.assertEqual('not_probed', result['client']['status'])
        self.assertEqual('possible', result['customization_sources']['grill_me']['same_name_risk'])
        self.assertEqual(before, path.read_bytes())
        self.assertFalse((self.home / '.config/agent-workflow').exists())

    def test_version_probe_is_not_runtime_proof_and_never_echoes_raw_output(self):
        for version, eligible in (('2.1.309', False), ('2.1.316', True), ('2.1.316-alpha.1', None)):
            completed = subprocess.CompletedProcess(['fixture', '--version'], 0,
                f'SECRET\n{version} (Claude Code)\n', 'credential error SECRET')
            with self.subTest(version=version), patch('manager.capabilities.shutil.which', return_value='/fixture/claude'), \
                    patch('manager.capabilities.subprocess.run', return_value=completed):
                result = diagnose('claude', probe=True, home=self.home, environment={})
            row = next(item for item in result['documented_capabilities'] if item['name'] == 'block_writes_outside_working_directories')
            self.assertEqual(eligible, row['version_meets_minimum'])
            self.assertFalse(row['runtime_verified'])
            self.assertNotIn('SECRET', json.dumps(result))
        completed = subprocess.CompletedProcess(['fixture'], 0, '2.1.249 (Claude Code)\n', '')
        with patch('manager.capabilities.shutil.which', return_value='/fixture/claude'), \
                patch('manager.capabilities.subprocess.run', return_value=completed):
            older = diagnose('claude', probe=True, home=self.home, environment={})
        for name in ('model_definition_precedence', 'model_force'):
            self.assertFalse(next(item for item in older['documented_capabilities'] if item['name'] == name)['version_meets_minimum'])
        with patch('manager.capabilities.shutil.which', return_value=None):
            self.assertEqual('not_found', diagnose('antigravity', probe=True, home=self.home, environment={})['client']['status'])
        with patch('manager.capabilities.shutil.which', return_value='/fixture/claude'), \
                patch('manager.capabilities.subprocess.run', side_effect=subprocess.TimeoutExpired('SECRET', 3)):
            self.assertEqual('timeout', diagnose('claude', probe=True, home=self.home, environment={})['client']['status'])

    def test_cli_effective_roles_and_doctor_keep_configured_values_and_files(self):
        project = self.home / 'project'
        role = self.write('project/.claude/agents/xy-backend.md',
                         '---\nname: xy-backend\nmodel: opus\neffort: high\nautoCompactWindow: 200000\n---\nfixture\n')
        self.write('.claude/settings.json', {'env': {'CLAUDE_CODE_EFFORT_LEVEL': 'max'}})
        before = role.read_bytes()
        output = io.StringIO()
        with patch('pathlib.Path.home', return_value=self.home), patch.dict(os.environ, {}, clear=True), redirect_stdout(output):
            self.assertEqual(0, cli_main(['roles', '--project', str(project), '--platform', 'claude', '--effective']))
        self.assertEqual({}, json.loads(output.getvalue()))
        self.assertEqual(service.native_settings(before, 'claude'), {'model': 'opus', 'effort': 'high'})
        self.assertEqual(before, role.read_bytes())
        output = io.StringIO()
        with patch('pathlib.Path.home', return_value=self.home), patch.dict(os.environ, {}, clear=True), redirect_stdout(output):
            self.assertEqual(0, cli_main(['doctor']))
        self.assertEqual(3, len(json.loads(output.getvalue())))
        self.assertFalse((self.home / '.config/agent-workflow').exists())


class TransactionTest(TemporaryProject):
    central_fixture = True

    def declare_restore_fixture_effort(self):
        """只修恢复用例的人工基线：native high 必须有明确项目来源。

        既有轻量事务 fixture 手工生成 high；真实中央角色缺省为 inherit。
        恢复守卫不能为这份人工数据新增兼容分支，因此仅需要正常恢复的四例
        声明对应 effort，其他用例和共享 fixture 的原始边界保持不动。
        """
        path = self.project / '.agent-workflow/project.yaml'
        self.write('.agent-workflow/project.yaml', role_models.update(path.read_text(),
                   {'codex': {'xy-backend': {'effort': 'high'}}}))

    def test_invalid_model_config_does_not_echo_adapter_secrets(self):
        self.write('.agent-workflow/project.yaml','project_name: test\nrole_models:\n  PRIVATE-ADAPTER-SECRET\n')
        with self.assertRaisesRegex(ValueError,'未显示配置原文') as raised:
            self.prepare()
        self.assertNotIn('PRIVATE-ADAPTER-SECRET',str(raised.exception));self.assertEqual([],service.backups(self.state,self.project))

    def test_deep_json_source_keeps_all_project_and_host_drafts(self):
        home=self.root/'home';rejected=deep_json_source(home,'codex')
        env={'HOME':str(home),'CODEX_HOME':str(home/'.codex'),'CLAUDE_CONFIG_DIR':str(home/'.claude')}
        with patch.dict(os.environ,env,clear=True):
            app=App(self.state,self.root,self.project)
            keys=(app.scope(),(str(self.root/'other-project'),'codex','xy-qa'),(str(self.project),'claude','xy-qa'))
            for key in keys:
                app.drafts[key]=dict(self.value);app.expected[key]={'model':'inherit','effort':'high'};app.source_stamps[key]='original-stamp'
            drafts={key:dict(value) for key,value in app.drafts.items()}
            expected={key:dict(value) for key,value in app.expected.items()};stamps=dict(app.source_stamps)
            # 走真实 dispatch→来源页→discover，确认来源失败不会逃出事件边界或丢掉其他范围草稿。
            app.dispatch('g');app.index=next(i for i,(_,action) in enumerate(app.options()) if action == 'sources');app.dispatch('enter')
            self.assertEqual(app.modal,'sources');self.assertFalse(app.done)
            if rejected:self.assertIn('模型来源读取失败',app.text)
            self.assertNotIn('DEEP-SOURCE-SECRET',app.text)
            self.assertEqual(app.drafts,drafts);self.assertEqual(app.expected,expected);self.assertEqual(app.source_stamps,stamps)
        self.assertEqual([],service.backups(self.state,self.project))

    def test_tui_restore_confirmation_keeps_original_version_guard(self):
        """实际走 TUI 的恢复确认回调，防止容器转换把 RestorePlan 的保护丢掉。"""
        self.declare_restore_fixture_effort()
        changes=self.prepare();path=self.project/changes[0].relative
        with path.open('r+b') as editor:
            identifier=service.commit(self.state,self.project,changes)
            app=App(self.state,self.root,self.project)
            app.changes=service.prepare_restore(self.state,self.project,identifier);app.modal='restore'
            editor.seek(0);editor.write(b'SAVE BEFORE TUI CONFIRM');editor.truncate();editor.flush()
            with ThreadPoolExecutor(max_workers=1) as executor,patch('manager.cli.check_changed_hosts') as verify:
                app.executor=executor;app.confirm()
                with self.assertRaisesRegex(ValueError,'后续保存'):app.future.result(timeout=5)
                app.poll_job();self.assertEqual(app.modal,'error');verify.assert_not_called()
            self.assertEqual(path.read_bytes(),changes[0].after)

    def test_restore_rechecks_original_version_before_write_and_after_verification(self):
        """预览后及验收期间的旧 fd 保存都须拒绝恢复，并保持当前已应用配置。"""
        self.declare_restore_fixture_effort()
        changes=self.prepare();path=self.project/changes[0].relative
        with path.open('r+b') as editor:
            identifier=service.commit(self.state,self.project,changes)
            plan=service.prepare_restore(self.state,self.project,identifier)
            def save():editor.seek(0);editor.write(b'SAVE AFTER PREVIEW');editor.truncate();editor.flush()
            save()
            with self.assertRaisesRegex(ValueError,'后续保存'):service.commit(self.state,self.project,plan)
            self.assertEqual(path.read_bytes(),changes[0].after)
            self.assertEqual(len(service.backups(self.state,self.project)),1)
            editor.seek(0);editor.write(changes[0].before);editor.truncate();editor.flush()
            plan=service.prepare_restore(self.state,self.project,identifier)
            with self.assertRaisesRegex(ValueError,'保留版本'):service.commit(self.state,self.project,plan,save)
            self.assertEqual(path.read_bytes(),changes[0].after)
            self.assertTrue(any(row['status'] == 'conflict' for row in service.backups(self.state,self.project)))

    def test_cancel_after_archive_rename_keeps_conflict_index_and_contents(self):
        changes=self.prepare();path=self.project/changes[0].relative;original=os.rename;fired=[]
        with path.open('r+b') as editor:
            def cancel(source,target,*args,**kwargs):
                result=original(source,target,*args,**kwargs)
                if str(source).startswith('.workflow-models-previous-') and not fired:
                    fired.append(True);editor.seek(0);editor.write(b'SAVE BEFORE CANCEL');editor.truncate();editor.flush()
                    raise KeyboardInterrupt()
                return result
            with patch('manager.service.os.rename',side_effect=cancel),self.assertRaisesRegex(ValueError,'备份 .*保留版本'):
                service.commit(self.state,self.project,changes)
        record=service.backups(self.state,self.project)[0]
        self.assertEqual(record['status'],'conflict')
        self.assertTrue(any((self.project/row['path']).read_bytes() == b'SAVE BEFORE CANCEL' for row in record['previous_files']))
        self.assertTrue(any(Path(row).read_bytes() == b'SAVE BEFORE CANCEL' for row in record['retained_files']))
        self.assertEqual(path.read_bytes(),changes[0].before)

    def test_capacity_is_reserved_before_project_mutation(self):
        """真实快照接近上限时，后续索引空间不足必须在写项目之前拒绝。"""
        self.declare_restore_fixture_effort()
        changes=self.prepare();initial=service.record_payload
        sizes=[]
        def observe(record):sizes.append((len(json.dumps(record,ensure_ascii=False,indent=2).encode())+1,bool(record.get('previous_files'))));return initial(record)
        with patch('manager.service.record_payload',side_effect=observe):identifier=service.commit(self.state,self.project,changes)
        base=next(size for size,versions in sizes if not versions)
        # 通过当前正式恢复同步原生 expected 收据；手写旧字节会被中央归属正确拒绝。
        service.commit(self.state,self.project,service.prepare_restore(self.state,self.project,identifier))
        count=len(service.backups(self.state,self.project));directories=list(self.project.glob('.agent-workflow-backup-models-*'))
        with patch.object(service,'MAX_RECORD_BYTES',base+100),self.assertRaisesRegex(ValueError,'有界读取'):
            service.commit(self.state,self.project,changes)
        self.assertEqual(len(service.backups(self.state,self.project)),count)
        self.assertEqual(list(self.project.glob('.agent-workflow-backup-models-*')),directories)
        for row in changes:self.assertEqual((self.project/row.relative).read_bytes(),row.before)

    def test_failed_error_log_keeps_original_failure_and_retained_paths(self):
        changes=self.prepare();original=state_files.write_state;calls=[]
        def broken(*args):
            calls.append(True)
            if len(calls)>1:raise OSError('DISK FULL FIXTURE')
            return original(*args)
        def fail():raise ValueError('ORIGINAL VERIFY FAILURE')
        with patch('manager.state_files.write_state',side_effect=broken),self.assertRaises(ValueError) as result:
            service.commit(self.state,self.project,changes,fail)
        message=str(result.exception)
        self.assertIn('ORIGINAL VERIFY FAILURE',message);self.assertIn('DISK FULL FIXTURE',message)
        self.assertIn('备份 ',message)
        for directory in self.project.glob('.agent-workflow-backup-models-*'):
            for path in directory.iterdir():self.assertIn(str(path),message)
        for row in changes:self.assertEqual((self.project/row.relative).read_bytes(),row.before)

    def test_bad_backup_shapes_are_isolated_and_keep_ui_drafts(self):
        identifier=service.commit(self.state,self.project,self.prepare())
        directory=service._backup_path(self.state,self.project);bad='20261029T000000Z-12345678'
        good=json.loads((directory/(identifier+'.json')).read_text())
        variants=[[],{**good,'status':[]},{**good,'files':[[]]},
                  {**good,'previous_files':[{'source':[],'path':'bad'}]},
                  {**good,'retained_files':{}},{**good,'previous_files':[]},'['*2000+']'*2000]
        from manager.cli import main
        for value in variants:
            with self.subTest(value=value):
                (directory/(bad+'.json')).write_text(value if isinstance(value,str) else json.dumps(value))
                rows=service.backups(self.state,self.project)
                self.assertEqual(len(rows),2);self.assertEqual(next(row for row in rows if row['id'] == bad)['status'],'invalid')
                with self.assertRaises(ValueError):service.prepare_restore(self.state,self.project,bad)
                app=App(self.state,self.root,self.project);app.drafts[app.scope()]={'model':'inherit','effort':'inherit'}
                app.dispatch('g');app.index=next(i for i,(_,action) in enumerate(app.options()) if action == 'backups');app.dispatch('enter')
                self.assertEqual(app.modal,'backups');self.assertTrue(app.drafts)
                app.index=next(i for i,row in enumerate(app.backup_rows) if row['id'] == bad);app.dispatch('enter')
                self.assertEqual(app.modal,'backups');self.assertTrue(app.drafts);self.assertIn('格式无效',app.toast)
                with redirect_stdout(io.StringIO()),redirect_stderr(io.StringIO()):
                    self.assertEqual(main(['--state-dir',str(self.state),'backups','--project',str(self.project)]),0)
                    self.assertEqual(main(['--state-dir',str(self.state),'restore','--project',str(self.project),bad]),2)

    def test_backup_summary_removes_terminal_controls_but_keeps_lines(self):
        summary=service.backup_summary(self.project/'\x1b]52;c;CONTROL\x07','20261029T000000Z-12345678')
        self.assertNotIn('\x1b',summary);self.assertNotIn('\x07',summary);self.assertEqual(summary.count('\n'),2)

    def test_failed_inode_archival_records_its_original_path(self):
        changes=self.prepare();original=os.rename;triggered=[]
        def fail(source,target,*args,**kwargs):
            if str(source).startswith('.workflow-models-previous-') and str(target).endswith('.toml') and not triggered:
                triggered.append(True);raise OSError('simulated archive failure')
            return original(source,target,*args,**kwargs)
        with patch('manager.service.os.rename',side_effect=fail),self.assertRaisesRegex(ValueError,'保留版本'):
            service.commit(self.state,self.project,changes)
        backup=service.backups(self.state,self.project)[0]
        self.assertEqual(backup['status'],'conflict');self.assertTrue(backup['retained_files'])
        self.assertEqual(Path(backup['retained_files'][0]).read_bytes(),changes[0].before)

    def test_held_old_fd_save_is_a_logged_conflict(self):
        changes=self.prepare();path=self.project/changes[0].relative;original=os.link;triggered=[]
        with path.open('r+b') as editor:
            def save(source,target,*args,**kwargs):
                if target == path.name and not triggered:
                    editor.seek(0);editor.write(b'CONCURRENT OLD FD SAVE');editor.truncate();editor.flush();triggered.append(True)
                return original(source,target,*args,**kwargs)
            with patch('manager.state_files.os.link',side_effect=save),self.assertRaisesRegex(ValueError,'保留版本'):
                service.commit(self.state,self.project,changes)
        backup=service.backups(self.state,self.project)[0]
        self.assertEqual(backup['status'],'conflict');self.assertTrue(backup['retained_files'])
        self.assertEqual(Path(backup['retained_files'][0]).read_bytes(),b'CONCURRENT OLD FD SAVE')
        self.assertEqual(path.read_bytes(),changes[0].before)

    def test_late_old_fd_save_keeps_a_permanent_reported_path(self):
        changes=self.prepare();path=self.project/changes[0].relative
        with path.open('r+b') as editor:
            identifier=service.commit(self.state,self.project,changes)
            editor.seek(0);editor.write(b'LATE SAVE');editor.truncate();editor.flush()
        backup=service.backups(self.state,self.project)[0]
        versions=[self.project/row['path'] for row in backup['previous_files']]
        self.assertTrue(any(version.read_bytes() == b'LATE SAVE' for version in versions))
        self.assertEqual(path.read_bytes(),changes[0].after)
        with self.assertRaisesRegex(ValueError,'后续保存'):service.prepare_restore(self.state,self.project,identifier)

    def test_source_guard_stops_before_any_project_write(self):
        changes=self.prepare();catalog=Catalog('codex',self.catalog.models,stamp='selected')
        with patch('manager.service.discover',return_value=Catalog('codex',stamp='changed')):
            with self.assertRaisesRegex(ValueError,'来源'):
                service.commit(self.state,self.project,changes,before_write=lambda:service.ensure_source(catalog,self.project))
        for row in changes:self.assertEqual((self.project/row.relative).read_bytes(),row.before)
        self.assertEqual(service.backups(self.state,self.project),[])

    def test_role_directory_stays_inside_ui_error_boundary(self):
        app=App(self.state,self.root,self.project)
        outside=self.root/'outside';outside.mkdir()
        role=self.project/'.codex/agents';role.rename(self.project/'.codex/original');role.symlink_to(outside,target_is_directory=True)
        app.dispatch('r');self.assertEqual(app.role_list(),[])
        self.assertIn('符号链接',app.toast)

    def test_discard_conflicted_draft_rebuilds_only_its_baseline(self):
        app=App(self.state,self.root,self.project);app.catalogs[(str(self.project),'codex')]=self.catalog
        app.dispatch('enter');app.index=next(i for i,(_,value) in enumerate(app.options()) if value == 'local-model');app.dispatch('enter')
        app.index=next(i for i,(_,value) in enumerate(app.options()) if value == 'max');app.dispatch('enter')
        other=('another-project','codex','xy-qa');app.drafts[other]={'model':'inherit','effort':'inherit'}
        # 模拟另一管理器的合法并发保存：更新适配器和中央收据后，丢弃旧草稿
        # 才能基于新来源编辑。裸改受管正文不能靠丢弃草稿自动获得认领权。
        concurrent=service.prepare(self.project,'codex',{'xy-backend':{'effort':'high'}},self.catalog,state=self.state)
        service.commit(self.state,self.project,concurrent)
        app.dispatch('s');self.assertIn('来源或配置',app.toast)
        app.dispatch('r');app.dispatch('u');self.assertIn(other,app.drafts);self.assertFalse(app.pending())
        app.catalogs[(str(self.project),'codex')]=self.catalog
        app.dispatch('enter');self.assertEqual(app.expected[app.scope()]['effort'],'high')
        self.assertEqual(app.expected[app.scope()]['sources']['effort'],'project')
        app.index=next(i for i,(_,value) in enumerate(app.options()) if value == 'local-model');app.dispatch('enter')
        app.index=next(i for i,(_,value) in enumerate(app.options()) if value == 'max');app.dispatch('enter');app.dispatch('s')
        self.assertEqual(app.modal,'preview')

    def test_stale_source_draft_requires_reselection_before_preview(self):
        app=App(self.state,self.root,self.project)
        first=Catalog('codex',self.catalog.models,stamp='first');second=Catalog('codex',self.catalog.models,stamp='second')
        app.catalogs[(str(self.project),'codex')]=first
        # 显式编辑现在也复核来源，整个交互均使用本测试的来源提供者，
        # 不能让虚拟stamp的首次复核落到开发机真实宿主目录。
        current={'catalog':first}
        with patch('manager.tui.discover',side_effect=lambda *args,**kwargs:current['catalog']), \
                patch('manager.model_preferences.discover',side_effect=lambda *args,**kwargs:current['catalog']):
            app.dispatch('enter');app.index=next(i for i,(_,value) in enumerate(app.options()) if value == 'local-model');app.dispatch('enter')
            app.index=next(i for i,(_,value) in enumerate(app.options()) if value == 'max');app.dispatch('enter')
            current['catalog']=second;app.dispatch('s')
            self.assertIsNone(app.modal);self.assertIn('来源',app.toast);self.assertTrue(app.pending())
            app.dispatch('s');self.assertIsNone(app.modal)
            app.dispatch('enter');app.dispatch('enter');app.dispatch('enter');app.dispatch('s')
            self.assertEqual(app.modal,'preview')

    def test_confirmation_views_scroll_without_applying(self):
        app=App(self.state,self.root,self.project)
        for modal in ('preview','restore'):
            with self.subTest(modal=modal):
                app.modal=modal;app.scroll=0;app.page_lines=6
                app.dispatch('down');self.assertEqual(app.scroll,1)
                app.dispatch('pagedown');self.assertEqual(app.scroll,7)
                app.dispatch('pageup');self.assertEqual(app.scroll,1)
                app.dispatch('up');self.assertEqual(app.scroll,0)
        self.assertEqual([],service.backups(self.state,self.project))
    def test_preview_is_read_only_then_apply_and_restore_exact_bytes(self):
        self.declare_restore_fixture_effort()
        changes=self.prepare();self.assertEqual([],service.backups(self.state,self.project))
        identifier=service.commit(self.state,self.project,changes)
        self.assertEqual(service.role_settings(self.project,'codex','xy-backend'),self.value)
        restore=service.prepare_restore(self.state,self.project,identifier)
        service.commit(self.state,self.project,restore)
        for change in changes:self.assertEqual((self.project/change.relative).read_bytes(),change.before)
        self.assertEqual(len(service.backups(self.state,self.project)),2)

    def test_failed_validation_rolls_back_config_and_agent(self):
        changes=self.prepare()
        def fail():raise ValueError('validation failed')
        with self.assertRaisesRegex(ValueError,'validation failed'):service.commit(self.state,self.project,changes,fail)
        for change in changes:self.assertEqual((self.project/change.relative).read_bytes(),change.before)
        self.assertEqual(service.backups(self.state,self.project)[0]['status'],'rolled_back')

    def test_replaced_config_does_not_block_other_file_rollback(self):
        changes=self.prepare();outside=self.root/'outside-config';outside.write_bytes(b'EXTERNAL')
        def fail():
            config=self.project/'.agent-workflow/project.yaml';config.unlink();config.symlink_to(outside)
            raise ValueError('verify failed')
        with self.assertRaisesRegex(ValueError,'并发修改|有界单链接普通文件'):service.commit(self.state,self.project,changes,fail)
        self.assertEqual((self.project/changes[0].relative).read_bytes(),changes[0].before)
        self.assertEqual(outside.read_bytes(),b'EXTERNAL')
        self.assertEqual(service.backups(self.state,self.project)[0]['status'],'conflict')

    def test_parent_swap_cannot_write_through_to_external_directory(self):
        changes=self.prepare();outside=self.root/'external-agents';outside.mkdir()
        external=outside/'xy-backend.toml';external.write_bytes(b'EXTERNAL')
        original=state_files.AnchoredFile.write;swapped=[]
        def swap(target,data,mode,expected=None):
            if target.name == 'xy-backend.toml' and not swapped:
                parent=self.project/'.codex/agents';parent.rename(self.project/'.codex/agents-original');parent.symlink_to(outside,target_is_directory=True);swapped.append(True)
            return original(target,data,mode,expected)
        def fail():raise ValueError('verify failed')
        with patch.object(state_files.AnchoredFile,'write',swap),self.assertRaisesRegex(ValueError,'verify failed|父目录在事务中被替换'):
            service.commit(self.state,self.project,changes,fail)
        self.assertEqual(external.read_bytes(),b'EXTERNAL')
        self.assertEqual((self.project/'.codex/agents-original/xy-backend.toml').read_bytes(),changes[0].before)

    def test_edit_during_temp_file_flush_is_preserved(self):
        changes=self.prepare();original=os.fsync;edited=[]
        path=self.project/changes[0].relative
        def edit(descriptor):
            original(descriptor)
            if not edited:
                path.write_bytes(b'CONCURRENT EDIT');edited.append(True)
        # 仅在角色文件的发布阶段注入并发编辑，不干扰先行备份的写入。
        real_write=state_files.AnchoredFile.write
        def write(target,data,mode,expected=None):
            if target.name == 'xy-backend.toml':
                with patch('manager.state_files.os.fsync',side_effect=edit):return real_write(target,data,mode,expected)
            return real_write(target,data,mode,expected)
        with patch.object(state_files.AnchoredFile,'write',write),self.assertRaisesRegex(ValueError,'并发修改'):
            service.commit(self.state,self.project,changes)
        self.assertEqual(path.read_bytes(),b'CONCURRENT EDIT')

    def test_last_moment_save_before_exclusive_publish_is_preserved(self):
        changes=self.prepare();original=os.link;edited=[];path=self.project/changes[0].relative
        def save(source,target,*args,**kwargs):
            if target == 'xy-backend.toml' and not edited:
                path.write_bytes(b'LAST MOMENT SAVE');edited.append(True)
            return original(source,target,*args,**kwargs)
        with patch('manager.state_files.os.link',side_effect=save),self.assertRaisesRegex(ValueError,'并发修改'):
            service.commit(self.state,self.project,changes)
        self.assertEqual(path.read_bytes(),b'LAST MOMENT SAVE')
        self.assertEqual(path.stat().st_nlink,1)
        self.assertEqual(list(path.parent.glob('.workflow-models-*.tmp')),[])

    def test_save_between_comparison_and_isolation_is_preserved(self):
        changes=self.prepare();original=os.rename;edited=[];path=self.project/changes[0].relative
        def save(source,target,*args,**kwargs):
            if source == 'xy-backend.toml' and not edited:
                path.write_bytes(b'SAVE BEFORE RENAME');edited.append(True)
            return original(source,target,*args,**kwargs)
        with patch('manager.service.os.rename',side_effect=save),self.assertRaisesRegex(ValueError,'并发修改'):
            service.commit(self.state,self.project,changes)
        self.assertEqual(path.read_bytes(),b'SAVE BEFORE RENAME')
        self.assertEqual(path.stat().st_nlink,1)
        self.assertEqual(list(path.parent.glob('.workflow-models-*.tmp')),[])

    def test_preview_apply_conflict_and_restore_conflict_preserve_other_work(self):
        changes=self.prepare();path=self.project/changes[0].relative;path.write_bytes(b'OTHER WORK')
        with self.assertRaisesRegex(ValueError,'预览后|未知编辑'):service.commit(self.state,self.project,changes)
        self.assertEqual(path.read_bytes(),b'OTHER WORK')
        path.write_bytes(changes[0].before);identifier=service.commit(self.state,self.project,changes)
        path.write_bytes(b'NEW OTHER WORK')
        with self.assertRaisesRegex(ValueError,'其他更改'):service.prepare_restore(self.state,self.project,identifier)
        self.assertEqual(path.read_bytes(),b'NEW OTHER WORK')

    def test_symlink_and_unknown_capability_fail_before_writes(self):
        outside=self.root/'outside';outside.write_bytes(b'OTHER')
        path=self.project/'.codex/agents/xy-backend.toml';path.unlink();path.symlink_to(outside)
        with self.assertRaises(ValueError):self.prepare()
        self.assertEqual(outside.read_bytes(),b'OTHER')
        with self.assertRaises(ValueError):service.validate_selection('codex',{'model':'local-model','effort':'low'},self.catalog)

    def test_project_registry_is_deduplicated_and_does_not_touch_project(self):
        # 本例只验证登记语义，使用未安装目录；旧自包含安装的删除另受原生迁移边界约束。
        self.project=self.root/'仅登记项目';self.project.mkdir()
        self.assertEqual(project_service.projects(self.state),[]);self.assertEqual([],service.backups(self.state,self.project))
        project_service.register(self.state,self.project);project_service.register(self.state,self.project)
        self.assertEqual(project_service.projects(self.state),[self.project])
        project_service.register(self.state,self.project,True);self.assertEqual(project_service.projects(self.state),[])
        self.assertNotIn(self.project,project_service.projects(self.state,self.root))
        project_service.register(self.state,self.project);self.assertIn(self.project,project_service.projects(self.state,self.root))

    def test_keyboard_stage_cancel_and_cross_project_scope(self):
        app=App(self.state,self.root,self.project)
        app.catalogs[(str(self.project),'codex')]=self.catalog
        # 选择按业务值定位；新增“跟随全局”与“继承宿主”后不能让固定行号
        # 把 max 测成 high，或在只改模型时顺带添加推理覆盖。
        app.dispatch('enter');app.index=next(i for i,(_,value) in enumerate(app.options()) if value == 'local-model');app.dispatch('enter')
        app.index=next(i for i,(_,value) in enumerate(app.options()) if value == 'max');app.dispatch('enter')
        self.assertEqual(app.pending(),{'xy-backend':self.value})
        app.dispatch('enter');app.dispatch('esc');self.assertEqual(app.pending(),{'xy-backend':self.value})
        app.dispatch('r');app.catalogs[(str(self.project),'codex')]=self.catalog
        app.dispatch('enter');app.dispatch('esc')
        app.dispatch('2');self.assertEqual(app.pending(),{});app.dispatch('1');self.assertEqual(len(app.pending()),1)
        app.dispatch('g');self.assertEqual(app.modal,'manage');app.dispatch('esc');self.assertIsNone(app.modal)

    def test_edit_baseline_detects_concurrent_role_change(self):
        app=App(self.state,self.root,self.project);app.catalogs[(str(self.project),'codex')]=self.catalog
        app.dispatch('enter')
        self.write('.codex/agents/xy-backend.toml',codex_agent(effort='medium'))
        app.dispatch('down');app.dispatch('enter');app.dispatch('down');app.dispatch('down');app.dispatch('enter');app.dispatch('s')
        self.assertIn('来源或配置',app.toast);self.assertIsNone(app.modal)
        self.assertEqual((self.project/'.codex/agents/xy-backend.toml').read_bytes(),codex_agent(effort='medium'))

    def test_unicode_cells_are_bounded(self):
        self.assertEqual(cell_width('中文A'),5);self.assertEqual(clip('中文A',4),'中文')


class AddInstallTest(TemporaryProject):
    """旧添加入口改为登记方式与条件预览；只操作临时目录。"""
    def settle(self,app):
        app.future.result(timeout=5);app.poll_job()

    def test_trailing_space_directory_is_not_replaced_by_trimmed_sibling(self):
        sibling=self.root/'Project';sibling.mkdir();target=self.root/'Project ';target.mkdir()
        # 原样、带引号和反斜杠拖入都必须保留目录名末尾的空格，不能选中已存在的同名邻居。
        escaped=str(target).replace('\\','\\\\').replace(' ','\\ ')
        for raw in (str(target),shlex.quote(str(target)),escaped):
            with self.subTest(raw=raw):
                app=App(self.state,self.root,self.project)
                app.dispatch('a');app.input=raw;app.dispatch('enter')
                self.assertEqual(app.modal,'add_mode');self.assertEqual(app.add_target,target)
                self.assertEqual(app.index,0);self.assertIsNone(app.future)
        self.assertFalse(self.state.exists())

    def test_empty_list_and_project_list_both_offer_registration_entry(self):
        app=App(self.state,self.root/'empty-scan')
        self.assertEqual(app.pane,'projects');self.assertIsNone(app.project)
        with patch.object(project_service,'apply_project') as apply:
            # 空列表仍先选中固定全局入口；向下选中可见登记项后 Enter，不能把全局当登记。
            app.dispatch('down');app.dispatch('enter');self.assertEqual(app.modal,'add')
            self.assertIn('登记',app.bindings()[0].label)
            app.dispatch('esc');apply.assert_not_called()
        self.assertFalse(self.state.exists())
        app=App(self.state,self.root,self.project);app.dispatch('left');app.dispatch('down')
        self.assertIsNone(app.project);app.dispatch('enter');self.assertEqual(app.modal,'add')

    def test_dragged_path_registers_after_preview_and_keeps_other_drafts(self):
        target=self.root/"新项目's $(literal)";target.mkdir()
        app=App(self.state,self.root,self.project);key=app.scope()
        app.drafts[key]=dict(self.value);app.expected[key]={'model':'inherit','effort':'high'}
        other_key=(str(self.project),'codex');app.catalogs[other_key]=self.catalog
        with ThreadPoolExecutor(max_workers=1) as executor:
            app.executor=executor;app.dispatch('a');app.input=shlex.quote(str(target));app.dispatch('enter')
            self.assertEqual(app.modal,'add_mode');self.assertEqual(app.index,0)
            app.dispatch('enter');self.settle(app)
            self.assertEqual(app.modal,'project_plan');self.assertFalse(self.state.exists())
            self.assertFalse((target/'.agent-workflow').exists())
            app.dispatch('enter');app.dispatch('enter');app.dispatch('a');self.settle(app)
        self.assertEqual(app.project,target);self.assertEqual(app.pane,'projects');self.assertEqual(app.modal,'result')
        self.assertEqual(app.role_list(),[]);self.assertEqual(app.drafts[key],self.value)
        self.assertIs(app.catalogs[other_key],self.catalog);self.assertIn(target,project_service.projects(self.state))
        self.assertEqual(app.projects.count(target),1)

    def test_invalid_input_stays_editable_without_starting_apply(self):
        app=App(self.state,self.root,self.project)
        # 空输入、多目录以及源包本身/子目录/包含源包的父目录均不得触发安装或状态写入。
        for value in ('',' \t',str(self.root/'missing'),"'unclosed",shlex.quote(str(self.root))+' '+shlex.quote(str(self.project)),
                      str(PACK),str(PACK/'manager'),str(PACK.parent)):
            with self.subTest(value=value),patch.object(project_service,'apply_project') as apply:
                app.dispatch('a');app.input=value;app.dispatch('enter')
                self.assertEqual(app.modal,'add');self.assertIsNone(app.future);apply.assert_not_called()
        self.assertFalse(self.state.exists())

    def test_apply_failure_keeps_project_list_and_drafts(self):
        target=self.root/'failed-project';target.mkdir()
        app=App(self.state,self.root,self.project);key=app.scope();app.drafts[key]=dict(self.value)
        with ThreadPoolExecutor(max_workers=1) as executor,patch.object(project_service,'apply_project',side_effect=ValueError('fixture update unfinished')):
            app.executor=executor;app.dispatch('a');app.input=str(target);app.dispatch('enter')
            app.dispatch('enter');self.settle(app);self.assertEqual(app.modal,'project_plan')
            app.dispatch('enter')
            with self.assertRaisesRegex(ValueError,'update unfinished'):app.future.result(timeout=5)
            app.poll_job()
        self.assertEqual(app.modal,'error');self.assertIn('update unfinished',app.text)
        self.assertEqual(app.project,self.project);self.assertNotIn(target,app.projects)
        self.assertNotIn(target,project_service.projects(self.state));self.assertEqual(app.drafts[key],self.value)
        with state_files.lock(self.state,str(target)):pass

    def test_adding_existing_project_registers_without_enable_or_duplicates(self):
        app=App(self.state,self.root,self.project)
        before=(self.project/'.codex/agents/xy-backend.toml').read_bytes()
        with ThreadPoolExecutor(max_workers=1) as executor:
            app.executor=executor;app.dispatch('a');app.input=str(self.project);app.dispatch('enter')
            app.dispatch('enter');self.settle(app);app.dispatch('enter');self.settle(app)
        self.assertEqual(app.projects.count(self.project),1)
        self.assertEqual(project_service.projects(self.state),[self.project]);self.assertEqual(app.modal,'result')
        self.assertEqual(before,(self.project/'.codex/agents/xy-backend.toml').read_bytes())


class InstalledProjectIntegrationTest(unittest.TestCase):
    """同一最小核心覆盖真实 TUI 启用、三宿主模型事务与 CLI 切版保留。"""
    def test_three_platform_configuration_survives_upgrade(self):
        with tempfile.TemporaryDirectory(prefix='workflow-manager-integration-') as raw:
            root=Path(raw).resolve();project=root/'backend';project.mkdir();state=root/'state'
            (project/'pyproject.toml').write_text('[project]\nname="example"\nversion="0.1.0"\n')
            source=CentralCliIntegrationTest.create_source(root)
            # 添加先选择“登记并启用”，读取预览后再确认；两次作业均消费正式共享服务。
            from lib import runtime_store
            core=runtime_store.import_core(source,state);select_fixture_current(state,core.binding())
            app=App(state,root)
            with ThreadPoolExecutor(max_workers=1) as executor,patch.object(project_service,'SOURCE',source):
                # 初始无项目时全局默认已占首项；直接用正式 a 键进入登记。
                app.executor=executor;app.dispatch('a');app.input=str(project);app.dispatch('enter')
                self.assertEqual(app.modal,'add_mode');app.index=1;app.dispatch('enter')
                app.future.result(timeout=30);app.poll_job();self.assertEqual(app.modal,'project_plan')
                self.assertFalse((project/'.agent-workflow').exists());app.dispatch('enter');app.future.result(timeout=30);app.poll_job()
            self.assertEqual(app.modal,'result');self.assertEqual(app.project,project);self.assertEqual(app.pane,'roles')
            for host in service.LOCATIONS:self.assertTrue(service.roles(project,host,state=state))
            for host,model,effort in [('codex','fixture-model','max'),('claude','fixture/model','inherit'),('antigravity','pro','inherit')]:
                catalog=Catalog(host,[Model(model,model,'fixture',('max',))])
                changes=service.prepare(project,host,{'xy-backend':{'model':model,'effort':effort}},catalog,state=state)
                service.commit(state,project,changes,lambda host=host:service.check(project,host,state=state))
                self.assertEqual(service.role_settings(project,host,'xy-backend'),{'model':model,'effort':effort})
            inherit=Catalog('codex',[Model('inherit','继承','fixture')])
            changes=service.prepare(project,'codex',{'xy-backend':{'model':'inherit','effort':'inherit'}},inherit,state=state)
            identifier=service.commit(state,project,changes,lambda:service.check(project,'codex',state=state))
            service.commit(state,project,service.prepare_restore(state,project,identifier),lambda:service.check(project,'codex',state=state))
            (source/'product/WORKFLOW.md').write_text('# 新固定版本\n',encoding='utf-8')
            environment={**os.environ,'HOME':str(root/'home'),'AGENT_WORKFLOW_PYTHON':sys.executable}
            result=subprocess.run(['bash',str(PACK/'workflow.sh'),'--state-dir',str(state),'--host-home',str(root/'home'),'open',str(project),
                                   '--source',str(source)],env=environment,capture_output=True,text=True,timeout=30)
            self.assertEqual(result.returncode,0,result.stdout[-3500:]+result.stderr[-3500:])
            self.assertEqual(service.role_settings(project,'codex','xy-backend')['effort'],'max')
            self.assertEqual(service.role_settings(project,'claude','xy-backend')['model'],'fixture/model')
            self.assertEqual(service.role_settings(project,'antigravity','xy-backend')['model'],'pro')


class InstallerBoundaryTest(unittest.TestCase):
    """用真实事务和真实进程组验证停止、目录切换及恢复，不安装到真实项目。"""
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='workflow-installer-boundary-')
        self.root=Path(self.temp.name).resolve();self.project=self.root/'project';self.project.mkdir()
        self.late=self.root/'late-write'

    def tearDown(self):self.temp.cleanup()


    def test_runner_cancel_stops_real_child_group(self):
        original=subprocess.Popen.wait;interrupted=[]
        def wait(process,*args,**kwargs):
            if not interrupted:interrupted.append(True);raise KeyboardInterrupt()
            return original(process,*args,**kwargs)
        command=[os.sys.executable,'-c',f'import time;from pathlib import Path;time.sleep(.5);Path({str(self.late)!r}).write_text("late")']
        with patch.object(subprocess.Popen,'wait',wait),self.assertRaisesRegex(SetupRunError,'取消'):
            SetupRunner().run(command,self.project)
        time.sleep(.55);self.assertFalse(self.late.exists())


class CentralCliIntegrationTest(unittest.TestCase):
    """通过真实 workflow.sh 验证统一服务；只构造协议所需的最小核心。

    两个固定版本共用一次可控来源，不复制整仓候选，也不读取用户账户配置。
    每例物理项目独立，但内容库与只读核心在本类内复用，避免反复导入变化中的源码。
    """
    @classmethod
    def setUpClass(cls):
        from lib import runtime_store
        cls.temporary=tempfile.TemporaryDirectory(prefix="central-cli-test-")
        cls.root=Path(cls.temporary.name).resolve();cls.source=cls.create_source(cls.root)
        cls.state=cls.root/"state";cls.scan=cls.root/"scan";cls.scan.mkdir()
        cls.first=runtime_store.import_core(cls.source,cls.state)
        cls.put(cls.source,"product/WORKFLOW.md","# 固定版本二\n".encode())
        cls.second=runtime_store.import_core(cls.source,cls.state)
        select_fixture_current(cls.state,cls.first.binding())

    @classmethod
    def create_source(cls,root):
        """旧三宿主集成测试也复用相同最小来源，避免其再次整仓导入。"""
        from lib import runtime_store
        source=root/"source"
        for directory in runtime_store.CORE_DIRECTORIES:(source/directory).mkdir(parents=True)
        for relative in runtime_store.SETUP_FILES:cls.put(source,relative,b"#!/bin/sh\nexit 0\n")
        # 真实薄桥和 context_read 的直接依赖显式列出；其余产品文件用最小夹具。
        selected=("lib/__init__.py", "lib/install/__init__.py", "lib/central/__init__.py", "lib/hosts/__init__.py", "lib/skills/__init__.py", "lib/documents/__init__.py", "lib/install/project_paths.py", "lib/install/install_process.py", "lib/install/windows_process.py", "lib/platform_fs.py","lib/runtime_store.py","lib/central/runtime_project.py","lib/hosts/native_context.py","lib/hosts/native_agents.py","manager/native_agents.py","lib/runtime_bridge.py",
                  "lib/runtime_pins.py","lib/standard_paths.py","lib/hosts/claude_instructions.py","lib/documents/context_read.py",
                  "lib/skills/shared_core_skills.py","lib/python_runtime.sh","lib/role_models.py","lib/central/role_preferences.py","lib/hosts/claude_options.py",
                  "lib/validate_antigravity_artifacts.py","lib/hosts/workflow_hook_install.py","lib/hosts/workflow_hook_settings.py",
                  "lib/workflow_hooks.py","lib/hosts/windows_hook_command.py","lib/hosts/merge_codex_config.py","manager/project_service.py", "manager/state_files.py", "manager/runtime_service.py","manager/runtime_state.py","manager/runtime_policy.py","manager/central_runtime.py","manager/runtime_lifecycle.py","manager/__init__.py",
                  "templates/project.yaml.example","templates/docs/PROJECT.md","platforms/shared/core-skills.txt")
        for relative in selected:cls.put(source,relative,(PACK/relative).read_bytes())
        for role in role_models.ROLES:cls.put(source,f"roles/{role}.md",(PACK/f"roles/{role}.md").read_bytes())
        for name in (PACK/"platforms/shared/core-skills.txt").read_text().splitlines():
            if name and not name.startswith("#"):
                cls.put(source,f"platforms/shared/skills/{name}/SKILL.md",
                        f"---\nname: {name}\ndescription: fixture\n---\n<!-- agent-workflow-pack:managed-skill -->\n# {name}\n".encode())
        cls.put(source,"product/GLOBAL_CONSTRAINTS.md",b"# fixture constraints\n")
        cls.put(source,"product/WORKFLOW.md","# 固定版本一\n".encode())
        return source

    @classmethod
    def tearDownClass(cls):cls.temporary.cleanup()

    @staticmethod
    def put(root,relative,body):
        path=root/relative;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(body);return path

    def setUp(self):
        # 项目ID由项目名派生；长测试方法名并非本例要验证的ID长度边界。
        self.project=self.root/("project-"+hashlib.sha256(self._testMethodName.encode()).hexdigest()[:10]);self.project.mkdir()
        self.home=self.root/(self._testMethodName+"-home");self.home.mkdir()
        self.environment={**os.environ,"HOME":str(self.home),"CODEX_HOME":str(self.home/".codex"),
                          "CLAUDE_CONFIG_DIR":str(self.home/".claude"),"AGENT_WORKFLOW_PYTHON":sys.executable,
                          "AGENT_WORKFLOW_STATE_DIR":str(self.root/"unused-default-state"),"PYTHONDONTWRITEBYTECODE":"1"}
        # 明确的项目清单使发现器选中真实后端角色；不探测宿主或访问业务仓库。
        self.put(self.project,"pyproject.toml",b'[project]\nname="fixture"\nversion="0.1.0"\n')

    def cli(self,*args,state=None,expected=0,json_mode=True):
        command=["bash",str(PACK/"workflow.sh"),"--state-dir",str(state or self.state),"--host-home",str(self.home),"--scan-root",str(self.scan)]
        if json_mode:command.append("--json")
        command.extend(str(value) for value in args)
        result=subprocess.run(command,cwd=self.root,env=self.environment,capture_output=True,text=True,timeout=35)
        self.assertEqual(result.returncode,expected,result.stdout+result.stderr)
        self.assertEqual(result.stderr,"",result.stderr)
        return json.loads(result.stdout) if json_mode else result.stdout

    def bridge(self,*args,expected=0):
        environment={**self.environment,"AGENT_WORKFLOW_STATE_DIR":str(self.state)}
        result=subprocess.run(["bash",str(self.project/".agent-workflow/lib/python_runtime.sh"),"-B","-X","utf8",
                               str(self.project/".agent-workflow/runtime.py"),*args],cwd=self.project,env=environment,
                              capture_output=True,text=True,timeout=20)
        self.assertEqual(result.returncode,expected,result.stdout+result.stderr)
        return result

    def enable(self):
        return self.cli("add",self.project,"--enable","--content-id",self.first.content_id)["result"]

    def test_runtime_current_follow_and_platform_reset_use_real_shared_services(self):
        # 独立可变 state 只服务本例；核心源仍复用同一最小夹具，宿主根显式隔离。
        state=self.root/(self._testMethodName+"-state")
        self.cli("open",self.project,state=state,expected=2)
        installed=self.cli("runtime","install",self.source,state=state)["result"]
        self.cli("open",self.project,state=state,expected=2)
        identifier=installed["runtime_binding"]["content_id"]
        before=set(state.rglob("*"))
        preview=self.cli("runtime","activate",identifier,"--dry-run",state=state)["result"]
        self.assertTrue(preview["can_apply"]);self.assertEqual(before,set(state.rglob("*")))
        self.assertIsNone(self.cli("runtime","status",state=state)["result"]["runtime_binding"])
        activated=self.cli("runtime","activate",identifier,state=state)["result"]
        self.assertEqual(installed["runtime_binding"],activated["runtime_binding"])
        result=self.cli("add",self.project,"--enable",state=state)["result"]
        self.assertTrue(result["declared_enabled"]);self.assertTrue(result["new_task_allowed"])
        self.assertEqual("follow",result["policy"])
        effective=self.cli("roles","--project",self.project,"--platform","claude","--effective",state=state)
        self.assertIn("xy-backend",effective)
        self.assertFalse((self.project/".claude/agents/xy-backend.md").exists())
        # 显式 use 锁住旧版；中央激活只动 follow，follow 再单独清锁并物化 current。
        from lib import runtime_store
        runtime_store.import_core(self.first.root,state)
        self.cli("use",self.project,self.first.content_id,state=state)
        self.cli("runtime","activate",identifier,state=state)
        pinned=self.cli("status",self.project,state=state)["result"]
        self.assertEqual("pinned",pinned["policy"]);self.assertEqual(self.first.binding(),pinned["runtime_binding"])
        followed=self.cli("follow",self.project,state=state)["result"]
        self.assertEqual("follow",followed["policy"]);self.assertEqual(installed["runtime_binding"],followed["runtime_binding"])
        created=self.cli("set","--project",self.project,"--platform","antigravity","--role","xy-backend","--model","pro","--apply",state=state)["result"]
        arguments=("set","--project",self.project,"--platform","antigravity","--all-roles","--reset","all")
        config=self.project/".agent-workflow/project.yaml";original=config.read_bytes()
        reset=self.cli(*arguments,state=state)["result"]
        self.assertTrue(reset["all_roles"]);self.assertTrue(reset["changes"]);self.assertEqual(original,config.read_bytes())
        reset_result=self.cli(*arguments,"--apply",state=state)["result"]
        self.assertTrue(reset_result["applied"])
        sparse=self.project/".agents/agents/xy-backend.md"
        self.assertFalse(sparse.exists())
        # reset 备份还原会重新创建稀疏local；最初set备份还原则删除local。两条
        # None/create/delete都必须经正式CLI透传同一NativeContext给原生收据。
        self.cli("restore","--project",self.project,reset_result["backup_id"],"--apply",state=state)
        self.assertTrue(sparse.is_file())
        self.cli("restore","--project",self.project,created["backup_id"],"--apply",state=state)
        self.assertFalse(sparse.exists())
        noop=self.cli(*arguments,"--apply",state=state)["result"]
        self.assertFalse(noop["applied"]);self.assertIsNone(noop["backup_id"])
        self.cli("set","--global","--platform","antigravity","--all-roles","--reset","all",state=state,expected=2)
        self.cli(*arguments,"--role","xy-backend",state=state,expected=2)
        self.cli("runtime","recover",state=state,expected=2)
        self.cli("close",self.project,state=state)
        self.cli("runtime","activate",self.first.content_id,state=state)
        disabled=self.cli("status",self.project,state=state)["result"]
        self.assertFalse(disabled["declared_enabled"]);self.assertFalse(disabled["new_task_allowed"])
        self.assertEqual(self.first.binding(),disabled["effective_binding"])
        self.assertEqual(installed["runtime_binding"],disabled["runtime_binding"])
        rolled=self.cli("runtime","rollback",state=state)["result"]
        self.assertEqual(installed["runtime_binding"],rolled["runtime_binding"])

    def test_runtime_cleanup_preview_apply_pins_and_interruption_recovery(self):
        state=self.root/(self._testMethodName+"-state")
        archives=self.root/".sync-backups";archives.mkdir(exist_ok=True)
        roots=[archives/(self._testMethodName+suffix) for suffix in ("-one","-two")]
        for root in roots:root.mkdir();(root/"old.txt").write_bytes(b"explicit historical fixture")
        # cleanup不需要宿主身份；从真实脚本入口验证custom state仍不猜HOME，
        # 缺少state的默认预览和显式dry-run都不能建立锁、journal或内容库。
        command=["bash",str(PACK/"workflow.sh"),"--state-dir",str(state),"--json","runtime","cleanup"]
        for options in ([],["--dry-run"]):
            result=subprocess.run(command+options,cwd=self.root,env=self.environment,capture_output=True,text=True,timeout=20)
            self.assertEqual(0,result.returncode,result.stdout+result.stderr)
            self.assertTrue(json.loads(result.stdout)["dry_run"]);self.assertFalse(state.exists())
        invalid=(("--apply","--dry-run"),("--recover","--backups-only"),
                 ("--recover","--approved-backup-root",roots[0]),("--recover","--task-record",self.root/"not-a-task.json"))
        for options in invalid:
            self.cli("runtime","cleanup",*options,state=state,expected=2)
            self.assertFalse(state.exists())
        self.cli("runtime","install",self.first.root,state=state)
        self.cli("runtime","install",self.second.root,state=state)
        pin=self.root/(self._testMethodName+"-task.json")
        pin.write_text(json.dumps({"schema_version":2,"runtime_binding":self.first.binding()}),encoding="utf-8")
        arguments=("runtime","cleanup","--approved-backup-root",roots[0],"--approved-backup-root",roots[1],
                   "--task-record",pin,"--backups-only")
        def snapshot(root):
            return {str(path.relative_to(root)):(path.lstat().st_ino,path.lstat().st_mode,path.lstat().st_mtime_ns,
                     path.read_bytes() if path.is_file() else None) for path in (root,*root.rglob("*"))}
        before=snapshot(state);archive_before=[snapshot(root) for root in roots]
        preview=self.cli(*arguments,state=state)
        self.assertTrue(preview["dry_run"]);self.assertEqual([],preview["result"]["cores"])
        self.assertEqual(set(map(str,roots)),set(preview["result"]["approved_archives"]))
        self.assertEqual(before,snapshot(state));self.assertEqual(archive_before,[snapshot(root) for root in roots])
        applied=self.cli(*arguments,"--apply",state=state)["result"]
        self.assertEqual(2,applied["archives_removed"]);self.assertEqual(0,applied["cores_removed"])
        self.assertTrue(all(not root.exists() for root in roots))
        collection=self.cli("runtime","cleanup","--task-record",pin,state=state)["result"]
        self.assertEqual([self.second.content_id],collection["cores"])
        self.cli("runtime","cleanup","--task-record",pin,"--apply",state=state)
        self.assertEqual([self.first.content_id],[row["content_id"] for row in self.cli("runtime","list",state=state)["result"]])
        interrupted=archives/(self._testMethodName+"-resume");interrupted.mkdir()
        (interrupted/"resume.txt").write_bytes(b"only explicitly approved fixture")
        unlink=os.unlink
        def interrupt_after_unlink(path,*args,**kwargs):
            # 仅注入真实系统调用后的信号：服务已持久化prepared/deleting并完成
            # 一次删除，恢复必须从原journal继续；不调用或替换后端私有方法。
            result=unlink(path,*args,**kwargs)
            if path == "resume.txt":raise KeyboardInterrupt("fixture cleanup interruption")
            return result
        output=io.StringIO()
        with patch("os.unlink",side_effect=interrupt_after_unlink),redirect_stdout(output):
            code=cli_main(["--state-dir",str(state),"--json","runtime","cleanup","--backups-only",
                           "--approved-backup-root",str(interrupted),"--apply"])
        self.assertEqual(130,code);self.assertIn("cleanup --recover",json.loads(output.getvalue())["error"]["message"])
        self.assertTrue(interrupted.exists());self.assertFalse((interrupted/"resume.txt").exists())
        before=snapshot(state)
        pending=self.cli("runtime","cleanup","--recover",state=state)
        self.assertTrue(pending["dry_run"]);self.assertEqual(before,snapshot(state))
        self.assertEqual("prepared",pending["result"]["phase"])
        self.assertTrue(pending["result"]["pending"]);self.assertTrue(pending["result"]["can_recover"])
        self.assertFalse(self.cli("runtime","status",state=state)["result"]["management_write_allowed"])
        resumed=self.cli("runtime","cleanup","--recover","--apply",state=state)["result"]
        self.assertEqual("applied",resumed["phase"]);self.assertFalse(interrupted.exists())
        self.assertTrue(self.cli("runtime","status",state=state)["result"]["management_write_allowed"])
        self.assertEqual([],list(self.home.iterdir()))

    def test_custom_state_requires_host_home_and_explicit_home_ignores_root_overrides(self):
        state=self.root/(self._testMethodName+"-state")
        result=subprocess.run(["bash",str(PACK/"workflow.sh"),"--state-dir",str(state),"--json","models","--platform","codex"],
                              cwd=self.root,env=self.environment,capture_output=True,text=True,timeout=15)
        self.assertEqual(2,result.returncode);self.assertFalse(state.exists())
        self.put(self.home,".codex/config.toml",b'model_catalog_json="models.json"\n')
        self.put(self.home,".codex/models.json",b'{"models":[{"id":"explicit-home-model","display_name":"fixture"}]}')
        self.environment["CODEX_HOME"]=str(self.root/"unrelated-host")
        output=self.cli("models","--platform","codex",state=state)
        # models 保留既有目录 JSON 形状，不能用另一个环境根替换显式选择的宿主。
        self.assertIn("explicit-home-model",json.dumps(output));self.assertFalse(state.exists())

    def test_dry_run_registration_names_and_json_refusals(self):
        state=self.root/"dry-run-state"
        before=set(self.project.rglob("*"))
        preview=self.cli("add",self.project,"--dry-run",state=state)
        self.assertTrue(preview["dry_run"]);self.assertTrue(preview["result"]["registered_after"])
        self.assertFalse(state.exists());self.assertEqual(set(self.project.rglob("*")),before)
        imported=self.cli("runtime","install",self.source,"--dry-run",state=state)
        self.assertEqual(imported["result"]["runtime_binding"],self.second.binding());self.assertFalse(state.exists())
        enabled=self.cli("open",self.project,"--source",self.source,"--dry-run",state=state)
        self.assertEqual(enabled["result"]["runtime_action"],"enable");self.assertTrue(enabled["result"]["changes"])
        self.assertFalse(state.exists());self.assertEqual(set(self.project.rglob("*")),before)
        self.cli("add",self.project)
        status=self.cli("status",self.project.name)["result"]
        self.assertEqual(status["state"],"unmanaged");self.assertFalse((self.project/".agent-workflow").exists())
        listed=self.cli("list")["result"]
        self.assertTrue(any(row["project"] == str(self.project) and row["registered"] for row in listed))
        current=self.cli("list")["result"];self.assertIn(str(self.project),[row["project"] for row in current])
        for arguments in (("projects", "list"), ("install", "--project", self.project),
                          ("open", self.project, "--migrate-legacy")):
            self.cli(*arguments, expected=2)
        unknown=self.cli("status","unknown-project",expected=2)
        self.assertEqual(unknown["error"]["code"],"project_resolution");self.assertIn(str(self.project),unknown["error"]["candidates"])
        alias=self.root/"nested"/self.project.name;alias.mkdir(parents=True);self.cli("add",alias)
        repeated=self.cli("del",self.project.name,expected=2)
        self.assertEqual(repeated["error"]["code"],"project_resolution");self.assertIn(str(alias),repeated["error"]["candidates"])
        refused=self.cli("status","--private-secret-do-not-echo",expected=2)
        self.assertNotIn("private-secret",json.dumps(refused))
        self.assertFalse((self.root/"unused-default-state").exists())

    def test_real_cli_versions_repair_disable_delete_and_pinned_helper(self):
        result=self.enable();self.assertTrue(result["enabled"])
        self.assertEqual(result["runtime_binding"],self.first.binding())
        self.assertEqual(set(result["hosts"]),set(service.LOCATIONS))
        versions=self.cli("runtime","list")["result"]
        self.assertEqual({row["content_id"] for row in versions},{self.first.content_id,self.second.content_id})
        imported=self.cli("runtime","install",self.source)["result"]
        self.assertEqual(imported["runtime_binding"],self.second.binding())
        upgraded=self.cli("use",self.project,self.second.content_id)["result"]
        self.assertEqual(upgraded["previous_binding"],self.first.binding())
        rolled=self.cli("rollback",self.project)["result"]
        self.assertEqual(rolled["runtime_binding"],self.first.binding())
        # 当前任务包明确携带旧 pin；真实薄桥 helper 必须使用同一自定义 state。
        task=self.put(self.project,"task.json",json.dumps({"schema_version":2,"runtime_binding":self.first.binding(),"task":{}}).encode())
        helper=["--binding",json.dumps(self.first.binding()),"helper","lib/documents/context_read.py",
                ".agent-workflow/product/WORKFLOW.md","--task-pack",str(task),"--root",str(self.project)]
        first=json.loads(self.bridge(*helper).stdout);self.assertEqual(first["text"],"# 固定版本一\n")
        self.cli("use",self.project,self.second.content_id)
        self.assertEqual(json.loads(self.bridge(*helper).stdout)["text"],first["text"])
        self.cli("close",self.project)
        self.assertEqual(json.loads(self.bridge(*helper).stdout)["text"],first["text"])
        self.bridge("check",expected=1)
        # 停用后继续用当前二版；重开不偷偷导入源码或切回旧版本。
        reopened=self.cli("open",self.project)["result"]
        self.assertEqual(reopened["runtime_binding"],self.second.binding())
        role=self.project/".codex/agents/xy-backend.toml";role.unlink()
        preview=self.cli("repair",self.project,"--dry-run")["result"]
        self.assertTrue(any(row["path"] == ".codex/agents/xy-backend.toml" for row in preview["changes"]))
        self.cli("repair",self.project);self.assertTrue(role.is_file())
        raw=role.read_bytes();role.write_bytes(raw+b"# unknown edit\n")
        refused=self.cli("del",self.project,expected=2)
        self.assertTrue(refused["error"]["conflicts"]);self.assertIn(self.project,project_service.projects(self.state))
        self.assertTrue(self.cli("status",self.project)["result"]["conflicts"])
        role.write_bytes(raw)
        deleted=self.cli("del",self.project)["result"]
        self.assertFalse(deleted["enabled"]);self.assertFalse(deleted["registered"])
        self.assertTrue(self.project.is_dir());self.assertTrue((self.project/".agent-workflow/project.yaml").is_file())
        self.assertTrue((self.project/"docs/PROJECT.md").is_file());self.assertNotIn(self.project,project_service.projects(self.state))
        self.assertEqual(json.loads(self.bridge(*helper).stdout)["text"],first["text"])

    def test_model_receipt_apply_restore_and_failure_keep_native_expected(self):
        self.enable()
        self.put(self.home,".codex/config.toml",b'model_catalog_json="models.json"\n')
        self.put(self.home,".codex/models.json",b'{"models":[{"id":"fixture-model","display_name":"fixture"}]}')
        role=self.project/".codex/agents/xy-backend.toml";original=role.read_bytes()
        arguments=("set","--project",self.project,"--platform","codex","--role","xy-backend","--model","fixture-model","--effort","max")
        preview=self.cli(*arguments);self.assertFalse(preview["result"]["applied"]);self.assertEqual(role.read_bytes(),original)
        changed=self.cli(*arguments,"--apply")["result"]
        self.assertEqual(service.role_settings(self.project,"codex","xy-backend")["model"],"fixture-model")
        self.assertFalse(self.cli("status",self.project)["result"]["conflicts"])
        self.cli("check","--project",self.project)
        restore=("restore","--project",self.project,changed["backup_id"])
        self.cli(*restore);self.assertNotEqual(role.read_bytes(),original)
        self.cli(*restore,"--apply");self.assertEqual(role.read_bytes(),original)
        self.assertFalse(self.cli("status",self.project)["result"]["conflicts"])
        catalog=Catalog("codex",[Model("fixture-model","fixture","fixture")])
        changes=service.prepare(self.project,"codex",{"xy-backend":{"model":"fixture-model","effort":"max"}},catalog,state=self.state)
        def failure():raise ValueError("fixture verification failure")
        with self.assertRaisesRegex(ValueError,"fixture verification failure"):
            service.commit(self.state,self.project,changes,failure)
        self.assertEqual(role.read_bytes(),original);self.assertFalse(project_service.project_status(self.state,self.project)["conflicts"])
        self.assertEqual(service.backups(self.state,self.project)[0]["status"],"rolled_back")
        # 工具自己的模型修改不得使下一次换版/停用被当成手改；未知正文仍须拒绝。
        service.commit(self.state,self.project,changes,lambda:service.check(self.project,"codex",state=self.state))
        self.cli("use",self.project,self.second.content_id)
        self.cli("close",self.project)
        self.cli("open",self.project)
        role.write_bytes(role.read_bytes()+b"# manual secret=DO-NOT-ECHO\n")
        rejected=self.cli(*arguments,"--apply",expected=2)
        self.assertNotIn("DO-NOT-ECHO",json.dumps(rejected));self.assertTrue(project_service.project_status(self.state,self.project)["conflicts"])

    def test_plan_registration_guards_cancel_clone_and_corrupt_core(self):
        from lib import runtime_store
        plan=project_service.preview_project(self.state,self.project,"add")
        other=self.root/"registry-concurrent";other.mkdir();project_service.register(self.state,other)
        with self.assertRaisesRegex(ValueError,"登记表在预览后"):
            project_service.apply_project(plan)
        self.assertNotIn(self.project,project_service.projects(self.state))
        cancelled=Event();cancelled.set()
        plan=project_service.preview_project(self.state,self.project,"add",enable=True,content_id=self.first.content_id)
        with self.assertRaisesRegex(ValueError,"已取消"):
            project_service.apply_project(plan,cancel=cancelled)
        self.assertFalse((self.project/".agent-workflow").exists())
        cancelled.clear();native_apply=service.runtime_service.apply
        def late_cancel(native_plan):
            # 只控制取消到达时机，真正文件发布仍执行正式原生服务。
            cancelled.set();return native_apply(native_plan)
        with patch.object(service.runtime_service,"apply",side_effect=late_cancel):
            result=project_service.apply_project(plan,cancel=cancelled)
        self.assertTrue(result["enabled"]);self.assertTrue(result["cancel_requested"])
        clone=self.root/"unmanaged-clone";shutil.copytree(self.project,clone,symlinks=True)
        status=self.cli("status",clone)["result"]
        self.assertEqual(status["state"],"unmanaged");self.assertFalse(status["enabled"])
        self.cli("open",clone,"--content-id",self.first.content_id,expected=2)
        self.assertFalse(project_service.project_status(self.state,clone)["enabled"])
        self.cli("use",self.project,"f"*64,expected=2)
        self.assertEqual(project_service.project_status(self.state,self.project)["runtime_binding"],self.first.binding())
        link=self.project/".agents/skills/xy-workflow";target=os.readlink(link)
        link.rename(link.with_name(".retained-fixture-link"));link.symlink_to(target)
        self.cli("close",self.project,expected=2)
        self.assertTrue(project_service.project_status(self.state,self.project)["conflicts"])
        # 损坏独立状态中的固定核心，不能影响共享两版本或降级到源码/其他版本。
        bad_state=self.root/"corrupt-state";core=runtime_store.import_core(self.source,bad_state)
        bad_project=self.root/"corrupt-project";bad_project.mkdir()
        self.cli("open",bad_project,"--content-id",core.content_id,state=bad_state)
        resource=core.root/"product/WORKFLOW.md";resource.chmod(0o644);resource.write_bytes(b"corrupt fixture\n")
        checked=self.cli("status",bad_project,state=bad_state)["result"]
        self.assertEqual(checked["runtime_binding"],core.binding());self.assertTrue(checked["conflicts"]);self.assertFalse(checked["enabled"])
        self.cli("open",bad_project,state=bad_state,expected=2)
        output=io.StringIO();error=io.StringIO()
        with patch("manager.cli.project_command",side_effect=KeyboardInterrupt),redirect_stdout(output),redirect_stderr(error):
            code=cli_main(["--state-dir",str(self.state),"--json","list"])
        self.assertEqual(code,130);self.assertEqual(json.loads(output.getvalue())["error"]["code"],"cancelled");self.assertEqual(error.getvalue(),"")


    def test_delete_preserves_registry_edits_after_native_disable(self):
        self.enable();plan=project_service.preview_project(self.state,self.project,"del")
        original_apply=service.runtime_service.apply
        newcomer=self.root/"externally-registered";newcomer.mkdir()
        def external_save(native_plan):
            result=original_apply(native_plan)
            # 模拟不遵守管理器锁的外部编辑器；原生停用已结算，登记不得吞掉新保存。
            data=project_service.registry(self.state);data["registered"].append(str(newcomer))
            (self.state/"projects.json").write_text(json.dumps(data),encoding="utf-8")
            return result
        with patch.object(service.runtime_service,"apply",side_effect=external_save),self.assertRaisesRegex(ValueError,"原生项目操作已结算"):
            project_service.apply_project(plan)
        self.assertFalse(project_service.project_status(self.state,self.project)["enabled"])
        self.assertIn(self.project,project_service.projects(self.state));self.assertIn(newcomer,project_service.projects(self.state))
        result=project_service.apply_project(project_service.preview_project(self.state,self.project,"del"))
        self.assertFalse(result["registered"]);self.assertIn(newcomer,project_service.projects(self.state));self.assertTrue(self.project.is_dir())

    def test_source_root_enable_refused_without_creating_state(self):
        state=self.root/"protected-source-state"
        self.cli("open",self.source,"--source",self.source,"--dry-run",state=state,expected=2)
        self.assertFalse(state.exists());self.assertFalse((self.source/".agent-workflow").exists())


class CliLauncherTest(TemporaryProject):
    """命令入口只安装到临时 bin，验证真实 PATH 查找，不修改本机命令或 shell 设置。"""
    def test_source_version_reports_unpacked_source_and_real_root(self):
        directory=self.root/'bin';entry=install_cli(directory)
        self.assertEqual(entry.name,'awf-dev');self.assertFalse((directory/'awf-cli').exists())
        result=subprocess.run([str(entry),'--state-dir',str(self.state),'--version'],
                              cwd=self.root,capture_output=True,text=True,timeout=15)
        self.assertEqual(result.returncode,0,result.stderr)
        version=(PACK/'product/VERSION').read_text(encoding='ascii').strip()
        self.assertEqual(result.stdout.splitlines(),[f'awf-cli {version}（源码未打包）',f'中央源根：{PACK}',
                                                  '入口来源：source（显式源码开发）',f'物理载荷根：{PACK}'])
        self.assertFalse((PACK/'manager/release.json').exists());self.assertFalse(self.state.exists())

    def test_cdpath_does_not_redirect_relative_links_or_pollute_source_directory(self):
        """覆盖 cd 的附加输出及搜索同名目录，直接源脚本也必须按调用位置定位。"""
        directory=self.root/'bin';directory.mkdir()
        source=self.root/'source with spaces';source.symlink_to(PACK,target_is_directory=True)
        (directory/'awf-cli').symlink_to('../source with spaces/workflow.sh')
        decoy=self.root/'decoy';(decoy/'bin').mkdir(parents=True);(decoy/'source with spaces').mkdir()
        # 每种入口都使用真实启动脚本；错误目录中没有运行时，偏离预期路径会立即失败。
        for cdpath in ('.',str(decoy),str(decoy)+os.pathsep+'.'):
            env={**os.environ,'CDPATH':cdpath,'AGENT_WORKFLOW_PYTHON':os.sys.executable}
            for entry in ('bin/awf-cli',str(directory/'awf-cli')):
                with self.subTest(cdpath=cdpath,entry=entry):
                    result=subprocess.run([entry,'--help'],cwd=self.root,env=env,capture_output=True,text=True,timeout=15)
                    self.assertEqual(result.returncode,0,result.stderr);self.assertTrue(result.stdout.startswith('usage: awf-cli'))
            with self.subTest(cdpath=cdpath,entry='direct_source'):
                result=subprocess.run(['/bin/bash','source with spaces/workflow.sh','--help'],cwd=self.root,env=env,
                                      capture_output=True,text=True,timeout=15)
                self.assertEqual(result.returncode,0,result.stderr);self.assertTrue(result.stdout.startswith('usage: awf-cli'))
        self.assertFalse(self.state.exists())

    def test_cdpath_is_preserved_for_python_and_relative_project_arguments(self):
        """隔离只作用于内部 cd；解释器仍收到原 CDPATH/PATH，相对项目按调用目录解释。"""
        directory=self.root/'bin';directory.mkdir();(directory/'awf-cli').symlink_to(PACK/'workflow.sh')
        log=self.root/'python-environment';wrapper=self.root/'python-wrapper'
        wrapper.write_text('#!/bin/sh\nprintf "%s\\n%s\\n" "$CDPATH" "$PATH" >> '+shlex.quote(str(log))+
                           '\nexec '+shlex.quote(os.sys.executable)+' "$@"\n');wrapper.chmod(0o755)
        env={**os.environ,'CDPATH':'.:kept-relative','AGENT_WORKFLOW_PYTHON':str(wrapper),
             'PATH':str(directory)+os.pathsep+os.environ['PATH']}
        result=subprocess.run(['awf-cli','--state-dir',str(self.state),'--scan-root',str(self.root),'--json','add',self.project.name],
                              cwd=self.root,env=env,capture_output=True,text=True,timeout=15)
        self.assertEqual(result.returncode,0,result.stderr);self.assertEqual(str(self.project),json.loads(result.stdout)['result']['project'])
        # 一次版本探测、一次模块执行；两个子进程的环境均应保留原值。
        self.assertEqual(log.read_text().splitlines(),[env['CDPATH'],env['PATH']]*2)

    def test_install_reports_actual_path_precedence_and_cwd_dependence(self):
        """真实 PATH 查询需区分被遮蔽、仅当前目录可用和稳定的绝对命令入口。"""
        directory=self.root/'commands';early=self.root/'earlier';early.mkdir()
        foreign=early/'awf-dev';original=b'#!/bin/sh\nprintf "FOREIGN COMMAND\\n"\n'
        foreign.write_bytes(original);foreign.chmod(0o755)
        system='/usr/bin:/bin'
        cases=[
            ('shadowed',str(early)+os.pathsep+str(directory)+os.pathsep+system,'其他同名命令',False),
            ('relative','commands'+os.pathsep+system,'相对或空目录项',False),
            ('empty',os.pathsep+str(directory)+os.pathsep+system,'相对或空目录项',False),
            ('relative_before_absolute','missing'+os.pathsep+str(directory)+os.pathsep+system,'相对或空目录项',False),
            ('absolute_before_relative',str(directory)+os.pathsep+'missing'+os.pathsep+system,'在任意目录输入 awf-dev',True),
            ('missing',system,'PATH 找不到 awf-dev',False),
        ]
        inode=None
        for name,path,message,ready in cases:
            with self.subTest(name=name):
                env={**os.environ,'PATH':path,'AGENT_WORKFLOW_PYTHON':os.sys.executable}
                result=subprocess.run(['/bin/bash',str(PACK/'workflow.sh'),'--install-cli','--bin-dir',str(directory)],
                                      cwd=self.root,env=env,capture_output=True,text=True,timeout=15)
                self.assertEqual(result.returncode,0,result.stderr);self.assertIn(message,result.stdout)
                self.assertEqual('在任意目录输入 awf-dev' in result.stdout,ready)
                self.assertEqual(foreign.read_bytes(),original)
                observed=(directory/'awf-dev').lstat().st_ino
                if inode is None:inode=observed
                self.assertEqual(observed,inode)

    def test_relative_python_is_selected_in_caller_directory_without_duplicate_probe(self):
        """显式相对路径与相对 PATH 都在调用目录解析，版本探测只执行一次。"""
        tools=self.root/'tools with spaces';tools.mkdir();log=self.root/'python-calls'
        wrapper=('#!/bin/sh\nprintf "%s\\n" "$1" >> '+shlex.quote(str(log))+'\nexec '+shlex.quote(os.sys.executable)+' "$@"\n')
        for name in ('python','python3'):
            path=tools/name;path.write_text(wrapper);path.chmod(0o755)
        for explicit in (True,False):
            with self.subTest(explicit=explicit):
                if log.exists():log.unlink()
                env={**os.environ,'PATH':'tools with spaces:/usr/bin:/bin'}
                if explicit:env['AGENT_WORKFLOW_PYTHON']='tools with spaces/python'
                else:env.pop('AGENT_WORKFLOW_PYTHON',None)
                result=subprocess.run(['/bin/bash',str(PACK/'workflow.sh'),'--help'],cwd=self.root,env=env,
                                      capture_output=True,text=True,timeout=15)
                self.assertEqual(result.returncode,0,result.stderr);self.assertIn('usage: awf-cli',result.stdout)
                self.assertEqual(log.read_text().splitlines(),['-c','-B'])

    def test_invalid_explicit_relative_python_does_not_fall_back(self):
        env={**os.environ,'AGENT_WORKFLOW_PYTHON':'missing/python'}
        result=subprocess.run(['bash',str(PACK/'workflow.sh'),'--help'],cwd=self.root,env=env,
                              capture_output=True,text=True,timeout=15)
        self.assertEqual(result.returncode,2);self.assertIn('Python >= 3.11',result.stderr)
        self.assertNotIn('usage: awf-cli',result.stdout)

    def test_link_parent_alias_uses_physical_directory_even_with_logical_decoy(self):
        """链接中的 .. 跟随物理父目录，不能被逻辑父目录下的同名文件夹误导。"""
        (self.root/'actual/bin').mkdir(parents=True)
        (self.root/'actual/pack').symlink_to(PACK,target_is_directory=True)
        alias=self.root/'alias';alias.symlink_to(self.root/'actual/bin',target_is_directory=True)
        entry=self.root/'actual/bin/awf-cli';entry.symlink_to('../pack/workflow.sh')
        (self.root/'pack').mkdir()
        self.assertEqual((alias/'awf-cli').resolve(),PACK/'workflow.sh')
        env={**os.environ,'AGENT_WORKFLOW_PYTHON':os.sys.executable}
        result=subprocess.run([str(alias/'awf-cli'),'--help'],cwd=self.root,env=env,
                              capture_output=True,text=True,timeout=15)
        self.assertEqual(result.returncode,0,result.stderr);self.assertIn('usage: awf-cli',result.stdout)
        self.assertFalse(self.state.exists())

    def test_install_short_command_preserves_caller_directory_and_is_idempotent(self):
        directory=self.root/'user bin';env={**os.environ,'PATH':str(directory)+os.pathsep+os.environ['PATH']}
        command=['bash',str(PACK/'workflow.sh'),'--install-cli','--bin-dir',directory.name]
        result=subprocess.run(command,cwd=self.root,env=env,capture_output=True,text=True,timeout=15)
        self.assertEqual(result.returncode,0,result.stderr)
        target=directory/'awf-dev';self.assertEqual(target.resolve(),PACK/'workflow.sh');inode=target.lstat().st_ino
        result=subprocess.run(['awf-dev','--help'],cwd=self.root,env=env,capture_output=True,text=True,timeout=15)
        self.assertEqual(result.returncode,0,result.stderr);self.assertIn('usage: awf-cli',result.stdout)
        result=subprocess.run(['awf-dev','--state-dir',str(self.state),'--scan-root',str(self.root),'--json','add',self.project.name],
                              cwd=self.root,env=env,capture_output=True,text=True,timeout=15)
        self.assertEqual(result.returncode,0,result.stderr);self.assertEqual(str(self.project),json.loads(result.stdout)['result']['project'])
        result=subprocess.run(['awf-dev','--install-cli','--bin-dir',directory.name],cwd=self.root,env=env,capture_output=True,text=True,timeout=15)
        self.assertEqual(result.returncode,0,result.stderr);self.assertEqual(target.lstat().st_ino,inode)

    def test_existing_command_or_foreign_links_are_never_overwritten(self):
        outside=self.root/'outside-command';outside.write_bytes(b'EXISTING COMMAND')
        for kind in ('file','foreign','dangling','cycle'):
            with self.subTest(kind=kind):
                directory=self.root/kind;directory.mkdir();target=directory/'awf-dev'
                if kind == 'file':target.write_bytes(b'USER COMMAND')
                else:target.symlink_to(outside if kind == 'foreign' else (directory/'missing' if kind == 'dangling' else target))
                before=os.readlink(target) if target.is_symlink() else target.read_bytes()
                with self.assertRaisesRegex(ValueError,'同名入口'):install_cli(directory)
                self.assertEqual(os.readlink(target) if target.is_symlink() else target.read_bytes(),before)
                self.assertEqual(outside.read_bytes(),b'EXISTING COMMAND')

    def test_relative_link_chain_and_source_directory_with_spaces(self):
        directory=self.root/'bin';directory.mkdir();links=self.root/'links';links.mkdir()
        source_alias=self.root/'source with spaces';source_alias.symlink_to(PACK,target_is_directory=True)
        (links/'entry').symlink_to('../source with spaces/workflow.sh')
        (directory/'awf-cli').symlink_to('../links/entry')
        env={**os.environ,'PATH':str(directory)+os.pathsep+os.environ['PATH']}
        result=subprocess.run(['awf-cli','--help'],cwd=self.project,env=env,capture_output=True,text=True,timeout=15)
        self.assertEqual(result.returncode,0,result.stderr);self.assertIn('usage: awf-cli',result.stdout)
        self.assertFalse(self.state.exists())


class TerminalAndCliTest(TemporaryProject):
    def test_deep_json_model_source_cli_has_safe_projection(self):
        home=self.root/'home';rejected=deep_json_source(home,'codex')
        env={**os.environ,'HOME':str(home),'CODEX_HOME':str(home/'.codex'),'CLAUDE_CONFIG_DIR':str(home/'.claude')}
        result=subprocess.run(['bash',str(PACK/'workflow.sh'),'--state-dir',str(self.state),'--host-home',str(self.root/'home'),'models','--platform','codex'],
                              cwd=self.root,env=env,capture_output=True,text=True,timeout=15)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertNotIn('Traceback',result.stderr);self.assertNotIn('DEEP-SOURCE-SECRET',result.stdout+result.stderr)
        output=json.loads(result.stdout)
        self.assertEqual([row['id'] for row in output['models']],['inherit'])
        if rejected:self.assertTrue(any('模型来源读取失败' in note for note in output['notes']))
        self.assertFalse(self.state.exists())

    def test_tui_interrupt_waits_for_synchronous_central_settlement(self):
        """同步中央写入开始后取消不伪报撤回；界面重绘，原生锁保持到事务结算。"""
        from lib.platform_fs import directory_lock
        self.project=self.root/'central-project';self.project.mkdir()
        source=CentralCliIntegrationTest.create_source(self.root)
        ready=Event();finish=Event();original_publish=service.runtime_service._publish;paused=[]
        def checkpoint(*args):
            result=original_publish(*args)
            if not paused:
                paused.append(True);ready.set()
                if not finish.wait(5):raise AssertionError('测试未释放同步中央事务')
            return result
        app=App(self.state,self.root,self.project);app.modal='manage'
        app.drafts[app.scope()]={'model':'inherit','effort':'inherit'}
        locked_during_settlement=[];painted=[];deadline=time.monotonic()+15
        class Screen:
            def keypad(self,_):pass
            def timeout(self,_):pass
            def getmaxyx(self):return 30,100
            def get_wch(screen):
                if time.monotonic()>deadline:raise AssertionError('取消测试超时')
                if app.modal == 'manage' and not app.future:
                    app.manage_action('install');return -1
                if app.modal == 'project_plan' and not app.future:
                    app.confirm();return -1
                if ready.is_set() and not app.cancel_job.is_set():raise KeyboardInterrupt()
                if ready.is_set() and app.cancel_job.is_set() and not finish.is_set():
                    with self.assertRaises(BlockingIOError):
                        with directory_lock(self.project,'install'):pass
                    locked_during_settlement.append(True);finish.set()
                if app.modal == 'result':app.done=True
                if app.modal == 'error':raise AssertionError(app.text)
                time.sleep(.01);return -1
        with patch.object(project_service,'SOURCE',source),patch.object(service.runtime_service,'_publish',side_effect=checkpoint),\
             patch('manager.tui.curses.curs_set'),patch('manager.tui.curses.has_colors',return_value=False),\
             patch('manager.tui.curses.mousemask'),patch.object(app,'draw',side_effect=lambda:painted.append(app.cancel_job.is_set())):
            self.assertEqual(app.loop(Screen()),0)
        self.assertTrue(finish.is_set());self.assertTrue(locked_during_settlement)
        self.assertTrue(any(painted));self.assertTrue(app.drafts);self.assertIn('结算',app.text)
        self.assertTrue(project_service.project_status(self.state,self.project)['enabled'])
        with directory_lock(self.project,'install'):pass

    def test_launcher_preserves_relative_project_paths(self):
        command=['bash',str(PACK/'workflow.sh'),'--state-dir',str(self.state),'--scan-root',str(self.root),'--json','add',self.project.name]
        result=subprocess.run(command,cwd=self.root,capture_output=True,text=True,timeout=15)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertEqual(str(self.project),json.loads(result.stdout)['result']['project'])

    def test_real_terminal_keyboard_and_resize_smoke(self):
        import fcntl
        master,slave=pty.openpty()
        fcntl.ioctl(slave,termios.TIOCSWINSZ,struct.pack('HHHH',30,100,0,0))
        # 从源包之外通过真实短命令默认打开 TUI；宿主目录指向临时夹具，不读本机账户配置。
        directory=self.root/'bin';entry=install_cli(directory)
        scan=self.root/'empty-scan';scan.mkdir()
        codex=self.root/'home/.codex';codex.mkdir(parents=True)
        (codex/'config.toml').write_text('model_catalog_json = "models.json"\n')
        (codex/'models.json').write_text(json.dumps({'models':[{'slug':'fixture-model','display_name':'Fixture Model','supported_reasoning_levels':['high','max']}]}))
        original={str(path.relative_to(self.project)):path.read_bytes() for path in self.project.rglob('*') if path.is_file()}
        env={**os.environ,'PATH':str(directory)+os.pathsep+os.environ['PATH'],'TERM':'xterm-256color','ESCDELAY':'25',
             'HOME':str(self.root/'home'),'CODEX_HOME':str(codex),'CLAUDE_CONFIG_DIR':str(self.root/'claude-home')}
        process=subprocess.Popen([str(entry),'--state-dir',str(self.state),'--host-home',str(self.root/'home'),'--scan-root',str(scan)],cwd=self.root,
                                 stdin=slave,stdout=slave,stderr=slave,env=env)
        os.close(slave);captured=bytearray()
        def until(text,*,existing=False):
            start=0 if existing else len(captured);deadline=time.monotonic()+5
            while time.monotonic()<deadline:
                if select.select([master],[],[],.1)[0]:
                    try:captured.extend(os.read(master,65536))
                    except OSError:break
                # curses 常把连续输入拆成带 SGR 的增量；这里只检查输出，不冒充最终屏幕录制。
                plain=re.sub(rb'\x1b(?:\[[0-?]*[ -/]*[@-~]|[()][0-2A-Z]|[ -/]*[@-~])',b'',bytes(captured[start:])).replace(b'\r',b'')
                if text.encode() in plain:return
                if process.poll() is not None:break
            self.fail('终端没有出现预期内容：'+text+'\n'+captured.decode(errors='replace')[-1200:])
        try:
            until('awf-cli')
            # 新界面首次状态在作业线程读取，期间按键按等待合同忽略；须观察
            # 同一真实终端的完成反馈后再操作，不能用固定sleep掩盖启动竞态。
            until('已读取预览 / 状态，尚未写入',existing=True)
            os.write(master,b'?');until('快捷键帮助')
            os.write(master,b'\x1b');time.sleep(.1)
            os.write(master,b'g');until('工作流管理')
            os.write(master,b'\x1b');time.sleep(.1)
            # 无binding的项目不再凭local文件提供角色；本例在全局默认范围检验键盘/弹层。
            os.write(master,b'\r\r');until('选择模型')
            os.write(master,b'/fixture\r');until('/ fixture')
            self.assertIsNone(process.poll())
            os.write(master,b'\r');until('推理级别')
            os.write(master,b'\r');until('已暂存')
            os.write(master,b':preview\r');until('保存预览')
            os.write(master,b'\x1b');time.sleep(.1)
            os.write(master,b'a');until('输入目录')
            os.write(master,'/tmp/中文路径'.encode()+b'\x15edited-path');until('edited-path')
            os.write(master,b'\x1b');time.sleep(.1)
            fcntl.ioctl(master,termios.TIOCSWINSZ,struct.pack('HHHH',16,55,0,0));os.kill(process.pid,signal.SIGWINCH);time.sleep(.1)
            os.write(master,b'q');until('退出确认')
            os.write(master,b'\x1b');time.sleep(.1)
            fcntl.ioctl(master,termios.TIOCSWINSZ,struct.pack('HHHH',10,45,0,0));os.kill(process.pid,signal.SIGWINCH);time.sleep(.1)
            os.write(master,b'q');until('Enter 放弃全部草稿并退出')
            os.write(master,b'\r')
            # 退出时 curses 仍需把恢复终端的序列写出；持续排空伪终端，避免测试自身反压。
            deadline=time.monotonic()+5
            while process.poll() is None and time.monotonic()<deadline:
                if select.select([master],[],[],.1)[0]:
                    try:captured.extend(os.read(master,65536))
                    except OSError:break
            process.wait(timeout=1)
            self.assertEqual(process.returncode,0,captured.decode(errors='replace')[-1000:])
            self.assertFalse(self.state.exists())
            self.assertEqual(original,{str(path.relative_to(self.project)):path.read_bytes() for path in self.project.rglob('*') if path.is_file()})
        finally:
            if process.poll() is None:process.kill();process.wait(timeout=5)
            os.close(master)


if __name__ == '__main__':unittest.main()
