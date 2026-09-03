# Review Gate — epic `2026-09-03-glob-parity` · F2 `matcher-docs` · attempt 2 · review-1

**Run:** `2026-09-03-glob-parity-matcher-docs-r2` · **Job under review:** `docs-contract`
**Merged commit:** `887d2f68b0b979138d4b3a8c772f2fcc9ae2e97a` (worktree realised `af81480c33442927ec3dc7a87c84f4eca227f40d`, baseline `af81480`)
**Spec:** `docs/superpowers/execution/epics/2026-09-03-glob-parity/specs/matcher-docs.md` (+ Amendment + 7 pre-flight amendments)
**Plan:** `docs/superpowers/plans/2026-09-03-epic-gp-matcher-docs-r2.md`
**Attempt-1 review:** `docs/superpowers/dogfood/2026-09-03-epic-gp-matcher-docs-review-1.md`
**Reviewer:** `superpowers-v:spec-reviewer`, three passes, `direct` isolation.

VERDICT: ISSUES

| Pass | Result |
|---|---|
| PASS 1 SPEC | ISSUES (1 × SPEC_GAP, 4 × CONSTRAINT_VIOLATION) |
| PASS 2 QUALITY | ISSUES (2 × QUALITY) — no fabricated metrics, no reward-hacking, no regression |
| PASS 3 INTEGRATION | ISSUES (2 × ACCEPTANCE_GAP) — build green, test evidence sound, rules technically correct |

**Headline:** attempt 2 closed the two SPEC_GAPs — the six rules and the bare-path reading are now
written down, and they are character-identical across the two files. It closed **none** of the
three CONSTRAINT_VIOLATIONs, and made every one of them worse, because it **never ran the plan's
Step 0**: attempt 1's two hunks were not undone. The new text was appended on top of them, in the
same two wrong places.

---

## Recall

`python3 scripts/compound-v-memory.py search "glob matcher parity docs memory execution-manifest" --intent review --top 8`
returned 8 hits, all of this feature's own substrate: the F2 spec + Amendment, the 1A archaeology
doc, the F1 `one-matcher` archaeology, the 1C library audit, the epic halt page and two
`triage-outcomes.jsonl` records. Nothing recalled contradicts the spec; no settled decision is
re-litigated here.

One recalled item is load-bearing and is used in PASS 3 below —
`docs/superpowers/library-audit/2026-09-03-epic-gp-matcher-docs.md` § 3:

> a bare `dir` entry there matches only the literal string `dir`, never its contents, unless
> written as `dir/**`. Documenting this backwards — implying `write_allowed` also treats a bare
> path as recursive — would misstate an **enf**[orced gate]

That hazard is **avoided** by this diff; see acceptance criterion 3 below.

`python3 scripts/compound-v-memory.py recall-check --files skills/compound-v/memory.md skills/compound-v/execution-manifest.md`
→ **`tighten` (2/2 match)**, evidence `2026-09-03-v3.4.1-triage-size/results/test-scope.json`
(blocked on `execution-manifest.md`) and `2026-09-03-v3.4.5-recall-freshness-r2/results/docs-2.json`
(blocked on `memory.md`). Conservative-only recommendations: `force_worktree`,
`extra_review_pass`, `fold_into_task0`. Two were already honoured — `docs-contract` ran at
`isolation: worktree`, and this review pass is the extra pass. Recall is evidence, never routing
authority; it decided nothing below and it loosened nothing.

---

## SPEC

### 1.1 Scope lock — clean

`results/docs-contract.json` → `gate_receipt.verdict: "pass"`, git-derived, baseline `af81480`,
`changed` = exactly `skills/compound-v/execution-manifest.md` and `skills/compound-v/memory.md`,
`violations: []`. `git diff --stat af81480..HEAD` shows those two files plus the pipeline's own
bookkeeping (`jobs/`, `receipts/`, `results/`, `state.json`, `worker-performance.jsonl`), all
written by the pipeline after the gate built its list. **No SCOPE_LOCK_VIOLATION.**

### 1.2 Spec coverage

| Spec requirement | Implemented in | Status |
|---|---|---|
| `grep -n fnmatch` finds nothing in either file | `grep -n fnmatch …` → no output, exit 1 | ✅ (vacuous per pre-flight #7) |
| Both files contain "the same matcher" | `grep -c` → `memory.md:1`, `execution-manifest.md:1` | ✅ |
| The six glob rules stated in both files | `execution-manifest.md:53`; `memory.md:93-99` | ✅ substance |
| That text is **identical** between the two files | normalized character diff: sole delta is the trailing `\|` markdown table-cell terminator on the manifest side (678 vs 676 chars) | ✅ |
| `memory.md` adds the recall-only bare-path reading | `memory.md:98-99` — "`recall-check` additionally reads a wildcard-free bare path as `<path>/**`, sugar the gate itself does not accept" | ✅ |
| Each file names the other as the same contract | `execution-manifest.md:53` → `[memory.md](memory.md)`; `memory.md:89` → `[execution-manifest.md](execution-manifest.md)` | ✅ |
| Proof pointer, verbatim "the parity rows in `python3 scripts/compound-v-memory.py --selftest`" | `grep -c "parity rows"` → **0** in both. Both carry attempt 1's weaker "`--selftest` carries a glob-parity suite" | ⚠️ substance only |
| **Plan Step 0 — undo attempt 1's two hunks (commit `d7dc25d`)** | **not done** | ❌ MISSING |
| `lint-frontmatter.py` clean | ran it: exit 0 | ✅ |
| Every relative link resolves | scripted check over both files: all resolve | ✅ |

**ISSUE: SPEC_GAP — the plan's Step 0 was never executed.**
`docs/superpowers/plans/2026-09-03-epic-gp-matcher-docs-r2.md` Step 0 is the first and mandatory
step: restore the `write_allowed` row to its pre-attempt-1 one-sentence form and delete the four
lines appended to `memory.md`'s trigger bullet, verifying `wc -l skills/compound-v/memory.md`
equals its value at `16786b7`.
Proof it did not happen: `git show 887d2f6` shows the pre-image of `execution-manifest.md:53`
already carrying attempt 1's cross-reference sentence — kept intact, and appended to — and the
`memory.md` half is a pure **+7 line** insertion placed *after* attempt 1's four lines, which are
still present at `memory.md:88-92`.
Measured: `wc -l < skills/compound-v/memory.md` = **213**;
`git show 16786b7:skills/compound-v/memory.md | wc -l` = **202**;
`git show af81480:skills/compound-v/memory.md | wc -l` = **206**.
→ Every constraint violation below descends from this one. Do Step 0 first.

*Note on identity.* The six-rule text is **not** the plan's verbatim sentence — the worker wrote a
numbered paraphrase ("`*` matches **inside** one path segment" against the plan's "**within** one
path segment") and added a seventh rule about `**/`. It is nonetheless byte-identical **between the
two files**, which is what pre-flight #4 requires. The plan's instruction — "Do not paraphrase
anything below. The paragraph and the row are pasted VERBATIM" — was not honoured; see the verbatim
CONSTRAINT_VIOLATION below and the `full_command` evidence in PASS 3.

### 1.3 Audit / pre-flight amendment constraint check

| Source | Constraint | Satisfied? | Evidence |
|---|---|---|---|
| Pre-flight #1 | The paragraph goes **after** the "Per-job fields" section and **before** `### Tier vocabulary` — **never inside the table** | ❌ | `grep -n "Glob semantics" skills/compound-v/execution-manifest.md` → **no match** (exit 1). The text sits inside the `write_allowed` table cell at `execution-manifest.md:53`. `### Tier vocabulary` is at line 64; lines 60-63 (the footnote and the trailing paragraph) are unchanged. |
| Pre-flight #2 | `memory.md` is a **same-line-count** replacement of the `recall-check` row, one line in / one out | ❌ | 206 → **213** lines (+7). The `recall-check` row at `memory.md:54` is **untouched** — it still reads `\| recall-check --files <glob>… \| **deterministic** recurring-failure → tighten/none verdict \|`. The new text landed in the trigger bullet at lines 93-99 instead. |
| Pre-flight #3 | The bare-path reading must not be implied for `write_allowed`/`read_allowed` | ✅ | `execution-manifest.md:53` states it as "One deliberate asymmetry, and the only one: `recall-check` additionally reads … sugar the gate itself does not accept." Correctly disclaimed; the library audit's hazard is avoided. |
| Pre-flight #4 | Six-rule sentence character-identical in both files | ✅ | Normalized diff of the two blocks: sole delta is the table-cell terminator. |
| Pre-flight #5 | Proof pointer by name, not line number | ⚠️ | Both cite "`--selftest` … glob-parity suite" — a name, not a line number, but not the plan's mandated verbatim "the parity rows in `python3 scripts/compound-v-memory.py --selftest`" (`grep -c "parity rows"` → 0, 0). |
| Pre-flight #6 | New `execution-manifest.md` prose wraps at ≤ 120 chars; `memory.md` row ≤ the file's longest existing line | ❌ / ✅ | `awk 'NR==53{print length($0)}' skills/compound-v/execution-manifest.md` = **1170** characters (attempt 1 was 491 — a regression of +679). `memory.md` longest line **465 → 465**, unchanged; the seven added lines run 103-108 chars. |
| Pre-flight #7 | `lint-frontmatter` + `grep fnmatch` are not proof of work | (noted) | Both pass and both are vacuous for these files; no verdict below rests on either. |
| Plan, Global Constraints | The contract and the proof pointer "verbatim in both files" | ❌ | Paraphrased — detected by the manifest's own `full_command`; see PASS 3. |

**ISSUE: CONSTRAINT_VIOLATION** (pre-flight #1 — **not closed from attempt 1, regressed**) —
`skills/compound-v/execution-manifest.md:53`. The amendment forbids exactly this placement and
names the target: after the Per-job fields footnote and trailing paragraph (lines 60-62), before
`### Tier vocabulary` (line 64). There is still no "Glob semantics" paragraph anywhere in the file.
→ Do Step 0, then place the paragraph at line 63.

**ISSUE: CONSTRAINT_VIOLATION** (pre-flight #2 — **not closed from attempt 1, regressed**) —
`skills/compound-v/memory.md`, 202 → 206 → **213** lines, and the `recall-check` row the spec names
(`memory.md:54`) was never touched. Stated as honestly as attempt 1 did: the constraint is
violated, the harm is **not** realised — the deepest live anchor into this file is
`skills/compound-v/memory.md:70-80` (`docs/superpowers/architecture/architecture.md:103`) and the
edit begins at line 93, so no existing anchor shifted. Fix the line count or amend the spec; do not
leave the two disagreeing for a third attempt.

**ISSUE: CONSTRAINT_VIOLATION** (pre-flight #6 — **not closed from attempt 1, regressed**) —
`skills/compound-v/execution-manifest.md:53` is **1170** characters against a ≤ 120 requirement.
A consequence of the placement violation: a markdown table cell cannot be wrapped. Fixed for free
by moving the text out of the table.

**ISSUE: CONSTRAINT_VIOLATION** (plan Global Constraints + Steps 2 and 3 — **new in attempt 2**) —
the paragraph and the row were paraphrased, not pasted. The plan says: "Do not paraphrase anything
below. The paragraph and the row are pasted VERBATIM. If you believe a constraint cannot be met,
stop, do not improvise, and say so in your summary." The worker's summary records no such stop.
The divergence is mechanically detectable: the manifest's `test_contract.full_command` greps for
`matches within one path segment` and the file says `matches inside one path segment` — see PASS 3.

### 1.4 Job-level acceptance (`docs-contract`'s own narrow `acceptance`)

| Job acceptance clause | Status | Command |
|---|---|---|
| `grep -c "the same matcher"` prints 1 for each file | ✅ | → `1`, `1` |
| `grep -n fnmatch` on both prints nothing | ✅ | → no output |
| No other section changed; `git diff --stat` shows only the two files, one hunk region each | ✅ | `git show 887d2f6 --stat` → 2 files, 8 insertions, 1 deletion |
| lint-frontmatter clean | ✅ | exit 0 |

As in attempt 1, the job's **narrow** acceptance passes in full while the **feature** acceptance
fails. That narrow list still cannot see placement, line count, wrapping, or verbatim identity.

### 1.5 Over-build

**Clean.** Two edits, no new sections, no speculative helpers, no extra cross-references. The extra
rule (4) about `**/` matching zero segments is not an over-build — it is a true statement of the
implemented matcher (`glob_to_regex` emits `(?:.*/)?` for a leading or mid `**/`,
`scripts/compound-v-scope-check.py:348`) that the scope-check docstring happens to omit.
**No OVER_BUILD.**

---

## QUALITY

Everything found is reported here, ranked. Nothing is withheld for a later round.

### 2.1 Code quality

**ISSUE: QUALITY** — `skills/compound-v/execution-manifest.md:53`. A **1170-character** table cell,
now carrying eight sentences and a numbered six-item list inside a one-line field-reference row.
Setting the spec aside entirely: it is unfindable prose (no heading, no anchor —
`grep "Glob semantics"` finds nothing), unreviewable in a diff, and it renders as one unbroken
block inside a three-column table. Attempt 1 was flagged for this at 491 characters; the fix round
more than doubled it.

**ISSUE: QUALITY** (**carried over from attempt 1, not closed**) —
`skills/compound-v/memory.md:89-90` still points at
"[`execution-manifest.md`](execution-manifest.md) § **Job fields**". No section by that name
exists; the heading is `## Per-job fields (jobs[])` at `execution-manifest.md:38`. The link
resolves (it is a bare file link); the section name it advertises does not.

*Adjacent, non-blocking, worth one line:* `memory.md:54` documents the `recall-check` verdicts as
`tighten`/`none`, while the code also returns `unavailable`
(`scripts/compound-v-memory.py:1134`, asserted at `:1655` and `:1681`; the manifest's own
`acceptance_criteria` #2 names all three). The in-place rewrite the spec ordered for that row
would have fixed this for free; skipping the row left it wrong.

### 2.2 No regression — clean

`lint-frontmatter.py` exits 0. Every relative link in both files resolves (scripted check over each
`[…](…)` target that is not http/mailto), so the CI dead-link scan
(`.github/workflows/validate.yml:232-274`) has nothing to catch. No line-number anchor into
`memory.md` moved (deepest live anchor `:70-80`; the edit starts at `:93`). Documentation-only diff,
no behaviour changed. `python3 scripts/compound-v-memory.py --selftest` → `0 failed`.
**No REGRESSION.**

### 2.3 Test alignment

Attempt 1's **TEST_GAP is CLOSED** — and it was closed correctly, by the r2 manifest, before this
job ran. `test_contract.full_command` now greps each file for `matches within one path segment` in
addition to `the same matcher`. That guard **does** detect the verbatim divergence: run against the
merged tree it exits **1** with `six-rule sentence missing in skills/compound-v/memory.md`.

What remains is that the guard is not in the **impacted** set the SCOPED tier owed, so it never ran
during the job. That is a manifest-design observation, not a worker failure: the `impacted_map`'s
only rule (`when: skills/**/*.md`) runs `lint-frontmatter.py`, which is vacuous for these two files
— so at SCOPED every command that actually ran was vacuous by construction. **No TEST_GAP is
charged against this diff.** The note belongs to whoever writes attempt 3's manifest: put the
content grep in the `impacted_map` rule, not only in `full_command`, or SCOPED will keep passing
vacuously.

### 2.4 Fabricated metrics — clean

No number is printed, logged or documented by this diff. Every factual claim the new text makes was
verified against the code rather than taken on assertion:

- "(1) `*` matches inside one path segment and never crosses `/`" — `glob_to_regex` emits `[^/]*`
  for a single `*` (`compound-v-scope-check.py:361`). ✅
- "(2) `**` crosses `/`" — `.*` (`:349`). ✅
- "(3) `dir/**` also matches `dir` itself" — `out[-1] = "(?:/.*)?"` (`:343`). ✅
- "(4) a leading or mid `**/` matches zero or more segments, so `**/x.py` matches `x.py`" —
  `out.append("(?:.*/)?")` (`:348`). ✅ (true, and absent from the docstring)
- "(5) `?` matches exactly one non-`/` character" — `[^/]` (`:366`). ✅
- "(6) `[` and `]` are literal, never character classes" — the deliberate fall-through to
  `re.escape(c)` (`:369-374`). ✅
- "Every pattern is fully anchored — a match must consume the whole path" — `(?s:` … `)\Z` with
  `re.match` (`:328`, `:375`, `:380`). ✅
- "`recall-check` additionally reads a wildcard-free bare path as `<path>/**`" —
  `scripts/compound-v-memory.py:1117`, asserted by the selftest row `bare dir == dir/**` at `:1645`. ✅
- "the same matcher … imported … not reimplemented" and "`--selftest` carries a glob-parity suite" —
  the `parity …` rows, `compound-v-memory.py:1632-1646`. ✅

**No FABRICATED_METRIC.**

### 2.5 Reward-hacking — clean

`git show 887d2f6 --stat` — two `.md` files, 8 insertions, 1 deletion. No test, spec, scorer,
grader, threshold or skip marker was touched, loosened or deleted. The `test_contract` did move
between attempts, but it moved **stricter** (attempt 1's `full_command` checked only "the same
matcher"; r2's adds the six-rule grep), it was authored by the orchestrator before dispatch, and it
is not in this diff. **No REWARD_HACK.**

### 2.6 Confirmed-blocker integrity

**n/a** — this run reached no `blocked_external` verdict and no `done_with_blockers` terminal.
`state.json`: `docs-contract` `status: "done"`, `total_retries: 0`, `circuit_open: {}`,
`escalated_to: null`. No frozen arbiter audit is in play for F2 attempt 2.

---

## INTEGRATION

### 3.1 Partition integrity — clean

One implementation job, two files, both inside `write_allowed`, git-derived gate `pass`, no
violations. No barrel or registry co-edited, no type redefined in two places, no seam between
parallel jobs (`max_parallel: 2`, but wave 1 held only `docs-contract`). **No PARTITION_LEAK.**

### 3.2 The quoted rules vs `scripts/compound-v-scope-check.py`'s docstring

This is the comparison the job's acceptance demands. Attempt 1 failed it with zero quoted rules;
**attempt 2 passes it on substance.**

`scripts/compound-v-scope-check.py:120-130`, the module docstring's "Glob semantics" block:

> * `*`   matches within a single path segment (not `/`).
> * `**`  matches across segments, including `/` (recursive).
> * `dir/**` also matches `dir` itself and everything beneath it.
> * `?`   matches one non-`/` character.
> * `[` and `]` are LITERAL. fnmatch character classes are deliberately NOT supported …
> Matching is anchored to the full repo-relative path.

| Rule | `scope-check` docstring | `execution-manifest.md:53` | `memory.md:93-99` | Agree? |
|---|---|---|---|---|
| `*` does not cross `/` | ✅ `:122` | ✅ "(1) … never crosses `/`" | ✅ identical text | ✅ |
| `**` crosses segments | ✅ `:123` | ✅ "(2)" | ✅ | ✅ |
| `dir/**` also matches `dir` | ✅ `:124` | ✅ "(3)" | ✅ | ✅ |
| `**/x` matches `x` (zero leading segments) | ❌ not in prose (code `:348`) | ✅ "(4)" | ✅ | docs **ahead of** the docstring |
| `?` = one non-`/` char | ✅ `:125` | ✅ "(5)" | ✅ | ✅ |
| `[` / `]` literal, `app/[locale]/**` real | ✅ `:126-129` | ✅ "(6)" | ✅ | ✅ |
| Anchored to the full repo-relative path | ✅ `:130` (code `(?s:`…`)\Z`) | ✅ "fully anchored — a match must consume the whole path" | ✅ | ✅ |
| Bare path = this path or anything under it | n/a (recall-side sugar, `compound-v-memory.py:1117`) | ✅ stated **as an asymmetry the gate does not accept** | ✅ | ✅ |

**No INTEGRATION_MISMATCH.** All three statements of the contract now agree, and the two documents
are strictly more complete than the docstring (rule 4). The docstring's own remaining gap — it
states six of the seven behaviours, missing `**/` collapsing to nothing — lies **outside this
feature's write scope** and is recorded here as a follow-up, not charged as a defect of this diff.

### 3.3 Build green, and the tests the tier owed

`triage.tier: SCOPED` with a declared, non-empty `impacted_map` (one rule, `when: skills/**/*.md`).
Both changed paths match that rule, so **no changed path falls outside the map**: the referencing
heuristic is not reached and `full_command` is **not owed** at SCOPED. What is owed is the
unconditional floor plus the impacted set.

Evidence read from `results/docs-contract.json`, not from prose:

| Field | Value | Verdict |
|---|---|---|
| `tests.command` | 3 commands, newline-separated: the floor `lint-frontmatter.py`, plus the `impacted_map` command resolved once per changed path | ✅ non-empty |
| `tests.exit_code` | `0` | ✅ |
| `tests.scope` | `impacted` | ✅ exactly what SCOPED owes here |
| `tests.selected_count` | `3` (commands, not cases) | ✅ consistent with the three resolved commands |

**No NO_TEST_EVIDENCE. No BUILD_RED.** Independently re-run by this reviewer on the merged tree:

- `/usr/bin/python3 -B scripts/lint-frontmatter.py` → exit **0**.
- The declared floor, `bash -c '/usr/bin/python3 scripts/lint-frontmatter.py >/dev/null'` → exit **0**.
- `python3 scripts/compound-v-memory.py --selftest` → `0 failed`, all self-tests passed.

**Recorded, and deliberately NOT charged as BUILD_RED:** the manifest's
`test_contract.full_command` **fails** on the merged tree —

```
six-rule sentence missing in skills/compound-v/memory.md
full_command exit=1
```

— because it greps `matches within one path segment` while both files say `matches inside one path
segment`. Under the tier rule, a SCOPED job with every changed path inside its `impacted_map` does
not owe `full_command`; demanding it here would be a review error. It is cited instead as
**evidence** for the verbatim CONSTRAINT_VIOLATION in PASS 1 — the manifest author's own
machine-checkable encoding of "verbatim" disagrees with what shipped.

### 3.4 Feature acceptance criteria

| # | Manifest `acceptance_criteria` | Evidence | Status |
|---|---|---|---|
| 1 | `grep -n fnmatch` on both prints nothing; both contain "the same matcher" and a pointer to the parity rows in `compound-v-memory.py --selftest` | `grep -n fnmatch` → no output (exit 1); `grep -c "the same matcher"` → `1`, `1`; both cite the `--selftest` glob-parity suite (`execution-manifest.md:53`, `memory.md:91-92`). `grep -c "parity rows"` → `0`, `0`, so the pointer is by description, not the plan's verbatim phrase | ✅ (pointer weak) |
| 2 | `execution-manifest.md` gains **exactly one "Glob semantics" paragraph** after the Per-job fields section, before `### Tier vocabulary`, **never inside the table**, and no other section changes; `memory.md`'s `recall-check` row is rewritten **in place as a same-line-count replacement (`wc -l` unchanged)** with the identical six-rule sentence plus the recall-only bare-path reading, and no other line changes | `grep -n "Glob semantics"` → **no match**; the text is inside the `write_allowed` table cell at `:53`; lines 60-63 unchanged. `memory.md` `wc -l` **206 → 213**; the `recall-check` row at `:54` is untouched; the text went into the trigger bullet at `:93-99` | ❌ **ACCEPTANCE_GAP** |
| 3 | Every relative link resolves; the `execution-manifest.md` paragraph wraps at ≤ **120** characters; the `memory.md` row does not exceed the file's longest pre-existing line; the paragraph does not claim the bare-path reading for `write_allowed`/`read_allowed` | Links ✅ (scripted, both files); `execution-manifest.md:53` = **1170** chars ❌; `memory.md` longest line 465 → 465 ✅; bare-path correctly stated as an asymmetry the gate does **not** accept ✅ | ❌ **ACCEPTANCE_GAP** (line length) |

**1 of 3 feature acceptance criteria met. The feature is not DONE.**

---

## Status of every attempt-1 finding

| # | Attempt-1 finding | Attempt 2 |
|---|---|---|
| 1 | **SPEC_GAP** — six-rule sentence in neither file | ✅ **CLOSED** — present in both, byte-identical between them (`execution-manifest.md:53`, `memory.md:93-99`), and technically correct against `compound-v-scope-check.py`. Not the plan's verbatim wording. |
| 2 | **SPEC_GAP** — bare-path reading missing from `memory.md` | ✅ **CLOSED** — `memory.md:98-99`, and correctly disclaimed for the enforced gate in `execution-manifest.md:53`. |
| 3 | **CONSTRAINT_VIOLATION** #1 — text inside the table instead of a paragraph before `### Tier vocabulary` | ❌ **NOT CLOSED — REGRESSED.** Still in the cell; no "Glob semantics" paragraph exists. |
| 4 | **CONSTRAINT_VIOLATION** #2 — `memory.md` line count 202 → 206 | ❌ **NOT CLOSED — REGRESSED** to **213**; the row the spec names (`:54`) was never rewritten. |
| 5 | **CONSTRAINT_VIOLATION** #6 — `execution-manifest.md:53` 491 chars vs ≤ 120 | ❌ **NOT CLOSED — REGRESSED** to **1170**. |
| 6 | **TEST_GAP** — `full_command` could not detect the missing rules | ✅ **CLOSED** by the r2 manifest, and the strengthened guard works: it exits 1 on the merged tree. (It is not in the SCOPED impacted set, so it did not run during the job.) |
| 7 | **QUALITY** — `memory.md` names a nonexistent "§ Job fields" | ❌ **NOT CLOSED** — `memory.md:89-90` unchanged. |
| 8 | **INTEGRATION_MISMATCH** — zero rules to compare against the code | ✅ **CLOSED** — all three statements now agree; the docs even state one behaviour (`**/` ⇒ zero segments) the docstring omits. |

**2 SPEC_GAPs closed; 3 CONSTRAINT_VIOLATIONs open and all three worse** — because the plan's
Step 0 was skipped and the new text was stacked on attempt 1's.

---

## Verdict

VERDICT: ISSUES

**Blocking, in fix order — attempt 3:**

1. **SPEC_GAP / the root cause** — run the plan's **Step 0** first. `git show d7dc25d -U0`, then
   revert both attempt-1 hunks: restore `execution-manifest.md`'s `write_allowed` row to its
   pre-attempt-1 one-sentence form, and delete the four lines appended to `memory.md`'s trigger
   bullet, so `wc -l skills/compound-v/memory.md` returns to **202**. Then apply Steps 2 and 3.
   Both attempts appended where the plan said replace; nothing below can be fixed while that stands.
2. **CONSTRAINT_VIOLATION** (pre-flight #1) — put the "Glob semantics" paragraph at line 63 of
   `skills/compound-v/execution-manifest.md`, between the trailing paragraph of "Per-job fields"
   and `### Tier vocabulary`; never in the table. `grep -n "Glob semantics"` must find it.
3. **CONSTRAINT_VIOLATION** (pre-flight #6) — wrap that paragraph at ≤ 120 characters. Free once
   (2) is done; impossible while it is a table cell.
4. **CONSTRAINT_VIOLATION** (pre-flight #2) — rewrite the **`recall-check` row at
   `skills/compound-v/memory.md:54`** in place, one line out and one line in, `wc -l` unchanged at
   202. That is the line the spec names; the trigger bullet is not it.
5. **CONSTRAINT_VIOLATION** (verbatim) — paste the plan's Step 2 paragraph and Step 3 row as
   written, character for character. The manifest's `full_command` is the check, and it must exit 0.
   If a constraint genuinely cannot be met, stop and name it — the plan asks for exactly that, and
   no attempt has used it.
6. **QUALITY** — `skills/compound-v/memory.md:89-90`: "§ Job fields" is not a real section; the
   heading is `## Per-job fields (jobs[])` at `execution-manifest.md:38`.
7. **QUALITY / adjacent** — while rewriting `memory.md:54`, `tighten`/`none` should read
   `tighten`/`none`/`unavailable` (`compound-v-memory.py:1134`), matching the manifest's own
   `acceptance_criteria` #2.
8. **Manifest note for attempt 3** (not a defect of this diff) — move the content grep from
   `full_command` into the `impacted_map` rule, or a SCOPED attempt will again run only vacuous
   commands and report `exit_code: 0`.

**Clean:** scope lock (gate `pass`, git-derived, `violations: []`) · over-build · fabricated metrics
(all eight factual claims verified against `compound-v-scope-check.py` and `compound-v-memory.py`) ·
reward-hacking · regressions · relative links · partition integrity · cross-artifact rule agreement ·
test evidence present, `scope: impacted`, `exit_code: 0`, exactly what SCOPED owed · build green.

**Recall verdict `tighten` was honoured** — `docs-contract` ran at `isolation: worktree` and this
extra review pass ran. It escalated nothing further and loosened nothing; it is cited as evidence
in PASS 3 (the library audit's bare-path hazard), never as authority.
