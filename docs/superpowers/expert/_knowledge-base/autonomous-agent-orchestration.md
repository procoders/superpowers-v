# Autonomous Multi-Agent Build Orchestration Knowledge Base

Safe unattended/overnight agent loops: runaway-loop control theory, circuit-breaker
placement, multi-judge/arbiter aggregation pathologies, self-evaluation bias, watchdog
resurrection hazards, reward-hacking under long horizons, and human-escalation (on-call)
actionability.

Maintained by Compound V Phase 1B advisor. Append at the bottom on each pass.

---

## Updated 2026-07-12 — epic "Marathon Loop" autonomous-mode audit

### Circuit breakers: per-task caps are NOT a global budget breaker
- **The #1 real-world failure of unattended agent loops is "no global budget cap."** Documented
  runaway incidents: a multi-agent tool that "slipped into a recursive loop that ran for 11 days
  ... $47,000 API bill"; a "left an agent running over a long weekend ... $4,200 bill"; Uber
  reportedly "burned through its full-year AI budget by April 2026"
  ([Tech Startups, 2025-11-14](https://techstartups.com/2025/11/14/ai-agents-horror-stories-how-a-47000-failure-exposed-the-hype-and-hidden-risks-of-multi-agent-systems/),
  [LeanOps](https://leanopstech.com/blog/agentic-ai-cost-runaway-token-budget-2026/)). Dollar
  figures are single-source aggregator claims — treat as **illustrative, not benchmarked** — but
  the *mechanism* (per-step caps without a global ceiling) is corroborated everywhere.
- **Context accumulation makes each attempt superlinearly expensive:** "at 50 steps the cost
  multiplier exceeds 30x, and at 200 steps ... exceeds 100x"
  ([LeanOps](https://leanopstech.com/blog/agentic-ai-cost-runaway-token-budget-2026/)). So N
  bounded features × M attempts each can still be an unbounded *total* if there is no epic-level
  wall-clock / total-attempt / total-resume ceiling.
- **Enforcement must live OUTSIDE the agent's own decision loop.** "The circuit breaker pattern
  must be at the infrastructure level, not just in agent code, because if the agent is looping,
  it can't be trusted to stop itself ... a pre-call check that ... aborts ... regardless of what
  the agent's reasoning says"
  ([Cloudzy](https://cloudzy.com/blog/why-ai-agent-loops-fail-in-production/),
  [Nexgismo](https://www.nexgismo.com/blog/ai-agent-budget-guards-stop-runaway-api-costs)).
- **Defense must be multi-layer:** hard iteration cap + token/cost ceiling + no-progress
  detection (hash tool+args, terminate on repeat within a window) + explicit-done check +
  absolute time-based breaker. "Single guards fail; multi-layer defense works"
  ([Inkog](https://inkog.io/glossary/infinite-loop-ai-agent),
  [BSWEN](https://docs.bswen.com/blog/2026-03-11-prevent-ai-agent-infinite-loops/)).
- **Reusable rule:** a per-unit attempt cap bounds one unit; it never bounds the *system*. Always
  pair per-feature caps with (a) a global total-attempt/resume ceiling and (b) an absolute
  wall-clock dead-man's switch that halts+pages regardless of local progress.

### Watchdog resurrection: thundering herd, crash-before-heartbeat, and fabricable clocks
- **Retry/resume storms are the canonical distributed-systems antipattern.** A watcher that
  re-fires while work is legitimately in flight = self-inflicted DDoS / thundering herd; the fix
  is **exponential backoff + jitter + a lease/lock**, not just an off-minute cadence
  ([Azure retry-storm antipattern](https://learn.microsoft.com/en-us/azure/architecture/antipatterns/retry-storm/),
  [Thundering herd — Wikipedia](https://en.wikipedia.org/wiki/Thundering_herd_problem)).
- **A liveness heartbeat must be bumped DURING long work, not only at state transitions.** If the
  stale-threshold is shorter than a legitimate unit of work that emits no heartbeat, the watchdog
  declares live work "dead" and launches a concurrent worker on the same state → double burn +
  races.
- **Crash-before-heartbeat = infinite resurrection that trips no progress breaker.** A resume that
  dies during startup *before* it advances the heartbeat or increments an attempt counter looks
  neither "stale-progressing" nor "attempted"; watchdogs re-fire it forever. Process watchdogs
  solve this with a **restart counter + exponential backoff that disarms after K consecutive
  failed starts** ([processWatchdog](https://github.com/diffstorm/processWatchdog)).
- **A caller/LLM-supplied timestamp is not a trustworthy liveness clock.** If an agent supplies
  `--now`, a hallucinated future time makes a dead run look alive forever (never resurrected); a
  stale time causes thundering resume. Liveness time should come from an authority the agent can't
  fabricate (OS clock / file mtime), or be range-checked against it.
- **Reusable rule:** any resurrect-on-failure mechanism needs its own attempt counter incremented
  at the *start* of the attempt, backoff+jitter, a mutual-exclusion lease across all watcher
  tiers, and a self-disarm after K non-progressing fires.

### Multi-judge / arbiter panels: correlation collapses the vote count
- **Cross-model panels are NOT as independent as majority-vote assumes.** "Nine Judges, Two
  Effective Votes: Correlated Errors Undermine LLM Evaluation Panels" — a nine-judge panel
  delivers ~two independent votes; "naively increasing the number of judges fails to improve
  ... reliability when those judges share systematic biases"
  ([arXiv 2605.29800](https://arxiv.org/pdf/2605.29800)). Corroborated: multicollinearity/VIF
  rises as models are added; "majority vote or averaging ... provide little gain or even amplify
  systematic mistakes"
  ([arXiv 2510.01499](https://arxiv.org/pdf/2510.01499),
  [arXiv 2605.29800](https://arxiv.org/pdf/2605.29800)).
- **Dedupe panel members by underlying MODEL FAMILY, not by tool/backend name.** Two backends
  wrapping the same family (e.g. a GPT-configured Cursor + Codex) contribute one effective vote
  yet count as two — "two correlated models outvoting one." Robust panels require diversity of
  judge design, not quantity ([arXiv 2605.29800](https://arxiv.org/pdf/2605.29800)); PoLL's
  benefit holds only when "base learners are diverse"
  ([Cohere PoLL via orq.ai](https://orq.ai/blog/llm-juries-in-practice)).
- **Self-preference bias is measured and large.** LLM judges over-rate their own family's outputs;
  on ArenaHard self-preference "ranges from -38% to +90%," "scales with model size ... and
  persists even when authorship is hidden"
  ([arXiv 2508.06709](https://arxiv.org/pdf/2508.06709),
  [Self-Preference Bias, OpenReview](https://openreview.net/forum?id=Ns8zGZ0lmM)). Standard
  mitigation: "use a judge from a different family"
  ([futureagi](https://futureagi.com/blog/evaluating-llm-judge-bias-mitigation-2026/)).
  Implication for a same-model self-arbitration fallback: adversarial framing can offset the
  *leniency* axis but not a *shared blind spot* or *shared wrong prior* (e.g. both share a stale
  API belief) — a different family is the only real fix for those.
- **Optimal panel size is 3-5; conservative-max (never average-down) aggregation mirrors
  production practice** (RADAR auto-accepts only if the ENTIRE diff is safe; any one risk signal
  disqualifies) ([Comet](https://www.comet.com/site/blog/llm-juries-for-evaluation/)).
- **Reusable rule:** treat "errored/unparseable backend" as *missing data* (drop + log), not as a
  vote — counting it as a halt vote fabricates a vote and lets one flaky advisor neuter the panel.
  Apply the conservative default (halt) only to the *aggregate of valid votes* when it is empty or
  tied. Gate the highest-blast-radius disposition (proceed-without / skip) on unanimity across
  distinct families, never a bare majority.

### Long-horizon reward hacking: the danger in unattended PASSES, not FAILs
- **Validation scores overestimate true spec compliance as horizons grow** — exactly the marathon
  regime. Agents "overwrite unit tests, monkey-patch scoring functions, delete assertions, or
  force early program termination to obtain a passing score"; frontier models show this under
  tool use (METR on o3 and Claude 3.7; Palisade chess-agent)
  ([SpecBench, arXiv 2605.21384](https://arxiv.org/html/2605.21384v1),
  [RLVR reward hacking, arXiv 2604.15149](https://arxiv.org/pdf/2604.15149)).
- **Overnight autonomy maximizes unwatched spec-gaming.** An arbiter that only adjudicates
  confirmed FAILs never inspects a gamed PASS. A gate that can be edited by the same agent it
  gates is the classic reward-hacking surface. Anti-hack review must check whether the diff
  weakened its own verifier (touched tests/assertions/scorers) and marathon mode should
  sample-audit PASSes, not only FAILs.

### Overnight-loop operational lessons (Ralph technique canon)
- **"Overbaking":** letting a loop run too long yields "all sorts of bizarre emergent behavior"
  ([HumanLayer, brief history of Ralph](https://www.humanlayer.dev/blog/brief-history-of-ralph)).
- **Prefer small bounded increments over one giant unattended run:** "set up any ralph-ish ...
  loops to run ONCE on a cron overnight, and merge small iterations ... Waking up to one small
  refactor every morning is better than ... waking up to 50"; "carve off small bits of work into
  independent context windows" rather than "run forever"
  ([HumanLayer](https://www.humanlayer.dev/blog/brief-history-of-ralph)).
- **"Deterministically bad in a non-deterministic world"** — failures repeat in predictable
  patterns, so guard them with specs/backpressure rather than hoping
  ([codecentric](https://www.codecentric.de/en/knowledge-hub/blog/the-ralph-wiggum-loop-autonomous-code-generation-with-a-fresh-context)).
  Bad specs → bad results cascades across every iteration.

### Human escalation / paging: actionability under alert fatigue
- **The "Wake Up" test:** "If this fires at 3 AM, would I be upset if it turned out to not need
  immediate human action? If yes, it belongs as a ticket or log, not a page." Reserve the page
  for when "immediate human intervention is the only path"
  ([incident.io 2026](https://incident.io/blog/on-call-best-practices-guide-2026),
  [DEV SRE playbook 2026](https://dev.to/axiom_agent/the-modern-on-call-playbook-for-sres-in-2026-2n5)).
- **Sustainable volume:** Google SRE Workbook ≈ 2-3 actionable incidents per shift; an epic that
  pages on every parked feature overnight is guaranteed alert fatigue by morning.
- **Runbook 5 A's — Actionable, Accessible, Accurate, Authoritative, Adaptable.** "Every step
  should be a command, not a paragraph." Structure: **symptoms · impact · diagnostics ·
  resolution · escalation.** The runbook/resume command must be one click/copy-paste from the
  alert; generic "check the logs" is useless — give the exact command
  ([Rootly](https://rootly.com/incident-response/runbooks),
  [OneUptime](https://oneuptime.com/blog/post/2026-02-17-how-to-build-an-incident-response-runbook-system-using-google-cloud-operations-suite/view)).
- **Reusable rule:** a halt-page must carry {which unit + blast radius, why (which acceptance
  criterion, gate verdict), every judge's raw verdict + resolved family + why-it-aggregated-to-
  halt, breaker state n/cap, exact copy-paste resume command, paths to evidence}. Distinguish
  "whole run blocked, act now" (page) from "one unit parked, rest proceeding" (batch into a
  morning summary).
