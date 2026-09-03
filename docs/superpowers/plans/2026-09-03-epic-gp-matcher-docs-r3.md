# F2 `matcher-docs` attempt 3 — the exact text, pasted — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Attempts 1 and 2 (reviews `…-matcher-docs-review-1.md`, `…-matcher-docs-r2-review-1.md`) both worked from the previous diff and paraphrased. Attempt 3 resets the two files to their pre-F2 content and pastes two exact blocks. Nothing is composed by the worker.

**Architecture:** `git checkout 16786b7 -- skills/compound-v/memory.md skills/compound-v/execution-manifest.md` restores the pre-F2 files (only the two F2 attempts touched them since 16786b7, verified with `git log 16786b7..HEAD -- <files>`). Then one paragraph is inserted before `### Tier vocabulary` in `execution-manifest.md`, and one physical line (the `recall-check` row) is replaced in `memory.md`. The floor test greps the sentence in both files, so the gate enforces the content.

**Tech Stack:** Markdown; bash; git.

## Partition Map (Phase 2 — disjoint write paths)

| Task | write_allowed | type |
|---|---|---|
| A `docs-exact` | `skills/compound-v/memory.md`, `skills/compound-v/execution-manifest.md` | implement (claude · deep · high · worktree) |
| R `spec-review-1` | `docs/superpowers/dogfood/2026-09-03-epic-gp-matcher-docs-r3-review-1.md` | review (claude · deep · high · direct, depends_on A) |

---

### Task A: `docs-exact`

- [ ] **Step 0: Reset both files to the pre-F2 content**

```bash
git checkout 16786b7 -- skills/compound-v/memory.md skills/compound-v/execution-manifest.md
wc -l skills/compound-v/memory.md   # expect 202
grep -c 'Glob semantics' skills/compound-v/execution-manifest.md   # expect 0
```

- [ ] **Step 1: Insert the paragraph in `execution-manifest.md`** immediately before the line `### Tier vocabulary (stable — never changes when models churn)`, with one blank line before and after. Paste exactly:

```markdown
**Glob semantics (`write_allowed`, `read_allowed`, `impacted_map.when`).** `*` matches within one path segment (never `/`);
`**` matches across segments; `dir/**` also matches `dir` itself; `?` matches one non-`/` character; `[` and `]` are literal
(no character classes — `app/[locale]/**` is a real directory); matching is anchored to the full repo-relative path. This is
the scope gate's own matcher (`scripts/compound-v-scope-check.py` `matches`), and V-memory's `recall-check` uses
the same matcher — see [`memory.md`](memory.md); the proof is the `parity …` rows of
`python3 scripts/compound-v-memory.py --selftest`.
```

- [ ] **Step 2: Replace the `recall-check` row in `memory.md`** — the ONE physical line that starts with `` | `recall-check --files <glob>… `` — with exactly this one line:

```markdown
| `recall-check --files <glob>… [--k N] [--json]` | **deterministic** recurring-failure → `tighten`/`none`/`unavailable` verdict. Files match lane globs with the same matcher as the scope gate: `*` matches within one path segment (never `/`); `**` matches across segments; `dir/**` also matches `dir` itself; `?` matches one non-`/` character; `[` and `]` are literal (no character classes — `app/[locale]/**` is a real directory); matching is anchored to the full repo-relative path (see [`execution-manifest.md`](execution-manifest.md)). recall-check only: a bare path with no wildcard means "this path or anything under it" (the enforced gate has no such reading). Proof: the `parity …` rows of `python3 scripts/compound-v-memory.py --selftest`. |
```

- [ ] **Step 3: Verify**

```bash
wc -l skills/compound-v/memory.md                                   # 202 — unchanged
grep -c 'matches within one path segment' skills/compound-v/memory.md skills/compound-v/execution-manifest.md   # 1 and 1
grep -c 'the same matcher' skills/compound-v/memory.md skills/compound-v/execution-manifest.md                  # 1 and 1
grep -n -B2 'Glob semantics' skills/compound-v/execution-manifest.md | head -5   # preceded by a blank line, after the Per-job fields prose
git diff --stat 16786b7 -- skills/compound-v/memory.md skills/compound-v/execution-manifest.md   # 2 files; memory.md 1 insertion 1 deletion
```

- [ ] **Step 4: Commit**

```bash
git add skills/compound-v/memory.md skills/compound-v/execution-manifest.md
git commit -m "docs(compound-v): one glob contract for the scope gate and recall-check, stated in both files (attempt 3, exact text)"
```

### Task R: `spec-review-1`

- Create: `docs/superpowers/dogfood/2026-09-03-epic-gp-matcher-docs-r3-review-1.md`. Follow the `spec-reviewer` agent definition. SPEC: every row of the r2 review's §1.3 constraint table re-checked; QUALITY: `git diff 16786b7 -- <two files>` shows exactly one inserted paragraph and one replaced row; INTEGRATION: the rules match `scripts/compound-v-scope-check.py`'s docstring; links resolve. End with `## Verdict` and one line `VERDICT: APPROVED` or `VERDICT: ISSUES`.
