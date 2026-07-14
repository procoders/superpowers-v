---
description: Open the Compound V observability dashboard — a present-only, read-only browser view over docs/superpowers/execution/** (runs, epics, per-job status, scope-gate verdicts, blocker ledger). `emit` writes a static self-contained HTML snapshot; `serve` runs an ephemeral, localhost-only, read-only live viewer. Observe in the browser; control stays in the CLI.
---

You are opening the **Compound V observability dashboard**. It is **read-only and present-only**: it renders the
state that already exists under `docs/superpowers/execution/**` (runs, epics, jobs, scope-gate verdicts, usage,
blocker ledger). It never dispatches, collects, merges, kills, or mutates anything — control stays in the CLI
(`/v:dispatch`, `/v:resume`, `/v:epic`), which is the git-derived, human-gated moat. This is the same read-only
data [`/v:status`](v-status.md) prints as text, rendered as a browser UI.

Args: `{{args}}` — `serve` (live) or `emit` (static snapshot); default `emit`. Optional `--port N` (serve) / `--out FILE` (emit).

Deterministic mechanics live in [`scripts/compound-v-dashboard.py`](../scripts/compound-v-dashboard.py); it is pure
stdlib, degrade-safe (renders what exists, honest "no runs/state yet"), and **anti-ruflo** — measured-only usage
(`—` when unmeasured), real counts (never a fabricated `%`), real timestamps only.

## Branch on `{{args}}`

- **`serve`** (or `--serve`) → an **ephemeral, read-only, `127.0.0.1`-only** live viewer that auto-refreshes as a
  run/epic progresses — the local equivalent of a competitor's live agent UI, minus the control surface:
  ```
  python3 scripts/compound-v-dashboard.py serve [--port 8787] [--execution-root docs/superpowers/execution]
  ```
  It binds `127.0.0.1` only (never `0.0.0.0`), serves **GET/HEAD only**, is realpath-contained to the execution
  root, and runs in the **foreground** until you Ctrl-C — it never backgrounds, never auto-launches, and writes
  nothing to any run dir. Print the `http://127.0.0.1:<port>/` URL for the user to open, and remind them it stops
  on Ctrl-C.

- **`emit`** (default, or `--html`) → a **self-contained static HTML snapshot** (data inlined, offline, theme-aware —
  good for sharing / audit), written to `docs/superpowers/execution/dashboard.html` (git-ignored build artifact):
  ```
  python3 scripts/compound-v-dashboard.py emit [--out docs/superpowers/execution/dashboard.html] [--execution-root docs/superpowers/execution]
  ```
  Print the `file://…` path for the user to open.

## Honest boundary (state it)

Observation is in the browser; **control is CLI-only** — there are deliberately no merge/kill/retry buttons, because
Compound V's guarantees are git-derived and human-gated, not dashboard-driven. `serve` is a process only while you
watch it (Ctrl-C ends it); it is not an always-on server and is never reachable off `localhost`.
