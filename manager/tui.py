"""可实际运行的 curses 终端界面；键盘为主，鼠标仅作为列表选择辅助。"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import curses
from dataclasses import dataclass
import locale
from pathlib import Path
import shlex
from threading import Event
import unicodedata

from .catalog import Catalog, clean, discover
from . import service

HOSTS=("codex","claude","antigravity")
HOST_LABELS=("Codex","Claude Code","Antigravity")
ROLE_LABELS={"xy-backend":"后端开发","xy-web":"前端开发","xy-desktop":"桌面开发","xy-apple":"Apple 开发","xy-android":"Android 开发","xy-uiux":"UI 设计","xy-qa":"独立 QA"}
MANAGE=(("install","安装 / 升级工作流"),("check","检查安装"),("backups","备份 / 恢复"),("sources","本地模型来源"))


def cell_width(text: str) -> int:
    return sum(0 if unicodedata.combining(char) else 2 if unicodedata.east_asian_width(char) in {"W","F"} else 1 for char in text)


def clip(text: str, width: int) -> str:
    """按终端单元格截断中文，避免中文宽字符挤占相邻表格列。"""
    result=""; used=0
    for char in clean(text,8000):
        size=cell_width(char)
        if used+size>width:break
        result+=char;used+=size
    return result


@dataclass(frozen=True)
class Binding:
    key: str
    label: str
    action: str


class App:
    def __init__(self,state: Path,scan: Path,initial: Path | None=None):
        self.state,self.scan=state,scan
        self.projects=service.projects(state,scan)
        if initial and initial not in self.projects:self.projects.append(initial)
        self.project_index=self.projects.index(initial) if initial else 0
        self.host_index=0;self.role_index=0;self.pane="roles" if self.projects else "projects"
        self.modal=None;self.index=0;self.scroll=0;self.text="";self.input=""
        self.drafts={};self.expected={};self.catalogs={};self.settings_cache={};self.roles_cache={}
        self.source_stamps={};self.roles_errors={};self.page_lines=10
        self.scratch=None;self.changes=[];self.backup_rows=[]
        self.toast="Enter 编辑角色 · g 工作流管理 · a 添加并安装"
        self.done=False;self.future=None;self.after_job=None;self.show_job_result=True
        self.cancel_job=Event()
        self.hits=[];self.screen=None

    @property
    def project(self):
        # 列表末尾保留一个可选择的安装入口，不把它伪装成项目路径。
        return self.projects[self.project_index] if 0<=self.project_index<len(self.projects) else None

    @property
    def host(self):return HOSTS[self.host_index]

    def role_list(self):
        if not self.project:return []
        key=(str(self.project),self.host)
        if key not in self.roles_cache:
            try:
                self.roles_cache[key]=service.roles(self.project,self.host)
                self.roles_errors.pop(key,None)
            except (OSError,ValueError) as exc:
                # 安全拒绝属于可展示状态；不让重绘退出并丢失其他项目的草稿。
                self.roles_cache[key]=[];self.roles_errors[key]=clean(str(exc),500)
                self.toast=self.roles_errors[key]
        return self.roles_cache[key]

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

    def bindings(self):
        # 底栏、帮助、键盘分发共用这一张按上下文生成的表，不维护平行的快捷键文案。
        if self.future:return []
        if self.modal == "add":return [Binding("Enter","安装到此项目","add-confirm"),Binding("Esc","取消","back")]
        if self.modal in {"model","effort","manage","backups"}:
            return [Binding("↑↓","选择","move"),Binding("Enter","确认","confirm"),Binding("Esc","返回","back")]
        if self.modal in {"preview","install","restore","quit"}:
            labels={"preview":"备份并应用","install":"确认安装 / 升级","restore":"确认恢复","quit":"放弃草稿并退出"}
            scrolling=[] if self.modal == "quit" else [Binding("↑↓","滚动","scroll"),Binding("PgUp/PgDn","翻页","scroll")]
            return [*scrolling,Binding("Enter",labels[self.modal],"confirm"),Binding("Esc","返回","back")]
        if self.modal:return [Binding("↑↓","滚动","scroll"),Binding("PgUp/PgDn","翻页","scroll"),Binding("Esc","返回","back")]
        return [Binding("↑↓","选择项目" if self.pane == "projects" else "选择角色","move"),
                Binding("Tab","切换项目 / 角色","pane"),Binding("Enter","打开角色表" if self.pane == "projects" else "编辑角色","confirm"),
                Binding("1/2/3","切换平台","host"),Binding("s",f"预览变更 ({len(self.pending())})","preview"),
                *([Binding("u","丢弃当前角色草稿","discard")] if self.scope() in self.drafts else []),
                Binding("g","工作流管理","manage"),Binding("a","添加并安装","add"),Binding("r","刷新来源","refresh"),
                Binding("?","帮助","help"),Binding("q","退出","quit")]

    def options(self):
        if self.modal == "model":return [(row.label,row.id) for row in self.catalog().models]
        if self.modal == "effort":
            model=next(row for row in self.catalog().models if row.id == self.scratch["model"])
            return [("继承宿主", "inherit")]+[(level,level) for level in model.efforts]
        if self.modal == "manage":return [(label,action) for action,label in MANAGE]
        if self.modal == "backups":return [(f'{row["id"]} · {row["status"]}',row["id"]) for row in self.backup_rows]
        return []

    def open_model(self):
        if not self.role:raise ValueError("当前平台没有已安装角色，请按 g 安装或升级工作流")
        self.scratch=dict(self.current(self.role));self.modal="model"
        # 保存用户开始编辑时看到的基线，不能在暂存时重新读取并吞掉并发变更。
        if self.scope() not in self.expected:
            self.expected[self.scope()]=dict(self.settings_cache[self.scope()])
        rows=self.options();self.index=next((i for i,(_,identifier) in enumerate(rows) if identifier == self.scratch["model"]),0)

    def stage(self):
        key=self.scope()
        if key not in self.expected:self.expected[key]=dict(service.role_settings(self.project,self.host,self.role))
        if self.scratch == self.expected[key]:
            self.drafts.pop(key,None);self.expected.pop(key,None);self.source_stamps.pop(key,None)
        else:
            self.drafts[key]=dict(self.scratch);self.source_stamps[key]=self.catalog().stamp
        self.modal=None;self.scratch=None;self.toast="已暂存；s 预览后才写入当前项目 / 平台"

    def start_job(self,operation,after=None,*,show_result=True):
        # 安装与检查放到单个后台线程；主循环持续重绘，避免 TUI 长时间像卡死。
        self.cancel_job.clear()
        self.show_job_result=show_result
        self.modal=None;self.future=self.executor.submit(operation);self.after_job=after
        self.toast="正在执行管理操作，请等待完成；安装时 Ctrl+C 可请求取消并等待恢复"

    def poll_job(self):
        if not self.future or not self.future.done():return
        future,self.future=self.future,None
        try:
            result=future.result()
            if self.after_job:self.after_job()
            self.text=str(result or "完成");self.modal="result" if self.show_job_result else None;self.scroll=0
            self.toast="操作完成" if self.show_job_result else "安装完成；Enter 配置角色模型，1/2/3 切换平台"
        except Exception as exc:
            self.text=str(exc);self.modal="error";self.scroll=0;self.toast="操作未完成，已保留可恢复状态"
        self.after_job=None

    def install_project(self,project,*,select_after=False):
        """添加入口与管理入口共用同一安装任务，保留预检、互斥锁、取消和恢复。

        仅成功后登记并选择新项目；失败时不留下已安装的假记录。刷新只涉及该项目，
        其他项目缓存及所有未应用草稿保持原状，避免重读来源或吞掉编辑基线。
        """
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
        self.start_job(install,after,show_result=not select_after)
        self.toast="正在安装 / 升级："+clean(project,500)+"；Ctrl+C 可请求取消并等待恢复"

    def confirm(self):
        project,host=self.project,self.host
        if self.modal == "model":
            self.scratch["model"]=self.options()[self.index][1]
            if host == "codex":
                self.modal="effort";self.index=next((i for i,(_,value) in enumerate(self.options()) if value == self.scratch["effort"]),0)
            else:self.scratch["effort"]="inherit";self.stage()
        elif self.modal == "effort":self.scratch["effort"]=self.options()[self.index][1];self.stage()
        elif self.modal == "manage":
            action=self.options()[self.index][1];self.scroll=0
            if action == "install":self.text=service.install_preview(project);self.modal="install"
            elif action == "check":self.start_job(lambda:service.check(project))
            elif action == "sources":self.text="\n".join([f"{row.id} · {row.source}" for row in self.catalog().models]+self.catalog().notes+self.catalog().inactive);self.modal="sources"
            elif action == "backups":
                self.backup_rows=service.backups(self.state,project);self.modal="backups";self.index=0
                if not self.backup_rows:self.toast="当前项目还没有模型配置备份；安装器的旧运行时备份保留在项目目录"
        elif self.modal == "preview":
            changes=list(self.changes);keys=[self.scope(role) for role in self.pending()];catalog=self.catalog()
            def after():
                for key in keys:
                    self.drafts.pop(key,None);self.expected.pop(key,None);self.settings_cache.pop(key,None);self.source_stamps.pop(key,None)
            def apply():
                identifier=service.commit(self.state,project,changes,lambda:service.check(project,host),
                                          before_write=lambda:service.ensure_source(catalog,project))
                return service.backup_summary(project,identifier)
            self.start_job(apply,after)
        elif self.modal == "install":
            self.install_project(project)
        elif self.modal == "backups":
            if not self.backup_rows:return
            self.changes=service.prepare_restore(self.state,project,self.options()[self.index][1]);self.modal="restore"
            self.text="恢复以下配置；恢复前会再保存一份备份：\n"+"\n".join(row.relative for row in self.changes)
        elif self.modal == "restore":
            from .cli import check_changed_hosts
            # 恢复计划携带原版本指纹；不可转成普通 list 丢失发布前/验收后的复核。
            changes=self.changes
            def restore():
                identifier=service.commit(self.state,project,changes,lambda:check_changed_hosts(project,changes))
                return service.backup_summary(project,identifier)
            self.start_job(restore,lambda:self.settings_cache.clear())
        elif self.modal == "quit":self.done=True
        elif not self.modal:
            if self.pane == "projects":
                if self.project is None:self.act("add")
                else:self.pane="roles"
            else:self.open_model()

    def act(self,action,key=None):
        if action == "move":
            delta=-1 if key == "up" else 1
            if self.modal:
                rows=self.options();self.index=(self.index+delta)%len(rows) if rows else 0
            elif self.pane == "projects":self.project_index=(self.project_index+delta)%(len(self.projects)+1);self.role_index=0
            else:
                rows=self.role_list();self.role_index=(self.role_index+delta)%len(rows) if rows else 0
        elif action == "scroll":
            delta=-self.page_lines if key == "pageup" else self.page_lines if key == "pagedown" else -1 if key == "up" else 1
            self.scroll=max(0,self.scroll+delta)
        elif action == "pane":self.pane="projects" if self.pane == "roles" else "roles"
        elif action == "host":self.host_index=int(key)-1;self.role_index=0
        elif action == "confirm":self.confirm()
        elif action == "manage":
            if not self.project:raise ValueError("请先按 a 添加项目")
            self.modal="manage";self.index=0
        elif action == "add":self.modal="add";self.input=""
        elif action == "add-confirm":
            # 只解析终端拖入的路径，不把文本交给 shell 执行。
            raw=self.input.strip()
            # Path('') 会指向当前目录，空回车必须拒绝，不能误把启动目录当作安装目标。
            if not raw:raise ValueError("请先拖入项目根目录，再按回车安装")
            direct=Path(raw).expanduser()
            values=[raw] if direct.is_dir() else shlex.split(raw)
            if len(values) != 1:raise ValueError("请拖入一个项目目录")
            project=service.project_path(values[0])
            # 输入区已明确回车即安装；直接启动唯一安装器，不再要求跳转管理页确认。
            self.install_project(project,select_after=True)
        elif action == "preview":
            if not self.pending():self.toast="当前项目 / 平台没有待应用变更";return
            cached=self.catalog()
            fresh=discover(self.host,project=self.project) if cached.stamp else cached
            self.catalogs[(str(self.project),self.host)]=fresh
            # 每个草稿记录选择时的来源；刷新不能悄悄把旧草稿背书成新提供方的选择。
            if fresh.stamp and any(self.source_stamps.get(self.scope(role)) != fresh.stamp for role in self.pending()):
                raise ValueError("模型来源或能力已变化；草稿保留，请重新选择模型，或按 u 丢弃当前角色草稿")
            expected={role:self.expected[self.scope(role)] for role in self.pending()}
            self.changes=service.prepare(self.project,self.host,self.pending(),fresh,expected)
            self.text="\n".join(f'{role}\n  {expected[role]["model"]} / {expected[role]["effort"]}\n  → {value["model"]} / {value["effort"]}' for role,value in self.pending().items())
            self.text+="\n\n范围：\n"+"\n".join(row.relative for row in self.changes);self.modal="preview";self.scroll=0
        elif action == "refresh":
            self.catalogs.pop((str(self.project),self.host),None)
            self.roles_cache.pop((str(self.project),self.host),None)
            for cache_key in list(self.settings_cache):
                if cache_key[:2] == self.scope()[:2]:self.settings_cache.pop(cache_key)
            self.toast="本地来源已刷新，草稿保留；冲突时按 u 丢弃当前角色草稿后重新编辑"
        elif action == "discard":
            key=self.scope()
            self.drafts.pop(key,None);self.expected.pop(key,None);self.source_stamps.pop(key,None);self.settings_cache.pop(key,None)
            self.toast="已丢弃当前角色草稿；下次编辑使用当前配置，其他草稿保留"
        elif action == "help":
            self.text="\n".join(f"{row.key}  {row.label}" for row in self.bindings())+"\n\n角色配置在新创建的子 Agent 生效；已有 Agent 不会被重启。\n缓存表示本地可见，不保证模型调用成功。"
            self.modal="help";self.scroll=0
        elif action == "quit":
            if self.drafts:self.modal="quit";self.text="有未应用草稿。Enter 放弃全部草稿并退出；Esc 返回。"
            else:self.done=True
        elif action == "back":
            if self.modal == "effort":
                self.modal="model";self.index=next(i for i,(_,identifier) in enumerate(self.options()) if identifier == self.scratch["model"])
            elif self.modal in {"install","sources","backups"}:self.modal="manage";self.index=0
            else:
                if self.modal == "model" and self.scope() not in self.drafts:self.expected.pop(self.scope(),None)
                self.modal=None;self.scratch=None
            self.scroll=0

    def dispatch(self,key):
        if self.future:return
        if self.modal == "add" and key not in {"enter","esc"}:
            if key == "backspace":self.input=self.input[:-1]
            elif isinstance(key,str) and len(key) == 1 and key.isprintable():self.input+=key
            return
        for row in self.bindings():
            matches=((row.key == "↑↓" and key in {"up","down"}) or
                     (row.key == "PgUp/PgDn" and key in {"pageup","pagedown"}) or
                     (row.key == "1/2/3" and key in {"1","2","3"}) or row.key.lower() == key)
            if matches:
                try:self.act(row.action,key)
                except (OSError,ValueError,KeyError,TypeError) as exc:self.toast=clean(str(exc),500)
                return

    def put(self,y,x,text,width=None,attr=0):
        h,w=self.screen.getmaxyx()
        if y<0 or y>=h or x<0 or x>=w:return
        available=min(w-x-1,width if width is not None else w-x-1)
        if available<=0:return
        try:self.screen.addstr(y,x,clip(text,available),attr)
        except curses.error:pass

    def box(self,y,x,h,w,title,focused=False):
        color=self.green if focused else 0
        self.put(y,x,"┌"+"─"*max(0,w-2)+"┐",w,color)
        self.put(y,x+2," "+title+" ",max(0,w-4),color)
        for row in range(y+1,y+h-1):self.put(row,x,"│",1,color);self.put(row,x+w-1,"│",1,color)
        self.put(y+h-1,x,"└"+"─"*max(0,w-2)+"┘",w,color)

    def footer_lines(self,width):
        tokens=[f"{row.key} {row.label}" for row in self.bindings()]
        lines=[""]
        for token in tokens:
            if cell_width(lines[-1])+cell_width(token)+3>width:lines.append("")
            lines[-1]+=("   " if lines[-1] else "")+token
        return lines

    def draw(self):
        self.screen.erase();self.hits=[];h,w=self.screen.getmaxyx()
        if h<16 or w<55:
            self.put(0,0,"请将终端调整至至少 55 列 × 16 行");self.put(2,0,"q 退出；配置与草稿未应用")
            self.screen.refresh();return
        self.put(0,1,"› awf-cli · 角色模型",w-2,self.green)
        x=1
        for i,label in enumerate(HOST_LABELS):
            text=f"[{i+1}] {label}  ";self.put(1,x,text,cell_width(text),self.selected if i == self.host_index else 0)
            self.hits.append((1,x,cell_width(text),"host",i));x+=cell_width(text)
        lines=self.footer_lines(w-3)
        body_h=h-5-len(lines)
        if self.modal:
            titles={"model":"选择模型","effort":"选择推理级别","manage":"工作流管理","preview":"变更预览","install":"安装 / 升级确认","backups":"模型配置备份","restore":"恢复确认","sources":"本地模型来源","help":"快捷键帮助","quit":"退出确认","add":"添加并安装项目","result":"操作结果","error":"操作未完成"}
            self.box(3,0,body_h,w,titles.get(self.modal,self.modal),True)
            self.put(4,2,"安装 Codex / Claude Code / Antigravity" if self.modal == "add" else f"{self.project or ''} / {HOST_LABELS[self.host_index]}",w-5)
            rows=self.options();available=max(1,body_h-4)
            self.page_lines=available
            if self.modal in {"model","effort","manage","backups"}:
                start=max(0,min(self.index-available+1,max(0,len(rows)-available)))
                for offset,(label,_) in enumerate(rows[start:start+available]):
                    index=start+offset;y=5+offset
                    self.put(y,2,("› " if index == self.index else "  ")+label,w-5,self.selected if index == self.index else 0)
                    self.hits.append((y,2,w-5,"option",index))
                if rows:self.put(3,w-15,f" {self.index+1}/{len(rows)} ",12)
            elif self.modal == "add":
                self.put(5,2,"拖入项目根目录，回车直接安装；Esc 取消。",w-5)
                self.put(6,2,self.input,w-5)
                self.put(7,2,"已有工作流将升级；保留项目配置，失败由安装器恢复。",w-5)
            else:
                # 文本按终端单元格换行；长检查结果可滚动，不丢失失败诊断。
                wrapped=[]
                for line in self.text.splitlines():
                    remaining=clean(line,8000)
                    if not remaining:wrapped.append("")
                    while remaining:
                        part=clip(remaining,w-5);wrapped.append(part);remaining=remaining[len(part):]
                self.scroll=min(self.scroll,max(0,len(wrapped)-available))
                for offset,line in enumerate(wrapped[self.scroll:self.scroll+available]):self.put(5+offset,2,line,w-5)
                if len(wrapped)>available:self.put(3,w-19,f" {self.scroll+1}-{min(len(wrapped),self.scroll+available)}/{len(wrapped)} ",16)
        else:
            split=w>=80;left=25 if split else w
            if split or self.pane == "projects":
                self.box(3,0,body_h,left,"项目",self.pane == "projects")
                available=max(1,body_h-3);start=max(0,self.project_index-available+1)
                for offset,project in enumerate([*self.projects,None][start:start+available]):
                    index=start+offset;pending=project is not None and any(key[0] == str(project) for key in self.drafts)
                    label=project.name if project is not None else "＋ 添加并安装项目"
                    self.put(5+offset,2,("› " if index == self.project_index else "  ")+label+(" *" if pending else ""),left-5,self.selected if index == self.project_index else 0)
                    self.hits.append((5+offset,2,left-5,"project",index))
            if split or self.pane == "roles":
                x=left if split else 0;rw=w-x
                self.box(3,x,body_h,rw,f"{self.project.name if self.project else '未选择项目'} / 角色模型",self.pane == "roles")
                role_width=17 if rw>=60 else 14;effort_width=8;model_width=max(8,rw-role_width-effort_width-9)
                self.put(4,x+2,"角色",role_width);self.put(4,x+role_width+2,"模型",model_width);self.put(4,x+role_width+model_width+3,"推理",effort_width)
                rows=self.role_list()
                if not rows:
                    hint="没有已安装角色 · a 添加并安装 / g 安装" if self.project else "选择左侧项目，或按 a 添加并安装"
                    self.put(6,x+2,self.roles_errors.get((str(self.project),self.host),hint),rw-5)
                available=max(1,body_h-5);start=max(0,self.role_index-available+1)
                for offset,role in enumerate(rows[start:start+available]):
                    role_index=start+offset
                    try:value=self.current(role)
                    except (OSError,ValueError):value={"model":"配置异常","effort":"?"}
                    attr=self.selected if role_index == self.role_index else 0;y=6+offset
                    self.put(y,x+2,("› " if role_index == self.role_index else "  ")+ROLE_LABELS.get(role,role),role_width,attr)
                    self.put(y,x+role_width+2,"继承" if value["model"] == "inherit" else value["model"],model_width,attr)
                    self.put(y,x+role_width+model_width+3,"继承" if value["effort"] == "inherit" else value["effort"],effort_width,attr)
                    if self.scope(role) in self.drafts:self.put(y,w-3,"*",1,self.yellow)
                    self.hits.append((y,x+2,rw-5,"role",role_index))
        self.put(h-len(lines)-2,1,self.toast,w-3,self.yellow if self.future else 0)
        for offset,line in enumerate(lines):self.put(h-len(lines)-1+offset,1,line,w-3,self.green)
        self.screen.refresh()

    def loop(self,screen):
        self.screen=screen;screen.keypad(True);screen.timeout(100)
        curses.curs_set(0)
        self.green=self.yellow=self.selected=0
        if curses.has_colors():
            curses.start_color();curses.use_default_colors()
            curses.init_pair(1,curses.COLOR_GREEN,-1);curses.init_pair(2,curses.COLOR_YELLOW,-1)
            self.green=curses.color_pair(1);self.yellow=curses.color_pair(2)
        self.selected=self.green|curses.A_REVERSE
        try:curses.mousemask(curses.BUTTON1_CLICKED)
        except curses.error:pass
        with ThreadPoolExecutor(max_workers=1) as self.executor:
            while not self.done:
                try:self.poll_job();self.draw();self.read_input(screen)
                except KeyboardInterrupt:
                    if not self.future:raise
                    # 保持主循环重绘并等待工作线程完成；它退出锁之前绝不退出 executor。
                    self.cancel_job.set();self.toast="已请求取消；正在等待当前管理操作及必要恢复完成"
        return 0

    def read_input(self,screen):
        """读取一次输入，方便主循环统一处理信号而不阻断后台恢复进度。"""
        try:raw=screen.get_wch()
        except curses.error:return
        if raw == curses.KEY_RESIZE:return
        if raw == curses.KEY_MOUSE and not self.future:
            try:_,x,y,_,_=curses.getmouse()
            except curses.error:return
            for row,col,width,kind,index in self.hits:
                if y == row and col<=x<col+width and (not self.modal or kind == "option"):
                    if kind == "host":self.host_index=index;self.role_index=0
                    elif kind == "project":
                        self.project_index=index;self.role_index=0;self.pane="roles"
                        if self.project is None:self.act("add")
                    elif kind == "role":self.role_index=index;self.pane="roles";self.dispatch("enter")
                    else:self.index=index;self.dispatch("enter")
                    break
            return
        key={curses.KEY_UP:"up",curses.KEY_DOWN:"down",curses.KEY_PPAGE:"pageup",curses.KEY_NPAGE:"pagedown",curses.KEY_ENTER:"enter",curses.KEY_BACKSPACE:"backspace",curses.KEY_BTAB:"tab","\x7f":"backspace","\b":"backspace","\t":"tab","\n":"enter","\r":"enter","\x1b":"esc"}.get(raw,raw)
        if screen.getmaxyx()[0]<16 or screen.getmaxyx()[1]<55:
            if key == "q" and not self.future:self.done=True
        else:self.dispatch(key)


def run(state: Path,scan: Path,project: Path | None=None) -> int:
    locale.setlocale(locale.LC_ALL,"")
    return curses.wrapper(App(state,scan,project).loop)
