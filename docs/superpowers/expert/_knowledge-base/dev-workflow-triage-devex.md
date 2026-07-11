# Developer-Workflow Triage / DevEx Knowledge Base

How an automated gate should classify a coding request as trivial-vs-not and offer a
reduced-ceremony fast lane: confirmation-prompt fatigue, mid-flight escalation cost, latency
tolerance, and the "small change that is actually high-impact" taxonomy.

Maintained by Compound V Phase 1B advisor. Append at the bottom on each pass.

---

## Updated 2026-07-11 — pre-evaluation fast-path offer (v2.9 audit)

### Confirmation-prompt / gate fatigue is the headline DevEx risk of "ask on every request"
- **Approval fatigue is measured, not hypothetical.** Anthropic's own Claude Code telemetry: users
  approve **~93%** of prompts, and "as approvals increase, attention to each dialog wanes" — the
  dialog degrades into reflexive "y-spamming." Verbatim confirmed via
  [note.com analysis of Cursor 3.6 / Anthropic research](https://note.com/marusho_1266/n/nf4845bd739b3?hl=en).
  Design implication: a prompt fired on *every* trivially-classified request trains the developer to
  rubber-stamp it, which quietly destroys the honesty value of "never auto-route" — a rubber-stamped
  offer is a de-facto auto-route.
- **The industry is actively removing per-action prompts, not adding them.** OS-level sandboxing cut
  Claude Code permission prompts by **~84%**; Cursor 3.6 Auto-review routes through
  Allowlist→Sandbox→LLM-classifier explicitly to reduce "y-spamming." The DevEx direction of travel
  in 2026 is *fewer* interruptions on low-stakes actions, gated by a trust boundary rather than a
  human click. Source: same note.com analysis + search corroboration.
- **Alert-fatigue mechanism generalizes to any noisy gate.** "If a tool output contains a high amount
  of false positives, engineers assume the rest are also inaccurate and ignore the output"
  ([arXiv 2107.02096, security-tool-in-DevOps study](https://arxiv.org/pdf/2107.02096)); 2025 SANS
  survey: **73%** of teams name false positives as their top detection challenge
  ([Cycode](https://cycode.com/blog/stopping-alert-fatigue-3-simple-steps/),
  [Vectra](https://www.vectra.ai/topics/alert-fatigue)). A triage gate that cries "trivial!" and is
  wrong, or "confirm?" too often, desensitizes the same way.
- **Reusable rule:** an offer-style gate is only honest if it is *rare and high-signal*. Options that
  preserve the never-auto-route invariant WITHOUT training rubber-stamping: (a) remember-my-choice per
  taxonomy-category (Linear's per-property opt-in auto-apply pattern), (b) a silent-below-a-floor lane
  with a visible undo, (c) folding the offer into an interaction the developer is *already* having
  (the recon/clarify turn) so it costs zero extra context switches. The last is cheapest and is what
  the v2.9 spec already does — keep it; do NOT add a standalone offer screen.

### Mid-flight escalation ("actually this needs the full pipeline") — trust cost is real but survivable
- No single study measures "fast-path revoked mid-flight" satisfaction directly (evidence gap — flag).
  Reasoned synthesis from adjacent evidence:
- **Context-switch cost is the tax you pay if you escalate late.** Recovering from an interruption
  averages ~23 min; developers lose 15–30 min of productive coding per switch; flow takes ~15 min to
  reach and one notification breaks it ([Axolo](https://axolo.co/blog/p/cost-context-switching-developer-workflow),
  [Techworld-with-Milan](https://newsletter.techworld-with-milan.com/p/context-switching-is-the-main-productivity)).
  So an escalation that arrives *after* the developer has mentally moved on is the expensive kind.
- **Escalation on real evidence (the diff) is the trustworthy kind.** Every shipped system keeps the
  hard escape-hatch on structural/real-diff signal, not on the cheap pre-diff guess (Meta RADAR
  risk-disqualify; Cursor Bugbot high-risk→human; CODEOWNERS). Design implication: escalation should
  fire as *early as the diff allows* and be framed as "the safety net worked," not "we were wrong" —
  the alternative (never offering, or offering then silently downgrading review) is worse for trust.
- **Trust asymmetry:** a fast-path false-NEGATIVE (said trivial, shipped a bug) is far more corrosive
  than a false-POSITIVE (ran full ceremony on something trivial — merely annoying). Bias the gate
  toward full ceremony; the MSR-2026 and RADAR designs all encode this asymmetry.

### "Trivial" traps — surfaces where a tiny diff is high-impact that a dir-structure scan misses
A path-pattern list keyed on directory structure (auth/, payments/, migrations/) will MISS these
because the risk lives in the *content/semantics* of a small string edit, not the file's location:
- **Legal / compliance copy** (ToS, disclaimers, consent text, license strings, cookie banners). Legal
  sources are explicit that single-word choices carry substantive liability weight — "design
  professionals must draw disclaimer language as carefully as the rest of the package"
  ([IRMI](https://www.irmi.com/articles/expert-commentary/design-disclaimers-and-implied-warranties)).
  A one-word edit to a consent string can be a GDPR/regulatory change, not a copy tweak.
- **i18n / l10n strings — especially interpolation placeholders.** Deleting/altering a `{{var}}` /
  `%s` placeholder "risks crashing the application, displaying raw code, or nonsensical output";
  interpolating before the translation call causes silent lookup misses; a library minor bump changed
  undefined-variable handling and broke interpolation
  ([i18next best-practices](https://www.i18next.com/principles/best-practices),
  [Crisol on placeholders](https://www.crisoltranslations.com/our-blog/placeholders-how-to-translate-around-them/),
  [i18next#1721](https://github.com/i18next/i18next/issues/1721)). A "just a string" change to a
  message catalog fans out to every locale and can crash on grammar/gender/plural rules the English
  author never sees.
- **Accessibility names/labels (aria-label, alt).** `aria-label` **overrides** native naming (alt,
  `<label for>`); a small edit can silently break WCAG SC 2.5.3 Label-in-Name / 4.1.2 Name-Role-Value,
  and "incorrect ARIA is often worse than no ARIA"
  ([Level Access](https://www.levelaccess.com/blog/aria-labels-and-accessible-names-a-developers-guide/),
  [W3C ARIA6](https://www.w3.org/TR/WCAG20-TECHS/ARIA6.html)). (v2.9 already lists a11y — this is the
  *why*.)
- **Feature-flag definitions / defaults.** A flag default flip is a one-line change with production
  blast radius: Google's June 2025 global GCP outage (3+ hrs) was a policy change that "was not
  feature-flag-protected"; PostHog had four flag-service incidents in 10 days (14+ hrs impact)
  ([Google/Unleash](https://www.getunleash.io/blog/google-outage-feature-flags),
  [PostHog post-mortem](https://posthog.com/handbook/company/post-mortems/2025-10-21-feature-flags-recurring-outages)).
- **Config / constant literals** (timeouts, pricing constants, quotas, rate limits, retry counts). A
  DB connection-timeout change from 1s→300ms triggered a cascading PostHog outage
  ([PostHog Sep-2025](https://posthog.com/handbook/company/post-mortems/2025-09-29-flags-is-down));
  AWS's 2017 S3 outage was a single mistyped command param. Config changes are a top outage class
  ([CloudTruth](https://cloudtruth.com/blog/how-often-does-a-change-to-a-configuration-file-cause-a-production-outage/)).
- **Brand / contrast-bearing "cosmetic" values.** A color hex is not always cosmetic: it can be a
  brand-token or a WCAG contrast-ratio surface (v2.9's "make button X red" case). Already handled by
  the shared-token/a11y override — generalize the caveat to any *design-token* file.
- **Generalized rule:** the high-impact axis must be decided on *what the change semantically IS*
  (localization already resolves this), not only *where the file lives*. Legal-copy, i18n-catalog,
  flag-definition, and config-constant surfaces belong on the sensitive taxonomy's **content-pattern**
  side, complementing the path-pattern side.

### The two-axis (difficulty × impact) framing — sound; watch for one latent axis
- Difficulty⊥impact matches how practitioners reason (Greptile: "same severity means more on payments
  vs an internal script" = impact independent of difficulty). Do NOT over-axis.
- **The one axis worth naming explicitly is reversibility / blast-radius**, and it is largely already
  *inside* "impact" — but note the two can diverge: a change can be low product-impact yet
  irreversible/wide-blast (a data migration, a flag default that changes persisted state, a cache-key
  format). Every production system encodes this as a hard eligibility gate, not a score axis: RADAR
  permanently blocks incident-runbooks and SOX scope; GitHub hard-blocks edits to `.github/agents/`
  ("don't let the change touch the thing that governs review"). Design implication: keep it as a
  fail-closed *override* (which v2.9 does — sensitive-path + control-surface self-modification), NOT a
  third score axis. Reversibility is a gate, not a coordinate.

### Latency budget for an inline pre-flight gate
- **Nielsen's limits (stable since 1968):** 0.1s = feels instant; **1.0s = the ceiling for keeping the
  user's flow of thought uninterrupted**; 10s = the ceiling for holding attention at all (needs a
  progress indicator beyond that)
  ([NN/g](https://www.nngroup.com/articles/response-times-3-important-limits/)). An inline gate that
  runs *before the developer's request proceeds* should target **≤1s** to stay inside flow; a
  deterministic-tier-only pre-eval (ripgrep+glob+git+YAML+FTS5, zero model calls) is well inside this.
  The rare Tier-3 model call is the latency risk — it must stay off the common path (v2.9 reaches T3
  only when `T1 unclassified ∧ T2 insufficient`, correct) and should show a "checking…" affordance if
  it can exceed ~1s.
- Any pre-flight slower than the flow ceiling *is itself* the ceremony the fast-path exists to remove.

### Cross-checks against shipped triage systems (what "everyone" does)
- **Suggestion, never silent auto-route:** Linear Triage Intelligence (per-property opt-in), Azure
  DevOps Auto-Triage (0.75 confidence threshold + human queue below), Devin/Copilot (human-judged).
  Confirms v2.9 Iron-Invariant #4.
- **Structural ≫ text signal:** MSR-2026 structural AUC 0.957 vs text 0.52–0.57
  ([arXiv 2601.00753](https://arxiv.org/html/2601.00753v1)); prefer the diff-lane signal whenever a
  diff exists (v2.9 post-hoc re-classification is the right lever).
- **All-safe, not majority-safe:** RADAR auto-accepts only if the ENTIRE diff falls in a
  safe-category allowlist; any single risk signal disqualifies. v2.9's conservative-max
  (never-average-down) mirrors this — keep it.
