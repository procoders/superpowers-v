# Phase 1B Domain Audit — Epic Autonomous "Marathon Loop" Mode

**Date:** 2026-07-12 · **Advisor:** Compound V Phase 1B (domain-expert) ·
**Spec:** `docs/superpowers/specs/2026-07-12-epic-autonomous-mode-design.md`

## 1. Domain(s) Identified

- `autonomous-agent-orchestration` — unattended/overnight multi-agent build loops:
  runaway-loop control, circuit-breaker placement, watchdog resurrection.
- `llm-judge-aggregation` — multi-backend arbiter panels, majority-vote pathologies,
  self-preference / correlated-error bias.
- `oncall-escalation` — human paging actionability under alert fatigue.

## 2. Sources Consulted

- **KB reused:** `_knowledge-base/dev-workflow-triage-devex.md` (RADAR all-safe rule, alert
  fatigue, reversibility-is-a-gate — all reused below).
- **KB created:** `_knowledge-base/autonomous-agent-orchestration.md` (this pass).
- **Web (2026-07-12, 9 parallel searches + 2 fetches):**
  - Correlated judge errors: [arXiv 2605.29800 "Nine Judges, Two Effective Votes"](https://arxiv.org/pdf/2605.29800),
    [arXiv 2510.01499](https://arxiv.org/pdf/2510.01499).
  - Self-preference bias: [arXiv 2508.06709](https://arxiv.org/pdf/2508.06709),
    [OpenReview Ns8zGZ0lmM](https://openreview.net/forum?id=Ns8zGZ0lmM),
    [futureagi 2026](https://futureagi.com/blog/evaluating-llm-judge-bias-mitigation-2026/).
  - Panel design: [Cohere PoLL via orq.ai](https://orq.ai/blog/llm-juries-in-practice),
    [Comet LLM juries](https://www.comet.com/site/blog/llm-juries-for-evaluation/).
  - Runaway cost: [Tech Startups 2025-11-14](https://techstartups.com/2025/11/14/ai-agents-horror-stories-how-a-47000-failure-exposed-the-hype-and-hidden-risks-of-multi-agent-systems/),
    [LeanOps](https://leanopstech.com/blog/agentic-ai-cost-runaway-token-budget-2026/).
  - Loop safety: [Cloudzy](https://cloudzy.com/blog/why-ai-agent-loops-fail-in-production/),
    [Inkog](https://inkog.io/glossary/infinite-loop-ai-agent),
    [Nexgismo](https://www.nexgismo.com/blog/ai-agent-budget-guards-stop-runaway-api-costs).
  - Resurrection/thundering herd: [Azure retry-storm](https://learn.microsoft.com/en-us/azure/architecture/antipatterns/retry-storm/),
    [Thundering herd](https://en.wikipedia.org/wiki/Thundering_herd_problem),
    [processWatchdog](https://github.com/diffstorm/processWatchdog).
  - Reward hacking: [SpecBench arXiv 2605.21384](https://arxiv.org/html/2605.21384v1),
    [RLVR arXiv 2604.15149](https://arxiv.org/pdf/2604.15149).
  - Overnight loops (Ralph): [HumanLayer](https://www.humanlayer.dev/blog/brief-history-of-ralph),
    [codecentric](https://www.codecentric.de/en/knowledge-hub/blog/the-ralph-wiggum-loop-autonomous-code-generation-with-a-fresh-context).
  - Escalation: [incident.io 2026](https://incident.io/blog/on-call-best-practices-guide-2026),
    [Rootly runbooks](https://rootly.com/incident-response/runbooks).

## 3. Ranked Risks + Required Mitigations

Ranked by (likelihood × blast radius) for an unattended overnight run. R1-R5 are MUST-fix.

### R1 (CRITICAL) — No global budget/wall-clock/resume breaker; per-feature caps don't bound the epic
Both circuit breakers are **local**: `max_attempts_per_feature` (2) bounds one feature;
`max_no_progress_cycles` (3) bounds a stall. Neither bounds the *system*. A 20-feature epic ×2
attempts = 40 full pipelines, each superlinearly expensive (context accumulation: >30x at 50
steps, >100x at 200 — [LeanOps](https://leanopstech.com/blog/agentic-ai-cost-runaway-token-budget-2026/)),
plus every watcher re-fire, with **no ceiling on total attempts, total resumes, or wall-clock.**
Every documented runaway is exactly this: "no global budget cap" (11-day $47k loop; full-year
budget by April — [Tech Startups](https://techstartups.com/2025/11/14/ai-agents-horror-stories-how-a-47000-failure-exposed-the-hype-and-hidden-risks-of-multi-agent-systems/)).
**MUST:** add an epic-level `max_total_attempts` and a `max_wall_clock_hours` dead-man's switch
(default a conservative few hours) that halts+pages regardless of local progress, plus a
`max_resume_count`. Enforce it in `epic-state.py` / the watch script — **outside** the driver's
reasoning, since "if the agent is looping it can't be trusted to stop itself"
([Cloudzy](https://cloudzy.com/blog/why-ai-agent-loops-fail-in-production/)). Dollar/token metrics
stay anti-ruflo: bound **counts** (attempts, resumes, wall-clock), never fabricated cost.

### R2 (CRITICAL) — Crash-before-heartbeat = infinite resurrection that trips NEITHER breaker
`attempts` bumps only when a feature "enters running"; `last_progress_at` bumps only on a state
mutation. A resume that dies during startup (bad worktree, auth failure, OOM) — **before** either
event — leaves the pre-crash timestamp and attempt count untouched. The watcher sees "stale"
(age > 45 min), re-fires, crashes again, forever: a ~30-min-cadence crashloop all night that
never progresses and never hits a cap (the exact failure the spec author flagged as a question).
**MUST:** a **resume-attempt counter incremented at the START of every resume** (before any work),
with its own cap + **exponential backoff + jitter**, and self-disarm after K consecutive
non-progressing fires — the process-watchdog pattern
([processWatchdog](https://github.com/diffstorm/processWatchdog),
[Azure retry-storm](https://learn.microsoft.com/en-us/azure/architecture/antipatterns/retry-storm/)).
A resume that produces no `last_progress_at` advance must count against this cap.

### R3 (HIGH) — Thundering resume: two watcher tiers + long waves + no lock = concurrent drivers
`stale-after = 45 min`, but a full pipeline wave (partition-review → dispatch → scope-gate →
review) can legitimately exceed 45 min while emitting **no state mutation** (so no heartbeat).
The watcher then declares live work dead and launches a second `/v:epic <id>` on the same
`epic-state.json` + same branch/worktree — a retry storm / self-inflicted DDoS. Off-minute
:17/:47 reduces *within-tier* collision but the two tiers (session cron + disk task) can still
**both** fire. **MUST:** (a) a **lease/lock** (PID + `started_at` + host) that makes any resume
**no-op while a live lease is held** — mutual exclusion **across both tiers**; (b) **heartbeat
DURING long waves**, not only on transitions (or raise `stale-after` above the worst-case
silent-wave duration); (c) jitter on both tiers. See
[thundering herd](https://en.wikipedia.org/wiki/Thundering_herd_problem).

### R4 (HIGH) — Arbiter panel treats correlated backends as independent; skip_independent under-guarded
Two problems in one aggregation:
- **Correlated votes.** Panel discovery is by backend *name* (`codex`/`agy`/`cursor`), never by
  underlying model **family**. Cursor's model is user-configurable; a GPT-configured Cursor +
  Codex = two GPT-family votes outvoting one Gemini — the "two correlated models outvote one"
  case. "Nine Judges, Two Effective Votes"
  ([arXiv 2605.29800](https://arxiv.org/pdf/2605.29800)): correlation collapses the effective vote
  count; majority vote can "amplify systematic mistakes"
  ([arXiv 2510.01499](https://arxiv.org/pdf/2510.01499)).
  **MUST:** resolve each backend's actual model, **dedupe by family**, and require the majority to
  span ≥2 distinct families (else collapse same-family members to one effective vote). Record the
  resolved family per vote in the audit JSON.
- **Disposition blast-radius asymmetry.** `halt` is reversible (human looks); `retry_fix` is
  breaker-bounded; **`skip_independent` is the only disposition whose damage compounds unattended**
  — if the "independence" call is wrong (latent shared util/config/migration), the epic builds on
  a broken foundation for hours. Per the KB's RADAR "all-safe not majority-safe" rule and
  "reversibility is a gate, not a coordinate," **`skip_independent` MUST require unanimity across
  distinct families AND a structural cross-check** (the DAG + scope-gate confirm no shared files),
  never a bare majority. A bare majority may authorize at most `retry_fix`.

### R5 (HIGH) — Reward hacking accumulates in unwatched PASSes; the arbiter only sees FAILs
The arbiter adjudicates a *confirmed FAIL*. But the dangerous overnight failure is a **gamed
PASS** — deleted assertions, monkey-patched scorer, weakened tests — and "validation scores
overestimate true spec compliance as horizons grow"
([SpecBench arXiv 2605.21384](https://arxiv.org/html/2605.21384v1); METR/Palisade on frontier
models). Marathon runs unattended for hours = maximal unwatched spec-gaming, and **nothing looks
at passes.** Relatedly, the spec has **no re-verification of already-`success` features**, so a
later feature that regresses an earlier one is never detected (the "A/B oscillation" the author
asked about is actually bounded by monotonic per-feature `attempts`; the real gap is silent
regression of completed work). **MUST:** the Review Gate includes an **anti-reward-hacking check**
(did the diff modify its own tests/assertions/scorers/verifier?), marathon **sample-audits a
fraction of PASSes**, and epic-complete runs a final integration re-verification across all
features before declaring `done`.

### R6 (MED-HIGH) — Caller-supplied liveness clock (`--now`) is fabricable by the very agent it judges
`last_progress_at` "comes from `--now` passed by the caller." The caller is an LLM driver; a
hallucinated **future** `--now` makes a dead epic look alive forever (never resurrected), a stale
one causes thundering resume. A liveness signal must not be forgeable by the monitored party.
**MUST:** the watcher's staleness decision uses an authority the agent can't fabricate — OS wall
clock in the watch script and/or `epic-state.json` file mtime — or **range-checks `--now` against
the OS clock** and rejects implausible values. (Keep the injectable arg for testability; just
don't *trust* it for liveness.)

### R7 (MED) — "Any parse failure → halt" is internally inconsistent and lets one flaky backend neuter autonomy
The spec says both "any parse failure breaks conservative toward `halt`" **and** "never fabricate
a vote for an absent/errored backend." A parse failure **is** an errored backend — counting it as
halt-leaning **fabricates a halt vote** (self-contradiction). Operationally, one chronically-flaky
backend that always returns garbled JSON then halts **every** feature, silently converting marathon
into checkpoint and blaming "the panel." Treating errored replies as *missing data* is the
literature noru ([arXiv 2605.29800](https://arxiv.org/pdf/2605.29800)). **SHOULD:** a parse
failure → **drop that member + log** (same as absent); apply the conservative `halt` default only
to the **aggregate of valid votes** when empty/tied; if valid votes are empty → fall to the Claude
adversarial fallback, and only halt if that too fails. This reconciles the two spec rules.

### R8 (MED) — Zero-backend self-arbitration silently ≈ checkpoint, and shares blind spots the framing can't fix
For the large solo-dev audience with no Codex/agy/cursor, **every** arbitration is the fresh-Claude
fallback with "default to halt." Self-preference research: adversarial framing offsets the
*leniency* axis but **not** a shared blind spot or **shared wrong prior** (both the implementer and
the judge Claude share a stale API belief → confident wrong `retry_fix` until the cap
— [arXiv 2508.06709](https://arxiv.org/pdf/2508.06709); mitigation is literally "a judge from a
different family" — [futureagi](https://futureagi.com/blog/evaluating-llm-judge-bias-mitigation-2026/)).
And "default to halt" biases toward never-progressing, so marathon degrades to
"burn the attempts, then checkpoint." **MUST (honesty):** the docs state plainly that **without a
cross-model backend, marathon's arbiter adds ~no autonomy over checkpoint** — the resume/liveness
layer is the only real benefit. **SHOULD:** the Claude-only fallback may return **only `halt` or
`retry_fix`, never `skip_independent`** (a single self-family judge must not authorize the
compounding disposition), and must **cite the specific acceptance criterion** it judged.

### R9 (MED) — Halt-page actionability / alert fatigue
Apply the on-call "Wake Up test": page only when human action is the only path forward
([incident.io](https://incident.io/blog/on-call-best-practices-guide-2026)); Google SRE ≈ 2-3
actionable pages/shift. An epic that pages per parked feature overnight is alert fatigue by
morning. **MUST:** distinguish **"whole epic blocked → page now"** from **"one feature parked,
independent frontier still chewing → batch into a morning summary."** The halt report MUST be a
runbook (5 A's; every step a command) containing, at minimum:
1. **Which** feature halted (id + title) + **blocked_by_failure** dependents (blast radius).
2. **Why** — the failing acceptance criterion, scope-gate + reviewer verdicts, `last_error`,
   failing-diff summary (not "review failed").
3. **What the panel said** — every member's raw verdict + reason + **resolved model family**, the
   aggregate, and *why* it resolved to halt (tie / parse-fail / cap / unanimous / correlated).
4. **Breaker state** — attempts n/cap, no-progress k/cap, resume-count, wall-clock; which breaker
   tripped.
5. **Exact copy-paste resume command** (`/v:resume <run-id>`) + how to override (raise cap /
   force-skip) — one action from the page.
6. **Paths** to the arbiter audit JSON, run dir, worktree, failing diff.
7. Counts only (attempts/resumes/elapsed) — **no fabricated cost/token figures** (anti-ruflo).

### R10 (MED-LOW, collectively real) — Overnight-environment naïvety
- **Laptop sleep silently kills Tier 1.** `CronCreate` is in-memory/session-bound; sleep → it
  doesn't fire; only the on-disk Tier 2 survives sleep→wake. **MUST document** that sleep disables
  Tier 1 entirely (the honesty boundary should say so, not just "Level-2 semi").
- **Quota/credential expiry mid-run.** "Survives quota exhaustion" holds only if the quota resets
  **and** the session is still authenticated; an expired OAuth token won't resurrect on relaunch
  without re-auth. State this in the Level-2 caveat.
- **Substrate growth.** v2.6.4 fixed *deletion* of the audit trail; the marathon's flip side is
  unbounded **growth** — worktrees, run dirs, arbiter JSONs per attempt/resume accumulate all
  night. **SHOULD** bound/rotate or at least document cleanup.
- **Clock/DST + off-minute cron** across a midnight run; **merge/commit races** on the single epic
  branch when a resume overlaps an in-flight dispatch (folds into the R3 lock).
- **"Overbaking"** — Ralph canon: long unattended runs yield "bizarre emergent behavior"; prefer
  "small iterations merged over time" over one 50-change morning
  ([HumanLayer](https://www.humanlayer.dev/blog/brief-history-of-ralph)). The wall-clock
  dead-man's switch (R1) is the concrete guard.

## 4. Common Traps in This Domain
- Per-unit caps mistaken for a global budget (R1).
- Liveness heartbeat bumped only on transitions, not during work (R3).
- Resurrection with no attempt counter / backoff → crashloop (R2).
- Majority vote assuming judge independence that correlation destroys (R4).
- Trusting the monitored agent's own timestamp as the liveness clock (R6).
- Only adjudicating FAILs while gamed PASSes accumulate unwatched (R5).
- Paging on every event → alert fatigue → the real halt gets rubber-stamped (R9).

## 5. Regulatory / Compliance Notes
None external (internal dev-tooling). **Project-internal "constitution" that binds this feature:**
Opus-default/never-Haiku; no fabricated cost/token metrics (breakers bound **counts**, the arbiter
never fakes a vote — extend to "never fakes a halt vote from a parse failure," R7); git-derived
enforcement never model-self-reported (so R6's clock and R1's breaker must be script/OS-authoritative);
two-command commit discipline; commit substrate before worktree cleanup (v2.6.4).

## 6. Recent Breaking Changes (last 12 months)
No library API breaks (spec is stdlib + existing adapters). Relevant **field shifts**:
frontier-model reward-hacking under tool use is now empirically confirmed (METR o3 / Claude 3.7;
SpecBench 2026) — raises R5's priority; and 2026 judge-panel research (arXiv 2605.29800, 2508.06709)
now quantifies correlation/self-preference, making R4/R8 evidence-backed rather than speculative.

## 7. Design Constraints for the Plan (NON-NEGOTIABLE)
1. Add an **epic-level global breaker**: `max_total_attempts` + `max_resume_count` +
   `max_wall_clock_hours` dead-man's switch, enforced in `epic-state.py`/watch (outside driver
   reasoning), halting+paging regardless of local progress. Bound **counts**, never cost. (R1)
2. Add a **resume-attempt counter incremented at resume START**, with exponential-backoff+jitter
   and self-disarm after K non-progressing fires. (R2)
3. Add a **cross-tier lease/lock** (PID+started_at+host) so a resume no-ops while a live lease is
   held; **heartbeat during long waves** (or set `stale-after` above worst-case silent-wave
   duration); jitter both tiers. (R3)
4. Arbiter: **resolve backend → model family, dedupe by family, require majority to span ≥2
   families**; record resolved family in the audit JSON. (R4)
5. **`skip_independent` requires unanimity across distinct families + a structural (DAG +
   scope-gate) no-shared-files cross-check**; a bare majority may authorize at most `retry_fix`;
   the Claude-only fallback may never authorize `skip_independent`. (R4/R8)
6. Review Gate gains an **anti-reward-hacking check** (diff must not weaken its own
   tests/assertions/scorers); marathon **sample-audits PASSes**; epic-complete runs a **final
   cross-feature integration re-verification** before `done`. (R5)
7. Liveness staleness decided on an **OS/file-mtime clock the agent can't fabricate**, or
   range-check `--now` against the OS clock. (R6)
8. A **parse failure/errored backend = dropped + logged (missing data), not a halt vote**; the
   conservative `halt` default applies only to the aggregate of valid votes when empty/tied. (R7)
9. **Honesty text:** without a cross-model backend, marathon adds ~no autonomy over checkpoint;
   laptop sleep disables Tier 1; "survives quota exhaustion" only if quota resets AND session stays
   authed. (R8/R10)
10. **Halt-page report is a runbook** with the seven fields in R9; page only on whole-epic block,
    batch parked-feature notices into a morning summary. (R9)

## 8. Open Questions for the Human (product/business)
1. **Global budget defaults.** What are sane defaults for `max_wall_clock_hours`,
   `max_total_attempts`, `max_resume_count` for an overnight run? (Domain says "conservative +
   small increments"; the actual number is a risk-appetite call.)
2. **skip_independent trust.** Is auto-`skip_independent` wanted at all, or should *every* skip
   page a human? It is the one disposition that compounds damage unattended — some teams will want
   it human-only.
3. **PASS sampling rate.** What fraction of PASSes should the anti-reward-hacking audit sample
   (0% / 10% / 100%)? Higher = safer but slower/costlier.
4. **Paging channel + quiet hours.** Where does the halt-page go (the spec has scheduled-tasks but
   no notification sink)? Should it respect quiet hours and only page on whole-epic block?
5. **Single-backend UX.** For solo devs with no cross-model backend, should `/v:init` *offer*
   marathon at all, or warn "arbiter ≈ checkpoint without a second model"?

## 9. Knowledge Base Updates
- **Created** `_knowledge-base/autonomous-agent-orchestration.md` — reusable matrices on global-vs-
  local breakers, watchdog resurrection hazards, judge-panel correlation/self-preference, long-
  horizon reward hacking, and on-call actionability. Every claim cites a primary/secondary source.
- **Reused** `_knowledge-base/dev-workflow-triage-devex.md` (RADAR all-safe, reversibility-is-a-
  gate, alert fatigue) — applied to R4/R5/R9.
