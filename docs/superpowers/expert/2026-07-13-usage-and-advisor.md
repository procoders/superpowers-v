# Domain note — v2.12 usage & advisor (2026-07-13)

## anti-ruflo (the domain constraint that governs Feature A)

Compound V's product promise includes "no made-up cost numbers." The usage feature must record ONLY
real measured usage. Concretely:
- A backend that exposes token counts (codex, opencode, cursor, claude `-p` shell-out) => `measured:true`
  with the real numbers.
- A backend that does not (agy, claude-via-Task, devin) => `measured:false` with NULL tokens — never a
  guess, never a zero-that-reads-as-real. The aggregator reports "N unmeasured" honestly rather than
  implying a total is complete.
- `/v:status` must show measured totals + the unmeasured count; the existing line that bans token metrics
  is reworded to ban ESTIMATES, not measurements.

## Advisor pattern (the domain shape chosen)

The "cheap executor consults a stronger model on hard sub-decisions" pattern is real (Anthropic ships it
as the `advisor_20260301` API tool). For a Claude Code plugin that shells nothing external and holds no
API key, the faithful realization is a **harness subagent pattern**, enhanced with Compound V's own
cross-model ethos:
- Executor = Sonnet. On a hard sub-decision it consults an advisor of a DIFFERENT brand when available
  (Codex `exec --sandbox read-only`), because a family-diverse second opinion catches blind spots the
  same family shares — the same reason Compound V already runs cross-model (Codex) review. Fall back to
  Opus when no cross-brand backend is installed.
- The advisor is READ-ONLY: it advises, it never writes files or runs destructive bash. This is both a
  domain-correct separation (advice vs action) AND the structural fix for the 2026-07-13 incident (a
  writing nested bypass agent deleted the repo). A no-write advisor cannot repeat it.
