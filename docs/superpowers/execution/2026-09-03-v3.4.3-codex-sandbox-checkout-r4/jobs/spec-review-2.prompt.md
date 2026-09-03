# Review Gate pass 2 — review-1's seven issues, and the session id read from this run's own directory

Compound V run `2026-09-03-v3.4.3-codex-sandbox-checkout-r4`, job `spec-review-2`.

Your agent definition carries the three-pass Review Gate and a Step 0 (V-memory recall). Follow it. This is the SECOND pass. Read review-1 (ISSUES 7) and this run's two fix jobs as new code; the orchestrator closed issues 1 and 3 in the emitter and the lane guard (commits after 87ed50b) — verify them from THIS run's artefacts: results/sandbox-helper-fix.json session_id must equal the UUID in logs/sandbox-helper-fix.events.jsonl line 1. Do not run `codex`; the events log is the evidence. Write docs/superpowers/dogfood/2026-09-03-v3.4.3-codex-sandbox-checkout-review-2.md. Run python with -B; register your lane with a literal --cwd.

Prerequisites, already merged and COMMITTED into your base before this worktree was created: sandbox-helper-fix, docs-fix.

## Write-allowed (your lane — anything else is a scope violation)

- `docs/superpowers/dogfood/2026-09-03-v3.4.3-codex-sandbox-checkout-review-2.md`

## Read-allowed (advisory — git cannot enforce reads)

- `**`

## Acceptance (your definition of done)

- The review-2 file exists with ## Recall, ## SPEC, ## QUALITY, ## INTEGRATION, ## Verdict; for each of review-1's seven issues it states closed or open with the command and output that proves it (issue 7 is closed by dropping the `codex --version` requirement — the events log's first line is the evidence instead; issue 4 is recorded as cache drift, out of every lane); results/sandbox-helper-fix.json of THIS run carries a session_id that is a UUID equal to the thread_id in logs/sandbox-helper-fix.events.jsonl's first line, quoted verbatim; the verdict is APPROVED or ISSUES with a numbered list.

Turn cap: 80 (default for tier deep; default light 30 / standard 50 / deep 80). Plan to finish inside it.

## What you must NOT report

Do not report `blocked`, `files_changed` or `violations`. Those are
enforcement fields, they are derived from git by the caller, and a
constrained party filling in its own enforcement fields is the
fabricated-evidence pattern.
