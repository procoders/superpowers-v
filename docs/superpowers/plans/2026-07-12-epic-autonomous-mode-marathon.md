# Epic Autonomous Mode — "Marathon Loop" (v2.10) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: use superpowers:subagent-driven-development (recommended)
> or superpowers:executing-plans. Steps use `- [ ]` checkboxes. Source of truth:
> `docs/superpowers/specs/2026-07-12-epic-autonomous-mode-design.md` (v2.10 scope, converged v3) — read
> its "Design constraints from Sol R4" section; every one is a task acceptance criterion here.

**Goal:** ship an opt-in `marathon` stance for `/v:epic` that chews the whole runnable feature DAG in one
invocation, routes failures via a Codex+Claude arbiter panel, isolates suspected external blockers
without halting, and stays bounded by in-script global breakers — the default (`checkpoint`) epic
unchanged.

**Architecture:** one serial "core-contract" unit extends `scripts/compound-v-epic-state.py` (all state +
CLI); a new `scripts/compound-v-epic-arbiter.py` runs the panel; prose wires the driver + reviewer;
docs/CI/release last. Resume after a fall = existing `/v:resume` + human `/v:epic` re-entry (no
auto-watcher — that is deferred v2.11).

**Tech Stack:** Python 3.9-safe stdlib only (no PyYAML — state is pure JSON); reuse atomic-write idiom
(`compound-v-fastpath-run.py:704`), `compound-v-run-with-timeout.py`, `compound-v-resolve-model.py`,
`~/.claude/compound-v-capabilities.json`.

## Global Constraints (every task inherits these — copied verbatim from the spec)

- Opus by default; Sonnet only for the junior-mechanical carve-out; **NEVER Haiku**.
- **No fabricated cost/token metrics** — breakers bound counts + wall-clock only.
- **Two-command commit discipline** — no `&&` on side-effecting git; check each exit code.
- **Opt-in:** default `checkpoint` epic is behaviorally unchanged; new state fields written only in
  `marathon` stance; all 34 existing `epic-state.py` selftests pass unchanged + whole-dir golden
  compatibility (snapshot the epic dir + `git status`, not just JSON bytes).
- **Atomic writes** (tmp + `os.replace`); **no cross-process lock in v2.10** (single process).
- **Python 3.9 ISO:** emit `+00:00` (never bare `Z`); normalize trailing `Z`→`+00:00` on ingest before
  `fromisoformat`. `--now <iso>` injectable; CLI default real clock.
- All new scripts `LANG=C`-clean (reconfigure stdout/stderr UTF-8). Commit new artifacts at v2.6.4 points.

## File Structure

- `scripts/compound-v-epic-state.py` (MODIFY, unit A — the whole file, serial) — marathon state + all new
  subcommands + selftests.
- `scripts/compound-v-epic-arbiter.py` (CREATE, unit B) — Codex+Claude panel, family map, truth table,
  redaction, audit.
- `commands/v-epic.md`, `skills/compound-v/epic-mode.md`, `commands/v-init.md`, `agents/spec-reviewer.md`
  (MODIFY, unit C) — driver loop, Claude-ballot dispatch, `/v:init` stance, anti-reward-hack gate.
- `README.md`, `CHANGELOG.md`, `.claude-plugin/{plugin,marketplace}.json`, `.github/workflows/validate.yml`
  (MODIFY, unit D) — docs, version 2.9.0→2.10.0, CI wiring.

Dependency order: **A → B → C → D** (A publishes its CLI/state contract before B & C; C consumes B's
ballot interface). A is one serial unit (disjoint-write invariant on `epic-state.py`).

---

## Unit A — Core contract (`scripts/compound-v-epic-state.py`)

**Interfaces produced (the frozen contract B & C consume):**
- state schema (marathon-only): `autonomy{stance,max_features,max_attempts_per_feature=2,
  max_no_progress_cycles=3,max_total_attempts,max_wall_clock_hours=10,started_at}`, per-feature
  `{attempts=0,last_error,disposition}`, top-level `final_review{status}`, `blocker_ledger[]`,
  `no_progress_cycles`, `total_attempts`.
- CLI: `--init --stance marathon [caps]`, `--next --autonomous`, `--record-disposition`,
  `--record-final-review`, `--record-progress-cycle`, `--breaker-check` (read), `--trip-breaker` (write),
  `--can-retry`, `--update --status running|blocked|... [--attempt ...]`, `--stats` (adds `blocked`).

### Task A1: marathon schema in `build_state` + `--init --stance`
**Files:** Modify `scripts/compound-v-epic-state.py` (`build_state` ~:111, `main` `--init` ~:445; add
`--stance`, cap args); Test: extend `_selftest`.
**Interfaces — Produces:** `build_state(features, epic_id, title, stance=None, caps=None)` adds the
marathon block + per-feature `attempts/last_error/disposition` ONLY when `stance=="marathon"`; validates
`epic_id` via `_id_ok` (Sol-R4#10).
- [ ] Write failing selftest: `--init` without stance → byte-identical to today (no `autonomy` key);
  `--init --stance marathon --max-wall-clock-hours 8` → writes `autonomy` with every field once,
  `started_at` from `--now`.
- [ ] Run → fails. Implement. Run → passes.
- [ ] Selftest: `_id_ok` rejects a traversal `epic_id` at init.
- [ ] Whole-dir golden test: checkpoint `--init` leaves no extra artifact. Commit.

### Task A2: `--next --autonomous` (read-only, DAG routing, terminal states)
**Files:** Modify (new `next_feature_autonomous`, selected at the `want_next` branch ~:489); Test:
`_selftest`.
**Interfaces — Produces:** `next_feature_autonomous(state) -> (feature|None, reason, blocked_by:[ids])`.
Default `next_feature` UNTOUCHED (all default selftests stay green).
- [ ] Failing selftest: an abandoned/`blocked` feature removes only transitive dependents (reverse
  reachability over `depends_on`, reuse `_detect_cycle` idiom); independents stay runnable; `blocked_by`
  derived read-only; re-derives after a source reopens.
- [ ] Terminal resolution: `done` only if all-done AND `final_review==passed`; `blocked_needing_human` for
  halt_epic / tripped breaker / any suspected blocker; `running_with_failures` while runnable. (v2.10
  never emits `done_with_blockers`.)
- [ ] Run fail→impl→pass. Default `--next` shape unchanged (2-key) selftest still green. Commit.

### Task A3: attempts + `--can-retry` + transition table
**Files:** Modify (`--update` ~:498). **Produces:** `--update --status running` increments
`attempts` (via `.get`); legal →running sources = pending/failed (done/blocked rejected);
`--can-retry --feature F` → `{can_retry,attempts,cap}`.
- [ ] Failing selftest: running-transition increments; done→running rejected; `--can-retry` flips at
  `max_attempts_per_feature`. Impl→pass→commit.

### Task A4: `--record-disposition`
**Files:** Modify. **Produces:** `--record-disposition --feature F --disposition retry_fix|halt_feature|
halt_epic|blocked_external --reason ... [--families-agreeing ...]` stores `disposition` obj atomically;
**hard-rejects `--blocker-confirmed true`** (v2.10, Sol-R4#2) — `confirmed` always false.
- [ ] Failing selftest: round-trips + drives `--next --autonomous` routing; `confirmed:true` rejected.
  Impl→pass→commit.

### Task A5: blocker ledger lifecycle
**Files:** Modify (`--update --status blocked`, `--summary`, `--stats`). **Produces:** ledger append
idempotent by `(feature, attempt)`; entries carry `active`/`resolved_at`; `--update --status pending`
resolves the active entry (so a since-succeeded blocker never appears in the report).
- [ ] Failing selftest: blocked→pending→done clears the ledger entry; replay of the same blocked update
  is idempotent (no dup); `--stats` breaks out `blocked`. Impl→pass→commit.

### Task A6: final-review gate
**Files:** Modify. **Produces:** top-level `final_review{status:pending|passed|failed}`;
`--record-final-review --status ...` atomic; A2's terminal resolution already reads it.
- [ ] Failing selftest: all-features-done but `final_review!=passed` → NOT `done` (stays
  `running_with_failures`/pending-review); after `--record-final-review passed` → `done`. Impl→pass→commit.

### Task A7: global breakers (`--breaker-check` read / `--trip-breaker` write / `--record-progress-cycle`)
**Files:** Modify. **Produces:** `--breaker-check --now T` read-only → `{tripped,which,detail}` on
`total_attempts>=max(6,3×features)` | `no_progress_cycles>=3` | wallclock`>=max_wall_clock_hours`;
`--trip-breaker --now T` atomically sets `blocked_needing_human`; `--record-progress-cycle --cycle-id C
--now T` idempotently compares prior vs current `done` count, increments/resets `no_progress_cycles`.
- [ ] Failing selftest: each breaker trips at its boundary not before; `--breaker-check` never mutates;
  `--trip-breaker` sets terminal; `no_progress_cycles` resets on a new `done`; replayed `--cycle-id` is a
  no-op; null/negative caps validated with a loud log. Impl→pass→commit.
- [ ] **Publish the contract:** run full `--selftest` under `LANG=C` and Python 3.9; write a short
  `## CLI contract` block at the top of the script docstring listing every subcommand + JSON shape (B & C
  read this). Commit.

---

## Unit B — Arbiter panel (`scripts/compound-v-epic-arbiter.py`, NEW) — depends on A

**Interfaces — Produces:** `compound-v-epic-arbiter.py classify --state S --feature F --evidence-file E
[--claude-ballot F] --now T` → prints `{disposition, confirmed:false, reason, ballots:[...]}` and writes
the audit JSON.

### Task B1: capabilities discovery + family map
- [ ] Failing selftest: reads `~/.claude/compound-v-capabilities.json` (fixture) — Codex available iff
  `available && exec_flags_verified`; absent/malformed → Codex unavailable → Claude-only path. Family map
  (`gpt`→GPT, `gemini`→Gemini, `claude|opus|sonnet`→Claude, `grok`→Grok, else `unknown`) keyed on resolved
  model NAME; `cursor` "auto"→unknown; one ballot per family. Impl→pass→commit.

### Task B2: Codex read-only poll (through the supervisor)
- [ ] Failing selftest (fake supervisor): builds the exact invocation `compound-v-run-with-timeout.py
  --timeout N --max-output-bytes M -- codex exec --sandbox read-only --model <resolved> -c
  model_reasoning_effort=high --json --output-last-message F "<prompt>" </dev/null`; reads verdict from
  the FINAL message, SKIPS the cosmetic `codex_hooks` deprecation event; a garbled reply is DROPPED +
  logged (never a fabricated halt vote). Impl→pass→commit.

### Task B3: Claude ballot interface + evidence redaction
- [ ] Failing selftest: `classify` EMITS a bounded Claude prompt and ACCEPTS `--claude-ballot <file>`
  (B cannot launch Claude — C does); a malformed/stale/wrong-feature ballot is dropped safely. Evidence
  redaction: conservative function drops token / `Authorization:` / private-key / URL-cred / multiline
  secrets, **fails closed** (omit suspect evidence) if it can't complete, before egress; capped to
  `--max-output-bytes`. Impl→pass→commit.

### Task B4: aggregation truth table + audit write
- [ ] Failing selftest: the COMPLETE truth table for every pair of valid ballots + one-ballot + zero-
  ballot (retry_fix/halt_feature/halt_epic/blocked_external); parse-fail dropped; empty/tied →
  conservative `halt_feature`; `blocked_external` on the Codex+Claude panel → SUSPECTED (`confirmed:false`)
  because <2 known external families; `retry_fix` past `--can-retry` cap → `halt_feature`; classify still
  runs at the cap. Audit JSON validates BOTH `epic_id` + `feature` id, realpath-contained, atomic,
  cap/rotate. `--selftest` under `LANG=C` + Py3.9. Commit.

---

## Unit C — Driver + reviewer prose (4 files) — depends on A, B

### Task C1: `commands/v-epic.md` + `skills/compound-v/epic-mode.md` — autonomous path
- [ ] Add the `marathon` branch: loop `--next --autonomous`; `--breaker-check` + `--record-progress-cycle`
  before each feature; on FAILURE → build evidence file → dispatch a fresh adversarial Claude Task
  (write its ballot file) → run arbiter `classify --claude-ballot` → `--record-disposition` → act under
  the breaker (retry_fix re-runs; halt_feature abandons → DAG continues; blocked_external → ledger);
  before terminal `done` run the final cross-feature re-verification → `--record-final-review`; on terminal
  status emit the halt-page runbook (every field from spec Component 5). Default path unchanged; **split
  any `&&` git chains touched.** Scope the fail-fast prose to `checkpoint` stance. Commit.

### Task C2: `commands/v-init.md` — stance config
- [ ] `/v:init` Step 3 writes `epic.autonomy.stance` (default `checkpoint`; offer `marathon` with the
  honest v2.10 boundary: in-session + human resume, NO auto-revive; the breaker caps). Commit.

### Task C3: `agents/spec-reviewer.md` — anti-reward-hack gate
- [ ] Add to the QUALITY pass a deterministic "did this diff weaken its own tests/scorers to pass?" check
  with concrete evidence (removed asserts, loosened thresholds, deleted test files, scorer edits) — a
  fixture where a weakened scorer is REJECTED. Commit.

---

## Unit D — Docs + CI + release — depends on C

### Task D1: CI selftests under Py3.9
- [ ] `.github/workflows/validate.yml`: run `compound-v-epic-state.py --selftest` and
  `compound-v-epic-arbiter.py --selftest` under **Python 3.9** (add the version) + the normal version.
  Commit.

### Task D2: README + CHANGELOG + version bump
- [ ] README "Main features": Marathon Loop · Arbiter Panel · Blocker Ledger · Global Breakers, honest
  v2.10 boundary inline ("auto-resurrection coming in v2.11"). CHANGELOG 2.10.0 entry. Bump
  `.claude-plugin/{plugin,marketplace}.json` 2.9.0→2.10.0. Commit.

## Self-review (run before dispatch)
- Spec coverage: every spec Component + all 11 R4 constraints map to a task above (final-review→A6/A2;
  no-caller-confirm→A4; truth table→B4; breaker freq→C1+A7; progress-cycle→A7; --init stance→A1; ballot
  interface→B3/C1; ledger lifecycle→A5; anti-reward-hack→C3; feature-id audit→B4; redaction→B3). ✓
- No placeholders: each task names exact files, signatures, and the acceptance test. ✓
- Type consistency: disposition enum, terminal-status names, and the arbiter JSON shape match across A/B/C.
