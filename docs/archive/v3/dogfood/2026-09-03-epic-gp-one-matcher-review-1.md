# Review Gate — epic `2026-09-03-glob-parity` · F1 `one-matcher` · review-1

- **Run:** `2026-09-03-glob-parity-one-matcher`
- **Reviewed diff:** `4bc979a39759deafbfd8471405c18a433cd4a5e3` (wave 1, job `matcher-swap`, merged from worktree `wf_e77d98a8-18a-1`), against baseline `155239a8916da3f380a7f00ba847385de1e2cbdb`
- **Spec:** `docs/superpowers/execution/epics/2026-09-03-glob-parity/specs/one-matcher.md`
- **Plan:** `docs/superpowers/plans/2026-09-03-epic-gp-one-matcher.md`
- **Reviewer:** `superpowers-v:spec-reviewer` (job `spec-review-1`, `direct` isolation, baseline `cd8f2142`)
- **Interpreter for every command below:** `/usr/bin/python3` → `Python 3.9.6` (the CI floor)

**VERDICT: APPROVED** — SPEC ✅ · QUALITY ✅ · INTEGRATION ✅. Four non-blocking observations are recorded in
§QUALITY/§INTEGRATION; none of them gates DONE, and none asks the implementer for another round.

---

## Recall

Step 0 ran both halves of the recall layer before the diff was opened.

**`search --intent review`** (`compound-v-memory.py search "glob matcher parity recall-check scope gate" --intent review --top 8`)
— not empty. Eight hits, all of them this epic's own artefacts: the F1 plan (×3), the F1 spec, the F2
`matcher-docs` plan (×2), the epic brief, and the 1A archaeology doc's own Step 0. **No prior incident record
exists for a glob-matcher change**, so there is no settled decision this review is re-litigating and no past
failure shape to match against. The one substantive recalled constraint is the epic brief's framing — this
feature's run is the stage-7 death-and-resurrection subject — which is why the run carries a superseded gate
receipt (see §INTEGRATION, observation 4). Cited, not treated as authority.

**`recall-check`** over the diff's file set:

```
/usr/bin/python3 -B scripts/compound-v-memory.py recall-check --files scripts/compound-v-memory.py --json
→ {"verdict": "none", "match_count": 0, "k": 2, ...}   exit 0
```

**Verdict `none`** — no repeated `blocked`/`error`/`timeout` or scope-violation history on
`scripts/compound-v-memory.py`. No `tighten` escalation is owed, and recall loosens nothing: the controls this
run already carries (worktree isolation on the implementer, the git-derived scope gate, this review pass) stand
exactly as the manifest set them.

---

## SPEC

### Scope lock

| Job | `write_allowed` | Paths actually changed | Verdict |
|---|---|---|---|
| `matcher-swap` | `scripts/compound-v-memory.py` | `scripts/compound-v-memory.py` (only) | ✅ in lane |

Evidence: `git show --stat 4bc979a` → `1 file changed, 93 insertions(+), 5 deletions(-)`; the final gate receipt
`receipts/matcher-swap.gate.json` records `verdict: pass`, `violations: []`, baseline `155239a8`, patch digest
`sha256:458355c1…`. `git diff 155239a8..HEAD --name-only` shows `scripts/compound-v-memory.py` plus run
bookkeeping written by the caller (`state.json`, `results/`, `receipts/`, `jobs/*.baseline`,
`docs/superpowers/memory/worker-performance.jsonl`) — none of it worker-written. **No `SCOPE_LOCK_VIOLATION`.**

### Spec coverage

| Spec requirement | Implemented at | Status |
|---|---|---|
| `_file_matches` stops using `fnmatch`, delegates to scope-check `matches(path, pattern)` | `scripts/compound-v-memory.py:1115-1125` | ✅ |
| Bare glob (no `*`/`?`) means "this path or anything under it": try `g`, then `g.rstrip("/") + "/**"` | `:1122-1123` | ✅ |
| Sibling loaded by path with `importlib.util.spec_from_file_location`, resolved from `os.path.dirname(__file__)` | `:1057` (`_SCOPE_CHECK_PATH`), `:1088-1093` | ✅ |
| Loader failure ⇒ `verdict: unavailable`, `note: "scope-check matcher unavailable…"`, never a silent `none` | `:1131-1136` | ✅ |
| `import fnmatch` removed (nothing else uses it) | line 32 deleted; `grep -n fnmatch` exit 1 | ✅ |
| Only `scripts/compound-v-memory.py` modified | see scope-lock table | ✅ |
| Parity table of ≥8 `(pattern, path, expected)` rows, each asserted against BOTH `scope.matches` and `_file_matches` | `:1632-1643` — 10 rows, both matchers per row | ✅ |
| Bare-dir row `("docs", "docs/a/b.md", True)` asserted as `_file_matches` True **and** `scope.matches("docs/a/b.md", "docs/**")` True | `:1645-1646` | ✅ |

Every one of the ten spec-named rows is present verbatim: `src/*.py`×2, `src/**`×2, `app/[locale]/**`×2,
`README.md`×2, `**/x.py`, `docs/**`. **No `SPEC_GAP`.**

### Audit / pre-flight constraint check

| Source | MUST | Satisfied | Evidence |
|---|---|---|---|
| Pre-flight amendment 1 | Loader = the hardened `load_scope_matcher` shape, not the bare triple | ✅ | `:1073-1111`: `sys.pycache_prefix` redirected to a private `tempfile.mkdtemp`, restored in `finally`, tmpdir `rmtree`'d |
| Pre-flight amendment 1 | **Fail closed** when the private bytecode-cache dir cannot be created — load nothing | ✅ | `:1080-1083` sets `err` and the `if err is None` guard at `:1084` skips the import entirely |
| Pre-flight amendment 1 | Whole `spec_from_file_location`/`module_from_spec`/`exec_module` inside one `try/except` | ✅ | `:1078-1097` |
| Pre-flight amendment 1 | `callable(getattr(module, "matches", None))` verified before use | ✅ | `:1104-1106` |
| Pre-flight amendment 2 | Never load at module top level (`compound-v-onboard.py` imports this module) | ✅ | load happens only inside `_scope_matches()`, first called from `_file_matches`/`recall_check`/`_selftest` |
| Pre-flight amendment 2 | Memoized, **failure included** — never re-exec per (record × file) pair | ✅ | `_SCOPE_MATCH` / `_SCOPE_MATCH_ERR` globals, `:1068-1072`; selftest asserts `v2 == v` on the cached-failure path (`:1653`) |
| Pre-flight amendment 3 | `unavailable` is a well-formed verdict at exit 0, same JSON shape as `none` | ✅ | `:1133-1136` returns `verdict`/`match_count`/`k`/`files_queried`/`actions`/`evidence`/`note`; live run below exits 0 |
| Pre-flight amendment 4 | Bare-dir fallback is `/**`, not `/*` | ✅ | `:1123`; the `("docs", "docs/a/b.md")` row is the guard that would fail under `/*` |
| Pre-flight amendment 5 | `scripts/compound-v-scope-check.py` untouched, incl. its selftest | ✅ | `git diff 155239a8..HEAD -- scripts/compound-v-scope-check.py` → 0 lines |
| Pre-flight amendment 5 | No third-party packages | ✅ | added imports are `importlib.util`, `shutil`, `tempfile` — all stdlib |
| Plan global constraint | Python 3.9 syntax | ✅ | full selftest green under `/usr/bin/python3` 3.9.6 |

**No `CONSTRAINT_VIOLATION`.**

### Job acceptance (`matcher-swap`, manifest `jobs[].acceptance`)

| Criterion | Command | Result |
|---|---|---|
| `--selftest` passes with the parity rows all `ok` | `/usr/bin/python3 -B scripts/compound-v-memory.py --selftest` | ✅ all 10 `parity …` lines `ok`, `bare dir == dir/**` ok, `matcher missing -> unavailable` ok, `0 failed`, `all self-tests passed` |
| `grep -n fnmatch scripts/compound-v-memory.py` prints nothing | `grep -n fnmatch scripts/compound-v-memory.py` | ✅ no output, exit 1 |
| `recall_check` returns `unavailable` with a note starting `scope-check matcher unavailable` when the sibling cannot be loaded | asserted in-selftest at `:1647-1653` (path repointed to `/nonexistent/…`, both first and cached call checked) | ✅ |

### Over-build check

The diff is the plan's Step 1 and Step 3 code **verbatim** — same identifiers, same comments, same ordering. No
extra CLI flag, no extra exported helper, no speculative abstraction, no added logging, no config knob. The
three new module-level names (`_SCOPE_CHECK_PATH`, `_SCOPE_MATCH`, `_SCOPE_MATCH_ERR`) are all named by the plan
and all three are read by the selftest's loader-failure block, so none is dead. **No `OVER_BUILD`.**

**PASS 1 SPEC: ✅**

---

## QUALITY

### Code quality

Naming follows the file's existing private-underscore convention. The loader's `finally` restores
`sys.pycache_prefix` to the *previous* value (`getattr(sys, "pycache_prefix", None)` captured at `:1076`) rather
than to `None`, so a caller that had its own prefix set is not clobbered. The `except Exception` breadth at
`:1082` and `:1095` is deliberate and correct here — the point is fail-closed, and the reason string is
preserved into the verdict rather than swallowed. Docstrings on both `_scope_matches` and `_file_matches` state
the *why* (one matcher, forged-`.pyc` defence, bare-path reading), not the *what*. No duplication introduced —
this diff removes the second glob implementation rather than adding one. No dead code. **No `QUALITY` issue.**

### No regression

| Check | Evidence |
|---|---|
| Full `--selftest` green | `/usr/bin/python3 -B scripts/compound-v-memory.py --selftest` → `0 failed / all self-tests passed` |
| `scope-check --selftest` still green and unchanged | `/usr/bin/python3 -B scripts/compound-v-scope-check.py --selftest` → `SELFTEST PASSED`; diff vs baseline = 0 lines |
| Every caller of the changed function updated | `grep -rn "_file_matches\|_scope_matches" scripts/ skills/ hooks/` → only `recall_check` (`:1141`) and `_selftest`; `recall_check` guards the new `RuntimeError` path at `:1131`, so the raise can never escape to a caller |
| `tighten` path still works after the swap | `recall-check --files '**' --k 1 --json` → `verdict tighten`, `match_count 16`, `actions [force_worktree, extra_review_pass, fold_into_task0]` — the bridge still fires on real recorded failures |
| `none` path still works | `recall-check --files scripts/compound-v-memory.py --json` → `verdict none`, exit 0 |
| No lazy-import regression for `compound-v-onboard.py` | load is inside `_scope_matches()`, never at module import |

The one deliberate behaviour change is the semantics themselves: `*` no longer crosses `/`, and `[` `]` are now
literal. That is the point of the feature, and it moves recall-check *onto* the contract its callers already
speak — `partition-reviewer.md:18` and `spec-reviewer.md:36` both pass `write_allowed`-shaped globs, i.e. gate
globs. **No `REGRESSION`.**

### Test alignment

Every MUST above has a test that fails if the requirement breaks:

| MUST | Guard |
|---|---|
| `*` does not cross `/` | `parity src/*.py ~ src/a/b.py` (expects False) |
| `**` crosses `/`; `dir/**` matches `dir` | `parity src/** ~ src/a/b.py`, `parity src/** ~ src` |
| `[` `]` literal, not a character class | `parity app/[locale]/** ~ app/[locale]/page.tsx` (True) **and** `~ app/l/page.tsx` (False) — the pair is what distinguishes literal from class |
| Anchored to the full repo-relative path | `parity README.md ~ docs/README.md` (False) |
| Leading `**/` matches at depth zero | `parity **/x.py ~ x.py` |
| Bare-dir fallback is `/**`, not `/*` | `bare dir == dir/**` (also asserts the negative, `docs2/a.md` → False, so the fallback is not a prefix-substring match) |
| Loader failure ⇒ `unavailable`, note prefix, cached | `matcher missing -> unavailable` (asserts verdict, `note.startswith`, and `v2 == v`) |
| Parity is *parity*, not just correctness | each row asserts `_scope(path, pat) is want AND _file_matches(path, [pat]) is want` — the two matchers are checked against each other, so a future divergence in either fails |

These are behavioural assertions with expected values, not "it compiles". `is want` / `is True` identity
comparisons are safe because `scope.matches` returns `re.…match(path) is not None` — a real `bool`
(`scripts/compound-v-scope-check.py:378-381`). **No `TEST_GAP`.**

### No fabricated metrics (anti-ruflo)

The diff prints, logs and documents **no** number: no token count, no baseline constant, no "saved N", no
speedup percentage, no duration claim. The only literals added are glob patterns and expected booleans in the
parity table. **No `FABRICATED_METRIC`.**

### No reward-hacking

The only test-bearing file in the diff is `compound-v-memory.py`'s own `_selftest`, and it is **purely
additive** — 26 added lines, zero deleted lines inside `_selftest` (`git show 4bc979a` hunk at `@@ -1567,6
+1629,32 @@` is `+`-only). No assertion removed or commented out, no test file deleted or renamed, no threshold
loosened, no `skip`, no exception swallowed to soften a failure. The scorer/checker of record here —
`scripts/compound-v-scope-check.py`, whose `matches()` *is* the bar — was not edited at all (0-line diff); the
implementation was moved onto it instead. The `except Exception` blocks added in the loader do not soften an
existing hard failure: they convert an *unhandled crash* into an explicit `unavailable` verdict that the spec
demands and the selftest asserts, which is strictly louder than the pre-change behaviour. **No `REWARD_HACK`.**

### §2.6 confirmed-blocker integrity

**Not applicable.** This run reached no marathon `blocked_external` verdict and no `done_with_blockers`
terminal; there is no `arbiter/` directory and no blocker ledger entry for feature F1. `state.json` carries a
`blocked_reason`, but it is a *scope-gate* refusal from the stage-7 death, not an arbiter blocker verdict — see
§INTEGRATION observation 4.

### Non-blocking observations

1. **(LOW · spec-prose nit, not a code defect)** The spec prose reads "A bare glob with no `*`, `?` **or
   trailing `/`**…", which would exclude `docs/` from the fallback; the implemented guard at `:1122` tests only
   `"*" not in g and "?" not in g`, so `docs/` *does* get the `docs/**` fallback (`rstrip("/")` handles it).
   The implementation matches the **plan's verbatim code block** (Step 3), which is the more specific artefact,
   and the behaviour is the more useful of the two readings. Flagged only so F2 `matcher-docs` states the rule
   the code actually implements, rather than re-copying the spec's looser phrasing.
2. **(LOW · accepted by design)** `_SCOPE_MATCH_ERR` caches a *transient* failure for the process lifetime, so a
   long-lived process that hits e.g. a momentarily unwritable temp dir reports `unavailable` for the rest of
   that process. This is exactly pre-flight amendment 2 ("cache a failed load too"), and every real caller is a
   short-lived subprocess (`compound-v-emit-workflow.py:1368` spawns it per emit). Recorded, not charged.
3. **(INFO)** `scope.matches` recompiles `glob_to_regex(pattern)` on every call, where `fnmatch` carried an
   internal pattern cache. At recall-check volumes (16 failure records in this repository today) this is
   immaterial, and `re.compile` is itself memoized by the `re` module. No action.

**PASS 2 QUALITY: ✅**

---

## INTEGRATION

### Partition integrity at the seam

One implementer job, one write path, no Task 0, no shared barrel or registry. Nothing to leak across, and
nothing did: the composite's only source change is `scripts/compound-v-memory.py`, and the one file this
feature declared read-only — `scripts/compound-v-scope-check.py` — has a zero-line diff against the run
baseline. **No `PARTITION_LEAK`.**

### Cross-job / cross-component seams

The contract this change crosses is `recall_check` → the emitter, since `recall_check` can now return a
*third* verdict value. Verified at the consumer:

- `scripts/compound-v-emit-workflow.py:1408-1410` validates
  `verdict not in ("none", "tighten", "unavailable")` → the new `unavailable` is already an accepted member of
  the enum, so the emitter treats it as a first-class verdict rather than rejecting it as unknown. ✅
- The same consumer independently synthesizes `unavailable` via `_recall_unavailable(...)` for its own failure
  modes (engine missing, timeout, non-zero rc, bad JSON), so the shape the engine now emits is the shape the
  emitter already produced and handled. ✅
- `match_count: 0` and the `k` passthrough in the `unavailable` return (`:1133-1136`) satisfy the emitter's
  strict shape checks at `:1412-1424` (non-negative non-bool `int`; `k >= 1`), so an `unavailable` verdict
  cannot be re-classified as malformed. ✅
- Callers pass **gate-shaped globs** (`agents/partition-reviewer.md:18` — "every `write_allowed` glob";
  `agents/spec-reviewer.md:36` — "globs from the diff"), which is precisely why parity with the gate matcher is
  the correct semantics and not a narrowing of an unrelated contract. ✅

**No `INTEGRATION_MISMATCH`.**

### Build green, and the tests the tier owes

Manifest `triage.tier: FULL`. `test_contract.impacted_map` is **declared and non-empty** (one rule,
`when: scripts/compound-v-*.py`). Derived independently from `files_changed`: the single changed path
`scripts/compound-v-memory.py` **matches** that rule, therefore no changed path falls outside the map and
`full_command` is **not owed** — the derived-default rule applies at FULL exactly as at any other tier. The
obligation is: floor + impacted (∪ previously-failing ∪ newly-added, both empty here).

Job result evidence (`results/matcher-swap.json`, not the summary prose):

| Field | Value | Owed? |
|---|---|---|
| `tests.command` | 2 commands, newline-separated: the floor, then the impacted rule expanded for `scripts/compound-v-memory.py` | non-empty ✅ |
| `tests.exit_code` | `0` | ✅ |
| `tests.scope` | `impacted` | matches what FULL-with-a-declared-map owes ✅ |
| `tests.selected_count` | `2` (commands, not cases) | consistent ✅ |
| `tests.failures` | `[]` | ✅ |

The gate receipt corroborates command-by-command: `receipts/matcher-swap.gate.json` → `tests.checks[]` both
`status: pass, rc: 0`, `tests.passed: true`, `merge_blocked: false`, and `contract_notes` recording
"impacted: 1 command(s) from 1 changed path(s)", "previously-failing: 0", "newly-added: 0". **No
`NO_TEST_EVIDENCE`.**

I did not take green on the worker's word. Re-run here, at `direct` isolation, on the merged tree:

```
# floor_command, verbatim from the manifest
bash -c 'python3 -B scripts/compound-v-memory.py --selftest >/dev/null && \
         python3 -B scripts/compound-v-scope-check.py --selftest >/dev/null'
→ exit 0

# full_command, verbatim — run as extra evidence though the tier did not owe it
bash -c 'for s in scripts/compound-v-*.py; do grep -q -- "--selftest" "$s" || continue; \
         /usr/bin/python3 -B "$s" --selftest >/dev/null 2>&1 || { echo "FAIL $s"; exit 1; }; done'
→ ALL_SELFTESTS_OK, exit 0
```

Every `--selftest`-bearing script in `scripts/` is green under 3.9.6, not just the two the contract required.
`git status --porcelain` after all of it shows no stray artefact from the review (only this job's own
`register-lane` bookkeeping and the file you are reading). **No `BUILD_RED`.**

### Feature acceptance criteria (manifest `acceptance_criteria` — the run-level gate)

| # | Criterion | Proving command | Status |
|---|---|---|---|
| 1 | `compound-v-memory.py --selftest` passes and prints an `ok` line for every parity row (≥10 rows incl. `app/[locale]/**` and `src/*.py` vs `src/a/b.py`); `compound-v-scope-check.py --selftest` still passes and the file is unchanged | `/usr/bin/python3 -B scripts/compound-v-memory.py --selftest` → 10 `parity …` ok lines (incl. `parity app/[locale]/** ~ app/[locale]/page.tsx`, `parity app/[locale]/** ~ app/l/page.tsx`, `parity src/*.py ~ src/a/b.py`) + `bare dir == dir/**` + `matcher missing -> unavailable`, `0 failed`; `/usr/bin/python3 -B scripts/compound-v-scope-check.py --selftest` → `SELFTEST PASSED`; `git diff 155239a8..HEAD -- scripts/compound-v-scope-check.py` → 0 lines | ✅ PASS |
| 2 | `grep -n fnmatch scripts/compound-v-memory.py` prints nothing; `_file_matches` delegates to `compound-v-scope-check.py` `matches()` loaded by path, with the bare-path form meaning "this path or anything under it" via a `/**` fallback | `grep -n fnmatch scripts/compound-v-memory.py` → no output, exit 1; delegation at `:1119` (`m = _scope_matches()`) loaded by path at `:1057` + `:1088-1093`; `/**` fallback at `:1122-1123`, guarded by the `bare dir == dir/**` selftest row | ✅ PASS |
| 3 | `python3 -B scripts/compound-v-memory.py recall-check --files 'app/[locale]/**' --json` exits 0 with `verdict` in `none\|tighten\|unavailable`; when the sibling cannot be loaded the verdict is `unavailable` with a note starting `"scope-check matcher unavailable"`, never `none` | `/usr/bin/python3 -B scripts/compound-v-memory.py recall-check --files 'app/[locale]/**' --json` → `{"verdict": "none", "match_count": 0, …}`, **exit 0**; the loader-failure half is asserted in-selftest (`matcher missing -> unavailable` — checks `verdict == "unavailable"`, `note.startswith("scope-check matcher unavailable")`, and that the cached second call returns the identical document) | ✅ PASS |

3 of 3 met. **No `ACCEPTANCE_GAP`.**

4. **(INFO · run bookkeeping, outside this diff's lane)** `state.json` still carries
   `blocked_reason: "wave 1: integration REFUSED … {\"blocked\": 1}"` stamped `19:23`, next to a wave-1 record
   that merged successfully at `20:29` (`commit 4bc979a`, `integrated: true`). The superseded receipt
   `receipts/matcher-swap.gate.superseded-3dad7dd78b21.json` explains it: the pre-death attempt was gated
   against a **stale baseline** (`47a7a733`) while the worktree's realised commit was `3dad7dd7`, so the diff
   swept in six unrelated F2-triage files and the gate correctly BLOCKED. `patch_sha256` is **identical**
   (`sha256:458355c1…`) in both receipts — the worker's own patch never changed and never left its lane; only
   the baseline pin was wrong, which is the bug commit `155239a8` (finding 146) fixed before the relaunch. The
   stale `blocked_reason` string is caller-owned bookkeeping, not a property of the reviewed change, and does
   not gate this verdict. Worth clearing on the next state write so `/v:status` does not read a healthy wave as
   blocked.

**PASS 3 INTEGRATION: ✅**

---

## Verdict

```
REVIEW GATE: F1 one-matcher — run 2026-09-03-glob-parity-one-matcher

VERDICT: APPROVED
  PASS 1 SPEC:        ✅  requirements 8/8 · pre-flight MUSTs 11/11 · over-build clean · job acceptance 3/3
  PASS 2 QUALITY:     ✅  code-quality clean · no regression (tighten + none paths both re-probed live)
                          · every MUST carries a guard row · no fabricated metrics · no reward-hacking
                          (selftest diff is +26/−0) · §2.6 n/a (no blocker verdict in this run)
  PASS 3 INTEGRATION: ✅  no partition leak · emitter seam accepts `unavailable` (emit-workflow:1408)
                          · build green — floor exit 0 AND full_command exit 0 under /usr/bin/python3 3.9.6
                          · tier FULL with a matched impacted_map ⇒ full_command not owed; tests.exit_code 0,
                            tests.scope "impacted", tests.selected_count 2 · feature AC 3/3 met
  Scope lock: respected — 1 file, in lane; final gate receipt verdict "pass", violations []
```

**VERDICT: APPROVED**
