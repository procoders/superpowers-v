# F1 `review-index` (dogfood review index generator) — Code Archaeology

Spec under audit: `docs/superpowers/execution/epics/2026-09-03-verification-index/specs/review-index.md`
Companion (depends on F1's output): `.../specs/readme-section.md` (F2).

## Step 0 — V-memory

Ran three `compound-v-memory.py search` passes (`dogfood review index generator markdown table`,
`dogfood directory review files VERDICT APPROVED ISSUES`, `verification index epic pass counting scorecard`).
No prior spec, ADR, or archaeology doc describes a "VERDICT line" parser, a dogfood index generator, or this
epic. The only relevant hits were the review files themselves (evidence, used below) and the v2.14.1 CI-discovery
fix (used in §3/§5). **V-memory returned nothing that pre-empts this feature** — it is genuinely new ground. The
index also reports **105 docs behind the repo** (stale — `/v:memory-refresh` not run this session); this does not
change the above conclusion since the gap is recent dogfood/CHANGELOG churn, not a missed design doc.

## 1. Matrix — real filename/content shapes vs. the spec's stated parsing rules

There is no existing script to branch-audit (F1 is new code). The load-bearing "existing reality" here is the
**live corpus** the script will run against: `docs/superpowers/dogfood/*review*.md` today matches **35 files**.
Read every one of them (`Glob` + `Grep`, not memory). The matrix below is filename/content shape × whether the
spec's literally-stated rules (as written in `review-index.md`) handle it correctly, verified against real files.

| Shape | Real example(s) | Spec rule as written | Result |
|---|---|---|---|
| Bare feature, no pass suffix | `2026-09-02-df10-review.md` | `pass`=1 when absent | Handled |
| Feature name that itself contains "review" (via "review**er**") | `2026-09-02-df11-reviewer-retry-review.md` | feature = "text between date and `-review`" | **Ambiguous/unhandled** — see §2 `feature` |
| **`-impl.md` file whose feature slug contains "reviewer"** | `2026-09-02-df11-reviewer-retry-impl.md`, `df12-reviewer-third-impl.md`, `df13-reviewer-fourth-impl.md`, `df15-reviewer-fifth-impl.md` | Discovery = "every `*review*.md`" | **Matches the glob, is not a review file** — see §2 `discovery` |
| Explicit pass 1..N, uniform | `2026-09-03-v3.4.1-triage-size-review-1.md` … `-3.md` | `-N` suffix, numeric | Handled if pass regex is `[0-9]+` (not `[0-9]`) |
| Implicit pass 1, then explicit 2..10 | `2026-09-02-v3.4-native-first-review.md`, `-review-2.md` … `-review-10.md` | "1 when absent" | Handled, **but pass reaches double digits (10)** — see §2 `pass` |
| `## VERDICT: **ISSUES** (N)` — markdown H2 heading prefix | all 10 `v3.4-native-first-review*.md`, `df20-final-review.md`, `df11-reviewer-retry-review.md` (12 files) | `^\**VERDICT:?\**\s*(APPROVED\|ISSUES)` | **Fails to match** — see §2 `verdict` |
| `VERDICT: **ISSUES**` — bold wraps only the value, space precedes the asterisks | `df27-full-pass-review.md` | same regex | **Fails to match** — see §2 `verdict` |
| `**VERDICT: ISSUES**` / `**VERDICT: APPROVED**` — bold wraps label+value together | `v3.4.2-transcript-watch-review-*.md`, `v3.4.3-codex-sandbox-checkout-review-*.md`, `v3.4.1-triage-size-review-1.md` (bare form) | same regex | Matches |
| `VERDICT: ISSUES` — bare | `df10-review.md`, `df12/df13-reviewer-*-review.md`, `df18/df21-*-review.md` | same regex | Matches |
| No VERDICT line at all | `df15-reviewer-fifth-review.md`, `df19-clean-review.md`, `df22-closed-review.md`, `df24-review.md`, `df25-recall-reachable-review.md` | "else `unknown`" | Correctly falls to unknown — **but see the `set -e`/grep-no-match hazard in §5** |
| Multiple VERDICT-shaped lines in one file | `v3.4.1-triage-size-review-2.md` (lines 10 and 527), `-review-3.md` (lines 10 and 470) | "the **first** line matching" | Correctly requires first-match discipline; a `tail`/`grep -l`-only approach would be wrong here |
| Unrelated lowercase "verdict" mid-sentence | `df25-recall-reachable-review.md:68` — `` `verdict: pass` `` inside prose about a JSON gate field | regex is `^`-anchored | **Correctly excluded** by the line-start anchor — this is a part of the spec's regex that is already right and must not be "simplified" away |

**Precise count (verified by reading every matched file, not sampling):** of the 35 files the stated discovery
glob matches, 4 are non-review `-impl.md` files swept in by the substring "review" inside "review**er**". Of the
31 true review files, 26 contain a genuine uppercase `VERDICT` line; **13 of those 26 (50%, = 13/31 ≈ 42% of all
real review files) do not match the spec's literal regex** and would be mis-reported as `unknown` despite having
an unambiguous APPROVED/ISSUES verdict. The other 5 of the 31 correctly have no verdict line at all.

## 2. Shared State — the four computed fields per row

There is no runtime process state (this is a batch script), so I audit the four values the spec derives per row,
per file, the same way I'd audit a shared variable: where each is set, and where it silently goes wrong.

**`feature`** (spec: "the filename between the date and `-review`"):
- Correctly set when: the literal string `-review` appears exactly once, immediately before `.md` or `-N.md`
  (the common case — 31 of 35 files).
- **Ambiguous/wrong when a naive "first occurrence" strip is used**: `2026-09-02-df11-reviewer-retry-review.md`
  contains the literal substring `-review` **twice** — once inside `-review`**`er`**`-retry-` (an artifact of
  "reviewer" containing "review"), once as the real terminal suffix. A first-match strip (e.g. `sed
  's/-review.*//'`, or bash `${var%%-review*}` which removes from the **first** occurrence) yields
  `feature="df11"`, silently dropping `-reviewer-retry`. A last-match strip (bash `${var%-review*}`, which
  removes from the **last**, i.e. shortest-suffix, occurrence) correctly yields `feature="df11-reviewer-retry"`.
  The spec does not say which; git has no history to settle it because the script does not exist yet. **This is a
  MUST-FIX in the plan, not an implementation detail** — both a shell built-in and a naive regex are equally
  "idiomatic," and only one is right against this corpus.
- **Undefined for the 4 impl false-positives** (`df11/df12/df13/df15-reviewer-*-impl.md`): these end in `-impl.md`,
  not `-review.md` or `-review-N.md`, so a *correctly end-anchored* `feature` regex does not match them at all.
  The spec never says what a script does with a file the discovery glob matched but the parse regex rejects.

**`pass`** (spec: "the trailing `-N` after `review` (1 when absent)"):
- Correctly set for 1-digit N and the implicit-1 case in every file I found.
- **At risk for 2-digit N**: `2026-09-02-v3.4-native-first-review-10.md` is real and present. A pass-extraction
  regex written as `[0-9]` (single digit, an easy typo/copy-paste from "the trailing digit") will either fail to
  strip the `0` from `feature` or truncate `pass` to `"1"` — wrong either way. Confirmed necessary, not
  hypothetical: pass 10 exists today.
- **Sort key, not just a display field**: passes 1–10 exist for one feature (`v3.4-native-first`). A **lexical**
  sort on `pass` (plain `sort` on the string, no `-n`) orders them `1, 10, 2, 3, 4, 5, 6, 7, 8, 9` — wrong. This
  must be a numeric sort, verified necessary by the real corpus (not a "what if" — double digits exist now).

**`verdict`** (spec regex, quoted above): see the Matrix — 13 of 31 real files silently default to `unknown`
under the regex as literally written, because (a) the corpus's dominant format for one entire 10-pass series plus
2 others is `## VERDICT: ...` (H2 heading prefix, 12 files) which the regex's `\**` (asterisks only) cannot match,
and (b) one file (`df27-full-pass-review.md`) has the bold asterisks *after* the whitespace rather than before it,
which the regex's `\**\s*` ordering does not tolerate. Both are real, common, present-today shapes, not edge
cases invented for this audit.

**`date`** (spec: "the leading `YYYY-MM-DD` of the filename"): every one of the 35 matched filenames starts with
a well-formed `YYYY-MM-DD`. No gap found here — confirmed handled by a plain leading-prefix extraction.

**`discovery`** (spec: "every `*review*.md`"): this is a substring glob, not an anchored one. It is exactly
`ls docs/superpowers/dogfood/*review*.md` per the epic's own acceptance criterion (`review-index.md` line 18),
and that shell glob **does** match "review" as a substring of "review**er**" — confirmed by `Glob` returning the
4 impl files above. Since the acceptance criterion is pinned to this exact `ls` count, the plan cannot silently
switch to an end-anchored discovery pattern (e.g. `find ... -regex '.*-review(-[0-9]+)?\.md'`) without also
changing the acceptance criterion — doing so would make the row count *not* equal `ls *review*.md | wc -l` and
fail F1's own stated test. This is a genuine tension in the spec as written: the **discovery** pattern and the
**per-file parse** pattern must either (a) both stay loose and the plan must define row content for a file that
matches discovery but not parse, or (b) the acceptance criterion's count formula is amended alongside a tighter
discovery pattern. Either is fine; leaving it unresolved is not — the plan must pick one explicitly.

## 3. Sibling Code

No existing script in this repo parses dogfood review files, generates a table+footer index, or does anything
structurally identical to F1 — this is genuinely new ground, not an extension of a known path. Two adjacent
things exist and were read in full for applicable idiom, not as a gate to inherit:

- **`scripts/compound-v-dashboard.py`** — a *different* index generator (Python, indexes `docs/superpowers/execution/**`
  run/epic state into an HTML dashboard, not dogfood review docs). No `VERDICT` parsing, no shared code path. Not
  a duplicate of F1 and not extendable to become one (wrong language per spec's explicit "Bash 3.2 + git" mandate,
  wrong source directory, wrong output shape). Confirmed via `grep -n VERDICT` — zero hits.
- **`scripts/compound-v-run-codex-worker.sh:519-548`** — the established idiom in *this* repo for "a `grep` that
  is expected to sometimes find nothing, under `set -euo pipefail`": wrap the pipeline in `{ ... } || true` and
  say so in a comment (line 540-541: `` `set -euo pipefail` a no-match `grep` exits 1, which without this abort
  the worker before it can emit its job_result``). Every `.sh` file under `scripts/` that I checked
  (`compound-v-codex-review.sh:40`, `compound-v-run-cursor-worker.sh:60`, `compound-v-run-antigravity-worker.sh:51`,
  `compound-v-run-opencode-worker.sh:73`, `compound-v-run-devin-worker.sh:67`, `compound-v-advisor-consult.sh:59`,
  `test-advisor-worker-stub.sh:18`) opens with `set -euo pipefail`. **This is the sibling gate F1 inherits**: if
  F1's script also opens `set -euo pipefail` (a reasonable default consistent with every other script in
  `scripts/`) and does not apply the same `|| true` guard around its per-file VERDICT grep, it **will** abort on
  the first file (9 of 35 exist today, per §1/§2) whose VERDICT grep finds nothing — turning the spec's documented
  "else `unknown`" fallback into a hard script crash. This is not speculative: the corpus guarantees the no-match
  path is hit on every real run against the live directory.
- **Test-companion convention, not `--selftest`**: `CONVENTIONS.md:16` documents a `--selftest` flag convention,
  but that citation is specifically for *Python* scripts (`compound-v-scope-check.py`, `compound-v-onboard.py`).
  Every `.sh` script I found instead ships a **separate** `tests/test-*.sh` companion
  (`test-worker-path-transport.sh`, `test-advisor-worker-stub.sh`, `test-sandbox-checkout.sh`) — exactly what F1's
  spec proposes (`tests/test-dogfood-index.sh`). Confirmed alignment, not a gap.

No `git blame`/history exists for a prior version of this script — it has never existed — so there is no
"known-latent-bug in the sibling" to inherit beyond the `set -e`/no-match idiom above, which is itself the
lesson from a *past* incident (v2.8.1 hardening, per the comment's own citation) rather than a live bug today.

## 4. External APIs

None. F1 touches only the local filesystem, `sed`/`awk`/`grep`, and (per the spec's tool list) `git` — no
third-party service, no library with a version to pin, no HTTP contract. Context7 lookup is not applicable and
was not attempted; this section is intentionally empty rather than padded.

One local-tooling note worth recording since "git" is explicitly named as an allowed tool alongside bash/sed/awk:
if the implementation uses `git ls-files` for discovery instead of a plain filesystem glob, its result can
diverge from `ls docs/superpowers/dogfood/*review*.md` (the acceptance criterion's own count formula) whenever an
untracked review-shaped file sits in the working tree — a real possibility in *this* repo, which routinely
accumulates freshly-written, not-yet-committed dogfood review files mid-session. CI checks out a clean tree
(`actions/checkout@v4`) so this would not surface there, but it would surface locally. Not fatal, but the plan
should be explicit about which discovery mechanism is used and that it matches the criterion's `ls`-based count.

## 5. Regression Surface + DRY

**Regression scan** (what already works today that a bug in F1 could break):

- **`README.md`'s existing 7 sections** (`Requirements`, `🎮 New here?`, `Main features`, `How it routes the
  work`, `Install`, `How to use it`, `Good to know`, `Under the hood` — confirmed via `grep '^## '`) are read by
  F2, which inserts a new `## Verification program` section "before the last existing `##` section." F1 itself
  does not touch `README.md` (out of scope per its own "Files: Create `scripts/...`, `tests/...`" line), so no
  direct regression risk to README from F1 — but F1's **output correctness** is F2's **input contract**: F2's
  spec (`readme-section.md`) states the two published numbers ("N review files, A APPROVED") "must equal the
  footer... at the time of writing," verified by the reviewer reading both files, not by an automated check. If
  F1's `APPROVED` count is wrong because of the §1/§2 regex gap (13 real ISSUES/APPROVED verdicts undercounted
  into "other"), **F2 will publish a wrong number to `README.md` and the reviewer has no automated signal to
  catch it** — the cross-feature acceptance criterion only checks that F2's numbers match F1's footer, not that
  F1's footer matches reality.
- **CI's recursive test sweep** (`.github/workflows/validate.yml:344-361`, confirmed present, fixed in v2.14.1)
  auto-discovers any `tests/*.sh` or `tests/*.py` file with no manual registration — `tests/test-dogfood-index.sh`
  will run in CI automatically. Confirmed non-issue, not a gap: no separate wiring step is needed, unlike repos
  where a test list must be hand-maintained. Note for the plan: the sweep invokes tests as `LANG=C bash "$t"`
  (line 357) — if the script's footer literal contains the middle-dot separator (`·`, U+00B7, as specified: `"Reviews:
  N · APPROVED: A · ISSUES: I · other: O"`), that is a hardcoded UTF-8 byte sequence in the script source, not a
  locale-dependent computation, so `LANG=C` should not corrupt it — confirmed low risk, worth a footer
  byte-comparison in the test regardless since idempotence is an explicit acceptance criterion.
- **`scripts/lint-frontmatter.py`** (F2's acceptance gate) exempts every `.md` file outside `agents/*.md`,
  `commands/*.md`, `skills/*/SKILL.md` (confirmed by reading `lint-frontmatter.py:8-9`) — the newly-created
  `docs/superpowers/dogfood/README.md` needs no frontmatter and will not trip this linter. Confirmed non-issue.
- **V-memory FTS5 index** will pick up the new `docs/superpowers/dogfood/README.md` on the next
  `/v:memory-refresh` (it indexes `docs/superpowers/**` prose) — expected, benign, not a regression.

**DRY check**: searched `scripts/*.py` for any existing `VERDICT` parser to extend instead of duplicating.
Found two unrelated hits — `compound-v-integration-gate.py` (`VERDICTS = ("pass", "blocked", "error")`, a JSON
receipt field for the scope-gate's own machine verdict) and `compound-v-transcript-watch.py` (an `exit code
[1-9]` pattern, a different "verdict" concept entirely). **Neither parses the markdown "`VERDICT: APPROVED |
ISSUES`" free-text convention F1 needs.** There is no duplicate to extend or refactor — F1's parser is genuinely
new, which also means there is no prior battle-tested regex to lean on: the spec's own regex is the only
definition that exists anywhere in this codebase, and §1/§2 show it needs to be fixed before implementation, not
copied from elsewhere.

## 6. Design constraints for the spec (non-negotiable)

1. **Fix the `verdict` regex to accept `## VERDICT: ...` (H2 heading prefix).** This is not a rare shape — it is
   the format used by an entire 10-pass review series (`v3.4-native-first`) plus 2 more files, 12 of the 31 real
   review files, the single largest format bucket in the corpus. As written, the spec's regex fails on it.
2. **Fix the `verdict` regex's bold-tolerance so `VERDICT: **ISSUES**` (asterisks after the label+colon, before
   only the value) also matches**, not just `**VERDICT: ISSUES**` (asterisks wrapping label+value together).
   Confirmed present today (`df27-full-pass-review.md`).
3. **Every per-file grep against the VERDICT pattern must be `|| true`-guarded** (or otherwise made
   fail-non-fatal), following the established idiom at `scripts/compound-v-run-codex-worker.sh:519-548`. Under
   `set -euo pipefail` — the convention every other `.sh` script in `scripts/` uses — a no-match grep exits
   non-zero and aborts the script. 9 of the 35 files discovery matches today (5 true reviews with no verdict line,
   4 impl false-positives) are **guaranteed** to hit this path on the very first real run.
4. **Resolve the discovery-vs-parse tension explicitly**: `*review*.md` (the spec's stated discovery glob, pinned
   to the acceptance criterion's `ls *review*.md | wc -l`) matches 4 files
   (`df11/df12/df13/df15-reviewer-*-impl.md`) that are not review files at all — their feature slug merely
   contains "review" via "review**er**." The plan must state what a row looks like for a discovered file whose
   filename does not end in `-review[-N].md`, or change the discovery/count mechanism and its acceptance
   criterion together. Silence here means an implementer's arbitrary choice becomes the behavior.
5. **`feature` extraction must strip from the LAST occurrence of `-review`, not the first.** Confirmed necessary:
   `df11-reviewer-retry-review.md` contains the literal substring `-review` twice (once inside "review**er**").
   A first-occurrence strip silently truncates to `feature="df11"`, losing `-reviewer-retry`.
6. **`pass` extraction and its sort must handle 2-digit numbers.** `v3.4-native-first-review-10.md` exists today.
   A `[0-9]` (singular) regex mis-parses it; a lexical (non-numeric) sort on `pass` orders 1,10,2,3…9.
7. **`verdict` under-counting is not cosmetic — it propagates to F2's published README numbers**, which the
   epic's own acceptance criteria treat as human-reviewer-verified but not automated-verified. A wrong F1 footer
   becomes a wrong, merged, published claim in `README.md` with nothing to catch it downstream.
8. **The `^`-anchor on the verdict regex is correct and must be kept.** `df25-recall-reachable-review.md:68`
   contains an unrelated lowercase `` `verdict: pass` `` mid-sentence (a JSON gate-field reference); the anchor
   is what keeps this from being a false-positive match. Any "simplification" to a bare substring search would
   reintroduce this failure mode.
9. **If `git` is used for file discovery (not just incidental version-control operations), it must not diverge
   from the `ls`-based count the acceptance criterion is pinned to** — `git ls-files` and a filesystem glob can
   disagree in the presence of untracked review-shaped files, which this repo routinely has mid-session.

## 7. File Touch Map

| Path | Action | Notes |
|---|---|---|
| `scripts/compound-v-dogfood-index.sh` | CREATE | New file, no existing consumers, no shared-resource conflict. |
| `tests/test-dogfood-index.sh` | CREATE | Auto-discovered by CI's recursive sweep (`.github/workflows/validate.yml:344-361`) — no manual test-registry edit needed anywhere. |
| `docs/superpowers/dogfood/README.md` | CREATE (generated) | **SHARED RESOURCE (cross-feature boundary)** — F2 (`readme-section.md`, depends_on this feature) reads this file's footer counts directly to populate `README.md`. Its exact final byte content is F2's input contract, not just this feature's own output. |
| `docs/superpowers/dogfood/*review*.md` (35 files today) | READ-ONLY input | Not modified. Their real filenames/content are the load-bearing contract validated in §1/§2 above — any fixture used by `tests/test-dogfood-index.sh` should be modeled on these actual shapes (heading-prefixed VERDICT, double-digit pass, the "review**er**" collision), not an idealized subset. |
| `README.md` (repo root) | Out of scope for F1 | Touched by F2 only; F1's spec explicitly excludes it ("Files: Create `scripts/...`, `tests/...`"). |
