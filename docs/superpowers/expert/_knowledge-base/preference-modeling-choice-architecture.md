# Preference-Modeling & Choice-Architecture Knowledge Base

Hazards of modeling a human's judgment/preferences and feeding it back as a decision aid: constructed
preference, elicited-rationale confabulation, default/pre-select nudging, recommender feedback-loop
ossification, automation complacency, and personal-model consent/staleness. Applies to any feature that
"learns the user," "personalizes," "pre-selects a default," or "reasons as the creator would."

Maintained by Compound V Phase 1B advisor. Append at the bottom on each pass.

---

## Updated 2026-07-16 — decision-preference capture audit (v2.16.0)

### Constructed preference — the object you're modeling may not exist
- People "do not possess complete preference orderings waiting to be revealed … they build preferences on the
  spot" from whatever is salient — normatively-equivalent elicitation methods give systematically different
  answers (preference reversals, framing effects). [Lichtenstein & Slovic, *The Construction of Preference*](https://www.cambridge.org/core/books/construction-of-preference/994FE8DFB8D431338B2A009F25271FBC);
  [Decision Research](https://www.decisionresearch.org/book-collection/the-construction-of-preference);
  [Slovic 1995](https://bear.warrington.ufl.edu/brenner/mar7588/Papers/slovic-ampsy1995.pdf).
- **Implication:** a "judgment model" partly fits noise and calls it taste. Showing "you usually pick X" at a
  fork *manufactures consistency with a past self* rather than eliciting present judgment.

### The elicited "why" is a confabulation generator — "human-confirmed" ≠ "genuine"
- **Choice blindness** (Johansson & Hall): people fluently produce "elaborate explanations" for choices they
  *never made* (jam/supermarket switch); confabulated reasons "seem completely plausible." [LUCS PDF](https://www.lucs.lu.se/fileadmin/user_upload/lucs/2011/01/Johansson-et-al.-2006-How-Something-Can-Be-Said-About-Telling-More-Than-We-Can-Know.pdf);
  [Social Science Space](https://www.socialsciencespace.com/2023/04/petter-johansson-on-choice-blindness/).
- **Rationale-driven preference manufacturing**: requiring a person to justify/label a choice "may actually
  *generate* preferences rather than reveal them. The act of articulating reasoning can cement preferences that
  didn't previously exist." [RLHF May Not Reflect Genuine Preferences, arXiv 2604.03238](https://arxiv.org/pdf/2604.03238)
  (builds on Slovic construction + Krosnick satisficing).
- **Acquiescence / satisficing**: people agree with a presented statement "when in doubt," especially with low
  prior info, to minimize effort; leading wording swings answers 13–18pp. [YouGov](https://yougov.com/articles/45308-how-leading-questions-and-acquiescence-bias-can-im);
  [Sage — Acquiescence Response Bias](https://methods.sagepub.com/ency/edvol/encyclopedia-of-survey-research-methods/chpt/acquiescence-response-bias).
- **Reusable rule:** to capture a *why* honestly, use **UNPROMPTED free-text first**; never show candidate
  rationales before the human's own attempt; a tapped candidate is `borrowed`, a distinct weaker class, and is
  excluded from any "your rationale" rendering. A confirm click does not launder a system-authored reason.

### Pre-select / default = a nudge, even when the user is free to change it
- Default effect: pre-selected option wins overwhelmingly (retirement enrollment 49%→86% on which box was
  pre-checked) via status-quo bias + loss aversion + cognitive-effort avoidance. [UX Magazine](https://uxmag.com/articles/the-psychology-of-defaults-how-pre-selected-options-influence-behavior);
  [Sue Behavioural Design](https://www.suebehaviouraldesign.com/en/blog/defaults-explained/). The presentation
  *frame* itself moves the effect size — [Framing the Default, PMC11612645](https://pmc.ncbi.nlm.nih.gov/articles/PMC11612645/).
- **Regulatory verdict:** preselection/pre-ticked boxes are a named dark pattern — "Silence, pre-ticked boxes
  or inactivity" do not constitute consent ([GDPR Recital 32](https://www.cookieyes.com/blog/dark-patterns-in-cookie-consent/)),
  now actionable in the EU ([dark-patterns regime](https://cbtw.tech/insights/illegal-dark-patterns-europe/)).
  Freedom-to-override is what pre-selection *exploits*, not what excuses it.
- **Reusable rules:** never render a literal pre-tick; phrase evidence as falsifiable dated history, not
  identity; prefer **pull (evidence-on-demand)** over push; re-arm any pre-select per session, never persist it
  as the resting state.

### Recommender feedback loop → ossification; the anti-echo metric must not be dark or contaminated
- Capture→distill→recall→highlight→capture *is* a feedback loop: preferences "continually reinforced," diversity
  "narrowed" over time. [TheSAI echo chambers](https://thesai.org/Downloads/Volume16No10/Paper_71-Understanding_Echo_Chambers_in_Recommender_Systems.pdf).
  **Lock-in Hypothesis**: "models learn human beliefs … reinforce … reabsorb … feed them back … again and
  again," with "sudden and sustained drops in diversity." [arXiv 2506.06166](https://arxiv.org/abs/2506.06166).
- **Automation complacency / learned helplessness**: "if the dashboard rewards acceptance, the workforce will
  learn acceptance"; users defer even against their own judgment; agency decays. [UXmatters 2026](https://www.uxmatters.com/mt/archives/2026/06/designing-for-doubt-how-to-prevent-automation-complacency-in-ai-workflows.php);
  [Springer 2025](https://link.springer.com/article/10.1007/s00146-025-02422-7).
- **Failure the metric hides:** a low override-rate is ambiguous — genuine agreement OR abandonment. As
  helplessness sets in, override-rate *drops*, which a naive demotion rule reads as "healthy."
- **Reusable rules:** (1) track a drift signal in *every* mode, not only where you nudge; (2) demote on a
  **recency-weighted, last-K disagreement rate**, not an all-time ratio; (3) add a **staleness trip** (expire a
  pattern not re-confirmed in > T days / > M forks) independent of override; (4) add an **active-doubt holdout**
  (periodically suppress the nudge and record the clean choice) — the exploration fix for feedback loops; (5)
  weight an *override* > a *match*, and never present any threshold as measured confidence.

### Modeling a person → bounded consent, dating, expiry, purge (digital-twin minimum bar)
- Static personal models "may not reflect evolving user preferences over time" ([Quirks](https://www.quirks.com/articles/expanding-informed-consent-in-the-age-of-synthetic-data-and-digital-twins));
  consent must be bounded/contextual ([Petrie-Flom — Predictive Persons](https://petrieflom.law.harvard.edu/2025/10/29/predictive-persons-privacy-law-and-digital-twins/));
  guardrail norm = person owns the copy + audit log + withdraw consent, under a "Minimally Viable
  Permissibility Principle" (consent, transparency, harm-mitigation, contextual integrity) ([TechPolicy.Press](https://www.techpolicy.press/digital-twins-demand-a-new-social-contract/)).
- **Git distribution IS egress.** A committed personal model ships a dated behavioral profile with every clone/
  fork/release. In-project precedent: v2.6.2 pulled machine-local personal fields *out* of the committed config
  after a downstream reviewer flagged them. Apply the same, more strongly, to a judgment model.
- **Reusable rules:** decide egress explicitly (local-only gitignored vs committed-with-consent, excluded from
  release build); date every pattern (first_seen/last_confirmed/expiry); one-command purge + per-pattern prune;
  visible "stale — last confirmed N months ago" banner; extend any secret-scan to PII in free-text fields.

### Net-value test for "model the creator / reason as the user" features
- Such a lane opposes a cross-model/anti-anchoring moat: it entrenches blind spots and produces "more X, not
  better designs." It flips **net-positive only** as a *falsifiable-memory aid*: on-demand dated history, never
  a "you value X" identity claim, never pre-select, and **paired with a mandatory divergent counter-move** so
  recall triggers challenge, not convergence.
