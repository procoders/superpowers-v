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

**Resolving the plugin root.** The `scripts/` and `schemas/` invoked below ship with the
plugin, not with the caller's repository. Resolve the plugin root once per session before
calling any of them:

```bash
CV="${CLAUDE_PLUGIN_ROOT:-$(ls -d "$HOME"/.claude/plugins/cache/*/superpowers-v/*/ 2>/dev/null | sort -V | tail -1)}"
CV="${CV%/}"
[ -f "$CV/scripts/compound-v-emit-workflow.py" ] || CV="$PWD"
[ -f "$CV/scripts/compound-v-emit-workflow.py" ] || { echo "superpowers-v plugin root not found: reinstall the plugin" >&2; CV=""; }
```

`CLAUDE_PLUGIN_ROOT` is set for hooks but is not set in this Bash environment, so treat it as a
hint, never the whole answer — the cache line covers an installed plugin, `$PWD` is used only inside a checkout of this plugin, and an empty `$CV` is a stop — do not run the steps below with it.

---

## When to run it — the tier decides IF, the stakes decide HOW DEEP

**First gate (3.1.0, mechanical): the triage tier.** A cross-model second opinion follows
the **same entry criterion as brainstorming**. A change too small to brainstorm is too
small to hand to a second model family — there is no plan for it to read. Ask the engine
rather than remembering the rule:

```bash
python3 "$CV/scripts/compound-v-preeval.py" --cross-model-review "$TIER" --flavor "$FLAVOR"   # FLAVOR = manifest triage.flavor, empty when none
```

| Triage tier | Second opinion | Why |
|---|---|---|
| `DIRECT` | **no** | No brainstorm, no plan, no manifest — nothing exists to review. |
| `SCOPED` | **no** by default | A bounded, localized change; the Opus `partition-reviewer` and the deterministic validator already cover it. Ask explicitly if the slice turns out to be coupled. |
| `SCOPED+` (`triage.flavor: scoped_plus`) | **yes, mandatory** | A small edit on a *sensitive* path — auth, payments, PII, migrations, or this repo's own enforcement chain. Small enough to skip the full pipeline, expensive enough that being wrong is not recoverable by "we'll catch it in review". This is the one row where the second opinion is not a judgment call. |
| `FULL` | **yes** | The pipeline ran brainstorm and planning. That is the threshold a second family is worth paying for. |

An unrecognised tier falls to **yes**: not knowing how big a change is, is itself a reason
to have another family read it, and this gate can only ever spend tokens — it can never
let a worse plan through.

**Second gate (unchanged): the stakes.** Inside `FULL`, the list below chooses the *depth*
of the review, not whether to ask. A max-effort GPT review costs real tokens and ~minutes.
Reach for the deepest form when ANY of these hold:

- the plan touches **security / auth / payments / PII / migrations / shared data model**;
- the partition is **large or coupled** (≈4+ parallel tasks, or a serial shared-foundation task others depend on);
- the change is **architectural** (new subsystem, cross-cutting refactor);
- the **human explicitly asks** for a second opinion.

**Skip** for small, mechanical, or single-slice plans — the Opus `partition-reviewer` plus
the deterministic `validate-manifest.py` already cover those. Two rules of thumb that agree
with the table above: run it when the plan's riskiest job resolves to model tier `deep` or
`frontier`, and run it when the ticket carries **business logic with many code-level
dependencies** — the same coupling signal that puts a job on Opus rather than Sonnet.
Volume alone is not the criterion; a thousand mechanical lines in one lane still does not
need a second family, and eighty coupled ones do.

This sits in the three-layer plan check, each layer catching a different class of error:

| Layer | Who | Catches |
|---|---|---|
| Deterministic | `scripts/compound-v-validate-manifest.py` | hard invariants (disjoint write-scope, codex⇒worktree, reviewers⇒opus/deep) — no opinions |
| Primary judgment | `superpowers-v:partition-reviewer` (Opus) | decomposition sense, coverage |
| **Independent second opinion** | **Codex, tier `frontier`, effort `xhigh`** | the planner-family's own blind spots |

---

## How to run it

After `partition-reviewer` returns **PASS** and `validate-manifest.py` is clean, dispatch
the read-only cross-model review:

```bash
"$CV/scripts/compound-v-codex-review.sh" \
  --plan-file docs/superpowers/plans/<plan>.md \
  --repo "$PWD" \
  --effort xhigh \
  [--context-file docs/superpowers/archaeology/<topic>.md] ...
```

- The model is resolved for **codex / tier `frontier`** (e.g. `gpt-6-astra`) — see [routing-policy.md](routing-policy.md). Review runs on the frontier tier, one rung above implementation's `deep`/`standard` (`gpt-6.1-sol`): the strongest reasoning pays off where it's spent catching the planner's own blind spots. `--effort xhigh` is "Codex on their strongest reasoning" (codex-only top rung; the script accepts low|medium|high|xhigh and defaults to xhigh).
- Codex runs **read-only** (`--sandbox read-only`): it may READ the repo to ground each objection against the real files, but writes nothing.
- It returns structured findings per [`schemas/plan-review.schema.json`](../../schemas/plan-review.schema.json) — `verdict` (endorse | concerns | reject), a list of `findings` (each: `severity`, `category`, `claim`, `evidence`, `recommendation`), and `blind_spots_checked`.
- The reviewer is prompted to **refute** the plan, default to skepticism, and prefer concrete evidence; an empty `findings` list is honest and valid.

Or, for manual control: `/v:review-plan <plan-path>`.

---

## The ladder

"Run the cross-model review" assumes Codex is installed. It is not always. The ladder is
what "second opinion" resolves to when it is not — three rungs, tried in order, and the
receipt says honestly which one actually ran:

1. **Codex CLI present → as today.** `scripts/compound-v-codex-review.sh` drives a
   read-only `codex exec` worker — a genuinely different model family reading the same
   bytes. This is the row above; nothing here changes it.
2. **No Codex, an advisor is configured → an advisor-assisted second look.** Dispatch
   **one read-only Opus subagent through the Agent tool** — not a script, a Claude
   subagent, because there is no headless Codex to shell out to. Give it the same
   adversarial prompt the driver embeds (the "INDEPENDENT cross-model reviewer" prompt in
   `compound-v-codex-review.sh`, with the same plan/diff and context files attached), plus
   one added instruction: **consult the advisor tool before you write your verdict.** The
   subagent still returns findings against `schemas/plan-review.schema.json` — same
   `verdict`/`findings`/`blind_spots_checked` shape, so every downstream consumer (the
   receipt wrapper, the arbitration step) needs no branch for it.

   Wrap the result exactly as the SCOPED+ receipt below is wrapped, with two differences:
   `reviewer_backend: "claude-advisor"` (not `"codex"`) and `cross_model: false`. That
   second field is the point of this rung: **the honesty is a field a machine can read,
   not only a sentence a human may skip.** A validator or a future job that greps receipts
   for "did a cross-model review run" gets a correct answer without parsing prose.
   `compound-v-validate-manifest.py` accepts a `claude-advisor` receipt and prints the
   advisory `SECOND_OPINION_SAME_FAMILY` — a WARN, not a refusal.
3. **Neither Codex nor an advisor configured → skip, with the notice.** State plainly that
   no second opinion ran and why (no Codex CLI found, no `advisorModel` set) — the same
   skip this document already described before this ladder existed.

**The disclosure line — verbatim, in every rendering of rung 2** (the receipt's own prose
summary, `/v:review-plan`'s output, `/v:dispatch` step 9's report, any dashboard that shows
the verdict):

> Second look by the same model family (Claude + advisor) — no decorrelation; not a
> cross-model review.

Say this even when the advisor resolves to a different family under the hood (e.g. Fable)
— the subagent doing the reading, writing the findings and reaching the verdict is still
Claude reviewing Claude's own work; the advisor is consulted mid-thought, not handed the
pen. Rung 2 is an honest downgrade, never presented as equivalent to rung 1, and the prose
everywhere it appears tells the project: **if you can install Codex, install it** — a
Claude review of Claude's code shares Claude's blind spots no matter how the receipt is
worded.

**The SCOPED+ rule.** [`/v:dispatch`](../../commands/v-dispatch.md) step 9 makes the
second opinion **mandatory** for a `triage.flavor: scoped_plus` run. The ladder is how that
mandate survives a machine with no Codex CLI: **rung 2 satisfies the SCOPED+ requirement**
— the WARN is the price of satisfying it this way, not a reason to treat it as unsatisfied
— and **rung 3 still refuses.** A SCOPED+ run with neither Codex nor an advisor configured
does not get a silent pass; it is exactly as unreviewed as it looks, and the mandatory gate
says so.

---

### The SCOPED+ variant — same driver, different input, and a receipt

A SCOPED+ run has no plan document to hand over; it has a diff. [`/v:dispatch`](../../commands/v-dispatch.md)
step 8 seals the reviewed bytes to `receipts/cross-model.patch`, passes *that* as `--plan-file`
with the spec as `--context-file`, and wraps the driver's findings in a receipt
([`schemas/cross-model-receipt.schema.json`](../../schemas/cross-model-receipt.schema.json)) that
adds `run_id`, `pre_eval_id` and a `diff_digest` over the sealed patch, self-sealed with the shared
digest primitive. `compound-v-validate-manifest.py --require-cross-model-receipt` then verifies it
before the merge.

The receipt exists because "mandatory" and "we ran it, trust us" are different claims. **The findings
stay advisory — arbitration below is unchanged, and a `concerns` verdict is not a merge blocker.**
What the receipt makes unfalsifiable is only that a reviewer of a different family actually read
*these bytes* on *this run*.

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
