"""原始 HTML 的来源目标合同；不依赖装配器或反馈消费者。

来源键只由登记路径和原始起始标签位置决定。浏览器摘录与运行时 DOM 都
不能创建设计稿来源；每次 validate 都重读源字节重新建立此目录。
"""
from __future__ import annotations

from collections import Counter
import hashlib
import json
from html.parser import HTMLParser
import re

from lib.documents import validate_prototype_workspace as workspace
from lib.documents.safe_documents import normalized_relative, digest

SOURCE_ATTRIBUTE = "data-prototype-review-source"
SOURCE_KEY_PATTERN = re.compile(r"source-[0-9a-f]{64}\Z")
FORBIDDEN_TAGS = {"script", "style", "template", "link", "meta", "noscript"}


class _SourceRoot(HTMLParser):
    """显式内容根优先；旧合法独立页只允许唯一main作窄范围兼容。"""
    def __init__(self, source: str):
        super().__init__(convert_charrefs=True)
        self.offsets = [0] + [match.end() for match in re.finditer("\n", source)]
        self.explicit, self.mains = [], []

    def handle_starttag(self, tag, attrs):
        line, column = self.getpos()
        offset = self.offsets[line - 1] + column
        if "data-prototype-page-content" in dict(attrs): self.explicit.append(offset)
        if tag == "main": self.mains.append(offset)

    handle_startendtag = handle_starttag

    def selected(self):
        if self.explicit:
            if len(self.explicit) != 1: raise ValueError("来源页面必须有唯一显式内容根")
            return self.explicit[0], False
        if len(self.mains) != 1: raise ValueError("没有显式内容根时来源页面必须有唯一main")
        return self.mains[0], True


class _SourceTargets(HTMLParser):
    """保留原始字符位置，避免重新序列化 HTML 改变用户稿件字节。"""
    def __init__(self, page: str, source: str, root_offset: int, implicit_root: bool):
        super().__init__(convert_charrefs=True)
        self.page, self.source = page, source
        self.root_offset, self.implicit_root = root_offset, implicit_root
        self.line_offsets = [0]
        self.line_offsets.extend(match.end() for match in re.finditer("\n", source))
        self.ids, self.source_keys, self.contracts, self.req_ids = Counter(), {}, {}, {}
        self.stack, self.insertions, self.roots = [], [], 0

    def handle_starttag(self, tag, attributes):
        attrs = dict(attributes)
        if len(attrs) != len(attributes):
            raise ValueError("来源 HTML 不得含重复属性")
        if any(name.startswith("data-prototype-review-") for name in attrs):
            raise ValueError("来源 HTML 使用了评审器保留属性")
        identifier = attrs.get("id")
        if "id" in attrs:
            if not identifier or not workspace.STABLE_ID_PATTERN.fullmatch(identifier):
                raise ValueError("DOM ID 必须是原样的稳定标识")
            self.ids[identifier] += 1
            if self.ids[identifier] != 1:
                raise ValueError("DOM ID 不得重复：" + identifier)
        line, column = self.getpos()
        offset = self.line_offsets[line - 1] + column
        root = offset == self.root_offset
        if root: self.roots += 1
        inside = root or any(entry[1] for entry in self.stack)
        forbidden = tag in FORBIDDEN_TAGS or any(entry[2] for entry in self.stack)
        if root and forbidden: raise ValueError("来源内容根位于不允许的区域")
        contract = None
        if "data-contract-for" in attrs:
            target = attrs["data-contract-for"].strip()
            if target in self.contracts: raise ValueError("目标存在重复契约：" + target)
            contract = {"id": identifier, "interface_refs": set()}
            self.contracts[target] = contract
        owners = [entry[3] for entry in self.stack if entry[3] is not None]
        if contract is not None: owners.append(contract)
        reference = attrs.get("data-interface-ref")
        if reference is not None and reference.strip():
            for owner in owners: owner["interface_refs"].add(reference)
        if inside and not forbidden:
            key = "source-" + hashlib.sha256(("agent-workflow/prototype-source/v1\0" + self.page + "\0" + str(offset)).encode("utf-8")).hexdigest()
            locator = {"type": "id", "id": identifier} if identifier else {"type": "source", "key": key}
            self.source_keys[key] = locator
            # 只接受节点自身明确声明的业务映射，不从自由文字或工具需求目录推断。
            declared = attrs.get("data-req-ids", "").split()
            if any(not re.fullmatch(r"REQ-[0-9]{3,}", value) for value in declared) or len(set(declared)) != len(declared):
                raise ValueError("来源节点的显式需求映射无效")
            self.req_ids[(locator["type"], identifier or key)] = declared
            raw = self.get_starttag_text()
            end = offset + len(raw) - (2 if raw.endswith("/>") else 1)
            # fallback属性仅写项目外快照；浏览器仍使用同一唯一内容根合同。
            root_attribute = " data-prototype-page-content" if root and self.implicit_root else ""
            self.insertions.append((end, root_attribute + ' ' + SOURCE_ATTRIBUTE + '="' + key + '"'))
        if tag not in workspace.HTML_VOID_ELEMENTS:
            self.stack.append((tag, inside, forbidden, contract))

    def handle_startendtag(self, tag, attributes):
        self.handle_starttag(tag, attributes)
        if tag not in workspace.HTML_VOID_ELEMENTS: self.handle_endtag(tag)

    def handle_endtag(self, tag):
        for index in range(len(self.stack) - 1, -1, -1):
            if self.stack[index][0] == tag:
                del self.stack[index:]
                break


def _capture(page: str, body: bytes) -> _SourceTargets:
    source = body.decode("utf-8")
    roots = _SourceRoot(source)
    roots.feed(source); roots.close()
    root_offset, implicit_root = roots.selected()
    parser = _SourceTargets(page, source, root_offset, implicit_root)
    parser.feed(source); parser.close()
    if parser.roots != 1: raise ValueError("来源页面必须有唯一内容根")
    return parser


def capture_targets(page: str, body: bytes) -> dict:
    """只读返回来源目录，失败抛ValueError。

    ids统计全页唯一ID；allowed_ids限定允许内容区。source_keys把注入键映射
    到优先ID的规范locator；req_ids以(type, id或key)为键保存节点自身明确
    业务映射。contracts保留data-contract-for的原契约及显式接口引用集合。
    这些只供Python独立复核，不投影成第二份浏览器页面结构。
    """
    parser = _capture(page, body)
    allowed_ids = {entry["id"] for entry in parser.source_keys.values() if entry["type"] == "id"}
    return {"ids": parser.ids, "source_keys": parser.source_keys, "contracts": parser.contracts,
            "req_ids": parser.req_ids, "allowed_ids": allowed_ids}


def inject_source_targets(page: str, body: bytes) -> bytes:
    """仅在派生快照插入保留属性；用户 HTML 字节和文件永远保持原状。"""
    parser = _capture(page, body)
    source = parser.source
    for offset, addition in reversed(parser.insertions): source = source[:offset] + addition + source[offset:]
    return source.encode("utf-8")


def canonical_target(value: object, pages: list[str]) -> dict:
    """封闭 target 判别联合；失败抛 ValueError，没有路径猜测或自动父层绑定。"""
    if not isinstance(value, dict): raise ValueError("目标必须是对象")
    scope = value.get("scope")
    if not isinstance(scope, str): raise ValueError("目标范围必须是文字")
    if scope == "global":
        if set(value) != {"scope"}: raise ValueError("本轮整体目标字段无效")
    elif scope in {"page", "node"}:
        if set(value) != ({"scope", "page", "locator"} if scope == "node" else {"scope", "page"}):
            raise ValueError("页面或节点目标字段无效")
        page = value["page"]
        if not isinstance(page, str) or normalized_relative(page).as_posix() != page or page not in pages:
            raise ValueError("目标页面不在登记范围")
        if scope == "node":
            locator = value["locator"]
            if not isinstance(locator, dict): raise ValueError("节点定位必须是对象")
            if locator.get("type") == "id":
                if set(locator) != {"type", "id"} or not isinstance(locator["id"], str) or not workspace.STABLE_ID_PATTERN.fullmatch(locator["id"]):
                    raise ValueError("节点 ID 定位无效")
            elif locator.get("type") == "source":
                if set(locator) != {"type", "key"} or not isinstance(locator["key"], str) or not SOURCE_KEY_PATTERN.fullmatch(locator["key"]):
                    raise ValueError("节点来源定位无效")
            else: raise ValueError("未知节点定位类型")
    else: raise ValueError("未知目标范围")
    return value


def validate_source_target(target: dict, metadata: dict) -> None:
    """确认目标确实来自允许的原始内容区，而非运行时新造节点或工具外壳。"""
    if target["scope"] != "node": return
    page = metadata[target["page"]]
    locator = target["locator"]
    if locator["type"] == "id":
        if locator["id"] not in page["allowed_ids"]: raise ValueError("目标 ID 不在来源内容区")
    else:
        found = page["source_keys"].get(locator["key"])
        if found is None or found["type"] != "source":
            raise ValueError("来源键不存在或目标应优先使用稳定 ID")


def json_bytes(value: object) -> bytes:
    """规范排序的身份字节；浏览器安全转义只改变运输文本，不改变内容身份。"""
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def review_id(context: dict) -> str:
    """身份不包含自身字段，避免装配与独立消费者各自维护哈希语义。"""
    return digest(json_bytes({key: value for key, value in context.items() if key != "review_id"}))


MAX_CONTEXT_BYTES = 8 * 1024
MAX_FRAGMENT_BYTES = 12 * 1024
MAX_PAGES = 16
MAX_FEEDBACK_BYTES = 1024 * 1024
MAX_ITEMS = 256
MAX_TEXT_LENGTH = 4000
MAX_ID_LENGTH = 128
MAX_INTERFACE_REFS = 32
MAX_INTERFACE_LENGTH = 512
CONTEXT_FIELDS = {"schema_version", "request_id", "adapter", "prototype_root", "plan_source",
                  "plan_sha256", "requirements", "pages", "project_id", "adapter_sha256",
                  "navigation_sha256", "tool", "review_id"}
ITEM_FIELDS = {"id", "page", "target_id", "kind", "message", "req_ids"}
OPTIONAL_ITEM_FIELDS = {"comparison", "interaction_id", "interface_refs"}
REQ_PATTERN = re.compile(r"(?<![A-Za-z0-9_-])REQ-[0-9]{3,}(?![A-Za-z0-9_-])")
ID_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]*\Z")
SHA_PATTERN = re.compile(r"[0-9a-f]{64}\Z")


class FeedbackError(ValueError):
    """反馈格式、来源绑定或节点归属不能安全确认。"""


def _json_bytes(value: object) -> bytes:
    try:
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8")
    except (ValueError, TypeError, UnicodeError, RecursionError) as exc:
        raise FeedbackError("反馈必须是有界的 UTF-8 JSON 数据") from exc


def _unique_object(pairs: list[tuple[str, object]]) -> dict:
    # 所有嵌套对象共用此入口；不能让解析器的最后一个值覆盖重复字段后继续核验。
    result = {}
    for key, value in pairs:
        if key in result:
            raise FeedbackError("JSON 不得含有重复字段：" + key)
        result[key] = value
    return result


def _object(value: object, required: set[str], label: str, optional: set[str] | None = None) -> dict:
    if not isinstance(value, dict) or not required.issubset(value) or set(value) - required - (optional or set()):
        raise FeedbackError(f"{label}字段缺失或包含未知字段")
    return value


def _text(value: object, label: str, limit: int, *, empty: bool = False) -> str:
    if not isinstance(value, str) or len(value) > limit or (not empty and not value.strip()) or "\0" in value:
        raise FeedbackError(f"{label}须为限额内的文字")
    try:
        value.encode("utf-8")
    except UnicodeError as exc:
        raise FeedbackError(f"{label}不是有效 UTF-8") from exc
    return value


def _identifier(value: object, label: str, *, dom: bool = False) -> str:
    text = _text(value, label, MAX_ID_LENGTH)
    if not (workspace.STABLE_ID_PATTERN if dom else ID_PATTERN).fullmatch(text):
        raise FeedbackError(f"{label}不是稳定标识")
    return text


def _relative(value: object, label: str) -> str:
    text = _text(value, label, 1024)
    # 路径还要能原样进入浏览器上下文；URL 保留符/控制符不能被前端另行解释。
    if re.search(r"[:#?%\x00-\x1f\x7f]", text):
        raise FeedbackError(f"{label}含有不支持的 URL 保留字符或控制字符")
    return normalized_relative(text).as_posix()


def _strings(value: object, label: str, limit: int, item_limit: int) -> list[str]:
    if not isinstance(value, list) or len(value) > limit:
        raise FeedbackError(f"{label}须为限额内的数组")
    result = [_text(item, label, item_limit) for item in value]
    if len(result) != len(set(result)):
        raise FeedbackError(f"{label}不得重复")
    return result


def _version(value: object, label: str) -> None:
    # bool 是 Python int 的子类，但不属于 JSON 协议版本；必须使用精确整数类型。
    if type(value) is not int or value != 2:
        raise FeedbackError(f"{label}仅支持 schema_version 2（旧协议须重新 prepare）")


def check_context(value: object) -> dict:
    context = _object(value, CONTEXT_FIELDS, "评审上下文")
    if len(_json_bytes(context)) > MAX_CONTEXT_BYTES:
        raise FeedbackError("评审上下文超过 8 KiB 限额")
    _version(context["schema_version"], "评审上下文")
    _identifier(context["request_id"], "请求 ID")
    for key in ("adapter", "prototype_root", "plan_source"):
        _relative(context[key], key)
    for key in ("plan_sha256", "adapter_sha256", "navigation_sha256", "project_id", "review_id"):
        if not isinstance(context[key], str) or not SHA_PATTERN.fullmatch(context[key]):
            raise FeedbackError("评审摘要无效：" + key)
    tool = _object(context["tool"], {"version", "payload_sha256"}, "工具绑定")
    if (not isinstance(tool["version"], str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9.+_-]{0,127}", tool["version"])
            or not isinstance(tool["payload_sha256"], str) or not SHA_PATTERN.fullmatch(tool["payload_sha256"])):
        raise FeedbackError("工具版本或载荷摘要无效")
    if review_id(context) != context["review_id"]:
        raise FeedbackError("评审内容身份不匹配")
    requirements = context["requirements"]
    if not isinstance(requirements, list) or not requirements:
        raise FeedbackError("需求标签须为非空数组")
    req_ids = []
    for requirement in requirements:
        _object(requirement, {"id", "label"}, "需求标签")
        if not isinstance(requirement["id"], str) or not REQ_PATTERN.fullmatch(requirement["id"]):
            raise FeedbackError("需求 ID 无效")
        _text(requirement["label"], "需求标签", MAX_CONTEXT_BYTES)
        req_ids.append(requirement["id"])
    if len(req_ids) != len(set(req_ids)):
        raise FeedbackError("需求标签 ID 不得重复")
    pages = context["pages"]
    if not isinstance(pages, list) or not 1 <= len(pages) <= MAX_PAGES:
        raise FeedbackError("评审页数须为 1 至 16 页")
    paths = []
    for page in pages:
        _object(page, {"path", "dependency_fingerprint"}, "评审页面")
        path = _relative(page["path"], "页面路径")
        if not isinstance(page["dependency_fingerprint"], str) or not SHA_PATTERN.fullmatch(page["dependency_fingerprint"]):
            raise FeedbackError("页面依赖指纹无效")
        paths.append(path)
    if len(paths) != len(set(paths)):
        raise FeedbackError("评审页面不得重复")
    return context



def _requirements(body: bytes) -> list[dict[str, str]]:
    """投影现有 Markdown 标签，不生成 REQ，也不把重复导航提及当作新需求。"""
    result = {}
    fence = None
    for line in body.decode("utf-8").splitlines():
        stripped = line.lstrip()
        marker = re.match(r"(`{3,}|~{3,})", stripped)
        if marker:
            if fence is None:
                fence = marker[1][0]
            elif fence == marker[1][0]:
                fence = None
            continue
        if fence is not None:
            continue
        for match in REQ_PATTERN.finditer(line):
            req_id = match[0]
            if req_id in result:
                continue
            # 表格优先保留需求列中的标签；正文去掉紧随 ID 的 Markdown/标点语法。
            label = " ".join(line[match.end():].split("|", 1)[0].strip().strip("`*_ []：:-").split())
            result[req_id] = {"id": req_id, "label": label or req_id}
    if not result:
        raise FeedbackError("选定 Markdown 中没有已存在的 REQ 标签")
    return list(result.values())


class _ContractReferences(HTMLParser):
    """只读提取目标契约内明确声明的引用，绝不从链接或文字猜测接口。"""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.contracts = {}
        self.stack = []
        self.ids = Counter()

    def handle_starttag(self, tag, attributes):
        attrs = dict(attributes)
        if "id" in attrs:
            stable_id = attrs["id"]
            if not stable_id or not workspace.STABLE_ID_PATTERN.fullmatch(stable_id):
                raise FeedbackError("DOM ID 必须是原样的稳定标识，不可用空白修正后定位")
            self.ids[stable_id] += 1
            if self.ids[stable_id] != 1:
                raise FeedbackError("DOM ID 不得重复：" + stable_id)
        contract = None
        if "data-contract-for" in attrs:
            target = attrs["data-contract-for"].strip()
            if target in self.contracts:
                raise FeedbackError("目标存在重复契约：" + target)
            contract = {"id": attrs.get("id"), "interface_refs": set()}
            self.contracts[target] = contract
        owners = [owner for _, owner in self.stack if owner is not None]
        if contract is not None:
            owners.append(contract)
        reference = attrs.get("data-interface-ref")
        if reference is not None and reference.strip():
            # 属性原始字面值是对照依据，不 trim 后重绑；只检查空白/限额，不解释成 URL。
            for owner in owners:
                owner["interface_refs"].add(reference)
        if tag not in workspace.HTML_VOID_ELEMENTS:
            self.stack.append((tag, contract))

    def handle_startendtag(self, tag, attributes):
        self.handle_starttag(tag, attributes)
        if tag not in workspace.HTML_VOID_ELEMENTS:
            self.handle_endtag(tag)

    def handle_endtag(self, tag):
        for index in range(len(self.stack) - 1, -1, -1):
            if self.stack[index][0] == tag:
                del self.stack[index:]
                break
