# Project — {{PROJECT_NAME}}

> Canonical project directory. Keep only current scope and links; replace
> entries in place and never append task chronicles, QA transcripts, scheduler state, or raw logs.

## Current project

- Product purpose and current scope: **TODO**

## Active features

| Feature | Current summary | Detail |
|---|---|---|
| None recorded | Initialize after the first feature passes QA | — |

Only QA-verified active features belong here. After QA verifies a complete feature removal, delete
its row and rename its detail document to `<feature>.removed.md` in `{{DOC_FEATURES_DIR}}/`.

## Controlled documents

- Feature details and current architectural rationale: `{{DOC_FEATURES_DIR}}/`
- Requirement plans (唯一可编辑 `.md` + 同名派生 `.html`；意图/恢复及历史，非当前功能事实): `{{DOC_PLANS_DIR}}/`
- 项目特有规范索引（存在时）：`{{DOC_STANDARDS}}`；通用工程/UI 规则来自内置 `xy-code-standards` / `xy-ui-design`。
- Prototype evidence, when configured: `{{DOC_DESIGN_DIR}}/prototype/`
- Optional memory fallback: `{{DOC_NOTES_DIR}}/`
