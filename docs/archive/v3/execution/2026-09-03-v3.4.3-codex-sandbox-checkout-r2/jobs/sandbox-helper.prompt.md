# Task A (codex) — scripts/compound-v-sandbox-checkout.sh and tests/test-sandbox-checkout.sh

Compound V run `2026-09-03-v3.4.3-codex-sandbox-checkout-r2`, job `sandbox-helper`.

Implement plan Task A (docs/superpowers/plans/2026-09-03-v3.4.3-codex-sandbox-checkout.md) against the spec (docs/superpowers/specs/2026-09-03-v3.4.3-codex-sandbox-checkout-design.md §Decisions 1–2). Write the failing test first, then the script. Bash 3.2 (macOS default): no associative arrays, no mapfile; `git ls-files -z` + `cp -p`; `set -eu`; shellcheck-clean. Touch only the two files of your lane. Pre-flight amendments 3–4 apply: symlinks are copied as symlinks (cp -pR on the single path, never follow), and --help says gitignored files are never carried.

## Write-allowed (your lane — anything else is a scope violation)

- `scripts/compound-v-sandbox-checkout.sh`
- `tests/test-sandbox-checkout.sh`

## Read-allowed (advisory — git cannot enforce reads)

- `**`

## Acceptance (your definition of done)

- bash tests/test-sandbox-checkout.sh is green and asserts every case of plan Task A Step 1 (byte identity, kept modes, untracked absent, execution dir dropped/kept, pre-eval emptied, exit 3 on a non-empty dest, exit 2 outside a git repo); shellcheck scripts/compound-v-sandbox-checkout.sh is clean.
- The script is bash 3.2 compatible, set -eu, uses git only (no python, no jq), never writes outside <dest>, and prints `sandbox: <dest>` and `files: <n> commit: <sha>` on success.
- A tracked symlink is copied as a symlink, never followed (the test creates one); --help states that gitignored files (lane-map.json, logs/*.jsonl) are never carried, keep-execution or not.

Turn cap: 50 (default for tier standard; default light 30 / standard 50 / deep 80). Plan to finish inside it.

## What you must NOT report

Do not report `blocked`, `files_changed` or `violations`. Those are
enforcement fields, they are derived from git by the caller, and a
constrained party filling in its own enforcement fields is the
fabricated-evidence pattern.
