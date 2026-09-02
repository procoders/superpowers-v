# Review Gate — three passes against the spec and the feature-level acceptance criteria

Compound V run `2026-09-02-v3.4-native-first-r11`, job `spec-review-8`.

Your agent definition carries the three-pass Review Gate and a Step 0 (V-memory recall).
Follow it. This is the EIGHTH pass. Read the seven earlier passes under docs/superpowers/dogfood/.
The seventh pass raised two items (a PATH test that could not fail; the hook cost stated for one
population). This run's job worker-concise closed them AND introduced the implementer role
(agents/implementer.md with maxTurns and the official Opus 5 conciseness snippets), spawned by
agentType for every non-review claude job, plus the effort policy and the /v:init env offer.
Review the merge as new code: verify the snippets are verbatim from Anthropic's Opus 5 guide;
verify the rendered implementer prompt carries no verification imperative; drive the lane-guard
PATH case against the pre-change hook and show it reds; check both cost numbers against a
measurement of your own. Report everything you find in this one pass, ranked. Then run the
acceptance commands on the whole merged tree with /usr/bin/python3 -B. Write
docs/superpowers/dogfood/2026-09-02-v3.4-native-first-review-8.md with ## Recall, ## SPEC,
## QUALITY, ## INTEGRATION, ## Verdict (APPROVED or ISSUES with a numbered list). Run python with
-B; register your lane with a literal --cwd.

Prerequisites, already merged and COMMITTED into your base before this worktree was created: worker-concise.

## Write-allowed (your lane — anything else is a scope violation)

- `docs/superpowers/dogfood/2026-09-02-v3.4-native-first-review-8.md`

## Read-allowed (advisory — git cannot enforce reads)

- `**`

## Acceptance (your definition of done)

- The review-8 file exists with the five sections; it states, for each of the seventh pass's two items and for the implementer role, closed/open with evidence; the verdict is APPROVED or ISSUES with a numbered list.

## What you must NOT report

Do not report `blocked`, `files_changed` or `violations`. Those are
enforcement fields, they are derived from git by the caller, and a
constrained party filling in its own enforcement fields is the
fabricated-evidence pattern.
