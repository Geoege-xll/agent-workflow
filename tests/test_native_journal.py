"""纯原生日志codec测试；不导入宿主发布夹具或POSIX终端模块。"""

import base64
import copy
import json
import unittest
from unittest.mock import patch

from lib.hosts import native_journal

json_bytes = native_journal.json_bytes


def _snapshot(payload, mode=0o600, identity=()):
    # 这里只构造codec字段，没有真实文件身份，也不提供任何文件系统授权。
    return {"kind": "file", "body": base64.b64encode(payload).decode("ascii"),
            "mode": mode, "identity": list(identity)}


class NativeJournalCodecTest(unittest.TestCase):
    def test_lossless_deterministic_shared_body_and_independent_containers(self):
        for security in (None, "a" * 64):
            node = _snapshot(b"exact bytes\x00\xff", 0o600, (1, 2, 3, 1, 13, 5, 6))
            if security is not None:
                node["security"] = security
            logical = {"schema_version": 1, "first": node, "second": node}
            with self.subTest(security=security):
                encoded = native_journal.encode(logical)
                wire = json.loads(encoded)
                self.assertEqual(2, wire["schema_version"])
                self.assertEqual(1, len(wire["bodies"]))
                reordered = {key: (dict(reversed(list(value.items()))) if isinstance(value, dict) else value)
                             for key, value in reversed(list(logical.items()))}
                self.assertEqual(encoded, native_journal.encode(reordered))
                restored = native_journal.decode(encoded)
                self.assertEqual(logical, restored)
                self.assertIs(restored["first"]["body"], restored["second"]["body"])
                self.assertIsNot(restored["first"], restored["second"])
                self.assertIsNot(restored["first"]["identity"], restored["second"]["identity"])
                self.assertEqual(encoded, native_journal.encode(restored))
                self.assertEqual(1, logical["schema_version"])
                self.assertNotIn("body_ref", logical["first"])

    def test_physical_limit_and_repeated_body_logical_limit_are_separate(self):
        LIMIT = native_journal.LIMIT
        node = _snapshot(b"x" * 600000, 0o600)
        logical = {"schema_version": 1, "nodes": [node] * 9}
        with self.assertRaises(ValueError):
            json_bytes(logical)
        encoded = native_journal.encode(logical)
        self.assertLess(len(encoded), LIMIT)
        self.assertEqual(logical, native_journal.decode(encoded))
        # 物理表仍只有一份正文，扩大引用次数必须被独立的 RAM 展开界拒绝。
        wire = json.loads(encoded)
        wire["nodes"] *= 2
        with self.assertRaises(ValueError):
            native_journal.decode(json_bytes(wire))
        with self.assertRaises(ValueError):
            native_journal.encode({"schema_version": 1, "nodes": [node] * 18})
        with self.assertRaises(ValueError):
            native_journal.decode(b" " * (LIMIT + 1))
        legacy = {"schema_version": 1, "legacy": {"body_ref": "not a v2 reference"}}
        self.assertEqual(legacy, native_journal.decode(json_bytes(legacy)))
        # compact 很小的深宽图仍会被 pretty 缩进放大；必须在最终 serializer
        # 组装字符串前拒绝，不能先分配超限正文再依赖 json_bytes 的事后检查。
        deep = [0] * 20000
        for _ in range(160):
            deep = [deep]
        with patch.object(native_journal, "json_bytes", side_effect=AssertionError("must reject before pretty allocation")):
            with self.assertRaises(ValueError):
                native_journal.encode({"schema_version": 1, "applied_evidence": deep})

    def test_malformed_references_tables_cycles_and_unknown_schema_fail_closed(self):
        wire = json.loads(native_journal.encode({"schema_version": 1, "node": _snapshot(b"one", 0o600)}))
        candidates = []
        for reference in (True, -1, 1, "0", None):
            bad = copy.deepcopy(wire)
            bad["node"]["body_ref"] = reference
            candidates.append(bad)
        for body in (wire["bodies"][0], base64.b64encode(b"unused").decode()):
            candidates.append({**copy.deepcopy(wire), "bodies": [*wire["bodies"], body]})
        candidates += [{**copy.deepcopy(wire), "bodies": ["not base64!"]},
                       {**copy.deepcopy(wire), "bodies": [{}]},
                       {**copy.deepcopy(wire), "schema_version": 3},
                       {**copy.deepcopy(wire), "node": {**wire["node"], "unknown": True}},
                       {**copy.deepcopy(wire), "node": _snapshot(b"one", 0o600)}]
        for index, bad in enumerate(candidates):
            with self.subTest(index=index), self.assertRaises(ValueError):
                native_journal.decode(json_bytes(bad))
        with self.assertRaises(ValueError):
            native_journal.decode(b'{"schema_version":2,"schema_version":2,"bodies":[]}')
        logical = {"schema_version": 1}
        logical["cycle"] = logical
        with self.assertRaises(ValueError):
            native_journal.encode(logical)
