#!/usr/bin/env python3
"""离线构建独立原生 Agent 配置工具；零第三方依赖、零工作流安装依赖。"""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
from pathlib import Path
import re
import stat
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]
if sys.version_info < (3, 11):
    raise SystemExit("需要 Python >= 3.11；请使用 bash scripts/python_runtime.sh packaging/build_agent_config.py")
sys.path.insert(0, str(ROOT))
from product.command_identity import load_identity

README = """# Native Agent Config

独立管理 Codex、Claude Code 与 Antigravity 已发现的原生 Agent 模型字段与调用偏好。
网页同时提供 Codex、Claude Code 工作流的用户级默认与当前项目继承／启用／停用。
配置工具与任何工作流插件、角色清单、安装器及中央项目绑定相互独立。

需要本机已有 Python 3.11+ 和 Bash；当前构建验证覆盖 macOS，本包不安装解释器。
解压后从任意目录运行：

```sh
bash <解压根>/scripts/agent_config.sh console --host codex
bash <解压根>/scripts/agent_config.sh open --host codex
bash <解压根>/scripts/agent_config.sh status --host codex
bash <解压根>/scripts/agent_config.sh doctor --host codex
bash <解压根>/scripts/agent_config.sh list --host claude
bash <解压根>/scripts/agent_config.sh resolve --host codex --role <list返回的AgentID>
```

网页入口输出包含片段令牌的本地 URL；console 默认尝试打开浏览器，--no-browser 仅输出。
插件使用的 open/status/doctor 返回脱敏 JSON；status/doctor 不安装、不启动服务或浏览器。
open 的浏览器失败会保留 ready 服务及权限为 0600 的私有 HTML 打开入口。
serve 可前台运行并使用 --port 0 和 --idle-timeout 1800；mcp 是手动选择的 stdio 子命令，
不注册到宿主、不作为网页或工作流运行前置。脚本查询与网页保存调用同一业务核心。
尚未提供跨进程 preview/apply 脚本；网页预览在服务端保留同一确认计划。

测试或明确选择其他配置根时使用 --home <绝对目录> --data-dir <独立临时状态目录>；
可加 --project <绝对项目目录>。这些选项不修改 HOME、CODEX_HOME 或 PATH。
默认直接读取本机实际用户配置根。保存直接修改所选可写原生定义；插件来源保持只读。
保存结果包含逐项状态、必要的备份恢复路径与清理状态；磁盘保存不证明当前会话已加载。

调用偏好按用户通用、用户实际 Agent、当前项目通用、当前项目实际 Agent 逐字段继承。
独立文件固定保存在实际宿主配置根的 native-agent-config/dispatch-preferences.json，
不跟随 --data-dir 或安装版本迁移；插件缓存始终只读。默认目标 * 不是原生 Agent 名。
Codex 的本机模型目录来自实际 app-server 或显式目录，Claude 使用实际设置与菜单的
只读投影；目录可见不证明账户可调用。AGY 会话模型 slug 与子代理 inherit/flash/pro
分开处理，不支持的参数不伪造。模型变化后必须重新确认该模型可用的推理档位。
可从包外使用同源纯标准库只读入口，缺文件无偏好，损坏/危险来源/未知版本明确失败：

```sh
bash <解压根>/scripts/python_runtime.sh -B -X utf8 <解压根>/native_config/preference_contract.py --host codex --agent '*' --project <绝对项目目录>
```

该查询不启动 HTTP、不准备组件、不安装 MCP、不修改宿主设置；测试可显式加 --home。
model=inherit 表示不传模型覆盖；当前派发 schema 无法表达已配置字段时必须报告并阻断，
不能静默丢弃。完整原生定义仍可能按宿主规则优先，runtime_verified 始终为 false。

工作流卡与模型编辑分别预览、分别保存。继承只移除本层工作流启停键；Codex 项目写
.codex/config.toml，Claude 项目写 .claude/settings.local.json，后者仅影响本机当前项目，
继承后仍可能采用共享 .claude/settings.json。工具只编辑已明确识别的工作流插件身份，
其他插件和模型字段保持。Codex 项目信任、启动参数及托管策略仍由宿主决定。
Antigravity 的用户／项目启停文件合同尚未核实，因此本页只提供官方管理说明。

停用工作流之前，请保留本独立包的解压目录和页面提供的重新打开命令。停用插件后，
可离开工作流项目目录，在终端直接运行以下独立入口，重新预览并保存启用或继承：

```sh
bash <解压根>/scripts/agent_config.sh open --host codex --project <绝对项目目录>
bash <解压根>/scripts/agent_config.sh open --host claude --project <绝对项目目录>
```

恢复用户级默认时省略 --project；若之前明确选择了其他配置根或状态目录，恢复时继续
传入相同 --home 和 --data-dir。该入口无需已启用的工作流 Skill、工作流源码或 MCP。
也可在 Codex 官方 /plugins 或桌面插件管理中重新启用；Claude 可在项目目录执行
claude plugin enable <页面确认的插件ID> --scope local，用户级使用 --scope user。
保存成功后请启动新会话核实加载和实际工作流行为；工具始终区分已保存、等待新会话加载
与实际运行未验证，当前会话已加载的上下文不会随停用清除。
官方配置与管理说明：
- Codex：https://learn.chatgpt.com/docs/config-file/config-reference
- Claude：https://code.claude.com/docs/en/plugins/cli-reference
- Antigravity：https://antigravity.google/docs/plugins?tab=cli

包内仅包含本项目源代码、网页资源及已有 Python 选择器。运行依赖全部由本机 Python
标准库提供，没有新增第三方库、远程脚本、字体或需随包附带的第三方许可证。
本机官方宿主的发现、加载与实际运行能力需要各宿主真实验收，不能从 BUILD_VERIFIED 推断。
"""


def read_source(source: Path, relative: str):
    """只读取物理普通文件；拒绝通过软链把工作流或用户目录夹入独立包。"""
    path = source / relative
    for part in (path, *path.parents):
        if part == source:
            break
        if part.is_symlink():
            raise ValueError("构建来源不能使用符号链接：" + relative)
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode):
        raise ValueError("构建来源必须是普通文件：" + relative)
    return path.read_bytes()


def payload(source: Path):
    source = source.resolve(strict=True)
    version = read_source(source, "native_config/VERSION").decode("ascii").strip()
    if not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+(?:-[A-Za-z0-9.-]+)?", version):
        raise ValueError("独立版本文件无效")
    root = source / "native_config"
    if root.is_symlink():
        raise ValueError("核心目录不能使用符号链接")
    # 两个独立产品只共享这三个标准库身份文件，不把工作流本体带入配置组件。
    load_identity(source)
    files = {name: read_source(source, name) for name in (
        "native_config/VERSION", "product/__init__.py", "product/command_identity.py", "product/command_identity.json")}
    for name in ("product/__init__.py", "product/command_identity.py"):
        for node in ast.walk(ast.parse(files[name], filename=name)):
            modules = [item.name for item in node.names] if isinstance(node, ast.Import) else [node.module or ""] if isinstance(node, ast.ImportFrom) else []
            if any(module.split(".")[0] not in sys.stdlib_module_names for module in modules):
                raise ValueError("共用身份合同包含非标准库依赖：" + name)
    # 模块表只来自这次实际打包的 Python 文件。相对依赖必须能在当前包中解析，
    # 不能因为省略绝对根名就绕过闭包检查，也不能越出 native_config 包边界。
    local_modules = set()
    for path in root.rglob("*.py"):
        if "__pycache__" not in path.parts:
            parts = path.relative_to(source).with_suffix("").parts
            local_modules.add(".".join(parts[:-1] if parts[-1] == "__init__" else parts))
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise ValueError("核心载荷不能使用符号链接")
        if "__pycache__" in path.parts or not path.is_file() or path.suffix != ".py":
            continue
        relative = path.relative_to(source).as_posix()
        body = read_source(source, relative)
        # 独立包不能碰巧靠源码根中的 lib/manager 导入成功；构建时先封闭依赖集合。
        for node in ast.walk(ast.parse(body, filename=relative)):
            if isinstance(node, ast.Import):
                modules = [item.name for item in node.names]
            elif isinstance(node, ast.ImportFrom):
                if node.level:
                    package = path.relative_to(source).parts[:-1]
                    if node.level > len(package):
                        raise ValueError("独立核心包含非标准库或工作流依赖：" + relative)
                    base = ".".join(package[:len(package) - node.level + 1])
                    # from . import x 导入实际子模块；from .x import y 只需 x 属于闭包，
                    # y 的运行时导出合同由真实独立包导入/启动验证，不伪造静态执行器。
                    dependencies = ([base + "." + node.module] if node.module else
                                    [base + "." + item.name for item in node.names])
                    if any(module not in local_modules for module in dependencies):
                        raise ValueError("独立核心包含非标准库或工作流依赖：" + relative)
                    continue
                modules = [node.module or ""]
            else:
                continue
            # 身份合同是唯一获准的本地依赖：精确模块、绝对导入与唯一函数都需匹配。
            # 不接受 product 的其他正文、星号或相对导入，避免白名单扩成工作流依赖。
            identity_import = (isinstance(node, ast.ImportFrom) and node.level == 0
                               and node.module == "product.command_identity"
                               and [(item.name, item.asname) for item in node.names] == [("load_identity", None)])
            if any(module.split(".")[0] not in sys.stdlib_module_names and module not in local_modules
                   and not identity_import for module in modules):
                raise ValueError("独立核心包含非标准库或工作流依赖：" + relative)
        files[relative] = body
    for name in ("index.html", "console.js", "console.css"):
        relative = "native_config/web/" + name
        files[relative] = read_source(source, relative)
    for name in ("agent_config.py", "agent_config.sh", "python_runtime.sh"):
        relative = "scripts/" + name
        files[relative] = read_source(source, relative)
    files["README.md"] = README.encode("utf-8")
    provenance = {"name": "native-agent-config", "version": version, "third_party_dependencies": [],
                  "files": {name: hashlib.sha256(body).hexdigest() for name, body in sorted(files.items())}}
    files["BUILD.json"] = (json.dumps(provenance, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode()
    return version, files


def build(source: Path, output_dir: Path):
    """固定时间戳、路径顺序与权限；相同源码产生相同字节，构建不访问网络。"""
    version, files = payload(source)
    output_dir.mkdir(parents=True, exist_ok=True)
    destination = output_dir / f"native-agent-config-{version}.zip"
    with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for name, body in sorted(files.items()):
            info = zipfile.ZipInfo(name, date_time=(2020, 1, 1, 0, 0, 0))
            info.create_system = 3
            info.external_attr = ((0o100755 if name.endswith(".sh") else 0o100644) << 16)
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, body)
    return {"artifact": str(destination), "version": version, "files": len(files),
            "sha256": hashlib.sha256(destination.read_bytes()).hexdigest(), "status": "BUILD_VERIFIED"}


def main():
    parser = argparse.ArgumentParser(description="离线构建独立原生 Agent 配置服务")
    parser.add_argument("--source", type=Path, default=ROOT)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    try:
        print(json.dumps(build(args.source, args.output_dir), ensure_ascii=False))
    except (ValueError, OSError, UnicodeError, SyntaxError):
        print("独立配置服务构建失败：请检查版本、物理来源及标准库依赖。", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
