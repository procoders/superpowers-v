# Epic `2026-09-03-verification-index` · F1 `review-index` — Implementation Plan

> **For agentic workers:** executed by Compound V (`/v:dispatch`) on Engine C as one feature of the epic — two jobs in dependency order, the gate and the authority after each wave. Spec: `docs/superpowers/execution/epics/2026-09-03-verification-index/specs/review-index.md`.

**Goal:** a bash generator for the dogfood review index and its committed output.

**Architecture:** Task A writes the script and its test; Task B (after A) runs the script once on the real directory and commits the generated `docs/superpowers/dogfood/README.md`; the review job checks idempotence on the merged tree.

**Tech Stack:** bash 3.2, sed/awk, git; `tests/*.sh` fixture sandbox.

## Global Constraints

- Bash 3.2, `set -eu`, shellcheck-clean; no python.
- Idempotent output (byte-identical on a second run); rows sorted by date then pass.
- Verdict parsing tolerates markdown bold and an optional colon (`**VERDICT: APPROVED**`, `VERDICT: ISSUES`).

## Partition Map (disjoint `write_allowed`)

| Task | Writes |
|---|---|
| A `index-script` | `scripts/compound-v-dogfood-index.sh`, `tests/test-dogfood-index.sh` |
| B `index-output` (after A) | `docs/superpowers/dogfood/README.md` |

### Task A: the generator and its test
- [ ] **Step 1 (failing test):** `tests/test-dogfood-index.sh` builds a fixture dir with `2026-09-01-alpha-review-1.md` (`**VERDICT: ISSUES**`), `2026-09-01-alpha-review-2.md` (`VERDICT: APPROVED`), `2026-09-02-beta-review-1.md` (no verdict line) and a non-review file; runs the script with `--dir <fixture> --out <tmp>`; asserts three rows in date/pass order with verdicts `ISSUES`, `APPROVED`, `unknown`, the footer `Reviews: 3 · APPROVED: 1 · ISSUES: 1 · other: 1`, byte-identical output on a second run, exit non-zero with a message on a missing dir.
- [ ] **Step 2:** implement `scripts/compound-v-dogfood-index.sh [--dir D] [--out P]` (defaults: `docs/superpowers/dogfood`, `<dir>/README.md`); parse per the spec; write atomically (temp file + mv).
- [ ] **Step 3:** `bash tests/test-dogfood-index.sh` green; `shellcheck scripts/compound-v-dogfood-index.sh` clean.

### Task B: the generated index (depends on A)
- [ ] Run `bash scripts/compound-v-dogfood-index.sh` from the repository root; the output file is the deliverable; `git diff --exit-code docs/superpowers/dogfood/README.md` after a second run proves idempotence.
