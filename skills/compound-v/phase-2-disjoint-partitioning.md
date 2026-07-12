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

## Emit the Execution Manifest (after the Partition Map)

The Partition Map proves the file sets are disjoint. That is necessary but not sufficient for the orchestrator: Phase 3 dispatches each task to a **backend** (Claude subagent, headless Codex worker, …) on a chosen **model**, with a chosen **isolation** (direct vs worktree). Those decisions are not free-form — they come from the Routing Policy. Phase 2 therefore emits a machine-readable **execution manifest** in addition to the prose, so the dispatcher has an unambiguous contract instead of re-deriving routing from prose.

> Phase 2 now produces **two** artifacts: the human Partition Map (above) and `manifest.yaml` (this section). The map is for reviewers; the manifest is for the dispatcher. They must agree — every parallel task in the map is exactly one `jobs[]` entry in the manifest, with the identical `write_allowed`.

### Where it goes

```
docs/superpowers/execution/<run-id>/manifest.yaml
```

One manifest per run. The full schema, every field, and the worked example live in [`execution-manifest.md`](execution-manifest.md) — that doc is the spec; this section is the **how-to-build-it from a verified partition**. Mirror [`examples/manifest.example.yaml`](../../examples/manifest.example.yaml) for layout.

### How to build it from the verified partition

1. **Top-level fields.** Fill `run_id` (convention `YYYY-MM-DD-<slug>`), `feature`, `spec_path`, `plan_path`, the three `audits` paths (archaeology / domain / library), `routing_stance` (read from `.claude/compound-v.json`; default `balanced`, `claude-only` when no Codex), and `max_parallel` (the Phase 3 4–6 ceiling — see below).
2. **Carry the feature-level `acceptance_criteria`** straight from the spec's Acceptance Criteria. These are **feature-level** and gate the *final integration review* — not any single task. Do **not** synthesize them; copy the spec's AC verbatim. (Each job *also* gets its own narrow `acceptance`; do not confuse the two — see `execution-manifest.md`.)
3. **One `jobs[]` entry per partition row** (Task 0 + every parallel task). For each, set:
   - `id` (the task id), `title`, and a `type` token the Routing Policy understands (`shared_foundation`, `core_slice`, `bounded_crud`, `large_isolated`, `mechanical_refactor`, `docs`, `tests_new`, `external_api`, `review`).
   - `write_allowed` = **exactly** that row's exclusive file set from the Partition Map (the disjointness you just verified is what makes the manifest valid).
   - `read_allowed` = the row's extra reads. Task 0 outputs and the three audits are **auto-included** — do not list them.
   - `acceptance` = that task's narrow per-task acceptance.
   - `depends_on` = predecessor job ids (every parallel task `depends_on` Task 0; later batches `depends_on` the earlier-batch authors whose files they link to).
   - `run` = `serial` for Task 0, `parallel` for the batch.
4. **Route each job** — backend · model · isolation come from [`routing-policy.md`](routing-policy.md), applied to the job's `type` under the active stance. Do **not** hand-pick them per job; let the policy decide and record what it returns. The policy also consults [`routing-lessons.md`](../../docs/superpowers/memory/routing-lessons.md), so a recorded lesson can override the table default.
5. **Preserve the two structural rules** the partition already guarantees, now as manifest invariants:
   - **Disjoint writes** — no path appears in two jobs' `write_allowed`. (This is the Partition Map's "No file appears in two rows ✅," restated for the validator.)
   - **Shared resources → serial Task 0** — the `shared_foundation` job is `run: serial`, `isolation: direct`, and every other job `depends_on` it. No sibling races it.

### Routing-derived invariants (do not violate when writing the manifest)

These come from `routing-policy.md` / `execution-manifest.md` and are enforced deterministically by [`scripts/compound-v-validate-manifest.py`](../../scripts/compound-v-validate-manifest.py):

- **Codex ⇒ worktree.** Any `backend: codex` job MUST be `isolation: worktree` (Codex's sandbox restricts writes to a *directory*, so worktree + `git diff` is the only file-scope enforcement).
- **Reviewers ⇒ opus.** Any `review` job is `model: opus`.
- **Unclear scope ⇒ return to planning** — never emit a job whose file set you cannot pin. Go back and partition it; do not ship a guessed `write_allowed`.

> `backend` and `model` are **execution-layer data**. They live only in the manifest — they MUST NOT appear in any agent / skill / command frontmatter. Never write `model: haiku` anywhere.

### Validate before handing off

Run the deterministic validator against the materialized manifest. **Select the mode by manifest kind (CR5-1):** the manifest this phase emits from a plan carries **no** `fast_path` block, so it is validated **mode-lessly** (legacy), as shown. A `fast_path` manifest — the v2.9 pre-eval-backed single-job kind, materialized by [`compound-v-fastpath-materialize.py`](../../scripts/compound-v-fastpath-materialize.py), not by this phase — MUST instead be validated with `--mode pre-dispatch`; a mode-less `fast_path` manifest is fail-closed rejected:

```bash
# plan-based (legacy) manifest — what this phase emits:
python3 scripts/compound-v-validate-manifest.py docs/superpowers/execution/<run-id>/manifest.yaml
# fast_path manifest (produced by the pre-eval materializer, shown here for completeness):
python3 scripts/compound-v-validate-manifest.py docs/superpowers/execution/<run-id>/manifest.yaml \
  --mode pre-dispatch --repo-root <repo>
```

A non-zero exit (disjointness, codex⇒worktree, or reviewers⇒opus violation) means the manifest contradicts the partition — fix it before Phase 3. This is the same gate [`partition-reviewer`](../../agents/partition-reviewer.md) runs.

## Manifest Self-Review Checklist

In addition to the partition checklist above, before saving the manifest verify:

- [ ] Every parallel-task row in the Partition Map has exactly one `jobs[]` entry with the identical `write_allowed`.
- [ ] Feature-level `acceptance_criteria` were copied verbatim from the spec (not invented).
- [ ] Each job's `backend`/`model`/`isolation` came from `routing-policy.md`, not hand-picked.
- [ ] No `backend: codex` job is `isolation: direct`.
- [ ] No `review` job is anything but `model: opus`.
- [ ] No path appears in two jobs' `write_allowed`.
- [ ] `compound-v-validate-manifest.py` exits 0 (mode-less — a plan-based manifest carries no `fast_path` block).

## Handoff to Phase 3

When the Partition Map **and** the manifest are complete and validated, announce:

> "Plan complete with verified Partition Map and validated `manifest.yaml`: 1 serial Task 0, N parallel-safe jobs, routed per the active stance. Proceeding to Phase 3 manifest-driven dispatch."

Then invoke the execution phase using [`phase-3-parallel-opus-dispatch.md`](phase-3-parallel-opus-dispatch.md), which reads the manifest and dispatches each job to its backend via [`backend-launcher`](../backend-launcher/SKILL.md).
