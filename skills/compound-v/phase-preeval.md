# Pre-Eval — Proportionate Fast-Path Triage (before Trigger 0)

**When this fires:** a change **request arrives**, before anything else — upstream of Trigger 0 recon, Trigger 1 pre-flights, brainstorming, and planning (spec §1). Pre-Eval scores the request on two axes and, only when a change is *provably* trivial + low-impact, lets the harness OFFER a proportionate fast-path instead of the full pipeline.

**Goal:** stop trivial fixes from being a Nolan odyssey — while never letting anything risky silently skip ceremony. Pre-Eval can only ever *save* work on the proven-trivial path; every ambiguity fails closed to the normal pipeline.

> Think of Pre-Eval as Stan Edgar reading the one-pager before the board convenes: a fast, deterministic read on whether this even needs the full room. He does not vote for you — he only decides whether to *offer* the short meeting, and the one decision he signs alone is the one the standing rules already settled in writing: §A4's DIRECT auto-route class. Everything outside it is an OFFER a human accepts.

**Reliability, stated plainly (updated v3.4):** Pre-Eval used to be **description-driven and UNENFORCEABLE** (AC-6) — exactly as weak as Trigger 0 — and it showed: the engine had produced **zero** artifacts in its entire history, because the only thing that was supposed to start it was a skill description firing at phase transitions that all happen *after* the size of the change is decided.

The scoring now has a **mechanical trigger**: `hooks/triage-prompt-nudge.sh` fires on the native `UserPromptSubmit` event and runs `compound-v-preeval.py triage` — the same subcommand [`/v:triage`](../../commands/v-triage.md) step T2 runs — writing a session-bound record before any work starts. That is a real change in kind, and it is bounded rather than absolute, so state it precisely:

- **It runs at most once per session**, and never on a slash command, a short question, a session that already has a covering record, or a session with an active run. The prompt at turn 20 of a long session is not scored by the hook; `/v:triage` is still how that gets a record.
- **Once means once ATTEMPTED, not once succeeded** *(spec WS2, amended 2026-09-02)*. The spec first said the hook's temp-dir marker would be retired and the record itself would be the marker. It was kept, and both gates stand: the record answers "is this session already sized", the marker — written *before* the engine runs — answers "has this session already been attempted". Without it, a crashed or timed-out engine leaves the session armed and the next prompt mints a **second** record for it, which is the per-turn pollution the once-rule exists to prevent, arriving by the failure path. The cost the amendment accepts, stated: a session whose first scoring failed is spent, and only `/v:triage` can recover it.
- **It never commits.** The engine never runs git and neither does a hook, so the record it writes is uncommitted. The Stop-time gate reads records off disk and does not care whether they are committed; it is `compound-v-validate-manifest.py --require-triage` and plain git durability that do — an uncommitted record fails `--require-triage` and is lost to a `git clean`, a fresh clone or a removed worktree. Committing it is `/v:triage` step T3's job, and it is not optional.
- **It is not enforcement.** Nothing here blocks. The mechanical closures are still `compound-v-validate-manifest.py --require-triage` (passed by `/v:dispatch` in every mode) and the triage rule in `hooks/epic-goal-stop.sh`. The hook makes sure a record EXISTS for those two to find.
- **The tier is a size decision, never permission.** SCOPED and FULL still require a human offer and acceptance (Iron-Invariant #4).

A missed or skipped Pre-Eval still degrades to the normal pipeline (Iron-Invariant #5, fail-closed). Do **not** claim Pre-Eval is enforced; claim that it now runs.

The engine is [`scripts/compound-v-preeval.py`](../../scripts/compound-v-preeval.py) — `triage_request` is the Phase-T entry point, and its docstring names its two callers; the record schema is [`schemas/pre-eval-record.schema.json`](../../schemas/pre-eval-record.schema.json); the config + digest + commit conventions live in [`docs/superpowers/architecture/pre-eval-config.md`](../../docs/superpowers/architecture/pre-eval-config.md); the truth-table authority is spec §2.

---

## 1. Iron Invariants (honesty constraints — not scope-negotiable)

1. **No raw LLM magnitude.** The engine assembles bands by deterministic logic. The only model touch — the Tier-3 `light` classify — emits a **pre-declared enum**, never a number.
2. **Localization before any `low`.** A `low` verdict is impossible until A1's bounded read-only `localize()` resolved real paths/tokens/fan-out. "make button X red" may be a global design token or an a11y contrast state — discovered *before* the decision.
3. **Tier 2 is escalation-only until calibrated.** Historical outcomes may only *lower* ceremony after enough *fast-path-taken* outcomes accrue; legacy full-pipeline successes are counterfactual and may only ESCALATE. At launch, Tier 2 is escalation-only by construction.
4. **The score OFFERS by default. It auto-routes only inside the DIRECT auto-route class, whose membership is decided by mechanically checkable predicates and never by model judgement. Every other tier still requires a human offer and acceptance.** The class's membership predicates are the v3.0 spec's §A4; they include a floor that has actually run and passed, and a full post-diff re-validation against the **pre-edit** taxonomy snapshot, and any fired override disqualifies. Outside that class the human-confirm step every production triage system keeps is still mandatory here.
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

Run the engine. It writes the Phase-P artifacts (§4) and returns a verdict in the engine's **three-valued** decision enum — `DECISION_FASTPATH` (the DIRECT tier), `DECISION_SCOPED`, `DECISION_FULL` (spec §A1; [`compound-v-preeval.py`](../../scripts/compound-v-preeval.py) and `pre-eval-record.schema.json` are the authority for the literals) — or `needs_t3` (§3). The engine is the single authority for spec §2; do not re-derive the truth-table in prose or by hand.

---

## 3. The truth-table (spec §2 — assembled deterministically by the engine)

Two axes, computed **separately**, each → a band `{low, medium, high, unknown}`. Within an axis: **conservative-max across tiers, never average down** — one strong `high` is never diluted.

### Layer A — hard overrides (ordered; first match → `FULL_PIPELINE`, zero further cost)

| # | Condition | Why |
|---|---|---|
| 1 | localization `failed` ∨ `ambiguous` | paths unknown → cannot judge |
| 2 | any resolved path on the **sensitive path-list** — *unless* the SCOPED+ carve-out below applies | auth/payments/PII/a11y/migrations/infra |
| 3 | `shared_token` ∨ `is_generated` ∨ `is_a11y_state` | "button" = global token / contrast state |
| 4 | semantic-vs-path disagreement (T1 `low` but T3 `user-facing-major`, or converse) | tier disagreement escalates |
| 5 | `churn.hot` on any resolved path | churn ESCALATES only; low/insufficient never lowers |
| 6 | any axis `unknown` | no signal → full pipeline |

Overrides **1/3/5 need no model call** and are checked first, so a fired override never triggers a Tier-3 Task (AC-3 — **zero model calls on any Layer-A override**). Overrides **4/6** depend on the computed axes (Tier-3 only when Tier-1 left difficulty unclassified). Override #2 is belt-and-suspenders: the engine trusts A1's `sensitive_path` flag **and** independently re-matches the sensitive path-list. Since 3.4.1 it is the one override that may ask a question before it fires — see SCOPED+ below.

### SCOPED+ and the T3 demotion (3.4.1): size reaches the tier

The 3.4 scorer could not say *small* about code. Any path under a broad glob — `scripts/**` is the one this repository trips over — came back `high/high` and therefore FULL, whether the change was a one-line comment or a rewrite. A size decision that can only ever say "big" is not a size decision, so 3.4.1 lets one cheap question move the band, in exactly two places and never further.

**The demotion.** When *every* Tier-1 row that produced the bands came from a **broad** glob (one containing `**` or ending `/*` — breadth is a property of the pattern, not a repo scan), *and* no resolved path is sensitive, *and* no content pattern raised impact, *and* `fan_out ≤ 2`, the engine asks for Tier-3 even though Tier-1 banded — returning `needs_t3` with `t3_reason: "demotion"` (the ordinary unbanded case says `"unbanded"`; the caller reads the reason for its log, and re-entry is identical). A reply of `plumbing` or `user-facing-minor` sets the bands to `(medium, medium)` and the matrix yields **SCOPED**; `user-facing-major` or `unknown` leaves them alone and the run stays FULL. Difficulty is raised to at least `medium` on purpose: **DIRECT for code stays unreachable**, and a demotion may never reach the tier that skips the human. Override #4 (semantic-vs-path disagreement) is *not* evaluated here — the whole point of this path is that Tier-1 said `high` from a glob that means "everything under here" and Tier-3 says `plumbing`. It keeps firing where Tier-1 came from a specific row. The record keeps the taxonomy's original bands beside the decision as `t3_demotion: {from: {difficulty, impact}, category, applied}`, so a demotion is always legible after the fact.

**SCOPED+.** A sensitive path is the case where being wrong is expensive, and it is also the case where a one-line fix is most likely to be blocked by a full pipeline nobody wants to run. So override #2 becomes conditional: sensitive ∧ localization `exact` ∧ `fan_out ≤ 2` ∧ Tier-3 says `plumbing` or `user-facing-minor` ⇒ `SCOPED_PIPELINE` with **`flavor: "scoped_plus"`** and bands `(medium, medium)`, with `override_fired: null` and `t3_demotion` carrying `"sensitive": true`. On that path with no category yet, the engine returns `needs_t3` with `t3_reason: "sensitive"`. **Every other sensitive case fires override #2 and goes FULL exactly as before, and no sensitive path is ever DIRECT.** `.pem`/`.key`/`.env` files and `.github/**` are on a hard never-demote list in the engine: secrets and CI are not "small edits", whatever a classifier says about them.

SCOPED+ is a *smaller pipeline, not a cheaper one*. It buys back both reviews the plain SCOPED band skips: [`/v:orchestrate`](../../commands/v-orchestrate.md) copies `flavor` into the manifest's `triage` block, which obliges the run to declare a `type: review` job with `tier: deep` and `backend: claude` (`compound-v-validate-manifest.py --require-triage` refuses the manifest without one), and [`/v:dispatch`](../../commands/v-dispatch.md) step 8 additionally runs a **mandatory** cross-model second opinion whose receipt is verified rather than asserted. The human offer and acceptance are unchanged — SCOPED+ is a SCOPED-sized change, and the tier is still a size decision, never permission.

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

The **parent harness** then runs **ONE `light`-tier Task** (Sonnet, **never Haiku**) with `t3_prompt` — built + parsed by `compound-v-classify-request.py` (`build_prompt` / `parse_category`) — turns the reply into an enum, and **re-invokes** the engine with `--t3-category <enum>`. Re-entry reuses the same `pre_eval_id` (discovered via the intent-record fingerprint, §4) and continues from the first missing artifact. The engine itself **never calls a model** on any path. Any error / timeout / unparse / non-enum reply → `unknown` → `FULL_PIPELINE` (fail-closed).

Since 3.4.1 the `UserPromptSubmit` hook can finish Tier-3 itself, without a Task and without handing the turn back: `compound-v-classify-request.py --classify-headless` answers the same prompt from a bounded nested `claude -p` (Sonnet — **never Haiku**), falling back to the read-only codex route and then to `unknown`. `/v:triage` documents that as the default route and the Task route as the fallback. Nothing about this section's contract changes — same prompt, same enum, same fail-closed direction — only who runs it.

---

## 4. Phase P — lifecycle & commit ordering (parent-owned; NO run_id yet)

All artifacts live under `docs/superpowers/pre-eval/` — **not** `execution/<run-id>/` (that dir does not exist at pre-brainstorm time, AC-2). The engine WRITES; the **orchestrator/dispatcher COMMITS** (v2.6.4 discipline — an uncommitted artifact is lost to `git clean`, a fresh clone or a removed worktree, and never indexes into V-memory). The engine **never runs git**, which is why `base_commit` is an *input* to `triage_request` rather than something it reads, and why the UserPromptSubmit hook leaves its record uncommitted for `/v:triage` step T3.

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
