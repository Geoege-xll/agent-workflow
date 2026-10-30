"""键盘优先的 curses 工作台；渲染与导航不改变服务层事务合同。"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import curses
from dataclasses import dataclass, replace
import locale
from pathlib import Path
import shlex
from threading import Event
import time

from .catalog import Catalog, clean, discover
from . import service
from .tui_support import Layout, TextInput, Theme, cell_width, clip, ellipsize, padded, wrapped

HOSTS=("codex","claude","antigravity")
HOST_LABELS=("Codex","Claude Code","Antigravity")
ROLE_LABELS={"xy-backend":"后端开发","xy-web":"前端开发","xy-desktop":"桌面开发","xy-apple":"Apple 开发","xy-android":"Android 开发","xy-uiux":"UI 设计","xy-qa":"独立 QA"}
LIST_MODALS={"model","effort","manage","backups","commands"}


@dataclass(frozen=True)
class Binding:
    key: str
    label: str
    action: str
    aliases: str = ""


COMMANDS=(Binding("Enter","编辑角色","edit","edit model"),
          Binding("s","预览变更","preview","preview diff apply"),
          Binding("u","丢弃当前角色草稿","discard","discard undo draft"),
          Binding("g","工作流管理","manage","manage workflow"),
          Binding("a","添加并安装","add","add init project"),
          Binding("r","刷新来源","refresh","refresh reload"),
          Binding("","安装 / 升级工作流","install","install upgrade"),
          Binding("","检查安装","check","check verify"),
          Binding("","模型配置备份 / 恢复","backups","backup restore"),
          Binding("","本地模型来源","sources","source catalog"),
          Binding("?","帮助","help","help shortcuts"),
          Binding("q","退出","quit","quit exit"))
COMMAND_BY_ACTION={row.action:row for row in COMMANDS}
MANAGE=tuple((action,COMMAND_BY_ACTION[action].label) for action in ("install","check","backups","sources"))


class App:
    def __init__(self,state: Path,scan: Path,initial: Path | None=None):
        self.state,self.scan=state,scan
        self.projects=service.projects(state,scan)
        if initial and initial not in self.projects:self.projects.append(initial)
        self.project_index=self.projects.index(initial) if initial else 0
        self.host_index=0;self.role_index=0;self.pane="roles" if self.projects else "projects"
        self.modal=None;self.index=0;self.scroll=0;self.text="";self.editor=TextInput()
        self.filter_text="";self.searching=False;self.search_input=TextInput();self.search_before=None
        self.frames=[];self.quit_code=0;self.exit_code=0
        self.drafts={};self.expected={};self.catalogs={};self.settings_cache={};self.roles_cache={}
        self.source_stamps={};self.roles_errors={};self.page_lines=10
        self.scratch=None;self.changes=[];self.backup_rows=[]
        self.toast="Enter 编辑角色 · / 搜索列表 · : 查找操作";self.toast_kind="info"
        self.done=False;self.future=None;self.after_job=None;self.show_job_result=True
        self.cancel_job=Event();self.job_cancellable=False;self.job_name="管理操作";self.job_started=0;self.job_return=None
        self.hits=[];self.screen=None;self.theme=Theme();self.cursor_visible=None

    @property
    def input(self):return self.editor.text

    @input.setter
    def input(self,value):self.editor=TextInput(value,len(value))

    @property
    def project(self):
        # 列表末尾的安装入口不是项目路径，也不能变成默认安装目标。
        return self.projects[self.project_index] if 0<=self.project_index<len(self.projects) else None

    @property
    def host(self):return HOSTS[self.host_index]

    def notify(self,text,kind="info"):
        self.toast=clean(text,500);self.toast_kind=kind

    def installed_roles(self):
        if not self.project:return []
        key=(str(self.project),self.host)
        if key not in self.roles_cache:
            try:
                self.roles_cache[key]=service.roles(self.project,self.host)
                self.roles_errors.pop(key,None)
            except (OSError,ValueError) as exc:
                self.roles_cache[key]=[];self.roles_errors[key]=clean(str(exc),500)
                self.notify(exc,"error")
        return self.roles_cache[key]

    def role_list(self):
        rows=list(self.installed_roles())
        # 外部移除的角色仍保留草稿入口，u 只丢弃这一项，不牵连其他范围。
        rows.extend(role for role in self.pending() if role not in rows)
        return rows

    @property
    def role(self):
        rows=self.role_list();return rows[min(self.role_index,len(rows)-1)] if rows else None

    def scope(self,role=None):return (str(self.project),self.host,role or self.role)

    def catalog(self) -> Catalog:
        key=(str(self.project),self.host)
        if key not in self.catalogs:self.catalogs[key]=discover(self.host,project=self.project)
        return self.catalogs[key]

    def current(self,role):
        key=self.scope(role)
        if key in self.drafts:return self.drafts[key]
        if key not in self.settings_cache:self.settings_cache[key]=service.role_settings(self.project,self.host,role)
        return self.settings_cache[key]

    def pending(self):return {role:value for (project,host,role),value in self.drafts.items() if project == str(self.project) and host == self.host}

    def command(self,action,label=None):
        row=COMMAND_BY_ACTION[action]
        return replace(row,label=label) if label else row

    def unavailable(self,action):
        if action in {"edit","preview","discard","manage","refresh","install","check","backups","sources"} and not self.project:return "请先选择项目"
        if action == "edit" and not self.role:return "当前宿主没有已安装角色"
        if action == "edit" and self.role not in self.installed_roles():return "角色已移除；u 可单独丢弃此角色草稿，其他草稿保留"
        if action == "preview" and not self.pending():return "当前范围没有待应用变更"
        if action == "discard" and self.scope() not in self.drafts:return "当前角色没有草稿"
        return ""

    def bindings(self):
        # 帮助、底栏、命令面板与派发共用动作定义，提示不能承诺后端不支持的能力。
        if self.future:
            return [Binding("Ctrl+C","请求取消并等待","interrupt")] if self.job_cancellable else [Binding("等待","操作完成后继续","wait")]
        if self.searching:
            return [Binding("↑↓","选择匹配项","move"),Binding("PgUp/PgDn","翻页","move"),Binding("Enter","接受筛选","accept-search"),Binding("Esc","取消搜索","back")]
        if self.modal == "add":
            return [Binding("Enter","安装到此项目","add-confirm"),Binding("Esc","取消","back"),Binding("←→","移动光标","input"),Binding("Home/End","行首 / 行尾","input"),Binding("Ctrl+U","清空输入","input")]
        if self.modal in LIST_MODALS:
            rows=[Binding("↑↓","选择","move"),Binding("Home/End","首项 / 末项","move"),Binding("PgUp/PgDn","翻页","move"),Binding("Enter","执行操作" if self.modal == "commands" else "确认选择","confirm"),Binding("Esc","返回","back")]
            if self.modal != "commands":rows+=[Binding("/","搜索","search"),self.command("help")]
            if self.modal == "manage":rows.append(Binding(":","命令","commands"))
            return rows
        if self.modal in {"preview","install","restore","quit"}:
            labels={"preview":"备份并应用","install":"确认安装 / 升级","restore":"确认恢复","quit":"放弃草稿并退出"}
            scrolling=[] if self.modal == "quit" else [Binding("↑↓","滚动","scroll"),Binding("PgUp/PgDn","翻页","scroll"),Binding("Home/End","页首 / 页尾","scroll")]
            return [*scrolling,Binding("Enter",labels[self.modal],"confirm"),Binding("Esc","返回","back")]
        if self.modal:
            return [Binding("↑↓","滚动","scroll"),Binding("PgUp/PgDn","翻页","scroll"),Binding("Home/End","页首 / 页尾","scroll"),Binding("Esc","返回","back")]
        return [Binding("↑↓","选择项目" if self.pane == "projects" else "选择角色","move"),
                Binding("Home/End","首项 / 末项","move"),Binding("PgUp/PgDn","翻页","move"),
                Binding("Tab","切换项目 / 角色","pane"),Binding("Shift+Tab","反向切换","pane"),
                Binding("Enter","打开角色表" if self.pane == "projects" else "编辑角色","confirm"),
                Binding("1/2/3","切换宿主","host"),Binding("/","搜索","search"),Binding(":","命令","commands"),
                self.command("preview",f"预览变更 ({len(self.pending())})"),
                *([self.command("discard")] if self.scope() in self.drafts else []),
                self.command("manage"),self.command("add"),self.command("refresh"),self.command("help"),self.command("quit"),
                *([Binding("Esc","清除筛选","back")] if self.filter_text else [])]

    def options(self):
        if self.modal == "model":return [(row.label,row.id) for row in self.catalog().models]
        if self.modal == "effort":
            model=next((row for row in self.catalog().models if row.id == self.scratch["model"]),None)
            return [("继承宿主","inherit")]+[(level,level) for level in model.efforts] if model else [("继承宿主","inherit")]
        if self.modal == "manage":return [(label,action) for action,label in MANAGE]
        if self.modal == "backups":return [(f'{row["id"]} · {row["status"]}',row["id"]) for row in self.backup_rows]
        if self.modal == "commands":
            return [(row.label+(f"  [{row.key}]" if row.key else "")+(" · "+reason if (reason:=self.unavailable(row.action)) else ""),row.action) for row in COMMANDS]
        return []

    def list_kind(self):return self.modal if self.modal in LIST_MODALS else self.pane if not self.modal else None

    def visible_rows(self,kind=None):
        kind=kind or self.list_kind()
        if kind == "projects":
            rows=[(i,project.name,str(project),str(project)) for i,project in enumerate(self.projects)]
            rows.append((len(self.projects),"+ 添加并安装项目","", ""))
        elif kind == "roles":
            installed=set(self.installed_roles())
            rows=[(i,("已移除 · " if role not in installed else "")+ROLE_LABELS.get(role,role),role,role) for i,role in enumerate(self.role_list())]
        elif kind in LIST_MODALS:rows=[(i,label,value,COMMANDS[i].aliases if kind == "commands" else value) for i,(label,value) in enumerate(self.options())]
        else:return []
        query=(self.input if kind == "commands" else self.search_input.text if self.searching else self.filter_text) if kind == self.list_kind() else ""
        query=query.casefold().strip()
        return [(index,label,value) for index,label,value,extra in rows if not query or query in f"{label} {value} {extra}".casefold()]

    def selection(self):
        return self.index if self.modal else self.project_index if self.pane == "projects" else self.role_index

    def select(self,index):
        if self.modal:self.index=index
        elif self.pane == "projects":
            if index != self.project_index:self.role_index=0
            self.project_index=index
        else:self.role_index=index

    def sync_selection(self):
        rows=self.visible_rows()
        if rows and self.selection() not in [row[0] for row in rows]:self.select(rows[0][0])

    def view_frame(self):
        return {key:getattr(self,key) for key in ("modal","index","scroll","text","pane","filter_text","project_index","host_index","role_index")}

    def restore_view(self,frame):
        for key,value in frame.items():setattr(self,key,value)
        self.searching=False;self.search_before=None

    def show_view(self,modal):
        self.frames.append(self.view_frame())
        self.modal=modal;self.index=0;self.scroll=0;self.filter_text="";self.searching=False;self.search_before=None

    def close_view(self):
        if self.frames:self.restore_view(self.frames.pop())
        else:self.modal=None;self.filter_text="";self.scroll=0;self.searching=False

    def open_model(self):
        if reason:=self.unavailable("edit"):raise ValueError(reason)
        self.scratch=dict(self.current(self.role));self.show_view("model")
        # 编辑基线只能来自用户开始编辑时看到的版本，不能在暂存时悄悄更新。
        if self.scope() not in self.expected:self.expected[self.scope()]=dict(self.settings_cache[self.scope()])
        rows=self.options();self.index=next((i for i,(_,identifier) in enumerate(rows) if identifier == self.scratch["model"]),0)

    def stage(self):
        key=self.scope()
        if key not in self.expected:self.expected[key]=dict(service.role_settings(self.project,self.host,self.role))
        if self.scratch == self.expected[key]:
            self.drafts.pop(key,None);self.expected.pop(key,None);self.source_stamps.pop(key,None)
        else:self.drafts[key]=dict(self.scratch);self.source_stamps[key]=self.catalog().stamp
        self.close_view()
        while self.modal in {"model","effort"}:self.close_view()
        self.scratch=None;self.notify("已暂存；s 预览后才写入当前项目 / 宿主","warning")

    def start_job(self,operation,after=None,*,show_result=True,name="管理操作",cancellable=False):
        # 返回帧只保留有效入口，不让结果页返回可重复提交的旧确认页。
        candidates=[self.view_frame(),*reversed(self.frames)]
        self.job_return=next((dict(frame) for frame in candidates if frame["modal"] == "manage"),None)
        if self.job_return is None:
            self.job_return=next((dict(frame) for frame in candidates if frame["modal"] is None),self.view_frame())
            self.job_return.update(modal=None,scroll=0,text="")
        self.cancel_job.clear();self.job_cancellable=cancellable;self.job_name=name;self.job_started=time.monotonic()
        self.show_job_result=show_result;self.modal=None;self.frames=[];self.filter_text="";self.searching=False
        self.future=self.executor.submit(operation);self.after_job=after
        self.notify("正在"+name+"；"+("Ctrl+C 可请求取消并等待恢复" if cancellable else "请等待完成，此操作不支持中途取消"),"warning")

    def poll_job(self):
        if not self.future or not self.future.done():return
        future,self.future=self.future,None
        try:
            result=future.result()
            if self.after_job:self.after_job()
            self.text=str(result or "完成");self.modal="result" if self.show_job_result else None;self.scroll=0
            self.notify("操作完成" if self.show_job_result else "安装完成；Enter 配置角色模型，1/2/3 切换宿主","success")
        except Exception as exc:
            self.text=str(exc);self.modal="error";self.scroll=0;self.notify("操作未完成；请查看诊断及保留的恢复信息","error")
        self.frames=[self.job_return] if self.modal and self.job_return else []
        self.after_job=None;self.job_cancellable=False

    def install_project(self,project,*,select_after=False):
        """仅成功后登记；安装预检、互斥、取消和恢复仍由原服务负责。"""
        def install():
            with service.lock(self.state,str(project)):result=service.install(project,self.cancel_job)
            service.register(self.state,project);return result
        def after():
            if select_after:
                if project not in self.projects:self.projects.append(project)
                self.project_index=self.projects.index(project);self.role_index=0;self.pane="roles"
            for cache in (self.settings_cache,self.roles_cache,self.roles_errors,self.catalogs):
                for key in list(cache):
                    if key[0] == str(project):cache.pop(key)
        self.start_job(install,after,show_result=not select_after,name="安装 / 升级 "+clean(project,180),cancellable=True)

    def manage_action(self,action):
        if not self.project:raise ValueError("请先按 a 添加项目")
        if action == "install":
            text=service.install_preview(self.project);self.show_view("install");self.text=text
        elif action == "check":self.start_job(lambda:service.check(self.project),name="检查安装")
        elif action == "sources":
            catalog=self.catalog();text="\n".join([f"{row.id} · {row.source}" for row in catalog.models]+catalog.notes+catalog.inactive)
            self.show_view("sources");self.text=text
        elif action == "backups":
            rows=service.backups(self.state,self.project);self.show_view("backups");self.backup_rows=rows
            if not rows:self.notify("当前项目还没有模型配置备份；安装器的旧运行时备份保留在项目目录")

    def can_confirm_quit(self):
        if not self.screen:return True
        h,w=self.screen.getmaxyx();return h>=5 and w>=40

    def confirm(self):
        if self.list_kind() and self.selection() not in [row[0] for row in self.visible_rows()]:
            self.notify("没有匹配项；Esc 清除筛选，或 / 重新搜索","warning");return
        project,host=self.project,self.host
        if self.modal == "commands":
            action=self.options()[self.index][1];reason=self.unavailable(action)
            if reason:self.notify(reason,"warning");return
            self.close_view();self.act(action)
        elif self.modal == "model":
            self.scratch["model"]=self.options()[self.index][1]
            if host == "codex":
                self.show_view("effort");self.index=next((i for i,(_,value) in enumerate(self.options()) if value == self.scratch["effort"]),0)
            else:self.scratch["effort"]="inherit";self.stage()
        elif self.modal == "effort":self.scratch["effort"]=self.options()[self.index][1];self.stage()
        elif self.modal == "manage":self.manage_action(self.options()[self.index][1])
        elif self.modal == "preview":
            changes=list(self.changes);keys=[self.scope(role) for role in self.pending()];catalog=self.catalog()
            def after():
                for key in keys:
                    self.drafts.pop(key,None);self.expected.pop(key,None);self.settings_cache.pop(key,None);self.source_stamps.pop(key,None)
            def apply():
                identifier=service.commit(self.state,project,changes,lambda:service.check(project,host),before_write=lambda:service.ensure_source(catalog,project))
                return service.backup_summary(project,identifier)
            self.start_job(apply,after,name="备份并应用模型配置")
        elif self.modal == "install":self.install_project(project)
        elif self.modal == "backups":
            if not self.backup_rows:return
            changes=service.prepare_restore(self.state,project,self.options()[self.index][1])
            self.show_view("restore");self.changes=changes
            self.text="恢复以下配置；恢复前会再保存一份备份：\n"+"\n".join(row.relative for row in self.changes)
        elif self.modal == "restore":
            from .cli import check_changed_hosts
            # 恢复计划携带原版本指纹，不可转成普通 list 丢失发布前/验收后复核。
            changes=self.changes
            def restore():
                identifier=service.commit(self.state,project,changes,lambda:check_changed_hosts(project,changes))
                return service.backup_summary(project,identifier)
            self.start_job(restore,lambda:self.settings_cache.clear(),name="恢复模型配置")
        elif self.modal == "quit":
            if not self.can_confirm_quit():self.notify("请放大窗口后确认，草稿仍保留","warning");return
            self.exit_code=self.quit_code;self.done=True
        elif not self.modal:
            if self.pane == "projects":
                if self.project is None:self.act("add")
                else:self.pane="roles";self.filter_text=""
            else:self.open_model()

    def quit(self,*,interrupted=False):
        self.quit_code=130 if interrupted else 0
        if self.drafts:
            if self.modal != "quit":self.show_view("quit")
            self.text=f"有 {len(self.drafts)} 项未应用草稿（包含其他项目 / 宿主）。\n\nEnter 放弃全部草稿并退出；Esc 返回，不写入项目。"
        else:self.done=True;self.exit_code=self.quit_code

    def interrupt(self):
        if self.future:
            if self.job_cancellable:
                self.cancel_job.set();self.notify("已请求取消；正在等待当前管理操作退出及必要恢复完成","warning")
            else:self.notify("此操作不支持中途取消；请等待完成，事务与锁仍受保护","warning")
        else:self.quit(interrupted=True)

    def act(self,action,key=None):
        if action == "move":
            rows=self.visible_rows()
            if not rows:return
            indices=[row[0] for row in rows];position=indices.index(self.selection()) if self.selection() in indices else 0
            if key == "home":position=0
            elif key == "end":position=len(rows)-1
            elif key in {"pageup","pagedown"}:position=max(0,min(len(rows)-1,position+(-self.page_lines if key == "pageup" else self.page_lines)))
            else:position=(position+(-1 if key == "up" else 1))%len(rows)
            self.select(indices[position])
        elif action == "scroll":
            if key == "home":self.scroll=0
            elif key == "end":self.scroll=10**9
            else:
                delta=-self.page_lines if key == "pageup" else self.page_lines if key == "pagedown" else -1 if key == "up" else 1
                self.scroll=max(0,self.scroll+delta)
        elif action == "pane":self.pane="projects" if self.pane == "roles" else "roles";self.filter_text=""
        elif action == "host":
            role=self.role;self.host_index=int(key)-1;rows=self.role_list()
            self.role_index=rows.index(role) if role in rows else 0;self.filter_text=""
        elif action == "confirm":self.confirm()
        elif action == "edit":self.open_model()
        elif action == "manage":
            if not self.project:raise ValueError("请先按 a 添加项目")
            self.show_view("manage")
        elif action in {"install","check","backups","sources"}:self.manage_action(action)
        elif action == "commands":self.show_view("commands");self.input="";self.sync_selection()
        elif action == "add":self.show_view("add");self.input=""
        elif action == "add-confirm":
            raw=self.input.strip()
            # Path('') 指向当前目录，空回车必须拒绝；路径正文绝不交给 shell。
            if not raw:raise ValueError("请先拖入项目根目录，再按回车安装")
            direct=Path(raw).expanduser();values=[raw] if direct.is_dir() else shlex.split(raw)
            if len(values) != 1:raise ValueError("请拖入一个项目目录")
            project=service.project_path(values[0])
            self.install_project(project,select_after=True)
        elif action == "preview":
            if not self.pending():self.notify("当前项目 / 宿主没有待应用变更");return
            cached=self.catalog();fresh=discover(self.host,project=self.project) if cached.stamp else cached
            self.catalogs[(str(self.project),self.host)]=fresh
            if fresh.stamp and any(self.source_stamps.get(self.scope(role)) != fresh.stamp for role in self.pending()):
                raise ValueError("模型来源或能力已变化；草稿保留，请重新选择模型，或按 u 丢弃当前角色草稿")
            expected={role:self.expected[self.scope(role)] for role in self.pending()}
            changes=service.prepare(self.project,self.host,self.pending(),fresh,expected)
            text="\n\n".join(f'{ROLE_LABELS.get(role,role)}  /  {role}\n  原配置  {expected[role]["model"]} / {expected[role]["effort"]}\n  待应用  {value["model"]} / {value["effort"]}' for role,value in self.pending().items())
            text+="\n\n变更文件：\n"+"\n".join(row.relative for row in changes)
            self.show_view("preview");self.changes=changes;self.text=text
        elif action == "refresh":
            role=self.role
            self.catalogs.pop((str(self.project),self.host),None);self.roles_cache.pop((str(self.project),self.host),None)
            for cache_key in list(self.settings_cache):
                if cache_key[:2] == self.scope()[:2]:self.settings_cache.pop(cache_key)
            rows=self.role_list();self.role_index=rows.index(role) if role in rows else 0
            self.filter_text="";self.sync_selection()
            self.notify("本地来源已刷新，草稿保留；冲突时按 u 丢弃当前角色草稿后重新编辑")
        elif action == "discard":
            key=self.scope()
            self.drafts.pop(key,None);self.expected.pop(key,None);self.source_stamps.pop(key,None);self.settings_cache.pop(key,None)
            self.sync_selection()
            self.notify("已丢弃当前角色草稿；下次编辑使用当前配置，其他草稿保留")
        elif action == "help":
            text="当前视图\n"+"\n".join(f"{row.key:12} {row.label}" for row in self.bindings())
            text+="\n\n主界面命令（: 可按名称搜索）\n"+"\n".join(f"{row.key or '命令面板':12} {row.label}" for row in COMMANDS)
            text+="\n\n/ 搜索后 Enter 只接受筛选，再按 Enter 才确认。\n鼠标单击只选中，Enter 确认。\n角色配置在新创建的子 Agent 生效；已有 Agent 不会被重启。\n缓存表示本地可见，不保证模型调用成功。"
            self.show_view("help");self.text=text
        elif action == "quit":self.quit()
        elif action == "search":
            self.search_before=self.view_frame();self.searching=True;self.search_input=TextInput(self.filter_text,len(self.filter_text))
        elif action == "accept-search":self.filter_text=self.search_input.text;self.searching=False;self.search_before=None
        elif action == "back":
            if self.searching:
                self.restore_view(self.search_before);self.search_before=None
            elif self.filter_text:self.filter_text=""
            else:
                previous=self.modal
                if previous == "model" and self.scope() not in self.drafts:self.expected.pop(self.scope(),None)
                self.close_view()
                if previous == "model":self.scratch=None
                if previous == "quit":self.quit_code=0

    def dispatch(self,key):
        if key == "ctrl-c":self.interrupt();return
        if self.future:return
        if self.modal in {"add","commands"} and key not in {"enter","esc","up","down","pageup","pagedown"}:
            self.editor.edit(key)
            if self.modal == "commands":self.sync_selection()
            return
        if self.searching and key not in {"enter","esc","up","down","pageup","pagedown"}:
            self.search_input.edit(key);self.sync_selection();return
        groups={"↑↓":{"up","down"},"PgUp/PgDn":{"pageup","pagedown"},"Home/End":{"home","end"},"1/2/3":{"1","2","3"},"Shift+Tab":{"backtab"}}
        for row in self.bindings():
            if key in groups.get(row.key,set()) or row.key.lower() == key:
                try:self.act(row.action,key)
                except (OSError,ValueError,KeyError,TypeError) as exc:self.notify(exc,"error")
                return

    def put(self,y,x,text,width=None,attr=0):
        h,w=self.screen.getmaxyx()
        if y<0 or y>=h or x<0 or x>=w:return
        available=min(w-x-1,width if width is not None else w-x-1)
        if available<=0:return
        try:self.screen.addstr(y,x,clip(text,available),attr)
        except curses.error:pass

    def row(self,y,x,width,text,attr=0):self.put(y,x,padded(text,width),width,attr)

    def footer_lines(self,width):
        priority=("confirm","add-confirm","accept-search","search","commands","back","help","preview","pane","interrupt","wait")
        bindings=self.bindings();chosen=[]
        for action in priority:
            match=next((row for row in bindings if row.action == action),None)
            if match:chosen.append(match)
        lines=[""]
        for row in chosen:
            token=ellipsize(f"{row.key} {row.label}",width)
            if lines[-1] and cell_width(lines[-1])+cell_width(token)+3>width:
                if len(lines)>=2:break
                lines.append("")
            lines[-1]+=("   " if lines[-1] else "")+token
        return lines

    def draw_input(self,y,x,width,field):
        text,cursor=field.viewport(width)
        self.row(y,x,width,text,self.theme.selected)
        self.cursor=(y,x+cursor)

    def finish_draw(self):
        visible=self.cursor is not None
        if self.cursor_visible != visible:
            try:curses.curs_set(int(visible))
            except curses.error:pass
            self.cursor_visible=visible
        if self.cursor:
            try:self.screen.move(*self.cursor)
            except curses.error:pass
        self.screen.refresh()

    def draw_projects(self,layout):
        width=layout.sidebar-2 if layout.sidebar else layout.width-3;x=1
        self.put(3,x,"> 项目" if self.pane == "projects" else "  项目",width,self.theme.focus if self.pane == "projects" else self.theme.title)
        active=self.pane == "projects"
        query=self.search_input.text if self.searching and active else self.filter_text if active else ""
        if self.searching and active:self.draw_input(4,x,width,self.search_input)
        else:self.put(4,x,ellipsize("/ "+query if query else f"{len(self.projects)} 个本地项目",width),width,self.theme.muted)
        end=layout.bottom-layout.details-(1 if query else 0);available=max(1,end-5)
        rows=self.visible_rows("projects");selected=next((i for i,row in enumerate(rows) if row[0] == self.project_index),0)
        start=max(0,selected-available+1)
        if active:self.page_lines=available
        for offset,(index,label,_) in enumerate(rows[start:start+available]):
            pending=index<len(self.projects) and any(key[0] == str(self.projects[index]) for key in self.drafts)
            attr=self.theme.selected if active and index == self.project_index else self.theme.inactive if index == self.project_index else self.theme.text
            self.row(5+offset,x,width,("> " if index == self.project_index else "  ")+("* " if pending else "")+label,attr)
            self.hits.append((5+offset,x,width,"project",index))
        if not rows:self.put(5,x,"无匹配 · Esc 清除",width,self.theme.warning)
        if query:self.put(end,x,"+ 添加并安装 · a",width,self.theme.focus)

    def draw_roles(self,layout):
        x=layout.sidebar+2 if layout.sidebar else 1;width=layout.width-x-2
        active=self.pane == "roles"
        title=("> " if active else "  ")+(self.project.name if self.project else "未选择项目")+" / 角色模型"
        self.put(3,x,ellipsize(title,width),width,self.theme.focus if active else self.theme.title)
        if self.searching and active:self.draw_input(4,x,width,self.search_input)
        else:
            subtitle="/ "+self.filter_text if active and self.filter_text else f"{HOST_LABELS[self.host_index]} · {len(self.pending())} 项待应用"+(" · Tab 切换项目/角色" if not layout.sidebar else "")
            self.put(4,x,ellipsize(subtitle,width),width,self.theme.muted)
        role_width=18 if width>=65 else 14;effort_width=10;model_width=max(5,width-role_width-effort_width-2)
        self.put(5,x,padded("角色",role_width)+" "+padded("模型",model_width)+" "+padded("推理",effort_width),width,self.theme.muted)
        rows=self.visible_rows("roles");available=max(1,layout.bottom-layout.details-6)
        if active:self.page_lines=available
        selected=next((i for i,row in enumerate(rows) if row[0] == self.role_index),0);start=max(0,selected-available+1)
        if not rows:
            hint="无匹配 · Esc 清除筛选" if self.filter_text and active else "没有已安装角色 · a 添加 / g 安装" if self.project else "Tab 选择项目，或按 a 添加并安装"
            self.put(7,x,ellipsize(self.roles_errors.get((str(self.project),self.host),hint),width),width,self.theme.warning)
        for offset,(index,label,role) in enumerate(rows[start:start+available]):
            try:value=self.current(role)
            except (OSError,ValueError):value={"model":"配置异常","effort":"?"}
            selected=index == self.role_index;pending=self.scope(role) in self.drafts
            attr=self.theme.selected if active and selected else self.theme.inactive if selected else self.theme.text
            prefix=(">" if selected else " ")+("*" if pending else " ")
            model="继承" if value["model"] == "inherit" else value["model"];effort="继承" if value["effort"] == "inherit" else value["effort"]
            self.row(6+offset,x,width,padded(prefix+label,role_width)+" "+padded(model,model_width)+" "+padded(effort,effort_width),attr)
            self.hits.append((6+offset,x,width,"role",index))

    def draw_modal(self,layout):
        titles={"model":"选择模型","effort":"选择推理级别","manage":"工作流管理","preview":"变更预览","install":"安装 / 升级确认","backups":"模型配置备份","restore":"恢复确认","sources":"本地模型来源","help":"快捷键帮助","quit":"退出确认","add":"添加并安装项目","result":"操作结果","error":"操作未完成","commands":"命令面板"}
        x=max(1,(layout.width-92)//2);width=layout.width-2*x-1
        self.put(3,x,titles.get(self.modal,self.modal),width,self.theme.error if self.modal in {"error","quit"} else self.theme.focus)
        self.put(4,x,ellipsize(f"{self.project or '未选择项目'} / {HOST_LABELS[self.host_index]}",width,tail=True),width,self.theme.muted)
        if self.modal in LIST_MODALS:
            if self.modal == "commands":self.draw_input(5,x,width,self.editor)
            elif self.searching:self.draw_input(5,x,width,self.search_input)
            else:self.put(5,x,ellipsize("/ "+self.filter_text if self.filter_text else "↑↓ 选择 · / 搜索 · Enter 确认",width),width,self.theme.muted)
            details=3 if self.modal == "model" and layout.details else 0
            available=max(1,layout.bottom-details-6);self.page_lines=available
            rows=self.visible_rows();selected=next((i for i,row in enumerate(rows) if row[0] == self.index),0);start=max(0,selected-available+1)
            for offset,(index,label,_) in enumerate(rows[start:start+available]):
                disabled=self.unavailable(COMMANDS[index].action) if self.modal == "commands" else ""
                attr=self.theme.selected if index == self.index else self.theme.muted if disabled else self.theme.text
                self.row(6+offset,x,width,("> " if index == self.index else "  ")+label,attr)
                self.hits.append((6+offset,x,width,"option",index))
            if not rows:self.put(6,x,"没有匹配项 · Esc 返回，或重新输入搜索",width,self.theme.warning)
            if details and rows:
                model=next((row for row in self.catalog().models if row.id == self.options()[self.index][1]),None)
                if model:
                    self.put(layout.bottom-3,x,"─"*width,width,self.theme.muted)
                    self.put(layout.bottom-2,x,ellipsize("ID  "+model.id,width),width)
                    self.put(layout.bottom-1,x,ellipsize("来源  "+model.source,width),width,self.theme.muted)
            count=f" {selected+1 if rows else 0} / {len(rows)} "
            self.put(3,x+max(0,width-cell_width(count)),count,cell_width(count),self.theme.muted)
        elif self.modal == "add":
            self.put(5,x,"拖入项目根目录，回车直接安装三平台工作流。",width)
            self.put(6,x,"项目目录",width,self.theme.muted);self.draw_input(7,x,width,self.editor)
            self.put(9,x,"已有工作流将升级；保留项目配置，失败由安装器恢复。",width,self.theme.muted)
            if self.toast_kind == "error":self.put(10,x,ellipsize("! "+self.toast,width),width,self.theme.error)
        else:
            lines=wrapped(self.text,width);available=max(1,layout.bottom-6);self.page_lines=available
            self.scroll=min(self.scroll,max(0,len(lines)-available))
            for offset,line in enumerate(lines[self.scroll:self.scroll+available]):
                attr=self.theme.error if self.modal == "error" else self.theme.warning if self.modal == "quit" else self.theme.text
                self.put(6+offset,x,line,width,attr)
            if len(lines)>available:
                count=f" {self.scroll+1}–{min(len(lines),self.scroll+available)} / {len(lines)} "
                self.put(3,x+max(0,width-cell_width(count)),count,cell_width(count),self.theme.muted)

    def draw(self):
        self.screen.erase();self.hits=[];self.cursor=None;h,w=self.screen.getmaxyx();layout=Layout(h,w)
        if h<16 or w<55:
            if self.modal == "quit":
                self.put(0,0,ellipsize(f"有 {len(self.drafts)} 项未应用草稿",w-1),attr=self.theme.warning)
                if self.can_confirm_quit():
                    self.put(2,0,"Enter 放弃全部草稿并退出",attr=self.theme.error);self.put(3,0,"Esc 返回，不写入项目")
                else:self.put(1,0,"请放大窗口后确认；Esc 返回")
            elif self.future:self.put(0,0,"任务仍在执行，请等待");self.put(2,0,self.toast)
            else:self.put(0,0,"请调整至至少 55 列 × 16 行");self.put(2,0,"q 安全退出；草稿仍保留")
            self.finish_draw();return
        count=f"* {len(self.drafts)} 项待应用" if self.drafts else "配置未更改"
        self.put(0,1,"awf-cli  /  角色模型",max(1,w-cell_width(count)-4),self.theme.title)
        self.put(0,w-cell_width(count)-2,count,cell_width(count),self.theme.warning if self.drafts else self.theme.muted)
        x=1
        for i,label in enumerate(HOST_LABELS):
            text=f" {i+1} {label} ";attr=self.theme.focus|curses.A_UNDERLINE if i == self.host_index else self.theme.muted
            self.put(1,x,text,cell_width(text),attr)
            if not self.modal:self.hits.append((1,x,cell_width(text),"host",i))
            x+=cell_width(text)+1
        self.put(2,1,"─"*(w-3),w-3,self.theme.muted)
        if self.modal:self.draw_modal(layout)
        else:
            if layout.sidebar or self.pane == "projects":self.draw_projects(layout)
            if layout.sidebar:
                for row in range(3,layout.bottom-layout.details):self.put(row,layout.sidebar,"│",1,self.theme.muted)
            if layout.sidebar or self.pane == "roles":self.draw_roles(layout)
            if layout.details:
                self.put(layout.bottom-3,1,"─"*(w-3),w-3,self.theme.muted)
                self.put(layout.bottom-2,1,ellipsize(str(self.project or "选择项目，或按 a 添加并安装"),w-3,tail=True),w-3,self.theme.muted)
                if self.role:
                    try:
                        value=self.current(self.role);detail=f'{self.role}  ·  {value["model"]} / {value["effort"]}'
                    except (OSError,ValueError):detail="角色配置异常，请检查本地文件"
                    self.put(layout.bottom-1,1,ellipsize(detail,w-3),w-3)
        self.put(layout.bottom,1,"─"*(w-3),w-3,self.theme.muted)
        status=self.toast;kind=self.toast_kind
        if self.future:
            elapsed=max(0,int(time.monotonic()-self.job_started));spinner="|/-\\"[(elapsed*3)%4]
            status=f"{spinner} {self.job_name} · {elapsed}s · "+("已请求取消，等待退出及必要恢复" if self.cancel_job.is_set() else "执行中");kind="warning"
        prefix={"error":"! ","warning":"* ","success":"+ ","info":"· "}[kind]
        self.put(layout.status,1,ellipsize(prefix+status,w-3),w-3,getattr(self.theme,kind,self.theme.text))
        for offset,line in enumerate(self.footer_lines(w-3)):self.put(layout.hints+offset,1,line,w-3,self.theme.focus)
        self.finish_draw()

    def loop(self,screen):
        self.screen=screen;screen.keypad(True);screen.timeout(100);self.theme=Theme.create()
        try:curses.set_escdelay(25)
        except (AttributeError,curses.error):pass
        try:curses.mousemask(curses.BUTTON1_CLICKED)
        except curses.error:pass
        with ThreadPoolExecutor(max_workers=1) as self.executor:
            while not self.done:
                try:self.poll_job();self.draw();self.read_input(screen)
                except KeyboardInterrupt:
                    # 不退出 executor；完整等待写者、恢复与锁释放后才允许退出。
                    self.interrupt()
        return self.exit_code

    def read_input(self,screen):
        try:raw=screen.get_wch()
        except curses.error:return
        if raw == curses.KEY_RESIZE:return
        if raw == curses.KEY_MOUSE and not self.future and not self.searching:
            try:_,x,y,_,_=curses.getmouse()
            except curses.error:return
            for row,col,width,kind,index in self.hits:
                if y == row and col<=x<col+width:
                    if kind == "host":self.act("host",str(index+1))
                    elif kind in {"project","role"}:
                        pane="projects" if kind == "project" else "roles"
                        if self.pane != pane:self.filter_text=""
                        self.pane=pane;self.select(index)
                    else:self.index=index
                    break
            return
        key={curses.KEY_UP:"up",curses.KEY_DOWN:"down",curses.KEY_LEFT:"left",curses.KEY_RIGHT:"right",curses.KEY_HOME:"home",curses.KEY_END:"end",curses.KEY_DC:"delete",curses.KEY_PPAGE:"pageup",curses.KEY_NPAGE:"pagedown",curses.KEY_ENTER:"enter",curses.KEY_BACKSPACE:"backspace",curses.KEY_BTAB:"backtab","\x7f":"backspace","\b":"backspace","\t":"tab","\n":"enter","\r":"enter","\x1b":"esc","\x03":"ctrl-c"}.get(raw,raw)
        h,w=screen.getmaxyx()
        if h<16 or w<55:
            if key == "ctrl-c":self.interrupt()
            elif not self.future:
                if self.modal == "quit" and key in {"enter","esc"}:self.dispatch(key)
                elif key == "q":self.quit()
        else:self.dispatch(key)


def run(state: Path,scan: Path,project: Path | None=None) -> int:
    locale.setlocale(locale.LC_ALL,"")
    return curses.wrapper(App(state,scan,project).loop)
