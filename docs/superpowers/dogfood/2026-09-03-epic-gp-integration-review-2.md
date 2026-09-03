# Final cross-feature re-verification — epic `2026-09-03-glob-parity` · PASS 2

- **Epic:** `2026-09-03-glob-parity` (F1 `one-matcher`, F2 `matcher-docs`)
- **Reviewer:** fresh spec-reviewer, no context from pass 1
- **Tree reviewed:** `21e7dff` (the two doc/script files under review are byte-identical to `23b811c`:
  `git diff --stat 23b811c..HEAD -- skills/compound-v/execution-manifest.md skills/compound-v/memory.md
  scripts/compound-v-memory.py scripts/compound-v-scope-check.py` is empty)
- **Pass 1:** `docs/superpowers/dogfood/2026-09-03-epic-gp-integration-review.md` → ISSUES (2 items)
- **Fix commits under review:** `c680501` (three `?` parity rows + the `read_allowed` correction),
  `23b811c` (glob-semantics paragraph reflowed to ≤120 columns)

Ledger, quoted verbatim:

```
$ python3 scripts/compound-v-epic-state.py --stats --state docs/superpowers/execution/epics/2026-09-03-glob-parity/epic-state.json
{"epic_id": "2026-09-03-glob-parity", "status": "running", "total": 2, "done": 2, "pending": 0, "running": 0, "failed": 0, "remaining": 0, "blocked": 0}
```

`blocked: 0` and the ledger's `blockers` field is absent — no `blocked_external` verdict exists in this
epic, so the confirmed-blocker integrity check (§2.6) has no subject and is not applicable.

## Scope

Re-verification only: the two pass-1 items, plus pass-1 criteria 1 and 3 re-run from scratch on the
current tree. No new implementation was reviewed; `c680501` is +3 lines in `scripts/compound-v-memory.py`
and a one-line header change in `skills/compound-v/execution-manifest.md`, `23b811c` is a 6-line reflow of
the same paragraph. Nothing else in the repository was read as under review.

## Pass-1 items

### Item 1 (MEDIUM) — no parity row exercised the `?` rule → CLOSED

Three rows now exist, at `scripts/compound-v-memory.py:1640-1642`:

```python
# `?` is one non-`/` character (final integration review of epic 2026-09-03-glob-parity:
# the rule was documented in both files and asserted nowhere)
("src/?.py", "src/a.py", True), ("src/?.py", "src/ab.py", False), ("a?b", "a/b", False),
```

Green on the current tree — `/usr/bin/python3 -B scripts/compound-v-memory.py --selftest`:

```
  ok   parity src/?.py ~ src/a.py
  ok   parity src/?.py ~ src/ab.py
  ok   parity a?b ~ a/b
0 failed
all self-tests passed
```

**Load-bearing, proved by mutation.** In a scratch copy of `scripts/` (outside the repo, under the
session scratchpad — the repository working tree was never touched; `git status --porcelain` is empty
before and after), `scripts/compound-v-scope-check.py:365` was changed from `out.append("[^/]")` to
`out.append(".")`, i.e. `?` made to cross `/`. Running the scratch `compound-v-memory.py --selftest`
against that scratch matcher:

```
  ok   parity src/?.py ~ src/a.py
  ok   parity src/?.py ~ src/ab.py
  FAIL parity a?b ~ a/b
1 failed
FAILED: parity a?b ~ a/b
```

The row catches the mutation on both halves of the assertion — the check is
`_scope(path, pat) is want and _file_matches(path, [pat]) is want`, so a wrong-but-agreeing pair of
matchers still fails against the `want` constant. That closes the specific hole pass 1 named: with `?`
delegated to a single matcher, parity alone would have been satisfied by two matchers wrong in the same
way; the `want` column is what makes the row an assertion about the rule rather than about agreement.
The two `src/?.py` rows are insensitive to this particular mutation (`.` still matches exactly one
character in `src/a.py` and still fails two in `src/ab.py`) — the brief asked for at least one, and
`a?b ~ a/b` is it.

### Item 2 (LOW) — `read_allowed` named as a subject of the gate's matcher → CLOSED

`skills/compound-v/execution-manifest.md:64` now reads:

```
**Glob semantics (`write_allowed`, `impacted_map.when`; `read_allowed` is advisory, never matched).**
```

Every other mention of `read_allowed` in that file is consistent: `:54` ("**ADVISORY only — NOT
enforced** (git cannot track reads)"), `:206` (auto-inclusion), and `:275-277` (the dedicated "Only
`write_allowed` is enforced; `read_allowed` is advisory" section, ending "Do not present it as enforced
anywhere"). `skills/compound-v/memory.md` contains **zero** occurrences of `read_allowed` — its
recall-check row scopes itself to lane globs and `write_allowed` (`:84`), so it never made the claim.

## Criteria

| # | Criterion | Evidence | Status |
|---|---|---|---|
| a | `--selftest` prints the three new `parity` rows as ok and `0 failed` | `/usr/bin/python3 -B scripts/compound-v-memory.py --selftest` → three `ok parity …?…` rows, `0 failed`, `all self-tests passed` | PASS |
| b | The `?` rows are load-bearing | scratch-copy mutation of `compound-v-scope-check.py:365` (`[^/]` → `.`) → `FAIL parity a?b ~ a/b`, `1 failed`; repo tree untouched | PASS |
| c | Six-rule sentence agrees clause for clause in both files; paragraph ≤120 cols | clause table below; `execution-manifest.md:64-69` = 101/114/112/101/108/114 chars | PASS |
| d | `read_allowed` no longer described as matched by the gate in either file | `execution-manifest.md:54,64,206,275-277`; `memory.md`: no occurrence | PASS |
| e1 | Pass-1 criterion 1 — both selftests green | memory `all self-tests passed` / `0 failed`; `compound-v-scope-check.py --selftest` → `SELFTEST PASSED` | PASS |
| e3 | Pass-1 criterion 3 — no leftovers from the reverted F2 attempts; links resolve | one occurrence of the glob paragraph per file (no duplicate/orphan copy); `git status --porcelain` empty; no `.orig`/`.rej`/`.bak` anywhere; `import fnmatch` gone from `compound-v-memory.py`; all four cross-referenced paths exist | PASS |

### (c) clause-for-clause

| # | `execution-manifest.md:65-67` | `memory.md:54` | Agree |
|---|---|---|---|
| 1 | `*` matches within one path segment (never `/`) | identical | ✅ |
| 2 | `**` matches across segments | identical | ✅ |
| 3 | `dir/**` also matches `dir` itself | identical | ✅ |
| 4 | `?` matches one non-`/` character | identical | ✅ |
| 5 | `[` and `]` are literal (no character classes — `app/[locale]/**` is a real directory) | identical | ✅ |
| 6 | matching is anchored to the full repo-relative path | identical | ✅ |

Same six clauses, same order, same wording. The two files differ only in the surrounding framing, and the
two framings are consistent: `execution-manifest.md:67-69` names the owner ("This is the scope gate's own
matcher (`scripts/compound-v-scope-check.py` `matches`), and V-memory's `recall-check` uses the same
matcher") and `memory.md:54` names the borrower ("with the same matcher as the scope gate"). Each links to
the other and both cite the `parity …` selftest rows as the proof. `memory.md:54`'s recall-check-only
addition — a bare path with no wildcard means "this path or anything under it", explicitly flagged as
something "the enforced gate has no such reading" — is a documented divergence in the *caller*, not in the
six rules, and `compound-v-memory.py:1648-1649` asserts it (`bare dir == dir/**`).

**On the 120-column rule.** It is met where it was asked for: the reflowed paragraph,
`execution-manifest.md:64-69`, is 101-114 characters per line. `memory.md:54` is a single 758-character
markdown **table row**, which cannot be wrapped without breaking the table; it is out of scope for a
column rule and unchanged by either fix commit. The four other >120 non-table lines in `memory.md`
(`:90`, `:115`, `:174`, `:200`) all pre-date this epic (`git blame`: `e0125035`, `32da05f0`, `9276d889`,
`6be93a3d`), and `execution-manifest.md` has never carried a repo-wide ≤120 convention (`:3`, `:9`, `:30`,
`:60`, `:62`, `:101` are all longer). No regression, no new finding.

### Test evidence

Docs + selftest change; the floor is the two selftests, and I ran both myself rather than accepting a
report:

| Command | Result |
|---|---|
| `/usr/bin/python3 -B scripts/compound-v-memory.py --selftest` | `0 failed` · `all self-tests passed` |
| `/usr/bin/python3 -B scripts/compound-v-scope-check.py --selftest` | `SELFTEST PASSED` |

### Anti-ruflo / reward-hack sweep

`c680501` **adds** three assertions and loosens nothing; `23b811c` is whitespace-and-wrapping only. No
assertion removed, no threshold relaxed, no test skipped, no scorer edited, no fabricated metric — the
only numbers in either diff are the parity `want` booleans, and the mutation run above shows they bite.

## Verdict

Both pass-1 items are closed on the current tree, and pass-1 criteria 1 and 3 still hold. The `?` rows are
not decoration: a one-character weakening of the shared matcher turns the suite red. Nothing was written
into the repository by this review except this file.

VERDICT: PASS
