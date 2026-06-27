# Phase 3 — Manifest-Driven Parallel Dispatch

**When this fires:** A plan with a verified Partition Map and a validated [`manifest.yaml`](execution-manifest.md) exists (Phase 2 emitted both), ready to execute.

**Goal:** Read `manifest.yaml` and dispatch each job to the backend the manifest names (Claude subagent or headless Codex worker) via the [`backend-launcher`](../backend-launcher/SKILL.md) contract, concurrently per batch, with strict scope locks and **per-job isolation** — direct writes to the active workspace where safe, an isolated git worktree where the job is risky or runs on an external backend. **Opus by default for Claude jobs; Sonnet only for the narrow junior-level mechanical tasks defined below; backend/model/isolation are read from the manifest, not re-decided here.** After every job the **scope gate** runs and `state.json` is updated.

> **Agent-driven flow, deterministic enforcement (by design).** The orchestration *flow* below — read the manifest, dispatch batches, honor `depends_on`/`run`/`max_parallel`, run reviews — is intentionally **agent-driven**, not a standalone executable dispatcher daemon. That is the deliberate Engine A choice (PRD §3.1, anti-ruflo: no daemon, no MCP server, no scheduler process). The **enforcement**, by contrast, is fully **deterministic scripts**: [`compound-v-scope-check.py`](../../scripts/compound-v-scope-check.py) (the git-derived scope gate) and [`compound-v-validate-manifest.py`](../../scripts/compound-v-validate-manifest.py) (the invariant gate). The safety guarantees live in those scripts, not in the flow — an agent driving the flow cannot weaken a guarantee the scripts enforce. This is intent, not a gap.

> **Compatibility:** the older "no worktrees, direct writes only" stance from 0.1.x is now **per-job isolation** (the manifest's `isolation` field). Direct writes remain the default for in-harness Claude jobs whose partition is clean; worktrees are used where a job is risky (touches a broad/shared surface) or runs on an external backend (Codex is **always** worktree). A bare plan path with no manifest still works — the dispatcher materializes a manifest first (see `commands/v-dispatch.md`), then proceeds as below.

## Concurrency Reality (from 2026 Claude Code testing)

- **Foreground parallel limit: 4-6 Task calls in one message.** Beyond that you hit rate-limit cascades and permission-prompt thrashing.
- **Background limit (`run_in_background: true`): 5-10.** Background agents auto-deny permission prompts (use already-granted perms) and the parent gets a notification when each finishes.
- **If your plan has N>6 parallel tasks**, batch them: dispatch 4-6 at a time, wait for the batch to return, dispatch the next batch. Document the batches in the Partition Map.
- **`run_in_background: true` for the implementer batch is acceptable** when permissions are pre-granted for the workspace — it lets you continue orchestration work while implementers run. Background subagents do NOT carry working-directory state between Bash calls; foreground subagents do. Plan accordingly.
- **Cap runaway reasoning:** include `maxTurns: 15` (or your project's limit) on every dispatched Claude Task call. Implementers that haven't finished in 15 turns are usually stuck and need a re-dispatch with more context, not more turns. (Codex worker jobs are bounded by `timeout_sec` in the `job_spec` instead — see `backend-launcher`.)

## The Three Overrides

This phase replaces three defaults from `subagent-driven-development`:

| Default | Compound V |
|---------|---------------|
| "Never dispatch multiple implementation subagents in parallel (conflicts)" | **Dispatch all parallel-batch jobs in parallel** (batched at 4-6 concurrent) — Partition Map + the manifest's disjoint `write_allowed` guarantee no conflicts |
| "Use the least powerful model that can handle each role" / cheap model for mechanical tasks | **Opus by default; Sonnet allowed only when the job passes the strict junior-task taxonomy below.** The manifest's `model` already encodes this per job (routed by `routing-policy.md`); reviewers are always Opus. |
| Isolated workspace via git worktrees | **Per-job isolation** — the manifest's `isolation` field: `direct` writes to the active workspace where the partition is clean and the backend is in-harness; `worktree` where the job is risky or external. **Codex jobs are always `worktree`.** Either way the scope gate runs on return. |

The first override is safe ONLY because Phase 2 produced a verified Partition Map and a validated manifest. Without them, revert to sequential dispatch.

> **Why isolation is now per-job, not blanket-off.** 0.1.x did direct writes only because every job was an in-harness Claude subagent the partition could keep apart. v1.0 adds an out-of-process Codex worker whose sandbox can only restrict writes to a *directory* — so external/risky jobs need a worktree, and the git-diff scope gate inside it is the enforcement. Direct writes are still the default for clean in-harness Claude jobs; worktrees are reserved for "risky or external," not imposed on everything. This is the reconciliation of the old "no worktrees" rule, not its reversal.

---

## Model Selection Taxonomy (Opus Default, Narrow Sonnet Exception)

> In the v1.0 flow this decision is already made for you: [`routing-policy.md`](routing-policy.md) routes each job's `type` to a **`tier`** (`deep`/`standard`/`light`) when Phase 2 materializes the manifest, and the dispatcher resolves that tier to a concrete `model` via [`compound-v-resolve-model.py`](../../scripts/compound-v-resolve-model.py) before dispatch (Step 2). Wherever this section says `model: opus` / `model: sonnet`, read it as **the resolved output of a tier** (`deep`/`standard`→`opus`, `light`→`sonnet`) — the literal strings are illustrative, not hardcoded call-site values. The taxonomy below is the *rationale* the routing policy encodes — keep it as the check when you author a job's `tier`, or when you run a bare-plan flow with no manifest yet. Either way the rule is identical.

**Default: Opus.** Every Claude implementer runs on Opus unless the job passes ALL the boxes for Sonnet eligibility below. Reviewers (spec + quality) are ALWAYS Opus — they're the safety net, and a cheap reviewer is no reviewer. (Codex jobs carry their own model, e.g. `gpt-5.5`, set by the routing policy — that is execution-layer data and never appears in any frontmatter.)

### When Sonnet IS allowed (the "Junior Dev" carve-out)

A task may use `model: "sonnet"` ONLY if EVERY one of these is true:

- [ ] **Single file**, ≤ 200 LOC change total
- [ ] **Mechanical transformation** with no design judgment: rename, find-and-replace, format conversion, lint-fix, adding a known-pattern boilerplate (e.g. adding a translation key everywhere it's referenced)
- [ ] **Spec is so explicit** a competent junior dev could complete it without asking design questions
- [ ] **No cross-file integration** — the change does not affect callers, types in other files, or any other task in the parallel batch
- [ ] **Tests already exist OR test code is fully provided in the task** (the implementer is not designing tests, just adding minimal impl to make provided tests pass)
- [ ] **Task description includes the EXACT before/after** for each meaningful change (no "figure out the pattern")
- [ ] **No external API calls** — talking to APIs requires domain judgment Sonnet is more likely to miscall
- [ ] **No security / auth / payments / PII / accessibility (a11y/ARIA) surface** — these always need senior-level reasoning regardless of how mechanical they look. (a11y is in the exclusion list because ADA/EAA legal exposure is real, and screen-reader/keyboard-nav correctness requires judgment a junior model frequently miscalls.)

If you can't tick ALL boxes → Opus. There is no "mostly junior" tier.

### Canonical Sonnet-eligible tasks (real examples)

✅ Rename `getCwd` → `getCurrentWorkingDirectory` across 12 call-sites in one file
✅ Add a new entry to the i18n string table file for an existing message (English + the 4 already-present locales, given exact strings)
✅ Convert a CommonJS `require`/`module.exports` file to ESM `import`/`export` syntax (mechanical 1:1)
✅ Apply a Prettier/eslint --fix style normalization to a generated file
✅ Add a CSV export that exactly mirrors a TSV export already in the codebase, file-for-file

### Canonical Sonnet-INELIGIBLE tasks (require Opus)

❌ "Implement the OAuth callback handler" — design judgment + security surface
❌ "Add a new field to the User type, propagate everywhere" — cross-file integration
❌ "Extend the existing pricing calculator to handle EU VAT" — domain reasoning
❌ "Write the unit tests for the new payments client" — designing tests = senior work
❌ "Refactor module X for clarity" — there's no clear before/after; it's all design judgment

### Defaults when in doubt

When you can't decide → Opus. The cost difference is real but small compared to the cost of a Sonnet-shipped bug surviving review and reaching prod.

### Marking the model decision in the Partition Map

Every parallel task in the Partition Map should declare its model:

```markdown
| Task | Files | Model | Sonnet justification (if applicable) |
|------|-------|-------|--------------------------------------|
| 1: OAuth callback | src/routes/oauth/callback.ts, …test.ts | opus | — (design + security) |
| 2: Rename getUser→fetchUser | src/lib/user-loader.ts | sonnet | Mechanical rename, single file, all call-sites listed, no design |
| 3: Add EU locale strings | src/i18n/strings/{en,de,fr,it,es}.json | sonnet | Pure data; exact key/value pairs in task |
```

If the "Sonnet justification" column is empty for a Sonnet task, the partition is wrong — switch to Opus.

## The Dispatch Sequence

Read `manifest.yaml`. Honor `depends_on`, `run`, and `max_parallel`. Each job is dispatched **to the backend its manifest entry names**, through the one [`backend-launcher`](../backend-launcher/SKILL.md) contract — the dispatcher builds a `job_spec`, hands it to the adapter for `backend`, and gets back a canonical `job_result`. The orchestrator speaks only that contract; it never sees backend-specific flags. After **every** job returns, run the scope gate and update `state.json` (Step 2b).

### Backend dispatch — one contract, two live adapters

For each job, the dispatcher builds a `job_spec` (`backend`, `prompt`, `tier`, optional `effort`, `model` [resolved from tier/effort, or an explicit manifest override], `cwd`, `write_allowed`, `read_only`, `timeout_sec`, `network`, optional `output_schema`) and routes by `backend`. The concrete `model` is resolved before dispatch by [`compound-v-resolve-model.py`](../../scripts/compound-v-resolve-model.py) (see Step 2 below):

- **`backend: claude`** → [`adapter-claude.md`](../backend-launcher/adapter-claude.md): an in-harness `Task` call with the `model` override and `maxTurns: 15`. `isolation: direct` writes to the active workspace against a baseline commit; `isolation: worktree` runs inside an isolated worktree.
- **`backend: codex`** → [`adapter-codex.md`](../backend-launcher/adapter-codex.md): a Bash-spawned headless `codex exec` worker (own process, own worktree — **always** `worktree`), via [`scripts/compound-v-run-codex-worker.sh`](../../scripts/compound-v-run-codex-worker.sh). Never an `agents/` entry, never the openai-codex broker.
- **`backend: antigravity`** → [`adapter-antigravity.md`](../backend-launcher/adapter-antigravity.md): a Bash-spawned headless `agy --print` worker (own process, own worktree — **always** `worktree`), via [`scripts/compound-v-run-antigravity-worker.sh`](../../scripts/compound-v-run-antigravity-worker.sh). **Lower-trust / opt-in** (no kernel sandbox); `--model` is omitted when empty. (Shipped 1.1.)
- **`backend: cursor`** → [`adapter-cursor.md`](../backend-launcher/adapter-cursor.md): a Bash-spawned headless `cursor-agent -p -f` worker (own process, own worktree — **always** `worktree`), via [`scripts/compound-v-run-cursor-worker.sh`](../../scripts/compound-v-run-cursor-worker.sh). **Lower-trust / opt-in** (no kernel sandbox; requires an authenticated `cursor-agent`); resolves tier→`model` (default `auto` — the only option on a Cursor Free plan). (Shipped 2.1.)

Every adapter returns the **same** `job_result` shape ([`schemas/job_result.schema.json`](../../schemas/job_result.schema.json)); enforcement is uniform because it lives in the caller's scope gate, not in the backend.

### Step 1: Serial Pre-Phase (Task 0), if present

If the manifest has a `type: shared_foundation`, `run: serial` job (shared types/migrations/configs):

- Dispatch **one** job — by its manifest backend, resolving its model first via `compound-v-resolve-model.py` (Task 0 routes `claude · tier: deep · direct` ⇒ **opus** in every stance).
- On return, run the scope gate (Step 2b) and write `state.json`.
- Wait for completion. Run spec + quality reviews (sequentially, on Opus). Address feedback.
- Only then proceed to the parallel batch (every parallel job `depends_on` it).

### Step 1b: Optional gated cross-model plan review (high-stakes only)

After the partition-reviewer returns **PASS** and before dispatching the parallel batch, the orchestrator MAY run an **optional gated cross-model plan review** — a read-only Codex second opinion per [`cross-model-review.md`](cross-model-review.md). Run it ONLY for high-stakes plans (security / auth / payments / migrations / shared data model, a large or coupled partition, an architectural change, or a human request); skip it for small/mechanical plans. It is **advisory only** — the orchestrator arbitrates every finding and Codex is never the authority. A clean review (or a skip) proceeds to dispatch; accepted findings fold back into the plan/manifest first.

### Step 2: Parallel Implementer Batch(es)

For all `run: parallel` jobs in the current batch, dispatch implementers **in a single message with concurrent calls — up to 4-6 per message** (the manifest's `max_parallel`) to stay under rate-limit cascades. If a batch has more than `max_parallel` jobs, split it; the manifest's `depends_on` + batch grouping define the order.

Each dispatch must include:

1. **Backend + tier/effort from the manifest; resolve the concrete model BEFORE dispatch** — never re-decide backend/tier/isolation here. The manifest carries the routing **intent** (`tier` ∈ {deep, standard, light}, optional `effort` ∈ {low, medium, high}) instead of a hardcoded model string, so the plugin survives model churn (refresh the config `models` map via `/v:models`, never the call sites). Before invoking the backend for a job, resolve the model with [`scripts/compound-v-resolve-model.py`](../../scripts/compound-v-resolve-model.py):

   ```bash
   # (backend, tier, effort, config) -> concrete model. --config points at the
   # project .claude/compound-v.json whose `models` map overrides built-in
   # defaults per cell; omit --config to use built-in defaults.
   # Build the flag list with explicit if/else (portable across bash AND zsh —
   # ${VAR:+...} conditional expansion does NOT word-split under zsh).
   set -- --backend "$BACKEND" --tier "$TIER"
   [ -n "$EFFORT" ] && set -- "$@" --effort "$EFFORT"
   [ -n "$CONFIG" ] && set -- "$@" --config "$CONFIG"
   RESOLVED=$(python3 scripts/compound-v-resolve-model.py "$@")
   MODEL=$(printf '%s' "$RESOLVED" | python3 -c 'import json,sys; print(json.load(sys.stdin)["model"])')
   ```

   - **`claude`** resolves tier→model: `deep`/`standard`→`opus`, `light`→`sonnet`. Pass the resolved model to the `Task` call. `effort` is advisory on this path — the `Task` call has no separate effort flag.
   - **`codex`** resolves tier→model (e.g. `deep`→`gpt-5.5`) and passes `--model <resolved>` **and** `--effort <effort>` to [`scripts/compound-v-run-codex-worker.sh`](../../scripts/compound-v-run-codex-worker.sh) (`--effort` → `-c model_reasoning_effort=<effort>`). The execution-layer model never appears in any frontmatter.
   - **`antigravity`** resolves tier→model (a Gemini name, e.g. `deep`→`Gemini 3.1 Pro (High)`) and passes `--model <resolved>` to [`scripts/compound-v-run-antigravity-worker.sh`](../../scripts/compound-v-run-antigravity-worker.sh) (omitted when empty; agy has no effort flag). `--write-allowed` is colon-joined globs; always `worktree`.
   - **`cursor`** resolves tier→model (default `auto`) and passes `--model <resolved>` to [`scripts/compound-v-run-cursor-worker.sh`](../../scripts/compound-v-run-cursor-worker.sh) (cursor has no effort flag). On a Cursor **Free** plan only `auto` works (named models error); set named ids per tier via config on a paid plan. Always `worktree`; requires an authenticated `cursor-agent`.
   - **An explicit manifest `model:` override skips resolution** (call the resolver with `--explicit-model <M>`, or pass the model straight through). This keeps existing explicit-model jobs valid — a job MUST carry `model` OR `tier`.

   A `claude` job lands on `opus` for `deep`/`standard` tiers, `sonnet` only where the manifest routed it `light` (the strict junior-task taxonomy above). Reviewer jobs always route `tier: deep` ⇒ opus.
2. **Turn/time bound:** `maxTurns: 15` on Claude Task calls; `timeout_sec` in the `job_spec` for Codex workers. An implementer that hasn't finished in 15 turns is usually stuck and needs a re-dispatch with more *context*, not more turns.
3. **`run_in_background: true`** is acceptable for the implementer batch — lets the orchestrator continue prep work while implementers run. The parent receives a notification per agent when it completes. Background subagents do NOT carry cwd state between Bash calls; **plan absolute paths in the prompt** (this is also why Codex worktree paths in the `job_spec` are always absolute).
4. **Strict scope lock** — paste this verbatim at the top of the prompt (it is the *instructed* half; the git-diff scope gate in Step 2b is the *enforced* half):

```
SCOPE LOCK (Compound V):

WRITE-allowed (you may create or modify these):
  - <task file 1>
  - <task file 2>

READ-allowed (you may read these, but NOT modify):
  - <Task 0 output file A>     # shared types
  - <Task 0 output file B>     # shared config
  - <archaeology audit path>   # design constraints

Writing to ANY file outside the WRITE-allowed list is a hard failure.
Reading ANY file outside both lists is a hard failure.

This includes: sibling parallel tasks' files (never read those — use the
shared types from Task 0 instead), config files, registries, barrels,
lockfiles, anything else.

If your task requires touching a file not in either list, STOP and
report BLOCKED with the file name and why. Do not improvise. Do not
"just peek."

You are running in parallel with N-1 other implementers. Each has a
non-overlapping WRITE list and the same READ list (Task 0 outputs +
audit). The Partition Map (in the plan) is the contract that makes
this safe.
```

**Auto-propagation rule:** Every parallel task's READ-allowed list automatically includes:
- All files Task 0 created or modified (its outputs are shared by design)
- The archaeology audit at `docs/superpowers/archaeology/<topic>.md`
- The domain-expert audit at `docs/superpowers/expert/<topic>.md`
- The library-audit at `docs/superpowers/library-audit/<topic>.md`
- The plan file itself if the subagent needs to look up cross-references (rare)

The controller builds the READ list from Task 0's commit diff. Don't make the subagent guess.

5. **Full task text** (don't make the subagent read the plan file — paste the task).
6. **Reference to ALL THREE audits' design constraints** — list them inline as MUST/MUST-NOT bullets:
   - From `docs/superpowers/archaeology/<topic>.md` § "Design constraints for the spec"
   - From `docs/superpowers/expert/<topic>.md` § "Design Constraints for the Plan"
   - From `docs/superpowers/library-audit/<topic>.md` § "Design Constraints for the Plan"
7. **TDD requirement**: follow `superpowers:test-driven-development` for each behavior change.
8. **Self-review requirement** before reporting DONE.

### Step 2b: Scope gate + state.json — after EVERY job returns

The SCOPE LOCK prose is advisory. The **authority** is the deterministic git-diff scope gate. Run it on every job the moment it returns when the job is isolated enough for per-job attribution — a `worktree` job or a **serial `direct`** job. For **parallel `direct`** jobs sharing one tree, the per-job gate is not deterministic (see the attribution note below); gate that batch as a unit instead. Regardless of backend or isolation:

```bash
# worktree job (codex always, claude when isolation: worktree)
python3 scripts/compound-v-scope-check.py --worktree "$WT" --allow-file "$ALLOW"
# direct job (in-harness claude against a pre-dispatch baseline commit)
python3 scripts/compound-v-scope-check.py --repo "$CWD" --baseline "$BASE" --allow-file "$ALLOW"
```

The gate computes what the job *actually* changed purely from git —
`git diff --name-only` ∪ `git ls-files --others --exclude-standard` — and matches each path against the job's `write_allowed`. These enforcement fields (`files_changed`, `violations`, `blocked`) are **git-derived, never model-self-reported**; the worker's `--output-last-message` / return text feeds only the human `summary`. See [`scripts/compound-v-scope-check.py`](../../scripts/compound-v-scope-check.py) and the rule in [`backend-launcher/SKILL.md`](../backend-launcher/SKILL.md).

> **Per-job scope attribution requires per-job isolation (worktree).** The gate reads a *repo-wide* diff. That is unambiguous for a `worktree` job (the worktree contains only that job's changes) and for a **serial `direct`** job (nothing else is writing the tree at the same time). It is **NOT** safe for **parallel `direct`** jobs sharing one working tree: each job's per-job gate would see its siblings' changes too, producing a false BLOCK or unattributable diff. So for parallel jobs, EITHER:
> - give each parallel job **`isolation: worktree`** for true per-job attribution (the routing policy already does this for risky/external jobs), OR
> - gate the parallel `direct` jobs at **batch granularity**: run the gate **once after the whole batch** against the **union of the batch's `write_allowed`**. This deterministically detects any *out-of-batch* leak (a path no job in the batch was allowed to write) but **cannot attribute a leak to a specific job**. Serial `direct` jobs keep their own per-job gate.
>
> When the partition mixes parallel `direct` jobs, prefer worktrees if you need per-job attribution; otherwise document that the batch is gated as a unit.

Then update `state.json` (the run's single source of truth — schema in [`state-machine.md`](state-machine.md)):

- **PASS** (no violation) → set the job `status: done`. For a worktree job, merge back with an **index-based patch that includes new (untracked) files** — `git -C "$WT" add -A && git -C "$WT" diff --cached --binary HEAD | (cd "$REPO" && git apply --index)` into the main tree, then `git worktree remove -f`. (A plain `git diff HEAD | git apply` would silently DROP allowed new files.) Direct jobs are already in the tree.
- **BLOCKED** (any path outside `write_allowed`) → set `status: blocked`, advance the run `phase` to terminal **BLOCKED**, surface the offending paths, and **do not merge** — leave the worktree for inspection. A BLOCKED job halts the run; it does not get silently re-dispatched.
- **failed / timeout / error** (a non-success backend *failure*, distinct from a scope-gate `blocked`) → run the **classify → policy → act** loop before deciding anything: classify the failure ([`compound-v-classify-failure.py`](../../scripts/compound-v-classify-failure.py)), look up the action ([`compound-v-failure-policy.py`](../../scripts/compound-v-failure-policy.py)), then **retry** (same backend, backoff), **reroute** (out_of_credits → circuit-break + env-aware codex→claude rewrite, announced loudly; context_length → bigger tier), or **halt** (mark `failed`, keep the run resumable, continue independent siblings). Never retry `out_of_credits`/`auth`; cap retries by count AND wall-clock. Full table: [`failure-policy.md`](failure-policy.md).

`state.json` is written after every per-job transition, so a crash never loses more than the in-flight job, and [`/v:resume`](../../commands/v-resume.md) can reconcile against git (git-wins) and re-dispatch only the incomplete.

> The wiring above is what [`agents/parallel-dispatcher.md`](../../agents/parallel-dispatcher.md) actually does: dispatch → scope-check → state.json, HALT on BLOCKED. This skill is the spec; that agent is the executable.

### Step 3: Parallel Reviewer Batch

When all N implementers return, dispatch **2N reviewer subagents** — one spec-compliance reviewer and one code-quality reviewer per task. Same batching rule applies: 4-6 per message. If 2N > 6 (e.g. N=4 tasks → 8 reviewers), split into two messages.

Each reviewer also gets `model: "opus"`. Reviewers also have a scope lock — they may only read the files of the task they're reviewing (plus the spec/audit for context).

### Step 4: Per-Task Fix Loops

If a reviewer flags issues on Task K:
- Re-dispatch ONLY Task K's implementer with the reviewer feedback.
- Re-dispatch ONLY Task K's reviewers when the fix lands.
- Other tasks stay done. No global re-run.

This is the second source of speed: failures are isolated to the task that failed.

### Step 5: Final Integration Review

After every task is approved and every worktree job has merged back (Step 2b), dispatch ONE final code-reviewer subagent (on Opus) that reads the full set of changes across all tasks and verifies:

- No partition leaked (the scope gate already enforced this per-job from git; the reviewer confirms nothing slipped through at the integration seam)
- Cross-task integration works (the types from Task 0 are used correctly by parallel tasks)
- The composite change matches the original spec + archaeology constraints **and the manifest's feature-level `acceptance_criteria`** (this is the AC-gate for the run)

This is the final pass of the three-pass Review Gate (spec / quality / integration) — see [`agents/spec-reviewer.md`](../../agents/spec-reviewer.md). On PASS, advance `state.json` to `MERGED` and hand off to `superpowers:finishing-a-development-branch`.

## Dispatch Template (implementer)

```
[Task tool call: subagent_type: "general-purpose", model: "opus", maxTurns: 15, description: "Implement Task K: <name>", run_in_background: true (optional)]

SCOPE LOCK (Compound V):
You may ONLY read and write these files:
  - src/middleware/auth.ts
  - src/middleware/auth.test.ts

Touching ANY file outside this list is a hard failure. If you need a file
not listed, STOP and report BLOCKED.

You are one of 3 parallel implementers. The Partition Map guarantees your
files do not overlap with siblings. Trust the partition.

---

DESIGN CONSTRAINTS (from archaeology audit):
- MUST handle all 4 server-type cells
- MUST fall back to apiKeyRecord.user_id when userId is undefined
- MUST NOT duplicate credential-injection logic

DESIGN CONSTRAINTS (from domain-expert audit):
- MUST use Notion v2 OAuth endpoint, Basic auth header (not body)
- MUST store workspace_id alongside the token
- MUST validate state parameter and exact redirect URI match

DESIGN CONSTRAINTS (from library-audit):
- MUST replace oauth2orize (abandoned 2022) with @node-oauth/oauth2-server
- MUST upgrade stripe-node v11 → v17 (needed for automatic_payment_methods)

---

TASK K: <name>

[paste full task text from plan, including all steps and code blocks]

---

PROCESS:
- Follow TDD: write failing test, watch it fail, minimal impl, watch it pass, commit
- Self-review before reporting DONE
- Report one of: DONE / DONE_WITH_CONCERNS / NEEDS_CONTEXT / BLOCKED

Use `superpowers:test-driven-development` for the test-first discipline.
```

## Dispatch Template (reviewer — spec compliance)

```
[Task tool call: subagent_type: "general-purpose", model: "opus", maxTurns: 10, description: "Spec-review Task K"]

You are reviewing Task K of a Compound V parallel implementation.

SCOPE: read only these files
  - src/middleware/auth.ts
  - src/middleware/auth.test.ts
  - docs/superpowers/archaeology/<topic>.md
  - docs/superpowers/expert/<topic>.md
  - docs/superpowers/library-audit/<topic>.md
  - docs/superpowers/plans/<plan>.md (Task K section + design constraints)

CHECK:
1. Code matches the spec/task as written
2. All MUST items from the archaeology audit are satisfied
3. No SCOPE LOCK violation (no edits to files outside Task K's assigned list)
4. Nothing extra was built that the spec didn't ask for

Report: APPROVED or ISSUES with specific line references.
```

## Cost Reality

Compound V is expensive per-task — the `deep`/`standard` tier (Opus) is a larger model than the `light` tier (Sonnet), and you're running multiple subagents per task (implementer + 2 reviewers). The "~5x" below is a pre-existing relative magnitude claim about Opus-vs-Sonnet list pricing, not a measured per-run figure — never print fabricated per-run token/cost numbers. Opus is ~5x the cost of Sonnet, but:

- **Wall-clock time** for N parallel tasks ≈ time for 1 task (the slowest one)
- **Quality** is higher (Opus catches issues cheap models miss)
- **Rework cost** is lower (archaeology + partition catches design bugs before they're code bugs)

Use Compound V when speed-to-shipping matters more than minimum cost. For tiny features or solo learning, default Superpowers is fine.

## What Can Still Go Wrong

| Failure | Cause | Fix |
|---------|-------|-----|
| Implementer K edited a file not in its WRITE list | Partition Map missed a coupling | Pause; investigate the missed coupling; add it to Task 0 or fix the partition; re-dispatch Task K |
| Implementer K silently created a new file not in any list | Partition Map missed a needed file; subagent improvised instead of reporting BLOCKED | Reject the new file; investigate why it was needed; either add to Task K's WRITE list (if exclusive) or to Task 0 (if shared); re-dispatch Task K with the updated scope and a reminder: "improvising new files is a scope-lock violation" |
| Implementer K read a file not in its READ list | Auto-propagation missed a Task 0 output, or subagent peeked | If file is genuinely a Task 0 output, fix the READ list and re-dispatch (controller error). If subagent peeked at a sibling's WRITE file, reject and re-dispatch with stronger reminder. |
| Two tasks both modified a barrel/index file | Index file wasn't in Task 0 | Add it; the implementers each guessed at the export; resolve by hand and re-run |
| Tests pass per-task but integration fails | Cross-task assumption diverged | Final integration reviewer should catch this; fix in a sequential follow-up task |
| Subagent returned BLOCKED with "I need to read sibling file" | Scope lock was correct; partition was incomplete | Add the sibling file to Task 0 or merge the two tasks; revise plan |
| Opus model unavailable / rate-limited | Capacity issue | Fall back to most-capable available; document the fallback |
| Codex job wrote outside its directory worktree | Codex sandbox restricts to a *directory*, not a file allow-list | The scope gate catches it from `git diff` on return → `status: blocked`, no merge; tighten `write_allowed` and re-dispatch |
| Worktree merge-back conflicts with another job | Two worktree jobs' diffs touched the same line (partition leaked) | Should be impossible under a disjoint partition; if it happens the partition was wrong — the scope gate flags the overlap, resolve by hand and revise the manifest |

## Red Flags — STOP

- "Let me just dispatch them one by one to see what happens" → that's sequential; you've left Compound V
- "Sonnet is fine for this simple task" → no; the override is hard
- "I'll skip Task 0, the types are obvious" → no; without Task 0 the parallel batch races on types
- "The plan doesn't have a Partition Map but I'll figure it out as I go" → STOP; go back to Phase 2
- "I'll trust the worker's report of what it changed" → no; enforcement is **git-derived**, run the scope gate (Step 2b) on every job — never trust a model to self-report its writes
- "A Codex job can run direct, the worktree is overhead" → no; Codex ⇒ worktree is a hard invariant (the sandbox can't enforce a file allow-list)
- "I'll route the model/backend myself per task" → no; backend/tier/isolation come from the manifest (routed by `routing-policy.md`); the concrete model is resolved from `(backend, tier, effort, config)` via `compound-v-resolve-model.py` before dispatch — don't hardcode model strings
- "I'll hardcode `gpt-5.5` / `opus` in the job_spec" → no; pass `tier`/`effort` and let the resolver produce the model, so a model-churn refresh via `/v:models` (not a call-site edit) keeps routing alive. Only an explicit manifest `model:` override is hand-set, and it skips resolution.

## Handoff

After final integration review passes, hand off to `superpowers:finishing-a-development-branch`.
