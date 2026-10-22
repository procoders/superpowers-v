# Dogfood: 2026-09-02-df2-frontier — frontier tier

Run `2026-09-02-df2-frontier`, job `tier-frontier`. This file is the deliverable
of the frontier-tier seat in wave 1: its existence proves the frontier tier
routed to a live agent, dispatched into an isolated worktree, and produced a
write inside its declared lane.

- Lane registered before any other tool call; baseline pinned at
  `09195341ea96461fd9b62e008f0e4855031cd3ea`.
- Worktree: `.claude/worktrees/wf_a6f68c23-01d-1`.
- Write-allowed: this file only.

Enforcement fields (`blocked`, `files_changed`, `violations`) are deliberately
absent here — they are git-derived by the caller's scope gate, never
self-reported by the constrained party.
