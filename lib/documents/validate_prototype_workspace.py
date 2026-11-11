#!/usr/bin/env python3
"""Strict, read-only validation for the active HTML prototype workspace."""

from __future__ import annotations

# 直接脚本只信任自身物理位置确定的核心根，避免异 cwd 或 PYTHONPATH 中的
# 同名模块劫持内部依赖；正常包导入沿用调用方已选择的固定核心。
if not __package__:
    import sys as _sys
    from pathlib import Path as _Path
    _sys.path.insert(0, str(_Path(__file__).resolve().parents[2]))

import argparse
import hashlib
import json
if __package__:
    from lib.platform_fs import os
    from lib.documents.prototype_navigation import RequirementNavigation
else:
    from lib.platform_fs import os
    from lib.documents.prototype_navigation import RequirementNavigation
import re
import stat
import sys
from collections import Counter
from html.parser import HTMLParser
from pathlib import Path, PurePosixPath
from urllib.parse import unquote, urlsplit


MAX_TEXT_FILE_SIZE = 4 * 1024 * 1024
MAX_DEPENDENCY_SIZE = 32 * 1024 * 1024
MAX_DEPENDENCY_TOTAL_SIZE = 64 * 1024 * 1024
MAX_DEPENDENCY_NODES = 256
MAX_DEPENDENCY_DEPTH = 16
# 固定域版本属于公共编码合同；后续若调整闭包或编码语义，必须显式换版本，
# 不能让同名指纹悄悄代表另一种证据。
FINGERPRINT_DOMAIN = b"agent-workflow/prototype-dependency-fingerprint/v1\0"
MANDATORY_SECTIONS = (
    "purpose",
    "navigation",
    "interactions",
    "states",
    "exceptions",
)
BUTTON_INPUT_TYPES = {"button", "submit", "reset", "image"}
HTML_VOID_ELEMENTS = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}
TEXT_DEPENDENCY_SUFFIXES = {
    ".css",
    ".js",
    ".mjs",
    ".cjs",
    ".html",
    ".htm",
    ".json",
    ".svg",
    ".txt",
}
STABLE_ID_PATTERN = re.compile(r"[A-Za-z][A-Za-z0-9_-]*\Z")
VERSION_COPY_PATTERN = re.compile(
    r"(?:\A[0-9]{4}-[0-9]{2}-[0-9]{2}-|"
    r"-(?:r[0-9]+|v[0-9]+|final|new|[0-9]{4}-[0-9]{2}-[0-9]{2})(?:-copy)?\Z)",
    re.IGNORECASE,
)
PLACEHOLDER_PATTERN = re.compile(
    r"(?:tbd|todo|n/?a|not\s+applicable|none|placeholder)[.!]?\Z",
    re.IGNORECASE,
)
EXTERNAL_SCHEMES = {"http", "https"}
DIRECTORY_FLAGS = (
    os.O_RDONLY
    | getattr(os, "O_CLOEXEC", 0)
    | getattr(os, "O_NOFOLLOW", 0)
    | getattr(os, "O_DIRECTORY", 0)
)
REGULAR_FLAGS = (
    os.O_RDONLY
    | getattr(os, "O_CLOEXEC", 0)
    | getattr(os, "O_NOFOLLOW", 0)
    | getattr(os, "O_NONBLOCK", 0)
)
FileIdentity = tuple[int, int, int, int, int]


class ValidationError(ValueError):
    """A prototype artifact violates the controlled workspace contract."""


def _safe_relative_path(raw: str, label: str) -> PurePosixPath:
    if not raw or "\\" in raw:
        raise ValidationError(f"{label} must be a non-empty POSIX relative path")
    path = PurePosixPath(raw)
    if path.is_absolute() or not path.parts or any(
        part in {"", ".", ".."} for part in path.parts
    ):
        raise ValidationError(f"unsafe relative path for {label}: {raw}")
    return path


def _open_root(path: str | Path, label: str) -> int:
    raw_path = os.fspath(path)
    if not raw_path:
        raise ValidationError(f"{label} path must not be empty")
    if any(component == ".." for component in raw_path.split("/")):
        raise ValidationError(f"unsafe parent path component in {label}: {raw_path}")
    parsed_path = Path(raw_path)
    raw_parts = parsed_path.parts
    absolute = parsed_path.is_absolute()
    components = raw_parts[1:] if absolute else raw_parts
    anchor = Path(parsed_path.anchor) if absolute else Path(".")
    try:
        descriptor = os.open(anchor, DIRECTORY_FLAGS)
    except OSError as exc:
        raise ValidationError(
            f"cannot securely open {label} anchor as a real directory: {anchor}: {exc}"
        ) from exc
    try:
        for component in components:
            next_descriptor = _open_directory_at(descriptor, component, label)
            os.close(descriptor)
            descriptor = next_descriptor
        info = os.fstat(descriptor)
        if not stat.S_ISDIR(info.st_mode):
            raise ValidationError(f"{label} must be a real directory: {raw_path}")
        return descriptor
    except Exception:
        os.close(descriptor)
        raise


def _open_directory_at(parent_fd: int, name: str, label: str) -> int:
    try:
        descriptor = os.open(name, DIRECTORY_FLAGS, dir_fd=parent_fd)
    except OSError as exc:
        raise ValidationError(
            f"cannot securely open {label} as a real no-follow directory: {exc}"
        ) from exc
    info = os.fstat(descriptor)
    if not stat.S_ISDIR(info.st_mode):
        os.close(descriptor)
        raise ValidationError(f"{label} must be a real directory")
    return descriptor


def _walk_directory(root_fd: int, relative: PurePosixPath, label: str) -> int:
    descriptor = os.dup(root_fd)
    try:
        for component in relative.parts:
            next_descriptor = _open_directory_at(descriptor, component, label)
            os.close(descriptor)
            descriptor = next_descriptor
        return descriptor
    except Exception:
        os.close(descriptor)
        raise


def _open_regular_at(
    parent_fd: int,
    name: str,
    label: str,
    *,
    size_limit: int,
) -> int:
    try:
        descriptor = os.open(name, REGULAR_FLAGS, dir_fd=parent_fd)
    except OSError as exc:
        raise ValidationError(f"cannot securely open {label}: {exc}") from exc
    info = os.fstat(descriptor)
    if not stat.S_ISREG(info.st_mode):
        os.close(descriptor)
        raise ValidationError(f"{label} must be a real regular file")
    if info.st_nlink != 1:
        os.close(descriptor)
        raise ValidationError(f"hard link is forbidden for {label}")
    if info.st_size > size_limit:
        os.close(descriptor)
        raise ValidationError(f"{label} exceeds {size_limit} bytes")
    return descriptor


def _read_descriptor(descriptor: int, label: str, size_limit: int) -> bytes:
    chunks: list[bytes] = []
    total = 0
    try:
        while True:
            chunk = os.read(
                descriptor,
                min(1024 * 1024, size_limit + 1 - total),
            )
            if not chunk:
                return b"".join(chunks)
            chunks.append(chunk)
            total += len(chunk)
            if total > size_limit:
                raise ValidationError(f"{label} exceeds {size_limit} bytes")
    except ValidationError:
        raise
    except OSError as exc:
        raise ValidationError(f"cannot read {label}: {exc}") from exc


def _file_identity(info: os.stat_result) -> FileIdentity:
    return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def _attrs(attributes: list[tuple[str, str | None]], label: str) -> dict[str, str]:
    names = [name.casefold() for name, _ in attributes]
    duplicates = [name for name, count in Counter(names).items() if count > 1]
    if duplicates:
        raise ValidationError(f"duplicate HTML attribute in {label}: {duplicates[0]}")
    return {
        name.casefold(): "" if value is None else value
        for name, value in attributes
    }


def _classes(value: str) -> set[str]:
    return {item for item in value.split() if item}


def _normalized_text(parts: list[str]) -> str:
    return " ".join(" ".join(parts).split()).strip()


def _is_placeholder_text(text: str) -> bool:
    if PLACEHOLDER_PATTERN.fullmatch(text):
        return True
    folded = text.casefold().strip()
    if re.match(r"^todo\s*[:—-]\s*(?:fill|pending|add|write|complete|define|replace)\b", folded):
        return True
    if re.match(
        r"^tbd(?:\s*[:—-]|\s+)\s*(?:pending|fill|define|design|later)\b",
        folded,
    ):
        return True
    if re.match(r"^placeholder(?:\s+content)?(?:[.!]|\Z)", folded):
        return True
    if folded.startswith("not applicable") and not re.match(
        r"^not applicable because\s+\S.{7,}", folded
    ):
        return True
    return False


def _resolve_local_reference(
    source: PurePosixPath,
    raw_reference: str,
    label: str,
) -> PurePosixPath | None:
    reference = raw_reference.strip()
    if not reference:
        raise ValidationError(f"empty local reference in {label}")
    if "\\" in reference or reference.startswith("//"):
        raise ValidationError(f"external or unsafe dependency in {label}: {reference}")
    split = urlsplit(reference)
    if split.scheme.casefold() in EXTERNAL_SCHEMES or split.netloc or split.scheme:
        raise ValidationError(f"external dependency in {label}: {reference}")
    if not split.path:
        return None
    decoded_path = unquote(split.path)
    if not decoded_path or decoded_path.startswith("/") or "\\" in decoded_path:
        raise ValidationError(f"unsafe local dependency in {label}: {reference}")

    output: list[str] = list(source.parent.parts)
    for component in PurePosixPath(decoded_path).parts:
        if component in {"", "."}:
            continue
        if component == "..":
            if not output:
                raise ValidationError(
                    f"local dependency escapes the prototype workspace in {label}: {reference}"
                )
            output.pop()
            continue
        output.append(component)
    if not output:
        raise ValidationError(f"local dependency is not a file in {label}: {reference}")
    return PurePosixPath(*output)


class IndexParser(HTMLParser):
    """Collect the thin index structure without executing or rendering it."""

    FORBIDDEN_TAGS = {
        "base",
        "dialog",
        "embed",
        "form",
        "frame",
        "frameset",
        "img",
        "input",
        "manifest",
        "object",
        "source",
        "style",
        "video",
        "audio",
        "main",
        "section",
        "article",
    }

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.nav_depth = 0
        self.prototype_nav_count = 0
        self.page_links: list[str] = []
        self.references: list[tuple[str, str]] = []
        self.doctype_count = 0
        self.document_counts: Counter[str] = Counter()
        self.document_depths: Counter[str] = Counter()
        self.group_summaries: list[int] = []
        self.group_summary_depth = 0
        self.navigation_id = ""
        self.element_stack: list[str] = []
        self.preview_target: str | None = None
        self.preview_depth = 0
        self.preview_count = 0
        self.preview_hidden = False
        self.controller_count = 0
        self.script_depth = 0
        self.inline_script: list[str] = []
        self.workspace_tags: set[str] = set()
        self.empty_state_count = 0

    def handle_decl(self, declaration: str) -> None:
        if declaration.strip().casefold() != "doctype html":
            raise ValidationError("prototype index must use the HTML5 doctype")
        self.doctype_count += 1

    def handle_starttag(
        self, tag: str, attributes: list[tuple[str, str | None]]
    ) -> None:
        tag = tag.casefold()
        attrs = _attrs(attributes, "prototype index")
        if tag == "meta" and attrs.get("http-equiv", "").strip().casefold() == "refresh":
            raise ValidationError("prototype index must not redirect through meta refresh")
        if any(name.startswith("on") for name in attrs):
            raise ValidationError("prototype index must use its local controller instead of inline event handlers")
        if attrs.get("id") == "prototype-preview" and tag != "iframe":
            raise ValidationError("prototype-preview id is reserved for the controlled index iframe")
        if tag in {"html", "head", "body"}:
            self.document_counts[tag] += 1
            self.document_depths[tag] += 1
        if tag in self.FORBIDDEN_TAGS:
            raise ValidationError(f"thin prototype index must not contain <{tag}>")
        if tag in {"aside", "button"}:
            self.workspace_tags.add(tag)
        if attrs.get("id") == "prototype-empty":
            self.empty_state_count += 1
        if tag == "script":
            # 工作区只加载真实共享控制器，不开放任意 index 脚本或内联程序。
            if attrs.get("src") != "workspace.js" or self.controller_count:
                raise ValidationError("prototype index permits only its one local workspace.js controller")
            if attrs.get("type", "").casefold() not in {"", "text/javascript"}:
                raise ValidationError("prototype workspace controller must use its supported classic script type")
            self.controller_count += 1
            self.script_depth += 1
            self.references.append(("src", "workspace.js"))
        if "prototype-contract" in _classes(attrs.get("class", "")):
            raise ValidationError("thin prototype index must not contain a page contract")
        if "data-contract-section" in attrs or "data-contract-for" in attrs:
            raise ValidationError("thin prototype index must not contain contract metadata")
        for structural_attribute in (attrs.get("id", ""), attrs.get("class", "")):
            if re.search(
                r"(?:\A|[-_:])manifest(?:\Z|[-_:])",
                structural_attribute,
                re.IGNORECASE,
            ):
                raise ValidationError(
                    "thin prototype index must not contain manifest-style structure"
                )
        if tag == "nav":
            if attrs.get("aria-label") != "Prototype pages":
                raise ValidationError(
                    "thin prototype index may contain only the Prototype pages navigation region"
                )
            self.prototype_nav_count += 1
            self.nav_depth += 1
            self.navigation_id = attrs.get("id", "")
        if tag == "details":
            # 分组只扩展唯一页面导航，不能借原生折叠容器在目录中塞入另一份产品说明。
            if not self.nav_depth or self.group_summary_depth or self.navigation_id != "prototype-pages":
                raise ValidationError("prototype index groups must stay inside the page navigation")
            self.group_summaries.append(0)
        if tag == "summary":
            if (not self.group_summaries or self.group_summary_depth
                    or not self.element_stack or self.element_stack[-1] != "details"):
                raise ValidationError("prototype index summary must belong to a navigation group")
            self.group_summaries[-1] += 1
            if self.group_summaries[-1] != 1:
                raise ValidationError("prototype index group must contain exactly one summary")
            self.group_summary_depth += 1
        if tag == "iframe":
            # 这里只开放已批准的 index 单页承载，不把普通产品页或任意 HTML 当成嵌入工作区。
            # src 必须是登记页的原始规范文件名；不接受重定向、文档路径或脚本内联变更来源。
            if self.preview_count or attrs.get("id") != "prototype-preview":
                raise ValidationError("prototype index permits only one iframe with id prototype-preview")
            if self.nav_depth or self.document_depths["body"] != 1 or self.document_depths["head"]:
                raise ValidationError("controlled prototype preview must be inside the index body, outside navigation")
            if any(name in attrs for name in ("srcdoc", "style", "srcset")) or any(name.startswith("on") for name in attrs):
                raise ValidationError("controlled prototype preview forbids inline content, styles and event handlers")
            target = attrs.get("src")
            if target is not None and (target == "index.html" or not re.fullmatch(r"[a-z0-9][a-z0-9-]*\.html", target)):
                raise ValidationError("controlled prototype preview src must name a registered concrete local page")
            if target is None and "hidden" not in attrs:
                raise ValidationError("uninitialized prototype preview must be hidden without src")
            if not (attrs.get("title", "").strip() or attrs.get("aria-label", "").strip()):
                raise ValidationError("controlled prototype preview needs an accessible name")
            self.preview_target = target
            self.preview_count += 1
            self.preview_hidden = "hidden" in attrs
            self.preview_depth = 1
            # iframe 是真实渲染资源，而非需求文档导航；沿原闭包入口验证具体页和全部依赖。
            if target is not None:
                self.references.append(("src", target))
        if tag == "a" and "href" in attrs:
            if not self.nav_depth:
                raise ValidationError(
                    "thin prototype index page links must stay inside the Prototype pages navigation region"
                )
            href = attrs["href"].strip()
            if href == "index.html" or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9-]*\.html", href):
                raise ValidationError(
                    f"thin prototype index contains a non-page or non-canonical link: {href}"
                )
            self.page_links.append(href)
        if tag in {"link", "img", "source", "video", "audio"}:
            if tag == "link":
                relations = {item.casefold() for item in attrs.get("rel", "").split()}
                if relations != {"stylesheet"}:
                    raise ValidationError(
                        "thin prototype index permits only its local stylesheet link"
                    )
            for attribute in ("href", "src"):
                if attribute in attrs:
                    self.references.append((attribute, attrs[attribute]))
        if "srcset" in attrs:
            for candidate in attrs["srcset"].split(","):
                fields = candidate.strip().split()
                if not fields:
                    raise ValidationError("empty srcset candidate in prototype index")
                self.references.append(("srcset", fields[0]))
        if tag not in HTML_VOID_ELEMENTS:
            self.element_stack.append(tag)

    def handle_startendtag(
        self, tag: str, attributes: list[tuple[str, str | None]]
    ) -> None:
        self.handle_starttag(tag, attributes)

    def handle_endtag(self, tag: str) -> None:
        tag = tag.casefold()
        if tag == "summary":
            if not self.group_summary_depth:
                raise ValidationError("unexpected closing summary in prototype index")
            self.group_summary_depth -= 1
        if tag == "details":
            if not self.group_summaries or self.group_summaries.pop() != 1 or self.group_summary_depth:
                raise ValidationError("prototype index group must contain one closed summary")
        if tag == "iframe":
            if not self.preview_depth:
                raise ValidationError("unexpected closing iframe in prototype index")
            self.preview_depth -= 1
        if tag == "script":
            if not self.script_depth:
                raise ValidationError("unexpected closing script in prototype index")
            self.script_depth -= 1
        if tag == "nav":
            if not self.nav_depth:
                raise ValidationError("unexpected closing navigation tag in prototype index")
            if self.group_summaries:
                raise ValidationError("prototype index navigation group must be closed")
            self.nav_depth -= 1
        if tag in {"html", "head", "body"}:
            if not self.document_depths[tag]:
                raise ValidationError(f"unexpected closing <{tag}> in prototype index")
            self.document_depths[tag] -= 1
        if tag in self.element_stack:
            position = len(self.element_stack) - 1 - self.element_stack[::-1].index(tag)
            del self.element_stack[position:]

    def handle_data(self, data: str) -> None:
        if self.script_depth:
            self.inline_script.append(data)


class PageParser(HTMLParser):
    """Collect one active page's structural contract and local dependencies."""

    def __init__(self, label: str) -> None:
        super().__init__(convert_charrefs=True)
        self.label = label
        self.contract_count = 0
        self.contract_depth = 0
        self.summary_depth = 0
        self.summary_parts: list[str] = []
        self.current_section: str | None = None
        self.section_text: dict[str, list[str]] = {}
        self.section_order: list[str] = []
        self.heading_depth = 0
        self.ids: list[str] = []
        self.material_controls: list[str] = []
        self.interactive_ids: list[str] = []
        self.mappings: list[str] = []
        self.dialog_ids: list[str] = []
        self.dialog_stack: list[str] = []
        self.dialog_form_stack: list[str | None] = []
        self.native_close_dialogs: set[str] = set()
        self.references: list[tuple[str, str]] = []
        self.script_depth = 0
        self.script_parts: list[str] = []
        self.style_depth = 0
        self.style_parts: list[str] = []
        self.doctype_count = 0
        self.document_counts: Counter[str] = Counter()
        self.document_depths: Counter[str] = Counter()
        self.details_depth = 0
        self.plan_source = ""
        self.requirement_nav_count = 0
        self.navigation_stack: list[bool] = []
        self.requirement_links: list[tuple[str, str]] = []
        self.element_stack: list[str] = []
        self.details_summary_seen: list[bool] = []

    def handle_decl(self, declaration: str) -> None:
        if declaration.strip().casefold() != "doctype html":
            raise ValidationError(f"{self.label} must use the HTML5 doctype")
        self.doctype_count += 1

    def handle_starttag(
        self, tag: str, attributes: list[tuple[str, str | None]]
    ) -> None:
        tag = tag.casefold()
        attrs = _attrs(attributes, self.label)
        # 具体页被承载后也不能用声明式刷新绕过唯一登记路由；该入口不属于普通文档导航。
        if tag == "meta" and attrs.get("http-equiv", "").strip().casefold() == "refresh":
            raise ValidationError(f"prototype page must not redirect through meta refresh in {self.label}")
        if tag in {"iframe", "frame", "frameset"}:
            raise ValidationError(f"embedded frames are supported only by the controlled prototype index, not {self.label}")
        classes = _classes(attrs.get("class", ""))
        if tag in {"html", "head", "body"}:
            self.document_counts[tag] += 1
            self.document_depths[tag] += 1
        if "data-prototype-plan-source" in attrs:
            if tag != "body":
                raise ValidationError(f"requirement source must be declared on body in {self.label}")
            self.plan_source = attrs["data-prototype-plan-source"]
        if "prototype-requirement-links" in classes:
            if tag != "nav":
                raise ValidationError(f"requirement links must use a nav element in {self.label}")
            self.requirement_nav_count += 1
            if self.requirement_nav_count != 1 or any(self.navigation_stack):
                raise ValidationError(f"requirement navigation must be unique in {self.label}")
        if tag == "nav":
            self.navigation_stack.append("prototype-requirement-links" in classes)
        in_requirement_navigation = any(self.navigation_stack)
        if "data-prototype-document" in attrs and (tag != "a" or not in_requirement_navigation):
            raise ValidationError(f"requirement document link is outside its explicit navigation in {self.label}")
        if tag == "a" and in_requirement_navigation:
            kind = attrs.get("data-prototype-document", "")
            if kind not in {"html", "markdown"} or not attrs.get("href"):
                raise ValidationError(f"requirement navigation needs typed HTML/Markdown anchors in {self.label}")
            # 在提取 kind/href 之前保留并校验浏览上下文属性；没有 page-shell.js 的
            # 合法页同样不能通过默认、_self、_top 或命名窗口替换受控工作区。
            # target 是 ASCII 保留字，不裁掉空白或做 Unicode 折叠，避免把真实命名
            # 上下文误认成 _blank；rel 也只按 HTML 的 ASCII 空白拆分 token。
            target = attrs.get("target", "")
            relations = {value.lower() for value in re.split(r"[ \t\n\f\r]+", attrs.get("rel", ""))}
            if not target.isascii() or target.lower() != "_blank" or "noopener" not in relations:
                raise ValidationError(f"requirement navigation needs target=_blank and rel=noopener in {self.label}")
            self.requirement_links.append((kind, attrs["href"]))
        if tag == "details":
            self.details_depth += 1
            self.details_summary_seen.append(False)
        # 只有 details 的第一个直属 summary 才有浏览器原生折叠行为；同名标签藏在普通
        # 容器里或同一 details 的第二个 summary，均不能靠契约映射伪装成真实控件。
        is_native_summary = tag == "summary" and bool(self.element_stack) and self.element_stack[-1] == "details"
        if is_native_summary:
            is_native_summary = not self.details_summary_seen[-1]
            self.details_summary_seen[-1] = True

        if "prototype-contract" in classes:
            if tag != "details":
                raise ValidationError(
                    f"page contract must use <details> in {self.label}"
                )
            self.contract_count += 1
            self.contract_depth += 1
        elif tag == "details" and self.contract_depth:
            self.contract_depth += 1

        if tag == "summary" and self.contract_depth:
            self.summary_depth += 1

        if tag == "section" and "data-contract-section" in attrs:
            if not self.contract_depth:
                raise ValidationError(f"contract section is outside the contract in {self.label}")
            if self.current_section is not None:
                raise ValidationError(f"nested contract sections are forbidden in {self.label}")
            section = attrs["data-contract-section"].strip()
            self.current_section = section
            self.section_order.append(section)
            self.section_text.setdefault(section, [])

        if tag in {"h1", "h2", "h3", "h4", "h5", "h6"} and self.current_section:
            self.heading_depth += 1

        if "id" in attrs:
            stable_id = attrs["id"].strip()
            if not STABLE_ID_PATTERN.fullmatch(stable_id):
                raise ValidationError(f"unstable or empty id in {self.label}: {stable_id!r}")
            self.ids.append(stable_id)

        is_material = tag == "button" or (
            tag == "input" and attrs.get("type", "text").casefold() in BUTTON_INPUT_TYPES
        )
        if is_material:
            stable_id = attrs.get("id", "").strip()
            if not stable_id:
                raise ValidationError(f"material control lacks a stable id in {self.label}")
            self.material_controls.append(stable_id)
        is_interactive_input = (
            tag == "input" and attrs.get("type", "text").casefold() != "hidden"
        )
        if (
            is_material or is_interactive_input or tag in {"a", "select", "textarea"}
            # summary 自带键盘与折叠语义；有稳定 ID 时可被契约映射，普通文本不能冒充。
            or is_native_summary
        ) and attrs.get("id", "").strip():
            self.interactive_ids.append(attrs["id"].strip())
        submits_dialog_form = (
            tag == "button" and attrs.get("type", "submit").casefold() == "submit"
        ) or (
            tag == "input"
            and attrs.get("type", "text").casefold() in {"submit", "image"}
        )
        if (
            submits_dialog_form
            and self.dialog_form_stack
            and self.dialog_form_stack[-1] is not None
        ):
            self.native_close_dialogs.add(self.dialog_form_stack[-1])

        if "data-contract-for" in attrs:
            target = attrs["data-contract-for"].strip()
            if not STABLE_ID_PATTERN.fullmatch(target):
                raise ValidationError(f"invalid contract mapping target in {self.label}: {target!r}")
            if self.current_section != "interactions":
                raise ValidationError(
                    f"contract mapping must be inside the interactions section in {self.label}"
                )
            self.mappings.append(target)

        if tag == "dialog":
            dialog_id = attrs.get("id", "").strip()
            if not dialog_id:
                raise ValidationError(f"dialog lacks a stable id in {self.label}")
            self.dialog_ids.append(dialog_id)
            self.dialog_stack.append(dialog_id)
        if tag == "form":
            dialog_form_owner: str | None = None
            if attrs.get("method", "").casefold() == "dialog":
                if not self.dialog_stack:
                    raise ValidationError(
                        f"form method=dialog must be inside a dialog in {self.label}"
                    )
                dialog_form_owner = self.dialog_stack[-1]
            self.dialog_form_stack.append(dialog_form_owner)

        for attribute in ("href", "src"):
            if attribute in attrs:
                if tag == "a" and attribute == "href" and in_requirement_navigation:
                    # 跨原型根的唯一例外在专用文档边界核验，绝不进入渲染资源闭包。
                    continue
                # 导航仍须通过本地路径和文件安全检查，但不是渲染资源。
                # 不把互链页面或薄目录纳入当前页指纹，避免无关页面修改污染证据。
                kind = "navigation href" if tag in {"a", "area"} and attribute == "href" else attribute
                self.references.append((kind, attrs[attribute]))
        if tag == "video" and "poster" in attrs:
            self.references.append(("poster", attrs["poster"]))
        if tag == "object" and "data" in attrs:
            self.references.append(("data", attrs["data"]))
        if "srcset" in attrs:
            for candidate in attrs["srcset"].split(","):
                fields = candidate.strip().split()
                if not fields:
                    raise ValidationError(f"empty srcset candidate in {self.label}")
                self.references.append(("srcset", fields[0]))
        if "style" in attrs:
            self.style_parts.append(attrs["style"])
        if tag == "script":
            self.script_depth += 1
        if tag == "style":
            self.style_depth += 1
        if tag not in HTML_VOID_ELEMENTS:
            self.element_stack.append(tag)

    def handle_startendtag(
        self, tag: str, attributes: list[tuple[str, str | None]]
    ) -> None:
        self.handle_starttag(tag, attributes)
        self.handle_endtag(tag)

    def handle_endtag(self, tag: str) -> None:
        tag = tag.casefold()
        if tag in {"h1", "h2", "h3", "h4", "h5", "h6"} and self.heading_depth:
            self.heading_depth -= 1
        if tag == "section" and self.current_section is not None:
            self.current_section = None
        if tag == "summary" and self.summary_depth:
            self.summary_depth -= 1
        if tag == "details" and self.contract_depth:
            self.contract_depth -= 1
        if tag == "details" and self.details_depth:
            self.details_depth -= 1
            self.details_summary_seen.pop()
        if tag == "nav":
            if not self.navigation_stack:
                raise ValidationError(f"unexpected closing navigation in {self.label}")
            self.navigation_stack.pop()
        if tag == "script" and self.script_depth:
            self.script_depth -= 1
        if tag == "style" and self.style_depth:
            self.style_depth -= 1
        if tag == "dialog":
            if not self.dialog_stack:
                raise ValidationError(f"unexpected closing dialog in {self.label}")
            self.dialog_stack.pop()
        if tag == "form":
            if not self.dialog_form_stack:
                raise ValidationError(f"unexpected closing form in {self.label}")
            self.dialog_form_stack.pop()
        if tag in {"html", "head", "body"}:
            if not self.document_depths[tag]:
                raise ValidationError(f"unexpected closing <{tag}> in {self.label}")
            self.document_depths[tag] -= 1
        if tag in self.element_stack:
            # 祖先记录只用于识别原生 summary，不把这里扩写成第二个 HTML 标准解析器。
            position = len(self.element_stack) - 1 - self.element_stack[::-1].index(tag)
            del self.element_stack[position:]

    def handle_data(self, data: str) -> None:
        if self.summary_depth:
            self.summary_parts.append(data)
        if self.current_section is not None and not self.heading_depth:
            self.section_text[self.current_section].append(data)
        if self.script_depth:
            self.script_parts.append(data)
        if self.style_depth:
            self.style_parts.append(data)


def _parse_html(parser: HTMLParser, body: str, label: str) -> None:
    try:
        parser.feed(body)
        parser.close()
    except ValidationError:
        raise
    except Exception as exc:
        raise ValidationError(f"cannot parse {label} as HTML: {exc}") from exc


def _validate_document_structure(
    doctype_count: int,
    document_counts: Counter[str],
    document_depths: Counter[str],
    label: str,
) -> None:
    if doctype_count != 1:
        raise ValidationError(f"{label} must contain exactly one HTML5 doctype")
    for tag in ("html", "head", "body"):
        if document_counts[tag] != 1 or document_depths[tag] != 0:
            raise ValidationError(
                f"{label} must contain exactly one closed <{tag}> element"
            )


def _validate_index_structure(parser: IndexParser) -> None:
    """索引安全始终检查；单 iframe 只引用唯一导航中的既有页面，不创建第二份登记。"""
    _validate_document_structure(
        parser.doctype_count, parser.document_counts, parser.document_depths, "prototype index",
    )
    if parser.prototype_nav_count != 1:
        raise ValidationError("prototype index must contain exactly one Prototype pages navigation region")
    if parser.nav_depth or parser.group_summaries:
        raise ValidationError("prototype index navigation region must be closed")
    if parser.preview_depth:
        raise ValidationError("controlled prototype preview iframe must be closed")
    if parser.script_depth or _normalized_text(parser.inline_script):
        raise ValidationError("prototype index controller must be closed and contain no inline code")
    if parser.controller_count or parser.workspace_tags:
        if parser.controller_count != 1 or parser.preview_count != 1 or parser.navigation_id != "prototype-pages":
            raise ValidationError("prototype workspace structure needs one local controller, registration nav and preview")
    if parser.preview_count and parser.preview_target is None:
        # 无 src 不是通用 iframe 豁免：只有真实控制器可从唯一 nav 派生加载目标。
        if not parser.controller_count or not parser.preview_hidden:
            raise ValidationError("only a controlled workspace may initialize a hidden preview without src")
        if not parser.page_links and parser.empty_state_count != 1:
            raise ValidationError("empty prototype workspace needs its explicit empty state")
    if parser.preview_target is not None:
        if parser.navigation_id != "prototype-pages" or parser.preview_target not in parser.page_links:
            raise ValidationError("controlled prototype preview must target a page registered in nav#prototype-pages")


def _validate_page_structure(parser: PageParser) -> None:
    label = parser.label
    _validate_document_structure(
        parser.doctype_count,
        parser.document_counts,
        parser.document_depths,
        label,
    )
    if parser.contract_count != 1:
        raise ValidationError(
            f"{label} must contain exactly one page contract; found {parser.contract_count}"
        )
    if (
        parser.contract_depth
        or parser.current_section is not None
        or parser.script_depth
        or parser.style_depth
        or parser.dialog_stack
        or parser.dialog_form_stack
        or parser.details_depth
        or parser.navigation_stack
    ):
        raise ValidationError(f"unclosed page contract structure in {label}")
    if _normalized_text(parser.summary_parts) != "Page design and interaction contract":
        raise ValidationError(f"page contract summary is invalid in {label}")
    if tuple(parser.section_order) != MANDATORY_SECTIONS:
        raise ValidationError(
            f"{label} must contain the five exact contract sections in standard order"
        )
    for section in MANDATORY_SECTIONS:
        text = _normalized_text(parser.section_text.get(section, []))
        if not text or _is_placeholder_text(text):
            raise ValidationError(
                f"contract section {section!r} is empty or placeholder-only in {label}"
            )

    duplicate_ids = [value for value, count in Counter(parser.ids).items() if count > 1]
    if duplicate_ids:
        raise ValidationError(f"duplicate id in {label}: {duplicate_ids[0]}")
    id_set = set(parser.ids)
    mapping_counts = Counter(parser.mappings)
    for control_id in parser.material_controls:
        if mapping_counts[control_id] != 1:
            raise ValidationError(
                f"material control {control_id!r} needs exactly one contract mapping in {label}"
            )
    duplicate_mappings = [
        value for value, count in mapping_counts.items() if count != 1
    ]
    if duplicate_mappings:
        raise ValidationError(
            f"contract target {duplicate_mappings[0]!r} is mapped more than once in {label}"
        )
    missing_targets = [target for target in parser.mappings if target not in id_set]
    if missing_targets:
        raise ValidationError(
            f"contract target does not exist in {label}: {missing_targets[0]}"
        )
    noninteractive_targets = [
        target for target in parser.mappings if target not in set(parser.interactive_ids)
    ]
    if noninteractive_targets:
        raise ValidationError(
            f"contract target is not an interactive control in {label}: "
            f"{noninteractive_targets[0]}"
        )
    _validate_dialog_wiring(parser)


CSS_COMMENT_PATTERN = re.compile(r"/\*.*?\*/", re.DOTALL)
CSS_URL_PATTERN = re.compile(r"url\(\s*(['\"]?)(.*?)\1\s*\)", re.IGNORECASE | re.DOTALL)
CSS_IMPORT_PATTERN = re.compile(
    r"@import\s+(?!url\()(['\"])(.*?)\1",
    re.IGNORECASE | re.DOTALL,
)


def _css_references(body: str) -> list[str]:
    body = CSS_COMMENT_PATTERN.sub("", body)
    references = [match.group(2).strip() for match in CSS_URL_PATTERN.finditer(body)]
    references.extend(match.group(2).strip() for match in CSS_IMPORT_PATTERN.finditer(body))
    return references


def _open_dependency_at(
    prototype_fd: int,
    relative: PurePosixPath,
    label: str,
) -> int:
    directory_fd = os.dup(prototype_fd)
    try:
        for component in relative.parts[:-1]:
            next_fd = _open_directory_at(directory_fd, component, label)
            os.close(directory_fd)
            directory_fd = next_fd
        return _open_regular_at(
            directory_fd,
            relative.parts[-1],
            label,
            size_limit=MAX_DEPENDENCY_SIZE,
        )
    finally:
        os.close(directory_fd)


def _javascript_regex_end(body: str, start: int, label: str) -> int:
    """消费确定处于表达式起点的正则；转义和字符类内的斜线不能提前结束字面量。"""

    index = start + 1
    in_class = False
    while index < len(body):
        character = body[index]
        if character in {"\n", "\r", "\u2028", "\u2029"}:
            raise ValidationError(f"unterminated JavaScript regular expression in {label}")
        if character == "\\":
            if index + 1 >= len(body) or body[index + 1] in {"\n", "\r", "\u2028", "\u2029"}:
                raise ValidationError(f"unterminated JavaScript regular expression in {label}")
            index += 2
            continue
        if character == "[":
            if in_class:
                # 嵌套字符集需要结合 v 模式完整语法分析，受控验证器不猜测其边界。
                raise ValidationError(f"unsupported nested JavaScript regular expression class in {label}")
            in_class = True
        elif character == "]":
            in_class = False
        elif character == "/" and not in_class:
            index += 1
            while index < len(body) and body[index].isalpha():
                index += 1
            return index
        index += 1
    raise ValidationError(f"unterminated JavaScript regular expression in {label}")


def _javascript_lexical_views(body: str, label: str) -> tuple[str, str]:
    """Return comment-free source and code with strings/comments/supported regex masked."""

    source: list[str] = []
    code: list[str] = []
    state = "code"
    quote = ""
    index = 0
    expect_operand = True
    property_access = False
    # None 表示模板文字，整数表示当前 ${...} 的普通花括号深度；嵌套模板沿同一词法器
    # 处理，文字被遮蔽而插值代码保留，因此动态 import 不能藏在模板表达式里。
    templates: list[int | None] = []
    # 这些保留字之后可以明确开始一个表达式；不能加入 of / await 等可能是变量名
    # 的词，否则会把合法除法误认为正则，并可能掩盖后续真正的模块声明。
    regex_prefix_keywords = {"return", "throw", "case", "delete", "void", "typeof", "new", "in", "instanceof", "else", "do", "default"}
    while index < len(body):
        current = body[index]
        following = body[index + 1] if index + 1 < len(body) else ""
        if state == "template":
            replacement = "\n" if current == "\n" else " "
            source.append(replacement)
            code.append(replacement)
            if current == "\\" and following:
                replacement = "\n" if following == "\n" else " "
                source.append(replacement)
                code.append(replacement)
                index += 2
                continue
            if current == "`":
                templates.pop()
                state = "code"
                expect_operand = False
                property_access = False
            elif current == "$" and following == "{":
                source.append(" ")
                code.append(" ")
                templates[-1] = 0
                state = "code"
                expect_operand = True
                property_access = False
                index += 2
                continue
            index += 1
            continue
        if state == "code":
            if templates and templates[-1] is not None and current in {"{", "}"}:
                if current == "}" and templates[-1] == 0:
                    source.append(" ")
                    code.append(" ")
                    templates[-1] = None
                    state = "template"
                    index += 1
                    continue
                templates[-1] += 1 if current == "{" else -1
            if current == "/" and following == "/":
                source.extend((" ", " "))
                code.extend((" ", " "))
                state = "line-comment"
                index += 2
                continue
            if current == "/" and following == "*":
                source.extend((" ", " "))
                code.extend((" ", " "))
                state = "block-comment"
                index += 2
                continue
            if current == "/" and expect_operand:
                end = _javascript_regex_end(body, index, label)
                source.extend(body[index:end])
                code.extend(" " * (end - index))
                expect_operand = False
                property_access = False
                index = end
                continue
            if current == "`":
                source.append(" ")
                code.append(" ")
                templates.append(None)
                state = "template"
                index += 1
                continue
            if current in {"'", '"'}:
                quote = current
                source.append(current)
                code.append(" ")
                state = "string"
                expect_operand = False
                property_access = False
                index += 1
                continue
            if current.isalnum() or current in {"_", "$"}:
                end = index + 1
                while end < len(body) and (body[end].isalnum() or body[end] in {"_", "$", "\u200c", "\u200d"}):
                    end += 1
                token = body[index:end]
                source.extend(token)
                code.extend(token)
                expect_operand = not property_access and token in regex_prefix_keywords
                property_access = False
                index = end
                continue
            if current in {"+", "-"} and following == current:
                # 后缀 ++/-- 后仍是除法位置，前缀 ++/-- 则保留等待操作数的状态。
                source.extend((current, following))
                code.extend((current, following))
                property_access = False
                index += 2
                continue
            source.append(current)
            code.append(current)
            if not current.isspace():
                # 不根据闭合 ) / } 猜测“语句块还是表达式”；这些有歧义位置保持
                # 非正则处理，避免跨越真实 import/export。常规赋值、参数、return
                # 等明确起点支持正则；需要复杂上下文的正则应改用显式局部变量。
                expect_operand = current not in {".", ")", "]", "}"}
                property_access = current == "."
            index += 1
            continue
        if state == "line-comment":
            if current == "\n":
                source.append("\n")
                code.append("\n")
                state = "code"
            else:
                source.append(" ")
                code.append(" ")
            index += 1
            continue
        if state == "block-comment":
            if current == "*" and following == "/":
                source.extend((" ", " "))
                code.extend((" ", " "))
                state = "code"
                index += 2
                continue
            replacement = "\n" if current == "\n" else " "
            source.append(replacement)
            code.append(replacement)
            index += 1
            continue
        source.append(current)
        code.append("\n" if current == "\n" else " ")
        if current == "\\" and index + 1 < len(body):
            source.append(body[index + 1])
            code.append("\n" if body[index + 1] == "\n" else " ")
            index += 2
            continue
        if current == quote:
            state = "code"
        index += 1
    if state in {"block-comment", "string", "template"} or templates:
        raise ValidationError(f"unterminated JavaScript token in {label}")
    return "".join(source), "".join(code)


# 只识别静态导出声明的明确语法形状，不用“任意文本直到 from”猜测依赖。
# 名称允许常见 Unicode IdentifierName、Unicode 转义和字符串 ModuleExportName；
# 少数不在此受控字符集合内的语法会在下方显式拒绝，不能被当成无依赖跳过。
JS_NAME_ESCAPE = r"\\u(?:[0-9a-fA-F]{4}|\{[0-9a-fA-F]{1,6}\})"
JS_IDENTIFIER_NAME = rf"(?:[^\W\d]|[$]|{JS_NAME_ESCAPE})(?:\w|[$\u200c\u200d]|{JS_NAME_ESCAPE})*"
JS_STRING_TOKEN = r'''(?:'(?:\\[\s\S]|[^'\\\r\n])*'|"(?:\\[\s\S]|[^"\\\r\n])*")'''
JS_EXPORT_NAME = rf"(?:{JS_IDENTIFIER_NAME}|{JS_STRING_TOKEN})"
JS_EXPORT_SPECIFIER = rf"{JS_EXPORT_NAME}(?:\s+as\s+{JS_EXPORT_NAME})?"
JS_NAMED_SPECIFIERS = rf"\{{\s*(?:{JS_EXPORT_SPECIFIER}(?:\s*,\s*{JS_EXPORT_SPECIFIER})*\s*,?\s*)?\}}"
STATIC_JS_IMPORT_START_PATTERN = re.compile(r"\bimport\b")
STATIC_JS_IMPORT_HEAD_PATTERN = re.compile(
    rf"\bimport\s*(?:(?:{JS_IDENTIFIER_NAME}\s*,\s*)?"
    rf"(?:\*\s+as\s+{JS_IDENTIFIER_NAME}|{JS_NAMED_SPECIFIERS})|{JS_IDENTIFIER_NAME})"
    rf"\s*from\b\s*",
    re.MULTILINE | re.DOTALL,
)
STATIC_JS_EXPORT_START_PATTERN = re.compile(r"\bexport\s*(?:\*|\{)")
STATIC_JS_EXPORT_HEAD_PATTERN = re.compile(
    rf"\bexport\s*(?P<star>\*(?:\s+as\s+{JS_EXPORT_NAME})?)|"
    rf"\bexport\s*\{{\s*(?:{JS_EXPORT_SPECIFIER}"
    rf"(?:\s*,\s*{JS_EXPORT_SPECIFIER})*\s*,?\s*)?\}}",
    re.MULTILINE | re.DOTALL,
)
JS_MODULE_STRING_PATTERN = re.compile(JS_STRING_TOKEN)
DYNAMIC_JS_IMPORT_PATTERN = re.compile(r"\bimport\s*\(")
GET_ELEMENT_LITERAL_PATTERN = re.compile(
    r"document\s*\.\s*getElementById\s*\(\s*(['\"])([^'\"]*)\1\s*\)"
)
ELEMENT_BINDING_PATTERN = re.compile(
    r"\b(?:const|let|var)\s+([A-Za-z_$][A-Za-z0-9_$]*)\s*=\s*"
    r"document\s*\.\s*getElementById\s*\(\s*(['\"])([^'\"]*)\2\s*\)"
)
DIRECT_CLICK_HANDLER_PATTERN = re.compile(
    r"document\s*\.\s*getElementById\s*\(\s*(['\"])([^'\"]*)\1\s*\)"
    r"\s*\.\s*addEventListener\s*\(\s*(['\"])([^'\"]*)\3\s*,"
    r"\s*\(\s*\)\s*=>\s*\{(?P<body>.*?)\}\s*\)",
    re.DOTALL,
)


def _match_starts_in_code(code_only: str, match: re.Match[str], token: str) -> bool:
    return code_only[match.start() : match.start() + len(token)] == token


def _decode_javascript_module_string(token: str, label: str) -> str:
    """按字符串实际值检查模块路径；转义不能把外部 URL 伪装成本地文件名。"""

    body = token[1:-1]
    output: list[str] = []
    index = 0
    simple = {"b": "\b", "f": "\f", "n": "\n", "r": "\r", "t": "\t", "v": "\v"}
    while index < len(body):
        character = body[index]
        index += 1
        if character != "\\":
            output.append(character)
            continue
        if index == len(body):
            raise ValidationError(f"unsupported static JavaScript module string in {label}")
        escaped = body[index]
        index += 1
        if escaped in {"\n", "\r", "\u2028", "\u2029"}:
            if escaped == "\r" and body[index:index + 1] == "\n":
                index += 1
            continue
        if escaped in {"u", "x"}:
            if escaped == "u" and body[index:index + 1] == "{":
                match = re.match(r"\{([0-9a-fA-F]{1,6})\}", body[index:])
            else:
                digits = 4 if escaped == "u" else 2
                match = re.match(rf"([0-9a-fA-F]{{{digits}}})", body[index:])
            if match is None:
                raise ValidationError(f"unsupported static JavaScript module string escape in {label}")
            value = int(match.group(1), 16)
            if value > 0x10FFFF or 0xD800 <= value <= 0xDFFF:
                raise ValidationError(f"unsupported static JavaScript module Unicode escape in {label}")
            output.append(chr(value))
            index += match.end()
        elif escaped.isdigit():
            if escaped != "0" or body[index:index + 1].isdigit():
                raise ValidationError(f"unsupported static JavaScript module numeric escape in {label}")
            output.append("\0")
        else:
            output.append(simple.get(escaped, escaped))
    return "".join(output)


def _static_javascript_export_references(source: str, code_only: str, label: str) -> list[str]:
    """完整消费 export * / export {...} 的声明头，未知形状直接拒绝而非漏掉依赖。"""

    references: list[str] = []
    for start in STATIC_JS_EXPORT_START_PATTERN.finditer(code_only):
        header = STATIC_JS_EXPORT_HEAD_PATTERN.match(source, start.start())
        if header is None:
            raise ValidationError(f"unsupported static JavaScript export declaration in {label}")
        from_keyword = re.match(r"\s*from\b\s*", source[header.end():])
        if from_keyword is None:
            if header.group("star") is not None:
                raise ValidationError(f"unsupported static JavaScript export declaration in {label}")
            # export { localName } 是本地导出，确实没有模块依赖。
            continue
        literal_start = header.end() + from_keyword.end()
        literal = JS_MODULE_STRING_PATTERN.match(source, literal_start)
        if literal is None:
            raise ValidationError(f"unsupported static JavaScript export module specifier in {label}")
        references.append(_decode_javascript_module_string(literal.group(0), label))
    return references


def _static_javascript_import_references(source: str, code_only: str, label: str) -> list[str]:
    """先在代码视图定位真实 import，再从相同偏移消费一条静态声明，禁止跨诱饵扫描。"""

    references: list[str] = []
    consumed_end = 0
    # import 可合法出现在导出名称中；只排除已完整识别的声明头，不猜测未知代码范围。
    export_headers = [
        header.span()
        for start in STATIC_JS_EXPORT_START_PATTERN.finditer(code_only)
        if (header := STATIC_JS_EXPORT_HEAD_PATTERN.match(source, start.start())) is not None
    ]
    export_cursor = 0
    for start in STATIC_JS_IMPORT_START_PATTERN.finditer(code_only):
        # 两组偏移都单调递增；用游标排除声明头，避免大量 import/export 时二次方扫描。
        while export_cursor < len(export_headers) and export_headers[export_cursor][1] <= start.start():
            export_cursor += 1
        inside_export_header = export_cursor < len(export_headers) and export_headers[export_cursor][0] <= start.start()
        if start.start() < consumed_end or inside_export_header:
            continue
        preceding = start.start() - 1
        while preceding >= 0 and code_only[preceding].isspace():
            preceding -= 1
        after_keyword = start.end()
        while after_keyword < len(source) and source[after_keyword].isspace():
            after_keyword += 1
        if (preceding >= 0 and code_only[preceding] == ".") or source[after_keyword:after_keyword + 1] in {".", ":", "="}:
            # import.meta、成员访问和属性名不是静态模块声明；动态 import 由上层独立禁止。
            continue
        literal = JS_MODULE_STRING_PATTERN.match(source, after_keyword)
        if literal is None:
            header = STATIC_JS_IMPORT_HEAD_PATTERN.match(source, start.start())
            if header is None:
                raise ValidationError(f"unsupported static JavaScript import declaration in {label}")
            literal = JS_MODULE_STRING_PATTERN.match(source, header.end())
        if literal is None:
            raise ValidationError(f"unsupported static JavaScript import module specifier in {label}")
        consumed_end = literal.end()
        references.append(_decode_javascript_module_string(literal.group(0), label))
    return references


def _validate_dialog_wiring(parser: PageParser) -> None:
    if not parser.dialog_ids:
        return
    label = parser.label
    script = "\n".join(parser.script_parts)
    comment_free, code_only = _javascript_lexical_views(script, label)
    id_set = set(parser.ids)
    interactive_ids = set(parser.interactive_ids)
    mapped_ids = set(parser.mappings)

    for match in GET_ELEMENT_LITERAL_PATTERN.finditer(comment_free):
        if not _match_starts_in_code(code_only, match, "document"):
            continue
        literal = match.group(2)
        if literal not in id_set:
            raise ValidationError(
                f"getElementById literal does not exist in {label}: {literal}"
            )

    dialog_variables: dict[str, str] = {}
    dialog_ids = set(parser.dialog_ids)
    for match in ELEMENT_BINDING_PATTERN.finditer(comment_free):
        if not _match_starts_in_code(code_only, match, match.group(0).lstrip()[:5]):
            continue
        variable, element_id = match.group(1), match.group(3)
        if element_id in dialog_ids:
            dialog_variables[variable] = element_id

    openers: dict[str, set[str]] = {dialog_id: set() for dialog_id in dialog_ids}
    closers: dict[str, set[str]] = {dialog_id: set() for dialog_id in dialog_ids}
    for match in DIRECT_CLICK_HANDLER_PATTERN.finditer(comment_free):
        if not _match_starts_in_code(code_only, match, "document"):
            continue
        control_id = match.group(2)
        event = match.group(4).casefold()
        if event != "click":
            continue
        if control_id not in interactive_ids or control_id not in mapped_ids:
            raise ValidationError(
                f"dialog event control is not a mapped interactive control in {label}: "
                f"{control_id}"
            )
        body_start, body_end = match.span("body")
        body_code = code_only[body_start:body_end]
        for variable, dialog_id in dialog_variables.items():
            escaped = re.escape(variable)
            if re.search(rf"\b{escaped}\s*\.\s*showModal\s*\(", body_code):
                openers[dialog_id].add(control_id)
            if re.search(rf"\b{escaped}\s*\.\s*close\s*\(", body_code):
                closers[dialog_id].add(control_id)

    for dialog_id in parser.dialog_ids:
        if not openers[dialog_id]:
            raise ValidationError(
                f"dialog {dialog_id!r} has no proven mapped open control in {label}"
            )
        native_close = dialog_id in parser.native_close_dialogs
        if not closers[dialog_id] and not native_close:
            raise ValidationError(
                f"dialog {dialog_id!r} has no proven close behavior in {label}"
            )
        if closers[dialog_id] and openers[dialog_id] & closers[dialog_id]:
            raise ValidationError(
                f"dialog {dialog_id!r} reuses the same control for open and close in {label}"
            )


class DependencyValidator:
    """Validate a bounded graph of descriptor-anchored local dependencies."""

    def __init__(self, prototype_fd: int, *, navigation: RequirementNavigation | None = None) -> None:
        self.prototype_fd = prototype_fd
        self.navigation = navigation
        self.visited: set[PurePosixPath] = set()
        self.total_size = 0
        self.contents: dict[PurePosixPath, bytes] = {}
        self.identities: dict[PurePosixPath, FileIdentity] = {}
        self.edges: dict[PurePosixPath, set[PurePosixPath]] = {}

    def capture_path(self, target: PurePosixPath, *, size_limit: int = MAX_DEPENDENCY_SIZE) -> bytes:
        """以安全 fd 捕获一次完整字节；验证和指纹共享快照，禁止再次按路径读内容。"""

        if target in self.contents:
            raw = self.contents[target]
            if len(raw) > size_limit:
                raise ValidationError(f"prototype dependency {target} exceeds {size_limit} bytes")
            return raw
        if len(self.contents) >= MAX_DEPENDENCY_NODES:
            raise ValidationError(f"prototype dependency graph exceeds {MAX_DEPENDENCY_NODES} nodes")
        label = f"prototype dependency {target}"
        descriptor = _open_dependency_at(self.prototype_fd, target, label)
        try:
            info_before = os.fstat(descriptor)
            if self.total_size + info_before.st_size > MAX_DEPENDENCY_TOTAL_SIZE:
                raise ValidationError("prototype dependency graph exceeds the total size budget")
            # 二进制图片、字体等也必须读完整内容；仅靠 stat 无法证明资源指纹。
            raw = _read_descriptor(descriptor, label, size_limit)
            info_after = os.fstat(descriptor)
            if _file_identity(info_before) != _file_identity(info_after):
                raise ValidationError(f"{label} changed while it was being read")
            if self.total_size + len(raw) > MAX_DEPENDENCY_TOTAL_SIZE:
                raise ValidationError("prototype dependency graph exceeds the total size budget")
        finally:
            os.close(descriptor)
        self.contents[target] = raw
        self.identities[target] = _file_identity(info_after)
        self.total_size += len(raw)
        return raw

    def text(self, target: PurePosixPath, *, size_limit: int = MAX_DEPENDENCY_SIZE) -> str:
        raw = self.capture_path(target, size_limit=size_limit)
        try:
            return raw.decode("utf-8", errors="strict")
        except UnicodeDecodeError as exc:
            raise ValidationError(f"prototype dependency {target} is not valid UTF-8: {exc}") from exc

    def validate_reference(
        self,
        source: PurePosixPath,
        raw: str,
        label: str,
        *,
        depth: int = 0,
        resource: bool = True,
    ) -> PurePosixPath | None:
        target = _resolve_local_reference(source, raw, label)
        if target is not None:
            if resource and source != PurePosixPath("index.html") and target in {
                PurePosixPath("workspace.js"), PurePosixPath("workspace.css"),
            }:
                raise ValidationError("workspace controller and stylesheet may only be loaded by index.html")
            if resource:
                self.edges.setdefault(source, set()).add(target)
                self.validate_path(target, depth=depth + 1)
            else:
                # 导航目标仍完整验证，但从独立根计深度且不建立当前页的资源边。
                # 这样 CSS 下载链接也不能藏外部依赖，页面互链又不会变成资源闭环。
                self.validate_path(target)
        return target

    def validate_path(self, target: PurePosixPath, *, depth: int = 0) -> None:
        if target in self.visited:
            return
        if depth > MAX_DEPENDENCY_DEPTH:
            raise ValidationError(
                f"prototype dependency depth exceeds {MAX_DEPENDENCY_DEPTH}: {target}"
            )
        raw = self.capture_path(target)
        self.visited.add(target)
        label = f"prototype dependency {target}"
        suffix = target.suffix.casefold()
        if suffix not in TEXT_DEPENDENCY_SUFFIXES:
            return
        try:
            body = raw.decode("utf-8", errors="strict")
        except UnicodeDecodeError as exc:
            raise ValidationError(f"{label} is not valid UTF-8: {exc}") from exc
        if suffix == ".css":
            self.validate_css_body(target, body, depth=depth)
        elif suffix in {".js", ".mjs", ".cjs"}:
            self.validate_javascript_body(target, body, depth=depth)
        elif suffix in {".html", ".htm"}:
            if target == PurePosixPath("index.html"):
                index_parser = IndexParser()
                _parse_html(index_parser, body, str(target))
                _validate_index_structure(index_parser)
                _validate_references(self, target, index_parser.references, depth=depth)
            else:
                parser = PageParser(str(target))
                _parse_html(parser, body, str(target))
                if parser.plan_source or parser.requirement_links:
                    if self.navigation is None:
                        raise ValidationError("requirement navigation needs the configured project context")
                    try:
                        self.navigation.validate(target, parser.plan_source, parser.requirement_links)
                    except (OSError, ValueError) as exc:
                        raise ValidationError(f"{target} requirement navigation: {exc}") from exc
                _validate_references(self, target, parser.references, depth=depth)
                self.validate_css_body(target, "\n".join(parser.style_parts), depth=depth)
                self.validate_javascript_body(target, "\n".join(parser.script_parts), depth=depth)

    def require_current_identities(self) -> None:
        """结束前重新 no-follow 打开全部已捕获节点，只核对身份，不重读或重算字节。"""

        for target, expected in self.identities.items():
            descriptor = _open_dependency_at(self.prototype_fd, target, f"prototype dependency {target}")
            try:
                current = _file_identity(os.fstat(descriptor))
            finally:
                os.close(descriptor)
            if current != expected:
                raise ValidationError(f"prototype dependency {target} changed during validation")

    def fingerprint(self, page: PurePosixPath) -> str:
        """每页独立计算资源闭包；排序与长度前缀使遍历顺序和拼接边界不影响结果。"""

        closure: set[PurePosixPath] = set()

        def visit(target: PurePosixPath, depth: int) -> None:
            if target in closure:
                return
            if depth > MAX_DEPENDENCY_DEPTH:
                raise ValidationError(f"prototype dependency depth exceeds {MAX_DEPENDENCY_DEPTH}: {target}")
            closure.add(target)
            for dependency in sorted(self.edges.get(target, set()), key=lambda path: path.as_posix()):
                visit(dependency, depth + 1)

        visit(page, 0)
        digest = hashlib.sha256(FINGERPRINT_DOMAIN)
        for target in sorted(closure, key=lambda path: path.as_posix()):
            path_bytes = target.as_posix().encode("utf-8")
            raw = self.contents[target]
            digest.update(len(path_bytes).to_bytes(8, "big"))
            digest.update(path_bytes)
            digest.update(len(raw).to_bytes(8, "big"))
            digest.update(raw)
        return digest.hexdigest()

    def validate_css_body(
        self,
        source: PurePosixPath,
        body: str,
        *,
        depth: int = 0,
    ) -> None:
        for reference in _css_references(body):
            self.validate_reference(
                source,
                reference,
                f"CSS dependency referenced by {source}",
                depth=depth,
            )

    def validate_javascript_body(
        self,
        source: PurePosixPath,
        body: str,
        *,
        depth: int = 0,
    ) -> None:
        comment_free, code_only = _javascript_lexical_views(body, str(source))
        if DYNAMIC_JS_IMPORT_PATTERN.search(code_only):
            raise ValidationError(
                f"dynamic JavaScript import is unsupported in prototype dependency {source}"
            )
        references = _static_javascript_import_references(comment_free, code_only, str(source))
        references.extend(_static_javascript_export_references(comment_free, code_only, str(source)))
        for reference in references:
            self.validate_reference(
                source,
                reference,
                f"JavaScript import referenced by {source}",
                depth=depth,
            )


def _validate_references(
    dependencies: DependencyValidator,
    source: PurePosixPath,
    references: list[tuple[str, str]],
    *,
    depth: int = 0,
) -> list[PurePosixPath]:
    resolved: list[PurePosixPath] = []
    for kind, raw in references:
        target = dependencies.validate_reference(
            source,
            raw,
            f"{source} {kind}",
            depth=depth,
            resource=kind != "navigation href",
        )
        if target is None:
            continue
        resolved.append(target)
    return resolved


def validate_workspace(
    project_root: str | Path,
    prototype_relative_raw: str,
    *,
    pages: list[str] | None = None,
    expected: dict[str, str] | None = None,
    adapter: str | None = None,
) -> dict[str, list[dict[str, str]]]:
    """验证整个工作区，返回选定具体页的证据；指纹相等不代表授予用户批准。"""
    prototype_relative = _safe_relative_path(
        prototype_relative_raw,
        "prototype root",
    )
    project_fd = _open_root(project_root, "project root")
    prototype_fd = -1
    pages_fd = -1
    try:
        prototype_fd = _walk_directory(project_fd, prototype_relative, "prototype root")
        navigation = RequirementNavigation(Path(project_root), prototype_relative, adapter=adapter)
        dependencies = DependencyValidator(prototype_fd, navigation=navigation)
        index_body = dependencies.text(PurePosixPath("index.html"), size_limit=MAX_TEXT_FILE_SIZE)
        try:
            prototype_entries = set(os.listdir(prototype_fd))
        except OSError as exc:
            raise ValidationError(f"cannot list prototype workspace: {exc}") from exc
        dependencies.validate_path(PurePosixPath("prototype.css"))
        if "prototype.js" in prototype_entries:
            dependencies.validate_path(PurePosixPath("prototype.js"))
        # 页面直接放在原型根目录。仍用独立文件描述符和末尾身份复查，防止校验中
        # 目录被替换后，把旧目录的安全结论错误地应用到新文件。
        if "pages" in prototype_entries:
            raise ValidationError("nested prototype pages directory is retired; place pages directly in prototype root")
        _validate_workspace_nodes(prototype_fd)
        pages_fd = os.dup(prototype_fd)

        try:
            page_entries = sorted(os.listdir(pages_fd))
        except OSError as exc:
            raise ValidationError(f"cannot list prototype pages: {exc}") from exc

        page_names: list[str] = []
        page_bodies: dict[str, str] = {}
        pages_identity_info = os.fstat(pages_fd)
        pages_identity = (pages_identity_info.st_dev, pages_identity_info.st_ino)
        for name in page_entries:
            if name == "index.html" or not name.lower().endswith((".html", ".htm")):
                continue
            if not re.fullmatch(r"[a-z0-9][a-z0-9-]*\.html", name):
                raise ValidationError(f"prototype page must use a canonical lowercase .html name: {name}")
            if VERSION_COPY_PATTERN.search(PurePosixPath(name).stem):
                raise ValidationError(f"version-copy prototype page is forbidden: {name}")
            page_names.append(name)
            page_bodies[name] = dependencies.text(PurePosixPath(name), size_limit=MAX_TEXT_FILE_SIZE)

        index_parser = IndexParser()
        _parse_html(index_parser, index_body, "prototype index")
        _validate_index_structure(index_parser)
        _validate_references(
            dependencies,
            PurePosixPath("index.html"),
            index_parser.references,
        )
        expected_page_links = page_names
        if sorted(index_parser.page_links) != expected_page_links:
            raise ValidationError(
                "prototype index must link each active page exactly once and no inactive page"
            )

        for name in page_names:
            source = PurePosixPath(name)
            parser = PageParser(str(source))
            _parse_html(parser, page_bodies[name], str(source))
            _validate_page_structure(parser)
            dependencies.validate_path(source)

        current_pages_fd = _walk_directory(project_fd, prototype_relative, "current prototype root")
        try:
            current_pages_info = os.fstat(current_pages_fd)
            current_pages_identity = (
                current_pages_info.st_dev,
                current_pages_info.st_ino,
            )
            if current_pages_identity != pages_identity:
                raise ValidationError("prototype root directory changed during validation")
            if sorted(os.listdir(current_pages_fd)) != page_entries:
                raise ValidationError("prototype entries changed during validation")
        finally:
            os.close(current_pages_fd)
        # 所有页面都检查资源闭包深度，防止 --page 只输出一页时绕过另一页的限额。
        fingerprints = {
            name: dependencies.fingerprint(PurePosixPath(name)) for name in page_names
        }
        dependencies.require_current_identities()
        try:
            navigation.require_current_inputs()
        except (OSError, ValueError) as exc:
            raise ValidationError(f"requirement navigation changed during validation: {exc}") from exc
        # --page 只缩小证据输出，不缩小安全验证。薄目录不是用户确认的具体页面。
        selected = sorted(set(page_names if pages is None else pages))
        if any(name not in page_names for name in selected):
            raise ValidationError("selected page must name an active concrete prototype page, not index.html")
        expected = {} if expected is None else expected
        for name, value in expected.items():
            if name not in selected or not isinstance(value, str) or not re.fullmatch(r"[0-9a-fA-F]{64}", value):
                raise ValidationError(f"invalid expected fingerprint or unselected page: {name}")
        result: list[dict[str, str]] = []
        for name in selected:
            fingerprint = fingerprints[name]
            if name in expected and fingerprint != expected[name].lower():
                raise ValidationError(f"prototype dependency fingerprint mismatch: {name}")
            result.append({"path": (prototype_relative / name).as_posix(), "dependency_fingerprint": fingerprint})
        return {"pages": result}
    finally:
        if pages_fd >= 0:
            os.close(pages_fd)
        if prototype_fd >= 0:
            os.close(prototype_fd)
        os.close(project_fd)


def _validate_workspace_nodes(root_fd: int) -> None:
    """浅层页面与资源分目录共存，但不能混入计划、链接节点或隐藏的第二套页面。

    所有节点只做 no-follow 元数据检查；实际内容/依赖仍由原来的按需验证器读取。
    保留资源子目录的自由度，不要求预建 assets，也不扫描项目之外的任何位置。
    """

    count = 0

    def visit(directory_fd: int, prefix: str, depth: int) -> None:
        nonlocal count
        if depth > MAX_DEPENDENCY_DEPTH:
            raise ValidationError("prototype resource directory depth limit exceeded")
        for name in os.listdir(directory_fd):
            count += 1
            if count > MAX_DEPENDENCY_NODES:
                raise ValidationError("prototype workspace node limit exceeded")
            relative = f"{prefix}/{name}" if prefix else name
            info = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
            if name.startswith(".") or stat.S_ISLNK(info.st_mode):
                raise ValidationError(f"prototype contains hidden or linked entry: {relative}")
            if stat.S_ISDIR(info.st_mode):
                nested = _open_directory_at(directory_fd, name, relative)
                try:
                    visit(nested, relative, depth + 1)
                finally:
                    os.close(nested)
            elif not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                raise ValidationError(f"prototype entry must be a single-link regular file: {relative}")
            elif name.lower().endswith(".md") or (prefix and name.lower().endswith((".html", ".htm"))):
                raise ValidationError(f"prototype contains a document or nested page: {relative}")

    visit(root_fd, "", 0)


def main(argv: list[str]) -> int:
    class ArgumentParser(argparse.ArgumentParser):
        def error(self, message: str) -> None:
            raise ValidationError(message)

    parser = ArgumentParser(description=__doc__)
    parser.add_argument("project_root")
    parser.add_argument("prototype_root")
    parser.add_argument("--adapter", help="explicitly selected project-relative adapter; required for requirements navigation")
    parser.add_argument("--json", action="store_true", dest="json_output")
    parser.add_argument("--page", action="append", help="concrete page relative to the prototype root; repeatable")
    parser.add_argument("--expect", action="append", default=[], metavar="PAGE=SHA256")
    try:
        args = parser.parse_args(argv[1:])
    except ValidationError as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 2
    try:
        expected: dict[str, str] = {}
        for expectation in args.expect:
            name, separator, fingerprint = expectation.partition("=")
            if not separator or not name or not re.fullmatch(r"[0-9a-fA-F]{64}", fingerprint):
                raise ValidationError("--expect must be <concrete-page.html>=<64hexsha256>")
            if name in expected and expected[name] != fingerprint.lower():
                raise ValidationError(f"conflicting expected fingerprints for page: {name}")
            expected[name] = fingerprint.lower()
        result = validate_workspace(args.project_root, args.prototype_root, pages=args.page, expected=expected,
                                    adapter=args.adapter)
    except Exception as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 1
    if args.json_output:
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    else:
        print(f"[OK] prototype workspace is valid: {args.prototype_root}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
