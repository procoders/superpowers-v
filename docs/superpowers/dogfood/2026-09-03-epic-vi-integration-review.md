# Epic `2026-09-03-verification-index` — final cross-feature integration review

Checkpoint stance, PASS 3 (INTEGRATION) only. The two per-feature three-pass reviews already
passed (`docs/superpowers/dogfood/2026-09-03-epic-vi-review-index-review-2.md`,
`docs/superpowers/dogfood/2026-09-03-epic-vi-readme-section-review-2.md`); nothing below re-litigates
their per-feature ACs. This pass gates the composite on the epic brief's three criteria, the
cross-feature seams, and whether the build is actually green.

**Step 0 — V-memory.** `compound-v-memory.py search "dogfood verification index README section epic
integration" --intent review --top 8` returned eight hits, none on this feature (nearest: the
`epic-autonomous-mode` R5 note on gamed PASSes, applied below as the reward-hack lens). The
conservative bridge, `recall-check --files scripts/compound-v-dogfood-index.sh
tests/test-dogfood-index.sh README.md docs/superpowers/dogfood/README.md`, returned verdict `none`
(0/2 match) — no control is escalated on recall grounds, and recall never loosens one. The index is
reported 117 docs behind; noted, stepped past, not a blocker.

---

## Scope (base..HEAD)

`git diff 4f9faac..HEAD --stat` — 36 commits, 130 files, +13333/-19. Head is `d24fcbf`
(`epic(verification-index): F2 readme-section DONE`).

Pipeline bookkeeping (`docs/superpowers/execution/**`, `docs/superpowers/pre-eval/**`) is excluded
per the review brief, except `docs/superpowers/execution/epics/2026-09-03-verification-index/epic-state.json`.
What remains is the reviewable surface:

| Path | Change | Owner |
|---|---|---|
| `scripts/compound-v-dogfood-index.sh` | new, 140 lines | F1 |
| `tests/test-dogfood-index.sh` | new, 180 lines | F1 |
| `docs/superpowers/dogfood/README.md` | new, 40 lines (generated) | F1 output, refreshed by F2 |
| `README.md` | +6 (the `## Verification program` section) | F2 |
| `CHANGELOG.md` | +18 (`[Unreleased]`, findings 85/86/87/89) | carried in |
| `scripts/compound-v-{emit-workflow,epic-state,integration-gate,localize}.py` | +194/-19 | findings 85/86/87/89, landed inside the epic window |
| audits, specs, plans, review files, KB notes | new prose | F1/F2 pre-flights and reviews |

The four `fix(...)` commits (`15ef0ff`, `915686d`, `33ff0bf`, `be44570`) are not epic features. They
are inside `4f9faac..HEAD` because the epic hit each defect while running, so they are in scope for
"is the composite green", not for "did the epic build what it said".

---

## AC 1 — regeneration is byte-identical; README counts equal the footer counts

**The literal bare command was deliberately not run against the checkout** (it would modify a tracked
file during a review). Two equivalent forms were run instead, and `git status --porcelain` was empty
after each.

**(a) Idempotence, live corpus, output redirected out of the tree:**

```
$ bash scripts/compound-v-dogfood-index.sh --dir docs/superpowers/dogfood --out $S/run1/A.md
$ bash scripts/compound-v-dogfood-index.sh --dir docs/superpowers/dogfood --out $S/run1/B.md
$ diff $S/run1/A.md $S/run1/B.md
(no output — rc=0)
```

**(b) Idempotence through the default `--out` path, on a full copy of the corpus:**

```
$ cp docs/superpowers/dogfood/*.md $S/copy/
$ bash scripts/compound-v-dogfood-index.sh --dir $S/copy      # run 1
$ cp $S/copy/README.md $S/copy-run1.md
$ bash scripts/compound-v-dogfood-index.sh --dir $S/copy      # run 2
$ cmp $S/copy-run1.md $S/copy/README.md
(identical)
```

Byte-identical on the second run, both ways. ✅

**(c) The counts.** `README.md:138` states "34 review files, 3 APPROVED". The committed footer of
`docs/superpowers/dogfood/README.md` reads `Reviews: 34 · APPROVED: 3 · ISSUES: 26 · other: 5`.
Equal. ✅

**(d) The committed index is already one row stale** — the seam this epic exists to expose:

```
$ diff docs/superpowers/dogfood/README.md $S/run1/A.md
32a33
> | 2026-09-03 | epic-vi-readme-section | 2 | APPROVED | 2026-09-03-epic-vi-readme-section-review-2.md |
40c41
< Reviews: 34 · APPROVED: 3 · ISSUES: 26 · other: 5
---
> Reviews: 35 · APPROVED: 4 · ISSUES: 26 · other: 5
```

F2's own pass-2 review file landed *after* F2's `index-refresh` job ran, so the index cannot count it.
This was designed and disclosed, not missed: the F2 r2 manifest's `spec-review-2` body instructs the
reviewer to "state plainly that your own review file will not be counted until the next
regeneration", and `README.md:138` says "as of this writing". The F2 spec is equally explicit: "The
numbers must equal the footer at the time of writing."

**(e) This review file makes it two rows stale.** Simulated against a copy, with this document's
actual verdict line:

```
$ cp docs/superpowers/dogfood/*.md $S/sim2/ && printf '**VERDICT: ISSUES**' > $S/sim2/2026-09-03-epic-vi-integration-review.md
$ bash scripts/compound-v-dogfood-index.sh --dir $S/sim2
| 2026-09-03 | epic-vi-integration | 1 | ISSUES | 2026-09-03-epic-vi-integration-review.md |
Reviews: 36 · APPROVED: 4 · ISSUES: 27 · other: 5
```

So: **yes, the footer has to be regenerated once more** after this file lands, and after that
regeneration `README.md`'s "34 review files, 3 APPROVED" matches neither the new footer (36/4) nor the
current one (35/4). It still matches the *committed* footer it was copied from, which is what AC 1
and the F2 spec ask for.

**AC 1 verdict: MET as written.** The equality is a snapshot, honestly labelled, and the regeneration
is genuinely idempotent. Recorded as a non-blocking gap: **nothing enforces the equality after the
fact** — no CI step regenerates the index and compares it to `README.md`, so every future review file
silently widens the drift, and the `as of this writing` disclaimer is the only thing standing between
the drift and a false claim. See issue 2.

---

## AC 2 — every per-feature run reached MERGED with no manual step

Read from each run's `state.json` and from `git log --format='%h %ci %an | %s' 4f9faac..HEAD --reverse`.

| Run | `phase` | `merged_at` | Waves paired with a finalizer commit | Manual steps |
|---|---|---|---|---|
| `…-review-index` (F1 r1) | **DISPATCHED** | absent | no — see below | **2 hand commits** |
| `…-review-index-r2` (F1 r2) | MERGED | 2026-09-03T08:39:01Z | 1/1 | none |
| `…-review-index-r3` (F1 r3) | MERGED | 2026-09-03T09:07:12Z | 3/3 | none |
| `…-readme-section` (F2 r1) | MERGED | 2026-09-03T09:25:42Z | 3/3 | none |
| `…-readme-section-r2` (F2 r2) | MERGED | 2026-09-03T09:35:21Z | 3/3 | none |

**The miss, stated exactly.** F1's first run never reached MERGED. Its `state.json` carries:

```
"phase": "DISPATCHED",
"blocked_reason": "wave 2 refused: index-output",
"blocked_at": "2026-09-03T08:24:49Z",
"jobs": { …, "spec-review": { "status": "pending" } }
```

The commit trail shows the finalizer defect (finding 89 — the gate receipt did not say where a job
ran) and the hand repair, in order:

```
29b534a 09:19:20  compound-v: wave 1 of run …-review-index (index-script)      ← hand commit
dbf5749 09:19:20  bookkeeping(…-review-index): wave 1 finalized
04239b1 09:24:49  bookkeeping(…-review-index): wave 2 finalized                ← wrote phase BLOCKED
7c4070f 09:25:36  compound-v: wave 2 of run …-review-index (index-output)      ← hand commit
5616746 09:25:37  bookkeeping(…-review-index): wave 2 finalized                ← re-run finalizer
be44570 09:26:10  fix(record+authority+finalize): … (finding 89)
```

Three deterministic tells, beyond the two hand commits the brief already names:

1. `04239b1` (`git show 04239b1`) set `"phase": "BLOCKED"`, `"integrated": false`, `"merged": []`, and
   `blocked_reason: "wave 2 refused: index-output"` — while its **commit message still says "wave 2
   finalized"**. A refusal was committed under a success message.
2. The wave-2 *bookkeeping* commit (`04239b1`, 09:24:49) precedes the wave-2 *content* commit
   (`7c4070f`, 09:25:36) — the inversion is the human stepping in between them.
3. `5616746` reverted `BLOCKED` → `DISPATCHED` and recorded `integrated: true`, but **left
   `blocked_reason` and `blocked_at` in the file**. The r1 audit record on disk is now internally
   contradictory: phase DISPATCHED, both waves integrated, a stale refusal reason, and a `spec-review`
   job frozen at `pending`.

**The other four runs are clean.** Each carries `phase: MERGED`, a `merged_at`, every job
`status: done` with `merged.integrated: true`, and one `compound-v: wave N of run …` content commit
immediately followed by its `bookkeeping(…): wave N finalized` — never inverted, never duplicated.
Those are the finalizer's own commits; no hand step sits between `/v:epic`'s commands for r2, r3, F2
r1 or F2 r2.

**AC 2 verdict: PARTIAL MISS — 4 of 5 runs clean, 1 of 5 hand-finalized.** The miss is real and the
epic recovered from it correctly (r2/r3 after the `be44570` fix), but "every per-feature run reached
MERGED through the pipeline with no manual step" is false as written, and F1 r1's record additionally
lies about its own state. See issue 3.

---

## AC 3 — `epic-state.json` records both features `done` with their run-ids

Both commands, quoted verbatim:

```
$ /usr/bin/python3 -B scripts/compound-v-epic-state.py --summary --state docs/superpowers/execution/epics/2026-09-03-verification-index/epic-state.json
EPIC 2026-09-03-verification-index — The verification-program index (stage 5, the first epic)  [done]
  [done   ] review-index         deps=- run=2026-09-03-verification-index-review-index-r3
  [done   ] readme-section       deps=review-index run=2026-09-03-verification-index-readme-section-r2
```

```
$ /usr/bin/python3 -B scripts/compound-v-epic-state.py --next --state docs/superpowers/execution/epics/2026-09-03-verification-index/epic-state.json
{"feature": null, "reason": "epic complete: all features done"}
```

Both features `done`, both carrying the run-id of the run that actually merged them. ✅

**Observation A — the literal string.** The brief says `--summary` says "epic complete". It does not:
`--summary` prints `[done]` on the header line. The literal phrase is `--next`'s `reason`. The
substance of AC 3 is met by both; the brief's wording points at the wrong command.

**Observation B — top-level `done` before this review ran.** `epic-mode.md:166` says `done` requires
`final_review.status=="passed"` and that "feature completion alone is never `done`". **That sentence
governs marathon only, and this epic is checkpoint.** Three independent confirmations:

1. The paragraph sits inside `## Marathon stance (v2.10, opt-in)` (heading at line 116; the next
   heading, `## Goal and resurrection are native (3.4.0)`, is at line 172).
2. `scripts/compound-v-epic-state.py`'s docstring places `--record-final-review` and the sentence
   `"done" requires all-features-done AND final_review.status=="passed"` inside the section headed
   **"Marathon (opt-in, additive)"**; the "Checkpoint (default, unchanged)" section above it has no
   final-review command at all.
3. The code branches explicitly. In `apply_update`: `if marathon: … _recompute_top_status(state)` —
   the function that applies the `final_review` gate — `else:` (checkpoint) `if all(s == "done" for s
   in sts): state["status"] = "done"`. No final-review term.

This state has no `autonomy` and no `final_review` block, so it takes the checkpoint branch and `done`
on all-features-done is correct. **The docs do not contradict each other**; the marathon-scoped
sentence simply reads as universal when quoted out of its section. The state is not wrong, so this is
an observation for the orchestrator, not a blocker.

**AC 3 verdict: MET.**

---

## Cross-feature seams

**1. The link target (F2 → F1's output).** `README.md:138` carries
a real markdown link whose bracket text and whose target are both
`docs/superpowers/dogfood/README.md` — root-relative, **no leading slash** (`grep -c '](/docs/' README.md` → `0`), target exists. Because
`README.md` sits at the repo root, the CI gate's "resolve relative to the source file's dir" rule
makes this resolve correctly. Pre-flight 1A's warning was heeded. ✅

**2. The numbers (F2 → F1's footer).** Covered in AC 1(c)/(d): equal to the committed footer, stale
against a fresh one, disclosed. ✅ with the caveat above.

**3. The verdict rule (F1's generator over the review files this epic itself produced.)** Fresh
regeneration, `grep 'epic-vi' $S/run1/A.md`:

```
| 2026-09-03 | epic-vi-readme-section | 1 | ISSUES   | 2026-09-03-epic-vi-readme-section-review.md   |
| 2026-09-03 | epic-vi-review-index   | 1 | ISSUES   | 2026-09-03-epic-vi-review-index-review-1.md   |
| 2026-09-03 | epic-vi-readme-section | 2 | APPROVED | 2026-09-03-epic-vi-readme-section-review-2.md |
| 2026-09-03 | epic-vi-review-index   | 2 | APPROVED | 2026-09-03-epic-vi-review-index-review-2.md   |
```

Checked against the source files: F1 review-1 line 276 and F2 review line 3 both carry an ISSUES
verdict; F1 review-2 line 500 and F2 review-2 line 3 both carry an APPROVED one. Four for four. The
two decoys in the corpus are correctly ignored — F1 review-1 line 37 (`Verdict `none` — no
`tighten``) and F2 review-2 line 29 (a mid-sentence "verdict,") match neither alternation, and the
bare `## Verdict` headings do not either, because the pattern requires the token to follow. F1's
generator indexes its own epic's output correctly. ✅

**4. A vocabulary seam the epic surfaced.** The generator's enum is `APPROVED|ISSUES` and everything
else is `unknown` (F1 spec, "else `unknown`"). But `/v:epic` step 5 — *this* review — is specified to
emit `VERDICT: PASS` or `VERDICT: ISSUES`. Simulated with `**VERDICT: PASS**`, this very file indexes
as `| 2026-09-03 | epic-vi-integration | 1 | unknown | … |` and lands in the `other` bucket. The
verdict happens to be ISSUES, so the row is correct today, but a passing integration review would be
invisible to the index that exists to record it. Correct-by-spec, wrong-by-intent. See issue 4.

**5. `lint-frontmatter` — green.** `/usr/bin/python3 -B scripts/lint-frontmatter.py .` → `✅ All
frontmatter clean`, exit 0.

**6. The new test — green, and CI actually runs it.** `bash tests/test-dogfood-index.sh` →
`test-dogfood-index: all assertions passed`, exit 0. `.github/workflows/validate.yml`'s `tests` job
discovers `find tests -type f \( -name '*.sh' -o -name '*.py' \)` recursively and fails on zero
discoveries, so the new file is swept automatically. No v2.14.1-style false green here. ✅

**7. The dead-link CI gate is RED at HEAD and was GREEN at the baseline.** This is the blocking
finding. Replicating `.github/workflows/validate.yml` lines 234–267 verbatim:

```
$ bash <replica of the CI dead-link scan>          # at HEAD
DEAD: ./docs/superpowers/archaeology/2026-09-03-epic-vi-readme-section.md -> docs/superpowers/dogfood/README.md
DEAD: ./docs/superpowers/archaeology/2026-09-03-epic-vi-readme-section.md -> skills/compound-v/SKILL.md
DEAD: ./docs/superpowers/execution/2026-09-03-verification-index-readme-section/jobs/readme-section.prompt.md -> docs/superpowers/dogfood/README.md
DEAD: ./docs/superpowers/library-audit/2026-09-03-epic-vi-readme-section.md -> docs/superpowers/dogfood/README.md
DEAD: ./docs/superpowers/dogfood/2026-09-03-epic-vi-readme-section-review.md -> docs/superpowers/dogfood/README.md   (×3)
DEAD: ./docs/superpowers/dogfood/2026-09-03-epic-vi-readme-section-review-2.md -> docs/superpowers/dogfood/README.md (×2)
DEAD COUNT: 9   → exit 1

$ git archive 4f9faac | tar -x -C $S/base && cd $S/base && bash <same replica>
All intra-plugin links resolve                      → exit 0
```

All nine are new in this diff. `git log --diff-filter=A` attributes them to `0d41987` (the F2
pre-flight audits), `3122bf9` (the F2 job prompt) and the two F2 review commits `2018067` / `c09ec7b`.
The mechanism: every one of those documents *quotes* F2's root-relative link while itself living in a
nested directory, and the gate resolves each link against the source file's own directory —
`docs/superpowers/dogfood/` + `docs/superpowers/dogfood/README.md` does not exist. Backticks do not
help: the gate is a flat `grep -oE '\]\([^)]+\.(md|py|sh|json|ya?ml)[^)]*\)'` with no code-span or
fence awareness, which is why `…-review.md:224-225` trips it from inside a fenced block. The
offending lines are `archaeology/…:108` and `:112`, `library-audit/…:45`,
`execution/…/readme-section.prompt.md:27`, `…-review.md:76,224,225`, and `…-review-2.md:104,265`.

The workflow has no `paths:` filter and runs on `push: [main]` and `pull_request: [main]`, so this
fires on the next push. Exactly the PASS-3 failure mode: two features each individually correct, and a
repo-wide gate broken where they meet. See issue 1.

**8. An invariant F1's own spec states, failing against the committed index.** The spec requires "the
footer's `APPROVED` count must be ≥ the count of `grep -lE '^(#+[[:space:]]*)?\**VERDICT:?\**[[:space:]]*\**APPROVED'
docs/superpowers/dogfood/*-review*.md`". That grep now returns **4**; the committed footer says
**3**. Against a fresh regeneration it is 4 ≥ 4 and holds. This is the AC-1(d) staleness restated as a
violated invariant rather than a disclaimer, and it is the concrete reason issue 2 is worth closing.

**9. No CHANGELOG entry for either shipped feature.** `CHANGELOG.md`'s `[Unreleased]` section
documents findings 85, 86, 87 and 89 only. A new user-facing script, a new test and a new README
section shipped with no entry. Neither feature's manifest put `CHANGELOG.md` in a write lane, so no
job could have written it — a run-level gap, not a job-level one. Non-blocking (the brief's ACs are
silent on it).

**10. Every other CI gate is green at HEAD.** Version lockstep (`plugin.json` 3.4.3 = first numeric
CHANGELOG heading `[3.4.3]`; `[Unreleased]` is correctly skipped as non-numeric); the manifest
invariant gate over all tracked run manifests; the committed-`state.json` audit gate (all five
verification-index run dirs pass); the anti-ruflo fabricated-metric gate (no hits in `scripts/` or
`docs/`); and `--selftest` on all four changed Python scripts — `compound-v-epic-state`,
`compound-v-localize`, `compound-v-emit-workflow`, `compound-v-integration-gate` — each exit 0 under
`/usr/bin/python3` 3.9.6, the documented floor. `shellcheck -S warning
scripts/compound-v-dogfood-index.sh` is also clean (exit 0), though CI lints `hooks/` only.

**11. Reward-hack check (marathon lens, applied anyway).** No test file in the diff was deleted,
skipped, or loosened; `tests/test-dogfood-index.sh` is net-new and only adds assertions. The verdict
regex was *tightened* during F1 r3, not relaxed. Nothing here makes a gate pass by weakening it.
`git status --porcelain` was empty after every command in this review; no checkout file was modified.

---

## Verdict

**VERDICT: ISSUES**

The epic built what it said it would build, and both features are individually sound. It does not pass
integration, because the composite breaks a CI gate that was green when the epic started, and one of
five runs did not go through the pipeline unassisted.

1. **BUILD_RED (blocking) — the dead-link CI gate fails at HEAD with 9 dead links, all introduced by
   this epic.** Baseline `4f9faac` exits 0; HEAD exits 1. Sources:
   `docs/superpowers/archaeology/2026-09-03-epic-vi-readme-section.md:108,112`;
   `docs/superpowers/library-audit/2026-09-03-epic-vi-readme-section.md:45`;
   `docs/superpowers/execution/2026-09-03-verification-index-readme-section/jobs/readme-section.prompt.md:27`;
   `docs/superpowers/dogfood/2026-09-03-epic-vi-readme-section-review.md:76,224,225`;
   `docs/superpowers/dogfood/2026-09-03-epic-vi-readme-section-review-2.md:104,265`. Each writes
   a markdown link targeting `docs/superpowers/dogfood/README.md` (or `skills/compound-v/SKILL.md`) from a nested
   directory, and the gate resolves relative to the source file's dir. Two ways to close it, and the
   choice is the orchestrator's: strip the link syntax in those nine places (backtick the path instead
   of linking it — this file does that throughout, deliberately), or teach the gate to skip links
   inside code spans and fenced blocks. The second is the durable fix — the gate flagged a *fenced*
   line at `…-review.md:224`, so any future document that quotes a link will keep re-breaking it — but
   it widens a CI gate, so it is a decision, not a cleanup. **This review file hit the same trap
   while being written**: quoting the offending link verbatim added three more dead links, caught by
   re-running the gate replica against this file and rewritten out before it was finished. That is
   the recurrence argument in one data point.

2. **The README↔footer equality is unguarded (non-blocking).** AC 1's equality is true today only
   because F2 copied the numbers by hand from a snapshot. Nothing regenerates the index in CI and
   compares it to `README.md:138`, so the drift is already two rows wide (34/3 committed, 35/4 live,
   36/4 after this file) and F1's own spec invariant "footer APPROVED ≥ grep -l APPROVED count"
   already reads 3 ≥ 4. The `as of this writing` hedge is honest and is doing all the work. A
   regenerate-and-`git diff --exit-code` CI step would make the index self-maintaining; the
   orchestrator may reasonably decide the hedge is enough for a docs index.

3. **AC 2 is a partial miss, and F1 r1's record is internally inconsistent (non-blocking for the
   epic, worth fixing in the audit trail).** Four of five runs reached MERGED with zero manual steps.
   F1's first run did not: `state.json` phase is `DISPATCHED`, `blocked_reason: "wave 2 refused:
   index-output"`, `spec-review` still `pending`, and commits `29b534a` / `7c4070f` were made by hand
   after finding 89. Two smaller defects fell out of the same episode: `04239b1` committed a refusal
   under the message "wave 2 finalized", and `5616746` cleared `phase: BLOCKED` without clearing
   `blocked_reason` / `blocked_at`, leaving a record that simultaneously claims both waves integrated
   and a refusal outstanding. The finalizer fix `be44570` addressed the cause; the stale keys and the
   misleading commit message are separate, and the second one will recur on the next refusal.

4. **The index cannot record a passing integration review (non-blocking).** F1's verdict enum is
   `APPROVED|ISSUES`; `/v:epic` step 5 emits `PASS|ISSUES`. A `**VERDICT: PASS**` line indexes as
   `unknown` and lands in `other` — verified by simulation. Either the epic's integration review
   should emit `APPROVED`, or the generator should accept `PASS` as a third APPROVED-equivalent token.
   One line either way, and it only bites when the epic succeeds.

5. **Neither shipped feature has a CHANGELOG entry (non-blocking).** `[Unreleased]` lists findings
   85/86/87/89 and nothing about `scripts/compound-v-dogfood-index.sh`, `tests/test-dogfood-index.sh`
   or the README section. No job had `CHANGELOG.md` in its write lane, so this is a run-level omission
   to close before the next version bump.

---

## Pass 2 (HEAD cdb4355)

Re-verification only, scoped to what `cdb4355` changed: the dead-link gate in
`.github/workflows/validate.yml` (9 lines), F1 r1's `state.json` (18 lines), and the pass-1 report
above, which that commit also committed. Nothing in the pass-1 text is edited. Pass-1 issues 2, 4 and
5 were dispositions rather than code changes and are recorded below without re-litigation.

### 1. Dead-link gate — pass-1 issue 1 — **CLOSED**

The gate now drops fenced blocks and strips inline code spans before extracting links:

```
awk '/^[[:space:]]*(```|~~~)/ { fence = !fence; next } !fence { print }' "$file" \
  | sed -E 's/`[^`]*`//g' \
  | grep -oE '\]\([^)]+\.(md|py|sh|json|ya?ml)[^)]*\)' 2>/dev/null | sed 's/^](//;s/)$//' | ...
```

Replica updated to that extraction and run against a clean checkout of HEAD
(`git archive cdb4355 | tar -x`), so the working tree cannot flatter it:

```
$ (cd $S/head && bash $S/deadlink2.sh)
All intra-plugin links resolve
clean_head_exit=0
```

Nine to zero. The old replica still exits 1 on the same tree, which is what makes the delta the gate's
and not the corpus's:

```
$ bash $S/deadlink.sh   # pass-1 extraction, unchanged
old_replica_exit=1
```

**The plant.** A throwaway `zz-deadlink-plant.md` at the repo root with three links — one real
navigation outside any code context, one quoted in an inline code span, one quoted inside a fence,
all three pointing at files that do not exist:

```
$ bash $S/deadlink2.sh
DEAD: ./zz-deadlink-plant.md -> docs/superpowers/this-file-does-not-exist.md (resolved: ./docs/superpowers/this-file-does-not-exist.md)
DEAD COUNT: 1
exit_with_plant=1
```

Exactly the real one. The code-span copy and the fenced copy are both ignored; the gate did not go
blind, it learned the difference between navigation and text. A second, adversarial plant — a real
dead link on a line carrying an unmatched stray backtick earlier in the same line — is also still
caught (`DEAD: ./zz-plant2.md -> docs/nope-really-missing.md`, count 1), so the code-span strip does
not swallow links next to odd backticks. Both plants deleted; `git status --porcelain` clean after
each.

```
$ rm -f zz-deadlink-plant.md && bash $S/deadlink2.sh
exit_after_plant_removed=0
```

**Two durability notes, neither blocking.** The fence handling is a parity toggle: it flips on any
line beginning with three backticks or three tildes, without requiring the closer to match the
opener's character or run length — unlike the CommonMark-accurate fence walker the CHANGELOG-version
step uses 180 lines earlier in the same file. An unbalanced fence would therefore swallow the rest of
that file from link scanning. Measured across every `*.md` in the repo, **0 files** have odd fence
parity, so there is no live hole; the property is worth knowing rather than fixing. Second, this is a
gate that got *wider*, so the honest framing is that it now trades some recall for the precision it
gained — the plant is the evidence that the recall it kept is the recall that matters.

### 2. F1 r1's record — pass-1 issue 3 — **terminal and honest; three cosmetic residuals**

The record now reads `phase: MERGED`, `superseded_by: 2026-09-03-verification-index-review-index-r2`,
a `history` entry carrying the old `blocked_reason` / `blocked_at` plus the sentence "commits 29b534a
and 7c4070f are hand finalizations", and a note on `spec-review`: "never dispatched in this run;
performed by r2 (review-only) and r3 (APPROVED)".

**Is it terminal to the dashboard and the hook? Yes — measured before and after, same command, same
6-hour window:**

```
$ (cd $S/pre  && python3 scripts/compound-v-dashboard.py resume --open-jobs --max-age-hours 6)   # tree at d24fcbf
⏸ UNFINISHED COMPOUND V WORK: run 2026-09-03-verification-index-review-index — DISPATCHED, 2/3 jobs done, updated 2h ago. …

$ (cd $S/post && python3 scripts/compound-v-dashboard.py resume --open-jobs --max-age-hours 6)   # tree at cdb4355
(no output)
```

The exclusion is on terminality, not on staleness: the run's `updated_at` is inside the window (age
negative — see residual (c)), and the same command at HEAD with `--max-age-hours 100000` still prints
a different, genuinely unfinished run (`2026-09-01-v3.0-triage-tests-orchestration`, COLLECTED, 41h),
so the command is not simply mute. The dashboard's terminal set is literally
`TERMINAL_RUN_PHASES = ("merged",)` at `scripts/compound-v-dashboard.py:70`. The hook consumes exactly
this call — `hooks/triage-prompt-nudge.sh:310` runs `compound-v-dashboard.py resume --open-jobs
--max-age-hours 6`, and its documented rule is "cannot tell ⇒ ACTIVE" (line 299) — so the hook now
sizes prompts as if nothing were running. `/v:resume` agrees independently:
`commands/v-resume.md:15` says "If `phase` is already `MERGED`, report nothing to do and stop", so the
still-`pending` `spec-review` job can never be re-dispatched by a resume. Every consumer behaves
correctly.

**Is it internally consistent? Substantially, but not entirely — three residuals, all
representational, none behavioural:**

(a) **No `merged_at`.** All four sibling runs carry one (`…-r2` 08:39:01Z, `…-r3` 09:07:12Z, F2
09:25:42Z, F2 r2 09:35:21Z); this record has none. The finalizer stamps `merged_at` in the *same
branch* that sets `MERGED` (`scripts/compound-v-emit-workflow.py:4139-4140`), and its own selftest
asserts the pair — "finalize-wave advances the phase to MERGED when every job is integrated",
checking `phase == "MERGED" and bool(merged_at)` at `compound-v-emit-workflow.py:6331`.

(b) **`MERGED` now carries a second meaning.** The finalizer writes `MERGED` only when every manifest
job is integrated (`_done` over `manifest["jobs"]`, same function); with `spec-review` never
dispatched, `_done` is false and the finalizer would have written `DISPATCHED`. So for four runs
`MERGED` means "the pipeline finished all jobs" and for this one it means "abandoned and superseded,
do not resume". `commands/v-resume.md:53` states the normal-path rule this repair steps outside of:
"On reaching `MERGED`, do not write the phase by hand". That rule governs the pipeline, not a
post-hoc audit correction, so this is a naming overload to be aware of, not a violation to reverse —
and the `history` + `superseded_by` fields are what keep it honest.

(c) **`updated_at` is stamped 2026-09-03T09:58:00Z, nine minutes after the commit that wrote it**
(cdb4355 is dated 09:49:10Z) and ahead of the clock at review time (09:53:37Z). Harmless — a negative
age is trivially inside any window — but a hand-written timestamp that postdates its own commit is
the sort of thing this audit trail exists to not do.

(d) Minor: `superseded_by` has no reader anywhere in `scripts/`, `hooks/`, `skills/`, `commands/` or
`schemas/`. It is documentation for humans, which is a fine thing to be — noted so nobody later
assumes a consumer enforces it.

**AC 2 is unchanged by this repair, correctly.** Editing r1's phase does not make "every per-feature
run reached MERGED through the pipeline with no manual step" true, and the fix does not pretend
otherwise: the `history` entry names the two hand finalizations in the record itself. The pass-1
partial-miss finding stands as history; what changed is that the record no longer *contradicts* it.

### 3. README ↔ footer equality — pass-1 issue 2 — **decision recorded, accepted**

The orchestrator's decision: the "as of this writing" hedge stays, no CI regenerate-and-diff step is
added, because every review file lands after the index that counts it, so such a step would go red on
every review landing by construction.

**The reasoning is correct for the step pass 1 proposed**, and pass 1 under-thought it: a
regenerate-then-`git diff --exit-code` gate would fail on the very commit that adds a review file,
every time, which is a gate that trains people to ignore it. Accepted, not re-raised. Recorded for
completeness: a narrower guard exists that does not have that failure mode — assert that
`README.md`'s two numbers equal the **committed** footer rather than a regenerated one, which stays
green when the index is merely stale and goes red only when someone edits one of the two without the
other. That is a different guard than the one rejected, and offering it is not disagreement with the
reasoning that rejected the first.

### 4. `VERDICT: PASS` indexing as `other` — pass-1 issue 4 — **accepted as an honest row**

Left as is, recorded for the CHANGELOG. One concrete consequence worth writing down while it is in
front of us: this file now carries **two** verdict lines, and the generator takes the first
(`grep -m1`). Its index row therefore reports pass 1's verdict for the life of the document, whatever
pass 2 concludes. That is defensible — the row points at a file whose latest verdict a reader can see
in ten seconds — but it means the index counts *documents*, never *outcomes*, and a multi-pass review
file freezes at its first verdict. Same root as issue 4: the row is honest about the file and silent
about the state.

### 5. Surrounding build, re-verified at HEAD

`.github/workflows/validate.yml` still parses as YAML. `lint-frontmatter.py .` exit 0;
`tests/test-dogfood-index.sh` exit 0; `--selftest` exit 0 on `compound-v-epic-state`,
`compound-v-localize`, `compound-v-emit-workflow`, `compound-v-integration-gate` and
`compound-v-dashboard`; the committed-`state.json` audit gate passes for all five verification-index
run dirs. Nothing regressed around the two edits.

### Verdict — pass 2

Pass 1's one blocking item is closed, and closed by the durable fix rather than by editing nine
documents: the gate distinguishes a quoted link from a real one, proved by a plant that it still
fails on exactly the real dead link. F1 r1's record is now terminal to every consumer that reads it —
dashboard, hook and `/v:resume` — and the episode is preserved in `history` rather than erased, which
is the honest shape. The two remaining dispositions are recorded, and pass 1's AC results stand
unchanged: AC 1 met as written, AC 2 a partial miss (4 of 5 runs clean, F1 r1 hand-finalized), AC 3
met.

**VERDICT: PASS**

Non-blocking, recorded for the CHANGELOG and for whoever touches these files next — none of these
gates DONE:

1. F1 r1's repaired record carries `phase: MERGED` without a `merged_at` and with one manifest job
   never dispatched, a pair the finalizer never produces and its own selftest asserts against
   (`scripts/compound-v-emit-workflow.py:4139-4140`, `:6331`). Behaviour is correct everywhere;
   the shape is a hand-written special case.
2. The same record's `updated_at` (09:58:00Z) postdates the commit that wrote it (09:49:10Z).
3. The gate's fence handling is a parity toggle, not the CommonMark walker used elsewhere in the same
   workflow file; 0 repo files currently have odd fence parity, so no live hole.
4. `superseded_by` has no reader in the codebase — human documentation, not an enforced field.
5. A multi-pass review file freezes at its first verdict in the index, because the generator matches
   with `grep -m1`.
