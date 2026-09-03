# F2 `matcher-docs` — one glob contract, stated once — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `skills/compound-v/memory.md` and `skills/compound-v/execution-manifest.md` state the one glob contract (the scope gate's matcher, which recall-check now shares after F1) in the same words, each naming the other and the parity selftest as the proof.

**Architecture:** Two doc edits, no code. `execution-manifest.md` gains a short "Glob semantics" paragraph under the `write_allowed`/`read_allowed` rows of its field table (it never stated the semantics). `memory.md`'s `recall-check` row is rewritten with the same rules plus the bare-path reading.

**Tech Stack:** Markdown. Lines ≤ 200 characters. Relative links must resolve (CI dead-link gate).

## Global Constraints

- Only the two files below change. No new section elsewhere; no second description of the semantics anywhere.
- The contract, verbatim in both files: `*` matches within one path segment (never `/`); `**` matches across segments; `dir/**` also matches `dir` itself; `?` matches one non-`/` character; `[` and `]` are literal (no character classes — `app/[locale]/**` is a real directory); matching is anchored to the full repo-relative path.
- recall-check adds one reading: a bare path with no wildcard means "this path or anything under it" (`<path>/**`).
- The proof pointer, verbatim in both files: "the parity rows in `python3 scripts/compound-v-memory.py --selftest`".

## Partition Map (Phase 2 — disjoint write paths)

| Task | write_allowed | type |
|---|---|---|
| A `docs-contract` | `skills/compound-v/memory.md`, `skills/compound-v/execution-manifest.md` | implement (claude · light · low · worktree) |
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

- [ ] **Step 2: Add the paragraph to `execution-manifest.md`** directly after the field table that contains the `write_allowed` and `read_allowed` rows (leave one blank line before and after):

```markdown
**Glob semantics (`write_allowed`, `read_allowed`, `impacted_map.when`).** `*` matches within one path segment (never `/`);
`**` matches across segments; `dir/**` also matches `dir` itself; `?` matches one non-`/` character; `[` and `]` are literal
(no character classes — `app/[locale]/**` is a real directory); matching is anchored to the full repo-relative path. This is
the scope gate's own matcher (`scripts/compound-v-scope-check.py` `matches`), and V-memory's `recall-check` uses the same
matcher — see [`memory.md`](memory.md); the proof is the parity rows in `python3 scripts/compound-v-memory.py --selftest`.
```

- [ ] **Step 3: Rewrite the `recall-check` row in `memory.md`** — replace the row whose first cell starts with `` `recall-check --files <glob>… `` with:

```markdown
| `recall-check --files <glob>… [--k N] [--json]` | **deterministic** recurring-failure → `tighten`/`none`/`unavailable` verdict. Files match lane globs with the same matcher as the scope gate (`*` one segment, `**` across, `dir/**` includes `dir`, `?` one non-`/` char, `[`/`]` literal, anchored — see [`execution-manifest.md`](execution-manifest.md)); a bare path with no wildcard means "this path or anything under it". Proof: the parity rows in `python3 scripts/compound-v-memory.py --selftest`. |
```

- [ ] **Step 4: Verify**

Run: `grep -c 'the same matcher' skills/compound-v/memory.md skills/compound-v/execution-manifest.md` and `grep -n fnmatch skills/compound-v/memory.md skills/compound-v/execution-manifest.md` and `awk 'length > 200 {print FILENAME": "FNR}' skills/compound-v/memory.md skills/compound-v/execution-manifest.md`
Expected: each file counts 1; the fnmatch grep prints nothing; the awk prints nothing (the table row may exceed 200 characters only if the file's existing rows already do — check `awk 'length > 200' skills/compound-v/memory.md | wc -l` before editing and do not add a longer line than the longest existing one; if the row must be shorter, drop the parenthetical rule list and keep the link + "the same matcher" + the proof pointer).

- [ ] **Step 5: Commit**

```bash
git add skills/compound-v/memory.md skills/compound-v/execution-manifest.md
git commit -m "docs(compound-v): one glob contract for the scope gate and recall-check, stated in both files"
```

### Task R: `spec-review-1` — the three-pass Review Gate

**Files:**
- Create: `docs/superpowers/dogfood/2026-09-03-epic-gp-matcher-docs-review-1.md`

Follow the `spec-reviewer` agent definition. SPEC: every acceptance criterion of the spec by name (fnmatch grep empty, "the same matcher" present in both, parity-selftest pointer, links resolve, lines ≤ 200 unless pre-existing rows exceed it). QUALITY: no other section changed (`git diff --stat`), no fabricated claims. INTEGRATION: the rules quoted match `scripts/compound-v-scope-check.py`'s docstring word for word in substance. End with `## Verdict` and one line `VERDICT: APPROVED` or `VERDICT: ISSUES`.
