# Task A — the same six glob rules in memory.md and execution-manifest.md, each naming the other and the parity selftest

Compound V run `2026-09-03-glob-parity-matcher-docs-r2`, job `docs-contract`.

Implement Task A of docs/superpowers/plans/2026-09-03-epic-gp-matcher-docs-r2.md EXACTLY, starting with its Step 0 (undo attempt 1's two hunks from commit d7dc25d). The paragraph (Step 2) and the row (Step 3) are pasted VERBATIM from the plan — do not paraphrase, shorten or move them. Placement: the paragraph goes after the end of the Per-job fields section (after its footnote and trailing paragraph, immediately before the ### Tier vocabulary heading), never inside the table; the memory.md row replaces ONE physical line so the file's line count is unchanged. If you believe any constraint cannot be met, STOP, change nothing further, and say exactly which one in your summary. Only skills/compound-v/memory.md and skills/compound-v/execution-manifest.md may change. Verify with the plan's Step 4 commands and commit in your worktree.

## You are unattended

No one reads this session while it runs and no one will answer a question:
a turn that ends by asking for confirmation, approval or a preference does
NOTHING, and the job is then recorded as an absent implementation. Decide
with the spec, the plan and this prompt; when they are silent, choose the
smallest change that meets the acceptance, do it, run the checks, and return.

## Write-allowed (your lane — anything else is a scope violation)

- `skills/compound-v/memory.md`
- `skills/compound-v/execution-manifest.md`

## Read-allowed (advisory — git cannot enforce reads)

- `**`

## Acceptance (your definition of done)

- grep -c "the same matcher" prints 1 for each of the two files; grep -n fnmatch on both prints nothing; no other section of either file changed (git diff --stat shows only the two files, each with one hunk region); lint-frontmatter clean.

Turn cap: 80 (default for tier deep; default light 30 / standard 50 / deep 80). Plan to finish inside it.

## What you must NOT report

Do not report `blocked`, `files_changed` or `violations`. Those are
enforcement fields, they are derived from git by the caller, and a
constrained party filling in its own enforcement fields is the
fabricated-evidence pattern.
