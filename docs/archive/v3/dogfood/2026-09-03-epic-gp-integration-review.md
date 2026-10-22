# Epic `2026-09-03-glob-parity` — final cross-feature integration review

Reviewer: fresh `spec-reviewer` (no build context). Date: 2026-09-03. Decides `final_review`.

## Scope

- **Brief:** `docs/superpowers/execution/epics/2026-09-03-glob-parity/brief.md`
- **F1 `one-matcher`** — `git diff c011d6e -- scripts/compound-v-memory.py` (merged 4bc979a, 42cac01, 70cdfa1)
- **F2 `matcher-docs`** — `git diff 16786b7 -- skills/compound-v/memory.md skills/compound-v/execution-manifest.md` (final state 9cbf3dd; attempts d7dc25d / 887d2f6 reverted by attempt 3)
- Working tree at review time: `git status --porcelain` **empty** — every claim below is read off the committed tree, not a dirty worktree.

**Epic stats** (`python3 scripts/compound-v-epic-state.py --stats --state docs/superpowers/execution/epics/2026-09-03-glob-parity/epic-state.json`), quoted verbatim:

```json
{"epic_id": "2026-09-03-glob-parity", "status": "running", "total": 2, "done": 2, "pending": 0, "running": 0, "failed": 0, "remaining": 0, "blocked": 0}
```

`epic-state.json` also carries `final_review: {"status": "pending"}` and both features `done` — consistent with this review being the outstanding gate.

**V-memory (Step 0).** `search "glob matcher parity scope-check memory" --intent review` returned the F1 plan, the F2 archaeology and the F2 library audit — the last of which pins the exact hazard this epic could have shipped: documenting the recall-only bare-path reading as if the enforced gate had it too would "misstate an enforced rule". That claim is checked below (Criterion 2, item 3) and holds. `recall-check --files scripts/compound-v-memory.py skills/compound-v/memory.md skills/compound-v/execution-manifest.md` returned **`tighten` (2/2)** — prior `blocked` records on `skills/compound-v/execution-manifest.md` (`2026-09-03-v3.4.1-triage-size`) and `skills/compound-v/memory.md` (`2026-09-03-v3.4.5-recall-freshness-r2`). Escalation-only: applied here as an extra scrutiny pass over the two doc files, which is where finding 2 came from. It did not and could not loosen anything.

## Criteria

### Criterion 1 — both selftests pass; parity table ≥ 8 rows with the two named cases

| Check | Evidence | Status |
|---|---|---|
| `/usr/bin/python3 -B scripts/compound-v-memory.py --selftest` | `0 failed` / `all self-tests passed` | PASS |
| `/usr/bin/python3 -B scripts/compound-v-scope-check.py --selftest` | `SELFTEST PASSED` | PASS |
| Parity table ≥ 8 rows | `scripts/compound-v-memory.py:1634-1640` — **10** rows, each run through both `matches` and `_file_matches` (`:1641-1643`) | PASS |
| `app/[locale]/**` present | `:1637` — positive `app/[locale]/page.tsx` **and** negative `app/l/page.tsx` (the char-class reading is what the negative kills) | PASS |
| `src/*.py` vs `src/a/b.py` | `:1635` — `("src/*.py","src/a.py",True)` and `("src/*.py","src/a/b.py",False)` | PASS |

Criterion 1: **met**.

### Criterion 2 — the two merged diffs are coherent with each other

**(a) Six documented rules vs `glob_to_regex` (`scripts/compound-v-scope-check.py:317-375`) vs the parity rows.**

| Rule (docs) | Implemented | Asserted by a parity row |
|---|---|---|
| `*` matches within one segment, never `/` | `:361` → `[^/]*` | `:1635` both directions |
| `**` matches across segments | `:341,358` → `.*` / `(?:.*/)?` | `:1636`, `:1639` (`**/x.py` ~ `x.py`) |
| `dir/**` also matches `dir` | `:347-350` → `(?:/.*)?` | `:1636` `("src/**","src",True)` |
| `?` matches one non-`/` character | `:364-366` → `[^/]` | **none — see Issue 1** |
| `[` / `]` literal | `:367-372` (falls through to `re.escape`) | `:1637` both directions |
| anchored to the full repo-relative path | `:374` `)\Z` + `re.match` at `:381` | `:1638` `README.md` vs `docs/README.md` |

Implementation matches the documented wording six-for-six, and the F2 wording matches `scope-check.py`'s own module docstring (`:120-131`) clause for clause. Five of the six rules have a parity row; `?` has none anywhere in either script.

**(b) The proof pointer names a selftest that exists.** Both docs point at "the `parity …` rows of `python3 scripts/compound-v-memory.py --selftest`". The rows exist and are labelled exactly `parity <pat> ~ <path>` (`scripts/compound-v-memory.py:1642`), and the command runs green. The pointer resolves — with the one-rule caveat in Issue 1.

**(c) recall-check's bare-path reading is documented as recall-only and implemented that way.** `skills/compound-v/memory.md:54` scopes it explicitly — "recall-check only: a bare path with no wildcard means 'this path or anything under it' (the enforced gate has no such reading)". `skills/compound-v/execution-manifest.md:64-68` does **not** claim it for `write_allowed` (grep for "bare" in that file: no hits), so the enforced rule is not misstated. Implementation `scripts/compound-v-memory.py:1112-1121`: `m(changed, g)` first, then the `<g>/**` fallback gated on `"*" not in g and "?" not in g` — literal `[`/`]` correctly still qualify as "no wildcard". Asserted at `:1645-1646`, including the `docs2/a.md` false case that catches a substring regression. Coherent.

Criterion 2: **met except the `?` rule's missing assertion** (Issue 1).

### Criterion 3 — cross-feature seams

| Check | Evidence | Status |
|---|---|---|
| No F2 statement contradicts F1's code | table (a) above; `impacted_map.when` really is resolved with the gate matcher — `scripts/compound-v-fastpath-run.py:265-266,652` refuses "a second, weaker matcher"; the surviving `import fnmatch` at `:108` is used only at `:733` for `TEST_FILE_GLOBS` (test-file naming), not lane globs | PASS, with Issue 2 on `read_allowed` |
| No leftover "§ Job fields" | grep both docs: no hits | PASS |
| No leftover "glob-parity suite" | grep both docs: no hits | PASS |
| No 1170-char table cell | longest cell in `memory.md` is `:54` at **758** chars (the new recall-check row); `execution-manifest.md`'s longest line is `:519` at 1058, untouched by this epic's diff | PASS |
| Links resolve | `memory.md` → `execution-manifest.md`; `execution-manifest.md` → `memory.md`, `../../examples/manifest.example.yaml`, `../../scripts/compound-v-{memory,scope-check}.py` — all exist on disk | PASS |
| `fnmatch` fully removed from the recall path | `import fnmatch` dropped at `scripts/compound-v-memory.py:32`; no `fnmatch` reference remains in that file | PASS |
| Loader hardening is load-bearing, not decorative | `:1668-1687` spies on `spec_from_file_location` and asserts `_sfl_calls == []` — the sibling is provably never executed when the private bytecode cache cannot be made; a verdict-only assertion would pass with the guard deleted | PASS |
| No fabricated metrics / no weakened gates in either diff | neither diff removes, skips or loosens an assertion; F1 adds 13 assertions and deletes none; F2 is prose-only | PASS |

## Seams

The two features meet at exactly one place — the sentence in `execution-manifest.md:64-68` and the row in `memory.md:54` describing what `scripts/compound-v-scope-check.py` `matches` does — and F1 makes that description true for recall by deleting the second matcher rather than by describing it. That is the right direction of fix and the reason there is no drift to find: there is now one implementation and two references to it, not two implementations claimed to agree.

Two defects at the seam, ranked.

**Issue 1 (MEDIUM) — a documented contract clause with zero test coverage, inside the very set of rows both docs advertise as its proof.**
- `skills/compound-v/memory.md:54` and `skills/compound-v/execution-manifest.md:64-65` both state ``?` matches one non-`/` character` as one of the six rules, and both close with "Proof: the `parity …` rows of `python3 scripts/compound-v-memory.py --selftest`".
- `scripts/compound-v-memory.py:1634-1640` — the parity table has no `?` pattern. Neither does `scripts/compound-v-scope-check.py`'s own `_selftest` (`:628`+): the only `?` in that file is the implementation branch at `:364`.
- Consequence: if `?` regressed to cross `/` (drop the `[^/]` at `:364` for `.`), every selftest in this repository still passes green, and the docs would still claim the parity rows prove otherwise. That is precisely the TEST_GAP shape this project's charter exists to refuse — a stated guarantee with nothing that fails when it breaks.
- Fix: one row, e.g. `("src/?.py", "src/a.py", True), ("src/?.py", "src/ab.py", False)` plus a `src/?.py` vs `src/a/b.py` negative, appended at `:1639`. No doc change needed.

**Issue 2 (LOW) — `read_allowed` is named as a subject of "the scope gate's own matcher"; nothing matches it.**
- `skills/compound-v/execution-manifest.md:64` heads the paragraph **"Glob semantics (`write_allowed`, `read_allowed`, `impacted_map.when`)"** and `:67` asserts "This is the scope gate's own matcher (`scripts/compound-v-scope-check.py` `matches`)".
- True for `write_allowed` (`scripts/compound-v-scope-check.py:384-388`) and for `impacted_map.when` (`scripts/compound-v-fastpath-run.py:652`). Not true for `read_allowed`: no matcher in the repository ever evaluates it. `scripts/compound-v-emit-workflow.py:1637-1642` renders those globs verbatim into the worker prompt under the heading "Read-allowed (advisory — git cannot enforce reads)"; `compound-v-validate-manifest.py` only checks the field is a list of strings.
- Consequence: a reader takes the read lane to be evaluated the same way the write lane is enforced. It is prose handed to a model. The doc understates a real asymmetry the codebase is otherwise careful about — the same class of error the F2 library audit warned against, pointed the other way.
- Fix: scope the sentence, e.g. name `read_allowed` as the *stated* semantics for an advisory, unenforced field, or drop it from the paragraph heading.

Neither issue touches Criterion 1 or 3, and neither reflects a defect the per-feature reviews should have caught in isolation — Issue 1 is visible only when the docs' proof claim is read against the table, and Issue 2 only when the docs are read against a third file (`emit-workflow.py`) that is outside both features' lanes.

## Verdict

Criterion 1 met. Criterion 3 met. Criterion 2 met on five of six rules and on both coherence clauses; the sixth rule (`?`) is documented and implemented but asserted nowhere, so the proof pointer both docs publish is not fully earned. `final_review` must **not** be recorded `passed` on this pass.

1. `scripts/compound-v-memory.py:1634-1640` — parity table asserts no `?` pattern, while `skills/compound-v/memory.md:54` and `skills/compound-v/execution-manifest.md:64-65` state the `?` rule and name these rows as its proof; `scripts/compound-v-scope-check.py:364` would regress silently.
2. `skills/compound-v/execution-manifest.md:64,67` — `read_allowed` is claimed to use the scope gate's matcher; nothing evaluates `read_allowed` (`scripts/compound-v-emit-workflow.py:1637-1642` renders it as advisory prompt text, and the gate at `scripts/compound-v-scope-check.py:384-388` reads only `write_allowed`).

VERDICT: ISSUES
