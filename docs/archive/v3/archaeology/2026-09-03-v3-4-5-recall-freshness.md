# Recall Freshness (v3.4.5) — Code Archaeology

Spec: `docs/superpowers/specs/2026-09-03-v3.4.5-recall-freshness-design.md`
A plan already exists at `docs/superpowers/plans/2026-09-03-v3.4.5-recall-freshness.md` — this audit treats it as
one more artifact to check against the code, not as ground truth. Where it is silent or wrong, that is a finding.

## Step 0 — V-memory recall

Three queries against the live index (`scripts/compound-v-memory.py search --intent planning --top 8`):

1. `"recall freshness staleness V-memory"` — top hits: `docs/superpowers/specs/2026-06-30-v-onboard-design.md` §9
   (refresh/staleness is a *docs* concern there, unrelated engine), the PRD's CLI table
   (`docs/superpowers/specs/2026-06-27-v-memory-prd.md`), and `docs/superpowers/archaeology/2026-06-30-v-onboard.md`
   "Risk list" — which already flagged (R7) that `index_staleness()` reports root files "N new" until first
   refresh; cosmetic, changelogged, not otherwise fixed.
2. `"index staleness doctor refresh lock"` and `"refresh lock concurrent selftest cmd_search"` — no hit is a prior
   audit of `cmd_search`/`index_staleness`/`cmd_refresh` internals. **No prior code archaeology exists for this
   file's search/refresh path** — this is the first.

Every query's own stderr line — `V-memory: index is 2 new / 0 removed docs behind the repo` — is itself live
evidence of the exact defect under audit: staleness was detected and reported, and nothing acted on it. It also
demonstrates today's blind spot directly: only *new/removed* was counted, never *changed* — so an edited-but-still-
tracked doc (the most common edit shape in this repo) would never have shown up in that line at all, whether or not
one happens to exist right now.

V-memory itself also reported (separately, on every call): "index is 2 new / 0 removed docs behind the repo" for
its own corpus — i.e. this session's own memory queries are running the exact stale-recall scenario the spec
describes, on the meta-corpus that documents it.

## 1. Matrix

Axes `cmd_search` touches today vs. what the spec asks it to touch:

| db exists? | staleness (new∪changed∪removed) | `--no-refresh` | lock free? | Today's `cmd_search` | Spec-required behavior |
|---|---|---|---|---|---|
| no | n/a | false | n/a | print "index not found", **exit 1** (`:930-932`) | create db, fall into refresh (plan bullet 1) — **new**, unhandled today |
| no | n/a | true | n/a | same exit-1 path (flag doesn't exist yet) | **unspecified** — plan text doesn't branch on `--no-refresh` for the never-indexed case; see §7 |
| yes | 0 | — | — | search as-is, no warning | unchanged |
| yes | new/removed only >0 | false | free | search **stale**, warn on stderr *after* results are computed (`:940-945`) | refresh inline *before* querying, then search fresh, one refresh line |
| yes | **changed-only** >0 | false | free | **invisible today** — `index_staleness` doesn't hash, so a changed-but-still-tracked file never trips the warning at all (`:916-924`) | must trip the same refresh path — requires extending `index_staleness` to hash every tracked file, not just diff path sets |
| yes | >0 | false | **held** (hook or another `refresh` mid-flight) | n/a (no refresh attempted today) | proceed stale, keep the warning, **never wait** — `acquire_lock` is already `LOCK_NB` (`:617`), so this is free, but only if `cmd_search`'s own call site treats `None` the same way `cmd_refresh` does *without* printing `cmd_refresh`'s "already running — skipped" line (that line is refresh-command UX, not search UX) |
| yes | >0 | true | — | n/a | skip refresh, keep warning — i.e. reproduce **today's exact current behavior** as the opt-out |

The one cell nobody has tested yet, because it cannot exist until this ships: **staleness detected, lock free,
refresh actually runs, inline, on the hot path every agent calls at Step 0.** `cmd_search` has zero existing
selftest coverage today (see §3) — the function itself, not just its helpers, is entering this change untested.

## 2. Shared State

### `index_staleness(conn, root)` return shape — `scripts/compound-v-memory.py:916-924`
- Currently returns `(new_count, removed_count)` — a 2-tuple, path-set diff only, **no hashing**.
- One caller today: `cmd_search:940` (`new, removed = index_staleness(conn, root)`).
- One direct non-CLI caller: the selftest at `:1286` (`s_new, s_removed = index_staleness(...)`).
- `cmd_doctor` does **not** call this function — it duplicates the new/changed/removed computation inline at
  `:1110-1117`, hashing every tracked file itself. This is the DRY gap in §6.
- **Gap:** the spec's own decision ("staleness for the decision = new ∪ changed ∪ removed") requires a 3rd element.
  Every caller of the 2-tuple form breaks on a signature change — both call sites above must move in the same
  commit, and `cmd_doctor`'s duplicate logic is the one now redundant with the extended function.

### `indexed_files.content_hash` — written by `_persist_chunks` (`:634-661`), specifically `:651-656`
- This is the row that `index_staleness`'s "changed" extension, `cmd_refresh`'s own `changed` list (`:718`), and
  `cmd_doctor`'s `changed` list (`:1114`) all diff against.
- **Critical ordering hazard for the plan's own extraction.** `_persist_chunks` updates `content_hash` to the
  file's *current* `file_sha()` the moment it reindexes that file — before the caller does anything else. If
  `cmd_refresh` (after the planned split) computes its embedding-branch `to_index` set by **re-deriving** `changed`
  from a fresh `file_sha` vs. `indexed_files.content_hash` diff *after* `refresh_fts5` has already run for those
  same files, that diff will read **zero changed files** — `refresh_fts5` already wrote the new hash. The existing
  code sidesteps this today only because it computes `changed` **once**, before any persisting happens, and reuses
  that one list for both the FTS5 pass and the embedding pass (`:718, :740`). Whoever writes `refresh_fts5(conn,
  root) -> (n_indexed, n_removed)` as a self-contained function that *internally* recomputes `tracked_files` +
  `changed` (as the plan's phrasing implies) must NOT let `cmd_refresh`'s embedding branch also re-derive `changed`
  from the database *after* calling it — the embedding branch's file-selection must either (a) reuse the exact same
  `changed` list computed before `refresh_fts5` runs, passed through, or (b) rely solely on the existing
  "`embedding IS NULL`" union (`:746-750`), never on a post-refresh hash diff. **This is the single highest-risk
  spot in the whole change** — get it wrong and files that changed silently stop being embedded, forever, with
  no error, no warning, and no test that would catch it today (the query cache and identity-drift checks would
  both pass; the corpus would just quietly stop getting new dense vectors for edited docs).

### `chunks.embedding` column — same `_persist_chunks` insert (`:642-650`)
- `_persist_chunks` always `DELETE FROM chunks WHERE path=?` then reinserts. Called with `embedder=None` (which is
  exactly what a "no embedder" `refresh_fts5` must do — `reindex_file(conn, root, rel, embedder)` at `:664-673`
  sets `vecs = None` whenever `embedder is None`), every chunk for that path gets `embedding = NULL`, **including
  chunks that previously had a real vector.**
- Today this can only happen when `want_embed` is False, and `want_embed = args.with_embeddings or
  config_wants_embeddings(root)` (`:731`) — so for a project with `memory.embeddings: true` in
  `.claude/compound-v.json` and a bootstrapped venv, **every existing call to `cmd_refresh` already embeds**,
  regardless of the `--with-embeddings` CLI flag. There is currently **no code path** in which a bootstrapped,
  opted-in project's refresh wipes an existing file's vectors to NULL without immediately replacing them.
- The new inline refresh from `cmd_search` **is** such a path, by the spec's own design ("the dense lane is never
  touched by a search"): `refresh_fts5` must not consult `config_wants_embeddings()` at all. For a project that
  *does* have embeddings on, if `search` is the first thing to notice a changed file is stale (exactly the
  large-batch scenario this spec exists to fix, where the `--quick`-capped hook has been silently refusing —
  see §3), the inline refresh will `DELETE`+reinsert that file's chunks with `embedding = NULL` and stop there. The
  file's prior vectors — even if they were still valid — are gone until the next real embeddings-aware refresh
  (hook or human) reaches that same file. `dense_search` (`:847-863`) only ever queries `WHERE embedding IS NOT
  NULL`, so that file silently drops out of dense recall in the interim; if enough files are hit at once, the
  scale gate (`dense_active`, `:600-607`, `SCALE_GATE_MIN_CHUNKS=80`) could even flip the whole corpus back to
  FTS5-only until vectors are repopulated. Not a bug in the sense of crashing or wrong results — FTS5 recall stays
  correct throughout — but a real, silent, temporary degradation of the dense lane, landing hardest in precisely
  the "many stale files" case the fix targets, and only on installations that have opted into embeddings (not this
  repo — `memory.embeddings` is off here per the spec's own §"What the probe found").

### `args.no_embed` vs. the new `args.no_refresh`
- `--no-embed` (`:1439`, dest `no_embed`) already exists and gates *dense query execution* only (`cmd_search:937`).
  It has nothing to do with the refresh decision. The new `--no-refresh` is an independent axis; both can be set
  together. No collision in naming or `dest`, but the CLI help text and `skills/compound-v/memory.md`'s row
  (currently `[--top N] [--intent …] [--json] [--no-embed]`, `skills/compound-v/memory.md:53`) must show both
  distinctly, or a reader will conflate "don't embed the query" with "don't refresh the index."

## 3. Sibling Code

### `hooks/memory-refresh.sh` — the *existing* background refresh, and the actual root cause
Entry conditions: SessionStart (no `file_path`) or `PostToolUse:Write` under `docs/superpowers/**` (`:22-28`).
Fires `nohup python3 scripts/compound-v-memory.py refresh --quick </dev/null >/dev/null 2>&1 &` (`:36`) — detached,
silent, best-effort.

`--quick` maps straight to `cmd_refresh`'s own gate (`:721-724`):
```
if args.quick and len(changed) > QUICK_MAX_CHANGED:   # QUICK_MAX_CHANGED = 20 (:46)
    print("V-memory: %d changed files exceed --quick limit (%d); run a full refresh." % (...))
    return 0
```
That `print()` goes to stdout, which the hook redirects to `/dev/null`. **This is the exact mechanism that
produced the spec's "110-118 files behind" incident**: once more than 20 files are stale, this hook has been
silently no-op-ing on every SessionStart and every doc write, with its one diagnostic line thrown away by design.
It shares the same `paths["lock"]` flock as everything else (`acquire_lock`/`release_lock`, `:613-629`), so the new
inline refresh in `cmd_search` and this hook's background refresh cannot corrupt each other — whichever gets the
non-blocking `flock` first wins, the other is a no-op — but the hook's own >20-file silent refusal is **untouched
by this spec** (the Decision section only changes `search`), so it will keep refusing large batches exactly as
before. The spec's fix makes `search` self-heal around that refusal; it does not fix the refusal itself. Worth
recording as a fact for the plan/spec author, not a defect to fix in this cycle — the spec's own scope statement
("nothing else changes... `/v:memory-refresh` keeps its job") reads as a deliberate choice to leave the hook as-is.

### `cmd_doctor` (`:1095-1120`) — the only other place that computes "changed"
Entry: no gate, always runs its own inline `new`/`changed`/`removed` computation (`:1110-1117`), never calling
`index_staleness`. Its print format is `"  staleness   : %d new, %d changed, %d removed (run refresh to sync)"`
(`:1116-1117`) — fixed field order (new, changed, removed). If `index_staleness` is extended to return that same
3-tuple and `cmd_doctor` is switched to call it (the plan says exactly this), the field order and semantics must
match exactly or `doctor`'s human-facing output silently changes shape. No test asserts this string today — no
`tests/*.sh` file greps `doctor`'s staleness line (confirmed: no match for `V-memory:|no_embed|no_refresh` in
`tests/`) — so a mismatch would ship silently.

### `cmd_refresh` (`:698-779`) — the function being split
Full read, entry to exit:
1. `acquire_lock` — `None` ⇒ print "refresh already running — skipped." and **return 0** (`:702-704`). This is
   refresh-specific UX; `cmd_search`'s inline call must not reuse this print, only the lock semantics.
2. `--rebuild` drops and recreates all three tables (`:707-712`) — happens *before* `tracked_files` is even
   called, and stays entirely inside `cmd_refresh` (search never rebuilds).
3. `files = tracked_files(root)`, `changed`/`removed` computed by full-content `file_sha` diff (`:714-719`) — the
   only place in the whole file that pays this cost per invocation before this change.
4. `--quick` gate (`:721-724`) — stops here, returns 0, does nothing further. **The plan's `refresh_fts5(conn,
   root)` signature takes no `quick` argument**, so this gate necessarily stays in `cmd_refresh`, outside the
   extracted helper — meaning it structurally cannot leak into `search`'s inline call. Confirmed by the spec's own
   §"What the probe found" (a full refresh of 128 files ran in 0.38s; `--quick` refused the same batch because 128
   > 20) — `search` must run the *unbounded* form, never the 20-file-capped one, or the fix reproduces the exact
   failure it exists to close.
5. Embedder decision (`:729-734`): `want_embed = args.with_embeddings or config_wants_embeddings(root)`, gated by
   `is_bootstrapped(paths)`.
6. `to_index` selection (`:740-750`): `changed`, plus (if embedding) everything on identity drift, or the
   `embedding IS NULL` union otherwise. This is the logic whose ordering hazard is documented in §2 above.
7. One embedder call for the whole batch (`reindex_batch`, `:676-691`) or a per-file loop with `embedder=None`
   (`reindex_file` in a loop, `:758-760`).
8. `removed` purge, one `BEGIN IMMEDIATE`/`COMMIT` pair per path (`:761-765`).
9. `meta_set(conn, "chunker_version", CHUNKER_VERSION)` — **unconditional**, runs regardless of whether an
   embedder was used (`:767`). `embed_model`/`embedder_src` meta only set `if embedder is not None` (`:768-770`).
   **If the extracted `refresh_fts5` does not also stamp `chunker_version`**, any project whose *only* refreshes
   have ever been search-triggered ones (never an explicit `refresh`/hook run first) will have `chunker_version`
   unset in `meta`, so `identity_matches` (`:579-584`) reads False forever for that project, and `dense_active`
   (`:600-607`) never engages even after a later `bootstrap` + `refresh --with-embeddings` — until whichever call
   finally does set it. Low-severity (the hook/human refresh path already sets it unconditionally too, `:767` is
   outside the `if embedder is not None` block), but only if `refresh_fts5` is the *sole* refresher a project has
   ever run when it goes to check.
10. Final `print()` with counts (`:774-776`) — refresh-command UX, not reusable verbatim for `search`'s one-line
    stderr message (different wording per the spec: `"V-memory: refreshed N stale doc(s) before recall (FTS5
    lane)"`), but note it means `cmd_refresh`'s own post-split code will need `files`/`changed` counts a second
    time for its "unchanged: N" arithmetic (`len(files) - n_idx`, `:775`) even though `refresh_fts5` computed the
    same `tracked_files()` list internally — a second `git ls-files` round-trip per **explicit** refresh call (not
    a regression on the hot `search` path, since `search` calls `refresh_fts5` at most once, but worth flagging as
    a real, if minor, double-computation the extraction introduces into `cmd_refresh` itself).

### `cmd_search` (`:927-947`) — the function being changed
Current order: open db (or exit 1 if missing) → `bm25_search` → `dense_search` (maybe) → `rank_union` →
**then** `index_staleness` → warn on stderr → print results. The staleness check runs strictly *after* the search
already executed against the (possibly stale) index — today's warning is diagnostic-only, arriving after the
answer. The spec's fix requires moving the staleness check and any refresh **before** `bm25_search`/`dense_search`
run, not merely adding a refresh call somewhere in the function — a real control-flow reorder, not an addition.

## 4. External APIs

None. This change touches only `sqlite3`, `fcntl`, `argparse`, `subprocess` (to `git` and, unrelated to this
feature, a venv `python`) — all stdlib, matching the file's own stated invariant ("Python 3.9-safe; the CORE
imports stdlib only," `:26`). No new dependency, no third-party API surface change. Context7 lookup is not
applicable to this spec.

## 5. Regression Surface

- **`tests/test-agent-recall.sh`** asserts `search --help` still contains the substring `intent` (`:41`) and that
  `recall-check --help` still contains `files` (`:43`). Neither assertion is sensitive to adding `--no-refresh` —
  confirmed safe, but any future rename of `--intent` or `--files` would break this test; noted since the plan
  touches the same `argparse` block.
- **Five agents' Step 0** (`agents/code-archaeologist.md:26`, `domain-expert.md:26`, `doc-validator.md:26`,
  `spec-reviewer.md:26,36`, `partition-reviewer.md:18`) call `search`/`recall-check` with **no** `--no-refresh` and
  **no** `--no-embed`. Every one of them will now trigger the inline refresh whenever their target repo is stale —
  this is the entire point of the fix, but it means Step 0's latency profile changes for every pre-flight, every
  time, on every repo where the hook hasn't already caught up (which, per §3, is exactly the >20-changed-files
  case that matters most). If new + changed + removed requires hashing every tracked doc (the "changed" extension,
  §2), that hashing cost is now paid inline, synchronously, inside every single agent's Step 0 call — not
  benchmarked anywhere yet (the spec's 0.38s figure is for the *full reindex* of 128 already-known-changed files,
  not for the *staleness check itself* across the whole corpus of a repo that turns out to be fully fresh).
- **`hooks/memory-refresh.sh`**'s silent `--quick`-refusal behavior (§3) is unchanged by this spec and continues to
  produce zero user-visible signal when a batch exceeds 20 files — `search` now compensates for it, but does not
  fix it; a future change to the hook's cap or messaging is out of this cycle's scope, not a gap in this change.
- **Embeddings-enabled projects** (`memory.embeddings: true`, bootstrapped) lose vectors for any file `search`
  reindexes via the FTS5-only path, until the next embeddings-aware refresh reaches the same file (§2). This repo
  is not itself in that configuration, so it will not surface in this repo's own dogfooding of the fix — it will
  surface on any installation that has opted in.
- **`cmd_doctor`**'s human-readable staleness line (`:1116-1117`) changes its data source (from an inline
  duplicate computation to the shared `index_staleness`) if the plan's DRY consolidation (§6) is taken — no test
  guards its exact wording today, so this is a silent-breakage risk only in the sense that nothing would catch a
  format drift, not that one is expected.
- **`commands/v-remember.md:13`** currently tells a human "If it reports the index is missing, run
  `/v:memory-refresh` first, then retry." After this change that advice is actively wrong (a plain `search` on a
  missing index would build it inline, per the plan) — this is exactly what Task B already plans to remove; flagged
  here only to confirm the plan's doc-file list is complete (grepped the whole repo for that exact phrase and
  variants — it appears in exactly one prose file, matching the plan's Task B list).

## 6. DRY Findings

- **`index_staleness` vs. `cmd_doctor`'s inline staleness computation** (`:916-924` vs. `:1110-1117`): two
  independent implementations of "which tracked files are new/changed/removed against `indexed_files`," one
  path-set-only, one full-hash. The plan's own text ("`doctor` already computes 'changed' — reuse, do not
  duplicate") correctly identifies this and proposes consolidating into the extended `index_staleness`. Confirmed
  real duplication; extend `index_staleness`, then switch `cmd_doctor` to call it — do not leave both.
- **`cmd_refresh`'s FTS5-indexing body vs. any future `refresh_fts5` helper**: no duplication exists yet — this is
  a proposed *extraction*, not a found duplicate. Flagged only to note that after extraction, `reindex_file` /
  `reindex_batch` / `_persist_chunks` remain the single, correctly-shared low-level persistence path for both the
  FTS5-only and embedding cases (as they are today) — the extraction must not fork that machinery, only wrap a
  no-embedder call to it.
- No other file in the repository implements its own SQLite indexing, BM25 search, or staleness diffing —
  `scripts/compound-v-memory.py` is the sole owner of this mechanism (confirmed via repo-wide grep for
  `compound-v-memory.py`, `index_staleness`, `cmd_refresh`, `cmd_search` — 24 files reference the script by name,
  all as CLI callers via `python3 scripts/compound-v-memory.py ...`, none reimplementing its logic).

## 7. Design constraints for the spec

1. **Ordering hazard is the top risk.** `refresh_fts5`'s internal `changed`-file computation and `cmd_refresh`'s
   embedding-branch file-selection must not both re-derive "changed" from `indexed_files.content_hash` at
   different points in the same call — `_persist_chunks` (`:651-656`) updates that hash the moment a file is
   FTS5-refreshed, so a second hash-diff taken afterward reads zero changed files. Whatever selects files for
   embedding after the split must reuse the pre-refresh `changed` list or rely solely on the `embedding IS NULL`
   union (`:746-750`), never on a post-`refresh_fts5` hash diff.
2. **`chunker_version` meta must be set by whichever function actually chunks the files**, unconditionally — not
   only in `cmd_refresh`'s tail (`:767`), which today runs after every refresh but would not run at all for a
   refresh triggered purely through `cmd_search`'s inline call.
3. **The inline refresh from `search` must never carry the `--quick` cap** (`QUICK_MAX_CHANGED = 20`, `:46,
   :721-724`) — the spec's own motivating incident (110-118 stale files, `--quick` refused, full refresh took
   0.38s) is exactly the case a capped inline refresh would fail to fix.
4. **The inline refresh from `search` must never consult `config_wants_embeddings()` or pass a real embedder** —
   the spec's decision text says the dense lane is untouched, and `refresh_fts5`'s "no embedder" framing is the
   only way to guarantee that structurally. Document (spec or plan) that this means the FTS5-only persist will
   NULL out any existing vectors on a changed file for embeddings-enabled projects until the next embeddings-aware
   refresh — a real, if temporary, side effect, not a hidden bug once it's written down.
5. **Lock handling in `cmd_search` must be silent-fallback, not `cmd_refresh`'s "already running — skipped"
   print** — a held lock (from the hook or a concurrent `refresh`) must make the new code path behave exactly like
   today's code: search the stale index, print the existing multi-dev warning, never wait (already guaranteed by
   `LOCK_NB`, `:617`, but the *messaging* must not borrow `cmd_refresh`'s own line).
6. **`index_staleness`'s 3-tuple return signature is a breaking change to two known call sites** (`cmd_search:940`,
   the selftest at `:1286`) and should absorb `cmd_doctor`'s duplicate inline computation (`:1110-1117`) rather
   than leave both implementations live.
7. **Missing-db + `--no-refresh` together is unresolved.** The plan's `cmd_search` bullet says "if the db is
   missing → create it ... and fall into the refresh," with no stated branch for `--no-refresh` on a never-indexed
   repo. Today that combination cleanly exits 1 with a helpful message; after the described change, without an
   explicit decision, it most likely silently returns an empty result set with just the staleness warning on
   stderr, exit 0 — a real UX regression from today's actionable error if left implicit. This needs an explicit
   answer, not an assumption, before implementation.
8. **The new stderr message must stay on stderr, via `sys.stderr.write` matching the existing pattern at `:943`,
   never `print()`** — `cmd_search` supports `--json` (`:1438`) and callers depend on stdout carrying only the
   context pack; a `print()`-based refresh line would corrupt JSON output for any `--json` caller.
9. **`cmd_search` has no existing selftest coverage today** (only its helpers — `bm25_search`, `dense_search` —
   are exercised directly in `_selftest`, `:1170-1314`); the new selftest case is the first time `cmd_search`
   itself is called from the test suite, so there is no existing args-shim precedent in this file to copy beyond
   the `class A: ...` pattern used for `cmd_refresh` (`:1182-1183, :1196-1197`) — the new shim needs every attribute
   `cmd_search` reads (`repo, query, top, no_embed, json`, plus the new `no_refresh`), or it raises `AttributeError`
   before it tests anything.
10. **The selftest's existing end-to-end block runs against a non-git temp directory** (`tmp = tempfile.mkdtemp()`,
    `:1171`), so `tracked_files()` exercises its filesystem-walk fallback (`:347-355`), not its `git ls-files`
    branch (`:317-346`). The plan's proposed new-file-appears scenario works fine under that fallback (no `git
    add`/`commit` needed — the file just needs to exist on disk), but it does **not** exercise the git-tracked-only
    invariant that production usage actually depends on. That gap predates this change and is not proposed to be
    fixed by it — noted so the plan doesn't claim broader coverage than it has.

## 8. File Touch Map

| File | Role in this change | Flag |
|---|---|---|
| `scripts/compound-v-memory.py` | The engine: `cmd_search`, `index_staleness`, `cmd_refresh`, new `refresh_fts5` helper, new `--no-refresh` arg, selftest additions. Single file, ~1470 lines, 24 repo files reference it as a CLI dependency (agents, hooks, commands, docs) — no importers, all subprocess/CLI callers, so a signature change to internal functions (`index_staleness`) is invisible to every external caller as long as the CLI surface (`search`'s flags, its stdout/stderr shape) stays compatible. | not a generated/lockfile/schema/migration/index-barrel file — no SHARED RESOURCE flag by the strict definition, but note the fan-in above |
| `skills/compound-v/memory.md` | CLI reference table row for `search` (currently missing `--no-refresh`, `:53`) and the "Two lanes" freshness sentence (Task B). | — |
| `commands/v-remember.md` | Drops the now-wrong "if it reports the index is missing, run /v:memory-refresh first" line (`:13`). | — |
| `CHANGELOG.md` | New `[Unreleased]` entry (finding 98 per the spec's own numbering; changelog currently has findings up to 96 recorded, `CHANGELOG.md:14-15,43,52`). | — |

No migration, schema dump, lockfile, or index/barrel file is touched. No file outside this four-file list needs to
change for this spec (confirmed via repo-wide grep for the one doc phrase being removed, and for `index_staleness`/
`cmd_refresh`/`cmd_search` references — no other caller exists).
