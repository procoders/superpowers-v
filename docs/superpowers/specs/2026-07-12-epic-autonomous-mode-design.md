# Epic Autonomous Mode — "Marathon Loop" Design Spec (converged v2)

> **Status:** design, pre-implementation. Branch `epic-autonomous-mode`. Converged against 4 independent
> reviews (code-archaeology · doc-validator[live-probed] · domain-expert[research-grounded] · Codex Sol
> xhigh adversarial). Findings folded in; see "Review provenance" at the end.
> **For agentic workers:** feeds `superpowers:writing-plans`. Terminology (Marathon Loop · Execution
> Lease · Two-Tier Watcher · Arbiter Panel · Blocker Ledger · Global Breakers) is the vocabulary the
> README will use *once the mechanism exists* — do NOT write README marketing copy for unbuilt parts.

**Goal:** make `/v:epic` optionally run as a self-sustaining marathon — chew through its feature DAG
without stopping at every feature, survive interruptions without ever double-executing, decide what to
do about a failed feature via a family-diverse cross-model arbiter panel, isolate (not halt on)
fundamental external blockers, and stay bounded by hard global circuit breakers — all **opt-in**, so the
default epic behaves exactly as cautiously as today.

**Architecture (one line each):** A **Marathon Loop** raises the per-invocation feature budget and, in
autonomous mode, relaxes fail-fast so a failed feature blocks only its *dependents*. An **Execution
Lease** (fencing token + renewable heartbeat, atomic state writes) prevents two watcher tiers from ever
running the same run concurrently. A **Two-Tier Watcher** (session `CronCreate` + on-disk
`scheduled-tasks`) resurrects a *genuinely* dead run — only after atomically acquiring an expired lease.
An **Arbiter Panel** polls every available cross-model backend (deduped by model *family*) for a
disposition on a failed feature; a **Blocker Ledger** carves out fundamental external blockers without
halting the rest; **Global Breakers** (total attempts / resume count / wall-clock dead-man) bound the
whole run in the script itself.

**Tech Stack:** Python 3.9-safe stdlib (extends `scripts/compound-v-epic-state.py`); new
`scripts/compound-v-epic-arbiter.py`, `scripts/compound-v-epic-watch.py`; prose
(`skills/compound-v/epic-mode.md`, `commands/v-epic.md`, `commands/v-init.md`); `README.md`,
`CHANGELOG.md`, `.claude-plugin/*.json`; `.github/workflows/validate.yml` (wire the new selftests).
Reuses: `compound-v-run-with-timeout.py` (all external calls, `</dev/null`, `--max-output-bytes`),
`compound-v-resolve-model.py` (per-backend model + family), `~/.claude/compound-v-capabilities.json`
(the ONLY availability source), `compound-v-liveness.py` (per-JOB probe — cross-referenced, not merged).

## Global Constraints

- **Opus by default; Sonnet only for the junior-mechanical carve-out; NEVER Haiku** (lint + CI enforced).
- **No fabricated cost/token metrics** — breakers bound *counts and wall-clock*, never invented dollars.
- **Two-command commit discipline** — never chain side-effecting git with `&&`; check each exit code.
  (F5 must also split any pre-existing `&&` git chains it finds in `v-epic.md`.)
- **git-derived enforcement is authoritative; the arbiter only decides disposition of a CONFIRMED FAIL**
  — it can never fake a PASS. The scope-gate + Review Gate verdicts stay the source of truth.
- **All external CLIs** run through `compound-v-run-with-timeout.py` with `stdin </dev/null` **and an
  explicit `--max-output-bytes` cap**; evidence sent out is size-capped + secret-redacted.
- **Opt-in & compatibility:** the default (`checkpoint`) epic is **behaviorally unchanged**. New state
  fields (`autonomy`, `attempts`, `lease`, `last_progress_at`, `blocker_ledger`, breaker counters) are
  **written only in `marathon` stance**; a `checkpoint`/legacy state is neither read for nor mutated
  with them. Proof obligation: all 34 existing `epic-state.py` selftests pass unchanged **plus**
  golden-file tests asserting checkpoint `--init`/`--update` produce byte-identical output to today.
  ("Behavioral compatibility", not the earlier over-strong "byte-for-byte in all paths".)
- **Atomic, serialized state writes:** every mutation writes a temp file + `os.replace` (never a bare
  `open(...,"w")` that a concurrent reader can observe truncated). All new scripts `LANG=C`-clean
  (reconfigure stdout/stderr to UTF-8).
- **Python 3.9 ISO discipline:** emit timestamps as `datetime.now(timezone.utc).isoformat()` (→ `+00:00`
  form, never bare `Z`); on ingest, normalize a trailing `Z`→`+00:00` before `fromisoformat` (3.9 can't
  parse `Z`). `--now <iso>` is injectable for deterministic selftests; CLI default is the real clock.
- Commit every new terminal-point artifact (disarmed lease/state, arbiter audit JSON, blocker ledger) at
  the existing v2.6.4 commit points or `finishing-a-development-branch` cleanup erases it.

## The two-level failure model (honesty boundary — ships in the docs verbatim, corrected & expanded)

"Epic survives a fall" means precisely:

- **Level 1 — soft stall in a live session.** The session `CronCreate` watcher fires while the REPL is
  idle and (after acquiring an expired lease) re-enters `/v:epic <id>`. Fully automatic. **Caveats:**
  `CronCreate` is **session-scoped by construction** (no durability parameter); unexpired tasks are
  restored only on an explicit `--resume`/`--continue`, and **recurring tasks self-expire 7 days after
  creation** — a marathon running >7 days loses Tier-1 and must lean on Tier-2. If
  `CLAUDE_CODE_DISABLE_CRON=1` is set, Tier-1 never arms — the driver detects this and announces
  Tier-2-only. **Laptop sleep silently suspends Tier-1** (it is in-memory).
- **Level 2 — hard death** (quota exhausted, servers down, app closed). The on-disk `scheduled-tasks`
  watcher re-fires the self-contained resume prompt: "while the app is open, or **one catch-up run on
  next launch**" — NOT a truly always-on server. Survives app close; a sleep-through is skipped then
  gets one catch-up on wake. **"Survives quota exhaustion" holds only if the quota has reset AND the
  session is still authenticated** — an expired OAuth token does not self-heal on relaunch and needs a
  human.
- **Truly headless** (zero local process, laptop closed/asleep): out of scope; needs an OS `launchd`/cron
  shim that relaunches Claude Code — documented as an optional user-side add-on, never claimed built-in.

## Component 1 — Marathon Loop + relaxed routing (epic-state.py, opt-in)

- **Schema (marathon stance only):** top-level `"autonomy": {"stance":"marathon", "max_features":<int|
  null>, "max_attempts_per_feature":2, "max_no_progress_cycles":3, "max_total_attempts":<int|null>,
  "max_resume_count":30, "max_wall_clock_hours":10, "started_at":<iso>}`. Per feature:
  `"attempts":0, "last_error":<str|null>`. Absent `autonomy` ⇒ every legacy/checkpoint path, untouched.
- **`--next --autonomous` is a SEPARATE function** (`next_feature_autonomous`), selected at the
  `want_next` branch — the default `next_feature`, its load-bearing guard order, and all default
  selftests are byte-for-byte untouched. It relaxes fail-fast: a `failed`/`blocked` feature blocks only
  its **transitive dependents** (reuse the `_detect_cycle` adjacency-build idiom for reverse
  reachability); independent pending features stay runnable. Returns the 2-key `{feature,reason}` plus a
  THIRD key `"blocked_by_failure":[ids]` (default `--next` shape unchanged).
- **Terminal-state fix (Sol#3):** decouple watcher terminality from the failed-roll-up. Epic status
  gains `running_with_failures` (work still runnable despite ≥1 failed/blocked) vs `blocked_needing_human`
  (no runnable work AND a failure needs a human). The watcher disarms ONLY on a truly terminal status
  (`done` or `blocked_needing_human`), never on the first failure.
- **Idempotent retry accounting (Sol#7, DE-R2):** `attempts` increments **only** on a valid
  non-running→`running` transition, keyed by a unique **attempt token** minted at that transition;
  replaying `--update --status running` with the same token is a no-op (watcher re-entry / crash-resume
  can't inflate the count). `--can-retry --feature F` → `{can_retry, attempts, cap}` using
  `f.get("attempts",0)` and `autonomy.get("max_attempts_per_feature",2)`.
- **Acceptance:** default selftests unchanged & green; golden-file checkpoint compatibility; new
  selftests: autonomous routing skips an independent failure but blocks dependents; attempt-token makes
  a replayed `running` idempotent; `--can-retry` flips at the cap; `running_with_failures` keeps
  `--next --autonomous` productive while `blocked_needing_human` is terminal.

## Component 2 — Execution Lease + Heartbeat (epic-state.py — the concurrency spine)

The single most important correction: a bare `last_progress_at` is **not** a heartbeat — a feature can
spend >45 min in pre-flights/dispatch/review with no state mutation, and a naive watcher would resurrect
a *live* run (double execution). Replace it with a real lease.

- **`lease` (top-level):** `{"owner":"<uuid minted per driver invocation>", "pid":<int>, "generation":
  <int, bumped each acquire>, "acquired_at":<iso>, "renewed_at":<iso>, "expires_at":<iso>}`. The driver
  **renews** it (bumps `renewed_at`/`expires_at`, default TTL 15 min) at every step boundary AND on a
  cheap timer during long phases — so a healthy long wave keeps the lease alive without a feature-status
  change. `last_progress_at` remains, but only as *human-facing progress*, never as the liveness gate.
- **`--acquire-lease --owner U --pid P --now T [--ttl-min 15]`** → succeeds and writes the lease (atomic)
  **only if** no lease exists OR the existing lease is expired (`expires_at < now`) — a **fencing**
  acquire. Prints `{"acquired":bool, "generation":n, "held_by":<owner|null>}`. `--renew-lease`,
  `--release-lease` mirror it. A resume/update carrying a stale `generation` is rejected (fencing).
- **`--liveness --state S --now T [--stale-after-min 45]`** → `{alive, stale, held, lease_expired,
  age_min, epic_status}`. `stale` now means **lease expired on an incomplete epic**, not "timestamp
  old". This is what the watcher polls. Cross-references `compound-v-liveness.py` (per-JOB hang probe) in
  the docstring — different granularity, deliberately separate, mirrors its `--json`/exit-3/`--selftest`
  conventions.
- **Acceptance:** two concurrent `--acquire-lease` — exactly one wins; an expired lease is acquirable and
  bumps `generation`; a stale-generation `--renew`/update is rejected; a live-lease epic is never
  `stale`; selftest simulates "long wave, no status change, lease renewed → not stale" (the exact
  false-resurrection case) and "resume dies before renew → lease expires → next watcher acquires".

## Component 3 — Two-Tier Watcher (compound-v-epic-watch.py + prose)

Emits the watcher prompt and advises tiers; the driver makes the actual harness scheduling calls.

- `emit-prompt --epic-id E --state S` → the **self-contained** resume prompt used by BOTH tiers:
  *acquire an expired lease (no-op & exit if a live lease is held) → check liveness → resume only if
  stale → on resume, increment the **resume-attempt counter BEFORE any work**, apply exponential backoff
  + jitter, self-disarm after `max_no_progress_cycles` non-progressing fires → stop+disarm if
  `done`/`blocked_needing_human` or any global breaker tripped*. Fully self-contained per the
  `scheduled-tasks` contract.
- `plan --state S --now T` → `{tier1:{cron, disarm:bool}, tier2:{cadence, disarm:bool},
  disable_cron_detected:bool}`. Disarms only on truly-terminal status. Off-minute jittered cadence
  (:17/:47). Reports if `CLAUDE_CODE_DISABLE_CRON` is set (→ Tier-2 only). Notes the 7-day Tier-1
  expiry so the driver re-arms before it, or documents Tier-2 as the >7-day net.
- The driver arms Tier-1 via `CronCreate`, Tier-2 via `mcp__scheduled-tasks__create_scheduled_task`, and
  disarms both (`CronDelete` + `delete_scheduled_task`) at terminal points, co-located with the v2.6.4
  commits.
- **Acceptance:** `emit-prompt` is self-contained (epic-id, state path, lease-acquire-first, resume/
  disarm conditions, model/commit constraints) with no conversation-relative refs; a live-lease state
  yields a no-op prompt path; `plan` returns disarm only for terminal status and surfaces
  `disable_cron_detected`; the resume-attempt backoff self-disarms after K empties. `--selftest`.

## Component 4 — Cross-Model Arbiter Panel (compound-v-epic-arbiter.py)

Decide the disposition of a quality-gate FAILURE. **Family-diverse, degrade-safe, never a hard
dependency on any one backend.**

- **Discovery — capabilities file ONLY** (`.claude/compound-v.json` carries no availability since
  v2.6.2). Composite gates: `codex.available && codex.exec_flags_verified`; `antigravity.available`;
  `cursor.available && cursor.authenticated`. Absent/malformed file ⇒ zero backends ⇒ Claude fallback.
- **Family de-dup (DE-R4):** resolve each backend→model→**family** via `compound-v-resolve-model.py`
  (codex→GPT, antigravity→Gemini, cursor→whatever the user configured — could be GPT). Two same-family
  votes count as correlated, NOT independent.
- **Poll:** each available backend runs a **read-only advisory** query through the timeout supervisor
  (`</dev/null`, `--max-output-bytes`), **in a throwaway git worktree** (contains blast radius: only
  Codex's `--sandbox read-only` is a *kernel* boundary; agy/cursor are prompt-restricted — the honest
  label — but a disposable worktree bounds their filesystem reach and the scope gate catches stray
  writes). Non-codex backends get effort `high` (never `xhigh` — codex-only). For codex `--json`, read
  the verdict from the **final `--output-last-message`**, skipping the cosmetic `codex_hooks`
  deprecation event. Evidence (acceptance, gate/reviewer output, diff summary) is size-capped +
  secret-redacted before egress.
- **Verdict schema:** `{"disposition":"retry_fix|skip_independent|halt|blocked_external",
  "reason":"<line>", "evidence":"<missing external fact, if blocked_external>"}`.
- **Aggregate — asymmetric, family-aware, and parse-safe:**
  - **Parse failure / errored backend → DROP + LOG** (like an absent backend) — never counted as a
    `halt` vote (that would fabricate a vote and let one flaky backend silently revert marathon to
    checkpoint). The conservative default applies only to the aggregate of *valid* votes.
  - `retry_fix` vs `halt`: majority of valid votes; **empty or tied → conservative `halt`**.
  - `skip_independent`: the highest bar — **unanimity across ≥2 distinct families** AND a structural
    check (the feature shares no `write_allowed` files / no DAG edge with in-flight work). A bare
    majority authorizes at most `retry_fix`. (It is the only disposition whose wrong call compounds
    unattended.)
  - `blocked_external`: **≥2 distinct families agree, none dissenting `retry_fix`** → CONFIRMED. Any
    `retry_fix` dissent → route to `retry_fix` (someone thinks it's doable). <2 families ⇒ SUSPECTED
    (isolated so the epic continues, but flagged UNCONFIRMED / needs-human-verify).
  - Record every panel member's raw verdict + resolved family for the audit trail — never fabricate a
    vote. Audit path: validate `epic_id` (add `_id_ok` to `build_state`), derive the audit root from the
    contained state path with realpath containment, write atomically with a collision-safe invocation id.
- **Breaker interaction:** consulted only if `--can-retry` is true and no global breaker is tripped; a
  `retry_fix` past any cap is downgraded to `halt`. The breaker always wins.
- **Claude-only fallback:** a separate fresh-context adversarial Opus agent ("default to `halt`; justify
  any `retry_fix`"). It may return only `halt` or `retry_fix` — **never `skip_independent`, never
  CONFIRM a `blocked_external`** (same-family self-judgment can't clear those bars). Honesty line ships:
  *without a cross-model backend, the arbiter adds ≈no autonomy over checkpoint.*
- **Acceptance:** fixture capabilities (3 backends) + fake supervisor: 3 valid votes aggregate with
  family de-dup; two same-family votes don't outweigh a third family for `skip_independent`; a garbled
  reply is DROPPED (not a halt vote) and logged; empty/tied → halt; `blocked_external` needs ≥2 families;
  `retry_fix` past cap → halt; zero-backend path emits a well-formed adversarial Claude prompt capped to
  halt/retry_fix; audit path rejects a traversal `epic_id`. `--selftest`, `LANG=C`-clean.

## Component 4b — Blocker Ledger + end-of-epic human report (the "do everything you can" credo)

Finish everything in your power; isolate ONLY the genuinely impossible; escalate it — with multi-model
proof — without halting the rest. A fundamental external blocker is a *fact about the world*, not a
quality failure or a choice.

- **State:** `blocker_ledger:[{feature, confirmed:bool, reason, evidence, families_agreeing:[...],
  first_seen_at, blocks:[dependent ids]}]`; the feature gets status `blocked` (distinct from `failed`).
- **`--update --status blocked --feature F --blocker-reason ... --blocker-confirmed t|f
  --families-agreeing gpt,gemini`** appends the entry.
- **`--next --autonomous` treats `blocked` as a benign skip** — only transitive dependents become
  `blocked` (ledger-linked "blocked upstream: F"); independents stay runnable. `blocked` never trips
  fail-fast; the epic runs to completion on everything reachable. (`failed` past the retry cap →
  `blocked_needing_human`; `blocked` = "world lacks the data" and does NOT page mid-run.)
- **Two-point discovery:** a blocker can surface in **pre-flight research** (1B/1C find "upstream API
  has no such field") or mid-**implementation** (a worker hits it, like #150). Both funnel through the
  SAME ≥2-family arbiter confirmation before `confirmed:true`; a lone pre-flight suspicion is SUSPECTED.
- **End-of-epic report** leads with the ledger, visually separated from `failed`: "Built everything
  reachable. **N feature(s) need YOU** — a human/external action, because code can't create data that
  doesn't exist upstream:" per entry: feature, one-line reason, the missing external fact, families that
  agreed (or "single-model SUSPICION"), what it transitively blocked. A `blocked`-only epic is a
  SUCCESS-with-caveats, not a failure; `--stats` counts `blocked` separately.
- **Acceptance:** confirmed `blocked_external` isolates dependents not independents; `--next
  --autonomous` advances past a `blocked` feature; single-family proposal → `confirmed:false`; ledger
  round-trips through `--update`/`--summary`; `--stats` breaks out `blocked`; report names the missing
  fact + agreeing families, never fabricates, never confirms on Claude-self alone.

## Component 4c — Global Circuit Breakers (epic-state.py — enforced in the SCRIPT, DE-R1/R2)

Local caps never bound the system; a looping agent can't be trusted to stop itself, so the breaker lives
in the deterministic script, not the driver prose.

- **Counters (marathon state):** `total_attempts` (sum of all feature attempts), `resume_count`
  (incremented at every watcher resume START, before work — closes crash-before-heartbeat),
  `no_progress_cycles` (incremented on a resume that advances the `done` count by zero; **reset to 0** on
  any feature reaching `done`), and wall-clock derived from `autonomy.started_at` vs `--now`.
- **`--breaker-check --state S --now T`** → `{tripped:bool, which:[...], detail}`. Trips on any of:
  `total_attempts >= max_total_attempts` (default = `max(6, 3×feature_count)`), `resume_count >=
  max_resume_count` (30), `no_progress_cycles >= max_no_progress_cycles` (3), wall-clock >=
  `max_wall_clock_hours` (10). A tripped breaker forces the epic to `blocked_needing_human`, disarms both
  watchers, and pages the human. **Counts and hours only — never a fabricated cost.**
- **Acceptance:** each breaker trips at its boundary and not before; `no_progress_cycles` resets on a
  `done`; a resume that dies before any work still bumps `resume_count` (so the dead-man eventually
  fires); a tripped breaker yields `blocked_needing_human` + disarm; boundary/`null`/negative config is
  validated (a `null` cap = "unbounded for that axis" only if explicitly set, with a loud log).

## Component 5 — Driver wiring + halt-page runbook + PASS integrity (v-epic.md, epic-mode.md, v-init.md)

- **Autonomous path** (when `.claude/compound-v.json` `epic.autonomous.stance=="marathon"` or
  `--autonomous`): acquire the lease → arm the Two-Tier Watcher → loop with `--next --autonomous`,
  renewing the lease each step and `--breaker-check` before each feature → on FAILURE consult the Arbiter
  Panel and act under the breaker → bump `last_progress_at` → on terminal status disarm both watchers,
  release the lease, and report. Default (checkpoint) path unchanged; F5 also splits any existing `&&`
  git chains it touches (Sol#9) — acceptance is "behaviorally unchanged", not "textually additive".
- **PASS integrity (DE-R5):** the Review Gate gains an **anti-reward-hacking** check — did the diff weaken
  its own tests/scorers to pass? Marathon **sample-audits** a fraction of PASSes and runs a **final
  cross-feature re-verification** before `done` (guards silent regression of earlier features).
- **Halt-page = runbook (DE-Q4):** page ONLY on whole-epic block (`blocked_needing_human` or tripped
  breaker); park-notices for `blocked`/`skip_independent` features batch into the end-of-epic report, not
  mid-run pages. The page contains: the feature + blocked dependents; which acceptance criterion failed +
  gate verdicts + failing-diff summary; every panel member's raw verdict + reason + resolved family + why
  it aggregated as it did; breaker state (n/cap); a copy-paste `/v:resume <run-id>` + the override path;
  paths to arbiter JSON / run-dir / worktree / diff. Counts only, no fabricated cost.
- **`/v:init`** Step 3 writes `epic.autonomous.stance` (default `checkpoint`; offer `marathon` with the
  honest Level-1/2 + sleep/quota/auth caveats, the breaker caps, and — for a single-backend user — the
  "≈no autonomy over checkpoint" notice) and detects `CLAUDE_CODE_DISABLE_CRON`.
- **Acceptance:** spec-reviewer confirms the default path is behaviorally unchanged; honesty boundary
  present verbatim; halt-page contains every runbook field; the fail-fast prose in all three docs is
  *scoped to checkpoint stance*, not deleted; no fabricated metrics.

## Component 6 — README + docs + CI wiring (LAST — only after 1–5 are real & reviewed)

- README "Main features": a **Marathon Loop · Execution Lease · Two-Tier Watcher · Arbiter Panel ·
  Blocker Ledger** subsection with the honest Level-1/2/headless + sleep/quota caveats inline.
- **CI (Sol#10):** add the three new `--selftest`s (epic-state, arbiter, watch) to
  `.github/workflows/validate.yml`, run under **Python 3.9** (the floor) in addition to the normal
  version; add malformed-state / concurrent-lease / replayed-transition fixtures. F6 owns the workflow
  file so "CI green" actually exercises new behavior.
- `CHANGELOG.md` + `.claude-plugin/{plugin,marketplace}.json` bump 2.9.0 → 2.10.0.
- **Substrate housekeeping (DE-Q5):** document/implement bounded growth — arbiter JSONs and throwaway
  worktrees are cleaned or capped so an all-night run can't fill the disk (v2.6.4's flip side).
- **Acceptance:** every README claim maps to a shipped, tested component; the honesty caveats are
  present; CI runs the new selftests under Py3.9 and is green; version bumped.

## Feature DAG + disjoint partition

```
F1 marathon-loop + breakers  (epic-state.py: autonomy, --next --autonomous, attempts/token, breakers)  deps: []
F2 lease + heartbeat         (epic-state.py: lease/fencing, --liveness, atomic writes, Py3.9 ISO)        deps: [F1]
F4 arbiter-panel             (compound-v-epic-arbiter.py)                                                deps: [F1]
F3 watcher                   (compound-v-epic-watch.py)                                                  deps: [F2]
F5 driver + review-integrity (v-epic.md, epic-mode.md, v-init.md)                                        deps: [F1,F2,F3,F4]
F6 docs + CI + release       (README, CHANGELOG, plugin/marketplace json, validate.yml)                  deps: [F5]
```

Disjoint writes — **F1 & F2 both edit `scripts/compound-v-epic-state.py`, so they are ONE serial
dispatch unit, not parallel** (the disjoint-write invariant). F4/F3 are new files (parallel-safe). F5 =
3 prose files. F6 = README/CHANGELOG/2 manifests/workflow. No two units write the same file. The plugin
manifests are currently CLEAN (the session-start `M` was committed in the v2.9 flow) — no dirty-tree
hazard.

## Chosen defaults for the escalated open questions (documented, tunable in `/v:init`)

- **>7-day marathon:** in scope via Tier-2 as the durable net; Tier-1 re-arms opportunistically each
  resume, and the driver re-arms before the 7-day expiry when a run is still live.
- **`CLAUDE_CODE_DISABLE_CRON=1`:** driver **warns + falls back to Tier-2 only** (does not hard-fail).
- **Global-breaker defaults:** `max_wall_clock_hours=10`, `max_resume_count=30`,
  `max_total_attempts=max(6, 3×features)`, `max_no_progress_cycles=3` — all tunable.
- **`skip_independent` automatic?** Yes, but only under the highest bar (unanimity across ≥2 families +
  no-shared-files structural check); otherwise → `retry_fix`.
- **Single-backend users:** marathon is still offered, with the explicit "≈no autonomy over checkpoint"
  honesty notice; Claude-self fallback is capped to halt/retry_fix.
- **PASS-audit sample rate + paging quiet-hours:** sensible defaults (audit ~all cross-feature seams +
  a sample of intra-feature PASSes; page only on whole-epic block), tunable later.

## Honesty boundary (state to the user; ship in docs)

- Marathon mode is **opt-in**; the default epic is unchanged and still checkpoints for a human.
- "Survives a fall" = Level-1 fully auto (but Tier-1 dies on sleep / 7-day expiry / disable-cron),
  Level-2 semi (resurrects on next launch, only if quota reset AND still authed), truly-headless needs an
  OS shim. No pretending session-cron is server-cron.
- The Arbiter Panel is **advisory disposition of a confirmed failure**; the git-derived gate + the
  Execution Lease + the Global Breakers are the deterministic guardrails it cannot override. Claude-self
  is weaker than a family-diverse panel — the **breakers, not the arbiter, are the safety net**, and
  without a second model family the arbiter adds ≈no autonomy.
- `blocked_external` needs ≥2 model families to CONFIRM; a single model can only SUSPECT.
- No fabricated metrics; the arbiter never invents a vote for an absent/errored backend.

## Review provenance

Converged from four independent pre-implementation reviews on 2026-07-12: code-archaeology (grounded
insertion points + the pre-existing `compound-v-liveness.py` distinction + capabilities-file discovery
correction), doc-validator (live-probed scheduler semantics, `codex exec` read-only, agy/cursor headless,
Py3.9 ISO gotcha), domain-expert (research-grounded R1 global-breaker, R2 crash-before-heartbeat, R3
thundering-resume, R4 family-correlated votes, R5 reward-hacked PASS), and Codex Sol xhigh (lease/fencing,
atomic writes, terminal-state/roll-up conflict, read-only-advisor contradiction, compatibility, byte
caps). The audit docs live under `docs/superpowers/expert/` and the reviews are recorded in the run
history.
