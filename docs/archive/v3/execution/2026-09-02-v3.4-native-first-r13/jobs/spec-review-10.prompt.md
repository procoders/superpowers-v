# Review Gate — three passes against the spec and the feature-level acceptance criteria

Compound V run `2026-09-02-v3.4-native-first-r13`, job `spec-review-10`.

Your agent definition carries the three-pass Review Gate and a Step 0 (V-memory recall).
Follow it. This is the TENTH pass. Read the nine earlier passes under docs/superpowers/dogfood/. The
ninth pass found Codex H4 and L1 still open, records claiming otherwise, a stale comment, an orphaned
probe child, and a documented residual. The ORCHESTRATOR closed items 1–5 directly in the commit
"fix(gate): a pruned job is proven by its sealed patch, never by pathname overlap; …" — review that
commit as new code: reproduce the ninth pass's decoy-commit case against the merged tree (must be
unverifiable), confirm a real merge with a sealed patch passes, confirm no sealed patch ⇒
unverifiable; check RUN_DIR_EXEMPT_BY_NAME against the docstrings and the scope-check header; run the
lane-guard suite and confirm the orphan assertion discriminates (restore the old watchdog line in a
copy and show it reds). Report everything in one pass, ranked. Then run the acceptance commands on
the whole merged tree with /usr/bin/python3 -B. Write
docs/superpowers/dogfood/2026-09-02-v3.4-native-first-review-10.md with ## Recall, ## SPEC,
## QUALITY, ## INTEGRATION, ## Verdict (APPROVED or ISSUES with a numbered list). Run python with
-B; register your lane with a literal --cwd.

## Write-allowed (your lane — anything else is a scope violation)

- `docs/superpowers/dogfood/2026-09-02-v3.4-native-first-review-10.md`

## Read-allowed (advisory — git cannot enforce reads)

- `**`

## Acceptance (your definition of done)

- The review-10 file exists with the five sections; it states, for each of the ninth pass's six items, closed or open with evidence; the verdict is APPROVED or ISSUES with a numbered list.

Turn cap: 80 (default for tier deep; default light 30 / standard 50 / deep 80). Plan to finish inside it.

## What you must NOT report

Do not report `blocked`, `files_changed` or `violations`. Those are
enforcement fields, they are derived from git by the caller, and a
constrained party filling in its own enforcement fields is the
fabricated-evidence pattern.
