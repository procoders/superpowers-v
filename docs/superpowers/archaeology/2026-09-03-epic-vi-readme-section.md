# F2 `readme-section` (the README "Verification program" section) — Code Archaeology

Spec under audit: `docs/superpowers/execution/epics/2026-09-03-verification-index/specs/readme-section.md`
Depends on (already merged): F1 `review-index` — spec `.../specs/review-index.md`, its own archaeology
`docs/superpowers/archaeology/2026-09-03-epic-vi-review-index.md`, run `2026-09-03-verification-index-review-index-r3`
(**APPROVED**, `docs/superpowers/dogfood/2026-09-03-epic-vi-review-index-review-2.md`).

## Step 0 — V-memory

Three `compound-v-memory.py search` passes: `"readme verification program section"`, `"dogfood README footer
counts APPROVED review files"`, `"verification-index epic review-index F1 F2"`. No prior spec, ADR or archaeology
doc describes this exact section or a prior case of "a README section whose numbers are copied from another
generated file's footer" — **V-memory returned nothing directly on point**; this is genuinely new ground at the
README layer, same conclusion F1's own archaeology reached at the script layer. The one useful indirect hit was
`CONVENTIONS.md`'s anti-ruflo entry (fabricated-metric CI grep) — used as a pointer, then independently verified
against the actual `validate.yml` grep scope (§5) rather than trusted as-is. The engine also reports the FTS5
index **112 docs behind the repo** (stale, `/v:memory-refresh` not run this session); this does not change the
"nothing on point" conclusion since the gap is recent same-day dogfood/CHANGELOG churn, not a missed design doc.

## 1. Matrix

There is no existing *code* branch to enumerate (this is a one-shot docs edit), so the load-bearing dimension is
**which footer of `docs/superpowers/dogfood/README.md` the numbers are copied from** — the one already committed
in HEAD, or a freshly regenerated one — because this repo's own git status is clean right now and the committed
footer is demonstrably stale by exactly one row:

| Branch | Footer used | Numbers | Matches raw spec text (`Files: README.md only`) | Matches plan's Partition Map (one row) | Matches materialized `manifest.yaml` |
|---|---|---|---|---|---|
| **A — read HEAD as-is, no regeneration** | `docs/superpowers/dogfood/README.md` committed content, verified today | `Reviews: 32 · APPROVED: 2 · ISSUES: 25 · other: 5` | ✅ | ✅ | ❌ — manifest regenerates first |
| **B — regenerate `docs/superpowers/dogfood/README.md` first, then read** | Output of `bash scripts/compound-v-dogfood-index.sh` run against the current corpus | `Reviews: 33 · APPROVED: 3 · ISSUES: 25 · other: 5` (independently measured and quoted by F1's own review-2 pass, §"Note on the index's own freshness") | ❌ — touches a second file | ❌ — plan lists only `README.md` | ✅ — `manifest.yaml` job `index-refresh` |

**Root cause of branch A's staleness, verified by direct file census, not assumed:** `docs/superpowers/dogfood/`
holds 33 files today matching the generator's own `<date>-<feature>-review.md` / `-review-<N>.md` pattern (I
enumerated all of them against `scripts/compound-v-dogfood-index.sh:72-94`'s exact `case` logic). The committed
footer's `Reviews: 32` was correct at the moment F1's `index-output` job (`c20b48a`) ran, but
`2026-09-03-epic-vi-review-index-review-2.md` — F1's **own** review-gate output — was written *after* that commit
and is not indexed. This is not a hypothetical: F1's review-2 file measures the exact regenerated footer above
against a scratch `--out` path specifically so it would not have to predict it.

**Which branch is "handled by existing code"?** Both — the generator (`compound-v-dogfood-index.sh`) is correct
and idempotent either way; this is not a code bug. It is a **planning-artifact disagreement**: the raw spec
(`readme-section.md:11`, `"Files. Modify README.md only"`) and the plan (`plans/2026-09-03-epic-vi-readme-section.md:9-12`,
one Partition Map row) describe branch A; the already-materialized `manifest.yaml`
(`docs/superpowers/execution/2026-09-03-verification-index-readme-section/manifest.yaml:29-44`) and its job prompt
`jobs/index-refresh.prompt.md` implement branch B. See §7.

## 2. Shared State

**`docs/superpowers/dogfood/README.md`'s footer (`N`, `A` used by F2; `I`, `other` ignored by F2):**
- Set by: `scripts/compound-v-dogfood-index.sh:63-137` — four counters (`approved`, `issues`, `other`, `total`)
  incremented per matched file, emitted as `printf '\nReviews: %s · APPROVED: %s · ISSUES: %s · other: %s\n'`
  (`:137`) — note the separator is the Unicode middle dot `·` (U+00B7), not a comma or pipe.
- Currently (committed, HEAD): `Reviews: 32 · APPROVED: 2 · ISSUES: 25 · other: 5`.
- After regeneration (measured, not committed): `Reviews: 33 · APPROVED: 3 · ISSUES: 25 · other: 5`.
- **Gap if F2 reads it without regenerating:** the section publishes `32 review files, 2 APPROVED` — a claim
  already false on the day it is written, by the standard F1's own review-2 pass set for itself.

**`README.md`'s current heading list (governs "before the last existing `##` section"):**
- Read directly (`Grep '^## '`): 8 headings today — `Requirements`, `🎮 New here?`, `Main features`, `How it
  routes the work`, `Install`, `How to use it — two commands`, `Good to know`, `Under the hood (for the curious)`
  (line 136, last). Zero currently contain "Verification" — the "exactly once" acceptance criterion starts from a
  clean slate.
- **Section-boundary convention** (verified by reading every transition, not just the target one): every heading
  except `## 🎮 New here?` (line 31) is preceded by `blank line → --- → blank line`. The insertion point (between
  `## Good to know`'s last bullet, line 132, and the `---`/`## Under the hood` pair at 134-136) sits inside a
  region that *does* follow the convention — a new section spliced in without its own `---`-bracketing would be
  the visible outlier, not the norm.
- No file in the repo links to a `README.md#`-style anchor (`grep -r 'README\.md#'` — zero hits), so inserting a
  heading (which adds one new anchor and renames nothing) cannot break an existing cross-reference.

## 3. Sibling Code

No prior README section reads its numbers from another generated file's footer — genuinely new at this layer.
The load-bearing sibling is F1's generator and its test, both read in full:

- **`scripts/compound-v-dogfood-index.sh`** (141 lines, read in full). Relevant to F2: `:15` default `dir`, `:44`
  default `out` (`$dir/README.md`), `:52` the (now-fixed, per F1 review-2 §1/§4/§5) verdict pattern, `:99-114`
  match-anchored classification (mutation-proven), `:137` the exact footer `printf` format F2 must parse
  byte-for-byte. The script is `set -eu` (`:13`), bash-3.2-safe, and — per F1's review-2, item 7, still open,
  advisory — a `-review-100.md` (3-digit pass) would silently drop from both table and footer. Not live today
  (`grep -E '\-review-[0-9]{3,}\.md$'` over the corpus returns nothing), and F2 does not need to guard for it
  since F2 never re-derives counts, only copies the footer.
- **`tests/test-dogfood-index.sh`** (180 lines, read in full). Asserts the exact footer string format
  (`:159`, `"Reviews: 8 · APPROVED: 3 · ISSUES: 3 · other: 2"`) and byte-identical idempotence on a second run
  (`:161-169`) — this is the contract F2's own "regenerate, then read" step relies on: a second
  `bash scripts/compound-v-dogfood-index.sh` run changes nothing, so reading the footer after regeneration is
  deterministic and safe to do more than once.
- **F1's own review-2 pass** (`docs/superpowers/dogfood/2026-09-03-epic-vi-review-index-review-2.md`, read in
  full) records one **open, advisory, non-blocking** latent hazard directly relevant to F2's trust in the
  `APPROVED` count: item **A2** — the generator takes the *first* anchored `VERDICT` match (`grep -m1`); a
  multi-pass review file that quotes an earlier pass's verdict line *unindented* above its own final verdict would
  be indexed under the quoted (wrong) value. Not live today (the three files with two anchored verdict lines all
  agree), but the shape "quote a prior verdict, then state a new one" is exactly what every pass-≥2 review file
  in this corpus does, including F1's own review-2 file (which deliberately indents its quoted lines to dodge
  this, per its own "Note on quoting"). F2 has no way to detect this and is not asked to — see §7f.

## 4. External APIs

None. F2 touches only `README.md` (a local edit) and reads a local generated file
(`docs/superpowers/dogfood/README.md`). No third-party service, library, or HTTP contract — Context7 lookup does
not apply and was not attempted; this section is intentionally empty rather than padded.

## 5. Regression Surface

- **CI dead-link gate** (`.github/workflows/validate.yml:234-267`, read in full): scans every `.md` file for
  markdown links to `.md/.py/.sh/.json/.yml/.yaml` targets and fails the build if any does not resolve relative
  to the *linking file's own directory*. A link written from `README.md` as
  `[docs/superpowers/dogfood/README.md](docs/superpowers/dogfood/README.md)` resolves relative to `.` (repo
  root) and the target exists (merged by F1) — this passes. **A leading-slash form (`/docs/superpowers/...`) is
  silently skipped by this gate's own `case` statement (`:252`, `/docs/*` continue)** — not a failure either way,
  but inconsistent with every other intra-repo link already in `README.md` (all written path-relative-to-root, no
  leading slash, e.g. `[skills/compound-v/SKILL.md](skills/compound-v/SKILL.md)` at `README.md:140`).
- **Anti-ruflo fabricated-metric grep** (`validate.yml:185-214`, read in full): `find scripts docs -type f ...` —
  this walks only the `scripts/` and `docs/` trees. **`README.md` is at repo root and is never scanned by this
  step**, confirmed by reading the `find` invocation itself, not assumed from the `CONVENTIONS.md` summary. The
  new section's numeric prose ("N review files, A APPROVED") could not trip this gate even in principle.
- **`scripts/lint-frontmatter.py`** (F2's own stated acceptance gate): path-class gate only fires on
  `agents/*.md`, `commands/*.md`, `skills/*/SKILL.md` (`lint-frontmatter.py:9`, confirmed by reading the
  classifier). `README.md` is in none of these classes — the "stays green" acceptance criterion is trivially
  satisfied by any content change to `README.md` and says nothing about whether the new section's *numbers* are
  correct.
- **`README.md` is a high-churn, multi-feature file historically** (V-memory: `plans/2026-07-10-...brainstorm.md`
  Task 5, `plans/2026-07-12-...marathon.md` Task D2, `plans/2026-09-01-...orchestration.md` Task Z all modify
  `README.md` as part of unrelated release/feature work). No *other* job in **this** run's manifest also writes
  `README.md` — the write is disjoint within the run — but this is exactly the shape of file where a second,
  concurrently-dispatched epic touching `README.md` would produce a real merge conflict; flagged in the File
  Touch Map as a shared resource for that reason, not because this run's own partition is unsafe.
- **Nothing currently regresses in `docs/superpowers/dogfood/README.md` itself** if it is regenerated per branch
  B: the generator is idempotent (test-proven, §3) and F1's review-2 already re-ran it end-to-end against the
  live corpus with no row's existing verdict changing — regeneration only *adds* the missing row.

## 6. DRY Findings

No other code in the repo builds "a doc section whose numbers are copied from a generated footer." The only
existing consumer of this exact footer string is `tests/test-dogfood-index.sh:159`'s literal-string assertion —
not reusable code, just the format F2 must match by eye. Searched `scripts/*.py` and `scripts/*.sh` for any
existing "regenerate then read a footer" helper (`grep -rn 'Reviews:.*APPROVED'`) — zero hits outside the
generator and its test. Nothing to extend or refactor; a third path would not be a duplicate of anything that
exists.

## 7. Design constraints for the spec

1. **The plan MUST NOT let `README.md`'s numbers come from the currently-committed footer without first
   regenerating `docs/superpowers/dogfood/README.md`.** As of this audit (git status clean, verified against the
   actual file corpus) that footer is stale by exactly one row — `Reviews: 32` where the true count is `33` — and
   the missing row is F1's own review-gate output. Reading it as-is publishes a false claim the moment it lands.
2. **Regenerating `docs/superpowers/dogfood/README.md` means this feature touches two files, not one** —
   directly contradicting the raw spec text (`readme-section.md:11`, `"Files. Modify README.md only"`) and the
   plan's Partition Map (`plans/2026-09-03-epic-vi-readme-section.md:9-12`, a single `Task A → README.md` row).
   The already-materialized `manifest.yaml` for this exact run has already resolved this correctly — job
   `index-refresh` (`write_allowed: docs/superpowers/dogfood/README.md`) merges before job `readme-section`
   reads the footer, and `readme-section.prompt.md:7` records the dependency explicitly ("Prerequisites, already
   merged and COMMITTED into your base before this worktree was created: index-refresh"). **This two-job,
   two-file shape must be preserved** in any re-materialization of this manifest or hand-edit of the plan; falling
   back to the plan's literal single-file Partition Map reintroduces the stale-number defect described in #1.
3. **The regeneration step must run the script, never hand-edit the file** — `docs/superpowers/dogfood/README.md`
   is machine-generated with byte-identical idempotence as F1's own acceptance criterion; a hand edit would
   desync it from what a future `bash scripts/compound-v-dogfood-index.sh` run produces and silently fail F1's
   own idempotence guarantee on the next unrelated run.
4. **The new section's sentence copies `N` and `A` verbatim from the regenerated footer's `Reviews: N` and
   `APPROVED: A` tokens** — not the footer's own wording (which uses `·` separators and also carries `ISSUES`/
   `other`, neither of which the section surfaces) and not independently recomputed from the file corpus.
5. **The link to `docs/superpowers/dogfood/README.md` must be a real markdown link, written path-relative-to-root
   with no leading slash** (`docs/superpowers/dogfood/README.md`, not `/docs/superpowers/dogfood/README.md`), so
   it is both caught by the repo's dead-link CI gate (a leading-slash form is silently exempted, per §5) and
   consistent with every other intra-repo link already in `README.md`.
6. **Insertion point: before the current last `##` heading**, today `## Under the hood (for the curious)`
   (`README.md:136`) — re-verify this at implementation time rather than trusting this audit's line number, since
   `README.md` is high-churn (§5). Follow the file's own `blank / --- / blank` section-boundary convention on
   both sides of the new section, matching 7 of the file's 8 existing transitions.
7. **F2 has no automated check that the footer is itself accurate** — only that `README.md`'s numbers equal
   whatever the (regenerated) footer says. This is an explicit, accepted spec-level decision (`readme-section.md:8`,
   "a test-shaped check is not required (docs-only)... the reviewer verifies the equality by reading both files"),
   not a gap for F2 to close. The known, currently-dormant residual risk this leaves open is F1 review-2's item
   A2 (§3) — a self-quoting verdict line could someday feed a wrong `APPROVED` count into F2's output with no
   automated signal — recorded here as inherited, not introduced by F2, and out of F2's write scope to fix.
8. **`scripts/lint-frontmatter.py` and the anti-ruflo CI grep are both structurally inapplicable to this edit**
   (§5, verified by reading their scoping logic, not assumed from the AC's wording) — no implementation effort is
   owed defending against either.

## 8. File Touch Map

| Path | Action | Notes |
|---|---|---|
| `README.md` (repo root) | MODIFY | Insert one `## Verification program` section before the current last `##` heading. High historical co-change frequency across unrelated release tasks (§5) — no other job in *this* manifest also writes it (disjoint within-run), but flag as a conflict risk if any other epic/feature runs concurrently against the same branch. |
| `docs/superpowers/dogfood/README.md` | REGENERATE (`bash scripts/compound-v-dogfood-index.sh`; never hand-edited) | **SHARED RESOURCE** — generated output, cross-feature boundary (F1 → F2). Committed content is stale by one row as of this audit (§1). Not authorized by the raw spec's "Files: README.md only" line, but required by the already-materialized `manifest.yaml`'s `index-refresh` job — see constraint #2. Byte-identical idempotence is F1's own acceptance criterion; a second run must change nothing. |
| `scripts/compound-v-dogfood-index.sh`, `tests/test-dogfood-index.sh` | READ/RUN only, not modified | F1's generator + test, read in full (§3). Confirmed correct and mutation-tested as of `2026-09-03-verification-index-review-index-r3` (**APPROVED**). |
| `docs/superpowers/dogfood/*review*.md` (33 files today, per §1's census) | READ-ONLY input to the regeneration step | Not touched by F2 directly; their count is what makes the committed footer stale (§1). |
| `docs/superpowers/execution/epics/2026-09-03-verification-index/specs/readme-section.md` | Out of this run's `write_allowed`, but textually stale ("Files: README.md only" undercounts the true write surface, §7#2) | Same class of residual F1's own spec left behind (its review-2, item 3: `specs/review-index.md` still names a stale discovery glob) — recorded, not fixed, since neither file is in this run's write scope. |
| `docs/superpowers/plans/2026-09-03-epic-vi-readme-section.md` | Out of this run's `write_allowed`; Partition Map (single `Task A` row) understates the true write surface versus the materialized `manifest.yaml` | Same drift as the spec — flagged so a plan regeneration does not silently drop the `index-refresh` task. |
