"""按项目和当前 PM 查询、登记、领取或归档原任务记录。"""

from __future__ import annotations

if not __package__:
    import sys as _sys
    from pathlib import Path as _Path
    _sys.path.insert(0, str(_Path(__file__).resolve().parents[1]))

import argparse
import json
from pathlib import Path
import subprocess
import sys

from lib import task_graph_records as records, task_pool
from lib.agent_continuation import HOSTS
from lib.dispatch_admission_cli import _project_directory
from lib.hosts.factory import dispatch_policy, packaged_host
from lib.task_graph import TaskGraphError


def _capacity(args) -> dict | None:
    names = ("configured_subagents", "configured_writers", "host_available_subagents")
    result = {name: getattr(args, name, None) for name in names}
    if all(value is None for value in result.values()):
        return None
    if any(value is None for value in result.values()):
        raise TaskGraphError("capacity requires all three flags, including the fresh host observation")
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--root", required=True, help="当前项目的绝对物理根")
    common.add_argument("--pm-id", required=True, help="当前宿主和 PM 的稳定标识，不传私人信息或密钥")
    sub = parser.add_subparsers(dest="command", required=True)
    reg = sub.add_parser("register", parents=[common], help="登记一份原图或 Light 单包；可用最新 SHA 显式扩员")
    reg.add_argument("--title", help="可选短标题，最多 120 字")
    archive = sub.add_parser("archive", parents=[common], help="解除已全部终结的原记录登记，保留原件")
    claim = sub.add_parser("claim", parents=[common], help="按查看到的具体任务与 SHA 领取")
    for cmd in (reg, archive, claim):
        cmd.add_argument("--record", required=True, help="权威原记录绝对路径")
        cmd.add_argument("--expect-sha256", required=True, help="本次指令针对的原记录字节 SHA256")
    claim.add_argument("--request-id", required=True)
    claim.add_argument("--task-id", required=True)
    claim.add_argument("--register", action="store_true", help="首次派发时先登记该权威原件，再按完整池领取")
    claim.add_argument("--title", help="首次登记或显式扩员时的可读标题，须与 --register 同用")
    view = sub.add_parser("view", aliases=["status"], parents=[common], help="读取当前原件，查看记录与任务")
    view.add_argument("--query", help="标题、目标、请求、任务 ID 或别名关键字")
    view.add_argument("--record", help="只显示所选记录中的任务")
    release = sub.add_parser("release", parents=[common], help="用原领取回执与宿主结果保留或释放名额")
    release.add_argument("--receipt", type=Path, required=True)
    release.add_argument("--outcome", choices=["definitely_not_created", "unknown"], required=True)
    bind = sub.add_parser("bind", parents=[common], help="将本次原生创建实际返回的身份绑定到已领取的原任务")
    bind.add_argument("--receipt", type=Path, required=True)
    bind.add_argument("--host", choices=HOSTS, required=True)
    bind.add_argument("--agent-id", required=True)
    handoff = sub.add_parser("handoff", parents=[common], help="从当前 AGY 原件生成初次派发 Prompt")
    handoff.add_argument("--receipt", type=Path, required=True)
    finish = sub.add_parser("complete-writer", parents=[common], help="登记 PM 已核定的 AGY Writer 验证结果")
    for field in ("record", "expect-sha256", "request-id", "task-id", "agent-id", "source", "evidence"):
        finish.add_argument("--" + field, required=True)
    finish.add_argument("--revision", type=int)
    finish.add_argument("--verification-exit-code", required=True, type=int)
    closeout = sub.add_parser("closeout", parents=[common], help="只读核对本请求的验收、保全及精确可回收实例")
    closeout.add_argument("--request-id", required=True)
    closeout.add_argument("--preservation", type=Path)
    finish_closeout = sub.add_parser("finish-closeout", parents=[common], help="按原件 SHA 登记精确实例的终态观察")
    for field in ("request-id", "task-id", "record", "expect-sha256", "evidence"):
        finish_closeout.add_argument("--" + field, required=True)
    for cmd in (view, claim, release):
        for flag in ("configured-subagents", "configured-writers", "host-available-subagents"):
            cmd.add_argument("--" + flag, type=int, required=cmd is not view)
    args = parser.parse_args(argv)
    try:
        root = _project_directory(args.root)
        if args.command in ("view", "status"):
            result = task_pool.view(root, args.pm_id, path=args.record, query=args.query, capacity=_capacity(args))
        elif args.command == "register":
            result = task_pool.register(root, args.pm_id, args.record, args.expect_sha256, args.title)
        elif args.command == "archive":
            result = task_pool.archive(root, args.pm_id, args.record, args.expect_sha256)
        elif args.command == "claim":
            policy = dispatch_policy(args.pm_id)
            target = {"record": args.record, "request_id": args.request_id, "task_id": args.task_id}
            if args.title is not None and not args.register:
                raise TaskGraphError("--title on claim requires --register")
            if args.register:
                # 先以同一 SHA 验证登记对象。两步之间若原件、门禁或全池占用变化，
                # operate 会重读全部登记项并拒绝过期领取；已登记的委托仍能恢复。
                task_pool.register(root, args.pm_id, args.record, args.expect_sha256, args.title,
                                   dispatch_target=target, policy=policy)
            result = task_pool.operate(root, args.pm_id, "claim", _capacity(args), target=target,
                                       expected=args.expect_sha256, policy=policy)
        elif args.command in {"handoff", "complete-writer"}:
            if packaged_host() != "antigravity":
                raise TaskGraphError("this operation requires the Antigravity plugin package")
            if args.command == "handoff":
                receipt = records.decode(records.read_record(args.receipt))
                result = task_pool.agy_handoff(root, args.pm_id, receipt)
            else:
                target = {"record": args.record, "request_id": args.request_id, "task_id": args.task_id}
                result = task_pool.complete_agy_writer(
                    root, args.pm_id, target, args.expect_sha256, args.agent_id, revision=args.revision,
                    verification_exit_code=args.verification_exit_code, source=args.source, evidence=args.evidence,
                )
        elif args.command in {"closeout", "finish-closeout"}:
            if args.command == "closeout":
                result = task_pool.closeout(root, args.pm_id, args.request_id, args.preservation,
                                            installed=packaged_host())
            else:
                target = {"record": args.record, "request_id": args.request_id, "task_id": args.task_id}
                result = task_pool.finish_closeout(root, args.pm_id, target, args.expect_sha256,
                                                   Path(args.evidence), installed=packaged_host())
        elif args.command == "bind":
            receipt = records.decode(records.read_record(args.receipt))
            result = task_pool.bind(root, args.pm_id, receipt, {"host": args.host, "agent_id": args.agent_id},
                                    policy=dispatch_policy(args.pm_id, reference_host=args.host))
        else:
            receipt = records.decode(records.read_record(args.receipt))
            result = task_pool.operate(root, args.pm_id, "release", _capacity(args), receipt=receipt,
                                       outcome=args.outcome, policy=dispatch_policy(args.pm_id))
    except (ValueError, OSError, subprocess.SubprocessError) as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
