# Epic brief — one glob matcher for recall and the scope gate (stage 7: death & resurrection)

Two small, real features on one branch, in order. The point of the stage is the marathon loop itself: the
first feature's run is killed mid-dispatch on purpose, and the epic must come back through `/v:epic <epic-id>`
from the persisted state alone.

- **F1 `one-matcher`** — `scripts/compound-v-memory.py recall-check` matches changed files against lane globs
  with the scope gate's matcher (`compound-v-scope-check.py` `matches`: `*` never crosses `/`, `**` does,
  `dir/**` includes `dir`, `[`/`]` literal) instead of `fnmatch`. A parity selftest runs one fixture table
  through both scripts and asserts identical verdicts.
- **F2 `matcher-docs`** (depends on F1) — `skills/compound-v/memory.md` and `skills/compound-v/execution-manifest.md`
  state the one glob contract once, in the same words, and point at the parity selftest as the proof.

Epic acceptance criteria (the final cross-feature integration review):
1. `python3 scripts/compound-v-memory.py --selftest` and `python3 scripts/compound-v-scope-check.py --selftest`
   both pass; the parity table has at least eight rows and includes `app/[locale]/**` and a `src/*.py` vs
   `src/a/b.py` case.
2. Every per-feature run reached MERGED through the pipeline; F1's run was interrupted and resumed with
   `/v:resume <run-id>` from `epic-state.json` + `state.json` — no manual re-dispatch.
3. `--stats` reports both features `done` and `final_review.status == "passed"`; the marathon printed
   "epic terminal — stop the loop".

Stance: marathon (this invocation only; `.claude/compound-v.json` does not exist in this repository, so the
stance is bound by `--init --stance marathon`). Breaker caps: defaults (max_total_attempts 6, 10 h,
3 no-progress cycles). `/loop` and `/goal` are offered per §0c/§0d and armed only on an explicit yes.
