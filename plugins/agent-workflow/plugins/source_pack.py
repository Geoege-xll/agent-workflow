#!/usr/bin/env python3
"""插件内源包的资源／原有 helper 入口；不安装、不登记，也不派发 Agent。"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import runpy
import sys


if sys.version_info < (3, 11):
    raise SystemExit("Python >= 3.11 is required; invoke this entry with the packaged lib/python_runtime.sh")


# 入口仅信任自身物理位置。宿主传入的环境变量不能把本次调用重定向到另一个
# 插件缓存；在 helper 子上下文中重新设置它，供共用精确内置资源读取器使用。
ROOT = Path(__file__).resolve().parents[1]
CENTRAL_ENV = (
    "AGENT_WORKFLOW_RUNTIME_BINDING", "AGENT_WORKFLOW_PROJECT_ROOT",
    "AGENT_WORKFLOW_CONFIG_PATH", "AGENT_WORKFLOW_CORE_ROOT",
)
HELPERS = frozenset({
    "lib/task_graph_cli.py", "lib/agent_continuation_cli.py", "lib/documents/context_read.py",
    "lib/dispatch_admission_cli.py",
    "lib/documents/validate_prototype_workspace.py",
    # 反馈 helper 仅输出只读链接/节点交接，不提供 HTML patch 或批准入口。
    "lib/documents/prototype_feedback_cli.py",
    "lib/validate_project_docs.py",
    "lib/project/validate_project_config.py", "lib/project/ensure_project_id.py",
    "lib/delivery/qa_handoff_cli.py", "lib/delivery/worktree_cli.py",
    "lib/delivery/native_usage.py",
    "plugins/project_context.py",
})


def _file(relative: str) -> Path:
    """只接受规范的包内路径；禁止软链、父目录跳转和跨源包读取。"""
    path = PurePosixPath(relative)
    if (not path.parts or path.is_absolute() or path.as_posix() != relative
            or ".." in path.parts or "\\" in relative):
        raise ValueError("resource must be a canonical plugin-relative path")
    candidate = ROOT / relative
    for parent in (candidate, *candidate.parents):
        if parent == ROOT:
            break
        if parent.is_symlink():
            raise ValueError("plugin resources must not use symlinks")
    if not candidate.is_file():
        raise ValueError("packaged resource is missing")
    return candidate


def _json(relative: str) -> dict:
    value = json.loads(_file(relative).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("package metadata must be a JSON object")
    return value


def verify() -> dict:
    """每次独立调用核对原样来源和装配结果；摘要只证明字节，不授予业务权限。"""
    source = _json("workflow-sources.json")
    metadata = _json("sources.json")
    if set(source) != {"schema_version", "files"} or source["schema_version"] != 1:
        raise ValueError("unsupported workflow-sources contract")
    if not isinstance(source["files"], dict) or not source["files"]:
        raise ValueError("workflow-sources files must be a nonempty object")
    for relative, expected in source["files"].items():
        if hashlib.sha256(_file(relative).read_bytes()).hexdigest() != expected:
            raise ValueError("canonical source digest mismatch: " + relative)
    for relative, expected in metadata["payload_sha256"].items():
        if hashlib.sha256(_file(relative).read_bytes()).hexdigest() != expected:
            raise ValueError("package payload digest mismatch: " + relative)
    return metadata


def _execution_context(project: Path | None) -> Path | None:
    """共享原有项目与旧中央拒绝边界；只读偏好也不能绕过当前物理源包。"""
    if any(name in os.environ for name in CENTRAL_ENV):
        raise ValueError("central bridge environment cannot be mixed with plugin source-pack execution")
    supplied = os.environ.get("AGENT_WORKFLOW_PLUGIN_ROOT")
    if supplied is not None and Path(supplied).resolve() != ROOT:
        raise ValueError("plugin root environment conflicts with this physical installation")
    if project is None:
        return None
    # 在 resolve 前检查所有祖先；否则祖先软链会被规范化抹去，使唯一 reader
    # 看见另一物理项目路径并错误命中该项目偏好，削弱既有物理目录边界。
    if (not project.is_absolute() or ".." in project.parts
            or any(node.is_symlink() for node in (project, *project.parents))):
        raise ValueError("project must be an existing physical absolute directory")
    project = project.resolve(strict=True)
    if not project.is_dir() or project == ROOT or ROOT in project.parents:
        raise ValueError("workflow project must be outside the installed plugin")
    marker = project / ".agent-workflow/runtime.json"
    if marker.exists() or marker.is_symlink():
        raise ValueError("central project tasks must stay with their original pinned runtime")
    return project


def _dispatch_preferences(args) -> int:
    """只选择固定同源入口，不解析或重写偏好，且不加载服务、启动器或安装器。"""
    # 已安装包必须完整验证摘要；源码开发只使用自身物理根中的唯一纯合同。任何
    # 元数据残缺仍进入 verify 并拒绝，不能借删除一份元数据退回源码模式。
    if any((ROOT / name).exists() or (ROOT / name).is_symlink()
           for name in ("workflow-sources.json", "sources.json")):
        verify()
        entry = _file("plugins/dispatch_preferences.py")
    else:
        entry = _file("native_config/preference_contract.py")
    project = _execution_context(args.project)
    arguments = ["--host", args.host, "--agent", args.agent]
    if project is not None:
        arguments.extend(("--project", str(project)))
    if args.home is not None:
        arguments.extend(("--home", str(args.home)))
    # run_path 不导入 native_config/__init__，避免源码模式碰巧加载服务依赖；
    # reader 本身的 main 返回固定八字段或脱敏失败，保持原始退出码与语义。
    sys.dont_write_bytecode = True
    return runpy.run_path(str(entry))["main"](arguments)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    resource = commands.add_parser("resource", help="locate a verified packaged resource")
    resource.add_argument("path")
    helper = commands.add_parser("helper", help="execute an original packaged workflow helper")
    helper.add_argument("--project", required=True, type=Path)
    helper.add_argument("path", choices=sorted(HELPERS))
    helper.add_argument("arguments", nargs=argparse.REMAINDER)
    preferences = commands.add_parser("dispatch-preferences", help="read logical native dispatch preferences without starting a service")
    preferences.add_argument("--host", choices=("codex", "claude", "antigravity"), required=True)
    preferences.add_argument("--agent", required=True)
    preferences.add_argument("--project", type=Path)
    preferences.add_argument("--home", type=Path)
    args = parser.parse_args(argv)
    try:
        if args.command == "dispatch-preferences":
            return _dispatch_preferences(args)
        metadata = verify()
        if args.command == "resource":
            # 历史受管路径只是只读逻辑别名；项目适配器绝不走这条映射。
            relative = args.path.removeprefix(".agent-workflow/")
            if relative not in _json("workflow-sources.json")["files"]:
                raise ValueError("resource is not an original packaged source")
            path = _file(relative)
            print(json.dumps({"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                              "plugin_version": metadata["plugin_version"], "runtime_verified": False}))
            return 0
        project = _execution_context(args.project)
        # 不改变旧中央变量或猜测 HOME。项目 cwd、插件根和当前参数在这一次进程
        # 内同时确定；原 CLI 自己继续校验 Task Pack、门禁、规范和写入授权。
        os.environ["AGENT_WORKFLOW_PLUGIN_ROOT"] = str(ROOT)
        os.environ["PYTHONDONTWRITEBYTECODE"] = "1"
        sys.dont_write_bytecode = True
        os.chdir(project)
        sys.path.insert(0, str(ROOT))
        sys.argv = [str(_file(args.path)), *args.arguments]
        # 以原包名运行，保留lib内部相对导入。run_path不会像真正脚本进程那样
        # 加入脚本目录，容易误入旧平铺import分支；模块入口保持原有包语义。
        runpy.run_module(args.path[:-3].replace("/", "."), run_name="__main__", alter_sys=True)
        return 0
    except (ValueError, OSError, KeyError) as exc:
        print("[ERROR] " + str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
