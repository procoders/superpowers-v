# Cross-Model Plan Review — the independent second opinion

A **different model family** (Codex/GPT) adversarially reviews a Compound V plan/manifest
*before* dispatch. The value is **error decorrelation**: a second Opus reviewer shares
Opus's blind spots; a Codex reviewer has different priors and catches what the planner's
own family does not see in itself. Proven in practice — on its first real run, Codex read
the repo and found a genuine bug in `compound-v-validate-manifest.py` that the Opus
planner had shipped.

**Codex is ADVISORY, never the authority.** It returns its opinion; the **orchestrator
arbitrates**. One model does not silently overrule another — a possibly-weaker reviewer
must not gain false authority. The orchestrator weighs each finding with context the
reviewer lacks.

---

## When to run it (gate by stakes — it is not free)

A max-effort GPT review costs real tokens and ~minutes. Run it ONLY for **high-stakes
plans**. Invoke when ANY of these hold:

- the plan touches **security / auth / payments / PII / migrations / shared data model**;
- the partition is **large or coupled** (≈4+ parallel tasks, or a serial shared-foundation task others depend on);
- the change is **architectural** (new subsystem, cross-cutting refactor);
- the **human explicitly asks** for a second opinion.

**Skip** for small, mechanical, or single-slice plans — the Opus `partition-reviewer` plus
the deterministic `validate-manifest.py` already cover those. A rule of thumb: run it when
the plan's riskiest job resolves to **tier `deep`**.

This sits in the three-layer plan check, each layer catching a different class of error:

| Layer | Who | Catches |
|---|---|---|
| Deterministic | `scripts/compound-v-validate-manifest.py` | hard invariants (disjoint write-scope, codex⇒worktree, reviewers⇒opus/deep) — no opinions |
| Primary judgment | `compound-v:partition-reviewer` (Opus) | decomposition sense, coverage |
| **Independent second opinion** | **Codex, tier `deep`, effort `high`** | the planner-family's own blind spots |

---

## How to run it

After `partition-reviewer` returns **PASS** and `validate-manifest.py` is clean, dispatch
the read-only cross-model review:

```bash
scripts/compound-v-codex-review.sh \
  --plan-file docs/superpowers/plans/<plan>.md \
  --repo "$PWD" \
  --effort high \
  [--context-file docs/superpowers/archaeology/<topic>.md] ...
```

- The model is resolved for **codex / tier `deep`** (e.g. `gpt-5.5`) — see [routing-policy.md](routing-policy.md). `--effort high` is "Codex on their strongest reasoning."
- Codex runs **read-only** (`--sandbox read-only`): it may READ the repo to ground each objection against the real files, but writes nothing.
- It returns structured findings per [`schemas/plan-review.schema.json`](../../schemas/plan-review.schema.json) — `verdict` (endorse | concerns | reject), a list of `findings` (each: `severity`, `category`, `claim`, `evidence`, `recommendation`), and `blind_spots_checked`.
- The reviewer is prompted to **refute** the plan, default to skepticism, and prefer concrete evidence; an empty `findings` list is honest and valid.

Or, for manual control: `/v:review-plan <plan-path>`.

---

## Arbitration (the rule — the orchestrator owns the decision)

Codex's `verdict` is **input, not a gate**. For EVERY finding the orchestrator MUST do one of:

1. **ACCEPT** — the objection is real → revise the plan / fix the issue, and record it.
2. **OVERRIDE** — the objection is wrong or already handled → record a **one-line rebuttal** with the reasoning (often using context Codex could not have: "this file was added by a later feature", "the worker already implements this fallback").

Then:

- **Escalate to the human** any **critical/high** finding the orchestrator wants to OVERRIDE — surface it explicitly; do not silently dismiss a high-severity objection.
- **Set the real verdict** yourself: Codex's `reject` may become "proceed with fixes" once the alarming finding turns out to be a false alarm; Codex's `endorse` does not waive the deterministic gates.
- **Record the arbitration** (accepted vs overridden + why) in the run's reasoning, so the decision is auditable.

The point is not "Codex corrects Claude." It is "Codex offers a decorrelated critique; the orchestrator, with full context, decides." Surfacing a real blind spot the planner's family misses is the whole return on the cost.

---

## Reusability

The contract is backend-agnostic. Today the reviewer is Codex; when the Antigravity adapter
lands (1.1), the same gated step can take an Antigravity reviewer (`agy`, tier deep) via the
same `plan-review.schema.json` findings shape — a third, further-decorrelated perspective.
