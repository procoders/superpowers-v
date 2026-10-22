# Task B — the generated docs/superpowers/dogfood/README.md

Compound V run `2026-09-03-verification-index-review-index`, job `index-output`.

Task B: run `bash scripts/compound-v-dogfood-index.sh` from your worktree root (Task A's script is in HEAD by the time you run); the produced docs/superpowers/dogfood/README.md is the deliverable. Do not hand-edit it; run the script a second time and confirm `git diff --exit-code docs/superpowers/dogfood/README.md`. Run python with -B; register your lane with a literal --cwd.

Prerequisites, already merged and COMMITTED into your base before this worktree was created: index-script.

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

- docs/superpowers/dogfood/README.md is exactly the output of `bash scripts/compound-v-dogfood-index.sh` run from the repository root on the merged tree (a second run changes nothing); its row count equals the number of *review*.md files under docs/superpowers/dogfood/.

Turn cap: 30 (default for tier light; default light 30 / standard 50 / deep 80). Plan to finish inside it.

## What you must NOT report

Do not report `blocked`, `files_changed` or `violations`. Those are
enforcement fields, they are derived from git by the caller, and a
constrained party filling in its own enforcement fields is the
fabricated-evidence pattern.
