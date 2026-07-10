# Research-Grounded Ideation Knowledge Base

Anchoring / premature-convergence risk when a research pass runs *before* an ideation dialogue and
its output is fed to the ideating agent (human or LLM). The counterintuitive trap: research meant to
*deepen* ideation can *narrow* it.

Maintained by Compound V Phase 1B advisor. Append at the bottom on each pass.

---

## Updated 2026-07-10 — anchoring when front-loading research (research-grounded-brainstorm audit)

### The core risk
- **Front-loaded context narrows the idea space.** Design fixation: "the first idea drops an anchor;
  most people circle the anchor and never venture down the other, unexplored paths" — [IxDF Fixation](https://ixdf.org/literature/topics/fixation),
  [IxDF Anchoring](https://ixdf.org/literature/topics/anchoring). Adding a research dossier before
  ideation can therefore produce a *shallower*, more conventional output — the opposite of the intent.
- **LLMs anchor too — it's not just a human bias.** LLM ideation homogenizes / loses diversity
  ([arXiv 2602.20408 — Barriers to Diversity in LLM-Generated Ideas](https://arxiv.org/pdf/2602.20408));
  LLMs show measurable anchoring bias behaviorally ([arXiv 2511.05766 — Anchors in the Machine](https://arxiv.org/pdf/2511.05766),
  search-surfaced). AI-decision-making literature: "generative AI output can anchor users to its
  initial values"; smaller distance from AI advice → stronger anchoring.
- **Hedge on the specific claim:** a WebFetch summary of 2602.20408 echoed the auditor's own "research
  dossier" wording, so treat *"a dossier specifically narrows ideas"* as unconfirmed. The *robust*,
  multiply-corroborated claim: provided examples/context anchor; ideation homogenizes; diversity
  prompting and reframing counteract it.

### Mitigations that measurably help (adopt these in any recon/research-before-ideation feature)
- **Explicit diversity/anti-anchoring prompting** — instruct the ideator to generate ideas different
  from the provided context; label directions as one-of-many, non-exhaustive.
- **Reframing from multiple stakeholder/perspective viewpoints.**
- **Separate anchor-SAFE from anchor-UNSAFE content:** facts/hard-constraints/regulatory rules are
  safe to anchor on; suggested *approaches/solutions* are not — present ≥2–3 divergent ones.
- **Let the human narrow scope, not the AI** — a scope-clarifying turn before the research runs
  reduces both wasted tokens and anchoring (this is why deep-research products ask first).
- **Keep research output ADVISORY / evidence-only, never a routing or decision input.** If findings
  silently drive approach selection, that *is* the premature-convergence failure.

### Recon-output guardrail pattern (reusable template header)
> "This is evidence to *widen* the questions, not a conclusion to converge on. FACTS/CONSTRAINTS are
> binding; DIRECTIONS are one of several possibilities — deliberately generate alternatives that
> ignore them."

Structure: **FACTS/CONSTRAINTS (anchor-safe) → QUESTIONS-TO-ASK (framed as mistakes-to-avoid) →
SUGGESTED DIRECTIONS (anchor-unsafe, ≥2–3 divergent, non-exhaustive) → SOURCES.**
