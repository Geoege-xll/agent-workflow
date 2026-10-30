"""隔离录屏验证 TUI 单元格、焦点和输入；不读取真实宿主目录。"""

from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor
import curses
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from manager.catalog import Catalog, Model
from manager.tui import App, HOSTS, cell_width
from manager.tui_support import TextInput, Theme, ellipsize


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
        assert x+cell_width(text)<self.width,(y,x,text)
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
        self.root=Path(self.temp.name);self.project=self.root/"中文项目"
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
        for y,x,width,_,_ in self.app.hits:
            self.assertGreaterEqual(y,0);self.assertLess(y,height)
            self.assertGreaterEqual(x,0);self.assertLessEqual(x+width,self.screen.width-1)
        return self.screen

    def test_render_size_and_modal_matrix(self):
        for height,width in ((40,140),(30,110),(30,100),(24,80),(24,79),(16,55),(12,45),(3,18)):
            for modal in (None,"model","effort","manage","backups","preview","sources","help","quit","add","result","error","commands"):
                with self.subTest(size=(height,width),modal=modal):
                    self.app.modal=modal;self.app.scratch={"model":"local-model","effort":"high"}
                    self.app.text=("长诊断 é 中文 "+"a"*180+"\n")*30
                    self.app.input="/长目录/"+"中文"*60;self.app.backup_rows=[]
                    self.draw(height,width)

    def test_only_focused_panel_has_strong_full_row_selection(self):
        screen=self.draw()
        project_hit=next(hit for hit in self.app.hits if hit[3]=="project")
        role_hit=next(hit for hit in self.app.hits if hit[3]=="role")
        y,x,width,_,_=project_hit
        self.assertNotEqual(screen.attrs[y][x],self.app.theme.selected)
        y,x,width,_,_=role_hit
        self.assertTrue(all(attr==self.app.theme.selected for attr in screen.attrs[y][x:x+width]))
        self.app.dispatch("tab");screen=self.draw()
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

    def test_project_filter_empty_keeps_add_entry_but_does_not_install(self):
        self.app.pane="projects";self.app.dispatch("/");self.type("does-not-exist");self.app.dispatch("enter")
        self.assertIn("添加",self.draw().text())
        with patch.object(self.app,"install_project") as install:
            self.app.dispatch("enter");install.assert_not_called()
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
                self.app.dispatch("g");self.app.show_view("install");self.app.executor=executor
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
        self.app.dispatch("enter");self.app.dispatch("/");self.type("qsug123?:")
        self.assertEqual(self.app.modal,"model");self.assertFalse(self.app.done)
        self.assertEqual(self.app.search_input.text,"qsug123?:")

    def test_path_editing_and_read_input_keys(self):
        self.app.dispatch("a");self.type("/tmp/项目")
        self.app.dispatch("home");self.app.dispatch("right");self.type("x")
        self.assertEqual(self.app.input,"/xtmp/项目")
        self.screen.keys=[curses.KEY_END,curses.KEY_BACKSPACE,curses.KEY_LEFT,curses.KEY_DC]
        for _ in range(4):self.app.read_input(self.screen)
        self.assertEqual(self.app.input,"/xtmp/")
        self.app.dispatch("\x15");self.type("qsug123?:")
        self.assertEqual(self.app.input,"qsug123?:");self.assertEqual(self.app.modal,"add")

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

    def test_independent_model_and_effort_modification_and_column_toggling(self):
        self.assertEqual(self.app.role_column,"model")
        self.app.dispatch("right");self.assertEqual(self.app.role_column,"effort")
        self.app.dispatch("enter");self.assertEqual(self.app.modal,"effort")
        self.app.dispatch("esc");self.assertIsNone(self.app.modal)
        self.app.dispatch("left");self.assertEqual(self.app.role_column,"model")
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

    def test_effort_options_selectable_levels_for_hosts(self):
        self.app.host_index=1;self.app.scratch={"model":"inherit","effort":"inherit"}
        self.app.modal="effort"
        # When catalog model has explicit efforts ("high", "max"):
        model_levels=[v for _,v in self.app.options()]
        self.assertEqual(model_levels,["inherit","high","max"])
        # When catalog model has empty efforts, standard host levels are provided:
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

    def tearDown(self):
        self.assertFalse((self.root/"state").exists())


if __name__ == "__main__":unittest.main()
