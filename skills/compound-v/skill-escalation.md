# Skill Escalation Policy — gated, not fire-by-default

> *"You don't call in the whole Seven for a parking ticket. But when it's real, you make the call — and you write down that you made it."*

Compound V can pull in heavier sibling skills mid-pipeline. The rule mirrors the
forced-Context7 philosophy: **one skill is always on, the rest are gated.** The bar
for the gated ones is **"genuinely needed,"** not "might be nice." Firing all of them
every run is the ruflo anti-pattern (overhead theater) — we do the opposite.

The planning phase consults this doc. **Every escalation is logged** in the run's
reasoning (which skill, the trigger that justified it, what it changed). An escalation
with no recorded justification is a policy violation, not a freebie.

---

## The policy table (PRD §5.10)

| Skill | Status | Escalate ONLY when… |
|---|---|---|
| **Context7** (`plugin:context7:context7`) | **Forced — always on** | any library / SDK / API / CLI is named or implied — validate currency. Not gated; if a dependency is in play, Context7 runs. |
| **deep-research** | Gated | a **load-bearing** planning decision is genuinely uncertain or sources conflict, **beyond** what pre-flights 1B (domain) and 1C (library) already resolved. Not for facts those phases settled. (This is the **mid-pipeline** path — Trigger 0 recon is a separate, earlier use; see the note below.) |
| **playground** | Gated | a decision is **config-heavy or visual** and genuinely benefits from interactive user input (e.g. picking a routing stance, a design/tradeoff matrix). Not for decisions the planner can make alone. |
| **avoid-ai-writing** / **elements-of-style** | Gated | the run **generates user-facing copy or docs** that ship — clean the prose before delivery. Not for internal manifests, scripts, or state files. |

> **Trigger 0 recon — a second, earlier, gated use of deep-research.** Compound V also invokes
> deep-research *before* brainstorming begins (pre-brainstorm recon), at a point where 1B/1C do
> not exist yet — a different purpose (grounding the brainstorm, not resolving a planning
> unknown) with its own gate order (plumbing-skip → KB-hit → `brainstorm.deep_research` config)
> and its own logging discipline, documented in [phase-0-recon.md](phase-0-recon.md). The table
> row above governs the **mid-pipeline escalation** only; neither path loosens the other's gate.

---

## Forced vs gated — the distinction

**Context7 is forced.** It is not a judgment call: the moment any library, framework,
SDK, API, or CLI tool is named or implied, Context7 is consulted to confirm the
current surface. This is a standing rule, not an escalation — it does not need a
per-run justification, because "a dependency exists" is the trigger and it is almost
always true. (This is also why `/v:init` checks for the Context7 MCP and walks the
user through installing it if absent.)

**The other three are gated.** They cost real tokens and latency, and firing them
reflexively is exactly the overhead the anti-ruflo charter rejects. They run only when
the specific trigger in the table is genuinely met, and each firing is logged.

---

## Logging an escalation

When a gated skill is invoked, record one line in the run's reasoning (and, where it
influenced routing, it may later become a lesson in
[`routing-lessons.md`](../../docs/superpowers/memory/routing-lessons.md)):

```
ESCALATE deep-research — trigger: 1C left the auth-library choice unresolved
  (oauth-lib vs authlib conflict in sources). Outcome: chose authlib; folded into plan §4.
```

The log answers three questions: **which** skill, **why** (the concrete trigger),
**what changed**. No log ⇒ the escalation should not have happened.

---

## What this is NOT

- Not a checklist to run top-to-bottom each pipeline. The default is **zero** gated
  escalations on a well-specified plan whose pre-flights resolved the unknowns.
- Not a substitute for the pre-flights. On the **mid-pipeline escalation path**, deep-research
  escalates *past* 1B/1C, not instead of them — that rule stands unchanged. (Trigger 0 recon is
  the separate, earlier, gated use that runs *before* 1B/1C exist — see
  [phase-0-recon.md](phase-0-recon.md) — and it doesn't substitute for the pre-flights either:
  they still run, reading the recon doc first and deepening it.)
- Not a place to print token or cost numbers — escalation logs record decisions, never
  fabricated metrics.
