#!/usr/bin/env python3
"""只读汇总显式输入的原生用量，不读取账户、价格或其他会话，也不调用模型。

接口：bash lib/python_runtime.sh -X utf8 lib/native_usage.py --host HOST --input PATH
可重复 --input；每个文件是一个 JSON 对象（允许缩进）或逐行一个对象的 JSONL。
输入顺序就是观察顺序；本工具不根据 ID 推断时间，不排序或修复累计计数回退。
AGY 仅将紧邻的字节相同输入视为 export 重传；其他重复输入仍逐记录核对累计顺序。
每文件最多 4 MiB、整批最多 16 MiB／32 文件／20000 条记录，须先显式导出精简元数据。

Codex desktop 只加 token_usage_record.payload.usage，按 (thread_id,response_id)
去重；CLI turn.completed 仅在自带 thread_id、turn_id 时支持，且不与响应口径混加。
Claude 只接收成功终端 result，按 (session_id,uuid) 去重，不混入 assistant 片段。
Claude 缺 uuid 时仅接受该 session 的一个终端结果，不能证明跨流身份时拒绝合并。
Claude 仅将同一明确路径的同字节输入视为 export 重传，不同文件不以内容 SHA 代替 uuid。
AGY 单 JSON 使用 conversation_id/status=SUCCESS/usage，stream-json 仅消费
event=result 的 result 子对象；result.usage 是会话累计快照，只输出最后累计及首末观察
差值，单个快照的差值为 null。缺身份记录不计入总量，并在 coverage 显式披露。

字段使用宿主原名；cache_creation 的嵌套计数以点分路径保留。缺失字段输出 null，
真实零保持 0；缓存、推理子项不再次加到原生 total，也不推导缺失的 total。
输出仅有用量、已校验身份和覆盖摘要，不返回输入正文、错误载荷或任意元数据。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import re
import sys
from typing import Any

if __package__:
    from .claude_instructions import read_file
else:
    from claude_instructions import read_file


MAX_INPUTS = 32
MAX_TOTAL_BYTES = 16 * 1024 * 1024
MAX_RECORDS = 20000
MAX_COUNTER = 2**63 - 1
FIELDS = {
    "codex": ("input_tokens", "cached_input_tokens", "cache_write_input_tokens",
              "output_tokens", "reasoning_output_tokens", "total_tokens"),
    "claude": ("input_tokens", "output_tokens", "cache_creation_input_tokens",
               "cache_read_input_tokens", "cache_creation.ephemeral_5m_input_tokens",
               "cache_creation.ephemeral_1h_input_tokens"),
    "antigravity": ("input_tokens", "output_tokens", "thinking_tokens",
                    "cache_read_tokens", "total_tokens"),
}


class NativeUsageError(ValueError):
    """输入未满足原生计数或只读安全合同；消息不能包含输入正文。"""


def _unique_object(pairs):
    """全层级拒绝重复键，错误只报类别，不回显可能携带凭据的键名。"""
    result = {}
    for key, value in pairs:
        if key in result:
            raise NativeUsageError("JSON 含重复键")
        result[key] = value
    return result


def _nonfinite(_value):
    raise NativeUsageError("JSON 不允许 NaN 或 Infinity")


def _decode(text):
    def finite_float(raw):
        value = float(raw)
        if not math.isfinite(value):
            raise NativeUsageError("JSON 数值不能超出有限范围")
        return value

    return json.loads(text, object_pairs_hook=_unique_object, parse_constant=_nonfinite,
                      parse_float=finite_float)


def _records(body):
    """先尝试完整 JSON 对象，只有语法失败才逐行解析；数组不是多记录协议。"""
    text = body.decode("utf-8", errors="strict")
    try:
        value = _decode(text)
    except json.JSONDecodeError:
        lines = [line for line in text.splitlines() if line.strip()]
        if not lines or len(lines) > MAX_RECORDS:
            raise NativeUsageError("输入为空或超过记录数上限") from None
        try:
            values = [_decode(line) for line in lines]
        except (json.JSONDecodeError, ValueError, RecursionError):
            raise NativeUsageError("输入须为单个 JSON 对象或逐行 JSON 对象") from None
        form = "jsonl"
    else:
        values, form = [value], "json"
    if any(not isinstance(value, dict) for value in values):
        raise NativeUsageError("每条原生记录必须是 JSON 对象")
    return values, form


def _file_identity(info):
    return (info.st_dev, info.st_ino, info.st_mode, info.st_nlink, info.st_size,
            info.st_mtime_ns, info.st_ctime_ns)


def _read(path):
    """不 resolve 输入路径，避免跟随链接后绕过共用 reader 的拒绝边界。"""
    try:
        path = Path(path)
        if ".." in path.parts:
            raise NativeUsageError("输入路径不得包含父目录跳转")
        path = path.absolute()
        before = path.lstat()
        body = read_file(path)
        after = path.lstat()
    except UnicodeError:
        raise NativeUsageError("输入必须是完整、有效的 UTF-8") from None
    except NativeUsageError:
        raise
    except (OSError, ValueError, TypeError):
        raise NativeUsageError("无法安全读取输入：须为无链接父目录的单链接普通文件，且不超过 4 MiB") from None
    # 共用 reader 固定打开时的节点；这里再校验读取结束时未替换、截断或改写。
    if body is None or _file_identity(before) != _file_identity(after) or len(body) != before.st_size:
        raise NativeUsageError("输入在读取期间发生变化")
    return body


def _native_id(record, name):
    value = record.get(name)
    if value is None:
        return None
    # 身份只接受有界的可打印原生 ID；不允许控制字符或把长正文带入输出。
    if not isinstance(value, str) or re.fullmatch(r"[A-Za-z0-9_.:-]{1,256}", value) is None:
        raise NativeUsageError("原生身份必须是 1..256 位 ASCII 标识符")
    return value


def _usage(value, host):
    """只提取已确认的原生计数，不复制 usage 中的任意字符串或未知载荷。"""
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise NativeUsageError("usage 必须是对象")
    result = {}
    for field in FIELDS[host]:
        current = value
        for part in field.split("."):
            if not isinstance(current, dict) or part not in current:
                break
            current = current[part]
        else:
            # bool 是 int 子类，必须按精确类型判断；也不能把浮点／字符串强制转整数。
            if type(current) is not int or not 0 <= current <= MAX_COUNTER:
                raise NativeUsageError("原生 token 计数必须是 0..2^63-1 的整数，不能是 bool、浮点或 null")
            result[field] = current
    if host == "claude" and "cache_creation" in value and not isinstance(value["cache_creation"], dict):
        raise NativeUsageError("cache_creation 必须是对象")
    return result


def _summary(usages, fields):
    """只加已观察字段；coverage 说明哪些记录缺字段，不能把缺失当零补齐。"""
    totals, coverage = {}, {}
    for field in fields:
        present = [usage[field] for usage in usages if field in usage]
        totals[field] = sum(present) if present else None
        coverage[field] = {"present": len(present), "missing": len(usages) - len(present)}
    return totals, coverage


def summarize_usage(host: str, inputs: list[Path]) -> dict[str, Any]:
    """只读消费明确列出的文件；任一冲突／回退使整批失败，不返回部分成功总量。"""
    if host not in FIELDS:
        raise NativeUsageError("host 只支持 codex、claude、antigravity")
    if not inputs or len(inputs) > MAX_INPUTS:
        raise NativeUsageError("必须提供 1..32 个明确输入文件")
    coverage = dict(input_files=len(inputs), duplicate_inputs=0, parsed_records=0,
                    matched_records=0, counted_records=0, duplicate_records=0,
                    ignored_records=0, missing_identity_records=0, missing_usage_records=0,
                    missing_result_id_records=0, incomplete_identity_records=0,
                    missing_identity_fields={})
    sources, seen_files, seen_units, groups = [], set(), {}, {}
    counted_usages = []
    total_bytes = 0
    codex_mode = None
    previous_digest = None
    for path in inputs:
        body = _read(path)
        total_bytes += len(body)
        if total_bytes > MAX_TOTAL_BYTES:
            raise NativeUsageError("整批输入超过 16 MiB 上限")
        digest = hashlib.sha256(body).hexdigest()
        adjacent_duplicate = digest == previous_digest
        previous_digest = digest
        # Claude 的不同文件即使字节相同，也可能是两个独立 print 结果，不能以 SHA
        # 冒充原生 uuid。只允许同一明确路径、同一版本的 export 重传快捷去重；
        # 不 resolve 路径，沿用 _read 已检查的无链接路径，避免绕过安全读取边界。
        export_key = (Path(path).absolute(), digest) if host == "claude" else digest
        if export_key in seen_files:
            coverage["duplicate_inputs"] += 1
            # Codex 和 Claude 的已确认 export 重传可直接跳过。AGY 是有序累计快照：
            # 只把紧邻相同 export 当作重传，避免多快照 export 重传造成伪回退；
            # 非紧邻的同 SHA 仍须逐记录检查，否则 A10→B14→A10 会隐藏真实回退。
            if host != "antigravity" or adjacent_duplicate:
                continue
        seen_files.add(export_key)
        try:
            records, form = _records(body)
        except (UnicodeError, ValueError, RecursionError) as exc:
            if isinstance(exc, NativeUsageError):
                raise
            raise NativeUsageError("输入不是合法、有界的 UTF-8 JSON") from None
        sources.append({"sha256": digest, "bytes": len(body), "format": form})
        coverage["parsed_records"] += len(records)
        if coverage["parsed_records"] > MAX_RECORDS:
            raise NativeUsageError("整批输入超过记录数上限")
        for record in records:
            kind = record.get("type")
            if host == "codex":
                if kind == "token_usage_record":
                    native, mode = record.get("payload"), "response"
                elif kind == "turn.completed":
                    native, mode = record, "turn"
                else:
                    coverage["ignored_records"] += 1
                    continue
                if not isinstance(native, dict):
                    raise NativeUsageError("Codex 用量记录缺少原生对象")
                identity = {name: _native_id(native, name) for name in (
                    "thread_id", "turn_id", "session_id", "response_id")}
                unit_id = identity["response_id"] if mode == "response" else identity["turn_id"]
                key = (identity["thread_id"], unit_id)
                complete_identity = all(key)
                identity_fields = ("thread_id", "turn_id", "session_id", "response_id") if mode == "response" else ("thread_id", "turn_id")
            elif host == "claude":
                if kind != "result":
                    coverage["ignored_records"] += 1
                    continue
                if record.get("subtype") != "success" or record.get("is_error") is not False:
                    raise NativeUsageError("Claude 只接受 subtype=success 且 is_error=false 的终端 result")
                native = record
                identity = {"session_id": _native_id(record, "session_id"),
                            "uuid": _native_id(record, "uuid")}
                key = (identity["session_id"], identity["uuid"])
                complete_identity = identity["session_id"] is not None
                identity_fields = ("session_id", "uuid")
            else:
                # 官方 stream-json 的 result 在子对象内；step_update.usage 是片段，
                # 不能和累计 result.usage 混加。普通 JSON 只允许无 event/type 的终端对象。
                if record.get("event") == "result":
                    native = record.get("result")
                    if not isinstance(native, dict):
                        raise NativeUsageError("AGY event=result 必须包含 result 对象")
                elif (form == "json" and "event" not in record and "type" not in record
                      and any(name in record for name in ("conversation_id", "status", "usage"))):
                    native = record
                else:
                    coverage["ignored_records"] += 1
                    continue
                if (native.get("status") != "SUCCESS"
                        or ("is_error" in native and native["is_error"] is not False)
                        or native.get("error")):
                    raise NativeUsageError("AGY 终端结果表示失败，拒绝当作成功用量")
                identity = {"conversation_id": _native_id(native, "conversation_id")}
                key = identity["conversation_id"]
                complete_identity = key is not None
                identity_fields = ("conversation_id",)
            coverage["matched_records"] += 1
            absent = [name for name in identity_fields if identity.get(name) is None]
            if absent:
                coverage["incomplete_identity_records"] += 1
                for name in absent:
                    coverage["missing_identity_fields"][name] = coverage["missing_identity_fields"].get(name, 0) + 1
            usage = _usage(native.get("usage"), host)
            if not usage:
                coverage["missing_usage_records"] += 1
            if not complete_identity:
                coverage["missing_identity_records"] += 1
            if not usage or not complete_identity:
                continue

            if host == "antigravity":
                group = groups.get(key)
                if group is None:
                    group = {**identity, "snapshots": 0, "first_observed": usage,
                             "last_cumulative": usage, "seen_counters": {}, "usages": []}
                    groups[key] = group
                # 即便此前出现过相同快照，落在较大计数之后仍是逆序／重置，不能静默去重。
                if any(value < group["seen_counters"].get(field, value) for field, value in usage.items()):
                    raise NativeUsageError("AGY 同会话累计计数回退：输入逆序或会话重置，须分开核对")
                if group["snapshots"] and usage == group["last_cumulative"]:
                    coverage["duplicate_records"] += 1
                    continue
                group["snapshots"] += 1
                group["last_cumulative"] = usage
                group["seen_counters"].update(usage)
                group["usages"].append(usage)
            else:
                if host == "codex":
                    if codex_mode is not None and mode != codex_mode:
                        raise NativeUsageError("Codex 响应用量与逐 turn 汇总不能混加")
                    codex_mode = mode
                elif identity["uuid"] is None:
                    coverage["missing_result_id_records"] += 1
                    # session_id 不能区分同会话的多个 print 调用，不能拿相同计数猜测重复。
                    if any(unit[0] == identity["session_id"] for unit in seen_units):
                        raise NativeUsageError("Claude 缺终端 uuid，无法证明同会话跨结果身份")
                if host == "claude" and (identity["session_id"], None) in seen_units:
                    raise NativeUsageError("Claude 同会话已有缺 uuid 结果，拒绝不确定合并")
                if key in seen_units:
                    if seen_units[key] != (identity, usage):
                        raise NativeUsageError("同一原生身份出现冲突用量或归属")
                    coverage["duplicate_records"] += 1
                    continue
                seen_units[key] = (identity, usage)
                if host == "codex":
                    group_key = (identity["thread_id"], identity["turn_id"], identity["session_id"])
                    group_identity = {name: identity[name] for name in ("thread_id", "turn_id", "session_id")}
                else:
                    group_key, group_identity = key, identity
                group = groups.setdefault(group_key, {**group_identity, "usages": []})
                group["usages"].append(usage)
                counted_usages.append(usage)
            coverage["counted_records"] += 1

    coverage["status"] = ("not_sampled" if not coverage["counted_records"] else
                          "partial" if any(coverage[name] for name in (
                              "incomplete_identity_records", "missing_usage_records", "missing_result_id_records"))
                          else "sampled")
    result = {"host": host, "scope": "provided_native_records_only", "sources": sources,
              "coverage": coverage, "groups": []}
    fields = FIELDS[host]
    for group in groups.values():
        usages = group.pop("usages")
        if host == "antigravity":
            group.pop("seen_counters")
            first, last = group["first_observed"], group["last_cumulative"]
            group["observed_delta"] = {
                field: last[field] - first[field]
                if group["snapshots"] >= 2 and field in first and field in last else None
                for field in fields}
            # 只有首个快照明确给出所有原生字段为零，才有已观察的零起点。
            group["starts_at_zero"] = all(field in first and first[field] == 0 for field in fields)
            # 非零首快照只是窗口起点，无法证明会话创建时的初始基线；缺字段同样未知。
            group["initial_baseline"] = "observed_zero" if group["starts_at_zero"] else "unknown"
            group["first_observed"] = {field: first.get(field) for field in fields}
            group["last_cumulative"] = {field: last.get(field) for field in fields}
            _, group["field_coverage"] = _summary(usages, fields)
        else:
            group["record_count"] = len(usages)
            group["usage"], group["field_coverage"] = _summary(usages, fields)
        result["groups"].append(group)
    if host != "antigravity":
        result["totals"], result["field_coverage"] = _summary(counted_usages, fields)
    result["usage_semantics"] = ({"codex": f"per_{codex_mode or 'response'}",
                                  "claude": "terminal_result_native_fields",
                                  "antigravity": "conversation_cumulative_observed_interval"}[host])
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--host", required=True, choices=tuple(FIELDS))
    parser.add_argument("--input", required=True, type=Path, action="append",
                        help="单 JSON 对象或 JSONL 的显式精简导出路径；可重复，按传入顺序观察")
    args = parser.parse_args()
    try:
        result = summarize_usage(args.host, args.input)
    except NativeUsageError as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
