"""中央运行时统一命令入口；项目直接动词与模型显式 --apply 共享业务服务。"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys

from .catalog import clean, discover
from . import model_preferences, release, service


class CommandParser(argparse.ArgumentParser):
    """参数拒绝也走同一错误出口，使 --json 不被 argparse 的原始文本打断。"""
    def error(self, message):
        raise ValueError("命令参数无效：" + message)


def output_options(command, *, dry_run=False):
    # 子命令使用 SUPPRESS，避免覆盖放在全局位置的 --json。
    command.add_argument("--json", action="store_true", default=argparse.SUPPRESS,
                         help="stdout 仅输出稳定 JSON；拒绝退出 2，取消退出 130")
    if dry_run:
        command.add_argument("--dry-run", action="store_true", help="完全只读预览，不创建项目、登记或中央状态")


def parser() -> argparse.ArgumentParser:
    root=CommandParser(prog="awf-cli",description="中央工作流项目、固定版本与角色模型管理。项目参数只接受已存在路径或唯一登记名。")
    root.add_argument("--version",action="store_true",help="只读显示产品版本及源码/构建性质，以及实际中央源根")
    root.add_argument("--state-dir",help="独立管理状态目录；默认 ~/.config/agent-workflow")
    root.add_argument("--scan-root",default=str(Path.home()/"Desktop"),help="只扫描该目录的直接子项目")
    root.add_argument("--json",action="store_true",help="机器输出模式；--state-dir 等全局参数放在命令之前")
    commands=root.add_subparsers(dest="command")
    tui=commands.add_parser("tui",help="启动终端界面（默认命令）")
    tui.add_argument("--project",help="初始选中项目")
    for name in ("add", "del", "list", "status", "enable", "disable", "use", "rollback", "repair"):
        aliases={"enable":["open"], "disable":["close"]}.get(name, [])
        command=commands.add_parser(name, aliases=aliases, help={
            "add":"登记已存在目录；--enable 同时启用", "del":"先停用，再解除登记；保留全部项目文件",
            "list":"只读列出项目实际状态、固定版本、宿主和冲突", "status":"只读查看一个项目，省略项目则列出全部",
            "enable":"启用项目原生入口；已绑定项目默认保留当前版", "disable":"停用新任务入口；保留旧任务 pin",
            "use":"切到完整且已验证的中央内容 ID", "rollback":"切回项目已验证的前次版本",
            "repair":"条件恢复未完成事务或缺失受管资源，拒绝未知手改"}[name])
        if name != "list":
            command.add_argument("project", nargs="?" if name == "status" else None,
                                 help="已存在项目目录或唯一登记名称")
        if name == "add":command.add_argument("--enable", action="store_true", help="登记时启用中央原生入口")
        if name in {"add", "enable"}:
            source=command.add_mutually_exclusive_group()
            source.add_argument("--source", type=Path, help="显式导入该来源；首次启用默认当前中央源码")
            source.add_argument("--content-id", help="精确选择已导入的完整 SHA256 内容 ID")
        if name == "use":command.add_argument("content_id", help="完整 64 位小写 SHA256；不接受前缀或 latest")
        output_options(command, dry_run=name not in {"list", "status"})
    runtime=commands.add_parser("runtime",help="管理不可变中央核心；不会自动切换或清理项目版本")
    output_options(runtime)
    runtimes=runtime.add_subparsers(dest="runtime_action",required=True)
    runtime_list=runtimes.add_parser("list",help="只读列出已验证固定核心")
    output_options(runtime_list)
    runtime_install=runtimes.add_parser("install",help="只向中央库导入核心，不修改项目")
    runtime_install.add_argument("source",nargs="?",type=Path,default=service.SOURCE,help="来源目录，默认当前中央源码")
    output_options(runtime_install,dry_run=True)
    model=commands.add_parser("models",help="只读查看本地模型目录及来源")
    model.add_argument("--platform",choices=service.LOCATIONS,required=True)
    model.add_argument("--project")
    output_options(model)
    roles=commands.add_parser("roles",help="只读查看项目覆盖或全局角色默认及字段来源")
    scope=roles.add_mutually_exclusive_group(required=True)
    scope.add_argument("--project")
    scope.add_argument("--global",dest="global_scope",action="store_true",help="查看用户级工作流角色默认")
    roles.add_argument("--platform",choices=service.LOCATIONS,required=True)
    roles.add_argument("--effective",action="store_true",help="显示 Claude 具名角色的已知配置覆盖关系；不冒充运行时实测")
    output_options(roles)
    doctor=commands.add_parser("doctor",help="只读查看三宿主文档能力、来源观察与运行未验证边界")
    doctor.add_argument("--platform",choices=(*service.LOCATIONS,"all"),default="all")
    doctor.add_argument("--project",help="检查此项目配置；AGY 仅额外读取明确的 grill-me 技能路径，不扫描个人技能目录")
    doctor.add_argument("--probe",action="store_true",help="显式执行宿主 --version；不登录、不调用模型、不修改配置")
    output_options(doctor)
    change=commands.add_parser("set",help="预览或应用一个角色的模型设置")
    scope=change.add_mutually_exclusive_group(required=True)
    scope.add_argument("--project")
    scope.add_argument("--global",dest="global_scope",action="store_true",help="编辑用户级工作流角色默认")
    change.add_argument("--platform",choices=service.LOCATIONS,required=True)
    change.add_argument("--role",required=True)
    change.add_argument("--model")
    change.add_argument("--effort")
    change.add_argument("--reset",choices=("model","effort","all"),help="清除对应范围覆盖；项目恢复跟随全局，全局恢复宿主")
    change.add_argument("--apply",action="store_true",help="确认先备份，再写入并检查目标平台")
    output_options(change)
    for name in ("check","backups","restore"):
        command=commands.add_parser(name,help={"check":"只读检查三平台安装","backups":"列出模型配置备份","restore":"预览或恢复模型配置备份"}[name])
        command.add_argument("--project",required=True)
        if name == "restore":command.add_argument("backup")
        if name == "restore":command.add_argument("--apply",action="store_true")
        output_options(command)
    return root


def print_result(command: str, result, *, json_mode: bool, dry_run=False) -> None:
    """新命令固定信封；文本仅投影摘要，原文、凭据及计划前后像不进入输出。"""
    if json_mode:
        print(json.dumps({"schema_version": 1, "command": command, "dry_run": dry_run,
                          "result": result},ensure_ascii=False,indent=2))
        return
    rows=result if isinstance(result,list) else [result]
    if not rows:
        print("无记录。")
    for row in rows:
        if isinstance(row,str):
            print(clean(row,8192));continue
        if "project" not in row:
            print(json.dumps(row,ensure_ascii=False,indent=2));continue
        binding=row.get("runtime_binding") or (row.get("runtime") or {}).get("runtime_binding")
        previous=row.get("previous_binding") or (row.get("runtime") or {}).get("previous_binding")
        phase=row.get("state") or (row.get("status_before") or {}).get("state", "unmanaged")
        hosts=row.get("hosts") or (row.get("runtime") or {}).get("hosts",[])
        print(f"项目：{clean(row['project'])}\n状态：{phase}；宿主：{', '.join(hosts) or '无'}")
        print("固定内容 ID："+(binding["content_id"] if binding else "无"))
        print("前次内容 ID："+(previous["content_id"] if previous else "无"))
        if "registered" in row:print("已登记："+("是" if row["registered"] else "否"))
        if "registered_after" in row:print("登记前后："+str(row["registered_before"])+" → "+str(row["registered_after"]))
        if dry_run:print(f"只读预览；可应用：{row.get('can_apply',True)}；受管变更：{len(row.get('changes',[]))} 项")
        for conflict in row.get("conflicts",[]):
            print("冲突："+clean(conflict["path"])+"；"+clean(conflict["reason"]))


def project_command(args, state: Path, scan: Path) -> int | None:
    """把命令参数映射到共享服务；此层不自行拼接登记/停用或安装事务。"""
    action={"open":"enable", "close":"disable"}.get(args.command,args.command)
    if action in {"list", "status"}:
        result=(service.project_status(state,service.resolve_project(state,args.project))
                if action == "status" and args.project else service.project_summaries(state,scan))
        print_result(args.command,result,json_mode=args.json)
        return 0
    if action == "runtime":
        from lib import runtime_store
        if args.runtime_action == "list":
            result=runtime_store.list_cores(state)
        else:
            inspected=runtime_store.inspect_core(args.source)
            binding={key:inspected[key] for key in ("protocol_version","content_id","manifest_sha256")}
            result={"state_dir":str(state),"runtime_binding":binding,"label":inspected["label"]}
            if not args.dry_run:
                core=runtime_store.import_core(args.source,state,expected_binding=binding)
                result.update(root=str(core.root))
        print_result("runtime "+args.runtime_action,result,json_mode=args.json,dry_run=getattr(args,"dry_run",False))
        return 0
    if action not in {"add", "del", "enable", "disable", "use", "rollback", "repair"}:
        return None
    project=(service.project_path(args.project) if action == "add" else service.resolve_project(state,args.project))
    plan=service.preview_project(state,project,action,enable=getattr(args,"enable",False),
                                 source_root=getattr(args,"source",None), content_id=getattr(args,"content_id",None))
    result=plan.summary if args.dry_run else service.apply_project(plan)
    print_result(args.command,result,json_mode=args.json,dry_run=args.dry_run)
    # 预览冲突仍是业务拒绝，调用方不能把不可应用计划误判为成功。
    return 0 if plan.summary["can_apply"] else 2


def main(argv: list[str] | None = None) -> int:
    # 启动器为模块导入切换到源包；用户传入的相对项目路径仍以原调用目录解释。
    caller=os.environ.pop("AGENT_WORKFLOW_CALLER_DIR",None)
    if caller:os.chdir(caller)
    arguments=list(sys.argv[1:] if argv is None else argv)
    json_mode="--json" in arguments
    try:
        args=parser().parse_args(arguments)
        json_mode=args.json
        # 版本诊断不启动 curses、不读取宿主配置，也不创建管理状态；坏元数据仍走 CLI 错误出口。
        if args.version:
            if json_mode:print_result("version",{"description":release.describe()},json_mode=True)
            else:print(release.describe())
            return 0
        state=service.state_root(args.state_dir)
        scan=Path(args.scan_root).expanduser()
        if args.command in {None,"tui"}:
            if json_mode:raise ValueError("TUI 交互输出不支持 --json，请使用无交互命令")
            if not sys.stdin.isatty() or not sys.stdout.isatty():
                raise ValueError("TUI 需要交互终端。可使用 --help、list 或 models 等无交互命令。")
            from .tui import run
            project=service.project_path(args.project) if getattr(args,"project",None) else None
            return run(state,scan,project)
        direct=project_command(args,state,scan)
        if direct is not None:return direct
        project=service.resolve_project(state,args.project) if args.project else None
        if args.command == "models":
            print(json.dumps(discover(args.platform,project=project).as_dict(),ensure_ascii=False,indent=2))
        elif args.command == "roles":
            values={role:model_preferences.view(state,project,args.platform,role)
                    for role in model_preferences.roles(state,project,args.platform)}
            if args.effective:
                if args.platform != "claude" or project is None:raise ValueError("--effective 当前只解析项目 Claude 的具名非 fork 角色")
                from .claude_execution import effective_role
                from lib.claude_options import frontmatter_window
                catalog=discover("claude",project=project)
                if catalog.execution.get("status") != "projected":
                    raise ValueError("Claude 配置来源读取失败，无法推导有效角色设置；请用 doctor 检查来源")
                controls=catalog.execution["controls"]
                # 诊断读取已安装原生角色；不将模型事务的可写范围扩展到窗口或权限字段。
                values={role:effective_role(service.role_settings(project,"claude",role),controls,frontmatter_window(service.read_file(service.role_path(project,"claude",role))))
                        for role,value in values.items()}
            print(json.dumps(values,ensure_ascii=False,indent=2))
        elif args.command == "doctor":
            from .capabilities import diagnose
            hosts=service.LOCATIONS if args.platform == "all" else (args.platform,)
            print(json.dumps([diagnose(host,project=project,probe=args.probe) for host in hosts],ensure_ascii=False,indent=2))
        elif args.command == "set":
            # CLI 只映射本次实际编辑字段；缺省参数不能暗中变成另一字段的 inherit
            # 覆盖。reset 与同字段赋值互斥，跨字段的修改与恢复可在一次事务完成。
            fields={field:getattr(args,field) for field in ("model","effort") if getattr(args,field) is not None}
            resets=("model","effort") if args.reset == "all" else (args.reset,) if args.reset else ()
            if set(fields)&set(resets):raise ValueError("同一字段不能同时赋值与 reset")
            fields.update({field:None for field in resets})
            if not fields:raise ValueError("set 至少需要 --model、--effort 或 --reset")
            catalog=model_preferences.load_catalogs(state,project,args.platform)
            plan=model_preferences.preview(state,project,args.platform,{args.role:fields},catalog)
            # 保留既有 set 的 model/effort 结果字段；现在取计划解析后的有效值，
            # 既不把缺省参数写成覆盖，也不让旧 JSON 消费者丢失原有字段。
            result={**plan.summary,**plan.summary["values"][args.role],"role":args.role,"applied":False,
                    "changed_paths":plan.changed_paths}
            identifier=None
            if args.apply:
                result.update(model_preferences.apply(plan))
                identifier=result["backup_id"]
            if json_mode:print_result("set",result,json_mode=True,dry_run=not args.apply)
            else:
                print(json.dumps(result,ensure_ascii=False,indent=2))
                print(result.get("diagnostic","已应用。") if args.apply else "只读预览；添加 --apply 才会备份并写入。")
            return 0 if plan.summary["can_apply"] else 2
        elif args.command == "check":
            result=service.check(project,state=state)
            if json_mode:print_result("check",{"project":str(project),"diagnostic":result},json_mode=True)
            else:print(result)
        elif args.command == "backups":print(json.dumps(service.backups(state,project),ensure_ascii=False,indent=2))
        elif args.command == "restore":
            changes=service.prepare_restore(state,project,args.backup)
            if args.apply:
                identifier=service.commit(state,project,changes,lambda:check_changed_hosts(project,changes,state=state))
            if json_mode:
                print_result("restore",{"project":str(project),"changed_paths":[row.relative for row in changes],
                                         "applied":args.apply,"backup_id":identifier if args.apply else None},
                             json_mode=True,dry_run=not args.apply)
            else:
                print("恢复文件："+", ".join(row.relative for row in changes))
                print("恢复完成；"+service.backup_summary(project,identifier) if args.apply else "只读预览；添加 --apply 才执行恢复。")
        return 0
    except KeyboardInterrupt:
        if json_mode:
            print(json.dumps({"schema_version":1,"error":{"code":"cancelled","message":"操作已取消，已等待当前事务结算。"}},ensure_ascii=False))
        else:print("\n已取消。",file=sys.stderr)
        return 130
    except (OSError,ValueError,KeyError,TypeError,RecursionError,subprocess.TimeoutExpired) as exc:
        if json_mode:
            # 配置解析异常可能携带原始秘密。JSON 只投影固定诊断；名称解析例外
            # 明确仅含路径候选，原生 ActivationError 的 conflicts 按公开安全合同传递。
            error={"code":"operation_refused","message":"操作被拒绝，请检查参数、项目状态或固定版本。"}
            if isinstance(exc,service.ProjectResolutionError):
                error.update(code="project_resolution",message=clean(str(exc),6000),candidates=list(exc.candidates))
            if isinstance(exc,service.runtime_service.ActivationError):
                error["conflicts"]=list(exc.conflicts)
            print(json.dumps({"schema_version":1,"error":error},ensure_ascii=False,indent=2))
        else:
            print("[错误] "+clean(str(exc),6000),file=sys.stderr)
            if isinstance(exc,service.runtime_service.ActivationError):
                for conflict in exc.conflicts:
                    print("冲突："+clean(conflict["path"])+"；"+clean(conflict["reason"]),file=sys.stderr)
        return 2


def check_changed_hosts(project: Path,changes,*,state: Path | None = None) -> None:
    hosts={host for host,(directory,_) in service.LOCATIONS.items() if any(row.relative.startswith(directory+"/") for row in changes)}
    for host in sorted(hosts):service.check(project,host,state=state)


if __name__ == "__main__":
    raise SystemExit(main())
