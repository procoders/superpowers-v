# Phase 1B Domain Audit — Research-Grounded Brainstorm (v2.7.0)

**Advisor:** Compound V Phase 1B (domain-expert)
**Date:** 2026-07-10
**Spec audited:** `docs/superpowers/specs/2026-07-10-research-grounded-brainstorm-design.md`
**Scope note:** This is a DOMAIN/UX audit — the human-factors and prior-art reality of
(a) front-loading automated research before an ideation dialogue and (b) batching independent
clarification questions into one form. Existing-code reality is Phase 1A; library/API currency is
Phase 1C. This audit does not touch either.

---

## 1. Domain(s) Identified

1. **requirements-elicitation-ux** — how an AI agent should ask clarifying questions (sequential
   vs batched, count thresholds, question-classification failure modes, cognitive load).
2. **research-grounded-ideation** — anchoring / premature-convergence risk when a research pass is
   run *before* an ideation dialogue and its output is fed to the ideating agent.
3. **ai-consent-cost-ux** — honest cost/time disclosure and `ask|auto|off` defaults for a
   token-expensive optional AI step, under a hard no-fabricated-metrics rule.

No prior KB file existed for any of these (the two KB files present cover agent-instruction files
and design tokens — unrelated). No prior recon doc exists for this topic. This audit therefore
runs a full three-layer search and seeds two new KB files.

---

## 2. Sources Consulted

**KB reused:** none relevant (checked `_knowledge-base/agent-instruction-files.md`,
`_knowledge-base/design-md-tokens.md` — different domains).

**Web searches (9 in one batch + 6 follow-ups):** matrix-vs-per-page survey completion; anchoring/
design-fixation in ideation; LLM requirements-elicitation research 2025–26; conversational vs
traditional form completion; AI premature-convergence/confirmation-bias; AI PRD-generator prior art;
deep-research token cost/consent defaults; survey order-effects/skip-logic; deep-research products'
clarifying-question UX; developer sentiment on AI clarifying-question cadence; Miller's-law cognitive
load; framing bias in option-presentation.

**Primary sources fetched / quoted:**
- [Requirements Elicitation Follow-Up Question Generation (arXiv 2507.02858)](https://arxiv.org/html/2507.02858) — LLM vs human clarifying questions.
- [Examining and Addressing Barriers to Diversity in LLM-Generated Ideas (arXiv 2602.20408)](https://arxiv.org/pdf/2602.20408) — homogenization/anchoring in LLM ideation (fetched; see hedge in §4).
- [Anchors in the Machine: Anchoring Bias in LLMs (arXiv 2511.05766)](https://arxiv.org/pdf/2511.05766) — surfaced in search; establishes LLMs themselves anchor.
- [ScienceDirect — Web survey experiments on matrix questions](https://www.sciencedirect.com/science/article/abs/pii/S074756321630718X)
- [Survicate — 21,863-survey analysis, question count vs completion](https://survicate.com/blog/how-many-questions-should-surveys-have/)
- [Formstack/HubSpot multi-step vs single-page (via TinyCommand 2026 roundup)](https://tinycommand.com/blogs/conversational-forms-vs-traditional-forms-which-is-better-for-your-business)
- [IxDF — Design Fixation](https://ixdf.org/literature/topics/fixation) · [IxDF — Anchoring](https://ixdf.org/literature/topics/anchoring)
- [Keito — AI research-agent cost tracking](https://keito.ai/blog/ai-research-agent-cost-tracking/)
- [T-Minus AI — Deep Research showdown 2026](https://www.tminusai.com/blog/deep-research-ai-showdown-2026) (deep-research products gate on scope + time estimate)
- Developer practitioner blogs (Layer 3): [Pete Hodgson](https://blog.thepete.net/blog/2025/05/22/why-your-ai-coding-assistant-keeps-doing-it-wrong-and-how-to-fix-it/), [Dan Does Code](https://www.dandoescode.com/blog/efficient-vibe-coding-with-clarifying-questions), [BSWEN](https://docs.bswen.com/blog/2026-04-01-ai-clarifying-questions-codex/)
- [Miller's Law overview (UX/UI Principles)](https://uxuiprinciples.com/en/principles/millers-law)

---

## 3. Domain Constraints the Brainstorm Probably Missed

- **MUST** treat the recon output as a question-*widener*, not an answer. The stated goal is
  "brainstorm doesn't develop the task deeply enough." The ironic failure mode is that handing the
  ideating agent a research dossier can *narrow* the idea space (anchoring / premature convergence)
  — producing a shallower, more conventional spec, the exact opposite of the goal. This is
  well-documented for humans (design fixation: "the first idea drops an anchor; most people circle
  the anchor and never venture down unexplored paths" — [IxDF](https://ixdf.org/literature/topics/fixation))
  and now for LLMs (LLM ideation homogenizes; anchoring is a documented mechanism — [arXiv 2602.20408](https://arxiv.org/pdf/2602.20408); LLMs exhibit measurable anchoring bias — [arXiv 2511.05766](https://arxiv.org/pdf/2511.05766)).
- **MUST NOT** let recon emit a single recommended solution or approach. If it names approaches,
  it names **≥2–3 divergent ones, explicitly labeled non-exhaustive**, so the brainstorm diverges
  before it converges.
- **MUST** separate the recon doc into *facts/constraints* (safe to anchor on — regulatory rules,
  API signatures, hard limits) vs *suggested directions* (must not anchor on). The spec's own output
  target ("findings + questions the brainstorm should ask + constraints the spec must respect") is
  close — enforce the ordering so *questions* lead and *directions* are clearly optional.
- **MUST** state cost/time honestly and **qualitatively** in the `ask`-mode offer, with **no
  fabricated token number**. Deep-research cost is genuinely unpredictable (£0.10 → £20+, median
  £1–3, 3–5 search-deepen loops — [Keito](https://keito.ai/blog/ai-research-agent-cost-tracking/)),
  so any hard token figure would be a fabrication *and* likely wrong. Disclose the bounded scope
  (≤6 web searches OR one deep-research pass), an order-of-magnitude wall-clock, and that it spends
  tokens/subagents.
- **SHOULD** mirror the ambient deep-research UX norm: ChatGPT, Gemini, and Perplexity deep-research
  all gate the expensive pass behind a **scope/clarifying step and/or a visible time estimate**
  before spending ([T-Minus 2026](https://www.tminusai.com/blog/deep-research-ai-showdown-2026)).
  A one-line scope-narrowing prompt before recon both matches user expectations and *reduces* the
  anchoring risk (the human narrows scope, not the AI).
- **SHOULD** keep the batched companion form **small and chunked** (~3–5 distinct question groups
  per screen), not a dense grid. Survey evidence: "3 multiple-choice per page" beat *both* "1 per
  page" *and* "long matrix" on respondent satisfaction, and matrix/grid formats had **higher
  dropout** ([ScienceDirect](https://www.sciencedirect.com/science/article/abs/pii/S074756321630718X)).
  Each 7+-row matrix block adds ~2–5pp dropout and invites straight-lining.
- **MUST** ship the classification rule with a **"when unsure → sequential" tiebreak** (see §4).
  Misclassifying a dependent question as independent yields a half-stale form; the cost of a wrong
  "independent" call is higher than the cost of one extra terminal turn.

---

## 4. Common Traps in This Domain

- **Trap A — Recon anchors the brainstorm (the headline risk).** Front-loaded research narrows the
  idea space instead of widening it. *Hedge:* the arXiv 2602.20408 fetch partly echoed this audit's
  own "research dossier" phrasing, so treat the *specific* "dossier narrows ideas" wording as
  unconfirmed; the *robust* claim (LLM ideation homogenizes; provided context anchors; diversity-
  prompting and reframing counteract it) is corroborated across the fixation, anchoring-in-LLMs, and
  AI-decision-bias literature. Mitigation the design must adopt: explicit anti-anchoring header +
  divergent-options framing + facts/directions split.
- **Trap B — Batching a dependent question as if independent** → the form is half-stale the moment
  an earlier answer would have changed a later question. (§4 examples.)
- **Trap C — The wall-of-questions grid.** Cramming many "independent" questions onto one screen
  recreates the survey *matrix* anti-pattern: higher dropout, lower satisfaction, straight-lining —
  measurably *worse* than one-at-a-time. Batching helps only when the batch is small and visually
  chunked; multi-step beats single dense page (Formstack +25.4%, HubSpot +86% conversion — [TinyCommand roundup](https://tinycommand.com/blogs/conversational-forms-vs-traditional-forms-which-is-better-for-your-business)).
- **Trap D — Closed-options-only form suppresses the true answer.** Presenting only listed choices
  anchors the user and frames out the unlisted real answer; "AI-generated responses align more
  closely with user framing when prompts contain leading questions." Divergent brainstorming needs
  an open-ended escape hatch per group ("other / none of these" free text).
- **Trap E — Fabricated cost numbers.** Printing "~this costs N tokens" violates the project's hard
  anti-fabrication rule AND is likely wrong (cost variance is 200×). Dishonest lowballing also erodes
  the consent the `ask` default exists to obtain.
- **Trap F — Recon duplicating 1A/1B/1C searches.** Wasted tokens if recon and the pre-flights both
  run the same queries. The spec already fixes this with the read-first contract (1B/1C check
  `docs/superpowers/recon/` before searching) — verify that contract lands in *both* phase docs.
- **Counter-signal (must respect, not "fix"):** developer practitioners explicitly favor
  **one-at-a-time** clarification for *dependent/exploratory* work — "ask each question one at a
  time … cognitive load near zero, answer with a single letter … one revision cycle costs more than
  a focused interview" ([Dan Does Code](https://www.dandoescode.com/blog/efficient-vibe-coding-with-clarifying-questions),
  [Pete Hodgson](https://blog.thepete.net/blog/2025/05/22/why-your-ai-coding-assistant-keeps-doing-it-wrong-and-how-to-fix-it/)).
  The spec is correct to keep dependent chains sequential; the batching feature must not leak into
  them. Default bias stays sequential; the form is the exception that clears the 3-condition gate.

### Misclassification examples (looks independent, actually dependent) — for the tiebreak guidance

1. **Name vs identifier.** "What do we call the feature?" + "What's the CLI command prefix?" — if the
   name becomes the command, the second answer is constrained by the first.
2. **Format vs validation.** "Output JSON or YAML?" + "Validate against a schema?" — schema tooling
   and feasibility differ by format.
3. **Theme vs mode.** "Pick a color theme" + "Support dark mode?" — the theme constrains the
   dark-mode palette.
4. **Ranking vs MVP.** "Rank features A/B/C" + "Which is the MVP?" — the ranking *is* the MVP answer;
   asking both in one form invites self-contradiction.
5. **Runtime vs tooling.** "Node / Deno / Bun?" + "Which package manager?" — runtime constrains PM.
6. **The subtle systemic one — toggles coupled by an unshown budget.** "Enable X?" "Enable Y?"
   "Enable Z?" look independent, but if an unstated scope/time budget can't afford all three, the
   answers interact through a constraint the form never displays. This is the case the tiebreak must
   catch: **if the answers could ever contradict or over-subscribe a shared budget, they are not
   independent — ask sequentially.**

Order/carryover/priming effects are real and documented in questionnaire design (a problem-framed
question first depresses later scores regardless of experience — survey order-effect literature),
which is why "independence" must be judged on *answer interaction*, not surface topic.

---

## 5. Regulatory / Compliance Notes

This is internal developer-UX tooling; **no external regulatory surface** (no PII, payments,
health, etc.). Two soft notes:

- **Data egress / consent.** Recon sends the *topic text* (and, via `deep-research`, derived queries)
  to third-party search/LLM services. For a spec that may contain proprietary or pre-announcement
  product detail, the `ask` gate is also an *egress* consent point, not only a cost gate. The offer
  SHOULD make it clear that enabling recon performs external web searches. `off` must be a real,
  honored kill-switch for teams under confidentiality constraints.
- **Honest-disclosure norm.** Truthful cost/time framing is a trust/consumer-fairness expectation
  (and this project's explicit rule), not a statute. No compliance filing implications.

---

## 6. Recent Breaking Changes (last 12 months)

- **Deep-research became a standard, gated pattern (2025→2026).** ChatGPT, Gemini Deep Research, and
  Perplexity all now (a) ask a clarifying/scope question and/or (b) show a time estimate (ChatGPT
  ~5–15 min; Gemini browses 100+ pages) before running. The ambient user expectation for an
  expensive research step is now "it will confirm scope and tell me it takes minutes" — the recon
  offer should match this, not surprise the user. Source: [T-Minus 2026](https://www.tminusai.com/blog/deep-research-ai-showdown-2026).
- **LLM requirements-elicitation is a live research area (RE-2025 wave).** New finding directly
  relevant to recon-output shape: minimally-guided LLM clarifying questions are statistically **no
  worse** than human ones, and become **markedly better when guided by an explicit list of
  interviewer "mistake types"** (GPT-4o chosen in ~68% of paired comparisons; ~93.5% probability of
  producing the better mistake-avoiding question) — [arXiv 2507.02858](https://arxiv.org/html/2507.02858).
  Implication: recon's "questions the brainstorm should ask" section is more valuable if it's framed
  as *mistakes-to-avoid* (e.g., "don't ask a leading question; elicit tacit constraints") than as a
  raw question list.
- No breaking API/library changes bear on this feature (that's Phase 1C's call).

---

## 7. Design Constraints for the Plan (non-negotiable)

1. **Recon doc carries an explicit anti-anchoring header.** Verbatim-style guardrail the plan should
   bake into the output template, e.g.: *"This recon is evidence to widen the brainstorm's questions,
   not a conclusion to converge on. Treat FACTS/CONSTRAINTS as binding; treat DIRECTIONS as one of
   several possibilities — generate alternatives that ignore them."* (Counters premature convergence.)
2. **Recon output is structured FACTS/CONSTRAINTS (anchor-safe) vs SUGGESTED DIRECTIONS
   (anchor-unsafe, ≥2–3 divergent, non-exhaustive) vs QUESTIONS-TO-ASK.** Questions lead; a single
   recommended approach is forbidden.
3. **The "questions the brainstorm should ask" section is framed as mistakes-to-avoid**, not a flat
   question list — this is the empirically stronger form ([arXiv 2507.02858](https://arxiv.org/html/2507.02858)).
4. **`ask`-mode offer states cost/time honestly and qualitatively, with zero fabricated token
   counts.** Required elements: bounded scope (≤6 web searches OR one deep-research pass), an
   order-of-magnitude wall-clock ("usually a couple of minutes; deep research can run several
   minutes and spawn multiple subagents"), and an external-web-search/egress note. No numeric token
   estimate, ever.
5. **`off` is an honored hard kill-switch** (cost *and* confidentiality). `auto` still writes the
   same anti-anchoring header (constraint 1 applies regardless of mode).
6. **Batch gate keeps the ≥3 floor AND adds a ceiling:** ~3–5 distinct question groups per companion
   screen; beyond that, paginate/split or continue one-at-a-time. Never render a dense matrix/grid.
7. **Batched groups must be answerable in any order, share no rating scale/common stem, and each
   carries an open-ended "other / none of these" escape hatch** (counters straight-lining and
   closed-option framing bias).
8. **Classification rule ships with a "when unsure → sequential" tiebreak**, and the operational test
   for independence is *answer interaction* (could any answer change, contradict, or over-subscribe
   another, including via an unshown shared budget?), not surface topic. Include ≥3 of the §4
   looks-independent-but-dependent examples in `brainstorm-elicitation.md`.
9. **Dependent/exploratory questions stay one-at-a-time in the terminal** — this matches both upstream
   and the practitioner counter-signal; the batching feature must not capture them. Default bias =
   sequential; the form is the gated exception.
10. **Recon is EVIDENCE, never a routing/decision input** (same boundary as V-memory, already AC #8).
    This boundary is load-bearing *because* of the anchoring risk: if recon findings silently drove
    approach selection, that would *be* the premature-convergence failure. Keep it advisory-only.
11. **Recon is non-blocking and degrade-safe** — no engine / no network ⇒ skip with an explicit
    notice; never delay or block the brainstorm's first question.
12. **The 1B/1C read-first contract must land in BOTH phase docs** (not just referenced once), so the
    pre-flights deepen recon's queries instead of repeating them (avoids Trap F).

---

## 8. Open Questions for the Human

1. **Cost/time copy.** What is the *truthful* wall-clock band to display for each engine on this
   install? I will not fabricate it; product/Oleg must set an honest phrase (the literature band is
   "seconds for a WebSearch sweep; several minutes for a deep-research pass"). Confirm the exact
   wording.
2. **Scope-narrowing turn in `ask` mode.** Should the offer be a plain yes/no, or a one-line
   scope-narrowing prompt first (mirroring ChatGPT/Gemini/Perplexity)? The latter costs one extra
   turn but cuts wasted-scope tokens and reduces anchoring. Product call.
3. **Companion per-screen ceiling.** I recommend ~5 groups; the true cap depends on the Visual
   Companion's actual frame layout (Phase 1A/1C territory) — confirm the number.
4. **Is there a domain where anchoring is *desired*?** For strongly regulated / compliance-bound
   topics you may *want* the brainstorm to converge on the hard constraints. If so, the FACTS/
   CONSTRAINTS split already handles it — but confirm no domain should suppress the divergent
   DIRECTIONS section entirely.

---

## 9. Knowledge Base Updates

Created two new KB files (no prior coverage existed):

- `docs/superpowers/expert/_knowledge-base/requirements-elicitation-ux.md` — batching-vs-sequential
  matrix, count thresholds (floor + ceiling), classification/independence traps, cognitive-load and
  survey-format evidence, consent/cost-disclosure norms for expensive AI steps.
- `docs/superpowers/expert/_knowledge-base/research-grounded-ideation.md` — anchoring / premature-
  convergence when front-loading research into AI ideation, the human (fixation) + LLM (anchoring)
  evidence, and the anti-anchoring guardrail pattern.
