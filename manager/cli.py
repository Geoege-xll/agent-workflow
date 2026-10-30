"""管理器命令入口；默认启动 TUI，脚本模式中的写操作均显式要求 --apply。"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys

from .catalog import clean, discover
from . import service


def parser() -> argparse.ArgumentParser:
    root=argparse.ArgumentParser(prog="awf-cli",description="工作流项目与角色模型管理，不改变原有编排。")
    root.add_argument("--state-dir",help="独立管理状态目录；默认 ~/.config/agent-workflow")
    root.add_argument("--scan-root",default=str(Path.home()/"Desktop"),help="只扫描该目录的直接子项目")
    commands=root.add_subparsers(dest="command")
    tui=commands.add_parser("tui",help="启动终端界面（默认命令）")
    tui.add_argument("--project",help="初始选中项目")
    project=commands.add_parser("projects",help="列出或登记项目")
    project.add_argument("action",choices=["list","add","remove"],default="list",nargs="?")
    project.add_argument("path",nargs="?")
    model=commands.add_parser("models",help="只读查看本地模型目录及来源")
    model.add_argument("--platform",choices=service.LOCATIONS,required=True)
    model.add_argument("--project")
    roles=commands.add_parser("roles",help="只读查看项目已安装角色的当前模型")
    roles.add_argument("--project",required=True)
    roles.add_argument("--platform",choices=service.LOCATIONS,required=True)
    change=commands.add_parser("set",help="预览或应用一个角色的模型设置")
    change.add_argument("--project",required=True)
    change.add_argument("--platform",choices=service.LOCATIONS,required=True)
    change.add_argument("--role",required=True)
    change.add_argument("--model",required=True)
    change.add_argument("--effort",default="inherit")
    change.add_argument("--apply",action="store_true",help="确认先备份，再写入并检查目标平台")
    for name in ("install","check","backups","restore"):
        command=commands.add_parser(name,help={"install":"预览或执行安装升级","check":"只读检查三平台安装","backups":"列出模型配置备份","restore":"预览或恢复模型配置备份"}[name])
        command.add_argument("--project",required=True)
        if name == "restore":command.add_argument("backup")
        if name in {"install","restore"}:command.add_argument("--apply",action="store_true")
    return root


def main(argv: list[str] | None = None) -> int:
    # 启动器为模块导入切换到源包；用户传入的相对项目路径仍以原调用目录解释。
    caller=os.environ.pop("AGENT_WORKFLOW_CALLER_DIR",None)
    if caller:os.chdir(caller)
    args=parser().parse_args(argv)
    state=service.state_root(args.state_dir)
    scan=Path(args.scan_root).expanduser()
    try:
        if args.command in {None,"tui"}:
            if not sys.stdin.isatty() or not sys.stdout.isatty():
                raise ValueError("TUI 需要交互终端。可使用 --help、projects list 或 models 等无交互命令。")
            from .tui import run
            project=service.project_path(args.project) if getattr(args,"project",None) else None
            return run(state,scan,project)
        if args.command == "projects":
            if args.action != "list":
                if not args.path:raise ValueError("请提供项目路径")
                service.register(state,service.project_path(args.path),remove=args.action == "remove")
            print(json.dumps([str(path) for path in service.projects(state,scan)],ensure_ascii=False,indent=2))
            return 0
        project=service.project_path(args.project) if args.project else None
        if args.command == "models":
            print(json.dumps(discover(args.platform,project=project).as_dict(),ensure_ascii=False,indent=2))
        elif args.command == "roles":
            print(json.dumps({role:service.role_settings(project,args.platform,role) for role in service.roles(project,args.platform)},ensure_ascii=False,indent=2))
        elif args.command == "set":
            catalog=discover(args.platform,project=project)
            changes=service.prepare(project,args.platform,{args.role:{"model":args.model,"effort":args.effort}},catalog)
            print(f"项目：{clean(project)}\n平台：{args.platform}\n角色：{args.role}\n模型：{clean(args.model)}\n推理：{args.effort}")
            print("变更文件："+", ".join(row.relative for row in changes))
            if args.apply:
                identifier=service.commit(state,project,changes,lambda:service.check(project,args.platform),
                                          before_write=lambda:service.ensure_source(catalog,project))
                print("已应用；"+service.backup_summary(project,identifier))
            else:print("只读预览；添加 --apply 才会备份并写入。")
        elif args.command == "install":
            print(service.install_preview(project))
            if args.apply:
                with service.lock(state,str(project)):
                    print(service.install(project))
                service.register(state,project)
            else:print("添加 --apply 确认安装或升级。")
        elif args.command == "check":print(service.check(project))
        elif args.command == "backups":print(json.dumps(service.backups(state,project),ensure_ascii=False,indent=2))
        elif args.command == "restore":
            changes=service.prepare_restore(state,project,args.backup)
            print("恢复文件："+", ".join(row.relative for row in changes))
            if args.apply:
                identifier=service.commit(state,project,changes,lambda:check_changed_hosts(project,changes))
                print("恢复完成；"+service.backup_summary(project,identifier))
            else:print("只读预览；添加 --apply 才执行恢复。")
        return 0
    except KeyboardInterrupt:
        print("\n已取消。",file=sys.stderr);return 130
    except (OSError,ValueError,KeyError,TypeError,subprocess.TimeoutExpired) as exc:
        print("[错误] "+clean(str(exc),6000),file=sys.stderr);return 2


def check_changed_hosts(project: Path,changes) -> None:
    hosts={host for host,(directory,_) in service.LOCATIONS.items() if any(row.relative.startswith(directory+"/") for row in changes)}
    for host in sorted(hosts):service.check(project,host)


if __name__ == "__main__":
    raise SystemExit(main())
