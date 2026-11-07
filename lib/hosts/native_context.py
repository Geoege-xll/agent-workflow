"""一次解析、不可变的宿主路径；状态目录从不暗中授权访问用户 HOME。"""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
from typing import Mapping


def _absolute(raw: str | Path) -> Path:
    path = Path(raw).expanduser().absolute()
    if ".." in path.parts:
        raise ValueError("宿主路径不能包含上级跳转")
    return path


@dataclass(frozen=True)
class HostPaths:
    """原生配置根快照；环境变量只在入口解析，后续服务不得重新读取环境。"""

    home: Path
    codex: Path
    claude: Path
    antigravity: Path

    def __post_init__(self):
        for name in ("home", "codex", "claude", "antigravity"):
            object.__setattr__(self, name, _absolute(getattr(self, name)))
        if len({self.codex, self.claude, self.antigravity}) != 3:
            raise ValueError("三个宿主配置根必须彼此独立")

    @classmethod
    def for_home(cls, home: Path, *, environment: Mapping[str, str] | None = None) -> HostPaths:
        # environment={} 是测试及显式 HOME 的隔离合同；不能用 truthy fallback
        # 偷偷吸收实际进程中的 CODEX_HOME / CLAUDE_CONFIG_DIR。
        env = {} if environment is None else dict(environment)
        home = _absolute(home)
        return cls(home, _absolute(env["CODEX_HOME"]) if env.get("CODEX_HOME") else home / ".codex",
                   _absolute(env["CLAUDE_CONFIG_DIR"]) if env.get("CLAUDE_CONFIG_DIR") else home / ".claude",
                   home / ".gemini/config")

    def root(self, host: str) -> Path:
        if host not in {"codex", "claude", "antigravity"}:
            raise ValueError("未知宿主")
        return getattr(self, host)


@dataclass(frozen=True)
class NativeContext:
    """全局原生操作所需的显式身份；不包含项目启用或版本绑定授权。"""

    state: Path
    host_paths: HostPaths

    def __post_init__(self):
        object.__setattr__(self, "state", _absolute(self.state))
        if not isinstance(self.host_paths, HostPaths):
            raise ValueError("原生上下文必须提供 HostPaths")

    @classmethod
    def for_state(cls, state: Path | None = None, *, host_paths: HostPaths | None = None) -> NativeContext:
        from lib import runtime_store
        # 显式 --state-dir 常用于隔离、恢复或另一套安装；它仅授权该 state。
        # 缺少宿主根时直接拒绝，不能将 custom state 的全局写入落到真实 HOME。
        if host_paths is None and state is not None:
            raise ValueError("显式状态目录的原生操作必须同时提供 HostPaths")
        return cls(runtime_store.state_root(state), host_paths or HostPaths.for_home(Path.home(), environment=dict(os.environ)))
