# Review Gate — epic `2026-09-03-glob-parity` · F2 `matcher-docs` · review-1

**Run:** `2026-09-03-glob-parity-matcher-docs` · **Job under review:** `docs-contract`
**Merged commit:** `d7dc25d8cfd84ce5a45fdb3fd0afac838eb362dc` (worktree realised `986ff8f5d8ec76c571b147ed4adf752dae43d560`)
**Spec:** `docs/superpowers/execution/epics/2026-09-03-glob-parity/specs/matcher-docs.md` (+ Amendment + Pre-flight amendments)
**Plan:** `docs/superpowers/plans/2026-09-03-epic-gp-matcher-docs.md`
**Reviewer:** `superpowers-v:spec-reviewer`, three passes, direct isolation.

VERDICT: ISSUES

| Pass | Result |
|---|---|
| PASS 1 SPEC | ISSUES (2 × SPEC_GAP, 3 × CONSTRAINT_VIOLATION) |
| PASS 2 QUALITY | ISSUES (1 × TEST_GAP, 2 × QUALITY) — no fabricated metrics, no reward-hacking |
| PASS 3 INTEGRATION | ISSUES (1 × INTEGRATION_MISMATCH, 2 × ACCEPTANCE_GAP) — build green, test evidence sound |

---

## Recall

`compound-v-memory.py search "glob matcher contract docs memory.md execution-manifest" --intent review --top 8`
returned 8 hits, all of them this feature's own substrate: the F2 spec and its Amendment, the
1A archaeology doc, the plan, and the triage record. No prior decision is re-litigated by this
review, and nothing recalled contradicts the spec.

The recalled Amendment is load-bearing for this review and is quoted verbatim in PASS 1 below —
in particular the archaeology finding that
`grep -n -i 'fnmatch\|glob' skills/compound-v/execution-manifest.md` showed
"the manifest contract never states the glob semantics at all … the semantics live only in
`scripts/compound-v-scope-check.py`'s docstring." That is the condition F2 exists to end, and
PASS 3 finds it still true after the merge.

`compound-v-memory.py recall-check --files skills/compound-v/memory.md skills/compound-v/execution-manifest.md`
returns **`tighten` (2/2 match)** — both target files carry prior `blocked` records
(`2026-09-03-v3.4.1-triage-size/results/test-scope.json` on `execution-manifest.md`,
`2026-09-03-v3.4.5-recall-freshness-r2/results/docs-2.json` on `memory.md`).
Conservative-only recommendations: `force_worktree`, `extra_review_pass`, `fold_into_task0`.
Two of the three were already honoured by the manifest — `docs-contract` ran at
`isolation: worktree`, and this review pass exists. Recall is evidence here, not authority; it
did not decide any verdict below.

---

## SPEC

### 1.1 Scope lock — clean

Gate receipt (`results/docs-contract.json` → `gate_receipt.verdict`) is `pass`, git-derived,
baseline `986ff8f5`. `changed` = exactly `skills/compound-v/execution-manifest.md`,
`skills/compound-v/memory.md`; `violations: []`. `git diff --stat 986ff8f5..d7dc25d8` shows those
two files plus the pipeline's own `epic-state.json` bookkeeping. **No SCOPE_LOCK_VIOLATION.**

### 1.2 Spec coverage

| Spec requirement (Goal / Amendments) | Implemented in | Status |
|---|---|---|
| `grep -n fnmatch` finds nothing in either file | `grep -n fnmatch skills/compound-v/memory.md skills/compound-v/execution-manifest.md` → no output | ✅ (vacuous — pre-flight #7 says so) |
| Both files contain "the same matcher" | `grep -c` → `memory.md:1`, `execution-manifest.md:1` | ✅ |
| Both name the parity proof in `--selftest` | `execution-manifest.md:53`, `memory.md:92` | ✅ |
| Each file names the other as the same contract | `execution-manifest.md:53` → `[memory.md](memory.md)`; `memory.md:88` → `[execution-manifest.md](execution-manifest.md)` | ✅ |
| **The six glob rules stated in both files** (`*` within one segment, `**` across segments, `dir/**` also matches `dir`, `?` one non-`/` char, `[`/`]` literal, anchored to the full repo-relative path) | **(not found in either file)** | ❌ MISSING |
| **`memory.md` adds the recall-only bare-path reading** ("a bare path with no wildcard means this path or anything under it") | **(not found)** | ❌ MISSING |
| `lint-frontmatter.py` clean | ran it: `✅ All frontmatter clean`, exit 0 | ✅ |
| Every relative link resolves | both new links are same-directory siblings that exist | ✅ |

**ISSUE: SPEC_GAP (critical)**
The six-rule sentence — the entire substance of the spec's Goal and of pre-flight amendment #4
("the six-rule sentence is character-identical in both files") — is in **neither** file.
Proof: `grep -n -i -e "across segments" -e "within one segment" -e "repo-relative path" -e "anchored" -e "one non-" skills/compound-v/memory.md skills/compound-v/execution-manifest.md`
prints **nothing**.
What actually shipped is a cross-*reference* only: `execution-manifest.md:53` and `memory.md:88-92`
both say the matcher is shared and selftested, but neither says *what the matcher does*. The
contract is still stated exactly once in the repository — in
`scripts/compound-v-scope-check.py:317-325` — which is precisely the state F2 was written to end.
→ Add the six-rule sentence, character-identical, to both files.

**ISSUE: SPEC_GAP**
`memory.md` was required to add the recall-only bare-path reading (Goal; pre-flight #3).
Proof: `grep -n -i -e "bare path" -e "anything under it" -e "no wildcard" skills/compound-v/memory.md`
prints nothing. The behaviour is real and asserted —
`scripts/compound-v-memory.py:1645` checks `bare dir == dir/**` — and remains undocumented.
→ Add the bare-path sentence to `memory.md` only.

### 1.3 Audit / amendment constraint check

| Source | Constraint | Satisfied? | Evidence |
|---|---|---|---|
| Pre-flight #1 | The `execution-manifest.md` note goes **after** the "Per-job fields" section and **before** `### Tier vocabulary` — the table is contiguous, so it cannot go in a row | ❌ | The text was appended **inside the table**, to the `write_allowed` cell at `execution-manifest.md:53`. `### Tier vocabulary` is at line 64; nothing was added between 63 and 64. |
| Pre-flight #2 | `memory.md` is a **same-line-count** replacement, one line in / one out | ❌ | `git show 986ff8f5:skills/compound-v/memory.md \| wc -l` = **202**; `wc -l < skills/compound-v/memory.md` = **206**. One line removed, five added. |
| Pre-flight #3 | The bare-path reading must not be implied for `write_allowed`/`read_allowed` | ✅ | `execution-manifest.md:53` makes no bare-path claim (it makes no rule claim at all). |
| Pre-flight #4 | Six-rule sentence character-identical in both files | ❌ | See SPEC_GAP above — the sentence exists in neither. |
| Pre-flight #5 | Proof pointer named, not line-numbered | ✅ | Both cite "`compound-v-memory.py --selftest` … glob-parity suite". Weaker than the spec's literal "the `parity …` rows of", but it is a name, not a line number. |
| Pre-flight #6 | New `execution-manifest.md` prose wraps at ≤ 120 chars; `memory.md` row ≤ the file's longest existing line | ❌ / ✅ | `awk` on `execution-manifest.md` line 53 = **491 characters**. `memory.md` longest line before and after = **465** — unchanged, so the `memory.md` half passes. |
| Pre-flight #7 | `lint-frontmatter` + `grep fnmatch` are not proof of work | (noted) | Both pass and both are vacuous for these files; this review does not rest on either. |

**ISSUE: CONSTRAINT_VIOLATION** (pre-flight #1) — `skills/compound-v/execution-manifest.md:53`.
The note is inside the field table, on the `write_allowed` row. The amendment forbids exactly
this and names the target location: after the "Per-job fields" section's footnote and trailing
paragraph, before `### Tier vocabulary` (line 64).
→ Move the paragraph out of the table to lines 62-63.

**ISSUE: CONSTRAINT_VIOLATION** (pre-flight #2) — `skills/compound-v/memory.md`, 202 → 206 lines.
The rationale the amendment gives is that `docs/superpowers/architecture/architecture.md` anchors
line numbers into `memory.md`. Stated honestly: the constraint is violated, the harm is **not**
realised — the deepest live anchor is `skills/compound-v/memory.md:70-80`
(`architecture.md:103`) and the edit begins at line 88, so no existing anchor shifted. Fix the
line count anyway, or amend the spec; do not leave the two disagreeing.

**ISSUE: CONSTRAINT_VIOLATION** (pre-flight #6) — `skills/compound-v/execution-manifest.md:53` is
491 characters against a ≤ 120 requirement. This is a consequence of the placement violation: a
markdown table cell cannot be wrapped.
→ Fixed for free by moving the text out of the table.

### 1.4 Job-level acceptance (`docs-contract`'s own narrow `acceptance`)

| Job acceptance clause | Status | Command |
|---|---|---|
| `grep -c "the same matcher"` prints 1 for each file | ✅ | `grep -c "the same matcher" …` → `1`, `1` |
| `grep -n fnmatch` on both prints nothing | ✅ | `grep -n fnmatch …` → no output |
| Only the two files changed, one hunk region each | ✅ | `git diff --stat 986ff8f5..d7dc25d8` |
| lint-frontmatter clean | ✅ | exit 0 |

The job's **narrow** acceptance passes in full while the **feature** acceptance fails. That is
itself a finding: this acceptance list was written so it can be satisfied without stating a single
glob rule. See TEST_GAP in PASS 2.

### 1.5 Over-build — clean

Nothing was added beyond the two edits. No new sections, no speculative helpers, no extra
cross-references. **No OVER_BUILD.**

---

## QUALITY

Reported in this same pass rather than withheld for a later round: a second review is a fresh
spawn with none of this context, and a finding held back is a finding re-derived from scratch.

### 2.1 Code quality

**ISSUE: QUALITY** — `skills/compound-v/memory.md:88-89`. The new text points at
"[`execution-manifest.md`](execution-manifest.md) § Job fields". There is no section by that name;
the heading is `## Per-job fields (`jobs[]`)` at `execution-manifest.md:38`. The link resolves (it
is a bare file link), but the section it names does not exist as written.

**ISSUE: QUALITY** — `skills/compound-v/execution-manifest.md:53`. A 491-character table cell. Even
setting the spec aside, a four-sentence explanation stuffed into a one-line field-reference row is
unfindable prose and unreviewable in a diff; the pre-flight amendment moved it out of the table for
this reason as well as the structural one.

### 2.2 No regression — clean

`lint-frontmatter.py` exits 0. Both new relative links (`memory.md` ↔ `execution-manifest.md`) are
same-directory siblings that exist, so the CI dead-link scan
(`.github/workflows/validate.yml:232-274`) has nothing to catch. No line-number anchor into either
file moved (verified above). No behaviour changes — this is a documentation-only diff.

### 2.3 Test alignment

**ISSUE: TEST_GAP** — the manifest's `test_contract.full_command` checks only
`grep -q "the same matcher"` in each file. No command anywhere in the contract can detect the
missing six rules or the missing bare-path reading. That is exactly why a job that omitted the
whole substance of the feature reported `tests.exit_code: 0` and `status: "success"`.
→ The guard the requirement needs is a `grep` for the six-rule sentence itself in both files, plus
a check that the two occurrences are byte-identical (pre-flight #4 makes that mechanically
checkable). Add it to `full_command` before the fix round, or the next attempt can pass the same
way.

### 2.4 Fabricated metrics — clean

No numbers are printed, logged or documented by this diff. The two factual claims it does make are
**verified true**, not asserted:

- "imports `compound-v-scope-check.py`'s `matches()` rather than reimplementing it" —
  `scripts/compound-v-memory.py:1060-1113` loads the scope-check module by file spec and hard-fails
  if it "defines no `matches()`".
- "`--selftest` carries a glob-parity suite that fails if the two ever diverge" —
  `scripts/compound-v-memory.py:1632-1646`, the `parity <pat> ~ <path>` rows asserting
  `_scope(path, pat) is want and _file_matches(path, [pat]) is want`, plus the
  `bare dir == dir/**` row.

**No FABRICATED_METRIC.**

### 2.5 Reward-hacking — clean

The diff touches two `.md` files and nothing else — no test, spec, scorer, grader or threshold was
edited, loosened, skipped or deleted. `git diff --stat 986ff8f5..d7dc25d8` confirms. The TEST_GAP
in 2.3 is a pre-existing weakness in the manifest's own contract, authored before the job ran, not
something this diff weakened. **No REWARD_HACK.**

### 2.6 Confirmed-blocker integrity

**n/a** — this run reached no `blocked_external` verdict and no `done_with_blockers` terminal.
`state.json` shows `docs-contract` `status: "done"`, `total_retries: 0`, `circuit_open: {}`.

---

## INTEGRATION

### 3.1 Partition integrity — clean

One implementation job, two files, both inside `write_allowed`, git-derived gate `pass`. No seam,
no barrel or registry co-edited, no type redefined. **No PARTITION_LEAK.**

### 3.2 Cross-artifact comparison — the quoted rules vs. `compound-v-scope-check.py`'s docstring

This is the comparison the job's acceptance demands, and it is where the feature fails hardest.

`scripts/compound-v-scope-check.py:317-325`, `glob_to_regex`'s docstring, states:

> Translate a path glob (with `**`) into a fully-anchored regex string. Hand-rolled rather than
> `fnmatch.translate` so that `*` does NOT cross `/` while `**` does. `dir/**` also matches `dir`
> itself. `[` / `]` are literal (no character classes) so App-Router segments like `app/[locale]`
> match their real on-disk paths.

| Rule | In `scope-check` docstring | In `execution-manifest.md` | In `memory.md` |
|---|---|---|---|
| `*` does not cross `/` | ✅ (:321-322) | ❌ | ❌ |
| `**` crosses segments | ✅ (:321-322) | ❌ | ❌ |
| `dir/**` also matches `dir` | ✅ (:322) | ❌ | ❌ |
| `?` = one non-`/` character | ❌ prose (code only, :364-367 → `[^/]`) | ❌ | ❌ |
| `[` / `]` literal | ✅ (:322-324) | ❌ | ❌ |
| Anchored to the full repo-relative path | ✅ ("fully-anchored", :319; code `(?s:` … `)\Z`, :330/:374) | ❌ | ❌ |
| Bare path = this path or anything under it (recall only) | n/a (recall-side sugar) | correctly absent | ❌ missing |

**ISSUE: INTEGRATION_MISMATCH** — after the merge there are still **zero** quoted rules in either
document to compare against the code. The single source of truth remains
`scripts/compound-v-scope-check.py:317-325`, and that docstring itself states five of the six rules
in prose (`?` is implemented at :364-367 but never written down). A fix round should state all six
in the two docs and, ideally, close the `?` gap in the docstring so the three agree.

### 3.3 Build green and tier-owed tests

Manifest `triage.tier: FULL` with a **declared, non-empty** `impacted_map`
(`when: skills/**/*.md`). Both changed paths — `skills/compound-v/memory.md`,
`skills/compound-v/execution-manifest.md` — match that rule, so no changed path falls outside the
map and `full_command` is **not owed**; the derived-default rule is satisfied by the impacted set
plus the unconditional floor.

Evidence read from `results/docs-contract.json`, not from prose:

| Field | Value | Verdict |
|---|---|---|
| `tests.command` | floor `lint-frontmatter.py` + the two `impacted_map` commands, newline-separated, non-empty | ✅ |
| `tests.exit_code` | `0` | ✅ |
| `tests.scope` | `impacted` | ✅ matches what FULL owes here |
| `tests.selected_count` | `3` (commands, not cases) | ✅ consistent with `resolved_commands` in `jobs/docs-contract.test-contract.json` |

**No NO_TEST_EVIDENCE.** Independently re-run by this reviewer:

- `/usr/bin/python3 -B scripts/lint-frontmatter.py` → `✅ All frontmatter clean`, exit 0.
- The `full_command` equivalent (floor + `grep -q "the same matcher"` in both files) → passed.

**Build is green.** It is green and the feature is still wrong, which is the TEST_GAP of 2.3
restated as evidence.

### 3.4 Feature acceptance criteria

| # | Manifest `acceptance_criteria` | Evidence | Status |
|---|---|---|---|
| 1 | `grep -n fnmatch` on both prints nothing; both contain "the same matcher" and a pointer to the parity rows in `compound-v-memory.py --selftest` | `grep -n fnmatch` → no output; `grep -c "the same matcher"` → `1`,`1`; both cite the `--selftest` glob-parity suite | ✅ |
| 2 | `execution-manifest.md` gains exactly one "Glob semantics" paragraph after the "Per-job fields" section, before `### Tier vocabulary`, **never inside the table**, and no other section changes; `memory.md`'s `recall-check` row is rewritten **in place as a same-line-count replacement (`wc -l` unchanged)** with the identical six-rule sentence plus the recall-only bare-path reading | Text landed **inside** the table at `execution-manifest.md:53`; `memory.md` `wc -l` 202 → 206; the six-rule sentence and the bare-path reading are absent from both files | ❌ **ACCEPTANCE_GAP** |
| 3 | Every relative link resolves; the `execution-manifest.md` paragraph wraps at ≤ 120 characters; the `memory.md` row does not exceed the file's longest pre-existing line; the paragraph does not claim the bare-path reading for `write_allowed`/`read_allowed` | Links ✅; `execution-manifest.md:53` is **491** chars ❌; `memory.md` longest line 465 → 465 ✅; no bare-path claim on `write_allowed` ✅ | ❌ **ACCEPTANCE_GAP** (line length) |

**1 of 3 feature acceptance criteria met. The run is not DONE.**

---

## Verdict

VERDICT: ISSUES

**Blocking, in fix order:**

1. **SPEC_GAP** — the six-rule sentence is in neither file. Add it, character-identical, to
   `skills/compound-v/memory.md` and `skills/compound-v/execution-manifest.md`. This is the feature.
2. **SPEC_GAP** — add the recall-only bare-path reading to `skills/compound-v/memory.md`.
3. **CONSTRAINT_VIOLATION** — move the text out of the `write_allowed` table cell
   (`execution-manifest.md:53`) to a paragraph between line 63 and the `### Tier vocabulary`
   heading at line 64; wrap at ≤ 120 characters. Fixes the 491-character violation too.
4. **CONSTRAINT_VIOLATION** — restore `skills/compound-v/memory.md` to a same-line-count
   replacement (202 lines), or amend the spec. No live anchor shifted, but the spec and the file
   currently disagree.
5. **TEST_GAP** — `test_contract.full_command` cannot detect any of the above. Strengthen it
   (grep the six-rule sentence in both files; assert the two occurrences are identical) before the
   fix round, or the next attempt passes the same way this one did.
6. **QUALITY** — `memory.md:88-89` names a section "§ Job fields" that does not exist; the heading
   is `## Per-job fields (`jobs[]`)`.
7. **INTEGRATION_MISMATCH** — with (1) and (2) done, the three statements of the contract
   (`scope-check` docstring, `execution-manifest.md`, `memory.md`) should agree; consider adding
   `?` = one non-`/` character to `scripts/compound-v-scope-check.py:317-325`, which states five of
   six rules today.

**Clean:** scope lock (gate `pass`, git-derived) · over-build · fabricated metrics · reward-hacking ·
regressions · partition integrity · test evidence present and exit 0 · build green.

**Recall verdict `tighten` was honoured** — `docs-contract` ran in a worktree and this extra review
pass ran. It escalated nothing further and loosened nothing.
