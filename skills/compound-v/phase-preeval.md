# Pre-Eval — Proportionate Fast-Path Triage (before Trigger 0)

**When this fires:** a change **request arrives**, before anything else — upstream of Trigger 0 recon, Trigger 1 pre-flights, brainstorming, and planning (spec §1). Pre-Eval scores the request on two axes and, only when a change is *provably* trivial + low-impact, lets the harness OFFER a proportionate fast-path instead of the full pipeline.

**Goal:** stop trivial fixes from being a Nolan odyssey — while never letting anything risky silently skip ceremony. Pre-Eval can only ever *save* work on the proven-trivial path; every ambiguity fails closed to the normal pipeline.

> Think of Pre-Eval as Stan Edgar reading the one-pager before the board convenes: a fast, deterministic read on whether this even needs the full room. He does not vote for you — he only decides whether to *offer* the short meeting. The request-level score OFFERS; it never routes.

**Reliability, stated plainly:** Pre-Eval is **description-driven and UNENFORCEABLE** (AC-6) — exactly as weak as Trigger 0, with the same reminder-only `PreToolUse(Skill)` hook as its only backstop. This is safe **only** because a missed or skipped Pre-Eval degrades to the normal pipeline (Iron-Invariant #5, fail-closed). Do **not** claim Pre-Eval is enforced.

The engine is [`scripts/compound-v-preeval.py`](../../scripts/compound-v-preeval.py); the record schema is [`schemas/pre-eval-record.schema.json`](../../schemas/pre-eval-record.schema.json); the config + digest + commit conventions live in [`docs/superpowers/architecture/pre-eval-config.md`](../../docs/superpowers/architecture/pre-eval-config.md); the truth-table authority is spec §2.

---

## 1. Iron Invariants (honesty constraints — not scope-negotiable)

1. **No raw LLM magnitude.** The engine assembles bands by deterministic logic. The only model touch — the Tier-3 `light` classify — emits a **pre-declared enum**, never a number.
2. **Localization before any `low`.** A `low` verdict is impossible until A1's bounded read-only `localize()` resolved real paths/tokens/fan-out. "make button X red" may be a global design token or an a11y contrast state — discovered *before* the decision.
3. **Tier 2 is escalation-only until calibrated.** Historical outcomes may only *lower* ceremony after enough *fast-path-taken* outcomes accrue; legacy full-pipeline successes are counterfactual and may only ESCALATE. At launch, Tier 2 is escalation-only by construction.
4. **The score only OFFERS, never auto-routes.** Every production triage system keeps a human-confirm step; so does this one.
5. **Fail-closed everywhere.** Any ambiguity, missing data, tier disagreement, token-budget overrun, `unknown` axis, or **absent/malformed taxonomy** → `FULL_PIPELINE`.
6. **The scope gate is never skippable; the prediction is never trusted once a diff exists.** Post-hoc F2 re-classifies the real diff; a violation escalates.

---

## 2. Gate order — deterministic, always in this order

Evaluate in order; the first gate that resolves ends the check. The whole deterministic path (localization + Tier-1 + churn + Tier-2 + Layer-A) must resolve inside a **~1s flow ceiling** — it is YAML/glob/dict/git-cache lookups, no model call (spec §3).

### Gate 1 — `pre_eval.enabled` / `pre_eval.fast_path` (config, fail-closed)

Read via `compound-v-project-config.load_project_config(repo)` + `resolve_pre_eval(cfg)` (never parse the JSON by hand). Structural malformation → **warn once, use defaults, never treat invalid as an auto-route**. `pre_eval.fast_path: off` is a **hard kill-switch** — no offer, ever (still run the pipeline normally). `ask` (default) OFFERS when eligible. Per-key bad values coerce to the declared default with a one-time warning.

### Gate 2 — remember-my-choice read (AC-11)

Before offering, read `pre_eval.remember` (`{ "<taxonomy-category>": "fastpath" }`). A remembered category **suppresses the OFFER for that category only** — it is an explicit, revocable, one-time human opt-in, NOT a silent auto-route. **Every fail-closed override still fires** on a remembered request: sensitive path, shared-token, a11y, churn-hot, tier-disagreement, and the post-hoc diff escalation. Revoke via `/v:init` or by editing the config. Default: not remembered (ask every time).

### Gate 3 — score the request (the truth-table engine)

Run the engine. It writes the Phase-P artifacts (§4) and returns a verdict `∈ {FASTPATH_ELIGIBLE, FULL_PIPELINE}` — or `needs_t3` (§3). The engine is the single authority for spec §2; do not re-derive the truth-table in prose or by hand.

---

## 3. The truth-table (spec §2 — assembled deterministically by the engine)

Two axes, computed **separately**, each → a band `{low, medium, high, unknown}`. Within an axis: **conservative-max across tiers, never average down** — one strong `high` is never diluted.

### Layer A — hard overrides (ordered; first match → `FULL_PIPELINE`, zero further cost)

| # | Condition | Why |
|---|---|---|
| 1 | localization `failed` ∨ `ambiguous` | paths unknown → cannot judge |
| 2 | any resolved path on the **sensitive path-list** | auth/payments/PII/a11y/migrations/infra |
| 3 | `shared_token` ∨ `is_generated` ∨ `is_a11y_state` | "button" = global token / contrast state |
| 4 | semantic-vs-path disagreement (T1 `low` but T3 `user-facing-major`, or converse) | tier disagreement escalates |
| 5 | `churn.hot` on any resolved path | churn ESCALATES only; low/insufficient never lowers |
| 6 | any axis `unknown` | no signal → full pipeline |

Overrides **1/2/3/5 need no model call** and are checked first, so a fired override never triggers a Tier-3 Task (AC-3 — **zero model calls on any Layer-A override**). Overrides **4/6** depend on the computed axes (Tier-3 only when Tier-1 left difficulty unclassified). Override #2 is belt-and-suspenders: the engine trusts A1's `sensitive_path` flag **and** independently re-matches the sensitive path-list.

### Layer B — positive fast-path gate (only if no override fired)

`FASTPATH_ELIGIBLE` ⟺ `difficulty == low` ∧ `impact == low` ∧ `fan_out ≤ pre_eval.fan_out_threshold` (default 1) ∧ **exactly one literal normalized path** (no glob metachar, not shared/generated/config/migration).

### Tier 3 total table + the missing-data rule

Tier-3 is the **only** model touch, reached **only** when Tier-1 left difficulty unclassified ∧ Tier-2 is insufficient. Its enum maps to **both** axes deterministically: `plumbing → low/low`, `user-facing-minor → medium/medium`, `user-facing-major → high/high`, `unknown → unknown/unknown`. Tier-3 impact may only **raise**, never lower below Tier-1.

**Absent / malformed / unreadable taxonomy or its pinned snapshot → unconditional `FULL_PIPELINE`** (spec §2 round-3 fix): without the sensitive-path + content-pattern protections there is no way to *prove* a change is safe, so **Tier-3 alone never manufactures eligibility**. Same for a taxonomy with no safety coverage (empty sensitive path-list). Churn cache absent → churn signal absent (never escalates, never lowers). Triage-outcomes empty / `n < min_sample_count` → Tier-2 insufficient (escalation-only). Token-budget overrun at the Tier-3 boundary → abort → `FULL_PIPELINE`.

### The PARENT runs Tier-3 — never the engine (`needs_t3` re-entry)

The engine is **T3-agnostic**: it accepts a pre-resolved `--t3-category` enum and, when Tier-3 is required but the category is unset, returns:

```json
{ "needs_t3": true, "pre_eval_id": "…", "t3_prompt": "…" }
```

The **parent harness** then runs **ONE `light`-tier Task** (Sonnet, **never Haiku**) with `t3_prompt` — built + parsed by `compound-v-classify-request.py` (`build_prompt` / `parse_category`) — turns the reply into an enum, and **re-invokes** the engine with `--t3-category <enum>`. Re-entry reuses the same `pre_eval_id` (discovered via the intent-record fingerprint, §4) and continues from the first missing artifact. On the Claude path the engine **never calls a model**; the optional headless-codex route (A2) is for non-Claude harnesses only. Any error / timeout / unparse / non-enum reply → `unknown` → `FULL_PIPELINE` (fail-closed).

---

## 4. Phase P — lifecycle & commit ordering (parent-owned; NO run_id yet)

All artifacts live under `docs/superpowers/pre-eval/` — **not** `execution/<run-id>/` (that dir does not exist at pre-brainstorm time, AC-2). The engine WRITES; the **orchestrator/dispatcher COMMITS** (v2.6.4 discipline — an uncommitted artifact vanishes on `git worktree remove` and never indexes into V-memory). The engine **never runs git**.

1. **Intent record** `<pre_eval_id>.intent.json` (write-once, request-fingerprint → `pre_eval_id`) — written FIRST, ahead of localization, so a fresh-process resume with only the request text finds partial state (CR5-10).
2. **Localization artifact** `<pre_eval_id>.localization.json` (A1's write-once writer) — the resolved paths/fan-out/flags + its own content-digest bound across manifest+record+artifact (AC-13).
3. **Taxonomy snapshot** `<pre_eval_id>.taxonomy-snapshot.yaml` — the taxonomy's **RAW bytes**, content-addressed (`taxonomy_digest` = sha256 of the bytes, not a re-serialization). Immutable; a fast-path later copies it into the run preserving `taxonomy_ref`/`taxonomy_digest`.
4. **Record** `<pre_eval_id>.json` (write-once, O_EXCL) — `status: PRE_EVAL_DONE` (a RECORD field, **not** a `state.json` phase, AC-7/CR2-8), the two axes + derived 1-10 DISPLAY, `tiers_signalled`, `override_fired`, `decision`, `min_sample_status`, `taxonomy_ref`/`taxonomy_digest` (null in the absent-taxonomy case), and a self-integrity `digest`.
5. **`predicted` triage event** — appended to `docs/superpowers/memory/triage-outcomes.jsonl` keyed by `pre_eval_id` (F1's `append_predicted`, append-only). Even the absent-taxonomy `FULL_PIPELINE` still writes the record and appends `predicted` (Iron-Invariant #5).

On `needs_t3` the engine returns **without** writing the record or appending `predicted` — steps 1–3 are already durable; re-entry (§3) resumes at step 4.

**The `bind` event.** When (and only when) this request later becomes a run — fast-path OR full-pipeline — the orchestrator appends the `{event:"bind", pre_eval_id, run_id}` triage event as the run dir is created (F1's `bind_run`), joining the write-once `pre_eval_id` to the new `run_id`. Pre-Eval itself never mints a run-id.

---

## 5. The OFFER — folded into ONE interaction, never a standalone screen (AC-9)

A `FASTPATH_ELIGIBLE` verdict under `fast_path: ask` (and not remembered) is **OFFERED inside the single recon/clarify interaction** — never as its own prompt. Per-request prompting trains rubber-stamping, which becomes a de-facto auto-route and violates Iron-Invariant #4.

- Fold the fast-path offer into the **same** blocking interaction as the Trigger-0 recon ask when both fire (Codex: combine the questions). One screen, not two.
- The deterministic tiers resolve inside the **~1s flow ceiling**. If a Tier-3 `light` Task is on the path (rare), show a **"checking…"** affordance — a Tier-3 call can exceed ~1s and must not stall the interaction silently.
- State the choice qualitatively (proportionate fast-path vs full pipeline); **never** print a fabricated cost/token number (anti-ruflo). The derived 1-10 is a post-decision band-midpoint DISPLAY label, shown as evidence, never as the gate.
- Cancel / timeout / empty reply / an unrelated next message = **decline** → run the normal pipeline. On decline, the request still initializes at the normal first phase (not `FASTPATH_DISPATCHED`).

On accept, the fast-path is materialized into committed run artifacts by the dedicated materializer (Task M1) and dispatched at `FASTPATH_DISPATCHED`; the scope gate, the test floor, and a proportionate (1 combined SPEC+QUALITY pass, vacuous INTEGRATION) review are **never** skipped (spec §4).

---

## 6. Pre-Eval ≠ Recon — separate records, separate boundaries

Pre-Eval is a **routing/triage** artifact; recon ([phase-0-recon.md](phase-0-recon.md)) is **evidence-only** and never a routing input. They are separate records with separate streams (`pre-eval/<id>.json` + `triage-outcomes.jsonl` vs `recon/*.md` + `recon-outcomes.jsonl`). Recon's contract is unmodified. Pre-Eval is triage-only telemetry — evidence for the Tier-2 gate and `/v:status` precision, **never** a routing input beyond the triage boundary.
