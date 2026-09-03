# Task A — the `## Verification program` section of README.md

Compound V run `2026-09-03-verification-index-readme-section`, job `readme-section`.

Task A (docs only): read the footer of docs/superpowers/dogfood/README.md (`Reviews: N · APPROVED: A · ISSUES: I · other: O`), then insert a `## Verification program` section before the last existing `##` section of README.md: (1) what the program is — stages 1–8, each a dogfood cycle that runs this plugin against a native Claude Code mechanism and fixes what breaks; (2) a real markdown link to docs/superpowers/dogfood/README.md written exactly as that root-relative path, no leading slash; (3) the sentence `N review files, A APPROVED` with the footer's numbers verbatim. No other README change. Quote the footer line in your summary. Run python with -B; register your lane with a literal --cwd. You are unattended: decide and return. Pre-flight audits: docs/superpowers/archaeology/2026-09-03-epic-vi-readme-section.md (§7 MUSTs) and docs/superpowers/library-audit/2026-09-03-epic-vi-readme-section.md — read §7/§8 first.

Prerequisites, already merged and COMMITTED into your base before this worktree was created: index-refresh.

## You are unattended

No one reads this session while it runs and no one will answer a question:
a turn that ends by asking for confirmation, approval or a preference does
NOTHING, and the job is then recorded as an absent implementation. Decide
with the spec, the plan and this prompt; when they are silent, choose the
smallest change that meets the acceptance, do it, run the checks, and return.

## Write-allowed (your lane — anything else is a scope violation)

- `README.md`

## Read-allowed (advisory — git cannot enforce reads)

- `**`

## Acceptance (your definition of done)

- README.md has exactly one `## Verification program` section, inserted before the LAST existing `##` heading: three sentences — what the program is (stages 1–8, each a dogfood cycle against native Claude Code mechanisms), a link to docs/superpowers/dogfood/README.md, and `N review files, A APPROVED` with N and A copied from that file's footer line `Reviews: N · APPROVED: A · …` as it is in HEAD (index-refresh ran first); `/usr/bin/python3 -B scripts/lint-frontmatter.py .` green. The link is a real markdown link `[…](docs/superpowers/dogfood/README.md)` — no leading slash (pre-flight 1A: leading-slash links are exempt from the dead-link CI gate).

Turn cap: 30 (default for tier light; default light 30 / standard 50 / deep 80). Plan to finish inside it.

## What you must NOT report

Do not report `blocked`, `files_changed` or `violations`. Those are
enforcement fields, they are derived from git by the caller, and a
constrained party filling in its own enforcement fields is the
fabricated-evidence pattern.
