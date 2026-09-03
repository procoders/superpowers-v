# Review Gate — three passes against the spec and the feature acceptance criteria

Compound V run `2026-09-03-v3.4.5-recall-freshness`, job `spec-review`.

Your agent definition carries the three-pass Review Gate and a Step 0 (V-memory recall). Follow it — and note that Step 0 is the live test of the feature under review: quote your `search` invocation's stderr (the refresh line, or the absence of one). Review both jobs as new code against docs/superpowers/specs/2026-09-03-v3.4.5-recall-freshness-design.md and this manifest's acceptance criteria; reproduce AC 1 in a throwaway git repository with a docs/superpowers/ doc added after the first search; confirm no embedder call reaches search (`grep -n embed scripts/compound-v-memory.py` around cmd_search). Write docs/superpowers/dogfood/2026-09-03-v3.4.5-recall-freshness-review.md. Run python with -B; register your lane with a literal --cwd.

Prerequisites, already merged and COMMITTED into your base before this worktree was created: engine, docs.

## You are unattended

No one reads this session while it runs and no one will answer a question:
a turn that ends by asking for confirmation, approval or a preference does
NOTHING, and the job is then recorded as an absent implementation. Decide
with the spec, the plan and this prompt; when they are silent, choose the
smallest change that meets the acceptance, do it, run the checks, and return.

## Write-allowed (your lane — anything else is a scope violation)

- `docs/superpowers/dogfood/2026-09-03-v3.4.5-recall-freshness-review.md`

## Read-allowed (advisory — git cannot enforce reads)

- `**`

## Acceptance (your definition of done)

- The review file exists with ## Recall, ## SPEC, ## QUALITY, ## INTEGRATION, ## Verdict; Step 0's own `search` output is quoted, including whether it printed the refresh line (the live test of this feature); every acceptance criterion is run on the merged tree with the command and output; AC 1 is reproduced in a throwaway git repo; the verdict is APPROVED or ISSUES with a numbered list.

Turn cap: 80 (default for tier deep; default light 30 / standard 50 / deep 80). Plan to finish inside it.

## What you must NOT report

Do not report `blocked`, `files_changed` or `violations`. Those are
enforcement fields, they are derived from git by the caller, and a
constrained party filling in its own enforcement fields is the
fabricated-evidence pattern.
