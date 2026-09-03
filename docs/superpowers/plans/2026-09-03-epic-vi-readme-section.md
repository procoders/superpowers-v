# Epic `2026-09-03-verification-index` · F2 `readme-section` — Implementation Plan

> **For agentic workers:** executed by Compound V (`/v:dispatch`) on Engine C as feature 2 of the epic. Spec: `docs/superpowers/execution/epics/2026-09-03-verification-index/specs/readme-section.md`. F1 (`review-index`) is in HEAD.

**Goal:** README.md gains a "Verification program" section whose two numbers are read from the generated index footer.

**Architecture:** one docs job (worktree, light tier) + the review job (direct). No script changes.

## Partition Map
| Task | Writes |
|---|---|
| A `readme-section` | `README.md` |

### Task A
- [ ] Read `docs/superpowers/dogfood/README.md`'s footer (`Reviews: N · APPROVED: A · …`), then insert `## Verification program` before the last `##` section of README.md: what the program is (stages 1–8, each a dogfood cycle against native Claude Code mechanisms), a link to the index, and the sentence "N review files, A APPROVED" with the footer's numbers.
- [ ] `/usr/bin/python3 -B scripts/lint-frontmatter.py .` green; the section appears exactly once; the link target exists.

### Review
- [ ] Both numbers equal the footer; the index is regenerated first (`bash scripts/compound-v-dogfood-index.sh`) so F1's review file is counted, and if the footer changed, the README numbers are re-checked against the regenerated footer (the review says which).
