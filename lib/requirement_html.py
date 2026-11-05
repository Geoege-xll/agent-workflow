#!/usr/bin/env python3
"""把唯一需求 Markdown 投影为同目录 HTML；不产生批准、功能事实或原型指纹。"""

from __future__ import annotations

import argparse
import hashlib
from html.parser import HTMLParser
import json
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import subprocess
import sys
from urllib.parse import quote, unquote, urlsplit

if __package__:
    from .claude_instructions import atomic_write, read_file
    from .platform_fs import directory_lock, os
    from .task_graph_records import (
        _project_scratch_base, _validated_scratch_slot, publish, scratch_workspace,
    )
    from .validate_project_config import validate_docs
else:
    from claude_instructions import atomic_write, read_file
    from platform_fs import directory_lock, os
    from task_graph_records import (
        _project_scratch_base, _validated_scratch_slot, publish, scratch_workspace,
    )
    from validate_project_config import validate_docs


VENDOR = Path(__file__).absolute().parent / "vendor/answer-me-with-html"
BUNDLE_SHA256 = "c98ee6480fededc57b67ef160b348e915068b92aa10ad33fc1a17ff4e612ef83"
PROJECT_REPOSITORY = "https://github.com/Geoege-xll/agent-workflow"
UPSTREAM_REPOSITORY = "https://github.com/QingYunA/answer-me-with-html"
MARKER = b"<!-- agent-workflow:requirement-html:v1 "
LINK = re.compile(r"\[[^\]\n]*\]\(([^)\n]*)\)")
FENCE = re.compile(r"^ {0,3}(`{3,}|~{3,})(.*)$")
# 只开放本任务需要的内联代码和两类图。上游的图片、原始 HTML/SVG、src 文件导入
# 具有额外读取/嵌入能力，不能因已经 vendoring CLI 就顺便授予它们权限。
CODE_LANGUAGES = frozenset({
    "", "text", "plaintext", "json", "yaml", "yml", "python", "py", "bash", "sh",
    "shell", "javascript", "js", "typescript", "ts", "sql", "diff", "swift", "java",
    "go", "rust", "c", "cpp", "css", "toml", "markdown", "md", "flow", "sequence",
})


class RequirementHtmlError(ValueError):
    """可定位的输入、运行时或并发冲突；失败时不发布任何正式 HTML。"""


def digest(body: bytes) -> str:
    return hashlib.sha256(body).hexdigest()


def identity(info) -> tuple[int, ...]:
    # 访问时间可能因本次读取改变，不属于原稿保护或并发判断；其余节点/内容属性保留。
    return (info.st_dev, info.st_ino, info.st_mode, info.st_nlink,
            info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def snapshot(path: Path, *, required: bool = True) -> tuple[bytes | None, tuple | None]:
    """复用现有跨平台 no-follow/单链接/UTF-8 读取，并补上完整读取前后的身份检查。"""
    try:
        before = path.lstat()
    except FileNotFoundError:
        # 即使叶缺失，也让共用入口检查祖先，不能把链接祖先当作可写缺失路径。
        if read_file(path) is not None:
            raise RequirementHtmlError(f"读取期间文件出现：{path}")
        if required:
            raise RequirementHtmlError(f"文件不存在：{path}")
        return None, None
    body = read_file(path)
    if body is None or identity(before) != identity(path.lstat()) or len(body) != before.st_size:
        raise RequirementHtmlError(f"读取期间文件变化：{path}")
    return body, identity(before)


def normalized_relative(raw: str) -> Path:
    path = PurePosixPath(raw)
    if (not raw or "\\" in raw or "\0" in raw or path.is_absolute()
            or path.as_posix() != raw or any(part in {".", ".."} for part in path.parts)):
        raise RequirementHtmlError(f"须使用规范的相对路径：{raw!r}")
    return Path(raw)


def resolve_inputs(project: Path, source_raw: str, draft: bool, request_id: str | None):
    """正式稿只属于配置 plans；草案只属于当前请求 scratch，二者均不自动创建原稿。"""
    if ".." in project.parts:
        raise RequirementHtmlError("project 不得含 ..")
    root = project.absolute()
    # read_file 会核对每层真实祖先；根本身也必须存在且不是链接。
    if root.is_symlink() or not root.is_dir():
        raise RequirementHtmlError("project 必须是已有真实目录")
    installed = root / ".agent-workflow/project.yaml"
    config = installed if installed.exists() or installed.is_symlink() else root / "project.yaml"
    config_body, _ = snapshot(config)
    errors: list[str] = []
    docs = validate_docs(config_body.decode("utf-8").splitlines(), root, errors)
    if errors:
        raise RequirementHtmlError("项目 docs 配置无效：" + "; ".join(errors))
    plans = root / docs["plans"]
    if draft:
        if not request_id:
            raise RequirementHtmlError("--draft 必须同时提供 --request-id")
        scratch = _project_scratch_base(root) / _validated_scratch_slot(request_id)
        candidate = Path(source_raw)
        source = candidate if candidate.is_absolute() else root / normalized_relative(source_raw)
        if ".." in source.parts or not source.is_relative_to(scratch):
            raise RequirementHtmlError("草案只能位于当前 request-id 的 scratch 内")
        # 草案按未来正式 plans/<同名.md> 书写链接，批准后移动原字节即可继续使用。
        link_base = plans / source.name
    else:
        source = root / normalized_relative(source_raw)
        if not source.is_relative_to(plans):
            raise RequirementHtmlError("正式原稿只能位于配置 docs.plans 下")
        link_base = source
    if source.suffix != ".md":
        raise RequirementHtmlError("原稿必须是 .md 普通文件")
    body, source_identity = snapshot(source)
    return root, source, body, source_identity, link_base, root / docs["standards_root"] / "prototype"


class Anchors(HTMLParser):
    def __init__(self):
        super().__init__()
        self.ids: set[str] = set()

    def handle_starttag(self, tag, attrs):
        self.ids.update(value for name, value in attrs if name == "id" and value is not None)


def checked_link(root: Path, base: Path, prototype: Path, raw: str, line: int) -> Path | None:
    """只读取本稿实际引用的本地文件/状态锚点，不调用全原型树验证或改变原型导航合同。"""
    label = f"第 {line} 行链接 {raw!r}"
    split = urlsplit(raw)
    if split.scheme in {"http", "https", "mailto"} and not raw.startswith("//"):
        return None
    if split.scheme or split.netloc or split.query or "\\" in raw or raw.startswith("//"):
        raise RequirementHtmlError(f"{label}：不支持此链接形式")
    if not split.path:
        return None
    decoded = unquote(split.path)
    if (not decoded or decoded.startswith("/") or "\\" in decoded or "\0" in decoded
            or any(char.isspace() for char in decoded)):
        raise RequirementHtmlError(f"{label}：请使用无歧义的项目相对路径")
    # 允许 plans → standards/prototype 的必要 ..，逐段消费，不能越出项目根。
    parts = list(base.parent.relative_to(root).parts)
    for part in PurePosixPath(decoded).parts:
        if part == "..":
            if not parts:
                raise RequirementHtmlError(f"{label}：路径越出项目")
            parts.pop()
        elif part not in {"", "."}:
            parts.append(part)
    target = root.joinpath(*parts)
    if target.suffix not in {".md", ".html"}:
        raise RequirementHtmlError(f"{label}：本地链接只支持 Markdown 或具体原型 HTML 页")
    if target.suffix == ".html" and (target.parent != prototype or target.name == "index.html"):
        raise RequirementHtmlError(f"{label}：必须指向配置原型目录内的具体页面")
    try:
        body, _ = snapshot(target)
    except (OSError, ValueError) as exc:
        raise RequirementHtmlError(f"{label}：目标不存在或不是安全普通文件：{target}") from exc
    if target.suffix == ".html" and split.fragment:
        anchors = Anchors()
        anchors.feed(body.decode("utf-8"))
        if unquote(split.fragment) not in anchors.ids:
            raise RequirementHtmlError(f"{label}：原型状态锚点不存在")
    return target


def stage_markdown(body: bytes, root: Path, source: Path, base: Path, prototype: Path) -> bytes:
    """校验受控 Markdown；草案仅在舞台副本重定位链接，唯一原稿字节始终不写。"""
    text = body.decode("utf-8")
    # 嵌入权限不能依赖自写的 Markdown 代码跨度识别：转义反引号并不一定构成代码，
    # HTML 标签也允许换行。此入口有意只接收更窄的子集，在整稿上拒绝资源/标签起始串，
    # 即使它们看起来位于代码中也不豁免；因此不必重造解析器或先运行可能读取图片的 CLI。
    forbidden = re.search(r"!\s*\[|<\s*/?\s*[A-Za-z!?]", text)
    if forbidden:
        line = text.count("\n", 0, forbidden.start()) + 1
        raise RequirementHtmlError(f"第 {line} 行：不支持图片或原始 HTML；转义、行内代码和代码围栏也不能包含这些标记")
    lines = text.splitlines(keepends=True)
    fence: str | None = None
    output: list[str] = []
    for number, original in enumerate(lines, 1):
        match = FENCE.match(original)
        if match:
            token, arguments = match.groups()
            if token != "```" or not original.startswith("```"):
                raise RequirementHtmlError(f"第 {number} 行：请使用顶格的三个反引号围栏")
            if fence is None:
                language = arguments.strip().split(maxsplit=1)[0] if arguments.strip() else ""
                if language not in CODE_LANGUAGES or re.search(r"\bsrc\s*=", arguments, re.I):
                    raise RequirementHtmlError(f"第 {number} 行：不支持该代码围栏或 src 文件导入")
                fence = token[0]
            elif token[0] == fence and not arguments.strip():
                fence = None
            output.append(original)
            continue
        if fence is not None:
            output.append(original)
            continue
        # 普通链接也按原始文字检查；不再凭反引号外观跳过实际可能生效的链接。
        # 代码样例若需要展示链接语法，仍须满足相同的项目路径约束。
        visible = original
        if (number == 1 and original.strip() == "---"):
            raise RequirementHtmlError("第 1 行：需求稿不支持渲染器 frontmatter；请使用普通 Markdown 标题")
        if re.match(r"^\s{0,3}\[[^\]]+\]:", visible):
            raise RequirementHtmlError(f"第 {number} 行：不支持引用式链接")
        matches = list(LINK.finditer(visible))
        if "](" in LINK.sub("", visible):
            raise RequirementHtmlError(f"第 {number} 行：无法无损处理链接语法，请使用普通 [文字](相对路径)")
        replacements: list[tuple[int, int, str]] = []
        for match in matches:
            raw = match.group(1)
            if not raw or any(char.isspace() for char in raw):
                raise RequirementHtmlError(f"第 {number} 行：链接目标不得为空或带标题/空白")
            target = checked_link(root, base, prototype, raw, number)
            if target is not None and source != base:
                split = urlsplit(raw)
                try:
                    relative = Path(os.path.relpath(target, source.parent)).as_posix()
                except ValueError:
                    raise RequirementHtmlError(f"第 {number} 行链接 {raw!r}：草案链接跨文件系统根，无法安全重定位") from None
                replacements.append((match.start(1), match.end(1),
                                     quote(relative, safe="/.-_") + ("#" + split.fragment if split.fragment else "")))
        # 在原行的匹配位置替换，不能全局替换而污染正文或相同文本的行内代码。
        for start, stop, replacement in reversed(replacements):
            original = original[:start] + replacement + original[stop:]
        output.append(original)
    if fence is not None:
        raise RequirementHtmlError("代码围栏未闭合")
    return "".join(output).encode("utf-8")


def renderer_identity() -> str:
    bundle, _ = snapshot(VENDOR / "am.mjs")
    if digest(bundle) != BUNDLE_SHA256:
        raise RequirementHtmlError("内置渲染器字节与固定上游不匹配，请恢复安装载荷")
    helper, _ = snapshot(Path(__file__).absolute())
    return ("answer-me-with-html/0.5.10:" + BUNDLE_SHA256 + ":brand:" + PROJECT_REPOSITORY
            + ":adapter:" + digest(helper))


def project_branding(page: bytes) -> bytes:
    """仅适配生成页的固定展示区；正文、脚本、法律来源和 vendored 原件均不替换。

    固定 bundle 若改变页脚结构则明确失败，不能全局替换正文中合法的上游引用。
    适配器字节、项目仓库与最终 HTML 摘要都属于现有 renderer/page 身份校验。
    """
    text = page.decode("utf-8")
    matches = list(re.finditer(r'<p class="am-colophon">.*?</p>', text, re.S))
    if len(matches) != 1:
        raise RequirementHtmlError("固定渲染器的品牌区域不匹配，原页保留")
    match = matches[0]
    footer = match.group()
    old_link = f'href="{UPSTREAM_REPOSITORY}"'
    if footer.count(old_link) != 2 or ">Answer me with HTML</a>" not in footer:
        raise RequirementHtmlError("固定渲染器的项目链接不匹配，原页保留")
    footer = footer.replace(old_link, f'href="{PROJECT_REPOSITORY}"').replace(
        ">Answer me with HTML</a>", ">agent-workflow</a>")
    footer = footer[:-4] + (f' · 渲染器来源：<a href="{UPSTREAM_REPOSITORY}" '
                            'target="_blank" rel="noopener">Answer me with HTML</a></p>')
    text = text[:match.start()] + footer + text[match.end():]
    text = text.replace('<meta name="generator" content="Answer me with HTML 0.5.10">',
                        '<meta name="generator" content="agent-workflow (Answer me with HTML 0.5.10)">', 1)
    return text.encode("utf-8")


def page_record(page: bytes, binding: dict) -> tuple[dict, bytes]:
    if not page.startswith(MARKER) or b" -->\n" not in page[:4096]:
        raise RequirementHtmlError("已有 HTML 没有本工具版本记录，保留原页；请先明确处置该文件")
    header, payload = page[len(MARKER):].split(b" -->\n", 1)
    try:
        record = json.loads(header)
    except (ValueError, UnicodeError):
        raise RequirementHtmlError("已有 HTML 版本记录损坏，保留原页") from None
    if (not isinstance(record, dict) or record.get("project") != binding["project"]
            or record.get("source") != binding["source"] or record.get("draft") != binding["draft"]):
        raise RequirementHtmlError("已有 HTML 不属于当前原稿，保留原页")
    if record.get("html_sha256") != digest(payload):
        raise RequirementHtmlError("已有 HTML 已被修改，保留原页；请恢复派生页后重渲染")
    return record, payload


def node_environment(stage: Path) -> dict[str, str]:
    # 不继承 NODE_OPTIONS/NODE_PATH、AM_*、模型密钥或代理凭据；仅保留系统执行所需值。
    # TMP 三入口也指向任务舞台，使上游 AM_HOME 失败后的临时回退仍不能写个人目录。
    allowed = {"PATH", "SystemRoot", "SYSTEMROOT", "WINDIR", "COMSPEC", "PATHEXT", "LANG", "LC_ALL"}
    env = {key: value for key, value in os.environ.items() if key in allowed}
    env.update({"AM_HOME": str(stage / "am-home"), "AM_NO_UPDATE_CHECK": "1", "AM_NO_OPEN": "1",
                "TMPDIR": str(stage), "TMP": str(stage), "TEMP": str(stage)})
    return env


def run_renderer(stage: Path, markdown: bytes) -> bytes:
    node = shutil.which("node")
    if node is None:
        raise RequirementHtmlError("需求 HTML 渲染需要 Node.js >= 20；请提供现有 Node 运行时后重试")
    env = node_environment(stage)
    try:
        version = subprocess.run([node, "--version"], env=env, capture_output=True, timeout=5, check=True)
        found = re.fullmatch(rb"v(\d+)\.\d+\.\d+\s*", version.stdout)
        if not found or int(found.group(1)) < 20:
            raise RequirementHtmlError("需求 HTML 渲染需要 Node.js >= 20；当前 Node 版本不满足要求")
        for path in stage.rglob("*"):
            info = path.lstat()
            if stat.S_ISLNK(info.st_mode) or (not stat.S_ISDIR(info.st_mode) and
                    (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1)):
                raise RequirementHtmlError(f"渲染舞台存在链接或特殊节点：{path}")
        # 固定私有舞台不接受额外主题和配置，以免上游隐式消费非本轮内容。
        home = stage / "am-home"
        if (home / "config.json").exists() or (home / "themes").exists():
            raise RequirementHtmlError("渲染舞台出现非本轮配置/主题，拒绝消费")
        input_path, output_path = stage / "input.md", stage / "output.html"
        snapshot(input_path, required=False)
        snapshot(output_path, required=False)
        atomic_write(input_path, markdown, 0o600)
        command = [node, str(VENDOR / "am.mjs"), "render", str(input_path), "-o", str(output_path),
                   "--no-open", "--template", "doc", "--style", "off"]
        result = subprocess.run(command, cwd=stage, env=env, capture_output=True, timeout=30)
        if result.returncode:
            # 上游报错可能回显正文，因此主 CLI 仅给定位诊断；完整过程输出不注入用户页面。
            raise RequirementHtmlError(f"内置 render 失败（exit {result.returncode}），原稿和原 HTML 保留")
        html, _ = snapshot(output_path)
        if b"<html" not in html or b"am-source" not in html:
            raise RequirementHtmlError("内置 render 未返回完整 HTML，原页保留")
        return project_branding(html)
    except subprocess.TimeoutExpired:
        raise RequirementHtmlError("Node 渲染超时并已结束，原稿和原 HTML 保留") from None
    except subprocess.CalledProcessError:
        raise RequirementHtmlError("无法取得 Node 版本，原稿和原 HTML 保留") from None


def render_candidate(root: Path, source: Path, body: bytes, base: Path, prototype: Path,
                     request_id: str, *, draft: bool = False) -> bytes:
    """只在当前请求 scratch 渲染候选字节，绝不发布/替换原稿或正式 HTML。

    普通投影和多文件迁移共用相同输入校验、固定渲染器、隔离环境与版本记录。
    调用者保有原稿/页面前像，并在自己的条件发布边界重新核对；这里不假定跨文件
    原子性，也不让迁移先写 Markdown 再以补渲染掩盖失败或覆盖用户原页。
    """
    staged = stage_markdown(body, root, source, base, prototype)
    binding = {"project": str(root), "source": str(source.relative_to(root)) if not draft else str(source),
               "draft": draft}
    expected = {**binding, "source_sha256": digest(body), "renderer": renderer_identity()}
    if not request_id:
        raise RequirementHtmlError("render 必须提供 --request-id")
    scratch = Path(scratch_workspace(root, request_id)["scratch_dir"])
    stage = scratch / "requirement-html"
    # scratch 锁只保护固定舞台的建立；草案 HTML 也发布到 scratch，不能持有此锁
    # 再进入 publish 的同目录锁。实际渲染互斥交给舞台目录锁，二者不嵌套。
    with directory_lock(scratch, "requirement-html"):
        try:
            os.mkdir(stage, 0o700)
        except FileExistsError:
            pass
    with directory_lock(stage, "requirement-html"):
        html = run_renderer(stage, staged)
        expected["html_sha256"] = digest(html)
        # 路径属于外部输入；转义尖括号，避免特殊文件名提前结束 HTML 注释。
        header = json.dumps(expected, ensure_ascii=True, sort_keys=True).replace("<", "\\u003c").replace(">", "\\u003e")
        return MARKER + header.encode() + b" -->\n" + html


def process(action: str, project: Path, source_raw: str, request_id: str | None = None,
            *, draft: bool = False) -> dict:
    root, source, body, before_identity, base, prototype = resolve_inputs(project, source_raw, draft, request_id)
    stage_markdown(body, root, source, base, prototype)
    binding = {"project": str(root), "source": str(source.relative_to(root)) if not draft else str(source),
               "draft": draft}
    expected = {**binding, "source_sha256": digest(body), "renderer": renderer_identity()}
    target = source.with_suffix(".html")
    old, target_identity = snapshot(target, required=False)
    if old is not None:
        record, _ = page_record(old, binding)
        if all(record.get(key) == value for key, value in expected.items()):
            if snapshot(source) != (body, before_identity) or snapshot(target) != (old, target_identity):
                raise RequirementHtmlError("检查期间原稿或目标被并发修改")
            return {"status": "fresh", "source": str(source), "html": str(target), "rendered": False}
    if action == "check":
        raise RequirementHtmlError("需求 HTML 缺失或已过期，请对同一 Markdown 执行 render")
    page = render_candidate(root, source, body, base, prototype, request_id, draft=draft)
    # 候选准备完成后再复核原稿与原页；publish 继续以旧摘要条件原子替换，
    # 多文件迁移则直接消费候选字节并由既有文档事务统一发布，不调用本入口补渲染。
    if snapshot(source) != (body, before_identity) or snapshot(target, required=False) != (old, target_identity):
        raise RequirementHtmlError("生成期间原稿或目标被并发修改，原稿和原 HTML 保留")
    publish(target, page, "missing" if old is None else digest(old))
    return {"status": "fresh", "source": str(source), "html": str(target), "rendered": True}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("render", "check"))
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--source", required=True)
    parser.add_argument("--request-id")
    parser.add_argument("--draft", action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.action == "render" and not args.request_id:
            raise RequirementHtmlError("render 必须提供 --request-id")
        result = process(args.action, args.project, args.source, args.request_id, draft=args.draft)
    except (OSError, ValueError) as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
