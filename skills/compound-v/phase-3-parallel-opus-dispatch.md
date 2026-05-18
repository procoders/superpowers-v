# Phase 3 — Parallel Opus Dispatch

**When this fires:** Plan with verified Partition Map exists, ready to execute.

**Goal:** Dispatch all parallel-batch implementers concurrently with strict scope locks, direct writes to the active workspace. **Opus by default; Sonnet only for the narrow set of clearly junior-level mechanical tasks defined below.** No worktrees, no sequential drag.

## Concurrency Reality (from 2026 Claude Code testing)

- **Foreground parallel limit: 4-6 Task calls in one message.** Beyond that you hit rate-limit cascades and permission-prompt thrashing.
- **Background limit (`run_in_background: true`): 5-10.** Background agents auto-deny permission prompts (use already-granted perms) and the parent gets a notification when each finishes.
- **If your plan has N>6 parallel tasks**, batch them: dispatch 4-6 at a time, wait for the batch to return, dispatch the next batch. Document the batches in the Partition Map.
- **`run_in_background: true` for the implementer batch is acceptable** when permissions are pre-granted for the workspace — it lets you continue orchestration work while implementers run. Background subagents do NOT carry working-directory state between Bash calls; foreground subagents do. Plan accordingly.
- **Cap runaway reasoning:** include `maxTurns: 15` (or your project's limit) on every dispatched Task call. Implementers that haven't finished in 15 turns are usually stuck and need a re-dispatch with more context, not more turns.

## The Three Overrides

This phase replaces three defaults from `subagent-driven-development`:

| Default | Compound V |
|---------|---------------|
| "Never dispatch multiple implementation subagents in parallel (conflicts)" | **Dispatch all parallel-batch tasks in parallel** (batched at 4-6 concurrent) — Partition Map guarantees no conflicts |
| "Use the least powerful model that can handle each role" / cheap model for mechanical tasks | **Opus by default; Sonnet allowed only when task passes the strict junior-task taxonomy below.** Reviewers always Opus. |
| Isolated workspace via git worktrees | **Direct writes to active workspace** — Partition prevents collisions |

The first override is safe ONLY because Phase 2 produced a verified Partition Map. Without the map, revert to sequential dispatch.

---

## Model Selection Taxonomy (Opus Default, Narrow Sonnet Exception)

**Default: Opus.** Every implementer dispatched on Opus unless the task passes ALL the boxes for Sonnet eligibility below. Reviewers (spec + quality) are ALWAYS Opus — they're the safety net, and a cheap reviewer is no reviewer.

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

### Step 1: Serial Pre-Phase (Task 0), if present

If the plan has a Task 0 with shared types/migrations/configs:

- Dispatch **one** implementer subagent for Task 0 on Opus.
- Wait for completion. Run spec + quality reviews (sequentially, on Opus). Address feedback.
- Only then proceed to parallel batch.

### Step 2: Parallel Implementer Batch(es)

For all parallel-batch tasks, dispatch implementers **in a single message with concurrent Task tool calls — up to 4-6 per message** to stay under rate-limit cascades. If N > 6, batch them; document batches in the Partition Map ("Batch A: Tasks 1-5", "Batch B: Tasks 6-10").

Each dispatch must include:

1. **Model override:** `model: "opus"` (or `claude-opus-4-7`) by default. `model: "sonnet"` only when the task passed the strict junior-task taxonomy above (and only with the explicit Sonnet-justification recorded in the Partition Map).
2. **`maxTurns: 15`** to cap runaway reasoning. An implementer that hasn't finished in 15 turns is usually stuck and needs a re-dispatch with more *context*, not more turns.
3. **`run_in_background: true`** is acceptable for the implementer batch — lets the orchestrator continue prep work while implementers run. The parent receives a notification per agent when it completes. Background subagents do NOT carry cwd state between Bash calls; plan absolute paths in the prompt.
4. **Strict scope lock** — paste this verbatim at the top of the prompt:

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

After every task is approved, dispatch ONE final code-reviewer subagent (on Opus) that reads the full set of changes across all tasks and verifies:

- No partition leaked (no file touched outside its assigned task)
- Cross-task integration works (the types from Task 0 are used correctly by parallel tasks)
- The composite change matches the original spec + archaeology constraints

Then hand off to `superpowers:finishing-a-development-branch`.

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

Compound V is expensive per-task — Opus is ~5x the cost of Sonnet, and you're running multiple subagents per task (implementer + 2 reviewers). But:

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

## Red Flags — STOP

- "Let me just dispatch them one by one to see what happens" → that's sequential; you've left Compound V
- "Sonnet is fine for this simple task" → no; the override is hard
- "I'll skip Task 0, the types are obvious" → no; without Task 0 the parallel batch races on types
- "The plan doesn't have a Partition Map but I'll figure it out as I go" → STOP; go back to Phase 2

## Handoff

After final integration review passes, hand off to `superpowers:finishing-a-development-branch`.
