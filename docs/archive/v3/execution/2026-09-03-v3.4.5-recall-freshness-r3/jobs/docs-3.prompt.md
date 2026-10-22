# Task B'' — the two doc gaps review-1 blocked on (phase-0-recon.md, memory.md) — r2's identical patch was refused on a test-suite timeout

Compound V run `2026-09-03-v3.4.5-recall-freshness-r3`, job `docs-3`.

Review pass 1 (docs/superpowers/dogfood/2026-09-03-v3.4.5-recall-freshness-review.md) blocked on two docs: (1) skills/compound-v/phase-0-recon.md:45 still instructs a refresh before a search and quotes a warning the engine no longer emits — pre-flight 1A's 'exactly one prose file' claim missed it; (2) skills/compound-v/memory.md:141 says the staleness check is 'cheaply, one git ls-files' — it is now that plus a full content hash of every tracked doc (0.091 s vs 0.059 s over 275 docs, measured). Fix both exactly; quote the before/after lines in your summary. Touch only these two files. Run python with -B; register your lane with a literal --cwd. You are unattended: decide and return. NOTE: run r2's docs-2 made exactly this change (its sealed patch is at docs/superpowers/execution/2026-09-03-v3.4.5-recall-freshness-r2/receipts/ — read it, you may reproduce it verbatim); it was refused because an unmapped path promoted its test slice to the full suite, which exceeded the checker's 300 s cap under load. This manifest maps phase-0-recon.md, so only lint-frontmatter runs beyond the floor.

## You are unattended

No one reads this session while it runs and no one will answer a question:
a turn that ends by asking for confirmation, approval or a preference does
NOTHING, and the job is then recorded as an absent implementation. Decide
with the spec, the plan and this prompt; when they are silent, choose the
smallest change that meets the acceptance, do it, run the checks, and return.

## Write-allowed (your lane — anything else is a scope violation)

- `skills/compound-v/phase-0-recon.md`
- `skills/compound-v/memory.md`

## Read-allowed (advisory — git cannot enforce reads)

- `**`

## Acceptance (your definition of done)

- skills/compound-v/phase-0-recon.md no longer tells the agent to refresh before a search and no longer quotes the retired `index is N new / M removed docs behind the repo` string — it says a search refreshes the FTS5 lane itself and what the new stderr line looks like; skills/compound-v/memory.md's staleness sentence (review-1 item 2, around line 141) states the real cost: `git ls-files` plus a content hash of every tracked doc (~0.09 s over ~275 docs, measured by the review) and that this is still cheap enough to run before every search; lint-frontmatter green; no other change.

Turn cap: 30 (default for tier light; default light 30 / standard 50 / deep 80). Plan to finish inside it.

## What you must NOT report

Do not report `blocked`, `files_changed` or `violations`. Those are
enforcement fields, they are derived from git by the caller, and a
constrained party filling in its own enforcement fields is the
fabricated-evidence pattern.
