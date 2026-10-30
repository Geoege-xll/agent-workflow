"""curses 的单元格、输入与样式辅助，不包含项目或事务状态。"""

from __future__ import annotations

import curses
from dataclasses import dataclass
import unicodedata

from .catalog import clean


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

    @property
    def sidebar(self):return min(28,max(24,self.width//5)) if self.width>=110 else 22 if self.width>=80 else 0
    @property
    def bottom(self):return self.height-4
    @property
    def details(self):return 3 if self.height>=22 else 0
    @property
    def status(self):return self.height-3
    @property
    def hints(self):return self.height-2


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

    @classmethod
    def create(cls):
        try:
            if not curses.has_colors():return cls()
            curses.start_color();curses.use_default_colors()
            for index,color in enumerate((curses.COLOR_CYAN,curses.COLOR_YELLOW,curses.COLOR_RED,curses.COLOR_GREEN),1):
                curses.init_pair(index,color,-1)
            return cls(focus=curses.color_pair(1)|curses.A_BOLD,
                       selected=curses.color_pair(1)|curses.A_REVERSE|curses.A_BOLD,
                       warning=curses.color_pair(2)|curses.A_BOLD,
                       error=curses.color_pair(3)|curses.A_BOLD,
                       success=curses.color_pair(4)|curses.A_BOLD)
        except curses.error:
            # 不强制黑底，浅色终端及不支持默认背景的终端仍可使用单色界面。
            return cls()
