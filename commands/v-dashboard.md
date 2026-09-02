---
description: Emit the Compound V observability dashboard — a present-only, read-only static HTML snapshot over docs/superpowers/execution/** (runs, epics, per-job status, scope-gate verdicts, blocker ledger). For a LIVE view of a running dispatch, use the native `/workflows` and `/tasks` surfaces instead.
---

You are emitting the **Compound V observability dashboard**. It is **read-only and present-only**: it renders the
state that already exists under `docs/superpowers/execution/**` (runs, epics, jobs, scope-gate verdicts, usage,
blocker ledger). It never dispatches, collects, merges, kills, or mutates anything — control stays in the CLI
(`/v:dispatch`, `/v:resume`, `/v:epic`), which is the git-derived, human-gated moat. This is the same read-only
data [`/v:status`](v-status.md) prints as text, rendered as a shareable HTML page.

Args: `{{args}}` — optional `--out FILE` / `--execution-root DIR`.

Deterministic mechanics live in [`scripts/compound-v-dashboard.py`](../scripts/compound-v-dashboard.py); it is pure
stdlib, degrade-safe (renders what exists, honest "no runs/state yet"), and **anti-ruflo** — measured-only usage
(`—` when unmeasured), real counts (never a fabricated `%`), real timestamps only.

## For a LIVE view, use the native surfaces

This command emits a **static snapshot** only. Compound V no longer ships a bespoke local HTTP server for a live
view (removed in v3.4: native-first) — the harness already has one:

- **[`/workflows`](https://code.claude.com/docs/en/workflows)** shows a running Compound V dispatch's live progress
  as it executes.
- **`/tasks`** shows `state.json` / `epic-state.json` progress for runs and epics, live, without a snapshot step.

Reach for `emit` when you want a shareable, offline artifact (a link to paste, a point-in-time audit record) — not
as a substitute for watching a dispatch in progress.

## `emit` — self-contained static HTML snapshot

Data inlined, offline, theme-aware — good for sharing / audit — written to
`docs/superpowers/execution/dashboard.html` (git-ignored build artifact):

```
python3 scripts/compound-v-dashboard.py emit [--out docs/superpowers/execution/dashboard.html] [--execution-root docs/superpowers/execution]
```

Print the `file://…` path for the user to open.

## Honest boundary (state it)

Observation is read-only; **control is CLI-only** — there are deliberately no merge/kill/retry buttons anywhere,
because Compound V's guarantees are git-derived and human-gated, not dashboard-driven. A snapshot is a point-in-time
artifact, not a live connection — for progress as it happens, point the user at `/workflows` or `/tasks` instead of
re-emitting on a loop.
