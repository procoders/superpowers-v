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
