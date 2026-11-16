"""派生凭据的时间、容量和并发边界；不读取用户目录或启动实际宿主。"""

from concurrent.futures import ThreadPoolExecutor
import threading
import unittest
from unittest import mock

from native_config.browser_sessions import (BrowserSessionLimitError, BrowserSessions,
                                            MAX_BROWSER_SESSIONS, SESSION_TTL_SECONDS)


class BrowserSessionsTest(unittest.TestCase):
    def setUp(self):
        # 单独替换模块引用，不修改 HTTP 服务或其他线程使用的全局 time 模块。
        self.clock = mock.Mock()
        self.clock.monotonic.return_value = 100.0
        self.clock.time.return_value = 1_800_000_000.125
        self.patch = mock.patch("native_config.browser_sessions.time", self.clock)
        self.patch.start()
        self.addCleanup(self.patch.stop)
        self.sessions = BrowserSessions()

    def test_absolute_expiry_ignores_wall_clock_changes_and_access(self):
        token, expires_at = self.sessions.issue()
        self.assertRegex(token, r"^[A-Za-z0-9_-]{43}$")
        self.assertEqual(expires_at, 1_800_001_800_125)
        self.clock.time.return_value -= 100_000
        self.clock.monotonic.return_value = 100 + SESSION_TTL_SECONDS - 0.001
        self.assertTrue(self.sessions.valid(token))
        self.clock.monotonic.return_value = 100 + SESSION_TTL_SECONDS
        self.assertFalse(self.sessions.valid(token))
        # 已过期项不能因为墙钟回拨或随后验证而重新出现。
        self.clock.monotonic.return_value += 1
        self.assertFalse(self.sessions.valid(token))

    def test_capacity_rejects_without_evicting_and_reclaims_expired(self):
        tokens = [self.sessions.issue()[0] for _ in range(MAX_BROWSER_SESSIONS)]
        with self.assertRaises(BrowserSessionLimitError):
            self.sessions.issue()
        self.assertTrue(all(self.sessions.valid(token) for token in tokens))
        self.clock.monotonic.return_value += SESSION_TTL_SECONDS
        renewed, _ = self.sessions.issue()
        self.assertTrue(self.sessions.valid(renewed))
        self.assertTrue(all(not self.sessions.valid(token) for token in tokens))

    def test_instances_unknown_inputs_and_clear_do_not_transfer_authority(self):
        token, _ = self.sessions.issue()
        self.assertFalse(BrowserSessions().valid(token))
        for invalid in (None, b"a" * 43, "a" * 43, token + " ", "é" * 43):
            self.assertFalse(self.sessions.valid(invalid))
        self.sessions.clear()
        self.assertFalse(self.sessions.valid(token))

    def test_parallel_issuance_keeps_exact_capacity_and_unique_tokens(self):
        # 同时起步制造真实容量竞争；不能靠先检查再登记而超卖 64 个名额。
        start = threading.Barrier(16)

        def issue_batch(_index):
            start.wait(timeout=3)
            results = []
            for _ in range(5):
                try:
                    results.append(self.sessions.issue()[0])
                except BrowserSessionLimitError:
                    results.append(None)
            return results

        with ThreadPoolExecutor(max_workers=16) as pool:
            results = [token for batch in pool.map(issue_batch, range(16)) for token in batch]
        tokens = [token for token in results if token is not None]
        self.assertEqual(len(tokens), MAX_BROWSER_SESSIONS)
        self.assertEqual(len(set(tokens)), MAX_BROWSER_SESSIONS)
        self.assertEqual(results.count(None), 16)
