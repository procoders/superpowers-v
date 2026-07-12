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
- **Locked, atomic, serialized state writes:** `os.replace` gives *publish* atomicity but is NOT mutual
  exclusion. Every mutation — especially lease acquire/renew/release — runs the whole read → validate →
  mutate → temp-write → `os.replace` sequence under one **`fcntl.flock`** on a sibling lockfile
  (`<state>.lock`), so two concurrent watchers can never both "acquire". (Reuse any existing `flock`
  precedent in the repo.) All new scripts `LANG=C`-clean (reconfigure stdout/stderr to UTF-8).
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
  selftests are byte-for-byte untouched. It routes on the feature's **stored arbiter disposition**, not
  on the bare `failed` status (Sol-R2#8): a failure with a null/`halt` disposition → the epic goes
  `blocked_needing_human` (does NOT auto-route around it); a failure the arbiter marked
  `skip_independent`, or a `blocked` feature, blocks only its **transitive dependents** (reuse the
  `_detect_cycle` adjacency idiom for reverse reachability over `depends_on` — independence is a DAG
  fact, since per-feature `write_allowed` maps don't exist until a feature dispatches); independent
  pending features stay runnable. Returns the 2-key `{feature,reason}` plus a THIRD key
  `"blocked_by_failure":[ids]` (default `--next` shape unchanged).
- **Disposition→status transition table (Sol-R2#6/#8):** `halt`→`blocked_needing_human`;
  `skip_independent`→feature `failed` + routed-around (dependents blocked); `blocked_external`
  (confirmed)→feature `blocked` + ledger; `retry_fix`→feature `pending` (re-run) under the breaker. The
  DISPOSITION is stored on the feature and drives `--next --autonomous`.
- **Terminal states (Sol#3, Sol-R2#5):** decouple watcher terminality from the failed-roll-up. Epic
  status gains `running_with_failures` (work still runnable despite ≥1 failed/blocked) and three terminal
  states: `done` (all `done`), `done_with_blockers` (every remaining feature is `blocked`/`failed` but at
  least one `done` and NO feature needs a fixable human retry — a SUCCESS-with-caveats), and
  `blocked_needing_human` (a `halt` or a tripped breaker needs a person). The watcher disarms ONLY on a
  terminal status, never on the first failure; a blocked-only exhaustion resolves to `done_with_blockers`,
  not an endless watcher burn.
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
- **`--claim-stale --owner U --pid P --now T [--ttl-min 15]`** is the SINGLE atomic operation the watcher
  uses — it does check-terminality-and-expiry AND acquire in ONE flock-guarded transaction, returning
  `{"claimed":bool, "generation":n, "reason":"live-lease-held|terminal|claimed", "held_by":<owner|null>}`.
  It claims (and bumps `generation`) **only if** the epic is non-terminal AND (no lease OR lease expired).
  This replaces the self-defeating two-step "acquire then re-check stale" (Sol-R2#2): acquiring would have
  cleared the very staleness the watcher then tested. The watcher resumes iff `claimed==true`.
  `--renew-lease` / `--release-lease` mirror it; both require the caller's current `generation` (fencing —
  a stale generation is rejected).
- **`--liveness --state S --now T`** → `{held, lease_expired, epic_status, terminal}` for reporting only;
  the resume DECISION is `--claim-stale`, never a recompute-after-acquire. Cross-references
  `compound-v-liveness.py` (per-JOB hang probe) in the docstring — different granularity, deliberately
  separate; mirrors its `--json`/exit-3/`--selftest` conventions.
- **Worker-layer fencing scope (Sol-R2#3 — honest bound, not a full distributed lock):** the epic lease
  fences `epic-state.json`, but the actual per-feature work runs through the existing dispatcher /
  worktrees / merge-back, which do NOT carry the generation. So the guarantee is scoped honestly: (a) the
  driver **renews the lease on a timer** so expiry happens only on genuine death, keeping the
  double-start window small; (b) the driver **re-validates the lease generation at each fenced boundary —
  immediately before dispatch, before merge-back, before each commit — and REJECTS a stale-generation
  completion**, so a superseded driver's results can never merge; (c) the claim is therefore *"a stale
  driver's work is rejected at the fenced merge boundary"*, **NOT** *"two drivers can never run
  simultaneously"* — a stale driver may briefly waste compute before its next boundary check aborts it.
  Full generation-threading through every worker is explicitly out of scope for a single-user local tool.
  The README/honesty text uses the scoped wording, never "never double-executes".
- **Attempt token (durable, caller-supplied — Sol-R2#7):** the DRIVER mints a UUID and passes it:
  `--update --status running --feature F --attempt-token UUID --generation G`. epic-state stores
  `active_attempt_token`; replaying the SAME token is a no-op returning the same result; a DIFFERENT token
  while one is active is rejected; the transition requires the current lease `generation`. A documented
  transition table defines which prior statuses may go →`running` (pending/failed→running yes;
  done/blocked no). This makes attempts crash-safe (a watcher re-fire can't inflate the count).
- **Acceptance:** a **barrier-synchronized repeated-subprocess** test proves exactly one of N concurrent
  `--claim-stale` wins and generations never duplicate (the flock proof); a live-lease claim returns
  `claimed:false, reason:live-lease-held`; a terminal epic returns `claimed:false, reason:terminal`; an
  expired-lease non-terminal epic is claimed and bumps `generation`; a stale-generation `--renew`/update
  is rejected; replaying an attempt token is idempotent while a different one is rejected; "long wave, no
  status change, lease renewed → not claimable" (the false-resurrection case) and "resume dies before
  renew → lease expires → next `--claim-stale` succeeds".

## Component 3 — Two-Tier Watcher (compound-v-epic-watch.py + prose)

Emits the watcher prompt and advises tiers; the driver makes the actual harness scheduling calls.

- `emit-prompt --epic-id E --state S` → the **self-contained** resume prompt used by BOTH tiers:
  *run `--claim-stale` (the ONE atomic op) → if `claimed==false` (live lease held, or terminal) exit as a
  no-op → else increment the **resume-attempt counter BEFORE any work**, apply exponential backoff +
  jitter, self-disarm after `max_no_progress_cycles` non-progressing fires → resume `/v:epic <id>` →
  stop+disarm if `done`/`done_with_blockers`/`blocked_needing_human` or any global breaker tripped*. No
  separate "acquire then check stale" step (Sol-R2#2). Fully self-contained per the `scheduled-tasks`
  contract.
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
- **Family de-dup (DE-R4):** `compound-v-resolve-model.py --backend X --tier deep` returns the concrete
  model *name* (e.g. `gpt-5.6-sol`, `Gemini 3.1 Pro (High)`) — it has **no `family` concept**, so the
  arbiter ships its OWN `model_name → family` classifier (substring/regex: `gpt`→GPT, `gemini`→Gemini,
  `claude|opus|sonnet`→Claude, `grok`→Grok, else `unknown`). Crucially, **family is keyed on the resolved
  NAME, not the backend** — `cursor` is seeded by `/v:init` as the literal `"auto"` (revealing no family)
  and is user-configurable, so a resolved `"auto"`/unrecognized name is **family-`unknown`**, and
  `cursor`+`codex` may even be two GPT votes. Two same-family votes count as correlated, NOT independent;
  an `unknown`-family vote counts for the `retry_fix`/`halt` majority but is **INELIGIBLE to be the
  "second family"** for the `skip_independent`/`blocked_external` bars (Sol-R2#4).
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
  - `skip_independent`: the highest bar — **unanimity across ≥2 distinct KNOWN families** AND a
    structural DAG independence check (no `depends_on` edge to/from any in-flight or failed feature;
    per-feature `write_allowed` maps don't exist at arbitration time, so independence is a DAG fact, and
    unknown scope ⇒ NOT independent). A bare majority, or any `unknown`-family vote standing in for a
    second family, authorizes at most `retry_fix`. (It is the only disposition whose wrong call compounds
    unattended.)
  - `blocked_external`: **≥2 distinct KNOWN families agree, none dissenting `retry_fix`** → CONFIRMED. Any
    `retry_fix` dissent → route to `retry_fix` (someone thinks it's doable). <2 known families (incl. a
    lone backend, or `unknown`-family votes like Cursor's `auto` which never count toward the bar) ⇒
    SUSPECTED (isolated so the epic continues, but flagged UNCONFIRMED / needs-human-verify).
  - Record every panel member's raw verdict + resolved family for the audit trail — never fabricate a
    vote. Audit path: validate `epic_id` (add `_id_ok` to `build_state`), derive the audit root from the
    contained state path with realpath containment, write atomically with a collision-safe invocation id.
- **Classify vs. retry are SEPARATE (Sol-R2#6):** the panel is ALWAYS consulted on a failure to
  *classify* it (so an exhausted feature can still be recorded as `blocked_external`/`skip_independent`/
  reasoned-`halt`) — the ONLY thing the per-feature `--can-retry` cap gates is the `retry_fix`
  *disposition*, which is masked to `halt` once `attempts >= cap`. Arbitration itself is suppressed only
  if a GLOBAL breaker forbids further model calls (wall-clock / total-attempts tripped). The breaker
  always wins on ACTION; the arbiter always gets to CLASSIFY.
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
  agreed (or "single-model SUSPICION"), what it transitively blocked. When blocked features transitively
  exhaust all remaining work, the epic reaches the terminal **`done_with_blockers`** status (Sol-R2#5) —
  a SUCCESS-with-caveats that disarms the watchers (NOT an endless burn, NOT `blocked_needing_human`);
  `--stats` counts `blocked` separately. Resolving a blocker later is a human action: re-run
  `/v:epic <id>` after `--update --status pending --feature F` reopens it (dependents re-derive).
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
F1 CORE CONTRACT   (scripts/compound-v-epic-state.py — Components 1,2,4b,4c: autonomy, --next          deps: []
                    --autonomous, attempts/token, lease+flock+--claim-stale, --liveness, breakers,
                    blocker_ledger, terminal states, Py3.9 ISO. ONE serial unit — the WHOLE file.)
F4 arbiter-panel   (compound-v-epic-arbiter.py — new file; consumes F1's published state/CLI contract)  deps: [F1]
F3 watcher         (compound-v-epic-watch.py — new file; consumes F1's --claim-stale contract)          deps: [F1]
F5 driver+integrity(v-epic.md, epic-mode.md, v-init.md — driver loop, halt-page runbook, PASS audit)    deps: [F1,F3,F4]
F6 docs + CI + rel (README, CHANGELOG, plugin/marketplace json, validate.yml)                           deps: [F5]
```

Disjoint writes — **the entire `scripts/compound-v-epic-state.py` (Components 1, 2, 4b, 4c — marathon
loop, lease, blocker ledger, breakers) is ONE serial "core contract" unit (Sol-R2#9)**, NOT split by
component number; splitting it would collide on the same file. **F1 must publish its completed state-JSON
+ CLI contract (the `--claim-stale`/`--can-retry`/`--breaker-check`/`--update` signatures and the state
schema) BEFORE F3/F4 begin**, since both consume it. The `model_name→family` map lives inside F4's arbiter
(the resolver stays name-only), so `resolve-model.py` is NOT edited — no cross-unit write there. F4/F3 are
new files (parallel-safe once the contract is frozen). F5 = 3 prose files. F6 = README/CHANGELOG/2
manifests/workflow. No two units write the same file. Plugin manifests are currently CLEAN (session-start
`M` committed in the v2.9 flow) — no dirty-tree hazard.

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
- **Concurrency guarantee is scoped honestly (Sol-R2#3):** the lease + `flock` + generation-fencing
  guarantee *"a superseded driver's work is rejected at the fenced merge boundary"* and that two watchers
  can never both claim a stale run — **NOT** *"two drivers can never run for a moment simultaneously"*. A
  stale driver may briefly waste compute before its next boundary check aborts it. We never claim "never
  double-executes".
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
