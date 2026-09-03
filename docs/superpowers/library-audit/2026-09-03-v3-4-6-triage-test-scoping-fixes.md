# Library & Documentation Audit — v3.4.6 triage/test-scoping fixes

**Spec:** `docs/superpowers/specs/2026-09-03-v3.4.6-triage-test-scoping-fixes-design.md`
**Topic slug:** `v3-4-6-triage-test-scoping-fixes`
**Date:** 2026-09-03 · **Phase:** 1C (library/doc currency only — not code archaeology, not domain/regulatory)

## 0. V-memory recall (Step 0)

Five `compound-v-memory.py search` calls ran before opening any file (`--intent planning --top 6-8`):
`"triage test scoping fixes stage 5a"`, `"content_scan_incomplete t1_from_broad_glob taxonomy exclude"`,
`"test_contract timeout_s full_command TEST_TIMEOUT_S"`, `"PyYAML jsonschema Context7 library audit
knowledge base"`, `"bash 3.2 macOS default shellcheck workers"`, plus four follow-ups once the touched
files were known (`"Python 3.9 end of life…"`, `"jq 1.7 jqlang…"`, `"PyYAML soft-import fallback…"`,
`"TEST_TIMEOUT_S 300 600 codex exec timeout…"`).

Relevant recalled evidence, treated as evidence-with-citation, not re-derived:

- **A plan already exists**: `docs/superpowers/plans/2026-09-03-v3.4.6-triage-test-scoping-fixes.md`. Its
  own Architecture line states *"Stdlib only, Python 3.9 floor, bash 3.2 for the workers"* — the plan
  writer already knows the floor. This audit verifies that floor is still accurate and finds the specific
  traps a plan-writer's summary line can't warn against.
- `docs/superpowers/library-audit/2026-09-03-v3-4-5-recall-freshness.md` — the immediately-prior Phase 1C
  audit on this same repo, same day, same shape (stdlib-only spec, zero new libraries). Its Python-3.9-EOL
  finding and its "don't reach for a newer stdlib API while you're in the neighborhood" pattern are
  directly reusable here, cited rather than re-derived (§5).
- `docs/superpowers/library-audit/_knowledge-base/python-tooling.md` — live-confirmed (2026-09-03, today,
  same repo) Python 3.9 EOL date and PyYAML 6.0.3 health check. Both cited verbatim below (§2) rather than
  re-searched, since they were verified *today* against the same registries I would otherwise query.
- `docs/superpowers/library-audit/_knowledge-base/posix-shell-tooling.md` — live-confirmed bash-3.2.57
  macOS floor, with the precise framing this audit reuses: "frozen there by Apple's licensing stance, not
  'abandoned' in the deprecation sense." Directly relevant to Task B's five worker-script edits (§2, §7).
- `docs/superpowers/library-audit/2026-09-02-preflight-workflow-probe.md` — live-confirmed (yesterday) `jq`
  status: current **1.8.2**, this machine's **1.7.1**, unpinned/undeclared minimum version, and a specific
  jq-1.8.0 binding-syntax breaking change already characterized as not affecting this repo's filters. Task
  B extends exactly the jq filter family that finding was written about (§2, §3, §6).
- `docs/superpowers/library-audit/2026-09-02-v3-4-native-first.md` — a pre-existing 🟡 finding that
  `compound-v-emit-workflow.py::_load_yaml()` hard-`raise SystemExit`s on missing PyYAML, unlike every
  other YAML call site in the repo. `compound-v-emit-workflow.py` is one of Task B's own files (§6, §7).
- `docs/superpowers/recon/2026-09-01-v3.0-triage-tests-orchestration.md` — the closest-matching Trigger 0
  recon by topic (no exact path was handed to me; located by V-memory/topic-slug match, per the
  fallback rule). Read in full (§1). It carries **zero** library/tooling claims — every VERIFIED FACT in
  it is architecture/mechanism ("the sizing engine has no caller", "Workflow cannot be launched from a
  subagent"), squarely Phase 1A/plan territory, not Phase 1C's. It also predates five months and several
  shipped stages (v3.4.1 through v3.4.5) of exactly this triage/test-scoping subsystem — treating its
  2026-09-01 snapshot as current status today would itself be a staleness error, so nothing from it is
  revalidated as a library claim below; noted, not used.

No recalled document contradicts anything this audit finds. Where a KB entry is same-day (PyYAML, bash
3.2, Python 3.9 EOL — all dated 2026-09-03 or 2026-09-02, verified in this same repository), it is cited
directly rather than re-queried against the same live sources a second time within 24 hours.

## 1. Tools Available

- **Context7 MCP: ❌ NOT AVAILABLE this session.** `ToolSearch` for `context7`, `resolve-library-id`, and
  `query-docs` (covering both the plugin-bundled and plain tool-name forms) returned no matches; a broad
  `mcp` sweep surfaced only generic `ListMcpResourcesTool`/`ReadMcpResourceTool`/`WebFetch`, no Context7
  server. **DEGRADED: WebSearch-only for any *new* lookup.** In practice no new lookup was needed — every
  external-tool claim below (Python EOL, jq version, PyYAML health) was already live-verified *today or
  yesterday* by prior Phase 1C runs in this same repo (§0), so this audit cites those instead of
  re-querying WebSearch for facts less than 24 hours old against the same registries.
- **Dependency manifests found: NONE.** `Glob` for `package.json`, `requirements*.txt`, `pyproject.toml`
  at repo root: zero matches, confirmed directly (not assumed). Expected: this plugin ships no
  application runtime, and its own documented policy (`CONVENTIONS.md`, "Python: stdlib only") is stdlib
  Python + POSIX bash for all helper scripts.
- **Trigger 0 recon doc:** no exact path was handed to me by the caller. Fallback: V-memory/topic-slug
  scan of `docs/superpowers/recon/` located `2026-09-01-v3.0-triage-tests-orchestration.md` as the
  closest topical match. Read in full — see §0 for why nothing in it is a library-currency claim, and why
  its 2026-09-01 architecture snapshot is not treated as current (five shipped stages sit between it and
  this spec).

## 2. Libraries Mentioned

The spec's own text (`docs/superpowers/specs/2026-09-03-v3.4.6-triage-test-scoping-fixes-design.md`)
names **zero** third-party libraries, SDKs, or external APIs — confirmed by direct read (33 lines, two
parts, no library name anywhere). Its own plan states the dependency floor explicitly ("Stdlib only,
Python 3.9 floor, bash 3.2 for the workers"). Import-level confirmation, done directly rather than taken
on the plan's word: `grep '^import \|^from '` over all four touched Python files
(`compound-v-localize.py`, `compound-v-fastpath-run.py`, `compound-v-validate-manifest.py`,
`compound-v-emit-workflow.py`) returns only stdlib modules — `argparse, json, os, re, sys, datetime,
fnmatch, hashlib, shlex, shutil, subprocess, tempfile, select, time`. **Zero new imports would be needed
by the changes as described.**

The table below is the dependency surface a library-currency check actually applies to here: the
interpreter/shell floor the new code must run under, plus the two non-stdlib tools the *existing* code in
these exact files already leans on (PyYAML, jq) — not newly introduced by this spec, but directly adjacent
to the lines Task A/B touch, so worth confirming are still what the plan assumes.

| Name | Spec context | Current stable | Repo-targeted floor | Last release / status | Maintenance | Status |
|---|---|---|---|---|---|---|
| CPython (interpreter) | shebang of every touched `.py` file; plan's own "Python 3.9 floor" | **3.14.7** (2026-08-05); 3.15.0rc2 cut 2026-09-01 | **3.9** — `.github/workflows/validate.yml:283,346` (`actions/setup-python@v5`, `python-version: '3.9'`), the exact job that runs the `--selftest` sweep this spec's AC depends on | **3.9.25** (2025-10-14) — final release, EOL 2025-10-31 | frozen forever, no further releases possible | 🟠 HIGH — pre-existing, not introduced (§7) |
| bash (shell, worker scripts) | Task B edits `tc_validate` in all five `compound-v-run-*-worker.sh` | GNU bash **5.2.x** upstream, actively developed | **3.2.57** — macOS stock `/bin/bash` (`hooks/lane-guard.sh:19` and every worker's own header comment) | 2007, GPLv2 — Apple has shipped this exact build unchanged since, "frozen there by Apple's licensing stance, not 'abandoned' in the deprecation sense" (`_knowledge-base/posix-shell-tooling.md`) | upstream bash is actively maintained; **the shipped copy is permanently frozen by policy, not decay** | 🟡 frozen-by-design, distinct from abandonment (§7) |
| `jq` (CLI, worker scripts' `--test-contract-file` parsing) | Task B: "Every `tc_validate`: allow the `timeout_s` key" — extends the exact jq filters this spans | **1.8.2** (2026-06-20) | unpinned/undeclared anywhere in this repo; this machine carries 1.7.1 | active (1.8.1 fixed a CVE 2025-06) | active | 🟡 MEDIUM — pre-existing gap (undeclared min version), not introduced (§6) |
| PyYAML | not touched by Task A/B's *specific* edits, but `compound-v-validate-manifest.py` (owns the repo's one canonical `import yaml` site) and `compound-v-emit-workflow.py` (has a second, inconsistently-guarded `_load_yaml()`) are both files Task B opens | **6.0.3**, libraries.io "Sustainable", not archived | soft-import with stdlib `_mini_yaml` fallback (canonical site: `compound-v-validate-manifest.py:205-221`) | active | active | 🟢 OK as a library; the *inconsistent guarding* is a separate, pre-existing, already-tracked issue (§6) |
| `argparse`, `subprocess`, `shlex`, `hashlib`, `json`, `os`, `re`, `datetime`, `fnmatch`, `shutil`, `tempfile`, `select`, `time` (stdlib) | every touched file | tracks CPython | 3.9 floor (above) | stdlib, ships with interpreter | stable | 🟢 OK — no signature drift found in any call this spec's description implies (§3) |

## 3. API Signatures Verified

| Call / idiom | Where it's used or extended | Verified against | Result |
|---|---|---|---|
| `isinstance(v, int) and not isinstance(v, bool)` guard pattern | `_validate_test_contract` is the exact function Task B extends for `timeout_s`; the same file already uses this guard at **five** other sites (`compound-v-validate-manifest.py:999, 1344, 1346, 1352, 2362, 2554`) for other integer-typed manifest fields | Read directly, all six sites, in this file | **Confirmed established convention.** Python's `bool` is a subclass of `int`, so a naive `isinstance(v, int)` check silently accepts `timeout_s: true` as `1`. This file already defends against that everywhere else it validates an integer field. The new `timeout_s` check MUST follow the same pattern — precedent, not a discovery, but the plan text ("accepts an optional positive integer... refuses 0, negatives, non-integers") does not itself say "and not a bool", so it is worth being explicit (§7). |
| `_scalar()` (fallback YAML parser's plain-scalar coercion, `compound-v-validate-manifest.py:258-277`) vs `yaml.safe_load` | The manifest's new `test_contract.timeout_s: 600` must parse to the same Python type under **both** YAML backends this repo supports | Read `_scalar()` directly: `re.match(r"^-?\d+$", tok)` → `int(tok)` | **Confirmed parity.** `timeout_s: 600` and `timeout_s: 0` both parse to Python `int` under PyYAML's `safe_load` and under the stdlib `_mini_yaml` fallback alike — no behavioral fork between the two YAML paths for this new field. |
| jq `has()` / `type ==` / simple comparison idioms (existing `tc_validate` predicate, `compound-v-run-codex-worker.sh:127-137`) | Task B: extend this predicate's key-whitelist and add a `timeout_s` numeric/positive check, across all five worker scripts | jq 1.8.0's documented breaking change to `as`-binding semantics (`[-1 as $x \| 1,$x]` now yields `[1,-1]`), already characterized against this repo's filters in `2026-09-02-preflight-workflow-probe.md` §🟡-4: *"The repo's filters use `--arg` and simple field access, so nothing here is affected."* | **Extends to the new predicate.** The existing filter's one `as` binding (`.scope as $s \| [...] \| index($s) != null`) binds a single scalar to a single-output body — not the multi-value-generator shape the 1.8.0 change affects. A `timeout_s` check written in the same `has()`/`type ==`/comparison idiom (no new `as \|` generator binding) carries the same "unaffected" conclusion. **Caveat, stated plainly: this is a source-level read against the documented breaking change, not a live jq execution** — this session has no shell access to run `jq` itself; if the implementer introduces any `as`-binding shape beyond the existing one, re-verify live rather than trust this inference. |
| `sqlite3.connect(path, autocommit=False)` / any 3.10+-only syntax (`X \| None` union-type hints, `match` statements, `tomllib`) | None of Task A/B's four touched `.py` files carries `from __future__ import annotations`; none currently uses `typing.Optional[...]` or bare-union type hints anywhere (`grep` for both patterns: zero matches in all three files touched by Task A/B) | Direct source read | **Signature not to introduce.** `timeout_s: int \| None = None` as a real (non-string, non-deferred) annotation would evaluate `int \| None` at `def`-time, which raises on the repo's Python-3.9 floor (`TypeError: unsupported operand type(s) for \|`) — 3.10+ only. The file's own style (bare untyped params, `isinstance()` checks in the body) is the safe form to match; `typing.Optional[int]` would also be 3.9-safe if a hint is wanted, but nothing in these files uses even that. |
| `schemas/job_result.schema.json`'s `failure_class` enum | Spec Part 2, literally: *"schemas/job_result.schema.json **if** failure_class lacks timeout"* | Read the schema file directly, `properties.failure_class.enum` | **Conditional resolves to false — no edit needed.** `"timeout"` is already present in the enum (alongside `null, "none", "out_of_credits", "rate_limited", "overloaded", "auth", "context_length", "network", "other"`). The plan already correctly omits this file from Task B's write list — this confirms that omission is correct, not an oversight (§7). |

## 4. Critical Findings 🔴

None. No deprecated, archived, or 24+-month-dead dependency is in play, and this spec introduces no new
third-party library at all.

## 5. High-Priority Findings 🟠

### 🟠-1 — The Python-3.9 CI floor this spec's own `--selftest` acceptance criteria run under is upstream end-of-life, permanently frozen at 3.9.25.

Not new, not introduced by this spec — carried forward verbatim from `2026-09-03-v3-4-5-recall-freshness.md`'s §5 finding, re-confirmed to apply equally here: `.github/workflows/validate.yml:280-312`'s dynamic `scripts/*.py --selftest` sweep runs under `python-version: '3.9'`, and all four of this spec's touched scripts (`compound-v-localize.py`, `compound-v-fastpath-run.py`, `compound-v-validate-manifest.py`, `compound-v-emit-workflow.py`) carry `--selftest` and are swept by it. Python 3.9 reached end-of-life **2025-10-31**; 3.9.25 was final. No forward patch cushion exists — any 3.10+-only construct that happens to work on a contributor's newer local interpreter will pass locally and fail this exact CI job (or worse, only fail on a stock-macOS 3.9.6 contributor box outside CI). See §3's "signature not to introduce" for the concrete trap this spec's own new field (`timeout_s`, an "optional positive integer") makes newly tempting. No alternative library recommendation applies — this is an interpreter floor, not a swappable dependency; a floor bump is a standalone, repo-wide decision, explicitly out of scope for a fix-per-cycle change (open item, §8).

## 6. Medium Findings 🟡

### 🟡-1 — `jq` remains an unpinned, undeclared dependency one minor behind current, and Task B deepens exactly the filter family already flagged for it.

Carried forward from `2026-09-02-preflight-workflow-probe.md` §🟡-4 (one day old, re-confirmed applicable, not re-derived): current jq is **1.8.2** (2026-06-20), this development machine has **1.7.1**, and no file in this repo declares a minimum jq version. That audit already concluded the repo's existing jq filters (simple `--arg`/field-access/`has()` idioms) are unaffected by jq 1.8.0's breaking `as`-binding semantics change. Task B's `timeout_s` addition to `tc_validate` in all five `compound-v-run-*-worker.sh` extends precisely this filter family — §3 verifies (by source read, not live execution — no shell access this session) that the natural way to write the new check keeps the same unaffected shape. Not a blocker; worth keeping in the same idiom deliberately, not by accident.

### 🟡-2 — `compound-v-emit-workflow.py`, one of Task B's own files, contains a pre-existing, already-tracked PyYAML inconsistency that this spec's edit does not touch but sits directly next to.

Carried forward from `2026-09-02-v3-4-native-first.md` §🟡-1 (not re-derived): `_load_yaml()` at `compound-v-emit-workflow.py:181-187` hard-`raise SystemExit("PyYAML is required...")` on missing PyYAML, unlike the file's other three YAML call sites (which degrade to `have_yaml = False`) and unlike the canonical fallback-safe `load_yaml()` this repo otherwise standardizes on (`compound-v-validate-manifest.py:205-221`, confirmed §3). Task B's actual edit — passing `timeout_s` through the per-job `test_contract_file` JSON slice — does not call `_load_yaml()` at all (that slice is JSON, not YAML), so this is not a regression this spec causes. Flagged because it is exactly the kind of pre-existing rough edge a "while I'm in this file anyway" instinct could reach for; the standing "fix per cycle, no over-engineering" directive says don't (§7, §8).

### 🟡-3 — KB self-correction: `scripts/compound-v-*.sh` (including all five workers Task B edits) IS shellcheck-linted by CI today, contradicting a same-day KB claim to the contrary.

`_knowledge-base/posix-shell-tooling.md`'s `epic-vi-review-index` entry (dated 2026-09-03, the *same day* as this audit) states: *"This repo's CI shellcheck step only covers `hooks/*.sh` ... `scripts/*.sh` is not linted by CI at all as of 2026-09-03."* Direct read of `.github/workflows/validate.yml:227-230`, done for this audit, right now: `shellcheck hooks/*.sh scripts/compound-v-*.sh` — the glob **does** cover `scripts/compound-v-*.sh`, which matches all five files (`compound-v-run-codex-worker.sh`, `-antigravity-worker.sh`, `-cursor-worker.sh`, `-opencode-worker.sh`, `-devin-worker.sh`) Task B's plan lists as "shellcheck clean on the five workers." This is a real disagreement between recalled prose and the code as it stands right now, not a rounding difference — per the standing rule, **the code wins**, and the KB entry is corrected below (§9) rather than repeated. Practical effect for this spec, and it is *good* news for Task B: the "shellcheck clean" line item in the plan's own acceptance criteria already has a standing CI regression guard on exactly these five files — no separate follow-up is needed to get one. (This doesn't change §7's separate point that shellcheck does not check bash-*version* compatibility — it only confirms these files' shellcheck *lint* step, whatever it catches, does run in CI.)

## 7. Design Constraints for the Plan (MUST / MUST NOT)

- **MUST** keep every line Task A/B adds Python-3.9-compatible: no `X | None` / PEP 604 union-type hints, no `match` statements, no `tomllib`, no other 3.10+-only stdlib surface — none of the four touched files carries `from __future__ import annotations`, so such a hint is evaluated eagerly and breaks import outright on the CI floor (§3, §5).
- **MUST** validate `timeout_s` with the file's own established `isinstance(v, int) and not isinstance(v, bool)` pattern (`compound-v-validate-manifest.py:999,1344,1346,1352,2362,2554`), not a bare `isinstance(v, int)` — otherwise `timeout_s: true` silently validates as `1` (§3).
- **MUST NOT** edit `schemas/job_result.schema.json` for this spec. `failure_class`'s enum already includes `"timeout"` — the spec's own "if failure_class lacks timeout" conditional is false, confirmed by direct read. The plan already omits this file from Task B's write list; keep it that way (§3).
- **MUST** keep the five worker-script `tc_validate` jq-predicate edits in the same `has()` / `type ==` / plain-comparison idiom the existing predicate already uses — no new `as $x |` multi-value-generator binding — since jq is unpinned in this repo (current 1.8.2, this machine 1.7.1) and that exact construct is where 1.8.0 changed behavior (§3, §6).
- **MUST NOT** widen Task B into "also fix `_load_yaml()`'s missing PyYAML fallback" in `compound-v-emit-workflow.py` — real, but pre-existing, already tracked (§6), and out of scope for a fix-per-cycle change touching this file for an unrelated reason.
- **MUST** keep all five `compound-v-run-*-worker.sh` edits bash-3.2-syntax-safe (macOS stock `/bin/bash` 3.2.57 — no `declare -A`, `mapfile`/`readarray`, `declare -n`, `${var,,}`/`${var^^}`) — pre-existing repo floor, re-confirmed current via `_knowledge-base/posix-shell-tooling.md`, and **do not** treat a green `shellcheck` run as proof of this; shellcheck does not enforce bash-3.2 compatibility (same KB entry).
- **MUST NOT** introduce a new third-party import anywhere in Task A or Task B — confirmed the changes as described need none (§2); if an implementer reaches for one anyway, that is itself a scope violation of this spec's own "stdlib only" architecture line.

## 8. Open Questions for the Human

1. **Scope ambiguity in `timeout_s`'s actual reach, not resolvable from the spec text alone.** The spec's Part 2 decision says, literally, *"Every external worker's `tc_validate` accepts the new key"* — validation only. Separately, each `compound-v-run-*-worker.sh` already has its own independent `--test-timeout-sec` flag (default 900s, `compound-v-run-codex-worker.sh:259`) that actually governs the supervisor timeout its `tc_run` uses (line 184). As written, a manifest author who sets `test_contract.timeout_s: 120` would get that value *accepted* by every worker's validator but not necessarily *applied* by the bash-executed backends, which would keep running under their own unrelated 900s default unless Task B is also meant to wire `timeout_s` into `--test-timeout-sec`. This reads like a real gap between the field's implied contract and its literal spec text, but resolving it is a scoping decision (validate-only this cycle vs. wire-through now), not a library-currency call — flagging for the human/plan-writer rather than assuming either answer.
2. **Not blocking, deferred by design:** is there appetite for a standalone future ticket to move the CI Python floor off 3.9 (permanently EOL, §5)? Not recommended for folding into v3.4.6 — same conclusion as the immediately-prior v3.4.5 audit reached, restated here because it applies to this spec's touched files too.
3. No open question blocks v3.4.6 itself. Zero new libraries are introduced, and every stdlib/tool call surface this spec's description implies was checked against current docs or this repo's own same-day/prior-day live-verified findings with no unresolved signature drift.

## 9. Knowledge Base Updates

No new topic-slug KB file created. This spec's dependency surface (CPython 3.9 floor, bash 3.2 floor, jq,
PyYAML) is already owned by three existing KB files, each of which received a dated addendum:

- **`_knowledge-base/python-tooling.md`** — appended a 2026-09-03 note cross-referencing this run: confirms
  the file's own `isinstance(v, int) and not isinstance(v, bool)` convention (five prior sites) as the
  established pattern for any *new* integer manifest field, using `timeout_s` as the worked example, so a
  future Phase 1C/1A pass validating another integer field doesn't have to re-derive the citation list.
- **`_knowledge-base/posix-shell-tooling.md`** — two changes: (1) appended a 2026-09-03 note recording
  that `compound-v-run-*-worker.sh`'s `tc_validate` jq predicates were re-examined against the jq-1.8.0
  binding-syntax change and found unaffected (source-read only, not live-executed — flagged as such), for
  reuse the next time any of the five worker scripts' jq filters are touched; (2) **struck through**
  (never deleted) the `epic-vi-review-index` entry's claim that `scripts/*.sh` is not CI-shellcheck-linted
  — direct re-read of `validate.yml:227-230` today shows `scripts/compound-v-*.sh` IS covered and always
  was on that line — with a `→ corrected 2026-09-03` note explaining the miss and what's still true (§6,
  🟡-3).
- **No new PyYAML entry** — `2026-09-02-v3-4-native-first.md`'s `_load_yaml()` finding and
  `2026-09-03-epic-vi-readme-section.md`'s PyYAML-health entry already cover everything this run touched;
  this run adds no new PyYAML fact, only confirms neither prior finding is contradicted or extended by
  v3.4.6's actual edit (§6).

No jq-specific KB file exists yet in `_knowledge-base/` (its two mentions so far live inside dated
`posix-shell-tooling.md` and per-run audit files) — not created here either, since this run's jq content
is a re-confirmation of yesterday's finding, not new information warranting its own bucket.
