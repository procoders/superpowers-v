# Workflows Accelerator — opt-in Engine C (kept in 1.0)

> *"A faster engine when the road allows it — but the brakes and the seatbelt stay bolted to the chassis you trust."*

**Status: kept in 1.0, opt-in, default OFF.** This is the **Engine C** fast-path for
large parallel batches. It is **never** the floor and **never** the resume mechanism.
Engine A (agent + helper scripts, batched `Task` dispatch) is the floor that works for
every user; Engine C is a capability-gated accelerator that **always falls back to A**.

See the engine decision in PRD §3.1 and the architecture in §5.13. Engine B
(`claude -p` shell-out) is **rejected** and not implemented.

---

## When it engages

All three must hold, or Engine A runs instead:

1. The user **opted in** (recorded in `.claude/compound-v.json`, e.g. a
   `workflows_accelerator: true` flag set at `/v:init` — default absent/false).
2. The **capability probe passes** (Dynamic Workflows are actually available in this
   harness — they are not exposed in a plain subagent shell, so the probe is real).
3. The batch is **large enough to be worth it** (many parallel jobs that would
   otherwise queue under Engine A's 4–6 ceiling). For a small batch, A is already fine.

If any fails: **silently fall back to Engine A.** No error, no halt — the run proceeds
on the floor engine exactly as if C did not exist.

---

## The probe → run → fallback flow

```
opted-in?  ──no──► Engine A (batched Task, 4–6 fg)
   │yes
   ▼
capability-probe Dynamic Workflows
   │
   ├─ unavailable / errors ──► Engine A          (automatic fallback)
   │
   └─ available
        ▼
   emit a Workflow running the SAME partitioned jobs,
   schema-validated job_results, at the 16-wide cap
        │
        ├─ Workflow errors / disabled mid-run ──► Engine A   (automatic fallback)
        │
        └─ Workflow completes ──► results flow into the SAME collect + scope-gate
```

**Capability-probe → 16-wide Workflow → automatic fallback to Engine A.** The probe is
attempt-and-catch: try to use the capability, and on *any* failure (absent, disabled,
mid-run error) drop to Engine A. There is no separate "is it installed" oracle to
trust — the fallback is the safety net.

---

## What STAYS in Engine A — even when C runs

This is the load-bearing guarantee. Engine C only changes **how jobs fan out**, never
the enforcement or recovery layer:

- **The scope gate stays in Engine A.** Every job's `files_changed` is checked against
  `write_allowed` by [`compound-v-scope-check.py`](../../scripts/compound-v-scope-check.py)
  in A's layer, regardless of which engine dispatched the job. File-scope enforcement
  never regresses to C's weaker guarantees.
- **`state.json` resume stays in Engine A.** Workflows' resume is *same-session-only*
  and "starts fresh" after a Claude Code exit — it fails the crash case by design
  (PRD §3.1). So crash-resume lives entirely in A's
  [`state-machine.md`](state-machine.md) layer. Even when C ran the dispatch, the run
  is resumable because A owns the state.

So C is a throughput optimization sandwiched **inside** A's enforcement and recovery:
A partitions and writes state → (optionally) C fans out wide → A's scope gate checks
every result → A's state machine records and resumes. The seatbelt and brakes are
always A's.

---

## Why opt-in and not default

- Engine C is **harness-gated** (Claude Code only, Pro-excluded) — defaulting it on
  would break for most users.
- Its resume is unsafe for the crash case, so it can never own recovery.
- The anti-ruflo charter favors the small, predictable, portable floor. C is power the
  user explicitly asks for, behind a probe and a guaranteed fallback — not a default
  that quietly changes the run's guarantees.

To turn it on: `/v:init` offers it when Dynamic Workflows are detected; otherwise it
stays off and the pipeline runs on Engine A.
