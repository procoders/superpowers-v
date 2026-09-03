# v3.4.8 Workflow Retry — Code Archaeology

Spec: `docs/superpowers/specs/2026-09-03-v3.4.8-workflow-retry-design.md`. Plan (already drafted
— see note under §0): `docs/superpowers/plans/2026-09-03-v3.4.8-workflow-retry.md`.

**Note on sequencing.** A plan already exists for this feature (`docs/superpowers/plans/2026-09-03-v3.4.8-workflow-retry.md`,
Partition Map: Task A `scripts/compound-v-emit-workflow.py`, Task B `scripts/compound-v-validate-manifest.py`,
Task C docs). Per this agent's charter, this audit is built from the CODE, not the plan — the plan is
treated as one more claim to verify, not as ground truth. Several of its claims do not survive contact
with the code (§2, §3, §7).

## 0. V-memory recall

`compound-v-memory.py search` run three times (`"workflow retry design"`, `"withRetry agent() transient
error classify backoff"`, `"reviewer escalation deep frontier Fable review job tier"`). No prior
archaeology exists for this exact subsystem (retry/backoff/reviewer-escalation inside Engine C). Useful
adjacent hits, cited below where load-bearing: `docs/superpowers/archaeology/2026-09-03-v3-4-6-triage-test-scoping-fixes.md`
(prior `failure_class` field semantics), `docs/superpowers/architecture/2026-09-02-viability-audit.md`
(routing tiers verdict), and this project's own MEMORY.md v2.6.4 entry (execution audit-trail files
silently deleted by `git worktree remove` when not committed — directly relevant to §5).

## 1. Matrix

Dimensions: **stage function** (4, all in `compound-v-emit-workflow.py:emit_script`) × **job kind**
(ordinary vs. reviewer, by `_is_reviewer_job`) × **`agent()` failure signal** (throws vs. resolves `null`)
× **manifest kind** (ordinary Engine-C wave vs. `fast_path`) × **routing stance** (balanced/conservative/
cost-aware/claude-only).

| Stage fn (line) | What its `agent()` call does | Reviewer jobs go through it? | New `withRetry` target per plan? | Existing outer catch |
|---|---|---|---|---|
| `implementStage` (:2000) | Runs the job's own work (a review job's "work" is the review) | **Yes — same function, no separate review stage** | Yes | `catch(e)` → `{job, implement: null}`, logs `"threw"` (:2044-2050) |
| `gateStage` (:2074) | Verifies scope/diff for the job just implemented | No (gates every job type uniformly) | Not named in spec/plan (spec doesn't mention gate) | Banner: "THIS STAGE MUST NEVER THROW" (:2054) |
| `recordStage` (:2201) | Transport-only: spawns an agent to run `record` CLI via Bash | No | Yes (plan says "every `agent(` inside a stage") | `catch(e)` → `{recorded: false, reason: '...caught: '+e}` (:2242-2248) |
| `finalizeWave` (:2267) | Transport-only: spawns an agent to run `finalize-wave` CLI via Bash | No | Yes | `catch` not shown above :2299 but same pattern (`{integrated: false, ...}`) |

| Manifest kind | Reviewer escalation to `frontier`/Fable allowed? | Evidence |
|---|---|---|
| Ordinary Engine-C wave manifest | Yes, at **manifest-declaration time** (`tier: frontier` accepted since finding 119) | `compound-v-validate-manifest.py:5096-5119` selftest, `:2660-2671` job-declaration check |
| `fast_path` manifest | **No — schema-forbidden** | `schemas/fastpath-review-receipt.schema.json:52-55` `reviewer_tier` is `"const": "deep"`; `_review_resolution` (`compound-v-validate-manifest.py:1239-1291`) requires literal Opus resolution, no frontier path |

**Not handled by the plan:** the matrix cell (fast_path manifest × reviewer hits transient failure) is the
exact incident class this feature exists to fix (three consecutive 529s on an Opus reviewer), and it can
recur on a fast_path run. The plan's Partition Map touches only `compound-v-emit-workflow.py` and
`compound-v-validate-manifest.py`'s new `retry` block — it never touches `compound-v-fastpath-run.py`,
which is the script that actually drives fast_path's review (`review-spec`/`accept-review`, an in-harness
Task, per `agents/parallel-dispatcher.md:334-341` — a wholly different code path from the emitted JS
stage functions Task A edits). A fast_path reviewer gets **no relief at all** from this feature, and
the schema (`reviewer_tier: const: "deep"`) would need an explicit change before it ever could. If this
is an intentional scope cut, the plan must say so; right now it's silent.

## 2. Shared State

### `failure_class` (top-level job-result field, `scripts/compound-v-emit-workflow.py:3668`)

- **Set in `_job_result_from` (:3560-3670):** `"failure_class": None if status in ("success", "blocked") else "other"` — a **hardcoded literal**, not a lookup. This is the exact line the spec's decision #2 and the plan's Task A bullet 5 target.
- **NOT set from any classifier today** for the in-harness Claude `agent()` path. The proper classifier (`compound-v-classify-failure.py`) exists and is wired for the codex/antigravity/cursor **worker-script** backends (confirmed by `docs/superpowers/archaeology/2026-09-03-v3-4-6-triage-test-scoping-fixes.md`'s own finding on this exact field), never for Engine C's in-harness Claude stages.
- **Gap the plan must close precisely:** the plan says Record should write the class "when the stage result carries `retries` and a terminal transient error" — but as built today `_job_result_from` has no `retries` input parameter at all; Task A must add one and thread it from `recordStage`'s CLI invocation into `cmd_record` → `_job_result_from`.

### `reviewer_model` / reviewer-must-be-Opus invariant — THREE separate, non-identical gates

1. **Manifest-declaration-time** (`_is_reviewer(job)` region, `compound-v-validate-manifest.py:2660-2671`): `is_opus = str(job.get("model","")).lower() in ("opus","fable")`. Patched for finding 119; **accepts `tier: frontier`/`model: fable`.** Selftest: `:5096-5119`.
2. **`_is_claude_opus(model)`** (`compound-v-validate-manifest.py:1077-1080`): `"opus" in model.lower()`. `"fable"` does **not** contain `"opus"` → **returns False for Fable.** Used at `:1286` (`_review_resolution`, fast_path.review declaration resolution) and `:1489` (`_sealed_receipt_problems`, fast_path review receipt CR5-5). **Not patched for finding 119** — and per `schemas/fastpath-review-receipt.schema.json:57-59`, deliberately not meant to be (fast_path's reviewer must resolve to literal Opus, no exception).
3. **`resolve_job_model` / `_is_reviewer_job` exemption** (`compound-v-emit-workflow.py:1541-1566`): an *existing, deliberate* guard that **exempts reviewer jobs from cross-run re-attempt escalation**, with the stated reason (verbatim, :1552-1555): *"Reviewers are exempt: a sealed review receipt must carry a Claude Opus `reviewer_model`, so escalating one would invalidate the very receipt it exists to produce."*

**Gap:** gate 3's stated rationale is written as a universal invariant, but gates 1-2 show the invariant is **not** universal — it's true for fast_path (gate 2, schema-enforced) and **false** for an ordinary Engine-C wave manifest (gate 1 explicitly accepts Fable since finding 119). `skills/compound-v/execution-manifest.md:78-80` states the invariant as universal too ("Reviewers are not satisfied by `frontier`... For the same reason a reviewer is never escalated on a re-attempt") — **this is stale documentation**: the code (gate 1, finding 119) already contradicts the first half of that sentence. Task C edits this exact file/section to add the new retry-lift language; it will be adding a "reviewers DO get lifted to frontier" paragraph immediately next to an unfixed "reviewers are never escalated" paragraph unless the stale text is corrected in the same edit.

### `CLAUDE_ESCALATION` / `escalate_claude_model` (`compound-v-emit-workflow.py:1072`, `:1111-1124`)

- `CLAUDE_ESCALATION = ("sonnet", "opus", "fable")`. `escalate_claude_model(model)` steps one rung up this **fixed ladder by string value**, and explicitly refuses to touch a model string not on the ladder ("escalating a value we did not choose would be a fabricated routing decision", :1114-1116) — i.e., an explicit manifest `model:` pin outside the ladder is left alone.
- The plan's Task A instructs "spawn once more with `opts.model = 'fable'`" — a **hardcoded literal**, not a call to this existing function. Consequence: if a reviewer job carries an explicit `model:` pin (execution-manifest.md:48, a supported, backward-compatible field), the plan's hardcoded literal will unconditionally overwrite it with `'fable'` on retry-exhaustion, silently discarding an intentional pin that `escalate_claude_model` would have refused to touch. `resolve_job_model`'s own stance tables (`compound-v-resolve-model.py:79-99`) confirm `"deep"` resolves to `"opus"` under **every** stance (balanced/conservative/cost-aware), so `escalate_claude_model(resolved)` already gives the correct `'fable'` answer in the common case — reuse it, don't re-literal it.

## 3. Sibling Code — `agents/parallel-dispatcher.md` Step 2c (read in full: lines 241-292)

This is the analogous existing path the spec explicitly says it's "wiring in": *"Compound V already owns
the right policy... but it is wired into the residual subagent dispatcher and the external workers only."*

- **Entry condition:** a `job_result.status` that is not `success` and not `blocked`.
- **Inputs:** `job_result.failure_class` (or recomputed via `compound-v-classify-failure.py --backend ...
  --exit-code ... --stderr-file ...`), `job_result.retry_after_seconds`, `state.json`'s **per-(job, class)**
  `attempts` counter, `total_retries`, `max_total_retries`, `circuit_open[<backend>]`, the job's resolved
  `--current-tier`.
- **State is PERSISTED, crash-safe, resume-aware:** `cooldowns[<backend>]` and `attempts[<job>][<class>]`
  live in `state.json`, written after every transition, reconciled by `/v:resume` (git-wins).
- **Per-class ceilings differ:** `PER_CLASS_MAX` (`compound-v-failure-policy.py:48-54`) —
  `rate_limited: 3, overloaded: 2, network: 2, timeout: 1, other: 1`. The new manifest `retry.max_attempts`
  (plan: one flat int, default 3, applied uniformly to every transient class) is a **coarser, different
  policy shape**, not a restatement of the existing one — an "overloaded" class (the exact class of the
  incident that motivated this spec) gets one *more* attempt under the new default (3) than the existing,
  already-tuned policy allows it (2).
- **Backoff formula:** `_backoff(attempts, retry_after, jitter)` (`compound-v-failure-policy.py:65-71`) —
  `base = 2 * 2**attempts`, jitter is **additive** `random.uniform(0, 2)` (flat 0-2s regardless of
  magnitude), capped at 60s. The plan's JS formula, `min(60000, 2000 * 2**(attempt-1)) ± 25%`, matches the
  *base* growth (off-by-one index convention aside — plan's `attempt` is 1-indexed, policy's `attempts` is
  0-indexed prior-count, so they agree numerically) but its **jitter is multiplicative** (±25% of a
  possibly-large wait, growing without bound as attempts increase) — not the same shape as the sibling's
  flat additive jitter. A "mirror" that isn't one.
- **Known-latent property, not a bug:** re-dispatch after `retry` action goes through "the **full
  worker-script lifecycle**" — worktree removed and recreated fresh at HEAD, never resumed by poking a
  live CLI (`:274`). Nothing analogous exists for Engine C's in-workflow retry (there is no worktree
  recreate step in `withRetry` as specified — the same `agent()` call is simply re-invoked in place). This
  is fine for a `light`-tier transport call, but worth stating explicitly for an `implementStage` retry:
  the retried `agent()` call reuses whatever worktree state the first, failed attempt already touched
  (isolation is per-job, set once in `entry["agent_isolation"]` at plan-build time, :1513-1517).
- **No reviewer-escalation-on-transient-failure analog exists in Step 2c at all.** `decide()`
  (`compound-v-failure-policy.py:74-128`) has no branch that escalates a job's *tier* on a `RETRYABLE`
  class exhausting — only `context_length` sets `escalate_tier`. Finding 119's "lift the reviewer" is a
  **brand-new decision**, not a port of existing policy, and the plan's Partition Map doesn't touch
  `agents/parallel-dispatcher.md` — so after this ships, the residual (non-Engine-C) dispatcher still has
  no reviewer-lift behavior for the identical incident. State whether that asymmetry is intentional.

## 4. External APIs

No third-party API is touched. The relevant external contract is the **native Claude Code Workflow
script runtime** itself — not Context7-indexed (it's the harness's own tool, not a library). Verified via
the `workflow-authoring` skill (loaded this session) and cross-confirmed against this repo's own probes:

- **No `sleep`/`setTimeout`/delay primitive exists in a Workflow script at all.** The documented hooks are
  `agent()`, `pipeline()`, `parallel()`, `log()`, `phase()`, `args`, `budget`, `workflow()`. "No filesystem
  or Node.js API access" — `setTimeout` is a host/Node global, not a standard-JS built-in, and is not
  listed among the available built-ins (`JSON`, `Math`, `Array`, etc.).
- **`Date.now()`, `Math.random()`, bare `new Date()`, `import()` throw at runtime** ("they would break
  resume"). This repo's own generator already enforces this as a hard, tested constraint:
  `compound-v-emit-workflow.py:149-154` (`FORBIDDEN_PATTERNS`), with a selftest that plants each construct
  and confirms it's caught (`:5800-5825`).
- **Consequence for the spec as written:** the design's backoff (`wait min(60000, 2000*2**(attempt-1))
  ± jitter`) and its logged `ts` field require, respectively, a wait primitive and a timestamp source — and
  **neither exists** inside the JS sandbox by any documented mechanism. This is not a style objection; it
  is a hard runtime capability gap the plan must resolve (e.g. timestamps via `args`/post-return stamping,
  as the doc prescribes; a real wait has no documented equivalent at all — worth a live probe before
  design, not an assumption).
- **`agent()`'s own failure signal for a terminal API error is `null`, not a throw** — stated identically
  in two independent places: the `workflow-authoring` skill ("Returns null if... the subagent dies on a
  terminal API error after retries") and this repo's own `gateStage` banner comment
  (`compound-v-emit-workflow.py:2061-2063`: *"agent() returns null when it is skipped or dies on a
  terminal API error"*). The plan's `withRetry` is built entirely around `try { fn() } catch (err) {
  String(err).match(...) }` — **a design that structurally cannot fire for the failure signal the
  runtime documents for exactly the scenario (transient API death) this feature exists to handle**, unless
  `agent()` is verified, live, to also throw in some subtransient case before resolving null. Given the
  spec's own probe evidence ("Three consecutive `API Error: 529 Overloaded`... each cost a run") reads
  like a thrown/surfaced error string was actually observed, this needs a live, targeted verification
  against the installed binary — the same standard this file already holds itself to for the determinism
  constraints (":135-136: 'verified against the installed Claude Code 2.1.238 binary and its own error
  strings'") — before `withRetry` is designed around either assumption.
- **Resume determinism tension:** per the `workflow-authoring` skill, resume replays the "longest
  unchanged prefix of `agent()` calls" from a cache keyed by call sequence. A `withRetry` loop that calls
  `agent()` a variable number of times (1 to `max_attempts`) inside one stage call introduces a
  variable-length subsequence into that prefix. Nothing in the spec or plan addresses what a resume does
  if it lands mid-retry-loop.

## 5. Regression Surface

- **Every job, not just reviewers, goes through `implementStage`.** The plan's instruction ("wrap every
  `agent(...)` call in the stage functions") means a naive classifier regex now sits in the hot path for
  every dispatch. `compound-v-classify-failure.py`'s own rule ordering exists specifically because
  `out_of_credits` and `rate_limited` share substrings ("429") and MUST be checked in priority order
  (comment, `:43-46`). The plan's proposed single regex (`/529|Overloaded|overloaded_error|rate.?limit|
  429|ECONNRESET|ETIMEDOUT|network/i`) has no such ordering and would misclassify an `insufficient_quota`
  429 (out-of-credits, never-retry per policy) as retryable — burning `max_attempts` retries on a job that
  should have failed fast, for every job in every run, not just the reviewer scenario the spec cites.
- **`recordStage` and `finalizeWave`'s `agent()` calls are transport-only**, not content-producing. Their
  existing catch blocks already convert an exhausted/rethrown error into `{recorded: false, ...}` /
  `{integrated: false, ...}` (`:2242-2248`, similar at `:2299+`). If `withRetry` exhausts on one of these
  and the *content* work (the job's own diff) already succeeded, the consequence is not "misclassified
  failure_class" — it's that `record` (or `finalize-wave`) **never runs**, so `results/<id>.json` is never
  written at all. That is a full audit-trail loss for a job whose actual work was fine, a sharper version
  of the exact v2.6.4 incident (execution audit artifacts silently lost) this project's own MEMORY.md
  records as a real, previously-fixed incident. The plan treats all four stages' `agent()` calls as
  equivalent retry targets; they are not equivalent in blast radius.
- **`implementStage`'s existing inner try/catch (`:2027-2042`) already handles one specific failure mode**
  — `isAgentTypeMissing(spawnErr)` — with its own fallback (inline agent definition, no retry-with-backoff
  involved). `withRetry` must be composed around this existing branch without swallowing or duplicating it;
  the plan doesn't mention this existing structure at all.
- **`_is_reviewer_job` exemption (`:1552-1566`) is a live, deliberate guard against a *different*
  escalation mechanism** (cross-run, triggered by `prior_attempt_failed` on `/v:resume` re-emission). The
  new in-workflow, same-run escalation must not be implemented by relaxing or routing through this guard —
  it protects a genuinely different trigger and, per §2, a rationale that (for fast_path) is still real.
- **No `logs/` directory convention exists in a run-dir today.** An earlier archaeology
  (`docs/superpowers/archaeology/2026-07-11-session-aware-workers.md`) states this explicitly: *"no
  `logs/` convention exists today."* `retries.jsonl` under `<run>/logs/` is new ground — crash-safety
  (atomic append vs. the existing `_atomic_write`/`_atomic_write_bytes` whole-file-replace helpers,
  `:278-303`, neither of which is an append primitive) and whether it needs to be **committed** as part of
  the run's audit trail (per v2.6.4) are both open questions the plan doesn't address.
- **`gate-receipt`'s current argument surface has no `--escalated-from` flag.** `cmd_gate_receipt`'s full
  `argparse` list (`:2809-2830`): `--run-dir, --job-id, --worktree, --impl-no-result, --manifest, --mode,
  --repo-root, --scope-check, --fastpath, --python, --manifest-digest, --now`. The plan's "pass
  `--escalated-from deep` to gate-receipt" is a new CLI surface to add, in-scope for Task A (same file),
  but not yet present — confirmed absent, not merely unverified.

## 6. DRY Findings

- **Classification logic is being reinvented a third time.** `compound-v-classify-failure.py` already
  encodes backend-aware, priority-ordered substring rules (codex/claude/antigravity/cursor variants) plus,
  for claude specifically, an **authoritative structured path** (`_parse_claude_json`, parsing the
  stream-json `api_retry.error` enum — `:181-208`) with substring matching only as a documented fallback
  "when the output isn't JSON." The plan's flat JS regex over `String(err)` reuses none of this and is
  strictly weaker than even the claude fallback path the Python side already rejected as "narrow ... on
  purpose" and only-a-fallback. **Decision needed:** either shell out to the existing classifier (as
  `gate-receipt`/`record`/`finalize-wave` already do for other CLI calls, via a spawned transport agent),
  or, if `agent()`'s thrown/returned error carries no structured type the JS can pass to that classifier,
  document that a genuinely new, narrower classifier is required and justify why it can't reuse the
  existing needle set/priority order.
- **Backoff+jitter math already exists** (`compound-v-failure-policy.py:_backoff`, §3 above) and runs in a
  Python process unconstrained by the Workflow sandbox's `Math.random()` ban. The plan re-derives a
  different jitter shape from scratch inside the JS sandbox, where `Math.random()` is unavailable at all
  (§4) — meaning the reimplementation isn't just duplicative, it may be **unbuildable as specified**.
- **The reviewer-escalation ladder already exists** (`escalate_claude_model`, `CLAUDE_ESCALATION`, §2) and
  already has the "don't touch a model we don't own" safety property the plan's hardcoded `'fable'` literal
  lacks. Extend/call it; don't re-literal it.
- **Per-class retry ceilings already exist** (`PER_CLASS_MAX`, §3) with different values per class. The
  plan's single `max_attempts` knob is a new, coarser shape — extend the existing table (or explicitly
  decide manifest-level control should override it, and say why) rather than shipping two divergent retry
  budgets for the same failure classes across the two dispatch engines.

## 7. Design constraints for the spec (non-negotiable)

1. **Verify, live, whether `agent()` throws or resolves `null` on a transient API-death (529/overloaded).**
   This repo's own code and the `workflow-authoring` skill both document `null`-on-terminal-API-error, not
   throw (`compound-v-emit-workflow.py:2061-2063`). If that holds, `withRetry`'s `try/catch(err)` design
   catches nothing for the exact scenario (Opus reviewer 529) that motivated this feature, and the
   mechanism must be redesigned around a `null`-return check, not a thrown-error classifier.
2. **There is no `sleep`/timer/`Date.now`/`Math.random` primitive available inside a Workflow script**
   (verified against the installed binary's own constraints, already enforced by this file's
   `FORBIDDEN_PATTERNS`/`forbidden_hits` selftest). A literal "wait N ms with jitter" as specified cannot
   be built with any documented JS built-in. Resolve this architecturally (e.g., timestamps via `args` or
   post-return stamping per the runtime's own prescription; find or justify a substitute for the wait
   itself) before writing `withRetry`.
3. **Do not treat all four stage functions' `agent()` calls as equivalent retry targets.** `recordStage`/
   `finalizeWave`'s calls are transport-only; exhausting retries there means the job's result/wave commit
   never gets written at all (worse than a misclassified `failure_class`, and the exact shape of the
   v2.6.4 audit-trail-loss incident). Decide per-stage whether/how retry-exhaustion differs from today's
   existing catch-and-convert-to-value behavior, which already exists and already prevents an unhandled
   throw from escaping any stage (`compound-v-emit-workflow.py:2054-2063` banner, repeated per stage).
4. **Reuse `escalate_claude_model`/`CLAUDE_ESCALATION` for the reviewer lift, not a hardcoded `'fable'`
   literal** — the existing function already refuses to escalate a model it doesn't own (an explicit
   manifest `model:` pin), a safety property the plan's literal lacks.
5. **Resolve the three-way reviewer-Opus-invariant inconsistency before editing `execution-manifest.md`:**
   the manifest-declaration gate already accepts Fable (finding 119); the fast_path receipt gate
   (`_is_claude_opus`, schema `const: "deep"`) still requires literal Opus and is explicitly meant to;
   `execution-manifest.md:78-80`'s prose currently states the pre-119 (stale) version of the invariant as
   if universal. Fix the stale doc text in the same edit that documents the new retry-lift, or the doc
   will contradict itself in two adjacent paragraphs.
6. **State explicitly whether `fast_path` reviewers are in scope.** They currently cannot be escalated
   (schema-forbidden, `reviewer_tier: const: "deep"`) and are dispatched through a code path
   (`compound-v-fastpath-run.py` `review-spec`/`accept-review`) this plan's Partition Map never touches.
   If out of scope, the exact incident this spec cites can still recur unmitigated on a fast_path run —
   say so as a deliberate cut, not by omission.
7. **A naive single-regex classifier will misclassify `out_of_credits` as retryable** (both share `429`)
   unless it adopts the existing priority-ordered rule set (`out_of_credits` before `rate_limited`) from
   `compound-v-classify-failure.py`, or reuses that classifier directly.
8. **Match `retry.max_attempts`'s relationship to the existing per-class `PER_CLASS_MAX` table
   explicitly** (`rate_limited:3, overloaded:2, network:2, timeout:1`) — a flat default of 3 applied
   uniformly is not a restatement of the existing, already-tuned policy; decide whether it overrides it
   and document why.
9. **If a jitter formula is achievable at all inside the sandbox, match the sibling's shape** (additive
   `uniform(0, BACKOFF_BASE)`, flat regardless of magnitude) rather than a from-scratch multiplicative
   `± 25%` that diverges from the existing policy as attempts grow.
10. **Address resume semantics for a variable-length retry loop** inside a single `agent()` call site,
    given the Workflow runtime's documented resume-by-cached-call-prefix model.

## 8. File Touch Map (for Phase 2 partitioning)

| File | Role | SHARED RESOURCE? |
|---|---|---|
| `scripts/compound-v-emit-workflow.py` | 7,249 lines. Owns `emit_script` (JS template incl. all 4 stage functions), `_job_result_from`/`cmd_record` (`failure_class` write), `cmd_gate_receipt` (CLI surface for a new `--escalated-from`), `escalate_claude_model`/`_is_reviewer_job`/`CLAUDE_ESCALATION`, `FORBIDDEN_PATTERNS`/`forbidden_hits` (the determinism guard the new JS must pass), `selftest()` (~2,100 lines of its own, :5125-7226). **Already flagged by the plan itself as turn-budget-exhausting for five prior implementers** — grep-only reads, never a full read, per the plan's own header note. | **SHARED RESOURCE** — single largest generated-JS-template file in the repo; any other in-flight task touching Engine C's dispatch collides here. |
| `scripts/compound-v-validate-manifest.py` | 5,753 lines. Owns the new top-level `retry` block validation (no existing top-level schema constant — validation is per-block, ad hoc, matching the style of `triage`/`test_contract`/`fast_path`), and the THREE separate reviewer-Opus gates documented in §2 (`_is_claude_opus`, the `_is_reviewer`/finding-119 manifest check, `_review_resolution`/fast_path). | **SHARED RESOURCE** — same reasons; also the authority the `partition-reviewer` and `spec-reviewer` agents depend on. |
| `skills/compound-v/execution-manifest.md` | Human-readable schema doc. Contains the stale finding-119-contradicting invariant text (§2, §7.5) that must be corrected in the same edit. | Not generated/codegen, but read by every planner — treat edits carefully for the stale-text fix. |
| `skills/compound-v/failure-policy.md` | Documents the existing Python classify→decide loop (read in full for §3/§6). One new paragraph per the plan. | No. |
| `CHANGELOG.md` | `[Unreleased]` entry. | No — append-only convention, low collision risk if the entry is appended, not inserted mid-file. |
| `agents/parallel-dispatcher.md` | **Not in the plan's Partition Map**, but is the sibling this spec explicitly says already "owns the right policy" (§3) and the only place that could give the residual dispatcher reviewer-lift parity (§3, §7.6). Confirm the parity gap is an intentional cut before treating this file as out of scope. | Not touched by this plan as scoped; flagged here because §3/§7 depend on it being an explicit decision, not silence. |
| `schemas/fastpath-review-receipt.schema.json` | **Not in the plan's Partition Map.** Hard-schemas `reviewer_tier: const: "deep"` — the concrete artifact that makes fast_path reviewer escalation impossible without a schema change (§1, §7.6). | Not touched by this plan as scoped; same caveat as above. |
