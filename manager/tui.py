"""键盘优先的 curses 工作台；渲染与导航不改变服务层事务合同。"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import curses
from dataclasses import dataclass, replace
import locale
from pathlib import Path
import time

from lib.install.project_paths import InstallError, target_path
from lib import runtime_store
from .catalog import Catalog, clean, discover
from . import central_runtime, service, model_preferences, project_service, state_files
from .tui_state import Impact, Session
from .tui_support import (Layout, TextInput, Theme, PROJECT_ACTION_LABELS, binding_id, cell_width, clip,
                          draw_box, draw_divider, draw_frame, draw_scrollbar, ellipsize, operation_error, padded, project_badge,
                          project_plan_text, project_result_text, project_state, preference_plan_text, preference_result_text, runtime_status_text, runtime_plan_text, runtime_result_text, status_text, wrapped)

HOSTS=("codex","claude","antigravity")
HOST_LABELS=("Codex","Claude Code","Antigravity")
ROLE_LABELS={"xy-backend":"后端开发","xy-web":"前端开发","xy-desktop":"桌面开发","xy-apple":"Apple 开发","xy-android":"Android 开发","xy-uiux":"UI 设计","xy-qa":"独立 QA"}
LIST_MODALS={"model","effort","manage","backups","commands","add_mode","versions","runtime_versions"}
HOST_NAMES=dict(zip(HOSTS,HOST_LABELS))


@dataclass(frozen=True)
class Binding:
    key: str
    label: str
    action: str
    aliases: str = ""


COMMANDS=(Binding("Enter","编辑模型","edit","edit model"),
          Binding("e","修改推理","effort","effort reasoning level"),
          Binding("s","保存预览","preview","preview diff apply save"),
          Binding("u","丢弃当前角色草稿","discard","discard undo draft"),
          Binding("","恢复模型跟随全局","reset-model","reset model global"),
          Binding("","恢复推理跟随全局","reset-effort","reset effort global"),
          Binding("v","当前角色值与来源","preference-details","model effort source global project host"),
          Binding("g","工作流管理","manage","manage workflow"),
          Binding("a","登记项目","add","add register init project"),
          Binding("r","刷新状态与来源","refresh","refresh reload"),
          Binding("o","启用工作流","enable","open enable workflow"),
          Binding("p","停用工作流","disable","close disable workflow"),
          Binding("","显式导入来源并启用项目","install","install import source"),
          Binding("","中央运行时状态","runtime-status","runtime status current"),
          Binding("","导入当前中央核心","runtime-install","runtime install import"),
          Binding("","激活中央版本","runtime-activate","runtime activate current"),
          Binding("","回退中央版本","runtime-rollback","runtime rollback previous"),
          Binding("","恢复中央未结算事务","runtime-recover","runtime recover recovery"),
          Binding("","项目跟随中央版本","follow","project follow unlock"),
          Binding("","当前平台全部角色恢复跟随全局","reset-platform","reset all roles platform"),
          Binding("","中央版本列表 / 选择","versions","versions use pin"),
          Binding("","回退前次版本","rollback","rollback previous"),
          Binding("","检查工作流","check","check verify"),
          Binding("","修复受管资源","repair","repair recover"),
          Binding("","项目 / 三宿主详情","details","status hosts details"),
          Binding("","停用并解除登记","del","del delete unregister project"),
          Binding("","模型配置备份 / 恢复","backups","backup restore"),
          Binding("","本地模型来源","sources","source catalog"),
          Binding("?","帮助","help","help shortcuts"),
          Binding("q","退出","quit","quit exit"))
COMMAND_BY_ACTION={row.action:row for row in COMMANDS}
MANAGE=tuple((action,COMMAND_BY_ACTION[action].label) for action in
             ("runtime-status","runtime-install","runtime-activate","runtime-rollback","runtime-recover","enable","disable","follow","install","versions","rollback","check","repair","details","del","backups","sources","reset-platform","reset-model","reset-effort"))


class App:
    def __init__(self,state: Path,scan: Path,initial: Path | None=None,*,native_context=None):
        self.state,self.scan=state,scan
        self.native_context=native_context
        self.projects=project_service.projects(state,scan)
        if initial and initial not in self.projects:self.projects.append(initial)
        self.project_index=self.projects.index(initial) if initial else 0 if self.projects else -1
        self.host_index=0;self.role_index=0;self.role_selections={};self.role_column="model";self.pane="roles" if self.projects else "projects"
        self.modal=None;self.index=0;self.scroll=0;self.text="";self.editor=TextInput()
        self.filter_text="";self.searching=False;self.search_input=TextInput();self.search_before=None
        self.frames=[];self.quit_code=0;self.exit_code=0
        self.session=Session()
        self.drafts=self.session.drafts;self.expected=self.session.expected;self.source_stamps=self.session.source_stamps
        self.catalogs=self.session.catalogs;self.roles_errors=self.session.display_errors;self.page_lines=10
        self.scratch=None;self.scratch_choices={};self.scratch_fields={};self.preference_plan=None;self.changes=[];self.backup_rows=[]
        self.project_plan=None;self.version_rows=[];self.add_target=None
        self.runtime_plan=None;self.preference_keys=();self.preference_reset=False
        self.toast="m 选择模型 · e 选择推理 · s 保存预览";self.toast_kind="info"
        self.done=False
        self.hits=[];self.screen=None;self.theme=Theme();self.cursor_visible=None
        # 首次显示只取 P1 的只读上下文；此入口没有目录参数，绝不启动 native。
        # 后续绘制、帮助和选择器只消费 Session 内已接收的稳定投影。
        self.load_display()

    @property
    def project_rows(self):return self.session.project_rows

    @project_rows.setter
    def project_rows(self,value):self.session.project_rows=value

    @property
    def status_error(self):return self.session.status_error

    @status_error.setter
    def status_error(self,value):self.session.status_error=value

    @property
    def future(self):return self.session.job.future

    @future.setter
    def future(self,value):self.session.job.future=value

    @property
    def cancel_job(self):return self.session.job.cancel

    @property
    def input(self):return self.editor.text

    @input.setter
    def input(self,value):self.editor=TextInput(value,len(value))

    @property
    def project(self):
        # 列表末尾的登记入口不是项目路径，也不能变成默认启用目标。
        return self.projects[self.project_index] if 0<=self.project_index<len(self.projects) else None

    @property
    def global_scope(self):return self.project_index == -1

    @property
    def scope_id(self):return "<global>" if self.global_scope else str(self.project)

    @property
    def scope_label(self):return "全局默认" if self.global_scope else self.project.name if self.project else "未选择项目"

    @property
    def host(self):return HOSTS[self.host_index]

    def notify(self,text,kind="info"):
        self.toast=clean(text,500);self.toast_kind=kind

    def load_display(self,*,force=False):
        """仅在首次显示、范围切换或显式刷新入口读取配置，失败由 UI 保留诊断。"""
        if not self.global_scope and not self.project:return
        key=(self.scope_id,self.host)
        if not force and (key in self.session.displays or key in self.roles_errors):return
        try:self.session.accept_context(key,model_preferences.load_context(self.state,self.project,self.host,native_context=self.native_context))
        except (OSError,ValueError) as exc:
            self.session.fail_display(key,clean(str(exc),500));self.notify(exc,"error")

    def installed_roles(self):return self.session.installed_roles((self.scope_id,self.host))

    def role_list(self):
        rows=list(self.installed_roles())
        # 外部移除的角色仍保留草稿入口，u 只丢弃这一项，不牵连其他范围。
        rows.extend(role for role in self.pending() if role not in rows)
        return rows

    @property
    def role(self):
        rows=self.role_list();return rows[min(self.role_index,len(rows)-1)] if rows else None

    def scope(self,role=None):return (self.scope_id,self.host,role or self.role)

    def catalog(self) -> Catalog:
        # 空占位也不读取来源文件；真实目录只由显式 read_catalog 入口取得。
        stored=self.catalogs.get((self.scope_id,self.host),Catalog(self.host,_status="stale"))
        return stored.catalog if isinstance(stored,model_preferences.PreferenceCatalogs) else stored

    def read_catalog(self,ready):
        """显式进入编辑/来源页时预读本范围及受影响项目目录，失效最多恢复一次。"""
        project,host=self.project,self.host;key=(self.scope_id,host)
        cached=self.catalogs.get(key)
        def read():
            # 先完成显式目录批次，再取同一范围的 P1 上下文。已有草稿的 expected
            # 不参与这次显示替换，重开菜单本身也不更新旧来源 stamp。
            bundle=cached if cached is not None and model_preferences.check_catalogs(self.state,project,host,cached,native_context=self.native_context) else model_preferences.load_catalogs(self.state,project,host,native_context=self.native_context)
            if isinstance(bundle,Catalog):bundle=model_preferences.PreferenceCatalogs(bundle,{})
            return model_preferences.load_context(self.state,project,host,catalogs=bundle,native_context=self.native_context)
        def accept(context):
            self.session.accept_context(key,context)
            ready()
            if context.catalogs.catalog._status != "ready":
                self.notify("模型目录读取未完成；当前仅显示安全后备项，退出后重新进入可重试，或按 r 刷新","warning")
        if hasattr(self,"executor"):
            self.start_job(read,show_result=False,name="读取 "+HOST_NAMES[host]+" 模型目录",on_result=accept,
                           preserve_view=True,impact=Impact(frozenset({key[0]}),host))
        else:
            try:accept(read())
            except (OSError,ValueError) as exc:
                self.session.invalidate(Impact(frozenset({key[0]}),host),clean(str(exc),500));raise

    def base_value(self,role):
        return self.session.base_value(self.scope(role))

    def current(self,role):
        return self.session.current(self.scope(role))

    def pending(self):return self.session.pending((self.scope_id,self.host))

    def action_label(self,action):
        if action in {"reset-model","reset-effort"} and self.global_scope:
            return "恢复"+("模型" if action == "reset-model" else "推理")+"跟随宿主"
        return COMMAND_BY_ACTION[action].label

    def command(self,action,label=None):
        row=COMMAND_BY_ACTION[action]
        return replace(row,label=label or self.action_label(action))

    def unavailable(self,action):
        preference_actions={"edit","effort","preview","discard","manage","sources","reset-model","reset-effort","preference-details"}
        project_actions={"install","check","backups","enable","disable","follow","versions","rollback","repair","details","del","reset-platform"}
        if action in project_actions and self.global_scope:return "全局默认不执行项目工作流操作"
        if action in preference_actions|project_actions and not self.global_scope and not self.project:return "请先选择项目或全局默认"
        if action in {"edit","effort","reset-model","reset-effort","preference-details"} and not self.role:return "当前平台没有可编辑角色"
        if action in {"edit","effort","reset-model","reset-effort"} and self.role not in self.installed_roles():return "角色已移除；u 可单独丢弃此角色草稿，其他草稿保留"
        if action == "effort" and self.host == "antigravity":return "Antigravity 静态角色仅支持继承"
        if action == "preview" and not self.pending():return "无改动；当前范围没有待保存草稿，未写入配置"
        if action == "discard" and self.scope() not in self.drafts:return "当前角色没有草稿"
        if action == "rollback":
            row=self.project_rows.get(str(self.project))
            if row is not None and not row.get("previous_binding"):return "当前项目没有前次中央版本"
        return ""

    def manage_rows(self):
        # 全局入口不伪装成项目，管理菜单也不展示其不存在的启停或固定版本动作。
        return [(action,self.action_label(action)) for action,_ in MANAGE
                if not self.global_scope or action in {"sources","reset-model","reset-effort"} or action.startswith("runtime-")]

    def command_rows(self):
        project_actions={"enable","disable","follow","install","versions","rollback","check","repair","details","del","backups","reset-platform"}
        return [row for row in COMMANDS if not self.global_scope or row.action not in project_actions]

    def bindings(self):
        # 帮助、底栏、命令面板与派发共用动作定义，提示不能承诺后端不支持的能力。
        if self.future:
            return [Binding("Ctrl+C","请求取消并等待结算","interrupt")] if self.session.job.cancellable else [Binding("等待","操作完成后继续","wait")]
        if self.searching:
            return [Binding("↑↓","选择匹配项","move"),Binding("PgUp/PgDn","翻页","move"),Binding("Enter","接受筛选","accept-search"),Binding("Esc","取消搜索","back")]
        if self.modal == "add":
            return [Binding("Enter","选择登记方式","add-confirm"),Binding("Esc","取消","back"),Binding("←→","移动光标","input"),Binding("Home/End","行首 / 行尾","input"),Binding("Ctrl+U","清空输入","input")]
        if self.modal in LIST_MODALS:
            rows=[Binding("↑↓","选择","move"),Binding("Home/End","首项 / 末项","move"),Binding("PgUp/PgDn","翻页","move"),Binding("Enter","执行操作" if self.modal == "commands" else "确认选择","confirm"),Binding("Esc","返回","back")]
            if self.modal != "commands":rows+=[Binding("/","搜索","search"),self.command("help")]
            if self.modal == "manage":rows.append(Binding(":","命令","commands"))
            if self.modal in {"versions","runtime_versions"}:rows.append(Binding("i","完整版本详情","version-details"))
            return rows
        if self.modal == "runtime_plan":
            rows=[Binding("↑↓","滚动","scroll"),Binding("PgUp/PgDn","翻页","scroll"),Binding("Home/End","页首 / 页尾","scroll"),Binding("Esc","返回不写入","back")]
            if self.runtime_plan and self.runtime_summary()["can_apply"]:rows.insert(0,Binding("Enter","确认中央操作","confirm"))
            return rows
        if self.modal == "project_plan":
            rows=[Binding("↑↓","滚动","scroll"),Binding("PgUp/PgDn","翻页","scroll"),Binding("Home/End","页首 / 页尾","scroll"),Binding("Esc","返回不写入","back")]
            if self.project_plan and self.project_plan.summary["can_apply"]:
                rows.insert(0,Binding("Enter","确认"+PROJECT_ACTION_LABELS[self.project_plan.action],"confirm"))
            return rows
        if self.modal in {"preview","restore","quit"}:
            labels={"preview":"确认备份并保存","restore":"确认恢复","quit":"放弃草稿并退出"}
            scrolling=[] if self.modal == "quit" else [Binding("↑↓","滚动","scroll"),Binding("PgUp/PgDn","翻页","scroll"),Binding("Home/End","页首 / 页尾","scroll")]
            return [*scrolling,*([Binding("Enter",labels[self.modal],"confirm")] if self.modal != "preview" or self.preference_plan and self.preference_plan.summary["can_apply"] else []),Binding("Esc","返回","back")]
        if self.modal:
            return [Binding("↑↓","滚动","scroll"),Binding("PgUp/PgDn","翻页","scroll"),Binding("Home/End","页首 / 页尾","scroll"),Binding("Esc","返回","back")]
        role_binding=Binding("Enter","修改推理" if self.role_column == "effort" else "修改模型","confirm") if self.pane == "roles" else Binding("Enter","打开角色表","confirm")
        return [Binding("↑↓","选择项目" if self.pane == "projects" else "选择角色","move"),
                Binding("Home/End","首项 / 末项","move"),Binding("PgUp/PgDn","翻页","move"),
                Binding("Tab/Shift+Tab","下 / 上个平台","host"),Binding("←→","项目 / 内容","pane"),
                *([role_binding,Binding("m","修改模型","edit"),self.command("effort")] if self.pane == "roles" else [role_binding]),
                Binding("1/2/3","切换宿主","host"),Binding("/","搜索","search"),Binding(":","命令","commands"),
                self.command("preview",f"保存预览 ({len(self.pending())})"),
                *([self.command("discard")] if self.scope() in self.drafts else []),
                *([] if self.global_scope else [self.command("enable"),self.command("disable")]),
                self.command("preference-details"),self.command("manage"),self.command("add"),self.command("refresh"),self.command("help"),self.command("quit"),
                *([Binding("Esc","清除筛选","back")] if self.filter_text else [])]

    def options(self):
        if self.modal == "model":return self.follow_option("model")+[(row.label,row.id) for row in self.catalog().models]
        if self.modal == "effort":
            current_model_id=self.scratch.get("model") if self.scratch else None
            model=next((row for row in self.catalog().models if row.id == current_model_id),None)
            # 明确的模型能力优先限制档位；没有能力证据时仍可独立写入宿主标准值，
            # 这些后备选项只表示配置合同允许，不能当作该模型已支持或调用成功的证明。
            if model and model.efforts:
                levels=model.efforts
            elif self.host == "claude":
                levels=("low","medium","high","xhigh","max")
            elif self.host == "codex":
                levels=("none","minimal","low","medium","high","xhigh","max")
            else:
                levels=()
            labels={"inherit":"继承宿主","none":"none (关闭推理)","minimal":"minimal (极低)","low":"low (低)","medium":"medium (中)","high":"high (高)","xhigh":"xhigh (极高)","max":"max (最大)"}
            rows=self.follow_option("effort")+[("继承宿主","inherit")]+[(labels.get(level,level),level) for level in levels]
            selected=self.edit_choice("effort") if self.scratch is not None else None
            if selected is not None and selected not in [value for _,value in rows]:
                # 新模型的能力可能不含原推理档位；保留原来源供用户核对，不能自动
                # reset、制造覆盖或把这个保留项误称为已经支持的模型能力。
                rows.append((f"当前设置 {selected}（需核对能力）",selected))
            return rows
        if self.modal == "manage":return [(label+(" · "+reason if (reason:=self.unavailable(action)) else ""),action) for action,label in self.manage_rows()]
        if self.modal == "add_mode":return [("仅登记项目（默认，不启用工作流）","register"),("登记并启用三宿主工作流","register_enable")]
        if self.modal in {"versions","runtime_versions"}:
            row=self.project_rows.get(str(self.project),{})
            current=binding_id(row.get("runtime_binding"))
            return [(item["content_id"][:12]+(" · 当前" if self.modal == "versions" and item["content_id"] == current else "")+" · "+item["label"],item["content_id"]) for item in self.version_rows]
        if self.modal == "backups":return [(f'{row["id"]} · {row["status"]}',row["id"]) for row in self.backup_rows]
        if self.modal == "commands":
            return [(self.action_label(row.action)+(f"  [{row.key}]" if row.key else "")+(" · "+reason if (reason:=self.unavailable(row.action)) else ""),row.action) for row in self.command_rows()]
        return []

    def follow_option(self,field):
        if self.global_scope or not self.project or not self.role:return []
        inherited=self.session.following_value(self.scope())[field]
        # 跟随项的标签不包含 inherit，搜索 inherit/继承宿主只会命中明确宿主选项。
        return [("跟随全局（"+("宿主默认" if inherited == "inherit" else inherited)+"）",None)]

    def edit_choice(self,field):
        """选择器定位按已保存/暂存的字段来源，而非仅按当前有效字符串。"""
        if field in self.scratch_fields:return self.scratch_fields[field]
        if field in self.scratch_choices:return self.scratch_choices[field]
        if not self.global_scope:return self.base_value(self.role).get("overrides",{}).get(field)
        return self.scratch[field]

    def list_kind(self):return self.modal if self.modal in LIST_MODALS else self.pane if not self.modal else None

    def visible_rows(self,kind=None):
        kind=kind or self.list_kind()
        if kind == "projects":
            rows=[(i,project_badge(self.project_rows.get(str(project)))+" · "+project.name,str(project),str(project)) for i,project in enumerate(self.projects)]
            rows.insert(0,(-1,"全局默认","global","全局默认"))
            rows.append((len(self.projects),"+ 登记项目","", ""))
        elif kind == "roles":
            installed=set(self.installed_roles())
            rows=[(i,("已移除 · " if role not in installed else "")+ROLE_LABELS.get(role,role),role,role) for i,role in enumerate(self.role_list())]
        elif kind in LIST_MODALS:rows=[(i,label,value,self.command_rows()[i].aliases if kind == "commands" else value) for i,(label,value) in enumerate(self.options())]
        else:return []
        query=(self.input if kind == "commands" else self.search_input.text if self.searching else self.filter_text) if kind == self.list_kind() else ""
        query=query.casefold().strip()
        return [(index,label,value) for index,label,value,extra in rows if not query or query in f"{label} {value} {extra}".casefold()]

    def selection(self):
        return self.index if self.modal else self.project_index if self.pane == "projects" else self.role_index

    def select(self,index):
        if self.modal:self.index=index
        elif self.pane == "projects":
            if index != self.project_index:
                self.role_selections[(self.scope_id,self.host)]=self.role
                self.project_index=index
                self.load_display()
                roles=self.role_list();previous=self.role_selections.get((self.scope_id,self.host))
                self.role_index=roles.index(previous) if previous in roles else 0
        else:self.role_index=index

    def sync_selection(self):
        rows=self.visible_rows()
        if rows and self.selection() not in [row[0] for row in rows]:self.select(rows[0][0])

    def view_frame(self):
        frame={key:getattr(self,key) for key in ("modal","index","scroll","text","pane","filter_text","project_index","host_index","role_index","role_column")}
        # 输入属于触发视图，预览/错误返回不能丢失路径，也不能被命令面板搜索覆盖。
        frame["editor"]=replace(self.editor)
        return frame

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
        role=self.role
        def ready():
            self.prepare_editor(role)
            self.scratch=self.current(self.role);self.scratch_choices=dict(self.drafts.get(self.scope(),{}));self.scratch_fields={}
            self.show_view("model")
            rows=self.options();self.index=next((i for i,(_,identifier) in enumerate(rows) if identifier == self.edit_choice("model")),0)
            self.notify("选择模型后 Enter 继续选择推理；尚未暂存或保存，Esc 取消")
        self.read_catalog(ready)

    def open_effort(self):
        if reason:=self.unavailable("effort"):raise ValueError(reason)
        role=self.role
        def ready():
            self.prepare_editor(role)
            self.scratch=self.current(self.role);self.scratch_choices=dict(self.drafts.get(self.scope(),{}));self.scratch_fields={}
            self.show_view("effort")
            rows=self.options();self.index=next((i for i,(_,val) in enumerate(rows) if val == self.edit_choice("effort")),0)
            self.notify("选择推理后 Enter 暂存，尚未保存；Esc 取消")
        self.read_catalog(ready)

    def prepare_editor(self,role):
        # 目录预读期间角色集合可能改变。必须仍定位用户触发的角色，不能让
        # 新投影的同一个数字行号悄悄改成另一个角色，更不能为旧草稿换前像。
        if role not in self.installed_roles():raise ValueError("角色已移除；已有草稿保留，请刷新后核对或按 u 丢弃")
        self.role_index=self.role_list().index(role)
        self.session.begin(self.scope(role))

    def stage(self):
        key=self.scope()
        # Session 按原前像比较来源和值；只确认过的字段能改变草稿及来源授权。
        self.session.stage(key,self.scratch_fields,self.catalog().stamp)
        choices=self.drafts.get(key,{})
        self.close_view()
        while self.modal in {"model","effort"}:self.close_view()
        self.scratch=None;self.scratch_choices={};self.scratch_fields={}
        self.notify("已暂存，尚未保存；按 s 保存预览，再按 Enter 确认写入" if choices else "无改动；当前角色没有待保存草稿，未写入配置", "warning" if choices else "info")

    def reset_field(self,field):
        """恢复跟随与 u 丢弃草稿是两种动作；None 明确交给共享服务清除该范围覆盖。"""
        if reason:=self.unavailable("reset-"+field):raise ValueError(reason)
        key=self.scope()
        def ready():
            self.prepare_editor(key[2])
            self.session.reset(key,field,self.catalog().stamp)
            choices=self.drafts.get(key,{})
            target="宿主" if self.global_scope else "全局"
            self.notify(("已暂存恢复跟随"+target+"；尚未保存，按 s 预览") if choices else "无改动；此字段已跟随"+target,"warning" if choices else "info")
        # reset 也是显式编辑入口，需要完整预读当前范围的来源，不能让保存预览补跑宿主。
        self.read_catalog(ready)

    def start_job(self,operation,after=None,*,show_result=True,name="管理操作",cancellable=False,
                  on_result=None,preserve_view=False,impact=None,writes=False,draft_keys=(),refresh=None,result_text=None):
        if self.future:
            self.notify("已有操作执行中，请等待真实结果","warning");return
        impact=impact or Impact(frozenset({self.scope_id}),self.host,
                               frozenset({str(self.project)}) if self.project else frozenset())
        job=self.session.prepare_job(self.view_frame(),self.frames,preserve_view=preserve_view,impact=impact,
                                     after=after,on_result=on_result,show_result=show_result,name=name,
                                     cancellable=cancellable,writes=writes,draft_keys=tuple(draft_keys),
                                     refresh=refresh,result_text=result_text)
        self.modal=None;self.frames=[];self.filter_text="";self.searching=False
        try:job.future=self.executor.submit(job.execute,operation)
        except Exception:
            self.restore_view(job.return_view);self.frames=list(job.return_frames)
            self.session.finish_job(job);raise
        self.notify("正在"+name+"；"+("Ctrl+C 可请求取消；已开始的事务等待结算" if cancellable else "请等待完成，此操作不支持中途取消"),"warning")

    def poll_job(self):
        if not self.future or not self.future.done():return
        job=self.session.job;failure=None
        try:
            try:job.future.result()
            except Exception as exc:failure=exc
            diagnostic="状态需刷新；上次操作未完成" if failure else ""
            self.session.settle_job(job,diagnostic)
            self.restore_view(job.return_view);self.frames=list(job.return_frames)
            if failure is None:
                if job.after:job.after()
                self.notify("已读取预览 / 状态，尚未写入" if job.on_result and not job.show_result else "操作完成","success")
                if job.on_result:job.on_result(job.result)
                elif job.show_result:
                    self.show_view("result");self.text=job.result_text(job.result) if job.result_text else str(job.result or "完成")
            else:raise failure
        except Exception as exc:
            # 回调也属于作业的收尾边界：恢复已清洗的入口后再显示诊断，不能让
            # 部分回调留下的确认页重新可提交。写入结算事实独立于刷新/回调成败。
            self.session.invalidate(job.impact,"状态需刷新；请查看上次操作诊断")
            self.restore_view(job.return_view);self.frames=list(job.return_frames)
            if job.writes and job.operation_completed:
                self.show_view("result")
                try:result=job.result_text(job.result) if job.result_text else str(job.result or "完成")
                except Exception:result="业务操作已完成；结果显示未完成，请刷新状态核对。"
                stage="状态刷新" if job.phase == "refresh" else "结果显示"
                self.text=result+"\n\n业务操作已完成；后续"+stage+"未完成，请刷新核对，勿重复提交。\n"+operation_error(exc)
                self.notify("业务操作已完成；"+stage+"未完成，请刷新核对","warning")
            else:
                self.show_view("error");self.text=operation_error(exc)
                self.notify("操作未完成；请查看诊断及保留的恢复信息","error")
        finally:self.session.finish_job(job)

    def query_project_rows(self,include=None):
        rows=project_service.project_summaries(self.state,self.scan)
        if include and not any(row["project"] == str(include) for row in rows):
            rows.append({**project_service.project_status(self.state,include),"registered":False})
        return rows

    def accept_project_rows(self,rows,*,selected=None):
        """缓存仅用于展示；列表身份跟随权威结果，删除后选相邻项且不复活隐藏项目。"""
        old_index=self.project_index;old_project=self.project;old_role=self.role;keep_global=self.global_scope and selected is None
        selected=selected or old_project
        self.project_rows={row["project"]:row for row in rows};self.status_error=""
        self.projects=[Path(row["project"]) for row in rows]
        self.project_index=-1 if keep_global else self.projects.index(selected) if selected in self.projects else min(max(0,old_index),max(0,len(self.projects)-1))
        if not self.projects:self.pane="projects"
        roles=self.role_list() if self.project or self.global_scope else []
        self.role_index=roles.index(old_role) if self.project == old_project and old_role in roles else 0
        self.filter_text=""

    def refresh_project_status(self):
        selected=self.project
        self.start_job(lambda:self.query_project_rows(selected),show_result=False,name="读取项目与固定版本状态",
                       on_result=lambda rows:self.accept_project_rows(rows,selected=selected),preserve_view=True,
                       impact=Impact(frozenset(),projects=None))

    def preview_project(self,project,action,**options):
        def ready(plan):
            self.project_rows[str(project)]={**plan.status_before,"registered":plan.registered_before}
            self.project_plan=plan;self.show_view("project_plan");self.text=project_plan_text(plan.summary)
            if not plan.summary["can_apply"]:self.notify("预览发现冲突，不能应用；查看冲突路径或返回预览修复","warning")
        self.start_job(lambda:project_service.preview_project(self.state,project,action,native_context=self.native_context,**options),show_result=False,
                       name="预览"+PROJECT_ACTION_LABELS[action],on_result=ready,preserve_view=True)

    def apply_project(self):
        plan=self.project_plan
        if plan is None or not plan.summary["can_apply"]:
            self.notify("计划含冲突，不能确认；请返回核对冲突或预览修复","warning");return
        host=self.host;old_index=self.project_index;old_project=self.project;old_role=self.role
        def refresh(result):
            rows=self.query_project_rows(None if plan.action == "del" else plan.project)
            paths=[Path(row["project"]) for row in rows]
            selected=plan.project if plan.project in paths else paths[min(max(0,old_index),len(paths)-1)] if paths else None
            context=model_preferences.load_context(self.state,selected,host,native_context=self.native_context) if selected is not None else None
            return rows,selected,context
        def ready(result):
            rows,selected,context=self.session.job.refreshed
            self.accept_project_rows(rows,selected=plan.project)
            if context is not None:self.session.accept_context((str(selected),host),context)
            roles=self.role_list()
            if self.project == old_project and old_role in roles:self.role_index=roles.index(old_role)
            if plan.action == "del":
                # 列表变化后清除旧入口帧，结果页返回当前相邻项。其他范围的模型草稿原样保留。
                self.modal=None;self.frames=[];self.pane="projects"
            elif plan.action == "add":
                self.modal=None;self.frames=[];self.pane="roles" if result["enabled"] else "projects"
            self.show_view("result");self.text=project_result_text(result,HOST_NAMES)
            if result.get("cancel_requested"):self.notify("取消请求到达时事务已经开始；已完成结算，请查看真实结果","warning")
        # 服务拥有组合锁、条件前像与停用后解除登记；UI 仅把只读刷新独立成
        # 后置阶段。计划在提交时即消费，后置刷新失败也不能再提交同一计划。
        self.start_job(lambda:project_service.apply_project(plan,cancel=self.cancel_job),name=PROJECT_ACTION_LABELS[plan.action],
                       on_result=ready,cancellable=True,writes=True,refresh=refresh,
                       impact=Impact(frozenset({str(plan.project)}),projects=frozenset({str(plan.project)})),
                       result_text=lambda result:project_result_text(result,HOST_NAMES))
        self.project_plan=None

    def runtime_summary(self):
        return self.runtime_plan if isinstance(self.runtime_plan,dict) else self.runtime_plan.summary

    def runtime_action(self,action,content_id=None):
        """中央动作与项目动作共用作业/滚动确认，不借全局默认行存中央状态。"""
        if action == "runtime-status":
            self.start_job(lambda:central_runtime.status(self.state),name="读取中央运行时状态",preserve_view=True,
                           result_text=runtime_status_text);return
        if action == "runtime-activate" and content_id is None:
            def versions(rows):
                self.version_rows=rows;self.show_view("runtime_versions")
                if not rows:self.notify("中央库没有已导入版本；先导入中央核心","warning")
            self.start_job(lambda:runtime_store.list_cores(self.state),show_result=False,name="读取中央版本",on_result=versions,preserve_view=True);return
        def preview():
            if action == "runtime-install":
                inspected=runtime_store.inspect_core(project_service.SOURCE)
                return {"action":"install","can_apply":True,"runtime_binding":{key:inspected[key] for key in ("protocol_version","content_id","manifest_sha256")}}
            if action == "runtime-recover":return central_runtime.preview_recovery(self.state,native_context=self.native_context)
            return central_runtime.preview(self.state,action.removeprefix("runtime-"),
                        binding=project_service.runtime_binding(self.state,content_id) if content_id else None,native_context=self.native_context)
        def ready(plan):
            self.runtime_plan=plan;self.show_view("runtime_plan");self.text=runtime_plan_text(self.runtime_summary())
        self.start_job(preview,show_result=False,name="预览中央操作",on_result=ready,preserve_view=True)

    def apply_runtime(self):
        plan=self.runtime_plan
        if plan is None or not self.runtime_summary()["can_apply"]:return
        summary=self.runtime_summary();project,host,scope_id=self.project,self.host,self.scope_id
        def operation():
            if summary["action"] == "install":
                core=runtime_store.import_core(project_service.SOURCE,self.state,expected_binding=summary["runtime_binding"])
                return {"runtime_binding":core.binding(),"installed":True}
            if summary["action"] == "recover":return central_runtime.recover(plan)
            return central_runtime.apply(plan,cancel=self.cancel_job)
        def refresh(result):
            # 中央切版会失效所有旧显示，但当前范围必须取得新上下文再回主界面，
            # 否则成功返回后会把已启用角色误显示为空；旧草稿前像不随刷新续期。
            rows=self.query_project_rows(project)
            context=model_preferences.load_context(self.state,project,host,native_context=self.native_context)
            return rows,context
        # 中央 apply 返回的是整个固定批次事实；后续列表刷新失败仍展示服务原结果，
        # 不会重建计划或误报未写。恢复不支持中途取消，按钮忙态直至结算。
        self.start_job(operation,name="执行中央操作",writes=True,cancellable=summary["action"] in {"activate","rollback"},
                       impact=Impact(None,projects=None),result_text=runtime_result_text,
                       refresh=refresh,
                       on_result=lambda result:self.accept_runtime_result(result,(scope_id,host)))
        self.runtime_plan=None

    def accept_runtime_result(self,result,key):
        rows,context=self.session.job.refreshed
        self.accept_project_rows(rows)
        self.session.accept_context(key,context)
        self.show_view("result");self.text=runtime_result_text(result)+"\n\n逐项目实际状态：\n"+"\n\n".join(status_text(row,HOST_NAMES) for row in rows)

    def reset_platform(self):
        if reason:=self.unavailable("reset-platform"):raise ValueError(reason)
        project,host,scope_id=self.project,self.host,self.scope_id
        keys=tuple(key for key in self.session.entries if key[:2] == (scope_id,host))
        def ready(plan):
            # 提案从服务持久来源生成，不能先把 reset 塞入 Session 续期/覆盖旧授权。
            # captured keys 只在这一个计划真实成功时消费；取消、冲突和失败均保留。
            self.preference_plan=plan;self.preference_keys=keys;self.preference_reset=True
            self.show_view("preview");self.text="当前项目 · 当前平台 · 全部角色恢复跟随全局\n确认将替代当前范围在生成提案时已有的未保存草稿；其他范围保留。\n\n"+preference_plan_text(plan.summary,HOST_NAMES)
        self.start_job(lambda:model_preferences.reset_platform(self.state,project,host,native_context=self.native_context),
                       show_result=False,name="预览整平台恢复",on_result=ready,preserve_view=True)

    def manage_action(self,action):
        if action.startswith("runtime-"):self.runtime_action(action);return
        if action == "reset-platform":self.reset_platform();return
        if action in {"reset-model","reset-effort"}:self.reset_field(action.split("-",1)[1]);return
        if action == "sources":
            def ready():
                catalog=self.catalog()
                self.show_view("sources");self.text="\n".join([f"{row.id} · {row.source}" for row in catalog.models]+catalog.notes+catalog.inactive)
            self.read_catalog(ready);return
        if not self.project:raise ValueError("请先按 a 添加项目")
        project=self.project
        if reason:=self.unavailable(action):raise ValueError(reason)
        if action in {"enable","disable","follow","rollback","repair","del"}:self.preview_project(project,action)
        elif action == "install":
            # “导入当前来源”仍走当前中央启用计划：来源校验、只读预览和条件发布
            # 均由服务层负责；确认写入统一使用中央计划页，不保留已不可达的旧弹窗。
            self.preview_project(project,"enable",source_root=project_service.SOURCE)
        elif action == "check":self.start_job(lambda:service.check(project,state=self.state),name="检查工作流",preserve_view=True)
        elif action == "versions":
            def ready(rows):
                self.version_rows=rows;self.show_view("versions")
                if not rows:self.notify("中央内容库没有已导入版本；先启用项目或导入当前来源","warning")
            self.start_job(lambda:runtime_store.list_cores(self.state),show_result=False,name="校验中央版本列表",on_result=ready,preserve_view=True)
        elif action == "details":
            def ready(row):
                cached=self.project_rows.get(str(project),{})
                row={**row,"registered":cached.get("registered")}
                self.project_rows[str(project)]=row;self.show_view("details");self.text=status_text(row,HOST_NAMES)
                if row.get("conflicts"):self.notify("项目存在冲突；详情保留完整路径与修复方向","warning")
            self.start_job(lambda:project_service.project_status(self.state,project),show_result=False,name="读取三宿主详情",on_result=ready,preserve_view=True)
        elif action == "backups":
            rows=service.backups(self.state,self.project);self.show_view("backups");self.backup_rows=rows
            if not rows:self.notify("当前项目还没有模型配置备份；应用模型配置后可在此查看和恢复")

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
            selected=self.options()[self.index][1];self.scratch_fields["model"]=selected
            self.scratch["model"]=selected if selected is not None else self.session.following_value(self.scope())["model"]
            if host in {"codex","claude"}:
                self.show_view("effort");self.index=next((i for i,(_,value) in enumerate(self.options()) if value == self.edit_choice("effort")),0)
                self.notify("已选择模型，尚未暂存或保存；选择推理后 Enter 暂存，Esc 返回")
            else:self.stage()
        elif self.modal == "effort":
            selected=self.options()[self.index][1];self.scratch_fields["effort"]=selected
            self.scratch["effort"]=selected if selected is not None else self.session.following_value(self.scope())["effort"]
            self.stage()
        elif self.modal == "manage":self.manage_action(self.options()[self.index][1])
        elif self.modal == "add_mode":self.preview_project(self.add_target,"add",enable=self.options()[self.index][1] == "register_enable")
        elif self.modal == "versions":self.preview_project(project,"use",content_id=self.options()[self.index][1])
        elif self.modal == "runtime_versions":self.runtime_action("runtime-activate",self.options()[self.index][1])
        elif self.modal == "runtime_plan":self.apply_runtime()
        elif self.modal == "project_plan":self.apply_project()
        elif self.modal == "preview":
            plan=self.preference_plan
            if plan is None or not plan.summary["can_apply"]:
                self.notify("计划含冲突，不能保存；请核对诊断后重新预览","warning");return
            keys=self.preference_keys if self.preference_reset or plan.summary["changes"] else ();scope_id=self.scope_id;label=self.scope_label
            message=("整平台恢复" if self.preference_reset else "已保存模型配置")+f" · {label} / {HOST_NAMES[host]}"
            def apply():
                result=model_preferences.apply(plan)
                if not result["applied"] and plan.summary["changes"]:raise ValueError(result.get("diagnostic") or "配置未应用；草稿保留")
                return result
            def saved(result):
                self.session.accept_context((scope_id,host),self.session.job.refreshed)
                self.show_view("result");self.text=message+"\n"+preference_result_text(result)
                self.notify(message if result["applied"] else "无改动；未写入配置，未创建备份","success" if result["applied"] else "info")
            # 全局权威能影响所有项目的跟随字段；失败也按同一宿主的全部显示
            # 范围失效。其他草稿的 expected/stamp 始终保留，只有本次成功项结算。
            affected=frozenset(row["project"] for row in plan.summary.get("affected_projects",[]))
            impact=Impact(None if self.global_scope else frozenset({scope_id}),host,
                          affected if self.global_scope else frozenset({str(project)}))
            self.start_job(apply,name="备份并保存模型配置",on_result=saved,writes=True,draft_keys=keys,
                           impact=impact,refresh=lambda result:model_preferences.load_context(self.state,project,host,native_context=self.native_context),
                           result_text=lambda result:message+"\n"+preference_result_text(result))
            self.preference_plan=None
        elif self.modal == "backups":
            if not self.backup_rows:return
            changes=service.prepare_restore(self.state,project,self.options()[self.index][1])
            self.show_view("restore");self.changes=changes
            self.text="恢复以下配置；恢复前会再保存一份备份：\n"+"\n".join(row.relative for row in self.changes)
        elif self.modal == "restore":
            # 恢复计划携带原版本指纹，不可转成普通 list 丢失发布前/验收后复核。
            changes=self.changes
            def restore():
                identifier=service.commit(self.state,project,changes,lambda:service.check(project,state=self.state),native_context=self.native_context)
                return service.backup_summary(project,identifier)
            def restored(result):
                self.session.accept_context((str(project),host),self.session.job.refreshed)
                self.show_view("result");self.text=str(result or "完成")
            self.start_job(restore,name="恢复模型配置",writes=True,
                           impact=Impact(frozenset({str(project)}),projects=frozenset({str(project)})),
                           refresh=lambda result:model_preferences.load_context(self.state,project,host,native_context=self.native_context),
                           on_result=restored)
            self.changes=[]
        elif self.modal == "quit":
            if not self.can_confirm_quit():self.notify("请放大窗口后确认，草稿仍保留","warning");return
            self.exit_code=self.quit_code;self.done=True
        elif not self.modal:
            if self.pane == "projects":
                if self.project is None and not self.global_scope:self.act("add")
                else:self.pane="roles";self.filter_text=""
            else:
                if self.role_column == "effort":self.open_effort()
                else:self.open_model()

    def quit(self,*,interrupted=False):
        self.quit_code=130 if interrupted else 0
        if self.drafts:
            if self.modal != "quit":self.show_view("quit")
            self.text=f"有 {len(self.drafts)} 项未应用草稿（包含全局 / 其他项目 / 宿主）。\n\nEnter 放弃全部草稿并退出；Esc 返回，不写入项目。"
        else:self.done=True;self.exit_code=self.quit_code

    def interrupt(self):
        if self.future:
            if self.session.job.cancellable:
                self.cancel_job.set();self.notify("已请求取消；执行前可拒绝，已开始的事务等待真实结果与必要恢复","warning")
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
        elif action == "pane":
            # 方向键设置目标区域，而不是反复切换；同方向重复输入不会跳回另一侧。
            target="projects" if key == "left" else "roles"
            if self.pane != target:self.pane=target;self.filter_text=""
        elif action == "host":
            # Tab 与数字/鼠标共用平台切换合同，保留项目、区域、角色身份和全部范围草稿。
            role=self.role
            self.host_index=(self.host_index+(-1 if key == "backtab" else 1))%len(HOSTS) if key in {"tab","backtab"} else int(key)-1
            self.load_display()
            rows=self.role_list()
            self.role_index=rows.index(role) if role in rows else 0;self.filter_text=""
        elif action == "confirm":self.confirm()
        elif action == "edit":self.open_model()
        elif action == "effort":self.open_effort()
        elif action == "manage":
            if reason:=self.unavailable("manage"):raise ValueError(reason)
            self.show_view("manage")
        elif action.startswith("runtime-") or action in {"install","check","backups","sources","enable","disable","follow","versions","rollback","repair","details","del","reset-platform","reset-model","reset-effort"}:self.manage_action(action)
        elif action == "preference-details":
            if reason:=self.unavailable(action):raise ValueError(reason)
            value=self.current(self.role);names={"project":"项目","global":"全局","host":"宿主"}
            lines=[f"范围  {self.scope_label}",f"角色  {self.role}"]
            for field,label in (("model","模型"),("effort","推理")):
                choice=self.drafts.get(self.scope(),{}).get(field,value.get("overrides",{}).get(field))
                # 有效来源为宿主时仍需区分“跟随全局inherit”和项目明确inherit，
                # 否则用户无法判断以后修改全局默认会不会影响这个字段。
                relation=("跟随宿主默认" if self.global_scope else "跟随全局") if choice is None else "明确继承宿主" if choice == "inherit" else "明确设置"
                lines += ["",f"{label}  {value[field]}","来源  "+names.get(value.get('sources',{}).get(field),'未知'),"设置  "+relation]
            self.show_view("preference_details");self.text="\n".join(lines)+"\n\n修改哪个字段就覆盖哪个。恢复跟随通过管理菜单或命令面板暂存；u 仅丢弃草稿。"
        elif action == "version-details":
            if not self.version_rows:raise ValueError("中央内容库没有已导入版本")
            row=self.version_rows[self.index]
            self.show_view("version_details")
            self.text="\n".join(["完整内容 ID  "+row["content_id"],"清单 SHA256  "+row["manifest_sha256"],
                                  "来源标签（仅说明，不作为版本身份）  "+row["label"],"中央核心路径  "+row["root"],
                                  "", "Esc 返回版本列表；Enter 仅在列表中预览选择版本。"])
        elif action == "commands":self.show_view("commands");self.input="";self.sync_selection()
        elif action == "add":self.show_view("add");self.input=""
        elif action == "add-confirm":
            # 空格可以属于真实目录名：把完整输入交给唯一安装器解析，禁止先 strip。
            # 该入口同时保留原样优先、引号/反斜杠拖入、单目录及源包包含保护，绝不执行 shell。
            try:project=target_path(self.input,project_service.SOURCE)
            except InstallError as exc:raise ValueError(str(exc)) from exc
            project=state_files.project_path(project)
            self.add_target=project;self.show_view("add_mode")
        elif action == "preview":
            if not self.pending():self.notify("无改动；当前范围没有待保存草稿，未写入配置");return
            # 来源、归属与固定核心校验包含真实文件 I/O，必须沿既有单作业线程
            # 执行，让主线程继续绘制忙态和处理 Ctrl+C。提交前的服务 guard 不变。
            # 作业只消费这次按键的完整快照，不能在后台重读后来切换的 App 范围，
            # 也不能让可变 Catalog/草稿字典随显示刷新而续期本次来源授权。
            state,project,host,scope_id,context=self.state,self.project,self.host,self.scope_id,self.native_context
            choices=deepcopy(self.pending());keys=tuple((scope_id,host,role) for role in choices)
            expected=deepcopy({role:self.expected[(scope_id,host,role)] for role in choices})
            stamp=self.catalog().stamp;stamps=tuple(self.source_stamps.get(key) for key in keys)
            bundle=deepcopy(self.catalogs.get((scope_id,host)))
            def preview():
                # UI 只核对本次冻结的 bundle/草稿来源，不重复读取来源文件。
                # 服务 preview 唯一执行 check_catalogs 并返回不可保存的冲突计划；
                # apply 仍独立重验。这里的本地授权失败沿原错误出口保留草稿。
                if bundle is None or stamp and any(source != stamp for source in stamps):
                    raise ValueError("模型来源或能力已变化；草稿保留，请重新进入模型/推理选择，或按 u 丢弃当前角色草稿")
                return model_preferences.preview(state,project,host,choices,bundle,expected,native_context=context)
            def ready(plan):
                # 正常键盘导航在忙态被既有 dispatch 守卫拒绝；仍封闭检查回调归属，
                # 避免外部项目列表更新把原范围的确认计划展示到另一范围。
                if (self.scope_id,self.project,self.host) != (scope_id,project,host):
                    raise ValueError("保存预览范围已变化；草稿保留，请返回原范围重新预览")
                self.preference_keys=keys;self.preference_reset=False
                self.show_view("preview");self.preference_plan=plan;self.text=preference_plan_text(plan.summary,HOST_NAMES)
                self.notify("保存预览已生成，尚未写入；Enter 确认备份并保存，Esc 返回保留草稿" if plan.summary["can_apply"] else "预览发现冲突，不能保存；草稿保留", "warning")
            self.preference_plan=None
            self.start_job(preview,show_result=False,name="生成保存预览",on_result=ready,preserve_view=True,
                           impact=Impact(frozenset({scope_id}),host),writes=False)
        elif action == "refresh":
            role=self.role
            # 丢弃当前 scope 的快照；下一次显式编辑按需查询，不影响其他项目/平台目录。
            self.session.invalidate(Impact(frozenset({self.scope_id}),self.host))
            self.load_display(force=True)
            rows=self.role_list();self.role_index=rows.index(role) if role in rows else 0
            self.filter_text="";self.sync_selection()
            if (self.scope_id,self.host) not in self.roles_errors:
                self.notify("本地来源已刷新，草稿保留；冲突时按 u 丢弃当前角色草稿后重新编辑")
            if hasattr(self,"executor"):self.refresh_project_status()
        elif action == "discard":
            key=self.scope()
            self.session.discard(key)
            self.sync_selection()
            self.notify("已丢弃当前角色草稿；下次编辑使用当前配置，其他草稿保留")
        elif action == "help":
            text="当前视图\n"+"\n".join(f"{row.key:12} {row.label}" for row in self.bindings())
            text+="\n\n主界面命令（: 可按名称搜索）\n"+"\n".join(f"{row.key or '命令面板':12} {self.action_label(row.action)}" for row in self.command_rows())
            text+="\n\n项目列表上方的全局默认独立于项目计数；在项目区按 Home 可选择。草稿按全局/项目/平台隔离。\n项目直接编辑哪个字段就覆盖哪个，v 查看字段来源；g 或 : 搜索恢复模型/推理跟随全局。\n全局恢复跟随宿主；显式 inherit 始终表示宿主。u 只丢弃当前角色草稿。\n全局保存先列出受影响项目及冲突，再确认备份并保存。\n\n主界面 Tab 下一平台，Shift+Tab 上一平台，首尾循环；1/2/3 和顶部点击也可切换。\n左箭头聚焦项目，右箭头聚焦右侧内容；重复同方向保持当前区域，上下选择。\n模型保存：m 选择模型，再 Enter 选择推理、Enter 暂存；e 可只改推理。\n角色表 Enter 按当前选中列编辑；鼠标可选模型/推理列，m/e 随时独立进入对应编辑。\n已选择/已暂存均尚未保存；无改动不写入。按 s 查看保存预览，Enter 确认后才备份保存。\nEsc 取消选择或保存预览；已有草稿保留。失败/冲突保留草稿，核对诊断后重选或 u 丢弃。\n目录失败/来源变化后重新进入模型或推理编辑可重试；旧来源草稿须重新确认选择。\n/ 搜索后 Enter 只接受筛选，再按 Enter 才确认；输入中的左右键移动光标。\n弹层和输入中的 Tab/左右不切换底层平台或区域。\n鼠标单击只选中，Enter 确认。\na 输入目录后可选仅登记（默认）或登记并启用；所有写操作先预览，Esc 不写入。\n主界面 o 预览启用、p 预览停用选中项目；再次 Enter 确认。状态待刷新/冲突时以服务预览为准。\ng / : 可查看中央状态、导入/激活/回退/恢复；项目跟随清除锁版，use/项目回退保持锁版。\n整平台恢复只作用当前项目当前平台全部角色，独立预览，Esc/失败保留草稿；全局默认不提供批量恢复。\n版本列表 i 查看完整 ID，Enter 只读预览；完整 ID 才是版本身份。\nCtrl+C 在执行前可请求取消，事务已经开始后等待结算；不会终止已运行任务。\n角色配置在新创建的子 Agent 生效；已有 Agent 不会被重启。\n缓存表示本地可见，不保证模型调用成功。"
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
                self.close_view()
                left_editor=previous in {"model","effort"} and self.modal not in {"model","effort"}
                if left_editor:
                    # 编辑入口也可能来自管理页中的命令面板；回到该入口同样是
                    # 取消，不能因 modal 仍非空就残留未暂存的旧授权和 scratch。
                    self.session.cancel_edit(self.scope())
                    self.scratch=None;self.scratch_choices={};self.scratch_fields={}
                if previous == "quit":self.quit_code=0
                if previous == "project_plan":self.project_plan=None
                if previous == "runtime_plan":self.runtime_plan=None
                if previous == "preview":self.preference_plan=None;self.notify("已取消保存预览；草稿保留，尚未写入配置","warning")
                elif previous in {"model","effort"}:
                    self.notify("已取消本次选择；已有草稿保留，未写入配置" if left_editor else "已返回模型选择，尚未保存")

    def dispatch(self,key):
        if key == "ctrl-c":self.interrupt();return
        if self.future:return
        if self.modal in {"add","commands"} and key not in {"enter","esc","up","down","pageup","pagedown"}:
            self.editor.edit(key)
            if self.modal == "commands":self.sync_selection()
            return
        if self.searching and key not in {"enter","esc","up","down","pageup","pagedown"}:
            self.search_input.edit(key);self.sync_selection();return
        groups={"↑↓":{"up","down"},"PgUp/PgDn":{"pageup","pagedown"},"Home/End":{"home","end"},"1/2/3":{"1","2","3"},"Tab/Shift+Tab":{"tab","backtab"},"←→":{"left","right"}}
        for row in self.bindings():
            if key in groups.get(row.key,set()) or row.key.lower() == key:
                try:self.act(row.action,key)
                except (OSError,ValueError,KeyError,TypeError) as exc:self.notify(exc,"error")
                return

    def put(self,y,x,text,width=None,attr=0):
        h,w=self.screen.getmaxyx()
        if y<0 or y>=h or x<0 or x>=w:return
        # 右边框必须能写入最后一列。ncurses 写入右下角后可能报告 ERR，
        # 该格已绘制且未开启滚屏；沿用下面的异常边界，不让框架少一条边。
        available=min(w-x,width if width is not None else w-x)
        if available<=0:return
        try:self.screen.addstr(y,x,clip(text,available),attr)
        except curses.error:pass

    def row(self,y,x,width,text,attr=0):self.put(y,x,padded(text,width),width,attr)

    def footer_lines(self,width):
        priority=("host","pane","confirm","add-confirm","accept-search","commands","help","back","search","preview","effort","interrupt","wait")
        bindings=self.bindings();chosen=[]
        for action in priority:
            match=next((row for row in bindings if row.action == action),None)
            if match and match not in chosen:chosen.append(match)
        lines=[""]
        for row in chosen:
            token=ellipsize(f"[{row.key}] {row.label}",width)
            if lines[-1] and cell_width(lines[-1])+cell_width(token)+2>width:
                if len(lines)>=2:break
                lines.append("")
            lines[-1]+=("  " if lines[-1] else "")+token
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
        x=layout.left;width=layout.sidebar-x-2 if layout.sidebar else layout.span-2
        active=self.pane == "projects"
        query=self.search_input.text if self.searching and active else self.filter_text if active else ""
        title=("◈ " if active else "  ")+"项目列表"
        if layout.compact:title+=f" · {len(self.projects)} 个项目"
        self.put(layout.pane_title,x,ellipsize(title,width),width,self.theme.focus if active else self.theme.title)
        if not layout.compact:
            if self.searching and active:self.draw_input(layout.pane_subtitle,x,width,self.search_input)
            else:self.put(layout.pane_subtitle,x,ellipsize("/ "+query if query else self.status_error or f"{len(self.projects)} 个本地项目",width),width,self.theme.warning if self.status_error else self.theme.muted)
        elif self.searching and active:
            # 紧凑标题内保留输入光标，正文与固定全局入口不被搜索框挤走。
            self.draw_input(layout.pane_title,x,width,self.search_input)
        global_selected=self.global_scope
        attr=self.theme.selected if active and global_selected else self.theme.inactive if global_selected else self.theme.text
        pending=any(key[0] == "<global>" for key in self.drafts)
        self.row(layout.global_entry,x,width,("▌ " if active and global_selected else "› " if global_selected else "  ")+("● " if pending else "")+"全局默认",attr)
        self.hits.append((layout.global_entry,x,width,"project",-1))
        if not layout.compact:self.put(layout.global_entry+1,x,"┄"*width,width,self.theme.border)
        end=layout.list_bottom
        # 固定全局入口不参加真实项目的滚动/数量；虚线没有命中区。
        row_height=1 if layout.compact else 3
        available=max(1,(end-layout.project_start)//row_height)
        rows=[row for row in self.visible_rows("projects") if row[0] != -1]
        selected=next((i for i,row in enumerate(rows) if row[0] == self.project_index),0)
        start=max(0,selected-available+1)
        if active:self.page_lines=available
        for offset,(index,label,_) in enumerate(rows[start:start+available]):
            pending=index<len(self.projects) and any(key[0] == str(self.projects[index]) for key in self.drafts)
            is_sel=index == self.project_index
            attr=self.theme.selected if active and is_sel else self.theme.inactive if is_sel else self.theme.text
            marker="▌ " if active and is_sel else "› " if is_sel else "  "
            y=layout.project_start+offset*row_height
            display=self.projects[index].name if index<len(self.projects) else label
            detail=project_badge(self.project_rows.get(str(self.projects[index]))) if index<len(self.projects) else "a 输入现有项目目录"
            text=marker+("● " if pending else "")+display
            if layout.compact and index<len(self.projects):text=ellipsize(text,max(8,width-12))+" · "+detail
            self.row(y,x,width,text,attr);self.hits.append((y,x,width,"project",index))
            if not layout.compact:
                # 状态/pin属于辅助行：保留选中背景与颜色，但不继承名称行的粗体。
                self.row(y+1,x,width,"  "+detail,(attr & ~curses.A_BOLD) if is_sel else self.theme.muted)
                self.hits.append((y+1,x,width,"project",index))
                if y+2<end:self.put(y+2,x,"┄"*width,width,self.theme.border)
        if not rows:self.put(layout.project_start,x,"无匹配 · a 登记",width,self.theme.warning)
        if len(rows)>available:
            sb_x=layout.sidebar-1 if layout.sidebar else layout.right
            draw_scrollbar(self.put,layout.project_start,sb_x,min(available*row_height,end-layout.project_start),len(rows),start,available,self.theme.border)

    def draw_roles(self,layout):
        x=layout.sidebar+2 if layout.sidebar else layout.left;width=layout.right-x-1
        active=self.pane == "roles"
        title=("◈ " if active else "  ")+"角色模型"
        if layout.compact:title+=" · "+self.scope_label
        self.put(layout.pane_title,x,ellipsize(title,width),width,self.theme.focus if active else self.theme.title)
        if self.searching and active:self.draw_input(layout.pane_title if layout.compact else layout.pane_subtitle,x,width,self.search_input)
        elif not layout.compact:
            subtitle="/ "+self.filter_text if active and self.filter_text else f"{self.scope_label} · {HOST_LABELS[self.host_index]} · {len(self.pending())} 项未保存"+(" · ←项目 / →内容" if not layout.sidebar else "")
            self.put(layout.pane_subtitle,x,ellipsize(subtitle,width),width,self.theme.muted)
        role_width=18 if width>=65 else 14;effort_width=10;model_width=max(5,width-role_width-effort_width-2)
        model_hdr="模型 [m]" if width>=55 else "模型"
        effort_hdr="推理 [e]" if width>=55 else "推理"
        self.put(layout.role_header,x,padded("角色",role_width)+" "+padded(model_hdr,model_width)+" "+padded(effort_hdr,effort_width),width,self.theme.title)
        rows=self.visible_rows("roles");available=max(1,layout.list_bottom-layout.role_start)
        if active:self.page_lines=available
        selected=next((i for i,row in enumerate(rows) if row[0] == self.role_index),0);start=max(0,selected-available+1)
        if not rows:
            row=self.project_rows.get(str(self.project))
            if self.global_scope:hint="当前平台没有可用的工作流角色"
            elif not self.project:hint="尚无项目 · a 登记项目"
            elif self.filter_text and active:hint="无匹配 · Esc 清除筛选"
            elif row and row["state"] in {"unmanaged","disabled"}:hint="工作流未启用 · o 预览启用"
            else:hint="没有已安装角色 · o 预览启用 / g 查看状态"
            self.put(layout.role_start,x,ellipsize(self.roles_errors.get((self.scope_id,self.host),hint),width),width,self.theme.warning)
        for offset,(index,label,role) in enumerate(rows[start:start+available]):
            try:value=self.current(role)
            except (OSError,ValueError):value={"model":"配置异常","effort":"?"}
            is_sel=index == self.role_index;pending=self.scope(role) in self.drafts
            attr=self.theme.selected if active and is_sel else self.theme.inactive if is_sel else self.theme.text
            prefix=("▌" if (active and is_sel) else "›" if is_sel else " ")+("●" if pending else " ")
            raw_model="继承" if value["model"] == "inherit" else value["model"];raw_effort="继承" if value["effort"] == "inherit" else value["effort"]
            disp_model=("▸" if active and is_sel and self.role_column == "model" else "")+raw_model
            disp_effort=("▸" if active and is_sel and self.role_column == "effort" else "")+raw_effort
            self.row(layout.role_start+offset,x,width,padded(prefix+label,role_width)+" "+padded(disp_model,model_width)+" "+padded(disp_effort,effort_width),attr)
            self.hits.append((layout.role_start+offset,x,width,"role",index))
        if len(rows)>available:
            draw_scrollbar(self.put,layout.role_start,layout.right,available,len(rows),start,available,self.theme.border)

    def draw_modal(self,layout):
        titles={"model":"选择模型","effort":"选择推理级别","manage":"工作流管理","preview":"保存预览","backups":"模型配置备份","restore":"恢复确认","sources":"本地模型来源","help":"快捷键帮助","quit":"退出确认","add":"登记项目 · 输入目录","add_mode":"选择登记方式","project_plan":"项目管理 · 只读预览","versions":"中央版本列表 / 选择","version_details":"完整版本详情","details":"项目 / 三宿主详情","result":"操作结果","error":"操作未完成","commands":"命令面板","preference_details":"当前角色值与来源","runtime_versions":"选择中央激活版本","runtime_plan":"中央运行时 · 只读预览"}
        modal_title=titles.get(self.modal,self.modal)
        x=layout.modal_x;width=layout.modal_width
        inner_x=layout.modal_inner_x;inner_w=layout.modal_inner_width
        box_h=layout.bottom-layout.modal_top+1
        count=""
        if self.modal in LIST_MODALS:
            rows=self.visible_rows()
            selected=next((i for i,row in enumerate(rows) if row[0] == self.index),0)
            count=f" {selected+1 if rows else 0} / {len(rows)} "
        elif self.modal not in {"add"}:
            lines=wrapped(self.text,inner_w)
            available=max(1,layout.bottom-layout.modal_body)
            self.scroll=min(self.scroll,max(0,len(lines)-available))
            if len(lines)>available:
                count=f" {self.scroll+1}–{min(len(lines),self.scroll+available)} / {len(lines)} "

        title_attr=self.theme.error if self.modal in {"error","quit"} else self.theme.focus
        draw_box(self.put,layout.modal_top,x,box_h,width,title=modal_title,count=count,border_attr=self.theme.border,title_attr=title_attr,count_attr=self.theme.muted)
        # 弹层底边并入全宽状态分隔，圆角在这一行会留下断口；
        # 两端使用向上的 T 形接头，让弹层竖边与轻分隔连续相接。
        self.put(layout.bottom,x,"┴",1,self.theme.border)
        self.put(layout.bottom,x+width-1,"┴",1,self.theme.border)

        target=self.project_plan.project if self.modal == "project_plan" and self.project_plan else self.add_target if self.modal == "add_mode" else self.project
        sub_info=ellipsize(("中央运行时 / "+str(self.state)) if self.modal in {"runtime_plan","runtime_versions"} else f"{self.scope_label if self.global_scope else target or '未选择项目'} / {HOST_LABELS[self.host_index]}",inner_w,tail=True)
        self.put(layout.modal_top+1,inner_x,sub_info,inner_w,self.theme.muted)
        self.put(layout.modal_top+2,x,"├"+"─"*(width-2)+"┤",width,self.theme.border)

        if self.modal in LIST_MODALS:
            if self.modal == "commands":self.draw_input(layout.modal_body,inner_x,inner_w,self.editor)
            elif self.searching:self.draw_input(layout.modal_body,inner_x,inner_w,self.search_input)
            else:self.put(layout.modal_body,inner_x,ellipsize("/ "+self.filter_text if self.filter_text else "↑↓ 选择 · / 搜索 · Enter 确认",inner_w),inner_w,self.theme.muted)
            details=3 if self.modal == "model" and layout.details else 0
            available=max(1,layout.bottom-details-layout.modal_list);self.page_lines=available
            rows=self.visible_rows();selected=next((i for i,row in enumerate(rows) if row[0] == self.index),0);start=max(0,selected-available+1)
            for offset,(index,label,_) in enumerate(rows[start:start+available]):
                disabled=self.unavailable(self.command_rows()[index].action) if self.modal == "commands" else self.unavailable(self.manage_rows()[index][0]) if self.modal == "manage" else ""
                is_sel=index == self.index
                attr=self.theme.selected if is_sel else self.theme.muted if disabled else self.theme.text
                marker="▌ " if is_sel else "  "
                self.row(layout.modal_list+offset,inner_x,inner_w,marker+label,attr)
                self.hits.append((layout.modal_list+offset,inner_x,inner_w,"option",index))
            if not rows:
                empty="中央内容库尚无已导入版本 · Esc 返回" if self.modal in {"versions","runtime_versions"} and not self.version_rows else "没有匹配项 · Esc 返回，或重新输入搜索"
                self.put(layout.modal_list,inner_x,empty,inner_w,self.theme.warning)
            if details and rows:
                model=next((row for row in self.catalog().models if row.id == self.options()[self.index][1]),None)
                if model:
                    self.put(layout.bottom-3,inner_x,"─"*inner_w,inner_w,self.theme.muted)
                    self.put(layout.bottom-2,inner_x,ellipsize("ID  "+model.id,inner_w),inner_w)
                    self.put(layout.bottom-1,inner_x,ellipsize("来源  "+model.source,inner_w),inner_w,self.theme.muted)
            if len(rows)>available:
                draw_scrollbar(self.put,layout.modal_list,x+width-2,available,len(rows),start,available,self.theme.border)
        elif self.modal == "add":
            self.put(layout.modal_body,inner_x,"项目目录 · 输入或拖入现有根目录",inner_w,self.theme.muted)
            self.draw_input(layout.modal_body+1,inner_x,inner_w,self.editor)
            self.put(layout.modal_body+2,inner_x,"默认仅登记；先预览，确认后才写入。",inner_w,self.theme.muted)
            if self.toast_kind == "error" and layout.modal_body+3<layout.bottom:
                self.put(layout.modal_body+3,inner_x,ellipsize("! "+self.toast,inner_w),inner_w,self.theme.error)
        else:
            lines=wrapped(self.text,inner_w);available=max(1,layout.bottom-layout.modal_body);self.page_lines=available
            self.scroll=min(self.scroll,max(0,len(lines)-available))
            for offset,line in enumerate(lines[self.scroll:self.scroll+available]):
                attr=self.theme.error if self.modal == "error" else self.theme.warning if self.modal == "quit" else self.theme.text
                self.put(layout.modal_body+offset,inner_x,line,inner_w,attr)
            if len(lines)>available:
                draw_scrollbar(self.put,layout.modal_body,x+width-2,available,len(lines),self.scroll,available,self.theme.border)

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
        draw_frame(self.put,layout,self.theme.title)
        # 空草稿只能说明没有待保存编辑，不能代替服务验收或宣称配置已经同步。
        count=f"● {len(self.drafts)} 项未保存" if self.drafts else "无待保存草稿"
        self.put(layout.title,layout.left,"◈ awf-cli │ 角色模型",max(1,layout.span-cell_width(count)-2),self.theme.title)
        self.put(layout.title,layout.right-cell_width(count)+1,count,cell_width(count),self.theme.warning if self.drafts else self.theme.muted)
        x=layout.left
        for i,label in enumerate(HOST_LABELS):
            active=i == self.host_index
            text=f" [{i+1} {label}] " if active else f"  {i+1} {label}  "
            attr=self.theme.tab_active if active else self.theme.tab_inactive
            self.put(layout.tabs,x,text,cell_width(text),attr)
            if not self.modal:self.hits.append((layout.tabs,x,cell_width(text),"host",i))
            x+=cell_width(text)+1
        draw_divider(self.put,layout,layout.header_divider,self.theme.border)
        # 管理条横跨两栏；其下独立轻线先分区，再从栏头开始绘制侧栏竖线。
        draw_divider(self.put,layout,layout.bottom,self.theme.border,
                     junction=layout.sidebar if not self.modal and not layout.details else 0,end=True)
        if not self.modal:
            if self.global_scope:
                self.put(layout.workflow,layout.left,"全局默认 · 工作流子 Agent",layout.span,self.theme.title)
                self.put(layout.workflow_actions if layout.compact else layout.workflow,layout.left if layout.compact else max(layout.left,layout.right-29),"按平台 / 角色设置默认",layout.span if layout.compact else 30,self.theme.muted)
            else:
                state=project_state(self.project_rows.get(str(self.project))) if self.project else "未选择项目"
                actions="[o]启用工作流  [p]停用工作流"
                actions_x=layout.left if layout.compact else layout.right-cell_width(actions)+1
                state_width=layout.span if layout.compact else min(22,actions_x-layout.left-2)
                self.put(layout.workflow,layout.left,ellipsize("项目工作流 "+state,state_width),state_width,self.theme.title)
                if not layout.compact:
                    context_x=layout.left+state_width+1
                    self.put(layout.workflow,context_x,ellipsize(self.scope_label,max(0,actions_x-context_x-2)),max(0,actions_x-context_x-2),self.theme.muted)
                self.put(layout.workflow_actions,actions_x,actions,cell_width(actions),self.theme.focus)
            draw_divider(self.put,layout,layout.workflow_divider,self.theme.border,
                         junction=layout.sidebar if layout.sidebar else 0)
        if self.modal:self.draw_modal(layout)
        else:
            if layout.sidebar or self.pane == "projects":self.draw_projects(layout)
            if layout.sidebar:
                for row in range(layout.pane_title,layout.list_bottom):self.put(row,layout.sidebar,"│",1,self.theme.border)
                if layout.pane_divider is not None:
                    draw_divider(self.put,layout,layout.pane_divider,self.theme.border)
                    self.put(layout.pane_divider,layout.sidebar,"┼",1,self.theme.border)
            if layout.sidebar or self.pane == "roles":self.draw_roles(layout)
            if layout.details:
                draw_divider(self.put,layout,layout.list_bottom,self.theme.border,junction=layout.sidebar,end=True)
                self.put(layout.bottom-2,layout.left,ellipsize("全局默认 · 仅工作流子 Agent" if self.global_scope else str(self.project or "选择项目，或按 a 登记项目"),layout.span,tail=True),layout.span,self.theme.muted)
                if self.role:
                    try:
                        value=self.current(self.role);names={"project":"项目","global":"全局","host":"宿主"};sources=value.get("sources",{});detail=f'{self.role} · 模型来源 {names.get(sources.get("model"),"未知")} / 推理来源 {names.get(sources.get("effort"),"未知")} · v 详情'
                    except (OSError,ValueError):detail="角色配置异常，请检查本地文件"
                    self.put(layout.bottom-1,layout.left,ellipsize(detail,layout.span),layout.span)
        status=self.toast;kind=self.toast_kind
        if self.future:
            elapsed=max(0,int(time.monotonic()-self.session.job.started));spinner="|/-\\"[(elapsed*3)%4]
            status=f"{spinner} {self.session.job.name} · {elapsed}s · "+("已请求取消，等待真实结果与必要恢复" if self.cancel_job.is_set() else "执行中");kind="warning"
        prefix={"error":"✖ ","warning":"▲ ","success":"✔ ","info":"● "}.get(kind,"· ")
        self.put(layout.status,layout.left,ellipsize(prefix+status,layout.span),layout.span,getattr(self.theme,kind,self.theme.text))
        draw_divider(self.put,layout,layout.status_divider,self.theme.border)
        for offset,line in enumerate(self.footer_lines(layout.span)):self.put(layout.hints+offset,layout.left,line,layout.span,self.theme.focus)
        self.finish_draw()

    def loop(self,screen):
        self.screen=screen;screen.keypad(True);screen.timeout(100);self.theme=Theme.create()
        try:curses.set_escdelay(25)
        except (AttributeError,curses.error):pass
        try:curses.mousemask(curses.BUTTON1_CLICKED)
        except curses.error:pass
        with ThreadPoolExecutor(max_workers=1) as self.executor:
            # 验证核心摘要可能耗时，首次状态也放到既有作业线程；绘制帧只消费缓存。
            self.refresh_project_status()
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
                        if kind == "role":
                            self.role_column="effort" if x>=col+width-10 else "model"
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


def run(state: Path,scan: Path,project: Path | None=None,*,native_context=None) -> int:
    locale.setlocale(locale.LC_ALL,"")
    return curses.wrapper(App(state,scan,project,native_context=native_context).loop)
