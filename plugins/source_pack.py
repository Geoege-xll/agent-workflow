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
    "lib/documents/requirement_html.py",
    "lib/documents/validate_prototype_workspace.py",
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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    resource = commands.add_parser("resource", help="locate a verified packaged resource")
    resource.add_argument("path")
    helper = commands.add_parser("helper", help="execute an original packaged workflow helper")
    helper.add_argument("--project", required=True, type=Path)
    helper.add_argument("path", choices=sorted(HELPERS))
    helper.add_argument("arguments", nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)
    try:
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
        project = args.project
        if not project.is_absolute() or ".." in project.parts or project.is_symlink():
            raise ValueError("project must be an existing physical absolute directory")
        project = project.resolve(strict=True)
        if not project.is_dir() or project == ROOT or ROOT in project.parents:
            raise ValueError("workflow project must be outside the installed plugin")
        if any(name in os.environ for name in CENTRAL_ENV):
            raise ValueError("central bridge environment cannot be mixed with plugin source-pack execution")
        marker = project / ".agent-workflow/runtime.json"
        if marker.exists() or marker.is_symlink():
            raise ValueError("central project tasks must stay with their original pinned runtime")
        supplied = os.environ.get("AGENT_WORKFLOW_PLUGIN_ROOT")
        if supplied is not None and Path(supplied).resolve() != ROOT:
            raise ValueError("plugin root environment conflicts with this physical installation")
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
