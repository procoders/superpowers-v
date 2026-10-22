# F2 `matcher-docs` — one glob contract, stated once — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `skills/compound-v/memory.md` and `skills/compound-v/execution-manifest.md` state the one glob contract (the scope gate's matcher, which recall-check now shares after F1) in the same words, each naming the other and the parity selftest as the proof.

**Architecture:** Two doc edits, no code. `execution-manifest.md` gains a short "Glob semantics" paragraph after the end of its "Per-job fields" section (after the footnote and the trailing paragraph, before `### Tier vocabulary` — the field table is contiguous and cannot take a paragraph between rows). `memory.md`'s `recall-check` row is rewritten in place as a same-line-count replacement with the identical six-rule sentence plus the bare-path reading (recall-check only).

**Tech Stack:** Markdown. Lines ≤ 200 characters. Relative links must resolve (CI dead-link gate).

## Global Constraints

- Only the two files below change. No new section elsewhere; no second description of the semantics anywhere.
- The contract, verbatim in both files: `*` matches within one path segment (never `/`); `**` matches across segments; `dir/**` also matches `dir` itself; `?` matches one non-`/` character; `[` and `]` are literal (no character classes — `app/[locale]/**` is a real directory); matching is anchored to the full repo-relative path.
- recall-check adds one reading: a bare path with no wildcard means "this path or anything under it" (`<path>/**`).
- The proof pointer, verbatim in both files: "the parity rows in `python3 scripts/compound-v-memory.py --selftest`".

## Partition Map (Phase 2 — disjoint write paths)

| Task | write_allowed | type |
|---|---|---|
| A `docs-contract` | `skills/compound-v/memory.md`, `skills/compound-v/execution-manifest.md` | implement (claude · standard · medium · worktree — two files with a verbatim-in-both constraint: not a junior box) |
| R `spec-review-1` | `docs/superpowers/dogfood/2026-09-03-epic-gp-matcher-docs-review-1.md` | review (claude · deep · high · direct, depends_on A) |

Shared resources: none. Task 0: none.

---

### Task A: `docs-contract` — the same six rules in both files

**Files:**
- Modify: `skills/compound-v/execution-manifest.md` (after the `read_allowed` row of the field table, near line 54)
- Modify: `skills/compound-v/memory.md` (the `recall-check` row, line 54)

- [ ] **Step 1: Find the anchors**

Run: `grep -n 'read_allowed' skills/compound-v/execution-manifest.md | head -3` and `grep -n 'recall-check --files' skills/compound-v/memory.md`
Expected: the `read_allowed` table row (~line 54) and the `recall-check` row (line 54).

- [ ] **Step 2: Add the paragraph to `execution-manifest.md`** after the end of the "Per-job fields" section — after its footnote and its one trailing paragraph — and immediately before the `### Tier vocabulary` heading (find it with `grep -n '^### Tier vocabulary' skills/compound-v/execution-manifest.md`; leave one blank line before and after; never inside the table):

```markdown
**Glob semantics (`write_allowed`, `read_allowed`, `impacted_map.when`).** `*` matches within one path segment (never `/`);
`**` matches across segments; `dir/**` also matches `dir` itself; `?` matches one non-`/` character; `[` and `]` are literal
(no character classes — `app/[locale]/**` is a real directory); matching is anchored to the full repo-relative path. This is
the scope gate's own matcher (`scripts/compound-v-scope-check.py` `matches`), and V-memory's `recall-check` uses the same
matcher — see [`memory.md`](memory.md); the proof is the `parity …` rows of `python3 scripts/compound-v-memory.py --selftest`.
```

- [ ] **Step 3: Rewrite the `recall-check` row in `memory.md`** — replace the ONE physical line whose first cell starts with `` `recall-check --files <glob>… `` with the ONE line below (same line count: no blank lines added or removed — `docs/superpowers/architecture/architecture.md` anchors line numbers into this file):

```markdown
| `recall-check --files <glob>… [--k N] [--json]` | **deterministic** recurring-failure → `tighten`/`none`/`unavailable` verdict. Files match lane globs with the same matcher as the scope gate: `*` matches within one path segment (never `/`); `**` matches across segments; `dir/**` also matches `dir` itself; `?` matches one non-`/` character; `[` and `]` are literal (no character classes — `app/[locale]/**` is a real directory); matching is anchored to the full repo-relative path (see [`execution-manifest.md`](execution-manifest.md)). recall-check only: a bare path with no wildcard means "this path or anything under it" (the enforced gate has no such reading). Proof: the `parity …` rows of `python3 scripts/compound-v-memory.py --selftest`. |
```

- [ ] **Step 4: Verify**

Run: `grep -c 'the same matcher' skills/compound-v/memory.md skills/compound-v/execution-manifest.md`, `git diff --stat` (exactly two files), `git diff -U0 skills/compound-v/memory.md | grep -c '^[-+][^-+]'` (exactly 2: one line removed, one added), and `wc -l skills/compound-v/memory.md` before and after (identical)
Expected: each file counts 1; the fnmatch grep prints nothing. Line length, decided up front (partition review 2026-09-03): `memory.md` already carries table rows longer than 200 characters, so the rewritten `recall-check` row may exceed 200 characters but must stay at or below the longest line already in the file (measure it with `awk 'length>max{max=length} END{print max}' skills/compound-v/memory.md` before editing); the `execution-manifest.md` paragraph is wrapped at ≤ 120 characters per line. No other fallback: the rule list, the link, "the same matcher" and the proof pointer are all mandatory in both files.

- [ ] **Step 5: Commit**

```bash
git add skills/compound-v/memory.md skills/compound-v/execution-manifest.md
git commit -m "docs(compound-v): one glob contract for the scope gate and recall-check, stated in both files"
```

### Task R: `spec-review-1` — the three-pass Review Gate

**Files:**
- Create: `docs/superpowers/dogfood/2026-09-03-epic-gp-matcher-docs-review-1.md`

Follow the `spec-reviewer` agent definition. SPEC: every acceptance criterion of the spec by name (fnmatch grep empty, "the same matcher" present in both, parity-selftest pointer, links resolve, lines ≤ 200 unless pre-existing rows exceed it). QUALITY: no other section changed (`git diff --stat`), no fabricated claims. INTEGRATION: the rules quoted match `scripts/compound-v-scope-check.py`'s docstring word for word in substance. End with `## Verdict` and one line `VERDICT: APPROVED` or `VERDICT: ISSUES`.
