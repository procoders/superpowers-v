# Request-Level (Pre-Diff) Difficulty/Impact Triage

**Date:** 2026-07-11. Research pass for the v2.9 Pre-Evaluation design — the REQUEST-level lane,
which fires before any code/diff exists, using only the request text + retrieved project context to
predict difficulty and product impact. Distinct from (and, per this research, weaker than)
[diff-based classification](2026-07-11-diff-based-trivial-fast-path.md). Companion to the
[2026 orchestrator landscape synthesis](2026-07-11-2026-orchestrator-landscape-synthesis.md).

**Headline: request-level triage is the LEAST reliable signal tier — it must only OFFER a choice,
never auto-route, and must be grounded in retrieved history, not a cold read of request text.**

---

## 1. Text-only difficulty prediction is real but markedly weaker than diff-based

- Story-point-from-text is an active subfield. **GPT2SP** (GPT-2, text-only) reports median MAE 1.16,
  cross-project MAE 2.14 vs Deep-SE's 3.5 across 23,313 issues / 16 projects
  ([GPT2SP](https://www.researchgate.net/publication/359069565_GPT2SP_A_Transformer-Based_Agile_Story_Point_Estimation_Approach))
  — non-trivial signal, but errors of 1-3.5 points are large on a 1-2-3-5-8 scale.
- **Cleanest text-vs-structure comparison:** [arXiv 2601.00753](https://arxiv.org/html/2601.00753v1)
  (33,707 PRs) — structural AUC **0.9571** vs text AUC **0.57 (TF-IDF) / 0.52 (CodeBERT)**, a >40-point
  gap; text+structure barely beats structure alone. "Review burden is dictated by what agents touch,
  not what they say." (PR-open-time, not pure request-time — but the gap would likely be *larger*
  before any diff exists.)
- JIT defect prediction: commit *code* dominates commit *message* text
  ([arXiv 2410.12107](https://arxiv.org/html/2410.12107v1)).
- No study found where text-only matched or beat diff/code-based prediction.

## 2. Real products: suggest, don't silently auto-route

- **Devin** — human rule of thumb ("if you can do it in three hours, Devin can"), no published pre-code
  auto-difficulty model ([docs](https://docs.devin.ai/get-started/devin-intro)).
- **GitHub Copilot** — guidance tells *developers* to hand-judge complexity before assigning; not an
  automated classifier.
- **Linear Triage Intelligence** — the most concrete automated request-time system: semantic search over
  historical backlog + LLM to suggest team/project/assignee/labels + duplicates; **suggestion-based with
  per-property opt-in auto-apply**, NOT priority/difficulty prediction, NOT silent routing
  ([docs](https://linear.app/docs/triage-intelligence)).
- Azure DevOps Auto Triage — **0.75 confidence threshold** with human-queue escalation below it.

## 3. Impact is harder to predict than difficulty (reasoned synthesis, not a directly-measured finding)

- No paper frames this as a named two-axis comparison (explicit evidence gap).
- Adjacent support: bug-priority-from-text tops out at **F1 ~0.65** (BERT, 85K Eclipse bugs), degrades
  on cross-project data, and impact ground-truth is often *missing entirely* on GitHub/GitLab
  ([arXiv 2504.15912](https://arxiv.org/html/2504.15912v1)). [Triage/arXiv 2604.07494](https://arxiv.org/html/2604.07494v1)
  states the mechanism: "issue descriptions may not name target files, requiring heuristics whose
  accuracy bounds effectiveness" — knowing *which* surface is touched (needed for impact) requires info
  the text frequently omits.

## 4. Retrieval-grounding measurably improves prediction — the one strong positive lever

- [Search-based Optimisation of LLM Learning Shots](https://arxiv.org/abs/2403.08430) — optimizing
  few-shot examples improved story-point MAE by **59.34% avg** vs zero-shot (could not verify whether
  selection was similarity/retrieval-based specifically — flagged).
- Linear rebuilt Triage Intelligence around **retrieving similar historical issues** precisely because
  cold, ungrounded prediction was insufficient ([how-we-built](https://linear.app/now/how-we-built-triage-intelligence)).
- Adjacent RAG/few-shot corroboration in NER and vuln-detection.

## 5. Verdict + design implication

Request-level triage is real but the weakness is **measured, not assumed**: the closest text-vs-structure
comparison shows a >40-point AUC gap; impact-from-text tops out at F1 ~0.65 with shaky ground truth; and
every real production system doing anything similar keeps a human-confirmation step (Linear opt-in, Azure
0.75-threshold, Devin/Copilot human-judged).

**Design implications for Compound V:**
- Treat request-level triage as the **least reliable signal tier** — weaker than diff-based
  classification, which is preferred whenever a diff already exists.
- It must **only ever OFFER a fast-path vs full-pipeline choice, never silently auto-route** — consistent
  with the existing `AGENTS.md` principle "Recall is evidence for planning + review, never a routing
  input."
- Ground it in **retrieved historical similar-task context (V-memory)**, not a cold read of the request
  text — the one lever with a real, measured, positive effect.
