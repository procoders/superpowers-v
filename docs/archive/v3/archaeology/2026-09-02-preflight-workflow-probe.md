# Pre-flight Workflow Probe — Code Archaeology

**Spec audited:** `docs/superpowers/specs/2026-09-02-preflight-workflow-probe.md`
**Repo:** `/Users/oleg/Dev/superpowers-v` @ `v3.0-dogfood-collector-tests` (plugin 3.3.4)
**Knowledge base:** `docs/superpowers/archaeology/_knowledge-base/` — **empty**. No prior
archaeology audit touches the dashboard/hook subsystem; the ten existing audits cover
workers, onboarding, pre-evaluation, blockers, preferences, co-change. Nothing to inherit.

---

## 0. Headline: the spec proposes work that already shipped

The spec's change is: *add a `--json` flag to `scripts/compound-v-dashboard.py resume`*.

**That flag exists.** `scripts/compound-v-dashboard.py:1552`:

```python
p_resume.add_argument("--json", dest="as_json", action="store_true",
                      help="machine-readable output")
```

It has shipped since **commit `61b7ba9` (2026-08-30, v2.19)** — `git blame -L 1552,1554`
attributes both lines to that commit. It is implemented at `cmd_resume`
(`scripts/compound-v-dashboard.py:1505-1516`), documented in `CHANGELOG.md:535` and
`commands/v-status.md:132`, and **already consumed in production** by
`hooks/postcompact-resume.sh:222`.

Verified by execution, not by reading:

```
$ python3 scripts/compound-v-dashboard.py resume --json
{ "active": [ { "age_hours": 16.82…, "display_ts": "2026-09-01T17:13:20Z",
               "done": 16, "id": "2026-09-01-v3.0-triage-tests-orchestration",
               "kind": "run", "status": "COLLECTED", "total": 18 } ] }
```

Every downstream section of this audit is therefore about the **gap between what the spec
says the code does and what the code does** — which is where the real, plannable work is.

---

## 1. Matrix

`cmd_resume` branches on two dimensions; `active_records` filters on three more. All
combinations enumerated, all executed against real and synthetic roots.

| # | `--json` | root exists | records | stdout | bytes | rc | Existing code handles? |
|---|----------|-------------|---------|--------|-------|----|------------------------|
| 1 | no  | yes | ≥1 | rendered banner line | 317 (live repo) | 0 | ✅ all 3 hooks |
| 2 | no  | yes | 0  | **nothing** | **0** | 0 | ✅ silence is the signal |
| 3 | no  | no  | —  | **nothing** | **0** | 0 | ✅ indistinguishable from #2 |
| 4 | yes | yes | ≥1 | `{"active":[…]}` pretty-printed | 4 lines/record | 0 | ✅ postcompact only |
| 5 | yes | yes | 0  | `{"active": []}` | **19** | 0 | ⚠ **never empty** |
| 6 | yes | no  | —  | `{"active": []}` | **19** | 0 | ⚠ collapses with #5 |

Sub-dimensions inside a record, all reachable:

| dimension | values | where set | reaches `--json`? |
|---|---|---|---|
| `kind` | `run` \| `epic` | `load_run:295` / `load_epic:387` | yes |
| `status` | phase string \| `NO STATE` \| `UNPARSEABLE` \| `UNKNOWN` | `load_run:361-368`, `load_epic:409-413` | yes |
| `display_ts` | ISO string \| **`None`** | `load_run:371-377`, `load_epic:417-427` | yes, as JSON `null` |
| age | float hours \| **`None`** → record dropped | `_age_hours:1442-1454` | only non-`None` survive |
| `done`/`total` | ints, `total` = union of manifest+state ids | `load_run:344-357` | yes |

**Cell 5 is the trap the spec walks into.** Plain mode's contract is *silence means
nothing to say*. `--json` mode has **no silent state** — it always prints at least 19
bytes. All three consumers gate on non-empty stdout (§2). Cell 5/6 is the only cell that
matters for the spec's stated goal, and it is the one cell that breaks the callers.

Tested cells prior to this audit: **1 and 4 only** (cell 4 by `tests/test-native-points.sh`
indirectly, through the hook, never against the payload).

---

## 2. Shared State

### `args.as_json` — `scripts/compound-v-dashboard.py:1507`
- Set by: `--json` on the `resume` subparser only (`:1552`, `dest="as_json"`).
- **Not defined** on the `emit` or `serve` namespaces. `cmd_resume` is the sole reader, so
  no `AttributeError` today, but any refactor that shares a handler inherits the hazard.
- No `--no-json` inverse, no env override, no config key. `.claude/compound-v.json` has no
  say over it.

### stdout-emptiness — the actual load-bearing variable
This is the variable the spec's change would mutate, and it is read in **three** places,
never declared anywhere:

| consumer | line | guard | consequence if `--json` output were substituted |
|---|---|---|---|
| `hooks/session-banner.sh` | `:43` | `if [ -n "${resume:-}" ]` | **always true** → a 19-byte JSON blob is concatenated into a prose banner on **every** SessionStart in any repo containing `docs/superpowers/execution` |
| `hooks/precompact-snapshot.sh` | `:226` | `[ -n "$line" ] \|\| return 1` | **always true** → a snapshot file is written on every compaction, with `{"active": []}` as its body |
| `hooks/postcompact-resume.sh` | `:217` | `[ -n "$line" ] \|\| return 1` | **always true** → the hook speaks after every compaction, forever |

**Gap:** the empty-string contract is enforced by nothing — not a schema, not a test, not a
comment in `cmd_resume`. It is three independent `[ -n ]` tests in three shell files.

### `line` vs `ids` in `hooks/postcompact-resume.sh` — different points in time
- `line` (`:209-217`): the **PreCompact snapshot** when readable, else a live
  `resume` call.
- `ids` (`:221-225`): **always** a live `resume --json` call, a separate process.

The hook's own comment at `:219-220` claims *"so the two can never disagree about which
runs are active."* **That claim is false**, and by design — the snapshot path deliberately
sources the line from an earlier moment. Proven by probe (§3).

### `records` freshness — correctly hardened, do not regress
`_age_hours` (`:1442-1454`) reads `display_ts` **only**, never `sort_ts`. `sort_ts` is a
file mtime and git rewrites mtimes on clone and branch switch. A record with no recorded
timestamp is **dropped**, not assigned an age. This is the fix v2.19 shipped after a live
probe; `--json` inherits it because it filters through the same `active_records`.

---

## 3. Sibling Code

### `hooks/postcompact-resume.sh` (PostCompact) — the existing `--json` consumer
- **Entry conditions:** `jq` present; stdin parses as JSON *successfully* (`:155-170` —
  an empty-field parse is rejected, because a non-JSON stdin previously made the hook
  answer for `$PWD`); `hook_event_name` empty or `PostCompact`; `cwd` resolves; a `.git`
  ancestor found within 40 levels; `docs/superpowers/execution` is a directory; dashboard
  locatable; python locatable.
- **Reads:** `.hook_event_name`, `.trigger`, `.cwd`, `.session_id`, `.compact_summary`
  (never into a shell variable — `jq` answers `contains($id)` in-process).
- **Edge cases handled:** missing snapshot → live fallback; `_MAX_IDS=4`; plain-text output
  because PostCompact has no `hookSpecificOutput` variant on 2.1.238; `trap 'exit 0' EXIT`.

**LATENT BUG A — the "can never disagree" comment is false.** Probed: snapshot naming
`ghost-run` + a live root with zero unfinished work.

```
$ … resume --execution-root <root> --json      →  {"active": []}
$ … | bash hooks/postcompact-resume.sh
Compound V resume context after compaction (trigger=auto).
⏸ UNFINISHED COMPOUND V WORK: run ghost-run — DISPATCHING, 1/2 jobs done, …
(the compaction summary was not checked for these ids — the id query did not return)
```

The line names a run the id query does not know about. The inverse is equally reachable: a
run that *appears* during compaction is in `ids` but absent from the line.

**LATENT BUG B — the fallback note states a falsehood.** In the probe above the id query
**did** return: rc 0, valid JSON, zero rows. The hook cannot distinguish "query failed"
from "query returned empty" because both collapse to `ids=""` (`:221-225`) and the note branch tests only `[ -z "$ids" ]` (`:242-245`), so it reports
*"the id query did not return."* In a hook whose entire purpose is anti-amnesia honesty,
inside a repo with an explicit anti-ruflo CI gate, this is the wrong error to ship.

### `hooks/precompact-snapshot.sh` (PreCompact) — the plain-mode consumer
- **Entry conditions:** `jq`; parse succeeds; event is exactly `PreCompact`; `session_id`
  non-empty; `cwd` is a directory and resolves via `pwd -P`; project is Compound-V-present
  (`docs/superpowers/` **or** `.claude/compound-v.json`); dashboard resolves **from the
  plugin root only** — a cross-model review correctly called project-first resolution
  CRITICAL (cloning a repo would auto-execute its Python on compaction).
- **Edge cases handled:** `_bounded` 5 s wall clock with TERM→grace→KILL (no `timeout(1)`
  on macOS); prior snapshot `rm -f`'d **before** querying, so a stale snapshot cannot
  outlive its truth; write-to-`.part`-then-`mv` against torn reads.

**LATENT BUG C — documented reader that does not exist.** `:117-118` says the exported
shape exists *"so the readers — postcompact-resume.sh and session-banner.sh — can find
it"*, and `:234-235` emits to the user:

```
systemMessage: "…snapshotted before the <t> compaction — the resume banner will read it back."
```

`hooks/session-banner.sh` contains **no reference to the snapshot** (grep: zero hits for
`snapshot`/`snap-`). Only `postcompact-resume.sh` reads it —
`docs/superpowers/architecture/native-mechanisms.md:147` gets this right
(*"и он же читатель снапшота"*). So the user-visible message names the wrong hook.

### `hooks/session-banner.sh` (SessionStart) — the plain-mode consumer the spec names
- **Entry condition** (`:41`): `python3` on PATH **and** `docs/superpowers/execution` is a
  directory **relative to CWD**.
- **Call site drift from both siblings** (`:42`):

```bash
resume=$(python3 "${CLAUDE_PLUGIN_ROOT:-.}/scripts/compound-v-dashboard.py" resume 2>/dev/null || echo "")
```

| | session-banner | precompact-snapshot | postcompact-resume |
|---|---|---|---|
| `--execution-root` | **omitted** (relative default, CWD-dependent) | explicit | explicit |
| interpreter | bare `python3` | `python3` → `/usr/bin/python3` | `CV_PYTHON` → `python3` → `/usr/bin/python3` |
| wall-clock bound | **none** | `_bounded 5` | none, but `timeout: 10` in hooks.json |
| `hooks.json` timeout | **absent** | `10` | `10` |
| plugin-root pinning | `${CLAUDE_PLUGIN_ROOT:-.}` — falls back to **CWD** | plugin-only (hardened) | plugin-first |

`session-banner.sh` is the **only** resume consumer with no timeout at either layer and the
only one that can fall back to executing `./scripts/compound-v-dashboard.py` from the
current directory. It also runs under `set -euo pipefail`, so the `|| echo ""` is
load-bearing.

- **DRY note:** `hooks/triage-prompt-nudge.sh:53` documents `resume`-prints-nothing as its
  no-active-run condition but does **not** invoke it — no fourth call site.

---

## 4. External APIs

No third-party library is in this path, so Context7 has no authoritative entry to cite;
everything below was verified by local probe instead, which is the stronger evidence here.
(Dependency currency is Phase 1C's lane.)

| API | Version verified | Contract used | Quirks that bind the plan |
|---|---|---|---|
| `argparse` (stdlib) | Python **3.9.6** (`/usr/bin/python3`, the CI floor) and **3.14.7** (PATH) | `add_subparsers(dest="cmd")`, `store_true` with `dest="as_json"` | `--json` exists **only** on the `resume` namespace. `main()` with no subcommand prints help and returns **1**; `--selftest` is checked before subcommand dispatch. |
| `jq` | **1.7.1** | `jq -n --arg`, `jq -r` multi-output, `jq -e … contains($id)` | Hard requirement in all three hooks; each returns early when absent. `contains` is literal substring, not regex — ids with metacharacters are safe. |
| `datetime.fromisoformat` | 3.9 + 3.14 | `_parse_ts:1426` strips a trailing `Z` to `+00:00` by hand | 3.9's parser rejects bare `Z`; the manual rewrite is why it works on the floor. Do not "simplify" it. |

Both interpreters run the `resume` path **clean**: `/usr/bin/python3` (3.9.6) returns
identical JSON, and `python3 -W error::DeprecationWarning` on 3.14.7 produces **empty
stderr** and rc 0. The deprecated `datetime.utcfromtimestamp` at `:262` is confined to
`_fmt_mtime`, the HTML path — it never executes under `resume`.

CI enforces the floor: `.github/workflows/validate.yml:276,345` pin Python **3.9**, sweep
every `scripts/*.py` carrying `--selftest`, and discover every `tests/*.sh`.

---

## 5. Regression Surface

| # | Path | Impact if the resume contract changes |
|---|---|---|
| R1 | `hooks/session-banner.sh:41-46` | Fires on `startup\|clear\|compact` in **every** session. A non-empty-when-idle stdout appends raw JSON to the prose banner for every user, every session, in any repo with an execution dir. Highest blast radius in the repo. |
| R2 | `hooks/precompact-snapshot.sh:226` | An always-non-empty line makes every compaction write a snapshot, including `{"active": []}` — which `postcompact-resume.sh` then reports as the position. |
| R3 | `hooks/postcompact-resume.sh:217,222` | Already parses `--json` with `jq -r '.active[]? \| .id // empty'`. Renaming `active`, `id`, or flattening the envelope silently yields zero ids → the misleading note of Bug B on every compaction. |
| R4 | `tests/test-native-points.sh:498-516` | Asserts snapshot-preferred-over-live and live-fallback by writing with one hook and reading with the other. Any change to line provenance reddens exactly these two checks — which is the intended alarm, not a nuisance. |
| R5 | `scripts/compound-v-dashboard.py --selftest` (`:1351-1399`) | Exercises `active_records` and `format_resume_line`. It does **not** call `cmd_resume`, so a broken `--json` branch passes CI today. |
| R6 | `commands/v-status.md:132`, `CHANGELOG.md:535` | Both already document `--json`. A plan claiming to "add" it contradicts shipped docs and would trip a reviewer. |
| R7 | `_age_hours` / `display_ts` | Any move back to `sort_ts` makes every historical run in a fresh clone look seconds old, in both output modes. Guarded by a named selftest check. |
| R8 | `render_html` / `emit` / `serve` | Share `build_records`. Changes below `active_records` reach the HTML dashboard and the loopback server, including its realpath containment. |

---

## 6. DRY Findings

- **`--json` on `resume`: already written.** `scripts/compound-v-dashboard.py:1552`. Writing
  it again is a duplicate by definition. **Decision: extend/document/test the existing flag;
  do not add a second one.**
- **`build_records` is already the single source of run/epic truth** — `render_html`,
  `cmd_emit`, `cmd_serve`, `active_records` all funnel through it. `_is_unfinished`,
  `DEFAULT_RESUME_MAX_AGE_HOURS` and `format_resume_line` are likewise single-homed, and
  all three hooks correctly call the script rather than re-deriving. **No duplication to
  remove; the discipline is already right and must not be broken.**
- **Other `--json` producers are unrelated surfaces**, not duplicates:
  `compound-v-liveness.py:430` (worker liveness), `compound-v-integration-gate.py:916`
  (gate report), `compound-v-epic-state.py` (epic state ops). None emits an
  unfinished-work list.
- **Genuine duplication that exists on purpose:** `_snapshot_path` /`_digest` /`_store_dir`
  are copied between `precompact-snapshot.sh` and `postcompact-resume.sh`. Both files
  document this as deliberate house style (standalone hooks, no shared library), and
  `tests/test-native-points.sh` asserts agreement behaviourally — write with one, read with
  the other. **Decision: leave it. The test, not a shared file, is the contract.**

---

## 7. Design constraints for the spec

Non-negotiable. Derived from §§1-6, each traceable to a probe or a line number.

1. **The spec's premise is factually wrong and must be rewritten before planning.** `--json`
   exists (`:1552`, commit `61b7ba9`, 2026-08-30) and ships documented. A plan that "adds"
   it fabricates work. Restate the change as what is actually missing: the flag's
   **contract, its coverage, and its two broken consumers**.
2. **The spec's motivation is wrong for all three call sites.** No consumer "parses a
   rendered line." `session-banner.sh:44` concatenates it verbatim; `precompact-snapshot.sh`
   stores it verbatim; `postcompact-resume.sh` prints it verbatim and gets ids from a
   *separate* `--json` call. Any plan justified by "stop parsing the line" is solving a
   non-problem.
3. **Emptiness is the contract, and `--json` does not honour it.** Plain mode: 0 bytes when
   idle. `--json`: 19 bytes, always. Any plan touching `hooks/session-banner.sh:43` or
   `hooks/precompact-snapshot.sh:226` MUST state which sentinel replaces `[ -n ]` — an
   `.active | length` test, an exit code, or leaving those two on plain mode. Unstated =
   a banner that emits JSON to every user on every session start.
4. **`--json` MUST NOT become the default or replace plain output.** `format_resume_line`
   is prose aimed at a model reading a banner; `--json` is 4 lines per record. They are not
   substitutes.
5. **The payload shape MUST be pinned before any consumer is added.** Seven keys —
   `kind, id, status, done, total, age_hours, display_ts` (`:1508-1510`). `display_ts` is
   nullable (`load_run:371-377`); `age_hours` is an unbounded float
   (`0.00014355891280704074` observed); `status` can be `NO STATE`/`UNPARSEABLE`/`UNKNOWN`,
   not just a phase. No schema exists under `schemas/`. Declare it or do not consume it.
6. **`cmd_resume` MUST gain coverage.** The selftest (`:1351-1399`) exercises the library
   functions and never the command. Cells 4, 5 and 6 of §1 are untested. CI will run a new
   check automatically (`validate.yml:297-311`, `:345-369`) — there is no wiring excuse.
7. **Latent Bug A MUST be resolved in the spec, not discovered in review.**
   `postcompact-resume.sh:219-220` asserts line and ids "can never disagree." Probed false.
   Either fix the provenance (derive both from one call) or delete the false claim — but
   the plan must say which, because the snapshot's whole point is that the line is older
   than the disk.
8. **Latent Bug B MUST be fixed or scoped out explicitly.** `ids=""` conflates query
   failure with zero results, so the hook says "the id query did not return" when it
   returned successfully and empty. Distinguish the two exit paths or change the wording.
   This repo gates on not-lying; the hook currently does.
9. **Latent Bug C MUST be fixed or scoped out explicitly.** `precompact-snapshot.sh:117-118`
   and its user-facing `systemMessage` at `:234-235` name `session-banner.sh` as a snapshot
   reader. It is not one. Either wire the banner to the snapshot (a real behaviour change
   with R1's blast radius) or correct both strings.
10. **Freshness provenance is frozen.** `_age_hours` reads `display_ts` only; `sort_ts` is
    an mtime and git rewrites mtimes. A record without a recorded timestamp stays silent.
    Both modes inherit this. No plan may relax it.
11. **`session-banner.sh`'s call-site drift MUST be acknowledged.** It alone omits
    `--execution-root`, ignores `CV_PYTHON`, has no wall-clock bound at either layer, and
    resolves the script through `${CLAUDE_PLUGIN_ROOT:-.}` — a CWD fallback its two
    siblings deliberately removed as a code-execution hazard. Any plan that edits this file
    either fixes the drift or states why it is leaving it.
12. **`--json` cannot distinguish a missing execution root from an empty one** (cells 5 and
    6: both `{"active": []}`, rc 0). If a consumer needs "Compound V is not set up here"
    versus "nothing is running," the plan must add that signal; today it does not exist.
13. **Python 3.9.6 is the floor and the `Z`-stripping in `_parse_ts:1426` is why it holds.**
    Verified on both 3.9.6 and 3.14.7, clean stderr on both. No f-string/`match`/`|`-union
    syntax; no `datetime.UTC`.
14. **Blast radius ranking for test scoping:** `session-banner.sh` (every session) >
    `postcompact-resume.sh` / `precompact-snapshot.sh` (every compaction) >
    `compound-v-dashboard.py resume` (called by all three). Proportionate scoping does not
    mean skipping R1.

---

## 8. File Touch Map (for Phase 2 partitioning)

| File | Why touched | Flag |
|---|---|---|
| `scripts/compound-v-dashboard.py` | The `--json` branch, its payload contract, and the `_selftest` additions all live here. `_selftest` is one function in the same file as `cmd_resume`. | **SHARED RESOURCE** — read/invoked by 3 hooks + the CI selftest sweep; a single file with a single selftest body, so two jobs editing it will collide. Assign to exactly one lane. |
| `hooks/postcompact-resume.sh` | Bugs A and B; the only existing `--json` consumer. | — |
| `hooks/precompact-snapshot.sh` | Bug C (comment `:117-118` + `systemMessage` `:234-235`). | — |
| `hooks/session-banner.sh` | Constraint 3 (the `[ -n ]` guard) and 11 (call-site drift). | **SHARED RESOURCE** — highest blast radius; also touched by `tests/test-session-banner-staleness.sh`. |
| `tests/test-native-points.sh` | Coverage for provenance and the id-query paths. | **SHARED RESOURCE** — one shared `check` counter and a linear script every hook feature appends to. |
| `tests/test-session-banner-staleness.sh` | Only if the banner's guard or call site changes. | — |
| `commands/v-status.md` | `:132` is the only place the `resume` contract is described for users. | — |
| `docs/superpowers/architecture/native-mechanisms.md` | `:147`, `:165` describe the snapshot reader relationship; correct today, must stay correct. | **SHARED RESOURCE** — generated/curated knowledge base, citation-verified by `/v:onboard`. |
| `CHANGELOG.md` | Release note. | **SHARED RESOURCE** — every job appends to the same top section; serialize. |
| `.claude-plugin/plugin.json` | Version bump from `3.3.4` if released. | **SHARED RESOURCE** — single-line version field, CI-checked for consistency. |
| `hooks/hooks.json` | Only if `SessionStart` gains the `timeout` its siblings have. | **SHARED RESOURCE** — registry file; ordering and the `\|\| true` idioms are load-bearing and test-asserted. |

**Task 0 candidate (serial, before any parallel batch):** pin the `--json` payload contract
in `scripts/compound-v-dashboard.py`. Every other task in this feature reads that shape.
