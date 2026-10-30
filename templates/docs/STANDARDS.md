# Standards — {{PROJECT_NAME}}

> Canonical directory for enforceable engineering and design rules. Keep this file as a concise
> index; detailed rules live in the linked leaf documents, while approved prototype evidence lives
> under standards/prototype and is read only when it applies.

## Usage contract

- Every rule uses a stable lowercase ID and declares `hard` or `advisory` severity.
- Normative Markdown leaves live directly in the configured standards root. Design leaves use
  `DESIGN_*.md` and `- Domain: design`; other leaves declare `- Domain: engineering`. Group links
  below by domain and describe applicable modules/paths; do not add engineering/design/references subtrees.
- PM Task Packs select the smallest applicable leaf documents, bind their current fingerprints and
  rule IDs to exact owned paths, and never preload the whole standards tree.
- `GENERAL.md` 是生产代码变更（包括 Trivial 主会话直接修改）的基础工程规范叶。
  执行者须读取其中适用的共通开发规范；有派发和独立 QA 时，PM、实现 Agent 与 QA
  各自按职责读取。其他工程规范叶按任务相关性选取；纯原型设计任务只使用设计规范叶。
- Subagents must follow every selected rule. A missing, stale, or incomplete applicable rule set
  blocks dispatch or QA PASS; “read on demand” is not permission to ignore a relevant standard.
- Update current rules in place. Git retains history; this directory does not record task logs.
- PM assesses/adopts design-rule changes; UI Agent maintains authorized leaves. Initial adoption,
  incremental changes and full visual replacement update only their approved scope. A feature-doc
  no-op does not imply a standards no-op; refresh affected consumers after rule adoption.
- Normative design rules live in leaves, not a duplicate HTML index. Adopted rules do not assert
  that all production pages have migrated; use verified feature truth for completed migration.

## Engineering standards

{{ENGINEERING_STANDARDS_INDEX}}

## Design standards

{{DESIGN_STANDARDS_INDEX}}

## Related controlled truth

- Current project and feature index: `{{DOC_PROJECT}}`
- Current functional and architectural rationale: `{{DOC_FEATURES_DIR}}/`
- Prototype evidence, when configured: `{{DOC_DESIGN_DIR}}/prototype/`
