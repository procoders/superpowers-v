# Review Gate pass 3 — review-2's three issues against the merged tree (last within the cycle cap)

Compound V run `2026-09-03-v3.4.2-transcript-watch-r3`, job `spec-review-3`.

Your agent definition carries the three-pass Review Gate and a Step 0 (V-memory recall). Follow it. This is the THIRD and last pass within the cycle cap. Read review-2 (ISSUES 3) and the two fix jobs of this run as new code; reproduce issue 1's REPL cases on the merged tree; run the r1 manifest's acceptance criteria (docs/superpowers/execution/2026-09-03-v3.4.2-transcript-watch/manifest.yaml) with /usr/bin/python3 -B, including the watch --once against this run's own transcripts (no --wf) with the roster quoted. Write docs/superpowers/dogfood/2026-09-03-v3.4.2-transcript-watch-review-3.md. Run python with -B; register your lane with a literal --cwd.

Prerequisites, already merged and COMMITTED into your base before this worktree was created: watch-script, reviewer-contract.

## Write-allowed (your lane — anything else is a scope violation)

- `docs/superpowers/dogfood/2026-09-03-v3.4.2-transcript-watch-review-3.md`

## Read-allowed (advisory — git cannot enforce reads)

- `**`

## Acceptance (your definition of done)

- The review-3 file exists with ## Recall, ## SPEC, ## QUALITY, ## INTEGRATION, ## Verdict; for each of review-2's three issues it states closed or open with the command and output that proves it; every feature-level acceptance criterion of the r1 manifest is re-run on the merged tree including the watch --once against THIS run's own transcripts (roster quoted); the verdict is APPROVED or ISSUES with a numbered list.

Turn cap: 80 (default for tier deep; default light 30 / standard 50 / deep 80). Plan to finish inside it.

## What you must NOT report

Do not report `blocked`, `files_changed` or `violations`. Those are
enforcement fields, they are derived from git by the caller, and a
constrained party filling in its own enforcement fields is the
fabricated-evidence pattern.
