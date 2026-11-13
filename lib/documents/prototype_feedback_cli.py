#!/usr/bin/env python3
"""原型反馈的薄只读 CLI：仅输出准备链接或节点修订交接。"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

# 直接执行和插件 run_module 都禁止生成字节码；只读反馈不得在项目或包旁写缓存。
sys.dont_write_bytecode = True
if not __package__:
    # 信任自身物理根，不能让用户 cwd/PYTHONPATH 的同名模块替换反馈安全边界。
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from lib.documents.prototype_feedback import FeedbackError, parse_feedback, prepare_review, validate_feedback
from lib.documents.safe_documents import snapshot
from lib.documents.prototype_review import migration_preview, migration_apply, migration_recover, _closed_json


def main(argv: list[str] | None = None) -> int:
    class Parser(argparse.ArgumentParser):
        def error(self, message):
            raise FeedbackError("命令参数无效：" + message)

    parser = Parser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    prepare = commands.add_parser("prepare", help="准备带有限上下文的原型评审链接")
    validate = commands.add_parser("validate", help="复核导出的意见并输出节点交接")
    preview = commands.add_parser("migration-preview", help="只读预览纯工具归属和安全迁移影响")
    apply = commands.add_parser("migration-apply", help="凭同一来源 preview 显式迁移；不处理未知业务资产")
    recover = commands.add_parser("migration-recover", help="恢复中断迁移，保留冲突的用户新内容")
    for command in (prepare, validate, preview, apply, recover):
        command.add_argument("--root", required=True, type=Path, help="实际项目的绝对目录")
        command.add_argument("--adapter", required=True, help="本次显式选择的项目相对适配器")
        if command is not preview:
            command.add_argument("--data-dir", type=Path, help="用户级私有数据目录；测试应显式指定临时目录")
    for command in (prepare, preview):
        command.add_argument("--plan", required=True, help="项目相对需求 Markdown")
        command.add_argument("--request-id", required=True, help="当前请求的稳定 ID")
        command.add_argument("--pages", nargs="+", help="可选的项目相对具体 HTML 路径")
    preview.add_argument("--confirm-no-active-use", action="store_true", help="明确已排除本轮待迁移资产的活动使用；否则只报告保留")
    for command in (apply, recover):
        command.add_argument("--preview", required=True, type=Path, help="已审阅的原 preview JSON 文件")
    validate.add_argument("--input", required=True, type=Path, help="显式选择的反馈 JSON 文件")
    try:
        args = parser.parse_args(argv)
        if args.command == "prepare":
            result = prepare_review(args.root, args.adapter, args.plan, args.request_id, args.pages, data_dir=args.data_dir)
        elif args.command == "migration-preview":
            result = migration_preview(args.root, args.adapter, args.plan, args.request_id, args.pages,
                                       confirm_no_active_use=args.confirm_no_active_use)
        elif args.command in {"migration-apply", "migration-recover"}:
            preview_path = args.preview.absolute()
            raw, identity = snapshot(preview_path)
            operation = migration_apply if args.command == "migration-apply" else migration_recover
            parsed = _closed_json(raw)
            # 操作开始前固定输入；执行后只检查，不重新解释或悄悄替换 preview。
            if snapshot(preview_path) != (raw, identity): raise FeedbackError("迁移 preview 在读取期间变化")
            result = operation(args.root, args.adapter, parsed, data_dir=args.data_dir)
        else:
            input_path = args.input.absolute()
            if ".." in input_path.parts or "\\" in str(input_path):
                raise FeedbackError("反馈文件须使用无父跳转的明确路径")
            raw, identity = snapshot(input_path)
            result = validate_feedback(args.root, args.adapter, parse_feedback(raw), data_dir=args.data_dir)
            # 核验完成前意见本身也不能被替换；无论成功/失败都不改写或重绑输入文件。
            if snapshot(input_path) != (raw, identity):
                raise FeedbackError("反馈文件在核验期间发生变化")
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        return 0
    except (ValueError, OSError, TypeError, RecursionError) as exc:
        print(json.dumps({"status": "error", "error": {"code": "invalid_feedback", "message": "反馈处理失败：" + str(exc)}},
                         ensure_ascii=False, sort_keys=True))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
