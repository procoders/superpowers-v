# Task A — reset both files to 16786b7 and paste the exact paragraph and row (attempt 3)

Compound V run `2026-09-03-glob-parity-matcher-docs-r3`, job `docs-exact`.

Docs-only, exact text, no composition. Step 0: `git checkout 16786b7 -- skills/compound-v/memory.md skills/compound-v/execution-manifest.md` (restores the pre-F2 content; verify wc -l memory.md = 202). Step 1: in skills/compound-v/execution-manifest.md insert the following paragraph immediately BEFORE the line `### Tier vocabulary (stable — never changes when models churn)`, with one blank line before and after, character for character:
**Glob semantics (`write_allowed`, `read_allowed`, `impacted_map.when`).** `*` matches within one path segment (never `/`); `**` matches across segments; `dir/**` also matches `dir` itself; `?` matches one non-`/` character; `[` and `]` are literal (no character classes — `app/[locale]/**` is a real directory); matching is anchored to the full repo-relative path. This is the scope gate's own matcher (`scripts/compound-v-scope-check.py` `matches`), and V-memory's `recall-check` uses the same matcher — see [`memory.md`](memory.md); the proof is the `parity …` rows of `python3 scripts/compound-v-memory.py --selftest`.
Step 2: in skills/compound-v/memory.md replace the ONE physical line that starts with `| `recall-check --files <glob>… ` with exactly this one line (the file line count must stay 202):
| `recall-check --files <glob>… [--k N] [--json]` | **deterministic** recurring-failure → `tighten`/`none`/`unavailable` verdict. Files match lane globs with the same matcher as the scope gate: `*` matches within one path segment (never `/`); `**` matches across segments; `dir/**` also matches `dir` itself; `?` matches one non-`/` character; `[` and `]` are literal (no character classes — `app/[locale]/**` is a real directory); matching is anchored to the full repo-relative path (see [`execution-manifest.md`](execution-manifest.md)). recall-check only: a bare path with no wildcard means "this path or anything under it" (the enforced gate has no such reading). Proof: the `parity …` rows of `python3 scripts/compound-v-memory.py --selftest`. |
Step 3: verify `grep -c "matches within one path segment"` prints 1 for each file, `wc -l skills/compound-v/memory.md` prints 202, `git diff --stat 16786b7 -- <the two files>` shows memory.md 1 insertion 1 deletion. Do not paraphrase, reflow, shorten or move either block; if anything prevents this, STOP and say exactly what in your summary. Only the two files may change. Commit in your worktree.

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

- grep -c 'matches within one path segment' prints 1 for each file; wc -l memory.md prints 202; git diff --stat 16786b7 -- the two files shows memory.md 1 insertion 1 deletion; the paragraph starts a line of its own before "### Tier vocabulary".

Turn cap: 80 (default for tier deep; default light 30 / standard 50 / deep 80). Plan to finish inside it.

## What you must NOT report

Do not report `blocked`, `files_changed` or `violations`. Those are
enforcement fields, they are derived from git by the caller, and a
constrained party filling in its own enforcement fields is the
fabricated-evidence pattern.
