from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch


PACK = Path(__file__).resolve().parents[1]
RUNTIME = PACK / "lib/python_runtime.sh"
HELPER = PACK / "lib/native_usage.py"


def codex(response="r1", thread="t1", turn="u1", usage=None):
    """这些记录是合同测试替身，不代表真实宿主运行或采样证据。"""
    return {"type": "token_usage_record", "payload": {
        "thread_id": thread, "turn_id": turn, "session_id": thread,
        "response_id": response,
        "usage": usage if usage is not None else {
            "input_tokens": 10, "cached_input_tokens": 8, "output_tokens": 3,
            "reasoning_output_tokens": 2, "total_tokens": 13,
        },
    }}


def claude(usage=None, session="s1", result="v1"):
    return {"type": "result", "subtype": "success", "is_error": False,
            "session_id": session, "uuid": result,
            "usage": usage if usage is not None else {
                "input_tokens": 10, "cache_creation_input_tokens": 4,
                "cache_read_input_tokens": 8, "output_tokens": 3,
            }}


def agy(value, conversation="c1"):
    return {"conversation_id": conversation, "status": "SUCCESS", "usage": {
        "input_tokens": value, "output_tokens": value + 1,
        "thinking_tokens": 2, "cache_read_tokens": 3,
        "total_tokens": 2 * value + 1,
    }}


class NativeUsageTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(
            prefix="native-usage-", dir=Path(tempfile.gettempdir()).resolve())
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.counter = 0

    def write_agy_stream(self, *records):
        # 官方 stream-json 用 event/result 两层；此处不使用其他宿主的 type 字段替代。
        return self.write(*({"event": "result", "result": record} for record in records))

    def write(self, *records, pretty=False):
        self.counter += 1
        path = self.root / f"sample-{self.counter}.json"
        text = (json.dumps(records[0], ensure_ascii=False, indent=2) if pretty
                else "\n".join(json.dumps(r, ensure_ascii=False) for r in records))
        path.write_text(text, encoding="utf-8")
        return path

    def summarize(self, host, *paths):
        from lib import native_usage
        return native_usage.summarize_usage(host, list(paths))

    def test_codex_native_response_dedup_and_subitems_are_not_double_added(self):
        first = codex()
        first["payload"]["turn_usage"] = {"total_tokens": 9999}
        first["payload"]["thread_usage"] = {"total_tokens": 99999}
        path = self.write(first, first, codex("r2", turn="u2"), {
            "type": "event_msg", "payload": {"type": "token_count", "info": {
                "total_token_usage": {"total_tokens": 999999}}}})
        report = self.summarize("codex", path, path)
        self.assertEqual(26, report["totals"]["total_tokens"])
        self.assertEqual(16, report["totals"]["cached_input_tokens"])
        self.assertEqual(2, report["coverage"]["counted_records"])
        self.assertEqual(1, report["coverage"]["duplicate_records"])
        self.assertEqual(1, report["coverage"]["duplicate_inputs"])
        self.assertEqual(1, report["coverage"]["ignored_records"])
        self.assertEqual(2, len(report["groups"]))

    def test_codex_identity_conflicts_and_separate_threads(self):
        from lib.native_usage import NativeUsageError
        report = self.summarize("codex", self.write(codex(), codex(thread="t2")))
        self.assertEqual(26, report["totals"]["total_tokens"])
        for changed in (codex(usage={"input_tokens": 11}), codex(turn="changed")):
            with self.subTest(changed=changed), self.assertRaises(NativeUsageError):
                self.summarize("codex", self.write(codex(), changed))

    def test_codex_missing_identity_and_usage_are_visible_not_zero(self):
        missing = codex()
        del missing["payload"]["response_id"]
        no_usage = codex("r2")
        del no_usage["payload"]["usage"]
        report = self.summarize("codex", self.write(missing, no_usage))
        self.assertEqual("not_sampled", report["coverage"]["status"])
        self.assertEqual(1, report["coverage"]["missing_identity_records"])
        self.assertEqual(1, report["coverage"]["missing_usage_records"])
        self.assertIsNone(report["totals"]["total_tokens"])
        self.assertEqual({"response_id": 1}, report["coverage"]["missing_identity_fields"])
        report = self.summarize("codex", self.write(codex(usage={"total_tokens": 0})))
        self.assertEqual(0, report["totals"]["total_tokens"])
        self.assertIsNone(report["totals"]["input_tokens"])
        self.assertEqual({"present": 0, "missing": 1}, report["field_coverage"]["input_tokens"])

    def test_codex_cli_turn_requires_native_identity_and_does_not_mix_modes(self):
        from lib.native_usage import NativeUsageError
        event = {"type": "turn.completed", "thread_id": "t1", "turn_id": "u1",
                 "usage": {"input_tokens": 5, "output_tokens": 2}}
        report = self.summarize("codex", self.write(event, event))
        self.assertEqual(5, report["totals"]["input_tokens"])
        self.assertEqual(1, report["coverage"]["duplicate_records"])
        del event["turn_id"]
        self.assertEqual(1, self.summarize("codex", self.write(event))[
            "coverage"]["missing_identity_records"])
        event["turn_id"] = "u1"
        with self.assertRaises(NativeUsageError):
            self.summarize("codex", self.write(codex(), event))

    def test_claude_success_terminal_keeps_native_cache_semantics(self):
        record = claude()
        record["result"] = "正文和凭据绝不能进入摘要"
        record["usage"]["cache_creation"] = {
            "ephemeral_5m_input_tokens": 3, "ephemeral_1h_input_tokens": 1}
        record["usage"]["service_tier"] = "standard"
        report = self.summarize("claude", self.write(
            {"type": "assistant", "message": {"usage": {"input_tokens": 999}}}, record))
        self.assertEqual(10, report["totals"]["input_tokens"])
        self.assertEqual(8, report["totals"]["cache_read_input_tokens"])
        self.assertEqual(3, report["totals"]["cache_creation.ephemeral_5m_input_tokens"])
        self.assertNotIn("total_tokens", report["totals"])
        self.assertNotIn("正文", json.dumps(report, ensure_ascii=False))
        self.assertNotIn("standard", json.dumps(report))

    def test_claude_duplicate_results_conflicts_and_unidentified_inputs(self):
        from lib.native_usage import NativeUsageError
        record = claude()
        report = self.summarize("claude", self.write(record), self.write(record, pretty=True))
        self.assertEqual(10, report["totals"]["input_tokens"])
        self.assertEqual(1, report["coverage"]["duplicate_records"])
        path = self.write(record)
        repeated = self.summarize("claude", path, path)
        self.assertEqual(10, repeated["totals"]["input_tokens"])
        self.assertEqual(1, repeated["coverage"]["duplicate_inputs"])
        with self.assertRaises(NativeUsageError):
            self.summarize("claude", self.write(record, claude({"input_tokens": 11})))
        del record["uuid"]
        report = self.summarize("claude", self.write(record))
        self.assertEqual(1, report["coverage"]["missing_result_id_records"])
        self.assertEqual(10, report["totals"]["input_tokens"])
        with self.assertRaises(NativeUsageError):
            self.summarize("claude", self.write(record), self.write(record, pretty=True))

    def test_claude_failure_and_wrong_terminal_shape_rejected(self):
        from lib.native_usage import NativeUsageError
        for changes in ({"subtype": "error_max_turns"}, {"is_error": True},
                        {"is_error": 0}, {"subtype": None}):
            record = claude()
            record.update(changes)
            with self.subTest(changes=changes), self.assertRaises(NativeUsageError):
                self.summarize("claude", self.write(record))

    def test_claude_cross_file_same_bytes_require_native_result_identity(self):
        from lib.native_usage import NativeUsageError
        for has_uuid in (False, True):
            record = claude()
            if not has_uuid:
                del record["uuid"]
            first, second = self.write(record), self.write(record)
            self.assertEqual(first.read_bytes(), second.read_bytes())
            with self.subTest(has_uuid=has_uuid):
                if not has_uuid:
                    # 两个不同输入文件可能是两次调用；字节一样不能证明它们是同一原生结果。
                    with self.assertRaisesRegex(NativeUsageError, "uuid"):
                        self.summarize("claude", first, second)
                else:
                    report = self.summarize("claude", first, second)
                    self.assertEqual(1, report["coverage"]["counted_records"])
                    self.assertEqual(1, report["coverage"]["duplicate_records"])
                    self.assertEqual(10, report["totals"]["input_tokens"])
            if not has_uuid:
                # 同一明确路径重传仍兼容缺 uuid 的单结果；缺身份必须保持 partial。
                report = self.summarize("claude", first, first)
                self.assertEqual("partial", report["coverage"]["status"])
                self.assertEqual(1, report["coverage"]["missing_result_id_records"])
                self.assertEqual(1, report["coverage"]["duplicate_inputs"])
                self.assertEqual(10, report["totals"]["input_tokens"])

    def test_claude_cross_file_cli_rejects_missing_identity(self):
        record = claude()
        del record["uuid"]
        first, second = self.write(record), self.write(record)
        prefix = ["bash", str(RUNTIME), "-X", "utf8", str(HELPER), "--host", "claude"]
        # 官方形状的合同替身仅验证本地CLI，不表示真实Claude模型采样。
        result = subprocess.run(prefix + ["--input", str(first), "--input", str(second)],
                                capture_output=True, text=True, timeout=15)
        self.assertEqual(2, result.returncode, result.stdout)
        self.assertEqual("", result.stdout)
        self.assertIn("uuid", result.stderr)
        result = subprocess.run(prefix + ["--input", str(first), "--input", str(first)],
                                capture_output=True, text=True, timeout=15)
        self.assertEqual(0, result.returncode, result.stderr)
        report = json.loads(result.stdout)
        self.assertEqual("partial", report["coverage"]["status"])
        self.assertEqual(1, report["coverage"]["duplicate_inputs"])

    def test_agy_cumulative_delta_is_observed_interval_not_a_sum(self):
        report = self.summarize("antigravity", self.write_agy_stream(agy(10), agy(10), agy(14)))
        group = report["groups"][0]
        self.assertEqual(29, group["last_cumulative"]["total_tokens"])
        self.assertEqual(8, group["observed_delta"]["total_tokens"])
        self.assertEqual(4, group["observed_delta"]["input_tokens"])
        self.assertEqual(0, group["observed_delta"]["thinking_tokens"])
        self.assertEqual(1, report["coverage"]["duplicate_records"])
        self.assertNotIn("totals", report)
        single = self.summarize("antigravity", self.write(agy(10), pretty=True))["groups"][0]
        self.assertIsNone(single["observed_delta"]["total_tokens"])
        self.assertFalse(single["starts_at_zero"])
        self.assertEqual("unknown", single["initial_baseline"])
        zero = agy(0)
        zero["usage"] = {field: 0 for field in zero["usage"]}
        zero_report = self.summarize("antigravity", self.write(zero))["groups"][0]
        self.assertTrue(zero_report["starts_at_zero"])
        self.assertEqual("observed_zero", zero_report["initial_baseline"])

    def test_agy_conversations_are_isolated_and_rollback_is_rejected(self):
        from lib.native_usage import NativeUsageError
        report = self.summarize("antigravity", self.write_agy_stream(agy(10), agy(2, "c2"), agy(14)))
        self.assertEqual(2, len(report["groups"]))
        for snapshots in ((agy(10), agy(4)), (agy(10), agy(14), agy(10))):
            with self.subTest(snapshots=snapshots), self.assertRaises(NativeUsageError):
                self.summarize("antigravity", self.write_agy_stream(*snapshots))

    def test_agy_cross_input_duplicate_content_cannot_hide_rollback(self):
        from lib.native_usage import NativeUsageError
        for stream in (False, True):
            write = self.write_agy_stream if stream else self.write
            first, higher, copied_first = write(agy(10)), write(agy(14)), write(agy(10))
            # 第三份独立文件与第一份字节相同；同一路径重传也必须经过回退检查。
            for last in (copied_first, first):
                with self.subTest(stream=stream, repeated_path=last == first):
                    with self.assertRaisesRegex(NativeUsageError, "回退"):
                        self.summarize("antigravity", first, higher, last)

    def test_agy_adjacent_duplicate_exports_keep_monotonic_observations(self):
        first, higher = self.write(agy(10)), self.write(agy(14))
        report = self.summarize("antigravity", first, first, higher)
        self.assertEqual(1, report["coverage"]["duplicate_inputs"])
        self.assertEqual(2, report["coverage"]["counted_records"])
        self.assertEqual(8, report["groups"][0]["observed_delta"]["total_tokens"])
        export = self.write_agy_stream(agy(10), agy(14))
        # 紧邻同一多快照 export 是输入重传，不应把其旧首快照重新算成一次观察。
        report = self.summarize("antigravity", export, export)
        self.assertEqual(1, report["coverage"]["duplicate_inputs"])
        self.assertEqual(2, report["groups"][0]["snapshots"])
        self.assertEqual(29, report["groups"][0]["last_cumulative"]["total_tokens"])

    def test_agy_cross_input_cli_rejects_rollback_and_accepts_adjacent_replay(self):
        first, higher = self.write(agy(10)), self.write(agy(14))
        prefix = ["bash", str(RUNTIME), "-X", "utf8", str(HELPER), "--host", "antigravity"]
        command = prefix + ["--input", str(first), "--input", str(higher), "--input", str(first)]
        # 这些是官方格式的测试替身，只验证工具入口，不冒充 AGY 模型的真实采样。
        result = subprocess.run(command, capture_output=True, text=True, timeout=15)
        self.assertEqual(2, result.returncode, result.stdout)
        self.assertEqual("", result.stdout)
        self.assertIn("回退", result.stderr)
        export = self.write_agy_stream(agy(10), agy(14))
        result = subprocess.run(prefix + ["--input", str(export), "--input", str(export)],
                                capture_output=True, text=True, timeout=15)
        self.assertEqual(0, result.returncode, result.stderr)
        report = json.loads(result.stdout)
        self.assertEqual(1, report["coverage"]["duplicate_inputs"])
        self.assertEqual(2, report["coverage"]["counted_records"])

    def test_agy_missing_fields_and_identity_are_not_sampled_zeroes(self):
        first, last = agy(0), agy(3)
        del first["usage"]["thinking_tokens"]
        no_identity = agy(1)
        del no_identity["conversation_id"]
        report = self.summarize("antigravity", self.write_agy_stream(first, last, no_identity))
        self.assertIsNone(report["groups"][0]["observed_delta"]["thinking_tokens"])
        self.assertEqual(1, report["coverage"]["missing_identity_records"])
        self.assertFalse(report["groups"][0]["starts_at_zero"])
        self.assertEqual("unknown", report["groups"][0]["initial_baseline"])
        no_usage = agy(1)
        del no_usage["usage"]
        report = self.summarize("antigravity", self.write(no_usage, pretty=True))
        self.assertEqual(1, report["coverage"]["missing_usage_records"])
        self.assertEqual("not_sampled", report["coverage"]["status"])
        self.assertEqual([], report["groups"])

    def test_agy_official_stream_ignores_step_fragments_and_rejects_failed_terminal(self):
        from lib.native_usage import NativeUsageError
        report = self.summarize("antigravity", self.write(
            {"event": "init", "conversation_id": "c1", "init": {}},
            {"event": "step_update", "usage": {"total_tokens": 99999}},
            {"event": "result", "result": agy(10)}))
        self.assertEqual(21, report["groups"][0]["last_cumulative"]["total_tokens"])
        self.assertEqual(2, report["coverage"]["ignored_records"])
        record = agy(10)
        record["status"] = "ERROR"
        with self.assertRaises(NativeUsageError):
            self.summarize("antigravity", self.write(record))

    def test_invalid_counts_all_hosts_rejected_without_coercion(self):
        from lib.native_usage import NativeUsageError
        for host, make in (("codex", codex), ("claude", claude), ("antigravity", lambda: agy(1))):
            for value in (True, False, -1, 1.0, "1", None, [], {}):
                record = make()
                container = record["payload"] if host == "codex" else record
                container["usage"]["input_tokens"] = value
                with self.subTest(host=host, value=value), self.assertRaises(NativeUsageError):
                    self.summarize(host, self.write(record))

    def test_invalid_json_duplicate_keys_utf8_and_root_rejected(self):
        from lib.native_usage import NativeUsageError
        path = self.root / "bad.json"
        for body in (b'{"type":"result","type":"secret"}', b'{"x":NaN}',
                     b'{"x":Infinity}', b'{"x":1e999}', b'{}\n{"x":-Infinity}', b'[]', b'42', b'{bad}',
                     b'\xff', b'', b'\n\n'):
            path.write_bytes(body)
            with self.subTest(body=body), self.assertRaises(NativeUsageError):
                self.summarize("claude", path)

    @unittest.skipIf(os.name == "nt", "POSIX 链接与 FIFO；Windows 节点边界由共用 reader 回归覆盖")
    def test_safe_reader_rejects_links_special_files_and_oversize(self):
        from lib.native_usage import NativeUsageError
        target = self.write(codex())
        link = self.root / "link.json"
        link.symlink_to(target)
        hard = self.root / "hard.json"
        os.link(target, hard)
        fifo = self.root / "fifo"
        os.mkfifo(fifo)
        large = self.root / "large.json"
        large.write_bytes(b" " * (4 * 1024 * 1024 + 1))
        for path in (link, hard, fifo, large, self.root, self.root / "missing"):
            with self.subTest(path=path.name), self.assertRaises(NativeUsageError):
                self.summarize("codex", path)

    def test_limits_and_changed_file_fail_closed(self):
        from lib import native_usage
        path = self.write(codex())
        with patch.object(native_usage, "MAX_INPUTS", 1), self.assertRaises(native_usage.NativeUsageError):
            self.summarize("codex", path, path)
        with patch.object(native_usage, "MAX_TOTAL_BYTES", 1), self.assertRaises(native_usage.NativeUsageError):
            self.summarize("codex", path)
        with patch.object(native_usage, "MAX_RECORDS", 1), self.assertRaises(native_usage.NativeUsageError):
            self.summarize("codex", self.write(codex(), codex("r2")))
        original_reader = native_usage.read_file

        def mutate(candidate):
            body = original_reader(candidate)
            candidate.write_bytes(body + b" ")
            return body

        with patch.object(native_usage, "read_file", mutate), self.assertRaises(native_usage.NativeUsageError):
            self.summarize("codex", path)

    def test_real_cli_success_error_redaction_and_repeatable_inputs(self):
        path = self.write(codex())
        before = path.read_bytes()
        command = ["bash", str(RUNTIME), "-X", "utf8", str(HELPER), "--host", "codex",
                   "--input", str(path), "--input", str(path)]
        result = subprocess.run(command, capture_output=True, text=True, timeout=15)
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual("", result.stderr)
        self.assertEqual(13, json.loads(result.stdout)["totals"]["total_tokens"])
        self.assertEqual(before, path.read_bytes())
        path.write_text('{"secret_body":"千万不能输出", "type":"result", "type":"bad"}', encoding="utf-8")
        result = subprocess.run(command, capture_output=True, text=True, timeout=15)
        self.assertEqual(2, result.returncode)
        self.assertEqual("", result.stdout)
        self.assertNotIn("千万不能输出", result.stderr)
        self.assertNotIn("secret_body", result.stderr)
        self.assertNotIn("Traceback", result.stderr)


if __name__ == "__main__":
    unittest.main()
