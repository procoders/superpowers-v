# Review job — spawned by role, must consult V-memory first

Compound V run `2026-09-02-df27-full-pass`, job `spec-review`.

Your agent definition carries a Step 0 telling you to consult V-memory before
reviewing. Follow it, then review
`docs/superpowers/dogfood/2026-09-02-df27-full-pass-impl.md`.

Write `docs/superpowers/dogfood/2026-09-02-df27-full-pass-review.md` with exactly these
three sections:

## Recall
The exact command you ran, and the titles of what came back — or the words
"V-memory returned nothing" if it did. If the script was missing or errored,
say that instead. Do not invent results.

## Review
Two sentences on whether the file under review is accurate.

## Routing
One sentence confirming that nothing you recalled changed any routing
decision, because recall is never a routing input.

Prerequisites, already merged and COMMITTED into your base before this worktree was created: impl-slice.

## Write-allowed (your lane — anything else is a scope violation)

- `docs/superpowers/dogfood/2026-09-02-df27-full-pass-review.md`

## Read-allowed (advisory — git cannot enforce reads)

- `docs/superpowers/dogfood/2026-09-02-df27-full-pass-impl.md`

## Acceptance (your definition of done)

- The review names the recall command it ran and what came back.

## What you must NOT report

Do not report `blocked`, `files_changed` or `violations`. Those are
enforcement fields, they are derived from git by the caller, and a
constrained party filling in its own enforcement fields is the
fabricated-evidence pattern.
