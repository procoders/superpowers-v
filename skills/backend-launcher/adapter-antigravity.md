# Adapter: antigravity (stub — deferred to 1.1)

> *"Not every supe makes the team. This one's still in the lab — we benched it on purpose, and we're honest about why."*

Read the contract first: [`SKILL.md`](SKILL.md). This adapter is a **stub**. It implements the `job_spec → job_result` shape but does no work: it returns a clearly-labeled **unsupported** result so the dispatcher fails fast and routes elsewhere (env-aware routing collapses to Claude-only when no usable third-party backend is present). It ships in v1.0 as a placeholder, not a backend.

## Behavior

Given any `job_spec` with `backend: antigravity`, return immediately — never spawn `agy`, never touch git, never merge:

```jsonc
{
  "status": "error",
  "blocked": false,
  "files_changed": [],
  "violations": [],
  "summary": "unsupported: the antigravity backend is a v1.0 stub (deferred to 1.1). No work was performed; route this job to claude or codex.",
  "session_id": "",
  "worktree": "",
  "exit_code": 0
}
```

`status: "error"` + the explicit `"unsupported"` summary is the contract-level signal "this backend cannot run"; `blocked` stays `false` because nothing was dispatched and no file moved. `files_changed` / `violations` are empty for the same reason. The dispatcher treats this as "no backend" and either re-routes (Claude-only fallback) or returns the job to planning — it does **not** halt the whole run on a stub.

## Why deferred — verified, not assumed

Google's official `agy` CLI (Go, v1.0.12) fits this contract on paper — its headless shape already matches (`agy --print --sandbox --model … --add-dir <worktree> < prompt > result`), and file-scope would reuse the same worktree + `git diff` approach as Codex, so the adapter is roughly a one-day port *once it works*. Two blockers keep it out of v1.0:

- **Headless stdout is broken when piped/redirected** — `agy --print` returns empty stdout (exit 0) when output is piped or redirected, which is exactly how an adapter captures a result. ([#408](https://github.com/google-antigravity/antigravity-cli/issues/408), [#318](https://github.com/google-antigravity/antigravity-cli/issues/318))
- **No non-interactive auth** — interactive Google OAuth only; API keys are ignored, so it cannot authenticate in a scripted dispatcher. ([#223](https://github.com/google-antigravity/antigravity-cli/issues/223))

It is also preview-grade (399+ open issues, no license). We will not ship a backend we cannot verify.

## v1.1 target

The likelier unblock is the **Antigravity Python SDK** — it returns programmatic output over WebSockets, sidestepping the TTY-stdout bug entirely. **Spike the Python SDK first** in v1.1; fall back to the `agy` CLI only once #408/#318/#223 close. When either path lands, this stub becomes a real adapter that reuses the same worktree + `git diff` scope gate as [`adapter-codex.md`](adapter-codex.md) — the launcher's reuse payoff.
