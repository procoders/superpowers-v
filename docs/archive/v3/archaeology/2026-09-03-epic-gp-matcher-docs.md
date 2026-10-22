# F2 `matcher-docs` Code Archaeology

Spec under audit: `docs/superpowers/execution/epics/2026-09-03-glob-parity/specs/matcher-docs.md`
(+ its 2026-09-03 Amendment). Scope per spec: modify `skills/compound-v/memory.md` and
`skills/compound-v/execution-manifest.md` **only** — no code changes. This is F2 of epic
`2026-09-03-glob-parity` ("stage 7: death & resurrection"), `depends_on` F1 `one-matcher`.

## Step 0 — V-memory recall

Ran `scripts/compound-v-memory.py search` three times (`"glob matcher write_allowed fnmatch
parity"`, `"execution-manifest.md write_allowed field table dead-link lint-frontmatter"`,
`"recall-check bare path no wildcard matches this path or anything under it"`), `--intent
planning`. Not empty — every query returned real, load-bearing prior art for this exact spec:

- `docs/superpowers/archaeology/2026-09-03-epic-gp-one-matcher.md` — F1's own archaeology
  (required reading per the task's knowledge-base instruction; read in full, see below).
- `docs/superpowers/dogfood/2026-09-03-epic-gp-one-matcher-review-1.md` — F1's review: **F1 has
  shipped.** All 10 `parity …` selftest rows `ok`, plus `bare dir == dir/**` and `matcher missing
  -> unavailable`. `_file_matches` at `compound-v-memory.py:1115-1125` delegates to the scope
  gate's matcher exactly as F1's constraints demanded.
- **A plan, a manifest, a run state, and a Phase-1C library-audit already exist for this exact
  F2 spec**, found via V-memory and confirmed live on disk (not stale recollections):
  - `docs/superpowers/plans/2026-09-03-epic-gp-matcher-docs.md` (a full implementation plan)
  - `docs/superpowers/execution/2026-09-03-glob-parity-matcher-docs/manifest.yaml` +
    `state.json` (`"phase": "PARTITION_VERIFIED"`, both jobs `"status": "pending"` — validated,
    never dispatched)
  - `docs/superpowers/library-audit/2026-09-03-epic-gp-matcher-docs.md` (Phase 1C's own output)
  - The epic brief (`docs/superpowers/execution/epics/2026-09-03-glob-parity/brief.md`) names
    the reason: this epic's whole point is a kill-mid-dispatch/resume drill — F1's run was
    interrupted and resumed on purpose. Two `pre-eval/*.json` records exist for this feature
    under slightly different slugs (`one-matcher-docs` @ 19:09:10Z, `matcher-docs` @ 19:19:41Z),
    consistent with a second pass over F2's own pre-flights after resumption.
  - **This is reported as evidence, not treated as pre-approved.** Every claim below is
    independently re-verified against the live code and the live doc files as they read today,
    not copied from the plan/manifest/library-audit. Where I confirm them, I say so with my own
    citation; where I found something they didn't (or got subtly wrong), it's flagged in §7.

No claim below rests on a stale recollection alone.

**Tooling note:** this run's Bash access was clamped to exactly two `compound-v-memory.py`
command forms (`recall-check`/`search`). `git log`/`git blame` were not reachable; all code
reading below is Read/Grep against the current working tree, not git history. Same gap F1's own
archaeology flagged — real, not silently omitted.

## 1. Matrix

Two matrices: (A) does each of the spec's claimed rules match what the code actually does, and
(B) is each file's specified insertion point structurally valid.

### A — Rule-by-rule verification against `scripts/compound-v-scope-check.py`

| Rule (spec text) | Verified against | Match? |
|---|---|---|
| `*` matches within one path segment (never `/`) | `glob_to_regex:359-361` — single `*` emits `[^/]*` | ✅ |
| `**` matches across segments | `glob_to_regex:339-358` — `star_count >= 2` emits `.*` (or the two special cases below) | ✅ |
| `dir/**` also matches `dir` itself | `glob_to_regex:342-349` — when `**` follows a `/`, the just-emitted `/` is replaced with `(?:/.*)?` | ✅ |
| `?` matches one non-`/` character | `glob_to_regex:364-367` — emits `[^/]` | ✅ |
| `[` / `]` are literal (no character classes) | `glob_to_regex:368-372`, with an explicit code comment naming `app/[locale]/**` as the motivating case | ✅ |
| Anchored to the full repo-relative path | `glob_to_regex:330,374` (`(?s:` … `)\Z`) + `matches()` uses `re.match` (`:378-381`) — full-string anchor at both ends | ✅ |
| (recall-check only) bare path, no wildcard, means "this path or anything under it" | `compound-v-memory.py:1115-1125` `_file_matches`: on a literal miss, retries `g.rstrip("/") + "/**"` | ✅ — but **scoped to recall-check only**, see §2 |

All six rules the spec's Goal paragraph states, plus the bare-path addition, are exactly what
the live code does. Nothing in the spec's factual claims about matcher behavior is stale or
wrong.

### B — Insertion-point structural validity

| File | Spec/Amendment says | Literal reading | Structurally valid? |
|---|---|---|---|
| `execution-manifest.md` | "directly under the `write_allowed`/`read_allowed` rows of the field table" (Amendment); library-audit Constraint 3 says "directly after the `read_allowed` row (line 54 today)" | Insert a paragraph physically between markdown table row 54 (`read_allowed`) and row 55 (`acceptance`) | ❌ **breaks the table** — rows 55-59 (`acceptance`, `body`, `test_scope`, `timeout_sec`, footnote) are contiguous table syntax; a paragraph line between them terminates the table early and turns the remaining rows into a stray, unparsed line. See §7 constraint 1. |
| `execution-manifest.md` | (workable reading) "under the write_allowed/read_allowed rows" = within/after the section those rows live in | Insert after the table + its footnote + its one trailing paragraph end (after `execution-manifest.md:62`), before the next heading `### Tier vocabulary` (`:64`) | ✅ — this is what the pre-existing plan's Step 2 actually does, and it is the only placement that both satisfies "under write_allowed/read_allowed" in spirit and doesn't corrupt the table. |
| `memory.md` | "the `recall-check` row's wording... (line 54)" | Rewrite table row 54 in place | ✅ — single physical line in, single physical line out; no table-structure risk (this table has no footnote/trailing-paragraph ambiguity to navigate). |

## 2. Shared State

Not variables in the usual sense (this is a docs-only feature) — the "shared state" here is the
**matcher contract itself**: which callers rely on it, and whether the two target docs' claims
about who-uses-it are complete.

### The one matcher (`compound-v-scope-check.py:matches`) has THREE live callers today, not two

| Caller | File:line | Loads via | What it matches |
|---|---|---|---|
| The scope gate itself | `compound-v-scope-check.py:384-388` `is_allowed` | direct (same module) | `write_allowed` against a job's real git diff — **enforced** |
| `recall-check` (F1) | `compound-v-memory.py:1065-1125` `_scope_matches`/`_file_matches` | pycache-hardened sibling loader | prior-failure file paths against a job's `write_allowed` lane — **advisory** |
| `impacted_map` resolution (test_contract, pre-existing, unrelated to this epic) | `compound-v-fastpath-run.py:261-279` `_scope_check`, `:638-677` `_impacted_for` | plain memoized sibling loader | changed paths against `test_contract.impacted_map[].when` — **selects test commands** |

The third caller's own docstring (`compound-v-fastpath-run.py:264-267`) states the same thing the
spec wants documented: *"It is the repo's ONE path-glob authority... Feature B2's `impacted_map`
matching reuses it rather than reaching for `fnmatch` — a second, weaker matcher would diverge
from the gate."* `_impacted_for` (`:648-652`) goes further than F1: on a load failure it **raises**
`TestContractError` rather than degrading, explicitly refusing "a second, weaker matcher."

This does not change what F2 is scoped to write (the spec names only `write_allowed` and
`recall-check`), but it means the "same matcher" claim the docs will assert is **more true** than
the two-file spec implies — a third production call site already depends on the identical
semantics, unprompted by this epic. Worth the plan knowing so nobody undersells the claim, and a
reason **not** to also touch the `impacted_map`/`when` glob prose at `execution-manifest.md:505-539`
(see §7 constraint 6 — that would violate the spec's own "no other section changes").

### `_file_matches`'s bare-path fallback does NOT reach `write_allowed`/`is_allowed`

Verified directly (not inherited from F1's archaeology or the library-audit — re-read the
functions myself): `compound-v-scope-check.py:384-388` `is_allowed` calls `matches(path, pat)`
for each `pat` in `allowed`, and `matches` (`:378-381`) compiles `pat` through `glob_to_regex`
**verbatim** — no bare-path special case exists anywhere in `scope-check.py`. So today,
`write_allowed: ["docs"]` in a manifest authorizes writing to a file literally named `docs` and
**nothing under it** — a real write to `docs/foo.md` would `matches("docs/foo.md", "docs")` →
`False` → **BLOCKED**, the opposite of what "this path or anything under it" would suggest. The
bare-path convenience is `_file_matches`-only (`compound-v-memory.py:1123`, `_file_matches`'s own
fallback branch), invented for recall-check's advisory lookups, never present in the enforced
gate. Independently confirms the library-audit's Design Constraint 2 (§7 there) — I re-derived it
from the two functions directly rather than trusting that doc's claim.

## 3. Sibling Code

No new code path is being added (docs-only), so "sibling" here means: the nearby documented
sections in each target file that already describe adjacent behavior, which the new paragraph
must sit next to without duplicating or contradicting.

### `execution-manifest.md:268-270` — "Only `write_allowed` is enforced; `read_allowed` is advisory"

Read in full. This section states the **enforcement** distinction (write=hard, read=advisory) but
never once states the **matching** semantics (what `*`/`**`/`[`/`?` actually do) — confirmed by
grep: no `fnmatch`, no `glob_to_regex`, no mention of segment-crossing anywhere in this file
(§ Matrix A's grep evidence). This is the section an implementer might be tempted to extend
instead of adding the new paragraph after the field table, since it's the other place `write_allowed`
gets prose treatment — but the spec's own scope line ("No other section of either file changes")
and the Amendment's anchor ("directly under the write_allowed/read_allowed rows of the field
table") both point at the field-table location (§1B), not this section. Flagged so the plan
doesn't drift here by "logical" association.

### `execution-manifest.md:505-539` — the `impacted_map`/`when`-glob field table and prose

Also silent on matching semantics ("matches no `when` glob" appears three times, `:510,521,531`,
never defined). This section is governed by the identical matcher (§2 above) and is, if anything,
a stronger candidate for a semantics note than the enforcement-only §268-270 section — but per
§7 constraint 6, the spec's own scope explicitly forbids touching it. Noted as a real, pre-existing
doc gap this feature is *not* fixing, not as something the plan should quietly pick up.

### `memory.md:48-64` — the CLI table (rows 52-57)

The `recall-check` row (54) sits between `search` (53, itself the file's longest line today, see
§7 constraint 2) and `bootstrap` (55). No other row in this table references glob matching, so
the row rewrite is self-contained — no risk of the new prose reading as a continuation of an
adjacent row's claim.

## 4. External APIs

None. Pure in-repo prose describing in-repo code; no third-party library, SDK, or network API is
touched. Context7 was not invoked — nothing for it to verify. (This mirrors F1's own archaeology
finding for the same reason.)

## 5. Regression Surface

| Path that works today | Breaks if F2 lands wrong | Who notices |
|---|---|---|
| The CI "Check for dead intra-plugin cross-refs" step (`.github/workflows/validate.yml:234-274`) | A new `[memory.md](memory.md)` / `[execution-manifest.md](execution-manifest.md)` link with a typo'd path, or one written as `[../execution-manifest.md]` (wrong — the two files are **siblings** in `skills/compound-v/`, confirmed: both currently contain zero cross-links to each other, so there is no existing convention to copy — same-dir bare-filename links match how `[memory.md](memory.md)` already resolves against the repo's own sibling-link style used elsewhere, e.g. `parallel-dispatcher.md`) | CI, on the PR — hard-blocking, exact command reproduced in §7 |
| `python3 scripts/lint-frontmatter.py .` (CI + spec AC #3) | **Nothing this feature can break.** Verified live: neither file starts with `---\n` (`memory.md:1`, `execution-manifest.md:1` are both bare `#` headings), and neither path matches `path_class()`'s three gated classes (`agents/*.md`, `commands/*.md`, `skills/*/SKILL.md` — `lint-frontmatter.py:52-75`); `skills/compound-v/*.md` is not `skills/*/SKILL.md`. `lint_file` returns `[]` immediately for both (`:85-91`). This AC is **vacuously satisfied by any edit to these two files** — it only fails if some *unrelated* file in the repo is already unclean. Confirming this changes nothing about whether to run it (the spec requires it), but the plan/reviewer should not treat a clean run as evidence the new prose is correct — it tests nothing about this feature's actual content. |
| Every downstream `execution-manifest.md:NNN` line-anchored citation in **other** docs at a line number `>= 64` | Inserting the new paragraph (§1B's valid placement, before `:64`) shifts every subsequent line by however many lines are added. Confirmed live citations that would go stale: `docs/superpowers/dogfood/2026-09-03-v3.4.6-triage-test-scoping-fixes-review.md:83,239` (cites `execution-manifest.md:452`), `docs/superpowers/preflight/2026-09-01-v3.0-1a-archaeology.md:96,176,300` (cites `:160,164,165`), `reviews/pr-review-findings-6.md:43-44,48,115` (cites `:139,143,153,258-259`) | Nobody automated — these are dated dogfood/preflight/review snapshots (audit trail, not living cross-refs) and none is CI-checked by line number. **Not** an architecture-knowledge-base doc: grepped `docs/superpowers/architecture/*.md` for `execution-manifest.md` and found exactly one hit, a plain file-level link with no line anchor (`pre-eval-config.md:201`) — unaffected. So this is real but low-severity: prose that goes slightly stale in already-historical files, not a live/generated/trusted doc. |
| `docs/superpowers/architecture/architecture.md`'s line-anchored citations into `memory.md` (`:1-8`, `:57-63`, `:70-80`, per `architecture.md:94,96,98,103`) and `tech-context.md`'s (`memory.md:8`, `:10-11`) | **Breaks only if the `memory.md` row-54 edit changes the file's line count** — i.e., if the new recall-check row text is written across multiple physical lines instead of one, OR if a blank line is added/removed around it. A same-line-in/same-line-out edit (row 54 rewritten as one longer physical line, matching every other row in this table) leaves lines 57+ untouched. | `/v:onboard --refresh`'s own staleness check would eventually flag it if it ever re-verifies these citations — but this file **is** one of the "generated, citation-verified" docs per `CLAUDE.md`, so it is the one downstream doc in this whole surface that actually matters to keep accurate. |
| A future manifest author reading the new `write_allowed`/`read_allowed` prose | If the new paragraph states or implies the bare-path recursive reading applies to `write_allowed` (not just `recall-check`), a manifest author could write `write_allowed: ["docs"]` expecting it to authorize everything under `docs/`. Per §2, the actual effect is the opposite: every real write under `docs/` gets **BLOCKED** (over-restrictive, not a security hole — `is_allowed` has no such sugar) | The worker, mid-run, the first time it writes any file under such a lane — a confusing false BLOCKED with no code bug behind it, just a misdocumented contract |

## 6. DRY Findings

**Confirmed: exactly one remaining `fnmatch` usage in `scripts/`, and it is unrelated to this
epic's contract.** `scripts/compound-v-fastpath-run.py:108,733` still imports and calls
`fnmatch.fnmatchcase` — but only inside `_is_test_path` (`:725-733`), matching a **bare filename**
(no `/`) against filename-only conventions (`*_test.*`, `test_*.*`, `*.spec.*`, `:714`). Since the
candidate strings never contain `/`, `fnmatch`'s "`*` crosses `/`" divergence from the hand-rolled
matcher is unreachable here — this is a different, narrower problem (test-file naming convention
detection) than "which changed paths does a lane glob cover," not a second instance of the bug F1
fixed. Confirms F1 fully closed the one-matcher gap for its actual scope; nothing for F2 to
reconcile or mention.

**A fourth sibling-loader of `compound-v-scope-check.py` already exists**, beyond the four F1's
own archaeology counted (§3a-3d there) plus F1's own new one: `compound-v-fastpath-run.py:261-279`
`_scope_check` — plain `try/except`, memoized via a list-as-sentinel (`_SCOPE_CHECK_CACHE`), no
pycache hardening. Not this feature's concern (F2 touches no code), but relevant context for
§2's "three live callers" claim and worth the plan not being surprised by if it greps for other
`compound-v-scope-check.py` importers while verifying the "same matcher" claim.

No duplicate documentation of the glob contract exists anywhere else in `skills/compound-v/`
(grepped for `fnmatch`/`glob`/`crosses`/`character class` case-insensitively across the whole
directory — zero hits outside the two files already in scope). The "no second description
anywhere" constraint is achievable from a clean slate; there's nothing pre-existing to also purge.

## 7. Design constraints for the spec

Non-negotiable, derived from the above. (Constraints 1, 3-5, 8 are independently re-verified
against live code, not copied from the pre-existing plan/library-audit; where they agree with
those documents I say so — this is not a rubber stamp.)

1. **The `execution-manifest.md` paragraph must NOT be inserted literally between table rows 54
   and 55.** The field table (`:40-59`) plus its footnote (`:60`) and one trailing paragraph
   (`:62`) are contiguous; a stray paragraph line anywhere from `:55` to `:61` breaks the table's
   markdown syntax and orphans the remaining rows. The only structurally valid placement that
   still reads as "directly under the write_allowed/read_allowed rows" is **after `:62`, before
   the `### Tier vocabulary` heading at `:64`** — end of the "Per-job fields" section. This is
   what the pre-existing plan's Step 2 already does; stated here as a verified, non-negotiable
   constraint rather than an implementer's guess, because the Amendment's own wording ("directly
   under... the field table") and the library-audit's Constraint 3 ("directly after the
   `read_allowed` row") are both ambiguous enough to be misread literally.

2. **The `memory.md` row-54 edit must be a same-line-count replacement** (one physical line in,
   one physical line out — no inserted/removed blank lines around it). `docs/superpowers/architecture/architecture.md:94,96,98,103`
   line-anchors into `memory.md:57-63` and `:70-80`; those are the one downstream doc in this
   entire surface that is both trusted/generated (per this repo's own `CLAUDE.md`) and would
   actually go wrong (not just stale) if the line count shifts. The row may be as long as needed
   (line 53, the `search` row directly above it, is already ~455 characters — the file's longest
   line today — so a long row-54 rewrite is consistent with existing style, not a new violation).

3. **Do not extend the bare-path "this path or anything under it" reading to `write_allowed` or
   `read_allowed`.** Verified directly against `compound-v-scope-check.py:378-388` (`matches`/
   `is_allowed`): no such special case exists in the enforced gate. It is `_file_matches`
   (recall-check) -only sugar (`compound-v-memory.py:1123`). Stating it in the
   `execution-manifest.md` paragraph would misdocument an **enforced** security/scope boundary as
   more permissive than it is — the practical failure mode is a false BLOCKED (over-restrictive),
   not a security hole, but it is still a factual error about code that gates every job's writes.
   (Independently confirms library-audit Design Constraint 2 / MUST-NOT 2 — re-derived here, not
   assumed.)

4. **"Lines ≤ 200 characters" (spec's Tech Stack line, plan's Global Constraints) is not backed
   by any automated check.** Verified: `lint-frontmatter.py` has no line-length logic anywhere in
   its source (read in full, `scripts/lint-frontmatter.py:1-337`); the CI dead-link step
   (`.github/workflows/validate.yml:234-274`) checks link resolution only; no other script in
   `scripts/` or `.github/workflows/` checks markdown line length. Both target files already
   contain dozens of lines over 200 characters (`execution-manifest.md` alone: at least 15 lines
   over 500 characters, confirmed live — `:45,47,48,56,58,102,126,130,264,270,274,280,282,286,512`
   among others; `memory.md:53` is ~455 chars). So this is a **style intent for the new prose**,
   not an enforced gate — the plan should say so plainly rather than implying a check exists. The
   actionable, verifiable version of the constraint is: *do not add a line longer than the longest
   line already in that file* (spec's own acceptance criteria don't test this either — it's a
   manual `awk`/`grep -c` check the plan's own Step 4 already specifies correctly).

5. **AC #3 (`lint-frontmatter.py` clean) is not diagnostic for this feature.** Verified live:
   neither target file has a frontmatter block (`memory.md:1`, `execution-manifest.md:1` both
   start with a bare `#` heading) and neither matches `path_class()`'s gated set (`agents/*.md`,
   `commands/*.md`, literal `skills/*/SKILL.md` — `lint-frontmatter.py:52-75`), so `lint_file`
   returns no issues for either file regardless of what the new prose says (§5's Regression Surface
   table has the full trace). Required to run per the spec, but a green result proves nothing about
   this task's actual content — the reviewer should not cite it as content-level proof.

6. **Do not touch `execution-manifest.md:268-270` (enforcement-only prose) or `:505-539`
   (the `impacted_map`/`when`-glob section, itself silent on matching semantics and governed by
   the identical matcher, §2/§3) even though both are natural-seeming extension points.** The
   spec's own scope line ("No other section of either file changes") and its acceptance criteria
   (`grep -n fnmatch` finding nothing, "the same matcher" appearing — implicitly once per file,
   per the manifest's own acceptance test `grep -c "the same matcher"` expecting exactly `1`)
   together pin this to a single paragraph in one file and one row rewrite in the other.

7. **Both files must cite the parity selftest by its real, current name and location**:
   `compound-v-memory.py --selftest`'s `parity …` assertions, 10 rows, `:1634-1643`, plus the
   related `"bare dir == dir/**"` check at `:1645-1646` — all confirmed passing today (per F1's
   own dogfood review). Not a paraphrase, not a different script.

8. **The wording-identity question (spec: "say the same thing in the same words"; is that
   character-for-character identical prose in both files, or one canonical statement + a
   cross-reference in the other?) is a genuine open scope decision, already flagged by Phase 1C
   (library-audit §8, question 1) — not re-litigated here, but the plan must resolve it explicitly
   rather than let it be decided implicitly by whichever file gets edited first.** Whichever
   reading is chosen, the **facts** stated (the six rules + the bare-path addition, §1A above) must
   match the live code exactly in both files — that much is not optional either way.

## 8. File Touch Map

| File | Change | Notes |
|---|---|---|
| `skills/compound-v/memory.md` | Modified: table row 54 (`recall-check`) only, in place. | Not generated, not a lockfile/schema-dump, not a migration/route registry, not a barrel/index file — no SHARED-RESOURCE flag by this repo's stated criteria. Single job (`docs-contract`) touches both target files together per the existing manifest's partition, so no cross-task conflict risk within F2 itself. **Caution:** `docs/superpowers/architecture/architecture.md` line-anchors into this file (§7 constraint 2) — not a reason to flag SHARED RESOURCE (it's still a plain prose file with one clear owner-task), but a reason the edit must preserve line count. |
| `skills/compound-v/execution-manifest.md` | Modified: one new paragraph inserted after `:62` (end of "Per-job fields" section), before `:64` (`### Tier vocabulary`). | Same non-SHARED-RESOURCE reasoning as above. **Caution:** several *other* docs' historical file:line citations into this file, at lines `>= 64`, go stale by however many lines are inserted (§5's Regression Surface table) — all in dated dogfood/preflight/review snapshots, none CI-checked, none in the trusted/generated architecture KB. Acceptable drift, not a blocker, but worth the plan naming so it isn't mistaken for new information later. |
| `docs/superpowers/dogfood/2026-09-03-epic-gp-matcher-docs-review-1.md` | Created by the review job (`spec-review-1` in the existing manifest), not this archaeology. | Named for completeness only — out of this audit's own scope. |

## 9. Note on prior-run artifacts found during Step 0

A plan (`docs/superpowers/plans/2026-09-03-epic-gp-matcher-docs.md`), a materialized-but-never-
dispatched manifest + `state.json` (`docs/superpowers/execution/2026-09-03-glob-parity-matcher-docs/`),
and a Phase-1C library-audit already exist for this exact F2 spec, consistent with the epic's own
stated purpose (a kill-and-resume drill on F1, with two `pre-eval` records for F2 under slightly
different slugs). This audit was produced independently against live code and live doc content —
not by reading and restating those documents — and corroborates their core factual claims (the six
rules, the parity-selftest pointer, the two files' current line numbers) while adding three things
none of them stated: the table-insertion-break risk (§1B/§7-1), the architecture.md line-anchor
fragility specific to `memory.md` (§7-2), and the third live matcher caller in
`compound-v-fastpath-run.py` (§2/§6). Reported as evidence for whoever writes or re-writes the
plan, not as confirmation that the existing plan should be re-run unmodified.
