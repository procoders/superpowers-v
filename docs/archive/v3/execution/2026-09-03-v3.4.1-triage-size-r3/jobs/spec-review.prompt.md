# Review Gate — three passes against the spec and the feature-level acceptance criteria

Compound V run `2026-09-03-v3.4.1-triage-size-r3`, job `spec-review`.

Your agent definition carries the three-pass Review Gate and a Step 0 (V-memory recall). Follow it. Run every feature-level acceptance criterion of this manifest on the merged tree with /usr/bin/python3 -B, including driving hooks/triage-prompt-nudge.sh with synthetic UserPromptSubmit stdin for the four requests named in criterion 2 (use a throwaway session id; the records it writes are evidence — leave them uncommitted and list them). Write docs/superpowers/dogfood/2026-09-03-v3.4.1-triage-size-review-1.md. Run python with -B; register your lane with a literal --cwd.

Prerequisites, already merged and COMMITTED into your base before this worktree was created: release.

## Write-allowed (your lane — anything else is a scope violation)

- `docs/superpowers/dogfood/2026-09-03-v3.4.1-triage-size-review-1.md`

## Read-allowed (advisory — git cannot enforce reads)

- `**`

## Acceptance (your definition of done)

- The review file exists with

Turn cap: 80 (default for tier deep; default light 30 / standard 50 / deep 80). Plan to finish inside it.

## What you must NOT report

Do not report `blocked`, `files_changed` or `violations`. Those are
enforcement fields, they are derived from git by the caller, and a
constrained party filling in its own enforcement fields is the
fabricated-evidence pattern.
