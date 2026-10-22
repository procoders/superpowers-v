# Compound V v4 — design

Status: brainstormed with Oleg, 2026-10-22; builder check and Codex review folded in (`docs/v4/spec-review-codex.md`).
Branch `v4-design`. Evidence: `docs/v4/salon-report.md`, `docs/v4/transition.md`, `docs/v4/light-flow.md`,
`docs/v4/critique-codex.md`, `docs/v4/critique-gemini.md`. Items marked **(call)** are the author's decisions, not
Oleg's — open to veto. Where this document and `transition.md` disagree, this document wins.

## 1. Intent — why v4

A partner's tutorial test (Sumit, v3.8.5) exposed that the execution half of Compound V spends far more than it returns.
Our own experiments (salon booking app, blind-judged by Codex with a rubric and a capability census, ≥2 runs each)
confirmed it:

- Depth comes from **questions before code**: brainstorm answers alone nearly doubled considered capabilities
  (plain 37 → 63) for ~$2.
- **Domain research and checklists** add production depth (GDPR, VAT, storage erasure, backups, sessions, CSRF, limits).
- **Executable review + a fix round** catches what reading misses (default password, `Origin: null` + `no-referrer`).
- **The custom orchestration engine added nothing** at this size: the light flow (A5, ~$8, 17 min) beat the full v3
  pipeline (~$87, 49 min) on all four blind judgements (rubric 94/99 vs 62/72); on an existing codebase C-light beat
  C-full (75/78 vs 69/69) at half the cost. Prose-table parallelism without a manifest was safe in one run but 23 %
  slower and 31 % dearer.

Oleg's read: in the last half-year Claude Code learned to orchestrate itself well; v3's engine is now dead weight.
v4 keeps the principles that proved value and hands orchestration to Claude Code's native workflow with good
instructions.

## 2. Goals, non-goals, anti-goals

**Goals**
- A standalone plugin `compound-v` (no dependency on Superpowers) whose cycle is: brainstorm → conditional pre-flights
  → plan → native build → verification with receipts.
- Beat A5 on the salon benchmark at **$5–7** CLI cost, and be no worse than C-light on the brownfield feature — pass
  rules in §7.
- Engage on a plain request in a set-up project (the triage hook), as v3.9 does.

**Non-goals**
- Our own orchestration engine, manifest, waves, transport agents, epics/marathons, run dashboards, scorecards,
  lessons, V-memory as a separate engine, Antigravity/Cursor workers.
- Headless Codex/opencode **build** workers in 4.0 **(call)**: Codex is the reviewer only; the workers return later
  only with the deterministic result check §6 describes.
- Continuing unfinished v3 runs inside v4 (v3 stays installable; see §7).

**Anti-goals (failure even if it "works")**
- Cost creep: a salon-size build above ~$7 or a review/fix loop without a bound.
- Complexity creep: new code growing past ~2k lines (§6); mechanisms with no caller.
- A green "done" without verification receipts for the final tree.
- Hooks that trap a session: a hook may refuse once, never forever.

## 3. Constraints (from project policy and lessons)

- Model policy: Opus by default, Sonnet for mechanical execution and lookups, **never Haiku**; Fable only by explicit
  choice. Under the cost-aware stance the advisor is off or Opus, never Fable.
- No unmeasured numbers in docs or output (anti-fabrication CI guard stays).
- Critical steps are backed by mechanism (hooks + small scripts), not only prose (lesson "prose vs mechanism").
  Enforcement fields are written by scripts from real command results, never self-reported by the model.
- Hooks fail open, are time-bounded, and never write into the user's repo except where the step owns the file.
- Logs and records in `docs/` carry no personal data.
- Python stdlib only for scripts (3.9 floor); hooks in bash; the band is a Claude Code mod (tsx).
- Built in **this repository** on a fresh branch; v3 history, stars and links stay.

## 4. The cycle (what each step must do)

### 4.1 Brainstorm (own skill)
Covers, as territory not a script: the product and its users; the data lifecycle (create / change / retire with
history / delete, what the operator changes without a developer); jurisdiction, data handled and deployment; security
and every form; operations; **edge cases** as their own topic. For large work it asks **how deep** to go; depth may add
pre-flights and checks but never removes the tier's minimum (§4.5). Prior decisions are looked up in `docs/` by a cheap
Sonnet subagent (read-only) and shown as evidence. Output: a written design in `docs/compound-v/specs/`.

### 4.2 Pre-flights (conditional)
- **Domain research — always, light**: ≤4 web searches; output "requirement → source → acceptance check", owner facts
  marked as open.
- **Archaeology — when git tracks code** (greenfield = only prose, images, `.claude/` and `docs/compound-v/`); co-change
  and churn as inputs.
- **Library audit — when the plan adds or changes dependencies.**
Each writes one file under `docs/compound-v/preflight/`. They run as parallel Sonnet subagents with a turn cap.

### 4.3 Plan (own skill)
A detailed plan plus: an **acceptance table** (row = behaviour → check), a **task → model table** (instructions, not
code), and — only when parallel work is chosen — exclusive file lanes per task and the rule "more than one writer ⇒
each in its own worktree". The light-flow checklists (`docs/v4/light-flow.md`) are applied here. The plan also writes
the run record (§4.6). Optional: a plan review by Codex (exists today as `/v:review-plan`).

### 4.4 Build (native)
Claude Code builds: one agent by default; for large plans its native workflow/subagents with the `model` the plan's
table names. No emitter, manifest or transport. Tests are written with the code (negative paths, state transitions,
persisted state, missing config). Parallel writers: see §6.

### 4.5 Verification — the bar

**Steps.**
1. **Tests**: the project's own tests pass.
2. **Executable review** by a second model — Codex if installed, otherwise a fresh Claude subagent (Opus; Fable only by
   choice) — in an isolated checkout, judged against the **original request** plus the acceptance table and checklists,
   with structured findings. Then a fix round. **At most two review→fix rounds**; the check after the second fix is
   tests + browser + scope only, not a third review **(call)**.
3. **Real-world check**: for web apps a real browser submits real forms and the resulting state is checked; for non-web
   projects the binary/API is run for the main flows. curl is not enough for web forms.
4. **Scope check**: git diff of the run against the plan's lanes (or, without lanes, against the declared change set).
5. **Receipts** — see below.
6. **Usage**: time and cost of the run (§4.6).

**Tier obligations (call).**

| Tier | Tests | Executable review | Browser / run | Scope check | Receipts |
|---|---|---|---|---|---|
| light (typo, copy, config) | yes | no | only if a user-facing page or form changed | yes | yes |
| full (default for features) | yes | yes | yes | yes | yes |

Escalation to full is decided by the change's **content and structure**, not its path (v3's
`compound-v-postdiff-reclassify.py` is the model: auth, sessions, payments, personal data, new endpoints or forms in
innocently named files). It is recomputed against the pinned base after every fix; escalation invalidates earlier
receipts. Unclassifiable ⇒ full.

**Receipts and outcomes (call).**
- One script (`verify`) is the authority. It runs or reads each step's real result and writes a receipt bound to one
  canonical content snapshot of the working tree — additions, modifications, deletions and file modes, untracked
  files included — and to the acceptance-table revision. Receipts, run records and other enumerated evidence paths
  under `docs/compound-v/` are excluded from the snapshot, so writing a receipt never invalidates another.
- The reviewer's isolated checkout is built from that same snapshot (not `git ls-files`), and `verify` checks the
  checkout matches it before accepting the review.
- A run ends in exactly one outcome: **verified** (all receipts current) / **incomplete** (a step could not run:
  browser missing, budget hit, reviewer timeout, rounds exhausted with findings open) / **failed** (a step ran and
  failed). Only verified may be reported as done; incomplete and failed name the step and reason.
- The Stop hook reads `verify`'s result: while it is not verified it refuses the stop **once** with the reason; the
  second stop is allowed and the run stays incomplete/failed. The session is never trapped.
- No browser for a web app ⇒ **incomplete**, unless the user waives the check in chat; the waiver is recorded in the
  receipt. Browser source: Claude Code's own browser tooling or a Playwright/Chrome DevTools MCP the project already
  has; `/compound-v:init` detects which exists and offers the Playwright MCP if none. The plugin ships no browser.

### 4.6 Run record and budget (call)
- The plan writes `docs/compound-v/runs/<id>.json`: stage, tier, review round count, outcome. It survives compaction;
  the band, the Stop hook and session-continuity hooks read it. Stage transitions are written by the skills and by
  `verify`, never inferred from chat.
- Budget per run, from the plan: a stage share (brainstorm + pre-flights + plan / build / verification) with
  verification's share reserved up front. Hitting the run budget ⇒ incomplete, not a silent overrun.
- Cost is measured from the session transcripts — parent plus subagents (the salon kit's `session-usage.py` method) —
  and stored in the run record. Codex time and tokens are recorded separately. The account-quota footer of the band
  stays as context, never as the run's cost.

## 5. Around the cycle

- **Triage (small)**: tier light / full plus post-diff escalation (§4.5). One line per decision appended to a log in
  the project. Deterministic; no paid classifier call; conservative fallback (full) for unclassifiable requests.
- **Engagement hook**: on a plain request in a set-up project it starts the cycle (v3.9 behaviour, retargeted to the
  own skills); a not-set-up project gets one "run /compound-v:init" line.
- **Superpowers installed alongside (call)**: compound-v does not call or defer to it. `/compound-v:init` detects it and
  offers to disable it for this project (`enabledPlugins`), because both brainstorm skills would fire on the same
  request. The benchmark runs without Superpowers.
- **Band (mod)**: shows the cycle stage, receipt status and run cost from the run record, plus the quota footer.
- **Commands**: `/compound-v:init` (probes incl. browser and Superpowers, stance, light/full default, taxonomy if triage
  needs it), `onboard`, `pr-review`, `models` (model map for the plan table), `adr` (optional). No
  dispatch/orchestrate/resume/status/epic.
- **Memory**: project docs under `docs/compound-v/` (specs, plans, pre-flights, runs, receipts, decisions) + Claude
  Code's own project memory. No separate V-memory engine (overrides `transition.md`'s optional V-memory).
- **Session continuity**: the banner and compaction hooks restore position from the run record, spec and plan.

## 6. What carries over, changes, goes

`docs/v4/transition.md` is the reference table, with the critiques' corrections and the overrides in this document.
Carry `scope-check` (rewritten small), `codex-review.sh` (extended to executable review), `sandbox-checkout.sh`
(rebuilt on the canonical snapshot, §4.5), `run-with-timeout.py`, `postdiff-reclassify` logic (cut down to the
escalation predicates), `onboard`, `pr-review`, pre-flight agents, `lint-frontmatter.py`, the anti-fabrication and
model CI guards. Delete the engine (`cv_emit`, `cv_validate`, integration gate, collect, failure policy, fast-path,
lane-guard), epics, liveness/dashboard/transcript-watch, scorecard/lessons, triage statistics, Antigravity, Cursor,
Codex and opencode build workers.

**Size (call).** The ~2k-line target covers the **new core**: hooks, `verify`, receipts, run record, triage,
escalation, scope check. `onboard`, `pr-review` and CI tooling are carried and counted separately, and must not grow.

**Parallel writers (call).** No pre-write lane guard. Safety is: native subagents in their own worktrees, exclusive
lanes from the plan, and before anything merges a deterministic step in `verify` — the scope check of that worktree's
diff against its lane, then the project's tests on the merged tree. Release tests include a synthetic parallel run
(a write outside its lane, an interrupted worker) that must be refused.

## 7. How it gets made — decided

- Same repository, fresh branch; the plugin is renamed `compound-v` (commands `/compound-v:<name>`); v4.0.0.
- Built clean, not alongside v3: reuse only the parts in §6 "carry", rewrite small. This overrides the critiques'
  "coexist, deprecate first" order.
- v3 channel **(call)**: a `v3` branch keeps 3.9.x; the marketplace keeps a second entry `superpowers-v` pinned to it,
  if the marketplace format allows a ref — otherwise a separate marketplace file on that branch. README gets a
  migration section: v4 is a separate plugin id; unfinished v3 runs are finished with v3.
- Built through dogfooding: this design → plan → build with the light flow itself.
- **Acceptance (call)**, on the salon kit (`~/Dev/cv-salon-e2e-kit`), protocol frozen before the first v4 run:
  - Same `prd.md`, model, sandbox and settings as A5; owner answers given from a fixed script (the A3–A5 answers), so
    v4 must elicit them but gets the same content.
  - Two independent v4 builds per condition (greenfield salon, brownfield feature on A5's base); each judged blind by
    Codex twice (rubric + census), paired against the reference with labels swapped.
  - Pass: greenfield mean rubric ≥ A5's mean (96.5) **and** mean census "considered" ≥ A5's (75.5) **and** mean cost
    ≤ $7 (Oleg: the budget counts **Claude spend only**; other models are not counted for now). The binding
    configuration has no Codex — the reviewer is a Claude subagent, so its cost is inside the $7; the Codex-reviewer
    configuration is run and recorded alongside, not gated. Brownfield mean rubric ≥ C-light's mean (76.5) with no regression in the base tests. A miss is a release
    blocker for 4.0.0.
  - Holdout: one different small app, v4 vs the light flow alone, one build each, to catch overfitting to the salon.

## 8. Left to the builder

- Exact file layout of the new skills, agents, run records and receipts; receipt JSON format and hash method.
- The checklist wording (start from `docs/v4/light-flow.md`).
- The escalation predicate list and how the engagement hook detects a set-up project cheaply.
- Whether `models` and `adr` survive as commands or fold into init/plan.
- Test suite: delete engine tests with the engine; keep and adapt hook/triage/scope/sandbox/onboard tests; add tests
  for receipts (seeded failures: broken browser form, skipped review, edit after review, untracked file missing from
  the review checkout — all must be refused), bounded review rounds, refuse-once Stop behaviour, post-diff escalation,
  fail-open hooks and the synthetic parallel run.
