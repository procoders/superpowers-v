# F2 `matcher-docs` — one glob contract, stated once — spec

**Goal.** After F1, `skills/compound-v/memory.md` (the recall→action section that describes `recall-check`'s
file matching) and `skills/compound-v/execution-manifest.md` (the `write_allowed` glob semantics) say the same
thing in the same words: `*` within one segment, `**` across segments, `dir/**` also matches `dir`, `?` one
non-`/` character, `[` and `]` literal, anchored to the full repo-relative path; recall-check adds that a bare
path with no wildcard means "this path or anything under it". Each file names the other as the same contract
and names the proof: the parity rows in `compound-v-memory.py --selftest`.

**Files.** Modify `skills/compound-v/memory.md` and `skills/compound-v/execution-manifest.md` only. Both
files exist; find the current wording with `grep -n -i 'fnmatch\|glob' <file>` and replace it — do not add a
second description elsewhere in either file. Lines ≤ 200 characters; every relative link must resolve (the
CI dead-link gate).

**Acceptance criteria.** `grep -n fnmatch skills/compound-v/memory.md skills/compound-v/execution-manifest.md`
finds nothing; both files contain the phrase "the same matcher" and a reference to the parity selftest;
`/usr/bin/python3 scripts/lint-frontmatter.py` clean; the dead-link check passes.

## Amendment (2026-09-03, orchestrator, before F2's pre-flights)

`grep -n -i 'fnmatch\|glob' skills/compound-v/execution-manifest.md` shows the manifest contract never states the glob
semantics at all — `write_allowed` is described as "Glob list this job MAY write" (line 53) and the semantics live only in
`scripts/compound-v-scope-check.py`'s docstring. So F2 **adds** a short "Glob semantics" note directly under the
`write_allowed`/`read_allowed` rows of the field table in `execution-manifest.md` (one paragraph, the six rules above, the
recall cross-reference and the parity-selftest pointer), and **replaces** the `recall-check` row's wording in
`memory.md` (line 54) with the same rules plus the bare-path reading. No other section of either file changes.

## Pre-flight amendments (2026-09-03, after 1A archaeology and 1C library audit; 1B skipped — docs-only)

1. **Placement in `execution-manifest.md`:** the paragraph cannot sit between the `read_allowed` row and the next row (the table
   is contiguous through the `acceptance` rows). It goes after the end of the "Per-job fields" section — after its footnote and
   its one trailing paragraph — and before the `### Tier vocabulary` heading.
2. **`memory.md` edit is a same-line-count replacement:** one physical line in, one out, no blank lines added or removed —
   `docs/superpowers/architecture/architecture.md` anchors line numbers into `memory.md`.
3. **The bare-path reading is recall-check only.** The enforced gate (`matches`/`is_allowed`) has no such sugar; the
   `execution-manifest.md` paragraph must not imply it applies to `write_allowed`/`read_allowed`.
4. **Wording identity, decided:** the six-rule sentence is character-identical in both files; each file then adds its own one
   sentence (the manifest names the gate and links `memory.md`; memory.md adds the bare-path reading and links back).
5. **Proof pointer by name, not line number:** "the `parity …` rows of `python3 scripts/compound-v-memory.py --selftest`".
6. **Line length:** no script enforces 200; both files already carry longer lines. New prose in `execution-manifest.md` wraps at
   ≤ 120; the rewritten `memory.md` row stays ≤ the file's longest existing line.
7. **`lint-frontmatter.py` and `grep fnmatch` are not proof of work** (both vacuous for these files); the content checks are the
   two `grep -c "the same matcher"` counts and a visual diff of exactly the two hunks.
