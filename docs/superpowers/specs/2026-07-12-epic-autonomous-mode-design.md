# Epic Autonomous Mode — "Marathon Loop" Design Spec (v2.10 scope, converged v3)

> **Status:** design, pre-implementation. Branch `epic-autonomous-mode`. **PHASED** after 3 Codex Sol
> xhigh reject rounds converged on a scope decision (below). This spec is the **v2.10** slice; the
> deferred **v2.11** (auto-resurrection) is sketched at the end.
> **For agentic workers:** feeds `superpowers:writing-plans`. README marketing copy is written only for
> parts that exist and pass review (Component 6, last).

## Scope decision — why PHASED (read first)

Three independent Sol rounds converged: **every *critical* concurrency finding traced to the
auto-resurrection two-tier watcher.** Making it correct requires threading a lease *generation* through
the dispatcher / worker / merge-back / commit layer (`agents/parallel-dispatcher.md` Step 7,
`skills/backend-launcher/SKILL.md`) — i.e. re-architecting the plugin's most hardened execution code
(v2.6.4 commit discipline, the scope gate, worktree lifecycle). That is its own project, not an
overnight build.

**Remove the auto-watcher and the marathon is single-process — the entire class of concurrency
criticals disappears** (the lease/flock/`--claim-stale`/generation-fencing existed *only* to make
auto-resurrection safe). So:

- **v2.10 (this spec):** Marathon Loop + Global Breakers + cross-model Arbiter Panel (Codex + Claude) +
  Blocker Ledger + driver + docs. Autonomous **within one `/v:epic` invocation**; resume after a fall is
  the existing `/v:resume` + a human re-invoking `/v:epic` (re-entrant by design — safe, because nothing
  auto-resurrects concurrently). This is Oleg's manual overnight pattern productized, minus the scheduler.
- **v2.11 (deferred, its own spec):** the Execution Lease + Two-Tier Watcher + generation-fenced
  execution layer — the auto-"survives a fall while you sleep" part.

**Goal (v2.10):** make `/v:epic` optionally chew through its whole runnable feature DAG in one
invocation without stopping at every feature, decide what to do about a failed feature via a
family-diverse (Codex + Claude) arbiter panel, isolate — not halt on — suspected external blockers, and
stay bounded by hard global circuit breakers — all **opt-in**, so the default epic is unchanged.

**Tech Stack:** Python 3.9-safe stdlib (extends `scripts/compound-v-epic-state.py`); new
`scripts/compound-v-epic-arbiter.py`; prose (`skills/compound-v/epic-mode.md`, `commands/v-epic.md`,
`commands/v-init.md`); `README.md`, `CHANGELOG.md`, `.claude-plugin/*.json`, `.github/workflows/
validate.yml`. Reuses: `compound-v-run-with-timeout.py` (external calls, `</dev/null`,
`--max-output-bytes`), `compound-v-resolve-model.py` (model name), `~/.claude/compound-v-
capabilities.json` (the ONLY availability source), the atomic-write idiom from `compound-v-fastpath-
run.py:704` (tmp + `os.replace`).

## Global Constraints

- **Opus by default; Sonnet only for the junior-mechanical carve-out; NEVER Haiku** (lint + CI enforced).
- **No fabricated cost/token metrics** — breakers bound *counts and wall-clock*, never invented dollars.
- **Two-command commit discipline** — no `&&` on side-effecting git; check each exit code. F-core also
  splits any pre-existing `&&` git chains it touches in `v-epic.md`.
- **git-derived enforcement is authoritative; the arbiter only decides disposition of a CONFIRMED FAIL** —
  it can never fake a PASS.
- **All external CLIs** run through `compound-v-run-with-timeout.py` with `stdin </dev/null` **and an
  explicit `--max-output-bytes` cap**; evidence sent out is size-capped + secret-redacted.
- **Opt-in & compatibility:** the default (`checkpoint`) epic is **behaviorally unchanged**. New state
  fields are written **only in `marathon` stance**; a `checkpoint`/legacy state is neither read for nor
  mutated with them. Proof: all 34 existing `epic-state.py` selftests pass unchanged **plus** golden
  tests snapshotting the **whole epic dir + `git status`** (not just JSON bytes) after a checkpoint
  `--init`/`--update` — so no stray artifact appears in checkpoint mode.
- **Atomic writes:** every state mutation writes a temp file in the same dir + `os.replace` (never a bare
  `open(...,"w")` a reader can see truncated). *No cross-process lock is needed in v2.10* — the marathon
  is single-process; concurrency (and `fcntl.flock`) is a v2.11 concern.
- **Python 3.9 ISO discipline:** emit `datetime.now(timezone.utc).isoformat()` (`+00:00`, never bare
  `Z`); on ingest normalize a trailing `Z`→`+00:00` before `fromisoformat` (3.9 can't parse `Z`). `--now
  <iso>` injectable for deterministic selftests; CLI default is the real clock.
- **Substrate housekeeping:** arbiter audit JSONs are capped/rotated (owned by the arbiter script) so an
  all-night run can't fill the disk (v2.6.4's flip side).
- Commit every new terminal-point artifact (state, arbiter audit, blocker ledger) at the existing v2.6.4
  commit points. All new scripts `LANG=C`-clean.

## "Survives a fall" — the honest v2.10 boundary (ships in docs)

- **In-session (Level-1 lite):** the marathon loop continues past a soft per-feature error to the next
  runnable feature; a crashed feature is caught by the existing `running`→reconcile path on the next
  `/v:epic` re-entry. Automatic within the live session.
- **Hard death** (quota / servers / app closed): a **human re-invokes `/v:epic <id>`**, which is
  re-entrant and resumes from `epic-state.json` via the existing `/v:resume`. There is **no automatic
  resurrection in v2.10** — that is v2.11. We do NOT claim the epic self-revives while you sleep.
- No fabricated metrics; no overclaim.

## Component 1 — Marathon Loop + relaxed routing (epic-state.py, opt-in) — the "core-contract" unit

- **Schema (marathon stance only):** top-level `"autonomy":{"stance":"marathon","max_features":<int|
  null>,"max_attempts_per_feature":2,"max_no_progress_cycles":3,"max_total_attempts":<int|null>,
  "max_wall_clock_hours":10,"started_at":<iso>}`; per feature `"attempts":0,"last_error":<str|null>,
  "disposition":<obj|null>` (the arbiter's stored verdict — see below). Absent `autonomy` ⇒ every legacy/
  checkpoint path, untouched. All new fields read via `.get(...,default)`.
- **`--next --autonomous` is a SEPARATE function** (`next_feature_autonomous`) — the default
  `next_feature`, its guard order, and all default selftests are byte-for-byte untouched. It is
  **read-only** (like today's `--next`), and routes on **deterministic DAG reachability**, not on a bare
  `failed` status: a feature that is `failed`-and-abandoned or `blocked` removes only its **transitive
  dependents** from the runnable set (reverse reachability over `depends_on`, reusing the `_detect_cycle`
  adjacency idiom); independent pending features stay runnable. It derives `blocked_by:[ids]` read-only
  (Sol-R3#5 — no persisted cascade to reverse later; reopening a source feature simply re-derives). Adds
  a THIRD key `"blocked_by":[ids]`; the default `--next` 2-key shape is unchanged.
- **Terminal states (Sol-R2#5, Sol-R3):** `done` (all done); `done_with_blockers` (every remaining
  feature is a **CONFIRMED** `blocked`, ≥1 done, nothing needs a human) — SUCCESS-with-caveats;
  `blocked_needing_human` (a `halt_epic`, a tripped breaker, OR any **SUSPECTED** blocker needs a person);
  `running_with_failures` (non-terminal, work still runnable). `--next --autonomous` reports which.
- **Abandonment is deterministic, not an arbiter "skip" vote (Sol-R2#8, Sol-R3):** once a feature is
  abandoned (retry cap hit, or arbiter `halt_feature`), the DAG — not a model vote — decides that
  independent features keep running. This removes the unreachable-`write_allowed` structural check
  (per-feature scope maps don't exist at arbitration time) and the redundant `skip_independent`
  disposition.
- **Attempts (crash-safe, single-process):** `--update --status running` increments `attempts` (via
  `f.get("attempts",0)`); a documented transition table defines legal →`running` sources
  (pending/failed→running; done/blocked no). No cross-process attempt-token/generation is needed in
  v2.10 (single process; the existing `running`→reconcile handles a re-entered crash).
  `--can-retry --feature F` → `{can_retry,attempts,cap}`.
- **`--record-disposition --feature F --disposition retry_fix|halt_feature|halt_epic|blocked_external
  --confirmed t|f --families-agreeing gpt,... --reason ...`** stores the arbiter verdict on the feature
  (the contract `--next --autonomous` reads). Atomic write.
- **Acceptance:** default selftests unchanged & green; whole-dir golden compatibility; new selftests:
  autonomous routing continues past an abandoned independent feature but blocks dependents; `blocked_by`
  is correctly derived read-only and re-derives after a source reopens; terminal-state resolution
  (`done`/`done_with_blockers`/`blocked_needing_human`) for a graph where blockers exhaust reachable work;
  `--record-disposition` round-trips and drives `--next --autonomous`; `--can-retry` flips at the cap.

## Component 2 — Cross-Model Arbiter Panel (compound-v-epic-arbiter.py) — Codex + Claude

Decide the disposition of a quality-gate FAILURE. **Family-diverse, degrade-safe.**

- **Panel membership (Sol ×3):** **Codex** (real `--sandbox read-only` kernel boundary) + **in-harness
  Claude** (a fresh adversarial Opus agent). **Antigravity/Cursor are EXCLUDED from arbitration** — they
  lack kernel write-confinement and a disposable worktree cannot prevent out-of-worktree writes/egress of
  the evidence; they remain implementation *workers*, not advisors. Documented as reduced family count.
- **Discovery — capabilities file ONLY** (no availability in `.claude/compound-v.json` since v2.6.2):
  `codex.available && codex.exec_flags_verified`. Absent/malformed ⇒ Codex unavailable ⇒ Claude-only
  fallback.
- **Family (DE-R4):** the arbiter ships a `model_name → family` map (`gpt`→GPT, `gemini`→Gemini,
  `claude|opus|sonnet`→Claude, `grok`→Grok, else `unknown`), keyed on the resolved model name from
  `resolve-model.py`. **One ballot per family** (Sol-R3-med): same-family votes collapse to one ballot;
  within-family disagreement → that family's ballot is the more conservative of its votes. Codex=GPT,
  Claude=Claude ⇒ at most **two** families on this panel, and **Claude-self never counts as an
  independent confirming family** (same family as the implementer → correlated blind spots).
- **Poll:** Codex runs the read-only advisory query through the timeout supervisor (`</dev/null`,
  `--max-output-bytes`), effort **high** (never `xhigh` — that is a codex-only knob but the arbiter uses
  `high` for parity). Read the verdict from the **final `--output-last-message`**, skipping the cosmetic
  `codex_hooks` deprecation event. Evidence (acceptance, gate/reviewer output, diff summary) is
  size-capped + secret-redacted before egress. Claude runs as a fresh adversarial in-harness Task.
- **Verdict schema:** `{"disposition":"retry_fix|halt_feature|halt_epic|blocked_external","reason":
  "<line>","evidence":"<missing external fact, if blocked_external>"}`.
- **Classify always; retry-cap only masks `retry_fix` (Sol-R2#6):** the panel is ALWAYS consulted on a
  failure to classify it (so an exhausted feature can still be recorded `blocked_external`); only the
  `retry_fix` *action* is gated by `--can-retry` (masked to `halt_feature` at the per-feature cap).
  Arbitration is suppressed only if a GLOBAL breaker forbids further model calls.
- **Aggregate (Codex + Claude), parse-safe:** a parse failure / errored backend is **DROPPED + LOGGED**
  (never a fabricated `halt` vote — Sol-R2 / DE-Q2). Of the valid ballots: `retry_fix` vs
  `halt_feature`/`halt_epic` by majority; **empty or tied → conservative `halt_feature`** (abandon this
  feature safely; the DAG then continues independents — no whole-epic halt unless nothing is reachable).
- **`blocked_external` confirmation (the ≥2-family bar):** CONFIRMED only if **≥2 distinct KNOWN
  families** agree with no `retry_fix` dissent. On the Codex+Claude panel that bar is **not reachable**
  (only Codex is a distinct external family; Claude-self can't confirm) — so in v2.10 a `blocked_external`
  is always **SUSPECTED**: the feature is isolated (status `blocked`, epic keeps building the rest) but
  flagged UNCONFIRMED, and its presence resolves the epic to `blocked_needing_human` for a human to
  verify. Honest limitation: confirmed auto-blocking needs a 2nd safe external family (a v-future backend).
- **Claude-only fallback** (Codex absent): a single fresh adversarial Opus agent, capped to `retry_fix`
  or `halt_feature` — never `halt_epic`-by-itself-silently, never CONFIRM a blocker. Honesty line ships:
  *without a cross-model backend the arbiter adds ≈no independent signal over checkpoint.*
- **Audit trail:** record every ballot + resolved family under `docs/superpowers/execution/epics/<id>/
  arbiter/<feature>-<n>.json` — validate `epic_id` (add `_id_ok` to `build_state`), derive the audit root
  from the contained state path with realpath containment, write atomically, cap/rotate to bound growth.
- **Acceptance:** fixture capabilities + fake supervisor: Codex+Claude ballots aggregate with one-per-
  family collapse; a garbled Codex reply is DROPPED (not a halt vote) + logged; empty/tied → halt_feature;
  a `blocked_external` on this panel is SUSPECTED → `blocked_needing_human`; `retry_fix` past cap →
  halt_feature; classify still runs at the cap; Codex-absent → Claude-only capped path; audit path rejects
  a traversal `epic_id`. `--selftest`, `LANG=C`-clean.

## Component 3 — Blocker Ledger + end-of-epic human report (epic-state.py; the "do everything you can" credo)

Finish everything in your power; isolate only the genuinely impossible; escalate with proof; never halt
the rest.

- **State:** `blocker_ledger:[{feature,confirmed:bool,reason,evidence,families_agreeing:[...],
  first_seen_at,blocks:[derived dependent ids]}]`; the feature gets status `blocked`.
- **`--update --status blocked --feature F --blocker-reason ... --blocker-confirmed t|f
  --families-agreeing ...`** appends the entry. `--next --autonomous` treats `blocked` as a benign skip
  (only transitive dependents drop out, read-only-derived); it never trips a whole-epic halt.
- **Confirmed vs suspected (Sol-R3#4):** CONFIRMED (≥2 known families) → contributes to
  `done_with_blockers` (success-with-caveats). SUSPECTED (single family — the v2.10 default) → still
  isolated so the epic keeps building, but resolves the terminal status to **`blocked_needing_human`** so
  a person verifies it. The 2-family bar is thus meaningful, not cosmetic.
- **Two-point discovery:** a blocker can surface in **pre-flight research** (1B/1C) or mid-
  **implementation** (a worker hits it, like astrology #150). Both funnel through the arbiter's
  confirmation logic before `confirmed:true`.
- **End-of-epic report** leads with the ledger, visually separated from `failed`: "Built everything
  reachable. **N feature(s) need YOU** — a human/external action, because code can't create data that
  doesn't exist upstream:" per entry: feature, reason, the missing external fact, families that agreed
  (or "single-model SUSPICION"), what it transitively blocked. Resolving a blocker = human re-run of
  `/v:epic <id>` after `--update --status pending --feature F` (dependents re-derive read-only).
- **Acceptance:** a `blocked` feature isolates dependents not independents; `--next --autonomous` advances
  past it; single-family → `confirmed:false` → `blocked_needing_human`; ≥2 families → `confirmed:true` →
  `done_with_blockers`; ledger round-trips through `--update`/`--summary`; `--stats` breaks out `blocked`;
  report names the missing fact + agreeing families, never fabricates.

## Component 4 — Global Circuit Breakers (epic-state.py — enforced in the SCRIPT, DE-R1)

Local caps never bound the system; the breaker lives in the deterministic script.

- **Counters (marathon state):** `total_attempts` (sum of feature attempts), `no_progress_cycles`
  (incremented when a full `--next --autonomous` pass advances the `done` count by zero; **reset to 0** on
  any feature reaching `done`), wall-clock from `autonomy.started_at` vs `--now`.
- **Read/trip split (Sol-R3#6):** `--breaker-check --state S --now T` is **read-only** →
  `{tripped,which:[...],detail}`. A separate **`--trip-breaker --state S --now T`** atomically writes the
  epic to `blocked_needing_human` when a check trips. The driver calls check before each feature and trips
  on a positive. Trips on: `total_attempts>=max_total_attempts` (default `max(6,3×features)`),
  `no_progress_cycles>=max_no_progress_cycles` (3), wall-clock`>=max_wall_clock_hours` (10). **Counts and
  hours only — never a fabricated cost.**
- **Acceptance:** each breaker trips at its boundary and not before; `no_progress_cycles` resets on a
  `done`; `--breaker-check` never mutates; `--trip-breaker` atomically sets `blocked_needing_human`;
  boundary/`null`/negative config validated (a `null` cap = unbounded on that axis only if explicitly
  set, with a loud log).

## Component 5 — Driver wiring + halt-page runbook + PASS integrity (v-epic.md, epic-mode.md, v-init.md)

- **Autonomous path** (when `.claude/compound-v.json` `epic.autonomous.stance=="marathon"` or
  `--autonomous`): loop with `--next --autonomous`, `--breaker-check` before each feature; on a feature
  FAILURE consult the Arbiter Panel, `--record-disposition`, act under the breaker (retry_fix re-runs;
  halt_feature abandons → DAG continues independents; blocked_external → ledger); on terminal status
  report. Default (checkpoint) path unchanged; split any `&&` git chains touched (Sol-R2#9); acceptance =
  "behaviorally unchanged", not "textually additive".
- **PASS integrity (DE-R5):** the Review Gate gains an **anti-reward-hacking** check — did the diff weaken
  its own tests/scorers to pass? Marathon **sample-audits** a fraction of PASSes and runs a **final
  cross-feature re-verification** before `done` (guards silent regression of earlier features).
- **Halt-page = runbook (DE-Q4):** page ONLY on a whole-epic block (`blocked_needing_human` or tripped
  breaker); `blocked`/abandoned-feature notices batch into the end-of-epic report, not mid-run pages. The
  page contains: the feature + blocked dependents; which acceptance criterion failed + gate verdicts +
  failing-diff summary; every panel ballot + reason + resolved family + why it aggregated; breaker state
  (n/cap); a copy-paste `/v:resume <run-id>` + the override path; paths to arbiter JSON / run-dir / diff.
  Counts only.
- **`/v:init`** Step 3 writes `epic.autonomous.stance` (default `checkpoint`; offer `marathon` with the
  honest v2.10 boundary — in-session + human resume, no auto-revive — and the breaker caps).
- **Acceptance:** spec-reviewer confirms the default path is behaviorally unchanged; honesty boundary
  present; halt-page contains every runbook field; the fail-fast prose in all three docs is *scoped to
  checkpoint stance*, not deleted; no fabricated metrics.

## Component 6 — README + docs + CI (LAST — only after 1–5 are real & reviewed)

- README "Main features": a **Marathon Loop · Arbiter Panel · Blocker Ledger · Global Breakers**
  subsection with the honest v2.10 boundary inline (in-session autonomy + human resume; auto-resurrection
  is "coming in v2.11").
- **CI (Sol#10):** add the two new `--selftest`s (epic-state, arbiter) to `.github/workflows/validate.yml`,
  run under **Python 3.9** (the floor) plus the normal version; add malformed-state / disposition-round-
  trip fixtures.
- `CHANGELOG.md` + `.claude-plugin/{plugin,marketplace}.json` bump 2.9.0 → 2.10.0.
- **Acceptance:** every README claim maps to a shipped, tested component; the honesty caveats present; CI
  runs the new selftests under Py3.9 and is green; version bumped.

## Feature DAG + disjoint partition (v2.10)

```
A CORE CONTRACT  (scripts/compound-v-epic-state.py — Components 1,3,4: autonomy, --next --autonomous,   deps: []
                  attempts, --record-disposition, blocker_ledger, terminal states, breakers, Py3.9 ISO.
                  ONE serial unit = the WHOLE file. Publishes its state/CLI contract before B & C.)
B arbiter-panel  (scripts/compound-v-epic-arbiter.py — new; Codex+Claude, family map, cap/rotate audit)  deps: [A]
C driver+integrity(commands/v-epic.md, skills/compound-v/epic-mode.md, commands/v-init.md)                deps: [A,B]
D docs + CI + rel(README.md, CHANGELOG.md, .claude-plugin/{plugin,marketplace}.json, validate.yml)        deps: [C]
```

Disjoint writes — the **entire `compound-v-epic-state.py` is ONE serial unit A** (Components 1, 3, 4 —
not split by number, which would collide). **A publishes its state-JSON + CLI contract before B/C.** B is
a new file. `resolve-model.py` is NOT edited (the family map lives in B). C = 3 prose files. D = README/
CHANGELOG/2 manifests/workflow. No two units write the same file. Plugin manifests are CLEAN. No
`agents/parallel-dispatcher.md` / `backend-launcher` edits — those were only needed for v2.11 fencing.

## Chosen defaults (documented, tunable in `/v:init`)

- Global-breaker defaults: `max_wall_clock_hours=10`, `max_total_attempts=max(6,3×features)`,
  `max_no_progress_cycles=3` — tunable.
- Arbiter panel = Codex + Claude; agy/cursor excluded from arbitration (workers only).
- `blocked_external` in v2.10 is always SUSPECTED (→ human verify) — confirmed auto-blocking awaits a 2nd
  safe external family.
- Single-backend (no Codex): marathon still offered with the "≈no independent signal" honesty notice.

## v2.11 — Auto-Resurrection (DEFERRED, its own spec + review pass)

The "survives while you sleep" layer, split out because it needs correct distributed concurrency:
- **Execution Lease:** `fcntl.flock`-guarded (reuse `compound-v-memory.py:542`) single atomic
  `--claim-stale` (check-terminality-and-expiry-and-acquire in one locked txn — never acquire-then-
  recheck), owner+`generation` fencing, renewable heartbeat.
- **Two-Tier Watcher:** session `CronCreate` (Level-1; 7-day expiry, dies on sleep/`CLAUDE_CODE_DISABLE_
  CRON`) + on-disk `scheduled-tasks` (Level-2; next-launch catch-up). Persist watcher records (provider,
  task id, generation, timestamps) for idempotent arm/disarm.
- **Generation-fenced execution layer (the hard part, Sol-R3#1/#2):** thread owner+generation through the
  dispatcher / worker / merge-back / commit; an executable heartbeat helper renews during long phases;
  re-validate the lease before git-apply, before each commit, before terminal publish; reject stale
  completions; force all marathon jobs into worktrees. Honest guarantee: "a superseded driver's work is
  rejected at the fenced merge boundary", never "two drivers never run simultaneously".
- **Honesty boundary** (Level-1/Level-2/headless, sleep/quota/auth/7-day/disable-cron) from the earlier
  draft applies here.

## Review provenance

Converged from four independent pre-implementation reviews + three Codex Sol xhigh adversarial rounds on
2026-07-12. The Sol rounds drove the scope decision: R1/R2/R3 each surfaced fresh *critical* concurrency
defects in the auto-watcher, converging on "phase it". Audit docs under `docs/superpowers/expert/` and
`docs/superpowers/research/`; the raw Sol findings in the run history.
