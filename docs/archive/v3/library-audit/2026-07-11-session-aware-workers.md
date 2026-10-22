# Library/Capability Audit — v2.8.1 Session-Aware Workers (2026-07-11)

All facts LIVE-PROBED on codex-cli 0.144.1 (macOS) via the timeout supervisor with
`</dev/null` — no web-trust. No third-party dependency added; this is codex-CLI capability
verification.

## Verified capabilities

1. **`codex exec --json` emits `thread.started` as the FIRST JSONL event** — 🟢
   `{"type":"thread.started","thread_id":"019f50ba-...-..."}`. The `thread_id` is a UUID and
   IS the session id resume accepts. Capture = read the first line of `--json` stdout, parse
   `thread_id`. (An early `item.completed` may carry a benign `[features].codex_hooks`
   deprecation notice — unrelated, ignore.)

2. **`--json` and `--output-last-message <FILE>` COEXIST** — 🟢 (design-critical, verified)
   With `--json` on, stdout becomes JSONL AND the last-message file is still written verbatim.
   So the worker keeps its existing result path (`.job_result.txt`) and additionally parses
   JSONL for `thread_id`. No either/or.

3. **`codex exec --ephemeral`** — 🟢 "Run without persisting session files to disk." A run
   started `--ephemeral` cannot be resumed (nothing persisted) — exactly right for stateless
   discovery review rounds where resume/anchoring is undesirable.

4. **`codex exec resume [SESSION_ID] [PROMPT]`** — 🟢 SESSION_ID accepts a **UUID or a thread
   name** (UUIDs take precedence). `--last` picks the most recent; `--all` disables cwd
   filtering (relevant: our worktree paths are ephemeral, so cwd-filtered resume can miss a
   session — resume by explicit captured UUID, or pass `--all`).

5. **Thread NAMING at launch — NOT SUPPORTED** — 🔴 for the "resume by our job-id" idea.
   `codex exec --help` exposes no `--name`/`--thread`/`--session` flag; names can only be set
   in interactive flows, not `exec`. **Conclusion: capture the auto-generated `thread_id`
   UUID; do not attempt to name sessions.** (This closes the probe the user asked for.)

## Design constraints for the plan

- Worker MUST capture `thread_id` from the first `thread.started` JSONL line and surface it;
  the caller writes it into `job_result.session_id` (the schema field already exists).
- Adding `--json` MUST NOT change the result-extraction path — `--output-last-message` still
  works; parse JSONL only for the id (+ optional progress signal), keep `.job_result.txt` as
  the canonical last message.
- `--ephemeral` belongs ONLY in the review/discovery script, never the implementer worker
  (implementers are the ones we might resume).
- Resume via captured UUID is authoritative; if ever resuming by cwd, pass `--all`.
- Liveness reading JSONL is an ADDITIONAL signal layered on the existing git+FS classifier —
  degrade-safe: no JSONL file ⇒ fall back to the current mtime/commit logic unchanged.
