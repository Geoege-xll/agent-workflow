#!/usr/bin/env python3
"""只读项目画像、显式创建最小适配器，并将实际路径交给原任务初始化器。"""

from __future__ import annotations

import argparse
from dataclasses import asdict
import json
import hashlib
from pathlib import Path
import tempfile
import os

from lib.hosts.claude_instructions import read_file
from lib import plugin_resources, task_graph_cli, task_graph_records as records
from lib.platform_fs import publish_exclusive
from lib.project.ensure_project_id import derive_project_id
from lib.project.validate_project_config import validate_with_profile
from lib.task_graph_init import initialize


ROOT = Path(__file__).resolve().parents[1]
ADAPTERS = ("project.yaml", ".awf/project.yaml")


def context(adapter: str | None = None) -> tuple[dict, bytes]:
    """画像只来自实际cwd及已选适配器；模板仅用于新配置候选，不冒充项目事实。"""
    if plugin_resources.plugin_root() != ROOT:
        raise ValueError("invoke project_context through the packaged source_pack helper")
    project = Path.cwd().resolve(strict=True)
    marker = project / ".agent-workflow/runtime.json"
    if marker.exists() or marker.is_symlink():
        raise ValueError("central project markers cannot be migrated by plugin bootstrap")
    existing = [name for name in ADAPTERS if (project / name).exists() or (project / name).is_symlink()]
    if adapter is None:
        if len(existing) > 1:
            raise ValueError("multiple project adapters exist; select one explicitly")
        adapter = existing[0] if existing else ".awf/project.yaml"
    if adapter not in ADAPTERS:
        raise ValueError("adapter must be project.yaml or .awf/project.yaml")
    if existing and adapter not in existing:
        raise ValueError("an existing project adapter must be selected explicitly; refusing to create a second adapter")
    target = project / adapter
    body = read_file(target)
    present = body is not None
    if body is None:
        if adapter != ".awf/project.yaml":
            raise ValueError("new adapters may only be created at .awf/project.yaml")
        template = plugin_resources.read_source("templates/project.yaml.example").decode("utf-8")
        template = template.replace("project_name: MyProject", "project_name: " + json.dumps(project.name, ensure_ascii=False), 1)
        # 名称相同的不同物理项目不能自动共用严格记忆命名空间；摘要不暴露原路径。
        # 仅新建配置时派生一次，已有项目ID随现有配置复用，不因移动目录重算。
        identifier = derive_project_id(project.name)[:48] + "-" + hashlib.sha256(str(project).encode("utf-8")).hexdigest()[:12]
        template = template.replace("project_id: replace-with-unique-project-id", "project_id: " + identifier, 1)
        body = template.encode("utf-8")
    checked = validate_with_profile(target, project, ROOT / "roles", config_bytes=body)
    if checked.errors or checked.profile is None:
        raise ValueError("invalid project adapter: " + "; ".join(checked.errors))
    return {"project": str(project), "adapter": adapter, "exists": present,
            "sha256": records.digest(body) if present else None,
            "profile": asdict(checked.profile), "created": False}, body


def apply(adapter: str) -> dict:
    """只在显式apply下创建缺失配置；排他发布不能覆盖另一工作者刚写入的文件。"""
    result, body = context(adapter)
    if result["exists"]:
        return result
    project = Path(result["project"])
    target = project / adapter
    directory = target.parent
    created_directory = not directory.exists()
    directory.mkdir(mode=0o700, exist_ok=True)
    temporary = None
    try:
        # 复用已有安全读取检查祖先类型；即使文件缺失，也先拒绝链接父目录。
        if read_file(target) is not None:
            raise ValueError("adapter appeared before publication; inspect the current project again")
        descriptor, raw = tempfile.mkstemp(prefix=".project.yaml-", dir=directory)
        temporary = Path(raw)
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(body)
            stream.flush()
            os.fsync(stream.fileno())
        publish_exclusive(temporary, target)
        temporary = None
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
        if created_directory and not target.exists():
            try:
                directory.rmdir()
            except OSError:
                pass  # 只清理本次仍为空的目录，保留其他工作者新增的内容。
    result.update(created=True, exists=True, sha256=records.digest(body))
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    inspect = commands.add_parser("inspect")
    inspect.add_argument("--adapter", choices=ADAPTERS)
    for command in ("apply", "init"):
        sub = commands.add_parser(command)
        sub.add_argument("--adapter", choices=ADAPTERS, required=True)
        if command == "init":
            sub.add_argument("--input", type=Path, required=True)
            sub.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        if args.command == "apply":
            result = apply(args.adapter)
        else:
            result, _ = context(args.adapter)
            if args.command == "init":
                if not result["exists"]:
                    raise ValueError("apply the selected project adapter explicitly before init")
                original = records.read_record(args.input)
                decisions = records.decode(original)
                if not isinstance(decisions, dict):
                    raise ValueError("init decisions must be an object")
                if decisions.get("adapter_path", args.adapter) != args.adapter:
                    raise ValueError("decision adapter conflicts with the explicitly selected project adapter")
                # 只投影真实适配器路径；不改需求、门禁、批准、规范选择或任务合同。
                decisions["adapter_path"] = args.adapter
                result = initialize(decisions, Path(result["project"]), args.output, task_graph_cli._execute,
                                    input_path=args.input, input_body=original)
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        return 0
    except (ValueError, OSError) as error:
        print(json.dumps({"error": str(error)}, ensure_ascii=False))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
