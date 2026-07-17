# Four types of agentic loops — and what Compound V runs on each

Four ways to structure agentic work, and the Compound V feature that implements each. The recurring theme:
in the two most autonomous loops (goal-based and proactive) Compound V's **evaluator/judge is cross-vendor**
(Codex + Gemini via the [arbiter panel](../../scripts/compound-v-epic-arbiter.py)) and **git-derived**
(the [scope gate](../../scripts/compound-v-scope-check.py)) — not a single model checking itself — and every
loop keeps an honesty guardrail (a human gate or a circuit breaker), never a blind autopilot.

| # | Loop | Triggered by | Ends when | Compound V feature |
|---|---|---|---|---|
| 01 | **Turn-based** — you steer every move | your prompt | you review | the default + **checkpoint epic** (`MAX_FEATURES=1`) + the brainstorm HARD-GATE |
| 02 | **Goal-based** — it checks itself | `/v:epic` + breaker budget | the evaluator passes | **Marathon Loop** (v2.10) — evaluator = 3-pass review + cross-model arbiter |
| 03 | **Time-based** — the clock triggers it | an interval fires | it waits for the tick | **Auto-Resurrection Watch** (v2.11, `:17/:47`) + the **headless shim** (v2.14) |
| 04 | **Proactive** — no human present | an event / schedule | it decides (bounded) | marathon + watch + arbiter, **honestly bounded** |

---

## 01 · Turn-based — *you steer every move*

The default Claude Code interaction, and Compound V's **checkpoint** stance. You prompt, it acts, it replies,
you write the next prompt. The human is in the loop at every gate: the partition-review gate before dispatch,
the 3-pass Review Gate after, the brainstorming HARD-GATE (no implementation without your explicit design
approval — [`skills/compound-v/SKILL.md`](../../skills/compound-v/SKILL.md)), and the v2.16
[`/v:preferences`](../../commands/v-preferences.md) recall (evidence for you, never an answer). A checkpoint
epic ([`skills/compound-v/epic-mode.md`](../../skills/compound-v/epic-mode.md)) builds one feature, reports
`--stats`, and stops for you. *Triggered by your prompt · ends when you review.*

## 02 · Goal-based — *it checks itself*

The **Marathon Loop** (v2.10, opt-in): [`/v:epic --stance marathon`](../../commands/v-epic.md) chews the whole
runnable feature DAG in one invocation. The **budget** is a set of global circuit breakers — `total_attempts`,
`no_progress_cycles`, `max_wall_clock_hours`, `max_resume_count` — a hard mechanical ceiling no model judgment
overrides. The **evaluator** is the 3-pass Review Gate plus the **arbiter panel**
([`compound-v-epic-arbiter.py`](../../scripts/compound-v-epic-arbiter.py)), and it is **cross-vendor** — Codex
(GPT) + Gemini (via `agy`) as independent read-only judges, not a single model grading its own work (that is
the moat native single-family judge panels don't have). Goal met (all features done + the final integration
review passes) → the epic terminates `done` / `done_with_blockers`; otherwise the arbiter's `retry_fix`
disposition sends it back to work. *Triggered by `/v:epic` + the breaker budget · ends when the evaluator passes.*

## 03 · Time-based — *the clock triggers it*

The **Auto-Resurrection Watch** (v2.11, opt-in, marathon-only,
[`compound-v-epic-watch.py`](../../scripts/compound-v-epic-watch.py)): a two-tier scheduler (session `CronCreate`
+ on-disk `scheduled-tasks`) fires on an off-minute `:17/:47` cadence (~every 30 min), checks whether a marathon
epic is genuinely stalled or dead, and re-invokes `/v:epic` to resume — bounded by `max_resume_count` so a
persistently-dying run halts for a human instead of looping forever. The v2.14 **headless shim**
([`compound-v-headless-shim.py`](../../scripts/compound-v-headless-shim.py)) is the external `launchd`/cron form
of the same idea (present-only: it prints the artifact, you install it). These are Compound V's governed versions
of the native `/loop` and `/schedule`. *Triggered when the interval fires · ends when it waits for the next tick.*

## 04 · Proactive — *no human present*

The most autonomous shape, and where Compound V is **deliberately, honestly bounded**. The marathon + watch +
arbiter stack gives the full contour: the arbiter **triages** a failure, a retry **fixes** it, the 3-pass gate
plus the PASS-integrity sample-audit **review** it, the disposition / confirmed-blocker terminal **judges** it,
and auto-merge on `done_with_blockers` **closes** it — and with `watch` on, it resurrects itself with no human.
The honest boundary (stated, not hidden): a human still **seeds the specs up front**, and a `halt_epic` verdict,
a tripped breaker, or a merely-SUSPECTED blocker **pages a human** rather than pushing past a gate. It is not
"guess a product from one sentence," and truly machine-off resurrection needs external infrastructure Compound V
does not claim to ship. *Triggered by an event / schedule · ends when it decides — within the breakers.*

---

## The through-line

Compound V covers all four loops, but its distinctive value is in the two autonomous ones: the **evaluator**
(loop 02) and the **judge** (loop 04) are cross-vendor, git-derived, and anti-ruflo (counts only, no fabricated
metrics, evidence never an authority), and every loop carries a real stop condition — a human gate or a circuit
breaker — instead of an unbounded autopilot. See [`epic-mode.md`](../../skills/compound-v/epic-mode.md) for the
marathon/watch design and [`agents/spec-reviewer.md`](../../agents/spec-reviewer.md) for the review gate.
