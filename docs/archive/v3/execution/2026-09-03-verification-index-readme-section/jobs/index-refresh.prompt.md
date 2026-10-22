# Task 0 — regenerate the dogfood index so F1's review files are counted

Compound V run `2026-09-03-verification-index-readme-section`, job `index-refresh`.

Task 0: run `bash scripts/compound-v-dogfood-index.sh` from your worktree root; the produced docs/superpowers/dogfood/README.md is the deliverable. Do not hand-edit it; run the script a second time and confirm `git diff --exit-code docs/superpowers/dogfood/README.md`. If the file did not change, say so and return success with no changes. Run python with -B; register your lane with a literal --cwd. You are unattended: decide and return.

## You are unattended

No one reads this session while it runs and no one will answer a question:
a turn that ends by asking for confirmation, approval or a preference does
NOTHING, and the job is then recorded as an absent implementation. Decide
with the spec, the plan and this prompt; when they are silent, choose the
smallest change that meets the acceptance, do it, run the checks, and return.

## Write-allowed (your lane — anything else is a scope violation)

- `docs/superpowers/dogfood/README.md`

## Read-allowed (advisory — git cannot enforce reads)

- `**`

## Acceptance (your definition of done)

- docs/superpowers/dogfood/README.md is exactly the output of `bash scripts/compound-v-dogfood-index.sh` run from the worktree root (a second run changes nothing).

Turn cap: 30 (default for tier light; default light 30 / standard 50 / deep 80). Plan to finish inside it.

## What you must NOT report

Do not report `blocked`, `files_changed` or `violations`. Those are
enforcement fields, they are derived from git by the caller, and a
constrained party filling in its own enforcement fields is the
fabricated-evidence pattern.
