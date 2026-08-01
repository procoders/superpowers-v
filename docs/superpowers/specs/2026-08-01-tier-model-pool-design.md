# Tier model pools — spread a tier's jobs across several providers (PR 2 of 3)

**Goal:** let one tier name **several** (backend, model) pairs instead of one, and have the
dispatcher hand successive jobs to them in turn, so a run burns three providers' quotas evenly
instead of exhausting one. The operator's stated aim, verbatim: *"ровнее жечь квоты в трёх
провайдерах"*.

**Architecture:** a new `pools` section in the project config, a resolver entry point that
returns the *n*-th member of a pool, an assignment recorded in `state.json` at first dispatch,
and a resume path that reads the recorded assignment rather than re-deriving it. Enforcement,
the manifest schema and every worker stay untouched.

**Tech stack:** Python 3.9-safe stdlib. No new dependency, no new file format.

**Independent of PR 1.** This feature is useful with only `claude` and `codex` installed; `zai`
simply becomes an eligible pool member once [the zai backend](2026-07-31-zai-backend-design.md)
lands. Nothing here depends on that PR.

## The problem this solves

Today `models.<stance>.<backend>.<tier>` holds exactly one model per cell, and a job's
`backend` is fixed in the manifest at planning time. A run that partitions into eight `light`
jobs sends all eight to whichever backend the planner wrote down. On a metered subscription that
is the whole quota of one provider while two others sit idle.

## What changes

### 1. Config: a pool is a list, keyed by tier, spanning backends

Pools live beside `models`, not inside it, because a pool crosses backends and the existing map
is backend-keyed:

```jsonc
{
  "models": { /* unchanged; still the single-cell fallback */ },
  "pools": {
    "balanced": {
      "light": [
        { "backend": "claude", "model": "sonnet" },
        { "backend": "codex",  "model": "gpt-5.6-luna" },
        { "backend": "zai",    "model": "glm-5-turbo" }
      ]
    }
  }
}
```

Per-stance, exactly like `models`. A tier with no pool entry behaves exactly as today — this is
purely additive, and a config written before this change keeps working unchanged.

**Pool members inherit the map's rules, and add none.** Whatever a `models` cell accepts today, a
pool entry accepts. This PR deliberately takes no position on the never-Haiku gap in config
cells (see Non-goals) — it neither closes it nor depends on it.

### 2. A job opts in

A job asks for pool routing by naming the pool instead of a backend:

```yaml
  - id: task-3-docs
    backend: pool          # instead of claude | codex | zai | …
    tier: light
    isolation: worktree
```

`backend: pool` is a new enum value in the manifest validator. It is a *routing instruction*,
not a backend — no adapter is named `pool`, and the dispatcher resolves it to a real backend
before any worker is launched.

### 3. Assignment: round-robin at first dispatch, then frozen

The dispatcher keeps a per-run counter per tier. The *n*-th pool-routed job of a tier goes to
member `n mod len(pool)`, in dispatch order.

**The assignment is written into `state.json` the moment it is made:**

```jsonc
"jobs": {
  "task-3-docs": {
    "status": "dispatched",
    "assigned_backend": "codex",
    "assigned_model": "gpt-5.6-luna",
    "isolation": "worktree",
    "worktree": "/tmp/compound-v/…"
  }
}
```

`state.json` already carries `isolation` per job, so per-job routing state is an established
shape, not a new concept.

**`/v:resume` reads the recorded assignment and does not re-derive it.** Re-running the counter
after an interruption would hand the same job to a different backend with different isolation
and a different worktree — the run would no longer be reproducible. One exception: when the job
failed with a quota or rate-limit class, the recorded assignment is cleared and the existing
failure policy picks the next backend. That is the one case where moving the job is the point.

### 4. Isolation is forced to `worktree` for every pool-routed job

A pool spans backends whose isolation rules differ: `claude` may write directly against a
baseline commit, while `codex`, `cursor`, `antigravity`, `devin`, `opencode` and `zai` must run
in a worktree. If the assignment were allowed to change isolation, a job's enforcement shape
would depend on a counter.

So: **`backend: pool` requires `isolation: worktree`**, rejected by the validator otherwise. The
cost is a worktree for claude jobs that would not have needed one; the benefit is that every
member of a pool is enforced identically, and a resumed job keeps the isolation it started with.

### 5. Concurrency is capped per backend, not just per run

`max_parallel` is a run-level number today. A pool concentrates load differently: three
concurrent jobs may all land on the same member. Backends with their own ceiling — `zai` defaults
to 4, per its adapter — need that respected.

Add an optional `backend_max_parallel` map to the config (`{"zai": 4}`), consulted by the
dispatcher when it fills a batch. Absent entry ⇒ only the run-level `max_parallel` applies, so
existing behaviour is unchanged.

## What does not change

- `job_result`, every adapter and every worker script. A worker never learns it was pool-routed.
- The scope gate, the review gate, the reviewer invariant. **Reviewers are never pool-routed** —
  `backend: pool` on a reviewer job is rejected, because a reviewer must resolve to `deep`/opus
  deterministically, and a pool cannot promise that.
- The per-stance `models` map, which stays the fallback for every non-pool job.

## Risks and how each is handled

**A pool member is unavailable.** The dispatcher already knows which backends are available
(env-aware routing, `/v:init`). Unavailable members are filtered out of the pool *before* the
counter is applied, so an absent `zai` key means a two-member pool, not every third job failing.
If filtering empties the pool, the job falls back to the `models` cell for its tier and the run
logs that it did.

**A pool hides an unbalanced burn.** Round-robin balances *job counts*, not tokens; a pool member
that gets three cheap jobs while another gets three expensive ones is not actually balanced. This
PR does not attempt token-aware balancing — it would need per-backend quota introspection that
z.ai, for one, does not expose. The honest scope is round-robin, and the docs must say so rather
than implying quota-awareness.

**A stale assignment after a config change.** If the pool is edited between a run and its resume,
a recorded `assigned_backend` may no longer be in the pool. The recorded assignment still wins —
it is what the worktree and the partial work belong to — and the reconciliation logs the drift.

## Non-goals

- **No token- or quota-aware balancing** (see above).
- **No time-of-day routing** to exploit z.ai's promotional off-peak window.
- **No change to the never-Haiku policy** in either direction. Pool entries inherit the config
  map's rules exactly.
- **No pooling for `deep`.** Nothing forbids it mechanically, but `deep` carries the reviewer and
  sensitive-surface work, and spreading that across providers is a separate decision with a
  different risk profile. This PR ships `standard` and `light`.
- **No change to `job_result` or any adapter.**

## Acceptance criteria

1. A config with no `pools` key behaves exactly as before — every existing selftest passes
   unchanged.
2. `backend: pool` + `isolation: worktree` + a tier with a pool validates; `backend: pool` with
   `isolation: direct` fails with a message naming the rule.
3. A reviewer job with `backend: pool` fails validation.
4. Six pool-routed `light` jobs across a three-member pool produce the assignment sequence
   member 0, 1, 2, 0, 1, 2 — asserted deterministically, with no randomness anywhere.
5. An unavailable member is filtered before the counter: with `zai` absent, a three-member pool
   alternates between the remaining two and never assigns `zai`.
6. An empty filtered pool falls back to the `models` cell for that tier, and the fallback is
   logged.
7. Every assignment is recorded in `state.json` as `assigned_backend` / `assigned_model`.
8. `/v:resume` re-dispatches a pool-routed job to its **recorded** backend, not to whatever the
   counter would now produce — asserted by resuming a run whose counter state was lost.
9. A job that failed with `rate_limited` or `out_of_credits` has its assignment cleared on
   resume, and the failure policy chooses the next backend.
10. `backend_max_parallel` caps concurrent jobs per backend; absent entry leaves run-level
    `max_parallel` as the only limit.
