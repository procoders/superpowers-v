---
description: Run an independent cross-model (Codex) adversarial review of a Compound V plan/manifest before dispatch, then arbitrate the findings. Codex advises; the orchestrator decides.
---

You are running a **cross-model plan review** on `{{args}}` — an independent second opinion from a different model family (Codex/GPT), per [cross-model-review.md](../skills/compound-v/cross-model-review.md).

> Run it on demand, or **automatically before dispatch** when the project set `review.cross_model: true` at [`/v:init`](v-init.md) Step 3c (read from `.claude/compound-v.json`). Either way the stakes check below still applies — skip small/mechanical plans.

## Steps

1. **Resolve the plan path.** Use `{{args}}`; if empty, list `docs/superpowers/plans/*.md` and ask which to review.

2. **Stakes check (gating).** Confirm this plan warrants a cross-model review (security/auth/payments/migrations, large/coupled partition, architectural change, or the user asked). If it's small/mechanical, say so and recommend skipping — the Opus `partition-reviewer` + `validate-manifest.py` already cover it.

3. **Dispatch the read-only Codex reviewer:**
   ```bash
   scripts/compound-v-codex-review.sh --plan-file "<plan>" --repo "$PWD" --effort xhigh
   ```
   (Add `--context-file <audit>` for any archaeology/domain/library audits that ground the review.) The model is resolved for codex / tier `deep`. Codex reads the repo read-only and returns findings JSON per `schemas/plan-review.schema.json`.

4. **ARBITRATE — you own the decision, Codex is advisory.** For EVERY finding, do one of:
   - **ACCEPT** → the objection is real; note the fix (and apply it / fold it into the plan).
   - **OVERRIDE** → wrong or already handled; give a one-line rebuttal with the reasoning.

   Then: **escalate to the human** any critical/high finding you want to OVERRIDE; set the real verdict yourself (Codex's `reject` may become "proceed with fixes"); and present a short arbitration table (finding → ACCEPT/OVERRIDE → why).

5. **Hand back** the arbitrated decision: proceed to dispatch, revise the plan first, or escalate. Do NOT treat Codex's verdict as a hard gate — the deterministic `validate-manifest.py` is the only hard gate.

## Safety

- The review is **read-only** (`--sandbox read-only`) — it never modifies the repo.
- Codex never has final authority; arbitration is mandatory.
- Gate by stakes — a max-effort GPT review is not free.
