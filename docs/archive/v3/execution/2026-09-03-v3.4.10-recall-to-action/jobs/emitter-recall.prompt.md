# Task A — recall-check at emit time; evidence in the prompt; tier rung under auto_tighten; --no-recall

Compound V run `2026-09-03-v3.4.10-recall-to-action`, job `emitter-recall`.

BUDGET: scripts/compound-v-emit-workflow.py is 6,000+ lines; six implementers ran out of turns reading it. At most 20 tool calls of reading in total: `grep -n` for each named symbol, then `sed -n` only the ranges you need; never Read the whole file; then edit; then run `--selftest` ONCE. Implement Task A of docs/superpowers/plans/2026-09-03-v3.4.10-recall-to-action.md (spec docs/superpowers/specs/2026-09-03-v3.4.10-recall-to-action-design.md). Pre-flight 1A corrected the plan (read the spec's 'Decisions forced by pre-flight' section first): the work goes in `job_entry` BEFORE `resolve_job_model(` (grep both); the verdict reaches state.json through `register-lane --recall-check-json` (grep `def cmd_register_lane` and the emitted register-lane command string); a NEW `TIER_RAISE` dict; `subprocess.run(timeout=30)`; every `type: review` job gets the clause; `def cmd_emit`'s JSON summary lists recall_check + recall_check_ms. Touch only scripts/compound-v-emit-workflow.py. Read the pre-flight audits named in this manifest's audits block first (their §7 MUSTs bind). Tests first. Python 3.9 syntax. Run python with -B; register your lane with a literal --cwd. You are unattended: decide and return; if you approach your turn budget, commit what is complete and return a summary that says what is not.

## You are unattended

No one reads this session while it runs and no one will answer a question:
a turn that ends by asking for confirmation, approval or a preference does
NOTHING, and the job is then recorded as an absent implementation. Decide
with the spec, the plan and this prompt; when they are silent, choose the
smallest change that meets the acceptance, do it, run the checks, and return.

## Write-allowed (your lane — anything else is a scope violation)

- `scripts/compound-v-emit-workflow.py`

## Read-allowed (advisory — git cannot enforce reads)

- `**`

## Acceptance (your definition of done)

- `emit` on a manifest whose implement lane has ≥ k prior failure records under the results root records `recall_check` {verdict, match_count, evidence[:3], recall_check_ms} in the emitted job entry AND (via register-lane's new --recall-check-json) in state.json, and the implementer prompt carries the `## Prior failures on your lane` section with the evidence and the reading-budget instruction; with fewer records neither appears — proven by the emitter selftest with a temp results root. With `memory.auto_tighten: true` the job's tier is raised one rung via TIER_RAISE (light→standard, standard→deep; deep/frontier unchanged) inside job_entry BEFORE resolve_job_model, an explicit `model:` wins unchanged (asserted), and every `type: review` job's acceptance gains the re-check clause; with the default false, the prompt section alone. `emit --no-recall`, a missing engine, an engine error, or a 30 s TimeoutExpired ⇒ emit proceeds and records `recall_check: {verdict: unavailable, note}`; never a refusal; the emit JSON summary lists recall_check (with recall_check_ms) per job. Python 3.9: no match/case, no isinstance(x, A | B); stdlib only; the engine is a subprocess.

Turn cap: 80 (default for tier deep; default light 30 / standard 50 / deep 80). Plan to finish inside it.

## What you must NOT report

Do not report `blocked`, `files_changed` or `violations`. Those are
enforcement fields, they are derived from git by the caller, and a
constrained party filling in its own enforcement fields is the
fabricated-evidence pattern.
