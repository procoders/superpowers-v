# v2.12 — Per-ticket usage capture + on-demand Advisor

**Goal:** Two features shipped in one dogfooded epic on `v2.12-usage-and-advisor`: (A) capture
REAL measured backend token usage into `job_result` and aggregate it per ticket / feature / epic;
(B) an opt-in "cheap executor + on-demand cross-brand advisor" pattern — a Sonnet executor that, on
a hard sub-decision, consults an advisor of a DIFFERENT model/brand (Codex if available, else Opus),
where the advisor is READ-ONLY (advises, never writes).

**Architecture:** Feature A owns the shared usage foundation: a `usage` object on `job_result`, a
single extraction library, AND the collector passthrough (the pre-flight-discovered gap). Feature B's
escalation sensor consumes `usage.advisor_calls` read-only — the sole cross-feature dependency edge.

**Tech stack:** Python 3.9-safe stdlib, bash, jq. No new external deps. No API key. No `anthropic` SDK.

> **Grounded by 3 pre-flights (2026-07-13), live-probed — NOT training data:**
> - `claude -p --advisor` **does not exist** (0 matches, CLI 2.1.207). The API `advisor_20260301`
>   tool is real but requires the `anthropic` SDK + `ANTHROPIC_API_KEY` — rejected: breaks the plugin's
>   pure-stdlib/no-service/subscription ethos. Advisor is therefore a **harness subagent pattern**.
> - codex usage event = `turn.completed.usage{input_tokens,cached_input_tokens,output_tokens,reasoning_output_tokens}`
>   — SUM across all `turn.completed` events, filter out `error`/deprecation items.
> - opencode = `step_finish.part.tokens{input,output,reasoning,cache.read,cache.write,total}` (`--format json`).
> - cursor = `result.usage{inputTokens,outputTokens,cacheReadTokens,cacheWriteTokens}` (needs `-f`).
> - agy = NO structured usage → `measured:false`. claude via Task subagent = NO usage → `measured:false`.
> - **Collector gap:** `compound-v-collect-results.py build_result()` returns a fixed 10-key dict and
>   DROPS `usage`. MUST add passthrough or every measured value is silently discarded.

## Global Constraints (verbatim, apply to every task)

- Opus by default; Sonnet only for the narrow junior carve-out; **NEVER Haiku**.
- **anti-ruflo:** only REAL measured usage is recorded. No estimated / invented token or cost numbers.
  Where a backend exposes no usage, `usage:{... measured:false}` with null tokens. Selftest fixtures
  MUST be captured from real CLI output.
- **Advisor is READ-ONLY (hard MUST):** the advisor consult NEVER writes files or runs destructive
  bash. Cross-brand path = `codex exec --sandbox read-only`. Opus fallback = `claude -p --model opus`
  with NO write tools and **NEVER `--dangerously-skip-permissions`**. A no-write advisor structurally
  removes the repo-deletion incident risk. Test the consult script with a FAKE stub first; a real probe
  is allowed ONLY under a read-only sandbox.
- Python 3.9-safe (no `match`, no `X|Y` unions), stdlib only. `LANG=C`-clean. Selftests pass under 3.9.
- `usage` goes in `schemas/job_result.schema.json` **properties only, never `required`**; keep
  `additionalProperties:false`. The collector's `conformance_errors` rejects any property not in the schema.
- Worker stdout stays EXACTLY one `job_result` JSON — the usage-extract call reads the events log into a
  variable, never writes stdout.
- Git-derived enforcement only; scope gate after every job; push the WIP branch after each unit.
- Two-command commit discipline (no `&&` chaining of side-effectful git commands).

## Feature A — per-ticket usage capture

### A0 — foundation (shared, serial; nothing races it)
- `schemas/job_result.schema.json`: add optional `usage` object to **properties only**:
  `{input_tokens:int|null, output_tokens:int|null, advisor_calls:int|null, backend:string, measured:bool}`.
- `scripts/compound-v-usage-extract.py` (new): `(backend, events_log_path) -> usage`. Per-backend
  normalizer (each backend uses different casing/shape). codex: sum `turn.completed.usage`;
  opencode: sum `step_finish.part.tokens`; cursor: `result.usage`; agy/claude-Task/devin:
  `measured:false`, null tokens. `--selftest` with fixtures captured from real CLI output.
- `scripts/compound-v-collect-results.py`: `build_result()` (~:283) MUST copy `wjson.get("usage")`
  through to the result dict (null-safe, optional). Without this, A1 emission is discarded. This file
  was absent from the original touch list — it is the single blocking gap.

### A1 — worker usage hooks
- `scripts/compound-v-run-codex-worker.sh`, `scripts/compound-v-run-opencode-worker.sh`: `emit_job_result`
  gains a `usage` field; before emit, call `compound-v-usage-extract.py` on `$EVENTS_LOG` and pass the
  result. Absent/unparseable ⇒ `measured:false`. No stdout writes from the extract call.

### A2 — aggregation + status
- `scripts/compound-v-usage-aggregate.py` (new): scans `docs/superpowers/execution/<run-id>/results/*.json`,
  sums `usage` per ticket/feature/epic; `measured:false` jobs counted as "unmeasured", not zero.
- `commands/v-status.md`: add a usage column sourced from the aggregator; **reword line ~78** (currently
  forbids ALL token metrics) to permit MEASURED usage while still banning estimates; degrade-safe
  (results/ absent ⇒ show "—", never break the table).

### A3 — docs
- `skills/compound-v/execution-manifest.md`: document the `usage` field (measured-only contract).

## Feature B — on-demand cross-brand Advisor (subagent pattern, opt-in)

### B1 — eligibility
- `scripts/compound-v-resolve-model.py`: expose `advisor_eligible` (additive return field) — a
  `standard`/core-slice implementer OR a fast-path Claude worker is eligible; plus an advisor-backend
  SELECTOR: prefer a DIFFERENT brand than the executor (codex > other non-claude), fall back to opus.
- `scripts/compound-v-validate-manifest.py`: accept + validate an optional per-job `advisor:` block;
  reject advisor on ineligible job types with a clear message. (Currently an unknown `advisor:` key is
  silently accepted — B1 adds explicit validation; existing manifests stay valid.)

### B2 — advisor consult (READ-ONLY; stub-first)
- `scripts/compound-v-advisor-consult.sh` (new): input = a question + read-only context paths; picks the
  advisor backend via B1's selector (cross-brand codex `exec --sandbox read-only --json` preferred; opus
  fallback = `claude -p --model opus`, read-only, no write tools, never bypass-permissions); runs ONE
  advisory turn; returns advice text; increments an advisor-call counter. NEVER writes files.
- `skills/backend-launcher/adapter-advisor.md` (new): the read-only advisor contract + cross-brand rule.
- `scripts/test-advisor-worker-stub.sh` (new): fake-backend stub — proves the selector (cross-brand
  preference + opus fallback), argv, and advice parse. `advisor_calls` = worker-counted consults (NOT
  read from any CLI `usage.iterations[]` — that is turn count, not advisor count).

### B3 — escalation sensor (depends on A0 + B1)
- `scripts/compound-v-preeval.py`: clone the existing `churn_hot` triad — a `score()` kwarg
  (`advisor_hot`), an escalation-only override AFTER override #5, an `_advisor_hot_for()` reader over
  completed `results/*.json usage.advisor_calls`, wiring in `predict()`, and a selftest. **Escalation-only,
  fail-open** (absence never escalates), post-run read only (`score()` is a pre-dispatch pure function).
- `skills/compound-v/routing-policy.md`: document when advisor mode is chosen vs classic dispatch.

### B4 — surface
- `README.md`: flip the advisor lane from "opt-in, in development" to shipped/opt-in (cross-brand read-only).
- `docs/routing.svg`: drop the "in development" qualifier on the advisor lane.

## Closing (shared-resource owner + review)

- **Z1** (serial): `CHANGELOG.md` + version bump `.claude-plugin/plugin.json` +
  `.claude-plugin/marketplace.json` to `2.12.0` (lockstep). Sole writer of these shared files.
- **Z2** (serial, reviewer, writes nothing): spec-reviewer 3-pass over the whole diff, then Codex
  cross-model rounds to convergence before merge.

## Acceptance criteria (epic-level)

- `job_result` carries measured `usage`, threaded through worker → collector → aggregator; aggregator
  reports per-ticket/feature/epic totals with an honest unmeasured count; zero fabricated numbers.
- Advisor mode is selectable, eligible on core-slice + fast path, prefers a cross-brand advisor and
  falls back to Opus, is READ-ONLY, and is proven by a stub test (real probe only under read-only sandbox).
- All selftests green under Python 3.9; 2.12.0 lockstep; scope gate clean on every job.
