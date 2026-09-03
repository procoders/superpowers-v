# Task A — search refreshes the FTS5 lane inline (scripts/compound-v-memory.py + selftest)

Compound V run `2026-09-03-v3.4.5-recall-freshness`, job `engine`.

Implement Task A of docs/superpowers/plans/2026-09-03-v3.4.5-recall-freshness.md exactly; the spec is docs/superpowers/specs/2026-09-03-v3.4.5-recall-freshness-design.md. Read the pre-flight audits named in this manifest's audits block first (their §7 MUSTs bind). Tests first: add the selftest case, watch it fail, then implement. Never call the embedder from search. Touch only scripts/compound-v-memory.py. Run python with -B; register your lane with a literal --cwd. You are unattended: decide and return. The archaeology's §7 lists ten MUSTs — every one is in your acceptance; the ordering hazard (embedding branch re-hashing after refresh_fts5) is the one that silently breaks dense forever, so keep the pre-refresh `changed` list.

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

- refresh_fts5(conn, root) extracted from cmd_refresh (FTS5-only, no embedder) and used by both; index_staleness returns (new, changed, removed) and doctor reuses it; cmd_search: missing db ⇒ create + refresh; stale and not --no-refresh ⇒ lock, refresh_fts5, one stderr line `V-memory: refreshed N stale doc(s) before recall (FTS5 lane)`; lock held ⇒ today's warning, stale search; `--no-refresh` flag; selftest case per the plan (added-later doc found without --no-refresh, not found with it, no refresh line on a second search); `/usr/bin/python3 -B scripts/compound-v-memory.py --selftest` green; stdlib only, Python 3.9 floor. Pre-flight 1A MUSTs: staleness computed BEFORE the search; inline refresh never applies QUICK_MAX_CHANGED and never consults config_wants_embeddings(); cmd_refresh's embedding branch uses its pre-refresh `changed` list (or the `embedding IS NULL` union), never a post-refresh_fts5 hash diff; refresh_fts5 stamps `chunker_version`; lock held ⇒ silent stale search (no 'already running' line); missing db + --no-refresh ⇒ today's exit 1 + message; index_staleness 3-tuple moved in cmd_search, selftest and doctor (doctor's duplicate removed); stderr via sys.stderr.write.

Turn cap: 50 (default for tier standard; default light 30 / standard 50 / deep 80). Plan to finish inside it.

## What you must NOT report

Do not report `blocked`, `files_changed` or `violations`. Those are
enforcement fields, they are derived from git by the caller, and a
constrained party filling in its own enforcement fields is the
fabricated-evidence pattern.
