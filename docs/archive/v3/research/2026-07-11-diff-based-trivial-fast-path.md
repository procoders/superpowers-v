# Diff-Based Trivial-Change Detection (Fast-Path Eligibility)

**Date:** 2026-07-11. Research pass for the v2.9 fast-path design — the DIFF-level lane
(distinct from [request-level triage](2026-07-11-request-level-triage.md), which fires before any
code exists). Once a diff is produced, can deterministic structural signals classify it as trivial
and route it to reduced-ceremony review? Companion to the
[2026 orchestrator landscape synthesis](2026-07-11-2026-orchestrator-landscape-synthesis.md).

---

## 1. What real 2025-2026 systems use as signals

- **Meta RADAR (Risk Aware Diff Auto Review)** — [arXiv 2605.30208](https://arxiv.org/abs/2605.30208),
  [full text](https://arxiv.org/html/2605.30208v1). A multi-stage funnel:
  - **Eligibility gates (pre-ML, hard rules):** diff must not touch open-source code, not be
    SOX-scoped, not require additional reviews, not be WIP/RFC/previously-rejected; bot diffs must
    come from an "onboarded" automation source; runbooks tied to past incidents are permanently
    blocked.
  - **Static heuristics** on metadata/file-paths/thresholds (exact numbers undisclosed).
  - **Diff Risk Score (DRS)** — a fine-tuned Llama model predicting incident likelihood
    ([Meta eng blog](https://engineering.fb.com/2025/08/06/developer-tools/diff-risk-score-drs-ai-risk-aware-software-development-meta/)),
    19 downstream uses. Feature list/accuracy NOT public — the real gap.
  - **LLM Automated Code Review (ACR)** auto-accepts ONLY if classified entirely into a declared
    **safe-category allowlist** (refactor w/o behavior change, dead-code removal,
    defensive-programming, logging, pure formatting, doc/comment, import hygiene, test additions,
    static resources) AND scores ≥8/10. Any risk signal (complexity ≥4, structural change, secrets,
    SQLi, auth-bypass) disqualifies — the escape hatch.
  - Results: 60.31% auto-approve at the 50th-pct DRS threshold; 1/3 the revert rate, 1/50 the
    incident rate vs non-RADAR; 330%+ faster time-to-close.
  - "Blanket AutoAccept" bypasses per-diff review for deterministic codemods — trust in the *tool*,
    not the diff.
- **GitHub Copilot** — repo-level risk tier (low/medium) routes to lighter vs heavier review; "Agent
  Merge" drives CI-green + merge but keeps a human in the path ("Copilot not Autopilot"). Note: as of
  early 2026 standard content-exclusion filters DON'T apply to the autonomous cloud agent — a
  documented gap.
- **Cursor Bugbot** — stated policy: "low-risk PRs (such as a title change) can get auto-approved...
  high-risk PRs require human review"; classifier signals unpublished; identical-diff dedup +
  incremental "only what's new" mode. ([cursor.com/docs/bugbot](https://cursor.com/docs/bugbot))
- **Greptile** — contextual: same severity means more on payments vs an internal script; flags
  auth/roles/billing/webhooks/parsers/AI-agent-behavior/infra-permissions for elevated scrutiny — a
  path/domain-sensitivity multiplier on top of size.
- **CodeRabbit** — shipped, real config: `path_filters` globs, `path_instructions` per-dir,
  `ignore_title_keywords`, label exclusion (`wip`), a `risk:[critical,high,medium,low]` taxonomy with
  warn-vs-block enforcement. Clearest path-pattern-driven commercial implementation.
- **Google Gemini Code Assist** — "always comment, human decides"; no public trivial/risk routing
  gate found. (Individual tiers sunsetting mid-2026, consolidating into Antigravity.)
- **Graphite** — offload trivial style/lint to automated tools before human review; no diff-risk
  classifier gating ceremony found.

## 2. Structural features rival/beat semantic/LLM analysis — strong 2026 evidence

**"Early-Stage Prediction of Review Effort in AI-Generated Pull Requests"** (MSR 2026 Mining
Challenge, [arXiv 2601.00753](https://arxiv.org/html/2601.00753v1)). AIDev v1.0: 33,707 agent-authored
PRs, 2,807 repos.

| Model | Feature type | AUC |
|---|---|---|
| LightGBM structural-only | additions/deletions/changed_files/entropy, touches_tests/ci, file types, agent id | **0.9571** |
| Size-only baseline | log(total_changes) | 0.9330 |
| TF-IDF on title/description | text | 0.57 |
| CodeBERT embeddings on title/description | text | 0.52 |
| CodeBERT + structural | mixed | 0.957 (no better than structural-only) |

Authors' framing: "review burden is dictated by *what agents touch*, not what they *say*." **Caveat
they state:** per-repo generalization is weaker (median AUC 0.71, IQR 0.42-0.88); the 0.957 is a
pooled number; they recommend local per-repo calibration + exception workflows for large necessary
refactors. One strong MSR data point, not yet widely replicated.

**Corroborating:** the classic Cisco/SmartBear study (Cohen et al. ~2006) — defect-detection peaks at
200-400 LOC/session, drops sharply above ~400 (reviewer fatigue) — the oldest, most-replicated
structural signal. **JIT defect prediction** (Kamei et al. 2013,
[2022 survey](https://damevski.github.io/files/report_CSUR_2022.pdf)) independently converges on
structural features: diffusion (files/dirs/entropy), size, purpose (is-fix), history (prior defects),
experience. None require LLM semantics to be predictive.

## 3. Fast-path triggers vs escape hatches, from the wild

**Fast-path / definitely-trivial (real):** RADAR safe categories; RADAR Blanket AutoAccept for vetted
codemods; CodeRabbit `ignore_title_keywords`/label skip; Bugbot identical-diff dedup; Cisco 200-400
LOC ceiling.

**Escape hatch / escalation (real):** RADAR risk-signal auto-disqualify (complexity ≥4, secrets,
SQLi, auth-bypass) regardless of size + SOX/OSS hard-exclusion + permanently-blocked runbooks;
Greptile domain-sensitivity multiplier (auth/billing/webhooks/infra); GitHub CODEOWNERS tiered
enforcement (`*.sql` → data team, auth → 2 security approvals regardless of size); GitHub hard-blocks
Copilot from `.github/agents/` — "don't let the change touch the thing that governs review."

## 4. Proposed Compound V rule of thumb

**Fast-path eligibility (structural shape evidence-backed; exact thresholds are synthesis):**
- Files changed ≤ 3 AND total lines (added+deleted) ≤ ~50 (well inside Cisco's 200-400, deliberately
  conservative for a fully-automated gate)
- Zero path match against a **sensitive-surface denylist**: auth/session/credentials, payments/billing,
  DB migrations/schema, IaC/CI (`.github/**`, Terraform), permission/ACL, anything CODEOWNERS protects
- Classifiable into a **safe-category allowlist** (RADAR-analogous): formatting/whitespace,
  doc/comment-only, string/config-literal (version bump, copy), CSS/styling-only, test-only additions,
  import/dep-hygiene
- No new/changed control-flow branches, no new external calls, no changed function signatures
  (closest structural proxy to "no behavioral change" without semantic diffing)

**Escape hatch (any one → full ceremony):** any sensitive-path match regardless of line count; lines
exceed cap even if few files; touches orchestration/dispatch config itself (manifest schema,
scope-gate, routing policy) — modeled on GitHub's `.github/agents/` block; diff mixes safe-category +
non-allowlist changes in one commit (RADAR requires ALL-safe, not majority-safe).

**Evidence-backed vs synthesis, explicitly:** evidence-backed = structural-over-semantic, the
allowlist+escape-hatch shape, path-sensitivity multiplier, hard-blocking control-surface
self-modification. Synthesis = exact numbers (3 files/50 lines), the specific denylist, and the "no
new control-flow/signature" heuristic (no source gave a validated no-LLM behavioral-change detector —
best proxy, not proven).

## 5. Verdict: solid enough to ship with monitoring, thin at the edges

- The **general principle** (structural features predict review effort ≈ or > semantic; size+path
  heuristics are a legit first filter) has converging support: MSR 2026 (0.957 vs 0.52-0.57), Meta
  RADAR (measured outcomes), Cisco/SmartBear (2 decades), JIT defect prediction (a whole subfield).
- **Not well-evidenced publicly:** the exact thresholds. No source gives a validated N-files/M-lines
  cutoff; Meta doesn't publish DRS bands; the MSR authors flag weak per-repo generalization and
  recommend local calibration. Any concrete threshold shipped is a hypothesis, not a citation.
- **Scale caveat:** RADAR's wins ride on Meta-scale inputs (author-tenure DB, per-file defect history,
  SOX registry) Compound V won't have — expect a meaningfully lower real-world hit rate until the
  path lists and thresholds are tuned against Compound V's OWN scope-gate logs.

**Recommendation:** build the deterministic gate as a *conservative, monitored* first pass — bias
toward full ceremony on ambiguity — and calibrate thresholds against Compound V's own scope-gate
history over time, exactly as the MSR paper recommends local calibration over a global number.
