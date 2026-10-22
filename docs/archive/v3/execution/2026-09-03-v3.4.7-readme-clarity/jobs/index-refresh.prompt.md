# Task 0 — regenerate the dogfood index so README reads current numbers

Compound V run `2026-09-03-v3.4.7-readme-clarity`, job `index-refresh`.

THE ONE RULE (Oleg, 2026-09-03): documentation must be clear and simple. Plain words, short sentences, one idea per paragraph, every claim true of the code in HEAD; anything measured, historical or defensive is linked (AGENTS.md, CHANGELOG.md, TROUBLESHOOTING.md), never repeated. Run `bash scripts/compound-v-dogfood-index.sh` from your worktree root; the produced docs/superpowers/dogfood/README.md is the deliverable; run it twice and confirm `git diff --exit-code docs/superpowers/dogfood/README.md` on the second run. If nothing changed, say so and return success with no changes. Read the pre-flight audits named in this manifest's audits block first (their §7 MUSTs bind). Run python with -B; register your lane with a literal --cwd. You are unattended: decide and return; if you approach your turn budget, commit what is complete and return a summary that says what is not.

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

- docs/superpowers/dogfood/README.md is exactly the output of `bash scripts/compound-v-dogfood-index.sh` (a second run changes nothing).

Turn cap: 30 (default for tier light; default light 30 / standard 50 / deep 80). Plan to finish inside it.

## What you must NOT report

Do not report `blocked`, `files_changed` or `violations`. Those are
enforcement fields, they are derived from git by the caller, and a
constrained party filling in its own enforcement fields is the
fabricated-evidence pattern.
