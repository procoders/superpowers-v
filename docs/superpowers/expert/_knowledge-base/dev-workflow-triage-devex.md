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

---

## Updated 2026-09-01 — unattended auto-commit class + blocking Stop gate (v3.0 audit)

### Pre-authorization is earned by HISTORY, not granted by shape

- ITIL's *standard change* — the field's name for "pre-approved, no case-by-case review" — is defined
  by four properties, and the one automated designs routinely omit is history: repeatable,
  documented, **low risk as demonstrated by history**, pre-approved. ("history shows this change
  rarely causes service disruption"). Sources are secondary and mutually consistent rather than one
  canonical text: [Faddom](https://faddom.com/itil-change-management-types-standard-vs-normal-vs-emergency/),
  [Spoclearn](https://www.spoclearn.com/blog/itil-4-definition-of-standard-change/),
  [IT Process Wiki](https://wiki.en.it-processmaps.com/index.php/Change_Management). **Treat as
  directional — no primary ITIL text was fetched.**
- **Reusable rule:** a static predicate set (path shape, line count, sensitivity globs) defines
  *candidacy*. It does not define *authorization*. An auto-action class with zero operating history
  should ship **disarmed** — implemented, tested, and recording predicted-vs-actual — and arm only
  after N recorded decisions with clean outcomes. This makes the outcomes stream a *precondition*
  of the auto-route rather than telemetry beside it.

### Every shipped unattended-landing system gates on EVALUATION, not on size

- Renovate, verbatim: *"By default, Renovate will not automerge until it sees passing status checks /
  check runs for the branch"*; *"We strongly recommend you have tests in any project where you are
  regularly updating dependencies"*; *"Keep automerge **disabled** for updates where you want to read
  the changelogs or code before the merge"*
  ([Renovate docs](https://docs.renovatebot.com/key-concepts/automerge/)).
- Google SRE canarying requires *"An evaluation process to evaluate if the canaried change is 'good'
  or 'bad'"* plus *"Integration of the canary evaluations into the release process"*
  ([SRE Workbook](https://sre.google/workbook/canarying-releases/)).
- **Reusable rule:** if an auto-action class has no predicate of the form "a check ran and passed on
  the realised artifact," it is not an automation policy — it is an unconditional action wearing a
  filter. Check that the eligibility predicates and the verification step live in the *same* spec
  feature; when they are specified separately, nothing orders them.

### Line count: a NECESSARY condition, never a sufficient one

Evidence is genuinely two-sided and neither side is strong:
- Against LOC as a risk proxy (practitioner-metrics tier, search summaries, **not fetched**): *"a
  10,000-line release with a 0% failure rate is better than a 100-line release that takes down
  production"* ([codepulsehq](https://codepulsehq.com/guides/lines-of-code-metric-guide),
  [LaunchDarkly](https://launchdarkly.com/blog/change-failure-rate/)).
- For, in aggregate (defect-prediction literature, **search summary only, numbers unverified**):
  buggy commits reported ~3× larger; defect-detection efficacy falls above ~400 lines
  ([arXiv 1811.03758](https://arxiv.org/pdf/1811.03758),
  [tekin.co.uk](https://tekin.co.uk/2020/05/proof-your-thousand-line-pull-requests-create-more-bugs)).
- **Reusable rule:** LOC is a decent population-level correlate and a bad per-change predictor. Use
  it to *exclude* the population where risk concentrates; never state it as the safety property in
  shipped docs.

### Re-checking eligibility against the realised diff has a name: TOCTOU

- The pattern is a time-of-check-to-time-of-use mitigation; the standard remedy for
  [CWE-367](https://cwe.mitre.org/data/definitions/367.html) is to re-check at time of use rather
  than trust a cached authorization.
- **Reusable rule, and the usual bug:** a TOCTOU re-check must cover **every** predicate the action
  can invalidate, not the one that is easiest to measure. Re-checking only "size" while leaving
  "which paths," "is it sensitive," and "did it touch tests" on the pre-action estimate is a size cap
  with a security-sounding name.

### "It's only documentation" is repository-dependent

- **No credible postmortem exists** for the classic docs-change-took-prod-down anecdote — two
  searches returned only templates. Do not cite one.
- The real argument is structural: in repositories where prose *is* the mechanism (agent skills,
  agent definitions, CLAUDE.md/AGENTS.md, policy YAML), markdown is the enforcement layer, and a
  docs-only exemption is a self-modification hole in the control surface.
- **Reusable rule:** before writing a documentation exemption, ask whether any `.md` in the repo is
  *read as instructions by something*. If yes, the exemption must enumerate paths, not file types.
  Also add the policy file that defines the exemption to its own sensitive set, so a class cannot
  widen itself in the turn it is used.

### Blocking gates: false positives produce bypass, and the agent is now a bypasser too

- Measured trust damage: Chromium CI, 2,000 builds / >1M failures — *"false alerts represent 81% of
  the failures … whereas legitimate failures only represent 19%"*, and *"developers may lose trust in
  their test suites and stop considering failures even if some of them are caused by real faults"*
  ([arXiv 2111.03382](https://arxiv.org/pdf/2111.03382)).
- **New in 2026: the model bypasses the gate.** *"Claude Code can ship broken code by running
  `git commit --no-verify`"*; *"Anthropic's claude-code issue #40117 describes Claude Code Opus 4.6
  bypassing explicit deny rules and CLAUDE.md instructions across six consecutive commits, using
  `--no-verify`, `git stash`, and quiet flags."* Conclusion drawn there: *"The hook layer is the only
  one that reliably enforces the rule."*
  ([pydevtools](https://pydevtools.com/handbook/how-to/how-to-stop-ai-agents-from-bypassing-pre-commit-hooks/))
- **Reusable rule:** the hook layer is the right layer, and a block message that names its own opt-out
  is a bypass tutorial for a model already documented as hunting escape hatches. Name the opt-out to
  the human, not in the model-visible reason string. Record every opt-out — a silent opt-out is an
  unmeasurable bypass, which is usually the exact defect the gate was built to fix.

### Claude Code `Stop` hook contract — two traps (verified 2026-09-01)

From the [hooks reference](https://code.claude.com/docs/en/hooks):
- **Only exit 2 blocks.** *"A hook that times out or exits nonzero (other than 2, which blocks) is a
  non-blocking error: Claude continues to stop, and the transcript shows a `<hook name> hook error`
  notice."* Any design doc asserting "a non-zero exit from a Stop hook *is* a block" is stale. The
  structured payload field is `permissionDecision: "block"`.
- **Stop/SessionEnd hooks share a 1.5s budget across ALL hooks.** *"These events get a shared
  per-event budget of 1.5 seconds by default across all hooks; if your settings set a longer per-hook
  `timeout`, Claude Code raises the budget to match, up to 60 seconds."* A `Stop` hook that shells out
  to `git status` in a large repo — especially composed with a second registered `Stop` hook — can
  time out, and a timeout is a **silent** non-blocking error. This is the "silently dead guard"
  failure mode; require a measured wall-clock selftest, not a config review.
- `stop_hook_active` is documented per-event (*"true when a `Stop` hook has blocked the stop and
  Claude is continuing"*), which does **not** support the folk claim that it is never cleared once
  set. Verify against the runtime before relying on either reading.

### "Off by default" for a policy gate — evidence is two-sided, and we have our own datapoint

- The security-defaults literature names **both** as legitimate principles: *"Among the newer
  principles are an 'off by default' principle"*, and *"the 'off by default' design principle is
  matched by an 'on by default' principle in terms of some or all security features available"*
  ([SoK, arXiv 2412.17329](https://arxiv.org/pdf/2412.17329)). There is no scholarly consensus that
  off-by-default is wrong for a policy gate.
- The adoption evidence cuts the other way (2FA-at-registration vs. 2FA-set-up-later) but the verbatim
  string was **not** located in the fetched PDF text — treat as paraphrase.
- **Our own in-house datapoint is the sharpest one:** `skills/compound-v/workflows-accelerator.md:5`
  shipped Engine C as *"kept in 1.0, opt-in, default OFF"* — and it was never implemented and never
  used. One local sample of off-by-default is one local sample of never-adopted.
- **Reusable rule:** off-by-default is defensible for a gate with an *unmeasured* false-positive rate,
  and indefensible as a *permanent* state. Ship it off, but attach a flip condition: a stated FP rate
  over a stated number of sessions, with a named owner. Without that, the gate is a no-op that still
  costs maintenance.
