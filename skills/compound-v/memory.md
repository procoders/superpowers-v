# V-memory — recall over docs/superpowers (PRD §V-memory / v2.0)

A local-first **recall layer** over `docs/superpowers/**` prose. It **extends** Compound V's
two-half memory — the scorecard (`worker-performance.jsonl`, regenerated **from run
results**: `compound-v-scorecard.py --update --from-runs docs/superpowers/execution`
joins manifest jobs against `results/*.json`, unioned with the legacy `task-outcomes.jsonl`)
and the human-curated [`routing-lessons.md`](../../docs/superpowers/memory/routing-lessons.md) —
and **never rewrites either**. Where the scorecard is the *structured* routing signal, V-memory
is the *prose* recall surface: "have we seen this before?" across specs, plans, reviews,
archaeology, and lessons. Engine: [`scripts/compound-v-memory.py`](../../scripts/compound-v-memory.py).

For a **live** view of a run in progress, use the native `/workflows` and `/tasks` surfaces —
V-memory and the scorecard are both post-hoc, file-derived signals, never a live feed.

It is **the same discipline as the rest of the toolchain**: pure-stdlib core, offline,
`--selftest`'d, no daemon, no fabricated metrics. Commands: [`/v:remember`](../../commands/v-remember.md),
[`/v:memory-refresh`](../../commands/v-memory-refresh.md).

---

## Two lanes

- **Core — FTS5 (default, always on, pure stdlib).** SQLite FTS5 BM25 over **git-tracked**
  prose. Zero new dependencies, instant, offline. This is the dependable substrate everything
  else keys off.
- **Dense — embeddings (opt-in, out-of-repo, scale-gated).** `multilingual-e5-small` (384-dim,
  no remote code; the `Xenova/multilingual-e5-small` ONNX export) via an isolated `onnxruntime`
  venv living **outside the repo** at `~/.cache/compound-v/memory/<repo-id>/`. Used in a
  lightweight rank-union with FTS5 **only** once the corpus is large enough to matter; absent
  or broken ⇒ silently FTS5-only. `gte-multilingual-base` is an optional quality tier (it needs
  `trust_remote_code=True` — a documented caveat, opt-in only).

The semantic lane is bootstrapped **only** by an explicit command (the one and only network
step) — never from a hook:

```
python3 scripts/compound-v-memory.py bootstrap                  # out-of-repo venv + model, validated by a probe
python3 scripts/compound-v-memory.py refresh --with-embeddings  # populate vectors
```

[`/v:init`](../../commands/v-init.md) asks once whether to enable this lane and records the
choice as `memory.embeddings` in `.claude/compound-v.json`. When that flag is `true`, the
engine adds vectors on **every** refresh (including the background hook) — but still only
after the explicit `bootstrap` above; the flag never triggers an install.

---

## CLI

| Command | Effect |
|---|---|
| `refresh [--rebuild] [--quick] [--with-embeddings] [--repo P]` | incremental index by file hash (FTS5 always; dense only when bootstrapped) |
| `search "<q>" [--top N] [--intent planning\|review] [--json] [--no-embed] [--no-refresh]` | recall: FTS5 (∪ dense) → rank-union → agent-ready context pack. The FTS5 lane is fresh **by construction** at every search — a stale or missing index is refreshed inline before the query runs (`--no-refresh` opts out and searches whatever is already indexed); the dense lane is unaffected and refreshes only on an explicit `/v:memory-refresh --with-embeddings`. |
| `recall-check --files <glob>… [--k N] [--json]` | **deterministic** recurring-failure → `tighten`/`none` verdict |
| `bootstrap [--model M]` | the ONLY network step: create the out-of-repo embedding venv |
| `doctor` | index / venv / model / staleness health |
| `--selftest` | stdlib-only self-tests (no network, no model) |

A search-triggered refresh is FTS5-only: it never applies the `--quick` cap and never consults
the embeddings config, so it always catches up fully regardless of how many files are stale.
Documented side effect — with embeddings on and bootstrapped, a search-triggered refresh
re-chunks a changed file **without** vectors; that file's dense lane degrades to FTS5-only
until the next `/v:memory-refresh --with-embeddings` re-embeds it. It never breaks — the file
stays fully searchable via FTS5 in the meantime.

---

## Recall stays subordinate (the precedence rule)

Recall is **evidence, not authority**, and it is wired into **planning and review only** —
**routing is deliberately untouched**. Routing has, since v1.1, a hardened deterministic order
(human `routing-lessons.md` → stance table → conservative scorecard → fallback → invariants).
A fuzzy BM25/cosine match has no conservative-only contract, so it is **never** a routing input.
When recall surfaces a chunk during planning/review, treat it as a pointer to read, not a ruling;
`routing-lessons.md` + the scorecard remain the authority for backend/model/isolation.

## The recall→action bridge (deterministic, conservative-only)

The one place memory **acts automatically** is the analogue of the scorecard's
`unhealthy → escalate`, for the prose/structured half — and it is gated by a **structured**
match, **not** embedding similarity:

- **Trigger:** at **emit time**, for every `type: implement` job, the emitter runs
  `recall-check --files <the job's write_allowed> --json` as a subprocess (never an import) and
  counts prior `job_result` records (the authoritative git-derived `results/<id>.json`, per
  [`schemas/job_result.schema.json`](../../schemas/job_result.schema.json)) with
  `status ∈ {blocked, error, timeout}` (or a scope `violation`) on the same lane. `N ≥ k`
  (default `k=2`, the "two is a pattern" rule) ⇒ verdict `tighten`. `recall-check`'s glob
  matching against `write_allowed` (see [`execution-manifest.md`](execution-manifest.md) §
  Job fields) is the same matcher the scope gate enforces with — imported from
  `compound-v-scope-check.py`, not reimplemented — and `--selftest` carries a glob-parity
  suite that fails if the two ever diverge.
  The six rules, identical on both sides: (1) `*` matches inside one path segment and never crosses `/`;
  (2) `**` crosses `/`; (3) `dir/**` also matches `dir` itself; (4) a leading or mid `**/` matches zero or
  more segments, so `**/x.py` matches `x.py`; (5) `?` matches exactly one non-`/` character; (6) `[` and `]`
  are literal, never character classes, so `app/[locale]/**` matches that real directory instead of one
  character out of `l o c a e`. Every pattern is fully anchored — a match must consume the whole path. One
  deliberate asymmetry, and the only one: `recall-check` additionally reads a wildcard-free bare path as
  `<path>/**`, sugar the gate itself does not accept.
- **The two real actions (tighten only):**
  1. **Always, when `memory.auto_recall` is on (default true; the /v:init "Manual only" stance sets it false, and `emit --no-recall` forces it off for one emit):** the implementer prompt gains a
     `## Prior failures on your lane` section — the count, the last three evidence lines
     (run · status · file), and a reading-budget instruction that follows from them (`grep -n`
     then `sed -n` targeted ranges, ≤ 20 reading calls, never read a large file top to bottom,
     commit what is complete if the turn budget nears).
  2. **Applied only when `memory.auto_tighten` is true (default false):** the job's tier is
     raised one rung (`light → standard`, `standard → deep`; `deep`/`frontier` unchanged, via a
     new ascending `TIER_RAISE` table — never an index into the descending `TIERS` table), and
     every `type: review` job's acceptance gains a re-check clause: re-run `recall-check` over
     the merged diff and state whether the prior-failure pattern recurred. An explicit `model:`
     pin is never touched either way — the same rule as `escalate_claude_model`. With
     `auto_tighten` false, action 1 (the prompt section) still applies; only action 2 is gated.

  It **never** reroutes to a lower-trust backend, **never** loosens a test slice, and **never**
  picks a different backend. Verifiable: a `--selftest` case asserts fixtures(repeated failure)
  → tightening.
- **`--no-recall`:** `emit --no-recall` skips the lookup entirely. A missing
  `compound-v-memory.py`, an engine error, or a 30 s subprocess timeout is treated the same way
  — emit proceeds and records `recall_check: {verdict: unavailable, note}`; it is never a reason
  to refuse to emit. The verdict (and `recall_check_ms`, see below) is also printed in `emit`'s
  JSON summary.
- **Where the verdict is recorded.** The emitter has no `state.json` write path of its own, so
  the verdict rides in the emitted job entry (`recall_check: {verdict, match_count,
  evidence[:3], recall_check_ms}`) and reaches `state.json` through `register-lane` — the
  runtime hook that already writes a job's state entry before its work starts — via a new
  `--recall-check-json` argument on the emitted `register-lane` command — for a `tighten` verdict. A `none` or `unavailable` verdict lives in the emitted job entry and the emit summary only (Codex receipt, finding 6: one contract, stated).
- **Cost is measured per job, never assumed.** Each `recall-check` walk is timed at emit and
  recorded as `recall_check_ms` in the job entry and the emit summary; nothing about its cost is
  estimated or hardcoded.
- **A hand-probing note:** an unquoted shell variable does not word-split the way you expect in
  zsh — `recall-check --files $PATTERN` with an unquoted, space-containing `$PATTERN` lands as
  one argument instead of several, which reads as `none` everywhere even when the pattern should
  have matched. Quote deliberately, or pass the pattern pre-split, when probing by hand.

This is why recall earns a place in autonomy: the bridge is *measurable and testable*, unlike a
free-text "advisory" surface.

**Autonomy is project-configurable** (set at [`/v:init`](../../commands/v-init.md) Step 3b,
read from `.claude/compound-v.json`): `memory.auto_recall` (default `true`) gates whether the
pipeline auto-surfaces recall in planning + at the review gate; `memory.auto_tighten` (default
`false`) gates whether the `recall-check` verdict is **applied** automatically or merely
surfaced as advisory. Both `false` ⇒ memory is a manual `/v:remember` lookup only. The
conservative-only contract holds at every level — auto-tighten can only *tighten*.

---

## Invariants (enforced in the engine + self-tests)

1. **Cache outside the repo** — no `.gitignore` edit. Ignoring a path under `docs/superpowers/`
   would blind the scope gate's `git ls-files --others --exclude-standard`; keeping the cache in
   `~/.cache/compound-v/` sidesteps that entirely and means a refresh can never dirty a worker's
   scope gate.
2. **Index only git-tracked files** (`git ls-files` under `docs/superpowers`) — inherits
   `.gitignore` + the scope discipline; no parallel secret denylist. Plus a light redaction pass
   (`sk-`/`ghp_`/`AKIA`/`-----BEGIN … KEY-----`) before a chunk is stored.
3. **Crash-safe FTS5** — `fts5_escape()` + `try/except` on every `MATCH`; a raw query like a
   filename (`index.ts`) would otherwise throw `OperationalError` on stock sqlite.
4. **Concurrency-safe refresh** — `fcntl.flock(LOCK_EX|LOCK_NB)`, the loser is an instant no-op;
   per-file reindex in one `BEGIN IMMEDIATE … COMMIT` (FTS stays in sync via triggers).
5. **Hooks never install/download** — the refresh hook self-backgrounds an FTS5-only `refresh
   --quick` and returns in ~ms; bootstrap is always explicit.
6. **Embeddings identity-checked + degrade-safe** — identity = {model, dim, lib version,
   chunker, fingerprint}; mismatch ⇒ rebuild. Bootstrap is atomic (tmp → validate-by-probe →
   rename); a broken-but-present venv degrades exactly like an absent one.

---

## Multi-developer workflow (knowledge accumulates via git, not via a shared index)

The whole team's knowledge accumulates **through the committed corpus**, because the source of
truth is the git-tracked files, and the index is only a local, disposable cache derived from them:

- Every knowledge source V-memory draws on is a **committed git artifact** — `docs/superpowers/**`
  prose (specs/plans/reviews/archaeology/recon), the `execution/*/results/*.json` `job_result` records
  that feed `recall-check`, the human-curated `routing-lessons.md`, and `task-outcomes.jsonl`. A
  dev commits + pushes; a teammate pulls and now **has the same knowledge**.
- The **index is per-developer, local, and out-of-repo** (`~/.cache/compound-v/memory/<repo-id>/`)
  — deliberately **never committed**. Committing a binary FTS5/vector index would mean merge
  conflicts, model/OS mismatches, and stale blobs; instead each dev's cache rebuilds from the
  pulled files. After a pull, the index refreshes on the next SessionStart (the silent hook), on
  the next write under `docs/superpowers/`, or via an explicit `/v:memory-refresh`.
- **Freshness by construction:** `search` checks whether the FTS5 index is behind the working
  tree by running `git ls-files` plus a content hash of every tracked doc (~0.09s over ~275
  docs, measured) — still cheap enough to pay before every search — and, unless `--no-refresh`
  is passed, refreshes it inline before the query runs — printing one stderr line, `V-memory: refreshed N stale doc(s) before
  recall (FTS5 lane)`. So a dev who just pulled a teammate's docs gets current recall on the
  very next search, with no separate `/v:memory-refresh` step. `--no-refresh` searches whatever
  is already indexed and prints the staleness warning instead. A repo with no index yet builds
  one on the first search.
- **Trade-off (honest):** each dev pays the index-build (and, if enabled, the embedding) cost
  locally rather than sharing one index. That is the price of zero merge conflicts and
  reproducibility; a CI-generated shared index artifact is the escape hatch if the corpus ever
  grows enough to make per-dev embedding cost matter.

## Honesty boundary (state it to the user)

- **Lexical by default, semantic when it earns it.** FTS5 ships on; embeddings are opt-in and
  only change ranking past a corpus threshold. On a handful of docs, a full read or FTS5 already
  wins — V-memory is built for the consumer-scale corpora a long autonomous run accumulates, not
  for three files.
- **Recall is a better memory, not a decision-maker.** It surfaces evidence into planning/review
  and runs one deterministic conservative-only tighten; it does not reroute, loosen, or override
  the human-curated `routing-lessons.md` or the scorecard.
- **No daemon, no server, no fabricated metrics.** The index is a disposable, out-of-repo cache;
  delete it and `refresh` rebuilds it.

## Cross-references

- Engine + self-tests: [`scripts/compound-v-memory.py`](../../scripts/compound-v-memory.py)
- Commands: [`/v:remember`](../../commands/v-remember.md), [`/v:memory-refresh`](../../commands/v-memory-refresh.md)
- The two-half memory it extends: [`routing-lessons.md`](../../docs/superpowers/memory/routing-lessons.md), [`compound-v-scorecard.py`](../../scripts/compound-v-scorecard.py)
- Routing authority (untouched by recall): [`routing-policy.md`](routing-policy.md)
- The main skill: [`SKILL.md`](SKILL.md)
