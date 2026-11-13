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

README = """# Native Agent Config

独立管理 Codex、Claude Code 与 Antigravity 已发现的原生 Agent 模型字段。
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
    files = {"native_config/VERSION": read_source(source, "native_config/VERSION")}
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
            elif isinstance(node, ast.ImportFrom) and not node.level:
                modules = [node.module or ""]
            else:
                continue
            if any(module.split(".")[0] not in sys.stdlib_module_names | {"native_config"} for module in modules):
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
