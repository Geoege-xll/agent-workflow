"""原型反馈的只读准备、封闭协议与真实来源复核，不承担修订或批准。"""

from __future__ import annotations

import copy
import json
from collections import Counter
from html.parser import HTMLParser
from pathlib import Path
import re
from urllib.parse import urlencode

from lib.documents import prototype_review as review

from lib.documents.safe_documents import digest, normalized_relative, snapshot
from lib.documents import validate_prototype_workspace as workspace
from lib.project.validate_project_config import validate_docs
from lib.runtime_pins import adapter_path, record_binding


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
NOTICE = "本结果仅为用户修订输入；当前文字是浏览器摘录，建议文字是修改提案，没有可信已批准基线。不会自动修改文件或授予批准。"


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


def parse_feedback(raw: bytes) -> dict:
    """在执行任何文件来源核验前拒绝超限、重复键和非标准 JSON 数字。"""
    if not isinstance(raw, bytes) or len(raw) > MAX_FEEDBACK_BYTES:
        raise FeedbackError("反馈文件超过 1 MiB 限额")
    try:
        value = json.loads(raw.decode("utf-8", errors="strict"), object_pairs_hook=_unique_object,
                           parse_constant=lambda _: (_ for _ in ()).throw(FeedbackError("反馈不得含非标准 JSON 数字")))
    except (UnicodeError, json.JSONDecodeError, RecursionError) as exc:
        raise FeedbackError("反馈不是有效的 UTF-8 JSON 对象") from exc
    _object(value, {"schema_version", "context", "items"}, "反馈")
    return value


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


def _check_context(value: object) -> dict:
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
    if review.review_id(context) != context["review_id"]:
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


def _capture_review(root: str | Path, adapter: str, plan: str, request_id: str,
                    pages: list[str] | None, *, tool: dict) -> tuple[dict, dict, dict, list]:
    """无条件确认项目画像与来源，再复用原校验器；导航缺失不能跳过这些边界。"""
    project = Path(root)
    if not project.is_absolute() or ".." in project.parts or "\\" in str(project):
        raise FeedbackError("项目根必须是无父跳转的实际绝对目录")
    # 使用原校验器逐祖先 no-follow 打开目录；不能先 resolve 后把符号链接别名洗成安全路径。
    descriptor = workspace._open_root(project, "反馈项目根")
    workspace.os.close(descriptor)
    _identifier(request_id, "请求 ID")
    adapter = _relative(adapter, "适配器路径")
    plan = _relative(plan, "需求路径")
    binding = record_binding({}, root=project, initialize=True)
    if binding is not None:
        raise FeedbackError("反馈入口不接管中央固定运行时任务")
    selected = adapter_path(project, adapter, binding)
    if selected != adapter:
        raise FeedbackError("适配器不属于当前显式选择")
    captures = {}

    def capture(path):
        current = snapshot(path)
        if path in captures and captures[path] != current:
            raise FeedbackError("反馈来源在读取期间发生变化：" + path.name)
        captures[path] = current
        return current[0]

    adapter_body = capture(project / adapter)
    lines = adapter_body.decode("utf-8").splitlines()
    if sum(bool(re.fullmatch(r"docs:\s*(?:#.*)?", line)) for line in lines) != 1:
        raise FeedbackError("适配器必须包含唯一 docs 配置")
    errors = []
    docs = validate_docs(lines, project, errors)
    if errors:
        raise FeedbackError("适配器文档配置无效：" + "; ".join(errors))
    prototype = _relative(docs["standards_root"].rstrip("/") + "/prototype", "原型根")
    plans = normalized_relative(docs["plans"].rstrip("/"))
    relative_plan = normalized_relative(plan)
    if (relative_plan.suffix != ".md" or not relative_plan.is_relative_to(plans)
            or any(part.startswith(".") for part in relative_plan.parts)):
        raise FeedbackError("需求来源必须是所选 adapter 的 docs.plans 内 Markdown")
    plan_body = capture(project / plan)
    prototype_path = project / prototype
    descriptor = workspace._open_root(prototype_path, "反馈原型根")
    workspace.os.close(descriptor)
    if pages is None:
        chosen = sorted((Path(prototype) / path.name).as_posix() for path in prototype_path.iterdir()
                        if path.name != "index.html" and path.suffix.lower() in {".html", ".htm"})
    else:
        if not isinstance(pages, list):
            raise FeedbackError("pages 必须是项目相对 HTML 路径数组")
        chosen = [_relative(page, "页面路径") for page in pages]
    if not 1 <= len(chosen) <= MAX_PAGES or len(chosen) != len(set(chosen)):
        raise FeedbackError("须选择 1 至 16 个不重复页面")
    for page in chosen:
        if Path(page).parent != Path(prototype) or Path(page).name == "index.html":
            raise FeedbackError("评审页面须为配置原型根下的具体 HTML")
    chosen.sort()
    metadata = {}
    for page in chosen:
        body = capture(project / page).decode("utf-8")
        parser = workspace.PageParser(page)
        parser.feed(body)
        parser.close()
        if parser.plan_source and parser.plan_source != plan:
            raise FeedbackError("评审页面已绑定另一份需求 Markdown：" + page)
        references = _ContractReferences()
        references.feed(body)
        references.close()
        metadata[page] = {"ids": references.ids, "contracts": references.contracts}
    # 沿用同一 DependencyValidator 与指纹域；独立页不再依赖项目通用外壳。
    evidence = workspace.capture_selected_pages(project, prototype, pages=[Path(page).name for page in chosen], adapter=adapter)
    index_path = prototype_path / "index.html"
    index_snapshot = snapshot(index_path, required=False)
    index_body = index_snapshot[0]
    context = {"schema_version": 2, "request_id": request_id, "adapter": adapter, "prototype_root": prototype,
               "plan_source": plan, "plan_sha256": digest(plan_body), "requirements": _requirements(plan_body),
               "pages": evidence["pages"], "project_id": review.project_id(project),
               "adapter_sha256": digest(adapter_body), "navigation_sha256": digest(index_body or b""),
               "tool": copy.deepcopy(tool)}
    context["review_id"] = review.review_id(context)
    _check_context(context)
    # adapter/Markdown/节点元数据均由 snapshot 末尾复查，防止绑定检查与结果之间被替换。
    for path in tuple(captures):
        capture(path)
    if snapshot(index_path, required=False) != index_snapshot:
        raise FeedbackError("旧索引在评审捕获期间发生变化")
    files = dict(evidence["files"])
    files[plan] = plan_body
    navigation = review.navigation_data(index_body, evidence["pages"], files)
    return context, metadata, files, navigation


def prepare_review(root: str | Path, adapter: str, plan: str, request_id: str,
                   pages: list[str] | None = None, *, data_dir: str | Path | None = None) -> dict:
    """将固定工具与选定业务页面装配成用户级私有离线快照，不写项目。"""
    review.require_external_data_dir(root, data_dir)
    tool, tools = review.capture_tool()
    context, _, files, navigation = _capture_review(root, adapter, plan, request_id, pages, tool=tool)
    published = review.publish_bundle(context, files, tools, navigation, data_dir=data_dir)
    review_url = (Path(published["bundle_path"]) / "index.html").as_uri() + "#" + urlencode({"page": navigation[0]["name"]})
    return {"status": "ready", "context": context, "review_url": review_url, **published}


def validate_feedback(root: str | Path, adapter: str, feedback: dict, *,
                      data_dir: str | Path | None = None) -> dict:
    """重算权威输入并按稳定节点交接；意见字样和哈希相等都不授予修订/批准权限。"""
    # 公开 Python API 与 CLI 使用同样的限额和封闭字段，不信任调用方已做前端校验。
    if len(_json_bytes(feedback)) > MAX_FEEDBACK_BYTES:
        raise FeedbackError("反馈文件超过 1 MiB 限额")
    envelope = _object(feedback, {"schema_version", "context", "items"}, "反馈")
    _version(envelope["schema_version"], "反馈")
    context = _check_context(envelope["context"])
    review.require_external_data_dir(root, data_dir)
    if adapter != context["adapter"]:
        raise FeedbackError("反馈适配器与显式选择不一致")
    items = envelope["items"]
    if not isinstance(items, list) or len(items) > MAX_ITEMS:
        raise FeedbackError("反馈条目须为最多 256 项的数组")
    item_ids = set()
    req_ids = {req["id"] for req in context["requirements"]}
    pages = [page["path"] for page in context["pages"]]
    for item in items:
        _object(item, ITEM_FIELDS, "反馈条目", OPTIONAL_ITEM_FIELDS)
        item_id = _identifier(item["id"], "反馈 ID")
        if item_id in item_ids:
            raise FeedbackError("反馈 ID 不得重复")
        item_ids.add(item_id)
        if _relative(item["page"], "反馈页面") not in pages:
            raise FeedbackError("反馈页面不在本次评审范围")
        _identifier(item["target_id"], "目标 ID", dom=True)
        if not isinstance(item["kind"], str) or item["kind"] not in {"must_change", "suggestion", "question"}:
            raise FeedbackError("反馈等级无效")
        _text(item["message"], "反馈文字", MAX_TEXT_LENGTH)
        associated = _strings(item["req_ids"], "关联需求", len(req_ids), MAX_ID_LENGTH)
        if set(associated) - req_ids:
            raise FeedbackError("关联需求不在当前 Markdown 中")
        if "comparison" in item:
            comparison = _object(item["comparison"], {"before_text", "after_text"}, "局部提案")
            for key in ("before_text", "after_text"):
                _text(comparison[key], "局部提案文字", MAX_TEXT_LENGTH, empty=True)
        if "interaction_id" in item:
            _identifier(item["interaction_id"], "交互契约 ID", dom=True)
        if "interface_refs" in item:
            if not _strings(item["interface_refs"], "接口引用", MAX_INTERFACE_REFS, MAX_INTERFACE_LENGTH):
                raise FeedbackError("没有明确接口引用时必须省略 interface_refs")
    # 原离线包是当轮工具字节的权威；插件升级不要求旧缓存长期保留，
    # 也不允许把旧反馈静默绑定到新工具。项目源则必须每次真实重读。
    review.validate_bundle(context, data_dir=data_dir)
    current, metadata, current_files, navigation = _capture_review(root, adapter, context["plan_source"], context["request_id"], pages, tool=context["tool"])
    review.validate_bundle(context, data_dir=data_dir, source_files=current_files, navigation=navigation)
    if current != context:
        raise FeedbackError("反馈绑定已过期或来源不匹配；请保留原意见并重新准备评审")
    changes = {}
    for item in items:
        page = metadata[item["page"]]
        if page["ids"][item["target_id"]] != 1:
            raise FeedbackError("反馈目标不存在或 DOM ID 重复：" + item["target_id"])
        contract = page["contracts"].get(item["target_id"])
        if "interaction_id" in item:
            interaction_id = item["interaction_id"]
            if contract is None or contract["id"] != interaction_id or page["ids"][interaction_id] != 1:
                raise FeedbackError("交互关联不属于当前目标的唯一契约")
        if "interface_refs" in item:
            if contract is None or set(item["interface_refs"]) - contract["interface_refs"]:
                raise FeedbackError("接口引用未在当前目标契约中明确声明")
        key = (item["page"], item["target_id"])
        changes.setdefault(key, {"page": key[0], "target_id": key[1], "items": []})["items"].append(copy.deepcopy(item))
    return {"status": "current", "context": current, "changes": [changes[key] for key in sorted(changes)], "notice": NOTICE}
