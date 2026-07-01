# Job: task-0-resolver (Compound V — serial spine, isolation: direct)

You are an **implementation worker, NOT the planner.** Do not change architecture. Do not write
outside WRITE_ALLOWED. If the task needs a forbidden file, STOP and report BLOCKED.

## SCOPE LOCK
- **WRITE-allowed (the ONLY file you may modify):**
  - `scripts/compound-v-resolve-model.py`
- **READ-allowed:** `scripts/**`, `docs/superpowers/specs/**`, `docs/superpowers/plans/**`,
  `docs/superpowers/archaeology/**`
- You are in the MAIN repo at `/Users/oleg/Dev/superpowers-v` on branch `v2.4.0-stance-aware-models`.
  Commit on THIS branch. Do NOT create a worktree.

## Task — Stance-aware resolver (Task 1 of the plan, the serial spine)

Make tier→model resolution **stance-aware** so the `cost-aware` stance routes Claude `standard`-tier
implementers to Sonnet 5, while `balanced` (default) is unchanged. One value cell changes
(`cost-aware.claude.standard` opus→sonnet); around it the resolver gains a `--stance` axis
(default `balanced` = current behavior).

Implement EXACTLY the 10 steps in the plan's **Task 1** section, which carries the full code verbatim.
The plan is at `docs/superpowers/plans/2026-06-30-v2.4.0-stance-aware-models.md` — read its Task 1
section and the Global Constraints. The pieces, in order:

1. **Step 1** — Append the new stance-aware selftest assertions inside `_selftest()`, immediately
   before the `# Unknown backend / tier / effort raise.` block. Use the exact assertion block from
   the plan (default balanced standard→opus; cost-aware standard→sonnet; cost-aware deep stays opus;
   cost-aware light→sonnet; cost-aware codex unchanged; balanced standard→opus; unknown stance raises;
   legacy flat config under balanced AND cost-aware; per-stance config overrides its stance; per-stance
   leaves other stances on default). Also change the existing no-haiku check to scan ALL stances via
   `json.dumps(DEFAULT_MODELS_BY_STANCE).lower()`.
2. **Step 2** — Run `python3 scripts/compound-v-resolve-model.py --selftest`; confirm it FAILS
   (no `stance` kwarg / `DEFAULT_MODELS_BY_STANCE` undefined). This is the red of TDD.
3. **Step 3** — Replace the `DEFAULT_MODELS` block with the per-stance structure: `_CLAUDE_DEFAULT`,
   `_CLAUDE_COST_AWARE`, `_CODEX`, `_ANTIGRAVITY`, `_CURSOR` (keep the rich antigravity/cursor comments),
   `_stance_map(claude_map)`, `DEFAULT_MODELS_BY_STANCE` keyed by stance, and the
   `DEFAULT_MODELS = DEFAULT_MODELS_BY_STANCE["balanced"]` alias. Use the exact code from the plan.
4. **Step 4** — Add `VALID_STANCES = ("balanced", "conservative", "cost-aware", "claude-only")`
   right after the `EFFORTS` line. RE-DECLARE it (do NOT import / extract a shared module — mirror of
   `compound-v-validate-manifest.py`).
5. **Step 5** — Add the `_config_cell(config_models, stance, backend, tier)` helper immediately above
   `resolve()`. It must handle BOTH the legacy flat shape `{backend: {tier: model}}` AND the per-stance
   shape `{stance: {backend: {tier: model}}}`, discriminated by whether EVERY top-level key is a stance
   name. Use the exact code from the plan.
6. **Step 6** — Update `resolve()`: add the trailing `stance="balanced"` kwarg + validation, and route
   config/default lookups through the stance. Precedence: explicit_model > config_models > the stance's
   built-in default map. Output dict shape UNCHANGED (`backend`/`tier`/`model`/`effort` — stance is NOT
   echoed). Use the exact code from the plan.
7. **Step 7** — Add the `--stance` argparse flag in `main()` after `--effort`
   (`default="balanced", choices=list(VALID_STANCES)`), and pass `stance=args.stance` into the
   `resolve(...)` call.
8. **Step 8** — Run `python3 scripts/compound-v-resolve-model.py --selftest`; confirm `SELFTEST PASSED`
   (all new assertions PLUS every pre-existing one). This is the green of TDD.
9. **Step 9** — Smoke the CLI both ways:
   - `--backend claude --tier standard` → `"model": "opus"`
   - `--backend claude --tier standard --stance cost-aware` → `"model": "sonnet"`
   - `--backend claude --tier deep --stance cost-aware` → `"model": "opus"`
10. **Step 10** — Commit ONLY `scripts/compound-v-resolve-model.py`:
    `git add scripts/compound-v-resolve-model.py`
    `git commit -m "feat(routing): stance-aware model resolution (cost-aware claude standard -> sonnet)"`

## Design constraints (MUST / MUST-NOT — from the plan + archaeology audit)
- **MUST** keep `balanced` the DEFAULT stance — every caller omitting `--stance` keeps `standard → opus`.
  A wrong default silently shifts every run's models. Highest-stakes invariant.
- **MUST** change ONLY `cost-aware.claude.standard` (opus → sonnet). `cost-aware.claude.deep` MUST
  stay `opus` (sensitive/reviewer guard). All `codex`/`antigravity`/`cursor` cells identical across stances.
- **MUST** keep `sonnet` as an alias (Sonnet 5 via Claude Code's native tier alias) — no concrete
  `claude-sonnet-5` pinned.
- **MUST** keep `DEFAULT_MODELS = DEFAULT_MODELS_BY_STANCE["balanced"]` alias so stance-unaware refs work.
- **MUST-NOT** import or extract a shared `VALID_STANCES` module — re-declare it (both scripts are
  standalone stdlib CLIs).
- **MUST-NOT** echo `stance` in the output dict — the dispatcher's `model`/`effort` reads must be untouched.
- **MUST-NOT** introduce `haiku` anywhere; the no-haiku selftest now scans all stances.
- **MUST-NOT** touch any file other than `scripts/compound-v-resolve-model.py`.

## Method
Follow TDD (superpowers:test-driven-development): write the failing selftest → run it red → implement →
run it green → smoke the CLI → self-review the diff → commit. Self-review before reporting DONE.

## Status report format (end your run with exactly one)
- `DONE` — selftest green, CLI smokes pass, committed. Include the commit subject + the three smoke outputs.
- `DONE_WITH_CONCERNS` — done but flag the concern.
- `NEEDS_CONTEXT` — missing context to proceed; say precisely what.
- `BLOCKED` — needs a forbidden file or hit a wall; say which and stop.
