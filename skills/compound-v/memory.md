# V-memory — recall over docs/superpowers (PRD §V-memory / v2.0)

A local-first **recall layer** over `docs/superpowers/**` prose. It **extends** Compound V's
two-half memory — the machine-appended `task-outcomes.jsonl` → scorecard (`worker-performance.jsonl`)
and the human-curated [`routing-lessons.md`](../../docs/superpowers/memory/routing-lessons.md) —
and **never rewrites either**. Where the scorecard is the *structured* routing signal, V-memory
is the *prose* recall surface: "have we seen this before?" across specs, plans, reviews,
archaeology, and lessons. Engine: [`scripts/compound-v-memory.py`](../../scripts/compound-v-memory.py).

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
| `search "<q>" [--top N] [--intent planning\|review] [--json] [--no-embed]` | recall: FTS5 (∪ dense) → rank-union → agent-ready context pack |
| `recall-check --files <glob>… [--k N] [--json]` | **deterministic** recurring-failure → `tighten`/`none` verdict |
| `bootstrap [--model M]` | the ONLY network step: create the out-of-repo embedding venv |
| `doctor` | index / venv / model / staleness health |
| `--selftest` | stdlib-only self-tests (no network, no model) |

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

- **Trigger:** for a feature whose diff touches file pattern `F`, `recall-check --files F`
  counts prior `job_result` records (the authoritative git-derived `results/<id>.json`, per
  [`schemas/job_result.schema.json`](../../schemas/job_result.schema.json)) with
  `status ∈ {blocked, error, timeout}` (or a scope `violation`) on the same `F`. `N ≥ k`
  (default `k=2`, the "two is a pattern" rule) ⇒ verdict `tighten`.
- **Action (tighten only):** force worktree isolation, OR add one extra review pass, OR fold
  `F` into the serial Task 0 `shared_foundation`. It **never** reroutes to a lower-trust backend
  and **never** loosens. Verifiable: a `--selftest` case asserts fixtures(repeated failure) →
  tightening.

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
  prose (specs/plans/reviews/archaeology), the `execution/*/results/*.json` `job_result` records
  that feed `recall-check`, the human-curated `routing-lessons.md`, and `task-outcomes.jsonl`. A
  dev commits + pushes; a teammate pulls and now **has the same knowledge**.
- The **index is per-developer, local, and out-of-repo** (`~/.cache/compound-v/memory/<repo-id>/`)
  — deliberately **never committed**. Committing a binary FTS5/vector index would mean merge
  conflicts, model/OS mismatches, and stale blobs; instead each dev's cache rebuilds from the
  pulled files. After a pull, the index refreshes on the next SessionStart (the silent hook), on
  the next write under `docs/superpowers/`, or via an explicit `/v:memory-refresh`.
- **Freshness signal:** because refresh is eventually-consistent, `search` checks (cheaply, one
  `git ls-files`) whether the index is behind the working tree and prints a one-line
  *"index is N new / M removed docs behind — run /v:memory-refresh"* hint to stderr. So a dev who
  just pulled a teammate's docs is told their local recall hasn't caught up yet.
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
