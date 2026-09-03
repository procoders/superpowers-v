# Epic brief — the verification-program index (stage 5: the first epic ever)

Two small, real, docs-and-script features on one branch, in order:

- **F1 `review-index`** — `scripts/compound-v-dogfood-index.sh` generates `docs/superpowers/dogfood/README.md`:
  one table row per `docs/superpowers/dogfood/*review*.md` file (feature, pass number, VERDICT line, date from the
  filename), sorted by date then pass; a footer with the count. Idempotent; bash 3.2 + git only; a test in
  `tests/test-dogfood-index.sh` over a fixture directory.
- **F2 `readme-section`** (depends on F1) — `README.md` gains a short "Verification program" section that links
  the generated index and states, from the index itself, how many review files exist and how many are APPROVED
  (numbers read from the generated file, never typed).

Epic acceptance criteria (the final cross-feature integration review):
1. `bash scripts/compound-v-dogfood-index.sh` regenerates `docs/superpowers/dogfood/README.md` byte-identically
   on a second run; the README section's counts equal the index footer's counts.
2. Every per-feature run reached MERGED through the pipeline with no manual step between `/v:epic`'s own commands.
3. `epic-state.json` records both features `done` with their run-ids; `--summary` says "epic complete".

Autonomy budget for this invocation: MAX_FEATURES = 2 (the maintainer asked for the whole epic in one pass);
stance: checkpoint (no marathon config exists in this repository).
