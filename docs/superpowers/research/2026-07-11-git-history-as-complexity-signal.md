# Git Commit History as a Complexity/Risk Signal for Pre-Evaluation

**Date:** 2026-07-11. Research pass for the v2.9 Pre-Evaluation design, triggered by the user's
question: for existing (non-greenfield) repos, can `/v:onboard` mine git commit history —
per-path churn, revert density, fix/bug-message density — as an empirical signal for which
areas of a codebase are historically risky/complex, feeding the Pre-Evaluation scoring?

Companion to the [2026 orchestrator landscape synthesis](2026-07-11-2026-orchestrator-landscape-synthesis.md).

---

## 1. "Code churn as a defect/risk predictor" is real, multi-decade, still-active research

- **Nagappan & Ball, "Use of Relative Code Churn Measures to Predict System Defect Density,"**
  ICSE 2005 ([ACM DL](https://dl.acm.org/doi/10.1145/1062455.1062514),
  [MSR](https://www.microsoft.com/en-us/research/publication/use-of-relative-code-churn-measures-to-predict-system-defect-density/)).
  **Load-bearing nuance:** *absolute* churn (raw lines/commits changed) is a POOR predictor;
  only a set of *relative* churn measures (churn normalized against component size, temporal
  extent) discriminated fault-prone Windows Server 2003 binaries — at 89.0% accuracy. A naive
  raw-commit-count implementation reproduces the paper's NEGATIVE result, not its positive one.
- **Mockus & Weiss, "Predicting Risk of Software Changes,"** Bell Labs Tech Journal 2000
  ([PDF](https://mockus.org/papers/bltj13.pdf)) — origin of the change-level ("just-in-time")
  framing: failure probability of a *change* from size, diffusion across files/modules, developer
  experience, change type (fix vs. new).
- **Kamei et al. 2013** systematized **Just-In-Time (JIT) Defect Prediction** — 14 change-level
  metrics ([2022 survey](https://damevski.github.io/files/report_CSUR_2022.pdf)).
- **Rahman & Devanbu, "How, and Why, Process Metrics Are Better,"** ICSE 2013
  ([PDF](https://research.cs.queensu.ca/home/ahmed/home/teaching/CISC880/F17/papers/HowAndWhyProcessMetricsAreBetter.pdf))
  — across 85 releases of 12 large OSS projects, **process (churn/history) metrics outperformed
  static code metrics** as defect predictors. Directly relevant to the greenfield-vs-existing
  split: process metrics need history greenfield code doesn't have yet.
- Still active in 2026: MSR '26 ["Source Code Hotspots"](https://arxiv.org/pdf/2602.13170)
  (April 2026, peer-reviewed churn-hotspot diagnostic); Yang et al. 2024 weighted-churn +
  metaheuristic JIT prediction ([PMC](https://pmc.ncbi.nlm.nih.gov/articles/PMC11422029/));
  June 2026 ["Code Lifespan Survival Analysis"](https://arxiv.org/abs/2606.04993).

**Verdict on the evidence base: high confidence, real, replicated 2000→2026.**

## 2. What current (2025-2026) tools actually do with git history

- **CodeScene** (Adam Tornhill, *Your Code as a Crime Scene*) — the flagship commercial product:
  **Hotspots** = high commit-frequency files cross-referenced against a static Code Health score
  ([docs](https://codescene.io/docs/guides/technical/hotspots.html)). Their docs warn hotspot
  accuracy degrades with incomplete history — a real operational caveat for shallow clones.
- **Meta RADAR / Diff Risk Score (DRS)** — [arXiv 2605.30208](https://arxiv.org/pdf/2605.30208)
  (June 16, 2026). **The strongest current industrial evidence:** DRS uses git-history signals
  (churn, file change frequency, past defect/revert history on a region) + author expertise +
  complexity to gate ~20 risk-aware workflows including auto-approve. This is the production
  analog of Pre-Evaluation's intent, at scale, in 2026, with a citable paper.
- **GitLab** — churn/hotspot→MR-risk is a REQUESTED-but-unshipped feature
  ([issue #13387](https://gitlab.com/gitlab-org/gitlab/-/issues/13387)); shipped Code Quality is
  static-analysis-based, not churn-based.
- **Google** — no citable Google-specific churn-risk paper found (Critique is their review tool;
  general risk-in-review literature uses size/diffusion/experience features industry-wide).
  Flagged UNVERIFIED, not asserted.
- **AI PR-review tools (CodeRabbit/Greptile/Graphite)** — no evidence any publishes churn as an
  explicit risk signal; could not confirm/deny internals. UNVERIFIED.
- Prior-art OSS: [`gitrisky`](https://github.com/hinnefe2/gitrisky) (git metadata → RandomForest,
  needs labeled bug-fix commits — has an ML step, not purely deterministic); a "commit-prophet"
  personal project computing a deterministic 0-100 score with keyword fix-detection
  (`fix|bug|patch|error|...`) — structurally close, but small/unvetted.

## 3. Known failure modes / criticisms (real skepticism, not just proponents)

- **Confounds "active/healthy" with "risky."** Converged across sources: "High churn can result
  from positive activities such as feature development... or from negative issues like frequent
  bug fixes" ([Swimm](https://swimm.io/learn/developer-experience/how-to-measure-code-churn-why-it-matters-and-4-ways-to-reduce-it)).
  The MSR '26 hotspots paper states this about its OWN method: "raw churn metrics alone may
  mislead without understanding the underlying reasons."
- **Project-phase confound.** Churn is structurally higher in prototyping, lower in maintenance —
  same number, opposite meaning at different lifecycle stages.
- **Nagappan & Ball's own result is the caution**: raw/absolute churn was a *poor* predictor;
  only size-normalized relative churn worked.
- **The hot-config/core-module false positive** (a central router/config every feature touches
  getting flagged "risky" from diffusion alone) follows directly from "churn ≠ risk without
  context" — flagged as inference from the general literature, not a verbatim-quoted scenario.
- **Cross-project generalization is a known weak point** of the defect-prediction field — less
  relevant here (single-repo, no model transfer), but worth knowing.

## 4. Cheap deterministic computation — feasible, with one trap to avoid

Fits a "deterministic tiers, no LLM judgment" design IF you avoid one specific trap:
**do NOT run `git log --follow` per-path repeatedly** (O(files × history)). The correct pattern
(used by CodeScene, [`git-churn`](https://github.com/andymeneely/git-churn),
[`churn-charts`](https://github.com/softvis/churn-charts)):

- **One single pass** over history: `git log --all --numstat --format='--%H--%ct--%s'`, parsed
  once into a per-path table of commit count, lines +/-, and a fix/revert flag from the subject
  (`grep -iE 'fix|bug|revert|hotfix|patch'` on `%s` + `git log --grep` for real `git revert`
  commits, which carry a recognizable "This reverts commit ..." body).
- This is ONE traversal of the commit DAG — cost scales with total commit count, not
  files×commits. Git's `commit-graph` mitigations exist for the very-large-history case
  ([git perf](https://blog.gitbutler.com/git-tips-3-really-large-repositories)). Typical product
  repo (tens of thousands of commits): low-single-digit seconds to tens of seconds.
- **Pre-Evaluation shape**: compute once per repo (or incrementally from a stored "last SHA"
  pointer), persist a per-path table (JSON/SQLite) as a cache, then Pre-Evaluation does an O(1)
  lookup against the touched paths. One-time O(commits) cost → O(1) steady-state per evaluation.
- **Normalize** (per Nagappan & Ball): commits/day-since-creation and/or by size — never raw
  counts, or you hit the "old large healthy file looks riskiest" failure mode.
- No verified current wall-clock benchmark for this exact `--numstat` pattern at a given repo
  size was found — reasoned from adjacent git-log-perf evidence. Recommend a quick empirical
  timing test on the real target repos before deciding sync-vs-background/cache.

## 5. Verdict: recommend WITH caveats (feeds a tier, never a standalone gate)

**For:** best-evidenced class of defect signal in empirical SE, replicated 2000→2026; a real
2026 production system (Meta RADAR/DRS) uses exactly this signal in exactly this gating role;
genuinely deterministic and cheap once-and-cached; free once indexed, no external API.

**Caveats (why not unconditional):**
- The single most load-bearing finding (Nagappan & Ball) says the *naive* version (raw churn)
  doesn't work — only normalized does. Raw commit counts risk the exact hot-but-healthy-file
  false positive already worried about, the #1 documented criticism.
- Must be a **contributing input weighted alongside** the static taxonomy and outcome-history
  tiers, never a standalone verdict — every source (incl. pro-churn CodeScene and the MSR '26
  paper) converges on "context matters, don't use raw churn alone." Maps onto the existing tiered
  design: git-churn *feeds* tier 2 (historical), never solely triggers fast/heavy pathing.
- Fix/revert-keyword mining is inherently noisy (free-text matching) — weak secondary signal;
  normalized churn frequency is the better-evidenced primary of the two.

**Bottom line:** worth building, as a **normalized-churn + fix/revert-density signal that feeds
into (not replaces)** the tiered scoring, computed once per repo via a single `git log --numstat`
pass and cached in the `/v:onboard` output — not as a standalone gate, and not using raw counts.
