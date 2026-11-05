#!/usr/bin/env python3
"""公共中央安装入口，以及旧自包含安装的受管校验、归档和恢复所有者。"""

from __future__ import annotations

import argparse
from contextlib import nullcontext
import hashlib
import json
if __package__:
    from .platform_fs import os, project_install_lock, publish_exclusive
    from .platform_process import setup_command
else:
    from platform_fs import os, project_install_lock, publish_exclusive
    from platform_process import setup_command
from pathlib import Path
import re
import shlex
import shutil
import stat
import subprocess
import sys
import tempfile
import time
import uuid

# CLI 直接执行与测试按包导入使用同一入口读写逻辑，避免恢复路径另造安全规则。
if __package__:
    from .claude_instructions import CLAUDE_IMPORT, atomic_write, read_file
    from .validate_project_config import parse_project_name, strip_inline_comment, validate_with_profile
    from .workflow_hook_install import plan_hooks
    from .standards_baseline import plan_standard_updates, remove_created_standard
    from .validate_project_docs import parse_docs
    from .install_process import ACTIVE_RUNNER, SetupRunner, SetupRunError
else:
    from claude_instructions import CLAUDE_IMPORT, atomic_write, read_file
    from validate_project_config import parse_project_name, strip_inline_comment, validate_with_profile
    from workflow_hook_install import plan_hooks
    from standards_baseline import plan_standard_updates, remove_created_standard
    from validate_project_docs import parse_docs
    from install_process import ACTIVE_RUNNER, SetupRunner, SetupRunError


RUNTIME_NAME = ".agent-workflow"
MANIFEST_NAME = ".install-manifest.json"
PACK_FILES = (
    "setup_all.sh",
    "setup_claude.sh",
    "setup_codex.sh",
    "setup_antigravity.sh",
    "project.yaml",
)
PACK_DIRECTORIES = ("product", "roles", "platforms", "lib", "scripts", "templates")


class InstallError(Exception):
    """安装前置条件或受管运行时校验失败。"""


def _central_imports():
    """脚本入口只加入安装器自身可信根，不从当前业务目录导入同名模块。"""
    root = str(Path(__file__).resolve().parents[1])
    if root not in sys.path:
        sys.path.insert(0, root)
    from lib import runtime_project
    return runtime_project


def legacy_tree_snapshot(root: Path) -> dict:
    """完整、有界地指纹目录及所有普通文件，归档靠 rename 保留 inode 而非复制。

    这里不使用 rglob/resolve 跟随链接；每个文件和目录都经已锚定父描述符。
    摘要不保存旧核心正文，恢复所需的原 inode 仍在同文件系统归档中。
    """
    runtime = _central_imports()
    rows = {}
    with runtime.Tree(root) as tree:
        def visit(relative):
            directory = tree.directory(relative)
            info = os.fstat(directory)
            rows[relative] = {"kind": "directory", "identity": list(runtime.identity(info))}
            for name in sorted(os.listdir(directory)):
                child = relative + "/" + name if relative else name
                runtime.relative_path(child)
                if len(rows) >= 10000 or len(Path(child).parts) > 32:
                    raise InstallError("旧运行时目录超过有界迁移指纹范围")
                info = os.stat(name, dir_fd=directory, follow_symlinks=False)
                if stat.S_ISDIR(info.st_mode):
                    visit(child)
                else:
                    node = tree.read(child)
                    rows[child] = {"kind": "file", "identity": list(node.identity),
                                   "sha256": hashlib.sha256(node.payload).hexdigest()}
        visit("")
    return rows


def _capture_legacy(command: list[str], *, env: dict | None = None, body: bytes | None = None):
    """复用原安装器进程组回收边界，纯渲染也必须有有限超时和中断传播。"""
    runner = ACTIVE_RUNNER.get()
    remaining = 60.0 if runner is None or runner.deadline is None else min(60.0, runner.deadline - time.monotonic())
    if remaining <= 0:
        raise SetupRunError("安装预算已耗尽，未启动下一纯读取阶段")
    env = dict(os.environ) if env is None else dict(env)
    for key in ("BASH_ENV", "ENV", "CDPATH", "SHELLOPTS", "BASHOPTS"):
        env.pop(key, None)
    process = subprocess.Popen(command, env=env, stdin=subprocess.PIPE if body is not None else subprocess.DEVNULL,
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True)
    try:
        output, error = process.communicate(body, timeout=remaining)
    except BaseException:
        SetupRunner.stop(process)
        raise
    return subprocess.CompletedProcess(command, process.returncode, output, error)


def _render_legacy_claude(renderer: Path, runtime: Path, project: Path, config: Path, role: str) -> bytes:
    """仅调用原 Claude 生成函数，不运行其 setup main、恢复或 ID 初始化分支。

    原脚本尚无独立 render CLI。取当前安装所有者脚本中已知 main 标记之前的
    声明前缀，并以 --check 使唯一的早期初始化条件为假；三根在 source common
    后立即显式覆盖。前缀从不写到磁盘，也不复制/改写另一套角色渲染规则。
    """
    body = (renderer / "setup_claude.sh").read_text(encoding="utf-8")
    boundary = '\nif [[ "${PREFLIGHT_ONLY}" -eq 1 ]]; then'
    common = 'source "${SCRIPT_DIR}/lib/common.sh"'
    start = 'SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"'
    if body.count(boundary) != 1 or body.count(common) != 1 or body.count(start) != 1:
        raise InstallError("当前 Claude 生成器缺少可证明纯读取的声明边界")
    prefix = body.split(boundary, 1)[0].replace(start, "SCRIPT_DIR=" + shlex.quote(str(renderer)), 1)
    values = {"PACK_DIR": runtime, "PACK_LIB_DIR": renderer / "lib", "PROJECT_ROOT": project,
              "PROJECT_YAML": config, "PRODUCT_DIR": runtime / "product", "ROLES_DIR": runtime / "roles",
              "PLATFORMS_DIR": runtime / "platforms", "SCRIPTS_DIR": runtime / "scripts",
              "ROLES_YAML": runtime / "product/ROLES.yaml"}
    assignments = "\n".join(name + "=" + shlex.quote(str(value)) for name, value in values.items())
    prefix = prefix.replace(common, common + "\n" + assignments, 1)
    # 执行代码固定来自当前安装所有者，旧目录只作为已经过清单验证的数据来源，
    # 不通过旧可变 lib 路径执行另一份 Python helper。
    prefix = prefix.replace('"${PACK_DIR}/lib/', '"${SCRIPT_DIR}/lib/')
    # 原 Bash 生成函数在同一 local 声明里展开 ${role}，常规调用由外层循环
    # 提供该动态作用域值。纯入口显式给同一个变量，避免 nounset 下误失败。
    program = prefix + '\nrole="${AGENT_WORKFLOW_RENDER_ROLE}"\nrender_claude_agent "${role}"\n'
    result = _capture_legacy(["bash", "-s", "--", "--check"], body=program.encode(),
                            env={**os.environ, "AGENT_WORKFLOW_RENDER_ROLE": role,
                                 "AGENT_WORKFLOW_PYTHON": sys.executable, "PYTHONDONTWRITEBYTECODE": "1"},
                            )
    if result.returncode:
        raise InstallError("旧 Claude 原生输入不能按原来源纯渲染：" + role)
    return result.stdout


def legacy_preflight(old_runtime: Path, project_root: Path, config_path: Path) -> dict:
    """显式旧安装迁移的纯读取合同；返回精确文件前像与待归档目录指纹。

    不执行旧 setup --check，不恢复 Skill，不推断旧任务已结束。调用方只有在
    migrate_legacy 明确声明后才可消费此结果，且 apply 前还要重查全部指纹。
    """
    runtime_api = _central_imports()
    from lib.shared_core_skills import audit_managed_skill_root, compare_skill_trees, load_shared_core_skills
    from lib.claude_instructions import intervals, PAIRS
    project = runtime_api.canonical_project(project_root)
    old_runtime, config_path = Path(old_runtime).absolute(), Path(config_path).absolute()
    if old_runtime != project / RUNTIME_NAME or config_path != old_runtime / "project.yaml":
        raise InstallError("旧安装迁移必须显式提供当前项目的运行时及配置路径")
    _validate_existing(old_runtime)
    before_core = legacy_tree_snapshot(old_runtime)
    validation = validate_with_profile(config_path, project, old_runtime / "roles")
    if validation.errors or validation.profile is None:
        if any("notes" in item or "fallback_dir" in item for item in validation.errors):
            raise InstallError("旧 notes 配置必须先显式归属迁移")
        raise InstallError("旧项目配置未通过迁移前只读校验；未显示配置原文")
    names = load_shared_core_skills(old_runtime)
    renderer = Path(__file__).resolve().parents[1]
    files, moves, hosts = {}, [{"path": RUNTIME_NAME, "snapshot": before_core}], []
    with runtime_api.Tree(project) as tree:
        for host, (directory, suffix) in runtime_api.ROLE_PATHS.items():
            try:
                descriptor = tree.directory(directory)
            except FileNotFoundError:
                continue
            expected = {role + suffix for role in validation.profile.enabled_roles}
            present = set(os.listdir(descriptor))
            if not any(name.startswith("xy-") for name in present):
                continue  # 仅有用户自定义角色的目录不等于已经安装本工作流宿主。
            if not expected <= present or any(name.startswith("xy-") and name not in expected for name in present):
                raise InstallError("旧原生角色集合存在缺失或未知资源：" + directory)
            hosts.append(host)
            for role in validation.profile.enabled_roles:
                relative = directory + "/" + role + suffix
                node = tree.read(relative)
                if host == "codex":
                    result = _capture_legacy(["bash", str(renderer / "setup_codex.sh"), "--render-agent=" + role,
                                             "--render-runtime-root=" + str(old_runtime), "--render-project-root=" + str(project),
                                             "--render-config-path=" + str(config_path)],
                                            env={**os.environ, "AGENT_WORKFLOW_PYTHON": sys.executable, "PYTHONDONTWRITEBYTECODE": "1"},
                                            )
                    if result.returncode:
                        raise InstallError("旧 Codex 原生输入不能按原来源纯渲染：" + role)
                    expected_body = result.stdout
                elif host == "claude":
                    expected_body = _render_legacy_claude(renderer, old_runtime, project, config_path, role)
                else:
                    code = '''import sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
import render_antigravity_agent as renderer
from validate_project_config import validate_with_profile
runtime, project, config, role = Path(sys.argv[2]), Path(sys.argv[3]), Path(sys.argv[4]), sys.argv[5]
checked = validate_with_profile(config, project, runtime / "roles")
if checked.errors or checked.profile is None: raise ValueError("旧配置不合法")
renderer.project_profile = lambda unused: checked.profile
print(renderer.render(runtime, role), end="")
'''
                    result = _capture_legacy([sys.executable, "-B", "-X", "utf8", "-c", code, str(renderer / "lib"),
                                             str(old_runtime), str(project), str(config_path), role])
                    if result.returncode:
                        raise InstallError("旧 Antigravity 原生输入不能按原来源纯渲染：" + role)
                    expected_body = result.stdout
                if node.kind != "file" or node.payload != expected_body:
                    raise InstallError("旧受管原生角色含手改，停止转换：" + relative)
                files[relative] = node.value()
        skill_roots = {".claude/skills" if host == "claude" else ".agents/skills" for host in hosts}
        for root in sorted(skill_roots):
            audit_managed_skill_root(project / root, recover=False)
            for name in names:
                relative = root + "/" + name
                compare_skill_trees(old_runtime / "platforms/shared/skills" / name, project / relative, name)
                moves.append({"path": relative, "snapshot": legacy_tree_snapshot(project / relative)})
        agents = tree.read("AGENTS.md")
        spans = intervals(agents.payload)
        text = agents.payload.decode("utf-8")
        for begin, end in PAIRS:
            if begin not in spans:
                continue
            host = "claude" if ":claude-begin" in begin else re.search(r"pack:([a-z]+)-begin", begin)[1]
            source = old_runtime / ("platforms/shared/AGENTS.product.tpl" if host == "product" else f"platforms/{host}/AGENTS.{host}.tpl")
            expected = begin + "\n" + source.read_text(encoding="utf-8").rstrip("\n") + "\n" + end + "\n"
            start, stop = spans[begin]
            if text[start:stop] != expected:
                raise InstallError("旧共享入口含手改，停止转换：AGENTS.md")
        if not spans:
            raise InstallError("旧共享入口缺少可证明归属的标记")
        remaining = text
        for start, stop in sorted(spans.values(), reverse=True):
            remaining = remaining[:start] + remaining[stop:]
        files["AGENTS.md"] = agents.value()
        bases = {"AGENTS.md": runtime_api.Node("file", remaining.encode(), agents.mode).value()}
        if "claude" in hosts:
            claude = tree.read("CLAUDE.md")
            if claude.payload != CLAUDE_IMPORT:
                raise InstallError("旧 CLAUDE.md 薄入口含未知手改，停止转换")
            files["CLAUDE.md"] = claude.value()
            bases["CLAUDE.md"] = runtime_api.Node().value()
        if "codex" in hosts:
            from lib.merge_codex_config import render
            native = tree.read(".codex/config.toml")
            config_body = tree.read(RUNTIME_NAME + "/project.yaml")
            threads = re.search(rb"(?m)^  max_concurrent_subagents:\s*([1-9][0-9]*)", config_body.payload)
            if render(native.payload.decode(), int(threads[1]) if threads else 8).encode() != native.payload:
                raise InstallError("旧 Codex 原生配置含手改或受管漂移，停止转换")
            files[".codex/config.toml"] = native.value()
        config = tree.read(RUNTIME_NAME + "/project.yaml")
    if not hosts:
        raise InstallError("旧运行时没有可证明受管的原生宿主输入")
    if legacy_tree_snapshot(old_runtime) != before_core:
        raise InstallError("旧运行时在纯读取 preflight 期间发生变化")
    return {"schema_version": 1, "moves": moves, "files": files, "entry_baselines": bases,
            "config": config.value(), "hosts": hosts,
            "hook_shim": (old_runtime / "lib/workflow_hooks.py").is_file()}


def _target_path(raw: str, source_root: Path) -> Path:
    """兼容终端拖入的引号与反斜杠转义，但绝不通过 shell 执行路径。"""

    value = raw.rstrip("\r\n")
    if not value.strip():
        raise InstallError("未提供项目目录。请拖入目录后按回车，或将目录作为参数传入。")
    candidates = [value]
    if value.strip() != value:
        candidates.append(value.strip())
    # 参数模式收到的是 shell 已解引用的真实路径，文件夹名本身可能含单引号；
    # 只有原样和去除误输入空白的路径都不存在时，才解析终端拖入的转义形式。
    if not any(Path(candidate).expanduser().is_dir() for candidate in candidates):
        try:
            tokens = shlex.split(value)
        except ValueError as exc:
            raise InstallError(f"项目路径的引号或转义不完整：{exc}") from exc
        if len(tokens) == 1:
            candidates.append(tokens[0])
    for candidate in candidates:
        path = Path(candidate).expanduser()
        if not path.is_dir():
            continue
        if os.name == "nt":
            if __package__:
                from .windows_fs import Directory
            else:
                from windows_fs import Directory
            # Reject junction ancestors before resolve can erase their identity.
            with Directory(path):
                resolved = path.resolve(strict=True)
        else:
            resolved = path.resolve(strict=True)
        if resolved == source_root or resolved.is_relative_to(source_root):
            raise InstallError("目标项目不能是安装包本身或其子目录。")
        if source_root.is_relative_to(resolved):
            raise InstallError("目标目录不能包含当前安装包；请选择具体项目根目录。")
        return resolved
    raise InstallError(f"项目目录不存在或不是文件夹：{value}")


def _digest(path: Path) -> str:
    hasher = hashlib.sha256()
    if os.name == "nt":
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
        stream = os.fdopen(descriptor, "rb")
    else:
        stream = path.open("rb")
    with stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def _managed_files(root: Path) -> dict[str, str]:
    """配置由项目维护；其他运行时文件由安装包管理并记录指纹。"""

    result: dict[str, str] = {}
    if os.name == "nt":
        def visit(directory: Path) -> None:
            with os.scandir(directory) as entries:
                for entry in entries:
                    info = entry.stat(follow_symlinks=False)
                    path = Path(entry.path)
                    if stat.S_ISLNK(info.st_mode):
                        raise InstallError(f"受管运行时不能包含重解析点：{path}")
                    if stat.S_ISDIR(info.st_mode):
                        if path.name != "__pycache__":
                            visit(path)
                    elif stat.S_ISREG(info.st_mode) and info.st_nlink == 1:
                        relative = path.relative_to(root).as_posix()
                        if relative not in {"project.yaml", MANIFEST_NAME} and path.name != ".DS_Store":
                            result[relative] = _digest(path)
                    else:
                        raise InstallError(f"受管运行时必须为单链接普通文件：{path}")
        visit(root)
        return result
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise InstallError(f"受管运行时不能包含符号链接：{path}")
        if not path.is_file():
            continue
        relative_path = path.relative_to(root)
        relative = relative_path.as_posix()
        if relative in {"project.yaml", MANIFEST_NAME}:
            continue
        if path.name == ".DS_Store" or "__pycache__" in relative_path.parts:
            continue
        result[relative] = _digest(path)
    return result


def _validate_existing(runtime: Path) -> None:
    """升级前拒绝覆盖用户改过或来源不明的隐藏目录。"""

    if runtime.is_symlink() or not runtime.is_dir():
        raise InstallError(f"已存在非受管运行时目录：{runtime}")
    manifest_path = runtime / MANIFEST_NAME
    if not manifest_path.is_file():
        raise InstallError(f"已存在未标记的目录，不能自动覆盖：{runtime}")
    try:
        manifest_body = read_file(manifest_path) if os.name == "nt" else manifest_path.read_bytes()
        if manifest_body is None:
            raise ValueError("installation manifest is missing")
        manifest = json.loads(manifest_body)
    except (OSError, ValueError) as exc:
        raise InstallError(f"安装记录无法读取：{manifest_path}") from exc
    if not isinstance(manifest, dict) or manifest.get("schema_version") != 1 or not isinstance(
        manifest.get("managed_files"), dict
    ):
        raise InstallError("安装记录格式未知，不能安全升级。")
    actual = _managed_files(runtime)
    if actual != manifest["managed_files"]:
        raise InstallError(
            "隐藏运行时含有新增、删除或修改过的受管文件；已停止升级并保留原状。"
        )


def _backup_snapshot(root: Path) -> dict[str, dict]:
    """记录完整备份的文件内容和 POSIX 权限位，包含项目配置及附加文件。"""
    result: dict[str, dict] = {".": {"type": "directory", "mode": stat.S_IMODE(os.lstat(root).st_mode)}}

    def identity(info):
        # 内容读取不能掩盖并发替换、写入或权限变化；atime 的正常读取更新不参与判断。
        return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns,
                info.st_ctime_ns, info.st_mode, info.st_nlink)

    def visit(directory: Path) -> None:
        with os.scandir(directory) as entries:
            for entry in entries:
                path = directory / entry.name
                relative = path.relative_to(root).as_posix()
                info = entry.stat(follow_symlinks=False)
                mode = stat.S_IMODE(info.st_mode)
                if stat.S_ISDIR(info.st_mode):
                    result[relative] = {"type": "directory", "mode": mode}
                    visit(path)
                elif stat.S_ISREG(info.st_mode) and info.st_nlink == 1:
                    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | getattr(os, "O_NONBLOCK", 0))
                    with os.fdopen(descriptor, "rb") as stream:
                        opened = os.fstat(stream.fileno())
                        if (opened.st_dev, opened.st_ino, opened.st_nlink) != (info.st_dev, info.st_ino, 1):
                            raise InstallError(f"备份文件读取前发生变化：{path}")
                        hasher = hashlib.sha256()
                        if relative == MANIFEST_NAME:
                            # 只排除工具自身的快照字段以避免递归；用户附加字段及清单权限仍受保护。
                            manifest = json.load(stream)
                            if not isinstance(manifest, dict):
                                raise InstallError("备份清单不是 JSON 对象")
                            manifest.pop("backup_snapshot", None)
                            canonical = json.dumps(manifest, ensure_ascii=False, sort_keys=True,
                                                   separators=(",", ":")).encode("utf-8")
                            hasher.update(canonical)
                        else:
                            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                                hasher.update(chunk)
                        after = os.fstat(stream.fileno())
                    current = os.lstat(path)
                    if identity(info) != identity(after) or identity(info) != identity(current):
                        raise InstallError(f"备份文件读取期间发生变化：{path}")
                    result[relative] = {"type": "file", "mode": mode, "sha256": hasher.hexdigest()}
                else:
                    raise InstallError(f"备份包含链接或不支持的文件类型，已保留：{path}")

    visit(root)
    return result


def _record_backup_snapshot(backup: Path, snapshot: dict | None = None) -> None:
    """把创建时原始快照登记到备份清单，不能在以后清理时追认已修改的内容。"""
    # Windows 暂停自动轮换，也不重写旧清单，保留其原有 DACL 和继承策略。
    if os.name == "nt":
        return
    manifest_path = backup / MANIFEST_NAME
    original = read_file(manifest_path)
    if original is None:
        raise InstallError(f"备份清单已消失：{manifest_path}")
    manifest = json.loads(original)
    if not isinstance(manifest, dict):
        raise InstallError("备份清单不是 JSON 对象")
    manifest["backup_snapshot"] = _backup_snapshot(backup) if snapshot is None else snapshot
    body = (json.dumps(manifest, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    atomic_write(manifest_path, body, stat.S_IMODE(manifest_path.stat().st_mode))


def _windows_copy(source: Path, target: Path, identities: dict[Path, tuple[int, int]]) -> None:
    info = os.lstat(source)
    if stat.S_ISDIR(info.st_mode):
        os.mkdir(target, 0o700)
        with os.scandir(source) as entries:
            for entry in entries:
                if entry.name in {"__pycache__", ".DS_Store"} or entry.name.endswith(".pyc"):
                    continue
                if source.name == "lib" and entry.name == "install_workflow.py":
                    continue
                _windows_copy(Path(entry.path), target / entry.name, identities)
    elif stat.S_ISREG(info.st_mode) and info.st_nlink == 1:
        source_fd = os.open(source, os.O_RDONLY | os.O_NOFOLLOW)
        with os.fdopen(source_fd, "rb") as input_file:
            opened = os.fstat(input_file.fileno())
            if (opened.st_dev, opened.st_ino) != (info.st_dev, info.st_ino):
                raise InstallError(f"安装源文件在复制前变化：{source}")
            target_fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(target_fd, "wb") as output:
                shutil.copyfileobj(input_file, output)
                output.flush()
                os.fsync(output.fileno())
                created = os.fstat(output.fileno())
                identities[target] = (created.st_dev, created.st_ino)
            after = os.fstat(input_file.fileno())
            if (opened.st_size, opened.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
                raise InstallError(f"安装源文件在复制期间变化：{source}")
    else:
        raise InstallError(f"安装源包含链接或不支持的类型：{source}")


def _discard_windows_stage(stage: Path, expected: dict[str, tuple[str, tuple[int, int]]] | None) -> None:
    # An interrupted copy without a full inventory is left for diagnosis. Never
    # recursively delete unknown entries or a user's concurrent staged edits.
    if expected is None:
        return
    if __package__:
        from .windows_fs import remove_file_if_unchanged
    else:
        from windows_fs import remove_file_if_unchanged
    for relative, (digest, identity) in expected.items():
        path = stage / relative
        try:
            remove_file_if_unchanged(path, digest, identity)
        except (OSError, ValueError):
            pass
    directories = set()
    for relative in expected:
        directories.update((stage / relative).parents)
    for directory in sorted((p for p in directories if p == stage or p.is_relative_to(stage)),
                            key=lambda p: -len(p.parts)):
        try:
            os.rmdir(directory)
        except (OSError, ValueError):
            pass


def _copy_runtime(source_root: Path, stage: Path, identities=None) -> None:
    """只复制安装后运行所需的文件，避免把测试和历史草稿留在项目中。"""

    if os.name == "nt":
        if identities is None:
            identities = {}
        for name in (*PACK_FILES, *PACK_DIRECTORIES):
            _windows_copy(source_root / name, stage / name, identities)
        return
    for name in (*PACK_FILES, *PACK_DIRECTORIES):
        source = source_root / name
        if not source.exists() or source.is_symlink():
            raise InstallError(f"安装包缺少正常文件或目录：{source}")
        target = stage / name
        if source.is_dir():
            for child in source.rglob("*"):
                if child.is_symlink():
                    raise InstallError(f"安装包含符号链接，停止复制：{child}")
            ignored = ["__pycache__", "*.pyc", ".DS_Store"]
            if name == "lib":
                ignored.append("install_workflow.py")
            shutil.copytree(
                source,
                target,
                ignore=shutil.ignore_patterns(*ignored),
            )
        elif source.is_file():
            shutil.copy2(source, target)
        else:
            raise InstallError(f"安装包含不支持的文件类型：{source}")


def _run_setup(runtime: Path, project: Path, *options: str) -> None:
    command, environment = setup_command(runtime, options)
    # 只影响展示：把含空格的路径按 shell 可读形式显示，实际执行仍使用参数数组。
    print(f"[安装] {shlex.join(command)}", flush=True)
    runner = ACTIVE_RUNNER.get() or SetupRunner()
    if environment is None:
        runner.run(command, project)
    else:
        runner.run(command, project, env=environment)


def _initialize_project_name(config: Path, project: Path) -> tuple[int, int] | None:
    """仅替换暂存配置的默认显示名；显式名称和其余配置均属于项目。"""
    try:
        body = read_file(config)
        if body is None:
            raise ValueError("project.yaml is missing")
        text = body.decode("utf-8")
        matches = list(re.finditer(r"^project_name:[ \t]*([^\r\n]*)", text, re.MULTILINE))
        if len(matches) != 1:
            raise ValueError("project.yaml must contain exactly one top-level project_name")
        match = matches[0]
        raw = match.group(1)
        if parse_project_name(raw) != "MyProject":
            return
        # 目标根目录才是项目名；不能取源包、随机暂存目录或某个子模块的包名。
        # JSON 字符串也是合法 YAML，可安全保存中文、空格、引号和 # 等目录字符。
        # 只替换标量，保留行内注释、原换行符和 memory.project_id 等其他配置字节。
        value = json.dumps(project.name, ensure_ascii=False)
        suffix = raw[len(strip_inline_comment(raw)):]
        updated = (text[:match.start(1)] + value + suffix + text[match.end(1):]).encode("utf-8")
        if updated != body:
            identity = atomic_write(config, updated, stat.S_IMODE(config.stat().st_mode))
            print(f"[项目] project_name 已按目标目录初始化为 {value}", flush=True)
            return identity
    except ValueError as exc:
        raise InstallError(f"无法初始化项目名称：{exc}") from exc


def _restore_claude_entry(project: Path, original: bytes | None, mode: int) -> None:
    """撤回本轮发布的薄入口；先恢复入口，再让原运行时重建其他受管产物。"""
    path = project / "CLAUDE.md"
    current = read_file(path)
    if current == original:
        return
    # 只能撤回仍为本轮精确产物的入口；并发新增、修改或删除的用户内容不能覆盖。
    # 原先没有入口时只删除这一个确认过的文件，不触碰其他 Claude 指令。
    if current != CLAUDE_IMPORT:
        raise InstallError("CLAUDE.md 在升级期间发生其他变更；已保留现状，停止自动恢复入口。")
    atomic_write(path, original, mode)


def _restore_hook_configs(snapshots: list[tuple[Path, bytes | None, bytes, int]]) -> None:
    """只撤回仍等于本轮精确产物的配置；并发用户修改宁可报错，也不能覆盖。

    旧运行时可能不认识新 Hooks，故先恢复配置，再由原运行时重建其自身产物。
    首次安装保留可诊断状态；这里仅处理已有完整备份的升级失败。
    """
    for path, before, published, mode in reversed(snapshots):
        current = read_file(path)
        if current == before:
            continue
        if current != published:
            raise InstallError(f"Hook 配置升级期间发生其他变更，已保留：{path}")
        atomic_write(path, before, mode)


def _standard_update_snapshots(pack: Path, project: Path) -> list[tuple[Path, bytes | None, bytes | None, int]]:
    """冻结共享规范计划的原始输入与产物，供三宿主升级整体失败时恢复。

    创建、替换和删除采用同一份计划；不能只恢复 GENERAL 而留下损坏的索引，也不能
    把删除后的缺失当成读取错误。原字节只存当前事务内存，不制造历史源码树副本。
    """

    # 安装入口已经验证根目录；与共享规划器使用同一物理根，避免合法 /var 别名
    # 在 is_relative_to 中被误判为项目外路径。内部规范路径仍按配置逐级安全读取。
    if not stat.S_ISDIR(project.lstat().st_mode):
        raise InstallError(f"规范迁移根必须是实际目录：{project}")
    project = project.resolve()
    docs = parse_docs(pack / "project.yaml")
    discovered = validate_with_profile(pack / "project.yaml", project, pack / "roles")
    if discovered.errors or discovered.profile is None:
        raise InstallError("无法规划规范迁移：" + "; ".join(discovered.errors))
    expected_inputs: dict[Path, bytes | None] = {}
    updates = plan_standard_updates(pack, project, docs=docs, profile=discovered.profile,
                                    expected_inputs=expected_inputs)
    result = []
    for path, after in updates.items():
        if not path.resolve().is_relative_to(project):
            raise InstallError("规范路径必须位于项目内")
        before = read_file(path)
        if before != expected_inputs[path]:
            raise InstallError(f"规范在迁移规划后发生变更，已保留：{path}")
        if after != before:
            mode = stat.S_IMODE(path.stat().st_mode) if before is not None else 0o644
            result.append((path, before, after, mode))
    return result


def _restore_standard_updates(snapshots: list[tuple[Path, bytes | None, bytes | None, int]]) -> None:
    """只恢复仍等于本轮产物的规范，不能覆盖安装期间的项目专项并发修改。"""

    errors: list[str] = []
    for path, before, published, mode in reversed(snapshots):
        try:
            try:
                sampled = os.lstat(path)
            except FileNotFoundError:
                sampled = None
            current = read_file(path)
            if current == before:
                continue
            # 权限本身也是项目修改；不能只因内容相同就把并发 chmod 一起撤回。
            if current != published or (current is not None and stat.S_IMODE(path.stat().st_mode) != mode):
                raise InstallError(f"规范在升级期间发生其他变更，已保留现状：{path}")
            if published is None:
                # 删除后的恢复只能发布到仍缺失的名字。原 atomic_write 会在最后一步
                # 无条件 replace，覆盖 read_file 之后刚重建的用户文件。
                descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.restore-", dir=path.parent)
                temporary = Path(temporary_name)
                try:
                    with os.fdopen(descriptor, "wb") as stream:
                        stream.write(before)
                        os.fchmod(stream.fileno(), mode)
                        stream.flush()
                        os.fsync(stream.fileno())
                    publish_exclusive(temporary, path)
                finally:
                    if temporary.exists():
                        os.unlink(temporary)
            elif before is None:
                # 新建薄索引的撤回须绑定读取前的身份；即使用户替换成相同字节，
                # 也不能把新 inode 追认为本轮产物。普通既有文档恢复维持原机制。
                if sampled is None:
                    raise InstallError(f"规范在恢复采样期间发生变更，已保留：{path}")
                remove_created_standard(path, published, mode, (sampled.st_dev, sampled.st_ino))
            else:
                atomic_write(path, before, mode)
        except (InstallError, OSError, ValueError) as exc:
            errors.append(str(exc))
    # 一个项目文件有并发冲突，不阻止撤回其他仍精确属于本轮的独立规范文件。
    if errors:
        raise InstallError("; ".join(errors))


def _install(project: Path, source_root: Path, *, timeout: float | None = None) -> None:
    """给一次事务绑定超时控制；仅限制管理操作，不改变项目开发编排。"""
    runner = SetupRunner(timeout)
    token = ACTIVE_RUNNER.set(runner)
    try:
        control = nullcontext()
        if os.name == "nt":
            if __package__:
                from .windows_runtime import cancellation_guard
            else:
                from windows_runtime import cancellation_guard
            raw = os.environ.get("AGENT_WORKFLOW_CANCEL_FILE")
            if not raw:
                raise InstallError("Windows init requires its private npx cancellation channel")
            control = cancellation_guard(raw)
        # Shared boundary, independent of the manager's outer registry lock.
        # Both locks remain held until all writers and exact recovery finish.
        with project_install_lock(project), control:
            _install_transaction(project, source_root)
    finally:
        runner.close()
        ACTIVE_RUNNER.reset(token)


def _install_transaction(project: Path, source_root: Path) -> None:
    runtime = project / RUNTIME_NAME
    old_pack = project / "agent_workflow"
    # 新安装方式不迁移旧的项目内安装包，也不允许两个入口并存。
    # 这里只识别旧包的明确签名，避免误伤同名但属于业务的目录。
    if (old_pack / "setup_all.sh").is_file() and (
        old_pack / "product/WORKFLOW.md"
    ).is_file():
        raise InstallError(
            f"发现旧工作流目录 {old_pack}；请先备份并移除旧工作流，"
            "再使用本安装器。不会自动兼容或删除旧目录。"
        )
    if runtime.is_symlink():
        raise InstallError(f"不能覆盖符号链接：{runtime}")
    upgrading = runtime.exists()
    if upgrading:
        _validate_existing(runtime)

    # 暂存目录与项目同一文件系统，发布时可用重命名切换；前置检查失败不会
    # 触碰现有运行时或宿主入口。目录名由发现器明确排除，避免误识别为业务模块。
    if os.name == "nt":
        stage = project / (".agent-workflow-stage-" + uuid.uuid4().hex)
        os.mkdir(stage, 0o700)
    else:
        stage = Path(tempfile.mkdtemp(prefix=".agent-workflow-stage-", dir=project))
    stage_inventory: dict[str, tuple[str, tuple[int, int]]] | None = None
    created_files: dict[Path, tuple[int, int]] = {}
    backup: Path | None = None
    backup_snapshot: dict | None = None
    try:
        if os.name == "nt":
            _copy_runtime(source_root, stage, created_files)
        else:
            _copy_runtime(source_root, stage)
        if os.name == "nt":
            bootstrap = os.environ.get("AGENT_WORKFLOW_BOOTSTRAP", "")
            if not bootstrap or not Path(bootstrap).is_absolute():
                raise InstallError("Windows init requires its stable bootstrap path")
            if any(char in str(sys.executable) + bootstrap for char in "\r\n\x00"):
                raise InstallError("Windows runtime paths must be single-line absolute paths")
            record = stage / "lib/windows-runtime.paths"
            created_files[record] = atomic_write(
                record, f"{sys.executable}\n{bootstrap}\n".encode("utf-8"), 0o600)
        if upgrading:
            if os.name == "nt":
                original_config = read_file(runtime / "project.yaml")
                if original_config is None:
                    raise InstallError("旧运行时缺少 project.yaml")
                created_files[stage / "project.yaml"] = atomic_write(stage / "project.yaml", original_config, 0o600)
                if __package__:
                    from .windows_fs import copy_permissions
                else:
                    from windows_fs import copy_permissions
                copy_permissions(runtime / "project.yaml", stage / "project.yaml")
            else:
                shutil.copy2(runtime / "project.yaml", stage / "project.yaml")
        # 先保留升级前的项目配置，再只补默认名称；修改留在暂存区，预检失败或
        # 发布回滚时仍可恢复旧配置。宿主 --check / --preflight 本身保持只读。
        configured_identity = _initialize_project_name(stage / "project.yaml", project)
        if configured_identity is not None:
            created_files[stage / "project.yaml"] = configured_identity
        manifest = {
            "schema_version": 1,
            "managed_files": _managed_files(stage),
        }
        manifest_body = (json.dumps(manifest, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
        if os.name == "nt":
            created_files[stage / MANIFEST_NAME] = atomic_write(stage / MANIFEST_NAME, manifest_body, 0o600)
            digests = manifest["managed_files"] | {
                name: _digest(stage / name) for name in ("project.yaml", MANIFEST_NAME)
            }
            stage_inventory = {
                name: (digest, created_files[stage / name]) for name, digest in digests.items()
                if created_files.get(stage / name) is not None
            }
            if __package__:
                from .windows_fs import flush_tree
            else:
                from windows_fs import flush_tree
            flush_tree(stage)
        else:
            (stage / MANIFEST_NAME).write_bytes(manifest_body)
        _run_setup(stage, project, "--preflight")

        standard_snapshots = _standard_update_snapshots(stage, project) if upgrading else []
        if upgrading:
            # 发布前保留准确入口状态。仅恢复旧运行时不足以撤回新入口：
            # 原运行时可能采用不同入口合同，不能要求它识别本轮新增产物。
            claude_entry = project / "CLAUDE.md"
            claude_before = read_file(claude_entry)
            claude_mode = stat.S_IMODE(claude_entry.stat().st_mode) if claude_before is not None else 0o644
            backup = project / f".agent-workflow-backup-{uuid.uuid4().hex[:12]}"
        hook_snapshots: list[tuple[Path, bytes | None, bytes, int]] = []
        setup_started = False
        try:
            # 两次目录发布也在事务异常边界内；取消不能留下只有 backup 的悬空项目。
            if backup is not None:
                os.replace(runtime, backup)
                # 先在内存固定创建时状态，暂不改旧清单；后续准备/安装失败仍能逐字节恢复旧版本。
                if os.name != "nt":
                    backup_snapshot = _backup_snapshot(backup)
            os.replace(stage, runtime)
            if backup is not None:
                for host in ("claude", "codex", "antigravity"):
                    path, before, after = plan_hooks(runtime, project, host, simulate_codex_setup=host == "codex")
                    mode = stat.S_IMODE(path.stat().st_mode) if before is not None else 0o644
                    hook_snapshots.append((path, before, after, mode))
            setup_started = True
            _run_setup(runtime, project)
            _run_setup(runtime, project, "--check")
        except (InstallError, subprocess.CalledProcessError, OSError, ValueError, KeyboardInterrupt) as exc:
            runner = ACTIVE_RUNNER.get()
            if runner is not None:
                runner.begin_recovery()
            failure = (f"退出码 {exc.returncode}" if isinstance(exc, subprocess.CalledProcessError)
                       else "用户取消" if isinstance(exc, KeyboardInterrupt) else str(exc))
            if backup is not None and not backup.exists():
                raise InstallError(f"升级发布未开始（{failure}），旧运行时保持原状。") from exc
            if backup is not None and not runtime.exists():
                # 以实际目录状态识别“replace 已完成，标志赋值前被中断”的情况。
                os.replace(backup, runtime)
                raise InstallError(f"升级发布中断（{failure}），旧运行时已恢复。") from exc
            # 首次安装可能已经写入部分宿主入口；此时必须保留它们引用的
            # .agent-workflow 路径，不能把运行时搬走造成悬空指令。
            if backup is None:
                raise InstallError(
                    f"首次安装或验收失败（{failure}）；"
                    f"运行时仍在 {runtime}，请检查并重试，原始安装包尚不可删除。"
                ) from exc

            # 升级失败时保留失败版本供诊断，再恢复旧运行时和宿主入口，
            # 避免旧版本被新版本的部分产物覆盖后无法继续使用。
            failed = project / f".agent-workflow-failed-{uuid.uuid4().hex[:12]}"
            os.replace(runtime, failed)
            os.replace(backup, runtime)
            if not setup_started:
                # 快照准备失败时尚未发布任何宿主产物；仅恢复运行时，不覆盖预检后
                # 用户更改的配置，也不运行一个可能再次写入项目的旧安装脚本。
                raise InstallError(
                    f"升级发布前准备失败（{failure}）；旧运行时已恢复，用户配置保持原状；"
                    f"失败版本保留在 {failed}。"
                ) from exc
            try:
                restore_errors: list[str] = []
                # 文档冲突不能阻止薄入口与 Hook 的独立安全恢复；任一冲突仍会
                # 阻止执行旧 setup，避免它重新写入需要人工核对的并发项目文档。
                for restore in (
                    lambda: _restore_standard_updates(standard_snapshots),
                    lambda: _restore_claude_entry(project, claude_before, claude_mode),
                    lambda: _restore_hook_configs(hook_snapshots),
                ):
                    try:
                        restore()
                    except (InstallError, OSError, ValueError) as restore_exc:
                        restore_errors.append(str(restore_exc))
                if restore_errors:
                    raise InstallError("; ".join(restore_errors))
                _run_setup(runtime, project)
                _run_setup(runtime, project, "--check")
            except (InstallError, OSError, UnicodeError, ValueError) as restore_exc:
                raise InstallError(
                    f"新版本安装失败，旧运行时已恢复，但入口/Hook/规范无法安全恢复：{restore_exc}；"
                    f"失败版本保留在 {failed}，请人工核对上述文件。"
                ) from restore_exc
            except subprocess.CalledProcessError as restore_exc:
                raise InstallError(
                    f"新版本安装失败，旧运行时已恢复，但旧入口重建也失败；"
                    f"请检查 {failed} 与命令退出码 {restore_exc.returncode}。"
                ) from restore_exc
            raise InstallError(
                f"安装或验收失败（{failure}）；失败版本保留在 {failed}，"
                "原始安装包尚不可删除。"
            ) from exc

        # 至此新运行时已验收，后续只是备份维护，不能因登记失败或写后中断回滚已完成安装。
        # 沿用创建时内存指纹，不追认安装期间的并发修改；失败则保留所有备份并跳过轮换。
        recorded = True
        if backup is not None:
            try:
                _record_backup_snapshot(backup, backup_snapshot)
            except (InstallError, OSError, ValueError, KeyboardInterrupt):
                recorded = False
                print("[提示] 安装已验收，备份指纹登记未完成；旧备份已保留，本次跳过轮换。")
        print(f"[完成] 项目运行时：{runtime}")
        if backup is not None:
            print(f"[备份] 上一版本保留在：{backup}")
            if recorded:
                _prune_runtime_backups(project, backup)
        print(
            "[完成] 可移除本次使用的原始 agent_workflow 安装包；"
            "项目内 .agent-workflow 必须保留。"
        )
    finally:
        if stage.exists():
            if os.name == "nt":
                if __package__:
                    from .windows_process import WindowsJobCleanupError
                else:
                    from windows_process import WindowsJobCleanupError
                if not isinstance(sys.exception(), WindowsJobCleanupError):
                    _discard_windows_stage(stage, stage_inventory)
            else:
                shutil.rmtree(stage)


RUNTIME_BACKUP_NAME = re.compile(r"\.agent-workflow-backup-[0-9a-f]{12}")


def _prune_runtime_backups(project: Path, keep: Path) -> None:
    """升级验收通过后只保留最近一份旧运行时，避免每次升级累积完整副本。"""

    # Windows 的 stat mode 只反映只读属性，无法证明 DACL/继承权限没有变化。
    # 在具备原生 ACL 指纹与验收前保守保留，不能把 POSIX 权限位比较当作 Windows 权限保障。
    if os.name == "nt":
        print("[提示] Windows 旧运行时备份已保留：尚未提供经原生验收的 ACL 权限指纹。")
        return
    # 仅匹配安装器自身生成的运行时备份；角色模型备份（-models-）由管理器维护，
    # 失败版本（-failed-）留作诊断，二者都不在此处清理。符号链接及用户改动过的备份不删除。
    for stale in project.iterdir():
        if stale == keep or not RUNTIME_BACKUP_NAME.fullmatch(stale.name):
            continue
        if stale.is_symlink() or not stale.is_dir():
            continue
        try:
            _validate_existing(stale)
            body = read_file(stale / MANIFEST_NAME)
            if body is None:
                raise InstallError("备份清单已消失")
            manifest = json.loads(body)
            expected = manifest.get("backup_snapshot")
            # 历史备份缺少创建时证据，无法判断配置是否被修改；保留而不按当前状态补登记。
            if not isinstance(expected, dict) or expected != _backup_snapshot(stale):
                raise InstallError("备份缺少完整原始指纹或内容/权限已改变")
            shutil.rmtree(stale)
        except (InstallError, OSError, ValueError) as exc:
            # 清理旧备份失败或检测到非受管改动时保留原目录，只提示用户手工核对。
            print(f"[提示] 旧备份未能清理，已保留供人工核对：{stale}（{exc}）")
        else:
            print(f"[清理] 已移除更早的运行时备份：{stale.name}")


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="install.sh",
        description="将项目接入固定版本中央工作流；原始安装包可移除。"
    )
    parser.add_argument("project", nargs="?", help="项目根目录；省略时可拖入终端")
    parser.add_argument("--timeout", type=float, help="安装事务的应用预算秒数；超时后停止 setup 并执行恢复")
    parser.add_argument("--state-dir", type=Path, help="本机中央状态根；默认沿现有状态配置")
    parser.add_argument("--migrate-legacy", action="store_true", help="显式声明旧任务已收尾，验证并保留归档后转换旧安装")
    args = parser.parse_args()
    source_root = Path(__file__).resolve().parent.parent
    try:
        raw = args.project
        if raw is None:
            raw = input("请将需要安装的项目文件夹拖入终端，然后按回车：")
        project = _target_path(raw, source_root)
        print(f"[目标] {project}", flush=True)
        installed = install_central(project, source_root, state=args.state_dir,
                                    migrate_legacy=args.migrate_legacy, timeout=args.timeout)
        print("[完成] 中央项目已启用；固定内容 ID：" + installed["runtime_binding"]["content_id"])
    except (EOFError, KeyboardInterrupt):
        print("\n[取消] 未安装。", file=sys.stderr)
        return 2
    except (InstallError, OSError, ValueError, subprocess.CalledProcessError, SetupRunError) as exc:
        print(f"[错误] {exc}", file=sys.stderr)
        return 2
    return 0


def install_central(project: Path, source_root: Path, *, state: Path | None = None,
                    migrate_legacy: bool = False, timeout: float | None = None) -> dict:
    """源码/Homebrew/NPM 共用默认入口；不再默认复制完整核心到项目。

    原 _install 低层仍归旧自包含恢复/夹具所有者，不由此默认调用。Windows
    缺少安全软链后端时在导入、状态创建及项目写入之前明确拒绝，不回退复制。
    """
    if __package__:
        from .platform_fs import require_skill_symlinks
    else:
        from platform_fs import require_skill_symlinks
    # 此能力拒绝早于导入中央 manager/新增模块；旧 Windows 打包入口也必须给
    # 出明确平台边界，不能因不含 manager 而先抛缺模块错误，更不能回退复制。
    require_skill_symlinks()
    _central_imports()
    from lib.install_process import ACTIVE_RUNNER as central_runner
    from lib import runtime_store
    from manager import runtime_service
    runner = SetupRunner(timeout)
    token = central_runner.set(runner)
    original = ACTIVE_RUNNER.set(runner)
    try:
        plan = runtime_service.preview(runtime_store.state_root(state), project, "enable",
                                       source_root=source_root, migrate_legacy=migrate_legacy)
        if not plan.summary["can_apply"]:
            raise InstallError("；".join(item["reason"] for item in plan.summary["conflicts"]))
        if runner.deadline is not None and runner.deadline <= time.monotonic():
            raise SetupRunError("安装预算已耗尽，项目尚未发布")
        return runtime_service.apply(plan)
    finally:
        ACTIVE_RUNNER.reset(original)
        central_runner.reset(token)
        runner.close()


if __name__ == "__main__":
    raise SystemExit(main())
