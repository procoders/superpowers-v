# Review Gate pass 3 — review-2's four findings against the merged tree

Compound V run `2026-09-03-v3.4.1-triage-size-r5`, job `spec-review-3`.

Your agent definition carries the three-pass Review Gate and a Step 0 (V-memory recall). Follow it. This is the THIRD and last pass within the cycle cap. Read docs/superpowers/dogfood/2026-09-03-v3.4.1-triage-size-review-2.md: ISSUES (4). The ORCHESTRATOR closed them in commit 2aef342 — review that commit as new code. Finding 1: for each of the five external worker scripts, extract tc_validate + tc_command_at and drive them against the resolver's real slice (produce one with compound-v-fastpath-run.py resolve-tests at tier SCOPED with an unmapped path and a referencing test, and one at FULL); quote the exit codes. Confirm tests/test-engine-c-contract.sh's new checks red against `git show 10c2068:scripts/compound-v-run-codex-worker.sh`. Finding 2: grep -rn for any remaining instruction to write MERGED by hand across commands/ skills/ agents/ README.md. Finding 3: the CHANGELOG line. Finding 4: resolve-tests with an uncomputable previously-failing set at SCOPED — quote the label. Do NOT re-litigate review-1's items unless the fix regressed them; do re-run acceptance criterion 2 of the r1 manifest in a sandbox only if any scorer/taxonomy file changed since cd3ad93 (git diff --stat cd3ad93..HEAD -- scripts/compound-v-preeval.py scripts/compound-v-localize.py scripts/compound-v-taxonomy.py .claude/). Report in one pass, ranked. Write docs/superpowers/dogfood/2026-09-03-v3.4.1-triage-size-review-3.md with ## Recall, ## SPEC, ## QUALITY, ## INTEGRATION, ## Verdict (APPROVED or ISSUES with a numbered list). Run python with -B; register your lane with a literal --cwd.

## Write-allowed (your lane — anything else is a scope violation)

- `docs/superpowers/dogfood/2026-09-03-v3.4.1-triage-size-review-3.md`

## Read-allowed (advisory — git cannot enforce reads)

- `**`

## Acceptance (your definition of done)

- The review-3 file exists with ## Recall, ## SPEC, ## QUALITY, ## INTEGRATION, ## Verdict; for each of review-2's four findings it states closed or open with the command and output that proves it; the verdict is APPROVED or ISSUES with a numbered list.

Turn cap: 80 (default for tier deep; default light 30 / standard 50 / deep 80). Plan to finish inside it.

## What you must NOT report

Do not report `blocked`, `files_changed` or `violations`. Those are
enforcement fields, they are derived from git by the caller, and a
constrained party filling in its own enforcement fields is the
fabricated-evidence pattern.
