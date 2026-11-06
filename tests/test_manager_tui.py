"""隔离录屏验证 TUI 单元格、焦点和输入；不读取真实宿主目录。"""

from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor
import curses
import codecs
import errno
import fcntl
import json
import os
from pathlib import Path
import pty
import re
import select
import signal
import struct
import subprocess
import tempfile
import termios
from threading import Event
import time
import unittest
from unittest.mock import patch
import uuid

from lib import runtime_store
from manager import service
from manager.catalog import Catalog, Model
from manager.tui import App, HOSTS, cell_width
from manager.tui_support import Layout, TextInput, Theme, ellipsize, project_plan_text, status_text


PACK=Path(__file__).resolve().parents[1]
PYTHON=["bash",str(PACK/"lib/python_runtime.sh"),"-B","-X","utf8"]


class RecordingScreen:
    def __init__(self, height=30, width=100):
        self.height,self.width=height,width
        self.keys=[];self.cursor=None
        self.erase()

    def getmaxyx(self):return self.height,self.width
    def erase(self):
        self.cells=[[" " for _ in range(self.width)] for _ in range(self.height)]
        self.attrs=[[0 for _ in range(self.width)] for _ in range(self.height)]
    def refresh(self):pass
    def move(self,y,x):
        assert 0<=y<self.height and 0<=x<self.width,(y,x)
        self.cursor=(y,x)
    def get_wch(self):
        if self.keys:return self.keys.pop(0)
        raise curses.error()
    def addstr(self,y,x,text,attr=0):
        assert 0<=y<self.height and 0<=x<self.width,(y,x,text)
        # 允许真实右边框落在最后一列；光标的可达范围仍由 move 单独断言。
        assert x+cell_width(text)<=self.width,(y,x,text)
        for char in text:
            size=cell_width(char)
            if not size:
                if x:self.cells[y][x-1]+=char
                continue
            self.cells[y][x]=char;self.attrs[y][x]=attr
            for offset in range(1,size):
                self.cells[y][x+offset]="";self.attrs[y][x+offset]=attr
            x+=size
        self.cursor=(y,x)
    def line(self,y):return "".join(self.cells[y])
    def text(self):return "\n".join(self.line(y) for y in range(self.height))


class TextInputTest(unittest.TestCase):
    def test_editing_and_combining_boundaries(self):
        field=TextInput("中文é",4)
        field.edit("left");self.assertEqual(field.cursor,2)
        field.edit("delete");self.assertEqual(field.text,"中文")
        field.edit("home");field.edit("A");field.edit("end");field.edit("backspace")
        self.assertEqual(field.text,"A中")
        field.edit("\x15");self.assertEqual((field.text,field.cursor),("",0))

    def test_viewport_keeps_insertion_point_visible(self):
        field=TextInput("/very/long/中文路径/项目",len("/very/long/中文路径/项目"))
        text,cursor=field.viewport(12)
        self.assertLess(cell_width(text),13);self.assertLess(cursor,12)
        self.assertIn("项目",text)
        field.edit("home");text,cursor=field.viewport(12)
        self.assertTrue(text.startswith("/very"));self.assertEqual(cursor,0)

    def test_ellipsis_is_cell_bounded_and_tail_preserves_name(self):
        for width in range(1,18):
            self.assertLessEqual(cell_width(ellipsize("长路径/中文项目",width)),width)
            self.assertLessEqual(cell_width(ellipsize("长路径/中文项目",width,tail=True)),width)
        self.assertTrue(ellipsize("/long/prefix/项目",8,tail=True).endswith("项目"))


class TuiTest(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix="awf-tui-");self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name).resolve();self.project=self.root/"中文项目"
        self.projects=[self.project,self.root/"另一个项目"]
        self.catalog=Catalog("codex",[Model("inherit","继承宿主","fixture",("high","max")),Model("local-model","本地模型","fixture",("high","max"))])
        for target,value in (("manager.tui.service.projects",self.projects),
                             ("manager.tui.service.roles",["xy-backend","xy-web"]),
                             ("manager.tui.service.role_settings",{"model":"inherit","effort":"high"}),
                             ("manager.tui.discover",self.catalog)):
            patcher=patch(target,return_value=value);patcher.start();self.addCleanup(patcher.stop)
        self.app=App(self.root/"state",self.root/"scan",self.project)
        self.app.theme=Theme(focus=11,selected=12,inactive=13,warning=14,error=15,muted=16,success=17,title=18)
        self.screen=RecordingScreen();self.app.screen=self.screen

    def type(self,text):
        for char in text:self.app.dispatch(char)

    def draw(self,height=30,width=100):
        self.screen=RecordingScreen(height,width);self.app.screen=self.screen
        with patch("manager.tui.curses.curs_set"):
            self.app.draw()
        for y,x,hit_width,_,_ in self.app.hits:
            self.assertGreaterEqual(y,0);self.assertLess(y,height)
            self.assertGreaterEqual(x,0);self.assertLessEqual(x+hit_width,self.screen.width-1)
        if height>=16 and width>=55:
            # 外框先绘制，任何后续文字、滚动条或高亮越界都会破坏这些格子。
            self.assertEqual(self.screen.line(0),"┏"+"━"*(width-2)+"┓")
            self.assertEqual(self.screen.line(height-1),"┗"+"━"*(width-2)+"┛")
            for y in range(1,height-1):
                self.assertIn(self.screen.cells[y][0],{"┃","┠"})
                self.assertIn(self.screen.cells[y][-1],{"┃","┨"})
            if self.app.cursor:
                y,x=self.app.cursor
                self.assertTrue(0<y<height-1 and 1<x<width-2,(y,x))
            if self.app.modal:
                layout=Layout(height,width)
                self.assertEqual(self.screen.cells[layout.bottom][layout.modal_x],"┴")
                self.assertEqual(self.screen.cells[layout.bottom][layout.modal_x+layout.modal_width-1],"┴")
                for y in range(layout.modal_top+1,layout.bottom):
                    self.assertIn(self.screen.cells[y][layout.modal_x],{"│","├"})
                    self.assertIn(self.screen.cells[y][layout.modal_x+layout.modal_width-1],{"│","┤"})
                for y,x,hit_width,_,_ in self.app.hits:
                    self.assertGreater(y,layout.modal_top);self.assertLess(y,layout.bottom)
                    self.assertGreater(x,layout.modal_x)
                    self.assertLess(x+hit_width,layout.modal_x+layout.modal_width-1)
        return self.screen

    def test_render_size_and_modal_matrix(self):
        for height,width in ((40,140),(30,110),(30,100),(24,80),(24,79),(16,55),(12,45),(3,18)):
            for modal in (None,"model","effort","manage","backups","preview","sources","help","quit","add","result","error","commands","add_mode","project_plan","versions","version_details","details"):
                with self.subTest(size=(height,width),modal=modal):
                    self.app.modal=modal;self.app.scratch={"model":"local-model","effort":"high"}
                    self.app.text=("长诊断 é 中文 "+"a"*180+"\n")*30
                    self.app.input="/长目录/"+"中文"*60;self.app.backup_rows=[]
                    self.draw(height,width)
            if height>=16 and width>=55:
                self.app.modal=None;self.app.future=Future()
                self.draw(height,width);self.assertIn("执行中",self.screen.line(Layout(height,width).status))
                self.app.future=None

    def test_only_focused_panel_has_strong_full_row_selection(self):
        screen=self.draw()
        project_hit=next(hit for hit in self.app.hits if hit[3]=="project")
        role_hit=next(hit for hit in self.app.hits if hit[3]=="role")
        y,x,width,_,_=project_hit
        self.assertNotEqual(screen.attrs[y][x],self.app.theme.selected)
        y,x,width,_,_=role_hit
        self.assertTrue(all(attr==self.app.theme.selected for attr in screen.attrs[y][x:x+width]))
        self.app.dispatch("left");screen=self.draw()
        y,x,width,_,_=next(hit for hit in self.app.hits if hit[3]=="project")
        self.assertTrue(all(attr==self.app.theme.selected for attr in screen.attrs[y][x:x+width]))

    def test_footer_is_bounded_and_matches_available_bindings(self):
        for width in (55,80,140):
            lines=self.app.footer_lines(width-2)
            self.assertLessEqual(len(lines),2)
            self.assertTrue(all(cell_width(line)<=width-2 for line in lines))
            self.assertIn(":", " ".join(lines));self.assertIn("?", " ".join(lines))
        self.app.dispatch("g");self.app.dispatch("?")
        self.assertIn("搜索",self.app.text)
        self.app.dispatch("esc");self.assertEqual(self.app.modal,"manage")

    def test_model_search_accepts_without_confirming_and_preserves_real_index(self):
        self.app.dispatch("enter");self.app.dispatch("/");self.type("local")
        self.app.dispatch("enter")
        self.assertEqual(self.app.modal,"model");self.assertEqual(self.app.index,1)
        self.assertFalse(self.app.drafts)
        self.app.dispatch("enter");self.assertEqual(self.app.modal,"effort")
        self.app.dispatch("esc");self.assertEqual(self.app.modal,"model")
        self.assertEqual(self.app.index,1)

    def test_search_cancel_restores_selection_and_zero_results_do_not_confirm(self):
        self.app.dispatch("enter");self.app.dispatch("/");self.type("not-a-model")
        self.app.dispatch("enter");self.app.dispatch("enter")
        self.assertEqual(self.app.modal,"model");self.assertIsNone(self.app.future)
        self.assertFalse(self.app.drafts)
        self.app.dispatch("esc");self.app.dispatch("/");self.type("local")
        self.app.dispatch("esc");self.assertEqual(self.app.index,0)
        self.assertEqual(self.app.filter_text,"")

    def test_project_filter_uses_source_indices_not_visible_offsets(self):
        self.app.projects=[self.root/f"project-{i:02}" for i in range(30)]
        self.app.project_index=0;self.app.pane="projects"
        self.app.dispatch("/");self.type("project-29");self.app.dispatch("enter")
        self.assertEqual(self.app.project_index,29);self.assertEqual(self.app.project,self.root/"project-29")
        self.app.dispatch("enter");self.assertEqual(self.app.pane,"roles")
        self.assertEqual(self.app.filter_text,"")

    def test_project_filter_empty_keeps_registration_entry_without_writing(self):
        self.app.pane="projects";self.app.dispatch("/");self.type("does-not-exist");self.app.dispatch("enter")
        self.assertIn("登记",self.draw().text())
        with patch("manager.tui.service.apply_project") as apply:
            self.app.dispatch("enter");apply.assert_not_called()
        self.app.dispatch("a");self.assertEqual(self.app.modal,"add")

    def test_home_end_and_paging_use_visible_entries(self):
        self.app.roles_cache[(str(self.project),"codex")]=[f"role-{i:02}" for i in range(40)]
        self.draw();self.app.dispatch("end");self.assertEqual(self.app.role_index,39)
        self.app.dispatch("home");self.assertEqual(self.app.role_index,0)
        self.app.dispatch("pagedown");self.assertGreater(self.app.role_index,1)
        self.app.dispatch("/");self.type("role-3");self.app.dispatch("enter")
        self.app.dispatch("home");self.assertEqual(self.app.role_index,30)
        self.app.dispatch("end");self.assertEqual(self.app.role_index,39)

    def test_refresh_and_host_switch_preserve_role_identity(self):
        self.app.role_index=1;self.assertEqual(self.app.role,"xy-web")
        with patch("manager.tui.service.roles",return_value=["xy-web","xy-qa","xy-backend"]):
            self.app.dispatch("r");self.assertEqual(self.app.role,"xy-web")
        with patch("manager.tui.service.roles",return_value=["xy-qa","xy-web"]):
            self.app.dispatch("2");self.assertEqual(self.app.role,"xy-web")
        with patch("manager.tui.service.roles",return_value=["xy-qa"]):
            self.app.dispatch("3");self.assertEqual(self.app.role,"xy-qa")

    def test_platform_tab_cycle_preserves_project_pane_role_and_cross_scope_drafts(self):
        self.app.role_index=1
        self.app.roles_cache[(str(self.project),"claude")]=["xy-web","xy-qa"]
        self.app.roles_cache[(str(self.project),"antigravity")]=["xy-qa","xy-web"]
        for project in self.projects:
            for host in HOSTS:
                scope=(str(project),host,"xy-web")
                self.app.drafts[scope]={"model":"inherit","effort":"high"}
                self.app.expected[scope]={"model":"inherit","effort":"inherit"}
                self.app.source_stamps[scope]="fixture-"+host
        before=(dict(self.app.drafts),dict(self.app.expected),dict(self.app.source_stamps))
        for pane in ("roles","projects"):
            self.app.pane=pane
            for key,host in (("tab","claude"),("tab","antigravity"),("tab","codex"),
                             ("backtab","antigravity"),("backtab","claude"),("backtab","codex")):
                self.app.dispatch(key)
                self.assertEqual((self.app.host,self.app.pane,self.app.project,self.app.role),
                                 (host,pane,self.project,"xy-web"))
                self.assertEqual((self.app.drafts,self.app.expected,self.app.source_stamps),before)

    def test_catalog_scope_reuses_result_and_refresh_reloads_only_current_host(self):
        other=(str(self.project),"claude")
        self.app.catalogs[other]=Catalog("claude")
        refreshed=Catalog("codex",[Model("inherit","继承","native"),Model("dynamic","动态模型","native",("high",))])
        with patch("manager.tui.discover",side_effect=[self.catalog,refreshed]) as query:
            self.app.dispatch("enter");self.draw();self.draw()
            self.app.dispatch("esc");self.app.role_index=1;self.app.dispatch("enter");self.draw()
            self.assertEqual(query.call_count,1)
            self.app.dispatch("esc");self.app.dispatch("r");self.app.dispatch("enter");self.draw();self.draw()
            self.assertEqual(query.call_count,2)
            self.assertEqual(self.app.catalogs[other].host,"claude")
            self.assertIn(("动态模型","dynamic"),self.app.options())

    def test_save_staging_cancel_and_success_clear_only_the_applied_scope(self):
        # 检查草稿/确认与副作用边界，真实落盘和失败冲突另由同文件PTY消费者验证。
        with patch('manager.tui.service.commit') as commit:
            self.app.dispatch('m');self.app.dispatch('enter');self.app.dispatch('enter')
            self.assertFalse(self.app.pending());self.assertIn('无改动',self.app.toast)
            self.assertNotIn('已同步',self.draw().line(0));commit.assert_not_called()
            self.app.dispatch('m');self.app.dispatch('down');self.app.dispatch('enter')
            self.assertFalse(self.app.pending());commit.assert_not_called()
            self.app.dispatch('end');self.app.dispatch('enter')
            self.assertTrue(self.app.pending());self.assertIn('尚未保存',self.app.toast)
            other=(str(self.projects[1]),'claude','xy-qa')
            self.app.drafts[other]={'model':'inherit','effort':'high'}
            self.app.catalogs[other[:2]]=Catalog('claude')
            with patch('manager.tui.service.prepare',return_value=[service.Change('fixture',b'a',b'b',0o600)]):
                self.app.dispatch('s');self.assertEqual(self.app.modal,'preview');commit.assert_not_called()
                self.app.dispatch('esc');self.assertTrue(self.app.pending());commit.assert_not_called()
                self.app.dispatch('s')
            with ThreadPoolExecutor(max_workers=1) as self.app.executor, \
                 patch('manager.tui.service.backup_summary',return_value='fixture backup'):
                commit.return_value='fixture-id'
                self.app.dispatch('enter');self.app.future.result(timeout=2);self.app.poll_job()
            self.assertFalse(self.app.pending());self.assertIn(other,self.app.drafts)
            self.assertNotIn((str(self.project),'codex'),self.app.catalogs)
            self.assertIn(other[:2],self.app.catalogs)
            self.assertIn(self.project.name,self.app.toast);self.assertIn('Codex',self.app.toast)
            self.app.dispatch('esc');self.assertIn('已保存',self.app.toast)

    def test_project_dividers_scroll_and_mouse_identity_in_narrow_monochrome(self):
        self.app.projects=[self.root/f'中文项目-{index:02}' for index in range(12)]
        self.app.project_index=0;self.app.pane='projects';self.app.theme=Theme()
        screen=self.draw(16,55)
        first=next(hit for hit in self.app.hits if hit[3]=='project' and hit[4]==0)
        self.assertIn('中文项目-00',screen.line(first[0]))
        self.assertIn('待刷新',screen.line(first[0]+1))
        self.assertIn('──',screen.line(first[0]+2))
        self.assertFalse(any(hit[0]==first[0]+2 and hit[3]=='project' for hit in self.app.hits))
        self.assertTrue(all(key in screen.line(Layout(16,55).workflow) for key in ('待刷新','[o]','[p]')))
        # 点击项目分隔和外边框不应更改选择，不能扩大条目命中范围来补偿新布局。
        for y,x in ((first[0]+2,first[1]),(first[0],0),(Layout(16,55).bottom,first[1])):
            self.screen.keys=[curses.KEY_MOUSE]
            with patch('manager.tui.curses.getmouse',return_value=(0,x,y,0,curses.BUTTON1_CLICKED)):
                self.app.read_input(self.screen)
            self.assertEqual(self.app.project_index,0)
        self.app.dispatch('pagedown');self.assertGreater(self.app.project_index,0)
        self.app.dispatch('end');screen=self.draw(16,55)
        self.assertEqual(self.app.project_index,len(self.app.projects))
        # 仅当前视口的名称/状态行可以命中，鼠标不依赖项目条目的物理行号。
        # 最小尺寸只容纳一项；先从末尾登记入口返回最后一个项目再检查详情行命中。
        self.app.dispatch('up');self.draw(16,55)
        hit=next(hit for hit in self.app.hits if hit[3]=='project' and hit[4]<len(self.app.projects))
        y,x,width,_,index=hit;self.screen.keys=[curses.KEY_MOUSE]
        with patch('manager.tui.curses.getmouse',return_value=(0,x,y+1,0,curses.BUTTON1_CLICKED)):
            self.app.read_input(self.screen)
        self.assertEqual(self.app.project_index,index);self.assertIsNone(self.app.modal)

    def test_removed_role_draft_stays_selectable_and_individually_discardable(self):
        key=self.app.scope();other=(str(self.project),"claude","xy-qa")
        self.app.drafts[key]={"model":"local-model","effort":"high"}
        self.app.expected[key]={"model":"inherit","effort":"high"}
        self.app.drafts[other]={"model":"inherit","effort":"inherit"}
        with patch("manager.tui.service.roles",return_value=["xy-web"]):
            self.app.dispatch("r")
            self.assertEqual(self.app.role,"xy-backend")
            self.assertIn("已移除",self.draw().text())
            self.app.dispatch("enter");self.assertIsNone(self.app.modal)
            self.assertIn("已移除",self.app.toast)
            self.app.dispatch("u")
            self.assertNotIn(key,self.app.drafts);self.assertNotIn(key,self.app.expected)
            self.assertIn(other,self.app.drafts);self.assertEqual(self.app.role,"xy-web")
            self.assertNotIn("已移除",self.draw().line(6))

    def test_paging_while_searching_moves_selection_without_accepting(self):
        self.app.roles_cache[(str(self.project),"codex")]=[f"role-{i:02}" for i in range(40)]
        self.app.dispatch("/");self.type("role-");self.draw()
        self.app.dispatch("pagedown")
        self.assertGreater(self.app.role_index,1);self.assertTrue(self.app.searching)
        self.assertEqual(self.app.search_input.text,"role-")

    def test_job_results_never_return_to_old_confirmation(self):
        for fails in (False,True):
            with self.subTest(fails=fails),ThreadPoolExecutor(max_workers=1) as executor:
                self.app.frames=[];self.app.modal=None
                # 当前中央写操作使用统一计划确认页，结果或错误返回管理菜单，
                # 不复活已经消费的确认页，以免用户重复提交同一事务。
                self.app.dispatch("g");self.app.show_view("project_plan");self.app.executor=executor
                def operation():
                    if fails:raise ValueError("fixture failure")
                    return "fixture result"
                self.app.start_job(operation)
                try:self.app.future.result(timeout=2)
                except ValueError:pass
                self.app.poll_job();self.assertEqual(self.app.modal,"error" if fails else "result")
                self.app.dispatch("esc");self.assertEqual(self.app.modal,"manage")
                self.app.dispatch("esc");self.assertIsNone(self.app.modal)

    def test_text_views_home_end_and_paging(self):
        self.app.modal="preview";self.app.text="\n".join(str(i) for i in range(150))
        self.app.dispatch("end");self.draw();self.assertGreater(self.app.scroll,100)
        self.app.dispatch("home");self.assertEqual(self.app.scroll,0)
        self.app.dispatch("pagedown");self.assertGreater(self.app.scroll,0)

    def test_search_text_has_priority_over_all_letter_shortcuts(self):
        self.app.dispatch("enter");self.app.dispatch("/");self.type("qsug123?:op")
        self.assertEqual(self.app.modal,"model");self.assertFalse(self.app.done)
        self.assertEqual(self.app.search_input.text,"qsug123?:op")
        self.app.dispatch("left");cursor=self.app.search_input.cursor
        for key in ("tab","backtab"):self.app.dispatch(key)
        self.assertEqual(self.app.search_input.cursor,cursor)
        self.app.dispatch("right");self.assertEqual(self.app.search_input.cursor,len(self.app.search_input.text))
        self.assertEqual((self.app.host,self.app.pane),("codex","roles"))
        self.app.dispatch("esc")
        for key in ("tab","backtab","left","right"):self.app.dispatch(key)
        self.assertEqual((self.app.modal,self.app.host,self.app.pane),("model","codex","roles"))

    def test_path_editing_and_read_input_keys(self):
        self.app.dispatch("a");self.type("/tmp/项目")
        self.app.dispatch("home");self.app.dispatch("right");self.type("x")
        self.assertEqual(self.app.input,"/xtmp/项目")
        self.screen.keys=[curses.KEY_END,curses.KEY_BACKSPACE,curses.KEY_LEFT,curses.KEY_DC]
        for _ in range(4):self.app.read_input(self.screen)
        self.assertEqual(self.app.input,"/xtmp/")
        self.app.dispatch("\x15");self.type("qsug123?:op")
        self.assertEqual(self.app.input,"qsug123?:op");self.assertEqual(self.app.modal,"add")
        for modal in ("add","commands"):
            self.app.modal=modal;self.app.input="中文路径"
            self.app.dispatch("left");cursor=self.app.editor.cursor
            for key in ("tab","backtab"):self.app.dispatch(key)
            self.assertEqual(self.app.editor.cursor,cursor)
            self.app.dispatch("right");self.assertEqual(self.app.editor.cursor,len(self.app.input))
            self.assertEqual((self.app.modal,self.app.host,self.app.pane),(modal,"codex","roles"))

    def test_long_path_cursor_is_visible(self):
        self.app.dispatch("a");self.app.input="/prefix/"+"中文"*60+"/项目"
        screen=self.draw(16,55)
        self.assertIsNotNone(screen.cursor);self.assertIn("项目",screen.line(screen.cursor[0]))

    def test_input_cursor_does_not_flicker_on_repeated_redraws(self):
        self.app.dispatch("a")
        with patch("manager.tui.curses.curs_set") as cursor:
            self.app.draw();self.app.draw()
            self.assertEqual([call.args for call in cursor.call_args_list],[(1,)])
            self.assertEqual(self.screen.cursor,self.app.cursor)
            self.app.dispatch("esc");self.app.draw()
            self.assertEqual([call.args for call in cursor.call_args_list],[(1,),(0,)])

    def test_palette_reuses_preview_and_never_bypasses_confirmation(self):
        self.app.drafts[self.app.scope()]={"model":"local-model","effort":"high"}
        self.app.dispatch(":");self.type("预览")
        with patch.object(self.app,"act",wraps=self.app.act) as act,patch("manager.tui.service.prepare",return_value=[]),patch("manager.tui.service.commit") as commit:
            self.app.expected[self.app.scope()]={"model":"inherit","effort":"high"}
            self.app.dispatch("enter")
            self.assertEqual(self.app.modal,"preview");commit.assert_not_called()
            self.assertTrue(any(call.args[0]=="preview" for call in act.call_args_list))

    def test_palette_disables_unavailable_actions(self):
        self.app.dispatch(":");self.type("预览");self.app.dispatch("enter")
        self.assertEqual(self.app.modal,"commands");self.assertIn("没有",self.app.toast)
        self.assertIsNone(self.app.future)

    def test_help_returns_to_model_selection_with_filter(self):
        self.app.dispatch("enter");self.app.dispatch("/");self.type("local");self.app.dispatch("enter")
        self.app.dispatch("?");self.assertEqual(self.app.modal,"help")
        self.app.dispatch("esc");self.assertEqual(self.app.modal,"model")
        self.assertEqual(self.app.filter_text,"local");self.assertEqual(self.app.index,1)

    def test_mouse_only_selects_including_add_and_menu(self):
        for menu,kind in ((None,"role"),("manage","option")):
            self.app.modal=menu;self.draw()
            y,x,_,_,_=next(hit for hit in self.app.hits if hit[3]==kind)
            self.screen.keys=[curses.KEY_MOUSE]
            with patch("manager.tui.curses.getmouse",return_value=(0,x,y,0,curses.BUTTON1_CLICKED)):
                self.app.read_input(self.screen)
            self.assertEqual(self.app.modal,menu)
        self.app.modal=None;self.draw()
        y,x,_,_,_=next(hit for hit in self.app.hits if hit[3]=="project" and hit[4]==len(self.app.projects))
        self.screen.keys=[curses.KEY_MOUSE]
        with patch("manager.tui.curses.getmouse",return_value=(0,x,y,0,curses.BUTTON1_CLICKED)):
            self.app.read_input(self.screen)
        self.assertIsNone(self.app.modal);self.assertIsNone(self.app.project)

    def test_quit_protects_drafts_in_other_scopes_and_small_windows(self):
        self.app.drafts[("other-project","claude","xy-qa")]={"model":"inherit","effort":"inherit"}
        self.draw(10,45);self.screen.keys=["q"];self.app.read_input(self.screen)
        self.assertEqual(self.app.modal,"quit");self.assertFalse(self.app.done)
        self.app.dispatch("esc");self.assertFalse(self.app.done)
        self.app.interrupt();self.assertEqual(self.app.modal,"quit")
        self.draw(10,45);self.app.dispatch("enter")
        self.assertTrue(self.app.done);self.assertEqual(self.app.exit_code,130)

    def test_tiny_window_cannot_blindly_discard_drafts(self):
        self.app.drafts[self.app.scope()]={"model":"inherit","effort":"inherit"}
        self.draw(2,15);self.app.dispatch("q");self.app.dispatch("enter")
        self.assertFalse(self.app.done);self.assertTrue(self.app.drafts)
        self.app.dispatch("esc");self.assertIsNone(self.app.modal)

    def test_busy_only_reports_supported_cancellation(self):
        self.app.future=Future();self.app.job_cancellable=False
        self.app.interrupt();self.assertFalse(self.app.cancel_job.is_set());self.assertFalse(self.app.done)
        self.app.job_cancellable=True;self.app.interrupt();self.app.interrupt()
        self.assertTrue(self.app.cancel_job.is_set());self.assertIsNotNone(self.app.future)
        self.assertIn("等待",self.app.toast)

    def test_monochrome_and_unsupported_default_background_fall_back(self):
        with patch("manager.tui_support.curses.has_colors",return_value=False):
            theme=Theme.create();self.assertNotEqual(theme.selected,theme.text)
        with patch("manager.tui_support.curses.has_colors",return_value=True),patch("manager.tui_support.curses.start_color"),patch("manager.tui_support.curses.use_default_colors",side_effect=curses.error()):
            theme=Theme.create();self.assertNotEqual(theme.selected,theme.text)
        self.app.theme=theme;self.draw()

    def test_directional_panes_are_idempotent_and_model_effort_stay_independent(self):
        self.assertEqual(self.app.role_column,"model")
        for _ in range(2):
            self.app.dispatch("left");self.assertEqual(self.app.pane,"projects")
        self.app.dispatch("down");self.assertEqual(self.app.project_index,1)
        self.app.dispatch("up");self.assertEqual(self.app.project_index,0)
        for _ in range(2):
            self.app.dispatch("right");self.assertEqual(self.app.pane,"roles")
        self.app.dispatch("down");self.assertEqual(self.app.role_index,1)
        self.app.dispatch("up");self.assertEqual(self.app.role_index,0)
        self.assertEqual(self.app.role_column,"model")
        self.app.dispatch("enter");self.assertEqual(self.app.modal,"model")
        self.app.dispatch("esc");self.assertIsNone(self.app.modal)
        self.app.dispatch("m");self.assertEqual(self.app.modal,"model")
        self.app.dispatch("esc")
        self.app.dispatch("e");self.assertEqual(self.app.modal,"effort")
        options=self.app.options();self.assertTrue(len(options)>1)
        self.app.index=len(options)-1;val=options[-1][1]
        self.app.dispatch("enter");self.assertIsNone(self.app.modal)
        self.assertEqual(self.app.drafts[self.app.scope()]["effort"],val)
        self.assertEqual(self.app.drafts[self.app.scope()]["model"],"inherit")
        self.app.role_column="effort"
        for key in ("left","left","right","right"):self.app.dispatch(key)
        self.assertEqual(self.app.role_column,"effort")
        self.app.dispatch("enter");self.assertEqual(self.app.modal,"effort")

    def test_effort_options_selectable_levels_for_hosts(self):
        self.app.host_index=1;self.app.scratch={"model":"inherit","effort":"inherit"}
        self.app.modal="effort"
        # 已知模型能力时只提供证实的档位，继承仍始终可选。
        model_levels=[v for _,v in self.app.options()]
        self.assertEqual(model_levels,["inherit","high","max"])
        # 未知模型能力时提供宿主允许写入的标准值，不能把后备选项回填成模型能力证据。
        with patch.object(self.app,"catalog",return_value=Catalog("claude",[Model("inherit","继承","f",())])):
            claude_levels=[v for _,v in self.app.options()]
            self.assertEqual(claude_levels,["inherit","low","medium","high","xhigh","max"])
        self.app.host_index=0;self.app.scratch={"model":"inherit","effort":"inherit"}
        with patch.object(self.app,"catalog",return_value=Catalog("codex",[Model("inherit","继承","f",())])):
            codex_levels=[v for _,v in self.app.options()]
            self.assertEqual(codex_levels,["inherit","none","minimal","low","medium","high","xhigh","max"])
        self.app.host_index=2
        self.assertEqual(self.app.unavailable("effort"),"Antigravity 静态角色仅支持继承")

    def test_mouse_selects_role_column_model_or_effort(self):
        self.draw()
        role_hit=next(hit for hit in self.app.hits if hit[3]=="role")
        y,col,width,_,index=role_hit
        self.screen.keys=[curses.KEY_MOUSE]
        with patch("manager.tui.curses.getmouse",return_value=(0,col+width-5,y,0,curses.BUTTON1_CLICKED)):
            self.app.read_input(self.screen)
        self.assertEqual(self.app.role_column,"effort")
        self.screen.keys=[curses.KEY_MOUSE]
        with patch("manager.tui.curses.getmouse",return_value=(0,col+5,y,0,curses.BUTTON1_CLICKED)):
            self.app.read_input(self.screen)
        self.assertEqual(self.app.role_column,"model")

    def test_add_plan_cancel_preserves_path_and_does_not_write(self):
        self.project.mkdir()
        with ThreadPoolExecutor(max_workers=1) as self.app.executor:
            self.app.dispatch("a");self.type(str(self.project));self.app.dispatch("enter")
            self.assertEqual(self.app.modal,"add_mode")
            self.assertEqual(self.app.index,0)
            self.app.dispatch("enter");self.app.future.result(timeout=5);self.app.poll_job()
            self.assertEqual(self.app.modal,"project_plan")
            self.assertIn("仅登记项目",self.app.text)
            self.assertFalse((self.root/"state").exists());self.assertEqual([],list(self.project.iterdir()))
            self.app.dispatch("esc");self.assertEqual(self.app.modal,"add_mode")
            self.app.dispatch("esc");self.assertEqual(self.app.modal,"add")
            self.assertEqual(self.app.input,str(self.project))
            self.app.dispatch("esc");self.assertIsNone(self.app.modal)

    def test_conflicting_plan_has_readable_reason_and_no_confirm_binding(self):
        before={"project":str(self.project),"state":"enabled","enabled":False,"runtime_binding":None,
                "previous_binding":None,"hosts":[],"managed_paths":[],"conflicts":[]}
        summary={"action":"disable","project":str(self.project),"state_dir":str(self.root/"state"),
                 "registered_before":True,"registered_after":True,"runtime":None,"status_before":before,
                 "changes":[],"can_apply":False,"conflicts":[{"path":"中文/受管路径","reason":"用户手动修改，停止覆盖"}]}
        class ConflictingPlan:
            action="disable"
            def __init__(self,project,summary):self.project=project;self.summary=summary
        self.app.project_plan=ConflictingPlan(self.project,summary)
        self.app.show_view("project_plan");self.app.text=project_plan_text(summary)
        with patch("manager.tui.service.apply_project") as apply:
            self.app.dispatch("enter");apply.assert_not_called()
        self.assertFalse(any(row.action == "confirm" for row in self.app.bindings()))
        self.assertIn("停止覆盖",self.app.text);self.assertIn("修复",self.app.text)
        for size in ((24,80),(16,55)):
            self.draw(*size);self.assertIn("Esc",self.screen.text())
        self.app.dispatch("esc");self.assertIsNone(self.app.modal)

    def test_project_status_render_uses_cache_and_textual_state_in_monochrome(self):
        identifier="0123456789abcdef"*4
        row={"project":str(self.project),"state":"disabled","enabled":False,"registered":True,
             "runtime_binding":{"content_id":identifier},"previous_binding":None,
             "hosts":list(HOSTS),"managed_paths":["中文/超长路径/é"],"conflicts":[]}
        self.app.project_rows[str(self.project)]=row;self.app.theme=Theme()
        with patch("manager.tui.service.project_status") as status,patch("manager.tui.service.project_summaries") as summaries,patch("manager.tui.runtime_store.list_cores") as versions:
            self.draw();self.draw();status.assert_not_called();summaries.assert_not_called();versions.assert_not_called()
        text=self.screen.text();self.assertIn("已停用",text);self.assertIn(identifier[:8],text)
        for width in (80,100,140):
            screen=self.draw(24,width)
            name_row=next(hit[0] for hit in self.app.hits if hit[3] == "project" and hit[4] == 0)
            self.assertIn(self.project.name,screen.line(name_row))
            self.assertIn("已停用",screen.line(name_row+1));self.assertIn(identifier[:8],screen.line(name_row+1))
        detail=status_text(row,dict(zip(HOSTS,("Codex","Claude Code","Antigravity"))))
        self.assertIn(identifier,detail);self.assertIn("前次内容 ID  无",detail)
        self.assertTrue(all(label in detail for label in ("Codex","Claude Code","Antigravity")))
        row["conflicts"]=[{"path":"runtime_binding","reason":"固定核心版本缺失"}]
        self.assertIn("冲突",status_text(row,{}))

    def test_busy_job_blocks_duplicate_actions_and_waits_for_real_settlement(self):
        release=Event();started=Event()
        def operation():
            started.set();release.wait(5)
            return "真实结算结果"
        with ThreadPoolExecutor(max_workers=1) as self.app.executor:
            self.app.start_job(operation,name="测试事务",cancellable=True)
            self.assertTrue(started.wait(2));future=self.app.future
            host,pane=self.app.host,self.app.pane
            for key in ("tab","backtab","left","right","2"):self.app.dispatch(key)
            self.assertEqual((self.app.host,self.app.pane),(host,pane))
            self.app.dispatch("a");self.app.dispatch("enter");self.app.start_job(lambda:"不应执行")
            self.assertIs(self.app.future,future)
            self.app.interrupt();self.assertTrue(self.app.cancel_job.is_set());self.assertFalse(self.app.done)
            self.assertIn("真实结果",self.app.toast)
            release.set();future.result(timeout=5);self.app.poll_job()
            self.assertEqual(self.app.modal,"result");self.assertEqual(self.app.text,"真实结算结果")

    def test_empty_versions_and_unavailable_rollback_are_distinct(self):
        self.app.project_rows[str(self.project)]={"state":"unmanaged","previous_binding":None,"runtime_binding":None}
        self.app.modal="versions";self.app.version_rows=[]
        self.assertIn("尚无已导入版本",self.draw().text())
        self.app.dispatch("enter");self.assertIsNone(self.app.future)
        self.app.dispatch("esc");self.app.dispatch("g")
        action_index=next(i for i,(_,action) in enumerate(self.app.options()) if action == "rollback")
        self.app.index=action_index;self.app.dispatch("enter")
        self.assertEqual(self.app.modal,"manage");self.assertIn("没有前次中央版本",self.app.toast)

    def tearDown(self):
        self.assertFalse((self.root/"state").exists())


class TerminalCells:
    """读取真实 PTY 的 curses 字节流，以字符格断言当前屏幕，不把历史文本冒充当前视图。

    这里只实现本终端测试实际使用的光标、擦除、滚动区和重复字符序列；属性序列被忽略，
    颜色/反色的语义由 RecordingScreen 补充验证。它不替代完整终端或屏幕阅读器。
    """
    def __init__(self,height=30,width=100):
        self.decoder=codecs.getincrementaldecoder("utf-8")("replace");self.pending=""
        self.saved=(0,0);self.last=" ";self.resize(height,width)

    def resize(self,height,width):
        self.height,self.width=height,width;self.row=self.col=0
        self.scroll_top=0;self.scroll_bottom=height-1
        self.cells=[[" " for _ in range(width)] for _ in range(height)]

    def scroll_up(self,count=1):
        # ncurses 通过滚动区优化局部重绘，不能把它当成整屏清空。
        # 只移动上下边界内的完整字符格行，保留框线及区域外正文；每个补行独立创建。
        count=min(count,self.scroll_bottom-self.scroll_top+1)
        self.cells[self.scroll_top:self.scroll_bottom+1]=(
            self.cells[self.scroll_top+count:self.scroll_bottom+1]+
            [[" "]*self.width for _ in range(count)])

    def linefeed(self):
        # LF 保持当前列；到滚动区底部时上滚区域，不能仅把光标夹在物理屏幕底部，
        # 否则上一选择器的正文会残留，未来 visible() 也可能误认历史内容仍在当前帧。
        if self.row == self.scroll_bottom:self.scroll_up()
        else:self.row=min(self.height-1,self.row+1)

    def write_char(self,char):
        size=cell_width(char)
        if not size:
            if self.col:self.cells[self.row][self.col-1]+=char
            return
        self.col=min(self.col,self.width-1)
        self.cells[self.row][self.col]=char
        if size == 2 and self.col+1<self.width:self.cells[self.row][self.col+1]=""
        self.col=min(self.width,self.col+size);self.last=char

    def control(self,parameters,command):
        values=[int(part) if part.isdigit() else 0 for part in parameters.lstrip("?<>").split(";")]
        first=values[0] if values else 0;n=first or 1
        if command in {"H","f"}:self.row=max(0,(first or 1)-1);self.col=max(0,(values[1] if len(values)>1 and values[1] else 1)-1)
        elif command == "A":self.row-=n
        elif command == "B":self.row+=n
        elif command == "C":self.col+=n
        elif command == "D":self.col-=n
        elif command in {"G","`"}:self.col=n-1
        elif command == "d":self.row=n-1
        elif command == "E":self.row+=n;self.col=0
        elif command == "F":self.row-=n;self.col=0
        elif command == "r":
            top=(first or 1)-1
            bottom=(values[1] if len(values)>1 and values[1] else self.height)-1
            if 0<=top<bottom<self.height:
                # DECSTBM 的缺省范围是整屏，成功设置边界后光标归位；
                # 无效范围不改变当前区域，不能把终端参数当成任意列表切片。
                self.scroll_top,self.scroll_bottom=top,bottom;self.row=self.col=0
        elif command == "S":self.scroll_up(n)
        elif command == "J":
            if first in {2,3}:self.cells=[[" " for _ in range(self.width)] for _ in range(self.height)]
            elif first == 0:
                self.cells[self.row][self.col:]=[" "]*(self.width-self.col)
                for row in range(self.row+1,self.height):self.cells[row]=[" "]*self.width
        elif command == "K":
            start,end=(0,self.width) if first == 2 else (0,self.col+1) if first == 1 else (self.col,self.width)
            self.cells[self.row][start:end]=[" "]*(end-start)
        elif command == "X":
            end=min(self.width,self.col+n);self.cells[self.row][self.col:end]=[" "]*(end-self.col)
        elif command == "P":self.cells[self.row]=(self.cells[self.row][:self.col]+self.cells[self.row][self.col+n:]+[" "]*n)[:self.width]
        elif command == "@":self.cells[self.row]=(self.cells[self.row][:self.col]+[" "]*n+self.cells[self.row][self.col:])[:self.width]
        elif command == "b":
            for _ in range(n):self.write_char(self.last)
        elif command == "s":self.saved=(self.row,self.col)
        elif command == "u":self.row,self.col=self.saved
        self.row=max(0,min(self.height-1,self.row));self.col=max(0,min(self.width-1,self.col))

    def feed(self,data):
        self.pending+=self.decoder.decode(data)
        while self.pending:
            char=self.pending[0]
            if char == "\x1b":
                if len(self.pending)<2:return
                if self.pending[1] == "[":
                    match=re.match(r"\x1b\[([0-?]*)([ -/]*)([@-~])",self.pending)
                    if not match:return
                    self.control(match[1],match[3]);self.pending=self.pending[match.end():];continue
                if self.pending[1] in {"(",")"}:
                    if len(self.pending)<3:return
                    self.pending=self.pending[3:];continue
                if self.pending[1] == "7":self.saved=(self.row,self.col)
                elif self.pending[1] == "8":self.row,self.col=self.saved
                self.pending=self.pending[2:];continue
            self.pending=self.pending[1:]
            if char == "\r":self.col=0
            elif char == "\n":self.linefeed()
            elif char == "\b":self.col=max(0,self.col-1)
            elif char.isprintable():self.write_char(char)

    def text(self):return "\n".join("".join(row) for row in self.cells)


class TerminalCellsTest(unittest.TestCase):
    """直接覆盖真实流曾漏解的滚动语义，不启动额外项目或终端夹具。"""

    def populated(self):
        terminal=TerminalCells(6,12)
        for row,text in enumerate(("页头","甲中文","乙","丙","旧正文","页脚"),1):
            terminal.feed(f"\x1b[{row};1H{text}".encode())
        return terminal

    def test_scroll_region_csi_scroll_preserves_outside_and_cursor(self):
        terminal=self.populated()
        # CSI 可以跨 PTY 块到达，完整参数到达前不能提前改变区域。
        terminal.feed(b"\x1b[2;");self.assertEqual((terminal.scroll_top,terminal.scroll_bottom),(0,5))
        terminal.feed(b"5r");self.assertEqual((terminal.scroll_top,terminal.scroll_bottom,terminal.row,terminal.col),(1,4,0,0))
        terminal.feed(b"\x1b[4;3H\x1b[2S")
        self.assertEqual(["".join(row).rstrip() for row in terminal.cells],["页头","丙","旧正文","","","页脚"])
        self.assertEqual((terminal.row,terminal.col),(3,2))
        terminal.feed(b"\x1b[S\x1b[99S")
        self.assertEqual(["".join(row).rstrip() for row in terminal.cells],["页头","","","","","页脚"])
        self.assertNotIn("旧正文",terminal.text())
        self.assertEqual((terminal.row,terminal.col),(3,2))
        terminal.feed(b"\x1b[4;2r")
        self.assertEqual((terminal.scroll_top,terminal.scroll_bottom),(1,4))
        terminal.feed(b"\x1b[r")
        self.assertEqual((terminal.scroll_top,terminal.scroll_bottom,terminal.row,terminal.col),(0,5,0,0))
        terminal.resize(3,8);self.assertEqual((terminal.scroll_top,terminal.scroll_bottom),(0,2))

    def test_bottom_linefeed_scrolls_region_and_keeps_column(self):
        terminal=self.populated();terminal.feed(b"\x1b[2;5r\x1b[5;3H\n")
        self.assertEqual(["".join(row).rstrip() for row in terminal.cells],["页头","乙","丙","旧正文","","页脚"])
        self.assertEqual((terminal.row,terminal.col),(4,2))
        terminal.feed(b"Z");self.assertEqual("".join(terminal.cells[4]).rstrip(),"  Z")
        # 区域外的物理屏幕底部 LF 不滚动该区域；恢复整屏边界后才滚动整屏。
        before=[list(row) for row in terminal.cells]
        terminal.feed(b"\x1b[6;1H\n");self.assertEqual(terminal.cells,before)
        terminal.feed(b"\x1b[r\x1b[6;1H\n")
        self.assertEqual(["".join(row).rstrip() for row in terminal.cells],["乙","丙","旧正文","  Z","页脚",""])


class ProjectTuiIntegrationTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary=tempfile.TemporaryDirectory(prefix="central-tui-")
        cls.root=Path(cls.temporary.name).resolve();cls.state=cls.root/"state";cls.source=cls.root/"minimal-source"
        # 复用中央项目既有的最小协议夹具形状：只复制必需模块/模板，绝不复制整仓候选。
        for directory in runtime_store.CORE_DIRECTORIES:(cls.source/directory).mkdir(parents=True)
        def put(relative,body):
            path=cls.source/relative;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(body)
        for name in runtime_store.SETUP_FILES:put(name,b"#!/bin/sh\nexit 0\n")
        # apply 通过固定核心的真实 reader 验收发布；中央启停现在还要校验签名 Hook。
        # 只补齐这条真实消费链的直接依赖，不复制完整源包、宿主环境或独立运行时。
        for name in ("lib/platform_fs.py","lib/runtime_store.py","lib/runtime_project.py","lib/runtime_bridge.py","lib/claude_options.py",
                     "lib/claude_instructions.py","lib/workflow_hook_install.py","lib/workflow_hook_settings.py",
                     "lib/workflow_hooks.py","lib/windows_hook_command.py","lib/merge_codex_config.py",
                     "lib/shared_core_skills.py","lib/role_models.py","lib/python_runtime.sh","lib/validate_antigravity_artifacts.py",
                     "manager/runtime_service.py","manager/__init__.py","templates/project.yaml.example","templates/docs/PROJECT.md",
                     "roles/xy-qa.md","roles/xy-uiux.md","platforms/shared/core-skills.txt"):
            put(name,(PACK/name).read_bytes())
        put("product/WORKFLOW.md","# TUI 固定版本甲\n".encode());put("product/GLOBAL_CONSTRAINTS.md",b"# fixture\n")
        for name in (cls.source/"platforms/shared/core-skills.txt").read_text().splitlines():
            if name and not name.startswith("#"):
                put(f"platforms/shared/skills/{name}/SKILL.md",f"---\nname: {name}\ndescription: fixture\n---\n<!-- agent-workflow-pack:managed-skill -->\n# {name}\n".encode())
        cls.core=runtime_store.import_core(cls.source,cls.state)
        put("product/WORKFLOW.md","# TUI 固定版本乙\n".encode());cls.alternate=runtime_store.import_core(cls.source,cls.state)
        put("product/WORKFLOW.md","# TUI 固定版本甲\n".encode())

    @classmethod
    def tearDownClass(cls):cls.temporary.cleanup()

    def setUp(self):
        self.project=self.root/("中文 é 项目-"+uuid.uuid4().hex[:8]);self.project.mkdir()
        self.app=App(self.state,self.root/"empty-scan",self.project)
        self.executor=ThreadPoolExecutor(max_workers=1);self.app.executor=self.executor
        self.addCleanup(self.executor.shutdown,wait=True)
        self.source_patch=patch("manager.tui.service.SOURCE",self.source);self.source_patch.start();self.addCleanup(self.source_patch.stop)

    def type(self,text):
        for char in text:self.app.dispatch(char)

    def settle(self):
        future=self.app.future;self.assertIsNotNone(future)
        try:future.result(timeout=20)
        except (OSError,ValueError):pass
        self.app.poll_job()

    def menu(self,action):
        self.app.modal=None;self.app.frames=[];self.app.filter_text="";self.app.dispatch("g")
        self.app.index=next(index for index,(_,value) in enumerate(self.app.options()) if value == action)
        self.app.dispatch("enter");self.settle()

    def apply(self):
        self.assertEqual("project_plan",self.app.modal);self.assertTrue(self.app.project_plan.summary["can_apply"],self.app.text)
        self.app.dispatch("enter");self.settle();self.assertEqual("result",self.app.modal,self.app.text)

    @staticmethod
    def snapshot(root):
        result={}
        for directory,dirs,files in os.walk(root,followlinks=False):
            for name in dirs+files:
                path=Path(directory)/name;relative=str(path.relative_to(root))
                result[relative]=("link",os.readlink(path)) if path.is_symlink() else ("dir",None) if path.is_dir() else ("file",path.read_bytes())
        return result

    def test_real_project_lifecycle_versions_details_and_deletion_focus(self):
        self.app.dispatch("a");self.type(str(self.project));self.app.dispatch("enter");self.app.dispatch("enter");self.settle()
        self.assertEqual("project_plan",self.app.modal);self.assertEqual([],list(self.project.iterdir()))
        self.apply();self.assertFalse(service.project_status(self.state,self.project)["enabled"])
        self.assertIn(str(self.project),service.registry(self.state)["registered"])
        before=self.snapshot(self.root)
        # 当前来源导入与普通启用共用真实中央服务；先验证导入预览取消无写入，
        # 再从普通启用完成后续生命周期，避免仅用模拟调用证明消费者仍可达。
        self.menu("install");self.assertIn(self.core.content_id,self.app.text)
        self.app.dispatch("esc");self.assertEqual("manage",self.app.modal);self.assertEqual(before,self.snapshot(self.root))
        self.menu("enable");self.apply();self.assertTrue(service.project_status(self.state,self.project)["enabled"])
        self.menu("details");self.assertEqual("details",self.app.modal)
        self.assertTrue(all(label in self.app.text for label in ("Codex","Claude Code","Antigravity",self.core.content_id,str(self.project))))
        self.menu("versions");self.assertEqual("versions",self.app.modal)
        self.assertEqual({self.core.content_id,self.alternate.content_id},{value for _,value in self.app.options()})
        self.app.index=next(index for index,(_,value) in enumerate(self.app.options()) if value == self.alternate.content_id)
        self.app.dispatch("i");self.assertIn(self.alternate.content_id,self.app.text)
        self.app.dispatch("esc");self.app.dispatch("enter");self.settle();self.apply()
        self.assertEqual(self.alternate.content_id,service.project_status(self.state,self.project)["runtime_binding"]["content_id"])
        self.menu("rollback");self.apply()
        self.assertEqual(self.core.content_id,service.project_status(self.state,self.project)["runtime_binding"]["content_id"])
        self.menu("check");self.assertIn("只读校验通过",self.app.text)
        self.menu("disable");self.assertIn("保留项目文件",self.app.text);self.apply()
        config=(self.project/".agent-workflow/project.yaml").read_bytes()
        documentation=(self.project/"docs/PROJECT.md").read_bytes()
        neighbor=self.root/("相邻项目-"+uuid.uuid4().hex[:8]);neighbor.mkdir()
        service.apply_project(service.preview_project(self.state,neighbor,"add"))
        other_key=(str(neighbor),"claude","xy-qa");self.app.drafts[other_key]={"model":"inherit","effort":"inherit"}
        self.menu("del");self.apply();self.app.dispatch("esc")
        self.assertNotIn(self.project,self.app.projects);self.assertNotEqual(self.project,self.app.project)
        self.assertIsNone(self.app.modal);self.assertIn(other_key,self.app.drafts)
        self.assertEqual(config,(self.project/".agent-workflow/project.yaml").read_bytes())
        self.assertEqual(documentation,(self.project/"docs/PROJECT.md").read_bytes())
        self.assertNotIn(str(self.project),service.registry(self.state)["registered"])

    def test_hand_edit_conflict_and_unknown_pin_remain_visible_without_fallback(self):
        service.apply_project(service.preview_project(self.state,self.project,"add",enable=True,content_id=self.core.content_id))
        target=self.project/".codex/agents/xy-qa.toml";target.write_bytes(target.read_bytes()+b"\n# hand edit\n")
        self.menu("disable");self.assertFalse(self.app.project_plan.summary["can_apply"])
        before=self.snapshot(self.project);self.app.dispatch("enter")
        self.assertIsNone(self.app.future);self.assertEqual(before,self.snapshot(self.project));self.assertIn(".codex/agents/xy-qa.toml",self.app.text)
        self.menu("repair");self.assertFalse(self.app.project_plan.summary["can_apply"])
        from lib.runtime_project import project_key
        record_path=self.state/"bindings"/(project_key(self.project)+".json")
        record=json.loads(record_path.read_bytes());record["runtime_binding"]={"protocol_version":1,"content_id":"a"*64,"manifest_sha256":"a"*64}
        record["used_bindings"].append(record["runtime_binding"])
        record_path.write_text(json.dumps(record))
        self.menu("details");self.assertIn("固定核心版本缺失",self.app.text)
        self.menu("enable");self.assertEqual("error",self.app.modal);self.assertIn("固定核心版本缺失",self.app.text)
        self.assertEqual("a"*64,service.project_status(self.state,self.project)["runtime_binding"]["content_id"])

    def test_damaged_version_list_fails_and_keeps_model_draft(self):
        self.menu("versions");self.assertEqual("versions",self.app.modal)
        key=(str(self.project),"codex","xy-qa");self.app.drafts[key]={"model":"inherit","effort":"high"}
        target=self.alternate.root/"product/WORKFLOW.md";original=target.read_bytes()
        try:
            target.chmod(0o600);target.write_bytes(b"damaged\n");target.chmod(0o444)
            self.menu("versions");self.assertEqual("error",self.app.modal)
            self.assertIn("操作未完成",self.app.text);self.assertIn(key,self.app.drafts)
        finally:
            target.chmod(0o600);target.write_bytes(original);target.chmod(0o444)

    @unittest.skipUnless(os.name == "posix","真实 PTY 键盘与 resize 需要 POSIX 终端")
    def test_real_pty_registration_cancel_enable_disable_versions_conflict_and_resize(self):
        master,slave=pty.openpty();terminal=TerminalCells();raw=bytearray();checkpoints=[]
        fcntl.ioctl(slave,termios.TIOCSWINSZ,struct.pack("HHHH",30,100,0,0))
        host=self.root/("isolated-host-"+uuid.uuid4().hex[:8]);host.mkdir()
        # 只给本测试独占宿主声明显式目录，不触发真实Codex/账户或网络。
        # 模型保存仍通过生产App/service/中央收据和真实角色文件完成。
        (host/'codex').mkdir()
        (host/'codex/config.toml').write_text('model="fixture-current"\nmodel_catalog_json="models.json"\n')
        (host/'codex/models.json').write_text(json.dumps({'models':[
            {'slug':name,'display_name':name,'supported_reasoning_levels':[{'effort':'high'},{'effort':'max'}]}
            for name in ('fixture-current','fixture-other')]}))
        environment={key:value for key,value in os.environ.items() if not key.startswith("AGENT_WORKFLOW_")}
        environment.update(HOME=str(host),XDG_CONFIG_HOME=str(host/"config"),CLAUDE_CONFIG_DIR=str(host/"claude"),
                           CODEX_HOME=str(host/"codex"),TERM="xterm-256color",LANG="en_US.UTF-8")
        # 唯一注入是最小真实来源路径；run/App/服务/文件系统和所有按键均为生产实现。
        program="from pathlib import Path; import sys; from manager import service; from manager.tui import run; service.SOURCE=Path(sys.argv[4]); raise SystemExit(run(Path(sys.argv[1]),Path(sys.argv[2]),Path(sys.argv[3])))"
        process=subprocess.Popen([*PYTHON,"-c",program,str(self.state),str(self.root/"empty-scan"),str(self.project),str(self.source)],
                                 cwd=PACK,env=environment,stdin=slave,stdout=slave,stderr=slave,start_new_session=True)
        checkpoints.append(f'\n=== PTY进程 {process.pid} · 测试项目 {self.project} ===\n')
        os.close(slave)
        def pump(timeout=0.05):
            if select.select([master],[],[],timeout)[0]:
                try:data=os.read(master,65536)
                except OSError as exc:
                    if exc.errno == errno.EIO:return
                    raise
                raw.extend(data);terminal.feed(data)
        def wait_for(predicate,description,timeout=15):
            deadline=time.monotonic()+timeout
            while time.monotonic()<deadline:
                pump()
                if predicate():return
                if process.poll() is not None:break
            self.fail(f"PTY 未到达 {description}；exit={process.poll()}\n当前字符格：\n{terminal.text()}\n原始输出末段：{bytes(raw[-2000:])!r}")
        def visible(text):wait_for(lambda:text in terminal.text(),text)
        def view(title):wait_for(lambda:title in "".join(terminal.cells[4]),"视图标题 "+title)
        def checkpoint(name):
            # ncurses一帧可能分多个PTY块到达；排空后再保存字符格，避免把新标题
            # 和上一帧“执行中”拼成最终结果。原始字节仍完整保留供独立复核。
            for _ in range(3):pump(.03)
            if terminal.height>=16 and terminal.width>=55:
                self.assertEqual(''.join(terminal.cells[0]),"┏"+"━"*(terminal.width-2)+"┓")
                self.assertEqual(''.join(terminal.cells[-1]),"┗"+"━"*(terminal.width-2)+"┛")
                for row in terminal.cells[1:-1]:
                    self.assertIn(row[0],{"┃","┠"});self.assertIn(row[-1],{"┃","┨"})
                layout=Layout(terminal.height,terminal.width)
                if terminal.cells[layout.modal_top][layout.modal_x] == '╭':
                    self.assertEqual(terminal.cells[layout.bottom][layout.modal_x],'┴')
                    self.assertEqual(terminal.cells[layout.bottom][layout.modal_x+layout.modal_width-1],'┴')
            checkpoints.append(f'\n--- {name} ({terminal.height}x{terminal.width}) ---\n'+terminal.text()+'\n')
        def send(value):
            os.write(master,value.encode("utf-8"))
            # ESC需要等 ncurses 的转义序列窗口关闭；同时持续排空PTY，不能积压绘制字节。
            until=time.monotonic()+0.08
            while time.monotonic()<until:pump(min(0.02,max(0,until-time.monotonic())))
        def close_to_main():
            for _ in range(6):
                if "╭" not in "".join(terminal.cells[4]):return
                send("\x1b")
            self.fail("PTY 无法返回主界面\n"+terminal.text())
        def choose_menu(label,expected):
            send("g");view("工作流管理")
            send("/"+label+"\r");send("\r");view(expected)
        try:
            visible("未管理")
            checkpoint('主界面完整粗框与分区')
            # 使用真实终端的 Tab/反向 Tab 和应用模式箭头验证路由，
            # 选中平台用方括号、焦点用文字标记表达，单色也不依赖颜色判断。
            for key,index,label in (("\t",2,"Claude Code"),("\t",3,"Antigravity"),("\t",1,"Codex"),
                                    ("\x1b[Z",3,"Antigravity"),("\x1b[Z",2,"Claude Code"),("\x1b[Z",1,"Codex")):
                send(key);visible(f'[{index} {label}]')
            for _ in range(2):send('\x1bOD');visible('◈ 项目')
            checkpoint('Tab双向循环平台与左箭头幂等项目焦点')
            for _ in range(2):
                send('\x1bOC')
                wait_for(lambda:'◈ '+self.project.name in ''.join(terminal.cells[5]),'右箭头内容焦点')
            send('?');view('快捷键帮助');checkpoint('帮助弹层粗框与返回提示');send('\x1b')
            # 首次登记只走预览并取消，验证项目/registry均无写入，且输入能逐层返回。
            send("a");view("登记项目 · 输入目录");send(str(self.project))
            send('\x1bOD');send('\x1bOC');send('\t');send('\x1b[Z')
            checkpoint('路径输入光标与平台区域隔离')
            send("\r");view("选择登记方式")
            send("\r");view("项目管理 · 只读预览")
            checkpoint('登记只读预览弹层')
            self.assertNotIn(str(self.project),service.registry(self.state)["registered"])
            self.assertEqual([],list(self.project.iterdir()))
            send("\x1b");view("选择登记方式");send("\x1b");view("登记项目 · 输入目录")
            self.assertIn("项目-",terminal.text());send("\x1b")
            send("a");view("登记项目 · 输入目录");send(str(self.project)+"\r");view("选择登记方式")
            send("\r");view("项目管理 · 只读预览");send("\r");view("操作结果")
            self.assertIn(str(self.project),service.registry(self.state)["registered"])
            self.assertFalse(service.project_status(self.state,self.project)["enabled"]);send("\x1b")
            # 主界面启停不能依靠隐藏菜单或过期状态直接写入；先取消一次启用预览。
            close_to_main();visible('[o]启用预览');send('o');view('项目管理 · 只读预览')
            send('\x1b');self.assertFalse(service.project_status(self.state,self.project)['enabled'])
            send('o');view('项目管理 · 只读预览');send('\r');view('操作结果')
            self.assertTrue(service.project_status(self.state,self.project)["enabled"]);close_to_main()
            visible('项目工作流 已启用');checkpoint('主界面启用真实成功')
            choose_menu("三宿主详情","项目 / 三宿主详情")
            self.assertTrue(all(name in terminal.text() for name in ("Codex","Claude Code","Antigravity")))
            close_to_main()
            # 更新后的空备份提示必须从真实管理动作显示，并在最小支持宽度中
            # 保留返回键；它只说明模型备份，不再把用户引向已移除的旧运行时备份。
            choose_menu("模型配置备份","模型配置备份");visible("当前项目还没有模型配置备份")
            terminal.resize(16,55);fcntl.ioctl(master,termios.TIOCSWINSZ,struct.pack("HHHH",16,55,0,0));os.kill(process.pid,signal.SIGWINCH)
            view("模型配置备份");visible("Esc")
            terminal.resize(30,100);fcntl.ioctl(master,termios.TIOCSWINSZ,struct.pack("HHHH",30,100,0,0));os.kill(process.pid,signal.SIGWINCH)
            view("模型配置备份");close_to_main()
            terminal.resize(16,55);fcntl.ioctl(master,termios.TIOCSWINSZ,struct.pack('HHHH',16,55,0,0));os.kill(process.pid,signal.SIGWINCH)
            visible('[p]停用预览')
            send('\x1bOD');visible('◈ 项目')
            send('/'+self.project.name[-8:]+'\r')
            visible('项目工作流 已启用');checkpoint('55x16项目筛选分隔和启停入口')
            # 启用操作保留原触发区域；Enter明确打开项目，Tab只切平台。
            send('\x1b');send('\r')
            terminal.resize(30,100);fcntl.ioctl(master,termios.TIOCSWINSZ,struct.pack('HHHH',30,100,0,0));os.kill(process.pid,signal.SIGWINCH)
            # Esc取消选择和保存预览都必须无写入；跨宿主返回保留当前范围草稿。
            target=self.project/'.codex/agents/xy-qa.toml';original=target.read_bytes()
            send('m');view('选择模型');checkpoint('模型选择弹层粗框与内部层次')
            send('\t');send('\x1b[Z');send('\x1bOD');send('\x1bOC');view('选择模型')
            send('\x1b');self.assertEqual(original,target.read_bytes())
            send('m');view('选择模型');send('/fixture-other\r');send('\r');view('选择推理级别')
            send('/max\r');send('\r');visible('已暂存，尚未保存')
            self.assertEqual(original,target.read_bytes());checkpoint('模型推理暂存未写入')
            # 暂存返回主界面后，登记行应只包含登记入口和留白。
            # 检查完整正文区域可发现滚动漏解，不能仅凭四边闭合或状态文字判定稳定帧正确。
            layout=Layout(terminal.height,terminal.width)
            registration=next(row for row in terminal.cells if '+ 登记项目' in ''.join(row))
            self.assertEqual(''.join(registration[layout.left:layout.sidebar]).strip(),'+ 登记项目')
            send('s');view('保存预览');self.assertEqual(original,target.read_bytes())
            send('\x1b');visible('已取消保存预览');self.assertEqual(original,target.read_bytes())
            send('\t');visible('[2 Claude Code]');send('\x1b[Z');visible('[1 Codex]');send('s');view('保存预览')
            send('\r');view('操作结果');visible('已保存模型配置')
            self.assertEqual({'model':'fixture-other','effort':'max'},service.role_settings(self.project,'codex','xy-qa'))
            checkpoint('模型保存服务验收成功')
            # 结果正文在项目路径与备份说明之间有一行留白，必须验证整行为空，
            # 以免标题/成功状态已更新时，解析器仍把上一弹层残字当成当前结果。
            layout=Layout(terminal.height,terminal.width)
            backup_row=next(index for index,row in enumerate(terminal.cells) if '备份：' in ''.join(row))
            self.assertEqual(''.join(terminal.cells[backup_row-1][layout.modal_inner_x:
                             layout.modal_inner_x+layout.modal_inner_width]).strip(),'')
            close_to_main();visible('已保存模型配置')
            send('m');view('选择模型');send('\r');view('选择推理级别');send('\r');visible('无改动')
            self.assertNotIn('已同步',''.join(terminal.cells[0]))
            saved=target.read_bytes()
            send('e');view('选择推理级别');send('/high\r');send('\r');visible('已暂存，尚未保存')
            send('s');view('保存预览');target.write_bytes(saved+b'\n# concurrent fixture save\n')
            concurrent=target.read_bytes();send('\r');view('操作未完成');visible('草稿保留')
            self.assertEqual(concurrent,target.read_bytes());checkpoint('保存失败保留草稿和并发字节')
            close_to_main();visible('1 项未保存');target.write_bytes(saved)
            send('u');visible('已丢弃当前角色草稿');send('r');visible('已读取预览 / 状态')
            choose_menu("中央版本","中央版本列表 / 选择");send("i");view("完整版本详情")
            # 64位ID可能跨行，去除字符格换行后验证完整身份仍可达。
            self.assertTrue(any(value in terminal.text().replace("\n","").replace(" ","") for value in (self.core.content_id,self.alternate.content_id)))
            send("\x1b");view("中央版本列表 / 选择");send("\r");view("项目管理 · 只读预览")
            send("\x1b");view("中央版本列表 / 选择");close_to_main()
            close_to_main();send('p');view('项目管理 · 只读预览');send("\r");view("操作结果")
            self.assertFalse(service.project_status(self.state,self.project)["enabled"]);close_to_main()
            visible('项目工作流 已停用');checkpoint('主界面停用真实成功')
            # 在停用后的受管目标放入手改，真实预览必须显示冲突，Enter也不能发布。
            target=self.project/".codex/agents/xy-qa.toml";target.parent.mkdir(parents=True,exist_ok=True);target.write_text("user hand edit\n")
            # xterm keypad启用后使用应用模式End（kend），CSI F会被部分ncurses当作Esc返回。
            send('o');view('项目管理 · 只读预览');send("\x1bOF");visible("不能应用；冲突")
            before=self.snapshot(self.project);send("\r");self.assertEqual(before,self.snapshot(self.project))
            self.assertFalse(service.project_status(self.state,self.project)["enabled"]);close_to_main()
            # 表单错误保留输入，取消后缩小真实终端并从窄屏安全退出。
            send("a");view("登记项目 · 输入目录");send(str(self.root/"missing-project")+"\r");visible("目录不存在")
            self.assertIn("missing-project",terminal.text());send("\x1b")
            terminal.resize(12,45);fcntl.ioctl(master,termios.TIOCSWINSZ,struct.pack("HHHH",12,45,0,0));os.kill(process.pid,signal.SIGWINCH)
            visible("请调整至至少");send("q");process.wait(timeout=10)
            self.assertEqual(0,process.returncode)
            print(f"真实 PTY 已验证：完整粗框/内部分区、Tab/Shift+Tab双向循环、左右幂等焦点、路径/选择弹层隔离、登记预览取消/确认、主界面启用/停用、模型/推理暂存与取消、跨平台草稿返回、真实保存/无改动/并发失败保留草稿、版本完整ID、三宿主详情、55×16项目筛选/分隔/启停入口、手改冲突、表单错误、12×45退出；pid={process.pid} exit=0")
        finally:
            if process.poll() is None:
                # 仅回收本测试独占的短命夹具进程；正常路径必须q退出，此清理不作为取消能力证据。
                process.terminate();deadline=time.monotonic()+2
                while process.poll() is None and time.monotonic()<deadline:pump()
                if process.poll() is None:os.killpg(process.pid,signal.SIGKILL)
                process.wait(timeout=5)
            for _ in range(10):pump(0)
            os.close(master)
            if evidence:=os.environ.get("AGENT_WORKFLOW_TUI_EVIDENCE_LOG"):
                # 完整原始字节原样追加，不剥ANSI、不声称这是最终屏幕录制。
                with Path(evidence).open("ab") as output:
                    header=f'\n--- REAL PTY RAW BYTES BEGIN pid={process.pid} exit={process.returncode} (not a screen recording) ---\n'.encode()
                    output.write(header+bytes(raw)+b"\n--- REAL PTY RAW BYTES END ---\n")
            if evidence:=os.environ.get('AGENT_WORKFLOW_TUI_CELLS_LOG'):
                with Path(evidence).open('a',encoding='utf-8') as output:
                    output.write(''.join(checkpoints)+'\n--- 最终字符格 ---\n'+terminal.text()+'\n')


if __name__ == "__main__":unittest.main()
