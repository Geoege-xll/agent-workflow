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
import select
import signal
import shlex
import struct
import subprocess
import tempfile
import termios
import time
from threading import Event
import tomllib
import unittest
from unittest.mock import patch

from lib import role_models
from lib import install_workflow
from lib.install_process import SetupRunner, SetupRunError
from lib.install_workflow import _managed_files
from manager.catalog import Catalog, Model, discover
from manager import service
from manager.install_cli import install as install_cli
from manager.tui import App, cell_width, clip

PACK=Path(__file__).resolve().parents[1]


def codex_agent(model=None,effort="high"):
    payload='name = "xy-backend"\ndescription = "fixture"\n'
    if model:payload+=f'model = "{model}"\n'
    if effort:payload+=f'model_reasoning_effort = "{effort}"\n'
    payload+='sandbox_mode = "workspace-write"\nnickname_candidates = ["Backend"]\n\ndeveloper_instructions = "fixture instructions"\n'
    return f'# agent-workflow-pack:managed-codex-agent:v1 sha256={hashlib.sha256(payload.encode()).hexdigest()}\n{payload}'.encode()


class TemporaryProject(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix="workflow-manager-test-")
        self.root=Path(self.temp.name).resolve();self.project=self.root/"项目 A";self.project.mkdir()
        self.state=self.root/"state"
        self.write(".agent-workflow/project.yaml","project_name: test\nworkspace: auto\n")
        self.write(".agent-workflow/lib/role_models.py","# fixture\n")
        runtime=self.project/".agent-workflow"
        self.write(".agent-workflow/.install-manifest.json",json.dumps({"schema_version":1,"managed_files":_managed_files(runtime)}))
        self.write(".codex/agents/xy-backend.toml",codex_agent())
        self.catalog=Catalog("codex",[Model("inherit","继承","fixture",("high","max")),Model("local-model","本地模型","fixture",("high","max"))])
        self.value={"model":"local-model","effort":"max"}

    def tearDown(self):self.temp.cleanup()

    def write(self,relative,value):
        path=self.project/relative;path.parent.mkdir(parents=True,exist_ok=True)
        path.write_bytes(value if isinstance(value,bytes) else value.encode());return path

    def prepare(self):return service.prepare(self.project,"codex",{"xy-backend":self.value},self.catalog)


class ModelContractTest(unittest.TestCase):
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
        self.write('.claude/settings.json',{'env':{'ANTHROPIC_AUTH_TOKEN':'TOP-SECRET','ANTHROPIC_DEFAULT_OPUS_MODEL':'custom/model'},'modelPicker':{'options':[{'value':'custom/model','label':'自定义'}]},'modelSettings':{'custom/model':{'effortLevel':'max'}}})
        catalog=discover('claude',self.home,env={});output=json.dumps(catalog.as_dict())
        self.assertNotIn('TOP-SECRET',output);self.assertNotIn('AUTH_TOKEN',output)
        self.assertTrue(any(row.id == 'custom/model' for row in catalog.models));self.assertTrue(all(not row.efforts for row in catalog.models))
        self.assertIn('custom/model',next(row.label for row in catalog.models if row.id == 'opus'))

    def test_project_provider_change_does_not_reuse_old_menu(self):
        self.write('.claude/settings.json',{'model':'old-model','env':{'ANTHROPIC_BASE_URL':'old'},'modelPicker':{'options':['old-model']}})
        project=self.home/'project';self.write('project/.claude/settings.json',{'env':{'ANTHROPIC_BASE_URL':'new'}})
        self.assertNotIn('old-model',[row.id for row in discover('claude',self.home,project,{}).models])

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
        self.assertEqual(before.stamp,discover('claude',self.home,env={'ANTHROPIC_MODEL':'selected'}).stamp)

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
        self.assertNotEqual(before.stamp,discover('claude',self.home,env={'ANTHROPIC_BASE_URL':'second'}).stamp)
        self.assertNotEqual(before.stamp,discover('claude',self.home,env={'ANTHROPIC_DEFAULT_OPUS_MODEL':'second-model'}).stamp)


class TransactionTest(TemporaryProject):
    def test_tui_restore_confirmation_keeps_original_version_guard(self):
        """实际走 TUI 的恢复确认回调，防止容器转换把 RestorePlan 的保护丢掉。"""
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
        changes=self.prepare();initial=service._record_payload
        sizes=[]
        def observe(record):sizes.append((len(json.dumps(record,ensure_ascii=False,indent=2).encode())+1,bool(record.get('previous_files'))));return initial(record)
        with patch('manager.service._record_payload',side_effect=observe):service.commit(self.state,self.project,changes)
        base=next(size for size,versions in sizes if not versions)
        # 重置到应用前状态，用略高于初始快照的预算验证容量预留，而非制作大量临时脚本。
        for row in changes:(self.project/row.relative).write_bytes(row.before)
        count=len(service.backups(self.state,self.project));directories=list(self.project.glob('.agent-workflow-backup-models-*'))
        with patch.object(service,'MAX_RECORD_BYTES',base+100),self.assertRaisesRegex(ValueError,'有界读取'):
            service.commit(self.state,self.project,changes)
        self.assertEqual(len(service.backups(self.state,self.project)),count)
        self.assertEqual(list(self.project.glob('.agent-workflow-backup-models-*')),directories)
        for row in changes:self.assertEqual((self.project/row.relative).read_bytes(),row.before)

    def test_failed_error_log_keeps_original_failure_and_retained_paths(self):
        changes=self.prepare();original=service.write_state;calls=[]
        def broken(*args):
            calls.append(True)
            if len(calls)>1:raise OSError('DISK FULL FIXTURE')
            return original(*args)
        def fail():raise ValueError('ORIGINAL VERIFY FAILURE')
        with patch('manager.service.write_state',side_effect=broken),self.assertRaises(ValueError) as result:
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
                app.dispatch('g');app.dispatch('down');app.dispatch('down');app.dispatch('enter')
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
            with patch('manager.service.os.link',side_effect=save),self.assertRaisesRegex(ValueError,'保留版本'):
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

    def test_bad_manifest_and_role_directory_stay_inside_ui_error_boundary(self):
        app=App(self.state,self.root,self.project)
        self.write('.agent-workflow/.install-manifest.json','[]')
        app.dispatch('g');app.dispatch('enter')
        self.assertEqual(app.modal,'manage');self.assertIn('安装记录',app.toast)
        outside=self.root/'outside';outside.mkdir()
        role=self.project/'.codex/agents';role.rename(self.project/'.codex/original');role.symlink_to(outside,target_is_directory=True)
        app.roles_cache.clear();self.assertEqual(app.role_list(),[])
        self.assertIn('符号链接',app.toast)

    def test_discard_conflicted_draft_rebuilds_only_its_baseline(self):
        app=App(self.state,self.root,self.project);app.catalogs[(str(self.project),'codex')]=self.catalog
        app.dispatch('enter');app.dispatch('down');app.dispatch('enter');app.dispatch('down');app.dispatch('enter')
        other=('another-project','codex','xy-qa');app.drafts[other]={'model':'inherit','effort':'inherit'}
        self.write('.codex/agents/xy-backend.toml',codex_agent(effort='medium'))
        app.dispatch('s');self.assertIn('编辑期间',app.toast)
        app.dispatch('r');app.dispatch('u');self.assertIn(other,app.drafts);self.assertFalse(app.pending())
        app.catalogs[(str(self.project),'codex')]=self.catalog
        app.dispatch('enter');self.assertEqual(app.expected[app.scope()]['effort'],'medium')
        app.dispatch('down');app.dispatch('enter');app.dispatch('down');app.dispatch('enter');app.dispatch('s')
        self.assertEqual(app.modal,'preview')

    def test_stale_source_draft_requires_reselection_before_preview(self):
        app=App(self.state,self.root,self.project)
        first=Catalog('codex',self.catalog.models,stamp='first');second=Catalog('codex',self.catalog.models,stamp='second')
        app.catalogs[(str(self.project),'codex')]=first
        app.dispatch('enter');app.dispatch('down');app.dispatch('enter');app.dispatch('down');app.dispatch('enter')
        with patch('manager.tui.discover',return_value=second):app.dispatch('s')
        self.assertIsNone(app.modal);self.assertIn('来源',app.toast);self.assertTrue(app.pending())
        with patch('manager.tui.discover',return_value=second):app.dispatch('s')
        self.assertIsNone(app.modal)
        app.dispatch('enter');app.dispatch('enter');app.dispatch('enter')
        with patch('manager.tui.discover',return_value=second):app.dispatch('s')
        self.assertEqual(app.modal,'preview')

    def test_confirmation_views_scroll_without_applying(self):
        app=App(self.state,self.root,self.project)
        for modal in ('preview','install','restore'):
            with self.subTest(modal=modal):
                app.modal=modal;app.scroll=0;app.page_lines=6
                app.dispatch('down');self.assertEqual(app.scroll,1)
                app.dispatch('pagedown');self.assertEqual(app.scroll,7)
                app.dispatch('pageup');self.assertEqual(app.scroll,1)
                app.dispatch('up');self.assertEqual(app.scroll,0)
        self.assertFalse(self.state.exists())
    def test_preview_is_read_only_then_apply_and_restore_exact_bytes(self):
        changes=self.prepare();self.assertFalse(self.state.exists())
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
        with self.assertRaisesRegex(ValueError,'并发修改'):service.commit(self.state,self.project,changes,fail)
        self.assertEqual((self.project/changes[0].relative).read_bytes(),changes[0].before)
        self.assertEqual(outside.read_bytes(),b'EXTERNAL')
        self.assertEqual(service.backups(self.state,self.project)[0]['status'],'conflict')

    def test_parent_swap_cannot_write_through_to_external_directory(self):
        changes=self.prepare();outside=self.root/'external-agents';outside.mkdir()
        external=outside/'xy-backend.toml';external.write_bytes(b'EXTERNAL')
        original=service.AnchoredFile.write;swapped=[]
        def swap(target,data,mode,expected=None):
            if target.name == 'xy-backend.toml' and not swapped:
                parent=self.project/'.codex/agents';parent.rename(self.project/'.codex/agents-original');parent.symlink_to(outside,target_is_directory=True);swapped.append(True)
            return original(target,data,mode,expected)
        def fail():raise ValueError('verify failed')
        with patch.object(service.AnchoredFile,'write',swap),self.assertRaisesRegex(ValueError,'verify failed'):
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
        real_write=service.AnchoredFile.write
        def write(target,data,mode,expected=None):
            if target.name == 'xy-backend.toml':
                with patch('manager.service.os.fsync',side_effect=edit):return real_write(target,data,mode,expected)
            return real_write(target,data,mode,expected)
        with patch.object(service.AnchoredFile,'write',write),self.assertRaisesRegex(ValueError,'并发修改'):
            service.commit(self.state,self.project,changes)
        self.assertEqual(path.read_bytes(),b'CONCURRENT EDIT')

    def test_last_moment_save_before_exclusive_publish_is_preserved(self):
        changes=self.prepare();original=os.link;edited=[];path=self.project/changes[0].relative
        def save(source,target,*args,**kwargs):
            if target == 'xy-backend.toml' and not edited:
                path.write_bytes(b'LAST MOMENT SAVE');edited.append(True)
            return original(source,target,*args,**kwargs)
        with patch('manager.service.os.link',side_effect=save),self.assertRaisesRegex(ValueError,'并发修改'):
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
        with self.assertRaisesRegex(ValueError,'预览后'):service.commit(self.state,self.project,changes)
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
        self.assertEqual(service.projects(self.state),[]);self.assertFalse(self.state.exists())
        service.register(self.state,self.project);service.register(self.state,self.project)
        self.assertEqual(service.projects(self.state),[self.project])
        service.register(self.state,self.project,True);self.assertEqual(service.projects(self.state),[])
        self.assertNotIn(self.project,service.projects(self.state,self.root))
        service.register(self.state,self.project);self.assertIn(self.project,service.projects(self.state,self.root))

    def test_keyboard_stage_cancel_and_cross_project_scope(self):
        app=App(self.state,self.root,self.project)
        app.catalogs[(str(self.project),'codex')]=self.catalog
        app.dispatch('enter');app.dispatch('down');app.dispatch('enter')
        app.dispatch('down');app.dispatch('enter')
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
        self.assertIn('编辑期间',app.toast);self.assertIsNone(app.modal)

    def test_unicode_cells_are_bounded(self):
        self.assertEqual(cell_width('中文A'),5);self.assertEqual(clip('中文A',4),'中文')


class AddInstallTest(TemporaryProject):
    """只在临时目录验证“选择添加、拖入、回车安装”，不登记真实项目。"""
    def test_empty_list_and_project_list_both_offer_install_entry(self):
        app=App(self.state,self.root/'empty-scan')
        self.assertEqual(app.pane,'projects');self.assertIsNone(app.project)
        with patch.object(service,'install') as install:
            app.dispatch('enter');self.assertEqual(app.modal,'add')
            self.assertIn('安装',app.bindings()[0].label)
            app.dispatch('esc');install.assert_not_called()
        self.assertFalse(self.state.exists())
        app=App(self.state,self.root,self.project);app.dispatch('tab');app.dispatch('down')
        self.assertIsNone(app.project);app.dispatch('enter');self.assertEqual(app.modal,'add')

    def test_dragged_path_installs_once_then_selects_roles_and_keeps_other_drafts(self):
        target=self.root/"新项目's $(literal)";target.mkdir()
        app=App(self.state,self.root,self.project);key=app.scope()
        app.drafts[key]=dict(self.value);app.expected[key]={'model':'inherit','effort':'high'}
        other_key=(str(self.project),'codex');app.catalogs[other_key]=self.catalog
        app.roles_cache[(str(target),'codex')]=[]
        ready=Event();finish=Event()
        def install(project,cancel):
            self.assertEqual(project,target)
            with self.assertRaisesRegex(ValueError,'另一管理操作'):
                with service.lock(self.state,str(target)):pass
            self.assertNotIn(target,service.projects(self.state));ready.set()
            if not finish.wait(5):raise AssertionError('测试未释放安装任务')
            role=target/'.codex/agents/xy-backend.toml';role.parent.mkdir(parents=True);role.write_bytes(codex_agent())
            return 'installed fixture'
        with ThreadPoolExecutor(max_workers=1) as executor,patch.object(service,'install',side_effect=install) as installer:
            app.executor=executor;app.dispatch('a');app.input=shlex.quote(str(target));app.dispatch('enter')
            try:
                self.assertTrue(ready.wait(5));app.dispatch('enter');app.dispatch('a')
                self.assertIsNotNone(app.future);self.assertNotIn(target,app.projects)
            finally:finish.set()
            app.future.result(timeout=5);app.poll_job();self.assertEqual(installer.call_count,1)
        self.assertEqual(app.project,target);self.assertEqual(app.pane,'roles');self.assertIsNone(app.modal)
        self.assertEqual(app.role_list(),['xy-backend']);self.assertEqual(app.drafts[key],self.value)
        self.assertIs(app.catalogs[other_key],self.catalog);self.assertIn(target,service.projects(self.state))
        self.assertEqual(app.projects.count(target),1)

    def test_invalid_input_stays_editable_without_starting_installer(self):
        app=App(self.state,self.root,self.project)
        for value in ('',str(self.root/'missing'),"'unclosed",shlex.quote(str(self.root))+' '+shlex.quote(str(self.project))):
            with self.subTest(value=value),patch.object(service,'install') as install:
                app.dispatch('a');app.input=value;app.dispatch('enter')
                self.assertEqual(app.modal,'add');self.assertIsNone(app.future);install.assert_not_called()
        self.assertFalse(self.state.exists())

    def test_install_failure_keeps_project_list_and_drafts(self):
        target=self.root/'failed-project';target.mkdir()
        app=App(self.state,self.root,self.project);key=app.scope();app.drafts[key]=dict(self.value)
        with ThreadPoolExecutor(max_workers=1) as executor,patch.object(service,'install',side_effect=ValueError('fixture recovery completed')):
            app.executor=executor;app.dispatch('a');app.input=str(target);app.dispatch('enter')
            with self.assertRaisesRegex(ValueError,'recovery completed'):app.future.result(timeout=5)
            app.poll_job()
        self.assertEqual(app.modal,'error');self.assertIn('recovery completed',app.text)
        self.assertEqual(app.project,self.project);self.assertNotIn(target,app.projects)
        self.assertNotIn(target,service.projects(self.state));self.assertEqual(app.drafts[key],self.value)
        with service.lock(self.state,str(target)):pass

    def test_adding_existing_project_upgrades_without_duplicate_registration(self):
        app=App(self.state,self.root,self.project)
        with ThreadPoolExecutor(max_workers=1) as executor,patch.object(service,'install',return_value='upgraded fixture') as install:
            app.executor=executor;app.dispatch('a');app.input=str(self.project);app.dispatch('enter')
            app.future.result(timeout=5);app.poll_job();install.assert_called_once()
        self.assertEqual(app.projects.count(self.project),1)
        self.assertEqual(service.projects(self.state),[self.project]);self.assertIsNone(app.modal)


class InstalledProjectIntegrationTest(unittest.TestCase):
    """一个临时后端项目覆盖真实安装、三平台模型应用、检查及再次升级保留。"""
    def test_three_platform_configuration_survives_upgrade(self):
        with tempfile.TemporaryDirectory(prefix='workflow-manager-integration-') as raw:
            root=Path(raw).resolve();project=root/'backend';project.mkdir();state=root/'state'
            (project/'pyproject.toml').write_text('[project]\nname="example"\nversion="0.1.0"\n')
            # 首次安装走真实 TUI 回调和真实安装器；一个回车完成，成功即进入角色列表。
            app=App(state,root)
            with ThreadPoolExecutor(max_workers=1) as executor:
                app.executor=executor;app.dispatch('enter');app.input=str(project);app.dispatch('enter')
                app.future.result(timeout=180);app.poll_job()
            self.assertIsNone(app.modal);self.assertEqual(app.project,project);self.assertEqual(app.pane,'roles')
            for host in service.LOCATIONS:self.assertTrue(service.roles(project,host))
            for host,model,effort in [('codex','fixture-model','max'),('claude','fixture/model','inherit'),('antigravity','pro','inherit')]:
                catalog=Catalog(host,[Model(model,model,'fixture',('max',))])
                changes=service.prepare(project,host,{'xy-backend':{'model':model,'effort':effort}},catalog)
                service.commit(state,project,changes,lambda host=host:service.check(project,host))
                self.assertEqual(service.role_settings(project,host,'xy-backend'),{'model':model,'effort':effort})
            inherit=Catalog('codex',[Model('inherit','继承','fixture')])
            changes=service.prepare(project,'codex',{'xy-backend':{'model':'inherit','effort':'inherit'}},inherit)
            identifier=service.commit(state,project,changes,lambda:service.check(project,'codex'))
            service.commit(state,project,service.prepare_restore(state,project,identifier),lambda:service.check(project,'codex'))
            result=subprocess.run(['bash',str(PACK/'install.sh'),str(project)],capture_output=True,text=True,timeout=180)
            self.assertEqual(result.returncode,0,result.stdout[-3500:]+result.stderr[-3500:])
            self.assertEqual(service.role_settings(project,'codex','xy-backend')['effort'],'max')
            self.assertEqual(service.role_settings(project,'claude','xy-backend')['model'],'fixture/model')
            self.assertEqual(service.role_settings(project,'antigravity','xy-backend')['model'],'pro')


class InstallerBoundaryTest(unittest.TestCase):
    """用真实事务和真实进程组验证停止、目录切换及恢复，不安装到真实项目。"""
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='workflow-installer-boundary-')
        self.root=Path(self.temp.name).resolve();self.project=self.root/'project';self.project.mkdir()
        self.source=self.root/'source';self.source.mkdir();self.version='old';self.late=self.root/'late-write'
        child=f'import time;from pathlib import Path;time.sleep(.6);Path({str(self.late)!r}).write_text("late")'
        self.script=('set -eu\n'
            'if [[ "${1:-}" == "--preflight" || "${1:-}" == "--check" ]]; then exit 0; fi\n'
            'version=$(cat "$(dirname "$0")/version.txt")\nprintf "%s" "$version" > AGENTS.md\n'
            f'if [[ "$version" == "new" ]]; then {shlex.quote(os.sys.executable)} -c {shlex.quote(child)} &\n sleep 30\nfi\n')

    def tearDown(self):self.temp.cleanup()

    def copy(self,source,stage):
        (stage/'project.yaml').write_text((PACK/'project.yaml').read_text().replace('MyProject','Fixture'))
        (stage/'version.txt').write_text(self.version)
        (stage/'setup_all.sh').write_text(self.script)

    def hooks(self,runtime,project,host,**kwargs):return project/f'.{host}-settings.json',None,b'{}'

    def install(self,**kwargs):
        with patch.object(install_workflow,'_copy_runtime',self.copy),patch.object(install_workflow,'plan_hooks',self.hooks),redirect_stdout(io.StringIO()):
            install_workflow._install(self.project,self.source,**kwargs)

    def test_timeout_waits_for_descendants_and_restores_old_runtime(self):
        self.install();self.version='new';before_handler=signal.getsignal(signal.SIGINT)
        with service.lock(self.root/'state',str(self.project)):
            with self.assertRaisesRegex(install_workflow.InstallError,'超时'):self.install(timeout=.25)
        self.assertEqual((self.project/'.agent-workflow/version.txt').read_text(),'old')
        self.assertEqual((self.project/'AGENTS.md').read_text(),'old')
        self.assertEqual(signal.getsignal(signal.SIGINT),before_handler)
        time.sleep(.65);self.assertFalse(self.late.exists())
        with service.lock(self.root/'state',str(self.project)):pass

    def test_interrupt_after_either_replace_restores_runtime(self):
        self.install();self.version='new';original=os.replace
        for phase in ('backup','publish'):
            fired=[]
            def interrupt(source,target,*args,**kwargs):
                result=original(source,target,*args,**kwargs)
                matching=(Path(source) == self.project/'.agent-workflow' if phase == 'backup'
                          else Path(source).name.startswith('.agent-workflow-stage-') and Path(target) == self.project/'.agent-workflow')
                if matching and not fired:fired.append(True);raise KeyboardInterrupt()
                return result
            with self.subTest(phase=phase),patch('lib.install_workflow.os.replace',side_effect=interrupt):
                with self.assertRaises(install_workflow.InstallError):self.install()
            self.assertTrue(fired);self.assertEqual((self.project/'.agent-workflow/version.txt').read_text(),'old')
            self.assertEqual((self.project/'AGENTS.md').read_text(),'old')

    def test_runner_cancel_stops_real_child_group(self):
        original=subprocess.Popen.wait;interrupted=[]
        def wait(process,*args,**kwargs):
            if not interrupted:interrupted.append(True);raise KeyboardInterrupt()
            return original(process,*args,**kwargs)
        command=[os.sys.executable,'-c',f'import time;from pathlib import Path;time.sleep(.5);Path({str(self.late)!r}).write_text("late")']
        with patch.object(subprocess.Popen,'wait',wait),self.assertRaisesRegex(SetupRunError,'取消'):
            SetupRunner().run(command,self.project)
        time.sleep(.55);self.assertFalse(self.late.exists())


class CliLauncherTest(TemporaryProject):
    """命令入口只安装到临时 bin，验证真实 PATH 查找，不修改本机命令或 shell 设置。"""
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
        result=subprocess.run(['awf-cli','--state-dir',str(self.state),'--scan-root',str(self.root),'projects','add',self.project.name],
                              cwd=self.root,env=env,capture_output=True,text=True,timeout=15)
        self.assertEqual(result.returncode,0,result.stderr);self.assertIn(str(self.project),json.loads(result.stdout))
        # 一次版本探测、一次模块执行；两个子进程的环境均应保留原值。
        self.assertEqual(log.read_text().splitlines(),[env['CDPATH'],env['PATH']]*2)

    def test_install_reports_actual_path_precedence_and_cwd_dependence(self):
        """真实 PATH 查询需区分被遮蔽、仅当前目录可用和稳定的绝对命令入口。"""
        directory=self.root/'commands';early=self.root/'earlier';early.mkdir()
        foreign=early/'awf-cli';original=b'#!/bin/sh\nprintf "FOREIGN COMMAND\\n"\n'
        foreign.write_bytes(original);foreign.chmod(0o755)
        system='/usr/bin:/bin'
        cases=[
            ('shadowed',str(early)+os.pathsep+str(directory)+os.pathsep+system,'其他同名命令',False),
            ('relative','commands'+os.pathsep+system,'相对或空目录项',False),
            ('empty',os.pathsep+str(directory)+os.pathsep+system,'相对或空目录项',False),
            ('relative_before_absolute','missing'+os.pathsep+str(directory)+os.pathsep+system,'相对或空目录项',False),
            ('absolute_before_relative',str(directory)+os.pathsep+'missing'+os.pathsep+system,'在任意目录输入 awf-cli',True),
            ('missing',system,'PATH 找不到 awf-cli',False),
        ]
        inode=None
        for name,path,message,ready in cases:
            with self.subTest(name=name):
                env={**os.environ,'PATH':path,'AGENT_WORKFLOW_PYTHON':os.sys.executable}
                result=subprocess.run(['/bin/bash',str(PACK/'workflow.sh'),'--install-cli','--bin-dir',str(directory)],
                                      cwd=self.root,env=env,capture_output=True,text=True,timeout=15)
                self.assertEqual(result.returncode,0,result.stderr);self.assertIn(message,result.stdout)
                self.assertEqual('在任意目录输入 awf-cli' in result.stdout,ready)
                self.assertEqual(foreign.read_bytes(),original)
                observed=(directory/'awf-cli').lstat().st_ino
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
        target=directory/'awf-cli';self.assertEqual(target.resolve(),PACK/'workflow.sh');inode=target.lstat().st_ino
        result=subprocess.run(['awf-cli','--help'],cwd=self.root,env=env,capture_output=True,text=True,timeout=15)
        self.assertEqual(result.returncode,0,result.stderr);self.assertIn('usage: awf-cli',result.stdout)
        result=subprocess.run(['awf-cli','--state-dir',str(self.state),'--scan-root',str(self.root),'projects','add',self.project.name],
                              cwd=self.root,env=env,capture_output=True,text=True,timeout=15)
        self.assertEqual(result.returncode,0,result.stderr);self.assertIn(str(self.project),json.loads(result.stdout))
        result=subprocess.run(['awf-cli','--install-cli','--bin-dir',directory.name],cwd=self.root,env=env,capture_output=True,text=True,timeout=15)
        self.assertEqual(result.returncode,0,result.stderr);self.assertEqual(target.lstat().st_ino,inode)

    def test_existing_command_or_foreign_links_are_never_overwritten(self):
        outside=self.root/'outside-command';outside.write_bytes(b'EXISTING COMMAND')
        for kind in ('file','foreign','dangling','cycle'):
            with self.subTest(kind=kind):
                directory=self.root/kind;directory.mkdir();target=directory/'awf-cli'
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
    def test_tui_interrupt_reaches_installer_and_waits_until_lock_released(self):
        """真实安装子进程接收取消后模拟恢复；TUI 继续重绘，锁到恢复完成才释放。"""
        ready=self.root/'ready';cancelled=self.root/'cancelled';finished=self.root/'finished'
        driver=('import signal,time;from pathlib import Path\n'
                'def stop(*_):\n'
                f' Path({str(cancelled)!r}).write_text("received");time.sleep(.2);raise SystemExit(130)\n'
                'signal.signal(signal.SIGINT,stop)\n'
                f'Path({str(ready)!r}).touch()\n'
                'time.sleep(5)\n'
                f'Path({str(finished)!r}).touch()\n')
        source=self.root/'source';source.mkdir()
        (source/'install.sh').write_text('exec '+shlex.quote(os.sys.executable)+' -c '+shlex.quote(driver)+'\n')
        app=App(self.state,self.root,self.project);app.modal='install'
        app.drafts[app.scope()]={'model':'inherit','effort':'inherit'}
        entered=[];locked_during_recovery=[];painted=[];deadline=time.monotonic()+8
        class Screen:
            def keypad(self,_):pass
            def timeout(self,_):pass
            def getmaxyx(self):return 30,100
            def get_wch(screen):
                if time.monotonic()>deadline:raise AssertionError('取消测试超时')
                if not entered:
                    entered.append(True);app.confirm();return -1
                if ready.exists() and not app.cancel_job.is_set():raise KeyboardInterrupt()
                if cancelled.exists() and app.future:
                    try:
                        with service.lock(self.state,str(self.project)):pass
                    except ValueError:locked_during_recovery.append(True)
                if app.modal == 'error':app.done=True
                time.sleep(.01);return -1
        with patch.object(service,'SOURCE',source),patch.object(service,'install_preview',return_value='fixture'),\
             patch('manager.tui.curses.curs_set'),patch('manager.tui.curses.has_colors',return_value=False),\
             patch('manager.tui.curses.mousemask'),patch.object(app,'draw',side_effect=lambda:painted.append(app.cancel_job.is_set())):
            self.assertEqual(app.loop(Screen()),0)
        self.assertTrue(cancelled.exists());self.assertFalse(finished.exists());self.assertTrue(locked_during_recovery)
        self.assertTrue(any(painted));self.assertTrue(app.drafts);self.assertIn('已等待安装器退出',app.text)
        with service.lock(self.state,str(self.project)):pass

    def test_launcher_preserves_relative_project_paths(self):
        command=['bash',str(PACK/'workflow.sh'),'--state-dir',str(self.state),'--scan-root',str(self.root),'projects','add',self.project.name]
        result=subprocess.run(command,cwd=self.root,capture_output=True,text=True,timeout=15)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertIn(str(self.project),json.loads(result.stdout))

    def test_real_terminal_keyboard_and_resize_smoke(self):
        import fcntl
        master,slave=pty.openpty()
        fcntl.ioctl(slave,termios.TIOCSWINSZ,struct.pack('HHHH',30,100,0,0))
        # 从源包之外通过真实短命令默认打开 TUI；宿主目录指向临时夹具，不读本机账户配置。
        directory=self.root/'bin';install_cli(directory)
        env={**os.environ,'PATH':str(directory)+os.pathsep+os.environ['PATH'],'TERM':'xterm-256color','ESCDELAY':'25',
             'CODEX_HOME':str(self.root/'codex-home'),'CLAUDE_CONFIG_DIR':str(self.root/'claude-home')}
        process=subprocess.Popen(['awf-cli','--state-dir',str(self.state),'--scan-root',str(self.root)],cwd=self.root,
                                 stdin=slave,stdout=slave,stderr=slave,env=env)
        os.close(slave);captured=bytearray()
        def until(text):
            start=len(captured);deadline=time.monotonic()+5
            while time.monotonic()<deadline:
                if select.select([master],[],[],.1)[0]:
                    try:captured.extend(os.read(master,65536))
                    except OSError:break
                if text.encode() in captured[start:]:return
                if process.poll() is not None:break
            self.fail('终端没有出现预期内容：'+text+'\n'+captured.decode(errors='replace')[-1200:])
        try:
            until('awf-cli')
            os.write(master,b'?');until('快捷键帮助')
            os.write(master,b'\x1b');time.sleep(.1)
            os.write(master,b'g');until('工作流管理')
            os.write(master,b'\x1b');time.sleep(.1)
            os.write(master,b'\r');until('选择模型')
            os.write(master,b'\x1b');time.sleep(.1)
            fcntl.ioctl(master,termios.TIOCSWINSZ,struct.pack('HHHH',16,55,0,0));os.kill(process.pid,signal.SIGWINCH);time.sleep(.1)
            os.write(master,b'q')
            # 退出时 curses 仍需把恢复终端的序列写出；持续排空伪终端，避免测试自身反压。
            deadline=time.monotonic()+5
            while process.poll() is None and time.monotonic()<deadline:
                if select.select([master],[],[],.1)[0]:
                    try:captured.extend(os.read(master,65536))
                    except OSError:break
            process.wait(timeout=1)
            self.assertEqual(process.returncode,0,captured.decode(errors='replace')[-1000:])
            self.assertFalse(self.state.exists())
        finally:
            if process.poll() is None:process.kill();process.wait(timeout=5)
            os.close(master)


if __name__ == '__main__':unittest.main()
