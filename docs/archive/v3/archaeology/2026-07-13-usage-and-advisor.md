# Code archaeology — v2.12 usage & advisor (2026-07-13)

## BLOCKING gap (was absent from the original touch list)

`scripts/compound-v-collect-results.py` `build_result()` (~:283-294) returns a **fixed 10-key dict**
and DROPS `usage`. It parses the worker JSON into `wjson` (:195) but only lifts `session_id` (:254) and
`worktree` (:261). The written `results/<id>.json` (:441) therefore has NO `usage`, and the A2 aggregator
reads zero from every job. **MUST** add `wjson.get("usage")` passthrough (null-safe, optional).
`conformance_errors()` (:319-322) enforces `additionalProperties:false` against schema `properties`, so
`usage` must be added to the schema too, or the collector rejects it. Keep `usage` OUT of `required` (10 entries).

## emit_job_result (A1)

All 5 workers share an identical 10-positional-arg jq builder: codex `:61-88` / `:542`, opencode
`:109-136` / `:727`, plus antigravity `:70`, cursor `:77`, devin `:90`. A1 adds an 11th `usage` field to
codex + opencode only (the two with parseable event streams). **stdout must stay exactly one job_result
JSON** — codex reserves stdout and routes its event stream to `$EVENTS_LOG` (`:307-309`); the usage-extract
call must read the events log into a variable, never write stdout.

Events log at emit time: codex `EVENTS_LOG` = `logs/<id>.jsonl` (dispatcher-passed `--events-log`,
`:136,277`); opencode `EVENTS_LOG` = `$ART/opencode_events.jsonl` (hardcoded `:474`). Both exist at emit.

## preeval sensor (B3) — clone the churn_hot triad

`score()` is a **pre-dispatch pure function** — it never sees runtime data, so the advisor sensor is
escalation-only (post-run reclassification), exactly like `churn_hot`. Blueprint:
- `score(..., churn_hot=False)` at `:285`; escalation-only override #5 at `:353-356`.
- caller-side reader `_churn_hot_for(repo, paths)` at `:654-668` — "absent/unreadable => False (absence never escalates)".
- wired in `predict()` at `:740-742` (compute) / `:756-757` (pass); selftest at `:967`.
Clone: add `advisor_hot` kwarg, a new escalation-only override AFTER #5, `_advisor_hot_for()` reading
completed `results/*.json usage.advisor_calls`, wire at `:740/:756`, add a selftest. Fail-open (absence never escalates).

## Additive, low-risk

- `resolve-model.py resolve()` (:236-286): `advisor_eligible` is an additive return key; callers read
  `["model"]` — extra keys ignored. No landmine.
- `validate-manifest.py`: per-job validation checks required-field PRESENCE (:539-549) but has NO per-job
  `additionalProperties` rejection — an unknown `advisor:` block is currently silently accepted. B1 layers
  explicit validation; existing manifests stay valid.
- `commands/v-status.md:78` currently FORBIDS all token metrics ("state.json carries none") — must be
  reworded to permit MEASURED usage while still banning estimates; the column reads `results/*.json` via the
  aggregator (a new read dependency) and must degrade to "—" when results/ is absent.

## Regression surface (highest first)

1. `collect-results.py build_result` — runs for EVERY job of EVERY backend; a malformed passthrough or
   schema/collector mismatch fails the whole collect phase. Keep `usage` strictly optional + null-safe.
2. `job_result.schema.json` — add to `properties` only; never touch `required`; keep `additionalProperties:false`.
3. `emit_job_result` stdout purity — any leak corrupts the single-JSON contract.
