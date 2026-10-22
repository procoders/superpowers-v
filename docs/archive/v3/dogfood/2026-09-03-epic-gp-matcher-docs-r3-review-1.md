# Review Gate — epic `2026-09-03-glob-parity` · F2 `matcher-docs` · attempt 3 · review-1

**Run:** `2026-09-03-glob-parity-matcher-docs-r3` · **Job under review:** `docs-exact`
**Merged commit:** `9cbf3dd28fda5ff3ee948747bfb691be1a6d0c78` (worktree realised `5ec8db5d4ffc61c5301fc3033de6172ba338d1f6`, baseline `5ec8db5`)
**Pre-F2 reference:** `16786b7` — the tree both attempts were supposed to start from
**Spec:** `docs/superpowers/execution/epics/2026-09-03-glob-parity/specs/matcher-docs.md` (+ Amendment, 7 pre-flight amendments, **Amendment 3**)
**Plan:** `docs/superpowers/plans/2026-09-03-epic-gp-matcher-docs-r3.md`
**Prior reviews:** attempt 1 `…-matcher-docs-review-1.md`; attempt 2 `…-matcher-docs-r2-review-1.md`
**Reviewer:** `superpowers-v:spec-reviewer`, three passes, `direct` isolation.

VERDICT: APPROVED

| Pass | Result |
|---|---|
| PASS 1 SPEC | ✅ — requirements 12/12 · every pre-flight amendment satisfied · over-build clean · job acceptance met |
| PASS 2 QUALITY | ✅ — no regression · no fabricated claim · no reward-hacking · both r2 QUALITY findings closed |
| PASS 3 INTEGRATION | ✅ — no partition leak · seams hold · build green · floor + impacted ran, exit 0 · feature AC 3/3 met (one clause superseded, see below) |

**Headline:** attempt 3 ran the reset. `git checkout 16786b7 --` undid both prior attempts, and the
paragraph and the row went in **verbatim** — character-for-character identical to the text the
manifest's job body carries. Every one of the five constraint rows that attempt 2 left open is now
closed, `wc -l skills/compound-v/memory.md` is back to **202**, and the net diff against `16786b7`
is exactly one inserted paragraph and one replaced row.

**One thing to fix in the manifest, not in the code:** `acceptance_criteria` #3 still carries r2's
superseded 465-character ceiling. See §3.4.

---

## Recall

```
python3 scripts/compound-v-memory.py search "glob semantics matcher parity docs scope gate" --intent review --top 8
```

8 hits, all this feature's own substrate: the 1C library audit and its `python-tooling` knowledge-base
entry, the 1A archaeology doc, the F1 `one-matcher` plan, and the three F2 plans (attempts 1–3).
Nothing recalled contradicts the spec; no settled decision is re-litigated here.

One recalled item is load-bearing and is used in PASS 2.4 —
`docs/superpowers/library-audit/2026-09-03-epic-gp-matcher-docs.md` § 3:

> a bare `dir` entry there matches only the literal string `dir`, never its contents, unless
> written as `dir/**`. Documenting this backwards — implying `write_allowed` also treats a bare
> path as recursive — would misstate an **enf**[orced gate]

That hazard is **avoided**: the bare-path reading appears only in `memory.md`, explicitly fenced as
"recall-check only … (the enforced gate has no such reading)", and the `execution-manifest.md`
paragraph does not mention it at all.

```
python3 scripts/compound-v-memory.py recall-check --files skills/compound-v/memory.md skills/compound-v/execution-manifest.md
→ tighten (2/2 match)
  evidence: 2026-09-03-v3.4.1-triage-size/results/test-scope.json      (blocked on execution-manifest.md)
            2026-09-03-v3.4.5-recall-freshness-r2/results/docs-2.json  (blocked on memory.md)
  recommend (conservative-only): force_worktree, extra_review_pass, fold_into_task0
```

Two of the three were already honoured: `docs-exact` ran at `isolation: worktree`, and this review
pass is the extra pass. `state.json` records the same verdict, computed at emit time
(`jobs.docs-exact.recall_check.verdict: "tighten"`, `match_count: 2`, `recall_check_ms: 112`).
Recall is evidence, never routing authority — it decided nothing below, escalated nothing further,
and loosened nothing.

---

## SPEC

### 1.1 Scope lock — clean

`results/docs-exact.json` → `gate_receipt.verdict: "pass"`, git-derived, baseline `5ec8db5`,
`changed` = exactly `skills/compound-v/execution-manifest.md` and `skills/compound-v/memory.md`,
`violations: []`, `blocked: false`. `git show 9cbf3dd --stat` confirms the merge carried those two
files and nothing else. `git diff 16786b7 --stat -- skills/compound-v/` shows the same two files.
Working tree at review time holds only this review job's own bookkeeping
(`jobs/spec-review-1.baseline`, `jobs/spec-review-1.test-contract.json`, `preexisting/`, `state.json`).
**No SCOPE_LOCK_VIOLATION.**

### 1.2 Spec coverage

| Spec requirement | Implemented in | Status |
|---|---|---|
| Step 0 — reset both files to `16786b7` | net diff vs `16786b7` is 8 insertions / 1 deletion; every attempt-1 and attempt-2 hunk is gone (merge commit removes 14 lines) | ✅ |
| `wc -l skills/compound-v/memory.md` = 202 (unchanged from `16786b7`) | measured **202**; `git show 16786b7:… \| wc -l` → **202** | ✅ |
| Six-rule sentence in `execution-manifest.md` | `execution-manifest.md:64-69` | ✅ |
| Six-rule sentence in `memory.md` | `memory.md:54` | ✅ |
| Stated **once** per file (no second description) | `grep -c 'matches within one path segment'` → `1`, `1` | ✅ |
| Both files contain "the same matcher" | `grep -c` → `1`, `1` | ✅ |
| `grep -n fnmatch` finds nothing in either file | no output, exit 1 | ✅ (vacuous per pre-flight #7) |
| Each file names the other | `execution-manifest.md:68` → `[memory.md](memory.md)`; `memory.md:54` → `[execution-manifest.md](execution-manifest.md)` | ✅ |
| `memory.md` adds the recall-only bare-path reading | `memory.md:54` — "recall-check only: a bare path with no wildcard means \"this path or anything under it\" (the enforced gate has no such reading)" | ✅ |
| Proof pointer, the amendment's exact phrase | `grep -c 'parity …'` → `1`, `1`; both read "the `parity …` rows of `python3 scripts/compound-v-memory.py --selftest`" | ✅ |
| `lint-frontmatter.py` clean | re-ran: exit **0** | ✅ |
| Every relative link resolves | scripted check over every non-http `[…](…)` target in both files: **none broken** | ✅ |

**No SPEC_GAP.**

**Verbatim, measured — not judged.** I parsed the manifest's `jobs[docs-exact].body`, extracted the
six paragraph lines and the one table row it dictates, and compared them to what landed:

```
paragraph verbatim: True      (execution-manifest.md:64-69 vs job body, list-equal, line by line)
row verbatim:       True      (memory.md:54 vs job body, string-equal)
blank before: ''   blank after: ''   next line: '### Tier vocabulary (stable — never changes when models churn)'
```

This is the constraint both prior attempts broke. It is now met exactly.

### 1.3 Every constraint row of the r2 review's §1.3, re-checked

| Source | Constraint | r2 | r3 | Evidence |
|---|---|---|---|---|
| Pre-flight #1 | Paragraph after "Per-job fields", **before** `### Tier vocabulary`, **never inside the table** | ❌ | ✅ **CLOSED** | `grep -n '^\*\*Glob semantics'` → **64**; `### Tier vocabulary` → **71**; line 63 blank, 70 blank. The table's last row ends at `:58`; the footnote `:60` and trailing paragraph `:62` are untouched. The paragraph starts a line of its own, so it is not a cell. |
| Pre-flight #2 | `memory.md` is a same-line-count replacement of the `recall-check` row — one line in, one out | ❌ | ✅ **CLOSED** | `git diff 16786b7 -- memory.md` → **1 insertion, 1 deletion**, the replaced line being `memory.md:54`, the row the spec names. `wc -l` **202 → 202**. No blank line added or removed, so no `architecture.md` anchor into this file moved. |
| Pre-flight #3 | The bare-path reading must **not** be implied for `write_allowed`/`read_allowed` | ✅ | ✅ **still closed** | The `execution-manifest.md` paragraph never mentions it. `memory.md:54` states it as "recall-check only … (the enforced gate has no such reading)". Matches `scripts/compound-v-memory.py:1115-1123` (`_file_matches` adds `<g>/**` only for wildcard-free globs) against `compound-v-scope-check.py` `is_allowed`, which has no such branch. |
| Pre-flight #4 | Six-rule sentence **character-identical** in both files | ✅ | ✅ **still closed** | Extracted both spans and compared after unwrapping the manifest paragraph's ≤120 line breaks to single spaces: **identical: True**. Each file then adds its own one sentence, exactly as the amendment allows. |
| Pre-flight #5 | Proof pointer by name: "the `parity …` rows of `python3 scripts/compound-v-memory.py --selftest`" | ⚠️ | ✅ **CLOSED** | Present verbatim in both (`memory.md:54`; `execution-manifest.md:68-69`, split by the ≤120 wrap — `grep -c 'parity …'` → `1`, `1`). r2's weaker "carries a glob-parity suite" wording is gone. And the pointer is **true**: `--selftest` prints 10 rows named `parity …`. |
| Pre-flight #6 | New `execution-manifest.md` prose ≤ 120 chars/line; `memory.md` row ≤ the file's longest existing line | ❌ / ✅ | ✅ / **superseded** | Paragraph line lengths: **110, 113, 115, 114, 115, 50** — all ≤ 120 (r2 was a single 1170-char cell). The row is **750 characters** (758 bytes) against `16786b7`'s longest line of 465; **Amendment 3** explicitly outranks this clause and sets the ceiling at **800**. 750 < 800. |
| Pre-flight #7 | `lint-frontmatter` + `grep fnmatch` are not proof of work | (noted) | (noted, and **acted on**) | Both still vacuous for these two files — but r3's `floor_command` no longer relies on them: it greps the phrase counts, asserts `wc -l` = 202, and asserts the `^**Glob semantics` line anchor. r2 finding #8 is closed; see §3.3. |
| Plan, Global Constraints | The paragraph and the row pasted **verbatim**, no paraphrase | ❌ | ✅ **CLOSED** | Programmatic compare against `jobs[docs-exact].body`: paragraph `True`, row `True`. The manifest's own `full_command` grep (`matches within one path segment`) — which detected r2's paraphrase — now passes: `1`, `1`. |

**8 of 8 rows closed or still-closed. No CONSTRAINT_VIOLATION.**

### 1.4 Job-level acceptance (`docs-exact`'s own narrow `acceptance`)

| Clause | Status | Measurement |
|---|---|---|
| `grep -c 'matches within one path segment'` = 1 per file | ✅ | `1`, `1` |
| `wc -l memory.md` = 202 | ✅ | `202` |
| `git diff --stat 16786b7 --` shows memory.md 1 insertion 1 deletion | ✅ | `memory.md \| 2 +-` |
| The paragraph starts a line of its own before `### Tier vocabulary` | ✅ | `:64` paragraph, `:71` heading |

Unlike attempts 1 and 2 — where the narrow acceptance passed while the feature acceptance failed —
the narrow list and the feature list now agree.

### 1.5 Over-build — clean

Two edits, no new sections, no speculative helpers, no extra cross-reference beyond the one each
file owes the other. The paragraph's one addition over the spec's literal wording — naming
`impacted_map.when` alongside `write_allowed`/`read_allowed` — is not an over-build: it is a true
statement of the same matcher's third caller (`scripts/compound-v-fastpath-run.py:672`,
`if mod.matches(path, when)`), verified below. **No OVER_BUILD.**

---

## QUALITY

Everything found is reported here, ranked. Nothing is withheld for a later round.

### 2.1 Code quality — clean, and both r2 findings are closed

- **r2 QUALITY #1** (1170-character table cell at `execution-manifest.md:53`) → **CLOSED.** The
  text is now a findable, six-line, wrapped paragraph at `:64-69`; `grep 'Glob semantics'` locates it.
  The `write_allowed` row at `:53` is back to its one-sentence pre-F2 form.
- **r2 QUALITY #2** (`memory.md` pointing at a nonexistent "§ **Job fields**") → **CLOSED** by the
  reset: `grep -n 'Job fields' skills/compound-v/memory.md` → no match. Those lines were attempt 1's
  and are gone.
- **r2 QUALITY / adjacent** (`memory.md:54` documented only `tighten`/`none`, while the code also
  returns `unavailable`) → **CLOSED.** The replaced row now reads
  `` `tighten`/`none`/`unavailable` ``, matching `scripts/compound-v-memory.py:1134` and the
  manifest's own `acceptance_criteria`.

**No QUALITY issue.**

### 2.2 No regression — clean

`lint-frontmatter.py` → exit **0**. Every relative link in both files resolves (scripted, both
files), so the CI dead-link scan has nothing to catch. `memory.md` line count unchanged at 202, so
no line-number anchor into it moved — `docs/superpowers/architecture/architecture.md`'s
`memory.md:70-80` reference still points where it did. In `execution-manifest.md` the paragraph is
appended after the last pre-existing content of the "Per-job fields" section, shifting only
`### Tier vocabulary` and below by 7 lines; no committed doc anchors line numbers into that file's
tail. Documentation-only diff, no behaviour changed.
`python3 scripts/compound-v-memory.py --selftest` → **0 failed**. **No REGRESSION.**

### 2.3 Test alignment

Each MUST has a guard that fails if it breaks, and the guards are in the **floor**, so they run at
every tier:

| MUST | Guard | Would fail if broken? |
|---|---|---|
| Six-rule sentence present, exactly once, in both files | `floor_command` clause 1 (`grep -c … = 1`) | yes |
| "the same matcher" present in both | `floor_command` clause 2 | yes |
| `memory.md` stays 202 lines (same-line-count replacement) | `floor_command` clause 3 | yes |
| The paragraph is not inside a table | `floor_command` clause 4 (`grep -q '^\*\*Glob semantics'`) | yes |
| Verbatim identity with the dictated text | partially — the floor greps the sentence, not the whole block | see note |

Re-ran the floor verbatim against the merged tree: **exit 0**. **No TEST_GAP.**
*Note, non-blocking:* a paraphrase that preserved the grepped sentence would still slip past the
floor. Full verbatim identity was checked here by hand (§1.2) and is not machine-encoded. That is
acceptable for a one-shot docs task; it is not a defect of this diff.

### 2.4 Fabricated claims — clean

No number is printed, logged or documented by this diff, so there is no cost or savings figure to
fabricate. Every factual claim the new text makes was verified against the code, not taken on
assertion:

| Claim (both files) | Code | ✓ |
|---|---|---|
| `*` matches within one path segment (never `/`) | `glob_to_regex` emits `[^/]*` for a single `*` — `compound-v-scope-check.py:361` | ✅ |
| `**` matches across segments | `.*` — `:349` | ✅ |
| `dir/**` also matches `dir` itself | `out[-1] = "(?:/.*)?"` — `:343` | ✅ |
| `?` matches one non-`/` character | `[^/]` — `:366` | ✅ |
| `[` and `]` are literal; `app/[locale]/**` is a real directory | deliberate fall-through to `re.escape(c)` — `:367-374`, with the rationale in the comment | ✅ |
| Matching is anchored to the full repo-relative path | `(?s:` … `)\Z` with `re.match` — `:328`, `:375`, `:380` | ✅ |
| "This is the scope gate's own matcher (`compound-v-scope-check.py` `matches`)" | `matches()` at `:376-379` | ✅ |
| "V-memory's `recall-check` uses the same matcher" | `_file_matches` calls `_scope_matches()`, which `getattr`s `matches` from that file — `compound-v-memory.py:1105-1123` | ✅ |
| The rules govern `impacted_map.when` too | `compound-v-fastpath-run.py:672` `if mod.matches(path, when)`, with the "one path-glob authority" rationale at `:266` | ✅ |
| recall-check only: a bare wildcard-free path means "this path or anything under it" | `compound-v-memory.py:1121` (`"*" not in g and "?" not in g` → `g.rstrip("/") + "/**"`), asserted by the selftest row `bare dir == dir/**` | ✅ |
| Verdicts are `tighten`/`none`/`unavailable` | `compound-v-memory.py:1134` returns `unavailable` | ✅ |
| Proof: the `parity …` rows of `--selftest` | 10 rows named `parity …` in the live selftest output | ✅ |

**No FABRICATED_METRIC.**

### 2.5 Reward-hacking — clean

`git show 9cbf3dd --stat` → two `.md` files, 10 insertions, 14 deletions. No test, spec, scorer,
grader, threshold or skip marker is in the diff. The `test_contract` did change between r2 and r3,
and it moved **strictly stricter** — r2's floor was `lint-frontmatter.py` (vacuous for these files);
r3's floor greps the phrase counts, the 202-line count and the paragraph anchor. It was authored by
the orchestrator before dispatch and is not part of this diff. The 14 deletions are the *removal of
the two earlier attempts' text* by the mandated `git checkout 16786b7 --`, verified by the net diff
against `16786b7` being 8 insertions / 1 deletion. **No REWARD_HACK.**

### 2.6 Confirmed-blocker integrity

**n/a** — no `blocked_external` verdict, no `done_with_blockers` terminal. `state.json`:
`docs-exact` `status: "done"`, `total_retries: 0`, `circuit_open: {}`, `escalated_to: null`,
`cooldowns: {}`. No frozen arbiter audit is in play for F2 attempt 3.

---

## INTEGRATION

### 3.1 Partition integrity — clean

One implementation job, two files, both inside `write_allowed`, git-derived gate `pass`,
`violations: []`. `max_parallel: 2` but wave 1 held only `docs-exact`, so there is no cross-job
seam to leak through. No barrel, registry or type co-edited. **No PARTITION_LEAK.**

### 3.2 Cross-artifact agreement — the three statements of one contract

The contract is now stated in three places. They must agree, and they do:

| Rule | `compound-v-scope-check.py` docstring `:120-130` | `execution-manifest.md:64-69` | `memory.md:54` | Agree? |
|---|---|---|---|---|
| `*` does not cross `/` | ✅ `:122` | ✅ | ✅ identical text | ✅ |
| `**` crosses segments | ✅ `:123` | ✅ | ✅ | ✅ |
| `dir/**` also matches `dir` | ✅ `:124` | ✅ | ✅ | ✅ |
| `?` = one non-`/` char | ✅ `:125` | ✅ | ✅ | ✅ |
| `[` / `]` literal, `app/[locale]/**` real | ✅ `:126-129` | ✅ | ✅ | ✅ |
| Anchored to the full repo-relative path | ✅ `:130` | ✅ | ✅ | ✅ |
| Bare path = this path or anything under it | n/a (recall-side sugar, `compound-v-memory.py:1121`) | absent — correctly | ✅ stated, fenced as recall-only | ✅ |

**No INTEGRATION_MISMATCH.** Two notes, neither charged against this diff:

1. The docs deliberately no longer claim the `**/x` ⇒ `x` behaviour that attempt 2 stated as
   "rule 4". It is real (`compound-v-scope-check.py:348`, selftest row `parity **/x.py ~ x.py`) and
   is simply not part of the six-rule contract the spec fixed. Dropping it is spec-faithful, not a loss.
2. `execution-manifest.md:64` names `impacted_map.when` as a third field governed by these
   semantics — true (`compound-v-fastpath-run.py:672`) and stated in neither of the other two
   places. The docs are now the most complete statement of the contract.

### 3.3 Build green, and the tests the tier owed

`triage.tier: SCOPED`, with a declared, non-empty `impacted_map` (one rule, `when: skills/**/*.md`).
Both changed paths match it, so **no changed path is unmapped**: the referencing heuristic is not
reached, and `full_command` is **not owed** at SCOPED. What is owed is the unconditional floor plus
the impacted set — and that is exactly what ran.

Evidence read from `results/docs-exact.json`, not from prose:

| Field | Value | Verdict |
|---|---|---|
| `tests.command` | 3 commands, newline-separated: the floor, plus the `impacted_map` command resolved once per changed path | ✅ non-empty |
| `tests.exit_code` | `0` | ✅ green |
| `tests.scope` | `impacted` | ✅ exactly what SCOPED owes here |
| `tests.selected_count` | `3` (commands, not cases) | ✅ consistent |

**No NO_TEST_EVIDENCE. No BUILD_RED.** Independently re-run by this reviewer on the merged tree:

- the declared `floor_command`, verbatim → **exit 0** (`FLOOR_OK`)
- `/usr/bin/python3 -B scripts/lint-frontmatter.py` → **exit 0**
- the declared `full_command`'s content half (`grep -c 'matches within one path segment'`) → `1`, `1`
  — **it now passes**, unlike on r2's tree, where it was the machine-checkable proof of the paraphrase
- `python3 scripts/compound-v-memory.py --selftest` → **0 failed**, all self-tests passed, including
  the 10 `parity …` rows the new text points at

r2's finding #8 — "move the content grep out of `full_command`, or SCOPED will keep running only
vacuous commands" — was **acted on** by this manifest: the phrase counts, the 202-line assertion and
the paragraph-anchor check are all in `floor_command`, which runs unconditionally. The SCOPED run
was therefore substantive, not vacuous.

### 3.4 Feature acceptance criteria

| # | Manifest `acceptance_criteria` | Evidence | Status |
|---|---|---|---|
| 1 | `grep -c 'matches within one path segment'` = 1 for each file; `grep -c 'the same matcher'` = 1 and 1; `wc -l memory.md` = 202 (unchanged from `16786b7`) | `1`,`1` · `1`,`1` · `202`, and `git show 16786b7:… \| wc -l` → `202` | ✅ |
| 2 | `git diff 16786b7 --` shows exactly one inserted paragraph (before `### Tier vocabulary`, not inside any table) and one replaced row (1 insertion, 1 deletion in `memory.md`); nothing else differs in those files | `--stat` → `execution-manifest.md \| 7 +++++++`, `memory.md \| 2 +-`. The manifest hunk is the 6-line paragraph plus its trailing blank, inserted at `:64` with `### Tier vocabulary` at `:71`; `grep -n '^\*\*Glob semantics'` → `64`, so it is not a cell. The `memory.md` hunk replaces `:54` only. Two hunks total, nothing else. | ✅ |
| 3 | Every relative link in both files resolves; the paragraph lines are ≤ 120 characters; the `memory.md` row is not longer than the file's longest pre-existing line (465) | Links: **none broken** (scripted, both files) ✅ · paragraph lines **110/113/115/114/115/50** ✅ · row **750 characters** vs 465 — **superseded by Amendment 3**, ceiling 800; 750 < 800 ✅ | ✅ (third clause superseded) |

**3 of 3 met.**

**Recorded, and deliberately NOT charged as an ACCEPTANCE_GAP — a manifest-text defect, fix before reuse.**
`acceptance_criteria` #3's third clause ("not longer than the file's longest pre-existing line (465)")
is r2 text that Amendment 3 explicitly overrode *before this run was emitted*: "Amendment 4 … outranks
amendment 6's 'row ≤ the file's longest existing line' … The `memory.md` row may therefore exceed 465
characters; the ceiling is 800." The same manifest's own `jobs[docs-exact].body` encodes the override —
"the row is ~750 characters and that is expected — spec amendment 3" — so the manifest contradicts
itself, and no worker could satisfy both halves. The governing spec resolves it, and the shipped row
(750, under the 800 ceiling) is what the spec and the job body both ordered. Charging the implementer
for the manifest author's stale parenthetical would be a review error of the same species as demanding
`full_command` of a fully-mapped SCOPED job. **Action: amend `acceptance_criteria` #3 to the 800-character
ceiling before this manifest is copied for any further attempt** — r2's lesson was not to leave two
authorities disagreeing, and this is the last place they still do.

---

## Status of every r2 finding

| # | r2 finding | r3 |
|---|---|---|
| 1 | **SPEC_GAP** — plan Step 0 never executed; attempts stacked instead of resetting | ✅ **CLOSED** — reset ran; net diff vs `16786b7` is 8 insertions / 1 deletion; `wc -l memory.md` 213 → **202** |
| 2 | **CONSTRAINT_VIOLATION** #1 — text inside the `write_allowed` table cell, no paragraph | ✅ **CLOSED** — `execution-manifest.md:64-69`, own lines, before `### Tier vocabulary` at `:71` |
| 3 | **CONSTRAINT_VIOLATION** #6 — 1170-character line vs ≤ 120 | ✅ **CLOSED** — 110/113/115/114/115/50 |
| 4 | **CONSTRAINT_VIOLATION** #2 — line count 202 → 213, spec's row at `:54` never touched | ✅ **CLOSED** — `:54` replaced in place, 1 in / 1 out, 202 lines |
| 5 | **CONSTRAINT_VIOLATION** (verbatim) — paragraph and row paraphrased | ✅ **CLOSED** — programmatic compare against `jobs[docs-exact].body`: both `True` |
| 6 | **QUALITY** — `memory.md` cites a nonexistent "§ Job fields" | ✅ **CLOSED** — removed by the reset; `grep 'Job fields'` → no match |
| 7 | **QUALITY / adjacent** — row documented `tighten`/`none`, code also returns `unavailable` | ✅ **CLOSED** — row now reads `tighten`/`none`/`unavailable` |
| 8 | **Manifest note** — content grep only in `full_command`, so SCOPED ran vacuously | ✅ **CLOSED** — the grep, the line count and the paragraph anchor are in `floor_command`, which runs unconditionally |
| — | Pre-flight #5 proof pointer (r2: ⚠️ weaker wording) | ✅ **CLOSED** — the amendment's exact phrase in both files |

**8 of 8 r2 findings closed, plus the r2 warning.** Nothing regressed.

---

## Verdict

VERDICT: APPROVED

**PASS 1 SPEC** — requirements 12/12 · all 8 constraint rows of the r2 §1.3 table closed or
still-closed · paragraph and row **verbatim** against the dictated text · over-build clean · job
acceptance 4/4.

**PASS 2 QUALITY** — both r2 QUALITY findings and the adjacent one closed · no regression (links
resolve, `lint-frontmatter` 0, selftest 0 failed, no anchor moved) · every MUST guarded by the
unconditional floor · no fabricated claim (all 12 factual statements verified against
`compound-v-scope-check.py`, `compound-v-memory.py` and `compound-v-fastpath-run.py`) · no
reward-hacking (the contract moved stricter, and it is not in this diff).

**PASS 3 INTEGRATION** — no partition leak · all three statements of the glob contract agree, and
the docs are now the most complete of them · build green (evidence: `floor_command` exit 0,
`lint-frontmatter.py` exit 0, `--selftest` 0 failed) · floor + impacted ran, `exit_code: 0`,
`scope: impacted` — exactly what SCOPED owed · feature AC 3/3.

**Scope lock:** respected — gate `pass`, git-derived, `violations: []`, confirmed at the seam.

**Recall verdict `tighten` was honoured** — `docs-exact` ran at `isolation: worktree` and this extra
review pass ran. It escalated nothing further and loosened nothing; it is cited as evidence in
PASS 2.4 (the library audit's bare-path hazard), never as authority.

**One follow-up, not blocking this feature:** amend the run manifest's `acceptance_criteria` #3 to
Amendment 3's 800-character ceiling, so the manifest stops contradicting its own job body and the
governing spec.
