---
description: Execute a Compound-V-ready plan, manifest, or run-id via batched parallel multi-backend dispatch. Accepts a bare plan path (auto-materializes the manifest), or a manifest|run-id (dispatches directly). Runs partition-reviewer first; on PASS dispatches Task 0 serially then the parallel batches, enforces the scope gate, reviews, and hands off to finishing-a-development-branch.
---

You are about to execute **Phase 3** of Compound V — batched parallel multi-backend dispatch — on `{{args}}`.

This replaces the default Superpowers `subagent-driven-development` sequential-implementer pattern with parallel batches (4–6 implementers per message) on Opus by default, Sonnet only where the routing policy's justification holds, and Codex for large isolated jobs — each job dispatched through [`backend-launcher`](../skills/backend-launcher/SKILL.md) and gated by the file-scope check on return.

`{{args}}` is accepted in **three backward-compatible forms** — the dispatcher detects which:

| `{{args}}` is… | Action |
|---|---|
| a **plan path** (`docs/superpowers/plans/…md`) | **materialize the manifest first** (Phase 2 → `manifest.yaml` + `state.json` in a new run dir), then dispatch. *This is the 0.1.x contract the `plan-saved-nudge` hook and current users rely on — it still works.* |
| a **manifest path** (`…/execution/<run-id>/manifest.yaml`) | dispatch it directly (already materialized). |
| a **run-id** (a dir name under `docs/superpowers/execution/`) | resolve to that run's `manifest.yaml` and dispatch directly. |

## Steps

1. **Resolve `{{args}}`.**
   - If `{{args}}` is **empty**, list plans in `docs/superpowers/plans/` and runs in `docs/superpowers/execution/`, and ask which to dispatch.
   - If `{{args}}` is a **run-id** or a **manifest path**, load that run's `manifest.yaml`. Skip to step 3 (already materialized).
   - If `{{args}}` is a **plan path**, verify it exists, then **materialize** per [`/v:orchestrate`](v-orchestrate.md): apply [`routing-policy.md`](../skills/compound-v/routing-policy.md), write `manifest.yaml` + initial `state.json` into `docs/superpowers/execution/<run-id>/` (schema: [`execution-manifest.md`](../skills/compound-v/execution-manifest.md); run-dir + state shape: [`state-machine.md`](../skills/compound-v/state-machine.md)), then continue.

2. **Validate the materialized manifest** (only for the plan-path branch). **Pick the validator mode by manifest kind (CR5-1):** if `manifest.yaml` carries a `fast_path` block, validate it in **pre-dispatch** mode; a legacy (plan-based) manifest carries no such block and is validated **mode-lessly**, as before — a mode-less `fast_path` manifest is fail-closed rejected:
   ```
   # legacy manifest (no fast_path block):
   python3 scripts/compound-v-validate-manifest.py docs/superpowers/execution/<run-id>/manifest.yaml
   # fast_path manifest (v2.9 pre-eval-backed):
   python3 scripts/compound-v-validate-manifest.py docs/superpowers/execution/<run-id>/manifest.yaml \
     --mode pre-dispatch --repo-root <repo>
   ```
   Non-zero exit ⇒ fix the manifest and re-run; do not dispatch a manifest the validator rejects. (A plan-path materialization always yields a legacy manifest; the `fast_path` branch matters when `{{args}}` is a manifest/run-id that resolves to a pre-eval-backed run — and the partition reviewer in step 3 re-runs the validator with the same mode rule.)

3. **Run the partition reviewer first** (Iron Rule #4: no execution without a verified Partition Map):
   - Dispatch [`compound-v:partition-reviewer`](../agents/partition-reviewer.md) with the plan **and** the manifest (it runs `compound-v-validate-manifest.py` as its deterministic backing gate, then verifies disjointness + invariants).
   - If verdict is `FAIL` → **STOP.** Surface the failure to the user. Do not dispatch implementers.
   - If verdict is `PASS` → continue.

4. **Dispatch the parallel dispatcher**:
   - Dispatch [`compound-v:parallel-dispatcher`](../agents/parallel-dispatcher.md) with:
     - the manifest path (and run dir),
     - the partition-review verdict (PASS),
     - the audit paths: `docs/superpowers/{archaeology,expert,library-audit}/<topic>.md`.
   - The dispatcher handles **Task 0 serially**, then the parallel batches (honoring `depends_on` / `run` / `max_parallel`), routing each job to its `backend` via [`backend-launcher`](../skills/backend-launcher/SKILL.md). After **every** job it runs the [scope gate](../skills/compound-v/state-machine.md) (`git diff --name-only` ∪ `ls-files --others` vs `write_allowed`): a BLOCKED job **HALTS the run** and is never merged. It updates `state.json` after every phase, then runs the collector and the three-pass Review Gate (AC-gated).

5. When the dispatcher returns its summary, hand off to `superpowers:finishing-a-development-branch`.

## Safety

- Do NOT dispatch implementers if partition-reviewer returned FAIL.
- Do NOT override the Sonnet eligibility from the routing policy, and reviewers stay `model: opus`.
- Do NOT silently skip the final integration review.
- A scope-gate **BLOCKED** halts the run — the offending worktree is left for inspection and never merged. Recover with [`/v:resume <run-id>`](v-resume.md).
- `backend` / `model` (e.g. `gpt-5.6-sol`) are **execution-layer data** — they live in the manifest, never in frontmatter.
- Do **not** print fabricated cost or token metrics (anti-ruflo).
