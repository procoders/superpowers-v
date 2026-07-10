# Phase 0 — Pre-Brainstorm Recon (Trigger 0)

**When this fires:** `superpowers:brainstorming` is **about to begin** on a topic this session has no grounding for. Runs BEFORE the brainstorm's first question — the earliest interception point in the pipeline (Trigger 0, upstream of Trigger 1's pre-flights).

**Goal:** Hand the brainstorm a small, honest evidence base — verified facts, hard constraints, and sharper questions — so it starts grounded instead of guessing. Recon is a scout report, not a plan.

> Think of Trigger 0 as sending A-Train around the block before the Seven storm the tower: fast intel on what's actually out there. He reports back. He doesn't pick the plan.

---

## 1. Purpose and Honesty Boundary

Recon exists because a brainstorm that starts cold on an unfamiliar topic asks shallow questions and takes the field's constraints for granted. A bounded research pass before the first question fixes that — **if and only if** its output widens the question space instead of narrowing it.

- **Recon is evidence to widen the brainstorm's questions.** The Phase 1B domain audit behind this feature (2026-07-10) documents the failure mode: front-loaded research *anchors* ideation (design fixation in humans, measurable anchoring bias in LLMs). Handled carelessly, a recon dossier produces a *shallower*, more conventional spec — the exact opposite of the goal. Every rule in §4's output contract exists to counter this.
- **Recon is never an approach-selector.** It must not conclude, recommend a single solution, or pre-decide what the brainstorm should converge on.
- **Recon is never a routing input.** Same boundary as V-memory ([memory.md](memory.md)): findings inform the brainstorm's questions and later the plan's constraints; they never touch model or backend selection.

**Reliability, stated plainly:** Trigger 0 is **description-driven with zero hook backstop**. It fires before any file exists, so no `PostToolUse` hook can reinforce it — the post-save nudge fires only *after* a recon doc is written, which does not close the pre-fire gap. That makes Trigger 0 **weaker than Triggers 1–3** (which do get hook reminders). Do not overclaim its reliability; a missed Trigger 0 degrades to plain upstream brainstorming, and nothing breaks.

---

## 2. Gate Order — Three Gates, Always in This Order

Recon is gated, not fire-by-default (the same philosophy as [skill-escalation.md](skill-escalation.md)). Evaluate the gates in order; the first gate that says "skip" ends the check. **Log the gate decision** in one line in the session reasoning, whichever way it goes:

```
RECON fired — gates: plumbing=pass, KB=miss, config=ask→accepted (scope narrowed). Engine: deep-research.
RECON skipped — gate 2 KB hit: docs/superpowers/expert/2026-05-02-oauth.md covers the domain; handed to the brainstorm instead.
```

### Gate 1 — Plumbing skip

Reuses the existing plumbing classification verbatim (SKILL.md skip rules — the same test as the 1B skip rule):

> "skip only if the spec is entirely about *plumbing* (build system, lint config, internal refactor with no user-facing behavior). If users will see or feel it, domain expertise applies."

Read "spec" as "topic" — no spec exists yet at Trigger 0. Pure build/lint/dev-tooling topics skip recon silently. When in doubt, proceed to gate 2.

### Gate 2 — Knowledge-base hit (V-memory)

Before searching the web, check what the repo already knows. From the **repo root** (agent bash cwd resets between calls — `cd` explicitly or use an absolute script path):

```bash
python3 scripts/compound-v-memory.py search "<topic>" --top 8 --json
```

**Strong-hit rule:** if a returned doc covers the same domain/topic (not merely shares a keyword), **skip recon and hand those docs to the brainstorm instead** — the KB already paid for this knowledge. Weak or partial hits do not stop recon: pass them along AND continue to gate 3. Use `search`, never `recall-check` — `recall-check` is the routing-tighten bridge, a different contract, and recon must stay out of routing entirely.

### Gate 3 — Config: `brainstorm.deep_research` = `ask` | `auto` | `off`

Read from `.claude/compound-v.json`. **The reader owns the default:** a pre-v2.7 config has no `brainstorm` block and nothing validates that file — an absent key means `"ask"`.

- **`ask` (default):** present this offer, verbatim, before running anything:

  > "I can run a quick research pass before we brainstorm — either one deep-research pass (usually several minutes, spawns subagents) or up to 6 parallel web searches (usually under a couple of minutes). Note: this sends the topic text to external search services."

  Options: **run full** / **run with narrowed scope** (the user refines the topic in one line — mirrors the ambient deep-research UX and reduces anchoring, because the human narrows the scope, not the model) / **skip**. Cost is stated qualitatively — wall-clock bands and what gets spawned — never as a fabricated number.
- **`auto`:** run without asking — same engine ladder, same output contract. The anti-anchoring header (§4) applies in every mode.
- **`off`:** a **hard kill-switch, honored absolutely** — for cost AND for confidentiality. Recon sends topic text (and, via deep-research, derived queries) to external services; teams under confidentiality constraints set `off` and it means off: no engine runs, no nagging, no "just one quick search."

---

## 3. Engine Ladder

One engine runs per recon, chosen top-down. All rungs are **non-blocking**: recon must never block or delay the brainstorm's first question — if an engine hangs or errors mid-pass, drop to the next rung (or skip with notice) and move on.

**A — `deep-research` (bundled skill), if present.**

- The presence check is a **live look at the available-skills listing at fire time**. The `/v:init` capability flag (`deep_research` in `~/.claude/compound-v-capabilities.json`) is an **advisory hint only** — it can go stale (e.g. `disableBundledSkills`); the listing is the contract.
- Invoke through the **skill/slash interface** (its available-skills entry / `/deep-research`). **Never** hard-code a `Workflow({...})` call — the Workflow tool may be absent for a plain subagent — and **never** gate on a Claude Code version number.
- **deep-research returns its report as a MESSAGE and writes no files.** The caller captures the returned report, trims it to the recon format (§4 — five sections, ≤150 lines), and writes + commits the doc itself. Do not assume the native report shape or length matches the recon contract; the trim is the caller's job.

**B — parallel WebSearch, if deep-research is absent or declined.**

- **≤6 WebSearch calls in ONE message** (the Phase 1B search pattern: one message, concurrent calls — covering official docs, common pitfalls, hard constraints, recent changes, alternatives). The caller synthesizes the results into the §4 format.

**C — skip with explicit notice.**

- No engine available (or every rung failed): announce plainly — *"recon skipped: no research engine available"* — mirroring 1C's Context7 degrade notice. Never silently pretend recon ran; never stall waiting for an engine.

---

## 4. Output Contract

**Path:** `docs/superpowers/recon/YYYY-MM-DD-<topic>.md` — ≤150 lines, exactly these five sections in this order:

```markdown
# Recon — <topic> (YYYY-MM-DD)

*This recon is evidence to widen the brainstorm's questions, not a conclusion to converge on. Treat FACTS/CONSTRAINTS as binding; treat SUGGESTED DIRECTIONS as some of several possibilities — generate alternatives that ignore them.*

## QUESTIONS TO ASK
<mistakes-to-avoid framing — empirically stronger than a flat question list>
- Don't ask the user to pick a provider before eliciting the offline-support constraint (leading question; preference before requirement).
- Don't assume "standard OAuth" — this field has at least three consent-flow variants; ask which applies.

## FACTS / CONSTRAINTS
<anchor-safe: verified rules, hard limits, API realities — binding, each sourced>

## SUGGESTED DIRECTIONS
<anchor-unsafe: ≥2–3 divergent options, explicitly non-exhaustive>

## SOURCES
<a link or "verified manually on <date>" per claim>
```

Rules, all binding:

1. **The anti-anchoring header is verbatim and mandatory** — the exact italic line above, as one line, in every recon doc, in every mode (`ask` and `auto` alike).
2. **QUESTIONS lead**, framed as **mistakes-to-avoid**, not a flat question list.
3. **FACTS / CONSTRAINTS vs SUGGESTED DIRECTIONS is a hard split:** facts are safe to anchor on (regulatory rules, API signatures, hard limits); directions are not.
4. **≥2–3 divergent directions, explicitly non-exhaustive. A single recommended approach is forbidden.** The DIRECTIONS section is **never suppressed** — for compliance-heavy topics the binding rules belong in FACTS/CONSTRAINTS; the divergence stays.
5. **≤150 lines.** Recon is a scout report; if it doesn't fit, it's trying to be the audit (that's 1B/1C's job).
6. **No cost numbers.** State findings; never print a fabricated metric (the anti-ruflo rule binds recon output too).
7. **Write, then commit immediately:** `git add docs/superpowers/recon/<file>.md && git commit`. This is the v2.6.4 discipline — an uncommitted recon doc vanishes on worktree cleanup and never indexes into V-memory (the FTS5 lane indexes **git-tracked** prose), which means gate 2 can never hit on it for the next brainstorm.

When the doc is committed, announce: *"💉 Compound V — recon saved at `docs/superpowers/recon/<file>.md`. Starting the brainstorm with it."* The brainstorm reads the doc before its first question and treats DIRECTIONS as some options among many.

---

## 5. Recon ≠ Pre-Flight — Relationship to 1B/1C

Recon is **reconnaissance**; the pre-flights are the **audit**. Different jobs, different rigor — both run:

| | Phase 0 recon | Phase 1B/1C pre-flights |
|---|---|---|
| When | before the brainstorm's first question | after the brainstorm produces a spec |
| Input | a topic (no spec exists yet) | the full spec |
| Depth | bounded scout pass, ≤150 lines | full domain / library audit with KB persistence |
| Claims | unverified leads, honestly labeled | verified against live sources |

- **1B and 1C read the recon doc first** (`docs/superpowers/recon/`, matching topic) and **deepen** its queries rather than repeating them — recon's SOURCES are leads to verify, not settled facts. See [phase-1b-domain-expert.md](phase-1b-domain-expert.md) and [phase-1c-documentation-validation.md](phase-1c-documentation-validation.md).
- **Recon never substitutes for either pre-flight.** A topic that had recon still gets the full Trigger 1 treatment; a recon doc existing is not a skip justification for 1B or 1C.
- deep-research can ALSO fire **mid-pipeline** as a gated escalation past 1B/1C — that path keeps its own rules in [skill-escalation.md](skill-escalation.md). Two different doors into the same skill, each with its own gate; neither loosens the other.
