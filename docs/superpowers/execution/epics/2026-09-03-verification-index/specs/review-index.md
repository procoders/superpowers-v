# F1 `review-index` — the dogfood review index generator — spec

**Goal.** `scripts/compound-v-dogfood-index.sh [--dir docs/superpowers/dogfood] [--out <path>]` writes a Markdown
index of every `*review*.md` under the dogfood directory: `| date | feature | pass | verdict | file |`, sorted by
date then pass, plus a footer `Reviews: N · APPROVED: A · ISSUES: I · other: O`. Idempotent: the same inputs
produce byte-identical output. Bash 3.2 + git + sed/awk; shellcheck-clean; exit 0 on success, non-zero with one
message when the directory is missing.

**Parsing.** `date` = the leading `YYYY-MM-DD` of the filename; `feature` = the filename between the date and
`-review`; `pass` = the trailing `-N` after `review` (1 when absent); `verdict` = the first line matching
`^\**VERDICT:?\**\s*(APPROVED|ISSUES)` (case-insensitive, markdown bold tolerated), else `unknown`.

**Files.** Create `scripts/compound-v-dogfood-index.sh`, `tests/test-dogfood-index.sh` (fixture dir with three
review files of two features and two passes; asserts the table rows, the footer counts, idempotence, the
missing-dir refusal); write `docs/superpowers/dogfood/README.md` by running the script once on the real dir.

**Acceptance criteria.** `bash tests/test-dogfood-index.sh` green; `shellcheck` clean; the generated
`docs/superpowers/dogfood/README.md` exists, its row count equals `ls docs/superpowers/dogfood/*review*.md | wc -l`,
and a second run changes nothing (`git diff --exit-code docs/superpowers/dogfood/README.md`).

## Pre-flight amendments (2026-09-03, after 1A archaeology and 1C library audit)

1. **Verdict line, corrected against the corpus (42% of real files would have read `unknown`):** the first line
   matching, case-insensitively, `^(#+[[:space:]]*)?\**VERDICT:?\**[[:space:]]*\**(APPROVED|ISSUES)` — an H2 prefix
   (`## VERDICT: …`) and asterisks around the value (`VERDICT: **ISSUES**`) are both real. Keep the line-start
   anchor (a mid-sentence `verdict: pass` exists in one file). POSIX classes only — BSD grep has no `\s`.
2. **Discovery:** `<date>-<feature>-review.md` and `<date>-<feature>-review-<N>.md` only — `*review*.md` also
   matches `…-reviewer-…-impl.md`. `feature` strips from the LAST `-review`; `pass` allows two digits and sorts
   numerically; `LC_ALL=C` on every sort so macOS and CI agree byte for byte.
3. **A no-match grep must not abort** (`|| true`, the idiom of `compound-v-run-codex-worker.sh`); five real
   reviews carry no verdict line and are `unknown` rows, not crashes.
4. **Bash 3.2 for real:** no `declare -A`, `mapfile`, `${var,,}`; case-insensitivity via `grep -iE`; no `sed -i`
   (temp file + `mv`); no gawk-only builtins. shellcheck cannot prove 3.2 compatibility — the test runs the
   script under `/bin/bash` (3.2.57 on macOS) explicitly.
5. **F1's footer must match reality, not only F2's numbers:** the review spot-checks three files including one
   `## VERDICT` file and one `**ISSUES**` file; and the footer's `APPROVED` count must be ≥ the count of
   `grep -lE '^(#+[[:space:]]*)?\**VERDICT:?\**[[:space:]]*\**APPROVED' docs/superpowers/dogfood/*-review*.md`.
6. **CI shellchecks `hooks/*.sh` only** — widening it to `scripts/*.sh` is a follow-up recorded here.
