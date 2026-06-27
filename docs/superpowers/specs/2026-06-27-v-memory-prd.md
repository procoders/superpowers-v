# V-memory — semantic recall for Compound V (PRD, v2.0)

**Status:** approved for build (2026-06-27). Converged after live feasibility proof, a
4-model retrieval benchmark, a Codex cross-model review, and a 3-lens adversarial review.

## 1. What it is
A **local-first recall layer** over `docs/superpowers/**` prose so Compound V can surface
relevant past decisions / failures / lessons during planning and review, and so a narrow,
deterministic class of recurring failures can **auto-tighten** the next run. It **extends**
the existing two-half memory (PRD §5.8 — `task-outcomes.jsonl`/scorecard + human-curated
`routing-lessons.md`); it never rewrites either.

Two commands: `/v:remember "<q>"` (search) and `/v:memory-refresh` (index). Plus automatic,
non-blocking refresh hooks and an advisory recall step in planning/review.

## 2. Lanes
- **Core lane — FTS5 (default, pure stdlib, always on).** SQLite FTS5 BM25 over git-tracked
  prose. Zero new dependencies, offline, instant. This is the dependable substrate.
- **Dense lane — embeddings (opt-in, out-of-repo, scale-gated).** `multilingual-e5-small`
  (384-dim, no remote code) via an isolated onnxruntime venv. Bootstrapped only by explicit
  command, cached **outside the repo**, and used in union with FTS5 when present. Absent or
  broken ⇒ silently FTS5-only. `gte-multilingual-base` is an optional quality tier
  (`trust_remote_code` caveat, documented).

## 3. Invariants (hard requirements)
1. **Cache outside the repo:** `~/.cache/compound-v/memory/<repo-id>/`. No `.gitignore`
   edit (ignoring under `docs/superpowers/` would blind the scope gate's
   `git ls-files --others --exclude-standard`).
2. **Index only git-tracked files** (`git ls-files -z` under `docs/superpowers/`,
   `*.md`/`*.jsonl`): inherits `.gitignore` + scope discipline; no parallel secret denylist.
   Plus a light redaction pass (`sk-`/`ghp_`/`AKIA`/`-----BEGIN … KEY-----`) before storing.
3. **Crash-safe FTS5:** `fts5_escape(q)` in the search path + `try/except` around every
   `MATCH` (raw `MATCH 'index.ts'` throws on stock sqlite). Self-test proves `index.ts`,
   `a OR`, `"x` return cleanly.
4. **Concurrency-safe refresh:** `fcntl.flock(LOCK_EX|LOCK_NB)`, loser exits 0 (silent
   no-op); per-file reindex in one `BEGIN IMMEDIATE … COMMIT`.
5. **Hooks never install/download:** bootstrap runs only from explicit
   `bootstrap`/`/v:memory-refresh --with-embeddings`. Hook commands self-background and are
   FTS5-only; existing `session-banner.sh` + `plan-saved-nudge.sh` are preserved, not replaced.
6. **Embeddings identity-checked + degrade-safe:** identity tuple =
   `{embed_model, dim, embed_lib_version, chunker_version, embed_fingerprint}`; mismatch ⇒
   rebuild. Atomic bootstrap (tmp → validate-by-probe → rename; failure ⇒ FTS5-only).
   Search-time guard `try/excepts` the actual encode, so broken-but-present ≡ absent.
7. **Recall stays subordinate:** routing is untouched by fuzzy recall (it is deterministic
   since v1.1). `routing-lessons.md` + scorecard remain authority; recall is evidence in
   planning/review only.
8. **No fabricated metrics; `--selftest` flag; stdlib-only core.**

## 4. The recall→action bridge (deterministic, conservative-only)
Mirrors the scorecard's `unhealthy → escalate` for the prose half, gated by a **structured**
match (NOT embedding similarity):
- **Trigger:** for a feature whose diff touches file pattern `F`, count prior **`job_result`
  records** (the authoritative git-derived `results/<id>.json` under execution dirs, per
  [`schemas/job_result.schema.json`](../../../schemas/job_result.schema.json)) with
  `status ∈ {blocked, error, timeout}` (or a scope `violation`) on the same `F`. (Not
  `task-outcomes.jsonl` — that log records `(backend, type, status)` but no file paths, so
  it cannot anchor a per-file match.) If `N ≥ k` (default `k=2`, the scorecard's "two is a
  pattern"):
- **Action (tighten only):** force worktree isolation, OR add one extra review pass, OR
  recommend folding `F` into the serial Task 0. Never reroute to a lower-trust backend,
  never loosen. Verifiable by a `--selftest` (fixtures → tightening).

## 5. CLI (`python3 scripts/compound-v-memory.py <cmd>`)
| Command | Effect |
|---|---|
| `refresh [--rebuild] [--quick] [--with-embeddings] [--repo P]` | incremental index by file hash (FTS5 always; dense only if bootstrapped) |
| `search "<q>" [--top N] [--intent planning\|review] [--json] [--no-embed]` | hybrid (FTS5 ∪ dense) recall → context-pack md / json |
| `recall-check --files <globs> [--k N] [--json]` | the deterministic bridge: structured recurring-failure → tightening verdict |
| `bootstrap [--model M]` | create out-of-repo venv + fetch model (the ONLY network step) |
| `doctor` | report index / venv / model / staleness health |
| `--selftest` | stdlib-only self-tests (no network, no model) |

## 6. Default model (benchmark-backed)
`multilingual-e5-small` — ties the older `paraphrase-multilingual-MiniLM-L12-v2` on ranking
(MRR 0.958) at ~4× the encode speed, no `trust_remote_code`, multilingual (RU↔EN proven).
The `Xenova/multilingual-e5-small` ONNX export is exactly this model.

## 7. Out of scope (deferred until a corpus justifies it)
RRF fusion, graph-lite sibling expansion, diversity quotas, routing auto-recall, a shared
team index, an MCP wrapper. Staged the same way scorecards were gated behind `MIN_SAMPLES`.
