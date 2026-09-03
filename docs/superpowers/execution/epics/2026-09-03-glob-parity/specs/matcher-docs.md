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
