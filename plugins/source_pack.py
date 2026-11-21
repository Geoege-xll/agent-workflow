#!/usr/bin/env python3
"""插件内源包的资源／原有 helper 入口；不安装、不登记，也不派发 Agent。"""

from __future__ import annotations

import argparse
from collections.abc import Callable
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import runpy
import stat
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
    # PM 从任务池恢复已登记的原记录，再沿既有准入和更新流程执行；只开放命令入口。
    "lib/dispatch_admission_cli.py", "lib/task_pool_cli.py",
    "lib/documents/validate_prototype_workspace.py",
    # 同一个反馈 CLI 提供显式项目的 prepare-delivery/open/status/stop 与历史 prepare/validate。
    # prepare-delivery 仅准备受管文件入口；open 验证准备后登记已允许源并启动本机受限服务，
    # 二者均不接受网页任意 root/argv/file；
    # 白名单不授予项目写权限、HTML patch 批准或系统自启动权限。
    "lib/documents/prototype_feedback_cli.py",
    "lib/validate_project_docs.py",
    "lib/project/validate_project_config.py", "lib/project/ensure_project_id.py",
    "lib/delivery/qa_handoff_cli.py", "lib/delivery/worktree_cli.py",
    "lib/delivery/native_usage.py", "lib/hosts/capabilities.py", "lib/project/project_profile_cli.py",
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


def _canonical_manifest_files(source: dict) -> dict:
    if not isinstance(source, dict) or set(source) != {"schema_version", "files"} or source["schema_version"] != 1:
        raise ValueError("unsupported workflow-sources contract")
    if not isinstance(source["files"], dict) or not source["files"]:
        raise ValueError("workflow-sources files must be a nonempty object")
    return source["files"]


def _selected_bootstrap_bytes(relative: str) -> bytes:
    """只读固定的发行清单或 Python 源文件，供导入精选读取器之前的来源校验。"""
    # 此处不能依赖尚未校验的 selected_skills.read_regular。沿用包路径边界，
    # 在同一打开文件上拒绝软硬链接、特殊节点和超额内容，避免预检触发挂起或外部读取。
    budget = 16 * 1024 * 1024
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
    with os.fdopen(os.open(_file(relative), flags), "rb") as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise ValueError("selected skill bootstrap source must be a single-link regular file: " + relative)
        if info.st_size > budget:
            raise ValueError("selected skill bootstrap source exceeds read budget: " + relative)
        body = stream.read(budget + 1)
        if len(body) > budget:
            raise ValueError("selected skill bootstrap source exceeds read budget: " + relative)
        return body


def _selected_read_verifier() -> Callable[[str, str], None]:
    """先验证会执行的读取与身份来源，再返回供本页核对锁和目标的摘要校验器。"""

    def unique_object(pairs: list[tuple[str, object]]) -> dict:
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate package provenance key: " + key)
            result[key] = value
        return result

    source = json.loads(_selected_bootstrap_bytes("workflow-sources.json"), object_pairs_hook=unique_object)
    metadata = json.loads(_selected_bootstrap_bytes("sources.json"), object_pairs_hook=unique_object)
    workflow_files = _canonical_manifest_files(source)
    if (not isinstance(metadata, dict) or type(metadata.get("schema_version")) is not int
            or metadata["schema_version"] != 1 or metadata.get("product") != "workflow-core"
            or metadata.get("host") not in ("codex", "claude", "antigravity")
            or any(not isinstance(metadata.get(key), dict) for key in ("source_files", "payload_sha256"))):
        raise ValueError("unsupported selected skill package provenance")

    def verify_digest(relative: str, digest: str) -> None:
        # 必须同时出现在原样来源、来源记录和实际载荷。缺项也视为来源不匹配，
        # 锁与正文校验从读取器传回同一批字节的摘要，避免再次打开文件或混入替换版本。
        if any(records.get(relative) != digest for records in
               (workflow_files, metadata["source_files"], metadata["payload_sha256"])):
            raise ValueError("selected skill package source digest mismatch: " + relative)

    # 包初始化与身份声明也是实际导入闭包的一部分。必须在第一次导入产品模块或
    # 读取器之前核验，避免篡改的别名模块将合法的 xy-impeccable 解析为另一篇合法正文。
    for relative in ("plugins/source_pack.py", "lib/__init__.py", "lib/skills/__init__.py",
                     "lib/skills/selected_skills.py", "lib/skills/role_skills.py", "product/__init__.py",
                     "product/command_identity.py", "product/command_identity.json"):
        verify_digest(relative, hashlib.sha256(_selected_bootstrap_bytes(relative)).hexdigest())
    from product.command_identity import load_identity
    if metadata.get("plugin_name") != load_identity(ROOT)["plugin_name"]:
        raise ValueError("unsupported selected skill package provenance")
    return verify_digest


def verify() -> dict:
    """每次独立调用核对原样来源和装配结果；摘要只证明字节，不授予业务权限。"""
    source = _json("workflow-sources.json")
    metadata = _json("sources.json")
    payload = metadata.get("payload_sha256")
    if not isinstance(payload, dict):
        raise ValueError("unsupported package payload provenance")
    for relative, expected in _canonical_manifest_files(source).items():
        if hashlib.sha256(_file(relative).read_bytes()).hexdigest() != expected:
            raise ValueError("canonical source digest mismatch: " + relative)
    for relative, expected in payload.items():
        if hashlib.sha256(_file(relative).read_bytes()).hexdigest() != expected:
            raise ValueError("package payload digest mismatch: " + relative)
    # 发行摘要不能代替外部依赖闭包：额外文件、链接与错误声明同样拒绝。
    sys.path.insert(0, str(ROOT))
    from lib.hosts.factory import packaged_host
    from lib.skills.selected_skills import snapshot
    packaged_host(ROOT, provenance=metadata)
    snapshot(ROOT)
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
    sys.path.insert(0, str(ROOT))
    argv = sys.argv[1:] if argv is None else argv
    try:
        # 本命令无需从未经验证的身份模块解析 Playwright 命令名。先绑定分页实际
        # 使用的来源，其他子命令继续走原有解析和全量验证入口。
        if argv[:2] == ["selected-skills", "read"]:
            verify_source = _selected_read_verifier()
            from lib.skills.selected_skills import main as selected_main
            return selected_main(argv[1:], root=ROOT, verify_source=verify_source)
        from product.command_identity import load_identity
        identity = load_identity(ROOT)
        playwright_command = next(name for name, original in identity["skill_aliases"].items() if original == "playwright-cli")
    except (ValueError, OSError, StopIteration) as exc:
        print("[ERROR] " + str(exc), file=sys.stderr)
        return 2
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    resource = commands.add_parser("resource", help="locate a verified packaged resource")
    resource.add_argument("path")
    selected = commands.add_parser("selected-skills", help="check, diagnose or read the bundled original selected skills")
    selected.add_argument("arguments", nargs=argparse.REMAINDER)
    playwright = commands.add_parser(playwright_command, help="run the fixed bundled Playwright CLI; doctor reports readiness")
    playwright.add_argument("arguments", nargs=argparse.REMAINDER)
    web = commands.add_parser("xy-web-guidance", help="query the fixed official local modern Web package")
    web.add_argument("arguments", nargs=argparse.REMAINDER)
    apple = commands.add_parser("apple-skills", help="check/read local Xcode original SwiftUI guidance without launching Xcode")
    apple.add_argument("arguments", nargs=argparse.REMAINDER)
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
        if args.command == "selected-skills":
            verify()
            from lib.skills.selected_skills import main as selected_main
            return selected_main(args.arguments, root=ROOT)
        metadata = verify()
        if args.command == "xy-web-guidance":
            from lib.skills.modern_web_runtime import run as web_run
            return web_run(args.arguments, root=ROOT)
        if args.command == "apple-skills":
            from lib.skills.apple_guidance import main as apple_main
            return apple_main(args.arguments)
        if args.command == playwright_command:
            from lib.skills.playwright_runtime import run as playwright_run
            return playwright_run(args.arguments, root=ROOT)
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
