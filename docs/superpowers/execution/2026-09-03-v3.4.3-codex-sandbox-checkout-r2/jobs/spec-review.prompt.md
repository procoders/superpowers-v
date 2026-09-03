# Review Gate — three passes, plus the multi-model contract read from the run directory

Compound V run `2026-09-03-v3.4.3-codex-sandbox-checkout-r2`, job `spec-review`.

Your agent definition carries the three-pass Review Gate and a Step 0 (V-memory recall). Follow it. Run r1 of this feature died at the codex wrapper's spawn (finding 77, fixed in 792c6d2); this is r2. Criterion 2 is the point of this run: quote the session_id, worktree (expect $TMPDIR/compound-v/<run>/<job>, outside the repository), files_changed, the first events-log line and `codex --version` verbatim. Write docs/superpowers/dogfood/2026-09-03-v3.4.3-codex-sandbox-checkout-review-1.md. Run python with -B; register your lane with a literal --cwd.

Prerequisites, already merged and COMMITTED into your base before this worktree was created: sandbox-helper, docs-note.

## Write-allowed (your lane — anything else is a scope violation)

- `docs/superpowers/dogfood/2026-09-03-v3.4.3-codex-sandbox-checkout-review-1.md`

## Read-allowed (advisory — git cannot enforce reads)

- `**`

## Acceptance (your definition of done)

- The review file exists with ## Recall, ## SPEC, ## QUALITY, ## INTEGRATION, ## Verdict; every feature-level acceptance criterion is checked by running its command on the merged tree and quoting the output — criterion 2 by reading results/sandbox-helper.json, receipts/sandbox-helper.gate.json and logs/sandbox-helper.events.jsonl of THIS run, criterion 3 by building a sandbox and driving the hook inside it; the verdict is APPROVED or ISSUES with a numbered list.

Turn cap: 80 (default for tier deep; default light 30 / standard 50 / deep 80). Plan to finish inside it.

## What you must NOT report

Do not report `blocked`, `files_changed` or `violations`. Those are
enforcement fields, they are derived from git by the caller, and a
constrained party filling in its own enforcement fields is the
fabricated-evidence pattern.
