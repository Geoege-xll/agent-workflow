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


def main(argv: list[str] | None = None) -> int:
    class Parser(argparse.ArgumentParser):
        def error(self, message):
            raise FeedbackError("命令参数无效：" + message)

    parser = Parser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    prepare = commands.add_parser("prepare", help="准备带有限上下文的原型评审链接")
    validate = commands.add_parser("validate", help="复核导出的意见并输出节点交接")
    for command in (prepare, validate):
        command.add_argument("--root", required=True, type=Path, help="实际项目的绝对目录")
        command.add_argument("--adapter", required=True, help="本次显式选择的项目相对适配器")
    prepare.add_argument("--plan", required=True, help="项目相对需求 Markdown")
    prepare.add_argument("--request-id", required=True, help="当前请求的稳定 ID")
    prepare.add_argument("--pages", nargs="+", help="可选的项目相对具体 HTML 路径")
    validate.add_argument("--input", required=True, type=Path, help="显式选择的反馈 JSON 文件")
    try:
        args = parser.parse_args(argv)
        if args.command == "prepare":
            result = prepare_review(args.root, args.adapter, args.plan, args.request_id, args.pages)
        else:
            input_path = args.input.absolute()
            if ".." in input_path.parts or "\\" in str(input_path):
                raise FeedbackError("反馈文件须使用无父跳转的明确路径")
            raw, identity = snapshot(input_path)
            result = validate_feedback(args.root, args.adapter, parse_feedback(raw))
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
