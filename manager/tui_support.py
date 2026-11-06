"""curses 的单元格、输入与样式辅助，不包含项目或事务状态。"""

from __future__ import annotations

import curses
from dataclasses import dataclass
import unicodedata

from .catalog import clean


PROJECT_ACTION_LABELS = {
    "add": "登记项目", "del": "停用并解除登记", "enable": "启用工作流",
    "disable": "停用工作流", "use": "选择固定版本", "rollback": "回退前次版本",
    "repair": "修复受管资源",
}


def binding_id(binding) -> str:
    """展示完整内容 ID；缺失值明确为空，不能用来源标签或 latest 代替 pin。"""
    return str(binding["content_id"]) if binding else "无"


def project_state(row: dict | None) -> str:
    """只投影服务已经确认的状态；缓存缺失不表示未管理或已停用。"""
    if row is None:return "待刷新"
    if row.get("conflicts"):return "冲突"
    return {"enabled": "已启用", "disabled": "已停用", "unmanaged": "未管理",
            "prepared": "待恢复", "conflict": "冲突"}.get(row.get("state"), "未知状态")


def project_badge(row: dict | None) -> str:
    state = project_state(row)
    identifier = binding_id(row.get("runtime_binding")) if row else "无"
    return state + (" · " + identifier[:8] if identifier != "无" else "")


def status_text(row: dict, host_labels: dict[str, str]) -> str:
    """完整详情允许滚动，保留长路径、完整 ID 和三宿主的实际受管范围。"""
    lines = ["项目  " + str(row["project"]), "状态  " + project_state(row),
             "登记  " + ("未读取，请刷新" if row.get("registered") is None else "已登记" if row["registered"] else "未登记"),
             "当前内容 ID  " + binding_id(row.get("runtime_binding")),
             "前次内容 ID  " + binding_id(row.get("previous_binding")), "", "三宿主状态："]
    managed = set(row.get("hosts", []))
    for host, label in host_labels.items():
        # 服务只返回项目级一致性与受管宿主集合，不能杜撰逐宿主模型加载或探测结果。
        state = project_state(row) if host in managed else "未管理"
        lines.append(f"  {label}  {state}" + ("（在受管范围内）" if host in managed else ""))
    lines += ["", "受管路径：", *["  " + str(path) for path in row.get("managed_paths", [])]]
    if not row.get("managed_paths"):lines.append("  无受管路径")
    if row.get("pending_transaction"):lines += ["", "待结算事务  " + str(row["pending_transaction"])]
    if row.get("conflicts"):
        lines += ["", "冲突：", *[f"  {item['path']} · {item['reason']}" for item in row["conflicts"]]]
        lines.append("先检查上述路径；存在未完成事务时预览“修复受管资源”，手工修改应先核对并保留。")
    return "\n".join(lines)


def project_plan_text(summary: dict) -> str:
    """只渲染公共计划，不重新计算写集、业务状态或确认权限。"""
    native = summary.get("runtime") or {}
    before = summary["status_before"]
    current = native.get("runtime_binding") or before.get("runtime_binding")
    lines = ["动作  " + PROJECT_ACTION_LABELS[summary["action"]], "项目  " + summary["project"],
             "状态目录  " + summary["state_dir"],
             "登记  " + ("已登记" if summary["registered_before"] else "未登记") + " → " + ("已登记" if summary["registered_after"] else "未登记"),
             "当前状态  " + project_state(before), "目标内容 ID  " + binding_id(current),
             "前次内容 ID  " + binding_id(native.get("previous_binding") or before.get("previous_binding"))]
    if native:
        lines.append("工作流  " + ("已启用" if native["enabled_before"] else "未启用") + " → " + ("启用" if native["enabled_after"] else "停用"))
        lines.append("受管宿主  " + " / ".join(native.get("hosts", [])))
    if summary["action"] == "add" and not native:lines.append("仅登记项目；本次不会启用工作流或导入中央核心。")
    if summary["action"] in {"disable", "del"}:
        lines.append("停用新工作流入口；保留项目文件、配置、资料与历史，已运行任务不被终止。")
    if summary["action"] == "del":lines.append("停用成功后解除登记；项目将从本列表隐藏，不删除项目目录。")
    changes = summary["changes"]
    lines += ["", f"受管变更  {len(changes)} 项："]
    lines += [f"  {item['operation']}  {item['path']} · {item['purpose']}" for item in changes] or ["  无受管文件变更"]
    if native.get("warnings"):lines += ["", "提示：", *native["warnings"]]
    conflicts = summary["conflicts"]
    if conflicts:
        lines += ["", "不能应用；冲突：", *[f"  {item['path']} · {item['reason']}" for item in conflicts],
                  "请核对冲突路径；未完成事务可返回预览修复，其他手工修改需保留并核对后重试。"]
    else:lines += ["", "Enter 确认应用上述计划；Esc 返回，不写入项目或状态目录。"]
    return "\n".join(lines)


def project_result_text(result: dict, host_labels: dict[str, str]) -> str:
    lines = ["操作已结算。"]
    if result.get("cancel_requested"):
        lines.append("已收到取消请求；事务已开始并完成结算，以下为真实结果。")
    return "\n".join([*lines, "", status_text(result, host_labels)])


def operation_error(exc: Exception) -> str:
    """保留服务的安全冲突诊断和恢复提示，不把错误页误报为取消或完成。"""
    lines = [str(exc)]
    conflicts = getattr(exc, "conflicts", ())
    lines += [f"{item['path']} · {item['reason']}" for item in conflicts]
    lines.append("操作未完成。输入和模型草稿保留；返回后可刷新状态，核对冲突或预览修复。")
    return "\n".join(lines)


def cell_width(text: str) -> int:
    return sum(0 if unicodedata.combining(char) else 2 if unicodedata.east_asian_width(char) in {"W","F"} else 1 for char in text)


def clip(text: str, width: int) -> str:
    """按终端单元格截断，保留附着于末尾字符的组合标记。"""
    result="";used=0
    for char in clean(text,8000):
        size=cell_width(char)
        if used+size>width:break
        result+=char;used+=size
    return result


def ellipsize(text: str, width: int, *, tail=False) -> str:
    text=clean(text,8000)
    if width<=0:return ""
    if cell_width(text)<=width:return text
    if not tail:return clip(text,width-1)+"…"
    start=len(text);used=0
    while start:
        size=cell_width(text[start-1])
        if used+size>width-1:break
        start-=1;used+=size
    while start<len(text) and unicodedata.combining(text[start]):start+=1
    return "…"+text[start:]


def padded(text: str, width: int) -> str:
    text=ellipsize(text,width)
    return text+" "*max(0,width-cell_width(text))


def wrapped(text: str, width: int) -> list[str]:
    lines=[]
    for line in text.splitlines():
        remaining=clean(line,8000)
        if not remaining:lines.append("")
        while remaining:
            part=clip(remaining,width)
            if not part:break
            lines.append(part);remaining=remaining[len(part):]
    return lines


@dataclass
class TextInput:
    text: str = ""
    cursor: int = 0

    def previous(self):
        index=max(0,self.cursor-1)
        while index and unicodedata.combining(self.text[index]):index-=1
        return index

    def following(self):
        index=min(len(self.text),self.cursor+1)
        while index<len(self.text) and unicodedata.combining(self.text[index]):index+=1
        return index

    def edit(self,key):
        self.cursor=max(0,min(self.cursor,len(self.text)))
        if key == "left":self.cursor=self.previous()
        elif key == "right":self.cursor=self.following()
        elif key == "home":self.cursor=0
        elif key == "end":self.cursor=len(self.text)
        elif key == "backspace" and self.cursor:
            previous=self.previous();self.text=self.text[:previous]+self.text[self.cursor:];self.cursor=previous
        elif key == "delete" and self.cursor<len(self.text):self.text=self.text[:self.cursor]+self.text[self.following():]
        elif key == "\x15":self.text="";self.cursor=0
        elif isinstance(key,str) and len(key) == 1 and key.isprintable() and len(self.text)<8000:
            self.text=self.text[:self.cursor]+key+self.text[self.cursor:];self.cursor+=1

    def viewport(self,width):
        if width<=0:return "",0
        self.cursor=max(0,min(self.cursor,len(self.text)))
        start=0;used=cell_width(self.text[:self.cursor])
        # 给光标保留一格；长路径的尾端和行首都能通过光标移动到达。
        while start<self.cursor and used>=width:
            used-=cell_width(self.text[start]);start+=1
        while start<len(self.text) and unicodedata.combining(self.text[start]):start+=1
        return clip(self.text[start:],width),cell_width(self.text[start:self.cursor])


@dataclass(frozen=True)
class Layout:
    height: int
    width: int

    # 外框独占四周一格，文字再内缩一格；所有视图与命中区共用这些坐标，
    # 不能在旧内容上覆盖边框，否则中文宽字符、输入光标和底部提示会相互挤占。
    @property
    def left(self):return 2
    @property
    def right(self):return self.width-3
    @property
    def span(self):return self.width-4
    @property
    def title(self):return 1
    @property
    def tabs(self):return 2
    @property
    def header_divider(self):return 3
    @property
    def workflow(self):return 4
    @property
    def pane_title(self):return 5
    @property
    def pane_subtitle(self):return 6
    @property
    def project_start(self):return 7
    @property
    def role_header(self):return 7
    @property
    def role_start(self):return 8
    @property
    def sidebar(self):return min(28,max(24,self.width//5))+2 if self.width>=110 else 24 if self.width>=80 else 0
    @property
    def bottom(self):return self.height-6
    @property
    def details(self):return 3 if self.height>=22 else 0
    @property
    def list_bottom(self):return self.bottom-self.details
    @property
    def status(self):return self.height-5
    @property
    def status_divider(self):return self.height-4
    @property
    def hints(self):return self.height-3
    @property
    def modal_top(self):return self.workflow
    @property
    def modal_x(self):return max(self.left,(self.width-94)//2)
    @property
    def modal_width(self):return self.width-2*self.modal_x
    @property
    def modal_inner_x(self):return self.modal_x+2
    @property
    def modal_inner_width(self):return self.modal_width-4
    @property
    def modal_body(self):return self.modal_top+3
    @property
    def modal_list(self):return self.modal_top+4


def draw_frame(put, layout: Layout, border_attr: int):
    """粗外框只占预留字符格；细分隔通过轻横重竖接头连接外框。"""
    put(0,0,"┏"+"━"*(layout.width-2)+"┓",layout.width,border_attr)
    for row in range(1,layout.height-1):
        put(row,0,"┃",1,border_attr)
        put(row,layout.width-1,"┃",1,border_attr)
    put(layout.height-1,0,"┗"+"━"*(layout.width-2)+"┛",layout.width,border_attr)


def draw_divider(put, layout: Layout, y: int, attr: int, *, junction: int = 0, end: bool = False):
    """只连接真实存在的面板分隔；状态和按键区使用同一条轻分隔。"""
    put(y,0,"┠"+"─"*(layout.width-2)+"┨",layout.width,attr)
    if junction:put(y,junction,"┴" if end else "┬",1,attr)


@dataclass(frozen=True)
class Theme:
    text: int = 0
    muted: int = curses.A_DIM
    title: int = curses.A_BOLD
    focus: int = curses.A_BOLD
    selected: int = curses.A_REVERSE | curses.A_BOLD
    inactive: int = curses.A_BOLD
    warning: int = curses.A_BOLD
    error: int = curses.A_BOLD
    success: int = curses.A_BOLD
    border: int = curses.A_DIM
    tab_active: int = curses.A_REVERSE | curses.A_BOLD
    tab_inactive: int = curses.A_DIM
    badge: int = curses.A_BOLD
    indicator: int = curses.A_BOLD

    @classmethod
    def create(cls):
        try:
            if not curses.has_colors():return cls()
            curses.start_color();curses.use_default_colors()
            for index,color in enumerate((curses.COLOR_CYAN,curses.COLOR_YELLOW,curses.COLOR_RED,curses.COLOR_GREEN,curses.COLOR_MAGENTA,curses.COLOR_BLUE),1):
                curses.init_pair(index,color,-1)
            return cls(focus=curses.color_pair(1)|curses.A_BOLD,
                       selected=curses.color_pair(1)|curses.A_REVERSE|curses.A_BOLD,
                       warning=curses.color_pair(2)|curses.A_BOLD,
                       error=curses.color_pair(3)|curses.A_BOLD,
                       success=curses.color_pair(4)|curses.A_BOLD,
                       border=curses.A_DIM,
                       tab_active=curses.color_pair(1)|curses.A_REVERSE|curses.A_BOLD,
                       tab_inactive=curses.A_DIM,
                       badge=curses.color_pair(2)|curses.A_BOLD,
                       indicator=curses.color_pair(1)|curses.A_BOLD)
        except curses.error:
            # 不强制黑底，浅色终端及不支持默认背景的终端仍可使用单色界面。
            return cls()


def draw_box(put, y: int, x: int, h: int, w: int, *, title: str = "", count: str = "",
             border_attr: int = 0, title_attr: int = 0, count_attr: int = 0, round_corners: bool = True):
    if h < 2 or w < 2: return
    tl, tr, bl, br = ("╭", "╮", "╰", "╯") if round_corners else ("┌", "┐", "└", "┘")
    avail = max(0, w - 2)
    t_clean = f" {title.strip()} " if title.strip() else ""
    c_clean = f" {count.strip()} " if count.strip() else ""
    t_w = cell_width(t_clean)
    c_w = cell_width(c_clean)
    put(y, x, tl, 1, border_attr)
    if t_w + c_w <= avail:
        mid_bar = avail - t_w - c_w
        curr_x = x + 1
        if t_clean:
            put(y, curr_x, t_clean, t_w, title_attr or border_attr)
            curr_x += t_w
        if mid_bar > 0:
            put(y, curr_x, "─" * mid_bar, mid_bar, border_attr)
            curr_x += mid_bar
        if c_clean:
            put(y, curr_x, c_clean, c_w, count_attr or border_attr)
    else:
        disp_title = ellipsize(t_clean or title, avail)
        disp_w = cell_width(disp_title)
        put(y, x + 1, disp_title, disp_w, title_attr or border_attr)
        rem = max(0, avail - disp_w)
        if rem > 0:
            put(y, x + 1 + disp_w, "─" * rem, rem, border_attr)
    put(y, x + w - 1, tr, 1, border_attr)
    for row in range(y + 1, y + h - 1):
        put(row, x, "│", 1, border_attr)
        put(row, x + w - 1, "│", 1, border_attr)
    put(y + h - 1, x, bl + ("─" * avail) + br, w, border_attr)


def draw_scrollbar(put, y: int, x: int, h: int, total: int, current: int, page_size: int, attr: int = 0):
    if h <= 2 or total <= page_size or total <= 0: return
    thumb_size = max(1, int(h * (page_size / total)))
    max_scroll = max(1, total - page_size)
    thumb_pos = min(h - thumb_size, max(0, int((h - thumb_size) * (current / max_scroll))))
    for offset in range(h):
        char = "█" if thumb_pos <= offset < thumb_pos + thumb_size else "░"
        put(y + offset, x, char, 1, attr)

