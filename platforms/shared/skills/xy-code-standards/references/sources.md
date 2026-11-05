# Sources and adoption boundaries

Read this file on demand for maintenance and traceability. It is not required for every implementation and does
not require network access or installation/execution of third-party tools. Only methods are borrowed below;
the text was originally reorganized in Chinese. Project standards, authorization and verification contracts retain authority.

## Karpathy community guidelines

- Original entry: [forrestchang/andrej-karpathy-skills](https://github.com/forrestchang/andrej-karpathy-skills);
  it redirected to `multica-ai/andrej-karpathy-skills` when checked.
- Primary file: [karpathy-guidelines/SKILL.md](https://github.com/multica-ai/andrej-karpathy-skills/blob/main/skills/karpathy-guidelines/SKILL.md).
  Its frontmatter declares `license: MIT`. This community project organizes Karpathy's observations;
  do not describe it as his official release.
- Adopted: distinguish assumptions explicitly, control change scope and judge completion by verifiable results.
- Not adopted: fixed line-count targets, a blanket ban on abstractions used once, stopping to ask about every
  question, or the examples' test-first steps. Judge abstraction, confirmation and new tests by actual boundaries
  and existing contracts.

## Vercel official engineering Skill

- Primary repository: [vercel-labs/agent-skills](https://github.com/vercel-labs/agent-skills).
- Primary file: [react-best-practices/SKILL.md](https://github.com/vercel-labs/agent-skills/blob/main/skills/react-best-practices/SKILL.md).
  The file credits `vercel` and declares `license: MIT`.
- Adopted: organize concerns by actual impact and use matching conditions to determine detailed reference reads.
- Not adopted: React/Next.js APIs, caching/rendering rules, dependencies, versions or that stack's risk ordering;
  do not generalize them into requirements for every language/project.

## Local sampling and maintenance

Applicability has been checked against project standards and real modules/tests across different stacks.
Specific projects, source locations and session evidence remain in task handoffs. They are not prerequisites
for using this Skill. Do not copy business rules or machine paths, or infer a universal framework, version or
visual style from examples.

For later updates, check the provenance and license declarations of the files actually adopted. If copying
third-party text/code, retain the applicable license and attribution for that version. Current content introduces
no mandatory TDD, additional review, commit or release process.
