"""工作台专用的会话生命周期：草稿授权、只读投影和一次后台作业。

本模块不读取配置、不调用业务服务，也不决定布局或键位。App 负责在受控入口
取回服务上下文；这里保证显示刷新不会续期已有草稿，后台结果只结算一次。
"""

from __future__ import annotations

from collections.abc import MutableMapping
from concurrent.futures import Future
from copy import deepcopy
from dataclasses import dataclass, field
from threading import Event
import time
from typing import Callable


ScopeKey = tuple[str, str]
DraftKey = tuple[str, str, str]


@dataclass
class Draft:
    """同一范围/宿主/角色的改动、原始前像和来源授权共存共亡。"""

    choices: dict = field(default_factory=dict)
    expected: dict | None = None
    following: dict = field(default_factory=dict)
    stamp: str | None = None


class _DraftField(MutableMapping):
    """保留现有 App 诊断/测试的字典入口，底层仍只有一份 Draft。

    生产路由统一调用 Session 的 begin/stage/discard；这三个窄视图用于已有
    直接消费者读取或布置状态，避免为内部重构改变它们的字段含义。
    """

    def __init__(self, entries: dict[DraftKey, Draft], name: str):
        self.entries, self.name = entries, name

    def __getitem__(self, key):
        value = getattr(self.entries[key], self.name)
        if value is None or self.name == "choices" and not value:
            raise KeyError(key)
        return value

    def __setitem__(self, key, value):
        setattr(self.entries.setdefault(key, Draft()), self.name, deepcopy(value))

    def __delitem__(self, key):
        self[key]
        entry = self.entries[key]
        setattr(entry, self.name, {} if self.name == "choices" else None)
        if not entry.choices and entry.expected is None and entry.stamp is None:
            self.entries.pop(key)

    def __iter__(self):
        return (key for key in list(self.entries)
                if (value := getattr(self.entries[key], self.name)) is not None
                and (self.name != "choices" or value))

    def __len__(self):
        return sum(1 for _ in self)


@dataclass
class Display:
    """P1 同批上下文的独立显示副本；绘制只能消费此处已取回的数据。"""

    values: dict
    following: dict


@dataclass(frozen=True)
class Impact:
    """一次作业影响的偏好投影及项目状态范围；None 明确表示该维度全部。"""

    scopes: frozenset[str] | None
    host: str | None = None
    projects: frozenset[str] | None = frozenset()

    def matches(self, key: ScopeKey) -> bool:
        return (self.scopes is None or key[0] in self.scopes) and (self.host is None or key[1] == self.host)


@dataclass
class Job:
    """持有作业的完整入口与结算事实，Future 完成不等于界面回调已完成。"""

    impact: Impact = field(default_factory=lambda: Impact(frozenset()))
    return_view: dict | None = None
    return_frames: list = field(default_factory=list)
    future: Future | None = None
    after: Callable | None = None
    on_result: Callable | None = None
    result_text: Callable | None = None
    refresh: Callable | None = None
    show_result: bool = True
    writes: bool = False
    draft_keys: tuple[DraftKey, ...] = ()
    name: str = "管理操作"
    cancellable: bool = False
    cancel: Event = field(default_factory=Event)
    started: float = 0
    phase: str = "idle"
    operation_completed: bool = False
    result: object = None
    refreshed: object = None

    def execute(self, operation):
        # 先留下业务服务实际返回的事实，再读取展示资料。后者即使抛错，也不能
        # 把已经完成的登记/保存误报成写入失败，或让用户重提同一个确认计划。
        self.phase = "operation"
        self.result = operation()
        self.operation_completed = True
        if self.refresh:
            self.phase = "refresh"
            self.refreshed = self.refresh(self.result)
        self.phase = "callback"
        return self.result


class Session:
    """App 唯一会话状态所有者；授权状态从不由显示缓存反向更新。"""

    def __init__(self):
        self.entries: dict[DraftKey, Draft] = {}
        self.drafts = _DraftField(self.entries, "choices")
        self.expected = _DraftField(self.entries, "expected")
        self.source_stamps = _DraftField(self.entries, "stamp")
        self.displays: dict[ScopeKey, Display] = {}
        self.display_errors: dict[ScopeKey, str] = {}
        self.catalogs = {}
        self.project_rows = {}
        self.status_error = ""
        self.job = Job()

    def accept_context(self, key: ScopeKey, context):
        self.displays[key] = Display(context.role_values, context.following_values)
        self.display_errors.pop(key, None)
        if context.catalogs is not None:
            self.catalogs[key] = context.catalogs

    def fail_display(self, key: ScopeKey, diagnostic: str):
        self.displays.pop(key, None)
        self.display_errors[key] = diagnostic

    def installed_roles(self, key: ScopeKey) -> list[str]:
        display = self.displays.get(key)
        return list(display.values) if display else []

    def base_value(self, key: DraftKey) -> dict:
        display = self.displays.get(key[:2])
        entry = self.entries.get(key)
        value = display.values.get(key[2]) if display else None
        # 外部移除角色或来源损坏时，旧草稿仍可查看/丢弃；旧前像仅用于该草稿
        # 的可见性与并发守卫，不伪装成一次成功刷新得到的新配置。
        return deepcopy(value or (entry.expected if entry else None) or
                        {"model": "配置异常", "effort": "?", "sources": {}})

    def following_value(self, key: DraftKey) -> dict:
        display = self.displays.get(key[:2])
        entry = self.entries.get(key)
        return deepcopy((display.following.get(key[2]) if display else None) or
                        (entry.following if entry else None) or
                        {"model": "inherit", "effort": "inherit", "sources": {}})

    def current(self, key: DraftKey) -> dict:
        value = self.base_value(key)
        value.setdefault("sources", {})
        entry = self.entries.get(key)
        for name, choice in (entry.choices if entry else {}).items():
            if choice is None:
                following = self.following_value(key)
                value[name] = following[name]
                value["sources"][name] = following.get("sources", {}).get(name, "host")
            else:
                value[name] = choice
                value["sources"][name] = "host" if choice == "inherit" else "global" if key[0] == "<global>" else "project"
        return value

    def begin(self, key: DraftKey) -> Draft:
        entry = self.entries.setdefault(key, Draft())
        if entry.expected is None:
            entry.expected = self.base_value(key)
            entry.following = self.following_value(key)
        return entry

    def stage(self, key: DraftKey, selected: dict, stamp: str):
        entry = self.begin(key)
        baseline = entry.expected
        overrides = baseline.get("overrides", {})
        for name, choice in selected.items():
            unchanged = choice == baseline[name] if key[0] == "<global>" else (
                choice is None and name not in overrides or name in overrides and choice == overrides[name])
            if unchanged:
                entry.choices.pop(name, None)
            else:
                entry.choices[name] = choice
        if entry.choices:
            # 只有用户重新确认选择才更新来源 stamp；刷新显示/重开菜单本身不续期。
            entry.stamp = stamp
        else:
            self.discard(key)

    def reset(self, key: DraftKey, name: str, stamp: str):
        entry = self.begin(key)
        if name in entry.expected.get("overrides", {}):
            entry.choices[name] = None
        else:
            entry.choices.pop(name, None)
        if entry.choices:
            entry.stamp = stamp
        else:
            self.discard(key)

    def discard(self, key: DraftKey):
        self.entries.pop(key, None)

    def cancel_edit(self, key: DraftKey):
        if key in self.entries and not self.entries[key].choices:
            self.discard(key)

    def pending(self, key: ScopeKey) -> dict:
        return {role: entry.choices for (scope, host, role), entry in self.entries.items()
                if (scope, host) == key and entry.choices}

    def invalidate(self, impact: Impact, diagnostic: str = ""):
        # 显示与授权分别拥有生命周期：全局失败可能已触及多个项目，必须按作业
        # 原作用范围失效所有投影；任何路径都不修改 entries 内的前像或来源授权。
        keys = set(self.displays) | set(self.catalogs) | set(self.display_errors)
        for key in keys:
            if impact.matches(key):
                self.displays.pop(key, None)
                self.catalogs.pop(key, None)
                self.display_errors.pop(key, None)
                if diagnostic:
                    self.display_errors[key] = diagnostic
        for project in list(self.project_rows):
            if impact.projects is None or project in impact.projects:
                self.project_rows.pop(project)
        if diagnostic and (impact.projects is None or impact.projects):
            self.status_error = diagnostic

    def prepare_job(self, view: dict, frames: list, *, preserve_view: bool, **options) -> Job:
        # 消费过的确认页永远不能成为结果/错误的返回入口；只读预读也不能把
        # 夹在栈里的旧确认页带回来。导航帧由 App 提供，这里只管理其生命周期。
        confirmations = {"project_plan", "preview", "restore", "quit"}
        safe_frames = [dict(frame) for frame in frames if frame["modal"] not in confirmations]
        candidates = [view, *reversed(safe_frames)]
        if preserve_view and view["modal"] not in confirmations:
            return_view, return_frames = dict(view), safe_frames
        else:
            return_view = next((dict(frame) for frame in candidates if frame["modal"] in {"manage", "add_mode"}), None)
            return_frames = []
            if return_view is None:
                return_view = next((dict(frame) for frame in candidates if frame["modal"] is None), dict(view))
                return_view.update(modal=None, scroll=0, text="")
            elif return_view["modal"] == "add_mode":
                return_frames = next((safe_frames[:index] for index, frame in enumerate(safe_frames)
                                      if frame["modal"] == "add_mode"), safe_frames)
        self.job = Job(return_view=return_view, return_frames=return_frames, started=time.monotonic(), **options)
        return self.job

    def settle_job(self, job: Job, diagnostic: str = ""):
        if job.writes or diagnostic:
            self.invalidate(job.impact, diagnostic)
        if job.writes and job.operation_completed:
            for key in job.draft_keys:
                self.discard(key)

    def finish_job(self, job: Job):
        # 即使结果回调抛异常，也释放 Future、闭包及入口帧；业务结果/阶段保留作
        # 当前作业的诊断事实。忙态直到这一最终出口才结束，取消不会提前解锁 UI。
        job.future = None
        job.after = job.on_result = job.refresh = job.result_text = None
        job.return_view = None
        job.return_frames = []
        job.cancellable = False
