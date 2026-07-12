# Epic Autonomous Mode — "Marathon Loop" Design Spec

> **Status:** design, pre-implementation. Authored 2026-07-12 on branch `epic-autonomous-mode`.
> **For agentic workers:** this spec feeds `superpowers:writing-plans`. Terminology here (Marathon
> Loop · Heartbeat · Two-Tier Watcher · Arbiter Panel) is the vocabulary the README will use once the
> mechanism exists — do NOT write README marketing copy for any part that is not yet built.

**Goal:** make `/v:epic` optionally run as a self-sustaining marathon — chew through its feature DAG
without stopping for a human at every feature, survive interruptions, and decide what to do about a
failed feature via a cross-model arbiter panel — all under hard circuit breakers, and all **opt-in**
so the default epic stays exactly as cautious as it is today.

**Architecture (one sentence each):** A **Marathon Loop** raises the per-invocation feature budget and,
in autonomous mode, relaxes fail-fast so a failed feature blocks only its *dependents*. A **Heartbeat**
timestamp in `epic-state.json` lets an external watcher tell "actively chewing" from "died mid-chew". A
**Two-Tier Watcher** (session `CronCreate` + on-disk `scheduled-tasks`) resurrects a stalled/dead run.
On a quality-gate failure, an **Arbiter Panel** polls every available cross-model backend for a
disposition verdict (retry-fix / skip-independent / halt), falling back to a fresh adversarial Claude
agent, all bounded by **Circuit Breakers**.

**Tech Stack:** Python 3.9-safe stdlib (extends `scripts/compound-v-epic-state.py`); a new
`scripts/compound-v-epic-arbiter.py`; a new `scripts/compound-v-epic-watch.py`; skill/command prose
(`skills/compound-v/epic-mode.md`, `commands/v-epic.md`, `commands/v-init.md`); `README.md`. Reuses
existing backend detection (`~/.claude/compound-v-capabilities.json`, backend-launcher adapters) — no
new discovery mechanism.

## Global Constraints

- **Opus by default; Sonnet only for the junior-mechanical carve-out; NEVER Haiku** (lint + CI enforced).
- **No fabricated cost/token metrics** anywhere (anti-ruflo).
- **Two-command commit discipline** — never chain side-effecting git with `&&`; check each exit code.
- **git-derived enforcement never model-self-reported** — the arbiter decides *disposition of a
  confirmed FAIL*; it can never fake a PASS. The scope-gate + Review Gate verdicts stay authoritative.
- **External CLIs run through `scripts/compound-v-run-with-timeout.py` with `stdin </dev/null`.**
- **Everything new is OPT-IN.** Default `/v:epic` (no `epic.autonomous`) behaves byte-for-byte as today:
  `MAX_FEATURES=1`, hard fail-fast, no watcher, no arbiter. All 30+ existing `epic-state.py` selftests
  must still pass unchanged.
- **`LANG=C`-safe:** any script printing non-ASCII reconfigures stdout/stderr to UTF-8.
- Commit the epic run substrate before any worktree cleanup can delete it (v2.6.4 lesson).

## The two-level failure model (honesty boundary — ships in the docs verbatim)

"Epic survives a fall" means precisely:

- **Level 1 — soft stall in a live session** (a step errored, a wave hung, a turn ended without
  completing the epic): the session `CronCreate` watcher fires while the REPL is idle and re-enters
  `/v:epic <id>`. Fully automatic. **Verified feasible** (this is the manual pattern, productized).
- **Level 2 — hard death** (quota exhausted, Claude servers down, app closed): the on-disk
  `scheduled-tasks` watcher re-fires the self-contained resume prompt. **Semi-automatic** — it runs
  "while the app is open" or "on next launch", NOT from a truly always-on server. Honest wording, no
  overclaim.
- **Truly headless** (zero local process, laptop closed): out of scope for the plugin; needs an OS
  `launchd`/cron shim that relaunches Claude Code. Documented as an optional user-side add-on, not
  claimed as built-in.

`CronCreate` is in-memory/session-bound (`durable` = no-effect, dies on exit); `scheduled-tasks` is
on-disk (`~/.claude/scheduled-tasks/<id>/SKILL.md`, self-contained, fires on next launch). These facts
were verified live and are the basis for the Level-1/Level-2 split.

## Component 1 — Marathon Loop (epic-state.py, opt-in)

**State schema additions** (backward-compatible — absent ⇒ legacy behavior):
- top level: `"autonomy": {"stance": "checkpoint|marathon", "max_features": <int|null>,
  "max_attempts_per_feature": <int, default 2>, "max_no_progress_cycles": <int, default 3>}`.
  `stance` absent or `"checkpoint"` ⇒ **exactly today's behavior**.
- per feature: `"attempts": <int, default 0>` (bumped each time the feature enters `running`),
  `"last_error": <str|null>`.

**New `--next --autonomous` semantics** (a *separate* code path; the default `--next` is untouched):
- Fail-fast is **relaxed**: a `failed` feature blocks only features that (transitively) `depends_on`
  it. Independent pending features remain runnable. (Default `--next` keeps whole-epic fail-fast.)
- A `running` feature still means "crashed mid-run" and forces reconcile — unchanged.
- Returns the same `{"feature", "reason"}` contract, plus `"blocked_by_failure": [ids]` so the driver
  can report what was skipped.

**Retry accounting:** `--update --status running` increments `attempts`. A new read-only
`--can-retry --feature <id> --state S` returns `{"can_retry": bool, "attempts": n, "cap": m}` — the
deterministic backing for the circuit breaker. When `attempts >= max_attempts_per_feature`, the
feature is force-`failed` and the epic pages the human regardless of arbiter opinion.

**Acceptance:** default selftests unchanged & green; new selftests cover: marathon `--next` routes
around an independent failure but blocks dependents; `attempts` increments; `--can-retry` flips at the
cap; a `checkpoint`-stance state behaves identically to a legacy (no-`autonomy`) state.

## Component 2 — Heartbeat / liveness (epic-state.py)

- Every state mutation (`--update`, `--init`) writes `"last_progress_at": "<ISO-8601 UTC>"` at the top
  level. **Timestamp comes from `--now <iso>` passed by the caller** (scripts cannot call
  `datetime.now()` reproducibly in the workflow sandbox, and the driver already knows the time) — but
  for the CLI path a plain `datetime.now(timezone.utc)` default is fine; the injectable arg keeps it
  testable.
- New `--liveness --state S --now <iso> --stale-after-min <N, default 45>` →
  `{"alive": bool, "stale": bool, "last_progress_at", "age_min", "epic_status"}`. `stale` = incomplete
  epic whose `last_progress_at` is older than `N` minutes. This is what the watcher polls.
- **Acceptance:** a fresh epic is `alive` & not `stale`; advancing `--now` past the threshold flips
  `stale`; a `done` epic is never `stale`; selftest asserts all three.

## Component 3 — Two-Tier Watcher (compound-v-epic-watch.py + prose)

A helper that **emits the watcher prompt** and **advises which tier(s) to arm** — it does NOT itself
schedule (scheduling is a harness tool call the driver makes). Keeps the script harness-neutral.

- `compound-v-epic-watch.py emit-prompt --epic-id E --state S` → prints the self-contained resume
  prompt used by BOTH tiers (read state → check liveness → resume if stale → stop+disarm if
  done/blocked-needing-human). Self-contained per the `scheduled-tasks` contract (no conversation
  memory).
- `compound-v-epic-watch.py plan --state S --now <iso>` → `{"tier1": "cron 17,47 * * * *",
  "tier2": "scheduled-task 30m", "disarm": bool}` — advisory. `disarm=true` once the epic is terminal.
- **The driver** (`/v:epic --autonomous`) arms Tier 1 via `CronCreate` and Tier 2 via
  `mcp__scheduled-tasks__create_scheduled_task`, and disarms both (`CronDelete` +
  `delete_scheduled_task`) when the epic completes or blocks-for-human. Off-minute cadence (:17/:47).
- **Acceptance:** `emit-prompt` output is self-contained (mentions epic-id, state path, resume + disarm
  conditions, model/commit constraints) and contains no conversation-relative references; `plan`
  returns `disarm=true` for a `done`/`blocked` state and the arm cadence otherwise; both `--selftest`.

## Component 4 — Cross-Model Arbiter Panel (compound-v-epic-arbiter.py)

On a quality-gate FAILURE, decide the disposition. **Degrade-safe panel, never a hard dependency on
any one backend.**

- **Discovery:** read `~/.claude/compound-v-capabilities.json` (+ `.claude/compound-v.json` if present)
  for `available` backends among `codex`, `antigravity` (`agy`), `cursor`. No new detection.
- **Panel poll:** for each available external backend, run a **read-only** advisory query via that
  backend's headless invocation (through the timeout supervisor, `stdin </dev/null`), asking for a
  strict-JSON verdict `{"disposition": "retry_fix|skip_independent|halt|blocked_external",
  "reason": "<one line>", "evidence": "<what external fact is missing, if blocked_external>"}` over the
  failed feature's evidence (spec acceptance, scope-gate/reviewer output, the failing diff summary, and
  any pre-flight finding that flagged an external gap). Read-only ⇒ `agy`/`cursor`
  lower-trust-as-*writer* does NOT apply; they are advisors here.
- **`blocked_external`** = the feature cannot be built because of a fundamental EXTERNAL reality (an
  upstream API returns no/incomplete data, a DB lacks the field, an unmet upstream contract) — NOT a
  quality bug and NOT retryable by us. Requires human/external action. (Archetype: astrology #150 —
  `/horary/analyze` returns sign-only house cusps, no degrees ⇒ the wheel can't be rendered without an
  upstream `/horary/chart` shape change.)
- **Aggregate — asymmetric by disposition:**
  - `retry_fix` vs `halt` vs `skip_independent`: majority disposition; **ties and any parse failure
    break CONSERVATIVE toward `halt`** (never push unverified work through a gate).
  - `blocked_external`: the OPPOSITE bias — accepting it must be HARD, or it becomes a lazy escape from
    difficult work. **Accept as CONFIRMED only on ≥2 independent external models agreeing
    `blocked_external` with no dissenting `retry_fix`.** If ANY panel member says `retry_fix`, the
    feature is deemed *doable by someone* → route to `retry_fix` under the breaker (try, don't skip).
    With <2 external models available (e.g. Claude-only, or a single backend), a `blocked_external`
    proposal is downgraded to **SUSPECTED** (not confirmed) — see the Blocker Ledger: the feature is
    still isolated so the epic continues, but the note is flagged UNCONFIRMED / needs-human-verify, and
    Claude-self alone can never CONFIRM a blocker (same-family, and "not my choice" must mean not one
    model's choice).
  - Record every panel member's raw verdict for the audit trail (`docs/superpowers/execution/epics/
    <id>/arbiter/<feature>-<attempt>.json`) — never fabricate a vote for an absent/errored backend.
- **Fallback (zero external backends available):** emit a `needs_arbiter` prompt for a **separate,
  fresh-context Claude/Opus** agent (NOT the implementer), adversarially framed ("default to `halt`;
  only `retry_fix`/`skip_independent` if you can justify it"). The driver runs it as a Task and feeds
  the JSON verdict back via `--record-claude-verdict`.
- **Circuit-breaker interaction:** the arbiter is consulted only if `--can-retry` is true. A
  `retry_fix` when `attempts` would exceed the cap is downgraded to `halt`. The breaker always wins.
- **Acceptance:** with a fixture capabilities file listing 3 backends and a fake supervisor, the panel
  aggregates 3 verdicts, ties break to `halt`, a garbled backend reply is treated as `halt`-leaning
  and logged (not fabricated); zero-backend path emits a well-formed adversarial Claude prompt; a
  `retry_fix` past the cap becomes `halt`. All `--selftest`, `LANG=C`-clean.

## Component 4b — Blocker Ledger + end-of-epic human report (the "do everything you can" credo)

The core credo: **finish absolutely everything that is in your power; isolate ONLY the genuinely
impossible; escalate that — with multi-model proof — to a human, without halting the rest.** A
fundamental external blocker is a *fact about the world*, not a quality failure or a choice — so it must
never stop the epic, only carve out its own sub-tree.

- **State:** `epic-state.json` gains top-level `"blocker_ledger": [ {feature, confirmed: bool, reason,
  evidence, models_agreeing: [ids], first_seen_at, blocks: [dependent ids]} ]`. A feature whose
  disposition resolves to `blocked_external` (confirmed) or SUSPECTED-blocker gets a ledger entry and
  status `"blocked"` (a NEW terminal-ish status distinct from `failed`).
- **`--update --status blocked --feature F --blocker-reason ... --blocker-confirmed true|false
  --models-agreeing codex,cursor`** appends the ledger entry and marks F `blocked`.
- **`--next --autonomous` treats `blocked` like a benign skip, NOT a fail-fast trigger:** a `blocked`
  feature blocks only its transitive dependents (they also become `blocked`, ledger-linked "blocked
  upstream: F"); every INDEPENDENT pending feature stays runnable. The epic runs to completion on
  everything reachable, then reports. (`failed` after the retry cap still halts-for-human; `blocked` is
  the "world lacks the data" lane and does NOT halt.)
- **Discovery is two-point:** a blocker can surface during **pre-flight research** (1B domain / 1C
  doc-validator finds "the upstream API has no such field") *or* mid-**implementation** (a worker hits
  it, like #150). Both funnel through the SAME arbiter-panel confirmation (≥2 external models) before a
  ledger entry is marked `confirmed` — a pre-flight suspicion alone is SUSPECTED until the panel agrees.
- **End-of-epic report:** on `epic complete` (all features `done` OR `blocked`), the final integration
  review runs over the built subset, then the report leads with the Blocker Ledger:
  > "Built everything reachable. **N feature(s) need YOU** — a human/external action, because the code
  > cannot create data that doesn't exist upstream:" then per entry: feature, one-line reason, the
  > missing external fact, which models agreed (confirmed) or that it is a single-model SUSPICION, and
  > what it transitively blocked. `blocked` (world-fact) is visually separated from `failed`
  > (needs-a-fix) so the human sees "impossible-without-me" apart from "broken".
- **A `blocked`-only epic is still a SUCCESS-with-caveats, not a failure** — the point is maximal
  completion. `--stats` counts `blocked` separately from `done`/`failed`.
- **Acceptance:** selftest covers: a confirmed `blocked_external` isolates its dependents but not
  independents; `--next --autonomous` keeps advancing past a `blocked` feature; a single-model proposal
  yields `confirmed:false`; the ledger round-trips through `--update`/`--summary`; `--stats` breaks out
  `blocked`. The report text names the missing external fact and the agreeing models, never fabricates a
  vote, and never confirms on Claude-self alone.

## Component 5 — Driver wiring (v-epic.md, epic-mode.md, v-init.md)

- `/v:epic` gains an autonomous path: when `.claude/compound-v.json` `epic.autonomous.stance ==
  "marathon"` (or an explicit `--autonomous` arg), the loop (a) uses `--next --autonomous`, (b) arms
  the Two-Tier Watcher, (c) on a feature FAILURE consults the Arbiter Panel and acts on the verdict
  under the breaker, (d) bumps `last_progress_at` each transition, (e) on epic-complete/blocked-for-
  human disarms both watchers and reports. Default (checkpoint) path is unchanged.
- `epic-mode.md` (authority doc) gains the marathon section + the honesty boundary verbatim.
- `/v:init` Step 3 writes the `epic.autonomous` stance (a new gated question: keep default `checkpoint`;
  offer `marathon` with the honest Level-1/2 caveat and the circuit-breaker caps).
- **Acceptance:** a spec-reviewer pass confirms the default path is untouched (diff shows the autonomous
  path is strictly additive); the honesty boundary text is present; no fabricated metrics.

## Component 6 — README + docs (LAST — built only after 1–5 are real)

- README "Main features" gains a **Marathon Loop · Heartbeat · Two-Tier Watcher** subsection with the
  honest Level-1/2/headless boundary inline (no overclaim). Written only after the mechanism passes
  its review. `CHANGELOG.md` + `.claude-plugin/plugin.json` version bump (2.9.0 → 2.10.0).
- **Acceptance:** every capability the README claims maps to a shipped, tested component; the
  Level-2/headless honesty caveat is present; version bumped; CI green.

## Feature DAG (for the epic decomposition)

```
F1 marathon-loop (epic-state autonomy fields + relaxed --next + retry/breaker)   depends_on: []
F2 heartbeat     (last_progress_at + --liveness)                                 depends_on: [F1]
F4 arbiter-panel (compound-v-epic-arbiter.py)                                    depends_on: [F1]
F3 watcher       (compound-v-epic-watch.py emit-prompt/plan)                     depends_on: [F2]
F5 driver-wiring (v-epic.md / epic-mode.md / v-init.md)                          depends_on: [F1,F2,F3,F4]
F6 docs+release  (README / CHANGELOG / version bump)                             depends_on: [F5]
```

Disjoint file partition (no two features write the same file):
- F1,F2 → `scripts/compound-v-epic-state.py` (same file — so F1 and F2 are **one** dispatch unit, not
  parallel; sequence them or merge into one task to respect the disjoint-write invariant).
- F4 → `scripts/compound-v-epic-arbiter.py` (new).
- F3 → `scripts/compound-v-epic-watch.py` (new).
- F5 → `commands/v-epic.md`, `skills/compound-v/epic-mode.md`, `commands/v-init.md`.
- F6 → `README.md`, `CHANGELOG.md`, `.claude-plugin/plugin.json`, `.claude-plugin/marketplace.json`.

## Honesty boundary (state to the user, ship in docs)

- Marathon mode is **opt-in**; the default epic is unchanged and still checkpoints for a human.
- "Survives a fall" = Level-1 fully auto, Level-2 semi (resurrects on next Claude launch), truly-
  headless needs an OS shim. No pretending disk-cron is server-cron.
- The Arbiter Panel is **advisory disposition of a confirmed failure**; the git-derived gate and the
  circuit breaker are the deterministic guardrails it cannot override. Claude-self fallback is weaker
  than a cross-model panel (correlated blind spots) — the breaker, not the arbiter, is the safety net.
- No fabricated metrics; the arbiter never invents a vote for an absent backend.
```
