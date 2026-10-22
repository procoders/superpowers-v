# Task A' — lock release in a finally, one hash pass on the inline path, a lock-held selftest (review-1 items 3–5)

Compound V run `2026-09-03-v3.4.5-recall-freshness-r2`, job `engine-2`.

Review pass 1 (docs/superpowers/dogfood/2026-09-03-v3.4.5-recall-freshness-review.md) approved the engine and recorded three non-blocking items: (3) the lock release in cmd_search is not in a finally; (4) the inline path hashes every tracked doc twice (index_staleness, then refresh_fts5); (5) the lock-held branch has no automated guard. Close all three, minimally: finally; reuse the changed list; one selftest that holds the lock. Do not change behaviour otherwise; do not touch the embedding branch. Touch only scripts/compound-v-memory.py. Run python with -B; register your lane with a literal --cwd. You are unattended: decide and return.

## You are unattended

No one reads this session while it runs and no one will answer a question:
a turn that ends by asking for confirmation, approval or a preference does
NOTHING, and the job is then recorded as an absent implementation. Decide
with the spec, the plan and this prompt; when they are silent, choose the
smallest change that meets the acceptance, do it, run the checks, and return.

## Write-allowed (your lane — anything else is a scope violation)

- `scripts/compound-v-memory.py`

## Read-allowed (advisory — git cannot enforce reads)

- `**`

## Acceptance (your definition of done)

- cmd_search releases the refresh lock in a `finally` (an exception inside refresh_fts5 can no longer leave the lock held); the inline path hashes tracked docs ONCE (the staleness computation's changed list is handed to refresh_fts5 or the helper accepts a precomputed list — no second full hash pass; show the call graph in your summary); a selftest case holds the lock (acquire_lock on the same paths['lock']) and calls cmd_search on a stale index: the staleness warning is printed, NO refresh line, results come from the stale index, and the lock is still held afterwards by the test; `/usr/bin/python3 -B scripts/compound-v-memory.py --selftest` green; nothing else in the engine changes.

Turn cap: 50 (default for tier standard; default light 30 / standard 50 / deep 80). Plan to finish inside it.

## What you must NOT report

Do not report `blocked`, `files_changed` or `violations`. Those are
enforcement fields, they are derived from git by the caller, and a
constrained party filling in its own enforcement fields is the
fabricated-evidence pattern.
