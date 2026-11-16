"""仅在当前服务进程内保存浏览器派生凭据，不接触 CLI 入口令牌或持久化配置。"""

from __future__ import annotations

import re
import secrets
import threading
import time


SESSION_TTL_SECONDS = 30 * 60
MAX_BROWSER_SESSIONS = 64


class BrowserSessionLimitError(Exception):
    """活跃会话达到上限时明确拒绝签发，不能挤掉仍在使用的凭据。"""


class BrowserSessions:
    """统一拥有派生凭据的签发、验证和销毁；每个 ConsoleServer 独占一个实例。"""

    def __init__(self):
        self._lock = threading.Lock()
        self._deadlines: dict[str, float] = {}

    def _expire(self, now: float):
        # 调用者持锁；凭据数量有界，完整回收最多遍历 64 项，不启动后台定时任务。
        for token, deadline in list(self._deadlines.items()):
            if now >= deadline:
                del self._deadlines[token]

    def issue(self) -> tuple[str, int]:
        """返回随机凭据及 Unix 毫秒截止时间；容量检查和登记在同一把锁内完成。"""
        with self._lock:
            now = time.monotonic()
            self._expire(now)
            if len(self._deadlines) >= MAX_BROWSER_SESSIONS:
                raise BrowserSessionLimitError()
            token = secrets.token_urlsafe(32)
            while token in self._deadlines:
                token = secrets.token_urlsafe(32)
            # monotonic 是服务端唯一过期权威，墙钟只供页面提前提示；系统校时不会
            # 延长或缩短凭据权限。每次验证也不会滑动截止时间或自动续期。
            self._deadlines[token] = now + SESSION_TTL_SECONDS
            return token, int((time.time() + SESSION_TTL_SECONDS) * 1000)

    def valid(self, token: str) -> bool:
        """只接受当前实例签发且未过期的完整凭据，未知或格式错误一律返回 False。"""
        if not isinstance(token, str) or re.fullmatch(r"[A-Za-z0-9_-]{43}", token) is None:
            return False
        with self._lock:
            self._expire(time.monotonic())
            return token in self._deadlines

    def clear(self):
        """服务结束后丢弃全部派生凭据；无磁盘副本、cookie 或后台资源需要清理。"""
        with self._lock:
            self._deadlines.clear()
