# Tier model pools — spread a tier's jobs across providers (PR 2 of 3)

**Goal:** let one tier name **several backends** instead of one, and hand successive jobs to
them in turn, so a run draws on more than one provider's quota instead of draining a single one.

**Architecture:** a new `pools` block in the project config; a pure resolver entry point that
takes the member index as a parameter; an assignment computed from manifest job order, frozen
into `state.json` at first dispatch, and honoured verbatim by `/v:resume`. Enforcement, the
`job_result` contract and every worker stay untouched.

**Tech stack:** Python 3.9-safe stdlib. No new dependency, no new file format, no new CLI.

**PR 1 is a declared merge prerequisite.** The *code* here is independent — the resolver, the
validator and the assignment logic are exercised by fixtures and need no real backend. But every
shipped example needs `zai`, and with `claude` excluded from pools by default (§2) a pool without
it degenerates to a single member. So this PR does not merge before the zai backend does. That
backend lives on branch feat/zai-backend and is deliberately not linked here: the repo's
dead-link gate is line-based and does not respect inline code spans, so a quoted path fails CI
on a branch cut from `main`.

> **Revision note.** Rewritten 2026-08-01 after three pre-flights
> (`docs/superpowers/archaeology/2026-08-01-tier-model-pool.md`,
> `docs/superpowers/expert/2026-08-01-tier-model-pool.md`,
> `docs/superpowers/library-audit/2026-08-01-tier-model-pool.md`) found four blocking defects in
> the first draft, including a factual claim that was exactly inverted and a policy regression
> the draft's own Non-goals promised not to introduce.

## What this does and does not claim

It hands jobs to backends in a fixed, weighted rotation. That balances **job counts**, not
tokens, credits or messages — and the three providers do not even meter in the same unit
(Anthropic and OpenAI count against rolling message windows; z.ai counts credits derived from
tokens with per-model multipliers that **double during peak hours**, Mon–Fri 14:00–18:00
UTC+8). The same manifest run at 15:00 and at 20:00 consumes a different share of z.ai.

So this document does not claim the feature "burns quotas evenly" — that would be an unmeasured
assertion, and the repo's anti-ruflo rule forbids exactly that. It claims only what it does:
**a deterministic rotation that stops one provider absorbing an entire run.**

Weighted rotation is what comparable routers actually ship — LiteLLM shuffles by rpm/tpm
weights, OpenRouter weights by inverse square of price, Portkey requires explicit normalised
weights. Even a proxy that advertises itself as round-robin across several Claude Max
subscriptions does least-loaded with cooldown underneath. Bare rotation is the simple end of
that spectrum; weights are what keep it from being the naive end.

**Why not quota-aware routing.** Not because the numbers are unavailable — that was the first
draft's claim and it was inverted. z.ai is the *most* measurable of the three (published credit
formula, published per-model multipliers, plus an undocumented usage endpoint); Anthropic and
OpenAI both publish rate-limit headers. The real reason is architectural: **Compound V never
speaks HTTP to a provider.** It spawns CLI processes and reads stdout, stderr and exit codes, so
no provider header ever reaches the dispatcher. The repo already demonstrates this —
`compound-v-classify-failure.py` distinguishes a rate limit from exhausted credits by matching
*stderr text*, and nothing under `scripts/` parses a header. Quota-aware routing would need a
transport this plugin does not have.

And the one backend that is genuinely blind is `claude`, by this repo's own reckoning: it sits
in `UNMEASURED_BACKENDS` in `scripts/compound-v-usage-extract.py`, alongside `agy` and `devin`.

## The design

### 1. Config: `pools`, keyed by tier, spanning backends

```jsonc
{
  "models": { /* unchanged — still the single-cell resolution for every non-pool job */ },
  "pools": {
    "balanced": {
      "light":    [ { "backend": "codex" }, { "backend": "zai" } ],
      "standard": [ { "backend": "codex", "weight": 2 }, { "backend": "zai" } ]
    }
  },
  "backend_max_parallel": { "zai": 4 }
}
```

Per-stance, like `models`. A tier with no pool entry behaves exactly as today; a config written
before this change keeps working untouched.

**A member names a backend, not a model.** `model` is an **optional** override. Requiring it
would re-create the rot the tier map exists to prevent — `execution-manifest.md` states that the
map is what lets the plugin survive model churn, and `/v:models` refreshes `models`, not
manifests. A pool is already keyed by tier, so the existing resolver derives the model from
`(backend, tier, stance)`.

**`weight` is an optional positive integer from 1 through 100, default 1.** Expansion is
deterministic: a member of weight *n* occupies *n* consecutive slots in the expanded ring. One
tier's expanded ring is capped at 256 slots. Both limits are fail-closed memory-safety bounds: the
resolver materializes positional slots, so accepting an arbitrary JSON integer would turn config
parsing into a deterministic memory-exhaustion path. With every weight at 1 the sequence is plain
rotation, so the simple case is unchanged and no randomness enters anywhere. Shipping weights now
avoids a schema break later, and they are the only way to express the `claude` case below.

**Config-reader conventions this must follow** (all three were missed in the first draft):
`load_project_config` type-checks every known top-level key and raises on a bad value, so
`pools` and `backend_max_parallel` must join that check — a malformed routing key must fail
closed, never fail open. Every config block has a `resolve_<block>() -> (values, warnings)`
reader; `pools` needs one, and a list-of-objects is a shape no existing reader has handled.

### 2. `claude` is excluded from pools by default

Anthropic states that usage limits are **shared between Claude and Claude Code**. A `Task`
subagent draws on the same rolling window as the operator's own interactive session — the very
session driving the run. The other members are separate processes on separate subscriptions and
do not compete with the operator at all.

A pool that included `claude` by default would therefore spend the operator's own capacity to
save metered capacity they were not short of. Adding `claude` is an explicit, deliberate act,
and `weight` exists so it can be added at a reduced share rather than an equal one.

This also removes a second-order cost the first draft introduced: forcing `worktree` on every
pool job (§4) makes `claude` jobs — which may otherwise run `direct` — more expensive on exactly
the scarcest quota.

### 3. Assignment: computed from manifest order, frozen at first dispatch

The index is **the job's ordinal among pool-routed jobs of that tier in the manifest**, not the
order the dispatcher happened to launch them. Dispatch order varies with `depends_on`, batching
and retries; manifest order does not, so the assignment is reproducible from the manifest alone.

`resolve()` stays **pure**, and the counter does not live in it: every production caller is a
fresh subprocess, so an in-resolver counter would reset on every call and return member 0
forever. The resolver gains `resolve_pool(tier, index, stance, config) -> {backend, model}`,
taking the index as a parameter. (`itertools.cycle` is 3.9-safe but wrong here: an iterator
exposes no readable index, and the index is precisely what must be frozen.)

The **member list is frozen into `state.json` at run start**, so a config edit mid-run cannot
shift the sequence. An unavailable member is **skipped, and the counter still advances** —
rebuilding a shorter pool would change its length and move every later assignment.

```jsonc
"pool_members": { "light": [ {"backend":"codex"}, {"backend":"zai"} ] },
"jobs": {
  "task-3-docs": {
    "status": "dispatched",
    "assigned_backend": "codex",
    "assigned_model": "gpt-5.6-luna",
    "isolation": "worktree"
  }
}
```

**Availability has no mechanism today**, and the first draft wrongly assumed one. The config's
`backends`/`checked_at` fields were removed in v2.6.2; availability now lives in an uncommitted
capabilities file whose only machine-readable consumers are two predicates — one for codex, one
for agy. Nothing exists for cursor, devin, opencode or zai. This PR therefore defines
availability for pool members explicitly and narrowly: a member is available when its backend's
documented precondition holds (for `zai`, `ZAI_API_KEY` is set; for `codex`, the binary is on
`PATH`), evaluated once at run start and frozen with the member list.

`state.json` has **no schema and no validator** today, and real runs carry three different
per-job shapes. Since `assigned_backend` is load-bearing for resume and for the circuit breaker,
this PR adds a narrow validator for the fields it introduces rather than trusting the shape.

**`/v:resume` honours the recorded assignment** and never re-derives it: a resumed job belongs to
a specific worktree and a specific partial diff. The one exception is a job that failed on a
quota class — there, moving it is the point (§5).

### 4. `backend: pool` — a routing instruction, not a backend

A job opts in with `backend: pool` + `tier` + `isolation: worktree`. `pool` is resolved to a
real backend **before** any worker launches, so no adapter, worker, `FALLBACK` entry or
failure-classifier branch ever sees the string `pool`.

That is exactly why every backend-keyed site must be audited rather than assumed. The first
draft would have broken all of these:

- **The worktree invariant** does not include `pool`, so `backend: pool` + `isolation: direct`
  passes today. `pool` must require `worktree` — a pool spans backends whose isolation rules
  differ, and an assignment must never change a job's enforcement shape.
- **The reviewer prohibition** keys on the backend string, so a reviewer routed to `pool` slips
  past it *while the deep/opus check still passes* — the manifest looks compliant. `backend:
  pool` must be rejected on any reviewer job.
- **The never-Haiku execution-layer gate** fires on a job's explicit `model`. A pool job has
  none, so the gate becomes unreachable — a policy regression the first draft's own Non-goals
  promised not to introduce. The check must therefore run on the **resolved** model.
- **`VALID_BACKENDS`** is consumed at three sites, one of them `advisor_backend`. Adding `pool`
  there would make it a legal advisor backend, which `select_advisor` has no path for. The enum
  value must be scoped to `job.backend` only.
- **`FALLBACK.get("pool")`** would return `None` and halt the run; **the classifier's argparse**
  would exit 2. Neither can happen once resolution precedes dispatch — but both must be asserted
  by a test, not assumed.

### 5. Failure interaction — corrected

The first draft asserted that a quota failure moves a job to the next pool member. It does not,
and the existing behaviour is worse than that under a pool:

- `rate_limited` **retries on the same backend** with backoff (cap 3). It never reroutes.
- `out_of_credits` reroutes to `FALLBACK[backend]`, which is **always `claude`** — so the first
  exhausted codex quota would dump the remainder of the run onto the operator's own
  subscription, the precise outcome §2 exists to avoid.

For a pool-routed job, `out_of_credits` must reroute to the **next available pool member**,
falling back to the existing chain only when the pool is exhausted. And because `attempts` are
tracked per failure-class and **reset on a reroute**, a 3-retry cap silently becomes 9 across a
three-member pool against a 12-retry run budget: the run-level budget must be decremented across
reroutes, not just the per-class counter.

### 6. Concurrency

`max_parallel` is presence- and integer-checked only; batching itself is a prose instruction to
the dispatcher, not code. `backend_max_parallel` is therefore documented and **validator-checked
for shape**, and the dispatcher prose is extended to respect it. This PR does not pretend to add
an enforcement gate where none exists, and the acceptance criteria below do not claim one.

## Non-goals

- **No quota- or token-aware balancing** — Compound V has no HTTP transport to a provider.
- **No time-of-day routing** around z.ai's peak multiplier, though it is real and documented.
- **No change to the never-Haiku policy.** The resolved-model check in §4 exists to *preserve*
  the current gate under pool routing, not to extend it. The pre-existing gap in config map
  cells is untouched.
- **No pooling for `deep`.** It carries reviewers and sensitive surfaces; spreading those is a
  separate decision with a different risk profile. This PR ships `standard` and `light`.
- **No change to `job_result`, any adapter, or any worker.**

## Acceptance criteria

1. A config with no `pools` key behaves exactly as before; every existing selftest passes
   unchanged.
2. `backend: pool` + `isolation: worktree` + a tier with a pool validates. The same job with
   `isolation: direct` fails with a message naming the rule.
3. A reviewer job with `backend: pool` fails validation.
4. `pool` is rejected as an `advisor.advisor_backend` value while remaining valid as
   `job.backend`.
5. A pool job whose **resolved** model contains `haiku` fails validation — the gate that the
   absence of an explicit `model` would otherwise make unreachable.
6. Six pool-routed `light` jobs over a two-member pool with weights 2 and 1 assign in the exact
   sequence A, A, B, A, A, B — computed from manifest order, with no randomness.
7. With one member unavailable, the counter still advances: the sequence skips that member and
   the remaining assignments keep the positions they would otherwise have had.
8. The frozen member list is written to `state.json` at run start, and editing `pools` mid-run
   does not change any later assignment.
9. Every assignment is recorded as `assigned_backend` / `assigned_model`, and the new validator
   rejects a `state.json` where a dispatched pool job lacks them.
10. `/v:resume` re-dispatches a pool job to its **recorded** backend even when the counter state
    is gone.
11. An `out_of_credits` failure on a pool job reroutes to the **next pool member**, not to
    `claude`; the run-level retry budget is decremented across the reroute.
12. `backend_max_parallel` is shape-validated and documented. No claim is made that a gate
    enforces it.
