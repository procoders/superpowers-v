# Rationalization Table — Compound V

Agents (and humans) under pressure invent reasons to skip discipline. This file is the rebuttal sheet. Every excuse for breaking Compound V has a short, specific answer here.

**Foundational principle:** Violating the letter of the Compound V rules IS violating their spirit. The rules exist precisely because the spirit ("I know what I'm doing, this case is different") is how teams ship the skyscraper-hat.

---

## On the brainstorm-phase overrides (Trigger 0 recon + batched elicitation)

| Excuse | Reality |
|--------|---------|
| "I know this domain — skip the recon." | Whether the KB already covers it is **gate 2's** call (V-memory strong hit + freshness), not yours — run the gates and let them skip honestly. "I know it" is the anchoring failure mode Trigger 0 exists for: a confident training-data guess mislabeled as a constraint is the most dangerous anchor, which is exactly why the recon doc splits VERIFIED from UNVERIFIED LEADS. If the topic really is plumbing, gate 1 skips it for free. |
| "One-at-a-time is always politer / batching is rude." | Upstream's one-at-a-time is the rule for **dependent** chains — and it stays. ≥3 *independent* questions on one Visual Companion screen is fewer round-trips for the human, not less courtesy; the actual UX hazard is the survey **matrix/grid** (higher dropout, straight-lining), which stays banned. The gate (independence + count + config) decides, when unsure → sequential, and `batch_elicitation: false` restores one-at-a-time everywhere. |

## On skipping code-archaeology (Phase 1)

| Excuse | Reality |
|--------|---------|
| "This feature is too small to need archaeology." | The skip rule covers UI tweaks, copy, config — that's it. Anything that branches by mode, reads sibling state, or touches middleware needs the audit. 10 minutes now or hours later. |
| "I already read the relevant code during brainstorming." | Brainstorming reads to *imagine*; archaeology reads to *enumerate*. Different goals, different rigor. Write the matrix. |
| "We've shipped similar features before — I know the constraints." | Latent bugs from sibling code change between releases. Audit the current state, not your memory. |
| "I'll do the audit informally in my head." | The audit is a deliverable that `writing-plans` consumes. No file = no deliverable = no audit. |
| "External APIs haven't changed, I don't need context7." | Yes you do. Training-data API contracts go stale. context7 is one tool call. |

## On skipping the domain-expert advisor (Phase 1B)

| Excuse | Reality |
|--------|---------|
| "I already know this domain well." | Write it down anyway. Future-you doesn't have your memory; future agents definitely don't; the persistent KB compounds value over time. |
| "Archaeology already covers it." | No. Archaeology covers *the existing code*. The domain advisor covers *what the field requires that the spec didn't mention*. Different layer, different failure modes. |
| "It's just a small feature." | The skip rule is "pure plumbing with no user-facing surface." Small features that users see still have domain constraints. |
| "Web searches will be slow." | Run them in parallel — one message, 3–6 concurrent WebSearch calls. Same cost, 1/N wall-clock. |
| "The KB doesn't exist for this domain, creating it is too much work." | Bootstrapping the KB is a one-time cost amortized across every future feature in that domain. The first OAuth feature pays full; the fifth pays 20%. |
| "I'll skim the docs in my head instead of writing the audit." | The audit file is the deliverable that writing-plans consumes. No file = no audit. |
| "Section 8 (Open Questions) is too pushy — I'll just guess." | Guessing on domain questions is how features ship blocked-by-legal or blocked-by-product on launch day. Surface the questions; let the human answer. |

## On skipping the library/doc validator (Phase 1C)

| Excuse | Reality |
|--------|---------|
| "The LLM already knows current library versions." | No. Training cutoff is months-to-years stale. Yesterday's "latest" is today's "deprecated." Verify via Context7. |
| "Context7 is slow / I don't want to wait." | Lookups are seconds. Library lock-ins are weeks of rework. Run it. |
| "We already use library X in the codebase, that's the choice." | Phase 1C still flags if X hasn't been updated in 24+ months — your team committed to an abandoned dep. Better to learn now than after the CVE. |
| "We'll pick libraries during writing-plans, not now." | Then writing-plans is doing Phase 1C ad-hoc, badly, while also trying to plan. Separate the concerns. |
| "Context7 doesn't have this library." | Then fall back to WebSearch + the package registry. Don't skip — degrade. |
| "Implied libraries (e.g. 'use an ORM') don't count." | They do. The choice of ORM is the lock-in. Validate the candidates BEFORE writing-plans picks one. |
| "We already validated this library last year." | A year is forever in package land. Re-validate, even if the KB has prior entries (the KB rule is: trust if <6 months and primary source). |

## On using Sonnet outside the strict junior-task taxonomy

| Excuse | Reality |
|--------|---------|
| "The task LOOKS simple, Sonnet can handle it." | "Looks simple" ≠ "ticks all 8 boxes of the junior-task taxonomy." Re-check the checklist. If you skip even one box, the answer is Opus. |
| "I'll save 5× on token cost using Sonnet for half the batch." | The cost of one Sonnet-shipped bug surviving review = hours of debugging + a re-dispatch. The cost calculus assumes Opus everywhere unless the carve-out is met. |
| "It's a refactor, refactors are mechanical." | Most refactors aren't. "Rename function in one file with exact before/after specified" is mechanical. "Refactor module X for clarity" is design judgment = Opus. |
| "The task has tests, so Sonnet is safe." | Tests catch what tests cover. Sonnet's failure modes (hallucinated APIs, subtle off-by-ones in conditionals) often slip past tests written from the same flawed mental model. Opus for anything with judgment. |
| "I'll let the reviewer (Opus) catch Sonnet's mistakes." | Reviewers catch errors but cost cycles. Better to not make them. The Sonnet-eligibility taxonomy is calibrated so the reviewer almost never has work to do — that's the point. |
| "Sonnet on the security/auth/payments task is fine if I add 'be careful' to the prompt." | No. Security/auth/payments/PII/a11y surfaces are excluded from Sonnet by hard rule regardless of how the prompt's worded. |
| "Accessibility (add ARIA, keyboard handlers) is mechanical, Sonnet's fine." | No. a11y has ADA/EAA legal exposure and demands judgment about reading order, focus management, label association, live-region etiquette — Sonnet frequently miscalls these. Opus. |
| "Sonnet justification column is just paperwork." | It's the audit trail. If you can't write a one-sentence justification that ticks every checkbox, you didn't earn the Sonnet override. |

## On skipping the Partition Map (Phase 2)

| Excuse | Reality |
|--------|---------|
| "The tasks are obviously independent, I don't need the map." | If it's obvious, writing it down takes 90 seconds. If it's not obvious, you needed the map. |
| "Two tasks share a barrel file but it's just an export, it's fine." | Two implementers editing the same barrel file produce merge conflicts or one silently overwrites the other. Put the barrel in Task 0. |
| "I'll mark the map ✅ even though task 2 reads task 1's file." | That's lying to yourself. The reviewer in Phase 3 will catch it; you'll waste a dispatch. Fix the partition first. |
| "Partitioning by slice instead of layer is too much work." | Layer-based plans appear to partition but never actually do, because tests cross layers. Slice-based plans are slightly more design work upfront and dramatically faster to execute. |
| "Just this once, layer-based is fine." | Layer-based means sequential. You've left Compound V. |

## On skipping parallel dispatch (Phase 3)

| Excuse | Reality |
|--------|---------|
| "Let me dispatch one first to see how it goes." | That's sequential. The whole point of Compound V is the wall-clock collapse of N tasks into 1. One-at-a-time = default Superpowers. |
| "I'll do them in parallel but only two at a time, to be safe." | The Partition Map already guarantees safety. Throttling defeats the purpose. Dispatch all N. |
| "What if they collide?" | They can't — that's what the Partition Map verifies. If they could collide, the map was wrong. Fix the map, not the dispatch. |
| "I'll review them sequentially after dispatch." | No. Reviewers also go in parallel. 2N reviewer dispatches in one message. |

## On using cheap models

| Excuse | Reality |
|--------|---------|
| "Sonnet is fast and good enough for this mechanical task." | Compound V trades cost for quality + speed. Opus catches design-time bugs Sonnet ships. The point isn't minimum cost. |
| "I'll use Opus for hard tasks, Sonnet for easy ones." | Mixing models means you have to judge each task. The override removes that judgment cost. All-Opus is the contract. |
| "Opus rate-limited, let me fall back to Sonnet." | Acceptable, but document it: "Compound V fallback: Sonnet used for tasks X/Y because Opus unavailable at <timestamp>." |
| "The user said keep costs low." | Then default Superpowers, not Compound V. Compound V is opt-in for speed-priority work. |

## On bringing back git worktrees

| Excuse | Reality |
|--------|---------|
| "Worktrees are safer, just in case." | Worktrees serialize the integration cost — you have to merge them later. Compound V trades that for trust in the partition. |
| "What if a subagent goes rogue and edits outside scope?" | The scope-lock prompt is explicit. If a subagent violates it, the result is rejected and you investigate. Worktrees would hide the violation, not prevent it. |
| "I always use worktrees, it's my default." | Compound V is the exception. Other workflows can keep worktrees. |
| "The user asked for safety." | Then default Superpowers. Compound V is for users who've opted into speed over safety-margin. |

## On falling back to default Superpowers mid-flow

| Excuse | Reality |
|--------|---------|
| "Phase 2 is hard for this plan, let me just use default writing-plans." | If partitioning truly fails (deep coupling), document why at the top of the plan and use sequential dispatch. But "hard" ≠ "impossible." |
| "Phase 1 audit took longer than expected, skipping Phase 2 partitioning to save time." | The phases are independent. Time spent on Phase 1 doesn't earn skipping Phase 2. |
| "I'm already in the middle of execution, switching to parallel now is risky." | Correct — once execution starts sequentially, finish sequentially. Apply Compound V from the next plan. |

## On "the spirit vs the letter" arguments

| Excuse | Reality |
|--------|---------|
| "The spirit of Compound V is speed, and sequential is fast enough here." | The spirit is *structural guarantees that unlock speed*. Sequential might be fast for this plan, but you've broken the contract that makes future plans fast. |
| "I'm following the spirit even though I skipped the audit." | No. The audit IS the spirit — designing on top of what's actually there, not what you imagine is there. |
| "Compound V is too rigid, I'll adapt it." | Adapting = "this case is different" = the rationalization the table exists to refute. If adaptation is genuinely needed, fall back to default Superpowers explicitly. |

---

## Self-Check — Am I Rationalizing?

If you find yourself thinking:
- "Just this once..."
- "It's a small case..."
- "I know the codebase..."
- "Overkill for this feature..."
- "Adapting the rules slightly..."

**STOP.** That's the rationalization signal. Either:
1. Follow Compound V as written, or
2. Explicitly fall back to default Superpowers and document why.

Don't half-do it. Half-Velocity-Mode produces the worst of both worlds — the cost of Opus without the speed of parallelism, the time of archaeology without the safety of partitioning.

---

## When Compound V Genuinely Doesn't Apply

Honest cases for skipping the whole thing:

- **Greenfield single-file feature** (one new component in a new directory) — no archaeology needed, no partitioning needed, no parallelism to gain.
- **Pure refactor that touches every file** — partitioning is impossible by definition; use sequential.
- **Exploratory spike** — no plan, no spec, just trying things. Compound V requires a spec to start.
- **Solo learning / sandbox** — Compound V is for shipping; learning is fine sequentially.

In all other cases involving multi-task implementation work, Compound V applies.
