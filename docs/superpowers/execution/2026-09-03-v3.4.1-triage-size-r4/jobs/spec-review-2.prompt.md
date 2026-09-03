# Review Gate pass 2 — the five issues of review-1 against the merged tree

Compound V run `2026-09-03-v3.4.1-triage-size-r4`, job `spec-review-2`.

Your agent definition carries the three-pass Review Gate and a Step 0 (V-memory recall). Follow it. This is the SECOND pass. Read docs/superpowers/dogfood/2026-09-03-v3.4.1-triage-size-review-1.md: it found ISSUES (5). The ORCHESTRATOR closed them in commit e9ab86f ("fix(v3.4.1 review-1): …") — review that commit as new code. Issue 1: reproduce your predecessor's sandbox probe (git ls-files copy, fresh git init, empty pre-eval dir — the hook is silent on a checkout with an active run, and THIS run is active) for the four requests of acceptance criterion 2 plus a `.github/workflows/validate.yml` edit (the never-demote case) and a new file under scripts/; quote the tiers, flavors and t3_demotion fields. Issue 2: grep the four documents for any instruction to write MERGED by hand. Issue 3: read the CHANGELOG/README claims against your probe. Issue 4: run compound-v-fastpath-run.py resolve-tests at tier FULL with an unmapped path and quote the label. Issue 5: the 3.4.1 intro line. Then run every feature-level acceptance criterion of the r1 manifest (docs/superpowers/execution/2026-09-03-v3.4.1-triage-size/manifest.yaml) on the merged tree with /usr/bin/python3 -B. Report everything in one pass, ranked. Write docs/superpowers/dogfood/2026-09-03-v3.4.1-triage-size-review-2.md with ## Recall, ## SPEC, ## QUALITY, ## INTEGRATION, ## Verdict (APPROVED or ISSUES with a numbered list). Run python with -B; register your lane with a literal --cwd.

## Write-allowed (your lane — anything else is a scope violation)

- `docs/superpowers/dogfood/2026-09-03-v3.4.1-triage-size-review-2.md`

## Read-allowed (advisory — git cannot enforce reads)

- `**`

## Acceptance (your definition of done)

- The review-2 file exists with ## Recall, ## SPEC, ## QUALITY, ## INTEGRATION, ## Verdict; for each of review-1's five issues it states closed or open with the command and output that proves it; the verdict is APPROVED or ISSUES with a numbered list.

Turn cap: 80 (default for tier deep; default light 30 / standard 50 / deep 80). Plan to finish inside it.

## What you must NOT report

Do not report `blocked`, `files_changed` or `violations`. Those are
enforcement fields, they are derived from git by the caller, and a
constrained party filling in its own enforcement fields is the
fabricated-evidence pattern.
