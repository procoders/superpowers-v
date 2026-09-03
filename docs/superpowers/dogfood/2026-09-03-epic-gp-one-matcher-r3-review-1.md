# Review Gate — F1 `one-matcher` attempt 3 · run `2026-09-03-glob-parity-one-matcher-r3`

Three-pass `spec-reviewer` gate over the merged wave-1 commit `70cdfa1` (job `load-bearing-row`,
worktree `wf_8eb3aec3-b82-1`, realised `c83e9dc`), against
`docs/superpowers/plans/2026-09-03-epic-gp-one-matcher-r3.md` and the finding it exists to close —
`docs/superpowers/dogfood/2026-09-03-epic-gp-one-matcher-r2-review-1.md` **§3 (ACCEPTANCE_GAP /
TEST_GAP, blocking): the attempt-2 row was not load-bearing**.

**VERDICT: APPROVED** — §3 is **closed**. The row now fails the moment the `if err is None:` guard is
removed. Reproduced live by me, from source, three ways (§SPEC 3). One LOW reporting finding, recorded
below and explicitly non-blocking.

---

## Recall

| Probe | Result |
|---|---|
| `compound-v-memory.py search "fail-closed selftest bytecode cache guard" --intent review --top 8` | 8 hits, all on-topic: the r3 plan (Task A, Global Constraints, Step 2), the r2 plan, the attempt-1 sample-audit, and the attempt-2 review's §3 and §4. Nothing contradicting the plan; nothing settled that this review re-litigates. |
| `compound-v-memory.py recall-check --files scripts/compound-v-memory.py` | `recall-check: none (0/2 match on scripts/compound-v-memory.py)` — **no `tighten` verdict**. No control escalated on recall grounds. |

The one constraint recall carries into this review, quoted from the r3 plan's **Global Constraints**:
*"Only `scripts/compound-v-memory.py` changes, and only inside `_selftest`: the block that starts at the
comment `# fail-closed: when the private bytecode cache cannot be created` and ends at the
`check("no private bytecode cache -> unavailable, nothing loaded", …)` call is replaced by the block
below. Nothing else moves."* Prose and code agree; verified in §SPEC 1–2 rather than taken on the plan's
word.

Recall's second contribution is the *reason the r2 recipe was worthless*, and the r3 plan encodes the fix
in its own Global Constraints: `_SCOPE_CHECK_PATH` derives from `__file__`'s directory, so a guardless
copy with no sibling `compound-v-scope-check.py` beside it dies before the row runs. Every proof below
copies both files side by side.

---

## SPEC

### 1. Scope lock

| Check | Evidence |
|---|---|
| Files written vs `write_allowed: [scripts/compound-v-memory.py]` | `git show --stat 70cdfa1` → `scripts/compound-v-memory.py │ 22 +++++-------` — one file, `+15/-7` |
| Deterministic gate | `receipts/load-bearing-row.gate.json` → `verdict: "pass"`, `violations: []`, `diff_digest sha256:d4f08809…`, baseline `c83e9dc` |
| Stray artifacts (`.pyc` and friends) | `git status --porcelain` on the merged tree shows only this review job's own lane bookkeeping. Nothing left behind by the implementer. |

No scope violation. The gate ran, passed, and I confirmed it at the seam.

### 2. Spec coverage

| Plan step | Implemented in | Status |
|---|---|---|
| Step 1 — **replace** the fail-closed block (comment through `check(...)`) with the plan's snippet | `scripts/compound-v-memory.py:1658-1682`. Extracted the plan's fenced `python` block and the file's block and compared them programmatically: **byte-identical**, 25 lines each. | OK |
| Step 1 — replace, not duplicate | `grep -c 'no private bytecode cache' scripts/compound-v-memory.py` → **`1`** | OK |
| Step 2 — the row FAILS on a guardless copy, both files side by side | reproduced by me; see §3 | OK |
| Step 3 — both selftests green | `memory --selftest` → `83 ok / 0 failed / all self-tests passed`; `scope-check --selftest` → `SELFTEST PASSED` | OK |
| Step 4 — commit in the worktree | `c83e9dc`, merged as `70cdfa1` | OK |
| Job `acceptance` — *"REAL ok / GUARDLESS FAIL lines quoted verbatim in your summary"* | `results/load-bearing-row.json` `summary` is the harness-default job title verbatim: `"Task A — replace the attempt-2 row with a load-bearing one (spy on spec_from_file_location)"`. No proof line reported; `log: null`. | **LOW finding — see §6** |

### 3. The attempt-2 §3 finding is CLOSED — reproduced, three ways

I did not take the row's title for its behaviour. Guardless copy built by replacing
`        if err is None:\n            spec = ` with `        if True:\n            spec = ` (1 occurrence,
`scripts/compound-v-memory.py:1089`), both files copied into one scratch directory first.

**(a) The plan's Step 2, run verbatim.** Both lines quoted exactly as printed:

```
REAL:
  ok   no private bytecode cache -> unavailable AND the sibling was never loaded
GUARDLESS:
  FAIL no private bytecode cache -> unavailable AND the sibling was never loaded
```

The guardless copy's tail confirms the row is the *only* thing that broke — the removal is not
collaterally tripping something else:

```
  FAIL no private bytecode cache -> unavailable AND the sibling was never loaded

1 failed
FAILED: no private bytecode cache -> unavailable AND the sibling was never loaded
```

This is the exact inversion of attempt 2, where the guardless copy also printed `ok`.

**(b) Marker instrumentation — the row now tracks the real side effect.** The same two copies beside a
`compound-v-scope-check.py` whose first line appends one byte to a `MARKER` file on execution, so the
marker counts actual sibling executions during one `--selftest`:

| Copy | selftest result | `MARKER` bytes = sibling executions |
|---|---|---|
| real | `0 failed / all self-tests passed` | **1** (the parity rows' one legitimate load) |
| guardless (`if True:` at `:1089`) | **`1 failed`**, and the failure is this row | **2** — the extra unredirected execution the guard exists to prevent |

Attempt 2's table had the identical marker counts and *both* copies green. The behavioural difference the
guard controls was always observable; the row is now the thing that observes it.

**(c) A probe the plan did not ask for — the assertion also fails-closed if the patch goes inert.**
Attempt-2 review §QUALITY item 6 warned that `_no_cache` is never asserted called, so a refactor that
stops routing through `tempfile.mkdtemp` would leave the patch inert and the row green for an unrelated
reason. I simulated exactly that: a copy whose `_no_cache` delegates to the real `mkdtemp` instead of
raising, guard untouched.

```
  FAIL no private bytecode cache -> unavailable AND the sibling was never loaded
```

It fails. With the cache created, `err` is `None`, the loader reaches `spec_from_file_location`, the spy
records a call, `_sfl_calls == []` is false. The spy closes item 6 as a side effect of closing item 4 —
the row cannot go quietly green through either failure mode.

**Why it works, stated against the code.** `:1089`'s guard governs whether the module is *executed*, not
the returned verdict — `err` is already set by the `except` above, and `:1105-1109` raises the identical
message either way. That is precisely why attempt 2's verdict-only assertion could not fail. The new
conjunct `_sfl_calls == []` asserts on the side effect itself, which is the only observable that differs.

**Attempt-2 review §3: CLOSED.** So is the sample-audit's finding 1 behind it.

### 4. Audit / pre-flight constraint check

| Source | MUST | Satisfied | Notes |
|---|---|---|---|
| Pre-flight amendment 1 (`specs/one-matcher.md`) | fail closed — nothing loaded when the private bytecode cache cannot be created | OK | Production behaviour at `:1084-1090` unchanged and still correct; it now has a guard test that can fail for it |
| Attempt-2 review §3 | a row that FAILS when the `:1089` guard is deleted | OK | §3(a), (b) |
| Attempt-2 review §QUALITY item 5 (LOW) | fix the Step-2 recipe that proved nothing | OK | The r3 plan copies the sibling and states why in Global Constraints. I ran the recipe verbatim; it works. |
| Attempt-2 review §QUALITY item 6 (LOW) | the row must not stay green if the `mkdtemp` patch goes inert | OK | §3(c) — closed, though not by design; the spy covers it incidentally |
| Plan Global Constraints | only `scripts/compound-v-memory.py`, only inside `_selftest` | OK | `_selftest` spans `:1258`–`:1694`; every hunk header is `def _selftest()`, hunks at `:1658-1682` |
| Plan Global Constraints | one row in, one row out; no production change | OK | §QUALITY 2 |

### 5. Over-build

Clean. `+15/-7`, byte-identical to the plan's snippet — no extra flag, helper, export, abstraction or
logging, and nothing added beyond the block the plan specified.

### 6. LOW — the worker's summary again carried no proof (non-blocking)

The job `acceptance` asked the worker to quote the REAL/GUARDLESS lines into its summary; the summary is
the job title verbatim, for the **second consecutive attempt** (attempt 2 did the same). I am not blocking
on it, and the reason is not "close enough":

- Pass 1 §1.4 verifies the job acceptance *met by the diff*; a summary is not a property of a diff.
- DONE is gated on the manifest's feature `acceptance_criteria`, and criterion 1 assigns the quoting to
  whoever reproduces the proof. The r3 plan's Task R assigns that to this review explicitly
  (*"reproduce Step 2 yourself"*). I did — three times, from source.
- An independent re-derivation is **stronger** evidence than a worker's self-report of the same run. Failing
  the merge to make a worker paste back a line I already verified myself would be process theater, and
  would spend a whole attempt 4 on a string.

The systemic half is worth recording, and belongs to the manifest rather than to this diff: two attempts
running, the job body asked for proof in `summary` and got the default title. If that field is meant to
carry evidence, something has to make the worker fill it; asking in prose has now failed twice. Candidate
for the epic's next manifest pass — not a defect in this change.

**PASS 1 SPEC: OK.**

---

## QUALITY

Ranked; nothing withheld for a later round.

| # | Severity | Check | Result |
|---|---|---|---|
| 1 | — | **2.5 reward-hacking** | **None, and this is the check that matters most here** — the diff edits a test file, which is exactly where a gamed gate would live. Diffed every `check()` title before vs after: **74 before, 74 after**, and `diff` reports exactly **one changed line** — this row's title, strengthened. No row removed, renamed away, skipped or commented. The new assertion is a strict superset of the old one (`verdict` AND `note` AND `_sfl_calls == []`); no threshold moved, no exception newly swallowed. The scorer (`check`/`fails`) is untouched, and so is `scripts/compound-v-scope-check.py` (last touched at `0d751b1`, a different run). A change that makes a test *harder to pass* and then proves it fails on a planted defect is the opposite of a reward hack. |
| 2 | — | **2.4 fabricated metrics** | None. No count, saving, percentage or duration is printed, logged or documented anywhere in the diff. |
| 3 | — | **2.2 regression** | None. `83 ok / 0 failed` (unchanged — one row replaced, not added, consistent with `+15/-7`); `scope-check --selftest` `SELFTEST PASSED`. No signature changed, no export removed, no caller touched, no production line in the diff. |
| 4 | — | **2.3 test alignment** | Satisfied, and it is the point of the change. The MUST from pre-flight amendment 1 now has a row that fails when the guard is removed (§SPEC 3a), fails when the patch goes inert (§SPEC 3c), and fails for that reason alone (`1 failed`). |
| 5 | LOW | evidence reporting | §SPEC 6. Non-blocking; belongs to the manifest, not the diff. |
| 6 | INFO | `:1661-1675` | The spy patches the module-global `importlib.util.spec_from_file_location` for the duration of one `recall_check` call. Correct here — `finally` restores it, `_spy_sfl` delegates to the real function so behaviour is unchanged, and the real copy empirically records **zero** calls, so nothing else in the window is importing by file location. Same process-global-mutation-in-a-test note the attempt-2 review raised about `tempfile`; noted, not a defect. |
| 7 | INFO | `:1670` | `_sfl_calls.append(a)` keeps positional args only, not kwargs. Harmless — the assertion is on emptiness, and storing args at all is only useful for a failure message the row does not print. |
| 8 | INFO | `:1673`, `:1677-1678` | Two statements on one line, and tuple-form save/restore of two globals. Matches the existing idiom at `:1650`/`:1654` and the block it replaced. Consistency, not a lapse. |

**PASS 2 QUALITY: OK** (one LOW, non-blocking; three INFO).

---

## INTEGRATION

### Partition & seams

Single-job wave. One file, one function, no shared type, no barrel, no registry — no partition leak is
structurally possible and none is observed. `lane-map.json` resolves both lanes distinctly
(`wf_8eb3aec3-b82-1` → `load-bearing-row`, repo root → `spec-review-1`). No cross-job seam to check:
there is no Task 0 and no second implementer.

### Build green, and the tests the tier owes

Manifest `triage.tier: SCOPED`. `files_changed: [scripts/compound-v-memory.py]` matches the single
`impacted_map` rule `when: scripts/compound-v-*.py`, so no changed path falls through to the unmapped-path
referencing heuristic and **`full_command` is not owed** — demanding it at SCOPED with a declared map that
covers every changed path would be a review error. Owed: floor ∪ impacted. Derived by matching
`files_changed` against the map myself, not taken on the worker's word.

| Field (`results/load-bearing-row.json`) | Value | Owed? |
|---|---|---|
| `tests.command` | floor `bash -c 'python3 -B scripts/compound-v-memory.py --selftest … && … scope-check.py --selftest …'` **+** the impacted rule resolved to `scripts/compound-v-memory.py` | both present, non-empty |
| `tests.exit_code` | `0` | OK |
| `tests.scope` | `impacted` | matches what SCOPED owes |
| `tests.selected_count` | `2` (commands, not cases) | = floor + 1 impacted |
| `receipts/…gate.json` `tests.checks` | both `rc: 0`, `status: "pass"`, `tier: 1`; `merge_blocked: false` | consistent |
| `receipts/…gate.json` `tests.contract_notes` | `impacted: 1 command(s) from 1 changed path(s)`; `previously-failing: 0`; `newly-added: 0` | consistent |

Re-run by me on the merged tree — evidence, not the worker's word, and not `status`:

```
bash -c 'python3 -B scripts/compound-v-memory.py --selftest >/dev/null && python3 -B scripts/compound-v-scope-check.py --selftest >/dev/null'   → exit 0
bash -c '[ -f scripts/compound-v-memory.py ] || exit 0; grep -q -- "--selftest" … ; /usr/bin/python3 -B scripts/compound-v-memory.py --selftest >/dev/null'   → exit 0
/usr/bin/python3 -B scripts/compound-v-memory.py --selftest        → 83 ok, 0 failed, all self-tests passed
/usr/bin/python3 -B scripts/compound-v-scope-check.py --selftest   → SELFTEST PASSED
```

Green. No `NO_TEST_EVIDENCE` (`tests.command` is non-empty and names both owed commands), no `BUILD_RED`.

### §2.6 confirmed-blocker integrity

**n/a.** `docs/superpowers/execution/epics/2026-09-03-glob-parity/epic-state.json` has
`"blocker_ledger": []` — no `blocked_external` verdict, no `done_with_blockers` terminal in this epic. No
auto-merge escape hatch to audit.

### Feature acceptance criteria (`manifest.acceptance_criteria`)

| Criterion | Evidence | Status |
|---|---|---|
| 1. `memory --selftest` passes with the row *"no private bytecode cache -> unavailable AND the sibling was never loaded"*; the **SAME row FAILS** on a guardless copy built and run beside a copy of `compound-v-scope-check.py` exactly as Step 2 does (REAL ok / GUARDLESS FAIL, **both lines quoted**); `scope-check --selftest` still passes | row present and passing (`83 ok / 0 failed`); guardless copy prints `FAIL` and `1 failed` — **both lines quoted verbatim in §SPEC 3(a)**; corroborated by marker instrumentation §3(b) and the inert-patch probe §3(c); `scope-check --selftest` → `SELFTEST PASSED` | **MET** |
| 2. `git diff --stat` shows only `scripts/compound-v-memory.py` and only lines inside `_selftest`; the attempt-2 row is **replaced, not duplicated** (`grep -c` prints 1); no production code changed; no existing check weakened or removed | `+15/-7`, one file; every hunk at `:1658-1682`, inside `_selftest` (`:1258`–`:1694`), every hunk header `def _selftest()`; `grep -c 'no private bytecode cache'` → **`1`**; 74 `check()` rows before and after with exactly one title line changed, strengthened; scope gate `pass` | **MET** |

**PASS 3 INTEGRATION: OK.**

---

## Verdict

| Pass | Result |
|---|---|
| PASS 1 SPEC | **OK** — Step 1 block byte-identical to the plan; replaced not duplicated (`grep -c` = 1); Step 2 reproduced by me with REAL `ok` / GUARDLESS `FAIL`; scope lock respected; no over-build. One LOW, non-blocking (§6). |
| PASS 2 QUALITY | **OK** — no reward-hack (74 → 74 `check()` rows, one title changed, assertion strictly strengthened, scorer untouched); no fabricated metric; no regression; the MUST now has a guard that genuinely fails. |
| PASS 3 INTEGRATION | **OK** — no partition leak, no seam; floor + tier-owed impacted commands ran, exit 0, re-run by me; `full_command` correctly not owed at SCOPED; both feature acceptance criteria met; §2.6 n/a (empty blocker ledger). |

Attempt 2 was honest, in scope and green, and did not do the one thing it existed to do. Attempt 3 does
it. The assertion moved off the verdict — which the guard provably does not affect — and onto the side
effect the guard actually controls, and I broke the guard three different ways to watch the row fail each
time. One row in, one row out, no production line touched, both suites green.

The residual LOW is a reporting habit, not a defect in this change, and it belongs to the manifest: two
attempts have now been asked in prose to quote proof into `summary` and returned the job title instead.
Worth fixing where the asking happens, not here.

VERDICT: APPROVED
