# Phase 2 — Disjoint File Partitioning

**When this fires:** Inside `writing-plans`, after the spec and archaeology audit have been read, before defining tasks.

**Goal:** Structure the plan so that tasks have **mutually exclusive, non-overlapping file sets** — making parallel implementation safe.

## The Core Rule

**Every file is owned by exactly one task.** If two tasks need to touch the same file, the partition is wrong — redesign it.

This is the structural guarantee that makes Phase 3 (parallel Opus dispatch) safe. The default Superpowers rule "never dispatch implementers in parallel" exists *only because* default plans allow file overlap. Eliminate the overlap and the rule no longer applies.

## The Partition Map (required plan section)

Every Compound V plan **must** start with a Partition Map immediately after the Goal/Architecture header:

```markdown
## Partition Map

**Serial pre-phase (Task 0):** files all parallel tasks depend on
- `src/types/auth.ts` — new types used by Tasks 1, 2, 3
- `db/migrations/0042_oauth.sql` — migration ordering matters

**Parallel tasks (run concurrently):**

| Task | Files (exclusive ownership) |
|------|----------------------------|
| 1: Auth middleware | `src/middleware/auth.ts`, `src/middleware/auth.test.ts` |
| 2: Credential extension | `src/lib/credentials.ts`, `src/lib/credentials.test.ts` |
| 3: OAuth callback route | `src/routes/oauth/callback.ts`, `src/routes/oauth/callback.test.ts` |

**Verification:** No file appears in two rows. ✅
```

If you cannot truthfully write "No file appears in two rows. ✅", the partition is wrong. Redesign.

## How To Partition

### Default approach: split by feature slice, not by layer

**Bad partition (layer-based, overlaps):**

| Task | Files |
|------|-------|
| 1: Backend | `routes.ts`, `service.ts`, `db.ts` |
| 2: Frontend | `App.tsx`, `api-client.ts` |
| 3: Tests | `routes.test.ts`, `service.test.ts`, `App.test.tsx` |

Task 3 reads files Tasks 1 and 2 wrote — they can't run in parallel.

**Good partition (slice-based, disjoint):**

| Task | Files |
|------|-------|
| 1: OAuth login slice | `routes/oauth.ts`, `routes/oauth.test.ts`, `components/OAuthButton.tsx`, `components/OAuthButton.test.tsx` |
| 2: Session refresh slice | `lib/session-refresh.ts`, `lib/session-refresh.test.ts`, `hooks/useSession.ts`, `hooks/useSession.test.ts` |
| 3: Logout slice | `routes/logout.ts`, `routes/logout.test.ts`, `components/LogoutButton.tsx`, `components/LogoutButton.test.tsx` |

Each task owns its files end-to-end (route + component + tests). No overlap. Parallel-safe.

### Tests live with the code they test

Pair `foo.ts` and `foo.test.ts` in the same task. Never split implementation and tests into separate tasks — that forces sequential dependency.

## Shared Resources → Serial Pre-Phase

Some files are inherently shared:

- **Type declaration files** other tasks import from
- **Generated files**: lockfiles, schema dumps, codegen outputs
- **Migrations**: ordering matters
- **Config/registry files**: route registries, plugin lists, barrel files (`index.ts` that re-exports)
- **Single-source documentation**: README, CHANGELOG

Put these in **Task 0 (serial pre-phase)** that runs to completion BEFORE the parallel batch starts. Task 0 is a single sequential task; the parallel batch starts only after Task 0 commits.

```markdown
### Task 0 (Serial Pre-Phase): Shared types and migration

**Files (exclusive):**
- Create: `src/types/auth.ts`
- Create: `db/migrations/0042_oauth.sql`
- Modify: `src/types/index.ts` (barrel export)

[steps...]

### Task 1 (Parallel batch): OAuth login slice
[depends on Task 0]
...

### Task 2 (Parallel batch): Session refresh slice
[depends on Task 0]
...
```

## When Partitioning Is Impossible

Sometimes a plan genuinely can't be partitioned (deep coupling, refactor that touches every file). In that case:

1. **Document why** at the top of the Partition Map: "Partition not possible — refactor touches shared file X. Reverting to sequential execution per default Superpowers."
2. **Skip Phase 3 parallel dispatch.** Use standard `subagent-driven-development` sequentially.
3. **Flag this for follow-up:** is there a smaller refactor that would *enable* partitioning for future plans? Compound V rewards investments that unlock partitioning.

Compound V is not a hammer — when partitioning is impossible, fall back gracefully. But the bar for "impossible" is high. "Inconvenient" is not impossible.

## Self-Review Checklist

Before saving the plan, verify:

- [ ] Every file the implementation touches appears in exactly one task (or Task 0).
- [ ] No file in the parallel batch is read or written by another parallel task.
- [ ] Test files are paired with their implementation files in the same task.
- [ ] Shared types/migrations/configs/barrels are in Task 0.
- [ ] Task 0 (if present) is marked "Serial pre-phase — must complete before parallel batch."
- [ ] The Partition Map ends with "No file appears in two rows. ✅"

If any item fails → fix before handing off to Phase 3.

## Anti-Patterns

- **"It's just one shared file, the agents won't race."** They will. Add it to Task 0.
- **Partitioning by layer (backend/frontend/tests) instead of slice.** Tests always cross layers; this guarantees overlap.
- **Using "TBD" for the file list of any task.** Without exact files, you can't verify partition. Resolve before saving.
- **Marking the Partition Map ✅ when files actually overlap.** Compound V reviewers check this; lying here defeats the whole point.

## Handoff to Phase 3

When the Partition Map is complete and verified, announce:

> "Plan complete with verified Partition Map: 1 serial pre-phase task, N parallel-safe tasks. Proceeding to Phase 3 parallel Opus dispatch."

Then invoke the execution phase using `phase-3-parallel-opus-dispatch.md`.
