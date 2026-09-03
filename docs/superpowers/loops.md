# Four types of agentic loops — and what Compound V runs on each

Four ways to structure agentic work, and the Compound V feature that implements each. The recurring theme:
in the two most autonomous loops (goal-based and proactive) Compound V's **evaluator/judge is cross-vendor**
(Codex + Gemini via the [arbiter panel](../../scripts/compound-v-epic-arbiter.py)) and **git-derived**
(the [scope gate](../../scripts/compound-v-scope-check.py)) — not a single model checking itself — and every
loop keeps an honesty guardrail (a human gate or a circuit breaker), never a blind autopilot.

| # | Loop | Triggered by | Ends when | Compound V feature |
|---|---|---|---|---|
| 01 | **Turn-based** — you steer every move | your prompt | you review | the default + **checkpoint epic** (`MAX_FEATURES=1`) + the brainstorm HARD-GATE (upstream, prose) |
| 02 | **Goal-based** — it checks itself | `/v:epic` + breaker budget | the evaluator passes | **Marathon Loop** (v2.10) — evaluator = 3-pass review + cross-model arbiter |
| 03 | **Time-based** — the clock triggers it | an interval fires | it waits for the tick | the native **`/loop`** re-entering `/v:epic` (3.4.0) |
| 04 | **Proactive** — no human present | an event / schedule | it decides (bounded) | a native **`/schedule`** routine + marathon + arbiter, **honestly bounded** |

---

## 01 · Turn-based — *you steer every move*

The default Claude Code interaction, and Compound V's **checkpoint** stance. You prompt, it acts, it replies,
you write the next prompt. The human is in the loop at every gate: the partition-review gate before dispatch,
the 3-pass Review Gate after, the brainstorming HARD-GATE (no implementation without your explicit design
approval — this gate lives **upstream in the Superpowers brainstorming skill**, not in Compound V; an earlier
version of this doc miscited it to `skills/compound-v/SKILL.md`, which contains no such gate. It is also
prose upstream, not a mechanism — see [ADR 0002](adr/0002-limits-ship-with-the-claim.md) on stating limits
with claims), and the v2.16
[`/v:preferences`](../../commands/v-preferences.md) recall (evidence for you, never an answer). A checkpoint
epic ([`skills/compound-v/epic-mode.md`](../../skills/compound-v/epic-mode.md)) builds one feature, reports
`--stats`, and stops for you. *Triggered by your prompt · ends when you review.*

## 02 · Goal-based — *it checks itself*

The **Marathon Loop** (v2.10, opt-in): [`/v:epic --stance marathon`](../../commands/v-epic.md) chews the whole
runnable feature DAG in one invocation. The **budget** is a set of global circuit breakers — `total_attempts`,
`no_progress_cycles`, `max_wall_clock_hours` — a hard mechanical ceiling no model judgment overrides. The **evaluator** is the 3-pass Review Gate plus the **arbiter panel**
([`compound-v-epic-arbiter.py`](../../scripts/compound-v-epic-arbiter.py)), and it is **cross-vendor** — Codex
(GPT) + Gemini (via `agy`) as independent read-only judges, not a single model grading its own work (that is
the moat native single-family judge panels don't have). Goal met (all features done + the final integration
review passes) → the epic terminates `done` / `done_with_blockers`; otherwise the arbiter's `retry_fix`
disposition sends it back to work. *Triggered by `/v:epic` + the breaker budget · ends when the evaluator passes.*

## 03 · Time-based — *the clock triggers it*

Compound V shipped its own two-tier scheduler until 3.3; **3.4.0 hands this loop to the harness**. `/v:epic`
offers **`/loop 30m /v:epic <epic-id>`** — never starting it without your yes — and every firing is a plain,
re-entrant resume bounded by the marathon's existing breakers, with no second resume counter. When the epic
goes terminal, `/v:epic` prints *"epic terminal — stop the loop"* and stops the loop itself. The honest
boundary: a `/loop` shares the session's fate, and its interval mode is a `CronCreate` job that fires one
final time after 7 days and is then deleted — so marathons longer than a week are out of scope for 3.4.0 and
need a re-arm or `/schedule`. *Triggered when the interval fires · ends when it waits for the next tick.*

## 04 · Proactive — *no human present*

The most autonomous shape, and where Compound V is **deliberately, honestly bounded**. A **`/schedule`**
routine running `/v:epic <epic-id>` is the machine-off path — a cloud routine on a cron schedule, with its own
auth, offered by `/v:epic` §0c and never armed silently. The marathon + arbiter stack gives the full contour:
the arbiter **triages** a failure, a retry **fixes** it, the 3-pass gate plus the PASS-integrity sample-audit
**review** it, the disposition / confirmed-blocker terminal **judges** it, and auto-merge on
`done_with_blockers` **closes** it. The honest boundary (stated, not hidden): a human still **seeds the specs
up front**, and a `halt_epic` verdict, a tripped breaker, or a merely-SUSPECTED blocker **pages a human**
rather than pushing past a gate. It is not "guess a product from one sentence," and the routine's own cloud
auth is the user's to keep alive. *Triggered by an event / schedule · ends when it decides — within the breakers.*

---

## Commands per loop

Which of the 18 `/v:*` commands drives each loop:

- **01 · turn-based** — most of the toolbelt: [`/v:dispatch`](../../commands/v-dispatch.md), [`/v:orchestrate`](../../commands/v-orchestrate.md), [`/v:collect`](../../commands/v-collect.md), [`/v:status`](../../commands/v-status.md), [`/v:resume`](../../commands/v-resume.md), [`/v:remember`](../../commands/v-remember.md), [`/v:preferences`](../../commands/v-preferences.md), [`/v:dashboard`](../../commands/v-dashboard.md), [`/v:onboard`](../../commands/v-onboard.md), [`/v:pr-review`](../../commands/v-pr-review.md), [`/v:review-plan`](../../commands/v-review-plan.md), [`/v:adr`](../../commands/v-adr.md), [`/v:archaeology`](../../commands/v-archaeology.md), [`/v:init`](../../commands/v-init.md), [`/v:models`](../../commands/v-models.md), [`/v:memory-refresh`](../../commands/v-memory-refresh.md) — plus [`/v:epic`](../../commands/v-epic.md) in the checkpoint stance.
- **02 · goal-based** — `/v:epic --stance marathon`.
- **03 · time-based** — `/loop 30m /v:epic <epic-id>` (the native loop skill, offered by `/v:epic` §0c).
- **04 · proactive** — a `/schedule` routine running `/v:epic <epic-id>`, left unattended + `/v:resume` for a
  run caught mid-pipeline.

**One command climbs all four:** `/v:epic` ladders up one autonomy level at a time —
checkpoint (`MAX_FEATURES=1`, *turn*) → `--stance marathon` (*goal*) → wrapped in `/loop` (*time*) → wrapped
in a `/schedule` routine (*proactive*). The other 16 commands are turn-based tools you invoke and review.

## The through-line

Compound V covers all four loops, but its distinctive value is in the two autonomous ones: the **evaluator**
(loop 02) and the **judge** (loop 04) are cross-vendor, git-derived, and anti-ruflo (counts only, no fabricated
metrics, evidence never an authority), and every loop carries a real stop condition — a human gate or a circuit
breaker — instead of an unbounded autopilot. See [`epic-mode.md`](../../skills/compound-v/epic-mode.md) for the
marathon design and the native re-entry boundary, and [`agents/spec-reviewer.md`](../../agents/spec-reviewer.md)
for the review gate.
