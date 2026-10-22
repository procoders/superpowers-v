# v3.4.6 Triage/Test-Scoping Fixes — Code Archaeology

Spec under audit: `docs/superpowers/specs/2026-09-03-v3.4.6-triage-test-scoping-fixes-design.md`
(Part 1 — finding 99, the content-scan-exclude gap in `_classify_paths`; Part 2 — finding
102, the tier-1 checker's hardcoded 300 s cap).

## Step 0 — V-memory recall

Ran `scripts/compound-v-memory.py search` three times (`planning` intent): the spec's own
words (`triage test scoping proportionate content_scan_incomplete`), Part 2's mechanism
(`full_command timeout TEST_TIMEOUT_S fastpath run`), and Part 1's mechanism
(`compound-v-localize content_scan_exclude taxonomy classify_paths`). The index reported
itself "3 new / 2 changed / 0 removed docs behind" during the first call (another refresh
held the lock; the search read the index as-is — noted, not acted on, out of this audit's
scope) and current on the other two.

All three returned real hits, and one of them is load-bearing for this audit rather than
background: **a plan for this exact spec already exists** —
`docs/superpowers/plans/2026-09-03-v3.4.6-triage-test-scoping-fixes.md`. I read it in full
(see below) and treat it as a **draft to verify against the code, not an authority** — several
of its stated wiring points turn out to be incomplete once traced through the actual call
graph (§2, §5). The other load-bearing hit is `docs/superpowers/archaeology/2026-09-03-v3-4-1-triage-size.md`,
the prior audit for the feature that *built* the two mechanisms this spec patches
(`content_scan_exclude`, the T3 demotion, `_IMPACT_RAISING_FLAGS`). It is read in full and
cited throughout rather than re-derived — this audit does not re-litigate v3.4.1's design,
only the two defects layered on top of it.

**Also found, and worth flagging up front rather than burying:** a real pre-eval record for
this exact feature request already exists —
`docs/superpowers/pre-eval/2026-09-03T113149Z-implement-v3-4-6-per-docs-superpowers-specs-2026-09-03-v3-4-0cb5.json`
— and its own localization carries `"flags": ["content_scan_incomplete"]` against
`scripts/compound-v-fastpath-run.py` / `scripts/compound-v-localize.py`, i.e. **the request
to fix finding 99 was itself localized under the exact defect finding 99 describes.** Decision
was `FULL_PIPELINE` outright (not even a `needs_t3` demotion attempt) — but caution: `fan_out`
was 3, above `DEMOTION_MAX_FAN_OUT = 2` (`compound-v-preeval.py:263`), so fan-out alone would
have forced FULL regardless of the flag; the record does not, by itself, prove the flag was
the *deciding* factor here, only that the flag is live in production against this repo's own
scripts today. Treat it as corroboration of the underlying mechanism, not a controlled
isolation of the bug.

---

## 1. Matrix

### 1a. Part 1 — `_classify_paths` × `content_scan_exclude` (the cell the current code does not have)

| path's content-scan status | file size vs. `MAX_FILE_READ_BYTES` (65,536 B) | Current `_classify_paths` behaviour | Spec wants |
|---|---|---|---|
| NOT in `content_scan_exclude` | ≤ cap | reads full content, `incomplete=False` | unchanged |
| NOT in `content_scan_exclude` | > cap | reads capped content, `incomplete=True` | unchanged (still doubtful) |
| **IN `content_scan_exclude`** (e.g. `**/*.py`, `**/*.sh` in this repo's live taxonomy) | ≤ cap | reads full content (wastefully — `classify()` discards it via `content_scan_excluded` internally), `incomplete=False` | unaffected in outcome, only in wasted I/O |
| **IN `content_scan_exclude`** | **> cap** | **reads (and truncates) content anyway, sets `incomplete=True`** — the cell the spec fixes | **no read attempted, `incomplete` never set for this path; PATH rows + `sensitive_path` still evaluated via `tax.match_path`** |

The fourth row is not hypothetical: this repository's own live taxonomy
(`.claude/compound-v-impact-taxonomy.yaml:160-168`) sets
`content_scan_exclude: ["**/*.md", "**/*.py", "**/*.sh"]`, and `scripts/compound-v-fastpath-run.py`
/ `scripts/compound-v-localize.py` are both real, currently-oversized `.py` files under that
taxonomy (confirmed live via the pre-eval record in Step 0). `_classify_paths`
(`compound-v-localize.py:491-521`) has **no** call to `tax.content_scan_excluded` anywhere in
its body — it unconditionally opens every resolved path (`:505`) and sets `incomplete=True`
whenever the read exceeds the cap (`:512-515`), regardless of whether the taxonomy would ever
have looked at that content in the first place. `tax.classify()` (called one line later, `:517`)
*does* already skip content matching for an excluded path (`compound-v-taxonomy.py:673-674`),
but by then the read — and the `incomplete` flag — has already happened. The exclusion check
exists in exactly one of the two places it needs to.

### 1b. Downstream consequence matrix — what `content_scan_incomplete` currently vetoes

| `t1_from_broad_glob` precondition (`compound-v-preeval.py:640-645`) | Value when `content_scan_incomplete` is (wrongly) set | Value once Part 1 is fixed for an excluded path |
|---|---|---|
| `bool(_t1_rows)` | unaffected | unaffected |
| `all(row.get("broad") for row in _t1_rows)` | unaffected | unaffected |
| `not sensitive` | unaffected | unaffected |
| `not content_impact_high` | **False** — `_content_raises_impact(flags)` is True because `content_scan_incomplete ∈ _IMPACT_RAISING_FLAGS` (`:282-283`) | **True** — the flag is never set for an excluded path, so nothing vetoes the demotion on this axis |

This is the single line the whole Part 1 fix routes through: `_IMPACT_RAISING_FLAGS`
(`compound-v-preeval.py:282-283`) already contains `"content_scan_incomplete"` — added by
v3.4.1's own WS-B amendment 2 for a *different* purpose (a literal path whose content genuinely
couldn't be scanned should raise impact, not silently claim `exact`). Part 1 does not touch
this frozenset or the scorer at all; it only stops the flag from being produced in a case where
the taxonomy itself says "don't look."

### 1c. Part 2 — the two independent timeout mechanisms, and which one finding 102 actually hit

| Execution path | Timeout constant / flag | Who threads it | Consulted by finding 102's actual incident? |
|---|---|---|---|
| **Engine C direct-mode `test-floor`** (`compound-v-fastpath-run.py test-floor`, invoked by `compound-v-emit-workflow.py:2697-2703`) | `TEST_TIMEOUT_S = 300` (`:122`), default param of `run_test_floor` (`:1032-1033`), consumed at `_run_supervised(cmd, worktree, test_timeout_s)` (`:1093`) | `_cmd_test_floor` (`:1579-1607`) calls `run_test_floor(...)` **without ever passing `test_timeout_s`** — always the 300 s default | **Yes** — confirmed by `docs/superpowers/execution/2026-09-03-v3.4.5-recall-freshness-r2/results/docs-2.json` (`tests.exit_code: 124`) and `receipts/docs-2.gate.json` (`checks: [{"full_command","rc":124,"fail"}]`), the exact shape `run_test_floor`'s `checks` list produces, translated by `compound-v-emit-workflow.py`'s `_tests_block_from_floor` (`:3263-3331`) |
| **External-backend worker scripts** (`compound-v-run-{codex,antigravity,cursor,devin,opencode}-worker.sh`, `tc_run()`) | `TEST_TIMEOUT_SEC` — a shell var set **only** from the CLI flag `--test-timeout-sec`, default **900** (`compound-v-run-codex-worker.sh:259`), fed to `python3 "$SUPERVISOR" --timeout "$TEST_TIMEOUT_SEC"` (`:184`) inside `tc_run` (`:165-220`) | Never reads the `--test-contract-file` JSON for a timeout value at all — only the dispatcher's own CLI invocation (`agents/parallel-dispatcher.md:171-174`, which **hardcodes `[--test-timeout-sec 900]` in its reference template**) can change it | Not implicated in the observed incident (900 s already exceeds the 340-350 s suite), but is the path the plan's own Task B explicitly asks to patch (`tc_validate` in all five workers) |

These are **two structurally independent numbers**, not one constant read from two call sites.
The spec's Decision text ("`compound-v-fastpath-run.py` reads it from the contract the emitter
hands the worker") and the plan's Task B step 3 both describe fixing the first row; neither
explicitly re-derives the second row's `--test-timeout-sec` from the new `timeout_s` manifest
key, even though Task B's own scope list names all five `tc_validate` copies. See §5.3 for why
that half-wiring is a genuine, not cosmetic, gap.

---

## 2. Shared State

### `content_scan_incomplete` (a `_classify_paths`-produced flag) — every reader

- **Set in:** `compound-v-localize.py:_classify_paths` (`:511`, unreadable file — fail-closed,
  unaffected by this spec) and (`:514`, oversized read — **the cell this spec's Part 1
  changes**). Also propagated verbatim by the literal-path fast path (`:590-598`, WS-B
  amendment 2 of v3.4.1) into the top-level `flags` a `localize()` caller sees.
- **Read in `compound-v-preeval.py:241` `_IMPACT_RAISING_FLAGS`** (membership) →
  `_content_raises_impact` (`:433` prefix/membership check) → gates `content_impact_high`
  (`:627`) → gates `t1_from_broad_glob` (`:644`) → gates whether the T3-demotion branch is
  even entered (`:696`). **This is the entire causal chain finding 99 breaks.** No other
  reader in the codebase branches on this flag (confirmed: `Grep "content_scan_incomplete"`
  across `scripts/` returns only `compound-v-localize.py` and `compound-v-preeval.py`).
- **Gap the fix must not introduce:** `_classify_paths` also calls `_is_generated(rel, content)`
  (`compound-v-localize.py:519`, using the same `content` variable). `_is_generated`
  (`:457-467`) checks path-shaped globs first (unaffected by skipping the read) but falls back
  to content markers only `if content:` — for a path the fix now skips reading, `content` will
  be `b""`/`""`, so a *generated* file that is also excluded from content scanning (e.g. a
  generated `.py` with a "DO NOT EDIT" header, no matching entry in `_GENERATED_GLOBS`) silently
  loses `is_generated` detection. Low-severity (path-glob detection still runs, and no
  `_GENERATED_GLOBS` entry currently overlaps `**/*.py`/`**/*.sh` in this repo's own taxonomy),
  but it is a real, silent behaviour change the plan should at least acknowledge rather than
  discover in review.

### `timeout_s` (the new `test_contract` key, Part 2) — every point on the path from manifest to supervisor, and where each one is currently missing

| Hop | File : line | Currently reads `timeout_s`? |
|---|---|---|
| Manifest schema/validator | `compound-v-validate-manifest.py:845` `TEST_CONTRACT_ALLOWED_KEYS = ("floor_command", "full_command", "impacted_map")` | No — plan's `+= ("timeout_s",)` is the only change needed here, mirroring the existing allowed-vs-required-key pattern this file already uses (no `TEST_CONTRACT_REQUIRED_KEYS` exists to accidentally break) |
| Contract → slice | `compound-v-fastpath-run.py:768-943` `resolve_test_commands` builds `slice_` from `contract` at `:936-942` — copies `floor_command`/`full_command` when present, **never reads `contract.get("timeout_s")`** | No — needs a new line beside `:939-942` |
| `resolve-tests` CLI / worker file | `_cmd_resolve_tests` (`:1560-1576`) writes `slice_` verbatim to `--out`; `tc_validate` in all five workers currently **rejects** any key outside `["scope","floor_command","full_command","resolved_commands","selected_count"]` (`compound-v-run-codex-worker.sh:129`, byte-identical in the other four per the file's own comment at `:108-110`) | No — `timeout_s` in the slice would currently make every worker's `tc_validate` `die` with "unknown key", which is why Task B's list of all five workers is correct in scope, just (per next row) incomplete in depth |
| `test-floor` CLI | `_cmd_test_floor` (`:1579-1607`) calls `run_test_floor(args.worktree, args.baseline, changed, args.test_cmd, test_commands=test_commands)` at `:1602-1603` — **no `test_timeout_s=` kwarg at all**, so `run_test_floor`'s own default (`TEST_TIMEOUT_S=300`, soon 600) always wins even after `resolve_test_commands` starts copying the key into `slice_` | No — this is the wiring point finding 102's actual incident needs fixed (§1c row 1) |
| `tc_run` (external workers) | `compound-v-run-*-worker.sh:165-220` reads `.scope`/`.resolved_commands` from the contract file via `jq`; never reads a `.timeout_s` key; the supervisor's `--timeout` always comes from the shell var `TEST_TIMEOUT_SEC`, set **only** by the CLI flag `--test-timeout-sec` (default 900) | No — even after `tc_validate` is widened to *accept* `timeout_s`, `tc_run` never *consumes* it unless separately patched |
| Dispatcher's own invocation template | `agents/parallel-dispatcher.md:171-174` shows `[--test-timeout-sec 900]` as a literal, static flag in its worked example | No — nothing here derives the flag's value from `test_contract.timeout_s`; the template itself would need updating for the external-worker path to honor the new key end-to-end |
| Translation into `job_result.tests` | `compound-v-emit-workflow.py:_tests_block_from_floor` (`:3263-3331`) builds the schema-shaped block from `floor.get("checks")`/`floor.get("failures")`/`floor.get("duration_ms")` — **`floor.get("reasons")` is never read**, so the human-readable `"tier-1: configured tests failed (rc=124; timeout): <checker>"` string `run_test_floor` already produces (`:1102-1105`) is silently dropped before it reaches any job_result | No — the "receipt note" the spec's Decision text asks for (`timeout after N s: <checker>`) has no field to land in today; see §5.2 |

Five of these six hops are un-wired today. The plan (`docs/superpowers/plans/2026-09-03-v3.4.6-triage-test-scoping-fixes.md`,
Task B) explicitly names hops 1, 2/3 (bundled as "resolve_test_commands... gains timeout_s"),
4, and the five workers' `tc_validate` — but its own wording ("Every `...worker.sh` `tc_validate`:
allow the `timeout_s` key... in `--test-contract-file`") only asks for the *validator* to widen,
not for `tc_run` to *read* the key it now accepts, and does not mention `agents/parallel-dispatcher.md`'s
own invocation template at all. As literally scoped, `timeout_s` becomes real for Engine C's
`test-floor` path (once hop 4 above is added — the plan's own text is closest to naming this
one, via "`run_tests(..., test_timeout_s=TEST_TIMEOUT_S)`", though the function is actually
named `run_test_floor`, not `run_tests` — no function of that name exists in this file) and
**validated-but-inert** for every external-backend-dispatched job.

### `failure_class` — the top-level job field vs. the `tests` sub-object, and why they are not interchangeable

- **Set in (top-level):** each worker script's own status-derivation block
  (`compound-v-run-codex-worker.sh:624-677`, byte-identical pattern in the other four) — driven
  by `compound-v-classify-failure.py --backend <b> --exit-code <n> --stderr-file <f>`, itself
  classifying **the backend CLI's own exit/stderr** (rate-limited, auth, context-length, etc.),
  never anything about a test command the job ran internally.
- **Explicitly, deliberately NOT set from test outcomes** — the worker script says so in its
  own comment, verbatim (`compound-v-run-codex-worker.sh:708-711`): *"A non-zero `tests.exit_code`
  does NOT change `status`. `status`/`failure_class` describe the BACKEND's disposition, and
  re-labelling a red suite as a backend error would feed it to the retry/reroute policy, which
  cannot fix a failing test."*
- **Read by `compound-v-failure-policy.py`**, whose `RETRYABLE = {"rate_limited", "overloaded",
  "timeout", "network", "other"}` (`compound-v-classify-failure.py:41`) already treats
  `"timeout"` as retryable-once — meaning if the top-level field were set to `"timeout"` from a
  *test* timeout, the dispatcher would retry the entire AGENT invocation (burning a full model
  turn to re-do work that already succeeded, since the agent's own code changes were fine — only
  the test suite it ran was slow), which is precisely the mis-attribution the worker's own
  comment warns against.
- **The `tests` sub-object has no `failure_class`-shaped field at all.** `schemas/job_result.schema.json:88-135`
  declares `tests` as `"additionalProperties": false` with exactly `command` (required),
  `exit_code` (required), `scope` (required), `selected_count` (required), `duration_ms`
  (optional), `failures` (optional) — confirmed independently by `tests/test-engine-c-contract.sh`'s
  own header comment (`:1-19`), which exists specifically because a past release put the RAW
  `test-floor` document's fields (`phase`, `tier_used`, `merge_blocked`, …) straight into this
  `additionalProperties: false` object and broke schema conformance on the happy path.

**The spec's Decision text — "a checker that exits 124 is recorded with `failure_class: timeout`
in the job_result (the retry policy's existing class)" — names a field that, as currently
structured, cannot honestly express what it is being asked to express.** Setting the top-level
field would contradict the worker's own documented invariant and wrongly arm the retry policy
against a successful agent turn; there is no `tests.failure_class` to set instead without a
schema change (a new optional key inside `tests`, which is exactly the kind of change
`test-engine-c-contract.sh` exists to catch if done informally). This is not a nitpick — it is
the same class of defect (`additionalProperties: false` silently rejecting a field a design
assumes exists) that `tests/test-engine-c-contract.sh`'s own header describes shipping once
already in this codebase.

### `TEST_TIMEOUT_S` raise (300 → 600) interacting with the harness's own foreground ceiling

`agents/parallel-dispatcher.md:156-160` documents, in its own words, that **"the harness Bash
tool that spawns the worker... has a 600-second foreground ceiling"** and that "a job whose
`timeout_sec` exceeds 600 MUST be dispatched on the background path... otherwise the outer
bound kills the launcher before the worker can write its `job_result`, and a job that actually
finished is recorded as a timeout" — and the same paragraph calls this rule **"prose-enforced,
not guaranteed."** The spec's Part 2 validator accepts `timeout_s` up to 3600 and defaults the
floor to 600 — i.e. it explicitly enables values that meet or exceed the documented 600 s
foreground ceiling for the WHOLE worker process (agent time *plus* test time), not merely the
test step in isolation. A manifest that declares `test_contract.timeout_s: 900` on a
foreground-dispatched job would, per the file's own documented mechanism, get silently killed
by the OUTER harness bound before the test supervisor's own (now more generous) internal
timeout ever has a chance to fire cleanly and produce `rc=124` — reproducing a variant of
finding 102's exact symptom (a legitimate run killed by an unrelated cap) through a different
mechanism the spec does not mention.

---

## 3. Sibling Code

### 3a. `content_scan_excluded`'s only current call site (`compound-v-taxonomy.py:673-674`, inside `classify()`) — the pattern Part 1 must reuse, not reimplement

```python
if content is not None and path is not None and content_scan_excluded(taxonomy, path):
    content = None
```

Entry condition: only fires when both `content` and `path` are given (`classify()`'s two
optional params). This is a **content-matching** suppression — it still lets `path` flow
through `match_path` for PATH rows and `sensitive_path_list` unchanged (confirmed by its own
selftest, `compound-v-taxonomy.py:951-954`: an excluded `.md` keeps its `impact_band`/
`difficulty_band` from path rows, only `content_hits`/content-derived `flags` go empty). The
public `content_scan_excluded(taxonomy, path)` function (`:501-508`) is already exported and
already the single source of truth for "does this taxonomy exclude this path's content." Part
1's fix is a **second, independent call site** for the same function, gating a different
operation (whether to open the file at all, not whether to pattern-match its bytes) — the plan's
own wording (`tax.content_scan_excluded(taxonomy, path)` inside `_classify_paths`) already
names the correct reuse; there is no reimplementation risk here, only the two-call-sites fact
worth recording because a future reader might wonder why the same-looking check appears twice.

### 3b. `run_test_floor`'s rc-124 handling (`compound-v-fastpath-run.py:1091-1106`) — read in full, this is exactly what Part 2 extends

```python
for cmd, spelling in argvs:
    rc, _ = _run_supervised(cmd, worktree, test_timeout_s)
    result["checks"].append({"tier": 1, "checker": spelling, "rc": rc,
                             "status": "pass" if rc == 0 else "fail"})
    if rc != 0:
        failed_cmds.append((spelling, rc))
...
for name, rc in failed_cmds:
    result["reasons"].append(
        "tier-1: configured tests failed (rc=%s%s): %s"
        % (rc, "; timeout" if rc == 124 else "", name))
```

Today, rc 124 is already distinguishable in `reasons` (the `"; timeout"` suffix exists — this
is what the 2026-09-03 dogfood record's human reviewer read to correctly diagnose finding 102
by hand). What does **not** exist: (a) any `checks[].status` value other than `"pass"`/`"fail"`
— a timeout and a genuine assertion failure are both just `"fail"` at this granularity; (b) any
propagation of `reasons` past `_tests_block_from_floor`'s translation (§2, confirmed —
`reasons` is read nowhere in that function). A caller reading only the schema-shaped
`job_result.tests` block (which is everything `agents/spec-reviewer.md` and
`compound-v-integration-gate.py` see) cannot currently tell a 124 from any other failure without
re-deriving it from the raw `exit_code == 124` themselves.

### 3c. `_tests_block_from_floor`'s scope-fallback duplication (`compound-v-emit-workflow.py:3300-3317`) — a documented, deliberate DRY exception nearby, worth knowing before touching this function

The function's own comment (`:3301-3304`) states this fallback mirrors
`compound-v-fastpath-run.py:default_scope_for(contract, tier)` **on purpose, duplicated,
because both are standalone stdlib CLIs with no shared import (house style)**. This is directly
adjacent to where a `timeout_s`-aware change to `_tests_block_from_floor` (if the plan adds one,
e.g. to surface a timeout note) would land — the file's existing convention is duplicate-and-keep-in-sync
rather than import, so a Part 2 change here should follow the same house style rather than
introduce the first cross-file import between these two CLIs.

### 3d. `TEST_CONTRACT_ALLOWED_KEYS`'s existing extension precedent (`compound-v-validate-manifest.py:845`) — already extended once, safely

The current tuple (`"floor_command", "full_command", "impacted_map"`) is itself evidence that
widening this list is a known-safe, previously-exercised operation — `impacted_map` was added
by an earlier release without breaking `floor_command`/`full_command`-only manifests, because
the unknown-key loop (`:2247-2252`) walks `contract` and reports violations only for keys *not*
in the tuple; adding to the tuple can only ever *reduce* violations, never introduce one for an
existing manifest. `timeout_s`'s addition is the same shape of change and carries no analogous
risk to the one the v3.4.1 audit flagged for `TRIAGE_REQUIRED_KEYS`/`flavor` (that was a
required-field list; this is a pure allow-list).

### 3e. The five worker scripts' shared `tc_validate`/`tc_run` — already threaded through once for a new key (3.4.1's `impacted+referencing`/`selected_count`), same mechanical shape Part 2 repeats

`docs/superpowers/dogfood/2026-09-03-v3.4.1-triage-size-review-3.md`'s "Finding #1 — CLOSED,
all five workers, on a real slice" records that all five `tc_validate` copies were verified
identically for the previous key addition. The files' own comment
(`compound-v-run-codex-worker.sh:108-110`) states the constraint explicitly: **"These three
functions are BYTE-IDENTICAL in all five worker scripts... Fix them in all five, or in none."**
Part 2's Task B already lists all five files for `tc_validate`; per §2's table, the same
byte-identical-in-five constraint applies to `tc_run` too, the moment the plan decides `timeout_s`
must actually change behaviour on the external-worker path and not just pass structural
validation there.

---

## 4. External APIs

No new third-party SaaS/HTTP API. Both parts of this spec are internal-only: Part 1 touches a
taxonomy/classification module with no external calls; Part 2 touches the process-timeout
supervisor (`$SUPERVISOR`, an internal script) and the manifest/schema/worker-script contract,
all local. Per CLAUDE.md's "read docs before experimenting" rule, there is no library dependency
to validate here — this is Phase 1C's lane (library/doc currency), not this one's, and it
correctly has nothing to report.

---

## 5. Regression Surface

1. **Every existing selftest assertion built on the `_SHARED_TOKEN_TAXONOMY` fixture
   (`compound-v-localize.py:797-821`) is unaffected by Part 1**, because that fixture sets no
   `content_scan_exclude` key at all — `load_taxonomy` then defaults it to `[]`
   (`compound-v-taxonomy.py:437-438`), so `content_scan_excluded()` is `False` for every path
   under it and the fix's new branch never fires for HIGH-8(c) (`:1162-1180`) or WS-B(10)
   (`:1242-1249`), the two existing tests that currently pin `content_scan_incomplete`
   behaviour on an oversized file. **Neither needs rewriting under Part 1 as scoped** — this
   contradicts the plan's own line 19 ("fix a fixture that assumed the flag on any big file,
   never the rule"); no such universally-assuming fixture was found by tracing every call site
   of `_classify_paths` in this file's selftest. The plan should verify this claim against the
   actual fixture before treating a rewrite as required work; what genuinely is required is a
   **new** taxonomy fixture (with an explicit `content_scan_exclude` list) for the new test
   cases, since the shared fixture cannot express the excluded case at all.
2. **`content_scan_incomplete`'s only two readers stay exactly two after Part 1** (§2) — the
   fix removes a false-positive producer, it does not touch either consumer
   (`_IMPACT_RAISING_FLAGS` membership, `_content_raises_impact`'s prefix check). Any existing
   assertion that a **non-excluded** oversized file still raises the flag (HIGH-8(c),
   `compound-v-preeval.py:2252-2258`'s `content_scan_incomplete raises impact` case, which
   passes the flag synthetically and never calls `_classify_paths`) is unaffected.
3. **The external-worker `timeout_s` path (§2's table) is validate-only unless Task B is
   extended beyond its current wording.** If shipped exactly as the plan states it (`tc_validate`
   widened, `tc_run` untouched), a manifest with `test_contract.timeout_s: 900` dispatched to a
   Codex/Antigravity/Cursor/Devin/Opencode worker would pass structural validation, be silently
   ignored by `tc_run`'s actual `$SUPERVISOR --timeout` call (still driven by
   `--test-timeout-sec`, default 900, itself never derived from the manifest), and the operator
   would reasonably believe the declared budget is in effect when it is not. This is a silent
   configuration no-op, the specific failure shape a reviewer is least likely to catch by
   reading the diff (the validator change looks complete on its own).
4. **Raising `TEST_TIMEOUT_S` toward the harness's documented 600 s foreground ceiling
   (`agents/parallel-dispatcher.md:156-160`) reintroduces a variant of finding 102's own failure
   mode** if a foreground-dispatched job's total wall time (agent + tests) is pushed past 600 s
   by the new, larger test budget: the outer harness kill fires first, with no clean `rc=124`
   and no `job_result` written at all — worse than today's failure (today's failure at least
   produces a diagnosable `rc=124`/`blocked` record). The spec does not mention this ceiling;
   the plan should state explicitly whether test-only budgets above ~550 s require the
   background dispatch path, and if so, how that requirement is enforced (today: not
   mechanically, per the file's own "prose-enforced, not guaranteed" admission).
5. **`_tests_block_from_floor`'s existing behaviour of silently dropping `floor.get("reasons")`
   is pre-existing, not introduced by this spec** — but Part 2's stated goal (a "receipt note"
   surfacing `timeout after N s: <checker>`) cannot be satisfied without either reading
   `reasons` here for the first time, or adding an equivalent field. Any plan that claims this
   note reaches the job_result without touching `_tests_block_from_floor` is describing
   behaviour the current translation code does not produce.
6. **`tests/test-engine-c-contract.sh` already exists specifically to catch a `tests` block that
   violates `additionalProperties: false`** (its own header names the exact incident this would
   be a repeat of). Any Part 2 implementation that adds a field to the `tests` object without
   updating `schemas/job_result.schema.json`'s `tests.properties` will be caught by this test —
   which is the correct outcome, but only if the plan actually runs it (Task B's own checklist
   does list `bash tests/test-engine-c-contract.sh` as a gate, which is the right call).
7. **A checker timeout classified via the top-level `failure_class: "timeout"` would engage
   `compound-v-failure-policy.py`'s retry-once semantics** (`RETRYABLE` includes `"timeout"`),
   re-running the entire agent job. For a job whose code change was correct and whose only
   problem was a slow-but-passing test suite, this wastes a full model turn re-doing
   already-correct work, and does so silently unless the plan explicitly decides this
   consequence is intended (a genuine option — "retry the whole job on a slow-suite timeout" is
   defensible — but it must be a stated decision, not an accidental one inherited from reusing
   a same-named enum value that already has a different, documented meaning).

---

## 6. DRY Findings

1. **Part 1 correctly reuses the existing `content_scan_excluded()` function** (§3a) rather than
   reimplementing glob matching in `compound-v-localize.py` — no DRY violation here, and the
   plan's own wording already names the right call.
2. **`TEST_CONTRACT_ALLOWED_KEYS`'s extension pattern is already established** (§3d) — `+=
   ("timeout_s",)` is the same shape as the existing `impacted_map` addition, not a new pattern
   to invent.
3. **The five worker scripts' `tc_validate`/`tc_run` byte-identical-copy discipline is an
   existing, explicit, self-documented convention** (`compound-v-run-codex-worker.sh:108-110`),
   not something this spec introduces — Part 2 must follow it (all five or none), which the
   plan's file list already reflects for `tc_validate`. Whether it also needs to hold for
   `tc_run` depends on the scope decision in §5.3/§2.
4. **No existing mechanism computes "does this job's total wall time fit the foreground
   ceiling"** (§5.4) — there is nothing to reuse or extend here; if the plan decides this
   interaction needs enforcement rather than documentation, it is new code, and
   `agents/parallel-dispatcher.md:156-160`'s own text already flags the absence of such a
   mechanical guard as a known gap ("deferred to its own release").

---

## 7. Design constraints for the spec

Non-negotiable; each traces to a finding above.

1. **Part 1's fix site is `_classify_paths` (`compound-v-localize.py:491-521`) and only that
   function.** It must call `tax.content_scan_excluded(taxonomy, path)` (the existing exported
   function, `compound-v-taxonomy.py:501-508`) before the `open()` at `:505`, and skip both the
   read and the `incomplete=True` assignment when it returns True — `tax.match_path` /
   `sensitive_path` classification via `tax.classify()` at `:517` must still run with
   `content=None` for that path (already `classify()`'s own behaviour once `content is None`).
2. **No existing selftest fixture requires rewriting for Part 1 as scoped** (§5.1) —
   `_SHARED_TOKEN_TAXONOMY` has an empty `content_scan_exclude` by construction. The plan's
   claim that a fixture must be "fixed... that assumed the flag on any big file" should be
   verified against the actual test file before being treated as required work; what is
   genuinely required is a **new**, separate taxonomy fixture (with an explicit
   `content_scan_exclude` list) for the new positive/negative test cases, not a change to the
   shared one.
3. **`_is_generated`'s content-marker fallback silently stops firing for any excluded, oversized
   path** (§2) once Part 1 ships — low severity given today's `_GENERATED_GLOBS`/`content_scan_exclude`
   have no overlap, but the plan should say this is accepted, not leave it undiscussed.
4. **Part 2's `failure_class: "timeout"` target field does not exist where the spec's Decision
   text puts it, and the top-level field it might be confused with has an incompatible,
   explicitly documented meaning** (§2, §5.7). The plan MUST choose one of: (a) a new optional
   key inside the `tests` object (requires a `schemas/job_result.schema.json` change to
   `tests.properties`, which `tests/test-engine-c-contract.sh` will then correctly validate),
   or (b) an explicit, stated decision to set the top-level `failure_class` and accept that this
   arms the retry-the-whole-job policy for a slow-but-passing suite. Silently doing neither, or
   doing (b) without saying so, is not acceptable.
5. **The "receipt note" (`timeout after N s: <checker>`) has no current path from
   `run_test_floor`'s `reasons` list into any job_result field** (§2, §5.5) —
   `compound-v-emit-workflow.py:_tests_block_from_floor` must be extended to read
   `floor.get("reasons")` (or an equivalent new signal) for this note to exist anywhere a
   reviewer or the dispatcher can see it.
6. **`timeout_s` must be threaded through every hop in the §2 table, not just `tc_validate`, if
   it is meant to change behaviour on the external-worker dispatch path** — specifically
   `resolve_test_commands` (copy `contract.get("timeout_s")` into `slice_`), `tc_run` in all
   five worker scripts (read `.timeout_s` from the contract file and prefer it over
   `--test-timeout-sec` when present), and `agents/parallel-dispatcher.md`'s own invocation
   template (currently hardcodes `[--test-timeout-sec 900]`). If the plan intends `timeout_s` to
   govern **only** the Engine C `test-floor` path and considers the worker-script path
   out of scope for this release, it must say so explicitly rather than leave `tc_validate`'s
   widening as an implied (but unmet) promise of end-to-end effect.
7. **`_cmd_test_floor` (`compound-v-fastpath-run.py:1579-1607`) is the exact, missing wiring
   point for Engine C's own path** — it must pass `test_timeout_s=slice_.get("timeout_s",
   TEST_TIMEOUT_S)` into `run_test_floor` at its call site (`:1602-1603`). The plan's own text
   names a function called `run_tests`, which does not exist in this file; the real target is
   `run_test_floor`, called from `_cmd_test_floor`.
8. **The interaction between a larger `timeout_s` and the harness's documented 600 s foreground
   ceiling (`agents/parallel-dispatcher.md:156-160`) must be addressed explicitly** — at minimum
   the plan must state whether a `timeout_s` above the safe foreground margin forces (or should
   be documented as requiring) the background dispatch path, since exceeding the ceiling
   reproduces an *undiagnosable* version of the exact symptom finding 102 already made
   diagnosable.
9. **`schemas/job_result.schema.json`'s top-level `failure_class` enum already contains
   `"timeout"`** (`:78`) — the spec's own conditional file list ("schemas/job_result.schema.json
   if failure_class lacks timeout") resolves to **no change needed there**; the schema work, if
   any, belongs to the `tests` sub-object per constraint 4, not to widening an enum that is
   already correct.
10. **`compound-v-validate-manifest.py`'s `timeout_s` bound (positive integer ≤ 3600, refusing
    0/negative/non-integer) should mirror the existing `floor_command`/`full_command` type-check
    style at `:2253-2257`** (a per-key `isinstance`/range check appended to
    `_validate_test_contract`, not a new validation subsystem) — this is confirmed as the
    established pattern in this file, not a new one to invent.

---

## 8. File Touch Map

| File | Touch | Notes |
|---|---|---|
| `scripts/compound-v-localize.py` | edit | `_classify_paths` gains the `content_scan_excluded` gate before the read (§7.1); selftest gains a NEW taxonomy fixture with an explicit `content_scan_exclude`, not a rewrite of `_SHARED_TOKEN_TAXONOMY`-based cases (§7.2). |
| `scripts/compound-v-taxonomy.py` | none expected | `content_scan_excluded()` already exists and is reused as-is (§3a) — not a planned touch, listed here only because it is the function Part 1 calls into. |
| `scripts/compound-v-preeval.py` | none expected for Part 1 | `_IMPACT_RAISING_FLAGS`/`_content_raises_impact`/the T3-demotion branch are all unchanged; they simply see the flag less often. Confirm no plan drift adds an unneeded touch here. |
| `scripts/compound-v-fastpath-run.py` | major edit | `resolve_test_commands`/`resolve_from_manifest` gain `timeout_s` pass-through into `slice_` (§7.6); `_cmd_test_floor` gains the missing `test_timeout_s=` kwarg at its `run_test_floor` call (§7.7); `TEST_TIMEOUT_S` raised 300→600. **SHARED RESOURCE** — this is the single producer of the resolved test-contract slice every worker and Engine C's own `test-floor` path consumes; also touched by v3.4.1's still-fresh `impacted+referencing` logic, so this file is a repeat-contention point across features. |
| `scripts/compound-v-validate-manifest.py` | edit | `TEST_CONTRACT_ALLOWED_KEYS += ("timeout_s",)`; `_validate_test_contract` gains the range check (§7.10). |
| `scripts/compound-v-emit-workflow.py` | edit | `_tests_block_from_floor` gains a read of `floor.get("reasons")` (or equivalent) to surface the timeout note (§7.5) — **not mentioned in the plan's file list**, and required for the "receipt note" half of Part 2's stated goal to exist anywhere. **SHARED RESOURCE** — this is Engine C's own emitter; its 77-assertion selftest plus `tests/test-engine-c-contract.sh` both gate it. |
| `scripts/compound-v-run-codex-worker.sh`, `-antigravity-`, `-cursor-`, `-devin-`, `-opencode-worker.sh` | edit (scope depends on §7.6 decision) | `tc_validate` widened to accept `timeout_s` in all five, byte-identical (§3e). `tc_run` additionally needs to read and apply it **only if** the plan commits to the external-worker path being in scope (§7.6) — otherwise these five stay `tc_validate`-only. **SHARED RESOURCE** — explicitly documented in-file as "byte-identical... fix in all five, or in none." |
| `agents/parallel-dispatcher.md` | edit (if §7.6's external-worker scope is in) | Its own invocation template (`:171-174`) hardcodes `[--test-timeout-sec 900]`; needs to show deriving the flag from `test_contract.timeout_s` when declared, for the external path to actually honor the new key. **Not in the plan's current file list.** |
| `schemas/job_result.schema.json` | edit (if §7.4 chooses option (a)) | New optional key inside `tests` (e.g. a timeout-note or a `tests`-scoped failure signal), plus its `additionalProperties: false` set — **not** the top-level `failure_class` enum, which already has `"timeout"` (§7.9). Guarded by `tests/test-engine-c-contract.sh`. |
| `tests/test-engine-c-contract.sh` | run, not necessarily edited | The existing schema-conformance gate for Engine C's `job_result`; must be run against any change touching `_tests_block_from_floor` or the `tests` schema (§5.6). |
| `tests/v2.9-e2e/test_fastpath_and_escalation.py` | edit | Named in the plan's Task B; not read in this pass — confirm it doesn't hardcode `TEST_TIMEOUT_S=300` or a fan-out/timeout assumption Part 2 would break. |
| `skills/compound-v/execution-manifest.md` | edit | Document `test_contract.timeout_s` (default 600, ≤3600, per-checker) and, if §7.6's external-worker scope is in, that it governs the worker-script path too. |
| `CHANGELOG.md` | edit | `[Unreleased]` is currently **empty** (confirmed — the sibling audit's earlier caution about an unrelated already-shipped entry no longer applies; that content shipped as `[3.4.5]`). Clean slate for Task C. |
| `docs/superpowers/pre-eval/2026-09-03T113149Z-...-0cb5.*` (existing, not to be edited) | read-only reference | This run's own live pre-eval record and localization artifact — the "self-referential proof" cited in Step 0 and §1a; do not treat as a file this feature touches, only as evidence already on disk. |
