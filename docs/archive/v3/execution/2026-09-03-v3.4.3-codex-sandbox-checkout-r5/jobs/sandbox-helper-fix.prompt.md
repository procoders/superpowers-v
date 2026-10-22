# Task A' (codex) — `--taxonomy-from` gets its test, `files:` counts new paths only (review-1 issues 5, 6)

Compound V run `2026-09-03-v3.4.3-codex-sandbox-checkout-r5`, job `sandbox-helper-fix`.

Review pass 1 of this feature (docs/superpowers/dogfood/2026-09-03-v3.4.3-codex-sandbox-checkout-review-1.md) found two issues in your lane: (5) `--taxonomy-from` has no test; (6) the `files:` count is off by one when `--taxonomy-from` replaces a tracked path (count only paths the copy created). Add the test case first, then fix the count. Touch only scripts/compound-v-sandbox-checkout.sh and tests/test-sandbox-checkout.sh. Bash 3.2, set -eu, shellcheck-clean. You are unattended: no one will confirm an approach — implement it, run the test file and shellcheck, and return.

## You are unattended

No one reads this session while it runs and no one will answer a question:
a turn that ends by asking for confirmation, approval or a preference does
NOTHING, and the job is then recorded as an absent implementation. Decide
with the spec, the plan and this prompt; when they are silent, choose the
smallest change that meets the acceptance, do it, run the checks, and return.

## Write-allowed (your lane — anything else is a scope violation)

- `scripts/compound-v-sandbox-checkout.sh`
- `tests/test-sandbox-checkout.sh`

## Read-allowed (advisory — git cannot enforce reads)

- `**`

## Acceptance (your definition of done)

- bash tests/test-sandbox-checkout.sh is green and now carries a `--taxonomy-from <file>` case asserting the sandbox's .claude/compound-v-impact-taxonomy.yaml is byte-identical to the given file and that `files:` reports the number of paths CREATED (a replaced tracked path is not counted twice); shellcheck scripts/compound-v-sandbox-checkout.sh is clean; every earlier case still passes.

Turn cap: 50 (default for tier standard; default light 30 / standard 50 / deep 80). Plan to finish inside it.

## What you must NOT report

Do not report `blocked`, `files_changed` or `violations`. Those are
enforcement fields, they are derived from git by the caller, and a
constrained party filling in its own enforcement fields is the
fabricated-evidence pattern.
