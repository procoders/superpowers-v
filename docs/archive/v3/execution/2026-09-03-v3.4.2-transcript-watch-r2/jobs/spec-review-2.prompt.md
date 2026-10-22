# Review Gate pass 2 — review-1's ten issues against the merged tree, plus the r1 acceptance criteria

Compound V run `2026-09-03-v3.4.2-transcript-watch-r2`, job `spec-review-2`.

Your agent definition carries the three-pass Review Gate and a Step 0 (V-memory recall). Follow it. This is the SECOND pass. Read review-1 (ISSUES 10) and the two fix jobs of this run as new code. For issue 9, read execution-manifest.md's derived-default table before deciding: `impacted` under a declared impacted_map is the rule at every tier, by the maintainer's decision of 2026-09-02; say whether the reviewer's contract text in agents/spec-reviewer.md §3.3 agrees with it, and if not, name the sentence. Run every acceptance criterion of docs/superpowers/execution/2026-09-03-v3.4.2-transcript-watch/manifest.yaml on the merged tree with /usr/bin/python3 -B, including the watch --once against this run's own transcripts (no --wf), and quote the roster. Write docs/superpowers/dogfood/2026-09-03-v3.4.2-transcript-watch-review-2.md. Run python with -B; register your lane with a literal --cwd.

Prerequisites, already merged and COMMITTED into your base before this worktree was created: watch-script, docs-wiring.

## Write-allowed (your lane — anything else is a scope violation)

- `docs/superpowers/dogfood/2026-09-03-v3.4.2-transcript-watch-review-2.md`

## Read-allowed (advisory — git cannot enforce reads)

- `**`

## Acceptance (your definition of done)

- The review-2 file exists with ## Recall, ## SPEC, ## QUALITY, ## INTEGRATION, ## Verdict; for each of review-1's ten issues it states closed or open with the command and output that proves it — issue 9 is answered by the maintainer's derived-default rule (skills/compound-v/execution-manifest.md, 'The derived default'), not by a code change; every feature-level acceptance criterion of the r1 manifest is re-run on the merged tree, including the watch run --once against THIS run's own transcripts with its per-agent roster quoted; the verdict is APPROVED or ISSUES with a numbered list.

Turn cap: 80 (default for tier deep; default light 30 / standard 50 / deep 80). Plan to finish inside it.

## What you must NOT report

Do not report `blocked`, `files_changed` or `violations`. Those are
enforcement fields, they are derived from git by the caller, and a
constrained party filling in its own enforcement fields is the
fabricated-evidence pattern.
