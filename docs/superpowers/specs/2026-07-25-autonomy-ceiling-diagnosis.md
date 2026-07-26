# Diagnosis: why Compound V never delivers an overnight run

Research pass, 2026-07-25. **Diagnosis only — nothing was built.** Every claim below was either
live-probed on this machine or carries a `file:line` citation. The four load-bearing claims were
re-verified independently by the orchestrator before this document was written.

## The headline, verified

**No epic has ever run in this repository.** `docs/superpowers/execution/epics/` does not exist.
`crontab -l` → *no crontab for oleg*. No Compound V LaunchAgent. No registered scheduled task.
All nine committed runs are single-session builds.

The marathon loop (v2.10), the two-tier auto-resurrection watcher (v2.11) and the headless shim
(v2.14) together are **~1,900 lines of shipped, self-tested, CI-green code that has never executed
against a real build.**

**And the maintainer already routed around it.** `~/.claude/scheduled-tasks/astrolium-autonomous-watchdog/`
is a hand-written 8-hour overnight watchdog built on 2026-07-13 for a *different* repo, on the **native**
scheduled-tasks mechanism, **bypassing Compound V entirely** — and it runs its codex worker under
`nohup`. When 8 hours were actually needed, the answer was one hand-written file somewhere else.

## What is broken (fixable in Compound V), ranked by cost

1. **Nothing is ever armed. Cost: ~100% of the target.** Marathon is opt-in, watch is opt-in, and the
   shim must be manually emitted, manually re-emitted with `--allow-build`, manually saved and manually
   bootstrapped — five steps, none ever taken here. Every other limiter is downstream of this one.

2. **We deleted the one primitive that keeps a turn alive, on a false premise.** `hooks/hooks.json:2`
   states `SubagentStop` "is not documented in official Claude Code hooks reference; removed v0.1.1
   after honesty audit." **The premise is factually wrong.** `Stop` and `SubagentStop` are documented,
   and a `Stop` hook returning `decision: "block"` prevents Claude from stopping and continues the
   conversation. **Decisive local proof:** Anthropic's own official `ralph-loop` plugin — present in
   this machine's plugin cache — is built on a `Stop` hook
   (`~/.claude/plugins/cache/claude-plugins-official/ralph-loop/1.0.0/hooks/hooks.json`). So is `/goal`.
   We removed it and then spent three versions building a scheduler-based substitute.

3. **The wall-clock breaker measures calendar time, not working time.**
   `scripts/compound-v-epic-state.py:1643` computes `elapsed_hours = now - started_at`, where
   `started_at` is stamped once at `--init` (`:566`). Default `max_wall_clock_hours = 10` (`:357`). An
   epic initialized at 2pm is **already over budget by midnight** — the breaker trips on the first
   overnight check, before any useful work.

4. **The watcher cannot achieve a useful duty cycle.** Death is invisible until `last_progress_at` is
   45 minutes stale (`:370`), and the poll runs ~30 minutes apart (`compound-v-epic-watch.py:80`) —
   **up to 75 minutes of dead air per resurrection.**

5. **We throttle the one backend that runs to completion, and never detach it.**
   `scripts/compound-v-run-codex-worker.sh:46` sets `DEFAULT_TIMEOUT_SEC=900`, and **all nine real runs
   used that default** (zero `timeout_sec` overrides across every manifest). The worker is Bash-spawned
   inside the Claude session (`agents/parallel-dispatcher.md:51`) with no `nohup`/`setsid`, so it dies
   with the session. This is precisely the difference between `codex exec` "working great" standalone
   and not working inside Compound V.

6. **Usage-limit handling is tuned for seconds, not hours.** `scripts/compound-v-failure-policy.py:49`
   caps `rate_limited` at 3 retries with a 60s backoff ceiling (`:63`); `out_of_credits`/`auth` are not
   retryable at all. Hit a rolling window at 1am and the run halts until a human wakes up. **There is no
   sleep-until-quota-resets path anywhere in the codebase.**

7. **OAuth expiry is never mentioned.** Unattended launchd/cron sessions die silently on an expired
   token; the documented fix mints a long-lived token. Repo-wide grep for `setup-token` /
   `CLAUDE_CODE_OAUTH_TOKEN` → **zero hits.**

8. **Background/long-running session modes are unused.** Compound V uses none of the harness features
   that survive terminal close and process restart.

9. **The marathon runbook lives in context, not on disk.** No re-injection after compaction, and the
   cycle counter is model-held scratch state (`commands/v-epic.md:138`) while `processed_cycle_ids` is
   persisted — so after a compaction the counter can restart, replay a processed id, and silently
   **under-count** `no_progress_cycles`, disabling that breaker.

## Harness limits we cannot fix

A turn is a turn — an interactive session ends and needs an external event. Tier-1 `CronCreate` is
session-scoped and **can never survive the death it exists to detect** (our own doc says so at
`epic-mode.md:216`). Tier-2 requires the desktop app open. **Nothing local runs while the machine
sleeps** — and a closed lid on Apple Silicon sleeps regardless. Rolling usage windows are structural.
A genuine machine-off 8 hours needs remote infrastructure, which `epic-mode.md:219` already states
correctly.

## What we must NOT "fix"

**Never emit the permission-bypass flag.** This repo's own history includes a live worker that deleted
an entire repository (2026-07-13); the industry has parallel incidents. The non-bypass unattended mode
is real, documented, works, and — unlike bypass — still denies writes to `.git`, `.claude` and shell
profiles. `scripts/compound-v-headless-shim.py:176-180` already bans the bypass flag and its selftest
asserts the absence. **Do not reverse it.** Likewise keep `--allow-build` opt-in (what is wrong is that
the *emit* is manual and unwired, not that the safe default is safe), and keep the scope gate,
cross-vendor arbiter, blocker bar and sample audits — those are the moat, and they are not what costs
us the hours.

## Theatre vs real

| Feature | Verdict |
|---|---|
| `state.json` / `epic-state.json` / git-wins resume | **REAL** — genuinely durable and compaction-survivable. The load-bearing asset that would make every fix below work. |
| Scope gate, arbiter panel, blocker ledger, sample audits | **REAL** — the differentiator, untouched by this diagnosis. |
| Global circuit breakers | **REAL but mis-tuned** for overnight (calendar wall-clock; 2 attempts per feature). |
| Marathon stance | **HALF-THEATRE** — real state machine, but the "loop" is prose executed inside one turn with nothing keeping the turn alive. Never once exercised. |
| Tier-1 `CronCreate` watcher | **THEATRE** — session-scoped; contributes nothing to resurrection. |
| Tier-2 scheduled-tasks watcher | **REAL but unarmed** and app-gated. Zero tasks registered. |
| v2.14 headless shim | **THEATRE AS SHIPPED** — correct code, correct safety posture, wired into nothing, defaults to an artifact that cannot build, never installed. |
| The "honest boundary" prose | **REAL — and that is the trap.** "Not survives while you sleep" appears four separate times across the docs. Documenting the limitation with great care substituted for removing it: three versions of increasingly precise caveats, zero versions where an epic ran overnight. |

## The one-sentence diagnosis

Overnight autonomy fails not because the harness cannot run long, but because we built a
scheduler-based resurrection system with a 45-minute blindness window, gated it behind four opt-ins and
a manual install step nobody has ever taken, capped its wall-clock on calendar time, throttled its only
run-to-completion backend to 15 minutes, and — after an "honesty audit" resting on a factually incorrect
premise — deleted the one harness primitive that keeps a turn alive.

## Proposed next release (decision required — risk levels are the maintainer's call)

Restore the `Stop` hook; measure the budget in working time; detach the codex worker and lift its
15-minute cap; shrink the blindness window; document the long-lived token; teach the failure policy to
**sleep until a usage window resets** instead of halting; and wire the shim into `/v:epic --watch` so it
is armed rather than printed. **The safety posture above is not part of the proposal and does not
change.**
